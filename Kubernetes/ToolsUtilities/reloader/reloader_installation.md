# Reloader — Установка и настройка

## 1. Установка через Helm

### Добавление репозитория

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm repo update
```

### Установка Reloader

```bash
helm install reloader stakater/reloader \
  --namespace monitoring \
  --create-namespace \
  --set reloader.watchGlobally=true \
  --set reloader.deployment.resources.requests.cpu=100m \
  --set reloader.deployment.resources.requests.memory=128Mi
```

### Основные параметры Helm

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `reloader.watchGlobally` | `true` | Следить во всех namespace'ах |
| `reloader.namespace` | `default` | Namespace для установки |
| `reloader.replicas` | `1` | Количество реплик |
| `reloader.resources` | `{}` | Ресурсы контроллера |

### Пример values.yaml

```yaml
# values.yaml

reloader:
  namespace: monitoring
  watchGlobally: true
  replicas: 1
  
  deployment:
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

---

## 2. Установка через манифесты

### Полный манифест установки

```yaml
# reloader-setup.yaml

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
          image: ghcr.io/stakater/reloader:v1.0.118
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

### Применение манифестов

```bash
kubectl apply -f reloader-setup.yaml
```

### Проверка установки

```bash
# Проверка статуса
kubectl get deployment reloader -n monitoring
kubectl describe deployment reloader -n monitoring

# Проверка подов
kubectl get pods -n monitoring -l app=reloader
```

---

## 3. Исключение namespace'ов

### При установке через Helm

```yaml
# values.yaml
reloader:
  args:
    - --namespaces-to-ignore=kube-system,kube-public,kube-node-lease
    - --namespaces-to-select=default,production,staging
```

### При установке через манифесты

```yaml
spec:
  containers:
    - args:
        - --namespaces-to-ignore=kube-system
        - --log-level=info
```

---

## 4. Связанные документы

- **[Обзор и концепции](./reloader_overview.md)** — базовые определения
- **[Сценарии использования](./reloader_usage_scenarios.md)** — практические примеры
- **[Мониторинг и отладка](./reloader_monitoring_and_best_practices.md)** — логи и диагностика
