# Kustomize — Структура проекта и синтаксис

## 1. Определения

**Base (Базовый слой)** — директория с общими Kubernetes-манифестами и файлом `kustomization.yaml`, которые не зависят от конкретного окружения. Базовый слой не должен содержать специфичных для окружения изменений.

**Overlay (Слой наложения)** — директория, ссылающаяся на базовый слой (или другой overlay) через блок `resources` и применяющая трансформации посредством патчей, генераторов и метаданных.

**kustomization.yaml** — основной конфигурационный манифест, описывающий все ресурсы, трансформации, генераторы и патчи для данной директории. Если этот файл отсутствует, Kustomize игнорирует директорию.

## 2. Основные концепции

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
  - ../base                    # Относительная ссылка на базовый слой
  - https://example.com/k8s    # Удаленный ресурс (Remote resource, Kustomize 4.0+)

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

# --- Образы (Images) ---
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
# patchesJson6902:  # Устарело (legacy), заменено на patches
#   - target:
#       group: apps
#       version: v1
#       kind: Deployment
#       name: myapp
#     path: json-patch.yaml

# --- Компоненты (Alpha) ---
# components:
#   - ../components/monitoring
#   - ../components/logging

# --- Конфигурация трансформаций ---
# configurations:
#   - my-transformer-config.yaml

# --- Реплейсы (Устарело, legacy) ---
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
| `namespace` | Пространство имен для всех ресурсов | `production` |
| `namePrefix` | Префикс к именам ресурсов | `prod-` |
| `nameSuffix` | Суффикс к именам ресурсов | `-v1` |
| `commonLabels` | Метки для всех ресурсов + селекторы | `app: myapp` |
| `commonAnnotations` | Аннотации для всех ресурсов | `description: "Production"` |
| `configMapGenerator` | Генерация ConfigMap | См. [Продвинутые возможности](./kustomize_advanced_features.md) |
| `secretGenerator` | Генерация Secret | См. [Продвинутые возможности](./kustomize_advanced_features.md) |
| `patches` | Патчи для ресурсов | См. [Наложения и патчи](./kustomize_overlays_and_patches.md) |
| `images` | Переопределение имени/тега/хеша образа | `newTag: v1.2.0` |
| `generatorOptions` | Настройки генераторов | `disableNameSuffixHash: true` |
| `components` | Переиспользуемые компоненты (Alpha) | `../components/monitoring` |

### Ресурсы базового слоя (Base)

Поддерживаемые типы ресурсов в блоке `resources`:

| Тип | Пример | Примечание |
| :--- | :--- | :--- |
| Локальный файл | `deployment.yaml` | Путь относительно `kustomization.yaml` |
| Относительный путь | `../base` | Ссылка на локальную директорию |
| Удаленный URL | `https://example.com/k8s/resource.yaml` | Поддерживается с Kustomize 4.0+ |
| Git URL | `github.com/org/repo//path?ref=v1.0` | Версионирование через параметр `?ref=` |

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

Базовый слой не должен содержать директивы `namespace`, `namePrefix` и `nameSuffix` — эти трансформации должны применяться исключительно на уровне overlays.

## 3. Практические сценарии

### 3.1. Полный пример базового слоя

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

Минимальный слой наложения (overlay) для наследования конфигурации от базового слоя:

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

Более сложные примеры для staging и production с использованием патчей, генераторов и переопределением образов описаны в разделе [Наложения и патчи](./kustomize_overlays_and_patches.md).

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

### 3.4. Использование components (Alpha)

Компоненты позволяют создавать переиспользуемые блоки конфигурации.

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

Каждый компонент представляет собой отдельную директорию со своим собственным файлом `kustomization.yaml`, в котором указан тип `kind: Component`.

## 4. Дополнительная информация

### Порядок применения трансформаций и автоматическая сортировка

Kustomize применяет изменения в строго определенном порядке:

1. **resources** — загрузка всех указанных ресурсов.
2. **namePrefix/nameSuffix** — модификация имен ресурсов.
3. **namespace** — установка пространства имен.
4. **commonLabels/commonAnnotations** — добавление общих метаданных.
5. **patches** — применение всех патчей.
6. **images** — переопределение образов.
7. **configMapGenerator/secretGenerator** — генерация ConfigMap и Secret.
8. **generatorOptions** — применение финальных настроек к сгенерированным ресурсам.

**Автоматическая сортировка ресурсов:**
Во время сборки (`kustomize build`) Kustomize автоматически выстраивает ресурсы в итоговом манифесте в правильном порядке, независимо от того, в какой последовательности они были перечислены в `kustomization.yaml`.

- **CRD (CustomResourceDefinition)** всегда помещаются в начало итогового манифеста. Это гарантирует, что определения пользовательских ресурсов будут созданы в кластере до того, как будут применены сами пользовательские ресурсы, что предотвращает ошибки при развертывании.
- Стандартная последовательность развертывания обычно выглядит так: `Namespace` → `ResourceQuota` → `StorageClass` → `CustomResourceDefinition` → ... → `Deployment` → `Service`.

### Устаревшие поля (Legacy/Deprecated)

| Поле | Статус | Замена |
| :--- | :--- | :--- |
| `bases` | Удалено | Блок `resources` |
| `patchesJson6902` | Устарело (Deprecated) | Блок `patches` с использованием селектора `target` |
| `patchesStrategicMerge` | Устарело (Deprecated) | Блок `patches` с указанием пути `path` |
| `var` | Удалено | Механизм `replacements` |

### Валидация структуры

```bash
# Генерация манифестов (проверка синтаксиса kustomization.yaml)
kustomize build .
# → Вывод: полный объединенный YAML-файл

# Валидация сгенерированных манифестов через kubeconform
kustomize build . | kubeconform -strict -summary -
# → Вывод: Summary: 5 resources found, 0 errors
```

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — типы патчей и примеры окружений
- [Продвинутые возможности](./kustomize_advanced_features.md) — генерация ресурсов и интеграция с Helm
