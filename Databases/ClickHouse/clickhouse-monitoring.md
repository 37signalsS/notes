# ClickHouse — Мониторинг и системные таблицы

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**system.metrics** — мгновенные значения (количество активных запросов, соединений, частей). Снимок на момент запроса.

**system.events** — кумулятивные счётчики (общее число слияний, вставок, прочитанных строк с момента старта сервера).

**system.asynchronous_metrics** — периодически вычисляемые метрики (использование RAM, CPU, диска), обновляемые фоновым пулом.

**system.metric_log / system.asynchronous_metric_log** — история метрик во времени (таблицы MergeTree с TTL). Включены по умолчанию.

**system.query_log** — история запросов (текст, длительность, прочитанные строки/байты, память, тип результата).

**system.query_thread_log** — статистика по потокам выполнения запроса (полезно для анализа параллелизма).

**system.trace_log** — профилирование запроса (стек вызовов, время в каждой функции). Требует `trace_query = 1`.

**system.storage_policies** — политики хранения (диски, тома, факторы перемещения).

**system.zookeeper** — инспекция znode в ClickHouse Keeper / ZooKeeper.

## Основные концепции

### Модель метрик

| Тип | Таблица | Характер | Пример |
| :--- | :--- | :--- | :--- |
| Мгновенные | `system.metrics` | Снимок «сейчас» | `Query` (активные запросы), `Connection` |
| Кумулятивные | `system.events` | Счётчик с момента старта | `MergeTreePartsMerged`, `Query` |
| Асинхронные | `system.asynchronous_metrics` | Периодический замер | `MemoryResident`, `CPUUsage` |
| История | `system.metric_log` | Ряды во времени | `MetricLog` с TTL |

### Порты ClickHouse (справочник)

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `8123` | HTTP | HTTP-интерфейс (REST, `curl`, веб-интерфейсы) |
| `8443` | HTTPS | HTTP-интерфейс с TLS |
| `9000` | Native TCP | Нативный протокол (`clickhouse-client`, драйверы) |
| `9440` | Native TCP + TLS | Нативный протокол с TLS |
| `9009` | HTTP (inter-server) | Межсерверный обмен: репликация (загрузка частей), Distributed-запросы между серверами |
| `9363` | HTTP | Prometheus-экспортёр (`/metrics`) |
| `2181` | TCP | ClickHouse Keeper — клиентский порт (ZooKeeper-совместимый) |
| `9234` | TCP | ClickHouse Keeper — Raft-порт (внутренняя связь узлов Keeper) |

**Примечание:** в Altinity Operator метрики экспортируются через sidecar-экспортёр (порт `8888` в Service), а не напрямую на `9363`.

### SRE-метрики и SLI/SLO

Для построения дашбордов и SLO используйте ключевые метрики, доступные через `/metrics` на порту 9363:

| Метрика | system.metrics | system.events | Описание | SLO-порог |
| :--- | :--- | :--- | :--- | :--- |
| Активные запросы | `Query` | — | Текущее количество выполняющихся запросов | < 100 |
| Задержка репликации | `ReplicaAbsoluteDelay` (async) | — | Секунды отставания реплики | < 300s |
| Ошибки запросов | — | `QueryException` | Количество исключений при обработке запросов | rate < 0.1/s |
| Merge backlog | `BackgroundMergesInProgress` | `BackgroundMergesAndMutationsPoolTaskCount` | Активные слияния/мутации | < 50 |
| Память на сервере | `MemoryTracked` | — | Текущее использование памяти запросами | < 80% лимита |
| Заполнение диска | `DiskSpace` (async) | — | Доступное место на дисках | > 20% свободного |

### Включение и настройка логов

```xml
<!-- config.d/logs.xml -->
<clickhouse>
    <!-- История метрик (включена по умолчанию) -->
    <metric_log>
        <database>system</database>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
        <ttl>1</ttl>  <!-- хранение, дней -->
    </metric_log>
    <asynchronous_metric_log>
        <database>system</database>
        <flush_interval_milliseconds>60000</flush_interval_milliseconds>
        <ttl>30</ttl>
    </asynchronous_metric_log>

    <!-- Лог потоков запросов (по умолчанию выключен) -->
    <query_thread_log>
        <database>system</database>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
        <ttl>3</ttl>
    </query_thread_log>
</clickhouse>
```

## Практические сценарии

### Каталог системных таблиц

| Таблица | Назначение |
| :--- | :--- |
| `system.metrics` | Мгновенные метрики |
| `system.events` | Кумулятивные счётчики |
| `system.asynchronous_metrics` | Асинхронные метрики (RAM, CPU, диск) |
| `system.metric_log` | История мгновенных метрик |
| `system.asynchronous_metric_log` | История асинхронных метрик |
| `system.query_log` | История запросов |
| `system.query_thread_log` | Статистика потоков запросов |
| `system.trace_log` | Профилирование запросов |
| `system.text_log` | Текстовые логи сервера |
| `system.errors` | Счётчики ошибок |
| `system.processes` | Выполняющиеся запросы |
| `system.settings` | Текущие настройки сервера |
| `system.storage_policies` | Политики хранения |
| `system.disks` | Диски и их заполнение |
| `system.zookeeper` | Znode Keeper/ZooKeeper |
| `system.clusters` | Топология кластера |
| `system.replicas` | Статус реплик |
| `system.replication_queue` | Очередь репликации |
| `system.merges` | Активные слияния |
| `system.mutations` | Мутации |
| `system.parts` | Части таблиц |
| `system.dictionaries` | Словари |
| `system.grants` | Привилегии |
| `system.users` | Пользователи |
| `system.roles` | Роли |
| `system.row_policies` | Политики строк |
| `system.quotas` / `system.quota_limits` / `system.quota_usage` / `system.quotas_usage` | Квоты |
| `system.distributed_ddl_queue` | Очередь распределённого DDL (ON CLUSTER) |
| `system.distribution_queue` | Очередь асинхронных вставок в Distributed |
| `system.view_refreshes` | Статус обновлений refreshable MV |
| `system.filesystem_cache` | Кэш файлов (S3/диски) | Конфигурация — `system.filesystem_cache_settings` |

### Диагностические запросы

```sql
-- Активные запросы
SELECT query_id, user, query_duration_ms, read_rows, memory_usage
FROM system.processes ORDER BY query_duration_ms DESC;

-- Топ медленных запросов за период
SELECT query, count() AS cnt, avg(query_duration_ms) AS avg_ms,
       sum(read_rows) AS total_rows
FROM system.query_log
WHERE type = 'QueryFinish' AND event_time > now() - INTERVAL 1 HOUR
GROUP BY query ORDER BY avg_ms DESC LIMIT 10;

-- Ошибки запросов
SELECT exception, count() AS cnt
FROM system.query_log
WHERE type = 'ExceptionWhileProcessing' OR type = 'ExceptionBeforeStart'
GROUP BY exception ORDER BY cnt DESC;

-- Задержка репликации
SELECT database, table, absolute_delay, is_session_expired
FROM system.replicas WHERE absolute_delay > 60;

-- Очередь слияний
SELECT database, table, count() AS active_merges
FROM system.merges GROUP BY database, table;

-- Заполнение дисков
SELECT name, path, formatReadableSize(total_space) AS total,
       formatReadableSize(available_space) AS available,
       round(available_space / total_space * 100, 1) AS free_pct
FROM system.disks;

-- Политики хранения
SELECT * FROM system.storage_policies;

-- Инспекция znode Keeper
SELECT name, value FROM system.zookeeper WHERE path = '/clickhouse/tables';

-- Очередь распределённого DDL
SELECT * FROM system.distributed_ddl_queue ORDER BY create_time DESC LIMIT 10;

-- История метрик (RAM за последний час)
SELECT event_time, MemoryResident
FROM system.asynchronous_metric_log
WHERE metric = 'MemoryResident' AND event_time > now() - INTERVAL 1 HOUR
ORDER BY event_time;
```

### Prometheus-экспортёр

```xml
<!-- config.d/prometheus.xml -->
<clickhouse>
    <prometheus>
        <endpoint>/metrics</endpoint>
        <port>9363</port>
        <metrics>true</metrics>
        <events>true</events>
        <asynchronous_metrics>true</asynchronous_metrics>
        <status_info>true</status_info>
    </prometheus>
</clickhouse>
```

```yaml
# prometheus.yml
scrape_configs:
  - job_name: clickhouse
    static_configs:
      - targets: ['clickhouse-01:9363', 'clickhouse-02:9363']
```

### Алерты для K8s (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: clickhouse-alerts
  namespace: clickhouse
spec:
  groups:
  - name: clickhouse.rules
    rules:
    # Высокая задержка репликации
    - alert: ClickHouseReplicationLag
      expr: clickhouse_replica_absolute_delay_seconds > 300
      for: 5m
      annotations:
        summary: "Реплика {{ $labels.table }} отстаёт более 5 минут"

    # Много активных запросов (очередь)
    - alert: ClickHouseQueryQueue
      expr: clickhouse_metric_Query > 100
      for: 5m
      annotations:
        summary: "Слишком много запросов в очереди на {{ $labels.instance }}"

    # Мало свободного места
    - alert: ClickHouseDiskSpace
      expr: clickhouse_disk_available_bytes / clickhouse_disk_total_bytes < 0.2
      for: 2m
      annotations:
        summary: "Менее 20% свободного места на диске {{ $labels.disk }}"

    # Ошибки запросов
    - alert: ClickHouseQueryErrors
      expr: rate(clickhouse_event_QueryException[5m]) > 0.1
      annotations:
        summary: "Высокая частота ошибок запросов на {{ $labels.instance }}"

    # Merge backlog
    - alert: ClickHouseMergeBacklog
      expr: clickhouse_metric_backgroundPoolTask > 50
      for: 10m
      annotations:
        summary: "Нарастающая очередь слияний на {{ $labels.instance }}"
```

### Профилирование запроса

```sql
-- Включить трассировку для запроса
SELECT count() FROM logs SETTINGS trace_query = 1, log_query_settings = 1;

-- Просмотр стека вызовов
SELECT event_time, thread_number, read_rows, peak_memory_usage
FROM system.trace_log
WHERE query_id = '...'
ORDER BY event_time;
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `metric_log` пуст | Логирование отключено или таблица переполнена TTL | Проверить `<metric_log>` в `config.xml`; проверить TTL таблицы |
| `query_log` не растёт | `log_queries = 0` для пользователя | Проверить профиль пользователя; `SET log_queries = 1` |
| `query_thread_log` пуст | Не включён в `config.xml` | Добавить `<query_thread_log>` секцию |
| Порт 9363 не отвечает | Prometheus-экспортёр не настроен | Проверить `<prometheus>` в `config.xml`; перезапустить сервер |
| `system.zookeeper` пуст | Keeper не настроен или путь неверный | Проверить `<zookeeper>` в `config.xml`; `SYSTEM DROP DNS CACHE` |
| `system.processes` растёт | Runaway-запросы | `KILL QUERY WHERE ...`; см. **[Операционный SQL](./clickhouse-sql-operations.md)** |
| `metric_log` растёт быстро | Высокая частота flush, много метрик | Увеличить `flush_interval_milliseconds`, уменьшить `ttl` |
| `ReplicaAbsoluteDelay` растёт | Медленная репликация (сеть, диск) | Проверить I/O через `system.metrics`; `iostat` на ноде |
| `BackgroundMergesInProgress` > 50 | Перегрузка диска, merge backlog | Остановить чтение; добавить узлы или оптимизировать схему |
| `clickhouse_metric_Query` > 100 постоянно | Очередь запросов растёт | Анализировать `query_log`; ранжировать запросы по `memory_usage` |
| Метрики не экспортируются | `<prometheus><status>` выключен | Проверить `config.xml`; убедиться, что порт 9363 слушает `ss -tlnp` |
| K8s: метрики не скрейпятся | Service не пробрасывает порт 9363 | Проверить `service.spec.ports`; в Altinity Operator использовать порт 8888 |
| `system.disks` показывает 0 available | FUSE-диск или volume подмонтирован неправильно | Проверить `mount` на ноде; убедиться, что `storagePolicy` корректен |

## Лучшие практики

1. **Включите `metric_log` и `asynchronous_metric_log`** — история метрик необходима для capacity planning и post-mortem.
2. **`query_log` с TTL** — храните историю запросов 7–30 дней; используйте `system.query_log` для поиска медленных запросов.
3. **Алерт на задержку репликации** (`absolute_delay`) — ключевой SLO для кластера.
4. **Алерт на merge backlog** — растущая очередь слияний предшествует проблемам с производительностью.
5. **`system.disks`** — алерт на заполнение дисков (< 20% свободно).
6. **`trace_log`** для разового профилирования тяжёлых запросов (не включайте постоянно — накладные расходы).
7. **`system.distributed_ddl_queue`** — мониторьте при частых `ON CLUSTER` DDL.
8. **Экспортёр на 9363** — стандартный способ интеграции с Prometheus; в K8s с Altinity Operator — через sidecar.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Наблюдаемость (логи, метрики, трейсы, remote_write) — **[Наблюдаемость](./clickhouse-observability.md)**.
- Мониторинг в Altinity Operator — **[Kubernetes](./clickhouse-kubernetes.md#мониторинг-и-диагностика)**.
- SLO и метрики производительности — **[Производительность](./clickhouse-performance.md#ключевые-метрики-sre)**.
- Квоты и пользователи — **[Безопасность](./clickhouse-security.md)**.

### Ресурсы

- [Документация: system tables](https://clickhouse.com/docs/ru/operations/system-tables)
- [Документация: Prometheus](https://clickhouse.com/docs/ru/operations/monitoring/prometheus)
- [Документация: query_log](https://clickhouse.com/docs/ru/operations/system-tables/query_log)
