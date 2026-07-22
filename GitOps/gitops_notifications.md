# GitOps — уведомления о статусе развертываний

Уведомления являются неотъемлемой частью **GitOps (инфраструктура как код в Git)** конвейера, позволяя командам получать оперативную информацию о состоянии приложений без необходимости ручной проверки интерфейса или консоли.

## Определения

- **Уведомление (Notification)**: Автоматическое сообщение о событии в **GitOps-конвейере (Continuous Delivery — непрерывная доставка)**, например, об успехе или ошибке синхронизации, отправляемое во внешнюю систему (Slack, Telegram, Microsoft Teams, Email).
- **Вебхук (Webhook)**: Основной механизм доставки уведомлений. Инструмент отправляет **HTTP POST (HyperText Transfer Protocol POST)** запрос с деталями события на заранее указанный **URL (Uniform Resource Locator)**.
- **CDEvents**: Общая спецификация для описания событий в процессах непрерывной поставки, основанная на **CloudEvents (стандарт описания событий)**.

## Базовые концепции

### Назначение уведомлений

- **Оперативное информирование**: Оповещение об успешных и неудачных развертываниях в командных чатах.
- **Проактивное реагирование**: Немедленное получение данных о проблемах со здоровьем приложений (`Degraded`) после синхронизации.
- **Аудит и трассируемость**: Создание хронологической ленты всех изменений в выделенном канале для последующего анализа.

### Ключевые события для мониторинга

- Успешное завершение синхронизации (`Sync Succeeded`).
- Ошибка процесса синхронизации (`Sync Failed`).
- Изменение статуса здоровья приложения (например, переход из `Progressing` в `Healthy` или `Degraded`).
- Автоматическое обновление образа с помощью специализированных контроллеров (например, Image Updater).

### Возможности контроллера уведомлений Flux v1.8 (февраль 2026)

- **Комментарии к запросам на слияние (PR Comments)**: Прямое комментирование **Pull Request (Запрос на слияние)** в GitHub или GitLab.
- **Специализированные провайдеры**: Поддержка типов `githubpullrequestcomment`, `gitlabmergerequestcomment`, `giteapullrequestcomment`.
- **Расширенная аутентификация NATS (Messaging System)**: Поддержка **JWT (JSON Web Token)**, NKey и стандартной связки Username/Password.
- **Поддержка CDEvents**: Реализация спецификации в **Receiver API (Application Programming Interface)**.
- **mTLS**: Использование **mutual TLS (Двусторонний TLS)** для алертов и транспорта GitHub App.

### Стратегии и фильтрация

Для предотвращения "информационного шума" в GitOps-системах применяются следующие подходы:

- **Маршрутизация (Routing)**: Направление критических алертов (ошибки синхронизации в продуктивном окружении) в основные каналы, а информационных (успешный деплой в окружение разработки) — в архивные.
- **Дедупликация (Deduplication)**: Группировка повторяющихся уведомлений об одной и той же ошибке для предотвращения спама.
- **Фильтрация по важности (Severity Filtering)**: Отправка только событий с уровнем `error` или `warning` для определенных окружений.
- **Многопользовательская изоляция (Multi-tenancy)**: Разделение прав на получение уведомлений между разными командами на основе **RBAC (Role-Based Access Control — управление доступом на основе ролей)**.

## Практические сценарии

### Сценарий 1: Настройка уведомлений в Argo CD

Подробное руководство по конфигурации ArgoCD Notifications, включая примеры для Telegram, доступно в специализированном документе: **[ArgoCD Notifications: Настройка уведомлений](./ArgoCD/argocd_notifications.md)**.

Основные компоненты:
- Использование контроллера `argocd-notifications-controller`.
- Хранение конфигурации в ресурсах `ConfigMap` и `Secret`.
- Подписка приложений через аннотации в манифестах.

### Сценарий 2: Уведомления в Slack через Flux

Flux использует `notification-controller` и ресурсы типов `Provider` и `Alert`.

1. **Создание секрета с URL вебхука Slack:**

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: slack-webhook-secret
      namespace: flux-system
    stringData:
      address: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"
    ```

2. **Настройка ресурса Provider (куда отправлять):**

    ```yaml
    apiVersion: notification.toolkit.fluxcd.io/v1beta3
    kind: Provider
    metadata:
      name: slack-provider
      namespace: flux-system
    spec:
      type: slack
      channel: '#deployments'
      secretRef:
        name: slack-webhook-secret
    ```

3. **Настройка ресурса Alert (о чем уведомлять):**

    ```yaml
    apiVersion: notification.toolkit.fluxcd.io/v1beta3
    kind: Alert
    metadata:
      name: deployment-alerts
      namespace: flux-system
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

**Связанные документы:**
- [ArgoCD Notifications: детальное руководство](./ArgoCD/argocd_notifications.md)
- [Обзор Flux: архитектура и возможности](./flux.md)

**Официальные ресурсы:**
- [Документация ArgoCD Notifications](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- [Flux Notification Controller Documentation](https://fluxcd.io/flux/components/notification/)
