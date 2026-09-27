# Bloom Filters в Grafana Loki: практическое руководство

## Определения

**Bloom Filter (Бloom-фильтр)** — вероятностная структура данных, используемая Loki для быстрой проверки наличия искомой строки в чанке логов без обращения к объектному хранилищу. Bloom-фильтры не дают ложных отрицаний (false negatives), но могут давать ложные положительные (false positives). Это позволяет отфильтровать большинство чанков, не содержащих искомый паттерн, что ускоряет grep-подобные запросы в 10–50 раз.

**Bloom Gateway (Шлюз Bloom-фильтров)** — компонент Loki, индексирующий Bloom-фильтры и обрабатывающий запросы на проверку наличия строк. Работает как микросервис, развернутый отдельно от Read/Write компонентов. Использует встроенный кэш для ускорения повторных запросов.

**Bloom Block (Блок Bloom-фильтра)** — файл, содержащий Bloom-фильтры для一组 чанков. Блоки хранятся в объектном хранилище (S3/GCS) и кэшируются в памяти Bloom Gateway. Каждый блок покрывает определенный временной диапазон.

**Bloom Key Prefix (Префикс ключа Bloom)** — префикс, определяющий какой Bloom Gateway обрабатывает запрос. Используется для маршрутизации запросов к правильному инстансу. По умолчанию `v1`.

**Target Group Size (Размер целевой группы)** — количество чанков, покрываемых одним Bloom-блоком. Влияет на размер блока и эффективность фильтрации. По умолчанию 1000 чанков.

---

## Основные концепции

### Архитектура Bloom Filters в Loki

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│   Клиент        │────▶│  Query Frontend  │────▶│    Bloom Gateway    │
│   (Grafana)     │     │                  │     │  (Bloom-фильтры)   │
└─────────────────┘     └──────────────────┘     └─────────┬───────────┘
                                                           │
                                                           ▼
                                                   ┌──────────────────┐
                                                   │    Querier       │
                                                   │ (запрос к S3     │
                                                   │  для подходящих  │
                                                   │  чанков)         │
                                                   └─────────┬────────┘
                                                             │
                                                             ▼
                                                   ┌──────────────────┐
                                                   │  S3/GCS          │
                                                   │  (чанки логов)   │
                                                   └──────────────────┘
```

### Как Bloom Filter ускоряет запросы

1. Клиент отправляет LogQL запрос с grep-паттерном: `{app="nginx"} |= "error"`
2. Query Frontend передает запрос в Bloom Gateway
3. Bloom Gateway проверяет Bloom-фильтры для каждого чанка, покрывающего временной диапазон запроса
4. **Большинство чанков отфильтрованы** (не содержат "error") — к ним не обращаемся
5. Querier обращается только к чанкам, прошедшим фильтрацию
6. Результат возвращается клиенту

### Паттерны, ускоряемые Bloom Filters

| Паттерн | Ускорение | Пример |
| :--- | :--- | :--- |
| `|= "keyword"` | Высокое (10–50x) | `|= "OutOfMemory"` |
| `|~ "regex"` | Высокое (10–50x) | `\|~ "error\|warn"` |
| `!= "keyword"` | Высокое (10–50x) | `!= "DEBUG"` |
| `{app="nginx"}` | Не ускоряется | Только label selector |
| `\| json \| status >= 500` | Не ускоряется | После JSON parsing |

### Когда Bloom Filters критичны

| Сценарий | Без Bloom | С Bloom |
| :--- | :--- | :--- |
| Поиск "error" в 1 ТБ логов за 24ч | Все чанки → S3 (10–30 сек) | 5% чанков → S3 (0.5–1.5 сек) |
| Поиск редкого паттерна в терабайтах | Полный scan всех чанков | 0.1–1% чанков → S3 |
| Алерт на `|= "FATAL"` за сутки | Все чанки → S3 | 1–5% чанков → S3 |
| Запрос без grep (только labels) | Индекс → S3 | Индекс → S3 (без изменений) |

### Выбор конфигурации

| Параметр | Минимальный | Рекомендуемый | Высокая нагрузка |
| :--- | :--- | :--- | :--- |
| `enabled` | false | true | true |
| `ingester` replicas | 1 | 2 | 3 |
| `query_scheduler` replicas | 1 | 2 | 3 |
| `cache` | inmemory | inmemory | memcached |
| `target_group_size` | 1000 | 1000 | 500–1000 |

---

## Практические сценарии

### Сценарий 1: Включение Bloom Filters (Simple Scalable)

```yaml
# loki.yaml (Simple Scalable mode)
auth_enabled: true

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

limits_config:
  retention_period: 30d
  ingestion_rate_mb: 16

# Bloom Gateway конфигурация
bloom_gateway:
  enabled: true
  address: dns+bloom-gateway.logging.svc.cluster.local:9095
  # Кэш Bloom-блоков
  cache:
    inmemory:
      enabled: true
      max_size_mb: 512
  # Target group size — количество чанков на блок
  target_group_size: 1000

# Bloom Block Builder
bloom_block_builder:
  enabled: true
  target_group_size: 1000
  # Интервал построения блоков
  block_builder_interval: 1h

# Query Frontend: маршрутизация через Bloom Gateway
query_frontend:
  max_body_size: 15728640  # 15 MB для больших запросов
```

**Helm-values для Bloom Gateway (Kubernetes):**

```yaml
# loki-values.yaml
bloomGateway:
  enabled: true
  replicas: 2
  resources:
    requests:
      cpu: 1
      memory: 4Gi
    limits:
      cpu: 2
      memory: 8Gi
  persistence:
    enabled: true
    size: 50Gi

bloomBlockBuilder:
  enabled: true
  replicas: 1
  resources:
    requests:
      cpu: 500m
      memory: 2Gi
    limits:
      cpu: 1
      memory: 4Gi
  persistence:
    enabled: true
    size: 100Gi
```

### Сценарий 2: Bloom Filters с Memcached (Production)

```yaml
# loki.yaml
bloom_gateway:
  enabled: true
  address: dns+bloom-gateway.logging.svc.cluster.local:9095
  cache:
    memcached:
      memcached_client:
        hosts: dns+memcached-bloom.logging.svc.cluster.local:11211
        timeout: 500ms
        consistent_hash: true
  target_group_size: 1000

bloom_block_builder:
  enabled: true
  target_group_size: 1000
  block_builder_interval: 1h
```

**Memcached для Bloom Cache:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memcached-bloom
  namespace: logging
spec:
  replicas: 2
  selector:
    matchLabels:
      app: memcached-bloom
  template:
    metadata:
      labels:
        app: memcached-bloom
    spec:
      containers:
        - name: memcached
          image: memcached:1.6-alpine
          ports:
            - containerPort: 11211
          command:
            - memcached
            - -m 1024
            - -c 2048
            - -I 1m
          resources:
            requests:
              cpu: 250m
              memory: 1Gi
            limits:
              cpu: 500m
              memory: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: memcached-bloom
  namespace: logging
spec:
  selector:
    app: memcached-bloom
  ports:
    - port: 11211
      targetPort: 11211
```

### Сценарий 3: Мониторинг Bloom Gateway

**Ключевые метрики:**

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_bloom_gateway_queries_total` | Количество запросов к Bloom Gateway | Рост пропорционально запросам |
| `loki_bloom_gateway_query_duration_seconds` | Время обработки запроса | P99 > 100ms → проблема |
| `loki_bloom_gateway_blocks_queried_total` | Количество проверенных блоков | Рост выше запросов → много блоков |
| `loki_bloom_gateway_blocks_filtered_total` | Количество отфильтрованных блоков | Должно быть > 90% от checked |
| `loki_bloom_cache_hits_total` | Попадания в кэш Bloom | Рост пропорционально запросам |
| `loki_bloom_cache_misses_total` | Промахи кэша Bloom | > 50% от misses → увеличьте кэш |

**Прометеус-правила:**

```yaml
groups:
  - name: loki-bloom
    rules:
      - alert: LokiBloomGatewayHighLatency
        expr: |
          histogram_quantile(0.99, rate(loki_bloom_gateway_query_duration_seconds_bucket[5m])) > 0.1
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Bloom Gateway P99 latency above 100ms"
          description: "Current latency: {{ $value | humanizeDuration }}"

      - alert: LokiBloomFilterEfficiencyLow
        expr: |
          rate(loki_bloom_gateway_blocks_filtered_total[5m])
          / rate(loki_bloom_gateway_blocks_queried_total[5m])
          < 0.5
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Bloom filter filtering less than 50% of blocks"
          description: "Efficiency: {{ $value | humanizePercentage }}"

      - alert: LokiBloomGatewayUnhealthy
        expr: |
          up{job="bloom-gateway"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Bloom Gateway instance is down"
```

**Dashboard в Grafana:**

```logql
# Panel: Bloom Gateway Query Latency (Heatmap)
rate(loki_bloom_gateway_query_duration_seconds_bucket[5m])

# Panel: Bloom Filter Efficiency (Gauge)
sum(rate(loki_bloom_gateway_blocks_filtered_total[5m]))
/ sum(rate(loki_bloom_gateway_blocks_queried_total[5m]))

# Panel: Bloom Cache Hit Ratio (Time Series)
sum(rate(loki_bloom_cache_hits_total[5m]))
/ (sum(rate(loki_bloom_cache_hits_total[5m])) + sum(rate(loki_bloom_cache_misses_total[5m])))
```

### Сценарий 4: Отключение Bloom Filters (если не нужны)

Если вы не используете grep-паттерны и не хотите额外 overhead:

```yaml
bloom_gateway:
  enabled: false

bloom_block_builder:
  enabled: false
```

**Когда можно отключить:**
- Только label-based запросы (бgrep grep)
- Малый объем логов (< 100 ГБ/день)
- Ресурсы ограничены

### Сценарий 5: Тюнинг Bloom Filters

**Оптимизация target_group_size:**

| Размер группы | Размер блока | Фильтрация | Рекомендация |
| :--- | :--- | :--- | :--- |
| 500 | ~2 МБ | Лучшая фильтрация | Малый объем логов |
| 1000 | ~4 МБ | Хорошая фильтрация | По умолчанию, рекомендуется |
| 2000 | ~8 МБ | Средняя фильтрация | Большой объем, ресурсы ограничены |
| 5000 | ~20 МБ | Худшая фильтрация | Не рекомендуется |

```yaml
# Оптимизация для разных сценариев

# Сценарий 1: Малый объем логов, лучшая фильтрация
bloom_gateway:
  target_group_size: 500

# Сценарий 2: По умолчанию
bloom_gateway:
  target_group_size: 1000

# Сценарий 3: Большой объем, ресурсы ограничены
bloom_gateway:
  target_group_size: 2000
```

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Bloom Gateway не запускается** | Нет доступа к хранилищу для блоков | Проверьте права доступа к S3/GCS, bucket для Bloom блоков |
| **Высокая задержка Bloom Gateway** | Много блоков для проверки | Увеличьте `target_group_size`, добавьте кэш |
| **Low filter efficiency (< 50%)** | Данные содержат много искомых паттерн | Нормально для highly-matching данных; Bloom не эффективен для "шумных" данных |
| **Bloom Gateway OOM** | Слишком большой кэш | Увеличьте RAM, уменьшите `max_size_mb` кэша |
| **Блоки не создаются** | `bloom_block_builder` отключен | Включите `bloom_block_builder.enabled: true` |
| **Высокая стоимость S3** | Bloom блоки хранятся в S3 | Уменьшите `target_group_size`, настройте lifecycle policies |
| **Bloom filters не ускоряют запросы** | Запросы не содержат grep | Bloom filters работают только для `|=`, `|~`, `!=` паттернов |

---

## Дополнительная информация

### Лучшие практики

1. **Включайте Bloom Filters при grep-запросах:** Если вы часто используете `|= "keyword"` или `|~ "regex"`, Bloom Filters значительно ускорят запросы.
2. **Используйте Memcached для кэша:** Для production с высокой нагрузкой Memcached эффективнее inmemory кэша.
3. **Мониторьте filter efficiency:** Целевой показатель > 80%. Ниже — проверьте данные или увеличьте `target_group_size`.
4. **Не включайте Bloom Filters без нужды:** Если запросы только по labels, Bloom Adds overhead без benefits.
5. **Размещайте Bloom Gateway в том же cluster:** Минимизируйте network latency между Bloom Gateway и Querier.
6. **Регулярно проверяйте метрики:** `loki_bloom_gateway_blocks_filtered_total` должен расти пропорционально запросам.
7. **Используйте фиксированные теги образов:** Для воспроизводимости развертывания.

### См. также

- [Обзор Grafana Loki](./loki_overview.md) — архитектура и жизненный цикл данных
- [Эффективный LogQL](./loki_stack_setup/logql_examples.md) — продвинутые паттерны LogQL
- [Установка Loki в Kubernetes](./loki_stack_setup/loki_installation.md) — Helm-конфигурация
- [Оптимизация LGTM стека](../Kubernetes/Installation/LGTM_Stack/lgtm_performance_tuning.md) — общие принципы производительности
