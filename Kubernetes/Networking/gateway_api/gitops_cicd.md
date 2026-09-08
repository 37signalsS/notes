# GitOps и CI/CD для Gateway API

## Определения

**GitOps** — методология управления инфраструктурой, при которой Git-репозиторий является единственным источником истины (SSoT) для декларативного описания конфигурации системы. Изменения применяются автоматически при пуше в репозиторий.

**ArgoCD** — GitOps-контроллер для Kubernetes, отслеживающий изменения в Git-репозитории и автоматически синхронизирующий конфигурацию в кластере. Поддерживает валидацию манифестов и визуализацию diff.

**Flux** — набор GitOps-компонентов (Source Controller, Kustomize Controller, Helm Controller, Notification Controller) для Kubernetes. Официальный CNCF-проект для декларативного управления конфигурацией.

**kubeconform** — быстрый, строгий валидатор манифестов Kubernetes, заменяющий устаревший kubeval. Поддерживает валидацию CRD через OpenAPI-схемы, включая Gateway API.

**Progressive Delivery** — методология постепенного внедрения изменений с контролем на каждом этапе. Включает Canary, Blue-Green, Shadow деплои с автоматическим откатом при проблемах.

## Предварительные требования

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ | `kubectl get crd gateways.gateway.networking.k8s.io` |
| ArgoCD | 3.0+ (или Flux 2.x) | `kubectl get pods -n argocd` |
| kubeconform | 0.6+ | `kubeconform -v` |

## Базовые концепции

### Почему GitOps критичен для Gateway API

Gateway API ресурсы (Gateway, HTTPRoute, ReferenceGrant) — декларативные и идеально подходят для GitOps:

1. **Версионирование:** каждое изменение маршрутизации коммитится в Git с описанием
2. **Review:** PR/MR перед применением позволяет проверить изменения
3. **Audit:** история коммитов показывает кто, когда и почему изменил маршрутизацию
4. **Rollback:** откат к предыдущей версии — один git revert
5. **Валидация:** CI проверяет манифесты до применения в кластере

### Структура репозитория

```
gitops-gateway-api/
├── base/                          # Базовые ресурсы (common)
│   ├── gatewayclass.yaml
│   └── base-gateway.yaml
├── apps/                          # Приложения
│   ├── app-a/
│   │   ├── kustomization.yaml
│   │   ├── httproute.yaml
│   │   ├── backendtlspolicy.yaml
│   │   └── referencegrant.yaml
│   └── app-b/
│       ├── kustomization.yaml
│       └── httproute.yaml
├── infrastructure/                # Инфраструктура
│   ├── envoy-gateway/
│   │   ├── helmrelease.yaml       # (для Flux) или Application.yaml (для ArgoCD)
│   │   └── values.yaml
│   └── monitoring/
│       ├── servicemonitor.yaml
│       └── prometheusrule.yaml
├── envs/                          # Окружения
│   ├── production/
│   │   ├── kustomization.yaml
│   │   └── gateway-patch.yaml
│   ├── staging/
│   │   ├── kustomization.yaml
│   │   └── gateway-patch.yaml
│   └── dev/
│       ├── kustomization.yaml
│       └── gateway-patch.yaml
└── ci/                            # CI скрипты
    ├── validate.sh
    └── pipeline.yaml
```

## Практические сценарии

### CI: Валидация Gateway API манифестов с kubeconform

```bash
#!/bin/bash
# validate.sh — валидация Gateway API манифестов

set -euo pipefail

# Скачивание OpenAPI-схем Gateway API (если не кэшированы)
SCHEMA_DIR="/tmp/gateway-api-schemas"
mkdir -p $SCHEMA_DIR

if [ ! -f "$SCHEMA_DIR/gateway.networking.k8s.io_httproute.json" ]; then
  echo "Скачивание схем Gateway API..."
  for resource in gatewayclasses gateways httproutes grpcroutes tlsroutes tcproutes udproutes referencegrants backendtlspolicies; do
    curl -sL "https://raw.githubusercontent.com/kubernetes-sigs/gateway-api/main/config/crd/${resource}.yaml" \
      | kubeconform -summary -output json 2>/dev/null || true
  done
fi

# Валидация стандартных схем
echo "=== Валидация стандартных ресурсов Kubernetes ==="
find . -name "*.yaml" -o -name "*.yml" | xargs kubeconform \
  -strict \
  -summary \
  -output json \
  -ignore-missing-schemas

# Валидация с Gateway API CRD схемами
echo "=== Валидация Gateway API ресурсов ==="
find . -name "*.yaml" -o -name "*.yml" | xargs kubeconform \
  -strict \
  -summary \
  -output json \
  -schema-location default \
  -schema-location "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json"

echo "=== Валидация завершена ==="
```

### CI Pipeline: GitHub Actions для Gateway API

```yaml
# .github/workflows/gateway-api-validate.yaml
name: Validate Gateway API manifests

on:
  pull_request:
    paths:
    - 'kubernetes/**'
    - 'gateway-api/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Install kubeconform
      run: |
        curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz \
          | tar xz -C /usr/local/bin kubeconform

    - name: Validate manifests
      run: |
        find kubernetes/ -name "*.yaml" | xargs kubeconform \
          -strict \
          -summary \
          -output json \
          -ignore-missing-schemas

    - name: Dry-run apply
      run: |
        kubectl apply --dry-run=client -f kubernetes/gateway-api/
```

### CI Pipeline: GitLab CI для Gateway API

```yaml
# .gitlab-ci.yml
stages:
- validate
- deploy-staging
- deploy-production

validate-gateway-api:
  stage: validate
  image: bitnami/kubectl:1.28
  script:
  - curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz | tar xz -C /usr/local/bin kubeconform
  - find kubernetes/ -name "*.yaml" | xargs kubeconform -strict -summary -ignore-missing-schemas
  - kubectl apply --dry-run=client -f kubernetes/gateway-api/

deploy-staging:
  stage: deploy-staging
  image: bitnami/kubectl:1.28
  script:
  - kubectl apply -f kubernetes/gateway-api/ -n staging
  - kubectl wait --for=condition=Programmed gateway/external-gw -n staging --timeout=120s
  environment:
    name: staging
  only:
  - main
```

### ArgoCD: Application для Gateway API

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: gateway-api
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/gitops-gateway-api.git
    targetRevision: main
    path: envs/production
  destination:
    server: https://kubernetes.default.svc
    namespace: gateway-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - PrunePropagationPolicy=foreground
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

### Flux: Kustomization для Gateway API

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: gateway-api
  namespace: flux-system
spec:
  interval: 5m
  path: ./envs/production
  prune: true
  sourceRef:
    kind: GitRepository
    name: gateway-api
  healthChecks:
  - apiVersion: gateway.networking.k8s.io/v1
    kind: Gateway
    name: external-gw
    namespace: gateway-system
  timeout: 3m
```

### Flux: GitRepository источник

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: gateway-api
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/myorg/gitops-gateway-api.git
  ref:
    branch: main
  secretRef:
    name: git-credentials
```

### Progressive Delivery с Flagger

Flagger автоматизирует Canary/Blue-Green деплой через Gateway API:

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: api-service
  namespace: production
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-service
  progressDeadlineSeconds: 600
  service:
    port: 8080
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
    - name: request-duration
      thresholdRange:
        max: 500
      interval: 30s
    webhooks:
    - name: load-test
      url: http://flagger-loadtester.flagger-system/
      timeout: 5s
      metadata:
        cmd: "hey -z 1m -q 10 -c 2 http://api-service-canary.production:8080"
  analysisRef:
    gateways:
    - external-gw
    trafficRouting:
      gatewayAPI:
        routeName: api-service-canary
        stableService: api-service
        canaryService: api-service-canary
```

## Troubleshooting

### Типичные ошибки GitOps + Gateway API

| Симптом | Причина | Решение |
|:---|:---|:---|
| ArgoCD не синхронизирует | Неверный path или branch | Проверить `spec.source.path` в Application |
| Flux Kustomization в error | Health check не проходит | Проверить `healthChecks`, увеличить timeout |
| kubeconform не находит CRD | Отсутствуют Gateway API схемы | Добавить `-schema-location` с URL схем |
| CI pipeline падает на validate | Синтаксическая ошибка YAML | Проверить манифесты: `kubectl apply --dry-run=client` |
| Canary analysis fails | Метрики не доступны | Проверить Prometheus, ServiceMonitor |
| PR с Gateway API мержится без проверки | CI pipeline не настроен на paths | Обновить `on.pull_request.paths` |

### Диагностика ArgoCD

```bash
# Проверка статуса Application
kubectl get application gateway-api -n argocd -o yaml

# Просмотр diff
argocd app diff gateway-api

# Принудительная синхронизация
argocd app sync gateway-api

# Просмотр логов ArgoCD
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --tail=100
```

### Диагностика Flux

```bash
# Проверка статуса Kustomization
kubectl get kustomization gateway-api -n flux-system

# Просмотр событий
kubectl describe kustomization gateway-api -n flux-system

# Просмотр логов Flux
kubectl logs -n flux-system -l app=kustomize-controller --tail=100
```

## Best Practices

### Структура репозитория

1. **Разделяйте base и envs:**
   - `base/` — общие ресурсы без специфичных для окружения значений
   - `envs/` — patches для каждого окружения (dev, staging, production)

2. **Один PR — одно изменение:**
   - Изоляция изменений для удобства review и rollback
   - Описательные названия коммитов

3. **Валидация в CI:**
   - kubeconform с Gateway API CRD-схемами
   - `kubectl apply --dry-run=client` для проверки семантики
   - OPA/Gatekeeper для политик безопасности

### Безопасность

1. **RBAC для ArgoCD/Flux:**
   - Ограниченные права на создание/изменение Gateway API ресурсов
   - Отдельный ServiceAccount для каждого контроллера

2. **PR review:**
   - Обязательный review перед мержем
   - Проверка что ReferenceGrant корректны
   - Валидация что TLS-сертификаты существуют

3. **Secrets:**
   - Не хранить TLS-сертификаты в Git
   - Использовать Sealed Secrets, SOPS или External Secrets Operator
   - ReferenceGrant на Secret создавать отдельно

### Мониторинг GitOps

1. **Отслеживайте sync status:**
   - ArgoCD: `argocd app get gateway-api`
   - Flux: `kubectl get kustomization -A`

2. **Алерты на sync failure:**
   ```yaml
   - alert: GatewayAPISyncFailed
     expr: argocd_app_info{sync_status!="Synced",name="gateway-api"} == 1
     for: 5m
     labels:
       severity: warning
   ```

3. **Логируйте все изменения:**
   - Git commit history как аудит-лог
   - Flux notifications в Slack/Teams

## Дополнительная информация

### Связанные ресурсы

- [Определения Gateway API](./definitions.md) — общие концепции
- [Миграция с Ingress](./migration.md) — процесс миграции
- [Мониторинг](./monitoring.md) — настройка метрик для GitOps
- [Высокая доступность](./high_availability.md) — HA для GitOps-управляемых ресурсов

**Родительская тема:** [Gateway API](./definitions.md)
