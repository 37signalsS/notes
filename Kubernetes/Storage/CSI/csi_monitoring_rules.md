# Мониторинг и алертинг CSI-драйверов

## Определения

**CSI Monitoring и Alerting** — система отслеживания состояния CSI-драйверов, томов и операций хранения в Kubernetes, включающая метрики (Prometheus), визуализацию (Grafana) и оповещения (Alertmanager). Цель — обнаружение проблем до того, как они повлияют на приложения.

Три уровня мониторинга CSI:
1. **Уровень kubelet** — статистика использования томов (`kubelet_volume_stats_*`)
2. **Уровень CSI-драйвера** — метрики операций (создание, монтирование, снапшоты)
3. **Уровень СХД** — здоровье хранилища (Ceph, Longhorn, NFS)

---

## Теоретический блок

### Метрики kubelet по томам

`kubelet` экспортирует метрики для каждого смонтированного тома:

| Метрика | Описание | Использование |
| :--- | :--- | :--- |
| `kubelet_volume_stats_capacity_bytes` | Общий размер тома | Алерт на заполнение |
| `kubelet_volume_stats_used_bytes` | Использовано | `used/capacity > 0.85` |
| `kubelet_volume_stats_available_bytes` | Свободно | `available < 10Gi` |
| `kubelet_volume_stats_inodes_total` | Всего inodes | Мониторинг inode exhaustion |
| `kubelet_volume_stats_inodes_used` | Использовано inodes | `inodes_used/inodes_total > 0.85` |

> **Важно:** Для **блочных** (raw block) томов метрики `kubelet_volume_stats_*` обычно **не публикуются** — за их заполнением следит сама СХД.

### Метрики CSI-драйвера

| Метрика | Описание |
| :--- | :--- |
| `csi_operations_seconds` | Гистограмма задержек CSI RPC-вызовов |
| `csi_operations_errors_total` | Счётчик ошибок CSI-операций |
| `storage_operation_duration_seconds` | Задержки операций storage-контроллера |
| `storage_operation_errors_total` | Ошибки storage-операций |

### Метрики sidecar-контейнеров

| Sidecar | Метрика | Описание |
| :--- | :--- | :--- |
| `external-provisioner` | `csi_provisioner_operations_duration_seconds` | Задержки CreateVolume/DeleteVolume |
| `external-attacher` | `csi_attacher_operations_duration_seconds` | Задержки Attach/Detach |
| `external-resizer` | `csi_resizer_operations_duration_seconds` | Задержки ExpandVolume |
| `external-snapshotter` | `csi_snapshotter_operations_duration_seconds` | Задержки CreateSnapshot/DeleteSnapshot |

### PromQL паттерны для алертов

```promql
# Уровень заполнения PVC (> 85%)
(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.85

# Критическое заполнение PVC (> 95%)
(kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.95

# Exhaustion inodes
(kubelet_volume_stats_inodes_used / kubelet_volume_stats_inodes_total) > 0.85

# PVC в статусе Pending более 10 минут
kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1

# Ошибки CSI-операций
increase(csi_operations_errors_total[5m]) > 0

# Высокая латентность CSI-операций
histogram_quantile(0.99, rate(csi_operations_seconds_bucket[5m])) > 2

# Volume в ненормальном состоянии
kube_volumehealth_condition{condition="Abnormal"} == 1
```

---

## Практический блок

### PrometheusRule: Алерты для CSI и PVC

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: csi-storage-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: csi-storage.rules
      rules:
        # ===== УРОВЕНЬ ЗАПОЛНЕНИЯ PVC =====
        - alert: PersistentVolumeUsageHigh
          expr: |
            (
              kubelet_volume_stats_used_bytes
              / kubelet_volume_stats_capacity_bytes
            ) > 0.85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} заполнена на {{ $value | humanizePercentage }}"
            description: "Рекомендуется расширение тома или очистка данных"

        - alert: PersistentVolumeUsageCritical
          expr: |
            (
              kubelet_volume_stats_used_bytes
              / kubelet_volume_stats_capacity_bytes
            ) > 0.95
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} заполнена на {{ $value | humanizePercentage }}"
            description: "Критическое заполнение! Приложение может начать падать через несколько минут"

        # ===== INODE EXHAUSTION =====
        - alert: PersistentVolumeInodeExhaustion
          expr: |
            (
              kubelet_volume_stats_inodes_used
              / kubelet_volume_stats_inodes_total
            ) > 0.85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} — исчерпание inodes ({{ $value | humanizePercentage }})"

        # ===== PVC в статусе Pending =====
        - alert: PersistentVolumeClaimPending
          expr: |
            kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} в namespace {{ $labels.namespace }} в статусе Pending более 10 минут"

        # ===== ОШИБКИ CSI-ОПЕРАЦИЙ =====
        - alert: CSIOperationsErrors
          expr: |
            increase(csi_operations_errors_total[5m]) > 0
          for: 1m
          labels:
            severity: warning
          annotations:
            summary: "CSI-драйвер {{ $labels.driver }} генерирует ошибки"
            description: "{{ $value }} ошибок за последние 5 минут"

        # ===== ВЫСОКАЯ ЛАТЕНТНОСТЬ CSI =====
        - alert: CSIOperationsHighLatency
          expr: |
            histogram_quantile(0.99,
              rate(csi_operations_seconds_bucket[5m])
            ) > 5
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокая латентность CSI-операций ({{ $value }}s p99)"

        # ===== VOLUME HEALTH =====
        - alert: VolumeConditionAbnormal
          expr: |
            kube_volumehealth_condition{condition="Abnormal"} == 1
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Volume {{ $labels.persistentvolumeclaim }} в ненормальном состоянии"

        # ===== CSI-ДРАЙВЕР НЕ ГОТОВ =====
        - alert: CSIDriverNotReady
          expr: |
            absent(up{job="csi-driver"} == 1)
          for: 3m
          labels:
            severity: critical
          annotations:
            summary: "CSI-драйвер {{ $labels.driver }} не отвечает"

        # ===== STORAGECAPACITY ОТСУТСТВУЕТ =====
        - alert: CSIStorageCapacityMissing
          expr: |
            absent(csi_storage_capacity_bytes)
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "CSIStorageCapacity объекты отсутствуют — планировщик не учитывает ёмкость"
```

### Grafana Dashboard: Обзор CSI и Storage

```json
{
  "annotations": { "list": [] },
  "editable": true,
  "title": "CSI Storage Overview",
  "uid": "csi-storage-overview",
  "panels": [
    {
      "title": "PVC Usage",
      "type": "stat",
      "gridPos": { "h": 6, "w": 12, "x": 0, "y": 0 },
      "targets": [
        {
          "expr": "sum(kubelet_volume_stats_used_bytes) by (namespace, persistentvolumeclaim) / sum(kubelet_volume_stats_capacity_bytes) by (namespace, persistentvolumeclaim)",
          "legendFormat": "{{ namespace }}/{{ persistentvolumeclaim }}"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "unit": "percentunit",
          "thresholds": {
            "steps": [
              { "value": 0, "color": "green" },
              { "value": 0.7, "color": "yellow" },
              { "value": 0.85, "color": "orange" },
              { "value": 0.95, "color": "red" }
            ]
          }
        }
      }
    },
    {
      "title": "CSI Operations Latency (p99)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "targets": [
        {
          "expr": "histogram_quantile(0.99, rate(csi_operations_seconds_bucket[5m]))",
          "legendFormat": "{{ operation_type }}"
        }
      ],
      "fieldConfig": { "defaults": { "unit": "s" } }
    },
    {
      "title": "PVC Capacity",
      "type": "table",
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 8 },
      "targets": [
        {
          "expr": "kubelet_volume_stats_capacity_bytes",
          "legendFormat": "capacity",
          "format": "table",
          "instant": true
        },
        {
          "expr": "kubelet_volume_stats_used_bytes",
          "legendFormat": "used",
          "format": "table",
          "instant": true
        },
        {
          "expr": "kubelet_volume_stats_available_bytes",
          "legendFormat": "available",
          "format": "table",
          "instant": true
        }
      ]
    }
  ],
  "time": { "from": "now-6h", "to": "now" },
  "refresh": "30s"
}
```

### Настройка ServiceMonitor для CSI-драйвера

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: csi-driver-monitor
  namespace: kube-system
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: csi-rbdplugin-provisioner
  namespaceSelector:
    matchNames:
      - kube-system
  endpoints:
    - port: healthz
      interval: 30s
      path: /healthz/healthz
    - port: csi-http-metrics
      interval: 30s
      path: /metrics
```

### Проверка наличия метрик

```bash
# Проверка метрик kubelet по томам
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090
# В Prometheus UI: kubelet_volume_stats_available_bytes

# Проверка CSI-метрик
kubectl logs -n kube-system -l app=csi-rbdplugin-provisioner -c csi-provisioner | grep -i metric

# Проверка ServiceMonitor
kubectl get servicemonitor -A | grep csi
```

---

## Дополнительная информация

### Связанные темы
- [CSI — Обзор](./csi_overview.md) — архитектура и метрики
- [CSI — Сравнение драйверов](./csi_drivers_comparison.md) — мониторинг в таблице
- [Prometheus — Kubernetes](../../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md) — стек мониторинга
- [Grafana — Alerting](../../../../Grafana/alerting/kubernetes_alerts.md) — Kubernetes-алерты
- [Velero — Метрики](../../../ToolsUtilities/velero-overview.md#мониторинг) — метрики бэкапов

### Официальные источники
- [Kubernetes CSI Metrics](https://kubernetes-csi.github.io/docs/metrics.html) — CSI-метрики
- [kubelet Volume Stats](https://github.com/kubernetes/kubernetes/blob/master/pkg/kubelet/stats/cri_stats_provider.go) — реализация метрик
