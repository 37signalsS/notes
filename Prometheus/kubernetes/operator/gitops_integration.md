# GitOps-интеграция (Argo CD) с Prometheus Operator

## Определения

**GitOps для Prometheus Operator** — подход, при котором вся конфигурация стека мониторинга (CRD, Rules, AlertmanagerConfig, NetworkPolicy, Secrets) хранится в Git и автоматически синхронизируется с кластером через GitOps-инструменты (Argo CD). Operator управляет жизненным циклом Prometheus/Alertmanager, а GitOps — жизненным циклом самих CRD.

**Reconciliation Conflict** — конфликт, возникающий когда два контроллера (Operator и GitOps) пытаются управлять одним и тем же ресурсом. В контексте Prometheus Operator: ArgoCD может удалить/изменить ServiceMonitor, который Operator ожидает найти.

**Pruning (Обрезка)** — механизм GitOps-инструмента, удаляющий из кластера ресурсы, отсутствующие в Git. Без осторожного настройки Pruning может удалить CRD, созданные Operator-ом (например, auto-generated Secrets).

**ApplicationSet** — шаблон ArgoCD для автоматического создания Application для каждого кластера/окружения. Позволяет деплоить один и тот же monitoring stack в несколько кластеров с разными values.

> **Смотрите также:** [Установка](./installation.md) — ручная установка и Kustomize; [Концепции](./concepts.md) — архитектура Operator.

---

## Базовые концепции

### Модель взаимодействия Operator + GitOps

```
Git Repository
    ├── base/
    │   ├── operator/
    │   │   ├── bundle.yaml
    │   │   └── kustomization.yaml
    │   ├── crds/
    │   │   ├── prometheus.yaml
    │   │   ├── alertmanager.yaml
    │   │   └── servicemonitor-*.yaml
    │   └── rules/
    │       ├── node-alerts.yaml
    │       └── app-alerts.yaml
    └── overlays/
        ├── prod/
        │   ├── values-patch.yaml
        │   └── kustomization.yaml
        └── staging/
            ├── values-patch.yaml
            └── kustomization.yaml
            ↓
Argo CD
    ↓ sync
Kubernetes Cluster
    ↓ reconcile
Prometheus Operator
    ↓ generate
Prometheus/Alertmanager StatefulSets
```

### Кто чем управляет

| Ресурс | Владелец | GitOps | Operator |
|:---|:---|:---|:---|
| Deployment/StatefulSet Operator | GitOps | **Да** (manages) | Нет |
| CRD (ServiceMonitor, PrometheusRule) | GitOps | **Да** (manages) | Читает |
| Prometheus/Alertmanager CR | GitOps | **Да** (manages) | Reconcile |
| Secret (auto-generated Operator-ом) | Operator | **Нет** (prune risk) | **Да** (creates) |
| Service/EndpointSlice | Operator | **Нет** (prune risk) | **Да** (creates) |
| StatefulSet Prometheus/Alertmanager | Operator | **Нет** (prune risk) | **Да** (creates) |

**Критический момент:** Operator создает ресурсы (Secrets, Services, StatefulSets), которых нет в Git. GitOps может удалить их при Pruning. Это основной источник конфликтов.

### ArgoCD: Настройки для Operator

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus-operator
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/monitoring-manifests.git
    path: overlays/prod
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: false  # КРИТИЧНО: отключить prune для Operator namespace
      selfHeal: true
    syncOptions:
      - CreateNamespace=false
      - SkipDryRunOnMissingResource=true  # Для CRD, которые еще не созданы
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
  ignoreDifferences:
    # Игнорировать изменения, внесенные Operator-ом
    - group: ""
      kind: Secret
      jsonPointers:
        - /data
    - group: apps
      kind: StatefulSet
      jsonPointers:
        - /spec/replicas
    - group: ""
      kind: Service
      jsonPointers:
        - /spec/clusterIP
```

### Сценарий: Argo CD — Настройки для Operator

---

## Практические сценарии

### Сценарий 1: ArgoCD ApplicationSet для multi-cluster

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: monitoring-stack
  namespace: argocd
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            monitoring: enabled
  template:
    metadata:
      name: 'monitoring-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/monitoring-manifests.git
        path: overlays/{{metadata.labels.environment}}
        targetRevision: main
      destination:
        server: '{{server}}'
        namespace: monitoring
      syncPolicy:
        automated:
          prune: false
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - SkipDryRunOnMissingResource=true
```

### Сценарий 2: Vault-интеграция для секретов через GitOps

Секреты не должны храниться в Git. Используйте External Secrets Operator (ESO):

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: thanos-objstore-config
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: thanos-objstore-config
    creationPolicy: Owner
  data:
    - secretKey: thanos.yaml
      remoteRef:
        key: monitoring/thanos
        property: config
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: alertmanager-slack
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: alertmanager-slack-webhook
    creationPolicy: Owner
  data:
    - secretKey: url
      remoteRef:
        key: monitoring/alerts
        property: slack_webhook
```

### Сценарий 3: Handling CRD Mismatch при обновлении

При обновлении Operator (через Helm или bundle.yaml) CRD должны быть обновлены ДО нового Operator:

```yaml
# ArgoCD:使用_resourceTrackingMethod=annotation для CRD
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus-crds
  annotations:
    argocd.argoproj.io/manifest-generate-paths: /crds
spec:
  source:
    path: crds
  syncPolicy:
    syncOptions:
      - ServerSideApply=true  # Для CRD с large schema
      - RespectIgnoreDifferences=true
```

### Сценарий 4: Канареечное обновление через ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus-canary
spec:
  source:
    path: overlays/canary
  syncPolicy:
    automated:
      prune: false
  # Шаг 1: Sync canary
  # Шаг 2: Проверить метрики
  # Шаг 3: Promote в production
```

### Диагностика GitOps-конфликтов

```bash
# 1. Проверка sync-статуса ArgoCD
argocd app list -n argocd
argocd app get prometheus-operator -n argocd

# 2. Проверка конфликтов
argocd app diff prometheus-operator -n argocd

# 3. Проверка finalizers
kubectl get prometheus -n monitoring -o json | jq '.items[].metadata.finalizers'

# 4. Проверка annotations Operator
kubectl get servicemonitor -n monitoring -o json | \
  jq '.items[].metadata.annotations["prometheus-operator-uid"]'

# 5. Проверка Events на предмет prune
kubectl get events -n monitoring --field-selector reason=FailedCreate | tail -20
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Установка](./installation.md) | Kustomize overlays, ручная установка |
| [Secrets](./Security/secrets_best_practices.md) | ESO, CSI Driver, ротация секретов |
| [Kube-Prometheus-Stack Helm](../Kube_Prometheus_Stack_Helm/overview.md) | Helm-based deployment (альтернатива GitOps) |

### Частые ошибки на собеседованиях

1. **"GitOps может безопасно управлять Namespace Operator"** — Нет. Необходимо отключить Pruning для namespace, где работает Operator, иначе GitOps удалит auto-generated Secrets/Services/StatefulSets.
2. **"CRD деплоятся автоматически с Operator"** — Нет. CRD должны быть установлены отдельно И ПЕРЕД Operator. Используйте отдельный ArgoCD Application.
3. **"selfHeal безопасен для Operator"** — Рискованно. selfHeal может откатить изменения, внесенные Operator-ом (например, replicas). Настройте ignoreDifferences.
