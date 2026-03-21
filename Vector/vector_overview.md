# Vector: Обзор

## Определения

**Vector** — это высокопроизводительный конвейер для сбора, обработки и отправки логов, метрик и событий. Написан на языке Rust, что обеспечивает высокую производительность, безопасность памяти и низкое потребление ресурсов.

**Ключевая особенность:** Vector может работать в двух режимах:

- **Agent** — легковесный агент на каждом хосте (замена Filebeat/Fluent Bit)
- **Aggregator** — централизованный обработчик потоков данных (замена Logstash/Fluentd)

---

## Основные концепции

### Архитектура

Архитектура Vector состоит из трёх компонентов:

1. **Sources (Источники)** — определяют, откуда Vector получает данные:
    - Файлы логов (`/var/log/*.log`, journald)
    - Сетевые протоколы (Syslog, HTTP, TCP, UDP)
    - Очереди сообщений (Kafka, NATS)
    - Облачные сервисы (AWS S3, GCP Pub/Sub, Azure Event Hubs)
    - Контейнеры и оркестраторы (Docker, Kubernetes)
    - Системные метрики (OS, Prometheus endpoints)

2. **Transforms (Преобразования)** — модифицируют, фильтруют и обогащают данные:
    - **`remap`** — преобразования с помощью [VRL](./vrl_language.md)
    - **`filter`** — фильтрация событий по условиям
    - **`route`** — маршрутизация по разным sink'ам
    - **`reduce`** — агрегация нескольких событий
    - **`luajit`** — кастомная логика на Lua

3. **Sinks (Приемники)** — определяют, куда отправлять обработанные данные:
    - Хранилища логов (Elasticsearch, OpenSearch, Loki, ClickHouse)
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
| **Конфигурация** | TOML, YAML, JSON (TOML рекомендуется для строгости) |
| **Обработка ошибок** | Встроенные механизмы retry, dead letter queue |

### Режимы развертывания

#### Agent Mode (Агент на каждом хосте)

Vector устанавливается на каждый хост как DaemonSet (Kubernetes) или systemd-сервис (VM).

**Преимущества:**

- Минимальная задержка доставки
- Локальная буферизация при потере сети
- Снижение нагрузки на сеть (сжатие, агрегация на месте)

**Сценарии:**

- Сбор логов с файлов (`/var/log`, journald)
- Сбор метрик с экспортеров
- Отправка напрямую в хранилище или в Kafka

#### Aggregator Mode (Централизованный обработчик)

Vector разворачивается как отдельный сервис/кластер для обработки потоков от агентов.

**Преимущества:**

- Централизованная трансформация и обогащение
- Снижение нагрузки на агенты
- Удобство управления конфигурацией

**Сценарии:**

- Чтение из Kafka и трансформация перед отправкой в хранилище
- Агрегация логов из нескольких кластеров Kubernetes
- Обогащение данными из внешних источников (GeoIP, Kubernetes metadata)

#### Hybrid Mode (Комбинированный)

Агенты собирают и отправляют в Kafka → Aggregator читает из Kafka, трансформирует и отправляет в хранилища.

**Сценарий:** `Fluent Bit → Kafka → Vector → OpenSearch`

Подробный разбор см. в **[Практическом сценарии: Роутер логов из Kafka в OpenSearch](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)**.

---

## Сравнение с аналогами

| Характеристика | Vector | Logstash | Fluentd/Fluent Bit | file.d |
| :--- | :--- | :--- | :--- | :--- |
| **Язык** | Rust | Java/JRuby | Ruby/C | Go |
| **Производительность** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Потребление памяти** | Низкое | Высокое | Среднее | Низкое |
| **Экосистема плагинов** | Средняя | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Малая |
| **Конфигурация** | TOML/YAML | DSL (Ruby-like) | DSL | YAML |
| **Язык трансформации** | VRL | Filter-плагины | Record-modifier | Lua/Go |
| **Гарантия доставки** | At-least-once | At-least-once | At-least-once | At-least-once |

### Vector vs Logstash

- **Vector** превосходит Logstash по производительности (в 5–10 раз) и потреблению ресурсов
- **Logstash** имеет более зрелую экосистему плагинов (200+ против ~100 у Vector)
- **Выбор в пользу Vector:** Высоконагруженные системы, ограниченные ресурсы, безопасность
- **Выбор в пользу Logstash:** Экзотические плагины, legacy-интеграции

> Сравнение подробно разобрано в **[Logstash Overview](../ELK_Stack/Logstash/logstash_overview.md#сравнение-logstash-и-vector)**.

### Vector vs file.d

- **file.d** — российская альтернатива от OzonTech, также ориентирована на производительность
- **Vector** имеет более богатый функционал трансформаций (VRL vs Lua) и шире распространен
- **Выбор в пользу file.d:** Требования к импортозамещению, простая конфигурация
- **Выбор в пользу Vector:** Сложные трансформации, международная поддержка

> Подробнее о file.d см. в **[file.d Обзор](../file.d_overview.md)**.

### Vector vs Fluent Bit

- **Fluent Bit** — сверхлегкий агент (образ ~5 MB), но с ограниченными возможностями трансформации
- **Vector** тяжелее (~30 MB), но предоставляет полноценный язык трансформаций VRL
- **Оптимальная связка:** Fluent Bit как агент → Kafka → Vector как агрегатор

---

## Интеграция с Kubernetes

Vector официально поддерживает развертывание в Kubernetes через Helm-чарт.

**Рекомендуемые паттерны:**

1. **DaemonSet для сбора логов с хостов:**
    - Сбор с `/var/log/pods/*`
    - Автоматическое обогащение Kubernetes metadata

2. **Deployment для агрегации из Kafka:**
    - Горизонтальное масштабирование по CPU/RAM
    - Consumer groups для балансировки нагрузки

3. **StatefulSet для stateful-источников:**
    - Персистентный буфер на диске
    - Гарантированная доставка при перезапусках

---

## Миграция с других инструментов

### С Logstash на Vector

1. Экспорт конфигурации Logstash (pipeline, фильтры)
2. Переписывание фильтров на VRL (синтаксис отличается)
3. Тестирование на параллельном потоке данных
4. Переключение трафика через балансировщик

### С Fluent Bit на Vector

1. Fluent Bit уже может работать как агент — замена не требуется
2. Vector разворачивается как агрегатор вместо Fluentd
3. Постепенная миграция sink'ов

---

## Ресурсы

- **[Официальная документация](https://vector.dev/docs/)** — полные docs, tutorials, API reference
- **[VRL Playground](https://vrl.dev)** — онлайн-песочница для тестирования скриптов
- **[GitHub Repository](https://github.com/vectordotdev/vector)** — исходный код, issues, RFC
- **[Vector Discord](https://discord.gg/vectordotdev)** — сообщество для вопросов

---

## Связанные заметки

| Тема | Ссылка |
| :--- | :--- |
| Observability (4 столпа) | **[Обзор Observability](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)** |
| Архитектура сбора логов | **[Проектирование высоконагруженного мониторинга](../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md)** |
| Пайплайн Fluent Bit → Kafka → Vector | **[Tutorial](../ELK_Stack/Tutorials/fluentbit_kafka_vector_opensearch_pipeline.md)** |

| Хранение в Loki | **[Loki Overview](../Loki/loki_overview.md)** |
| Сравнение с Logstash | **[Logstash Overview](../ELK_Stack/Logstash/logstash_overview.md)** |
| Альтернатива file.d | **[file.d Обзор](../file.d_overview.md)** |
| Хранение в OpenSearch | **[OpenSearch Overview](../ELK_Stack/OpenSearch/opensearch_overview.md)** |
| Хранение в Loki | **[Loki Overview](../Loki/loki_overview.md)** |
| Язык трансформации VRL | **[VRL Language](./vrl_language.md)** |
