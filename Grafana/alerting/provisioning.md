# Provisioning алертов в Grafana

## Определения

**Provisioning алертов** — подход Infrastructure as Code для декларативного управления правилами оповещений, контакт-пойнтами и политиками уведомлений Grafana через YAML-файлы.

**Текущая версия (февраль 2026):** Grafana 12.x, apiVersion: 1

## Базовые концепции

### Структура директорий

```
/etc/grafana/provisioning/
├── alerting/
│   ├── rules/           # Правила алертинга
│   ├── contactpoints/   # Контакт-пойнты
│   └── policies/        # Политики уведомлений
```

### Типы ресурсов

| Тип | Файл | Назначение |
| :--- | :--- | :--- |
| **Правила** | `rules/*.yaml` | Группы правил и условия срабатывания |
| **Контакт-пойнты** | `contactpoints/*.yaml` | Каналы уведомлений (Email, Slack, Telegram) |
| **Политики** | `policies/*.yaml` | Маршрутизация и группировка уведомлений |

### Структура правила

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `uid` | Уникальный идентификатор | `api-error-rate-high` |
| `title` | Название правила | `API error rate > 5%` |
| `condition` | RefId условия срабатывания | `B` |
| `for` | Время подтверждения | `5m` |
| `noDataState` | Состояние при отсутствии данных | `NoData`, `Alerting`, `OK` |
| `execErrState` | Состояние при ошибке | `Error`, `OK` |
| `labels` | Метки для маршрутизации | `severity: critical` |
| `annotations` | Описание и контекст | `summary`, `runbook` |
| `data` | Запросы и выражения | PromQL + Threshold |

### Структура данных (data)

| RefId | Тип | Назначение |
| :--- | :--- | :--- |
| `A`, `B`, `C` | Query | Запросы к источникам данных (PromQL, SQL) |
| `__expr__` | Expression | Выражения: Threshold, Reduce, Math |

## Практические сценарии

### Пример: Правило алертинга для API

**Сценарий:** Алерт при доле ошибок API > 5%.

```yaml
# provisioning/alerting/rules/api-alerts.yaml
apiVersion: 1
groups:
  - orgId: 1
    name: api-alerts
    folder: Production
    interval: 1m
    rules:
      - uid: api_error_rate_high
        title: API error rate > 5%
        condition: B
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: api
          severity: critical
        annotations:
          summary: Высокая доля ошибок API
          description: Доля 5xx ошибок превышает 5%
          runbook: Проверьте логи и зависимые сервисы
        data:
          - refId: A
            datasourceUid: prometheus_ds_uid
            model:
              expr: 'sum(rate(http_requests_total{job="api",status=~"5.."}[5m])) / sum(rate(http_requests_total{job="api"}[5m])) * 100'
              instant: false
              format: time_series
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [5] }
                  query: { params: [A] }
```

**Параметры:**

- **Запрос A:** PromQL для расчёта доли ошибок
- **Условие B:** Threshold > 5%
- **`for`:** 5m (подтверждение устойчивости)

---

### Пример: Контакт-пойнты для Email

```yaml
# provisioning/alerting/contactpoints/email.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-email
    receivers:
      - uid: team-devops-email-receiver
        type: email
        settings:
          addresses: devops@example.com,ops@example.com
          singleEmail: false
          message: |
            {{ define "email.default.message" }}
            Алерт: {{ .CommonLabels.alertname }}
            Статус: {{ .Status }}
            {{ end }}
```

---

### Пример: Контакт-пойнты для Slack

```yaml
# provisioning/alerting/contactpoints/slack.yaml
apiVersion: 1

contactPoints:
  - orgId: 1
    name: team-devops-slack
    receivers:
      - uid: slack-receiver
        type: slack
        settings:
          recipient: '#alerts'
          token: '<SLACK_BOT_TOKEN>'
          username: Grafana Alerting
          icon_emoji: ':warning:'
          mentionUsers: '@oncall'
          mentionGroups: '@devops'
          mentionChannel: here
          enabled: true
```

---

### Пример: Политики уведомлений

```yaml
# provisioning/alerting/policies/routing.yaml
apiVersion: 1

policies:
  - orgId: 1
    receiver: default-receiver
    group_by: ['alertname', 'service', 'environment']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: critical-channel
        object_matchers:
          - ['severity', '=', 'critical']
        group_wait: 10s
        group_interval: 1m
        repeat_interval: 1h
        mute_time_intervals: []
      - receiver: warning-channel
        object_matchers:
          - ['severity', '=', 'warning']
        group_wait: 1m
        group_interval: 10m
        repeat_interval: 8h
      - receiver: email-channel
        object_matchers:
          - ['severity', '=', 'info']
        group_wait: 5m
        repeat_interval: 24h
```

**Параметры маршрутизации:**

- **`group_by`:** Метки для агрегации алертов
- **`group_wait`:** Задержка перед первой отправкой
- **`group_interval`:** Интервал между группами
- **`repeat_interval`:** Интервал повторных уведомлений
- **`object_matchers`:** Селекторы для маршрутизации

---

### Пример: Полная конфигурация (все в одном)

```yaml
# provisioning/alerting/full-config.yaml
apiVersion: 1

# Группы правил
groups:
  - orgId: 1
    name: application-alerts
    folder: Production
    interval: 30s
    rules:
      - uid: high-error-rate
        title: High error rate
        condition: B
        for: 5m
        noDataState: NoData
        execErrState: Error
        labels:
          service: api
          severity: critical
          team: backend
        annotations:
          summary: Высокая доля ошибок
          runbook: https://wiki.example.com/runbooks/error-rate
        data:
          - refId: A
            datasourceUid: prometheus
            model:
              expr: 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100'
          - refId: B
            datasourceUid: __expr__
            model:
              type: threshold
              conditions:
                - evaluator: { type: gt, params: [5] }

# Контакт-пойнты
contactPoints:
  - orgId: 1
    name: critical-channel
    receivers:
      - uid: pagerduty-receiver
        type: pagerduty
        settings:
          integrationKey: '<INTEGRATION_KEY>'
  - orgId: 1
    name: warning-channel
    receivers:
      - uid: slack-receiver
        type: slack
        settings:
          recipient: '#alerts-warning'
          token: '<TOKEN>'

# Политики
policies:
  - orgId: 1
    receiver: warning-channel
    group_by: ['alertname', 'service']
    group_wait: 30s
    group_interval: 5m
    repeat_interval: 4h
    routes:
      - receiver: critical-channel
        object_matchers:
          - ['severity', '=', 'critical']
```

---

### Пример: Метки и аннотации с шаблонами

```yaml
labels:
  service: '{{ $labels.service }}'
  environment: '{{ $labels.environment }}'
  severity: '{{ if gt $value 10 }}critical{{ else }}warning{{ end }}'

annotations:
  summary: '{{ .CommonAnnotations.summary }}'
  description: |
    Метрика: {{ .CommonLabels.alertname }}
    Значение: {{ $value }}
    Время: {{ .StartsAt.Format "2006-01-02 15:04:05" }}
  runbook: 'https://wiki.example.com/runbooks/{{ .CommonLabels.alertname }}'
  dashboard: 'https://grafana.example.com/d/{{ .CommonLabels.dashboard }}'
```

## Дополнительная информация

**Связанные темы:**

- [Основные концепции Grafana Alerting](./concepts.md) — определения, состояния правил
- [Алерты для Kubernetes](./kubernetes_alerts.md) — примеры правил для K8s
- [Интеграция с Telegram](./telegram_integration.md) — настройка Telegram-уведомлений
- [Интеграция с системами эскалации](./escalation_integrations.md) — PagerDuty, Opsgenie
- [Provisioning Grafana](../grafana_provisioning.md) — общее описание provisioning
- [Best practices](./best_practices.md) — рекомендации по настройке
