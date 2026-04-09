# Vector: Обзор

## Definitions

**Vector** — высокопроизводительный конвейер для сбора, обработки и отправки логов, метрик и событий. Написан на Rust — высокая производительность, безопасность памяти, низкое потребление ресурсов.

**Режимы работы:**

- **Agent** — легковесный агент на каждом хосте (замена Filebeat/Fluent Bit)
- **Aggregator** — централизованный обработчик потоков данных (замена Logstash/Fluentd)

---

## Basic Concepts

### Архитектура

Три компонента:

1. **Sources (Источники)** — определяют, откуда Vector получает данные:
    - Файлы логов (`/var/log/*.log`, journald)
    - Сетевые протоколы (Syslog, HTTP, TCP, UDP)
    - Очереди сообщений (Kafka, NATS)
    - Облачные сервисы (AWS S3, GCP Pub/Sub, Azure Event Hubs)
    - Контейнеры и оркестраторы (Docker, Kubernetes)
    - Системные метрики (OS, Prometheus endpoints)

2. **Transforms (Преобразования)** — модифицируют, фильтруют и обогащают данные:
    - **`remap`** — преобразования через [VRL](./vrl_language.md)
    - **`filter`** — фильтрация событий по условиям
    - **`route`** — маршрутизация по разным sink'ам
    - **`reduce`** — агрегация нескольких событий
    - **`luajit`** — кастомная логика на Lua

3. **Sinks (Приёмники)** — определяют, куда отправлять обработанные данные:
    - Хранилища логов (Elasticsearch, OpenSearch, [Loki](../Loki/loki_overview.md), ClickHouse)
    - Очереди (Kafka, NATS, AWS SQS)
    - Метрики (Prometheus remote write, Datadog, StatsD)
    - Облака (AWS S3, GCS, Azure Blob Storage)
    - HTTP/Webhook endpoints

### Ключевые характеристики

| Характеристика | Описание |
| :--- | :--- |
| **Производительность** | В 5–10 раз быстрее Logstash/Fluentd при меньшем потреблении CPU |
| **Безопасность памяти** | Гарантии Rust исключают уязвимости типа buffer overflow |
| **Гарантия доставки** | At-least-once delivery с персистентным буфером на диске |
| **Мультиплатформенность** | Linux, macOS, Windows, Docker, Kubernetes |
| **Конфигурация** | TOML, YAML, JSON (TOML рекомендуется) |
| **Обработка ошибок** | Встроенные retry, dead letter queue |

### Режимы развёртывания

#### Agent Mode

Vector на каждом хосте — DaemonSet (Kubernetes) или systemd-сервис (VM).

**Преимущества:** минимальная задержка, локальная буферизация при потере сети, сжатие на месте.

**Сценарии:** сбор логов с файлов (`/var/log`, journald), сбор метрик с экспортёров, отправка в хранилище или Kafka.

#### Aggregator Mode

Отдельный сервис/кластер для обработки потоков от агентов.

**Преимущества:** централизованная трансформация и обогащение, снижение нагрузки на агенты.

**Сценарии:** чтение из Kafka и трансформация, агрегация логов из нескольких K8s-кластеров, обогащение внешними данными (GeoIP, K8s metadata).

#### Hybrid Mode

Агенты → Kafka → Aggregator → хранилища. Сценарий: `Fluent Bit → Kafka → Vector → OpenSearch` (подробно в [туториале](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)).

### Сравнение с аналогами

| Характеристика | Vector | Logstash | Fluentd/Fluent Bit | file.d |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Rust | Java/JRuby | Ruby/C | Go |
| **Производительность** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Потребление памяти** | Низкое | Высокое | Среднее | Низкое |
| **Экосистема плагинов** | Средняя | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Малая |
| **Конфигурация** | TOML/YAML | DSL (Ruby-like) | DSL | YAML |
| **Язык трансформации** | VRL | Filter-плагины | Record-modifier | Lua/Go |
| **Гарантия доставки** | At-least-once | At-least-once | At-least-once | At-least-once |

**Vector vs Logstash** — Vector быстрее (в 5–10 раз), потребляет меньше ресурсов; Logstash имеет зрелую экосистему плагинов (200+ против ~100). Подробнее: [Logstash Overview](../ELK_Stack/Logstash/logstash_overview.md#сравнение-logstash-и-vector).

**Vector vs file.d** — file.d (OzonTech) ориентирован на импортозамещение; Vector имеет более богатые трансформации (VRL vs Lua). Подробнее: [file.d Overview](../file.d_overview.md).

**Vector vs Fluent Bit** — Fluent Bit легче (~5 MB), но с ограниченными трансформациями; Vector (~30 MB) предоставляет полноценный VRL. Оптимальная связка: Fluent Bit → Kafka → Vector.

### Интеграция с Kubernetes

Официальная поддержка через Helm-чарт:

1. **DaemonSet** — сбор логов с `/var/log/pods/*`, обогащение K8s metadata.
2. **Deployment** — агрегация из Kafka, горизонтальное масштабирование, consumer groups.
3. **StatefulSet** — stateful-источники, персистентный буфер, гарантированная доставка.

### Миграция с других инструментов

**С Logstash:** экспорт конфигурации → переписывание фильтров на VRL → тестирование на параллельном потоке → переключение трафика.

**С Fluent Bit:** Fluent Bit остаётся агентом, Vector разворачивается как агрегатор вместо Fluentd → постепенная миграция sink'ов.

---

## Practical Scenarios

Практические сценарии вынесены в отдельный файл: **[Practical Scenarios](./practical_scenarios.md)**.

Краткий перечень:
- Роутер логов из Kafka в OpenSearch ([подробнее](./practical_scenarios.md#практический-сценарий-роутер-логов-из-kafka-в-opensearch))
- Сбор метрик с Prometheus endpoints ([подробнее](./practical_scenarios.md#практический-сценарий-сбор-метрик-с-prometheus-endpoints))
- Обогащение логов GeoIP ([подробнее](./practical_scenarios.md#практический-сценарий-обогащение-логов-geoip))

---

## Additional Information

**Инструменты:** [VRL Playground](https://vrl.dev) — онлайн-песочница для тестирования скриптов; [VSCode Extension](https://marketplace.visualstudio.com/items?itemName=oryanp.vscode-vrl) — подсветка синтаксиса.

**Ресурсы:** [Официальная документация](https://vector.dev/docs/), [GitHub Repository](https://github.com/vectordotdev/vector), [Vector Discord](https://discord.gg/vectordotdev).

**Связанные заметки:** Observability — [Four Pillars](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md); проектирование высоконагруженного мониторинга — [Designing High-Load Monitoring](../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md); язык трансформации — [VRL Language](./vrl_language.md); практические сценарии — [Practical Scenarios](./practical_scenarios.md).
