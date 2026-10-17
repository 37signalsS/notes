# Vector: Обзор

**Актуально для:** Vector 0.58.0 (latest stable, released 2026-08-26)

**Vector** — высокопроизводительный, открытый (Mozilla Public License 2.0) конвейер для сбора, обработки и отправки логов, метрик и событий (traces). Написан на Rust, что обеспечивает высокую производительность, безопасность памяти и минимальное потребление ресурсов. Один статический бинарник, единственная зависимость — `libc` (доступны также musl-сборки без зависимостей для stripped-down окружений).

**Режимы работы:**
*   **Agent** — легковесный агент на каждом хосте: сбор логов с systemd-journal, syslog, файлов; first-pass парсинг и локальная буферизация. Альтернатива rsyslog +Fluent Bit на bare-metal и ВМ.
*   **Aggregator** — централизованный обработчик потоков данных: сложная трансформация (VRL), дедупликация, сэмплирование, агрегация метрик. Альтернатива Logstash.

---

## Определения

**Конвейер (Pipeline)** — направленный ациклический граф (DAG), описывающий путь данных от источника до хранилища. В Vector каждая конфигурация — это декларативное описание одного или нескольких пайплайнов. Может содержать несколько независимых пайплайнов (multiline, триггеры).

**Событие (Event)** — атомарная единица данных, проходящая через пайплайн. В Vector событие — это объект с набором полей (ключ-значение) и метаданными. Существует два типа событий: **log event** (строка лога с полями) и **metric event** (счетчик, гистограмма, gauge, summary и т.д.).

**Источник (Source)** — точка входа данных в пайплайн: файл, системный журнал, сетевой сокет, очередь сообщений или внутренний источник. Источник читает сырые данные, применяет десериализацию (через `codecs`) и нормализует timestamp.

**Трансформация (Transform)** — компонент обработки события: парсинг, фильтрация, обогащение, маршрутизация, агрегация. VRL-трансформация (`remap`) компилируется в нативный Rust-код при старте Vector, обеспечивая скорость, сравнимую с ручным кодом.

**Приёмник (Sink)** — конечная точка доставки: поисковый движок, хранилище метрик, очередь или внешний API. Sink сериализует событие (через `codecs`) и отправляет батчами с поддержкой backpressure.

**Backpressure (Обратное давление)** — механизм замедления источников при перегрузке приёмников. Реализуется через адаптивную concurrency (Adaptive Request Concurrency, ARC) на основе латентности. Предотвращает переполнение буфера и потерю данных.

**Dead Letter Queue (DLQ)** — механизец перенаправления событий, не прошедших трансформацию или доставку. Настраивается через поле `<component>.dropped` или отдельный sink типа `blackhole`/`file` для последующего анализа.

**At-least-once доставка** — семантика доставки, при которой каждое событие гарантированно достигает хранилища, но при сбоях возможны дубликаты. Обеспечивается дисковыми буферами и подтверждением от приёмника (acknowledgements).

---

## Основные концепции

### Архитектура

Vector построен на базе направленного ациклического графа (DAG) компонентов. Каждый компонент (source, transform, sink) объявляется как секция конфигурации и связывается через параметр `inputs`. Граф допускает fan-in (несколько источников → одна трансформация) и fan-out (один источник → несколько трансформаций/приёмников), но не допускает циклы.

#### Источники (Sources)

Vector поддерживает более 40 типов источников. Для DevOps/SRE/SysAdmin на базе bare-metal и ВМ ключевыми являются:

*   **Файлы и система:** `file` (с обнаружением ротации через `fingerprint`), `journald` (systemd journal), `syslog` (RFC 3164/5424), `windows_event_log` (через нативное Windows API).
*   **Хостовые метрики:** `host_metrics` — CPU, память, диск, сеть, файловая система (с `filesystem` и `mount` опциями); `proc` для произвольных метрик из `/proc`.
*   **Сетевые протоколы:** `socket` (TCP/UDP), `http_server` (веб-хуки), `http_client` (polling), `nats`, `kafka` (самостоятельный брокер), `redis`, `amqp`.
*   **Агрегаторы метрик:** `prometheus_scrape` (scrape endpoint), `prometheus_pushgateway`, `statsd`, `nginx_metrics`, `apache_metrics`.
*   **Внутренние источники:** `internal_logs` — логи самого Vector (для мониторинга); `internal_metrics` — метрики самого Vector (CPU, memory, buffer size, component throughput).
*   **Контейнеры:** `docker_logs` — сбор логов Docker-контейнеров через Docker API (на bare-metal и ВМ) и `file` с `multiline` для Podman.

#### Трансформации (Transforms)

Vector поддерживает следующие типы трансформаций:

*   **`remap`** — основной VRL-движок для парсинга, нормализации и обогащения событий. VRL-программы компилируются в нативный Rust при старте. Подробности: [VRL Language](./vrl_language.md).
*   **`filter`** — отсеивание событий по VRL-условию.
*   **`route`** — условная маршрутизация по VRL-выражениям.
*   **`aggregate`** — агрегация метрик по окнам времени (sum, min, max, mean, stdev, count, diff, latest).
*   **`sample`** — сэмплирование (геометрическое, по размеру).
*   **`throttle`** — ограничение скорости событий.
*   **`dedupe`** — удаление дубликатов по ключу.
*   **`log_to_metric`** — преобразование log-событий в метрики.
*   **`metric_to_log`** — обратное преобразование.
*   **`delay`** — задержка доставки событий на указанный интервал (v0.56+).
*   **`reduce`** — оконная агрегация для распределения по ключу.
*   **`window`** — фиксированное или скользящее окно времени.
*   **`tag_cardinality_limit`** — ограничение кардинальности тегов (защита от cardinality explosion).
*   **`exclusive_route`** — эксклюзивная маршрутизация (каждое событие маршрутизируется только на первый совпавший маршрут; неповторяющиеся → `._unmatched`).
*   **`incremental_to_absolute`** — преобразование приращений в абсолютные значения.
*   **`trace_to_log`** — преобразование трасс в логи.

#### Приёмники (Sinks)

Поддерживаемые sink-компоненты для DevOps/SRE/SysAdmin:

*   **Хранилища логов:** Loki, OpenSearch, Elasticsearch, ClickHouse (Native Arrow `arrow_stream` и HTTP), File (локальная архивация).
*   **Метрики:** `prometheus_remote_write`, `prometheus_exporter` (самостоятельный scrape endpoint).
*   **Очереди:** Kafka, NATS, Redis, AMQP — для построения надёжных буферизующих слоёв.
*   **Сеть:** `http` (POST/PUT), `socket` (TCP/UDP), `websocket`, `syslog` (перенаправление наружу).
*   **Vector-to-Vector:** sink `vector` для связи агентов с агрегаторами (сжатие `gzip`/`zstd`).
*   **`console`** — вывод в stdout/stderr (для отладки и unit-тестов).

### Жизненный цикл события

Событие проходит через пайплайн в следующем порядке:

1.  **Source**: Чтение данных из источника (файл, сокет, очередь, журнал). Источник применяет десериализацию (через `codecs = "json"`/`"text"`/`"bytes"`/`"syslog"`) и нормализацию `timestamp` (поле `.timestamp` или выбор поля через `timestamp_key`/`timestamp_source`).
2.  **Transform**: Выполняется stateless трансформация. VRL-код компилируется в нативный Rust при старте, что обеспечивает скорость, сравнимую с написанным вручную кодом. Трансформации не сохраняют состояние между событиями (за исключением агрегирующих трансформаций: `aggregate`, `reduce`, `dedupe`, `window`).
3.  **Buffer (опционально)**: Между трансформацией и sink'ом может стоять буфер. По умолчанию — `memory`, для критичных пайплайнов — `disk` (с WAL, `when_full = "block"`).
4.  **Sink**: Сериализация события через `encoding.codec` и отправка батчами (`batch.max_events`, `batch.timeout_secs`, `batch.max_bytes`). Адаптивная concurrency автоматически регулирует количество одновременных запросов на основе латентности.

### Структура конфигурации

Конфигурация Vector — текстовый файл в формате TOML (рекомендуется), YAML или JSON. TOML предпочтителен за строгую типизацию и иерархичность. Конфигурация может быть разбита на несколько файлов (слияние через `--config-dir`).

Глобальные опции:
```toml
data_dir = "/var/lib/vector"      # Персистентное состояние: buffer, WAL, enrichment tables
api.enabled = false               # Внутренний API для vector top/tap (127.0.0.1:8686)
```

Минимальная конфигурация — агент для сбора journald и файловых логов с VRL-нормализацией в Loki:

```toml
data_dir = "/var/lib/vector"
api.enabled = false

[sources.journald]
type = "journald"
include_units = ["sshd.service", "nginx.service"]

[sources.app_logs]
type = "file"
include = ["/var/log/app/*.log"]
ignore_older = 86400

[sources.docker_logs]
type = "docker_logs"
exclude_own = true

[transforms.normalize]
type = "remap"
inputs = ["journald", "app_logs", "docker_logs"]
source = '''
. = parse_json!(string!(.message))
.level = downcase(.level)
'''

[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"
labels.key = "{{ source }}"
```

**Горячая перезагрузка (Hot Reload):** Vector поддерживает перезагрузку конфигурации без остановки пайплайнов. Есть два способа:

1.  Сигнал `SIGHUP` — перечитывает конфигурационный файл, сохраняет текущие буферы и переключается на новую топологию.
2.  Флаг `--watch-config` / `-w` — Vector автоматически следит за изменениями файла и перезагружает конфигурацию без сигнала.

```bash
# Способ 1: ручной reload через сигнал
kill -HUP $(pidof vector)
# → INFO vector::config: Reloading configuration...
# → INFO vector::sources: Reloaded source journald

# Способ 2: запуск с авто-перезагрузкой конфигурации
vector --config /etc/vector/vector.yaml --watch-config
```

Для внешних VRL-файлов (`source = "file:///etc/vector/script.vrl"`) hot-reload также применяется — изменения в файле VRL подхватываются без перезапуска.

---

## Установка и управление службой

### Предпосылки

*   **ОС:** Linux (ядро 3.10+, systemd 219+), macOS 10.15+, Windows Server 2016+.
*   **Зависимости:** единственная внешняя зависимость — `libc`. Для stripped-down контейнеров доступны musl-сборки без зависимостей.
*   **Права:** Vector агент требует прав на чтение файлов журналов (`/var/log/`), `/var/log/journal/`, `/proc/`, `/sys/` и подключение к сокетам. Sink может требовать прав на запись в `data_dir`.
*   **Порты:** по умолчанию внутренний API слушает `127.0.0.1:8686` (gRPC + HTTP `/health`).

### Установка

```bash
# Официальный установщик (определяет платформу)
curl --proto '=https' --tlsv1.2 -sSfL https://sh.vector.dev | bash

# Или через пакетные менеджеры
# Debian/Ubuntu
curl -1 https://packages.timber.io/vector/latest/setup/deb.txt | sudo bash
sudo apt install vector

# RHEL/CentOS
curl -1 https://packages.timber.io/vector/latest/setup/rpm.txt | sudo bash
sudo yum install vector
```

Статический бинарник также доступен в архивах на [странице загрузки](https://vector.dev/download) для x86_64, ARM64 и ARMv7.

### Управление через systemd

Vector поставляется с unit-файлом `/etc/systemd/system/vector.service`:

```ini
[Unit]
Description=Vector
After=network.target
After=syslog.target

[Service]
Type=notify
ExecStart=/usr/bin/vector --config /etc/vector/vector.yaml --watch-config
Restart=always
User=vector
Group=vector
Environment=VECTOR_LOG=info

[Install]
WantedBy=multi-user.target
```

Основные команды:

```bash
systemctl daemon-reload                    # После изменения unit-файла
systemctl enable vector                  # Автозапуск при загрузке
systemctl start vector                   # Запуск
systemctl status vector                  # Статус
systemctl restart vector                 # Перезапуск (с потерей буферов)
systemctl reload vector                  # Hot reload (SIGHUP, без потери буферов)
journalctl -u vector -f                # Следить за логами в реальном времени
```

**Важно:** `systemctl reload` отправляет `SIGHUP`, что сохраняет буферы и не приводит к потере данных. `systemctl restart` останавливает и запускает заново — используйте только при обновлении бинаря или изменении системных настроек.

**Security hardening:** для production-развёртываний на bare-metal/ВМ добавьте systemd drop-in с `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp`, `LimitNOFILE` и т.д. — см. [Vector Security — Systemd Hardening](./vector_security.md#systemd-hardening).

---

## Операции и команды

### CLI инструменты

Vector предоставляет набор CLI-утилит для отладки, валидации и мониторинга:

*   **`vector validate`** — валидация конфигурации перед запуском. Заменяет устаревшую командду `vector check`. Выходной код `0` при успехе, `78` при ошибке. Флаги:
    ```bash
    vector validate /etc/vector/vector.yaml
    vector validate --config /etc/vector/*.yaml  # wildcard
    vector validate --no-environment            # пропустить проверки окружения
    vector validate --deny-warnings             # предупреждения → ошибки
    ```

*   **`vector tap`** — интерактивный просмотр событий на любом этапе конвейера (аналог `tcpdump` для логов). Подключается к внутреннему gRPC API.
    ```bash
    vector tap parse_log                      # события на выходе из transform
    vector tap parse_log.dropped              # события в DLQ
    vector tap --inputs-of 'sink_*'           # события НА входе sink
    vector tap --duration_ms 5000             # ограничить время выборки
    ```

*   **`vector top`** — визуализация топологии и метрик в реальном времени. Показывает `Events Out`, `Errors`, `Buffer Size` для каждого компонента.
    ```bash
    vector top                                # локальный экземпляр
    vector top --url 127.0.0.1:8686          # удалённый экземпляр
    vector top --components 'source_*'       # фильтр по компонентам
    ```

*   **`vector vrl`** — выполнение и тестирование VRL-выражений. Принимает программу как позиционный аргумент (не `--expression`).
    ```bash
    echo '{"message":"hello"}' | vector vrl '. = parse_json!(.message)'
    vector vrl --input test.json --program script.vrl
    vector vrl '.foo = true'                   # установить поле foo = true
    ```

*   **`vector graph`** — визуализация топологии в DOT-формате (GraphViz).
    ```bash
    vector graph --config /etc/vector/vector.yaml | dot -Tsvg > graph.svg
    ```

*   **`vector test`** — запуск unit-тестов конфигурации (секция `[[tests]]`).
    ```bash
    vector test /etc/vector/vector.yaml
    vector test --config-dir /etc/vector/
    ```

*   **`vector generate`** — генерация шаблона конфигурации для типового пайплайна.
    ```bash
    vector generate stdin/remap,filter,console
    ```

*   **`vector list`** — список доступных компонентов (sources, transforms, sinks).

### Внутренний API

Начиная с v0.55.0 внутренний API Vector полностью перешел с GraphQL на gRPC (tonic/HTTP2). REST API для health checks доступен по прежнему через HTTP/1.1 на том же порту.

*   **Включение:** `api.enabled = true` в конфигурации.
*   **Адрес:** `127.0.0.1:8686` по умолчанию (настраивается через `api.address`). Единый порт для gRPC и HTTP `/health`.
*   **Использование:** `vector top` и `vector tap` подключаются к этому API. Поддерживается gRPC reflection (используйте `grpcurl`).
*   **Безопасность:** аутентификация не поддерживается — включать только в изолированных средах (локальная машина или `iptables` на хосте). `/health` возвращает `{"ok":true}` и используется для systemd liveness/readiness проб.
*   **Health endpoint:**
    ```bash
    curl -s http://127.0.0.1:8686/health
    # → {"ok":true}
    ```

### Наблюдаемость и уровни логов

Vector настраивает свои логи через переменную `VECTOR_LOG` или флаги командной строки:

| Флаг | Уровень |
| :--- | :--- |
| `-v` | debug |
| `-vv` | trace |
| (по умолчанию) | info |
| `-q` | warn |
| `-qq` | error |
| `-qqq` | off (логи отключены) |

```bash
# Перехват логов Vector через systemd
journalctl -u vector -n 50 -p err --no-pager

# Отладка VRL-трансформации с trace-логами
vector --config vector.yaml -vv 2>&1 | grep 'remap'
```

### Ключевые внутренние метрики

Vector экспортирует подробные метрики о состоянии каждого компонента через источник `internal_metrics`. Для SRE эти метрики — основа для алертов и capacity planning. Полный каталог метрик доступен на [странице monitoring](https://vector.dev/docs/administration/monitoring/).

| Метрика | Описание | Использование |
| :--- | :--- | :--- |
| `component_errors_total{error_type="..."}` | Счётчик ошибок по типу (`parse_failed`, `confinement_failed`, `sink_request_failed`) | Алерт на рост ошибок |
| `component_received_events_total` / `component_sent_events_total` | Входящие и исходящие события компонента | Выявление узких мест |
| `component_latency_seconds` | Время обработки события (bucket-гистограмма) | Профилирование медленных трансформов |
| `component_buffer_*` | Состояние буферов: размер в байтах, количество событий, utilization | Прогноз заполнения disk buffer |
| `vector_build_info` | Версия Vector, коммит, дата сборки | Inventory, проверка совместимости |

---

## Обеспечение надёжности

### Backpressure и буферизация

Backpressure — ключевой механизм устойчивости пайплайна. Если sink не справляется с нагрузкой, Vector автоматически замедляет источники через адаптивную concurrency (ARC), а не отбрасывает данные.

**Типы буферов:**

*   **`memory`** (по умолчанию) — быстрый, но данные теряются при аварийном перезапуске (`SIGKILL`, OOM). Подходит для не критичных пайплайнов.
*   **`disk`** — персистентный сброс на диск с WAL, гарантия **at-least-once** delivery. Рекомендуется для критичных пайплайнов (Kafka → Loki, аудит логи).

```toml
[sinks.loki.buffer]
type = "disk"
max_size = 1073741824  # 1 GiB на sink
when_full = "block"    # Блокировать источник при переполнении
```

**Взаимодействие с backpressure:** если sink не справляется, ARC автоматически уменьшает `request.concurrency` для компонента, замедляя источники (например, Kafka consumer). Мониторинг состояния буферов — через метрики `component_buffer_*`.

### Гарантии доставки

| Свойство | Описание |
| :--- | :--- |
| At-least-once | Гарантировано при использовании `disk` buffer + acknowledgements. Могут быть дубли при сбое после записи, но до коммита. |
| At-most-once | По умолчанию без disk buffer. Используется для не критичных трасс/metric. |
| Acknowledgment | Sink поддерживает `acknowledgements.enabled = true` — событие удаляется из буфера только после подтверждения приёмника. |

---

## Практические сценарии

Детальные конфигурации вынесены в отдельный файл: **[Practical Scenarios](./practical_scenarios.md)**.

### Сценарий 1: Замена rsyslog на Vector для сбора системных логов

**Задача:** На bare-metal сервере или ВМ заменить rsyslog на Vector для централизованного сбора логов systemd-journald, auth.log и nginx access_log с первичной нормализацией.

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
# Нормализация уровня логирования через syslog severity
if exists(.priority) {
  .level = to_syslog_level!(.priority)
}
# Удаление временных полей журнала
del(._PID, ._SYSTEMD_UNIT)
'''

[sinks.loki]
type = "loki"
inputs = ["normalize"]
endpoint = "http://loki:3100"
encoding.codec = "json"

[sinks.loki.buffer]
type = "disk"
max_size = 1073741824
when_full = "block"
```

**Проверка:**
```bash
vector validate --config /etc/vector/vector.yaml
# → код возврата 0

vector tap normalize
# → {"level":"info","message":"Started","source":"journald",...}
```

### Сценарий 2: Сбор host_metrics и отправка в Prometheus

**Задача:** Собрать системные метрики CPU, памяти, диска и сетевых интерфейсов с серверов и экспортировать в Prometheus.

**Решение:** Использовать source `host_metrics` для сбора метрик хоста и sink `prometheus_remote_write` для отправки.

```toml
[sources.host]
type = "host_metrics"
scrape_interval_secs = 15
collect_cpu = true
collect_memory = true
collect_disk = true
collect_network = true
collect_filesystem = true
collect_uptime = true

[sinks.prom]
type = "prometheus_remote_write"
inputs = ["host"]
endpoint = "http://prometheus:9090/api/v1/write"
```

**Проверка:**
```bash
curl -s http://localhost:9090/api/v1/query?query=up | jq .
# → Метрики Vector присутствуют в Prometheus
```

### Сценарий 3: Защита хранилища через throttle + disk buffer

**Задача:** Ограничить скорость отправки логов в Loki, чтобы хранилище не перегружалось при всплесках трафика, и при этом не терять события.

**Решение:** Transform `throttle` ограничивает количество событий в единицу времени, disk buffer защищает от потерь при переполнении.

```toml
[transforms.limit_rate]
type = "throttle"
inputs = ["app_logs"]
key = "$$.hash"          # Группируем по хешу события
limit = 1000             # Максимум 1000 событий в секунду
period = 1s              # Окно сброса счётчика

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
field = "status"
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
vector tap normalize
# → {"message":"GET /healthz 200","status":"200",...}

# 3. Инспекция ошибок парсинга (reroute_dropped)
vector tap normalize.dropped
# → {"message":"invalid json","error":"parse error",...}
```

---

## Устранение неполадок

### Типичные ошибки и диагностика

#### VRL-ошибки компиляции

**Симптом:** Vector не стартует с ошибкой компиляции VRL-программы.

**Диагностика:**
1.  Запустите `vector validate /etc/vector/vector.yaml` — ошибка укажет точную позицию.
2.  Протестируйте VRL отдельно: `echo '{}' | vector vrl '<программа>'`.

**Частые причины:**
*   `parse_json!` или `parse_regex!` с `!` (fallible) без обработки ошибки — VRL abort при ошибке парсинга. Используйте `?` для graceful handling:
    ```vrl
    # Безопасный парсинг с fallback
    parsed, err = parse_json(.message)
    if err != null {
      .message = string!(.message)
    } else {
      . = parsed
    }
    ```
*   Несоответствие типов — VRL использует строгую типизацию. Применяйте `to_int!`, `to_string!`, `to_float!` для приведения типов.
*   `to_int!(.priority)` вместо `to_syslog_level!(.priority)` — если нужен syslog severity, используйте `to_syslog_level`.

#### События "пропадают" между трансформами

**Симптом:** `component_received_events_total` на входе sink меньше, чем на выходе source.

**Диагностика:**
```bash
# 1. Проверить dropped events на каждом этапе
vector tap normalize.dropped    # события, не прошедшие VRL
vector tap filter.dropped      # события, отфильтрованные filter

# 2. Проверить метрики backpressure
vector top --human-metrics
# → Обратите внимание на Buffer Size и Errors колонки
```

#### Disk buffer переполняется

**Симптом:** `component_buffer_fill_fraction` приближается к 1.0, `when_full = "block"` начинает задерживать источники.

**Решение:**
1.  Увеличьте `max_size` буфера.
2.  Проверье скорость sink через `component_latency_seconds`.
3.  Увеличьте `request.concurrency` для sink или настройте `request.rate_limit_*`.

#### Hot reload не работает

**Симптом:** После `kill -HUP $(pidof vector)` конфигурация не обновляется.

**Диагностика:**
1.  Проверьте, что процесс запущен с `--watch-config` или получает `SIGHUP`:
    ```bash
    ps aux | grep vector
    # → vector --config /etc/vector/vector.yaml
    ```
2.  Проверьте логи на предмет ошибок валидации:
    ```bash
    journalctl -u vector -n 20 --no-pager
    ```
3.  Запустите валидацию вручную: `vector validate /etc/vector/vector.yaml`

### Метрики для алертинга

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| `component_errors_total{error_type="parse_failed"}` | > 0 в течение 5 мин | Проверить формат входных данных, VRL-программу |
| `component_errors_total{error_type="sink_request_failed"}` | > 0 в течение 1 мин | Проверить доступность sink, сеть, TLS |
| `component_buffer_fill_fraction > 0.9` | > 0.9 в течение 1 мин | Увеличить `max_size` буфера или масштабировать sink |
| `component_latency_seconds{quantile="0.95"} > 5` | > 5 сек | Профильировать VRL-код, упростить трансформацию |
| `process_cpu_usage > 0.8` | > 0.8 в течение 10 мин | Добавить vCPU или распределить нагрузку |

---

## Лучшие практики

### Архитектурные принципы

1.  **Разделяйте роли Agent и Aggregator.** Agent (на хосте) собирает и делает first-pass parsing. Aggregator обрабатывает, обогащает и отправляет. Это упрощает масштабирование и отладку.
2.  **Используйте disk buffer для критичных пайплайнов.** Memory buffer теряет данные при `SIGKILL`/OOM. Disk buffer с `when_full = "block"` гарантирует at-least-once delivery.
3.  **Нормализуйте на источнике.** Приводите все логи к единому формату (JSON с полями `timestamp`, `level`, `message`, `source`) на этапе VRL-трансформации, а не на этапе sink.

### Безопасность и харднинг

1.  **Ограничение шаблонов маршрутизации (Template Confinement, v0.57):** Sinks, принимающие `{{ field }}` в шаблонах маршрутизации (HTTP-заголовки, имена таблиц/стримов), отклоняют шаблоны без буквального префикса при старте — предотвращает path traversal и инъекции. HTTP-family шаблоны не могут содержать `?`/`#`. Опт-аут: `dangerously_allow_unconfined_template_resolution: true`.
2.  **Переменные окружения (v0.57+):** Интерполяция `${VAR}` в конфигурации **отключена по умолчанию**. Для включения требуется явный флаг:
    ```bash
    vector --config /etc/vector/vector.yaml --dangerously-allow-env-var-interpolation
    # или
    export VECTOR_DANGEROUSLY_ALLOW_ENV_VAR_INTERPOLATION=true
    ```
    Предпочтительнее: используйте secret-провайдеры или переменные с префиксом для секретов.
3.  **TLS для sink:** Для всех sink, взаимодействующих с внешними системами (Elasticsearch, Kafka, OpenSearch), настраивайте TLS (`tls.*`) и аутентификацию (`auth.strategy = "basic"` для HTTP, SASL для Kafka).
4.  **Внутренний API:** не имеет аутентификации — включать только в изолированных средах (локальная машина, `iptables`). Используйте `api.enabled = false` в production, включайте только для `vector top`/`vector tap`.

### Производительность и capacity planning

*   **Пропускная способность** (оценка, из официальной документации):
    | Тип данных | Пропускная способность |
    | :--- | :--- |
    | Unstructured log event (~256 bytes) | ~10 MiB/s/vCPU |
    | Structured log event (~768 bytes) | ~25 MiB/s/vCPU |
    | Metric event (~256 bytes) | ~25 MiB/s/vCPU |
    | Trace span event (~1 KB) | ~25 MiB/s/vCPU |
*   **Рекомендуемый минимум:** 2 vCPU для Agent (на хосте), 4+ vCPU для Aggregator. ARM64 обычно эффективнее по соотношению цена/производительность (большие кэши L2/L3).
*   **Память:** 2 GiB на vCPU в качестве стартовой точки. Увеличьте при большом количестве sink (in-memory batching).
*   **Диск:** для disk buffer — объёма на 10 минут данных на каждый vCPU. SSD достаточно (I/O редко является узким местом).

### VRL-оптимизация

1.  **Компиляция в Rust:** VRL-программы компилируются в нативный код при старте. Избегайте `to_regex()` в hot-path (компиляция regex каждый раз); используйте литералы `r'pattern'` или `parse_regex!` с константой.
2.  **Error handling:** Используйте `!` (abort) только для критичных ошибок. Для не критичных используйте `try`-синтаксис: `parsed, err = parse_json(.message)`.
3.  **Avoid unnecessary copies:** VRL использует zero-copy для большинства операций. Операции вроде `.field = .other_field` копируют ссылку, а не данные.

### Очистка и обслуживание

1.  **Ротация логов Vector:** Используйте `logrotate` для файлов `vector.log` (если пишете в файл) или `journalctl`'s built-in ротацию.
2.  **Очистка disk buffer:** При остановке с `--no-graceful-shutdown-limit` (SIGKILL) буфер может повредиться. Всегда используйте graceful shutdown (SIGTERM/SIGINT с ожиданием).
3.  **Архивирование конфигурации:** Храните конфиги в version control. Используйте `vector test` для CI/CD проверки перед деплоем.
4.  **Обновление:** Поддерживается только последняя minor-версия. Планируйте обновление каждые 6 недель (stable release cadence). Перед обновлением проверьте release notes на breaking изменения.

## Дополнительная информация

### Версии и поддержка

Vector поддерживает только последнюю minor-версию (в 0.x серии). Stable releases выходят каждые 6 недель. Проверяйте [release notes](https://github.com/vectordotdev/vector/blob/master/RELEASES.md) перед обновлением.

### Конфигурационные форматы

| Формат | Поддержка | Рекомендации |
| :--- | :--- | :--- |
| TOML | ✅ | Рекомендуется (строгая типизация, комментарии) |
| YAML | ✅ | Удобен для CI/CD, поддерживает anchors/aliases |
| JSON | ✅ | Автоматическая генерация, но тяжел для чтения |

Множественные файлы конфигурации можно объединять через `--config-dir` или wildcard `--config /etc/vector/*.yaml`.

### См. также

*   **VRL:** Детальное описание языка трансформации — **[VRL Language](./vrl_language.md)**.
*   **Практические пайплайны:** Kafka → OpenSearch, адаптивное сэмплирование, ClickHouse + Arrow — **[Practical Scenarios](./practical_scenarios.md)**.
*   **Безопасность и харднинг:** TLS, mTLS, аутентификация, управление секретами, systemd hardening — **[Vector Security](./vector_security.md)**.
*   **Надёжность:** Retry policy, DLQ, circuit breaker, rate limiting, acknowledgements — **[Vector Reliability](./vector_reliability.md)**.
*   **Production deployment:** Kubernetes DaemonSet/Deployment, HA, health checks, resource limits, upgrade/backup — **[Vector Production Deployment](./vector_production_deployment.md)**.
*   **Производительность:** Profiling (pprof), benchmark, capacity planning — **[Vector Performance](./vector_performance.md)**.
*   **Loki:** Архитектура хранилища логов — **[Loki Overview](../Loki/loki_overview.md)**.
*   **Наблюдаемость:** Логи, метрики, трейсы — **[Четыре столпа наблюдаемости](../Concepts/Observability_and_Monitoring/four_pillars_of_observability.md)**.
*   **Мета-мониторинг:** Алерты и метрики для мониторинга пайплайна логов — **[Meta-monitoring](../Concepts/Observability_and_Monitoring/meta-monitoring.md)**.
*   **Документация:** [vector.dev](https://vector.dev/docs/) — официальная документация, справочник функций VRL и CLI.
