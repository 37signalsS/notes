# Интеграция GitLab CI/CD с Kubernetes

## Определения

**GitLab Agent for Kubernetes (KAS)** — основной и единственный рекомендуемый метод интеграции GitLab с кластерами Kubernetes (начиная с версий 17.x/18.x). Система состоит из серверного компонента (**GitLab KAS**) и агента (**agentk**), работающего внутри кластера по Pull-модели. Агент устанавливается как Deployment в.namespace `gitlab-agent` и поддерживает защищенный GRPC-туннель к серверу GitLab, что исключает необходимость экспонирования API-сервера кластера наружу.

**CI/CD Tunnel** — защищенный GRPC-туннель, позволяющий CI/CD-задачам GitLab взаимодействовать с API кластера Kubernetes напрямую. Исключает необходимость хранения `KUBECONFIG` в переменных и экспонирования API кластера в интернет. Туннель создается при вызове `kubectl config use-context $KUBE_CONTEXT` внутри задачи пайплайна и действует только на время выполнения задачи.

**Workload Identity Federation (OIDC/WIF)** — модель безопасности Zero Trust, при которой GitLab Runner получает временный JWT-токен (`id_tokens`) для федеративной аутентификации в облаках (AWS EKS, GKE, Azure AKS) или локальных сервисах (Vault, Kubernetes API) без использования статических секретов.

**GitLab Workspaces** — функционал (v16.x–19.x) для предоставления разработчикам облачных сред разработки (Cloud IDE) внутри кластера Kubernetes, управляемых через Агент. Каждый Workspace разворачивается как отдельный Pod с предустановленными инструментами разработки.

**`.gitlab/agents/<name>/config.yaml`** — файл конфигурации агента, определяющий правила доступа (какие проекты и группы могут использовать туннель), параметры имперсонации, Remote Development и другие настройки. Размещается в репозитории, где зарегистрирован агент.

**Network Policy** — объект Kubernetes, ограничивающий сетевой трафик между подами на уровне кластера. Используется для изоляции агента и ограничения доступа пайплайнов к ресурсам кластера.

**Pod Security Standards (PSS)** — механизм Kubernetes (замена устаревших PodSecurityPolicy), определяющий три уровня безопасности (`privileged`, `baseline`, `restricted`) для подов в конкретном namespace. Рекомендуется применять к namespace, где работает агент.

## Основные концепции

### Предварительные требования

Для корректной интеграции GitLab с Kubernetes необходимы следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **GitLab** | 16.0+ (рекомендуется 18.x+) | Встроенный KAS, поддержка `id_tokens` и CI/CD Tunnel. |
| **GitLab Agent for Kubernetes (KAS)** | 1.0+ (встроен в GitLab 16.0+) | Серверный компонент для связи с агентами. |
| **Kubernetes** | 1.27+ | Целевой кластер для деплоя приложений. |
| **Helm** | 3.12+ | Установка агента через чарт и управление релизами. |
| **kubectl** | 1.27+ | Управление кластером из задач пайплайна. |
| **GitLab Runner** | 16.0+ | Выполнение задач CI/CD (Docker или Kubernetes Executor). |

#### Проверка готовности кластера

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Client Version: v1.29.x
# → Server Version: v1.29.x

# Проверка наличия Helm
helm version --short
# → v3.14.x+gxxx

# Проверка доступа к API
kubectl cluster-info
# → Kubernetes control plane is running at https://...
```

### Архитектура интеграции

Интеграция строится на двух моделях взаимодействия:

```text
┌─────────────────────────────────────────────────────────┐
│                    GitLab Server                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐   │
│  │ CI/CD    │    │ GitLab   │    │ GitLab Agent     │   │
│  │ Pipeline │◄──►│ KAS      │◄──►│ Server (KAS)     │   │
│  └────┬─────┘    └──────────┘    └────────┬─────────┘   │
│       │                                    │             │
│       │ id_tokens (OIDC)                   │ GRPC        │
└───────┼────────────────────────────────────┼─────────────┘
        │                                    │
        ▼                                    ▼
┌───────────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                        │
│  ┌────────────────┐    ┌──────────────────────────────┐   │
│  │ CI/CD Tunnel   │◄──►│ agentk (Deployment)          │   │
│  │ (temporary)    │    │  Namespace: gitlab-agent      │   │
│  └───────┬────────┘    └──────────────────────────────┘   │
│          │                                                │
│          ▼                                                │
│  ┌────────────────┐                                       │
│  │ App Pods       │                                       │
│  │ (Deploy, Svc)  │                                       │
│  └────────────────┘                                       │
└───────────────────────────────────────────────────────────┘
```

### Стратегии интеграции (GitLab 18.x/19.x)

| Метод | Тип | Технология | Основной сценарий |
| :--- | :--- | :--- | :--- |
| **CI/CD Tunnel** | Push-модель | KAS + `kubectl`/`helm` | Динамический деплой, администрирование, Review Apps. |
| **GitOps (Native)** | Pull-модель | KAS + Git Sync | Простая синхронизация манифестов из репозитория. |
| **GitOps (Argo CD)** | Pull-модель | Argo CD + GitLab UI | Enterprise-стандарт с визуализацией состояния в GitLab. |
| **OIDC (WIF)** | Push-модель | `id_tokens` + IAM | Максимальная безопасность в публичных облаках. |

### Контексты доступа и иерархия

Связь пайплайна с кластером устанавливается через переменную `KUBE_CONTEXT`.
**Формат:** `путь/к/проекту-конфигурации:имя-агента`
**Пример:** `ops/k8s-infra:production-agent`

Если агент находится в отдельном «инфраструктурном» проекте, необходимо разрешить доступ в его `config.yaml`:
```yaml
# .gitlab/agents/production-agent/config.yaml
ci_access:
  projects:
    - id: web-apps/frontend
  groups:
    - id: backend-services
```

#### Иерархия доступа

GitLab Agent поддерживает три уровня имперсонации (access_as), определяющие, с какими правами пайплайн обращается к кластеру:

1.  **`agent: {}`** (по умолчанию) — пайплайн использует права ServiceAccount самого агента. Наиболее широкий доступ, рекомендуется только для административных задач.
2.  **`user: {}`** — пайплайн получает права пользователя GitLab, запустившего пайплайн. RBAC кластера должен иметь RoleBinding для этого пользователя.
3.  **`service_account: { name: ..., namespace: ... }`** — пайплайн использует права указанного ServiceAccount в конкретном namespace. Максимально гранулярный контроль.

## Установка и настройка GitLab Agent

### Шаг 1: Регистрация агента в GitLab

Способ 1: Через UI GitLab
1. Перейдите в **Operate > Kubernetes clusters > Connect a cluster**.
2. Укажите имя агента (например, `prod-agent`) и group/project, где будет храниться конфигурация.
3. Скопируйте команду установки (содержит временный токен регистрации).

Способ 2: Через API
```bash
curl --header "PRIVATE-TOKEN: <your_token>" \
  --data "name=prod-agent" \
  "https://gitlab.example.com/api/v4/projects/<project_id>/cluster_agents"
# → {"id":1,"name":"prod-agent","config":{"..."},"created_at":"..."}
```

### Шаг 2: Установка через Helm

```bash
# Добавление репозитория GitLab
helm repo add gitlab https://charts.gitlab.io
helm repo update

# Установка агента в кластер
helm install gitlab-agent gitlab/gitlab-agent \
  --namespace gitlab-agent \
  --create-namespace \
  --set token=<registration_token> \
  --set config.kasAddress=wss://kas.gitlab.example.com \
  --set config.agentId=<agent_id>

# Проверка статуса
kubectl get pods -n gitlab-agent
# → NAME                        READY   STATUS    RESTARTS   AGE
# → agentk-xxx                  1/1     Running   0          2m
```

Параметры Helm-чарта:

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `token` | Токен регистрации агента в GitLab | Обязательный |
| `config.kasAddress` | Адрес сервера KAS (WebSocket) | Обязательный |
| `config.agentId` | Уникальный ID агента | Автоматический |
| `resources.limits.cpu` | Лимит CPU для пода агента | `200m` |
| `resources.limits.memory` | Лимит памяти для пода агента | `256Mi` |
| `nodeSelector` | Ноды для запуска агента | `{}` |
| `tolerations` | Толерантности для планирования | `[]` |

### Шаг 3: Конфигурация доступа (config.yaml)

Создайте файл `.gitlab/agents/<agent-name>/config.yaml` в репозитории:

```yaml
# .gitlab/agents/prod-agent/config.yaml

# Доступ для CI/CD пайплайнов (CI/CD Tunnel)
ci_access:
  projects:
    - id: my-group/web-app          # Доступ для конкретного проекта
    - id: my-group/api-service
      access_as:
        user: {}                     # Имперсонация через пользователя
  groups:
    - id: my-group/backend-services  # Доступ для всей группы

# Доступ для пользователей (Web IDE, Terminal)
user_access:
  access_as:
    agent: {}
  projects:
    - id: my-group/web-app
  default_namespace: development

# Remote Development (GitLab Workspaces)
remote_development:
  enabled: true
  dns_zone: workspaces.example.com
```

### Шаг 4: Верификация подключения

```bash
# Проверка логов агента
kubectl logs -n gitlab-agent -l app=gitlab-agent --tail=50
# → {"level":"info","msg":"Connected to KAS","kas_address":"wss://..."}

# Проверка статуса через GitLab CLI (опционально)
glab cluster agent list --project my-group/infra
# → ID  NAME         STATUS
# → 1   prod-agent   connected
```

## Практические сценарии

### Сценарий 1: Деплой через CI/CD Tunnel с имперсонацией (RBAC)

Использование механизма `access_as` для ограничения прав пайплайна до уровня пользователя.

```yaml
# В пайплайне приложения (.gitlab-ci.yml)
deploy_app:
  stage: deploy
  image:
    name: line/kubectl-kustomize:latest
  variables:
    KUBE_CONTEXT: "ops/infra:my-agent"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl apply -f manifests/ --namespace $CI_PROJECT_NAME
```

**Настройка агента (config.yaml):**
```yaml
ci_access:
  projects:
    - id: my-app/repo
      access_as:
        user: {} # Пайплайн получит права пользователя, запустившего его
```

**Настройка RBAC в Kubernetes (для имперсонации user):**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gitlab-ci-user-binding
  namespace: my-app
subjects:
  - kind: User
    name: "gitlab-user@example.com"  # Имя пользователя GitLab
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deployment-manager
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployment-manager
  namespace: my-app
rules:
  - apiGroups: ["apps", ""]
    resources: ["deployments", "services", "configmaps", "secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Сценарий 2: Аутентификация в облаке AWS через OIDC

Исключение использования статических `AWS_ACCESS_KEY_ID`.

```yaml
deploy:aws:
  image: amazon/aws-cli:latest
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.com
  variables:
    ROLE_ARN: "arn:aws:iam::123456789012:role/GitLabDeployer"
  script:
    - >
      export $(printf "AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s"
      $(aws sts assume-role-with-web-identity
      --role-arn ${ROLE_ARN}
      --role-session-name "GitLabCI-${CI_PIPELINE_ID}"
      --web-identity-token ${GITLAB_OIDC_TOKEN}
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]'
      --output text))
    - aws eks update-kubeconfig --name prod-cluster
    - helm upgrade --install my-app ./chart
```

### Сценарий 3: Интеграция с Argo CD (Enterprise GitOps)

GitLab v18.x обеспечивает нативную поддержку Argo CD с отображением ресурсов в UI.

1.  **Bootstrap Argo CD** в кластере через Helm (рекомендуется через GitLab CI/CD Tunnel):

    ```bash
    # Добавление официального репозитория Argo CD
    helm repo add argo https://argoproj.github.io/argo-helm
    helm repo update

    # Установка Argo CD в namespace argocd
    helm install argo-cd argo/argo-cd \
      --namespace argocd \
      --create-namespace \
      --set server.service.type=ClusterIP \
      --wait --timeout 5m
    # → NAME: argo-cd
    # → LAST DEPLOYED: ...
    # → STATUS: deployed
    ```

2.  **Создание Application CR** для синхронизации манифестов из GitLab:

    ```yaml
    # manifest/argocd-application.yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: prod-cluster-apps
      namespace: argocd
      finalizers:
        - resources-finalizer.argocd.argoproj.io
    spec:
      project: default
      source:
        repoURL: https://gitlab.example.com/my-group/infra-gitops.git
        targetRevision: main
        path: clusters/prod-cluster
        directory:
          recurse: true
      destination:
        server: https://kubernetes.default.svc
        namespace: default
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
    ```

    ```bash
    # Применение Application через CI/CD Tunnel
    kubectl apply -f manifest/argocd-application.yaml
    # → application.argoproj.io/prod-cluster-apps created
    ```

3.  **Визуализация**: В интерфейсе GitLab перейдите в **Operate > Kubernetes clusters**. Выберите ваш агент для просмотра состояния синхронизации Argo CD Applications.

### Сценарий 4: Деплой в несколько namespace с RBAC-изоляцией

Развертывание микросервисов в разные namespace с уникальными правами доступа для каждого пайплайна.

```yaml
stages:
  - build
  - deploy

# Сборка образа
build:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

# Деплой в development (автоматически)
deploy_dev:
  stage: deploy
  image: alpine/k8s:1.30.0
  variables:
    KUBE_CONTEXT: "infra/k8s:dev-agent"
    TARGET_NS: "development"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $TARGET_NS --dry-run=client -o yaml | kubectl apply -f -
    - |
      helm upgrade --install $CI_PROJECT_NAME ./chart \
        --namespace $TARGET_NS \
        --set image.repository=$CI_REGISTRY_IMAGE \
        --set image.tag=$CI_COMMIT_SHA \
        --set ingress.host=dev.${CI_PROJECT_NAME}.example.com \
        --wait --timeout 3m
  environment:
    name: development
    url: https://dev.${CI_PROJECT_NAME}.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"

# Деплой в production (ручной, с другим агентом и namespace)
deploy_prod:
  stage: deploy
  image: alpine/k8s:1.30.0
  variables:
    KUBE_CONTEXT: "infra/k8s:prod-agent"
    TARGET_NS: "production"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - |
      helm upgrade --install $CI_PROJECT_NAME ./chart \
        --namespace $TARGET_NS \
        --set image.repository=$CI_REGISTRY_IMAGE \
        --set image.tag=$CI_COMMIT_SHA \
        --set ingress.host=${CI_PROJECT_NAME}.example.com \
        --wait --timeout 5m
    - kubectl rollout status deployment/$CI_PROJECT_NAME -n $TARGET_NS --timeout=300s
  environment:
    name: production
    url: https://${CI_PROJECT_NAME}.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Настройка агента для multi-namespace (config.yaml):**
```yaml
ci_access:
  projects:
    - id: my-group/web-app
      access_as:
        service_account:
          name: ci-deployer
          namespace: development   # Для dev-окружения
    - id: my-group/web-app
      access_as:
        service_account:
          name: ci-deployer
          namespace: production    # Для prod-окружения
```

### Сценарий 5: Доставка манифестов в Argo CD через API GitLab CI

В некоторых инфраструктурах GitLab CI используется не только для сборки, но и для динамической генерации и доставки манифестов в Argo CD. Этот паттерн применяется, когда стандартный GitOps-подход (Argo CD следит за репозиторием) недостаточно гибок.

**Принцип работы:**
1. GitLab CI собирает артефакт (Helm-чарт, Kustomize overlay, JSON-манифест).
2. Пайплайн вызывает Argo CD API для создания/обновления Application.
3. Argo CD рендерит манифест и применяет его в кластере.

```yaml
stages:
  - build
  - package
  - deploy

build:
  stage: build
  script:
    - ./build.sh

package:
  stage: package
  script:
    - helm package ./chart --version $CI_COMMIT_TAG
    - helm lint ./chart
  artifacts:
    paths:
      - *.tgz

deploy_to_argocd:
  stage: deploy
  image: curlimages/curl:latest
  script:
    - |
      # Получение токена Argo CD
      ARGOCD_TOKEN=$(curl -s -X POST https://argocd.example.com/api/v1/session \
        -d '{"username":"admin","password":"'"$ARGOCD_ADMIN_PASSWORD"'"}' \
        | jq -r '.token')
      
      # Создание/обновление Application
      curl -s -X POST https://argocd.example.com/api/v1/applications \
        -H "Authorization: Bearer $ARGOCD_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
          "metadata": {"name": "'$CI_PROJECT_NAME'"},
          "spec": {
            "project": "default",
            "source": {
              "repoURL": "https://gitlab.example.com/group/'$CI_PROJECT_NAME'.git",
              "targetRevision": "HEAD",
              "path": "helm/$CI_PROJECT_NAME",
              "helm": {
                "valueFiles": ["values-$CI_ENVIRONMENT_NAME.yaml"],
                "parameters": [
                  {"name": "image.tag", "value": "'$CI_COMMIT_SHORT_SHA'"}
                ]
              }
            },
            "destination": {
              "server": "https://kubernetes.default.svc",
              "namespace": "'$CI_PROJECT_NAME'"
            },
            "syncPolicy": {
              "automated": {"prune": true, "selfHeal": true},
              "syncOptions": ["CreateNamespace=true"]
            }
          }
        }'
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Важные нюансы:**
- **Секреты:** Токен Argo CD хранится в переменной проекта (`ARGOCD_ADMIN_PASSWORD`) или во внешнем менеджере секретов (Vault).
- **Идемпотентность:** Argo CD API идемпотентен — повторный вызов с теми же параметрами не создает дубликатов.
- **Валидация:** Перед `POST` выполните `helm lint` и `helm template` для проверки корректности чарта.
- **Ограничение:** Этот подход не подходит для сложных зависимостей между чартами, так как Argo CD не запускает `helm dependency build`. Убедитесь, что `Chart.lock` актуален.

**Альтернатива — Custom Tooling (CMP):**
Если требуется сложная генерация манифестов (QBEC, Jsonnet, Helmfile), используйте Config Management Plugins в Argo CD вместо прямых вызовов API из CI. Это изолирует логику генерации от пайплайна и позволяет Argo CD самостоятельно рендерить манифесты.

### Сценарий 6: Управление секретами через Vault и OIDC

Безопасная передача секретов в Kubernetes без хранения их в переменных GitLab.

```yaml
deploy_with_vault:
  stage: deploy
  image: alpine/k8s:1.30.0
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  variables:
    VAULT_ADDR: "https://vault.example.com"
    VAULT_ROLE: "gitlab-k8s-deployer"
    KUBE_CONTEXT: "infra/k8s:prod-agent"
  before_script:
    - apk add --no-cache vault jq kubectl
    # Аутентификация в Vault через OIDC
    - |
      export VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_ROLE \
        jwt=$VAULT_ID_TOKEN)
    # Получение секрета из Vault
    - |
      SECRET_JSON=$(vault kv get -format=json secret/prod/db-credentials)
      DB_USER=$(echo $SECRET_JSON | jq -r '.data.data.username')
      DB_PASS=$(echo $SECRET_JSON | jq -r '.data.data.password')
  script:
    - kubectl config use-context $KUBE_CONTEXT
    # Создание Kubernetes Secret из данных Vault
    - |
      kubectl create secret generic app-db-credentials \
        --namespace production \
        --from-literal=username="$DB_USER" \
        --from-literal=password="$DB_PASS" \
        --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install my-app ./chart --namespace production
```

### Сценарий 6: Настройка сред разработки (GitLab Workspaces)

1.  **Условие**: Наличие Ingress-контроллера с поддержкой Wildcard (например, `*.workspaces.example.com`).
2.  **Конфигурация агента**:
    ```yaml
    remote_development:
      enabled: true
      dns_zone: workspaces.example.com
    ```
3.  **Использование**: Разработчик может запустить Workspace непосредственно из Web IDE или раздела **Operate > Workspaces**.

## Безопасность и RBAC

### Принцип наименьших привилегий

Никогда не назначайте ServiceAccount агента роль `cluster-admin`. Используйте RoleBindings для ограничения доступа конкретными неймспейсами.

**Минимальный набор прав для ServiceAccount агента:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gitlab-agent-minimal
rules:
  # Доступ к подам агента (для самодиагностики)
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
  # Доступ к сервисам (для проверки connectivity)
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get", "list"]
  # Доступ к namespace (для проверки существования)
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list"]
  # Доступ к deployments и statefulsets (для деплоя)
  - apiGroups: ["apps"]
    resources: ["deployments", "statefulsets", "daemonsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Доступ к configmaps и secrets
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  # Доступ к services и ingresses
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Защита туннеля

Ограничивайте сетевой доступ `agentk` к KAS через Network Policies:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-agent-egress-only
  namespace: gitlab-agent
spec:
  podSelector:
    matchLabels:
      app: gitlab-agent
  policyTypes:
    - Egress
  egress:
    # Разрешить DNS
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Разрешить исходящий трафик к KAS (GitLab server)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
```

### Изоляция namespace для деплоев

Применение Pod Security Standards к namespace приложений:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### Имперсонация

Механизм `access_as` определяет, с какими правами пайплайн обращается к кластеру:

-   **`access_as: { agent: {} }`** (по умолчанию) — права ServiceAccount агента. Наиболее широкий доступ.
-   **`access_as: { user: {} }`** — права пользователя GitLab, запустившего пайплайн. Требует RoleBinding для пользователя в кластере.
-   **`access_as: { service_account: { name: ..., namespace: ... } }`** — права конкретного ServiceAccount. Рекомендуется для продакшена.

## Мониторинг и наблюдаемость

### Метрики агента

GitLab Agent экспонирует Prometheus-метрики на порту `8080` (по умолчанию):

```bash
# Просмотр метрик агента
kubectl port-forward -n gitlab-agent svc/gitlab-agent 8080:8080
curl http://localhost:8080/metrics
```

Ключевые метрики:

| Метрика | Описание | Целевое значение |
| :--- | :--- | :--- |
| `gitlab_agent_connections_total` | Общее количество активных соединений с KAS | > 0 (агент подключен) |
| `gitlab_agent_rpc_requests_total` | Количество RPC-запросов через туннель | Мониторинг роста |
| `gitlab_agent_rpc_request_duration_seconds` | Время выполнения RPC-запросов | p95 < 2s |
| `gitlab_agent_reconnects_total` | Количество переподключений к KAS | < 5/час |

### Логирование

```bash
# Просмотр логов агента (последние 100 строк)
kubectl logs -n gitlab-agent -l app=gitlab-agent --tail=100

# Фильтрация по уровню
kubectl logs -n gitlab-agent -l app=gitlab-agent | grep -i "error\|warn"

# Просмотр логов конкретного пода
kubectl logs -n gitlab-agent agentk-xxxxx-yyy
```

Типичные сообщения в логах:

| Уровень | Сообщение | Действие |
| :--- | :--- | :--- |
| `info` | `Connected to KAS` | Агент успешно подключился |
| `warn` | `Reconnecting to KAS` | Временная потеря связи, ожидается переподключение |
| `error` | `Failed to authenticate` | Проблема с токеном регистрации, проверьте `config.yaml` |
| `error` | `RBAC: forbidden` | Недостаточно прав ServiceAccount в кластере |

### Алерты (Prometheus/Alertmanager)

```yaml
# Пример правила алерта для Prometheus
groups:
  - name: gitlab-agent
    rules:
      - alert: GitLabAgentDisconnected
        expr: gitlab_agent_connections_total == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "GitLab Agent disconnected from KAS"
          description: "Agent in namespace {{ $labels.namespace }} has no active connections for 5 minutes."

      - alert: GitLabAgentHighReconnectRate
        expr: rate(gitlab_agent_reconnects_total[5m]) > 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Agent reconnecting frequently"
          description: "Agent reconnecting more than once every 5 minutes."
```

## Устранение неполадок (Troubleshooting)

### Типичные ошибки

-   **`Context not found`**:
    -   Пайплайн запущен в проекте, который не добавлен в `ci_access` агента.
    -   Имя проекта или агента в `KUBE_CONTEXT` указано неверно (чувствительно к регистру).
    -   Формат `KUBE_CONTEXT`: `group/project:agent-name` (без ведущего слэша).

-   **`GRPC: connection error`**:
    -   Проблема сетевой связности между `agentk` и GitLab KAS.
    -   Проверьте настройки прокси и доступность порта 443/wss.
    -   Убедитесь, что агент может разрешить DNS-имя KAS-сервера.

-   **`RBAC: forbidden`**:
    -   Права ServiceAccount агента в кластере недостаточны для выполнения `kubectl` команд.
    -   Проверьте логи агента: `kubectl logs -n gitlab-agent -l app=gitlab-agent`.
    -   Убедитесь, что RoleBinding/ClusterRoleBinding настроены корректно.

-   **`Agent token expired`**:
    -   Токен регистрации агента истек (по умолчанию 7 дней после создания).
    -   Пересоздайте токен через UI GitLab: **Operate > Kubernetes clusters > ваш агент > Revoke token**.

-   **`Namespace not found`**:
    -   Целевой namespace не существует в кластере.
    -   Добавьте `kubectl create namespace <name> --dry-run=client -o yaml | kubectl apply -f -` в скрипт деплоя.

-   **`Helm install/upgrade failed`**:
    -   Предыдущий релиз в состоянии `pending-upgrade`.
    -   Выполните `helm rollback <release-name> <revision>` и повторите попытку.

### Команды диагностики

```bash
# Внутри CI-задачи: проверка активных контекстов
kubectl config get-contexts
# → CURRENT   NAME                 CLUSTER          AUTHINFO         NAMESPACE
# → *         ops/infra:my-agent   ops/infra:...    ops/infra:...    default

# Проверка статуса агента в кластере
kubectl get pods -n gitlab-agent -o wide
# → NAME                        READY   STATUS    RESTARTS   AGE   IP
# → agentk-xxx-yyy              1/1     Running   0          15d   10.244.1.5

# Проверка логов агента (последние ошибки)
kubectl logs -n gitlab-agent -l app=gitlab-agent --tail=50 | grep -i error

# Проверка RBAC для ServiceAccount агента
kubectl auth can-i list deployments --namespace production --as=system:serviceaccount:gitlab-agent:gitlab-agent
# → yes / no

# Проверка доступа через CI/CD Tunnel (внутри задачи)
kubectl auth can-i get pods --namespace production
# → yes

# Проверка версии агента
kubectl get deployment -n gitlab-agent gitlab-agent -o jsonpath='{.spec.template.spec.containers[0].image}'
# → registry.gitlab.com/gitlab-org/cloud-native/agent/agentk:v17.x.x

# Проверка сетевой связности с KAS
kubectl exec -n gitlab-agent deploy/gitlab-agent -- wget -qO- --timeout=5 https://kas.gitlab.example.com/-/health
# → ok
```

## Обновление и обслуживание агента

### Обновление Helm-чарта

```bash
# Обновление репозитория
helm repo update

# Обзор доступных версий
helm search repo gitlab/gitlab-agent --versions
# → NAME                       CHART VERSION   APP VERSION   DESCRIPTION
# → gitlab/gitlab-agent        7.x.x           17.x.x       GitLab Agent for Kubernetes

# Обновление агента
helm upgrade gitlab-agent gitlab/gitlab-agent \
  --namespace gitlab-agent \
  --reuse-values

# Проверка после обновления
kubectl get pods -n gitlab-agent
kubectl logs -n gitlab-agent -l app=gitlab-agent --tail=20
```

### Обновление конфигурации агента

Изменения в `config.yaml` применяются автоматически при коммите в репозиторий, где зарегистрирован агент. Агент получает обновление через GRPC-туннель:

```bash
# Проверка текущей конфигурации агента
kubectl get configmap -n gitlab-agent -l app=gitlab-agent -o yaml

# Принудительное переподключение (при проблемах)
kubectl rollout restart deployment/gitlab-agent -n gitlab-agent
```

### Миграция с legacy-интеграций

Начиная с GitLab 18.0, поддержка legacy-интеграций Kubernetes на базе сертификатов прекращена. Процесс миграции:

1.  Установите GitLab Agent в кластер (раздел «Установка и настройка»).
2.  Зарегистрируйте агента в GitLab и настройте `config.yaml`.
3.  Обновите `.gitlab-ci.yml`: замените `KUBE_NAMESPACE` и `KUBE_TOKEN` на `KUBE_CONTEXT`.
4.  Удалите старые kubeconfig-секреты из переменных проекта.
5.  Проверьте работу пайплайнов в staging-окружении перед обновлением production.

### Backup и восстановление

```bash
# Экспорт конфигурации агента
kubectl get deployment -n gitlab-agent gitlab-agent -o yaml > agent-deployment-backup.yaml
kubectl get configmap -n gitlab-agent -l app=gitlab-agent -o yaml > agent-config-backup.yaml
kubectl get serviceaccount -n gitlab-agent gitlab-agent -o yaml > agent-sa-backup.yaml
kubectl get clusterrolebinding -l subject=gitlab-agent -o yaml > agent-cr-binding-backup.yaml

# Восстановление (после переустановки кластера)
kubectl apply -f agent-sa-backup.yaml
kubectl apply -f agent-config-backup.yaml
kubectl apply -f agent-deployment-backup.yaml
kubectl apply -f agent-cr-binding-backup.yaml
```

## Best Practices для продакшена

### Организация агентов

1.  **Один агент на окружение**: Используйте отдельного агента для dev, staging и production. Это обеспечивает изоляцию и позволяет применять разные RBAC-политики.
2.  **Инфраструктурный проект**: Храните конфигурацию агента в отдельном «инфраструктурном» проекте (`infra/k8s-agents`), а не в проекте приложения.
3.  **Именование**: Используйте осмысленные имена агентов (`prod-agent`, `staging-agent`, `dev-agent`).

### Безопасность

1.  **Имперсонация**: Всегда используйте `access_as: { user: {} }` или `access_as: { service_account: { ... } }` вместо `agent: {}` для пайплайнов приложений.
2.  **Network Policies**: Ограничьте egress агента только портом 443 (KAS) и DNS (порт 53).
3.  **Pod Security**: Применяйте `restricted` PSS к namespace, где работает агент.
4.  **Ротация токенов**: Регулярно обновляйте токены регистрации агента (раз в 90 дней).

### Надежность

1.  **Ресурсы**: Установите `resources.requests` и `resources.limits` для пода агента.
2.  **Tolerations и Affinity**: Настройте планирование агента на выделенные узлы control plane или infra-ноды.
3.  **Health checks**: Агент поддерживает GRPC health check на порту `50051` (по умолчанию).
4.  **Логирование**: Настройте сбор логов агента в централизованную систему (Loki, ELK).

### Производительность

1.  **Размер кластера**: Для кластеров с >100 нод рекомендуется установка нескольких экземпляров агента с round-robin балансировкой.
2.  **Тайм-ауты**: Увеличьте `--timeout` для Helm-операций в больших кластерах (5-10 минут).
3.  **Кэширование**: Используйте `HELM_CACHE_HOME` для кэширования Helm-чартов между запусками.

## Дополнительная информация

### См. также
-   **[Обзор GitLab Runner и Executor](./gitlab_ci_runners_executors.md)** — выбор между Kubernetes и Docker executors.
-   **[GitOps: Обзор методологии](../../../GitOps/GitOps_overview.md)** — принципы Pull-модели.
-   **[Интеграция GitLab CI и Vault](../Tutorials/vault_kubernetes_integration.md)** — использование OIDC для получения секретов.
