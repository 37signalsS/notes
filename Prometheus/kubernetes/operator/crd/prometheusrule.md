# PrometheusRule — Концепции (CRD)

## Определения

**`kind: PrometheusRule`** — Custom Resource Definition (CRD) в Prometheus Operator для декларативного описания правил оповещения (alerting rules) и правил записи (recording rules). Operator преобразует эти ресурсы в Kubernetes ConfigMap, которые автоматически монтируются в экземпляры Prometheus Server или PrometheusAgent.

**UTF-8 Mode (Prometheus 3.0+)** — современный режим валидации имен, позволяющий использовать в `PrometheusRule` любые символы UTF-8 (точки, тире и др.) в именах метрик и лейблов.

**API version:** `monitoring.coreos.com/v1`

> **SSoT по синтаксису:** Полное описание синтаксиса PromQL и логики вычислений приведено в [Правила Recording и Alerting](../../../rules.md).

## Базовые концепции

### Принцип работы и жизненный цикл

1.  **Декларация:** Пользователь создает объект `PrometheusRule`.
2.  **Агрегация:** Operator обнаруживает ресурс и создает ConfigMap в том же пространстве имен.
3.  **Монтирование:** Путь к ConfigMap добавляется в `StatefulSet` Prometheus.
4.  **Синхронизация:** `prometheus-config-reloader` отслеживает изменения и инициирует `/-/reload`.
5.  **Валидация:** Admission Webhook проверяет синтаксис PromQL и соответствие имен выбранной схеме (`legacy` или `utf8`).

### Связь с ресурсом Prometheus

Выборка правил осуществляется через селекторы в спецификации сервера:

| Параметр | Описание |
| :--- | :--- |
| **`ruleSelector`** | Фильтрует `PrometheusRule` по меткам (labels). |
| **`ruleNamespaceSelector`** | Определяет, в каких неймспейсах искать правила (`any: true` для всех). |

### Новые возможности (2025–2026)

*   **`keep_firing_for`**: Удерживает алерт в состоянии `firing` в течение заданного времени после прекращения условия (решение проблемы дребезга/flapping).
*   **`query_offset`**: Смещает окно вычисления группы правил в прошлое (критично для Remote Write и систем с задержками скрейпинга).
*   **`limit`**: Ограничивает количество генерируемых временных серий или алертов одной группой для защиты памяти Prometheus.
*   **`status` subresource**: Отображение состояния загрузки правил непосредственно в метаданных ресурса Kubernetes.

## Практические сценарии

### Сценарий 1: Отказоустойчивый алерт с защитой от дребезга

Пример использования `keep_firing_for` для предотвращения дублирования инцидентов при кратковременных колебаниях метрик.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: critical-app-alerts
  labels:
    release: monitoring
spec:
  groups:
    - name: api-health
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status=~"5.."}[5m]) > 1
          for: 5m
          keep_firing_for: 10m  # Удерживать алерт 10 минут после исправления
          labels:
            severity: critical
          annotations:
            summary: "Высокий уровень 5xx ошибок"
            description: "Текущее значение: {{ $value }}"
```

### Сценарий 2: Правила записи с компенсацией задержек (query_offset)

Использование `query_offset` для корректной агрегации данных, поступающих через Remote Write.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aggregation-rules
spec:
  groups:
    - name: global-stats
      interval: 1m
      query_offset: 2m  # Смещение на 2 минуты в прошлое
      limit: 500        # Ограничение на 500 создаваемых серий
      rules:
        - record: job:request_duration_seconds:p95
          expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

### Сценарий 3: Поддержка имен в стиле OpenTelemetry (UTF-8)

При использовании Prometheus 3.0 и включении `nameValidationScheme: utf8`.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: otel-compat-rules
spec:
  groups:
    - name: otel-metrics
      rules:
        - alert: ServiceDown
          # Использование точек в именах лейблов
          expr: up{app.kubernetes.io/name="my-service"} == 0
          for: 2m
```

## Дополнительная информация

### Основные параметры спецификации

| Параметр | Описание | Особенности |
| :--- | :--- | :--- |
| **`groups[].interval`** | Частота вычисления группы. | По умолчанию берется из `Prometheus.spec.evaluationInterval`. |
| **`groups[].query_offset`** | Смещение во времени. | Позволяет избежать скрейпинга "дыр" в данных. |
| **`groups[].limit`** | Лимит серий/алертов. | Защита от взрыва кардинальности. |
| **`groups[].rules[].keep_firing_for`** | Время удержания алерта. | Стабилизация состояния в Alertmanager. |

### Диагностика

1.  **Проверка в UI Prometheus:** Меню `Status -> Rules`. Если правила нет в списке, оно не было выбрано селектором или отклонено при загрузке.
2.  **Проверка ConfigMap:**
    `kubectl get configmap -n monitoring -l prometheus-name=<name>`
3.  **Логи config-reloader:**
    `kubectl logs -n monitoring <prometheus-pod> -c config-reloader` — проверка успешности `/-/reload`.

### Связанные темы

*   **[Prometheus CRD](./prometheus.md)** — настройка селекторов и схем валидации имен.
*   **[Alertmanager CRD](./alertmanager.md)** — маршрутизация сгенерированных алертов.
*   **[Promtool и Best Practices](../../../promtool_and_best_practices.md)** — утилиты для проверки правил.
*   **[Reliability Scores](../../../GEMINI.md)** — методология оценки достоверности (Score: 10).

### См. также
* [Prometheus Rule Specification (Official)](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
* [Prometheus Operator API Documentation](https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.PrometheusRule)
