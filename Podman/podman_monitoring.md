# Podman: Мониторинг и наблюдаемость

## Определения

**Мониторинг Podman** — процесс сбора, агрегации и визуализации метрик контейнеров, управляемых Podman, для обеспечения видимости состояния рабочих нагрузок в production-среде.

**cAdvisor (Container Advisor)** — агент сбора метрик контейнеров от Google, собирающий данные о потреблении ресурсов (CPU, память, сеть, I/O) всех контейнеров на хосте. Работает с Podman через поддержку OCI.

**Prometheus** — система мониторинга и алертинга, собирающая метрики по протоколу pull (scrape). Основной инструмент для сбора метрик контейнеров в modern инфраструктуре.

**Grafana** — платформа визуализации и дашбордов, интегрируемая с Prometheus для отображения метрик Podman-контейнеров в реальном времени.

**podman stats** — встроенная CLI-утилита Podman для получения live-метрик потребления ресурсов всеми запущенными контейнерами (аналог `docker stats`).

---

## Теоретический блок

### Архитектура мониторинга Podman

```
┌─────────────────────────────────────────────────────────────┐
│                      Grafana Dashboard                      │
│              (визуализация, алерты, отчёты)                  │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────────┐
│                       Prometheus                            │
│         (сбор метрик, хранение, alerting rules)             │
└───┬──────────────┬──────────────────────┬───────────────────┘
    │ scrape       │ scrape               │ scrape
┌───▼────┐   ┌─────▼──────┐   ┌──────────▼──────────┐
│cAdvisor│   │node_exporter│   │ Podman контейнеры   │
│(метрики│   │(метрики     │   │ (HTTP /metrics      │
│контейн.)│  │ хоста)      │   │  endpoint)          │
└────────┘   └─────────────┘   └─────────────────────┘
```

### Типы метрик Podman

| Тип | Описание | Примеры |
|---|---|---|
| **Container metrics** | Потребление ресурсов контейнером | CPU usage, memory usage, network I/O |
| **Pod metrics** | Агрегированные метрики по поду | Total CPU, total memory всех контейнеров |
| **System metrics** | Метрики хоста | Disk usage, network interfaces, system load |
| **Storage metrics** | Использование хранилища | Overlay FS size, image layer sizes |

### Методы сбора метрик

| Метод | Описание | Когда использовать |
|---|---|---|
| **podman stats CLI** | Встроенные live-метрики | Быстрая диагностика, one-off проверки |
| **cAdvisor** | Автоматический scrape контейнеров | Production мониторинг, все контейнеры |
| **HTTP /metrics** | Кастомный endpoint в приложении | Бизнес-метрики, SLI/SLO |
| **podman events** | Лог событий (create, start, stop) | Аудит, debugging, compliance |

---

## Практический блок

### 1. Быстрая диагностика через podman stats

```bash
# Live-метрики всех контейнеров
podman stats

# Вывод в формате table
podman stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"

# Снимок в JSON (для парсинга)
podman stats --format json

# Конкретный контейнер
podman stats my-app

# Без заголовков (для скриптов)
podman stats --no-stream --format "{{.Name}}: CPU={{.CPUPerc}} MEM={{.MemUsage}}"
```

### 2. События Podman (аудит и debugging)

```bash
# Все события в реальном времени
podman events

# Фильтрация по типу
podman events --filter event=start
podman events --filter event=died
podman events --filter event=oom

# Фильтрация по контейнеру
podman events --filter container=my-app

# Формат для логирования
podman events --format '{{.Time}} {{.Action}} {{.Name}}'

# Сохранение в файл (для аудита)
podman events --format '{{.Time}} {{.Action}} {{.Name}}' >> /var/log/podman-events.log
```

### 3. Деплой cAdvisor для Podman

#### Docker Compose (cAdvisor + Prometheus + Grafana)

```yaml
# docker-compose-monitoring.yml
version: '3.8'

services:
  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.6
    container_name: cadvisor
    privileged: true
    devices:
      - /dev/kmsg:/dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/containers:/var/lib/containers:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "8080:8080"
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:v3.14.0
    container_name: prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
    ports:
      - "9090:9090"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3000:3000"
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
```

#### Конфигурация Prometheus

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    # Фильтрация только Podman-контейнеров (опционально)
    metric_relabel_configs:
      - source_labels: [name]
        regex: '.+'
        target_label: container_name
```

### 4. Кастомный HTTP /metrics endpoint в приложении

#### Python (prometheus_client)

```python
from prometheus_client import Counter, Gauge, start_http_server
import time

# Метрики
http_requests_total = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
app_memory_bytes = Gauge('app_memory_bytes', 'Application memory usage')

def process_request():
    http_requests_total.labels(method='GET', endpoint='/api').inc()
    app_memory_bytes.set(get_memory_usage())

if __name__ == '__main__':
    start_http_server(8000)  # Метрики на :8000/metrics
    while True:
        process_request()
        time.sleep(1)
```

```bash
# Запуск контейнера с метриками
podman run -d -p 8000:8000 \
  -l prometheus_scrape=true \
  -l prometheus_port=8000 \
  -l prometheus_path=/metrics \
  my-app:latest
```

#### Go (prometheus/client_golang)

```go
package main

import (
    "net/http"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
    httpRequests = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "http_requests_total",
            Help: "Total HTTP requests",
        },
        []string{"method", "endpoint"},
    )
)

func init() {
    prometheus.MustRegister(httpRequests)
}

func main() {
    http.Handle("/metrics", promhttp.Handler())
    http.ListenAndServe(":8000", nil)
}
```

### 5. Настройка Grafana дашбордов

#### Импорт дашборда

1. Откройте Grafana (http://localhost:3000)
2. Добавьте Prometheus как источник данных (http://prometheus:9090)
3. Импортируйте дашборд:
   - ID **893** — Docker and System Monitoring (works with Podman)
   - ID **14282** — Container Metrics

#### Полезные PromQL запросы

```promql
# Использование CPU контейнером (в ядрах)
container_cpu_usage_seconds_total{container!=""}

# Использование памяти (в байтах)
container_memory_usage_bytes{container!=""}

# Сетевой I/O
container_network_receive_bytes_total{container!=""}
container_network_transmit_bytes_total{container!=""}

# Дисковый I/O
container_fs_reads_bytes_total{container!=""}
container_fs_writes_bytes_total{container!=""}

# Уровень заполнения диска
container_fs_avail_bytes{container!=""} / container_fs_limit_bytes{container!=""} * 100

# Количество перезапусков
container_restart_count{container!=""}
```

### 6. Мониторинг хранилища Podman

```bash
# Использование диска образами/контейнерами
podman system df

# Детальный вывод
podman system df -v

# Проверка overlay storage
podman system info | grep -A 10 "store"

# Мониторинг места на диске
df -h /var/lib/containers/storage
```

### 7. Алертинг в Prometheus

```yaml
# prometheus-rules.yml
groups:
  - name: podman_alerts
    rules:
      # Контейнер потребляет >80% CPU
      - alert: HighContainerCPU
        expr: container_cpu_usage_seconds_total{container!=""} > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage on container {{ $labels.name }}"
          
      # Контейнер потребляет >90% памяти
      - alert: HighContainerMemory
        expr: container_memory_usage_bytes{container!=""} / container_spec_memory_limit_bytes{container!=""} > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on container {{ $labels.name }}"
          
      # Контейнер не отвечает
      - alert: ContainerDown
        expr: up{job="cadvisor"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Container {{ $labels.name }} is down"
```

### 8. Интеграция с systemd

```ini
# /etc/systemd/system/podman-monitoring.service
[Unit]
Description=Podman Monitoring Stack
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/podman-compose -f /opt/monitoring/docker-compose-monitoring.yml up
ExecStop=/usr/bin/podman-compose -f /opt/monitoring/docker-compose-monitoring.yml down
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now podman-monitoring
```

---

## Дополнительная информация

### Сравнение методов сбора метрик

| Метод | Overhead | Гранулярность | Установка | Production |
|---|---|---|---|---|
| `podman stats` | Низкий | Хост | Встроено | Для debugging |
| cAdvisor | Средний | Контейнер | Compose | Рекомендуется |
| HTTP /metrics | Минимальный | Приложение | Код | Обязательно |

### Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| cAdvisor не видит контейнеры | Rootless Podman | Запуск cAdvisor с `--privileged` |
| Нет метрик по сети | Netavark | Обновить cAdvisor до v0.49+ |
| Высокий overhead | Частый scrape | Увеличить `scrape_interval` |
| Prometheus не хватает места | Долгое хранение | Настроить `retention.time` |

### Ссылки

- **[Prometheus: Обзор](../../Prometheus/overview.md)** — установка и настройка Prometheus
- **[Grafana: Обзор](../../Grafana/grafana_overview.md)** — установка и настройка Grafana
- **[cAdvisor](../../Prometheus/Exporters/cadvisor.md)** — деплой и конфигурация cAdvisor
- **[Node Exporter](../../Prometheus/Exporters/node_exporter.md)** — метрики хоста
- **[Podman stats](./podman_basic_commands.md)** — CLI-команды Podman
- **[Podman events](./podman_daemonless_architecture.md)** — система событий

# force reindex test
