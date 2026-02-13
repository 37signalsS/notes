# GitOps: Уведомления о статусе развертываний

Уведомления — это неотъемлемая часть GitOps-конвейера, позволяющая командам получать оперативную информацию о состоянии своих приложений без необходимости постоянно проверять UI или консоль.

## Определения

- **Уведомление (Notification)**: Автоматическое сообщение о событии в GitOps-конвейере (e.g., sync success/fail), отправляемое в стороннюю систему (Slack, Microsoft Teams, Email).
- **Webhook**: Основной механизм доставки уведомлений. GitOps-инструмент отправляет HTTP POST-запрос с деталями события на заранее указанный URL (например, входящий вебхук Slack).

## Основные концепции

### Зачем нужны уведомления?
- **Оперативное информирование**: Сообщать о успешных и неудачных развертываниях в командный чат.
- **Проактивное реагирование**: Немедленно узнавать о проблемах со здоровьем (`Degraded`) приложений после синхронизации.
- **Аудит и трассируемость**: Создавать "ленту" всех деплойментов в отдельном канале.

### Ключевые события для уведомлений
- Успешное завершение синхронизации (`Sync Succeeded`).
- Ошибка синхронизации (`Sync Failed`).
- Изменение статуса здоровья приложения (например, с `Progressing` на `Healthy` или `Degraded`).
- Автоматическое обновление образа с помощью Image Updater.

## Практические сценарии

### Сценарий 1: Уведомления в Slack из Argo CD

Argo CD использует `argocd-notifications-controller`. Настройка производится в `ConfigMap` и `Secret`.

1.  **Создайте Secret с URL вебхука Slack:**
    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: argocd-notifications-secret
    stringData:
      slack-url: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    ```

2.  **Настройте сервис и шаблон в ConfigMap:**
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: argocd-notifications-cm
    data:
      service.slack: |
        url: $slack-url
      template.app-sync-status: |
        message: |
          Application {{.app.metadata.name}} sync status is {{.app.status.sync.status}}.
          Health status is {{.app.satus.health.status}}.
          Revision: {{.app.status.sync.revision}}
      trigger.on-sync-status: |
        - when: app.status.operationState.phase in ['Succeeded', 'Failed']
          send: [app-sync-status]
    ```

3.  **Подпишите приложение на уведомления:**
    Добавьте аннотацию в манифест `Application`.
    ```yaml
    metadata:
      annotations:
        notifications.argoproj.io/subscribe.on-sync-status.slack: my-channel
    ```

### Сценарий 2: Уведомления в Slack из Flux

Flux использует `notification-controller` и CRD `Provider` и `Alert`.

1.  **Создайте Secret с URL вебхука Slack:**
    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: slack-webhook-secret
    stringData:
      address: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    ```

2.  **Настройте `Provider`, который указывает, куда отправлять:**
    ```yaml
    apiVersion: notification.toolkit.fluxcd.io/v1beta3
    kind: Provider
    metadata:
      name: slack-provider
    spec:
      type: slack
      channel: '#deployments'
      secretRef:
        name: slack-webhook-secret
    ```

3.  **Настройте `Alert`, который определяет, о чем уведомлять:**
    ```yaml
    apiVersion: notification.toolkit.fluxcd.io/v1beta3
    kind: Alert
    metadata:
      name: deployment-alerts
    spec:
      providerRef:
        name: slack-provider
      eventSources:
        - kind: Kustomization
          name: '*'
        - kind: HelmRelease
          name: '*'
      eventSeverity: error
      summary: "Deployment failed for ${{ .involvedObject.kind }} ${{ .involvedObject.name }}"
    ```

## Дополнительная информация
- **[Обзор ArgoCD](../ArgoCD/argocd_overview.md)**
- **[Обзор Flux](../Flux/overview.md)**
- **Официальная документация Argo CD**: [Notifications](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- **Официальная документация Flux**: [Notifications](https://fluxcd.io/flux/components/notification/)
