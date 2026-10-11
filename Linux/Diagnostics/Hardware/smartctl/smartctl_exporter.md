# smartctl_exporter: установка и настройка

## Определения

**`smartctl_exporter`** — официальный Prometheus-exporter для сбора метрик S.M.A.R.T. из физических накопителей. Опрашивает `smartctl` с настраиваемым интервалом и предоставляет метрики через HTTP-эндпоинт `/metrics` (по умолчанию порт `:9633`).

**`/etc/smartctl_exporter.yml`** — конфигурационный файл exporter, определяjący интервал опроса, фильтрацию устройств, exclusions и SSL/TLS-настройки.

---

## Базовые концепции

### Архитектура сбора метрик

```
smartctl_exporter  →  smartctl  →  /dev/sdX, /dev/nvmeXnY
       ↓
HTTP :9633/metrics
       ↓
Prometheus (scrape)  →  Grafana / Alertmanager
```

### Ключевые метрики

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `smartctl_device_healthy` | Gauge | 1 — диск исправен, 0 — неисправен |
| `smartctl_device_temperature_celsius` | Gauge | Текущая температура |
| `smartctl_device_percentage_used` | Gauge | Износ SSD (% от TBW) |
| `smartctl_device_available_spare` | Gauge | Доступные резервные блоки (%) |
| `smartctl_device_critical_warning` | Gauge | Битовая маска критических предупреждений (0 = OK) |
| `smartctl_device_power_cycle_count` | Gauge | Количество циклов включения/выключения |
| `smartctl_device_power_on_hours` | Gauge | Часы работы |
| `smartctl_device_media_errors` | Gauge | Ошибки целостности данных |
| `smartctl_device_program_fail_count` | Gauge | Ошибки программирования NAND |
| `smartctl_device_erase_fail_count` | Gauge | Ошибки стирания NAND |
| `smartctl_device_reallocated_sector_count` | Gauge | Переназначенные сектора (HDD) |
| `smartctl_device_pending_sector_count` | Gauge | Ожидающие переназначения сектора (HDD) |
| `smartctl_device_udma_crc_error_count` | Gauge | CRC-ошибки шины (HDD) |

### Пороговые значения для алертинга

| Метрика | Warning | Critical | Действие |
| :--- | :--- | :--- | :--- |
| `smartctl_device_temperature_celsius` | > 50 (HDD), > 70 (NVMe) | > 55 (HDD), > 80 (NVMe) | Проверка охлаждения |
| `smartctl_device_percentage_used` | > 80 | > 95 | Плановая / срочная замена |
| `smartctl_device_available_spare` | < 20 | < 10 | Плановая / срочная замена |
| `smartctl_device_critical_warning` | != 0 | != 0 | Немедленная замена |
| `smartctl_device_reallocated_sector_count` | > 0 (рост) | > 50 | Плановая замена |

---

## Практические сценарии

### Установка (бинарник)

```bash
# Скачивание последнего релиза
SMARTCTL_EXPORTER_VERSION="0.12.0"
wget https://github.com/prometheus-community/smartctl_exporter/releases/download/v${SMARTCTL_EXPORTER_VERSION}/smartctl_exporter-${SMARTCTL_EXPORTER_VERSION}.linux-amd64.tar.gz

tar xzf smartctl_exporter-${SMARTCTL_EXPORTER_VERSION}.linux-amd64.tar.gz
sudo cp smartctl_exporter-${SMARTCTL_EXPORTER_VERSION}.linux-amd64/smartctl_exporter /usr/local/bin/
sudo chmod +x /usr/local/bin/smartctl_exporter
```

### Конфигурационный файл

Создайте `/etc/smartctl_exporter.yml`:

```yaml
smartctl:
  path: /usr/sbin/smartctl
  interval: 60s
  devices:
    - /dev/sda
    - /dev/sdb
    - /dev/nvme0n1
  # Или автообнаружение (все поддерживаемые устройства):
  # devices: []

exclude:
  # Исключить устройства по регулярному выражению
  - "/dev/loop.*"
  - "/dev/ram.*"

smartctl_exporter:
  # Порт HTTP-сервера
  listen_address: ":9633"
  # Максимальное количество параллельных запросов smartctl
  max_parallel: 4
  # Таймаут на один запрос smartctl
  timeout: 30s
  # Логирование неудачных запросов
  log_failed_scrape: true
```

### Systemd-служба

Создайте `/etc/systemd/system/smartctl_exporter.service`:

```ini
[Unit]
Description=Prometheus smartctl_exporter
Documentation=https://github.com/prometheus-community/smartctl_exporter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=smartctl_exporter
Group=smartctl_exporter
ExecStart=/usr/local/bin/smartctl_exporter \
  --config.file=/etc/smartctl_exporter.yml \
  --web.listen-address=:9633
Restart=always
RestartSec=5

# Безопасность
NoNewPrivileges=no
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/smartctl_exporter
CapabilityBoundingSet=CAP_SYS_RAWIO
AmbientCapabilities=CAP_SYS_RAWIO

[Install]
WantedBy=multi-user.target
```

```bash
# Создание пользователя для сервиса
sudo useradd --system --no-create-home --shell /usr/sbin/nologin smartctl_exporter

# Даём права на чтение SMART-данных
sudo usermod -aG disk smartctl_exporter

# Запуск и автозагрузка
sudo systemctl daemon-reload
sudo systemctl enable --now smartctl_exporter
```

### Docker-контейнер

```bash
docker run -d \
  --name smartctl-exporter \
  --restart=unless-stopped \
  --privileged \
  -p 9633:9633 \
  -v /dev:/dev:ro \
  -v /usr/sbin/smartctl:/usr/sbin/smartctl:ro \
  prometheus/smartctl_exporter:latest \
  --config.file=/etc/smartctl_exporter.yml
```

Или с минимальными привилегиями:

```bash
docker run -d \
  --name smartctl-exporter \
  --restart=unless-stopped \
  --cap-add SYS_RAWIO \
  --device /dev/sda:/dev/sda:ro \
  --device /dev/nvme0n1:/dev/nvme0n1:ro \
  -p 9633:9633 \
  prometheus/smartctl_exporter:latest
```

### Docker Compose

```yaml
version: '3.8'
services:
  smartctl-exporter:
    image: prometheus/smartctl_exporter:latest
    container_name: smartctl-exporter
    restart: unless-stopped
    cap_add:
      - SYS_RAWIO
    devices:
      - /dev/sda:/dev/sda:ro
      - /dev/nvme0n1:/dev/nvme0n1:ro
    ports:
      - "9633:9633"
    volumes:
      - ./smartctl_exporter.yml:/etc/smartctl_exporter.yml:ro
```

### Настройка Prometheus scrape

#### Standalone Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "smartctl"
    static_configs:
      - targets: ["server1:9633", "server2:9633"]
    scrape_interval: 60s
```

#### File-based Service Discovery

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "smartctl"
    file_sd_configs:
      - files:
          - "/etc/prometheus/targets/smartctl.yml"
        refresh_interval: 5m

# /etc/prometheus/targets/smartctl.yml:
# - targets:
#     - "server1:9633"
#     - "server2:9633"
#   labels:
#     env: "production"
```

#### Kubernetes ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: smartctl-exporter
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: smartctl-exporter
  endpoints:
    - port: metrics
      interval: 60s
```

### Пример alerting-правил (Prometheus rules)

```yaml
groups:
  - name: smartctl_alerts
    rules:
      - alert: DiskTemperatureHigh
        expr: smartctl_device_temperature_celsius > 55
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Disk {{ $labels.device }} temperature high"
          description: "Temperature is {{ $value }}°C on {{ $labels.instance }}"

      - alert: DiskSSDWearHigh
        expr: smartctl_device_percentage_used > 80
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "SSD {{ $labels.device }} wear is {{ $value }}%"
          description: "Disk is approaching end of life. Plan replacement."

      - alert: DiskCriticalWarning
        expr: smartctl_device_critical_warning != 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Disk {{ $labels.device }} has critical SMART warning"
          description: "Immediate backup and replacement required."

      - alert: DiskReallocatedSectors
        expr: increase(smartctl_device_reallocated_sector_count[24h]) > 10
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Disk {{ $labels.device }} has {{ $value }} new reallocated sectors in 24h"

      - alert: DiskExporterDown
        expr: up{job="smartctl"} == 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "smartctl_exporter is down on {{ $labels.instance }}"
```

### Верификация работы

```bash
# Проверка, что exporter отвечает
curl -s http://localhost:9633/metrics | head -20

# Проверка конкретных метрик
curl -s http://localhost:9633/metrics | grep smartctl_device_temperature

# Проверка, что Prometheus видит target
curl -s http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job == "smartctl")'
```

---

## Дополнительная информация

### Фильтрация устройств

Если в системе есть loopback- или RAM-диски, исключите их:

```yaml
smartctl:
  devices:
    # Явное указание только нужных устройств:
    - /dev/sda
    - /dev/nvme0n1
    # Или паттерн (поддерживается не всеми версиями):
    # - /dev/sd[a-z]
```

### Производительность

- **Интервал опроса:** 60 секунд — баланс между актуальностью и нагрузкой. Для HDD в критичных системах можно降至 30s.
- **Параллельность:** При большом количестве дисков (>20) увеличьте `max_parallel` до 8, чтобы избежать таймаутов.
- **Влияние на I/O:** `smartctl -A` — быстрая операция (не более 100мс на диск). `smartctl -t long` запускайте отдельно, exporter его не вызывает.

### Интеграция с Grafana

Официальный дашборд: [Grafana Dashboard #12893](https://grafana.com/grafana/dashboards/12893) — smartctl_exporter.

Импорт через UI: **Dashboards → New → Import**, введите ID `12893` и подтвердите. Либо скачайте JSON дашборда через Grafana.com API (`https://grafana.com/api/dashboards/12893/revisions/latest/download`) и загрузите его на странице импорта.

### Кросс-ссылки

- [Главная страница: smartctl](./index.md) — навигация и инструменты.
- [Автоматический мониторинг (smartd)](./smartd_monitoring.md) — конфигурация демона мониторинга.
- [Проверка здоровья дисков](./disk_health_check.md) — пошаговые тесты.
- [Мониторинг SMART в Kubernetes](./smartctl_kubernetes.md) — DaemonSet для K8s.
- [Решение проблем (Troubleshooting)](./troubleshooting.md) — ошибки доступа.
