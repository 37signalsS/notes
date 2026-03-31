# Интеграция ArgoCD с Helm

См. также: [ArgoCD Overview](./argocd_overview.md), [Установка и настройка ArgoCD](./argocd_installation_and_setup.md), [Синхронизация](./synchronization.md).

## Определения

**Helm** — пакетный менеджер для Kubernetes, который использует формат чартов для описания приложений. ArgoCD предоставляет три подхода к интеграции с Helm.

## Базовые концепции

### Подход 1: Нативная поддержка Helm-чартов

ArgoCD напрямую ссылается на Helm-репозиторий и рендерит чарт во время синхронизации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: redis
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://charts.bitnami.com/bitnami'
    chart: 'redis'
    targetRevision: 16.8.9
    helm:
      values: |
        replica:
          replicaCount: 2
      parameters:
      - name: architecture
        value: standalone
  destination:
    server: https://kubernetes.default.svc
    namespace: redis
```

**Преимущества:**

- Простота начала работы
- Не требуется CI для генерации манифестов
- Автоматическое обновление при выходе новых версий чарта

**Недостатки:**

- Нарушение GitOps-модели: изменения в `values` требуют редактирования `Application`
- Нет истории изменений параметров в Git
- Затруднено добавление ресурсов вне чарта
- Один `Application` = один чарт

**Когда использовать:**

- Быстрое тестирование чартов
- Простые приложения без кастомизации
- Development-окружения

### Подход 2: `helm template` + Git (Рекомендуемый)

Генерация манифестов в CI и хранение их в Git.

**Процесс работы:**

1. Разработчики изменяют `values.yaml` в Git-репозитории
2. CI-пайплайн выполняет `helm template` и генерирует YAML-манифесты
3. Сгенерированные манифесты коммитятся в Git
4. ArgoCD синхронизирует изменения из Git

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/my-org/app-manifests.git'
    path: 'staging/my-app'
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Преимущества:**

- Чистый GitOps: вся история в Git
- Возможность добавления любых ресурсов в ту же директорию
- Комбинирование нескольких чартов в одном приложении
- Аудит и ревью всех изменений

**Недостатки:**

- Требуется CI-пайплайн для генерации
- Дублирование манифестов (чарт + сгенерированные YAML)

**Когда использовать:**

- Production-окружения
- Сложные приложения с кастомизацией
- Команды с строгими требованиями к аудиту

### Подход 3: Helm с параметрами (Hybrid)

Использование нативной поддержки Helm с хранением `values.yaml` в Git.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/my-org/helm-charts.git'
    path: 'charts/my-app'
    targetRevision: HEAD
    helm:
      valueFiles:
      - values.yaml
      - values-production.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
```

**Преимущества:**

- Баланс между простотой и GitOps
- `values.yaml` версионируются в Git
- Не требуется генерация манифестов

**Недостатки:**

- Ограниченная гибкость по сравнению с `helm template`

## Практические сценарии

### Сценарий 1: Развёртывание чарта из Helm-репозитория

```bash
# Создание приложения через CLI
argocd app create redis \
  --helm-chart redis \
  --repo https://charts.bitnami.com/bitnami \
  --revision 16.8.9 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace redis \
  --helm-set replica.replicaCount=2 \
  --sync-policy automated
```

### Сценарий 2: Использование локального Helm-чарта

```bash
# Генерация манифестов
helm template my-app ./charts/my-app \
  -f values-production.yaml \
  --output-dir ./manifests

# Коммит в Git
git add manifests/
git commit -m "Update manifests for my-app v1.2.0"
git push
```

### Сценарий 3: Комбинирование нескольких чартов

Создайте директорию с манифестами из разных чартов:

```
app-manifests/
├── redis/          # Манифесты из helm template redis
├── postgresql/     # Манифесты из helm template postgresql
└── app/            # Кастомные манифесты приложения
```

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: full-stack-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/my-org/app-manifests.git'
    path: '.'
    targetRevision: HEAD
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

### Сценарий 4: Parameter Overrides для разных окружений

```yaml
# values-dev.yaml
replica:
  replicaCount: 1
resources:
  limits:
    cpu: 100m
    memory: 128Mi

# values-prod.yaml
replica:
  replicaCount: 3
resources:
  limits:
    cpu: 500m
    memory: 512Mi
```

```yaml
# Application для dev
spec:
  source:
    helm:
      valueFiles:
      - values-dev.yaml

# Application для prod
spec:
  source:
    helm:
      valueFiles:
      - values-prod.yaml
```

## Дополнительная информация

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Версионирование чартов** | Фиксируйте версию чарта (`targetRevision: 16.8.9`, не `latest`) |
| **Хранение values в Git** | Все `values.yaml` файлы должны быть в Git |
| **Использование valueFiles** | Разделяйте общие и окруженческие значения |
| **Тестирование чартов** | Запускайте `helm lint` и `helm template` в CI |
| **Документирование** | Ведите CHANGELOG для изменений в чартах |

### Сравнение подходов

| Критерий | Нативный Helm | `helm template` + Git | Hybrid |
| :--- | :--- | :--- | :--- |
| **Простота** | Высокая | Средняя | Высокая |
| **GitOps-совместимость** | Низкая | Полная | Частичная |
| **Гибкость** | Низкая | Высокая | Средняя |
| **Аудит** | Низкий | Полный | Частичный |
| **Рекомендация** | Dev/Test | Production | Баланс |

[Официальная документация ArgoCD Helm](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/) и [Helm](https://helm.sh/docs/).
