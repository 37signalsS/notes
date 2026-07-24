# Kustomize — Наложения и патчи (Overlays and Patches)

## 1. Определения

**Наложение (Overlay)** — директория с манифестом `kustomization.yaml`, которая ссылается на `base/` или другой overlay и применяет специфические для окружения изменения (патчи). Позволяет создавать иерархии конфигураций без дублирования исходных файлов.

**Патч (Patch)** — фрагмент YAML или JSON, изменяющий существующий Kubernetes-ресурс без модификации исходного манифеста. Kustomize поддерживает три основных формата патчей: Strategic Merge, JSON Patch и Inline.

**Цель (Target)** — селектор, определяющий набор ресурсов, к которым должен быть применен патч. Фильтрация осуществляется по группе API, версии, типу (kind), имени и пространству имен.

## 2. Основные концепции

### Типы патчей

| Тип | Формат | Сценарий использования |
| :--- | :--- | :--- |
| **Strategic Merge Patch** | YAML | Слияние на основе схем Kubernetes. Идеально для простых изменений: `replicas`, `image`, `env`. |
| **JSON Patch (RFC 6902)** | YAML/JSON | Массив операций `op/path/value`. Позволяет удалять поля, вставлять элементы в массивы по индексу. |
| **Inline Patch** | YAML/JSON | Встраивается прямо в `kustomization.yaml`. Удобно для небольших изменений (1–3 строки). |

### Strategic Merge Patch (Стратегическое слияние)

Это стандартный механизм слияния в Kubernetes. Он использует предопределенные ключи слияния (например, `name` для контейнеров) для обновления существующих списков вместо их полной замены.

**Директивы управления слиянием:**
Kustomize поддерживает специальные директивы для изменения логики слияния:
- `$patch: replace` — полностью заменяет список или объект вместо попытки слияния.
- `$patch: delete` — удаляет конкретный объект из списка (например, конкретный контейнер).

Пример изменения `replicas` и добавления `env`:
```yaml
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

### JSON Patch (RFC 6902) и JSON Pointer

Использует явные операции с путями. Kustomize поддерживает расширенный синтаксис YAML для JSON патчей.

**Операции:**
- `add`: добавить поле или элемент в массив.
- `replace`: заменить значение существующего поля.
- `remove`: удалить поле или элемент.
- `copy`: копировать значение из одного пути в другой.
- `move`: переместить значение.

**Экранирование в JSON Pointer:**
Если имя поля содержит `/` или `~`, необходимо использовать следующие замены:
- `/` → `~1`
- `~` → `~0`

Пример: `/metadata/annotations/app.kubernetes.io~1name`

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

### Inline Patch (Встроенный патч)

Патч определяется непосредственно внутри `kustomization.yaml`. Это современный и предпочтительный способ для небольших правок, так как он позволяет видеть изменения без открытия дополнительных файлов.

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

### Унифицированный синтаксис patches (v3.1.0+)

В актуальных версиях Kustomize блоки `patchesStrategicMerge` и `patchesJson6902` считаются устаревшими (deprecated). Рекомендуется использовать единый блок `patches`, который поддерживает оба формата и предоставляет мощные селекторы `target`.

```yaml
patches:
  - path: patch-file.yaml      # Файл со Strategic Merge или JSON патчем
    target:
      kind: Deployment
      labelSelector: "env=prod"
  - patch: |                   # Inline патч
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: unused           # Имя в селекторе выше имеет приоритет
      spec:
        replicas: 10
    target:
      name: myapp
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

В сложных проектах изменения разбиваются на файлы по смыслу:

```yaml
# overlays/production/kustomization.yaml
patches:
  - path: replica-patch.yaml       # Увеличение replicas: 5
  - path: resource-limits.yaml     # CPU/memory limits
  - path: monitoring-sidecar.yaml  # Добавление лог-агента или экспортера
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

### 3.4. Удаление полей и ресурсов

Для удаления специфических полей (например, `livenessProbe`) используется операция `remove`:

```yaml
# overlays/staging/remove-probe-patch.yaml
- op: remove
  path: /spec/template/spec/containers/0/livenessProbe
```

**Удаление ресурса целиком:**
Хотя Kustomize спроектирован для добавления и изменения ресурсов, полностью исключить ресурс из `base` можно через "хак" с JSON Patch (удаление обязательного поля `metadata/name` приводит к тому, что Kustomize отбрасывает ресурс):

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Service
      name: unused-service
    patch: |-
      - op: remove
        path: /metadata/name
```
*Рекомендация: Если ресурс не нужен в большинстве окружений, лучше вынести его из base и подключать только в нужных оверлеях через resources.*

### 3.5. Patch через target: изменение конкретного контейнера по индексу

В JSON Patch можно точно указать, какой контейнер в списке `containers` нужно изменить:

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

### 3.6. Массовый патчинг ресурсов по типу

Если в `target` не указано `name`, патч применится ко всем ресурсам данного `kind`. Это полезно для добавления общих меток или настроек безопасности.

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /metadata/labels/app.kubernetes.io~1managed-by
        value: kustomize
```

### 3.7. Патчинг ConfigMap и Secret через генераторы

Генераторы поддерживают директиву `behavior: merge`, которая позволяет патчить содержимое ConfigMap/Secret из базового слоя без замены всего ресурса.

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=warn
      - METRICS_ENABLED=true
```

### 3.8. Переопределение образов (Images)

Механизм `images` — это специализированный встроенный трансформатор, который работает быстрее и удобнее, чем ручные паттерны Strategic Merge.

```yaml
# overlays/production/kustomization.yaml
images:
  - name: myregistry/myapp
    newTag: v1.2.0
    digest: sha256:abc123...
```

### 3.9. Валидация перед применением

Перед деплоем в кластер критически важно проверить итоговый результат сборки.

```bash
# Валидация синтаксиса и схем Kubernetes через kubeconform
kubectl kustomize overlays/production | kubeconform -strict -summary -
# → Результат: Summary: 10 resources found, 0 errors
```

## 4. Дополнительная информация

### Выбор типа патча

| Задача | Рекомендуемый тип | Примечание |
| :--- | :--- | :--- |
| Изменение 1–2 полей | Inline patch | Самый быстрый способ. |
| Простое изменение replicas/image | Strategic Merge | Максимальная читаемость. |
| Добавление элемента в массив | JSON Patch / Strategic Merge | Strategic Merge проще, JSON точнее. |
| Сложная структура (env, volumes) | Strategic Merge | Позволяет описывать структуру YAML. |
| Удаление поля | JSON Patch (`remove`) | Strategic Merge не умеет удалять без директив. |

### Ограничения

- **Отсутствие условной логики** — патчи применяются всегда. Нельзя применить патч «только если ConfigMap существует».
- **Специфика CRD** — Strategic Merge может работать некорректно с Custom Resources, если у них не настроены ключи слияния в OpenAPI схеме (будет происходить замена списка целиком). Используйте JSON Patch для CRD.
- **Порядок применения** — патчи применяются последовательно в том порядке, в котором они перечислены в `patches`.
- **Экранирование** — ошибки в JSON Pointer (забытые `~1`) — частая причина неисправностей.

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения и установка.
- [Структура и синтаксис](./kustomize_structure_and_syntax.md) — структура `kustomization.yaml`.
- [Продвинутые возможности](./kustomize_advanced_features.md) — генерация ресурсов, компоненты и replacements.
