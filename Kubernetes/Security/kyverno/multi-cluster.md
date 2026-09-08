# Управление политиками Kyverno в мультикластере

## Определения

**Multi-Cluster Management** — подход к управлению политиками безопасности в нескольких кластерах Kubernetes одновременно. Включает централизованное распространение политик, консистентность конфигураций и агрегацию отчетов.

**Fleet** — группа кластеров, управляемых из единой точки. В контексте Kyverno Fleet Management обеспечивает синхронизацию политик между control plane и рабочими кластерами.

**GitOps-Driven Policy** — подход, при котором политики распространяются через Git-репозитории с автоматической синхронизацией через Argo CD или Flux. Обеспечивает версионирование, аудит и rollback политик.

---

## Архитектура мультикластерного управления

```text
┌─────────────────────────────────────────────────────────────────┐
│  Control Plane (Управляющий кластер)                            │
│  ────────────────────────────────────────────────────────────  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  GitOps Repository (Argo CD ApplicationSet)             │   │
│  │  ─────────────────────────────────────────────────────  │   │
│  │  • kyverno-policies/base/ (общие политики)              │   │
│  │  • kyverno-policies/overlays/ (окружения)               │   │
│  │  • policy-reporter/ (конфигурация агрегации)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                      │                                          │
│       ┌──────────────┼──────────────┐                           │
│       ▼              ▼              ▼                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                     │
│  │ Cluster1 │  │ Cluster2 │  │ Cluster3 │                     │
│  │ (Prod)   │  │ (Stage)  │  │ (Dev)    │                     │
│  └──────────┘  └──────────┘  └──────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: GitOps с ApplicationSet

**Цель:** Автоматическое распространение политик во все кластеры через Argo CD.

**Структура репозитория:**

```bash
gitops-policies/
├── base/
│   ├── require-labels/
│   │   ├── kustomization.yaml
│   │   └── policy.yaml
│   ├── resource-limits/
│   │   ├── kustomization.yaml
│   │   └── policy.yaml
│   └── image-registry/
│       ├── kustomization.yaml
│       └── policy.yaml
├── overlays/
│   ├── production/
│   │   ├── kustomization.yaml
│   │   └── patches/
│   │       ├── require-labels-patch.yaml
│   │       └── resource-limits-patch.yaml
│   ├── staging/
│   │   ├── kustomization.yaml
│   │   └── patches/
│   └── development/
│       ├── kustomization.yaml
│       └── patches/
└── applicationset.yaml
```

**ApplicationSet для распространения:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: kyverno-policies
  namespace: argocd
spec:
  generators:
    - matrix:
        generators:
          # Генератор кластеров
          - clusters:
              selector:
                matchLabels:
                  environment: production
          # Генератор политик
          - git:
              repoURL: https://github.com/myorg/gitops-policies.git
              revision: main
              directories:
                - path: base/*
  template:
    metadata:
      name: '{{path.basename}}-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/myorg/gitops-policies.git
        targetRevision: main
        path: 'overlays/{{metadata.labels.environment}}/{{path.basename}}'
      destination:
        server: '{{server}}'
        namespace: kyverno
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

**Политика для production:**

```yaml
# overlays/production/require-labels-patch.yaml
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: require-labels
spec:
  validationActions: [Deny]  # Enforce для production
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "has(object.metadata.labels) && has(object.metadata.labels['app']) && has(object.metadata.labels['team'])"
      message: "Labels 'app' и 'team' обязательны в production"
```

### Сценарий 2: Кластер-специфичные политики

**Цель:** Разные политики для разных кластеров (prod, stage, dev).

**Генератор с параметрами:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: kyverno-cluster-policies
spec:
  generators:
    - list:
        elements:
          - cluster: production
            url: https://kubernetes.prod.example.com
            env: production
            validationFailureAction: Deny
          - cluster: staging
            url: https://kubernetes.stage.example.com
            env: staging
            validationFailureAction: Audit
          - cluster: development
            url: https://kubernetes.dev.example.com
            env: development
            validationFailureAction: Audit
  template:
    metadata:
      name: 'kyverno-{{cluster}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/myorg/gitops-policies.git
        targetRevision: main
        path: 'overlays/{{env}}'
      destination:
        server: '{{url}}'
        namespace: kyverno
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

**Параметризованные политики:**

```yaml
# base/require-labels/policy.yaml
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: require-labels
spec:
  validationActions: [{{validationFailureAction}}]
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "has(object.metadata.labels) && has(object.metadata.labels['app'])"
      message: "Label 'app' обязателен"
```

### Сценарий 3: Агрегация PolicyReport в мультикластере

**Цель:** Централизованный мониторинг нарушений во всех кластерах.

**Настройка Policy Reporter с federation:**

```yaml
# control-plane-values.yaml
policyReporter:
  # Включение federation mode
  federation:
    enabled: true
    listenAddress: ":8080"
  
  # Подключение к рабочим кластерам
  sources:
    - name: production
      type: kubernetes
      config:
        kubeconfig: /etc/kubernetes/config/prod-kubeconfig
        namespace: kyverno
    - name: staging
      type: kubernetes
      config:
        kubeconfig: /etc/kubernetes/config/stage-kubeconfig
        namespace: kyverno
    - name: development
      type: kubernetes
      config:
        kubeconfig: /etc/kubernetes/config/dev-kubeconfig
        namespace: kyverno

  # Централизованные targets
  targets:
    - name: prometheus
      type: prometheus
      config:
        endpoint: http://prometheus:9090
    - name: grafana
      type: grafana
      config:
        endpoint: http://grafana:3000
```

**Конфигурация federated Prometheus:**

```yaml
# prometheus-federation.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'kyverno-federation'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
            - kyverno
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        regex: policy-reporter
        action: keep
      - source_labels: [__meta_kubernetes_pod_annotation_federation_source]
        target_label: source_cluster
```

**Агрегированные метрики:**

```yaml
# prometheus-rules.yml
groups:
  - name: kyverno-federation
    rules:
      - record: kyverno_policy_violations_total_by_cluster
        expr: |
          sum(kyverno_policy_results_total{result="fail"}) by (source_cluster, policy)
      
      - alert: FederationHighViolationRate
        expr: |
          sum(rate(kyverno_policy_results_total{result="fail"}[5m])) by (source_cluster) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень нарушений в кластере {{ $labels.source_cluster }}"
          description: "{{ $value }} нарушений в минуту"
```

### Сценарий 4: Rollback политик в мультикластере

**Цель:** Откат политики во всех кластерах при обнаружении проблем.

**Процесс rollback:**

```bash
# Шаг 1: Обнаружение проблемы в staging
kubectl get policyreport -n kyverno -o json | \
  jq '.items[] | select(.summary.fail > 0) | .metadata.name'

# Шаг 2: Ручной откат через Argo CD
argocd app rollback kyverno-policies-staging 1

# Шаг 3: Автоматический rollback через Git
git revert HEAD --no-edit
git push origin main
# Argo CD автоматически применит откат

# Шаг 4: Принудительный sync для конкретного кластера
argocd app sync kyverno-policies-production --force
```

**Automated Rollback Policy:**

```yaml
# Argo CD Application с автоматическим rollback
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno-policies-production
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    retry:
      limit: 3
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
```

---

## Дополнительная информация

### Кластер-специфичные исключения

```yaml
# Исключения для конкретных кластеров
apiVersion: v2.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: resource-limits
  labels:
    kyverno.io/fleet: "production"
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  validations:
    - expression: "object.spec.containers.all(c, has(c.resources.limits))"
      message: "Resource limits обязательны"
  # Исключения для определенных кластеров
  exceptions:
    - clusterName: development
      namespaces: ["default", "test"]
```

### Мониторинг консистентности

```bash
# Проверка консистентности политик между кластерами
kubectl get clusterpolicy -A -o json | \
  jq -r '.items[] | "\(.metadata.name) \(.spec.validationFailureAction)"' | \
  sort | uniq -c | sort -rn

# Сравнение политик между кластерами
for cluster in prod stage dev; do
  echo "=== $cluster ==="
  kubectl --context=$cluster get clusterpolicy -o json | \
    jq -r '.items[] | .metadata.name' | sort
done
```

### См. также
- [GitOps-интеграция](./argo-cd.md) — настройка Argo CD с Kyverno
- [Производительность](./performance.md) — масштабирование в мультикластере
- [Disaster Recovery](./disaster-recovery.md) — восстановление после сбоев
- [Policy Reporter](./reporter.md) — агрегация отчетов
