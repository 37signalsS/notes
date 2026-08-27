# GitOps: Уведомления о статусе развертываний

Уведомления являются неотъемлемой частью GitOps-пайплайна (Infrastructure as Code). Они обеспечивают проактивный мониторинг состояния инфраструктуры и приложений, позволяя командам получать оперативную информацию о результатах синхронизации и изменениях состояния системы без необходимости ручного контроля консоли или интерфейса инструментов.

## Предварительные требования

Для воспроизведения практических сценариев из этого документа необходимы:

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| Kubernetes | Кластер версии 1.28+ с правами администратора (создание CRD, RBAC, Ingress) | `kubectl version --short` |
| Flux | Установленный Flux v2.7+ (актуальная ветка v2.9, в составе которой notification-controller v1.9.x) | `flux check` |
| ArgoCD | Версия 3.x для сценария 2 (в v2.x уведомления требуют отдельного deployment) | `argocd version` |
| Мессенджер | Slack workspace / Telegram bot / другой провайдер с правами на создание вебхуков или ботов | Тестовый POST-запрос к API |
| Инструменты | `flux` CLI, `kubectl`, `curl` для проверки входящих вебхуков | `flux --version` |

Исходное состояние окружения: контроллеры запущены и здоровы (`flux check` завершается строкой `✔ all checks passed`), namespace `flux-system` существует, исходные манифесты хранятся в Git-репозитории, синхронизируемом через `Kustomization` (рекомендуется хранить конфигурацию уведомлений там же — тогда она проходит через code review и версионирована).

## Определения

- **Уведомление (Notification)**: Автоматическое сообщение о событии в жизненном цикле ресурсов (Sync Succeeded, Failed, Degraded), отправляемое во внешние системы (Slack, Telegram, MS Teams, Email).
- **Вебхук (Webhook)**: Метод взаимодействия систем через HTTP POST-запросы. GitOps-контроллер отправляет JSON-пакет с деталями события на URL-адрес приемника (receiver).
- **Исходящий вебхук (Outbound)**: Уведомление о событии, отправляемое контроллером во внешнюю систему (направление «кластер -> мессенджер»). Во Flux реализуется связкой `Provider` + `Alert`.
- **Входящий вебхук (Inbound)**: Прием внешних HTTP-событий для триггера реконсиляции (направление «CI/форк -> кластер»). Во Flux реализуется ресурсом `Receiver`.
- **CDEvents**: Открытая спецификация Continuous Delivery Foundation (CDF) для описания событий в процессах Continuous Delivery (`dev.cdevents.service.deployed`, `dev.cdevents.change.merged` и т. д.), построенная на базе CloudEvents. Актуальная версия спецификации — v0.5.0. Обеспечивает интероперабельность между различными инструментами CI/CD/GitOps.
- **Статус здоровья (Health Status)**: Состояние ресурса в Kubernetes после применения манифестов (Healthy, Progressing, Degraded, Suspended).
- **Контроллер уведомлений (Notification Controller)**: Специализированный компонент GitOps-инструментария (например, в Flux или ArgoCD), отвечающий за фильтрацию событий, формирование сообщений по шаблонам и их доставку провайдерам.
- **Обогащение событий (Event Metadata)**: Добавление контекстной информации (имя кластера, регион, окружение, ссылка на dashboard) к телу события перед доставкой — позволяет отличать алерты из разных кластеров в одном общем канале.

## Базовые концепции

### Цели внедрения алертинга

- **Сокращение MTTR (Mean Time To Recovery)**: Мгновенное оповещение о сбоях в продуктивных окружениях.
- **Прозрачность изменений**: Формирование ленты событий ("Audit Trail") в командных чатах для отслеживания того, кто, когда и какое изменение инициировал.
- **Интеграция с ChatOps**: Возможность не только получать уведомления, но и взаимодействовать с кластером через команды в мессенджерах (при использовании дополнительных ботов).

### Ключевые события и уровни важности

Системы уведомлений обычно классифицируют события по уровням:
- **Info**: Успешная синхронизация, начало процесса обновления образа.
- **Warning**: Дрифт конфигурации (OutOfSync), задержка в достижении состояния Healthy.
- **Error**: Ошибка применения манифеста, ошибка аутентификации в Git-репозитории, переход ресурса в статус Degraded.

Соответствие уровней конфигурации инструментов:

| Уровень | Flux (`eventSeverity`) | ArgoCD (триггеры) |
| :--- | :--- | :--- |
| Info | `info` (все события, включая ошибки) | `on-sync-running`, `on-deployed` |
| Warning | Нет отдельного уровня — фильтруется через `inclusionList`/`exclusionList` по тексту сообщения | `on-sync-status-unknown`, кастомные триггеры |
| Error | `error` (только события с ошибками) | `on-sync-failed`, `on-health-degraded` |

Практическое правило: в production-каналы отправляют только `error`, а `info`-поток выводят в архивный канал или систему аудита, чтобы не размывать внимание дежурных.

### Архитектурные паттерны

1.  **Прямая интеграция**: Контроллер напрямую общается с API мессенджера (например, Telegram Bot API).
2.  **Шина событий (Event Bus)**: Контроллер отправляет события в NATS или Kafka, откуда их забирают различные потребители (consumers). Во Flux для этого есть нативный тип провайдера `nats`, а также `googlepubsub` и `azureeventhub` для облачных шин.
3.  **Агрегация через Webhook**: Использование промежуточных сервисов (Alertmanager, Zapier, n8n) для сложной маршрутизации и трансформации уведомлений.

Выбор паттерна зависит от масштаба: прямая интеграция достаточна для 1–5 кластеров и одного мессенджера; при росте числа кластеров и каналов доставки (мессенджеры, PagerDuty, SIEM, DORA-аналитика) централизованная шина снижает связность и позволяет менять потребителей без переконфигурации кластеров.

### Жизненный цикл уведомления

Типовой путь события от возникновения до доставки (справедливо и для Flux, и для ArgoCD):

1.  **Генерация**: Контроллер реконсиляции (например, `kustomize-controller` или `argocd-application-controller`) эмитит Kubernetes Event о результате операции.
2.  **Перехват**: Notification controller подписан на поток событий кластера и получает копию.
3.  **Фильтрация**: Событие сверяется с правилами подписки (во Flux — `Alert.eventSources` + `eventSeverity`, в ArgoCD — условия триггеров). Не подошедшие события отбрасываются.
4.  **Формирование**: Сообщение собирается по шаблону с подстановкой переменных (имя объекта, сообщение об ошибке, метаданные).
5.  **Доставка**: HTTP-запрос к API провайдера. При сбое выполняются повторные попытки (retry с backoff); недоставленное событие фиксируется в логах контроллера.
6.  **Дедупликация/кеширование**: Идентификаторы уже отправленных уведомлений сохраняются (в ArgoCD — в аннотациях приложения), чтобы повторные идентичные события не порождали дублей сообщений.

### Стратегии борьбы с "шумом"

- **Дедупликация**: Группировка событий по объекту (Involved Object). Если Deployment падает 10 раз подряд, в чат уходит одно сообщение с обновленным счетчиком.
- **Маршрутизация по окружениям**: Алерты из `production` уходят с тегом `@here` в основной канал, а из `dev` — в архивный канал без звуковых уведомлений.
- **Mute Timings**: Подавление уведомлений во время плановых технических работ или в нерабочее время (для некритичных систем).
- **Фильтрация по регулярным выражениям**: Во Flux поля `inclusionList` (пропускать только совпадающие имена объектов) и `exclusionList` (отбрасывать события по шаблону текста, например регулярно повторяющийся `no artifacts changes`) позволяют отсекать заведомо нерелевантные события еще на стороне контроллера.
- **Временное отключение**: Поле `suspend: true` у `Alert`/`Receiver` (Flux) останавливает обработку без удаления конфигурации — удобно на время массовых миграций, когда поток событий прогнозируемо велик.

## Практические сценарии

### Сценарий 1: Уведомления в Flux (GitOps Toolkit)

Flux использует модульную архитектуру, где за уведомления отвечает `notification-controller`.

**Компоненты конфигурации:**
1.  **Provider**: Описывает "куда" отправлять (Slack, Telegram, MS Teams, Discord, NATS, Azure Event Hub, Google Pub/Sub, DataDog, Sentry, PagerDuty, generic webhook и другие — полный список типов в спецификации `v1beta3`).
2.  **Alert**: Описывает "что" и "откуда" (Kustomization, HelmRelease, GitRepository), с какой важностью (`info`/`error`) и с каким обогащением метаданных.
3.  **Receiver**: Входящий вебхук для триггера реконсиляции ресурсов из внешних систем (см. подраздел ниже).

#### Пример настройки Slack

```yaml
# 1. Секрет с токеном/вебхуком
apiVersion: v1
kind: Secret
metadata:
  name: slack-url
  namespace: flux-system
stringData:
  address: "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXX" # Incoming Webhook из настроек Slack App
---
# 2. Провайдер
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: slack-provider
  namespace: flux-system
spec:
  type: slack
  channel: flux-alerts # канал назначения (можно переопределить из секрета)
  secretRef:
    name: slack-url
---
# 3. Алерт
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: critical-alerts
  namespace: flux-system
spec:
  providerRef:
    name: slack-provider
  eventSeverity: error # Только ошибки
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: HelmRelease
      name: '*'
```

После применения манифестов объекты `Alert` и `Provider` являются статическими конфигурациями — они не имеют собственного статуса готовности: созданный объект считается рабочим. Факт работы проверяется только реальным событием (см. «Проверка работоспособности» ниже).

#### Пример настройки Telegram

```yaml
# 1. Секрет с токеном бота (токен выдает @BotFather)
apiVersion: v1
kind: Secret
metadata:
  name: telegram-bot
  namespace: flux-system
stringData:
  token: "123456789:AAF..." # токен Telegram Bot API
---
# 2. Провайдер
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: telegram-provider
  namespace: flux-system
spec:
  type: telegram
  channel: "-1001234567890" # ID чата/канала (для публичных каналов допустимо @channelname)
  # address: https://api.telegram.org # переопределяется только для self-hosted Bot API Server
  secretRef:
    name: telegram-bot
---
# 3. Алерт: весь info-поток в архивный канал
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: info-feed
  namespace: flux-system
spec:
  providerRef:
    name: telegram-provider
  eventSeverity: info # все события, включая ошибки
  eventSources:
    - kind: Kustomization
      name: '*'
```

Чтобы бот мог писать в канал, добавьте его администратором канала. ID приватного чата получают через Bot API: отправьте сообщение боту и откройте `https://api.telegram.org/bot<TOKEN>/getUpdates` — поле `result[].message.chat.id`.

#### Обогащение событий (eventMetadata)

Без обогащения невозможно понять, какому кластеру принадлежит алерт в общем канале. Источники метаданных (в порядке возрастания приоритета):

1.  Аннотации на самих Flux-объектах с префиксом `event.toolkit.fluxcd.io/`;
2.  Поле `Alert.spec.eventMetadata`;
3.  Поле `Alert.spec.summary` (устарело — используйте `eventMetadata.summary`);
4.  Метаданные, добавляемые самим контроллером в payload события.

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: enriched-alerts
  namespace: flux-system
spec:
  providerRef:
    name: slack-provider
  eventSeverity: error
  eventSources:
    - kind: HelmRelease
      name: '*'
  eventMetadata: # статическое обогащение на уровне кластера
    cluster: prod-eu-central-1
    env: production
    region: eu-central-1
    runbook_url: https://runbooks.example.com/gitops
  inclusionList: # обрабатывать только эти объекты по имени (regex)
    - ".*platform.*"
  exclusionList: # отсекать шумные сообщения по тексту (regex)
    - "no objects changed"
    - "reconciliation skipped"
```

При конфликте ключей побеждает источник с более высоким приоритетом, а факт перезаписи фиксируется предупреждением в логах контроллера.

#### Входящие вебхуки (Receiver): триггер реконсиляции извне

`Receiver` решает обратную задачу: внешняя система (CI, Git-хостинг, соседний пайплайн) инициирует немедленную реконсиляцию Flux-ресурсов, не дожидаясь планового интервала. Это вторая половина паттерна «Webhooks» из архитектуры GitOps: исходящие `Alert` информируют мир, входящие `Receiver` получают сигналы от мира.

```yaml
# 1. Секрет с токеном — он же генератор секретного пути вебхука
apiVersion: v1
kind: Secret
metadata:
  name: webhook-token
  namespace: flux-system
stringData:
  token: "long-random-string"
---
# 2. Receiver: push в GitHub триггерит реконсиляцию GitRepository
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: webapp-receiver
  namespace: flux-system
spec:
  type: github # также: gitlab, bitbucket, harbor, dockerhub, quay, nexus, azuredevops, gcr, generic, generic-hmac
  events: ["ping", "push"] # какие события вебхука принимать
  secretRef:
    name: webhook-token
  resources:
    - apiVersion: source.toolkit.fluxcd.io/v1
      kind: GitRepository
      name: webapp
      namespace: flux-system
```

Адрес вебхука формируется из SHA256-хеша токена: `<external-url-of-notification-controller>/hook/<sha256(token)>`. Стандартно контроллер публикуется через Ingress на хост вида `hook.<cluster-domain>`; внутренний адрес — `http://notification-controller.flux-system.svc.cluster.local./hook/<id>`. Для систем без поддержки подписи HMAC используется тип `generic-hmac`; начиная с notification-controller v1.9 доступен тип `generic-oidc`, где вызывающий аутентифицируется OIDC ID-токеном вместо общего секрета (бесшовная интеграция с платформами, поддерживающими OIDC; см. также [Flux: Обзор и Ключевые Концепции](./flux.md)).

Настройка со стороны Git-хостинга: создайте webhook репозитория на URL из шага выше, content-type `application/json`, secret — тот же `token`. Flux проверит подпись `X-Hub-Signature-256` каждого запроса.

#### Новое в notification-controller (2025–2026)

Версионирование контроллера уведомлений независимо от версий Flux (например, Flux v2.9 включает notification-controller v1.9.x). Ключевые изменения последних релизов:

- **notification-controller v1.8**: **PR Comments** — автоматическое комментирование Pull/Merge Request в GitHub/GitLab о статусе проверки манифестов; **mTLS** — поддержка двустороннего TLS для транспорта событий и связи с GitHub App.
- **notification-controller v1.9**: тип Receiver `generic-oidc` — аутентификация вызывающего по OIDC ID-токену вместо общего HMAC-секрета, фильтрация ресурсов CEL-выражениями; поле `Provider.spec.proxySecretRef` для проксирования исходящих событий (старые поля `.spec.proxy` объявлены устаревшими); из состава CRD удалена API-версия `v1beta2` — манифесты на ней перестают применяться.
- Безопасность: GCR-Receiver'ы требуют полей `email` и `audience` в Secret (исправление CVE-2026-40109) — проверьте существующие Receivers после обновления.

#### Проверка работоспособности

```bash
# 1. Убедиться, что объекты созданы и CRD зарегистрированы
kubectl get providers.notification.toolkit.fluxcd.io \
  alerts.notification.toolkit.fluxcd.io \
  receivers.notification.toolkit.fluxcd.io -n flux-system
# → NAME              AGE
# → slack-provider    30s
# → critical-alerts   25s
# → webapp-receiver   20s

# 2. Проверить здоровье самого контроллера
flux check
# → ✔ notification-controller is healthy

# 3. Спровоцировать тестовое событие: аннотация запрашивает внеплановую реконсиляцию
flux reconcile kustomization flux-system --with-source
# → ► annotating Kustomization flux-system in flux-system namespace
# → ◎ waiting for Kustomization reconciliation
# → ✔ reconciled successfully

# 4. Наблюдать за обработкой события контроллером
kubectl logs -n flux-system deploy/notification-controller --tail=50 | grep -i "slack\|alert"
# → {"level":"info","ts":"...","logger":"event-server","msg":"dispatching event", ...}
```

Если шаг 4 показывает `dispatching event`, а сообщение в мессенджере не появилось — проблема на стороне провайдера (см. таблицу типовых проблем ниже).

#### Типовые проблемы (Flux)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Сообщения не приходят, в логах нет `dispatching event` | Событие отфильтровано: `eventSeverity: error`, а происходит успешная синхронизация | Отправлять `info`-поток или спровоцировать ошибку (сломать манифест намеренно) для проверки |
| `429 Too Many Requests` от Telegram/Slack API | Rate limit мессенджера при массовом применении (например, bootstrap нового кластера) | Разделить потоки: error-канал отдельно от info; добавить `exclusionList`; временно `suspend: true` у info-алерта |
| `401 Unauthorized` / `403 Forbidden` в логах контроллера | Невалидный токен в Secret, истекший Incoming Webhook, бот исключен из канала | Перевыпустить токен/вебхук, обновить Secret, проверить права бота в канале |
| Сообщение приходит, но непонятно из какого кластера | Нет обогащения `eventMetadata` | Добавить `cluster`/`env`/`region` в `Alert.spec.eventMetadata` или аннотации объектов |
| Вебхук Receiver отвечает `404` | Неправильный путь: хеш токена не совпадает с URL в настройках Git-хостинга | Взять точный путь из `.status.webhookPath` ресурса Receiver и пересверить с URL вебхука |
| Вебхук Receiver отвечает `403` | Подпись HMAC не совпадает (secret в Git-хостинге отличается от `token` в Secret) | Синхронизировать значение токена; проверить, что Git-хостинг шлет подпись (не отключена ли она) |
| После обновления Flux объекты `Alert`/`Provider` не применяются | Манифесты на удаленной версии API (`v1beta1`/`v1beta2` исключены из CRD) | Выполнить `flux migrate` — перепишет `apiVersion` в манифестах Git и переведет объекты в кластере (см. [Flux: Обзор](./flux.md)) |

### Сценарий 2: Уведомления в ArgoCD

ArgoCD Notifications интегрированы в основной контроллер (начиная с v3.x), что упрощает управление.

**Основные настройки:**
- **Triggers**: Условия отправки (например, `on-deployed`, `on-health-degraded`).
- **Templates**: Шаблоны сообщений с поддержкой переменных (`{{.app.metadata.name}}`).
- **Subscriptions**: Подписка конкретных приложений через аннотации.

Модель отличается от Flux: вместо отдельных CRD используется ConfigMap (`argocd-notifications-cm`) для триггеров/шаблонов и Secret (`argocd-notifications-secret`) для учетных данных сервисов. Готовые встроенные триггеры покрывают большинство потребностей; подписка приложения выглядит как аннотация `notifications.argoproj.io/subscribe.on-sync-failed.slack: ops-channel`.

Для выбора между инструментами полезно сравнение моделей конфигурации и триггеров двух контроллеров — таблица приведена в разделе «Сравнение с Flux notification-controller» детального руководства.

> **Детальное руководство по настройке:** см. **[ArgoCD Notifications: Настройка уведомлений](./ArgoCD/argocd_notifications.md)**.

### Сценарий 3: Использование CDEvents для мультиинструментальных сред

Если в организации используются одновременно ArgoCD, Flux и Tekton, целесообразно использовать стандарт CDEvents.

- **Workflow**: Каждый инструмент отправляет события в формате CloudEvents на центральный брокер.
- **Результат**: Единый формат уведомлений и возможность строить аналитику (DORA metrics) на основе стандартизированных данных.

**Роли инструментов (по состоянию на 2026):**

| Инструмент | Роль в экосистеме CDEvents |
| :--- | :--- |
| Tekton | Нативный producer (pipeline/task события) |
| Jenkins | Producer через плагин |
| Spinnaker | Producer (deployment события) |
| ArgoCD | Producer (события sync и деплоя приложений) |
| Flux | Producer через notification-controller (события реконсиляции и деплоя) |
| Keptn | Producer и consumer (lifecycle-наблюдаемость) |

#### Практическая схема: единая лента событий через брокер

Целевая топология: каждый кластер публикует события в центральный брокер (NATS/Kafka/Knative Eventing), потребители (мессенджер-роутер, SIEM, DORA-коллектор) читают из брокера один стандартизированный поток.

```yaml
# Flux -> NATS: публикация событий реконсиляции в шину
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: nats-bus
  namespace: flux-system
spec:
  type: nats
  address: nats://nats.example.com:4222
  secretRef:
    name: nats-credentials # user/password или токен
  channel: cd.events # subject NATS, на который публикуются события
---
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: bus-events
  namespace: flux-system
spec:
  providerRef:
    name: nats-bus
  eventSeverity: info # в шину уходят все события — фильтрацию делают потребители
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: OCIRepository
      name: '*'
```

Обратное направление — реакция Flux на события из конвейера (например, мердж PR должен запустить реконсиляцию) — реализуется Receiver'ом с типом `cdevents`, который принимает валидные CDEvents и триггерит ресурсы:

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: cdevents-receiver
  namespace: flux-system
spec:
  type: cdevents
  events:
    - "dev.cdevents.change.merged" # реагировать только на мердж изменений
  secretRef:
    name: receiver-token # HMAC-проверка отправителя
  resources:
    - apiVersion: source.toolkit.fluxcd.io/v1
      kind: GitRepository
      name: webapp
      namespace: flux-system
```

**Проверка сквозного сценария:**
```bash
# 1. Отправить тестовый CDEvent в URL Receiver'а (payload по схеме CloudEvents envelope)
curl -si -X POST "https://hook.example.com/hook/<sha256-token>" \
  -H "Content-Type: application/cloudevents+json" \
  -d '{"specversion":"1.0","type":"dev.cdevents.change.merged",
       "source":"https://git.example.com/webapp","id":"'"$(uuidgen)"'",
       "time":"2026-08-24T10:00:00Z"}'
# → HTTP/2 200

# 2. Убедиться, что реконсиляция была запущена именно вебхуком:
#    поле .status.lastHandledReconcileAt изменилось одновременно с запросом
kubectl get gitrepository webapp -n flux-system \
  -o jsonpath='{.status.lastHandledReconcileAt}'; echo

# 3. На стороне брокера убедиться в публикации:
nats sub cd.events --server nats://nats.example.com:4222
# → [#1] received on "cd.events"
```

Такой контур закрывает обе задачи: операционные уведомления людям (через потребителей брокера, маршрутизующих в Slack/Telegram) и машинную интеграцию инструментов между собой, включая расчет DORA-метрик (частота деплоя, lead time, MTTR, failure rate) по стандартизированным событиям, а не по парсингу разнородных логов.

## Мониторинг самой системы уведомлений

Система уведомлений — тоже критический компонент: ее молчаливый отказ означает отсутствие сигналов о реальных инцидентах. Минимальный набор контроля:

- **Метрики контроллера** (порт `:8080` notification-controller, стандартное семейство `gotk_*`): `gotk_reconcile_condition{kind="Receiver",...}` — успех последней реконсиляции объектов уведомлений; `gotk_suspend_status` — обнаружение случайно suspended алертов; `gotk_last_reconciled_timestamp` — свежесть обработки.
- **Heartbeat-алерт**: синтетическая проверка «канал жив»: периодическая задача отправляет тестовое событие через Provider и фиксирует доставку; отсутствие heartbeat дольше N часов само является алертом (правило «alert if no alerts»).
- **Логи**: ошибки доставки провайдеров пишутся в лог notification-controller — их стоит собирать централизованно (Loki/ELK) и алертить по росту частоты `failed to` в контексте event-server.

```yaml
# Пример PrometheusRule: контроллер уведомлений не справляется с реконсиляцией
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: flux-notification-alerts
  namespace: flux-system
spec:
  groups:
    - name: flux-notification
      rules:
        - alert: NotificationControllerReconcileFailing
          expr: |
            gotk_reconcile_condition{kind="Receiver", status="False", type="Ready"} == 1
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "Receiver {{ $labels.name }} не реконцилируется более 15 минут"
```

## Дополнительная информация

**Связанные документы:**
- [ArgoCD Notifications: детальное руководство](./ArgoCD/argocd_notifications.md) — полное руководство по настройке ArgoCD.
- [Flux: Обзор и Ключевые Концепции](./flux.md) — общая архитектура Flux.
- [Интеграция Grafana с Telegram](../Grafana/alerting/telegram-integration.md) — примеры шаблонов для Telegram.

**Рекомендации:**
1. **Безопасность**: Никогда не храните токены ботов и URL вебхуков в открытом виде в Git. Используйте [Sealed Secrets](./secrets_encryption.md) или External Secrets. Для входящих вебхуков всегда используйте проверку подписи (HMAC-типы Receiver, OIDC для платформ с поддержкой) — открытый endpoint без проверки превращает реконсиляцию в примитив для DoS.
2. **Шаблонизация**: Включайте в уведомления ссылки на логи (Grafana/Kibana) и на сам ресурс в UI ArgoCD/Flux для ускорения диагностики. Добавляйте `eventMetadata` (кластер, регион, окружение) — общий канал без этой информации бесполезен при нескольких кластерах.
3. **Версионность**: При обновлении контроллеров всегда проверяйте API-версии ресурсов `Provider`, `Alert` и `Receiver` (актуально: `v1beta3` для Provider/Alert, `v1` для Receiver; версии ниже `v1beta3` удалены из состава CRD). Используйте команду `flux migrate` для автоматической миграции манифестов.
4. **Rate limiting**: Помните об ограничениях API мессенджеров: Telegram — ~30 сообщений/сек на бота и ~20/мин в один канал, Slack — burst-лимиты на метод posting. Массовые операции (bootstrap, bulk-миграции) легко исчерпывают лимиты; разделяйте error/info потоки и применяйте `suspend` на время таких операций.
5. **Очистка окружения** (откат сценария 1):
   ```bash
   kubectl delete alert/critical-alerts alert/info-feed alert/enriched-alerts -n flux-system
   kubectl delete provider/slack-provider provider/telegram-provider -n flux-system
   kubectl delete receiver/webapp-receiver receiver/cdevents-receiver -n flux-system
   kubectl delete secret/slack-url secret/telegram-bot secret/webhook-token -n flux-system
   ```
   Также удалите вебхук из настроек Git-репозитория и Ingress-маршрут хоста `hook.<domain>`, если он больше не нужен.
