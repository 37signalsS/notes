# Интеграция Jaeger с Grafana

**Актуально для:** Jaeger v2.x / Grafana 11.x

> **Важно:** Документация описывает интеграцию **Jaeger v2** (на базе архитектуры OpenTelemetry Collector) с **Grafana 11.x**. Jaeger v1 достиг **EOL (End of Life)**.

**Интеграция Jaeger с Grafana** — это ключевой архитектурный паттерн построения единого контура Observability для DevOps и SRE инженеров. Grafana выступает центральной консолью анализа распределенных систем, объединяя поиск и визуализацию трейсов Jaeger с агрегированными метриками Prometheus (RED-метод, Exemplars) и структурированными логами Loki. Корректная связка позволяет расследовать инциденты по непрерывному пути: от обнаружения аномалии на графике задержек (p99 latency) до перехода в конкретный ошибочный спан трейса и чтения связанных с ним журналов выполнения без ручного копирования идентификаторов.

Общий обзор Jaeger: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура Jaeger v2: **[Архитектура Jaeger](./jaeger_architecture.md)**.
REST и gRPC интерфейсы: **[Query API Jaeger](./jaeger_query_api.md)**.
Анализ производительности и SPM: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Jaeger Data Source** | Встроенный источник данных Grafana (`type: jaeger`), обращающийся к HTTP Query API Jaeger для поиска и рендеринга трассировок |
| **Exemplars** | Точечные метаданные (включающие `trace_id`), прикрепляемые TSDB Prometheus к конкретным точкам временных рядов (гистограмм) |
| **tracesToLogsV2** | Спецификация конфигурации источника данных в Grafana 11.x для автоматического перехода от спана к логам в Loki с учетом временного окна и тегов |
| **tracesToMetrics** | Механизм в Grafana для генерации PromQL-запросов и построения графиков производительности сервиса непосредственно из интерфейса просмотра трейса |
| **Derived Fields** | Правила парсинга в источнике Loki, извлекающие `trace_id` из текста лога по регулярному выражению и создающие кликабельную ссылку на трейс |
| **Node Graph Panel** | Встроенный компонент визуализации Grafana, строящий интерактивный граф направленных вызовов между сервисами на основе структуры спанов |
| **Service Performance Monitoring (SPM)** | Методология мониторинга производительности сервисов на основе спанов (RED-метрики), вычисляемых процессором/коннектором `spanmetrics` |
| **RED-метод** | Модель мониторинга микросервисов: **Rate** (частота запросов), **Errors** (доля ошибок), **Duration** (длительность обработки) |
| **Span Links** | Ссылки между спанами без строгих отношений «родитель-потомок» (например, асинхронная обработка сообщений через брокер очередей) |
| **Data Links** | Настраиваемые ссылки в панелях Grafana, передающие значения переменных и меток (`${__data.fields...}`) в другие дашборды или вкладку Explore |

---

## Базовые концепции

### Архитектура интеграции

В On-Premise инфраструктуре Grafana взаимодействует с Jaeger через внутренний серверный прокси (`access: proxy`), что исключает проблемы с CORS и упрощает сетевую изоляцию компонентов внутри приватной сети или кластера:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Grafana (v11.x)                               │
│  ┌────────────────────┐   ┌───────────────────┐   ┌──────────────────┐ │
│  │ RED Dashboard      │   │ Explore (Traces)  │   │ Explore (Logs)   │ │
│  │ (Exemplar Diamonds)│   │ (Trace View +     │   │ (Derived Fields  │ │
│  │                    │   │  Node Graph)      │   │  Clickable Links)│ │
│  └─────────┬──────────┘   └─────────▲─────────┘   └────────▲─────────┘ │
│            │                        │                      │           │
│     PromQL │                  Query │ REST            LogQL│           │
│     Proxy  │                  Proxy │ :16686          Proxy│ :3100     │
└────────────┼────────────────────────┼──────────────────────┼───────────┘
             │                        │                      │
             ▼                        │                      ▼
      ┌──────────────┐                │               ┌──────────────┐
      │  Prometheus  │                │               │     Loki     │
      │  TSDB        │                │               │  Log Storage │
      └──────▲───────┘                │               └──────▲───────┘
             │ Scrape                 │                      │ Ingest
             │ (Exemplars)            │                      │
   ┌─────────┴────────────────────────▼──────────────────────┴───────────┐
   │                        Jaeger v2 / OTel Stack                       │
   │  ┌───────────────────────┐              ┌────────────────────────┐  │
   │  │  spanmetrics          │              │  jaeger_query          │  │
   │  │  (Prometheus Exporter)│              │  Extension (:16686)    │  │
   │  └──────────▲────────────┘              └───────────▲────────────┘  │
   │             │                                       │ Read          │
   │      OTLP   │                                ┌──────┴──────────┐    │
   │  ┌──────────┴────────────┐                   │ ClickHouse / ES │    │
   │  │ jaeger-collector (v2) │──────────────────▶│ Trace Storage   │    │
   │  └───────────────────────┘ Write             └─────────────────┘    │
   └─────────────────────────────────────────────────────────────────────┘
```

### Модель сквозной корреляции (Triage Pipeline)

Интеграция реализует двунаправленную навигацию между тремя столпами наблюдаемости:

1. **Метрики → Трейсы (Exemplars):**
   Приложение или OTel Collector генерирует метрики задержки с контекстом трассировки. Prometheus сохраняет дескриптор Exemplar (`trace_id`). На графике гистограммы задержек Grafana отображает ромбовидные маркеры. Клик по маркеру мгновенно открывает связанный трейс в Jaeger Data Source.
2. **Трейсы → Логи (`tracesToLogsV2`):**
   При просмотре спана в Grafana Trace View кнопка документа («Document Icon») формирует запрос в Loki. Grafana автоматически вычисляет временной диапазон спана с учетом настроенного запаса (`spanStartTimeShift` / `spanEndTimeShift`) и фильтрует логи по имени сервиса и `trace_id`.
3. **Логи → Трейсы (Derived Fields):**
   При анализе логов в Loki модуль `derivedFields` детектирует 128-битные шестнадцатеричные идентификаторы `trace_id` и подставляет активную ссылку, перенаправляющую инженера в Trace View источника Jaeger.
4. **Трейсы → Метрики (`tracesToMetrics`):**
   В контекстном меню спана доступны преднастроенные PromQL-запросы, позволяющие мгновенно оценить частоту вызовов конкретной операции и общую нагрузку на сервис в момент выполнения запроса.

---

## Практические сценарии

### Сценарий 1: Декларативная конфигурация источников данных через IaC (Provisioning)

**Ситуация:** Развертывание Grafana в production через автоматизированный provisioning с полной связкой Jaeger, Prometheus и Loki.

**Конфигурация:** Создайте манифест провижининга источников данных:

```yaml
# /etc/grafana/provisioning/datasources/observability.yaml
apiVersion: 1

datasources:
  # 1. Jaeger Data Source
  - name: Jaeger
    type: jaeger
    uid: jaeger-prod
    access: proxy
    url: http://jaeger-query.internal.net:16686
    isDefault: false
    editable: false
    jsonData:
      nodeGraph:
        enabled: true
      spanBar:
        type: Tag
        tag: http.status_code
      tracesToLogsV2:
        datasourceUid: loki-prod
        spanStartTimeShift: "-2m"
        spanEndTimeShift: "2m"
        filterBySpanID: false
        filterByTraceID: true
        tags:
          - key: service.name
            value: service
        customQuery: true
        query: '{$${__tags}} |= "$${__trace.id}"'
      tracesToMetrics:
        datasourceUid: prometheus-prod
        spanStartTimeShift: "-5m"
        spanEndTimeShift: "5m"
        tags:
          - key: service.name
            value: service
        queries:
          - name: "RPS операции"
            query: "sum(rate(traces_spanmetrics_calls_total{$${__tags}, span_name=\"$${__span.name}\"}[1m]))"
          - name: "p99 задержка сервиса"
            query: "histogram_quantile(0.99, sum(rate(traces_spanmetrics_latency_bucket{$${__tags}}[5m])) by (le))"

  # 2. Prometheus Data Source с поддержкой Exemplars для Jaeger
  - name: Prometheus
    type: prometheus
    uid: prometheus-prod
    access: proxy
    url: http://prometheus.internal.net:9090
    isDefault: true
    editable: false
    jsonData:
      httpMethod: POST
      exemplarTraceIdDestinations:
        - name: trace_id
          datasourceUid: jaeger-prod
          urlDisplayLabel: "Открыть в Jaeger Trace View"

  # 3. Loki Data Source с Derived Fields для перехода в Jaeger
  - name: Loki
    type: loki
    uid: loki-prod
    access: proxy
    url: http://loki.internal.net:3100
    isDefault: false
    editable: false
    jsonData:
      maxLines: 5000
      derivedFields:
        - name: TraceID
          matcherRegex: '(?i)(?:trace_id|traceId|traceID)[:=]\s*"?([a-f0-9]{32})'
          datasourceUid: jaeger-prod
          url: "$${__value.raw}"
          urlDisplayLabel: "Перейти к трейсу Jaeger"
```

**Валидация конфигурации через HTTP API:**

```bash
# Проверка доступности Jaeger Data Source через API Grafana
curl -sS -u admin:SecretPassword \
  http://127.0.0.1:3000/api/datasources/uid/jaeger-prod/health
# → {"status":"OK","message":"Data source is working"}

# Проверка регистрации связи с Prometheus
curl -sS -u admin:SecretPassword \
  http://127.0.0.1:3000/api/datasources/uid/prometheus-prod | jq '.jsonData.exemplarTraceIdDestinations'
# → [
# →   {
# →     "datasourceUid": "jaeger-prod",
# →     "name": "trace_id",
# →     "urlDisplayLabel": "Открыть в Jaeger Trace View"
# →   }
# → ]
```

---

### Сценарий 2: Построение RED/SPM-дашборда с поддержкой Exemplars

**Ситуация:** Создание панелей мониторинга для сервиса `billing-api` на основе метрик коннектора `spanmetrics` с переходом к проблемным трейсам.

#### 1. Rate (Частота вызовов в секунду)
```promql
sum(rate(traces_spanmetrics_calls_total{service_name="billing-api"}[1m])) by (span_name)
```

#### 2. Errors (Процент ошибок)
```promql
(
  sum(rate(traces_spanmetrics_calls_total{service_name="billing-api", status_code="STATUS_CODE_ERROR"}[1m])) by (span_name)
  /
  sum(rate(traces_spanmetrics_calls_total{service_name="billing-api"}[1m])) by (span_name)
) * 100
```

#### 3. Duration (p95 и p99 задержка с отображением Exemplars)
```promql
histogram_quantile(
  0.99,
  sum(rate(traces_spanmetrics_latency_bucket{service_name="billing-api"}[2m])) by (le, span_name)
)
```

**JSON-модель панели задержек с активными Exemplars:**

```json
{
  "title": "Billing API — p99 Latency с Exemplars",
  "type": "timeseries",
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus-prod"
  },
  "targets": [
    {
      "datasource": { "type": "prometheus", "uid": "prometheus-prod" },
      "expr": "histogram_quantile(0.99, sum(rate(traces_spanmetrics_latency_bucket{service_name=\"billing-api\"}[2m])) by (le, span_name))",
      "legendFormat": "{{span_name}} (p99)",
      "exemplar": true,
      "refId": "A"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "s",
      "custom": {
        "drawStyle": "line",
        "lineInterpolation": "smooth",
        "showPoints": "never"
      }
    }
  },
  "options": {
    "exemplars": {
      "color": "rgba(255, 99, 132, 0.9)"
    }
  }
}
```

**Валидация работы Exemplars:**
1. Откройте панель в режиме просмотра.
2. При наличии выброса задержки на графике отображаются подсвеченные маркеры.
3. При клике на маркер открывается всплывающее окно с `trace_id` и кнопкой `Query with Jaeger`.
4. Нажатие открывает окно с каскадной диаграммой спанов (Timeline) именно этого запроса.

---

### Сценарий 3: Настройка сквозного перехода Trace ↔ Logs (Jaeger ↔ Loki)

**Ситуация:** Расследование падения запроса: необходимо из деталей спана в Grafana Trace View перейти в журналы контейнера в Loki, а из строки лога исключения — обратно в трейс.

**1. Проверка формата логов приложения:**
Убедитесь, что приложение пишет структурированный JSON с идентификатором трейса в нижнем регистре:

```bash
# Тестовый запрос к сервису и проверка лога в Loki
curl -sS -X POST http://billing-api.internal.net:8080/charge \
  -H "Content-Type: application/json" \
  -d '{"amount": -10}'
# → {"error":"invalid_amount","code":400}

# Проверка записи лога через LogCLI
logcli query --addr="http://loki.internal.net:3100" \
  '{service="billing-api"} |= "invalid_amount"' --limit=1
# → 2026-10-12T14:15:00Z {"level":"error","msg":"charge failed","trace_id":"4bf92f3577b34da6a3ce929d0e0e4736","span_id":"00f067aa0ba902b7"}
```

**2. Конфигурация перехода из Loki в Jaeger:**
В файле `provisioning/datasources/observability.yaml` для источника `Loki` задано регулярное выражение:
`(?i)(?:trace_id|traceId|traceID)[:=]\s*"?([a-f0-9]{32})`

В интерфейсе Grafana Explore:
1. Выполните запрос `{service="billing-api"} |= "charge failed"`.
2. В найденной строке поле `trace_id` подсвечивается как внешняя ссылка.
3. Клик по ссылке разделяет экран (Split View) и открывает трейс `4bf92f3577b34da6a3ce929d0e0e4736` в источнике Jaeger.

**3. Конфигурация перехода из Jaeger в Loki:**
1. В правом окне (Jaeger Trace View) выберите спан `POST /charge`.
2. Нажмите на иконку документа рядом с именем спана.
3. Grafana сформирует запрос в Loki:
   `{service="billing-api"} |= "4bf92f3577b34da6a3ce929d0e0e4736"`
   с временными границами `[время_начала_спана - 2m, время_конца_спана + 2m]`.

---

### Сценарий 4: Визуализация топологии запроса через Node Graph и Service Map

**Ситуация:** SRE-инженеру требуется наглядно видеть топологию межсервисных вызовов внутри сложного трейса, чтобы локализовать сбоящий сервис без ручного разбора сотен дочерних спанов.

**Настройка:**
Включение Node Graph в конфигурации Jaeger Data Source:
```yaml
jsonData:
  nodeGraph:
    enabled: true
```

**Использование в Grafana:**
1. Перейдите в **Explore** → выберите источник **Jaeger**.
2. Введите идентификатор трейса или выполните поиск по фильтрам:
   - `Service`: `api-gateway`
   - `Operation`: `HTTP POST /checkout`
   - `Tags`: `error=true`
3. В верхней части экрана раскрывается блок **Node Graph**:
   - Зеленые/красные круги обозначают сервисы (`api-gateway`, `order-service`, `payment-service`, `postgresql`).
   - Толщина ребер показывает относительное время передачи данных.
   - Красный сектор на круге сервиса отражает процент спанов со статусом ошибки.
4. Клик по узлу фильтрует спаны в Timeline ниже, фокусируя внимание на вызовах выбранного сервиса.

---

### Сценарий 5: Автоматизация алертинга Grafana с прямыми переходами на трейсы

**Ситуация:** Настройка алерта на всплеск 5xx ошибок в Prometheus с автоматической генерацией ссылки на предзаполненный поиск в Grafana Explore / Jaeger.

**Манифест правила Grafana Alerting (Unified Alerting):**

```yaml
# /etc/grafana/provisioning/alerting/rules.yaml
apiVersion: 1

groups:
  - orgId: 1
    name: "SRE-SLO-Alerts"
    folder: "Backend Services"
    interval: "1m"
    rules:
      - uid: alert-billing-5xx
        title: "Billing Service High Error Rate"
        condition: "B"
        data:
          - refId: "A"
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "prometheus-prod"
            model:
              expr: 'sum(rate(traces_spanmetrics_calls_total{service_name="billing-api", status_code="STATUS_CODE_ERROR"}[5m])) / sum(rate(traces_spanmetrics_calls_total{service_name="billing-api"}[5m])) * 100'
              instant: true
          - refId: "B"
            relativeTimeRange:
              from: 300
              to: 0
            datasourceUid: "__expr__"
            model:
              type: "threshold"
              expression: "A"
              conditions:
                - evaluator:
                    type: "gt"
                    params: [5.0]
        for: "2m"
        labels:
          severity: "critical"
          team: "payments-sre"
        annotations:
          summary: "Error rate превысил 5% для billing-api"
          description: "Текущий уровень ошибок: {{ $value }}%. Ссылка для анализа трейсов в Grafana Explore:"
          runbook_url: "http://grafana.internal.net:3000/explore?left=%7B%22datasource%22:%22jaeger-prod%22,%22queries%22:%5B%7B%22query%22:%22service%3Dbilling-api%20error%3Dtrue%22%7D%5D%7D"
```

---

## Операции и команды

Команды диагностики и проверки интеграции для DevOps/SRE инженеров:

```bash
# 1. Проверка доступности Jaeger v2 Query API
curl -sS -I http://jaeger-query.internal.net:16686/api/services
# → HTTP/1.1 200 OK
# → Content-Type: application/json

# 2. Получение списка сервисов, зарегистрированных в Jaeger Query
curl -sS http://jaeger-query.internal.net:16686/api/services | jq .
# → {
# →   "data": [
# →     "api-gateway",
# →     "billing-api",
# →     "order-service"
# →   ],
# →   "total": 3,
# →   "limit": 0,
# →   "offset": 0,
# →   "errors": null
# → }

# 3. Проверка проксирования запросов через Grafana Data Source Proxy
curl -sS -u admin:SecretPassword \
  "http://127.0.0.1:3000/api/datasources/proxy/uid/jaeger-prod/api/traces?service=billing-api&limit=1" \
  | jq '.data | length'
# → 1

# 4. Проверка включения поддержки Exemplars в TSDB Prometheus
curl -sS http://prometheus.internal.net:9090/api/v1/status/flags \
  | jq '.data["enable-feature"]'
# → "exemplar-storage"

# 5. Выборка сырых данных с Exemplars из Prometheus через HTTP API
curl -sS 'http://prometheus.internal.net:9090/api/v1/query_exemplars?query=traces_spanmetrics_latency_bucket{service_name="billing-api"}&start=1773312000&end=1773312300' \
  | jq '.data[0].exemplars[0]'
# → {
# →   "seriesLabels": {
# →     "le": "0.5",
# →     "service_name": "billing-api"
# →   },
# →   "exemplars": [
# →     {
# →       "labels": {
# →         "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
# →       },
# →       "value": "0.412",
# →       "timestamp": 1773312150.123
# →     }
# →   ]
# → }

# 6. Проверка извлечения логов по trace_id из Loki
curl -sS -G "http://loki.internal.net:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={service="billing-api"} |= "4bf92f3577b34da6a3ce929d0e0e4736"' \
  --data-urlencode 'limit=1' | jq '.data.result[0].values[0][1]'
# → "2026-10-12T14:15:00Z {\"level\":\"error\",\"msg\":\"charge failed\",\"trace_id\":\"4bf92f3577b34da6a3ce929d0e0e4736\"}"
```

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Data source connection error: 502 / Connection refused** | Jaeger Query недоступен по указанному URL или порт 16686 блокируется сетевым экраном | `curl -Iv http://jaeger-query:16686/api/services` из контейнера/хоста Grafana | Проверить запуск сервиса Jaeger v2, корректность внутреннего DNS-имени и правил Firewall |
| **Exemplars не отображаются на графиках задержек** | 1. Prometheus запущен без флага хранилища Exemplars.<br>2. В панели Grafana отключена опция `Exemplars` | Проверить флаги: `curl -sS http://prometheus:9090/api/v1/status/flags \| grep exemplar`. Проверить метрику в UI Prometheus | Добавить в аргументы запуска Prometheus `--enable-feature=exemplar-storage`. В Grafana Panel Options активировать тумблер **Exemplars** |
| **При переходе по Exemplar открывается пустой трейс** | Различие в формате `trace_id` (например, 64-бит vs 128-бит) или время жизни трейсов в бэкенде Jaeger истекло | Проверить наличие трейса через REST API: `curl http://jaeger-query:16686/api/traces/<id>` | Настроить retention трейсов в ClickHouse/бэкенде Jaeger в соответствии с окном хранения метрик Prometheus |
| **Кнопка "Logs for this span" выдает `No data found`** | 1. Несовпадение тегов спана и меток Loki (`service.name` vs `service` или `job`).<br>2. Ошибочный временной сдвиг | В Grafana Explore посмотреть сгенерированный LogQL-запрос в поле истории | Скорректировать секцию `tags` и `mappedTags` в `tracesToLogsV2`. Задать `spanStartTimeShift: "-5m"` для компенсации асинхронной записи логов |
| **Кликабельная ссылка TraceID в Loki отсутствует** | Регулярное выражение `matcherRegex` в `derivedFields` не соответствует реальному синтаксису лога | Проверить сырую строку лога: `trace_id=...`, `traceId=...` или `traceID=...` | Обновить `matcherRegex` на универсальный: `(?i)(?:trace_id\|traceId\|traceID)[:=]\s*"?([a-f0-9]{32})` |
| **CORS ошибки в браузере при запросе к Jaeger** | В настройках источника Grafana выбран режим `access: browser` вместо `access: proxy` | В DevTools браузера ошибки вида `Blocked by CORS policy` | Переключить режим доступа на `Server (default / proxy)` в настройках источника |
| **Зависание Grafana при открытии трейсов с >10 000 спанов** | Высокая сложность отрисовки DOM дерева при детализации объемных пакетных процессов | Падение вкладки браузера, высокое потребление памяти процессом браузера | Установить фильтрацию в спанах, включить tail-sampling на уровне OTel Collector для отсечения избыточных спанов |

---

## Лучшие практики

1. **Инфраструктура как код (Provisioning as Code):**
   Все источники данных (Jaeger, Prometheus, Loki) и базовые дашборды должны управляться исключительно через Git-репозиторий и монтироваться в `/etc/grafana/provisioning/`. Запретите ручное редактирование источников в проде (`editable: false`).
2. **Использование единого стандарта OpenTelemetry Semantic Conventions:**
   Убедитесь, что все приложения передают стандартные имена атрибутов: `service.name`, `http.request.method`, `http.response.status_code`. Это гарантирует прозрачную работу шаблонов `tracesToLogsV2` и `tracesToMetrics` без кастомных трансформаций.
3. **Безопасность и разграничение доступа:**
   Размещайте Jaeger Query API внутри изолированного сетевого сегмента. Доступ пользователей организуйте только через аутентификацию Grafana с назначением ролей (RBAC). При необходимости используйте заголовок `X-Scope-OrgID` для мультиарендности.
4. **Контроль кардинальности метрик spanmetrics:**
   Не добавляйте уникальные динамические атрибуты спанов (`user_id`, `order_id`, `url_with_ids`) в dimensions метрик `spanmetrics`. В метрики должны попадать только агрегированные теги (`service.name`, `span.name`, `status_code`), а детальные идентификаторы должны исследоваться в трейсах и логах.
5. **Согласование TTL данных:**
   Синхронизируйте время хранения (Retention Time) между логами в Loki, метриками в Prometheus и трейсами в Jaeger (ClickHouse). Несогласованный retention приводит к «битым» ссылкам при переходе от долговременных метрик к уже удаленным трейсам.

---

## Очистка окружения

Команды удаления тестовых конфигураций и дашбордов:

```bash
# 1. Удаление файла декларативного провижининга
rm -f /etc/grafana/provisioning/datasources/observability.yaml

# 2. Перезагрузка источников данных через Grafana Admin API без рестарта сервиса
curl -sS -X POST -u admin:SecretPassword \
  http://127.0.0.1:3000/api/admin/provisioning/datasources/reload
# → {"message":"Datasources reloaded"}

# 3. Удаление временного дашборда по UID через API
curl -sS -X DELETE -u admin:SecretPassword \
  http://127.0.0.1:3000/api/dashboards/uid/billing-perf-dashboard
# → {"title":"Billing API — p99 Latency с Exemplars","message":"Dashboard billing-perf-dashboard deleted","id":12}

# 4. Остановка локального демонстрационного стека Docker Compose
docker compose -f docker-compose.observability.yaml down -v
# → Removing network observability_default
# → Removing volume observability_grafana_data
# → Removing volume observability_prometheus_data
```

---

## Дополнительная информация

**Смежные материалы базы знаний:**

* Архитектура и компоненты: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Спецификация REST и gRPC: **[Query API Jaeger](./jaeger_query_api.md)**
* Анализ производительности и расчет SLI/SLO: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Корреляция телеметрии и Exemplars в Grafana: **[Grafana: Корреляция телеметрии](../Grafana/grafana_correlation_exemplars.md)**
* Управление источниками данных: **[Grafana: Источники данных](../Grafana/grafana_datasources.md)**
* Декларативный провижининг: **[Grafana: Провижининг](../Grafana/grafana_provisioning.md)**
* Мониторинг как код: **[Мониторинг как код](../Grafana/monitoring_as_code.md)**

### См. также

* [Официальная документация Grafana: Jaeger Data Source](https://grafana.com/docs/grafana/latest/datasources/jaeger/)
* [Официальная документация OpenTelemetry: Span Metrics Connector](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/spanmetricsconnector)
* [Официальная спецификация OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)

