# Kustomize — Наложения и патчи (Overlays and Patches)

## 1. Определения

**Overlay** — директория с манифестом `kustomization.yaml`, которая ссылается на `base/` или другой overlay и применяет специфичные для окружения изменения (патчи).

**Patch** — фрагмент YAML/JSON, изменяющий существующий Kubernetes-ресурс без модификации исходного файла. Kustomize поддерживает три основных формата патчей.

**Target** — селектор (цель), определяющий, какой именно ресурс должен быть изменен патчем (на основе `kind`, `name`, `label`, `group`, `version`).

## 2. Основные концепции

### Типы патчей

| Тип | Формат | Сценарий использования |
| :--- | :--- | :--- |
| **Strategic Merge Patch** | Частичный YAML-объект ресурса | Простые изменения: количество реплик (replicas), замена образа (image), переменные окружения (env). |
| **JSON Patch (RFC 6902)** | Массив операций `op/path/value` | Точечные изменения: вставка элемента в массив, удаление конкретного поля. |
| **Inline Patch** | Встраивается прямо в `kustomization.yaml` | Быстрые небольшие изменения без создания отдельных файлов. |

### Strategic Merge Patch

При использовании Strategic Merge Patch создается YAML-файл, содержащий только те поля, которые необходимо добавить или изменить. Kubernetes автоматически выполняет стратегическое слияние с базовым ресурсом:

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

Использует явные операции с путями в формате JSON Pointer:

| Операция | Описание |
| :--- | :--- |
| `add` | Добавить поле или элемент массива |
| `replace` | Заменить значение существующего поля |
| `remove` | Удалить поле |
| `copy` | Копировать значение (редко используется) |
| `move` | Переместить значение (редко используется) |

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

Патч определяется непосредственно внутри `kustomization.yaml`. Это удобно для небольших изменений (в 1–3 строки), чтобы не плодить лишние файлы:

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

### Синтаксис target (селектор)

Блок `target` позволяет гибко выбирать ресурсы, к которым будет применен патч:

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

## 3. Практические сценарии

### 3.1. Базовый overlay для окружения staging

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

### 3.2. Множественные патчи для production

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

### 3.4. JSON Patch: удаление поля или ресурса

Для удаления специфических полей (например, `livenessProbe`) в конкретном окружении используется операция `remove`:

```yaml
# overlays/staging/remove-probe-patch.yaml
- op: remove
  path: /spec/template/spec/containers/0/livenessProbe
```

**Удаление ресурса целиком:**
Хотя Kustomize спроектирован для добавления и изменения ресурсов, полностью удалить ресурс из `base` можно через JSON Patch с фильтрацией или через пустой патч с операцией `remove` в `kustomization.yaml`:

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Service
      name: unused-service
    patch: |-
      - op: remove
        path: /metadata/name  # Нестандартный способ, лучше исключать из resources
```

*Примечание: Если ресурс не нужен в большинстве окружений, лучше не включать его в `base`, а добавлять только в нужные `overlays` через список `resources`.*

### 3.5. Patch через target: изменение конкретного контейнера

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

### 3.6. Patch всех Deployment одновременно

```yaml
# kustomization.yaml — без указания name в target
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /metadata/labels/app.kubernetes.io~1managed-by
        value: kustomize
```

Символы `~1` в JSON Pointer заменяют слэш `/`. Это позволяет добавить метку, содержащую `/` в имени ключа (например, `app.kubernetes.io/managed-by`).

### 3.7. Использование generator для патчинга ConfigMap и Secret

Генераторы также могут использовать поведение объединения (`merge`) для частичной перезаписи базовых конфигураций:

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

### 3.8. Переопределение образа (image) для разных окружений

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

### 3.9. Валидация перед применением

Перед применением в кластер рекомендуется проверять корректность манифестов через [kubeconform](../kubeconform/kubeconform_overview.md):

```bash
kubectl kustomize overlays/production | kubeconform -strict -summary -
# → Вывод: Summary: 10 resources found, 0 errors
```

Команды `kubectl kustomize` и `kubectl apply -k` описаны в [Обзор и основные концепции](./kustomize_overview.md).

## 4. Дополнительная информация

### Выбор типа патча

| Критерий | Рекомендуемый тип |
| :--- | :--- |
| Изменение 1–2 полей | Inline patch |
| Простое изменение replicas/image | Strategic Merge |
| Добавление элемента в массив | JSON Patch |
| Сложная структура (env, volumes) | Strategic Merge |
| Удаление поля | JSON Patch (`remove`) |

### Ограничения

- **Отсутствие условной логики** — патчи применяются всегда и безусловно.
- **Strategic Merge зависит от API Server** — поведение слияния может отличаться в зависимости от типа ресурса в кластере.
- **JSON Patch чувствителен к порядку** — например, при работе со списками сначала следует выполнять `add`, а затем `replace`.
- **Отсутствие кросс-ресурсных патчей** — один патч применяется к одному ресурсу (или группе однотипных ресурсов через селектор `target`).

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура проекта
- [Продвинутые возможности](./kustomize_advanced_features.md) — генерация ConfigMap и Secret
