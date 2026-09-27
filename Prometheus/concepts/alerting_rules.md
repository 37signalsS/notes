# Alerting Rules в Prometheus

> **См. также:** [Recording Rules и Alerting Rules](../rules.md), [Alertmanager](../alertmanager.md), [Алерты для типов метрик](./metric_types/alerts.md), [Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).

## Определения

* **Alerting Rule** — правило, определяющее условие (PromQL-выражение), при выполнении которого Prometheus генерирует алерт и отправляет его в [Alertmanager](../alertmanager.md). Правило содержит имя алерта (`alert`), выражение-условие (`expr`), время ожидания (`for`), дополнительные метки (`labels`) и аннотации (`annotations`).
* **Состояние алерта (Alert State)** — жизненное состояние алерта: `Inactive` (условие не выполнено), `Pending` (условие выполнено, но `for` еще не прошло), `Firing` (условие выполнено дольше `for`), `Resolved` (условие больше не выполняется).
* **Дребезг (Flapping)** — ситуация, когда алерт быстро переключается между `Firing` и `Resolved` из-за кратковременных колебаний метрики вокруг порогового значения. Решается увеличением `for` или использованием `keep_firing_for`.
* **Группа алертов (Alert Group)** — логическое объединение алертов в Alertmanager, обрабатываемых как единое уведомление. Группировка снижает количество уведомлений при массовых сбоях.

## Основные концепции

### Жизненный цикл алерта

1. **Вычисление:** Prometheus периодически вычисляет `expr` в alerting rule.
2. **Переход в Pending:** Если выражение истинно, алерт переходит в состояние `Pending`.
3. **Переход в Firing:** Если выражение остается истинным дольше `for`, алерт переходит в `Firing` и отправляется в Alertmanager.
4. **Доставка:** Alertmanager получает алерт, выполняет дедупликацию, группировку, ингибирование и маршрутизацию.
5. **Resolved:** Когда выражение становится ложным, алерт переходит в `Resolved` (с учетом `keep_firing_for`).

### Параметры alerting rule

| Параметр | Описание | Рекомендации |
|:---|:---|:---|
| `alert` | Имя алерта | Уникальное, отражающее проблему (например, `HighErrorRate`) |
| `expr` | PromQL-выражение | Условие срабатывания. Результат — вектор метрик |
| `for` | Время ожидания | Минимальная длительность истинности перед Firing. Рекомендация: `>= 3-5 * evaluation_interval` |
| `keep_firing_for` | Удержание в Firing | (v2.42+) Время удержания в Firing после нормализации метрики. Предотвращает дребезг |
| `labels` | Дополнительные метки | Маршрутизация в Alertmanager (например, `severity: critical`) |
| `annotations` | Аннотации | Описание проблемы, шаблоны `{{ $labels.name }}`, `{{ $value }}` |

### Интеграция с Alertmanager

```
Prometheus ──HTTP POST──> Alertmanager ──> Уведомления (Slack, Email, PagerDuty)
```

**Архитектура (два независимых этапа):**

1. **Детектирование (Prometheus):** Вычисление PromQL-выражений из alerting rules. При срабатывании — HTTP POST в Alertmanager.
2. **Обработка (Alertmanager):** Дедупликация → Группировка → Ингибирование → Тишина → Маршрутизация → Доставка.

### Группировка, ингибирование, тишина

| Механизм | Назначение | Пример |
|:---|:---|:---|
| **Группировка** | Объединение алертов по общим меткам в одно уведомление | Вместо 100 сообщений о падении подов — одно сводное |
| **Ингибирование** | Подавление зависимых алертов при активации родительского | Если кластер недоступен (`ClusterDown`) — не оповещать о падении подов |
| **Тишина** | Временное отключение уведомлений | Плановые работы: создать silence на 2 часа |

### Шаблоны в аннотациях

Доступные переменные в аннотациях:
- `{{ $labels.<name> }}` — значение метки из результата запроса
- `{{ $value }}` — числовое значение выражения в момент срабатывания
- `{{ $externalLabels.<name> }}` — глобальные метки Prometheus

## Практические примеры

### Базовый алерт на ошибки

```yaml
groups:
- name: http_alerts
  rules:
  - alert: HighErrorRate
    expr: sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Error rate > 5%"
      description: "Error rate is {{ $value | humanizePercentage }}"
```

### Алерт с keep_firing_for против дребезга

```yaml
groups:
- name: api.alerts
  rules:
  - alert: HighErrorRate
    expr: |
      sum by (instance) (rate(http_requests_total{status=~"5.."}[5m]))
      /
      sum by (instance) (rate(http_requests_total[5m])) > 0.05
    for: 5m
    keep_firing_for: 10m
    labels:
      severity: critical
    annotations:
      summary: "High error rate on {{ $labels.instance }}"
```

### Ингибирование в Alertmanager

```yaml
inhibit_rules:
  - source_matchers: [alertname="ClusterDown"]
    target_matchers: [alertname=~"Pod.*"]
    equal: [cluster]
```

### Маршрутизация по severity

```yaml
route:
  receiver: 'default-slack'
  group_by: ['alertname', 'service']
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
    - match:
        severity: warning
      receiver: 'slack-warnings'
```

## Дополнительная информация

* **Подробное описание параметров правил:** [Recording и Alerting Rules](../rules.md)
* **Архитектура Alertmanager:** [Alertmanager](../alertmanager.md)
* **Алерты по типам метрик:** [Алерты для типов метрик](./metric_types/alerts.md)
* **Рекомендации SRE:** [Рекомендации по мониторингу и алертингу](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)
* **Мета-мониторинг Alertmanager:** [Мета-мониторинг](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)
* **Валидация правил:** [promtool и лучшие практики](../promtool_and_best_practices.md)
