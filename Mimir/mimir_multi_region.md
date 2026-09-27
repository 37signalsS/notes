# Mimir: Multi-Region и Zone-Aware Deployment

## 1. Определения

**Multi-Region Deployment** — развертывание Mimir-кластера в нескольких географических регионах для обеспечения отказоустойчивости при авариях на уровне дата-центра. Zone Awareness — механизм распределения реплик Ingester по зонам доступности (AZ) внутри одного региона.

**Зачем:** Географическое распределение защищает от:
- Аварий на уровне дата-центра (пожар, отключение электроэнергии)
- Сетевых partitions между зонами
- Плановых работ в одном из регионов

## 2. Теоретический блок

### Архитектура multi-region Mimir

```
Region A                          Region B
┌─────────────────────┐          ┌─────────────────────┐
│ Distributor (3)     │          │ Distributor (3)     │
│ Ingester AZ-1 (3)  │←─Kafka──→│ Ingester AZ-1 (3)  │
│ Ingester AZ-2 (3)  │  bridge  │ Ingester AZ-2 (3)  │
│ Querier (5)        │          │ Querier (5)        │
│ Store-Gateway (3)  │          │ Store-Gateway (3)  │
│ Compactor (1)      │          │ Compactor (1)      │
└────────┬───────────┘          └────────┬───────────┘
         │                               │
         └──────────┬────────────────────┘
                    │
            ┌───────▼───────┐
            │  S3/MinIO     │  (общий бакет)
            │  (Region C)   │
            └───────────────┘
```

### Zone Awareness

Zone Awareness распределяет реплики Ingester по зонам доступности:
- Каждая зона содержит равное количество реплик
- При аварии одной зоны данные остаются доступными в других зонах
- Репликация происходит между зонами (не внутри)

### Режимы работы

| Режим | Описание | Использование |
|-------|----------|---------------|
| **Single Region, Zone Awareness** | Один регион, несколько AZ | Средние кластеры |
| **Multi-Region, Active-Active** | Оба региона обрабатывают запись и чтение | Высокая доступность |
| **Multi-Region, Active-Passive** | Один регион активен, второй standby | Disaster Recovery |
| **Multi-Cluster** | Независимые кластеры с shared storage | Максимальная изоляция |

## 3. Практический блок

### Zone Awareness (один регион)

```yaml
# mimir-config.yaml
mimir:
  structuredConfig:
    ingester:
      ring:
        zone_awareness_enabled: true
        zone_awareness_max_zones: 3
        replication_factor: 3

    # Каждый Ingester знает свою зону
    # (настраивается через переменную окружения или hostname)
```

```yaml
# Kubernetes: назначение зон через topologySpreadConstraints
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mimir-ingester
spec:
  replicas: 6  # 2 зоны × 3 реплики
  template:
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/component: ingester
```

### Multi-Region: Active-Active

```yaml
# Region A config
mimir:
  structuredConfig:
    ingester:
      ring:
        zone_awareness_enabled: true
        replication_factor: 3
        # Реплики распределяются по зонам A1, A2, B1
        # (B1 — зона из другого региона)
```

**Сетевая связность:**
```bash
# Требуется L3 connectivity между регионами (VPC Peering, VPN, dedicated links)
# Минимальная пропускная способность: 1 Gbps
# Задержка: < 5ms между регионами (для Zone Awareness)
# Для Active-Active: < 50ms (Kafka replication)
```

### Kafka Bridge между регионами

```properties
# Kafka bridge: репликация топиков между регионами
# Region A → Region B

# mirrormaker2 конфигурация
clusters = region-a, region-b
region-a.bootstrap.servers = kafka-a.region-a.svc:9092
region-b.bootstrap.servers = kafka-b.region-b.svc:9092

# Репликация топика mimir-ingest
replication.policy.class = org.apache.kafka.connect.mirror.IdentityReplicationPolicy
topics = mimir-ingest
```

### Multi-Region: Active-Passive (DR)

```yaml
# Region A (Active)
mimir:
  structuredConfig:
    ingester:
      ring:
        replication_factor: 3
        zone_awareness_enabled: true

# Region B (Passive) — только чтение
mimir:
  structuredConfig:
    querier:
      # Читает из общего S3
      store_gateway:
        addresses: ["store-gateway.region-b.svc:9095"]
```

**Переключение при аварии:**
```bash
# 1. Остановить запись в Region A
# 2. Убедиться, что все данные flushed в S3
kubectl exec -n mimir deploy/mimir-ingester -- \
  curl -s http://localhost:8080/ingester/flush

# 3. Переключить Prometheus/Alloy на Region B
# prometheus.yml:
# remote_write:
#   - url: "http://mimir-distributor.region-b:8080/api/v1/push"

# 4. Переключить Grafana на Region B
# grafana-datasources.yaml:
#   url: http://mimir-query-frontend.region-b:9009/prometheus
```

### Общий S3-бакет

```yaml
# Все регионы пишут в один S3-бакет
# MinIO: настройка репликации между кластерами

# Region A
mc alias set region-a http://minio.region-a:9000 mimir <secret>
mc mirror --watch --overwrite region-a/mimir-blocks region-b/mimir-blocks

# Region B (зеркало)
mc alias set region-b http://minio.region-b:9000 mimir <secret>
```

### Мониторинг multi-region кластера

```yaml
groups:
  - name: mimir_multi_region
    rules:
      # Лаг Kafka bridge
      - alert: KafkaBridgeLagHigh
        expr: kafka_consumer_group_lag > 1000
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Kafka bridge: высокий lag между регионами"

      # Задержка репликации данных
      - alert: CrossRegionDataDelay
        expr: time() - max(mimir_ingester_tsdb_head_max_time) > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Mimir: данные в разных регионах не синхронизированы"
```

## 4. Дополнительная информация

### См. также
- [Mimir: Обзор](./mimir_overview.md) — архитектура и Zone Awareness
- [Rolling Restart](./mimir_overview.md#6-rolling-restart-компонентов) — процедуры рестарта
- [Security Hardening](./mimir_security_hardening.md) — безопасность в multi-region среде
- [High Availability](../Concepts/High_Availability/) — общие концепции HA

### Официальные ресурсы
- **[Mimir Zone Awareness](https://grafana.com/docs/mimir/latest/configure/configure-zone-aware-replication/)** — настройка Zone Awareness
- **[Mimir Multi-Cluster](https://grafana.com/docs/mimir/latest/manage/monitoring-multi-cluster/)** — мультикластерная эксплуатация
