# Удаленное чтение и запись в Prometheus (Remote Read/Write)

Удаленное чтение и запись (Remote Read/Write, PRW) — это стандартный механизм Prometheus, позволяющий отправлять (push) и запрашивать (pull) метрики из внешних систем длительного хранения (LTS). Этот протокол решает фундаментальные проблемы локальной базы данных TSDB: ограничение дискового пространства, отсутствие горизонтального масштабирования и отсутствие встроенной высокой доступности.

## Определения

| Механизм | Описание |
|---|---|
| **`remote_write`** | Процесс, при котором Prometheus (или агент сбора) в реальном времени отправляет собранные метрики во внешнее хранилище. |
| **`remote_read`** | Метод запроса исторических данных из внешнего хранилища при выполнении PromQL-запросов, если этих данных нет в локальной TSDB. Используется редко, обычно Grafana подключается напрямую к LTS. |
| **WAL (Write-Ahead Log)** | Журнал предзаписи. Надежный буфер на диске, который `remote_write` использует для хранения данных перед отправкой по сети, гарантируя защиту от потерь при разрывах связи. |

## Базовые концепции

### Архитектура и защита данных (WAL)

Механизм `remote_write` спроектирован так, чтобы гарантировать доставку данных (at-least-once delivery) даже в нестабильных сетях.

1.  **Чтение с диска, а не из памяти:** Компонент `remote_write` не берет данные напрямую из оперативной памяти (Head Block). Он читает их из локального файла **[WAL](../../Databases/Concepts/write_ahead_log.md)**. Это гарантирует сохранность данных при перезагрузке сервера.
2.  **Буферизация (Backfill):** Если внешнее хранилище недоступно, Prometheus просто перестает продвигать указатель чтения WAL. Метрики продолжают копиться на локальном диске в рамках настроенного времени `retention`.
3.  **Восстановление:** При восстановлении связи `remote_write` начинает агрессивную отправку накопленных данных (backfilling), используя параллельные потоки (shards), чтобы догнать текущее время.

### Эволюция протокола: Remote Write 2.0 (Стандарт 2025–2026)

Начиная с версии Prometheus 3.0, спецификация **PRW 2.0** стала основным стандартом, радикально снижающим потребление ресурсов:

*   **Интернирование строк (String Interning):** В PRW 1.0 каждое имя метрики и лейбла передавалось текстом в каждом пакете. В PRW 2.0 используется словарь (symbol table). Строка отправляется один раз, а далее передается только ее числовой ID. Это **снижает объем исходящего Egress-трафика на 50–60%** и нагрузку на CPU хранилища (Mimir/VictoriaMetrics).
*   **Сжатие данных (Compression):** В дополнение к алгоритму `snappy` добавлена поддержка `zstd`, который обеспечивает лучший коэффициент сжатия при сопоставимой нагрузке на процессор.
*   **Метаданные и OTLP:** PRW 2.0 нативно передает типы метрик (Counter, Gauge, Histogram) и единицы измерения, что делает его полностью совместимым с форматом OpenTelemetry (OTLP) и поддержкой UTF-8.
*   **Created Timestamps:** Передача временных меток создания серии позволяет корректно обрабатывать сбросы счетчиков (counter resets) на стороне LTS, повышая точность функций `rate()` и `increase()`.

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

Обязательная практика для снижения затрат на хранилище: не отправляйте в LTS мусорные или отладочные метрики.

```yaml
remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    write_relabel_configs:
      # Отбросить все метрики сборщика мусора Go
      - source_labels: [__name__]
        regex: '^go_gc_.*'
        action: drop
      # Удалить высококардинальные лейблы (эфемерные порты)
      - source_labels: [instance]
        regex: '(.*):[0-9]+'
        target_label: instance
        replacement: '$1'
```

### Безопасность: Auth, TLS и OIDC

**Пример 1: Basic Auth и TLS**
```yaml
remote_write:
  - url: 'https://mimir.example.com/api/v1/push'
    tls_config:
      ca_file: '/etc/prometheus/certs/ca.crt'
      cert_file: '/etc/prometheus/certs/client.crt'
      key_file: '/etc/prometheus/certs/client.key'
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

**Пример 3: Настройка OAuth2 / OIDC (Рекомендуется для облаков)**
Интеграция с Keycloak, AWS IAM, Google Cloud Auth без статических паролей.
```yaml
remote_write:
  - url: 'https://managed-monitoring.cloud/api/v1/write'
    oauth2:
      client_id: 'monitoring-sa'
      client_secret_file: '/etc/prometheus/secrets/oauth2-secret'
      token_url: 'https://oauth2.googleapis.com/token'
      scopes:
        - 'https://www.googleapis.com/auth/monitoring.write'
```

### Настройка в Prometheus Operator (CRD)

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

## Тюнинг и эксплуатация

### Настройка очереди отправки (`queue_config`)

Тюнинг очереди критически важен для высоконагруженных систем (>100k samples/s).

| Параметр | Default | SRE Тюнинг / Описание |
|---|---|---|
| `capacity` | `10000` | Размер буфера в сэмплах на каждый шард. Увеличьте при нестабильной сети. |
| `max_shards` | `200` | Максимальное число параллельных потоков. Для больших потоков: `1000–2000`. |
| `min_shards` | `1` | Минимальное число потоков. Для стабильной нагрузки: `min_shards == max_shards`. |
| `max_samples_per_send`| `500` | Максимум сэмплов в батче. Увеличение до `5000` снижает накладные расходы на HTTP. |
| `batch_send_deadline` | `5s` | Максимальное время ожидания перед отправкой неполного батча. |
| `min_backoff` | `30ms` | Начальная пауза при ретраях (ошибки 5xx). |
| `max_backoff` | `5s` | Максимальная пауза при ретраях. При лагах LTS увеличьте до `15s`. |

**Мониторинг лага:**
- `prometheus_remote_storage_highest_timestamp_in_seconds`: время последнего скрейпа.
- `prometheus_remote_storage_queue_highest_sent_timestamp_seconds`: время последнего отправленного сэмпла.
- **Лаг** = разница между ними. Если растет — увеличивайте `max_shards`.
- `prometheus_remote_storage_dropped_samples_total`: критическая метрика потери данных.

### Параметры `remote_read`

Использование `remote_read` считается антипаттерном. Grafana должна обращаться в LTS напрямую.

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого чтения. |
| `remote_timeout` | `1m` | Таймаут запроса. Может требовать увеличения до `2m-5m`. |
| `read_recent` | `false` | Если `true`, Prometheus запрашивает из сети даже свежие данные (игнорируя Head Block). |
| `required_matchers` | — | Фильтр для отправки запроса в сеть только при наличии определенных меток. |

## Дополнительная информация

### Поддерживаемые хранилища (2025–2026)

| Хранилище | Архитектура | Примечание |
|---|---|---|
| **Grafana Mimir** | Microservices | 100% совместимость, мульти-тенантность, PRW 2.0. |
| **VictoriaMetrics** | Cluster/Single | Экстремальная производительность, нативное сжатие. |
| **Thanos Receive** | Gateway | Шлюз для выгрузки блоков в S3/GCS. |
| **ClickHouse** | Columnar DB | Через адаптер. Идеально для петабайтных логов метрик. |
| **TimescaleDB** | PostgreSQL | SQL-интерфейс поверх временных рядов (через адаптер). |
| **OpenTelemetry** | Collector | Прием PRW и конвертация в OTLP для любых систем. |

### См. также
*   [Масштабирование: обзор](./overview.md)
*   [Внутреннее устройство TSDB](../concepts/tsdb.md)
*   [Thanos: архитектура](./thanos_overview.md)
