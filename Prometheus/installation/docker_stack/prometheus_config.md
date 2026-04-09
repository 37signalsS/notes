# Конфигурация Prometheus для Docker Compose

## Definitions

**Конфигурация Prometheus в Docker Stack** — файл `prometheus.yml`, монтируемый через bind mount в контейнер Prometheus. Содержит scrape-цели, rule_files и alerting-секцию, адаптированные для Docker Compose (DNS-имена сервисов, контейнерные порты).

> **См. также:** [Prometheus Configuration (SSoT)](../../configuration.md) — общая структура `prometheus.yml`, CLI-флаги, retention, remote read/write.

## Basic Concepts

### Путь конфигурации в контейнере

| Параметр | Значение |
|---|---|
| Хост-путь | `./prometheus/prometheus.yml` |
| Контейнер-путь | `/etc/prometheus/prometheus.yml` (передаётся через `--config.file`) |
| Bind mount | `./prometheus:/etc/prometheus` (в `docker-compose.yml`) |

### Docker DNS и scrape-цели

В Docker Compose сервисы доступны по именам, объявленным в `docker-compose.yml`. Prometheus разрешает эти имена через встроенный Docker DNS:

| Сервис | Имя в scrape_config | Порт |
|---|---|---|
| Prometheus (self) | `localhost` | 9090 |
| Node Exporter | `node-exporter` | 9100 |
| cAdvisor | `cadvisor` | 8080 |
| Alertmanager | `alertmanager` | 9093 |

> **Важно:** `localhost` в scrape_config Prometheus означает контейнер Prometheus (не хост). Для сбора метрик с хоста используется Node Exporter.

### Связь с Alertmanager

Alerting-секция указывает на сервис Alertmanager по DNS-имени в Docker-сети:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Rule files

Путь к файлу правил — внутренний путь контейнера:

```yaml
rule_files:
  - /etc/prometheus/rules.yml
```

Файл `rules.yml` размещается в той же директории `./prometheus/` и монтируется вместе с `prometheus.yml`.

## Practical Scenarios

### Базовый `prometheus.yml` для Docker Stack

```yaml
global:
  scrape_interval: 15s

rule_files:
  - /etc/prometheus/rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
```

> **Структура блоков:** `global`, `rule_files`, `alerting`, `scrape_configs` — описана в [Prometheus Configuration (SSoT)](../../configuration.md#структура-prometheousyml).

### Пример `rules.yml`

```yaml
groups:
  - name: node_alerts
    rules:
      - alert: HostHighCpuLoad
        expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая загрузка CPU на {{ $labels.instance }}"
          description: "Загрузка CPU превышает 85% в течение 5 минут."

      - alert: HostHighMemoryLoad
        expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокое потребление памяти на {{ $labels.instance }}"
          description: "Потребление памяти превышает 90% в течение 5 минут."
```

> **Подробнее:** [Rules и алертинг](../../rules.md) — полное руководство по alerting rules, recording rules, состояния алертов.

### Продвинутая конфигурация: scrape-таймауты и relabeling

Для production-сред рекомендуется добавить явные таймауты и `metric_relabel_configs`:

```yaml
global:
  scrape_interval: 15s
  scrape_timeout: 10s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    scrape_interval: 10s
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '(.+):\d+'
        replacement: '${1}'

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    metric_relabel_configs:
      # Оставляем только метрики контейнеров (исключаем хост)
      - source_labels: [container_label_io_kubernetes_container_name]
        regex: '^$'
        action: drop
```

| Параметр | Значение | Зачем |
|---|---|---|
| `scrape_timeout: 10s` | < `scrape_interval` | Защита от зависших HTTP-запросов |
| `evaluation_interval: 15s` | = `scrape_interval` | Синхронизация вычисления правил со сбором метрик |
| `relabel_configs` (instance) | Убирает порт из метки `instance` | Читаемые имена хостов в дашбордах |
| `metric_relabel_configs` (cadvisor) | Drop пустых `container_label` | Уменьшение кардинальности метрик |

> **Подробно:** [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md).

### Проверка конфигурации

```bash
# Через promtool внутри контейнера
docker exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker exec prometheus promtool check rules /etc/prometheus/rules.yml

# Через curl — health endpoint
curl -s http://localhost:9090/-/healthy
# Ожидаемый ответ: Prometheus Server is Healthy.
```

### Перезагрузка после изменения конфига

```bash
# Вариант 1: hot reload (без перезапуска контейнера)
docker exec prometheus wget -q --post-data '' http://localhost:9090/-/reload

# Вариант 2: restart контейнера
docker compose restart prometheus

# Проверка логов
docker compose logs -f prometheus
```

> **Важно:** `promtool check config` обязателен перед reload — невалидный конфиг приведёт к падению процесса Prometheus при перезапуске. Hot reload безопасен — при ошибке конфигурации Prometheus продолжит работать со старой конфигурацией.

## Additional Information

### Связанные темы

* [Prometheus Configuration (SSoT)](../../configuration.md) — структура `prometheus.yml`, CLI-флаги, retention, remote read/write
* [Rules и алертинг](../../rules.md) — alerting rules, recording rules, состояния алертов
* [Alertmanager для Docker Compose](./docker_compose_alertmanager_config.md) — маршрутизация алертов
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — relabel_configs, metric_relabel_configs
* [Docker Compose конфигурация](./docker-compose_config.md) — полный YAML стека
* [Мониторинг удалённых хостов](./remote_hosts_monitoring.md) — Node Exporter на внешних серверах

### Параметры CLI Prometheus в Docker Stack

Передаются через `command` в `docker-compose.yml` (см. [docker-compose_config.md](./docker-compose_config.md)):

| Флаг | Значение в стеке | Описание |
|---|---|---|
| `--config.file` | `/etc/prometheus/prometheus.yml` | Путь к конфигурации |
| `--storage.tsdb.path` | `/prometheus` | Путь к TSDB (named volume) |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения метрик |
| `--web.console.libraries` | `/usr/share/prometheus/console_libraries` | Стандартные библиотеки UI |
| `--web.console.templates` | `/usr/share/prometheus/consoles` | Стандартные шаблоны UI |

> **Все флаги:** [Prometheus Configuration (SSoT)](../../configuration.md#флаги-запуска).
