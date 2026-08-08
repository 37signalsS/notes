# Vector: Обзор

**Vector** — высокопроизводительный, открытый (Mozilla Public License 2.0) конвейер для сбора, обработки и отправки логов, метрик и событий (traces). Написан на Rust, что обеспечивает высокую производительность, безопасность памяти и минимальное потребление ресурсов.

**Режимы работы:**
*   **Agent** — легковесный агент на каждом хосте (альтернатива Fluent Bit, Grafana Alloy).
*   **Aggregator** — централизованный обработчик потоков данных (альтернатива Logstash, Fluentd).

---

## Основные концепции

### Архитектура

Vector построен на базе направленного ациклического графа (DAG) компонентов:

1.  **Sources (Источники)** — определяют точки входа данных:
    *   **Файлы и система:** `/var/log/*.log`, `journald`, `windows_event_log` (native API), `exec`, `host_metrics`, `docker_logs`, `kubernetes_logs`.
    *   **Сетевые протоколы:** Syslog, HTTP (server/client), TCP, UDP, `websocket`, `dnstap`.
    *   **Очереди сообщений:** Kafka, NATS, AWS SQS, GCP Pub/Sub, Pulsar, Redis, AMQP.
    *   **Контейнеры и облака:** Docker, Kubernetes, AWS S3, AWS Kinesis Firehose, Splunk HEC.
    *   **Метрики:** Prometheus endpoints (`prometheus_scrape`), `prometheus_remote_write`, StatsD, Datadog Agent.
    *   **Собственные метаданные:** `internal_logs`, `internal_metrics` — наблюдение за самим Vector.
    *   **Открытая телеметрия:** `opentelemetry` — приём данных по OTLP (gRPC/HTTP), включая traces.

2.  **Transforms (Преобразования)** — логика обработки:
    *   **`remap`** — основной компонент для работы с [VRL](./vrl_language.md).
    *   **`filter`** — отсеивание событий по условиям.
    *   **`route`** — условная маршрутизация.
    *   **`aggregate`** — агрегация (например, суммирование метрик).
    *   **`enrichment_tables`** — обогащение данными из in-memory таблиц (обновляются без перезапуска, `reload_behavior` для сохранения состояния между перезагрузками).
    *   **Прочие:** `delay` (новый, v0.56+), `dedupe`, `sample`, `throttle`, `reduce`, `log_to_metric`, `metric_to_log`, `tag_cardinality_limit`, `aws_ec2_metadata`.

3.  **Sinks (Приёмники)** — точки выхода данных:
    *   **Хранилища:** OpenSearch, Elasticsearch, [Loki](../Loki/loki_overview.md), ClickHouse (поддержка Native Arrow/`arrow_stream`), GreptimeDB, Databend.
    *   **Объектные хранилища:** AWS S3 (Native Parquet, из коробки с v0.56), GCS, Azure Blob.
    *   **Мониторинг:** Prometheus remote write, Datadog, Azure Monitor — через `azure_logs_ingestion` (новый sink по Azure Monitor Logs Ingestion API; прежний `azure_monitor_logs` устарел, поддержка старого Data Collector API завершается в сентябре 2026).
    *   **Очереди:** Kafka, NATS, AWS Kinesis, Databricks Zerobus (v0.56+).
    *   **Vector-to-Vector:** sink `vector` с компрессией `gzip`/`zstd` (zstd — v0.56+).

### Внутренний API (gRPC, v0.55+)

Начиная с v0.55.0 внутренний API Vector полностью перешел с GraphQL на gRPC. Это касается и инструментов мониторинга (`vector top`, `vector tap`), что повысило стабильность при экстремальных нагрузках.

*   **Включение:** секция `api.enabled = true` в конфигурации.
*   **Адрес:** `127.0.0.1:8686` по умолчанию; единый порт для gRPC (tonic/HTTP2) и HTTP (`/health`), поддерживается gRPC reflection (grpcurl) и HTTP/1.1 для простых запросов.
*   **Безопасность:** аутентификация отсутствует — рекомендуется включать только в изолированных средах. `/health` возвращает `{"ok":true}` и используется для Kubernetes liveness/readiness проб.

### Ключевые характеристики

| Характеристика | Описание |
| :--- | :--- |
| **Производительность** | В 10 раз быстрее Logstash; поддержка Apache Arrow и Parquet для бинарной передачи. |
| **Безопасность памяти** | Гарантии Rust исключают утечки памяти и ошибки сегментации (Segfaults). |
| **Гарантия доставки** | At-least-once delivery с персистентным дисковым буфером. |
| **Наблюдаемость** | Встроенные метрики латентности компонентов, состояния буферов, capacity planning (`source_buffer_*`, `transform_buffer_*`, `component_latency_seconds`). |
| **Конфигурация** | YAML, JSON, TOML (TOML рекомендуется как стандарт). |

### Режимы развёртывания

#### Режим агента (Agent Mode)
Разворачивается как DaemonSet (Kubernetes) или системный сервис (systemd). Основная задача — сбор данных "у источника", первичный парсинг и локальная буферизация.

#### Режим агрегатора (Aggregator Mode)
Централизованный кластер. Используется для сложной трансформации, дедупликации, сэмплирования и обогащения данных перед отправкой в финальное хранилище.

### Сравнение с аналогами (Актуально на 2026 год)

| Инструмент | Vector | Grafana Alloy | Fluent Bit | Logstash |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Rust | Go | C | Java |
| **Ресурсы** | Низкие | Средние | Очень низкие | Высокие |
| **Сложная логика** | VRL (Очень мощный) | River (Скриптинг) | Ограниченно (Lua) | DSL (Ruby-like) |
| **Экосистема** | Высокая | Очень высокая (OTel) | Высокая | Максимальная |
| **Роль 2026** | **High-Load Aggregator** | **Standard OTel Agent** | **Edge Shipper** | **Legacy / Deep ELK** |

### Инструментарий и диагностика

Vector предоставляет мощный CLI для отладки и мониторинга:
*   **`vector top`** — визуализация топологии и нагрузки на компоненты в реальном времени (подключается к gRPC API, колонка `Events Out` корректна для компонентов с несколькими выходами).
*   **`vector tap`** — инспекция событий на любом этапе конвейера (аналог `tcpdump` для логов).
*   **`vector vrl`** — интерактивная REPL-среда для тестирования VRL-выражений.
*   **`vector validate`** — валидация конфигурации перед запуском (заменяет прежнюю команду `vector check`). Флаг `--no-environment` пропускает проверки окружения, `--deny-warnings` превращает предупреждения в ошибки.
*   **`vector graph`** — визуализация топологии в формате DOT (GraphViz).
*   **`vector test`** — запуск нативных unit-тестов конфигурации (секция `[[tests]]`, поддержка `expected_event_count`).

**Установка:** Vector компилируется в единый статический бинарник (зависимость только от `libc`; доступны musl-сборки без зависимостей). Рекомендуемый установщик: `curl --proto '=https' --tlsv1.2 -sSfL https://sh.vector.dev | bash`. Поддерживаются пакетные менеджеры (APT, RPM, Homebrew), Docker, Helm. Конфигурация по умолчанию: `/etc/vector/vector.yaml`.

### Интеграция с Kubernetes

Официальная поддержка через Helm-чарт включает три стратегии:
1.  **DaemonSet** — сбор логов с нод (`/var/log/pods/*`), обогащение метаданными K8s.
2.  **Deployment** — горизонтально масштабируемая агрегация (например, из Kafka).
3.  **StatefulSet** — для источников, требующих персистентного состояния или дисковых буферов.

### Мониторинг самого Vector

Vector наблюдает за собой через специальные sources:
*   **`internal_logs`** — логи самого Vector (уровень по умолчанию `info`, настраивается флагами `-v/-vv/-q/-qq` или переменной `VECTOR_LOG`). Доступны также через `stderr` (перехватываются systemd/K8s).
*   **`internal_metrics`** — метрики самого Vector, которые можно отправлять в Prometheus remote write, ClickHouse и другие sinks как обычные данные.

---

## Безопасность и стабильность

1.  **Интерполяция переменных окружения:** Начиная с v0.57, интерполяция `${VAR}` в конфигурационных файлах **отключена по умолчанию**. Для включения требуется флаг `--dangerously-allow-env-var-interpolation` или переменная `VECTOR_DANGEROUSLY_ALLOW_ENV_VAR_INTERPOLATION=true` (может раскрыть секреты в конфигурации). Прежние флаг `--disable-env-var-interpolation` и переменная `VECTOR_DISABLE_ENV_VAR_INTERPOLATION` удалены.
2.  **Ограничение шаблонов маршрутизации (Template Confinement, v0.57):** Sinks, принимающие `{{ field }}` в шаблонах маршрутизации (ключи объектов, пути файлов, HTTP-заголовки, имена таблиц/стримов), отклоняют шаблоны без буквального префикса при старте — предотвращает выход за границы (path traversal). HTTP-family шаблоны не могут содержать `?`/`#`. Исключение — `file` sink с явным `base_dir`. Опт-аут: `dangerously_allow_unconfined_template_resolution: true`. Метрики: `component_errors_total{error_type="confinement_failed"}`.
3.  **Backpressure:** Vector автоматически замедляет источники (например, Kafka), если приемники не справляются с потоком. Адаптивный механизм ограничивает concurrency на основе латентности (Adaptive Request Concurrency).
4.  **Дисковые буферы:** Рекомендуется использовать `type = "disk"` для защиты от потери данных при кратковременных сбоях или перезапусках.
5.  **Внутренний API:** не имеет аутентификации — включать только в изолированных средах.

---

## Практические сценарии

Детальные конфигурации вынесены в отдельный файл: **[Practical Scenarios](./practical_scenarios.md)**.

*   Роутер логов из Kafka в OpenSearch.
*   Адаптивное сэмплирование при высокой нагрузке.
*   Обогащение логов через Enrichment Tables (GeoIP).
*   Высокопроизводительная доставка в ClickHouse через Arrow.
*   Сбор метрик и конвертация в логи для Loki.
*   Маршрутизация по уровням логирования (route).
*   Наблюдаемость самого Vector (self-observability).
*   Unit-тестирование конфигурации (vector test).

---

## Дополнительная информация

*   **VRL:** Детальное описание языка трансформации — **[VRL Language](./vrl_language.md)**.
*   **Ресурсы:** [Официальная документация](https://vector.dev), [Vector GitHub](https://github.com/vectordotdev/vector).

**Связанные заметки:**
*   [Four Pillars of Observability](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)
*   [Loki Overview](../Loki/loki_overview.md)
*   [Пайплайн Fluent Bit → Kafka → Vector → OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)
