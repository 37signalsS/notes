# Kustomize — Overlays and Patches

## 1. Definitions

**Overlay** — директория с `kustomization.yaml`, которая ссылается на `base/` или другой overlay и применяет патчи для создания окружение-специфичной конфигурации.

**Patch** — фрагмент YAML/JSON, изменяющий существующий Kubernetes-ресурс без модификации исходного файла. Kustomize поддерживает три формата патчей.

**Target** — селектор, определяющий какой ресурс изменяется (по `kind`, `name`, `label`, `group`, `version`).

## 2. Basic Concepts

### Типы патчей

| Тип | Формат | Когда использовать |
| :--- | :--- | :--- |
| **Strategic Merge Patch** | Полный YAML-объект ресурса | Простые изменения: replicas, image, env |
| **JSON Patch (RFC 6902)** | Массив операций `op/path/value` | Точечные изменения: вставка в массив, удаление поля |
| **Inline Patch** | Встроен в `kustomization.yaml` | Быстрые изменения без отдельного файла |

### Strategic Merge Patch

Создаётся частичный YAML-объект с полями, которые нужно изменить. Kubernetes выполняет стратегическое слияние:

```yaml
# Изменение replicas и добавление env
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: myapp
        env:
        - name: NEW_VAR
          value: "value"
```

### JSON Patch (RFC 6902)

Явные операции с JSON Pointer путями:

| Операция | Описание |
| :--- | :--- |
| `add` | Добавить поле/элемент массива |
| `replace` | Заменить значение поля |
| `remove` | Удалить поле |
| `copy` | Копировать значение |
| `move` | Переместить значение |

```yaml
- op: replace
  path: /spec/replicas
  value: 5
- op: add
  path: /spec/template/spec/containers/0/env/-
  value:
    name: FEATURE_FLAG
    value: "enabled"
```

### Inline Patch

Патч определяется прямо в `kustomization.yaml` — удобно для изменений в 1–3 строки:

```yaml
patches:
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 10
```

### Синтаксис target

```yaml
patches:
  - target:
      group: apps           # apiVersion group (опционально)
      version: v1           # apiVersion (опционально)
      kind: Deployment      # kind ресурса
      name: myapp           # metadata.name
      namespace: default    # metadata.namespace (опционально)
    patch: ...
```

## 3. Practical Scenarios

### 3.1. Базовый overlay для staging

```yaml
# overlays/staging/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

namespace: staging
namePrefix: staging-

patches:
  - path: replica-patch.yaml

images:
  - name: myregistry/myapp
    newTag: v1.2.0-rc1
```

```yaml
# overlays/staging/replica-patch.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 1
```

### 3.2. Multiple patches для production

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

namespace: production
namePrefix: prod-

patches:
  - path: replica-patch.yaml       # replicas: 5
  - path: resource-limits.yaml     # CPU/memory limits
  - path: monitoring-sidecar.yaml  # sidecar container
```

### 3.3. JSON Patch: добавление env в контейнер

```yaml
# overlays/production/add-env-patch.yaml
- op: add
  path: /spec/template/spec/containers/0/env
  value:
    - name: ENV
      value: production
    - name: LOG_LEVEL
      value: info
```

### 3.4. Patch через target: изменение specific контейнера

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Deployment
      name: api-server
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/resources/limits/cpu
        value: "2"
```

### 3.5. Patch всех Deployment одновременно

```yaml
# kustomization.yaml — без name в target
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /metadata/labels/app.kubernetes.io~1managed-by
        value: kustomize
```

Тильда `~1` в JSON Pointer заменяет `/` — это позволяет добавить label с `/` в имени.

### 3.6. ConfigMap и Secret patch через generator

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=warn
      - METRICS_ENABLED=true

secretGenerator:
  - name: db-credentials
    behavior: create
    literals:
      - username=prod_user
      - password=prod_pass
```

### 3.7. Переопределение image для разных окружений

```yaml
# overlays/staging/kustomization.yaml
images:
  - name: myregistry/myapp
    newTag: v1.2.0-staging

# overlays/production/kustomization.yaml
images:
  - name: myregistry/myapp
    newTag: v1.2.0
    digest: sha256:abc123...
```

### 3.8. Validation перед применением

Перед применением рекомендуется валидировать манифесты через [kubeconform](../kubeconform/index.md):

```bash
kubectl kustomize overlays/production | kubeconform -strict -summary -
```

Команды `kubectl kustomize` и `kubectl apply -k` описаны в [Overview and Core Concepts](./kustomize_overview.md).

## 4. Additional Information

### Выбор типа патча

| Критерий | Рекомендуемый тип |
| :--- | :--- |
| Изменение 1–2 полей | Inline patch |
| Простое изменение replicas/image | Strategic Merge |
| Добавление элемента в массив | JSON Patch |
| Сложная структура (env, volumes) | Strategic Merge |
| Удаление поля | JSON Patch (`remove`) |

### Ограничения

- **Нет условной логики** — патчи применяются всегда
- **Strategic Merge зависит от API Server** — поведение слияния зависит от типа ресурса
- **JSON Patch чувствителен к порядку** — сначала `add`, потом `replace`
- **Нет кросс-ресурсных патчей** — один патч = один ресурс

### Связь с базовыми концепциями

- [Overview and Core Concepts](./kustomize_overview.md) — базовые определения
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура проекта
- [Продвинутые возможности](./kustomize_advanced_features.md) — генерация ConfigMap/Secret
