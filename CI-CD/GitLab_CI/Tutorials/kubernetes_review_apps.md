# Настройка динамических окружений (Review Apps) с Kubernetes

**Актуально для:** GitLab 19.4.x / Kubernetes 1.37.x / cert-manager 1.21.x / Helm 4.x (3.14+) / GitLab Agent for Kubernetes (KAS) v19.x

## Определения

**Review App** — временное, изолированное окружение, автоматически создаваемое для каждой ветки (Merge Request). Позволяет тестировать изменения в реальных условиях до слияния (Merge) в основную ветку.

**GitLab Agent for Kubernetes (KAS)** — основной механизм интеграции, обеспечивающий безопасный доступ пайплайнов к кластеру через **CI/CD Tunnel**. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**.

**Эфемерный Namespace (Ephemeral Namespace)** — временное пространство имен в Kubernetes, в которое разворачивается Review App. Оно должно быть удалено вместе с окружением для предотвращения «засорения» кластера.

**Wildcard DNS & Ingress** — конфигурация, позволяющая автоматически направлять трафик на динамические URL (например, `https://feature-123.review.example.com`).

**Wildcard Certificate** — SSL/TLS сертификат, действующий для всех поддоменов определенного уровня (например, `*.review.example.com`). Обычно выпускается через Let's Encrypt с использованием DNS-01 challenge.

**auto_stop_in** — параметр директивы `environment`, задающий время неактивности, после которого окружение автоматически останавливается и удаляется. Максимальное значение — 30 дней.

**deployment_tier** — категория окружения (`production`, `staging`, `testing`, `development`). Для Review Apps рекомендуется значение `testing`, чтобы корректно рассчитывать DORA-метрики. Подробнее см. **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**.

**environment_scope** — область действия переменных окружения. Позволяет изолировать секреты между `production`, `staging` и динамическими окружениями.

**CI_ENVIRONMENT_NAME** — предопределенная переменная, содержащая имя окружения (например, `review/feature-branch`).

**CI_ENVIRONMENT_SLUG** — предопределенная переменная, содержащая URL-safe slug окружения (например, `review-feature-branch`).

## Основные концепции

### Предварительные требования (Prerequisites)

Для работы Review Apps в Kubernetes-кластере должны быть установлены и настроены следующие компоненты:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **GitLab** | 18.4+ (рекомендуется 19.4.x) | Поддержка `environment:kubernetes`, KAS и CI/CD Tunnel. |
| **GitLab Agent for Kubernetes (KAS)** | v19.x (встроен в GitLab) | Защищенный туннель CI/CD Tunnel. Подробнее см. **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)**. |
| **Ingress Controller** | nginx-ingress (community) 1.30+ или F5 NGINX Ingress Controller 5.6+ / Traefik 3.7+ | Маршрутизация трафика по `Host` заголовкам для динамических URL. |
| **cert-manager** | 1.16+ (рекомендуется 1.21.1) | Автоматическое создание SSL/TLS сертификатов (Wildcard или per-MR). |
| **Helm** | 3.14+ (4.x supported) | Управление наборами ресурсов (чартами) для Review Apps. |
| **kubectl** | 1.37+ | Управление кластером из задач пайплайна. |
| **Docker** | 29.x | Сборка и публикация образов приложения. |

#### Проверка готовности кластера

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Client Version: v1.37.x
# → Server Version: v1.37.x

# Проверка наличия Ingress Controller
kubectl get pods -n ingress-nginx
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-xxx                1/1     Running   0          30d

# Проверка cert-manager
kubectl get pods -n cert-manager
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → cert-manager-xxx                           1/1     Running   0          30d
# → cert-manager-cainjector-xxx                1/1     Running   0          30d
# → cert-manager-webhook-xxx                   1/1     Running   0          30d

# Проверка GitLab Agent
kubectl get pods -n gitlab-agent
# → NAME                        READY   STATUS    RESTARTS   AGE
# → agentk-xxx                  1/1     Running   0          15d
```

### Архитектура и поток данных

Использование динамических окружений в Kubernetes строится на защищенном туннеле между GitLab и кластером:

```
Merge Request #123
       │
       ▼
GitLab CI Pipeline (build → deploy → cleanup)
       │
       ▼
GitLab Agent for Kubernetes (CI/CD Tunnel)
       │
       ▼
Kubernetes API Server
       │
       ▼
Ephemeral Namespace (review-123)
  ├── Deployment (backend)
  ├── Service
  ├── Ingress (review-123.review.example.com)
  └── Secret (DB credentials)
       │
       ▼
https://review-123.review.example.com
```

Ключевые моменты:
- **Нет статических kubeconfig:** доступ к кластеру осуществляется через туннель Агента.
- **Изоляция:** каждое MR-окружение разворачивается в отдельный Namespace.
- **Жизненный цикл:** создается при открытии MR, удаляется при закрытии или по `auto_stop_in`.

### Четыре ключевых принципа

1.  **Изоляция (Isolation):** Каждое MR-окружение разворачивается в свой Namespace. Это обеспечивает полную изоляцию ресурсов (Pods, Services, Secrets) и позволяет применять специфичные квоты и политики безопасности.
2.  **Динамическая маршрутизация (Dynamic Routing):** Ingress-контроллер (Nginx, Traefik, Istio) автоматически создает правила маршрутизации на основе `Host` заголовков.
3.  **Автоматическое управление жизненным циклом (Lifecycle Management):** Использование хуков `on_stop` и параметра `auto_stop_in` в GitLab CI для автоматического удаления ресурсов в кластере при закрытии MR или неактивности.
4.  **Безопасность (Security):** Доступ к кластеру осуществляется через GitLab Agent, что исключает передачу статических `kubeconfig` файлов и токенов в переменные окружения пайплайна.

Общие принципы описаны в **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)**.

## Практические сценарии

### Сценарий 1: Регистрация с Docker Executor (Рекомендуемый)

Современный подход исключает использование статических токенов `ClusterAdmin`. Доступ осуществляется через защищенный туннель Агента.

```yaml
stages:
  - build
  - deploy
  - cleanup

build_image:
  stage: build
  image: docker:29.0
  services:
    - docker:29.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG .
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG

deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com \
        --set image.tag=$CI_COMMIT_REF_SLUG
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID

stop_review:
  stage: cleanup
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    GIT_STRATEGY: none
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm uninstall review-$CI_COMMIT_REF_SLUG --namespace $NAMESPACE || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual
```

### Сценарий 2: Мульти-сервисное приложение (Frontend + Backend + DB)

Для реальных приложений часто нужно развернуть несколько компонентов одновременно.

```yaml
stages:
  - build
  - deploy
  - cleanup

build_backend:
  stage: build
  image: docker:29.0
  services:
    - docker:29.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE/backend:$CI_COMMIT_REF_SLUG ./backend
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE/backend:$CI_COMMIT_REF_SLUG

build_frontend:
  stage: build
  image: docker:29.0
  services:
    - docker:29.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE/frontend:$CI_COMMIT_REF_SLUG ./frontend
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker push $CI_REGISTRY_IMAGE/frontend:$CI_COMMIT_REF_SLUG

deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    RELEASE_NAME: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - |
      kubectl create secret generic review-db-credentials \
        --namespace $NAMESPACE \
        --from-literal=username=review_user \
        --from-literal=password=$(openssl rand -base64 16) \
        --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install $RELEASE_NAME ./charts/full-app \
        --namespace $NAMESPACE \
        --set backend.image.tag=$CI_COMMIT_REF_SLUG \
        --set frontend.image.tag=$CI_COMMIT_REF_SLUG \
        --set postgresql.auth.existingSecret=review-db-credentials \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com \
        --wait --timeout 5m
    - kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --timeout=120s
    - kubectl wait --for=condition=ready pod -l app=frontend -n $NAMESPACE --timeout=120s
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID

stop_review:
  stage: cleanup
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    RELEASE_NAME: "review-$CI_COMMIT_REF_SLUG"
    GIT_STRATEGY: none
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm uninstall $RELEASE_NAME --namespace $NAMESPACE || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: $CI_MERGE_REQUEST_ID
      when: manual
```

### Сценарий 3: Интеграция с HashiCorp Vault для секретов

Для безопасной передачи секретов в Review App без хранения их в переменных GitLab.

```yaml
deploy_with_vault:
  stage: deploy
  image: alpine/k8s:1.37.0
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.example.com
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
    VAULT_ADDR: "https://vault.example.com"
    VAULT_ROLE: "gitlab-review-apps"
  before_script:
    - apk add --no-cache vault jq
    - |
      VAULT_TOKEN=$(vault write -field=token auth/jwt/login \
        role=$VAULT_ROLE \
        jwt=$VAULT_ID_TOKEN)
      export VAULT_TOKEN
    - |
      DB_CREDS=$(vault kv get -format=json secret/review-apps/db-credentials)
      DB_USER=$(echo $DB_CREDS | jq -r '.data.data.username')
      DB_PASS=$(echo $DB_CREDS | jq -r '.data.data.password')
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - |
      kubectl create secret generic review-secrets \
        --namespace $NAMESPACE \
        --from-literal=db-user="$DB_USER" \
        --from-literal=db-password="$DB_PASS" \
        --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set secrets.existingSecret=review-secrets \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

Подробнее см. **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)**.

### Сценарий 4: Seed данных (Миграции и начальное заполнение)

Для тестирования Review App с реальными данными.

```yaml
deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
    - |
      echo "Ожидание готовности PostgreSQL..."
      kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=postgresql \
        -n $NAMESPACE --timeout=180s
    - |
      kubectl exec -n $NAMESPACE deploy/my-app-backend -- \
        python manage.py migrate --no-input
    - |
      kubectl exec -n $NAMESPACE deploy/my-app-backend -- \
        python manage.py seed_review_data --clear
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

> **Важно:** Не используйте продакшн-данные для Review Apps. Используйте анонимизированные или синтетические данные.

### Сценарий 5: Использование `environment:kubernetes` (GitLab 18.4+)

Начиная с GitLab 18.4, блок `environment:kubernetes` позволяет привязать окружение напрямую к namespace и агенту, обеспечивая визуализацию статуса ресурсов в UI GitLab.

```yaml
deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    kubernetes:
      namespace: $NAMESPACE
      agent: my-group/my-project:my-agent
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Сценарий 6: Чистый kubectl / Kustomize (без Helm)

Для простых приложений можно обойтись без Helm, используя `kubectl apply` или Kustomize.

```yaml
deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    # Вариант A: kubectl apply с переопределением namespace
    - kubectl apply -k ./k8s/overlays/review \
        --namespace $NAMESPACE
    # Вариант B: прямые манифесты с подстановкой переменных
    - envsubst < ./k8s/base/all.yaml | kubectl apply -n $NAMESPACE -f -
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Сценарий 7: Передача переменных через `dotenv` artifacts

Используйте `dotenv` для передачи переменных (например, URL приложения) между стадиями без повторного вычисления.

```yaml
stages:
  - deploy
  - test

.deploy_review:
  stage: deploy
  image: alpine/k8s:1.37.0
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
    - echo "REVIEW_URL=https://$CI_COMMIT_REF_SLUG.review.example.com" >> review.env
  artifacts:
    reports:
      dotenv: review.env
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID

test_review:
  stage: test
  image: curlimages/curl:latest
  script:
    - curl -f $REVIEW_URL/healthz
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Сценарий 8: Параллельный деплой через `parallel:matrix`

Для тестирования нескольких конфигураций одновременно (например, разные версии зависимостей).

```yaml
deploy_review_matrix:
  stage: deploy
  image: alpine/k8s:1.37.0
  parallel:
    matrix:
      - DB_VERSION: "postgresql-16"
        CACHE_VERSION: "redis-7"
  variables:
    NAMESPACE: "review-$CI_COMMIT_REF_SLUG-$DB_VERSION"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -
    - helm upgrade --install review-$CI_COMMIT_REF_SLUG ./charts/my-app \
        --namespace $NAMESPACE \
        --set postgresql.image.tag=$DB_VERSION \
        --set redis.image.tag=$CACHE_VERSION \
        --set ingress.host=$CI_COMMIT_REF_SLUG.review.example.com
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    deployment_tier: testing
    on_stop: stop_review
    auto_stop_in: 1 day
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

### Сценарий 9: Автоматическая очистка забытых окружений (CronJob)

Даже с `auto_stop_in` некоторые окружения могут остаться в кластере (отключенный MR, ошибки пайплайна). Настройте CronJob для периодической очистки namespace старше N дней.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: review-apps-cleanup
  namespace: kube-system
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: review-apps-cleanup
          containers:
          - name: kubectl
            image: alpine/k8s:1.37.0
            command:
            - /bin/sh
            - -c
            - |
              kubectl get namespaces -l purpose=review -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | while read ns; do
                AGE=$(kubectl get ns $ns -o jsonpath='{.metadata.creationTimestamp}')
                # Удалить namespace старше 7 дней
                if [ $(date -d "$AGE" +%s) -lt $(date -d "7 days ago" +%s) ]; then
                  echo "Deleting stale namespace: $ns"
                  kubectl delete namespace $ns --ignore-not-found
                fi
              done
          restartPolicy: OnFailure
```

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: review-apps-cleanup
  namespace: kube-system
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: review-apps-cleanup
rules:
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: review-apps-cleanup
subjects:
- kind: ServiceAccount
  name: review-apps-cleanup
  namespace: kube-system
roleRef:
  kind: ClusterRole
  name: review-apps-cleanup
  apiGroup: rbac.authorization.k8s.io
```

## После регистрации: Структура config.toml

GitLab Agent (agentk) конфигурируется через файл `.gitlab/agents/<name>/config.yaml` в репозитории. Для Review Apps важно ограничить область доступа:

```yaml
api_version: v2
gitops:
  # Опционально: интеграция с Flux для GitOps-сценариев
  enabled: false
user_access:
  access_as:
    agent: {}
  projects:
  - id: path/to/project
    default_namespace: review-$CI_COMMIT_REF_SLUG
    # Или используйте wildcard, если агент обслуживает несколько проектов
    # default_namespace: review-*
```

### Пример multi-runner конфигурации

Если в кластере зарегистрировано несколько агентов (например, один для Review Apps, другой для Production), укажите нужный в переменной `KUBE_CONTEXT`:

```yaml
variables:
  KUBE_CONTEXT: "path/to/project:review-agent" # Для Review Apps
  # KUBE_CONTEXT: "path/to/project:prod-agent" # Для Production
```

## Безопасность и изоляция

### 1. Сетевая изоляция (Network Policies)

Review Apps часто содержат экспериментальный код. Ограничьте их доступ к внутренней сети кластера, чтобы предотвратить обращение к Production или Staging базам данных.

```yaml
# k8s/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-internal-only
  namespace: review-feature-branch
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8
```

### 2. RBAC для GitLab Agent

Агент должен иметь доступ только к определенным пространствам имен. В конфигурации агента (`config.yaml`) ограничьте область действия:

```yaml
user_access:
  access_as:
    agent: {}
  projects:
  - id: path/to/project
    default_namespace: review-*
```

### 3. Pod Security Standards (PSS)

Примените уровень `restricted` или `baseline` к namespace Review Apps через `PodSecurity` admission:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: review-feature-branch
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

## Работа с базами данных

Review Apps по умолчанию должны быть **Stateless**. Если приложению требуется БД, используйте один из подходов:

### 1. Эфемерная БД в составе Helm-чарта

Самый надежный способ изоляции. БД разворачивается вместе с приложением и удаляется при очистке.

```yaml
# charts/my-app/values.yaml
postgresql:
  enabled: true
  auth:
    database: myapp_db
    username: user
  persistence:
    enabled: false
```

### 2. Общая база данных (Shared Database)

Использование одного инстанса БД (например, в Staging) с созданием уникальных схем/логических БД для каждого MR.
- **Плюсы:** Экономия ресурсов кластера.
- **Минусы:** Сложность очистки (нужны дополнительные скрипты для `DROP DATABASE`) и риск влияния Review Apps на стабильность Staging БД.

## Отладка и мониторинг

### Просмотр логов

Для отладки Review Apps используйте `kubectl` через туннель агента или интерфейс GitLab (Environments -> Review App -> Terminal).

```bash
kubectl logs -f -l app=my-app -n review-$CI_COMMIT_REF_SLUG
```

### Мониторинг ресурсов

В Grafana рекомендуется создать отдельный Dashboard для Review Apps, отфильтрованный по префиксу Namespace `review-*`. Это поможет выявить «зависшие» окружения, которые потребляют ресурсы.

### Prometheus Alerting

Настройте алерты на длительное существование Review Apps (TTL > 24 часа) и превышение квот:

```yaml
# Пример PrometheusRule для alertmanager
groups:
- name: review-apps
  rules:
  - alert: ReviewAppStale
    expr: kube_namespace_created > 0 and on(namespace) kube_namespace_labels{namespace=~"review-.*"} unless kube_pod_status_phase{namespace=~"review-.*", phase="Running"}
    for: 2h
    labels:
      severity: warning
    annotations:
      summary: "Review App namespace {{ $labels.namespace } is stale"
```

## Технические нюансы и ограничения

### Квоты ресурсов (Resource Quotas)

Динамические окружения могут быстро исчерпать ресурсы кластера. **Обязательно** устанавливайте `ResourceQuota` и `LimitRange` в namespaces для Review Apps:

```yaml
# k8s/quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: review-quota
spec:
  hard:
    requests.cpu: "500m"
    requests.memory: "1Gi"
    limits.cpu: "1000m"
    limits.memory: "2Gi"
```

### Горизонтальное масштабирование (HPA)

В Review Apps рекомендуется **отключать** HPA или устанавливать минимальные лимиты (например, `maxReplicas: 1`), чтобы избежать неконтролируемого роста потребления ресурсов при тестах.

### Graceful Shutdown

Убедитесь, что ваше приложение корректно обрабатывает `SIGTERM`. При удалении Namespace Kubernetes завершает все поды. Если приложение не успеет закрыть соединения, это может привести к ошибкам в логах или повреждению данных в общих БД.

### Удаление Registry-образов

После удаления Review App и слияния MR, в Container Registry остаются временные образы. Настройте **Registry Cleanup Policy** в настройках проекта для удаления тегов, не соответствующих `main` или `tags`.

### DNS propagation delay

При создании Ingress для нового Namespace DNS-запись может не распространиться мгновенно. Используйте `nslookup` или `dig` с несколькими попытками, или добавьте ожидание в пайплайн:

```yaml
- |
  for i in $(seq 1 10); do
    nslookup $CI_COMMIT_REF_SLUG.review.example.com && break
    sleep 5
  done
```

### Certificate rate limits

Let's Encrypt накладывает лимиты на выпуск сертификатов. При массовом создании Review Apps используйте один Wildcard сертификат для всех поддоменов, а не отдельный сертификат на каждый MR.

## Валидация и проверка

После настройки Review Apps выполните следующие проверки:

### 1. Проверка доступа к кластеру

```bash
kubectl config use-context $KUBE_CONTEXT
kubectl cluster-info
# → Kubernetes control plane is running at https://...
```

### 2. Проверка Wildcard DNS

```bash
nslookup feature-branch.review.example.com
# → Address: 203.0.113.50
```

### 3. Проверка SSL/TLS

```bash
openssl s_client -connect feature-branch.review.example.com:443 -servername feature-branch.review.example.com < /dev/null 2>/dev/null | openssl x509 -noout -dates
# → notBefore=Jan  1 00:00:00 2025 GMT
# → notAfter=Apr  1 00:00:00 2025 GMT
```

### 4. Проверка развернутого приложения

```bash
kubectl get pods -n review-feature-branch
# → NAME                                READY   STATUS    RESTARTS   AGE
# → my-app-backend-xxx                  1/1     Running   0          5m
# → my-app-frontend-xxx                 1/1     Running   0          5m

kubectl get svc -n review-feature-branch
# → NAME            TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
# → my-app-backend  ClusterIP   10.96.xxx.xxx  <none>        8000/TCP   5m
# → my-app-frontend ClusterIP   10.96.xxx.xxx  <none>        80/TCP     5m
```

### 5. Проверка Ingress

```bash
kubectl get ingress -n review-feature-branch
# → NAME             CLASS   HOSTS                                ADDRESS        PORTS     AGE
# → my-app-ingress   nginx   feature-branch.review.example.com    203.0.113.50   80, 443   5m
```

### 6. Проверка в GitLab UI

1. Перейдите в **Operate > Environments**.
2. Убедитесь, что окружение `review/feature-branch` отображается со статусом **Available**.
3. Нажмите на URL окружения — приложение должно открыться в браузере.

## Очистка

### Ручная очистка

```bash
kubectl get namespaces -l purpose=review
kubectl delete namespace review-stale-branch --ignore-not-found
```

### Автоматическая очистка

Используйте `auto_stop_in` в `.gitlab-ci.yml` и CronJob (см. Сценарий 9) для удаления namespace старше N дней.

### Очистка Secret'ов

Убедитесь, что `stop_review` удаляет не только Helm-релиз, но и связанные Secrets:

```yaml
stop_review:
  stage: cleanup
  script:
    - helm uninstall $RELEASE_NAME --namespace $NAMESPACE || true
    - kubectl delete secret review-db-credentials -n $NAMESPACE --ignore-not-found || true
    - kubectl delete namespace $NAMESPACE --ignore-not-found
```

## Решение проблем (Troubleshooting)

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pod stuck in Pending** | Недостаточно ресурсов в кластере или не выполняются Node Affinity/Tolerations. | Проверьте `kubectl describe pod <pod> -n <ns>`. Убедитесь, что `ResourceQuota` не исчерпаны. |
| **Pod CrashLoopBackOff** | Приложение падает при запуске (ошибка конфигурации, отсутствие БД, неверный образ). | Проверьте логи: `kubectl logs <pod> -n <ns> --previous`. Убедитесь, что образ доступен и переменные заданы. |
| **Ingress не создает правила** | Отсутствует `ingress.class` или Ingress Controller не установлен. | Добавьте аннотацию `kubernetes.io/ingress.class: nginx` или убедитесь, что Ingress Controller запущен. |
| **SSL-сертификат не выпускается** | cert-manager не может пройти DNS-01 challenge (неверные DNS-записи или API-токен). | Проверьте логи cert-manager: `kubectl logs -n cert-manager deploy/cert-manager`. Убедитесь, что Wildcard DNS-запись настроена. |
| **GitLab Agent не подключается** | KAS не установлен или туннель заблокирован. | Проверьте статус агента: `kubectl get pods -n gitlab-agent`. Проверьте `config.yaml` агента. |
| **Helm install timeout** | Один из подов не становится Ready (долгий запуск, неверные readiness probes). | Увеличьте `--timeout`. Проверьте `kubectl describe pod` для выявления причины. |
| **Namespace не удаляется** | Existing Finalizers или ResourceQuota блокируют удаление. | Проверьте finalizers: `kubectl get ns <ns> -o yaml`. Временно удалите Quota перед очисткой. |
| **Review App доступна по HTTP, но не по HTTPS** | Wildcard сертификат не привязан к Ingress или отсутствует `tls` секция. | Добавьте `tls` секцию в Ingress и убедитесь, что Secret с сертификатом существует. |
| **Auto-stop не работает** | Отсутствует `on_stop` в `environment` или задача остановки не найдена. | Убедитесь, что `stop_review` существует в `.gitlab-ci.yml` и имеет `environment: action: stop`. |
| **Данные не seed'ятся** | Миграции выполняются до готовности БД или seed-скрипт отсутствует в образе. | Добавьте `kubectl wait` для БД перед миграциями. Проверьте, что seed-команда доступна в контейнере. |
| **ResourceQuota блокирует деплой** | Review App требует больше ресурсов, чем разрешено квотой. | Увеличьте `requests`/`limits` в `ResourceQuota` или уменьшите потребление приложения. |
| **Кэш Helm не обновляется** | `helm upgrade` использует устаревшую версию чарта. | Используйте `helm repo update` перед деплоем или `--force` для принудительного обновления. |
| **Namespace не создается (AlreadyExists)** | Предыдущий запуск пайплайна не завершил очистку. | Добавьте `|| true` к команде создания namespace или проверьте состояние namespace перед созданием. |
| **DNS не резолвит новый поддомен** | TTL кэша DNS-провайдера или неверная Wildcard-запись. | Проверьте `dig` с внешнего резолвера. Убедитесь, что A-запись `*.review.example.com` указывает на правильный IP. |
| **Vault: Permission denied** | Роль Vault не настроена на `bound_claims` для проекта/ветки. | Проверьте политику Vault и параметры `bound_claims` в роли `gitlab-review-apps`. |

## Рекомендации по эксплуатации (Best Practices)

### Оптимизация ресурсов

1. **Всегда устанавливайте `ResourceQuota`** для namespaces Review Apps, чтобы предотвратить неконтролируемое потребление ресурсов.
2. **Отключайте HPA** для Review Apps или ограничивайте `maxReplicas: 1`.
3. **Используйте `auto_stop_in`** с разумными значениями (1–24 часа) для автоматической очистки неактивных окружений.
4. **Настройте Registry Cleanup Policy** для удаления временных образов после слияния MR.

### Безопасность

1. **Network Policies** — ограничьте доступ Review Apps к внутренней сети кластера.
2. **RBAC** — ограничьте права GitLab Agent только необходимыми namespace (`review-*`).
3. **Pod Security Standards** — примените `restricted` уровень к namespace Review Apps.
4. **Secrets** — используйте HashiCorp Vault или Kubernetes Secrets вместо переменных GitLab CI.
5. **Audit Events** — мониторьте создание и удаление namespace через GitLab Audit Events.

### Мониторинг

1. **Grafana Dashboard** — создайте отдельный дашборд для Review Apps с фильтрацией по `review-*` namespace.
2. **Prometheus Alerting** — настройте алерты на длительное существование Review Apps (TTL > 24h).
3. **Namespace Labels** — используйте labels `app`, `team`, `managed-by: gitlab-review` для атрибуции ресурсов.

### Очистка

1. **Ручная очистка** — периодически проверяйте `kubectl get namespaces -l purpose=review` и удаляйте забытые окружения.
2. **Автоматическая очистка** — используйте CronJob в кластере для удаления namespace старше N дней.
3. **Очистка Secret'ов** — убедитесь, что `stop_review` удаляет не только Helm-релиз, но и связанные Secrets.

## Граничные случаи

### Ограничения и нюансы

1. **Параллельные MR в одну ветку:** При одновременно открытых MR для одной ветки namespace может конфликтовать. Используйте `$CI_COMMIT_REF_SLUG` или `$CI_MERGE_REQUEST_IID` для уникальности.
2. **DNS propagation delay:** При создании Ingress для нового Namespace DNS-запись может не распространиться мгновенно. Используйте ожидание или проверку резолвинга в пайплайне.
3. **Certificate rate limits:** Let's Encrypt накладывает лимиты на выпуск сертификатов. При массовом создании Review Apps используйте один Wildcard сертификат для всех поддоменов.
4. **Namespace quota exhaustion:** При большом количестве одновременных Review Apps может исчерпаться квота кластера. Установите `ResourceQuota` и ограничьте `maxReplicas`.
5. **Finalizers и удаление namespace:** Некоторые ресурсы (например, PVC, Finalizers) могут блокировать удаление namespace. Убедитесь, что Helm-чарт не создает PersistentVolumeClaim или используйте `helm uninstall` с флагом `--keep-history` перед `kubectl delete namespace`.
6. **Concurrent MRs и имя namespace:** Если два MR имеют одинаковый `CI_COMMIT_REF_SLUG` (например, при rebase), namespace может уже существовать. Используйте `$CI_MERGE_REQUEST_IID` для абсолютной уникальности.
7. **Deletion race condition:** Если MR закрывается во время активного деплоя, задача `stop_review` может удалить namespace до завершения деплоя. Используйте `resource_group` или проверку существования namespace перед удалением.

## Дополнительная информация

### Смотрите также

- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка GitLab Agent и CI/CD Tunnel (основной источник по интеграции).
- **[Окружения и развертывания в GitLab CI](../Concepts/environments_and_deployments.md)** — общие концепции, tiers, защищенные окружения, DORA-метрики.
- **[Интеграция GitLab CI с HashiCorp Vault](vault_kubernetes_integration.md)** — управление секретами для Review Apps.
- **[GitLab Flow](../Tutorials/gitlab_flow.md)** — стратегия ветвления, в рамках которой используются Review Apps.
