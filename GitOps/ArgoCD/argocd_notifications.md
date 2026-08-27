# ArgoCD Notifications — настройка уведомлений

**ArgoCD Notifications** — встроенный компонент ArgoCD (начиная с v3.x), предназначенный для мониторинга событий жизненного цикла приложений и отправки уведомлений во внешние системы (Slack, Telegram, Email, MS Teams, PagerDuty и др.).

> **Актуальность (2026):** ArgoCD Notifications remains the recommended notification solution for ArgoCD. Начиная с v3.x, функционал уведомлений полностью интегрирован в `argocd-application-controller`, что исключает необходимость запуска отдельного контроллера. Проект активно поддерживается, выпускаются регулярные релизы с исправлениями безопасности.

## Предварительные требования

1. **Kubernetes кластер:** v1.22+.
2. **Argo CD установлен:** Версия 3.x (v2.x требует отдельного deployment `argocd-notifications-controller`). Проверка: `kubectl get pods -n argocd`.
3. **Доступ к API мессенджера:** Учетные данные для аутентификации в целевом сервисе (токен Slack, Telegram Bot Token, SMTP credentials).
4. **Хранилище Secret:** Достаточный объем памяти для хранения `argocd-notifications-secret`.

## Определения

- **ArgoCD Notifications**: Встроенный компонент ArgoCD, мониторящий события жизненного цикла приложений и отправляющий уведомления во внешние системы.
- **Триггер (Trigger)**: Логическое условие на базе языка выражений (Expression Language), при выполнении которого инициируется отправка уведомления.
- **Шаблон (Template)**: Структура и содержание сообщения, формируемого с использованием Go-шаблонов на основе данных о событии.
- **Сервис (Service)**: Конфигурация подключения к внешней платформе доставки (API токены, URL вебхуков).
- **Подписка (Subscription)**: Связка триггера, приложения и конкретного получателя (канала, почтового адреса).
- **Получатель (Recipient)**: Адресат уведомления в формате `<service>:<destination>` (например, `slack:my-channel`, `telegram:123456789`).
- **Дедупликация**: Механизм предотвращения дублирования уведомлений путем кеширования ID сообщений в аннотациях приложения.

## Архитектура

### Диаграмма взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│          ArgoCD Notifications: Архитектура уведомлений              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │  Kubernetes  │    │ argocd-      │    │  External    │          │
│  │  Cluster     │◀───│ application  │───▶│  Services    │          │
│  │  (App Events)│    │ controller   │    │  (Slack,     │          │
│  └──────────────┘    │ (v3.x+)     │    │   Telegram,  │          │
│         │            └──────────────┘    │   Email)     │          │
│         │                   │            └──────────────┘          │
│         ▼                   ▼                   │                   │
│  ┌──────────────┐    ┌──────────────┐           │                   │
│  │ argocd-notif │    │ argocd-notif │           │                   │
│  │ -cm          │    │ -secret      │           │                   │
│  │ (ConfigMap)  │    │ (Secret)     │           │                   │
│  └──────────────┘    └──────────────┘           │                   │
│         │                   │                   │                   │
│         ▼                   ▼                   ▼                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │ Triggers     │    │ Templates    │    │ Services     │          │
│  │ (Conditions) │    │ (Messages)   │    │ (Delivery)   │          │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Жизненный цикл уведомления

1. **Событие:** Изменение статуса приложения (например, `OutOfSync` или `Degraded`).
2. **Оценка:** Контроллер проверяет все активные подписки для данного приложения.
3. **Фильтрация:** Если условие триггера истинно, контроллер приступает к генерации.
4. **Рендеринг:** Подстановка данных приложения в выбранный шаблон.
5. **Дедупликация:** Проверка, не было ли это уведомление уже отправлено (по ID в аннотациях).
6. **Доставка:** Отправка через API выбранного сервиса.
7. **Кеширование:** Фиксация ID уведомления в аннотациях приложения для предотвращения дублей.

### Конфигурационные ресурсы

| Ресурс | Назначение | Содержимое |
| :--- | :--- | :--- |
| `argocd-notifications-cm` | Основная конфигурация | Триггеры, шаблоны, сервисы, подписки |
| `argocd-notifications-secret` | Чувствительные данные | Токены, пароли, URL вебхуков |

## Методы подписки

### 1. Локальные подписки (Application level)

Настраиваются через аннотации непосредственно в манифесте `Application`. Удобно для индивидуальных настроек команд.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  annotations:
    # Подписка на конкретный канал
    notifications.argoproj.io/subscribe.on-sync-failed.slack: "my-channel"
    notifications.argoproj.io/subscribe.on-health-degraded.telegram: "123456789"
```

### 2. Глобальные подписки (System level)

Настраиваются в `argocd-notifications-cm` и применяются ко всем приложениям, подходящим под селектор.

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

## Синтаксис получателей (Recipients)

| Формат | Описание | Пример |
| :--- | :--- | :--- |
| `slack:<channel>` | Slack канал | `slack:#alerts`, `slack:deploys` |
| `telegram:<chat-id>` | Telegram чат | `telegram:123456789` |
| `email:<address>` | Email адрес | `email:team@example.com` |
| `teams:<webhook-url>` | MS Teams webhook | `teams:https://outlook.office.com/webhook/...` |
| `webhook:<url>` | Произвольный webhook | `webhook:https://alertmanager.example.com` |
| `pagerduty:<service-key>` | PagerDuty сервис | `pagerduty:ABCDEFGHIJKLMNOPQRSTUVWXYZ` |
| `opsgenie:<api-key>` | Opsgenie алерт | `opsgenie:https://api.opsgenie.com/...` |

## Переменные шаблонов

Внутри шаблона доступны три основных объекта:

- **`.app`**: Полный объект `Application` (metadata, spec, status).
- **`.context`**: Глобальные переменные (например, `argocdUrl`, `env`).
- **`.service`**: Параметры конкретного сервиса доставки.

### Доступные переменные .app

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `.app.metadata.name` | Имя приложения | `my-app` |
| `.app.metadata.namespace` | Namespace | `argocd` |
| `.app.metadata.labels` | Метки приложения | `app=production` |
| `.app.spec.source.repoURL` | URL Git-репозитория | `https://github.com/org/repo` |
| `.app.spec.source.path` | Путь в репозитории | `k8s/overlays/prod` |
| `.app.status.sync.status` | Статус синхронизации | `Synced`, `OutOfSync` |
| `.app.status.health.status` | Статус здоровья | `Healthy`, `Degraded` |
| `.app.status.operationState.phase` | Фаза операции | `Succeeded`, `Failed` |
| `.app.status.operationState.message` | Сообщение об ошибке | `ComparisonError` |
| `.app.status.sync.revision` | Текущий коммит | `abc1234` |

### Пример сложного шаблона с логикой

```yaml
template.app-sync-status: |
  message: |
    Приложение {{.app.metadata.name}} в статусе {{.app.status.sync.status}}.
    {{ if eq .app.status.health.status "Degraded" }}
    Внимание: Обнаружены проблемы со здоровьем ресурсов!
    {{ end }}
    Коммит: {{.app.status.sync.revision}}
    Репозиторий: {{.app.spec.source.repoURL}}
```

### Шаблон с ссылками на UI

```yaml
template.app-with-links: |
  message: |
    *{{.app.metadata.name}}* — {{.app.status.sync.status}} | {{.app.status.health.status}}
    Коммит: `{{.app.status.sync.revision | first 7}}`
    UI: {{.context.argocdUrl}}/applications/{{.app.metadata.name}}
    {{if .app.status.operationState}}
    Операция: {{.app.status.operationState.phase}}
    {{end}}
```

## Настройка триггеров

### Встроенные триггеры

| Триггер | Условие (when) | Описание |
| :--- | :--- | :--- |
| **on-deployed** | `app.status.operationState.phase in ['Succeeded']` | Успешный деплой |
| **on-health-degraded** | `app.status.health.status == 'Degraded'` | Проблемы со здоровьем |
| **on-sync-running** | `app.status.operationState.phase in ['Running']` | Синхронизация в процессе |
| **on-sync-succeeded** | `app.status.operationState.phase in ['Succeeded']` | Успешная синхронизация |
| **on-sync-failed** | `app.status.operationState.phase in ['Failed', 'Error']` | Ошибка синхронизации |
| **on-sync-status-unknown** | `app.status.sync.status == 'Unknown'` | Неизвестный статус |
| **on-created** | `app.status.operationState.phase in ['Succeeded']` | Создание приложения |

### Кастомные триггеры

```yaml
data:
  trigger.on-high-risk-change: |
    - when: app.status.sync.status == 'OutOfSync' and app.metadata.labels['criticality'] == 'high'
      send: [risk-template]
  trigger.on-deploy-staging: |
    - when: app.status.operationState.phase in ['Succeeded'] and app.metadata.labels['env'] == 'staging'
      send: [staging-success]
```

### Использование функций для фильтрации

```yaml
trigger.on-deploy-with-image: |
  - when: |
      app.status.operationState.phase in ['Succeeded'] and
      has(app.status.operationState.operation.sync.revision) and
      app.status.operationState.operation.sync.revision != ""
    send: [image-update]
```

## Настройка сервисов

### Slack

```yaml
data:
  service.slack: |
    token: $slack-token
    signingSecret: $slack-signing-secret
```

**Создание секрета:**
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

**Создание секрета:**
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

**Создание секрета:**
```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=email-username=user@gmail.com \
  --from-literal=email-password=app-password \
  -n argocd
```

### MS Teams

```yaml
data:
  service.teams: |
    recipientURL: $teams-webhook-url
    headers: []
```

**Создание секрета:**
```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=teams-webhook-url=https://outlook.office.com/webhook/... \
  -n argocd
```

### PagerDuty

```yaml
data:
  service.pagerduty: |
    token: $pagerduty-token
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

### GitHub Status

```yaml
data:
  service.github: |
    appID: 123
    installationID: 456
    privateKey: $github-private-key
```

## Практические сценарии

### Сценарий 1: Уведомления в Telegram

**1. Настройка секрета:**
```bash
kubectl create secret generic argocd-notifications-secret \
  --from-literal=telegram-token=123456:ABC-DEF -n argocd
```

**2. Конфигурация в ConfigMap:**
```yaml
data:
  service.telegram: |
    my-bot:
      token: $telegram-token
  template.sync-failed: |
    message: "Ошибка деплоя {{.app.metadata.name}}!"
  trigger.on-sync-failed: |
    - when: app.status.operationState.phase in ['Failed', 'Error']
      send: [sync-failed]
```

**3. Подписка приложения:**
```yaml
annotations:
  notifications.argoproj.io/subscribe.on-sync-failed.telegram: "123456789"
```

### Сценарий 2: Обновление статуса в GitHub/GitLab

ArgoCD может помечать конкретный коммит галочкой или крестиком в интерфейсе Git-платформы.

```yaml
data:
  service.github: |
    appID: 123
    installationID: 456
    privateKey: $github-private-key
```

### Сценарий 3: Мультиканальные уведомления

Отправка в несколько каналов одновременно:

```yaml
data:
  subscriptions: |
    - recipients: [slack:#alerts, telegram:123456789, email:team@example.com]
      triggers: [on-sync-failed, on-health-degraded]
      selector: app=production
```

### Сценарий 4: Маршрутизация по окружениям

Разные каналы для разных сред:

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

### Сценарий 5: PagerDuty для критических ошибок

```yaml
data:
  service.pagerduty: |
    token: $pagerduty-token
  trigger.on-critical-error: |
    - when: |
        app.status.health.status == 'Degraded' and
        app.metadata.labels['criticality'] == 'high'
      send: [critical-template]
  template.critical-template: |
    message: |
      CRITICAL: {{.app.metadata.name}} is {{.app.status.health.status}}
      Environment: {{.app.metadata.labels['env']}}
      Time: {{.app.status.operationState.finishedAt}}
```

### Сценарий 6: Webhook для кастомных систем

```yaml
data:
  service.webhook: |
    url: https://alertmanager.example.com/api/v1/alerts
    headers:
    - name: Content-Type
      value: application/json
  template.json-template: |
    message: |
      {
        "app": "{{.app.metadata.name}}",
        "status": "{{.app.status.health.status}}",
        "sync": "{{.app.status.sync.status}}",
        "revision": "{{.app.status.sync.revision}}"
      }
```

## Сравнение с Flux notification-controller

| Характеристика | ArgoCD Notifications | Flux notification-controller |
| :--- | :--- | :--- |
| **Интеграция** | Встроен в `argocd-application-controller` (v3.x) | Отдельный контроллер в GitOps Toolkit |
| **Конфигурация** | ConfigMap + Secret + аннотации | CRD (`Provider`, `Alert`) |
| **Триггеры** | Expression Language (сложные условия) | Event Severity + Event Sources |
| **Шаблоны** | Go-шаблоны с переменными .app | Go-шаблоны с переменными |
| **Получатели** | Формат `service:destination` | CRD `Provider` + `Alert` |
| **Deduplication** | Да (аннотации приложения) | Да (встроенный механизм) |
| **Multi-tenancy** | Ограниченно (по labels) | Полная поддержка (namespaces) |
| **Webhook** | Да (встроенный) | Да (через Receiver CRD) |
| **CDEvents** | Нет | Да (в Flux v1.8+) |
| **PR Comments** | Нет | Да (GitHub/GitLab, Flux v1.8+) |

## Диагностика и отладка

### Тестирование шаблона

Позволяет увидеть отрендеренное сообщение в терминале:

```bash
argocd admin notifications template test <template-name> <app-name>
```

### Проверка триггера

Проверяет, сработает ли логика для конкретного приложения:

```bash
argocd admin notifications trigger run <trigger-name> <app-name>
```

### Логирование

Если уведомления не приходят, проверьте логи основного контроллера:

```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller | grep "notifications"
```

### Просмотр конфигурации

```bash
# Просмотр ConfigMap
kubectl get configmap argocd-notifications-cm -n argocd -o yaml

# Просмотр Secret
kubectl get secret argocd-notifications-secret -n argocd -o jsonpath='{.data}' | jq .
```

### Проверка подписок приложения

```bash
kubectl get app <app-name> -n argocd -o jsonpath='{.metadata.annotations}' | jq .
```

### Просмотр событий уведомлений

```bash
kubectl get events -n argocd --field-selector reason=Notifications | tail -20
```

## Рекомендации и лучшие практики

### Безопасность

- **Secrets:** Никогда не храните токены в ConfigMap. Используйте `argocd-notifications-secret`.
- **Least Privilege:** Создавайте отдельные Service Account для интеграций.
- **Token Rotation:** Регулярно обновляйте токены ботов и API ключи.
- **Webhook Security:** Настройте webhook secret для проверки подлинности запросов.

### Производительность

- **Интервал опроса:** Настройте `notifications.trigger.repeatDuration` для контроля частоты отправки.
- **Дедупликация:** Включите для предотвращения спама при частых ошибках.
- **Batch Processing:** Группируйте уведомления для снижения нагрузки на API мессенджеров.

### Надежность

- **Retry Logic:** Настройте повторные попытки при временных ошибках доставки.
- **Fallback Channels:** Настройте альтернативные каналы при недоступности основного.
- **Health Checks:** Мониторьте статус контроллера уведомлений.

### Устранение проблем

- **Логирование:** Включите `notifications.logLevel: debug` для отладки.
- **Тестирование:** Используйте `argocd admin notifications template test` перед деплоем.
- **Мониторинг:** Добавьте алерты на CrashLoopBackOff пода контроллера.

## Ограничения и edge cases

### Ограничения

1. **Только события ArgoCD:** Уведомления ограничены событиями жизненного цикла приложений ArgoCD.
2. **Одна нотификация на событие:** Невозможно отправить одно событие в несколько сервисов одного типа (например, два разных Slack-канала).
3. **Нет встроенной интеграции с PagerDuty/Opsgenie:** Требуется webhook или промежуточный сервис.
4. **Ограничения API мессенджеров:** Квоты и лимиты внешних API (Slack: 1 сообщение/секунда).

### Edge Cases

1. **Параллельные деплои:** При одновременных операциях возможны конфликты аннотаций.
2. **Долгие деплои:** При длительных операциях уведомление может прийти до завершения.
3. **Откат приложения:** При откате генерируется новое событие (если триггер настроен).
4. **Удаление приложения:** При удалении генерируется событие `on-sync-failed` (если триггер настроен).
5. **Namespace isolation:** Уведомления не работают между namespace без дополнительной настройки.
6. **Мульти-кластер:** Требуется отдельная конфигурация для каждого кластера.
7. **Аннотации:** Image Updater не валидирует аннотации — ошибки в синтаксисе приводят к тихим сбоям.

## Дополнительная информация

### См. также

- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.

### Связанные документы

- [GitOps: Уведомления и алертинг](../gitops_notifications.md) — общая архитектура уведомлений в GitOps.
- [Обзор архитектуры ArgoCD](./argocd_overview.md) — компоненты ArgoCD.
- [Политики синхронизации](./synchronization.md) — Auto Sync и связанные интеграции.
- [Auto Sync: Конфигурация нотификаций](./synchronization/scenarios/auto_sync.md) — примеры конфигурации.

### Официальная документация

- [ArgoCD Notifications Guide](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- [ArgoCD Notifications — GitHub](https://github.com/argoproj-labs/argocd-notifications)
