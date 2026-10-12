# Capacity Planning для Jaeger

**Актуально для:** Jaeger v2.x

**Capacity Planning для Jaeger** — это процесс инженерного расчета требуемых вычислительных ресурсов (CPU, RAM, дисковая подсистема, IOPS, пропускная способность сети) и проектирования архитектуры хранения под заданный объем телеметрии. От корректности sizing зависит устойчивость приема трейсов под пиковыми нагрузками, задержки при поиске в UI, стабильность демонов при backpressure и общая эффективность использования on-premise серверного оборудования.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.  
Архитектура и потоки данных: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Развертывание компонентов: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.  
Глубокий анализ подсистем хранения: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Spans per second (spans/s)** | Интенсивность потока спанов, поступающих от сервисов в Collector в секунду. Базовая расчетная единица нагрузки |
| **Span Footprint** | Средний размер одного спана в сериализованном (OTLP/Protobuf) и декодированном виде в памяти и на диске |
| **Retention Period** | Срок хранения трейсов в базе данных (например, 7, 14 или 30 дней) до удаления по TTL или ротации |
| **Ingestion Throughput** | Пропускная способность конвейера: объем данных в МБ/с и спанов/с, который Collector и база данных способны стабильно принять и записать |
| **Write Amplification (WA)** | Коэффициент усиления записи на диск при фоновых слияниях данных (LSM-деревья в Elasticsearch, MergeTree в ClickHouse) |
| **High Cardinality** | Большое количество уникальных значений в атрибутах спанов (`user_id`, `order_uuid`), приводящее к разрастанию индексов и деградации памяти |
| **Head-based Sampling** | Принятие решения о сэмплировании спана в момент его создания в SDK приложения (фиксированный процент или rate limiting) |
| **Tail-based Sampling** | Принятие решения о сохранении или отбрасывании трейса на уровне Collector после сбора всех его спанов (по ошибкам или длительности) |
| **Backpressure** | Механизм защиты конвейера при исчерпании емкости очереди или памяти, возвращающий вызывающей стороне ошибку перегрузки (`ResourceExhausted`) |
| **Memory Limiter** | Процессор OTel/Jaeger v2, защищающий процесс от аварийной остановки (OOM) с помощью упреждающего сброса данных при достижении порогов RAM |

---

## Базовые концепции и архитектура сайзинга

### 1. Анатомия спана и профилирование размера

Размер спана в распределенной трассировке не является фиксированной величиной. Он варьируется от 300 байт до 10+ КБ в зависимости от плотности контекста:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Структура спана (Span Payload)                  │
├───────────────────────────────────┬────────────────────────────────────┤
│ Базовый заголовок (~100–150 B)    │ TraceID (16 B), SpanID (8 B),      │
│                                   │ ParentSpanID (8 B), Timestamps,    │
│                                   │ Operation Name, SpanKind, Flags    │
├───────────────────────────────────┼────────────────────────────────────┤
│ Атрибуты ресурса (~150–400 B)     │ service.name, host.name, k8s.*,    │
│ (Resource Attributes)             │ telemetry.sdk.*, deployment.env    │
├───────────────────────────────────┼────────────────────────────────────┤
│ Атрибуты спана (~200–2000 B)      │ http.target, db.statement,         │
│ (Span Attributes)                 │ error, custom tags                 │
├───────────────────────────────────┼────────────────────────────────────┤
│ События спана (~100–5000+ B)      │ Exception stack traces, logs,      │
│ (Span Events / Logs)              │ network message timestamps         │
└───────────────────────────────────┴────────────────────────────────────┘
```

**Категории профилей спанов:**
- **Минимальный (Lightweight):** 400–600 байт. Внутренние вызовы микросервисов, gRPC-методы с базовыми тегами.
- **Средний типовой (Standard Enterprise):** 1 000–1 500 байт. HTTP/REST спаны, включающие стандартные семантические конвенции OpenTelemetry и метаданные оркестратора.
- **Тяжелый (Heavy):** 2 500–8 000+ байт. Запросы к базам данных с телом SQL-запроса (`db.statement`), спаны с перехваченными stack trace исключений или спаны сообщений брокеров.

---

### 2. Математическая модель расчета емкости хранилища

Емкость дисковой подсистемы рассчитывается исходя из входящего спан-рейта, длительности хранения и коэффициента сжатия целевой СУБД:

```
V_raw (GB/день) = (spans_per_sec × 86 400 × avg_span_size_bytes) / 1024^3
V_disk (GB) = V_raw × retention_days × storage_factor × replication_factor × headroom
```

Где:
- `spans_per_sec` — средний или пиковый поток спанов в секунду.
- `86 400` — количество секунд в сутках.
- `avg_span_size_bytes` — средний размер сырого спана (типовое значение: `1 000`–`1 200` байт).
- `storage_factor` — коэффициент дискового представления по отношению к сырому JSON/Protobuf:
  - **ClickHouse (MergeTree с LZ4/ZSTD):** `0.18`–`0.28` (сжатие в 3.5×–5.5× благодаря колоночной структуре).
  - **Elasticsearch / OpenSearch:** `1.15`–`1.40` (инвертированные индексы, `_source` и doc_values создают накладные расходы).
- `replication_factor` — кратность репликации (`1` для одиночных нод, `2` для ReplicatedMergeTree / Primary+Replica ES).
- `headroom` — инженерный запас емкости под фоновые слияния (part merges / Lucene segment merges), временные таблицы и пиковые скачки (рекомендуется `1.30`–`1.40`, то есть 30–40%).

#### Сравнительная таблица емкости для 10 000 spans/s (retention 14 дней)

| Параметр | ClickHouse (Bare-Metal) | Elasticsearch (Bare-Metal) |
| :--- | :--- | :--- |
| **Сырой объем данных за сутки** | ~1 004 ГБ/день | ~1 004 ГБ/день |
| **Коэффициент дискового сжатия** | `0.22` (колонки + ZSTD) | `1.25` (индексы + `_source`) |
| **Коэффициент репликации (RF)** | 2 (ReplicatedMergeTree) | 2 (1 Primary + 1 Replica) |
| **Чистый объем данных за 14 дней** | 6 184 ГБ (~6.04 ТБ) | 35 140 ГБ (~34.3 ТБ) |
| **Запас под merges и ОС (+35%)** | **~8.15 ТБ NVMe** | **~46.3 ТБ SSD/NVMe** |
| **Суточная нагрузка записи на СУБД** | 441 ГБ/день (с учетом RF) | 2 510 ГБ/день (с учетом RF) |

---

### 3. Модель сайзинга вычислительных ресурсов Collector

Jaeger v2 функционирует на ядре OpenTelemetry Collector. Ресурсы масштабируются горизонтально в зависимости от интенсивности десериализации, работы процессоров и буферизации очередей экспортеров.

| Ресурс | Формула расчета | Инженерное обоснование |
| :--- | :--- | :--- |
| **CPU Cores** | `(spans_per_sec / 1 500) × cpu_overhead_factor` | Один поток CPU в Go обрабатывает 1 200–2 000 спанов/с при стандартном пайплайне (декодирование OTLP + батчинг). При активных regex-процессорах overhead_factor = 1.3–1.5 |
| **RAM (Базовый)** | `(spans_per_sec × avg_span_size × 2) + 512 МБ` | Память под буферы сокетов, внутренний heap и служебные структуры данных Go runtime |
| **RAM (с Батчингом)** | `RAM_base + (send_batch_size × workers × avg_span_size)` | Память, удерживаемая `batch` процессором до момента сброса пачки в exporter |
| **Сеть (Входящая)** | `(spans_per_sec × avg_span_size × 8) / 1 000 000` (Mbps) | Пропускная способность OTLP gRPC/HTTP без учета сжатия (со сжатием gzip/zstd трафик снижается на 60–75%) |

```
                       ┌───────────────────────────────┐
                       │   OTLP Ingestion (Network)    │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   memory_limiter processor    │ <── GOMEMLIMIT (80%)
                       │   (Early drop при перегрузке) │
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │       batch processor         │ <── send_batch_size
                       │   (Буфер накопления пачки)    │     timeout: 1s-2s
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │   sending_queue (Exporter)    │ <── queue_size
                       │   (In-memory ring buffer)     │     num_consumers
                       └───────────────┬───────────────┘
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │    Storage Backend / Kafka    │
                       └───────────────────────────────┘
```

---

### 4. Влияние стратегий сэмплирования на емкость

Выбор стратегии сэмплирования — фундаментальный инструмент контроля емкости инфраструктуры:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Сравнение влияния сэмплирования                      │
├─────────────────────┬───────────────────┬───────────────────────────────┤
│ Механизм            │ Точка применения  │ Влияние на инфраструктуру     │
├─────────────────────┼───────────────────┼───────────────────────────────┤
│ **Head Sampling**   │ SDK приложения    │ Снижает нагрузку на сеть,     │
│ (Adaptive/Probab.)  │                   │ Collector, СУБД на 90–99%     │
├─────────────────────┼───────────────────┼───────────────────────────────┤
│ **Tail Sampling**   │ OTel / Jaeger     │ Требует огромного объема RAM  │
│ (Trace completion)  │ Collector         │ на Collector для буферизации  │
└─────────────────────┴───────────────────┴───────────────────────────────┘
```

#### Расчет оперативной памяти под Tail-based Sampling

Если на уровне Collector включен `tail_sampling` процессор, коллектор обязан удерживать в памяти спаны всех активных трейсов до истечения интервала `decision_wait` (ожидание завершения трейса):

```
RAM_tail_sampling = spans_per_sec × avg_span_size × decision_wait_sec × trace_assembly_factor
```

Где `trace_assembly_factor` (типично `1.8`–`2.5`) отражает накладные расходы структур данных Go (мапы, слайсы, заголовки трейсов).

**Пример расчета:**
- Нагрузка: 20 000 spans/s
- Средний размер: 1 200 байт
- Окно ожидания трейса (`decision_wait`): 30 секунд
- `trace_assembly_factor`: 2.0

```
RAM = 20 000 × 1 200 × 30 × 2.0 = 1 440 000 000 байт ≈ 1.34 ГБ чистой памяти трейсов
```

С учетом запаса на неравномерность завершения трейсов, сборщик мусора Go и spike headroom, для 20 000 spans/s при 30-секундном окне tail sampling требуется резервировать **не менее 6–8 ГБ RAM** суммарно на кластер коллекторов только под данный процессор.

---

### 5. Буферизация и сглаживание пиков через Kafka

В системах с высокой вариативностью трафика между Collector и хранилищем размещается кластер Apache Kafka.

- **Сглаживание пиков (Traffic Smoothing):** Коллекторы быстро сбрасывают спаны в Kafka с минимальной задержкой. При недоступности или временном замедлении ClickHouse/Elasticsearch данные накапливаются в топике.
- **Расчет количества партиций:**
  ```
  Partitions = max(ceil(Peak_Throughput_MB_s / Single_Partition_Write_Limit_MB_s), Ingester_Workers)
  ```
  Для Kafka на NVMe запись в одну партицию составляет 10–25 МБ/с. При потоке 100 000 spans/s (~120 МБ/с) требуется минимум **8–12 партиций**.
- **Расчет диска Kafka под буфер:**
  ```
  Disk_Kafka = Ingestion_MB_s × buffer_retention_sec × replication_factor × 1.3
  ```
  Буфер на 24 часа при 50 МБ/с и RF=3 требует:
  `50 МБ/с × 86 400 с × 3 × 1.3 = 16 848 000 МБ ≈ 16.0 ТБ дискового пространства`.

---

## Практические сценарии

### Сценарий 1: Sizing для умеренной нагрузки (5 000 spans/s) на On-Premise инфраструктуре

**Исходные параметры:**
- Входящий поток: 5 000 spans/s
- Средний размер спана: 1 000 байт
- Срок хранения (Retention): 7 дней
- Среда развертывания: On-premise виртуальные машины под KVM / Proxmox или физические серверы
- Целевое хранилище: ClickHouse (RF=2 для отказоустойчивости)

**Расчет ресурсов:**
1. **Сетевой поток:**
   `5 000 × 1 000 × 8 = 40 Mbps` (входящий сырой трафик). Со сжатием OTLP gzip — около `12–15 Mbps`.
2. **Дисковое пространство ClickHouse:**
   - Сырой объем: `(5 000 × 86 400 × 1 000) / 1024^3 ≈ 402 ГБ/день`.
   - За 7 дней: `402 × 7 = 2 814 ГБ`.
   - Объем сжатых данных (коэффициент 0.22, RF=2): `2 814 × 0.22 × 2 ≈ 1 238 ГБ`.
   - С учетом запаса 35% под слияния частей: `1 238 × 1.35 ≈ 1 671 ГБ` (~1.65 ТБ).
3. **Вычислительные ресурсы коллекторов:**
   - Суммарно требуется: `5 000 / 1 500 ≈ 3.3 ядра CPU`.
   - Резервирование: 3 реплики по 2 vCPU и 4 ГБ RAM (схема N+1).

**Рекомендуемая конфигурация инфраструктуры:**

| Компонент | Количество узлов | Спецификация на узел | Суммарные ресурсы |
| :--- | :--- | :--- | :--- |
| **Jaeger v2 Collector** | 3 узла/пода | 2 vCPU, 4 ГБ RAM, 20 ГБ системный диск | 6 vCPU, 12 ГБ RAM |
| **Jaeger v2 Query** | 2 узла/пода | 2 vCPU, 4 ГБ RAM | 4 vCPU, 8 ГБ RAM |
| **ClickHouse Server** | 2 узла (1 шард × 2 реплики) | 8 CPU, 16 ГБ RAM, 2× 1.2 ТБ NVMe (RAID-1) | 16 CPU, 32 ГБ RAM, ~2.4 ТБ NVMe |
| **ClickHouse Keeper** | 3 узла (кворум) | 2 CPU, 4 ГБ RAM, 50 ГБ SSD | 6 CPU, 12 ГБ RAM |

**Рабочая конфигурация Collector под данный профиль (`collector.yaml`):**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_concurrent_streams: 1024
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 8192
    timeout: 1s
    send_batch_max_size: 16384

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse

extensions:
  jaeger_storage:
    backends:
      clickhouse:
        addresses:
          - "clickhouse-01.internal:9000"
          - "clickhouse-02.internal:9000"
        database: jaeger_v2
        username: jaeger
        password: "${CLICKHOUSE_PASSWORD}"

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      address: 0.0.0.0:8888
```

---

### Сценарий 2: Sizing для High-Load Enterprise (100 000 spans/s) на Bare-Metal кластере

**Исходные параметры:**
- Нагрузка: 100 000 spans/s постоянная, пики до 180 000 spans/s
- Средний размер спана: 1 200 байт
- Срок хранения: 14 дней
- Инфраструктура: Собственный ЦОД, выделенные физические серверы Supermicro/Dell, сеть 10/25 GbE
- Архитектура: Двухконтурная со сглаживающим буфером Apache Kafka и шардированным кластером ClickHouse

**Математический расчет:**
1. **Сетевой поток:**
   - Входящий поток в коллекторы: `100 000 × 1 200 × 8 = 960 Mbps` (~120 МБ/с).
   - В пике (180k spans/s): `1.73 Gbps` (~216 МБ/с).
   - Трафик репликации Kafka (RF=3): `120 МБ/с × 3 = 360 МБ/с` (требуются выделенные интерфейсы 10 GbE).
2. **Дисковое пространство ClickHouse:**
   - Сырой суточный объем: `(100 000 × 86 400 × 1 200) / 1024^3 = 9 655 ГБ/день` (~9.43 ТБ/день).
   - За 14 дней: `9.43 × 14 = 132 ТБ`.
   - В сжатом виде (коэффициент 0.22, RF=2): `132 × 0.22 × 2 = 58.08 ТБ`.
   - С запасом 35% под MergeTree и индексы: **~78.4 ТБ полезной емкости NVMe**.
3. **Kafka буфер (ретенция 24 часа на случай регламентных работ с БД):**
   - Сырой объем за 24 ч: `9.43 ТБ`.
   - Сжатие в Kafka продюсером (zstd): коэффициент ~0.45 → `4.24 ТБ`.
   - С учетом репликации (RF=3) и запаса: `4.24 × 3 × 1.3 ≈ 16.5 ТБ полезного дискового пространства`.

**Спецификация серверного парка:**

| Компонент | Кол-во серверов | Аппаратная конфигурация сервера | Роль в конвейере |
| :--- | :--- | :--- | :--- |
| **Ingestion Collector** | 8 серверов (или k8s pods) | 16 Cores (AMD EPYC / Intel Xeon), 32 ГБ RAM, 2× 25GbE | Прием OTLP от клиентов, базовый батчинг, запись в Kafka |
| **Kafka Cluster** | 5 серверов | 32 Cores, 128 ГБ RAM, 4× 3.84 ТБ NVMe U.2 (RAID-10), 2× 25GbE | Буферизация спанов, топик `jaeger-spans` на 24 партиции |
| **Ingester (Jaeger v2)** | 8 серверов | 16 Cores, 32 ГБ RAM, 2× 10GbE | Вычитывание из Kafka, подготовка колоночных пачек в ClickHouse |
| **ClickHouse Storage** | 6 серверов (3 шарда × 2 реплики) | 64 Cores, 256 ГБ RAM, 8× 3.84 ТБ NVMe (software RAID-0 / JBOD), 2× 25GbE | Хранение 80+ ТБ трейсов, параллельное выполнение поисковых запросов |
| **ClickHouse Keeper** | 3 сервера | 8 Cores, 16 ГБ RAM, 2× 480 ГБ SATA SSD (RAID-1) | Координация репликации метаданных |
| **Jaeger v2 Query** | 4 сервера за HAProxy | 16 Cores, 32 ГБ RAM, 2× 10GbE | Обработка поисковых запросов UI и дашбордов Grafana |

---

### Сценарий 3: Настройка защитных буферов памяти Collector

Чтобы коллектор Jaeger v2 гарантированно не завершался аварийно по OOM при пиковых скачках, необходимо согласовать переменные среды Go runtime и процессор `memory_limiter`.

**Принцип согласования порогов:**
Если контейнеру или процессу выделено 8 ГБ RAM:
- Установите переменную `GOMEMLIMIT=6800MiB` (85% от доступного лимита памяти).
- В `memory_limiter` установите `limit_percentage: 80` и `spike_limit_percentage: 20`.

```yaml
# Фрагмент конфигурации Jaeger v2 Collector
processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 10000
    timeout: 1s
    send_batch_max_size: 20000

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse
    sending_queue:
      enabled: true
      num_consumers: 16
      queue_size: 5000
```

---

### Сценарий 4: Оценка и предотвращение High Cardinality

**Проблема:** В спаны начали добавлять атрибут `http.request.header.authorization`, `db.query.parameters` или уникальный `user_uuid`.
**Влияние на ресурсы:**
1. **ClickHouse:** Уникальные значения в первичных ключах или вторичных индексах (`INDEX idx_user user_id TYPE minmax GRANULARITY 4`) вызывают экспоненциальный рост объема `.mrk` и `.idx` файлов. Слияния частей замедляются в 2–4 раза, вызывая ошибку `Too many parts`.
2. **Elasticsearch:** Раздувание инвертированного индекса приводит к исчерпанию JVM Old Gen Heap и зависанию GC на мастер- и дата-нодах.

**Инженерное решение в конвейере Jaeger v2:**
Применение процессора `attributes` или `transform` для удаления или нормализации атрибутов до записи в постоянное хранилище:

```yaml
processors:
  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          # Удаление персональных и высококардинальных атрибутов
          - delete_key(attributes, "user.auth_token")
          - delete_key(attributes, "raw.payload")
          # Маскирование UUID до общего шаблона
          - replace_pattern(attributes["http.target"], "/api/v1/orders/[0-9a-fA-F\\-]+", "/api/v1/orders/{order_id}")
```

---

### Сценарий 5: Мониторинг утилизации ресурсов и емкости в Prometheus

Для предотвращения потери трейсов и своевременного масштабирования узлов настраивается мониторинг очередей и утилизации:

**Ключевые PromQL-запросы:**

```promql
# 1. Входящий спан-рейт на коллекторах (spans/sec)
sum(rate(otelcol_receiver_accepted_spans_total[1m]))

# 2. Количество спанов, отброшенных из-за нехватки памяти (должно быть строго 0)
sum(rate(otelcol_processor_memory_limiter_refused_spans_total[1m]))

# 3. Доля переполнения внутренней очереди экспортера (0 - 100%)
(sum(otelcol_exporter_queue_size) / sum(otelcol_exporter_queue_capacity)) * 100

# 4. Ошибки сброса данных в хранилище (ClickHouse/ES write errors)
sum(rate(otelcol_exporter_send_failed_spans_total[1m]))

# 5. Степень заполнения дисковых массивов ClickHouse
100 - (node_filesystem_avail_bytes{mountpoint="/var/lib/clickhouse"} / node_filesystem_size_bytes{mountpoint="/var/lib/clickhouse"} * 100)
```

**Правила алертинга Prometheus (`alerts.yaml`):**

```yaml
groups:
  - name: jaeger_capacity_alerts
    rules:
      - alert: JaegerMemoryLimiterDroppingSpans
        expr: sum(rate(otelcol_processor_memory_limiter_refused_spans_total[2m])) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Jaeger Collector отбрасывает спаны по memory_limiter"
          description: "Текущий поток спанов превышает объем выделенной оперативной памяти. Требуется срочное масштабирование реплик Collector."

      - alert: JaegerExporterQueueSaturation
        expr: (sum(otelcol_exporter_queue_size) / sum(otelcol_exporter_queue_capacity)) > 0.80
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Очередь экспортера Jaeger заполнена более чем на 80%"
          description: "Хранилище (ClickHouse/Kafka) не успевает подтверждать запись данных. Возможно исчерпание IOPS."

      - alert: JaegerStorageDiskSpaceRunningLow
        expr: (100 - (node_filesystem_avail_bytes{mountpoint="/var/lib/clickhouse"} / node_filesystem_size_bytes{mountpoint="/var/lib/clickhouse"} * 100)) > 80
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Дисковое пространство хранилища Jaeger заполнено на >80%"
          description: "Осталось менее 20% свободного места на разделе /var/lib/clickhouse. Проверьте политики TTL и коэффициент сжатия."
```

---

## Операции и команды

Практические команды системного администратора для аудита емкости, нагрузки и дискового пространства компонентов трассировки.

### 1. Измерение входящего спан-рейта и утилизации буферов Collector

```bash
# Получение текущего статуса работы memory_limiter
curl -s http://127.0.0.1:8888/metrics | grep -E "otelcol_processor_memory_limiter"
# → otelcol_processor_memory_limiter_current_usage_mib 1845.2
# → otelcol_processor_memory_limiter_limit_mib 2048.0
# → otelcol_processor_memory_limiter_refused_spans_total 0

# Проверка наполнения очереди экспортера и сброса пачек
curl -s http://127.0.0.1:8888/metrics | grep -E "otelcol_exporter_queue"
# → otelcol_exporter_queue_capacity 5000
# → otelcol_exporter_queue_size 240
```

### 2. Аудит дисковой емкости и сжатия в ClickHouse

```bash
# Запуск проверки фактического размера таблиц и коэффициента компрессии
clickhouse-client --query "
SELECT
    table,
    formatReadableSize(sum(data_compressed_bytes)) AS compressed,
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed,
    round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 2) AS compression_ratio,
    sum(rows) AS total_spans
FROM system.parts
WHERE database = 'jaeger_v2' AND active
GROUP BY table;
"
# → spans           642.18 GiB   3.12 TiB   4.98   3412984501
# → spans_index      84.32 GiB   380.11 GiB 4.51   3412984501

# Проверка количества активных частей (parts) во избежание ошибки Too many parts
clickhouse-client --query "
SELECT count() AS active_parts, max(parts_per_partition) AS max_parts_in_partition
FROM (
    SELECT partition, count() AS parts_per_partition
    FROM system.parts
    WHERE database = 'jaeger_v2' AND table = 'spans' AND active
    GROUP BY partition
);
"
# → 48    12
```

### 3. Проверка емкости и шардов в Elasticsearch

Если в качестве бэкенда задействован Elasticsearch или OpenSearch:

```bash
# Оценка объема индексов трейсов и количества шардов
curl -s -X GET "http://127.0.0.1:9200/_cat/indices/jaeger-span-*?v&s=pri.store.size:desc&h=index,pri,rep,docs.count,pri.store.size,store.size"
# → index                     pri rep docs.count pri.store.size store.size
# → jaeger-span-2026-10-12      6   1  482019481        284.2gb    568.4gb
# → jaeger-span-2026-10-11      6   1  475102911        279.8gb    559.6gb

# Проверка заполнения очереди индексации (write thread pool)
curl -s -X GET "http://127.0.0.1:9200/_nodes/stats/thread_pool?filter_path=nodes.*.thread_pool.write" | jq '.nodes[].thread_pool.write | {active, queue, rejected}'
# → { "active": 16, "queue": 0, "rejected": 0 }
```

### 4. Проверка пропускной способности и лага в буфере Kafka

```bash
# Проверка лага группы консьюмеров ingester
kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 --describe --group jaeger-ingester
# → GROUP           TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID
# → jaeger-ingester jaeger-spans  0          18402910        18403100        190             ingester-pod-1
# → jaeger-ingester jaeger-spans  1          18399401        18399510        109             ingester-pod-2

# Проверка фактического дискового размера топика по брокерам
kafka-log-dirs.sh --bootstrap-server 127.0.0.1:9092 --describe --topic-list jaeger-spans
# → {"version":1,"brokers":[{"broker":1,"logDirs":[{"logDir":"/var/lib/kafka/data","error":null,"partitions":[{"partition":"jaeger-spans-0","size":148291048123,"offsetLag":0}]}]}]}
```

---

## Диагностика и устранение неисправностей

| Проблема / Симптом | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Коллектор отбрасывает спаны (код 429 / ResourceExhausted)** | Превышение лимита RAM, сработал `memory_limiter` | `curl 127.0.0.1:8888/metrics \| grep refused_spans` показывает рост счетчика | 1. Увеличить горизонтально количество реплик коллекторов.<br>2. Проверить значение `GOMEMLIMIT` и cgroup limits.<br>3. Увеличить частоту сброса `batch` процессора (`timeout: 500ms`). |
| **OOM-Killed (код 137) процесса Collector** | Лимит памяти cgroup достигнут быстрее, чем сработал `memory_limiter` | `dmesg -T \| grep -i oom-killer` или `kubectl describe pod` показывает `Exit Code 137` | 1. Установить `GOMEMLIMIT` на уровне 80–85% от физического лимита контейнера.<br>2. Уменьшить `send_batch_max_size` и размер `sending_queue`.<br>3. Выделить больше RAM процессу. |
| **ClickHouse: `DB::Exception: Too many parts in all data parts in table`** | Слишком частая вставка мелкими пачками (отсутствует батчинг на стороне коллектора) | Лог `/var/log/clickhouse-server/clickhouse-server.err.log` содержит ошибку `Too many parts` | 1. Увеличить `send_batch_size` в OTel Collector до 10 000–20 000.<br>2. Увеличить таймаут сброса пачки до 1–2 с.<br>3. При экстремальных пиках направлять спаны сначала в Kafka. |
| **Elasticsearch: `EsRejectedExecutionException`** | Переполнение очереди `write` пула потоков из-за нехватки дисковых IOPS | Логи Elasticsearch: `rejected execution of org.elasticsearch.action.bulk` | 1. Увеличить размер пачки bulk запросов.<br>2. Разнести primary и replica шарды на разные NVMe диски.<br>3. Настроить более редкий `index.refresh_interval: "30s"`. |
| **Диск заполняется быстрее расчетного времени** | Взрыв размера спанов из-за high cardinality или отключения сэмплирования | Запрос `formatReadableSize(sum(data_compressed_bytes))` в ClickHouse показывает резкий рост за последние 24 ч | 1. Проверить размер спанов через метрики или анализ выборки строк.<br>2. Внедрить фильтрацию и удаление тяжелых атрибутов процессором `transform`.<br>3. Снизить rate сэмплирования на клиентах. |
| **Постоянный рост Kafka Consumer Lag** | Пропускная способность записи в БД ниже скорости поступления спанов в очередь | `kafka-consumer-groups.sh` показывает непрерывно растущий `LAG` | 1. Добавить воркеров Ingester (до количества партиций топика).<br>2. Увеличить `batch.size` и параллелизм вставки в целевую СУБД.<br>3. Добавить шарды в кластер ClickHouse. |

---

## Лучшие практики

1. **Многоуровневый расчет запаса (Headroom):** Никогда не рассчитывайте дисковую подсистему "байт-в-байт". Для колоночных баз (ClickHouse) и поисковых систем (Elasticsearch) всегда закладывайте **минимум 35% свободного места** от общего объема диска. При заполнении хранилища выше 80% резко падает скорость слияний и возрастает риск аварийного перехода таблицы в Read-Only.
2. **Конфигурация батчинга — ключевой фактор производительности:** Единичные вставки спанов уничтожают дисковые подсистемы любых СУБД. Настраивайте размер пачки `send_batch_size` в диапазоне `8 192`–`16 384` спанов с таймаутом `1s`–`2s`.
3. **Строгая связка `GOMEMLIMIT` и `memory_limiter`:** В Jaeger v2 критически важно задавать переменную окружения `GOMEMLIMIT` на уровне 80–85% от доступной памяти хоста/контейнера совместно с `memory_limiter` процессором (`limit_percentage: 80`, `spike_limit_percentage: 20`). Это полностью устраняет непредвиденные аварии OOM-Killer.
4. **Отказ от дорогостоящих индексов по произвольным тегам:** Индексируйте только те атрибуты, по которым регулярно выполняется поиск оператором (`service.name`, `http.status_code`, `environment`). Не создавайте отдельные вторичные индексы под поля с потенциально бесконечным набором значений.
5. **Автоматизация очистки через партиционирование и TTL:** В ClickHouse настраивайте удаление старых трейсов на уровне схемы таблиц через декларативный `TTL start_time + INTERVAL 14 DAY DELETE`. В Elasticsearch применяйте автоматические политики ILM (Index Lifecycle Management) с удалением индексов по суточному ролловеру.
6. **Выбор накопителей enterprise-уровня:** Для высоконагруженных инсталляций трассировки (>10 000 spans/s) применяйте серверные NVMe накопители с высоким показателем DWPD (Drive Writes Per Day ≥ 1–3). Использование сетевых HDD/NFS хранилищ приводит к деградации и backpressure.

---

## Очистка тестового окружения

Команды удаления временных файлов, логов и тестовых стендов после проведения нагрузочного тестирования сайзинга:

```bash
# Удаление временных тестовых таблиц в ClickHouse
clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_v2_loadtest SYNC;"
# → OK

# Удаление временного тестового топика в Kafka
kafka-topics.sh --bootstrap-server 127.0.0.1:9092 --delete --topic jaeger-spans-test
# → Topic jaeger-spans-test is marked for deletion

# Очистка локальных временных данных процесса
rm -rf /tmp/jaeger-benchmarks/*
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**
- Архитектурное устройство компонентов Jaeger: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Варианты развертывания и топологии: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
- Подробный разбор механизмов баз данных: **[Storage Deep Dive для Jaeger](./jaeger_storage_deep_dive.md)**
- Настройка протокола OTLP и сетевого конвейера: **[OTLP конфигурация Jaeger](./jaeger_otlp_configuration.md)**
- Диагностика и профилирование производительности: **[Анализ производительности Jaeger](./jaeger_performance_analysis.md)**
- Отказоустойчивость и резервирование: **[High Availability и Disaster Recovery для Jaeger](./jaeger_high_availability.md)**
- Сайзинг и масштабирование кластера ClickHouse: **[ClickHouse: Capacity & Upgrades](../Databases/ClickHouse/clickhouse-capacity-upgrades.md)**
- Расчет емкости и шардирования Elasticsearch: **[Elasticsearch: Capacity Planning](../ELK_Stack/Elasticsearch/elasticsearch_capacity_planning.md)**
- Планирование емкости брокеров сообщений Kafka: **[Apache Kafka: Capacity Planning](../Kafka/kafka_capacity_dr.md)**

**Официальная документация:**
- [Jaeger Tracing Documentation — Architecture & Deployment](https://www.jaegertracing.io/docs/latest/)
- [OpenTelemetry Collector Performance and Sizing Guidelines](https://opentelemetry.io/docs/collector/scaling/)
- [ClickHouse Documentation — Sizing Hardware & MergeTree Engine](https://clickhouse.com/docs/en/operations/hardware)
