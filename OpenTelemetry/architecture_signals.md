# OpenTelemetry: Архитектура и сигналы

## Определения

**Сигналы** — стандартизированные типы телеметрии, которые описывают поведение системы с разных сторон:

- **Traces (трассировки)** показывают причинно-следственный путь запроса через сервисы.
- **Metrics (метрики)** представляют числовые измерения состояния и производительности.
- **Logs (логи)** фиксируют структурированные или текстовые события.
- **Profiles (профили)** описывают потребление ресурсов программой на уровне стеков выполнения.

OTel задаёт общие концепции Resource и Instrumentation Scope, но наличие сигнала в спецификации не означает одинаковую готовность API, SDK, автоинструментации и backend-поддержки во всех языках.

## Статусы сигналов

| Сигнал | Статус | Практическое значение |
| :--- | :--- | :--- |
| **Трассировки** | **Stable** | Зрелый API, SDK и экосистема инструментации |
| **Метрики** | **Stable** | Зрелый API и SDK; возможности агрегации зависят от реализации |
| **Логи** | **Stable**, кроме явно отмеченных частей | Logs API стабилен, но поддержка мостов, автоинструментации и корреляции различается по языкам |
| **Профили** | **Alpha** | Формат и интеграции развиваются; перед production нужно проверять поддержку каждого компонента |

OpenTelemetry имеет статус **CNCF Graduated**. Стабильность проекта не делает каждый отдельный компонент стабильным: у Collector, отдельных receivers, processors, exporters и extensions могут быть разные уровни зрелости.

## Общие элементы данных

### Resource

**Resource** описывает сущность, создавшую телеметрию: сервис, процесс, Pod, host, кластер или устройство. Типовые атрибуты:

- `service.name`;
- `service.version`;
- `service.instance.id`;
- `k8s.namespace.name`;
- `k8s.pod.name`;
- `host.name`.

Одинаковый Resource помогает backend-системе связывать данные, пришедшие от одного источника, даже если они были собраны разными SDK или агентами.

### Instrumentation Scope

**Instrumentation Scope** идентифицирует библиотеку или компонент, создавший запись: имя, версия и schema URL. Это позволяет отличать данные автоматической инструментации HTTP-библиотеки от ручных span или пользовательских метрик.

## 1. Трассировки

Трассировка состоит из span-ов. Каждый span представляет операцию и содержит имя, время начала и окончания, `trace_id`, `span_id`, attributes, events и links. Контекст между сервисами передаётся через W3C Trace Context, обычно в заголовках `traceparent` и `tracestate`; Baggage передаёт дополнительные контекстные значения.

Трассировки полезны для анализа распределённых запросов, зависимостей сервисов, ошибок и задержек. Они не заменяют метрики и логи: trace показывает конкретный путь выполнения, а metric и log помогают оценить общую картину и детали событий.

Подробнее: [Трассировки: глубокое погружение](../Concepts/Observability_and_Monitoring/traces_deep_dive.md).

## 2. Метрики

Метрики описывают измеряемые значения и их изменение во времени. OTel поддерживает несколько типов инструментов и агрегаций, включая:

- `Counter` и `UpDownCounter`;
- `Gauge`;
- `Histogram`;
- `ExponentialHistogram`, если реализация и backend его поддерживает.

Метрики используют attributes. Каждый уникальный набор attribute values может образовать отдельную временную серию, поэтому кардинальность нужно контролировать на этапе проектирования. Не следует использовать в label пользователя, заказ, сессию, request ID или другие почти уникальные идентификаторы.

Подробнее: [Метрики: глубокое погружение](../Concepts/Observability_and_Monitoring/metrics_deep_dive.md).

## 3. Логи

OTel определяет log data model, Logs API и SDK. **Logs API** предназначен в том числе для авторов log appenders и мостов между существующими библиотеками, такими как Log4j, Logback или стандартными средствами языка, и моделью OTel.

Лог может содержать:

- timestamp и observed timestamp;
- severity number и severity text;
- body;
- attributes;
- event name;
- exception;
- `trace_id` и `span_id`, если доступен текущий execution context;
- Resource context.

Корреляция логов с трассировками не возникает сама по себе. Она требует корректной передачи контекста, поддержки со стороны logging bridge или автоинструментации и возможности backend искать логи по `trace_id`. Для файловых и stdout-логов Collector может читать и парсить данные через `filelog` или принимать их от другого агента, например Fluent Bit.

Подробнее: [Логи: глубокое погружение](../Concepts/Observability_and_Monitoring/logs_deep_dive.md).

## 4. Профили

**Profiles** — коллекция stack traces и связанных значений, представляющих потребление ресурсов и выполнение кода. Профили обычно собираются периодическим сэмплированием состояния работающей программы.

OTel Profiles строится поверх формата, совместимого с `pprof`, и добавляет Resource, Instrumentation Scope, attributes и возможные ссылки на trace/span. Это позволяет связывать профиль с другими сигналами, но прямая связь sample-to-span зависит от источника профиля, SDK и backend.

Статус сигнала — **Alpha**. Перед внедрением нужно проверить:

- поддерживает ли выбранный язык нужный profiler;
- принимает ли Collector соответствующий receiver и pipeline;
- понимает ли backend формат и ссылки на traces;
- какой overhead допустим для production.

Подробнее: [Профилирование: глубокое погружение](../Concepts/Observability_and_Monitoring/profiling_deep_dive.md).

## Корреляция сигналов

OTel предоставляет общие идентификаторы и контексты, но backend должен уметь использовать их для навигации.

- **Traces ↔ Logs:** общий `trace_id` и, при наличии, `span_id`; требуется结构化 logging или log bridge.
- **Metrics ↔ Traces:** exemplar может содержать trace ID и ссылаться на конкретный запрос.
- **Traces ↔ Profiles:** профиль может иметь ссылку на trace/span, если profiler и backend поддерживают эту связь.
- **Resource correlation:** одинаковые service, Pod, host и deployment attributes помогают сопоставлять сигналы даже без прямого trace ID.

Корреляция должна быть проверена сквозным тестом: создать запрос, найти trace, перейти к связанным logs и exemplar, затем убедиться, что backend возвращает ожидаемые данные.

## Архитектура Collector

Collector принимает данные, обрабатывает их и экспортирует в один или несколько backend-ов:

```text
Receivers → Processors → Exporters
                   │
                   └── Connectors → другие pipelines
```

### Receivers

Принимают OTLP, Prometheus, Jaeger, Zipkin, Fluent Bit, Syslog, filelog и другие форматы. Receiver определяет, какие сигналы и с каких endpoints поступают в Collector.

### Processors

Обрабатывают данные внутри pipeline. Распространённые задачи:

- `memory_limiter` — защита от переполнения памяти и backpressure;
- `batch` — группировка записей перед экспортом;
- `attributes` и `resource` — добавление, удаление или изменение атрибутов;
- `transform` — преобразование полей и нормализация данных;
- `filter` — отбор данных до отправки;
- `tail_sampling` — решение о сохранении trace после анализа span-ов;
- `spanmetrics` — создание метрик из трассировок.

**Порядок processors важен.** `memory_limiter` обычно размещают первым, чтобы ограничить потребление памяти и создать backpressure до остальной обработки. `batch` обычно размещают ближе к экспорту, чтобы уменьшить количество сетевых запросов.

### Exporters

Отправляют данные в backend. Один Collector может одновременно экспортировать traces в Tempo или Jaeger, metrics в Prometheus/Mimir, logs в Loki/OpenSearch и другие сигналы в специализированные хранилища.

### Connectors

Connectors соединяют pipelines. Например, `spanmetrics` принимает traces и создаёт metrics, которые затем обрабатываются и экспортируются отдельным metrics pipeline. `servicegraph` строит данные о зависимостях сервисов.

### Extensions

Extensions предоставляют служебные функции: health check, pprof, authentication, управление конфигурацией и другие возможности. Они не заменяют receivers, processors или exporters.

### Процессоры: подробнее

#### memory_limiter

Защищает Collector от OOM при пиковых нагрузках. Работает по принципу мягкого и жёсткого лимита:

- `limit_mib` — целевой предел памяти для pipeline. При превышении Collector начинает отклонять входящие данные.
- `spike_limit_mib` — допуск для краткосрочных всплесков. Позволяет обработать неожиданный наплыз без немедленного отказа.
- `check_interval` — частота проверки памяти.

**SRE-совет:** Настройте `limit_mib` на 50–70% от доступной RAM контейнера/хоста, оставляя запас под ОС и другие процессы. При использовании в Kubernetes задавайте лимиты в deployment и выравнивайте их с `limit_mib`.

#### batch

Группирует записи перед экспортом для снижения нагрузки на сеть и backend. Ключевые параметры:

- `send_batch_size` — максимальный размер батча.
- `timeout` — максимальное время ожидания наполнения батча.
- `metadata_keys` — поля, по которым можно группировать батчи (например, `service.name`).

**SRE-совет:** `send_batch_size` должен соответствовать среднему объёму данных, генерируемых за 10–30 секунд. Слишком большой батч увеличивает задержку экспорта; слишком маленький — создаёт избыточный сетевой трафик.

#### tail_sampling

Принимает решение о сохранении trace после получения достаточной части span-ов. Позволяет сохранять ошибки, медленные запросы и другие важные сценарии. Процессор stateful: он хранит данные до принятия решения, поэтому требует памяти, мониторинга и правильной маршрутизации.

Для нескольких gateway-экземпляров все span одного trace должны попадать на один экземпляр, иначе решение может быть неполным. В agent-to-gateway топологии для этого применяют балансировку по trace ID.

#### spanmetrics

Создаёт derived-метрики на основе трассировок: количество span, их длительность, количество ошибок по сервисам и операциям. Позволяет строить RED-метрики (Rate, Errors, Duration) без изменения кода приложений.

**SRE-совет:** Контролируйте кардинальность метрик, генерируемых `spanmetrics`. Каждая уникальная комбинация `service.name` + `span.name` + `span.kind` создаёт отдельную временную серию. Используйте `dimensions` для ограничения набора атрибутов.

#### filter

Отбирает данные до отправки. Может исключать или включать записи по атрибутам, типам сигналов или содержимому. Используется для снижения кардинальности и стоимости.

**SRE-совет:** Применяйте `filter` как можно раньше в pipeline, чтобы уменьшить нагрузку на последующие processors и exporters. Исключайте health-check метрики, debug-спаны и другие служебные данные на edge Collector.

## Сэмплирование

### Head-based sampling

Решение принимается в SDK до завершения trace. Оно быстрое и эффективное, но не может учитывать будущую ошибку или итоговую задержку. Вероятностное сэмплирование должно быть согласованным, чтобы весь trace сохранялся целиком.

### Tail-based sampling

Решение принимается после получения достаточной части trace. Можно сохранять traces с ошибками, высокой задержкой или特定 business-атрибутами. Процессор stateful: он хранит данные до принятия решения, поэтому требует памяти, мониторинга и правильной маршрутизации.

Для нескольких gateway-экземпляров все span одного trace должны попадать на один экземпляр, иначе решение может быть неполным. В agent-to-gateway топологии для этого применяют балансировку по trace ID.

### Комбинированный подход

Может сначала ограничивать поток на SDK (head-based), а затем применять tail-based правила на Gateway. Это снижает нагрузку на Gateway, сохраняя при этом важные traces.

## Кардинальность и стоимость

Кардинальность — количество уникальных комбинаций labels или attributes. Высокая кардинальность увеличивает расход памяти, CPU, ingestion и storage.

Рекомендации:

1. Не добавлять почти уникальные идентификаторы в metric attributes.
2. Нормализовать URL, route, operation name и другие поля с высокой вариативностью.
3. Фильтровать ненужные поля до exporter.
4. Агрегировать данные там, где допустима потеря детализации.
5. Настраивать retention отдельно для traces, logs и metrics.
6. Проверять фактический объем на репрезентативных данных перед выбором backend.

## Выбор backend

Выбор backend следует основывать на требованиях:

- поддержка нужных сигналов и версий OTLP;
- качество корреляции traces, logs, metrics и profiles;
- ограничения cardinality и допустимые attribute sets;
- запросы, индексация, retention и стоимость хранения;
- надёжность, retry, очереди и восстановление после сбоев;
- TLS, аутентификация, фильтрация PII и аудит;
- возможность масштабировать ingestion и query-нагрузку.

LGTM, OpenSearch, ClickHouse, VictoriaMetrics, VictoriaLogs, Tempo, Loki и другие решения решают разные задачи. Универсального лучшего backend для всех сигналов нет.

## Data Prepper

**Data Prepper** — pipeline-движок экосистемы OpenSearch. Он принимает OTLP, маршрутизирует traces и logs, применяет processors, преобразует данные в документы OpenSearch и может формировать service map. Это опциональный компонент для OpenSearch, а не обязательная часть OpenTelemetry.

## Практические сценарии

### Сценарий 1: Выбор топологии развёртывания Collector

Топология Collector зависит от нагрузки, требований к задержке и операционных возможностей:

| Топология | Когда использовать | Особенности |
| :--- | :--- | :--- |
| **Direct export** | Локальная разработка, демо | SDK → backend напрямую. Нет Collector, минимальная задержка. |
| **Agent (DaemonSet)** | Kubernetes, несколько узлов | Collector на каждом узле собирает локальный трафик, применяет базовую обработку и передаёт в Gateway. Низкая задержка, распределённая обработка. |
| **Gateway (Deployment)** | Централизованная обработка | Агрегирует данные, выполняет фильтрацию, enrichment, tail-based sampling и маршрутизацию. Требует балансировки по trace ID. |
| **Agent + Gateway** | Production Kubernetes | Агенты собирают данные на узлах, Gateway выполняет общую обработку. Оптимальный баланс задержки и функциональности. |
| **Sidecar** | Изоляция workloads | Collector в том же Pod. Простота развёртывания, но больше экземпляров и ресурсов. |
| **eBPF/OBI** | Legacy, без изменения кода | Собирает сетевые и системные данные без инъекции. Не заменяет бизнес-инструментацию. |

**SRE-совет:** В production Kubernetes используйте **Agent + Gateway**. Agent на каждом узле (DaemonSet) собирает данные с минимальной задержкой, а центральный Gateway выполняет resource-heavy операции: tail-based sampling, k8sattributes enrichment, маршрутизацию. Это обеспечивает масштабируемость и отказоустойчивость.

### Сценарий 2: Маршрутизация сигналов по разным backend

Один Collector может одновременно экспортировать traces, metrics и logs в разные backend-системы:

```text
Приложение → OTLP/gRPC (4317) → Collector
                                ├── Traces → Jaeger/Tempo
                                ├── Metrics → Prometheus/Mimir
                                └── Logs → Loki/OpenSearch
```

Конфигурация pipelines позволяет обрабатывать каждый сигнал независимо:

```yaml
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch, tail_sampling]
      exporters: [otlp/tempo]
    metrics:
      receivers: [otlp, kubeletstats]
      processors: [memory_limiter, batch, attributes/cluster]
      exporters: [prometheusremotewrite]
    logs:
      receivers: [otlp, filelog]
      processors: [memory_limiter, batch]
      exporters: [loki]
```

**Важно:** Каждый pipeline имеет свои receivers, processors и exporters. Processor `memory_limiter` обычно размещают первым во всех pipelines для защиты от OOM.

### Сценарий 3: Валидация корреляции сигналов

После развёртывания проверьте сквозную корреляцию:

**Шаг 1. Создайте тестовый запрос**

```bash
curl -H "traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" \
     http://payment-api:8080/check
```

**Шаг 2. Найдите trace в backend**

Найдите trace по `trace_id` = `0af7651916cd43dd8448eb211c80319c`. Убедитесь, что trace содержит все ожидаемые spans.

**Шаг 3. Проверьте корреляцию с логами**

В backend найдите логи, связанные с этим trace_id. В Loki запрос: `{service="payment-api"} | trace_id="0af7651916cd43dd8448eb211c80319c"`. В результатах должен быть trace_id в атрибутах.

**Шаг 4. Проверьте exemplar в метриках**

На графике метрики `http_request_duration_seconds` найдите exemplar и перейдите к связанному trace. Exemplar должен содержать trace_id.

**Ожидаемый результат:** Все три сигнала содержат общий `trace_id` и `span_id`, и backend позволяет навигации между ними.

### Сценарий 4: Мониторинг и алертинг Collector

Collector следует мониторить как обычный production-сервис. По умолчанию он выводит внутренние метрики через Prometheus endpoint на порту `8888`.

**Критические метрики:**

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `otelcol_receiver_refused_*` | > 0 | Проверить `memory_limiter`, ресурсы Collector, сетевые задержки |
| `otelcol_exporter_queue_size` | > 80% capacity | Backend перегружен или недоступен. Проверить retry, sending_queue, backend health |
| `otelcol_exporter_send_failed_*` | > 0 | Проверить сеть, TLS, backend endpoint, квоты |
| `otelcol_processor_memory_limiter_refused_spans_total` | > 0 | Увеличить `limit_mib` или масштабировать Collector |
| `otelcol_processor_incoming_items` vs `outgoing_items` | Разрыв > 10% | Processor bottleneck. Проверить CPU, добавить инстансы |

**Команды проверки:**

```bash
# Метрики Collector
curl -s http://otel-collector:8888/metrics | grep "otelcol"

# Логи Collector
kubectl logs -n observability -l app=otel-collector --tail=100 | grep -E "(error|refused|failed)"

# Проверка очередей exporter
curl -s http://otel-collector:8888/metrics | grep "otelcol_exporter_queue"
```

### Сценарий 5: Очистка окружения

```bash
# Удаление тестовых ресурсов Kubernetes
kubectl delete instrumentation --all -n my-app
kubectl delete pods -l instrumentation.opentelemetry.io/inject-java=true -n my-app

# Очистка тестовых метрик и логов
rm -f /tmp/otel-sdk.log /tmp/otel-sdk-debug.log

# Остановка фоновых Collector'ов
docker stop otel-collector && docker rm otel-collector

# Удаление тестовых сертификатов
rm -f ca.crt ca.key server.crt server.key client.crt client.csr client.key

# Очистка очереди отправки (если использовался file_storage)
rm -rf /tmp/otel-sending-queue/*
```

## Безопасность Collector

- Для внешних соединений используют TLS или mTLS; параметры безопасности задают явно, а не полагаются на случайные значения по умолчанию.
- Для аутентификации могут применяться заголовки, bearer token, OIDC и другие механизмы backend.
- Конфиденциальные данные фильтруют или маскируют до экспорта с помощью processors и политик сбора.
- Telemetry Schemas помогают управлять изменениями семантических конвенций и совместимостью данных.
- Конфигурацию Collector хранят в системе контроля версий, проверяют перед внедрением и сопровождают метриками pipeline.

## Ресурсы и масштабирование

Collector потребляет CPU и память пропорционально объёму обрабатываемых данных. Для оценки ресурсов:

1. **CPU:** Зависит от количества span, сложности processors и compression. Batch processor и transform требуют больше CPU, чем простой pass-through.
2. **Память:** Определяется `memory_limiter` и размером очередей. Tail-based sampling и spanmetrics хранят состояния span в памяти.
3. **Сеть:** OTLP/gRPC использует HTTP/2. Сжатие (`zstd`, `gzip`) снижает带宽, но увеличивает CPU.

**SRE-совет:** Начните с 1 CPU и 2 GiB RAM на инстанс Collector. При нагрузке > 50k spans/second масштабируйте горизонтально. Мониторьте `otelcol_processor_memory_limiter_refused_spans_total` — этот индикатор сигнализирует о необходимости увеличения лимитов или количества инстансов.

## Высокая доступность

- Запускайте несколько инстансов Collector за балансировщиком.
- Используйте `file_storage` для `sending_queue` — это гарантирует доставку данных при перезапуске Collector.
- При использовании tail-based sampling убедитесь, что все span одного trace попадают на один экземпляр (балансировка по trace ID).
- Для Gateway-топологии настройте health check и readiness probe. Collector готов к обслуживанию только после загрузки конфигурации.

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Connection refused на 4317** | gRPC receiver не запущен или endpoint неверный | Проверить `kubectl get pods -l app=otel-collector`, логи Collector, переменную `OTEL_EXPORTER_OTLP_ENDPOINT` |
| **TLS handshake failure** | Неверный сертификат или клиент не предоставляет сертификат при mTLS | Проверить `tls` блок в конфигурации, срок действия сертификатов (`openssl x509 -in server.crt -noout -dates`) |
| **High CPU на Collector** | Отсутствует compression или слишком большой `max_recv_msg_size` | Включить `zstd` compression, ограничить `max_recv_msg_size` |
| **Backpressure / OOM** | Отсутствует `memory_limiter` или `sending_queue` переполнен | Добавить `memory_limiter`, настроить `sending_queue.size`, увеличить `limit_mib` |
| **Частичный успех (Partial Success)** | Некорректные записи в батче (нарушение семантики, превышение размера) | Проверить rejected records в ответе, логировать на стороне SDK, исправить источник данных |
| **Спаны не поступают при высокой нагрузке** | `batch` processor переполнен или `send_batch_size` слишком большой | Уменьшить `send_batch_size`, увеличить `timeout`, добавить горизонтальное масштабирование Collector |
| **L4-балансировка даёт неравномерную нагрузку** | gRPC streaming распределяется по соединениям, а не по запросам | Перейти на L7-балансировщик с HTTP/2 aware routing |
| **Trace разорван между сервисами** | Отсутствует Propagator или нарушена семантика W3C | Проверить наличие `tracecontext` propagator в SDK всех сервисов, убедиться что Ingress/Proxy пропускает заголовки |
| **Высокое потребление RAM в Collector** | Tail-sampling с большими объемами данных | Увеличить `limit_mib` в `memory_limiter`, уменьшить `num_traces`, оптимизировать политики сэмплирования |
| **Потеря данных при SIGTERM** | Отсутствует graceful shutdown | Реализовать `Shutdown` с `context.WithTimeout`, проверить `terminationGracePeriodSeconds` |
| **Слишком много метрик/трейсов** | Отсутствует сэмплирование или кардинальность атрибутов слишком высокая | Настроить `TraceIDRatioBased`, использовать aggregation в SDK, ограничить `OTEL_RESOURCE_ATTRIBUTES` |
| **Контекст теряется между сервисами** | W3C Trace Context не распространяется через очередь/message broker | Явно инжектировать/экстрактировать Propagator на границах асинхронных вызовов |

## Мониторинг Collector

Collector по умолчанию предоставляет внутренние Prometheus metrics на `8888` и пишет внутренние логи в `stderr`. Необходимо отслеживать:

- `otelcol_receiver_accepted_*` и `otelcol_receiver_refused_*` — приток данных и backpressure.
- `otelcol_processor_incoming_items` и `otelcol_processor_outgoing_items` — throughput processors.
- `otelcol_exporter_queue_size` и `otelcol_exporter_queue_capacity` — заполнение очереди exporter.
- `otelcol_exporter_enqueue_failed_*` и `otelcol_exporter_send_failed_*` — ошибки доставки.
- `otelcol_processor_memory_limiter_refused_spans_total` — защита от OOM сработала.
- CPU, RSS, heap и длительность export requests.

Наличие refused items, переполненной очереди или устойчивых export failures требует проверки backend, сети, ресурсов Collector и настроек retry.

## Ограничения и крайние случаи (Edge Cases)

- **Очень большие сообщения:** При превышении `max_recv_msg_size` (по умолчанию 4 MB) gRPC возвращает `RESOURCE_EXHAUSTED`. Для трассировок это обычно означает слишком много атрибутов или вложенных событий в одном span. Решение — уменьшить детализацию или увеличить лимит с одновременным добавлением compression.
- **Высокая кардинальность метрик:** OTLP не ограничивает количество уникальных временных рядов на стороне протокола, но backend и Collector имеют практические лимиты. Метрики с кардинальностью выше 10 000 series по одному metric name требуют отдельного проектирования.
- **Сетевые разрывы:** При разрыве TCP-соединения gRPC-stream завершается с ошибкой `UNAVAILABLE`. SDK с настроенным retry policy автоматически переподключается. `sending_queue` на стороне Collector гарантирует доставку после восстановления связи, если backend временно недоступен.
- **Смешанные версии SDK и Collector:** OTLP v1.x обратно совместим с v0.x receivers в пределах одного major-версии. При обновлении Collector сначала обновляют receivers/processors, затем exporters, проверяя совместимость с backend.

## Демо

Официальный demo-проект показывает многопоточное приложение, Collector и backend-системы:

```bash
git clone https://github.com/open-telemetry/opentelemetry-demo.git
cd opentelemetry-demo
docker compose up --force-recreate --remove-orphans --detach
```

В версиях репозитория с отдельным минимальным compose-файлом:

```bash
docker compose -f docker-compose.minimal.yml up --force-recreate --remove-orphans --detach
```

После запуска проверяют web store, Collector, traces, metrics и logs в выбранных backend UI.

## Смотрите также

- [OpenTelemetry: Обзор](./opentelemetry_overview.md)
- [Протокол OTLP](./otlp_protocol.md)
- [Инструментация и SDK](./instrumentation_sdk.md)
- [Интеграция с Prometheus](./prometheus_integration.md)
- [Интеграция с Grafana](./grafana_integration.md)
- [Продвинутое сэмплирование](./advanced_sampling.md)
- [Отказоустойчивость Collector](./collector_high_availability.md)
