# Argo CD: Практическое руководство по установке и настройке

> **Актуальность (2026):** Argo CD версии v3.x является отраслевым стандартом. Основные изменения касаются обязательного использования **Server-Side Apply (SSA)** для установки CRD, интеграции контроллера **ApplicationSet** в ядро системы и поддержки **Gateway API** для публикации сервисов. Начиная с v3.5+ доступен **mTLS** между компонентами. Для продуктивных сред рекомендуется исключительно **HA-режим** (High Availability). SSH-доступ к Git-репозиториям (ed25519/rsa) поддерживается через `argocd-ssh-known-hosts-cm`.

## Предварительные требования

Перед началом установки Argo CD убедитесь в наличии:

1. **Kubernetes кластер:** v1.26+ (рекомендуется v1.28+). Поддерживаются любые дистрибутивы (EKS, GKE, AKS, kubeadm, k3s, minikube).
2. **`kubectl`:** Установлен и настроен для доступа к целевому кластеру. Проверка: `kubectl cluster-info`.
3. **Helm:** v3.10+ (опционально, для установки через чарты). Проверка: `helm version`.
4. **Сеть:** Доступ из кластера к Git-репозиторию и реестрам образов (Docker Hub, Harbor, GHCR).
5. **RBAC:** Администратор кластера для первоначальной установки CRD и Namespace.
6. **Ресурсы:** Минимум 2 CPU / 4 GB RAM для контрольной плоскости Argo CD (non-HA). Для HA — минимум 4 CPU / 8 GB RAM.
7. **Ingress Controller или Gateway API:** Если планируется доступ через внешний URL (nginx, istio, traefik).
8. **cert-manager:** Рекомендуется для автоматического выпуска TLS-сертификатов (Let's Encrypt).

## Определения

**Установка Argo CD** — процесс развёртывания компонентов системы GitOps в Kubernetes-кластере, включающий установку определений ресурсов (CRD), сервисов управления, механизмов контроля доступа и систем кеширования.

**Высокая доступность (HA)** — конфигурация Argo CD, обеспечивающая отказоустойчивость через репликацию ключевых компонентов (API, Repo Server, Controller) и использование распределенного кеша Redis (Sentinel/Cluster).

**Server-Side Apply (SSA)** — нативный механизм Kubernetes для управления состоянием ресурсов на стороне сервера. В Argo CD v3.x является основным методом установки и синхронизации ресурсов, имеющих большой объем данных или управляемых несколькими контроллерами одновременно.

**ApplicationSet Controller** — компонент Argo CD, позволяющий массово создавать и обновлять объекты `Application` на основе шаблонов и генераторов (Git, List, Cluster, Matrix).

**AppProject** — логическая группировка приложений в Argo CD, определяющая допустимые источники (repos), назначения (destinations), функции (roles) и ограничения (sync windows).

**Repository Credentials** — хранилище учетных данных для доступа к Git-репозиториям, поддерживает HTTPS (token/password) и SSH (ed25519/rsa). Управляется через Secret с лейблом `argocd.argoproj.io/secret-type: repository`.

**Cluster Secret** — объект Secret в namespace `argocd`, содержащий URL кластера и учетные данные для управления удаленным Kubernetes-кластером. Позволяет Argo CD работать в multi-cluster режиме.

## Базовые концепции

### Компоненты системы

Архитектура Argo CD v3.x состоит из следующих сервисов:

| Компонент | Назначение | Реплики (HA) |
| :--- | :--- | :--- |
| `argocd-server` | API и веб-интерфейс. Управляет RBAC, аутентификацией и визуализацией состояния приложений. | 3 |
| `argocd-repo-server` | Клонирование Git-репозиториев, работа с Helm-чартами и рендеринг манифестов (Kustomize, CMP). | 3 |
| `argocd-application-controller` | Основной цикл управления: отслеживает состояние (diff) и выполняет синхронизацию (sync). | 1-2 (с шардированием) |
| `argocd-applicationset-controller` | Оркестрация множества приложений (ApplicationSets). | 1-2 |
| `argocd-dex-server` | Прокси для интеграции с внешними провайдерами личности (OIDC, SAML, LDAP). | 1 |
| `argocd-redis` | Высокопроизводительный кеш для хранения состояния кластера и ускорения рендеринга. | 3 (Sentinel) |
| `argocd-notifications-controller` | Обработка событий и отправка алертов (Slack, MSTeams, Telegram). | 1 |

### Способы развертывания

1. **Helm (Рекомендуемый для Production):** Обеспечивает гибкую параметризацию через `values.yaml` и простое управление жизненным циклом самого Argo CD. Поддерживает profile-based конфигурацию.
2. **Kustomize / Manifests:** Прямое управление YAML-файлами. Подходит для простых инсталляций или когда Helm запрещен требованиями безопасности.
3. **Argo CD Operator:** Автоматизирует установку и обновление Argo CD, но вносит дополнительный слой абстракции. Рекомендуется для OpenShift-сред.

### Матрица выбора метода установки

| Критерий | Helm | Kustomize / Manifests | Operator |
| :--- | :--- | :--- | :--- |
| **Простота настройки** | Высокая | Средняя | Высокая |
| **Гибкость параметров** | Полная (values.yaml) | Ограниченная (patch'и) | Средняя |
| **Управление обновлениями** | `helm upgrade` | Ручное / Argo CD | Автоматическое |
| **Multi-tenancy** | Через namespace | Через namespace | Через CRD |
| **Production рекомендация** | **Да** | Для простых сред | Для OpenShift |
| **Air-gapped** | Да (OCI registry) | Да (локальные файлы) | Ограниченно |
| **CRD management** | `--server-side` | `--server-side` | Автоматический |

### Жизненный цикл установки

```
┌─────────────────────────────────────────────────────────────────┐
│  Жизненный цикл установки Argo CD                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Planning          2. Install        3. Configure            │
│  ┌──────────┐        ┌──────────┐      ┌──────────┐           │
│  │ Выбор    │───────▶│ CRD +    │─────▶│ Access   │           │
│  │ метода   │        │ Deploys  │      │ (RBAC)   │           │
│  └──────────┘        └──────────┘      └──────────┘           │
│                                               │                │
│                                               ▼                │
│  6. Upgrade           5. Monitor        4. Connect             │
│  ┌──────────┐        ┌──────────┐      ┌──────────┐           │
│  │ v2→v3    │◀───────│Alerts +  │◀─────│ Git +    │           │
│  │ migrate  │        │ Grafana  │      │ Clusters │           │
│  └──────────┘        └──────────┘      └──────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Практические сценарии

### Сценарий 1: Установка Argo CD v3.x через Helm (HA-режим)

Helm является стандартом для управления инфраструктурой в 2026 году.

**1. Добавление репозитория и подготовка `values.yaml`:**
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
```

**2. Конфигурация для HA (фрагмент `values.yaml`):**
```yaml
global:
  ha:
    enabled: true # Включает репликацию компонентов
    redis:
      proxy:
        enabled: true # Использование Redis Sentinel для HA

server:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3

repoServer:
  replicas: 3

controller:
  replicas: 2 # Требуется шардирование при большом кол-ве приложений

configs:
  cm:
    # Включение mTLS между компонентами (v3.5+)
    # server.initial.tls: "true"
    # Альтернатива: global.tls.enabled в values.yaml
```

**3. Установка:**
```bash
# Использование --server-side обязательно для установки объемных CRD v3.x
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd --create-namespace \
    -f values.yaml --server-side

# Ожидание готовности
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
```

**4. Profile-based установка (продвинутый режим):**
```bash
# Использование профилей для разных окружений
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd --create-namespace \
    --set global.ha.enabled=true \
    --set server.autoscaling.enabled=true \
    --set server.autoscaling.minReplicas=3 \
    --server-side
```

### Сценарий 2: Установка через манифесты (SSA)

Если Helm не используется, примените официальные HA-манифесты.

```bash
kubectl create namespace argocd

# --server-side позволяет избежать ошибок "too long" для аннотаций в CRD
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/ha/install.yaml

# → result: customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io configured...
```

**Проверка установленных CRD:**
```bash
kubectl get crd | grep argoproj
# Ожидаемый результат:
# applicationsets.argoproj.io
# applications.argoproj.io
# appprojects.argoproj.io
# argocds.argoproj.io        # если используется Operator
```

### Сценарий 3: Настройка доступа (Gateway API и Ingress)

Для работы через внешние балансировщики необходимо настроить публикацию сервиса `argocd-server`.

**Вариант А: Gateway API (Стандарт 2026 года)**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: argocd-server
  namespace: argocd
spec:
  parentRefs: [{name: prod-gateway, namespace: istio-system}]
  hostnames: ["argocd.example.com"]
  rules:
  - matches: [{path: {type: PathPrefix, value: /}}]
    backendRefs: [{name: argocd-server, port: 80}]
```

**Вариант Б: Ingress (Классический метод с SSL-терминацией)**
Для работы через Ingress рекомендуется отключить TLS на самом `argocd-server`:
```yaml
# Патч Deployment argocd-server
spec:
  template:
    spec:
      containers:
      - name: argocd-server
        command: ["argocd-server", "--insecure"]
```

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: nginx
  rules:
  - host: argocd.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port: {name: http}
  tls:
  - hosts: ["argocd.example.com"]
    secretName: argocd-tls
```

### Сценарий 4: Подключение приватных репозиториев (GitLab/GitHub и Harbor)

**1. Создание секрета для Git (HTTPS):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: private-repo-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  url: https://gitlab.example.com/org/project.git
  username: "git-bot"
  password: "glpat-secret-token"
```

**2. Подключение Harbor (OCI Helm Repo):**
```bash
argocd repo add harbor.example.com/library --type helm --name harbor-oci \
    --enable-oci --username <robot-user> --password <robot-pwd>
```

**3. SSH-доступ к репозиториям:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: ssh-repo-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  url: git@github.com:org/repo.git
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...
    -----END OPENSSH PRIVATE KEY-----
  insecure: "false"
```

**4. Добавление known hosts для SSH:**
```bash
# Скачивание SSH known hosts
ssh-keyscan github.com >> /tmp/known_hosts

# Создание ConfigMap
kubectl create configmap argocd-ssh-known-hosts-cm \
  --from-file=ssh_known_hosts=/tmp/known_hosts \
  -n argocd
```

### Сценарий 5: Настройка доверенных TLS-сертификатов (Internal CA)

Если внутренние реестры используют самоподписанные сертификаты, добавьте их в доверенные на уровне Argo CD:

```bash
# 1. Создание ConfigMap с корневым сертификатом
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=internal-root.ca=/path/to/root-ca.crt \
  -o yaml --dry-run=client | kubectl apply -f -

# 2. Сервис автоматически подмонтирует сертификаты из CM с соответствующим лейблом
```

**Проверка доверенных сертификатов:**
```bash
kubectl get configmap argocd-tls-certs-cm -n argocd -o yaml
```

### Сценарий 6: Базовая настройка RBAC и локальных пользователей

Настройка выполняется через `argocd-cm` (пользователи) и `argocd-rbac-cm` (права).

**1. Создание пользователя (`argocd-cm`):**
```yaml
data:
  accounts.readonly-user: login, apiKey
```

**2. Назначение прав (`argocd-rbac-cm`):**
```yaml
data:
  policy.csv: |
    p, role:readonly, applications, get, */*, allow
    g, readonly-user, role:readonly
```

**3. Настройка AppProject для изоляции команд:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-backend
  namespace: argocd
spec:
  description: "Backend team project"
  sourceRepos:
    - "https://gitlab.example.com/backend/*"
  destinations:
    - namespace: "backend-*"
      server: "https://kubernetes.default.svc"
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  roles:
    - name: developer
      description: "Backend developer"
      policies:
        - p, proj:team-backend:developer, applications, get, team-backend/*, allow
        - p, proj:team-backend:developer, applications, sync, team-backend/*, allow
      groups:
        - backend-team
```

### Сценарий 7: Шардирование контроллера (Controller Sharding)

При управлении более чем 500 приложениями или десятками удаленных кластеров увеличьте количество реплик контроллера.

**Контекст Multi-cluster:**
При подключении кластеров через прокси (Teleport) шардирование критично для распределения нагрузки на скрипты аутентификации. Подробнее о масштабировании такой архитектуры: **[GitOps-мозг: Производительность](../Concepts/gitops-policy-management.md#производительность-и-масштабирование)**.

**Настройка в `argocd-cmd-params-cm`:**
```yaml
data:
  controller.sharding.algorithm: round-robin
```

**Масштабирование:**
```bash
kubectl scale deployment argocd-application-controller -n argocd --replicas=2
```

**Проверка шардов:**
```bash
# Статистика кластера
argocd admin cluster stats

# Просмотр распределения приложений по шардам
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller -o wide
```

### Сценарий 8: Установка в изолированном контуре (Offline/Air-gapped)

1.  **Перенос образов:** Скачайте все образы Argo CD и перенесите их в локальный реестр (например, Harbor).
2.  **Правка манифестов:** Используйте Kustomize для замены `image` и добавления `imagePullSecrets`.
3.  **Локальные репозитории:** Все внешние Helm-чарты должны быть зеркалированы во внутренний OCI-реестр.

**Чеклист Air-gapped установки:**
```
□ 1. Скачать все Docker-образы Argo CD (сервер, repo-server, controller, redis, dex)
□ 2. Перенести образы в локальный реестр (Harbor, Nexus)
□ 3. Настроить imagePullSecrets в namespace argocd
□ 4. Зеркалировать Helm-чарты во внутренний OCI-реестр
□ 5. Настроить SSH known hosts для Git-серверов (если SSH-доступ)
□ 6. Добавить TLS-сертификаты внутренних CA
□ 7. Настроить DNS для внутренних сервисов (vault, gitlab, harbor)
□ 8. Протестировать сетевую доступность всех зависимостей
```

### Сценарий 9: Установка CLI

CLI `argocd` необходим для управления Argo CD из командной строки.

**macOS:**
```bash
# Homebrew (рекомендуется)
brew install argocd

# Или скачать бинарник вручную
curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-darwin-amd64
chmod +x argocd && sudo mv argocd /usr/local/bin/
```

**Linux (amd64):**
```bash
# Скачивание последней версии
curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
chmod +x argocd && sudo mv argocd /usr/local/bin/

# Проверка версии
argocd version
```

**Windows:**
```powershell
# Chocolatey
choco install argocd

# Или скачать .exe с GitHub Releases
# https://github.com/argoproj/argo-cd/releases/latest
```

**Настройка completion:**
```bash
# Bash
argocd completion bash > /etc/bash_completion.d/argocd

# Zsh
argocd completion zsh > "${fpath[1]}/_argocd"
```

### Сценарий 10: Начальная конфигурация

После установки Argo CD требуется первичная настройка.

**1. Получение первичного пароля:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
```

**2. Доступ к UI:**
```bash
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Откройте http://localhost:8080
# Логин: admin
# Пароль: из шага 1
```

**3. Вход через CLI:**
```bash
argocd login localhost:8080 --username admin --password <password> --insecure
```

**4. Изменение пароля:**
```bash
# Через CLI
argocd account update-password

# Или через Secret ( нового пароля)
NEW_PASSWORD=$(echo -n 'new-password' | base64)
kubectl -n argocd patch secret argocd-initial-admin-secret \
  -p '{"data": {"password": "'$NEW_PASSWORD'"}}'
```

**5. Создание первого приложения:**
```bash
argocd app create my-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace guestbook \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Синхронизация
argocd app sync my-app

# Просмотр состояния
argocd app get my-app
```

### Сценарий 11: Обновление и миграция v2→v3

**Важно:** Обновление с v2 на v3 требует миграции CRD и проверки совместимости.

**1. Миграция CRD (обязательно для v3.x):**
```bash
# Обновление CRD с SSA (критично!)
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/crds.yaml

# Или через Helm
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --set server.initArgs[0]="--server" \
  --server-side
```

**2. Миграция ApplicationSet:**
```bash
# v3.x интегрирует ApplicationSet Controller в ядро
# Удалите старый ApplicationSet Controller (если был установлен отдельно)
kubectl delete deployment argocd-applicationset-controller -n argocd
```

**3. Проверка совместимости:**
```bash
# Проверка версии
argocd version

# Проверка CRD
kubectl get crd | grep argoproj

# Проверка логов на ошибки миграции
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100
```

**4. Rollback при проблемах:**
```bash
# Откат на предыдущую версию Helm
helm rollback argocd <revision> -n argocd

# Или откат CRD
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.9.0/manifests/crds.yaml
```

### Сценарий 12: Backup и Disaster Recovery

**1. Резервное копирование состояния Argo CD:**
```bash
# Экспорт всех Application и AppProject
kubectl get applications -n argocd -o yaml > argocd-apps-backup.yaml
kubectl get appprojects -n argocd -o yaml > argocd-projects-backup.yaml

# Экспорт секретов (репозитории, кластеры)
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type -o yaml > argocd-secrets-backup.yaml

# Экспорт ConfigMaps (конфигурация)
kubectl get configmaps -n argocd argocd-cm argocd-rbac-cm argocd-params-cm -o yaml > argocd-config-backup.yaml
```

**2. Восстановление:**
```bash
# Восстановление в порядке зависимостей
kubectl apply -f argocd-config-backup.yaml
kubectl apply -f argocd-secrets-backup.yaml
kubectl apply -f argocd-projects-backup.yaml
kubectl apply -f argocd-apps-backup.yaml
```

**3. Восстановление из etcd (полное):**
```bash
# Если доступен etcd snapshot
etcdctl snapshot restore /backup/etcd-snapshot.db --data-dir=/var/lib/etcd-restored
```

### Сценарий 13: NetworkPolicies (Security Hardening)

Ограничьте сетевой доступ компонентов Argo CD.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: argocd-server-network-policy
  namespace: argocd
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: istio-system
    ports:
    - port: 8080
      protocol: TCP
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: argocd
    ports:
    - port: 6379
      protocol: TCP
    - port: 8083
      protocol: TCP
  - to: [] # Разрешить DNS
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

**Основные правила:**
- Ingress: только из ingress controller / istio
- Egress: только в Redis, repo-server, DNS
- Isolation: изолируйте Argo CD от production namespace

### Сценарий 14: Интеграция с Prometheus и Grafana

**1. Включение метрик в Argo CD:**
```yaml
# argocd-cmd-params-cm
data:
  metrics.enabled: "true"
  controller.metrics.enabled: "true"
  server.metrics.enabled: "true"
  repoServer.metrics.enabled: "true"
```

**2. ServiceMonitor для Prometheus Operator:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: argocd-metrics
  namespace: argocd
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-metrics
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

**3. Основные метрики для дашбордов:**
| Метрика | Описание | Тип |
| :--- | :--- | :--- |
| `argocd_app_info` | Информация о приложении (health, sync, project) | Gauge |
| `argocd_app_sync_total` | Количество синхронизаций (по статусам) | Counter |
| `argocd_app_reconcile_total` | Количество реконсиляций | Counter |
| `argocd_app_health_status` | Статус здоровья приложения | Gauge |
| `argocd_app_sync_duration_seconds` | Длительность синхронизации | Histogram |
| `argocd_repo_open_connections` | Активные соединения с Git | Gauge |
| `argocd_redis_connection_pool_size` | Размер пула соединений Redis | Gauge |

**4. Grafana Dashboard:**
```bash
# Импорт дашборда ID 14582 (Argo CD)
# https://grafana.com/grafana/dashboards/14582-argo-cd/
```

## Технический справочник

### Рекомендации по ресурсам

| Компонент | Non-HA (100 apps) | HA (1000+ apps) | Memory-intensive |
| :--- | :--- | :--- | :--- |
| `argocd-application-controller` | 1 CPU / 2Gi | 2 CPU / 4Gi | 4 CPU / 8Gi |
| `argocd-repo-server` | 500m / 1Gi | 1 CPU / 2Gi | 2 CPU / 4Gi |
| `argocd-server` | 200m / 512Mi | 500m / 1Gi | 1 CPU / 2Gi |
| `argocd-redis` | 500m / 1Gi | 1 CPU / 2Gi | 2 CPU / 4Gi |
| `argocd-dex-server` | 50m / 64Mi | 100m / 128Mi | 200m / 256Mi |

### Ключевые переменные окружения

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `ARGOCD_SERVER` | Адрес API сервера | `argocd-server.argocd` |
| `ARGOCD_OPTS` | Дополнительные опции CLI | — |
| `ARGOCD_LATEST` | Использовать latest версию CLI | `true` |
| `ARGOCD_INSECURE` | Отключить проверку TLS | `false` |
| `ARGOCD_PRIMARY_CACERT` | Путь к CA-сертификату | — |

### Параметры `argocd-cm` (ConfigMap)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `url` | Публичный URL Argo CD | — |
| `statusbadge.enabled` | Включить Status Badge | `false` |
| `admin.enabled` | Включить admin-пользователя | `true` |
| `users.allowSignup` | Разрешить регистрацию | `false` |
| `helm.valuesFileSchemes` | Допустимые схемы values файлов | `https,oci` |
| `timeout.reconciliation` | Таймаут реконсиляции | `180s` |

### Параметры `argocd-rbac-cm` (RBAC)

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `policy.default` | Роль по умолчанию | `role:readonly` |
| `policy.csv` | Политики доступа (CSV) | — |
| `scopes` | Области применения политик | `[groups]` |

### Пост-установочные проверки (Health Check)

1. **Поды:** `kubectl get pods -n argocd` (все `Running`).
2. **CRD:** `kubectl get crd | grep argoproj` (5+ ресурсов).
3. **API:** `curl -k https://argocd.example.com/healthz` (200 OK).
4. **Redis:** `kubectl exec -it -n argocd deployment/argocd-redis -- redis-cli ping` (должен вернуть `PONG`).
5. **CLI:** `argocd version` (выводит версию клиента и сервера).
6. **RBAC:** `argocd admin settings rbac validate` (валидация политик).
7. **Порты:** Проверка доступности сервисов:
   ```bash
   kubectl get svc -n argocd argocd-server
   # Ожидаемый результат: CLUSTER-IP, порты 80/443
   ```

### Диагностика

```bash
# Статистика кластера и шардов
argocd admin cluster stats

# События контроллера
kubectl get events -n argocd --field-selector involvedObject.kind=Application

# Проверка mTLS между компонентами (v3.5+)
# Если включено global.tls.enabled=true, проверьте логи repo-server на наличие TLS handshake errors

# Просмотр логов всех компонентов
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-server --tail=100
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=100
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100

# Проверка ConfigMaps
kubectl get configmaps -n argocd

# Проверка Secrets
kubectl get secrets -n argocd | grep -E 'repository|cluster|ssh'
```

### Security Hardening Checklist

```
□ 1. Включить mTLS между компонентами (global.tls.enabled=true)
□ 2. Настроить NetworkPolicies (изолировать namespace argocd)
□ 3. Удалить admin-пользователя после настройки SSO
□ 4. Ограничить RBAC: использовать minimal privileges
□ 5. Включить Audit Logging в Vault (если используется)
□ 6. Настроить Pod Security Standards (Restricted)
□ 7. Ограничить ресурсы (CPU/Memory limits) для всех компонентов
□ 8. Включить readOnlyRootFilesystem для repo-server
□ 9. Настроить ImagePullPolicy: Always
□ 10. Проверить Secrets на наличие plaintext паролей
```

## Ограничения и edge cases

### Ограничения

1. **Namespace isolation:** Argo CD v3.x не поддерживает multi-tenancy через один instance без AppProject.
2. **ApplicationSet limits:** При 1000+ ApplicationSet требуется шардирование ApplicationSet Controller.
3. **Redis scalability:** Вертикальное масштабирование Redis ограничено; для кластеров 10000+ apps используется Redis Cluster.
4. **Git rate limits:** GitHub/GitLab API limits (5000 req/hour) могут блокировать большие монорепозитории.
5. **SSA conflicts:** Параллельные операции с одним ресурсом могут вызывать conflicts.

### Edge Cases

1. **CRD upgrade failure:** Если CRD не обновились, Argo CD может потерять доступ к Application объектам.
2. **Redis OOM:** При большом количестве приложений Redis может потребовать горизонтального масштабирования.
3. **Helm chart dependencies:** При использовании chart dependencies с OCI-реестрами требуется дополнительная настройка.
4. **SSH key rotation:** При ротации SSH ключей необходимо обновлять Secret в namespace argocd.
5. **Multi-cluster latency:** При управлении удалёнными кластерами через Internet увеличивается latency реконсиляции.
6. **ApplicationSet conflicts:** При параллельном обновлении ApplicationSet и Application могут возникать conflicts.
7. **Dex downtime:** При недоступности Dex-сервера SSO-аутентификация недоступна (локальные пользователи работают).
8. **mTLS handshake errors:** При неправильной настройке TLS могут возникать ошибки handshakes между компонентами.

## См. также

- [Argo CD: Обзор системы](./argocd_overview.md)
- [Argo CD: Настройка SSO через GitLab](./argocd_sso_gitlab.md) — детальная настройка OIDC.
- [Argo CD: Синхронизация и её политики](./synchronization.md)
- [Argo CD: Интеграция с Vault](./argocd_vault_integration.md)
- [Argo CD: Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md)
- [Argo CD: Custom Tooling и плагины](./argocd_custom_tooling.md)
- [Официальное руководство по HA](https://argo-cd.readthedocs.io/en/stable/operator-manual/high-availability/)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
