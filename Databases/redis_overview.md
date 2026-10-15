# Redis — обзор и практическое руководство

**Актуально для:** Redis 8.0–8.10 / Valkey 9.x

Высокопроизводительное хранилище данных в оперативной памяти (in-memory), используемое как база данных, кэш, брокер сообщений и очередь задач. Теоретические основы кэширования — в разделе **[Кэширование: обзор](../Concepts/Caching/caching_overview.md)**.

## Определения

**Redis (Remote Dictionary Server)** — NoSQL СУБД типа «ключ-значение» с открытым исходным кодом. Работа целиком в RAM обеспечивает задержки в микросекунды и пропускную способность до миллионов операций в секунду на узел. Отличительная черта — богатый набор структур данных с атомарными операциями на стороне сервера.

**Текущая версия:** Redis 8.10.2 (сентябрь 2026). Линейка 8.x выпускается по схеме: мажор — раз в год, минор — раз в полгода: 8.0 (май 2025), 8.2 (авг 2025), 8.4 (ноя 2025), 8.6 (фев 2026), 8.8 (май 2026), 8.10 (июл 2026).

**Модель поддержки:** активная поддержка — текущий релиз, предыдущий минор и предыдущий мажор; security support: 8.2 — до сен 2030, 8.0 — до дек 2026, 7.4/7.2 — до дек 2029.

**Лицензии по версиям:**

| Версия | Лицензия |
| :--- | :--- |
| 7.2 и ранее | BSD-3-Clause |
| 7.4–7.8 | RSALv2 или SSPLv1 (с марта 2024) |
| 8.0+ | RSALv2 / SSPLv1 / AGPLv3 (тройная лицензия; AGPLv3 — OSI-approved) |

**Форки после смены лицензии (2024):**
- **Valkey** — fork Redis 7.2.4 под эгидой Linux Foundation, лицензия BSD-3-Clause; текущая версия 9.1 (май 2026).
- **Redict** — fork Redis 7.2.4 под LGPL-3.0-only; независимый проект (Codeberg), не связан с Linux Foundation и не получает новых типов данных Redis 8.

**RDB** — снапшот всего датасета в один файл. **AOF** — журнал операций записи. **Fork** — порождение дочернего процесса для фонового сохранения (RDB/AOF-rewrite). **Eviction** — вытеснение ключей при достижении `maxmemory`.

## Основные концепции

### Модель данных

Redis — хранилище «ключ-значение» с набором структур. В 8.0 возможности Redis Stack (Query Engine/Search, JSON, Time Series, вероятностные типы) интегрированы в ядро; отдельные модули больше не требуются.

| Структура | Описание | Применение |
| :--- | :--- | :--- |
| **Strings** | Текст/бинарные данные, до 512 МБ | Кэш страниц, сессии, счетчики |
| **Lists** | Упорядоченные коллекции (quicklist) | Простые очереди, логи последних событий |
| **Sets** | Неупорядоченные уникальные элементы | Теги, уникальные посетители, пересечения |
| **Hashes** | Карты полей и значений; compact hashes (8.10) — до 50% экономии памяти для ключей с общей схемой, массовая вставка через `HIMPORT` | Объекты пользователей, конфигурации |
| **Sorted Sets** | Множества с числовым score; кэширование ZRANK (8.2) | Лидерборды (`ZREVRANGEBYSCORE` — топ-N), индексы с приоритетом |
| **Bitmaps** | Битовые массивы; `BITOP` с операторами DIFF/DIFF1/ANDOR/ONE (8.2) | Аналитика посещаемости (DAU), флаги |
| **Bitfields** | Инкременты/декременты произвольных битовых полей | Счетчики, упаковка состояний |
| **HyperLogLog** | Приблизительный подсчет уникальных, ~12 КБ на ключ | Cardinality на больших данных |
| **Geospatial** | Координаты на основе sorted sets | Поиск точек в радиусе, дистанции |
| **Streams** | Логи событий с группами потребителей; `XNACK` (8.8), идемпотентность `XADD IDMP/IDMPAUTO` (8.6), `MAXCOUNT/MAXSIZE` в XREAD (8.10) | Шина событий, очереди с ACK |
| **JSON** (8.0+) | Документы с JSONPath; однородные числовые массивы (8.4, до 92% экономии) | Документо-ориентированное хранение |
| **Time Series** (8.0+) | `TS.ADD`/`TS.RANGE`; NaN-значения (8.6), множественные агрегаторы (8.8), `TS.NRANGE`/`TS.READ` (8.10) | Метрики, мониторинг |
| **Probabilistic** (8.0+) | Bloom filter, Cuckoo filter, Count-min sketch, Top-k, t-digest | Проверка принадлежности, частотные оценки |
| **Vector Set** (8.0+, beta) | Поиск ближайших соседей (KNN) через `VSIM` (фильтрация `IN` — 8.2), сжатие векторов (8.2) | Поиск сходства, рекомендательные выборки |
| **Array** (8.8+) | Разреженные индексируемые последовательности строк с O(1) доступом по индексу; ring-буфер режим | Ring-буферы, логи, скользящие окна, агрегации |

**Внутренние оптимизации памяти:**
- `listpack` (заменил `ziplist` в 7.0) — компактное хранение небольших коллекций в одном блоке; пороги — `hash-max-listpack-entries` (128), `hash-max-listpack-value` (64), `zset-max-listpack-*` (128/64), `set-max-intset-entries` (512), `list-max-listpack-size` (-2, 8 КБ).
- `intset` — оптимизация для множеств только из целых чисел.
- `quicklist` — связный список из `listpack`-блоков для списков.
- Compact hashes (8.10) — имена полей хранятся один раз для ключей с общей схемой.

Кодировку любого ключа можно проверить: `OBJECT ENCODING key`.

Все операции над структурами данных атомарны.

### Управление памятью

Redis использует аллокатор `jemalloc` (на Linux) с объектными обертками. При достижении лимита `maxmemory` вступает в силу политика вытеснения. Теория алгоритмов — в **[Политики вытеснения](../Concepts/Caching/caching_eviction_policies.md)**.

**Политики вытеснения (`maxmemory-policy`):**

| Политика | Описание |
| :--- | :--- |
| `noeviction` | Не вытеснять, возвращать ошибку при записи. Безопасно для роли БД. |
| `allkeys-lru` | (Рекомендуется для кэша) Удаляет наименее давно использованные ключи. |
| `allkeys-lfu` | Удаляет наименее часто используемые ключи. |
| `allkeys-random` | Удаляет случайные ключи. |
| `volatile-lru` / `volatile-lfu` / `volatile-random` | То же, но только среди ключей с TTL. |
| `volatile-ttl` | Вытеснять ключи с наименьшим оставшимся TTL. |
| `volatile-lrm` / `allkeys-lrm` | (8.6+) Вытеснять по давности модификации (least recently modified) — для write-heavy нагрузки. |

LRU/LFU в Redis аппроксимируются сэмплированием: `maxmemory-samples` (по умолчанию 5) случайных ключей на вытеснение; точность LFU настраивается через `lfu-log-factor` (10) и `lfu-decay-time` (1).

### TTL и старение данных

Redis хранит TTL для каждого ключа с миллисекундной точностью:
1. **Пассивное истечение:** ключ удаляется при обращении, если TTL истек.
2. **Активное истечение:** фоновый цикл выборочно проверяет ключи (`hz`, по умолчанию 10 циклов в секунду; `dynamic-hz yes` адаптирует частоту к нагрузке).

Оставшийся TTL ключа — команда `TTL key` (секунды; `PTTL` — миллисекунды). Возвращает `-1`, если ключ существует без TTL, и `-2`, если ключ не найден (с Redis 2.8):
```bash
redis-cli TTL session:abc123
# → (integer) 1799
```

### Механизмы персистентности (Persistence)

1. **RDB (Snapshotting):** снапшоты всей БД (`save 3600 1 300 100 60 10000` — defaults). Компактно, быстрое восстановление, но риск потери данных между снапшотами. Создание — через `fork` (задержка пропорциональна размеру датасета).
2. **AOF (Append-Only File):** журнал каждой операции записи. С 7.0 — **multi-part AOF**: каталог `appendonlydir/` с базовым файлом (`.base.rdb`), инкремальным журналом (`.incr.aof`) и манифестом. `appendfsync`: `always` (максимальная надежность), `everysec` (default, компромисс), `no` (делегирование ОС).
3. **Гибрид RDB+AOF:** `aof-use-rdb-preamble yes` (default) — AOF-rewrite записывает снапшот + журнал.
4. **BACKUP (8.10+):** node-side резервное копирование и восстановление на основе MP-AOF, включая инкрементальные бэкапы и координированные бэкапы кластера с низким влиянием на нагрузку.
5. **WAIT:** команда ожидания подтверждения записи от N реплик — компромисс между надежностью и задержкой (детали — в **[Redis HA](../Concepts/Caching/caching_redis_ha.md)**).

### Программируемость: Lua и Функции

1. **Lua-скрипты** (`EVAL`/`EVALSHA`): группа команд выполняется атомарно. Долгие скрипты блокируют event loop — используйте `pcall` и разбивайте логику.
2. **Redis Functions (7.0+):** функции хранятся в БД (персистентны), поддерживают версионность (`FUNCTION LOAD`/`FLUSH`) и избавляют клиента от повторной загрузки логики. Флаг `SCRIPT_RUNNER` (8.10) помечает команды, выполняющие скрипты.

### Безопасность и контроль доступа

- **ACL (6.0+):** пользователи с правами на команды, ключи (`~*`) и каналы (`&*`). Команды: `ACL SETUSER`/`GETUSER`/`LIST`/`SAVE`/`LOAD`/`CAT`/`USERS`/`WHOAMI`.
- **ACL DRYRUN (7.0+):** проверка прав без выполнения и побочных эффектов:
  ```bash
  redis-cli ACL SETUSER reader on >secret ~cache:* +GET
  # → OK
  redis-cli ACL DRYRUN reader GET cache:user:42
  # → OK
  redis-cli ACL DRYRUN reader SET cache:user:42 "x"
  # → Key outside the allowed pattern
  ```
- **Категории ACL в 8.0:** `@read`/`@write` теперь включают команды новых типов; добавлены `@search`, `@json`, `@timeseries`, `@bloom`, `@cuckoo`, `@cms`, `@topk`, `@tdigest`. Перед апгрейдом на 8.x выгружайте `ACL LIST` и проверяйте правила через `ACL DRYRUN`.
- **Безопасность по умолчанию:** пароль (`requirepass`) НЕ установлен по умолчанию — default-пользователь работает без пароля (`nopass`); пакеты Debian/Ubuntu привязывают `bind 127.0.0.1 ::1` и включают `protected-mode yes` (отклоняет запросы не с loopback без пароля). В production задайте `requirepass` или ACL-пользователя вручную.
- **TLS (6.0+):** `tls-port`, `tls-cert-file`/`tls-key-file`/`tls-ca-cert-file`, `tls-replication yes`, `tls-cluster yes`; с 8.6 — автоматическая аутентификация клиентов по TLS-сертификату.
- **Hardening:** `rename-command` для переименования опасных команд (`FLUSHALL`, `CONFIG`), ACL-ограничение `@dangerous`.
- Интеграция с LDAP/Active Directory и Entra ID RBAC — функции коммерческих продуктов Redis Software/Cloud, в Redis Open Source не входят.

### Архитектура выполнения и потоковая модель

- **Event loop:** команды выполняются в одном потоке (отсюда атомарность); CPU-bound команды блокируют всех клиентов.
- **Threaded I/O (6.0+):** вспомогательные потоки обрабатывают чтение/запись сетевых сокетов (`io-threads`; многопоточное чтение включается через `io-threads-do-reads`).
- **Фоновые потоки (4.0+):** lazy free (`UNLINK`, `FLUSHALL ASYNC`, `FLUSHDB ASYNC`) и active defrag (`activedefrag yes`).
- **Производительность по релизам:** 8.0 — до 87% ниже задержка и 2x throughput vs 7.2; 8.6 — более 5x throughput vs 7.2 (типичная кэш-нагрузка); 8.8 — MGET +68%, XREADGROUP +83%, ZADD +74%, SCAN +40%, полная синхронизация репликации +60%.

### Масштабирование и высокая доступность

- **Replication:** асинхронная master-replica репликация; реплики обслуживают read-запросы.
- **Sentinel:** мониторинг мастер-нод, автоматический failover (минимум 3 Sentinel-процесса).
- **Redis Cluster:** шардирование по 16384 хэш-слотам (`CRC16(key) mod 16384`), горизонтальное масштабирование записи, автоматический failover; клиенты получают `MOVED`/`ASK` при миграции слотов. С 8.2 — `CLUSTER SLOT-STATS` (метрики по слотам: число ключей, CPU, сетевой трафик).

Детали топологий, настройки и тестирования failover — в **[Redis: высокая доступность](../Concepts/Caching/caching_redis_ha.md)**.

**Когда нужно шардирование (качественные признаки):**
- Датасет приближается к объему RAM одной ноды.
- Пропускная способность записи упирается в возможности одного мастера.
- Требуется изоляция нагрузки между сервисами.

**Практический вывод:** узкое место кэша обычно — операции в секунду, а не объем RAM. Для большинства систем проще реализовать «тупой кэш» (весь датасет в RAM), чем partial-кэш с динамической инвалидацией.

### Очереди задач

- **List:** `LPUSH`/`RPUSH` + `BLPOP`/`BRPOP` — блокирующие операции для асинхронной обработки; `LMOVEM`/`BLMOVEM` (8.10) — атомарный перенос нескольких элементов.
- **Streams:** `XADD`/`XREADGROUP`/`XACK` — группы потребителей, подтверждение обработки, история, PEL (pending entries list); `XNACK` (8.8) — явный возврат сообщения в группу.
- **Pub/Sub:** `PUBLISH`/`SUBSCRIBE` — fire-and-forget без сохранения истории; для надежной доставки используйте Streams.

## Практические сценарии

### Счетчики и аналитика
```bash
# Атомарное увеличение на 1
INCR page_views:article:123
# Увеличение на N
INCRBY page_views:article:123 10
# Увеличение дробного числа
INCRBYFLOAT rating:product:789 0.5
# Cardinality объединения без материализации (8.10+)
SUNIONCARD visitors:mon visitors:tue visitors:wed
```

### Лидерборды (sorted sets)
```bash
# Топ-10 с баллами: от +inf до -inf (по убыванию score)
ZREVRANGEBYSCORE leaderboard +inf -inf WITHSCORES LIMIT 0 10
```

### Сессии пользователей
```bash
# Создание сессии с TTL 30 минут (1800 сек)
SETEX session:abc123 1800 "{\"user_id\":123,\"role\":\"admin\"}"
# Проверка и продление
EXISTS session:abc123
EXPIRE session:abc123 1800
# Хеш-команды с TTL (8.0+): запись, чтение с продлением, чтение с удалением
HSETEX session:fields:abc123 1800 user_id 123 role admin
HGETEX session:fields:abc123 1800 user_id
HGETDEL session:fields:abc123 user_id
```

### Распределённые блокировки
```bash
# Захватить блокировку на 30 сек (NX - только если нет ключа)
SET lock:resource:123 "client_id_uuid" NX EX 30
```
*Освобождение (через Lua для атомарности — только владелец может удалить):*
```lua
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
```
Алгоритм Redlock (N независимых мастеров), clock drift, GC-паузы и ограничения репликации — в **[Распределенные блокировки](../Concepts/Caching/caching_distributed_locks.md)**.

### Rate limiting (8.8+)
```bash
# Fixed window: 100 запросов в 60 секунд
# Возвращает [new_value, actual_increment]; actual_increment = 0 -> лимит исчерпан
INCREX ratelimit:user:42 BYINT 1 UBOUND 100 EX 60 ENX
```
`ENX` устанавливает TTL только при первом запросе, создавая фиксированное окно; `INCREX` атомарно объединяет инкремент, границы и истечение, устраняя race condition схемы `INCR`+`EXPIRE`.

### Pub/Sub и Streams
```bash
# Публикация / подписка (fire-and-forget)
PUBLISH channel:news "Breaking news!"
SUBSCRIBE channel:news

# Streams: добавление, чтение группой, подтверждение
XADD orders_stream * user_id 100 action "purchase"
XREADGROUP GROUP consumers:1 worker1 COUNT 10 BLOCK 5000 STREAMS orders_stream >
XACK orders_stream consumers:1 <message-id>
XNACK orders_stream consumers:1 <message-id>
```

### Геоданные
```bash
# Добавление координат (долгота, широта)
GEOADD cities 13.4050 52.5200 "Berlin" 2.3522 48.8566 "Paris"
# Поиск в радиусе 500 км от Берлина (GEOSEARCH заменяет deprecated GEORADIUS, 6.2+)
GEOSEARCH cities FROMLONLAT 13.4050 52.5200 BYRADIUS 500 km ASC COUNT 10
# Расстояние между городами
GEODIST cities "Berlin" "Paris" km
```

### Векторный поиск
```bash
# Query Engine (интегрирован в 8.0): KNN-поиск по индексу
FT.SEARCH idx "*=>[KNN 5 @vec $query_vec]" PARAMS 2 query_vec "\x00..." DIALECT 2
```
Для Vector Set поиск ближайших соседей выполняется командой `VSIM` (с 8.2 поддерживает фильтрацию `IN`); синтаксис и параметры индекса — в документации по Vector Set.

### Time Series и вероятностные структуры (8.0+)
```bash
# Метрика: добавление точки и чтение диапазона
TS.ADD sensors:temp:1 * 23.5
TS.RANGE sensors:temp:1 - + COUNT 10
# Bloom filter: проверка принадлежности
BF.ADD urls:seen "https://example.com"
BF.EXISTS urls:seen "https://example.com"
# HyperLogLog: приблизительная cardinality
PFADD visitors:2026-10-03 "user:1" "user:2"
PFCOUNT visitors:2026-10-03
```

## Установка и настройка

### Предварительные требования

- **ОС** (список тестирования Redis 8.8/8.10): Ubuntu 22.04/24.04/26.04, Debian 12/13, Rocky Linux 8.10/9.7/10.1, AlmaLinux 8.10/9.7/10.1, Alpine 3.23, macOS (Intel/ARM).
- **RAM:** минимум 2 ГБ для dev; для production рассчитывайте по формуле: `RAM = (средний размер ключа × количество ключей) × 1.5` (с overhead).
- **Порты:** 6379 (данные), 26379 (Sentinel), порт + 10000 (cluster bus).
- **Сеть:** NTP-синхронизация, задержка между нодами < 1 мс.

### Шаг 1: Инсталляция (Ubuntu/Debian)

Пакеты из дистрибутива могут быть старее (Ubuntu 24.04 — 7.2.x, Debian 13 — 8.0.x); официальный репозиторий устанавливает актуальную версию:
```bash
sudo apt-get install lsb-release curl gpg
curl -fsSL https://packages.redis.io/gpg | sudo gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg
sudo chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/redis.list
sudo apt-get update
sudo apt-get install redis
sudo systemctl enable --now redis-server
```

*Фиксация мажорной линии (например, 8.6):*
```bash
# /etc/apt/preferences.d/redis
Package: redis redis-server redis-sentinel redis-tools
Pin: version 6:8.6.*
Pin-Priority: 1001
```

*Другие платформы:*
```bash
# RHEL/Rocky/AlmaLinux: создать /etc/yum.repos.d/redis.repo
#   [Redis] name=Redis baseurl=http://packages.redis.io/rpm/rhel9 enabled=1 gpgcheck=1
sudo rpm --import /tmp/redis.key && sudo yum install redis
# Docker
docker run -d --name redis -p 6379:6379 redis
# macOS
brew install redis && brew services start redis
```

**Валидация установки:**
```bash
redis-server --version
# → Redis server v=8.10.2 ...
redis-cli PING
# → PONG
redis-cli INFO server | grep redis_version
# → redis_version:8.10.2
```

Подключение к удалённому инстансу: `redis-cli -h <хост> -p <порт> -a <пароль>`; выбор БД — ключ `-n <db>` (например, `redis-cli -n 1`). Пароль в `-a` виден в списке процессов хоста.

### Шаг 2: Тюнинг ядра Linux (критично для Prod)
```bash
# 1. Отключение Transparent Huge Pages (вызывает задержки при снапшотах)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
# 2. Увеличение лимита соединений
sudo sysctl -w net.core.somaxconn=65535
# 3. Разрешение overcommit памяти (официальная рекомендация Redis:
#    избегает ошибок fork при BGSAVE/AOF-rewrite)
echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Шаг 3: Базовая конфигурация (`/etc/redis/redis.conf`)
```conf
# Привязка и безопасность (пароль задается вручную, по умолчанию его нет)
bind 127.0.0.1 ::1
protected-mode yes
requirepass secure_password_2026

# Память
maxmemory 4gb
maxmemory-policy allkeys-lru

# Персистентность (defaults 7.x+)
save 3600 1 300 100 60 10000
appendonly yes
appendfsync everysec

# Дефрагментация
activedefrag yes
```

### Справочник параметров (значения по умолчанию)

| Параметр | Default | Назначение |
| :--- | :--- | :--- |
| `bind` / `protected-mode` | 127.0.0.1 (пакеты) / yes | Интерфейсы; защита без пароля |
| `port` / `daemonize` / `supervised` | 6379 / no / no | Порт; фоновый режим (в пакетах — systemd) |
| `dir` / `dbfilename` / `databases` | ./ / dump.rdb / 16 | Рабочий каталог, RDB-файл, число БД |
| `maxmemory` / `maxmemory-policy` | 0 (без лимита) / noeviction | Лимит и политика вытеснения |
| `maxmemory-samples` / `lfu-log-factor` / `lfu-decay-time` | 5 / 10 / 1 | Точность LRU/LFU |
| `save` / `stop-writes-on-bgsave-error` / `rdbchecksum` | 3600 1 300 100 60 10000 / yes / yes | Снапшоты RDB |
| `appendonly` / `appendfsync` | no / everysec | AOF: журнал и режим fsync |
| `auto-aof-rewrite-percentage` / `auto-aof-rewrite-min-size` / `aof-use-rdb-preamble` | 100 / 64mb / yes | Авто-компактизация AOF |
| `maxclients` / `timeout` / `tcp-keepalive` | 10000 / 0 / 300 | Соединения |
| `io-threads` / `hz` / `dynamic-hz` | 1 / 10 / yes | Потоки I/O; частота фоновых циклов |
| `hash-max-listpack-entries` / `hash-max-listpack-value` | 128 / 64 | Пороги listpack-кодировки хешей |
| `set-max-intset-entries` | 512 | Порог intset-кодировки множеств |
| `zset-max-listpack-entries` / `zset-max-listpack-value` | 128 / 64 | Пороги listpack-кодировки sorted sets |
| `list-max-listpack-size` | -2 (8 КБ) | Размер quicklist-ноды |
| `activedefrag-threshold-lower` / `-upper` / `-cycle-min` / `-cycle-max` | 10 / 100 / 1 / 25 | Параметры активной дефрагментации |
| `slowlog-log-slower-than` / `slowlog-max-len` | 10000 (10 мс) / 128 | Медленные команды |
| `latency-monitor-threshold` | 0 (выключен) | Мониторинг задержек |
| `notify-keyspace-events` | "" | Keyspace notifications (выключены) |
| `proto-max-bulk-len` | 512mb | Максимальный размер значения |
| `repl-backlog-size` / `min-replicas-to-write` / `min-replicas-max-lag` | 1mb / 0 / 10 | Репликация |
| `replica-serve-stale-data` / `replica-read-only` / `replica-priority` | yes / yes / 100 | Поведение реплик |
| `cluster-enabled` / `cluster-config-file` / `cluster-node-timeout` | no / nodes.conf / 15000 | Cluster |
| `cluster-require-full-coverage` | yes | Отказ при непокрытых слотах |
| `loglevel` | notice | Детальность логов |

Изменение параметров в рантайме: `CONFIG SET <param> <value>`; сохранение в файл: `CONFIG REWRITE`.

## Эксплуатация

### Бэкапы и восстановление
```bash
redis-cli BGSAVE                    # фоновый снапшот (fork)
redis-cli LASTSAVE                  # время последнего снапшота
redis-cli BGREWRITEAOF              # компактизация AOF
redis-check-rdb /var/lib/redis/dump.rdb
redis-check-aof --fix /var/lib/redis/appendonlydir/appendonly.aof.1.incr.aof
```
Восстановление: остановить Redis, скопировать `dump.rdb` в `dir` (или каталог `appendonlydir/` целиком для AOF), запустить. `BGSAVE` пишет во временный файл и атомарно переименовывает — копирование `dump.rdb` после завершения `BGSAVE` безопасно. С 8.10 — команда `BACKUP` для node-side инкрементальных бэкапов на основе MP-AOF. RDB/AOF-файлы размещайте на отдельном диске от данных и ОС.

### Мониторинг
```bash
redis-cli INFO server       # версия, uptime, ОС
redis-cli INFO clients      # connected_clients, blocked_clients
redis-cli INFO memory       # used_memory, mem_fragmentation_ratio, maxmemory
redis-cli INFO stats        # instantaneous_ops_per_sec, keyspace_hits/misses, evicted_keys
redis-cli INFO persistence  # rdb_last_bgsave_status, aof_last_rewrite_status
redis-cli INFO replication  # role, connected_slaves, master_repl_offset
redis-cli INFO keyspace     # ключей на БД, с истекающим TTL
redis-cli INFO all          # все разделы сразу (агрегат)
```
Ключевые метрики: hit rate = `keyspace_hits / (keyspace_hits + keyspace_misses)`; `mem_fragmentation_ratio` > 1.5 — фрагментация; рост `evicted_keys` — не хватает `maxmemory`; разница replication offset > 10000 — лаг репликации. Углубленная диагностика: `MEMORY STATS`/`MEMORY USAGE key`/`MEMORY DOCTOR`/`MEMORY PURGE`, `LATENCY DOCTOR`/`LATEST`/`HISTORY <event>`, `SLOWLOG GET 10`, `HOTKEYS` (8.6+), `redis-cli --stat`/`--bigkeys`/`--memkeys`/`--latency`/`--hotkeys`/`--scan --pattern "user:*"`. Экспорт в Prometheus — через **[Redis Exporter](../Prometheus/Exporters/redis_exporter.md)**.

Точный размер ключа: `MEMORY USAGE key` оценивает коллекции сэмплированием (по умолчанию 5 вложенных значений); `SAMPLES 0` обходит все элементы и даёт точный результат:
```bash
redis-cli MEMORY USAGE big_hash SAMPLES 0
# → (integer) 480
```
Журнал медленных команд: `SLOWLOG GET <N>` (последние N записей, по умолчанию 10), `SLOWLOG LEN` (длина), `SLOWLOG RESET` (очистка — записи теряются безвозвратно).

### Нагрузочное тестирование (redis-benchmark)
```bash
# Краткий вывод: 100k запросов, 50 клиентов, pipeline глубиной 10
redis-benchmark -q -n 100000 -c 50 -P 10
# Только SET/GET, payload 1 КБ, случайные ключи из диапазона 1M
redis-benchmark -t set,get -d 1024 -r 1000000 -n 1000000 -q
```
Флаги: `-h`/`-p` (хост/порт), `-c` (параллельных клиентов, default 50), `-n` (всего запросов, default 100000), `-d` (размер значения SET/GET, байт, default 3), `-P` (глубина pipeline, default 1 — без pipeline), `-t` (подмножество тестов), `-r` (диапазон случайных ключей), `-q` (только query/sec), `--cluster` (режим кластера), `--threads` (многопоточность). Без `-P` pipeline не измеряется — а именно он основной рычаг throughput.

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `OOM command not allowed` | `maxmemory` + `noeviction` | `INFO memory`, `--bigkeys` | Увеличить `maxmemory`, сменить политику, разбить big keys |
| Всплески задержек | THP, тяжёлые команды, fork | `LATENCY DOCTOR`, `SLOWLOG GET 10`, `--latency` | `SCAN` вместо `KEYS`, отключить THP, не совмещать fork с нагрузкой |
| Ошибки `fork` при BGSAVE | overcommit, нехватка памяти | `INFO persistence`, `dmesg` | `vm.overcommit_memory=1`, свободная RAM |
| Replication lag | сеть, большие ключи | `INFO replication` (offset diff) | `repl-backlog-size`, сеть, `WAIT` для критичных записей |
| `mem_fragmentation_ratio` > 1.5 | фрагментация jemalloc | `INFO memory` | `activedefrag yes`, `MEMORY PURGE`, рестарт с реплики |
| Рост `evicted_keys` | не хватает памяти | `INFO stats` | Больше RAM, политика вытеснения, TTL |
| Рост `connected_clients` | утечка соединений | `CLIENT LIST`, `INFO clients` | Пул соединений, `timeout` в клиенте |
| Cluster `fail` state | непокрытые слоты | `CLUSTER INFO`, `CLUSTER NODES`, `redis-cli --cluster check` | Назначить слоты, `redis-cli --cluster fix` |
| `MOVED`/`ASK` ошибки | клиент без Cluster-поддержки | логи клиента | Smart client с кэшем слотов |
| Медленный `DEL`/`EXPIRE` | big key | `SLOWLOG`, `OBJECT ENCODING` | `UNLINK`, разбить ключ на части |
| Рост AOF | частые записи | `INFO persistence` | `BGREWRITEAOF`, `auto-aof-rewrite-*` |
| Зависшие клиенты | блокирующие команды | `CLIENT LIST`, `SLOWLOG` | Таймауты в клиенте, `CLIENT KILL` |

`redis-cli monitor` показывает команды в реальном времени, но снижает производительность — используйте только в диагностике, не в постоянном мониторинге.

### Полезные однострочники
```bash
# Суммарная память ключей по паттерну (MB)
redis-cli --scan --pattern 'session:*' | xargs -n1 redis-cli MEMORY USAGE | awk '{sum+=$1} END{print sum/1024/1024" MB"}'
# Безопасное удаление ключей по паттерну (SCAN вместо блокирующего KEYS)
redis-cli --scan --pattern 'cache:*' | xargs -r redis-cli DEL
# Долгоживущие/простаивающие соединения (сортировка по idle)
redis-cli CLIENT LIST | tr ' ' '\n' | grep -E 'addr=|age=|idle=' | paste - - - | sort -t= -k3 -rn | head
```

## Лучшие практики

- Оставляйте 20–30% RAM под fork, репликацию и overhead ОС; `maxmemory` — не более 70–80% RAM хоста.
- `SCAN`/`HSCAN`/`SSCAN`/`ZSCAN` вместо `KEYS`/`SMEMBERS`/`HGETALL` в production.
- Pipeline и пул соединений (**[Connection Pooling](../Concepts/Caching/caching_connection_pooling.md)**); избегайте big keys (сотни КБ и больше) — они блокируют `DEL`, `EXPIRE` и вытеснение.
- TTL на всех кэш-ключах; `noeviction` только для роли первичной БД.
- `min-replicas-to-write 1` защищает от потерь при падении реплики (ценой отклонения записей); `WAIT` — для критичных операций.
- Отдельные диски под RDB/AOF; NTP на всех нодах; регулярное тестирование failover (`SENTINEL FAILOVER`, `CLUSTER FAILOVER`).
- ACL вместо общего пароля: отдельные пользователи на сервис с минимальными правами; `ACL DRYRUN` перед применением.
- Паттерны кэширования (cache-aside, write-through, инвалидация) — в **[Паттерны кэширования](../Concepts/Caching/caching_patterns.md)**; keyspace notifications — в **[Keyspace Notifications](../Concepts/Caching/caching_keyspace_notifications.md)**.

## Ограничения и крайние случаи

- **Single-threaded execution:** CPU-bound команды (`KEYS`, `SMEMBERS`, `SORT`, Lua) блокируют всех клиентов; держите их вне горячего пути.
- **Fork latency:** задержка `BGSAVE`/AOF-rewrite пропорциональна размеру датасета; на больших БД (десятки ГБ) планируйте окна сохранения.
- **Pub/Sub:** fire-and-forget — сообщения не сохраняются и не повторяются при переподключении.
- **Cluster:** 16384 слотов; `maxclients` 10000 по умолчанию; keyspace notifications выключены по умолчанию.
- **Шифрование данных на диске** в Open Source не предусмотрено — ответственность дискового шифрования на уровне ОС.
- **Асинхронная репликация:** окно потери данных ~1–2 секунды при failover; см. **[Redis HA](../Concepts/Caching/caching_redis_ha.md)**.
- **8.6 limitation:** не комбинируйте `XADD IDMP/IDMPAUTO` с `appendonly yes` + `aof-use-rdb-preamble no` (нестандартная конфигурация) — исправление в следующем патч-релизе.
- **Vector Set:** beta в 8.0 (API может меняться); RDB-формат vector sets несовместим с big-endian машинами (исправлено в 8.0.4).
- **Безопасность 8.8:** CVE-2026-62356 (OOB write при загрузке CMSketch RDB) и другие — обновляйтесь до 8.8.2+ или 8.10.

## Обновление версий

- **7.4 → 8.0:** модули интегрированы (отдельные RediSearch/RedisJSON/RedisTimeSeries/RedisBloom не нужны); ACL-категории расширены — выгрузите `ACL LIST` и проверьте правила через `ACL DRYRUN` до апгрейда; Community Edition переименован в Open Source; RDB vector sets несовместим с big-endian.
- **8.6:** новые политики `volatile-lrm`/`allkeys-lrm`, `HOTKEYS`, идемпотентность Streams (с ограничением выше), TLS-cert аутентификация.
- **8.8:** Array, `INCREX`, `XNACK`, field-level hash notifications; security fixes.
- **8.10:** compact hashes, `BACKUP`, `HIMPORT`, `LMOVEM`/`BLMOVEM`, `SUNIONCARD`/`SDIFFCARD`, расширения JSONPath.
- Rolling upgrade — по одной ноде с проверкой совместимости протокола; см. **[Redis HA](../Concepts/Caching/caching_redis_ha.md)**.

## Дополнительная информация

### Сравнение с форками и Memcached (2026)

| Параметр | Redis 8.10 | Valkey 9.1 | Redict | Dragonfly | Memcached |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Лицензия** | RSALv2/SSPLv1/AGPLv3 | BSD-3-Clause | LGPL-3.0-only | BSL | BSD |
| **Новые типы (Array, Vector Set, JSON, TS)** | Нативно | Через модули (valkey-search и др.) | Нет (форк 7.2.4) | Частично | Нет |
| **Потоки** | Threaded I/O (6.0+) | Асинхронный I/O | — | Multi-core event loop | Многопоточный |

Полное сравнение Redis и Memcached — **[Redis vs Memcached](./redis_vs_memcached.md)**.

### Смежные темы

- Обзор кэширования — **[Кэширование: обзор](../Concepts/Caching/caching_overview.md)**
- Политики вытеснения — **[Caching Eviction Policies](../Concepts/Caching/caching_eviction_policies.md)**
- Высокая доступность (Sentinel/Cluster) — **[Redis HA](../Concepts/Caching/caching_redis_ha.md)**
- Распределенные блокировки — **[Distributed Locks](../Concepts/Caching/caching_distributed_locks.md)**
- Репликация в БД — **[Репликация: теория](./Concepts/replication.md)**
- Мониторинг — **[Redis Exporter](../Prometheus/Exporters/redis_exporter.md)**
