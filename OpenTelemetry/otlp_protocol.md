# OpenTelemetry: Протокол OTLP

## Определения

**OTLP (OpenTelemetry Protocol)** — это унифицированный протокол передачи данных, предназначенный для отправки телеметрических сигналов (трассировок, метрик, логов и профилей) из приложения в Collector или совместимый бэкенд. Он определяет стандартную схему данных на основе Protocol Buffers (Protobuf), что обеспечивает высокую эффективность, компактность и строгую типизацию. Protobuf обеспечивает обратную и прямую совместимость схем: старые потребители корректно обрабатывают сообщения с новыми полями, а новые — игнорируют отсутствующие, что критично для постепенного rolling update в production.

**Статус в августе 2026 года:**
- **Все сигналы (Traces, Metrics, Logs, Profiles):** Стабильны (GA) и поддерживаются в рамках версии OTLP v1.x.
- **CNCF Status:** Проект OpenTelemetry официально имеет статус **Graduated** (с мая 2026).
- **Приоритеты:** OTLP/Arrow признан основным стандартом для высоконагруженных систем (High-Load), а gRPC остается предпочтительным транспортом для межсервисного взаимодействия.

## Основные концепции

### Иерархия данных

OTLP использует общую вложенную структуру для всех сигналов, что позволяет эффективно передавать метаданные и снижать избыточность:

1.  **Resource:** Контейнер верхнего уровня. Описывает источник телеметрии через атрибуты (`service.name`, `host.name`, `k8s.pod.name`). Все данные внутри одного сообщения `Resource` принадлежат одной и той же логической сущности. Resource детекторы (Kubernetes, системные переменные среды, Docker) автоматически заполняют атрибуты, исключая ошибки ручного ввода.
2.  **Instrumentation Scope:** Группирует телеметрию по библиотеке или компоненту, который её сгенерировал (например, `io.opentelemetry.java-agent` версии `2.x`). Это позволяет отличать данные автоматической инструментации HTTP-библиотеки от ручных span или пользовательских метрик.
3.  **Signal Records:** Непосредственно записи данных (массив спанов, метрик, логов или профилей).

### Структура сигналов в OTLP

-   **Трассировки (Span):** Содержат имя, тип (`kind`), временные метки (start/end), атрибуты, события (`Events`) и ссылки (`Links`). Идентификаторы `trace_id` и `span_id` передаются как байтовые массивы. Span не содержит информации о родительском процессе — она передаётся через контекст.
-   **Метрики (Metric):** Включают точки данных (`DataPoint`) с временными метками и значениями. Поддерживаются типы `Gauge`, `Sum` (Monotonic/Non-monotonic), `Histogram` и `ExponentialHistogram` (Native Histograms). Кардинальность (количество уникальных комбинаций attribute values) напрямую влияет на объём хранения и стоимость — её необходимо контролировать на этапе проектирования.
-   **Логи (LogRecord):** Включают тело сообщения (`Body`), уровень важности (`Severity`), временную метку и контекст (`trace_id`/`span_id`) для бесшовной корреляции. Корреляция логов с трассировками не возникает сама по себе: она требует корректной передачи контекста, поддержки со стороны logging bridge или автоинструментации и возможности backend искать логи по `trace_id`.
-   **Профили (Profile):** Используют колончатую структуру для передачи данных непрерывного профилирования, обеспечивая минимальный оверхед при передаче стеков вызовов. OTel Profiles строится поверх формата, совместимого с `pprof`, и добавляет Resource, Instrumentation Scope, attributes и возможные ссылки на trace/span.

### Кодирование данных (Encoding)

-   **Protobuf (Бинарный):** Основной формат для Production. Использует бинарное представление, минимизируя трафик и нагрузку на CPU. Схема жёстко типизирована, что исключает ошибки десериализации на стороне получателя. Поддерживает streaming и частичные обновления схемы безbreaking changes.
-   **JSON (Текстовый):** Используется преимущественно для отладки, веб-инструментов и в Serverless-средах, где бинарный Protobuf затрудняет диагностику. Строго соответствует схеме Protobuf, но имеет больший размер и выше CPU cost на сериализацию/десериализацию.

**Почему Protobuf, а не JSON, стал стандартом:**
- Бинарное представление в 3–10 раз компактнее текстового JSON для типовых телеметрических нагрузок.
- Жёсткая схема исключает «тихие» ошибки парсинга, возникающие при несоответствии ключей или типов в JSON.
- Нативная поддержка streaming в gRPC позволяет отправлять данные частично, без ожидания формирования полного батча.

### Пример OTLP/HTTP (JSON)

Демонстрация иерархии для метрики типа `Gauge`:

```json
{
  "resourceMetrics": [
    {
      "resource": {
        "attributes": [
          {"key": "service.name", "value": {"stringValue": "payment-api"}}
        ]
      },
      "scopeMetrics": [
        {
          "scope": {"name": "http-server", "version": "1.0.0"},
          "metrics": [
            {
              "name": "http.server.active_requests",
              "gauge": {
                "dataPoints": [
                  {
                    "timeUnixNano": "1717428123000000000",
                    "asInt": "15",
                    "attributes": [{"key": "http.method", "value": {"stringValue": "POST"}}]
                  }
                ]
              }
            }
          ]
        }
      ]
    }
  ]
}
```

### Распространение контекста (Context Propagation)

OTLP обеспечивает передачу контекста наблюдаемости между узлами:
-   **W3C Trace Context:** Нативная поддержка заголовков `traceparent` и `tracestate` во всех транспортах. `traceparent` содержит `trace-id`, `parent-id` и `trace-flags` (флаг sampled). `tracestate` передаёт vendor-specific данные без нарушения совместимости.
-   **Baggage:** Передача пользовательских метаданных (key-value) сквозь всю цепочку вызовов. В 2026 году baggage по умолчанию ограничен 4 КБ на заголовок, чтобы предотвратить увеличение размера запросов и переполнение буферов прокси.

## Транспорт и протоколы

### Сравнение реализаций

| Характеристика | gRPC | HTTP/1.1 (JSON/Protobuf) | OTLP/Arrow |
| :--- | :--- | :--- | :--- |
| **Порт по умолчанию** | `4317` | `4318` | `4317` (через gRPC) |
| **Транспорт (L4/L7)** | HTTP/2 (Binary) | HTTP/1.1 (Text/Binary) | HTTP/2 (Columnar) |
| **Производительность** | Высокая | Средняя | Максимальная |
| **Сжатие** | gzip, snappy, zstd | gzip, deflate, snappy, zstd | Встроенное (Arrow IPC) |
| **Streaming** | Bidirectional | Нет | Нет |
| **Сценарий** | Backend-to-Backend | Web, Serverless, Proxy | High-Load, Collector-to-Collector |

**Почему gRPC использует HTTP/2 и почему L4-балансировка не подходит:**
gRPC строится на HTTP/2, который multiplexes несколько логических streams поверх одного TCP-соединения. Обычная L4-балансировка (TCP round-robin) распределяет соединения, но не отдельные streams внутри них. Если балансировщик не поддерживает HTTP/2 aware routing, все streams одного trace могут попасть на один экземпляр Collector, что приводит к неравномерной нагрузке и нарушению tail-based sampling. Решение — L7-балансировщики (Angie, Nginx, Envoy), которые терминируют HTTP/2 и распределяют запросы на уровне frames.

### OTLP/Arrow (OTAP)

**OTLP/Arrow** — это расширение протокола, использующее формат Apache Arrow для колоночного представления данных.
-   **Преимущества:** Обеспечивает до 10-кратного улучшения сжатия по сравнению со стандартным Protobuf за счёт группировки схожих записей (одтипные поля хранятся contiguous в памяти).
-   **Применение:** Рекомендуется при объемах трафика свыше 100 000 сигналов/сек или при передаче данных через дорогостоящие каналы связи. В 2026 году OTLP/Arrow поддерживается в Collector начиная с версии 0.112.0 и требует совместимого backend (например, ClickHouse с Arrow plugin или Dedicated OTLP/Arrow ingestion).

---

## Практические сценарии

### Сценарий 1: OTLP/gRPC с zstd-сжатием

Production-рекомендуемая конфигурация Collector с gRPC receiver и zstd compression:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size: 4mb
        max_connection_age: 1h
        max_connection_age_grace: 30s

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1536
    spike_limit_mib: 512
  batch:
    send_batch_size: 1024
    timeout: 10s

exporters:
  otlp:
    endpoint: "my-backend:4317"
    compression: zstd
    retry:
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 300s
    timeout: 10s
    sending_queue:
      size: 1000
      num_consumers: 4

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
```

**Валидация:**

```bash
# Проверка gRPC health endpoint
grpcurl -plaintext localhost:4317 list
# → opentelemetry.collector.otlp.v1.OTLPService

# Проверка метрик accepted spans
curl -s http://localhost:8888/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans_total{...} 1523

# Проверка queue size exporter
curl -s http://localhost:8888/metrics | grep otelcol_exporter_queue_size
# → otelcol_exporter_queue_size{...} 0

# Нагрузочный тест: отправка 1000 спанов
for i in $(seq 1 1000); do
  echo "{\"resourceSpans\":[]}" | \
    grpcurl -plaintext -d @ localhost:4317 opentelemetry.collector.otlp.v1.OTLPService/Export
done
```

### Сценарий 2: mTLS между SDK и Collector

Взаимная TLS-аутентификация защищает Collector от несанкционированной отправки телеметрии.

**Генерация сертификатов:**

```bash
# 1. Генерация CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes \
  -subj "/CN=OTel CA"

# 2. Сертификат сервера (Collector)
openssl req -newkey rsa:4096 -keyout server.key -out server.csr -nodes \
  -subj "/CN=otel-collector.observability.svc"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365

# 3. Клиентский сертификат
openssl req -newkey rsa:4096 -keyout client.key -out client.csr -nodes \
  -subj "/CN=otel-client"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out client.crt -days 365
```

**Конфигурация Collector:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        tls:
          cert_file: /etc/otel/certs/server.crt
          key_file: /etc/otel/certs/server.key
          client_ca_file: /etc/otel/certs/ca.crt
```

**Клиентская конфигурация (env vars):**

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector.observability.svc:4317
export OTEL_EXPORTER_OTLP_CERTIFICATE=/path/to/client.crt
export OTEL_EXPORTER_OTLP_CLIENT_KEY=/path/to/client.key
export OTEL_EXPORTER_OTLP_CLIENT_CA=/path/to/ca.crt
```

**Валидация:**

```bash
# Успешный mTLS handshake
openssl s_client -connect otel-collector.observability.svc:4317 \
  -cert client.crt -key client.key -CAfile ca.crt
# → Verify return code: 0 (ok)

# Без клиентского сертификата — ошибка
openssl s_client -connect otel-collector.observability.svc:4317
# → SSL routines:ssl3_get_record:wrong version number
```

### Сценарий 3: Балансировка нагрузки L7 для gRPC

gRPC использует долгоживущие HTTP/2 соединения. Обычная L4-балансировка (TCP) распределяет соединения, но не отдельные streams внутри них, что приводит к hotspot на отдельных экземплярах Collector.

**Решение:** L7-балансировщики (Angie, Nginx, Envoy), которые терминируют gRPC и распределяют отдельные запросы (streams) внутри одного соединения по разным узлам Collector.

**Пример конфигурации Nginx (stream module с gRPC health check):**

```nginx
stream {
  upstream otel_backend {
    zone otel_backend 64k;
    server otel-collector-1:4317;
    server otel-collector-2:4317;
    server otel-collector-3:4317;
  }

  server {
    listen 4317;
    proxy_pass otel_backend;
    proxy_timeout 10s;
    proxy_connect_timeout 2s;

    # Health check для удаления неработающих бэкендов
    health_check interval=5s fails=3 passes=2;
  }
}
```

**Валидация:**

```bash
# Проверка балансировки: отправка запросов на Nginx,
# в логах Collector должны быть распределены по разным экземплярам
grpcurl -plaintext nginx-lb:4317 list

# Проверка health check
curl http://nginx-lb:8080/health
```

### Сценарий 4: Обработка частичного успеха (Partial Success)

Если батч данных содержит некорректные записи (например, нарушение семантических конвенций или превышение `max_recv_msg_size`), Collector может вернуть статус `Partial Success`. SDK получает количество принятых и отклонённых записей.

-   **Действие SDK:** Современные SDK логируют ошибки, но не переотправляют батч повторно, чтобы избежать бесконечных циклов ретраев и дублирования корректных данных.
-   **Действие SRE:** При устойчивых `Partial Success` необходимо проверять логи Collector на предмет конкретных rejected records, исправлять источник (SDK или автоинструментацию) и только после этого переотправлять исправленные данные.

**Диагностика:**

```bash
# В логах Collector
grep -i "partial success" /var/log/otel/collector.log
# → RPC response: RECEIVED_PARTIAL_SUCCESS (accepted=100, rejected=2)

# В метриках
curl -s http://localhost:8888/metrics | grep otelcol_receiver_refused
# → otelcol_receiver_refused_spans_total{...} 2
```

### Сценарий 5: Обработка backpressure и переполнения очереди

`sending_queue` на стороне exporter защищает от потери данных при временной недоступности backend. При переполнении queue Collector начинает отклонять новые данные на уровне processor, создавая backpressure к receiver.

```yaml
exporters:
  otlp:
    endpoint: "my-backend:4317"
    sending_queue:
      size: 5000
      num_consumers: 10
    retry:
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 300s
```

**Мониторинг backpressure:**

```bash
# Размер очереди exporter
curl -s http://localhost:8888/metrics | grep otelcol_exporter_queue_size
# → otelcol_exporter_queue_size{...} 42 (норма)
# → otelcol_exporter_queue_size{...} 4900 (критично,接近 лимита)

# Отказанные отправки
curl -s http://localhost:8888/metrics | grep otelcol_exporter_send_failed
# → otelcol_exporter_send_failed_spans_total{...} 0 (норма)
# → otelcol_exporter_send_failed_spans_total{...} 156 (проблема)

# refused items на receiver (backpressure)
curl -s http://localhost:8888/metrics | grep otelcol_receiver_refused
```

### Сценарий 6: Нагрузочное тестирование OTLP endpoint

```bash
# Установка grpcurl (если не установлен)
# macOS: brew install grpcurl
# Linux: wget https://github.com/fullstorydev/grpcurl/releases/download/v1.9.1/grpcurl_1.9.1_linux_x86_64.tar.gz

# Тест доступности gRPC
grpcurl -plaintext localhost:4317 list
# → opentelemetry.collector.otlp.v1.OTLPService

# Нагрузочный тест: 10 000 запросов по 100 параллельных соединений
# Используем ghz (gRPC benchmarking tool)
# ghz --insecure --proto otlp.proto --call opentelemetry.collector.otlp.v1.OTLPService/Export \
#   -d '{"resourceSpans":[...]}' -c 100 -n 10000 localhost:4317

# Или через Python-скрипт с aiohttp/gRPC
python3 -c "
import asyncio
from grpc import insecure_channel

async def load_test():
    channel = insecure_channel('localhost:4317')
    # ... отправка тестовых данных
    pass
"
```

### Безопасность и аутентификация

-   **Шифрование:** Использование TLS/mTLS (порты 4317/4318) обязательно для всех внешних соединений. Внутренние соединения внутри доверенной сети могут использовать plaintext, но это следует явно документировать.
-   **Аутентификация:**
    -   API-ключи: заголовок `x-otlp-api-key`.
    -   JWT/OAuth2: заголовок `Authorization` с валидацией через `oidc` расширение в Collector.
    -   mTLS: клиентские сертификаты, проверяемые на стороне Collector через `client_ca_file`.
-   **Сжатие:** Рекомендуется `zstd` (лучший баланс скорости и степени сжатия в 2026 году) или `gzip`. `snappy` — для low-latency систем, где скорость сжатия важнее ratio.
-   **Ограничение размера сообщения:** Параметр `max_recv_msg_size` (по умолчанию 4 MB) защищает от DoS через oversized payload. В production рекомендуется явно устанавливать лимит, соответствующий реальному объёму батчей.

---

## Дополнительная информация

### Схема конфигурации Collector (2026)

Современная конфигурация с zstd compression и защитой от OOM:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        max_recv_msg_size: 4mb
        max_connection_age: 1h
        max_connection_age_grace: 30s
        tls:
          cert_file: /etc/otel/certs/server.crt
          key_file: /etc/otel/certs/server.key
          client_ca_file: /etc/otel/certs/ca.crt
      http:
        endpoint: 0.0.0.0:4318
        cors:
          allowed_origins: ["*"]

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 1536
    spike_limit_mib: 512
  batch:
    send_batch_size: 1024
    timeout: 10s

exporters:
  otlp:
    endpoint: "my-backend:4317"
    compression: zstd
    retry:
      initial_interval: 1s
      max_interval: 30s
      max_elapsed_time: 300s
    timeout: 10s
    sending_queue:
      size: 1000
      num_consumers: 4
    tls:
      ca_file: /etc/otel/ca.crt

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp]
```

### Рекомендации по настройке (Best Practices)

-   **Persistent Queues:** Используйте `sending_queue` с дисковым хранилищем (`file_storage`) на стороне экспортеров Collector для предотвращения потери данных при сбоях сети. Без `file_storage` очередь хранится только в оперативной памяти, и при перезапуске Collector все неподтверждённые данные теряются.
-   **Батчинг:** Всегда настраивайте `batch` процессор для уменьшения количества сетевых запросов и повышения эффективности сжатия. `send_batch_size` должен соответствовать среднему объёму данных, генерируемых за 10–30 секунд.
-   **Управление ресурсами:** Используйте `memory_limiter` процессор перед всеми остальными для предотвращения OOM при пиковых нагрузках. `limit_mib` должен оставлять запас под операционную систему и другие процессы (обычно 50–70% от доступной RAM на контейнер/хосте).
-   **TLS:** Включайте TLS на всех внешних endpoint. Используйте `min_version: TLS1.3` где возможно, чтобы исключить устаревшие и уязвимые версии протокола.
-   **Мониторинг:** Экспортируйте внутренние метрики Collector на порт `8888` и подключайте их к Prometheus. Критические метрики: `otelcol_receiver_refused_*`, `otelcol_exporter_queue_size`, `otelcol_exporter_send_failed_*`, `otelcol_processor_memory_limiter_refused_spans_total`.
-   **Сэмплирование:** Применяйте head-based sampling на стороне SDK для снижения объёма данных и tail-based sampling на Gateway для сохранения ошибок и медленных запросов. Для нескольких gateway-экземпляров все span одного trace должны попадать на один экземпляр (балансировка по trace ID).

### Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Connection refused на 4317** | gRPC receiver не запущен или endpoint неверный | Проверить `kubectl get pods -l app=otel-collector`, логи Collector, переменную `OTEL_EXPORTER_OTLP_ENDPOINT` |
| **TLS handshake failure** | Неверный сертификат или клиент не предоставляет сертификат при mTLS | Проверить `tls` блок в конфигурации, срок действия сертификатов (`openssl x509 -in server.crt -noout -dates`) |
| **High CPU на Collector** | Отсутствует compression или слишком большой `max_recv_msg_size` | Включить `zstd` compression, ограничить `max_recv_msg_size` |
| **Backpressure / OOM** | Отсутствует `memory_limiter` или `sending_queue` переполнен | Добавить `memory_limiter`, настроить `sending_queue.size`, увеличить `limit_mib` |
| **Частичный успех (Partial Success)** | Некорректные записи в батче (нарушение семантики, превышение размера) | Проверить rejected records в ответе, логировать на стороне SDK, исправить источник данных |
| **Спаны не поступают при высокой нагрузке** | `batch` processor переполнен или `send_batch_size` слишком большой | Уменьшить `send_batch_size`, увеличить `timeout`, добавить горизонтальное масштабирование Collector |
| **L4-балансировка даёт неравномерную нагрузку** | gRPC streaming распределяется по соединениям, а не по запросам | Перейти на L7-балансировщик с HTTP/2 aware routing |

### Ограничения и крайние случаи (Edge Cases)

-   **Очень большие сообщения:** При превышении `max_recv_msg_size` (по умолчанию 4 MB) gRPC возвращает `RESOURCE_EXHAUSTED`. Для трассировок это обычно означает слишком много атрибутов или вложенных событий в одном span. Решение — уменьшить детализацию или увеличить лимит с одновременным добавлением compression.
-   **Высокая кардинальность метрик:** OTLP не ограничивает количество уникальных временных рядов на стороне протокола, но backend и Collector имеют практические лимиты. Метрики с кардинальностью выше 10 000 series по одному metric name требуют отдельного проектирования.
-   **Сетевые разрывы:** При разрыве TCP-соединения gRPC-stream завершается с ошибкой `UNAVAILABLE`. SDK с настроенным retry policy автоматически переподключается. `sending_queue` на стороне Collector гарантирует доставку после восстановления связи, если backend временно недоступен.
-   **Смешанные версии SDK и Collector:** OTLP v1.x обратно совместим с v0.x receivers в пределах одного major-версии. При обновлении Collector сначала обновляют receivers/processors, затем exporters, проверяя совместимость с backend.

### Мониторинг Collector

Collector по умолчанию предоставляет внутренние Prometheus metrics на `8888` и пишет внутренние логи в `stderr`. Необходимо отслеживать:

-   `otelcol_receiver_accepted_*` и `otelcol_receiver_refused_*` — приток данных и backpressure.
-   `otelcol_processor_incoming_items` и `otelcol_processor_outgoing_items` — throughput processors.
-   `otelcol_exporter_queue_size` и `otelcol_exporter_queue_capacity` — заполнение очереди exporter.
-   `otelcol_exporter_enqueue_failed_*` и `otelcol_exporter_send_failed_*` — ошибки доставки.
-   `otelcol_processor_memory_limiter_refused_spans_total` — защита от OOM сработала.
-   CPU, RSS, heap и длительность export requests.

### Очистка окружения

```bash
# Удаление тестовых сертификатов
rm -f ca.crt ca.key server.crt server.key client.crt client.csr client.key

# Остановка тестового Collector
docker stop otel-collector && docker rm otel-collector

# Очистка очереди отправки (если использовался file_storage)
rm -rf /tmp/otel-sending-queue/*
```

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Архитектура и сигналы](./architecture_signals.md)
- [OTLP Configuration для Jaeger](../Jaeger/jaeger_otlp_configuration.md)
- [Безопасность в Kubernetes](./security_kubernetes.md)
- [Управление ресурсами](./resource_management.md)
- [Отказоустойчивость Collector](./collector_high_availability.md)
