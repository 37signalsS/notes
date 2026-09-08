# Fleet: непрерывная доставка в Rancher (GitOps)

## Определения

**Fleet** — масштабируемое GitOps-решение, интегрированное в Rancher, предназначенное для доставки манифестов и Helm-чартов на тысячи кластеров одновременно. Является основным инструментом Continuous Delivery в экосистеме Rancher (замена устаревших Rancher Pipelines).

**GitRepo** — CRD Fleet, определяющий источник манифестов (Git-репозиторий или OCI-реестро) и параметры синхронизации. Контроллер Fleet опрашивает указанный репозиторий и применяет изменения в целевые кластеры.

**Bundle** — логический артефакт, создаваемый Fleet из содержимого GitRepo. Bundle содержит все манифесты (YAML, Helm-чарты, Kustomize) и метаданные для деплоя. Fleet автоматически собирает Bundle из файлов в GitRepo и применяет его.

**Fleet Agent** — компонент, работающий на каждом downstream-кластере. Агент выполняет Pull-модель: сам забирает изменения из GitRepo и применяет их локально. Это обеспечивает автономность кластеров и минимальные сетевые требования (только исходящий доступ к Git).

**GitRepo ClusterGroup** — механизм таргетизации, позволяющийгруппироватьdownstream-кластеры по меткам (labels) и направлятьBundle только в отобранные кластеры. Поддерживает синтаксис `matchExpressions` (включая `In`, `NotIn`, `Exists`).

## Базовые концепции

### Архитектура Fleet

Fleet работает по Pull-модели, аналогичной ArgoCD/Flux, но оптимизирован для масштабирования на тысячи кластеров:

```
┌─────────────────────┐
│   Git Repository    │  ← Источник манифестов (Git/OCI)
└──────────┬──────────┘
           │ Poll / Webhook
┌──────────▼──────────┐
│  Fleet Controller   │  ← В Management-кластере
│  (gitrepoReconciler)│     Собирает Bundle из GitRepo
└──────────┬──────────┘
           │ Pull (Bundle)
┌──────────▼──────────┐     ┌──────────────────────┐
│   Downstream K8s    │     │   Downstream K8s     │
│   ┌──────────────┐  │     │   ┌──────────────┐   │
│   │ Fleet Agent  │  │     │   │ Fleet Agent  │   │
│   │ (applies)    │  │     │   │ (applies)    │   │
│   └──────────────┘  │     │   └──────────────┘   │
└─────────────────────┘     └──────────────────────┘
```

**Ключевые особенности:**
- **Pull-модель:** агент на каждом кластере сам забирает изменения, не требуя входящего доступа.
- **Масштабируемость:** один Bundle может быть применен на тысячи кластеров через ClusterGroup.
- **Автономность:** при потере связи с Rancher/ GitRepo кластеры продолжают работать с последним известным состоянием.
- **Детекция дрейфа:** агент периодически сверяет состояние кластера с Git и применяет расхождения.

### GitRepo: конфигурация

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  paths:
    - apps/production
  targetNamespace: prod
  serviceAccountName: fleet-agent   # SA для доступа к API downstream
  correctDrift:
    enabled: true                    # автоматическое исправление дрейфа
    force: true                      # принудительное применение
  poll: true                         # опрос каждые 5 секунд
  revision: main                     # ветка/тег/коммит
```

**Ключевые параметры:**
- `repo` — URL Git-репозитория или OCI-реестра.
- `branch` — ветка для отслеживания (по умолчанию `main`).
- `paths` — подкаталоги в репозитории для деплоя (если пусто — весь репозиторий).
- `targetNamespace` — целевой namespace для всех ресурсов (если не указан в манифестах).
- `correctDrift` — автоматическое исправление дрейфа (ручные правки в кластере откатываются).
- `poll` — периодический опрос Git (по умолчанию включен, интервал ~5 сек).
- `serviceAccountName` — SA в downstream-кластере для применения манифестов.

### Bundle: структура

Fleet автоматически создает Bundle из содержимого GitRepo. Bundle содержит:
- Все YAML/Helm/Kustomize файлы из указанных `paths`.
- Метаданные (имя GitRepo, ревизию, целевые namespace).
- Настройки Helm (если используется Helm-чарт).

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: Bundle
metadata:
  name: my-app
  namespace: fleet-local
spec:
  sources:
    - repo: https://github.com/org/k8s-manifests.git
      ref: main
      paths:
        - apps/production
  targetRestrictions:
    - clusterGroup: production       # ограничение по ClusterGroup
  defaultNamespace: prod
  correctDrift:
    enabled: true
```

**Важно:** Bundle создается автоматически и не редактируется вручную. Управление осуществляется через GitRepo.

### ClusterGroup: таргетизация кластеров

ClusterGroup позволяет группировать downstream-кластеры по меткам и направлятьBundle только в отобранные:

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: ClusterGroup
metadata:
  name: production
  namespace: fleet-local
spec:
  selector:
    matchLabels:
      env: prod
    matchExpressions:
      - key: region
        operator: In
        values:
          - eu-west
          - eu-central
```

**Связь GitRepo → ClusterGroup:**

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  targets:
    - clusterGroup: production       # деплой только в кластеры группы
```

**Примеры селекторов:**

| Задача | Селектор |
| :--- | :--- |
| Все кластеры | `selector: {}` (пустой) |
| Только prod | `matchLabels: {env: prod}` |
| prod, кроме staging | `matchExpressions: [{key: env, operator: In, values: [prod]}, {key: stage, operator: NotIn, values: [staging]}]` |
| Кластеры с特定ной меткой | `matchExpressions: [{key: gpu, operator: Exists}]` |

### Каналы обновлений (Fleet GitRepo)

Fleet поддерживает несколько веток/тегов для управления обновлениями:

```yaml
apiVersion: fleet.cattle.io/valpha1
kind: GitRepo
metadata:
  name: my-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  revision: v1.2.0                 # фиксированная версия (тег)
```

**Стратегия:**
- `branch: main` — автоматическое обновление при каждом коммите.
- `revision: v1.2.0` — фиксированная версия, обновление только при смене тега.
- `paths` — позволяет деплоить разные компоненты из разных путей репозитория.

## Практические сценарии

### Шаг 1: Установка Fleet (обычно уже установлен в Rancher)

Fleet поставляется с Rancher "из коробки". Проверка:

```bash
# Проверка наличия Fleet controller
kubectl -n cattle-fleet-system get pods
# → fleet-controller-...   Running

# Проверка Fleet agents в downstream-кластерах
kubectl -n cattle-fleet-system get pods -l app=fleet-agent
```

Если Fleet не установлен, установите через Apps & Marketplace → Fleet.

### Шаг 2: Создание GitRepo для приложения

Допустим, у нас есть репозиторий с манифестами:

```
k8s-manifests/
├── apps/
│   └── production/
│       ├── namespace.yaml
│       ├── deployment.yaml
│       ├── service.yaml
│       └── ingress.yaml
└── fleet/
    └── gitrepo.yaml
```

```yaml
# fleet/gitrepo.yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  paths:
    - apps/production
  targetNamespace: prod
  correctDrift:
    enabled: true
```

```bash
# Применение
kubectl apply -f fleet/gitrepo.yaml

# Проверка статуса
kubectl get gitrepo -n fleet-local
# → my-app    Ready    1/1
```

### Шаг 3: Таргетизация на конкретные кластеры

```yaml
# ClusterGroup для prod-кластеров
apiVersion: fleet.cattle.io/v1alpha1
kind: ClusterGroup
metadata:
  name: production
  namespace: fleet-local
spec:
  selector:
    matchLabels:
      env: prod
---
# GitRepo с таргетизацией
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  paths:
    - apps/production
  targets:
    - clusterGroup: production
```

### Шаг 4: Доставка Helm-чартов через Fleet

Fleet поддерживает Helm-чарты как источник манифестов:

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-helm-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/helm-charts.git
  branch: main
  paths:
    - charts/my-app
  helm:
    releaseName: my-app
    values:
      replicas: 3
      image:
        tag: v1.2.0
```

### Шаг 5: Kustomize через Fleet

```yaml
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: my-kustomize-app
  namespace: fleet-local
spec:
  repo: https://github.com/org/k8s-manifests.git
  branch: main
  paths:
    - overlays/production
```

### Шаг 6: Мониторинг статуса деплоя

```bash
# Статус GitRepo
kubectl get gitrepo -n fleet-local -o wide
# → NAME         READY   STATUS
# → my-app       1/1     Reconciling

# ДеталиBundle
kubectl get bundle -n fleet-local
# → my-app-...   Ready   1/1

# Статус на конкретном downstream-кластере
kubectl get bundledeployment -n fleet-local
# → my-app-...   Ready   Applied
```

### Шаг 7: Исправление дрейфа (Drift Correction)

Fleet автоматически отслеживает дрейф и исправляет ручные правки:

```yaml
spec:
  correctDrift:
    enabled: true
    force: true     # принудительное применение (перезаписывает ручные правки)
```

**Поведение:**
- Если кто-то изменил Deployment в кластере через `kubectl edit`, Fleet вернет его в состояние из Git.
- Если `force: false`, Fleet не будет применять изменения, конфликтующие с ручными правками.

### Шаг 8: Откат через Git

В GitOps-модели откат выполняется через Git:

```bash
# 1. Откат коммита в Git
git revert HEAD

# 2. Push изменений
git push origin main

# 3. Fleet автоматически применит предыдущую версию
kubectl get gitrepo -n fleet-local
# → my-app    Ready    1/1
```

### Шаг 9: Multi-тенантность с Fleet

Разные команды могут управлять своимиGitRepo и ClusterGroup:

```yaml
# Team A: деплой в dev/staging
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: team-a-app
  namespace: fleet-local
spec:
  repo: https://github.com/team-a/app.git
  branch: main
  targets:
    - clusterGroup: dev-staging

# Team B: деплой в prod
apiVersion: fleet.cattle.io/v1alpha1
kind: GitRepo
metadata:
  name: team-b-app
  namespace: fleet-local
spec:
  repo: https://github.com/team-b/app.git
  branch: main
  targets:
    - clusterGroup: production
```

### Шаг 10: Автоматизация через Rancher UI

1. В Rancher UI: **Continuous Delivery → Git Repos → Create**
2. Укажите URL репозитория, ветку, пути
3. Выберите целевые кластеры (ClusterGroup)
4. Нажмите **Create**

Fleet автоматически создаст GitRepo и начнет синхронизацию.

## Диагностика и устранение неполадок

### GitRepo не синхронизируется

```bash
# Проверка статуса GitRepo
kubectl describe gitrepo <name> -n fleet-local

# Проверка логов Fleet controller
kubectl -n cattle-fleet-system logs -l app=fleet-controller --tail=100

# Проверка доступности Git-репозитория
kubectl -n cattle-fleet-system run git-test --rm -it --image=alpine -- \
  wget -qO- https://github.com/org/repo.git/info/refs?service=git-upload-pack
```

**Типичные причины:**
- Неверный URL/ветка/токен Git-репозитория.
- Fleet agent не имеет доступа к Git (сетевые ограничения).
- BundleCreateError (ошибка в манифестах).

### Bundle в состоянии Error

```bash
# Детали ошибки
kubectl get bundle -n fleet-local -o yaml
# → Status: Conditions: Reason: BundleApplyError

# Проверка манифестов
fleet test .   # локальная валидация манифестов
```

**Решение:** проверьте YAML-синтаксис манифестов, права SA в downstream-кластере, наличие required CRD.

### Fleet Agent не подключается

```bash
# Проверка подов Fleet agent в downstream
kubectl -n cattle-fleet-system get pods
# → fleet-agent-...   CrashLoopBackOff

# Логи агента
kubectl -n cattle-fleet-system logs -l app=fleet-agent --tail=100
```

**Типичные причины:**
- Неверный токен/сертификат для подключения к Rancher.
- Сетевые ограничения (исходящий доступ к Rancher по 443).
- Нехватка ресурсов (проверьте limits/requests).

### Дрейф не исправляется

Убедитесь, что `correctDrift.enabled: true` в GitRepo. Проверьте, что SA в downstream-кластере имеет права на изменение ресурсов.

## Дополнительная информация

### Сравнение Fleet с ArgoCD/Flux

| Критерий | Fleet | ArgoCD | Flux |
| :--- | :--- | :--- | :--- |
| **Фокус** | Мультикластер (тысячи кластеров) | Single/multi-cluster | Single/multi-cluster |
| **Архитектура** | Pull (агент на каждом кластере) | Pull (сервер + агенты) | Pull (операторы) |
| **Таргетизация** | ClusterGroup + labels | ApplicationSet | Kustomization + labels |
| **Helm** | Нативная поддержка | Через ArgoCD Helm plugin | Через HelmRelease |
| **Масштабируемость** | до 100k+ кластеров | до数千 кластеров | до数百 кластеров |
| **Интеграция с Rancher** | Полная (встроено) | Через дополнительную установку | Через дополнительную установку |

### Рекомендации по использованию Fleet

1. **Разделяйте инфраструктуру и приложения:** используйте разные GitRepo для базовых сервисов (cert-manager, ingress) и приложений.
2. **Используйте ClusterGroup:** группируйте кластеры по средам (dev/staging/prod) для изоляции деплоя.
3. **Включайте correctDrift:** для production рекомендуется `force: true`, чтобы предотвратить ручные правки.
4. **Фиксируйте версии:** используйте `revision` (теги) вместо `branch` для production-деплоев.
5. **Мониторьте статус:** настройте алертинг на `GitRepoReady` и `BundleReady` через Prometheus.

### Связанные темы

- [Rancher: Обзор платформы](./rancher_overview.md) — архитектура и компоненты.
- [Rancher Pipelines (Legacy)](./rancher_pipelines.md) — миграция со старых пайплайнов.
- [GitOps: Обзор](../../GitOps/GitOps_overview.md) — общие принципы GitOps.
- [ArgoCD](../../GitOps/ArgoCD/argocd_overview.md) — альтернативный GitOps-инструмент.

**Внешние ресурсы:**

- [Fleet Documentation](https://fleet.rancher.io/) — официальная документация.
- [Rancher Fleet GitHub](https://github.com/rancher/fleet) — исходный код.
