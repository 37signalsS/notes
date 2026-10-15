# Crossplane: Observability (метрики, алерты, трассировка, логи)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Observability в Crossplane** — комплекс механизмов телеметрии (Prometheus-метрики, распределенные трассировки, структурированные логи и Kubernetes Events), обеспечивающих непрерывный контроль состояния управляющего контура (Control Plane) и целевых инфраструктурных ресурсов.

**Core-метрики** — внутренние метрики контроллеров ядра Crossplane (`crossplane` и `crossplane-rbac-manager`), отражающие состояние подсистемы композиций, планировщика пакетов, менеджера прав RBAC и очередей контроллеров. Экспортируются по протоколу HTTP на порту `8080` (`/metrics`).

**Provider-метрики** — метрики жизненного цикла управляемых ресурсов (`Managed Resources`, MR), экспортируемые подами провайдеров на базе библиотеки `crossplane-runtime`. Включают показатели присутствия, готовности, синхронизации и дрейфа ресурсов.

**Controller-Runtime Metrics** — низкоуровневые системные метрики очередей и рабочих потоков Go-контроллеров (`workqueue_*`, `controller_runtime_*`), позволяющие SRE оценивать задержки выполнения задач (reconciliation latency), насыщение очередей и частоту повторных попыток (retries).

**Условия Ready и Synced** — базовые Kubernetes Conditions в статусе каждого MR и композитного ресурса (`XR`):
- `Synced=True` — целевое состояние манифеста успешно применено контроллером к целевой инфраструктуре (локальному кластеру, СУБД, сетевому устройству или операционной системе).
- `Ready=True` — управляемый ресурс завершил инициализацию, прошел проверки работоспособности (health checks) и готов к приему рабочей нагрузки. Ресурс может находиться в состоянии `Ready=True`, но иметь `Synced=False` при возникновении дрейфа или сетевого сбоя на этапе сверки.

**Configuration Drift (дрейф конфигурации)** — расхождение между декларированным в Kubernetes-манифесте состоянием ресурса и его фактическим состоянием в целевой системе. Фиксируется метрикой `crossplane_managed_resource_drift_seconds`.

**CLI Trace** — встроенный механизм визуализации иерархии реконсиляции Crossplane (`crossplane beta trace`), строящий направленный граф от пользовательского запроса (`Claim`/`XRC`) через композитный ресурс (`XR`) до низкоуровневых объектов (`MR`) с выводом их текущих условий и причин блокировок.

**OpenTelemetry (OTLP) Tracing** — экспорт распределенных спанов трассировки из контроллеров Crossplane и Composition Functions в централизованный коллектор для профилирования задержек в конвейере реконсиляции.

---

## Базовые концепции и архитектура

### Архитектура Observability в Crossplane

Управляющий контур Crossplane развертывается в Kubernetes и состоит из нескольких слабосвязанных компонентов, каждый из которых генерирует телеметрию:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Control Plane                        │
│                                                                        │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │    Crossplane Core     │              │     Provider Pods        │  │
│  │ (crossplane, rbac-mgr) │              │(kubernetes, helm, sql..) │  │
│  │   HTTP :8080 /metrics  │              │   HTTP :8080 /metrics    │  │
│  └───────────┬────────────┘              └────────────┬─────────────┘  │
│              │                                        │                │
│              │ (PodMonitor / ServiceMonitor)          │                │
│              ▼                                        ▼                │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │            Prometheus / VictoriaMetrics (Scrape Loop)            │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │ PromQL / Alert Rules             │
│                                     ▼                                  │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │   Alertmanager Alerts  │              │    Grafana Dashboards    │  │
│  └────────────────────────┘              └──────────────────────────┘  │
│                                                                        │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │ Structured Logs (Zap)  │ ───────────► │ Vector / Loki / Fluentd  │  │
│  │ stdout (JSON, --debug) │              │                          │  │
│  └────────────────────────┘              └──────────────────────────┘  │
│                                                                        │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │ Kubernetes Events API  │ ───────────► │ EventRouter / Exporter   │  │
│  │ (Normal / Warning)     │              │                          │  │
│  └────────────────────────┘              └──────────────────────────┘  │
│                                                                        │
│  ┌────────────────────────┐              ┌──────────────────────────┐  │
│  │ OTLP Spans (gRPC/HTTP) │ ───────────► │ OpenTelemetry Collector  │  │
│  │ Functions Pipeline     │              │ (Jaeger / Tempo)         │  │
│  └────────────────────────┘              └──────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### Модель метрик: Core vs Provider Metrics

1. **Метрики ядра (Core):**
   - Управление пакетами: `crossplane_package_installed`, `crossplane_package_healthy`.
   - Регистрация композиций: время парсинга `Composition` и выполнения пайплайна функций.
   - RBAC-менеджер: количество сгенерированных ролей и привязок (`ClusterRoleBinding`).
2. **Метрики провайдеров (`crossplane-runtime`):**
   - `crossplane_managed_resource_exists` — общее число управляемых ресурсов по видам (`group`, `version`, `kind`, `provider`).
   - `crossplane_managed_resource_ready` — количество ресурсов в состоянии `Ready=True`.
   - `crossplane_managed_resource_synced` — количество ресурсов в состоянии `Synced=True`.
   - `crossplane_managed_resource_drift_seconds` — время с момента обнаружения расхождения до его устранения.
   - `crossplane_managed_resource_first_time_to_readiness_seconds` — гистограмма времени от создания ресурса до первого перехода в `Ready=True`.
   - `crossplane_managed_resource_deletion_seconds` — гистограмма длительности финализации и удаления ресурсов.
3. **Метрики очередей `controller-runtime`:**
   - `workqueue_depth` — текущее количество задач в очереди реконсиляции. Рост очереди сигнализирует о нехватке воркеров или блокировках внешнего API.
   - `workqueue_queue_duration_seconds` — время ожидания элемента в очереди перед обработкой.
   - `workqueue_work_duration_seconds` — время, затраченное воркером на одну итерацию `Reconcile()`.
   - `controller_runtime_reconcile_total` — общее число вызовов сверки с разделением по статусам (`result="success"`, `result="error"`, `result="requeue"`).
   - `controller_runtime_reconcile_errors_total` — счетчик ошибок реконсиляции.

### Статусные условия и модель дрейфа (Synced и Ready)

Жизненный цикл любого инфраструктурного ресурса в Crossplane выражается матрицей состояний:

| Состояние `Synced` | Состояние `Ready` | Интерпретация для SRE | Действие системы |
|---|---|---|---|
| `True` | `True` | **Штатное состояние.** Ресурс актуален и полностью функционален. | Плановый периодический опрос (`--poll`). |
| `True` | `False` | **Инициализация.** Манифест применен, инфраструктура создается/прогревается. | Ожидание перехода в готовность либо таймаут. |
| `False` | `True` | **Дрейф или ошибка связи.** Ресурс работает, но параметры рассинхронизированы или целевой endpoint временно недоступен. | Немедленный повторный запуск цикла сверки. |
| `False` | `False` | **Авария / Ошибка провижининга.** Ресурс не создан или отклонен целевой системой. | Exponential backoff повторов, генерация события `Warning`. |

### Трассировка вызовов и дерево композиции

При использовании Composition Functions (в архитектуре Crossplane v1.14+ и v2.x) запрос проходит через многоуровневый конвейер:
1. Пользователь создает `Claim` (например, `PostgreSQLInstance`).
2. Composite Resource Controller трансформирует Claim в `XR` (`XPostgreSQLInstance`).
3. Crossplane вызывает цепочку `Function` через gRPC (на базе Protobuf / Unix-сокеты или mTLS).
4. Каждая функция возвращает желаемое состояние дочерних `MR` (например, `Release` для Helm-провайдера и `Database` для SQL-провайдера).
5. Провайдеры применяют изменения и возвращают условия `Ready`/`Synced`.

Визуализировать этот путь в терминале позволяет утилита `crossplane beta trace`. Для глубокого профилирования задержек контроллеры передают контекст W3C Trace Context в OpenTelemetry Collector.

### Структурированное логирование и Kubernetes Events

- **Логи:** Все компоненты используют Go-библиотеку `zap`. При включении флага `--debug` вывод содержит полный контекст реконсиляции (имя контроллера, namespace/name объекта, UID, diff полей и сырые ответы внутренних систем). Логи выводятся в stdout в формате JSON (`--logging-format=json`).
- **События (Events):** При каждом значимом действии контроллеры Crossplane создают объект `Event`:
  - `Normal`: `CreatedExternalResource`, `UpdatedExternalResource`, `ReconcileSuccess`.
  - `Warning`: `CannotResolveReferences`, `CannotCompose`, `CannotConnectToProvider`, `CannotUpdateExternalResource`, `ReconcileError`.

---

## Практические сценарии и конфигурация

### 1. Настройка экспорта метрик через Helm (Crossplane Core)

При развертывании Crossplane через официальный Helm-чарт включите экспорт метрик и создайте системный Service:

```yaml
# values-crossplane-monitoring.yaml
metrics:
  enabled: true

rbacManager:
  metrics:
    enabled: true

# Дополнительные флаги для контроллера ядра
extraArgs:
  - --debug
  - --max-reconcile-rate=100

resourcesCrossplane:
  limits:
    cpu: 1000m
    memory: 1Gi
  requests:
    cpu: 200m
    memory: 256Mi

serviceMonitor:
  enabled: false # Для гибкого управления используем отдельный PodMonitor
```

Применение параметров:
```bash
helm upgrade --install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace \
  -f values-crossplane-monitoring.yaml
# → Release "crossplane" has been upgraded. Happy Helming!
```

### 2. Сбор метрик через ServiceMonitor и PodMonitor (Prometheus Operator)

Для надежного сбора метрик со всех подов Crossplane (Core, RBAC Manager, динамические поды Providers и Functions) рекомендуется использовать `PodMonitor` из состава [Prometheus Operator](../../Prometheus/kubernetes/operator/crd/podmonitor.md):

```yaml
# crossplane-podmonitors.yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: crossplane-core-monitor
  namespace: crossplane-system
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app: crossplane
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      interval: 15s
      scrapeTimeout: 10s
---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: crossplane-providers-monitor
  namespace: crossplane-system
  labels:
    release: prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: crossplane-provider
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      interval: 30s
      scrapeTimeout: 15s
```

Применение манифеста:
```bash
kubectl apply -f crossplane-podmonitors.yaml
# → podmonitor.monitoring.coreos.com/crossplane-core-monitor created
# → podmonitor.monitoring.coreos.com/crossplane-providers-monitor created
```

### 3. Тюнинг провайдеров и функций через DeploymentRuntimeConfig

В Crossplane v1.14+ и v2.x управление подами провайдеров осуществляется через ресурс `DeploymentRuntimeConfig`. С его помощью провайдеру назначаются метки для скрейпинга, порт метрик, лимиты ресурсов и параметры отладки:

```yaml
# provider-runtime-config.yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: default-provider-config
  namespace: crossplane-system
spec:
  deploymentTemplate:
    spec:
      selector: {}
      template:
        metadata:
          labels:
            app.kubernetes.io/component: crossplane-provider
          annotations:
            prometheus.io/scrape: "true"
            prometheus.io/port: "8080"
            prometheus.io/path: "/metrics"
        spec:
          containers:
            - name: package-runtime
              args:
                - --debug
                - --poll=60s
                - --max-reconcile-rate=50
              ports:
                - name: metrics
                  containerPort: 8080
                  protocol: TCP
              resources:
                limits:
                  cpu: 500m
                  memory: 512Mi
                requests:
                  cpu: 100m
                  memory: 128Mi
```

Привязка конфигурации к провайдеру (например, `provider-kubernetes`):

```yaml
# provider-kubernetes.yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.15.0
  runtimeConfigRef:
    name: default-provider-config
```

### 4. Экспорт распределенных трассировок через OpenTelemetry (OTLP)

Для трассировки вызовов контроллеров Crossplane передайте стандартные переменные окружения OpenTelemetry Go SDK через `DeploymentRuntimeConfig` или Helm `env`:

```yaml
# otel-tracing-runtime-config.yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: tracing-runtime-config
  namespace: crossplane-system
spec:
  deploymentTemplate:
    spec:
      selector: {}
      template:
        spec:
          containers:
            - name: package-runtime
              env:
                - name: OTEL_EXPORTER_OTLP_ENDPOINT
                  value: "http://otel-collector.monitoring.svc.cluster.local:4317"
                - name: OTEL_EXPORTER_OTLP_INSECURE
                  value: "true"
                - name: OTEL_SERVICE_NAME
                  value: "crossplane-provider"
                - name: OTEL_TRACES_SAMPLER
                  value: "parentbased_traceidratio"
                - name: OTEL_TRACES_SAMPLER_ARG
                  value: "0.1" # 10% семплирование в продакшене
```

### 5. Сбор и агрегация структурированных JSON-логов (Vector / Loki)

Контроллеры Crossplane генерируют структурированные логи `zap`. Для парсинга в агентах сбора логов (Vector, Fluent Bit) настройте извлечение ключевых полей:

Пример конфигурации источника и парсера в `Vector` (on-prem):

```toml
[sources.kubernetes_crossplane_logs]
type = "kubernetes_logs"
include_namespaces = ["crossplane-system"]

[transforms.parse_crossplane_json]
type = "remap"
inputs = ["kubernetes_crossplane_logs"]
source = '''
.parsed, err = parse_json(.message)
if err == null {
  .level = .parsed.level
  .controller = .parsed.controller
  .reconcile_object = .parsed.request
  .error_msg = .parsed.error
  .timestamp = .parsed.ts
}
'''

[sinks.loki_cluster]
type = "loki"
inputs = ["parse_crossplane_json"]
endpoint = "http://loki.monitoring.svc.cluster.local:3100"
encoding.codec = "json"
labels.namespace = "{{ kubernetes.pod_namespace }}"
labels.component = "{{ kubernetes.pod_labels.\"app.kubernetes.io/component\" }}"
labels.level = "{{ level }}"
```

### 6. Расчет SRE-метрик, SLI/SLO и мониторинг в PromQL

#### SRE Индикаторы качества обслуживания (SLI/SLO)

1. **SLI Доступности инфраструктуры (Managed Resources Readiness):**
   Доля существующих ресурсов в состоянии `Ready=True`:
   ```promql
   sum(crossplane_managed_resource_ready == 1) / sum(crossplane_managed_resource_exists)
   ```
   *Целевой показатель (SLO):* $\ge 99.5\%$ за скользящее окно 30 дней.

2. **SLI Успешности реконсиляции (Reconciliation Success Rate):**
   Доля итераций реконсиляции без ошибок:
   ```promql
   sum(rate(controller_runtime_reconcile_total{result="success"}[5m]))
   /
   sum(rate(controller_runtime_reconcile_total[5m]))
   ```
   *Целевой показатель (SLO):* $\ge 99.9\%$.

3. **SLI Задержки реконсиляции (P99 Reconcile Latency):**
   99-й перцентиль времени выполнения цикла сверки:
   ```promql
   histogram_quantile(0.99, sum(rate(controller_runtime_reconcile_time_seconds_bucket[5m])) by (le, controller))
   ```
   *Целевой показатель (SLO):* $< 3.0$ сек для локальных контроллеров.

#### Ключевые аналитические запросы PromQL

- **Количество несинхронизированных ресурсов по типам:**
  ```promql
  sum by (group, version, kind) (crossplane_managed_resource_exists - crossplane_managed_resource_synced)
  ```
- **Ресурсы с непрекращающимся дрейфом (> 15 минут):**
  ```promql
  crossplane_managed_resource_drift_seconds > 900
  ```
- **Длина очереди задач контроллеров (Saturation):**
  ```promql
  sum by (name) (workqueue_depth)
  ```
- **Частота повторных попыток (Retries Rate):**
  ```promql
  sum by (name) (rate(workqueue_retries_total[5m]))
  ```

### 7. Настройка правил алертинга (PrometheusRule / Alertmanager)

Манифест `PrometheusRule` для развертывания через [PrometheusRule CRD](../../Prometheus/kubernetes/operator/crd/prometheusrule.md):

```yaml
# crossplane-alert-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: crossplane-sre-rules
  namespace: crossplane-system
  labels:
    role: alert-rules
    release: prometheus-stack
spec:
  groups:
    - name: crossplane.control-plane
      rules:
        - alert: CrossplaneWorkqueueBacklog
          expr: workqueue_depth > 50
          for: 10m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: "Высокая глубина очереди Crossplane: {{ $labels.name }}"
            description: "Очередь {{ $labels.name }} содержит {{ $value }} элементов более 10 минут. Возможна перегрузка воркеров."

        - alert: CrossplaneReconcileHighErrorRate
          expr: |
            (
              sum by (controller) (rate(controller_runtime_reconcile_errors_total[5m]))
              /
              sum by (controller) (rate(controller_runtime_reconcile_total[5m]))
            ) > 0.05
          for: 5m
          labels:
            severity: critical
            team: platform-sre
          annotations:
            summary: "Высокий уровень ошибок контроллера {{ $labels.controller }}"
            description: "Доля ошибок реконсиляции контроллера {{ $labels.controller }} превышает 5% за последние 5 минут."

        - alert: CrossplanePackageUnhealthy
          expr: crossplane_package_healthy == 0
          for: 10m
          labels:
            severity: critical
            team: platform-sre
          annotations:
            summary: "Пакет Crossplane нездоров: {{ $labels.package }}"
            description: "Пакет {{ $labels.package }} находится в нездоровом состоянии более 10 минут."

    - name: crossplane.managed-resources
      rules:
        - alert: CrossplaneMRStuckNotReady
          expr: (crossplane_managed_resource_exists - crossplane_managed_resource_ready) > 0
          for: 30m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: "Обнаружены неготовые Managed Resources: {{ $labels.kind }}"
            description: "Один или несколько ресурсов вида {{ $labels.kind }} находятся в Ready=False более 30 минут."

        - alert: CrossplaneConfigurationDrift
          expr: crossplane_managed_resource_drift_seconds > 600
          for: 15m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: "Зафиксирован дрейф конфигурации: {{ $labels.kind }}"
            description: "Ресурс {{ $labels.kind }} рассинхронизирован с целевым состоянием более 15 минут."
```

### 8. Визуализация в Grafana (Community и SRE Dashboards)

1. **Официальный дашборд сообщества:**
   - **ID Дашборда:** `24549` (Crossplane Metrics).
   - Импортируется через интерфейс Grafana (`Dashboards` → `New` → `Import` → ID `24549`).
   - Отображает общие агрегаты по Managed Resources, Provider Health и Composition Function Execution Time.
2. **Рекомендуемая сетка панелей для SRE-дашборда:**
   - **Row 1: High-Level Health & SLI**
     - Gauge: *Infrastructure Readiness SLI* (`sum(crossplane_managed_resource_ready)/sum(crossplane_managed_resource_exists)`).
     - Gauge: *Reconcile Success Rate* (`1 - (errors/total)`).
     - Stat: *Active Drifting Resources* (`count(crossplane_managed_resource_drift_seconds > 0)`).
   - **Row 2: Controller Engine Saturation**
     - Time Series: *Workqueue Depth by Controller* (`workqueue_depth`).
     - Time Series: *Queue Wait Latency P95/P99* (`workqueue_queue_duration_seconds`).
     - Time Series: *Reconcile Duration Heatmap / P99* (`controller_runtime_reconcile_time_seconds`).
   - **Row 3: Resource Inventory & Drift**
     - Table: *Resources by Group/Kind with Synced/Ready counts*.
     - Time Series: *Drift Duration by Resource*.
   - **Row 4: Package Manager & Runtime**
     - Table: *Installed Providers and Functions Status* (`crossplane_package_healthy`).
     - Time Series: *CPU & Memory Usage per Provider Pod*.

---

## Операции и команды

Все команды приводятся с примерами их вызова и ожидаемого результата в терминале.

### 1. Проверка локального эндпоинта метрик

Проброс порта к основному контроллеру ядра Crossplane:
```bash
kubectl -n crossplane-system port-forward deployment/crossplane 8080:8080
# → Forwarding from 127.0.0.1:8080 -> 8080
# → Forwarding from [::1]:8080 -> 8080
```

Проверка отдачи метрик через HTTP:
```bash
curl -s http://localhost:8080/metrics | grep -E "^crossplane_managed_resource" | head -n 5
# → crossplane_managed_resource_exists{group="helm.crossplane.io",kind="Release",provider="provider-helm",version="v1beta1"} 12
# → crossplane_managed_resource_ready{group="helm.crossplane.io",kind="Release",provider="provider-helm",version="v1beta1"} 12
# → crossplane_managed_resource_synced{group="helm.crossplane.io",kind="Release",provider="provider-helm",version="v1beta1"} 12
# → crossplane_managed_resource_drift_seconds{group="helm.crossplane.io",kind="Release",provider="provider-helm",version="v1beta1"} 0
# → crossplane_managed_resource_first_time_to_readiness_seconds_count{group="helm.crossplane.io",kind="Release",provider="provider-helm",version="v1beta1"} 12
```

### 2. Визуализация дерева композиции (CLI Trace)

Для инспекции состояния Claim, XR и дочерних MR используется команда `crossplane beta trace` (в устаревших версиях v1.11–v1.13 — `crossplane alpha trace`):

```bash
crossplane beta trace cluster PostgreSQLInstance dev-database -n app-team-alpha
# → NAME                                                  SYNCED   READY   STATUS
# → PostgreSQLInstance/dev-database (Claim)               True     True    Available
# → └─ XPostgreSQLInstance/dev-database-5k8ql (XR)        True     True    Available
# →    ├─ Release/dev-database-pg-helm (MR)               True     True    Applied
# →    └─ Object/dev-database-pg-config (MR)              True     True    Available
```

Пример вывода при наличии ошибки синхронизации дочернего ресурса:
```bash
crossplane beta trace cluster PostgreSQLInstance failed-db -n app-team-alpha
# → NAME                                                  SYNCED   READY   STATUS
# → PostgreSQLInstance/failed-db (Claim)                  False    False   Waiting: Composite resource is not ready
# → └─ XPostgreSQLInstance/failed-db-w92x1 (XR)           False    False   Waiting: 1 of 2 resources are not ready
# →    ├─ Release/failed-db-pg-helm (MR)                  False    False   CannotConnectToTargetCluster: dial tcp 10.96.0.1:443: connect: connection refused
# →    └─ Object/failed-db-pg-config (MR)                 True     True    Available
```

Для непрерывного наблюдения за деревом композиции в режиме реального времени (полезно во время инцидентов и отладки reconcile) используйте флаг `--watch`: команда перерисовывает граф при каждом обновлении условий (Synced/Ready) и не завершается сама. Это удобнее, чем повторять `crossplane beta trace` вручную после каждой итерации.

```bash
crossplane beta trace cluster PostgreSQLInstance failed-db -n app-team-alpha --watch
# → (граф перерисовывается при каждом изменении conditions; для выхода — Ctrl+C)
```

### 3. Диагностика событий через Kubernetes Events API

Фильтрация Warning-событий, связанных с объектами Crossplane:
```bash
kubectl get events -A --field-selector type=Warning | grep -E "crossplane|Cannot|Reconcile" | head -n 5
# → crossplane-system   12m   Warning   CannotConnectToProvider   managedresource/internal-dns-record   dial tcp 192.168.10.50:53: i/o timeout
# → crossplane-system   4m    Warning   CannotCompose             composite/cluster-infra-8hj2          pipeline step "patch-and-transform" failed: function returned fatal error
```

Детальный просмотр событий конкретного управляемого ресурса:
```bash
kubectl describe release.helm.crossplane.io/production-ingress -n crossplane-system
# → Name:         production-ingress
# → Namespace:    crossplane-system
# → Events:
# →   Type    Reason                    Age   From                                 Message
# →   ----    ------                    ----  ----                                 -------
# →   Normal  CreatedExternalResource   45m   managed/release.helm.crossplane.io   Successfully requested creation of external resource
# →   Normal  ReconcileSuccess          2m    managed/release.helm.crossplane.io   Successfully reconciled resource
```

### 4. Просмотр и фильтрация логов с помощью jq

Просмотр ошибок контроллера провайдера в реальном времени:
```bash
kubectl -n crossplane-system logs -l app.kubernetes.io/component=crossplane-provider -c package-runtime --tail=50 | jq 'select(.level=="error") | {time: .ts, controller: .controller, msg: .msg, error: .error}'
# → {
# →   "time": 1728825600.124,
# →   "controller": "managed/release.helm.crossplane.io",
# →   "msg": "cannot reconcile resource",
# →   "error": "release already exists"
# → }
```

### 5. Проверка состояния установленных пакетов

Проверка статуса здоровья всех установленных провайдеров и функций:
```bash
kubectl get providers,functions
# → NAME                                                   INSTALLED   HEALTHY   PACKAGE                                                      AGE
# → provider.pkg.crossplane.io/provider-kubernetes         True        True      xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v0.15 42d
# → provider.pkg.crossplane.io/provider-helm               True        True      xpkg.upbound.io/crossplane-contrib/provider-helm:v0.19       42d
# →
# → NAME                                                   INSTALLED   HEALTHY   PACKAGE                                                      AGE
# → function.pkg.crossplane.io/function-patch-and-transform True       True      xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.1 42d
```

---

## Устранение неполадок (Troubleshooting)

### Типичные неполадки и регламент устранения

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| **Prometheus сообщает `Scrape target down` на порту 8080** | Не открыт порт в поде, отсутствует метка селектора `PodMonitor` либо трафик заблокирован `NetworkPolicy`. | `kubectl get pod -n crossplane-system -o wide`<br>`kubectl get podmonitor -n crossplane-system`<br>`kubectl describe networkpolicy -n crossplane-system` | 1. Проверить совпадение селекторов в `PodMonitor` и labels пода.<br>2. Убедиться, что `DeploymentRuntimeConfig` провайдера объявляет `ports[].containerPort: 8080`.<br>3. Разрешить входящий трафик от Prometheus в `NetworkPolicy`. |
| **Взрывной рост `workqueue_depth` и падение производительности** | Слишком частый поллинг (`--poll`), низкий лимит воркеров (`--max-reconcile-rate`) или зависание запросов к внешним системам. | `curl -s localhost:8080/metrics \| grep workqueue`<br>`kubectl top pods -n crossplane-system` | 1. Увеличить `--poll` (например, с 10s до 60s или 120s) в `DeploymentRuntimeConfig`.<br>2. Отрегулировать воркеры через `--max-reconcile-rate=100`.<br>3. Выделить больше CPU/памяти подам провайдера. |
| **Ложный алерт `CrossplaneDriftDetected`** | Целевая система нормализует параметры (например, добавляет дефолтные порты или поля), что Crossplane воспринимает как сторонний дрейф. | Сравнить `spec.forProvider` и фактическое состояние в логах провайдера (`--debug`). | Использовать директиву `managementPolicies: ["Observe"]` либо настроить игнорирование мутирующих полей через `ignoreChanges` в схеме провайдера. |
| **Под провайдера или функции завершается с `OOMKilled`** | Утечка памяти при реконсиляции тысяч MR или генерации больших манифестов функциями композиции. | `kubectl describe pod -n crossplane-system <pod-name>` (проверить `Last State: Terminated`, `Exit Code: 137`). | 1. Увеличить `resources.limits.memory` в `DeploymentRuntimeConfig`.<br>2. Разделить крупные монолитные композиции на независимые суб-композиции.<br>3. Включить Go GC тюнинг: `GOMEMLIMIT` и `GOGC=80`. |
| **Забивание etcd событиями (Event spamming)** | Ресурс находится в состоянии перманентной ошибки (`Synced=False`), контроллер непрерывно генерирует `Warning Events`. | `kubectl get events -n crossplane-system --sort-by='.metadata.creationTimestamp'` | 1. Устранить причину ошибки на целевом ресурсе.<br>2. Приостановить реконсиляцию проблемного ресурса аннотацией `crossplane.io/paused: "true"`. |
| **`crossplane beta trace` завершается с ошибкой `not found`** | Использован неверный ресурс (Claim вместо XR), указан не тот Namespace либо плагин CLI устарел. | `crossplane version`<br>`kubectl get <kind> -A` | 1. Уточнить имя и пространство имен ресурса.<br>2. Обновить Crossplane CLI: `curl -sL https://raw.githubusercontent.com/crossplane/crossplane/master/install.sh \| sh`. |

---

## Лучшие практики (Best Practices)

1. **Тюнинг интервалов сверки (Poll Interval):**
   - Значение по умолчанию `--poll=1m` подходит для небольших инсталляций (< 200 ресурсов).
   - В крупных кластерах (> 1000 ресурсов) увеличьте интервал опроса до `3m`–`5m` через `DeploymentRuntimeConfig` (`--poll=300s`). Это предотвратит деградацию API-сервера Kubernetes и насыщение сетевых каналов.
2. **Селективное разделение провайдеров:**
   - Избегайте развертывания монолитных сборок с сотнями ненужных CRD.
   - Используйте специализированные легковесные провайдеры (`provider-kubernetes`, `provider-helm`, `provider-sql`) с индивидуальными `DeploymentRuntimeConfig` для изоляции сбоев и независимого масштабирования памяти.
3. **Защита эндпоинтов телеметрии:**
   - Порт `8080` экспортирует открытый HTTP-эндпоинт без аутентификации.
   - В мультитенантных кластерах изолируйте пространство имен `crossplane-system` строгой `NetworkPolicy`, разрешающей входящие соединения на порт `8080` исключительно от подов с лейблом Prometheus Scraper.
4. **Многоуровневая структура алертинга:**
   - **Warning (P2/P3):** Единичные ресурсы в `Ready=False` от 15 до 30 минут, обнаружение дрейфа, превышение очереди задач.
   - **Critical (P1):** Отказ контроллеров ядра, нездоровые пакеты (`crossplane_package_healthy == 0`), падение доли успешных реконсиляций ниже 95%, нехватка памяти/постоянные рестарты (`CrashLoopBackOff`, `OOMKilled`).
5. **Ротация и ретеншен логов:**
   - Не храните логи с флагом `--debug` в постоянном режиме в продакшене. Включайте `--debug` точечно для проблемного провайдера через `DeploymentRuntimeConfig`.
   - Настройте лимит хранения логов в Loki / Vector до 7–14 дней для экономии дискового пространства в On-Prem инфраструктуре.

---

## Дополнительная информация

Внутренние ссылки на смежные разделы базы знаний:
- [Обзор Crossplane](./overview.md) — фундаментальные концепции, компоненты и модель работы.
- [Мультитенантность и изоляция](./multi_tenancy.md) — изоляция тенантов, RBAC Manager и защита инфраструктуры.
- [Composition Functions](./composition_functions.md) — архитектура конвейера функций, их логирование и RuntimeConfig.
- [Интеграция с GitOps](./gitops_integration.md) — совместная работа с Argo CD/Flux и отслеживание синхронизации.
- [Резервное копирование и восстановление](./backup_dr.md) — резервирование состояния etcd, XR и обработка аварий.
- [Тестирование платформы](./testing_crossplane.md) — валидация композиций до выкатки в продакшен.
- [Настройка Provider Kubernetes](./provider_kubernetes_setup.md) — управление внутренними объектами кластера через Crossplane.
- [Типовые аварийные паттерны](./incident_patterns.md) — runbook на OOMKill, herd reconcile, finalizer deadlock, деградацию etcd/API.
- [Capacity Planning и сайзинг](./capacity_planning.md) — ресурсные лимиты control plane и тюнинг poll interval.
- [Управление секретами в GitOps](../secrets_encryption.md) — ESO, SOPS, HashiCorp Vault для доставки учетных данных.
- [PodMonitor (CRD)](../../Prometheus/kubernetes/operator/crd/podmonitor.md) — декларативный скрейпинг подов через Prometheus Operator.
- [ServiceMonitor (CRD)](../../Prometheus/kubernetes/operator/crd/servicemonitor.md) — мониторинг эндпоинтов сервисов.
- [PrometheusRule (CRD)](../../Prometheus/kubernetes/operator/crd/prometheusrule.md) — декларативное описание правил алертинга и записи.

Внешние официальные ресурсы:
- [Официальная документация Crossplane по метрикам](https://docs.crossplane.io/latest/guides/metrics/)
- [Grafana Dashboard: Crossplane Metrics (ID 24549)](https://grafana.com/grafana/dashboards/24549-crossplane-metrics/)
