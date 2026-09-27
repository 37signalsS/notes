# OpenTelemetry: GitOps для Collector

## Определения

**GitOps для OpenTelemetry Collector** — это практика управления конфигурацией и развёртыванием Collector с использованием Git как единственного источника истины (Single Source of Truth). Основные инструменты: ArgoCD, Flux, Kustomize, Helm.

В 2026 году GitOps является стандартом для управления инфраструктурой в Kubernetes, включая компоненты наблюдаемости.

## Теоретический блок

### Архитектура GitOps

```text
Git Repository (конфигурация Collector)
        ↓
ArgoCD/Flux (контроллер)
        ↓
Kubernetes (развёртывание Collector)
        ↓
OTel Operator (управление Collector)
```

### Преимущества GitOps

- **Версионирование** — все изменения хранятся в Git.
- **Аудит** — история изменений доступна в Git.
- **Воспроизводимость** — можно развернуть точно такую же конфигурацию.
- **Автоматизация** — автоматическое применение изменений.

### Компоненты

1. **Git Repository** — хранит манифесты Kubernetes и конфигурацию Collector.
2. **ArgoCD/Flux** — контроллер, следящий за изменениями в Git и применяющий их.
3. **OTel Operator** — управляет развёртыванием и конфигурацией Collector.
4. **Kustomize/Helm** — инструменты шаблонизации манифестов.

## Практические сценарии

### Сценарий 1: ArgoCD + OTel Operator

**Шаг 1: Установка OTel Operator через Helm**

```bash
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm install opentelemetry-operator open-telemetry/opentelemetry-operator \
  --namespace opentelemetry-operator \
  --create-namespace
```

**Шаг 2: Создание Application в ArgoCD**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/your-org/otel-configs.git'
    targetRevision: HEAD
    path: collector/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: opentelemetry
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**Шаг 3: Конфигурация Collector в Git**

```yaml
# collector/overlays/production/otelcollector.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  mode: deployment
  replicas: 3
  config:
    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
    processors:
      memory_limiter:
        check_interval: 1s
        limit_mib: 512
      batch:
        timeout: 10s
    exporters:
      otlp/tempo:
        endpoint: "tempo:4317"
      prometheus:
        endpoint: "0.0.0.0:8889"
    service:
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [otlp/tempo]
        metrics:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [prometheus]
```

**Валидация:**

```bash
# Проверка статуса ArgoCD
argocd app get otel-collector

# Проверка Collector в Kubernetes
kubectl get opentelemetrycollector -n opentelemetry
```

### Сценарий 2: Flux + Helm

**Шаг 1: Добавление Helm-чарта в Flux**

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: open-telemetry
  namespace: flux-system
spec:
  interval: 1h
  url: https://open-telemetry.github.io/opentelemetry-helm-charts
```

**Шаг 2: Создание HelmRelease**

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: opentelemetry-operator
  namespace: flux-system
spec:
  interval: 1h
  chart:
    spec:
      chart: opentelemetry-operator
      version: "0.x.x"
      sourceRef:
        kind: HelmRepository
        name: open-telemetry
  values:
    operator:
      replicas: 1
    collector:
      image:
        repository: otel/opentelemetry-collector-contrib
        tag: "0.96.0"
```

### Сценарий 3: Kustomize для управления конфигурацией

**Базовая конфигурация:**

```yaml
# collector/base/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - otelcollector.yaml
  - service.yaml
  - serviceaccount.yaml
  - clusterrole.yaml
  - clusterrolebinding.yaml
```

**Overlays для окружений:**

```yaml
# collector/overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
bases:
  - ../../base
patchesStrategicMerge:
  - otelcollector-patch.yaml
```

**Patch для production:**

```yaml
# collector/overlays/production/otelcollector-patch.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
spec:
  replicas: 3
  config:
    processors:
      memory_limiter:
        limit_mib: 1024
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **ArgoCD не синхронизирует** | Ошибка в манифестах | Проверить `argocd app diff otel-collector` |
| **Operator не создает Collector** | Ошибка в CRD | Проверить логи Operator |
| **Конфигурация не применяется** | Kustomize паттерн не найден | Проверить `kustomize build collector/overlays/production` |
| **Helm-чарт не обновляется** | Проблемы с доступом к репозиторию | Проверить `helm repo update` |

### Best Practices

1. **Храните конфигурацию в Git** — это единственная истина.
2. **Используйте overlays** — разделяйте конфигурацию для разных окружений.
3. **Автоматизируйте проверку** — настройте CI для проверки манифестов.
4. **Мониторьте изменения** — настройте алерты на изменения конфигурации.
5. **Документируйте процессы** — опишите процедуру обновления Collector.

### Ссылки

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [Flux Documentation](https://fluxcd.io/docs/)
- [OTel Operator Helm Chart](https://github.com/open-telemetry/opentelemetry-helm-charts)
- [Kustomize Documentation](https://kustomize.io/)
