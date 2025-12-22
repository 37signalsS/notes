# Kustomize: Декларативное управление конфигурациями Kubernetes

**Kustomize** — это нативный инструмент Kubernetes для декларативного управления конфигурациями, который позволяет настраивать Kubernetes-объекты, не затрагивая их оригинальные манифесты. Он работает по принципу "наложения" (overlay), позволяя вносить изменения в базовые конфигурации для различных окружений (development, staging, production).

В отличие от таких шаблонизаторов, как Helm, Kustomize не использует шаблоны в традиционном смысле. Вместо этого он модифицирует существующие YAML-манифесты путем добавления, удаления или изменения полей.

## Ключевые возможности

*   **Декларативное управление:** Все изменения описываются в `kustomization.yaml` файлах, что делает конфигурацию версионируемой и легко отслеживаемой в Git.
*   **"Наложения" (Overlays):** Позволяет создавать специфичные для окружений конфигурации, накладывая патчи на общую "базовую" конфигурацию. Это реализует принцип DRY (Don't Repeat Yourself).
*   **Генерация ресурсов:** Может генерировать ConfigMaps и Secrets из файлов или литералов.
*   **Изменение имен и меток:** Автоматически добавляет префиксы/суффиксы к именам и меткам ресурсов, что полезно для изоляции окружений.
*   **Встроенная поддержка:** Kustomize является частью `kubectl` (начиная с версии 1.14), что упрощает его использование и интеграцию в рабочие процессы.

## Пример структуры Kustomize

Типичная структура проекта с Kustomize включает базовую конфигурацию (`base`) и несколько наложений (`overlays`) для разных окружений.

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

### Базовая конфигурация (`base`)

Файлы в директории `base` содержат общие, неспецифичные для окружения манифесты.

**`base/deployment.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 2  # Базовое значение, переопределяется в overlays
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
```

**`base/kustomization.yaml`:**
Этот файл определяет, какие ресурсы входят в базовую конфигурацию.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
```

### Наложения (`overlays`)

Директории `overlays` содержат специфичные для окружений изменения. Каждое наложение ссылается на `base` и применяет к нему свои патчи.

#### Staging окружение

**`overlays/staging/kustomization.yaml`:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: staging            # Создать ресурсы в namespace 'staging'
namePrefix: staging-          # Добавить префикс 'staging-' к именам ресурсов
commonLabels:                 # Добавить общие метки ко всем ресурсам
  environment: staging
resources:
  - ../../base                # Ссылка на базовую конфигурацию
patches:                      # Список патчей для применения
  - path: replica-patch.yaml
  - path: configmap-patch.yaml
images:                       # Переопределение тегов образов
  - name: myregistry/myapp
    newTag: v1.2.0-staging
```

**`overlays/staging/replica-patch.yaml`:**
Этот патч изменяет количество реплик для `Deployment`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 2
```

#### Production окружение

**`overlays/production/kustomization.yaml`:**

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
```

**`overlays/production/replica-patch.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 5
```

**`overlays/production/resource-limits.yaml`:**
Этот патч добавляет или изменяет лимиты ресурсов для контейнера.

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

## Применение конфигурации

Для применения конфигурации используется `kubectl apply -k`.

```bash
# Применение Staging конфигурации
kubectl apply -k overlays/staging/

# Применение Production конфигурации
kubectl apply -k overlays/production/

# Просмотр результата без применения (Dry Run)
kubectl kustomize overlays/production/
```

## Интеграция с Helm

Kustomize часто используется в связке с Helm для управления сложными конфигурациями. Helm используется для генерации базовых манифестов из чарта (`helm template`), а Kustomize затем применяется для наложения специфичных для окружения патчей на эти сгенерированные манифесты.

**Подробнее:** [Helm: пакетный менеджер для Kubernetes#структура-проекта-с-helm-и-kustomize](../ToolsUtilities/helm_overview.md#структура-проекта-с-helm-и-kustomize)
