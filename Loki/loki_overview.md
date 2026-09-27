# Grafana Loki — обзор системы агрегации логов

## Определения

**Grafana Loki** — это горизонтально масштабируемая, высокодоступная, многопользовательская (multi-tenant) система агрегации логов, вдохновленная принципами Prometheus. В отличие от традиционных систем (например, Elasticsearch), Loki не индексирует полный текст логов, а фокусируется на метаданных (метках). Сами логи сжимаются и хранятся в виде объектов.

**Loki 3.x (Актуальная версия):** Начиная с версии 3.0, в систему добавлена нативная поддержка Bloom-фильтров для ускорения поиска по неиндексированным данным и механизм структурированных метаданных. Это позволяет Loki конкурировать по скорости поиска с полнотекстовыми системами, сохраняя при этом низкую стоимость владения.

**Stream (Поток):** Уникальная комбинация лейблов (labels), которая определяет группу логов. Все логи с одинаковым набором лейблов принадлежат одному потоку. Индексация строится именно вокруг streams, что позволяет быстро фильтровать данные.

**Chunk (Чанк):** Сжатый блок логов, содержащий записи одного stream. Чанки формируются в памяти инжестера и затем записываются в объектное хранилище. Размер чанка обычно составляет несколько МБ. Bloom-фильтры строятся на уровне чанков.

**TSDB Index:** Формат индекса Loki 3.x, обеспечивающий высокую плотность хранения и быструю загрузку. Индекс хранит соответствие stream ID → список чанков и обновляется периодически компактором.

**Bloom Filter (Фильтр Блума):** Вероятностная структура данных, используемая для быстрого определения отсутствия искомой строки в чанке. Если фильтр сообщает, что строка отсутствует — это гарантировано верно. Если сообщает, что строка может присутствовать — требуется дополнительная проверка (false positive). В Loki 3.x Bloom-фильтры ускоряют grep-подобные запросы в 10–50 раз.

**Structured Metadata (Структурированные метаданные):** Механизм Loki 3.x, позволяющий прикреплять ключ-значение пары к строкам логов без создания новых лейблов. Метаданные не индексируются, но могут фильтроваться в LogQL, что решает проблему high cardinality.

**Write-Ahead Log (WAL):** Механизм надежности Loki и Alloy, при котором данные записываются на диск перед отправкой в бэкенд. При сбое записи в хранилище данные восстанавливаются из WAL, обеспечивая семантику at-least-once.

**Retention (Хранение):** Политика автоматического удаления старых логов. В Loki управляется через `retention_period` в `limits_config` и применяется фоновым компактором.

### Статус компонентов и агентов (август 2026)

| Агент | Статус | Дата EOL | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Grafana Alloy** | Текущий (Standard) | — | Основной агент для сбора логов, метрик и трассировок |
| **Grafana Agent (static mode)** | Устарело (EOL) | Ноябрь 2025 | Обязательная миграция на Alloy |
| **Promtail** | Устарело (EOL) | Весна 2026 | Обязательная миграция на Alloy |

**Подробнее о миграции:** [Grafana Alloy](../Grafana/grafana_alloy_overview.md)

---

## Основные концепции

### Ключевые особенности Loki 3.x

*   **Экономичное хранение:** Индексируются только метки (labels), что на порядок снижает объем индекса и требования к CPU/RAM по сравнению с полнотекстовой индексацией в Elasticsearch.
*   **Простота эксплуатации:** Loki спроектирован как легкая альтернатива ELK-стеку. Он проще в управлении, так как не требует сложной настройки схем индексов и позволяет использовать дешевые объектные хранилища (S3).
*   **Bloom-фильтры:** Технология ускорения запросов, позволяющая быстро определять отсутствие искомой строки в блоке данных без его чтения. Это ускоряет "grep-подобные" запросы в 10–50 раз. Фильтр строится в фоне компонентами Bloom Builder/Gateway.
*   **Структурированные метаданные (Structured Metadata):** Позволяют прикреплять контекст к строкам логов без создания новых лейблов. Предотвращает взрыв кардинальности (high cardinality), сохраняя возможность фильтрации и поиска.
*   **LogQL:** Язык запросов, максимально близкий к PromQL. Если вы знакомы с Prometheus, освоение Loki будет интуитивно понятным.
*   **Корреляция «из коробки»:** Благодаря идентичной модели метаданных с Prometheus и Tempo, переход между сигналами (метрики ↔ логи ↔ трейсы) в Grafana происходит бесшовно.

### Принципы работы и жизненный цикл лога

Понимание пути данных критично для диагностики проблем и оптимизации производительности.

1.  **Сбор:** Агент (Alloy/Promtail) читает логи из источника (файл, stdout, journald), присваивает статические лейблы и отправляет в Loki через HTTP API `/loki/api/v1/push`.
2.  **Прием (Distributor):** Проверяет лимиты tenant'а, валидирует запрос и распределяет по инжестерам на основе хеша меток. Если инжестер недоступен — возвращает 429 или буферизует на стороне агента.
3.  **Буферизация (Ingester):** Логи накапливаются в памяти в виде чанков. Параллельно данные записываются в WAL (Write-Ahead Log) на локальный диск. Это гарантирует durability при сбое питания.
4.  **Сброс (Flush):** По достижении порога размера или времени чанк сжимается (обычно gzip/snappy) и отправляется в объектное хранилище (S3/MinIO/filesystem).
5.  **Индексация:** Метаданные stream (лейблы) записываются в TSDB Index и также сохраняются в хранилище. В версии 3.x параллельно строятся Bloom-фильтры для чанков.
6.  **Компакция:** Фоновый процесс (Compactor) объединяет мелкие файлы индексов, удаляет дубликаты и применяет политики retention (удаляет чанки старше `retention_period`).
7.  **Запрос (Querier):** При выполнении LogQL запрос:
    *   Сначала фильтруется по индексу (лейблы в селекторе).
    *   Затем Query Frontend проверяет кэш и Bloom-фильтры.
    *   Querier читает чанки из памяти инжестеров (свежие данные) и из хранилища (история).
    *   Результаты объединяются и возвращаются клиенту.

### Режимы развертывания

| Режим | Описание | Назначение |
| :--- | :--- | :--- |
| **Single Binary** | Все компоненты запущены в одном процессе. | Тестирование, малые нагрузки (< 10 ГБ/день). |
| **Simple Scalable** | Разделение на цели: Read (чтение), Write (запись) и Backend (служебные задачи). | Рекомендуемый режим для Production (масштабируется до ТБ/день). |
| **Distributed** | Каждый микросервис (Ingester, Querier, Distributor и др.) запускается отдельно. | Экстремальные нагрузки, требующие тонкой настройки каждого компонента. |

### Архитектура компонентов

#### Общий поток данных

Loki использует упрощенный конвейер обработки данных:
1.  **Агенты (Clients):** Собирают логи (Alloy, Fluentd, Fluent Bit), присваивают лейблы и отправляют в Loki.
2.  **Loki Server:** Принимает потоки, индексирует только лейблы и сжимает логи в чанки (chunks).
3.  **Хранилище (Storage):** Сохраняет чанки и индексы в объектные хранилища (S3/GCS/MinIO) или локально.
4.  **Визуализация:** Запросы LogQL выполняются через Grafana или CLI (`logcli`).

#### Детальная архитектура микросервисов

Loki состоит из набора микросервисов, обеспечивающих конвейер обработки данных:

*   **Gateway:** Единая точка входа (Nginx/Ingress), распределяющая трафик между Read и Write таргетами.
*   **Distributor (Дистрибьютор):** Принимает входящие потоки, проверяет их на соответствие лимитам tenant'а и распределяет по инжестерам на основе хеша меток.
*   **Ingester (Инжестер):** Накапливает "чанки" логов в памяти, пишет в WAL для durability, индексирует их и записывает в объектное хранилище. Обеспечивает избыточность через фактор репликации (RF).
*   **Querier (Запросчик):** Выполняет поиск, запрашивая данные одновременно из памяти инжестеров (свежие данные, обычно за последние 1–2 часа) и из объектного хранилища (история).
*   **Query Frontend:** Кэширует результаты, разделяет тяжелые запросы на параллельные подзапросы и управляет очередями.
*   **Index Gateway:** Оптимизирует доступ к индексам TSDB, кэширует частые запросы к индексу.
*   **Bloom Builder / Gateway:** Компоненты для создания и обслуживания Bloom-фильтров (в версии 3.x). Построение происходит асинхронно после записи чанков.
*   **Compactor:** Объединяет файлы индексов, удаляет дубликаты и применяет политики удержания данных (retention).
*   **Ruler:** Выполняет прави-based алертинг на основе LogQL запросов (аналогично Prometheus Alerting Rules).

#### Хранение данных (Storage)

Loki использует двухуровневое хранение:

| Уровень | Что хранится | Формат | Где |
| :--- | :--- | :--- | :--- |
| **Индекс** | Stream ID → чанки, метки streams | TSDB Index (boltdb-shipper) | Объектное хранилище или локально |
| **Чанки** | Сжатые логи | snappy/gzip chunks | S3, GCS, Azure Blob, filesystem |

**Важно:** В Single Binary и Simple Scalable режимах для production рекомендуется использовать объектное хранилище (S3/MinIO), так как filesystem не обеспечивает репликацию и при удалении PVC данные теряются безвозвратно.

### Deep Dive: Object Storage Backends

#### Выбор хранилища

| Бэкенд | Рекомендация | Стоимость | HA | Сложность |
| :--- | :--- | :--- | :--- | :--- |
| **S3 (AWS)** | Production (cloud) | Pay-per-use | Встроенная | Низкая |
| **MinIO** | Production (on-prem) | Fixed cost | Нужен cluster | Средняя |
| **GCS (GCP)** | Production (cloud) | Pay-per-use | Встроенная | Низкая |
| **Azure Blob** | Production (cloud) | Pay-per-use | Встроенная | Низкая |
| **Filesystem** | Dev/test only | Fixed cost | Нет | Низкая |

#### S3 (AWS) — production recommended

```yaml
# loki.yaml
common:
  path_prefix: /loki
  storage:
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      bucketnames: loki-data-chunks
      access_key: <AKIAIOSFODNN7EXAMPLE>    # Или через env vars
      secret_key: <wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY>
      s3forcepathstyle: false
      insecure: false
      http_config:
        idle_conn_timeout: 90s
        response_header_timeout: 0s
        insecure_skip_verify: false
```

**IAM Policy для Loki (рекомендуется):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LokiS3Access",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::loki-data-chunks",
        "arn:aws:s3:::loki-data-chunks/*"
      ]
    }
  ]
}
```

**S3 Bucket Lifecycle Policy (для автоматической очистки):**

```json
{
  "Rules": [
    {
      "ID": "AbortIncompleteMultipartUpload",
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": {
        "DaysAfterInitiation": 7
      }
    },
    {
      "ID": "ExpireOldObjects",
      "Status": "Enabled",
      "Expiration": {
        "Days": 90
      },
      "Filter": {
        "Prefix": "chunks/"
      }
    }
  ]
}
```

#### MinIO (on-premise)

```yaml
# loki.yaml
common:
  storage:
    s3:
      endpoint: minio.logging.svc.cluster.local:9000
      bucketnames: loki-data
      access_key: minioadmin
      secret_key: minioadmin
      insecure: true  # Для internal MinIO без TLS
      s3forcepathstyle: true
```

**MinIO Docker Compose (development):**

```yaml
services:
  minio:
    image: minio/minio:latest
    container_name: minio
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin
    volumes:
      - minio-data:/data
    command: server /data --console-address ":9001"

volumes:
  minio-data:
```

#### GCS (Google Cloud)

```yaml
# loki.yaml
common:
  storage:
    gcs:
      bucket_name: loki-data-chunks
      service_account: /path/to/service-account.json
```

#### Конфигурация chunk/index storage (раздельная)

```yaml
# Раздельное хранилище для chunks и indexes
storage_config:
  aws:
    s3:
      endpoint: s3.amazonaws.com
      region: us-east-1
      bucketnames: loki-chunks
  aws_s3notification:
    bucketnames: loki-index

# TSDB Index
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index:
        prefix: index_
        period: 24h
```

#### Мониторинг storage

| Метрика | Описание |
| :--- | :--- |
| `loki_store_chunks_downloaded_total` | Количество скачанных чанков |
| `loki_store_chunks_upload_failed_total` | Ошибки загрузки чанков |
| `loki_compactor_bytes_processed_total` | Объем данных компактором |
| `loki_request_duration_seconds{operation="put"}` | Latency записи в S3 |

#### Типичные ошибки storage

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **"Access Denied"** | Неверные credentials или policy | Проверьте IAM policy, access_key/secret_key |
| **"NoSuchBucket"** | Bucket не существует | Создайте bucket, проверьте region |
| **"SlowDown"** | Превышен S3 rate limit | Увеличьте `max_idle_conns`, добавьте retry |
| **"Throttling"** | AWS throttling requests | Распределите нагрузку, используйте S3 Transfer Acceleration |
| **"Connection timeout"** | Network issues | Проверьте security groups, VPC endpoints |

### Кэширование и производительность

Для обеспечения высокой скорости запросов Loki использует многоуровневое кэширование:
1.  **Chunk Cache:** Кэширование самих блоков логов (обычно в Memcached или Redis). Значительно ускоряет повторные запросы к горячим данным.
2.  **Index Cache:** Кэширование фрагментов индекса TSDB.
3.  **Result Cache:** Кэширование ответов на частые запросы (в Query Frontend). Включается по умолчанию при наличии Redis/Memcached.
4.  **Bloom Cache:** Кэширование Bloom-фильтров в памяти/Bloom Gateway для ускорения поиска.

### Безопасность и мультиарендность

*   **Аутентификация:** Loki не содержит встроенной базы пользователей. Для Production используется заголовок `X-Scope-OrgID` (включается через `auth_enabled: true`), который передается через Gateway (Nginx/OAuth Proxy).
*   **Изоляция:** Каждый tenant (Tenant) видит только свои данные. Это позволяет использовать один кластер Loki для множества команд или клиентов.
*   **Лимиты:** Настраиваются индивидуально для каждого tenant'а (ingestion rate, max query series, retention, max query length).

---

## Практические сценарии

### Выбор способа установки

*   **Kubernetes (Helm):** Стандарт для Production. [Инструкция по установке в K8s](./loki_stack_setup/loki_installation.md).
*   **Docker Compose:** Идеально для локальной разработки и тестирования. [Пример настройки Docker Compose](./Docker_Compose/loki_docker_compose_setup.md).
*   **Linux (Binary/Systemd):** Для Bare-metal серверов или миграции с legacy-систем.

### Опасность высокой кардинальности (High Cardinality)

Основная причина отказа Loki — чрезмерное количество уникальных комбинаций меток. **Никогда** не используйте в качестве лейблов:
- Идентификаторы сессий или запросов (`session_id`, `trace_id`, `request_id`).
- IP-адреса пользователей или Email.
- Текст сообщений или уникальные хеши.
- Временные метки или счетчики с высокой дискретностью.

Для этих данных используйте **Structured Metadata** (Loki 3.x) или парсинг внутри LogQL запроса. Лейблы должны описывать только статический источник данных (cluster, service, env, container).

**Правило:** Количество уникальных значений (cardinality) для каждого лейбла должно оставаться стабильным во времени. Если значение изменяется с каждым запросом — это не лейбл.

### Валидация работоспособности

После установки выполните базовую проверку:

```bash
# Проверка готовности Loki
curl -s http://loki:3100/ready
# → ready

# Список всех активных меток в системе
curl -s http://loki:3100/loki/api/v1/labels | jq '.data'

# Проверка метрик инжестера
curl -s http://loki:3100/metrics | grep loki_ingester_streams_created_total
# → loki_ingester_streams_created_total 5

# Проверка статуса Bloom-фильтров (Loki 3.x)
curl -s http://loki:3100/loki/api/v1/bloom?query={job="my-app"}&start=now-1h&end=now
```

### Мониторинг здоровья кластера

Ключевые метрики Loki для мониторинга:

| Метрика | Описание | Критическое значение |
| :--- | :--- | :--- |
| `loki_ingester_streams_created_total` | Количество активных streams | Резкий рост может указывать на взрыв cardinality |
| `loki_ingester_memory_chunks` | Чанки в памяти инжестера | Рост → возможна нехватка RAM |
| `loki_request_duration_seconds` | Длительность запросов | P99 > 10s → требуется оптимизация |
| `loki_distributor_sent_bytes_total` | Объем принятых данных | Для планирования емкости |
| `loki_compactor_retention_dry_runs_total` | Запуски retention в dry-run | Должен совпадать с реальными удалениями |
| `loki_querier_queries_total` | Количество запросов | Рост без увеличения нагрузки → возможен abusive querying |

### Безопасность эксплуатации

1. **Аутентификация:** Всегда включайте `auth_enabled: true` дляProduction. Используйте Nginx/Ingress с OAuth Proxy для передачи заголовка `X-Scope-OrgID`.
2. **Сетевая изоляция:** Loki не должен быть доступен напрямую из интернета. Размещайте его в отдельном namespace/сегменте сети.
3. **Resource Limits:** Устанавливайте лимиты памяти для Loki, особенно для Querier (тяжелые запросы могут потреблять много RAM).
4. **Rate Limiting:** Настройте `ingestion_rate_mb` и `max_query_series` для защиты от abusive usage.
5. **Audit:** Логируйте все запросы к Loki API через Gateway (Nginx access logs) для аудита.

### Язык запросов LogQL

**Пример структуры:**
`{app="api", env="prod"} |= "error" | json | duration > 500ms`

1.  **Селектор:** `{app="api", env="prod"}` — фильтрация по индексированным меткам.
2.  **Фильтр текста:** `|= "error"` — выбор строк, содержащих подстроку.
3.  **Парсер:** `| json` — преобразование строки в набор полей.
4.  **Фильтр полей:** `duration > 500ms` — логическое условие на основе извлеченных данных.
5.  **Агрегация:** `sum by (level) (rate({app="api"}[5m]))` — превращение логов в временной ряд.

> **Практическое руководство:** [Примеры LogQL запросов](./loki_stack_setup/logql_examples.md)

---

## Устранение неполадок

### Диагностика состояния

```bash
# Проверка готовности компонентов (health check)
curl http://loki:3100/ready

# Список всех активных меток в системе
curl http://loki:3100/loki/api/v1/labels

# Проверка статуса streams
curl -s http://loki:3100/loki/api/v1/status/buildinfo | jq

# Проверка метрик WAL и чанков
curl -s http://loki:3100/metrics | grep -E "loki_ingester|loki_wal"
```

### Типичные ошибки

| Ошибка | Возможная причина | Решение |
| :--- | :--- | :--- |
| **"Entry out of order"** | Данные для одного стрима пришли с меткой времени раньше, чем уже записанные. Часто при пересылке старых логов или при отсутствии уникального идентификатора инстанса в лейблах. | Обеспечьте уникальность лейблов для каждого инстанса (например, добавьте `pod` или `instance`). Настройте `reject_old_samples: true` и `reject_old_samples_max_age`. |
| **"Limit exceeded: ingestion rate"** | Превышена скорость записи (`ingestion_rate_mb`). | Увеличьте лимиты в `limits_config` или масштабируйте количество инжестеров. Проверьте, нет ли burst-нагрузки от конкретного приложения. |
| **"Query timeout"** | Запрос выполняется слишком долго. | Оптимизируйте LogQL (сначала фильтры по меткам, потом парсинг), увеличьте `query_timeout` или добавьте Querier. Проверьте `max_query_series`. |
| **429 Too Many Requests** | Превышен лимит скорости записи. | Увеличьте `ingestion_burst_size_mb` для кратковременных пиков. При старом превышении — настройте сэмплирование на стороне агента. |
| **High Ingestion Latency** | Недостаточно реплик Write или медленное S3. | Увеличьте количество реплик `write`, проверьте сетевую задержку до S3 и лимиты CPU инжестеров. |
| **"Bloom filter missing"** | Bloom-фильтры не успели построиться. | Построение происходит с задержкой после записи данных. Настройте `bloom_build_config` (период, размер чанка). Для просроченных данных фильтры строятся retroactively. |
| **Логи не появляются в Loki** | Проблемы с сетью, неверные labels, отброс старых сэмплов. | Проверьте endpoint, метрики агента, `reject_old_samples_max_age`. Убедитесь, что timestamp в логах корректен. |
| **Ошибка 401 Unauthorized** | Включен `auth_enabled`, но отсутствует заголовок `X-Scope-OrgID`. | Добавьте заголовок в настройки агента (Alloy) и в Grafana Data Source. |
| **Высокое потребление RAM** | Отсутствуют лимиты, слишком большой `max_query_series` или взрыв cardinality. | Установите `deploy.resources.limits.memory`. Уменьшите `max_query_series`. Проверьте уникальные комбинации лейблов. |

### Диагностические команды

```bash
# Проверка статуса всех компонентов (Kubernetes)
kubectl get pods -n logging -l app.kubernetes.io/name=loki

# Проверка логов записи (Distributor/Ingester)
kubectl logs -n logging -l app.kubernetes.io/component=write -f

# Проверка метрик (если включен ServiceMonitor)
kubectl get servicemonitor -n logging

# Статус индекса через API
curl -G -H "X-Scope-OrgID: fake" http://localhost:3100/loki/api/v1/status/buildinfo

# Проверка текущих лимитов
curl -s http://localhost:3100/loki/api/v1/limits | jq
```

---

## Дополнительная информация

### Инструменты экосистемы

*   **Logcli:** CLI-утилита для отладки запросов и управления кластером из терминала.
*   **Loki Canary:** Инструмент для мониторинга потерь данных и задержек записи.
*   **Grafana Alloy:** Современный агент, заменяющий Promtail. [Настройка Alloy](./loki_stack_setup/alloy_installation.md).

### Лучшие практики

1.  **Лейблы:** Используйте статические, низкокардинальные лейблы (cluster, service, env, container). Никогда не используйте идентификаторы запросов, IP-адреса пользователей или временные метки как лейблы.
2.  **Structured Metadata:** Для высококардинальных данных (trace_id, user_id, session_id) используйте structured metadata (Loki 3.x) вместо лейблов.
3.  **Сэмплирование:** Для высоконагруженных систем применяйте head-based или adaptive сэмплирование на стороне агента для INFO/DEBUG логов.
4.  **Retention:** Настраивайте `retention_period` согласно политике хранения. Для production: 7–30 дней для оперативных логов, 90+ дней для аудита.
5.  **Мониторинг:** Следите за метриками `loki_ingester_memory_chunks`, `loki_request_duration_seconds`, `loki_distributor_sent_bytes_total`.
6.  **Объектное хранилище:** Для production всегда используйте S3/MinIO, а не filesystem. Файловая система не обеспечивает репликацию и при сбое диска данные теряются.
7.  **Аутентификация:** Всегда включайте `auth_enabled: true` и передавайте `X-Scope-OrgID` через Gateway.
8.  **Валидация:** После каждого изменения конфигурации проверяйте `/ready` и выполните тестовый LogQL запрос.

### Ограничения и edge cases

1.  **Bloom-фильтры:** Имеют вероятность false positive (обычно < 1%). Для критичных сценариев, где требуется 100% точность, используйте фильтры как предварительный этап, а не единственный механизм.
2.  **Structured Metadata:** В текущей версии не поддерживается индексация structured metadata (только фильтрация). Для частых фильтров по высококардинальным полям рассмотрите использование отдельного stream с фильтрацией на уровне агента.
3.  **Max Query Length:** Запросы по слишком широкому временному диапазону (например, несколько лет) могут приводить к таймаутам. Ограничьте `max_query_length` в `limits_config`.
4.  **WAL Recovery:** При восстановлении из WAL после сбоя доставка логов может быть дублирована (at-least-once семантика). Убедитесь, что downstream системы (например, Grafana) обрабатывают дубликаты корректно.
5.  **Filesystem storage:** В Single Binary/Simple Scalable режимах filesystem не поддерживает горизонтальное масштабирование. Для > 100 ГБ/день используйте S3.

### Ссылки

*   **[Установка Grafana для Loki](./loki_stack_setup/grafana_installation.md)** — настройка визуализации и алертинга.
*   **[Интеграция Fluent Bit](./fluentbit_integration.md)** — использование альтернативных агентов сбора.
*   **[Официальная документация Grafana Loki](https://grafana.com/docs/loki/latest/)** — подробный справочник параметров конфигурации.
