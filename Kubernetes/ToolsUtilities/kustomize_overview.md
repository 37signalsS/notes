# Kustomize

## 1. Определения

**Kustomize** — это нативный инструмент Kubernetes для декларативного управления конфигурациями. В отличие от шаблонизаторов (Helm), он позволяет настраивать Kubernetes-объекты без изменения оригинальных манифестов, используя механизм наложения патчей (overlays).

**Встроен в kubectl:** Начиная с версии 1.14, Kustomize встроен в `kubectl` (команда `kubectl kustomize`).

## 2. Основные концепции

### Декларативное управление

Все изменения описываются в файлах `kustomization.yaml`, что делает конфигурацию:
- **Версионируемой** — хранится в Git вместе с кодом
- **Отслеживаемой** — история изменений в Git
- **Повторяемой** — одинаковый результат при каждом применении

### Принцип наложения (Overlays)

Создание специфичных для окружений конфигураций путём наложения патчей на общую базовую конфигурацию.

```
                    ┌─────────────────┐
                    │      base/      │
                    │  (общая конф.)  │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
            v                v                v
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │  staging/  │  │ production/│  │   local/   │
     │  (overlay) │  │  (overlay) │  │  (overlay) │
     └────────────┘  └────────────┘  └────────────┘
```

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Генерация ресурсов** | Создание ConfigMap и Secret из файлов или литералов |
| **Манипуляция метаданными** | Добавление префиксов/суффиксов к именам ресурсов |
| **Общие метки** | Добавление labels ко всем ресурсам |
| **Патчи** | Изменение существующих ресурсов (JSON/RFC 6902, strategic merge) |
| **Компоненты** | Переиспользуемые фрагменты конфигурации (alpha) |
| **Варианты (variants)** | Альтернативные конфигурации для одного окружения |

### Структура kustomization.yaml

**Базовая структура:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

# Ресурсы для включения
resources:
  - deployment.yaml
  - service.yaml
  - configmap.yaml

# Общие метки
commonLabels:
  app: myapp
  environment: production

# Префиксы/суффиксы имён
namePrefix: prod-
nameSuffix: -v1

# Генерация ConfigMap
configMapGenerator:
  - name: app-config
    literals:
      - KEY=value

# Генерация Secret
secretGenerator:
  - name: app-secret
    literals:
      - username=admin
      - password=secret

# Патчи
patches:
  - path: replica-patch.yaml
  - target:
      kind: Deployment
      name: myapp
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 3

# Изображения
images:
  - name: myregistry/myapp
    newTag: v1.2.0
    newName: newregistry/newapp
```

## 3. Практические сценарии

### 3.1. Структура проекта

**Типичная структура:**

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

### 3.2. Базовая конфигурация

**`base/deployment.yaml`:**

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
        env:
        - name: CONFIG_PATH
          value: /etc/config
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
```

**`base/service.yaml`:**

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

**`base/kustomization.yaml`:**

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

### 3.3. Staging overlay

**`overlays/staging/kustomization.yaml`:**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: staging
namePrefix: staging-
commonLabels:
  environment: staging

resources:
  - ../../base

patches:
  - path: replica-patch.yaml
  - path: configmap-patch.yaml

images:
  - name: myregistry/myapp
    newTag: v1.2.0-staging

configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=debug
      - ENV=staging
```

**`overlays/staging/replica-patch.yaml`:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 1
```

### 3.4. Production overlay

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

configMapGenerator:
  - name: app-config
    behavior: merge
    literals:
      - LOG_LEVEL=info
      - ENV=production

secretGenerator:
  - name: app-secret
    behavior: create
    literals:
      - api-key=prod-secret-key
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

### 3.5. Применение конфигурации

**Просмотр результата (dry-run):**

```bash
# Просмотр сгенерированных манифестов
kubectl kustomize overlays/production/

# Сохранение в файл
kubectl kustomize overlays/production/ > manifests.yaml
```

**Применение к кластеру:**

```bash
# Применение staging конфигурации
kubectl apply -k overlays/staging/

# Применение production конфигурации
kubectl apply -k overlays/production/
```

**Удаление:**

```bash
kubectl delete -k overlays/staging/
```

### 3.6. Патчи различных типов

**Strategic Merge Patch (полный объект):**

```yaml
# patches/deployment-patch.yaml
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

**JSON Patch (RFC 6902):**

```yaml
# patches/json-patch.yaml
- op: replace
  path: /spec/replicas
  value: 5
- op: add
  path: /spec/template/spec/containers/0/env/-
  value:
    name: FEATURE_FLAG
    value: "enabled"
```

**Патч через inline (в kustomization.yaml):**

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

### 3.7. Генерация ConfigMap и Secret

**Из литералов:**

```yaml
configMapGenerator:
  - name: app-config
    literals:
      - DATABASE_URL=postgres://localhost:5432/db
      - CACHE_TTL=3600

secretGenerator:
  - name: db-secret
    literals:
      - username=admin
      - password=S3cr3t
```

**Из файлов:**

```yaml
configMapGenerator:
  - name: nginx-config
    files:
      - nginx.conf

secretGenerator:
  - name: tls-secret
    files:
      - tls.crt
      - tls.key
    type: kubernetes.io/tls
```

**С поведением (behavior):**

```yaml
configMapGenerator:
  - name: app-config
    behavior: merge  # merge, replace, create
    literals:
      - NEW_KEY=new_value
```

### 3.8. Интеграция с Helm

**Гибридный подход:**

```bash
# Генерация базовых манифестов из Helm
helm template my-chart > base/manifest.yaml

# Создание kustomization.yaml для base
cat > base/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - manifest.yaml
EOF

# Применение overlay через kustomize
kubectl apply -k overlays/production/
```

**Подробнее:** [Интеграция Helm + Kustomize](./Helm/helm_advanced_topics.md#2-гибридное-использование-с-kustomize)

### 3.9. Валидация с kubeconform

```bash
# Валидация результата kustomize
kubectl kustomize overlays/production | kubeconform -summary -

# Или в одном шаге
kubectl kustomize overlays/production | kubeconform -strict -
```

## 4. Дополнительная информация

### Версии API Kustomize

| API Version | Kubernetes | Примечание |
| :--- | :--- | :--- |
| **kustomize.config.k8s.io/v1beta1** | 1.14+ | Текущая стабильная |
| **kustomize.config.k8s.io/v1alpha1** | 1.14-1.20 | Устаревшая |

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| kubectl | 1.14+ | Встроенная версия |
| kustomize CLI | 5.0+ | Отдельная установка |

### Установка kustomize CLI

```bash
# Linux
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
sudo mv kustomize /usr/local/bin/

# macOS
brew install kustomize

# Проверка версии
kustomize version
```

### Лучшие практики

1. **Храните base в отдельной директории** — изоляция общей конфигурации
2. **Используйте именованные патчи** — понятные имена файлов патчей
3. **Избегайте сложной логики** — для сложных случаев рассмотрите Helm
4. **Валидируйте результат** — используйте kubeconform перед применением
5. **Версионируйте всё в Git** — полный аудит изменений

### Ограничения

- **Нет условной логики** — в отличие от Helm шаблонов
- **Нет циклов** — нельзя генерировать множество одинаковых ресурсов
- **Простые трансформации** — сложные изменения требуют множественных патчей

### Сравнение с Helm

| Характеристика | Kustomize | Helm |
| :--- | :--- | :--- |
| **Шаблонизация** | ❌ Нет | ✅ Есть (Go templates) |
| **Наложение патчей** | ✅ Встроенное | ❌ Через values |
| **Встроен в kubectl** | ✅ Да | ❌ Нет |
| **Условная логика** | ❌ Нет | ✅ Есть |
| **Пакетный менеджер** | ❌ Нет | ✅ Есть (чарты) |
| **Сложность** | Низкая | Средняя/Высокая |

### Связанные документы

- **[Helm](./Helm/helm_overview.md)** — шаблонизация и пакетный менеджер
- **[kubeconform](./kubeconform.md)** — валидация манифестов
- **[ConfigMap](../Base/ConfigMap/pod_usage.md)** — использование ConfigMap
- **[GitOps](../../GitOps/GitOps_overview.md)** — применение в GitOps

### Репозиторий и документация

- [GitHub: kubernetes-sigs/kustomize](https://github.com/kubernetes-sigs/kustomize)
- [Официальная документация](https://kustomize.io/)
- [kubectl kustomize](https://kubectl.docs.kubernetes.io/references/kubectl/kustomize/)
