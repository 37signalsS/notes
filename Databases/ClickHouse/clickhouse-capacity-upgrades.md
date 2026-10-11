# ClickHouse — Capacity Planning, обновления и HA

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Capacity planning** — оценка требуемых ресурсцев (хранилище, RAM, CPU, IOPS, сеть) на основе объёма данных и паттернов нагрузки. Включает профилирование текущей нагрузки, моделирование роста и установку порогов масштабирования.

**Rolling upgrade** — обновление кластера по одному узлу без простоя: обновили реплику, дождались догона, перешли к следующей. Требует, чтобы кластер оставался доступным для клиентов на остальных узлах.

**LTS (Long Term Support)** — релиз с длительной поддержкой (например, 26.8 LTS, поддерживается до августа 2027 года). **Stable** — обычный ежемесячный релиз (например, 26.9).

**Connection pooling** — переиспользование соединений к ClickHouse (на стороне клиента или прокси) для снижения накладных расходов на установку TCP/TLS.

**HAProxy** — TCP/HTTP-балансировщик, используемый для распределения клиентских подключений между узлами ClickHouse и реализации health check'ов.

**CHProxy** — кэширующий HTTP-прокси для ClickHouse с поддержкой connection pooling, rate limiting, автоматического переключения на healthy-реплики и запросов в native-протоколе через TCP.

**Deprecation** — пометка настройки/функции как устаревшей; удаляется в одной из следующих мажорных версий.

**is_obsolete** — колонка в `system.settings` (UInt8), показывающая, что настройка больше не поддерживается. Используется вместо поиска по `description LIKE '%deprecated%'`.

**tier** — колонка в `system.settings` (Enum8), описывающая уровень поддержки функции: `Production` (0), `Obsolete` (4), `Experimental` (8), `Beta` (12), `PrivatePreview` (16).

**system.settings_changes** — системная таблица, содержащая информацию об изменениях настроек между версиями ClickHouse. Позволяет проанализировать breaking changes перед upgrade.

## Основные концепции

### Методология sizing

#### Профилирование нагрузки

Перед расчётом ресурсов необходимо классифицировать нагрузку:

| Параметр | Как измерить | Инструменты |
| :--- | :--- | :--- |
| **Тип нагрузки** | Read-heavy / write-heavy / mixed | `system.query_log`, `query_log` |
| **Пик QPS** | Максимальное количество запросов в секунду | `system.metrics.Query`, Grafana |
| **Средний размер запроса** | `read_rows` / `read_bytes` | `system.query_log` |
| **Паттерн доступа** | Точечные запросы / сканирование / агрегации | `EXPLAIN`, `query_log` |
| **Сезонность** | Пики в business hours | Prometheus |
| **INSERT rate** | Строк/секунду при вставке | `system.query_log` |
| **Максимальная сложность** | Самый тяжелый запрос | `system.query_log ORDER BY memory_usage DESC` |

#### Формулы sizing

**Хранилище:**
```
raw_data × compression_ratio × replication_factor × headroom
```
- `compression_ratio` — типично 5–10× для ClickHouse (зависит от данных; кодеки `ZSTD` дают больше, чем `LZ4`).
- `replication_factor` — обычно 2–3.
- `headroom` — 30–50% на рост и фрагментацию частей.

**RAM:**
- Для запросов: `max_memory_usage` × `max_concurrent_queries` + запас.
- Для слияний: зависит от нагрузки на merges; мониторьте `system.asynchronous_metrics.MemoryResident`.
- Правило: RAM ≥ 2× горячего набора данных (working set).

**Диск (IOPS/пропускная способность):**
- Слияния (merges) I/O-интенсивны — SSD/NVMe для продакшена.
- Вставки и слияния конкурируют за I/O — мониторьте `system.merges` и `system.disks`.

**Сеть:**
- Репликация: трафик вставок × `replication_factor`.
- Межсерверный обмен (порт 9009): Distributed-запросы, загрузка частей.

### Мониторинг роста

```sql
-- Текущий размер таблиц
SELECT database, table,
       formatReadableSize(total_bytes) AS total,
       formatReadableSize(data_uncompressed_bytes) AS uncompressed
FROM system.tables
WHERE engine LIKE '%MergeTree%'
ORDER BY total_bytes DESC;

-- Динамика роста (за период)
SELECT toDate(event_time) AS day, sum(read_rows) AS rows_inserted
FROM system.query_log
WHERE type = 'QueryFinish' AND query LIKE 'INSERT%'
GROUP BY day ORDER BY day;

-- Размер частей (фрагментация)
SELECT table, count() AS parts,
       formatReadableSize(sum(bytes_on_disk)) AS size
FROM system.parts
WHERE active
GROUP BY table ORDER BY parts DESC;

-- Скорость вставки (строк/сек)
SELECT count() / 60 AS rows_per_sec
FROM system.query_log
WHERE type = 'QueryFinish' AND query LIKE 'INSERT%'
  AND event_time > now() - INTERVAL 1 MINUTE;
```

### Пороги масштабирования

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| **CPU utilization** | > 80% > 5 мин | Добавить узлы или оптимизировать запросы |
| **Memory usage** | > 85% от `max_memory_usage` | Увеличить RAM или включить External Aggregation |
| **Disk usage** | > 85% | Добавить диск или включить Tiered Storage (S3) |
| **Parts per table** | > 10 000 | Настроить `async_insert`, проверить батчинг |
| **Replication delay** | `absolute_delay > 60` | Проверить сеть, диски, Keeper |
| **Active queries** | > `max_concurrent_queries * 0.8` | Добавить узлы или настроить очередь запросов |
| **Merge backlog** | > 10 merges на таблицу | Проверить I/O, `merge_max_block_size` |

### Обновления (upgrade)

#### Совместимость

- **Keeper** обновляется первым (обратно совместим — использует Raft, алгоритм добавления/удаления узлов поддерживается).
- **ClickHouse** обратно совместим в пределах мажорной линии (например, 26.9.1 → 26.9.5); между LTS — проверяйте breaking changes.
- **Между LTS-релизами** (например, 26.3 → 26.8) — десятки breaking changes и ~70 изменённых дефолтов настроек. Обязательно сверяйте changelog.

#### Pre-upgrade checklist

1. **Сверить changelog** на breaking changes и изменённые дефолты настроек.
2. **Найти deprecated-настройки** в конфиге:
   ```sql
   -- Используйте is_obsolete и tier вместо description LIKE '%deprecated%'
   SELECT name, value, default, is_obsolete, tier
   FROM system.settings
   WHERE is_obsolete = 1 OR tier = 'Obsolete';
   ```
3. **Проверить изменённые настройки** между версиями:
   ```sql
    -- system.settings_changes показывает изменения настроек между версиями
    -- Перед upgrade проверьте изменения во всех версиях новее текущей
    SELECT version, changes
    FROM system.settings_changes
    WHERE version >= '26.4' AND version <= '26.8'
    FORMAT Vertical;
   ```
4. **Сделать бэкап** (`clickhouse-backup create pre-upgrade-$(date +%F)`).
5. **Проверить задержку репликации** (`system.replicas.absolute_delay` ≈ 0).
6. **Зафиксировать версию пакета** (pin) для отката.
7. **Тестировать upgrade в staging** — зеркалировать продакшен на тестовый кластер.

#### Rolling upgrade

1. Обновить ClickHouse Keeper (все узлы).
2. Поочерёдно: остановить ClickHouse на реплике → обновить пакеты → запустить → дождаться догона (`absolute_delay` ≈ 0) → следующая реплика.
3. Проверить `system.clusters`, `system.replicas`, работоспособность запросов.

```bash
# Pin версии (apt) — обязательно включать clickhouse-common-static
apt-get install clickhouse-server=26.8.15.10 clickhouse-client=26.8.15.10 clickhouse-common-static=26.8.15.10

# Проверить версию
clickhouse-client --query "SELECT version()"

# Проверить, что все узлы в кластере на одной версии
clickhouse-client --query "SELECT hostName(), version() FROM system.clusters WHERE cluster = 'your_cluster'"
```

**Downgrade:** возможен, но рискован (формат частей может измениться). Тестируйте на стенде; при необходимости — восстановление из бэкапа. Всегда проверяйте changelog на обратную несовместимость перед downgrade.

#### Валидация после обновления

```sql
-- Проверка версии на всех узлах
SELECT hostName(), version() FROM system.clusters WHERE TCPPort IS NOT NULL;

-- Проверка состояния реплик
SELECT database, table, is_readonly, absolute_delay, is_session_expired
FROM system.replicas
WHERE absolute_delay > 0 OR is_readonly = 1;

-- Проверка отсутствия ошибок в логах
SELECT count() AS errors
FROM system.query_log
WHERE type = 'ExceptionWhileProcessing'
  AND event_time > now() - INTERVAL 5 MINUTE;

-- Проверка, что запросы работают
SELECT 1;
```

### Валидация после изменения ёмкости

После добавления/удаления узлов или изменения ресурсов:

```sql
-- 1. Все узлы видят новую конфигурацию
SELECT hostName(), version(), uptime FROM system.clusters WHERE cluster = 'your_cluster';

-- 2. Баланс распределения parts между узлами
SELECT hostName(), count() AS parts
FROM system.parts
WHERE active AND table IN ('events')
GROUP BY hostName() ORDER BY parts DESC;

-- 3. Репликация в состоянии
SELECT database, table, absolute_delay, is_readonly
FROM system.replicas
WHERE absolute_delay > 0 OR is_readonly = 1;

-- 4. Нет ошибок в логах после изменения
SELECT count() AS errors
FROM system.query_log
WHERE type = 'ExceptionWhileProcessing'
  AND event_time > now() - INTERVAL 10 MINUTE;
```

### HA и балансировка (HAProxy, CHProxy)

#### Конфигурация HAProxy

```haproxy
# /etc/haproxy/haproxy.cfg
frontend clickhouse_http
    bind *:8123
    default_backend ch_http

frontend clickhouse_native
    bind *:9000
    default_backend ch_native

backend ch_http
    option httpchk GET /ping
    # Ограничение количества соединений на реплику
    maxconn 1000
    # Максимальная очередь запросов в балансировщике
    maxqueue 100
    server ch-01 clickhouse-01:8123 check inter 5s fall 3 rise 2
    server ch-02 clickhouse-02:8123 check inter 5s fall 3 rise 2

backend ch_native
    option tcp-check
    # health check для native-протокола: TCP-подключение к порту 9000
    server ch-01 clickhouse-01:9000 check inter 5s fall 3 rise 2
    server ch-02 clickhouse-02:9000 check inter 5s fall 3 rise 2
```

**Health check:** HTTP `/ping` возвращает `Ok.` (порт 8123). Для native-протокола — TCP-проверка порта 9000.

**Настройки балансировки:**
- `option httpchk GET /ping` — более надёжный health check для HTTP-бэкенда.
- `inter 5s` — интервал проверки каждые 5 секунд.
- `fall 3 rise 2` — три падения для пометки сервера DOWN, два успешных для UP.
- `maxconn 1000` — лимит одновременных соединений на один сервер.
- `maxqueue 100` — максимальная длина очереди запросов в балансировщике.

#### Паттерны балансировки

- **Read-only балансировка** — HAProxy перед несколькими репликами для SELECT.
- **Write через Distributed** — вставка в Distributed-таблицу на любом узле (`insert_distributed_sync = 1` для синхронности).
- **`prefer_localhost`** — при запросе через Distributed на том же узле использовать локальную таблицу (меньше сетевых hops).
- **`max_replica_delay_for_distributed_queries`** — фencing lagging replicas: если реплика отстаёт более N секунд, она исключается из запроса.
  ```sql
  -- Исключать реплики с задержкой > 10 секунд
  SET max_replica_delay_for_distributed_queries = 10;
  SET load_balancing = 'in_order';
  SELECT count() FROM events_all;
  ```

#### CHProxy (альтернатав HAProxy)

CHProxy — это кэширующий прокси, который добавляет:

- **Connection pooling** — переиспользование соединений к ClickHouse.
- **Query caching** — кэш результатов запросов с гибкой инвалидацией по TTL.
- **Automatic failover** — переключение на healthy-реплику при ошибке.
- **Rate limiting** — ограничение количества запросов от одного пользователя.
- **Request throttling** — защита от burst-ов.

CHProxy особенно полезен для read-heavy нагрузки с повторяющимися запросами (дашборды, BI).

### Connection pooling и лимиты

**Настройки сервера (config.xml):**

```xml
<!-- config.d/limits.xml -->
<clickhouse>
    <max_connections>4096</max_connections>
    <max_concurrent_queries>200</max_concurrent_queries>
    <keep_alive_timeout>3</keep_alive_timeout>
</clickhouse>
```

- `max_connections` — максимум одновременных соединений (по умолчанию 100, для продакшена ≥ 4096).
- `max_concurrent_queries` — максимум одновременных запросов (0 = unlimited).
- `keep_alive_timeout` — время жизни keep-alive соединения для HTTP (сек, по умолчанию 3).

**Настройки пользователя (users.xml) — idle_connection_timeout:**

```xml
<!-- users.d/profile.xml -->
<profiles>
    <default>
        <!-- Таймаут неактивного TCP-соединения (сек, по умолчанию 3600) -->
        <idle_connection_timeout>10</idle_connection_timeout>
    </default>
</profiles>
```

`idle_connection_timeout` — это **session-настройка**, а не серверная. Устанавливается в профилях пользователей (`users.xml`), а не в `config.xml`.

**На стороне клиента:** используйте пул соединений драйвера (JDBC/ODBC/Python) — создание соединения к ClickHouse дорого.

## Практические сценарии

### Worksheet: sizing кластера

| Параметр | Значение | Как оценить |
| :--- | :--- | :--- |
| Сырые данные/мес | 1 TB | Источники (Kafka, логи, БД) |
| Сжатие | 7× | Тест на репрезентативной выборке |
| Репликация | 3 | Требования HA |
| Headroom | 40% | Рост + фрагментация |
| **Хранилище/узел** | `1TB × 12 × 3 × 1.4 / N_узлов` | Формула выше |
| RAM/узел | 128–256 GB | 2× working set + merges |
| CPU/узел | 16–32 ядра | Параллелизм запросов + merges |
| Диск | NVMe, 3–5 GB/s | merges + вставки |
| Сеть | 10 GbE+ | Репликация + Distributed |

### Prerequisites перед обновлением

| Требование | Как проверить |
| :--- | :--- |
| **Бэкап** | `clickhouse-backup create pre-upgrade-$(date +%F)`; проверить `clickhouse-backup list` |
| **Дисковое пространство** | `system.disks` — free ≥ 30% (для parts-форматов и временных файлов) |
| **Задержка репликации** | `system.replicas.absolute_delay` ≈ 0 на всех узлах |
| **Staging-тест** | Зеркалировать прод на тест; выполнить upgrade |
| **Pin версии** | Зафиксировать пакет (`clickhouse-common-static` включительно) для отката |
| **Чтение changelog** | Сверить breaking changes и изменённые дефолты (через `system.settings_changes`) |

### Мониторинг перед обновлением

```sql
-- Задержка репликации (должна быть ~0 перед обновлением следующей реплики)
SELECT database, table, absolute_delay, is_session_expired
FROM system.replicas;

-- Активные запросы (дождаться завершения тяжёлых)
SELECT count() FROM system.processes;

-- Deprecated/obsolete настройки в конфиге
SELECT name, value, is_obsolete, tier
FROM system.settings
WHERE is_obsolete = 1 OR tier = 'Obsolete';

-- Изменения настроек между версиями (перед upgrade на 26.8)
SELECT version, changes
FROM system.settings_changes
WHERE version >= '26.4' AND version <= '26.8';

-- Состояние Keeper/ZooKeeper
SELECT * FROM system.zookeeper_connection;

-- Проверка свободного места на дисках
SELECT name, path,
       formatReadableSize(free_space) AS free,
       formatReadableSize(total_space) AS total,
       round(free_space / total_space * 100, 1) AS free_pct
FROM system.disks;
```

### Обновление через apt (пример)

```bash
# 1. Бэкап
clickhouse-backup create pre-upgrade-$(date +%F)

# 2. Обновить Keeper (на всех узлах)
apt-get update && apt-get install clickhouse-keeper=26.8.15.10

# 3. Проверить статус Keeper
echo ruok | nc localhost 2181
# → imok

# 4. Обновить ClickHouse (по одной реплике)
systemctl stop clickhouse-server
# Обязательно включайте clickhouse-common-static при pin
apt-get install clickhouse-server=26.8.15.10 clickhouse-client=26.8.15.10 clickhouse-common-static=26.8.15.10
systemctl start clickhouse-server

# 5. Дождаться догона
watch -n5 "clickhouse-client --query \"SELECT absolute_delay FROM system.replicas\""

# 6. Повторить для следующей реплики
```

### Обновление через yum/dnf (RHEL/CentOS)

```bash
# 1. Бэкап
clickhouse-backup create pre-upgrade-$(date +%F)

# 2. Обновить Keeper
yum install clickhouse-keeper-26.8.15.10

# 3. Обновить ClickHouse по одной реплике
systemctl stop clickhouse-server
yum install clickhouse-server-26.8.15.10 clickhouse-client-26.8.15.10 clickhouse-common-static-26.8.15.10
systemctl start clickhouse-server
```

### Downgrade (откат)

Downgrade возможен, но рискован — формат частей данных может измениться между версиями. Перед откатом:

1. Проверьте changelog на обратную несовместимость.
2. Восстановите из бэкапа, сделанного до upgrade.
3. Тестируйте downgrade на стенде.

```bash
# Откат до предыдущей версии
systemctl stop clickhouse-server
apt-get install clickhouse-server=26.3.42.3 clickhouse-client=26.3.42.3 clickhouse-common-static=26.3.42.3
systemctl start clickhouse-server
```

### Очистка после обновления

После успешного upgrade/downgrade:

```bash
# 1. Очистить apt cache старых версий (Debian/Ubuntu)
apt-get clean && apt-get autoclean
apt-get autoremove --purge

# 2. Очистить yum cache (RHEL/CentOS)
yum clean all

# 3. Проверить отсутствие старых бинарников
dpkg -l | grep clickhouse  # или: rpm -qa | grep clickhouse

# 4. Очистить journalctl логи (если не важны)
journalctl --vacuum-time=30d --unit=clickhouse-server

# 5. Удалить старые логи
find /var/log/clickhouse-server/ -name "*.log.*" -mtime +30 -delete
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Version mismatch` после обновления | Узлы на разных версиях | Завершить rolling upgrade; проверить все узлы |
| `Unknown setting` после обновления | Настройка удалена в новой версии | Удалить/заменить настройку; сверить changelog |
| `Setting ... is deprecated` | Настройка устарела | Заменить на актуальную (см. `is_obsolete` в `system.settings`) |
| `is_obsolete = 1` предупреждение | Настройка помечена как obsolete | Заменить настройку; `SELECT name, is_obsolete, tier FROM system.settings WHERE is_obsolete = 1 OR tier = 'Obsolete'` |
| HAProxy не переключает | Health check не проходит | Проверить `/ping` на 8123, порт, `listen_host` |
| Много соединений в TIME_WAIT | Нет keep-alive / короткий timeout | Настроить пул соединений; `keep_alive_timeout` |
| `Too many simultaneous queries` | `max_concurrent_queries` исчерпан | Увеличить лимит или оптимизировать запросы |
| Диск заполнен после обновления | Новые форматы частей, старые не удалены | Проверить `system.parts`, `old_parts_lifetime` |
| Реплика отстаёт после upgrade | Сеть или I/O | Проверить `absolute_delay`, `system.replication_queue`, `system.replicas` |
| Keeper не восстанавливается | Потеря кворума | Восстановить из снапшота Keeper (см. [Бэкапы](./clickhouse-backup.md#бэкап-clickhouse-keeper)) |
| Запросы читают устаревшие данные | Реплика отстаёт | Включить `max_replica_delay_for_distributed_queries` для fencing |

## Лучшие практики

1. **Sizing с запасом 30–50%** — рост данных и фрагментация частей.
2. **Тестируйте сжатие** на репрезентативной выборке перед закупкой дисков.
3. **Профилируйте нагрузку** перед sizing — QPS, размер запросов, сезонность.
4. **Rolling upgrade** — Keeper первым, затем реплики по одной, с контролем `absolute_delay`.
5. **Pin версий** пакетов (включая `clickhouse-common-static`) для контролируемого отката.
6. **Сверяйте changelog** между LTS-релизами — десятки breaking changes.
7. **Используйте `system.settings_changes`** для проверки изменений настроек перед upgrade.
8. **HAProxy с health check** (`/ping` на 8123) для read-only балансировки.
9. **Fencing lagging replicas** через `max_replica_delay_for_distributed_queries`.
10. **Пул соединений** на стороне клиента — создание соединения дорого.
11. **Мониторьте рост** (`system.tables`, `system.parts`) для capacity planning.
12. **LTS для продакшена**, Stable для тестирования новых возможностей.
13. **Алерты на пороги** — CPU > 80%, RAM > 85%, Disk > 85%, `absolute_delay` > 60.
14. **Очищайте старые пакеты и логи** после upgrade/downgrade (`apt-get clean`, `journalctl --vacuum-time`, `find /var/log/... -mtime +30 -delete`).
15. **Проверяйте ёмкость после изменений** — все узлы должны видеть новую конфигурацию, parts должны быть сбалансированы.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Rolling update в кластере — **[Кластер](./clickhouse-cluster.md#обновление-без-простоя-rolling-updates)**.
- Бэкапы перед обновлением — **[Бэкапы](./clickhouse-backup.md)**.
- Мониторинг и системные таблицы — **[Мониторинг](./clickhouse-monitoring.md)**.
- Файловая система и хранение — **[Файловая система](./clickhouse-filesystem-storage.md)**.
- Производительность и SLO — **[Производительность](./clickhouse-performance.md#ключевые-метрики-sre)**.
- Высокая конкурентность и pooling — **[Высокая конкурентность](./clickhouse-high-concurrency.md)**.

### Ресурсы

- [Документация: Changelog](https://clickhouse.com/docs/resources/changelogs)
- [Документация: Upgrade](https://clickhouse.com/docs/ru/operations/upgrade)
- [Документация: System tables — settings](https://clickhouse.com/docs/ru/reference/system-tables/settings)
- [Документация: System tables — settings_changes](https://clickhouse.com/docs/ru/reference/system-tables/settings_changes)
- [Документация: System tables — replicas](https://clickhouse.com/docs/ru/reference/system-tables/replicas)
- [HAProxy](https://www.haproxy.org/)
- [CHProxy](https://github.com/Altinity/chproxy)