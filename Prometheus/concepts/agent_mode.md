# Agent Mode в Prometheus

> **См. также:** [Remote Read/Write](../scaling/remote_read_write.md), [Масштабирование](../scaling/overview.md), [Конфигурация](../configuration.md), [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

## Определения

* **Agent Mode** — режим работы Prometheus, при котором отключены локальное хранилище TSDB и выполнение правил. Сервер работает как облегченный сборщик метрик, сразу пересылающий данные через Remote Write во внешнее хранилище. Введен в v2.32.0, стабилизирован в v3.x.
* **Server Mode** — стандартный режим работы Prometheus с полным функционалом: TSDB для хранения, PromQL для запросов, recording/alerting rules для обработки.
* **WAL (Write-Ahead Log)** — в Agent Mode используется только как краткосрочный буфер для исходящих данных (по умолчанию 24 часа), а не как полноценное хранилище.

## Основные концепции

### Agent Mode vs Server Mode

| Критерий | Server Mode | Agent Mode |
|:---|:---|:---|
| **TSDB** | Да (полноценное хранилище) | Нет (только WAL-буфер) |
| **PromQL запросы** | Да | Нет |
| **Recording Rules** | Да | Нет |
| **Alerting Rules** | Да | Нет |
| **Remote Write** | Да | Да |
| **Потребление RAM** | Выше | На 30-40% ниже |
| **Потребление CPU** | Выше | На 30-40% ниже |
| **Дисковое пространство** | Зависит от retention | Минимальное (только WAL) |

### Когда использовать Agent Mode

1. **Edge-кластеры:** Сбор метрик на удаленных сайтах с ограниченными ресурсами и пересылка в центральное хранилище.
2. **Мультикластерная архитектура:** Сбор в каждом кластере, хранение и обработка в центре (VictoriaMetrics, Mimir, Thanos).
3. **Ресурсно-ограниченные среды:** IoT, встроенные системы, контейнеры с ограниченными лимитами.
4. **Миграция с Legacy-систем:** Замена Graphite/StatsD мостов на стандартный Prometheus Agent.
5. **Горизонтальное масштабирование сбора:** Несколько Agent-экземпляров для распределения нагрузки скрейпинга.

### Архитектура Agent Mode

```
Targets --> Prometheus Agent --> Remote Write --> LTS (VM/Mimir/Thanos)
                                      |
                                      v
                                 WAL (24h buffer)
```

**Ключевые особенности:**
- **Stateless:** Агенты не хранят данные локально (кроме краткосрочного WAL-буфера).
- **Нет выполнения правил:** Вся логика обработки (recording/alerting) переносится на LTS.
- **Remote Write 2.0:** Основной протокол в 2026 году, снижает трафик на 60% за счет интернирования строк.

### Ограничения

1. **Нет локальных данных:** Невозможно выполнить PromQL-запрос или построить дашборд напрямую по Agent.
2. **Зависимость от LTS:** При недоступности LTS данные копятся в WAL максимум 24 часа (по умолчанию), затем безвозвратно теряются.
3. **Нет правил:** Recording и Alerting rules недоступны. Всю логику нужно размещать на стороне LTS (Thanos Ruler, Mimir Ruler).
4. **OTLP балансировка:** Входящий OTLP-трафик не балансируется между репликами автоматически.

### Сравнение с Grafana Alloy

| Характеристика | Prometheus Agent | Grafana Alloy |
|:---|:---|:---|
| **Назначение** | Сбор метрик Prometheus | Универсальный коллектор (метрики, логи, трейсы) |
| **Протоколы** | Pull (scrape), OTLP Push | Pull, Push, Logs, Traces |
| **Потребление RAM (100K серий)** | ~2 GB | ~1 GB |
| **Потребление CPU (100K серий)** | ~2 cores | ~1 core |
| **Конфигурация** | Prometheus YAML | Alloy River (HCL-подобный) |
| **Интеграция с LTS** | Remote Write | Remote Write, PrometheusRW |

## Практические примеры

### Запуск в Agent Mode

```bash
prometheus \
  --enable-feature=agent \
  --config.file=agent.yml \
  --storage.tsdb.path=/tmp/prometheus \
  --storage.tsdb.retention.time=24h
```

### Конфигурация agent.yml

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

remote_write:
  - url: "http://victoriametrics:8428/api/v1/write"
    queue_config:
      max_shards: 30
      capacity: 10000
      max_samples_per_send: 5000
    write_relabel_configs:
      - source_labels: [__name__]
        regex: 'go_.*'
        action: drop

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['node1:9100', 'node2:9100']
```

### Docker Compose (Agent + VictoriaMetrics)

```yaml
version: '3.8'
services:
  prometheus-agent:
    image: prom/prometheus:v3.1.0
    command:
      - '--enable-feature=agent'
      - '--config.file=/etc/prometheus/agent.yml'
      - '--storage.tsdb.retention.time=24h'
    volumes:
      - ./agent.yml:/etc/prometheus/agent.yml
    ports:
      - "9090:9090"

  victoriametrics:
    image: victoriametrics/victoria-metrics:v1.102.0
    command:
      - '--storageDataPath=/victoria-metrics-data'
      - '--retentionPeriod=90d'
    volumes:
      - vm-data:/victoria-metrics-data
    ports:
      - "8428:8428"
```

### Kubernetes (PrometheusAgent CRD)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusAgent
metadata:
  name: agent
spec:
  replicas: 2
  remoteWrite:
    - url: "http://victoriametrics:8428/api/v1/write"
      writeRelabelConfigs:
        - sourceLabels: [__name__]
          regex: 'go_.*'
          action: drop
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2
      memory: 4Gi
```

### Мониторинг Agent

```promql
# Размер WAL
prometheus_tsdb_wal_size_bytes

# Отброшенные сэмплы Remote Write
rate(prometheus_remote_storage_dropped_samples_total[5m])

# Очередь Remote Write
prometheus_remote_storage_queue_segments
```

## Дополнительная информация

* **Remote Write подробно:** [Remote Read/Write](../scaling/remote_read_write.md)
* **Масштабирование:** [Масштабирование Prometheus](../scaling/overview.md)
* **Конфигурация:** [Конфигурация Prometheus](../configuration.md)
* **Grafana Alloy:** [Grafana Alloy Overview](../../Grafana/grafana_alloy_overview.md)
* **PrometheusAgent в Kubernetes:** [Operator Concepts](../kubernetes/operator/concepts.md)
* **Сравнение стеков:** [Дизайн высоконагруженного мониторинга](../../Concepts/Observability_and_Monitoring/designing_high-load_monitoring_in_distributed_systems.md)
