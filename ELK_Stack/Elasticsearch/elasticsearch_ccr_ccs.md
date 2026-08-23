# Cross-Cluster Replication и Cross-Cluster Search

> Руководство по межкластерной репликации данных (CCR) и поиску через кластеры (CCS). Рассматриваются use cases, настройка, API и паттерны для DR и geo-distributed search.
>
> Связанные темы: capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md).

## Определения

* **Cross-Cluster Replication (CCR)** — асинхронная репликация индексов из leader-кластера в follower-кластер. Обеспечивает DR и размещение данных ближе к пользователям.
* **Cross-Cluster Search (CCS)** — выполнение поисковых запросов через несколько кластеров прозрачно для клиента.
* **Leader Cluster** — кластер-источник данных для CCR. Только один на индекс.
* **Follower Cluster** — кластер-приемник реплицируемых данных. Индекс follower read-only.
* **API Key Authentication** — механизм аутентификации между кластерами для CCS/CCR.
* **Remote Cluster** — конфигурация подключения к удаленному кластеру (на уровне кластера).

## Архитектура CCR

### Модель Leader-Follower

```
┌─────────────────┐         ┌─────────────────┐
│  Leader Cluster │  CCR    │ Follower Cluster│
│  (us-east)      │────────▶│ (eu-west)       │
│                 │  async  │                 │
│  index: logs-*  │         │ index: logs-*   │
│  read-write     │         │ read-only       │
└─────────────────┘         └─────────────────┘
```

### Поток данных

```
Leader Cluster                         Follower Cluster
┌──────────┐    Auto-follow Pattern    ┌──────────┐
│ Index A  │ ────────────────────────▶ │ Index A  │
│ Index B  │ ────────────────────────▶ │ Index B  │
│ Index C  │ ────────────────────────▶ │ Index C  │
└──────────┘                           └──────────┘
        │
        ▼
   New Index D  ──auto followed──▶      Index D
```

## Архитектура CCS

### Прозрачный поиск через кластеры

```
                    ┌─────────────────┐
                    │   Application   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Local Cluster   │  (координирующий)
                    │ (us-east)       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ us-east    │  │ eu-west    │  │ ap-south   │
     │ (local)    │  │ (remote)   │  │ (remote)   │
     └────────────┘  └────────────┘  └────────────┘
```

## Настройка Remote Cluster

### Через elasticsearch.yml (статическая)

```yaml
# На каждом узле кластера
search.remote.cluster.seeds:
  - us-east-es-node1:9300
  - us-east-es-node2:9300
  - us-east-es-node3:9300
```

### Через API (динамическая, рекомендуется)

```bash
# На принимающем кластере (eu-west)
PUT _cluster/settings
{
  "persistent": {
    "cluster.remote.us-east.seeds": [
      "us-east-es-node1:9300",
      "us-east-es-node2:9300",
      "us-east-es-node3:9300"
    ],
    "cluster.remote.us-east.transport.ping_schedule": "30s"
  }
}

# Проверка соединения
GET _remote/info
```

## Cross-Cluster Search (CCS)

### Синтаксс запроса

```bash
# Поиск в remote кластере
GET us-east:logs-*/_search
{
  "query": {
    "match": { "message": "error" }
  }
}

# Агрегация через кластеры
GET logs-*/_search
{
  "size": 0,
  "aggs": {
    "by_cluster": {
      "terms": {
        "field": "_index",
        "size": 10
      }
    }
  }
}
```

### CCS с частичным поиском

```bash
GET logs-*/_search?allow_partial_search_results=false
{
  "query": { "match_all": {} }
}
```

### Приоритет и preference

```bash
# Предпочитать локальный кластер для снижения latency
GET logs-*/_search?preference=_local
```

## Cross-Cluster Replication (CCR)

### Настройка Leader Cluster

```bash
# Создание API ключа для follower
POST /_security/api_key
{
  "name": "ccr-follower-key",
  "access": {
    "replication": ["logs-*"]
  },
  "expiration": "7d"
}
```

### Настройка Follower Cluster

```bash
# Регистрация leader-кластера с API key
PUT _ccr/connection/us-east
{
  "leader_cluster": "us-east",
  "api_key": "<id>:<api_key>"
}
```

### Создание Follower Index

```bash
POST _ccr/follow
{
  "leader_index": "logs-2026.08",
  "remote_cluster": "us-east",
  "read_only_allow_delete": false
}
```

### Auto-follow Patterns

```bash
# Автоматическая репликация всех индексов, соответствующих паттерну
PUT _ccr/auto_follow/us-east
{
  "remote_cluster": "us-east",
  "leader_index_patterns": ["logs-*"],
  "follow_index_pattern": "{{leader_index}}",
  "settings": {
    "index.number_of_replicas": 1
  }
}
```

## Use Cases

### 1. Disaster Recovery (DR)

```
Leader (active)          Follower (DR site)
     │                        │
     │  Continuous sync       │
     └───────────────────────▶│
                              │
     Site down!               │
                              │
     X                        ▼
                         Promote to read-write
```

**RPO:** Секунды-минуты (зависит от задержки сети и объема данных)
**RTO:** Минуты (ручное или автоматическое переключение)

### 2. Geo-distributed Search

```
User in EU ──▶ eu-west cluster ──▶ Local data (fast)
                    │
                    └──▶ CCS to us-east, ap-south for global view
```

Снижает latency для региональных пользователей при сохранении возможности глобального поиска.

### 3. Data Locality (GDPR)

```
EU Data ──▶ eu-west cluster (stays in EU)
US Data ──▶ us-east cluster (stays in US)
```

Данные не покидают юрисдикцию, но возможен ограниченный глобальный поиск.

### 4. Hub-and-Spoke Architecture

```
                    ┌────────────┐
                    │ Hub Cluster│ (аналитика)
                    └─────┬──────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
   ┌──────────┐    ┌──────────┐    ┌──────────┐
   │ Spoke 1  │    │ Spoke 2  │    │ Spoke 3  │
   │ (prod)   │    │ (staging)│    │ (dev)    │
   └──────────┘    └──────────┘    └──────────┘
```

## Мониторинг CCR

```bash
# Статус follower индексов
GET _ccr/stats

# Детали конкретного follower
GET _ccr/stats/follower

# Leader stats
GET _ccr/stats/leader
```

Ключевые метрики:
- `follower_global_checkpoint` — последний примененный чекпоинт
- `leader_global_checkpoint` — текущий чекпоинт leader
- `number_of_outstanding_read_requests` — отставание
- `operations_read` — количество прочитанных операций

## API Key для CCS/CCR

### Создание API Key с ограничениями

```bash
POST /_security/api_key
{
  "name": "ccs-api-key",
  "role_descriptors": {
    "ccs-role": {
      "cluster": ["cross_cluster_search"],
      "index": [
        {
          "names": ["logs-*"],
          "privileges": ["read", "read_cross_cluster"]
        }
      ]
    }
  },
  "expiration": "1d",
  "metadata": {
    "purpose": "cross-cluster-search",
    "environment": "production"
  }
}
```

### Использование API Key в запросе

```bash
curl -H "Authorization: ApiKey <base64_encoded>" \
  "https://eu-west-es:9200/us-east:logs-*/_search"
```

## Best Practices

1. **API Key rotation** — регулярно обновляйте ключи, используйте короткий expiration
2. **Network latency** — CCR чувствителен к latency между кластерами. <50ms для синхронной реплики, <200ms для async
3. **Bandwidth** — оцените объем данных в секунду, чтобы избежать перегрузки сети
4. **Security** — TLS обязателен для межкластерного трафика
5. **Monitoring** — алертите на отставание CCR (lag > 1000 ops)
6. **Leader limit** — follower может следовать только за одним leader на индекс
7. **Index settings** — follower наследует settings от leader, можно переопределить (replicas, shards)

## Ограничения

- **CCR:** follower индекс read-only (только для чтения)
- **CCR:** нельзя реплицировать system indices (.security, .kibana)
- **CCR:** auto-follow работает только для новых индексов
- **CCS:** агрегации могут быть неточными при `allow_partial_search_results=true`
- **CCS:** wildcard в имени кластера не поддерживается (нужно указать явно)
- **Версии:** кластеры должны быть совместимы (обычно ±1 major version)

## См. также

* **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура кластера, шардинг.
* **[Capacity Planning](./elasticsearch_capacity_planning.md)** — планирование ресурсов для multi-cluster.
* **[Security Advanced](./elasticsearch_security_advanced.md)** — API Keys для CCR/CCS.
* **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — паттерны DR с использованием CCR.
* **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты для межкластерного взаимодействия.
* **[ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — управление жизненным циклом.
