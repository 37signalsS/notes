# MariaDB MaxScale: Мониторинг и метрики

**Актуально для:** MaxScale 25.10.x / 26.10.x

## Определения

*   **Telemetry** — встроенный экспорт метрик и логов MaxScale через OpenTelemetry (OTLP). Включается параметром `telemetry=true` в секции `[maxscale]`. Отправка метрик поддерживается начиная с MaxScale 25.10; более старые версии не умеют слать метрики.
*   **OTLP** — OpenTelemetry Protocol; MaxScale push'ит метрики на коллектор (по умолчанию `http://localhost:4318/v1/metrics`).
*   **Query Classifier Cache** — кэш данных классификации запросов. По умолчанию занимает до 15% памяти MaxScale, ограничивается параметром `query_classifier_cache_size`. Метрики кэша: `maxscale.query_cache.*`.
*   **monitor_diagnostics** — диагностические поля монитора (кто Primary, GTID, лаг реплики), доступные через REST API (`GET /v1/monitors/:name`) и `maxctrl show monitors`.
*   **router_diagnostics** — поля статистики роутера (route_master, rw_transactions и т. п.), видимые через `maxctrl show service`.
*   **MaxGUI** — веб-интерфейс управления и мониторинга, живущий на admin-порте REST API (8989).
*   **mema-agent** — агент MariaDB Enterprise Manager; с флагом `--maxscale` собирает метрики MaxScale через REST API и может push'ить их по OTLP.

## Теоретический блок

### Архитектура метрик MaxScale

У MaxScale **нет встроенного Prometheus-эндпоинта**: `/metrics` на admin-порте не предоставляется, и в справочнике ресурсов REST API (текущая версия) Metrics-ресурса нет. Три пути получить метрики:

1.  **OpenTelemetry (рекомендуемый, 25.10+)** — MaxScale push'ит метрики на OTel Collector, который экспортирует их в Prometheus (локальный `prometheus`-экспортёр) или по remote write (`prometheusremotewrite`-экспортёр — для Prometheus, VictoriaMetrics, Mimir).
2.  **REST API (pull-модель)** — JSON-ресурсы `/v1/servers`, `/v1/services`, `/v1/monitors`; скрейпинг своим скриптом или сторонним экспортёром (например, community-проект `maxctrl_exporter`).
3.  **MariaDB Enterprise Manager** — агент `mema-agent` с флагом `--maxscale` (требует MaxScale 25.10+).

### Канонические метрики (OpenTelemetry)

Метрики различаются между линиями 25.10 и 26.10 — для каждой метрики указана версия добавления. Имена приведены в формате OTLP (с точками).

**Серверные (per server), MaxScale 25.10:**

| Метрика | Тип | Смысл |
| :--- | :--- | :--- |
| `maxscale.server.operations` | Gauge | Число активных операций |
| `maxscale.server.connections` | Gauge | Открытые соединения |
| `maxscale.server.response_dur` | Histogram | Время ответа (секунды) — основа для SLO по латентности |
| `maxscale.server.read_packets` | Gauge (running total) | Прочитанные (маршрутизированные) запросы |
| `maxscale.server.write_packets` | Gauge (running total) | Записи |
| `maxscale.server.status` | Gauge | Статус: `0`=Read, `1`=Write, `2`=Up, `3`=Down |

**Серверные (per server), добавлены в MaxScale 26.10:**

| Метрика | Тип | Смысл |
| :--- | :--- | :--- |
| `maxscale.server.errors` | Gauge (running total) | Ответы с ошибками |
| `maxscale.server.transactions` | Gauge (running total) | Завершённые транзакции |
| `maxscale.server.pool_size` | Gauge | Размер пула соединений |
| `maxscale.server.pool_found` | Gauge (running total) | Попадания в пул |
| `maxscale.server.pool_empty` | Gauge (running total) | Промахи пула (пул пуст) |
| `maxscale.server.replication_lag` | Gauge | Лаг репликации (секунды) |
| `maxscale.server.transaction_lag` | Gauge | На сколько транзакций сервер отстал |

**Сервисные (per service) — все добавлены в MaxScale 26.10:**

`maxscale.service.operations`, `.connections`, `.read_packets`, `.write_packets`, `.errors`, `.transactions` (смысл аналогичен серверным).

**Кэш классификатора запросов, MaxScale 25.10:**

| Метрика | Тип | Смысл |
| :--- | :--- | :--- |
| `maxscale.query_cache.size` | Gauge | Размер кэша классификатора (байты) |
| `maxscale.query_cache.hits` | Gauge (running total) | Попадания |
| `maxscale.query_cache.misses` | Gauge (running total) | Промахи |

**Метрики по SQL, MaxScale 26.10:**

*   `maxscale.query.latency` (Gauge) — латентность по канонической форме запроса, разбивка по перцентилям p50/p75/p95/p99. У каждой точки два атрибута: `percentile` (`p50`, `p75`, `p95` или `p99`) и `sql` (каноническая форма запроса). Экспортируются только самые частые запросы — до `telemetry_sql_count` (default 50); фильтры `telemetry_sql_match` / `telemetry_sql_exclude`. Атрибут `sql` делает метрику высококардинальной — ограничивайте `telemetry_sql_count`.

**Общие, MaxScale 25.10:** `maxscale.qps` (запросов/сек), `maxscale.uptime` (аптайм в секундах), `maxscale.version` (версия), `maxscale.process.time` (использование CPU).

**Примечание по именам в Prometheus:** OTel Collector при экспорте в Prometheus заменяет точки на подчёркивания (`maxscale.server.status` → `maxscale_server_status`). Gauge-метрики не получают суффикса `_total`. Проверяйте фактические имена через `curl http://otel-collector:9090/metrics`.

### Что мониторить (SRE-набор)

*   **Доступность:** `maxscale.server.status` (Down = 3), `maxscale.uptime`, состояние listener'ов.
*   **Failover:** события смены Primary (`maxctrl show monitors` → поле `primary`), `maxscale.server.status` 1→2/3.
*   **Нагрузка:** `maxscale.qps`, `maxscale.server.operations`, `maxscale.process.time`.
*   **Качество маршрутизации:** соотношение `read_packets`/`write_packets` per server (проверка RW-split), `maxscale.server.errors` (26.10).
*   **Репликация:** `maxscale.server.replication_lag` (26.10) против `max_replication_lag`; `transaction_lag` — отставание в транзакциях (точнее секунд при неравномерной нагрузке). В pull-модели — `seconds_behind_master` в `monitor_diagnostics`.
*   **Латентность:** `maxscale.server.response_dur` (Histogram) для SLO; `maxscale.query.latency` (26.10) для поиска тяжёлых запросов.
*   **Пул:** рост `pool_empty` (26.10) — пул мал.
*   **Кэш классификатора:** `query_cache.size` против лимита памяти (`query_classifier_cache_size`).

## Практические сценарии

### Prerequisites

*   OTel Collector с OTLP-приёмником (порт 4318) — для push-модели.
*   Или доступ к REST API — для pull-модели.
*   Для MaxGUI и REST API — пользователь с правами (см. [Безопасность](./maxscale_security.md)).

### Шаг 1: Включение telemetry

```ini
# /etc/maxscale.cnf

[maxscale]
telemetry=true

# Куда push'ить (default: http://localhost:4318/v1/metrics)
# ВНИМАНИЕ: параметр НЕ dynamic — меняется только с перезапуском MaxScale
telemetry_url=http://otel-collector:4318/v1/metrics

# Минимальный интервал отправки (default 60s), dynamic
telemetry_update_interval=60s

# Атрибуты ко всем метрикам, dynamic
telemetry_attributes=project=default-project,cluster=mariadb1,instance=maxscale1

# TLS к коллектору (все три параметра НЕ dynamic — нужен перезапуск).
# Когда заданы telemetry_ssl_ca и telemetry_ssl_cert, отправка идёт по HTTPS —
# переведите telemetry_url на https://...
# telemetry_ssl_key=/certs/client-key.pem
# telemetry_ssl_cert=/certs/client-cert.pem
# telemetry_ssl_ca=/certs/ca.pem
# Не валидировать сертификаты коллектора (self-signed), dynamic
# telemetry_ssl_insecure=true

# Лимит и фильтры для метрик латентности по SQL (dynamic).
# telemetry_sql_count=0 отключает maxscale.query.latency
telemetry_sql_count=50
# telemetry_sql_match=^SELECT
# telemetry_sql_exclude=^SHOW
```

Проверка: `maxctrl show maxscale` — параметры telemetry видны в выводе; ошибки экспорта логируются на уровне info (включается `maxctrl alter maxscale log_info=true`, отключать после отладки — лог объёмный).

### Шаг 2: OTel Collector → Prometheus

```yaml
# otel-collector-config.yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  prometheus:
    endpoint: "0.0.0.0:9090"
    # namespace НЕ нужен: метрики MaxScale и так начинаются с "maxscale."
    # (с namespace: maxscale имена удвоятся: maxscale_maxscale_server_status)

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
```

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'maxscale-otel'
    static_configs:
      - targets: ['otel-collector:9090']
```

Для long-term storage вместо локального экспортёра используйте `prometheusremotewrite`-экспортёр (remote write в Prometheus, VictoriaMetrics, Mimir).

### Шаг 3: Pull-модель через REST API

Метрики и диагностику можно читать напрямую (базовая аутентификация или JWT — см. [REST API](./maxscale_rest_api.md)):

```bash
# Кластерное здоровье: кто Primary, GTID, лаг реплики, lock_held
curl -s -u admin:mariadb http://localhost:8989/v1/monitors/MariaDB-Monitor | jq '.data.attributes.monitor_diagnostics'
```

Полезные поля `monitor_diagnostics` (пример для mariadbmon):

| Поле | Смысл |
| :--- | :--- |
| `master` / `primary` | Текущий Primary |
| `state` | Состояние монитора (`Idle`, `Running`) |
| `server_info[].gtid_binlog_pos` / `gtid_current_pos` | GTID-позиции серверов |
| `server_info[].read_only` / `server_id` | Режим и идентификатор сервера |
| `server_info[].lock_held` | Cooperative-monitoring lock (при `cooperative_monitoring_locks`) |
| `server_info[].slave_connections[].seconds_behind_master` | Лаг реплики (секунды) |
| `server_info[].slave_connections[].slave_io_running` / `slave_sql_running` | Работают ли IO/SQL потоки |
| `server_info[].slave_connections[].last_io_error` / `last_sql_error` | Последние ошибки репликации |

```bash
# Лаг реплики по всем репликам монитора
curl -s -u admin:mariadb http://localhost:8989/v1/monitors/MariaDB-Monitor \
  | jq '.data.attributes.monitor_diagnostics.server_info[].slave_connections[]
        | {replica: .master_server_name, lag: .seconds_behind_master, io: .slave_io_running}'

# Серверы и сервисы
curl -s -u admin:mariadb http://localhost:8989/v1/servers | jq '.data[].id'
curl -s -u admin:mariadb http://localhost:8989/v1/services | jq '.data[].id'
```

Сторонний community-экспортёр **maxctrl_exporter** ([GitHub](https://github.com/vbezgachev/maxctrl_exporter), образ в Docker Hub) экспортирует метрики REST API в формате Prometheus (соединения, сессии сервисов, статус инстанса; эндпоинт по умолчанию `:8093/metrics`, настройка через переменные `MAXSCALE_URL`, `MAXSCALE_USERNAME`, `MAXSCALE_PASSWORD`). Проект не официальный и давно не обновлялся — он не знает метрики OTel 25.10+/26.10; для новых метрик используйте telemetry.

### Шаг 4: Диагностика через maxctrl

```bash
# Состояние серверов: Server, Address, Port, Connections, State,
# GTID (текущее @@gtid_current_pos), Monitor
maxctrl list servers

# Детально по серверу: connections, operations, router diagnostics
maxctrl show server db-node-1

# Статистика сервиса (router_diagnostics readwritesplit):
# route_master, route_slave, rw_transactions, ro_transactions,
# trx_max_size_exceeded, queries
maxctrl show service RW-Split-Service

# Мониторы: кто Primary (поле primary), lock_held при cooperative monitoring
maxctrl show monitors

# Активные сессии
maxctrl list sessions

# Состояние самого MaxScale: версия, uptime, параметры (в т.ч. telemetry)
maxctrl show maxscale

# Последние запросы сессий — требует retain_last_statements=1 в maxscale.cnf
maxctrl list queries

# Дамп состояния всех объектов в JSON (для отладки и баг-репортов).
# Без имени файла вывод идёт на stdout (удобно в Docker)
maxctrl create report maxctrl-report.json
```

Анализ отчёта через `jq`:

```bash
jq '.servers.data[].id'    maxctrl-report.json   # список серверов
jq '.services.data[].id'   maxctrl-report.json   # список сервисов
jq '.monitors.data[].id'   maxctrl-report.json   # список мониторов
jq '.listeners.data[].id'  maxctrl-report.json   # список listener'ов
jq '.filters.data[].id'    maxctrl-report.json   # список фильтров

# Конкретный объект
jq '.services.data|map(select(.id == "RW-Split-Service"))' maxctrl-report.json

# Какой монитор следит за сервером
jq '.servers.data|map(select(.id == "db-node-1"))|.[].relationships.monitors.data' maxctrl-report.json

# Память, занятая кэшем классификатора (всех потоков)
jq '[.threads.data[].attributes.stats.query_classifier_cache.size]|add' maxctrl-report.json
```

### Шаг 5: MaxGUI

```ini
# /etc/maxscale.cnf
[maxscale]
# Веб-интерфейс на admin-порте (default: true)
admin_gui=true
# Безопасный режим: GUI и /auth доступны только по TLS (default: true)
admin_secure_gui=true
```

Открывается на `https://<maxscale-host>:8989/`. Настройка TLS-ключа/сертификата (`admin_ssl_key`, `admin_ssl_cert`) — в [Безопасности](./maxscale_security.md). Полезный побочный эффект: при `admin_gui=false` корневой URL admin-порта отдаёт `200 OK` — годится как health check. Для тестового стенда: `admin_host=0.0.0.0` + `admin_secure_gui=false`.

### Шаг 6: MariaDB Enterprise Manager (MEMA)

Агент `mema-agent` собирает метрики MaxScale через REST API и отправляет их в Enterprise Manager (или напрямую по OTLP):

```bash
# На хосте MaxScale (пакет mema-agent из MariaDB Enterprise Tools)
sudo mema-agent setup --cluster-name=MyCluster \
  --endpoint=https://<em-host> --otlp-port=<port> \
  --maxscale --host-name=<hostname> \
  --maxscale-user=admin --maxscale-password=<password> \
  --otlp-insecure --otlp-interval=60s
```

*   Требует MaxScale **25.10+** — старые версии не умеют отправлять метрики.
*   Если REST API MaxScale на HTTPS: `--maxscale-host=https://127.0.0.1:8989`; для self-signed сертификатов добавьте `--maxscale-insecure`.
*   Регистрация топологии в UI: Add Database → «Database with MaxScale» — Enterprise Manager подключается к MaxScale и автоматически обнаруживает все backend-серверы.
*   Диагностика ошибок экспорта: `maxctrl alter maxscale log_info=true` (ошибки экспорта логируются на info-уровне; лог объёмный — отключайте после отладки).

### Шаг 7: Алерты (примеры для Prometheus/Alertmanager)

```yaml
groups:
  - name: maxscale
    rules:
      - alert: MaxScaleServerDown
        expr: maxscale_server_status == 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "MaxScale: сервер {{ $labels.server }} Down"

      - alert: MaxScaleReplicationLag   # метрика 26.10+
        expr: maxscale_server_replication_lag > 30
        for: 5m
        labels:
          severity: warning

      - alert: MaxScaleTransactionLag   # метрика 26.10+
        expr: maxscale_server_transaction_lag > 100
        for: 5m
        labels:
          severity: warning

      - alert: MaxScaleHighErrors       # метрика 26.10+
        expr: rate(maxscale_server_errors[5m]) > 0.1
        for: 5m
        labels:
          severity: warning

      - alert: MaxScalePoolExhaustion   # метрика 26.10+
        expr: increase(maxscale_server_pool_empty[5m]) > 0
        for: 5m
        labels:
          severity: warning

      - alert: MaxScaleQueryLatency     # метрика 26.10+
        expr: maxscale_query_latency{percentile="p95"} > 1
        for: 5m
        labels:
          severity: warning

      - alert: MaxScaleRestarted
        expr: maxscale_uptime < 300
        labels:
          severity: info
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Метрики не приходят в коллектор | `telemetry=false`, недоступен `telemetry_url`, или `telemetry_url` меняли без перезапуска (параметр не dynamic) | Проверьте `maxctrl show maxscale`, доступность коллектора, перезапустите MaxScale; включите `maxctrl alter maxscale log_info=true` для логов экспорта |
| Метрики без атрибутов (project, cluster) | Не задан `telemetry_attributes` | Добавьте атрибуты |
| Нет метрик латентности по SQL | Версия < 26.10, `telemetry_sql_count=0`, или сработали `telemetry_sql_match`/`telemetry_sql_exclude` | Обновитесь или проверьте лимит и фильтры |
| Нет метрик `maxscale.service.*`, `pool_*`, `replication_lag` | Версия < 26.10 — эти метрики добавлены в 26.10 | Обновитесь или используйте `maxscale.server.*` и `seconds_behind_master` из REST API |
| GUI недоступен | `admin_gui=false` или `admin_secure_gui=true` без сертификатов | Настройте GUI и TLS (см. [Безопасность](./maxscale_security.md)) |
| MaxScale убив systemd watchdog | Долгий reverse-DNS lookup IP клиентов | `skip_name_resolve=true` в `[maxscale]` |
| Высокое потребление памяти | Кэш классификатора (до 15% памяти по умолчанию), буферизация writeq, отладочные параметры | Понизьте `query_classifier_cache_size`; `writeq_high_water`/`writeq_low_water` (например, 512/128); отключите `retain_last_statements` и `session_trace` при интенсивной нагрузке (но `maxctrl list queries` требует `retain_last_statements=1`) |
| `ERROR 1045 (28000): Access denied` | Пользователь создан только для хоста клиента, но не для хоста MaxScale | Создайте пользователей и `'bob'@'office'`, и `'bob'@'maxscale'`; альтернатива — `proxy_protocol` + `proxy_protocol_networks` на сервере |
| Ошибки аутентификации/прав в целом | Не видно, какие запросы отклоняются | `debug=enable-statement-logging` в `[maxscale]` — все SQL на уровне notice |
| `Error 23: Too many open files` | Низкий лимит открытых файлов | `LimitNOFILE=<число>` в `[Service]` файла maxscale.service |
| `maxctrl` падает с `ENOENT: no such file or directory, uv_cwd` | Удалена текущая рабочая директория | Перейти в существующую директорию |
| `maxctrl`: `Pkg: Error reading from file.` | Исполняемый файл stripped (потеряны символы) | Переустановить пакет MaxScale |

## Best Practices

1.  **Telemetry + OTel Collector** — канонический путь для Prometheus в 25.10+; не ищите `/metrics` на MaxScale — его нет.
2.  **Учитывайте линию версий при алертинге**: `maxscale.service.*`, `pool_*`, `replication_lag`, `transaction_lag`, `query.latency` доступны только в 26.10+. На 25.10 алертите по `server.*`, `query_cache.*` и `maxscale.qps`.
3.  **Алерты на `maxscale.server.status == 3`** (Down) и на смену `primary` — базовый набор.
4.  **`telemetry_url` и `telemetry_ssl_*` не dynamic** — меняйте их в плановом окне обслуживания (нужен перезапуск); `telemetry`, `telemetry_update_interval`, `telemetry_attributes`, `telemetry_sql_*` — dynamic, применяются через `maxctrl alter maxscale`.
5.  **`telemetry_sql_count` ограничивайте** — атрибут `sql` делает метрики латентности высококардинальными.
6.  **Сравнивайте `read_packets` per server** — быстро видит неравномерный RW-split.
7.  **`maxctrl create report`** перед эскалацией в баг — дамп состояния всех объектов (логируйте в [Jira MaxScale](https://jira.mariadb.org/browse/MXS) вместе с версией и конфигом без паролей).
8.  **Следите за памятью кэша классификатора**: `jq '[.threads.data[].attributes.stats.query_classifier_cache.size]|add'` или метрика `maxscale.query_cache.size`.
9.  **`admin_audit` обязателен при expos'е REST API в сеть** — настройка в [Безопасности](./maxscale_security.md).

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — логирование и logrotate.
*   **[Безопасность](./maxscale_security.md)** — `admin_audit`, TLS admin-порта, пользователи REST API.
*   **[REST API и maxctrl](./maxscale_rest_api.md)** — pull-модель через API, команды maxctrl.
*   **[Failover и Switchover](./maxscale_failover.md)** — мониторинг failover-событий.
*   **[Connection Pooling](./maxscale_connection_pooling.md)** — метрики пула.
*   **[Мониторинг MariaDB](../monitoring.md)** — метрики сервера БД.
*   [MaxScale Telemetry](https://mariadb.com/docs/maxscale/reference/maxscale-telemetry.md) — эталонный список экспортируемых метрик.
*   [MaxScale Troubleshooting](https://mariadb.com/docs/maxscale/maxscale-management/maxscale-troubleshooting.md) — официальная страница устранения неполадок.
