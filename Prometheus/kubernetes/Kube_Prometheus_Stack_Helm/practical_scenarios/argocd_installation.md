# Argo CD: Установка kube-prometheus-stack через Application

> [Назад к оглавлению](../overview.md)

> **Источник темы:** декларативное развёртывание kube-prometheus-stack через GitOps (Argo CD) с использованием CRD `Application` и `AppProject`.
> **Смежные темы:** [Обзор kube-prometheus-stack](../overview.md) — компоненты, версии, архитектура; [Онлайн-установка](./online_installation.md) — установка через Helm CLI; [Application Exporters через Argo CD](../application_exporters_argocd.md) — паттерн Application для экспортеров в namespace рабочей нагрузки.

## Определения

**Application (Argo CD)** — CRD `argoproj.io/v1alpha1`, управляемый контроллером `argocd-application-controller`. Осуществляет декларативную установку, обновление и откат Helm-чартов на основе состояния из Git, поддерживая drift detection и самовосстановление (self-healing).

**AppProject (Argo CD)** — CRD `argoproj.io/v1alpha1`, определяющий логическую границу безопасности: разрешенные репозитории, целевые кластеры и типы ресурсов. Применяется для изоляции production-окружений.

**Репозиторий (Repository Secret)** — объект `Secret` с меткой `argocd.argoproj.io/secret-type: repository`, регистрирующий внешний Helm- или Git-репозиторий в Argo CD. Для публичных Helm-репозиториев (например, `prometheus-community`) можно использовать `repoURL` напрямую в манифесте `Application` без создания секрета.

**Argo CD** — декларативный GitOps-инструмент непрерывной доставки (CD) для Kubernetes. Автоматизирует развертывание манифестов и синхронизацию состояния кластера с Git-репозиторием, используя pull-модель с централизованной контрольной площадкой и Web UI.

**fullnameOverride** — параметр Helm, который задаёт базовое имя для всех ресурсов чарта. При значении `kube-prom-stack` имена сервисов становятся предсказуемыми: `kube-prom-stack-prometheus`, `kube-prom-stack-grafana`, `kube-prom-stack-alertmanager`.

## Предварительные требования

- **Argo CD v3.5+** установлен и загружен в кластер (namespace `argocd`).
- **AppProject `monitoring`** создан с разрешением на доступ к Helm-репозиторию `prometheus-community`.
- Namespace `monitoring` создаётся автоматически при синхронизации (`CreateNamespace=true`).
- **Sealed Secrets controller** установлен (для безопасного управления паролями Grafana — см. [Сценарий 2](#сценарий-2-управление-секретами-grafana-через-sealed-secrets)).
- **StorageClass** с поддержкой `ReadWriteOnce` доступен для PVC Prometheus и Alertmanager.
- Метод отслеживания ресурсов (Resource Tracking) настроен на аннотации в `argocd-cm` (`application.resourceTrackingMethod: annotation`) для совместимости с Helm-чартами — см. [Argo CD: Интеграция с Helm](../../GitOps/ArgoCD/helm_integration.md).

## Основные концепции

### Архитектура развертывания через Argo CD

```
Git Repository
    │
    ├── Repository Secret: prometheus-community Helm repo  (Argo CD)
    │
    ├── AppProject/monitoring  (Argo CD)
    │
    ├── Application/kube-prom-stack-monitoring  (Argo CD)
    │       │
    │       └── Chart: kube-prometheus-stack 65.x
    │               ├── Prometheus Operator (Deployment)
    │               ├── Prometheus Server (StatefulSet)
    │               ├── Alertmanager (StatefulSet)
    │               ├── Grafana (Deployment)
    │               ├── Node Exporter (DaemonSet)
    │               ├── kube-state-metrics (Deployment)
    │               └── CRDs (ServiceMonitor, PodMonitor, PrometheusRule, ...)
    │
    └── Secret/grafana-admin-secret  (SealedSecret → Secret)
```

**Преимущества GitOps-подхода:**
- Полный drift detection и автоматическая синхронизация через `selfHeal`.
- История изменений в Git с возможностью отката через `argocd app rollback`.
- Согласованность конфигурации между средами (dev/staging/prod).
- Интеграция с Helm Hooks: аннотации `helm.sh/hook` транслируются в фазы синхронизации Argo CD (PreSync/PostSync) и Sync Waves — см. [Argo CD: Интеграция с Helm](../../GitOps/ArgoCD/helm_integration.md).

### Влияние `fullnameOverride` на имена ресурсов

При `fullnameOverride: kube-prom-stack` имена ключевых сервисов становятся предсказуемыми:

| Компонент | Service Name | Port |
|---|---|---|
| Prometheus | `kube-prom-stack-prometheus` | 9090 |
| Alertmanager | `kube-prom-stack-alertmanager` | 9093 |
| Grafana | `kube-prom-stack-grafana` | 80 |
| Alertmanagera (headless) | `kube-prom-stack-alertmanager-headless` | — |

## Практические сценарии

### Сценарий 1: Полный Application для kube-prometheus-stack

**Шаг 1: Создание AppProject (необязательно для single-tenant)**

```yaml
# argocd/projects/monitoring-project.yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: monitoring
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: Проект для инфраструктурного мониторинга (Prometheus, Grafana, AlertManager)
  sourceRepos:
    - https://prometheus-community.github.io/helm-charts   # Разрешённый Helm-репозиторий
  destinations:
    - server: https://kubernetes.default.svc
      namespace: monitoring                                # Разрешённый namespace
  clusterResourceWhitelist:
    - group: "*"
      kind: "*"                                            # Разрешение cluster-scoped ресурсов (CRD)
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"                                            # Разрешение всех ресурсов в namespace
```

**Шаг 2: Регистрация Helm-репозитория (опционально для публичных)**

Для публичных Helm-репозиториев `argocd-repo-server` клонирует индекс автоматически при первом обращении. Для приватных репозиториев создаётся Secret:

```yaml
# argocd/repositories/repo-prometheus-community.yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-prometheus-community
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
type: Opaque
stringData:
  type: helm
  url: https://prometheus-community.github.io/helm-charts
  name: prometheus-community
  enableOci: "false"
```

**Шаг 3: Создание значений (values.yaml)**

```yaml
# argocd/values/monitoring/kube-prom-stack-values.yaml
fullnameOverride: kube-prom-stack

prometheus:
  prometheusSpec:
    retention: 30d
    retentionSize: 40GB
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    ruleSelectorNilUsesHelmValues: false
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          resources:
            requests:
              storage: 50Gi
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2000m
        memory: 4Gi

alertmanager:
  alertmanagerSpec:
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: local-path
          resources:
            requests:
              storage: 5Gi

grafana:
  adminPassword: ""
  persistence:
    enabled: true
    storageClassName: local-path
    size: 10Gi
  grafana.ini:
    server:
      root_url: https://grafana.example.com
  sidecar:
    dashboards:
      enabled: true
      searchNamespace: ALL

nodeExporter:
  enabled: true

kubeStateMetrics:
  enabled: true
```

**Шаг 4: Манифест Application в namespace `argocd`**

```yaml
# argocd/applications/kube-prom-stack-application.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-prom-stack-monitoring
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: monitoring

  source:
    repoURL: https://prometheus-community.github.io/helm-charts
    chart: kube-prometheus-stack
    targetRevision: "65.x"                       # Фиксированная версия чарта
    helm:
      releaseName: kube-prom-stack
      valueFiles:
        - $values/values/monitoring/kube-prom-stack-values.yaml        # values из Git
      values: |
        prometheus:
          prometheusSpec:
            serviceMonitorSelectorNilUsesHelmValues: false

  destination:
    server: https://kubernetes.default.svc
    namespace: monitoring

  syncPolicy:
    automated:
      prune: true                                  # Удалять ресурсы, удалённые из Git
      selfHeal: true                               # Откат ручных правок в кластере
      allowEmpty: false                            # Защита от удаления всего при пустом репо
    syncOptions:
      - CreateNamespace=true                       # Автоматически создать namespace monitoring
      - ServerSideApply=true                     # SSA для управления владением полями
      - ApplyOutOfSyncOnly=true                    # Применять только изменённые объекты
      - SkipDryRunOnMissingResource=true           # Пропустить dry-run валидацию CRD
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
```

> **Важно:** `serviceMonitorSelectorNilUsesHelmValues: false` — критично. Без этого Prometheus отслеживает только ServiceMonitor/PodMonitor/PrometheusRule в собственном неймспейсе. При `false` Operator использует пустой селектор, который выбирает все ресурсы по всему кластеру (в рамках `namespaceSelector`).

**Шаг 5: Применение через Argo CD**

```bash
# 1. Синхронизация изменений
argocd app sync kube-prom-stack-monitoring --refresh --prune
# → TIMESTAMP                  GROUP  KIND        NAMESPACE   NAME                           STATUS   HEALTH   HOOK  MESSAGE
# → 2026-10-15T17:30:00+03:00   apps   Deployment  monitoring  kube-prom-stack-grafana        Synced   Healthy        deployment.apps/kube-prom-stack-grafana configured

# 2. Проверка статуса
argocd app get kube-prom-stack-monitoring
# → Name:               kube-prom-stack-monitoring
# → Server:             https://kubernetes.default.svc
# → Namespace:          monitoring
# → URL:                https://argocd.internal.infra/applications/kube-prom-stack-monitoring
# → Repo:               https://prometheus-community.github.io/helm-charts
# → Target:             65.x
# → Path:               -
# → Sync Window:        Sync Allowed
# → Sync Status:        Synced to 65.x (...)
# → Health Status:      Healthy
```

### Сценарий 2: Управление секретами Grafana через Sealed Secrets

Пароль администратора Grafana не должен храниться в Git в открытом виде. Используйте Sealed Secrets с офлайн-шифрованием через `kubeseal --cert`.

**Шаг 1: Получение сертификата контроллера**

```bash
kubeseal --fetch-cert \
  --controller-name=sealed-secrets \
  --controller-namespace=kube-system \
  --cert pub-cert.pem
```

**Шаг 2: Создание и шифрование Secret**

```bash
# 1. Создание временного Secret
kubectl create secret generic grafana-admin-secret \
  --from-literal=admin-user="admin" \
  --from-literal=admin-password="$(openssl rand -base64 24)" \
  --dry-run=client -o yaml \
  | kubeseal --cert pub-cert.pem -o yaml \
  > argocd/values/monitoring/grafana-admin-secret.yaml
```

**Шаг 3: Связь с Application через `existingSecret`**

```yaml
# В values.yaml для kube-prometheus-stack
grafana:
  admin:
    existingSecret: grafana-admin-secret
    userKey: admin-user
    passwordKey: admin-password
```

> **Почему `existingSecret`:** При использовании Sealed Secrets контроллер автоматически расшифровывает `SealedSecret` в обычный `Secret` в кластере. Helm-чарт ссылается на уже существующий Secret через `existingSecret`, что разделяет управление секретами от жизненного цикла чарта.

### Сценарий 3: ServiceMonitor для приложения

Чтобы Prometheus начал скрейпить приложение, ServiceMonitor должен содержать метку `release: kube-prom-stack`, соответствующую селектору `serviceMonitorSelector` в ресурсе `Prometheus`:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-service
  namespace: app
  labels:
    release: kube-prom-stack    # обязательна для discovery
spec:
  selector:
    matchLabels:
      app: my-service
  namespaceSelector:
    matchNames:
      - app
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```

> **См. также:** [ServiceMonitor CRD](../../operator/crd/servicemonitor.md) — справочник параметров и best practices.

### Сценарий 4: Валидация работоспособности

```bash
# 1. Проверка статуса подов (все Running)
kubectl get pods -n monitoring -l app.kubernetes.io/instance=kube-prom-stack
# → kube-prom-stack-kube-prom-stack-prometheus-0    Running
# → kube-prom-stack-kube-state-metrics-...          Running
# → kube-prom-stack-grafana-...                     Running

# 2. Prometheus UI — проверка targets
kubectl port-forward -n monitoring svc/kube-prom-stack-prometheus 9090:9090
# http://localhost:9090/targets — все должны быть UP

# 3. Alertmanager UI
kubectl port-forward -n monitoring svc/kube-prom-stack-alertmanager 9093:9093
# http://localhost:9093/#/status

# 4. Grafana UI
kubectl port-forward -n monitoring svc/kube-prom-stack-grafana 3000:80
# http://localhost:3000 — логин: admin, пароль из Secret
```

## Диагностика и устранение неполадок

| Проблема | Вероятная причина | Решение |
|---|---|---|
| Application `Health: Degraded` | Ошибка валидации values или недоступность репозитория | `argocd app diff kube-prom-stack-monitoring` и `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server` |
| ServiceMonitor не появляется в Prometheus | Отсутствует метка `release: kube-prom-stack` | Добавьте `additionalLabels.release: kube-prom-stack` в values |
| Target в статусе DOWN | Несоответствие селекторов или labels | Проверьте `kubectl get svc <name> --show-labels` |
| Grafana 404/502 (Ingress) | Ошибка в `root_url` или путях | Проверьте `grafana.grafana.ini.server.root_url` и Ingress `pathType` |
| Prometheus OOMKilled | Недостаточно памяти | Увеличьте `resources.limits.memory` |
| PVC в статусе Pending | StorageClass не найден или нет свободных PV | Проверьте `kubectl get sc` и квоты |
| Secret не расшифровывается | kubeseal несовместим или сертификат истёк | `kubeseal --fetch-cert` и пересоздайте |
| `field is immutable` при синке | Конфликт метки `app.kubernetes.io/instance` между именем Application и `releaseName` | Переключить `application.resourceTrackingMethod: annotation` в `argocd-cm` |
| `metadata.annotations: Too long (>256KB)` | Манифест превышает лимит аннотации `last-applied-configuration` | Включить `ServerSideApply=true` в syncOptions |

## Лучшие практики

1. **Фиксация версии чарта:** Всегда указывайте точную версию (`version: "65.5.0"`), а не `latest` или диапазон.
2. **Drift detection:** Argo CD автоматически обнаруживает drift. Не вмешивайтесь в ресурсы вручную (`kubectl edit`) — исправляйте через Git и `argocd app sync`.
3. **Секреты в Git:** Используйте Sealed Secrets или External Secrets Operator. Никогда не коммитьте чувствительные данные в открытом виде.
4. **CreateNamespace:** Используйте `CreateNamespace=true` в `syncOptions` для автоматического создания namespace.
5. **Ресурсные лимиты:** Всегда задавайте `resources.requests` и `resources.limits` для всех компонентов.
6. **Retention и PVC:** Настраивайте `retentionSize` на 10–15% меньше размера PVC (см. [Persistent Volumes](./persistent_volumes.md)).
7. **Validation:** Всегда проверяйте через `helm template` + `--dry-run=client` перед коммитом в Git. Используйте `argocd app manifest <app>` для проверки рендеринга в контексте Argo CD.
8. **Resource Tracking:** Используйте аннотации для отслеживания (`application.resourceTrackingMethod: annotation`), чтобы избежать конфликтов с метками Helm-чартов.
9. **skipCrds:** Оставьте `skipCrds: false` (по умолчанию) для корректной установки CRD prometheus-operator. Используйте `SkipDryRunOnMissingResource=true`, если CRD создаются в той же синхронизации, что и их экземпляры.

## Связанные темы

- [Обзор kube-prometheus-stack](../overview.md) — архитектура, версии, селекторы.
- [Онлайн-установка через Helm CLI](./online_installation.md) — альтернатива без GitOps.
- [Конфигурация компонентов](../other_components_config.md) — RBAC, config-reload, default rules.
- [Application Exporters через Argo CD](../application_exporters_argocd.md) — паттерн Application для экспортеров в namespace рабочей нагрузки.
- [Веб-аутентификация и секреты](../practical_scenarios/web_authentication.md) — `existingSecret`, OAuth2-proxy, mTLS.

---

> **Примечание:** Сценарий был конвертирован из Flux CD в Argo CD. Основное соответствие концепций:
> - Flux `HelmRepository` → Argo CD `repoURL` в `Application` (или `Secret` с меткой `repository`)
> - Flux `HelmRelease` → Argo CD `Application` с `helm` source
> - Flux `flux reconcile hr` → `argocd app sync <app>`
> - Flux `flux get helmrelease` → `argocd app get <app>`
> - Flux `prune: true` → Argo CD `prune: true` в `syncPolicy.automated`
> - Flux `remediation` → Argo CD `retry` с экспоненциальным backoff