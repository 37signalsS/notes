# Deployment с GitOps

Интеграция Kubernetes Deployment с GitOps: Git как SSoT, автоматическая синхронизация через ArgoCD/Flux и rollback через Git.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes с установленным GitOps-оператором (ArgoCD или Flux).
- Репозиторий Git с манифестами Kubernetes.
- Установленный `kubectl` с доступом к кластеру.
- Базовое понимание [Deployment](./index.md).

## 1. Определения

**GitOps** — методология, при которой Git является единственным источником правды (SSoT) для инфраструктуры и приложений. Изменения применяются автоматически через reconciliation loop.

> Общая теория GitOps, архитектура ArgoCD/Flux, drift detection и sync waves см. в [GitOps Overview](../../../GitOps/GitOps_overview.md), [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md), [Flux](../../../GitOps/flux.md) и [ArgoCD vs Flux](../../../GitOps/argo_vs_flux_manifests.md).

## 2. Базовые концепции

### Deployment + GitOps: что меняется

| Аспект | Ручной деплой | GitOps |
|:-------|:-------------|:-------|
| **Источник изменений** | `kubectl apply` | Git commit |
| **Применение** | CI/CD pipeline push | GitOps operator pull |
| **Rollback** | `kubectl rollout undo` | `git revert` + reconciliation |
| **Audit trail** | Логи CI/CD | Git history |
| **Self-healing** | Нет | Автоматическое исправление drift |

### Типичный GitOps workflow

```
1. Разработчик коммитит изменения в Git
    ↓
2. CI пайплайн: lint → test → build → scan → push image
    ↓
3. CI обновляет манифест в Git (image tag)
    ↓
4. GitOps оператор обнаруживает изменение в Git
    ↓
5. Reconciliation: применение изменений в кластере
    ↓
6. Проверка здоровья Deployment
```

## 3. Практические сценарии

### ArgoCD: Deployment

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/k8s-manifests.git
    targetRevision: main
    path: apps/my-app/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Flux: Deployment

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/my-app/overlays/production
  prune: true
  sourceRef:
    kind: GitRepository
    name: k8s-manifests
  healthChecks:
  - apiVersion: apps/v1
    kind: Deployment
    name: my-app
    namespace: production
  timeout: 3m
```

### Rollback через Git

```bash
# 1. Откат через git revert (рекомендуемый способ)
git log --oneline -3
# → abc1234 update image to v1.2.0 (проблемная)
# → def5678 update image to v1.1.0

git revert HEAD
git push origin main

# 2. ArgoCD/Flux автоматически обнаружит и применит

# 3. ВАЖНО: argocd app rollback НЕ рекомендуется
# при auto-sync — следующая reconciliation перезапишет
# Всегда используйте git revert!
```

### Sync Waves для порядка деплоя

```yaml
# Wave 0: ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  annotations:
    argocd.argoproj.io/sync-wave: "0"

---
# Wave 1: Migration Job
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration
  annotations:
    argocd.argoproj.io/sync-wave: "1"
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded

---
# Wave 2: Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  annotations:
    argocd.argoproj.io/sync-wave: "2"
```

### Drift Detection

```bash
# ArgoCD: проверка drift
argocd app get my-app

# Flux: проверка состояния
flux get kustomizations

# Ручное исправление drift
# Лучше: внести изменения в Git и дождаться reconciliation

# Принудительная синхронизация
argocd app sync my-app          # ArgoCD
flux reconcile kustomization my-app  # Flux
```

### Структура репозитория

```
k8s-manifests/
├── apps/
│   ├── my-app/
│   │   ├── base/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   └── kustomization.yaml
│   │   └── overlays/
│   │       ├── staging/
│   │       └── production/
│   └── another-app/
├── infrastructure/
│   ├── prometheus/
│   └── nginx-ingress/
└── clusters/
    ├── staging/
    └── production/
```

## 4. Дополнительная информация

### См. также
- [GitOps Overview](../../../GitOps/GitOps_overview.md) — общие принципы GitOps.
- [ArgoCD](../../../GitOps/ArgoCD/argocd_overview.md) — архитектура и конфигурация ArgoCD.
- [Flux CD](../../../GitOps/flux.md) — архитектура и конфигурация Flux.
- [ArgoCD vs Flux](../../../GitOps/argo_vs_flux_manifests.md) — сравнение (6 сценариев).
- [Sync Waves](../../../GitOps/ArgoCD/synchronization/scenarios/sync_waves_hooks.md) — ordered deployment (581 строка).
- [Ignore Differences](../../../GitOps/ArgoCD/synchronization/ignore_differences.md) — drift management (435 строк).
- [Progressive Delivery](./progressive_delivery.md) — Argo Rollouts, Flagger.
- [Kustomize](../../../Kubernetes/ToolsUtilities/kustomize/) — шаблонизация манифестов.
