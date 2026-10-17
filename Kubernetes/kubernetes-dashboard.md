# Веб-интерфейсы Kubernetes: Dashboard, Headlamp и альтернативы

**Актуально для:** Kubernetes 1.30+ / Kubernetes Dashboard 7.14.x / Headlamp 0.46.x

## Определения

**Kubernetes Dashboard** — официальный веб-интерфейс общего назначения под эгидой Kubernetes SIG-UI. Предоставляет веб-панель для мониторинга и управления рабочими нагрузками (Deployments, StatefulSets, DaemonSets), сервисами, конфигурациями (ConfigMaps, Secrets) и состоянием узлов кластера. Начиная с версии v7.0.0, архитектура проекта полностью переработана из единого монолитного сервиса в микросервисную структуру с Kong API Gateway в качестве реверс-прокси и установкой через Helm-чарт.

**Headlamp** — современный расширяемый веб- и десктоп-интерфейс для Kubernetes с открытым исходным кодом, развиваемый в рамках CNCF Sandbox (проект Kubernetes SIGs). Архитектурно ориентирован на мультикластерное управление, расширяемость через плагины (TypeScript/JavaScript), нативную интеграцию с OIDC (Keycloak, Dex, Authentik) и работу строго в рамках RBAC подключенного пользователя без необходимости выдачи привилегированного ServiceAccount самому дашборду.

**Lens Desktop / FreeLens** — локальная графическая IDE для Kubernetes, работающая на рабочей станции инженера через локальный `kubeconfig`. Не требует обязательной установки серверных компонентов в кластер (за исключением опционального стека сбора метрик Prometheus).

**k9s** — высокопроизводительный терминальный интерфейс (TUI), работающий локально через `kubeconfig` и предназначенный для непрерывного мониторинга, мгновенной навигации и отладки ресурсов кластера без использования графического браузера.

---

## Архитектура и основные концепции

### Сравнение инструментов управления кластером

| Параметр | Headlamp (CNCF Sandbox) | Kubernetes Dashboard v7+ | FreeLens / Lens Desktop | k9s (TUI) |
| :--- | :--- | :--- | :--- | :--- |
| **Тип интерфейса** | Web UI / Desktop | Web UI | GUI (Desktop IDE) | Terminal (TUI) |
| **Среда развертывания** | In-cluster (Helm) / Local Desktop | In-cluster (Helm) | Local Workstation | Local Workstation / Bastion |
| **Мультикластерность** | Родная (переключение в UI) | Ограниченная (один кластер на инстанс) | Родная (каталог кластеров) | Быстрое переключение контекстов |
| **Аутентификация** | OIDC SSO, токен ServiceAccount | Токен ServiceAccount, OIDC, Kubeconfig | Локальный `kubeconfig` | Локальный `kubeconfig` |
| **Модель привилегий** | Проксирует права текущего пользователя | Проксирует токен текущего пользователя | Права контекста `kubeconfig` | Права контекста `kubeconfig` |
| **Архитектура в кластере** | Легковесный backend-proxy + SPA frontend | Микросервисы: Kong, Web, API, Auth, Scraper | Не требует (опционально Metrics Stack) | Не требует серверных компонентов |
| **Нагрузка на API-сервер** | Низкая (кеширование и WebSocket/SSE) | Средняя (фоновый опрос и metrics-scraper) | Средняя/Высокая при открытии многих вкладок | Минимальная (адресные watch-запросы) |
| **Расширяемость** | Плагины на JS/TS | Ограниченная (кастомизация настроек) | Расширения JavaScript/React | Алиасы, кастомные плагины (shell) |
| **Основное назначение** | Корпоративный портал, команды разработки и SRE | Базовый веб-доступ к standalone-кластеру | Полнофункциональная рабочая среда инженера | Экспресс-диагностика, траблшутинг в консоли |

### Архитектура Kubernetes Dashboard v7.x

В версиях v7.x архитектура была полностью переработана для повышения безопасности и изоляции компонентов:

```
[ Пользователь / Браузер ]
           │
           ▼ (HTTPS / 8443)
┌────────────────────────────────────────────────────────────────────────┐
│ Kubernetes Dashboard Namespace                                         │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐    │
│   │ Kong API Gateway (DB-less Proxy)                             │    │
│   │ Маршрутизация запросов, SSL-терминация, CSRF валидация       │    │
│   └───┬──────────────────────────┬───────────────────────────┬───┘    │
│       │                          │                           │        │
│       ▼ (/api)                   ▼ (/)                       ▼ (/auth)│
│   ┌──────────────┐       ┌──────────────┐            ┌──────────────┐ │
│   │ dashboard-api│       │ dashboard-web│            │dashboard-auth│ │
│   │ (Go backend) │       │ (Angular SPA)│            │(Аутентификац)│ │
│   └───┬──────────┘       └──────────────┘            └──────────────┘ │
│       │                                                               │
│       ▼ (Внутренние метрики)                                          │
│   ┌─────────────────────────┐                                         │
│   │dashboard-metrics-scraper│ ────► Опрос metrics-server кластера     │
│   └─────────────────────────┘                                         │
└───────┬────────────────────────────────────────────────────────────────┘
        │
        ▼ (Взаимодействие от имени переданного Bearer-токена)
[ Kubernetes API Server (kube-apiserver) ]
```

1. **Kong API Gateway:** Единая точка входа, работающая в DB-less режиме (конфигурация через ConfigMap `kong-dbless-config`). Обеспечивает внутреннюю маршрутизацию между микросервисами, проверку CSRF-токенов и управление сессионными cookies.
2. **dashboard-web:** Отдает скомпилированное Single Page Application (SPA).
3. **dashboard-api:** Обрабатывает REST-запросы к ресурсам кластера и транслирует их в вызовы `kube-apiserver`.
4. **dashboard-auth:** Валидирует токены аутентификации и управляет состоянием входа.
5. **dashboard-metrics-scraper:** Периодически опрашивает `metrics-server` и сохраняет временной срез данных CPU/Memory для отрисовки графиков в веб-интерфейсе.

### Архитектура и модель безопасности Headlamp

Headlamp спроектирован по модели **Zero Privileges for Dashboard ServiceAccount**:

```
[ Пользователь ] ──► [ IdP / Keycloak ] (OIDC аутентификация)
        │                       │
        │ (ID Token / JWT)      ▼
        ▼
[ Headlamp Ingress / Service ]
        │
        ▼
[ Headlamp Pod (Go Proxy + React SPA) ]
        │
        │ Передача оригинального Bearer Token пользователя
        ▼
[ Kubernetes API Server ] (Авторизация через встроенный RBAC)
```

- **Отсутствие админских прав у пода:** Сам под Headlamp использует ServiceAccount с минимальными правами (чтение версии кластера и проверка доступности неймспейсов). Все запросы к ресурсам выполняются строго от имени переданного токена пользователя (`Authorization: Bearer <token>`).
- **OIDC/SSO интеграция:** При включенном OIDC Headlamp перенаправляет пользователя на корпоративный IdP (Keycloak, Dex, Authentik). Полученный JWT ID Token пересылается в API Server. Если API Server настроен с параметрами `--oidc-issuer-url` и `--oidc-client-id`, авторизация происходит нативно через Kubernetes RBAC на основе ролей и групп пользователя.
- **Поддержка плагинов:** Headlamp динамически загружает JS/TS плагины из каталога или ConfigMap, что позволяет добавлять кастомные представления для операторов (Argo CD, cert-manager, Cilium, внешние системы хранения).

---

## Практические сценарии и установка

### Предварительные требования

- Кластер Kubernetes: версия 1.28+ (on-premise / bare-metal).
- Утилита `kubectl` с настроенным доступом администратора кластера.
- Установленный пакетный менеджер `helm` версии v3.12+.
- Работающий Ingress Controller (например, Ingress-NGINX) и cert-manager (для генерации TLS-сертификатов).

---

### Сценарий 1: Развертывание Kubernetes Dashboard v7.x через Helm

#### Шаг 1: Подключение репозитория и установка чарта

```bash
# Добавление официального Helm-репозитория
helm repo add kubernetes-dashboard https://kubernetes.github.io/dashboard/
helm repo update

# Проверка доступных версий
helm search repo kubernetes-dashboard/kubernetes-dashboard --versions | head -n 5
# → kubernetes-dashboard/kubernetes-dashboard  7.14.0  ...
```

Создайте конфигурационный файл `dashboard-values.yaml`:

```yaml
# dashboard-values.yaml
app:
  mode: 'dashboard'
  security:
    networkPolicy:
      enabled: true
      ingressDenyAll: false
    containerSecurityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsUser: 1001
      runAsGroup: 2001
      capabilities:
        drop: ["ALL"]
  settings:
    global:
      clusterName: "prod-baremetal"
      itemsPerPage: 20
      resourceAutoRefreshTimeInterval: 10
      hideAllNamespaces: false

# Настройка Ingress (опционально, если доступ нужен через общекластерный Ingress)
ingress:
  enabled: true
  ingressClassName: nginx
  hosts:
    - k8s-dashboard.internal.example.com
  useDefaultAnnotations: true
  tls:
    enabled: true
    secretName: k8s-dashboard-tls

# Отключение встроенного metrics-server, если он уже развернут в кластере
metrics-server:
  enabled: false

# Включение сборщика метрик для графиков
metricsScraper:
  enabled: true

# Шлюз Kong (входит в поставку чарта v7)
kong:
  enabled: true
  proxy:
    type: ClusterIP
    http:
      enabled: false
    tls:
      enabled: true
```

Выполните установку:

```bash
helm upgrade --install kubernetes-dashboard kubernetes-dashboard/kubernetes-dashboard \
  --namespace kubernetes-dashboard \
  --create-namespace \
  -f dashboard-values.yaml
# → Release "kubernetes-dashboard" has been upgraded. Happy Helming!
```

Проверьте запуск всех микросервисов:

```bash
kubectl -n kubernetes-dashboard get pods -o wide
# → kubernetes-dashboard-api-...                1/1     Running
# → kubernetes-dashboard-auth-...               1/1     Running
# → kubernetes-dashboard-kong-...               1/1     Running
# → kubernetes-dashboard-metrics-scraper-...    1/1     Running
# → kubernetes-dashboard-web-...                1/1     Running
```

#### Шаг 2: Создание сервисных аккаунтов и RBAC для доступа

Никогда не выдавайте права `cluster-admin` дефолтным сервисным аккаунтам. Создайте специализированные учетные записи:

##### Вариант А: Ограниченный администратор (Cluster Admin для DevOps/SRE)

```yaml
# dashboard-admin.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dashboard-admin
  namespace: kubernetes-dashboard
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dashboard-admin-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
  - kind: ServiceAccount
    name: dashboard-admin
    namespace: kubernetes-dashboard
```

##### Вариант Б: Read-Only доступ (Для дежурной смены / мониторинга)

```yaml
# dashboard-readonly.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dashboard-viewer
  namespace: kubernetes-dashboard
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: dashboard-viewer-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: view
subjects:
  - kind: ServiceAccount
    name: dashboard-viewer
    namespace: kubernetes-dashboard
```

Примените манифесты:

```bash
kubectl apply -f dashboard-admin.yaml
kubectl apply -f dashboard-readonly.yaml
```

#### Шаг 3: Генерация временного токена аутентификации

В Kubernetes 1.24+ статические токены в секретах отключены по умолчанию. Для входа генерируется короткоживущий токен через TokenRequest API:

```bash
# Генерация токена со сроком жизни 8 часов (для рабочего дня)
kubectl -n kubernetes-dashboard create token dashboard-admin --duration=8h
# → eyJhbGciOiJSUzI1NiIsImtpZCI6Ii4uLiJ9...
```

#### Шаг 4: Безопасный доступ через port-forward (без Ingress)

Если Dashboard не опубликован наружу через Ingress, доступ организуется через локальный туннель:

```bash
# Проброс порта к Kong API Gateway
kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard-kong-proxy 8443:443
# → Forwarding from 127.0.0.1:8443 -> 8443
```

Откройте в браузере `https://localhost:8443`, выберите вход по токену и вставьте сгенерированный Bearer-токен.

---

### Сценарий 2: Развертывание Headlamp (in-cluster) с корпоративным OIDC

Headlamp является предпочтительным решением для мультипользовательских сред благодаря бесшовной интеграции с IdP.

#### Шаг 1: Подключение репозитория

```bash
# Репозиторий проекта под эгидой Kubernetes SIGs
helm repo add headlamp https://kubernetes-sigs.github.io/headlamp/
helm repo update
```

#### Шаг 2: Создание конфигурации с OIDC и Ingress

```yaml
# headlamp-values.yaml
replicaCount: 2

# Конфигурация приложения
config:
  # Настройка OIDC для сквозной аутентификации через корпоративный Keycloak / Dex
  oidc:
    clientID: "kubernetes-headlamp"
    clientSecret: "HeadlampSuperSecret2026!"
    issuerURL: "https://sso.internal.example.com/realms/kubernetes"
    scopes: "openid,profile,email,groups"

# Сетевой доступ через Ingress
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "64m"
  hosts:
    - host: headlamp.internal.example.com
      paths:
        - path: /
          type: ImplementationSpecific
  tls:
    - secretName: headlamp-tls-certs
      hosts:
        - headlamp.internal.example.com

# Ограничение ресурсов контейнера
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

# Безопасность контекста пода
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
```

#### Шаг 3: Установка чарта

```bash
helm upgrade --install headlamp headlamp/headlamp \
  --namespace headlamp \
  --create-namespace \
  -f headlamp-values.yaml
# → Release "headlamp" has been upgraded. Happy Helming!
```

#### Шаг 4: Настройка NetworkPolicy для изоляции интерфейса

Изолируйте namespace `headlamp`, разрешив входящий трафик только от контроллера Ingress-NGINX:

```yaml
# headlamp-netpol.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: headlamp-isolate-ingress
  namespace: headlamp
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: headlamp
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем входящий трафик только от пода Ingress NGINX
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
          podSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
      ports:
        - protocol: TCP
          port: 4466 # Внутренний порт Headlamp
  egress:
    # Разрешаем исходящий трафик к kube-apiserver и DNS кластера
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
    # Доступ к Kubernetes API (ClusterIP сервиса kubernetes в default namespace)
    - to:
        - ipBlock:
            cidr: 10.96.0.1/32 # IP ClusterIP сервиса kubernetes
      ports:
        - protocol: TCP
          port: 443
    # Доступ к внешнему OIDC провайдеру (IdP)
    - to:
        - ipBlock:
            cidr: 192.168.10.0/24 # Подсеть корпоративного SSO
      ports:
        - protocol: TCP
          port: 443
```

Примените политику:

```bash
kubectl apply -f headlamp-netpol.yaml
# → networkpolicy.networking.k8s.io/headlamp-isolate-ingress created
```

---

### Сценарий 3: Локальные альтернативы без установки компонентов в кластер

В средах с максимальными требованиями к безопасности (где запрещено развертывать сторонние веб-серверы внутри кластера) стандартом являются локальные клиенты.

#### Использование Headlamp Desktop

Headlamp выпускается также как локальное десктопное приложение (Linux, macOS, Windows):
1. Установите бинарный пакет с [официального сайта](https://headlamp.dev/).
2. Headlamp Desktop автоматически считывает локальные контексты из `~/.kube/config`.
3. Все сетевые вызовы выполняются напрямую с рабочей станции инженера на порт `kube-apiserver`, не создавая уязвимых точек входа внутри кластера.

#### Lens Desktop / FreeLens

Локальная графическая среда разработки и управления. Подробные эксплуатационные сценарии вынесены в SSoT-документ: **[Lens — практические сценарии](./ToolsUtilities/lens/practical_scenarios.md)**.
- Использует локальный `~/.kube/config`.
- Позволяет просматривать и редактировать объекты в режиме реального времени, управлять Helm-релизами и просматривать логи нескольких подов одновременно.

#### Быстрая отладка через k9s

Терминальный интерфейс (TUI) — базовый инструмент дежурного инженера и администратора кластера при работе по SSH или в консоли. Полный справочник горячих клавиш и настроек: **[k9s — терминальный UI](./ToolsUtilities/k9s.md)**.

```bash
# Запуск в целевом контексте и namespace
k9s --context prod-baremetal -n kube-system
# → Запуск интерактивного TUI
```

**Ключевые операции в k9s:**
- Навигация по ресурсам: ввод `:` и типа ресурса (`:pods`, `:svc`, `:deploy`, `:ing`, `:events`).
- Фильтрация: `/` затем подстрока имени объекта. Фильтрация по статусу сбоев: `/^0` (показать поды не в статусе Ready).
- Просмотр логов: клавиша `l` (переключение контейнеров клавишами `0`–`9`, автопрокрутка tail `t`, перенос строк `w`).
- Shell в контейнер: клавиша `s` (автоматическое открытие сессии exec).
- Редактирование YAML: клавиша `e` (открывает ресурс в `$EDITOR` с валидацией изменений при сохранении).
- Port-Forwarding без командной строки: наведите курсор на Service или Pod и нажмите `Shift + f`, укажите локальный и удаленный порт. Список активных пробросов доступен по команде `:portforwards`.

---

## Операции и команды управления

Сводная таблица регламентных команд для сопровождения веб-интерфейсов:

| Задача | Инструмент / Компонент | Команда |
| :--- | :--- | :--- |
| **Генерация токена доступа** | Kubernetes Dashboard | `kubectl -n kubernetes-dashboard create token <sa-name> --duration=8h` |
| **Быстрый туннель к Dashboard** | Kubernetes Dashboard | `kubectl -n kubernetes-dashboard port-forward svc/kubernetes-dashboard-kong-proxy 8443:443` |
| **Быстрый туннель к Headlamp** | Headlamp (in-cluster) | `kubectl -n headlamp port-forward svc/headlamp 8080:80` |
| **Проверка статуса подов** | Dashboard v7 | `kubectl -n kubernetes-dashboard get pods -l app.kubernetes.io/part-of=kubernetes-dashboard` |
| **Просмотр логов шлюза Kong** | Dashboard v7 | `kubectl -n kubernetes-dashboard logs deploy/kubernetes-dashboard-kong -c proxy` |
| **Просмотр логов бэкенда API** | Dashboard v7 | `kubectl -n kubernetes-dashboard logs deploy/kubernetes-dashboard-api` |
| **Проверка прав учетной записи** | RBAC Auth Can-I | `kubectl auth can-i get pods --as=system:serviceaccount:kubernetes-dashboard:dashboard-viewer -n default` |
| **Обновление чарта Dashboard** | Helm | `helm upgrade kubernetes-dashboard kubernetes-dashboard/kubernetes-dashboard -n kubernetes-dashboard -f values.yaml` |
| **Обновление чарта Headlamp** | Helm | `helm upgrade headlamp headlamp/headlamp -n headlamp -f values.yaml` |

---

## Диагностика и устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Dashboard v7: 502 / 503 Bad Gateway через Kong** | Один из внутренних сервисов (api или auth) не прошел Readiness Probe | `kubectl -n kubernetes-dashboard get pods`<br>`kubectl -n kubernetes-dashboard describe pod -l app.kubernetes.io/name=kubernetes-dashboard-api` | Проверить лимиты памяти (OOMKilled) у контейнеров `dashboard-api` и `dashboard-auth`. Увеличить memory limit до 512Mi. |
| **Dashboard: Token Expired or Invalid** | Истек срок действия динамического токена TokenRequest | `kubectl -n kubernetes-dashboard logs deploy/kubernetes-dashboard-auth` | Сгенерировать свежий токен через `kubectl create token <sa-name> --duration=8h`. Проверить синхронизацию NTP на нодах кластера. |
| **Dashboard: Нет графиков потребления CPU/RAM** | Сервис `metrics-scraper` не может получить данные от `metrics-server` | `kubectl -n kubernetes-dashboard logs deploy/kubernetes-dashboard-metrics-scraper`<br>`kubectl top nodes` | Убедиться, что `metrics-server` запущен в кластере. Если используются самоподписанные сертификаты kubelet, добавить аргумент `--kubelet-insecure-tls` в манифест `metrics-server`. |
| **Dashboard / Headlamp: CSRF token mismatch при работе через Ingress** | Прокси-сервер или балансировщик срезает заголовок `X-Forwarded-Proto` или `Origin` | Анализ заголовков в DevTools браузера (код ошибки 401/403) | В аннотациях Ingress-NGINX добавить `nginx.ingress.kubernetes.io/proxy-buffer-size: "16k"` и проверить передачу HTTPS заголовков. |
| **Headlamp: OIDC Redirect Loop** | Несовпадение `issuerURL` или отсутствие необходимых scopes | `kubectl -n headlamp logs deploy/headlamp` | Сверить `issuerURL` в `headlamp-values.yaml` с `iss` в ID-токене Keycloak. Добавить `offline_access` и `groups` в параметры scopes. |
| **Headlamp: Пустой список неймспейсов / 403 Forbidden** | Пользователь авторизован, но у него нет прав на `list namespaces` | `kubectl auth can-i list namespaces --as=<username>` | Назначить пользователю ClusterRole с правами `list` на `namespaces` или использовать прямое указание namespace в URL Headlamp (`/c/main/namespaces/<ns-name>`). |
| **Headlamp: Под завис в CrashLoopBackOff** | Ошибка чтения volume или неверные права на диск | `kubectl -n headlamp describe pod -l app.kubernetes.io/name=headlamp` | Проверить права доступа (`fsGroup: 1000`) к подключаемому хранилищу плагинов. |
| **k9s: `Unable to connect to the server`** | Недоступен IP-адрес API сервера или протух сертификат в `~/.kube/config` | `kubectl cluster-info` | Проверить сетевой маршрут к мастер-нодам кластера и срок действия клиентских сертификатов. |

---

## Лучшие практики безопасности и эксплуатации

1. **Принцип наименьших привилегий (RBAC Least Privilege):**
   - Запрещено использование учетной записи `cluster-admin` для постоянной работы через браузерные интерфейсы.
   - Для регулярного мониторинга инженерам создаются аккаунты с привязкой к стандартной роли `view`. Изменения конфигураций должны осуществляться через GitOps (Argo CD, Flux) или контролируемый CI/CD пайплайн, а не через ручное редактирование в Web UI.
2. **Ограничение сетевого периметра (Zero Trust Networking):**
   - Никогда не публикуйте Kubernetes Dashboard или Headlamp на публичных IP-адресах без VPN или корпоративного Reverse Proxy с дополнительным фактором аутентификации (mTLS / 2FA).
   - Обязательно применяйте `NetworkPolicy`, изолирующую поды веб-интерфейса от остального пространства кластера.
3. **Отказ от статических токенов (Static Token Deprecation):**
   - Не создавайте бесконечные токены ServiceAccount через аннотацию `kubernetes.io/service-account.token`. Используйте динамические токены с ограниченным временем жизни (`TokenRequest API`) или OIDC.
4. **Конфигурация Runtime Security:**
   - Эксплуатируйте поды интерфейсов с `readOnlyRootFilesystem: true`, запретом эскалации привилегий (`allowPrivilegeEscalation: false`) и профилем seccomp `RuntimeDefault`.
5. **Централизованный аудит (Kubernetes Audit Logging):**
   - Включите аудит на стороне `kube-apiserver`. Все действия пользователей в веб-интерфейсах должны логироваться с сохранением имени субъекта (`user`), IP-адреса источника и выполняемого глагола (`get`, `create`, `delete`).
6. **Выбор интерфейса под требования безопасности среды:**
   - **Production кластеры высокой критичности (PCI-DSS, High-Sec):** Полный запрет развертывания Web UI внутри кластера. Доступ операторов только через консольные утилиты (`kubectl`, `k9s`) или локальный `Headlamp Desktop` / `FreeLens` через VPN и бастион.
   - **Staging / Dev кластеры:** Централизованный `Headlamp` с авторизацией через корпоративный OIDC.

---

## Очистка ресурсов

```bash
# 1. Удаление Kubernetes Dashboard v7
helm uninstall kubernetes-dashboard -n kubernetes-dashboard
kubectl delete clusterrolebinding dashboard-admin-binding dashboard-viewer-binding
kubectl delete namespace kubernetes-dashboard

# 2. Удаление Headlamp
helm uninstall headlamp -n headlamp
kubectl delete namespace headlamp

# 3. Сброс локальных конфигураций инструментов на рабочей станции (при необходимости)
rm -rf ~/.config/k9s
rm -rf ~/.config/Headlamp
```

---

## Дополнительная информация

### Официальные ресурсы

- [Документация и репозиторий Kubernetes Dashboard](https://github.com/kubernetes/dashboard)
- [Официальный сайт проекта Headlamp (CNCF Sandbox)](https://headlamp.dev/)
- [Репозиторий Headlamp на GitHub](https://github.com/kubernetes-sigs/headlamp)
- [Репозиторий k9s CLI](https://github.com/derailed/k9s)
- [Проект FreeLens (Community Fork)](https://github.com/freelensapp/freelens)

### См. также

- [Kubernetes — обзор инструментов](./kubernetes_overview.md)
- [RBAC — управление доступом](./Security/rbac/rbac_overview.md)
- [Lens — практические сценарии](./ToolsUtilities/lens/practical_scenarios.md)
- [k9s — терминальный UI](./ToolsUtilities/k9s.md)
- [NetworkPolicy в Kubernetes](./Networking/Network/network_policy.md)
- [Ingress NGINX — контроллер входящего трафика](./Networking/Ingress/overview.md)
