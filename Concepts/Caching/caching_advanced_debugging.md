# Продвинутая диагностика и отладка Redis

**Актуально для:** Redis 7.x / 8.x, Valkey 8.x

> **Примечание по совместимости:** Valkey 8.x является форком Redis 7.x под лицензией BSD. Все команды диагностики, параметры конфигурации и форматы вывода, описанные в этом документе, совместимы с Valkey 8.x. Различия могут касаться только лицензирования и поддержки модулей.

## Определения

**Event loop (цикл событий)** — центральный механизм Redis, обрабатывающий сетевые события, таймеры и callback-функции в одном потоке. Все команды проходят через event loop, что обеспечивает атомарность без мьютексов.

**Main thread (основной поток)** — последовательно выполняет все команды клиентов, управляет expire-очередью и координирует фоновые задачи. Блокировка main thread на любой операции (KEYS, SMEMBERS, SORT, Lua-скрипты) останавливает обработку всех остальных клиентов.

**I/O threads (потоки ввода-вывода)** — вспомогательные потоки (начиная с Redis 6.0), которые берут на себя чтение из и запись в сокеты. В v8.x добавлены потоки для фоновой дефрагментации и ленивого освобождения, обеспечивая до 2x прироста пропускной способности при сохранении атомарности основного ядра.

**jemalloc** — аллокатор памяти, используемый Redis по умолчанию. Выделяет память блоками (chunks), которые затем делятся на объекты. При несовпадении размеров возникает внешняя фрагментация, компенсируемая `activedefrag`.

**Major page faults** — ситуации, когда Redis запрашивает страницу памяти, которой нет в RAM, и ОС выполняет подкачку с диска. Вызывают задержки в сотни миллисекунд. Minor page faults (страница в Page Cache, но не в RAM процесса) — нормальны и дешевы.

**RDB (Snapshotting)** — механизм персистентности, создающий сжатые снапшоты всей БД. При записи RDB Redis форкает дочерний процесс, что создает нагрузку на copy-on-write и может вызывать latency spikes.

**AOF (Append-Only File)** — журналирование каждой операции записи. В v7.0+ используется Multi-part AOF (базовый файл + инкрементальные обновления). AOF rewrite форкает процесс и может блокировать main thread на короткое время.

**Redis Flex (v8+)** — движок оптимизации фоновых задач, снижающий Tail Latency во время снапшотов за счет интеллектуального планирования I/O.

**Lazy Freeing** — асинхронное освобождение памяти при удалении больших объектов (DEL на ключах > 64 КБ по умолчанию). Позволяет main thread не блокироваться на `free()`.

**Replication lag** — задержка между записью на master и применением той же записи на replica. Измеряется в секундах и критична для консистентности чтения с реплик.

## Архитектура и основные концепции

### Модель выполнения Redis

Redis использует реакторный паттерн (Reactor Pattern):

1. Event loop фиксирует события на сокетах и таймерах.
2. При поступлении запроса I/O thread читает его и ставит в очередь команд.
3. Main thread берет команду из очереди и выполняет атомарно.
4. I/O thread записывает ответ в сокет.

**Последствия для отладки:**
- Любая блокировка main thread блокирует **все** клиенты.
- I/O threads не ускоряют выполнение самих команд, только обработку сетевого I/O.
- Фоновые задачи (expire, replication, RDB, AOF rewrite, defrag) конкурируют за CPU и память с основными операциями.

### Жизненный цикл команды

Каждая команда проходит через этапы:

1. **Парсинг запроса** — I/O thread преобразует байты в объект команды.
2. **Выполнение в main thread** — атомарное исполнение, возможна блокировка.
3. **Запись результата в буфер клиента** — формирование ответа.
4. **Отправка ответа** — I/O thread отправляет байты в сокет.

Блокировка на любом этапе приводит к увеличению latency.

### Блокирующие команды

Команды, блокирующие main thread:

- `KEYS *` / `KEYS user:*` — полное сканирование keyspace
- `SMEMBERS` — загрузка всех элементов set в память
- `SORT` — сортировка больших коллекций
- `FLUSHALL` / `FLUSHDB` — полная очистка
- `BGSAVE` / `BGREWRITEAOF` — форк дочернего процесса (блокирует на миллисекунды)
- `DEBUG RELOAD` / `DEBUG SLEEP` — принудительная блокировка
- Сложные Lua-скрипты без `redis.call()` — выполняются атомарно, блокируя main thread на все время исполнения

### Фоновые задачи и их влияние на latency

Redis выполняет фоновые задачи, которые могут влиять на задержки:

- **TTL-очистка:** удаление истекших ключей (частота определяется параметром `hz`, по умолчанию 10 раз в секунду)
- **Активная дефрагментация:** объединение разрозненных страниц памяти в contiguous-блоки
- **Репликация:** отправка изменений репликам, буфер `repl-backlog`
- **Снапшоты:** RDB и Multi-part AOF rewrite (форк процесса, copy-on-write)
- **Lazy Freeing:** асинхронное удаление больших объектов
- **Redis Flex (v8+):** планировщик фоновых задач, снижающий пиковые задержки

## Практические сценарии

### Анализ медленных команд

**Включение slow log:**

```bash
# Установить порог задержки (в микросекундах)
redis-cli CONFIG SET slowlog-log-slower-than 10000

# Установить максимальный размер лога
redis-cli CONFIG SET slowlog-max-len 128
```

**Валидация:**

```bash
redis-cli CONFIG GET slowlog-log-slower-than
# → (integer) 10000

redis-cli CONFIG GET slowlog-max-len
# → (integer) 128
```

**Просмотр slow log:**

```bash
# Получить последние 10 записей
redis-cli SLOWLOG GET 10

# Получить общее количество записей
redis-cli SLOWLOG LEN

# Очистить slow log
redis-cli SLOWLOG RESET
```

**Пример вывода:**

```
1) 1) (integer) 1234567890
   2) (integer) 15000
   3) "KEYS"
   4) "*"
   5) "127.0.0.1"
   6) (integer) 1
```

Где:
- 1) — timestamp Unix
- 2) — задержка в микросекундах
- 3) — команда
- 4) — аргументы
- 5) — IP клиента
- 6) — ID клиента

### Измерение latency

```bash
# Однократное измерение
redis-cli --latency

# Периодическое измерение (каждую секунду)
redis-cli --latency-history

# Продвинутый режим (детальная гистограмма)
redis-cli --latency-dist
```

**Пример вывода:**

```
min: 0, max: 1, avg: 0.12 (milliseconds)
```

**Валидация:**

```bash
redis-cli --latency-history | tail -1
# → min: 0, max: 2, avg: 0.15 (milliseconds) — приемлемо для production
```

### Команда LATENCY DOCTOR

`latency doctor` — встроенный инструмент, анализирующий историю latency spikes и выводящий причину:

```bash
redis-cli LATENCY DOCTOR
```

**Пример вывода (иллюстративный):**

```
# Doctor Report (Redis 8.0.0)

* 12 latency spikes occurred in the last 60 seconds.
* Recent latency spike caused by: fork during BGSAVE (child snapshot)
* Advice: Consider using Redis Flex or schedule RDB during off-peak.
* Current active-defrag: yes
* Memory fragmentation ratio: 1.08
* Major page faults: 0
* Slow log entries: 3
```

### Команда LATENCY GRAPH

```bash
redis-cli LATENCY GRAPH command
# → Отображает график latency для каждой команды
```

### Анализ памяти

**Проверка фрагментации:**

```bash
redis-cli INFO memory | grep mem_fragmentation_ratio
# → mem_fragmentation_ratio:1.08 (норма: 1.0-1.5)
```

**Валидация:**

```bash
redis-cli INFO memory | grep -E "used_memory_human|maxmemory_human|mem_fragmentation_ratio"
# → used_memory_human:1.92G
# → maxmemory_human:2.00G
# → mem_fragmentation_ratio:1.05
```

**Детальная информация о памяти:**

```bash
# Размер конкретного ключа
redis-cli MEMORY USAGE user:123
# → 256 (байт)

# Детальная информация о внутреннем представлении (10 выборок)
redis-cli MEMORY USAGE user:123 SAMPLES 10
# → Детальная информация о внутреннем представлении

# Санитар-проверка памяти
redis-cli MEMORY DOCTOR
# → Диагностика проблем с памятью
```

**Пример вывода MEMORY DOCTOR:**

```
[WARNING] Your memory fragmentation ratio is 1.23
[WARNING] You have keys with very large values (user:session:abc123: 5242880 bytes)
[INFO] 12345 keys sampled for Doctor output
```

**Анализ аллокатора:**

```bash
redis-cli MEMORY MALLOC-STATS
# → Статистика jemalloc: allocated, active, resident, mapped
```

### Анализ блокировок

**Проверка блокированных клиентов:**

```bash
redis-cli INFO clients | grep blocked_clients
# → blocked_clients:0

redis-cli CLIENT LIST | grep blocked
# → Показывает заблокированных клиентов (например, BLPOP)
```

**Поиск блокирующих команд:**

```bash
redis-cli SLOWLOG GET 10 | grep -E "KEYS|SMEMBERS|SORT"
```

### Мониторинг в реальном времени

**Информация о сервере:**

```bash
redis-cli INFO server
redis-cli INFO memory
redis-cli INFO stats
redis-cli INFO replication
redis-cli INFO cpu
```

**Пример INFO stats:**

```
instantaneous_ops_per_sec:1234
keyspace_hits:1234567
keyspace_misses:12345
```

**Пример INFO memory:**

```
used_memory_human:1.92G
used_memory_peak_human:2.00G
mem_fragmentation_ratio:1.05
```

### Deep Dive: интерпретация INFO command

`INFO` возвращает секции. Критические поля для отладки:

| Секция | Поле | Что означает | Порог |
| :--- | :--- | :--- | :--- |
| `memory` | `used_memory_human` | RAM, занятая данными + overhead | < 80% maxmemory |
| `memory` | `maxmemory_human` | Лимит памяти | Зависит от хоста |
| `memory` | `mem_fragmentation_ratio` | Отношение RSS к allocator | > 1.5 — проблемная |
| `memory` | `used_memory_peak_human` | Пик потребления | — |
| `stats` | `keyspace_hits` | Попадания в кэш | — |
| `stats` | `keyspace_misses` | Промахи кэша | — |
| `stats` | `evicted_keys` | Вытесненные ключи | Рост > 100/мин |
| `stats` | `major_faults` | Major page faults | > 0 — проблема |
| `clients` | `connected_clients` | Активные соединения | Зависит от maxclients |
| `clients` | `blocked_clients` | Заблокированные (BLPOP и т.д.) | Рост — проблема |
| `cpu` | `used_cpu_sys` | CPU time system | — |
| `cpu` | `used_cpu_user` | CPU time user | — |
| `replication` | `lag` | Задержка репликации (если видна) | > 1 сек — проблема |
| `persistence` | `rdb_last_save_time` | Время последнего RDB | — |
| `persistence` | `aof_delayed_fsync` | Задержки fsync в AOF | > 0 — проблема |

### Анализ репликации

```bash
# Статус репликации
redis-cli INFO replication

# Проверка lag (master)
redis-cli INFO clients | grep -E "client_id|addr"
redis-cli CLIENT LIST | grep -E "id=|addr="
```

**Пример диагностики lag:**

```bash
# На master: найти offset
redis-cli INFO replication | grep master_repl_offset
# → master_repl_offset:123456789

# На replica: найти offset
redis-cli INFO replication | grep slave_repl_offset
# → slave_repl_offset:123450000

# Lag в байтах
echo $((123456789 - 123450000))
# → 6789 bytes
```

### Анализ кластера (Redis Cluster)

```bash
# Проверка состояния кластера
redis-cli --cluster check 127.0.0.1:7000

# Информация о узлах
redis-cli -p 7000 CLUSTER INFO
redis-cli -p 7000 CLUSTER NODES
```

### Page faults: диагностика на уровне ОС

```bash
# Статистика page faults процесса Redis
pid=$(pgrep redis-server)
sudo perf stat -p $pid -e page-faults,major-faults,minor-faults -- sleep 10

# Или через ps:
ps -p $pid -o pid,min_flt,maj_flt,comm
# → PID    MINFLT  MAJFLT COMMAND
# → 12345  123456  0      redis-server
```

Major faults > 0 в стабильном состоянии указывают на:
1. Недостаток RAM
2. Отсутствие huge pages (THP)
3. Слишком большой `maxmemory` для физической RAM

### Валидация конфигурации фоновых задач

```bash
# Проверка конфигурации TTL-очистки
redis-cli CONFIG GET hz
# → hz 10

# Проверка активности defrag
redis-cli CONFIG GET activedefrag
# → activedefrag yes

# Проверка ленивого освобождения
redis-cli CONFIG GET lazyfree-lazy-eviction
redis-cli CONFIG GET lazyfree-lazy-expire
redis-cli CONFIG GET lazyfree-lazy-server-del
```

## Устранение неисправностей

### Latency spikes

**Причины:**
1. Блокирующие команды (KEYS, SMEMBERS, SORT)
2. Фоновые задачи (RDB, AOF rewrite, replication backlog)
3. Фрагментация памяти (`mem_fragmentation_ratio` > 1.5)
4. Major page faults (недостаток RAM или THP)
5. Перегрузка CPU или I/O
6. Контекстные переключения между потоками
7. Большие ключи, удаляемые синхронно (без lazyfree)

**Диагностика:**

```bash
# Проверка slow log
redis-cli SLOWLOG GET 10

# Проверка фрагментации
redis-cli INFO memory | grep mem_fragmentation_ratio

# Проверка page faults
redis-cli INFO stats | grep major_faults

# Проверка background tasks
redis-cli INFO persistence | grep -E "rdb_last_save|aof_delayed"

# Проверка CPU
redis-cli INFO cpu
top -p $(pgrep redis-server)
```

**Решения:**
1. Замените `KEYS` на `SCAN`, `SMEMBERS` на `SSCAN`
2. Используйте `--latency-history` для периодического измерения
3. Включите `activedefrag yes` при фрагментации > 1.5
4. Отключите Transparent Huge Pages (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`)
5. Используйте huge pages (если требуется) или увеличьте RAM
6. Настройте `lazyfree-lazy-eviction yes` и `lazyfree-lazy-expire yes`
7. Перенесите RDB/AOF rewrite на пики вне нагрузки (cron)
8. Увеличьте `hz` для более частой TTL-очистки при большом количестве истекающих ключей

### Memory pressure

**Причины:**
1. Недостаток `maxmemory`
2. Большие ключи (big keys)
3. Высокий miss penalty (кэш не держит hot data)
4. Фрагментация памяти
5. Утечки памяти (неудаляемые ключи)

**Диагностика:**

```bash
# Поиск больших ключей
redis-cli --bigkeys

# Проверка фрагментации
redis-cli INFO memory | grep mem_fragmentation_ratio

# Анализ аллокатора
redis-cli MEMORY MALLOC-STATS
```

**Решения:**
1. Увеличьте `maxmemory`
2. Разбейте большие ключи на части
3. Перенесите большие объекты во внешнее хранилище
4. Включите `activedefrag yes`
5. Настройте `lazyfree-lazy-eviction yes`

### OOM errors

**Симптом:** `OOM command not allowed`

**Причина:** `maxmemory` исчерпан, политика `noeviction` не позволяет удалять ключи

**Решения:**
1. Увеличьте `maxmemory`
2. Смените политику на `allkeys-lru` или `allkeys-lfu`
3. Найдите и удалите большие ключи: `redis-cli --bigkeys`
4. Перенесите часть данных во внешнее хранилище
5. Проверьте, нет ли утечек (ключи без TTL, которые не удаляются)

### Replication lag

**Симптом:** Данные на master обновлены, но на replica устаревшие.

**Причины:**
1. Нехватка пропускной способности сети
2. Большие транзакции или Lua-скрипты на master
3. `repl-backlog-size` слишком мал (replica отстала и требует full resync)
4. Слишком много replic или slow replic

**Диагностика:**

```bash
# На master
redis-cli INFO replication | grep master_repl_offset

# На replica
redis-cli INFO replication | grep slave_repl_offset

# Разница в байтах
redis-cli INFO replication | grep -E "master_repl_offset|slave_repl_offset"
```

**Решения:**
1. Увеличьте `repl-backlog-size`
2. Используйте `min-replicas-to-write` и `min-replicas-max-lag` для защиты от записи при отставании
3. Проверьте сеть: `ping`, `traceroute`, `ss -ti` для TCP metrics
4. Уменьшите количество replic или используйте цепочки репликации

### High CPU usage

**Причины:**
1. Большое количество соединений
2. Сложные Lua-скрипты или большие ключи
3. Высокий miss rate (много операций кэширования, но данные вытесняются)
4. Фоновые задачи (RDB, AOF rewrite, defrag)
5. Тонкая настройка `hz` (слишком частая TTL-очистка)

**Диагностика:**

```bash
# Количество соединений
redis-cli INFO clients | grep connected_clients

# Загрузка CPU
redis-cli INFO cpu
top -p $(pgrep redis-server)

# Проверка miss rate
redis-cli INFO stats | grep -E "keyspace_hits|keyspace_misses"
```

**Решения:**
1. Ограничьте количество соединений через `maxclients`
2. Оптимизируйте Lua-скрипты (меньше циклов, pipelining)
3. Увеличьте `maxmemory` для снижения miss rate
4. Перенесите фоновые задачи на отдельный инстанс или используйте Redis Flex
5. Настройте `hz` на 10-25 (по умолчанию 10, при большом TTL-трафика можно увеличить)

### Slow AOF rewrite / RDB save

**Симптом:** Пики latency во время снапшотов.

**Причины:**
1. Большой объем данных (форк процесса + copy-on-write)
2. Высокая запись в момент снапшота
3. Отсутствие Redis Flex (v8+)

**Диагностика:**

```bash
redis-cli INFO persistence | grep -E "rdb_last_save|rdb_changes_since_last_save"
redis-cli INFO persistence | grep aof_delayed_fsync
```

**Решения:**
1. Используйте `save ""` для отключения автоматических RDB в production, делайте снапшоты вручную в окна низкой нагрузки
2. Настройте AOF с `appendfsync everysec` вместо `always`
3. Включите `lazyfree-lazy-eviction yes` для уменьшения copy-on-write
4. Обновитесь до Redis 8.x для использования Redis Flex
5. Используйте `rdb-del-sync-files no` для предотвращения блокировок реплик

## Лучшие практики

### Производительность
- Используйте `SCAN` вместо `KEYS`, `SSCAN` вместо `SMEMBERS`
- Настройте `slowlog-log-slower-than` на 10 000 мкс (10 мс) для production
- Используйте `MEMORY DOCTOR` для периодической диагностики
- Включите `activedefrag yes` при фрагментации > 1.5
- Используйте `lazyfree-lazy-eviction yes` и `lazyfree-lazy-expire yes`
- Настройте `hz 10` для общего использования; увеличьте до 25 при большом TTL-трафика
- Отключите THP: `echo never > /sys/kernel/mm/transparent_hugepage/enabled`

### Безопасность
- Никогда не выполняйте `FLUSHALL` или `FLUSHDB` в production
- Используйте ACL для ограничения доступа к опасным командам (`CONFIG`, `DEBUG`, `FLUSHALL`)
- Логируйте все `CONFIG` и `DEBUG` команды через slowlog
- Привязывайте Redis к внутреннему интерфейсу (`bind 127.0.0.1` или внутренний IP)
- Используйте `requirepass` или ACL v2 (Redis 8.x)

### Эксплуатация
- Настройте мониторинг `redis_slowlog_length`, `redis_used_memory_bytes`, `redis_fragmentation_ratio`
- Тестируйте latency после каждого изменения конфигурации
- Используйте `--latency-history` для периодического измерения задержек
- Настройте алерты на `evicted_keys_total`, `major_faults`, `blocked_clients`
- Используйте `CONFIG REWRITE` для сохранения изменений конфигурации между перезапусками

### SRE Runbook: пороги алертинга

| Метрика | Команда проверки | Порог | Действие |
| :--- | :--- | :--- | :--- |
| `mem_fragmentation_ratio` | `INFO memory` | > 1.5 | Включить `activedefrag` или перезапустить |
| `major_faults` | `INFO stats` | > 0 | Проверить RAM, отключить THP |
| `evicted_keys` | `INFO stats` | Рост > 100/мин | Увеличить `maxmemory` или сменить TTL |
| `blocked_clients` | `INFO clients` | > 10 | Найти BLPOP/BRPOP в slowlog |
| `slowlog` длина | `SLOWLOG LEN` | > 100 | Анализировать каждую запись |
| `used_memory` / `maxmemory` | `INFO memory` | > 80% | Планировать увеличение RAM |
| `instantaneous_ops_per_sec` | `INFO stats` | Резкое падение | Проверить блокировки и CPU |

## Дополнительная информация

### Встроенные инструменты отладки

| Инструмент | Назначение | Пример |
| :--- | :--- | :--- |
| `SLOWLOG` | Журнал медленных команд | `redis-cli SLOWLOG GET 10` |
| `LATENCY` | Измерение и анализ задержек | `redis-cli --latency-history` |
| `LATENCY DOCTOR` | Диагностика причин latency spikes | `redis-cli LATENCY DOCTOR` |
| `LATENCY GRAPH` | График latency по командам | `redis-cli LATENCY GRAPH command` |
| `MEMORY` | Анализ памяти | `redis-cli MEMORY DOCTOR` |
| `MEMORY USAGE` | Размер ключа | `redis-cli MEMORY USAGE user:123` |
| `MEMORY MALLOC-STATS` | Статистика jemalloc | `redis-cli MEMORY MALLOC-STATS` |
| `BIGKEYS` | Поиск больших ключей | `redis-cli --bigkeys` |
| `MONITOR` | Трассировка всех команд | `redis-cli MONITOR` |
| `DEBUG` | Внутренняя диагностика | `redis-cli DEBUG SLEEP 5` |
| `INFO` | Полная статистика | `redis-cli INFO all` |
| `CLIENT LIST` | Список соединений | `redis-cli CLIENT LIST` |

### Важность MONITOR

Команда `MONITOR` позволяет трассировать все команды в реальном времени. Используйте ее осторожно — она значительно снижает производительность:

```bash
redis-cli MONITOR
# → 1698765432.123456 [0 10.0.0.10:54321] "SET" "user:123" "value"
# → 1698765432.123789 [0 10.0.0.10:54321] "GET" "user:123"
```

### Crash recovery

При аварийном завершении Redis восстанавливает данные из RDB/AOF файлов:

```bash
# Проверка integrity RDB файла
redis-check-rdb /var/lib/redis/dump.rdb

# Проверка integrity AOF файла
redis-check-aof /var/lib/redis/appendonly.aof
```

### Важность валидации после изменений

Любое изменение конфигурации требует валидации:

```bash
# 1. Проверить текущее значение
redis-cli CONFIG GET activedefrag

# 2. Применить изменение
redis-cli CONFIG SET activedefrag yes

# 3. Сохранить в конфигурационный файл
redis-cli CONFIG REWRITE

# 4. Проверить эффект через 5-10 минут
redis-cli INFO memory | grep mem_fragmentation_ratio
redis-cli INFO stats | grep major_faults
```

### Связанные темы

- [Обзор кэширования](./caching_overview.md) — уровни и метрики
- [Паттерны кэширования](./caching_patterns.md) — стратегии взаимодействия с БД
- [Алгоритмы вытеснения](./caching_eviction_policies.md) — управление памятью
- [Redis Overview](../../Databases/redis_overview.md) — общее руководство
- [Redis против Memcached](../../Databases/redis_vs_memcached.md) — архитектурное сравнение
