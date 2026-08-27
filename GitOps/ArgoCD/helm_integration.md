# Интеграция Argo CD с Helm

> **Актуальность (2026):** Argo CD v3.x: полная поддержка Helm 4, Server-Side Apply по умолчанию для больших чартов, OCI-нативность (v3.1+), Multiple Sources (v2.6+), Progressive Sync для ApplicationSets.

## Предварительные требования

1. **Kubernetes кластер:** v1.26+ (рекомендуется v1.28+).
2. **Argo CD установлен:** `kubectl get pods -n argocd` — все поды в статусе `Running`.
3. **Helm установлен:** v4.0+ (рекомендуется) или v3.10+ (legacy). Проверка: `helm version`.
4. **CLI `argocd`:** Установлен и настроен (`argocd login`).
5. **Git-репозиторий:** Доступен с манифестами или Helm-чартами.
6. **RBAC:** Администратор кластера для первоначальной настройки.

## Определения

**Helm** — пакетный менеджер для Kubernetes, использующий формат чартов для декларативного описания приложений.

**Helm-чарт (Chart)** — упакованный набор манифестов и шаблонов, описывающих связанные ресурсы Kubernetes.

**Файлы значений (Values)** — внешние параметры конфигурации, позволяющие адаптировать один чарт под разные окружения (dev, prod).

**OCI-артефакты (OCI Artifacts)** — современный стандарт упаковки и хранения Helm-чартов в Docker-реестрах (Harbor, AWS ECR, GitHub Container Registry).

**Multiple Sources** — механизм Argo CD (v2.6+), позволяющий объединять в одном приложении чарт из внешнего репозитория и конфигурации из приватного Git.

**AppProject** — логическая группировка приложений в Argo CD с ограничениями по источникам, целевым кластерам и namespace.

## Базовые концепции

### Архитектура рендеринга Helm в Argo CD

Argo CD рендерит Helm-чарты на стороне `argocd-repo-server`:

```
┌─────────────────────────────────────────────────────────────────┐
│              Argo CD + Helm: Pipeline рендеринга               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  Git / OCI   │───▶│ repo-server  │───▶│  K8s API     │      │
│  │  (Источник)  │    │ (Helm render)│    │  (Применение)│      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ Chart.yaml   │    │ helm template│    │  Resources   │      │
│  │ values.yaml  │    │ или хуки     │    │  (Deploy,    │      │
│  │ templates/   │    │ CMP плагин   │    │   Service...)│      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Процесс рендеринга:**
1. `argocd-repo-server` клонирует Git-репозиторий или скачивает чарт из OCI-реестра.
2. Выполняется `helm template` (или кастомный плагин через CMP).
3. Результат — готовые YAML-манифесты, которые применяются через K8s API.
4. Результат кешируется для ускорения повторных синхронизаций.

**Важно:** Argo CD **не выполняет** `helm install`/`helm upgrade`. Он только рендерит манифесты и применяет их через API Kubernetes. Это означает, что:
- Helm-релизы **не создаются** в кластере (нет записей в Secret `sh.helm.release`).
- Управление состоянием через Helm CLI невозможно.
- Для отката используется Argo CD Rollback, а не `helm rollback`.

### Подход 1: Нативная поддержка Helm-репозиториев

Argo CD выполняет рендеринг чарта (`helm template`) на стороне `argocd-repo-server`. В версии v3.x обеспечена полная поддержка **Helm 4**, что повышает безопасность за счет отказа от устаревших API.

**Helm 4 vs Helm 3:**

| Параметр | Helm 3 | Helm 4 |
| :--- | :--- | :--- |
| **Server-Side Apply** | Опционально | По умолчанию |
| **OCI-поддержка** | Базовая | Полная (стабильный API) |
| **Безопасность** | Устаревшие API | Отказ от legacy API |
| **Производительность** | Стандартная | Оптимизированный рендеринг |

#### Традиционный репозиторий (HTTPS)
```yaml
spec:
  source:
    repoURL: 'https://charts.bitnami.com/bitnami'
    chart: 'redis'
    targetRevision: 16.x.x
```

#### OCI-совместимый репозиторий
Для работы с OCI-реестрами необходимо предварительно настроить учетные данные в настройках Argo CD.

**1. Создание секрета для OCI-реестра:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: oci-registry-creds
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  url: ghcr.io/argoproj/charts
  username: <имя-пользователя>
  password: <токен>
  type: oci
```

**2. Применение секрета:**
```bash
kubectl apply -f oci-secret.yaml
```

**3. Манифест Application:**
```yaml
spec:
  source:
    repoURL: 'ghcr.io/argoproj/charts'
    chart: 'argo-cd'
    targetRevision: 5.x.x
```

**Нюансы v3.x:**
- **Производительность:** Repo-server кеширует результаты рендеринга, снижая нагрузку на Git и сеть.
- **Строгая валидация:** Поддержка `values.schema.json` включена по умолчанию.
- **OCI черезhelm registry login:** Для приватных реестров настройте credentials в `argocd-cm` или через Kubernetes Secret.

### Подход 2: Использование нескольких источников (Multiple Sources)

Это промышленный стандарт для GitOps-процессов. Он позволяет использовать публичный "золотой" чарт и хранить специфичные для компании `values.yaml` в отдельном закрытом репозитории.

```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
      helm:
        valueFiles:
          - $values/infra/redis/values-prod.yaml
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: HEAD
      ref: values # Алиас для обращения из первого источника
```

**Ключевые преимущества:**
- **Разделение ответственности:** Инфраструктурная команда управляет чартом, команды разработки — значениями.
- **Атомарность:** Все изменения конфигурации фиксируются в Git, обеспечивая полный аудит.
- **Безопасность:** Секреты и специфичная конфигурация хранятся в приватном репозитории, а не в публичном чарте.

**Пример: Multiple Sources с несколькими values-файлами:**
```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'postgresql'
      targetRevision: 12.x.x
      helm:
        valueFiles:
          - $values/apps/my-app/values-base.yaml
          - $values/apps/my-app/values-prod.yaml
          - $values/apps/my-app/values-secrets.yaml
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: main
      ref: values
```

**Важно:** Ссылка на значения из внешнего репозитория начинается с `$values/` (символ доллара + имя ref).

### Подход 3: Рендеринг манифестов в CI

Манифесты генерируются внешней системой (GitLab CI, GitHub Actions) и сохраняются в Git как чистый YAML.

**Когда использовать:**
- Требуется глубокое патчирование через Kustomize, которое невозможно средствами Helm.
- Необходимо сканирование манифестов (Trivy/Checkov) *до* их попадания в кластер.
- Используются сложные генераторы (например, Jsonnet), не поддерживаемые Argo CD нативно.

**Пример CI-пайплайна (GitHub Actions):**
```yaml
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Render Helm
      run: |
        helm dependency update charts/my-app
        helm template my-app charts/my-app \
          -f values/prod.yaml \
          --output-dir ./manifests

    - name: Scan manifests
      run: |
        trivy config ./manifests --severity CRITICAL,HIGH
        kubeconform ./manifests

    - name: Commit to GitOps repo
      run: |
        git add ./manifests
        git commit -m "chore: update manifests for prod"
        git push
```

## Продвинутая интеграция через плагины (CMP v2)

Для инструментов, выходящих за рамки стандартного `helm template` (например, Helmwave, Helmfile или расшифровка секретов через `helm-secrets`), используются **[Config Management Plugins](./argocd_custom_tooling.md)**.

**Сценарий использования Helmwave через CMP:**
1. В `repo-server` добавляется sidecar с бинарным файлом `helmwave`.
2. В манифесте `Application` указывается имя плагина.
3. Плагин выполняет сборку графа зависимостей и рендеринг всех ресурсов стека.

**Сравнение CMP v1 и CMP v2:**

| Характеристика | CMP v1 (Legacy) | CMP v2 (Modern) |
| :--- | :--- | :--- |
| **Архитектура** | Процесс в основном контейнере | Sidecar-контейнер |
| **Безопасность** | Общее пространство имен | Изолированный контейнер |
| **Зависимости** | Ограничены основным образом | Полная независимость |
| **Обнаружение** | Ручная настройка | Автоматическое (Discovery) |

Подробнее: **[Custom Tooling и плагины (CMP)](./argocd_custom_tooling.md)**.

## Масштабирование через ApplicationSet

Для управления сотнями однотипных Helm-приложений используется генератор `Git`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: helm-apps
  namespace: argocd
spec:
  generators:
  - git:
      repoURL: https://github.com/my-org/gitops-repo.git
      directories:
      - path: apps/*
  template:
    metadata:
      name: '{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: 'https://charts.example.com'
        chart: 'common-app-engine'
        targetRevision: 1.2.0
        helm:
          valueFiles:
          - '{{path}}/values.yaml'
      destination:
        server: https://kubernetes.default.svc
        namespace: production
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
        - CreateNamespace=true
```

**Типы генераторов для Helm:**

| Генератор | Описание | Пример использования |
| :--- | :--- | :--- |
| **Git** | Читает директории/ветки из Git | Микросервисы в разных папках |
| **List** | Статический список кластеров/окружений | dev, staging, prod |
| **Cluster** | Все подключенные кластеры | Multi-cluster развертывание |
| **Matrix** | Комбинация двух генераторов | Git + Cluster |
| **SCM Provider** | Динамическое создание из GitLab/GitHub API | Feature-ветки |

Подробнее: **[Синхронизация и политики](./synchronization.md)**.

## Специфичные Sync Options для Helm

В Argo CD существуют параметры, критичные для стабильного деплоя чартов:

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **SkipDryRunOnMissingResource=true** | Позволяет игнорировать ошибки `dry-run`, если чарт создает CRD и ресурсы на их основе в одной транзакции. Критично для первого деплоя Operators. | false |
| **IncludeMutationWebhook=true** | Учитывает изменения, вносимые мутирующими вебхуками, при выполнении diff. | false |
| **ServerSideApply=true** | Рекомендуется для чартов с огромными манифестами (например, Prometheus Operator) для обхода лимита аннотаций (256 KB). | false |
| **CreateNamespace=true** | Автоматическое создание целевого Namespace, если он отсутствует. | false |
| **Prune=true** | Удаление ресурсов в кластере, которых больше нет в Git. | false |
| **SelfHeal=true** | Автоматический откат ручных правок в кластере к состоянию в Git. | false |
| **RespectIgnoreDifferences=true** | Использование настроек `ignoreDifferences` не только для визуализации, но и при синхронизации. | false |
| **Replace=true** | Использование `kubectl replace` вместо `apply` (для ресурсов с неизменяемыми полями). | false |

**Пример использования:**
```yaml
spec:
  syncPolicy:
    syncOptions:
    - CreateNamespace=true
    - Prune=true
    - SelfHeal=true
    - ServerSideApply=true
    - SkipDryRunOnMissingResource=true
    - RespectIgnoreDifferences=true
```

**Взаимодействие параметров:**
- `SelfHeal=true` + `RespectIgnoreDifferences=true` — SelfHeal не перезаписывает поля из `ignoreDifferences`.
- `SkipDryRunOnMissingResource=true` + CRD Operators — позволяет.deployать CRD и ресурсы одновременно.
- `ServerSideApply=true` + большой чарт — обходит лимит аннотации `last-applied-configuration`.

## Практические сценарии

### Сценарий 1: Интеграция с Vault через AVP

Использование **Argo CD Vault Plugin** позволяет на лету подставлять секреты в Helm-шаблоны без их хранения в Git.

```yaml
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
      helm:
        valueFiles:
          - $values/apps/redis/values.yaml
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: HEAD
      ref: values
      plugin:
        name: argocd-vault-plugin
```

Подробнее: **[Интеграция с Vault](./argocd_vault_integration.md)**.

### Сценарий 2: Локальные зависимости чартов

Argo CD умеет автоматически запускать `helm dependency build`, если в репозитории обнаружен `Chart.lock`. Это позволяет использовать `file://` зависимости для локальных сабчартов.

```bash
# Структура репозитория
my-app/
├── Chart.yaml
├── Chart.lock
├── charts/
│   └── common-lib-0.1.0.tgz  # Локальный сабчарт
├── templates/
│   └── deployment.yaml
└── values.yaml
```

**Важно:** Argo CD автоматически обнаружит `Chart.lock` и выполнит `helm dependency build` перед рендерингом.

### Сценарий 3: Multi-environment с Values-Overlay

Использование разных values-файлов для dev, staging и prod окружений.

```yaml
# Application для dev
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-dev
spec:
  sources:
    - repoURL: 'https://charts.bitnami.com/bitnami'
      chart: 'redis'
      targetRevision: 16.8.9
    - repoURL: 'https://github.com/my-org/gitops-config.git'
      targetRevision: main
      ref: values
      helm:
        valueFiles:
          - $values/environments/dev/values.yaml
  destination:
    server: https://kubernetes-dev.example.com
    namespace: development
```

### Сценарий 4: Откат через Argo CD

Поскольку Argo CD не создает Helm-релизы, откат выполняется через Argo CD Rollback:

```bash
# Просмотр истории синхронизаций
argocd app history my-app

# Откат к предыдущей версии
argocd app rollback my-app

# Откат к конкретному коммиту
argocd app rollback my-app <commit-hash>
```

### Сценарий 5: Тестирование чарта перед деплоем

Валидация чарта перед применением в кластере:

```bash
# Локальный рендеринг
helm template my-app ./charts/my-app -f values/prod.yaml > rendered.yaml

# Валидация схемы
helm lint ./charts/my-app -f values/prod.yaml

# Dry-run в кластере (без реального применения)
helm template my-app ./charts/my-app -f values/prod.yaml | kubectl apply --dry-run=client -f -

# Проверка через Argo CD
argocd app diff my-app --local ./charts/my-app
```

## Диагностика и мониторинг

### Базовые команды диагностики

```bash
# Просмотр состояния приложения
argocd app get my-app

# Просмотр diff
argocd app diff my-app

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр логов repo-server (рендеринг Helm)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`Helm template failed`** | Ошибка в синтаксисе шаблонов Helm | Проверьте шаблоны локально: `helm template .` |
| **`values.yaml not found`** | Указан неверный путь к values-файлу | Проверьте путь в `valueFiles` и ссылки `$values/` |
| **`CRD not found`** | Чарт создает CRD и ресурсы одновременно | Добавьте `SkipDryRunOnMissingResource=true` |
| **`OCI login failed`** | Ошибка аутентификации в OCI-реестре | Проверьте секрет `repository` в namespace `argocd` |
| **`Chart dependency build failed`** | Ошибка сборки зависимостей | Проверьте `Chart.yaml` и доступность сабчартов |
| **`values.schema.json invalid`** | Несоответствие values-файла схеме | Проверьте values-файл по схеме чарта |
| **`ApplicationSet generation failed`** | Ошибка в шаблоне ApplicationSet | Проверьте переменные `{{path.basename}}` и генератор |

## Рекомендации и лучшие практики

### Производительность

- **Используйте Server-Side Apply:** Включайте `ServerSideApply=true` для чартов с манифестами >256 KB (обход лимита аннотаций).
- **Кеширование:** Repo-server кеширует результаты рендеринга. Используйте `targetRevision` с фиксированными версиями, а не `latest`.
- **Shallow Git Cloning:** Используйте `--depth` для монорепозиториев (>1000 файлов).

### Безопасность

- **Фиксация версий:** Запрещено использовать `targetRevision: latest`. Всегда фиксируйте Major или Minor версию для предсказуемости.
- **OCI-безопасность:** Используйте короткоживущие токены или IAM-роли для доступа к реестрам образов вместо статических паролей.
- **Сканер секретов:** Включайте `trivy config` и `kubeconform` в CI-пайплайны перед слиянием изменений в GitOps-репозиторий.
- **AppProject:** Всегда создавайте отдельные проекты для разных команд/окружений.

### Надежность

- **Миграция на Helm v4:** В 2026 году рекомендуется полностью отказаться от Helm v3 в пользу v4 из-за встроенной поддержки SSA и улучшенной работы с OCI.
- **Тестирование:** Включайте `helm lint` и `kubeconform` в CI-пайплайны перед слиянием изменений в GitOps-репозиторий.
- **Валидация схемы:** Используйте `values.schema.json` для автоматической проверки values-файлов.
- **Откат:** Используйте `argocd app rollback` вместо `helm rollback`, так как Argo CD не создает Helm-релизы.

## Ограничения и edge cases

### Ограничения

1. **Нет Helm-релизов:** Argo CD не создает записей в Secret `sh.helm.release`. Управление через Helm CLI невозможно.
2. **Лимит аннотаций:** Клиентский Apply ограничивает размер манифестов (256 KB). Для больших чартов используйте Server-Side Apply.
3. **Cross-namespace ресурсы:** Автоматическая синхронизация работает только в рамках одного namespace.
4. **ApplicationSet и `automated`:** Стандартный флаг `syncPolicy.automated` внутри шаблона ApplicationSet игнорируется. Решение о запуске синхронизации принимает контроллер `ApplicationSet`.
5. **Множественные ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.

### Edge Cases

1. **CRD и ресурсы в одной транзакции:** Если чарт создает CRD и ресурсы на их основе, добавьте `SkipDryRunOnMissingResource=true`.
2. **Мутирующие вебхуки:** Если в кластере есть вебхуки, изменяющие манифесты, добавьте `IncludeMutationWebhook=true` для корректного diff.
3. **Helm-зависимости из приватных источников:** Используйте `helm repo add` с credentials или Multiple Sources с отдельным секретом.
4. **OCI-реестры с самоподписанными сертификатами:** Добавьте CA-сертификат в `argocd-cm` через `tls.clientCAData`.
5. **Ручные правки через kubectl:** Argo CD автоматически откатит изменения при включенном `selfHeal=true`. Используйте `RespectIgnoreDifferences=true` для полей, которые можно менять вручную.
6. **Проблемы с зависимостями:** Если `Chart.lock` отсутствует, Argo CD не выполнит `helm dependency build`. Убедитесь, что зависимости собраны в CI.
7. **Откат при Progressive Sync:** Если приложение находится в процессе Progressive Sync, откат через Argo CD может нарушить логику раскатки.

## Дополнительная информация

### См. также

- [Обзор Argo CD](./argocd_overview.md)
- [Синхронизация и политики](./synchronization.md)
- [Custom Tooling и плагины (CMP)](./argocd_custom_tooling.md)
- [Официальная документация: Helm Support](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
- [Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md) — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- [Отслеживание ресурсов](./argocd_resource_tracking.md) — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- [Удаление и очистка](./argocd_deletion_and_cleanup.md) — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.

### Ссылки на базу знаний Helm

- [Обзор Helm](../Kubernetes/ToolsUtilities/Helm/helm_overview.md)
- [Структура Helm-чарта](../Kubernetes/ToolsUtilities/Helm/helm_chart_structure.md)
- [Основные команды и рабочий процесс](../Kubernetes/ToolsUtilities/Helm/helm_commands_and_workflow.md)
- [Зависимости и библиотечные чарты](../Kubernetes/ToolsUtilities/Helm/helm_dependencies_and_library_charts.md)
- [Шаблонизация в Helm](../Kubernetes/ToolsUtilities/Helm/helm_templating.md)
