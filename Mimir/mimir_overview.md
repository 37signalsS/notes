# Grafana Mimir

## 1. Определения

**Grafana Mimir** — это горизонтально масштабируемое, высокодоступное и мульти-тенантное решение для долгосрочного хранения метрик, полностью совместимое с [Prometheus](../Prometheus/overview.md). Проект разработан Grafana Labs как часть интегрированного стека наблюдаемости (Stack LGTM: **L**oki, **G**rafana, **T**empo, **M**imir).

**История и эволюция:** Mimir является форком и глубоким развитием проекта **Cortex**. В 2022 году Grafana Labs представила Mimir как замену Cortex, значительно упростив эксплуатацию и повысив производительность. Он стал ответом на потребность в хранении триллионов метрик и альтернативой таким системам, как [VictoriaMetrics](../VictoriaMetrics/overview.md) и [Thanos](../Prometheus/scaling/thanos_overview.md).

**Актуальное состояние (июль 2026):** Основной веткой является **Mimir 3.1.x**. Главные изменения коснулись архитектуры хранения (Ingest Storage) и движка запросов (MQE), что позволило снизить TCO (Total Cost of Ownership) и повысить надежность при чтении данных.

Основная задача Mimir — агрегировать метрики из множества кластеров Prometheus, предоставляя единую точку для глобального запроса (Global View) и решая фундаментальные проблемы масштабирования и долгосрочного хранения.

## 2. Базовые концепции

### Архитектурная философия

Архитектура Mimir разделяет общие принципы с другими компонентами Grafana Stack ([Loki](../Loki/loki_overview.md), [Tempo](../Tempo/index.md)):

- **Язык:** Все компоненты написаны на **Go**.
- **Режим развертывания:** Поддерживает **монолитный режим** (один бинарный файл) для тестирования и **микросервисный режим** для промышленной эксплуатации в Kubernetes.
- **Хранилище:** Основным местом хранения данных является **объектное хранилище** (S3, GCS, Azure Blob, MinIO). Это обеспечивает практически неограниченную емкость и низкую стоимость хранения.

### Write-Ahead Log (WAL) в Mimir

WAL играет критически важную роль в обеспечении надежности записи данных. В отличие от классического Prometheus, где WAL является локальным буфером на диске перед записью в блоки TSDB, в Mimir WAL выполняет двойную функцию:

1. **На стороне Prometheus/Alloy:** Перед отправкой по `remote_write` данные записываются в локальный WAL. Это гарантирует, что при сбое сети или недоступности Mimir данные не потеряются и будут доставлены при восстановлении связи (backfilling).
2. **На стороне Ingester:** После получения данных от Distributor, Ingester сохраняет их в локальный WAL на диске перед записью в оперативную память (RAM). Это обеспечивает безопасность при перезагрузке пода — данные можно восстановить из WAL без повторной отправки от Prometheus.

**Схема потока WAL:**
```
Prometheus → локальный WAL (диск) → remote_write → Distributor → Kafka → Ingester → локальный WAL (диск) → RAM (TSDB Head) → Flush → S3
```

**Размер WAL Ingester'а:** Размер WAL напрямую влияет на скорость восстановления после сбоя. ПриFlush раз в 2 часа и нагрузке 500K сэмплов/сек, WAL может достигать 50–100 GB на узел. Рекомендуется использовать быстрые SSD для WAL, так как при восстановлении происходит последовательное чтение всего файла.

### Архитектурные механизмы и отказоустойчивость

Mimir использует распределенные алгоритмы для обеспечения целостности и доступности данных:

- **Хеширующие кольца (Hash Rings):** Все микросервисы (Distributors, Ingesters, Queriers) используют согласованное хеширование для распределения нагрузки. Состояние кольца хранится во внешнем KV-хранилище (**etcd** или **Consul**) или передается через **Gossip-протокол** (Memberlist).
- **HA Tracker (High Availability):** Компонент внутри Distributor, который отвечает за дедупликацию метрик от HA-пар Prometheus. Он гарантирует, что если два инстанса Prometheus отправляют одни и те же данные, в хранилище попадет только одна копия.
- **Шардирование и репликация:** Данные реплицируются (обычно `replication_factor: 3`) между инжестерами. Даже при выходе из строя одного узла, данные остаются доступными для чтения и записи.
- **Зоны доступности (Zone Awareness):** Mimir может распределять реплики инжестеров по разным зонам, минимизируя риск потери данных при аварии в дата-центре.

### Ingest Storage (Apache Kafka)

Начиная с версии 3.0, Mimir использует **Apache Kafka** как асинхронный буфер между путем записи и путем чтения. Это решение отделяет прием данных от их persist-сохранения и обеспечивает следующие преимущества:

- **Полная изоляция путей:** Сбои в чтении (например, медленный Store-Gateway) не блокируют прием новых данных.
- **Гладкая нагрузка:** Kafka сглаживает пики ingestion, позволяя Ingester'ам работать с постоянной скоростью.
- **Масштабируемость:** Добавление новых Ingester'ов не требует перераспределения существующих данных — они просто подключаются к соответствующему партиции Kafka.

**Ключевые параметры Kafka для Mimir:**

| Параметр | Рекомендация | Описание |
| :--- | :--- | :--- |
| **Топики** | `mimir-ingest` | Основной топик для данных метрик. |
| **Партиции** | 12–24 | Зависит от пропускной способности. Формула: `max_ingesters × 2`. |
| **Replication Factor** | 3 | Для HA в рамках кластера Kafka. |
| **Retention** | 24–48 часов | Достаточно для повторной обработки при сбое Ingester. |
| **Segment Bytes** | 1–2 GB | Оптимизация для сжатия и скорости чтения. |
| **Compression Type** | `lz4` | Баланс между скоростью и коэффициентом сжатия. |

**Consumer Groups:** Каждый Ingester подписывается на топик как часть consumer group. Kafka автоматически распределяет партиции между активными инжестерами. При добавлении нового узла происходит перебалансировка (rebalance), которая занимает несколько секунд.

### Mimir Query Engine (MQE)

MQE — это потоковый движок выполнения PromQL-запросов, представленный в версии 3.0 и ставший стандартом в 3.1. В отличие от классического bulk-подхода Prometheus, где запрос загружает все данные в память и затем вычисляет, MQE обрабатывает данные потоково:

- **Потоковая обработка:** Данные читаются из S3 и Ingester'ов блоками и обрабатываются по мере поступления. Это снижает пиковое потребление RAM до **92%**.
- **Полная совместимость с PromQL:** Все существующие дашборды и алерты работают без изменений.
- **Projection Pushdown:** MQE запрашивает из объектного хранилива только те метки и образцы (samples), которые фактически используются в запросе. Это снижает сетевую нагрузку и I/O.
- **Common Subexpression Elimination (CSE):** Идентичные вычисления внутри одного запроса объединяются. Это снижает нагрузку на CPU до **15–20%** для сложных алертов.

**Ограничения MQE:** На момент версии 3.1 MQE не поддерживает некоторые редкие функции PromQL (например, `subquery` с определенными комбинациями). Для абсолютного большинства production-сценариев это не является проблемой.

### Runtime Configuration

Mimir поддерживает **Runtime Configuration** — механизм обновления конфигурации лимитов и настроек без перезапуска процессов. Это критически важно для production-сред, где downtime недопустим.

**Формат:** YAML-файл, загружаемый из объектного хранилища или локального пути.

**Пример `runtime-config.yaml`:**

```yaml
limits:
  ingestion:
    ingestion_rate: 100000
    ingestion_burst_size: 200000
    max_series_per_user: 1000000
    max_global_series_per_user: 2000000
  query:
    max_query_series: 50000
    query_timeout: 3m
    max_query_lookback: 720h
    max_fetched_series_per_query: 100000
  compactor:
    compaction_blocks_retention: 720h
```

**Обновление без перезапуска:** Изменения в runtime-config.yaml автоматически подхватываются компонентами через интервал опроса (по умолчанию 10 секунд). Для принудительного обновления можно отправить SIGHUP процессу.

### Лимиты и квоты (Limits & Quotas)

Mimir предоставляет детальный контроль над ресурсами на уровне тенанта:

- **Ingestion rate:** Максимальное количество сэмплов в секунду на тенанта. Превышение приводит к отклонению данных (HTTP 429) и метрике `mimir_distributor_discarded_samples_total`.
- **Series limit:** Максимальное количество активных временных рядов. При превышении новые серии отклоняются.
- **Query limits:** Ограничения на сложность запроса (количество затронутых серий, время выполнения).
- **User-defined limits:** Возможность задать индивидуальные лимиты для конкретных OrgID через Runtime Configuration.

### Retention Policies

Retention в Mimir управляется на двух уровнях:

1. **Ingester Retention (горячие данные):** Данные в RAM инжестеров доступны для чтения в течение 2–4 часов (последний flush). Это "горячий" tier.
2. **Block Retention (холодные данные):** После слияния блоков Compactor'ом, retention применяется к TSDB-блокам в объектном хранилище. Стандартное значение — 30–90 дней, но может быть увеличено до нескольких лет.

**Применение retention:** Compactor удаляет блоки, у которых `maxTime` старше порога retention. Это происходит асинхронно во время слияния блоков.

### Compaction Process

Compactor — это фоновый процесс, который оптимизирует хранение данных:

1. **Сканирование:** Compactor периодически сканирует бакет объектного хранилища, находя новые необработанные блоки.
2. **Слияние:** Несколько небольших блоков (размером 2–4 часа) объединяются в крупные (1–2 дня). Это снижает количество объектов в S3 и ускоряет запросы.
3. **Дедупликация:** При слиянии удаляются дублирующиеся образцы (если они есть).
4. **Применение retention:** Старые блоки удаляются.
5. **Индексация:** Обновляются глобальные индексы, используемые Store-Gateway.

**Важно:** Compactor требует значительных ресурсов (CPU/RAM и особенно диск для временных файлов). При недостатке ресурсов накапливается "Compaction Lag" — разница между последним flush'ем и последним скомпактированным блоком.

### Изоляция и управление ресурсами (Мульти-тенантность)

Mimir спроектирован как система для обслуживания множества независимых организаций (тенантов):

- **Идентификация:** Тенанты разделяются на уровне API через заголовок `X-Scope-OrgID`. Все данные в S3 и индексы в памяти снабжены этим идентификатором.
- **Лимиты и квоты (Limits & Quotas):** Глобальные и индивидуальные лимиты настраиваются в файле `limits.yaml` или через Runtime Configuration.
    - **Ingestion rate:** Максимальное количество сэмплов в секунду.
    - **Series limit:** Максимальное количество активных временных рядов.
    - **Query limits:** Ограничения на сложность запроса (количество затронутых серий, время выполнения).
- **Изоляция Querier:** Поддержка выделенных групп Querier для критически важных тенантов, чтобы тяжелые запросы одних пользователей не аффектили других.

### Путь данных (Data Flow)

1. **Запись (Write Path):** Prometheus → Distributor (валидация, дедупликация через HA Tracker) → Kafka (Ingest Storage) → Ingester (запись в WAL и формирование блоков в RAM).
2. **Сброс (Flush):** Ingester периодически (раз в 2 часа) упаковывает данные в блоки TSDB и загружает их в S3.
3. **Чтение (Read Path):** Grafana → Query Frontend (кэширование, шардирование) → Querier → (одновременно) Ingesters (свежие данные из RAM) + Store-Gateway (исторические данные из S3).

### Архитектурные изменения в Mimir 3.0 и 3.1

Переход к версии 3.1 ознаменовал стабилизацию **декаплированной архитектуры (Ingest Storage)**.

| Изменение | Описание | Техническое преимущество |
| :--- | :--- | :--- |
| **Ingest Storage (Kafka)** | Использование Apache Kafka как асинхронного буфера между записью и чтением. | Полная изоляция пути записи от пути чтения. Сбои в чтении не блокируют прием данных. |
| **Mimir Query Engine (MQE)** | Потоковый движок выполнения запросов (вместо bulk-обработки Prometheus). | Снижение пикового потребления RAM до **92%**. Полная совместимость с PromQL. |
| **Projection Pushdown** | Считывание из хранилища только необходимых меток и образцов. | Снижение нагрузки на сеть и I/O объектного хранилища. |
| **Common Subexpression Elimination (CSE)** | Объединение идентичных вычислений внутри одного запроса. | Снижение нагрузки на CPU до **15-20%** для сложных алертов и дашбордов. |

**До версии 3.0:** Пути чтения и записи были тесно связаны через инжестеры, что приводило к деградации производительности при массовых запросах.
**Версия 3.1:** Введен слой **Ingest Storage**, где данные сначала попадают в Kafka, что делает инжестеры более устойчивыми и упрощает их масштабирование.

### Основные компоненты (Микросервисы)

Mimir состоит из набора специализированных сервисов, каждый из которых масштабируется независимо:

- **Distributor:** Принимает метрики от Prometheus через `remote_write`. Выполняет валидацию данных, проверку лимитов для каждого тенанта (OrgID) и распределяет данные между инжестерами (через Kafka в новой архитектуре).
- **Ingester:** Получает данные, хранит их в памяти в виде временных рядов (TSDB) и периодически "сбрасывает" сжатые блоки (blocks) в объектное хранилище. Обеспечивает репликацию для высокой доступности.
- **Querier:** Выполняет PromQL-запросы. Запрашивает свежие данные у Ingesters, а исторические — у Store-Gateway. В версии 3.1 использует MQE по умолчанию.
- **Query Frontend:** Интеллектуальный прокси перед Querier. Выполняет шардирование запросов по времени, кэширует результаты (в Memcached/Redis) и управляет очередями для предотвращения перегрузки Querier.
- **Store-Gateway:** Шлюз к объектному хранилищу. Сканирует бакеты, загружает метаданные блоков и предоставляет индексы для Querier. Версия 3.1 включает проверку контрольных сумм (CRC32) для обнаружения повреждений данных.
- **Compactor:** Оптимизирует блоки данных в объектном хранилище, объединяя мелкие блоки в крупные, удаляя помеченные на удаление данные и применяя Retention.
- **Ruler:** Выполняет правила записи (recording rules) и алертинга (alerting rules) для каждого тенанта независимо.
- **Alertmanager:** Принимает алерты от Ruler, выполняет дедупликацию, группировку и отправку уведомлений через настроенные каналы (Slack, Email, PagerDuty).

### Сравнение с альтернативами (2026)

**Сравнение производительности:**

| Характеристика | VictoriaMetrics | Thanos | Grafana Mimir (v3.1) |
| :--- | :--- | :--- | :--- |
| **Производительность записи** | 1M+ сэмплов/сек (один узел) | Ограничена Prometheus | 500K-2M сэмплов/сек на pod |
| **Задержка запросов (<2ч)** | 10-30ms | 50-100ms | 20-50ms |
| **Задержка запросов (>24ч)** | 100-300ms | 200ms-2s | 100ms-500ms |
| **Сжатие данных** | До 10-15x | 2-4x | 3-5x |
| **Мин. требования (Production)** | 4 vCPU, 8GB RAM | 4 vCPU, 16GB RAM | 8 vCPU, 32GB RAM |

**Архитектурные различия:**

| Решение | Паттерн | Сильные стороны | Недостатки |
| :--- | :--- | :--- | :--- |
| **VictoriaMetrics** | Unified Platform | Простота эксплуатации, низкие ресурсы, агрессивное сжатие. | Базовая мульти-тенантность. |
| **Thanos** | Sidecar-based | Бесшовная миграция, CNCF-совместимость. | Высокая задержка при чтении из S3. |
| **Grafana Mimir** | Microservices | Строгая изоляция тенантов, продвинутый кэширование, Global View. | Сложность настройки (требует K8s). |

### Ключевые концепции

- **Remote Write API** — стандартный протокол Prometheus для отправки метрик. Подробнее: [Prometheus remote_read_write](../Prometheus/scaling/remote_read_write.md).
- **Мульти-тенантность** — изоляция через HTTP-заголовок `X-Scope-OrgID`. Позволяет одной инсталляции обслуживать сотни независимых клиентов.
- **TSDB Blocks** — сжатые блоки данных, совместимые с форматом Prometheus. Подробнее: [TSDB concepts](../Prometheus/concepts/tsdb.md).
- **Global View** — возможность выполнять один запрос к данным из множества географически распределенных кластеров.
- **Native Histograms** — нативные гистограммы Prometheus (Sparse Histograms), полностью поддерживаемые с версии 3.0. Позволяют значительно снизить количество временных рядов при сохранении высокой точности распределения.
- **Out-of-order samples** — поддержка записи образцов "вразнобой" (`out_of_order_time_window`), необходимая для источников с задержками передачи (IoT, мобильные приложения).
- **Exemplars** — ссылки на трейсы (traceID), прикрепленные к конкретным метрикам. Позволяют переходить от графика к логам и трейсам в один клик.

## 3. Практические сценарии

### Централизованное хранилище для гибридного облака

1. **Локальные коллекторы:** В каждом кластере (AWS, Bare Metal, Edge) разворачивается [Grafana Alloy](../Grafana/grafana_alloy_overview.md) или Prometheus в режиме Agent.
2. **Пересылка:** Данные отправляются через `remote_write` в центральный Mimir. Используется заголовок `X-Scope-OrgID` для разделения сред (например, `prod`, `dev`).
3. **Хранение:** Mimir сохраняет данные в централизованный S3-бакет с политикой жизненного цикла 1-3 года.
4. **Визуализация:** Центральная Grafana подключается к Mimir. Команды используют переменные в дашбордах для фильтрации по тенантам.

### Требования к ресурсам (на один pod в Production)

В версии 3.1 благодаря MQE потребление памяти Querier значительно снизилось, но Store-Gateway всё ещё требует ресурсов под кэш индексов.

| Компонент | vCPU (Rec) | RAM (Rec) | Диск (Временный) |
| :--- | :--- | :--- | :--- |
| **Distributor** | 4-8 | 8GB | — |
| **Ingester** | 8-16 | 32-64GB | 50-100GB (Write-Ahead Log) |
| **Querier** | 8-16 | 16-32GB | — |
| **Query Frontend** | 4-8 | 8GB | — |
| **Store-Gateway** | 8-16 | 64-128GB | 20GB (Кэш метаданных) |
| **Compactor** | 4-8 | 16GB | 200GB+ (для слияния блоков) |

**Формула расчета для Ingester:**
```
RAM = (samples_per_second × head_series_memory_bytes) + wal_size
```
Где `head_series_memory_bytes` ≈ 30–50 байт на серию.

### Развёртывание в Kubernetes

**Helm-чарт:** `grafana/mimir-distributed`

```bash
# Добавление репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка с использованием внешней Kafka для Ingest Storage
helm install mimir grafana/mimir-distributed \
  --namespace mimir \
  --create-namespace \
  -f custom-values.yaml
```

**Пример production-ready `values.yaml` для Mimir 3.1:**

```yaml
# Общие настройки
mimir:
  structuredConfig:
    multitenancy_enabled: true
    auth_enabled: true
    server:
      http_listen_port: 8080
      grpc_listen_port: 9095
    distributor:
      pool:
        max_workers: 2048
      ha_tracker:
        enable_ha_tracker: true
        kvstore:
          store: memberlist
    ingester:
      ring:
        kvstore:
          store: memberlist
        replication_factor: 3
      # Включение Ingest Storage (Kafka)
      use_ingest_storage: true
      ingest_storage:
        kafka:
          addresses:
            - kafka.mimir.svc:9092
          topic_name: mimir-ingest
          consumer_group: mimir-ingester
          last_produced_offset_recheck_interval: 5s
          flush_timeout: 10m
    store_gateway:
      sharding_ring:
        kvstore:
          store: memberlist
        replication_factor: 3
      cache:
        chunks:
          memcached:
            addresses:
              - memcached.mimir.svc:11211
            timeout: 500ms
            max_idle_connections: 100
            update_interval: 1m
        metadata:
          memcached:
            addresses:
              - memcached.mimir.svc:11211
            timeout: 500ms
            max_idle_connections: 100
    query_frontend:
      cache:
        results:
          memcached:
            addresses:
              - memcached.mimir.svc:11211
            timeout: 500ms
            expiration: 24h
    compactor:
      sharding_ring:
        kvstore:
          store: memberlist
        replication_factor: 1
      compaction_interval: 1h
      deletion_marks_cleanup_interval: 1h
    limits:
      ingestion:
        ingestion_rate: 100000
        ingestion_burst_size: 200000
        max_series_per_user: 1000000
        max_global_series_per_user: 2000000
      query:
        max_query_series: 50000
        query_timeout: 3m
        max_query_lookback: 720h
        max_fetched_series_per_query: 100000
    storage:
      bucket_name: mimir-blocks
      endpoint: s3.mimir.svc:9000
      region: us-east-1
      access_key_id: mimir
      secret_access_key: secret
      insecure: true
      s3:
        s3: null  # Отключаем S3 для MinIO
        endpoint: s3.mimir.svc:9000
        access_key_id: mimir
        secret_access_key: secret
        insecure: true
    # Внешний etcd для Hash Rings
    memberlist:
      join_members:
        - mimir-gossip-ring

# Настройка инжестеров
ingester:
  replicas: 3
  resources:
    requests:
      cpu: 8
      memory: 32Gi
    limits:
      cpu: 16
      memory: 64Gi
  persistence:
    enabled: true
    size: 200Gi
    storageClass: local-ssd

# Настройка дистрибьюторов
distributor:
  replicas: 3
  resources:
    requests:
      cpu: 4
      memory: 8Gi
    limits:
      cpu: 8
      memory: 16Gi

# Настройка квериеров
querier:
  replicas: 5
  resources:
    requests:
      cpu: 8
      memory: 16Gi
    limits:
      cpu: 16
      memory: 32Gi

# Настройка Store-Gateway
store_gateway:
  replicas: 3
  resources:
    requests:
      cpu: 8
      memory: 64Gi
    limits:
      cpu: 16
      memory: 128Gi
  cache:
    chunks:
      memcached:
        replicas: 3
        resources:
          requests:
            memory: 8Gi
    metadata:
      memcached:
        replicas: 3
        resources:
          requests:
            memory: 8Gi

# Настройка Query Frontend
query_frontend:
  replicas: 2
  resources:
    requests:
      cpu: 4
      memory: 8Gi
    limits:
      cpu: 8
      memory: 16Gi

# Настройка Compactor
compactor:
  replicas: 1
  resources:
    requests:
      cpu: 4
      memory: 16Gi
    limits:
      cpu: 8
      memory: 32Gi
  persistence:
    enabled: true
    size: 500Gi
    storageClass: local-ssd

# Настройка Ruler и Alertmanager
ruler:
  replicas: 1
  resources:
    requests:
      cpu: 2
      memory: 4Gi
alertmanager:
  replicas: 1
  resources:
    requests:
      cpu: 1
      memory: 2Gi
```

### Конфигурация MinIO для локального объектного хранилища

Для on-prem или边缘 сред без доступа к публичному облаку, MinIO является стандартным выбором. Важно правильно настроить политики жизненного цикла и версионирование.

**Развертывание MinIO через Helm:**

```bash
helm repo add minio https://charts.min.io/
helm install minio minio/minio \
  --namespace storage \
  --create-namespace \
  -f minio-values.yaml
```

**Пример `minio-values.yaml`:**

```yaml
mode: standalone
rootUser: mimir
rootPassword: <SECRET_2b4b64f9>bucket
  replicas: 4
  drivesPerNode: 1
  size: 500Gi
  storageClass: local-ssd
  # Для production обязательно используйте репликацию MinIO
  # или внешние бэкапы через mc mirror
```

**Политика жизненного цикла (Lifecycle) для бакета `mimir-blocks`:**

```json
{
  "Rules": [
    {
      "ID": "transition-to-ia",
      "Status": "Enabled",
      "Filter": {
        "Prefix": ""
      },
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "STANDARD_IA"
        }
      ]
    },
    {
      "ID": "delete-after-retention",
      "Status": "Enabled",
      "Filter": {
        "Prefix": ""
      },
      "Expiration": {
        "Days": 365
      }
    }
  ]
}
```

**Применение политики через `mc` (MinIO Client):**

```bash
mc alias set mimir http://minio.mimir.svc:9000 mimir <SECRET_2b4b64f9>
mc ilm import mimir/mimir-blocks < lifecycle.json
```

### Конфигурация Apache Kafka для Ingest Storage

Для production Kafka рекомендуется разворачивать кластер из 3 брокеров с репликацией RF=3.

**Пример `server.properties` для брокера Kafka:**

```properties
# Сеть
listeners=PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=PLAINTEXT://kafka-0.mimir.svc:9092
num.network.threads=8
num.io.threads=16
socket.send.buffer.bytes=1024000
socket.receive.buffer.bytes=1024000
socket.request.max.bytes=104857600

# Логи
log.dirs=/var/lib/kafka/data
num.partitions=24
default.replication.factor=3
offsets.topic.replication.factor=3
transaction.state.log.replication.factor=3
transaction.state.log.min.isr=2

# Retention для топика Mimir
log.retention.hours=48
log.retention.bytes=10737418240
log.segment.bytes=1073741824
log.retention.check.interval.ms=300000

# Сжатие
compression.type=lz4

# Контроль доступа
authorizer.class.name=kafka.security.authorizer.AclAuthorizer
super.users=User:admin
```

**ACL для Mimir:**

```bash
# Создание топика
kafka-topics.sh --create --topic mimir-ingest --partitions 24 --replication-factor 3 --bootstrap-server kafka:9092

# Настройка ACL
kafka-acls.sh --authorizer-properties zookeeper.connect=zookeeper:2181 \
  --add --allow-principal User:mimir --operation All --topic mimir-ingest \
  --group mimir-ingester
```

### Конфигурация etcd для Hash Rings

etcd обеспечивает консистентность состояния хеширующих колец в кластере Mimir.

**Пример `etcd-values.yaml`:**

```yaml
replicaCount: 3
resources:
  requests:
    cpu: 2
    memory: 4Gi
  limits:
    cpu: 4
    memory: 8Gi
storage:
  size: 20Gi
  storageClass: local-ssd
auth:
  rbac:
    create: true
    roles:
      - name: mimir
        rules:
          - apiGroups: [""]
            resources: ["endpoints", "services"]
            verbs: ["get", "list", "watch"]
```

**Проверка состояния колец:**

```bash
# Проверка статуса Distributor
kubectl exec -n mimir deploy/mimir-distributor -- curl -s http://localhost:8080/ring | jq

# Проверка статуса Ingester
kubectl exec -n mimir deploy/mimir-ingester -- curl -s http://localhost:8080/ring | jq
```

### Конфигурация Memcached для кэширования

Memcached критически важен для производительности Store-Gateway и Query Frontend.

**Пример `memcached-values.yaml`:**

```yaml
replicas: 3
resources:
  requests:
    memory: 8Gi
    cpu: 2
  limits:
    memory: 16Gi
    cpu: 4
service:
  ports:
    memcached: 11211
config:
  memory_limit: 12GB
  max_item_size: 5MB
  connections: 1024
  threads: 8
```

### Обновление Runtime Configuration

Runtime Configuration позволяет изменять лимиты и настройки без перезапуска пода.

**Загрузка нового конфига:**

```bash
# Загрузка в S3/MinIO
mc cp runtime-config.yaml mimir/mimir-blocks/runtime-config.yaml

# Или через API (если включен)
curl -X POST http://mimir-distributor.mimir.svc:8080/runtime_config \
  -H "Content-Type: application/yaml" \
  --data-binary @runtime-config.yaml

# Проверка применения
kubectl exec -n mimir deploy/mimir-distributor -- curl -s http://localhost:8080/runtime_config | jq
```

### Правила алертинга (Alertmanager + Ruler)

Пример recording rule для расчета глобального rate:

```yaml
# mimir-rules.yaml
groups:
  - name: global_metrics
    interval: 30s
    rules:
      - record: job:request_rate:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)
      - alert: HighErrorRate
        expr: sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокий процент ошибок"
          description: "Более 5% запросов возвращают 5xx"
```

**Применение правил:**

```bash
kubectl create configmap mimir-rules \
  --from-file=rules.yaml=mimir-rules.yaml \
  -n mimir

# Правила автоматически подхватываются Ruler'ом
# Проверка:
kubectl exec -n mimir deploy/mimir-ruler -- \
  curl -s http://localhost:8080/rules | jq
```

### Развертывание на Bare Metal / On-Prem

Для сред без Kubernetes Mimir поддерживает монолитный режим, но для production рекомендуется микросервисный режим даже на bare metal (через Docker Compose или Systemd unit-файлы).

**Docker Compose (Minimum Viable Production):**

```yaml
version: '3.8'
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: mimir
      MINIO_ROOT_PASSWORD: <SECRET_2b4b64f9>bucket
    volumes:
      - ./minio-data:/data
    ports:
      - "9000:9000"
      - "9001:9001"

  memcached:
    image: memcached:1.6-alpine
    command: ["-m", "8G", "-c", "1024", "-t", "8"]
    ports:
      - "11211:11211"

  mimir:
    image: grafana/mimir:3.1.0
    command: |
      -target=all
      -config.expand-env=true
    environment:
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=mimir
      - MINIO_SECRET_KEY=<SECRET_2b4b64f9>bucket
    ports:
      - "8080:8080"   # HTTP API
      - "9095:9095"   # gRPC
    volumes:
      - ./mimir-config.yaml:/etc/mimir/config.yaml
    depends_on:
      - minio
      - memcached
```

### Валидация развертывания

После установки выполните следующие проверки:

**1. Проверка состояния компонентов:**

```bash
# Все pod'ы должны быть Running
kubectl get pods -n mimir

# Проверка готовности
kubectl get pods -n mimir -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'
```

**2. Проверка записи (Write Path):**

```bash
# Отправка тестовой метрики
curl -X POST http://mimir-distributor.mimir.svc:8080/api/v1/push \
  -H "Content-Type: application/x-protobuf" \
  -H "X-Scope-OrgID: test-tenant" \
  -H "X-Prometheus-Remote-Write-Version: 2.0" \
  --data-binary @test-metrics.pb

# Проверка метрики в Mimir
curl -G http://mimir-query-frontend.mimir.svc:9009/prometheus/api/v1/query \
  --data-urlencode 'query=up' \
  -H "X-Scope-OrgID: test-tenant"
# → Должен вернуть результат
```

**3. Проверка чтения (Read Path):**

```bash
# PromQL-запрос
curl -G http://mimir-query-frontend.mimir.svc:9009/prometheus/api/v1/query_range \
  --data-urlencode 'query=sum(rate(http_requests_total[5m]))' \
  --data-urlencode 'start=1h' \
  --data-urlencode 'end=now' \
  --data-urlencode 'step=1m' \
  -H "X-Scope-OrgID: test-tenant"
```

**4. Проверка статуса колец:**

```bash
# Distributor ring
kubectl exec -n mimir deploy/mimir-distributor -- curl -s http://localhost:8080/ring | jq '.distributor.ingesters'

# Ingester ring
kubectl exec -n mimir deploy/mimir-ingester -- curl -s http://localhost:8080/ring | jq '.ingester.lifecycler.ring'
```

**5. Проверка метрик самого Mimir:**

```bash
# Ключевые метрики для проверки
curl -s http://mimir-query-frontend.mimir.svc:9009/prometheus/api/v1/query \
  --data-urlencode 'query=sum(rate(mimir_distributor_received_samples_total[5m]))' | jq
# → Должен показывать ненулевой приток

curl -s http://mimir-query-frontend.mimir.svc:9009/prometheus/api/v1/query \
  --data-urlencode 'query=sum(rate(mimir_distributor_discarded_samples_total[5m]))' | jq
# → Должен быть 0 (если нет превышения лимитов)
```

### Мониторинг Mimir (Self-Monitoring)

Mimir экспортирует метрики в формате Prometheus. Для мониторинга самой системы Mimir требуется отдельный Prometheus (не входящий в кластер Mimir).

**Ключевые метрики SRE:**

| Категория | Метрика | Описание | Alert-порог |
| :--- | :--- | :--- | :--- |
| **Write** | `mimir_distributor_received_samples_total` | Общее количество принятых сэмплов | — |
| | `mimir_distributor_discarded_samples_total` | Отброшенные сэмплы (лимиты) | > 0 |
| | `mimir_ingester_ingested_samples_total` | Сэмплы, записанные в Ingester | — |
| **Read** | `mimir_querier_query_duration_seconds` | Время выполнения PromQL-запросов | > 2s (p99) |
| | `mimir_store_gateway_query_duration_seconds` | Время запросов к S3 | > 1s (p99) |
| | `mimir_cache_misses_total` | Промахи кэша | Рост > 20% |
| **Ring** | `cortex_ring_members_changed_total` | Изменения в кольце | Резкий рост |
| | `mimir_ingester_ring_members` | Количество членов кольца | < replicaCount |
| **Compactor** | `mimir_compactor_runs_completed_total` | Завершенные циклы compaction | — |
| | `mimir_compactor_blocks_retention_call_duration_seconds` | Время применения retention | > 1h |

**Рекомендуемые дашборды:**
- `Mimir / Reads` — задержки запросов, кэш-попадания
- `Mimir / Writes` — пропускная способность, ошибки
- `Mimir / Ingest Storage` — лаг Kafka, offset'ы
- `Mimir / Store Gateway` — загрузка S3, индекс

### Резервное копирование и восстановление (Backup & DR)

**Что нужно бэкапировать:**

1. **WAL Ingester'ов:** Находящиеся в оперативной памяти данные, которые еще не сброшены в S3. При сбое Ingester'а WAL восстанавливается автоматически, но для полной безопасности рекомендуется репликация WAL на другой узел.
2. **Конфигурация Mimir:** `config.yaml`, `limits.yaml`, `runtime-config.yaml`, правила алертинга.
3. **KV-состояние (Hash Rings):** etcd/Consul — для них используйте стандартные механизмы бэкапа этих систем.
4. **S3 бакет с блоками:** Настройте versioning и replication на уровне MinIO/S3. Это защищает от случайного удаления.

**Сценарий восстановления после потери Ingester'а:**

```bash
# 1. Ingester автоматически восстанавливается из WAL при перезапуске
kubectl rollout restart deployment/mimir-ingester -n mimir

# 2. Проверка, что данные появились
kubectl exec -n mimir deploy/mimir-ingester -- \
  curl -s http://localhost:8080/ingester/flush | jq

# 3. Проверка метрик — лаг должен быть минимальным
kubectl exec -n mimir deploy/mimir-ingester -- \
  curl -s http://localhost:8080/ingester/memory_series | jq
```

**План disaster recovery:**

| Сценарий | RTO | RPO | Действия |
| :--- | :--- | :--- | :--- |
| **Сбой одного Ingester'а** | 5–10 мин | 0 (WAL) | Автовосстановление из WAL |
| **Сбой всей зоны** | 1–2 часа | 0 (RF=3) | Перебалансировка на другие зоны |
| **Потеря S3 (локального)** | 2–4 часа | До 2 часов | Восстановление из бэкапа S3 + backfill из Kafka |
| **Потеря всего кластера Mimir** | 4–8 часов | До 2 часов | Развертывание нового кластера + dual-write |

### Планирование емкости (Capacity Planning)

**Формула для оценки объема хранения:**

```
Объем (GB) = (samples_per_sec × bytes_per_sample × retention_seconds × replication_factor) / 1024^3
```

Где `bytes_per_sample` ≈ 8–16 байт (зависит от количества лейблов и сжатия).

**Пример:** 500K сэмплов/сек, retention 30 дней, RF=3, 12 байт/сэмпл:
```
(500000 × 12 × 2592000 × 3) / 1024^3 ≈ 54.6 GB/день → ~1.6 TB на 30 дней
```

С учетом сжатия 3-5x реальный объем будет в 3–5 раз меньше.

### Миграция с других систем

**С Prometheus (Local → Mimir):**
1. Настройте `remote_write` на Prometheus/Alloy с `initial_delay: 0s` для немедленной отправки.
2. Включите `max_shards: 1000` для ускорения backfill.
3. После завершения backfill'а (проверка по `mimir_distributor_received_samples_total`) можно уменьшить retention локального Prometheus.

**С Thanos:**
1. Thanos использует объектное хранилище в том же формате, что и Mimir (TSDB blocks).
2. Можно настроить Mimir на чтение из того же S3-бакета, предварительно проверив совместимость формата блоков.
3. Постепенно переключайте запросы с Thanos Query на Mimir Query Frontend.

**С VictoriaMetrics:**
1. Экспортируйте данные в формате Prometheus remote_write.
2. Используйте Parallel Write (несколько Prometheus/Alloy) для ускорения миграции.
3. Сравните результаты query'ов на обоих системах для валидации.

### Безопасность (Security Hardening)

- **mTLS между сервисами:** Используйте cert-manager для выдачи сертификатов. Пример конфигурации:

```yaml
# values.yaml
mimir:
  structuredConfig:
    server:
      grpc_tls_enabled: true
      grpc_tls_cert_path: /etc/certs/tls.crt
      grpc_tls_key_path: /etc/certs/tls.key
      http_tls_enabled: true
      http_tls_cert_path: /etc/certs/tls.crt
      http_tls_key_path: /etc/certs/tls.key
```

- **RBAC для ServiceAccount'ов:** Mimir pod'ы должны иметь минимально возможные права. Например, Ruler не должен иметь прав на запись в S3.
- **NetworkPolicy:** Запретите весь входящий трафик к Mimir, кроме трафика от Prometheus/Alloy (порт 8080) и Grafana (порт 9009).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mimir-allow
  namespace: mimir
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mimir
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/component: prometheus
      ports:
        - protocol: TCP
          port: 8080
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - protocol: TCP
          port: 9009
```

- **Аутентификация:** Используйте OIDC или mTLS для аутентификации Prometheus → Mimir. Никогда не используйте anonymous access в production.

### Настройка источника данных в Grafana

```yaml
# grafana-datasources.yaml
apiVersion: 1
datasources:
  - name: Mimir-LTS
    type: prometheus
    url: http://mimir-query-frontend.mimir.svc:9009/prometheus
    access: proxy
    jsonData:
      httpMethod: POST
      # Заголовок для мульти-тенантности
      httpHeaderName1: "X-Scope-OrgID"
    secureJsonData:
      httpHeaderValue1: "my-org-id"
```

**Проверка подключения:**

```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  "http://grafana:3000/api/datasources/proxy/uid/mimir-lts/api/v1/query?query=up" \
  | jq '.status'
# → "success"
```

## 4. Настройка Prometheus/Alloy → Mimir

### Базовая конфигурация Prometheus remote_write

Прометей отправляет метрики в Mimir через протокол `remote_write`. Ниже — production-ready конфигурация с очередями, ретраями и буферизацией.

```yaml
# prometheus.yml
remote_write:
  - url: "http://mimir-distributor.mimir.svc:8080/api/v1/push"
    send_exemplars: true
    send_native_histograms: true

    # Идентификация тенанта
    headers:
      X-Scope-OrgID: "production"

    # Очередь и буферизация
    queue_config:
      capacity: 10000          # Максимум сэмплов в очереди
      max_shards: 50           # Максимум параллельных потоков отправки
      min_shards: 5            # Минимум потоков
      max_samples_per_send: 5000
      batch_send_deadline: 5s  # Интервал отправки батчей
      retry_on_http_429: true  # Повтор при rate limit (v3.x)

    # Таймауты
    remote_timeout: 30s

    # Сжатие
    enable_http2: true

    # TLS (рекомендуется для production)
    tls_config:
      ca_file: /etc/prometheus/ca.crt
      cert_file: /etc/prometheus/client.crt
      key_file: /etc/prometheus/client.key

    # Метрики для мониторинга remote_write
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'prometheus_remote_storage_.*'
        action: keep
```

### Конфигурация Grafana Alloy → Mimir

Alloy является рекомендуемым агентом для сбора и пересылки метрик. Его конфигурация более гибкая, чем у Prometheus.

```hcl
// alloy.river

// Сбор метрик через Prometheus-скрапинг
prometheus.scrape "default" {
  targets = [
    { __address__ = "app:8080", job = "myapp" },
  ]
  forward_to = [prometheus.remote_write.mimir.receiver]
}

// Отправка в Mimir
prometheus.remote_write "mimir" {
  endpoint {
    url = "http://mimir-distributor.mimir.svc:8080/api/v1/push"

    headers = {
      "X-Scope-OrgID" = "production",
    }

    queue_config {
      capacity         = 10000
      max_shards       = 50
      min_shards       = 5
      batch_send_deadline = "5s"
    }

    tls_config {
      ca_file   = "/etc/alloy/ca.crt"
      cert_file = "/etc/alloy/client.crt"
      key_file  = "/etc/alloy/client.key"
    }
  }

  // Включить отправку exemplars и native histograms
  send_exemplars           = true
  send_native_histograms   = true
}
```

### Проверка доставки

```bash
# Проверка что Mimir принимает данные
curl -s -H "X-Scope-OrgID: production" \
  "http://mimir-query-frontend:9009/prometheus/api/v1/query?query=up" | jq '.data.result | length'
# → Должно вернуть количество активных целей

# Мониторинг очереди remote_write на стороне Prometheus
curl -s "http://prometheus:9090/api/v1/query?query=prometheus_remote_storage_samples_pending" | jq
# → Должен стремиться к 0

# Проверка rate limit'ов
curl -s "http://mimir-distributor:8080/metrics" | grep mimir_distributor_discarded_samples_total
# → Должен быть 0 (если нет превышения лимитов)
```

## 5. PromQL-оптимизация под Mimir

### Отличия от Prometheus

Mimir обрабатывает PromQL-запросы иначе, чем локальный Prometheus:
- Данные читаются из **S3** (Store-Gateway), а не с локального диска
- Запросы проходят через **Query Frontend** с кэшированием
- **MQE** (Mimir Query Engine) обрабатывает данные потоково

### Паттерны оптимизации

**1. Избегайте `group_left` / `group_right` с высокой кардинальностью:**

```promql
# ПЛОХО: group_left с миллионами серий
sum by (instance) (rate(http_requests_total[5m]))
  * on (instance) group_left
  label_replace(up, "instance", "$1", "instance", "(.*):.*")

# ХОРОШО: используйте relabeling на стороне сбора
# или joined recording rule заранее
```

**2. Используйте recording rules для сложных запросов:**

```yaml
# Вместо сложного PromQL в каждом дашборде — recording rule
groups:
  - name: http_metrics
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job, method, code)
      - record: job:http_errors:ratio5m
        expr: |
          sum(rate(http_requests_total{code=~"5.."}[5m])) by (job)
          /
          sum(rate(http_requests_total[5m])) by (job)
```

**3. Ограничивайте временные окна:**

```promql
# ПЛОХО: огромное окно без step
sum(rate(http_requests_total[7d]))

# ХОРОШО: разумный step через query_range
# В Grafana: step = interval * 2 (или min_interval)
```

**4. Используйте `histogram_quantile` с recording rules:**

```yaml
# Вычисление перцентиля — через recording rule, не на лету
- record: job:http_latency_p99
  expr: histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le, job))
```

**5. Используйте Projection Pushdown (MQE):**

```promql
# MQE автоматически запрашивает только нужные метки/сэмплы
# Дополнительно: указывайте конкретные лейблы вместо wildcard
sum(rate(http_requests_total{job="api", method="GET"}[5m])) by (code)
# Вместо:
sum(rate(http_requests_total[5m])) by (job, method, code)
```

## 6. Rolling restart компонентов

### Ingester (самый критичный)

Ingester хранит данные в WAL и RAM. При перезапуске данные восстанавливаются из WAL.

```bash
# 1. Проверьте состояние кольца перед рестартом
kubectl exec -n mimir deploy/mimir-distributor -- \
  curl -s http://localhost:8080/ring | jq '.ingester.ingesters[] | {state: .state, address: .address}'
# → Все ingester'ы должны быть в состоянии ACTIVE

# 2. Rolling restart (по одному поду)
kubectl rollout restart statefulset/mimir-ingester -n mimir

# 3. Мониторинг восстановления WAL
kubectl logs -n mimir -l app.kubernetes.io/component=ingester -f | grep -i "wal replay"
# → Дождитесь завершения replay перед следующим подом

# 4. Проверка после рестарта
kubectl exec -n mimir deploy/mimir-distributor -- \
  curl -s http://localhost:8080/ring | jq '.ingester.ingesters[] | {state: .state, tokens: .tokens}'
```

**Важно:** между рестартами разных подов Ingester делайте паузу 5–10 минут, пока WAL replay не завершится. Рестартуйте **не более одного** пода одновременно.

### Distributor

Distributor Stateless — безопасен для быстрого рестарта.

```bash
kubectl rollout restart deployment/mimir-distributor -n mimir
# Ожидание: несколько секунд
kubectl rollout status deployment/mimir-distributor -n mimir
```

### Querier / Query Frontend

Stateless компоненты — рестарт безопасен.

```bash
kubectl rollout restart deployment/mimir-querier -n mimir
kubectl rollout restart deployment/mimir-query-frontend -n mimir
```

### Compactor

Compactor — hazardous для рестарта во время compaction.

```bash
# 1. Проверьте, не идет ли compaction
kubectl exec -n mimir deploy/mimir-compactor -- \
  curl -s http://localhost:8080/compactor/ring | jq '.compactor.ring'

# 2. Если compaction не идет — безопасно рестартить
kubectl rollout restart statefulset/mimir-compactor -n mimir
```

### Store-Gateway

Store-Gateway кэширует метаданные в RAM. При рестарте кэш прогревается заново.

```bash
kubectl rollout restart statefulset/mimir-store-gateway -n mimir
# После рестарта первые запросы могут быть медленными (прогрев кэша)
```

## 7. Scale-down Ingester

Уменьшение количества Ingester'ов — рискованная операция, требующая аккуратности.

### Пошаговая процедура

```bash
# 1. Убедитесь, что кластер стабилен
kubectl exec -n mimir deploy/mimir-distributor -- \
  curl -s http://localhost:8080/ring | jq '.ingester.ingesters | length'
# → Текущее количество ingester'ов

# 2. Снизьте replication_factor (если нужно) через Runtime Configuration
cat <<EOF | kubectl exec -n mimir -i deploy/mimir-distributor -- \
  curl -s -X POST http://localhost:8080/runtime_config \
  -H "Content-Type: application/yaml" --data-binary @-
limits:
  replication_factor: 2
EOF

# 3. Дождитесь перераспределения токенов
kubectl logs -n mimir -l app.kubernetes.io/component=ingester -f | grep "ring"
# → Все ingester'ы должны стать ACTIVE с новым распределением токенов

# 4. Уменьшите количество реплик
kubectl scale statefulset/mimir-ingester --replicas=2 -n mimir

# 5. Проверьте, что данные не потеряны
curl -s -H "X-Scope-OrgID: production" \
  "http://mimir-query-frontend:9009/prometheus/api/v1/query?query=count(up)" | jq '.data.result[0].value[1]'
```

### Важные замечания

- **Никогда не уменьшайте количество Ingester'ов более чем на 1 за раз**
- Дождитесь завершения **flush** (раз в 2 часа) перед удалением следующего пода
- Если `replication_factor: 3`, минимум 3 Ingester'а обязательны
- При scale-down изолируйте PVC удаленных подов (политика `Retain`)

## 8. Расширенный Troubleshooting

### Ingester OOM Kill

```bash
# Проверка OOM
kubectl get events -n mimir --field-selector reason=OOMKilling
# Или:
kubectl describe pod -n mimir -l app.kubernetes.io/component=ingester | grep -A5 "Last State"

# Решение: увеличьте лимит памяти
# formulas: RAM = (samples_per_second × head_series_memory_bytes) + wal_size
# head_series_memory_bytes ≈ 30-50 байт на серию
```

### Store-Gateway: высокий cache miss ratio

```bash
# Проверка cache hit ratio
curl -s "http://mimir-store-gateway:8080/metrics" | grep mimir_store_gateway_cache_hits_total
curl -s "http://mimir-store-gateway:8080/metrics" | grep mimir_store_gateway_cache_misses_total

# cache_hit_ratio = hits / (hits + misses)
# Целевое значение: > 80%

# Решения:
# 1. Увеличьте размер Memcached (memory_limit)
# 2. Увеличьте max_idle_connections в конфиге
# 3. Проверьте, что Memcached не thrashing (evictions > 0)
```

### Медленные PromQL-запросы

```bash
# 1. Найдите медленный запрос через логи
kubectl logs -n mimir -l app.kubernetes.io/component=query-frontend | grep "query_result_total_duration_seconds"

# 2. Проверьте, использует ли запрос recording rules
# Если нет — создайте recording rule для сложной агрегации

# 3. Проверьте кэш
curl -s "http://mimir-query-frontend:8080/metrics" | grep mimir_query_frontend_cache_entries

# 4. Увеличьте timeout если запросы legitimate
# runtime-config.yaml: max_query_timeout: 10m
```

### Kafka Consumer Lag

```bash
# Проверка lag
kubectl exec -n mimir kafka-0 -- \
  kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --group mimir-ingester --describe

# Lag должен стремиться к 0. Если стабильно растет:
# 1. Увеличьте количество Ingester'ов
# 2. Увеличьте партиции в Kafka (требует планирования)
# 3. Проверьте, не hammered ли Ingester CPU/RAM
```

### Нехватка диска на Compactor

```bash
# Проверка использования диска
kubectl exec -n mimir statefulset/mimir-compactor -- df -h /data

# Compactor требует много временного места для слияния блоков
# Решение: увеличьте PVC (min 200GB для production)
# Или настройте shard compaction через sharding_ring
```

### Дедупликация данных (double counting)

```bash
# Если данные дублируются — проверьте HA Tracker
curl -s "http://mimir-distributor:8080/metrics" | grep mimir_distributor_ha_tracker_runs_total

# Причины:
# 1. Два Prometheus отправляют одни и те же метрики с разными external_labels
# 2. HA Tracker отключен (enable_ha_tracker: false)
# 3. Разные cluster/replica labels у HA-пар
```

## 10. Дополнительная информация

### Рекомендации по эксплуатации

- **Мониторинг самого Mimir:** Mimir поставляет богатый набор метрик. Необходимо развернуть отдельный Prometheus для мониторинга Mimir и использовать официальные дашборды "Mimir / Reads", "Mimir / Writes".
- **Оптимизация кэширования:** Обязательно используйте Memcached для Query Frontend (кэширование результатов) и Store-Gateway (кэширование чанков и индексов). Это может снизить стоимость S3 запросов на 80%.
- **Native Histograms:** Начиная с версии 3.0, Mimir полностью поддерживает нативные гистограммы Prometheus (Sparse Histograms). Это позволяет значительно снизить количество временных рядов при сохранении высокой точности распределения.
- **Out-of-order samples:** Включите поддержку записи образцов "вразнобой" (`out_of_order_time_window`), если ваши источники данных (например, IoT-устройства или мобильные приложения) имеют задержки при передаче.
- **WAL на SSD:** Всегда используйте SSD для Write-Ahead Log. При использовании HDD время восстановления после сбоя может составлять часы вместо минут.
- **Количество партиций Kafka:** Рассчитывайте исходя из максимального числа инжестеров. Формула: `max_ingesters × 2`. Добавление партиций позже возможно, но требует перебалансировки.
- **Снэпшоты TSDB:** Mimir сам управляет снэпшотами в S3. Дополнительное резервное копирование блоков обычно не требуется, если настроено versioning в MinIO/S3.

### Диагностика и Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Inconsistent Ring** | Рассинхрон состояния кольца в KV-хранилище или сетевые задержки gossip. | Проверьте статус `/ring` на Distributor/Ingester. Перезапустите узлы с некорректным статусом (LEAVING/UNHEALTHY). |
| **Slow Queries (S3)** | Высокая задержка объектного хранилища или отсутствие кэширования. | Увеличьте кэш метаданных в Store-Gateway. Проверьте лимиты (Throttling) на стороне S3. |
| **Compaction Lag** | Недостаточно ресурсов у Compactor для слияния огромных блоков. | Увеличьте CPU/RAM для Compactor. Разделите работу Compactor на несколько шардов через `sharding_ring`. |
| **Ingestion Errors** | Превышение лимитов тенанта или сбои в Kafka (Ingest Storage). | Проверьте метрики `mimir_distributor_discarded_samples_total`. Скорректируйте лимиты в `limits.yaml`. |
| **High Memory Usage (Querier)** | Слишком сложные запросы или отсутствие кэширования. | Включите Query Frontend с Memcached. Увеличьте лимит `max_query_series`. |
| **Data Loss after Ingester Crash** | WAL поврежден или не хватило места на диске. | Проверьте логи Ingester'а. Увеличьте размер PVC для WAL. |
| **Kafka Consumer Lag** | Ingester'ы не справляются с нагрузкой или Kafka перебалансировка. | Увеличьте количество Ingester'ов. Проверьте партиции в Kafka (`kafka-consumer-groups.sh`). |

### Рекомендации по обновлению на 3.1

При переходе с 2.x на 3.1 рекомендуется стратегия "Side-by-side": развертывание нового кластера с включенным MQE и Ingest Storage, настройка двойной записи (dual-write) и постепенное переключение запросов.

### См. также
- [Recording Rules и Alerting Rules](./mimir_recording_rules.md) — управление правилами через Ruler API.
- [SLO/SLI для Mimir](./mimir_slo_sli.md) — построение SLO для самого Mimir как сервиса.
- [Security Hardening](./mimir_security_hardening.md) — mTLS, RBAC, NetworkPolicy, изоляция тенантов.
- [Native Histograms и Exemplars](./mimir_native_histograms_exemplars.md) — инструментация, PromQL, Grafana.
- [Multi-Region и Zone Awareness](./mimir_multi_region.md) — отказоустойчивость и географическое распределение.
- [Обзор Prometheus](../Prometheus/overview.md) — базовые принципы.
- [Grafana Alloy](../Grafana/grafana_alloy_overview.md) — рекомендуемый агент.
- [VictoriaMetrics — обзор](../VictoriaMetrics/overview.md) — альтернатива Mimir.
- [TSDB — концепции](../Prometheus/concepts/tsdb.md) — формат хранения данных.
- [Remote Read/Write](../Prometheus/scaling/remote_read_write.md) — протокол отправки метрик.

### Официальные ресурсы
- **[Mimir Documentation](https://grafana.com/docs/mimir/latest/)** — основное руководство.
- **[Mimir GitHub](https://github.com/grafana/mimir)** — исходный код и релизы.
- **[Grafana Labs Blog](https://grafana.com/blog/)** — технические статьи о MQE и Ingest Storage.
