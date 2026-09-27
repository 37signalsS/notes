# Расчет ресурсов Prometheus Operator

## Определения

**Resource Sizing Prometheus Operator** — методология расчета минимальных и рекомендуемых ресурсов (CPU, RAM, Disk) для компонентов стека мониторинга в Kubernetes, основанная на количестве активных серий (active series), частоте скрейпинга (scrape_interval) и 목표 retention. Правильный sizing предотвращает OOMKill, троттлинг CPU и переполнение TSDB.

**Active Series (Активные серии)** — количество временных рядов, которые Prometheus удерживает в Head Block (RAM). Каждая уникальная комбинация имени метрики и набора лейблов образует одну серию. Рост активных серий напрямую увеличивает потребление RAM и размер TSDB.

**Head Block** — текущий незакрытый блок TSDB, хранящийся в оперативной памяти. Все запросы PromQL выполняются к Head Block и закрытым блокам на диске. Размер Head Block пропорционален количеству активных серий.

**Bytes Per Sample** — количество байт, требуемых для хранения одного сэмпла в TSDB. Зависит от типа метрики и лейблов: для Gauge/Counter ~1-2 байта, для Histogram с высокой кардинальностью лейблов — до 8-16 байт.

> **Смотрите также:** [Концепции](./concepts.md) — архитектура TSDB; [Высокая доступность](./high_availability.md) — шардирование и репликация; [Prometheus TSDB](../../../Prometheus/concepts/tsdb.md) — внутренняя структура хранилища.

---

## Базовые концепции

### Формулы расчета ресурсов

#### RAM (промежуточное хранилище)

Формула для Prometheus Server:

```
RAM (GB) = 2 + (0.001 × active_series)
```

| Активные серии | RAM (рекомендуется) | RAM (QoS Guaranteed) |
|:---|:---|:---|
| < 100K | 2-4 GiB | 4 GiB |
| 100K — 500K | 4-8 GiB | 8 GiB |
| 500K — 1M | 8-16 GiB | 16 GiB |
| 1M — 5M | 16-64 GiB | 32-64 GiB |
| > 5M | 64+ GiB | Шардирование обязательно |

Дополнительные компоненты:

```
Head Block RAM = active_series × bytes_per_series (6-8 байт)
WAL Overhead = samples_per_second × bytes_per_sample × 2ч (默认保留)
Go GC Overhead = ~20-30% от общего объема RAM
```

Для крупных инстансов (>1M серий) рекомендуется установить `GOMEMLIMIT` на 70-80% от `limits.memory`:

```yaml
env:
  - name: GOMEMLIMIT
    value: "14GiB"  # При limits.memory: 20Gi
```

#### CPU

```
CPU (cores) = 2 + (0.0005 × active_series)
```

| Активные серии | CPU (рекомендуется) | CPU (heavy queries) |
|:---|:---|:---|
| < 100K | 0.5-1 core | 1-2 cores |
| 100K — 500K | 1-2 cores | 2-4 cores |
| 500K — 1M | 2-4 cores | 4-8 cores |
| > 1M | 4-8 cores | Шардирование обязательно |

Для скрейпинга: ~1 core на каждые 300-500K samples/сек.

#### Disk (TSDB)

```
Disk (GB) = weekly_growth_GB × retention_days
```

Где `weekly_growth` зависит от количества серий и scrape_interval:

| Активные серии | scrape_interval=15s | scrape_interval=30s | scrape_interval=60s |
|:---|:---|:---|:---|
| 100K | ~5-10 GB/нед | ~3-5 GB/нед | ~2-3 GB/нед |
| 500K | ~25-50 GB/нед | ~15-25 GB/нед | ~8-12 GB/нед |
| 1M | ~50-100 GB/нед | ~30-50 GB/нед | ~15-25 GB/нед |

**Рекомендации по retentionSize:**

```yaml
spec:
  retentionSize: 90GB  # На 10-15% меньше размера PVC
  storage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 100Gi
```

> **Важно:** `retentionSize` останавливает прием новых данных при достижении лимита, но оставляет место для WAL. Всегда выделяйте 10-15% запаса.

### Расчет количества шардов

Шарды распределяют скрейпинг между несколькими инстансами Prometheus. Каждый шард — отдельный StatefulSet.

```
shards = ceil(total_scrape_targets × scrape_interval_cpu_cost / cpu_per_shard)
```

**Эмпирическое правило:**

| Активные серии | Рекомендуемые шарды | Реплики на шард |
|:---|:---|:---|
| < 500K | 1 | 2 (HA) |
| 500K — 2M | 2-3 | 2 (HA) |
| 2M — 5M | 3-5 | 2 (HA) |
| > 5M | 5+ | 2 (HA) |

Общее количество подов = `shards × replicas`.

### Ресурсы для Agent Mode

Prometheus Agent потребляет на 30-40% меньше ресурсов за счет отсутствия TSDB и Query Engine:

| Активные серии | CPU | RAM | Disk (WAL) |
|:---|:---|:---|:---|
| 10K | 0.25 core | 256 MiB | 1 GB SSD |
| 50K | 0.5 core | 512 MiB | 2 GB SSD |
| 100K | 1 core | 1 GiB | 5 GB SSD |
| 500K | 2 cores | 2 GiB | 10 GB SSD |

WAL Size (Agent):

```
WAL (GB) = samples_per_second × bytes_per_sample × retention_seconds
```

### Alertmanager

| Реплики | CPU | RAM | Disk |
|:---|:---|:---|:---|
| 1 (Lab) | 250m | 256 MiB | 5 GiB |
| 3 (Production) | 500m | 512 MiB | 10-20 GiB |

### Operator

| Нагрузка | CPU | RAM |
|:---|:---|:---|
| < 100 целей | 100-200m | 128-256 MiB |
| 100-500 целей | 200-500m | 256-512 MiB |
| > 500 целей | 500m+ | 512 MiB+ |

---

## Практические сценарии

### Сценарий A: Production кластер (500K серий, 2000 целей)

```yaml
# Prometheus Server
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  shards: 2
  version: v3.12.0
  resources:
    requests:
      cpu: "2"
      memory: 8Gi
    limits:
      cpu: "4"
      memory: 16Gi
  retentionSize: 85GB
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 100Gi
  env:
    - name: GOMEMLIMIT
      value: "14GiB"
---
# Alertmanager
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: "1"
      memory: 1Gi
  storage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 20Gi
```

**Верификация размеров:**

```bash
# Проверка размера TSDB
kubectl exec -n monitoring prometheus-main-0 -- du -sh /prometheus

# Проверка количества активных серий
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series | jq .

# Проверка потребления RAM
kubectl top pod -n monitoring -l app.kubernetes.io/name=prometheus

# Прогноз роста серий на 7 дней
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- \
  'http://localhost:9090/api/v1/query?query=predict_linear(prometheus_tsdb_head_series[1h], 7*24*3600)' | jq .
```

### Сценарий B: Edge-кластер (10K серий, Agent Mode)

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: PrometheusAgent
metadata:
  name: edge-collector
  namespace: edge
spec:
  replicas: 1
  version: v3.12.0
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: "1"
      memory: 1Gi
  remoteWrite:
    - url: "http://central-lts:8428/api/v1/write"
  storage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 5Gi
```

### Сценарий C: Крупный кластер (3M серий, шарды + Thanos)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 2
  shards: 4
  version: v3.12.0
  resources:
    requests:
      cpu: "4"
      memory: 32Gi
    limits:
      cpu: "8"
      memory: 64Gi
  retentionSize: 200GB
  retention: 7d  # Локально, LTS через Thanos
  storage:
    volumeClaimTemplate:
      spec:
        storageClassName: fast-nvme
        resources:
          requests:
            storage: 250Gi
  thanos:
    version: v0.41.0
    objectStorageConfig:
      key: thanos.yaml
      name: thanos-objstore-config
  env:
    - name: GOMEMLIMIT
      value: "56GiB"
```

### Диагностика sizing

```bash
# 1. Проверка потребления ресурсов подами
kubectl top pods -n monitoring --sort-by=memory

# 2. Проверка лимитов и requests
kubectl get pods -n monitoring -o json | \
  jq '.items[] | {name: .metadata.name, requests: .spec.containers[0].resources.requests, limits: .spec.containers[0].resources.limits}'

# 3. Мониторинг потребления RAM через PromQL
# → RAM usage percentage:
container_memory_working_set_bytes{namespace="monitoring", container="prometheus"}
  / container_spec_memory_limit_bytes{namespace="monitoring", container="prometheus"} * 100

# 4. Мониторинг CPU throttling:
rate(container_cpu_cfs_throttled_seconds_total{namespace="monitoring"}[5m])
  / rate(container_cpu_usage_seconds_total{namespace="monitoring"}[5m]) * 100

# 5. Проверка размера PVC
kubectl get pvc -n monitoring -o custom-columns=\
  NAME:.metadata.name,SIZE:.spec.resources.requests.storage,USED:.status.capacity.storage

# 6. Прогноз заполнения диска (7 дней):
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 3600*24*7) < 0
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Высокая доступность](./high_availability.md) | Шардирование и репликация: `shards` vs `replicas` |
| [TSDB](../../../Prometheus/concepts/tsdb.md) | Внутренняя структура хранилища, compaction, WAL |
| [Sizing Overview](../../../Prometheus/scaling/overview.md) | Пороговые значения: comfort/warning/critical |
| [Rancher Capacity Planning](../../../../Kubernetes/Rancher/rancher_capacity_planning.md) | Формулы RAM/CPU для Rancher-сред |
| [Designing High-Load Monitoring](../../../../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md) | Методология проектирования: retention tiers, cost optimization |
| [Persistent Volumes](../Kube_Prometheus_Stack_Helm/practical_scenarios/persistent_volumes.md) | Рекомендуемые размеры PVC для KPS |

### Частые ошибки на собеседованиях

1. **"1M серий = 8 GB RAM"** — Нет. 1M серий требует 8-16 GB RAM (Head Block) + 4 GB overhead + 20-30% GC. Итого: 16-32 GB. Указывайте `GOMEMLIMIT`.
2. **"retentionSize = размер PVC"** — Нет. `retentionSize` должен быть на 10-15% меньше PVC, чтобы оставить место для WAL.
3. **"Шарды = реплики"** — Нет. Шарды делят цели скрейпинга (горизонтальное масштабирование). Реплики — избыточность внутри шарда (HA). Итого подов = shards × replicas.
4. **"Agent Mode не нуждается в диске"** — Нет. Agent использует WAL для буферизации при недоступности LTS. WAL требует SSD.
