# Prometheus Remote Read/Write

> Remote Read/Write — современный подход к **[масштабированию Prometheus](./overview.md)**, делегирующий хранение метрик внешним системам.
>
> **См. также:** [TSDB](../concepts/tsdb.md), [Federation](./federation.md), [Thanos](./thanos_overview.md).

## Определения

**Remote Read/Write** — механизм Prometheus, позволяющий отправлять (`remote_write`) и запрашивать (`remote_read`) метрики из внешних систем хранения. Решает ограничения локальной TSDB: объём, retention, горизонтальное масштабирование.

| Механизм | Описание |
|---|---|
| **`remote_write`** | Prometheus отправляет собранные метрики во внешнее хранилище в реальном времени; локальный инстанс работает как агент сбора |
| **`remote_read`** | Prometheus запрашивает исторические данные из внешнего хранилища при выполнении PromQL-запросов, выходящих за рамки локальной TSDB |

## Основные концепции

### Принцип работы

Prometheus делегирует хранение внешним системам, продолжая выполнять сбор метрик и обработку PromQL-запросов локально.

| Аспект | Описание |
|---|---|
| **Локальная обработка** | Агрегация и вычисление PromQL выполняются на стороне Prometheus; внешнее хранилище только предоставляет данные |
| **Нагрузка при чтении** | Запросы за длительный период требуют выгрузки большого объёма сырых данных — необходимо планировать ресурсы (CPU, RAM) |
| **Агентный режим** | При использовании `remote_write` локальный Prometheus работает как агент сбора, не храня данные долгосрочно |

### Пример конфигурации

```yaml
# /etc/prometheus/prometheus.yml
global:
  scrape_interval: 15s
  external_labels:
    cluster: 'prod-us'

remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    queue_config:
      max_shards: 500
      capacity: 10000
    write_relabel_configs:
      - source_labels: [__name__]
        regex: 'go_.*'
        action: drop

remote_read:
  - url: 'http://victoriametrics:8428/api/v1/read'
    read_recent: true
    required_matchers:
      cluster: 'prod-us'
```

### Параметры `remote_write`

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого хранилища |
| `remote_timeout` | `30s` | Таймаут одного запроса записи |
| `write_relabel_configs` | — | Фильтрация/модификация меток перед отправкой (синтаксис `relabel_configs`) |
| `basic_auth.username` | — | Имя пользователя (Basic Auth) |
| `basic_auth.password` | — | Пароль (Basic Auth) |
| `bearer_token` | — | Токен Bearer-авторизации |
| `bearer_token_file` | — | Путь к файлу с Bearer-токеном |
| `proxy_url` | — | URL proxy-сервера |
| `tls_config.insecure_skip_verify` | `false` | Пропускать проверку TLS-сертификата |
| `tls_config.ca_file` | — | Путь к CA-сертификату |
| `tls_config.cert_file` | — | Путь к клиентскому сертификату |
| `tls_config.key_file` | — | Путь к клиентскому ключу |
| `tls_config.server_name` | — | Имя сервера для TLS-проверки |

### Параметры `remote_read`

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого чтения |
| `remote_timeout` | `1m` | Максимальное время ожидания ответа |
| `read_recent` | `false` | Запрашивать данные, уже присутствующие в локальной TSDB (полезно для заполнения пробелов) |
| `required_matchers` | — | Метки, обязательные для направления запроса во внешнее хранилище |
| Аутентификация | — | Аналогична `remote_write` (`basic_auth`, `bearer_token`, `tls_config`) |

## Практические сценарии

### Фильтрация метрик через `write_relabel_configs`

Типовой сценарий — исключение высокочастотных или служебных метрик перед отправкой для снижения нагрузки на хранилище:

```yaml
remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    write_relabel_configs:
      # Отбросить метрики go_*
      - source_labels: [__name__]
        regex: 'go_.*'
        action: drop
      # Отбросить метрики с лейблом debug=true
      - source_labels: [debug]
        regex: 'true'
        action: drop
```

## Дополнительная информация

### Управление очередью `remote_write` (`queue_config`)

| Параметр | Default | Описание |
|---|---|---|
| `capacity` | `500` | Количество сэмплов в буфере перед отправкой |
| `max_shards` | `1000` | Максимальное число параллельных потоков записи |
| `min_shards` | `1` | Минимальное число потоков |
| `max_samples_per_send` | `100` | Максимум сэмплов в одном батче |
| `batch_send_deadline` | `5s` | Максимальное время ожидания в буфере |
| `min_backoff` | `30ms` | Начальная задержка перед повторной попыткой |
| `max_backoff` | `100ms` | Максимальная задержка между попытками |

### Поддерживаемые хранилища

| Хранилище | Read | Write | Примечание |
|---|---|---|---|
| **Thanos** | Да | Да | Read через Query-компонент |
| **VictoriaMetrics** | Да | Да | Высокая производительность |
| **Cortex** | Да | Да | Горизонтально масштабируемый |
| **Mimir** | Да | Да | Форк Cortex от Grafana Labs |
| **InfluxDB** | Да | Да | |
| **PostgreSQL/TimescaleDB** | Да | Да | |
| **Splunk** | Да | Да | |
| **TiKV** | Да | Да | |
| **Azure Data Explorer** | Да | Да | |
| **CrateDB** | Да | Да | |
| **IRONdb** | Да | Да | |
| **M3DB** | Да | Да | |
| **Elasticsearch** | — | Да | |
| **Graphite** | — | Да | |
| **Gnocchi** | — | Да | |
| **Kafka** | — | Да | |
| **OpenTSDB** | — | Да | |
| **SignalFx** | — | Да | |
| **AppOptics** | — | Да | |
| **Chronix** | — | Да | |
| **Wavefront** | — | Да | |
