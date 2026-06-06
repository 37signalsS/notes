# Reloader — Установка и настройка

## Определения

**Установка Reloader** — процесс развёртывания контроллера Reloader в Kubernetes-кластере для автоматического отслеживания изменений в ConfigMap/Secret и инициирования rolling upgrade (плавного обновления) рабочих нагрузок (workloads).

**Основной источник:** [Обзор и концепции Reloader](./reloader_overview.md)

---

## Основные концепции

### Способы установки

| Способ | Когда использовать | Преимущества |
| :--- | :--- | :--- |
| **Helm** | Production, GitOps | Управление версиями, параметризация. |
| **Манифесты** | Быстрое развёртывание, air-gapped | Не требует Helm (пакетный менеджер). |

### RBAC-требования

Reloader требует RBAC (Role-Based Access Control — управление доступом на основе ролей) для доступа к:

- **secrets, configmaps** — `list`, `get`, `watch`
- **deployments, daemonsets, statefulsets** — `list`, `get`, `watch`, `update`, `patch`
- **cronjobs** — `list`, `get`, `watch`

### Ресурсы контроллера

| Ресурс | Request | Limit |
| :--- | :--- | :--- |
| CPU (Central Processing Unit) | 100m | 300m |
| Память (Memory) | 128Mi | 256Mi |

---

## Практические сценарии

### Сценарий 1: Установка через Helm (рекомендуется)

**1. Добавление репозитория:**

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
```

**2. Создание values.yaml:**

```yaml
# values.yaml
reloader:
  namespace: monitoring
  watchGlobally: true
  replicas: 1

  deployment:
    image:
      tag: v1.4.17
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 300m
        memory: 256Mi

  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --log-level=info
```

**3. Установка:**

```bash
helm install reloader stakater/reloader \
  --namespace monitoring \
  --create-namespace \
  --values values.yaml
```

**Основные параметры Helm:**

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `reloader.watchGlobally` | `true` | Следить во всех пространствах имён (namespaces). |
| `reloader.namespace` | `default` | Пространство имён для установки. |
| `reloader.replicas` | `1` | Количество реплик. |
| `reloader.resources` | `{}` | Ресурсы контроллера. |

---

### Сценарий 2: Установка через манифесты

**Полный манифест `reloader-setup.yaml`:**

```yaml
---
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reloader
  namespace: monitoring
  labels:
    app: reloader

---
# ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: reloader-role
  labels:
    app: reloader
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

---
# ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: reloader-role-binding
  labels:
    app: reloader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: reloader-role
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: monitoring

---
# Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: reloader
  namespace: monitoring
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
      containers:
        - name: reloader
          image: ghcr.io/stakater/reloader:v1.4.17
          imagePullPolicy: IfNotPresent
          args:
            - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
            - --log-level=info
          ports:
            - containerPort: 9090
              protocol: TCP
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 300m
              memory: 256Mi
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
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL

---
# Service (для мониторинга)
apiVersion: v1
kind: Service
metadata:
  name: reloader
  namespace: monitoring
  labels:
    app: reloader
spec:
  ports:
    - port: 9090
      targetPort: 9090
      protocol: TCP
      name: http
  selector:
    app: reloader
```

**Применение:**

```bash
kubectl apply -f reloader-setup.yaml
```

---

### Сценарий 3: Исключение пространств имён

**Через Helm:**

```yaml
# values.yaml
reloader:
  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --namespaces-to-select=default,production,staging
```

**Через манифест:**

```yaml
spec:
  containers:
    - args:
        - --namespaces-to-ignore=kube-system
        - --log-level=info
```

---

### Проверка установки

```bash
# Статус deployment
kubectl get deployment reloader -n monitoring
kubectl describe deployment reloader -n monitoring

# Статус подов
kubectl get pods -n monitoring -l app=reloader

# Логи
kubectl logs -f deployment/reloader -n monitoring
```

---

## Дополнительная информация

### Требования

| Компонент | Минимальная версия |
| :--- | :--- |
| Kubernetes | 1.26+ |
| Helm | 3.0+ |

### Безопасность

Манифест установки включает `securityContext`:

- `runAsNonRoot: true`
- `runAsUser: 65534` (nobody)
- `allowPrivilegeEscalation: false`
- `capabilities.drop: ALL`

### Ресурсы

- [GitHub: stakater/Reloader](https://github.com/stakater/Reloader)
- [Helm Chart на ArtifactHub](https://artifacthub.io/packages/helm/stakater/reloader)
