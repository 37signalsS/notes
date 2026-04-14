# Prometheus Configuration

## Definitions

**Конфигурация Prometheus** — набор параметров, определяющих сбор, хранение и обработку метрик, а также управление оповещениями. Состоит из:

1. **`prometheus.yml`** — основной YAML-файл: цели сбора (scrape targets), правила (rules), интеграция с Alertmanager и LTS.
2. **CLI-флаги** — параметры запуска процесса: путь к TSDB, retention, веб-интерфейс, лимиты запросов.

> **См. также:** [Prometheus overview](./overview.md), [TSDB](./concepts/tsdb.md), [Alertmanager](./alertmanager.md)

## Basic Concepts

### Структура `prometheus.yml`

```yaml
global:
  scrape_interval: 1m
  evaluation_interval: 1m
  external_labels:
    monitor: 'my-prometheus'

rule_files:
  - 'rules/*.rules.yml'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

alerting:
  alertmanagers:
  - static_configs:
      - targets: ['localhost:9093']

remote_write:
  - url: "http://remote-storage.example.com/write"

remote_read:
  - url: "http://remote-storage.example.com/read"
```

| Блок | Назначение |
|---|---|
| `global` | Параметры по умолчанию: `scrape_interval`, `evaluation_interval`, `external_labels` |
| `rule_files` | Пути к [правилам записи и алертинга](./rules.md) (поддержка glob) |
| `scrape_configs` | Задания (jobs) сбора метрик, включая [Service Discovery и Relabeling](./service_discovery_and_relabeling.md) |
| `alerting` | Настройки отправки алертов в [Alertmanager](./alertmanager.md) |
| `remote_write` / `remote_read` | Интеграция с LTS ([Mimir](../Mimir/mimir_overview.md), [VictoriaMetrics](../VictoriaMetrics/overview.md)). Подробнее: [Remote Read/Write](./scaling/remote_read_write.md) |

### Флаги запуска

| Флаг | Default | Описание |
|---|---|---|
| `--config.file` | `prometheus.yml` | Путь к конфигурационному файлу |
| `--web.listen-address` | `0.0.0.0:9090` | Адрес UI и [API](./prometheus_api.md) |
| `--storage.tsdb.path` | `data/` | Путь к [TSDB](./concepts/tsdb.md) |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных (`30d`, `2y`) |
| `--storage.tsdb.retention.size` | `0B` | Макс. размер хранилища (`50GB`) |
| `--query.timeout` | `2m` | Таймаут PromQL-запроса |
| `--query.max-concurrency` | `20` | Макс. количество одновременных запросов |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`) |

## Practical Scenarios

### Базовая конфигурация

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  - job_name: "node_exporter"
    static_configs:
      - targets: ["localhost:9100"]
```

### Retention (хранение данных)

| Параметр | Default | Описание |
|---|---|---|
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных |
| `--storage.tsdb.retention.size` | `0B` | Макс. размер (0 = без ограничений) |

**Способы настройки:**

| Метод | Пример |
|---|---|
| CLI | `prometheus --storage.tsdb.retention.time=30d` |
| Docker Compose | `command: ['--storage.tsdb.retention.time=7d', '--storage.tsdb.retention.size=10GB']` |
| CI/CD | Короткий retention (`12h`–`24h`) — актуальность важнее долгосрочного хранения |

**Проверка:** Status → Command-Line Flags → `storage.tsdb.retention.time`

**Зачем настраивать:**

- Оптимизация дискового пространства
- Производительность запросов (длительное хранение замедляет PromQL)

### Параметры `scrape_configs`

| Параметр | Назначение |
|---|---|
| `scrape_interval` | Частота опроса (переопределяет global) |
| `scrape_timeout` | Таймаут HTTP-запроса (< `scrape_interval`) |
| `metrics_path` | Путь к метрикам (default: `/metrics`) |
| `scheme` | `http` или `https` |
| `honor_labels` | `true` — сохранять метки цели при конфликте с внешними |
| `relabel_configs` | Модификация меток **до** сбора. См. [Service Discovery и Relabeling](./service_discovery_and_relabeling.md) |
| `metric_relabel_configs` | Модификация меток **после** сбора |

## Additional Information

### Проверка конфигурации

```bash
promtool check config /path/to/prometheus.yml
promtool check rules /path/to/rules.yml
```

Подробнее: [promtool и лучшие практики](./promtool_and_best_practices.md)

### Перезагрузка конфигурации

```bash
# systemd
sudo systemctl reload prometheus

# HTTP
curl -X POST http://localhost:9090/-/reload
```

«Горячая» перезагрузка без прерывания сбора метрик.
