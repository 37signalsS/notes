# Кэширование в Grafana Loki: настройка и оптимизация

## Определения

**Chunk Cache (Кэш чанков)** — кэш сжатых блоков логов, размещаемый между Querier и объектным хранилищем. При повторном запросе к горячим данным Querier обращается к кэшу вместо S3/MinIO, что снижает задержку с секунд до миллисекунд. В Loki 3.x поддерживает embedded_cache (встроенный) или внешние бэкенды (Redis, Memcached).

**Index Cache (Кэш индекса)** — кэш фрагментов TSDB Index, хранящий результаты последних запросов к индексу. Ускоряет определение streams, соответствующих селектору. Эффективен при повторяющихся запросах с одинаковыми лейблами.

**Result Cache (Кэш результатов)** — кэш готовых результатов выполнения LogQL запросов в Query Frontend. При идентичном повторном запросе результат возвращается из кэша без обращения к Querier. Автоматически инвалидируется при появлении новых данных.

**Bloom Cache (Кэш Bloom-фильтров)** — кэш Bloom-фильтров в памяти Bloom Gateway. Позволяет быстро проверять наличие искомой строки в чанке без обращения к хранилищу. Ускоряет grep-подобные запросы в 10–50 раз.

**Embedded Cache (Встроенный кэш)** — кэш, работающий в процессе Loki без внешних зависимостей. Подходит для Single Binary и中小型 кластеров. Для production с высокой нагрузкой рекомендуется внешний бэкенд.

---

## Основные концепции

### Архитектура кэширования Loki

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Клиент    │────▶│  Query Frontend  │────▶│     Querier     │
│  (Grafana)  │     │  (Result Cache)  │     │                 │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                              ┌─────────────────────────┼─────────────────────────┐
                              │                         │                         │
                              ▼                         ▼                         ▼
                    ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
                    │   Index Cache    │     │   Chunk Cache    │     │   Bloom Cache    │
                    │ (Redis/Memcached)│     │ (Redis/Memcached)│     │  (Bloom Gateway) │
                    └──────────────────┘     └──────────────────┘     └──────────────────┘
                              │                         │                         │
                              ▼                         ▼                         ▼
                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                    Объектное хранилище (S3/MinIO/GCS)               │
                    └─────────────────────────────────────────────────────────────────────┘
```

### Когда кэширование критично

| Сценарий | Без кэша | С кэшем |
| :--- | :--- | :--- |
| Повторный запрос к тем же данным | Чтение из S3 (100–500ms) | Чтение из Redis (1–5ms) |
| Графики в Grafana с частым обновлением | Каждые N секунд обращение к S3 | Результат из кэша |
| Алерты с коротким interval | Многократные запросы к одному и тому же времени | Result Cache отдает мгновенно |
| Поиск по горячим данным (последние 2ч) | Ingester memory → S3 | Ingester memory → Chunk Cache → S3 |

### Выбор бэкенда кэша

| Бэкенд | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Embedded Cache** | Нулевая инфраструктура, простота | Ограничен RAM процесса, нет распределения | Single Binary, dev/test |
| **Redis** | Поддержка кластеризации, Pub/Sub, persistence | Выше потребление RAM, сложнее кластеризация | Production с HA |
| **Memcached** | Простота, горизонтальное масштабирование, низкое потребление RAM | Нет persistence, нет кластеризации (нужен client-side) | Production, простота |

**Рекомендация для production:** Memcached для Chunk Cache (крупные объекты, простое масштабирование) + Redis для Result Cache (требуется инвалидация и persistence).

### Кэширование в Loki 3.x: изменения

В Loki 3.x произошли изменения в конфигурации кэширования:
- **TSDB Index** заменил BoltDB Shipper — индекс теперь хранится в объектном хранилище, и кэш индекса работает иначе.
- **Bloom Gateway** использует собственный кэш Bloom-фильтров, независимый от Chunk/Index Cache.
- **Embedded cache** теперь доступен для всех типов кэша (не только chunk).

---

## Практические сценарии

### Сценарий 1: Embedded Cache (Single Binary / Dev)

Минимальная конфигурация без внешних зависимостей.

```yaml
# loki.yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

# Встроенный кэш чанков (работает в процессе Loki)
chunk_store_config:
  chunk_cache_config:
    embedded_cache:
      enabled: true
      max_size_mb: 512   # Максимальный размер кэша в MB

# Кэш результатов (встроенный)
query_range:
  results_cache:
    cache:
      embedded_cache:
        enabled: true
        max_size_mb: 256

limits_config:
  retention_period: 30d
  ingestion_rate_mb: 10
```

**Валидация:**

```bash
# Проверка размера кэша через метрики
curl -s http://localhost:3100/metrics | grep "loki_cache_"
# → loki_cache_chunk_memcached_hits_total 1234
# → loki_cache_chunk_memcached_misses_total 567
```

### Сценарий 2: Memcached для Chunk Cache (Production)

Развертывание Memcached через Kubernetes Deployment или Docker Compose.

**Memcached Deployment (Kubernetes):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memcached-chunks
  namespace: logging
spec:
  replicas: 3
  selector:
    matchLabels:
      app: memcached-chunks
  template:
    metadata:
      labels:
        app: memcached-chunks
    spec:
      containers:
        - name: memcached
          image: memcached:1.6-alpine
          ports:
            - containerPort: 11211
          command:
            - memcached
            - -m 2048          # 2GB RAM на инстанс
            - -c 4096           # Максимум соединений
            - -t 4              # Потоков
            - -I 5m             # Максимальный размер объекта (чанки Loki)
            - -n 512            # Минимальное количество слотов
          resources:
            requests:
              cpu: 500m
              memory: 2Gi
            limits:
              cpu: "1"
              memory: 2Gi
          readinessProbe:
            tcpSocket:
              port: 11211
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: 11211
            initialDelaySeconds: 15
            periodSeconds: 20
---
apiVersion: v1
kind: Service
metadata:
  name: memcached-chunks
  namespace: logging
spec:
  selector:
    app: memcached-chunks
  ports:
    - port: 11211
      targetPort: 11211
```

**Memcached Deployment (Docker Compose):**

```yaml
services:
  memcached-chunks:
    image: memcached:1.6-alpine
    container_name: memcached-chunks
    command: memcached -m 2048 -c 4096 -t 4 -I 5m
    ports:
      - "11211:11211"
    restart: always
    deploy:
      resources:
        limits:
          memory: 2G
```

**Конфигурация Loki для Memcached:**

```yaml
# loki.yaml
chunk_store_config:
  chunk_cache_config:
    memcached:
      memcached_client:
        hosts: dns+memcached-chunks.logging.svc.cluster.local:11211
        timeout: 500ms
        max_idle_conns: 16
        consistent_hash: true

# Для Docker Compose:
# hosts: dns+memcached-chunks:11211
```

**Валидация:**

```bash
# Проверка доступности Memcached
echo "stats" | nc memcached-chunks 11211 | grep -E "curr_items|bytes|curr_connections"

# Проверка попадания данных в кэш
curl -s http://localhost:3100/metrics | grep "loki_cache_chunk_memcached_hits"
# → Рост hits после запросов к логам
```

### Сценарий 3: Redis для Result Cache и Index Cache

Развертывание Redis с поддержкой кластеризации.

**Redis Deployment (Kubernetes):**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: logging
spec:
  replicas: 3
  serviceName: redis-headless
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          command:
            - redis-server
            - --maxmemory 1gb
            - --maxmemory-policy allkeys-lru
            - --save ""
            - --appendonly no
            - --tcp-backlog 511
          resources:
            requests:
              cpu: 250m
              memory: 1Gi
            limits:
              cpu: "1"
              memory: 1Gi
          readinessProbe:
            exec:
              command:
                - redis-cli
                - ping
            initialDelaySeconds: 5
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: redis
  namespace: logging
spec:
  selector:
    app: redis
  ports:
    - port: 6379
      targetPort: 6379
```

**Конфигурация Loki для Redis:**

```yaml
# loki.yaml

# Index Cache через Redis
storage_config:
  tsdb_shipper:
    active_index_directory: /loki/tsdb-index
    cache_location: /loki/tsdb-cache

index_cache:
  redis:
    endpoint: redis.logging.svc.cluster.local:6379
    timeout: 500ms
    db: 0

# Result Cache через Redis
query_range:
  results_cache:
    cache:
      redis:
        endpoint: redis.logging.svc.cluster.local:6379
        timeout: 500ms
        db: 1

# Chunk Cache через Memcached (или Redis)
chunk_store_config:
  chunk_cache_config:
    memcached:
      memcached_client:
        hosts: dns+memcached-chunks.logging.svc.cluster.local:11211
        timeout: 500ms
```

**Валидация:**

```bash
# Проверка Redis
redis-cli -h redis.logging.svc.cluster.local ping
# → PONG

# Проверка использования памяти
redis-cli -h redis.logging.svc.cluster.local info memory | grep used_memory_human
# → used_memory_human:256M

# Проверка попадания в кэш
redis-cli -h redis.logging.svc.cluster.local info stats | grep keyspace_hits
```

### Сценарий 4: Мониторинг эффективности кэша

**Ключевые метрики Loki для мониторинга кэша:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_cache_chunk_memcached_hits_total` | Успешные обращения к кэшу чанков | Рост пропорционально запросам |
| `loki_cache_chunk_memcached_misses_total` | Промахи кэша чанков | > hits → кэш неэффективен |
| `loki_cache_index_memcached_hits_total` | Успешные обращения к кэшу индекса | Рост пропорционально запросам |
| `loki_cache_result_memcached_hits_total` | Успешные обращения к кэшу результатов | Рост пропорционально запросам |
| `loki_cache_chunk_memcached_request_duration_seconds` | Время запроса к кэшу | P99 > 10ms → проблема |

**Расчет hit ratio:**

```logql
# Hit ratio для chunk cache за 5 минут
sum(rate(loki_cache_chunk_memcached_hits_total[5m]))
/
(sum(rate(loki_cache_chunk_memcached_hits_total[5m])) + sum(rate(loki_cache_chunk_memcached_misses_total[5m])))
# → Ожидается > 0.8 (80%) для эффективного кэша
```

**Прометеус-правила для алертинга:**

```yaml
groups:
  - name: loki-cache
    rules:
      - alert: LokiCacheHitRatioLow
        expr: |
          sum(rate(loki_cache_chunk_memcached_hits_total[5m]))
          / (sum(rate(loki_cache_chunk_memcached_hits_total[5m])) + sum(rate(loki_cache_chunk_memcached_misses_total[5m])))
          < 0.5
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Loki chunk cache hit ratio below 50%"
          description: "Cache hit ratio is {{ $value | humanizePercentage }}"

      - alert: LokiCacheLatencyHigh
        expr: histogram_quantile(0.99, rate(loki_cache_chunk_memcached_request_duration_seconds_bucket[5m])) > 0.01
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Loki cache P99 latency above 10ms"
```

**Dashboard в Grafana:**

```logql
# Panel: Cache Hit Ratio (Time Series)
sum by (name) (rate(loki_cache_chunk_memcached_hits_total[5m]))
/
(sum by (name) (rate(loki_cache_chunk_memcached_hits_total[5m])) + sum by (name) (rate(loki_cache_chunk_memcached_misses_total[5m])))

# Panel: Cache Request Latency (Heatmap)
rate(loki_cache_chunk_memcached_request_duration_seconds_bucket[5m])
```

### Сценарий 5: Полная production-конфигурация (Simple Scalable + Memcached + Redis)

```yaml
# loki.yaml (Simple Scalable mode)
auth_enabled: true

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

common:
  path_prefix: /loki
  storage:
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      bucketnames: loki-data
  replication_factor: 3
  ring:
    kvstore:
      store: memberlist

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: index_
        period: 24h

# Chunk Cache: Memcached
chunk_store_config:
  chunk_cache_config:
    memcached:
      memcached_client:
        hosts: dns+memcached-chunks.logging.svc.cluster.local:11211
        timeout: 500ms
        max_idle_conns: 32
        consistent_hash: true

# Index Cache: Redis
index_cache:
  redis:
    endpoint: redis.logging.svc.cluster.local:6379
    timeout: 500ms
    db: 0

# Result Cache: Redis
query_range:
  results_cache:
    cache:
      redis:
        endpoint: redis.logging.svc.cluster.local:6379
        timeout: 500ms
        db: 1
  split_queries_by_interval: 15m
  cache_results: true

limits_config:
  retention_period: 744h
  max_query_series: 5000
  allow_structured_metadata: true
  ingestion_rate_mb: 16
  ingestion_burst_size_mb: 32

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Низкий hit ratio (< 50%)** | Кэш слишком мал, данные не кэшируются | Увеличьте `max_size_mb` в embedded_cache или добавьте инстансы Memcached |
| **Высокая задержка кэша (P99 > 10ms)** | Перегрузка Memcached/Redis | Увеличьте количество инстансов, проверьте network latency |
| **Memcached OOM** | Недостаточно RAM | Увеличьте `-m` параметр Memcached |
| **Redis OOM** | Недостаточно RAM или нет eviction | Установите `maxmemory` и `maxmemory-policy allkeys-lru` |
| **Кэш не работает** | Неверный хост/порт | Проверьте DNS-резолвинг: `nslookup memcached-chunks.logging.svc.cluster.local` |
| **Дублирование данных в кэше** | memcached_client использует round-robin вместо consistent_hash | Включите `consistent_hash: true` |

---

## Дополнительная информация

### Рекомендации по размеру кэша

| Тип кэша | Минимум (Small) | Рекомендуется (Medium) | Высокая нагрузка (Large) |
| :--- | :--- | :--- | :--- |
| **Chunk Cache** | 512 MB | 2–4 GB | 8–16 GB |
| **Index Cache** | 256 MB | 1–2 GB | 4–8 GB |
| **Result Cache** | 128 MB | 512 MB – 1 GB | 2–4 GB |

### Лучшие практики

1. **Разделяйте кэши:** Chunk Cache на Memcached, Result/Index Cache на Redis — разные паттерны доступа.
2. **consistent_hash:** Всегда включайте для Memcached client — снижает miss при масштабировании.
3. **Мониторьте hit ratio:** Целевой показатель > 80%. Ниже — увеличивайте размер кэша.
4. **Не кэшируйте всё:** Hot data (последние 1–2 часа) и так в памяти инжестеров. Кэш нужен для warm data.
5. **Ресурсные лимиты:** Кэш не должен потреблять > 50% RAM ноды.
6. **Версионирование:** Используйте фиксированные теги образов Memcached/Redis.
7. **Network:** Размещайте кэш в том же namespace/network, что и Loki — минимизируйте задержку.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-чарты и конфигурация
- [Оптимизация LGTM стека](../Kubernetes/Installation/LGTM_Stack/lgtm_performance_tuning.md) — общие принципы производительности
