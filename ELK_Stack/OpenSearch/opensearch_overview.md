# OpenSearch: Обзор

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и служит основной точкой входа для изучения OpenSearch — полностью открытой альтернативы Elastic Stack.

## Определения

* **OpenSearch** — распределенный поисковый и аналитический движок с открытым исходным кодом (лицензия Apache 2.0). Проект создан как форк Elasticsearch 7.10.2 и развивается под эгидой OpenSearch Software Foundation (проект Linux Foundation с сентября 2024 года, при поддержке AWS, Oracle, Red Hat и др.).
* **OpenSearch Dashboards** — веб-интерфейс для визуализации данных и управления кластером; детальное руководство: **[OpenSearch Dashboards](./opensearch_dashboards.md)**.
* **Neural Search** — набор возможностей для реализации семантического поиска с использованием векторов (embeddings) и моделей машинного обучения.
* **Search Pipeline** — механизм модульной обработки поисковых запросов и ответов (переписывание запросов, фильтрация, нормализация) на стороне сервера.
* **Remote-Backed Storage** — архитектурное решение, позволяющее использовать объектные хранилища (S3, Azure Blob, GCS, HDFS) как уровень долговечного хранения данных, обеспечивая разделение ресурсов вычисления и хранения.
* **k-NN** — плагин приближенного поиска K ближайших соседей (Approximate Nearest Neighbor, ANN), превращающий OpenSearch в полноценную векторную базу данных.
* **Data Prepper** — самостоятельный компонент экосистемы OpenSearch для приема и преобразования данных (нативная поддержка OTLP, фильтрация, обогащение) перед индексацией; аналог Logstash в стеке Elastic.

## Основные концепции

### История и лицензирование

OpenSearch появился в 2021 году после изменения лицензионной политики Elastic. В отличие от Elasticsearch, OpenSearch остается под лицензией Apache 2.0, что позволяет использовать все функции (Security, Alerting, ML) бесплатно в коммерческих и SaaS-решениях.

Ключевые вехи развития:

| Версия | Дата | Значимые изменения |
| :--- | :--- | :--- |
| 1.x | 2021 | Первый релиз форка на базе Elasticsearch 7.10.2 |
| 2.x | 2022–2024 | Segment Replication, развитие k-NN, зрелость ISM |
| 3.0 | май 2025 | Apache Lucene 10, JVM 21 (минимум), удаление Java Security Manager, экспериментальный gRPC-транспорт |
| 3.2 | 2025 | gRPC Bulk API и k-NN поиск — General Availability |
| 3.5 | февраль 2026 | Agentic conversation memory, hook-based управление контекстом для оптимизации LLM-токенов, расширенная Prometheus-поддержка |
| 3.8.0 | август 2026 | Актуальная стабильная версия |

По состоянию на 2026 год OpenSearch значительно дивергировал от Elasticsearch, сфокусировавшись на открытости, производительности (независимый бенчмарк Trail of Bits в марте 2025 показал преимущество OpenSearch в ряде сценариев, включая векторный поиск) и интеграции с генеративным ИИ.

### Ключевые возможности (OpenSearch 3.x)

* **Современный фундамент (с версии 3.0)**: ядро Apache Lucene 10 (sparse indexing, улучшенный параллельный ввод-вывод, векторное квантование) на JVM 21; прирост до ~20% на агрегированных операциях по сравнению с веткой 2.19 и более чем 9.5x по сравнению с веткой 1.3 (данные официальных бенчмарков проекта).
* **Встроенная безопасность (Security Plugin)**: TLS, интеграция с AD/LDAP/SAML и тонкая настройка прав доступа (FGAC — Fine-Grained Access Control: security на уровне документов и полей) включены в базовую версию. В 3.x снижены накладные расходы FGAC за счет уменьшения объема внутренней сериализации при межузловом обмене.
* **Segment Replication**: репликация готовых сегментов Lucene вместо повторной индексации документов на репликах; снижает нагрузку на CPU primary-узла (реплики не выполняют индексацию самостоятельно) и повышает throughput записи ценой роста сетевого трафика. Начиная с версии 2.10 является обязательным условием для включения Remote-Backed Storage.
* **Disk-Optimized Vector Search**: бинарное квантование (Binary Quantization) сокращает потребление памяти для векторного поиска до 32 раз при сохранении высокой точности; дополнено SQ-кодированием Faiss (16/32x сжатие) и экспериментальными derived source fields (удаление векторов из `_source` с динамической инъекцией при чтении).
* **Hybrid Search**: одновременное выполнение лексического (BM25) и векторного поиска с автоматической нормализацией и ранжированием результатов через search pipeline.
* **Index State Management (ISM)**: автоматизация жизненного цикла индексов через политики (ротация, перемещение между узлами hot/warm, удаление).
* **gRPC-транспорт**: бинарный протокол взаимодействия клиент–сервер (protobuf поверх gRPC) как высокопроизводительная альтернатива HTTP/JSON; Bulk API и k-NN запросы GA с версии 3.2, остальной функционал пока экспериментальный.
* **Pull-based Ingestion**: прямое вычитывание данных из Apache Kafka силами самого кластера без внешних агентов (экспериментальная возможность; настраиваемые таймауты метаданных появились в 3.7).
* **Telemetry Plugin**: сбор внутренних метрик производительности на базе OpenTelemetry; заменил связку Performance Analyzer + RCA agent, удаленную в версии 3.0.
* **AI-экосистема**: ML Commons (выполнение локальных моделей на узлах кластера и вызов внешних сервисов), AI Agent Framework, agentic memory (3.5+) — конвейер для построения RAG-приложений без внешней инфраструктуры.

### OpenSearch как векторная база данных

OpenSearch является одним из лидеров среди векторных хранилищ благодаря плагину **k-NN**:

* **Движки**: Основные — **Faiss** и **Lucene**; движок NMSLIB объявлен устаревшим (deprecated) с версии 3.0 и рекомендуется к миграции.
* **Важное изменение 3.0**: движок по умолчанию сменен с NMSLIB на Faiss. Если индекс использует `space_type: "cosinesimil"` без явного указания движка, векторы автоматически нормализуются к единичной длине при индексации — это меняет поведение существующих приложений при обновлении кластера.
* **Выбор движка**: Faiss/HNSW — для крупных развертываний (до 16 000 измерений, post-filtering); Lucene — для небольших наборов (лучшие латентность и recall до нескольких миллионов векторов) и умной фильтрации (адаптивный выбор pre/post-filtering во время поиска); Faiss/IVF — когда допустимо обучение индекса ради компактности.
* **Масштабируемость**: поиск по миллиардам векторов в распределенном кластере; параллельное выполнение k-NN запросов ускорено в ~2.5 раза в Lucene 10 по сравнению с предыдущей версией ядра.
* **Интеграция с ML**: локальные модели на узлах кластера (ML Commons) и внешние сервисы (Amazon Bedrock, OpenAI, Cohere) для генерации эмбеддингов "на лету" через Ingest Pipelines.

Пример создания векторного индекса (OpenSearch 3.x):

```json
PUT /products-vectors
{
  "settings": { "index": { "knn": true } },
  "mappings": {
    "properties": {
      "title": { "type": "text" },
      "embedding": {
        "type": "knn_vector",
        "dimension": 4,
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "space_type": "cosinesimil"
        }
      }
    }
  }
}
# → {"acknowledged": true, "shards_acknowledged": true, "index": "products-vectors"}
```

> Примечание: реальная размерность определяется моделью эмбеддингов (например, 384 для all-MiniLM-L6-v2, 768 для many BERT-моделей, 1536 для text-embedding-3-small). Значение `4` здесь — для читаемости примера.

### Сравнение с Elasticsearch (актуально на 2026 год)

| Характеристика | OpenSearch | Elasticsearch |
| :--- | :--- | :--- |
| **Лицензия** | Apache 2.0 (открытая) | ELv2 / SSPL + AGPLv3 как опция (с версии 8.16, август 2024) |
| **Стоимость** | Все функции бесплатны | Бесплатный базовый уровень; платные Enterprise-функции |
| **Версионная линия** | 3.x (Lucene 10, JVM 21) | 8.x–9.x |
| **AI/ML** | Гибкая интеграция любых моделей (ML Commons, коннекторы) | Мощные встроенные модели (ELSER), AI Assistant |
| **Хранение** | Глубокая интеграция с S3 (Remote Store + lightweight snapshots) | Searchable Snapshots, Data Tiers |
| **Производительность** | Сильные результаты в бенчмарках индексации и векторного поиска (Trail of Bits, 2025) | Лидер в задержках сложного поиска |

Обе системы продолжают взаимно перенимать удачные решения (Data Streams, ISM/ILM, гибридный поиск), но их API уже несовместимы: миграция между ними требует переиндексации данных.

## Практические сценарии

### Быстрый старт: локальный кластер за 5 минут

Требования: Docker 20+, 2 ГБ свободной RAM. Начиная с OpenSearch 2.12 контейнер требует задания начального пароля администратора переменной `OPENSEARCH_INITIAL_ADMIN_PASSWORD` (минимум 8 символов: заглавная буква, цифра, спецсимвол).

```bash
docker run -d --name opensearch-dev \
  -p 9200:9200 -p 9600:9600 \
  -e discovery.type=single-node \
  -e OPENSEARCH_INITIAL_ADMIN_PASSWORD='Dev#2026Start!' \
  opensearchproject/opensearch:3.8.0
# → контейнер запущен; полная готовность кластера через 30–60 секунд

curl -ku admin:'Dev#2026Start!' https://localhost:9200
# → {
# →   "name" : "opensearch-dev",
# →   "cluster_name" : "opensearch",
# →   "version" : {
# →     "distribution" : "opensearch",
# →     "number" : "3.8.0",
# →     "build_flavor" : "default", ...
# →   },
# →   "tagline" : "The OpenSearch Project: https://opensearch.org/"
# → }
```

Порты: `9200` — HTTP API (TLS включен по умолчанию), `9600` — внутренние метрики узла. Проверка установленных плагинов:

```bash
docker exec opensearch-dev bin/opensearch-plugin list
# → org.opensearch.knn
# → org.opensearch.neuralsearch
# → org.opensearch.security
# → ... (полный набор входит в дистрибутив)
```

> Внимание: демонстрационные сертификаты (`demo certs`) подходят только для локальных экспериментов. Для production замените их собственным PKI и отключите демо-конфигурацию (`plugins.security.ssl.http.enabled_custom_certonly...`, см. [Администрирование](./opensearch_administration.md)).

### Проверка векторного поиска end-to-end

Продолжение работы с индексом из раздела выше — добавление документа и ANN-поиск:

```json
POST /products-vectors/_doc?refresh=true
{
  "title": "Механическая клавиатура",
  "embedding": [0.45, -1.2, 3.1, 0.87]
}
# → {"_index":"products-vectors","result":"created","_shards":{"successful":1}}

GET /products-vectors/_search
{
  "size": 3,
  "query": {
    "knn": {
      "embedding": {
        "vector": [0.4, -1.1, 3.0, 0.9],
        "k": 3
      }
    }
  }
}
# → {"hits":{"total":{"value":1},"hits":[{"_source":{"title":"Механическая клавиатура"},
# →   "_score":0.98,...}]}}
```

Пояснения: параметр `k` задает число ближайших соседей; `_score` вычисляется из косинусного сходства (чем ближе к 1, тем похожее документы). Для генерации векторов из текста подключите Neural Search pipeline (см. сценарий RAG ниже).

### Реализация RAG (Retrieval-Augmented Generation)

OpenSearch выступает в роли хранилища знаний для LLM:

1. **Ingest**: данные поступают в OpenSearch, где search pipeline с процессором `text_embedding` автоматически превращает текст в векторы.
2. **Search**: пользователь задает вопрос; выполняется Hybrid Search (лексический BM25 + семантический поиск) с нормализацией результатов процессором `normalization`.
3. **Response**: результаты передаются в LLM как контекст для генерации точного ответа.

Настройка пайплайна эмбеддингов на стороне сервера:

```json
PUT /_search/pipeline/nlp-ingest-pipeline
{
  "request_processors": [
    {
      "text_embedding": {
        "model_id": "<model_id>",
        "field_map": {
          "question_text": "question_embedding"
        }
      }
    }
  ]
}
# → {"acknowledged": true}

PUT /rag-index/_settings
{ "index.search.default_pipeline": "nlp-ingest-pipeline" }
# → {"acknowledged": true}
```

Идентификатор модели `<model_id>` получают после регистрации модели через ML Commons API (`POST /_plugins/_ml/models/_register`); для внешних провайдеров предварительно настраивается коннектор (Bedrock, OpenAI, Cohere).

### Интеграция с Jaeger для трассировки

OpenSearch — один из стандартных бэкендов для **[Jaeger](../../Jaeger/jaeger_overview.md)**:

* **Прямая запись**: Jaeger Collector пишет спаны напрямую в индексы OpenSearch.
* **Trace Analytics**: использование плагина Observability в OpenSearch Dashboards для визуализации карт сервисов и поиска "узких мест" в распределенных транзакциях.

### Автоматизация логов через ISM

Настройка политик хранения без внешних инструментов:

* **Hot**: логи активно пишутся на SSD-узлы (7 дней).
* **Warm**: индексы переносятся на HDD или Remote Storage (23 дня).
* **Delete**: автоматическое удаление через 30 дней.

Полное руководство с примерами политик и rollover: **[Управление жизненным циклом индексов (ISM)](./opensearch_ism_lifecycle.md)**.

## Дополнительная информация

### Мониторинг и производительность

* **Telemetry Plugin** (3.0+): экспорт внутренних метрик узлов (JVM, пулы потоков, кэши) через OpenTelemetry в Prometheus или другой OTLP-приемник. Проверка доступности метрик локально:
  ```bash
  curl -ku admin:$OS_PASS https://localhost:9600/_plugins/_telemetry/metrics
  # → JSON с метриками узла (prometheus-экспортер настраивается отдельно)
  ```
* **Query Insights**: встроенная в 2.x/3.x подсистема сбора топ-N медленных и ресурсоемких запросов — отправная точка для оптимизации.
* **Search/Shard Indexing Backpressure**: механизмы динамического ограничения входящей нагрузки при перегрузке индексатора, защищающие кластер от каскадных отказов.
* **Segment Replication Stats**: `GET /_cat/segment_replication?v` показывает отставание реплик (replication lag) — ключевую метрику при включенной сегментной репликации.

### Безопасность

* **Начальный пароль администратора**: обязательное требование с версии 2.12 (`OPENSEARCH_INITIAL_ADMIN_PASSWORD`); стандартный пароль `admin` больше не допустим.
* **TLS на всех слоях**: транспортном (между узлами) и HTTP; для production используйте собственный PKI вместо демо-сертификатов.
* **FGAC**: роли, сопоставление ролей пользователям (roles_mapping), document-level security (DLS) и field-level security (FLS)/masking включены бесплатно; в 3.x их накладные расходы заметно снижены.
* Управление пользователями и ролями через REST API и `securityadmin.sh`: см. [Администрирование OpenSearch](./opensearch_administration.md).

### Обновление до ветки 3.x: критические требования

1. **Переиндексация старых данных**: индексы, созданные в Elasticsearch ≤ 7.10.2 или OpenSearch ≤ 1.3, несовместимы с 3.x — их необходимо переиндексировать (`_reindex`) до обновления, независимо от уровня хранения.
2. **JVM 21**: минимальная версия среды выполнения; проверьте кастомные плагины на совместимость с Lucene 10 и удалением Java Security Manager.
3. **k-NN**: движок NMSLIB deprecated, движок по умолчанию — Faiss (с нормализацией векторов для `cosinesimil` без явного движка); устаревшие настройки `index.knn.algo_param.*` удалены.
4. **Performance Analyzer RCA agent удален** — переходите на Telemetry Plugin.
5. **Новый PGP-ключ подписи артефактов** для версий 3.x (ключ для 2.x зарезервирован за старыми релизами) — обновите процедуру верификации пакетов.
6. На управляемых платформах (Amazon OpenSearch Service) обновление выполняется через Blue/Green deployment с нулевым простоем поиска и записи.

### Развертывание и экосистема

* **Kubernetes**: официальный Helm-чарт — [Развертывание в Kubernetes (Helm)](./opensearch_helm_deployment.md); Kubernetes Operator 3.0 (январь 2026) добавил quorum-safe rolling restarts, multi-namespace поддержку и hot-reload TLS-сертификатов.
* **Выделенные серверы**: автоматизация через Ansible — [Развертывание с помощью Ansible](./opensearch_ansible_deployment.md).
* **Отказоустойчивость API**: схема Floating VIP на базе Keepalived — [Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md).
* **Управляемые сервисы**: Amazon OpenSearch Service, Aiven, Instaclustr; сторонние enterprise-дистрибутивы с LTS-поддержкой (например, BDB OpenSearch Enterprise).
* **Ingestion**: Data Prepper как OTel-native шлюз приема телеметрии; прямое pull-based чтение из Kafka (экспериментальное).

---
## См. также

*   **[OpenSearch: Администрирование](./opensearch_administration.md)** — безопасность, шарды, тюнинг.
*   **[OpenSearch Dashboards](./opensearch_dashboards.md)** — визуализация и работа с данными.
*   **[ISM: жизненный цикл индексов](./opensearch_ism_lifecycle.md)** — политики хранения.
*   **[Search Pipelines](./opensearch_search_pipelines.md)** — request/response processors для гибридного поиска.
*   **[OpenSearch: Траблшутинг индексации](./opensearch_troubleshooting_indexing.md)** — диагностика проблем индексации и сегментов.
*   **[OpenSearch: Capacity Planning](./opensearch_capacity_planning.md)** — проектирование кластера и расчет мощностей.
*   **[ELK стек: Обзор](../elk_stack_overview.md)** — сравнение с Elastic Stack.
