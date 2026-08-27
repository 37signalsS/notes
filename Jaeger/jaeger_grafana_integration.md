# Интеграция Jaeger с Grafana

> **Важно:** Документация описывает **Jaeger v2** (текущая версия). Jaeger v1 достиг **EOL (End of Life)**.

**Интеграция Jaeger с Grafana** — это набор практик по подключению Jaeger как источника данных, построению дашбордов RED/Service Performance, настройке корреляции трейсов с метриками и логами, а также использованию Exemplars для перехода от метрик к детальным трейсам. В 2026 году Grafana является стандартным интерфейсом для observability, и без правильной интеграции Jaeger теряет половину своей ценности — возможность быстро коррелировать всплеск метрик с конкретными запросами.

Общий обзор Jaeger: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Query API: **[Query API Jaeger](./jaeger_query_api.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Jaeger Data Source** | Источник данных Grafana, подключающийся к Jaeger Query API для поиска и визуализации трейсов |
| **Service Performance** | Встроенный дашборд Grafana для Jaeger, показывающий RED-метрики (Rate, Errors, Duration) на основе спанов |
| **Trace to Metrics** | Возможность перехода от агрегированной метрики (график p99) к конкретному трейсу через Exemplars |
| **Trace to Logs** | Корреляция трейсов с логами по `trace_id`/`span_id` через Derived Fields |
| **Trace to Traces** | Связь между связанными трейсами (например, producer → consumer) через Span Links |
| **Exemplars** | Примеры конкретных спанов, прикрепленные к гистограммам метрик spanmetrics |
| **Provenance** | Механизм в Grafana для отслеживания происхождения дашбордов и источников данных |

---

## Базовые концепции

### Архитектура интеграции

```
┌─────────────┐     OTLP      ┌─────────────┐     Query API     ┌─────────────┐
│ Applications│──────────────▶│   Jaeger    │◀─────────────────▶│   Grafana   │
│             │  4317/4318    │  Collector  │    16686          │   UI        │
└─────────────┘               └──────┬──────┘                   └──────┬──────┘
                                     │                               │
                              ┌──────▼──────┐                ┌──────▼──────┐
                              │  Storage    │                │ Prometheus  │
                              │ (ClickHouse)│                │ (spanmetrics)│
                              └─────────────┘                └─────────────┘
```

Grafana подключается к Jaeger через два канала:
1. **Jaeger Data Source** — прямое подключение к Query API (порт 16686) для поиска трейсов.
2. **Prometheus Data Source** — подключение к метрикам spanmetrics для RED-дашбордов и Exemplars.

### Типы источников данных в Grafana 2026

| Источник | Роль в интеграции с Jaeger |
| :--- | :--- |
| **Jaeger** | Поиск трейсов, Trace View, Service Performance |
| **Prometheus** | Метрики spanmetrics (calls_total, duration_bucket), Exemplars |
| **Loki** | Логи с Derived Fields для перехода к трейсам |
| **Tempo** | Альтернативное хранилище трейсов (не используется, если есть Jaeger) |

---

## Практические сценарии

### Сценарий 1: Настройка Jaeger Data Source в Grafana

**Ситуация:** Необходимо добавить Jaeger как источник данных в Grafana для поиска трейсов.

**Через UI:**

1. Открыть **Connections → Data sources → Add new data source → Jaeger**.
2. Указать URL: `http://jaeger-query.observability.svc:16686`.
3. Нажать **Save & test**.

**Через provisioning (IaC):**

```yaml
# provisioning/datasources/jaeger.yaml
apiVersion: 1

datasources:
  - name: Jaeger
    type: jaeger
    access: proxy
    url: http://jaeger-query.observability.svc:16686
    isDefault: false
    jsonData:
      tracesToLogs:
        - datasourceUid: loki
        - tags: ["traceID", "spanID"]
        - mappedTags: [{ key: "traceID", value: "trace_id" }]
      tracesToMetrics:
        - datasourceUid: prometheus
        - tags: [{ key: "service_name", value: "service" }, { key: "operation_name", value: "operation" }]
      serviceMap:
        datasourceUid: prometheus
      spanBar:
        type: None
    editable: true
```

**Валидация:**

1. Перейти в **Explore** → выбрать источник **Jaeger**.
2. Выполнить поиск по сервису `api-gateway` за последний час.
3. Убедиться, что трейсы отображаются в Timeline.

### Сценарий 2: Построение RED-дашборда с корреляцией traces ↔ metrics

**Ситуация:** Нужен дашборд для мониторинга сервиса `payment` с возможностью перехода от метрик к трейсам.

**Панель 1: Rate (RPS)**

```promql
sum(rate(calls_total{service_name="payment"}[5m])) by (operation_name)
```

**Панель 2: Errors (Error Rate)**

```promql
sum(rate(calls_total{service_name="payment", status_code="5xx"}[5m])) by (operation_name) / sum(rate(calls_total{service_name="payment"}[5m])) by (operation_name) * 100
```

**Панель 3: Duration (p99 latency)**

```promql
histogram_quantile(0.99, sum(rate(duration_bucket{service_name="payment"}[5m])) by (le, operation_name))
```

**Корреляция с трейсами:**

1. В настройках панели Duration включить **Exemplars**.
2. Убедиться, что `spanmetrics` экспортирует метрики с атрибутами `trace_id` и `span_id`.
3. При наведении на пик на графике появляются ромбики-exemplars — клик открывает трейс в Jaeger UI.

### Сценарий 3: Настройка Trace to Logs (Jaeger → Loki)

**Ситуация:** Необходимо из трейса переходить к логам конкретного запроса.

**Предварительные требования:**
- Loki установлен и добавлен как источник данных в Grafana.
- Приложения логируют `trace_id` и `span_id` в формате OpenTelemetry.

**Настройка в Jaeger Data Source:**

```yaml
jsonData:
  tracesToLogs:
    - datasourceUid: loki
    - tags: ["traceID", "spanID"]
    - mappedTags:
        - { key: "traceID", value: "trace_id" }
```

**Или через Loki Derived Fields:**

1. Открыть источник данных **Loki** → **Derived fields** → **Add derived field**.
2. Name: `Trace ID`, Type: `Link`, URL: `http://jaeger-query:16686/trace/{%trace_id%}`.
3. Regex: `trace_id=(\w+)`.

**Валидация:**

1. Найти трейс в Jaeger UI.
2. Скопировать `traceID` и выполнить поиск в Loki: `{service_name="payment"} |~ "trace_id=abc123"`.
3. Убедиться, что логи соответствующего запроса найдены.

### Сценарий 4: Service Performance Monitoring (SPM) дашборд

Grafana предоставляет встроенный шаблон дашборда для Jaeger Service Performance.

**Установка:**

1. В Grafana открыть **Dashboards → New → Import**.
2. Ввести ID дашборда: `14915` (Jaeger Service Performance) или создать кастомный.
3. Выбрать источники данных: Jaeger + Prometheus.

**Кастомный SPM дашборд (JSON):**

```json
{
  "dashboard": {
    "title": "Service Performance: payment",
    "panels": [
      {
        "title": "Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(calls_total{service_name=\"payment\"}[5m])) by (operation_name)",
            "legendFormat": "{{operation_name}}"
          }
        ]
      },
      {
        "title": "Error Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(calls_total{service_name=\"payment\",status_code=\"5xx\"}[5m])) by (operation_name) / sum(rate(calls_total{service_name=\"payment\"}[5m])) by (operation_name) * 100",
            "legendFormat": "{{operation_name}}"
          }
        ]
      },
      {
        "title": "p99 Latency",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.99, sum(rate(duration_bucket{service_name=\"payment\"}[5m])) by (le, operation_name))",
            "legendFormat": "{{operation_name}}"
          }
        ]
      }
    ]
  }
}
```

### Сценарий 5: Автоматизация алертинга через Grafana

**Ситуация:** Нужно настроить алерт при росте p99 latency или error rate.

**Алерт 1: p99 latency > 500ms**

```yaml
# В Grafana Alerting → New Alert Rule
expr: histogram_quantile(0.99, sum(rate(duration_bucket{service_name="payment"}[5m])) by (le)) > 500000000
for: 5m
labels:
  severity: critical
annotations:
  summary: "High p99 latency for payment service"
  description: "p99 latency is {{ $value }}ms"
```

**Алерт 2: Error rate > 1%**

```yaml
expr: (sum(rate(calls_total{service_name="payment",status_code="5xx"}[5m])) / sum(rate(calls_total{service_name="payment"}[5m])) * 100) > 1
for: 3m
labels:
  severity: warning
annotations:
  summary: "High error rate for payment service"
```

**Валидация:**

1. Искусственно вызвать рост latency: `ab -n 1000 -c 50 -s 2000 http://payment:8080/api`.
2. Убедиться, что алерт перешел в состояние `Firing`.
3. Проверить уведомление в Slack/Email.

---

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Jaeger data source недоступен** | Неверный URL или порт 16686 закрыт | Проверить `kubectl port-forward` или Service, убедиться что Query запущен |
| **Exemplars не отображаются** | spanmetrics не настроен или Prometheus не имеет `--enable-feature=exemplar-storage` | Проверить конфигурацию spanmetrics и флаг Prometheus |
| **Trace to Logs не работает** | Loki не имеет поля `trace_id` или неверный `mappedTags` | Проверить логи Loki на наличие `trace_id`, обновить Derived Fields |
| **SPM дашборд пустой** | Нет метрик spanmetrics в Prometheus | Проверить, что `spanmetrics` processor включен в пайплайн Collector |
| **Долгий поиск трейсов** | ClickHouse/ES без индексов или большой объем данных | Настроить индексы, ограничить lookback, добавить кэширование |

---

## Лучшие практики

1.  **Provisioning как код:** Храните конфигурацию источников данных и дашбордов в Git через provisioning-файлы.
2.  **Единый стандарт атрибутов:** Используйте семантические конвенции OpenTelemetry (`service.name`, `http.method`) для совместимости с Service Performance.
3.  **Exemplars для перехода к трейсам:** Включайте Exemplars в `spanmetrics` — это сокращает время диагностики с минут до секунд.
4.  **Trace to Logs:** Обязательно логируйте `trace_id` и `span_id` в структурированном виде (JSON) для корреляции с Loki.
5.  **Алерты наRED:** Настраивайте алерты на p99 latency и error rate, а не на средние значения.

---

## Очистка окружения

```bash
# Удаление дашбордов (если использовались временные)
# Через UI: Dashboard → Settings → Delete

# Удаление provisioning файлов (если использовались)
rm -f provisioning/datasources/jaeger.yaml
rm -f provisioning/dashboards/jaeger.json

# Очистка Docker
docker compose down -v
```

---

## Дополнительная информация

**Смежные темы:**

* Query API: **[Query API Jaeger](./jaeger_query_api.md)**
* Service Performance Monitoring: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Spanmetrics processor: **[Анализ производительности с Jaeger](./jaeger_performance_analysis.md)**
* Корреляция метрик и трейсов (Exemplars): **[Grafana: Корреляция телеметрии](../Grafana/grafana_correlation_exemplars.md)**
* Источники данных Grafana: **[Grafana: Источники данных](../Grafana/grafana_datasources.md)**

### См. также

* [Grafana Jaeger Data Source Documentation](https://grafana.com/docs/grafana/latest/datasources/jaeger/)
* [Jaeger Service Performance Dashboard](https://grafana.com/grafana/dashboards/14915)
