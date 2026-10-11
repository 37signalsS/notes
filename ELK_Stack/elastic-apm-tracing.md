# Elastic APM: распределённые трассировки и RUM

**Актуально для:** Elastic Stack 9.5.x / 8.19 LTS

## Определения

*   **APM (Application Performance Monitoring)** — мониторинг производительности приложений: латентность, ошибки, «медленные» вызовы по внешним зависимостям.
*   **Agent** — библиотека в коде приложения (Java, .NET, Node.js, Python, Go, Ruby, PHP) или JavaScript-скрипт в браузере (RUM). Инструментирует код: HTTP-хендлеры, запросы в БД, обращения к очередям, HTTP-вызовы к другим сервисам.
*   **APM Server** — отдельный компонент стека (порт по умолчанию **8200**): принимает данные агентов, валидирует их, применяет сэмплинг и отправляет в Elasticsearch. Управляется через Fleet-интеграцию **APM** или автономно (`apm-server`).
*   **Transaction** — один логический запрос/операция в сервисе (например, `GET /api/orders`), измеренная от начала до завершения. У кардинально разных URL транзакции группируются в *транзакционные группы* по шаблону имени.
*   **Span** — отдельный фрагмент работы внутри транзакции: вызов БД, HTTP-запрос к сервису, работа очереди. Span привязан к родительской транзакции (или другому span).
*   **Trace (трасса)** — сквозной путь запроса через несколько сервисов: от браузера/входящего HTTP до баз данных и обратно. Связь обеспечивается идентификаторами **W3C Trace Context** (`traceparent`), которые агенты передают в заголовках между сервисами.
*   **RUM (Real User Monitoring)** — сбор метрик из браузера реального пользователя: длительность страницы, Web Vitals (LCP/CLS/INP), ошибки JS, AJAX-вызовы.
*   **Log correlation** — связка логов и трасс: в лог попадают те же `trace.id` / `transaction.id` / `span.id` (поля ECS), что и в телеметрию APM, — из лога можно перейти в трассу и обратно.
*   **ecs-logging** — библиотеки форматирования логов в формат ECS (JSON) для популярных логгеров; в связке с агентом/APM-корреляцией дают готовые трассировочные поля в логах.

## Основные концепции

### Архитектура: четыре компонента

| Компонент | Роль |
|---|---|
| **APM-агенты** (backend) | Инструментируют приложение, собирают транзакции, span, ошибки |
| **APM Server** (Fleet-интеграция APM или standalone) | Приём, валидация, сэмплинг, доставка в Elasticsearch |
| **Elasticsearch** | Хранение телеметрии; управление индексами APM (шаблоны, ILM-политики, ingest-пайплайны) выполняет встроенный плагин **`apm-data`** — с 9.0 APM Server не управляет индексами вообще и пишет только в **data streams** (плагин бэкпортирован в 8.15.5+/8.16.2+/8.17.0) |
| **Kibana** | Service Map, Transactions/Spans, Errors, Dependencies, User Experience (RUM), central configuration агентов |

Агенты говорят с APM Server по HTTP(S) на порту 8200. Агенты backend-сервисов аутентифицируются `secret token` или API key; RUM-запросы из браузера — через отдельный anonymous-режим APM Server (браузер не может безопасно хранить токен).

### Два режима развёртывания APM Server

1.  **Fleet-managed (рекомендуется)** — интеграция APM добавляется в политику Fleet; управление через UI (порты, RUM, кастомные индексы, нагруженность) — без правки конфигов.
2.  **Standalone** — демон `apm-server` с конфигом `apm-server.yml`; выходы данных (`output`): **Elasticsearch, Logstash, Kafka, Redis, File, Console**. Полезно, когда телеметрия должна идти через брокер, минуя прямую доставку в ES.

Важно: **RUM и мобильные агенты требуют централизованно доступного APM Server** (Fleet-agent или standalone, выставленного наружу/за reverse proxy) — браузер не может писать в Elasticsearch напрямую.

### Нативный приём OpenTelemetry (OTLP)

APM Server принимает трейсы, метрики и логи напрямую по **OTLP** — и по **OTLP/gRPC**, и по **OTLP/HTTP**, на том же порту 8200, что и запросы Elastic-агентов (HTTP-эндпоинты `/v1/traces`, `/v1/metrics`, `/v1/logs`; gRPC-сервисы `opentelemetry.proto.collector.*`). Аутентификация — тот же `secret_token`/API key (`Authorization: Bearer ...`). Приём работает и с OTel SDK/Collector, и с Elastic-агентами; tail-based sampling APM Server применяется и к OTLP-трейсам.

Ограничения: Elastic не рекомендует этот intake для новых развёртываний (предпочтительны Elastic Agent или managed OTLP); EDOT-SDK поддерживаются только через Elastic Agent Gateway. Для OTLP/gRPC требуется HTTP/2 (TLS или H2C); при проксировании/балансировке удобнее OTLP/HTTP. Теория протокола — в [OTLP](../OpenTelemetry/otlp_protocol.md), обзор — в [OpenTelemetry: обзор](../OpenTelemetry/opentelemetry_overview.md).

### Данные, сэмплинг и централизованная конфигурация

*   **Head-based сэмплинг** (по умолчанию) — транзакции отбираются агентом по `transaction_sample_rate` до завершения: при снижении ставки уменьшается объём данных, но редкие медленные транзакции могут быть потеряны. Ставка задаётся на агенте (в т.ч. через central configuration).
*   **Tail-based сэмплинг** (`apm-server.sampling.tail.enabled`, по умолчанию выключен; только при выводе в Elasticsearch) — решение принимается в APM Server после завершения трейса: политики сопоставляются с root-транзакцией в заданном порядке, каждая задаёт `sample_rate` (0–1) и условия; список должен завершаться default-политикой (только `sample_rate`), иначе APM Server отклонит трейс с ошибкой `no matching policy`. Настройки: `interval` (синхронизация между экземплярами, 1m), `ttl` (хранение событий до решения, 30m, ≥ 2×`interval`), `storage_limit` (в 9.0+ без явного лимита, но останов записи при 80% диска), `discard_on_write_failure` (по умолчанию `false` — при переполнении хранилища трейсы обходят сэмплинг и индексируются целиком; `true` — отбрасываются, с потерей данных). С 9.0 хранилище переписано на Pebble (в 8.x — BadgerDB): ниже нагрузка на диск/память, выше throughput. Плата: больше CPU/RAM/диска на APM Server и больше трафика от агентов, зато меньше данных в ES и 100% ошибок/медленных трейсов при низкой ставке. Теория tail-based и сэмплирование в OTel Collector — в [трассировках (deep dive)](../Concepts/Observability_and_Monitoring/traces_deep_dive.md) и [продвинутом сэмплировании](../OpenTelemetry/advanced_sampling.md).
*   **Central configuration** — изменение ключевых настроек агентов (логирование, сэмплинг, захват stack trace) из Kibana без перезапуска приложения (агенты опрашивают конфигурацию).
*   Ошибки (uncaught exceptions) хранятся отдельно (data stream `logs-apm.error-*`) и группируются по типу исключения и стеку — результат группировки виден в полях `error.grouping_key`/`error.grouping_name`; для RUM-фреймов исключение из расчёта групп задаётся `apm-server.rum.exclude_from_grouping`.

### Корреляция с логами (главная связка с логовой частью стека)

Спецификация APM предписывает добавлять в события логов идентификаторы трассы:

*   `trace.id` — идентификатор сквозной трассы (32 hex);
*   `transaction.id` — идентификатор транзакции (16 hex);
*   `span.id` — идентификатор span (16 hex);
*   `error.id` — идентификатор ошибки (для событий ошибок).

Эти имена — поля [Elastic Common Schema](elastic_common_schema.md), поэтому логи и APM попадают в один семантический словарь. Механики по агентам:

*   **Java**: агент автоматически кладёт `trace.id`/`transaction.id`/`error.id` в MDC поддерживаемых фреймворков (Logback, Log4j2, slf4j); **с версии агента 1.30.0 log correlation включён по умолчанию** (отключается через `disable_instrumentations: [log-correlation]`). Для вывода в pattern логгера добавьте `%X` (все значения) или `%X{trace.id}`.
*   **Node.js**: API `apm.currentTraceIds`; при использовании ECS-плагинов для **Pino / Winston / Morgan** идентификаторы добавляются в запись автоматически.
*   **Python**: обработчик для `structlog`, декорирование `LogRecord`; реформатирование в ECS-JSON — опция `log_ecs_reformatting` (значения `off`/`override`, **по умолчанию `off`**, technical preview; с агента 6.16.0 работает без установки `ecs_logging`); готовый вывод — `transaction.id=... trace.id=... span.id=...` в текстовом формате.
*   **Go / .NET**: получение ID через API агента и ручное добавление в структурированные логи.
*   **Плоские текстовые логи без интеграций**: ID извлекаются на приёме (grok/dissect в ingest pipeline или Logstash) по формату полей ECS: `trace.id` — 32 hex-символа, `transaction.id`/`span.id` — 16 hex-символов (регулярное выражение вида `TRACE_ID=[0-9A-Fa-f]{32}` — иллюстративное, адаптируйте под формат своих логов).

Практическое следствие: **одинаковые имена полей** в логах приложения и в APM-данных позволяют в Kibana переходить из лога в трассу и обратно; без них корреляция невозможна — общий словарь описан в [ECS](elastic_common_schema.md) и [структурированном логировании](../Linux/SystemAdministration/Logging/structured_logging.md).

## Практические сценарии

### 1. Развёртывание APM Server через Fleet

1.  Fleet → Policies → **Add integration** → **Elastic APM** (интеграция `apm`).
2.  В настройках интеграции — порт (8200), TLS, **Enable RUM** (см. сценарий 4), **tail-based sampling**, anonymous rate limits. Ограничить исходные IP нативно нельзя — ставьте APM Server за reverse proxy/фаервол (в APM Server есть только rate-limit анонимных запросов по IP, см. сценарий 4).
3.  Агенты подключаются на `http(s)://<apm-server>:8200` с `secret token`/API key из настроек интеграции.
4.  Проверка: `curl -H "Authorization: Bearer $TOKEN" http://apm:8200/` → HTTP 200 и `{"build_date":...,"build_sha":...,"publish_ready":true,"version":"..."}`; без авторизации — тоже HTTP 200 (это healthcheck-эндпоинт), но без payload.

### 2. Standalone APM Server (конфиг с выходом в Kafka)

```yaml
# apm-server.yml (фрагмент)
apm-server:
  host: "0.0.0.0:8200"
  secret_token: "changeme"
  rum:
    enabled: true
    allow_origins: ['*']

output.kafka:
  hosts: ["kafka1:9092", "kafka2:9092"]
  topic: "apm"
  partition.hash:
    hash: ["service.name", "trace.id"]
```

```bash
./apm-server -e -c apm-server.yml   # -e — логи в stdout для диагностики
# → {"log.level":"info","message":"APM Server started"}
```

Дальше события APM перехватывает Logstash (input `beats`/`kafka`) и отправляет в ES — такие сценарии описаны в [Logstash: Входы и выходы](Logstash/logstash_inputs_outputs.md).

### 3. Подключение backend-агентов

**Java** (javaagent, без правки кода):

```bash
java -javaagent:/opt/elastic-apm/elastic-apm-agent.jar \
  -Delastic.apm.service_name=orders-api \
  -Delastic.apm.server_urls=http://apm:8200 \
  -Delastic.apm.environment=production \
  -Delastic.apm.secret_token=changeme \
  -jar orders-api.jar
```

**Node.js** (первые строки входного модуля):

```js
require('@elastic/apm-node').start({
  serviceName: 'orders-api',
  serverUrl: 'http://apm:8200',
  secretToken: 'changeme',
  environment: 'production'
})
```

**Python**:

```python
import elasticapm
elasticapm.init(
    service_name="orders-api",
    server_url="http://apm:8200",
    secret_token="changeme",
    environment="production",
)
```

Валидация: отправить тестовый запрос в сервис → в Kibana **APM → Services** появляется сервис; в транзакции видны span БД/HTTP; в **Errors** — ошибки при исключении.

### 4. RUM: мониторинг фронтенда

Настройка сервера (Fleet: интеграция APM → **Enable RUM**; standalone: `apm-server.rum.enabled: true`).

*   `allow_origins` — CORS-белый список источников; **по умолчанию `['*']`** — для прода сузьте до доменов приложения.
*   APM Server сам отвечает на CORS-предзапросы. Исходные IP нативно не ограничиваются — за защиту от злоупотреблений отвечает anonymous-аутентификация: `apm-server.auth.anonymous.rate_limit.event_limit` (максимум событий в секунду на один IP, **по умолчанию 300**) и `.ip_limit` (сколько уникальных IP отслеживать в LRU-кэше, **по умолчанию 1000**; суммарный потолок — произведение). Anonymous-доступ автоматически включается, когда задан `secret_token`/API key и включён RUM; сузить его можно через `allow_agent: [rum-js]` и `allow_service`.
*   `apm-server.capture_personal_data` (по умолчанию `true`) — захват client IP и User-Agent; отключайте, если эти данные не нужны для анализа (минимизация PII).
*   Для минифицированного JS загружайте **source maps** (Kibana → User Experience → Settings → Upload source maps), иначе стек-трейсы ошибок будут в закодированном виде.

**Подключение (script tag):**

```html
<script src="https://unpkg.com/@elastic/apm-rum@^5"></script>
<script>
  elasticApm.init({
    serviceName: 'store-frontend',
    serverUrl: 'https://apm.example.com:8200',
    environment: 'production'
  });
</script>
```

**Или через npm:**

```bash
npm install @elastic/apm-rum
```

```js
import { init } from '@elastic/apm-rum'
init({
  serviceName: 'store-frontend',
  serverUrl: 'https://apm.example.com:8200'
})
```

Валидация: открыть страницу → в Kibana **APM → Services → RUM**/User Experience: загрузка страницы, Web Vitals (LCP, CLS, **INP — с Kibana 8.12 / RUM-агент 5.16**), AJAX-запросы, JS-ошибки.

### 5. Корреляция логов и трасс: полный цикл

1.  Приложение пишет логи с `trace.id`/`transaction.id` (см. «Корреляция с логами»): проще всего — **ecs-logging**-библиотека или автоматическая инъекция агента (Java MDC, Node ECS-плагины).
2.  Логи уходят в тот же Elasticsearch, что и APM (Filebeat/Fluent Bit → ES) — сценарии сбора — в [Filebeat](filebeat_overview.md) и [EFK-пайплайнах](Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md).
3.  В Kibana: из **APM → Trace waterfall** — кнопка «View logs» (по `trace.id`), из лога в **Discover** — переход к транзакции. Обратная связь: показать все логи конкретной трассы можно фильтром `trace.id: "..."`.
4.  Если логи только текстовые: извлечь ID grok-процессором (формат 32/16 hex — см. «Корреляцию с логами») — и только после этого корреляция заработает.

### 6. Kibana: что смотреть

*   **APM → Services** — список сервисов, latency/throughput/error rate.
*   **Service Map** — карта зависимостей сервисов (кто к кому ходит) на основе обмена заголовками трассировки.
*   **Transactions / Trace waterfall** — последовательность span в рамках запроса, «где время».
*   **Errors** — сгруппированные исключения с контекстом транзакции.
*   **Dependencies** — внешние вызовы (БД, брокеры, HTTP).
*   **User Experience** — RUM-метрики и Web Vitals.
*   Основной обзор раздела Observability — в [Kibana: Observability](Kibana/kibana_observability.md).

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| Сервис не появляется в APM → Services | Агент не достучался до APM Server | Проверить `server_url`/порты/фаервол (8200), токен; лог агента (`-Delastic.apm.log_level=debug`), `curl http://apm:8200/` |
| `401 Unauthorized` от APM Server | Неверный/отсутствующий `secret_token`/API key | Сверить токен интеграции; у RUM-запросов должен работать anonymous-режим |
| Нет данных RUM на проде | CORS/`allow_origins`, страница не подключила скрипт | Проверить домены в `allow_origins`, консоль браузера (403 от `/intake/v2/rum/events` → CORS), правильность `serverUrl` |
| Логи есть, трассы нет (или наоборот) | Разные Elasticsearch / разные имена полей | Убедиться, что логи и APM пишутся в один кластер, а логи содержат `trace.id`/`transaction.id` |
| `trace.id` отсутствует в логах Java | Нет активной транзакции на момент лога или не выводится MDC | `%X{trace.id}` в pattern логгера; логировать внутри запроса, а не в фоновых потоках |
| Мало span / пустой waterfall | Нет инструментации нужного клиента (БД, HTTP) или сэмплинг отсёк | Включить инструментацию библиотеки в агенте, поднять `transaction_sample_rate` для сервиса |
| Ошибки JS без читаемых стеков | Нет source maps | Загрузить source maps для релиза (Kibana UX → Upload source maps) |
| APM Server отклоняет транзакции: `no matching policy` | Включён tail-based sampling, но трейс не подошёл ни под одну политику | Завершить список политик default-политикой (только `sample_rate`) |
| RUM-трафик обрезается / 429 при всплесках | Anonymous rate limit (300 событий/с на IP по умолчанию) | Поднять `apm-server.auth.anonymous.rate_limit.event_limit`/`ip_limit`; проверить `allow_origins` |
| APM Server пишет об ошибках доставки в ES | ES перегружен/недоступен, ретеншн data stream | Очередь/ретраи APM Server, здоровье кластера — [Troubleshooting индексации](Elasticsearch/elasticsearch_troubleshooting_indexing.md), ILM — [ILM и ретеншн](Elasticsearch/elasticsearch_ilm_and_retention.md) |

## Best Practices

*   **Имена сервисов стабильны и говорящие** (`orders-api`, не `svc1`): они же ключ в Service Map, alerting и central configuration.
*   **RUM-`allow_origins` сужайте до доменов приложения** — `['*']` допустим только для старта.
*   **Сэмплинг настраивайте осознанно**: 100% данных на проде дорого; head-based сэмплинг теряет редкие медленные транзакции — сочетайте с логами (которые почти всегда полные) через `trace.id`. На высоконагруженных продах — **tail-based sampling** вместо 100% head-based: сохраняйте ошибки и медленные трейсы при низкой общей ставке (только при выводе в Elasticsearch; следите за диском под хранилище сэмплера и метриками `apm-server`).
*   **Логи и телеметрию — в один кластер и один словарь (ECS)**: без общих `trace.id` корреляция не работает.
*   **Структурированные логи вместо grok**: ecs-logging дешевле и надёжнее, чем парсинг плоского текста на приёме.
*   **APM Server за reverse proxy с TLS** для RUM (браузеры требуют HTTPS на страницах с HTTPS); прямой отдачей 8200 наружу пользуйтесь только в тестах.
*   **Не храните токены в фронтенде**: backend-агенты — `secret_token`/API key, RUM — anonymous + allow-list.
*   **Центральная конфигурация вместо перевыкатки** для отладки: временно поднять уровень логирования агента из Kibana.

## Дополнительная информация

*   **[Kibana: Observability](Kibana/kibana_observability.md)** — разделы APM/User Experience, обзор метрик.
*   **[Elastic Common Schema](elastic_common_schema.md)** — поля `trace.id`, `transaction.id`, `span.id`, `error.id` и их место в словаре ECS.
*   **[Filebeat](filebeat_overview.md)**, **[EFK-пайплайн](Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** — сбор логов приложения для корреляции.
*   **[Logstash: Входы и выходы](Logstash/logstash_inputs_outputs.md)** — standalone-доставка данных APM через Kafka/Logstash.
*   **[Elastic Agent и Fleet](Elasticsearch/elastic_agent_and_fleet.md)** — управление интеграциями, политики, central management.
*   **[Elasticsearch: ILM и ретеншн](Elasticsearch/elasticsearch_ilm_and_retention.md)** — ретеншн data streams с телеметрией (по умолчанию политики задаёт плагин `apm-data`).
*   **[OTLP: протокол](../OpenTelemetry/otlp_protocol.md)** и **[OpenTelemetry: обзор](../OpenTelemetry/opentelemetry_overview.md)** — нативный приём OTLP в APM Server (см. «Нативный приём OpenTelemetry»).
*   **[Трассировки: deep dive](../Concepts/Observability_and_Monitoring/traces_deep_dive.md)** — теория head/tail-based сэмплирования и корреляции идентификаторов.
*   Структурированные логи: [Структурированное логирование](../Linux/SystemAdministration/Logging/structured_logging.md); теория корреляции идентификаторов — [Concepts: Logs deep dive](../Concepts/Observability_and_Monitoring/logs_deep_dive.md).

### Перекрытие с существующими файлами (§0.10)

Проверенные файлы (grep + RAG по базе):

*   `ELK_Stack/Kibana/kibana_observability.md` — обзор разделов Observability; настоящий файл — как устроены трассировки и корреляция. В kibana_observability добавлена ссылка сюда.
*   `ELK_Stack/elastic_common_schema.md` — SSoT по полям ECS (в т.ч. tracing-поля); здесь поля только перечислены со ссылкой, маппинг не дублируется.
*   `ELK_Stack/elastic_agent_and_fleet.md` — SSoT по Fleet в целом; здесь только сценарий добавления интеграции APM.
*   `ELK_Stack/elk_stack_overview.md` — упоминание APM одной строкой; добавлена ссылка.
*   `Concepts/Observability_and_Monitoring/{four_pillars_of_observability,logs_deep_dive,traces_deep_dive}.md` — общая теория наблюдаемости, correlation id и сэмплирование трейсов; не дублируются, только ссылки.
*   `OpenTelemetry/{opentelemetry_overview,otlp_protocol,advanced_sampling}.md` — OTel-каталог базы: протокол OTLP и tail-based sampling в OTel Collector (`groupbytrace`/`tail_sampling` processors) — другая точка применения; здесь — приём OTLP в APM Server и его собственный tail-based сэмплер. Дублирования нет, только перекрёстные ссылки.
*   Содержания APM/трассировок в базе не существовало (проверено RAG и grep: `APM`, `трассиров`, `distributed tracing`) — создание нового файла оправдано.
