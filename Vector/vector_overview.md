# Vector: Обзор

**Vector** — высокопроизводительный, открытый (Mozilla Public License 2.0) конвейер для сбора, обработки и отправки логов, метрик и событий (traces). Написан на Rust, что обеспечивает высокую производительность, безопасность памяти и минимальное потребление ресурсов.

**Режимы работы:**
*   **Agent** — легковесный агент на каждом хосте (альтернатива Fluent Bit, Grafana Alloy).
*   **Aggregator** — централизованный обработчик потоков данных (альтернатива Logstash, Fluentd).

---

## Определения

**Конвейер (Pipeline)** — направленный ациклический граф (DAG), описывающий путь данных от источника до хранилища. В Vector каждая конфигурация — это декларативное описание одного или нескольких пайплайнов.

**Событие (Event)** — атомарная единица данных, проходящая через пайплайн. В Vector событие — это объект с набором полей (ключ-значение), обрабатываемый компонентами DAG.

**Источник (Source)** — точка входа данных в пайплайн: файл, системный журнал, сетевой сокет, очередь сообщений или внутренний источник.

**Трансформация (Transform)** — компонент обработки события: парсинг, фильтрация, обогащение, маршрутизация, агрегация.

**Приёмник (Sink)** — конечная точка доставки: поисковый движок, хранилище метрик, очередь или внешний API.

**Backpressure (Обратное давление)** — механизм замедления источников при перегрузке приёмников, предотвращающий потерю данных и падение производительности.

**At-least-once доставка** — семантика доставки, при которой каждое событие гарантированно достигает хранилища, но при сбоях возможны дубликаты.

**Dead Letter Queue (DLQ)** — отдельный выход (`<transform>.dropped`), в который направляются события, не прошедшие трансформацию или доставку, для последующего анализа.

---

## Основные концепции

### Архитектура

Vector построен на базе направленного ациклического графа (DAG) компонентов. Каждый компонент (source, transform, sink) объявляется как секция конфигурации и связывается через параметр `inputs`. Граф допускает fan-in (несколько источников → одна трансформация) и fan-out (один источник → несколько трансформаций/приёмников), но не допускает циклов.

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

### Жизненный цикл события

Событие проходит через пайплайн в следующем порядке:

1.  **Source**: Чтение данных из источника (файл, сокет, очередь). Источник применяет десериализацию (например, `codec = "json"` для TCP) и нормализацию timestamp.
2.  **Transform**: Выполняется zero-copy или копирующая трансформация в зависимости от типа. VRL-код компилируется в нативный Rust при старте, что обеспечивает скорость, сравнимую с написанным вручную кодом.
3.  **Buffer (опционально)**: Между трансформацией и sink'ом может стоять буфер. По умолчанию — `memory`, для критичных пайплайнов — `disk`.
4.  **Sink**: Сериализация события и отправка в конечное хранилище. При недоступности хранилища sink сообщает backpressure в source, который замедляет чтение.

Важно: трансформации в Vector stateless — они не хранят состояние между событиями, что упрощает горизонтальное масштабирование и отладку.

### Структура конфигурации

Конфигурация Vector — текстовый файл в формате TOML (рекомендуется), YAML или JSON. TOML предпочтителен, так как комментируем и иерархичен.

```toml
# /etc/vector/vector.yaml (или .toml)
data_dir = "/var/lib/vector"  # Персистентное состояние (buffer, WAL, enrichment tables)

[sources.app_logs]
type = "file"
include = ["/var/log/app/*.log"]

[transforms.parse]
type = "remap"
inputs = ["app_logs"]
source = '''
. = parse_json!(string!(.message))
.level = to_lower_str!(.level)
'''

[sinks.loki]
type = "loki"
inputs = ["parse"]
endpoint = "http://loki:3100"
```

**Горячая перезагрузка (Hot Reload):** Vector поддерживает перезагрузку конфигурации без остановки пайплайнов. Отправьте сигнал `SIGHUP` процессу Vector — он перечитает конфигурационный файл, сохранит текущие буферы и переключится на новую топологию. Для внешних VRL-файлов (`file = "/etc/vector/script.vrl"`) также работает live-reload.

```bash
kill -HUP $(pidof vector)
# → INFO vector::config: Reloading configuration...
# → INFO vector::sources: Reloaded source app_logs
```

### Backpressure и буферизация

Backpressure — ключевой механизм устойчивости пайплайна. Если sink не справляется с нагрузкой, Vector автоматически замедляет источники, а не отбрасывает данные.

**Типы буферов:**

*   **`memory`** (по умолчанию) — быстрый, но данные теряются при аварийном перезапуске. Подходит для не критичных пайплайнов.
*   **`disk`** — персистентный сброс на диск, гарантия **at-least-once** delivery. Рекомендуется для критичных пайплайнов (Kafka → OpenSearch, audit логи).

**Параметры disk buffer:**
```toml
[sinks.opensearch.buffer]
type = "disk"
max_size = 1073741824  # 1 GiB на sink
when_full = "block"    # Блокировать источник, если буфер заполнен
# when_full = "drop_newest"  # Отбрасывать новые события (не рекомендуется для критичных данных)
```

**Взаимодействие с backpressure:** если Sink не справляется, Vector через adaptive request concurrency автоматически замедляет Sources (например, чтение из Kafka), не теряя данные. Мониторинг состояния буферов — через метрики `component_buffer_*`.

### Внутренний API (gRPC, v0.55+)

Начиная с v0.55.0 внутренний API Vector полностью перешел с GraphQL на gRPC. Это касается и инструментов мониторинга (`vector top`, `vector tap`), что повысило стабильность при экстремальных нагрузках.

*   **Включение:** секция `api.enabled = true` в конфигурации.
*   **Адрес:** `127.0.0.1:8686` по умолчанию; единый порт для gRPC (tonic/HTTP2) и HTTP (`/health`), поддерживается gRPC reflection (grpcurl) и HTTP/1.1 для простых запросов.
*   **Безопасность:** аутентификация отсутствует — рекомендуется включать только в изолированных средах. `/health` возвращает `{"ok":true}` и используется для Kubernetes liveness/readiness проб.

### Горячая перезагрузка (Hot Reload)

Vector поддерживает перезагрузку конфигурации без остановки пайплайнов. Отправьте сигнал `SIGHUP` процессу Vector — он перечитает конфигурационный файл, сохранит текущие буферы и переключится на новую топологию. Для внешних VRL-файлов (`file = "/etc/vector/script.vrl"`) также работает live-reload.

```bash
kill -HUP $(pidof vector)
# → INFO vector::config: Reloading configuration...
# → INFO vector::sources: Reloaded source app_logs
```

### Ключевые внутренние метрики

Vector экспортирует подробные метрики о состоянии каждого компонента. Для SRE эти метрики — основа для алертов и capacity planning.

| Метрика | Описание | Использование |
| :--- | :--- | :--- |
| `component_errors_total{error_type="..."}` | Счётчик ошибок по типу (`parse_failed`, `confinement_failed`, `sink_request_failed`) | Алерт на неожиданный рост |
| `component_received_events_total` / `component_sent_events_total` | Входящие и исходящие события компонента | Балансировка, выявление "узких мест" |
| `component_latency_seconds` | Время обработки события компонентом (bucket-гистограмма) | Профилирование медленных трансформаций |
| `component_buffer_*` | Состояние буферов: размер в байтах, количество событий, утилизация | Прогноз заполнения disk buffer |
| `source_buffer_*` | Состояние буферов источников | Backpressure, недостаток партиций Kafka |
| `transform_buffer_*` | Состояние буферов трансформаций | Перегрузка VRL-кода |
| `vector_build_info` | Версия Vector, коммит, дата сборки | Inventory, совместимость |

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
6.  **TLS и аутентификация в sinks:** Для sinks, взаимодействующих с внешними системами (Elasticsearch, Kafka, OpenSearch), настраивайте TLS (`tls.*`) и механизмы аутентификации (`auth.strategy = "basic"`, SASL для Kafka). Никогда не храните пароли в конфигурации — используйте переменные окружения или secret-провайдеры с учетом ограничений v0.57+.
7.  **Шифрование Vector-to-Vector:** При обмене данными между агентами и агрегаторами через sink `vector` используйте компрессию `zstd` и TLS для защиты данных в transit.

---

## Практические сценарии

Детальные конфигурации вынесены в отдельный файл: **[Practical Scenarios](./practical_scenarios.md)**. Ниже приведены сценарии, характерные для работы DevOps/SRE/SysAdmin инженера с Vector в повседневных задачах.

### Сценарий 1: Замена rsyslog на Vector для сбора системных логов

**Задача:** На bare-metal сервере или ВМ заменить традиционный rsyslog на Vector для централизованного сбора логов systemd-journald, auth.log и nginx access_log с первичной нормализацией.

**Решение:** Vector собирает логи из journald и файлов, нормализует поля через VRL и отправляет в Loki. Disk buffer обеспечивает сохранность при перезапуске службы.

```toml
data_dir = "/var/lib/vector"

[sources.journald]
type = "journald"
include_units = ["sshd.service", "nginx.service", "sudo.service"]

[sources.auth_log]
type = "file"
include = ["/var/log/auth.log"]
ignore_older = 86400

[sources.nginx_access]
type = "file"
include = ["/var/log/nginx/access.log"]
ignore_older = 86400

[transforms.normalize]
type = "remap"
inputs = ["journald", "auth_log", "nginx_access"]
source = '''
# Нормализация уровня логирования
if exists(.priority) {
  .level = match!(.priority, r'^\d+') -> to_int!(.) -> to_string!({
    0: "emerg", 1: "alert", 2: "crit", 3: "err",
    4: "warning", 5: "notice", 6: "info", 7: "debug"
  })
}
# Удаление временных полей
del(._PID)
del(._SYSTEMD_UNIT)
'''

[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"
labels = { source = "vector_syslog", host = "${HOSTNAME}" }
```

**Проверка:**
```bash
vector validate --config /etc/vector/vector.yaml
# → код возврата 0

vector tap normalize
# → {"level":"info","message":"Started","source":"vector_syslog",...}
```

### Сценарий 2: Сбор host_metrics и отправка в Prometheus

**Задача:** Собрать системные метрики CPU, памяти, диска и сетевых интерфейсов с серверов и экспортировать в Prometheus в формате remote write.

**Решение:** Использовать source `host_metrics` для сбора метрик хоста и sink `prometheus_remote_write` для отправки.

```toml
[sources.host]
type = "host_metrics"
scrape_interval_secs = 15
collect_cpu = true
collect_memory = true
collect_disk = true
collect_network = true

[sinks.prom]
type = "prometheus_remote_write"
inputs = ["host"]
endpoint = "http://prometheus:9090/api/v1/write"
```

**Проверка:**
```bash
curl -s http://localhost:9090/api/v1/query?query=up | jq .
# → Данные по метрикам Vector присутствуют
```

### Сценарий 3: Защита хранилища через throttle + disk buffer

**Задача:** Ограничить скорость отправки логов в Loki, чтобы хранилище не перегружалось при всплесках трафика, и при этом не терять события.

**Решение:** Transform `throttle` ограничивает количество событий в единицу времени, disk buffer защищает от потерь при переполнении.

```toml
[transforms.limit_rate]
type = "throttle"
inputs = ["app_logs"]
key = "$$.hash"  # Группируем по хешу события (или используйте .service)
limit = 1000     # Максимум 1000 событий в секунду
period = 1s      # Окно сброса счётчика

[sinks.loki]
type = "loki"
inputs = ["limit_rate"]
endpoint = "http://loki:3100"

[sinks.loki.buffer]
type = "disk"
max_size = 536870912  # 512 MiB
when_full = "block"
```

**Мониторинг:**
```bash
vector top
# → Следите за dropped в throttle и размером буфера
```

### Сценарий 4: Создание SLI из логов через log_to_metric

**Задача:** Преобразовать логи об ошибках HTTP в метрики для расчёта SLI (доля успешных запросов) и алертинга.

**Решение:** Использовать transform `log_to_metric` для генерации метрики `http_requests_total` из логов, затем отправить в Prometheus.

```toml
[transforms.http_metrics]
type = "log_to_metric"
inputs = ["nginx_access"]
name = "http_requests_total"
namespace = "vector"
type = "counter"
field = "status"  # Значение метрики — поле status
tags.status = "{{ status }}"
tags.service = "nginx"

[sinks.prom]
type = "prometheus_remote_write"
inputs = ["http_metrics"]
endpoint = "http://prometheus:9090/api/v1/write"
```

**Проверка:**
```bash
curl -s http://localhost:9090/api/v1/query?query=http_requests_total | jq .
# → Метрика появилась в Prometheus
```

### Сценарий 5: Диагностика пайплайна через vector tap и vector top

**Задача:** Оперативно найти причину, почему определённые логи не доходят до Loki.

**Решение:** Использовать `vector top` для оценки нагрузки и `vector tap` для инспекции событий на конкретном этапе пайплайна.

```bash
# 1. Общая нагрузка на компоненты
vector top
# → app_logs: Events Out 1500/s
# → parse: Events Out 1480/s
# → loki: Events Out 1475/s

# 2. Инспекция после парсинга
vector tap parse
# → {"message":"GET /healthz 200","status":"200",...}

# 3. Инспекция ошибок парсинга (reroute_dropped)
vector tap parse.dropped
# → {"message":"invalid json","error":"parse error",...}
```

---

## Дополнительная информация

### Установка и управление службой

Vector компилируется в единый статический бинарник (зависимость только от `libc`; доступны musl-сборки без зависимостей). Установка:

```bash
curl --proto '=https' --tlsv1.2 -sSfL https://sh.vector.dev | bash
```

Служба systemd (`/etc/systemd/system/vector.service`) поставляется в пакете. После изменения конфигурации используйте `systemctl reload vector` для горячей перезагрузки.

### Интерполяция переменных окружения (v0.57+)

`${VAR}` в конфигурации отключена по умолчанию. Для включения:
```bash
vector --config /etc/vector/vector.yaml --dangerously-allow-env-var-interpolation
```
Или используйте секреты через провайдеры (HashiCorp Vault, environment variables с префиксом), не включая глобальную интерполяцию.

### См. также

*   **VRL:** Детальное описание языка трансформации — **[VRL Language](./vrl_language.md)**.
*   **Практические пайплайны:** Kafka → OpenSearch, адаптивное сэмплирование, ClickHouse + Arrow — **[Practical Scenarios](./practical_scenarios.md)**.
*   **Loki:** Архитектура хранилища логов — **[Loki Overview](../Loki/loki_overview.md)**.
*   **Наблюдаемость:** Логи, метрики, трассировки — **[Четыре столпа Observability](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)**.
*   **Веб-интерфейс и документация:** [Official VRL documentation](https://vector.dev/docs/reference/vrl/) — полный справочник функций и синтаксиса.
