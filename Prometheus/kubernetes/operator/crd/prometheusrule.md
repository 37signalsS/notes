# PrometheusRule — Концепции (CRD)

## Определения

**`kind: PrometheusRule`** — Custom Resource Definition (CRD) в Prometheus Operator для декларативного описания правил оповещения (alerting rules) и правил записи (recording rules). Operator преобразует эти ресурсы в Kubernetes ConfigMap, которые автоматически монтируются в экземпляры Prometheus Server или PrometheusAgent.

**UTF-8 Mode (Prometheus 3.0+)** — современный режим валидации имен, позволяющий использовать в `PrometheusRule` любые символы UTF-8 (точки, тире и др.) в именах метрик и лейблов. Это критично для нативной совместимости с OpenTelemetry.

**API version:** `monitoring.coreos.com/v1`

> **Справочная информация:** Подробное описание синтаксиса PromQL и логики вычислений приведено в файле [Правила Recording и Alerting](../../../rules.md).

## Базовые концепции

### Принцип работы и жизненный цикл

1.  **Декларация:** Пользователь создает объект `PrometheusRule`.
2.  **Валидация:** Admission Webhook проверяет синтаксис PromQL. Если правила некорректны, создание ресурса будет отклонено с ошибкой.
3.  **Агрегация:** Operator обнаруживает ресурс и создает ConfigMap в том же пространстве имен.
4.  **Монтирование:** Оператор обновляет `StatefulSet` Prometheus, добавляя путь к ConfigMap в аргументы запуска.
5.  **Синхронизация:** Контейнер `prometheus-config-reloader` внутри пода отслеживает изменения в смонтированных файлах и инициирует HTTP-запрос к `/-/reload`.
6.  **Привязка (Binding):** Через подресурс `status` можно отследить, какие именно инстансы Prometheus в данный момент используют этот набор правил.

### Связь с ресурсом Prometheus

Выборка правил осуществляется через селекторы в спецификации сервера:

| Параметр | Описание |
| :--- | :--- |
| **`ruleSelector`** | Фильтрует `PrometheusRule` по меткам (labels). |
| **`ruleNamespaceSelector`** | Определяет, в каких неймспейсах искать правила (`any: true` для всех доступных). |

### Новые возможности (2025–2026)

*   **`keep_firing_for`**: Удерживает алерт в состоянии `firing` в течение заданного времени после прекращения условия. Это решает проблему «дребезга» (flapping) и предотвращает закрытие инцидентов при кратковременных просадках метрик.
*   **`query_offset`**: Смещает окно вычисления всей группы правил в прошлое. Необходимо для корректной работы с системами, имеющими задержку записи (Remote Write, Thanos). Требует Prometheus >= v2.53.0.
*   **`limit`**: Ограничивает количество генерируемых временных серий (для recording) или алертов (для alerting) одной группой. Защищает память Prometheus от взрывного роста кардинальности.
*   **Подресурс `status` и `Bindings`**: Позволяет увидеть список ресурсов (Prometheus, PrometheusAgent), которые успешно загрузили данный `PrometheusRule`.

## Практические сценарии

### Сценарий 1: Отказоустойчивый алерт с защитой от дребезга

Пример использования `keep_firing_for` для стабилизации состояния алерта в Alertmanager.

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
          keep_firing_for: 10m  # Алерт остается активным 10 минут после исправления
          labels:
            severity: critical
          annotations:
            summary: "Высокий уровень 5xx ошибок"
            description: "Текущее значение: {{ $value }}"
```

### Сценарий 2: Правила записи с компенсацией задержек (query_offset)

Использование `query_offset` для агрегации данных, которые приходят с лагом в 1-2 минуты.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aggregation-rules
spec:
  groups:
    - name: global-stats
      interval: 1m
      query_offset: 2m  # Смещение вычислений на 2 минуты назад
      limit: 1000       # Ограничение: не более 1000 серий на группу
      rules:
        - record: job:request_duration_seconds:p95
          expr: histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

### Сценарий 3: Поддержка имен в стиле OpenTelemetry (UTF-8)

При включении `nameValidationScheme: utf8` в ресурсе Prometheus (версия 3.0+).

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
          # Допустимы точки и спецсимволы в именах лейблов без экранирования
          expr: up{service.name="auth-provider", cloud.region="us-east-1"} == 0
          for: 2m
```

## Дополнительная информация

### Основные параметры спецификации

| Параметр | Описание | Особенности |
| :--- | :--- | :--- |
| **`groups[].interval`** | Частота вычисления группы. | Если не задан, используется `evaluationInterval` из Prometheus. |
| **`groups[].query_offset`** | Временное смещение. | Минимизирует "дыры" при Remote Write. |
| **`groups[].limit`** | Лимит рядов/алертов. | Предотвращает OOM при ошибках в селекторах. |
| **`groups[].rules[].keep_firing_for`** | Удержание состояния. | Параметр уровня конкретного правила. |
| **`groups[].partial_response_strategy`** | Стратегия при частичном ответе. | Используется в Thanos Ruler (`warn` или `abort`). |

### Диагностика и отладка

1.  **Проверка статуса ресурса:**
    `kubectl get prometheusrule <name> -o yaml` — проверьте секцию `status.conditions` на наличие ошибок валидации.
2.  **Проверка привязок (Bindings):**
    Убедитесь, что ваш инстанс Prometheus присутствует в `status.bindings`. Если его нет — проверьте `ruleSelector` в объекте `Prometheus`.
3.  **Логи config-reloader:**
    `kubectl logs -n monitoring <prometheus-pod> -c config-reloader` — здесь отображаются ошибки, возникшие при попытке перезагрузить конфигурацию в самом Prometheus.
4.  **Валидация через Promtool:**
    Перед деплоем рекомендуется проверять правила локально: `promtool check rules rules.yaml`.

### Связанные темы

*   **[Prometheus CRD](./prometheus.md)** — настройка селекторов и схем валидации имен.
*   **[Alertmanager CRD](./alertmanager.md)** — маршрутизация уведомлений.
*   **[Promtool и лучшие практики](../../../promtool_and_best_practices.md)** — рекомендации по написанию эффективных правил.

### См. также
* [Prometheus Rule Specification (Official)](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
* [Prometheus Operator API Documentation (v1)](https://prometheus-operator.dev/docs/operator/api/#monitoring.coreos.com/v1.PrometheusRule)

