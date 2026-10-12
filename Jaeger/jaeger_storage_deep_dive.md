# Хранилище Jaeger: Deep Dive

**Актуально для:** Jaeger v2 (v2.x / v2.22+), ClickHouse 24.x–26.x, Elasticsearch 8.x–9.x, OpenSearch 2.x–3.x, Apache Cassandra 4.x / 5.x, Apache Kafka 3.8–4.0

**Storage Deep Dive для Jaeger** — это руководство по внутреннему устройству, конфигурированию, эксплуатации и тюнингу подсистем хранения телеметрии в Jaeger v2 для системных администраторов, DevOps и SRE-инженеров. В архитектуре Jaeger v2 на базе OpenTelemetry Collector взаимодействие с базами данных абстрагировано через **Storage Extension** (`jaeger_storage`) и **Storage Exporter** (`jaeger_storage_exporter`). Выбор и низкоуровневая настройка СУБД (ClickHouse, Elasticsearch/OpenSearch, Cassandra, Badger) или промежуточного потокового буфера (Apache Kafka) определяют предельную пропускную способность конвейера (ingestion rate), задержки выборки при расследовании инцидентов, накладные расходы на дисковые операции и совокупную стоимость инфраструктуры (TCO).

Общий обзор возможностей платформы: **[Обзор Jaeger](./jaeger_overview.md)**.  
Архитектура конвейеров и расширений: **[Архитектура Jaeger](./jaeger_architecture.md)**.  
Топологии развертывания компонентов: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**.  
Расчет вычислительных ресурсов и сайзинг: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**.  
Стратегии миграции с v1 на v2: **[Миграция с Jaeger v1 на v2](./jaeger_migration_v1_to_v2.md)**.  
Отказоустойчивость и кластеризация: **[Отказоустойчивость Jaeger](./jaeger_high_availability.md)**.  
API выборки спанов и зависимостей: **[Jaeger Query API](./jaeger_query_api.md)**.  
Сетевая безопасность и RBAC: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Storage Extension (`jaeger_storage`)** | Централизованное расширение Jaeger v2, инкапсулирующее пулы соединений, драйверы БД, health check и retry-логику для зарегистрированных бэкендов |
| **Storage Exporter (`jaeger_storage_exporter`)** | Экспортер конвейера OTel в Jaeger v2, преобразующий внутренние структуры спанов `pdata.Traces` в формат целевого хранилища через `jaeger_storage` |
| **MergeTree** | Семейство базовых движков таблиц ClickHouse с древовидной структурой хранения на диске, обеспечивающее фоновое слияние отсортированных частей данных (data parts) |
| **ReplicatedMergeTree** | Движок ClickHouse, обеспечивающий синхронизацию и целостность данных между узлами кластера с координацией через ClickHouse Keeper |
| **Granule (Гранула)** | Минимальная единица физического чтения данных в ClickHouse (по умолчанию 8192 строки), на границы которой указывает разреженный индекс |
| **Data Skipping Index** | Вторичный индекс ClickHouse (Bloom Filter, MinMax, Set), позволяющий пропускать целые гранулы без их декомпрессии при выборке по тегам или идентификаторам |
| **Inverted Index (Инвертированный индекс)** | Структура данных Elasticsearch/OpenSearch, сопоставляющая отдельные термы со списком документов; обеспечивает быстрый полнотекстовый поиск, но требует больших затрат RAM |
| **doc_values** | Дисковая колоночная структура данных в Lucene/Elasticsearch, используемая для быстрой сортировки, агрегаций и вычисления метрик без десериализации исходного документа |
| **Data Stream** | Абстракция Elasticsearch для управления неизменяемыми временными рядами поверх скрытых автогенерируемых индексов с единым постоянным именем |
| **ILM / ISM** | Механизмы автоматического управления жизненным циклом индексов в Elasticsearch (Index Lifecycle Management) и OpenSearch (Index State Management) |
| **TWCS (Time Window Compaction Strategy)** | Стратегия компактизации в Cassandra, группирующая SSTable по временным окнам; позволяет целиком удалять устаревшие файлы по истечении TTL без чтения диска |
| **Tombstone** | Маркер удаления записи или ячейки в LSM-хранилищах (Cassandra, Badger); накапливается при точечных операциях удаления или построчном TTL и может деградировать чтение |
| **Badger** | Встраиваемая (embedded) key-value база данных на базе LSM-дерева, работающая локально на NVMe-накопителе без внешних сетевых сервисов |
| **Consumer Group Offset** | Числовой указатель позиции вычитывания в партиции Kafka, коммитируемый процессом Ingester после успешной фиксации пачки спанов в постоянном хранилище |
| **Backpressure** | Механизм передачи обратного давления от хранилища через переполнение внутренних очередей экспортера к коллекторам и SDK при исчерпании емкости диска или CPU базы |

---

## Базовые концепции и архитектура бэкендов хранения

### Сравнительный анализ бэкендов хранения

Выбор хранилища для on-premise инфраструктуры зависит от профиля нагрузки (соотношение операций чтения и записи), глубины хранения (retention), необходимости произвольного поиска по тегам и доступных вычислительных ресурсов:

| Критерий | ClickHouse | Elasticsearch / OpenSearch | Apache Cassandra | Badger (Embedded) | In-Memory |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Назначение** | Production (рекомендуется по умолчанию) | Корпоративные среды с развитым ELK/поиском | Масштабируемая запись по ключу (legacy/NoSQL) | Автономные хосты, edge, dev-окружения | Тестирование, CI/CD, отладка |
| **Скорость записи** | Экстремально высокая (100k+ spans/s/node) | Средняя (20k–40k spans/s/node из-за индексов) | Высокая (50k–80k spans/s/node, append-only) | Высокая (локальный NVMe, zero-network) | Ограничена только пропускной способностью RAM |
| **Поиск по атрибутам** | Высокая (при наличии Bloom Filter и ORDER BY) | Максимальная (любые теги через инвертированный индекс) | Низкая (только по `trace_id` либо через вторичные индексы) | Базовая (итерация по ключам) | Быстрая (полный перебор в памяти) |
| **Сжатие на диске** | Максимальное (5x–10x, колоночные кодеки) | Среднее (2x–3x, накладные расходы Lucene) | Умеренное (2x–4x, LZ4/Deflate компрессия) | Высокое (Zstandard/Snappy на уровне блоков) | Сжатие отсутствует (RAM footprint) |
| **Удаление по TTL** | Мгновенно (отбрасывание директорий партиций) | Автоматически через ILM/ISM (удаление индексов) | Эффективно только при TWCS; иначе tombstones | Фоновая компактизация LSM-дерева | Очистка по таймеру или размеру очереди |
| **Накладные расходы** | Минимальные (native C++, эффективная память) | Высокие (JVM heap до 31 GB, сборщик мусора) | Высокие (JVM heap, настройка memtable) | Минимальные (Go runtime, shared memory) | Высокие (требует много RAM) |
| **Эксплуатация** | Средняя (мониторинг слияний и партиций) | Высокая (шарды, сегменты, split-brain, GC) | Высокая (repairstats, tombstones, compaction) | Нулевая (управление файловыми путями) | Нулевая (данные теряются при рестарте) |

### Архитектура Storage Extension (`jaeger_storage`) в Jaeger v2

В Jaeger v2 архитектура взаимодействия с базами данных полностью унифицирована. В отличие от v1, где каждый микросервис (`collector`, `query`, `ingester`) имел собственную реализацию драйверов БД и CLI-флагов, в v2 используется декларативная компонентная модель OpenTelemetry Collector:

```
                  ┌─────────────────────────────────────────────────────────┐
                  │                 Jaeger v2 Process Host                  │
                  │                                                         │
  OTLP / gRPC ───►│  [Receivers: otlp, kafka, jaeger]                       │
                  │                          │                              │
                  │                          ▼                              │
                  │  [Processors: memory_limiter ──► batch]                 │
                  │                          │                              │
                  │                          ▼                              │
                  │  [Exporter: jaeger_storage_exporter]                    │
                  │                          │                              │
                  │  ┌───────────────────────┼───────────────────────────┐  │
                  │  │ Storage Extension:    │                           │  │
                  │  │ `jaeger_storage`      ▼                           │  │
                  │  │   ┌─────────────────────────────────────────────┐ │  │
                  │  │   │ Connection Pool & Health Check Probes       │ │  │
                  │  │   │ Exponential Backoff Retry & Circuit Breaker │ │  │
                  │  │   └──────────────────────┬──────────────────────┘ │  │
                  │  │                          │                        │  │
                  │  │   Named Backends:        ▼                        │  │
                  │  │   [clickhouse]   [elasticsearch]   [badger]       │  │
                  │  └──────────┬───────────────┬────────────┬───────────┘  │
                  │             │               │            │              │
  HTTP UI 16686 ─►│  [jaeger_query Extension]───┘            │              │
                  │             │                            │              │
                  └─────────────┼────────────────────────────┼──────────────┘
                                ▼                            ▼
                     [ClickHouse Cluster]          [Elasticsearch Cluster]
```

Ключевые механизмы Storage Extension:
1. **Именованные бэкенды (`backends`):** В секции `extensions.jaeger_storage.backends` объявляются именованные конфигурации баз данных. Это позволяет одновременно иметь несколько подключений (например, `clickhouse_write` для коллектора и `clickhouse_readonly` для интерфейса поиска).
2. **Связывание компонентов:** Экспортер `jaeger_storage_exporter` ссылается на имя бэкенда через атрибут `trace_storage: <backend_name>`. Сервис `jaeger_query` ссылается на этот же или другой бэкенд через `storage.traces: <backend_name>`.
3. **Пул соединений и Keep-Alive:** Расширение удерживает постоянные TCP/HTTP соединения с базой, переиспользуя сокеты между пачками спанов и снижая задержки handshake.
4. **Очереди и повторные попытки (Retry & Queueing):** Если база данных отвечает отказом или сетевым таймаутом, `jaeger_storage_exporter` сохраняет пачки во внутренней очереди памяти (`queue_size`), выполняя экспоненциальные повторы (`retry_on_failure`).

---

### ClickHouse Deep Dive

ClickHouse является рекомендуемым бэкендом хранения для Jaeger v2 благодаря колоночной компрессии, высокой скорости вставки и отсутствию накладных расходов виртуальной машины Java.

#### 1. Устройство движка MergeTree для телеметрии

В ClickHouse данные сохраняются в виде физических директорий — частей (parts). При каждой операции записи (`INSERT`) формируется новая часть данных, состоящая из сжатых столбцов (`.bin`), файлов засечек разреженного индекса (`.mrk`) и файла первичного ключа (`primary.idx`). Фоновый процесс ClickHouse непрерывно объединяет мелкие части в крупные (background merge), применяя сортировку и сжатие.

```
/var/lib/clickhouse/data/jaeger_v2/spans/
├── 20261012_20261012_1_1_0/             # Новая несмерженная часть данных (part)
│   ├── checksums.txt
│   ├── columns.txt
│   ├── count.txt
│   ├── default_compression_codec.txt
│   ├── primary.idx                     # Разреженный индекс первичного ключа
│   ├── trace_id.bin                    # Сжатые данные колонки trace_id
│   ├── trace_id.mrk2                   # Файл засечек гранул для trace_id
│   ├── service_name.bin
│   ├── service_name.mrk2
│   └── start_time.bin
└── 20261012_20261012_1_50_3/            # Результат фонового слияния 50 частей
```

#### 2. Проектирование первичного ключа и порядка сортировки

В ClickHouse существует строгое правило: **значения `PRIMARY KEY` обязаны быть префиксом кортежа `ORDER BY`**. Нарушение этого правила приводит к синтаксической ошибке при создании таблицы.
- **`ORDER BY`:** Физический порядок сортировки строк на диске внутри каждой части.
- **`PRIMARY KEY`:** Индекс, загружаемый в оперативную память. Содержит одну запись на каждые 8192 строки (гранула).

Для поиска трейсов в Jaeger характерны два паттерна запросов:
1. **Поиск списка трейсов:** фильтрация по `service_name`, `operation_name`, временному окну `start_time` и длительности `duration`.
2. **Получение деталей конкретного трейса:** точечная выборка всех спанов по `trace_id`.

Оптимальный порядок сортировки:
```sql
ORDER BY (service_name, operation_name, toUnixTimestamp(timestamp), trace_id)
```
При таком порядке поиск спанов определенного сервиса за временной интервал считывает только непрерывные гранулы с диска.

#### 3. Вторичные индексы пропуска данных (Data Skipping Indices)

Для мгновенного нахождения спанов по `trace_id` без полного сканирования таблицы (Full Table Scan) накладывается индекс типа **Bloom Filter**:
```sql
INDEX idx_trace_id trace_id TYPE bloom_filter(0.01) GRANULARITY 1
```
Параметр `0.01` задает вероятность ложноположительного срабатывания (1%). Гранулярность `1` означает создание фильтра Блума для каждой гранулы данных (8192 строк). При поиске по `WHERE trace_id = '...'` ClickHouse вычисляет хеш и отбрасывает 99% гранул без обращения к диску.

Для фильтрации по произвольным тегам спанов (`Map(LowCardinality(String), String)`) создаются индексы на ключи и значения:
```sql
INDEX idx_tags_keys mapKeys(tags) TYPE bloom_filter(0.01) GRANULARITY 1,
INDEX idx_tags_values mapValues(tags) TYPE bloom_filter(0.01) GRANULARITY 1
```

#### 4. Партиционирование и удаление данных по TTL

Партиционирование разделяет данные таблицы на изолированные папки по суткам:
```sql
PARTITION BY toDate(timestamp)
```
- **Запрет мелкого партиционирования:** Не используйте партиционирование по часам (`toHour()`) или сервисам (`service_name`). Это порождает десятки тысяч мелких частей, перегружает ClickHouse Keeper и вызывает ошибку `Too many parts in all data parts in table (252)`.
- **TTL с отбрасыванием целых частей:** Настройка `SETTINGS ttl_only_drop_parts = 1` предписывает ClickHouse удалять партицию целиком путем удаления директории в файловой системе сразу после того, как максимальная дата в ней превысила интервал TTL. Это исключает фоновые сканирования строк и не создает дисковой нагрузки.

---

### Elasticsearch / OpenSearch Deep Dive

Elasticsearch и OpenSearch востребованы в организациях, где трассировка объединяется с логами в рамках единого хранилища OpenSearch/Elastic с поддержкой полнотекстового поиска по содержимому payload.

#### 1. Инвертированный индекс и `doc_values`

В архитектуре Apache Lucene (ядро Elasticsearch):
- **Инвертированный индекс:** Используется для поиска спанов по тегам. Каждое строковое значение разбирается на токены и вносится в словарь. Полнотекстовый тип `text` требует значительных объемов heap-памяти для построения сегментов. Для сервисов и тегов трассировки **обязателен тип `keyword`**, индексирующий строку целиком без токенизации.
- **`doc_values`:** Столбчатое представление значений полей, сохраняемое на диске параллельно с инвертированным индексом. Используется Jaeger Query для агрегаций (подсчет латентности p95, группировка операций, расчет графа сервисов). Поля с типом `keyword` и числовые поля имеют `doc_values` включенными по умолчанию.

#### 2. Маппинг и Composable Index Templates

В Jaeger v2 рекомендуется использовать потоки данных (Data Streams) либо индексные шаблоны `_index_template/jaeger_v2` с фиксированным маппингом. Динамический маппинг (`"dynamic": false` или `"dynamic": "runtime"`) предотвращает проблему "mapping explosion" (разрастание структуры метаданных кластера при передаче тысячами сервисов случайных тегов).

Структура тегов должна моделироваться через тип `nested`, если требуется точное соответствие пар "ключ-значение" в рамках одного спана:
```json
"tags": {
  "type": "nested",
  "properties": {
    "key": { "type": "keyword" },
    "value": { "type": "keyword", "ignore_above": 1024 }
  }
}
```

#### 3. Политики жизненного цикла (ILM / ISM)

Управление ротацией индексов спанов настраивается через многоуровневую модель:
- **Hot-фаза:** Запись новых спанов. Ротация (Rollover) выполняется по достижению размера шарда 30–50 ГБ либо возраста 1 сутки (`max_primary_shard_size: 50gb`, `max_age: 1d`).
- **Warm-фаза:** Спустя 2–7 дней индексы переносятся на более медленные дисковые массивы. Выполняется принудительное сжатие шардов (`shrink: 1`) и слияние сегментов (`force_merge: 1`) для освобождения памяти и ускорения чтения.
- **Delete-фаза:** Полное удаление индексов по достижении установленного срока хранения (например, `min_age: 14d`).

---

### Apache Cassandra Deep Dive

Apache Cassandra — исторически первый production-бэкенд Jaeger. Построен на архитектуре распределенного LSM-дерева без единой точки отказа (Masterless Peer-to-Peer).

#### 1. Механизм Time Window Compaction Strategy (TWCS)

Для данных трассировки использование стандартных стратегий компактизации (SizeTieredCompactionStrategy или LeveledCompactionStrategy) в production недопустимо:
- **Проблема STCS/LCS:** Спаны непрерывно объединяются между собой, перемешивая старые и новые записи внутри одних и тех же SSTable. В результате при наступлении TTL на отдельные спаны Cassandra создает маркеры удаления (tombstones). Чтобы освободить место, СУБД вынуждена непрерывно перезаписывать терабайты данных, вызывая деградацию дискового ввода-вывода (Write Amplification > 30).
- **Решение TWCS:** Данные группируются в отдельные SSTable строго по временным окнам поступления (например, 1 день). В течение текущего дня файлы объединяются по размеру, а по завершении суток окно закрывается и SSTable становится неизменяемой (frozen). Когда истекает срок `default_time_to_live` для этого окна, Cassandra просто удаляет весь файл SSTable из файловой системы без чтения, без создания tombstones и без дополнительной нагрузки на диск.

#### 2. Проблема и предотвращение надгробных камней (Tombstones)

Tombstone в Cassandra генерируется при удалении строки, ячейки или при истечении срока TTL отдельной колонки. При чтении трейса по `trace_id` координатор сканирует диапазон колонок. Если на пути встречается множество tombstones, узел расходует память и CPU на их фильтрацию.
- При достижении `tombstone_warn_threshold` (по умолчанию 1000) узел записывает предупреждение в лог.
- При достижении `tombstone_failure_threshold` (по умолчанию 100 000) запрос немедленно завершается с ошибкой `ReadFailureException: TombstoneOverwhelmingException`.
- **Правило для трассировки:** Всегда задавайте `default_time_to_live` на уровне таблицы целиком, применяйте TWCS с размером окна в 1 сутки и снижайте параметр `gc_grace_seconds` до 3600 (1 час) или 0 (если в кластере настроен ежедневный repair).

---

### Badger и In-Memory Deep Dive

#### 1. In-Memory бэкенд

Реализован внутри процесса Jaeger на базе ring-буферов и map в оперативной памяти.
- **Особенности:** Не требует дисковых операций и внешних СУБД. Максимальная скорость обработки спанов.
- **Ограничения:** Полная потеря данных при перезапуске контейнера или процесса. Ограничен лимитом RAM процесса.
- **Область применения:** Локальная разработка микросервисов, smoke-тестирование в CI/CD конвейерах.

#### 2. Badger (Embedded KV Store)

Badger — это библиотека Go, реализующая LSM-хранилище (LSM-tree с разделением ключей и значений по модели WiscKey). Хранилище работает локально внутри бинарного файла Jaeger v2.
- **Архитектура:** Ключи спанов хранятся в упорядоченном LSM-дереве на диске, а тела спанов (payload) записываются в журнал значений (Value Log, Vlog). Это минимизирует Write Amplification на твердотельных накопителях NVMe.
- **Разделение директорий:** Позволяет хранить индекс (`directory_key`) на ультрабыстром NVMe-диске, а значения (`directory_value`) — на более емком накопителе.
- **Периодическая компактизация:** Фоновый процесс (`maintenance_interval: 5m`) выполняет сжатие Value Log, удаляя устаревшие спаны в соответствии с TTL.
- **Область применения:** Edge-узлы, автономные серверы, изолированные стенды разработки без внешней инфраструктуры СУБД.

---

### Apache Kafka Deep Dive (Буферизация и стриминг)

В крупных enterprise-инфраструктурах с миллионными потоками спанов прямое подключение коллекторов к базам данных создает риск отказа: всплеск трафика или временная деградация базы (например, перестроение индексов в ES или слияние партиций в ClickHouse) приводит к исчерпанию очередей коллектора и потере трейсов.

Apache Kafka внедряется как промежуточный амортизационный буфер между **Collector** (роль Producer) и **Ingester** (роль Consumer):

```
[OTel SDKs] ──► [Jaeger Collectors] ──(Produce: OTLP/LZ4)──► [Kafka Topic: jaeger-spans]
                                                                        │
                                                              (Consume: Group jaeger-ingester)
                                                                        ▼
                                                             [Jaeger Ingesters] ──(Batch)──► [ClickHouse / ES]
```

#### 1. Расчет количества партиций

Количество партиций в топике `jaeger-spans` рассчитывается исходя из максимальной пропускной способности одного потока Ingester:
$$N_{\text{partitions}} = \max\left(\frac{\text{Peak Throughput (spans/s)}}{C_{\text{consumer\_thread\_capacity}}}, N_{\text{collector\_instances}}\right)$$
На практике один поток Ingester способен десериализовать и батчировать в ClickHouse около 5000–8000 спанов в секунду. Для пиковой нагрузки 100 000 спанов/с требуется минимум 16–20 партиций и аналогичное количество воркеров консьюмера.

#### 2. Компрессия и сегментация

- **Компрессия на уровне Producer:** Использование `lz4` или `zstd` на стороне Collector уменьшает сетевой трафик между дата-центрами в 3–5 раз и экономит дисковое пространство брокеров Kafka.
- **Retention логов:** Задавайте время хранения в Kafka на уровне 24–48 часов (`retention.ms=172800000`). Kafka — это буфер поглощения пиков и аварий СУБД, а не долговременное хранилище трейсов.

#### 3. Семантика коммита Offset и управление Lag

- **At-least-once доставка:** Ingester считывает спаны пачками, формирует bulk-запрос в ClickHouse/Elasticsearch и коммитит смещение (`commit offset`) только **после получения успешного подтверждения** от базы данных.
- **Идемпотентность:** Запись спанов в ClickHouse (по первичному ключу `trace_id, span_id`) и Elasticsearch (по `_id = span_id`) идемпотентна: повторное считывание сообщений из Kafka при аварийном перезапуске Ingester не создает дубликатов в базе данных.

---

## Практические сценарии, развертывание и настройка

### Сценарий 1: Развертывание и оптимизация ClickHouse для Jaeger v2

**Цель:** Создать production-схему в ClickHouse с поддержкой эффективных вторичных индексов, политик TTL и настроить Jaeger v2 для безопасной записи и выборки спанов.

#### 1. Подготовка схемы и прав доступа в ClickHouse

```bash
# Подключение к ClickHouse через CLI и создание базы данных
clickhouse-client --user default --query "CREATE DATABASE IF NOT EXISTS jaeger_v2;"
```

Создание основной таблицы спанов с оптимизированными типами данных, сжатием и индексами пропуска:

```sql
-- Выполняется в clickhouse-client
CREATE TABLE IF NOT EXISTS jaeger_v2.spans
(
    timestamp DateTime64(6) CODEC(DoubleDelta, LZ4),
    trace_id String CODEC(ZSTD(1)),
    span_id String CODEC(ZSTD(1)),
    parent_span_id String CODEC(ZSTD(1)),
    operation_name LowCardinality(String) CODEC(ZSTD(1)),
    service_name LowCardinality(String) CODEC(ZSTD(1)),
    duration_us UInt64 CODEC(T64, ZSTD(1)),
    tags Map(LowCardinality(String), String) CODEC(ZSTD(1)),
    logs Nested(
        timestamp DateTime64(6),
        fields Map(LowCardinality(String), String)
    ) CODEC(ZSTD(1)),
    flags UInt32 CODEC(T64, ZSTD(1)),
    
    -- Вторичные индексы пропуска данных (Data Skipping Indices)
    INDEX idx_trace_id trace_id TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_tags_keys mapKeys(tags) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_tags_values mapValues(tags) TYPE bloom_filter(0.01) GRANULARITY 1,
    INDEX idx_duration duration_us TYPE minmax GRANULARITY 1
)
ENGINE = MergeTree()
PARTITION BY toDate(timestamp)
ORDER BY (service_name, operation_name, toUnixTimestamp(timestamp), trace_id)
TTL toDateTime(timestamp) + INTERVAL 7 DAY
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
```

Создание сервисных учетных записей с разграничением прав (принцип наименьших привилегий):

```sql
-- Пользователь для записи (Jaeger Collector / Ingester)
CREATE USER IF NOT EXISTS jaeger_writer IDENTIFIED WITH sha256_password BY 'WriterSecretPassword123';
GRANT SELECT, INSERT ON jaeger_v2.* TO jaeger_writer;

-- Пользователь для чтения (Jaeger Query UI)
CREATE USER IF NOT EXISTS jaeger_reader IDENTIFIED WITH sha256_password BY 'ReaderSecretPassword123';
GRANT SELECT ON jaeger_v2.* TO jaeger_reader;
```

#### 2. Конфигурация Jaeger v2 (`config-clickhouse.yaml`)

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 500ms
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_size: 4096
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_prod:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "WriterSecretPassword123"
          connection_params:
            dial_timeout: "5s"
            compress: "lz4"
  jaeger_query:
    storage:
      traces: clickhouse_prod
    http:
      endpoint: 0.0.0.0:16686

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_prod
    queue:
      num_consumers: 16
      queue_size: 5000
    retry_on_failure:
      enabled: true
      initial_interval: 1s
      max_interval: 10s
      max_elapsed_time: 30s

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [jaeger_storage_exporter]
```

#### 3. Проверка работоспособности

```bash
# Проверка поступления спанов в таблицу
clickhouse-client --user jaeger_reader --password ReaderSecretPassword123 --query "
SELECT service_name, count() AS total_spans 
FROM jaeger_v2.spans 
GROUP BY service_name 
ORDER BY total_spans DESC 
LIMIT 5;
"
# → frontend      45200
# → order-service 31100
# → auth-service  12450
```

---

### Сценарий 2: Развертывание и настройка Elasticsearch / OpenSearch с ILM

**Цель:** Сконфигурировать Composable Index Template и политику ILM в Elasticsearch для хранения спанов с автоматической ротацией, сжатием сегментов и удалением через 14 дней.

#### 1. Создание политики ILM (`jaeger_policy`)

```bash
curl -X PUT "http://192.168.10.15:9200/_ilm/policy/jaeger_policy" \
     -H "Content-Type: application/json" \
     -d '{
  "policy": {
    "phases": {
      "hot": {
        "min_age": "0ms",
        "actions": {
          "rollover": {
            "max_primary_shard_size": "50gb",
            "max_age": "1d"
          },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "2d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "delete": {
        "min_age": "14d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}'
# → {"acknowledged":true}
```

#### 2. Создание индексного шаблона (`_index_template/jaeger_v2`)

```bash
curl -X PUT "http://192.168.10.15:9200/_index_template/jaeger_v2" \
     -H "Content-Type: application/json" \
     -d '{
  "index_patterns": ["jaeger-v2-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "index.refresh_interval": "30s",
      "index.lifecycle.name": "jaeger_policy",
      "index.lifecycle.rollover_alias": "jaeger-v2"
    },
    "mappings": {
      "dynamic": false,
      "properties": {
        "traceID": { "type": "keyword" },
        "spanID": { "type": "keyword" },
        "parentSpanID": { "type": "keyword" },
        "operationName": { "type": "keyword" },
        "serviceName": { "type": "keyword" },
        "startTime": { "type": "date_nanos" },
        "duration": { "type": "long" },
        "tags": {
          "type": "nested",
          "properties": {
            "key": { "type": "keyword" },
            "value": { "type": "keyword", "ignore_above": 1024 }
          }
        }
      }
    }
  }
}'
# → {"acknowledged":true}
```

#### 3. Инициализация первичного индекса с alias

```bash
curl -X PUT "http://192.168.10.15:9200/jaeger-v2-000001" \
     -H "Content-Type: application/json" \
     -d '{
  "aliases": {
    "jaeger-v2": {
      "is_write_index": true
    }
  }
}'
# → {"acknowledged":true,"shards_acknowledged":true,"index":"jaeger-v2-000001"}
```

#### 4. Конфигурация Jaeger v2 с Elasticsearch бэкендом

```yaml
extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      es_cluster:
        elasticsearch:
          server_urls:
            - "http://192.168.10.15:9200"
            - "http://192.168.10.16:9200"
          index_prefix: "jaeger-v2"
          username: "jaeger_writer"
          password: "${env:ES_PASSWORD}"
          num_shards: 3
          num_replicas: 1
  jaeger_query:
    storage:
      traces: es_cluster
    http:
      endpoint: 0.0.0.0:16686

exporters:
  jaeger_storage_exporter:
    trace_storage: es_cluster
    queue:
      num_consumers: 8
      queue_size: 2000

service:
  extensions: [healthcheckv2, jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

---

### Сценарий 3: Развертывание Apache Cassandra с Time Window Compaction Strategy (TWCS)

**Цель:** Создать Keyspace и таблицы для спанов Jaeger с TWCS, исключающей генерацию tombstones и скачки дисковой нагрузки при истечении TTL.

#### 1. Создание схемы данных в `cqlsh`

```sql
-- 1. Создание Keyspace с репликацией по дата-центрам
CREATE KEYSPACE IF NOT EXISTS jaeger_v2
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'dc1': 3
};

-- 2. Создание таблицы спанов с TWCS и суточным окном
CREATE TABLE IF NOT EXISTS jaeger_v2.spans
(
    trace_id blob,
    span_id bigint,
    parent_id bigint,
    operation_name text,
    service_name text,
    flags int,
    start_time bigint,
    duration bigint,
    tags map<text, text>,
    logs text,
    PRIMARY KEY (trace_id, span_id)
)
WITH default_time_to_live = 604800
AND gc_grace_seconds = 86400
AND compaction = {
    'class': 'org.apache.cassandra.db.compaction.TimeWindowCompactionStrategy',
    'compaction_window_unit': 'DAYS',
    'compaction_window_size': '1',
    'timestamp_resolution': 'MICROSECONDS'
};
```

#### 2. Подключение в конфигурации Jaeger v2

```yaml
extensions:
  jaeger_storage:
    backends:
      cassandra_prod:
        cassandra:
          servers: ["192.168.10.51", "192.168.10.52", "192.168.10.53"]
          port: 9042
          keyspace: "jaeger_v2"
          local_dc: "dc1"
          connections_per_host: 4
          timeout: "5s"
```

---

### Сценарий 4: Настройка высокопроизводительного конвейера Kafka + Ingester

**Цель:** Развернуть отказоустойчивый конвейер с Kafka-буфером для изоляции ClickHouse от пиков нагрузки.

#### 1. Создание топика `jaeger-spans` в Apache Kafka

```bash
# Создание топика на 16 партиций с фактором репликации 3 и сжатием LZ4
kafka-topics.sh --bootstrap-server 192.168.10.31:9092 --create \
  --topic jaeger-spans \
  --partitions 16 \
  --replication-factor 3 \
  --config retention.ms=172800000 \
  --config segment.bytes=1073741824 \
  --config compression.type=lz4 \
  --config min.insync.replicas=2
# → Created topic jaeger-spans.
```

#### 2. Конфигурация узла Jaeger Collector (Producer)

```yaml
# /etc/jaeger/collector.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  memory_limiter:
    check_interval: 200ms
    limit_percentage: 80
    spike_limit_percentage: 20
  batch:
    send_batch_size: 8192
    timeout: 500ms

exporters:
  kafka:
    brokers: ["192.168.10.31:9092", "192.168.10.32:9092", "192.168.10.33:9092"]
    topic: "jaeger-spans"
    encoding: "otlp_proto"
    compression: "lz4"
    producer:
      max_message_bytes: 4194304
      required_acks: -1

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [kafka]
```

#### 3. Конфигурация узла Jaeger Ingester (Consumer)

```yaml
# /etc/jaeger/ingester.yaml
receivers:
  kafka:
    brokers: ["192.168.10.31:9092", "192.168.10.32:9092", "192.168.10.33:9092"]
    topic: "jaeger-spans"
    encoding: "otlp_proto"
    group_id: "jaeger-ingester"
    autocommit:
      enable: false

processors:
  batch:
    send_batch_size: 16384
    timeout: 1s

extensions:
  healthcheckv2:
    endpoint: 0.0.0.0:13133
  jaeger_storage:
    backends:
      clickhouse_target:
        clickhouse:
          endpoint: "tcp://192.168.10.20:9000"
          database: "jaeger_v2"
          username: "jaeger_writer"
          password: "WriterSecretPassword123"

exporters:
  jaeger_storage_exporter:
    trace_storage: clickhouse_target
    queue:
      num_consumers: 32
      queue_size: 10000

service:
  extensions: [healthcheckv2, jaeger_storage]
  pipelines:
    traces:
      receivers: [kafka]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
```

---

### Сценарий 5: Бесшовный перенос и Dual-Write миграция между хранилищами

**Цель:** Перевести поток спанов со старого кластера Elasticsearch на новый ClickHouse без остановки приема данных и без разрыва трейсов.

В Jaeger v2 стратегия параллельной записи (Dual-Write) реализуется добавлением нескольких экспортеров в один конвейер `traces`:

```yaml
exporters:
  jaeger_storage_exporter/es_legacy:
    trace_storage: es_old_backend
    queue:
      queue_size: 2000

  jaeger_storage_exporter/clickhouse_new:
    trace_storage: clickhouse_new_backend
    queue:
      queue_size: 5000

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters:
        - jaeger_storage_exporter/es_legacy
        - jaeger_storage_exporter/clickhouse_new
```
После завершения срока хранения старых спанов в Elasticsearch (например, через 14 дней) экспортер `jaeger_storage_exporter/es_legacy` удаляется из YAML-манифеста, а кластер Elasticsearch выводится из эксплуатации.

---

## Операции и команды администрирования хранилищ

### ClickHouse: Мониторинг и обслуживание

```bash
# 1. Проверка количества частей (parts) и размера таблицы по партициям
clickhouse-client --query "
SELECT 
    partition,
    count() AS parts_count,
    formatReadableSize(sum(bytes_on_disk)) AS disk_size,
    sum(rows) AS total_rows
FROM system.parts
WHERE database = 'jaeger_v2' AND table = 'spans' AND active = 1
GROUP BY partition
ORDER BY partition DESC;
"
# → 20261012   12   42.15 GiB   125040000
# → 20261011   4    41.80 GiB   124100000

# 2. Мониторинг фоновых процессов слияния частей (Merges)
clickhouse-client --query "
SELECT 
    table, 
    elapsed, 
    progress, 
    num_parts, 
    result_part_name, 
    formatReadableSize(total_size_bytes_compressed) AS size
FROM system.merges
WHERE database = 'jaeger_v2';
"

# 3. Ручной форсированный сброс устаревшей суточной партиции (в случае аварийной нехватки диска)
clickhouse-client --query "ALTER TABLE jaeger_v2.spans DROP PARTITION '20260901';"
# → Ok.
```

### Elasticsearch / OpenSearch: Аудит и обслуживание

```bash
# 1. Проверка состояния шардов и кластера
curl -s "http://192.168.10.15:9200/_cat/shards/jaeger-v2*?v&s=store:desc" | head -n 5
# → index            shard prirep state   docs   store ip            node
# → jaeger-v2-000002 0     p      STARTED 14.5m 32.1gb 192.168.10.15 data-node-1
# → jaeger-v2-000002 0     r      STARTED 14.5m 32.1gb 192.168.10.16 data-node-2

# 2. Проверка статуса выполнения ILM для текущего индекса
curl -s "http://192.168.10.15:9200/jaeger-v2-000002/_ilm/explain?pretty"
# → "phase" : "hot", "action" : "rollover", "step" : "check-rollover-ready"

# 3. Принудительное слияние сегментов (Force Merge) для ротированного индекса
curl -X POST "http://192.168.10.15:9200/jaeger-v2-000001/_forcemerge?max_num_segments=1"
# → {"_shards":{"total":3,"successful":3,"failed":0}}
```

### Apache Cassandra: Проверка здоровья и tombstones

```bash
# 1. Статус узлов кластера
nodetool status jaeger_v2
# → Datacenter: dc1
# → Status=Up/Down, State=Normal/Leaving/Joining/Moving
# → UN  192.168.10.51  412.5 GiB  256  49.2%  Rack1

# 2. Проверка плотности tombstones и размера SSTables
nodetool tablestats jaeger_v2.spans
# → Keyspace : jaeger_v2
# → Table : spans
# → Space used (total) : 442918239012
# → Average tombstones per slice : 0.01 (норма: < 10)
# → Maximum tombstones per slice : 2

# 3. Запуск плановой компактизации таблицы
nodetool compact jaeger_v2 spans
```

### Apache Kafka: Аудит консьюмер-группы Ingester

```bash
# 1. Проверка текущего отставания (Lag) по всем партициям
kafka-consumer-groups.sh --bootstrap-server 192.168.10.31:9092 \
  --describe --group jaeger-ingester
# → GROUP           TOPIC        PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG             CONSUMER-ID
# → jaeger-ingester jaeger-spans 0          84920192        84920200        8               ingester-node-1_...
# → jaeger-ingester jaeger-spans 1          85100412        85100415        3               ingester-node-2_...

# 2. Изменение времени хранения (retention) топика на лету без перезапуска брокеров
kafka-configs.sh --bootstrap-server 192.168.10.31:9092 --alter \
  --entity-type topics --entity-name jaeger-spans \
  --add-config retention.ms=86400000
# → Completed updating config for topic jaeger-spans.
```

---

## Диагностика и устранение неисправностей

| Проблема / Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **ClickHouse: `Code: 252. Too many parts in all data parts in table`** | Слишком частая вставка мелкими пачками; фоновый процесс слияния не успевает объединять части (лимит > 300 частей на партицию) | `journalctl -u clickhouse-server \| grep "Too many parts"`<br>или запрос:<br>`SELECT count() FROM system.parts WHERE active=1 AND database='jaeger_v2'` | 1. Увеличить `send_batch_size` до `8192`–`16384` и `timeout` до `1s`–`2s` в `batch` процессоре коллектора.<br>2. Включить `async_insert = 1` в параметрах подключения.<br>3. Временно поднять `max_parts_in_total` в ClickHouse `merge_tree`. |
| **Elasticsearch: `429 Too Many Requests / EsRejectedExecutionException`** | Переполнение очереди пула потоков `write` из-за исчерпания дисковых IOPS или слишком частого обновления индексов | Запрос состояния пула потоков:<br>`GET _nodes/stats/thread_pool/write`<br>где `rejected > 0` | 1. Увеличить `index.refresh_interval` в шаблоне с `1s` до `30s` или `60s`.<br>2. Увеличить размер пачки в коллекторе.<br>3. Разнести primary и replica шарды на выделенные NVMe-диски. |
| **Elasticsearch: Сбой по OOM (JVM OutOfMemoryError) и зависание GC** | Раздувание инвертированного индекса строковых полей высокой кардинальности (High-cardinality tags) | Анализ heap памяти ноды:<br>`GET _nodes/stats/jvm`<br>Логи: `java.lang.OutOfMemoryError: Java heap space` | 1. Запретить динамический маппинг (`dynamic: false`).<br>2. Добавить `ignore_above: 1024` для строковых тегов.<br>3. Вычищать высококардинальные теги (`user_id`, UUID) через `attributes` процессор в Jaeger Collector. |
| **Cassandra: `ReadFailureException: TombstoneOverwhelmingException`** | Сканирование диапазона натыкается на более чем 100 000 маркеров удаления из-за неэффективной компактизации | Просмотр логов Cassandra:<br>`grep -i "tombstone" /var/log/cassandra/system.log` | 1. Перевести таблицу на стратегию `TimeWindowCompactionStrategy` (TWCS).<br>2. Проверить `nodetool tablestats` на среднее число tombstones.<br>3. Не удалять спаны единичными операциями `DELETE`. |
| **Kafka: Лаг консьюмер-группы `jaeger-ingester` лавинообразно растет** | Скорость вставки в СУБД ниже входящего потока спанов; блокировка соединений; частые rebalance группы | Проверка лага:<br>`kafka-consumer-groups.sh --describe --group jaeger-ingester`<br>Метрика: `otelcol_receiver_accepted_spans` vs exporter | 1. Увеличить количество реплик Ingester до числа партиций топика.<br>2. Проверить дисковую очередь СУБД (ClickHouse IOPS).<br>3. Перевести консьюмер на `cooperative-sticky` протокол распределения партиций. |
| **Jaeger Collector: Рост счетчика `otelcol_exporter_enqueue_failed_spans`** | Переполнение внутренней памяти очереди экспортера из-за деградации бэкенда хранения | Мониторинг Prometheus:<br>`rate(otelcol_exporter_enqueue_failed_spans[1m]) > 0` | 1. Увеличить `queue_size` в `jaeger_storage_exporter`.<br>2. Увеличить число потребителей `num_consumers`.<br>3. Включить буферизацию через Kafka, изолируя коллекторы от задержек СУБД. |
| **Jaeger UI: Задержка выборки трейса > 10 секунд (Timeout)** | Запрос выполняет Full Table Scan в ClickHouse/ES из-за отсутствия вторичного индекса по искомому атрибуту | Анализ системных логов СУБД:<br>`SELECT query_duration_ms, read_rows FROM system.query_log WHERE type='QueryFinish'` | 1. Проверить наличие индекса `bloom_filter` на колонку `trace_id` и `tags`.<br>2. Ограничивать интервал поиска в UI короткими временными окнами (до 1–2 часов). |

---

## Лучшие практики эксплуатации (SRE & DevOps)

### 1. Архитектурный выбор бэкенда для On-Premise

- **По умолчанию выбирайте ClickHouse:** Для новых инсталляций ClickHouse превосходит альтернативы по плотности хранения данных (экономия до 70% диска по сравнению с Elasticsearch) и пропускной способности при значительно меньших требованиях к CPU/RAM.
- **Используйте Kafka при высоких пиках:** Если пиковый входящий трафик превышает средний более чем в 3 раза (распродажи, инциденты, всплески ошибок), использование Kafka в качестве буфера между Collector и Ingester обязательно.
- **Изолируйте узлы Query от узлов Ingestion:** Направляйте запросы UI и Grafana на выделенные read-only реплики ClickHouse или узлы-координаторы Elasticsearch, чтобы тяжелые аналитические запросы инженеров не замедляли запись новых спанов.

### 2. Тюнинг дисковой подсистемы и параметров Linux

```bash
# Оптимальные параметры sysctl для нод хранения (/etc/sysctl.d/99-storage.conf)
# Разрешение выделения достаточного числа областей виртуальной памяти (критично для ES и CH)
vm.max_map_count = 1048576

# Снижение агрессивности вытеснения страниц памяти в swap
vm.swappiness = 1

# Контроль грязных страниц памяти для предотвращения зависания дисковых сбросов
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10

# Увеличение сетевых очередей для интенсивного OTLP/gRPC трафика
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384
```

- **Файловая система:** Используйте **XFS** с опциями монтирования `noatime,nodiratime,logbufs=8,logbsize=256k`.
- **Дисковые накопители:** Базы данных трассировки генерируют высокую нагрузку на последовательную и произвольную запись; используйте локальные Enterprise NVMe накопители с защитой от потери питания (PLP). Избегайте сетевых блочных устройств с ограничением по IOPS.

### 3. Санитайзинг тегов и фильтрация High Cardinality

Большинство проблем с памятью и производительностью баз данных вызваны бесконтрольной отправкой уникальных тегов (`user_id`, `jwt_token`, `request_body`). Санитайзинг выполняется на уровне Jaeger Collector с помощью стандартных процессоров OTel:

```yaml
processors:
  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          # Удаление высококардинальных персональных данных
          - delete_key(attributes, "http.request.body")
          - delete_key(attributes, "user.auth_token")
          # Маскирование IP-адресов
          - replace_pattern(attributes["client.ip"], "^([0-9]+\\.[0-9]+)\\..*", "$$1.0.0")
```

### 4. Стратегии Retention и удаление данных

- **Никогда не удаляйте спаны построчно:** Операторы `DELETE FROM spans WHERE timestamp < ...` вызывают тяжелые блокировки, перестроение LSM-деревьев и деградацию файловой системы.
- **Удаляйте только партициями или индексами:**
  - В ClickHouse: через директиву `TTL toDateTime(timestamp) + INTERVAL N DAY` с параметром `SETTINGS ttl_only_drop_parts = 1`.
  - В Elasticsearch: через действие `delete` в ILM политике для целых индексов.
  - В Cassandra: только через Time Window Compaction Strategy (TWCS).
  - В Kafka: через ротацию сегментов `retention.ms` и `retention.bytes`.

### 5. Ключевые SRE-метрики для алертинга

| Метрика | Источник | Порог для алерта | Описание |
| :--- | :--- | :--- | :--- |
| `otelcol_exporter_enqueue_failed_spans` | Collector | `rate(...) > 0` в течение 1 мин | Сброс спанов из-за переполнения очередей перед хранилищем |
| `otelcol_exporter_send_failed_spans` | Collector | `rate(...) > 1%` от входящих спанов | Ошибки записи непосредственно в СУБД (таймауты, сетевые сбои) |
| `kafka_consumergroup_lag` | Kafka Exporter | `lag > 50000` и монотонно растет | Отставание консьюмеров Ingester от скорости входящего потока |
| `clickhouse_system_parts_count` | ClickHouse | `parts > 250` на одну партицию | Угроза ошибки 252 (слишком много частей данных) |
| `elasticsearch_threadpool_write_rejected` | ES Exporter | `rate(...) > 0` | Переполнение очереди записи Elasticsearch |
| `jaeger_storage_read_latency_seconds` | Jaeger Query | `p95 > 2.0s` | Деградация скорости чтения из хранилища при запросах UI |

---

## Очистка тестового окружения

```bash
# 1. Остановка процессов Jaeger и зависимостей в Docker Compose
docker compose -f docker-compose-storage.yaml down -v

# 2. Удаление тестовых постоянных томов ClickHouse и Elasticsearch
docker volume rm jaeger_clickhouse_data jaeger_elasticsearch_data jaeger_kafka_data

# 3. Удаление тестовой базы данных в ClickHouse (если тестирование шло на выделенном сервере)
clickhouse-client --query "DROP DATABASE IF EXISTS jaeger_v2;"

# 4. Удаление тестовых индексов и политик в Elasticsearch
curl -X DELETE "http://192.168.10.15:9200/jaeger-v2-*"
curl -X DELETE "http://192.168.10.15:9200/_index_template/jaeger_v2"
curl -X DELETE "http://192.168.10.15:9200/_ilm/policy/jaeger_policy"

# 5. Удаление топика в Apache Kafka
kafka-topics.sh --bootstrap-server 192.168.10.31:9092 --delete --topic jaeger-spans
# → Topic jaeger-spans is marked for deletion.
```

---

## Дополнительная информация

**Смежные материалы по Jaeger:**
- Общие концепции и компоненты трассировки: **[Обзор Jaeger](./jaeger_overview.md)**
- Детализация конвейеров и расширений: **[Архитектура Jaeger](./jaeger_architecture.md)**
- Топологии развертывания и orchestration: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
- Расчет сайзинга CPU, RAM и IOPS: **[Capacity Planning для Jaeger](./jaeger_capacity_planning.md)**
- Перевод инфраструктуры с v1 на v2: **[Миграция с Jaeger v1 на v2](./jaeger_migration_v1_to_v2.md)**
- Высокая доступность и отказоустойчивость: **[Отказоустойчивость Jaeger](./jaeger_high_availability.md)**
- Спецификация API чтения и поиска трейсов: **[Jaeger Query API](./jaeger_query_api.md)**
- Защита данных, mTLS и авторизация: **[Безопасность и харденинг Jaeger](./jaeger_security_hardening.md)**

**Смежные материалы по СУБД и брокерам:**
- Обзор архитектуры ClickHouse: **[ClickHouse: Обзор](../Databases/ClickHouse/clickhouse.md)**
- Кластеризация и репликация MergeTree: **[ClickHouse: Кластер и репликация](../Databases/ClickHouse/clickhouse-cluster.md)**
- Моделирование данных и движки таблиц: **[ClickHouse: Моделирование данных](../Databases/ClickHouse/clickhouse-data-modeling.md)**
- Архитектура и эксплуатация Apache Cassandra: **[Cassandra: Архитектура](../Databases/cassandra-scylladb/architecture.md)**
- Администрирование и nodetool в Cassandra: **[Cassandra: Эксплуатация](../Databases/cassandra-scylladb/operations.md)**
- Управление шаблонами в Elasticsearch: **[Elasticsearch: Индексные шаблоны](../ELK_Stack/Elasticsearch/elasticsearch_index_templates.md)**
- Политики хранения и ротации в Elasticsearch: **[Elasticsearch: ILM и ретеншн](../ELK_Stack/Elasticsearch/elasticsearch_ilm_and_retention.md)**
- Архитектура брокера Apache Kafka: **[Apache Kafka: Обзор](../Kafka/kafka_overview.md)**
- Мониторинг брокеров и топиков Kafka: **[Apache Kafka: Метрики и мониторинг](../Kafka/kafka_for_monitoring.md)**

**Официальная документация:**
- [Jaeger v2 Storage Documentation](https://www.jaegertracing.io/docs/latest/storage/)
- [ClickHouse MergeTree Family Engines](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree)
- [Elasticsearch Index Lifecycle Management Guide](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
- [Apache Cassandra TimeWindowCompactionStrategy](https://cassandra.apache.org/doc/latest/cassandra/operating/compaction/twcs.html)
- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
