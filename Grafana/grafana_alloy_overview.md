# Grafana Alloy — обзор

**Актуально для:** Grafana Alloy 1.20.x

## Определения

**Grafana Alloy** — универсальный агент для сбора телеметрии (метрики, логи, трассировки, профили), пришедший на смену Grafana Agent и Promtail. Построен на базе **OpenTelemetry Collector**, но оптимизирован для работы со стеком LGTM (Loki, Grafana, Tempo, Mimir/Pyroscope). Ключевая особенность — декларативный язык конфигурации, который в ранних версиях носил название River и сегодня называется **синтаксисом конфигурации Alloy (Alloy configuration syntax)**.

Распространяется как единый бинарный файл `alloy`, поддерживает Linux (amd64/arm64), macOS и Windows. Может работать как systemd-сервис, Docker-контейнер или разворачиваться в Kubernetes через Helm-чарт **Grafana Alloy** или **Grafana Alloy Operator**. В отличие от Grafana Agent, у Alloy нет режимов `static`/`flow` — он всегда описывается единым компонентным синтаксисом.

**Компоненты** — строительные блоки конфигурации. Block-компоненты описываются как `тип.имя "метка" { ... }` (например, `loki.write "local" { ... }`). У каждого компонента есть входы (**arguments**) и выходы (**exports**), которые связываются через точечную нотацию `компонент.поле` (например, `local.file_match.app_logs.targets`). Данные текут только вдоль явно указанных связей — глобальных настроек сбора не существует.

**OTLP (OpenTelemetry Protocol)** — стандартный протокол, используемый Alloy как основной транспорт взаимодействия с современными системами наблюдаемости. Поддерживает два транспорта: gRPC (порт `4317`) и HTTP (порт `4318`).

**WAL (Write-Ahead Log)** — буфер на диске в каталоге, задаваемом `--storage.path`, обеспечивающий надёжную доставку телеметрии (семантика at-least-once) при временной недоступности бэкенда: неотправленные данные накапливаются на диске и отправляются повторно после восстановления связи.

### Статус агентов и миграция

| Агент | Статус | Конец поддержки (EOL) |
| :--- | :--- | :--- |
| **Promtail** | Устарел (EOL) | 2 марта 2026 |
| **Grafana Agent (static/flow) и Agent Operator** | Устарели (EOL) | 1 ноября 2025 |
| **Grafana Alloy** | **Актуальный стандарт** | — |

Promtail и Grafana Agent больше не получают обновлений и исправлений безопасности. Для новых развёртываний используется только Alloy; для существующих — миграция штатным конвертером (см. Сценарий 5).

---

## Базовые концепции

### Ключевые возможности Alloy

| Возможность | Техническое описание |
| :--- | :--- |
| **Унифицированный сбор** | Заменяет связку `node_exporter`, `promtail` и standalone `otel-collector` одним бинарным файлом. |
| **Компонентная модель (DAG)** | Каждый блок конфигурации — компонент с входами (arguments) и выходами (exports). |
| **Авто-инструментирование (eBPF)** | Сбор трасс и RED-метрик (`beyla.ebpf`) и профилей (`pyroscope.ebpf`) на уровне ядра Linux без изменения кода приложений. |
| **Кластеризация** | Распределение целей сбора между несколькими экземплярами Alloy для масштабирования и отказоустойчивости. |
| **Native Prometheus** | Прямое использование кода Prometheus для сбора (scraping) и релейблинга (relabeling). |
| **Debug UI** | Веб-интерфейс на порту `12345` для анализа графа компонентов и поиска ошибок в реальном времени. |
| **Метрики здоровья и отладки** | Метрики агента и компонентов на `:12345/metrics`; эндпоинты `/-/ready` и `/-/healthy`. |
| **Надёжная доставка (WAL)** | Буферизация на диске (`--storage.path`) с повторами отправки при сбоях бэкенда. |

### Архитектура и компонентная модель

Alloy строит направленный ациклический граф (DAG) из компонентов. Категории компонентов:

- `discovery.*` — обнаружение целей (Kubernetes, Docker, файлы конфигурации service discovery, Consul и др.).
- `local.*` — работа с локальными ресурсами: `local.file` (чтение файла), `local.file_match` (обнаружение файлов по glob).
- `prometheus.*` — сбор и экспорт метрик (`scrape`, `exporter.unix`, `exporter.self`, `remote_write`, `relabel`).
- `loki.*` — сбор, обработка и отправка логов (`source.file`, `source.docker`, `process`, `relabel`, `write`).
- `otelcol.*` — приёмники, процессоры и экспортёры OpenTelemetry (`receiver.otlp`, `processor.batch`, `exporter.otlp`, `exporter.prometheus`).
- `pyroscope.*` — сбор, обогащение и отправка профилей (`ebpf`, `scrape`, `write`).
- `beyla.*` — авто-инструментирование приложений через eBPF (`beyla.ebpf`).
- `remote.*`, `sys.*` — внешние источники (`remote.http`, `remote.vault`) и функции окружения (`sys.env`).

Принципы:

- Данные передаются только по явным связям через `forward_to` или аргументы вида `targets = ...`.
- Компонент пересоздаётся при изменении его блока во время динамической перезагрузки; неиспользуемые выходы игнорируются.
- Порядок вычисления определяется графом зависимостей, а не позицией компонента в файле.

### Синтаксис конфигурации Alloy

Язык ориентирован на связность. Вместо глобальных настроек каждый компонент явно указывает, куда передавать данные через аргумент `forward_to`. Конфигурация состоит из двух элементов: **атрибутов** (`имя = значение`) и **блоков** (компоненты и вложенные настройки). Значения могут быть результатом функций стандартной библиотеки (например, `sys.env("LOKI_PASSWORD")`) или ссылок на экспорты других компонентов.

**Пример конвейера сбора логов:**

```hcl
// 1. Обнаружение локальных лог-файлов по glob-шаблону
local.file_match "app_logs" {
  path_targets = [{
    __path__ = "/var/log/*.log",
    job      = "app",
  }]
}

// 2. Чтение обнаруженных файлов
loki.source.file "app" {
  targets    = local.file_match.app_logs.targets
  forward_to = [loki.write.local.receiver]
}

// 3. Отправка логов в Loki
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
  external_labels = {
    source = "grafana-alloy",
  }
}
```

Для сбора логов из файлов рекомендован встроенный блок `file_match` внутри `loki.source.file` — он избавляет от отдельного компонента и его накладных расходов:

```hcl
loki.source.file "app" {
  targets    = [{ __path__ = "/var/log/*.log" }]
  forward_to = [loki.write.local.receiver]

  file_match {
    enabled     = true
    sync_period = "10s"
  }
}

loki.write "local" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}
```

Синтаксис проверяется и форматируется утилитами `alloy fmt` (форматирование) и `alloy validate` (проверка синтаксиса, имён компонентов, обязательных и неизвестных свойств). Ошибки указывают на файл и строку.

### Потоковая обработка данных (stages и пайплайны)

Обработка выполняется внутри компонентов-процессоров:

- `loki.process` применяет **stages** к лог-строкам: `stage.regex` (извлечение полей), `stage.labels`/`stage.label_drop`/`stage.label_keep` (лейблы), `stage.timestamp` (время), `stage.multiline` (склейка многострочных логов), `stage.metrics` (счётчики из логов).
- `prometheus.relabel` и `metric_relabel_configs` — фильтрация и переименование метрик до отправки.
- `otelcol.*` процессоры (например, `otelcol.processor.batch`) — батчинг и трансформация OTLP.

Пример извлечения `trace_id` из логов и проставления его как лейбла приведён в Сценарии 2.

### Высокая доступность и масштабирование (Clustering)

**Clustering** — режим, в котором несколько экземпляров агента объединяются в логический кластер. Это позволяет:

- **Распределять цели сбора** между узлами.
- **Обеспечивать отказоустойчивость**: при падении узла его цели перераспределяются между оставшимися.
- **Масштабировать** сбор горизонтально, добавляя экземпляры Alloy.

Кластеризация настраивается в два независимых шага:

1. **Уровень агента** — включение кластера командной строкой (флаги `--cluster.*`) или через Helm-чарт (`alloy.clustering.enabled`). Пир-узлы обмениваются данными по встроенному HTTP-серверу Alloy; если порт в `--cluster.join-addresses` не указан, используется порт HTTP-листенера (по умолчанию `12345`).

```bash
alloy run /etc/alloy/config.alloy \
  --cluster.enabled \
  --cluster.name=alloy-prod \
  --cluster.node-name=alloy-0 \
  --cluster.join-addresses=alloy-0:12345,alloy-1:12345,alloy-2:12345
```

2. **Уровень компонента** — каждый компонент, который должен участвовать в распределении нагрузки, включает это явно блоком `clustering`. Без такого блока кластер на уровне агента сам по себе нагрузку не распределяет.

```hcl
prometheus.scrape "distributed" {
  targets    = [{ "__address__" = "target:9100", "job" = "distributed" }]
  forward_to = [prometheus.remote_write.mimir.receiver]

  clustering {
    enabled = true
  }
}
```

Ключевые флаги кластера: `--cluster.enabled`, `--cluster.name` (защита от слияния кластеров), `--cluster.node-name`, `--cluster.join-addresses`, `--cluster.discover-peers`, `--cluster.advertise-address`, `--cluster.advertise-interfaces` (по умолчанию `eth0,en0`), `--cluster.rejoin-interval` (по умолчанию `60s`), `--cluster.enable-tls`.

### Надёжность доставки: WAL и повторные попытки

Alloy буферизирует исходящие данные в WAL (каталог `--storage.path`). Если бэкенд недоступен, данные накапливаются на диске и отправляются повторно после восстановления связи. Это даёт семантику **at-least-once** (возможны дубликаты при сбоях). `prometheus.remote_write` и `loki.write` имеют встроенные очереди и параметры повтора. WAL должен размещаться на постоянном томе — при его потере неотправленная телеметрия теряется.

### HTTP-сервер, UI и эндпоинты

Alloy запускает встроенный HTTP-сервер. На non-containerized платформах он по умолчанию слушает `127.0.0.1:12345` (только localhost); в контейнере адрес задаётся флагом `--server.http.listen-addr`. Полезные эндпоинты:

- `GET /` — встроенный UI с графом компонентов и живой отладкой.
- `GET /-/ready` — готовность (после загрузки начальной конфигурации возвращает `Alloy is ready.`).
- `GET /-/healthy` — здоровье всех компонентов (`All Alloy components are healthy.`).
- `GET /metrics` — метрики агента и компонентов в формате Prometheus (префиксы `alloy_*`, `prometheus_*`, `loki_*`, `otelcol_*`).
- `GET /-/support` — диагностический support bundle.
- `GET /debug/pprof` — профили Go (pprof).
- `POST /-/reload` — перезагрузка конфигурации.

Собственные метрики агента рекомендуется скрапить в Prometheus (см. Сценарий 4), чтобы мониторить здоровье сборщика.

### Безопасность: TLS, mTLS и секреты

Компоненты поддерживают блок `tls { ... }` (поля `insecure`, `ca_file`, `cert_file`, `key_file`, `server_name`) для шифрования и взаимной аутентификации (mTLS) при отправке в OTLP/remote_write/HTTP. Для кластера TLS включается флагами `--cluster.enable-tls`, `--cluster.tls-ca-path`, `--cluster.tls-cert-path`, `--cluster.tls-key-path`.

Секреты не должны храниться в открытом виде в конфигурации. Варианты:

- Интерполяция переменных окружения: `sys.env("LOKI_PASSWORD")` (значение подставляется при вычислении графа).
- Чтение секрета из файла компонентом `local.file` или получение из Vault компонентом `remote.vault`.
- Монтирование секретов из Docker/K8s Secret Volume в контейнер.

Монтируйте `config.alloy` в контейнер в режиме только для чтения (`:ro`).

---

## Практические сценарии

### Предварительные требования

- **ОС:** Linux (amd64/arm64), macOS или Windows.
- **Версия:** актуальная — 1.20.x (см. `Installation/docker_compose_setup.md`).
- **Порты:** `4317`/`4318` (OTLP), `12345` (HTTP-сервер: UI, `/metrics`, эндпоинты здоровья), порт HTTP-сервера также используется для кластера.
- **Хранилище:** каталог под `--storage.path` (WAL и позиции файлов). В Linux-пакете systemd задаёт `--storage.path=/var/lib/alloy`; в официальном Docker-примере — `/var/lib/alloy/data`.
- **Сеть:** исходящий доступ к бэкендам (Loki `:3100`, Tempo `:4317`, Mimir/Prometheus `:9090`/`:9099`, Pyroscope `:4040`).
- **eBPF (опционально):** только Linux с поддержкой BTF (ядро ≥ 5.8), привилегированный режим (`CAP_SYS_ADMIN`), доступ к `/proc` и `/sys`.
- **Docker-логи (опционально):** доступ к `/var/run/docker.sock` — `sudo setfacl -m u:alloy:r /var/run/docker.sock` или добавление пользователя `alloy` в группу `docker`.

### Сценарий 1: Приём OTLP-телеметрии

`otelcol.receiver.otlp` принимает данные по OTLP (gRPC и HTTP) и передаёт их далее в пайплайн. Traces уходят в Tempo, метрики через `otelcol.exporter.prometheus` конвертируются в формат Prometheus и отправляются через `prometheus.remote_write`.

```hcl
// Приёмник OTLP (gRPC и HTTP)
otelcol.receiver.otlp "default" {
  grpc { endpoint = "0.0.0.0:4317" }
  http { endpoint = "0.0.0.0:4318" }

  output {
    traces  = [otelcol.exporter.otlp.tempo.input]
    metrics = [otelcol.exporter.prometheus.mimir.input]
  }
}

// Экспорт traces в Tempo
otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}

// Конвертация OTLP-метрик в Prometheus и запись в Mimir
otelcol.exporter.prometheus "mimir" {
  forward_to = [prometheus.remote_write.mimir.receiver]
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Валидация:** приложение отправляет данные на `alloy:4317`/`alloy:4318`; в Tempo появляются трассы, в Mimir — метрики. Проверка на стороне агента: `curl -s localhost:12345/metrics | grep otelcol`; ошибки — `journalctl -u alloy | grep -i error` (или `docker logs monitoring-alloy | grep -i error`).

### Сценарий 2: Корреляция метрик и логов через trace_id

Пример сбора логов PostgreSQL с извлечением `trace_id` и проставлением его лейблом для корреляции с трассами.

```hcl
// Обнаружение лог-файлов СУБД
local.file_match "pg_logs" {
  path_targets = [{
    __path__ = "/var/lib/postgresql/data/log/postgresql.log",
    job      = "postgres-logs",
  }]
}

loki.source.file "read_logs" {
  targets    = local.file_match.pg_logs.targets
  forward_to = [loki.process.add_trace_id.receiver]
}

loki.process "add_trace_id" {
  // Извлекаем trace_id из строки лога в карту extracted
  stage.regex {
    expression = ".*traceparent='00-(?P<trace_id>[a-f0-9]{32})-[a-f0-9]{16}-01'.*"
    source     = "log_line"
  }

  // Проставляем извлечённое значение как лейбл traceID
  stage.labels {
    values = {
      traceID = "trace_id",
    }
  }

  forward_to = [loki.write.loki_writer.receiver]
}

loki.write "loki_writer" {
  endpoint { url = "http://loki:3100/loki/api/v1/push" }
}
```

**Валидация:** в Loki — логи с лейблом `job="postgres-logs"` и лейблом `traceID`; значение `traceID` совпадает с `trace_id` соответствующей трассы в Tempo (переход по ссылке Grafana Exemplars/derived fields).

### Сценарий 3: eBPF-инструментирование без изменения кода

Трассы и RED-метрики HTTP/gRPC-сервисов снимаются компонентом `beyla.ebpf` (обёртка Grafana Beyla). Профили приложений снимаются компонентом `pyroscope.ebpf`.

```hcl
// eBPF-инструментирование: трассы и RED-метрики
beyla.ebpf "default" {
  traces {
    instrumentations = ["http", "grpc", "sql"]
    sampler {
      name = "traceidratio"
      arg  = "0.1" // сэмплирование 10% трасс
    }
  }

  output {
    traces = [otelcol.exporter.otlp.tempo.input]
  }
}

otelcol.exporter.otlp "tempo" {
  client {
    endpoint = "tempo:4317"
    tls { insecure = true }
  }
}
```

```hcl
// eBPF-профилирование хоста
pyroscope.ebpf "host" {
  forward_to = [pyroscope.write.local.receiver]
}

pyroscope.write "local" {
  endpoint { url = "http://pyroscope:4040" }
}
```

**Требования:** Linux с BTF, привилегированный контейнер/процесс (`privileged: true` или `CAP_SYS_ADMIN`, `CAP_BPF`), доступ к `/proc`, `/sys` и `/sys/fs/bpf`. **Валидация:** `curl -s localhost:12345/metrics | grep alloy_component_healthy`; в UI (`/`) узел соответствующего компонента должен быть в состоянии Healthy; в логах Alloy — строка инициализации eBPF.

### Сценарий 4: Сбор метрик хоста и Docker-контейнеров

Alloy заменяет Node Exporter и cAdvisor: собирает метрики хоста и контейнеров.

```hcl
// Метрики хоста
prometheus.exporter.unix "host" { }

// Обнаружение контейнеров Docker
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// Сбор метрик хоста
prometheus.scrape "host_metrics" {
  targets         = prometheus.exporter.unix.host.targets
  forward_to      = [prometheus.remote_write.mimir.receiver]
  scrape_interval = "15s"
}

// Сбор метрик контейнеров
prometheus.scrape "container_metrics" {
  targets         = discovery.docker.containers.targets
  forward_to      = [prometheus.remote_write.mimir.receiver]
  scrape_interval = "15s"
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Валидация:** `curl -s localhost:12345/metrics | grep 'up{'` показывает статусы целей; в Prometheus появляются target-ы с job `host`/`containers`; `docker logs monitoring-alloy | grep -i error` пуст. Для `prometheus.exporter.unix` в контейнере может потребоваться доступ к `/proc` и `/sys` (монтирование или привилегии).

### Сценарий 5: Миграция с Promtail и Grafana Agent

Alloy включает встроенный конвертер конфигураций. Поддерживаемые форматы источника: `promtail`, `prometheus`, `static` (Grafana Agent Static), `otelcol`.

1. **Конвертация:**
   ```bash
   alloy convert --source-format=promtail --output=config.alloy promtail-config.yaml
   alloy convert --source-format=static   --output=config.alloy agent-static.yaml
   alloy convert --source-format=otelcol  --output=config.alloy otel-collector.yaml
   ```
2. **Проверка синтаксиса** перед деплоем:
   ```bash
   alloy validate config.alloy
   # → config.alloy: no issues found
   ```
3. **Пробный запуск без сохранения** — Alloy конвертирует на лету и запускается на исходном конфиге:
   ```bash
   alloy run --config.format=promtail promtail-config.yaml
   ```

Полный пошаговый план миграции в Kubernetes (параллельный запуск, проверка совпадения лейблов, вывод из эксплуатации) — в [alloy_installation.md](../Loki/loki_stack_setup/alloy_installation.md).

### Сценарий 6: Установка и первый запуск

**Вариант A — Docker Compose:**

```yaml
services:
  alloy:
    image: grafana/alloy:v1.20.1
    container_name: monitoring-alloy
    command: run --server.http.listen-addr=0.0.0.0:12345 --storage.path=/var/lib/alloy/data /etc/alloy/config.alloy
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - alloy_data:/var/lib/alloy/data
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
curl -Lo alloy.tar.gz https://github.com/grafana/alloy/releases/download/v1.20.1/alloy-linux-amd64.tar.gz
tar xzf alloy.tar.gz
sudo mv alloy /usr/local/bin/
sudo useradd -rs /bin/false alloy
sudo alloy run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
```

**Валидация первого запуска:**

```bash
# Готовность агента
curl -fsS http://localhost:12345/-/ready
# → Alloy is ready.

# Здоровье всех компонентов
curl -fsS http://localhost:12345/-/healthy
# → All Alloy components are healthy.

# Проверка синтаксиса/формата
alloy fmt /etc/alloy/config.alloy   # без вывода при корректном формате
alloy validate /etc/alloy/config.alloy
```

Глубокая установка в Kubernetes (Helm, DaemonSet/Deployment/StatefulSet, RBAC, NetworkPolicy) описана в выделенном файле — см. «См. также».

### Сценарий 7: Кластеризация и распределение нагрузки

Кластер включается флагами, распределение целей — блоком `clustering` у компонента:

```bash
alloy run /etc/alloy/config.alloy \
  --cluster.enabled \
  --cluster.name=alloy-prod \
  --cluster.node-name=$(hostname) \
  --cluster.join-addresses=alloy-0:12345,alloy-1:12345,alloy-2:12345
```

```hcl
prometheus.scrape "distributed" {
  targets    = [{ "__address__" = "target:9100", "job" = "distributed" }]
  forward_to = [prometheus.remote_write.mimir.receiver]

  clustering {
    enabled = true
  }
}

prometheus.remote_write "mimir" {
  endpoint { url = "http://mimir:9009/api/v1/push" }
}
```

**Валидация:** `curl -s localhost:12345/metrics | grep alloy_cluster_peers` показывает число узлов; в UI (`/`) отображаются подключённые peers. При падении узла его цели автоматически перераспределяются. TLS для кластера — через `--cluster.enable-tls` и `--cluster.tls-*`.

### Сценарий 8: Безопасная передача секретов

Интерполяция переменных окружения (значения подставляются при вычислении графа):

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

Для Docker задайте переменные через `environment:` сервиса или смонтированный файл `docker-compose.yml` `secrets:`. Для чтения секрета из файла используйте `local.file`, для получения из Vault — `remote.vault`.

**Валидация:** `alloy validate` проходит (секрет не присутствует в открытом виде в репозитории); проверка доставки — появление данных в бэкенде и отсутствие ошибок аутентификации в логах. Временные значения секрета можно посмотреть в live debugging UI.

---

## Дополнительная информация

### Сравнение Alloy и OpenTelemetry Collector

| Характеристика | Grafana Alloy | OTel Collector (Upstream) |
| :--- | :--- | :--- |
| **Язык** | Синтаксис Alloy (динамический граф) | YAML (конфигурация коллектора) |
| **Сбор метрик** | Нативный код Prometheus (scrape/relabel) | `prometheusreceiver` |
| **Фокус** | Экосистема Grafana + OTel | Универсальный стандарт |
| **Отладка** | Встроенный UI и граф компонентов | Текстовые логи и метрики |

### Преимущества и ограничения

#### Преимущества
- **Консолидация:** уменьшение числа агентов на хосте снижает нагрузку на CPU/RAM и упрощает патчинг.
- **Прозрачность:** встроенный UI позволяет быстро увидеть, почему метрика не дошла до хранилища (фильтрация или ошибка соединения).
- **Готовность к будущему:** Alloy — единая точка развития сбора телеметрии Grafana, включая профилирование и eBPF.

#### Ограничения
- **Порог входа:** синтаксис Alloy требует понимания принципов связывания экспортов и аргументов между компонентами.
- **Потребление ресурсов:** в очень простых сценариях (только сбор логов) Alloy может быть тяжелее, чем Promtail.

### Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Граф не загружается / ошибка парсинга | Синтаксическая ошибка, неверная точечная нотация | `alloy validate config.alloy`; сообщение с номером строки | Исправить связи `forward_to`/экспорты; проверить `alloy fmt` |
| Компонент в состоянии error (нет доставки) | Бэкенд недоступен, неверный URL, отказ TLS | `curl` к бэкенду; логи `level=error`; красный узел в UI | Проверить сеть, URL, блок `tls{}`; перезапустить граф |
| OTLP connection refused | Порт 4317/4318 закрыт или receiver не слушает | `ss -ltnp \| grep 4317` | Открыть порт, проверить `otelcol.receiver.otlp` |
| WAL растёт / диск заполняется | Бэкенд долго недоступен | Размер каталога `--storage.path` | Каталог на отдельном томе; восстановить сеть до бэкенда |
| 429 / rate limit от Loki или Mimir | Превышение лимита приёма | Логи бэкенда, метрики `alloy_*` | Настроить `batch`/очереди, дедупликацию, согласовать лимиты |
| Clustering split-brain / peers flapping | Нестабильный канал, неверные `--cluster.join-addresses` | Метрика `alloy_cluster_peers`, логи кластера | Стабильные адреса и порты, корректный `--cluster.name` |
| Высокое потребление памяти | Большие пайплайны без батчинга | `alloy_process_resident_memory_bytes` | Добавить `otelcol.processor.batch`, ограничить параллелизм |
| eBPF не работает | Ядро без BTF / не Linux / не хватает прав | `uname -a`; логи компонента | Использовать обычный receiver; ядро ≥ 5.8; `privileged: true` |
| Permission denied на `--storage.path` или docker.sock | Права пользователя `alloy` | Логи `permission denied` | `chown alloy` каталог; `setfacl -m u:alloy:r /var/run/docker.sock` |
| Изменения конфигурации не применились | Граф не перезагрузился (ошибка валидации) | Лог перезагрузки | `alloy validate`; при ошибке Alloy сохраняет предыдущий граф |

### Рекомендации по эксплуатации

- Фиксируйте версию (1.20.x) в образах и манифестах.
- Монтируйте `config.alloy` в режиме только для чтения (`:ro`).
- Размещайте WAL (`--storage.path`) на постоянном томе и не теряйте его.
- Скрапьте собственные метрики Alloy (`:12345/metrics`) в Prometheus для мониторинга агента.
- Используйте встроенный UI (`/`) и эндпоинты `/-/ready`, `/-/healthy` для диагностики и health-check.
- Прогоняйте `alloy fmt` и `alloy validate` в CI перед деплоем.
- Передавайте секреты через env/K8s Secrets/Vault/`local.file`, не храните в репозитории.
- Один `config.alloy` на функцию; избегайте гигантских монолитных графов.
- Устанавливайте resource limits (memory/CPU) на контейнер или systemd-юнит.
- Начинайте с минимального пайплайна и расширяйте его по необходимости.

### Ограничения и особые случаи

- **Семантика at-least-once:** при сбоях возможны дубликаты метрик/логов/трасс.
- **Динамическая перезагрузка** пересоздаёт изменившиеся компоненты; in-memory состояние (локальные счётчики агрегаторов) сбрасывается.
- **eBPF** доступен только на Linux с BTF; на macOS/Windows не поддерживается.
- **Кластеризация** требует стабильной сети и явных `--cluster.join-addresses`; авто-discovery peers ограничен.
- Один процесс Alloy строит **один глобальный граф** — несколько независимых графов в одном файле невозможны.
- При долгой недоступности бэкенда **WAL растёт неограниченно**, пока не восстановится связь.
- Порядок вычисления компонентов определяется графом, а не позицией в файле.

### Актуальность и ссылки

Актуальная версия Alloy — **1.20.x**. Основные направления развития: интеграция с Helm-чартом и **Grafana Alloy Operator** в Kubernetes, поддержка OpenTelemetry Profiles.

- [Официальный репозиторий GitHub](https://github.com/grafana/alloy)
- [Документация по компонентам Alloy](https://grafana.com/docs/alloy/latest/reference/components/)
- [CLI и команды Alloy](https://grafana.com/docs/alloy/latest/reference/cli/)
- [Миграция с Promtail](https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/)
- [Установка Alloy в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md)

**См. также:** [Обзор Grafana](./grafana_overview.md), [OpenTelemetry Collector](../OpenTelemetry/opentelemetry_overview.md), [Установка Alloy в Kubernetes](../Loki/loki_stack_setup/alloy_installation.md).
