# OpenSearch: Capacity Planning и проектирование кластера

**Актуально для:** OpenSearch 3.9.x (релиз 29 сентября 2026). Отличия ветки 2.x (2.15, 2.17) отмечены в тексте.

> Заметка посвящена расчету параметров кластера OpenSearch: размера шардов, числа узлов, объемов диска, heap, CPU и пропускной способности. Базовые понятия (шарды, роли узлов, data tiers) описаны в [обзоре OpenSearch](./opensearch_overview.md); ISM — в [жизненном цикле индексов (ISM)](./opensearch_ism_lifecycle.md); механика watermarks и общий траблшутинг — в [администрировании](./opensearch_administration.md); снапшоты и disaster recovery — в [Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md).

## Определения

* **Capacity Planning (Планирование мощностей)** — процесс определения количества узлов, дискового пространства, RAM и CPU для стабильной работы кластера под прогнозируемой нагрузкой.
* **Shard Sizing (Размер шардов)** — целевой объем данных на одном первичном шарде. Влияет на скорость индексации, восстановление и нагрузку на Cluster Manager.
* **Hot-Warm Architecture** — разделение узлов по ролям хранения: `hot` (NVMe/SSD, активная запись), `warm` (HDD/бюджетный SSD, редкий поиск), `cold` (объектное хранилище, архив).
* **Oversharding (Избыточное шардирование)** — создание слишком большого числа шардов относительно объема данных и heap. Приводит к замедлению публикации состояния кластера и восстановления.
* **JVM Heap** — память JVM OpenSearch. Максимум ~31 ГБ (Compressed OOPs). Вторая половина RAM остается под Lucene page cache.
* **Page Cache (Кэш страниц ОС)** — неиспользуемая RAM для кэширования файлов Lucene. От размера page cache напрямую зависит скорость поиска.
* **Segment Replication (SegRep)** — репликация готовых сегментов Lucene с primary на реплики. Снижает CPU-нагрузку на data-узлах, но увеличивает сетевой трафик.
* **Remote-Backed Storage (RBS)** — хранение сегментов в объектном хранилище. Отделяет вычисления от хранения, ускоряет восстановление узлов. Работает с любым S3-совместимым хранилищем, включая on-prem решения (MinIO, Ceph).
* **Write amplification (Усиление записи)** — коэффициент, показывающий, сколько байт записано на диск относительно исходного объема. Высокое значение — признак неоптимальных настроек merge.
* **Recovery bandwidth (Пропускная способность восстановления)** — скорость, с которой реплика восстанавливает данные с primary шарда. Ограничивается `indices.recovery.max_bytes_per_sec`.
* **Disk Watermarks (Пороги диска)** — три порога заполнения диска (low/high/flood_stage), управляющие размещением шардов и блокировкой записи. Подробная механика — в [администрировании](./opensearch_administration.md).
* **cluster.max_shards_per_node** — лимит шардов на data-узел. До 2.15 включительно: 1000. С 2.17+: до 4000 (1000 на каждые 16 ГБ heap). Шарды закрытых индексов в лимит не входят.
* **OpenSearch Benchmark** — официальный фреймворк макробенчмарков OpenSearch (форк Rally, PyPI-пакет `opensearch-benchmark`); используется для замера throughput и latency перед закупкой железа.

## Основные концепции

### Правило размера шардов

| Тип данных | Целевой размер | Максимальный |
| :--- | :--- | :--- |
| Логи / метрики | 30–50 ГБ | 100 ГБ |
| Поисковые индексы | 20–30 ГБ | 50 ГБ |
| Векторные индексы | 10–20 ГБ | 50 ГБ |

Основания для ограничений:

* **Восстановление после сбоя**: время восстановления пропорционально размеру шарда. Шард 100 ГБ восстанавливается в 2–3 раза дольше, чем шард 30 ГБ.
* **Нагрузка на Cluster Manager**: каждый шард — это метаданные в кластерном состоянии. Тысячи шардов замедляют выборы и публикацию состояния.
* **Эффективность merge**: мелкие шарды сливаются неэффективно, слишком крупные — медленно.

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

**Почему 31 ГБ**: JVM использует Compressed OOPs (32-битные указатели) до этого порога. При 32 ГБ и выше указатели расширяются до 64 бит, что увеличивает потребление памяти и снижает производительность.

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

### Thread pools и CPU

Размеры пулов потоков рассчитываются автоматически от числа доступных процессоров (исходный код `ThreadPool.java`; переопределение — через `node.processors`):

| Пул | Тип | Размер | Queue |
| :--- | :--- | :--- | :--- |
| `write` (индексация, bulk) | FIXED | = число процессоров | 10000 |
| `search` | RESIZABLE | `(процессоры × 3) / 2 + 1` | 1000 |
| `get` | FIXED | = число процессоров | 1000 |
| `analyze` | FIXED | 1 | 16 |

Следствие для capacity planning: поисковые нагрузки требуют примерно в 1.5 раза больше потоков на ядро, чем индексация — при выборе CPU учитывайте соотношение поиска к записи. Насыщение пула проявляется в росте `rejected` (`_cat/thread_pool`).

### Disk watermarks

| Порог | По умолчанию | Поведение при превышении |
| :--- | :--- | :--- |
| `low` | 85% | Новые шарды (в т.ч. реплики новых индексов) не размещаются на узле |
| `high` | 90% | Существующие шарды переносятся на другие узлы |
| `flood_stage` | 95% | Индексы с шардами на узле переводятся в read-only (`index.blocks.read_only_allow_delete`) |

Заполнение диска проверяется каждые `cluster.info.update.interval` (по умолчанию `30s`). Планируйте диск так, чтобы штатное использование не превышало low watermark: запас нужен под merge, рост translog и суточный прирост данных. Механика порогов и снятия блока — в [администрировании](./opensearch_administration.md).

### Роли узлов и их sizing

Стартовые рекомендации (точный sizing — по результатам бенчмарка, сценарий 10):

| Роль | vCPU | RAM | Диск | Сеть |
| :--- | :--- | :--- | :--- | :--- |
| `cluster_manager` | 4–8 | 16–32 ГБ | Не требуется (метаданные) | 1 Гбит/с |
| `data` hot | 8–16 | 32–64 ГБ (heap 16–31 ГБ) | NVMe 500 ГБ–2 ТБ | 10 Гбит/с |
| `data` warm | 4–8 | 16–32 ГБ | HDD/SSD 2–8 ТБ | 1 Гбит/с |
| `search` (3.0+) | 8–16 | 32–64 ГБ | Не требуется (remote store) | 10 Гбит/с |
| `coordinating` | 8–16 | 32–64 ГБ | Не требуется | 10 Гбит/с |
| `ingest` | 4–8 | 16–32 ГБ | Зависит от pipeline | 1 Гбит/с |

### Формула расчета

```
Общее число шардов = (Объем данных / Целевой размер шарда) × Количество реплик
Число узлов = Общее число шардов / Шардов на узел
```

Для временных рядов (индекс на интервал времени):

```
Шардов на индекс = CEILING(Данные за интервал / Целевой размер шарда)
Общее число шардов = Шардов на индекс × Число индексов в retention × (1 + Реплики)
```

Пример: 50 ГБ/день, rollover по 30 ГБ → 2 первичных шарда/день; за 30 дней → 60 первичных; с 1 репликой → 120 шардов. Чем чаще ротация, тем больше шардов — но тем лучше распределение нагрузки и тем быстрее удаление устаревших данных.

### Оценка пропускной способности индексации

* **Размер bulk-запроса**: 3–15 МБ (стартовая точка — 3–5 МБ).
* **Concurrency**: 2–4 параллельных bulk-потока на data-узел; замер и постепенный рост до насыщения пула `write`.
* **refresh_interval**: `30s` для логов вместо `1s` по умолчанию — резко снижает число сегментов и write amplification.
* **SegRep**: до +25–40% throughput индексации ценой сетевого трафика (детали — в [администрировании](./opensearch_administration.md)).
* **Замер**: OpenSearch Benchmark (сценарий 10) дает docs/s и MB/s на узел — базу для масштабирования.

## Практические сценарии

**Предварительные требования для всех сценариев**:

```bash
export OS="https://localhost:9200"
export PASS="<пароль пользователя admin>"
curl -ku admin:$PASS -k "$OS"   # → {"name" : "opensearch-dev", ..., "tagline" : "The OpenSearch Project"}
```

Флаг `-k` нужен для демо-сертификатов локального кластера; в production используйте собственный PKI без `-k` (см. [обзор](./opensearch_overview.md)).

### 1. Расчет кластера для логов приложения

Сценарий: 3 приложения, 50 ГБ логов/день, retention 30 дней.

```bash
# 1. Общий объем
# 50 ГБ/день × 30 дней = 1500 ГБ
# С overhead на сегменты и translog × 1.3 → ~2 ТБ

# 2. Число первичных шардов
# 2 ТБ / 50 ГБ ≈ 40 первичных шардов
# С 1 репликой → 80 шардов всего

# 3. Число узлов
# 80 / 25 (шардов на узел с 16 ГБ heap) ≈ 3.2 → 4 узла минимум
# С запасом 20–30%: 5 узлов (3 hot + 2 warm)
```

Политика ISM для ротации и удаления (полный синтаксис и все действия — в [жизненном цикле индексов](./opensearch_ism_lifecycle.md)):

```json
PUT /_plugins/_ism/policies/logs_30d
{
  "policy": {
    "description": "Логи: ротация по 30 ГБ/1 дню, warm-оптимизация, удаление через 30 дней",
    "default_state": "hot",
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
# → {"_id":"logs_30d","primary_term":1,"seq_no":0,"policy":{...}}
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

> Квантование (1-bit/2-bit/4-bit SQ, binary quantization) сокращает потребление памяти векторами до 32x — закладывайте его в расчет, если допустима потеря точности (детали — в [обзоре](./opensearch_overview.md)).

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
# 1. Распределение шардов и диска по узлам
curl -ku admin:$PASS -k "$OS/_cat/allocation?v&h=node,shards,disk.indices,disk.used,disk.total,disk.percent"
# → node  shards disk.indices disk.used disk.total disk.percent
# → node1 120    1.2tb        1.5tb     2tb        75
# → node2 118    1.1tb        1.4tb     2tb        70

# 2. Heap, CPU и нагрузка по узлам
curl -ku admin:$PASS -k "$OS/_cat/nodes?v&h=name,node.role,heap.percent,ram.percent,cpu,load_1m,disk.used_percent"

# 3. Лимит шардов
curl -ku admin:$PASS -k "$OS/_cluster/settings?include_defaults=true&filter_path=**.max_shards_per_node"
# → {"defaults":{"cluster":{"max_shards_per_node":"1000"}}}

# 4. Remote Store Stats (если используется RBS)
curl -ku admin:$PASS -k "$OS/_plugins/_remote_store/stats?pretty"
```

Алерты (пороги — рекомендации, настраивайте под SLA): `heap.percent > 75`, `disk.used_percent > 80`, рост `pending_tasks`, `rejected > 0` в пулах `write`/`search`, `breakers.*.tripped > 0`.

### 6. Сценарий роста: добавление узлов

```bash
# 1. Проверить текущую нагрузку
curl -ku admin:$PASS -k "$OS/_cat/nodes?v&h=name,node.role,heap.percent,disk.used_percent,cpu,load_1m"

# 2. Добавить узел с ролью data
node.roles: [ data ]

# 3. OpenSearch автоматически relocate шарды
curl -ku admin:$PASS -k "$OS/_cat/allocation?v"

# 4. Ограничить скорость relocation
curl -ku admin:$PASS -k -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "persistent": { "indices.recovery.max_bytes_per_sec": "100mb" } }'
# → {"acknowledged":true}
```

### 7. Расчет пропускной способности сети

| Компонент | Входящий | Исходящий | Комментарий |
| :--- | :--- | :--- | :--- |
| Индексация | bulk от приложений | Репликация SegRep | 1 Гбит/с на узел данных |
| Поиск | Запросы | Merge результатов | 1 Гбит/с |
| Recovery | Данные с primary | Данные на replica | Пик при добавлении узла |
| Remote Store | Чтение из объектного хранилища | Кэширование сегментов | Зависит от объема данных |

```bash
# Проверить транспорт
curl -ku admin:$PASS -k "$OS/_nodes/stats/transport?pretty"
```

### 8. RTO/RPO для disaster recovery

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| RPO | ≈ 0 для подтвержденных записей | `index.translog.durability: request` (по умолчанию): fsync на primary и всех репликах до ACK; при `async` — окно до `sync_interval` (5s по умолчанию) |
| RPO (полное восстановление) | Интервал SM-политики | Между снапшотами данные восстанавливаются только из последнего снапшота |
| RTO | 30 минут | Восстановление шарда 50 ГБ с NVMe; зависит от `indices.recovery.max_bytes_per_sec` |
| SLA | 99.9% | ~8.7 часов простоя в год |

```bash
# Уменьшить RTO
curl -ku admin:$PASS -k -X PUT "$OS/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "200mb",
    "cluster.routing.allocation.node_concurrent_recoveries": 4,
    "cluster.routing.allocation.cluster_concurrent_rebalance": 2
  }
}'
# → {"acknowledged":true}
```

### 9. Расчет места для снапшотов

Сценарий: кластер из сценария 1 (2 ТБ данных), ежедневные снапшоты, retention 7 дней.

```bash
# 1. Первый снапшот — полная копия данных
# ~2 ТБ

# 2. Последующие снапшоты — инкрементальные
# Переносятся только измененные сегменты с момента предыдущего снапшота
# Оценка при стабильной записи: 5–10% от объема данных в сутки

# 3. Размер репозитория
# Верхняя граница: Данные × Число хранимых снапшотов
# Практическая оценка: 1.5–2× объема данных при ежедневных снапшотах
# 2 ТБ × 2 → 4 ТБ на репозиторий

# 4. Проверка снапшотов
curl -ku admin:$PASS -k "$OS/_cat/snapshots/my_repository?v"
# → id                 start_epoch ... indices successful_shards failed_shards ...
```

Автоматизация создания и удаления снапшотов — через Snapshot Management (SM) policies; механика и примеры — в [Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md).

### 10. Нагрузочное тестирование перед продакшеном

OpenSearch Benchmark (PyPI-пакет `opensearch-benchmark`, форк Rally) — эталонный инструмент замера throughput и latency. Методика:

1. Замерьте throughput на один узел (docs/s и МБ/s) с production-подобными размером bulk и concurrency.
2. Масштабируйте: `число узлов = целевой throughput / throughput на узел`.
3. Сравнивайте конфигурации через `opensearch-benchmark compare`.

```bash
# 1. Установка
pip3 install opensearch-benchmark

# 2. Sanity-check прогон (первые 1000 операций каждой задачи, метрики не валидны)
opensearch-benchmark run --pipeline=benchmark-only \
  --workload=nyc_taxis \
  --target-host=https://localhost:9200 \
  --client-options=basic_auth_user:admin,basic_auth_password:$PASS,verify_certs:false \
  --test-mode

# 3. Полный прогон — без --test-mode; фрагмент результата:
# | Mean Throughput              | index | 4500.0 | docs/s |
# | 50th percentile latency      | search | 12.3  | ms     |
# | 100th percentile service time| search | 89.7  | ms     |
# | error rate                   | index | 0      | %      |
```

Что анализировать в отчете: throughput по задачам, latency/service time (p50/p95/p99), error rate, время GC, merge/refresh/flush, heap. Начиная с версии 2.0 доступен streaming ingestion — генерация синтетических данных до ТБ/день без локального корпуса, что позволяет тестировать в масштабе production. Справочник по workload'ам и флагам: [документация OpenSearch Benchmark](https://docs.opensearch.org/latest/benchmark/).

## Troubleshooting

Capacity-специфичные проблемы; общий траблшутинг кластера — в [администрировании](./opensearch_administration.md), проблемы индексации и сегментов — в [траблшутинге индексации](./opensearch_troubleshooting_indexing.md).

1. **Oversharding**: рост `pending_tasks`, медленная публикация состояния кластера, долгое восстановление. Диагностика: `_cat/allocation`, `_cluster/health`. Решение: уменьшить число шардов на новых индексах (rollover по размеру), `shrink` для разросшихся шардов, увеличить heap.
2. **Диск заполнен (watermark)**: быстрая диагностика — `_cat/allocation?v&s=disk.percent:desc`. Механика порогов и снятие блока `read_only_allow_delete` — в [администрировании](./opensearch_administration.md).
3. **Медленное восстановление после добавления узла**: проверьте `indices.recovery.max_bytes_per_sec`, загрузку сети и `_cat/recovery?v`.
4. **Yellow после добавления индексов**: чаще всего не хватает узлов данных для числа реплик либо достигнут лимит `cluster.max_shards_per_node` — `_cluster/allocation/explain` назовет конкретную причину.
5. **Давление на heap при большом числе шардов**: каждый шард потребляет heap на метаданные; устойчивый `heap.percent > 75` при множестве мелких шардов — сигнал к консолидации.
6. **Write rejections**: пул `write` насыщен (queue 10000 переполнен) — масштабируйте кластер или оптимизируйте bulk (размер 3–15 МБ, concurrency).

## Best Practices

* **Запас 20–30%** по диску, CPU и числу узлов — под пики, merge и восстановление.
* **Планируйте под пик**, не под среднюю нагрузку: суточные и недельные всплески определяют требуемый sizing.
* **Контролируйте размер шардов** через rollover/ISM (30–50 ГБ); не более 100 ГБ на первичный шард.
* **Тестируйте восстановление** из снапшота до продакшена и после любых изменений конфигурации.
* **Мониторьте тренд роста** (`_cat/indices` по store size) и прогнозируйте дату исчерпания диска — не момент достижения watermark.
* **Стремитесь к стабильному числу шардов**: избегайте множества мелких шардов; консолидируйте через `shrink` и `force_merge`.
* **`force_merge` до 1 сегмента** на warm/закрытых индексах — ускоряет поиск и освобождает место.
* **Раздельное железо** под hot/warm; выделенные cluster manager (3 или 5 узлов) в production.
* **Бенчмарк перед продакшеном** (OpenSearch Benchmark) — замер на реальном железе с production-подобными данными.
* **Алерты**: heap > 75%, disk > 80%, pending tasks > 0, rejected > 0, breakers tripped > 0.

## Дополнительная информация

### Формулы

```
Диск = (Данные × Реплики × 1.3) + Запас на merge (20%)
Шарды = CEILING(Объем данных / Целевой размер)
Узлы = CEILING((Шарды × Реплики) / Шардов_на_узел)
Heap = MIN(50% RAM, 31 ГБ)
Репозиторий снапшотов ≈ 1.5–2 × Объем данных (ежедневные снапшоты)
```

### Проверочный список capacity planning

- [ ] Оценен дневной объем данных (ГБ/день) и пиковый коэффициент
- [ ] Определен retention (дни/месяцы)
- [ ] Рассчитан общий объем с overhead
- [ ] Выбран целевой размер шарда (30–50 ГБ)
- [ ] Определено число реплик
- [ ] Рассчитано общее число шардов (включая временные ряды по формуле)
- [ ] Определено число узлов с запасом 20–30%
- [ ] Проверен `cluster.max_shards_per_node`
- [ ] Sized CPU под соотношение поиск/индексация (thread pools)
- [ ] Установлены disk watermarks и алерты
- [ ] Рассчитано место для снапшотов
- [ ] Настроен алертинг на heap, disk, pending tasks, rejected
- [ ] Протестировано восстановление из snapshot
- [ ] Выполнен бенчмарк (OpenSearch Benchmark) на целевом железе

### Лимиты и ограничения

Актуальная сводка лимитов (шарды на узел, размер шарда, JVM heap) поддерживается в [администрировании OpenSearch](./opensearch_administration.md#ключевые-ограничения-и-лимиты) — во избежание расхождения значений в двух местах.

### Смотрите также

*   **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура и роли узлов.
*   **[OpenSearch: Администрирование](./opensearch_administration.md)** — безопасность, watermarks, тюнинг.
*   **[OpenSearch: Snapshots и Disaster Recovery](./opensearch-disaster-recovery.md)** — снапшоты, SM, план восстановления.
*   **[OpenSearch: ISM жизненный цикл](./opensearch_ism_lifecycle.md)** — автоматизация ротации.
*   **[OpenSearch: Траблшутинг индексации](./opensearch_troubleshooting_indexing.md)** — диагностика проблем.
*   **[OpenSearch Benchmark: документация](https://docs.opensearch.org/latest/benchmark/)** — нагрузочное тестирование.
