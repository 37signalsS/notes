# Обзор Elastic Stack (ELK)

> Эта заметка является авторитетным источником по архитектуре и компонентам Elastic Stack. Она служит точкой входа для понимания того, как современные версии стека (8.x и 9.x) эволюционировали от классического ELK к платформе **Search AI** и **OTel-native** наблюдаемости.

## Определения

* **Elastic Stack (ранее ELK)** — комплексное решение для сбора, поиска, анализа и визуализации данных (логов, метрик, трассировок) в реальном времени. Включает Elasticsearch, Kibana, Logstash, Beats и Elastic Agent.
* **Search AI Platform** — современное позиционирование стека в версиях 9.x, акцентирующее внимание на использовании ИИ, векторного поиска и архитектуры **Search AI Lake**.
* **Search AI Lake** — облачная архитектура (Serverless), разделяющая хранение (в S3/GCS) и вычисления, обеспечивая практически неограниченное масштабирование и работу с данными без управления индексами и шардами.
* **ES|QL (Elasticsearch Query Language)** — конвейерный язык запросов (Piped Query Language), ставший основным интерфейсом анализа данных в Kibana. Использует поколоночный движок выполнения для высокой скорости обработки.
* **OpenTelemetry (OTel) Native** — стратегия Elastic по полной поддержке протокола OTLP напрямую в Elasticsearch, что позволяет отказаться от проприетарных агентов в пользу открытых стандартов.
* **Fleet** — система централизованного управления парком агентов (Elastic Agent) через интерфейс Kibana. Обеспечивает дистрибуцию политик, обновлений и интеграций на тысячи хостов.
* **Elastic Agent** — универсальный агент, собирающий логи, метрики, трассировки и обеспечивающий защиту конечных точек (EDR). Управляется через Fleet или работает в standalone-режиме.
* **ECS (Elastic Common Schema)** — унифицированная схема данных, обеспечивающая единообразие полей (например, `source.ip`, `user.name`, `event.outcome`) во всех компонентах стека. В 9.x ECS объединена с конвенциями OTel.
* **Integrations** — готовые пакеты настроек (inparsers, dashboards, alerting rules) для 300+ систем и сервисов, устанавливаемые через Fleet или Kibana UI.
* **Observability (Наблюдаемость)** — объединение логов, метрик, трассировок и профилей для понимания состояния распределенных систем. В Elastic Stack — одно из трех ключевых направлений (наряду с Security и Search AI).
* **APM (Application Performance Monitoring)** — подсистема для сбора трассировок, метрик приложений и ошибок. Включает APM Server, работающий с Elastic Agent или standalone.
* **SIEM (Security Information and Event Management)** — подсистема безопасности для корреляции событий, обнаружения угроз и расследования инцидентов. Реализована через Detection Rules, Elastic Security и timelines.
* **CNAPP (Cloud-Native Application Protection Platform)** — комплексная платформа защиты облачных приложений, объединяя CSPM, CWPP и защиту от уязвимостей контейнеров. Реализована в Elastic Security.
* **ILM (Index Lifecycle Management)** — автоматизация жизненного цикла индексов: горячее → тёплое → холодное хранение → удаление. Критична для управления большими объемами данных.

## Основные концепции

### Компоненты и методы доставки данных

Архитектура 2026 года выделяет два основных пути поступления данных:

#### 1. Современный подход (OTel & Elastic Agent)
*   **OpenTelemetry SDK/Collector**: Рекомендуемый метод для новых приложений. Данные отправляются напрямую в Elasticsearch через нативный эндпоинт OTLP.
*   **Elastic Agent**: Универсальный агент, управляемый через **Fleet**. Заменяет семейство Beats, обеспечивая сбор логов, метрик и защиту конечных точек (EDR) в рамках одной политики.
*   **Integrations**: Готовые наборы настроек для 300+ систем (Nginx, K8s, AWS), устанавливаемые через Kibana UI.

#### 2. Классический и инфраструктурный подход
*   **[Beats](./filebeat_overview.md)**: Легковесные агенты (Filebeat, Metricbeat) для специфических задач или устаревших систем.
*   **[Logstash](./Logstash/logstash_overview.md)**: Мощный ETL-движок для сложной трансформации данных из источников, не поддерживающих OTel/Agent (например, Netflow, JDBC).

#### 3. Брокеры сообщений в конвейере

Для защиты от потери данных при всплесках нагрузки между агентами и Elasticsearch рекомендуется промежуточный буфер:

*   **Kafka** — наиболее распространенный выбор для высоконагруженных сред. Обеспечивает持久ное хранение, репликацию и горизонтальное масштабирование. Подробнее: [Kafka для мониторинга](../Kafka/kafka_for_monitoring.md).
*   **Redis** — подходит для небольших объемов, где нужна простота вместо масштабируемости.
*   **Vector** — легковесная альтернатива Logstash с поддержкой OTLP. Подробнее: [Vector: Обзор](../Vector/vector_overview.md).

### Ядро и аналитика

*   **[Elasticsearch](./Elasticsearch/elasticsearch_overview.md)**: Сердце стека. В 9.x поддерживает квантование векторов (**DiskBBQ**), позволяя хранить миллиарды векторов с минимальным использованием RAM.
*   **[Kibana](./Kibana/kibana_overview.md)**: Окно в данные. Интегрирует **AI Assistant** для помощи в написании запросов и расследовании инцидентов.
*   **ES|QL**: Позволяет выполнять сложные преобразования (Join, Stats, Filter) в одном запросе, значительно превосходя старый KQL по возможностям аналитики.

### Архитектурные решения (Solutions)

Elastic Stack структурирован по трем направлениям:
1.  **Observability**: Логи, метрики и OTel-трассировки. Основной упор на корреляцию сигналов и автоматический поиск аномалий (ML).
2.  **Security**: SIEM, защита облачных сред (CNAPP) и конечных точек. Использует общую схему данных **ECS (Elastic Common Schema)**, которая теперь объединена с конвенциями OTel.
3.  **Search AI**: Платформа для создания RAG-приложений. Включает встроенные Inference API для работы с моделями (OpenAI, Gemini, Jina).

### Версии и жизненный цикл

Elastic Stack развивается по двум основным веткам:

| Характеристика | 8.x (LTS) | 9.x (Current) |
| :--- | :--- | :--- |
| **Актуальная версия** | 8.19 (август 2026) | 9.5 (август 2026) |
| **EOL (End of Life)** | ~2028 | ~2029+ |
| **Тип входов Beats** | `log` + `filestream` | Только `filestream` |
| **Безопасность** | Опционально (вкл по умолчанию с 8.0) | Обязательно, TLS + token-based auth |
| **OTLP** | Через OTel Collector | Нативный OTLP endpoint |
| **ES|QL** | Доступен (GA с 8.14) | Основной язык запросов |
| **Elasticsearch Query DSL** | Полная поддержка | Полная поддержка (совместимость) |

**Рекомендация:** Для новых развертываний используйте 9.x. Миграция с 8.x на 9.x обычно обратно совместима, но требует проверки конфигураций Beats (тип `log` удалён в пользу `filestream`).

### Лицензирование

| Лицензия | Компоненты | Ограничения |
| :--- | :--- | :--- |
| **SSPL (Server Side Public License)** | Elasticsearch, Kibana (8.x+) | Запрет конкурентного SaaS без выкладывания кода |
| **ELv2 (Elastic License v2)** | Многие функции 9.x | Запрет предоставления Managed ES без соглашения |
| **Apache 2.0** | Logstash, Beats, APM Server | Полностью открытый код |
| **AGPL** | OpenSearch (форк) | Альтернатива для полного Open Source |

> **Важно:** SSPL и ELv2 — не лицензии Open Source по OSI. Для организаций с жесткими требованиями к лицензированию рассмотрите OpenSearch как альтернативу (см. [OpenSearch: Обзор](./OpenSearch/opensearch_overview.md)).

### Варианты развертывания

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Self-Managed** | Установка на собственные серверы/VM | Полный контроль, нарушение compliance, air-gapped среды |
| **[Docker Compose](./Tutorials/practical_setup_with_docker.md)** | Локальная среда разработки и прототипирования | Dev-окружение, обучение, быстрый старт |
| **[ECK (Elastic Cloud on Kubernetes)](./elastic_cloud_on_k8s.md)** | Оператор для Kubernetes | Продакшн в Kubernetes, автоматизация TLS и обновлений |
| **Elastic Cloud** | Управляемый SaaS от Elastic | Минимальные операционные затраты, быстрое масштабирование |
| **[Serverless (Search AI Lake)](#миграция-на-serverless-search-ai-lake)** | Pay-per-use, без управления инфраструктурой | Нестабильная нагрузка, fast experimentation |

### Безопасность и аутентификация

С версии 8.0 все функции безопасности включены по умолчанию:

*   **TLS**: Шифрование всех соединений (inter-node, client-to-node). Сертификаты автоматически генерируются при первом запуске.
*   **Аутентификация**: API Keys, JWT, PKI, SAML/OIDC для SSO.
*   **Авторизация**: RBAC (Role-Based Access Control) с предустановленными и кастомными ролями.
*   **Auditing**: Логирование всех запросов к API и изменения данных.
*   **Filebeat Keystore**: Хранение секретов в зашифрованном виде (не в YAML). Подробнее: [Filebeat: Обзор](./filebeat_overview.md#безопасность-и-хранение-секретов).

## Практические сценарии

### 1. Построение конвейера высокой нагрузки

Для защиты от потери данных при всплесках (bursts) используется брокер сообщений:
`Elastic Agent (OTLP) -> Kafka -> Vector (или Logstash) -> Elasticsearch`.

```yaml
# Пример: Vector как Kafka consumer с записью в Elasticsearch
sources:
  kafka_input:
    type: kafka
    bootstrap_servers: "kafka1:9092,kafka2:9092"
    topics: ["logs-*"]
    group_id: "vector-consumers"

sinks:
  elasticsearch:
    type: elasticsearch
    inputs: ["kafka_input"]
    endpoints: ["https://es-cluster:9200"]
    api_key: "${ES_API_KEY}"
    batch:
      max_bytes: 10485760  # 10 MiB
      timeout_secs: 5
```

### 2. Миграция на Serverless (Search AI Lake)

Переход на Elastic Cloud Serverless позволяет:
*   Отказаться от планирования размера дисков и JVM Heap.
*   Использовать **Searchable Snapshots** как основной способ работы с данными ("холодные" данные ищутся почти так же быстро, как "горячие").
*   Платить только за фактически выполненные запросы и объем хранения в облаке.

**Порядок действий:**
1.  Экспортируйте данные из self-managed кластера через Snapshot API.
2.  Создайте Serverless-проект в Elastic Cloud.
3.  Импортируйте данные через Backup & Restore API.
4.  Настройте Agent Policies в Fleet для отправки в новый endpoint.
5.  Валидируйте целостность данных через `GET _count` и Kibana Discover.

### 3. Использование ES|QL для расследований

Пример запроса, объединяющего данные логов и информацию о пользователях в момент запроса:
```sql
FROM logs-*
| WHERE event.dataset == "auth" AND status == "failure"
| LOOKUP users_metadata ON user.id
| STATS count() BY country, department
```

### 4. Настройка ILM для автоматической ротации данных

```json
PUT _ilm/policy/logs-policy
{
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
        "min_age": "7d",
        "actions": {
          "shrink": { "number_of_shards": 1 },
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "cold": {
        "min_age": "30d",
        "actions": {
          "searchable_snapshot": {
            "snapshot_repository": "found-snapshots"
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": { "delete": {} }
      }
    }
  }
}
```

### 5. Централизованное управление через Fleet

```yaml
# Пример: политика Fleet для сбора логов с Kubernetes
agent.policies:
  - name: "k8s-logs"
    namespace: "production"
    monitoring_enabled: ["logs", "metrics"]
    package_policies:
      - name: "kubernetes"
        package: "kubernetes"
        inputs:
          - type: container_logs
            enabled: true
            vars:
              - name: paths
                value: ["/var/log/containers/*.log"]
          - type: kubernetes_metrics
            enabled: true
```

## Мониторинг и наблюдаемость за Elastic Stack

### Встроенные инструменты

*   **Stack Monitoring**: Встроенный дашборд в Kibana для мониторинга состояния всех компонентов (ES, Kibana, Logstash, Beats). Включает метрики кластера, индексов, запросов и очередей.
*   **Stats API**: `GET _stats`, `GET _nodes/stats` — детальные метрики по узлам и индексам.
*   **Cluster Health API**: `GET _cluster/health` — статус кластера (green/yellow/red), количество узлов, активные шарды.

### Сбор телеметрии Elastic Stack

Для мониторинга самого стека используйте Prometheus или OTel Collector:

```yaml
# Пример: экспорция метрик ES в Prometheus через Exporter
# https://github.com/prometheus-community/elasticsearch_exporter
- job_name: "elasticsearch"
  static_configs:
    - targets: ["es-exporter:9114"]
  metrics_path: /metrics
```

### Настройка алертинга

Kibana поддерживает алертинг по метрикам кластера:

1.  **Index Threshold**: Срабатывание при количестве документов в индексе выше порога.
2.  **Cluster Health**: Уведомление при переходе в статус yellow/red.
3.  **Elasticsearch Query**: Произвольный запрос с пороговым значением.

```json
// Пример: правила алертинга через API
PUT _alerting/rule/cluster-health
{
  "name": "Cluster Red Alert",
  "rule_type_id": ".es-query",
  "schedule": { "interval": "1m" },
  "params": {
    "searchType": "esQuery",
    "esQuery": "{\"bool\":{\"must\":[{\"match_phrase\":{\"cluster.status\":\"red\"}}]}}",
    "index": [".monitoring-es-*"],
    "timeField": "@timestamp",
    "threshold": [1],
    "thresholdComparator": ">="
  },
  "actions": [{
    "actionTypeId": ".email",
    "params": { "to": ["ops@example.com"] }
  }]
}
```

## Резервное копирование и восстановление

### Snapshot API

Elasticsearch поддерживает снимки (snapshots) для бэкапа данных:

```bash
# 1. Регистрация хранилища снимков (S3)
curl -X PUT "https://es:9200/_snapshot/s3_backup" -H 'Content-Type: application/json' -d'
{
  "type": "s3",
  "settings": {
    "bucket": "my-es-backups",
    "region": "eu-west-1"
  }
}'

# 2. Создание снимка
curl -X PUT "https://es:9200/_snapshot/s3_backup/snapshot_$(date +%Y%m%d)?wait_for_completion=true"

# 3. Восстановление из снимка
curl -X POST "https://es:9200/_snapshot/s3_backup/snapshot_20260823/_restore"
```

### Рекомендации

*   **Частота**: Ежедневные автоматические снимки через Curator или ILM.
*   **Хранение**: Off-site репликация (S3 cross-region, GCS multi-region).
*   **Тестирование**: Регулярно выполняйте test-restore в изолированной среде.
*   **Кластерные метаданные**: Включите в снимок политики ILM, настройки и шаблоны индексов.

## Устранение неполадок

### Типичные проблемы

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Кластер в статусе **Yellow** | Replica shards не назначены (один узел) | Добавьте узел или уменьшите `number_of_replicas` |
| Кластер в статусе **Red** | Primary shards не назначены | Проверьте логи узлов, возможно повреждение данных |
| **High Disk Watermark** (read-only) | Диск заполнен на 85%+ | Расширьте диск, удалите старые индексы, сбросьте блокировку |
| Медленные запросы | Неоптимальный маппинг или large aggregations | Используйте ES|QL, добавьте `filter` контекст, проверьте `profile` API |
| **Bulk Rejection** (429) | Перегрузка кластера записями | Увеличьте `thread_pool.write.queue_size` или замедлите запись |
| Kibana не подключается | TLS сертификат или аутентификация | Проверьте `elasticsearch.hosts` и сертификаты в `kibana.yml` |

### Диагностические команды

```bash
# Состояние кластера
curl -k -u elastic:$PASS "https://localhost:9200/_cluster/health?pretty"

# Статус индексов
curl -k -u elastic:$PASS "https://localhost:9200/_cat/indices?v&s=store.size:desc"

# Задачи в очереди
curl -k -u elastic:$PASS "https://localhost:9200/_tasks?pretty"

# Hot threads (-diagnosis зависаний)
curl -k -u elastic:$PASS "https://localhost:9200/_nodes/hot_threads"

# Slow log (медленные запросы)
curl -k -u elastic:$PASS "https://localhost:9200/_settings?pretty&filter_path=**.index.search.slowlog"
```

## Граничные случаи и ограничения

### Совместимость версий

*   **Beats → Elasticsearch**: Агенты Beats 8.x совместимы с ES 8.x и 9.x. Агенты Beats 9.x совместимы только с ES 9.x.
*   **Logstash → Elasticsearch**: Плагин `elasticsearch` поддерживает обратную совместимость минорных версий.
*   **Kibana → Elasticsearch**: Kibana должна иметь ту же мажорную версию, что и Elasticsearch.

### Производительность

*   **Shard Size**: Оптимальный размер shard — 10–50 GiB. Слишком много мелких шардов снижает производительность кластера.
*   **Mapping Explosion**: Лимит на количество полей в индексе (по умолчанию 1000). Используйте `dynamic: strict` или `dynamic: runtime` для контроля.
*   **JVM Heap**: Рекомендуется 50% доступной RAM, но не более 31 GiB (для использования компрессии pointers).

### Управление памятью в Elasticsearch

```yaml
# Рекомендуемые настройки JVM (jvm.options)
-Xms16g  # Для узлов с 32 GiB RAM
-Xmx16g
# Включить gzip для полей типа text
-XX:+UseCompressedOops
```

## Ссылки и взаимосвязи

### Компоненты стека

*   **[Elasticsearch: Обзор](./Elasticsearch/elasticsearch_overview.md)** — архитектура кластера, роли узлов, шардинг.
*   **[Kibana: Обзор](./Kibana/kibana_overview.md)** — интерфейс управления, визуализация, алертинг.
*   **[Logstash: Обзор](./Logstash/logstash_overview.md)** — архитектура стадий, Keystore, Persistent Queues.
*   **[Filebeat: Обзор](./filebeat_overview.md)** — сбор файловых логов, filestream input, autodiscover.
*   **[Beats Family](./Elasticsearch/beats_family.md)** — Metricbeat, Heartbeat, Auditbeat, Packetbeat для сбора метрик, аудита и сетевого мониторинга.
*   **[Elastic Agent и Fleet](./Elasticsearch/elastic_agent_and_fleet.md)** — централизованное управление сбором данных через Fleet Server.

### Обработка и трансформация данных

*   **[Ingest Pipelines](./Elasticsearch/elasticsearch_ingest_pipelines.md)** — обработка документов перед индексацией: grok, dissect, geoip, enrich процессоры.
*   **[Grok и Dissect Patterns](./grok_dissect_patterns.md)** — коллекция рецептов для парсинга логов в Logstash и Ingest Pipelines.
*   **[Logstash: Конвейеры, фильтры и производительность](./Logstash/logstash_pipelines.md)** — архитектура pipelines, агрегация, DLQ, тюнинг.

### Индексация и хранение

*   **[Elasticsearch: Индексирование и маппинг](./Elasticsearch/elasticsearch_mapping_and_indexing.md)** — структуры данных, анализаторы, шаблоны.
*   **[Index Templates и Data Streams](./Elasticsearch/elasticsearch_index_templates.md)** — Composable Templates, Component Templates, Data Streams для time-series.
*   **[ILM и политики хранения](./Elasticsearch/elasticsearch_ilm_and_retention.md)** — автоматизация жизненного цикла: hot → warm → cold → delete.
*   **[Rollup и Transform](./Elasticsearch/elasticsearch_rollup_transform.md)** — агрегация исторических данных, pivot, latest views.
*   **[Capacity Planning](./Elasticsearch/elasticsearch_capacity_planning.md)** — расчет размера кластера, шардов, ресурсов.

### Производительность и оптимизация

*   **[Search Performance Tuning](./Elasticsearch/elasticsearch_search_tuning.md)** — кэширование, query profiling, routing, circuit breakers.
*   **[Траблшутинг индексации](./Elasticsearch/elasticsearch_troubleshooting_indexing.md)** — диагностика проблем индексации и сегментов.
*   **[Upgrades и миграция](./Elasticsearch/elasticsearch_upgrades.md)** — Rolling Upgrade, Blue-Green, version compatibility.

### Мониторинг и безопасность

*   **[Stack Monitoring](./Elasticsearch/elasticsearch_stack_monitoring.md)** — ключевые метрики ES, Logstash, Beats, Kibana и алертинг.
*   **[Alerting: Kibana Alerting и Watcher](./Elasticsearch/elasticsearch_alerting.md)** — типы правил, Connectors, Actions, Watcher.
*   **[Security Advanced](./Elasticsearch/elasticsearch_security_advanced.md)** — DLS, FLS, Audit Logging, SAML/OIDC, Kibana Spaces.
*   **[Network и Firewall](./elasticsearch_network_requirements.md)** — порты, протоколы, TLS, firewall rules.

### Отказоустойчивость

*   **[Cross-Cluster Replication и Search](./Elasticsearch/elasticsearch_ccr_ccs.md)** — CCR для DR, CCS для geo-distributed поиска.
*   **[Disaster Recovery Patterns](./Elasticsearch/elasticsearch_disaster_recovery.md)** — RPO/RTO, multi-site, snapshot strategies.

### Инфраструктура и развертывание

*   **[Docker Compose: Развертывание ELK](./Tutorials/practical_setup_with_docker.md)** — пошаговое руководство с TLS и безопасностью.
*   **[Мультинодовый кластер](./Tutorials/cluster_setup.md)** — настройка кластера из 3+ узлов.
*   **[ECK: Elastic Cloud on Kubernetes](./elastic_cloud_on_k8s.md)** — оператор для продакшн-развертывания в Kubernetes.

### OpenSearch

*   **[OpenSearch: Обзор](./OpenSearch/opensearch_overview.md)** — альтернатива на Apache 2.0 лицензии.
*   **[Search Pipelines (OpenSearch)](./OpenSearch/opensearch_search_pipelines.md)** — request/response processors для гибридного поиска.

### Смежные технологии

*   **[OpenSearch: Обзор](./OpenSearch/opensearch_overview.md)** — альтернатива на Apache 2.0 лицензии.
*   **[Kafka для мониторинга](../Kafka/kafka_for_monitoring.md)** — буферизация и декаплинг в конвейере логов.
*   **[Vector: Обзор](../Vector/vector_overview.md)** — легковесная альтернатива Logstash.
*   **[Сравнение: Elastic Stack vs OpenSearch vs Loki](./elk_stack_overview.md#сравнение-с-альтернативами)** — детальная таблица ниже.

### Сравнение с альтернативами

| Характеристика | Elastic Stack | [OpenSearch](./OpenSearch/opensearch_overview.md) | [Loki](../../Loki/loki_overview.md) |
| :--- | :--- | :--- | :--- |
| **Лицензия** | ELv2 / SSPL | Apache 2.0 (Open Source) | AGPL |
| **Аналитика** | ES|QL (Поколоночная) | PPL / SQL | LogQL (Построчная) |
| **ИИ / Векторы** | Лидер (DiskBBQ, GPU) | Базовая поддержка (k-NN) | Нет |
| **Управление** | Fleet (Централизованно) | Скрипты / Terraform | Grafana-centric |
| **Хранение** | Локальное + S3 (Search AI Lake) | Локальное + S3 | Только object storage (S3) |
| **OTel** | Нативный OTLP (9.x) | Через Collector | Через Alloy/OTel Collector |

### Полезные ссылки

*   **[Настройка кластера Elasticsearch 8](../ELK_Stack/Tutorials/cluster_setup.md)** — развертывание в self-managed среде.
*   **[Elasticsearch: Индексирование и маппинг](./Elasticsearch/elasticsearch_mapping_and_indexing.md)** — детально о структурах данных.
*   **[Отказоустойчивость с Kafka](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** — архитектура для больших данных.
*   **[Официальная документация Elastic](https://www.elastic.co/guide/index.html)**.

> **Важно**: При планировании обновлений до версии 9.x учитывайте, что поддержка старых типов инпутов в Beats (например, `log`) прекращена в пользу `filestream`. См. **[Обзор Filebeat](./filebeat_overview.md)**.
