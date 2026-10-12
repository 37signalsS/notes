# Архитектура Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая стабильная линейка v2.x / v2.22+). Jaeger v1 достиг **EOL (End of Life)**.

**Архитектура Jaeger v2** построена на базе фреймворка **OpenTelemetry Collector**. Компоненты Jaeger интегрированы непосредственно в бинарный дистрибутив OpenTelemetry в виде специализированных расширений (Extensions), процессоров (Processors) и экспортеров (Exporters). Это обеспечивает унификацию конвейеров телеметрии, нативную обработку протокола OTLP, гибкую маршрутизацию спанов и модульную ролевую модель на базе единого исполняемого файла.

Общий обзор концепций трассировки: **[Обзор Jaeger](./jaeger_overview.md)**.  
Варианты топологического развертывания: **[Варианты развертывания](./jaeger_deployment_options.md)**.

---

## Определения

| Компонент / Термин | Назначение |
| :--- | :--- |
| **Jaeger Binary (v2)** | Единый бинарный дистрибутив на базе OpenTelemetry Collector Core/Contrib, выполняющий функции приема, буферизации, обработки, маршрутизации и отдачи данных трассировки |
| **Pipeline DAG** | Направленный ациклический граф конвейера обработки данных внутри коллектора: цепочка `receivers → processors → exporters` (или `connectors`) |
| **pdata (Pipeline Data)** | Внутренняя zero-copy модель данных OpenTelemetry в памяти процесса Jaeger, используемая для эффективной передачи спанов между компонентами без постоянной переупаковки |
| **Storage Extension (`jaeger_storage`)** | Централизованное расширение Jaeger v2, управляющее пулами соединений, повторными попытками и адаптерами к бэкендам хранения (ClickHouse, Elasticsearch, Cassandra, Memory) |
| **Storage Exporter (`jaeger_storage_exporter`)** | Специализированный экспортер, преобразующий структуры спанов OTLP в формат хранения Jaeger и отправляющий их в бэкенд через `jaeger_storage` |
| **Query Extension (`jaeger_query`)** | Расширение, запускающее HTTP и gRPC серверы для обслуживания Query API и встроенного веб-интерфейса Jaeger UI |
| **Remote Sampling Extension (`remote_sampling`)** | Расширение для обслуживания клиентских запросов SDK по протоколам HTTP/gRPC с выдачей статических или динамических стратегий сэмплирования |
| **Adaptive Sampling Processor (`adaptive_sampling`)** | Процессор, анализирующий входящий поток спанов по связкам `(service, operation)` и рассчитывающий вероятности сэмплирования для удержания целевого RPS |
| **Memory Limiter Processor (`memory_limiter`)** | Процессор ранней защиты от аварийного завершения процесса (OOM) путем принудительного отбрасывания данных или отказа в приеме при исчерпании лимитов RAM |
| **Unified Binary Role** | Специализация инстанса Jaeger (`all-in-one`, `collector`, `ingester`, `query`, `agent`), определяемая исключительно составом включенных в YAML компонентов |
| **Ingester Role** | Роль бинарного файла, считывающая спаны из очередей Kafka (через `kafka` receiver) и записывающая их в постоянное хранилище |
| **Connector** | Компонент OTel Collector, объединяющий конец одного конвейера с началом другого (в Jaeger v2 используется `jaeger_storage_exporter` для построения Dead-Letter Queue) |
| **Backpressure** | Механизм передачи сигнала о перегрузке от хранилища и очередей экспортера обратно к входящим портам коллектора и клиентам SDK |

---

## Базовые концепции и архитектура

### Эволюция архитектуры: переход от Jaeger v1 к v2

Архитектура Jaeger v1 состояла из нескольких отдельных монофункциональных исполняемых файлов:
- `jaeger-agent` — локальный демон/sidecar, принимавший спаны от устаревших Jaeger SDK по UDP (Thrift) и пересылавший их по gRPC в Collector;
- `jaeger-collector` — центральный сервис валидации, предобработки и записи спанов в БД;
- `jaeger-ingester` — специализированный сервис вычитывания сообщений из Kafka и записи в БД;
- `jaeger-query` — отдельный веб-сервис с REST API и статическими файлами UI.

В Jaeger v2 эта модель заменена на **единую расширяемую платформу OpenTelemetry Collector**:

```
[Jaeger v1 Architecture]
SDK (Thrift/UDP) ──> jaeger-agent (gRPC) ──> jaeger-collector ──> Storage
                                                    │
                                                    └──> Kafka ──> jaeger-ingester ──> Storage
Browser ──> jaeger-query (HTTP/UI) ───────────────────────────────────┘

[Jaeger v2 Architecture]
OTel SDK (OTLP/gRPC) ──> [Edge OTel Collector] ──> Jaeger v2 Binary ──> Storage (ClickHouse/ES)
                                                   ├── jaeger_storage
                                                   ├── jaeger_query (HTTP 16686 UI)
                                                   └── remote_sampling
```

Ключевые архитектурные преимущества v2:
1. **Унификация сетевого протокола:** Стандартом стал протокол **OTLP** (OpenTelemetry Protocol) поверх gRPC (порт 4317) и HTTP (порт 4318) с Protobuf-сериализацией. Устаревшие протоколы (Jaeger Thrift, Zipkin) поддерживаются как опциональные receivers.
2. **Модульный конвейер обработки данных:** Любой инстанс Jaeger v2 может использовать стандартные процессоры экосистемы OTel (батчинг, обогащение метаданными инфраструктуры, фильтрация персональных данных, агрегация метрик).
3. **Единый образ и бинарный файл:** Эксплуатация упрощена за счет одного бинарного файла `jaeger` (образ `jaegertracing/jaeger:2.x`), чья роль задается YAML-конфигурацией.
4. **Концепция Extensions:** Функционал разделения доступа к хранилищам, интерфейсам UI и сэмплированию вынесен в расширения, управляющие жизненным циклом фоновых служб независимо от потоков данных.

---

### Внутренний конвейер обработки данных (Pipeline DAG)

Внутри процесса Jaeger v2 спаны проходят строгий конвейер, построенный на модели pdata (структуры данных в памяти с минимальным оверхедом на аллокации):

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Jaeger v2 Process                                                         │
│                                                                           │
│  [Receivers]              [Processors Pipeline]            [Exporters]    │
│  ┌──────────────┐         ┌─────────────────────────┐      ┌────────────┐ │
│  │ otlp (gRPC)  │────┐    │ 1. memory_limiter       │  ┌──>│ jaeger_    │ │
│  └──────────────┘    │    │    (ранний дроп при OOM)│  │   │ storage_   │ │
│  ┌──────────────┐    ├───>│ 2. k8sattributes/attrs  │──┤   │ exporter   │ │
│  │ otlp (HTTP)  │────┤    │    (обогащение спанов)  │  │   └──────┬─────┘ │
│  └──────────────┘    │    │ 3. batch                │  │          │       │
│  ┌──────────────┐    │    │    (буферизация пачек)  │  │          ▼       │
│  │ kafka (Ing.) │────┘    └─────────────────────────┘  │   ┌────────────┐ │
│  └──────────────┘                                      └──>│ kafka      │ │
│                                                            │ exporter   │ │
│  [Extensions Subsystem]                                    └────────────┘ │
│  ┌────────────────────────┐  ┌────────────────────────┐                   │
│  │ jaeger_storage         │  │ jaeger_query           │                   │
│  │ (ClickHouse/ES/Memory) │  │ (REST API & UI: 16686) │                   │
│  └────────────────────────┘  └────────────────────────┘                   │
└───────────────────────────────────────────────────────────────────────────┘
```

Этапы прохождения спана:
1. **Прием (Ingestion):** `receiver` принимает байты из сетевого сокета (TCP), валидирует Protobuf/JSON и преобразует payload во внутренние структуры `pdata.Traces`.
2. **Защита от перегрузки (Memory Check):** `memory_limiter` проверяет текущее состояние кучи Go и cgroup-лимитов. Если память превышает `spike_limit`, запрос немедленно отклоняется с ошибкой gRPC `ResourceExhausted` (Backpressure).
3. **Обогащение и трансформация (Processing):** Процессоры модифицируют спаны, маскируют чувствительные теги, добавляют атрибуты узла или пода.
4. **Батчинг (Batching):** `batch` processor накапливает спаны до достижения лимита размера (`send_batch_size`) или таймаута (`timeout`), снижая количество I/O-операций.
5. **Очередь и отправка (Queue & Export):** `jaeger_storage_exporter` помещает батч во внутреннюю очередь `queue` (bounded buffer). Воркеры пула извлекают пачки и передают их в драйвер бэкенда через `jaeger_storage`.

---

### Ролевая модель Unified Binary

В Jaeger v2 функциональная роль экземпляра определяется набором компонентов в конфигурационном файле:

| Роль | Активные компоненты | Назначение в архитектуре |
| :--- | :--- | :--- |
| **All-in-one** | `receivers`: [otlp, jaeger]<br>`processors`: [batch]<br>`exporters`: [jaeger_storage_exporter]<br>`extensions`: [jaeger_storage, jaeger_query, remote_sampling] | Локальная разработка, стенды интеграционного тестирования, небольшие автономные контуры (in-memory / Badger) |
| **Collector** | `receivers`: [otlp]<br>`processors`: [memory_limiter, batch]<br>`exporters`: [jaeger_storage_exporter] или [kafka]<br>`extensions`: [jaeger_storage] | Высоконагруженный прием телеметрии от приложений, валидация и запись напрямую в БД или буфер Kafka |
| **Ingester** | `receivers`: [kafka]<br>`processors`: [batch]<br>`exporters`: [jaeger_storage_exporter]<br>`extensions`: [jaeger_storage] | Асинхронное вычитывание спанов из очередей Kafka и пакетная запись в постоянное хранилище |
| **Query** | `receivers`: [nop]<br>`processors`: []<br>`exporters`: [nop]<br>`extensions`: [jaeger_storage, jaeger_query] | Выделенный узел чтения: UI и Query API для инженеров, Grafana и внешних систем. Не принимает входящие трейсы |
| **Agent / Edge** | `receivers`: [otlp]<br>`processors`: [memory_limiter, batch]<br>`exporters`: [otlp]<br>`extensions`: [] | Локальный сборщик на хосте или DaemonSet в Kubernetes. Выполняет предварительный батчинг и проксирует OTLP в центральные коллекторы |

---

### Архитектура подсистемы хранения (Storage Extension)

В отличие от классического OpenTelemetry Collector, где каждый экспортер независимо открывает свои сетевые соединения, Jaeger v2 требует совместного использования бэкенда хранения компонентами записи (`jaeger_storage_exporter`) и чтения (`jaeger_query`).

Эту задачу решает расширение **`jaeger_storage`**:
- **Пул соединений (Connection Pooling):** Создает единый пул TCP/HTTP соединений к базе данных, предотвращая исчерпание сокетов.
- **Драйверы бэкендов:** Реализует интерфейсы взаимодействия с базами данных:
  - **ClickHouse:** Первоклассный бэкенд (first-class citizen) для высоконагруженных сред. Колоночное хранение, эффективное сжатие (LZ4/ZSTD) и партиционирование по дням обеспечивают минимальную нагрузку на дисковую подсистему и мгновенное удаление старых данных по TTL.
  - **Elasticsearch / OpenSearch:** Документоориентированное хранилище с полнотекстовым поиском. Требует управления индексами (ILM/ISM) и потребляет существенно больше памяти под JVM.
  - **Cassandra:** Исторический NoSQL бэкенд для линейной масштабируемости записи по ключу, но с ограниченными возможностями фильтрации по произвольным тегам.
  - **Memory:** Хранилище в оперативной памяти процесса (кольцевой буфер `max_traces`), данные сбрасываются при перезапуске.
  - **Badger:** Встраиваемое key-value хранилище на основе LSM-дерева на локальном диске для одноузловых инсталляций.

---

### Управление памятью, очередями и Backpressure

Для надежной работы в SRE/DevOps окружениях Jaeger v2 реализует многоуровневый контур контроля очередей и ресурсов памяти:

```
[Входящий OTLP запрос]
       │
       ▼
┌────────────────────────────────────────────────────────┐
│ 1. Memory Limiter Processor                            │
│    Использование RAM > limit?                          │
│    ├── ДА ──> Возврат gRPC ResourceExhausted (429/503) │
│    └── НЕТ                                             │
└──────────────────────┬─────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────┐
│ 2. Batch Processor                                     │
│    Накопление до send_batch_size или timeout           │
└──────────────────────┬─────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────┐
│ 3. Storage Exporter Queue                              │
│    Очередь queue_size заполнена?                       │
│    ├── ДА  ──> otelcol_exporter_enqueue_failed_spans   │
│    └── НЕТ ──> Пул воркеров num_consumers              │
└──────────────────────┬─────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────┐
│ 4. Storage Driver & Database                           │
│    Сбой записи / таймаут сокета?                       │
│    ├── retry_on_failure: повторные попытки             │
│    └── Dead-Letter Queue Connector (при терминальном   │
│        сбое)                                           │
└────────────────────────────────────────────────────────┘
```

1. **Взаимодействие Go Runtime и cgroups:**
   - Коллектор написан на Go. По умолчанию сборщик мусора ориентируется на процент прироста кучи (`GOGC=100`). При резком всплеске спанов аллокации могут превысить лимит памяти контейнера/узла до срабатывания GC, что приводит к OOM-Kill ядром Linux.
   - В Jaeger v2 критически важно задавать переменную окружения `GOMEMLIMIT` (на уровне 80–85% от лимита памяти процесса) совместно с `memory_limiter` процессором (`limit_percentage: 80`, `spike_limit_percentage: 20`).
2. **Буферная очередь экспортера (`queue`):**
   - Настраивает локальную очередь в памяти: `queue_size` (количество батчей) и `num_consumers` (число параллельных горутин отправки).
   - Если хранилище замедляет запись, очередь заполняется. При переполнении спаны сбрасываются, инкрементируя счетчик `otelcol_exporter_enqueue_failed_spans_total`.
   - Флаг `wait_for_result: true` синхронизирует подтверждение приема с фактом записи, гарантируя семантику At-least-once, но снижая пиковый RPS.
3. **Dead-Letter Queue через Connectors:**
   - Компонент `jaeger_storage_exporter` может объявляться в секции `connectors:`. В этом режиме спаны, которые база данных окончательно отклонила (например, нарушение схемы или фатальная ошибка), перенаправляются в отдельный выходной конвейер (например, запись на аварийный локальный диск или в файл).

---

### Архитектура подсистемы сэмплирования

Jaeger v2 поддерживает три архитектурных механизма сэмплирования:

1. **Head-based Sampling (на клиенте):**
   - Решение о сохранении спана принимается SDK приложения в момент создания корневого спана.
   - Расширение `remote_sampling` выступает сервером конфигураций: SDK периодически запрашивает стратегии по HTTP (порт 5778 или 4318) / gRPC (порт 4317).
2. **Adaptive Sampling Engine:**
   - Процессор `adaptive_sampling` в конвейере коллектора подсчитывает входящий RPS по каждой паре `(сервис, операция)`.
   - Алгоритм динамически пересчитывает вероятность выборки (от 0.0 до 1.0) для каждого эндпоинта, стремясь к заданному лимиту (например, не более 5 трейсов в секунду на операцию).
   - Вычисленные вероятности сохраняются в общее состояние и раздаются расширением `remote_sampling` клиентам SDK.
3. **Tail-based Sampling (на коллекторе):**
   - Процессор `tailsampling` задерживает все спаны трейса в памяти на интервал `decision_wait` (например, 5–10 секунд).
   - После сбора полного графа трейса процессор анализирует его атрибуты: если в трейсе есть спаны со статусом `Error` или длительностью выше SLA, трейс сохраняется; успешные рутинные трейсы отбрасываются.
   - *Архитектурное ограничение:* требует маршрутизации всех спанов одного `trace_id` на один и тот же инстанс коллектора (Trace ID aware routing / Load-balancing exporter).

---

### Сетевая архитектура и порты Jaeger v2

| Порт | Протокол | Сервис / Компонент | Назначение в архитектуре |
| :--- | :--- | :--- | :--- |
| **4317** | TCP (gRPC) | OTLP Receiver | Основной порт приема спанов от OpenTelemetry SDK и Edge-агентов |
| **4318** | TCP (HTTP) | OTLP Receiver | Прием спанов по OTLP/HTTP (Protobuf/JSON), web-клиенты, serverless |
| **16686** | TCP (HTTP) | `jaeger_query` Extension | Веб-интерфейс Jaeger UI и HTTP API поиска трасс |
| **16685** | TCP (gRPC) | `jaeger_query` Extension | Высокопроизводительный gRPC API чтения данных (для интеграций) |
| **8888** | TCP (HTTP) | Internal Telemetry | Метрики состояния самого процесса Jaeger в формате Prometheus (`/metrics`) |
| **13133** | TCP (HTTP) | `healthcheckv2` Extension | Проверка готовности и жизнеспособности процесса (Liveness/Readiness probes) |
| **1777** | TCP (HTTP) | `pprof` Extension | Профилирование производительности Go runtime (`/debug/pprof`) |
| **55679** | TCP (HTTP) | `zpages` Extension | Диагностические HTML-страницы состояния конвейеров (`/debug/tracez`) |
| **14250** | TCP (gRPC) | Legacy Receiver | Прием данных от устаревших агентов Jaeger v1 (обратная совместимость) |
| **14268** | TCP (HTTP) | Legacy Receiver | Прием данных в формате Jaeger Thrift напрямую от старых клиентов |
| **9411** | TCP (HTTP) | Zipkin Receiver | Прием трассировок от сервисов с библиотеками Zipkin v1/v2 |
| **6831** | UDP | Legacy Receiver | Прием компактного Thrift по UDP от устаревших клиентов v1 |
| **5778** | TCP (HTTP) | `remote_sampling` | Раздача конфигураций сэмплирования клиентам v1 |

---

### Граничные условия и ограничения архитектуры

- **In-Memory хранилище:** Допустимо только для All-in-one режима и тестирования. При перезапуске процесса или ротации контейнера данные безвозвратно теряются.
- **Встраиваемый Badger:** Ограничен одним узлом (Single Node), не поддерживает кластеризацию и горизонтальное масштабирование. Подходит для локальных стендов или объемов до 1 млн спанов в сутки.
- **Высокая кардинальность атрибутов (Cardinality Explosion):** Передача уникальных идентификаторов (`user_id`, `jwt_token`, `query_hash`) в тегах спанов без предварительной нормализации приводит к исчерпанию памяти в ClickHouse и неконтролируемому разрастанию индексов в Elasticsearch.
- **Потеря данных при жестком завершении (`SIGKILL`):** Спаны, находящиеся в оперативной памяти `batch` процессора и очереди экспортера `queue`, не сбрасываются на диск при аварийной остановке процесса. Для корректной остановки требуется передача сигнала `SIGTERM` с паузой на graceful shutdown (по умолчанию 15–30 секунд).
- **Отсутствие кэширования в Query:** `jaeger_query` не имеет встроенного L2-кэша ответов. Повторные тяжелые запросы из UI или Grafana транслируются напрямую в ClickHouse/Elasticsearch.

---

## Практические сценарии

### Подготовка окружения

Минимальные системные требования для запуска компонентов Jaeger v2 на Linux (on-premise / bare-metal / VM):

```bash
# 1. Проверка доступности памяти и ядер процессора
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           15Gi       1.2Gi        12Gi       1.0Mi       2.3Gi        14Gi

nproc
# → 8

# 2. Проверка открытых портов (убедиться, что 4317, 4318, 16686 свободны)
ss -tulpn | grep -E ':(4317|4318|16686|8888|13133)'
# → (вывод должен быть пуст)
```

---

### Сценарий 1: Production архитектура Collector с ClickHouse и защитой по памяти

**Контекст:** Настройка высокопроизводительного коллектора для приема спанов по OTLP, буферизации, защиты от OOM и надежной записи в кластер ClickHouse.

Создание конфигурационного файла:

```yaml
# /etc/jaeger/collector-clickhouse.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"
        max_concurrent_streams: 1024
      http:
        endpoint: "0.0.0.0:4318"

processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 2048
    timeout: 2s
    send_batch_max_size: 4096

extensions:
  healthcheckv2:
    endpoint: "0.0.0.0:13133"
  jaeger_storage:
    backends:
      prod_clickhouse:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
          username: "default"
          password: ""
          connection_params:
            dial_timeout: "5s"
            compress: "lz4"

exporters:
  jaeger_storage_exporter:
    trace_storage: prod_clickhouse
    queue:
      num_consumers: 16
      queue_size: 1000
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 10s
      max_elapsed_time: 30s

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      level: detailed
      readers:
        - pull:
            exporter:
              prometheus:
                host: "0.0.0.0"
                port: 8888
    logs:
      level: info
```

**Запуск процесса с переменными окружения Go:**

```bash
# Экспорт лимитов памяти Go Runtime (например, для ноды с 8GB RAM выделяем 6800MiB)
export GOMEMLIMIT=6800MiB
export GOGC=100

# Запуск Jaeger v2 бинарника
jaeger --config /etc/jaeger/collector-clickhouse.yaml
# → 2026-10-12T13:30:00.000Z info service@v0.110.0/service.go:175 Everything is ready. Begin running and processing data.
```

**Валидация работы архитектурного конвейера:**

```bash
# 1. Проверка состояния Liveness через healthcheckv2
curl -i http://localhost:13133/
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → {"status":"Server available"}

# 2. Проверка метрик загрузки очередей и лимитов памяти в Prometheus
curl -s http://localhost:8888/metrics | grep -E 'otelcol_processor_memory_limiter|otelcol_exporter_queue'
# → otelcol_processor_memory_limiter_current_usage_mib 124.5
# → otelcol_processor_memory_limiter_refused_spans_total 0
# → otelcol_exporter_queue_size{exporter="jaeger_storage_exporter"} 0
```

---

### Сценарий 2: Потоковая Decoupled-архитектура через Kafka

**Контекст:** Разделение контура приема спанов и контура дисковой записи через персистентную очередь Kafka для сглаживания пиковых нагрузок и предотвращения потерь при деградации базы данных.

**1. Конфигурация Collector (Producer):**

```yaml
# /etc/jaeger/collector-kafka.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 85
    spike_limit_percentage: 15
  batch:
    send_batch_size: 4096
    timeout: 1s

exporters:
  kafka:
    brokers: ["192.168.10.11:9092", "192.168.10.12:9092", "192.168.10.13:9092"]
    topic: "jaeger-spans-v2"
    protocol_version: "2.8.0"
    encoding: "otlp_proto"
    compression: "lz4"
    producer:
      max_message_bytes: 4194304
      required_acks: 1

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [kafka]
```

**2. Конфигурация Ingester (Consumer):**

```yaml
# /etc/jaeger/ingester-storage.yaml
receivers:
  kafka:
    brokers: ["192.168.10.11:9092", "192.168.10.12:9092", "192.168.10.13:9092"]
    topic: "jaeger-spans-v2"
    protocol_version: "2.8.0"
    encoding: "otlp_proto"
    group_id: "jaeger-ingester-group"
    client_id: "jaeger-ingester-01"

processors:
  batch:
    send_batch_size: 8192
    timeout: 3s

extensions:
  jaeger_storage:
    backends:
      clickhouse_backend:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_backend
    queue:
      num_consumers: 32
      queue_size: 2000

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [kafka]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация задержек и отставания Ingester:**

```bash
# Проверка лага консьюмер-группы в Kafka
kafka-consumer-groups.sh --bootstrap-server 192.168.10.11:9092 --describe --group jaeger-ingester-group
# → GROUP                 TOPIC            PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# → jaeger-ingester-group jaeger-spans-v2  0          1048590         1048600         10
# → jaeger-ingester-group jaeger-spans-v2  1          1029401         1029402         1
```

---

### Сценарий 3: Выделенный узел чтения (Query Service) с UI и коррекцией Clock Skew

**Контекст:** Развертывание отдельного независимого узла Jaeger v2 для обслуживания веб-интерфейса инженеров и Grafana Data Source без приема входящих спанов.

```yaml
# /etc/jaeger/query-service.yaml
receivers:
  nop:

processors:

exporters:
  nop:

extensions:
  healthcheckv2:
    endpoint: "0.0.0.0:13133"
  jaeger_storage:
    backends:
      clickhouse_read:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
  jaeger_query:
    storage:
      traces: clickhouse_read
    base_path: "/jaeger"
    max_clock_skew_adjust: "10s"
    ui:
      config_file: "/etc/jaeger/ui-config.json"
      log_access: true
    http:
      endpoint: "0.0.0.0:16686"
    grpc:
      endpoint: "0.0.0.0:16685"

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [nop]
      processors: []
      exporters: [nop]
```

**Валидация интерфейса и API:**

```bash
# 1. Проверка доступности UI по сконфигурированному префиксу base_path
curl -I http://localhost:16686/jaeger/
# → HTTP/1.1 200 OK
# → Content-Type: text/html; charset=utf-8

# 2. Проверка Query REST API (получение списка зарегистрированных сервисов)
curl -s http://localhost:16686/jaeger/api/services | jq .
# → {
# →   "data": [
# →     "billing-service",
# →     "order-api",
# →     "payment-gateway"
# →   ],
# →   "total": 3,
# →   "limit": 0,
# →   "offset": 0,
# →   "errors": null
# → }
```

---

### Сценарий 4: Архитектура адаптивного сэмплирования (Adaptive Sampling)

**Контекст:** Автоматическая регуляция процента сохраняемых трасс для каждого эндпоинта инфраструктуры без ручной правки конфигураций приложений.

```yaml
# /etc/jaeger/collector-adaptive-sampling.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: "0.0.0.0:4317"

processors:
  adaptive_sampling:
    calculation_interval: 1m
    target_samples_per_second: 10
    initial_sampling_probability: 0.1
    min_sampling_probability: 0.001

  batch:
    send_batch_size: 1024
    timeout: 1s

extensions:
  jaeger_storage:
    backends:
      sampling_store:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
  remote_sampling:
    adaptive:
      sampling_store: sampling_store
      initial_sampling_probability: 0.1
    http:
      endpoint: "0.0.0.0:5778"
    grpc:
      endpoint: "0.0.0.0:14250"

exporters:
  jaeger_storage_exporter:
    trace_storage: sampling_store

service:
  extensions: [jaeger_storage, remote_sampling]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [adaptive_sampling, batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация отдачи стратегий сэмплирования клиентам SDK:**

```bash
# Опрос стратегий для сервиса "order-api" через HTTP эндпоинт remote_sampling
curl -s "http://localhost:5778/api/sampling?service=order-api" | jq .
# → {
# →   "strategyType": "PROBABILISTIC",
# →   "probabilisticSampling": {
# →     "samplingRate": 0.045
# →   },
# →   "operationSampling": {
# →     "defaultSamplingProbability": 0.01,
# →     "perOperationStrategies": [
# →       {
# →         "operation": "POST /v1/checkout",
# →         "probabilisticSampling": {
# →           "samplingRate": 0.25
# →         }
# →       }
# →     ]
# →   }
# → }
```

---

## Операции и команды системного администрирования

### Оптимизация ядра Linux (Sysctl) под высокую нагрузку на Collector

При приеме более 20,000 OTLP-запросов в секунду сетевой стек Linux по умолчанию отбрасывает входящие SYN-пакеты и исчерпывает сокеты.

```bash
# Применение оптимизаций сетевого стека в /etc/sysctl.d/99-jaeger-collector.conf
cat << 'EOF' | sudo tee /etc/sysctl.d/99-jaeger-collector.conf
# Увеличение длины очереди соединений сокета
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 16384

# Расширение пула локальных портов для исходящих соединений к ClickHouse/Kafka
net.ipv4.ip_local_port_range = 10240 65535

# Ускоренное освобождение закрытых TCP сокетов в TIME_WAIT
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1

# Увеличение размеров буферов приема/отправки сокетов (до 16MB)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
EOF

# Немедленное применение параметров
sudo sysctl -p /etc/sysctl.d/99-jaeger-collector.conf
# → net.core.somaxconn = 8192
# → net.ipv4.tcp_max_syn_backlog = 16384
# → net.ipv4.ip_local_port_range = 10240 65535
# → net.ipv4.tcp_fin_timeout = 15
# → net.ipv4.tcp_tw_reuse = 1
# → net.core.rmem_max = 16777216
# → net.core.wmem_max = 16777216
```

### Диагностика производительности через pprof

Если коллектор демонстрирует аномальное потребление CPU или задержки:

```bash
# Сбор профиля CPU в течение 30 секунд (требуется расширение pprof на порту 1777)
go tool pprof -top http://localhost:1777/debug/pprof/profile?seconds=30
# → Showing top 10 nodes out of 145
# →       flat  flat%   sum%        cum   cum%
# →      1.20s 25.10% 25.10%      1.20s 25.10%  runtime.cgocall
# →      0.80s 16.74% 41.84%      1.10s 23.01%  go.opentelemetry.io/collector/pdata/ptrace...
# →      0.45s  9.41% 51.26%      0.45s  9.41%  runtime.mallocgc

# Инспекция распределения памяти кучи (Heap allocations)
go tool pprof -top http://localhost:1777/debug/pprof/heap
```

---

## Типичные проблемы и устранение неполадок

| Симптом / Проблема | Архитектурная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Collector отбрасывает спаны (код 429 / ResourceExhausted)** | Сработал `memory_limiter`: использование RAM приблизилось к `limit_percentage` | `curl -s http://localhost:8888/metrics \| grep otelcol_processor_memory_limiter_refused_spans_total` | 1. Увеличить физическую память узла.<br>2. Проверить значение `GOMEMLIMIT`.<br>3. Увеличить `send_batch_size` и частоту сброса в бэкенд. |
| **Процесс завершается с кодом 137 (OOM-Killed)** | Лимит cgroup превышен до срабатывания `memory_limiter` и GC | `dmesg -T \| grep -i oom-killer` или `journalctl -u jaeger -e` | Задать `GOMEMLIMIT` на уровне 80% от лимита памяти cgroup и установить `spike_limit_percentage: 20` в конфигурации. |
| **Рост счетчика `otelcol_exporter_enqueue_failed_spans_total`** | Переполнена очередь `queue_size` из-за медленного бэкенда хранения | `curl -s http://localhost:8888/metrics \| grep otelcol_exporter_enqueue_failed` | 1. Увеличить `num_consumers` в `queue`.<br>2. Увеличить `queue_size`.<br>3. Проверить производительность дисков ClickHouse/Elasticsearch. |
| **Дочерние спаны отображаются левее родительских в UI** | Рассинхронизация часов (Clock Skew) между серверами приложений | Предупреждение `Clock Skew Adjustment` в деталях трейса в Jaeger UI | 1. Настроить службу синхронизации времени `chrony` на всех узлах.<br>2. Скорректировать параметр `max_clock_skew_adjust` в `jaeger_query`. |
| **Ошибка `too many open files` в логах коллектора** | Исчерпан лимит файловых дескрипторов процесса при наплыве OTLP TCP-соединений | `ulimit -n` или `ls /proc/$(pgrep jaeger)/fd \| wc -l` | Увеличить `LimitNOFILE=65536` в systemd unit файле сервиса `jaeger`. |
| **Пустой список сервисов в Jaeger UI (`/api/services`)** | Ошибка подключения `jaeger_query` к бэкенду или отсутствие записанных спанов | `curl -s http://localhost:16686/jaeger/api/services` возвращает `{"data":[]}` | Проверить параметры подключения в `jaeger_storage` и убедиться в наличии прав на чтение базы данных. |

---

## Рекомендации и лучшие практики

### 1. Изоляция ролей в архитектуре (Role Separation)
В высоконагруженных средах никогда не запускайте инстансы в роли `all-in-one`. Разделяйте инфраструктуру как минимум на два независимых пула:
- **Collector Pool:** Масштабируется горизонтально по CPU и сетевому трафику. Занимается только приемом и сбросом спанов.
- **Query Pool:** Размещается за балансировщиком нагрузки (Nginx/HAProxy) и масштабируется по числу аналитических запросов пользователей и Grafana. Деградация или тяжелый поисковый запрос в Query никогда не аффектит контур приема телеметрии.

### 2. Сбалансированная связка памяти (Memory Sizing Triangle)
Для предотвращения сбоев по памяти настраивайте три взаимосвязанных параметра:
1. **cgroup Memory Limit:** Жесткий лимит памяти контейнера или systemd unit (например, `8 GiB`).
2. **Go Runtime Limit:** Переменная `GOMEMLIMIT=6800MiB` (~83% от cgroup лимита).
3. **Memory Limiter Processor:**
   ```yaml
   processors:
     memory_limiter:
       check_interval: 500ms
       limit_percentage: 80
       spike_limit_percentage: 20
   ```

### 3. Буферизация через Kafka при пиковых нагрузках
Если пиковый трафик превышает 50,000 спанов/сек или время доступности дисковой подсистемы БД не гарантировано, включайте Streaming-архитектуру с Kafka:
- Топик Kafka должен иметь не менее 12–24 партиций для параллельной обработки.
- Ingester-ноды группируются в один `group_id` и масштабируются синхронно с числом партиций Kafka.

### 4. Graceful Shutdown
При обновлении конфигураций или перезапуске нод обеспечьте корректный останов процесса:
```ini
# /etc/systemd/system/jaeger.service
[Service]
KillSignal=SIGTERM
TimeoutStopSec=30s
ExecStop=/bin/kill -s SIGTERM $MAINPID
```
Это позволит воркерам `queue` сбросить накопленные спаны в базу данных до уничтожения процесса.

---

## Дополнительная информация

**Смежные материалы базы знаний:**
* Концепции распределенной трассировки и терминология: **[Обзор Jaeger](./jaeger_overview.md)**
* Развертывание в виде systemd-сервисов и контейнеров: **[Варианты развертывания](./jaeger_deployment_options.md)**
* Детальная конфигурация бэкендов хранения (ClickHouse, Elasticsearch): **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* Тонкая настройка сетевых протоколов OTLP и буферов: **[OTLP Configuration](./jaeger_otlp_configuration.md)**
* Спецификация HTTP и gRPC интерфейсов чтения: **[Query API Jaeger](./jaeger_query_api.md)**
* Расчет вычислительных ресурсов и сайзинг: **[Capacity Planning](./jaeger_capacity_planning.md)**
* Отказоустойчивость и кластеризация компонентов: **[High Availability и DR](./jaeger_high_availability.md)**
* Анализ задержек и настройка Tail-based сэмплирования: **[Анализ производительности](./jaeger_performance_analysis.md)**
* Защита сетевых соединений (mTLS) и изоляция: **[Security Hardening](./jaeger_security_hardening.md)**
* Развертывание в локальных кластерах Kubernetes: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Пошаговая миграция с устаревшей версии: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**

**Официальные технические ресурсы:**
* [Официальная архитектурная документация Jaeger v2](https://www.jaegertracing.io/docs/latest/architecture/)
* [Спецификация конфигурации Jaeger v2](https://www.jaegertracing.io/docs/latest/deployment/configuration/)
* [Репозиторий проекта Jaeger Tracing](https://github.com/jaegertracing/jaeger)
