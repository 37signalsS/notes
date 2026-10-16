# Traefik в GitOps и CI/CD: валидация, пайплайн, паттерны

## Определения

**GitOps** — подход к управлению инфраструктурой и конфигурацией, при котором Git является единственным источником правды. Изменения применяются автоматически через синхронизацию.

**CI/CD для Traefik** — пайплайн непрерывной интеграции и доставки для валидации и применения конфигурации Traefik.

**Configuration validation** — проверка конфигурации Traefik на синтаксические и семантические ошибки до применения.

**Canary promotion** — автоматическое повышение веса canary после успешных проверок.

**Infrastructure as Code (IaC)** — управление конфигурацией Traefik через код (YAML, Helm values, Terraform).

## Базовые концепции

### Структура репозитория

```
infra/
├── traefik/
│   ├── helm/
│   │   ├── values/
│   │   │   ├── values-base.yaml
│   │   │   ├── values-staging.yaml
│   │   │   └── values-production.yaml
│   │   └── Chart.yaml
│   ├── dynamic/
│   │   ├── middlewares/
│   │   │   ├── secure-headers.yaml
│   │   │   └── rate-limit.yaml
│   │   └── routers/
│   │       ├── app.yaml
│   │       └── api.yaml
│   ├── crds/
│   │   ├── ingressroutes/
│   │   └── middlewares/
│   └── tests/
│       ├── lint/
│       └── validate/
```

### Валидация конфигурации

Traefik поддерживает валидацию через CLI:
```bash
traefik config validate --configfile=/etc/traefik/traefik.yml
```

Для Kubernetes: валидация CRD через `kubectl apply --dry-run`.

### Паттерны GitOps

1. **Push-based**: CI пайплайн валидирует и применяет изменения.
2. **Pull-based**: Argo CD синхронизирует репозиторий с кластером.

### Интеграция с Argo CD

- **Argo CD**: Application отслруживает Helm release или Kustomize overlay.

## Практические сценарии

### Сценарий 1: Валидация в CI

```yaml
# .github/workflows/traefik-validate.yml
name: Traefik Config Validation
on:
  pull_request:
    paths:
    - 'traefik/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Validate static config
      run: |
        docker run --rm \
          -v "$(pwd)/traefik/traefik.yml:/etc/traefik/traefik.yml:ro" \
          traefik:v3.4 config validate --configfile=/etc/traefik/traefik.yml

    - name: Validate dynamic config
      run: |
        for f in traefik/dynamic/*.yaml; do
          docker run --rm \
            -v "$(pwd)/traefik/traefik.yml:/etc/traefik/traefik.yml:ro" \
            -v "$(pwd)/$f:/etc/traefik/dynamic/$(basename $f):ro" \
            traefik:v3.4 config validate --configfile=/etc/traefik/traefik.yml
        done

    - name: Validate CRDs
      run: |
        kubectl apply --dry-run=client -f traefik/crds/
```

### Сценарий 2: Helm values per environment

```yaml
# values-base.yaml
deployment:
  replicas: 2

service:
  type: ClusterIP

metrics:
  prometheus:
    enabled: true
    entryPoint: metrics
```

```yaml
# values-production.yaml
deployment:
  replicas: 3

service:
  type: LoadBalancer
  annotations:
    metallb.universe.tf/address-pool: production-pool

providers:
  kubernetesCRD:
    allowCrossNamespace: false

networkPolicy:
  enabled: true
```

```bash
# Применение
helm upgrade --install traefik traefik/traefik \
  --namespace traefik \
  --values values-base.yaml \
  --values values-production.yaml
```

### Сценарий 3: ArgoCD Application

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: traefik
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/org/infra.git
    targetRevision: HEAD
    path: traefik/helm
  destination:
    server: https://kubernetes.default.svc
    namespace: traefik
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
```

### Сценарий 4: Argo CD Application (Helm chart)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: traefik
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://traefik.github.io/charts
    chart: traefik
    targetRevision: ">=34.0.0"
    helm:
      releaseName: traefik
      values: |
        deployment:
          replicas: 2
        service:
          type: LoadBalancer
  destination:
    server: https://kubernetes.default.svc
    namespace: traefik
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

### Сценарий 5: Автоматический canary promotion (Flagger)

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: app
  namespace: prod
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: app
  progressDeadlineSeconds: 60
  service:
    port: 80
    targetPort: 8080
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
    - name: request-success-rate
      thresholdRange:
        min: 99
      interval: 1m
    - name: latency
      thresholdRange:
        max: 500
      interval: 1m
```

### Сценарий 6: Pre-commit hooks

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
  - id: traefik-config-validate
    name: Traefik config validate
    entry: bash -c 'docker run --rm -v "$(pwd)/traefik/traefik.yml:/etc/traefik/traefik.yml:ro" traefik:v3.4 config validate'
    language: system
    files: 'traefik/.*\.yml$'
```

## Операции и команды

```bash
# Валидация конфигурации
traefik config validate --configfile=/etc/traefik/traefik.yml

# Валидация через Docker
docker run --rm -v "$(pwd)/traefik.yml:/etc/traefik/traefik.yml:ro" traefik:v3.4 config validate

# Helm lint
helm lint traefik/helm

# Helm template
helm template traefik traefik/traefik -f values.yaml

# Dry-run kubectl
kubectl apply --dry-run=client -f crds/
kubectl diff -f crds/
```

## Устранение неисправлений

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **ArgoCD не синхронизирует** | Репозиторий недоступен, ошибка в Helm values | Проверьте connectivity, `argocd app diff traefik` |
| **Валидация падает** | Ошибка в YAML, несуществующее поле | Проверьте `traefik config validate` вывод |
| **Canary не продвигается** | Метрики не достигают порога | Проверьте SLO, настройте `threshold` |
| **Pre-commit не работает** | Docker не запущен, volumes неверны | Запустите Docker, проверьте пути |

## Рекомендации

- Валидация — обязательный шаг в CI перед любым применением.
- Helm values разделяйте по окружениям (base + overlay).
- Для Argo CD используйте `CreateNamespace=true` и `selfHeal=true`.
- Canary promotion автоматизируйте через Flagger с четкими SLO.
- Храните конфигурацию в Git, используйте PR/MR для изменений.
- Для критических изменений используйте manual approval в ArgoCD.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура, providers.
- [Traefik в Kubernetes](./traefik-kubernetes.md) — CRD, Helm.
- [Gateway API Traefik](../../Kubernetes/Networking/gateway_api/traefik.md) — Gateway API deployment.
- [Progressive Delivery в GitOps](../../GitOps/Concepts/progressive_delivery_gitops.md) — Flagger, Argo Rollouts.
- [Helm installation](../../Kubernetes/Networking/Ingress/installation/helm-installation.md) — Helm commands.
- [Argo CD](https://argo-cd.readthedocs.io/) — документация Argo CD.
