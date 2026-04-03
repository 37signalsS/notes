# Kustomize — Project Structure and Syntax

## 1. Definitions

**Base** — директория с общими Kubernetes-манифестами и `kustomization.yaml`, не зависящими от окружения. Base не содержит overlay-специфичных изменений.

**Overlay** — директория, ссылающаяся на base (или другой overlay) через `resources` и применяющая трансформации через патчи, generators, метаданные.

**kustomization.yaml** — единственный манифест, описывающий все ресурсы, трансформации, генераторы и патчи для данной директории. Без него Kustomize игнорирует директорию.

## 2. Basic Concepts

### Типичная структура проекта

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

### Полная структура kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# --- Ресурсы ---
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
  - ../base                    # относительная ссылка на base
  - https://example.com/k8s    # remote resource (Kustomize 4.0+)

# --- Трансформации метаданных ---
namespace: production
namePrefix: prod-
nameSuffix: -v1
commonLabels:
  app: myapp
  managed-by: kustomize
commonAnnotations:
  description: "Production deployment"

# --- Генераторы ---
configMapGenerator:
  - name: app-config
    literals:
      - KEY=value
    # files:
    #   - nginx.conf
    # envs:
    #   - config.env

secretGenerator:
  - name: app-secret
    literals:
      - username=admin
      - password=secret
    # type: kubernetes.io/tls
    # behavior: create

# --- Патчи ---
patches:
  - path: replica-patch.yaml
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 3

# --- Изображения ---
images:
  - name: myregistry/myapp
    newTag: v1.2.0
    newName: newregistry/newapp
    # digest: sha256:abc123...

# --- Опции генераторов ---
generatorOptions:
  disableNameSuffixHash: false
  labels:
    generated-by: kustomize
  annotations:
    managed: "true"

# --- Ресурсы для удаления ---
# patchesJson6902:  # legacy, заменён на patches
#   - target:
#       group: apps
#       version: v1
#       kind: Deployment
#       name: myapp
#     path: json-patch.yaml

# --- Компоненты (alpha) ---
# components:
#   - ../components/monitoring
#   - ../components/logging

# --- Конфигурация трансформаций ---
# configurations:
#   - my-transformer-config.yaml

# --- Реплейсы (legacy) ---
# replacements:
#   - source:
#       kind: ConfigMap
#       name: app-config
#       fieldPath: data.version
#     targets:
#       - select:
#           kind: Deployment
#           name: myapp
#         fieldPaths:
#           - spec.template.metadata.labels.version
```

### Описание ключевых полей

| Поле | Назначение | Пример |
| :--- | :--- | :--- |
| `resources` | Список YAML-файлов или директорий | `deployment.yaml`, `../base` |
| `namespace` | Namespace для всех ресурсов | `production` |
| `namePrefix` | Префикс к именам ресурсов | `prod-` |
| `nameSuffix` | Суффикс к именам ресурсов | `-v1` |
| `commonLabels` | Labels для всех ресурсов + селекторы | `app: myapp` |
| `commonAnnotations` | Annotations для всех ресурсов | `description: "Production"` |
| `configMapGenerator` | Генерация ConfigMap | См. [Advanced Features](./kustomize_advanced_features.md) |
| `secretGenerator` | Генерация Secret | См. [Advanced Features](./kustomize_advanced_features.md) |
| `patches` | Патчи для ресурсов | См. [Overlays and Patches](./kustomize_overlays_and_patches.md) |
| `images` | Override image name/tag/digest | `newTag: v1.2.0` |
| `generatorOptions` | Настройки генераторов | `disableNameSuffixHash: true` |
| `components` | Переиспользуемые компоненты (alpha) | `../components/monitoring` |

### Base ресурсы

Поддерживаемые типы ресурсов в `resources`:

| Тип | Пример | Примечание |
| :--- | :--- | :--- |
| Локальный файл | `deployment.yaml` | Относительно kustomization.yaml |
| Относительный путь | `../base` | Ссылка на base/overlay |
| Remote URL | `https://example.com/k8s/resource.yaml` | Kustomize 4.0+ |
| Git URL | `github.com/org/repo//path?ref=v1.0` | Через `?ref=` для версии |

### Практика: base/kustomization.yaml

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

Base не должен содержать `namespace`, `namePrefix`, `nameSuffix` — эти трансформации применяются в overlays.

## 3. Practical Scenarios

### 3.1. Полный пример base

**base/deployment.yaml:**

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
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
```

**base/service.yaml:**

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

**base/kustomization.yaml:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - deployment.yaml
  - service.yaml

commonLabels:
  app: myapp
  managed-by: kustomize
```

### 3.2. Базовый overlay

Минимальный overlay для наследования от base:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: staging
namePrefix: staging-

resources:
  - ../../base

commonLabels:
  environment: staging
```

Полные примеры staging и production overlays с патчами, generators и images — в [Наложения и патчи](./kustomize_overlays_and_patches.md).

### 3.3. Remote base из Git

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - github.com/org/infrastructure//k8s/base?ref=v2.0.0

namespace: production
namePrefix: prod-

patches:
  - path: custom-patch.yaml
```

### 3.4. Использование components (alpha)

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

components:
  - ../components/prometheus
  - ../components/monitoring
```

Каждый компонент — отдельная директория со своим `kustomization.yaml` типа `kind: Component`.

## 4. Additional Information

### Порядок применения трансформаций

Kustomize применяет изменения в следующем порядке:

1. **resources** — загрузка ресурсов
2. **namePrefix/nameSuffix** — модификация имён
3. **namespace** — установка namespace
4. **commonLabels/commonAnnotations** — добавление метаданных
5. **patches** — наложение патчей
6. **images** — override образов
7. **configMapGenerator/secretGenerator** — генерация ресурсов
8. **generatorOptions** — финальные настройки генераторов

### Устаревшие поля

| Поле | Статус | Замена |
| :--- | :--- | :--- |
| `bases` | Удалено | `resources` |
| `patchesJson6902` | Deprecated | `patches` с `target` |
| `patchesStrategicMerge` | Deprecated | `patches` с `path` |
| `var` | Удалено | `replacements` |

### Валидация структуры

```bash
# Проверка kustomization.yaml
kustomize build .

# Валидация через kubeconform
kustomize build . | kubeconform -strict -summary -
```

### Связь с другими разделами

- [Overview and Core Concepts](./kustomize_overview.md) — базовые определения
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — типы патчей, полные staging/production примеры
- [Продвинутые возможности](./kustomize_advanced_features.md) — генерация ConfigMap/Secret, интеграция с Helm
