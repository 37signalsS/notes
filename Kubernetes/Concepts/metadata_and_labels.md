# Метаданные, метки и аннотации в Kubernetes

## Определение

В Kubernetes каждый объект (Pod, Service, ConfigMap) содержит поле **`metadata`**, которое используется для его идентификации, организации и управления жизненным циклом. Основными инструментами структурирования и обогащения данных являются метки и аннотации.

*   **Метаданные (Metadata)** — системные данные, описывающие объект (имя, UID, версия ресурса). Хранятся в etcd и управляются API-сервером.
*   **Метки (Labels)** — пары «ключ-значение», используемые для **идентификации** и группировки объектов. Метки индексируются API-сервером и используются селекторами. Внутри etcd хранятся как инвертированный индекс для быстрого поиска.
*   **Аннотации (Annotations)** — пары «ключ-значение» для хранения **дополнительных данных**, не предназначенных для идентификации. Они не индексируются и не используются для поиска. Хранятся как есть, без структурирования.

### Архитектура хранения в etcd

```
etcd key: /registry/pods/<namespace>/<name>
    ↓
JSON-документ:
{
  "metadata": {
    "name": "web-abc123",
    "namespace": "default",
    "uid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "resourceVersion": "12345",
    "generation": 3,
    "creationTimestamp": "2025-01-15T10:30:00Z",
    "labels": { "app": "web", "env": "prod" },
    "annotations": { "description": "Web API" }
  },
  "spec": { ... }
}
```

Labels хранятся в том же JSON-документе, но API-сервер поддерживает **инвертированный индекс** для быстрого выполнения селекторов. При запросе `kubectl get pods -l app=web` API-сервер не сканирует все Pod'ы — он использует индекс для мгновенного поиска совпадений.

---

## Поля метаданных (Metadata Fields)

Помимо пользовательских меток и аннотаций, поле `metadata` содержит критически важные системные поля (заполняются API-сервером):

### Идентификация
*   **`name`**: Уникальное имя объекта в рамках одного **Namespace**. Для основной части ресурсов: от 1 до 253 символов, DNS-поддомен формат (буквы, цифры, `-`, `.`). Для Pod/ReplicaSet: до 63 символов (для автоматически генерируемых имен через `generateName`).
*   **`generateName`**: Префикс для автоматической генерации имени. API-сервер добавляет случайный суффикс (5 символов). Используется при создании Pod'ов через контроллеры.
*   **`namespace`**: Логическое пространство имен. Если не указано, используется `default`. Для Namespace-Scoped ресурсов определяет область видимости. Cluster-Scoped ресурсы (Node, Namespace, PersistentVolume) не имеют этого поля.
*   **`uid`**: Глобально уникальный идентификатор (UUID), генерируемый API-сервером при создании. Формат: RFC 4122. Не изменяется на протяжении жизненного цикла объекта. Используется в `ownerReferences` для связывания объектов.

### Управление версиями
*   **`resourceVersion`**: Версия объекта в etcd. Используется для **оптимистичной блокировки** (optimistic concurrency control). При обновлении объекта клиент должен передать текущий `resourceVersion` — если он изменился с момента чтения, API-сервер вернет ошибку `409 Conflict`. Не является числовым значением — это внутренний идентификатор etcd-ревизии.
*   **`generation`**: Номер версии спецификации объекта (`spec`). Увеличивается при каждом изменении `spec`. Поля `status` и `metadata` не влияют на `generation`. Используется контроллерами для определения, было ли изменение уже обработано (через `status.observedGeneration`).
*   **`selfLink`**: URL-путь к объекту (например, `/api/v1/namespaces/default/pods/web`). **Deprecated** начиная с v1.20 — может быть пустым в будущих версиях.

### Владение и жизненный цикл
*   **`ownerReferences`**: Список объектов-владельцев (например, Deployment владеет ReplicaSet, ReplicaSet владеет Pod). Используется механизмом **Garbage Collection** для каскадного удаления: при удалении владельца Kubernetes автоматически удалит все объекты с соответствующими `ownerReferences`. Каждая запись содержит: `apiVersion`, `kind`, `name`, `uid`, `blockOwnerDeletion` (блокирует удаление владельца до завершения удаления зависимого объекта).
*   **`finalizers`**: Список блокировок, препятствующих удалению объекта до выполнения внешних очисток. При наличии хотя бы одного finalizer API-сервер не удалит объект из etcd, а установит `deletionTimestamp`. Контроллер должен удалить свой finalizer после очистки. Примеры: `kubernetes.io/pvc-protection`, `kubernetes.io/finalizer-lifecycle`, CSI-финализаторы.
*   **`deletionTimestamp`**: Время, установленное API-сервером при запросе на удаление (когда есть finalizers). Объект все еще существует в etcd, но помечен для удаления. Pod'ы в هذا состоянии не могут быть запланированы на новые узлы.

### Управление полями
*   **`managedFields`**: Метаданные о том, какой компонент (например, `kubectl`, `helm`, `argocd`, `kube-controller-manager`) управляет конкретными полями объекта. Ключевой механизм **Server-Side Apply (SSA)**. Позволяет избежать конфликтов при одновременном управлении разными частями объекта разными инструментами. Содержит: `manager` (имя), `operation` (Apply/Update), `time`, `fieldsV1` (структура управляемых полей).

### Временные метки
*   **`creationTimestamp`**: Время создания объекта в формате RFC 3339. Не может быть изменено. Используется для вычисления `age` в `kubectl get` и для TTL-контроллеров.
*   **`deletionGracePeriodSeconds`**: Количество секунд между установкой `deletionTimestamp` и физическим удалением. По умолчанию: 30 секунд для Pod'ов. Позволяет приложению корректно завершить работу (graceful shutdown).
*   **`labels`**: см. раздел [Метки (Labels) и Селекторы](#метки-labels-и-селекторы) ниже.
*   **`annotations`**: см. раздел [Аннотации (Annotations)](#антнотации-annotations) ниже.

---

## Метки (Labels) и Селекторы

Метки позволяют организовывать объекты в наборы (группировать), значимые для пользователей, без изменения структуры API.

### Синтаксис ключей и лимиты
*   **Префикс (опционально)**: DNS-поддомен (до 253 символов), separated точкой. Рекомендуется использовать для разделения ответственности (например, `company.com/team`). Если префикс опущен, ключ считается пользовательским (не kitchen system). Префикс `kubernetes.io/` и `k8s.io/` зарезервирован для системных меток.
*   **Имя**: Обязательно (до 63 символов). Должно начинаться и заканчиваться буквой или цифрой, может содержать `-`, `_`, `.`. Регулярное выражение: `^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$`.
*   **Значение**: До 63 символов (может быть пустым). Регулярное выражение: `^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$`.

**Примеры валидных ключей:**
```yaml
# Пользовательские (с префиксом)
app.kubernetes.io/name: "nginx"
team.acme.com/cost-center: "cc-12345"

# Без префика (пользовательские)
env: production
tier: frontend

# Системные (зарезервированные)
kubernetes.io/hostname: "worker-01"
topology.kubernetes.io/zone: "eu-central-1a"
```

**Примеры невалидных ключей:**
```yaml
# Начинается с дефиса
-app: invalid          # → ошибка: must start with alphanumeric

# Содержит пробел
my app: invalid        # → ошибка: must contain only alphanumeric, '-', '_', '.'

# Слишком длинный префикс (>253 символов)
a/very/long/prefix/.../name: invalid  # → ошибка: prefix too long
```

### Ограничения на количество меток

*   **На объект**: Максимум **63 метки** (рекомендация Kubernetes). Фактический лимит — размер JSON-документа (ограничение etcd: **1.5MB** на объект, но метаданные + spec + status в сумме).
*   **Размер ключа + значение**: Ключ до 253 + значение до 63 = до 316 символов на метку.
*   **Суммарный размер метаданных**: Ограничен **256KB** в etcd (лимит на размер ключа etcd). На практике: ~100-200 меток с короткими значениями.

### Индексация в API-сервере

Kubernetes API-сервер поддерживает **инвертированный индекс** для меток. При создании/обновлении объекта с метками, API-сервер обновляет индекс в etcd:

```
Индекс: app=web → [pod-a, pod-b, pod-c]
Индекс: env=prod → [pod-a, pod-c, deploy-x]
Индекс: app=web AND env=prod → [pod-a, pod-c]
```

Это позволяет селекторам работать за **O(1)** вместо **O(N)** (полный скан всех объектов). Индекс поддерживается только для Core API-сервера (Pod, Service, Node и т.д.) и не расширяется на CRD без дополнительных контроллеров.

### Типы селекторов (Label Selectors)

Селекторы позволяют API-серверу быстро находить объекты по их меткам.

1.  **На основе равенства (Equality-based)**:
    Используется в основном в Service `spec.selector` и других «старых» ресурсах.
    *   `env = production` — ключ `env` должен иметь значение `production`
    *   `tier != frontend` — ключ `tier` не должен быть `frontend`

2.  **На основе множеств (Set-based)**:
    Современный подход, используется через поле `matchExpressions` в `Deployment`, `Job`, `DaemonSet`, `ReplicaSet`.
    *   `env in (prod, staging)` — значение входит в список
    *   `tier notin (backup)` — значение не входит в список
    *   `partition` — ключ просто существует (любое значение)
    *   `!partition` — ключ отсутствует

3.  **Комбинированные селекторы**:
    Можно комбинировать оба типа в одном запросе:
    ```bash
    kubectl get pods -l "app=web,env in (prod,staging),!deprecated"
    # → Логическое И: app=web И (env=prod ИЛИ env=staging) И НЕ deprecated
    ```

### Распространение меток (Label Propagation)

Контроллеры Kubernetes автоматически копируют метки между связанными объектами:

| Владелец | Зависимый | Какие метки копируются |
| :--- | :--- | :--- |
| Deployment | ReplicaSet | Все метки из `spec.selector.matchLabels` + `spec.template.metadata.labels` |
| ReplicaSet | Pod | Все метки из `spec.template.metadata.labels` |
| Service | Endpointslice | Метки сервиса через label selector |
| StatefulSet | Pod | Все метки из `spec.template.metadata.labels` |
| DaemonSet | Pod | Все метки из `spec.template.metadata.labels` |
| Job | Pod | Все метки из `spec.template.metadata.labels` |

**Важно:** При изменении меток в `spec.template.metadata.labels` контроллер начнет создавать новые Pod'ы с обновленными метками. Старые Pod'ы не получат новые метки автоматически.

*Подробнее о работе с метками и селекторами на практике:* **[Метки, аннотации и выбор узлов для Pod](../Base/Pod/pod_labels_annotations_node_selection.md)** — полный референс kubectl-команд, сценарии использования (Blue-Green, Canary, NetworkPolicy), troubleshooting.

---

## Рекомендованные метки (Well-known Labels)

Kubernetes стандартизирует набор меток для обеспечения совместимости между инструментами (Helm, ArgoCD, Kustomize). Эти метки поддерживаются контроллерами Kubernetes и должны использоваться при возможности.

### Метки приложения (app.kubernetes.io/*)

| Ключ | Описание | Пример | Кто использует |
| :--- | :--- | :--- | :--- |
| `app.kubernetes.io/name` | Название приложения | `mysql` | Helm, ArgoCD, Prometheus |
| `app.kubernetes.io/instance` | Уникальное имя экземпляра | `mysql-abcxzy` | Helm ( release name) |
| `app.kubernetes.io/version` | Текущая версия (SemVer) | `v1.4.2` | Helm, CI/CD |
| `app.kubernetes.io/component` | Роль компонента | `database`, `frontend` | Humans, дашборды |
| `app.kubernetes.io/part-of` | Родительская система | `wordpress` | Humans, аудит |
| `app.kubernetes.io/managed-by` | Инструмент деплоя | `helm`, `argocd` | Helm, Kustomize |

**Пример полного набора меток для Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mysql
  labels:
    app.kubernetes.io/name: mysql
    app.kubernetes.io/instance: mysql-abcxzy
    app.kubernetes.io/version: "8.0.36"
    app.kubernetes.io/component: database
    app.kubernetes.io/part-of: wordpress
    app.kubernetes.io/managed-by: helm
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: mysql      # ← минимальный селектор
      app.kubernetes.io/instance: mysql-abcxzy
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mysql
        app.kubernetes.io/instance: mysql-abcxzy
        app.kubernetes.io/version: "8.0.36"
        app.kubernetes.io/component: database
        app.kubernetes.io/part-of: wordpress
        app.kubernetes.io/managed-by: helm
```

### Топологические метки

Эти метки автоматически проставляются компонентом Kubelet или Cloud Controller Manager:

*   `topology.kubernetes.io/zone`: Зона доступности (например, `eu-central-1a`).
*   `topology.kubernetes.io/region`: Регион (например, `eu-central-1`).
*   `kubernetes.io/hostname`: Имя узла (уникальное в кластере).
*   `kubernetes.io/os` / `kubernetes.io/arch`: ОС и архитектура (например, `linux`, `amd64`).

### Метки Node Roles

Kubernetes поддерживает стандартные префиксы для ролей узлов:

```bash
# Стандартные роли (автоматически при установке)
node-role.kubernetes.io/control-plane: ""   # Control plane узлы
node-role.kubernetes.io/master: ""          # (deprecated) Control plane

# Пользовательские роли (рекомендуемые префиксы)
node-role.kubernetes.io/ingress: ""         # Ingress-ноды
node-role.kubernetes.io/gpu: ""             # GPU-ноды
node-role.kubernetes.io/worker: ""          # Worker-ноды
```

```bash
# Просмотр узлов по роли
kubectl get nodes -l node-role.kubernetes.io/control-plane
kubectl get nodes -l node-role.kubernetes.io/ingress
```

### Метки для Pod Security Standards

Kubernetes 1.25+ поддерживает метки для управления безопасностью Pod:

```yaml
# Enforce: запретить нарушения
metadata:
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest

# Warn: предупреждать о нарушениях
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest

# Audit: логировать нарушения
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
```

---

## Аннотации (Annotations)

Используются для данных, которые не подходят для селекторов, но важны для контроллеров, дашбордов или внешних инструментов интеграции.

### Синтаксис и ограничения

*   **Ключ**: Аналогичен меткам (до 253 символов префикс + до 63 имя). Рекомендуется использовать полные URI для инструментов: `prometheus.io/scrape`, `nginx.ingress.kubernetes.io/rewrite-target`.
*   **Значение**: До **256KB** суммарно на все аннотации объекта (ограничение etcd: максимальный размер ключа — 1.5MB, но метаданные + spec + status в сумме). На практике: до 10-20 аннотаций со средним размером значения 1-5KB.
*   **Индексация**: Аннотации **не индексируются** API-сервером. Запросы вида `kubectl get pods -l annotation.key=value` **невозможны**. Для поиска по аннотациям используйте `kubectl get pods -o json | jq`.

### Типовые сценарии использования

**История изменений (Change Cause):**
```bash
# Автоматическое добавление при обновлении через kubectl
kubectl set image deployment/my-app app=my-app:v2.0
# → Аннотация kubernetes.io/change-cause добавляется автоматически

# Ручное добавление
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление образа до v1.2.3"
# → Результат виден в kubectl rollout history deployment/my-app
```

**Конфигурация Ingress:**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  annotations:
    # NGINX Ingress Controller
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/cors-allow-origin: "https://example.com"

    # Traefik
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"

    # Cert-Manager
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
```

**Секреты и Vault:**
```yaml
annotations:
    vault.hashicorp.com/agent-inject: "true"
    vault.hashicorp.com/role: "my-app"
    vault.hashicorp.com/agent-inject-secret-db: "secret/data/db"
    vault.hashicorp.com/agent-inject-template-db: |
      {{- with secret "secret/data/db" -}}
      DB_PASSWORD={{ .Data.data.password }}
      {{- end -}}
```

**Service Mesh (Istio):**
```yaml
annotations:
    sidecar.istio.io/inject: "true"
    sidecar.istio.io/proxyCPU: "100m"
    sidecar.istio.io/proxyMemory: "128Mi"
    sidecar.istio.io/logLevel: "info"
    traffic.sidecar.istio.io/includeInboundPorts: "8080"
```

**Мониторинг (Prometheus):**
```yaml
annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
    prometheus.io/path: "/metrics"
    prometheus.io/scheme: "http"
```

**Сбор логов (Fluent Bit / Fluentd):**
```yaml
annotations:
    fluentbit.io/parser: "json"
    fluentbit.io/parser-backend: "nginx"
    fluentd.io/parser: "json"
```

**Документация и аудит:**
```yaml
annotations:
    description: "Основной API-сервис обработки платежей"
    team: "platform"
    on-call: "platform-oncall@company.com"
    cost-center: "cc-12345"
    runbook-url: "https://wiki.company.com/runbooks/payment-api"
    incident-url: "https://pagerduty.com/incidents/ABC123"
```

---

## Практические сценарии

### 1. Работа с метками через kubectl

```bash
# Показать поды с их метками
kubectl get pods --show-labels
# → NAME    READY   STATUS    LABELS
# → web-0   1/1     Running   app=web,env=prod,tier=frontend

# Поиск по селектору на основе множеств (Set-based)
kubectl get pods -l "env in (production, staging),tier=frontend"
# → web-0   1/1     Running   ...

# Комбинированный селектор (AND)
kubectl get pods -l "app=web,env=prod"
# → Только Pod'ы с ОБЕИМИ метками

# Добавить метку существующему узлу
kubectl label nodes worker-1 disktype=ssd
# → node/worker-1 labeled

# Удалить метку (минус после ключа)
kubectl label nodes worker-1 disktype-
# → node/worker-1 unlabeled

# Перезапись существующей метки
kubectl label pods my-pod env=prod --overwrite
# → pod/my-pod labeled

# Проверка меток узлов
kubectl get nodes --show-labels | tr ',' '\n' | grep disktype
```

### 2. Использование matchExpressions в Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: my-app
    matchExpressions:
      - {key: tier, operator: In, values: [frontend, api]}
      - {key: env, operator: NotIn, values: [dev]}
  template:
    metadata:
      labels:
        app: my-app
        tier: frontend
        env: production
    spec:
      containers:
      - name: app
        image: nginx:1.27
```

### 3. Фиксация причины изменения (Change Cause)

Аннотации полезны для ведения аудита ручных изменений:

```bash
# Ручное добавление аннотации с причиной
kubectl annotate deployment/my-app kubernetes.io/change-cause="Обновление образа до v1.2.3"
# → deployment.apps/my-app annotated

# Просмотр истории изменений
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         Обновление образа до v1.2.3

# Автоматическое добавление при kubectl set image
kubectl set image deployment/my-app app=my-app:v2.0
# → Аннотация добавляется автоматически
```

### 4. Поиск объектов по аннотациям

Аннотации не индексируются, поэтому поиск возможен только через jsonpath/jq:

```bash
# Поиск Pod с определенной аннотацией
kubectl get pods -o json | jq -r '.items[] | select(.metadata.annotations["team"] == "platform") | .metadata.name'
# → web-abc123
# → api-def456

# Просмотр конкретной аннотации
kubectl get pod my-pod -o jsonpath='{.metadata.annotations.prometheus\.io/scrape}'
# → true

# Кастомный вывод с аннотациями
kubectl get pods -o custom-columns="NAME:.metadata.name,CHANGE:.metadata.annotations.kubernetes\.io/change-cause"
```

### 5. Управление метками через Server-Side Apply

Server-Side Apply (SSA) позволяет нескольким инструментам безопасно управлять разными полями объекта:

```bash
# Инженер управляет replicas
kubectl apply --server-side --field-manager=eng-team -f deployment.yaml

# SRE управляет метками
kubectl apply --server-side --field-manager=sre-team -f labels-patch.yaml

# Просмотр managedFields
kubectl get deployment my-app -o json | jq '.metadata.managedFields'
# → [
#     {"manager": "eng-team", "operation": "Apply", "fieldsV1": {"f:spec": {"f:replicas": {}}}},
#     {"manager": "sre-team", "operation": "Apply", "fieldsV1": {"f:metadata": {"f:labels": {}}}}
#   ]

# Разрешение конфликтов (force)
kubectl apply --server-side --field-manager=sre-team --force-conflicts -f labels-patch.yaml
```

### 6. kubectl patch для обновления меток и аннотаций

`kubectl patch` позволяет точечно обновлять метки и аннотации без перезаписи всего объекта:

```bash
# Обновление метки (strategic merge patch)
kubectl patch deployment my-app -p '{"metadata":{"labels":{"version":"v2"}}}'

# Обновление аннотации
kubectl patch deployment my-app -p '{"metadata":{"annotations":{"description":"Обновленный API"}}}'

# Обновление меток в template (для следующего rollouts)
kubectl patch deployment my-app -p '{"spec":{"template":{"metadata":{"labels":{"env":"staging"}}}}}'

# JSON merge patch (для замены всего объекта меток)
kubectl patch deployment my-app --type=merge -p '{"metadata":{"labels":{"team":"platform","cost-center":"cc-12345"}}}'

# Кастомный патч через jsonpatch
kubectl patch deployment my-app --type=json -p='[
  {"op":"add","path":"/metadata/labels/env","value":"production"},
  {"op":"replace","path":"/metadata/annotations/description","value":"Продакшен API"}
]'
```

**Проверка результата:**
```bash
kubectl get deployment my-app -o jsonpath='{.metadata.labels}' | jq .
# → {"app":"my-app","env":"production","version":"v2","team":"platform"}
```

### 7. Организация ресурсов с помощью меток в масштабе

В больших кластерах метки становятся основным инструментом управления ресурсами:

```bash
# Массовая проверка меток всех Deployment в namespace
kubectl get deployments -n production -o json | \
  jq -r '.items[] | "\(.metadata.name)\t\(.metadata.labels.team // "n/a")\t\(.metadata.labels.env // "n/a")"'

# Найти все Pod без метки team (потенциальные孤儿 ресурсы)
kubectl get pods --all-namespaces -o json | \
  jq -r '.items[] | select(.metadata.labels.team == null) | "\(.metadata.namespace)/\(.metadata.name)"'

# Подсчет ресурсов по командам через метки
kubectl get deployments --all-namespaces -o json | \
  jq -r '.items[] | .metadata.labels.team // "unknown"' | sort | uniq -c | sort -rn

# Группировка Pod по метке app для визуального контроля
kubectl get pods --all-namespaces -l app=web -o custom-columns="NS:.metadata.namespace,NAME:.metadata.name,NODE:.spec.nodeName,STATUS:.status.phase"
```

**Сценарий: Автоматическая разметка узлов при добавлении в кластер:**
```bash
# Скрипт для маркировки новых узлов (可以 run в CI/CD)
for node in $(kubectl get nodes --no-headers | grep "<none>" | awk '{print $1}'); do
  kubectl label node "$node" env=production team=platform
done
```

### 8. Валидация меток через Kyverno

Kyverno позволяет требовать обязательные метки при создании ресурсов:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-required-labels
    match:
      any:
      - resources:
          kinds:
          - Deployment
          - Service
          - ConfigMap
    validate:
      message: "Ресурс должен содержать обязательные метки: team, env, app"
      pattern:
        metadata:
          labels:
            team: "?*"
            env: "?*"
            app: "?*"
  - name: check-cost-center
    match:
      any:
      - resources:
          kinds:
          - Deployment
    validate:
      message: "Deployment должен содержать метку cost-center для аудита затрат"
      pattern:
        metadata:
          labels:
            cost-center: "?*"
  - name: validate-label-values
    match:
      any:
      - resources:
          kinds:
          - Deployment
    validate:
      message: "Метка env может иметь только значения: dev, staging, production"
      pattern:
        metadata:
          labels:
            env: "dev | staging | production"
```

**Проверка политики:**
```bash
# Попытка создать Deployment без обязательных меток → ошибка
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-deploy
spec:
  selector:
    matchLabels:
      app: test
  template:
    metadata:
      labels:
        app: test
    spec:
      containers:
      - name: test
        image: nginx
EOF
# → Error: admission webhook denied the request: 
#   Ресурс должен содержать обязательные метки: team, env, app
```

### 9. Связь меток с PodDisruptionBudget

PodDisruptionBudget использует метки для определения защищаемых Pod:

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web-pdb
  namespace: production
spec:
  minAvailable: 2    # или maxUnavailable: 1
  selector:
    matchLabels:
      app: web
      env: production
```

**Практические особенности:**
- PDB не создает Pod — он защищает существующие
- Селектор PDB должен соответствовать меткам Pod, а не контроллера
- При нарушении PDB `kubectl drain` блокируется до истечения таймаута

```bash
# Проверка PDB и количества защищенных Pod
kubectl get pdb -n production
# → NAME      MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → web-pdb   2               <none>            1                     30d

# Проверка каких Pod касается PDB
kubectl get pdb web-pdb -n production -o jsonpath='{.status.currentHealthy}'
# → 5

# Симуляция drain (не удаляет, а показывает конфликты)
kubectl drain worker-01 --dry-run=client --ignore-daemonsets --delete-emptydir-data
```

### 10. Ограничение доступа к меткам через RBAC

RBAC может ограничивать доступ к определенным меткам (через `resourceNames` для��бора или label selectors в Policy):

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: label-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
  # Ограничение по namespace (метки в селекторе RBAC не поддерживаются)
  # Для фильтрации по меткам используйте рекламные инструменты или OPA
```

**Фильтрация по меткам в kubectl (пример для аудита):**
```bash
# Вывод Pod только с определенными метками
kubectl get pods -n production -o json | \
  jq -r '.items[] | select(.metadata.labels.team == "platform") | .metadata.name'

# Экспорт меток для аудита
kubectl get deployments --all-namespaces -o json | \
  jq -r '.items[] | {name: .metadata.name, namespace: .metadata.namespace, labels: .metadata.labels}' | \
  jq -s '.' > labels-audit.json
```

---

## Типичные ошибки и troubleshooting

### Ошибка 1: "selector does not match template labels"

**Сообщение:**
```
error: Deployment.apps "my-app" is invalid: spec.template.metadata.labels: Invalid value: 
map[string]string{"app":"my-app","version":"v2"}: `selector` does not match template `labels`
```

**Причина:** Метки в `spec.template.metadata.labels` не покрывают селектор `spec.selector.matchLabels`.

**Диагностика:**
```bash
# Проверить селектор
kubectl get deployment my-app -o jsonpath='{.spec.selector.matchLabels}'
# → {"app":"my-app"}

# Проверить метки template
kubectl get deployment my-app -o jsonpath='{.spec.template.metadata.labels}'
# → {"app":"my-app","version":"v2"}

# Проблема: template имеет метку version, которой нет в селекторе — это нормально.
# Ошибка возникает если в селекторе есть метки, которых НЕТ в template.
```

**Решение:** Убедитесь, что все метки из `spec.selector.matchLabels` присутствуют в `spec.template.metadata.labels`. Добавьте недостающие метки:
```bash
kubectl patch deployment my-app -p '{"spec":{"template":{"metadata":{"labels":{"version":"v1"}}}}}'
```

### Ошибка 2: "field is immutable"

**Сообщение:**
```
The Deployment "my-app" is invalid: spec.selector: Invalid value: 
..."field is immutable", "spec.selector": peer value not permitted
```

**Причина:** Попытка изменить `spec.selector` после создания Deployment.

**Решение:** Пересоздайте Deployment:
```bash
# Экспортировать текущий манифест
kubectl get deployment my-app -o yaml > my-app.yaml

# Изменить метки вручную в my-app.yaml (в spec.selector и spec.template.metadata.labels)
# Удалить поля, которые генерируются автоматически (resourceVersion, uid, status, creationTimestamp)

# Удалить старый и создать новый
kubectl delete deployment my-app
kubectl apply -f my-app.yaml
```

### Ошибка 3: "Request Entity Too Large (413)"

**Причина:** Суммарный размер Labels + Annotations превышает лимит etcd.

**Диагностика:**
```bash
# Проверить размер метаданных объекта
kubectl get deployment my-app -o json | jq '.metadata' | wc -c
# → 524288 (если больше 262144 = 256KB, проблема)

# Найти ключи с большими значениями
kubectl get deployment my-app -o json | jq '.metadata.annotations | to_entries[] | "\(.key): \(.value | length) chars"'
```

**Решение:** Вынести большие данные в ConfigMap/Secret или уменьшить размер аннотаций.

### Ошибка 4: Service не находит Pod

**Сообщение:** Приложение недоступно, `kubectl get endpoints` показывает пустой список.

**Причина:** Метки в `spec.selector` Service не совпадают с метками Pod.

**Диагностика:**
```bash
# Проверить селектор Service
kubectl get svc my-app -o jsonpath='{.spec.selector}'
# → {"app":"my-app","env":"production"}

# Проверить метки Pod
kubectl get pods -l app=my-app --show-labels
# → NAME    READY   STATUS    LABELS
# → my-pod  1/1     Running   app=my-app,env=staging  ← НЕТ env=production!

# Проверить Endpoints
kubectl get endpoints my-app
# → NAME       ENDPOINTS   AGE
# → my-app     <none>      30d
```

**Решение:** Обновить метки Pod или селектор Service:
```bash
# Вариант 1: Добавить нужную метку к Pod (временно, для отладки)
kubectl label pod my-pod env=production

# Вариант 2: Исправить Service (основное решение)
kubectl patch svc my-app -p '{"spec":{"selector":{"env":"staging"}}}'
```

### Ошибка 5: Метки не индексируются для CRD

**Причина:** Инвертированный индекс API-сервера работает только для Core API-ресурсов (Pod, Service, Node). Для CRD селекторы работают как полный скан (O(N)).

**Симптомы:** Медленные запросы `kubectl get` с селекторами к большим количествам CRD-объектов.

**Решение:** Для CRD используйте Sparse Index в etcd или контроллеры с кешированием (Kubernetes informers). Рассмотрите использование Operator SDK для построения контроллеров, которые поддерживают индексацию.

### Ошибка 6: Конфликт managedFields при SSA

**Сообщение:**
```
error: Apply failed with 1 conflict: conflict with "helm" on metadata.labels
```

**Причина:** Два менеджера (например, `helm` и `sre-team`) пытаются управлять одними и теми же полями.

**Решение:**
```bash
# Разрешить конфликт принудительно
kubectl apply --server-side --field-manager=sre-team --force-conflicts -f manifest.yaml

# Проверить managedFields
kubectl get deployment my-app -o json | jq '.metadata.managedFields[] | {manager: .manager, operation: .operation}'
```

### Ошибка 7: Pod не планируется из-за неправильных меток узлов

**Сообщение:**
```
0/3 nodes are available: 3 node(s) didn't match pod anti-affinity rules.
```

**Причина:** Анти-аффинити или nodeSelector указывают на метки, которых нет на узлах.

**Диагностика:**
```bash
# Проверить требования Pod
kubectl get pod my-pod -o jsonpath='{.spec.affinity}' | jq .

# Проверить метки всех узлов
kubectl get nodes --show-labels | tr ',' '\n' | grep -E "disktype|gpu|env"

# Найти узлы с нужными метками
kubectl get nodes -l disktype=ssd,gpu=true
```

---

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Используйте префиксы для меток**: Не используйте `env: prod`, используйте `my-company.com/env: prod`. Это предотвращает конфликты с чартами сторонних поставщиков и системными контроллерами.
2.  **Валидация (Policy-as-Code)**: Используйте инструменты типа **Kyverno** или **OPA Gatekeeper** для обязательного требования меток (`owner`, `cost-center`) при создании ресурсов.
3.  **Лимиты размера**: Суммарный объем метаданных объекта (Labels + Annotations) ограничен **256KB** (лимит etcd). Не храните в аннотациях огромные конфигурационные файлы; используйте для этого `ConfigMap`.
4.  **Селекторы неизменны**: В ресурсах типа `Deployment` поле `spec.selector` является **неизменяемым** после создания. Изменение меток в `template.metadata.labels` без обновления селектора (что невозможно) приведет к ошибке или потере управления подами.
5.  **Минимизируйте количество меток**: Каждая метка — это дополнительный размер JSON-документа в etcd. Используйте только метки, которые действительно необходимы для селекторов, мониторинга или аудита.
6.  **Используйте консистентную схему меток**: Определите стандартную схему меток для организации (`app`, `env`, `team`, `cost-center`) и придерживайтесь её во всех проектах.
7.  **Не храните секреты в аннотациях**: Аннотации видны всем, кто имеет доступ к namespace (через `kubectl get -o yaml`). Используйте [Secrets](../Base/secrets/etcd_storage.md) или External Secrets Operator.
8.  **Изменяйте `spec.selector` только при создании**: Поле неизменяемо. Планируйте имена меток заранее. Если нужно изменить метки — создайте новый Deployment.
9.  **Для мониторинга используйте аннотации**: Prometheus, Fluent Bit и другие инструменты читают аннотации для автообнаружения — не перегружайте ими системные метки.
10. **Используйте `--overwrite` осознанно**: Не перезаписывайте метки без проверки — это может сломать селекторы Service или Deployment.
11. **Документируйте схему меток**: Ведите справочник меток для организации (Google Doc, Confluence, README в Git-репозитории). Укажите обязательные метки, допустимые значения и форматы для команд и проектов.
12. **Используйте `kubectl label --dry-run=client`**: При массовой разметке проверяйте результат заранее, чтобы не нарушить существующие селекторы.
13. **Разделяйте метки для выборки и метки для аудита**: Селекторы Deployment/Service должны содержать минимальный набор меток для выборки. Метки для аудита (`team`, `cost-center`, `on-call`) добавляйте отдельно и не включайте в `spec.selector`.

### Edge Cases и известные особенности

*   **256KB лимит метаданных**: Если суммарный размер Labels + Annotations + других системных полей превышает 256KB, API-сервер вернет ошибку `413 Request Entity Too Large`. Это критично при хранении больших JSON-конфигов в аннотациях. Решение: вынести данные в ConfigMap/Secret.
*   **Конфликт managedFields**: При одновременном применении SSA от двух менеджеров к одному полю возникает конфликт. Решение: `--force-conflicts` или согласование между командами.
*   **Потеря меток при масштабировании**: Если изменить `spec.template.metadata.labels` в Deployment, новые Pod'ы получат новые метки, а старые — нет. Это может сломать Service, если селектор ссылается на измененные метки.
*   **Слишком длинные ключи меток**: Ключи с префиксом > 253 символов или именем > 63 символов отвергаются API-сервером. Типичная ошибка: `metadata.labels: Invalid value`.
*   **Пустые значения меток**: Kubernetes допускает пустые значения (`key: ""`), но многие инструменты (Helm, Prometheus) могут некорректно их обрабатывать. Избегайте пустых значений.
*   **Специальные символы в ключах**: Ключи могут содержать только alphanumeric, `-`, `_`, `.`. Пробелы, слеши, кириллица запрещены.
*   **Регистр ключей**: Ключи меток **case-sensitive**. `App` и `app` — это разные ключи. Используйте lowercase для консистентности.
*   **Автоматические метки контроллеров**: Некоторые контроллеры добавляют метки автоматически (например, `statefulset.kubernetes.io/pod-name` для StatefulSet). Не пытайтесь изменить или удалить эти метки — контроллер перезапишет их.
*   **Метки и garbage collection**: Если удалить Deployment, все связанные ReplicaSet и Pod'ы будут удалены через `ownerReferences`. Метки не влияют на этот процесс — важны только `ownerReferences`.
*   **Конфликт меток при каскадном обновлении**: При обновлении Deployment через `kubectl apply` контроллер создает новый ReplicaSet с новыми метками. Старые Pod'ы остаются с cũ метками до завершения rollout. В этот момент Service может одновременно обслуживать Pod'ы с разными метками — учитывайте это при планировании.
*   **Helm и immutable values**: При использовании Helm, если значение переменной используется в `spec.selector.matchLabels`, его нельзя изменить в последующих релизах. Helm вернет ошибку `field is immutable`. Решение: пересоздать релиз или использовать `helm install --replace`.
*   **Проблемы с масштабированием HPA**: Если HPA ссылается на метрику, связанную с конкретными метками Pod, убедитесь, что все Pod'ы имеют одинаковые метки. Разнородные метки приведут к некорректному расчету метрик.
*   **Метки и CronJob**: При создании CronJob метки из `spec.jobTemplate.spec.template.metadata.labels` копируются в Pod'ы, создаваемые каждым запуском. Если метки содержат динамические значения (например, `${BUILD_ID}`), каждый Pod будет иметь уникальные метки, что затрудняет мониторинг.

### См. также
*   **[Garbage Collection и Owner References](garbage_collection.md)** — каскадное удаление, foreground/background/orphan, цепочки владения.
*   **[Метки, аннотации и выбор узлов для Pod](../Base/Pod/pod_labels_annotations_node_selection.md)** — практический референс kubectl-команд, сценарии Blue-Green/Canary, NetworkPolicy, troubleshooting.
*   **[PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md)** — защита Pod от массового удаления (использует селекторы по меткам).
*   **[HPA (Horizontal Pod Autoscaler)](../Autoscaling/HPA/hpa_concepts.md)** — автоскейлинг на основе метрик (метки используются для фильтрации целей).
*   **[Сетевые политики (NetworkPolicy)](../Networking/Network/network_overview.md)** — изоляция трафика по меткам Pod.
*   **[Node Affinity и Taints](../Scheduling/affinity.md)** — планирование на основе меток узлов и подов.
*   **[Kyverno: правила валидации](../Security/kyverno/rules.md)** — Policy-as-Code для обязательных меток.
*   **[Взаимодействие с API](./api_interaction.md)** — архитектура ресурсов и управление через API.
