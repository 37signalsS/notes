# Nomad — Логирование (Centralized Logging)

## Определения

**Centralized Logging** — практика централизованного сбора, обработки и хранения логов из всех задач Nomad в единой системе (ELK, Loki, Vector) для обеспечения可观имости и устранения неисправностей.

**Nomad Client Log Directory** — директория на клиенте, куда записываются stdout/stderr каждой задачи: `/opt/nomad/data/alloc/<alloc-id>/<task-name>/logs/`.

**Promtail** — агент сбора логов, предназначенный для доставки логов в Loki. Работает как system job на каждом Nomad-клиенте.

**Vector** — высокопроизводительный агент сбора и маршрутизации логов (метрик, событий), поддерживающий множество входов и выходов.

## Основные концепции

### Архитектура логирования для Nomad

```
Nomad Tasks (stdout/stderr)
       ↓
Nomad Client Log Files
       ↓
┌──────────────────────┐
│  Log Agent (system)  │
│  Promtail / Vector  │
│  / Filebeat          │
└──────────┬───────────┘
           ↓
    ┌──────┴──────┐
    │  Loki /     │
    │  Elasticsearch│
    │  /ClickHouse │
    └──────┬──────┘
           ↓
    ┌──────┴──────┐
    │  Grafana /  │
    │  Kibana     │
    └─────────────┘
```

### Структура логов Nomad

```
/opt/nomad/data/alloc/
└── <alloc-id>/
    └── <task-name>/
        └── logs/
            ├── <task-name>.stdout.0
            ├── <task-name>.stderr.0
            └── <task-name>.stdout.1
```

**Конфигурация ротации логов (client.hcl):**
```hcl
client {
  alloc_dir = "/opt/nomad/data/alloc"

  # Настройки логирования
  logging {
    type = "file"
    config {
      max_files     = 10
      max_file_size = 10 # MB
    }
  }
}
```

### Выбор агента логирования

| Агент | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Promtail** | Простая настройка, интеграция с Loki | Ограниченная обработка |
| **Vector** | Мощная маршрутизация, VRL, высокая производительность | Бо́льший footprint |
| **Filebeat** | Зрелый, интеграция с ELK | Тяжелее, больше конфигурации |

## Практические сценарии

### Сценарий 1: Promtail как System Job

```hcl
job "promtail" {
  datacenters = ["dc1"]
  type        = "system"

  group "monitoring" {
    task "promtail" {
      driver = "docker"

      config {
        image = "grafana/promtail:2.9.0"
        args  = ["-config.file=/etc/promtail/config.yml"]

        volumes = [
          "/opt/nomad/data/alloc:/nomad-allocs:ro",
          "/var/log:/var/log:ro",
        ]
      }

      template {
        data = <<EOH
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki.service.consul:3100/loki/api/v1/push

scrape_configs:
  - job_name: nomad
    static_configs:
      - targets:
          - localhost
        labels:
          job: nomad
          __path__: /nomad-allocs/*/*/logs/*.stdout.*

  - job_name: nomad-stderr
    static_configs:
      - targets:
          - localhost
        labels:
          job: nomad
          __path__: /nomad-allocs/*/*/logs/*.stderr.*
EOH
        destination = "local/config.yml"
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
```

### Сценарий 2: Vector как System Job

```hcl
job "vector" {
  datacenters = ["dc1"]
  type        = "system"

  group "monitoring" {
    task "vector" {
      driver = "docker"

      config {
        image = "timberio/vector:0.40.0-debian"
        args  = ["--config", "/etc/vector/vector.toml"]

        volumes = [
          "/opt/nomad/data/alloc:/nomad-allocs:ro",
          "local/config.toml:/etc/vector/vector.toml:ro",
        ]
      }

      template {
        data = <<EOH
[sources.nomad_stdout]
  type = "file"
  include = ["/nomad-allocs/*/*/logs/*.stdout.*"]
  read_from = "beginning"

[sources.nomad_stderr]
  type = "file"
  include = ["/nomad-allocs/*/*/logs/*.stderr.*"]
  read_from = "beginning"

[transforms.parse]
  type = "remap"
  inputs = ["nomad_stdout", "nomad_stderr"]
  source = '''
    .timestamp = now()
    .host = get_hostname!()
  '''

[sinks.loki]
  type = "loki"
  inputs = ["parse"]
  endpoint = "http://loki.service.consul:3100"
  labels.job = "nomad"
  encoding.codec = "json"
EOH
        destination = "local/config.toml"
      }

      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
```

### Сценарий 3: Structured Logging в приложении

Рекомендации по формату логов для максимально эффективного парсинга:

```json
{
  "timestamp": "2026-01-15T10:30:00Z",
  "level": "info",
  "service": "webapp",
  "alloc_id": "abc123",
  "message": "Request processed",
  "method": "GET",
  "path": "/api/v1/users",
  "status": 200,
  "duration_ms": 45
}
```

**VRL-трансформация для Vector:**
```ruby
structured = parse_json!(.message)
.timestamp = structured.timestamp
.level = structured.level
.service = structured.service
.message = structured.message
```

### Сценарий 4: Фильтрация по namespace/task

```yaml
# Promtail pipeline для фильтрации
scrape_configs:
  - job_name: nomad-production
    pipeline_stages:
      - regex:
          source: filename
          expression: '/nomad-allocs/(?P<alloc_id>[^/]+)/'
      - labels:
          alloc_id:
    static_configs:
      - targets:
          - localhost
        labels:
          job: nomad
          env: production
          __path__: /nomad-allocs/*/*/logs/*.stdout.*
```

## Диагностика

```bash
# Проверка логов задачи
nomad alloc logs <alloc-id> <task-name>

# Просмотр логов на диске
ls -la /opt/nomad/data/alloc/<alloc-id>/<task-name>/logs/

# Проверка Promtail
curl http://localhost:9080/ready

# Проверка Vector
curl http://localhost:8686/graphql
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `No logs found` | Агент не монтирует директорию allocs | Проверьте volumes в job-файле |
| `Loki push failed` | Loki недоступен | Проверьте連絡ность с Loki через Consul |
| `High memory usage` | Слишком много sources | Ограничьте include-паттерны |
| `Log rotation not working` | Не настроена ротация | Добавьте `logging` блок в client.hcl |

## Дополнительная информация

- [Loki: Обзор](../Loki/loki_overview.md) — архитектура и настройка Loki.
- [Vector: Обзор](../Vector/vector_overview.md) — конфигурация Vector.
- [Nomad — мониторинг](./nomad_monitoring.md) — Prometheus + Grafana интеграция.
- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — основы Nomad.
