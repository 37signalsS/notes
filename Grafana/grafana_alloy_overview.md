# Grafana Alloy — обзор

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), пришедший на смену Grafana Agent. Построен на базе **OpenTelemetry Collector**, но оптимизирован для работы со стеком LGTM (Loki, Grafana, Tempo, Mimir). Ключевой особенностью является использование декларативного языка конфигурации River.

Распространяется в виде единого бинарного файла `alloy`, поддерживает Linux (amd64/arm64), macOS и Windows. Может работать как systemd-сервис, Docker-контейнер или разворачиваться в Kubernetes через **Grafana Alloy Operator**. В отличие от Grafana Agent, у Alloy нет «static/flow» режимов — он всегда работает в режиме Flow и описывается на языке River.

**River** — язык конфигурации, вдохновленный HCL, который позволяет описывать конвейеры обработки данных (pipelines) в виде направленного графа компонентов. Поддерживает динамическое обновление конфигурации без полной остановки агента.

Конфигурация состоит из компонентов. Block-компоненты описываются как `тип.имя "метка" { ... }`, attribute-компоненты (например, `sys.env`, `const`, `remote.http`) — без тела блока. У каждого компонента есть входы (**arguments**) и выходы (**exports**), которые связываются между собой через точечную нотацию `компонент.поле` (например, `discovery.file.local_files.targets`). Данные текут только вдоль явно указанных связей — глобальных настроек не существует.

**OTLP (OpenTelemetry Protocol)** — стандартный протокол, используемый Alloy как основной транспорт для взаимодействия с современными системами наблюдаемости. Поддерживает два транспорта: gRPC (порт `4317`) и HTTP (порт `4318`).

**WAL (Write-Ahead Log)** — буфер на диске в каталоге `/var/lib/alloy`, обеспечивающий надёжную доставку телеметрии (семантика at-least-once) при временной недоступности бэкенда. Alloy накапливает неотправленные данные в WAL и повторяет попытки отправки после восстановления связи.

### Статус агентов и миграция

| Агент | Статус | Конец поддержки (EOL) |
| :--- | :--- | :--- |
| **Promtail** | Устарело (Deprecated) | Весна 2026 |
| **Grafana Agent (static/flow)** | Устарело (Deprecated) | Октябрь 2025 |
| **Grafana Alloy** | **Актуальный стандарт** | — |

---

## Базовые концепции

### Ключевые возможности Alloy

| Возможность | Техническое описание |
| :--- | :--- |
| **Унифицированный сбор** | Заменяет связку `node_exporter`, `promtail` и `otel-collector` одним бинарным файлом. |
| **Компонентная модель (DAG)** | Каждый блок конфигурации — это компонент с входами (arguments) и выходами (exports). |
| **Авто-инструментирование (eBPF)**| Сбор сетевых метрик и трейсов на уровне ядра Linux без изменения кода приложений. |
| **Кластеризация** | Встроенный механизм распределения нагрузки между узлами Alloy для масштабирования сбора данных. |
| **Native Prometheus** | Прямое использование кода Prometheus для сбора (scraping) и релейблинга (relabeling). |
| **Debug UI** | Визуальный интерфейс на порту `12345` для анализа состояния графа и поиска ошибок в реальном времени. |
| **Метрики здоровья и отладки** | Собственные метрики агента и компонентов доступны на `:12345/metrics`; эндпоинты `/live`, `/ready`. |
| **Надёжная доставка (WAL)** | Буферизация на диске (`/var/lib/alloy`) с повторными попытками отправки при сбоях бэкенда. |

### Архитектура и компонентная модель

Alloy строит направленный ациклический граф (DAG) из компонентов. Категории компонентов:

- `discovery.*` — обнаружение целей сбора (файлы, Docker, Kubernetes, Consul, файловые сервисы).
- `prometheus.*` — сбор и экспорт метрик (scrape, exporter.unix, exporter.docker, remote_write, relabel).
- `loki.*` — сбор, обработка и отправка логов (source.file, process, write).
- `otelcol.*` — приёмники, процессоры и экспортеры OpenTelemetry (receiver.otlp, exporter.otlp, receiver.ebpf).
- `tracing.*` / `profiling.*` — трассировки и профили.
- `remote.*`, `sys.*`, `local.file.*` — вспомогательные (внешние источники, окружение, файлы).

Принципы:

- Данные передаются только по явным связям через `forward_to` или аргументы вида `targets = ...`.
- Компонент пересоздаётся при изменении его блока во время динамической перезагрузки; неиспользуемые выходы игнорируются.
- Порядок загрузки определяется графом, а не позицией компонента в файле.

### Язык конфигурации River

River ориентирован на связность. Вместо глобальных настроек каждый компонент явно указывает, куда передавать данные через аргумент `forward_to`.

**Пример архитектуры пайплайна (сбор логов):**

```hcl
// 1. Обнаружение локальных лог-файлов
discovery.file "local_files" {
  path_targets = [{
    __path__ = "/var/log/*.log",
  }]
}

// 2. Чтение обнаруженных файлов
loki.source.file "local_logs" {
  targets = discovery.file.local_files.targets
  forward_to = [loki.write.to_loki_cloud.receiver]
}

// 3. Отправка логов в Loki
loki.write "to_loki_cloud" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
  external_labels = {
    source = "grafana-alloy",
  }
}
```

Синтаксис конфигурации проверяется утилитами `alloy fmt` (форматирование) и `alloy lint` (статическая проверка графа). Ошибки парсинга указывают на файл и строку.

### Потоковая обработка данных (stages и пайплайны)

Обработка выполняется внутри компонентов-процессоров:

- `loki.process` применяет **stages** к лог-строкам: `stage.regex` (извлечение полей), `stage.labels`/`stage.label_drop` (лейблы), `stage.timestamp` (время), `stage.multiline` (склейка многострочных логов), `stage.metrics` (счётчики из логов).
- `prometheus.relabel` и `metric_relabel_configs` — фильтрация и переименование метрик до отправки.
- `otelcol.*` процессоры (например, `otelcol.processor.batch`) — батчинг и трансформация OTLP.

Пример извлечения `trace_id` из логов и проставления его как лейбла `traceID` приведён в Сценарии 2.

### Высокая доступность и масштабирование (Clustering)

Alloy поддерживает **Clustering** — режим, в котором несколько экземпляров агента объединяются в логический кластер. Это позволяет:

- **Распределять цели сбора (Scrape Targets)**: каждый узел берет на себя часть нагрузки.
- **Обеспечивать отказоустойчивость**: при падении одного узла его цели перераспределяются между оставшимися.
- **Контролировать состояние**: через компонент `cluster` (блок в конфигурации) с включённым `enable_clustering = true`.

```hcl
cluster {
  enabled           = true
  name              = "alloy-prod"
  advertise_address = sys.env("NODE_IP") + ":9094"
  join_addresses    = ["alloy-0:9094", "alloy-1:9094", "alloy-2:9094"]
  gossip_interval    = "2s"
}
```

Кластер использует gossip на порту `9094`. Распределение целей поддерживают компоненты `prometheus.scrape`, `loki.source.*` и ряд других; остальные компоненты выполняются независимо на каждом узле.

### Надёжность доставки: WAL и повторные попытки

Alloy буферизирует исходящие данные в WAL (каталог `storage.path`, по умолчанию `/var/lib/alloy`). Если бэкенд недоступен, данные накапливаются на диске и отправляются повторно после восстановления связи. Это даёт семантику **at-least-once** (возможны дубликаты при сбоях). `prometheus.remote_write` и `loki.write` имеют встроенные очереди и параметры повтора. WAL должен размещаться на постоянном томе — при его потере неотправленная телеметрия теряется.

### Debug UI и метрики агента

Debug UI доступен по умолчанию на порту `12345`. Полезные эндпоинты:

- `GET /live` — проверка живости (возвращает `Healthy`).
- `GET /ready` — готовность к приёму трафика.
- `GET /metrics` — метрики агента и всех компонентов в формате Prometheus (префиксы `alloy_*`, `prometheus_*`, `loki_*`, `otelcol_*`).
- `GET /component/<имя>` — состояние конкретного компонента.
- `GET /graph` — визуализация DAG графа с цветовой индикацией ошибок.

Собственные метрики агента рекомендуется скрапить в Prometheus (см. Сценарий 6), чтобы мониторить здоровье сборщика.

### Безопасность: TLS, mTLS и секреты

Компоненты поддерживают блок `tls { ... }` (поля `insecure`, `ca_file`, `cert_file`, `key_file`, `server_name`) для шифрования и взаимной аутентификации (mTLS) при отправке в OTLP/remote_write/HTTP.

Секреты не должны храниться в открытом виде в конфигурации. Варианты:

- Интерполяция переменных окружения: `sys.env("LOKI_PASSWORD")` (подставляются при загрузке графа).
- Шифрование литералов в конфиге: `alloy secrets encrypt` создаёт блок, читаемый только с ключом.
- Монтирование секретов из Docker/Kubernetes Secret Volume в контейнер.

Монтируйте `config.alloy` в контейнер в режиме только для чтения (`:ro`).

---

## Практические сценарии

### Предварительные требования

- **ОС:** Linux (amd64/arm64), macOS или Windows.
- **Версия:** актуальная — v1.18.x (на август 2026 года, см. `docker_compose_setup.md`).
- **Порты:** `4317`/`4318` (OTLP), `12345` (Debug UI и `/metrics`), `9094` (gossip кластеризации, если включена).
- **Хранилище:** каталог `/var/lib/alloy` (WAL) с правами записи пользователю `alloy`; в Docker — монтировать постоянный том.
- **Сеть:** исходящий доступ к бэкендам (Loki `:3100`, Tempo `:4317`, Mimir/Prometheus `:9090`/`:9099`).
- **eBPF (опционально):** только Linux с поддержкой BTF (ядро ≥ 4.18, рекомендуется ≥ 5.8).
- **Docker-логи (опционально):** доступ к `/var/run/docker.sock` — `sudo setfacl -m u:alloy:r /var/run/docker.sock` или добавление пользователя `alloy` в группу `docker`.

### Сценарий 1: Использование eBPF для сетевой наблюдаемости

Компонент `otelcol.receiver.ebpf` позволяет получать данные о задержках и сетевых соединениях без внесения изменений в приложение.

```hcl
otelcol.receiver.ebpf "network_telemetry" {
  network_interface = "eth0"
  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [otelcol.exporter.prometheus.mimir.input]
  }
}
```

**Требования:** Linux с BTF. **Валидация:** убедиться, что метрики появились — `curl -s localhost:12345/metrics | grep alloy_ebpf`; в Debug UI (`/graph`) проверить, что узел `otelcol.receiver.ebpf.network_telemetry` не в состоянии error. В логах Alloy должна появиться строка инициализации eBPF-приёмника.

### Сценарий 2: Full-Stack Observability для PostgreSQL

Комплексный пример сбора всех сигналов от БД и приложения, их корреляция через `trace_id`.

```hcl
// --- 1. Сбор трейсов ---
otelcol.receiver.otlp "traces_receiver" {
  grpc { endpoint = "0.0.0.0:4317" }
  output { traces = [otelcol.exporter.otlp.traces_exporter.input] }
}

otelcol.exporter.otlp "traces_exporter" {
  client { endpoint = "tempo:4317"; tls { insecure = true } }
}

// --- 2. Сбор логов с извлечением trace_id ---
discovery.file "log_files" {
  path_targets = [{
    __path__ = "/var/lib/postgresql/data/log/postgresql.log",
    "job" = "postgres-logs",
  }]
}

loki.source.file "read_logs" {
  targets = discovery.file.log_files.targets
  forward_to = [loki.process.add_trace_id.receiver]
}

loki.process "add_trace_id" {
  stage.regex {
    expression = ".*traceparent='00-(?P<trace_id>[a-f0-9]{32})-[a-f0-9]{16}-01'.*"
    source     = "log_line"
  }
  stage.label_drop {
    values = { "trace_id" = `^(?P<value>.*)$` }
    target_label = "traceID"
  }
  forward_to = [loki.write.loki_writer.receiver]
}

loki.write "loki_writer" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}

// --- 3. Сбор метрик ---
prometheus.scrape "postgres_metrics" {
  targets = [{ "__address__" = "postgres_exporter:9187", "job" = "postgres" }]
  forward_to = [prometheus.remote_write.mimir.receiver]
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Валидация:** в Tempo найти трейсы от `traces_exporter`; в Loki — логи с лейблом `job="postgres-logs"` и полем `traceID`; в Mimir — метрики `pg_*` от job `postgres`. Проверка доставки через агента: `curl -s localhost:12345/metrics | grep tempo` и `grep mimir`. Ошибки искать в логах: `journalctl -u alloy | grep -i error` (или `docker logs monitoring-alloy | grep -i error`).

### Сценарий 3: Миграция с помощью встроенного конвертера

Alloy включает инструменты для быстрого перехода с устаревших агентов.

1. **Конвертация** (поддерживаемые форматы источника: `promtail`, `prometheus`, `agent` — Grafana Agent static/flow, `telegraf`, `otelcol`):
   ```bash
   alloy convert --source-format=promtail --output=config.alloy promtail-config.yaml
   alloy convert --source-format=agent   --output=config.alloy agent-config.yaml
   ```
2. **Проверка синтаксиса** перед деплоем:
   ```bash
   alloy lint config.alloy
   # → config.alloy: no issues found
   ```
3. **Проверка графа без запуска** (`--dry-run` загружает и валидирует граф, затем завершается):
   ```bash
   alloy run --dry-run /etc/alloy/config.alloy
   ```

### Сценарий 4: Установка и первый запуск

**Вариант A — Docker Compose (рекомендуется для быстрого старта):**

```yaml
services:
  alloy:
    image: grafana/alloy:v1.18.1
    container_name: monitoring-alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - alloy_data:/var/lib/alloy
      - /var/run/docker.sock:/var/run/docker.sock:ro
    ports:
      - "12345:12345"
      - "4317:4317"
    restart: unless-stopped

volumes:
  alloy_data:
```

**Вариант B — бинарный файл (systemd):**

```bash
curl -Lo alloy.tar.gz https://github.com/grafana/alloy/releases/download/v1.18.1/alloy-linux-amd64.tar.gz
tar xzf alloy.tar.gz
sudo mv alloy /usr/local/bin/
sudo useradd -rs /bin/false alloy
sudo alloy run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
```

**Валидация первого запуска:**

```bash
# Живость агента
curl -fsS http://localhost:12345/live
# → Healthy

# Загрузка всех модулей графа (в логах)
docker logs monitoring-alloy --tail 20 | grep -i "all modules loaded"

# Проверка синтаксиса/формата
alloy fmt /etc/alloy/config.alloy   # без вывода при корректном формате
```

Глубокая установка в Kubernetes (Helm, Operator, DaemonSet/Deployment) описана в выделенном файле — см. «См. также».

### Сценарий 5: Кластеризация и распределение нагрузки

Добавьте блок `cluster` в конфигурацию и включите распределение целей у компонентов сбора:

```hcl
cluster {
  enabled           = true
  name              = "alloy-prod"
  advertise_address = sys.env("NODE_IP") + ":9094"
  join_addresses    = [sys.env("ALLOY_PEERS")]
  gossip_interval    = "2s"
}

prometheus.scrape "distributed" {
  clustering {
    enabled = true
  }
  targets = [{ "__address__" = "target:9100", "job" = "distributed" }]
  forward_to = [prometheus.remote_write.mimir.receiver]
}
```

**Валидация:** `curl -s localhost:12345/metrics | grep alloy_cluster_peers` показывает число узлов; в Debug UI (`/graph`) отображаются подключённые peers. При падении узла его цели автоматически перераспределяются.

### Сценарий 6: Сбор метрик хоста и Docker-контейнеров

Alloy заменяет Node Exporter и самостоятельно собирает метрики хоста и контейнеров (см. также `grafana_with_graphite_collectd.md`).

```hcl
// Метрики хоста
prometheus.exporter.unix "host" { }

// Обнаружение контейнеров Docker
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Сбор метрик хоста
prometheus.scrape "host_metrics" {
  targets        = prometheus.exporter.unix.host.targets
  forward_to     = [prometheus.remote_write.mimir.receiver]
  scrape_interval = "15s"
}

// Сбор метрик контейнеров
prometheus.scrape "container_metrics" {
  targets        = discovery.docker.containers.targets
  forward_to     = [prometheus.remote_write.mimir.receiver]
  scrape_interval = "15s"
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Валидация:** `curl -s localhost:12345/metrics | grep 'up{'` показывает цели со статусом; в Prometheus появляются target-ы с job `host`/`containers`; `docker logs monitoring-alloy | grep -i error` пуст. Для `prometheus.exporter.unix` в контейнере может потребоваться доступ к `/proc` и `/sys` (монтирование или привилегии).

### Сценарий 7: Безопасная передача секретов

Интерполяция переменных окружения (подставляются при загрузке графа):

```hcl
loki.write "secure" {
  endpoint {
    url = sys.env("LOKI_URL")
    basic_auth {
      username = sys.env("LOKI_USER")
      password = sys.env("LOKI_PASSWORD")
    }
  }
  external_labels = { source = "grafana-alloy" }
}
```

Для Docker задайте переменные через `environment:` сервиса или смонтированный файл `docker-compose.yml` `secrets:`. Для шифрования литералов в самом файле используйте `alloy secrets encrypt`.

**Валидация:** `alloy run` успешно считывает переменные (секрет не присутствует в открытом виде в репозитории); проверка доставки — появление данных в бэкенде и отсутствие ошибок аутентификации в логах.

---

## Дополнительная информация

### Сравнение Alloy и OpenTelemetry Collector

| Характеристика | Grafana Alloy | OTel Collector (Upstream) |
| :--- | :--- | :--- |
| **Язык** | River (Динамический граф) | YAML (Статический стек) |
| **Сбор метрик** | Нативный код Prometheus (Scrape/Relabel) | `prometheusreceiver` (Legacy/Contrib) |
| **Фокус** | Экосистема Grafana + OTel | Универсальный стандарт |
| **Отладка** | Потоковая визуализация в UI | Текстовые логи и метрики |

### Преимущества и ограничения

#### Преимущества
- **Консолидация:** уменьшение количества агентов на хосте снижает нагрузку на CPU/RAM и упрощает патчинг.
- **Прозрачность:** Debug UI позволяет мгновенно увидеть, почему метрика не дошла до хранилища (фильтрация или ошибка соединения).
- **Готовность к будущему:** Alloy является фундаментом для технологий **Adaptive Metrics** и **Profiles-to-Traces**.

#### Ограничения
- **Порог входа:** River требует обучения и понимания принципов экспорта/импорта данных между компонентами.
- **Потребление ресурсов:** в очень простых сценариях (только сбор логов) Alloy может быть тяжелее, чем Promtail.

### Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Граф не загружается / ошибка парсинга | Синтаксическая ошибка River, неверная точечная нотация | `alloy lint config.alloy`; сообщение об ошибке с номером строки | Исправить связи `forward_to`/`exports`; проверить `alloy fmt` |
| Компонент в состоянии error (нет доставки) | Бэкенд недоступен, неверный URL, отказ TLS | `curl` к бэкенду; логи `level=error`; красный узел в Debug UI | Проверить сеть, URL, блок `tls{}`; перезапустить граф |
| OTLP connection refused | Порт 4317/4318 закрыт или receiver не слушает | `ss -ltnp \| grep 4317` | Открыть порт, проверить `otelcol.receiver.otlp` |
| WAL растёт / диск заполняется | Бэкенд долго недоступен | Размер `/var/lib/alloy` | Каталог на отдельном томе; восстановить сеть до бэкенда |
| 429 / rate limit от Loki или Mimir | Превышение лимита приёма | Логи бэкенда, метрики `alloy_*` | Настроить `batch`/`queue`, дедупликацию, согласовать лимиты |
| Clustering split-brain / peers flapping | Нестабильный gossip, неверные `join_addresses` | `alloy_cluster_peers` метрика, логи gossip | Стабильные адреса `:9094`, корректный `gossip_interval` |
| Высокое потребление памяти | Большие пайплайны без батчинга | `alloy_process_resident_memory_bytes` | Добавить `otelcol.processor.batch`, ограничить параллелизм |
| eBPF не работает | Ядро без BTF / не Linux | `uname -a` | Использовать обычный receiver; обновить ядро (≥5.8) |
| Permission denied на `/var/lib/alloy` или docker.sock | Права пользователя `alloy` | Логи `permission denied` | `chown alloy` каталог; `setfacl -m u:alloy:r /var/run/docker.sock` |
| Изменения конфигурации не применились | Граф не перезагрузился (ошибка валидации) | Лог перезагрузки | `alloy lint`; при ошибке Alloy сохраняет предыдущий граф |

### Рекомендации по эксплуатации

- Фиксируйте версию (v1.18.x) в образах и манифестах.
- Монтируйте `config.alloy` в режиме только для чтения (`:ro`).
- Размещайте WAL (`/var/lib/alloy`) на постоянном томе и не теряйте его.
- Скрапьте собственные метрики Alloy (`:12345/metrics`) в Prometheus для мониторинга агента.
- Используйте Debug UI (`/graph`) для диагностики состояния графа.
- Прогоняйте `alloy fmt` и `alloy lint` в CI перед деплоем.
- Передавайте секреты через env/K8s Secrets/`alloy secrets`, не храните в репозитории.
- Один `config.alloy` на функцию; избегайте гигантских монолитных графов.
- Устанавливайте resource limits (memory/CPU) на контейнер или systemd-юнит.
- Начинайте с минимального пайплайна и расширяйте его по необходимости.

### Ограничения и особые случаи

- **Семантика at-least-once:** при сбоях возможны дубликаты метрик/логов/трасс.
- **Динамическая перезагрузка** пересоздаёт изменившиеся компоненты; in-memory состояние (локальные счётчики агрегаторов) сбрасывается.
- **eBPF** доступен только на Linux с BTF; на macOS/Windows не поддерживается.
- **Кластеризация** требует стабильной сети и явных `join_addresses`; авто-discovery peers ограничен.
- Один процесс Alloy строит **один глобальный граф** — несколько независимых графов в одном файле невозможны.
- При долгой недоступности бэкенда **WAL растёт неограниченно**, пока не восстановится связь.
- Порядок загрузки компонентов определяется графом, а не позицией в файле.

### Актуальность и ссылки

Информация актуальна на **август 2026 года**. Актуальная версия Alloy — **v1.18.x**. Основные направления развития: глубокая интеграция с **Grafana Alloy Operator** в Kubernetes и поддержка **OpenTelemetry Profiles**.

- [Официальный репозиторий GitHub](https://github.com/grafana/alloy)
- [Документация по компонентам River](https://grafana.com/docs/alloy/latest/reference/components/)
- [Установка в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md)

**См. также:** [Обзор Grafana](./grafana_overview.md), [OpenTelemetry Collector](../OpenTelemetry/opentelemetry_overview.md), [Установка Alloy в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md).
