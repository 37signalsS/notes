# Elasticsearch: Capacity Planning и проектирование кластера

**Актуально для:** Elasticsearch 8.x / 9.x

> Заметка посвящена расчёту параметров кластера Elasticsearch: размера шардов, числа узлов, объёмов диска, heap и пропускной способности. Базовые понятия (шарды, роли узлов, data tiers) описаны в [обзоре Elasticsearch](./elasticsearch_overview.md); механика ILM (rollover, shrink, forcemerge) — в [ILM и политиках хранения](./elasticsearch_ilm_and_retention.md); развертывание — в [руководстве по настройке кластера](../Tutorials/cluster_setup.md).

## Определения

* **Capacity Planning (Планирование мощностей)** — процесс определения количества узлов, дискового пространства, RAM и CPU, необходимых для стабильной работы кластера под прогнозируемой нагрузкой.
* **Shard Sizing (Размер шардов)** — целевой объём данных на одном первичном шарде. Влияет на скорость восстановления после сбоев, нагрузку на master-узел и эффективность поиска.
* **Oversharding (Избыточное шардирование)** — слишком большое число шардов относительно объёма данных и heap кластера. Замедляет обновления кластерного состояния, выборы мастера и восстановление.
* **JVM Heap** — память, выделенная JVM Elasticsearch. Максимум 31 ГБ (порог Compressed OOPs). Вторую половину RAM должна занимать page cache Lucene.
* **Page Cache (Кэш страниц ОС)** — неиспользуемая RAM, которую ОС использует для кэширования файлов Lucene. От размера page cache напрямую зависит скорость поиска.
* **Data Tier (Уровень данных)** — группа узлов с одинаковой ролью хранения (`data_hot`, `data_warm`, `data_cold`, `data_frozen`). Elasticsearch распределяет шарды индекса по узлам одного tier.
* **Rollover** — создание нового backing index по порогу размера/возраста (ILM). Основной инструмент контроля размера шарда для time-series данных.
* **Shrink / Split** — API изменения числа первичных шардов: shrink уменьшает (цель — делитель исходного числа), split увеличивает (цель — кратное исходному). Оба требуют read-only индекс.
* **Quantization (Квантизация векторов)** — int8/int4/bbq представление векторов для снижения памяти при kNN-поиске (int8 ~4×, int4 ~8×, bbq ~32×).
* **Write amplification (Усиление записи)** — отношение байт, фактически записанных на диск, к исходному объёму данных. Рост — признак неоптимальных настроек merge/refresh.
* **Recovery bandwidth (Пропускная способность восстановления)** — скорость восстановления реплики с primary шарда. Ограничивается `indices.recovery.max_bytes_per_sec`.
* **Memory:data ratio** — отношение RAM узла к объёму данных на нём; параметр формулы расчёта числа узлов. Зависит от типа нагрузки: поиск требует больше памяти на ГБ данных, чем логирование.

## Основные концепции

### Правило размера шардов

Официальная рекомендация Elastic (8.x/9.x):

* **Размер шарда: 10–50 ГБ**; для time-series данных типично **20–40 ГБ**.
* **Число документов: менее 200 млн на шард** (теоретический предел — чуть более 2 млрд, но практика показывает деградацию раньше).
* **Жёсткого лимита размера шарда нет** — большие шарды возможны, но дольше восстанавливаются и медленнее ищут.

| Тип данных | Целевой размер первичного шарда | Порог rollover (ILM) |
| :--- | :--- | :--- |
| Логи / метрики (временные ряды) | 20–40 ГБ | `max_primary_shard_size: 50gb`, `min_primary_shard_size: 10gb` |
| Поисковые индексы (документы) | 10–50 ГБ | по объёму/возрасту |
| Векторные индексы (k-NN) | 10–20 ГБ (ориентир сообщества; официальной нормы нет) | по числу векторов |

Основания для ограничений:

* **Восстановление после сбоя**: время восстановления пропорционально размеру шарда — шард 100 ГБ восстанавливается вдвое дольше, чем 50 ГБ (копирование по сети).
* **Нагрузка на master**: каждый шард — метаданные в кластерном состоянии; тысячи шардов замедляют публикацию состояния и выборы.
* **Merge efficiency**: мелкие шарды дают мелкие сегменты — поиск по 50 шардам по 1 ГБ существенно дороже, чем по одному шарду 50 ГБ.
* **С 8.3** Elastic значительно снизила потребление heap на шард — правила стали консервативными, но остаются безопасным ориентиром при планировании.

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

**Почему 31 ГБ**: JVM использует Compressed OOPs (32-битные указатели) до этого порога; при 32 ГБ и выше указатели расширяются до 64 бит, растёт потребление памяти, падает производительность. Heap задаётся статически (`-Xms`/`-Xmx` равными) и не меняется без рестарта узла.

### Правило шардов на узел

```
Шардов на узел ≤ 20 на 1 ГБ heap (официальное правило)
```

Пример:

* 8 ГБ heap → ≤ 160 шардов
* 16 ГБ heap → ≤ 320 шардов
* 31 ГБ heap → ≤ 620 шардов

Начиная с 8.3 Elastic снизила потребление heap на шард, поэтому для типовых логовых нагрузок допустимо больше — но 20/ГБ остаётся безопасным ориентиром при планировании.

### Лимиты шардов в кластере

* `cluster.max_shards_per_node` — default **1000** шардов (primaries + replicas, включая unassigned) на non-frozen data-узел; для frozen — `cluster.max_shards_per_node.frozen` default **3000**.
* Лимит кластера = `cluster.max_shards_per_node` × число non-frozen data-узлов. Превышение — запрос на создание шардов отклоняется.
* Замкнутые (closed) индексы не учитываются; кластер без data-узлов — без лимита.
* Повышение лимита требует корректировки лимитов mmap и открытых файловых дескрипторов на узлах.
* `cluster.routing.allocation.total_shards_per_node` — лимит на один индекс (default `-1`, unlimited).

Проверка текущих значений:

```bash
curl -u elastic:$PASS -k "$ES/_cluster/settings?include_defaults=true&filter_path=defaults.cluster.max_shards_per_node*"
# → {"defaults":{"cluster":{"max_shards_per_node":"1000","max_shards_per_node.frozen":"3000"}}}
```

### Роли узлов и их sizing

| Роль | CPU | RAM | Диск | Сеть |
| :--- | :--- | :--- | :--- | :--- |
| Master-eligible | 4–8 cores | 16–32 ГБ | Метаданные (малый SSD) | 1 Гбит/с |
| Data Hot | 8–16 cores | 32–64 ГБ (heap 16–31 ГБ) | NVMe 500 ГБ–2 ТБ | 10 Гбит/с |
| Data Warm | 4–8 cores | 16–32 ГБ | HDD/SSD 2–8 ТБ | 1 Гбит/с |
| Data Cold | 2–4 cores | 8–16 ГБ | HDD/SSD 4–16 ТБ (локальный диск) | 1 Гбит/с |
| Data Frozen | 2–4 cores | 8–16 ГБ | Локальный кэш; данные в репозитории (object storage) | 10 Гбит/с |
| Coordinating | 8–16 cores | 32–64 ГБ | Не требуется | 10 Гбит/с |
| Ingest | 4–8 cores | 16–32 ГБ | Зависит от pipeline | 1 Гбит/с |

Примечания:

* Если `node.roles` не задан, узел получает все роли (master, data, data_content, data_hot, data_warm, data_cold, data_frozen, ingest, ml, remote_cluster_client, transform).
* Coordinating-only узел — явно пустой список: `node.roles: []`. Каждый узел неявно координирует запросы; выделённые coordinating-узлы нужны большим кластерам, но их избыток грузит мастера (он ждёт подтверждения обновлений состояния от каждого узла).
* Минимально необходимые роли кластера: `master` и (`data_content` + `data_hot` или `data`).
* Cold tier хранит данные на локальном диске; frozen — в snapshot-репозитории (object storage) с локальным кэшем.

### Формулы расчёта

```
Общее число шардов = Число индексов × Первичных шардов × (1 + Число реплик) × Интервалов retention
Объём диска (ГБ) = Данные (ГБ) × (1 + 0.15 watermark + 0.05 запас)
Число data-узлов = ROUNDUP(Объём диска / RAM на узел / Memory:data ratio) + 1 (узел на failover)
```

Пример:

* 1 ТБ логов, целевой размер шарда 50 ГБ → 20 первичных шардов
* С 1 репликой → 40 шардов всего
* При 20 шардах на узел (16 ГБ heap) → 2 узла данных минимум
* С запасом на рост и failover: 3 узла данных + 3 master-eligible

## Предварительные требования

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", ..., "tagline" : "You Know, for Search"}
```

* **Привилегии**: `monitor` cluster privilege для `_cat/*` и `_cluster/stats`; `manage` для изменения cluster settings; `manage index` для shrink/split.
* **Версия**: настройки и defaults в заметке актуальны для 8.x/9.x; в 7.x часть defaults отличается (например, `index.translog.flush_threshold_size` 512 МБ вместо 10 ГБ).
* **Heap**: `-Xms` и `-Xmx` задаются статически в `jvm.options`; изменение heap требует рестарта узла.
* **Нагрузочное тестирование**: Rally (`esrally`) — официальный бенчмарк Elastic; расчёты ниже — отправная точка, финальный sizing — по результатам теста реальной нагрузкой.

## Практические сценарии

### 1. Расчёт кластера для логов приложения

Сценарий: 3 приложения генерируют 50 ГБ логов в сутки, retention 30 дней.

```bash
# 1. Общий объём данных
# 50 ГБ/день × 30 дней = 1500 ГБ = 1.5 ТБ (первичные шарды)

# 2. Целевой размер шарда для логов: 20–40 ГБ, порог rollover 50 ГБ
# 1.5 ТБ / 50 ГБ = 30 первичных шардов

# 3. Реплики: 1 (failover одного узла)
# 30 × (1 + 1) = 60 шардов всего

# 4. Число узлов: 60 / 20 (шардов на узел при 16 ГБ heap) = 3 узла минимум
# С запасом 20–30%: 4 hot-узла; + 2 warm-узла для старых данных
```

Рекомендуемая конфигурация:

```yaml
# 4 hot-узла (NVMe 500 ГБ–1 ТБ каждый)
node.roles: [ data_hot, data_content, ingest ]
node.attr.temp: hot

# 2 warm-узла (HDD 4 ТБ каждый)
node.roles: [ data_warm ]
node.attr.temp: warm

# 3 master-eligible узла (16 ГБ RAM каждый)
node.roles: [ master ]
```

```json
// ILM политика с учётом sizing (механика действий — в заметке про ILM)
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_primary_shard_size": "50gb", "min_primary_shard_size": "10gb", "max_age": "1d" }
        }
      },
      "warm": {
        "min_age": "7d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "allocate": { "require": { "temp": "warm" } }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": { "delete": {} }
      }
    }
  }
}
```

Замечания по ILM: действие `shrink` само блокирует запись на исходном индексе и требует, чтобы число шардов цели было делителем исходного; в hot-фазе `shrink`/`forcemerge` допустимы только вместе с `rollover`. `forcemerge` — best effort: шарды, перемещаемые в момент merge, не сливаются.

### 2. Расчёт кластера для метрик (TSDB)

Сценарий: 1000 хостов, каждый отправляет 100 метрик каждые 15 секунд, retention 90 дней.

```bash
# 1. Число документов
# 1000 хостов × 100 метрик × 4 сэмпла/мин × 60 мин × 24 ч = 576 млн документов/день
# × 90 дней ≈ 51.8 млрд документов

# 2. Оценка объёма с downsampling
# Детальные данные (7 дней): ~400 ГБ (с учётом compression)
# Downsampled 1h (83 дня): ~30 ГБ
# Итого: ~430 ГБ

# 3. Число шардов
# Целевой размер 30 ГБ → 15 первичных шардов; с запасом — 20
```

```json
{
  "settings": {
    "index.mode": "time_series",
    "index.mapping.source.mode": "synthetic",
    "number_of_shards": 20,
    "number_of_replicas": 1
  }
}
```

`index.mapping.source.mode: synthetic` хранит `_source` синтетически из doc values — экономия диска ценой ограничений (все поля должны поддерживать doc values; проверьте совместимость маппинга перед применением).

### 3. Расчёт кластера для векторного поиска

Сценарий: 10 миллионов документов с векторами 768 измерений (float32), retention бессрочный.

```bash
# 1. Объём сырых векторов
# 10M × 768 dims × 4 bytes = 30.7 ГБ
# С HNSW-графами и Lucene overhead × 3 → ~90 ГБ (ориентир)

# 2. Целевой размер шарда для векторных индексов: 10–20 ГБ (ориентир сообщества)
# 90 ГБ / 15 ГБ = 6 шардов

# 3. RAM для k-NN
# Граф HNSW и квантизованные векторы загружаются в native memory (off-heap)
# Для 10M векторов 768d с int8: ~8–12 ГБ native memory
# Heap: 16–31 ГБ (агрегации, запросы)
# Итого: 64 ГБ RAM минимум на узел
```

```json
{
  "mappings": {
    "properties": {
      "embedding": {
        "type": "dense_vector",
        "dims": 768,
        "index": true,
        "index_options": {
          "type": "int8_hnsw",
          "m": 32,
          "ef_construction": 200,
          "confidence_interval": 0.95
        }
      }
    }
  }
}
```

Параметры `index_options`: `m` default 16, `ef_construction` default 100 (рост повышает recall ценой скорости индексации); `confidence_interval` — 0.90–1.0 или 0 (динамический квантиль). В 9.0 float-векторы всегда индексируются как `int8_hnsw`; в 9.1+ default — `bbq_hnsw` для ≥384 измерений, `int8_hnsw` для меньших.

Квантизация снижает память поиска: int8 ~4×, int4 ~8×, bbq ~32×; сырые float-векторы сохраняются на диске для reranking (int8 на 40 ГБ float-данных добавляет ~10 ГБ к диску). Для больших векторов исключайте поле из `_source` (`"_source": {"excludes": ["embedding"]}`) — экономия на загрузке документов при kNN-поиске.

### 4. Определение размера hot-warm tier

Сценарий: кластер на 150 ГБ логов в сутки с ILM Hot-Warm.

```bash
# 1. Hot-хранилище (7 дней)
# 150 ГБ/день × 7 = 1.05 ТБ первичных; с репликой × 2 → 2.1 ТБ
# 3 hot-узла × 1 ТБ NVMe = 3 ТБ (запас ~30%)

# 2. Warm-хранилище (следующие 23 дня)
# 150 ГБ/день × 23 = 3.45 ТБ первичных
# После shrink (1 шард) и forcemerge: ~2.7 ТБ
# С репликой × 2 → ~5.4 ТБ
# 2 warm-узла × 4 ТБ HDD = 8 ТБ (запас ~30%)
```

### 5. Мониторинг и алертинг capacity

```bash
# 1. Текущее использование шардов
curl -u elastic:$PASS -k "$ES/_cat/shards?v&h=index,prirep,shard,store,node&s=store:desc"

# 2. Распределение по узлам
curl -u elastic:$PASS -k "$ES/_cat/allocation?v&h=node,shards,disk.used_percent,heap.percent"

# 3. Число шардов в кластере
curl -u elastic:$PASS -k "$ES/_cluster/stats?filter_path=indices.shards.total"

# 4. Лимит шардов (default 1000 на non-frozen узел, 3000 на frozen)
curl -u elastic:$PASS -k "$ES/_cluster/settings?include_defaults=true&filter_path=defaults.cluster.max_shards_per_node*"
```

Алерты (через Kibana Alerting или Prometheus):

* `heap.percent > 75` — давление на GC
* `disk.used_percent > 80` — приближение к low watermark (85%)
* шардов на узел > 800 — приближение к лимиту 1000
* тренд общего числа шардов — раннее обнаружение oversharding

### 6. Сценарий роста: добавление узлов

Сценарий: кластер на 3 узлах, нагрузка выросла в 2 раза, нужно масштабировать.

```bash
# 1. Текущая нагрузка
curl -u elastic:$PASS -k "$ES/_cat/nodes?v&h=name,node.role,heap.percent,disk.used_percent,cpu,load_1m"

# 2. Новый узел (elasticsearch.yml)
node.roles: [ data_hot, data_content, ingest ]
node.attr.temp: hot

# 3. Elasticsearch автоматически relocate шарды
curl -u elastic:$PASS -k "$ES/_cat/allocation?v"

# 4. Контроль скорости recovery (default 40 МБ/с на узел)
curl -u elastic:$PASS -k "$ES/_cluster/settings?include_defaults=true&filter_path=defaults.indices.recovery.max_bytes_per_sec"
```

Настройки recovery (defaults; Elastic не рекомендует менять concurrency со значений по умолчанию):

```json
{
  "persistent": {
    "indices.recovery.max_bytes_per_sec": "100mb",
    "cluster.routing.allocation.node_concurrent_incoming_recoveries": 2,
    "cluster.routing.allocation.node_concurrent_outgoing_recoveries": 2,
    "cluster.routing.allocation.cluster_concurrent_rebalance": 2
  }
}
```

* `indices.recovery.max_bytes_per_sec` default **40mb** (40 МиБ/с) на узел; для dedicated cold/frozen узлов default зависит от памяти: ≤4 ГБ — 40, 4–8 — 60, 8–16 — 90, 16–32 — 125, >32 — 250 МиБ/с.
* `node_concurrent_incoming_recoveries` / `node_concurrent_outgoing_recoveries` default **2**; `node_initial_primaries_recoveries` default **4** (восстановление primary с локального диска при рестарте узла).
* Устаревший `node_concurrent_recoveries` работает как fallback для обоих направлений — используйте направленные настройки.

### 7. Расчёт пропускной способности сети

Сценарий: планирование сети для кластера на 5 узлов.

| Компонент | Входящий трафик | Исходящий трафик | Комментарий |
| :--- | :--- | :--- | :--- |
| Индексация | bulk-запросы от приложений | Репликация на другие узлы | 1 Гбит/с на узел данных |
| Поиск | Запросы от приложений | Merge результатов с шардов | 1 Гбит/с на узел данных |
| Recovery | Данные с primary | Данные на replica | Пиковая нагрузка при добавлении узла |
| Cross-cluster | Запросы к удалённому кластеру | Результаты поиска | Только для CCR/CCS (требует `remote_cluster_client`) |

```bash
# Текущая нагрузка на сеть (transport)
curl -u elastic:$PASS -k "$ES/_nodes/stats/transport?pretty"
```

### 8. SLA, RTO/RPO

| Параметр | Значение | Обоснование |
| :--- | :--- | :--- |
| RPO | ≈ 0 для acknowledged writes | `index.translog.durability: request` (default): fsync перед подтверждением запроса на primary и всех репликах |
| RPO (при `durability: async`) | ≤ `index.translog.sync_interval` (default 5s, мин 100ms) | fsync в фоне раз в интервал |
| RTO | 30 минут | Восстановление primary шарда 50 ГБ с NVMe + recovery реплик |
| SLA доступности | 99.9% | ~8.7 часов простоя в год |
| SLA поиска | 99.95% | ~4.4 часа простоя в год |

Translog: автоматический flush при `index.translog.flush_threshold_size` (default **10 ГБ**; в 7.x — 512 МБ) или `index.translog.flush_threshold_age` (flush не реже раза в минуту); размер translog не превышает 1% диска. Для уменьшения RTO — snapshot-restore из репозитория (механика — в [Disaster Recovery](./elasticsearch_disaster_recovery.md)) и настройки recovery из сценария 6.

## Изменение размера шардов

Шарды неизменяемы: исправить sizing можно только скопировав данные в новый индекс.

| API | Когда | Требования |
| :--- | :--- | :--- |
| `POST /<index>/_shrink/<target>` | Уменьшить число шардов | Индекс read-only, green, все шарды на одном узле; число шардов цели — **делитель** исходного (простое число → только 1 шард); `manage index` privilege |
| `POST /<index>/_split/<target>` | Увеличить число шардов | Индекс read-only, green; число шардов цели — **кратное** исходному |
| Reindex | Произвольное изменение | Достаточно диска на копию; новый индекс с нужным `number_of_shards` |

```bash
# Shrink: 8 шардов → 2 (делитель)
curl -u elastic:$PASS -k -X POST "$ES/my-index/_shrink/my-index-shrunk" \
-H 'Content-Type: application/json' -d'
{
  "settings": {
    "index.routing.allocation.require._name": null,
    "index.blocks.write": null
  }
}'
```

* Восстановление из snapshot и clone API **не исправляют** sizing — копия сохраняет число шардов.
* ILM `shrink` сам размещает все шарды исходного индекса на одном узле и снимает `index.routing.allocation.total_shards_per_node`; при ошибке размещения ILM ждёт `index.lifecycle.step.wait_time_threshold` (default 12 часов), затем повторяет попытку.
* Перед shrink рекомендуется снять реплики (`number_of_replicas: 0`), после — вернуть.

## Настройки, влияющие на capacity

| Настройка | Default | Влияние |
| :--- | :--- | :--- |
| `indices.memory.index_buffer_size` | 10% heap (shared, min 48mb) | Буфер индексации на узел; ~512 МБ на активно пишущий шард — дальше прироста обычно нет |
| `index.refresh_interval` | 1s (только для индексов с поиском за 30s) | Меньше — свежее поиск, больше — меньше сегментов и нагрузки |
| `index.translog.durability` | `request` | fsync на каждый запрос; `async` — раз в `sync_interval` (5s) |
| `index.translog.flush_threshold_size` | 10 ГБ | Порог flush сегментов |
| `indices.recovery.max_bytes_per_sec` | 40mb/узел | Пропускная способность recovery |
| `cluster.routing.allocation.cluster_concurrent_rebalance` | 2 | Параллельные rebalance в кластере |
| `cluster.routing.allocation.allow_rebalance` | `indices_all_active` | Когда разрешён rebalance |
| `cluster.routing.rebalance.enable` | `all` | Разрешение rebalance по типам шардов |
| `cluster.routing.allocation.balance.shard` | 0.45f | Вес выравнивания числа шардов по узлам |
| `index.codec` | `best_speed` (LZ4) | `best_compression` (ZSTD) — экономия диска ценой CPU; обычно для cold/warm |

Compression: Elasticsearch обычно сжимает данные на 20–30% (LZ4); `best_compression` даёт до ~15% дополнительной экономии ценой CPU.

## Валидация расчёта

```bash
# 1. Распределение размеров шардов — отклонения от целевого 10–50 ГБ
curl -u elastic:$PASS -k "$ES/_cat/shards?v&h=index,prirep,shard,store&s=store:desc&bytes=gb"

# 2. Число шардов и документов
curl -u elastic:$PASS -k "$ES/_cluster/stats?filter_path=indices.shards.total,indices.docs.count"

# 3. Баланс по узлам
curl -u elastic:$PASS -k "$ES/_cat/allocation?v"

# 4. Идёт ли recovery / relocate
curl -u elastic:$PASS -k "$ES/_cat/recovery?v&active_only=true"

# 5. Очередь задач мастера (рост — признак перегрузки кластерного состояния)
curl -u elastic:$PASS -k "$ES/_cat/pending_tasks?v"
```

* **Нагрузочный тест**: Rally (`esrally`) с треками, близкими к реальной нагрузке; замер throughput/latency до и после изменения sizing.
* **Тренд**: мониторинг `indices.shards.total` и `store.size` по времени (Stack Monitoring, см. [Stack Monitoring](./elasticsearch_stack_monitoring.md)) — рост числа шардов быстрее роста данных = oversharding.
* **Проверка лимита**: `GET _cluster/settings?include_defaults=true&filter_path=defaults.cluster.max_shards_per_node*` — запас до 1000/узел.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `cluster is close to reaching the configured maximum number of shards` | Приближение к `cluster.max_shards_per_node` × узлов | Временно поднять лимит (`cluster.max_shards_per_node: 1200`), затем уменьшить число шардов (shrink/rollover с большим размером); после стабилизации — сбросить лимит в `null` |
| Долгие recovery, медленные выборы мастера | Oversharding (тысячи мелких шардов) | Shrink мелких индексов; увеличить rollover-порог; delete индексов вместо delete документов |
| Шард > 50 ГБ, деградация поиска | Слишком крупный шард | Split (кратное) или reindex в индекс с большим числом шардов |
| Recovery не завершается | Исчерпана полоса (`max_bytes_per_sec`) или concurrency | Проверить `_cat/recovery`; временно поднять `max_bytes_per_sec` (сценарий 6) |
| ILM shrink падает на шаге allocation | Нет места на узле, конфликт allocation rules, узел удалён | ILM ждёт 12 ч (`index.lifecycle.step.wait_time_threshold`), затем повторяет; проверить диск и `allocate`-правила |
| `forcemerge` не слил все сегменты | Best effort: шарды relocating в момент merge | Повторить после завершения relocation |

## Граничные случаи

* **Простое число шардов** (например, 7 или 13): shrink возможен только до 1 шарда; для другого числа — reindex.
* **Closed индексы** не учитываются в лимите шардов — закрытие старых индексов освобождает лимит без удаления данных.
* **Frozen-шарды** имеют отдельный лимит (3000/узел) и не учитываются в `cluster.max_shards_per_node`.
* **Повышение `cluster.max_shards_per_node`** выше default требует корректировки лимитов mmap и файловых дескрипторов на узлах.
* **Избыток coordinating-only узлов** грузит мастера: он ждёт подтверждения обновлений кластерного состояния от каждого узла.
* **Translog** не превышает 1% диска; при очень интенсивной записи flush по размеру (10 ГБ) может задерживать recovery.
* **Квантизация векторов** хранит сырые значения на диске — экономия памяти не означает пропорциональной экономии диска.
* **`node.roles` задан явно** — узел получает ТОЛЬКО перечисленные роли; забытая роль (например, `ingest`) выводит из строя соответствующий функционал.

## Best Practices

* **Планируйте под пик**, не под среднюю нагрузку: суточные/недельные всплески определяют sizing.
* **Delete indices, not documents**: удалённые документы занимают место до merge; удаление индекса освобождает сразу.
* **Data Streams + ILM** для time-series: каждый backing index — возможность скорректировать стратегию шардирования (rollover-порог, `number_of_shards` в шаблоне).
* **Rollover**: `max_primary_shard_size: 50gb`, `min_primary_shard_size: 10gb`.
* **3 master-eligible узла** для production (нечётное число, отдельные от data).
* **Quantization** (int8/int4/bbq) для векторных индексов — до 32× экономии памяти поиска.
* **`best_compression`** для cold/warm-данных — до ~15% дополнительной экономии диска.
* **Бенчмарк перед production**: Rally с реалистичным треком; расчёты — отправная точка.
* **Мониторьте тренд шардов**, а не только текущие значения.

## Cleanup

```bash
# 1. Сбросить временно повышенный лимит шардов
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "persistent": { "cluster.max_shards_per_node": null } }'

# 2. Вернуть recovery-настройки к default
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "persistent": {
    "indices.recovery.max_bytes_per_sec": null,
    "cluster.routing.allocation.node_concurrent_incoming_recoveries": null,
    "cluster.routing.allocation.node_concurrent_outgoing_recoveries": null,
    "cluster.routing.allocation.cluster_concurrent_rebalance": null
} }'

# 3. Удалить временный индекс после shrink/split/reindex
curl -u elastic:$PASS -k -X DELETE "$ES/my-index-old"

# 4. Убрать allocation-фильтры после перепрофилирования узла
curl -u elastic:$PASS -k -X PUT "$ES/_cluster/settings" \
-H 'Content-Type: application/json' -d'
{ "transient": { "cluster.routing.allocation.exclude._name": null } }'
```

## Дополнительная информация

### Проверочный список capacity planning

- [ ] Оценён дневной объём индексируемых данных (ГБ/день) и пиковый коэффициент
- [ ] Определён retention (дни/месяцы/годы)
- [ ] Рассчитан общий объём с overhead (watermark 15% + запас 5%)
- [ ] Выбран целевой размер шарда (10–50 ГБ; 20–40 ГБ для time-series)
- [ ] Число документов на шард < 200 млн
- [ ] Определено число реплик (1 для prod)
- [ ] Рассчитано общее число шардов: × (1 + реплики)
- [ ] Определено число узлов по формуле (с запасом 20–30% и +1 failover)
- [ ] Проверен лимит шардов: `cluster.max_shards_per_node` (1000) × узлов
- [ ] Установлены disk watermarks (85%/90%/95% — см. [Обзор](./elasticsearch_overview.md))
- [ ] Настроен алертинг на heap, disk, число шардов
- [ ] Проведён нагрузочный тест (Rally)
- [ ] Протестировано восстановление из snapshot на стенде

### Смотрите также

*   **[Elasticsearch: Обзор](./elasticsearch_overview.md)** — архитектура, роли узлов, watermarks.
*   **[Elasticsearch: Жизненный цикл (ILM)](./elasticsearch_ilm_and_retention.md)** — механика rollover/shrink/forcemerge.
*   **[Настройка кластера Elasticsearch](../Tutorials/cluster_setup.md)** — развертывание и системный тюнинг.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска, slow logs, circuit breakers.
*   **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — метрики для планирования.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — шаблоны индексов.
*   **[Cross-Cluster Replication](./elasticsearch_ccr_ccs.md)** — multi-cluster capacity.
*   **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — snapshot-restore и RTO/RPO.
