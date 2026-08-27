# Capacity Planning для Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**Capacity Planning для Jaeger** — это процесс расчета требуемых вычислительных ресурсов (CPU, RAM, disk IOPS, сеть) и проектирования архитектуры хранилища под заданную нагрузку. От правильного sizing зависит стабильность сбора трейсов, скорость поиска в UI и стоимость владения (TCO). В 2026 году при нагрузках выше 10,000 spans/s без продуманного capacity planning система теряет данные и становится неинтерактивной.

Общий обзор системы: **[Обзор Jaeger](./jaeger_overview.md)**.
Архитектура и потоки данных: **[Архитектура Jaeger](./jaeger_architecture.md)**.
Развертывание: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Spans per second (spans/s)** | Количество спанов, генерируемых приложениями и поступающих в Collector в секунду. Основная единица нагрузки |
| **Retention (ретенция)** | Период хранения трейсов в хранилище (например, 7 дней, 30 дней). Определяет объем данных на диске |
| **Throughput** | Пропускная способность системы: сколько спанов в секунду может обработать Collector и записать Storage |
| **TCO (Total Cost of Ownership)** | Полная стоимость владения: лицензии, инфраструктура, операционные расходы |
| **Cardinality** | Количество уникальных комбинаций тегов/атрибутов (например, `user_id` с миллионами значений). Высокая cardinality взрывает индексы |
| **Hot / Warm / Cold storage** | Стратегия хранения: быстрые SSD для свежих данных (hot), дешевые диски для старых (cold) |
| **Backpressure** | Механизм обработки перегрузки; при превышении capacity спаны отбрасываются на уровне Collector |

---

## Базовые концепции

### Формула расчета объема хранения

Примерная формула для оценки размера хранилища:

```
Объем (GB) = (spans_per_day × avg_span_size × retention_days × replication_factor) / 1024^3
```

Где:
- `spans_per_day` = `spans_per_second × 86400`
- `avg_span_size` = средний размер спана в байтах (обычно 500–2000 байт)
- `retention_days` = период хранения
- `replication_factor` = 1 для ClickHouse (RF1 в v3 Tempo), 2–3 для Elasticsearch

**Пример:**
- Нагрузка: 5,000 spans/s
- Средний размер: 1,000 байт
- Ретенция: 7 дней
- Репликация: 1 (ClickHouse)

```
spans_per_day = 5,000 × 86,400 = 432,000,000
Объем = (432M × 1,000 × 7 × 1) / 1,073,741,824 ≈ 2.8 TB
```

### Формула sizing Collector

| Метрика | Формула | Пример |
| :--- | :--- | :--- |
| **CPU** | `spans_per_second × 0.002` (ядра) | 5,000 spans/s × 0.002 = 10 ядер (3–5 инстансов по 2–4 ядра) |
| **RAM** | `spans_per_second × 0.0005` (GB) + overhead spanmetrics | 5,000 × 0.0005 = 2.5 GB + 2 GB = 4.5 GB на инстанс |
| **Сеть** | `spans_per_second × avg_span_size × 8` (bps) | 5,000 × 1,000 × 8 = 40 Mbps входящего трафика |

**Важно:** При использовании `spanmetrics` или `tail_sampling` добавьте 30–50% к RAM из-за буферизации трейсов.

### Sizing ClickHouse для Jaeger

ClickHouse стал рекомендованным хранилищем для Jaeger v2 (first-class citizen с v2.20+).

| Параметр | Рекомендация |
| :--- | :--- |
| **Количество шардов** | 3+ для HA. При > 50M spans/день используйте 6+ шардов |
| **Реплики на шард** | 2 (RF=2) для production |
| **Диск** | NVMe SSD. Минимум 100 GB на шард, исходя из формулы выше |
| **RAM** | 4–8 GB на шард для кэширования MergeTree индексов |
| **CPU** | 4–8 ядер на шард (ClickHouse активно использует parallelization) |
| **TTL** | Настройте на уровне таблицы: `TTL createdAt + INTERVAL 7 DAY` |

### Sizing Elasticsearch для Jaeger

| Параметр | Рекомендация |
| :--- | :--- |
| **Количество мастре-нод** | 3 (обязательно для HA) |
| **Реплики** | 2 для production |
| **Диск** | SSD. Целевой размер шарда 20–50 GB |
| **RAM** | 16–32 GB на узел (50% от RAM отдайте под JVM heap, максимум 31 GB) |
| **CPU** | 8+ ядер для индексации |
| **Индексы** | Используйте ILM (Index Lifecycle Management) для ротации индексов |

### Sizing Kafka (Streaming-архитектура)

Kafka используется как буфер между Collector и Ingester для сглаживания пиков.

| Параметр | Рекомендация |
| :--- | :--- |
| **Партиции** | 6–12 для high-load. Формула: `max(продюсеры, консьюмеры) × 2` |
| **Retention** | 24–48 часов (достаточно для повторной обработки при сбое ClickHouse) |
| **Replication Factor** | 3 для production |
| **Диск** | 500 GB – 2 TB на брокер (зависит от throughput) |
| **CPU / RAM** | 4–8 ядер, 8–16 GB RAM на брокер |

---

## Практические сценарии

### Сценарий 1: Расчет ресурсов для стартапа (5,000 spans/s)

**Ситуация:** Новый проект, нагрузка 5,000 spans/s, retention 7 дней, бюджет ограничен.

**Расчет:**

```
spans_per_day = 5,000 × 86,400 = 432,000,000
Объем ClickHouse (RF=1) = 432M × 1,000 × 7 / 1,073,741,824 ≈ 2.8 TB
```

**Рекомендуемая архитектура:**

| Компонент | Ресурсы | Количество | Цель |
| :--- | :--- | :--- | :--- |
| **Collector (Deployment)** | 2 CPU / 4 GB RAM | 3 реплики | Обработка 5,000 spans/s |
| **Query** | 1 CPU / 2 GB RAM | 2 реплики | Обслуживание UI |
| **ClickHouse** | 4 CPU / 8 GB RAM / 200 GB NVMe | 3 шарда × 1 реплика = 3 узла | Хранение 2.8 TB |
| **Kafka** | 4 CPU / 8 GB RAM / 500 GB SSD | 3 брокера | Буфер на 24 часа |

**Стоимость (приблизительно):**
- ClickHouse ноды: 3 × $200/мес = $600
- Kafka брокеры: 3 × $150/мес = $450
- Collector + Query: 5 × $100/мес = $500
- **Итого:** ~$1,550/мес

### Сценарий 2: Расчет для enterprise (100,000 spans/s)

**Ситуация:** Крупный enterprise с 100,000 spans/s, retention 30 дней, требования к HA и безопасности.

**Расчет:**

```
spans_per_day = 100,000 × 86,400 = 8,640,000,000
Объем ClickHouse (RF=2) = 8.64B × 1,200 × 30 × 2 / 1,073,741,824 ≈ 576 TB
```

**Рекомендуемая архитектура:**

| Компонент | Ресурсы | Количество |
| :--- | :--- | :--- |
| **Collector** | 4 CPU / 8 GB RAM | 10+ реплик (HPA) |
| **Query** | 2 CPU / 4 GB RAM | 5+ реплик за LB |
| **ClickHouse** | 16 CPU / 32 GB RAM / 2 TB NVMe | 12 шардов × 2 реплики = 24 узла |
| **Kafka** | 8 CPU / 16 GB RAM / 2 TB SSD | 9 брокеров (9 партиций) |
| **Load Balancer** | — | HAProxy / Nginx перед Query |

**Стоимость (приблизительно):**
- ClickHouse: 24 × $800/мес = $19,200
- Kafka: 9 × $400/мес = $3,600
- Collector + Query: 15 × $200/мес = $3,000
- **Итого:** ~$25,800/мес

### Сценарий 3: Оценка impact high cardinality

**Ситуация:** В спанах появился атрибут `user_id` с миллионами уникальных значений. Необходимо оценить влияние на хранилище.

**Анализ:**

- **ClickHouse:** Каждый уникальный `user_id` добавляется в первичный ключ/индекс. При 10M уникальных значений размер индекса может вырасти на 10–20 GB, а скорость записи упасть на 20–40%.
- **Elasticsearch:** Каждый уникальный `user_id` создает отдельный терм в инвертированном индексе. Это приводит к "exploding index" и потреблению RAM на уровне Master-нод.

**Решение:**

1.  Агрегировать `user_id` до `customer_tier` (gold/silver/bronze).
2.  Использовать `spanmetrics` dimensions только по высокоуровневым атрибутам (`http.method`, `http.status_code`).
3.  Настроить `attributes` processor в OTel Collector для удаления/маскирования high-cardinality полей перед записью в хранилище.

### Сценарий 4: Мониторинг utilization и прогноз роста

**Ситуация:** Необходимо настроить мониторинг для раннего обнаружения исчерпания capacity.

**PromQL-запросы:**

```promql
# Utilization CPU Collector
rate(process_cpu_seconds_total{job="jaeger-collector"}[5m]) / count(up{job="jaeger-collector"}) * 100

# Utilization RAM Collector
container_memory_working_set_bytes{job="jaeger-collector"} / container_spec_memory_limit_bytes{job="jaeger-collector"} * 100

# Disk usage ClickHouse
100 - (node_filesystem_avail_bytes{mountpoint="/var/lib/clickhouse"} / node_filesystem_size_bytes{mountpoint="/var/lib/clickhouse"} * 100)

# Спаны dropped (backpressure)
rate(otelcol_processor_memory_limiter_refused_spans_total[5m])
```

**Алерты:**

```yaml
# CPU Collector > 80% на 5 минут
alert: JaegerCollectorHighCPU
expr: rate(process_cpu_seconds_total{job="jaeger-collector"}[5m]) > 0.8
for: 5m

# RAM Collector > 85%
alert: JaegerCollectorHighMemory
expr: container_memory_working_set_bytes{job="jaeger-collector"} / container_spec_memory_limit_bytes{job="jaeger-collector"} > 0.85
for: 5m

# ClickHouse disk > 75%
alert: JaegerClickHouseDiskUsage
expr: 100 - (node_filesystem_avail_bytes{mountpoint="/var/lib/clickhouse"} / node_filesystem_size_bytes{mountpoint="/var/lib/clickhouse"} * 100) > 75
for: 10m

# Spans dropped
alert: JaegerSpansDropped
expr: rate(otelcol_processor_memory_limiter_refused_spans_total[5m]) > 0
for: 2m
```

---

## Лучшие практики

1.  **Начинайте с 3 реплик Collector и 2 реплик Query:** Это минимальный HA для production.
2.  **Используйте ClickHouse с RF1 и S3:** При retention > 14 дней объектное хранилище снижает TCO в 2–3 раза по сравнению с Elasticsearch.
3.  **Ограничивайте cardinality:** Удаляйте high-cardinality атрибуты на уровне Collector, если они не нужны для поиска.
4.  **Настраивайте TTL:** Автоматическое удаление старых трейсов предотвращает неконтролируемый рост хранилища.
5.  **Используйте Kafka при пиковой нагрузке:** Если spikes превышают 2× среднюю нагрузку, добавьте Kafka буфер.
6.  **Мониторинг利用率:** Настройте алерты на CPU, RAM, disk и `spans_dropped_total` до наступления проблем.

---

## Очистка окружения

```bash
# Остановка Docker Compose
docker compose down -v

# Удаление данных ClickHouse
docker volume rm jaeger_clickhouse_data

# Удаление тестовых ресурсов Kubernetes
kubectl delete namespace jaeger-test
```

---

## Дополнительная информация

**Смежные темы:**

* Ресурсные требования: **[Архитектура Jaeger](./jaeger_architecture.md)**
* Хранилище и бэкенды: **[Обзор Jaeger](./jaeger_overview.md)**
* Storage Extension конфигурация: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
* Capacity Planning для Elasticsearch: **[Elasticsearch: Capacity Planning](../ELK_Stack/Elasticsearch/elasticsearch_capacity_planning.md)**

### См. также

* [ClickHouse Capacity Planning](https://clickhouse.com/docs/operations/server-configuration-parameters/settings#server-configuration-parameters)
* [Jaeger Production Deployment Guide](https://www.jaegertracing.io/docs/latest/deployment/)
