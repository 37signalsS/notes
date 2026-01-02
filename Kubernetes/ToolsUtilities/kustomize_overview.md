### Определения

**Kustomize** — это нативный инструмент Kubernetes для декларативного управления конфигурациями. В отличие от шаблонизаторов, он позволяет настраивать Kubernetes-объекты, не затрагивая их оригинальные манифесты, путем наложения (overlay) патчей.

Kustomize встроен в `kubectl` (начиная с версии 1.14), что упрощает его использование.

### Основные концепции

*   **Декларативное управление:** Все изменения описываются в файлах `kustomization.yaml`, что делает конфигурацию версионируемой и легко отслеживаемой в Git.
*   **Принцип наложения (Overlays):** Позволяет создавать специфичные для окружений конфигурации (например, `development`, `production`), накладывая патчи на общую "базовую" конфигурацию. Это реализует принцип DRY (Don't Repeat Yourself).
*   **Генерация ресурсов:** Способен генерировать `ConfigMap` и `Secret` из файлов или литералов.
*   **Манипуляция метаданными:** Автоматически добавляет префиксы/суффиксы к именам и общие метки для всех ресурсов, что полезно для изоляции окружений.

### Практические сценарии

#### 1. Структура проекта

Типичная структура проекта включает базовую конфигурацию (`base`) и несколько наложений (`overlays`) для разных окружений.

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

#### 2. Базовая конфигурация (`base`)

Файлы в `base` содержат общие, неспецифичные для окружения манифесты.

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
Определяет ресурсы, входящие в базу.
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml
```

#### 3. Наложения (`overlays`)

Директории `overlays` содержат специфичные для окружений изменения. Каждое наложение ссылается на `base` и применяет патчи.

**Staging (`overlays/staging/kustomization.yaml`):**
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

**Production (`overlays/production/kustomization.yaml`):**
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
**Пример патча для Production (`overlays/production/resource-limits.yaml`):**
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

#### 4. Применение конфигурации

Для применения конфигурации используется флаг `-k` в `kubectl`.

```bash
# Применение Staging конфигурации
kubectl apply -k overlays/staging/

# Применение Production конфигурации
kubectl apply -k overlays/production/

# Просмотр результата без применения (Dry Run)
kubectl kustomize overlays/production/
```

### Дополнительная информация

Kustomize часто используется совместно с Helm. Такой гибридный подход, где Helm генерирует базовые манифесты (`helm template`), а Kustomize накладывает на них специфичные для окружения патчи, подробно рассмотрен в разделе о [структуре проекта с Helm и Kustomize](../ToolsUtilities/helm_overview.md#структура-проекта-с-helm-и-kustomize).
