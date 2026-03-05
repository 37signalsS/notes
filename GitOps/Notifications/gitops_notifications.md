# GitOps: Уведомления о статусе развертываний

> **Актуальные версии (февраль 2026):** ArgoCD Notifications v3.3, Flux notification-controller v1.8.1.

Уведомления — это неотъемлемая часть GitOps-конвейера, позволяющая командам получать оперативную информацию о состоянии своих приложений без необходимости постоянно проверять UI или консоль.

## Определения

- **Уведомление (Notification)**: Автоматическое сообщение о событии в GitOps-конвейере (e.g., sync success/fail), отправляемое в стороннюю систему (Slack, Microsoft Teams, Email).
- **Webhook**: Основной механизм доставки уведомлений. GitOps-инструмент отправляет HTTP POST-запрос с деталями события на заранее указанный URL (например, входящий вебхук Slack).

## Базовые концепции

### Зачем нужны уведомления?

- **Оперативное информирование**: Сообщать о успешных и неудачных развертываниях в командный чат.
- **Проактивное реагирование**: Немедленно узнавать о проблемах со здоровьем (`Degraded`) приложений после синхронизации.
- **Аудит и трассируемость**: Создавать "ленту" всех деплойментов в отдельном канале.

### Ключевые события для уведомлений

- Успешное завершение синхронизации (`Sync Succeeded`).
- Ошибка синхронизации (`Sync Failed`).
- Изменение статуса здоровья приложения (например, с `Progressing` на `Healthy` или `Degraded`).
- Автоматическое обновление образа с помощью Image Updater.

### Новые функции notification-controller v1.8 (февраль 2026)

- **PR Comments**: Прямое комментирование Pull Request в GitHub/GitLab
- **Новые провайдеры**: `githubpullrequestcomment`, `gitlabmergerequestcomment`, `giteapullrequestcomment`
- **Расширенная аутентификация NATS**: JWT, NKey, Username/Password
- **CDEvents support**: Поддержка CDEvents в Receiver API
- **mTLS**: mTLS для алертов и GitHub App transport

## Практические сценарии

### Сценарий 1: Уведомления из Argo CD

**Основное руководство:** Подробное руководство по настройке ArgoCD Notifications, включая примеры для Telegram, доступно в основной заметке: **[ArgoCD Notifications: Настройка уведомлений](../ArgoCD/argocd_notifications.md)**.

Краткое описание:
- Argo CD использует компонент `argocd-notifications-controller`
- Конфигурация хранится в `ConfigMap` и `Secret`
- Приложения подписываются на уведомления через аннотации
- Встроенные триггеры: `on-sync-succeeded`, `on-sync-failed`, `on-health-degraded`

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

- **[ArgoCD Notifications](../ArgoCD/argocd_notifications.md)**: Полное руководство по настройке ArgoCD.
- **[Flux Overview](../Flux/overview.md)**: Архитектура Flux и notification-controller.
- **Официальная документация ArgoCD**: [Notifications](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- **Официальная документация Flux**: [Notification Controller](https://fluxcd.io/flux/components/notification/)
