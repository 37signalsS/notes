# Reloader — Установка и настройка

## Определения

**Установка Reloader** — процесс развёртывания контроллера Reloader в Kubernetes-кластере для автоматического отслеживания изменений в ConfigMap/Secret и инициирования плавного обновления (Rolling Upgrade) рабочих нагрузок (workloads).

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Способы установки

| Способ | Когда использовать | Преимущества |
| :--- | :--- | :--- |
| **Helm** | Production, GitOps (ArgoCD/Flux) | Управление версиями, поддержка HA, простая параметризация через `values.yaml`. |
| **Манифесты (YAML)** | Быстрое развёртывание, Air-gapped | Не требует сторонних инструментов, полный контроль над каждым ресурсом. |
| **Kustomize** | GitOps без шаблонизации | Нативный подход Kubernetes, отсутствие "магии" шаблонов. |

### Требования к RBAC

Reloader требует Role-Based Access Control (RBAC) для мониторинга ресурсов и внесения изменений. Контроллеру необходимы следующие права доступа:

- **Ресурсы конфигурации:** `secrets`, `configmaps` — методы `list`, `get`, `watch`.
- **Рабочие нагрузки:** `deployments`, `daemonsets`, `statefulsets`, `deployments.extensions` — методы `list`, `get`, `watch`, `update`, `patch`.
- **Дополнительно:** `cronjobs`, `rollouts.argoproj.io` (если используется Argo Rollouts) — методы `list`, `get`, `watch`.

### Ресурсы и масштабирование

Контроллер потребляет ресурсы пропорционально количеству отслеживаемых объектов в кластере.

| Параметр | Рекомендация (S/M кластер) | Описание |
| :--- | :--- | :--- |
| **CPU Request** | 100m | Минимальное резервирование. |
| **CPU Limit** | 300m | Для обработки всплесков при массовом обновлении. |
| **Memory Request** | 128Mi | Базовое потребление. |
| **Memory Limit** | 512Mi | Лимит для предотвращения OOM-kill при кешировании API. |

---

## Практические сценарии

### Сценарий 1: Установка через Helm (Рекомендуется для Production)

Этот метод позволяет легко управлять жизненным циклом и обновлять контроллер.

**1. Добавление репозитория:**

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
# → result: "stakater" has been added to your repositories
```

**2. Создание расширенного `values.yaml` (v1.4.19):**

```yaml
# values.yaml
reloader:
  replicas: 2 # Запуск в режиме High Availability (HA)
  watchGlobally: true
  
  # Ограничение области видимости для больших кластеров
  # namespaceSelector: "reloader-enabled=true" 

  deployment:
    image:
      tag: v1.4.19
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 300m
        memory: 512Mi

  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --log-level=info
    - --enable-csi-integration=true # Поддержка Secrets Store CSI Driver
    - --reload-strategy=annotations # Рекомендуется для GitOps
```

**3. Выполнение установки:**

```bash
helm install reloader stakater/reloader \
  --namespace reloader-system \
  --create-namespace \
  --values values.yaml
# → result: NAME: reloader, STATUS: deployed, NAMESPACE: reloader-system
```

---

### Сценарий 2: Установка через полные манифесты (Air-gapped / Manual)

Данный сценарий полезен для глубокого понимания структуры ресурсов или работы в изолированных сетях.

**Полный манифест `reloader-setup.yaml`:**

```yaml
---
# Создание пространства имён
apiVersion: v1
kind: Namespace
metadata:
  name: reloader-system

---
# Сервисный аккаунт
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    app: reloader

---
# Роль для доступа к ресурсам (ClusterRole)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs"]
    verbs: ["list", "get", "watch"]
  - apiGroups: ["argoproj.io"]
    resources: ["rollouts"]
    verbs: ["list", "get", "watch", "update", "patch"]

---
# Привязка роли
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: reloader-role-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: reloader-role
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: reloader-system

---
# Контроллер (Deployment)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: reloader-system
  labels:
    app: reloader
spec:
  replicas: 1
  selector:
    matchLabels:
      app: reloader
  template:
    metadata:
      labels:
        app: reloader
    spec:
      serviceAccountName: reloader
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        fsGroup: 65534
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.4.19
          imagePullPolicy: IfNotPresent
          args:
            - --namespaces-to-ignore=kube-system,kube-public
            - --log-level=info
            - --reload-strategy=env-vars # По умолчанию
          ports:
            - containerPort: 9090
              name: http
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 300m
              memory: 512Mi
          livenessProbe:
            httpGet:
              path: /healthz
              port: 9090
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /readyz
              port: 9090
            initialDelaySeconds: 5
            periodSeconds: 5
```

**Применение:**

```bash
kubectl apply -f reloader-setup.yaml
# → result: serviceaccount/reloader created, clusterrole.rbac.authorization.k8s.io/reloader-role created...
```

---

### Сценарий 3: Настройка для GitOps (ArgoCD / Flux)

При использовании GitOps-инструментов крайне важно предотвратить циклы обновлений (OutOfSync).

1.  **Выбор стратегии:** Используйте `--reload-strategy=annotations`. В этом режиме Reloader добавляет аннотацию `reloader.stakater.com/last-reloaded-from` в шаблон пода.
2.  **Игнорирование различий (ArgoCD):** Настройте ArgoCD Application так, чтобы он игнорировал эту аннотацию.

```yaml
# Фрагмент ArgoCD Application
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

---

## Проверка установки

**1. Проверка статуса подов:**

```bash
kubectl get pods -n reloader-system -l app=reloader
# → result: reloader-6c84df96b5-abcde  1/1  Running  0  5m
```

**2. Проверка RBAC прав (self-test):**

Убедитесь, что контроллер действительно может обновлять Deployment:

```bash
kubectl auth can-i patch deployments --as=system:serviceaccount:reloader-system:reloader
# → result: yes
```

**3. Просмотр логов запуска:**

```bash
kubectl logs -f deployment/reloader -n reloader-system
# → result: time="..." level=info msg="Reloader started"
# → result: time="..." level=info msg="Watching for changes in all namespaces"
```

---

## Дополнительная информация

### Совместимость версий

| Версия Reloader | Kubernetes | Helm |
| :--- | :--- | :--- |
| **v1.4+** | 1.26 - 1.30+ | 3.10+ |
| **v1.0 - v1.3** | 1.21 - 1.25 | 3.0+ |

### Параметры безопасности (SecurityContext)

Манифест установки по умолчанию включает следующие меры защиты:

- **`runAsNonRoot: true`**: Контроллер никогда не запускается от имени пользователя root.
- **`allowPrivilegeEscalation: false`**: Запрет на повышение привилегий внутри контейнера.
- **`readOnlyRootFilesystem: true`**: (Рекомендуется) Файловая система контейнера доступна только для чтения.
- **`capabilities.drop: ["ALL"]`**: Удаление всех системных Linux-возможностей.

### Ресурсы

- [Официальный репозиторий GitHub](https://github.com/stakater/Reloader)
- [ArtifactHub: Helm Chart](https://artifacthub.io/packages/helm/stakater/reloader)
- [Мониторинг и отладка](./reloader_monitoring_and_best_practices.md)
- [Практические сценарии использования](./reloader_usage_scenarios.md)
