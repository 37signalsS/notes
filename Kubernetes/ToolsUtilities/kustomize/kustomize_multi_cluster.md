# Kustomize — Multi-cluster и multi-tenancy паттерны

## 1. Определения

**Multi-cluster Kustomize** — подход к управлению конфигурациями Kubernetes, при котором один репозиторий с базовыми манифестами и множеством overlay'ов используется для деплоя в несколько кластеров (регионы, окружения, команды) с контролируемыми различиями.

**Multi-tenancy через Kustomize** — архитектурный паттерн, при котором изолированные конфигурации для разных команд/тенантов создаются через иерархию overlays с общими base и специфичными для тенанта патчами.

**Fleet-репозиторий** — Git-репозиторий, описывающий конфигурацию всех кластеров: общие базовые компоненты + специфичные overlay на каждый кластер.

## 2. Основные концепции

### Структура репозитория для multi-cluster

```text
infra-repo/
├── base/                              # Общая base для ВСЕХ кластеров
│   ├── apps/
│   │   └── web-server/
│   │       ├── deployment.yaml
│   │       ├── service.yaml
│   │       └── kustomization.yaml
│   └── platform/                      # Аддоны: monitoring, ingress
│       ├── monitoring/
│       └── ingress/
├── clusters/                          # Точка входа каждого кластера
│   ├── prod-eu/
│   │   ├── kustomization.yaml         # Ссылка на base + platform overlays
│   │   ├── cluster-vars.yaml          # Кластер-специфичные переменные
│   │   └── apps/
│   │       └── web-server/
│   │           └── kustomization.yaml # Overlay для EU
│   ├── prod-us/
│   │   ├── kustomization.yaml
│   │   ├── cluster-vars.yaml
│   │   └── apps/
│   │       └── web-server/
│   │           └── kustomization.yaml # Overlay для US
│   └── staging/
│       ├── kustomization.yaml
│       └── apps/
│           └── web-server/
│               └── kustomization.yaml
└── overlays/                          # Глобальные overlays (опционально)
    └── regional/
        ├── eu/
        └── us/
```

### Модели мульти-кластерного деплоя

| Модель | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Directory promotion** | Все среды в одной ветке, разные overlay'и | Стандартный GitOps (ArgoCD) |
| **Branch promotion** | Каждая среда — отдельная ветка | Простые пайплайны, малая команда |
| **Tag promotion** | Git-tag определяет версию | Команды с semver-релизным циклом |
| **Hub-and-Spoke** | Центральный ArgoCD управляет spoke-кластерами | 10–50 кластеров |
| **Pull-per-cluster** | Каждый кластер тянет свою конфигурацию | 50+ кластеров, edge |

### Multi-tenancy через overlays

```text
tenants/
├── team-alpha/
│   ├── base/                         # Общая base для всех тенантов
│   │   ├── namespace.yaml
│   │   ├── rbac.yaml
│   │   ├── network-policy.yaml
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── dev/
│       │   └── kustomization.yaml    # team-alpha, ns: alpha-dev
│       └── prod/
│           └── kustomization.yaml    # team-alpha, ns: alpha-prod
├── team-beta/
│   ├── base/
│   │   ├── namespace.yaml
│   │   ├── rbac.yaml
│   │   ├── network-policy.yaml
│   │   └── kustomization.yaml
│   └── overlays/
│       ├── dev/
│       └── prod/
└── platform/                         # Общие platform-ресурсы
    ├── base/
    └── overlays/
```

**Пример overlay для тенанта:**
```yaml
# tenants/team-alpha/overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base
  - ../../../../base/apps/web-server

namespace: alpha-prod
namePrefix: alpha-

commonLabels:
  team: alpha
  environment: production
  managed-by: platform-team

patches:
  - target:
      kind: Namespace
    patch: |-
      - op: add
        path: /metadata/labels/pod-security.kubernetes.io~1enforce
        value: restricted
  - target:
      kind: ResourceQuota
    patch: |-
      - op: replace
        path: /spec/hard/cpu
        value: "8"
      - op: replace
        path: /spec/hard/memory
        value: "16Gi"

configMapGenerator:
  - name: tenant-config
    literals:
      - TEAM=alpha
      - ENVIRONMENT=production
```

## 3. Практические сценарии

### 3.1. Multi-cluster: prod-eu vs prod-us

**cluster-vars для EU:**
```yaml
# clusters/prod-eu/cluster-vars.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-vars
data:
  REGION: "eu-west-1"
  INGRESS_CLASS: "nginx-internal"
  MONITORING_ENDPOINT: "prometheus-eu.internal"
  REPLICAS: "5"
```

**cluster-vars для US:**
```yaml
# clusters/prod-us/cluster-vars.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-vars
data:
  REGION: "us-east-1"
  INGRESS_CLASS: "nginx-external"
  MONITORING_ENDPOINT: "prometheus-us.internal"
  REPLICAS: "3"
```

**Overlay для EU:**
```yaml
# clusters/prod-eu/apps/web-server/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../../../base/apps/web-server
  - ../cluster-vars.yaml

namespace: web-server
namePrefix: eu-

patches:
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 5
  - target:
      kind: Deployment
      name: web-server
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/env/-
        value:
          name: REGION
          valueFrom:
            configMapKeyRef:
              name: cluster-vars
              key: REGION

replacements:
  - source:
      kind: ConfigMap
      name: cluster-vars
      fieldPath: data.INGRESS_CLASS
    targets:
      - select:
          kind: Ingress
          name: web-server
        fieldPaths:
          - spec.ingressClassName
```

### 3.2. ArgoCD ApplicationSet для multi-cluster

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: web-server
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: prod-eu
            url: https://kubernetes-eu.internal
            region: eu
          - cluster: prod-us
            url: https://kubernetes-us.internal
            region: us
  template:
    metadata:
      name: 'web-server-{{cluster}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/infra-gitops.git
        targetRevision: main
        path: 'clusters/{{cluster}}/apps/web-server'
      destination:
        server: '{{url}}'
        namespace: web-server
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - ServerSideApply=true
```

### 3.4. Multi-tenancy: namespace-per-team с RBAC

```yaml
# tenants/team-alpha/base/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: alpha
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
    tenant: alpha
---
# tenants/team-alpha/base/rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alpha-admin
  namespace: alpha
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: admin
subjects:
  - kind: Group
    name: team-alpha
    apiGroup: rbac.authorization.k8s.io
---
# tenants/team-alpha/base/resource-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: alpha-quota
  namespace: alpha
spec:
  hard:
    cpu: "4"
    memory: "8Gi"
    pods: "20"
    services: "10"
---
# tenants/team-alpha/base/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-ingress
  namespace: alpha
spec:
  podSelector: {}
  policyTypes:
    - Ingress
  ingress: []  # Запрет всего входящего трафика
```

### 3.5. Промоушн между кластерами

**Последовательный деплой (staging → prod-eu → prod-us):**
```bash
#!/bin/bash
set -euo pipefail

# 1. Deploy staging (все изменение)
kubectl apply -k overlays/staging/

# 2. Валидация staging
kubectl get deploy -n web-server -o wide
kubectl wait --for=condition=available deployment/web-server -n web-server --timeout=300s

# 3. Deploy prod-eu (первый регион)
kubectl apply -k clusters/prod-eu/apps/web-server/
kubectl wait --for=condition=available deployment/web-server -n web-server --timeout=300s

# 4. Deploy prod-us (второй регион, с задержкой)
sleep 300  # Ожидание стабилизации EU
kubectl apply -k clusters/prod-us/apps/web-server/
kubectl wait --for=condition=available deployment/web-server -n web-server --timeout=300s
```

## 4. Дополнительная информация

### Рекомендации по структуре

- **Base — нейтральна:** никогда не указывайте namespace, namePrefix, environment-specific настройки в base
- **Cluster-specific — только в clusters/:** различия между кластерами только через overlays
- **CODEOWNERS:** платформенная команда ревьюит `platform/`, прикладные команды — `apps/*`
- **Monorepo vs Polyrepo:** monorepo (всё в одном репозитории) проще для <10 сервисов, polyrepo — для зрелых организаций

### См. также

- [Multi-cluster паттерны в GitOps](../../../GitOps/Concepts/multi_cluster_patterns.md) — общая архитектура multi-cluster
- [Multi-tenancy в Kubernetes](../../Concepts/multi-tenancy.md) — модели изоляции тенантов
- [Интеграция в CD](./kustomize_cd_integration.md) — ArgoCD интеграция
