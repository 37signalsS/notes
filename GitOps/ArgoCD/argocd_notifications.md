# ArgoCD Notifications — настройка уведомлений

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Статус архитектуры:** Контроллер уведомлений входит в состав стандартной поставки Argo CD (манифесты `install.yaml` и `ha/install.yaml`) и функционирует как выделенный Kubernetes Deployment (`argocd-notifications-controller`). Исторически (до версии Argo CD v2.3) компонент развивался в отдельном репозитории `argoproj-labs/argocd-notifications`, после чего был перенесён в ядро проекта (core). В современных версиях v3.x контроллер сохраняет архитектуру независимого процесса с собственным циклом реконсиляции, пулом воркеров и HTTP-сервером метрик Prometheus.

ArgoCD Notifications — специализированный контроллер, непрерывно отслеживающий жизненный цикл ресурсов `Application` и `AppProject` в кластере Kubernetes (события синхронизации, изменения статуса здоровья, фазы выполнения операций) и рассылающий структурированные сообщения во внешние каналы связи: Telegram, корпоративный Email (SMTP), Mattermost, Slack, локальные системы Webhook (Prometheus Alertmanager, оркестраторы автоматизации), SRE-платформы дежурств (PagerDuty, Opsgenie, Grafana OnCall) и системы контроля версий (GitLab / GitHub Commit Status API).

---

## Определения

- **ArgoCD Notifications Controller (`argocd-notifications-controller`)** — контроллер Kubernetes, работающий в пространстве имён `argocd`, отвечающий за чтение подписок, вычисление условий триггеров, рендеринг Go-шаблонов и диспетчеризацию сообщений.
- **Триггер (Trigger)** — декларативное логическое условие на базе языка выражений `antonmedv/expr`, определяющее момент отправки уведомления и связывающее событие с шаблонами сообщений.
- **`oncePer`** — директива дедупликации внутри триггера, гарантирующая отправку уведомления ровно один раз для уникального значения указанного поля (например, хэша коммита `sync.revision`).
- **Шаблон (Template)** — Go-шаблон (`text/template` / `html/template` с функциями Sprig и хелперами Argo CD), формирующий тело, тему, вложения и заголовки сообщения с подстановкой атрибутов приложения.
- **Сервис доставки (Service)** — адаптер подключения к внешней транспортной системе (Telegram Bot API, SMTP-сервер, HTTP-вебхук, Slack API), содержащий базовый URL и ссылки на секреты.
- **Получатель (Recipient)** — адрес назначения сообщения в формате `<service>:<destination>` (например, `telegram:-1001234567890`, `email:sre-team@corp.local`) либо `<service>.<name>:<destination>` для именованных сервисов.
- **Подписка (Subscription)** — декларативная связь триггера, приложения и получателя, настраиваемая через аннотации `Application` / `AppProject` или глобальный список `subscriptions` в ConfigMap.
- **Глобальные подписки (System-level subscriptions)** — централизованные правила рассылки в ConfigMap `argocd-notifications-cm`, применяемые ко всем приложениям кластера по селекторам меток (`selector`).
- **Самообслуживание (Self-service notifications)** — мультитенантный режим, позволяющий командам разработки настраивать собственные локальные триггеры, шаблоны и сервисы в namespace своих приложений без прав администратора в namespace `argocd`.
- **Контекст (Context)** — глобальная карта переменных типа «ключ-значение» (`context` в ConfigMap), доступная во всех шаблонах сообщений (например, базовый URL инстанса Argo CD, имя кластера, дата-центр).
- **Каталог уведомлений (Catalog)** — официальная библиотека готовых типовых триггеров и шаблонов сообщений, устанавливаемая поверх базовой конфигурации.
- **Кэш дедупликации (Dedup State)** — служебные аннотации ресурса `Application` (`notified.notifications.argoproj.io`), в которых контроллер фиксирует факт отправки уведомлений для защиты от повторных срабатываний при циклическом изменении состояний (flapping).

---

## Архитектура и принцип работы

### Компоненты системы

Контроллер функционирует независимо от `argocd-application-controller` и взаимодействует с кластером и внешними сервисами по следующей схеме:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Kubernetes Cluster (Namespace: argocd)                                │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  ┌───────────────────────┐                 ┌────────────────────────┐  │
│  │ Application &         │                 │ argocd-cmd-params-cm   │  │
│  │ AppProject CRs        │                 │ (Параметры контроллера)│  │
│  └───────────┬───────────┘                 └───────────┬────────────┘  │
│              │ Watch Events                            │ Env / Flags   │
│              ▼                                         ▼               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │             argocd-notifications-controller (Deployment)         │  │
│  │                                                                  │  │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │  │
│  │  │ Subscription    │  │ Trigger Engine   │  │ Template Engine │  │  │
│  │  │ Evaluator       │─▶│ (antonmedv/expr) │─▶│ (Go / Sprig)    │  │  │
│  │  └─────────────────┘  └──────────────────┘  └─────────────────┘  │  │
│  │           │                     │                     │          │  │
│  │           │ Metrics (:9001)     │ Dedup State Check   │ Delivery │  │
│  └───────────┼─────────────────────┼─────────────────────┼──────────┘  │
│              │                     │                     │             │
│              ▼                     ▼                     │             │
│  ┌───────────────────────┐  ┌──────────────┐             │             │
│  │ argocd-notif-cm       │  │ argocd-notif │             │             │
│  │ (Triggers, Templates, │  │ -secret      │             │             │
│  │  Services, Context)   │  │ (Токены, API)│             │             │
│  └───────────────────────┘  └──────────────┘             │             │
│                                                          │             │
└──────────────────────────────────────────────────────────┼─────────────┘
                                                           │
                                                           ▼ Outbound HTTP/TLS
                               ┌─────────────────────────────────────────┐
                               │ On-Premise & Corporate External Systems │
                               ├─────────────────────────────────────────┤
                               │ • Telegram Bot API                      │
                               │ • Corporate SMTP / Postfix              │
                               │ • Mattermost / Rocket.Chat / Slack      │
                               │ • Prometheus Alertmanager Webhook       │
                               │ • SRE On-Call (PagerDuty / Opsgenie)    │
                               │ • GitLab / GitHub Commit Status API     │
                               └─────────────────────────────────────────┘
```

### Конфигурационные ресурсы

| Ресурс | Роль в системе | Размещаемые параметры |
| :--- | :--- | :--- |
| `argocd-notifications-cm` | Декларативная конфигурация логики | Определения сервисов (`service.*`), триггеров (`trigger.*`), шаблонов (`template.*`), глобальных подписок (`subscriptions`), триггеров по умолчанию (`defaultTriggers`) и глобального контекста (`context`). |
| `argocd-notifications-secret` | Защищённое хранилище учётных данных | API-токены ботов, пароли SMTP, закрытые ключи (private keys), секретные URL вебхуков. Ссылки из ConfigMap оформляются через префикс `$<key-name>`. |
| `argocd-cmd-params-cm` | Общесистемные флаги демона | Конкурентность воркеров (`notificationscontroller.processors.count`), уровень логирования (`notificationscontroller.log.level`), активация мультитенантности (`notificationscontroller.selfservice.enabled`). |

### Жизненный цикл обработки события

1. **Генерация события в K8s Informer:** При каждом изменении полей `.status` (фаза `operationState`, здоровье `health.status`, статус синхронизации `sync.status`) ресурса `Application` контроллер получает объект в очередь обработки.
2. **Сбор подписок:** Контроллер агрегирует подписки из двух источников:
   - Локальные аннотации `Application.metadata.annotations` (вид `notifications.argoproj.io/subscribe.<trigger>.<service>`).
   - Глобальные правила из секции `subscriptions` в `argocd-notifications-cm`, если метки приложения удовлетворяют `selector`.
3. **Вычисление предикатов триггеров:** Условие `when` проверяется с помощью интерпретатора `antonmedv/expr`. Для безопасного обращения к полям, которые могут отсутствовать до инициации операции, применяется оператор безопасной навигации `?.` (например, `app.status?.operationState.phase`).
4. **Проверка фильтра `oncePer`:** Если в триггере задано правило `oncePer`, вычисляется значение выражения (например, ревизия Git). Контроллер сравнивает его со значением, сохранённым в аннотации приложения. Если значение совпадает — событие отбрасывается как дубликат.
5. **Рендеринг шаблона:** Вызывается Go-шаблонизатор, в контекст которого передаются объекты `.app`, `.appProject`, `.context`, `.serviceType`, `.recipient`, а также защищённый объект `.secrets` (при условии, что self-service выключен).
6. **Фиксация состояния дедупликации:** Перед фактической отправкой идентификатор события и значение `oncePer` записываются в аннотацию ресурса `Application` через API Kubernetes.
7. **Доставка во внешний канал:** Воркер контроллера выполняет исходящий сетевой запрос к внешнему API с экспортом времени выполнения и статуса в метрики Prometheus (`argocd_notifications_deliveries_total`).

---

## Предварительные требования

1. **Kubernetes:** Версия v1.28–v1.32+ (проверено на bare-metal и on-premise кластерах).
2. **Argo CD:** Версия v3.4+ (актуальная ветка v3.5.x, контроллер развёрнут как Deployment `argocd-notifications-controller`).
3. **Сетевая связность (Egress):** Узлы кластера или поды в namespace `argocd` должны иметь доступ по протоколам HTTP/HTTPS/SMTP к целевым сервисам (Telegram API `api.telegram.org:443`, корпоративный SMTP `:25/:465/:587`, внутренний Alertmanager `:9093`, корпоративный чат-сервер).
4. **Инструменты администрирования:** Утилиты `kubectl` и `argocd` CLI с правами кластерного администратора.

---

## Установка и развёртывание

### 1. Проверка базового Deployment

В стандартных манифестах Argo CD контроллер уведомлений уже присутствует. Проверьте его статус:

```bash
kubectl get deployment argocd-notifications-controller -n argocd
# → NAME                            READY   UP-TO-DATE   AVAILABLE   AGE
# → argocd-notifications-controller 1/1     1            1           5d
```

### 2. Установка официального каталога триггеров и шаблонов

Каталог содержит проверенные шаблоны (`template.*`) и условия (`trigger.*`) для всех базовых сценариев жизненного цикла GitOps:

```bash
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/notifications_catalog/install.yaml
# → configmap/argocd-notifications-cm serverside-applied
```

Каталог наполняет ConfigMap следующими стандартными триггерами:
- `on-created` — создание нового приложения;
- `on-deleted` — инициация удаления приложения;
- `on-deployed` — успешный переход в Healthy после синхронизации;
- `on-health-degraded` — деградация здоровья приложения (CrashLoopBackOff, Unhealthy поды);
- `on-sync-running` — начало процесса синхронизации;
- `on-sync-succeeded` — успешное применение манифестов;
- `on-sync-failed` — сбой синхронизации (ошибки валидации манифестов, конфликты CRD);
- `on-sync-status-unknown` — потеря связи контроллера с состоянием ресурсов.

---

## Конфигурация ядра системы

### Структура `argocd-notifications-cm`

Все настройки диспетчеризации, шаблонов и каналов группируются в секции `data` ConfigMap:

| Ключ ConfigMap | Формат | Назначение |
| :--- | :--- | :--- |
| `service.<type>` | YAML | Параметры базового сервиса доставки (`telegram`, `email`, `slack`, `webhook` и т. д.). |
| `service.<type>.<name>` | YAML | Именованный сервис для разделения сред (например, `service.slack.prod`, `service.webhook.alertmanager`). |
| `trigger.<name>` | YAML-список | Логические условия `when`, целевые шаблоны `send` и ключ дедупликации `oncePer`. |
| `template.<name>` | YAML | Структура сообщения: общее поле `message` или специфичные секции (`email`, `slack`, `webhook`). |
| `context` | YAML map | Глобальные константы для подстановки в шаблоны (`argocdUrl`, `environment`, `cluster`). |
| `defaultTriggers` | YAML-список | Триггеры, активируемые по умолчанию, если в аннотации указан только получатель без имени триггера. |
| `defaultTriggers.<service>` | YAML-список | Триггеры по умолчанию для конкретного типа сервиса. |
| `subscriptions` | YAML-список | Централизованные подписки с фильтрацией по меткам приложений (`selector`). |

### Переменные и встроенные функции шаблонов

Внутри Go-шаблона доступны следующие корневые объекты:

| Переменная | Тип данных | Содержимое |
| :--- | :--- | :--- |
| `.app` | `map / v1alpha1.Application` | Полное описание ресурса: `.app.metadata.name`, `.app.spec.source.repoURL`, `.app.status.sync.status`, `.app.status.health.status`. |
| `.appProject` | `map / v1alpha1.AppProject` | Проект приложения: `.appProject.metadata.name`, `.appProject.spec.description`, `.appProject.spec.roles`. |
| `.context` | `map[string]string` | Пользовательские параметры из секции `context` в ConfigMap. |
| `.secrets` | `map[string]string` | Данные из `argocd-notifications-secret` (доступны, если self-service **отключён**). |
| `.serviceType` | `string` | Имя используемого протокола доставки (`telegram`, `slack`, `email`, `webhook`). |
| `.recipient` | `string` | Адрес получателя сообщения. |

**Встроенные функции расширения:**

| Функция | Назначение | Пример использования |
| :--- | :--- | :--- |
| `.time.Now()` | Возвращает текущее время (`time.Time`) | `{{.time.Now}}` |
| `.time.Parse(str)` | Разбор даты по стандарту RFC3339 | `{{call .time.Parse .app.status.operationState.startedAt}}` |
| `.time.Local()` | Приведение к локальной таймзоне контейнера | `{{(call .time.Parse .app.status.operationState.startedAt).Local.Format "2006-01-02 15:04:05"}}` |
| `.strings.ToUpper(s)` | Перевод строки в верхний регистр | `{{call .strings.ToUpper .app.status.sync.status}}` |
| `.strings.ToLower(s)` | Перевод строки в нижний регистр | `{{call .strings.ToLower .app.status.health.status}}` |
| `.strings.ReplaceAll(s, old, new)` | Замена подстроки | `{{call .strings.ReplaceAll .app.spec.source.path "/" "-"}}` |
| `.sync.GetInfoItem(app, name)` | Извлечение параметра `info` операции | `{{call .sync.GetInfoItem .app "commitUrl"}}` |
| `.repo.FullNameByRepoURL(url)` | Преобразование Git URL в вид `owner/repo` | `{{call .repo.FullNameByRepoURL .app.spec.source.repoURL}}` |
| `.repo.RepoURLToHTTPS(url)` | Конвертация SSH Git URL в HTTPS-ссылку | `{{call .repo.RepoURLToHTTPS .app.spec.source.repoURL}}` |
| `.repo.QueryEscape(str)` | Экранирование спецсимволов для URL | `{{call .repo.QueryEscape (call .repo.FullNameByRepoURL .app.spec.source.repoURL)}}` |
| `.repo.GetCommitMetadata(sha)` | Получение данных коммита из репозитория | `{{(call .repo.GetCommitMetadata .app.status.sync.revision).Author}}` |
| `.repo.GetAppDetails()` | Извлечение параметров Helm/Kustomize | `{{(call .repo.GetAppDetails).Type}}` |

### Поддерживаемые транспортные сервисы (On-Premise / SRE стек)

Контроллер поддерживает широкий набор интеграций без привлечения проприетарных облачных шин:

| Сервис | Ключ сервиса | Механизм взаимодействия | Основные параметры подключения |
| :--- | :--- | :--- | :--- |
| **Telegram** | `service.telegram` | Telegram Bot API | `token` (токен бота от @BotFather). |
| **Email (SMTP)** | `service.email` | Протокол SMTP / STARTTLS | `host`, `port`, `from`, `username`, `password`, `insecure`. |
| **Mattermost** | `service.mattermost` | Входящий HTTP Incoming Webhook | `apiUrl`, `insecure`. |
| **Rocket.Chat** | `service.rocketchat` | Входящий HTTP Incoming Webhook | `email`, `password` или webhook URL. |
| **Slack** | `service.slack` | Slack Web API / Webhook | `token`, `signingSecret`. |
| **Webhook** | `service.webhook` | Произвольный HTTP/HTTPS POST-запрос | `url`, `headers`, `basicAuth`, `clientCert`. |
| **Alertmanager** | `service.alertmanager` | Prometheus Alertmanager API | `url`, базовая аутентификация или TLS. |
| **Grafana** | `service.grafana` | Grafana Incident / OnCall API | `url`, `apiToken`. |
| **PagerDuty** | `service.pagerdutyv2` | Events API v2 | `serviceKeys` (маппинг ключей интеграции). |
| **Opsgenie** | `service.opsgenie` | Opsgenie Alert API | `apiUrl`, `appKey`. |
| **GitHub** | `service.github` | GitHub Commit Status API | `appID`, `installationID`, `privateKey`. |
| **GitLab** | `service.webhook.gitlab` | GitLab Commit Status API | `url`, `headers` (Private-Token). |
| **NATS** | `service.nats` | On-Premise брокер сообщений | `url`, `subject`, учётные данные. |
| **Console** | `service.console` | Вывод в STDOUT | Отладка локально и через CLI. |

### Системные параметры контроллера (`argocd-cmd-params-cm`)

Параметры контроллера задаются централизованно через ConfigMap `argocd-cmd-params-cm`, исключая ручную модификацию Deployment:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Уровень детализации логов: debug | info | warn | error
  notificationscontroller.log.level: "info"
  # Формат логов: json | text
  notificationscontroller.log.format: "json"
  # Количество параллельных воркеров обработки событий (по умолчанию 1)
  notificationscontroller.processors.count: "4"
  # Активация режима самообслуживания (мультитенантность)
  notificationscontroller.selfservice.enabled: "false"
  # Список пространств имён, где контроллер отслеживает приложения
  application.namespaces: "argocd, tenant-team-a, tenant-team-b"
```

При изменении параметров перезапустите контроллер:

```bash
kubectl rollout restart deployment argocd-notifications-controller -n argocd
# → deployment.apps/argocd-notifications-controller restarted
```

---

## Настройка сервисов доставки

Все секретные токены и пароли размещаются в `argocd-notifications-secret`, а их имена с префиксом `$` передаются в `argocd-notifications-cm`.

### 1. Telegram

```bash
# Создание или обновление ключа в Secret
kubectl patch secret argocd-notifications-secret -n argocd --type merge -p \
  '{"stringData": {"telegram-token": "123456789:AAF_example_token_from_botfather"}}'
# → secret/argocd-notifications-secret patched
```

Конфигурация в `argocd-notifications-cm`:

```yaml
data:
  service.telegram: |
    token: $telegram-token
```

Подписка приложения (ID чата или канала со знаком минус):

```yaml
metadata:
  annotations:
    notifications.argoproj.io/subscribe.on-sync-failed.telegram: "-1001987654321"
    notifications.argoproj.io/subscribe.on-health-degraded.telegram: "-1001987654321"
```

### 2. Корпоративный Email (SMTP)

```bash
kubectl patch secret argocd-notifications-secret -n argocd --type merge -p \
  '{"stringData": {"smtp-user": "argocd-bot@corp.local", "smtp-pass": "SecretMailPassw0rd!"}}'
# → secret/argocd-notifications-secret patched
```

Конфигурация в `argocd-notifications-cm`:

```yaml
data:
  service.email: |
    host: mail.corp.local
    port: 587
    from: argocd-notifications@corp.local
    username: $smtp-user
    password: $smtp-pass
    insecure: false
```

### 3. Mattermost / Slack

Для Mattermost и Slack используется идентичный формат payload:

```bash
kubectl patch secret argocd-notifications-secret -n argocd --type merge -p \
  '{"stringData": {"mattermost-webhook": "https://mattermost.corp.local/hooks/xxxxxx5678"}}'
# → secret/argocd-notifications-secret patched
```

Конфигурация в `argocd-notifications-cm`:

```yaml
data:
  service.mattermost: |
    apiUrl: $mattermost-webhook
```

### 4. Webhook для Prometheus Alertmanager

Позволяет транслировать аварии развёртывания в общий мониторинговый пайплайн SRE:

```yaml
data:
  service.webhook.alertmanager: |
    url: http://alertmanager-operated.monitoring.svc.cluster.local:9093/api/v2/alerts
    headers:
      - name: Content-Type
        value: application/json
```

---

## Операции и команды управления (CLI)

Управление и отладка уведомлений выполняются через бинарник `argocd` с подкомандой `admin notifications`. Для работы требуются права администратора кластера (`kubectl context`).

### Справочник команд CLI

| Команда | Назначение | Ключевые флаги |
| :--- | :--- | :--- |
| `argocd admin notifications trigger get` | Получение списка всех триггеров | `-o yaml`, `-o json` |
| `argocd admin notifications trigger run <trigger> <app>` | Оценка условий триггера для приложения | `--config-map <path>`, `--secret <path>` |
| `argocd admin notifications template get` | Просмотр списка шаблонов | `-o yaml` |
| `argocd admin notifications template notify <template> <app>` | Генерация и тестовая отправка сообщения | `--recipient <service:dest>` |

### Примеры практической работы

#### 1. Проверка списка активных триггеров

```bash
argocd admin notifications trigger get
# → NAME                   CONDITION
# → on-created             "true"
# → on-deleted             app.metadata.deletionTimestamp != nil
# → on-deployed            app.status?.operationState.phase in ['Succeeded']
# → on-health-degraded     app.status.health.status == 'Degraded'
# → on-sync-failed         app.status?.operationState.phase in ['Error', 'Failed']
# → on-sync-running        app.status?.operationState.phase in ['Running']
# → on-sync-status-unknown app.status.sync.status == 'Unknown'
# → on-sync-succeeded      app.status?.operationState.phase in ['Succeeded']
```

#### 2. Тестирование условия триггера для конкретного приложения

Позволяет мгновенно понять, сработает ли условие прямо сейчас, без изменения состояния в кластере:

```bash
argocd admin notifications trigger run on-sync-failed my-backend-service
# → TRIGGER        CONDITION                                             RESULT
# → on-sync-failed app.status?.operationState.phase in ['Error','Failed'] false
```

#### 3. Тестирование шаблона с выводом в консоль (Dry-Run)

Рендерит шаблон по реальным метаданным приложения в терминал без отправки в сеть:

```bash
argocd admin notifications template notify app-sync-failed my-backend-service
# → Recipient: console:stdout
# → Message:
# → Application my-backend-service sync failed at 2026-10-12T14:15:00Z.
# → Error details: Deployment.apps "backend" is invalid: spec.replicas: Invalid value: -1
```

#### 4. Отправка тестового сообщения реальному получателю

```bash
argocd admin notifications template notify app-sync-failed my-backend-service \
  --recipient telegram:-1001987654321
# → Notification successfully sent to telegram:-1001987654321
```

#### 5. Офлайн-валидация конфигурации без доступа к кластеру

Команда позволяет проверить синтаксис локального файла `my-notif-cm.yaml` перед коммитом в Git:

```bash
argocd admin notifications trigger run on-sync-failed ./manifests/app.yaml \
  --config-map ./manifests/argocd-notifications-cm.yaml \
  --secret :empty
# → TRIGGER        CONDITION                                             RESULT
# → on-sync-failed app.status?.operationState.phase in ['Error','Failed'] true
```

---

## Практические производственные сценарии

### Сценарий 1: Информативный Telegram-алерт с кнопками и метаданными коммита

**Задача:** При падении синхронизации или деградации подов присылать в дежурный чат Telegram сообщение с автором коммита, веткой, описанием ошибки и ссылкой на интерфейс Argo CD.

1. **Регистрация шаблона в `argocd-notifications-cm`:**

```yaml
data:
  context: |
    argocdUrl: https://argocd.corp.local
    clusterName: k8s-core-prod

  template.telegram-app-incident: |
    message: |
      🚨 <b>[Argo CD] Инцидент с приложением: {{.app.metadata.name}}</b>
      <b>Кластер:</b> {{.context.clusterName}}
      <b>Здоровье:</b> {{.app.status.health.status}}
      <b>Статус Sync:</b> {{.app.status.sync.status}}
      <b>Ревизия:</b> <code>{{.app.status.sync.revision}}</code>
      {{- if .app.status.operationState }}
      <b>Фаза операции:</b> {{.app.status.operationState.phase}}
      <b>Сообщение:</b> <code>{{.app.status.operationState.message}}</code>
      {{- end }}
      <b>Автор:</b> {{(call .repo.GetCommitMetadata .app.status.sync.revision).Author}}
      <b>Коммит:</b> {{(call .repo.GetCommitMetadata .app.status.sync.revision).Message}}
    telegram:
      format: HTML
      parseMode: HTML
      disableWebPagePreview: true
      replyMarkup: |
        {
          "inline_keyboard": [
            [
              {"text": "🔍 Открыть в Argo CD", "url": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"}
            ]
          ]
        }
```

2. **Связывание триггера и шаблона:**

```yaml
data:
  trigger.on-app-incident: |
    - when: app.status.health.status == 'Degraded' or (app.status?.operationState.phase in ['Error', 'Failed'])
      send: [telegram-app-incident]
      oncePer: app.status?.operationState.syncResult.revision
```

3. **Подписка приложения через аннотации:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-gateway
  namespace: argocd
  annotations:
    notifications.argoproj.io/subscribe.on-app-incident.telegram: "-1001234567890"
```

### Сценарий 2: Корпоративный HTML-отчёт на почту команды разработки

**Задача:** При успешном деплое новой версии отправлять на список рассылки команды структурированное письмо с историей изменений.

```yaml
data:
  template.email-deployment-report: |
    email:
      subject: "🚀 Успешный деплой: {{.app.metadata.name}} ({{.app.status.sync.revision}})"
      body: |
        <!DOCTYPE html>
        <html>
        <head><style>body{font-family:sans-serif;} table{border-collapse:collapse;width:100%;} td,th{border:1px solid #ddd;padding:8px;}</style></head>
        <body>
          <h2>Статус развёртывания сервиса {{.app.metadata.name}}</h2>
          <table>
            <tr><th>Параметр</th><th>Значение</th></tr>
            <tr><td>Окружение</td><td>{{.app.metadata.labels.env}}</td></tr>
            <tr><td>Target Namespace</td><td>{{.app.spec.destination.namespace}}</td></tr>
            <tr><td>Репозиторий</td><td>{{.app.spec.source.repoURL}}</td></tr>
            <tr><td>Ветка / Ревизия</td><td>{{.app.spec.source.targetRevision}} ({{.app.status.sync.revision}})</td></tr>
            <tr><td>Автор коммита</td><td>{{(call .repo.GetCommitMetadata .app.status.sync.revision).Author}}</td></tr>
          </table>
          <p><a href="{{.context.argocdUrl}}/applications/{{.app.metadata.name}}">Перейти в панель управления Argo CD</a></p>
        </body>
        </html>
```

### Сценарий 3: Маршрутизация через Webhook в локальный Prometheus Alertmanager

**Задача:** Превращать сбои деплоя в алерты Alertmanager для обработки дежурными SRE инженерами по единым правилам эскалации.

```yaml
data:
  template.alertmanager-alert: |
    webhook:
      alertmanager:
        method: POST
        body: |
          [
            {
              "labels": {
                "alertname": "ArgoCDApplicationDegraded",
                "application": "{{.app.metadata.name}}",
                "severity": "critical",
                "cluster": "{{.context.clusterName}}",
                "env": "{{.app.metadata.labels.env}}"
              },
              "annotations": {
                "summary": "Приложение {{.app.metadata.name}} находится в состоянии {{.app.status.health.status}}",
                "description": "Сбой синхронизации: {{.app.status?.operationState.message}}",
                "dashboard_url": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
              },
              "generatorURL": "{{.context.argocdUrl}}/applications/{{.app.metadata.name}}"
            }
          ]
```

### Сценарий 4: Глобальная матричная подписка для Production-окружений

**Задача:** Автоматически отправлять критические алерты со всех приложений с меткой `env: production` дежурным SRE в PagerDuty и Telegram без необходимости ручной расстановки аннотаций в каждом манифесте.

```yaml
data:
  subscriptions: |
    # Для всех приложений с env: production отправлять сбои в Telegram дежурных
    - recipients: [telegram:-1001987654321]
      triggers: [on-sync-failed, on-health-degraded]
      selector: env=production

    # Для критических сервисов дублировать вызов в SRE PagerDuty
    - recipients: [pagerdutyv2:sre-core-oncall]
      triggers: [on-sync-failed]
      selector: criticality=tier-1
```

### Сценарий 5: Режим самообслуживания (Self-Service) для мультитенантности

**Задача:** Команда разработчиков `team-analytics` ведёт свои манифесты `Application` в пространстве имён `team-analytics`. Они хотят подключить свой локальный Telegram-чат и кастомный шаблон, не обращаясь к администраторам платформы.

1. **Активация режима в `argocd-cmd-params-cm` (выполняет администратор):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  application.namespaces: "argocd, team-analytics"
  notificationscontroller.selfservice.enabled: "true"
```

2. **Создание локального ConfigMap тенантом (в namespace `team-analytics`):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: team-analytics
data:
  service.telegram: |
    token: $local-telegram-token

  template.analytics-alert: |
    message: |
      [Analytics Team] Приложение {{.app.metadata.name}} упало: {{.app.status.health.status}}
```

3. **Создание локального Secret тенантом:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-notifications-secret
  namespace: team-analytics
type: Opaque
stringData:
  local-telegram-token: "987654321:XYZ_tenant_token"
```

> **Важное ограничение безопасности:** При активации флага `--self-service-notification-enabled` глобальный доступ к объекту `.secrets` внутри шаблонов блокируется во избежание утечки секретов между тенантами.

---

## Диагностика и устранение неисправностей

### 1. Проверка состояния контроллера и логов

Логи контроллера в формате JSON предоставляют исчерпывающую информацию о вычислении триггеров и попытках сетевой доставки:

```bash
kubectl logs -n argocd deployment/argocd-notifications-controller --tail=100
# → {"level":"info","msg":"Processing app change: payment-gateway","time":"2026-10-12T14:20:00Z"}
# → {"level":"info","msg":"Trigger on-sync-failed evaluated to true for payment-gateway","time":"2026-10-12T14:20:01Z"}
# → {"level":"info","msg":"Sending notification telegram:-1001234567890 using template app-sync-failed","time":"2026-10-12T14:20:01Z"}
```

Если доставка завершилась сбоем, лог зафиксирует ошибку:

```bash
kubectl logs -n argocd deployment/argocd-notifications-controller | grep -i "failed to send"
# → {"level":"error","msg":"Failed to send notification to telegram: 400 Bad Request: can't parse entities: Unsupported start tag","time":"2026-10-12T14:20:02Z"}
```

### 2. Мониторинг Prometheus (Порт `:9001`)

Контроллер отдаёт метрики Prometheus на порту `9001` (путь `/metrics`).

**Ключевые метрики:**

| Метрика | Тип | Лейблы | Назначение |
| :--- | :--- | :--- | :--- |
| `argocd_notifications_deliveries_total` | Counter | `trigger`, `service`, `succeeded` (`"true"` / `"false"`) | Суммарное число попыток доставки уведомлений с разделением на успешные и сбойные. |
| `argocd_notifications_trigger_eval_total` | Counter | `name`, `triggered` (`"true"` / `"false"`) | Число проверок условий триггеров и фактов их срабатывания. |

Пример PrometheusRule для мониторинга здоровья подсистемы уведомлений:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-notifications-alerts
  namespace: argocd
spec:
  groups:
    - name: argocd-notifications
      rules:
        - alert: ArgoCDNotificationDeliveryFailed
          expr: |
            rate(argocd_notifications_deliveries_total{succeeded="false"}[5m]) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Сбой доставки уведомлений Argo CD в сервис {{ $labels.service }}"
            description: "Контроллер не может доставить сообщения по триггеру {{ $labels.trigger }}. Проверьте токены и доступность шлюза."
```

### 3. Диагностика кэша дедупликации (Dedup Cache)

Если уведомление не приходит повторно после исправления и нового сбоя, проверьте аннотации приложения:

```bash
kubectl get app payment-gateway -n argocd -o jsonpath='{.metadata.annotations}' | jq .
# → {
# →   "notifications.argoproj.io/subscribe.on-sync-failed.telegram": "-1001234567890",
# →   "notified.notifications.argoproj.io": "..."
# → }
```

Контроллер хранит состояние в аннотациях вида `notified.notifications.argoproj.io` или `NotificationProcessed`. Для принудительного сброса кэша дедупликации удалите служебную аннотацию:

```bash
kubectl patch app payment-gateway -n argocd --type=json \
  -p='[{"op": "remove", "path": "/metadata/annotations/notified.notifications.argoproj.io"}]'
# → application.argoproj.io/payment-gateway patched
```

---

## Таблица типичных ошибок и решений

| Ошибка / Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `config referenced '<key>', but key does not exist in secret` | В `argocd-notifications-secret` отсутствует ключ, указанный через `$<key>` в ConfigMap. | `kubectl get secret argocd-notifications-secret -n argocd -o jsonpath='{.data}' \| jq 'keys'` | Добавить недостающий ключ в Secret через `kubectl patch secret`. |
| `trigger with name '<name>' does not exist` | Подписка ссылается на триггер, который не объявлен в ConfigMap (каталог не применён). | `argocd admin notifications trigger get` | Применить манифест каталога `notifications_catalog/install.yaml` или объявить триггер в `argocd-notifications-cm`. |
| `cannot evaluate field operationState in type interface {}` (nil pointer) | В условии `when` триггера обратились к `app.status.operationState` без оператора `?.`. До начала операции поле равно `nil`. | Анализ тела условия триггера в ConfigMap. | Заменить обращение на безопасную навигацию: `app.status?.operationState.phase`. |
| HTTP `400 Bad Request: can't parse entities` (Telegram) | Неэкранированные спецсимволы в HTML/Markdown (например, `<` или `>` в тексте ошибки Go). | Логи контроллера (`msg="Failed to send notification"`). | Использовать HTML-форматирование с экранированием либо оборачивать сообщения об ошибках в теги `<code>`. |
| HTTP `401 Unauthorized` / `403 Forbidden` | Недействительный токен бота, отозванный вебхук или бот исключён из чата/канала. | Выполнить прямой тестовый запрос через `curl` с использованием токена. | Перевыпустить токен у провайдера, обновить Secret и добавить бота администратором канала. |
| HTTP `429 Too Many Requests` | Исчерпание лимитов внешнего API при массовой одновременной синхронизации (Rate Limiting). | Появление `429` в метриках `argocd_notifications_deliveries_total{succeeded="false"}`. | Добавить директиву `oncePer`, разделить потоки (не слать `info` в чат инцидентов), настроить батчинг. |
| Уведомления приходят повторно каждые несколько минут (Flapping) | Статус здоровья приложения колеблется между `Progressing` и `Degraded`, а в триггере нет `oncePer`. | `kubectl get app <name> -w` (наблюдение за сменой статусов). | Добавить в условие триггера поле `oncePer: app.status?.operationState.syncResult.revision`. |
| Переменная `{{.context.argocdUrl}}` пуста в сообщении | Секция `context` не сконфигурирована в `argocd-notifications-cm`. | Просмотр секции `data.context` в ConfigMap. | Прописать валидный URL в `argocd-notifications-cm` под ключом `context: "argocdUrl: https://..."`. |
| В шаблоне не работает обращение к `{{.secrets}}` | Включён флаг мультитенантности `self-service` в `argocd-cmd-params-cm`. | Проверить параметр `notificationscontroller.selfservice.enabled`. | В режиме self-service объект `.secrets` намеренно изолирован. Вынести учётные данные в настройки сервиса (`service.*`). |

---

## Рекомендации для инженеров (Best Practices)

### Борьба с информационным шумом (Alert Fatigue)

1. **Строгое разделение каналов по критичности:**
   - Канал дежурных SRE (Telegram / Mattermost / PagerDuty): только `on-sync-failed` и `on-health-degraded` для окружения `production`.
   - Информационный архивный канал: `on-deployed` и `on-created` для отслеживания аудита выпуска релизов.
2. **Обязательное использование `oncePer`:** Не создавайте триггеры без `oncePer`. При циклических падениях подов контроллер без `oncePer` заспамит чат десятками однотипных сообщений в минуту.
3. **Монорепозитории:** В монорепозиториях, где один коммит инициирует синхронизацию множества микросервисов, используйте `oncePer: app.status?.operationState.syncResult.revision` вместо общего `app.status.sync.revision`. Это исключит повторные ложные уведомления между приложениями.

### Безопасность и хранение секретов

1. **Никаких секретов в Git в открытом виде:** Конфигурация `argocd-notifications-cm` хранится в GitOps, но Secret `argocd-notifications-secret` должен синхронизироваться через External Secrets Operator (ESO), HashiCorp Vault или Sealed Secrets.
2. **Изоляция токенов по средам:** Создавайте независимые токены для staging и production окружений, используя именованные сервисы (`service.telegram.prod` и `service.telegram.dev`).
3. **Подпись Webhook-запросов (HMAC):** При интеграции с собственными микросервисами автоматизации передавайте в заголовках токен авторизации или подпись через `headers: [{name: "X-Auth-Token", value: "$webhook-token"}]`.

### Производительность и надёжность

1. **Масштабирование воркеров:** Для кластеров с числом приложений свыше 200 увеличьте количество параллельных обработчиков с 1 до 4–8 в `argocd-cmd-params-cm` (`notificationscontroller.processors.count: "4"`).
2. **Явная настройка таймзоны:** Задайте переменную окружения `TZ` в Deployment контроллера (например, `Europe/Moscow`), чтобы время в шаблонах соответствовало часовому поясу дежурной смены.
3. **Ресурсы контейнера:** Выделите контроллеру гарантированные ресурсы (Requests/Limits: `cpu: 100m / 500m`, `memory: 128Mi / 512Mi`), чтобы предотвратить OOMKilled при массовом получении событий во время перезапуска K8s API.

---

## Ограничения и граничные случаи

1. **Границы области видимости:** ArgoCD Notifications отслеживает состояние ресурсов **только на уровне Argo CD** (`Application` и `AppProject`). Контроллер не является заменой Prometheus/Alertmanager: он не оповещает о падении отдельных подов, нехватке памяти на нодах или HTTP-ошибках трафика, если они не привели к изменению статуса здоровья `Application`.
2. **Ограничение адресатов на сервис:** Аннотация `notifications.argoproj.io/subscribe.<trigger>.<service>` поддерживает указание только одного получателя на конкретный сервис. Для отправки одного и того же триггера в два разных Telegram-чата необходимо сконфигурировать именованный сервис (`service.telegram.sre` и `service.telegram.devs`).
3. **Конфликты при параллельных операциях:** Если аннотации приложения одновременно модифицируются через UI, CLI и GitOps, возможны конфликты оптимистичной блокировки Kubernetes. Для исключения конфликтов используйте Server-Side Apply или объявляйте подписки централизованно через секцию `subscriptions` в ConfigMap.
4. **Специфика Argo CD Image Updater:** Изменения тегов образов, производимые Image Updater через Git-коммиты, вызывают только события синхронизации (`sync`). События ручных операций (`operationState`) при этом не генерируются.

---

## Дополнительная информация

### См. также в базе знаний

- [Argo CD: Мультитенантность и изоляция](./argocd_multi_tenancy.md) — настройка `application.namespaces` и прав команд.
- [Argo CD: Установка и базовая настройка](./argocd_installation_and_setup.md) — компоненты ядра, порты метрик, профили HA.
- [Argo CD: AppProject и границы проектов](./argocd_appproject_deep.md) — ролевая модель и ограничения источников.
- [Argo CD: Модель доступа RBAC](./argocd_rbac_deep.md) — матрица привилегий и JWT-аутентификация.
- [Argo CD: Харденинг и безопасность](./argocd_security_hardening.md) — NetworkPolicies, mTLS и SecurityContext.
- [Argo CD: Аварийное восстановление](./argocd_disaster_recovery.md) — резервное копирование ConfigMap и Secret.
- [GitOps: Уведомления о статусе развёртываний](../gitops_notifications.md) — сравнение подходов Flux notification-controller и Argo CD.

### Официальные источники

- [Официальная документация Argo CD Notifications](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/)
- [Справочник триггеров (Triggers)](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/triggers/)
- [Справочник шаблонов (Templates)](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/templates/)
- [Встроенные функции шаблонов (Functions)](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/functions/)
- [Каталог шаблонов и триггеров (Catalog)](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/catalog/)
- [Мониторинг и метрики контроллера (Monitoring)](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/monitoring/)
