# Prometheus Remote Read/Write

> **Remote Read/Write (PRW)** — это стандартный механизм Prometheus, позволяющий отправлять (push) и запрашивать (pull) метрики из внешних систем длительного хранения (LTS). Этот протокол решает фундаментальные проблемы локальной базы данных TSDB: ограничение дискового пространства, отсутствие горизонтального масштабирования и отсутствие встроенной высокой доступности.
>
> **Надёжность:** 10 (SSoT + Web Verification 2025)
>
> **См. также:** [Масштабирование (обзор)](./overview.md), [Thanos](./thanos_overview.md), [Внутреннее устройство TSDB](../concepts/tsdb.md).

## Определения

| Механизм | Описание |
|---|---|
| **`remote_write`** | Prometheus (или агент сбора) в реальном времени отправляет собранные метрики во внешнее хранилище. |
| **`remote_read`** | Prometheus запрашивает исторические данные из внешнего хранилища при выполнении PromQL-запросов, если этих данных нет в локальной TSDB. Используется редко, обычно Grafana подключается напрямую к LTS. |
| **WAL (Write-Ahead Log)** | Журнал предзаписи. Надежный буфер на диске, который `remote_write` использует для хранения данных перед отправкой по сети, гарантируя защиту от потерь при разрывах связи. |

---

## Основные концепции

### Архитектура и защита данных (WAL)

Механизм `remote_write` спроектирован так, чтобы гарантировать доставку данных (at-least-once delivery) даже в нестабильных сетях.

1.  **Чтение с диска, а не из памяти:** Компонент `remote_write` не берет данные напрямую из оперативной памяти (Head Block). Он читает их из локального файла **[WAL](../../Databases/Concepts/write_ahead_log.md)**.
2.  **Буферизация (Backfill):** Если внешнее хранилище недоступно, Prometheus просто перестает продвигать указатель чтения WAL. Метрики продолжают копиться на локальном диске (в рамках настроенного времени `retention`).
3.  **Восстановление:** При восстановлении связи `remote_write` начинает агрессивно отправлять накопленные данные (backfilling), чтобы догнать текущее время.

### Эволюция протокола: Remote Write 2.0 (Стандарт 2024–2025)

Начиная с версии Prometheus 3.0, внедряется спецификация **PRW 2.0**, которая радикально снижает потребление ресурсов:

*   **String Interning (Таблица символов):** В PRW 1.0 (Protobuf) каждое имя метрики и лейбла передавалось текстом в каждом пакете. В PRW 2.0 используется словарь (symbol table). Строка отправляется один раз, а далее передается только ее числовой ID. Это **снижает объем исходящего Egress-трафика на 50–60%** и радикально уменьшает нагрузку на CPU хранилища (Mimir/VictoriaMetrics).
*   **Сжатие данных (Compression):** Исторически использовался алгоритм `snappy`. В современных версиях добавлена поддержка `zstd`, который обеспечивает лучший коэффициент сжатия при сопоставимой нагрузке на процессор.
*   **Метаданные и OTLP:** PRW 2.0 нативно передает типы метрик (Counter, Gauge) и единицы измерения, что делает его совместимым с форматом OpenTelemetry (OTLP).

---

## Практические сценарии и параметры конфигурации

### Базовые параметры `remote_write`

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого хранилища. |
| `remote_timeout` | `30s` | Таймаут одного HTTP-запроса записи. При медленной сети стоит увеличить. |
| `send_exemplars` | `false` | Включает отправку Exemplars (ссылки на трейсы) вместе с метриками. |
| `send_native_histograms` | `false` | Отправка высокоточных Native Histograms (экспериментально). |
| `write_relabel_configs` | — | Мощный инструмент фильтрации и модификации меток **до** их отправки в сеть. |
| `name` | (хэш) | Уникальное имя очереди в метриках (полезно при наличии нескольких `remote_write`). |

### Фильтрация мусора (Relabeling)

Обязательная практика для снижения затрат на хранилище: не отправляйте в LTS высокочастотные или отладочные метрики.

```yaml
remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    write_relabel_configs:
      # Отбросить все метрики сборщика мусора Go
      - source_labels: [__name__]
        regex: '^go_gc_.*'
        action: drop
      # Добавить статичный лейбл (хотя лучше использовать global.external_labels)
      - target_label: env
        replacement: production
```

### Безопасность: Auth, TLS и OIDC

Современные системы хранения (особенно в облаке) требуют строгой аутентификации.

**Пример 1: Basic Auth и TLS**
```yaml
remote_write:
  - url: 'https://mimir.example.com/api/v1/push'
    tls_config:
      ca_file: '/etc/prometheus/certs/ca.crt'
      cert_file: '/etc/prometheus/certs/client.crt'
      key_file: '/etc/prometheus/certs/client.key'
      insecure_skip_verify: false
    basic_auth:
      username: 'prom-writer'
      password_file: '/etc/prometheus/secrets/mimir-pass'
```

**Пример 2: Bearer Token (Kubernetes Service Account)**
```yaml
remote_write:
  - url: 'https://thanos-receive.monitoring.svc:19291/api/v1/receive'
    bearer_token_file: '/var/run/secrets/kubernetes.io/serviceaccount/token'
```

**Пример 3: Настройка OAuth2 / OIDC (Современный подход)**
Используется для интеграции с Keycloak, Google Cloud IAM или Azure AD без статических паролей.
```yaml
remote_write:
  - url: 'https://managed-prometheus.googleapis.com/v1/projects/my-project/locations/global/workspaces/my-workspace/api/v1/write'
    oauth2:
      client_id: 'my-client-id'
      client_secret_file: '/etc/prometheus/secrets/oauth2-secret'
      token_url: 'https://oauth2.googleapis.com/token'
      scopes:
        - 'https://www.googleapis.com/auth/monitoring.write'
```

### Настройка в Prometheus Operator (CRD)

В Kubernetes настройка `remote_write` производится через секцию `spec.remoteWrite` ресурса `Prometheus`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  remoteWrite:
    - url: "http://victoria-metrics.monitoring.svc:8428/api/v1/write"
      sendExemplars: true
      queueConfig:
        maxShards: 100
      writeRelabelConfigs:
        - action: drop
          regex: "container_network_.*"
          sourceLabels: [__name__]
```

## Дополнительная информация

### Тюнинг очереди отправки (`queue_config`)

Настройка очереди критически важна для высоконагруженных систем (>100k samples/s). Если очередь не справляется, Prometheus начнет потреблять слишком много оперативной памяти (OOMKill) или дропать сэмплы.

| Параметр | Default | SRE Тюнинг / Описание |
|---|---|---|
| `capacity` | `10000` | Размер буфера в сэмплах (на каждый шард). Если сеть часто "мигает", можно увеличить до `50000`, но это увеличит потребление RAM. |
| `max_shards` | `200` | **Главный рычаг масштабирования.** Максимальное число параллельных HTTP(TCP)-соединений. При задержках или большом потоке увеличивайте до `1000+`. |
| `min_shards` | `1` | Минимальное число потоков. Для стабильной нагрузки можно зафиксировать равным `max_shards`, чтобы избежать задержек на масштабирование очереди. |
| `max_samples_per_send`| `500` | Максимум сэмплов в одном батче. Увеличение до `2000-5000` снижает накладные расходы на HTTP/Headers, но хранилище (LTS) должно поддерживать прием больших батчей. |
| `batch_send_deadline` | `5s` | Максимальное время ожидания перед отправкой батча, даже если он не заполнен до `max_samples_per_send`. |
| `min_backoff` / `max_backoff` | `30ms` / `5s`| Управление ретраями при ошибках 5xx. При нестабильном приемнике (Thanos Receive) `max_backoff` стоит увеличить до `10-15s`. |

**Как понять, что нужен тюнинг?**
Проверяйте метрику `prometheus_remote_storage_highest_timestamp_in_seconds` и `prometheus_remote_storage_queue_highest_sent_timestamp_seconds`. Если разница между ними (лаг) постоянно растет, вам нужно увеличивать `max_shards` или `max_samples_per_send`. Ошибки сброса: `prometheus_remote_storage_dropped_samples_total`.

### Параметры `remote_read`

Использование `remote_read` считается антипаттерном в современных системах, так как Grafana должна напрямую обращаться в Thanos/Mimir. Используйте только если вам критически важна оценка Recording Rules локальным сервером поверх старых данных.

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого чтения. |
| `remote_timeout` | `1m` | Запросы на чтение могут занимать много времени, стоит увеличить до `2m-5m`. |
| `read_recent` | `false` | По умолчанию Prometheus не запрашивает из сети данные за последние 2-6 часов (считая, что они есть в локальном Head Block). Если `true`, будет читать из сети всё. |
| `required_matchers` | — | Отправлять запрос во внешнюю БД **только** если в PromQL есть определенные метки (например, `cluster: prod`). Защищает от "глупых" запросов. |

### Поддерживаемые хранилища (Обновлено 2025)

| Хранилище | Архитектура | Примечание |
|---|---|---|
| **Grafana Mimir** | Microservices | 100% совместимость. Основной потребитель новшеств PRW 2.0 (String Interning). |
| **VictoriaMetrics** | Monolith/Cluster | Максимально эффективный приемник, часто переваривает миллионы сэмплов даже с настройками `queue_config` по умолчанию. |
| **Thanos Receive** | Sidecar/Push | Поддерживает маршрутизацию (Routing) на основе лейблов (Tenant ID) для мульти-тенантности. |
| **ClickHouse** | Columnar DB | Требуется адаптер (prom2click или ClickHouse Keeper). Отличный выбор для терабайтных логов метрик. |
| **TimescaleDB** | PostgreSQL ext. | Интеграция через Promscale (устаревает, вектор на прямую интеграцию). |
| **OpenTelemetry (OTLP)** | Collector | OTel Collector (с версии 0.141+) может принимать PRW и конвертировать его в OTLP для отправки в любые системы. |
