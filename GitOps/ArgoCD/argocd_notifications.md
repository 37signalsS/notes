# ArgoCD Notifications — настройка уведомлений

**Актуально для:** Argo CD 3.5.x

> **Статус:** Уведомления — официальная часть проекта Argo CD. Ранее (до v3.x) функционал
> реализовывался отдельным компонентом из `argoproj-labs/argocd-notifications`; репозиторий
> архивирован, поддержка перенесена в core. Контроллер уведомлений остаётся отдельным
> Deployment (`argocd-notifications-controller`), **не** объединённым с
> `argocd-application-controller`.

ArgoCD Notifications — компонент, непрерывно следящий за событиями жизненного цикла
приложений (sync, health, операции) и отправляющий сообщения во внешние системы: Slack,
Email, Telegram, PagerDuty, GitHub Status, Alertmanager, Grafana и др.

## Определения

- **ArgoCD Notifications** — контроллер уведомлений внутри проекта Argo CD, работает отдельным Deployment.
- **Триггер (Trigger)** — логическое условие (Expression Language / `antonmedv/expr`), при выполнении которого отправляется уведомление.
- **`oncePer`** — поле триггера, дедуплицирующее уведомления: отправляет лишь раз при смене значения указанного поля.
- **Шаблон (Template)** — Go-шаблон, формирующий тело сообщения с подстановкой переменных.
- **Сервис (Service)** — конфигурация подключения к внешней платформе (API-токен, URL вебхука).
- **Получатель (Recipient)** — адресат в формате `<service>:<destination>` (например, `slack:my-channel`).
- **Подписка (Subscription)** — связь триггера, приложения и получателя; задаётся через аннотации Application или глобальную запись `subscriptions` в ConfigMap.
- **Глобальные подписки (System-level subscriptions)** — подписки, объявленные в `argocd-notifications-cm`, применяющиеся ко всем приложениям по селектору.
- **Самообслуживание (Self-service notifications)** — режим, позволяющий tenant-приложениям определять свои сервисы и подписки в локальном namespace (через `--self-service-notification-enabled`).
- **Контекст (Context)** — пользовательская карта ключей/значений, доступная во всех шаблонах.
- **Каталог (Catalog)** — набор готовых триггеров и шаблонов, устанавливуемый одной командой.
- **Dedup память** — аннотации приложения, в которых кэшируются ID отправленных уведомлений для предотвращения дублей.

## Архитектура

### Компоненты

Уведомления реализованы отдельным контроллером, не частью `argocd-application-controller`:

```
┌──────────────────────────────────────────────────────────────┐
│  ArgoCD Notifications — Архитектура                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  Kubernetes  │    │ argocd-      │    │  External    │   │
│  │  Cluster     │◀───│ notifications│───▶│  Services    │   │
│  │  (App Events)│    │ -controller  │    │ (Slack,      │   │
│  └──────────────┘    │ (Deployment) │    │  Telegram,   │   │
│         │            └──────────────┘    │  Email, ...) │   │
│         │                   │            └──────────────┘   │
│         ▼                   ▼                   │           │
│  ┌──────────────┐    ┌──────────────┐           │           │
│  │ argocd-notif │    │ argocd-notif │           │           │
│  │ -cm          │    │ -secret      │           │           │
│  │ (ConfigMap)  │    │ (Secret)     │           │           │
│  └──────────────┘    └──────────────┘           │           │
│         │                   │                   │           │
│         ▼                   ▼                   ▼           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Triggers     │    │ Templates    │    │ Services     │  │
│  │ (Conditions) │    │ (Messages)   │    │ (Delivery)   │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Ресурсы конфигурации

| Ресурс | Назначение | Содержимое |
| :--- | :--- | :--- |
| `argocd-notifications-cm` | Основная конфигурация | Триггеры (`trigger.*`), шаблоны (`template.*`), сервисы (`service.*`), подписки (`subscriptions`), `defaultTriggers`, `context` |
| `argocd-notifications-secret` | Чувствительные данные | Токены, пароли, private key, ссылки на вебхуки |
| `argocd-cmd-params-cm` | Параметры контроллера | `notificationscontroller.*`, `application.namespaces` |

### Жизненный цикл уведомления

1. **Событие:** изменение статуса Application (sync, health, operation).
2. **Оценка подписок:** контроллер проверяет локальные аннотации и глобальные подписки.
3. **Фильтрация:** вычисляется `when`-условие триггера через `antonmedv/expr` с поддержкой optional chaining (`?.`).
4. **`oncePer`-проверка:** если значение `oncePer` совпало с кэшированным — уведомление пропускается.
5. **Рендеринг:** шаблон исполняется с переменными `.app`, `.appProject`, `.context`, `.secrets`, `.serviceType`, `.recipient` и функциями `time`, `strings`, `repo`, `sync`.
6. **Дедупликация:** ID уведомления кэшируется в аннотации Application (`NotificationProcessed`).
7. **Доставка:** вызов API сервиса (Slack webhook, Telegram Bot API, SMTP, GitHub Checks API и т.д.).

## Предварительные требования

1. **Kubernetes:** v1.22+.
2. **Argo CD:** v3.x (v3.5.4 — текущая на 2026 г.). Notifications работает как отдельный `argocd-notifications-controller`, установленный вместе с `install.yaml`.
3. **Доступ к API мессенджеров:** токены, вебхуки, SMTP-учётные данные.
4. **Secret для токенов:** `argocd-notifications-secret` с ключами, на которые ссылаются сервисы через `$<key>`.

## Установка

### 1. Базовая установка (входит в Argo CD)

Уведомления поставляются вместе с Argo CD — в `install.yaml` уже присутствуют Deployment, Service, Role, ConfigMap (`argocd-notifications-cm`) и Secret (`argocd-notifications-secret`).

### 2. Установка каталога (рекомендуется)

Каталог содержит готовые триггеры и шаблоны (`trigger.*` и `template.*`):

```bash
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/notifications_catalog/install.yaml
```

Каталог добавляет 8 встроенных триггеров и соответствующие шаблоны.

### 3. Проверка

```bash
kubectl get deployment argocd-notifications-controller -n argocd
kubectl get configmap argocd-notifications-cm -n argocd -o yaml
```

## Конфигурация

### Структура ConfigMap

Все настройки находятся в `argocd-notifications-cm` (data):

| Ключ | Описание |
| :--- | :--- |
| `service.<type>(.<name>)` | Конфигурация сервиса доставки |
| `trigger.<name>` | Определение триггера (YAML-список условий) |
| `template.<name>` | Шаблон сообщения |
| `subscriptions` | Глобальные подписки (YAML-список) |
| `defaultTriggers` | Триггеры по умолчанию для всех подписок |
| `defaultTriggers.<service>` | Триггеры по умолчанию для конкретного сервиса |
| `context` | Глобальные переменные для шаблонов (YAML key-value) |

### Переменные шаблонов

Внутри шаблона доступны три основных объекта и набор функций:

| Переменная | Описание |
| :--- | :--- |
| `.app` | Объект `Application` (metadata, spec, status) |
| `.appProject` | Объект `AppProject`, связанный с приложением |
| `.context` | Пользовательская карта ключей/значений |
| `.secrets` | Доступ к Secret (только если self-service **выключен**) |
| `.serviceType` | Тип сервиса доставки (`slack`, `email`, ...) |
| `.recipient` | Адресат уведомления |

**Функции (через точку доступа):**

| Функция | Описание | Пример |
| :--- | :--- | :--- |
| `.time.Now()` | Текущее время | `{{time.Now}}` |
| `.time.Parse(s)` | Разбор RFC3339 строки | `{{call .time.Parse .app.status.operationState.startedAt}}` |
| `.strings.ReplaceAll(s,old,new)` | Замена в строке | `{{call .strings.ToUpper .app.metadata.name}}` |
| `.repo.GetCommitMetadata(sha)` | Метаданные коммита | `{{call .repo.GetCommitMetadata .app.status.sync.revision}}` |
| `.repo.FullNameByRepoURL(url)` | `owner/repo` | `{{call .repo.FullNameByRepoURL .app.spec.source.repoURL}}` |
| `.sync.GetInfoItem(app, name)` | Параметр info из sync | `{{call .sync.GetInfoItem .app "commitUrl"}}` |

**Часто используемые переменные `.app`:**

| Переменная | Описание | Значения |
| :--- | :--- | :--- |
| `.app.metadata.name` | Имя приложения | `my-app` |
| `.app.metadata.namespace` | Namespace | `argocd` |
| `.app.status.sync.status` | Статус синхронизации | `Synced`, `OutOfSync` |
| `.app.status.health.status` | Статус здоровья | `Healthy`, `Degraded`, `Progressing` |
| `.app.status.operationState.phase` | Фаза операции | `Succeeded`, `Failed`, `Running`, `Error` |
| `.app.status.operationState.message` | Сообщение об ошибке | `ComparisonError`, `ApplyOutOfSync` |
| `.app.status.sync.revision` | Текущий коммит | `abc1234` |
| `.app.spec.source.repoURL` | Репозиторий | `https://github.com/org/repo` |
| `.app.spec.source.path` | Путь | `k8s/overlays/prod` |

**Настройка часового пояса контроллера:**

```yaml
# Deployment argocd-notifications-controller
spec:
  template:
    spec:
      containers:
      - name: argocd-notifications-controller
        env:
        - name: TZ
          value: Europe/Moscow
```

### Поддерживаемые сервисы (21 типов)

| Сервис | Service key | Примечание |
| :--- | :--- | :--- |
| Slack | `service.slack` | attachments, deliveryPolicy, groupingKey |
| Telegram | `service.telegram` | Bot API |
| Email (SMTP) | `service.email` | host, port, from, username, password |
| MS Teams (Webex) | `service.teams` | **Deprecated, выведен из эксплуатации** (был deprecated March 2026) |
| Teams Workflows | `service.teams-workflows` | Рекомендуемая замена для Office 365 Connectors |
| PagerDuty | `service.pagerduty` | integration key |
| PagerDuty v2 | `service.pagerdutyv2` | serviceKeys (map) |
| Opsgenie | `service.opsgenie` | API URL + token |
| Grafana | `service.grafana` | API каналы/онтемлы |
| Alertmanager | `service.alertmanager` | webhook URL |
| Google Chat | `service.googlechat` | вебхук |
| Mattermost | `service.mattermost` | webhook URL |
| Rocket.Chat | `service.rocketchat` | webhook URL |
| Pushover | `service.pushover` | API token + user key |
| Webex | `service.webex` | webhook URL |
| AWS SQS | `service.awssqs` | очередь сообщений |
| NATS | `service.nats` | очередь сообщений |
| GCP PubSub | `service.gcppubsub` | очередь сообщений |
| New Relic | `service.newrelic` | API key |
| Webhook | `service.webhook` | произвольный HTTP endpoint |
| GitHub Status | `service.github` | commit status через GitHub App |
| Console | `service.console` | вывод в stdout (для CLI `template notify`) |

### Анонимные (named) сервисы

Один тип сервиса можно настроить несколько раз с разными именами:

```yaml
data:
  service.slack.prod: |
    token: $slack-prod-token
    signingSecret: $slack-prod-signing-secret
  service.slack.dev: |
    token: $slack-dev-token
```

Подписка указывает имя сервиса:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-succeeded.prod: my-channel
    notifications.argoproj.io/subscribe.on-sync-succeeded.dev: my-channel
```

### Триггеры

#### Встроенные триггеры (из каталога)

| Триггер | Условие (when) | oncePer | Описание |
| :--- | :--- | :--- | :--- |
| **on-created** | `"true"` | `app.metadata.name` | Приложение создано |
| **on-deleted** | `app.metadata.deletionTimestamp != nil` | `app.metadata.name` | Приложение удаляется |
| **on-deployed** | `app.status?.operationState.phase in ['Succeeded']` | `app.status.sync.revision` | Успешный деплой (once per revision) |
| **on-health-degraded** | `app.status.health.status == 'Degraded'` | `app.status?.operationState.syncResult.revision` | Проблемы со здоровьем |
| **on-sync-running** | `app.status?.operationState.phase in ['Running']` | `app.status?.operationState.syncResult.revision` | Синхронизация в процессе |
| **on-sync-succeeded** | `app.status?.operationState.phase in ['Succeeded']` | `app.status?.operationState.syncResult.revision` | Успешная синхронизация |
| **on-sync-failed** | `app.status?.operationState.phase in ['Error', 'Failed']` | `app.status?.operationState.syncResult.revision` | Ошибка синхронизации |
| **on-sync-status-unknown** | `app.status.sync.status == 'Unknown'` | `app.status?.operationState.syncResult.revision` | Неизвестный статус |

> **Важно:** используйте `?.` (optional chaining) для доступа к `operationState`, так как он отсутствует до начала операции.

#### Кастомные триггеры

```yaml
data:
  trigger.on-high-risk-change: |
    - when: |
        app.status?.operationState.phase in ['Error',
        and app.metadata.labels['criticality'] == 'high'
      send: [risk-template]
      oncePer: app.status?.operationState.syncResult.revision
```

#### Default triggers

Если подписка не указывает триггер, используется `defaultTriggers`:

```yaml
data:
  defaultTriggers: |
    - on-sync-status-unknown
  defaultTriggers.slack: |
    - on-sync-running
    - on-sync-succeeded
```

Аннотация без имени триггера:

```yaml
annotations:
  notifications.argoproj.io/subscribe.slack: my-channel
```

### Методы подписки

#### 1. Локальные подписки (Application annotations)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.slack: my-channel
    notifications.argoproj.io/subscribe.on-health-degraded.telegram: 123456789
```

#### 2. Глобальные подписки (System-level)

В `argocd-notifications-cm`:

```yaml
data:
  subscriptions: |
    - recipients: [slack:alerts-channel]
      triggers: [on-sync-failed]
      selector: app=production
    - recipients: [telegram:123456789]
      triggers: [on-health-degraded]
      selector: env=production
```

### Управление параметрами контроллера (argocd-cmd-params-cm)

| Ключ ConfigMap | Env var | Описание |
| :--- | :--- | :--- |
| `notificationscontroller.log.level` | `ARGOCD_NOTIFICATIONS_CONTROLLER_LOGLEVEL` | `debug\|info\|warn\|error` (default: `info`) |
| `notificationscontroller.log.format` | `ARGOCD_NOTIFICATIONS_CONTROLLER_LOGFORMAT` | `json\|text` (default: `json`) |
| `notificationscontroller.processors.count` | `ARGOCD_NOTIFICATION_CONTROLLER_PROCESSORS_COUNT` | Количество воркеров (default: 1) |
| `application.namespaces` | `ARGOCD_APPLICATION_NAMESPACES` | Namespace-ы для self-service |
| `notificationscontroller.selfservice.enabled` | `ARGOCD_NOTIFICATION_CONTROLLER_SELF_SERVICE_NOTIFICATION_ENABLED` | Включить self-service |

## Установка и настройка сервисов

### Slack

```yaml
data:
  service.slack: |
    token: $slack-token
    signingSecret: $slack-signing-secret
```

```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=slack-token=xoxb-1234567890-... \
  --from-literal=slack-signing-secret=abc123... \
  -n argocd
```

### Telegram

```yaml
data:
  service.telegram: |
    token: $telegram-token
```

```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=telegram-token=123456:ABC-DEF \
  -n argocd
```

### Email (SMTP)

```yaml
data:
  service.email: |
    host: smtp.gmail.com
    port: 587
    from: argocd@example.com
    username: $email-username
    password: $email-password
    insecure: false
```

```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=email-username=user@gmail.com \
  --from-literal=email-password=app-password \
  -n argocd
```

### MS Teams (Webex) — DEPRECATED

> **Выведен из эксплуатации (March 2026).** Используйте Teams Workflows.

### Teams Workflows (рекомендуется)

```yaml
data:
  service.teams-workflows: |
    webhookURL: $teams-webhook-url
```

### PagerDuty (v2 рекомендуется)

```yaml
data:
  service.pagerdutyv2: |
    serviceKeys:
      my-service: $pagerdutyv2-key
```

```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=pagerdutyv2-key=<pd-integration-key> \
  -n argocd
```

### GitHub Status

```yaml
data:
  service.github: |
    appID: 123
    installationID: 456
    privateKey: $github-private-key
```

### Webhook (произвольный)

```yaml
data:
  service.webhook: |
    url: https://alertmanager.example.com/api/v1/alerts
    headers:
    - name: Content-Type
      value: application/json
```

### Alertmanager

```yaml
data:
  service.alertmanager: |
    url: https://alertmanager.example.com
```

### Grafana

```yaml
data:
  service.grafana: |
    url: https://grafana.example.com
    apiToken: $grafana-token
```

## Операции и команды (CLI)

Все команды CLI — через `argocd admin notifications` (требует подключения к кластеру, где установлен argocd-admin):

| Команда | Описание |
| :--- | :--- |
| `argocd admin notifications trigger get` | Список всех триггеров |
| `argocd admin notifications trigger get <name>` | Детали конкретного триггера |
| `argocd admin notifications trigger run <name> <app>` | Вычислить триггер для приложения (проверка условия `when`) |
| `argocd admin notifications template get` | Список всех шаблонов |
| `argocd admin notifications template get <name>` | Детали шаблона |
| `argocd admin notifications template notify <name> <app> --recipient <service:destination>` | Отправить тестовое уведомление |

**Примеры:**

```bash
# Проверить, сработает ли триггер для приложения
argocd admin notifications trigger run on-sync-failed my-app

# Список всех триггеров
argocd admin notifications trigger get

# Список всех шаблонов
argocd admin notifications template get

# Отправить тестовое уведомление в Slack
argocd admin notifications template notify app-sync-failed my-app \
  --recipient slack:my-channel
```

## Практические сценарии

### Сценарий 1: Базовая настройка Telegram

```bash
# 1. Создать Secret
kubectl create secret generic argocd-notifications-secret \
  --from-literal=telegram-token=123456:ABC-DEF -n argocd

# 2. Настроить сервис в ConfigMap
kubectl patch cm argocd-notifications-cm -n argocd --type merge -p \
  '{"data": {"service.telegram": "token: $telegram-token"}}'

# 3. Подписаться через аннотацию Application
kubectl annotate app my-app \
  notifications.argoproj.io/subscribe.on-sync-failed.telegram=123456789
```

### Сценарий 2: GitHub Commit Status

Обновление статуса коммита в Git (галочка/крестик в PR):

```yaml
data:
  service.github: |
    appID: 123
    installationID: 456
    privateKey: $github-private-key
```

### Сценарий 3: Мультиканальные уведомления

Одна подписка — несколько получателей:

```yaml
data:
  subscriptions: |
    - recipients: [slack:#alerts, telegram:123456789, email:team@example.com]
      triggers: [on-sync-failed, on-health-degraded]
      selector: app=production
```

### Сценарий 4: Маршрутизация по окружениям

Разные каналы для dev/staging/prod:

```yaml
data:
  subscriptions: |
    - recipients: [slack:#prod-alerts]
      triggers: [on-sync-failed, on-health-degraded]
      selector: env=production
    - recipients: [slack:#dev-alerts]
      triggers: [on-sync-failed]
      selector: env=development
    - recipients: [email:team@example.com]
      triggers: [on-deployed]
      selector: env=production
```

### Сценарий 5: PagerDuty для критических ошибок (v2)

```yaml
data:
  defaultTriggers.pagerdutyv2: |
    - on-sync-failed
    - on-health-degraded
  trigger.on-critical-error: |
    - when: |
        app.status.health.status == 'Degraded'
        and app.metadata.labels['criticality'] == 'high'
      send: [critical-template]
      oncePer: app.status?.operationState.syncResult.revision
  template.critical-template: |
    pagerdutyv2:
      serviceKeys:
        my-service: $pagerdutyv2-key
      severity: error
      details:
        app: {{.app.metadata.name}}
        health: {{.app.status.health.status}}
        environment: {{.app.metadata.labels['env']}}
```

### Сценарий 6: Webhook в Alertmanager

```yaml
data:
  service.webhook: |
    url: https://alertmanager.example.com/api/v1/alerts
    headers:
    - name: Content-Type
      value: application/json
  template.json-template: |
    webhook:
      body: |
        {
          "app": "{{.app.metadata.name}}",
          "status": "{{.app.status.health.status}}",
          "sync": "{{.app.status.sync.status}}",
          "revision": "{{.app.status.sync.revision}}"
        }
```

### Сценарий 7: Самообслуживание (Self-service notifications)

Позволяет командам управлять уведомлениями в своём namespace. В `argocd-cmd-params-cm`:

```yaml
data:
  application.namespaces: app-team-one, app-team-two
  notificationscontroller.selfservice.enabled: "true"
```

Команда создаёт локальный ConfigMap в своём namespace:

```yaml
# в namespace app-team-one
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
data:
  service.slack: |
    token: $slack-token
  template.local-template: |
    slack:
      text: "Local notification for {{.app.metadata.name}}"
```

> **Ограничение:** при включённом self-service `.secrets` недоступен в шаблонах.

### Сценарий 8: Настройка timezone

```yaml
# Deployment argocd-notifications-controller
spec:
  template:
    spec:
      containers:
      - name: argocd-notifications-controller
        env:
        - name: TZ
          value: Asia/Tokyo
```

### Сценарий 9: Масштабирование контроллера

Для высокой нагрузки:

```yaml
# argocd-cmd-params-cm
data:
  notificationscontroller.processors.count: "4"
```

Или через CLI:

```bash
kubectl patch deployment argocd-notifications-controller -n argocd --type merge -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"argocd-notifications-controller","args":["argocd-notifications","--processors-count=4"]}]}}}}'
```

### Сценарий 10: Dedup и oncePer для монорепозиториев

В монорепозитории один коммит может затрагивать несколько приложений. `oncePer` по умолчанию (`app.status.sync.revision`) отправит уведомление для каждого. Для единого уведомления используйте `operationState.syncResult.revision`:

```yaml
data:
  trigger.sync-operation-change: |
    - when: app.status?.operationState.phase in ['Succeeded']
      send: [github-commit-status]
      oncePer: app.status?.operationState.syncResult.revision
```

## Диагностика и отладка

### Проверка подписки приложения

```bash
kubectl get app <app-name> -n argocd -o jsonpath='{.metadata.annotations}' | jq .
```

Должна присутствовать аннотация `notifications.argoproj.io/subscribe.*`.

### Тестирование триггера

```bash
argocd admin notifications trigger run on-sync-failed my-app
```

Выводит `CONDITION`/`RESULT` для каждого условия триггера.

### Тестирование шаблона

```bash
# Отправить тестовое уведомление
argocd admin notifications template notify app-sync-failed my-app \
  --recipient console:stdout

# Просмотр шаблона
argocd admin notifications template get app-sync-failed -o yaml
```

### Проверка конфигурации

```bash
# ConfigMap
kubectl get configmap argocd-notifications-cm -n argocd -o yaml

# Secret (без значений)
kubectl get secret argocd-notifications-secret -n argocd -o jsonpath='{.data}' | jq 'keys'

# Подписчики из CLI
argocd admin notifications trigger get
```

### Логи контроллера

```bash
kubectl logs -n argocd deployment/argocd-notifications-controller --tail=100
```

### Метрики

Контроллер экспортирует метрики на порту `:9001`. Доступны:
- `argocd_notifications_events_total` — количество обработанных событий
- `argocd_notifications_notifications_sent_total` — отправленные уведомления
- `argocd_notifications_errors_total` — ошибки доставки

### События Kubernetes

```bash
kubectl get events -n argocd --field-selector involvedObject.name=<app-name> | grep -i notif
```

## Таблица типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `config referenced '<key>', but key does not exist in secret` | Secret не содержит ключ | Добавить ключ в `argocd-notifications-secret` |
| `trigger with name '<name>' does not exist` | Триггер не загружен из каталога | Применить `notifications_catalog/install.yaml` |
| `notifications.argoproj.io/subscribe.<trigger>.<service>` не работает | Неверный формат аннотации | Проверить: имя триггера, сервис, destination |
| `403 Forbidden` от Slack/Telegram | Невалидный токен или бот исключён | Перевыпустить токен, проверить права |
| `429 Too Many Requests` | Rate limit API | Группировать уведомления, увеличить `oncePer` |
| Сообщение не приходит | `oncePer` кэширует ID | Проверить аннотацию `NotificationProcessed` на Application |
| `argocdUrl` пуст в шаблоне | Контекст не настроен | Добавить `context.argocdUrl` в ConfigMap |
| Self-service шаблон не использует `.secrets` | Self-service выключает доступ к Secret | Перенести секреты в сервис-конфигурацию |

## Лучшие практики

### Безопасность

- **Secret вместо ConfigMap:** все токены, ключи и вебхуки хранить в `argocd-notifications-secret`, ссылаться через `$<key>`.
- **Sign Secret для Slack:** включать `signingSecret` для проверки подписи webhook.
- **Least Privilege для GitHub App:** минимальные scope — только `repo:status` и `read:org`.
- **Webhook HMAC:** для собственных вебхуков использовать `headers` с HMAC-сигнатурой.
- **Service-specific tokens:** отдельные токены для prod и dev окружений (named сервисы).

### Производительность

- **`oncePer`:** обязательно указывать для предотвращения спама при "flapping" состояний.
- **`processors.count`:** для 100+ приложений увеличить до 2–4.
- **`defaultTriggers`:** использовать вместо перечисления триггеров в каждой подписке.
- **Селекторы:** использовать `selector` в глобальных подписках вместо массовых аннотаций.

### Надёжность

- **Fallback channels:** для критических триггеров дублировать в несколько сервисов.
- **Отслеживание метрик:** алерт на рост `argocd_notifications_errors_total`.
- **CrashLoopBackOff:** алерт на restart пода контроллера.
- **Тестирование:** `template notify` перед деплоем в прод.
- **Timezone:** явно устанавливать `TZ` для предсказуемых timestamp в шаблонах.

### Устранение и очистка

- **Удаление подписки:** `kubectl annotate app <name> --null notifications.argoproj.io/subscribe.on-sync-failed.slack`.
- **Очистка аннотаций dedup:** `kubectl patch app <name> --type=json -p='[{"op":"remove","path":"/metadata/annotations/NotificationProcessed"}]'`.
- **Ротация токенов:** периодически обновлять через `kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -`.

## Ограничения и edge cases

### Ограничения

1. **Scope уведомлений:** ограничены событиями жизненного цикла Argo CD (sync, health, operation). Нет событий о конкретных подах/ресурсах внутри приложения.
2. **Один recipient на тип:** нельзя отправить один и тот же триггер в два канала одного сервиса без named-сервиса.
3. **Self-service ограничения:** при включённом self-service `.secrets` недоступен, сервисы должны быть в namespace приложения.
4. **Teams legacy:** Office 365 Connectors (service.teams) выведен из эксплуатации (March 2026).
5. **Mono-repo:** `oncePer: app.status.sync.revision` отправит уведомление на каждое приложение при одном коммите. Использовать `operationState.syncResult.revision`.

### Edge cases

1. **Параллельные операции:** при одновременных sync/rollback аннотации могут конфликтовать — использовать `fieldManager` через Server-Side Apply.
2. **Нулевой operationState:** до начала синхронизации `app.status.operationState` равен `nil` — обязательно использовать `?.`.
3. **Удаление Application:** при удалении генерируется событие `deletionTimestamp` — триггер `on-deleted`.
4. **Меж-namespace:** по умолчанию контроллер видит только namespace, где установлен. Для self-service нужен `--application-namespaces` и `--self-service-notification-enabled`.
5. **Image Updater:** изменения, вызванные Argo CD Image Updater, не генерируют operation events (только sync).

## Дополнительная информация

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — policy.csv, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — sourceRepos, destinations, syncWindows, роли.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext.
- [Установка и настройка](./argocd_installation_and_setup.md) — компоненты Argo CD, HA, профили.
- [Обзор архитектуры](./argocd_overview.md) — компоненты и Цикл сверки.
- [GitOps: Уведомления и алертинг](../gitops_notifications.md) — сравнение Argo CD и Flux notification подходов.
- [Синхронизация: Auto Sync](./synchronization/scenarios/auto_sync.md) — примеры конфигурации notifications.

### Официальная документация

- [Notifications Overview](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- [Triggers](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/triggers)
- [Templates](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/templates)
- [Catalog](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/catalog)
- [Services](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/services/overview)
- [Dynamic Cluster Distribution](https://argo-cd.readthedocs.io/en/stable/operator-manual/dynamic-cluster-distribution) (для масштабирования контроллера)
