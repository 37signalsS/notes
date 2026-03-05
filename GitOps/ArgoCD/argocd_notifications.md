# ArgoCD Notifications: Настройка уведомлений

## Определения

**ArgoCD Notifications** — это дополнительный компонент для ArgoCD, который отслеживает события жизненного цикла приложений (например, успешная синхронизация, деградация) и отправляет уведомления в сторонние системы, такие как Slack, Telegram, Email и другие.

Это позволяет командам получать оперативную информацию о состоянии развертываний, не отслеживая постоянно веб-интерфейс ArgoCD.

## Базовые концепции

Вся конфигурация `argocd-notifications` хранится в двух основных ресурсах Kubernetes в неймспейсе `argocd`:

1. `argocd-notifications-cm` (`ConfigMap`): Основной файл конфигурации, описывающий логику работы.
2. `argocd-notifications-secret` (`Secret`): Хранит чувствительные данные, такие как токены API, пароли и URL вебхуков.

Конфигурация в `ConfigMap` состоит из четырех ключевых сущностей:

- **`triggers` (Триггеры):** Определяют, *когда* отправлять уведомление. Триггер срабатывает при выполнении определенного условия, например, когда приложение успешно синхронизировалось (`on-sync-succeeded`) или его здоровье ухудшилось (`on-health-degraded`).

- **`templates` (Шаблоны):** Определяют, *что* будет содержаться в уведомлении. Это шаблоны сообщений, написанные с использованием Go-шаблонизации. Они могут включать переменные из контекста приложения (имя, статус, коммит и т.д.) и иметь специфичные секции для разных сервисов (например, отдельный формат для Slack и Email).

- **`services` (Сервисы):** Определяют, *куда* отправлять уведомления. Здесь настраиваются подключения к внешним системам: Telegram, Slack, Email, GitHub и др.

- **`subscriptions` (Подписки):** Связывают триггеры с сервисами для конкретных `Application` или `AppProject`. Подписка указывает, на какой триггер реагировать и через какой сервис отправлять уведомление.

### Важное замечание о версиях

При установке `argocd-notifications` с помощью официальных манифестов важно убедиться, что версия манифеста соответствует версии документации. В прошлом были случаи, когда `Getting Started` гайд ссылался на устаревшую версию манифестов, что приводило к несовместимости конфигурации. Установка через [официальный Helm-чарт](https://github.com/argoproj/argo-helm/tree/main/charts/argocd-notifications) является более надежным способом, так как версионирование в Helm строже.

**Для ArgoCD v3.x:** Notifications встроен в основной дистрибутив, отдельная установка не требуется.

## Практические сценарии

### Настройка уведомлений в Telegram

#### Шаг 1: Подготовка в Telegram

1. **Создайте бота:** В Telegram найдите `@BotFather`, создайте нового бота и получите его **токен**.
2. **Создайте группу:** Создайте новую группу для получения уведомлений.
3. **Добавьте бота в группу.**
4. **Получите Chat ID:**
    - Отправьте любое сообщение в группу.
    - Выполните GET-запрос к API Telegram, подставив свой токен: `https://api.telegram.org/bot<YOUR-BOT-TOKEN>/getUpdates`.
    - В ответе JSON найдите объект вашего чата и его `id` (он будет отрицательным числом, например, `-1001234567890`).

#### Шаг 2: Настройка Secret

Создайте `Secret` с токеном вашего Telegram-бота. Контроллер будет искать секрет с именем `argocd-notifications-secret`.

```yaml
# argocd-notifications-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: argocd
stringData:
  # Ключ должен соответствовать тому, что используется в ConfigMap
  telegram-token: "1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
```

#### Шаг 3: Настройка ConfigMap

Отредактируйте `ConfigMap` `argocd-notifications-cm`, добавив сервис для Telegram.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  # Контекст для подстановки правильного URL в сообщениях
  context: |
    argocd.url: https://argocd.example.com

  # Описание сервиса для отправки уведомлений
  service.telegram: |
    # Имя `my-telegram-bot` - произвольное, используется в подписках
    my-telegram-bot:
      # Ссылка на токен из Secret. Переменная называется `telegram-token`.
      token: $telegram-token

  # Триггеры и шаблоны обычно идут "из коробки" при установке.
  # Пример триггера:
  trigger.on-sync-succeeded: |
    - when: app.status.operationState.phase in ['Succeeded']
      send: [app-sync-succeeded]
  # Пример шаблона:
  template.app-sync-succeeded: |
    message: |
      ✅ Application `{{.app.metadata.name}}` has been successfully synced.
      Sync status: {{.app.status.sync.status}}
      Health status: {{.app.status.health.status}}
      Revision: {{.app.status.sync.revision}}
      [View in ArgoCD]({{.context.argocd.url}}/applications/{{.app.metadata.name}})
```

#### Шаг 4: Подписка приложения на уведомления

Добавьте аннотацию к манифесту ArgoCD `Application`, чтобы подписать его на уведомления.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-test-app
  namespace: argocd
  annotations:
    # Структура: notifications.argoproj.io/subscribe.<trigger-name>.<service-name>: <recipient>
    # - trigger-name: on-sync-succeeded (из ConfigMap)
    # - service-name: my-telegram-bot (из ConfigMap)
    # - recipient: ID чата, полученный на шаге 1
    notifications.argoproj.io/subscribe.on-sync-succeeded.my-telegram-bot: "-1001234567890"
spec:
  # ... остальная часть манифеста
```

После применения этих изменений `argocd-notifications` будет отправлять сообщение в указанный Telegram-чат каждый раз, когда это приложение успешно синхронизируется.

### Как это работает?

Когда событие происходит, `argocd-notifications-controller`:

1. Находит приложение с аннотацией подписки, соответствующей событию.
2. Читает из `ConfigMap` нужный шаблон (`template`) и сервис (`service`).
3. Забирает токен из `Secret`.
4. Формирует сообщение и отправляет его через API Telegram.
5. Добавляет в аннотации приложения информацию о том, что уведомление было отправлено, чтобы избежать дублирования.

## Дополнительная информация

### Встроенные триггеры (v3.x)

| Триггер | Условие | Шаблон |
| :--- | :--- | :--- |
| `on-sync-succeeded` | `app.status.operationState.phase in ['Succeeded']` | `app-sync-succeeded` |
| `on-sync-failed` | `app.status.operationState.phase in ['Failed', 'Error']` | `app-sync-failed` |
| `on-health-degraded` | `app.status.health.status == 'Degraded'` | `app-health-degraded` |
| `on-sync-running` | `app.status.operationState.phase in ['Running']` | `app-sync-running` |
| `on-sync-status-unknown` | `app.status.sync.status == 'Unknown'` | `app-sync-status-unknown` |

### Поддерживаемые сервисы уведомлений

- **Telegram:** Боты через token
- **Slack:** Webhook URL или OAuth
- **Email:** SMTP-сервер
- **Microsoft Teams:** Webhook URL
- **GitHub:** Status API
- **GitLab:** Commit Status API
- **Webhook:** Произвольный HTTP POST

### Ссылки

- **[GitOps: Уведомления](../Notifications/gitops_notifications.md)** — обзор уведомлений в GitOps
- **[Официальная документация](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)**
