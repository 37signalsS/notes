# Kustomize — Структура проекта и синтаксис

## 1. Определения

**База (Base)** — директория с набором стандартных Kubernetes-манифестов и файлом `kustomization.yaml`, которые не зависят от конкретного окружения. Базовый слой представляет собой фундамент конфигурации, который остается неизменным («чистым») для всех оверлеев.

**Наложение (Overlay)** — директория, ссылающаяся на базовый слой (или другой overlay) через блок `resources` и применяющая трансформации посредством патчей, генераторов и метаданных для конкретной среды (Development, Staging, Production).

**kustomization.yaml** — основной конфигурационный манифест, описывающий все ресурсы, трансформации, генераторы и патчи для данной директории. Если этот файл отсутствует, Kustomize игнорирует директорию. Это «точка сборки», определяющая финальный вид манифеста.

## 2. Основные концепции

### Типичная структура проекта

Использование Kustomize предполагает разделение общей логики и специфических настроек. Рекомендуемая структура выглядит следующим образом:

```
kubernetes/
├── base/                   # Базовая конфигурация
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── kustomization.yaml
└── overlays/               # Окружения
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

Ниже приведен пример файла со всеми ключевыми полями. Обратите внимание на использование унифицированного блока `patches` и механизма `replacements`.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# --- Ресурсы ---
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
  - ../base                    # Относительная ссылка на базовый слой
  - https://github.com/org/repo//path?ref=v1.0 # Удаленный ресурс (Kustomize 4.0+)

# --- Трансформации метаданных ---
namespace: production
namePrefix: prod-
nameSuffix: -v1
commonLabels:
  app: myapp
  managed-by: kustomize
commonAnnotations:
  description: "Production deployment"

# --- Генераторы (подробнее в Продвинутых возможностях) ---
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

# --- Патчи (Унифицированный синтаксис) ---
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

# --- Опции генераторов ---
generatorOptions:
  disableNameSuffixHash: false
  labels:
    generated-by: kustomize
  annotations:
    managed: "true"

# --- Компоненты ---
components:
  - ../components/monitoring
  - ../components/logging

# --- Замены (Replacements) — современная альтернатива vars ---
replacements:
  - source:
      kind: ConfigMap
      name: app-config
      fieldPath: data.version
    targets:
      - select:
          kind: Deployment
          name: myapp
        fieldPaths:
          - spec.template.metadata.labels.version
```

### Описание ключевых полей

| Поле | Назначение | Пример |
| :--- | :--- | :--- |
| `resources` | Список YAML-файлов, директорий или URL | `deployment.yaml`, `../base` |
| `namespace` | Пространство имен для всех ресурсов | `production` |
| `namePrefix` / `nameSuffix` | Префикс/суффикс к именам всех ресурсов | `prod-`, `-v1` |
| `commonLabels` | Метки для всех ресурсов и их селекторов | `app: myapp` |
| `commonAnnotations` | Аннотации для всех ресурсов | `managed-by: kustomize` |
| `configMapGenerator` | Динамическая генерация ConfigMap | См. [Продвинутые возможности](./kustomize_advanced_features.md) |
| `secretGenerator` | Динамическая генерация Secret | См. [Продвинутые возможности](./kustomize_advanced_features.md) |
| `patches` | Унифицированный блок для любых патчей | См. [Наложения и патчи](./kustomize_overlays_and_patches.md) |
| `images` | Переопределение имени/тега/хеша образа | `newTag: v1.2.0` |
| `generatorOptions` | Глобальные настройки генераторов | `disableNameSuffixHash: true` |
| `components` | Использование переиспользуемых модулей | `../components/monitoring` |
| `replacements` | Копирование данных между полями ресурсов | Замена устаревших `vars` |

### Ресурсы базового слоя (Base)

Поддерживаемые типы источников в блоке `resources`:

| Тип | Пример | Примечание |
| :--- | :--- | :--- |
| Локальный файл | `deployment.yaml` | Путь относительно `kustomization.yaml` |
| Относительный путь | `../base` | Ссылка на локальную директорию с манифестом |
| Удаленный URL | `https://example.com/k8s/res.yaml` | Прямая ссылка на YAML-файл |
| Git URL | `github.com/org/repo//path?ref=v1` | Параметр `?ref=` для веток/тегов |

### Практика: base/kustomization.yaml

Базовый слой должен быть самодостаточным и содержать только общие метаданные.

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

**Важное правило:** Базовый слой не должен содержать директивы `namespace`, `namePrefix` и `nameSuffix`. Эти трансформации предназначены исключительно для уровня overlays, чтобы не ограничивать гибкость использования базы.

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

Минимальный слой наложения (overlay) для наследования конфигурации:

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

Использование удаленной базы позволяет централизованно управлять манифестами для множества команд.

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

### 3.4. Использование компонентов (Components)

Компоненты (стабильны в актуальных версиях) позволяют «подмешивать» опциональную функциональность (например, конфигурацию Prometheus или лог-агентов).

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

Каждый компонент — это директория с `kustomization.yaml`, где указан `kind: Component`.

## 4. Дополнительная информация

### Порядок применения трансформаций и автоматическая сортировка

Kustomize применяет изменения в строго определенном порядке, независимо от последовательности полей в файле:

1. **resources** — чтение исходных файлов.
2. **generators** — создание ConfigMap и Secret.
3. **transformers (metadata)** — установка `namespace`, `namePrefix/Suffix`, `commonLabels`.
4. **transformers (resources)** — применение `patches`, `images`, `replacements`.
5. **generatorOptions** — применение финальных аннотаций/меток к сгенерированным ресурсам.

**Автоматическая сортировка ресурсов:**
Во время сборки (`kustomize build`) Kustomize автоматически выстраивает ресурсы в итоговом манифесте в логически правильном порядке:

- **Namespace** всегда идет первым.
- **ResourceQuota** и **LimitRange** следуют за ней.
- **CustomResourceDefinition (CRD)** помещаются в начало (после неймспейса), чтобы определения типов были в кластере до создания самих объектов.
- **ConfigMap** и **Secret** идут перед контроллерами (`Deployment`, `StatefulSet`).
- **Service** и **Ingress** обычно находятся в конце.

### Устаревшие поля (Legacy/Deprecated)

| Поле | Статус | Замена |
| :--- | :--- | :--- |
| `bases` | Удалено | Блок `resources` |
| `patchesJson6902` | Deprecated | Блок `patches` с селектором `target` |
| `patchesStrategicMerge` | Deprecated | Блок `patches` с указанием пути `path` |
| `vars` | Удалено | Механизм `replacements` |

### Валидация структуры

```bash
# Генерация и проверка синтаксиса
kustomize build .

# Валидация против схем API Kubernetes через kubeconform
kustomize build . | kubeconform -strict -summary -
# → Вывод: Summary: 5 resources found, 0 errors
```

### Связь с другими разделами

- [Обзор и основные концепции](./kustomize_overview.md) — базовые определения и установка.
- [Наложения и патчи](./kustomize_overlays_and_patches.md) — подробный разбор механизмов модификации.
- [Продвинутые возможности](./kustomize_advanced_features.md) — генераторы, Helm-интеграция и замены.
- [Валидация манифестов (kubeconform)](../kubeconform_overview.md) — подробнее о проверке схем.
