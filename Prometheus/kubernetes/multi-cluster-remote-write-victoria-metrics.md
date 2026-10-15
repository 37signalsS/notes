# Мультикластерный Prometheus: remote_write в централизованное хранилище VictoriaMetrics

**Актуально для:** kube-prometheus-stack 70.x, VictoriaMetrics v1.140.x, APISIX 3.10.x, Prometheus 3.x, Kubernetes 1.31+

В каждом spoke-кластере работает собственный Prometheus (через kube-prom-stack). Для долгосрочных трендов, кросс-кластерных сравнений и хранения метрик дольше, чем позволяет spoke-кластер, spoke-экземпляры Prometheus пишут через `remote_write` в центральный VictoriaMetrics на infra-кластере.

## Определения

| Понятие | Описание |
|---|---|
| **Spoke-кластер** | Операционный Kubernetes-кластер (on-prem, YC, edge), в котором работает локальный Prometheus через kube-prom-stack. |
| **Infra-кластер** | Централизованный кластер, на котором развёрнуто центральное хранилище метрик (VictoriaMetrics) и Grafana для единого observability-окна. |
| **kube-prom-stack** | [Helm-чарт](../../Kube_Prometheus_Stack_Helm/overview.md) `kube-prometheus-stack` (KPS), объединяющий Prometheus, Alertmanager, Grafana, node-exporter и правила алертинга в одном релизе. |
| **Kustomize-патч** | Слои Kustomize, применяемые к каждому spoke-окружению (dev/staging/prod) для переопределения значений HelmRelease через `spec.values`. |
| **externalLabels** | Глобальные метки, добавляемые к каждой серии Prometheus. Метка `cluster` используется для фильтрации в кросс-кластерных дашбордах. |

> **См. также:** [Remote Read/Write](../scaling/remote_read_write.md) — протокол, параметры `queueConfig`, `writeRelabelConfigs`, TLS/Basic Auth; [Интеграция с LTS через Operator](./operator/long_term_storage_integration.md) — конфигурация Prometheus CRD с `remoteWrite`; [VictoriaMetrics: обзор](../../../VictoriaMetrics/overview.md) — архитектура, режимы, HA.

## Базовые концепции

### Архитектура Spoke-to-Infrastructure

```text
[ Spoke Cluster A ]            [ Spoke Cluster B ]            [ Spoke Cluster C ]
  kube-prom-stack                 kube-prom-stack                  kube-prom-stack
  Prometheus (3d retention)       Prometheus (3d retention)        Prometheus (3d retention)
  externalLabels.cluster=A         externalLabels.cluster=B          externalLabels.cluster=C
        │                              │                                 │
        └──────────── remote_write ────┴────── remote_write ────────────┘
                        │                        │                        │
                     [ Central VictoriaMetrics on Infra Cluster ]
                        │ (90d retention, 50Gi PV)
                        └─ vm_rows_inserted_total
                               │
                    [ Grafana (Global View) ]
```

Ключевые принципы:

1. **Spoke-кластеры хранят только recent data** — `retention: 3d` и `retentionSize: 10GB` держат локальное хранилище компактным. Исторические данные существуют только в центральном VictoriaMetrics.
2. **Метка `cluster` в `externalLabels`** — каждая серия помечается именем кластера, что позволяет фильтровать по кластеру в дашбордах и запросах.
3. **writeRelabelConfigs** — на стороне Prometheus фильтруются только полезные метрики, снижая трафик ~60–70%.
4. **Восстановление после сбоя** — при недоступности VictoriaMetrics `remote_write` буферизует данные в WAL до лимита `retention`, затем выполняет backfill (см. [Remote Read/Write](../scaling/remote_read_write.md#механизм-backfill-при-восстановлении-связи)).

## Практические сценарии

### Сценарий 1: Конфигурация remote_write через kube-prom-stack values + Kustomize

Настройка живёт в `values` kube-prom-stack и применяется к каждому spoke-кластеру Kustomize-патчем:

```yaml
# patches/kube-prom-stack.yaml (окружение dev)
spec:
  values:
    prometheus:
      prometheusSpec:
        externalLabels:
          cluster: dev
          environment: dev
        remoteWrite:
          - url: "http://victoria-metrics.observability.infra.svc.cluster.local:8428/api/v1/write"
            queueConfig:
              capacity: 10000
              maxSamplesPerSend: 1000
              maxShards: 10
            writeRelabelConfigs:
              - sourceLabels: [__name__]
                regex: "(node_|container_|kube_|up|probe_).+"
                action: keep
        retention: 3d
        retentionSize: "10GB"
```

`externalLabels.cluster` помечает каждую серию именем кластера — это важно для кросс-кластерных дашбордов. `retention: 3d` держит spoke-хранилище компактным, поскольку исторические данные живут в VictoriaMetrics.

Параметры `queueConfig` (capacity, maxSamplesPerSend, maxShards) настраиваются в зависимости от нагрузки — см. [таблицу параметров очереди](../scaling/remote_read_write.md#настройка-очереди-отправки-queue_config) для тонкой настройки.

### Сценарий 2: Кросс-кластерный URL remote_write

На YC-кластерах и on-prem k3s VictoriaMetrics недоступна через внутренний DNS (это другой кластер). Два варианта:

**Вариант 1: Публикация VictoriaMetrics через APISIX (проще)**

```yaml
# ApisixRoute на infra
- name: vm-remote-write
  match:
    hosts:
      - vm-write.infra.test.antonnovikov.com
    paths:
      - /api/v1/write
  backends:
    - serviceName: victoria-metrics-victoria-metrics
      serviceNamespace: observability
      servicePort: 8428
```

```yaml
# URL remote_write в spoke patches
remoteWrite:
  - url: "https://vm-write.infra.test.antonnovikov.com/api/v1/write"
```

**Вариант 2: WireGuard VPN между кластерами**

Spoke-кластеры подключаются к infra через VPN и обращаются к внутреннему ClusterIP напрямую. Это избегает публичного exposure, но требует настройки маршрутизации между кластерами.

```yaml
# URL remote_write через VPN (внутренний ClusterIP)
remoteWrite:
  - url: "http://victoria-metrics.observability.infra.svc.cluster.local:8428/api/v1/write"
```

### Сценарий 3: writeRelabelConfigs для снижения трафика

Отправлять все серии в центральное хранилище расточительно. `writeRelabelConfigs` фильтрует только самые полезные метрики:

```yaml
writeRelabelConfigs:
  # Оставляем: инфраструктурные метрики
  - sourceLabels: [__name__]
    regex: "(node_|container_|kube_state_|up|probe_|kubelet_).+"
    action: keep
  # Отбрасываем: высококардинальные шумные метрики
  - sourceLabels: [__name__]
    regex: "(go_gc_|go_memstats_|process_).+"
    action: drop
  # Отбрасываем: метрики короткоживущих подов (заменяем recording rules)
  - sourceLabels: [__name__, pod]
    regex: "container_.+;.+-[a-z0-9]{10}-.+"
    action: drop
```

Это снижает трафик `remote_write` на ~60–70% по сравнению с отправкой всего подряд. Общие принципы relabeling описаны в [Remote Read/Write](../scaling/remote_read_write.md#фильтрация-мусора-relabeling).

### Сценарий 4: Кросс-кластерный дашборд в Grafana

Когда все кластеры пишут в VictoriaMetrics, один дашборд в Grafana позволяет сравнивать их:

```promql
sum by (cluster) (
  rate(container_cpu_usage_seconds_total{container!=""}[5m])
)
```

Добавляем template-переменную для фильтрации:

```json
{
  "name": "cluster",
  "type": "query",
  "query": "label_values(up, cluster)",
  "datasource": "VictoriaMetrics"
}
```

Переменная заполняется из лейбла `cluster`, который добавляет `externalLabels`.

### Сценарий 5: Проверка работоспособности remote_write

```bash
# На spoke: проверяем очередь remote_write
kubectl port-forward -n observability svc/prometheus-operated 9090:9090
# Затем: http://localhost:9090/graph?g0.expr=prometheus_remote_storage_queue_length

# На infra: проверяем скорость приёма в VictoriaMetrics
kubectl port-forward -n observability svc/victoria-metrics-victoria-metrics 8428:8428
# Затем: http://localhost:8428/api/v1/query?query=sum(rate(vm_rows_inserted_total[5m]))
```

Ошибки `remote_write` отражаются в `prometheus_remote_storage_failed_samples_total`. Устойчивое ненулевое значение означает, что центральный VictoriaMetrics недоступен или отклоняет записи.

Дополнительные метрики для мониторинга:

| Метрика | Описание |
|:---|:---|
| `prometheus_remote_storage_queue_length` | Текущий размер очереди. |
| `prometheus_remote_storage_queue_capacity` | Максимальная ёмкость очереди. |
| `prometheus_remote_storage_failed_samples_total` | Количество неудалось отправить. |
| `prometheus_remote_storage_dropped_samples_total` | Сэмплы, отброшенные при переполнении очереди. |
| `vm_rows_inserted_total` | Количество строк, вставленных в VictoriaMetrics. |

### Сценарий 6: Алертинг на задержку remote_write

```yaml
# PrometheusRule для алерта при росте очереди remote_write
- alert: RemoteWriteQueueFull
  expr: >
    prometheus_remote_storage_queue_length /
    prometheus_remote_storage_queue_capacity > 0.8
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Очередь remote_write > 80% на {{ $labels.cluster }}"
    description: "VictoriaMetrics может быть недоступна или работать медленно"
```

### Сценарий 7: Настройка VictoriaMetrics на infra-кластере

```yaml
# values HelmRelease VictoriaMetrics
server:
  retentionPeriod: 90d
  persistentVolume:
    size: 50Gi
  resources:
    requests:
      memory: 2Gi
      cpu: 500m
    limits:
      memory: 4Gi
```

При 3 spoke-кластерах, пишущих ~500k samples/min каждый, 90 дней помещаются в ~30–40Gi. VictoriaMetrics сжимает данные значительно лучше, чем Prometheus TSDB (~10x), поэтому реальное потребление диска намного ниже. Формулы оценки размера диска описаны в [разделе планирования мощностей VictoriaMetrics](../../VictoriaMetrics/overview.md#планирование-мощностей-capacity-planning).

### Сценарий 8: Аутентификация для remote_write

Если VictoriaMetrics доступна из интернета (через APISIX), включить basic auth:

```yaml
# VictoriaMetrics: включить basic auth
server:
  extraArgs:
    httpAuth.username: "prom-writer"
    httpAuth.password: "strong-password"
```

```yaml
# Spoke Prometheus remote_write
remoteWrite:
  - url: "https://vm-write.infra.test.example.com/api/v1/write"
    basicAuth:
      username:
        name: vm-remote-write-secret
        key: username
      password:
        name: vm-remote-write-secret
        key: password
```

Секрет — SealedSecret, закоммиченный в spoke overlay. Другие варианты аутентификации (Bearer Token, OAuth2, mTLS) описаны в [Remote Read/Write](../scaling/remote_read_write.md#безопасность-auth-tls-и-mtls).

## Дополнительная информация

- [Remote Read/Write](../scaling/remote_read_write.md) — протокол, параметры `queueConfig`, `writeRelabelConfigs`, безопасность
- [Интеграция с LTS через Operator](./operator/long_term_storage_integration.md) — конфигурация `remoteWrite` в Prometheus CRD
- [VictoriaMetrics: обзор](../../../VictoriaMetrics/overview.md) — архитектура, режимы, sizing
- [Мультикластерный мониторинг Prometheus](./multi_cluster_monitoring.md) — сравнение моделей (Federation, Thanos, Mimir)
- [Высокая доступность Prometheus](../concepts/high_availability.md) — HA-паттерны и remote_write
