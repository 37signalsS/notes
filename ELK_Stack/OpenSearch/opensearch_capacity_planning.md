# OpenSearch: Capacity Planning и проектирование кластера

> Заметка посвящена расчету параметров кластера OpenSearch: размера шардов, числа узлов, объемов диска, heap и пропускной способности. Базовые понятия (шарды, роли узлов, data tiers) описаны в [обзоре OpenSearch](./opensearch_overview.md); ISM — в [жизненном цикле индексов (ISM)](./opensearch_ism_lifecycle.md).

## Определения

* **Capacity Planning (Планирование мощностей)** — процесс определения количества узлов, дискового пространства, RAM и CPU для стабильной работы кластера под projected нагрузку.
* **Shard Sizing (Размер шардов)** — целевой объем данных на одном первичном шарде. Влияет на скорость индексации, восстановление и нагрузку на Cluster Manager.
* **Hot-Warm Architecture** — разделение узлов по ролям хранения: `hot` (NVMe/SSD, активная запись), `warm` (HDD/бюджетный SSD, редкий поиск), `cold` (объектное хранилище, архив).
* **Oversharding (Избыточное шардирование)** — создание слишком большого числа шардов относительно объема данных и heap. Приводит к замедлению публикации состояния кластера и восстановления.
* **JVM Heap** — память JVM OpenSearch. Максимум ~31 ГБ (Compressed OOPs). Вторая половина RAM остается под Lucene page cache.
* **Page Cache (Кэш страниц ОС)** — неиспользуемая RAM для кэширования файлов Lucene. От размера page cache напрямую зависит скорость поиска.
* **Segment Replication (SegRep)** — репликация готовых сегментов Lucene с primary на реплики. Снижает CPU-нагрузку на data-узлах, но увеличивает сетевой трафик.
* **Remote-Backed Storage (RBS)** — хранение сегментов в объектном хранилище (S3/GCS). Отделяет вычисления от хранения, ускоряет восстановление узлов.
* **Write amplification (Усиление записи)** — коэффициент, показывающий, сколько байт записано на диск относительно исходного объема. Высокое значение — признак неоптимальных настроек merge.
* **max_shards_per_node** — лимит шардов на data-узел. До 2.15 включительно: 1000. С 2.17+: до 4000 (1000 на каждые 16 ГБ heap).

## Основные концепции

### Правило размера шардов

| Тип данных | Целевой размер | Максимальный |
| :--- | :--- | :--- |
| Логи / метрики | 30–50 ГБ | 100 ГБ |
| Поисковые индексы | 20–30 ГБ | 50 ГБ |
| Векторные индексы | 10–20 ГБ | 50 ГБ |

### Правило heap и RAM

```
Heap = 50% физической RAM, но не более 31 ГБ
Оставшаяся RAM → page cache Lucene
```

| RAM сервера | JVM Heap | Page Cache |
| :--- | :--- | :--- |
| 16 ГБ | 8 ГБ | 8 ГБ |
| 32 ГБ | 16 ГБ | 16 ГБ |
| 64 ГБ | 31 ГБ | 33 ГБ |
| 128 ГБ | 31 ГБ | 97 ГБ |

### Правило шардов на узел

OpenSearch 2.17+:

```
Шардов на узел = MIN(1000 на 16 ГБ heap, 4000 максимум)
Консервативный ориентир: 20–25 шардов на 1 ГБ heap
```

Пример:

* 16 ГБ heap → 320–400 шардов максимум
* 31 ГБ heap → 620–775 шардов максимум
* 8 ГБ heap → 160–200 шардов максимум

### Формула расчета

```
Общее число шардов = (Объем данных / Целевой размер шарда) × Количество реплик
Число узлов = Общее число шардов / Шардов на узел
```

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export OS="https://localhost:9200"
export PASS="<пароль пользователя admin>"
curl -ku admin:$PASS "$OS"   # → {"name" : "opensearch-dev", ..., "tagline" : "The OpenSearch Project"}
```

### 1. Расчет кластера для логов приложения

Сценарий: 3 приложения, 50 ГБ логов/день, retention 30 дней.

```bash
# 1. Общий объем
# 50 ГБ/день × 30 дней = 1500 ГБ
# С overhead × 1.3 → ~2 ТБ

# 2. Число шардов
# 2 ТБ / 50 ГБ = 40 (с overhead ~35 первичных)
# С 1 репликой → 70 шардов

# 3. Число узлов
# 70 / 25 (на узел 16 ГБ heap) ≈ 3
# С запасом: 5 узлов (3 hot + 2 warm)
```

```json
{
  "policy": {
    "states": [
      {
        "name": "hot",
        "actions": [
          { "rollover": { "min_primary_shard_size": "30gb", "min_index_age": "1d" } }
        ],
        "transitions": [{ "state_name": "warm" }]
      },
      {
        "name": "warm",
        "actions": [
          { "replica_count": { "number_of_replicas": 1 } },
          { "force_merge": { "max_num_segments": 1 } },
          { "read_only": {} }
        ],
        "transitions": [{ "state_name": "delete", "conditions": { "min_index_age": "30d" } }]
      },
      {
        "name": "delete",
        "actions": [{ "delete": {} }]
      }
    ],
    "ism_template": {
      "index_patterns": ["logs-prod-*"],
      "priority": 10
    }
  }
}
```

### 2. Расчет кластера для метрик (TSDB)

Сценарий: 1000 хостов, 100 метрик каждые 15 секунд, retention 90 дней.

```bash
# 1. Объем
# 1000 × 100 метрик × 4 измерения/час × 24 часа × 90 дней
# ≈ 864 000 000 документов

# 2. С downsampling
# Детальные (7 дней): ~100 ГБ
# Downsampled 1h (83 дня): ~30 ГБ
# Итого: ~130 ГБ

# 3. Шарды
# 130 ГБ / 30 ГБ = 5 шардов (с запасом)
```

### 3. Расчет кластера для векторного поиска

Сценарий: 10 миллионов документов с векторами 768 измерений, retention бессрочный.

```bash
# 1. Объем
# 10M × 768 dims × 4 bytes = 30 ГБ сырых векторов
# С HNSW overhead × 3 → ~90 ГБ

# 2. Шарды
# 90 ГБ / 15 ГБ = 6 шардов

# 3. RAM
# HNSW граф в page cache: ~8–12 ГБ
# Heap для запросов: 16–31 ГБ
# Итого: 64 ГБ минимум на узел
```

### 4. Определение размера hot-warm tier

Сценарий: кластер на 2 ТБ логов с ISM Hot-Warm-Cold.

```bash
# 1. Hot
# 50 ГБ/день × 7 дней = 350 ГБ
# С репликами × 2 → 700 ГБ

# 2. Warm
# 50 ГБ/день × 23 дня = 1150 ГБ
# После shrink/force merge: ~800 ГБ
# С репликами × 2 → 1.6 ТБ

# Итого:
# Hot: 3 узла × 1 ТБ NVMe = 3 ТБ (с запасом 50%)
# Warm: 2 узла × 4 ТБ HDD = 8 ТБ (с запасом 100%)
```

### 5. Мониторинг и алертинг capacity

```bash
# 1. Распределение шардов
curl -ku admin:$PASS "$OS/_cat/shards?v&h=index,shard,prirep,store,node&s=store:desc"

# 2. Распределение по узлам
curl -ku admin:$PASS "$OS/_cat/allocation?v&h=node,shards,disk.used_percent,heap.percent"

# 3. Лимит шардов
curl -ku admin:$PASS "$OS/_cluster/settings?include_defaults=true&filter_path=**.max_shards_per_node"

# 4. Remote Store Stats (если используется RBS)
curl -ku admin:$PASS "$OS/_plugins/_remote_store/stats?pretty"
```

### 6. Сценарий роста: добавление узлов

```bash
# 1. Проверить текущую нагрузку
curl -ku admin:$PASS "$OS/_cat/nodes?v&h=name,node.role,heap.percent,disk.used_percent,cpu,load_1m"

# 2. Добавить узел с ролью data
node.roles: [ data ]

# 3. Elasticsearch автоматически relocate шарды
curl -ku admin:$PASS "$OS/_cat/allocation?v"

# 4. Ограничить скорость relocation
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "persistent": { "indices.recovery.max_bytes_per_sec": "100mb" } }'
```

### 7. Расчет пропускной способности сети

| Компонент | Входящий | Исходящий | Комментарий |
| :--- | :--- | :--- | :--- |
| Индексация | bulk от приложений | Репликация SegRep | 1 Гбит/с на узел данных |
| Поиск | Запросы | Merge результатов | 1 Гбит/с |
| Recovery | Данные с primary | Данные на replica | Пик при добавлении узла |
| Remote Store | Чтение из S3 | Кэширование сегментов | Зависит от объема данных |

```bash
# Проверить транспорт
curl -ku admin:$PASS "$OS/_nodes/stats/transport?pretty"
```

### 8. RTO/RPO для disaster recovery

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| RPO | 15 минут | Translog flush + durability `request` |
| RTO | 30 минут | Восстановление шарда 50 ГБ с NVMe |
| SLA | 99.9% | ~8.7 часов простоя в год |

```bash
# Уменьшить RTO
curl -ku admin:$PASS -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 4,
    "cluster.routing.allocation.cluster_concurrent_rebalance": 2
  }
}'
```

## Дополнительная информация

### Формулы

```
Диск = (Данные × Реплики × 1.3) + Запас на merge (20%)
Шарды = CEILING(Объем данных / Целевой размер)
Узлы = CEILING((Шарды × Реплики) / Шардов_на_узел)
Heap = MIN(50% RAM, 31 ГБ)
```

### Проверочный список capacity planning

- [ ] Оценен дневной объем данных (ГБ/день)
- [ ] Определен retention (дни/месяцы)
- [ ] Рассчитан общий объем с overhead
- [ ] Выбран целевой размер шарда (30–50 ГБ)
- [ ] Определено число реплик
- [ ] Рассчитано общее число шардов
- [ ] Определено число узлов с запасом 20–30%
- [ ] Проверен `max_shards_per_node`
- [ ] Установлены disk watermarks
- [ ] Настроен алертинг на heap, disk, pending tasks
- [ ] Протестировано восстановление из snapshot

### Ограничения

| Параметр | Значение |
| :--- | :--- |
| Шардов на узел (до 2.15) | 1000 |
| Шардов на узел (2.17+) | до 4000 (1000 на 16 ГБ heap) |
| Рекомендуемые шарды | <= 25 на 1 ГБ heap |
| Размер первичного шарда | 30–50 ГБ |
| JVM heap | 50% RAM, максимум ~31 ГБ |

### Смотрите также

*   **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура и роли узлов.
*   **[OpenSearch: Администрирование](./opensearch_administration.md)** — безопасность и тюнинг.
*   **[OpenSearch: ISM жизненный цикл](./opensearch_ism_lifecycle.md)** — автоматизация ротации.
*   **[OpenSearch: Траблшутинг индексации](./opensearch_troubleshooting_indexing.md)** — диагностика проблем.
