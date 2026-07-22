# Декларативное управление оповещениями — Provisioning

## Определения

**Provisioning (Провиженинг) алертов** — подход Infrastructure as Code (инфраструктура как код) для декларативного управления правилами оповещений, контакт-пойнтами, политиками уведомлений, интервалами подавления и шаблонами Grafana через YAML-файлы.

## Базовые концепции

### Структура директорий

Конфигурационные файлы сканируются Grafana при старте из стандартной директории:

```
/etc/grafana/provisioning/
├── alerting/
│   ├── rules/           # Правила алертинга
│   ├── contactpoints/   # Контакт-пойнты (каналы уведомлений)
│   ├── policies/        # Политики уведомлений (маршрутизация)
│   ├── mute_timings/    # Интервалы подавления
│   └── templates/       # Шаблоны сообщений
```

**Важно:** В отличие от провиженинга дашбордов, рекурсивный поиск файлов в поддиректориях `alerting/` может не поддерживаться (в зависимости от версии). Рекомендуется размещать файлы непосредственно в корне соответствующих папок.

### Типы ресурсов

| Тип | Директория | Назначение |
| :--- | :--- | :--- |
| **Правила** | `rules/` | Группы правил и условия срабатывания |
| **Контакт-пойнты** | `contactpoints/` | Каналы уведомлений (Email, Slack, Telegram) |
| **Политики** | `policies/` | Маршрутизация и группировка уведомлений |
| **Интервалы подавления** | `mute_timings/` | Определение времени, когда уведомления не должны отправляться |
| **Шаблоны** | `templates/` | Глобальные шаблоны для формирования сообщений |

### Особенности и ограничения

- **Read-only в UI:** Ресурсы, созданные через провиженинг, помечаются в интерфейсе как `Provisioned`. Их нельзя редактировать через UI, только через исходные файлы.
- **OrgId:** Почти все ресурсы требуют указания `orgId` (по умолчанию `1`).
- **UID:** Для правил и контакт-пойнтов крайне рекомендуется задавать фиксированные `uid`, чтобы избежать дублирования при перезагрузках.

### Структура правила алертинга

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `uid` | Уникальный идентификатор правила | `api-error-rate-high` |
| `title` | Название правила (отображается в интерфейсе) | `API error rate > 5%` |
| `condition` | Идентификатор (RefId) условия срабатывания | `B` |
| `for` | Время подтверждения состояния (пендинг) | `5m` |
| `noDataState` | Состояние при отсутствии данных | `NoData`, `Alerting`, `OK` |
| `execErrState` | Состояние при ошибке выполнения запроса | `Error`, `OK` |
| `labels` | Метки для маршрутизации и фильтрации | `severity: critical` |
| `annotations` | Описание, ссылки на документацию и контекст | `summary`, `runbook` |
| `data` | Массив запросов и вычислительных выражений | PromQL + Threshold |

### Структура данных (поле data)

| Идентификатор (RefId) | Тип | Назначение |
| :--- | :--- | :--- |
| `A`, `B`, `C` | Query | Запросы к источникам данных (PromQL, SQL) |
| `__expr__` | Expression | Выражения: Threshold (порог), Reduce, Math |

## Практические сценарии

### Пример: Настройка правила для API

Декларативное описание правила для мониторинга доли ошибок.

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

---

### Пример: Настройка контакт-пойнтов для Email

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

### Пример: Настройка контакт-пойнтов для Slack

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
          mentionUsers: '@oncall'
          mentionGroups: '@devops'
          mentionChannel: here
          enabled: true
```

---

### Пример: Политики уведомлений (маршрутизация)

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
```

---

### Пример: Использование шаблонов в метках и аннотациях

Шаблонизация позволяет динамически формировать сообщения на основе данных алерта.

```yaml
labels:
  service: '{{ $labels.service }}'
  severity: '{{ if gt $value 10 }}critical{{ else }}warning{{ end }}'

annotations:
  summary: '{{ .CommonAnnotations.summary }}'
  description: |
    Метрика: {{ .CommonLabels.alertname }}
    Значение: {{ $value }}
    Время: {{ .StartsAt.Format "2006-01-02 15:04:05" }}
  runbook: 'https://wiki.example.com/runbooks/{{ .CommonLabels.alertname }}'
```

---

### Пример: Настройка интервалов подавления (Mute Timings)

Позволяет отключать уведомления в определенное время (например, в нерабочие часы).

```yaml
# provisioning/alerting/mute_timings/maintenance.yaml
apiVersion: 1
muteTimes:
  - orgId: 1
    name: off-hours
    time_intervals:
      - weekdays: ['saturday', 'sunday']
      - times:
          - start: '18:00'
            end: '09:00'
```

---

### Пример: Настройка шаблонов уведомлений (Templates)

Глобальные шаблоны для переиспользования в разных контакт-пойнтах.

```yaml
# provisioning/alerting/templates/common.yaml
apiVersion: 1
templates:
  - orgId: 1
    name: standard_template
    template: |
      {{ define "standard.message" }}
      Внимание! Алерт: {{ .Labels.alertname }}
      Состояние: {{ .Status }}
      Описание: {{ .Annotations.description }}
      {{ end }}
```

---

### Безопасность и секреты

Для защиты чувствительных данных (токенов, паролей) в конфигурационных файлах рекомендуется использовать переменные окружения. Grafana поддерживает интерполяцию переменных в формате `${VAR_NAME}`.

```yaml
# Пример использования переменной окружения для токена Slack
token: ${SLACK_TOKEN}
```

*Примечание: Интерполяция должна быть включена в конфигурации Grafana (`instance_name` или глобально).*

## Дополнительная информация

**См. также:**

- [Основные концепции Grafana Alerting](./concepts.md) — терминология и состояния правил.
- [Best practices по алертингу](./best_practices.md) — рекомендации по настройке и минимизации шума.
- [Общий провиженинг Grafana](../grafana_provisioning.md) — управление источниками данных и дашбордами.
