# Performance Tuning Wazuh: оптимизация, EPS, capacity planning

## Определения

**EPS (Events Per Second)** — количество событий, обрабатываемых Wazuh Manager в секунду. Ключевая метрика производительности. Типичные значения: 500–5000 EPS для средних сред, 10k+ для крупных.

**Backpressure** — механизм динамического ограничения входящего потока данных при перегрузке индексатора. При активации Wazuh замедляет приём событий, предотвращая потерю данных.

**Queue Latency** — задержка обработки события от момента поступления в движок до индексации. Норма: <100ms. Критично: >500ms.

**Wazuh-Engine** — аналитическое ядро (C++), обрабатывающее события. В 5.0+ интегрировано в процесс индексатора. Потребляет CPU и RAM пропорционально EPS.

**ISM (Index State Management)** — автоматическое управление жизненным циклом индексов OpenSearch: hot → warm → cold → delete. Влияет на диск и производительность запросов.

**Shard** — минимальная единица хранения в OpenSearch. Оптимальный размер шарда: 10–50 GB. Слишком много мелких шардов = overhead, слишком большие = проблемы с балансировкой.

## Основные концепции

### Архитектура производительности

```
Агенты (1000+)
    │
    ▼ TCP 1514
┌───────────────────┐
│   Wazuh Manager   │
│  ┌──────────────┐ │
│  │ Queue Buffer │ │  ← RAM bottleneck
│  └──────┬───────┘ │
│         ▼         │
│  ┌──────────────┐ │
│  │ Wazuh-Engine │ │  ← CPU bottleneck
│  │ (correlation)│ │
│  └──────┬───────┘ │
│         ▼         │
│  ┌──────────────┐ │
│  │ Integrations │ │  ← I/O bottleneck
│  └──────────────┘ │
└────────┬──────────┘
         │
         ▼ TCP 9200
┌───────────────────┐
│  Wazuh Indexer    │
│  (OpenSearch 3.x) │  ← Disk/RAM bottleneck
└───────────────────┘
```

### Ключевые метрики

| Метрика | Норма | Опасность | Действие |
|:---|:---|:---|:---|
| **EPS** | <5000 | >10000 | Масштабирование Engine/Indexer |
| **Queue Latency** | <100ms | >500ms | Оптимизация правил, CPU |
| **CPU Usage** | <70% | >90% | Scale-up или分流 |
| **RAM Usage** | <80% | >90% | Увеличение RAM |
| **Disk IOPS** | <50% capacity | >80% | Переход на NVMe |
| **Disk Usage** | <70% | >85% | ISM policies, cleanup |
| **Backpressure** | false | true | Throttling источников |
| **Agent Disconnect** | <1% | >5% | Проверка сети |

## Практические сценарии

### 1. Бенчмаркинг EPS

```bash
#!/bin/bash
# Измерение текущего EPS через API
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Получение метрик за последние 5 минут
curl -sk "$API/manager/metrics?section=engine" \
  -H "Authorization: Bearer $TOKEN" | \
  jq '{
    events_processed: .data.events.processed_total,
    events_per_second: .data.events.eps,
    queue_latency_ms: .data.queue.latency_avg,
    queue_size: .data.queue.current_size,
    backpressure: .data.backpressure.active
  }'
```

### 2. Оптимизация Wazuh-Engine

```bash
# Проверка использования CPU движком
ps -p $(pgrep -f wazuh-engine) -o pid,pcpu,pmem,vsz,rss --no-headers

# Оптимизация через wazuh.yaml
cat >> /var/wazuh-manager/etc/wazuh.yaml << 'EOF'
engine:
  workers: 8                    # Количество worker-процессов (= CPU cores)
  queue:
    size: 10000                 # Размер входной очереди
    batch_size: 500             # Размер батча для обработки
  rules:
    cache_size: 10000           # Кэш скомпилированных правил
    reload_interval: 300        # Перечитывание правил (сек)
EOF

# Перезапуск
systemctl restart wazuh-manager
```

### 3. Оптимизация OpenSearch Indexer

```yaml
# /etc/wazuh-indexer/opensearch.yml
# Оптимизация для производительности

# Кластер
cluster.name: wazuh-indexer-cluster
node.name: ${HOSTNAME}
node.roles: [master, data, ingest]

# Сетевые настройки
network.host: 0.0.0.0
transport.host: 0.0.0.0
discovery.seed_hosts: ["indexer-1", "indexer-2", "indexer-3"]
cluster.initial_master_nodes: ["indexer-1", "indexer-2", "indexer-3"]

# Оптимизация JVM
# /etc/wazuh-indexer/jvm.options
-Xms16g    # 50% от RAM (максимум 32GB)
-Xmx16g

# Оптимизация индексации
indices.memory.index_buffer_size: 20%
thread_pool.write.queue_size: 1000
thread_pool.write.size: 8

# Дисковая подсистема
path.data: /var/wazuh-indexer/data
path.logs: /var/wazuh-indexer/logs
```

### 4. ISM Policy для автоматической ротации

```bash
# Создание ISM policy через API
curl -sk -X PUT "https://localhost:9200/_plugins/_ism/policies/wazuh_lifecycle" \
  -H "Content-Type: application/json" \
  -u admin:admin -d '{
  "policy": {
    "description": "Wazuh index lifecycle: hot → warm → cold → delete",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_primary_shard_size": "30gb",
              "min_index_age": "1d"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "shrink": {
              "number_of_shards": 1
            }
          },
          {
            "force_merge": {
              "max_num_segments": 1
            }
          }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "freeze": {}
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "90d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "delete": {}
          }
        ]
      }
    ]
  }
}'
```

### 5. Оптимизация правил для производительности

```xml
<!-- ПЛОХО: тяжёлый regex на каждое событие -->
<rule id="100100" level="5">
  <decoded_as>json</decoded_as>
  <regex>(?i)(error|fail|critical|fatal|panic)</regex>
</rule>

<!-- ХОРОШО: prematch + простой regex -->
<rule id="100101" level="0" noalert="1">
  <decoded_as>json</decoded_as>
  <prematch>"level":</prematch>
</rule>
<rule id="100102" level="5">
  <if_sid>100101</if_sid>
  <field name="level">error|critical|fatal</field>
</rule>

<!-- ЕЩЁ ЛУЧШЕ: CDB-список вместо regex для IP -->
<rule id="100103" level="10">
  <if_sid>100102</if_sid>
  <list field="srcip" lookup="match_key">etc/lists/known-bad-ips</list>
  <description>Event from known bad IP</description>
</rule>
```

### 6. Capacity Planning

```python
#!/usr/bin/env python3
"""Расчёт требований к ресурсам Wazuh."""
import json

def calculate_resources(agents, avg_events_per_agent_per_min, retention_days):
    # EPS
    total_events_per_min = agents * avg_events_per_agent_per_min
    eps = total_events_per_min / 60

    # Disk (Full Visibility: ~500 bytes/event)
    daily_events = total_events_per_min * 60 * 24
    daily_gb = (daily_events * 500) / (1024**3)
    total_disk_gb = daily_gb * retention_days * 1.2  # 20% overhead

    # Manager RAM (rule of thumb: 4GB per 5000 EPS)
    manager_ram_gb = max(12, (eps / 5000) * 4)

    # Indexer RAM (rule of thumb: 16GB per 10k EPS)
    indexer_ram_gb = max(16, (eps / 10000) * 16)

    # Indexer nodes (1 node per 32GB RAM)
    indexer_nodes = max(3, int(indexer_ram_gb / 32) + 1)

    return {
        "eps": round(eps),
        "daily_events": f"{daily_events:,.0f}",
        "daily_disk_gb": round(daily_gb, 1),
        "total_disk_gb": round(total_disk_gb),
        "manager_ram_gb": round(manager_ram_gb),
        "indexer_ram_gb_per_node": round(indexer_ram_gb / indexer_nodes),
        "indexer_nodes": indexer_nodes,
        "manager_cpu_cores": max(4, int(eps / 1000) * 2)
    }

# Пример: 500 агентов, 10 событий/мин на агент, 90 дней retention
result = calculate_resources(agents=500, avg_events_per_agent_per_min=10, retention_days=90)
print(json.dumps(result, indent=2))
```

### 7. Мониторинг производительности

```bash
#!/bin/bash
# Ежедневный отчёт о производительности

echo "=== Wazuh Performance Report ==="
echo "Date: $(date)"
echo ""

# EPS из логов
echo "--- Events Processed (last 24h) ---"
grep -c "Event processed" /var/wazuh-manager/logs/wazuh.log 2>/dev/null || echo "N/A"

# Размер очереди
echo "--- Queue Status ---"
/var/wazuh-manager/bin/wazuh-control status | grep -i queue

# Disk usage
echo "--- Disk Usage ---"
df -h /var/wazuh-indexer/data 2>/dev/null

# OpenSearch индексы
echo "--- Index Size ---"
curl -sk "https://localhost:9200/_cat/indices/wazuh-*?v&h=index,docs.count,store.size" -u admin:admin

# Агенты
echo "--- Agent Status ---"
curl -sk "https://localhost:55000/agents/summary" \
  -H "Authorization: Bearer $(curl -sk -X POST 'https://localhost:55000/security/user/authenticate' -d '{"username":"admin","password":"admin"}' | jq -r '.data.token')" | \
  jq '.data'
```

### 8. Оптимизация disk I/O для Indexer

```bash
# Настройка I/O scheduler (NVMe)
echo "none" > /sys/block/nvme0n1/queue/scheduler

# Увеличение dirty ratio
sysctl -w vm.dirty_ratio=40
sysctl -w vm.dirty_background_ratio=10

# Оптимизация файловой системы
# Для ext4:
mount -o noatime,nodiratime,barrier=0 /dev/nvme0n1p1 /var/wazuh-indexer/data

# Для XFS (рекомендуется):
mount -o noatime,nodiratime,logbufs=8 /dev/nvme0n1p1 /var/wazuh-indexer/data
```

## Дополнительная информация

### Rules of thumb для sizing

| Параметр | Формула |
|:---|:---|
| **EPS** | agents × events_per_agent_per_min / 60 |
| **Manager RAM** | 4 GB × (EPS / 5000), мин. 12 GB |
| **Indexer RAM** | 16 GB × (EPS / 10000), мин. 16 GB |
| **Indexer nodes** | RAM_total / 32, мин. 3 |
| **Disk/day** | EPS × 500 bytes × 86400 / 1024^3 |
| **Shard size** | 10–50 GB, оптимально 20–30 GB |
| **CPU Manager** | cores = EPS / 1000, мин. 4 |

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **EPS падает** | Indexer перегружен | Проверьте disk watermark, добавьте ноды |
| **Queue latency растёт** | Много regex-правил | Переведите в CDB-списки, используйте `<prematch>` |
| **Backpressure активен** | Индексатор не успевает | Очистите старые индексы, увеличьте replication |
| **High CPU on Manager** | Слишком много правил | Оптимизируйте правила, отключите неиспользуемые |
| **Disk заполняется** | Нет ISM policy | Настройте hot/warm/cold/delete |
| **Agent disconnects** | Сеть или ресурсы Manager | Проверьте `ss -tlnp`, `top`, `iostat` |

### Best Practices

1. **Начните с бенчмарка**: измерьте реальный EPS перед оптимизацией.
2. **CDB вместо regex**: для 100+ проверяемых значений используйте CDB-списки (O(1) vs O(n)).
3. **prematch перед regex**: сначала простой поиск подстроки, потом regex.
4. **ISM обязателен**: без него диск заполнится за дни.
5. **NVMe для Indexer**: HDD = катастрофа для IOPS.
6. **Мониторьте Golden Signals**: events rate, queue latency, disk watermark, KVDB latency, backpressure.
7. **Тестируйте изменения**: новые правила сначала на 1% агентов.

### См. также
- [Развертывание Wazuh](./deployment.md) — hardware requirements.
- [Health Monitoring](./wazuh-health-monitoring.md) — Golden Signals и метрики.
- [Правила](./wazuh-rules.md) — оптимизация правил.
