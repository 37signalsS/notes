# vCluster — интеграция с GitOps

> Документ описывает интеграцию vCluster с GitOps-инструментами: ArgoCD, Flux, ApplicationSet для управления множеством тенантов, конфигурацией vCluster через Git. CI/CD — в [vcluster_cicd_integration.md](./vcluster_cicd_integration.md), установка — в [vcluster_installation.md](./vcluster_installation.md).

## Определения

**GitOps** — методология управления инфраструктурой и приложениями через Git как единственный источник истины. Все изменения проходят через PR/MR, применяются автоматически или вручную.

**ArgoCD** — GitOps-controller для Kubernetes. Синхронизирует желаемое состояние (Git) с текущим (кластер). Поддерживает Helm, Kustomize, raw manifests.

**Flux** — GitOps-controller от CNCF. Композитный подход: Source Controller (Git/Helm), Kustomize Controller, Helm Controller, Notification Controller.

**ApplicationSet** — CRD ArgoCD, позволяющий динамически генерировать Application из шаблонов. Идеально для управления множеством vCluster (один шаблон — много тенантов).

**Application** — CRD ArgoCD, описывающий один компонент: источник (Git/Helm), назначение (кластер/namespace), политика синхронизации.

**Self-Heal** — механизм ArgoCD, восстанавливающий состояние кластера при отклонении от Git. Конфликтует со Sleep Mode vCluster.

**Prune** — автоматическое удаление объектов, которые были удалены из Git.

## Основные концепции

### Архитектура GitOps для vCluster

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Git Repository                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  clusters/                                                  │ │
│  │    ├── team-alpha/                                           │ │
│  │    │   ├── vcluster.yaml                                     │ │
│  │    │   └── apps/                                             │ │
│  │    │       ├── deployment.yaml                               │ │
│  │    │       └── service.yaml                                  │ │
│  │    ├── team-beta/                                            │ │
│  │    │   ├── vcluster.yaml                                     │ │
│  │    │   └── apps/                                             │ │
│  │    └── platform/                                             │ │
│  │        ├── argocd-applicationset.yaml                        │ │
│  │        └── monitoring/                                       │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ArgoCD (на хост-кластере)                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  ApplicationSet: vcluster-tenants                           │ │
│  │    ├── Application: vc-team-alpha                           │ │
│  │    ├── Application: vc-team-beta                            │ │
│  │    └── Application: vc-team-gamma                           │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                       │
│         ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Host Cluster                                               │ │
│  │    ├── vCluster team-alpha (namespace: team-alpha)          │ │
│  │    ├── vCluster team-beta  (namespace: team-beta)           │ │
│  │    └── vCluster team-gamma (namespace: team-gamma)          │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Практические сценарии

### ArgoCD: ApplicationSet для множества vCluster

```yaml
# argocd-applicationset.yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: vcluster-tenants
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: https://github.com/myorg/gitops-infra.git
        revision: main
        directories:
          - path: clusters/*
  template:
    metadata:
      name: 'vc-{{path.basename}}'
      annotations:
        argocd.argoproj.io/manifest-generate-paths: '/clusters/{{path.basename}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/myorg/gitops-infra.git
        targetRevision: main
        path: 'clusters/{{path.basename}}'
        helm:
          releaseName: 'vc-{{path.basename}}'
          valueFiles:
            - vcluster.yaml
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path.basename}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: false  # Важно: отключить для vCluster со Sleep Mode
        syncOptions:
          - CreateNamespace=true
          - ApplyOutOfSyncOnly=true
        retry:
          limit: 3
          backoff:
            duration: 30s
            factor: 2
            maxDuration: 3m
```

### ArgoCD: Application для одного vCluster с приложениями

```yaml
# argocd-vcluster-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vc-team-alpha
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/gitops-infra.git
    targetRevision: main
    path: clusters/team-alpha
  destination:
    server: https://kubernetes.default.svc
    namespace: team-alpha
  syncPolicy:
    automated:
      prune: true
      selfHeal: false
    syncOptions:
      - CreateNamespace=true
  ignoreDifferences:
    # Игнорировать изменения replicas при Sleep Mode
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

### Flux: конфигурация vCluster через Git

```yaml
# flux-source.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: gitops-infra
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/myorg/gitops-infra.git
  ref:
    branch: main
---
# flux-kustomization.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: vcluster-team-alpha
  namespace: flux-system
spec:
  interval: 5m
  path: ./clusters/team-alpha
  prune: true
  sourceRef:
    kind: GitRepository
    name: gitops-infra
  healthChecks:
    - apiVersion: apps/v1
      kind: StatefulSet
      name: vc-team-alpha
      namespace: team-alpha
  timeout: 3m
```

### Управление конфигурацией vCluster через Git

Структура репозитория:

```
gitops-infra/
├── clusters/
│   ├── team-alpha/
│   │   ├── vcluster.yaml          # Конфигурация vCluster
│   │   ├── apps/
│   │   │   ├── kustomization.yaml
│   │   │   ├── deployment.yaml
│   │   │   └── service.yaml
│   │   └── network/
│   │       └── networkpolicy.yaml
│   ├── team-beta/
│   │   ├── vcluster.yaml
│   │   └── apps/
│   └── team-gamma/
│       ├── vcluster.yaml
│       └── apps/
├── platform/
│   ├── argocd/
│   │   ├── applicationset.yaml
│   │   └── project.yaml
│   └── monitoring/
│       ├── prometheus/
│       └── grafana/
└── README.md
```

### Конфигурация vCluster для GitOps

```yaml
# clusters/team-alpha/vcluster.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
      image: "registry.k8s.io/kube-apiserver:v1.36.0"

  backingStore:
    etcd:
      embedded:
        enabled: true
        size: "8Gi"
        storageClassName: "fast-ssd"

  statefulSet:
    replicas: 3  # Production HA
    resources:
      requests:
        cpu: 300m
        memory: 512Mi
      limits:
        cpu: 1
        memory: 1Gi

sync:
  toHost:
    pods:
      enabled: true
    services:
      enabled: true
    ingresses:
      enabled: true
  fromHost:
    storageClasses:
      enabled: true
    ingressClasses:
      enabled: true
    nodes:
      enabled: true

networking:
  gatewayAPI:
    enabled: true
    apiServer:
      enabled: true
      host: "team-alpha.vcluster.example.com"
      gatewayRef:
        name: "external-gateway"
        namespace: "infra"
  proxy:
    extraSANs:
      - "team-alpha.vcluster.example.com"

policies:
  podSecurityStandard: restricted
  networkPolicy:
    enabled: true
  resourceQuota:
    enabled: true
    quota:
      requests.cpu: "8"
      requests.memory: 16Gi
      pods: "100"
  limitRange:
    enabled: true
    default:
      cpu: 500m
      memory: 512Mi

sleepMode:
  enabled: true
  autoSleepSeconds: 3600
  autoWakeup: true
```

### Решение конфликта selfHeal + Sleep Mode

ArgoCD selfHeal восстанавливает replicas до желаемого состояния, будя спящий vCluster. Решения:

#### Вариант 1: Отключить selfHeal для vCluster

```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: false  # Отключить для vCluster
```

#### Вариант 2: Ignore differences для replicas

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
    - group: apps
      kind: StatefulSet
      jsonPointers:
        - /spec/replicas
```

#### Вариант 3: Использовать ArgoCD ApplicationSet с condition

```yaml
generators:
  - git:
      repoURL: https://github.com/myorg/gitops-infra.git
      revision: main
      directories:
        - path: clusters/*
  - list:
      elements: []
# В шаблоне: selfHeal: false для спящих сред
```

### Ротация конфигурации vCluster через Git

```bash
# 1. Изменить vcluster.yaml в Git
vim clusters/team-alpha/vcluster.yaml

# 2. Создать PR
git checkout -b update-team-alpha-config
git add clusters/team-alpha/vcluster.yaml
git commit -m "feat(team-alpha): increase etcd size to 10Gi"
git push origin update-team-alpha-config

# 3. После мержа ArgoCD/Flux применит изменения
# 4. Проверить статус
argocd app get vc-team-alpha
# → Health: Healthy, Sync: Synced
```

### Диагностика проблем GitOps

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| ArgoCD selfHeal будит vCluster | `selfHeal: true` + Sleep Mode | `selfHeal: false` или `ignoreDifferences` |
| ApplicationSet не генерирует Applications | Неверный path в generator | Проверить `directories.path` |
| Flux Kustomization в Error | Git repository недоступен | Проверить credentials, network |
| Синхронизация зациклена | SelfHeal + аннотации Helm | Добавить `ApplyOutOfSyncOnly` |
| vCluster не обновляется через GitOps | Helm values не применяются | Проверить `helm.valueFiles` в Application |
| Prune удаляет нужные объекты | Объекты не в Git | Добавить `managedFields` или exclude |

### Лучшие практики

- **selfHeal: false для vCluster:** Sleep Mode и selfHeal конфликтуют. Используйте `ignoreDifferences`.
- **Версионирование CLI:** Зафиксируйте версию vCluster CLI в GitOps-репозитории.
- **Паттерн multi-tenancy:** ApplicationSet + git generator для автоматического добавления тенантов.
- **Health checks:** В Flux добавляйте `healthChecks` для контроля состояния Control Plane.
- **RBAC в ArgoCD:** Ограничьте доступ тенантов к своему vCluster через `AppProject`.
- **Мониторинг синхронизации:** Алерт на `argocd_app_sync_total{phase="Error"}`.
- **Тестирование изменений:** Сначала примените изменения в dev vCluster, потом в production.

## Дополнительная информация

### Внутренние ссылки

- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — CI/CD интеграция](./vcluster_cicd_integration.md)
- [vCluster — обзор и архитектура](./vcluster_overview.md)

### См. также

- [ArgoCD — обзор](../../GitOps/ArgoCD/argocd_overview.md)
- [ArgoCD — ApplicationSet](../../GitOps/ArgoCD/argocd_applicationsets.md)
- [ArgoCD — troubleshooting](../../GitOps/ArgoCD/argocd_troubleshooting_and_monitoring.md)

### Внешние ссылки

- [vCluster GitOps Documentation](https://www.vcluster.com/docs/use-cases/gitops)
- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Flux Documentation](https://fluxcd.io/docs/)
