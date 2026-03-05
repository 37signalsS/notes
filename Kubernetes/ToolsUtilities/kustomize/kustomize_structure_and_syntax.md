# Kustomize — Структура проекта и синтаксис

## 1. Структура проекта

**Типичная структура:**

```
kubernetes/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── kustomization.yaml
└── overlays/
    ├── staging/
    │   ├── kustomization.yaml
    │   ├── replica-patch.yaml
    │   └── configmap-patch.yaml
    └── production/
        ├── kustomization.yaml
        ├── replica-patch.yaml
        └── resource-limits.yaml
```

## 2. Базовая конфигурация

### `base/deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: myapp
        image: myregistry/myapp:latest
        ports:
        - containerPort: 8080
        env:
        - name: CONFIG_PATH
          value: /etc/config
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
```

### `base/service.yaml`

```yaml
apiVersion: v1
kind: Service
metadata:
  name: myapp
spec:
  selector:
    app: myapp
  ports:
  - port: 80
    targetPort: 8080
  type: ClusterIP
```

### `base/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml

commonLabels:
  app: myapp
  managed-by: kustomize
```

## 3. Структура kustomization.yaml

**Базовая структура:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Ресурсы для включения
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml

# Общие метки
commonLabels:
  app: myapp
  environment: production

# Префиксы/суффиксы имён
namePrefix: prod-
nameSuffix: -v1

# Генерация ConfigMap
configMapGenerator:
  - name: app-config
    literals:
      - KEY=value

# Генерация Secret
secretGenerator:
  - name: app-secret
    literals:
      - username=admin
      - password=secret

# Патчи
patches:
  - path: replica-patch.yaml
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 3

# Изображения
images:
  - name: myregistry/myapp
    newTag: v1.2.0
    newName: newregistry/newapp
```

## 4. Staging overlay

### `overlays/staging/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: staging
namePrefix: staging-
commonLabels:
  environment: staging

resources:
  - ../../base

patches:
  - path: replica-patch.yaml
  - path: configmap-patch.yaml

images:
  - name: myregistry/myapp
    newTag: v1.2.0-staging

configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=debug
      - ENV=staging
```

### `overlays/staging/replica-patch.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 1
```

## 5. Production overlay

### `overlays/production/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: production
namePrefix: prod-
commonLabels:
  environment: production

resources:
  - ../../base

patches:
  - path: replica-patch.yaml
  - path: resource-limits.yaml

images:
  - name: myregistry/myapp
    newTag: v1.2.0

configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=info
      - ENV=production

secretGenerator:
  - name: app-secret
    behavior: create
    literals:
      - api-key=prod-secret-key
```

### `overlays/production/replica-patch.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 5
```

### `overlays/production/resource-limits.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  template:
    spec:
      containers:
      - name: myapp
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
```

## 6. Связанные документы

- **[Обзор и концепции](./kustomize_overview.md)** — базовые определения
- **[Наложения и патчи](./kustomize_overlays_and_patches.md)** — типы патчей
- **[Продвинутые возможности](./kustomize_advanced_features.md)** — генерация ConfigMap/Secret
