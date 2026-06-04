# PrometheusRule — Концепции (CRD)

## Определения

**`kind: PrometheusRule`** — Custom Resource Definition в Prometheus Operator для декларативного описания правил оповещения (alerting rules) и правил записи (recording rules). Operator преобразует ресурсы `PrometheusRule` в Kubernetes ConfigMap, которые автоматически монтируются в экземпляры Prometheus Server.

**API version:** `monitoring.coreos.com/v1`

> **См. также:** [Правила Recording и Alerting](../../../rules.md) — общие концепции, синтаксис PromQL и состояния алертов.

## Базовые концепции

### Принцип работы

1. Пользователь создаёт объект `PrometheusRule` с описанием групп правил.
2. Prometheus Operator обнаруживает новый ресурс и создаёт (или обновляет) ConfigMap в том же пространстве имён (namespace).
3. Operator обновляет список файлов правил в конфигурации Prometheus (через Kubernetes Secret).
4. Sidecar-контейнер `prometheus-config-reloader` инициирует перезагрузку конфигурации Prometheus.
5. Prometheus начинает вычислять правила с заданным в группе интервалом.

### Связь с Prometheus CRD

Экземпляр Prometheus выбирает правила для загрузки с помощью селекторов в своей спецификации:

```yaml
# В спецификации ресурса Prometheus
spec:
  ruleSelector:
    matchLabels:
      release: monitoring        # Выборка правил по меткам (labelSelector)
  ruleNamespaceSelector:
    matchNames:
      - monitoring               # Список namespace для поиска правил
```

Если `ruleSelector` не указан, Prometheus загрузит все объекты `PrometheusRule` из разрешённых пространств имён.

### Структура ресурса

Каждый объект `PrometheusRule` содержит одну или несколько групп (`groups`). Группа — это логический набор правил, выполняемых последовательно.

**Иерархия объектов:**

- `PrometheusRule`
  - `groups[]`
    - `name`: Уникальное имя группы.
    - `interval`: Интервал вычисления правил в группе (например, `30s`).
    - `rules[]`: Список определений правил.

> **Синтаксис:** Полное описание параметров `alert`, `expr`, `for`, `labels` и `annotations` приведено в SSoT-файле [Правила Recording и Alerting](../../../rules.md).

## Практические сценарии

### Настройка правил оповещения (Alerting Rules)

Пример алертов для мониторинга ошибок приложения и доступности узлов:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: app-alerts
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: application-health
      rules:
        - alert: HighErrorRate
          expr: rate(http_requests_total{status="500"}[5m]) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокий уровень ошибок в приложении"
            description: "Доля 500-х ошибок составляет {{ $value }} запросов в секунду"
        - alert: PodRestarts
          expr: increase(kube_pod_container_status_restarts_total[1h]) > 5
          for: 10m
          labels:
            severity: info
          annotations:
            summary: "Частые перезапуски подов"
```

### Настройка правил записи (Recording Rules)

Пример предварительного вычисления (агрегации) метрик для оптимизации дашбордов:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: aggregation-rules
  namespace: monitoring
  labels:
    release: monitoring
spec:
  groups:
    - name: metrics-aggregation
      rules:
        - record: job:http_requests_total:rate5m
          expr: sum(rate(http_requests_total[5m])) by (job)
```

### Мониторинг ресурсов Kubernetes

```yaml
- alert: HighMemoryUsage
  expr: (sum(container_memory_usage_bytes) by (pod) / sum(container_spec_memory_limit_bytes) by (pod)) * 100 > 90
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Высокое потребление памяти подом {{ $labels.pod }}"
```

## Дополнительная информация

### Основные параметры спецификации (spec)

| Параметр | Описание | Пример |
|---|---|---|
| **`groups`** | Массив групп правил | См. примеры выше |
| **`groups[].name`** | Имя группы (обязательно) | `node-alerts` |
| **`groups[].interval`** | Частота вычисления правил | `30s`, `1m` |
| **`groups[].rules`** | Список Alerting или Recording правил | — |

### Параметры правил (rules)

| Параметр | Применимость | Описание |
|---|---|---|
| **`alert`** | Alerting | Имя оповещения |
| **`record`** | Recording | Имя новой (вычисленной) метрики |
| **`expr`** | Оба типа | PromQL выражение для вычисления |
| **`for`** | Alerting | Время удержания условия до срабатывания |
| **`labels`** | Оба типа | Набор меток для алерта или новой метрики |
| **`annotations`** | Alerting | Метаданные (summary, description, etc.) |

### Инструменты и отладка

- **Валидация:** Используйте утилиту `promtool` для проверки синтаксиса перед деплоем.
- **Проверка в UI:** Загруженные правила можно увидеть в веб-интерфейсе Prometheus в разделе **Status -> Rules**.
- **Статус Operator:** Если правила не появились, проверьте логи Prometheus Operator на наличие ошибок при создании ConfigMap.

> **Лучшие практики:** [promtool и правила проектирования](../../../promtool_and_best_practices.md).

### Связанные ресурсы

- [Prometheus CRD](./prometheus.md) — настройка селекторов для загрузки правил.
- [Alertmanager CRD](./alertmanager.md) — управление доставкой алертов.
- [Примеры алертов](../../../concepts/metric_types/alerts.md) — типовые алерты для различных видов метрик.
