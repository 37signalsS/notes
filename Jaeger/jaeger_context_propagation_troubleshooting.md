# Диагностика и устранение разрывов трасс (Broken Traces & Context Propagation)

**Актуально для:** Jaeger v2.x / OpenTelemetry SDK 1.x / W3C Trace Context / Kubernetes 1.28–1.32

> **Статус:** Руководство описывает инженерные методы расследования, локализации и предотвращения разрывов контекста трассировки (**Broken Traces**) и появления изолированных спанов (**Orphan Spans**) в **Jaeger v2**. Рассматриваются on-premise и bare-metal инфраструктуры (Linux, systemd, Kubernetes, Nginx, Kafka, PostgreSQL) без вендорных облачных решений и AI-инструментов.

**Распространение контекста (Context Propagation)** — фундаментальный механизм распределенной трассировки, связывающий независимые сетевые вызовы микросервисов, фоновые очереди и обращения к базам данных в единый ациклический граф (DAG). В реальной production-эксплуатации разрыв контекста приводит к потере видимости транзакций: в Jaeger UI вместо сквозного дерева вызовов отображаются десятки несвязанных одиночных спанов, что делает невозможным локализацию задержек на критическом пути и расчет метрик MTTR.

Смежные документы:
* Общие архитектурные принципы: **[Обзор Jaeger](./jaeger_overview.md)**
* Анализ задержек и критического пути: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Настройка транспортных приемников OTLP: **[Конфигурация OTLP для Jaeger](./jaeger_otlp_configuration.md)**
* Интеграция с Ingress и Service Mesh: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* Наблюдаемость СУБД: **[PostgreSQL Observability](../Databases/PostgreSQL/Operations/observability.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Context Propagation (Распространение контекста)** | Процесс упаковки, передачи через транспортный протокол (сеть, очередь) и извлечения метаданных трассировки (`trace_id`, `span_id`, флаги) на принимающей стороне |
| **W3C Trace Context** | Индустриальный стандарт IETF/W3C для передачи контекста через HTTP-заголовки `traceparent` и `tracestate` |
| **`traceparent`** | Структурированный заголовок формата `version-trace_id-parent_id-trace_flags` (например: `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`) |
| **`tracestate`** | Непрозрачный заголовок формата `vendor1=value1,vendor2=value2` для передачи вендор-специфичных метаданных маршрутизации без искажения глобального `trace_id` |
| **Orphan Span (Осиротевший спан)** | Спан, не имеющий родительского идентификатора (`parent_span_id` отсутствует или равен 0), либо спан, чей родительский спан не найден в хранилище |
| **Broken Trace (Разорванная трасса)** | Распределенная транзакция, распавшаяся на два или более изолированных несвязанных графа из-за потери заголовков контекста на одном из участков пути |
| **Baggage** | Механизм сквозной передачи произвольных пар ключ-значение (контекста транзакции, например `tenant_id`, `user_tier`) через всю цепочку вызовов в заголовке `baggage` |
| **Carrier** | Сетевая структура данных или протокольный конверт (HTTP Headers, gRPC Metadata, Kafka Record Headers), в который сериализуется контекст трассировки |
| **Injector / Extractor** | Компоненты OpenTelemetry SDK: Injector записывает контекст в Carrier перед отправкой запроса; Extractor считывает и восстанавливает контекст из входящего Carrier |
| **Composite Propagator** | Составной конфигурационный пропогатор SDK, объединяющий несколько форматов (например, `tracecontext,baggage,b3,jaeger`) для обеспечения обратной совместимости |
| **Span Links** | Семантическая связь между спанами без строгих отношений «родитель-потомок». Обязательна для очередей сообщений (Kafka, RabbitMQ) во избежание искажения сквозного времени ответа |
| **Clock Skew (Сдвиг часов)** | Рассинхронизация физических системных часов между серверами, приводящая к искажению временной шкалы (дочерний спан визуально начинается раньше родительского) |
| **SQLCommenter** | Стандарт OpenTelemetry для внедрения контекста трассировки (`traceparent`, `service.name`) прямо в текст SQL-запроса в виде комментариев `/* ... */` |

---

## Базовые концепции и архитектура распространения контекста

### 1. Анатомия заголовка W3C Trace Context (`traceparent`)

Заголовок `traceparent` строго стандартизирован и имеет длину ровно 55 символов в шестнадцатеричной кодировке ASCII, разделенных дефисами:

```
  00 - 4bf92f3577b34da6a3ce929d0e0e4736 - 00f067aa0ba902b7 - 01
  ──   ────────────────────────────────   ────────────────   ──
  │                   │                          │           │
  │                   │                          │           └─ Trace Flags (2 hex = 8 бит)
  │                   │                          │              01: Sampled (записывать)
  │                   │                          │              00: Not Sampled
  │                   │                          └─ Parent ID / Span ID (16 hex = 64 бит)
  │                   └─ Trace ID (32 hex = 128 бит)
  └─ Version (2 hex): "00" (текущая версия стандарта)
```

Правила парсинга в production:
* Если версия `00`, длина строки обязана составлять строго 55 символов.
* Все нули в `trace_id` (`00000000000000000000000000000000`) или `parent_id` (`0000000000000000`) являются недопустимыми значениями; при получении таких значений SDK обязан сбросить контекст и сгенерировать новый `trace_id`.
* Младший бит `Trace Flags` (`01`) указывает, что данная трасса была отобрана для сохранения сэмплировщиком (Recorded/Sampled).

---

### 2. Типовые причины разрыва трасс в Production

Разрыв распределенных трасс на изолированные фрагменты возникает в пяти классических точках архитектуры:

```
[Пользователь]
      │
      ▼ (traceparent: 00-aaa-111-01)
┌─────────────┐
│ API Gateway │ ──► ПРОБЛЕМА 1: Прокси сбрасывает заголовки или генерирует новый TraceID
└──────┬──────┘
       │ (Заголовки утеряны -> генерируется новый TraceID: 00-bbb-222-01)
       ▼
┌─────────────┐
│ Service A   │ ──► ПРОБЛЕМА 2: Код сервиса запускает горутину/тред с context.Background()
└──────┬──────┘
       │
       ▼ (Kafka)
┌─────────────┐
│ Kafka Topic │ ──► ПРОБЛЕМА 3: Продюсер не записал headers, либо консьюмер связал через Child-Of
└──────┬──────┘
       │
       ▼
┌─────────────┐
│ Service B   │ ──► ПРОБЛЕМА 4: Несовпадение форматов (Сервис A шлет W3C, Сервис B ждет B3)
└──────┬──────┘
       │
       ▼ (SQL)
┌─────────────┐
│ PostgreSQL  │ ──► ПРОБЛЕМА 5: Запросы к БД не содержат метаданных (нет SQLCommenter)
└─────────────┘
```

#### Причина 1: Сброс заголовков на Ingress / Reverse Proxy
Многие конфигурации Nginx или балансировщиков по умолчанию перезаписывают заголовки трассировки, либо модули генерации `X-Request-ID` перезаписывают входной `trace_id`. В результате входящий запрос от внешнего клиента получает новый `trace_id` на шлюзе, а трасса клиента отсекается.

#### Причина 2: Асинхронные пулы потоков и утеря контекста рантайма
Внутренняя среда исполнения приложений хранит контекст в структурах памяти:
* **Go:** Передача `context.Context`. Если разработчик пишет `go doAsyncWork(context.Background())` вместо передачи родительского `ctx`, создаваемый внутри горутины спан теряет родителя и становится отдельным `Root Span` с новым `trace_id`.
* **Java:** Контекст хранится в `ThreadLocal`. При передаче задачи в пул потоков (`ExecutorService`, `ForkJoinPool` или реактивные пайплайны Project Reactor / Spring WebFlux) `ThreadLocal` не копируется в рабочий поток по умолчанию без использования `Context.wrap()`.

#### Причина 3: Некорректная обработка очередей сообщений (Kafka / RabbitMQ)
В брокерах очередей контекст должен внедряться в бинарные заголовки сообщений (`RecordHeaders`). Типовые ошибки:
1. Консьюмер вычитывает сообщения батчем (100 штук) и создает один спан обработки, забывая связать его с индивидуальными `traceparent` каждого сообщения из пачки.
2. Использование отношения `Child-Of` для асинхронного консьюмера: если сообщение обработано через 30 минут, дочерний спан растягивает сквозной таймлайн родительского HTTP-запроса до 30 минут, искажая аналитику задержек. Правильное решение — семантическая связь `Span Links` (`Follows-From`).

#### Причина 4: Несовпадение протоколов пропогации (Format Mismatch)
Legacy-сервисы могут использовать устаревший формат Zipkin B3 (`X-B3-TraceId`, `X-B3-SpanId`) или исторический заголовок Jaeger (`uber-trace-id`). Если upstream-сервис отправляет W3C `traceparent`, а downstream-сервис ожидает `uber-trace-id`, downstream не находит знакомого заголовка и начинает новую трассу.

#### Причина 5: Рассинхронизация времени серверов (Clock Skew)
Если сервер сервиса B спешит на 500 мс относительно сервера сервиса A, в Jaeger UI дочерний спан B визуально начнется **раньше**, чем родительский спан A, либо получит отрицательную задержку.

---

## Практические сценарии диагностики и устранения

### Сценарий 1: Настройка Ingress-контроллеров для сохранения и генерации `traceparent`

**Задача:** Сконфигурировать Nginx / Ingress-NGINX так, чтобы:
1. Если клиент пришел с валидным `traceparent` — проксировать его в upstream без модификации.
2. Если клиент пришел без заголовка — автоматически генерировать валидный W3C `traceparent` на входе.
3. Пробрасывать `trace_id` в логи доступа Nginx для сквозной корреляции с Loki/Promtail.

#### 1. Модификация конфигурации Nginx (`nginx.conf`)

```nginx
# В секции http определяем генерацию traceparent при его отсутствии
map $http_traceparent $incoming_traceparent {
    default $http_traceparent;
    # Если заголовок отсутствует или пуст - генерируем новый W3C traceparent
    # 00 (версия) - 32 hex trace_id - 16 hex span_id - 01 (sampled)
    ""      "00-$request_id$request_id-0000000000000001-01";
}

# Извлекаем чистый trace_id для логов
map $incoming_traceparent $extracted_trace_id {
    "~*^00-([0-9a-f]{32})-" $1;
    default                 "-";
}

log_format json_analytics escape=json '{'
    '"time_local":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"request":"$request",'
    '"status": "$status",'
    '"body_bytes_sent":"$body_bytes_sent",'
    '"request_time":"$request_time",'
    '"trace_id":"$extracted_trace_id",'
    '"traceparent":"$incoming_traceparent"'
'}';

server {
    listen 80;
    server_name api.internal.net;
    access_log /var/log/nginx/access.log json_analytics;

    location / {
        proxy_pass http://backend_upstream;

        # ОБЯЗАТЕЛЬНО: Проброс сохраненного или сгенерированного W3C контекста
        proxy_set_header traceparent $incoming_traceparent;
        proxy_set_header tracestate  $http_tracestate;
        proxy_set_header baggage     $http_baggage;

        # Дополнительно передаем X-Request-ID для legacy-систем
        proxy_set_header X-Request-ID $extracted_trace_id;
    }
}
```

#### 2. Проверка проброса заголовков через curl

```bash
# Тест 1: Передача собственного traceparent
curl -sS -I -H "traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01" http://127.0.0.1/api/v1/ping
# → HTTP/1.1 200 OK
# → Content-Type: application/json

# Проверка фиксации trace_id в журнале access.log
tail -n 1 /var/log/nginx/access.log | jq .
# → {
# →   "time_local": "2026-10-12T21:10:00+03:00",
# →   "status": "200",
# →   "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
# →   "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
# → }
```

---

### Сценарий 2: Распространение контекста через Kafka и использование Span Links

**Задача:** Организовать связывание асинхронной очереди Kafka с трассировкой Jaeger:
* Producer внедряет W3C `traceparent` в Record Headers сообщения.
* Consumer извлекает `traceparent` и связывает обработку сообщения с исходной транзакцией через **Span Links**, чтобы не искажать длительность родительского спана продюсера.

#### 1. Логика продюсера (Go SDK)

```go
package main

import (
	"context"
	"github.com/segmentio/kafka-go"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

// KafkaHeaderCarrier реализует TextMapCarrier для Kafka Record Headers
type KafkaHeaderCarrier []kafka.Header

func (c *KafkaHeaderCarrier) Get(key string) string {
	for _, h := range *c {
		if h.Key == key {
			return string(h.Value)
		}
	}
	return ""
}

func (c *KafkaHeaderCarrier) Set(key string, val string) {
	*c = append(*c, kafka.Header{Key: key, Value: []byte(val)})
}

func (c *KafkaHeaderCarrier) Keys() []string {
	keys := make([]string, len(*c))
	for i, h := range *c {
		keys[i] = h.Key
	}
	return keys
}

func ProduceOrderEvent(ctx context.Context, writer *kafka.Writer, orderID string) error {
	tr := otel.Tracer("order-service")
	ctx, span := tr.Start(ctx, "kafka.produce.order_created", trace.WithSpanKind(trace.SpanKindProducer))
	defer span.End()

	// Инъекция контекста трассировки в заголовки Kafka
	carrier := KafkaHeaderCarrier{}
	otel.GetTextMapPropagator().Inject(ctx, &carrier)

	msg := kafka.Message{
		Key:     []byte(orderID),
		Value:   []byte(`{"order_id":"` + orderID + `","status":"paid"}`),
		Headers: []kafka.Header(carrier),
	}

	return writer.WriteMessages(ctx, msg)
}
```

#### 2. Логика консьюмера с использованием Span Links (Go SDK)

```go
func ProcessOrderMessage(ctx context.Context, msg kafka.Message) error {
	tr := otel.Tracer("notification-service")

	// 1. Извлечение родительского контекста из заголовков сообщения
	carrier := KafkaHeaderCarrier(msg.Headers)
	extractedCtx := otel.GetTextMapPropagator().Extract(ctx, &carrier)
	producerSpanContext := trace.SpanContextFromContext(extractedCtx)

	// 2. ВАЖНО: Создаем спан консьюмера с использованием Link, а не как Child-Of
	// Это исключает ложное увеличение длительности родительской транзакции в UI
	opts := []trace.SpanStartOption{
		trace.WithSpanKind(trace.SpanKindConsumer),
	}
	if producerSpanContext.IsValid() {
		opts = append(opts, trace.WithLinks(trace.Link{SpanContext: producerSpanContext}))
	}

	workCtx, span := tr.Start(ctx, "kafka.consume.order_created", opts...)
	defer span.End()

	// Выполнение фоновой обработки
	return executeNotification(workCtx, msg.Value)
}
```

---

### Сценарий 3: Настройка Composite Propagator для гетерогенных окружений

**Задача:** В процессе плавной миграции в инфраструктуре одновременно присутствуют legacy-сервисы с Zipkin B3, старые клиенты Jaeger с `uber-trace-id` и современные сервисы с W3C `traceparent`. Требуется настроить SDK так, чтобы приложения понимали любой из форматов и передавали дальше W3C.

#### 1. Конфигурация через стандартные переменные окружения OpenTelemetry

```bash
# В манифесте Deployment Kubernetes или systemd-юните сервиса
# Задаем составной пропогатор: W3C TraceContext + Baggage + Zipkin B3 + Jaeger
export OTEL_PROPAGATORS="tracecontext,baggage,b3,b3multi,jaeger"

# Пример передачи в Docker Compose / Pod:
# 1. Приоритет проверки при извлечении (Extract): слева направо
#    (Сначала ищет traceparent, если нет - проверяет b3, затем uber-trace-id).
# 2. При инъекции (Inject): генерирует W3C traceparent + legacy заголовки для совместимости.
```

#### 2. Проверка работы составного пропогатора через CLI

```bash
# Отправка запроса с устаревшим заголовком Zipkin B3 Single Header
curl -sS -I -H "b3: 4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-1" http://127.0.0.1:8080/api/v1/orders
# → HTTP/1.1 200 OK
# → traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-5a4b12c8d7e9f1a2-01

# Ответ подтверждает: сервис успешно подхватил TraceID из B3 и преобразовал его в валидный W3C traceparent
```

---

### Сценарий 4: Диагностика сетевых заголовков через `tcpdump` на сервере

Когда в Jaeger UI трасса разрывается между сервисом A и сервисом B, первый шаг SRE — убедиться, что заголовок действительно покидает сетевую карту отправителя и достигает получателя.

```bash
# 1. Захват HTTP-трафика на интерфейсе узла (порт 8080) с фильтрацией строки traceparent
sudo tcpdump -i any -A -s 0 'tcp port 8080 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12:1] & 0xf0)>>2)) != 0)' | grep -E -A 2 -B 2 "traceparent:"

# → 21:15:02.129384 IP 192.168.10.15.48292 > 192.168.10.20.8080: Flags [P.], seq 1:450
# → POST /api/v1/payments HTTP/1.1
# → Host: billing-service:8080
# → traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
# → Content-Length: 124

# Вывод подтверждает: заголовок корректно передается по сети в физическом L7-пакете.
# Если заголовок виден в tcpdump, но сервис B создает новый TraceID — проблема в Extractor внутри кода сервиса B.
```

---

### Сценарий 5: Сквозная трассировка СУБД через SQLCommenter

**Задача:** Связать спан вызова базы данных из приложения со slow query логом PostgreSQL, чтобы DBA и SRE могли мгновенно находить медленные транзакции по `trace_id`.

#### 1. Формат SQL-запроса, формируемый SQLCommenter

```sql
SELECT id, status, total_amount 
FROM orders 
WHERE customer_id = 9182 
/*traceparent='00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',service='order-api',route='/api/v1/orders'*/;
```

#### 2. Настройка PostgreSQL для фиксации комментариев (`postgresql.conf`)

```ini
# Увеличение размера буфера сохранения текста запроса в памяти
# По умолчанию 1024 байта; длинные запросы с комментариями могут обрезаться
track_activity_query_size = 4096

# Префикс журналов с указанием времени, PID и имени приложения
log_line_prefix = '%m [%p] %u@%d [%a] '

# Логировать запросы, выполняющиеся дольше 250 мс
log_min_duration_statement = 250
```

#### 3. Поиск медленного запроса в логах PostgreSQL по `trace_id` из Jaeger

```bash
# Поиск в логах СУБД по trace_id, полученному при расследовании спана в Jaeger UI
grep "4bf92f3577b34da6a3ce929d0e0e4736" /var/log/postgresql/postgresql-16-main.log
# → 2026-10-12 21:20:14.912 MSK [148291] app@prod_db [order-api] LOG:  duration: 489.123 ms  statement: SELECT id, status, total_amount FROM orders WHERE customer_id = 9182 /*traceparent='00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',service='order-api',route='/api/v1/orders'*/;
```

---

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Трасса состоит ровно из одного спана (Root), дочерние сервисы создают новые трассы** | Обратный прокси или API Gateway отрезает HTTP-заголовок `traceparent`, либо downstream-сервис использует несовместимый пропогатор | 1. `tcpdump -A port <port> \| grep traceparent`.<br>2. Проверить переменные `OTEL_PROPAGATORS` в downstream-подах. | 1. Настроить `proxy_set_header traceparent $http_traceparent;` в Nginx.<br>2. Установить `OTEL_PROPAGATORS="tracecontext,baggage,b3,jaeger"` для downstream-сервисов. |
| **Отрицательная длительность спана или дочерний спан начинается раньше родительского** | Рассинхронизация физического системного времени (Clock Skew) между серверами | Команда на всех хостах: `chronyc tracking \| grep "System time"`. Расхождение > 50 мс искажает UI. | 1. Настроить демон `chronyd` на всех нодах кластера с единым пулом NTP.<br>2. В Jaeger UI включить алгоритм Clock Skew Adjustment (по умолчанию включен). |
| **Асинхронные задачи (Goroutines / ThreadPool) теряют родительский контекст** | В коде горутины инициализируется чистый контекст `context.Background()` или не копируется Java `ThreadLocal` | Поиск в репозитории кода приложения: `grep -rn "context.Background()" .` внутри обработчиков HTTP-запросов. | Передавать родительский `ctx` аргументом в функцию горутины; в Java оборачивать задачи через `Context.wrap(runnable)`. |
| **Зависание или разрыв трейса при прохождении брокера Kafka** | Продюсер не добавил `KafkaHeaderCarrier`, либо консьюмер связал вызов через `Child-Of` вместо `Span Links` | В Jaeger UI: спан консьюмера отображается с задержкой в часы, либо не связан с продюсером. | 1. Внедрить инъекцию заголовков в Kafka Record Headers продюсера.<br>2. В консьюмере формировать спан через `trace.WithLinks(producerSpanContext)`. |
| **В логах приложения поле `trace_id` пустое, хотя спаны в Jaeger отправляются** | Логгер не интегрирован с OTel Context (нет Mapped Diagnostic Context / MDC в Java, нет middleware логгера в Go) | Логи сервиса: `{"msg":"order created","trace_id":""}` | Настроить мост логгера (OTel Logging Instrumentation), автоматически читающий текущий `SpanContext` и обогащающий JSON-логи. |

---

## Лучшие практики

1. **Единый базовый стандарт W3C:** В качестве основного формата распространения контекста всегда используйте W3C Trace Context (`traceparent`). Legacy-форматы (B3, Jaeger) подключайте только как дополнительные через составной пропогатор `OTEL_PROPAGATORS="tracecontext,baggage,b3,jaeger"`.
2. **Семантика Span Links для асинхронных контуров:** Никогда не делайте спан консьюмера прямым потомком (`Child-Of`) спана продюсера в очередях сообщений (Kafka, RabbitMQ, Celery). Это разрушает метрику задержки клиентской транзакции. Используйте `Span Links` (`Follows-From`).
3. **Безопасность метаданных в Baggage:** Механизм Baggage передает заголовки по всей цепочке вызовов, включая сторонние внешние сервисы. **Категорически запрещено** помещать в Baggage токены авторизации (JWT, Bearer), пароли, ключи API и персональные данные (PII). Ограничивайте размер Baggage (не более 1–2 КБ суммарно).
4. **Обогащение логов и корреляция (Traces to Logs):** Каждый логгер в инфраструктуре обязан автоматически включать текущий `trace_id` и `span_id` в структурированный JSON-лог. Это фундамент корреляции в Grafana (переход от спана к логам в Loki за 1 клик).
5. **Синхронизация системного времени NTP:** Эксплуатация распределенной трассировки невозможна без жесткого контроля NTP. Убедитесь, что на всех физических серверах запущен демон `chrony`, а максимальный дрейф часов между узлами не превышает **5–10 мс**.

---

## Дополнительная информация

**Смежные материалы в базе знаний:**
* Стратегии сэмплирования трасс: **[Стратегии сэмплирования в Jaeger](./jaeger_sampling_strategies.md)**
* Анализ узких мест и критического пути: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Интеграция с Ingress-NGINX и сетками: **[Интеграция Jaeger с Service Mesh](./jaeger_service_mesh_integration.md)**
* Трассировка со стороны PostgreSQL: **[PostgreSQL Observability](../Databases/PostgreSQL/Operations/observability.md)**
* Общая спецификация протокола: **[Протокол OTLP](../OpenTelemetry/otlp_protocol.md)**

**Официальная документация:**
* [W3C Trace Context Specification](https://www.w3.org/TR/trace-context/)
* [OpenTelemetry Context Propagation Guide](https://opentelemetry.io/docs/concepts/context-propagation/)
* [OpenTelemetry SQLCommenter Documentation](https://google.github.io/sqlcommenter/)
