# Kustomize — Структура проекта и синтаксис

В данном разделе рассматриваются правила организации файлов в Kustomize-проектах, синтаксис управляющего манифеста `kustomization.yaml` и внутренняя логика сборки ресурсов.

## 1. Определения

**База (Base)** — директория, содержащая набор стандартных Kubernetes-манифестов и файл `kustomization.yaml`. База представляет собой «чистый» фундамент конфигурации, который остается неизменным для всех производных оверлеев.

**Наложение (Overlay)** — директория, ссылающаяся на базу (или другое наложение) через блок `resources` и применяющая трансформации для конкретной среды (Development, Staging, Production).

**kustomization.yaml** — основной конфигурационный манифест, описывающий ресурсы, трансформации, генераторы и патчи. Наличие этого файла в директории является обязательным для признания её Kustomize-проектом.

**Компоненты (Components)** — (v4+) механизм для создания переиспользуемых фрагментов конфигурации, которые могут содержать ресурсы и патчи, позволяющий горизонтальное подмешивание логики.

**Валидаторы (Validators)** — (v5+) механизмы проверки итоговых манифестов на соответствие правилам (например, линтинг или проверка безопасности) перед завершением процесса сборки.

## 2. Основные концепции

### Типичная структура проекта

Для минимизации дублирования YAML-кода рекомендуется использовать иерархическую структуру «Base-Overlay»:

```text
kubernetes/
├── base/                   # Базовая конфигурация (общая логика)
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── kustomization.yaml
└── overlays/               # Специфика окружений
    ├── staging/
    │   ├── kustomization.yaml
    │   ├── replica-patch.yaml
    │   └── configmap-patch.yaml
    └── production/
        ├── kustomization.yaml
        ├── replica-patch.yaml
        └── resource-limits.yaml
```

### Полная структура kustomization.yaml (v5.x)

Пример файла, демонстрирующий современные возможности и поля API `kustomize.config.k8s.io/v1beta1`.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# --- 1. Ресурсы (Источники) ---
resources:
  - deployment.yaml
  - service.yaml
  - ../base                    # Локальная директория
  - https://github.com/org/repo//path?ref=v1.0 # Удаленный ресурс

# --- 2. Трансформации метаданных ---
namespace: production           # Установка Namespace для всех ресурсов
namePrefix: prod-               # Префикс к именам
nameSuffix: -v1                 # Суффикс к именам
commonLabels:                   # Метки для всех ресурсов и селекторов
  app: myapp
  managed-by: kustomize
commonAnnotations:              # Аннотации для всех ресурсов
  description: "Production deployment"

# --- 3. Генераторы (Генерация на лету) ---
configMapGenerator:
  - name: app-config
    literals:
      - KEY=value
    files:
      - nginx.conf
secretGenerator:
  - name: app-secret
    type: kubernetes.io/tls
    files:
      - tls.crt
      - tls.key

# --- 4. Модификации (Патчи и Образы) ---
patches:
  - path: replica-patch.yaml
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 3
images:
  - name: myregistry/myapp
    newTag: v1.2.0

# --- 5. Компоненты и Замены ---
components:
  - ../components/monitoring
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

# --- 6. Валидация и Опции ---
validators:
  - path: security-check.yaml
generatorOptions:
  disableNameSuffixHash: false
  labels:
    generated-by: kustomize
```

### Порядок выполнения трансформаций (Build Pipeline)

Kustomize применяет изменения в строго определенном порядке, независимо от последовательности полей в файле:

1.  **resources** — чтение и парсинг исходных файлов.
2.  **generators** — динамическое создание ConfigMap и Secret.
3.  **transformers (metadata)** — установка `namespace`, `namePrefix`, `nameSuffix`, `commonLabels`.
4.  **transformers (content)** — применение `patches`, `images`, `replacements`.
5.  **validators** — финальная проверка ресурсов перед выводом.

### Автоматическая сортировка ресурсов

Kustomize автоматически сортирует ресурсы в итоговом манифесте для обеспечения корректности их создания в Kubernetes (на основе GVK):

1.  **Namespace** (всегда первый).
2.  **ResourceQuota, LimitRange**.
3.  **CustomResourceDefinition (CRD)**.
4.  **ServiceAccount, RBAC (Roles, Bindings)**.
5.  **ConfigMap, Secret** (зависимости для подов).
6.  **Service**.
7.  **Workloads** (Deployment, StatefulSet, DaemonSet).
8.  **Ingress, Webhooks**.

## 3. Практические сценарии

### 3.1. Типы источников в блоке resources

| Тип | Синтаксис | Примечание |
| :--- | :--- | :--- |
| **Локальный файл** | `service.yaml` | Путь относительно `kustomization.yaml`. |
| **Директория** | `../base` | Ссылка на папку с `kustomization.yaml`. |
| **Удаленный URL** | `https://host/res.yaml` | Прямое скачивание YAML-файла. |
| **Git URL** | `github.com/org/repo//path?ref=v1` | `//` разделяет корень репо и путь к папке. |

### 3.2. Правила оформления базового слоя (Base)

Базовый слой должен быть самодостаточным и максимально гибким:
- **Никаких Namespace:** Не указывайте `namespace` в базе; это ограничит возможность деплоя базы в разные пространства имен оверлеями.
- **Отсутствие префиксов:** `namePrefix` и `nameSuffix` предназначены исключительно для уровня overlays.
- **Самодостаточность:** База должна успешно собираться командой `kustomize build .`.

**Пример base/kustomization.yaml:**
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
commonLabels:
  app: myapp
```

### 3.3. Remote base из Git с версионированием

Использование удаленной базы позволяет централизованно управлять манифестами для всей организации.

```yaml
# overlays/production/kustomization.yaml
resources:
  # Фиксация версии через ?ref= критически важна для стабильности CD
  - github.com/my-org/infra-base//k8s/base?ref=v2.1.0
namespace: production
namePrefix: prod-
```

### 3.4. Использование компонентов (Components)

Позволяет «подмешивать» опциональную функциональность (например, конфигурацию мониторинга) горизонтально.

```yaml
# kustomization.yaml
components:
  - ../components/prometheus
  - ../components/logging
```

## 4. Дополнительная информация

### Устаревшие поля (Legacy)

| Поле | Статус | Замена |
| :--- | :--- | :--- |
| `bases` | Удалено | Блок `resources`. |
| `patchesJson6902` | Deprecated | Блок `patches` с селектором `target`. |
| `patchesStrategicMerge` | Deprecated | Блок `patches` с указанием пути `path`. |
| `vars` | Удалено | Механизм `replacements` (для строгой типизации). |

### Советы для собеседования

**Вопрос:** Какова основная цель файла `kustomization.yaml` в Kustomize?
**Ответ:** Это декларативное руководство по эксплуатации. Он определяет состав ресурсов и цепочку трансформаций, необходимых для получения финального состояния кластера, позволяя управлять сложными настройками для разных сред без модификации исходных («золотых») базовых манифестов.

### Валидация и проверка
```bash
# 1. Рендеринг итогового манифеста
kustomize build .

# 2. Валидация против схем API Kubernetes через kubeconform
kustomize build . | kubeconform -strict -summary -
# → Результат: Summary: 8 resources found, 0 errors
```

### Связь с другими разделами
- **[Обзор и основные концепции](./kustomize_overview.md)** — введение и установка.
- **[Наложения и патчи](./kustomize_overlays_and_patches.md)** — подробнее о механизмах модификации.
- **[Продвинутые возможности](./kustomize_advanced_features.md)** — генераторы, замены и плагины.
- **[Валидация манифестов](./kustomize_testing_validation.md)** — conftest, snapshot, lint.
- **[Валидация манифестов (kubeconform)](../kubeconform_overview.md)** — подробнее о проверке схем.
