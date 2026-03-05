# CRD AlertmanagerConfig

## Определения

**`kind: AlertmanagerConfig`** — Custom Resource Definition для описания маршрутизации и получателей алертов в Alertmanager.

## Пример конфигурации

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
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

## Основные параметры spec

### Route

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`groupBy`** | Группировка алертов | `['alertname', 'job']` |
| **`groupWait`** | Ожидание перед отправкой | `30s` |
| **`groupInterval`** | Интервал между группами | `5m` |
| **`repeatInterval`** | Интервал повторения | `12h` |
| **`receiver`** | Получатель по умолчанию | `slack` |
| **`routes`** | Дочерние маршруты | См. ниже |
| **`matchers`** | Матчеры для маршрута | `severity: critical` |

### Matchers

```yaml
matchers:
  - name: severity
    value: critical
    regex: false
  - name: team
    value: "backend|frontend"
    regex: true
```

## Получатели (Receivers)

### Slack

```yaml
receivers:
  - name: 'slack'
    slackConfigs:
      - channel: '#monitoring'
        apiURL:
          name: slack-webhook
          key: url
        sendResolved: true
        title: '{{ .Status | toUpper }}: {{ .CommonLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

### Email

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

### PagerDuty

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

### Webhook

```yaml
receivers:
  - name: 'webhook'
    webhookConfigs:
      - url: 'https://hooks.example.com/alerts'
        sendResolved: true
        httpConfig:
          bearerTokenSecret:
            name: webhook-secret
            key: token
          tlsConfig:
            caFile: /etc/alertmanager/secrets/ca.crt
```

### OpsGenie

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

### Telegram

```yaml
receivers:
  - name: 'telegram'
    telegramConfigs:
      - botToken:
          name: telegram-secret
          key: token
        chatID: '123456789'
        apiURL: 'https://api.telegram.org'
        message: '{{ .CommonLabels.alertname }}: {{ .CommonAnnotations.summary }}'
```

## Пример сложной маршрутизации

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
      
      # Предупреждения → Slack
      - matchers:
          - name: severity
            value: warning
        receiver: 'slack-warning'
        repeatInterval: 6h
      
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

## Селектор Alertmanager

Alertmanager выбирает AlertmanagerConfig по селектору:

```yaml
# В Alertmanager CRD
spec:
  alertmanagerConfigSelector:
    matchLabels:
      release: monitoring
  alertmanagerConfigNamespaceSelector:
    matchNames:
      - monitoring
```

## Секреты

Все чувствительные данные (webhook URL, пароли, API keys) должны храниться в Kubernetes Secrets:

```bash
# Создание секрета для Slack
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring

# Создание секрета для PagerDuty
kubectl create secret generic pagerduty-secret \
  --from-literal=routing-key='your-routing-key' \
  -n monitoring
```

## Связанные темы

* **[Alertmanager CRD](./alertmanager.md)** — описание Alertmanager
* **[Alertmanager](../../alertmanager.md)** — базовая настройка
* **[PrometheusRule](./prometheusrule.md)** — правила алертинга
