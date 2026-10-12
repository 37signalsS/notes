# Анализ производительности с помощью Jaeger

**Актуально для:** Jaeger v2.x

> **Статус:** Документация описывает архитектуру и методы глубокого анализа производительности в **Jaeger v2** (на базе кодовой базы OpenTelemetry Collector). Рассматриваются on-premise и bare-metal сценарии (Linux, systemd, Docker, self-hosted Kubernetes, ClickHouse, Prometheus) без использования проприетарных облачных платформ и без AI-компонентов.

**Анализ производительности в Jaeger** — это комплексный процесс выявления узких мест (bottlenecks), локализации задержек на критическом пути и диагностики сложных распределенных деградаций с использованием трассировки. В Jaeger v2 переход на нативную модель данных OpenTelemetry и унифицированную архитектуру конвейеров позволяет инженерам DevOps, SRE и системным администраторам решать задачи профилирования микросервисов, вычисления RED-метрик (Rate, Errors, Duration) без модификации кода приложений и связывать высокоуровневые SLO с конкретными строками выполнения запросов.

---

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **Timeline (Gantt Chart)** | Каскадная временная диаграмма в Jaeger UI, отображающая иерархию, моменты старта и длительность всех спанов трассы |
| **Критический путь (Critical Path)** | Непрерывная цепь последовательных зависимых операций в DAG трассы, суммарная длительность которой определяет конечное время ответа запроса. Оптимизация операций вне критического пути не уменьшает latency для клиента |
| **Self-Time (Собственное время)** | Время выполнения спана за вычетом времени ожидания дочерних вызовов (`Self-Time = Duration - Sum(Children Duration)` с учетом наложений). Отражает реальную работу на CPU, обработку в памяти или ожидание неинструментированного ресурса |
| **Child-Time (Время дочерних вызовов)** | Время, затраченное внешними зависимостями (базами данных, сторонними микросервисами, кэшами), вызванными текущим спаном |
| **Паттерн N+1** | Архитектурный антипаттерн, при котором сервис выполняет множество мелких последовательных запросов к БД или RPC вместо одного батч-вызова |
| **Fan-out Cascade** | Паттерн параллельного или псевдопараллельного разветвления одного запроса на десятки/сотни подзапросов, способный приводить к насыщению пулов соединений и thread pool starvation |
| **Tail Latency (Задержка хвоста)** | Задержка запросов на верхних перцентилях распределения (p95, p99, p99.9), отражающая опыт наименее удачливых пользователей и являющаяся главным фокусом SRE |
| **Service Performance Monitoring (SPM)** | Мониторинг производительности сервисов на основе трассировки путем непрерывного вычисления агрегированных метрик RED из спанов |
| **RED-метрики** | Методология мониторинга сервисов: **Rate** (частота запросов/с), **Errors** (доля ошибочных запросов), **Duration** (распределение задержки по перцентилям) |
| **Exemplars** | Механизм OpenMetrics/Prometheus, связывающий точку на графике метрики или корзину гистограммы с конкретным `trace_id` для быстрого перехода к трейсу |
| **Span Links** | Отношения между спанами, не являющиеся родительскими (родитель-потомок). Применяются для асинхронных контуров (Kafka, RabbitMQ), пакетной обработки и связывания отложенных задач |
| **Trace Comparison (Trace Diff)** | Визуальное и структурное сопоставление двух трейсов в Jaeger UI для выявления деградаций между версиями сервиса или между быстрым и медленным запросом |
| **Tail-based Sampling** | Метод сэмплирования, при котором решение о сохранении трассы принимается после ее полного завершения на основе анализа итогового статуса (ошибка) или длительности (превышение порога) |
| **Head-based Sampling** | Принятие решения о сэмплировании в момент старта корневого спана без знания о будущей длительности или возникновении сбоя |
| **Backpressure** | Состояние перегрузки буферов коллектора или сетевых очередей, при котором коллектор вынужден отбрасывать спаны или сигнализировать агентам об ограничении скорости |
| **Memory Limiter** | Процессор OTel Collector (`memory_limiter`), защищающий коллектор от аварийного завершения по Out-Of-Memory (OOM) путем контролируемого сброса данных при приближении к лимиту RAM |

---

## 2. Базовые концепции и архитектура анализа

### 2.1 Анатомия распределенного трейса и разбивка времени

Каждый трейс в Jaeger v2 представляет собой направленный ациклический граф (DAG), состоящий из спанов:

```
[Client / Ingress: Total Latency 450ms]
│
├── [Service A (API Gateway): 50ms self-time]
│   │
│   ├── [Service B (Auth): 80ms] ──> [Redis: 15ms]
│   │
│   └── [Service C (Order Processor): 320ms]
│       ├── [PostgreSQL (SELECT users): 30ms]
│       ├── [Service D (Payment RPC): 220ms] (CRITICAL PATH)
│       │   └── [Payment Gateway HTTP: 210ms] (CRITICAL PATH)
│       └── [Kafka (Produce order.created): 10ms] (Span Link)
```

Временная структура спана раскладывается на три составляющие:
1. **Queuing Delay (Задержка очереди):** Время между моментом отправки запроса клиентом и моментом, когда рабочий поток сервиса-получателя начал его обработку. Выявляется разницей временных меток между спаном `SpanKind.CLIENT` и спаном `SpanKind.SERVER`.
2. **Execution Time (Время непосредственной работы / Self-Time):** Время, когда код сервиса производит локальные вычисления, парсинг JSON, рендеринг или ожидает локальные блокировки (мьютексы, I/O).
3. **Downstream Waiting Time (Время ожидания зависимостей):** Время от отправки вызова дочернему сервису до получения ответа.

### 2.2 Алгоритм определения критического пути

**Критический путь** — это цепь непараллельных спанов, определяющая общую продолжительность запроса.
* Если родительский спан запускает две параллельные операции: `Op1` (длительность 200 мс) и `Op2` (длительность 50 мс), то в критический путь входит исключительно `Op1`.
* Оптимизация `Op2` с 50 мс до 10 мс **не уменьшит** время ответа запроса ни на одну миллисекунду (Закон Амдала).
* В Jaeger UI критический путь визуализируется непрерывной линией спанов, примыкающих друг к другу по времени завершения.

```
+-------------------------------------------------------+ Root Span (400ms)
|   +-----------------------+ Op1 (250ms) [CRITICAL]    |
|   |                       |                           |
|   +-------+ Op2 (80ms)    |                           |
|                           +-----------------------+ Op3 (150ms) [CRITICAL]
+-------------------------------------------------------+
```

### 2.3 Архитектурные антипаттерны распределенной производительности

1. **Паттерн N+1:**
   - **Симптом в Jaeger UI:** Сервис выполняет сотни последовательных спанов типа `db.system` или `http.method` к одной и той же внешней системе. Временная шкала выглядит как частый «забор» из коротких блоков.
   - **Причина:** Использование ORM (lazy loading сущностей в цикле) или отсутствие пакетных методов в сервисах.
   - **Влияние:** Накладные расходы на сетевой round-trip (RTT) и переключение контекста превышают полезное время выполнения в десятки раз.

2. **Fan-out Cascade и истощение пулов (Connection Pool Starvation):**
   - **Симптом:** Корневой спан инициирует 50+ параллельных вызовов, но первые 10 выполняются быстро, а последующие спаны имеют длительную задержку старта или падают по таймауту.
   - **Причина:** Исчерпание размера HTTP Connection Pool или DB Connection Pool. Потоки приложения блокируются в ожидании свободного сокета.

3. **Скрытые паузы сборщика мусора (GC Stop-The-World) и Lock Contention:**
   - **Симптом:** Спан имеет высокий `Self-Time` (например, 2 секунды), но не имеет дочерних спанов, а профилировщик CPU не фиксирует полезной нагрузки.
   - **Причина:** JVM/Go GC пауза, ожидание освобождения мьютекса (`pthread_mutex_lock`, `sync.Mutex`), ожидание дискового I/O или `fsync` в синхронном вызове.

4. **Асинхронные задержки очередей (Queue Lag):**
   - **Симптом:** Спан `Producer` завершился за 2 мс, но связанный через `Span Link` спан `Consumer` стартовал спустя 45 секунд.
   - **Причина:** Накопление очереди сообщений в Kafka/RabbitMQ из-за недостаточного количества партиций или медленной работы консьюмеров.

### 2.4 Service Performance Monitoring (SPM) и RED-метрики в Jaeger v2

В архитектуре Jaeger v2 генерация RED-метрик вынесена на уровень конвейера OpenTelemetry Collector через коннектор `spanmetrics` (`spanmetricsconnector`):

```
[OTLP Receiver] 
       │ (traces)
       ▼
 [Batch Processor]
       │ (traces)
       ├────────────────────────────────────────┐
       ▼ (traces)                               ▼ (traces)
[jaeger_storage_exporter]              [spanmetrics connector]
       │                                        │ (metrics)
       ▼ (ClickHouse: jaeger_v2.spans)          ▼
                                        [Prometheus Exporter] ──> [Prometheus Server]
```

1. **Rate (Частота):** Счетчик `calls_total` (или `traces_spanmetrics_calls_total`), инкрементируемый при каждом завершении спана, сгруппированный по `service_name`, `span_name` и статусу.
2. **Errors (Ошибки):** Фильтрация счетчика `calls_total` с признаком `status_code="STATUS_CODE_ERROR"`.
3. **Duration (Длительность):** Гистограмма `duration_bucket` с экспоненциальными или явными границами интервалов для расчета процентилей p50, p90, p99.

### 2.5 Математика Tail Latency в микросервисах

В монолитной архитектуре запрос зависит от одного процесса. В распределенной микросервисной топологии один входящий запрос пользователя часто вызывает цепочку из $N$ микросервисных вызовов.
Если система состоит из $N = 30$ независимых подзапросов, и каждый сервис имеет $p99 = 1\%$ вероятности деградации, то общая вероятность того, что пользователь столкнется с задержкой уровня p99, вычисляется по формуле:

$$P(\text{задержка}) = 1 - (1 - 0.01)^{30} = 1 - (0.99)^{30} \approx 1 - 0.7397 = 26.03\%$$

Для $N = 50$ сервисов вероятность деградации вырастает до **39.5%**. Это явление называется **Tail Latency Amplification**. Классические средние значения (mean / average) полностью маскируют эту проблему, поэтому анализ трассировок строится исключительно вокруг перцентилей p95, p99 и p99.9.

### 2.6 Ресурсные требования узлов анализа Jaeger v2

| Компонент | Рекомендуемые ресурсы (10k спанов/сек) | Рекомендуемые ресурсы (50k спанов/сек) | Замечания архитектора |
| :--- | :--- | :--- | :--- |
| **Jaeger v2 Collector** | 4 ядра CPU, 8 GB RAM | 16 ядер CPU, 32 GB RAM | Буферизация памяти критична при включении `tail_sampling` |
| **ClickHouse Server** | 8 ядер CPU, 32 GB RAM, NVMe | 32 ядра CPU, 128 GB RAM, NVMe RAID10 | Движок MergeTree; компрессия ZSTD; TTL партиций |
| **Prometheus Server** | 4 ядра CPU, 16 GB RAM | 8 ядер CPU, 32 GB RAM | Хранение метрик `spanmetrics` (контроль кардинальности тегов) |
| **Jaeger Query Service** | 2 ядра CPU, 4 GB RAM | 8 ядер CPU, 16 GB RAM | Статeless-компонент, легко масштабируется горизонтально за LB |

### 2.7 Критический порядок процессоров в конвейере Jaeger v2 (Pipeline Guardrails)

Порядок следования процессоров в конфигурационном блоке `pipelines.traces.processors` является строго детерминированным. Нарушение порядка приводит к аварийным завершениям коллектора по OOM, утечкам конфиденциальных данных и ложным срабатываниям фильтров:

```text
[Receivers] 
     │
     ▼
┌──────────────────────────────┐
│ 1. memory_limiter            │ ──► СТРОГО ПЕРВЫМ: защита от OOM до любых аллокаций
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 2. k8sattributes / resourcedet│ ──► Обогащение спанов метаданными пода/ноды
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 3. transform (OTTL)          │ ──► Маскирование PII до попадания в буферы и сэмплирование
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 4. tail_sampling             │ ──► Принятие решений над полным графом до батчинга
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ 5. batch                     │ ──► СТРОГО ПОСЛЕДНИМ ПЕРЕД ЭКСПОРТОМ: упаковка пачек в СУБД
└──────────────┬───────────────┘
               ▼
[Exporters / Connectors]
```

* **Правило 1 (`memory_limiter` строго первый):** Если поставить `batch` или `tail_sampling` перед `memory_limiter`, спаны сначала осядут в объемных очередях оперативной памяти. При пиковом всплеске трафика Linux OOM Killer уничтожит процесс коллектора до того, как `memory_limiter` успеет инициировать защитный сброс данных.
* **Правило 2 (`transform` до `tail_sampling`):** Очистка конфиденциальных данных (пароли, токены) должна выполняться до буферизации, чтобы чувствительные данные не оставались в оперативной памяти на интервал `decision_wait`.
* **Правило 3 (`batch` строго последним перед экспортерами):** `batch` задерживает передачу спанов на интервал `timeout` (1–2 секунды). Если поставить `batch` перед `tail_sampling`, это искусственно искажает расчет времени жизни спанов и ломает тайминги `decision_wait`.

---

## 3. Практические сценарии

### Сценарий 1: Комплексный анализ критического пути и разбор сквозной задержки

**Ситуация:** Пользователи веб-портала жалуются на медленную загрузку корзины заказов (`GET /checkout`). Среднее время ответа выросло с 200 мс до 2400 мс. Необходимо найти источник задержки на критическом пути.

##### Шаг 1: Поиск проблемных трейсов через CLI / cURL

```bash
# Поиск 5 последних трейсов сервиса checkout с задержкой более 2 секунд за последний час
curl -sS "http://127.0.0.1:16686/api/traces?service=checkout-service&operation=GET%20/checkout&minDuration=2s&lookback=1h&limit=5" \
  | jq -r '.data[] | {traceID: .traceID, duration: (.spans[0].duration / 1000), spansCount: (.spans | length)}'
```
```text
# → {
# →   "traceID": "4b6e8f19a0d23c5e8821bb40f1a92e11",
# →   "duration": 2415.82,
# →   "spansCount": 42
# → }
```

##### Шаг 2: Анализ спанов выбранного трейса

```bash
# Выгрузка дерева спанов трейса для определения спана с максимальным self-time
curl -sS "http://127.0.0.1:16686/api/traces/4b6e8f19a0d23c5e8821bb40f1a92e11" \
  | jq -r '.data[0].spans[] | "\(.operationName) | duration: \(.duration / 1000)ms | process: \(.processID)"'
```
```text
# → GET /checkout | duration: 2415.82ms | process: p1
# → auth.validate_token | duration: 14.12ms | process: p2
# → warehouse.check_stock | duration: 38.45ms | process: p3
# → discount.calculate_promotions | duration: 2310.15ms | process: p4
# → db.query.get_coupons | duration: 2280.90ms | process: p4
```

##### Шаг 3: Детализация критического спана в Side Panel Jaeger UI

1. Открыть Jaeger UI по адресу `http://<jaeger-host>:16686`.
2. Перейти в трейс `4b6e8f19a0d23c5e8821bb40f1a92e11`.
3. На диаграмме Gantt раскрыть ветку `discount.calculate_promotions`.
4. В боковой панели (Side Panel) проверить спан `db.query.get_coupons`:
   - Тег `db.system`: `postgresql`
   - Тег `db.statement`: `SELECT * FROM promo_coupons WHERE user_id = $1 AND is_active = true FOR UPDATE;`
   - Событие (Event): `lock_wait_acquired` со смещением в 2250 мс.
5. **Вывод SRE:** Задержка вызвана блокировкой строки (`FOR UPDATE`) в PostgreSQL, вызванной параллельной фоновой транзакцией обновления промокодов.

---

### Сценарий 2: Диагностика паттерна N+1 и избыточных обращений к базе данных

**Ситуация:** Эндпоинт `GET /catalog/products` обрабатывается за 1800 мс при получении списка из 50 товаров. Нагрузка на базу данных PostgreSQL аномально возрастает при росте RPS.

##### Шаг 1: Проверка количества однотипных вызовов в трейсе через API

```bash
# Получение распределения операций внутри медленного трейса
TRACE_ID="3c2f10ab78910cd123456789abcdef01"
curl -sS "http://127.0.0.1:16686/api/traces/${TRACE_ID}" | jq '
  [ .data[0].spans[] | select(.tags[] | select(.key == "db.system")) ] 
  | group_by(.operationName) 
  | map({operation: .[0].operationName, count: length, total_ms: (map(.duration) | add / 1000)})
'
```
```json
# → [
# →   {
# →     "count": 50,
# →     "operation": "SELECT catalog_categories",
# →     "total_ms": 1420.5
# →   },
# →   {
# →     "count": 1,
# →     "operation": "SELECT catalog_products",
# →     "total_ms": 25.1
# →   }
# → ]
```

##### Шаг 2: Анализ временной шкалы (Gantt Chart)

1. В Jaeger UI отчетливо видна лесенка из 50 последовательных спанов к PostgreSQL, каждый длительностью 25–30 мс (`duration`), где `self-time` сервиса между вызовами составляет менее 0.5 мс.
2. В тегах каждого спана содержится единичный запрос: `SELECT * FROM categories WHERE id = ?`.
3. **Решение для разработчиков:** Заменить цикл запросов на одиночный групповой запрос `SELECT * FROM categories WHERE id IN (...)` или применить кэширование справочника категорий в Redis.

---

### Сценарий 3: Настройка генерации RED-метрик (SPM) через Spanmetrics Connector

**Ситуация:** Требуется настроить вычисление метрик RED (Rate, Errors, Duration) непосредственно из трассировок на коллекторе Jaeger v2 и экспортировать их в Prometheus для построения сводных SRE-дашбордов.

##### Шаг 1: Подготовка конфигурации `jaeger-v2-spm.yaml`

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

connectors:
  spanmetrics:
    histogram:
      explicit:
        buckets: [10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2s, 5s]
    dimensions:
      - name: http.status_code
      - name: http.method
      - name: db.system
    exemplars:
      max_per_data_point: 2
    metrics_flush_interval: 15s

processors:
  batch:
    send_batch_size: 2048
    timeout: 5s

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: "traces_spanmetrics"
  jaeger_storage_exporter:
    trace_storage: clickhouse

extensions:
  jaeger_storage:
    backends:
      clickhouse:
        endpoint: "tcp://127.0.0.1:9000"
        database: "jaeger_v2"

service:
  extensions: [jaeger_storage]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [spanmetrics, jaeger_storage_exporter]
    metrics/spanmetrics:
      receivers: [spanmetrics]
      processors: [batch]
      exporters: [prometheus]
```

##### Шаг 2: Запуск Jaeger v2 и валидация эндпоинта метрик

```bash
# Запуск бинарного файла Jaeger v2 с конфигурацией
/usr/local/bin/jaeger --config /etc/jaeger/jaeger-v2-spm.yaml &

# Проверка доступности OTLP порта и Prometheus экспортера
ss -tulpn | grep -E '4317|8889'
```
```text
# → tcp   LISTEN 0      128          0.0.0.0:4317       0.0.0.0:*    users:(("jaeger",pid=21045,fd=7))
# → tcp   LISTEN 0      128          0.0.0.0:8889       0.0.0.0:*    users:(("jaeger",pid=21045,fd=9))
```

##### Шаг 3: Сбор метрик и валидация данных RED

```bash
# Проверка сгенерированных счетчиков calls_total и корзин длительности
curl -sS http://127.0.0.1:8889/metrics | grep -E 'calls_total|duration_milliseconds_bucket' | head -n 8
```
```text
# → # HELP traces_spanmetrics_calls_total Total number of calls
# → # TYPE traces_spanmetrics_calls_total counter
# → traces_spanmetrics_calls_total{http_method="GET",http_status_code="200",service_name="api-gateway",span_name="HTTP GET /order",status_code="STATUS_CODE_UNSET"} 1240
# → traces_spanmetrics_calls_total{http_method="POST",http_status_code="500",service_name="api-gateway",span_name="HTTP POST /pay",status_code="STATUS_CODE_ERROR"} 18
# → # HELP traces_spanmetrics_duration_milliseconds_bucket Duration histogram
# → # TYPE traces_spanmetrics_duration_milliseconds_bucket histogram
# → traces_spanmetrics_duration_milliseconds_bucket{le="100",service_name="api-gateway",span_name="HTTP GET /order"} 950
# → traces_spanmetrics_duration_milliseconds_bucket{le="500",service_name="api-gateway",span_name="HTTP GET /order"} 1215
```

---

### Сценарий 4: Сравнение трасс (Trace Comparison) для анализа регрессии после деплоя

**Ситуация:** После релиза версии v2.4 сервиса `payment-service` время обработки транзакции выросло на 400 мс. Требуется локализовать добавленный шаг с помощью функции сравнения трасс.

##### Шаг 1: Нахождение идентификаторов эталонного и деградировавшего трейсов

```bash
# Получение быстрого трейса до релиза (v2.3)
PRE_DEPLOY_TRACE=$(curl -sS "http://127.0.0.1:16686/api/traces?service=payment-service&operation=ProcessPayment&maxDuration=150ms&limit=1" | jq -r '.data[0].traceID')

# Получение медленного трейса после релиза (v2.4)
POST_DEPLOY_TRACE=$(curl -sS "http://127.0.0.1:16686/api/traces?service=payment-service&operation=ProcessPayment&minDuration=500ms&limit=1" | jq -r '.data[0].traceID')

echo "Эталонный трейс (v2.3): ${PRE_DEPLOY_TRACE}"
echo "Регрессионный трейс (v2.4): ${POST_DEPLOY_TRACE}"
```
```text
# → Эталонный трейс (v2.3): 8a1290bcde123456
# → Регрессионный трейс (v2.4): 9f3456bcde789012
```

##### Шаг 2: Использование режима сравнения в Jaeger UI

1. В Jaeger UI перейти на вкладку **Search**.
2. В правом верхнем углу интерфейса нажать кнопку **Compare Traces**.
3. Вставить идентификаторы:
   - **Trace A (Base):** `8a1290bcde123456`
   - **Trace B (Comparison):** `9f3456bcde789012`
4. Нажать **Compare**.

##### Шаг 3: Интерпретация результатов Diff-анализа

```text
[Trace Comparison Graph]
  ProcessPayment (Self-Time: +5ms)
  ├── ValidateCards (+2ms)
  ├── [НОВЫЙ СПАН] FraudCheck.EvaluateRisk (+385ms) ─── [ПОЯВИЛСЯ В ТРЕЙСЕ B]
  │   └── http.post fraud-detection.internal (+380ms)
  └── AuthorizeBank (+12ms)
```

**Результат анализа:** Регрессия вызвана внедрением новой проверки на фрод (`FraudCheck.EvaluateRisk`), которая выполняется синхронно в критическом пути вместо асинхронной валидации.

---

### Сценарий 5: Настройка Tail-Based Sampling для захвата аномалий и экономии хранилища

**Ситуация:** Трафик сервисов составляет 25 000 RPS. Сохранение 100% спанов перегружает диск ClickHouse. Необходимо сохранять:
- 100% трейсов с ошибками (HTTP 5xx или статус `Error`);
- 100% трейсов с общей задержкой более 1000 мс (аномалии производительности);
- 1% случайных успешных трейсов для фонового статистического анализа.

##### Шаг 1: Конфигурация процессора `tail_sampling`

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 20000
    expected_new_traces_per_sec: 5000
    policies:
      - name: drop-healthchecks
        type: string_attribute
        string_attribute:
          key: http.target
          values: ["/healthz", "/metrics", "/live"]
          enabled_regex_matching: false
          invert_match: true

      - name: sample-errors
        type: status_code
        status_code:
          status_codes: [ERROR]

      - name: sample-slow-traces
        type: latency
        latency:
          threshold_ms: 1000

      - name: probabilistic-sample
        type: probabilistic
        probabilistic:
          sampling_percentage: 1.0

  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 4096
    timeout: 5s

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [jaeger_storage_exporter]
```

##### Шаг 2: Валидация работы политик сэмплирования по внутренним метрикам

```bash
# Проверка количества трейсов, сохраненных каждой политикой
curl -sS http://127.0.0.1:8888/metrics | grep "processor_tail_sampling_count_traces_sampled"
```
```text
# → processor_tail_sampling_count_traces_sampled{policy="sample-errors"} 215
# → processor_tail_sampling_count_traces_sampled{policy="sample-slow-traces"} 84
# → processor_tail_sampling_count_traces_sampled{policy="probabilistic-sample"} 1420
```

---

### Сценарий 6: Расследование асинхронных задержек очередей сообщений через Span Links

**Ситуация:** Заказ обрабатывается асинхронно через брокер сообщений Kafka. Пользователь ожидает подтверждения заказа 30 секунд. При этом спан публикации (`Producer`) длится 5 мс, а спан обработки (`Consumer`) длится 40 мс. Где теряются остальные 29.9 секунд?

##### Шаг 1: Извлечение трейса консьюмера со связями (Span Links)

```bash
# Поиск спана Consumer с получением связанных ссылок
curl -sS "http://127.0.0.1:16686/api/traces?service=order-consumer&operation=order.process&limit=1" \
  | jq -r '.data[0].spans[] | {spanID: .spanID, operation: .operationName, startTime: .startTime, duration: .duration, links: .references}'
```
```json
# → {
# →   "spanID": "bb11223344556677",
# →   "operation": "order.process",
# →   "startTime": 1712918430000000,
# →   "duration": 42000,
# →   "links": [
# →     {
# →       "refType": "FOLLOWS_FROM",
# →       "traceID": "aa00112233445566",
# →       "spanID": "cc778899aabbccdd"
# →     }
# →   ]
# → }
```

##### Шаг 2: Расчет времени нахождения сообщения в очереди (Queue Lag)

```bash
# Время отправки продюсером: 1712918400050000 мкс (12:00:00.050)
# Время старта консьюмера:    1712918430000000 мкс (12:00:30.000)
# Задержка в брокере = (1712918430000000 - 1712918400050000) / 1000000 = 29.95 сек.
```

##### Шаг 3: Проверка состояния партиций Kafka на брокере

```bash
# Диагностика потребительской группы через утилиты Kafka
kafka-consumer-groups.sh --bootstrap-server 127.0.0.1:9092 --describe --group order-processing-group
```
```text
# → GROUP                  TOPIC           PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID     HOST
# → order-processing-group order.events    0          104520          189430          84910           consumer-pod-1  /10.244.2.14
```
**Вывод SRE:** Причина сквозной задержки — критическое отставание (Consumer Lag) в партиции 0 (84 910 сообщений). Необходим горизонтальный скейлинг консьюмеров или увеличение числа партиций топика.

---

### Сценарий 7: Защита и тюнинг производительности коллектора Jaeger v2 под экстремальной нагрузкой

**Ситуация:** В пиковые часы поток спанов возрастает до 40 000 спанов/с. Инстанс Jaeger v2 перезапускается ОС по OOMKilled. Необходимо защитить коллектор от падений и предотвратить потерю критичных данных.

##### Шаг 1: Настройка консервативного Memory Limiter и оптимизация батчей

```yaml
processors:
  memory_limiter:
    check_interval: 500ms
    # Жесткий порог ограничения: 75% от общего лимита контейнера (например, от 8GB = 6144MiB)
    limit_mib: 6144
    # Порог начала сброса всплесков
    spike_limit_mib: 1024

  batch:
    send_batch_size: 8192
    timeout: 2s
    send_batch_max_size: 16384

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

##### Шаг 2: Валидация метрик защиты памяти

```bash
# Проверка текущего потребления и количества спанов, отклоненных лимитером
curl -sS http://127.0.0.1:8888/metrics | grep "otelcol_processor_memory_limiter"
```
```text
# → otelcol_processor_memory_limiter_current_usage_mib 4892.4
# → otelcol_processor_memory_limiter_limit_mib 6144
# → otelcol_processor_memory_limiter_refused_spans_total 0
```
Если счетчик `refused_spans_total` начинает расти, это означает штатное срабатывание механизма защиты: коллектор отбрасывает часть данных, но сохраняет стабильность процесса и продолжает принимать трафик.

---

### Сценарий 8: Автоматизация контроля SLO/SLI задержек через Jaeger Query API v3

**Ситуация:** Требуется автоматический скрипт для регулярной проверки SLO надежности: «Не более 0.1% запросов сервиса `checkout-service` могут длиться дольше 1500 мс за последний час».

##### Шаг 1: Создание скрипта проверки SLO (`check_slo.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

JAEGER_QUERY="http://127.0.0.1:16686"
SERVICE="checkout-service"
LOOKBACK="1h"
THRESHOLD_MS="1500ms"
MAX_VIOLATIONS_PERCENT=0.1

# Получение суммарной статистики через Query API v3
SUMMARY_JSON=$(curl -sS "${JAEGER_QUERY}/api/v3/trace-summaries?service=${SERVICE}&lookback=${LOOKBACK}")

TOTAL_TRACES=$(echo "${SUMMARY_JSON}" | jq '.totalTraces // 0')

if [ "${TOTAL_TRACES}" -eq 0 ]; then
  echo "WARN: Трейсы сервиса ${SERVICE} за последний час не найдены."
  exit 0
fi

# Получение количества трейсов, нарушивших порог задержки
SLOW_JSON=$(curl -sS "${JAEGER_QUERY}/api/v3/trace-summaries?service=${SERVICE}&lookback=${LOOKBACK}&minDuration=${THRESHOLD_MS}")
SLOW_TRACES=$(echo "${SLOW_JSON}" | jq '.totalTraces // 0')

VIOLATION_RATE=$(awk -v slow="${SLOW_TRACES}" -v total="${TOTAL_TRACES}" 'BEGIN { printf "%.4f", (slow / total) * 100 }')

echo "Сервис: ${SERVICE}"
echo "Всего запросов: ${TOTAL_TRACES}"
echo "Запросов > ${THRESHOLD_MS}: ${SLOW_TRACES} (${VIOLATION_RATE}%)"

if (( $(echo "${VIOLATION_RATE} > ${MAX_VIOLATIONS_PERCENT}" | bc -l) )); then
  echo "CRITICAL: Нарушение SLO! Уровень деградаций ${VIOLATION_RATE}% превышает допустимый порог ${MAX_VIOLATIONS_PERCENT}%"
  exit 2
else
  echo "OK: Сервис находится в пределах бюджета ошибок SLO."
  exit 0
fi
```

##### Шаг 2: Запуск и валидация скрипта

```bash
chmod +x check_slo.sh
./check_slo.sh
```
```text
# → Сервис: checkout-service
# → Всего запросов: 18450
# → Запросов > 1500ms: 7 (0.0379%)
# → OK: Сервис находится в пределах бюджета ошибок SLO.
```

---

### Сценарий 9: Построение топологии зависимостей сервисов на лету через Servicegraph Connector

**Задача:** Автоматизировать расчет направленного графа связей между микросервисами в реальном времени без развертывания тяжелых внешних джоб обработки спанов (устаревший batch `jaeger-spark-dependencies`).

#### 1. Архитектура коннектора `servicegraph`
В Jaeger v2 коннектор `servicegraph` перехватывает спаны типа `SpanKindClient` и `SpanKindServer`, сопоставляет родительские и дочерние вызовы по `parent_span_id` и генерирует три метрики топологии в Prometheus:
* `traces_service_graph_request_total`: суммарное число вызовов между `client` и `server`.
* `traces_service_graph_request_failed_total`: число вызовов с ошибками (`failed="true"`).
* `traces_service_graph_request_server_seconds_bucket`: гистограмма времени ответа клиент-серверного взаимодействия.

#### 2. Конфигурация Jaeger v2 с коннектором `servicegraph`

```yaml
connectors:
  servicegraph:
    dimensions:
      - connection.type
    store:
      ttl: 20s
      max_items: 10000

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
    spike_limit_percentage: 20

  batch:
    send_batch_size: 4096
    timeout: 1s

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_main

  prometheus:
    endpoint: 0.0.0.0:8889
    namespace: "traces_servicegraph"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter, servicegraph]

    metrics/servicegraph:
      receivers: [servicegraph]
      processors: [memory_limiter]
      exporters: [prometheus]
```

#### 3. Валидация выгрузки топологии через Prometheus API

```bash
# Проверка счетчиков графа вызовов между клиентом (api-gateway) и сервером (auth-service)
curl -sS "http://127.0.0.1:8889/metrics" | grep "traces_servicegraph_request_total"
# → # HELP traces_servicegraph_request_total Total number of requests between services
# → # TYPE traces_servicegraph_request_total counter
# → traces_servicegraph_request_total{client="api-gateway",server="auth-service",failed="false"} 8420
# → traces_servicegraph_request_total{client="api-gateway",server="auth-service",failed="true"} 14
# → traces_servicegraph_request_total{client="api-gateway",server="order-service",failed="false"} 3910
```

Метрики `traces_servicegraph_*` напрямую подключаются в панели **Grafana Node Graph Panel**, формируя динамическую интерактивную карту сервисов с индикацией задержек ребер и частоты сбоев.

---

## 4. Операции и команды

В таблице собраны основные команды оперативного мониторинга и диагностики производительности трейсинга:

| Категория | Команда / Запрос | Назначение |
| :--- | :--- | :--- |
| **Jaeger Query API** | `curl -sS "http://127.0.0.1:16686/api/traces?service=auth&minDuration=1s&limit=20"` | Выгрузка списка трейсов с задержкой более 1с |
| **Jaeger Query API v3** | `curl -sS "http://127.0.0.1:16686/api/v3/trace-summaries?service=api-gateway&lookback=30m"` | Агрегированная сводка длительностей по сервису |
| **ClickHouse Диагностика** | `clickhouse-client --query "SELECT quantile(0.99)(duration_us)/1000 AS p99_ms FROM jaeger_v2.spans WHERE service_name='auth' AND timestamp >= now() - INTERVAL 1 HOUR"` | Прямой расчет p99 latency в хранилище |
| **ClickHouse Нагрузка** | `clickhouse-client --query "SELECT service_name, count() AS total_spans, round(sum(length(tags))/1024/1024, 2) AS tags_mb FROM jaeger_v2.spans WHERE timestamp >= now() - INTERVAL 1 HOUR GROUP BY service_name ORDER BY total_spans DESC LIMIT 5"` | Определение сервисов, создающих максимальный объем данных |
| **Метрики Коллектора** | `curl -sS http://127.0.0.1:8888/metrics \| grep -E 'otelcol_receiver_accepted_spans|otelcol_receiver_refused_spans'` | Контроль пропускной способности приемников OTLP |
| **PromQL: p99 Latency** | `histogram_quantile(0.99, sum(rate(traces_spanmetrics_duration_milliseconds_bucket{service_name="api-gateway"}[5m])) by (le))` | Расчет p99 задержки в Grafana/Prometheus |
| **PromQL: Error Rate** | `sum(rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[5m])) / sum(rate(traces_spanmetrics_calls_total[5m])) * 100` | Расчет процента ошибок по сервисам |

### 4.1 Проверка состояния хранилища ClickHouse через CLI

```bash
# Проверка размера таблиц спанов и индексов на узле ClickHouse
clickhouse-client --query "
SELECT 
    table, 
    formatReadableSize(sum(data_compressed_bytes)) AS compressed, 
    formatReadableSize(sum(data_uncompressed_bytes)) AS uncompressed, 
    round(sum(data_uncompressed_bytes) / sum(data_compressed_bytes), 2) AS ratio,
    sum(rows) AS total_rows 
FROM system.parts 
WHERE database = 'jaeger_v2' AND active = 1 
GROUP BY table;
"
```
```text
# → table  compressed  uncompressed  ratio  total_rows
# → spans  14.21 GiB   118.45 GiB    8.34   142850000
```

### 4.2 Проверка отброшенных спанов на коллекторе

```bash
# Диагностика сброса спанов из-за переполнения очередей экспортеров
curl -sS http://127.0.0.1:8888/metrics | grep "otelcol_exporter_enqueue_failed_spans"
```
```text
# → otelcol_exporter_enqueue_failed_spans{exporter="jaeger_storage_exporter"} 0
```

---

## 5. Типичные проблемы и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий p99 latency при стабильном p50** | «Длинный хвост» запросов: единичные блокировки строк в БД, медленный GC или дисковый I/O | Поиск спанов с `minDuration=3s`. Анализ тегов `db.statement`, просмотр `wait.lock` | Оптимизация тяжелых запросов, переход на Read-Replica, увеличение пула соединений |
| **Collector падает с аварийным завершением OOM** | Отсутствует `memory_limiter` при резком росте RPS или включен `tail_sampling` с огромным `decision_wait` | `dmesg -T \| grep -i "killed process"`. Рост метрики `otelcol_processor_memory_limiter_current_usage_mib` | Включить `memory_limiter` с порогом 75–80% RAM; уменьшить `decision_wait` до 5–10 секунд |
| **Потеря трейсов (Missing Spans)** | Переполнение буфера экспортера или сетевой backpressure к ClickHouse | Рост метрик `otelcol_exporter_enqueue_failed_spans` или `otelcol_receiver_refused_spans` | Увеличить `queue_size` в экспортёре; оптимизировать диски ClickHouse (NVMe, XFS) |
| **Span Metrics не генерируются** | Некорректный пайплайн в конвейере: коннектор `spanmetrics` не подключен как приемник в пайплайн метрик | Метрика `curl localhost:8889/metrics` возвращает 404 или пустой список счетчиков | Сверить схему пайплайна: экспорт спанов в `spanmetrics`, чтение метрик из `spanmetrics` |
| **Взрыв кардинальности (Cardinality Explosion) в Prometheus** | В `dimensions` коннектора `spanmetrics` добавлены динамические теги (`user_id`, `order_id`, `url_path` с ID) | Prometheus потребляет десятки гигабайт RAM; лог `too many series in scrape` | Удалить динамические атрибуты из секции `dimensions`. Оставить только `service_name`, `span_name`, `http.status_code` |
| **Рассинхронизация Timeline (Clock Skew)** | Рассинхронизация времени NTP между серверами микросервисов | Дочерние спаны отображаются раньше родительских (отрицательная длительность) | Настроить службу синхронизации времени `chrony` на всех хостах (`chronyc tracking`) |
| **Медленный поиск трейсов в Jaeger UI (>10 сек)** | Полнотекстовый поиск по неиндексированным тегам в больших таблицах ClickHouse | Запрос к ClickHouse `system.query_log` показывает сканирование миллиардов строк | Добавить Secondary Index (Bloom Filter) на поле `tags` в таблице `jaeger_v2.spans` ClickHouse |
| **Холодный старт и разорванные трейсы (Orphan Spans)** | Потеря контекста (`traceparent`) в асинхронных задачах или потоках пула приложения | Корневые спаны отсутствуют, спаны микросервисов отображаются как независимые трейсы | Проверить передачу W3C Trace Context заголовков через контекст выполнения задачи (`Tracer.extract/inject`) |
| **Низкая гранулярность перцентилей задержки** | Стандартные границы интервалов гистограммы `spanmetrics` не соответствуют реальному диапазону | График p95/p99 в Grafana выглядит ступенчатым без плавных переходов | Настроить `explicit.buckets` в конфигурации `spanmetrics` с шагом под профиль сервиса (от 10ms до 10s) |
| **Задержки в очереди очередей не видны в трейсе** | Использование стандартного родительского контекста для асинхронных сообщений вместо Span Links | Длительность консьюмера ошибочно включает 20 минут нахождения сообщения в брокере | Использовать `Span Links` (`SpanRefType.FOLLOWS_FROM`) для разделения трейса продюсера и консьюмера |

---

## 6. Лучшие практики

1. **Ориентация на критический путь (Amdahl's Law):**
   При оптимизации производительности распределенного запроса никогда не начинайте с сервисов, находящихся вне критического пути. Сокращение времени выполнения параллельной ветки со 100 мс до 10 мс не изменит общее время ответа клиента, если соседняя ветка выполняется 800 мс.
2. **Изоляция высококардинальных атрибутов:**
   Никогда не выносите идентификаторы сущностей (`customer_id`, `jwt_token`, `payment_id`) в `dimensions` процессоров генерации метрик (`spanmetrics`). Кардинальность в миллионы уникальных рядов гарантированно приведет к падению Prometheus по OOM. Детальные идентификаторы должны оставаться тегами спанов в ClickHouse.
3. **Использование Tail-based Sampling для производственных контуров:**
   При объеме трафика более 5 000 RPS хранение всех успешных быстрых запросов экономически нецелесообразно. Настройте Tail-based Sampling с правилом: 100% трейсов с ошибками, 100% трейсов с латентностью выше порога SLO (p95/p99) и 1–5% фонового трафика.
4. **Контроль задержек очередей через Span Links:**
   Для асинхронных взаимодействий через Kafka/RabbitMQ не делайте спан консьюмера прямым дочерним спаном продюсера (Child-Of), так как это искажает расчет сквозного времени ответа родительского HTTP-запроса. Используйте семантическую связь `Span Links` (`Follows-From`).
5. **Связывание метрик и трейсов через Exemplars:**
   Активируйте передачу `trace_id` в метриках гистограмм Prometheus (`exemplars`). Это сокращает Mean Time to Resolution (MTTR) от обнаружения пика задержки на дашборде Grafana до перехода к проблемному спану до одного клика мыши.
6. **Оптимизация схемы хранения ClickHouse:**
   Для таблицы `jaeger_v2.spans` используйте партиционирование по дням (`toYYYYMMDD(timestamp)`), сортировку по первичному ключу `(service_name, operation_name, toStartOfHour(timestamp), duration_us)` и настройте автоматический TTL (`TTL timestamp + INTERVAL 14 DAY DELETE`).
7. **Мониторинг внутреннего состояния коллекторов Jaeger:**
   Обязательно настройте алерты Prometheus на внутренние метрики Jaeger:
   - `otelcol_processor_memory_limiter_refused_spans_total > 0` (коллектор под угрозой OOM);
   - `otelcol_exporter_enqueue_failed_spans > 0` (переполнение очередей отправки в ClickHouse);
   - `rate(otelcol_receiver_refused_spans[5m]) > 0` (сетевой отказ в приеме телеметрии).

---

## 7. Очистка тестового окружения

Команды для безопасного сброса временных данных профилирования и тестовых стендов на Linux хосте:

```bash
# 1. Остановка локального процесса Jaeger v2
pkill -f "jaeger --config" || true

# 2. Остановка тестового стека Docker Compose (если использовался локальный стенд)
docker compose -f /opt/jaeger-bench/docker-compose.yaml down -v

# 3. Очистка временных тестовых партиций в ClickHouse
clickhouse-client --query "DROP TABLE IF EXISTS jaeger_v2.spans_test;"
# → OK

# 4. Проверка состояния системных ресурсов и сетевых портов
ss -tulpn | grep -E '4317|4318|16686|8889' || echo "Все порты трассировки успешно освобождены"
# → Все порты трассировки успешно освобождены
```

---

## 8. Дополнительная информация

**Смежные разделы базы знаний:**

* Архитектурное устройство и конвейеры Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Детальная конфигурация OTLP конвейеров и процессоров: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* Организация и оптимизация хранилища ClickHouse: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* Интеграция с Grafana, дашборды SPM и настройка Exemplars: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* Эксплуатация программного интерфейса запросов: **[Query API Jaeger](./jaeger_query_api.md)**
* Расчет инфраструктурных мощностей и сайзинг: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Развертывание в высоконадежных конфигурациях: **[High Availability и DR](./jaeger_high_availability.md)**
* Общий обзор платформы и терминология: **[Обзор Jaeger](./jaeger_overview.md)**
* Теоретические основы распределенной трассировки: **[Traces Deep Dive](../Concepts/Observability_and_Monitoring/traces_deep_dive.md)**
