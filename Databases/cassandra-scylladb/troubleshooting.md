# Поиск и устранение неисправностей

**Актуально для:** Apache Cassandra 5.0.x / ScyllaDB 2026.x

## Определения

- **Client-side exception** — исключение, сгенерированное драйвером на клиенте (`NoHostAvailableException`): ни один узел не отвечает или недоступен по сети. Запрос не дошёл до кластера.
- **Server-side exception** — исключение, возвращённое координатором (`UnavailableException`, `WriteTimeoutException`): запрос дошёл до кластера, но не выполнен.
- **Coordinator** — узел, координирующий запрос клиента. Его таймауты, очереди пулов потоков и GC — первое место диагностики.
- **Hint (hinted handoff)** — мутация, сохранённая координатором для недоступной реплики; доставляется при восстановлении узла, хранится не дольше `max_hint_window` (дефолт 3 часа), затем удаляется.
- **Diagnostics dump** — дамп внутреннего состояния ScyllaDB в лог по сигналу `SIGQUIT` (per-shard, logger `diagnostics`). На JVM-узле (Cassandra) `SIGQUIT` даёт thread dump — механизмы разные.
- **scylla-doctor** — инструмент ScyllaDB: проверка системных требований, конфигурации и тюнинга узла; выводит `.vitals.json` и архив логов (запускается на каждом узле).

## Методология диагностики

Цель — изолировать слой, на котором ломается запрос, вместо вслепую менять конфигурацию. Порядок вопросов:

1. **Масштаб:** один запрос/клиент или все клиенты? Один узел или весь кластер? Одна keyspace/таблица или все?
2. **Тип операции:** чтение или запись? Batch? LWT? Range scan?
3. **Тип ошибки** — определяет слой:
   - `NoHostAvailableException` → клиент/сеть (драйвер не достучался ни до одного узла);
   - `UnavailableException` → реплики (живых реплик меньше, чем требует consistency level);
   - `Write/ReadTimeoutException` → координатор/диск (узлы не ответили в пределах таймаута);
   - `TombstoneOverwhelmingException` → модель данных (см. [Тюнинг](./performance.md));
   - OOM / падение узла → JVM/heap или диск.
4. **Слой:** клиент/драйвер → сеть (firewall, DNS, MTU) → координатор (пулы потоков, GC) → реплики (диск, compaction) → ОС (CPU, I/O, память).

Правило: меняйте **один параметр за раз** и фиксируйте до/после (см. [Тюнинг](./performance.md)); перед рестартом узла соберите диагностику — рестарт уничтожает состояние очередей и дампов.

## Ошибки клиентов и координатора

### NoHostAvailableException (client-side)

- **Причина:** драйвер не смог подключиться ни к одному узлу: узлы down, закрыт порт native transport (9042), firewall/DNS, неверные contact points, или ошибка конфигурации драйвера (например, datacenter в load-balancing policy не совпадает с DC узлов, исчерпан пул соединений — inner exception `BusyPoolException`).
- **Диагностика:**
  ```bash
  # Состояние узлов и native transport
  nodetool status
  nodetool info          # → Native Transport active: true
  ss -tlnp | grep 9042   # порт слушается?
  # В логах драйвера — inner exception с причиной (connection refused, timeout, pool busy)
  ```
- **Решение:** по причине — поднять узел, открыть порт 9042 (см. [Установку](./installation.md)), исправить contact points/DC в конфиге драйвера, увеличить connections per host. Таймауты клиента настраиваются **в драйвере** (в Java driver 4.x read timeout по умолчанию 12 с), а не в `cassandra.yaml`.

### UnavailableException (server-side)

- **Причина:** координатор знает, что живых реплик меньше, чем требует consistency level (например, `QUORUM` при `RF=3` требует 2 из 3). Исключение содержит `consistency level`, `required` и `alive` — сколько реплик нужно и сколько видно.
- **Диагностика:**
  ```bash
  nodetool status              # какие реплики DOWN (столбец Status)
  nodetool describecluster     # недостижимые узлы, версии схемы
  # Метрики: ClientRequest.*.Unavailables (Cassandra),
  #          scylla_storage_proxy_coordinator_*_unavailable (ScyllaDB)
  ```
- **Решение:** восстановить реплики (bootstrap/replace — см. [Обслуживание](./operations.md)); временно снизить consistency level (с потерей гарантий чтения — `R + W > RF`); проверить, что `RF` соответствует числу узлов в DC. **Не путать** с проблемой присоединения к кластеру: разный `cluster_name` или недоступные seeds не дают `UnavailableException` — узел просто не входит в кольцо (см. следующий раздел).

### WriteTimeoutException / ReadTimeoutException

- **Причина:** координатор не получил достаточно ответов в пределах таймаута. Реальные таймауты (Cassandra 5.0; в 4.0/3.11 — с суффиксом `_in_ms`):

  | Параметр (5.0) | Дефолт | Для чего |
  | :--- | :--- | :--- |
  | `read_request_timeout` | `5000ms` | чтение |
  | `write_request_timeout` | `2000ms` | запись |
  | `request_timeout` | `10000ms` | прочие операции |
  | `range_request_timeout_in_ms` (4.0) | `10000ms` | range-сканы, secondary index |
  | `truncate_request_timeout_in_ms` (4.0) | `60000ms` | TRUNCATE (снапшот перед удалением) |

  Параметра `rpc_timeout_in_ms` в современном `cassandra.yaml` **нет** — это устаревшее имя. Текущие значения: `nodetool gettimeout read`.
- **Диагностика:**
  ```bash
  nodetool tpstats          # PendingTasks растёт? Blocked? Dropped Messages > 0?
  nodetool compactionstats  # backlog compaction?
  nodetool gcstats          # паузы GC (Cassandra 4.0+)
  iostat -x 1               # диск в потолке (%util, await)?
  ```
- **Решение:** найти узкое место (диск, compaction, GC, перегрузка) и устранить его; простое повышение таймаутов маскирует проблему. Write timeout **не означает**, что запись потеряна — координатор мог сохранить hint (см. раздел Hints). Read timeout — чтение не выполнено, повторите запрос.

### TombstoneOverwhelmingException

- **Причина:** запрос сканировал больше `tombstone_failure_threshold` (дефолт 100000) tombstones — защита от OOM. Формат записи в логе и пороги — в [Тюнинг → Диагностика Tombstones](./performance.md#диагностика-tombstones).
- **Решение:** исправить модель данных (временные ряды — TWCS), запустить repair, при гарантии частого repair — уменьшить `gc_grace_seconds`. **Не** повышать `tombstone_failure_threshold` — это маскирует проблему (см. антипаттерны в [Тюнинг](./performance.md)).

## Узел не запускается / не присоединяется к кластеру

- **Симптомы:** узел не появляется в `nodetool status`, или `UN` не становится, или падает при старте.
- **Типичные причины:**
  - seed-узлы недоступны или разный `cluster_name` — узел не входит в кольцо (архитектурная причина — см. [Архитектуру](./architecture.md#поиск-и-устранение-неисправностей));
  - неверные `listen_address` / `rpc_address` / `broadcast_address`;
  - занятый порт (7000/7001 gossip, 9042 native transport, 7199 JMX) — в логе ошибка bind;
  - `ConfigurationException` в логе — неверный параметр конфигурации;
  - `IOException` — нет прав на каталоги данных или диск заполнен;
  - ScyllaDB: не выполнен `scylla_setup`, неверные seeds в `scylla.yaml`.
- **Диагностика:**
  ```bash
  # Логи запуска — первая ошибка (ERROR/FATAL) со стектрейсом
  tail -100 /var/log/cassandra/system.log
  journalctl -u scylla-server -n 100        # ScyllaDB (systemd)
  nodetool describecluster                    # имя кластера, snitch, версии схемы
  ```
- **Решение:** по причине — исправить `cluster_name`/seeds/адреса, освободить порт, дать права, очистить место. Если `nodetool describecluster` показывает **несколько версий схемы** — схема ещё распространяется по gossip: подождите; если не сходится — проверить логи узлов с отличающейся версией.

## Диагностический bundle команд

Команды работают и в Cassandra, и в ScyllaDB (в ScyllaDB — подмножество; полный список: `nodetool help`). При включённой аутентификации JMX добавьте `-u <user> -pw <пароль>` (см. [Безопасность](./security.md)). Мониторинговые команды (`status`, `info`, `tpstats`, `tablestats`, `compactionstats`, `proxyhistograms`, `tablehistograms`, `toppartitions`, `gcstats`, `failuredetector`, `gossipinfo`) — в [Мониторинг](./monitoring.md).

```bash
# Информация о кластере: имя, snitch, partitioner, версии схемы,
# недостижимые узлы (schema disagreement — несколько версий схемы)
nodetool describecluster

# Сетевая статистика: текущие streaming-операции (bootstrap, repair, rebuild),
# режим узла, прогресс и скорость передачи
nodetool netstats

# Кольцо: диапазоны токенов по узлам (дисбаланс нагрузки)
nodetool ring

# Текущие таймауты (read, write, range, ...)
nodetool gettimeout read

# Вероятностная трассировка запросов (0 — выкл., 1 — все; дефолт 0)
nodetool settraceprobability 0.1

# Hints: статус хранения, отложенные доставки, pending hints (Cassandra 4.1+)
nodetool statushandoff
nodetool listpendinghints

# Уровень логирования logger'а в runtime (ScyllaDB; Cassandra — через logback)
nodetool setlogginglevel mylogger debug
```

## Логи, GC-лог и дампы

| Артефакт | Cassandra | ScyllaDB |
| :--- | :--- | :--- |
| Основной лог | `/var/log/cassandra/system.log` | `/var/log/scylla/scylla.log`; в production — syslog → `journalctl` |
| GC-лог | `${CASSANDRA_LOG_DIR}/gc.log` (ротация 10 × 10 МиБ = 100 МиБ; строка `-Xlog:gc` добавляется `cassandra-env.sh`, если не задана в `jvm-server.options`) | — (Seastar не использует JVM GC) |
| Heap dump при OOM | `-XX:+HeapDumpOnOutOfMemoryError` активен в `jvm-server.options`; путь — `CASSANDRA_HEAPDUMP_DIR` (на 5.0.4+ по умолчанию — лог-каталог: **дамп размером с heap может заполнить файловую систему** — указывайте ФС с запасом); на 5.0.0–5.0.3/4.x — только если переменная задана, иначе рабочий каталог | — |
| Thread dump | `jstack <pid>` или `kill -3 <pid>` (SIGQUIT → thread dump в лог) | `SIGQUIT` → **diagnostics dump** в лог (logger `diagnostics`, per-shard) |
| Core dump | — | `/var/lib/scylla/coredump` (если пусто — проверьте настройки ядра/ABRT) |

При OOM Cassandra завершается принудительно (`-XX:OnOutOfMemoryError=kill -9 %p`, добавляется `cassandra-env.sh`) — supervisor/systemd перезапускает узел.

**JVM-диагностика (Cassandra):** инструменты JDK для анализа heap и потоков — `jstat` (GC-статистика), `jmap` (heap dump по требованию), `jstack` (thread dump); анализ GC-лога — GCViewer / gceasy.io. Полный справочник JVM-инструментов — **[Управление Java-приложениями](../../Linux/Development/java_management.md)**. ScyllaDB не использует JVM — для неё диагностика через `scyllatop`, REST API и diagnostics dump (см. выше).

**Сбор данных для эскалации (ScyllaDB):** `scylla-doctor` на каждом узле → `.vitals.json` + архив логов; дополнительно — `scyllatop` (не `top`: ScyllaDB многопоточна per-shard), вывод `system.local` / `system.peers`, при проблемах с производительностью — `system.large_partitions`, при проблемах с консистентностью — `system_distributed.repair_history`. REST API ScyllaDB — надмножество всех `nodetool`-команд.

## Hints (hinted handoff)

Hints накапливаются, когда реплика недоступна во время записи. Проблемы: рост места на диске, задержка доставки, потеря данных при превышении окна.

```bash
# Сколько hints хранится и для кого (Cassandra 4.1+, CASSANDRA-14795):
# Host ID, Address, Rack, DC, Status, Total files, Newest, Oldest
nodetool listpendinghints

# Статус хранения/доставки hints; приостановка/возобновление доставки
nodetool statushandoff
nodetool pausehandoff && nodetool resumehandoff

# Окно хранения hints (дефолт 3 часа) и throttle доставки
nodetool getmaxhintwindow
nodetool sethintedhandoffthrottlekb 1024
```

- Параметр `max_hint_window` (5.0/4.1; в 4.0 — `max_hint_window_in_ms`). Hints старше окна **удаляются** — если узел был down дольше, консистентность восстанавливается только `nodetool repair` (см. [Обслуживание](./operations.md)).
- Узел UP, но hints не доставляются: `nodetool tpstats | grep -i hint`, логи по `grep -i hint /var/log/cassandra/system.log`, метрика `scylla_hints_manager_send_errors` (ScyllaDB).
- Удалить накопившиеся hints принудительно: `nodetool truncatehints` (после проверки, что реплики восстановлены через repair).

## Zombie data и clock skew

**Zombie data (воскрешение удалённых данных):** узел, который был down дольше `gc_grace_seconds`, не получил tombstone при восстановлении и может «воскресить» удалённую запись при следующем repair/чтении. Защита:

- Repair чаще `gc_grace_seconds` (дефолт 10 дней) — единственная надёжная защита (см. [Обслуживание](./operations.md))
- Не уменьшать `gc_grace_seconds` без гарантии частого repair
- Симптом: удалённая запись снова видна после восстановления узла

**Clock skew (рассинхронизация часов):** Cassandra/ScyllaDB разрешают конфликты последних записей по timestamp (LWW — last write wins); рассинхронизация часов узлов приводит к тому, что более старая запись «побеждает» более новую.

- **Профилактика:** NTP на всех узлах (обязателен); проверка: `ntpstat` или `chronyc tracking`
- **Симптомы:** stale reads, «воскрешение» старых версий строк, непредсказуемый порядок событий
- **Диагностика:** сравнить часы узлов (`date` на каждом узле), проверить drift в мониторинге NTP

## Диск заполнен

- **Причины:** backlog compaction, снапшоты (в т.ч. после scrub/verify), hints, сегменты commitlog, GC-лог/heap dump (см. выше).
- **Диагностика:**
  ```bash
  df -h /var/lib/cassandra /var/lib/scylla
  nodetool compactionstats     # pending compactions
  nodetool listsnapshots       # снапшоты и их размеры
  nodetool listpendinghints    # hints (Cassandra 4.1+)
  ```
- **Решение:** удалить ненужные снапшоты (`nodetool clearsnapshot`), поднять throughput compaction (`nodetool setcompactionthroughput`), добавить место; при критическом заполнении — Cassandra может отказывать в записи или падать, ScyllaDB прекращает принимать записи. Профилактика: алерты на свободное место и compaction backlog (см. [Мониторинг](./monitoring.md)).

## Валидация

```bash
# Ошибка исчезла из логов (счётчик не растёт)
grep -c "WriteTimeoutException" /var/log/cassandra/system.log
# → 0

# Кластер здоров: все узлы UN
nodetool status

# Очереди пусты, потери нет
nodetool tpstats
# → PendingTasks стабильно < 50, Dropped Messages = 0

# Клиентский запрос выполняется
cqlsh -e "SELECT * FROM my_app.user_events LIMIT 1;"
# → строка без ошибок

# Hints доставлены
nodetool listpendinghints
# → пустой вывод (нет строк)
```

## Best Practices

- **Соберите диагностику до рестарта:** логи, `tpstats`, `compactionstats`, thread/heap dump — рестарт уничтожает состояние.
- **Не рестартируйте все узлы одновременно** — rolling restart, один узел за раз.
- **Эскалация:** Cassandra — `system.log` + `gc.log` + heap dump + вывод `tpstats`/`describecluster`; ScyllaDB — `scylla-doctor` vitals + логи + core dump (если есть).
- **Алерты на первые сигналы** (Dropped Messages, timeouts, unavailable, Pending Tasks, compaction backlog, TombstoneWarnings) — пороги в [Мониторинг](./monitoring.md).
- **NTP на всех узлах** — корректность LWW-разрешения конфликтов зависит от часов (см. [Архитектуру](./architecture.md)).

### Очистка

```bash
# Диагностические артефакты (heap dump может быть размером с heap)
rm /var/log/cassandra/cassandra-*-pid*.hprof

# Снапшоты после scrub/verify (см. [Обслуживание](./operations.md))
nodetool clearsnapshot
```

## См. также

- **[Мониторинг и observability](./monitoring.md)** — метрики, пороги алертов, nodetool-мониторинг.
- **[Тюнинг производительности](./performance.md)** — Tombstones, GC, антипаттерны.
- **[Обслуживание и эксплуатация](./operations.md)** — repair, compaction, topology-операции.
- **[Бэкап и восстановление](./backup-recovery.md)** — восстановление после сбоев.
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — архитектурные причины симптомов.
- **[Установка и настройка](./installation.md)** — порты, расположение конфигов.
- **[Безопасность](./security.md)** — JMX-аутентификация для nodetool.
