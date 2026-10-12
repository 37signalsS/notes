# Query API Jaeger

**Актуально для:** Jaeger v2.x

**Jaeger Query API** — программный интерфейс (REST и gRPC) для выборки, фильтрации и анализа распределенных трассировок, каталога сервисов, операций и графов зависимостей. В архитектуре Jaeger v2 Query Service функционирует как встроенное расширение `jaeger_query` внутри единого бинарного процесса на базе OpenTelemetry Collector. Сервис предоставляет обратную совместимость с API v1, высокопроизводительный streaming через gRPC v2/v3 и агрегированные сводки v3 для автоматизации задач DevOps, SRE и системного администрирования.

Смежные документы:
* Общая архитектура и компоненты: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Анализ задержек и критического пути: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Внутреннее устройство бэкендов хранения: **[Storage Deep Dive](./jaeger_storage_deep_dive.md)**
* Защита инфраструктуры и TLS: **[Security Hardening для Jaeger](./jaeger_security_hardening.md)**
* Визуализация и дашборды: **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)**

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **`jaeger_query` Extension** | Компонент расширения Jaeger v2, предоставляющий встроенный веб-интерфейс Jaeger UI, HTTP REST API (порты по умолчанию 16686) и gRPC API (порт 16685) над общим слоем хранения |
| **Storage Extension (`jaeger_storage`)** | Подсистема Jaeger v2, абстрагирующая постоянное хранилище (ClickHouse, Elasticsearch, Memory, Badger) от сборщиков и сервисов чтения |
| **Query API v1** | Классический REST/JSON интерфейс Jaeger (`/api/services`, `/api/operations`, `/api/traces`, `/api/dependencies`), используемый Jaeger UI, скриптами автоматизации и внешними дашбордами |
| **Query API v3** | Интерфейс нового поколения (HTTP REST и gRPC `jaeger.api_v3.QueryService`), оперирующий моделью данных OpenTelemetry (`TracesData`) и серверными агрегациями (`trace-summaries`) |
| **TraceID / SpanID** | Уникальные шестнадцатеричные идентификаторы трассы (64 или 128 бит) и отдельного спана (64 бита) в формате W3C Trace Context |
| **Lookback** | Относительный временной интервал поиска (например, `1h`, `30m`, `2d`), отсчитываемый назад от текущего момента времени |
| **Clock Skew Adjustment** | Алгоритм серверной коррекции временных меток спанов, компенсирующий сетевые задержки и рассинхронизацию системных часов серверов в распределенной среде |
| **Raw Traces** | Режим выборки трасс (`raw_traces=true` / `raw=true`), отключающий алгоритм выравнивания смещения часов и возвращающий сырые таймстемпы хранилища |
| **Search Depth** | Параметр ограничения глубины сканирования записей в хранилище при поиске трейсов (аналог лимита на уровне БД) |
| **Trace Summaries** | Компактное агрегированное представление трассы (длительность, число спанов, список сервисов, статус ошибки) без передачи полного графа спанов |

---

## Базовые концепции и архитектура

### Архитектурная роль Query Service в Jaeger v2

В Jaeger v2 архитектура компонентов унифицирована вокруг ядра OpenTelemetry Collector. В отличие от Jaeger v1, где `jaeger-query` представлял собой отдельный сервис со своим пулом драйверов БД, в v2 функции чтения инкапсулированы в модуле `jaeger_query`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Jaeger v2 Single Binary                         │
│                                                                        │
│  [OTel Receivers] ──► [Processors] ──► [jaeger_storage Exporter]       │
│                                                │                       │
│                                                ▼                       │
│  ┌────────────────────────┐         ┌───────────────────────┐          │
│  │ jaeger_query Extension │ ◄────── │ jaeger_storage Ext.   │          │
│  │                        │         │ (Connection Pools)    │          │
│  │  ├─ HTTP REST (:16686) │         └──────────┬────────────┘          │
│  │  ├─ gRPC API  (:16685) │                    │                       │
│  │  └─ Jaeger Web UI      │                    │                       │
│  └───────────▲────────────┘                    │                       │
└──────────────┼─────────────────────────────────┼───────────────────────┘
               │                                 ▼
   ┌───────────┴───────────┐         ┌───────────────────────┐
   │ Клиенты автоматизации │         │ Постоянное хранилище  │
   │ (SRE, Grafana, curl)  │         │ (ClickHouse / ES)     │
   └───────────────────────┘         └───────────────────────┘
```

**Ключевые принципы работы:**
1. **Stateless-слой:** Расширение `jaeger_query` не имеет локального изменяемого состояния и может горизонтально масштабироваться за балансировщиком нагрузки (Nginx/HAProxy).
2. **Прямое чтение из СУБД:** Запросы на выборку транслируются через внутренний интерфейс `jaeger_storage` в оптимизированные запросы к СУБД (например, `SELECT` с фильтрами по индексам в ClickHouse).
3. **Разделение портов:** По умолчанию веб-интерфейс и REST API обслуживаются на порту `16686` (TCP), а высокопроизводительный бинарный протокол gRPC — на порту `16685` (TCP).

### Сетевые порты и протоколы

| Порт | Протокол | Модуль | Назначение |
| :--- | :--- | :--- | :--- |
| **16686** | TCP / HTTP | `jaeger_query` | Веб-интерфейс Jaeger UI, REST API v1 и REST API v3 |
| **16685** | TCP / gRPC | `jaeger_query` | Высокопроизводительный gRPC Query API (`jaeger.api_v3.QueryService` и v2) |
| **13133** | TCP / HTTP | `health_check` | Health check эндпоинт проверки жизнеспособности процесса (liveness/readiness) |
| **8888** | TCP / HTTP | `telemetry` | Prometheus-метрики производительности процесса Jaeger и Query Extension |

---

### Сравнение версий Query API

| Параметр | Query API v1 | Query API v2 | Query API v3 |
| :--- | :--- | :--- | :--- |
| **Основной протокол** | HTTP/1.1 (JSON) | gRPC / HTTP (JSON) | gRPC (HTTP/2) + HTTP/1.1 REST |
| **Схема данных** | Jaeger Data Model (Thrift/JSON) | Jaeger Protobuf Model | OpenTelemetry TracesData (`OTel v1`) |
| **Потоковая передача** | Нет (буферизация всего ответа) | Да (gRPC Server Streaming) | Да (gRPC Server Streaming) |
| **Агрегированные сводки** | Отсутствуют | Отсутствуют | Поддерживаются (`/api/v3/trace-summaries`) |
| **Пагинация** | Ограниченная (`limit`, `offset`) | Cursor-based пагинация | Cursor-based пагинация (`search_depth`, маркеры продолжения) |
| **Рекомендуемое применение** | Bash-скрипты, curl, утилиты jq | Legacy gRPC клиенты | Высоконагруженные клиенты, SRE-автоматизация, Grafana |

---

### Спецификация эндпоинтов HTTP REST API

#### 1. REST API v1 (`http://<host>:16686/api/...`)

##### `GET /api/services`
Возвращает список всех зарегистрированных сервисов, присутствующих в хранилище трасс.

* **Параметры:** отсутствуют.
* **Формат ответа:**
```json
{
  "data": [
    "api-gateway",
    "auth-service",
    "billing-service",
    "order-consumer"
  ],
  "total": 4,
  "limit": 0,
  "offset": 0,
  "errors": null
}
```

##### `GET /api/operations?service=<service_name>`
Возвращает перечень операций (span names) для указанного сервиса.

* **Обязательные параметры:**
  * `service` (string) — точное имя сервиса.
* **Опциональные параметры:**
  * `spanKind` (string) — фильтрация по типу спана (`server`, `client`, `producer`, `consumer`, `internal`).

##### `GET /api/traces`
Поиск и выгрузка списка трасс по набору фильтров.

| Параметр | Тип | Формат / Пример | Описание |
| :--- | :--- | :--- | :--- |
| `service` | string | `api-gateway` | **Обязательный** (за редким исключением). Имя сервиса, участвующего в трассе |
| `operation` | string | `GET /v1/orders` | Фильтр по названию корневой или дочерней операции |
| `tags` | string (JSON) | `{"http.status_code":"500","error":"true"}` | JSON-объект с атрибутами спанов (URL-encoded в строке запроса) |
| `minDuration` | string | `500ms`, `2s`, `1.5s` | Минимальная суммарная длительность трассы (Go duration format) |
| `maxDuration` | string | `10s` | Максимальная длительность трассы |
| `start` | int64 | `1710000000000000` | Начало временного диапазона в **микросекундах** Unix Epoch |
| `end` | int64 | `1710003600000000` | Конец временного диапазона в **микросекундах** Unix Epoch |
| `lookback` | string | `1h`, `30m`, `2d` | Относительный диапазон (используется вместо явных `start`/`end`) |
| `limit` | int | `20`, `100` | Максимальное количество возвращаемых трасс (по умолчанию 100, предел 1500) |
| `raw` | bool | `true` / `false` | Отключение алгоритма выравнивания смещения часов (Clock Skew Adjustment) |

##### `GET /api/traces/{traceID}`
Возвращает полную иерархическую структуру конкретной трассы по ее идентификатору.

* **Параметры пути:**
  * `traceID` (string) — 16- или 32-значный hex-идентификатор (без префикса `0x`).
* **Опциональные параметры:**
  * `raw=true` — получение исходных спанов без алгоритмического выравнивания времени.
* **Структура ответа:**
  * `data[].traceID` — идентификатор трассы.
  * `data[].spans[]` — массив спанов: `spanID`, `operationName`, `startTime` (в микросекундах), `duration` (в микросекундах), `tags` (массив `{key, type, value}`), `logs` (события с временными метками), `references` (связи `CHILD_OF`, `FOLLOWS_FROM`).
  * `data[].processes` — словарь метаданных процессов (`serviceName`, `tags` с окружением, версией, хостом).
  * `data[].warnings` — массив предупреждений о неполноте данных или ошибках сборщика.

##### `GET /api/dependencies`
Возвращает направленный граф вызовов между сервисами за указанный период.

* **Параметры:**
  * `endTs` (int64) — конечная метка времени диапазона в **миллисекундах** Unix Epoch.
  * `lookback` (int64) — глубина окна в **миллисекундах** (например, `86400000` для 24 часов).
* **Формат ответа:**
```json
{
  "data": [
    {
      "parent": "api-gateway",
      "child": "auth-service",
      "callCount": 45210
    },
    {
      "parent": "api-gateway",
      "child": "billing-service",
      "callCount": 8940
    }
  ],
  "errors": null
}
```

---

#### 2. REST API v3 (`http://<host>:16686/api/v3/...`)

##### `GET /api/v3/trace-summaries`
Возвращает компактную агрегированную аналитику по трассам, минимизируя сетевой оверхед и нагрузку на память клиента.

* **Параметры:**
  * `service_name` (string) — имя сервиса.
  * `operation_name` (string) — фильтр по операции.
  * `start_time_min` / `start_time_max` (RFC-3339ns) — временные границы (например, `2026-10-12T10:00:00Z`).
  * `duration_min` / `duration_max` (string) — пороги длительности (например, `1s`).
  * `search_depth` (int32) — максимальное число проверяемых трасс.

##### `GET /api/v3/traces`
Полнофункциональный поиск трейсов с возвратом структуры в формате OpenTelemetry.

---

### Спецификация gRPC API v3 (`jaeger.api_v3.QueryService`)

Интерфейс gRPC на порту `16685` базируется на Protobuf-определении `jaeger.api_v3.QueryService`:

```protobuf
service QueryService {
  rpc GetTrace(GetTraceRequest) returns (stream opentelemetry.proto.trace.v1.TracesData);
  rpc FindTraces(TraceQueryParameters) returns (stream opentelemetry.proto.trace.v1.TracesData);
  rpc GetServices(GetServicesRequest) returns (GetServicesResponse);
  rpc GetOperations(GetOperationsRequest) returns (GetOperationsResponse);
}
```

**Преимущества для SRE и автоматизации:**
* **Streaming-ответ:** Сервер передает спаны чанками по мере их извлечения из базы данных через протокол HTTP/2, предотвращая буферизацию гигабайтных массивов в оперативной памяти.
* **Строгая типизация:** Сериализация через Protobuf снижает накладные расходы на парсинг в сравнении с JSON в 3–5 раз.

---

### Механизм выравнивания смещения часов (Clock Skew Adjustment)

В распределенных системах системное время хостов может расходиться на десятки и сотни миллисекунд (дрейф NTP, задержки виртуализации). Это приводит к аномалиям: спан дочернего сервиса начинается раньше, чем родительский запрос был отправлен, либо имеет отрицательную длительность.

**Алгоритм Jaeger Query:**
1. Построение дерева вызовов на основе `references` (`CHILD_OF`).
2. Оценка задержки сети туда и обратно (Round-Trip Time, RTT).
3. Если временной интервал выполнения дочернего спана $[T_{c\_start}, T_{c\_end}]$ выходит за границы интервала родителя $[T_{p\_start}, T_{p\_end}]$, Query Service линейно сдвигает шкалу времени дочернего процесса так, чтобы дочерний спан гарантированно лежал внутри родительского окна с равным распределением сетевых задержек.
4. **Отключение (`raw=true` / `raw_traces=true`):** Используется при системном аудите, анализе точности синхронизации NTP между нодами кластера и расследовании низкоуровневых сбоев ОС.

---

### Ключевые Prometheus-метрики Query Extension

Query Service экспортирует метрики на порту `8888` (эндпоинт `/metrics`), которые используются системными администраторами и SRE для мониторинга стабильности подсистемы чтения:

| Метрика | Тип | Назначение |
| :--- | :--- | :--- |
| `jaeger_query_requests_total{endpoint="..."}` | Counter | Общее число входящих запросов к Query API с разбивкой по эндпоинтам |
| `jaeger_query_latency_seconds_bucket{endpoint="..."}` | Histogram | Гистограмма времени выполнения запросов API и выборок из базы данных |
| `jaeger_query_traces_returned_total` | Counter | Суммарное количество трейсов, успешно возвращенных клиентам |
| `jaeger_storage_reads_total{status="ok|error"}` | Counter | Количество операций чтения из нижележащего хранилища (ClickHouse/ES) |
| `jaeger_storage_read_latency_seconds_bucket` | Histogram | Длительность исполнения запросов непосредственно в СУБД |

---

## Практические сценарии и настройка

### Сценарий 1: Конфигурация расширения `jaeger_query` в Jaeger v2

**Задача:** Сконфигурировать Jaeger v2 на базе Linux (on-premise сервер) для обслуживания HTTP REST (порт 16686) и gRPC API (порт 16685) с пулом подключений к локальному хранилищу ClickHouse.

**Файл конфигурации:** `/etc/jaeger/config.yaml`

```yaml
service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [nop]
      processors: []
      exporters: [nop]
  telemetry:
    metrics:
      address: "0.0.0.0:8888"

extensions:
  healthcheckv2:
    endpoint: "0.0.0.0:13133"

  jaeger_storage:
    backends:
      clickhouse_main:
        clickhouse:
          endpoint: "tcp://127.0.0.1:9000"
          database: "jaeger_v2"
          username: "jaeger_reader"
          password: "ReaderStrongPassword123"
          connection_limits:
            max_open_conns: 50
            max_idle_conns: 10
            conn_max_lifetime: "10m"

  jaeger_query:
    storage:
      traces: clickhouse_main
      dependencies: clickhouse_main
    base_path: "/"
    max_clock_skew_adjust: "5s"
    ui:
      log_access: true
    http:
      endpoint: "0.0.0.0:16686"
      cors:
        allowed_origins:
          - "http://grafana.internal:3000"
          - "http://monitoring.internal"
        allowed_headers:
          - "Authorization"
          - "Content-Type"
    grpc:
      endpoint: "0.0.0.0:16685"
      max_message_size: 104857600   # 100 MiB для крупных трейсов
```

**Применение и валидация сетевых сокетов:**

```bash
# 1. Запуск или перезапуск службы systemd
sudo systemctl restart jaeger

# 2. Проверка состояния службы
sudo systemctl is-active jaeger
# → active

# 3. Валидация открытых TCP-портов на локальном сетевом интерфейсе
ss -tulnp | grep -E ':(16686|16685|13133|8888)\b'
# → tcp   LISTEN 0      128          0.0.0.0:16686      0.0.0.0:*    users:(("jaeger",pid=4812,fd=9))
# → tcp   LISTEN 0      128          0.0.0.0:16685      0.0.0.0:*    users:(("jaeger",pid=4812,fd=10))
# → tcp   LISTEN 0      128          0.0.0.0:13133      0.0.0.0:*    users:(("jaeger",pid=4812,fd=11))
# → tcp   LISTEN 0      128          0.0.0.0:8888       0.0.0.0:*    users:(("jaeger",pid=4812,fd=12))

# 4. Проверка готовности через healthcheck
curl -sS -i http://127.0.0.1:13133/
# → HTTP/1.1 200 OK
# → Content-Length: 0
```

---

### Сценарий 2: Автоматизация поиска деградаций и ошибок через curl и jq

**Задача:** Автоматически выгрузить трассы с кодом возврата HTTP 500 за последние 30 минут для сервиса `checkout-service`, отфильтровать операции с превышением порога времени и получить TraceID для прикрепления к инциденту.

```bash
# 1. Проверка списка сервисов в хранилище
curl -sS http://127.0.0.1:16686/api/services | jq -r '.data[]'
# → api-gateway
# → checkout-service
# → payment-service
# → inventory-service

# 2. Выборка трасс с тегом ошибки (http.status_code=500) с ограничением lookback=30m
curl -sS -G "http://127.0.0.1:16686/api/traces" \
  --data-urlencode "service=checkout-service" \
  --data-urlencode 'tags={"http.status_code":"500"}' \
  --data-urlencode "lookback=30m" \
  --data-urlencode "limit=5" | jq '.data[] | {traceID: .traceID, durationMs: (.spans[0].duration / 1000), operation: .spans[0].operationName}'
# → {
# →   "traceID": "4b6e8f19a0d23c5e8821bb40f1a92e11",
# →   "durationMs": 2410.5,
# →   "operation": "POST /checkout"
# → }

# 3. Получение структуры трассы и определение проблемного спана, вернувшего ошибку
TRACE_ID="4b6e8f19a0d23c5e8821bb40f1a92e11"
curl -sS "http://127.0.0.1:16686/api/traces/${TRACE_ID}" | jq '
  .data[0].spans[] |
  select(.tags[] | (.key == "error" and .value == true) or (.key == "http.status_code" and .value == "500")) |
  {
    spanID: .spanID,
    operationName: .operationName,
    durationMs: (.duration / 1000),
    errorTags: [.tags[] | select(.key == "error" or .key == "http.status_code")]
  }'
# → {
# →   "spanID": "7a91fc82d54a11e0",
# →   "operationName": "ExecutePayment",
# →   "durationMs": 2350.2,
# →   "errorTags": [
# →     {
# →       "key": "http.status_code",
# →       "type": "string",
# →       "value": "500"
# →     },
# →     {
# →       "key": "error",
# →       "type": "bool",
# →       "value": true
# →     }
# →   ]
# → }
```

---

### Сценарий 3: Агрегированный анализ трейсов через Query API v3

**Задача:** Проверить SLO задержки после релиза нового сервиса в рамках скрипта автоматической проверки качества деплоя (Sanity Check). Если среди трасс сервиса `payment-service` доля медленных запросов (> 1 секунды) превышает 1%, вернуть ненулевой код возврата.

```bash
#!/usr/bin/env bash
set -euo pipefail

JAEGER_URL="http://127.0.0.1:16686"
SERVICE="payment-service"
THRESHOLD_DURATION="1s"
LOOKBACK="15m"

# 1. Запрос агрегированной сводки v3
TOTAL_COUNT=$(curl -sS "${JAEGER_URL}/api/traces?service=${SERVICE}&lookback=${LOOKBACK}&limit=1000" | jq '.data | length')
SLOW_COUNT=$(curl -sS "${JAEGER_URL}/api/v3/trace-summaries?service_name=${SERVICE}&duration_min=${THRESHOLD_DURATION}&lookback=${LOOKBACK}" 2>/dev/null | jq '.data | length // 0')

if [ "${TOTAL_COUNT}" -eq 0 ]; then
  echo "Предупреждение: Трассы для сервиса ${SERVICE} не найдены за последние ${LOOKBACK}"
  exit 0
fi

# 2. Расчет процента нарушений SLO
PERCENT=$(awk "BEGIN {printf \"%.2f\", (${SLOW_COUNT} / ${TOTAL_COUNT}) * 100}")

echo "Всего запросов: ${TOTAL_COUNT}, Медленнее ${THRESHOLD_DURATION}: ${SLOW_COUNT} (${PERCENT}%)"
# → Всего запросов: 420, Медленнее 1s: 2 (0.48%)

if (( $(echo "${PERCENT} > 1.0" | bc -l) )); then
  echo "Сбой SLO: процент медленных запросов превышает допустимый лимит 1%" >&2
  exit 1
else
  echo "Проверка SLO успешно пройдена"
fi
# → Проверка SLO успешно пройдена
```

---

### Сценарий 4: Запросы к gRPC Query API через grpcurl

**Задача:** Опросить gRPC API на порту `16685` без использования веб-интерфейса и JSON REST, применяя бинарный протокол через CLI-утилиту `grpcurl`.

```bash
# 1. Инспекция доступных gRPC сервисов (если включена gRPC reflection)
grpcurl -plaintext 127.0.0.1:16685 list
# → grpc.health.v1.Health
# → grpc.reflection.v1alpha.ServerReflection
# → jaeger.api_v2.QueryService
# → jaeger.api_v3.QueryService

# 2. Запрос списка зарегистрированных сервисов через v3 API
grpcurl -plaintext 127.0.0.1:16685 jaeger.api_v3.QueryService/GetServices
# → {
# →   "services": [
# →     "api-gateway",
# →     "checkout-service",
# →     "payment-service"
# →   ]
# → }

# 3. Выборка трасс по сервису через v3 gRPC
grpcurl -plaintext -d '{"service_name": "checkout-service", "search_depth": 1}' \
  127.0.0.1:16685 jaeger.api_v3.QueryService/FindTraces | head -n 25
# → {
# →   "resourceSpans": [
# →     {
# →       "resource": {
# →         "attributes": [
# →           {
# →             "key": "service.name",
# →             "value": {
# →               "stringValue": "checkout-service"
# →             }
# →           }
# →         ]
# →       }
# →     }
# →   ]
# → }
```

---

### Сценарий 5: Скрипт SRE-анализа и расчета перцентилей (Python)

**Задача:** Автономный скрипт системного администрирования для расчета перцентилей задержек (p50, p90, p99) на основе данных реальных спанов из Jaeger Query API и генерации диагностического отчета.

Файл: `/usr/local/bin/jaeger_sla_reporter.py`

```python
#!/usr/bin/env python3
"""
Автономный скрипт расчета SLA/SLO на основе Jaeger Query API.
Использует только стандартную библиотеку Python (без внешних зависимостей).
"""

import sys
import json
import urllib.request
import urllib.parse

JAEGER_HOST = "http://127.0.0.1:16686"
SERVICE_NAME = "checkout-service"
OPERATION_NAME = "POST /checkout"
LOOKBACK = "1h"
LIMIT = 500


def fetch_traces(host: str, service: str, operation: str, lookback: str, limit: int):
    params = urllib.parse.urlencode({
        "service": service,
        "operation": operation,
        "lookback": lookback,
        "limit": str(limit)
    })
    url = f"{host}/api/traces?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "SRE-Reporter/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP error: {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", [])


def calculate_percentile(sorted_data, percentile):
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * percentile
    f = int(k)
    c = f + 1
    if c < len(sorted_data):
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])
    return sorted_data[f]


def main():
    try:
        traces = fetch_traces(JAEGER_HOST, SERVICE_NAME, OPERATION_NAME, LOOKBACK, LIMIT)
    except Exception as exc:
        print(f"Ошибка запроса к Jaeger Query API: {exc}", file=sys.stderr)
        sys.exit(2)

    if not traces:
        print(f"Нет данных по сервису {SERVICE_NAME} за период {LOOKBACK}.")
        sys.exit(0)

    durations_ms = []
    error_count = 0

    for trace in traces:
        for span in trace.get("spans", []):
            if span.get("operationName") == OPERATION_NAME:
                duration_us = span.get("duration", 0)
                durations_ms.append(duration_us / 1000.0)
                # Проверка наличия тега ошибки
                for tag in span.get("tags", []):
                    if tag.get("key") == "error" and tag.get("value") is True:
                        error_count += 1
                        break

    durations_ms.sort()
    count = len(durations_ms)
    p50 = calculate_percentile(durations_ms, 0.50)
    p90 = calculate_percentile(durations_ms, 0.90)
    p99 = calculate_percentile(durations_ms, 0.99)
    error_rate = (error_count / count * 100.0) if count > 0 else 0.0

    print("=" * 55)
    print(f"Отчет производительности: {SERVICE_NAME} :: {OPERATION_NAME}")
    print(f"Глубина анализа: {LOOKBACK} | Количество транзакций: {count}")
    print("-" * 55)
    print(f"Latency P50: {p50:.2f} ms")
    print(f"Latency P90: {p90:.2f} ms")
    print(f"Latency P99: {p99:.2f} ms")
    print(f"Ошибок: {error_count} (Error Rate: {error_rate:.2f}%)")
    print("=" * 55)


if __name__ == "__main__":
    main()
```

**Тестовый запуск скрипта:**

```bash
chmod +x /usr/local/bin/jaeger_sla_reporter.py
/usr/local/bin/jaeger_sla_reporter.py
# → =======================================================
# → Отчет производительности: checkout-service :: POST /checkout
# → Глубина анализа: 1h | Количество транзакций: 342
# → -------------------------------------------------------
# → Latency P50: 124.30 ms
# → Latency P90: 412.85 ms
# → Latency P99: 1180.40 ms
# → Ошибок: 3 (Error Rate: 0.88%)
# → =======================================================
```

---

### Сценарий 6: Production Hardening: Nginx Reverse Proxy перед Jaeger Query

**Задача:** Закрыть прямой доступ к портам `16686` и `16685` на хосте, настроить Nginx reverse proxy с TLS 1.3 терминацией, ограничением частоты запросов (`rate limiting` для защиты ClickHouse от агрессивных выборок) и аутентификацией по Bearer-токену.

**Конфигурация Nginx:** `/etc/nginx/conf.d/jaeger_query_proxy.conf`

```nginx
# Ограничение частоты тяжелых запросов к Query API
limit_req_zone $binary_remote_addr zone=jaeger_query_limit:10m rate=15r/s;

# Маппинг авторизационных токенов
map $http_authorization $is_authorized {
    default 0;
    "Bearer SreProductionSecretToken2026" 1;
}

server {
    listen 443 ssl http2;
    server_name jaeger.internal;

    ssl_certificate /etc/ssl/certs/jaeger_internal.crt;
    ssl_certificate_key /etc/ssl/private/jaeger_internal.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Защита от перегрузки хранилища через чрезмерный размер тела запроса
    client_max_body_size 10M;

    # Проверка Bearer Token
    if ($is_authorized = 0) {
        return 401 '{"error": "Unauthorized: invalid or missing Bearer token"}';
    }

    # REST API и Jaeger UI
    location / {
        limit_req zone=jaeger_query_limit burst=20 nodelay;

        proxy_pass http://127.0.0.1:16686;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        # Таймауты для предотвращения зависания тяжелых запросов в СУБД
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
        proxy_send_timeout 30s;
    }

    # Отдельный высокопроизводительный gRPC эндпоинт
    location /jaeger.api_v3.QueryService/ {
        grpc_pass grpc://127.0.0.1:16685;
        grpc_read_timeout 60s;
        grpc_send_timeout 60s;
        grpc_set_header Host $host;
        grpc_set_header X-Real-IP $remote_addr;
    }
}
```

**Валидация конфигурации Nginx и защищенного доступа:**

```bash
# 1. Проверка синтаксиса конфигурации Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение конфигурации без простоя
sudo systemctl reload nginx

# 3. Попытка запроса без токена (ожидается 401)
curl -sS -k -i https://127.0.0.1/api/services
# → HTTP/2 401 
# → {"error": "Unauthorized: invalid or missing Bearer token"}

# 4. Успешный запрос с валидным Bearer-токеном
curl -sS -k -H "Authorization: Bearer SreProductionSecretToken2026" https://127.0.0.1/api/services | jq .total
# → 4
```

---

## Операции и команды

Сводная таблица ключевых команд диагностики, валидации и эксплуатации Jaeger Query API:

| Операция | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка жизнеспособности** | `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:13133/` | `# → 200`<br>Валидация liveness/readiness процесса Jaeger |
| **Список зарегистрированных сервисов** | `curl -sS http://127.0.0.1:16686/api/services \| jq .data` | `# → ["api-gateway","billing-service"]`<br>Проверка доступности каталога сервисов |
| **Список операций сервиса** | `curl -sS "http://127.0.0.1:16686/api/operations?service=api-gateway" \| jq .data` | `# → ["GET /health","POST /order"]`<br>Выгрузка операций конкретного компонента |
| **Поиск трейсов с ошибками** | `curl -sS -G "http://127.0.0.1:16686/api/traces" --data-urlencode "service=api-gateway" --data-urlencode 'tags={"error":"true"}' --data-urlencode "limit=5"` | `# → {"data":[{...}],"total":5...}`<br>Выборка дефектных транзакций за интервал |
| **Поиск тяжелых запросов по длительности** | `curl -sS "http://127.0.0.1:16686/api/traces?service=billing-service&minDuration=2s&limit=3"` | `# → {"data":[{...}],"total":3...}`<br>Фильтрация по минимальной длительности |
| **Получение сырого трейса (без Clock Skew)** | `curl -sS "http://127.0.0.1:16686/api/traces/<TRACE_ID>?raw=true"` | `# → {"data":[{"traceID":"...","spans":[...]}]}`<br>Анализ системных меток времени без сдвигов |
| **Граф зависимостей сервисов** | `curl -sS "http://127.0.0.1:16686/api/dependencies?endTs=$(date +%s%3N)&lookback=86400000"` | `# → {"data":[{"parent":"a","child":"b","callCount":120}]}`<br>Выгрузка связей за 24 часа |
| **Агрегированная сводка v3** | `curl -sS "http://127.0.0.1:16686/api/v3/trace-summaries?service_name=api-gateway&limit=10"` | `# → {"data":[{"traceID":"...","duration":"120ms"}]}`<br>Легковесный запрос сводки v3 |
| **Проверка gRPC рефлексии** | `grpcurl -plaintext 127.0.0.1:16685 list` | `# → jaeger.api_v3.QueryService`<br>Проверка доступности бинарного интерфейса |
| **Сбор метрик Query Extension** | `curl -sS http://127.0.0.1:8888/metrics \| grep "^jaeger_query_"` | `# → jaeger_query_requests_total{...} 1542`<br>Мониторинг внутреннего состояния |

---

## Типичные проблемы и устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Пустой ответ `/api/services` (`"data": []`)** | 1. Хранилище пусто (данные еще не записаны).<br>2. Ошибка подключения к ClickHouse.<br>3. `jaeger_query` настроен на неверный backend. | 1. `curl -sS http://127.0.0.1:16686/api/services`<br>2. `journalctl -u jaeger -n 100 \| grep -i "storage"` | Проверить секцию `extensions.jaeger_query.storage.traces` в `config.yaml`. Убедиться в корректности сетевого доступа и учетных данных к СУБД. |
| **Ошибка `404 Not Found` или пустой массив при запросе конкретного `traceID`** | 1. Истек TTL хранения данных в таблицах СУБД.<br>2. TraceID передан с префиксом `0x` или содержит недопустимые символы.<br>3. Спан еще не сброшен на диск из буфера коллектора. | 1. Проверить в СУБД:<br>`clickhouse-client -q "SELECT count() FROM jaeger_v2.jaeger_spans WHERE trace_id = unhex('<ID>')"` | Передавать чистый hex-идентификатор (например, `4b6e8f19a0d23c5e8821bb40f1a92e11`). Проверить настройки TTL в ClickHouse/Elasticsearch. |
| **Высокая задержка ответа `/api/traces` (Query Timeout)** | 1. Слишком широкий параметр `lookback` (например, 7 дней) без указания `operation`.<br>2. В ClickHouse отсутствуют первичные индексы по колонкам `service_name` и `start_time`.<br>3. Параметр `limit` не задан (сканирование тысяч строк). | 1. Проверить выполняющиеся запросы в ClickHouse:<br>`clickhouse-client -q "SELECT query_duration_ms, query FROM system.processes"` | 1. Ограничить `lookback` до 1–3 часов для интерактивных выборок.<br>2. Всегда передавать параметр `limit` (не более 100).<br>3. Настроить индексы и партиционирование в СУБД. |
| **Ошибка 500 при вызове `/api/dependencies`** | 1. Бэкенд хранения не поддерживает расчет зависимостей на лету (например, Badger/Memory).<br>2. Не запущена фоновая джоба генерации графа связей или пуста таблица зависимостей. | `curl -sS -i "http://127.0.0.1:16686/api/dependencies?endTs=1710000000000&lookback=86400000"` | Для production использовать ClickHouse с предрассчитанной агрегацией спанов либо задействовать встроенный механизм вычисления связей. |
| **Ошибка gRPC `RESOURCE_EXHAUSTED` (Received message larger than max)** | Трейс содержит десятки тысяч спанов и превышает дефолтный лимит gRPC (4 MiB). | В логах клиента:<br>`rpc error: code = ResourceExhausted desc = grpc: received message larger than max (X vs 4194304)` | В конфигурации `jaeger_query.grpc` увеличить значение параметра `max_message_size` (например, до `104857600` байт — 100 MiB) и настроить аналогичный лимит на клиенте. |
| **Искажение временных шкал и отрицательные задержки спанов** | Рассинхронизация часов (NTP drift) между серверами микросервисов превышает допустимый предел `max_clock_skew_adjust`. | Запрос трассы с параметром `raw=true` и сравнение меток времени `startTime` родителя и потомка. | 1. Настроить службу `chrony` или `systemd-timesyncd` на всех нодах инфраструктуры.<br>2. Увеличить `max_clock_skew_adjust` в конфигурации `jaeger_query` (например, до `10s`). |
| **Высокое потребление памяти процессом Jaeger (OOMKilled)** | Большое число параллельных запросов `/api/traces` с параметром `limit=1500` выгружают миллионы спанов в RAM. | `ps -eo pid,rss,cmd \| grep jaeger`<br>или Prometheus-метрика `process_resident_memory_bytes` | Настроить `memory_limiter` processor в пайплайне Jaeger, выставить лимит частоты запросов в Nginx и снизить максимальный `limit` на стороне API Gateway. |

---

## Лучшие практики

1. **Ограничивайте параметры `lookback` и `limit`:**
   Никогда не выполняйте запросы к `/api/traces` без указания окна времени и лимита. В production с терабайтными объемами трасс используйте `lookback` в диапазоне от `15m` до `3h` и `limit <= 100`. Для аналитики за длительные периоды (дни/недели) используйте прямые аналитические SQL-запросы к ClickHouse, а не интерактивный Query API.

2. **Кэшируйте вызовы статических метаданных:**
   Эндпоинты `/api/services` и `/api/operations` редко изменяются в течение рабочего дня. Настройте на уровне reverse proxy (Nginx) кэширование ответов с `proxy_cache_valid 200 5m`, чтобы предотвратить частые сканирующие запросы от интерфейсов и дашбордов к базе данных.

3. **Используйте выделенные Read-Only реплики хранилища:**
   В высоконагруженных окружениях направляйте запросы `jaeger_storage` для `jaeger_query` на read-only реплики ClickHouse или узлы-координаторы Elasticsearch, изолируя их от ingestion-узлов, в которые сбрасывают спаны коллекторы.

4. **Предпочитайте gRPC v3 и Server Streaming для автоматизации:**
   При написании внутренних SRE-утилит и фоновых демонов анализа качества телеметрии используйте gRPC эндпоинт (`порт 16685`) и интерфейс `jaeger.api_v3.QueryService`. Streaming позволяет обрабатывать данные потоком без риска исчерпания памяти приложения.

5. **Изолируйте доступ и терминацию TLS:**
   Не открывайте порты `16686` и `16685` в публичные сети. Размещайте Query Service во внутреннем контуре за обратным прокси-сервером (Nginx, Envoy) с принудительной авторизацией (Bearer token, mTLS) и жестким ограничением полосы пропускания (`rate limiting`).

6. **Ведите мониторинг метрик самого Query Service:**
   Настройте алерты на превышение времени выполнения запросов `jaeger_query_latency_seconds_bucket` (p95 > 2.5s) и всплески ошибок `jaeger_storage_reads_total{status="error"}`. Это позволяет обнаружить деградацию файловой системы или нехватку ресурсов СУБД до жалоб пользователей.

---

## Очистка окружения

Команды для системного администратора по остановке тестовых процессов, удалению временных файлов и освобождению сетевых портов:

```bash
# 1. Остановка службы Jaeger (systemd)
sudo systemctl stop jaeger

# 2. Остановка временного контейнера (если запуск производился через Docker)
docker stop jaeger-test 2>/dev/null || true
docker rm -f jaeger-test 2>/dev/null || true

# 3. Удаление временных скриптов и отчетов
rm -f /usr/local/bin/jaeger_sla_reporter.py
rm -f /tmp/jaeger_traces_dump.json

# 4. Проверка полного освобождения портов 16686, 16685, 13133, 8888
ss -tulpn | grep -E ':(16686|16685|13133|8888)\b' || echo "Порты Query API успешно освобождены"
# → Порты Query API успешно освобождены
```

---

## Дополнительная информация

**Смежные материалы в базе знаний:**
* **[Архитектура Jaeger](./jaeger_architecture.md)** — архитектурные уровни Jaeger v2, устройство подсистем расширений и сборщиков.
* **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)** — практическое выявление аномалий задержки, анализ критического пути и узких мест.
* **[Storage Deep Dive](./jaeger_storage_deep_dive.md)** — оптимизация хранения трейсов в ClickHouse, схемы таблиц и политики TTL.
* **[Security Hardening для Jaeger](./jaeger_security_hardening.md)** — обеспечение сетевой безопасности, mTLS и разграничение прав доступа.
* **[Интеграция Jaeger с Grafana](./jaeger_grafana_integration.md)** — настройка data source в Grafana через Jaeger HTTP/gRPC API.

**Официальные спецификации и документация:**
* [Официальная документация Jaeger Query API](https://www.jaegertracing.io/docs/latest/apis/)
* [Спецификация Protobuf Jaeger API v3](https://github.com/jaegertracing/jaeger-idl/tree/main/proto/api_v3)
* [Спецификация OpenTelemetry TracesData Protobuf](https://github.com/open-telemetry/opentelemetry-proto)
