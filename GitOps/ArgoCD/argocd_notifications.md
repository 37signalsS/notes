# ArgoCD Notifications: Настройка уведомлений

## Определения

**ArgoCD Notifications** — встроенный компонент ArgoCD (начиная с v3.x), предназначенный для мониторинга событий жизненного цикла приложений и отправки уведомлений во внешние системы (Slack, Telegram, Email и др.).

**Триггер (Trigger)** — логическое условие, при выполнении которого инициируется отправка уведомления (например, `on-sync-failed`).

**Шаблон (Template)** — структура и содержание сообщения, формируемого на основе данных о событии с использованием Go-шаблонов.

**Сервис (Service)** — конфигурация подключения к внешней платформе доставки (API токены, URL вебхуков).

**Подписка (Subscription)** — связка приложения с триггером и конкретным получателем.

## Основные концепции

### Архитектура и компоненты

В версиях **ArgoCD v3.x** функционал уведомлений полностью интегрирован в основной контроллер, что упрощает администрирование. Конфигурация хранится в двух ресурсах:

1. **`argocd-notifications-cm` (ConfigMap):** Логика уведомлений (триггеры, шаблоны, описание сервисов).
2. **`argocd-notifications-secret` (Secret):** Чувствительные данные (токены Telegram, Slack Webhooks).

### Принцип работы

1. Контроллер отслеживает изменения статуса `Application`.
2. При наступлении события проверяются аннотации приложения на наличие активных подписок.
3. Если подписка найдена и условие триггера выполнено, контроллер рендерит сообщение по шаблону.
4. Сообщение отправляется через настроенный сервис.
5. Аннотация `notifications.argoproj.io/last-notification-id` предотвращает повторную отправку одного и того же события.

## Практические сценарии

### Сценарий 1: Настройка уведомлений в Telegram

#### 1. Подготовка в Telegram
- Создать бота через `@BotFather` и получить `token`.
- Добавить бота в группу и получить `Chat ID` (например, через бота `@getmyid_bot`).

#### 2. Настройка секретов и конфигурации
```yaml
# Secret
stringData:
  telegram-token: "1234567890:ABC-DEF"

# ConfigMap
data:
  service.telegram: |
    my-bot:
      token: $telegram-token
  
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Failed', 'Error']
      send: [app-sync-failed]

  template.app-sync-failed: |
    message: |
      [ERROR] Application `{{.app.metadata.name}}` sync failed!
      View details: {{.context.argocd.url}}/applications/{{.app.metadata.name}}
```

#### 3. Подписка приложения
Добавьте аннотацию в манифест `Application`:
```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.my-bot: "-1001234567890"
```

### Сценарий 2: Интеграция с Commit Status API (GitHub/GitLab)

ArgoCD может отправлять статус синхронизации напрямую в UI Git-платформы, помечая коммиты как проверенные (Check Succeeded/Failed).

```yaml
data:
  service.github: |
    github-app:
      appID: 12345
      installationID: 67890
      privateKey: $github-private-key
```

## Дополнительная информация

### Поддерживаемые системы

- **Мессенджеры:** Slack, Telegram, Discord, Microsoft Teams, Mattermost.
- **Email:** SMTP интеграция.
- **Git-платформы:** GitHub, GitLab, Bitbucket (Commit Status).
- **Webhooks:** Универсальные HTTP-запросы для интеграции с любыми API.

### Полезные команды для диагностики

```bash
# Проверка логов контроллера уведомлений (в v3.x это часть application-controller)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep notifications
```

### См. также

- [ArgoCD Overview](./argocd_overview.md)
- [Синхронизация и её политики](./synchronization.md)
- [GitOps: Уведомления](../gitops_notifications.md)
