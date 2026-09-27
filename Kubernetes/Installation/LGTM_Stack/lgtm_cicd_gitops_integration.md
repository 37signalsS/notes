# Интеграция стека LGTM с CI/CD и GitOps

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**
> - **[CI/CD интеграция](./lgtm_cicd_gitops_integration.md)** (текущий)

---

## Определения

**GitOps** — операционная модель, в которой Git является единственным источником истины (SSoT) для декларативного описания желаемого состояния инфраструктуры. Изменения применяются автоматически через reconciliation loop.

**Pull-based Deployment** — модель доставки, при которой агент внутри кластера (ArgoCD, Flux) самостоятельно забирает изменения из Git и применяет их. В отличие от Push-based (CI пушит в кластер), Pull-based обеспечивает лучшую безопасность и аудит.

**Reconciliation Loop** — процесс непрерывного сравнения текущего состояния кластера с желаемым состоянием в Git и применения изменений для достижения консистентности.

**Drift Detection** — механизм обнаружения расхождений между текущим состоянием кластера и описанием в Git. Автоматическое исправление дрейфа (self-healing) является ключевым преимуществом GitOps.

---

## Основные концепции

### Архитектура GitOps для LGTM стека

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        GitOps Architecture for LGTM                     │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Git Repository                                 │  │
│  │  • Helm values.yaml для каждого компонента                       │  │
│  │  • Kubernetes манифесты (NetworkPolicy, RBAC)                     │  │
│  │  • Правила алертинга (PrometheusRule)                             │  │
│  │  • Конфигурация OTel Collector                                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    GitOps Agent (ArgoCD / Flux)                   │  │
│  │  • Pull-based: агент забирает изменения из Git                   │  │
│  │  • Reconciliation: непрерывное сравнение состояний               │  │
│  │  • Self-healing: автоматическое исправление дрейфа                │  │
│  │  • Health checks: проверка готовности ресурсов                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                              ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Kubernetes Cluster                              │  │
│  │  • Prometheus, Grafana, Loki, Tempo                               │  │
│  │  • OTel Collector, Operator                                       │  │
│  │  • NetworkPolicies, RBAC                                          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Преимущества GitOps для LGTM

| Преимущество | Описание | Реализация |
| :--- | :--- | :--- |
| **Прослеживаемость** | Каждое изменение фиксируется в Git | git log, PR reviews |
| **Аудит** | Полная история изменений конфигурации | Git history |
| **Воспроизводимость** | Одно и то же состояние可以从 одного коммита | Tagged releases |
| **Безопасность** | CI не имеет доступа к кластеру | Pull-based model |
| **Self-healing** | Автоматическое исправление дрейфа | Reconciliation loop |
| **Откат** | Простой возврат к предыдущей версии | git revert |

---

## Практические сценарии

### Сценарий 1: Структура GitOps репозитория для LGTM

**Цель:** Организация репозитория для управления стеком LGTM.

#### Шаг 1: Создание структуры директорий

```bash
mkdir -p lgtm-gitops/{base,overlays/{dev,staging,prod}}
```

#### Шаг 2: Создание базовых манифестов

```yaml
# base/prometheus/values.yaml
prometheus:
  prometheusSpec:
    retention: 15d
    storageSpec:
      volumeClaimTemplate:
        spec:
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi

grafana:
  enabled: true
  adminPassword: ${GRAFANA_ADMIN_PASSWORD}
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.${DOMAIN}
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.${DOMAIN}
```

```yaml
# base/loki/values.yaml
loki:
  auth_enabled: true
  commonConfig:
    replication_factor: 3
  storage:
    type: s3
    s3:
      endpoint: ${S3_ENDPOINT}
      region: ${AWS_REGION}
      secretAccessKey: ${S3_SECRET_KEY}
      accessKeyId: ${S3_ACCESS_KEY}
```

```yaml
# base/tempo/values.yaml
tempo:
  storage:
    trace:
      backend: s3
      s3:
        endpoint: ${S3_ENDPOINT}
        region: ${AWS_REGION}
        secretAccessKey: ${S3_SECRET_KEY}
        accessKeyId: ${S3_ACCESS_KEY}
```

#### Шаг 3: Создание overlays для разных окружений

```yaml
# overlays/prod/prometheus-patch.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-values
  namespace: monitoring
data:
  values.yaml: |
    prometheus:
      prometheusSpec:
        retention: 30d
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: encrypted-ssd
              resources:
                requests:
                  storage: 100Gi
        resources:
          limits:
            cpu: 2000m
            memory: 4Gi
          requests:
            cpu: 500m
            memory: 2Gi
```

---

### Сценарий 2: Настройка ArgoCD для LGTM стека

**Цель:** Развертывание и управление LGTM стеком через ArgoCD.

> **Примечание:** Подробная теория ArgoCD описана в:
> - [ArgoCD: Обзор](../../../GitOps/ArgoCD/argocd_overview.md)
> - [GitOps: Пайплайн](../../../GitOps/gitops_pipeline_example.md)

#### Шаг 1: Установка ArgoCD

```bash
kubectl create namespace argocd

helm repo add argo https://argoproj.github.io/argo-helm
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --set server.extraArgs[0]="--insecure" \
  --version 7.3.11
```

#### Шаг 2: Создание Application для Prometheus

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/lgtm-gitops.git
    targetRevision: main
    path: overlays/prod
    helm:
      valueFiles:
        - values-prometheus.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### Шаг 3: Создание Application для Loki

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/lgtm-gitops.git
    targetRevision: main
    path: overlays/prod
    helm:
      valueFiles:
        - values-loki.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: loki
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### Шаг 4: Создание Application для Tempo

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tempo
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/lgtm-gitops.git
    targetRevision: main
    path: overlays/prod
    helm:
      valueFiles:
        - values-tempo.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: tempo
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

#### Шаг 5: Создание Application для OTel Collector

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/lgtm-gitops.git
    targetRevision: main
    path: overlays/prod
    helm:
      valueFiles:
        - values-otel.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: opentelemetry
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Валидация:**

```bash
# Проверка статуса ArgoCD приложений
kubectl get applications -n argocd

# Проверка синхронизации
argocd app list
# → Expected: все приложения в статусе Synced/Healthy
```

---

### Сценарий 3: Настройка Flux для LGTM стека

**Цель:** Альтернативная реализация GitOps с помощью Flux.

> **Примечание:** Подробная теория Flux описана в:
> - [Flux: Обзор](../../../GitOps/flux.md)

#### Шаг 1: Установка Flux

```bash
flux bootstrap github \
  --owner=your-org \
  --repository=lgtm-gitops \
  --branch=main \
  --path=./clusters/production \
  --personal
```

#### Шаг 2: Создание HelmRelease для Prometheus

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: prometheus
  namespace: monitoring
spec:
  interval: 5m
  chart:
    spec:
      chart: kube-prometheus-stack
      version: "88.6.2"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    prometheus:
      prometheusSpec:
        retention: 30d
        storageSpec:
          volumeClaimTemplate:
            spec:
              storageClassName: encrypted-ssd
              resources:
                requests:
                  storage: 100Gi
```

#### Шаг 3: Создание Kustomization для NetworkPolicies

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1beta1
kind: Kustomization
metadata:
  name: network-policies
  namespace: flux-system
spec:
  interval: 10m
  path: ./network-policies
  prune: true
  sourceRef:
    kind: GitRepository
    name: lgtm-gitops
```

---

### Сценарий 4: CI/CD пайплайн для обновления LGTM

**Цель:** Автоматизация обновления компонентов стека LGTM.

#### Шаг 1: GitHub Actions workflow для обновления зависимостей

```yaml
# .github/workflows/update-lgtm-deps.yml
name: Update LGTM Dependencies

on:
  schedule:
    - cron: '0 6 * * 1'  # Каждый понедельник в 6:00
  workflow_dispatch:

jobs:
  update-deps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Update Helm dependencies
        run: |
          # Обновление версий чартов
          helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
          helm repo add grafana https://grafana.github.io/helm-charts
          helm repo update

          # Проверка последних версий
          PROMETHEUS_VERSION=$(helm search repo prometheus-community/kube-prometheus-stack --version '>=88.0.0' -o json | jq -r '.[0].version')
          LOKI_VERSION=$(helm search repo grafana/loki --version '>=18.0.0' -o json | jq -r '.[0].version')
          TEMPO_VERSION=$(helm search repo grafana/tempo --version '>=2.0.0' -o json | jq -r '.[0].version')

          echo "Prometheus: $PROMETHEUS_VERSION"
          echo "Loki: $LOKI_VERSION"
          echo "Tempo: $TEMPO_VERSION"

      - name: Create Pull Request
        uses: peter-evans/create-pull-request@v5
        with:
          title: 'chore: update LGTM dependencies'
          body: |
            Automated update of LGTM stack dependencies:
            - Prometheus: ${{ env.PROMETHEUS_VERSION }}
            - Loki: ${{ env.LOKI_VERSION }}
            - Tempo: ${{ env.TEMPO_VERSION }}
          branch: chore/update-lgtm-deps
```

#### Шаг 2: GitLab CI pipeline для валидации

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy

validate:
  stage: validate
  script:
    # Валидация Helm chart
    - helm lint base/prometheus/
    - helm lint base/loki/
    - helm lint base/tempo/

    # Валидация Kubernetes манифестов
    - kubectl apply --dry-run=client -f network-policies/

    # Проверка безопасности
    - trivy config --severity HIGH,CRITICAL .

deploy-prod:
  stage: deploy
  script:
    - argocd app sync prometheus
    - argocd app sync loki
    - argocd app sync tempo
  only:
    - main
  when: manual
```

---

### Сценарий 5: Мониторинг GitOps статуса

**Цель:** Отслеживание состояния GitOps синхронизации для LGTM стека.

#### Шаг 1: Метрики ArgoCD для Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: argocd-metrics
  namespace: argocd
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-server
  endpoints:
    - port: metrics
```

#### Шаг 2: Алерты на рассинхронизацию

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: gitops-alerts
  namespace: monitoring
spec:
  groups:
    - name: gitops
      rules:
        - alert: ArgoCDAppOutOfSync
          expr: argocd_app_info{sync_status!="Synced"} == 1
          for: 15m
          labels:
            severity: warning
          annotations:
            summary: "ArgoCD приложение рассинхронизировано"
            description: "Приложение {{ $labels.name }} в namespace {{ $labels.namespace }} не синхронизировано более 15 минут"

        - alert: ArgoCDAppDegraded
          expr: argocd_app_info{health_status!="Healthy"} == 1
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "ArgoCD приложение в состоянии Degraded"
            description: "Приложение {{ $labels.name }} в namespace {{ $labels.namespace }} в нездоровом состоянии"
```

---

## Дополнительная информация

### Чек-лист GitOps интеграции

| Компонент | Проверка | Статус |
| :--- | :--- | :--- |
| **Репозиторий** | Структура base/overlays создана | ☐ |
| **ArgoCD/Flux** | Установлен и настроен | ☐ |
| **Applications** | Все компоненты LGTM добавлены | ☐ |
| **NetworkPolicies** | Управляются через GitOps | ☐ |
| **RBAC** | Управляется через GitOps | ☐ |
| **Алерты** | Настроены на рассинхронизацию | ☐ |
| **CI/CD** | Валидация перед деплоем | ☐ |

### Связанные материалы

- **[GitOps: Обзор](../../../GitOps/GitOps_overview.md)** — принципы и практики
- **[ArgoCD: Обзор](../../../GitOps/ArgoCD/argocd_overview.md)** — детали ArgoCD
- **[Flux: Обзор](../../../GitOps/flux.md)** — детали Flux
- **[GitOps: Пайплайн](../../../GitOps/gitops_pipeline_example.md)** — примеры пайплайнов

---

**Навигация по руководству:**

- **[Backup и восстановление](./lgtm_backup_disaster_recovery.md)** (назад)
- **[Оптимизация производительности](./lgtm_performance_tuning.md)** (вперед)
