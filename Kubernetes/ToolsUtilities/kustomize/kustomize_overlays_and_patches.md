# Kustomize — Наложения и патчи (Overlays and Patches)

В данном разделе рассматриваются механизмы модификации ресурсов Kubernetes без изменения их исходных манифестов, что позволяет гибко адаптировать конфигурации под различные окружения (Dev, Staging, Prod).

## 1. Определения

**Наложение (Overlay)** — директория с манифестом `kustomization.yaml`, которая ссылается на «базу» (`base/`) или другой overlay и применяет специфические для окружения изменения. Позволяет создавать иерархии конфигураций без дублирования исходных файлов.

**Патч (Patch)** — инструкция по модификации существующего Kubernetes-ресурса. Kustomize поддерживает два основных метода: декларативное слияние (Strategic Merge) и точечные операции по спецификации RFC 6902 (JSON Patch).

**Цель (Target)** — селектор, определяющий набор ресурсов, к которым применяется патч. Фильтрация осуществляется по группе API, версии, типу (kind), имени, пространству имен, а также по меткам (`labelSelector`) и аннотациям.

## 2. Основные концепции

### Типы патчей

| Тип | Формат | Сценарий использования |
| :--- | :--- | :--- |
| **Strategic Merge Patch** | YAML | Слияние на основе схем Kubernetes. Идеально для простых изменений: `replicas`, `image`, `env`. |
| **JSON Patch (RFC 6902)** | YAML/JSON | Массив операций `op/path/value`. Позволяет удалять поля, вставлять элементы в массивы по индексу. |
| **Inline Patch** | YAML/JSON | Встраивается прямо в `kustomization.yaml`. Удобно для небольших правок в 1–3 строки. |

### Strategic Merge Patch (Стратегическое слияние)

Это стандартный механизм слияния в Kubernetes. Он использует предопределенные ключи слияния (например, `name` для контейнеров) для обновления существующих списков вместо их полной замены.

**Директивы управления слиянием:**
- `$patch: replace` — полностью заменяет список или объект вместо попытки слияния.
- `$patch: delete` — удаляет конкретный объект из списка (например, конкретный sidecar-контейнер).

*Пример изменения replicas и добавления переменной окружения:*
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

Использует явные операции с путями. Kustomize поддерживает расширенный синтаксис YAML для JSON патчей, что упрощает их чтение.

**Основные операции:**
- `add`: добавить поле или элемент в массив (используйте индекс или `-` для добавления в конец).
- `replace`: заменить значение существующего поля.
- `remove`: удалить поле или элемент (единственный способ полностью удалить блок, например `resources` или `livenessProbe`).
- `copy`: копировать значение из одного пути в другой.
- `move`: переместить значение (удаление из источника и добавление в цель).

**Экранирование в JSON Pointer:**
Если имя поля содержит `/` или `~`, необходимо использовать следующие замены в путях `path`:
- `/` → `~1`
- `~` → `~0`
*Пример:* `/metadata/annotations/app.kubernetes.io~1name`

### Унифицированный синтаксис patches (v3.1.0+)

Блоки `patchesStrategicMerge` и `patchesJson6902` считаются устаревшими (deprecated). Рекомендуется использовать единый блок `patches`, который поддерживает оба формата и предоставляет мощные селекторы `target`.

```yaml
patches:
  - path: patch-file.yaml      # Файл со Strategic Merge или JSON патчем
    target:
      kind: Deployment
      labelSelector: "env=prod"
  - patch: |                   # Inline патч (YAML формат)
      - op: replace
        path: /spec/replicas
        value: 10
    target:
      name: myapp
```

## 3. Практические сценарии

### 3.1. Базовый overlay для окружения staging

```yaml
# overlays/staging/kustomization.yaml
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

### 3.2. JSON Patch: Добавление элементов в массив

Добавление нескольких переменных окружения в первый контейнер:

```yaml
# overlays/production/add-env-patch.yaml
- op: add
  path: /spec/template/spec/containers/0/env/-
  value:
    name: ENV
    value: production
- op: add
  path: /spec/template/spec/containers/0/env/-
  value:
    name: LOG_LEVEL
    value: info
```

### 3.3. Удаление ресурсов через JSON Patch ("Hack")

Хотя Kustomize предназначен для композиции, исключить ресурс из базы можно, удалив его обязательное поле `metadata/name` через патч. Kustomize отбросит такой невалидный ресурс.

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
*Рекомендация: Для чистоты архитектуры лучше выносить такие ресурсы из `base` в отдельные компоненты.*

### 3.4. Точечная модификация контейнера по индексу

В сложных Deployment с несколькими контейнерами (sidecars) JSON Patch позволяет точно адресовать изменения:

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Deployment
      name: api-server
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/1/resources/limits/cpu
        value: "500m" # Изменение ресурсов именно во втором контейнере
```

### 3.5. Массовый патчинг по типу (Kind)

Если в `target` не указано `name`, патч применится ко всем ресурсам данного типа. Полезно для глобальных настроек безопасности.

```yaml
# kustomization.yaml
patches:
  - target:
      kind: Deployment
    patch: |-
      - op: add
        path: /spec/template/spec/securityContext/runAsNonRoot
        value: true
```

### 3.6. Патчинг через генераторы (behavior: merge)

Позволяет изменять содержимое ConfigMap/Secret из базы, сохраняя хеширование имен.

```yaml
# overlays/production/kustomization.yaml
configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=warn
```

### 3.7. Работа с Custom Resources (CRD)

Для CRD (например, Istio, Cert-manager) Strategic Merge часто работает как полная замена (`replace`), так как Kustomize не знает ключей слияния.
**Рекомендация:** Всегда используйте JSON Patch для CRD, чтобы гарантировать атомарность изменений.

```yaml
patches:
  - target:
      group: cert-manager.io
      kind: Certificate
    patch: |-
      - op: replace
        path: /spec/duration
        value: 2160h
```

### 3.8. Валидация сборки

```bash
# Проверка синтаксиса и схем через kubeconform
kustomize build overlays/production | kubeconform -strict -summary -
# → Summary: 15 resources found, 0 errors
```

## 4. Дополнительная информация

### Выбор метода модификации

| Задача | Рекомендуемый метод | Причина |
| :--- | :--- | :--- |
| Изменение простых полей | Strategic Merge | Наглядность YAML-структуры. |
| Удаление полей/ресурсов | JSON Patch (`remove`) | Strategic Merge не умеет удалять блоки без директив. |
| Работа с массивами по индексу | JSON Patch | Гарантированная точность. |
| Работа с CRD | JSON Patch | Исключает замену всего ресурса при отсутствии схем. |

### Ограничения и особенности

- **Отсутствие условной логики** — патчи применяются безусловно. Нельзя сделать патч «если ConfigMap существует».
- **Порядок применения** — патчи применяются строго в порядке их перечисления в списке `patches`.
- **Namespace и префиксы** — трансформации метаданных (namespace, namePrefix) применяются ДО патчей. Учитывайте это в селекторах `target`.
- **Экранирование** — ошибки в JSON Pointer (например, пропущенный `~1` вместо `/`) — самая частая причина «тихих» ошибок патчинга.

### См. также
- **[Обзор и основные концепции](./kustomize_overview.md)** — введение и установка.
- **[Структура и синтаксис](./kustomize_structure_and_syntax.md)** — разбор `kustomization.yaml`.
- **[Продвинутые возможности](./kustomize_advanced_features.md)** — генераторы, компоненты и replacements.
- **[Debugging Kustomize](./kustomize_debugging.md)** — диагностика ошибок патчинга.
- **[Работа с CRD](./kustomize_crd_patterns.md)** — JSON Patch для кастомных ресурсов.
