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

### Сценарий 1: Уведомления из Argo CD

Argo CD использует отдельный компонент `argocd-notifications-controller`. Процесс настройки включает три основных шага:

1.  **Настройка `ConfigMap` и `Secret`:** В `ConfigMap` (`argocd-notifications-cm`) определяются триггеры, шаблоны сообщений и сервисы (Slack, Telegram и т.д.). В `Secret` (`argocd-notifications-secret`) хранятся токены и URL вебхуков.
2.  **Подписка:** Приложения или проекты подписываются на уведомления с помощью аннотаций в своих манифестах.
3.  **Результат:** При срабатывании триггера (например, `on-sync-succeeded`) контроллер отправляет отформатированное сообщение в указанный сервис.

Подробное руководство по настройке, включая примеры для Telegram, доступно в основной заметке: **[ArgoCD Notifications: Настройка уведомлений](../ArgoCD/argocd_notifications.md)**.

### Сценарий 2: Уведомления в Slack из Flux

Flux использует `notification-controller` и CRD `Provider` и `Alert`.

1. **Создайте Secret с URL вебхука Slack:**

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: slack-webhook-secret
    stringData:
      address: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    ```

2. **Настройте `Provider`, который указывает, куда отправлять:**

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

3. **Настройте `Alert`, который определяет, о чем уведомлять:**

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
