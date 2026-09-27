# Оптимизация затрат на мониторинг

## Определения

**Cost Optimization Prometheus Operator** — стратегии минимизации TCO (Total Cost of Ownership) стека мониторинга в Kubernetes без ущерба для надежности и полноты покрытия. Включает оптимизацию кардинальности, дифференцированный scrape_interval, выбор retention policies, правильный sizing и использование Agent Mode для edge-кластеров.

**Cardinality (Кардинальность)** — количество уникальных временных рядов (series), создаваемых одной метрикой. Каждая уникальная комбинация лейблов образует отдельную серию. Высокая кардинальность — основная причина роста потребления RAM и размера TSDB.

**Downsampling** — уменьшение разрешения данных во времени (например, с 15-секундного на 5-минутное). Снижает размер хранилища в 20 раз при retention >30 дней.

**Cost per Series** — условная стоимость хранения одной активной серии в TSDB. Зависит от retention и hardware: при retention 30 дней и SSD ~$0.001-0.005/серию/месяц.

> **Смотрите также:** [Расчет ресурсов](./resource_sizing.md) — формулы RAM/CPU/Disk; [Agent Mode](../../../Prometheus/concepts/agent_mode.md); [Labels & Cardinality](../../../Prometheus/concepts/labels_and_cardinality.md).

---

## Базовые концепции

### Факторы стоимости

| Фактор | Влияние | Оптимизация |
|:---|:---|:---|
| **Количество серий** | Прямое (RAM, Disk, CPU) | Удаление неиспользуемых метрик, ограничение лейблов |
| **scrape_interval** | Пропорциональное (данные) | Дифференцированный: 15s критичные, 60s фоновые |
| **retention** | Экспоненциальное (Disk) | 7-14 дней локально, LTS для长期 |
| **Количество шардов** | Линейное (Pod'ы) | Правильный расчет по активным сериям |
| **Agent vs Server** | 30-40% экономия RAM/CPU | Agent для edge и forwarding-only сценариев |

### Формула TCO

```
TCO_месяц = CPU_cost + RAM_cost + Disk_cost + Network_cost

Где:
  CPU_cost = shards × replicas × CPU_per_pod × price_per_core
  RAM_cost = shards × replicas × RAM_per_pod × price_per_GiB
  Disk_cost = PVC_size × price_per_GiB
  Network_cost = egress_GB × price_per_GB (для remote_write)
```

---

## Практические сценарии

### Оптимизация 1: Удаление неиспользуемых метрик

```yaml
# В Prometheus CRD или ServiceMonitor: отсечь шумные метрики
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  additionalScrapeConfigs:
    - job_name: 'kubernetes-pods'
      metric_relabel_configs:
        # Удалить метрики Go runtime (высокая кардинальность)
        - action: drop
          regex: "go_.*"
          sourceLabels: [__name__]
        # Удалить метрики kube_proxy (не нужны в большинстве случаев)
        - action: drop
          regex: "kube_proxy_.*"
          sourceLabels: [__name__]
        # Удалить контейнерные метрики с пустым именем
        - action: drop
          regex: ""
          sourceLabels: [container]
        # Оставить только key-метрики для подов
        - action: keep
          regex: "container_(cpu|memory|network|fs)_.*"
          sourceLabels: [__name__]
```

### Оптимизация 2: Дифференцированный scrape_interval

```yaml
# Вместо единого scrape_interval=15s для всех целей:
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: critical-apps
spec:
  endpoints:
    - port: metrics
      interval: 15s  # Критичные приложения
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: background-apps
spec:
  endpoints:
    - port: metrics
      interval: 60s  # Фоновые сервисы (cron jobs, batch)
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: infrastructure
spec:
  endpoints:
    - port: metrics
      interval: 30s  # Инфраструктурные компоненты
```

### Оптимизация 3: Agent Mode для edge-кластеров

```yaml
# Вместо полного Prometheus Server на edge:
apiVersion: monitoring.coreos.com/v1alpha1
kind: PrometheusAgent
metadata:
  name: edge-collector
  namespace: edge
spec:
  replicas: 1
  resources:
    requests:
      cpu: 250m      # Вместо 1-2 cores для Server
      memory: 512Mi  # Вместо 4-8 GiB для Server
  remoteWrite:
    - url: "http://central-lts:8428/api/v1/write"
```

**Экономия:** 30-40% CPU, 50-70% RAM, отсутствие TSDB-диска.

### Оптимизация 4: Retention sizing

```yaml
# Правило: retentionSize = 85% от PVC
spec:
  retentionSize: 85GB  # При PVC 100Gi
  storage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 100Gi
```

**Рекомендации по retention:**

| Сценарий | Локальный retention | LTS retention |
|:---|:---|:---|
| Dev/Test | 1-3 дня | Не нужен |
| Production (базовый) | 7-14 дней | 30-90 дней |
| Production (compliance) | 7-14 дней | 90-365 дней |

### Оптимизация 5: Шарды vs Реплики

```
# Неправильно: 1 шард, 4 реплики → 4 пода, каждый скрейпит ВСЕ цели
# Правильно: 2 шарда, 2 реплики → 4 пода, каждый скрейпит ПОЛОВИНУ целей
```

| Конфигурация | Подов | Нагрузка на каждый | RAM на каждый |
|:---|:---|:---|:---|
| 1 shard × 4 replicas | 4 | 100% целей | 16 GiB |
| 2 shards × 2 replicas | 4 | 50% целей | 8 GiB |

Итого: при одинаковом количестве подов правильное шардирование снижает потребление RAM в 2 раза.

### Оптимизация 6: Управление кардинальностью

```yaml
# В ScrapeConfig: ограничение количества лейблов
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: high-cardinality-app
spec:
  staticConfigs:
    - targets: ["app:9090"]
  metricRelabelConfigs:
    # Удалить лейбл user_id (высокая кардинальность)
    - action: labeldrop
      regex: "user_id"
    # Удалить лейбл request_id (уникальный на каждый запрос)
    - action: labeldrop
      regex: "request_id"
    # Оставить только агрегированные метрики
    - action: keep
      regex: "http_requests_total|http_request_duration_seconds"
      sourceLabels: [__name__]
```

### Оптимизация 7: Запись только нужных метрик в LTS

```yaml
# В remoteWrite: отфильтровать метрики перед отправкой в LTS
spec:
  remoteWrite:
    - url: "http://victoria-metrics:8428/api/v1/write"
      writeRelabelConfigs:
        # Отправить только критичные метрики
        - action: keep
          regex: "up|container_cpu_.*|container_memory_.*|kube_node_status_condition.*"
          sourceLabels: [__name__]
        # Или удалить фоновые
        - action: drop
          regex: "go_.*|process_.*"
          sourceLabels: [__name__]
```

### Мониторинг стоимости

```yaml
# Алерт на рост кардинальности
groups:
  - name: cost-monitoring
    rules:
      - alert: CardinalityExplosion
        expr: prometheus_tsdb_head_series > 1000000
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Кардинальность >1M серий"

      - alert: TSDBDiskGrowing
        expr: predict_linear(prometheus_tsdb_storage_blocks_bytes[6h], 7*24*3600) > 100*1024*1024*1024
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "TSDB вырастет до 100GB через 7 дней"

      - alert: RemoteWriteDroppedSamples
        expr: increase(prometheus_remote_storage_dropped_samples_total[1h]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Теряются сэмплы при remote_write"
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [Расчет ресурсов](./resource_sizing.md) | Формулы RAM/CPU/Disk |
| [Agent Mode](../../../Prometheus/concepts/agent_mode.md) | 30-40% экономия ресурсов |
| [Labels & Cardinality](../../../Prometheus/concepts/labels_and_cardinality.md) | Влияние лейблов на производительность |
| [Remote Write](../../../Prometheus/scaling/remote_read_write.md) | queueConfig, write_relabel_configs |
| [TSDB](../../../Prometheus/concepts/tsdb.md) | Retention mechanics, compaction |
| [Cost Optimization Overview](../../../../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md) | Методология: storage tiering, ROI |

### Частые ошибки на собеседованиях

1. **"Мониторинг не стоит денег"** — Нет. Каждый Prometheus с 1M серий требует 16-32 GB RAM + 100 GB SSD. В облаке это $200-500/месяц только на один инстанс.
2. **"scrape_interval=15s для всех — нормально"** — Нет. Для фоновых сервисов 60s снижает стоимость хранения в 4 раза без потери полноты.
3. **"Agent Mode не имеет смысла в production"** — Нет. Agent экономит 30-40% ресурсов на edge-кластерах, где не нужен локальный TSDB.
