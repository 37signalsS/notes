# Grafana Tempo

## Definitions

**Tempo** — высокомасштабируемое распределённое хранилище трассировок (traces) от Grafana Labs. Анонсировано в 2020, GA в 2021. Язык — Go, лицензия — AGPLv3. Цель — экономичное хранение больших объёмов трассировок в object storage (S3, GCS, Azure, MinIO).

**Trace (трассировка)** — запись полного жизненного цикла запроса, проходящего через несколько сервисов. Показывает задействованные сервисы, последовательность, длительность этапов и взаимодействия.

**Span (спан)** — фундаментальная единица трассировки. Представляет отдельную операцию (HTTP-запрос, вызов функции, запрос к БД). Имеет имя, время начала/окончания, атрибуты, ссылки на другие спаны.

**TraceQL** — язык запросов для поиска и фильтрации трассировок в Tempo. Вдохновлён PromQL и LogQL. Поддерживает фильтрацию по атрибутам, длительности, событиям (events), ссылкам (links) и агрегацию (metrics).

---

## Basic Concepts

### Назначение трассировок

- Выявление задержек и «узких мест» в распределённых системах.
- Визуализация потоков выполнения запросов.
- Отладка ошибок на стыке сервисов.

### Ключевые особенности

- **Масштабируемость** — горизонтальное масштабирование для обработки больших объёмов трассировок.
- **Экономичное хранение** — object storage (S3, GCS, Azure, MinIO) или NFS. Данные хранятся сжатыми в формате vParquet.
- **Поддержка OpenTelemetry** — полный цикл сбора, обработки и экспорта телеметрии через [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).
- **Мульти-тенантность** — встроенная изоляция данных для разных команд/клиентов (tenants).
- **Интеграция с Grafana** — визуализация и корреляция с метриками/логами. Собственного UI нет.
- **Гибкость форматов** — приём [Jaeger](../Jaeger/jaeger_overview.md), Zipkin, [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md).
- **Exemplars** — связь трассировок с метриками [Prometheus](../Prometheus/overview.md) через `trace_id`.
- **Нативные гистограммы Prometheus** — поддержка native histograms для данных высокой точности (с v2.6).

### Сравнение с Jaeger

| Характеристика | Tempo | Jaeger v2 |
| :--- | :--- | :--- |
| Индексация | Только по `trace_id` | Полная индексация метаданных (теги) |
| Хранилище | Object storage (S3, GCS, Azure, MinIO) | Elasticsearch, OpenSearch, Cassandra, ClickHouse, Badger |
| Стоимость хранения | Низкая | Высокая (требует БД) |
| Поиск | Ограничен (по trace_id и атрибутам через TraceQL) | Гибкий поиск по тегам, сервисам, операциям |
| UI | Интеграция с Grafana | Собственный Jaeger UI |
| Масштабируемость | Неограниченная (object storage) | Ограничена возможностями БД |
| Операционная сложность | Низкая | Средняя/Высокая (тюнинг БД) |
| Экосистема | Grafana Stack (Loki, Mimir, Grafana) | CNCF, независимый проект |

Tempo выбирают для экономичного хранения больших объёмов трассировок в экосистеме Grafana. Jaeger — для сценариев с требованием гибкого поиска и независимого развёртывания. Подробнее: [Jaeger overview](../Jaeger/jaeger_overview.md).

### Архитектура

Tempo развёртывается как монолит или распределённо. Архитектура аналогична [Loki](../Loki/loki_overview.md) и [Mimir](../Mimir/mimir_overview.md). Компоненты:

- **Distributor** — приём трассировок, валидация, распределение.
- **Ingester** — буферизация в памяти, запись в долгосрочное хранилище в сжатом виде.
- **Querier** — обработка запросов TraceQL (из инжестеров и долгосрочного хранилища).
- **Query Frontend** (опционально) — кэширование и параллелизация запросов.
- **Compactor** — фоновая оптимизация хранения (объединение файлов, политики хранения).
- **Metric Generator** (опционально) — генерация метрик из трассировок для [Prometheus](../Prometheus/overview.md)/[Mimir](../Mimir/mimir_overview.md).

Подробнее: [Архитектура и операции Tempo](./architecture_operations.md).

---

## Practical Scenarios

### Установка и развёртывание

Способы установки: бинарный файл (Linux, macOS, Windows), [Docker](../Docker/docker_overview.md), Kubernetes (Helm-чарт), Grafana Cloud.

Развёртывание в Kubernetes:

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
helm install tempo grafana/tempo-distributed --namespace tempo --create-namespace
```

Пример полного развёртывания: [LGTM Stack в Minikube](../Kubernetes/Installation/LGTM_Stack/lgtm_otel_minikube_overview.md).

### TraceQL

Базовые примеры запросов:

```traceql
// Фильтрация по атрибутам спанов
{.service.name = "frontend" && .http.status_code = 500}

// Фильтрация по продолжительности
{.duration > 100ms}

// Поиск по событиям (events)
{ event.name = "exception" }

// Агрегация (TraceQL Metrics, с v2.6)
count_by(.service.name)
```

> **Важно:** Для TraceQL Metrics требуется `replication_factor: 1` и настройка `local-blocks` processor. Подробнее: [конфигурация TraceQL Metrics](./architecture_operations.md#traceql-metrics-configuration).

### Интеграции

**Grafana** — поиск и фильтрация через TraceQL, просмотр диаграммы Ганта, корреляция с метриками (Exemplars) и логами (Derived Fields). Настройка datasource: [Grafana datasources](../Grafana/grafana_datasources.md).

**OpenTelemetry Collector** — рекомендуемый способ отправки трассировок в Tempo. Конфигурация receiver/exporter описана в [OTLP Protocol](../OpenTelemetry/otlp_protocol.md).

**Loki** — настройка Derived Fields извлекает `trace_id` из логов и создаёт ссылку на datasource Tempo. Подробнее: [Loki overview](../Loki/loki_overview.md).

### Рекомендации по эксплуатации

- **Head sampling** — сэмплирование на уровне приложения для управления объёмом данных.
- **Retention policy** — настройка политик хранения до развёртывания в production.
- **Единые trace_id** — поддержка единых идентификаторов для трассировок, метрик и логов.
- **Кэширование** — Redis/Memcached для Query Frontend.
- **Мониторинг Tempo** — развёртывание [Prometheus](../Prometheus/overview.md) для мониторинга метрик самого Tempo.
- **TLS** — включение TLS для всех внутренних коммуникаций в production.

Подробнее: [Архитектура и операции Tempo](./architecture_operations.md).

---

## Additional Information

Tempo входит в состав Grafana Stack (LGTM) и тесно интегрирован с [Grafana](../Grafana/grafana_overview.md), [Loki](../Loki/loki_overview.md) (корреляция логов через Derived Fields), [Prometheus](../Prometheus/overview.md) (exemplars и метрики), [Mimir](../Mimir/mimir_overview.md). Стандарт телеметрии — [OpenTelemetry](../OpenTelemetry/opentelemetry_overview.md). Альтернатива — [Jaeger](../Jaeger/jaeger_overview.md).

Файлы директории Tempo: [Архитектура и операции](./architecture_operations.md) (формат vParquet, breaking changes, конфигурации хранилищ).

Документация: [официальная документация](https://grafana.com/docs/tempo/latest/), [GitHub-репозиторий](https://github.com/grafana/tempo), [TraceQL Documentation](https://grafana.com/docs/tempo/latest/traceql/).
