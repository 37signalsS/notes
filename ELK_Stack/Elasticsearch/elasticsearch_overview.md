# Elasticsearch: Обзор

**Актуально для:** Elasticsearch 9.5.x / 8.19 LTS

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и служит основной точкой входа для изучения Elasticsearch. Она охватывает архитектуру, роли узлов, механизмы масштабирования, современные возможности поиска, а также практические сценарии диагностики, обслуживания и устранения типовых неполадок.
>
> Детализация по смежным темам: схемы данных и векторный поиск — [Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md); автоматизация жизненного цикла — [ILM и политики хранения](./elasticsearch_ilm_and_retention.md); развертывание кластера — [руководство по настройке](../Tutorials/cluster_setup.md); траблшутинг индексации — [Траблшутинг индексации и сегментов](./elasticsearch_troubleshooting_indexing.md); capacity planning — [Capacity Planning](./elasticsearch_capacity_planning.md); обработка документов — [Ingest Pipelines](./elasticsearch_ingest_pipelines.md); шаблоны и Data Streams — [Index Templates](./elasticsearch_index_templates.md); оптимизация поиска — [Search Tuning](./elasticsearch_search_tuning.md); мониторинг — [Stack Monitoring](./elasticsearch_stack_monitoring.md); безопасность — [Security Advanced](./elasticsearch_security_advanced.md); алертинг — [Alerting](./elasticsearch_alerting.md); CCR/CCS — [Cross-Cluster](./elasticsearch_ccr_ccs.md); Rollup — [Rollup и Transform](./elasticsearch_rollup_transform.md); DR — [Disaster Recovery](./elasticsearch_disaster_recovery.md); upgrades — [Upgrades](./elasticsearch_upgrades.md); сеть — [Network и Firewall](../elasticsearch_network_requirements.md).

## Определения

* **Elasticsearch** — распределенный, высокопроизводительный поисковый и аналитический движок с открытым интерфейсом (REST API). Начиная с версий 8.x, Elasticsearch позиционируется как **унифицированная платформа поиск**, сочетающая полнотекстовый поиск, аналитику временных рядов и возможности **векторной базы данных**. С 9.5 добавлены нативный columnar-режим хранения (Columnar Mode) и режим VectorDB index mode для векторного поиска с автокалибровкой. Актуальные мажорные линейки — 8.x (LTS) и 9.x (current). Исходный код бесплатной части доступен под тремя лицензиями на выбор: Elastic License 2.0, SSPL v1 и AGPLv3 (последняя добавлена начиная с релиза 8.16, что вернуло проекту статус Open Source).
* **Индекс (Index)** — логическое пространство документов с общей схемой (маппингом), распределенное по шардам. Аналог таблицы в реляционной БД. Подробно о проектировании схем: [Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md).
* **Документ (Document)** — основная единица хранения: JSON-объект с уникальным идентификатором `_id` внутри индекса. Все операции записи и поиска выполняются на уровне отдельных документов.
* **Инвертированный индекс** — основная структура данных для текстового поиска, связывающая уникальные термы со списком документов, в которых они встречаются. Обеспечивает мгновенный полнотекстовый поиск.
* **Сегмент Lucene (Lucene Segment)** — минимальная неделимая единица хранения инвертированного индекса. Каждый шард физически является независимым индексом Apache Lucene, состоящим из множества сегментов; документы добавляются только новыми сегментами и не изменяются на месте (иммутабельность сегментов) — это фундаментальная причина существования механизмов refresh, merge и near-real-time поиска.
* **ES|QL (Elasticsearch Query Language)** — современный язык запросов с конвейерной структурой (pipes), использующий специализированный движок **поколоночного выполнения (columnar engine)** для высокой производительности аналитических и поисковых задач. Общедоступен (GA) начиная с версии 8.14. С 8.19/9.1 GA: команда `LOOKUP JOIN` (обогащение событий данными lookup-таблиц без денормализации) и поддержка Cross-Cluster Search.
* **Retriever (Ретривер)** — современная абстракция запроса поиска (введены в 8.14, GA с 8.16), позволяющая декларативно комбинировать несколько стратегий выборки (стандартный поиск, kNN, RRF-ранжирование) в одном запросе вместо ручного слияния результатов.
* **HNSW (Hierarchical Navigable Small World)** — алгоритм приближенного поиска ближайших соседей (k-NN), используемый для эффективного поиска по векторным представлениям (embeddings).
* **Квантование (Quantization)** — метод сжатия векторов для снижения потребления off-heap RAM: `int8` (сокращение в 4 раза, тип индекса по умолчанию для float-полей с 8.14), `int4` (в 8 раз, требует чётного числа измерений) и `bbq` — Better Binary Quantization (в 32 раза, с 8.16). Сырые float-векторы сохраняются на диске для переранжирования и reindex, поэтому диск растёт (~25% для int8, ~12.5% для int4, ~3% для bbq).
* **Columnar Mode** (9.5+) — нативный columnar-режим хранения Elasticsearch для аналитических нагрузок: больше данных в том же объёме, быстрее запросы, дольше хранение.
* **VectorDB index mode** (9.5+) — режим векторного индекса с автокалибровкой: одна настройка применяет подобранные defaults (квантование, merge policy, прогрев кэша) — векторный поиск «из коробки» без ручного тюнинга.
* **Узел (Node)** — отдельный процесс или сервер Elasticsearch.
* **Кластер (Cluster)** — группа узлов, объединенных общим именем (`cluster.name`), обеспечивающая единое пространство хранения и вычислений.

## Основные концепции

### Роли узлов

В Elasticsearch 8.x/9.x используется гранулярная модель ролей для оптимизации ресурсов. Роли назначаются параметром `node.roles` в `elasticsearch.yml`; узел может совмещать несколько ролей. Если `node.roles` не задан, узел получает все роли по умолчанию: `master`, `data`, `data_content`, `data_hot`, `data_warm`, `data_cold`, `data_frozen`, `ingest`, `ml`, `remote_cluster_client`, `transform`. Каждый кластер обязательно требует роли `master` и (`data_content` + `data_hot` либо `data`).

* **Мастер-узел (Master)**: Управляет состоянием кластера (создание индексов, распределение шардов, членство узлов). Различайте понятия:
    * *master-eligible* — узел, имеющий право избираться мастером (`node.roles: [ master ]`);
    * *выбранный мастер* — один активный мастер, координирующий кластер в текущий момент.
    В Prod-средах требуется минимум 3 master-eligible узла для обеспечения кворума и защиты от **Split-Brain**. Кворум вычисляется как `(N / 2) + 1`: из 3 узлов достаточно 2 живых, из 5 — 3. Четное количество не дает преимуществ (4 узла выдерживают отказ только одного), но увеличивает нагрузку на выборы. Практический выбор топологии мастер-узлов и их тюнинг — в [руководстве по настройке кластера](../Tutorials/cluster_setup.md).
* **Узлы данных (Data Nodes)**: Хранят шарды и выполняют запросы. Делятся на уровни (**Data Tiers**):
    * `content`: Для статичных данных с низкой частотой обновлений.
    * `hot`: Для активной записи и самого частого поиска (SSD).
    * `warm/cold`: Для данных, к которым обращаются реже (HDD или более дешевые SSD).
    * `frozen`: Поиск напрямую по **Searchable Snapshots** в объектном хранилище (S3) — локальный диск используется только как кэш.
* **Инжест-узел (Ingest)**: Предварительная обработка документов через `ingest pipelines` (парсинг, обогащение). При тяжёлой нагрузке ingest выносят на отдельные узлы, не совмещая роль с master- и data-узлами.
* **ML-узел (ml)**: Выполняет классические задачи машинного обучения — детекцию аномалий (anomaly detection jobs), датафрейм-аналитику, а также разворачивает модели инференса (ELSER, E5, модели Eland).
* **Remote-узел (remote_cluster_client)**: Клиент cross-cluster операций. Требуется для CCS и CCR: при CCR все master-узлы локального кластера должны иметь эту роль, при CCS запросы к remote-кластерам приходят на узел с этой ролью (детали — [CCR/CCS](./elasticsearch_ccr_ccs.md)).
* **Transform-узел (transform)**: Выполнение transform-задач (пивот-агрегации исторических данных). Требуется для transforms, а также Fleet и Elastic Security.
* **Voting-only узел (voting_only)**: Master-eligible узел, участвующий в кворуме, но никогда не избираемый мастером — узел-развязка (tiebreaker) для схем с чётным числом зон. Помечать `voting_only` можно только узлы с ролью `master` (подробнее — [настройка кластера](../Tutorials/cluster_setup.md)).
* **Координирующий узел (Coordinating)**: Принимает запросы, распределяет их по шардам (фазы scatter/gather) и агрегирует результаты. Любой узел по умолчанию может быть координирующим; выделенный координирующий узел задается пустым списком ролей `node.roles: []` и рекомендуется в нагруженных кластерах для защиты мастер-узлов и data-узлов от накладных расходов агрегации.

**Инференс (Inference) — не отдельная роль узла.** Встроенные модели (ELSER, E5) и модели, загруженные через Eland, разворачиваются на ML-узлах: число аллокаций и потоков управляется через Inference API (`num_allocations`, `num_threads`; adaptive allocations масштабируют аллокации до 0 через 15 минут простоя). Elastic Inference Service (EIS) — управляемый сервис инференса, не потребляющий ресурсы собственных узлов; сторонние модели (OpenAI, Cohere, Azure и др.) вызываются через Inference API извне.

### Лицензирование

Исходный код бесплатной части доступен под тремя лицензиями на выбор: Elastic License 2.0, SSPL v1 и AGPLv3 (AGPLv3 — одобренная OSI open-source лицензия, добавлена в 8.16). Клиентские библиотеки, Logstash и Beats распространяются под Apache 2.0. Функциональность разделена по уровням подписки:

| Уровень | Ключевые возможности |
| :--- | :--- |
| Basic (бесплатный) | Полнотекстовый поиск, агрегации, ES\|QL, векторный поиск (HNSW, int8/int4), снапшоты, ILM (фазы hot/warm/delete), downsampling, Cross-Cluster Search, Kibana Alerting (большинство типов правил) |
| Platinum | ML (anomaly detection, data frame analytics), Watcher, Cross-Cluster Replication |
| Enterprise | Searchable Snapshots (фазы ILM cold/frozen), ES\|QL через CCS, `bbq_disk` (9.2+), SLO |

> SSPL и ELv2 — не лицензии Open Source по OSI. Для организаций с жёсткими требованиями к лицензированию рассмотрите OpenSearch как альтернативу (см. [OpenSearch: Обзор](../OpenSearch/opensearch_overview.md)).

### Шардирование и Репликация

* **[Шард (Shard)](../../Databases/Concepts/sharding.md)**: Часть индекса; физически — самостоятельный Lucene-индекс со своим JVM-оверходом, файловыми дескрипторами и потоками слияния.
    * **Primary Shard**: Основная копия данных. Количество фиксируется при создании индекса (кроме Data Streams). Причина неизменности — механика маршрутизации: номер шарда вычисляется детерминированно от идентификатора документа:
      ```text
      shard_num = hash(_routing) % number_of_primary_shards
      ```
      где `_routing` по умолчанию равен `_id`. Изменение числа первичных шардов сделало бы существующие документы недоступными по этому адресу, поэтому вместо этого применяется reindex или Data Streams с ротацией. Начиная с версии 7.x новый индекс по умолчанию создается с **1** первичным шардом.
    * **Replica Shard**: Копия основного шарда. Служит для отказоустойчивости и масштабирования **чтения**. По умолчанию создается 1 реплика на каждый primary.
* **Балансировка**: Elasticsearch автоматически распределяет шарды между узлами, предотвращая перекосы нагрузки.
* **Лимиты**: Рекомендуемый размер шарда — 10–50 ГБ (для time-series типично 20–40 ГБ), менее 200 млн документов на шард; формулы расчёта — в [Capacity Planning](./elasticsearch_capacity_planning.md).
* **Овершардирование (Oversharding)** — главная ошибка проектирования: тысячи мелких шардов (единицы МБ) истощают heap мастер-узлов и замедляют выборы и восстановление. Ориентир — держать суммарное число шардов в пределах ~20 на 1 ГБ heap кластера и объединять мелкие индексы (см. Force Merge и ILM-ротацию в [заметке о жизненном цикле](./elasticsearch_ilm_and_retention.md)).

### Запись документа и видимость данных

Понимание жизненного цикла записи объясняет поведение поиска "почему документ еще не виден" и настройки производительности:

1. **Индексация**: Документ попадает в in-memory buffer шарда и параллельно дописывается в **Translog** — журнал упреждающей записи (Write-Ahead Log), обеспечивающий долговечность (durability): по умолчанию fsync выполняется на каждый запрос (`index.translog.durability: request`).
2. **Refresh**: Раз в секунду (по умолчанию) содержимое буфера сбрасывается в новый сегмент Lucene, и документ становится доступным для поиска. Отсюда модель *near-real-time search*: между записью и видимостью документа возможна задержка до `refresh_interval`.
3. **Flush**: Периодически (или по команде `_flush`) сегменты сбрасываются на диск с fsync, а Translog обрезается. После сбоя узел восстанавливает шард из последнего флаша + повторяет операции из Translog.
4. **Merge**: Фоновые потоки сливают мелкие сегменты в крупные, поддерживая производительность поиска. Удаление и обновление документов реализуются флагом удаления в старом сегменте; место освобождается только после слияния.

### Статусы здоровья кластера

Статус определяется по самому критичному состоянию индексов:
* **Green**: Все шарды (Primary и Replica) распределены и доступны.
* **Yellow**: Все Primary шарды доступны, но часть реплик не распределена (риск потери данных при сбое одного узла).
* **Red**: Хотя бы один Primary шард недоступен. Часть данных потеряна для поиска и записи.

Быстрая проверка из CLI:

```bash
curl -u elastic:$PASS -k "https://localhost:9200/_cluster/health?pretty"
```

```json
{
  "cluster_name" : "es-prod",
  "status" : "green",
  "timed_out" : false,
  "number_of_nodes" : 5,
  "number_of_data_nodes" : 3,
  "active_primary_shards" : 24,
  "active_shards" : 48,
  "unassigned_shards" : 0,
  "active_shards_percent_as_number" : 100.0
}
```

Ключевые поля для мониторинга: `status`, `unassigned_shards` (>0 — есть нераспределенные шарды, см. сценарий диагностики ниже) и `active_shards_percent_as_number`.

### Безопасность

* **Шифрование**: TLS между узлами (порт 9300) и для HTTP-трафика (порт 9200) включено по умолчанию.
* **Auto-configuration**: При первом старте (8.x+) security настраивается автоматически: генерируются пароль `elastic`, TLS-сертификаты для HTTP и transport и enrollment-токены. Отключается явной настройкой `xpack.security.autoconfiguration.enabled: false` (триггерит Bootstrap Checks).
* **RBAC**: Управление доступом на основе ролей интегрировано с `elastic` пользователем. Принцип наименьших привилегий: сервисам выдавайте роли с правами только на нужные индексы и действия, а не встроенную роль `superuser`.
* **Enrollment Tokens**: Упрощают подключение новых узлов и Kibana через автоматический обмен сертификатами. Токен действует 30 минут; перевыпуск: `bin/elasticsearch-create-enrollment-token -s node` (или `-s kibana`).
* **API-ключи**: Предпочтительный способ аутентификации приложений вместо передачи логина/пароля: ключи можно ограничить по ролям и отозвать независимо от пользователей.
* **Пароли**: Смена пароля суперпользователя выполняется утилитой `bin/elasticsearch-reset-password -u elastic` или через `PUT /_security/user/elastic/_password`.

## Практические сценарии

**Предварительные требования для всех сценариев:**

* Рабочий кластер Elasticsearch 8.x/9.x (single-node стенд в Docker — [руководство](../Tutorials/practical_setup_with_docker.md), мультинода — [руководство по кластеру](../Tutorials/cluster_setup.md)).
* Переменная окружения с паролем суперпользователя и утилита `curl`:

```bash
export ES="https://localhost:9200"
export PASS="<пароль пользователя elastic>"
# Проверка доступности:
curl -u elastic:$PASS -k "$ES"   # → {"name" : "es-node-1", "cluster_name" : "es-prod", "version" : {...}, "tagline" : "You Know, for Search"}
```

* Флаг `-k` отключает проверку самоподписанного сертификата TLS (в Prod используйте `--cacert http_ca.crt`).

### Быстрый старт: первый индекс и документ

Минимальный цикл проверки работоспособности кластера от записи до поиска.

```bash
# 1. Создать документ (индекс создастся автоматически с динамическим маппингом)
curl -u elastic:$PASS -k -X POST "$ES/my-first-index/_doc?refresh=true" \
-H 'Content-Type: application/json' -d'
{ "title": "DevOps guide", "tags": ["elk", "search"], "views": 10 }'
# → {"_index":"my-first-index","_id":"<автогенерированный>","result":"created","_shards":{"total":2,"successful":1,"failed":0}}

# 2. Найти документ полнотекстовым запросом
curl -u elastic:$PASS -k "$ES/my-first-index/_search?q=title:devops&pretty"
# → hits.total.value = 1; найденный документ лежит в hits.hits[0]._source

# 3. Удалить тестовые данные (очистка окружения)
curl -u elastic:$PASS -k -X DELETE "$ES/my-first-index"
# → {"acknowledged":true}
```

Пояснения: параметр `refresh=true` делает документ видимым немедленно, минуя секундный интервал refresh (для тестов; в продакшене не используется — см. раздел про запись). Ответ `_shards.total=2` означает primary+replica; на single-node кластере `successful=1`, а статус кластера станет `yellow` — это ожидаемо, реплике некуда распределиться.

### Гибридный поиск с использованием RRF

Современный подход, сочетающий классический поиск (BM25) и векторный поиск для повышения качества результатов.

```json
GET /my-index/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "match": { "text": "devops guide" } } } },
        { "knn": { "field": "vector_field", "query_vector": [0.1, 0.2, ...], "k": 10 } }
      ]
    }
  }
}
```
*   **RRF (Reciprocal Rank Fusion)**: Алгоритм ранжирования, объединяющий списки результатов из разных движков поиска.

### Обслуживание узла (Rolling Update)

Для безопасного выключения узла без массовой перебалансировки шардов:

0.  **Предварительная проверка**: Убедитесь, что кластер `green` и все реплики распределены, иначе обслуживание усугубит деградацию:
    ```bash
    curl -u elastic:$PASS -k "$ES/_cluster/health?wait_for_status=green&timeout=30s"
    # → {"status":"green","timed_out":false,"unassigned_shards":0,...}
    ```
    Дополнительно можно заранее вытеснить шарды с узла настройкой `"cluster.routing.allocation.exclude._name": "<имя-узла>"`.
1.  **Приостановить аллокацию реплик**:
    ```bash
    curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_cluster/settings" \
    -H 'Content-Type: application/json' -d'
    { "persistent": { "cluster.routing.allocation.enable": "primaries" } }'
    ```
2.  Выполнить обслуживание (обновление ОС, замена диска). Останавливайте процесс корректно (`systemctl stop elasticsearch`, SIGTERM) — Elasticsearch выполнит чистое закрытие шардов и транслога.
3.  **Включить аллокацию обратно**:
    ```bash
    curl -u elastic:$PASS -k -X PUT "https://localhost:9200/_cluster/settings" \
    -H 'Content-Type: application/json' -d'
    { "persistent": { "cluster.routing.allocation.enable": "all" } }'
    ```
4.  **Валидация результата**: Реплики должны восстановиться без ручного вмешательства, узел — вернуться в ротацию:
    ```bash
    curl -u elastic:$PASS -k "$ES/_cluster/health?wait_for_status=green&timeout=120s"
    # → {"status":"green","unassigned_shards":0}
    curl -u elastic:$PASS -k "$ES/_cat/nodes?v&h=name,node.role,heap.percent,disk.used_percent"
    # → вернувшийся узел виден в списке; heap.percent желательно < 75
    ```

Повторяйте шаги для каждого узла по очереди; не обслуживайте два master-eligible узла одновременно, чтобы не потерять кворум.

### Использование ES|QL для аналитики

Пример запроса для агрегации логов по статусам:
```sql
FROM logs-*
| WHERE @timestamp > NOW() - 15 minutes
| STATS count = COUNT(*) BY status_code
| SORT count DESC
```
*   **Преимущество**: Выполняется на поколоночном движке, что значительно быстрее стандартных Query DSL агрегаций.
*   **Запуск из CLI** (в Kibana Dev Tools тот же запрос вводится как есть):
    ```bash
    curl -u elastic:$PASS -k -X POST "$ES/_query?pretty" \
    -H 'Content-Type: application/json' -d'
    {
      "query": """
        FROM logs-*
        | WHERE @timestamp > NOW() - 15 minutes
        | STATS count = COUNT(*) BY status_code
        | SORT count DESC
        | LIMIT 10
      """
    }'
    ```
    ```text
       status_code   |    count
    -----------------+--------------
    200              |          842
    404              |           31
    500              |            7
    ```
*   **Обогащение (LOOKUP JOIN, GA с 8.19/9.1)**: команда `LOOKUP JOIN` обогащает события данными lookup-таблиц без денормализации; ES|QL также поддерживает Cross-Cluster Search (GA, требует Enterprise на всех участвующих кластерах). С 8.19/9.1 настройка `allow_partial_results` включена по умолчанию — запрос завершается частичными результатами, если часть шардов временно недоступна (например, во время rolling upgrade).
*   **Ограничения**: ES|QL дополняет, но не заменяет Query DSL: запись через него недоступна, часть поисковых функций отсутствует. Для гибридного поиска используйте retrievers (сценарий выше).
*   **Справочник языка**: команды и конвейер, REST API (`POST /_query`), форматы ответа, права доступа, асинхронные запросы и параметризация — в [ES|QL — конвейерный язык запросов](./esql-query-language.md).

### Диагностика нераспределенных шардов (Yellow/Red)

Сценарий: после отказа узла статус `yellow` или `red`, часть шардов в состоянии `UNASSIGNED`.

```bash
# 1. Найти проблемные шарды и код причины
curl -u elastic:$PASS -k "$ES/_cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state:desc"
# → logs-2026.08.23 0 r UNASSIGNED NODE_LEFT
# Частые reason: INDEX_CREATED, CLUSTER_RECOVERED, NODE_LEFT, ALLOCATION_FAILED

# 2. Получить объяснение планировщика для конкретного шарда
curl -u elastic:$PASS -k "$ES/_cluster/allocation/explain?pretty" \
-H 'Content-Type: application/json' -d'
{ "index": "logs-2026.08.23", "shard": 0, "primary": false }'
```

```json
{
  "can_allocate" : "no",
  "allocate_explanation" : "Elasticsearch isn't allowed to allocate this shard to any of the nodes...",
  "node_allocation_decisions" : [ {
      "node_name" : "es-data-2",
      "node_decision" : "no",
      "store" : { "in_sync" : [ { "allocation_id" : "..." } ] }
  } ]
}
```

Типовые выводы explain и действия:

* **`decider: SAME_SHARD`** — реплику нельзя размещать на узел, где уже живет primary того же шарда: добавьте узел данных или временно снизите `number_of_replicas`.
* **`decider: DISK_WATERMARK`** — не хватает места на диске; пороги и порядок действий описаны в [руководстве по кластеру](../Tutorials/cluster_setup.md).
* **`decider: INDEX_READ_ONLY_ALLOW_DELETE`** — индекс заблокирован flood stage; решение в разделе устранения неполадок ниже.
* Реплика без живой копии данных (`can_allocate: no_valid_copy`), а данные больше не нужны — удалите индекс; если нужны — восстановите из снапшота.

### Диагностика кластера: ключевые команды

Команды повседневной эксплуатации (все `_cat` API поддерживают `?format=json` и `?bytes=b` для точных значений):

| Команда | Что показывает |
| :--- | :--- |
| `GET /` | Версия, имя и UUID кластера |
| `GET _license` | Текущий уровень лицензии и дата истечения |
| `GET _cat/indices?v&h=index,health,status,docs.count,store.size,pri,rep` | Состояние, размер и число документов по индексам |
| `GET _cat/allocation?v` | Занятость диска и распределение шардов по узлам |
| `GET _cat/thread_pool?v&h=node_name,name,active,queue,rejected` | Очереди и отклонения в потоках (write, search) |
| `GET _cat/recovery?v` | Прогресс восстановления шардов (relocation, recovery) |
| `GET _cat/snapshots/<repo>?v` | Статус снапшотов в репозитории |
| `GET _cat/repositories?v` | Зарегистрированные репозитории снапшотов |
| `GET _cluster/stats` | Сводная статистика кластера: индексы, шарды, узлы, память |
| `GET _nodes/stats` | Метрики узлов: os, jvm, process, fs, breaker |
| `GET _nodes/hot_threads` | Горячие потоки — CPU-интенсивные операции |
| `GET _cluster/pending_tasks` | Очередь задач мастера (задержки применения метаданных) |
| `GET _tasks?detailed=true&actions=*search*` | Долгие выполняющиеся задачи (поиск, reindex) |

Пример диагностики перегрузки записи (иллюстративный вывод):
```bash
curl -u elastic:$PASS -k "$ES/_cat/thread_pool?v&h=node_name,name,active,queue,rejected" | grep -E "write|search"
# → es-data-1  write  4  0  0
# Растущие queue и rejected в потоке write → backpressure (см. таблицу устранения неполадок)
```

### Резервное копирование: снапшоты

Снапшот — согласованная копия индексов (в т.ч. состояния кластера) во внешнем репозитории. Снапшоты обычных индексов доступны в бесплатном уровне лицензии; Searchable Snapshots (поиск прямо по снимку) требуют Enterprise — см. [ILM](./elasticsearch_ilm_and_retention.md).

```bash
# 0. Prerequisite: путь репозитория должен быть прописан на всех узлах
#    elasticsearch.yml → path.repo: ["/mnt/es-snapshots"] (общий каталог или NFS)

# 1. Зарегистрировать файловый репозиторий
curl -u elastic:$PASS -k -X PUT "$ES/_snapshot/local-backup" \
-H 'Content-Type: application/json' -d'
{ "type": "fs", "settings": { "location": "/mnt/es-snapshots", "compress": true } }'
# → {"acknowledged":true}

# 2. Проверить регистрацию
curl -u elastic:$PASS -k -X POST "$ES/_snapshot/local-backup/_verify"
# → {"nodes":{"<node_id>":{"name":"es-node-1"}}}

# 3. Снять снапшот всех открытых индексов
curl -u elastic:$PASS -k -X PUT "$ES/_snapshot/local-backup/snap-2026-08-23?wait_for_completion=true" \
-H 'Content-Type: application/json' -d'
{ "indices": "*", "ignore_unavailable": true, "include_global_state": false }'
# → {"snapshot":{"snapshot":"snap-2026-08-23","uuid":"...","state":"SUCCESS","indices":[...],"shards":{"total":48,"failed":0,"successful":48}}}

# 4. Восстановление (индекс должен быть закрыт или переименован)
curl -u elastic:$PASS -k -X POST "$ES/_snapshot/local-backup/snap-2026-08-23/_restore?wait_for_completion=true" \
-H 'Content-Type: application/json' -d'
{ "indices": "my-index", "rename_pattern": "(.+)", "rename_replacement": "restored-$1" }'
# → {"snapshot":{"snapshot":"snap-2026-08-23","indices":{"restored-my-index":{"shards":{"total":2,"failed":0,"successful":2}}}}}
```

Пояснения: `include_global_state: false` исключает состояние кластера из снапшота (иначе повторный снимок отклоняется при смене состава master-eligible узлов); `rename_*` позволяет восстановить индекс под новым именем поверх существующего без его удаления. Регулярное расписание настраивается политикой SLM (`PUT /_slm/policy/<name>`). Очистка тестового репозитория: `DELETE /_snapshot/local-backup/snap-*`, затем `DELETE /_snapshot/local-backup`.

### Аутентификация приложений через API-ключи

Вместо передачи пароля `elastic` приложениям создавайте ограниченные ключи:

```bash
curl -u elastic:$PASS -k -X POST "$ES/_security/api_key?pretty" \
-H 'Content-Type: application/json' -d'
{
  "name": "app-log-writer",
  "role_descriptors": {
    "log-writer": {
      "cluster": ["monitor"],
      "indices": [
        { "names": ["logs-app-*"], "privileges": ["create_doc", "auto_configure"] }
      ]
    }
  }
}'
# → {"id":"<ключ-id>","name":"app-log-writer","api_key":"<закодированный ключ>"}
```

Использование в запросах: заголовок `Authorization: ApiKey <base64(id:api_key)>`. Отзыв: `DELETE /_security/api_key/<id>`. Ключ действует согласно `expiration` (если задана) и наследует права указанных ролей — при компрометации отзывается независимо от пользователя.

## Устранение неполадок

| Симптом / ошибка | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| `429 Too Many Requests`, `circuit_breaking_exception` | Parent circuit breaker превысил ~95% heap (крупные агрегации, fielddata) | `GET /_nodes/stats/breaker` — какой breaker сработал; уменьшайте размер выборки/агрегаций, проверяйте heap по `_cat/nodes`; масштабируйте RAM до 31 ГБ |
| `429 ... es_rejected_execution_exception` при bulk | Переполнена очередь write thread pool — пишете быстрее, чем индексируется | Уменьшите размер батчей (5-15 МБ), добавьте паузу/backpressure у отправителя, увеличьте `refresh_interval` |
| `cluster_block_exception: FORBIDDEN/12/index read-only /api/allow delete` | Сработал flood_stage (диск >95%) — индексы заблокированы на запись | Освободите место, затем снимите блокировку: `PUT /<index>/_settings {"index.blocks.read_only_allow_delete": null}` |
| Статус `yellow` на single-node / dev-стенде | Репликам нет куда распределиться (узел один) | Нормально для стенда: `"number_of_replicas": 0` в шаблоне или осознанно игнорировать |
| Узел не стартует: `vm.max_map_count [65536] is too low, increase to at least [262144]` | Bootstrap Checks: системные лимиты ОС не выполнены | `sysctl -w vm.max_map_count=262144` (персистентно — в `/etc/sysctl.d/`); аналогично поднимите nofile |
| `master_not_discovered_exception`, кластер не выбирает мастера | Потеряно большинство master-eligible узлов (кворума нет) | Верните в строй упавший master-eligible узел (приоритет). В крайнем случае — аварийная процедура `bin/elasticsearch-node unsafe-bootstrap` на узле со свежайшими данными (риск потери последних операций; применять осознанно) |
| Контейнер Elasticsearch падает, exit code 137 | OOM Killer убил процесс (мало памяти Docker/хоста) | Диагностика и решение описаны в [Docker-руководстве](../Tutorials/practical_setup_with_docker.md) |
| Поиск не находит свежезаписанный документ | Не наступил refresh (по умолчанию 1 сек) | Ждать либо `POST /<index>/_refresh`; в тестах использовать `?refresh=true` |

## Рекомендации по эксплуатации (Best Practices)

*   **JVM Heap**: Устанавливайте 50% от физической RAM. **Лимит: 31 ГБ** (для сохранения работы Compressed OOPs). Выделение 32 ГБ и более может привести к *снижению* производительности из-за 64-битных указателей. Heap задается через файл `jvm.options.d/heap.options` (`-Xms` = `-Xmx`), а не правкой основного `jvm.options`.
*   **Refresh Interval**: Для индексов с логами увеличьте `refresh_interval` до `30s` или `60s`. Это снижает нагрузку на CPU за счет редкого создания Lucene-сегментов.
*   **Vector Quantization**: Используйте `int8` или `int4` для HNSW индексов в больших кластерах. Это экономит до 75% RAM при поиске по эмбеддингам.
*   **Swap**: Должен быть полностью отключен (`swapoff -a`), чтобы избежать "замираний" узла при сборке мусора. Дополнительно зафиксируйте heap от выгрузки: `bootstrap.memory_lock: true`.
*   **Off-heap память**: Графы HNSW и page cache живут вне heap — оставляйте ОС вторую половину RAM (fielddata, наоборот, загружается в JVM heap и ограничивается fielddata breaker — см. [Search Tuning](./elasticsearch_search_tuning.md); см. также [заметку о маппинге](./elasticsearch_mapping_and_indexing.md)).
*   **Системные лимиты**: Обязательные требования к ОС для сетевого режима: `vm.max_map_count >= 262144`, nofile не менее 65535. Проверка: `sysctl vm.max_map_count`.
*   **Bulk-индексация**: Используйте пакеты 5-15 МБ; после разовой массовой загрузки выполните `_forcemerge?max_num_segments=1` на закрытых индексах (для потоковых данных это делает ILM в фазе warm).
*   **Мониторинг и алертинг**: Включите Stack Monitoring и настройте алерты на ключевые метрики (heap, диск, unassigned shards) — см. [Stack Monitoring](./elasticsearch_stack_monitoring.md) и [Alerting](./elasticsearch_alerting.md).

## Дополнительная информация

### Ключевые настройки `elasticsearch.yml`

*   `cluster.name`: Имя кластера (обязательно совпадение на всех узлах).
*   `discovery.seed_hosts`: Список IP других узлов для формирования кластера.
*   `cluster.initial_master_nodes`: Список имен узлов для первого запуска (bootstrap). После первого старта настройку удаляют из конфига всех узлов — повторный запуск с ней опасен расщеплением кластера.
*   `cluster.routing.allocation.disk.watermark.low`: Порог (85%), после которого ES перестает назначать новые шарды на узел.
*   `cluster.routing.allocation.disk.watermark.high`: Порог (90%), при котором ES начинает выселять существующие шарды с узла на другие.
*   `cluster.routing.allocation.disk.watermark.flood_stage`: Порог (95%), при котором все индексы на узле переходят в `read-only`.

Минимальные примеры для типовых ролей:

```yaml
# Узел master-eligible
cluster.name: es-prod
node.name: es-master-1
node.roles: [ master ]                       # только управление кластером, без данных
network.host: 0.0.0.0                        # слушать внешние интерфейсы (включает bootstrap checks)
discovery.seed_hosts: ["10.0.0.11","10.0.0.12","10.0.0.13"]     # адреса master-eligible узлов
cluster.initial_master_nodes: ["es-master-1","es-master-2","es-master-3"]  # ТОЛЬКО первый запуск
path.data: /var/lib/elasticsearch
path.logs: /var/log/elasticsearch
```

```yaml
# Узел data_hot + ingest (типовой приемник логов)
cluster.name: es-prod
node.name: es-hot-1
node.roles: [ data_hot, data_content, ingest ]
network.host: 0.0.0.0
discovery.seed_hosts: ["10.0.0.11","10.0.0.12","10.0.0.13"]
path.data: /var/lib/elasticsearch
```

Каждый параметр: `node.roles` фиксирует функции узла (полный список ролей см. выше); `network.host` отличен от loopback, поэтому при старте выполняются строгие Bootstrap Checks (см. устранение неполадок); `path.data` должен лежать на быстром диске с достаточным местом.

---
*   **[Настройка кластера Elasticsearch 8](../Tutorials/cluster_setup.md)** — практическое руководство по развертыванию.
*   **[Elasticsearch: ILM и политики хранения](./elasticsearch_ilm_and_retention.md)** — автоматизация жизненного цикла данных.
*   **[Elasticsearch: Индексирование и маппинг](./elasticsearch_mapping_and_indexing.md)** — детально о структурах данных.
*   **[Elasticsearch: Траблшутинг индексации](./elasticsearch_troubleshooting_indexing.md)** — диагностика проблем индексации и сегментов.
*   **[Elasticsearch: Capacity Planning](./elasticsearch_capacity_planning.md)** — проектирование кластера и расчет мощностей.
*   **[Ingest Pipelines](./elasticsearch_ingest_pipelines.md)** — обработка документов перед индексацией: процессоры grok, dissect, geoip.
*   **[Index Templates и Data Streams](./elasticsearch_index_templates.md)** — Composable Templates, Data Streams для time-series данных.
*   **[Search Performance Tuning](./elasticsearch_search_tuning.md)** — оптимизация поиска: кэширование, profiling, routing.
*   **[Stack Monitoring](./elasticsearch_stack_monitoring.md)** — ключевые метрики для мониторинга кластера.
*   **[Security Advanced](./elasticsearch_security_advanced.md)** — DLS, FLS, Audit Logging, SAML/OIDC интеграция.
*   **[Alerting](./elasticsearch_alerting.md)** — Kibana Alerting rules, Watcher, Connectors.
*   **[Cross-Cluster Replication и Search](./elasticsearch_ccr_ccs.md)** — CCR для DR, CCS для межкластерного поиска.
*   **[Rollup и Transform](./elasticsearch_rollup_transform.md)** — агрегация исторических данных.
*   **[Disaster Recovery](./elasticsearch_disaster_recovery.md)** — паттерны аварийного восстановления.
*   **[Upgrades и миграция](./elasticsearch_upgrades.md)** — Rolling Upgrade, Blue-Green deployment.
*   **[Network и Firewall](../elasticsearch_network_requirements.md)** — порты, протоколы, firewall rules.
