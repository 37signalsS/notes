# ArgoCD Notifications: Настройка уведомлений

## Определения

**ArgoCD Notifications** — компонент ArgoCD для мониторинга событий жизненного цикла приложений и отправки уведомлений во внешние системы (Slack, Telegram, Email и др.).

**Триггер (Trigger)** — условие, при выполнении которого инициируется отправка уведомления (например, `on-sync-succeeded`).

**Шаблон (Template)** — структура и содержание сообщения, формируемого на основе данных о событии.

**Сервис (Service)** — конфигурация подключения к внешней системе доставки сообщений.

**Подписка (Subscription)** — связка конкретного приложения с триггером и сервисом доставки.

## Базовые концепции

Конфигурация уведомлений базируется на двух ресурсах в неймспейсе `argocd`:

1. **`argocd-notifications-cm` (ConfigMap):** Содержит логику (триггеры, шаблоны, описание сервисов).
2. **`argocd-notifications-secret` (Secret):** Хранит чувствительные данные (токены, пароли).

### Компоненты конфигурации

- **Triggers:** Определяют «когда» отправлять. Используют выражения для проверки состояния приложения.
- **Templates:** Определяют «что» отправлять. Используют Go-шаблонизацию для извлечения данных из контекста приложения (имя, статус, ревизия).
- **Services:** Определяют «куда» отправлять. Настраиваются для каждого типа интеграции (Telegram, Slack и т.д.).
- **Subscriptions:** Определяют получателей. Настраиваются через аннотации в манифесте `Application`.

### Принцип работы

1. Контроллер `argocd-notifications-controller` отслеживает изменения в `Application`.
2. При наступлении события проверяются аннотации приложения на наличие подписок.
3. Если подписка найдена и условие триггера выполнено, контроллер рендерит шаблон.
4. Сообщение отправляется через настроенный сервис.
5. В аннотации приложения ставится отметка об отправке для предотвращения дублирования.

**Примечание для ArgoCD v3.x:** Функционал уведомлений встроен в основной дистрибутив, отдельная установка компонентов не требуется.

## Практические сценарии

### Настройка уведомлений в Telegram

#### 1. Подготовка в Telegram

- Создать бота через `@BotFather` и получить `token`.
- Создать группу и добавить туда бота.
- Получить `Chat ID` группы (например, через `https://api.telegram.org/bot<TOKEN>/getUpdates`).

#### 2. Конфигурация Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
stringData:
  telegram-token: "1234567890:ABC-DEF"
```

#### 3. Конфигурация ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  context: |
    argocd.url: https://argocd.example.com

  service.telegram: |
    my-telegram-bot:
      token: $telegram-token

  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-sync-succeeded]

  template.app-sync-succeeded: |
    message: |
      [SUCCESS] Application `{{.app.metadata.name}}` has been successfully synced.
      Sync status: {{.app.status.sync.status}}
      Health status: {{.app.status.health.status}}
      Revision: {{.app.status.sync.revision}}
      View in ArgoCD: {{.context.argocd.url}}/applications/{{.app.metadata.name}}
```

#### 4. Подписка приложения

Добавьте аннотацию в манифест `Application`:

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-succeeded.my-telegram-bot: "-1001234567890"
```

## Дополнительная информация

### Встроенные триггеры

| Триггер | Условие | Шаблон по умолчанию |
| :--- | :--- | :--- |
| `on-sync-succeeded` | Статус `Succeeded` | `app-sync-succeeded` |
| `on-sync-failed` | Статус `Failed` или `Error` | `app-sync-failed` |
| `on-health-degraded` | Здоровье `Degraded` | `app-health-degraded` |
| `on-sync-running` | Процесс `Running` | `app-sync-running` |

### Поддерживаемые сервисы

- Telegram (Bots)
- Slack (Webhooks, OAuth)
- Email (SMTP)
- Microsoft Teams (Webhooks)
- GitHub/GitLab (Commit Status API)

### См. также

- [ArgoCD Overview](./argocd_overview.md)
- [Установка и настройка ArgoCD](./argocd_installation_and_setup.md)
- [Troubleshooting и мониторинг](./argocd_troubleshooting_and_monitoring.md)
- [GitOps: Уведомления](../gitops_notifications.md)
