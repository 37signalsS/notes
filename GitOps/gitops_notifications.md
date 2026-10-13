# GitOps: Уведомления о статусе развертываний

**Актуально для:** Flux v2.9.x (notification-controller v1.9.x), Argo CD v3.5+, Kubernetes 1.28–1.32+ (on-premise / bare-metal)

Уведомления являются неотъемлемой частью GitOps-пайплайна (Infrastructure as Code). Они обеспечивают проактивный мониторинг состояния инфраструктуры и сервисов, позволяя командам эксплуатации и разработки получать оперативную информацию о результатах реконсиляции, дрейфе конфигурации и сбоях развертываний без необходимости непрерывного ручного контроля консоли или дашбордов.

---

## Определения

- **Уведомление (Notification)**: Автоматическое сообщение о событии в жизненном цикле объектов Kubernetes (Sync Succeeded, Failed, Degraded, Drift Detected), отправляемое во внешние системы связи (Mattermost, Telegram, Slack, Webhooks, корпоративная почта).
- **Вебхук (Webhook)**: Метод межсистемного взаимодействия по протоколу HTTP (обычно запросы `POST` с телом JSON). При возникновении события контроллер направляет данные на эндпоинт приемника.
- **Исходящее уведомление (Outbound Notification)**: Оповещение о событиях в кластере, отправляемое контроллером во внешнюю среду («кластер → мессенджер/шина»). Во Flux реализуется связкой `Provider` + `Alert`, в Argo CD — контроллером `argocd-notifications-controller`.
- **Входящий вебхук (Inbound Webhook Receiver)**: Прием внешних HTTP-сигналов для немедленного запуска цикла реконсиляции («CI/реестр контейнеров → кластер») без ожидания планового интервала опроса. Во Flux реализуется ресурсом `Receiver`.
- **Контроллер уведомлений (Notification Controller)**: Специализированный контроллер GitOps-инструментария (например, `notification-controller` во Flux или `argocd-notifications-controller` в Argo CD), отвечающий за перехват событий, фильтрацию, шаблонизацию и доставку сообщений.
- **Обогащение событий (Event Metadata)**: Добавление контекстных атрибутов (имя кластера, дата-центр, окружение, ссылка на Runbook) к телу события перед отправкой для однозначной идентификации источника в мультикластерной среде.
- **Дрейф конфигурации (Drift / OutOfSync)**: Расхождение между эталонным декларативным состоянием в Git-репозитории и фактическим состоянием объектов в кластере Kubernetes.
- **Дедупликация и троттлинг (Deduplication & Rate Limiting)**: Механизмы подавления повторных идентичных сообщений и ограничения частоты исходящих запросов для предотвращения блокировок со стороны API приемников (HTTP 429 Too Many Requests).
- **Дребезг событий (Flapping)**: Высокочастотное циклическое переключение статуса ресурса (например, между Healthy и Degraded при CrashLoopBackOff), порождающее лавину однотипных уведомлений (Alert Storm).
- **CDEvents**: Открытая спецификация Continuous Delivery Foundation (CDF) на базе спецификации CloudEvents (CNCF), стандартизирующая схему метаданных событий непрерывной доставки (`dev.cdevents.service.deployed`, `dev.cdevents.change.merged`) для интероперабельности между гетерогенными CI/CD-системами.
- **Common Expression Language (CEL)**: Декларативный язык вычисления выражений, используемый в Kubernetes и современных версиях Flux/Argo CD для гранулярной фильтрации событий и полей ресурсов без накладных расходов на полноценный скриптинг.
- **Взаимный TLS (mTLS)**: Протокол двусторонней криптографической аутентификации клиента и сервера по сертификатам X.509, применяемый для безопасной передачи вебхуков в изолированных корпоративных контурах.

---

## Архитектура и базовые концепции

### Цели внедрения алертинга в GitOps

1. **Сокращение MTTR (Mean Time To Recovery)**: Немедленная доставка контекста инцидента (стек ошибки Kustomize, сбой pre-install хука Helm, конфликт Server-Side Apply) дежурному инженеру.
2. **Прозрачность изменений (Audit Trail)**: Автоматическая публикация журнала синхронизаций в командных каналах с указанием автора коммита, SHA-хеша и измененных манифестов.
3. **Обратная связь для CI/CD-пайплайнов**: Информирование сборочных конвейеров о завершении выкатки в кластер для запуска интеграционных и нагрузочных тестов.
4. **Интеграция с ChatOps**: Предоставление дежурным первичных ссылок на логи, метрики и команды отката непосредственно из сообщения в чате.

### Классификация событий и матрица критичности

GitOps-контроллеры генерируют события Kubernetes (Events), которые категоризируются по уровням:

| Уровень важности | Flux Toolkit (`eventSeverity`) | Argo CD (состояния триггеров) | Типовые сценарии | Канал назначения |
| :--- | :--- | :--- | :--- | :--- |
| **Info** | `info` (включает успешные и информационные события) | `on-deployed`, `on-sync-running`, `on-sync-succeeded` | Успешная реконсиляция, скачивание нового артефакта Git/OCI, плановый опрос | Архивный аудит-канал, SIEM, брокер метрик |
| **Warning** | Фильтруется через `exclusionList` / CEL-выражения | `on-sync-status-unknown`, предупреждения валидации | Дрейф конфигурации, задержка готовности подов (Progressing) | Инженерный чат команды сервиса |
| **Error** | `error` (только сбои и ошибки) | `on-sync-failed`, `on-health-degraded` | Ошибка парсинга YAML, откат HelmRelease, CrashLoopBackOff контроллеров | Основной дежурный канал (On-Call SRE), пейджер |

> **Правило SRE:** В каналы с включенными звуковыми оповещениями (дежурные смены) направляются исключительно события уровня `Error`. Информационный поток (`Info`) направляется в немой канал аудита или централизованную шину сообщений.

### Сравнение архитектурных моделей: Flux vs Argo CD

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        АРХИТЕКТУРНЫЕ МОДЕЛИ УВЕДОМЛЕНИЙ В GITOPS                       │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [ FLUX TOOLKIT: ДЕКЛАРАТИВНЫЕ CRD ]          [ ARGO CD: CONFIGMAP + АННОТАЦИИ ]       │
│                                                                                        │
│  ┌───────────────────────────────┐            ┌─────────────────────────────────────┐  │
│  │ Kustomization / HelmRelease   │            │ Application CR                      │  │
│  └───────────────┬───────────────┘            └──────────────────┬──────────────────┘  │
│                  │ K8s Event                                     │ Watch status        │
│                  ▼                                               ▼                     │
│  ┌───────────────────────────────┐            ┌─────────────────────────────────────┐  │
│  │ notification-controller       │            │ argocd-notifications-controller     │  │
│  │  - Alert CR (фильтрация)      │            │  - argocd-notifications-cm (логика) │  │
│  │  - Provider CR (транспорт)    │            │  - argocd-notifications-secret (auth│  │
│  │  - Receiver CR (входящие хуки)│            │  - Аннотации подписки на Application│  │
│  └───────────────┬───────────────┘            └──────────────────┬──────────────────┘  │
│                  │                                               │                     │
│                  └───────────────────────┬───────────────────────┘                     │
│                                          │ Outbound HTTP POST                          │
│                                          ▼                                             │
│                     ┌─────────────────────────────────────────┐                        │
│                     │ Корпоративные сервисы доставки          │                        │
│                     │ • Mattermost / Slack / Telegram Bot     │                        │
│                     │ • On-Premise Event Bus (NATS / Kafka)   │                        │
│                     │ • Prometheus Alertmanager Webhook       │                        │
│                     └─────────────────────────────────────────┘                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

| Критерий | Flux (`notification-controller`) | Argo CD (`argocd-notifications-controller`) |
| :--- | :--- | :--- |
| **Единица конфигурации** | Нативные Kubernetes CRD (`Provider`, `Alert`, `Receiver`) | Централизованный ConfigMap (`argocd-notifications-cm`) и аннотации на `Application` |
| **Управление правами (RBAC)** | Стандартный RBAC Kubernetes на уровне namespace для каждого CRD | Доступ к ConfigMap в namespace `argocd` или режим Self-service в namespaces |
| **Входящие вебхуки** | Нативный ресурс `Receiver` (мгновенный триггер реконсиляции) | Встроенный Webhook-сервер `argocd-server` (`/api/webhook`) |
| **Язык шаблонизации** | Фиксированные шаблоны провайдеров с обогащением через `eventMetadata` | Мощный Go-шаблонизатор (`text/template`) со Sprig-функциями |
| **Локальная шина событий** | Нативная поддержка провайдера `nats` | Вебхуки в локальные HTTP-адаптеры / брокеры |

### Архитектурные паттерны доставки

1. **Прямая интеграция (Direct Push)**: Контроллер напрямую выполняет исходящий HTTP-запрос к API сервиса связи (Telegram Bot API, Mattermost Incoming Webhook, корпоративный SMTP). Оптимально для небольших и средних сред (до 5 кластеров).
2. **Шина событий (Event Bus Pattern)**: Контроллеры публикуют события в локальный отказоустойчивый брокер сообщений (NATS JetStream, Apache Kafka). Потребители (боты, аналитика DORA, SIEM) подписываются на топики брокера. Устраняет зависимость кластера от доступности внешних чат-платформ.
3. **Агрегация через Webhook-шлюз**: Отправка событий в локальный Prometheus Alertmanager или корпоративный оркестратор автоматизации (n8n, локальный webhook-сервер) для сложной группировки, дедупликации и маршрутизации по расписанию дежурств.

### Жизненный цикл события

1. **Генерация события**: Внутренний контроллер (`kustomize-controller`, `helm-controller`, `argocd-application-controller`) завершает итерацию реконсиляции и публикует Kubernetes Event в API-сервер.
2. **Перехват**: Контроллер уведомлений, подписанный на поток событий, считывает объект через Informer-кэш.
3. **Фильтрация и сопоставление**:
   - Во Flux: сопоставление источника (`eventSources`), уровня (`eventSeverity`) и регулярных выражений (`inclusionList` / `exclusionList`).
   - В Argo CD: вычисление булевых предикатов триггеров на языке `expr`.
4. **Дедупликация и проверка дребезга**: Сверка хэша события или ревизии коммита с кэшем последних доставок во избежание повторной отправки идентичных сообщений.
5. **Обогащение и рендеринг**: Формирование тела сообщения, внедрение глобальных метаданных (`cluster`, `dc`, `env`, ссылки на документацию).
6. **Сетевая доставка**: Выполнение HTTP POST с экспортом метрик времени задержки и кодов ответа. При временных сбоях (сеть, HTTP 5xx) срабатывает повтор с экспоненциальной задержкой (exponential backoff).

### Стратегии борьбы с шумом и Alert Fatigue

- **Regex-фильтрация во Flux**: Использование `exclusionList` для отсечения регулярных информационных сообщений (например, `.*no changes.*`, `.*reconciliation skipped.*`).
- **Спецификаторы `oncePer` в Argo CD**: Ограничение срабатывания триггера строгим изменением ревизии коммита (`sync.revision`), предотвращающее отправку алертов при каждом плановом цикле сверки.
- **Временное отключение (`suspend: true`)**: Флаг в манифестах `Alert` и `Receiver` во Flux, позволяющий заморозить генерацию уведомлений на период регламентных работ без удаления конфигурации.
- **Разделение каналов по окружениям**: Разделение потоков production, staging и dev по независимым чатам и топикам.

---

## Практические сценарии и конфигурация

### Предварительные требования

Перед развертыванием практических конфигураций убедитесь в доступности инфраструктурных компонентов:

| Компонент | Минимальная версия | Назначение | Команда проверки |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.28+ (on-premise / bare-metal) | Среда исполнения GitOps-операторов | `kubectl version --short` |
| **Flux** | v2.7+ (рекомендуется v2.9.x) | GitOps-контроллеры и notification-controller | `flux check` |
| **Argo CD** | v3.4+ / v3.5+ | GitOps-платформа (для сценария 2) | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-notifications-controller` |
| **Mattermost / Telegram** | Актуальный API | Приемники входящих сообщений | `curl -sS -X POST <webhook-url> -d '{"text":"test"}'` |
| **NATS** | v2.10+ (self-hosted) | Локальный брокер шины сообщений | `nats server ping --server nats.msg-broker.svc:4222` |

Исходное состояние: пространство имен `flux-system` инициализировано, утилиты `kubectl` и `flux` настроены с административным доступом к кластеру.

---

### Сценарий 1: Уведомления и алертинг во Flux (GitOps Toolkit)

Flux использует модульную архитектуру GitOps Toolkit, в которой нотификации обслуживаются оператором `notification-controller`. Конфигурация состоит из трех типов ресурсов:
1. `Provider` — точка интеграции с внешней платформой (адрес, учетные данные, прокси, сертификаты).
2. `Alert` — правила маршрутизации событий (какие ресурсы слушать, с какой важностью и куда отправлять).
3. `Receiver` — входящий вебхук для немедленной инициализации реконсиляции по внешнему сигналу.

#### 1.1 Интеграция с корпоративным Mattermost / Slack (Исходящие уведомления)

Провайдер типа `slack` во Flux полностью совместим с self-hosted платформой Mattermost (поддерживающей Incoming Webhooks) и корпоративными серверами Slack.

```yaml
# 1. Секрет с вебхуком Mattermost / Slack
apiVersion: v1
kind: Secret
metadata:
  name: mattermost-webhook-url
  namespace: flux-system
type: Opaque
stringData:
  address: "https://mattermost.corp.internal/hooks/xxxx-incoming-webhook-key-xxxx"
---
# 2. Провайдер доставки
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: mattermost-provider
  namespace: flux-system
spec:
  type: slack
  channel: gitops-alerts
  username: Flux-Bot
  secretRef:
    name: mattermost-webhook-url
---
# 3. Алерт только для критических сбоев Kustomization и HelmRelease
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: critical-workload-alerts
  namespace: flux-system
spec:
  providerRef:
    name: mattermost-provider
  eventSeverity: error
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: HelmRelease
      name: '*'
  eventMetadata:
    cluster: k8s-prod-dc1
    dc: dc-msk-01
    env: production
    runbook: "https://wiki.corp.internal/runbooks/gitops-failures"
  exclusionList:
    - ".*reconciliation skipped.*"
    - ".*no changes.*"
```

#### 1.2 Интеграция с Telegram Bot API с разделением потоков

Для взаимодействия с Telegram создается бот через `@BotFather` и извлекается идентификатор канала или группы (`channel`).

```yaml
# 1. Секрет с токеном Telegram бота
apiVersion: v1
kind: Secret
metadata:
  name: telegram-bot-token
  namespace: flux-system
type: Opaque
stringData:
  token: "7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
---
# 2. Провайдер Telegram
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: telegram-provider
  namespace: flux-system
spec:
  type: telegram
  channel: "-1001987654321" # ID супергруппы или закрытого канала
  secretRef:
    name: telegram-bot-token
---
# 3. Алерт для общего информационного аудита (Info-поток)
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: audit-feed-alerts
  namespace: flux-system
spec:
  providerRef:
    name: telegram-provider
  eventSeverity: info
  eventSources:
    - kind: Kustomization
      name: "infra-*"
    - kind: GitRepository
      name: '*'
  eventMetadata:
    cluster: k8s-prod-dc1
    environment: production
```

> **Важно:** Бот должен быть предварительно добавлен в канал администратором с правом публикации сообщений. Для получения `channel_id` отправьте тестовое сообщение в группу с ботом и выполните `curl -s https://api.telegram.org/bot<TOKEN>/getUpdates | jq '.result[].message.chat.id'`.

#### 1.3 Входящие вебхуки (Receiver): Мгновенная реконсиляция по Push-событиям

По умолчанию Flux опрашивает Git-репозитории с интервалом `spec.interval` (например, раз в 5–10 минут). Ресурс `Receiver` открывает защищенный HTTP-эндпоинт, при обращении к которому `source-controller` немедленно скачивает свежий коммит.

```yaml
# 1. Секрет с HMAC-токеном авторизации вебхука
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-webhook-secret
  namespace: flux-system
type: Opaque
stringData:
  token: "9f82c4e1a6b8d7e3f2c5a1b4d8e7f9a2b3c4d5e6f7a8b9c0"
---
# 2. Определение входящего вебхука для on-premise GitLab / Gitea
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: gitlab-receiver
  namespace: flux-system
spec:
  type: gitlab # Доступны: gitlab, github, gitea, bitbucket, harbor, generic, generic-hmac, cdevents
  events:
    - "Push Hook"
    - "Tag Push Hook"
  secretRef:
    name: gitlab-webhook-secret
  resources:
    - apiVersion: source.toolkit.fluxcd.io/v1
      kind: GitRepository
      name: fleet-infra
      namespace: flux-system
```

После применения манифеста `notification-controller` генерирует секретный путь, основанный на SHA256-хэше переданного токена.

**Публикация Receiver через Ingress (on-premise):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: flux-receiver-ingress
  namespace: flux-system
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/proxy-body-size: "5m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  rules:
    - host: flux-webhook.corp.internal
      http:
        paths:
          - path: /hook/
            pathType: Prefix
            backend:
              service:
                name: notification-controller
                port:
                  number: 80
```

#### 1.4 Корпоративная безопасность: Корпоративный Forward Proxy и собственный PKI

В изолированных дата-центрах (on-premise) прямой доступ из подов в интернет запрещен. Доставка во внешние сервисы (например, Telegram API) должна маршрутизироваться через корпоративный Forward Proxy, а обращения к внутренним системам (Mattermost, GitLab) — валидироваться корпоративным корневым CA.

Начиная с `notification-controller` v1.9 (Flux v2.9), настройка прокси и сертификатов вынесена в декларативные поля спецификации `Provider`:

```yaml
# 1. Секрет с параметрами корпоративного HTTP(S) прокси
apiVersion: v1
kind: Secret
metadata:
  name: corp-proxy-credentials
  namespace: flux-system
type: Opaque
stringData:
  http_proxy: "http://proxy-user:ProxyPass123@proxy.corp.internal:3128"
  https_proxy: "http://proxy-user:ProxyPass123@proxy.corp.internal:3128"
  no_proxy: ".corp.internal,.cluster.local,10.0.0.0/8"
---
# 2. Секрет с корпоративным корневым сертификатом (Root CA)
apiVersion: v1
kind: Secret
metadata:
  name: internal-root-ca
  namespace: flux-system
type: Opaque
stringData:
  ca.crt: |
    -----BEGIN CERTIFICATE-----
    MIIEAzCCAuugAwIBAgIUWxxxxCorporateInternalRootCAxxxx
    -----END CERTIFICATE-----
---
# 3. Provider с привязкой прокси и сертификатов
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: corp-secured-provider
  namespace: flux-system
spec:
  type: slack
  channel: gitops-alerts
  secretRef:
    name: mattermost-webhook-url
  proxySecretRef:
    name: corp-proxy-credentials
  certSecretRef:
    name: internal-root-ca
```

---

### Сценарий 2: Архитектура уведомлений в Argo CD и интеграция

В Argo CD подсистема оповещений реализована через встроенный компонент `argocd-notifications-controller` (входит в стандартную поставку версий v3.x).

В отличие от модели CRD во Flux, архитектура Argo CD базируется на централизованном ConfigMap `argocd-notifications-cm` и подписках через аннотации:
- **Triggers**: Логические условия отправки, описанные на синтаксисе библиотеки `antonmedv/expr`.
- **Templates**: Go-шаблоны оформления сообщений с поддержкой markdown-разметки и блоков параметров.
- **Services**: Конфигурации адаптеров доставки (Telegram, Slack, Webhook, SMTP).
- **Subscriptions**: Декларативная привязка триггеров к приложениям через аннотации ресурса `Application`.

Пример аннотации подписки на ресурс `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-service
  namespace: argocd
  annotations:
    # Подписка на ошибку синхронизации в Mattermost/Slack
    notifications.argoproj.io/subscribe.on-sync-failed.mattermost: "sre-alerts-channel"
    # Подписка на деградацию здоровья пода в Telegram
    notifications.argoproj.io/subscribe.on-health-degraded.telegram: "-1001987654321"
spec:
  project: default
  source:
    repoURL: 'https://gitlab.corp.internal/apps/billing.git'
    targetRevision: HEAD
    path: deploy
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: billing
```

> **Единый источник истины по Argo CD:** Детальная настройка сервисов, контекста, синтаксиса триггеров и Go-шаблонов приведена в профильном документе: **[ArgoCD Notifications: Настройка уведомлений](./ArgoCD/argocd_notifications.md)**.

---

### Сценарий 3: Мультиинструментальная интеграция через локальную шину NATS и CDEvents

В гетерогенных enterprise-инфраструктурах, где одновременно функционируют Flux, Argo CD и автоматизированные пайплайны сборки, прямая интеграция каждого инструмента с чатами порождает хаос. Целевая топология — публикация событий в единую on-premise шину сообщений (NATS) в стандартизированном формате CDEvents.

#### 3.1 Публикация событий Flux в шину NATS

```yaml
# 1. Секрет аутентификации в кластере NATS
apiVersion: v1
kind: Secret
metadata:
  name: nats-cluster-auth
  namespace: flux-system
type: Opaque
stringData:
  token: "NatsSecretClientToken98765"
---
# 2. Провайдер NATS
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Provider
metadata:
  name: nats-event-bus
  namespace: flux-system
spec:
  type: nats
  address: "nats://nats.msg-broker.svc.cluster.local:4222"
  channel: "gitops.events.flux" # Тема (subject) в NATS
  secretRef:
    name: nats-cluster-auth
---
# 3. Алерт для экспорта всех событий реконсиляции в шину
apiVersion: notification.toolkit.fluxcd.io/v1beta3
kind: Alert
metadata:
  name: stream-all-to-bus
  namespace: flux-system
spec:
  providerRef:
    name: nats-event-bus
  eventSeverity: info
  eventSources:
    - kind: Kustomization
      name: '*'
    - kind: HelmRelease
      name: '*'
    - kind: OCIRepository
      name: '*'
```

#### 3.2 Входящий Receiver стандарта CDEvents

Flux поддерживает прием CDEvents (спецификация Continuous Delivery Foundation) через отдельный тип ресивера `cdevents`. При публикации события о завершении пайплайна в формате CloudEvents ресивер валидирует сигнатуру и инициирует синхронизацию:

```yaml
apiVersion: notification.toolkit.fluxcd.io/v1
kind: Receiver
metadata:
  name: cdevents-pipeline-receiver
  namespace: flux-system
spec:
  type: cdevents
  events:
    - "dev.cdevents.change.merged"
    - "dev.cdevents.artifact.published"
  secretRef:
    name: gitlab-webhook-secret
  resources:
    - apiVersion: source.toolkit.fluxcd.io/v1
      kind: GitRepository
      name: fleet-infra
      namespace: flux-system
```

---

## Эксплуатация и регламентные операции

### 1. Верификация состояния подсистемы уведомлений

```bash
# 1. Проверка регистрации CRD и статуса контроллера Flux
flux check --components=notification-controller
# → ✔ notification-controller: deployment/notification-controller is healthy
# → ✔ all checks passed

# 2. Проверка состояния объектов Provider, Alert и Receiver
kubectl get providers.notification.toolkit.fluxcd.io,alerts.notification.toolkit.fluxcd.io,receivers.notification.toolkit.fluxcd.io -n flux-system
# → NAME                                                   READY   STATUS   AGE
# → provider.notification.toolkit.fluxcd.io/mattermost     True    Ready    5m
# → alert.notification.toolkit.fluxcd.io/critical-workloads True   Ready    5m
# → receiver.notification.toolkit.fluxcd.io/gitlab-receiver True   Ready    5m

# 3. Извлечение сгенерированного адреса вебхука для настройки в GitLab / CI
kubectl get receiver gitlab-receiver -n flux-system -o jsonpath='{.status.webhookPath}'
# → /hook/c8f2b3e8a71d4e0b5f12a3456789abcdef0123456789abcdef0123456789abcd
```

### 2. Тестирование сквозной доставки сообщений

Для проверки доставки без внесения деструктивных изменений в репозитории спровоцируйте внеплановую реконсиляцию с аннотацией:

```bash
# Спровоцировать реконсиляцию Kustomization
flux reconcile kustomization flux-system --with-source
# → ► annotating Kustomization flux-system in flux-system namespace
# → ◎ waiting for Kustomization reconciliation
# → ✔ reconciled successfully

# Просмотр логов диспетчеризации событий контроллером
kubectl logs -n flux-system deploy/notification-controller --tail=50 | grep -i "dispatching"
# → {"level":"info","ts":"2026-10-13T15:20:11.102Z","logger":"event-server","msg":"dispatching event","provider":"mattermost-provider","eventSeverity":"info"}
```

Тестирование входящего эндпоинта Receiver через `curl`:

```bash
# Тестовый запрос вебхука (GitLab Push Event)
curl -sS -X POST "https://flux-webhook.corp.internal/hook/c8f2b3e8a71d4e0b5f12a3456789abcdef0123456789abcdef0123456789abcd" \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Token: 9f82c4e1a6b8d7e3f2c5a1b4d8e7f9a2b3c4d5e6f7a8b9c0" \
  -H "X-Gitlab-Event: Push Hook" \
  -d '{"ref":"refs/heads/main","after":"7a9c3b8f1e2d4c5a6b7e8f9a0b1c2d3e4f5a6b7c"}'
# → {"status":"reconciliation requested"}

# Проверка фиксации времени обработки в GitRepository
kubectl get gitrepository fleet-infra -n flux-system -o jsonpath='{.status.lastHandledReconcileAt}'
# → 2026-10-13T15:21:04.421Z
```

### 3. Регламентное управление рассылкой (Mute / Unmute)

При проведении плановых работ или массовых миграциях во избежание лавины сообщений рассылка приостанавливается декларативно либо через CLI:

```bash
# Приостановка отправки уведомлений
flux suspend alert critical-workload-alerts -n flux-system
# → ► suspending alert critical-workload-alerts in flux-system namespace
# → ✔ alert suspended

# Проверка флага приостановки
kubectl get alert critical-workload-alerts -n flux-system -o jsonpath='{.spec.suspend}'
# → true

# Возобновление отправки после завершения работ
flux resume alert critical-workload-alerts -n flux-system
# → ► resuming alert critical-workload-alerts in flux-system namespace
# → ✔ alert resumed
```

### 4. Ротация токенов и секретов вебхуков

Для ротации токена входящего вебхука без прерывания обслуживания:
1. Подготовьте новый секрет в Kubernetes с новым токеном.
2. Обновите поле `spec.secretRef.name` в манифесте `Receiver`.
3. Зафиксируйте новый путь из `.status.webhookPath` и добавьте его в настройках GitLab Webhooks.
4. После подтверждения поступления запросов удалите старый вебхук в GitLab.

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Методика диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Уведомления не приходят при успешных операциях** | В `Alert.spec.eventSeverity` задан уровень `error`, отсекающий статус `info` | Проверить манифест: `kubectl get alert <name> -n flux-system -o yaml` | Для информационных лент сменить значение на `eventSeverity: info`; для ошибок оставить `error`. |
| **HTTP 429 Too Many Requests в логах контроллера** | Превышение лимитов API мессенджера (Rate Limit: в Telegram ~30 сообщ/сек, в Slack burst limit) | В логах контроллера: `grep "429 Too Many Requests"` | 1. Настроить `exclusionList` для отсечения шума.<br>2. Разделить алерты по независимым каналам.<br>3. Выставить `spec.suspend: true` на время bulk-миграций. |
| **HTTP 401 Unauthorized / HTTP 403 Forbidden** | Истек срок действия вебхука, отозван токен бота или бот не добавлен в закрытый чат/канал | В логах контроллера: `grep "failed to send event"` | 1. Проверить права бота администратором в канале Telegram.<br>2. Перегенерировать вебхук/токен и обновить Secret.<br>3. Проверить корректность префикса chat ID (`-100...`). |
| **Receiver отвечает HTTP 404 Not Found** | URL вебхука в GitLab/CI не совпадает с SHA256-хэшем токена из Secret | Сравнить URL запроса с полем `.status.webhookPath` ресурса `Receiver` | Скопировать точный путь из `kubectl get receiver <name> -n flux-system -o jsonpath='{.status.webhookPath}'` в настройки вебхука GitLab. |
| **Receiver отвечает HTTP 403 Forbidden** | Не совпадает подпись HMAC (секретный токен в GitLab отличается от значения в Secret) | `kubectl logs deploy/notification-controller -n flux-system \| grep "signature validation failed"` | Убедиться, что токен в `X-Gitlab-Token` / `X-Hub-Signature-256` совпадает со значением в `Secret.stringData.token`. |
| **Сетевые таймауты i/o timeout к Telegram / Webhook** | Трафик блокируется корпоративным сетевым экраном дата-центра; нет маршрутизации в интернет | Проверить логи: `dial tcp ... i/o timeout` | 1. Настроить `proxySecretRef` в объекте `Provider`.<br>2. Проверить открытие egress-трафика в NetworkPolicy кластера. |
| **x509: certificate signed by unknown authority** | Внутренний сервер Mattermost / GitLab использует корпоративный CA, отсутствующий в доверенных | Ошибка в логах контроллера при отправке вебхука | Добавить корпоративный сертификат в `certSecretRef` объекта `Provider`. |
| **Объекты Alert/Provider не применяются после обновления Flux** | Использование устаревших версий CRD API (`v1beta1` или `v1beta2`, удаленных из состава контроллера) | Ошибка валидации Kubernetes API: `no matches for kind Provider in version .../v1beta1` | Выполнить команду `flux migrate`, автоматически обновляющую `apiVersion` до `notification.toolkit.fluxcd.io/v1beta3`. |
| **Лавина сообщений при Flapping (CrashLoopBackOff)** | При циклическом падении пода контроллер шлет алерт на каждый рестарт | Анализ частоты сообщений в канале связи | Добавить фильтр по паттерну в `exclusionList` либо повысить порог ожидания стабильности в HelmRelease (`spec.timeout` / `spec.rollback`). |

---

## Мониторинг системы уведомлений

Сбой в работе контроллера уведомлений создает эффект «молчаливого инцидента» (Silent Failure): сбои приложений не доходят до дежурных. Необходим непрерывный мониторинг состояния самого контроллера.

### Ключевые метрики Prometheus

`notification-controller` экспортирует метрики на порту `:8080` (эндпоинт `/metrics`):

- `gotk_reconcile_condition{kind="Receiver", type="Ready", status="True|False"}` — готовность входящих вебхуков.
- `gotk_suspend_status{kind="Alert"}` — флаг приостановки отправки уведомлений (защита от забытого `suspend: true`).
- `event_server_events_total` — счетчик входящих событий от других контроллеров.
- `event_server_dispatch_duration_seconds` — гистограмма времени доставки сообщений провайдерам.
- `event_server_dispatch_errors_total` — счетчик ошибок доставки во внешние сервисы.

### Правила PrometheusRule для обнаружения деградации

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gitops-notifications-monitoring
  namespace: flux-system
  labels:
    role: alert-rules
spec:
  groups:
    - name: gitops-notification-controller.rules
      rules:
        # Алерт: Сбой реконсиляции объектов Receiver
        - alert: GitOpsReceiverNotReady
          expr: gotk_reconcile_condition{kind="Receiver", status="False", type="Ready"} == 1
          for: 10m
          labels:
            severity: warning
            team: sre
          annotations:
            summary: "Receiver {{ $labels.name }} в namespace {{ $labels.namespace }} не готов"
            description: "Входящий вебхук {{ $labels.name }} недоступен более 10 минут. Автоматическая реконсиляция по push-событиям не работает."

        # Алерт: Оповещения долгое время находятся в режиме suspend
        - alert: GitOpsAlertsSuspendedTooLong
          expr: gotk_suspend_status{kind="Alert"} == 1
          for: 4h
          labels:
            severity: warning
            team: sre
          annotations:
            summary: "Алерт {{ $labels.name }} приостановлен более 4 часов"
            description: "Объект Alert {{ $labels.name }} находится в статусе suspend: true. Возможна потеря сигналов об авариях после регламентных работ."

        # Алерт: Рост числа ошибок доставки уведомлений
        - alert: GitOpsNotificationDeliveryFailures
          expr: rate(event_server_dispatch_errors_total[5m]) > 0.1
          for: 5m
          labels:
            severity: critical
            team: sre
          annotations:
            summary: "Высокая частота ошибок доставки уведомлений GitOps"
            description: "Контроллер уведомлений фиксирует сбои при отправке сообщений внешним провайдерам (rate > 0.1 ош/сек)."
```

---

## Лучшие практики

### 1. Безопасность и управление секретами
- **Никогда не коммитьте токены в открытом виде**: Токены мессенджеров, пароли прокси и HMAC-ключи должны шифроваться в Git через [SOPS / Sealed Secrets](./secrets_encryption.md) либо доставляться через External Secrets Operator из HashiCorp Vault.
- **Обязательная валидация HMAC / OIDC для Receiver**: Никогда не публикуйте входящие вебхуки без секретного токена. Неавторизованный эндпоинт открывает возможность DoS-атаки на API-сервер Kubernetes путем непрерывной инициализации реконсиляции.
- **Сетевая изоляция (NetworkPolicy)**: Ограничивайте доступ к эндпоинту Receiver на уровне Kubernetes NetworkPolicy, разрешая входящий трафик только с IP-адресов корпоративных Ingress-контроллеров или внутренних подсетей GitLab.

### 2. Организация каналов и борьба с шумом
- **Трехуровневая модель каналов (Channel Tiering)**:
  - **Tier 1 (Incident / Pager)**: Только `eventSeverity: error` от критических сервисов (`production`). Включены звуковые пуш-уведомления дежурной смены.
  - **Tier 2 (Engineering Updates)**: События `error` и ключевые `info` из `staging`/`dev` контуров.
  - **Tier 3 (Audit Feed / Silent)**: Все события `info` (успешные реконсиляции, обновления образов). Без звука, с настроенной автоочисткой истории через 30 дней.
- **Структурированное обогащение (`eventMetadata`)**: Всегда указывайте имя кластера (`cluster`), площадку/ЦОД (`dc`), контур (`env`) и ссылку на регламент реагирования (`runbook`). Без этих данных алерт в общем канале дезориентирует инженера.

### 3. Отказоустойчивость в On-Premise инфраструктуре
- **Локальные приемники**: Используйте self-hosted Mattermost или локальные брокеры NATS вместо облачных сервисов для исключения влияния внешних сетевых сбоев.
- **Настройка Egress Proxy**: Все внешние вызовы (Telegram API) должны быть строго централизованы через корпоративный прокси с авторизацией и аудитом.
- **Мониторинг Dead Man's Switch**: Настройте периодическую генерацию тестового события (например, раз в сутки) для валидации сквозной цепочки доставки.

### 4. Регламент очистки тестовых ресурсов

Для удаления объектов, созданных в рамках практических сценариев:

```bash
# 1. Удаление ресурсов Flux Notification
kubectl delete alert critical-workload-alerts audit-feed-alerts stream-all-to-bus -n flux-system
# → alert.notification.toolkit.fluxcd.io "critical-workload-alerts" deleted
# → alert.notification.toolkit.fluxcd.io "audit-feed-alerts" deleted
# → alert.notification.toolkit.fluxcd.io "stream-all-to-bus" deleted

kubectl delete provider mattermost-provider telegram-provider corp-secured-provider nats-event-bus -n flux-system
# → provider.notification.toolkit.fluxcd.io "mattermost-provider" deleted
# → provider.notification.toolkit.fluxcd.io "telegram-provider" deleted
# → provider.notification.toolkit.fluxcd.io "corp-secured-provider" deleted
# → provider.notification.toolkit.fluxcd.io "nats-event-bus" deleted

kubectl delete receiver gitlab-receiver cdevents-pipeline-receiver -n flux-system
# → receiver.notification.toolkit.fluxcd.io "gitlab-receiver" deleted
# → receiver.notification.toolkit.fluxcd.io "cdevents-pipeline-receiver" deleted

# 2. Удаление секретов и Ingress
kubectl delete secret mattermost-webhook-url telegram-bot-token gitlab-webhook-secret corp-proxy-credentials internal-root-ca nats-cluster-auth -n flux-system
# → secret "mattermost-webhook-url" deleted
# → secret "telegram-bot-token" deleted
# → secret "gitlab-webhook-secret" deleted
# → secret "corp-proxy-credentials" deleted
# → secret "internal-root-ca" deleted
# → secret "nats-cluster-auth" deleted

kubectl delete ingress flux-receiver-ingress -n flux-system
# → ingress.networking.k8s.io "flux-receiver-ingress" deleted
```

---

## Дополнительная информация

**Связанные документы в базе знаний:**
- [Flux: Обзор и Ключевые Концепции](./flux.md) — общая архитектура GitOps Toolkit и жизненный цикл контроллеров.
- [ArgoCD Notifications: Настройка уведомлений](./ArgoCD/argocd_notifications.md) — единый источник истины (SSoT) по настройке триггеров, шаблонов и сервисов в Argo CD.
- [GitOps: Управление секретами и шифрование](./secrets_encryption.md) — безопасное хранение учетных данных вебхуков и токенов в Git (SOPS, Sealed Secrets).
- [Аудит событий и логирование в GitOps](./Concepts/audit_logs.md) — экспорт событий реконсиляции в централизованные системы аудита и SIEM.
- [DORA-метрики в GitOps](./Concepts/dora_metrics_gitops.md) — расчет метрик частоты развертываний и MTTR на основе потоков событий.
- [Интеграция Grafana с Telegram](../Grafana/alerting/telegram-integration.md) — примеры настройки контактных точек и шаблонов сообщений для Telegram Bot API.

**Официальная документация:**
- [Flux Notification Controller Documentation](https://fluxcd.io/flux/components/notification/)
- [Argo CD Notifications Documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- [CDEvents Specification (Continuous Delivery Foundation)](https://cdevents.dev/)
