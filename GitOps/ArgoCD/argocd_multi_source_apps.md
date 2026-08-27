# Argo CD: Multiple Sources и sourceHydrator

> **Актуальность (2026):** Multiple Sources (v2.6+) позволяют объединять в одном приложении Helm-чарт из внешнего репозитория и values-файлы из Git-репозитория. sourceHydrator (v3.x) — новый механизм для git-оптимизированных конфигураций, который генерирует манифесты в отдельном ветвлении и синхронизирует их через HTTP. Архитектура Multiple Sources: repo-server клонирует оба источника, рендерит Helm и применяет результат.

## Предварительные требования

1. **Argo CD v2.6+** (для Multiple Sources) или **v3.x** (для sourceHydrator).
2. **Helm-репозиторий** или OCI-реестр с чартами.
3. **Git-репозиторий** с values-файлами.
4. **argocd CLI** настроен.
5. **Понимание Helm интеграции** (см. [Helm Integration](./helm_integration.md)).

## Определения

**Multiple Sources** — механизм Argo CD (v2.6+), позволяющий приложению использовать несколько источников: например, Helm-чарт из одного репозитория и values-файлы из другого. При рендеринге repo-server клонирует все источники и объединяет их.

**Source Hydrator (Гидратор источников)** — компонент v3.x, который рендерит манифесты из Helm/Kustomize и записывает их в отдельную Git-ветку (обычно `hydrated`), а контроллер синхронизирует из неё. Позволяет изолировать CI/CD от контура и обеспечивать audit trail.

**Ref (Ссылка на источник)** — поле `ref` в манифесте Application, ссылающееся на другой источник (Git-репозиторий или Helm-чарт). Используется для обозначения вторичных источников.

**Source Type (Тип источника)** — тип первичного источника: `Helm`, `Git`, `Kustomize` или `OCI`. Определяет метод рендеринга манифестов.

**Hydrated Branch (Гидрированная ветка)** — Git-ветка, в которую sourceHydrator записывает отрендеренные манифесты. По умолчанию `hydrated`. Контроллер синхронизирует из этой ветки.

## Базовые концепции

### Архитектура Multiple Sources

```text
┌──────────────────────────────────────────────┐
│  Application Manifest                        │
│                                              │
│  sources:                                    │
│  - chart: my-app                             │  ← Первичный источник (Helm-чарт)
│    repoURL: https://charts.example.com       │
│    targetRevision: 1.2.3                      │
│  - ref: values                               │  ← Вторичный источник (values)
│    repoURL: https://github.com/org/config    │
│    path: environments/production              │
│    targetRevision: main                       │
└──────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
┌─────────────────┐    ┌─────────────────────┐
│  Helm Registry  │    │  Git Repository     │
│  (Chart)        │    │  (Values)           │
└────────┬────────┘    └──────────┬──────────┘
         │                        │
         ▼                        ▼
┌──────────────────────────────────────────────┐
│  repo-server                                 │
│  1. Клонирует chart из Helm registry          │
│  2. Клонирует values из Git                   │
│  3. Рендерит: helm template chart values/    │
│  4. Возвращает отрендеренные манифесты        │
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│  application-controller                       │
│  Применяет отрендеренные манифесты в кластер  │
└──────────────────────────────────────────────┘
```

### Архитектура sourceHydrator

```text
┌──────────────────────────────────────────────┐
│  Application Manifest                        │
│                                              │
│  source:                                     │
│    repoURL: https://github.com/org/config    │
│    path: apps/my-app                         │
│    targetRevision: main                      │
│  sourceHydrator:                             │
│    hydrateTo:                                │
│      targetRevision: hydrated                │
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│  sourceHydrator controller                   │
│  1. Клонирует main ветку                     │
│  2. Рендерит Helm/Kustomize                  │
│  3. Записывает результат в hydrated ветку    │
│  4. Коммитит и пушит                         │
└──────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────┐
│  application-controller                       │
│  Синхронизирует из hydrated ветки             │
│  (а не из main!)                              │
└──────────────────────────────────────────────┘
```

### Сравнение подходов

| Подход | Когда использовать | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Single Source** | Простые приложения, чарт и values в одном репо | Простота, нет extra шагов | Нет разделения ответственности |
| **Multiple Sources** | Чарт в реестре, values в Git | Разделение chart/config, multi-env | Сложнее отладка, repo-server должен клонировать оба источника |
| **CI-рендеринг** | Полный контроль над рендерингом | Полная гибкость, кастомные плагины | CI должен рендерить, Argo CD видит plain YAML |
| **sourceHydrator** | GitOps-first подход, аудит рендеринга | Audit trail, git-история рендеринга | Только v3.x, requires hydrated branch |

## Практические сценарии

### Сценарий 1: Helm-чарт из реестра + values из Git

Классический случай: чарт публикуется в Harbor/ChartMuseum, values для каждого окружения хранятся в Git.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app-production
  namespace: argocd
spec:
  project: production
  source:
    # Первичный источник: Helm-чарт
    chart: my-app
    repoURL: https://charts.example.com
    targetRevision: 1.5.0
    helm:
      valueFiles:
        - $values/environments/production/values.yaml
  sources:
    # Вторичный источник: values-файлы
    - ref: values
      repoURL: https://github.com/myorg/config
      targetRevision: main
      path: environments/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
```

**Структура Git-репозитория конфигураций:**
```text
config/
├── environments/
│   ├── production/
│   │   ├── values.yaml
│   │   └── values-secret.yaml
│   ├── staging/
│   │   ├── values.yaml
│   │   └── values-secret.yaml
│   └── dev/
│       └── values.yaml
└── apps/
    ├── app1/
    │   └── kustomization.yaml
    └── app2/
        └── kustomization.yaml
```

### Сценарий 2: Multi-environment с одним ApplicationSet

Один ApplicationSet генерирует приложения для каждого окружения с разными values.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: my-app
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            cluster: https://dev-cluster.example.com
            revision: main
          - env: staging
            cluster: https://staging-cluster.example.com
            revision: release-1.5
          - env: production
            cluster: https://prod-cluster.example.com
            revision: release-1.5
  template:
    metadata:
      name: 'my-app-{{env}}'
    spec:
      project: '{{env}}'
      sources:
        - chart: my-app
          repoURL: https://charts.example.com
          targetRevision: 1.5.0
          helm:
            valueFiles:
              - $values/environments/{{env}}/values.yaml
        - ref: values
          repoURL: https://github.com/myorg/config
          targetRevision: '{{revision}}'
          path: 'environments/{{env}}'
      destination:
        server: '{{cluster}}'
        namespace: 'app-{{env}}'
```

### Сценарий 3: sourceHydrator с GitOps-first подходом

Вместо рендеринга в CI, sourceHydrator рендерит и коммитит в отдельную ветку.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/apps
    targetRevision: main
    path: apps/my-app
    # sourceHydrator конфигурация
    sourceHydrator:
      hydrateTo:
        targetRevision: hydrated
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
```

**Пример apps/my-app/ (с Helm):**
```yaml
# apps/my-app/chart.yaml
apiVersion: v2
name: my-app
version: 1.0.0
dependencies:
  - name: nginx
    version: "1.0.0"
    repository: "https://charts.example.com"
```

```yaml
# apps/my-app/values.yaml
replicaCount: 3
image:
  repository: nginx
  tag: "1.25"
```

```yaml
# apps/my-app/kustomization.yaml (если Kustomize)
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```

**Просмотр гидрированных манифестов:**
```bash
# Переключение на hydrated ветку
git checkout hydrated

# Просмотр отрендеренных манифестов
ls -la apps/my-app/

# Возврат к исходной ветке
git checkout main
```

### Сценарий 4: Multiple Sources с Kustomize

Kustomize-манифесты с внешними бэкендами.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  sources:
    # Основной Kustomize
    - path: apps/my-app
      repoURL: https://github.com/myorg/apps
      targetRevision: main
      directory:
        recurse: false
    # Внешние бэкенды (database URL, etc.)
    - ref: backends
      repoURL: https://github.com/myorg/backends
      targetRevision: main
      path: backends
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
```

### Сценарий 5: Проблемы и решение — ошибка "could not retrieve ref"

Типичная ошибка при неправильной настройке `ref`.

**Причина:** Секундарный источник не склонирован или `ref` не соответствует полю `ref` в sources.

**Решение:**
```yaml
# Правильно: ref в sources указывает на имя вторичного источника
sources:
  - ref: values         # ← Это имя
    repoURL: https://github.com/myorg/config
    path: values/
  - chart: my-app
    repoURL: https://charts.example.com
    helm:
      valueFiles:
        - $values/values.yaml   # ← Это ссылка (через $)

# Неправильно: ref не совпадает
sources:
  - ref: config          # ← Имя
    repoURL: https://github.com/myorg/config
  - chart: my-app
    helm:
      valueFiles:
        - $values/values.yaml   # ← Ссылка на "values" (не найдено!)
```

## Диагностика

### Базовые команды

```bash
# Просмотр конфигурации источников
argocd app get my-app -o yaml | grep -A20 "source:\|sources:"

# Проверка рендеринга
argocd app manifests my-app

# Просмотр diff
argocd app diff my-app

# Принудительное обновление
argocd app get my-app --refresh
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `could not retrieve ref` | `ref` в valueFiles не совпадает с `ref` в sources | Проверьте имена `ref` |
| `failed to clone` | repo-server не может склонировать репозиторий | Проверьте доступ (SSH key, token) |
| `chart not found` | Helm-чарт не найден в реестре | Проверьте `chart` и `repoURL` |
| `values file not found` | values-файл не найден во вторичном источнике | Проверьте `path` и структуру |
| `source type mismatch` | Тип источника не совпадает с конфигурацией | Убедитесь, что sources корректно определены |

## Лучшие практики

- **Разделяйте chart и values:** Храните Helm-чарты в реестре (ChartMuseum/Harbor/OCI), values — в Git.
- **Используйте $ref values:** Для multi-env деплоев создайте отдельный репозиторий конфигураций с environments/.
- **Версионируйте values:** Используйте ветки/теги для不同 environments (main для dev, release-* для staging/prod).
- **Тестируйте локально:** Используйте `argocd app manifests` для проверки рендеринга.
- **Избегайте sourceHydrator для простых случаев:** Multiple Sources проще для понимания и отладки.

## Ограничения и edge cases

### Ограничения

- **repo-server должен клонировать все источники:** Каждый источник добавляет время на клонирование (задержка рендеринга).
- **sourceHydrator только для v3.x:** Не работает в v2.x.
- **Нет поддержки overlapping sources:** Источники не могут пересекаться по path.
- **Hydrated branch требует write access:** repo-server должен иметь право пушить в hydrated ветку.

### Edge Cases

- **Один источник = $values:** Если sources содержит только один источник с `ref: values`, Argo CD не может его найти — нужен хотя бы один основной источник.
- **sourceHydrator + Progressive Sync:** sourceHydrator не поддерживает Progressive Sync — манифесты применяются пачкой.
- **OCI-источники:** Multiple Sources поддерживает OCI, но requires credentials для pull.
- **Кэширование:** repo-server кэширует клонированные репозитории. При обновлении source может потребоваться `argocd app get --refresh`.

## Дополнительная информация

### См. также

- [Helm интеграция](./helm_integration.md)
- [Dynamic Environments (ApplicationSet)](./dynamic_environments_crossplane.md)
- [Установка и настройка](./argocd_installation_and_setup.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Ссылки

- [Multiple Sources](https://argo-cd.readthedocs.io/en/stable/operator-manual/multiple-source-apps/)
- [Source Hydrator](https://argo-cd.readthedocs.io/en/stable/proposals/source-hydrator/)
- [ApplicationSet Generators](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators/)
