# Интеграция с долгосрочным хранилищем (LTS) через Operator

## Определения

**Long-Term Storage (LTS) для Prometheus** — внешнее хранилище метрик, обеспечивающее сохранность данных за пределами локального retention TSDB (обычно 15-30 дней). В контексте Kubernetes Operator используются три основных подхода: Thanos Sidecar (интеграция через `spec.thanos`), VictoriaMetrics (через `remoteWrite`) и Mimir (через `remote_write`).

**Thanos Sidecar** — компонент, добавляемый Operator-ом к каждому поду Prometheus через `spec.thanos`. Sidecar выгружает закрытые TSDB-блоки в объектное хранилище (S3/GCS/MinIO) и предоставляет gRPC API для Thanos Query (глобальный view и дедупликация).

**VictoriaMetrics** — высокопроизводительная альтернатива TSDB с совместимым с PromQL языком MetricsQL. Интеграция с Operator через `remoteWrite` в Prometheus CRD, направляющий данные на HTTP-эндпоинт VictoriaMetrics (`/api/v1/write`).

**Mimir** — микросервисная платформа для LTS от Grafana Labs. Не использует Operator CRD — интеграция через стандартный `remote_write` конфиг Prometheus. Mimir имеет собственную Helm-диаграмму (mimir-distributed).

> **Смотрите также:** [Концепции](./concepts.md) — архитектура Operator; [High Availability](./high_availability.md) — Remote Write queueConfig; [Thanos Overview](../../../Prometheus/scaling/thanos_overview.md); [VictoriaMetrics Overview](../../../VictoriaMetrics/overview.md); [Mimir Overview](../../../Mimir/mimir_overview.md).

---

## Базовые концепции

### Сравнение трех подходов

| Характеристика | Thanos Sidecar | VictoriaMetrics | Mimir |
|:---|:---|:---|:---|
| **Механизм интеграции** | `spec.thanos` в Prometheus CRD | `remoteWrite` в Prometheus CRD | `remote_write` в конфиге |
| **Оператор** | Prometheus Operator (нативно) | VM Operator (отдельный) | Собственный Helm-chart |
| **Дедупликация** | Query component (по external_labels) | Нативная (по `extra_label`) | Distributor (по tenant ID) |
| **Хранилище** | S3/GCS/MinIO/Azure Blob | S3/GCS/MinIO/Local | S3/GCS/MinIO |
| **Multi-tenancy** | Нет (через label isolation) | Да (`extra_labels`) | Да (`X-Scope-OrgID`) |
| **Глобальный view** | Thanos Query (gRPC) | vminsert/vmselect | Query Frontend |
| **Downsampling** | Compactor | Нативный (retention policies) | Compactor |
| **Алерты/recording rules** | Thanos Ruler | vmalert | Ruler (Mimir API) |
| **Overhead RAM** | ~200-500 MiB на sidecar | ~10% от Prometheus | Зависит от компонентов |

### Архитектурные паттерны

#### Паттерн 1: Thanos Sidecar (самый распространенный в Operator)

```
Prometheus (StatefulSet)
    ├── thanos-sidecar (container)
    │     ├──上传 блоков → S3/GCS
    │     └── gRPC (10901) → Thanos Query
    ├── config-reloader (sidecar)
    └── prometheus (main)

Thanos Query → Store Gateway (S3) + Sidecar (gRPC)
    └── Global View + Dedup
```

**Преимущества:** Нативная интеграция с Operator, минимальный overhead, data remains in Prometheus TSDB.

**Ограничения:** Sidecar не может уменьшить нагрузку на Prometheus (данные все еще хранятся локально).

#### Паттерн 2: VictoriaMetrics (remoteWrite)

```
Prometheus (StatefulSet)
    └── remoteWrite → VictoriaMetricsSingle / VMCluster
                            ├── TSDB (локальный)
                            └── Data retention: годы

Prometheus (Agent Mode)
    └── remoteWrite → VictoriaMetrics (без локального TSDB)
```

**Преимущества:** Значительная экономия ресурсов Prometheus (особенно Agent Mode), встроенная поддержка downsampling, multi-tenancy.

**Ограничения:** Требует отдельного Operator (VM Operator) или ручной deployment.

#### Паттерн 3: Mimir (remote_write)

```
Prometheus (StatefulSet) или Alloy
    └── remoteWrite → Mimir Distributor
                            ├── Ingester → WAL → S3
                            └── Query Frontend → Grafana
```

**Преимущества:** Микросервисная архитектура, native multi-tenancy, интеграция с Grafana.

**Ограничения:** Более сложная operational модель, нет нативной интеграции с Prometheus Operator CRD.

---

## Практические сценарии

### Сценарий 1: Thanos Sidecar через Operator

#### Шаг 1: Создание Secret для объектного хранилища

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: thanos-objstore-config
  namespace: monitoring
type: Opaque
stringData:
  thanos.yaml: |
    type: s3
    config:
      bucket: "thanos-metrics"
      endpoint: "minio.corp.local:9000"
      access_key: "minioadmin"
      secret_key: "minioadmin"
      insecure: false
```

#### Шаг 2: Конфигурация Prometheus с Thanos Sidecar

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.12.0
  retention: 7d  # Локально — только для HA и быстрого доступа
  retentionSize: 45GB
  externalLabels:
    cluster: "prod-europe-1"
    prometheus_replica: "$(POD_NAME)"
  thanos:
    version: v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 50Gi
```

#### Шаг 3: NetworkPolicy для Thanos gRPC

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: thanos-sidecar-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: thanos-sidecar
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 10901
          protocol: TCP
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: thanos-query
      ports:
        - port: 10901
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Egress к объектному хранилищу (S3/MinIO)
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8  # IP MinIO/S3
      ports:
        - port: 9000
          protocol: TCP
        - port: 443
          protocol: TCP
```

#### Шаг 4: Верификация

```bash
# Проверка запуска thanos-sidecar
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus -o jsonpath='{.items[*].spec.containers[*].name}'
# → prometheus config-reloader thanos-sidecar

# Проверка логов sidecar
kubectl logs -n monitoring prometheus-main-0 -c thanos-sidecar --tail=50

# Проверка выгрузки блоков
kubectl logs -n monitoring prometheus-main-0 -c thanos-sidecar | grep -i "upload"

# Проверка доступности Thanos Query
kubectl port-forward -n monitoring svc/thanos-query 10902:10902
# → http://localhost:10902
```

### Сценарий 2: Remote Write в VictoriaMetrics

#### Шаг 1: Установка VictoriaMetrics (single-node)

```bash
helm repo add victoriametrics https://victoriametrics.github.io/helm-charts/
helm install victoria-metrics victoriametrics/victoria-metrics-single \
  -n monitoring \
  --set storage retention=30d \
  --set storage storagePath=/victoria-metrics/data
```

#### Шаг 2: Конфигурация Prometheus с remoteWrite

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.12.0
  remoteWrite:
    - url: "http://victoria-metrics.monitoring.svc:8428/api/v1/write"
      remoteTimeout: 30s
      sendExemplars: true
      queueConfig:
        capacity: 25000
        maxShards: 150
        minShards: 10
        maxSamplesPerSend: 5000
        batchSendDeadline: 3s
        minBackoff: 30ms
        maxBackoff: 10s
      writeRelabelConfigs:
        # Фильтрация метрик перед отправкой
        - action: drop
          regex: "container_network_.*"
          sourceLabels: [__name__]
        # Добавление tenant label
        - action: replace
          targetLabel: tenant_id
          replacement: "prod"
  storage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 20Gi  # Только WAL + локальная retention
```

#### Шаг 3: Верификация

```bash
# Проверка очереди remote write
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/metrics | grep -E "prometheus_remote_storage_shards|prometheus_remote_storage_dropped"

# Проверка данных в VictoriaMetrics
kubectl port-forward -n monitoring svc/victoria-metrics 8428:8428
curl -s 'http://localhost:8428/api/v1/query?query=up' | jq .
```

### Сценарий 3: Remote Write в Mimir

#### Шаг 1: Конфигурация Prometheus с remoteWrite в Mimir

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  remoteWrite:
    - url: "http://mimir-nginx.monitoring.svc:8080/api/v1/push"
      remoteTimeout: 30s
      headers:
        X-Scope-OrgID: "prod"
      queueConfig:
        capacity: 10000
        maxShards: 100
        maxSamplesPerSend: 2000
        batchSendDeadline: 5s
      tlsConfig:
        cert:
          secret:
            name: mimir-client-tls
            key: tls.crt
        keySecret:
          name: mimir-client-tls
          key: tls.key
```

#### Шаг 2: Verификация доставки

```bash
# Мониторинг очереди
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/metrics | grep prometheus_remote_storage_samples_pending

# Если pending растет — проблема с доступностью Mimir
# Проверка Mimir Distributor
kubectl logs -n monitoring -l app.kubernetes.io/name=mimir-distributor --tail=50 | grep -i "push"
```

### Diagnostics

```bash
# 1. Проверка remote_write очереди (для VM/Mimir)
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/metrics | grep -E "prometheus_remote_storage_(shards|dropped|pending)"

# 2. Проверка логов thanos-sidecar (для Thanos)
kubectl logs -n monitoring prometheus-main-0 -c thanos-sidecar | grep -E "upload|error|heartbeat"

# 3. Проверка доступности хранилища
# Для S3/MinIO:
kubectl run -n monitoring --rm -it --image=curlimages/curl debug -- \
  curl -s http://minio.corp.local:9000/minio/health/live

# 4. Проверка метрик LTS
# Thanos: thanos_sidecar_last_successful_upload_timestamp
# VM: vm_rows_inserted_total
# Mimir: mimir_ingester_TSDB_head_series
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Prometheus CRD](./crd/prometheus.md) | Поля `spec.thanos`, `remoteWrite`, `externalLabels` |
| [High Availability](./high_availability.md) | Remote Write queueConfig, WAL, stale markers |
| [Secrets](./Security/secrets_best_practices.md) | Конфигурация `thanos-objstore-config` Secret |
| [NetworkPolicy](./Security/access_control.md) | Правила для Thanos Sidecar (порт 10901) |
| [Thanos Overview](../../../Prometheus/scaling/thanos_overview.md) | Архитектура Thanos, Store Gateway, Compactor |
| [Remote Read/Write](../../../Prometheus/scaling/remote_read_write.md) | Протокол, queueConfig, WAL, write_relabel_configs |
| [VictoriaMetrics Overview](../../../VictoriaMetrics/overview.md) | MetricsQL, vmagent, vmalert |
| [Mimir Overview](../../../Mimir/mimir_overview.md) | Архитектура Mimir, multi-tenancy, sizing |
| [Agent Mode](../../../Prometheus/concepts/agent_mode.md) | Agent vs Server для edge-кластеров |

### Частые ошибки на собеседованиях

1. **"Thanos заменяет Prometheus"** — Нет. Thanos добавляет глобальный view, дедупликацию и долгосрочное хранилище. Prometheus по-прежнему скрейпит и хранит данные локально.
2. **"remote_write обеспечивает exactly-once delivery"** — Нет. Только at-least-once. Дубликаты дедуплицируются LTS по timestamp + fingerprint.
3. **"Agent Mode не нуждается в диске"** — Нет. WAL буферизует данные при недоступности LTS. Требуется SSD.
4. **"retention в Operator = retention в LTS"** — Нет. `spec.retention` управляет локальным retention. LTS retention настраивается отдельно (S3 lifecycle, Thanos Compactor, VM retention).
