# Argo CD: Практическое руководство по установке и настройке

> **Актуальность (2026):** Argo CD версии v3.x является отраслевым стандартом. Основные изменения касаются обязательного использования **Server-Side Apply (SSA)** для установки CRD, интеграции контроллера **ApplicationSet** в ядро системы и поддержки **Gateway API** для публикации сервисов. Для продуктивных сред рекомендуется исключительно **HA-режим** (High Availability).

## Определения

**Установка Argo CD** — процесс развёртывания компонентов системы GitOps в Kubernetes-кластере, включающий установку определений ресурсов (CRD), сервисов управления, механизмов контроля доступа и систем кеширования.

**Высокая доступность (HA)** — конфигурация Argo CD, обеспечивающая отказоустойчивость через репликацию ключевых компонентов (API, Repo Server, Controller) и использование распределенного кеша Redis (Sentinel/Cluster).

**Server-Side Apply (SSA)** — нативный механизм Kubernetes для управления состоянием ресурсов на стороне сервера. В Argo CD v3.x является основным методом установки и синхронизации ресурсов, имеющих большой объем данных или управляемых несколькими контроллерами одновременно.

**ApplicationSet Controller** — компонент Argo CD, позволяющий массово создавать и обновлять объекты `Application` на основе шаблонов и генераторов (Git, List, Cluster, Matrix).

## Базовые концепции

### Компоненты системы

Архитектура Argo CD v3.x состоит из следующих сервисов:

| Компонент | Назначение |
| :--- | :--- |
| `argocd-server` | API и веб-интерфейс. Управляет RBAC, аутентификацией и визуализацией состояния приложений. |
| `argocd-repo-server` | Клонирование Git-репозиториев, работа с Helm-чартами и рендеринг манифестов (Kustomize, CMP). |
| `argocd-application-controller` | Основной цикл управления: отслеживает состояние (diff) и выполняет синхронизация (sync). |
| `argocd-applicationset-controller` | Оркестрация множества приложений (ApplicationSets). |
| `argocd-dex-server` | Прокси для интеграции с внешними провайдерами личности (OIDC, SAML, LDAP). |
| `argocd-redis` | Высокопроизводительный кеш для хранения состояния кластера и ускорения рендеринга. |
| `argocd-notifications-controller` | Обработка событий и отправка алертов (Slack, MSTeams, Telegram). |

### Способы развертывания

1. **Helm (Рекомендуемый для Production):** Обеспечивает гибкую параметризацию через `values.yaml` и простое управление жизненным циклом самого Argo CD.
2. **Kustomize / Manifests:** Прямое управление YAML-файлами. Подходит для простых инсталляций или когда Helm запрещен требованиями безопасности.
3. **Argo CD Operator:** Автоматизирует установку и обновление Argo CD, но вносит дополнительный слой абстракции.

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
```

**3. Установка:**
```bash
# Использование --server-side обязательно для установки объемных CRD v3.x
helm upgrade --install argocd argo/argo-cd \
    --namespace argocd --create-namespace \
    -f values.yaml --server-side
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

### Сценарий 5: Настройка доверенных TLS-сертификатов (Internal CA)

Если внутренние реестры используют самоподписанные сертификаты, добавьте их в доверенные на уровне Argo CD:

```bash
# 1. Создание ConfigMap с корневым сертификатом
kubectl -n argocd create configmap argocd-tls-certs-cm \
  --from-file=internal-root.ca=/path/to/root-ca.crt \
  -o yaml --dry-run=client | kubectl apply -f -

# 2. Сервис автоматически подмонтирует сертификаты из CM с соответствующим лейблом
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

### Сценарий 8: Установка в изолированном контуре (Offline/Air-gapped)

1.  **Перенос образов:** Скачайте все образы Argo CD и перенесите их в локальный реестр (например, Harbor).
2.  **Правка манифестов:** Используйте Kustomize для замены `image` и добавления `imagePullSecrets`.
3.  **Локальные репозитории:** Все внешние Helm-чарты должны быть зеркалированы во внутренний OCI-реестр.

## Технический справочник

### Рекомендации по ресурсам (HA-режим на 100 приложений)

| Компонент | CPU (Requests/Limits) | Memory (Requests/Limits) | Реплики |
| :--- | :--- | :--- | :--- |
| `argocd-application-controller` | 1 / 2 | 2Gi / 4Gi | 1-2 |
| `argocd-repo-server` | 500m / 1 | 1Gi / 2Gi | 3 |
| `argocd-server` | 200m / 500m | 512Mi / 1Gi | 3 |
| `argocd-redis` | 500m / 1 | 1Gi / 2Gi | 3 (Sentinel) |

### Пост-установочные проверки (Health Check)

1. **Поды:** `kubectl get pods -n argocd` (все `Running`).
2. **CRD:** `kubectl get crd | grep argoproj` (5+ ресурсов).
3. **API:** `curl -k https://argocd.example.com/healthz` (200 OK).
4. **Redis:** `kubectl exec -it -n argocd deployment/argocd-redis -- redis-cli ping` (должен вернуть `PONG`).

### Диагностика

```bash
# Статистика кластера и шардов
argocd admin cluster stats

# События контроллера
kubectl get events -n argocd --field-selector involvedObject.kind=Application

# Проверка mTLS между компонентами (v3.5+)
# Если включено global.tls.enabled=true, проверьте логи repo-server на наличие TLS handshake errors
```

## Дополнительная информация

### См. также

- [Argo CD: Обзор системы](./argocd_overview.md)
- [Argo CD: Настройка SSO через GitLab](./argocd_sso_gitlab.md) — детальная настройка OIDC.
- [Argo CD: Синхронизация и её политики](./synchronization.md)
- [Argo CD: Интеграция с Vault](./argocd_vault_integration.md)
- [Argo CD: Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md)
- [Argo CD: Custom Tooling и плагины](./argocd_custom_tooling.md)
- [Официальное руководство по HA](https://argo-cd.readthedocs.io/en/stable/operator-manual/high-availability/)
