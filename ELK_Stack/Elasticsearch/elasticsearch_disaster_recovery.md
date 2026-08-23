# Disaster Recovery Patterns

> Руководство по паттернам аварийного восстановления для Elastic Stack. Рассматриваются RPO/RTO, multi-site replication и snapshot strategies.
>
> Связанные темы: CCR/CCS — [Cross-Cluster](./elasticsearch_ccr_ccs.md); бэкапы — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md).

## Определения

* **RPO (Recovery Point Objective)** — максимально допустимая потеря данных (время).
* **RTO (Recovery Time Objective)** — максимально допустимое время восстановления.
* **Disaster Recovery (DR)** — процедуры восстановления после катастрофического сбоя.
* **Multi-Site Replication** — репликация данных между дата-центрами.
* **Failover** — автоматическое или ручное переключение на резервный кластер.
* **Failback** — возврат на основной кластер после восстановления.
* **Snapshot** — полный или инкрементальный бэкап данных.
* **Searchable Snapshot** — восстановленный снапшот, доступный для поиска.

## Стратегии DR

### 1. Active-Passive (Cold Standby)

```
Active Cluster (Site A)          Passive Cluster (Site B)
├── Receives all traffic         ├── Idle (or minimal)
├── Writes to local storage      ├── Receives replicated data
└── Healthy                      └── On standby

RPO: Minutes (replication lag)
RTO: Hours (manual failover)
```

### 2. Active-Passive (Warm Standby)

```
Active Cluster (Site A)          Passive Cluster (Site B)
├── Receives all traffic         ├── Ready to accept traffic
├── Writes to local storage      ├── Has recent data
└── Healthy                      └── DNS switch on failure

RPO: Seconds to minutes
RTO: Minutes to hours
```

### 3. Active-Active (Multi-Site)

```
Site A                           Site B
├── Receives traffic (US)        ├── Receives traffic (EU)
├── Writes to local storage      ├── Writes to local storage
└── Replicates to Site B        └── Replicates to Site A

RPO: Seconds (async replication)
RTO: Seconds (automatic failover)
```

## Snapshot-Based DR

### Snapshot Lifecycle Management (SLM)

```bash
# Настройка snapshot repository
PUT _snapshot/my-repo
{
  "type": "fs",
  "settings": {
    "location": "/mnt/backup",
    "compress": true,
    "max_snapshot_bytes_per_sec": "40mb",
    "max_restore_bytes_per_sec": "40mb"
  }
}

# SLM Policy
PUT _slm/policy/daily-snapshots
{
  "schedule": "0 30 1 * * ?",
  "name": "<daily-snap-{now/d}>",
  "repository": "my-repo",
  "config": {
    "indices": ["logs-*", "metrics-*"],
    "include_global_state": true,
    "ignore_unavailable": true
  },
  "retention": {
    "expire_after": "30d",
    "min_count": 5,
    "max_count": 50
  }
}
```

### SLM для DR

```bash
PUT _slm/policy/dr-snapshots
{
  "schedule": "0 */4 * * * ?",  # Every 4 hours
  "name": "<dr-snap-{now}>",
  "repository": "my-repo",
  "config": {
    "indices": ["*"],
    "include_global_state": false
  },
  "retention": {
    "expire_after": "7d",
    "min_count": 10,
    "max_count": 100
  }
}
```

### Восстановление из снапшота

```bash
# Восстановление всех индексов
POST _snapshot/my-repo/daily-snap-2026.08.23/_restore
{
  "indices": "*",
  "include_global_state": true,
  "rename_pattern": "(.+)",
  "rename_replacement": "$1-restored"
}

# Восстановление конкретного индекса
POST _snapshot/my-repo/daily-snap-2026.08.23/_restore
{
  "indices": "logs-2026.08",
  "include_global_state": false
}
```

## Cross-Cluster Replication (CCR) для DR

### Настройка Leader-Follower

```bash
# Leader Cluster (Active)
PUT _ccr/auto_follow/dr-follower
{
  "remote_cluster": "dr-cluster",
  "leader_index_patterns": ["critical-*"],
  "follow_index_pattern": "{{leader_index}}"
}

# Восстановление после катастрофы
# 1. Promote follower to read-write
POST critical-index/_ccr/pause_follow
POST critical-index/_doc
{
  "_meta": {
    "promoted": true
  }
}
```

### CCR DR Strategy

```
Normal Operation:
  Active Cluster ──CCR──▶ DR Cluster (read-only)
  Writes go to Active   Receives replicated data

Disaster (Active Cluster Down):
  Active Cluster (DOWN)  DR Cluster (promoted to read-write)
                          1. Pause follow
                          2. Accept writes
                          3. Become primary

Recovery:
  Active Cluster (restored from DR)
  Re-establish CCR in reverse direction
```

## Multi-Site Deployment

### Architecture

```
                    ┌─────────────────┐
                    │   Global DNS    │
                    │ (Route 53/etc)  │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
   ┌──────────┐       ┌──────────┐       ┌──────────┐
   │ Site A   │       │ Site B   │       │ Site C   │
   │ (US)     │◀─────▶│ (EU)     │◀─────▶│ (APAC)   │
   └──────────┘  CCR  └──────────┘  CCR  └──────────┘
```

### DNS Failover

```yaml
# Route 53 health check example
HealthCheck:
  Type: HTTPS
  ResourcePath: /_cluster/health
  Port: 443
  RequestInterval: 30
  FailureThreshold: 3

RecordSet:
  Name: elasticsearch.company.com
  Type: A
  SetIdentifier: site-a
  Failover: PRIMARY
  HealthCheckId: site-a-health
```

## RPO/RTO по стратегиям

| Стратегия | RPO | RTO | Cost | Complexity |
|-----------|-----|-----|------|------------|
| Daily Snapshot | 24h | Hours | Low | Low |
| 4-hour Snapshot | 4h | Hours | Low-Medium | Low |
| CCR (async) | Seconds-Minutes | Minutes | High | Medium |
| Active-Active | Seconds | Seconds | Very High | High |
| Snapshot + CCR | Seconds | Minutes | High | High |

## Searchable Snapshots для DR

### Frozen Tier

```yaml
# elasticsearch.yml
xpack.searchable.snapshot.shared_cache.size: 20%
```

### Восстановление как Searchable Snapshot

```bash
POST _snapshot/my-repo/daily-snap-2026.08.23/_restore
{
  "indices": "logs-*",
  "rename_pattern": "(.+)",
  "rename_replacement": "$1-restored",
  "index_settings": {
    "index.number_of_replicas": 0
  },
  "ignore_index_settings": ["index.refresh_interval"]
}
```

### Когда использовать Searchable Snapshots

- Long-term compliance storage
- Archive search capability
- Cost-effective DR for cold data

## Testing DR

### DR Drill Process

```
1. Select DR strategy to test
2. Simulate primary site failure
3. Execute failover procedure
4. Verify data integrity
5. Verify application connectivity
6. Measure RTO
7. Failback to primary
8. Document results
```

### Automated DR Testing

```bash
# Health check script
#!/bin/bash
CLUSTER_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" \
  https://active-cluster:9200/_cluster/health)

if [ "$CLUSTER_HEALTH" != "200" ]; then
  # Trigger failover
  curl -X POST "https://dr-cluster:9200/_ccr/pause_follow"
  # Update DNS
  aws route53 change-resource-record-sets ...
fi
```

## Best Practices

### Snapshots

1. **Automate with SLM** — не полагайтесь на ручные бэкапы
2. **Test restores regularly** — бэкап бесполезен если не восстанавливается
3. **Off-site storage** — S3/GCS/Azure для защиты от site failure
4. **Retention policy** — баланс между cost и recovery needs
5. **Include global state** — templates, ILM policies, security settings

### CCR для DR

1. **Monitor replication lag** — алертите на >1000 ops
2. **Auto-follow patterns** — автоматическая репликация новых индексов
3. **Promote procedure** — документируйте шаги failover
4. **Network bandwidth** — учитывайте latency между сайтами

### General

1. **Document DR procedures** — runbook для каждого сценария
2. **Regular DR drills** — минимум раз в квартал
3. **Measure RTO/RPO** — валидируйте в реальных условиях
4. **Automate failover** — где возможно для снижения RTO
5. **Cross-team coordination** — DBA, network, application teams

## Common DR Scenarios

### Scenario 1: Single Node Failure

```
Impact: Minimal (replicas handle reads)
Action: Replace node, cluster self-heals
RPO: 0 (replicas available)
RTO: Minutes (node replacement)
```

### Scenario 2: Site Failure

```
Impact: Complete loss of one site
Action: Failover to DR site
RPO: Depends on replication strategy
RTO: Minutes to hours
```

### Scenario 3: Data Corruption

```
Impact: Bad data in primary cluster
Action: Restore from snapshot before corruption
RPO: Time since last good snapshot
RTO: Hours (restore + replay)
```

### Scenario 4: Split Brain

```
Impact: Two clusters think they're primary
Action: Quorum-based resolution, manual intervention
RPO: Possible data divergence
RTO: Hours (reconciliation)
```

## Cost Optimization для DR

### Tiered DR Strategy

```
Tier 1 (Critical):
  - CCR (async)
  - RPO: seconds
  - RTO: minutes

Tier 2 (Important):
  - 4-hour snapshots
  - RPO: 4h
  - RTO: hours

Tier 3 (Archive):
  - Daily snapshots
  - RPO: 24h
  - RTO: day(s)
```

### Storage Costs

- **Hot DR** (CCR): 2x storage cost
- **Warm DR** (frequent snapshots): 1.5x storage
- **Cold DR** (daily snapshots): minimal cost
- **Searchable snapshots**: cheaper than hot, more expensive than cold

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера.
* **[Cross-Cluster Replication и Search](./elasticsearch_ccr_ccs.md)** — CCR для DR.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — SLM для бэкапов.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов.
* **[Upgrades и миграция](./elasticsearch_upgrades.md)** — процедуры обновления.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — безопасность данных.
