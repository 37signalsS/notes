# Анализ производительности с помощью Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

**Анализ производительности в Jaeger** — это процесс глубокой интерпретации данных трассировки для выявления узких мест, анализа задержек и диагностики сложных распределенных сбоев. В версии v2 Jaeger перешел на нативную поддержку модели данных OpenTelemetry, что расширило возможности визуализации, автоматизации анализа и корреляции сигналов телеметрии.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Timeline (Gantt Chart)** | Каскадная диаграмма, показывающая последовательность и длительность спанов. Основной инструмент для визуального анализа задержек |
| **Критический путь (Critical Path)** | Последовательность спанов, которая напрямую определяет общую длительность трассы. Оптимизация спанов вне этого пути не уменьшит время ответа пользователю |
| **Trace Logs (Unified View)** | Представление всех событий (**Span Events**) трейса в виде единого хронологического списка, позволяющее видеть "историю" запроса без переключения между спанами |
| **Deep Dependency Graph (DDG)** | Граф зависимостей, показывающий полные транзитивные пути вызовов (A -> B -> C) относительно выбранного сервиса |
| **Span Links** | Связи между спанами, которые не являются родительскими (например, связь между трейсом обработки сообщения и трейсом его публикации в очереди) |
| **Паттерн N+1** | Проблема, при которой сервис выполняет множество последовательных мелких запросов (обычно к БД) вместо одного группового вызова |
| **Span Metrics / SPM** | Метрики, генерируемые на основе спанов (RPS, Error Rate, Latency), позволяющие видеть производительность на уровне сервисов и операций |
| **RED-метрики** | Три фундаментальные метрики для оценки сервиса: **Rate** (частота запросов), **Errors** (доля ошибок), **Duration** (задержка). В Jaeger v2 вычисляются через процессор `spanmetrics` |
| **SLI (Service Level Indicator)** | Количественный показатель здоровья сервиса (например, p99 latency < 500ms). В контексте Jaeger SLI строится на основе агрегации спанов |
| **SLO (Service Level Objective)** | Целевое значение SLI за определенный период (например, 99.9% запросов с latency < 500ms в течение месяца). Используется для баланса между новыми фичами и надежностью |
| **SLA (Service Level Agreement)** | Контракт с пользователем, основанный на SLO. Нарушение SLA влечет финансовые или репутационные последствия. Jaeger предоставляет данные для расчета error budget |
| **Процентили (Percentiles)** | Значение, ниже которого падает заданный процент наблюдений. p50 — медиана, p95/p99 — хвост задержек. В Jaeger UI отображаются для каждого сервиса и операции |
| **Span-to-Metrics** | Процесс преобразования трассировочных данных в метрики Prometheus через процессор `spanmetrics` OTel Collector. Позволяет строить дашборды RED без дополнительного инструментирования |
| **Tail Latency** | Задержка «хвоста» распределения (p99, p999). В отличие от среднего значения, отражает опыт наихудших пользователей и является ключевым индикатором производительности распределенных систем |
| **Backpressure** | Механизм обработки перегрузки при переполнении буферов агента или коллектора. Спаны отбрасываются на уровне Collector; метрики `spans_dropped_total` позволяют отследить потерю видимости |
| **Exemplars** | Примеры конкретных спанов, прикрепленные к гистограммам метрик. Позволяют переходить от агрегированной метрики (p99 = 2s) к конкретной трассе, вызвавшей пик |

---

## Базовые концепции

### Ключевые элементы интерфейса Jaeger v2

Интерфейс Jaeger v2 оптимизирован для работы с большими объемами данных и поддерживает нативные возможности OpenTelemetry:

*   **Панель поиска:** Поддерживает фильтрацию по сервисам, операциям, тегам (`http.status_code=500`, `error=true`) и пользовательским атрибутам.
*   **Side Panel Details:** Детали спана (теги, логи, метаданные) открываются в боковой панели, не перекрывая временную шкалу трейса.
*   **Trace Statistics:** Агрегированная статистика по типам спанов и сервисов внутри одного трейса, помогающая быстро найти компоненты с наибольшим вкладом в задержку.
*   **Deep Dependencies:** Интерактивный граф, позволяющий анализировать зависимости на уровне сервисов и конкретных эндпоинтов.

### Service Performance Monitoring (SPM)

В Jaeger v2 значительно улучшена поддержка SPM. Система позволяет вычислять **RED-метрики** (Rate, Errors, Duration) непосредственно из потока спанов:
*   **Агрегация:** Выполняется на стороне коллектора (через `spanmetrics` processor) или Query-сервиса.
*   **Визуализация:** В UI доступны графики задержек (p99, p95) и процента ошибок для каждой операции.
*   **Корреляция:** Прямой переход от всплеска на графике метрик к списку соответствующих трейсов.

### RED-метрики в контексте Jaeger

**RED** — это методология мониторинга, сфокусированная на взаимодействиях между сервисами (API, базы данных, очереди). В Jaeger v2 RED-метрики строятся на-native на данных трассировки:

| Компонент | Что измеряет | Источник данных в Jaeger |
| :--- | :--- | :--- |
| **Rate (Частота)** | Количество запросов в секунду (RPS) к сервису или операции | Агрегация спанов по `service_name` + `operation_name` через `spanmetrics` processor |
| **Errors (Ошибки)** | Доля запросов, завершившихся с кодом 5xx или статусом `Error` в спане | Фильтрация по `span.status = Error` или `http.status_code >= 500` |
| **Duration (Задержка)** | Распределение времени обработки запроса (p50, p95, p99) | Агрегация атрибута `duration` спанов в гистограмму Prometheus |

**Важно:** RED-метрики дополняют, но не заменяют классические метрики Prometheus из приложения. Трассировка дает контекст (почему именно этот запрос медленный), а метрики — тенденцию.

### SLI, SLO и SLA в Jaeger

Для построения системы надежности на основе данных Jaeger используются три взаимосвязанных понятия:

*   **SLI (Service Level Indicator):** Количественный показатель, который можно измерить. Пример: «p99 latency для сервиса `payment` составляет 450ms». В Jaeger SLI вычисляется агрегацией спанов за скользящее окно.
*   **SLO (Service Level Objective):** Целевое значение SLI за определенный период. Пример: «99.9% запросов к `payment` должны иметь latency < 500ms в течение 30 дней». Нарушение SLO приводит к расходованию error budget.
*   **SLA (Service Level Agreement):** Контракт с внешним пользователем или бизнесом, основанный на SLO. При нарушении SLA обычно предусмотрены финансовые санкции. Jaeger не управляет SLA напрямую, но предоставляет первичные данные для его расчета.

**Практическое применение:** Настройте дашборд Grafana, который запрашивает у Jaeger Query API данные о p99 latency за последний час и сравнивает с SLO. При превышении порога — создавать тикет автоматически.

### Перцентили и Tail Latency

Среднее значение (mean) скрывает «хвост» задержек — опыт наихудших пользователей. Для корректного анализа производительности используются перцентили:

| Перцентиль | Значение | Использование |
| :--- | :--- | :--- |
| **p50 (медиана)** | 50% запросов быстрее этого значения | Типичный опыт пользователя |
| **p95** | 95% запросов быстрее | Обычный порог для SLO веб-сервисов |
| **p99** | 99% запросов быстрее | Индикатор «хвоста»; ключевая метрика для распределенных систем |
| **p999** | 99.9% запросов быстрее | Экстремальные случаи; используется в high-frequency trading и реального времени |

В Jaeger UI перцентили отображаются в Trace Statistics и в SPM-дашбордах. Для автоматического расчета настройте `spanmetrics` processor с гистограммами:

```yaml
spanmetrics:
  metrics_exporter: prometheus
  histogram:
    explicit:
      buckets: [50ms, 100ms, 200ms, 500ms, 1s, 2s, 5s]
```

### Процессор Span Metrics (spanmetrics)

Процессор `spanmetrics` — ключевой компонент для преобразования трейсов в метрики. Он работает внутри OTel Collector и генерирует:
*   **Счетчики:** `calls_total` — общее количество спанов по сервису/операции.
*   **Гистограммы:** `duration_bucket` — распределение задержек для расчета перцентилей.
*   **Dimensions:** Набор атрибутов, по которым происходит группировка (например, `http.method`, `http.status_code`, `db.system`).

**Важно:** `spanmetrics` не отправляет метрики сам — он только создает их в памяти. Для экспорта в Prometheus добавьте `prometheus` exporter в пайплайн или используйте `prometheusremotewrite` exporter.

### Ресурсные требования для анализа производительности

Анализ производительности в production требует достаточных ресурсов для хранения и обработки данных:

| Компонент | CPU | RAM | Примечание |
| :--- | :--- | :--- | :--- |
| **Collector (spanmetrics)** | 1 - 2 ядра | 1GB - 2GB | Зависит от количества OTLP-соединений и Dimensions в spanmetrics |
| **Query Service** | 2 - 4 ядра | 2GB - 4GB | Высокая нагрузка при сложных аналитических запросах к ClickHouse |
| **ClickHouse** | 4 - 8 ядер | 8GB - 16GB | Зависит от объема данных (>10M спанов/день требует кластера) |
| **Prometheus** | 2 - 4 ядра | 4GB - 8GB | Для хранения метрик spanmetrics за 7-30 дней |

### Backpressure и потеря данных

При перегрузке системы (всплеск трафика, недоступность хранилища) часть спанов может быть отброшена. В Jaeger v2 существует несколько уровней защиты:

1.  **Memory Limiter Processor:** Ограничивает потребление памяти коллектора. При превышении лимита данные отбрасываются gracefully.
2.  **Batch Processor:** Группирует спаны перед отправкой, уменьшая количество сетевых вызовов.
3.  **Kafka Buffer:** В streaming-архитектуре Kafka накапливает спаны при недоступности ClickHouse.
4.  **Мониторинг потерь:** Метрика `otelcol_exporter_send_failed_spans_total` или `jaeger_span_store_write_errors_total` сигнализирует о проблемах. Метрика `otelcol_receiver_refused_spans_total` — о перегрузке на приеме.

**Практическое правило:** Если `spans_dropped_total` растет, — это всегда проблема инфраструктуры (недостаточно ресурсов, сетевые задержки, падение БД), а не инструментации приложений.

### Методика анализа производительности

1.  **Поиск аномалий:** Используйте фильтр `Min Duration` и поиск по тегам для нахождения трейсов, выходящих за рамки **SLO (Service Level Objectives)**.
2.  **Анализ критического пути:** Определите, какой сервис или база данных удерживает выполнение запроса. В Jaeger UI критический путь часто подсвечивается или визуально определяется как непрерывная цепь спанов.
3.  **Идентификация "водопадов":** Ищите последовательные вызовы, которые могли бы выполняться параллельно. Это типичный признак неэффективного использования ресурсов.
4.  **Анализ событий (Events):** Изучите раздел Trace Logs для поиска ошибок или задержек на уровне кода (например, время ожидания захвата мьютекса или длительность Garbage Collection).

---

## Практические сценарии

### Сценарий 1: Диагностика "длинного хвоста" (Long Tail Latency)

**Ситуация:** Среднее время ответа в норме, но 1% запросов обрабатывается более 5 секунд.

| Шаг | Действие | Результат |
| :--- | :--- | :--- |
| **1** | Поиск в UI: `Service`: `gateway`, `Min Duration`: `5s` | Список аномально медленных трейсов |
| **2** | Выбор трейса и переход в **Trace Statistics** | Выявлено, что 95% времени тратится на один сервис `auth` |
| **3** | Анализ спана в `auth` через Side Panel | Тег `db.statement` показывает сложный SQL-запрос, а тег `wait.lock` — ожидание блокировки в БД |
| **4** | Исправление | Оптимизация индекса или пересмотр стратегии блокировок |

### Сценарий 2: Генерация Span Metrics в OTel Collector

Для получения метрик производительности без дополнительного инструментирования настройте процессор в Jaeger v2:

```yaml
processors:
  spanmetrics:
    metrics_exporter: prometheus
    dimensions:
      - name: http.method
      - name: http.status_code

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [spanmetrics, batch]
      exporters: [jaeger_storage_exporter]
```

**Валидация:**

1. Применить конфигурацию: `jaeger --config collector-config.yaml`.
2. Отправить тестовые запросы к сервису.
3. Проверить метрики: `curl -s http://localhost:8888/metrics | grep calls_total` — должны отображаться счетчики по сервисам.
4. В Prometheus выполнить запрос: `rate(calls_total{service_name="api-gateway"}[5m])` — должен отображаться Rate.
5. Для Duration: `histogram_quantile(0.99, sum(rate(duration_bucket{service_name="api-gateway"}[5m])) by (le))` — должен показываться p99.

### Сценарий 3: Автоматизация через API v3

Для автоматического мониторинга качества трейсов используйте новый API Jaeger. Пример получения сводки по медленным трейсам:

```bash
curl 'http://jaeger-query:16686/api/v3/trace-summaries?service=api-gateway&minDuration=2s&lookback=1h'
```

**Валидация:**

1. Выполнить запрос и убедиться, что возвращается JSON со сводкой.
2. Проверить, что количество трейсов в ответе совпадает с фильтром в UI.
3. Интегрировать запрос в скрипт мониторинга или Grafana (через JSON API).

### Сценарий 4: Настройка Tail-based Sampling для захвата аномалий

Для эффективного анализа в высоконагруженных системах используйте `tailsamplingprocessor`, чтобы сохранять 100% "медленных" трейсов:

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: sample-errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: sample-slow-traces
        type: latency
        latency: {threshold_ms: 2000}
```

**Валидация:**

1. Запустить коллектор с конфигурацией: `jaeger --config collector-config.yaml`.
2. Вызвать ошибку в приложении: `curl -X POST http://app:8080/fail` — убедиться, что трейс сохранен.
3. Вызвать задержку >2s: `curl -X POST http://app:8080/slow` — убедиться в сохранении.
4. Проверить метрики: `curl http://localhost:8888/metrics | grep processor_tail_sampling` — количество принятых решений должно расти.

### Сценарий 5: Тюнинг ресурсов Collector для High-Load

**Ситуация:** Collector падает с OOM при нагрузке 5,000 spans/s. Необходимо оптимизировать конфигурацию.

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 2048
    spike_limit_mib: 512
  batch:
    send_batch_size: 1024
    timeout: 10s
  tail_sampling:
    decision_wait: 5s
    num_traces: 5000
    policies:
      - name: sample-errors
        type: status_code
        status_code: {status_codes: [ERROR]}
```

**Шаги:**

1. Добавить `memory_limiter` с лимитом 2GB и spike_limit 512MB.
2. Увеличить `send_batch_size` до 1024 для уменьшения количества сетевых вызовов.
3. Уменьшить `decision_wait` до 5s для снижения латентности tail-sampling (при риске потери части трейсов).
4. Мониторить метрики: `otelcol_processor_memory_limiter_refused_spans_total` (должен быть 0).

**Валидация:**

```bash
# Проверка метрик памяти
curl -s http://localhost:8888/metrics | grep memory_limiter
# → otelcol_processor_memory_limiter_current_usage_mib{...} 145.2
# → otelcol_processor_memory_limiter_refused_spans_total{...} 0
```

### Сценарий 6: Масштабирование Query Service

**Ситуация:** При нагрузке 50 concurrent users поиск по сервисам занимает >10 секунд. Необходимо горизонтально масштабировать Query.

```yaml
# query-config.yaml
extensions:
  jaeger_storage:
    trace_storage:
      type: clickhouse
      options:
        clickhouse:
          endpoint: "tcp://clickhouse:9000"
          database: jaeger_v2
  jaeger_query:
    ui:
      config_file: /etc/jaeger/ui.json

service:
  extensions: [jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: []
      exporters: []
```

**Шаги:**

1. Запустить несколько инстансов Query с одинаковой конфигурацией.
2. Настроить Load Balancer перед портом 16686 (round-robin или least-connections).
3. В ClickHouse проверить права доступа: `SHOW GRANTS FOR 'jaeger'` — пользователь должен иметь `SELECT` на всех таблицах.
4. Мониторить метрики: `jaeger_query_search_latency_seconds` (должна снижаться с ростом инстансов).

**Валидация:**

```bash
# Запуск 3 инстансов Query
jaeger --config query-config.yaml &  # Порт 16686
jaeger --config query-config.yaml --grpc-port 16687 &  # Порт 16687
jaeger --config query-config.yaml --grpc-port 16688 &  # Порт 16688

# Проверка через LB
curl -s http://localhost:16686/api/traces?service=api-gateway&limit=10 | jq .
```

### Сценарий 7: Автоматизация алертинга на основе RED-метрик

**Ситуация:** Необходимо настроить алерты в Prometheus/Grafana на превышение p99 latency и рост ошибок.

**PromQL-запросы:**

```promql
# p99 latency для сервиса api-gateway (должен быть < 500ms)
histogram_quantile(0.99, sum(rate(duration_bucket{service_name="api-gateway"}[5m])) by (le))

# Error rate для сервиса (должен быть < 1%)
sum(rate(calls_total{service_name="api-gateway", status_code="5xx"}[5m])) / sum(rate(calls_total{service_name="api-gateway"}[5m])) * 100

# RPS (Rate) для сервиса
sum(rate(calls_total{service_name="api-gateway"}[5m]))
```

**Валидация:**

1. Искусственно вызвать рост latency: `ab -n 1000 -c 50 -s 2000 http://app:8080/api`.
2. Убедиться, что алерт срабатывает в Grafana.
3. Искусственно вызвать ошибки (500 status) и проверить срабатывание алерта на Error Rate.

### Сценарий 8: Использование Exemplars для перехода от метрик к трейсам

**Ситуация:** Grafana показывает всплеск p99 latency, но не ясно, какой конкретно запрос вызвал проблему.

**Решение:** Включить Exemplars в `spanmetrics` processor:

```yaml
spanmetrics:
  metrics_exporter: prometheus
  dimensions:
    - name: service_name
    - name: operation_name
  exemplars:
    traceIDAttribute: trace_id
    spanIDAttribute: span_id
```

**Результат:** В Prometheus и Grafana метрики latency будут содержать ссылки на конкретные трейсы. При наведении на всплеск на графике можно сразу перейти к детальному анализу спана в Jaeger UI.

### Сценарий 9: Корреляция Span Metrics и Application Metrics

**Ситуация:** Нужно сопоставить всплеск latency на уровне приложения (из Prometheus) с конкретными трейсами (из Jaeger).

**Алгоритм:**

1. В дашборде Grafana расположить рядом панель с `http_request_duration_seconds` (p99) и панель с трассами Jaeger (через Jaeger Data Source).
2. Использовать временную синхронизацию: при клике на пик latency в метриках — фильтр в Jaeger UI по времени и сервису.
3. Для автоматизации использовать Span Links между трейсами producer и consumer (например, между gateway и auth-service).

**Валидация:**

1. Создать всплеск latency через `curl -X POST http://app:8080/slow`.
2. В Grafana найти соответствующий пик на графике.
3. В Jaeger UI найти трейс по времени и сервису — убедиться, что причина медленного ответа видна на Timeline.

---

## Типичные проблемы производительности и устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий p99 latency при стабильном p50** | "Длинный хвост" запросов к базе данных или внешним зависимостям | Анализ Trace Statistics, поиск спанов с `db.system` и высокой длительностью | Оптимизация индексов БД, добавление кэширования, пересмотр connection pool |
| **Collector падает с OOM** | Отсутствует `memory_limiter` или некорректный `limit_mib` при высокой нагрузке | `dmesg | grep -i "oom\|killed"`, метрики `otelcol_processor_memory_limiter_current_usage_mib` | Добавить `memory_limiter` с `limit_mib`, настроить `spike_limit_mib`, увеличить RAM инстанса |
| **Span Metrics не генерируются** | Процессор `spanmetrics` не включен в пайплайн или `metrics_exporter` не настроен | `curl localhost:8888/metrics | grep calls_total` — метрики отсутствуют | Проверить порядок процессоров: `[spanmetrics, batch]`, убедиться что `metrics_exporter: prometheus` указан |
| **Missing Spans (пропуски данных)** | Переполнение буфера, недоступность Kafka/хранилища, backpressure | `otelcol_exporter_send_failed_spans_total`, `spans_dropped_total` | Увеличить `send_batch_size`, проверить доступность БД, добавить Kafka buffer |
| **Медленный поиск в UI** | Отсутствие индексов в ClickHouse, большое количество данных, сложные фильтры | `system.metrics` в ClickHouse, `query_log` | Добавить индексы по `service_name`, `operation_name`, настроить TTL, ограничить период поиска |
| **Tail Sampling не работает** | Неверная конфигурация `decision_wait` или policies, нехватка RAM | `processor_tail_sampling_traces_seen` != 0, но `sampling_decision_latency` растет | Увеличить `limit_mib` в `memory_limiter`, проверить синтаксис YAML, уменьшить `num_traces` |
| **Дублирование спанов в хранилище** | Несколько Collector'ов отправляют данные без идемпотентности, Kafka Consumer Group конфликт | `SELECT count(DISTINCT span_id) FROM jaeger_v2.spans` != `count(*)` | Включить дедупликацию на уровне БД, использовать Kafka с ключом `trace_id`, настроить идемпотентность Consumer |
| **Clock Skew искажает Timeline** | Рассинхронизация NTP между серверами, отсутствие `chrony` | Спаны отображаются в будущем или с отрицательной длительностью | Настроить `chrony` или `systemd-timesyncd` на всех узлах, проверить `clock_skew` в Jaeger UI |
| **Низкая точность перцентилей** | Слишком маленький `send_batch_size` или отсутствие гистограмм в spanmetrics | График p99 "ступенчатый", а не плавный | Увеличить `send_batch_size`, настроить explicit buckets в spanmetrics (50ms, 100ms, 200ms, 500ms, 1s, 2s, 5s) |
| **UI показывает пустые сервисы** | Query extension не настроен или `service_name` отсутствует в спанах | Раздел Services пуст, хотя спаны есть в БД | Проверить семантические конвенции (`service.name`), перезапустить Query с актуальной конфигурацией Storage |

---

## Лучшие практики анализа производительности

1.  **Начинайте с SLI/SLO:** Прежде чем настраивать мониторинг, определите целевые перцентили (p95, p99) и допустимый уровень ошибок. Без SLO метрики бессмысленны.
2.  **Используйте RED для дашбордов:** Стройте дашборды Grafana по методу RED (Rate, Errors, Duration) для каждого критического сервиса. Это обеспечивает единый стандарт observability.
3.  **Коррелируйте метрики и трейсы:** Настройте Exemplars в `spanmetrics`, чтобы из Grafana можно было одним кликом перейти к детальному трейсу в Jaeger UI.
4.  **Tail-based Sampling для production:** Head-based Sampling отбрасывает редкие, но важные аномалии. В высоконагруженных системах используйте Tail-based Sampling с политиками на ошибки и задержки.
5.  **Мониторинг самого Jaeger:** Настройте алерты на метрики Collector'а: `otelcol_receiver_refused_spans_total` (прием данных отклоняется), `otelcol_exporter_send_failed_spans_total` (ошибки записи), `otelcol_processor_memory_limiter_refused_spans_total` (OOM риск). Отсутствие спанов в хранилище чаще всего является результатом падения экспортера, а не проблем в инструментации приложений.
6.  **Ограничивайте кардинальность тегов:** Высокая кардинальность (`user_id`, `request_id` с миллионами значений) приводит к взрыву индексов в ClickHouse и росту потребления памяти. Используйте агрегированные атрибуты (`customer_tier=gold`) вместо уникальных идентификаторов.
7.  **Настраивайте TTL в ClickHouse:** Автоматическое удаление старых трейсов (`TTL createdAt + INTERVAL 7 DAY`) предотвращает неконтролируемый рост хранилища.
8.  **Используйте семантические конвенции OpenTelemetry:** Стандартные атрибуты (`http.method`, `db.system`, `exception.type`) обеспечивают совместимость UI, автоматические дашборды и корреляцию с Tempo/Grafana.

---

## Очистка окружения

```bash
# Остановка Docker Compose окружения
docker compose down -v

# Удаление данных ClickHouse (если использовался Docker)
docker volume rm jaeger_clickhouse_data

# Очистка in-memory данных (перезапуск контейнера)
docker restart jaeger

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test

# Очистка метрик Prometheus (если использовался локальный Prometheus)
rm -rf prometheus_data/

# Проверка отсутствия "подвисших" спанов в Kafka
kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group jaeger-ingester
```

**Рекомендуемые атрибуты OpenTelemetry для анализа:**

*   `http.method`, `http.status_code`, `http.target` — для анализа веб-трафика.
*   `db.system`, `db.statement`, `db.operation` — для диагностики баз данных.
*   `rpc.system`, `rpc.service`, `rpc.method` — для анализа взаимодействия микросервисов.
*   `exception.type`, `exception.message`, `exception.stacktrace` — для детального разбора ошибок.

**Смежные темы:**

* Детальное устройство системы: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Методы интеграции: **[Интеграция с Kubernetes](./jaeger_kubernetes_integration.md)**
* Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**
* Query API Reference: **[Query API Jaeger](./jaeger_query_api.md)**
* Миграция с v1 на v2: **[Миграция Jaeger v1 → v2](./jaeger_migration_v1_to_v2.md)**
* Capacity Planning: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
* Storage Deep Dive: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* HA и Disaster Recovery: **[High Availability и DR](./jaeger_high_availability.md)**
* Интеграция с Grafana: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**
* OTLP Configuration: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* eBPF и Auto-instrumentation: **[eBPF и автоматическая инструментация](./jaeger_ebpf_auto_instrumentation.md)**
* Multi-tenancy: **[Multi-tenancy и изоляция](./jaeger_multi_tenancy.md)**
* Security Hardening: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Основы трассировки: **[Traces Deep Dive](../Concepts/Observability_and_Monitoring/traces_deep_dive.md)**
