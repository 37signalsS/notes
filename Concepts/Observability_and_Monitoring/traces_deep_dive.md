# Трассировки: глубокое погружение

## Определения

**Распределённая трассировка (Distributed Tracing)** — метод отслеживания полного пути выполнения запроса через все компоненты распределённой системы. В отличие от логов, фиксирующих атомарные события, трассировка фокусируется на связях (причинно-следственных и временных) между этими событиями. Визуализируется в виде каскадной диаграммы (диаграммы Ганта), иллюстрирующей жизненный цикл запроса.

**Назначение:**

- Выявление узких мест (bottlenecks) в распределённых микросервисных архитектурах.
- Анализ каскадных задержек (Long Tail Latency) и сложных отказов.
- Визуализация динамических зависимостей между сервисами и инфраструктурой.
- Реализация **Observability 2.0** — переход от простого сбора данных к контекстуальному анализу всей системы через сквозные идентификаторы.

**Ключевой принцип Observability:** Трассировки позволяют ответить на вопрос «Где именно?» (на каком этапе цепочки) возникла проблема, дополняя метрики («Что именно сломалось / сколько ошибок?») и логи («Что произошло внутри конкретного шага?»).

**См. также:** [Четыре столпа Observability](./four_pillars_of_observability.md) — фундаментальные концепции наблюдаемости.

## Базовые концепции

### Анатомия трассировки (OpenTelemetry Standard)

| Компонент | Описание | Пример / Техническая деталь |
| :--- | :--- | :--- |
| **Trace (Трассировка)** | Набор спанов, представляющих единый путь запроса. Имеет уникальный `trace_id` (16 байт). | Транзакция «Оформить заказ». |
| **Span (Спан)** | Единица работы (HTTP-вызов, SQL-запрос, выполнение функции). Имеет `span_id` (8 байт), время начала и завершения. | `POST /v1/billing/charge` |
| **Span Kind** | Тип спана, определяющий его роль в распределенной системе. | `Server`, `Client`, `Producer`, `Consumer`, `Internal`. |
| **Attributes (Атрибуты)** | Метаданные спана (ключ=значение). Обязательны для фильтрации и аналитики. | `http.status_code=500`, `db.system=postgresql`. |
| **Events (События)** | Временные метки внутри спана для фиксации атомарных действий или ошибок. | `exception.stacktrace`, `cache.hit`. |
| **Span Links (Связи)** | Механизм соединения независимых трейсов. Критичен для асинхронности (Kafka, Batch). | Связь между `producer-trace` и `consumer-trace`. |

### Типы спанов (Span Kind)

Правильная типизация спанов критична для построения корректной топологии сервисов:
- **Server:** Спан на стороне приемника синхронного запроса (например, входящий HTTP в API).
- **Client:** Спан на стороне отправителя синхронного запроса (например, вызов внешней БД или API).
- **Producer:** Спан отправки сообщения в асинхронную очередь (Kafka, RabbitMQ).
- **Consumer:** Спан получения и обработки сообщения из очереди.
- **Internal:** Внутренняя операция процесса (вызов тяжелой функции, вычисления).

### Распространение контекста (Context Propagation)

Процесс передачи `trace_id` и `span_id` между службами через заголовки протоколов. Без этого невозможно восстановить дерево вызовов.

**Протоколы и стандарты 2026 года:**
- **W3C Trace Context:** Отраслевой стандарт (заголовок `traceparent`). Состоит из четырех полей: `version-traceid-parentid-flags`.
- **Baggage:** Механизм передачи пользовательских метаданных (например, `customer_tier=gold`) через всю цепочку вызовов без обращений к БД в каждом сервисе. Влияет на безопасность, так как Baggage передается между границами доверия.
- **OTLP/Arrow:** Высокоэффективный транспорт, использующий Apache Arrow для сжатия телеметрии. В 2026 году позволяет снизить нагрузку на сеть в 10 раз при передаче трейсов с миллионами спанов.

### Архитектура сбора трассировок

```bash
Приложение (SDK) → Агент (OTel Collector / eBPF) → Транспорт (Kafka) → Обработка → Хранилище (Tempo/ClickHouse)
```

**Backpressure и сброс данных:**
При переполнении буферов агента или коллектора (например, всплеск трафика или медленная запись в БД) спаны начинают отбрасываться.
- **Дроп на уровне SDK:** Приложение может замедляться, если SDK настроен на блокирующую отправку (не рекомендуется).
- **Дроп на уровне Collector:** Предпочтительный вариант. Метрики `spans_dropped_total` позволяют отследить потерю видимости.

### Сэмплирование (Sampling)

В высоконагруженных системах запись 100% данных невозможна из-за затрат на IO и хранение.

1.  **Head-based Sampling:** Решение принимается в точке входа (например, сохранять 1% трейсов).
    - **Probabilistic:** Случайный отбор по хешу `trace_id`.
    - **Rate Limiting:** Ограничение количества трейсов в секунду.
2.  **Tail-based Sampling (Рекомендуется):** Решение принимается после завершения всего трейса (на уровне Collector). Позволяет сохранить 100% ошибок и медленных запросов, отбрасывая «здоровые» данные. Требует значительной RAM на коллекторе для ожидания завершения всех спанов трейса.
3.  **Adaptive Sampling:** Автоматическая регулировка вероятности сэмплирования на основе текущего RPS и целевого объема данных.

### Инструментация: eBPF vs SDK

| Характеристика | OpenTelemetry SDK | eBPF (OBI) |
| :--- | :--- | :--- |
| **Сложность внедрения** | Высокая (требует изменения кода/библиотек) | Нулевая (Zero-code) |
| **Детализация** | Максимальная (внутренние бизнес-события) | Средняя (сетевые вызовы, системные вызовы) |
| **Производительность** | Нагрузка на рантайм приложения | Минимальная нагрузка на ядро ОС |
| **Видимость TLS** | Нативная | Требует внедрения в OpenSSL/Go-tls через uprobes |

---

## Преимущества трассировки

1.  **Анализ критического пути (Critical Path Analysis):** Позволяет определить, какая именно часть цепочки вызовов напрямую влияет на итоговое время ответа. Оптимизация спанов вне критического пути не ускорит ответ пользователю.
2.  **Диагностика Long Tail Latency (p99):** Трассировка — единственный способ понять, почему 1% пользователей ждет ответа 10 секунд, когда среднее время (p50) составляет 100мс.
3.  **Zero-code Tracing (eBPF):** В 2026 году стандарт eBPF (OpenTelemetry OBI) позволяет получать трейсы из скомпилированных языков (Go, Rust, C++) без изменения кода и sidecar-контейнеров, включая видимость TLS-трафика.
4.  **Trace-based Testing:** Использование трассировочных данных для автоматической проверки архитектурных инвариантов (например, «этот метод не должен делать более 2 запросов к БД»).

---

## Практические сценарии

### Сценарий 1: Диагностика задержек через TraceQL (Tempo 3.0)

**Задача:** Найти медленные запросы к Postgres, где общее время трейса > 2с.

**Запрос в Grafana:**
```traceql
{ duration > 2s } >> { span.db.system = "postgresql" && duration > 500ms }
```
**Действия:**
1. Выбрать трейс и изучить атрибуты спана: `db.statement` (текст SQL-запроса).
2. Проверить `db.wait_time` для определения — проблема в выполнении запроса или в ожидании свободного соединения из пула.

### Сценарий 2: Анализ асинхронного сбоя в Kafka через Span Links

**Задача:** Найти причину, почему сообщение было отправлено, но не обработано.

**Действия:**
1. Найти трейс продюсера (отправка сообщения).
2. В UI Jaeger v2 или Tempo использовать раздел **Links** для перехода в связанный трейс консьюмера.
3. В трейсе консьюмера найти `Span Event` с типом `exception`, возникший при десериализации данных.

### Сценарий 3: Настройка Tail-sampling в OTel Collector

**Задача:** Сохранять все ошибки и запросы дольше 2 секунд, для остального — сэмплировать 1%.

**Конфигурация:**
```yaml
processors:
  tail_sampling:
    policies:
      - name: errors-policy
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow-policy
        type: latency
        latency: {threshold_ms: 2000}
      - name: probabilistic-policy
        type: probabilistic
        probabilistic: {sampling_percentage: 1}
```

**Валидация:**
1. Вызвать ошибку в приложении. Убедиться, что трейс доступен в хранилище, несмотря на низкий общий процент сэмплирования.
2. Вызвать искусственную задержку (> 2с). Убедиться, что трейс сохранен.
3. Проверить метрики коллектора `processor_tail_sampling_sampling_decision_latency` для оценки нагрузки на CPU.

### Сценарий 4: Генерация метрик на основе спанов (Span-to-Metrics)

**Задача:** Создать метрику Latency для конкретной SQL-операции без изменения кода приложения.

**Решение:** Использование процессора `spanmetrics` в OTel Collector.

**Конфигурация:**
```yaml
processors:
  spanmetrics:
    metrics_exporter: prometheus
    dimensions:
      - name: db.system
      - name: db.operation
```

**Результат:** Коллектор автоматически генерирует гистограммы `duration` и счетчики `calls`, обогащенные указанными атрибутами. Это позволяет строить графики производительности БД напрямую из потока трейсов.

### Сценарий 5: Tenant-aware Routing через Baggage

**Задача:** Пробросить идентификатор клиента (`tenant_id`) через 10 микросервисов для отладки конкретного пользователя без изменения сигнатур функций.

**Действия:**
1. На входе (Gateway) добавить Baggage: `tracer.set_baggage("tenant_id", "client_abc")`.
2. В любом промежуточном сервисе извлечь значение: `context.get_baggage("tenant_id")`.
3. Использовать это значение для добавления атрибута к спану или для маршрутизации логов.

**Внимание:** Baggage передается в заголовках HTTP (`baggage: tenant_id=client_abc`), поэтому избегайте хранения в нем чувствительных данных (секретов).

### Сценарий 6: Мониторинг OTel Collector и предотвращение потери спанов

**Задача:** Обеспечить отказоустойчивость пайплайна сбора трассировок и предотвратить потерю данных.

**Ключевые метрики OTel Collector для мета-мониторинга:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `otelcol_processor_in_spans` | Входящие спаны | Снижение > 50% |
| `otelcol_exporter_sent_spans` | Отправленные спаны | Снижение > 30% |
| `otelcol_exporter_send_failed_spans` | Ошибки отправки | > 0 за 5 минут |
| `otelcol_processor_dropped_spans` | Отброшенные спаны | > 0 (critical) |
| `otelcol_receiver_refused_spans` | Отказанные спаны | > 0 за 5 минут |
| `otelcol_processor_batch_batch_size` | Размер батча | Стабильно < send_batch_size |

**Алерт-правило для Prometheus:**
```yaml
groups:
- name: otel-collector-meta-monitoring
  rules:
  - alert: OtelCollectorSpansDropped
    expr: rate(otelcol_processor_dropped_spans[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "OTel Collector is dropping spans - data loss"
      
  - alert: OtelCollectorExportFailed
    expr: rate(otelcol_exporter_send_failed_spans[5m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "OTel Collector export failures detected"
      
  - alert: OtelCollectorMemoryHigh
    expr: otelcol_process_runtime_memory_alloc_bytes / otelcol_process_runtime_memory_alloc_bytes > 0.8
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "OTel Collector memory usage > 80%"
```

**Конфигурация OTel Collector с memory_limiter и tail_sampling:**
```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 4000
    spike_limit_mib: 500
    
  tail_sampling:
    decision_wait: 10s
    num_traces: 100000
    policies:
      - name: errors-policy
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow-policy
        type: latency
        latency: {threshold_ms: 2000}
      - name: probabilistic-policy
        type: probabilistic
        probabilistic: {sampling_percentage: 1}

exporters:
  otlp/tempo:
    endpoint: tempo.observability.svc:4317
    tls:
      insecure: true
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, tail_sampling, batch]
      exporters: [otlp/tempo]
```

### Сценарий 7: Correlation ID для полной трассировки запроса

**Задача:** Реализовать сквозную трассировку от HTTP-запроса до SQL-запроса и обратно, обеспечивая корреляцию логов, метрик и трассировок.

**Реализация на Go:**
```go
package middleware

import (
    "context"
    "net/http"
    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/trace"
)

func TracingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx := otel.GetTextMapPropagator().Extract(r.Context(), r.Header)
        
        spanName := r.Method + " " + r.URL.Path
        ctx, span := otel.Tracer("http-server").Start(ctx, spanName,
            trace.WithAttributes(
                attribute.String("http.method", r.Method),
                attribute.String("http.url", r.URL.String()),
                attribute.String("http.host", r.Host),
                attribute.String("http.user_agent", r.UserAgent()),
            ),
        )
        defer span.End()
        
        // Добавляем trace_id в логи
        traceID := span.SpanContext().TraceID().String()
        logger := log.With("trace_id", traceID)
        
        // Передаем контекст дальше
        ctx = context.WithValue(ctx, "logger", logger)
        next.ServeHTTP(w, r.WithContext(ctx))
    })
}
```

**Результат:** Каждый HTTP-запрос получает уникальный `trace_id`, который:
1. Передается в дочерние сервисы через заголовки
2. Добавляется в логи для корреляции
3. Связывает метрики с конкретными запросами через Exemplars

### Сценарий 8: Настройка Jaeger с ClickHouse для высоконагруженных систем

**Задача:** Обеспечить сбор и хранение трассировок при нагрузке > 100K spans/сек.

**Преимущества ClickHouse перед Elasticsearch:**
- **Производительность записи:** в 10-100 раз быстрее
- **Сжатие данных:** в 5-10 раз лучше
- **Стоимость хранения:** в 3-5 раз дешевле
- **Скорость запросов:** للمногомерных аналитических запросов

**Конфигурация Jaeger v2 с ClickHouse:**
```yaml
# docker-compose.yml
version: '3.8'
services:
  jaeger:
    image: jaegertracing/jaeger:2.0
    environment:
      - CASSANDRA_SERVERS=cassandra
      - CASSANDRA_KEYSPACE=jaeger_v2
      - SPAN_STORAGE_TYPE=cassandra
      - COLLECTOR_OTLP_ENABLED=true
    ports:
      - "4317:4317"   # OTLP gRPC
      - "4318:4318"   # OTLP HTTP
      - "16686:16686" # UI
    depends_on:
      - cassandra

  cassandra:
    image: cassandra:4.1
    volumes:
      - cassandra-data:/var/lib/cassandra
    environment:
      - CASSANDRA_CLUSTER_NAME=jaeger
      - CASSANDRA_DC=dc1
      - CASSANDRA_RACK=rack1

volumes:
  cassandra-data:
```

**Конфигурация для ClickHouse (высокая производительность):**
```yaml
# jaeger-config.yaml
span_storage:
  type: clickhouse
  clickhouse:
    endpoint: clickhouse:9000
    database: jaeger
    max_open_connections: 100
    max_execution_time: 30s
    
collector:
  otlp:
    enabled: true
    grpc:
      host_port: :4317
    http:
      host_port: :4318
```

### Сценарий 9: Автоматическая инструментация Java-приложений с OTel Agent

**Задача:** Быстро добавить трассировки в существующее Java-приложение без изменения кода.

**Шаги:**
1. Скачать OTel Java Agent:
```bash
wget https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar
```

2. Запустить приложение с агентом:
```bash
java -javaagent:opentelemetry-javaagent.jar \
     -Dotel.service.name=my-java-service \
     -Dotel.exporter.otlp.endpoint=http://otel-collector:4317 \
     -Dotel.resource.attributes=deployment.environment=production \
     -jar my-application.jar
```

3. Конфигурация через environment variables:
```bash
# Включение автоматической инструментации
OTEL_JAVAAGENT_ENABLED=true

# Экспорт в OTLP
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Дополнительные атрибуты
OTEL_RESOURCE_ATTRIBUTES=service.version=1.0.0,deployment.region=eu-west-1

# Сэмплирование
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1  # 10% сэмплирование
```

**Результат:** Автоматически инструментируются:
- HTTP-клиенты (OkHttp, Apache HttpClient, RestTemplate)
- HTTP-серверы (Spring Boot, Jersey)
- JDBC-драйверы
- Клиенты очередей (Kafka, RabbitMQ)
- Redis, MongoDB, Elasticsearch

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Разорванные трейсы** | Отсутствие передачи заголовков `traceparent` в одном из узлов | Проверить наличие Propagators в SDK всех сервисов. Проверить конфигурацию Ingress/Proxy (должны пропускать заголовки). |
| **Clock Skew (Сдвиг времени)** | Рассинхронизация NTP на разных серверах | Спаны могут отображаться в будущем или иметь отрицательную длительность. Требуется строгая синхронизация времени через `chrony`. |
| **Высокая нагрузка на сеть** | Слишком большой объем атрибутов или отсутствие сжатия | Использовать OTLP/Arrow. Ограничить размер атрибутов (например, не писать полные тела запросов/ответов в теги). |
| **Missing Spans (Пропуски)** | Переполнение буфера (Backpressure) | Увеличить `send_batch_size` в коллекторе, проверить метрики `spans_dropped_total`. |
| **Высокая задержка трассировки** | Медленная запись в хранилище (Tempo/ClickHouse) | Проверить IOPS хранилища, оптимизировать batch processor, увеличить параллелизм записи. |
| **Дублирование спанов** | Несколько Collector'ов отправляют данные без идемпотентности | Включить дедупликацию на уровне БД, использовать Kafka с ключом `trace_id`, настроить идемпотентность Consumer. |
| **Trace_id не коррелирует с логами** | Отсутствие передачи trace_id в логах | Убедиться, что SDK добавляет trace_id в логи. Использовать structured logging с полем `trace_id`. |
| **Высокое потребление RAM в Collector** | Tail-sampling с большими объемами данных | Увеличить `limit_mib` в `memory_limiter`, уменьшить `num_traces`, оптимизировать политики сэмплирования. |
| **Spans не доходят до хранилища** | Проблемы с сетью или TLS | Проверить маршрутизацию, сертификаты, логи Collector. Использовать `insecure: true` для тестов. |
| **Медленные запросы TraceQL** | Неоптимизированные индексы или слишком большие диапазоны | Ограничивать временные диапазоны, использовать индексы по сервисам/операциям, оптимизировать схему ClickHouse. |
| **Кардинальность атрибутов** | Слишком много уникальных значений атрибутов | Ограничить cardinality, использовать family-атрибуты, оптимизировать семантические конвенции. |
| **Проблемы с eBPF инструментацией** | Несовместимость версий ядра или отсутствие поддержки | Проверить версию ядра (>= 5.10), включить BTF, проверить permissions для eBPF. |

### Диагностические команды

```bash
# OTel Collector: проверка метрик
curl -s http://localhost:8888/metrics | grep "otelcol"

# Jaeger: проверка состояния
curl -s http://localhost:16686/api/services | jq '.data'

# Tempo: проверка готовности
curl -s http://localhost:3200/ready

# Prometheus: проверка целей
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="otel-collector")'

# ClickHouse: проверка подключения
clickhouse-client --query "SELECT count() FROM jaeger.spans WHERE timestamp > now() - INTERVAL 1 HOUR"

# Kafka: проверка топика
kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic jaeger-spans

# kubectl: диагностика OTel Collector
kubectl get pods -n observability -l app=otel-collector
kubectl logs -n observability -l app=otel-collector --tail=100

# Проверка заголовков traceparent
curl -H "traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01" \
     http://localhost:8080/api/endpoint
```

## Дополнительная информация

### Инструментарий 2026

| Инструмент | Роль | Особенности 2026 |
| :--- | :--- | :--- |
| **Grafana Tempo 3.0** | Хранилище | Архитектура **Decoupled Path** (RF1 через Kafka-buffer), поддержка TraceQL Metrics в реальном времени. |
| **Jaeger v2.20+** | Бэкенд + UI | Полностью построен на **OTel Collector Framework**. Рекомендуемый бэкенд для масштабирования — **ClickHouse**. |
| **OpenTelemetry eBPF (OBI)** | Инструментация | Zero-code сбор данных с уровня ядра. Видимость сетевых вызовов без участия SDK. |
| **Tracetest** | Тестирование | Автоматизация тестов на основе распределенных трассировок. |

### Язык запросов TraceQL (Tempo)

| Запрос | Описание |
| :--- | :--- |
| `{.duration > 1s}` | Трейсы дольше 1 сек |
| `{status = error}` | Все трейсы с ошибками |
| `{span.http.method = "POST"}` | Трейсы с POST-запросами |
| `{resource.service.name = "auth-svc"}` | Фильтр по конкретному сервису |

### Лучшие практики

1.  **Семантические конвенции:** Строго используйте [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/) для имен атрибутов (например, `http.response.status_code`). Это критично для корреляции между инструментами.
2.  **Context Propagation везде:** Убедитесь, что `traceparent` передается через все посредники (Proxy, Load Balancers, Queues).
3.  **Автоматическое инструментирование:** Используйте OTel Java Agent или Python Auto-instrumentation для 80% задач, но вручную размечайте критические бизнес-операции внутри спанов.
4.  **ClickHouse для трейсов:** При объемах > 1 ТБ/день ClickHouse в Jaeger v2 обеспечивает кратно лучшую производительность поиска и записи по сравнению с Elasticsearch.
5.  **Размер атрибутов:** Ограничивайте размер атрибутов (не более 1 КБ на атрибут). Не записывайте полные тела запросов/ответов - используйте только идентификаторы или первые N символов.
6.  **Иерархия атрибутов:** Используйте namespace для атрибутов (например, `app.user.id` вместо `user_id`). Это упрощает фильтрацию и агрегацию.
7.  **Мониторинг буферов:** Регулярно проверяйте метрики `spans_dropped_total` и `buffer_utilization`. Настраивайте алерты при превышении порогов.
8.  **Версионирование схем:** Используйте versioning для атрибутов (например, `http.request.version: 2`). Это помогает при миграциях.
9.  **Тестирование инструментации:** Регулярно проверяйте, что спаны корректно создаются и связаны. Используйте Trace-based testing для автоматизации.
10. **Документирование:** Ведите каталог спанов и их атрибутов. Это критично для командной работы и onboarding новых инженеров.

### Чек-лист по внедрению трассировок

- [ ] Определены критические пути запросов для трассировки
- [ ] Настроен OTel Collector с memory_limiter и tail_sampling
- [ ] Выбрано хранилище (Tempo, Jaeger с ClickHouse)
- [ ] Настроена Context Propagation во всех сервисах
- [ ] Интегрированы трассировки с логами (trace_id в логах)
- [ ] Настроен мониторинг пайплайна трассировок
- [ ] Определены политики сэмплирования для разных сервисов
- [ ] Настроены алерты на потерю спанов
- [ ] Документированы семантические конвенции для команды
- [ ] Проведено обучение команды работе с трассировками

### Архитектурные паттерны трассировок

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Agent-per-host** | OTel Collector на каждой ноде | Kubernetes DaemonSet, bare-metal серверы |
| **Sidecar** | Collector рядом с каждым подом | Kubernetes, высокая изоляция |
| **Gateway** | Централизованный Collector | Малые системы, простые архитектуры |
| **Agent + Gateway** | Комбинация для масштабирования | Крупные системы, много сервисов |

### Стоимость и производительность

| Метрика | SDK | eBPF | Влияние |
| :--- | :--- | :--- | :--- |
| **CPU overhead** | 1-5% | 0.1-1% | Минимальное при правильной настройке |
| **Memory overhead** | 10-50 МБ | 1-5 МБ | Зависит от объема данных |
| **Network overhead** | 10-100 КБ/сек | 1-10 КБ/сек | Сжатие данных критично |
| **Storage requirements** | 10-100 ГБ/день | 10-100 ГБ/день | Зависит от сэмплирования |

### См. также

- **[OpenTelemetry: обзор](../../OpenTelemetry/opentelemetry_overview.md)** — база современных систем телеметрии.
- **[Tempo: обзор](../../Tempo/index.md)** — распределённое хранилище трассировок.
- **[Метрики: детали](./metrics_deep_dive.md)** — переход от графиков к трейсам через Exemplars.
- **[Jaeger: обзор](../../Jaeger/jaeger_overview.md)** — распределённая система трассировки.
- **[OTLP Protocol](../../OpenTelemetry/otlp_protocol.md)** — протокол передачи телеметрии.
- **[Инструментация SDK](../../OpenTelemetry/instrumentation_sdk.md)** — руководство по инструментации.
- **[Архитектура сигналов](../../OpenTelemetry/architecture_signals.md)** — связь метрик, логов и трассировок.
