# Деплой cAdvisor и сбор метрик контейнеров

## Определения

**cAdvisor (Container Advisor)** — open-source инструмент от Google для мониторинга потребления ресурсов и производительности запущенных контейнеров. Агент cAdvisor работает на каждом хосте, автоматически обнаруживает все контейнеры и собирает детальные метрики из cgroups. Экспортирует данные в формате Prometheus через HTTP-эндпоинт `/metrics`.

**Container Metrics** — числовые измерения потребления ресурсов контейнером: CPU (user/system/throttled), память (RSS/cache/swap), сеть (Rx/Tx bytes/packets), файловая система (_read/write IOPS_), процессы. Метрики считываются из cgroups и предоставляются в реальном времени.

**Prometheus Exporter** — приложение, преобразующее внутренние данные системы в формат метрик Prometheus и предоставляющее их через HTTP-эндпоинт (обычно `/metrics`). cAdvisor является exporter'ом для контейнерных метрик, Node Exporter — для метрик хоста, Docker Engine metrics — для метрик демона.

**Scrape** — механизм Prometheus периодического получения (опроса) метрик с целевых эндпоинтов. Конфигурация scrape определяет целевые адреса (`targets`), интервал опроса (`scrape_interval`), параметры аутентификации и relabeling.

**Grafana Dashboard** — визуальный слой для отображения временных рядов метрик. Готовые дашборды ускоряют настройку мониторинга: ID 1229 (Docker и cAdvisor), ID 10619 (Docker Engine & Containerd), ID 14282 (cAdvisor полный).

## Базовые концепции

### Архитектура cAdvisor

cAdvisor работает как агент на каждом хосте и собирает метрики напрямую из виртуальной файловой системы cgroups:

```
┌─────────────────────────────────────────────────┐
│                    Host                         │
│                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │Container │  │Container │  │Container │      │
│  │    A     │  │    B     │  │    C     │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │              │              │            │
│       ▼              ▼              ▼            │
│  ┌─────────────────────────────────────────┐    │
│  │              cgroups v1/v2              │    │
│  │  /sys/fs/cgroup/.../<id>/cpu.stat      │    │
│  │  /sys/fs/cgroup/.../<id>/memory.stat   │    │
│  │  /sys/fs/cgroup/.../<id>/io.stat       │    │
│  └──────────────────┬──────────────────────┘    │
│                     │                           │
│                     ▼                           │
│  ┌─────────────────────────────────────────┐    │
│  │            cAdvisor Agent               │    │
│  │  • Считывает данные из cgroups          │    │
│  │  • Агрегирует по контейнерам            │    │
│  │  • Предоставляет /metrics endpoint      │    │
│  └──────────────────┬──────────────────────┘    │
│                     │ :8080                      │
│                     ▼                           │
│              Prometheus                        │
│              (scrape)                          │
└─────────────────────────────────────────────────┘
```

Ключевые особенности:
- **Автоматическое обнаружение**: cAdvisor мониторит Docker daemon и автоматически добавляет/удаляет контейнеры
- **Сбор из cgroups**: данные поступают из ядра Linux без дополнительной инструментации приложений
- **Хранение истории**: встроенное хранение метрик за последние 60 секунд (самодостаточно, но для long-term нужен Prometheus)
- **Веб-интерфейс**: встроенный UI на порту `8080` для быстрой диагностики

### Docker Engine built-in metrics vs cAdvisor

Docker предоставляет два механизма сбора метрик, которые дополняют друг друга:

| Параметр | Docker Engine Metrics | cAdvisor |
|----------|----------------------|----------|
| **Порт** | `9323` | `8080` |
| **Обнаружение** | Встроен в daemon | Отдельный агент |
| **Гранулярность** | Агрегированная статистика daemon | Per-container детализация |
| **Метрики** | Количество контейнеров, образов, ошибки сборки | CPU, RAM, Network, Disk I/O, Processes |
| **Настройка** | `daemon.json` | `docker run` / Compose |
| **Данные** | Состояние Docker Engine | Потребление ресурсов каждым контейнером |
| **Применение** | Мониторинг самого демона | Мониторинг приложений в контейнерах |

**Рекомендация:** использовать оба источника одновременно. Docker Engine metrics для здоровья демона, cAdvisor — для детализации по контейнерам.

### Что собирает cAdvisor

| Категория | Ключевые метрики | Описание |
|-----------|-----------------|----------|
| **CPU** | `container_cpu_usage_seconds_total` | Суммарное время CPU (user + system) |
| | `container_cpu_cfs_throttled_seconds_total` | Время ограничения CPU (throttling) |
| | `container_cpu_cfs_periods_total` | Количество периодов CFS |
| **Память** | `container_memory_working_set_bytes` | Активная память (excl. cache) |
| | `container_memory_rss` | Резидентный набор памяти |
| | `container_memory_cache` | Файловый кеш |
| | `container_memory_failures_total` | События нехватки памяти |
| **Сеть** | `container_network_receive_bytes_total` | Входящий трафик |
| | `container_network_transmit_bytes_total` | Исходящий трафик |
| | `container_network_receive_errors_total` | Ошибки приема |
| **ФС** | `container_fs_reads_total` / `container_fs_writes_total` | Операции чтения/записи |
| | `container_fs_read_bytes_total` / `container_fs_write_bytes_total` | Объем данных |
| **Процессы** | `container_processes` / `container_threads` | Количество процессов/потоков |

### Интеграция с Prometheus

Prometheus подключается к cAdvisor через механизм scrape. Два способа настройки:

**Статическая конфигурация** — фиксированное количество хостов:
```yaml
scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['192.168.1.10:8080']
    scrape_interval: 15s
```

**Dynamic Service Discovery** — автоматическое обнаружение через Docker Socket:
```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      - source_labels: [__meta_docker_container_label_prometheus_scrape]
        regex: true
        action: keep
```

**Ключевые параметры scrape:** `scrape_interval` (дефолт 15s), `scrape_timeout` (дефолт 10s), `metric_relabel_configs` (фильтрация метрик), `honor_labels` (приоритет лейблов).

### Grafana дашборды

Готовые дашборды для визуализации метрик контейнеров:

| Dashboard ID | Назначение | Метрики |
|--------------|-----------|---------|
| **1229** | Docker и cAdvisor | CPU, RAM, Network контейнеров и хоста |
| **10619** | Docker Engine & Containerd | Расширенная статистика daemon + containerd |
| **14282** | cAdvisor полный | Детальные метрики I/O, filesystem, processes |
| **11600** | Node Exporter Full | Метрики хоста (配合 Node Exporter) |

Установка через Grafana UI: Dashboards → Import → ввести ID → Load.

## Практические сценарии

### 1. Деплой cAdvisor (standalone)

Запуск cAdvisor как отдельного контейнера с монтированием необходимых путей:

```bash
docker run -d \
  --name cadvisor \
  --restart unless-stopped \
  -p 8080:8080 \
  -v /:/rootfs:ro \
  -v /var/run:/var/run:ro \
  -v /sys:/sys:ro \
  -v /var/lib/docker/:/var/lib/docker:ro \
  -v /dev/disk/:/dev/disk:ro \
  --privileged \
  --device=/dev/kmsg \
  gcr.io/cadvisor/cadvisor:v0.49.1
```

**Параметры:**
- `-v /:/rootfs:ro` — корневая ФС хоста (для определения типа ОС и размера диска)
- `-v /var/run:/var/run:ro` — Docker socket (для обнаружения контейнеров)
- `-v /sys:/sys:ro` — sysfs (данные cgroups)
- `-v /var/lib/docker/:/var/lib/docker:ro` — слои образов
- `--privileged` — доступ к cgroups v1/v2 (альтернатива — конкретные capabilities)
- `--device=/dev/kmsg` — kernel messages для внутренних нужд

**Проверка:**
```bash
curl -s http://localhost:8080/metrics | head -20
```

**Веб-интерфейс:** `http://localhost:8080` — встроенная панель с графиками по каждому контейнеру.

### 2. cAdvisor в Docker Compose (полный стек)

Деплой Prometheus + cAdvisor + Grafana:

```yaml
version: '3.8'

services:
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.1
    container_name: cadvisor
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    privileged: true
    devices:
      - /dev/kmsg
    networks:
      - monitoring

  prometheus:
    image: prom/prometheus:v2.53.0
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:11.1.0
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### 3. Конфигурация Prometheus scrape

Файл `prometheus.yml` для сбора метрик с cAdvisor:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Метрики cAdvisor (per-container)
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    scrape_interval: 10s

  # Метрики Docker Engine (daemon stats)
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['host.docker.internal:9323']
```

**Динамическое обнаружение контейнеров (docker_sd_config):**

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Собирать метрики только с контейнеров с лейблом prometheus_scrape=true
      - source_labels: [__meta_docker_container_label_prometheus_scrape]
        regex: true
        action: keep

      # Установить job_name по лейблу
      - source_labels: [__meta_docker_container_label_prometheus_job]
        target_label: job

      # Установить путь для scrape по лейблу
      - source_labels: [__meta_docker_container_label_prometheus_path]
        target_label: __metrics_path__
        regex: (.+)

      # Добавить лейбл с именем контейнера
      - source_labels: [__meta_docker_container_name]
        target_label: container_name
```

**Запуск контейнера с лейблами для автоматического обнаружения:**

```bash
docker run -d \
  --name my-app \
  -l prometheus_scrape=true \
  -l prometheus_port=8080 \
  -l prometheus_path=/metrics \
  -l prometheus_job=my-application \
  my-app:latest
```

### 4. Ключевые метрики и PromQL запросы

**CPU Usage (процент от одного ядра):**
```promql
# Использование CPU контейнером (в ядрах)
rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]) * 100

# Процент от лимита
rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])
/
(container_spec_cpu_quota{container!="",container!="POD"} / container_spec_cpu_period{container!="",container!="POD"})
* 100
```

**Memory Usage:**
```promql
# Активная память (без кеша)
container_memory_working_set_bytes{container!="",container!="POD"}

# Процент от лимита
container_memory_working_set_bytes{container!="",container!="POD"}
/
container_spec_memory_limit_bytes{container!="",container!="POD"}
* 100

# RSS (резидентный набор)
container_memory_rss{container!="",container!="POD"}
```

**Network I/O:**
```promql
# Входящий трафик (байт/сек)
rate(container_network_receive_bytes_total{container!="",container!="POD"}[5m])

# Исходящий трафик (байт/сек)
rate(container_network_transmit_bytes_total{container!="",container!="POD"}[5m])

# Ошибки сети
rate(container_network_receive_errors_total{container!="",container!="POD"}[5m])
```

**Disk I/O:**
```promql
# Чтение (байт/сек)
rate(container_fs_reads_bytes_total{container!="",container!="POD"}[5m])

# Запись (байт/сек)
rate(container_fs_writes_bytes_total{container!="",container!="POD"}[5m])

# IOPS
rate(container_fs_reads_total{container!="",container!="POD"}[5m])
+
rate(container_fs_writes_total{container!="",container!="POD"}[5m])
```

### 5. Alerting правила для проблем контейнеров

Файл `alerts.yml` для Prometheus:

```yaml
groups:
  - name: container_alerts
    rules:
      # Высокое использование CPU (>80% от лимита)
      - alert: ContainerHighCpuUsage
        expr: |
          (
            rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])
            /
            (container_spec_cpu_quota{container!="",container!="POD"} / container_spec_cpu_period{container!="",container!="POD"})
          ) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} — CPU >80%"

      # Память близка к лимиту (>90%)
      - alert: ContainerMemoryNearLimit
        expr: |
          (
            container_memory_working_set_bytes{container!="",container!="POD"}
            /
            container_spec_memory_limit_bytes{container!="",container!="POD"}
          ) > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.name }} — память >90% от лимита"

      # OOM Killed
      - alert: ContainerOomKilled
        expr: increase(container_oom_events_total{container!="",container!="POD"}[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.name }} завершен из-за OOM"

      # Контейнер не отвечает
      - alert: ContainerDown
        expr: absent(container_cpu_usage_seconds_total{container="my-app"})
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Контейнер my-app недоступен"

      # Высокий CPU Throttling
      - alert: ContainerCpuThrottling
        expr: |
          rate(container_cpu_cfs_throttled_seconds_total{container!="",container!="POD"}[5m])
          /
          rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]) > 0.25
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} — CPU throttling >25%"
```

### 6. Кастомные метрики из приложений

Для экспорта бизнес-метрик используйте клиентские библиотеки Prometheus.

**Python (prometheus_client):**
```python
from prometheus_client import Counter, Gauge, start_http_server

REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
ACTIVE_CONNECTIONS = Gauge('active_connections', 'Number of active connections')

start_http_server(8000)

REQUEST_COUNT.labels(method='GET', endpoint='/api/users').inc()
ACTIVE_CONNECTIONS.set(42)
```

**Go (prometheus/client_golang):**
```go
import "github.com/prometheus/client_golang/prometheus/promhttp"

var httpRequests = prometheus.NewCounterVec(
    prometheus.CounterOpts{
        Name: "http_requests_total",
        Help: "Total HTTP requests",
    },
    []string{"method", "endpoint"},
)

func main() {
    http.Handle("/metrics", promhttp.Handler())
    http.ListenAndServe(":8000", nil)
}
```

**Запуск и scrape конфигурация:**
```bash
docker run -d --name my-app -p 8000:8000 \
  -l prometheus_scrape=true -l prometheus_port=8000 \
  -l prometheus_path=/metrics my-app:latest
```

```yaml
scrape_configs:
  - job_name: 'my-app'
    static_configs:
      - targets: ['my-app:8000']
```

## Дополнительная информация

### Связанные документы

- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — встроенный экспортер Docker Engine (порт 9323)
- **[Нативные метрики Docker](./docker_native_metrics.md)** — быстрая диагностика через `docker stats`
- **[Конфигурация Docker daemon](../docker_daemon_config.md)** — настройка `daemon.json`

### Сравнение: cAdvisor vs docker stats vs Docker Engine Metrics

| Критерий | cAdvisor | docker stats | Docker Engine Metrics |
|----------|----------|-------------|----------------------|
| **Назначение** | Промышленный мониторинг | Ручная диагностика | Мониторинг демона |
| **Хранение данных** | Prometheus (long-term) | Только real-time | Prometheus (long-term) |
| **Привилегии** | Требует /sys, /var/lib/docker | Достаточно docker group | Настройка daemon.json |
| **Нагрузка** | Низкая (cgroups) | Средняя (API опрос) | Низкая (встроено) |
| **Обнаружение** | Автоматическое | Ручной список | Автоматическое |
| **Гранулярность** | Per-container + per-pod | Per-container | Агрегированная |

### Нагрузка ресурсов cAdvisor

- **CPU:** ~0.1-0.5% на хосте (10-50 контейнеров)
- **RAM:** ~30-50 MB
- **Сеть:** ~1-5 KB/s на контейнер (зависит от scrape_interval)
- **Диск:** при Prometheus ~1-2 KB на метрику в час

**Масштабирование:** до 100 контейнеров — один экземпляр; 100-500 — `scrape_interval: 30s`; более 500 — federation.

### Типичные ошибки

1. **`permission denied` на `/sys/fs/cgroup`** — добавить `--privileged` или `--volume /sys/fs/cgroup:/sys/fs/cgroup:ro`
2. **cAdvisor не видит контейнеры** — проверить примонтирован `/var/run/docker.sock`
3. **Метрики не появляются в Prometheus** — проверить `scrape_interval` и доступность порта `8080`
4. **Высокий CPU на больших кластерах** — увеличить `scrape_interval`, использовать `metric_relabel_configs`
5. **Устаревший образ** — обновлять до последней версии (исправления безопасности)
6. **cgroups v1/v2 конфликт** — определить версию: `stat -f /sys/fs/cgroup | head -5`; для v2 использовать `--privileged`
