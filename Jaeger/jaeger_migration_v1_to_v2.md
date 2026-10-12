# Миграция Jaeger с v1 на v2

**Актуально для:** Jaeger v1.x → v2.x

> **Важно:** Документация описывает процесс миграции на **Jaeger v2**. Классическая ветка Jaeger v1 достигла статуса **EOL (End of Life)** и больше не поддерживается сообществом. Классический `jaegertracing/jaeger-operator` переведён в статус устаревшего (deprecated) в пользу OpenTelemetry Operator. Все архитектурные решения и сценарии ориентированы на on-premise и bare-metal инфраструктуру (Linux, systemd, Docker, Kubernetes) без привязки к проприетарным облачным сервисам.

**Миграция Jaeger v1 → v2** — это переход от устаревшей архитектуры раздельных специализированных микросервисов (`jaeger-agent`, `jaeger-collector`, `jaeger-query`, `jaeger-ingester`) к архитектуре единого бинарного файла (**Unified Binary**) на базе кодовой базы OpenTelemetry Collector. Процесс миграции затрагивает форматы конфигурации, схему сетевых портов, драйверы хранилищ (ClickHouse, Elasticsearch, Cassandra), механизмы распространения контекста трассировки (Context Propagation) и инструментацию клиентских приложений.

Архитектура компонентов и пайплайнов v2: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Варианты развертывания на on-premise инфраструктуре: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.  
Устройство бэкендов хранения и структуры таблиц: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.  
Развертывание и операторы в Kubernetes: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.  
Спецификация и формат передачи данных: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **EOL (End of Life)** | Официальное прекращение жизненного цикла линейки Jaeger v1: выпуск обновлений безопасности, исправлений ошибок и поддержки старых клиентов прекращен |
| **Unified Binary** | Архитектурная парадигма Jaeger v2: единый исполняемый файл `jaeger`, выполняющий роли Collector, Query, Ingester или All-in-one исключительно на основе YAML-манифеста OpenTelemetry Collector |
| **Storage Extension (`jaeger_storage`)** | Встроенное расширение Jaeger v2, управляющее пулом соединений, драйверами баз данных (ClickHouse, Elasticsearch, Cassandra, Badger, Memory) и трансляцией спанов |
| **Storage Exporter (`jaeger_storage_exporter`)** | Компонент конвейера экспорта Jaeger v2, передающий спаны из OTel-пайплайна в хранилище, сконфигурированное в `jaeger_storage` |
| **Query Extension (`jaeger_query`)** | Расширение Jaeger v2, предоставляющее HTTP UI (порт 16686) и gRPC Query API (порт 16685) для выборки трейсов из сконфигурированного хранилища |
| **OTLP (OpenTelemetry Protocol)** | Стандартизированный протокол CNCF для передачи телеметрии по gRPC (порт 4317) и HTTP/Protobuf (порт 4318), являющийся основным для Jaeger v2 |
| **Legacy Receivers** | Встроенные приемники v2 (`jaeger`, `zipkin`), обеспечивающие обратную совместимость со старыми протоколами Thrift Compact (UDP 6831), Thrift HTTP (14268) и gRPC v1 (14250) |
| **Context Propagation** | Механизм передачи идентификаторов трейса между микросервисами через HTTP/gRPC-заголовки. Переход от проприетарного формата `uber-trace-id` к стандарту W3C `traceparent` |
| **Dual-Run (Параллельный запуск)** | Стратегия бесшовной миграции, при которой Jaeger v2 принимает как устаревший трафик v1 через legacy-порты, так и новый трафик OTLP, исключая окно недоступности |
| **OpenTelemetry Operator** | Kubernetes-оператор, заменивший устаревший Jaeger Operator v1 для декларативного управления жизненным циклом коллекторов и автоинструментации |

---

## Базовые концепции

### Архитектурные различия между Jaeger v1 и Jaeger v2

В первой версии Jaeger каждый функциональный узел представлял собой независимый бинарный файл со своей кодовой базой и специфичными флагами запуска:

*   **Jaeger v1:** Клиенты отправляли трейсы по UDP на локальный демон `jaeger-agent` (порт 6831), который батчировал их и пересылал по TChannel/gRPC на `jaeger-collector` (порты 14268/14250). Коллектор напрямую писал в БД. Для чтения запускался `jaeger-query` с встроенным UI. При высокой нагрузке между коллектором и хранилищем требовалось развертывать Kafka и отдельный бинарник `jaeger-ingester`.
*   **Jaeger v2:** Построен полностью на базе каркаса OpenTelemetry Collector Core/Contrib. Больше нет бинарников `jaeger-agent`, `jaeger-collector` или `jaeger-query`. Все функции выполняет один бинарный файл `jaeger` с декларативным YAML-файлом конфигурации. Пайплайн состоит из четырех стандартных стадий: `receivers` → `processors` → `exporters`, координируемых секцией `service`. Доступ к базам данных вынесен в расширения (`extensions`).

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Jaeger v1 (Устаревшая)                        │
│                                                                        │
│  [App + Jaeger SDK] ──(UDP 6831)──► [jaeger-agent]                    │
│                                            │ (gRPC 14250)              │
│                                            ▼                           │
│                                     [jaeger-collector]                 │
│                                            │                           │
│                     ┌──────────────────────┴─────────────────────┐     │
│                     ▼                                            ▼     │
│            [ClickHouse / ES] ◄────────(gRPC)────────── [jaeger-query]  │
│                                                              │ (16686) │
│                                                              ▼         │
│                                                         [Jaeger UI]    │
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                        Jaeger v2 (Unified Binary)                      │
│                                                                        │
│  [App + OTel SDK] ───────(OTLP 4317/4318)──────┐                       │
│  [App + Legacy SDK] ────(UDP 6831 / gRPC 14250)─┼──┐                   │
│                                                 │  │                   │
│  ┌──────────────────────────────────────────────▼──▼─────────────────┐ │
│  │                    jaeger (Unified Process)                       │ │
│  │                                                                   │ │
│  │  Receivers:   [otlp]              [jaeger legacy]                 │ │
│  │                 │                        │                        │ │
│  │  Processors:    └──────► [memory_limiter] ◄┘                      │ │
│  │                                 │                                 │ │
│  │                                 ▼                                 │ │
│  │                              [batch]                              │ │
│  │                                 │                                 │ │
│  │  Exporters:                     ▼                                 │ │
│  │                     [jaeger_storage_exporter]                     │ │
│  │                                 │                                 │ │
│  │  Extensions:          [jaeger_storage] ◄── [jaeger_query]         │ │
│  └─────────────────────────────────┬──────────────────────┬──────────┘ │
│                                    ▼                      ▼            │
│                            [ClickHouse / ES]        [Jaeger UI 16686]  │
└────────────────────────────────────────────────────────────────────────┘
```

### Сопоставление портов и сетевых интерфейсов

В Jaeger v2 устаревшие порты v1 поддерживаются исключительно для плавного перевода трафика без единовременной модификации всех клиентских приложений:

| Порт | Протокол | Назначение в Jaeger v1 | Роль и статус в Jaeger v2 |
| :--- | :--- | :--- | :--- |
| **4317** | TCP (gRPC) | Не использовался | **OTLP gRPC (Основной)** — прием спанов от OpenTelemetry SDK и OTel Collector |
| **4318** | TCP (HTTP) | Не использовался | **OTLP HTTP (Основной)** — прием спанов в формате Protobuf/JSON по HTTP |
| **16686** | TCP (HTTP) | Jaeger UI / Query HTTP API | **Jaeger UI (Основной)** — предоставляется расширением `jaeger_query` |
| **16685** | TCP (gRPC) | Jaeger Query gRPC | **Query gRPC API** — программное чтение трейсов сторонними системами (Grafana) |
| **8888** | TCP (HTTP) | Не использовался (был 14269) | **Collector Metrics** — внутренние Prometheus-метрики процесса (`/metrics`) |
| **13133** | TCP (HTTP) | Не использовался | **Health Check** — эндпоинт проверки жизнеспособности `healthcheckv2` |
| **14250** | TCP (gRPC) | Прием спанов от `jaeger-agent` | **Legacy gRPC** — поддерживается приемником `receivers.jaeger.protocols.grpc` |
| **14268** | TCP (HTTP) | Прямой прием Thrift HTTP | **Legacy Thrift HTTP** — приемник `receivers.jaeger.protocols.thrift_http` |
| **6831** | UDP | Агент Thrift Compact | **Legacy UDP** — приемник `receivers.jaeger.protocols.thrift_compact` |
| **6832** | UDP | Агент Thrift Binary | **Legacy UDP Binary** — приемник `receivers.jaeger.protocols.thrift_binary` |
| **5778** | TCP (HTTP) | Конфигурация сэмплирования агента | **Sampling HTTP** — поддерживается расширением `remote_sampling` |
| **9411** | TCP (HTTP) | Zipkin JSON/Thrift | **Zipkin HTTP** — поддерживается стандартным приемником `receivers.zipkin` |

> [!WARNING]
> Порт метрик в Jaeger v2 изменился: вместо порта v1 `14269` внутренние метрики OpenTelemetry Collector публикуются на порту **8888** (`/metrics`). Скрейпинг в Prometheus необходимо обновить до вывода старых коллекторов из эксплуатации.

### Сдвиг парадигмы конфигурации (CLI Flags → OTel YAML)

Jaeger v1 настраивался через длинные цепочки флагов командной строки или плоские переменные окружения. Jaeger v2 полностью перешел на иерархическую структуру OpenTelemetry Collector:

```
┌───────────────────────────────────────┐         ┌──────────────────────────────────────────┐
│      Jaeger v1 (Флаги и ENV)          │         │        Jaeger v2 (OTel YAML)             │
├───────────────────────────────────────┤         ├──────────────────────────────────────────┤
│ --span-storage.type=clickhouse        │  ───►   │ extensions:                              │
│ --clickhouse.endpoint=127.0.0.1:9000  │         │   jaeger_storage:                        │
│ --clickhouse.database=jaeger_v2       │         │     backends:                            │
│                                       │         │       ch: { clickhouse: { ... } }        │
├───────────────────────────────────────┤         ├──────────────────────────────────────────┤
│ --collector.grpc-port=14250           │  ───►   │ receivers:                               │
│ --collector.http-port=14268           │         │   jaeger:                                │
│                                       │         │     protocols:                           │
│                                       │         │       grpc: { endpoint: ... }            │
├───────────────────────────────────────┤         ├──────────────────────────────────────────┤
│ --collector.queue-size=10000          │  ───►   │ processors:                              │
│ --collector.num-workers=100           │         │   batch: { ... }                         │
│                                       │         │   memory_limiter: { ... }                │
└───────────────────────────────────────┘         └──────────────────────────────────────────┘
```

### Модели миграции хранилищ (Storage Backends)

В Jaeger v2 взаимодействие с базами данных инкапсулировано в `jaeger_storage`:

1.  **ClickHouse:**
    *   *В версии v1:* часто применялась неофициальная схема таблиц `jaeger_spans` или сторонние прокси-плагины.
    *   *В версии v2:* встроен официальный нативный драйвер ClickHouse. Таблицы спанов и сервисов создаются в структуре `MergeTree` с партиционированием по дням и TTL.
    *   *Стратегия миграции:* Создается новая база данных `jaeger_v2` с целевой схемой v2. Исторические данные v1 остаются доступными в старой БД, а новые спаны v2 пишутся в `jaeger_v2`. При необходимости объединенного поиска накладывается `VIEW`.
2.  **Elasticsearch / OpenSearch:**
    *   *В версии v1:* Использовались суточные индексы `jaeger-span-YYYY-MM-DD` и отдельные cron-скрипты очистки (`jaeger-es-index-cleaner`, `jaeger-es-rollover`).
    *   *В версии v2:* Нативная интеграция с Index Lifecycle Management (ILM) и шаблонами индексов `_index_template/jaeger_v2`.
    *   *Стратегия миграции:* Настройка alias `jaeger_v2` и подключение расширения `jaeger_storage`. Старые спаны v1 доживают свой срок хранения (retention period) в индексах `jaeger-span-*`, после чего удаляются без необходимости конвертации.
3.  **Cassandra:**
    *   Keyspace может быть переиспользован либо выделен в новый `jaeger_v2` с последующим переключением пула соединений.

### Миграция распространения контекста (Context Propagation)

Главная опасность миграции распределенной трассировки — **разрыв цепочки трейса (Broken Trace)** при вызове между уже обновленным сервисом и сервисом на старой библиотеке:

*   **Формат Jaeger v1:** Заголовок `uber-trace-id: {trace-id}:{span-id}:{parent-span-id}:{flags}`.
*   **Стандарт OpenTelemetry:** Заголовки W3C TraceContext: `traceparent: 00-{trace-id}-{span-id}-{flags}` и `tracestate`.
*   **Решение:** На переходный период все клиенты OpenTelemetry SDK настраиваются на композитный пропогатор (`composite propagator`):
    ```bash
    export OTEL_PROPAGATORS="tracecontext,baggage,jaeger,b3"
    ```
    При такой конфигурации сервис извлекает контекст из любого пришедшего заголовка (W3C, Jaeger или Zipkin B3), а при исходящем запросе внедряет как `traceparent`, так и `uber-trace-id`.

---

## Практические сценарии

### Сценарий 1: Инвентаризация и аудит существующей инфраструктуры Jaeger v1

**Ситуация:** Перед развертыванием v2 необходимо выявить все точки входа телеметрии, используемые библиотеки в кодовой базе и состояние портов на хостах.

**Шаги выполнения:**

1.  **Проверка активных сетевых сокетов на серверах трассировки:**
    ```bash
    # Проверка прослушиваемых TCP и UDP портов
    ss -tulnp | grep -E ':(14250|14268|6831|6832|5778|16686|14269)\b'
    ```
    ```text
    # → udp   UNCONN 0      0       0.0.0.0:6831       0.0.0.0:*    users:(("jaeger-agent",pid=1204,fd=5))
    # → tcp   LISTEN 0      128     0.0.0.0:14250      0.0.0.0:*    users:(("jaeger-collecto",pid=1240,fd=7))
    # → tcp   LISTEN 0      128     0.0.0.0:14268      0.0.0.0:*    users:(("jaeger-collecto",pid=1240,fd=8))
    # → tcp   LISTEN 0      128     0.0.0.0:16686      0.0.0.0:*    users:(("jaeger-query",pid=1255,fd=6))
    ```

2.  **Аудит переменных окружения приложений в Kubernetes:**
    ```bash
    # Поиск подов, использующих старые библиотеки Jaeger SDK
    kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"/"}{.metadata.name}{": "}{range .spec.containers[*].env[*]}{.name}{"="}{.value}{" "}{end}{"\n"}{end}' | grep -E "JAEGER_AGENT_HOST|JAEGER_ENDPOINT|JAEGER_SAMPLER"
    ```
    ```text
    # → default/order-service-5896d8b-x7z1a: JAEGER_AGENT_HOST=jaeger-agent.monitoring JAEGER_SAMPLER_TYPE=const 
    # → billing/payment-api-744bc7-q8lp9: JAEGER_ENDPOINT=http://jaeger-collector.monitoring:14268/api/traces
    ```

3.  **Аудит индексов в Elasticsearch (для стека с ES):**
    ```bash
    # Проверка существующих индексов v1 и объема данных
    curl -s -X GET "http://127.0.0.1:9200/_cat/indices/jaeger-*?v&s=index"
    ```
    ```text
    # → health status index                      uuid                   pri rep docs.count docs.deleted store.size
    # → green  open   jaeger-service-2026-10-11  xZ0L9MKnQ7m-1v4fFkLQ1Q   1   1        240            0    120.4kb
    # → green  open   jaeger-span-2026-10-11     aB1C2D3E4F5-6G7H8I9J0K   3   1    4820194            0      3.8gb
    # → green  open   jaeger-span-2026-10-12     kL9M8N7O6P5-4Q3R2S1T0U   3   1    5102941            0      4.1gb
    ```

4.  **Резервное копирование таблиц ClickHouse перед началом работ:**
    ```bash
    # Создание локального снапшота ClickHouse через системный freeze (on-premise)
    clickhouse-client --query "ALTER TABLE jaeger.jaeger_spans FREEZE WITH NAME 'backup_pre_v2_$(date +%Y%m%d)'"
    ```
    ```text
    # → Backup backup_pre_v2_20261012 created successfully
    ```

---

### Сценарий 2: Развертывание Jaeger v2 в режиме Dual-Run с обратной совместимостью

**Ситуация:** Требуется развернуть Jaeger v2 рядом с v1 или вместо него так, чтобы он одновременно принимал спаны от старых клиентов (UDP 6831, gRPC 14250, HTTP 14268) и новых клиентов (OTLP 4317/4318).

**Файл конфигурации Jaeger v2 (`/etc/jaeger/config.yaml`):**

```yaml
receivers:
  # Нативный протокол OTLP для новых клиентов
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

  # Приемник обратной совместимости для старых клиентов и агентов v1
  jaeger:
    protocols:
      grpc:
        endpoint: 0.0.0.0:14250
      thrift_http:
        endpoint: 0.0.0.0:14268
      thrift_compact:
        endpoint: 0.0.0.0:6831
      thrift_binary:
        endpoint: 0.0.0.0:6832

  # Поддержка клиентов Zipkin
  zipkin:
    endpoint: 0.0.0.0:9411

processors:
  # Защита от OOM при всплесках трафика (обязательно первым в пайплайне)
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20

  # Батчинг спанов перед сбросом в хранилище
  batch:
    send_batch_size: 8192
    timeout: 1s

extensions:
  # Проверка статуса сервиса
  healthcheckv2:
    endpoint: 0.0.0.0:13133

  # Пул соединений к хранилищу
  jaeger_storage:
    backends:
      clickhouse_primary:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
          username: "jaeger"
          password: "SecretPassword123"
          connection_limit: 50

  # Веб-интерфейс и Query API
  jaeger_query:
    storage:
      traces: clickhouse_primary
    http:
      endpoint: 0.0.0.0:16686

exporters:
  # Экспортер записи трейсов в сконфигурированный бэкенд
  jaeger_storage_exporter:
    trace_storage: clickhouse_primary

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp, jaeger, zipkin]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: "0.0.0.0"
                port: 8888
```

**Развертывание через Docker Compose (`docker-compose.yml`):**

```yaml
services:
  jaeger-v2:
    image: jaegertracing/jaeger:2.3.0
    container_name: jaeger-v2
    restart: unless-stopped
    command: ["--config", "/etc/jaeger/config.yaml"]
    volumes:
      - ./config.yaml:/etc/jaeger/config.yaml:ro
    ports:
      - "4317:4317"         # OTLP gRPC
      - "4318:4318"         # OTLP HTTP
      - "16686:16686"       # Jaeger Web UI
      - "16685:16685"       # Query gRPC
      - "14250:14250"       # Legacy Collector gRPC
      - "14268:14268"       # Legacy Thrift HTTP
      - "6831:6831/udp"     # Legacy Thrift Compact UDP
      - "8888:8888"         # Prometheus Metrics
      - "13133:13133"       # Healthcheck
    environment:
      - GOMEMLIMIT=3800MiB
```

**Валидация запуска и портов:**

```bash
docker compose up -d
# → [+] Running 1/1
# →  ✔ Container jaeger-v2  Started

# Проверка состояния контейнера
docker compose ps
# → NAME        IMAGE                         COMMAND                  SERVICE      CREATED         STATUS                   PORTS
# → jaeger-v2   jaegertracing/jaeger:2.3.0    "/go/bin/jaeger --co…"   jaeger-v2    5 seconds ago   Up 4 seconds (healthy)   0.0.0.0:4317-4318->4317-4318/tcp, ...

# Проверка доступности интерфейса проверки здоровья
curl -s http://localhost:13133/
# → {"status":"Server available"}

# Проверка приема тестового запроса на старый порт 14268
curl -s -X POST http://localhost:14268/api/traces -H "Content-Type: application/x-thrift" --data-binary @/dev/null -v
# → < HTTP/1.1 202 Accepted
```

---

### Сценарий 3: Трансляция флагов CLI и переменных окружения v1 в YAML v2

**Ситуация:** Требуется перевести существующий production-скрипт запуска `jaeger-collector` и `jaeger-query` на единый файл конфигурации `config.yaml`.

#### Матрица сопоставления параметров

| Назначение | Параметр Jaeger v1 (CLI / ENV) | Эквивалент в Jaeger v2 (YAML) |
| :--- | :--- | :--- |
| **Выбор хранилища** | `--span-storage.type=elasticsearch`<br>`SPAN_STORAGE_TYPE=elasticsearch` | `extensions.jaeger_storage.backends.<name>.elasticsearch` |
| **Адреса Elasticsearch** | `--es.server-urls=http://es1:9200,http://es2:9200`<br>`ES_SERVER_URLS=...` | `extensions.jaeger_storage.backends.<name>.elasticsearch.server_urls: [...]` |
| **Индекс Elasticsearch** | `--es.index-prefix=jaeger_prod`<br>`ES_INDEX_PREFIX=...` | `extensions.jaeger_storage.backends.<name>.elasticsearch.index_prefix: "jaeger_prod"` |
| **Порт Legacy gRPC** | `--collector.grpc-port=14250` | `receivers.jaeger.protocols.grpc.endpoint: "0.0.0.0:14250"` |
| **Порт Legacy HTTP** | `--collector.http-port=14268` | `receivers.jaeger.protocols.thrift_http.endpoint: "0.0.0.0:14268"` |
| **Очередь обработки** | `--collector.queue-size=10000` | `processors.batch.send_batch_size: 8192`<br>`processors.batch.timeout: 1s` |
| **Порт метрик** | `--admin.http.host-port=:14269` | `service.telemetry.metrics.readers[0].pull.exporter.prometheus.port: 8888` |
| **Базовый путь UI** | `--query.base-path=/jaeger` | `extensions.jaeger_query.http.base_path: "/jaeger"` |

#### Исходный скрипт запуска v1 (Legacy bash)

```bash
# Устаревший запуск двух раздельных бинарников
/usr/local/bin/jaeger-collector \
  --span-storage.type=elasticsearch \
  --es.server-urls=http://10.10.0.11:9200,http://10.10.0.12:9200 \
  --es.index-prefix=production \
  --es.num-shards=5 \
  --es.num-replicas=1 \
  --collector.grpc-port=14250 \
  --collector.http-port=14268 \
  --collector.queue-size=50000 &

/usr/local/bin/jaeger-query \
  --span-storage.type=elasticsearch \
  --es.server-urls=http://10.10.0.11:9200,http://10.10.0.12:9200 \
  --es.index-prefix=production \
  --query.base-path=/jaeger &
```

#### Итоговый файл конфигурации v2 (`/etc/jaeger/jaeger-production.yaml`)

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  jaeger:
    protocols:
      grpc:
        endpoint: 0.0.0.0:14250
      thrift_http:
        endpoint: 0.0.0.0:14268

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 75
    spike_limit_percentage: 15
  batch:
    send_batch_size: 10000
    timeout: 500ms

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      es_prod:
        elasticsearch:
          server_urls:
            - "http://10.10.0.11:9200"
            - "http://10.10.0.12:9200"
          index_prefix: "production"
          num_shards: 5
          num_replicas: 1
  jaeger_query:
    storage:
      traces: es_prod
    http:
      endpoint: 0.0.0.0:16686
      base_path: "/jaeger"

exporters:
  jaeger_storage_exporter:
    trace_storage: es_prod

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp, jaeger]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      readers:
        - pull:
            exporter:
              prometheus:
                host: "0.0.0.0"
                port: 8888
```

---

### Сценарий 4: Миграция бэкендов хранения без простоя (ClickHouse и Elasticsearch)

**Ситуация:** Эксплуатируется production-кластер хранения с непрерывным потоком трейсов. Нужно перевести запись на v2, не потеряв возможность читать исторические данные за предыдущие 7 дней.

#### 1. Подготовка ClickHouse

Для Jaeger v2 развертывается новая структура базы данных:

```sql
-- Создание базы данных для Jaeger v2
CREATE DATABASE IF NOT EXISTS jaeger_v2;

-- Основная таблица спанов с эффективным первичным ключом и сжатием LZ4
CREATE TABLE IF NOT EXISTS jaeger_v2.jaeger_spans (
    timestamp DateTime64(6) CODEC(DoubleDelta, LZ4),
    trace_id String CODEC(ZSTD(1)),
    span_id String CODEC(ZSTD(1)),
    parent_span_id String CODEC(ZSTD(1)),
    operation_name LowCardinality(String),
    service_name LowCardinality(String),
    duration_us Int64 CODEC(T64, ZSTD(1)),
    tags Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    status_code LowCardinality(String),
    status_message String CODEC(ZSTD(1))
) ENGINE = MergeTree()
PARTITION BY toDate(timestamp)
ORDER BY (service_name, operation_name, timestamp)
TTL toDate(timestamp) + INTERVAL 7 DAY DELETE
SETTINGS index_granularity = 8192;
```

```bash
# Выполнение миграции схемы через консоль
clickhouse-client --multiquery < /tmp/jaeger_v2_schema.sql
# → Query id: 1b8d818e-49b8-4c12-881b-5136fa9dc810
# → Ok.
```

#### 2. Подготовка Elasticsearch (Index Lifecycle Management)

```bash
# Создание политики ILM для удаления индексов через 7 дней
curl -X PUT "http://127.0.0.1:9200/_ilm/policy/jaeger_v2_policy" -H 'Content-Type: application/json' -d'
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_primary_shard_size": "30gb",
            "max_age": "1d"
          }
        }
      },
      "delete": {
        "min_age": "7d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
```
```text
# → {"acknowledged":true}
```

```bash
# Создание шаблона индексов для v2
curl -X PUT "http://127.0.0.1:9200/_index_template/jaeger_v2_template" -H 'Content-Type: application/json' -d'
{
  "index_patterns": ["jaeger_v2-*"],
  "template": {
    "settings": {
      "index.lifecycle.name": "jaeger_v2_policy",
      "index.lifecycle.rollover_alias": "jaeger_v2",
      "number_of_shards": 3,
      "number_of_replicas": 1
    }
  }
}'
```
```text
# → {"acknowledged":true}
```

```bash
# Инициализация первого индекса с алиасом записи
curl -X PUT "http://127.0.0.1:9200/jaeger_v2-000001" -H 'Content-Type: application/json' -d'
{
  "aliases": {
    "jaeger_v2": {
      "is_write_index": true
    }
  }
}'
```
```text
# → {"acknowledged":true,"shards_acknowledged":true,"index":"jaeger_v2-000001"}
```

**План бесшовного переключения:**
1. Запустить Jaeger v2 с записью в `jaeger_v2` (ClickHouse или Elasticsearch).
2. Оставить старый `jaeger-query` v1 доступным для инженеров на резервном URL (`http://jaeger-legacy.internal:16686`) на время жизни старых данных (7 дней).
3. Основной трафик инженеров направить на новый `jaeger_query` v2 (`http://jaeger.internal:16686`).
4. По истечении 7 дней старые индексы `jaeger-span-*` v1 полностью удаляются по TTL, и старый Query останавливается.

---

### Сценарий 5: Миграция в Kubernetes (переход с Jaeger Operator на OpenTelemetry Operator)

**Ситуация:** В кластере Kubernetes развернут устаревший `jaegertracing/jaeger-operator` с ресурсом `kind: Jaeger`. Требуется перейти на стандартизированный `OpenTelemetry Operator` и манифест `OpenTelemetryCollector`.

#### 1. Устаревший манифест v1 (`jaeger-v1-cr.yaml`):

```yaml
apiVersion: jaegertracing.io/v1
kind: Jaeger
metadata:
  name: jaeger-cluster
  namespace: observability
spec:
  strategy: production
  storage:
    type: elasticsearch
    options:
      es:
        server-urls: http://elasticsearch.logging.svc.cluster.local:9200
  collector:
    replicas: 3
  query:
    replicas: 2
```

#### 2. Новый манифест OpenTelemetry Operator (`jaeger-v2-otel-cr.yaml`):

```yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: jaeger-v2
  namespace: observability
spec:
  image: jaegertracing/jaeger:2.3.0
  mode: deployment
  replicas: 3
  resources:
    limits:
      cpu: "2"
      memory: 4Gi
    requests:
      cpu: "500m"
      memory: 1Gi
  env:
    - name: GOMEMLIMIT
      value: "3600MiB"
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
          http:
            endpoint: 0.0.0.0:4318
      jaeger:
        protocols:
          grpc:
            endpoint: 0.0.0.0:14250
          thrift_http:
            endpoint: 0.0.0.0:14268

    processors:
      memory_limiter:
        check_interval: 500ms
        limit_percentage: 80
        spike_limit_percentage: 20
      batch:
        send_batch_size: 8192
        timeout: 1s

    extensions:
      healthcheckv2:
        endpoint: 0.0.0.0:13133
      jaeger_storage:
        backends:
          es_cluster:
            elasticsearch:
              server_urls:
                - "http://elasticsearch.logging.svc.cluster.local:9200"
              index_prefix: "jaeger_v2"
      jaeger_query:
        storage:
          traces: es_cluster
        http:
          endpoint: 0.0.0.0:16686

    exporters:
      jaeger_storage_exporter:
        trace_storage: es_cluster

    service:
      extensions: [healthcheckv2, jaeger_storage, jaeger_query]
      pipelines:
        traces:
          receivers: [otlp, jaeger]
          processors: [memory_limiter, batch]
          exporters: [jaeger_storage_exporter]
      telemetry:
        metrics:
          readers:
            - pull:
                exporter:
                  prometheus:
                    host: "0.0.0.0"
                    port: 8888
```

#### 3. Применение и миграция Service:

```bash
# Применение нового коллектора
kubectl apply -f jaeger-v2-otel-cr.yaml
# → opentelemetrycollector.opentelemetry.io/jaeger-v2 created

# Проверка статуса запуска подов
kubectl get pods -n observability -l app.kubernetes.io/name=jaeger-v2-collector
# → NAME                                    READY   STATUS    RESTARTS   AGE
# → jaeger-v2-collector-5d687449b5-c4h9x    1/1     Running   0          25s
# → jaeger-v2-collector-5d687449b5-j7r9v    1/1     Running   0          25s
# → jaeger-v2-collector-5d687449b5-z2x5p    1/1     Running   0          25s

# Перенаправление существующего Kubernetes Service на новые селекторы (zero-downtime)
kubectl patch svc jaeger-collector -n observability -p '{"spec":{"selector":{"app.kubernetes.io/name":"jaeger-v2-collector"}}}'
# → service/jaeger-collector patched
```

---

### Сценарий 6: Миграция на Bare-Metal Linux с Systemd

**Ситуация:** На физических серверах Debian/Ubuntu запущены демоны `jaeger-collector.service` и `jaeger-query.service`. Требуется объединить их в один unit `jaeger.service` и настроить сетевые параметры ядра для исключения потерь UDP-пакетов на порту 6831.

#### 1. Тюнинг сетевого стека ядра Linux (`/etc/sysctl.d/99-jaeger.conf`):

```ini
# Увеличение максимального размера буфера приема сетевых пакетов UDP
net.core.rmem_max = 16777216
net.core.rmem_default = 2097152

# Увеличение длины очереди сетевой карты
net.core.netdev_max_backlog = 10000
```

```bash
# Применение параметров ядра
sysctl -p /etc/sysctl.d/99-jaeger.conf
# → net.core.rmem_max = 16777216
# → net.core.rmem_default = 2097152
# → net.core.netdev_max_backlog = 10000
```

#### 2. Установка бинарного файла и создание пользователя:

```bash
# Создание сервисного пользователя без оболочки
useradd -r -s /bin/false -d /var/lib/jaeger jaeger

# Размещение бинарника Jaeger v2
install -m 0755 /tmp/jaeger /usr/local/bin/jaeger

# Создание каталогов для конфигурации и логов
mkdir -p /etc/jaeger /var/log/jaeger
chown -R jaeger:jaeger /var/log/jaeger /etc/jaeger
```

#### 3. Создание Systemd Unit файла (`/etc/systemd/system/jaeger.service`):

```ini
[Unit]
Description=Jaeger v2 Unified Telemetry Engine
Documentation=https://www.jaegertracing.io/docs/2.3/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=jaeger
Group=jaeger
Environment="GOMEMLIMIT=7200MiB"
LimitNOFILE=65536
LimitNPROC=32768
ExecStart=/usr/local/bin/jaeger --config /etc/jaeger/config.yaml
Restart=on-failure
RestartSec=5s

# Защита процесса (Systemd Hardening)
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/jaeger
PrivateTmp=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
```

```bash
# Остановка старых сервисов v1
systemctl stop jaeger-collector jaeger-query
systemctl disable jaeger-collector jaeger-query

# Активация и запуск нового сервиса v2
systemctl daemon-reload
systemctl enable --now jaeger
# → Created symlink /etc/systemd/system/multi-user.target.wants/jaeger.service → /etc/systemd/system/jaeger.service.

# Проверка статуса сервиса
systemctl status jaeger --no-pager
# → ● jaeger.service - Jaeger v2 Unified Telemetry Engine
# →      Loaded: loaded (/etc/systemd/system/jaeger.service; enabled; vendor preset: enabled)
# →      Active: active (running) since Sun 2026-10-12 14:30:10 UTC; 4s ago
# →    Main PID: 28410 (jaeger)
# →       Tasks: 18 (limit: 38383)
# →      Memory: 114.2M
```

---

### Сценарий 7: Миграция клиентских библиотек приложений (SDK Migration)

**Ситуация:** Микросервисы используют устаревшие библиотеки `jaeger-client-go`, `jaeger-client-python` или `jaeger-client-java`. Требуется перевести их на официальный OpenTelemetry SDK без потери трассировки между обновленными и необновленными сервисами.

#### 1. Переменные окружения для OpenTelemetry SDK

Каждый обновляемый микросервис настраивается через стандартные переменные CNCF OTel:

```bash
# Адрес коллектора Jaeger v2 (gRPC порт 4317)
export OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger-collector.internal:4317"
export OTEL_EXPORTER_OTLP_PROTOCOL="grpc"

# Имя сервиса
export OTEL_SERVICE_NAME="order-processor"

# Композитные пропогаторы: извлекает W3C, Jaeger и B3, внедряет W3C и Jaeger
export OTEL_PROPAGATORS="tracecontext,baggage,jaeger"

# Сэмплирование: 100% родительское или по умолчанию
export OTEL_TRACES_SAMPLER="parentbased_always_on"
```

#### 2. Пример миграции инициализации в Go

**Было (Jaeger Client v1 — устарело):**

```go
// Устаревший Jaeger Client v1 (EOL)
cfg := jaegercfg.Configuration{
    ServiceName: "order-processor",
    Sampler: &jaegercfg.SamplerConfig{
        Type:  jaeger.SamplerTypeConst,
        Param: 1,
    },
    Reporter: &jaegercfg.ReporterConfig{
        LogSpans:           false,
        LocalAgentHostPort: "127.0.0.1:6831", // Отправка по UDP
    },
}
tracer, closer, err := cfg.NewTracer()
opentracing.SetGlobalTracer(tracer)
```

**Стало (OpenTelemetry SDK v2):**

```go
package main

import (
    "context"
    "log"

    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/propagation"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
    semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials/insecure"
)

func initTracer(ctx context.Context) (*sdktrace.TracerProvider, error) {
    // Подключение к Jaeger v2 по OTLP/gRPC
    exporter, err := otlptracegrpc.New(ctx,
        otlptracegrpc.WithInsecure(),
        otlptracegrpc.WithEndpoint("jaeger-collector.internal:4317"),
        otlptracegrpc.WithDialOption(grpc.WithBlock()),
    )
    if err != nil {
        return nil, err
    }

    res, err := resource.New(ctx,
        resource.WithAttributes(
            semconv.ServiceNameKey.String("order-processor"),
        ),
    )
    if err != nil {
        return nil, err
    }

    tp := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter),
        sdktrace.WithResource(res),
    )

    otel.SetTracerProvider(tp)
    // Установка W3C TraceContext + Jaeger Propagator
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
        propagation.TraceContext{},
        propagation.Baggage{},
    ))

    return tp, nil
}
```

---

### Сценарий 8: Вывод из эксплуатации устаревших компонентов и отключение legacy-портов

**Ситуация:** Все приложения переведены на OTLP. Необходимо закрыть устаревшие порты v1 в конфигурации Jaeger v2, заблокировать их в межсетевом экране и отключить устаревшие демоны.

#### 1. Проверка отсутствия входящего трафика на старых портах через Prometheus

Перед отключением проверяются метрики на порту `8888`:

```bash
# Проверка счетчиков спанов, принятых legacy-приемником jaeger
curl -s http://127.0.0.1:8888/metrics | grep 'otelcol_receiver_accepted_spans'
```
```text
# → otelcol_receiver_accepted_spans{receiver="otlp",transport="grpc"} 9482150
# → otelcol_receiver_accepted_spans{receiver="otlp",transport="http"} 124018
# → otelcol_receiver_accepted_spans{receiver="jaeger",transport="grpc"} 0
# → otelcol_receiver_accepted_spans{receiver="jaeger",transport="udp"} 0
```
Если счетчики для `receiver="jaeger"` остаются нулевыми в течение суток — трафик v1 полностью исчерпан.

#### 2. Обновление конфигурации v2 (`/etc/jaeger/config.yaml`):

Удалите секцию `jaeger:` из `receivers` и уберите его из списка в `service.pipelines.traces`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

# Секция legacy receivers удалена

processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
  batch:
    send_batch_size: 8192
    timeout: 1s

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp] # Только OTLP
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

```bash
# Перезагрузка сервиса Jaeger
systemctl reload-or-restart jaeger

# Проверка закрытия портов через ss
ss -tulnp | grep -E ':(14250|14268|6831|6832)\b'
# → (Вывод пустой: сокеты успешно закрыты)
```

#### 3. Блокировка на уровне nftables / iptables:

```bash
# Удаление разрешающих правил для устаревших портов (on-premise безопасность)
iptables -D INPUT -p udp -m udp --dport 6831 -j ACCEPT
iptables -D INPUT -p tcp -m tcp --dport 14250 -j ACCEPT
iptables -D INPUT -p tcp -m tcp --dport 14268 -j ACCEPT
```

---

## Типичные проблемы и устранение неполадок

| Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Разрыв цепочки трейса (Broken Trace) между сервисами** | Обновленный сервис шлет только W3C заголовок (`traceparent`), а необновленный downstream ждет заголовок `uber-trace-id` | Проверка HTTP-заголовков входящего запроса:<br>`tcpdump -A -s 0 -i any 'tcp port 8080 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12:2]>>10)<<2)) != 0)' \| grep -iE 'traceparent\|uber-trace-id'` | Настроить в OTel SDK обновленного сервиса композитный пропогатор:<br>`OTEL_PROPAGATORS="tracecontext,baggage,jaeger"` |
| **Потеря спанов по UDP (порт 6831) при нагрузке** | Переполнение буфера сокета ядра ОС Linux (`receive buffer errors`) | Выполнить проверку дропов сокета:<br>`netstat -su \| grep "receive buffer errors"`<br>или `ss -u -a` (столбец Drop) | 1. Увеличить `net.core.rmem_max` до `16777216` в `/etc/sysctl.conf`.<br>2. Ускорить перевод приложений с UDP на надежный OTLP/gRPC (4317) |
| **Падение процесса Jaeger v2 по OOMKilled** | В конфигурации v2 отсутствует `memory_limiter` или он размещен после `batch` процессора | Анализ логов ядра и статуса контейнера:<br>`dmesg -T \| grep -i oom`<br>или `kubectl describe pod jaeger-v2` | 1. Поместить `memory_limiter` строго **первым** в списке `processors`.<br>2. Задать `GOMEMLIMIT` на уровне 80–85% от лимита памяти контейнера/cgroup |
| **Ошибка запуска: `failed to get trace storage: backend not found`** | Имя бэкенда в `exporters.jaeger_storage_exporter.trace_storage` не совпадает с ключом в `extensions.jaeger_storage.backends` | Просмотр логов запуска процесса:<br>`journalctl -u jaeger -n 50 --no-pager \| grep -i "storage"` | Привести к единому идентификатору имя бэкенда в секциях `backends:` и `trace_storage:` |
| **Спаны пишутся, но UI не отображает данные** | Расширение `jaeger_query` настроено на другое имя хранилища или старую схему данных | Проверка логов query-расширения:<br>`curl -s http://localhost:16686/api/services \| jq .`<br>`# → {"data":[],"total":0,"limit":0,"offset":0,"errors":null}` | Убедиться, что `extensions.jaeger_query.storage.traces` ссылается на тот же бэкенд, что и `jaeger_storage_exporter` |
| **Elasticsearch: ошибка маппинга полей (`mapper_parsing_exception`)** | Jaeger v2 попытался записать документы в индекс, созданный шаблоном v1 со старыми типами полей | Просмотр ошибок в логах Jaeger:<br>`journalctl -u jaeger \| grep -i "mapper_parsing_exception"` | Использовать новый префикс индексов (например, `jaeger_v2`) и отдельный шаблон `_index_template/jaeger_v2` |
| **ClickHouse: тайм-аут пула соединений (`connection pool exhausted`)** | Превышен лимит параллельных соединений в `jaeger_storage` при высокой интенсивности записи | Проверка метрик OTel экспортера:<br>`curl -s http://localhost:8888/metrics \| grep otelcol_exporter_enqueue_failed_spans` | Увеличить `connection_limit` в блоке `clickhouse:` и увеличить параметр `max_connections` в `clickhouse-server/config.xml` |

---

## Лучшие практики

1.  **Поэтапный переход (Phased Rollout):** Всегда выполняйте миграцию в строгой последовательности:
    *   *Этап 1:* Развертывание Jaeger v2 в режиме Dual-Run с сохранением всех портов обратной совместимости.
    *   *Этап 2:* Проверка записи и чтения через новый UI на порту 16686.
    *   *Этап 3:* Постепенная инструментация сервисов через OpenTelemetry SDK (начиная с наименее критичных).
    *   *Этап 4:* Деактивация портов обратной совместимости и удаление устаревших демонов `jaeger-agent`.
2.  **Обязательное использование `memory_limiter`:** В Jaeger v2 процессор `memory_limiter` должен всегда стоять первым в цепочке `processors: [memory_limiter, batch]`. Это гарантирует, что коллектор будет мягко отбрасывать спаны при исчерпании лимитов вместо внезапного аварийного завершения по OOM.
3.  **Композитные пропогаторы на переходный период:** Включайте поддержку заголовков `jaeger` во всех новых сервисах (`OTEL_PROPAGATORS="tracecontext,baggage,jaeger"`), чтобы предотвратить разрыв трейсов в гетерогенном окружении.
4.  **Фиксация версий образов:** В production-манифестах категорически запрещено использовать теги `:latest` или `:2`. Всегда фиксируйте точные патч-версии (например, `jaegertracing/jaeger:2.3.0`).
5.  **Контроль сходимости метрик:** В процессе миграции отслеживайте равенство входящих спанов через Grafana: сумма `otelcol_receiver_accepted_spans{receiver="otlp"}` и `otelcol_receiver_accepted_spans{receiver="jaeger"}` должна коррелировать с историческими показателями `jaeger_collector_spans_received_total`.
6.  **Изоляция хранилищ по схемам:** Не пытайтесь писать данные v2 поверх индексов или таблиц v1. Создавайте отдельные пространства имен (`jaeger_v2` в ClickHouse, индексные алиасы `jaeger_v2` в Elasticsearch).

---

## Очистка окружения

После завершения миграции всех микросервисов и истечения срока хранения данных (retention period) в старой системе:

```bash
# 1. Остановка и удаление устаревших демонов v1 (на хостах Linux)
systemctl stop jaeger-collector jaeger-query jaeger-agent
systemctl disable jaeger-collector jaeger-query jaeger-agent
rm -f /etc/systemd/system/jaeger-*.service
systemctl daemon-reload

# 2. Удаление устаревших DaemonSet jaeger-agent в Kubernetes
kubectl delete daemonset jaeger-agent -n observability --ignore-not-found

# 3. Удаление устаревшего оператора Jaeger v1 (при использовании OpenTelemetry Operator)
kubectl delete deployment jaeger-operator -n observability --ignore-not-found
kubectl delete crd jaegers.jaegertracing.io --ignore-not-found

# 4. Удаление старых таблиц/индексов v1 после истечения срока хранения (ClickHouse)
clickhouse-client --query "DROP TABLE IF EXISTS jaeger.jaeger_spans SYNC"
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**

*   Архитектура и внутренние компоненты: **[Архитектура Jaeger](./jaeger_architecture.md)**
*   Варианты развертывания на on-premise инфраструктуре: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
*   Детальный разбор хранилищ (ClickHouse, Elasticsearch): **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
*   Интеграция с Kubernetes и OpenTelemetry Operator: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
*   Анализ производительности и сайзинг: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
*   Диагностика узких мест и профилирование: **[Анализ производительности Jaeger](./jaeger_performance_analysis.md)**
*   Спецификация транспорта OTLP: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**

### См. также

*   [Официальное руководство по миграции Jaeger v1 на v2 (Jaeger Tracing)](https://www.jaegertracing.io/docs/latest/migration/)
*   [Спецификация OpenTelemetry Collector Configuration](https://opentelemetry.io/docs/collector/configuration/)
*   [Репозиторий Jaeger v2 на GitHub](https://github.com/jaegertracing/jaeger)
