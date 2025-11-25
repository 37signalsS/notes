# Prometheus Remote Read/Write

Prometheus поддерживает интеграцию с внешними системами хранения через `remote_read` и `remote_write` API. Это ключевой механизм для построения масштабируемых и долгосрочных решений для хранения метрик.

Подробнее об архитектурном подходе можно прочитать в [[./overview.md]].

## 1. Настройка Remote Read

Секция `remote_read` в `prometheus.yml` позволяет настроить Prometheus на чтение данных из удаленного хранилища.

### Параметры

-   `url`: URL-адрес, куда будут отправляться запросы для удаленного чтения.
-   `remote_timeout` (default: `1m`): Максимальное время ожидания для операции удаленного чтения.
-   `read_recent` (default: `false`): Определяет, выполнять ли удаленный запрос для временного интервала, который уже имеется в локальном хранилище Prometheus.
-   `required_matchers`: Список меток, для которых будет производиться удаленное чтение. (Не является обязательным).
-   `basic_auth`:
    -   `username`: Имя пользователя для Basic-аутентификации.
    -   `password`: Пароль для Basic-аутентификации.
-   `bearer_token`: Токен для Bearer-авторизации.
-   `bearer_token_file`: Файл, содержащий токен для Bearer-авторизации.
-   `proxy_url`: Адрес proxy-сервера.
-   `tls_config`: Конфигурация TLS для безопасного подключения.
    -   `insecure_skip_verify` (default: `false`): Проверять ли валидность сертификата.
    -   `ca_file`: Путь к файлу с корневыми сертификатами (CA).
    -   `cert_file`: Путь к файлу с клиентским сертификатом.
    -   `key_file`: Путь к файлу с клиентским ключом.
    -   `server_name`: Имя сервера для проверки в сертификате.

## 2. Настройка Remote Write

Секция `remote_write` позволяет настроить отправку метрик из Prometheus в удаленное хранилище.

### Параметры

-   `url`: URL-адрес, куда будут отправляться метрики.
-   `remote_timeout` (default: `30s`): Таймаут для одного запроса на удаленную запись.
-   `write_relabel_configs`: Позволяет модифицировать метки перед отправкой в удаленное хранилище. Синтаксис аналогичен `relabel_configs`.
-   `basic_auth`, `bearer_token`, `bearer_token_file`, `proxy_url`, `tls_config`: Аналогичны параметрам в `remote_read`.

### Настройки очереди (`queue_config`)

Блок `queue_config` управляет очередью и механизмами повторных попыток отправки данных, что критически важно для надежности.

-   `capacity` (default: `500`): Количество сэмплов для буферизации в памяти.
-   `max_shards` (default: `1000`): Максимальное количество "шардов" (параллельных потоков) для отправки данных. Увеличение этого значения может повысить пропускную способность, но также увеличит потребление ресурсов.
-   `min_shards` (default: `1`): Минимальное количество шардов.
-   `max_samples_per_send` (default: `100`): Максимальное количество сэмплов в одном батче (пакете) отправки.
-   `batch_send_deadline` (default: `5s`): Максимальное время, которое сэмпл может провести в буфере, прежде чем батч будет принудительно отправлен.
-   `min_backoff` (default: `30ms`): Начальная задержка перед повторной попыткой отправки после ошибки. Удваивается с каждой неудачной попыткой.
-   `max_backoff` (default: `100ms`): Максимальная задержка между повторными попытками.

## 3. Поддерживаемые удаленные хранилища

Prometheus может интегрироваться с большим количеством систем. Некоторые из них:

-   AppOptics: `write`
-   Azure Data Explorer: `read` and `write`
-   Chronix: `write`
-   Cortex: `read` and `write`
-   CrateDB: `read` and `write`
-   Elasticsearch: `write`
-   Gnocchi: `write`
-   Graphite: `write`
-   InfluxDB: `read` and `write`
-   IRONdb: `read` and `write`
-   Kafka: `write`
-   M3DB: `read` and `write`
-   OpenTSDB: `write`
-   PostgreSQL/TimescaleDB: `read` and `write`
-   SignalFx: `write`
-   Splunk: `read` and `write`
-   TiKV: `read` and `write`
-   **Thanos**: `write` (и `read` через Query-компонент)
-   **VictoriaMetrics**: `write` (и `read`)
-   Wavefront: `write`

---
**Связанные темы:**
- [[./overview.md]]
- [[./thanos_overview.md]]
- [[../../VictoriaMetrics/overview.md]]
