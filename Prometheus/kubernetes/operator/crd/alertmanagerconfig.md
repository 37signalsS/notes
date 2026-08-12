# AlertmanagerConfig — Концепции (CRD)

## Определения

**`kind: AlertmanagerConfig`** — Custom Resource Definition в Prometheus Operator для декларативного описания маршрутизации и получателей алертов. Позволяет управлять подмножествами конфигурации Alertmanager (receivers, routes, inhibit rules, time intervals) через отдельные Kubernetes-объекты, без редактирования основного файла `alertmanager.yml` или Secret.

> **Концепции Alertmanager:** [Alertmanager](../../../alertmanager.md) — архитектура, конвейер обработки, ключи запуска.

## Базовые концепции

### Назначение

AlertmanagerConfig решает задачу **разделенного управления** конфигурацией: разные команды могут создавать свои маршруты и получатели в своих namespace, не затрагивая глобальную конфигурацию Alertmanager. Prometheus Operator автоматически агрегирует все AlertmanagerConfig, отобранные селекторами в [Alertmanager CRD](./alertmanager.md).

### API версии

| Версия | Статус | С версии Prometheus Operator | Примечание |
| :--- | :--- | :--- | :--- |
| **`v1beta1`** | **Stable** | `v0.57.0+` | Рекомендуемая. Поддерживает **CEL-валидацию** (`x-kubernetes-validations`), **UTF-8 matchers** (Prometheus 3.0) и подресурс **status**. |
| **`v1alpha1`** | Legacy | `v0.40.0+` | Поддерживается для обратной совместимости. Использует `muteTimeIntervals`. |

**Ключевые особенности v1beta1 (2025–2026):**

- **CEL-валидация:** Проверка ресурсов на стороне API-сервера Kubernetes. Позволяет немедленно отклонять некорректные конфигурации (например, при указании нескольких типов авторизации одновременно).
- **Строгая типизация:** Переход от `uint` к `int` с CEL-валидаторами для блокировки отрицательных значений интервалов.
- **Подресурс status:** Позволяет отслеживать `ObservedGeneration` и `Conditions` (успешность применения конфигурации).
- **MatchTypes:** Поле `regex` удалено. Используются явные операторы: `=`, `!=`, `=~`, `!~`.
- **SecretKeySelector:** Поля `name` и `key` строго обязательны.

### Глобальная конфигурация

Начиная с 2025 года, `AlertmanagerConfig` стал основным способом задания **корневой конфигурации** инстанса Alertmanager.

1.  **Назначение:** Ресурс `Alertmanager` ссылается на `AlertmanagerConfig` через `spec.alertmanagerConfiguration.name`.
2.  **Отмена принудительных меток:** В глобальном режиме Оператор **не добавляет** автоматический матчер по namespace, что позволяет создавать общекластерные маршруты.
3.  **Глобальные параметры:** Параметры вроде `smtp_smarthost` или `slack_api_url` теперь можно задавать в блоке `global` самого ресурса `Alertmanager`, который интегрируется с выбранным конфигом.

### Взаимосвязь с Alertmanager CRD

```
Alertmanager CRD (селекторы)
    ↓
  выбирает AlertmanagerConfig по меткам
    ↓
  агрегирует route-дерево и receivers
    ↓
  генерирует alertmanager.yaml в Secret
```

Alertmanager выбирает AlertmanagerConfig через селекторы в Alertmanager CRD:

```yaml
# Alertmanager CRD
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

### Структура спецификации (spec)

| Блок | Описание |
| :--- | :--- |
| **`route`** | Дерево маршрутов (обязательный) — определяет группировку и направление алертов |
| **`receivers`** | Именованные получатели (Slack, Email, PagerDuty, Webhook, Telegram и др.) |
| **`inhibitRules`** | Правила подавления алертов (взаимное глушение) |
| **`timeIntervals`** | Временные интервалы (ранее `muteTimeIntervals`) |

## Практические сценарии

### Базовая конфигурация (v1beta1)

```yaml
apiVersion: monitoring.coreos.com/v1beta1
kind: AlertmanagerConfig
metadata:
  name: slack-config
  namespace: monitoring
spec:
  route:
    groupBy: ['alertname', 'job']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
    receiver: 'slack'
    routes:
      - matchers:
          - name: severity
            value: critical
        receiver: 'slack-critical'
  receivers:
    - name: 'slack'
      slackConfigs:
        - channel: '#monitoring'
          apiURL:
            name: slack-webhook
            key: url
    - name: 'slack-critical'
      slackConfigs:
        - channel: '#alerts-critical'
          apiURL:
            name: slack-webhook-critical
            key: url
```

### Параметры маршрута (route)

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`groupBy`** | Метки для группировки алертов | `['alertname', 'job']` |
| **`groupWait`** | Задержка перед первой отправкой | `30s` |
| **`groupInterval`** | Интервал между уведомлениями группы | `5m` |
| **`repeatInterval`** | Интервал повторных уведомлений | `12h` |
| **`receiver`** | Получатель по умолчанию | `slack` |
| **`routes`** | Дочерние маршруты | Массив вложенных route |
| **`matchers`** | Условия для маршрута | Массив matchers (v1beta1) |
| **`continue`** | Продолжать обработку после совпадения | `true` |
| **`muteTimeIntervals`** | Имена timeIntervals для заглушения | `['maintenance']` |

### Матчеры (Matchers v1beta1)

В версии `v1beta1` вместо флага `regex` используется поле `matchType`:

```yaml
matchers:
  - name: severity
    value: critical          # точное совпадение (=)
  - name: team
    value: "backend|frontend"
    matchType: "=~"          # regex-совпадение
  - name: namespace
    value: production
    matchType: "!="          # отрицание
```

| `matchType` | Поведение | По умолчанию |
| :--- | :--- | :--- |
| **`=`** | Точное совпадение | Да |
| **`!=`** | Отрицание | — |
| **`=~`** | Regex-совпадение | — |
| **`!~`** | Regex-отрицание | — |

### Получатели (Receivers)

#### Slack (с обновлением сообщений)

```yaml
receivers:
  - name: 'slack'
    slackConfigs:
      - channel: '#monitoring'
        updateMessage: true # Обновлять сообщение вместо отправки нового
        apiURL:
          name: slack-webhook
          key: url
        sendResolved: true
        title: '{{ .Status | toUpper }}: {{ .CommonLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

#### Email

```yaml
receivers:
  - name: 'email'
    emailConfigs:
      - to: 'team@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        authUsername: 'alertmanager'
        authPassword:
          name: smtp-secret
          key: password
        sendResolved: true
```

#### PagerDuty

```yaml
receivers:
  - name: 'pagerduty'
    pagerdutyConfigs:
      - routingKey:
          name: pagerduty-secret
          key: routing-key
        severity: 'critical'
        description: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

#### Webhook (с кастомными заголовками)

```yaml
receivers:
  - name: 'webhook'
    webhookConfigs:
      - url: 'https://hooks.example.com/alerts'
        sendResolved: true
        httpConfig:
          httpHeaders:
            - name: "X-API-Key"
              valueFrom:
                secret:
                  name: webhook-secret
                  key: api-key
          authorization:
            type: Bearer
            credentials:
              name: webhook-secret
              key: token
```

#### Telegram (нативная поддержка)

```yaml
receivers:
  - name: 'telegram'
    telegramConfigs:
      - botToken:
          name: telegram-secret
          key: token
        chatID: 123456789
        apiURL: 'https://api.telegram.org'
        message: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

#### Jira (нативная интеграция 2026)

```yaml
receivers:
  - name: 'jira'
    jiraConfigs:
      - apiURL: 'https://jira.corp.local'
        project: 'MON'
        issueType: 'Incident'
        auth:
          password:
            name: jira-auth
            key: api-token
```

#### OpsGenie

```yaml
receivers:
  - name: 'opsgenie'
    opsgenieConfigs:
      - apiKey:
          name: opsgenie-secret
          key: api-key
        apiURL: 'https://api.opsgenie.com/v2/alerts'
        priority: 'P1'
        message: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

### Сложная маршрутизация

```yaml
spec:
  route:
    groupBy: ['alertname', 'namespace']
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
    receiver: 'default-receiver'
    routes:
      # Критические алерты → PagerDuty
      - matchers:
          - name: severity
            value: critical
        receiver: 'pagerduty'
        groupWait: 10s
        repeatInterval: 1h

      # Алерты от базы данных → DBA team
      - matchers:
          - name: team
            value: database
        receiver: 'dba-team'

      # Алерты из production → приоритет выше
      - matchers:
          - name: namespace
            value: production
        receiver: 'production-oncall'
        groupWait: 10s
```

### Правила подавления (inhibitRules)

Подавление позволяет заглушить менее значимые алерты при наличии более критичных:

```yaml
spec:
  inhibitRules:
    - sourceMatchers:
        - name: severity
          value: critical
      targetMatchers:
        - name: severity
          value: warning
      equal:
        - alertname
        - namespace
```

### Временные интервалы (timeIntervals)

Определение периодов, в которые уведомления заглушены (окна обслуживания):

```yaml
spec:
  timeIntervals:
    - name: maintenance-window
      timeIntervals:
        - times:
            - startTime: '02:00'
              endTime: '06:00'
          weekdays: ['monday:friday']
          location: 'Europe/Moscow'
```

Использование в маршруте:

```yaml
route:
  receiver: 'slack'
  muteTimeIntervals:
    - maintenance-window
```

### Секреты для получателей

Все чувствительные данные должны храниться в Kubernetes Secrets:

```bash
# Создание секрета для Slack
kubectl create secret generic slack-auth \
  --from-literal=webhook-url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring
```

Ссылка на секрет в AlertmanagerConfig:

```yaml
apiURL:
  name: slack-auth    # имя Secret
  key: webhook-url    # ключ в Secret
```

## Дополнительная информация

### Диагностика

1.  **Список ресурсов:** `kubectl get alertmanagerconfig -n monitoring`
2.  **Детали объекта и статус:** `kubectl get alertmanagerconfig slack-config -o yaml` — ищите секцию `status`.
3.  **Проверка генерации конфига:**
    `kubectl get secret alertmanager-main-generated -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d`

### Особенности агрегации

- **Уникальность имен:** Имена `receivers` и `timeIntervals` должны быть уникальны в рамках одного Alertmanager.
- **Изоляция Namespace:** В обычном режиме оператор принудительно добавляет матчер по namespace к каждому маршруту.
- **Порядок:** Маршруты из разных ресурсов добавляются в дерево в алфавитном порядке имен ресурсов.

### Связанные темы

- [Alertmanager CRD](./alertmanager.md) — развёртывание инстансов.
- [Alertmanager — концепция](../../../alertmanager.md) — архитектура обработки данных.
- [PrometheusRule CRD](./prometheusrule.md) — генерация алертов.
- [Secrets best practices](../Security/secrets_best_practices.md) — защита учетных данных.
