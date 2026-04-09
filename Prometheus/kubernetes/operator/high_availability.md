# Prometheus Operator — Высокая доступность

## Definitions

**High Availability (HA) в Prometheus Operator** — обеспечение отказоустойчивости стека мониторинга через запуск нескольких реплик Prometheus и Alertmanager с автоматической синхронизацией состояния.

> **См. также:** [Scaling Overview](../../scaling/overview.md) — базовая HA без Operator, [Alertmanager HA](../../alertmanager.md#высокая-доступность-ha) — gossip-протокол.

## Basic Concepts

### HA Prometheus

Prometheus Operator управляет репликами Prometheus через StatefulSet. Каждая реплика собирает **одни и те же метрики** независимо.

**Ключевые принципы:**

- **Минимум 2 реплики** для отказоустойчивости
- **Одинаковая конфигурация** на всех репликах (управляется Operator)
- **StatefulSet** сохраняет идентичность pod'ов при перезапусках
- **Каждый экземпляр** хранит собственную локальную TSDB

### HA Alertmanager

Alertmanager использует **gossip-протокол** (порт 9094) для кластеризации:

- **Минимум 3 реплики** для кворума
- **Дедупликация алертов** — при получении одинакового алерта от нескольких Prometheus, уведомление отправляется один раз
- **Синхронизация silences** между репликами через gossip
- Prometheus Operator автоматически настраивает `--cluster.peer` для всех pod'ов

### Шардирование (Sharding)

Для распределения нагрузки цели скрейпинга разделяются между несколькими StatefulSet:

| Параметр | Описание |
|---|---|
| `replicas` | Количество реплик внутри каждого шарда (HA) |
| `shards` | Количество независимых StatefulSet (горизонтальное масштабирование) |

**Пример:** `replicas: 2, shards: 2` → 4 pod'а (2 шарда × 2 реплики), каждый шард собирает свою подмножество целей.

> **Важно:** Шардирование не обеспечивает дедупликацию — каждый шард хранит уникальные данные. Для глобального запроса используйте [Thanos](../../scaling/thanos_overview.md) или [Mimir](../../../Mimir/mimir_overview.md).

## Practical Scenarios

### HA Prometheus конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  version: v3.10.0
  serviceAccountName: prometheus
  serviceMonitorSelector:
    matchLabels:
      release: monitoring
  resources:
    requests:
      memory: 400Mi
      cpu: 200m
    limits:
      memory: 2Gi
      cpu: 1000m
  retention: 15d
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
```

### HA Alertmanager конфигурация

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  version: v0.31.0
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: standard
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
```

### Шардирование Prometheus

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  shards: 2
  # Остальные параметры аналогично HA конфигурации
```

### Проверка HA статуса

```bash
# Проверка реплик Prometheus
kubectl get prometheus -n monitoring
kubectl get statefulset -n monitoring -l app.kubernetes.io/name=prometheus

# Проверка кластера Alertmanager
kubectl get alertmanager -n monitoring
kubectl logs -n monitoring -l app.kubernetes.io/name=alertmanager | grep cluster

# Проверка gossip-соединений
kubectl exec -it alertmanager-main-0 -n monitoring -- \
  wget -qO- http://localhost:9094/api/v2/status | jq '.cluster'
```

### Thanos Sidecar для долгосрочного хранения

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  thanos:
    version: v0.37.0
    image: quay.io/thanos/thanos:v0.37.0
    resources:
      requests:
        memory: 128Mi
        cpu: 100m
```

> **Детали:** [Thanos Overview](../../scaling/thanos_overview.md), [Remote Read/Write](../../scaling/remote_read_write.md).

## Additional Information

### Метрики для мониторинга HA

| Метрика | Описание | Alert |
|---|---|---|
| `prometheus_operator_spec_replicas` | Ожидаемое количество реплик из spec | `!= actual` |
| `alertmanager_cluster_members` | Членов кластера Alertmanager | `< 3` |
| `alertmanager_cluster_alive_members` | Активных членов кластера | `< quorum` |
| `up{job="prometheus"}` | Статус экземпляров Prometheus | `== 0` |
| `prometheus_operator_reconcile_errors_total` | Ошибки reconciliation Operator | `rate > 0` |

### Ограничения базового HA

| Ограничение | Описание | Решение |
|---|---|---|
| **Расхождение данных** | Реплики никогда не имеют идентичных TSDB | Thanos Query для глобального обзора |
| **Визуализация** | Grafana получает дублированные ряды | HAProxy в режиме standby или Thanos |
| **Масштабирование** | HA не решает проблемы нагрузки | Шардирование или Remote Write |
| **Долгосрочное хранение** | Локальная TSDB ограничена 30-60 днями | Thanos Sidecar + S3 |

### Рекомендации по ресурсам

| Компонент | CPU request | Memory request | CPU limit | Memory limit |
|---|---|---|---|---|
| **Prometheus (HA)** | 200m | 400Mi | 1000m | 2Gi |
| **Alertmanager (HA)** | 100m | 128Mi | 200m | 256Mi |
| **Thanos Sidecar** | 100m | 128Mi | 250m | 256Mi |

> **См. также:** [Prometheus CRD](./crd/prometheus.md), [Alertmanager CRD](./crd/alertmanager.md), [Security](./Security/index.md), [Troubleshooting](./troubleshooting.md).
