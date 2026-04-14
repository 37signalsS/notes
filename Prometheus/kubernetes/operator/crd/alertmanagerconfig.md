# CRD AlertmanagerConfig

## Definitions

**`kind: AlertmanagerConfig`** — Custom Resource Definition в Prometheus Operator для декларативного описания маршрутизации и получателей алертов. Позволяет управлять подмножествами конфигурации Alertmanager (receivers, routes, inhibit rules, time intervals) через отдельные Kubernetes-объекты, без редактирования основного `alertmanager.yml`.

> **SSoT по концепции Alertmanager:** [Alertmanager](../../../alertmanager.md) — архитектура, конвейер обработки, ключи запуска.

## Basic Concepts

### Назначение

AlertmanagerConfig решает задачу **разделенного управления** конфигурацией: разные команды могут создавать свои маршруты и получатели в своих namespace, не затрагивая глобальный конфиг Alertmanager. Prometheus Operator автоматически агрегирует все AlertmanagerConfig, отобранные селекторами в [Alertmanager CRD](./alertmanager.md).

### API версии

| Версия | Статус | С версии Prometheus Operator | Примечание |
| :--- | :--- | :--- | :--- |
| **`v1beta1`** | Stable | `v0.57.0+` | Рекомендуемая. `regex` удалён из Matcher, `muteTimeIntervals` → `timeIntervals` |
| **`v1alpha1`** | Legacy | `v0.40.0+` | Поддерживается для обратной совместимости |

**Ключевые отличия `v1beta1` от `v1alpha1`:**

- `spec.muteTimeIntervals` переименовано в `spec.timeIntervals`
- Поле `regex` удалено из типа `Matcher` (вместо этого используется `matchType`: `=`, `!=`, `=~`, `!~`)
- `SecretKeySelector`: поля `name` и `key` стали обязательными, `optional` удалено

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

### Структура spec

| Блок | Описание |
| :--- | :--- |
| **`route`** | Дерево маршрутов (обязательный) — определяет группировку и направление алертов |
| **`receivers`** | Именованные получатели (Slack, Email, PagerDuty, Webhook, Telegram и др.) |
| **`inhibitRules`** | Правила подавления алертов (на уровне CRD) |
| **`timeIntervals`** | Временные интервалы для mute-периодов (ранее `muteTimeIntervals`) |
| **`muteTimeIntervals`** | Устарело (v1alpha1) — используйте `timeIntervals` |

## Practical Scenarios

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

### Параметры route

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`groupBy`** | Метки для группировки алертов в одно уведомление | `['alertname', 'job']` |
| **`groupWait`** | Задержка перед первой отправкой группы | `30s` |
| **`groupInterval`** | Интервал между уведомлениями одной группы | `5m` |
| **`repeatInterval`** | Интервал повторных уведомлений | `12h` |
| **`receiver`** | Получатель по умолчанию (обязательный) | `slack` |
| **`routes`** | Дочерние маршруты | Массив вложенных route |
| **`matchers`** | Условия для маршрута | Массив matchers (v1beta1) |
| **`continue`** | Продолжать обработку после совпадения | `true` / `false` |
| **`muteTimeIntervals`** | Имена timeIntervals для заглушения | `['maintenance-window']` |

### Matchers (v1beta1)

В `v1beta1` поле `regex` удалено. Вместо него используется семантика по типу значения:

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

#### Slack

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

#### Webhook

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

#### Telegram

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

| Параметр | Описание |
| :--- | :--- |
| **`sourceMatchers`** | Условия алерта-источника (подавляющего) |
| **`targetMatchers`** | Условия подавляемого алерта |
| **`equal`** | Метки, которые должны совпадать в обоих алертах |

### Временные интервалы (timeIntervals)

Определение периодов, в которые уведомления заглушены (maintenance-окна):

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

Использование в route:

```yaml
route:
  receiver: 'slack'
  muteTimeIntervals:
    - maintenance-window
```

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| **`times`** | Диапазон времени (UTC или location) | `startTime: '02:00', endTime: '06:00'` |
| **`weekdays`** | Дни недели (диапазоны допустимы) | `['monday:friday']` |
| **`days_of_month`** | Дни месяца | `['1:5', '15:20']` |
| **`months`** | Месяцы | `['january:march']` |
| **`years`** | Годы | `['2025:2026']` |
| **`location`** | Часовой пояс | `'Europe/Moscow'` |

### Секреты для получателей

Все чувствительные данные хранятся в Kubernetes Secrets:

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

Ссылка на секрет в AlertmanagerConfig:

```yaml
apiURL:
  name: slack-webhook    # имя Secret
  key: url               # ключ в Secret
```

## Additional Information

### Диагностика

| Действие | Команда |
| :--- | :--- |
| Список AlertmanagerConfig | `kubectl get alertmanagerconfig -n monitoring` |
| Детали объекта | `kubectl describe alertmanagerconfig slack-config -n monitoring` |
| Проверка генерации конфига | `kubectl get secret <am-secret> -n monitoring -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d` |

### Ограничения и особенности

- AlertmanagerConfig **агрегируется** Prometheus Operator — при конфликтах имён receivers поведение не определено
- Каждый AlertmanagerConfig должен иметь **уникальные имена receivers** в рамках одного Alertmanager
- Имя AlertmanagerConfig должно быть **уникальным в namespace**
- Изменения в AlertmanagerConfig применяются автоматически (рекозилиация ~5-10с)

### Связанные темы

- [Alertmanager CRD](./alertmanager.md) — описание развёртывания Alertmanager
- [Alertmanager — общая концепция](../../../alertmanager.md) — архитектура, конвейер обработки, ключи запуска
- [PrometheusRule CRD](./prometheusrule.md) — правила генерации алертов
- [Secrets best practices](../Security/secrets_best_practices.md) — управление секретами
