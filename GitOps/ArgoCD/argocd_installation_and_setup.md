# Argo CD: Практическое руководство по установке и настройке

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Контекст развертывания:** Argo CD v3.x является отраслевым стандартом GitOps для оркестрации инфраструктуры и приложений. В архитектуре v3.x обязательным требованием является использование **Server-Side Apply (SSA)** для установки и обновления ресурсоемких CRD, контроллер **ApplicationSet** интегрирован в состав дистрибутива, а для публикации сервисов поддерживается как классический Ingress (NGINX), так и **Gateway API** (Envoy, Cilium, Istio). Начиная с v3.5+ доступен **mTLS** между внутренними сервисами. Для продуктивных контуров регламентируется исключительно **HA-режим** (High Availability) с Redis Sentinel/HAProxy. Аутентификация к Git-серверам (GitLab, Gitea) обеспечивается по HTTPS и SSH (ed25519) с привязкой доверенных CA и `known_hosts`.

## Определения

**Установка Argo CD** — процесс развертывания компонентов управляющего контура GitOps в кластере Kubernetes, включающий регистрацию Custom Resource Definitions (CRD), запуск контроллеров синхронизации, API-сервера, кэширующего уровня Redis и первичную настройку сетевого доступа.

**Режим высокой доступности (HA)** — конфигурация Argo CD, исключающая единые точки отказа (SPOF) за счет репликации ключевых компонентов (`argocd-server`, `argocd-repo-server`, `argocd-application-controller`), распределения реплик по физическим узлам через PodAntiAffinity и запуска кэша Redis в кластере с координацией через Sentinel или HAProxy.

**Server-Side Apply (SSA)** — нативный механизм Kubernetes API, переносящий расчет и слияние изменений (field management) с клиента `kubectl` на `kube-apiserver`. В Argo CD v3.x использование `--server-side` является обязательным при установке CRD, так как объем схем превышает лимит аннотации `kubectl.kubernetes.io/last-applied-configuration` (256 КБ).

**Шардирование контроллера (Controller Sharding)** — распределение нагрузки по обработке приложений (`Application`) между несколькими независимыми экземплярами `argocd-application-controller` на основе детерминированного алгоритма (round-robin или по хэшу целевого кластера).

**Redis Sentinel / HAProxy** — архитектура высокой доступности кэша Argo CD, в которой пул экземпляров Redis управляется процессами Sentinel для автоматического failover при сбое мастера, а клиентские поды подключаются через балансировщик HAProxy.

**ApplicationSet Controller** — встроенный контроллер автоматизации, генерирующий множество ресурсов `Application` по единым шаблонам с использованием генераторов (Git-директории, кластеры, списки, pull requests).

**Repository Credentials** — объект `Secret` с системной меткой `argocd.argoproj.io/secret-type: repository`, хранящий авторизационные данные (SSH-ключи, токены, пароли) для доступа к исходным репозиториям Git и Helm/OCI-реестрам.

**Cluster Secret** — объект `Secret` с системной меткой `argocd.argoproj.io/secret-type: cluster`, содержащий адрес API-сервера, CA-сертификат и токен сервисного аккаунта целевого управляемого кластера Kubernetes.

## Архитектура и базовые концепции

### Компоненты системы

Архитектура Argo CD v3.x состоит из взаимодействующих микросервисов:

| Компонент | Назначение | Реплики (Non-HA) | Реплики (HA) | Сетевые порты |
| :--- | :--- | :--- | :--- | :--- |
| `argocd-server` | API-сервер (gRPC/REST) и пользовательский веб-интерфейс. Выполняет аутентификацию, RBAC-авторизацию и генерацию UI. | 1 | 3 | 8080 (HTTP), 8083 (gRPC) |
| `argocd-repo-server` | Внутренний сервис клонирования Git-репозиториев, скачивания Helm-чартов и рендеринга манифестов (Kustomize, Helm, CMP v2). | 1 | 3-5 | 8081 (gRPC), 8084 (metrics) |
| `argocd-application-controller` | Основной контроллер сверки (reconciliation loop). Сравнивает состояние Git с кластером, вычисляет diff и применяет изменения. | 1 | 2-3 (с шардированием) | 8082 (metrics) |
| `argocd-applicationset-controller` | Оркестратор генерации множественных объектов `Application` на основе правил `ApplicationSet`. | 1 | 2 | 7000 (metrics), 8080 (webhook) |
| `argocd-redis` / `redis-ha` | Высокопроизводительный кэш манифестов, сессий, токенов и состояния Kubernetes-ресурсов. | 1 (Standalone) | 3 (Sentinel) + 3 HAProxy | 6379 (Redis), 26379 (Sentinel) |
| `argocd-dex-server` | Встроенный OIDC/OAuth2 прокси для интеграции с внешними корпоративными каталогами (GitLab, Keycloak, LDAP, Active Directory). | 1 | 1-2 | 5556 (HTTP), 5557 (gRPC) |
| `argocd-notifications-controller` | Контроллер рассылки уведомлений о событиях синхронизации (Telegram, корпоративный вебхук, почта). | 1 | 1 | 9001 (metrics) |

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                  Архитектура высокой доступности Argo CD (HA)                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    Инженеры / CI-пайплайны                Управляемые кластеры (Bare-Metal) │
│           │                                             ▲                    │
│           │ HTTPS / gRPC                                │ K8s API (6443)     │
│           ▼                                             │                    │
│    ┌──────────────┐                             ┌────────────────┐           │
│    │ Ingress /    │                             │ argocd-app-    │           │
│    │ Gateway API  │                             │ controller     │           │
│    └──────┬───────┘                             │ (Shard 0..N)   │           │
│           │                                     └───────▲────────┘           │
│           ▼                                             │                    │
│    ┌──────────────┐         gRPC (mTLS)                 │                    │
│    │ argocd-      │─────────────────────────────┐       │                    │
│    │ server (x3)  │                             ▼       ▼                    │
│    └──────┬───────┘ ┌────────────┐          ┌────────────────┐               │
│           │         │ argocd-    │◀─────────│ argocd-repo-   │               │
│           │         │ dex (OIDC) │          │ server (x3)    │               │
│           ▼         └────────────┘          └───────┬────────┘               │
│    ┌──────────────┐                                 │                        │
│    │ HAProxy      │                                 │ Git / OCI / SSH        │
│    │ (port 6379)  │                                 ▼                        │
│    └──────┬───────┘                      ┌───────────────────────┐           │
│           ▼                              │ Self-Hosted GitLab /  │           │
│    ┌──────────────┐                      │ Harbor Registry /     │           │
│    │ Redis HA     │                      │ Корпоративный Git     │           │
│    │ (Sentinel x3)│                      └───────────────────────┘           │
│    └──────────────┘                                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Способы развертывания

1. **Helm (Рекомендуемый для Production):** Официальный чарт `argo/argo-cd`. Позволяет централизованно управлять конфигурацией через `values.yaml`, параметризовать распределение ресурсов, настраивать PDB (PodDisruptionBudget), реплики и монтирование секретов.
2. **Kustomize / Официальные манифесты:** Прямое применение апстрим-манифестов (`ha/install.yaml` или `install.yaml`). Используется при жестких требованиях GitOps-бутстрапа без пакетных менеджеров или в контурах с запретом Helm.
3. **Argo CD Operator:** Развертывание через Kubernetes Operator. Вносит дополнительную абстракцию и зависимости, рекомендуется преимущественно при наличии регламентов на использование операторов.

### Сравнительная матрица методов установки

| Критерий | Helm (argo-cd) | Kustomize / Vanilla YAML | Operator |
| :--- | :--- | :--- | :--- |
| **Сложность внедрения** | Низкая (декларативные `values.yaml`) | Средняя (необходимость оверлеев) | Средняя (зависимость от CRD оператора) |
| **Управление HA-стеком** | Автоматическое развертывание Redis HA | Ручная правка манифестов | Декларативное через CRD `ArgoCD` |
| **Обновление версий** | `helm upgrade` с валидацией чарта | `kubectl apply` поверх существующего | Автоматическое или полуавтоматическое |
| **Установка больших CRD** | Обязательно `--server-side` | Обязательно `--server-side` | Выполняется контроллером оператора |
| **Изоляция в On-Premise** | Полная поддержка Private OCI/Harbor | Локальные файлы / Git | Требует зеркалирования оператор-образов |
| **Стандарт для Production** | **Основной выбор** | Для минималистичных стендов | Для специализированных платформ |

### Топологии развертывания в On-Premise инфраструктуре

1. **In-Cluster (Автономная):** Argo CD развернут в том же кластере, в который выполняет деплой. Подходит для средних инсталляций, тестовых контуров и одиночных кластеров.
2. **Central Hub (Hub-and-Spoke):** Единый выделенный управляющий кластер (Management Cluster), на котором работает высокодоступный Argo CD. Управляющий кластер подключается по сети к целевым рабочим кластерам (Target Clusters) через их kube-apiserver и управляет сотнями рабочих узлов и неймспейсов без установки дополнительных агентов в целевые среды.

### Жизненный цикл установки

```
1. Планирование  ──▶ 2. Пререквизиты ──▶ 3. Установка CRD ──▶ 4. Развертывание HA ──▶ 5. Инициализация ──▶ 6. Валидация
   Выбор топологии      Сеть, диски,        SSA apply            Helm / Manifests        Смена пароля,        Health checks,
   (In-Cluster/Hub)     ресурсы, DNS        схем v3.x            Sentinel, контроллеры   Ingress, Git creds   тестовый sync
```

## Практические сценарии установки и настройки

### Предварительные требования к инфраструктуре

Перед началом установки убедитесь в выполнении следующих требований:

1. **Кластер Kubernetes:** Версия v1.28–v1.32+ на базе on-premise дистрибутивов (kubeadm, k3s, RKE2, Talos Linux, MicroK8s).
2. **Утилиты управления:** Установленный `kubectl` с правами `cluster-admin` и `helm` v3.12+.
   ```bash
   kubectl version --client -o yaml
   # → result: clientVersion: { major: "1", minor: "31", ... }
   helm version --short
   # → result: v3.16.1+g5a5449d
   ```
3. **Аппаратные ресурсы:**
   - **Non-HA стенд:** минимум 2 vCPU, 4 ГБ RAM на узлах K8s.
   - **Production HA:** минимум 3 рабочих узла (для размещения кворума реплик), суммарно не менее 6 vCPU и 12 ГБ RAM для компонентов Argo CD.
4. **Сетевая связность (Firewall / Security):**
   - Доступ от подов `argocd-repo-server` к внутреннему Git-серверу (GitLab/Gitea): порт 443 (HTTPS) или 22 (SSH).
   - Доступ от подов `argocd-repo-server` к корпоративному OCI-реестру (Harbor): порт 443.
   - Доступ от подов `argocd-application-controller` к API-серверам целевых кластеров: порт 6443.
   - Корректно настроенный внутренний CoreDNS для разрешения локальных FQDN.
5. **Хранилище (StorageClass):** Для Redis HA требуется StorageClass, поддерживающий `ReadWriteOnce` с минимальными задержками (Ceph RBD, Local PV, OpenEBS, NFS v4.1).

---

### Сценарий 1: Установка Argo CD через Helm в HA-режиме (Production)

Официальный чарт `argo/argo-cd` является основным инструментом развертывания.

**1. Добавление и обновление репозитория Helm:**
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update argo
# → result: Successfully got an update from the "argo" chart repository
```

**2. Подготовка production-файла `values-ha.yaml`:**
```yaml
# values-ha.yaml — Отказоустойчивая конфигурация для On-Premise инфраструктуры
global:
  domain: "argocd.corp.internal"
  # Включение HA-режима: автоматически конфигурирует реплики и Redis HA
  ha:
    enabled: true
    redis:
      proxy:
        enabled: true

# API-сервер и пользовательский интерфейс
server:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 6
    targetCPUUtilizationPercentage: 80
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: 1000m
      memory: 1Gi
  certificate:
    enabled: false # Терминация TLS выполняется на Ingress
  extraArgs:
    - --insecure # Отключение внутреннего TLS для корректной работы за Ingress

# Сервер клонирования и рендеринга манифестов
repoServer:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 8
    targetCPUUtilizationPercentage: 75
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  # Настройка максимального времени выполнения сборки манифестов (Helm/Kustomize)
  env:
    - name: ARGOCD_EXEC_TIMEOUT
      value: "180s"

# Контроллер синхронизации
controller:
  replicas: 2
  resources:
    requests:
      cpu: 1000m
      memory: 2Gi
    limits:
      cpu: 4000m
      memory: 8Gi
  env:
    - name: ARGOCD_CONTROLLER_SHARDING_ALGORITHM
      value: "round-robin"

# Контроллер ApplicationSet
applicationSet:
  replicas: 2
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

# Конфигурация Redis HA (Sentinel)
redis-ha:
  enabled: true
  redis:
    masterGroupName: argocd-master
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 2Gi
  haproxy:
    enabled: true
    replicas: 3
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 256Mi

# Базовые параметры argocd-cm
configs:
  cm:
    url: https://argocd.corp.internal
    admin.enabled: "true"
    timeout.reconciliation: 180s
    helm.valuesFileSchemes: "https,oci"
  params:
    server.insecure: true
    controller.sharding.algorithm: "round-robin"
```

**3. Развертывание чарта с использованием Server-Side Apply:**
```bash
# Создание пространства имен
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
# → result: namespace/argocd created

# Установка с флагом --server-side (критично для больших CRD v3.x)
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  -f values-ha.yaml \
  --server-side \
  --timeout 10m
# → result: Release "argocd" has been upgraded. Happy Helming!
```

**4. Контроль готовности всех подов:**
```bash
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
# → result: deployment.apps/argocd-server condition met

kubectl wait --for=condition=available deployment/argocd-repo-server -n argocd --timeout=300s
# → result: deployment.apps/argocd-repo-server condition met

kubectl get pods -n argocd -o wide
# → result: все поды в статусе Running и распределены по разным нодам
```

---

### Сценарий 2: Установка через манифесты (Server-Side Apply)

Если в контуре не используется Helm, развертывание выполняется официальными HA-манифестами.

**1. Применение манифестов с принудительным разрешением конфликтов SSA:**
```bash
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -

# Применение официального бандла высокой доступности
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/ha/install.yaml
# → result: customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io configured
# → result: service/argocd-server created
```

**2. Валидация зарегистрированных CRD:**
```bash
kubectl get crd -l app.kubernetes.io/part-of=argocd
# → result:
# NAME                          CREATED AT
# applications.argoproj.io      2026-10-12T10:00:00Z
# applicationsets.argoproj.io   2026-10-12T10:00:00Z
# appprojects.argoproj.io       2026-10-12T10:00:00Z
```

---

### Сценарий 3: Настройка сетевой публикации (Ingress и Gateway API на Bare-Metal)

Argo CD API-сервер одновременно обслуживает стандартный HTTP(S) трафик для Web UI и gRPC-соединения для утилиты CLI.

#### Вариант А: Ingress NGINX (Классическая схема с SSL-терминацией)

Для корректной работы веб-интерфейса и gRPC через NGINX Ingress Controller сервер запускается с параметром `--insecure` (чтобы избежать двойного шифрования и redirect loops):

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    # Базовые параметры NGINX
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "60"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-buffer-size: "128k"
spec:
  ingressClassName: nginx
  rules:
  - host: argocd.corp.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: argocd-server
            port:
              name: http
  tls:
  - hosts:
    - argocd.corp.internal
    secretName: argocd-corp-tls-secret
```

#### Вариант Б: Gateway API (HTTPRoute)

Если в кластере используется Gateway API (реализации Envoy Gateway, Cilium Service Mesh или Istio):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: argocd-server-route
  namespace: argocd
spec:
  parentRefs:
  - name: internal-gateway
    namespace: gateway-system
  hostnames:
  - "argocd.corp.internal"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: argocd-server
      port: 80
```

Применение манифеста:
```bash
kubectl apply -f argocd-ingress.yaml
# → result: ingress.networking.k8s.io/argocd-server-ingress created
```

---

### Сценарий 4: Подключение приватных корпоративных Git-репозиториев и Harbor OCI

Argo CD требует учетных данных для чтения манифестов из защищенных репозиториев.

#### Вариант 1: GitLab / Gitea через HTTPS (Personal/Project Access Token)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-gitlab-internal
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://gitlab.corp.internal/platform/gitops-manifests.git
  username: "gitops-sync-bot"
  password: "glpat-secret-token-value"
  # Включение LFS при необходимости
  enableLfs: "false"
```

#### Вариант 2: SSH-доступ по ed25519 ключу

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-ssh-internal
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: git@gitlab.corp.internal:platform/gitops-manifests.git
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
    ...
    -----END OPENSSH PRIVATE KEY-----
  insecure: "false"
```

**Регистрация доверенных SSH-хостов (`known_hosts`):**
Для предотвращения атак Man-in-the-Middle `argocd-repo-server` сверяет публичный ключ SSH-сервера.

```bash
# Получение публичного ключа Git-сервера
ssh-keyscan -t ed25519 -p 22 gitlab.corp.internal > /tmp/ssh_known_hosts
# → result: # gitlab.corp.internal:22 SSH-2.0-OpenSSH_8.9p1

# Добавление в системный ConfigMap
kubectl create configmap argocd-ssh-known-hosts-cm \
  --from-file=ssh_known_hosts=/tmp/ssh_known_hosts \
  -n argocd --dry-run=client -o yaml | kubectl apply -f -
# → result: configmap/argocd-ssh-known-hosts-cm configured
```

#### Вариант 3: Подключение Harbor OCI Helm-репозитория

```bash
argocd repo add harbor.corp.internal/charts \
  --type helm \
  --name harbor-charts \
  --enable-oci \
  --username "robot-argocd" \
  --password "harbor-robot-secret-token"
# → result: Repository 'harbor.corp.internal/charts' added
```

---

### Сценарий 5: Настройка доверенных внутренних TLS-сертификатов (Internal Corporate CA)

Если локальные сервисы (GitLab, Harbor, Vault) используют сертификаты, подписанные корпоративным центром сертификации (Private CA), поды `argocd-repo-server` и `argocd-server` будут отклонять соединения с ошибкой `x509: certificate signed by unknown authority`.

**1. Добавление корневого сертификата в ConfigMap:**
```bash
# Создание ConfigMap с файлом корневого сертификата
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=corp-root-ca.crt=/etc/ssl/certs/corporate-root-ca.crt \
  --dry-run=client -o yaml | kubectl apply -f -
# → result: configmap/argocd-tls-certs-cm configured
```

**2. Автоматическое монтирование:**
Компоненты Argo CD автоматически сканируют `argocd-tls-certs-cm` и добавляют сертификаты в системный пул доверенных CA. Перезапуск подов не требуется, но для ускорения применения можно выполнить:
```bash
kubectl rollout restart deployment/argocd-repo-server -n argocd
# → result: deployment.apps/argocd-repo-server restarted
```

---

### Сценарий 6: Установка и настройка CLI (`argocd`)

#### Установка на Linux (amd64 / arm64)
```bash
# Определение актуальной стабильной версии
ARGOCD_VERSION=$(curl -sSL "https://api.github.com/repos/argoproj/argo-cd/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

# Загрузка исполняемого файла
curl -sSL -o argocd "https://github.com/argoproj/argo-cd/releases/download/${ARGOCD_VERSION}/argocd-linux-amd64"

# Установка прав и перенос в PATH
chmod +x argocd
sudo mv argocd /usr/local/bin/

# Проверка
argocd version --client
# → result: argocd: v3.5.x+...
```

#### Настройка автодополнения (Shell Completion)
```bash
# Для Bash
sudo sh -c 'argocd completion bash > /etc/bash_completion.d/argocd'

# Для Zsh
argocd completion zsh > "${fpath[1]}/_argocd"
```

---

### Сценарий 7: Первичная аутентификация и безопасная смена пароля администратора

После развертывания Argo CD генерирует случайный пароль для встроенного пользователя `admin`.

**1. Извлечение первичного сгенерированного пароля:**
```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo
# → result: vN8k9LmX2pQ4rS1z
```

**2. Вход через CLI:**
```bash
argocd login argocd.corp.internal --username admin --password "vN8k9LmX2pQ4rS1z" --grpc-web
# → result: 'admin:login' logged in successfully
# → result: Context 'argocd.corp.internal' updated
```

**3. Смена пароля через CLI:**
```bash
argocd account update-password \
  --current-password "vN8k9LmX2pQ4rS1z" \
  --new-password "SecureProdPassword2026!"
# → result: Password updated
```

**4. Альтернатива: Декларативная установка пароля через bcrypt-хэш:**
Если смена пароля автоматизируется через скрипты без интерактивного CLI:
```bash
# Генерация bcrypt-хэша с фактором стоимости 10
NEW_HASH=$(htpasswd -nbBC 10 "" "SecureProdPassword2026!" | tr -d ':\n')
MTIME=$(date -u +%FT%T%Z)

# Патчинг системного секрета argocd-secret (НЕ initial-admin-secret!)
kubectl -n argocd patch secret argocd-secret \
  -p "{\"stringData\": {\"admin.password\": \"$NEW_HASH\", \"admin.passwordMtime\": \"$MTIME\"}}"
# → result: secret/argocd-secret patched
```

**5. Удаление первичного секрета (Обязательное требование безопасности):**
```bash
kubectl -n argocd delete secret argocd-initial-admin-secret
# → result: secret "argocd-initial-admin-secret" deleted
```

---

### Сценарий 8: Подключение удаленных целевых On-Premise кластеров (Multi-Cluster)

В топологии Central Hub (Hub-and-Spoke) единый управляющий экземпляр Argo CD подключается по сети к целевым рабочим кластерам (Target Clusters).

#### 1. Механика работы команды `argocd cluster add`:
При выполнении команды `argocd cluster add <context>` утилита CLI выполняет следующие низкоуровневые действия:
1. Считывает текущий контекст `kubectl` инженера и подключается к API-серверу целевого кластера.
2. В пространстве имен `kube-system` целевого кластера создает ServiceAccount `argocd-manager`.
3. Создает объект `ClusterRole` (по умолчанию с правами `cluster-admin`) и `ClusterRoleBinding` `argocd-manager-role`.
4. Генерирует или извлекает токен авторизации (Bearer Token) сервисного аккаунта и корневой CA-сертификат API-сервера.
5. Создает в управляющем кластере (в namespace `argocd`) объект `Secret` с системной меткой `argocd.argoproj.io/secret-type: cluster`.

```bash
# Просмотр доступных контекстов инженера
kubectl config get-contexts -o name
# → result: kubernetes-admin@cluster-worker-prod-01

# Регистрация кластера через CLI
argocd cluster add kubernetes-admin@cluster-worker-prod-01 \
  --name "worker-prod-01" \
  --system-namespace kube-system \
  --yes
# → result: Cluster 'https://192.168.10.50:6443' added
```

#### 2. Декларативный онбординг без CLI (Стандарт GitOps для K8s 1.24+):
В автоматизированных пайплайнах подготовки кластеров (Ansible, Terraform, Talos) запуск интерактивного CLI неприемлем. В Kubernetes 1.24+ токены ServiceAccount не создаются автоматически, поэтому токен объявляется явно через привязанный Secret.

**Шаг А. Создание ServiceAccount и токена на целевом рабочем кластере:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argocd-manager
  namespace: kube-system
---
apiVersion: v1
kind: Secret
metadata:
  name: argocd-manager-token
  namespace: kube-system
  annotations:
    kubernetes.io/service-account.name: argocd-manager
type: kubernetes.io/service-account.token
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-manager-role
subjects:
  - kind: ServiceAccount
    name: argocd-manager
    namespace: kube-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
```

**Шаг Б. Создание секрета кластера в управляющем контуре Argo CD:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-worker-prod-01
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
type: Opaque
stringData:
  name: "worker-prod-01"
  server: "https://192.168.10.50:6443"
  config: |
    {
      "bearerToken": "eyJhGciOi...",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "LS0tLS1CRUdJTi..."
      }
    }
```

```bash
kubectl apply -f cluster-secret.yaml
# → result: secret/cluster-worker-prod-01 created

# Проверка статуса подключения к кластеру
argocd cluster list
# → result:
# SERVER                          NAME            STATUS      MESSAGE
# https://kubernetes.default.svc  in-cluster      Successful  
# https://192.168.10.50:6443      worker-prod-01  Successful
```

#### 3. Принцип наименьших привилегий (Namespace-Scoped Multi-Cluster):
Если целевой кластер принадлежит сторонней команде или находится в DMZ, выдача роли `cluster-admin` недопустима. Argo CD поддерживает ограничение доступа заданным списком пространств имен:
1. Вместо `ClusterRoleBinding` на целевом кластере создаются `Role` и `RoleBinding` строго в разрешенных неймспейсах (например, `apps-prod`, `apps-stage`).
2. В секрете кластера в поле `namespaces` явно фиксируется перечень доступных зон:
```yaml
stringData:
  name: "worker-dmz-01"
  server: "https://192.168.20.50:6443"
  namespaces: "apps-prod,apps-stage"
  config: |
    {
      "bearerToken": "..."
    }
```

#### 4. Сетевые барьеры On-Premise (NAT, DMZ, Firewall):
Argo CD по умолчанию использует **Push-модель**: под `argocd-application-controller` инициирует TCP-соединение на порт `6443` API-сервера целевого кластера.
- Если целевой кластер находится за NAT или межсетевым экраном, запрещающим входящие подключения к `6443`:
  1. Организуется постоянный L3-туннель (WireGuard, IPsec) между сетью управления и сетью кластера.
  2. Публикуется защищенный реверс-прокси (HAProxy / Envoy с mTLS) для проксирования запросов к API-серверу.
  3. Для полностью изолированных анклавов используется альтернатива: запуск автономного экземпляра Argo CD внутри целевого контура (Pull-модель), читающего общий Git-репозиторий.

---

### Сценарий 9: Шардирование контроллера (Controller Sharding)

При росте числа управляемых приложений (более 500) или кластеров (более 10) один экземпляр `argocd-application-controller` может упираться в лимиты CPU/Memory или задерживать цикл реконсиляции.

**1. Конфигурация в `argocd-cmd-params-cm`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Алгоритм распределения: round-robin или legacy (по кластерам)
  controller.sharding.algorithm: "round-robin"
```

**2. Масштабирование контроллера в StatefulSet:**
В официальном Helm-чарте шардирование активируется масштабированием `controller.replicas`:
```bash
kubectl scale statefulset argocd-application-controller -n argocd --replicas=3
# → result: statefulset.apps/argocd-application-controller scaled
```

Каждый под получает переменную окружения `ARGOCD_CONTROLLER_SHARD` с номером реплики (0, 1, 2) и флаг `--replicas 3`, обрабатывая строго свою часть приложений.

**3. Проверка распределения шардов:**
```bash
argocd admin cluster stats
# → result:
# SHARD  CLUSTERS  APPLICATIONS
# 0      3         180
# 1      3         175
# 2      4         192
```

---

### Сценарий 10: Установка в полностью изолированном контуре (Offline / Air-Gapped)

В закрытых датацентрах без прямого выхода в Интернет развертывание выполняется через локальное зеркало.

**1. Перечень обязательных контейнерных образов (v3.5+):**
- `quay.io/argoproj/argocd:v3.5.x` (основной образ для server, repo-server, controller)
- `quay.io/argoproj/argocd-applicationset:v3.5.x`
- `docker.io/redis:7.2.x-alpine`
- `docker.io/haproxy:2.8.x-alpine` (для redis-ha)
- `ghcr.io/dexidp/dex:v2.41.x`

**2. Скрипт синхронизации с внутренним Harbor:**
```bash
REGISTRY="harbor.corp.internal/base-images"

for IMG in "quay.io/argoproj/argocd:v3.5.4" "docker.io/redis:7.2.4-alpine"; do
  skopeo copy "docker://${IMG}" "docker://${REGISTRY}/$(basename ${IMG})"
done
# → result: Copying blob... Copying config... Writing manifest...
```

**3. Подготовка Helm-чарта в OCI:**
```bash
helm pull argo/argo-cd --version 7.7.x
helm push argo-cd-7.7.x.tgz oci://harbor.corp.internal/charts/
# → result: Pushed: harbor.corp.internal/charts/argo-cd:7.7.x
```

**4. Развертывание из внутреннего OCI-источника:**
```bash
helm upgrade --install argocd oci://harbor.corp.internal/charts/argo-cd \
  --namespace argocd \
  --set global.image.repository="harbor.corp.internal/base-images/argocd" \
  --set redis-ha.redis.image.repository="harbor.corp.internal/base-images/redis" \
  -f values-airgapped.yaml \
  --server-side
```

---

### Сценарий 11: Регламент планового обновления Argo CD (Upgrade Runbook)

Обновление мажорных и минорных версий (например, v2.14 на v3.x или v3.4 на v3.5) в продуктивной HA-инсталляции требует строгого соблюдения этапов для исключения прерывания GitOps-доставки.

#### Этап 1: Предварительная подготовка и аудит
1. **Изучение Release Notes:** Проверьте список `Breaking Changes`, устаревших флагов CLI и измененных схем CRD.
2. **Обязательное создание резервной копии метаданных:**
```bash
# Экспорт всех конфигураций, секретов, приложений и проектов Argo CD
kubectl exec -n argocd -it deploy/argocd-server -- argocd-util export > /tmp/argocd-pre-upgrade-backup.yaml
# → result: Backup completed successfully
```

#### Этап 2: Обновление CRD через Server-Side Apply
Объем схем CRD Argo CD (`applications.argoproj.io`, `applicationsets.argoproj.io`) превышает лимит клиентской аннотации `kubectl.kubernetes.io/last-applied-configuration` (256 КБ). Стандартный `kubectl apply -f crds.yaml` завершится фатальной ошибкой `metadata.annotations: Too long`.

```bash
# Применение схем новой версии strictly через Server-Side Apply
kubectl apply --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/crds.yaml
# → result: customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io configured
# → result: customresourcedefinition.apiextensions.k8s.io/applicationsets.argoproj.io configured
# → result: customresourcedefinition.apiextensions.k8s.io/appprojects.argoproj.io configured
```

#### Этап 3: Пошаговое обновление рабочей нагрузки в HA-режиме
При использовании официального Helm-чарта обновление выполняется командой `helm upgrade` с флагом `--server-side`:

```bash
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --version 7.7.x \
  -f values-ha.yaml \
  --server-side
# → result: Release "argocd" has been upgraded.
```

Внутренняя последовательность RollingUpdate контроллеров:
1. `redis-ha` (Sentinel / HAProxy) — обновление кэширующего слоя с сохранением кворума.
2. `argocd-repo-server` — подтягивает новые бинарные версии Kustomize/Helm и CMP-плагинов.
3. `argocd-application-controller` — переподключается к K8s API и перечитывает обновленные CRD.
4. `argocd-server` и `argocd-dex-server` — обновляют UI и gRPC/REST API эндпоинты.

#### Этап 4: Валидация и сброс кэша
```bash
# Проверка соответствия версий компонентов
argocd version
# → result:
# argocd: v3.5.4+...
# argocd-server: v3.5.4+...

# Проверка отсутствия ошибок в контроллере
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100 | grep -iE "error|fatal"

# Принудительный сброс устаревшего кэша в Redis и запуск реконсиляции
argocd app list -o name | xargs -r -n1 argocd app get --hard-refresh > /dev/null
```

#### Этап 5: План экстренного отката (Emergency Rollback)
Если в новой версии обнаружен регресс или несовместимость CMP-плагинов:
```bash
# Просмотр истории релизов
helm history argocd -n argocd

# Откат на стабильную ревизию
helm rollback argocd <previous-revision> -n argocd --server-side
# → result: Rollback release argocd to <previous-revision> success
```

---

### Сценарий 12: Декларативная базовая конфигурация (`argocd-cm`, `argocd-cmd-params-cm`, `argocd-rbac-cm`)

Ключевые системные настройки Argo CD задаются тремя ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  url: "https://argocd.corp.internal"
  application.instanceLabelKey: "argocd.argoproj.io/instance"
  # Настройка таймаута сверки (по умолчанию 180s)
  timeout.reconciliation: "180s"
  # Включение локальных пользователей
  accounts.deployer: apiKey
  accounts.auditor: login
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Права для сервисного аккаунта deployer (CI/CD)
    p, role:deployer, applications, sync, */*, allow
    p, role:deployer, applications, get, */*, allow
    g, deployer, role:deployer

    # Права для группы безопасности auditors
    p, role:auditor, applications, get, */*, allow
    p, role:auditor, logs, get, */*, allow
    g, auditor, role:auditor
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  server.insecure: "true"
  controller.status.processors: "20"
  controller.operation.processors: "10"
  repo.server.timeout.seconds: "120"
```

Применение:
```bash
kubectl apply -f argocd-core-configs.yaml
# → result: configmap/argocd-cm configured
# → result: configmap/argocd-rbac-cm configured
# → result: configmap/argocd-cmd-params-cm configured
```

## Операции и команды

Сводная таблица основных административных команд сопровождения Argo CD:

| Команда | Назначение | Пример использования | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| `argocd login` | Аутентификация в API-сервере | `argocd login <host> --username admin` | `Context '<host>' updated` |
| `argocd version` | Проверка версии CLI и сервера | `argocd version` | Вывод версий клиента и сервера |
| `argocd repo add` | Регистрация Git или Helm репозитория | `argocd repo add <git-url> --ssh-private-key-path id_rsa` | `Repository '<git-url>' added` |
| `argocd repo list` | Список зарегистрированных репозиториев | `argocd repo list` | Таблица с URL, TYPE, STATUS (Successful) |
| `argocd cluster add` | Регистрация нового кластера K8s | `argocd cluster add <context-name> --name <name>` | `Cluster '<api-url>' added` |
| `argocd cluster list` | Просмотр подключенных кластеров | `argocd cluster list` | Таблица с адресами кластеров и статусом связи |
| `argocd admin settings rbac validate` | Синтаксическая валидация RBAC | `argocd admin settings rbac validate` | `Policy syntax OK` |
| `argocd admin cluster stats` | Статистика по шардам и кластерам | `argocd admin cluster stats` | Распределение приложений по шардам |
| `kubectl wait` | Ожидание доступности подов | `kubectl wait --for=condition=available deploy/argocd-server -n argocd` | `condition met` |
| `redis-cli ping` | Проверка доступности кэша Redis | `kubectl exec -n argocd deploy/argocd-redis -- redis-cli ping` | `PONG` |

## Диагностика и устранение неисправностей

### Ошибка 1: Ошибка размера аннотации при установке CRD
- **Симптом:** При выполнении `kubectl apply -f .../crds.yaml` команда завершается с ошибкой:
  `The CustomResourceDefinition "applications.argoproj.io" is invalid: metadata.annotations: Too long: must have at most 262144 bytes`
- **Причина:** Клиентский `kubectl apply` пытается сохранить предыдущее состояние манифеста в аннотацию `kubectl.kubernetes.io/last-applied-configuration`, размер которой превышает жесткий лимит etcd в 256 КБ.
- **Диагностика:** Попытка повторного применения без SSA завершается с тем же сообщением.
- **Решение:** Применять CRD исключительно с флагом Server-Side Apply:
  ```bash
  kubectl apply --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/crds.yaml
  # → result: customresourcedefinition.apiextensions.k8s.io/applications.argoproj.io configured
  ```

---

### Ошибка 2: Ошибка верификации TLS при клонировании Git (`x509: certificate signed by unknown authority`)
- **Симптом:** При создании `Application` статус синхронизации переходит в `ComparisonError`:
  `rpc error: code = Unknown desc = Get "https://gitlab.corp.internal/...": x509: certificate signed by unknown authority`
- **Причина:** Поды `argocd-repo-server` не имеют корневого сертификата доверенного корпоративного CA.
- **Диагностика:**
  ```bash
  kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server --tail=50 | grep -i "x509"
  # → result: x509: certificate signed by unknown authority
  ```
- **Решение:** Создать ConfigMap `argocd-tls-certs-cm` с сертификатом CA и привязать к пространству имен `argocd`:
  ```bash
  kubectl -n argocd create configmap argocd-tls-certs-cm \
    --from-file=corp-ca.crt=/path/to/root-ca.crt \
    --dry-run=client -o yaml | kubectl apply -f -
  kubectl rollout restart deployment/argocd-repo-server -n argocd
  ```

---

### Ошибка 3: Бесконечный редирект (HTTP 307 Redirect Loop) в веб-интерфейсе
- **Симптом:** При попытке открыть URL в браузере страница бесконечно перезагружается, либо выдается `ERR_TOO_MANY_REDIRECTS`.
- **Причина:** Ingress-контроллер выполняет SSL-терминацию и передает трафик на `argocd-server` по HTTP, а `argocd-server` считает соединение незащищенным и принудительно возвращает HTTP 307 Redirect на `https://`.
- **Диагностика:**
  ```bash
  curl -I http://argocd.corp.internal
  # → result: HTTP/1.1 307 Temporary Redirect
  # → result: Location: https://argocd.corp.internal/
  ```
- **Решение:** Запустить `argocd-server` с флагом `--insecure` (в Helm `server.extraArgs: ["--insecure"]` или `configs.params.server.insecure: true`), сообщив серверу, что TLS завершается на внешнем балансировщике.

---

### Ошибка 4: Невозможность входа администратора после утери или сброса пароля
- **Симптом:** Команда `argocd login` возвращает `Invalid username or password`, а секрет `argocd-initial-admin-secret` удален.
- **Причина:** Рассинхронизация или утеря хэша `admin.password` в секрете `argocd-secret`.
- **Диагностика:**
  ```bash
  kubectl get secret argocd-secret -n argocd -o jsonpath="{.data.admin\.password}"
  # → result: пусто либо устаревший хэш
  ```
- **Решение:** Сгенерировать новый bcrypt-хэш и обновить системный секрет напрямую:
  ```bash
  NEW_BCRYPT=$(htpasswd -nbBC 10 "" "NewEmergencyPass123!" | tr -d ':\n')
  kubectl -n argocd patch secret argocd-secret -p "{\"stringData\": {\"admin.password\": \"$NEW_BCRYPT\", \"admin.passwordMtime\": \"$(date -u +%FT%T%Z)\"}}"
  # → result: secret/argocd-secret patched
  ```

---

### Ошибка 5: Сбой Redis HA / Sentinel Failover
- **Симптом:** Веб-интерфейс выдает `Internal Server Error`, в логах `argocd-server` и `argocd-repo-server` появляются ошибки: `dial tcp: lookup redis-ha-haproxy: no such host` или `READONLY You can't write against a read only replica`.
- **Причина:** Сбой мастера Redis, зависание Sentinel quorum или отсутствие Persistent Volume для пода Redis.
- **Диагностика:**
  ```bash
  kubectl get pods -n argocd -l app.kubernetes.io/name=redis-ha
  # → result: поды Redis в статусе CrashLoopBackOff или Pending

  # Проверка текущего мастера в Sentinel
  kubectl exec -it -n argocd argocd-redis-ha-server-0 -c sentinel -- redis-cli -p 26379 sentinel get-master-addr-by-name argocd-master
  # → result: IP мастера
  ```
- **Решение:** Проверить доступность PVC и StorageClass для Redis. Если кворум Sentinel разорван, перезапустить стейтфулсет Redis HA:
  ```bash
  kubectl rollout restart statefulset/argocd-redis-ha-server -n argocd
  ```

---

### Ошибка 6: `argocd-repo-server` OOMKilled при сборке тяжелых манифестов
- **Симптом:** Приложения переходят в статус `Unknown`, в событиях пода фиксируется `OOMKilled` (Exit Code 137).
- **Причина:** Рендеринг объемных Helm-чартов или монорепозиториев Kustomize с десятками оверлеев потребляет больше памяти, чем задано в `resources.limits`.
- **Диагностика:**
  ```bash
  kubectl describe pod -n argocd -l app.kubernetes.io/name=argocd-repo-server | grep -E 'Last State|Exit Code'
  # → result: Last State: Terminated, Exit Code: 137, Reason: OOMKilled
  ```
- **Решение:** Увеличить лимиты памяти в `values.yaml` (минимум 2–4 GiB на под в продуктивных средах) и настроить переменную окружения `ARGOCD_EXEC_TIMEOUT` до 180s.

## Лучшие практики и регламент обслуживания

### Отказоустойчивость и сайзинг в On-Premise
1. **Распределение реплик:** Всегда активируйте `podAntiAffinity` для компонентов `server`, `repo-server` и `redis-ha`, чтобы экземпляры распределялись по разным физическим нодам кластера.
2. **PodDisruptionBudget (PDB):** Устанавливайте `minAvailable: 1` для предотвращения одновременного вывода реплик из строя при регламентных работах и обновлении узлов K8s.
3. **Автономность контроллера:** Для `argocd-application-controller` задавайте `requests` и `limits` по CPU в соотношении 1:2, чтобы не допускать дросселирования (CPU throttling) в момент массовых событий синхронизации.

### Hardening безопасности
1. **Деактивация локального `admin`:** После интеграции с корпоративным SSO (GitLab/Keycloak) полностью отключите локальную учетную запись администратора в `argocd-cm`:
   ```yaml
   data:
     admin.enabled: "false"
   ```
2. **Защита файловой системы:** Включайте `readOnlyRootFilesystem: true` и запуск от непривилегированного пользователя (`runAsNonRoot: true`, UID 999) во всех подах Argo CD.
3. **Сетевые политики (NetworkPolicies):** Изолируйте namespace `argocd`. Входящий трафик к `argocd-server` разрешайте только от Ingress Controller, а доступ к порту Redis (6379) — исключительно изнутри namespace `argocd`.

### Регламент полного удаления и очистки ресурсов (Clean Uninstallation)

При выводе стенда из эксплуатации или повторном бутстрапе кластера соблюдайте строгий порядок очистки, чтобы избежать зависания неймспейсов из-за финалайзеров (`finalizers`).

**1. Удаление всех объектов `Application` с удалением финалайзеров:**
```bash
# Снятие финалайзеров, если ресурсы не удаляются штатно
kubectl get applications -n argocd -o jsonpath='{.items[*].metadata.name}' | xargs -r -n1 kubectl patch application -n argocd -p '{"metadata":{"finalizers":null}}' --type=merge
kubectl delete applications -n argocd --all --timeout=60s
# → result: application.argoproj.io "..." deleted
```

**2. Удаление Helm-релиза:**
```bash
helm uninstall argocd -n argocd
# → result: release "argocd" uninstalled
```

**3. Удаление CRD и связанных ресурсов:**
```bash
kubectl delete crd -l app.kubernetes.io/part-of=argocd
# → result: customresourcedefinition.apiextensions.k8s.io "applications.argoproj.io" deleted
# → result: customresourcedefinition.apiextensions.k8s.io "applicationsets.argoproj.io" deleted
# → result: customresourcedefinition.apiextensions.k8s.io "appprojects.argoproj.io" deleted
```

**4. Удаление пространства имен и остаточных PVC:**
```bash
kubectl delete namespace argocd
# → result: namespace "argocd" deleted
```

## Ограничения и граничные условия

1. **Лимиты Server-Side Apply:** При наличии нескольких систем, управляющих одним объектом, возможны конфликты field ownership. Для Argo CD рекомендуется явный флаг `ServerSideApply=true` в `syncOptions`.
2. **Масштабирование Redis:** Вертикальный предел одного узла Redis в HA-режиме — порядка 5 000–8 000 приложений. Для сверхкрупных инсталляций (10 000+ приложений) требуется переход на Redis Cluster с шардированием ключей.
3. **Лимиты Git API при активном опросе:** По умолчанию Argo CD опрашивает Git каждые 3 минуты (`timeout.reconciliation: 180s`). В монорепозиториях с сотнями приложений это может исчерпать лимиты Git-сервера. Решение — настройка Webhooks от GitLab/Gitea в `argocd-server`.
4. **Сетевые задержки при Multi-Cluster управлении:** При межкластерном latency более 100 мс время выполнения sync loop существенно возрастает. Рекомендуется размещать локальные инстансы Argo CD в каждом удаленном датацентре либо оптимизировать таймауты `argocd-cmd-params-cm`.

- [Argo CD: Паттерн App of Apps и структура GitOps-репозиториев](./argocd_app_of_apps.md) — Иерархическое управление приложениями и бутстрап кластера.
- [Argo CD: Интеграция с Kustomize](./kustomize_integration.md) — Оверлеи, Kustomize Components, флаги сборки и подмена образов.
- [Argo CD: Интеграция с Helm](./helm_integration.md) — Управление Helm-чартами, параметрами и OCI-реестрами.
- [Прогрессивная доставка в GitOps](../Concepts/progressive_delivery_gitops.md) — Canary и Blue-Green развертывания с Argo Rollouts и Flagger.
- [Управление секретами и шифрование в GitOps](../secrets_encryption.md) — Практика SOPS, age, Sealed Secrets и External Secrets.
- [Argo CD: Обзор архитектуры системы](./argocd_overview.md) — Базовая концепция, компоненты и цикл реконсиляции.
- [Argo CD: Настройка SSO через GitLab](./argocd_sso_gitlab.md) — Детальное руководство по интеграции OIDC и групп.
- [Argo CD: Синхронизация и её политики](./synchronization.md) — Параметры автоматической синхронизации, prune и self-heal.
- [Argo CD: Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md) — Метрики Prometheus, ServiceMonitor и дашборды Grafana.
- [Argo CD: Custom Tooling и плагины](./argocd_custom_tooling.md) — Настройка CMP v2 sidecar для генерации манифестов.
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Настройка ролей, прав и политик в `argocd-rbac-cm`.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Проекты, квоты и разграничение доступа команд.
- [Disaster Recovery и резервное копирование](./argocd_disaster_recovery.md) — Бэкап манифестов, секретов и восстановление после сбоев.
- [Безопасность и hardening](./argocd_security_hardening.md) — GPG-подписи, NetworkPolicies и Pod Security Standards.
- [Мультитенантность в Argo CD](./argocd_multi_tenancy.md) — Паттерны изоляции команд и инфраструктурных контуров.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — Cascading deletion, orphan resources и finalizers.
- [GitOps-мозг: Управление политиками](../Concepts/gitops-policy-management.md) — Централизованное управление кластерами и политиками.
