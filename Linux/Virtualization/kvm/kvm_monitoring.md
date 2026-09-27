# Мониторинг KVM: Prometheus, libvirt_exporter, Grafana

В данном файле описывается построение системы мониторинга KVM-хостов и виртуальных машин с использованием Prometheus, libvirt_exporter и Grafana. Методы ручной диагностики представлены в [Диагностика и решение проблем](./troubleshooting.md), а инструменты в реальном времени — в [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md).

## Определения

**Prometheus** — система мониторинга и алертинга с pull-моделью сбора метрик. Хранит данные в Time-Series Database (TSDB), предоставляет PromQL для анализа и интегрируется с Grafana для визуализации.

**libvirt_exporter** — экспортер Prometheus для сбора метрик libvirt: состояние ВМ, потребление CPU/RAM, сетевой трафик, дисковый I/O, статус гостевого агента.

**node_exporter** — экспортер Prometheus для сбора системных метрик хоста: CPU, RAM, диск, сеть, система, процессы.

**kvm_stat** — утилита для мониторинга событий KVM в реальном времени: VM-Exit, MMIO, EPT miss, halt.

**Alertmanager** — компонент Prometheus для маршрутизации и отправки алертов (email, Slack, PagerDuty, webhook).

**Grafana** — платформа для визуализации метрик. Подключается к Prometheus как datasource и предоставляет дашборды для мониторинга KVM.

**Steal Time** — время, в течение которого vCPU ВМ ожидал физический CPU из-за перегрузки хоста или конкуренции за ресурсы.

## Базовые концепции

### Архитектура стека мониторинга

Мониторинг KVM строится на нескольких уровнях сбора метрик.

**Уровни сбора:**
- **Хост (L0):** node_exporter собирает метрики ОС: CPU, RAM, диск, сеть, температура.
- **Гипервизор (L0):** libvirt_exporter собирает метрики libvirt: состояние ВМ, vCPU, память.
- **Гостевая ОС (L1):** node_exporter внутри ВМ собирает метрики гостя.
- **KVM Events:** kvm_stat показывает аппаратные события (VM-Exits, MMIO).

**Схема потока данных:**
```
node_exporter ──┐
                ├──→ Prometheus ──→ Grafana (дашборды)
libvirt_exporter┘        │
                         ├──→ Alertmanager ──→ Slack/PagerDuty
                         │
node_exporter (VM) ──────┘
```

### Метрики libvirt_exporter

libvirt_exporter предоставляет следующие метрики для мониторинга ВМ.

**Ключевые метрики:**

| Метрика | Описание | Тип |
| :--- | :--- | :--- |
| `libvirt_domain_info_vcpu_time` | Время CPU в наносекундах на vCPU | counter |
| `libvirt_domain_info_memory_stats_rss` | Фактический RSS (resident set size) ВМ | gauge |
| `libvirt_domain_info_memory_stats_actual` | Текущий выделенный объём памяти | gauge |
| `libvirt_domain_info_balloon_current` | Размер balloon (возвращённая память) | gauge |
| `libvirt_domain_info_balloon_target` | Целевой размер balloon | gauge |
| `libvirt_domain_block_stats_read_bytes` | Суммарные байты чтения с диска | counter |
| `libvirt_domain_block_stats_write_bytes` | Суммарные байты записи на диск | counter |
| `libvirt_domain_block_stats_read_requests` | Количество операций чтения | counter |
| `libvirt_domain_block_stats_write_requests` | Количество операций записи | counter |
| `libvirt_domain_interface_stats_rx_bytes` | Входящий сетевой трафик | counter |
| `libvirt_domain_interface_stats_tx_bytes` | Исходящий сетевой трафик | counter |
| `libvirt_domain_state` | Состояние ВМ (running=1, paused=0, shutdown=-1) | gauge |

**Примеры PromQL запросов:**
```promql
# Количество запущенных ВМ
sum(libvirt_domain_state{state="running"}) by (instance)

# Потребление памяти всеми ВМ
sum(libvirt_domain_info_memory_stats_actual) by (instance, domain)

# Steal Time в процентах (через node_exporter)
100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

# Сетевой трафик ВМ (MB/s)
rate(libvirt_domain_interface_stats_rx_bytes_total[5m]) / 1024 / 1024
rate(libvirt_domain_interface_stats_tx_bytes_total[5m]) / 1024 / 1024

# Дисковый IOPS
rate(libvirt_domain_block_stats_read_requests_total[5m])
rate(libvirt_domain_block_stats_write_requests_total[5m])
```

### Установка и настройка экспортеров

**1. libvirt_exporter (на KVM-хосте):**
```bash
# Установка из исходников
git clone https://github.com/kumina/libvirt_exporter.git
cd libvirt_exporter
go build -o libvirt_exporter

# Настройка systemd-юнита
cat > /etc/systemd/system/libvirt_exporter.service << 'EOF'
[Unit]
Description=Prometheus libvirt exporter
After=network.target libvirtd.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/libvirt_exporter \
  --web.listen-address=":9177"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now libvirt_exporter

# Проверка
curl http://localhost:9177/metrics
```

**2. node_exporter (на KVM-хосте):**
```bash
# Установка
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar xzf node_exporter-*.tar.gz
mv node_exporter-*/node_exporter /usr/local/bin/

# Systemd
cat > /etc/systemd/system/node_exporter.service << 'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
Type=simple
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
  --web.listen-address=":9100" \
  --collector.systemd \
  --collector.processes
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node_exporter
```

**3. Prometheus scrape конфигурация:**
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'kvm-hosts'
    static_configs:
      - targets:
          - 'kvm-host-01:9100'   # node_exporter
          - 'kvm-host-01:9177'   # libvirt_exporter
          - 'kvm-host-02:9100'
          - 'kvm-host-02:9177'
    metrics_path: /metrics

  - job_name: 'kvm-vms'
    static_configs:
      - targets:
          - 'vm-web-01:9100'     # node_exporter внутри ВМ
          - 'vm-db-01:9100'
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
        regex: '(.+):9100'
        replacement: '${1}'

rule_files:
  - 'kvm_alerts.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'alertmanager:9093'
```

### Алертинг правила для KVM

**kvm_alerts.yml:**
```yaml
groups:
  - name: kvm_alerts
    rules:
      # ВМ не запущена
      - alert: VMNotRunning
        expr: libvirt_domain_state{state="running"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "VM {{ $labels.domain }} не запущена"
          description: "ВМ {{ $labels.domain }} на {{ $labels.instance }} находится в состоянии {{ $labels.state }} более 5 минут."

      # Высокий Steal Time
      - alert: HighStealTime
        expr: |
          100 - (avg by(instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий Steal Time на {{ $labels.instance }}"
          description: "Steal Time превышает 10% на хосте {{ $labels.instance }} в течение 10 минут."

      # Критический уровень памяти хоста
      - alert: HostMemoryCritical
        expr: |
          (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100 > 95
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Критический уровень памяти на {{ $labels.instance }}"
          description: "Использование памяти превышает 95% на хосте {{ $labels.instance }}."

      # Дисковое пространство заканчивается
      - alert: StoragePoolFull
        expr: |
          (1 - node_filesystem_avail_bytes{mountpoint="/var/lib/libvirt/images"} / node_filesystem_size_bytes{mountpoint="/var/lib/libvirt/images"}) * 100 > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Пул хранилища заполнен на {{ $value }}%"
          description: "Использование хранилища /var/lib/libvirt/images превышает 85%."

      # Balloon не работает (память ВМ не перераспределяется)
      - alert: BalloonNotWorking
        expr: |
          libvirt_domain_info_balloon_target > 0 and libvirt_domain_info_balloon_current == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Balloon не работает в {{ $labels.domain }}"
          description: "Виртуальный баллон установлен, но не забирает память у ВМ."

      # Высокий I/O на диске
      - alert: HighDiskIOPS
        expr: |
          rate(libvirt_domain_block_stats_read_requests_total[5m]) > 10000 or
          rate(libvirt_domain_block_stats_write_requests_total[5m]) > 10000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий IOPS на диске ВМ {{ $labels.domain }}"
          description: "Скорость операций ввода-вывода превышает 10 000 IOPS."

      # Сетевая потеря пакетов
      - alert: NetworkPacketLoss
        expr: |
          rate(node_network_receive_drop_total{device="veth*"}[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Сетевые потери на {{ $labels.instance }}"
          description: "Потери пакетов превышают 100 pps на интерфейсе {{ $labels.device }}."

      # QEMU process остановился
      - alert: QEMUProcessDown
        expr: |
          absent(process_running{comm="qemu-system-x86"})
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "QEMU-процесс не найден"
          description: "Процесс qemu-system-x86 не обнаружен на хосте {{ $labels.instance }}."
```

## Практические сценарии

### Сценарий 1: Полная установка стека мониторинга

Развертывание Prometheus + Alertmanager + Grafana через Docker Compose.

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./kvm_alerts.yml:/etc/prometheus/kvm_alerts.yml
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
    ports:
      - "9090:9090"
    restart: unless-stopped

  alertmanager:
    image: prom/alertmanager:latest
    container_name: alertmanager
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml
    ports:
      - "9093:9093"
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin123
      - GF_INSTALL_PLUGINS=grafana-clock-panel,grafana-piechart-panel
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    restart: unless-stopped

  libvirt-exporter:
    image: quay.io/kumina/libvirt_exporter:latest
    container_name: libvirt-exporter
    pid: host  # Требуется для доступа к процессам libvirt
    volumes:
      - /var/run/libvirt:/var/run/libvirt:ro
      - /dev/kvm:/dev/kvm:ro
    command:
      - '--web.listen-address=:9177'
    ports:
      - "9177:9177"
    restart: unless-stopped

volumes:
  prometheus_data:
  grafana_data:
```

**Запуск:**
```bash
docker compose up -d
# Проверка
curl http://localhost:9177/metrics  # libvirt_exporter
curl http://localhost:9090/api/v1/targets  # Prometheus
# http://localhost:3000  # Grafana (admin/admin123)
```

### Сценарий 2: Настройка Grafana-дашборда для KVM

**1. Добавление Prometheus как datasource:**
```bash
# Через provisioning (автоматически)
cat > /etc/grafana/provisioning/datasources/prometheus.yml << 'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
EOF
```

**2. Импорт дашборда:**
```bash
# Дашборд по умолчанию: ID 12198 (KubeVirt Overview)
# Или создание кастомного через JSON:
{
  "dashboard": {
    "title": "KVM Host Overview",
    "panels": [
      {
        "title": "Running VMs",
        "type": "stat",
        "targets": [{
          "expr": "sum(libvirt_domain_state{state='running'}) by (instance)",
          "legendFormat": "{{ instance }}"
        }]
      },
      {
        "title": "Host CPU Usage",
        "type": "graph",
        "targets": [{
          "expr": "100 - (avg by(instance) (irate(node_cpu_seconds_total{mode='idle'}[5m])) * 100)",
          "legendFormat": "{{ instance }}"
        }]
      },
      {
        "title": "VM Memory Usage",
        "type": "graph",
        "targets": [{
          "expr": "libvirt_domain_info_memory_stats_actual / 1024 / 1024 / 1024",
          "legendFormat": "{{ domain }}"
        }]
      },
      {
        "title": "Disk I/O",
        "type": "graph",
        "targets": [{
          "expr": "rate(libvirt_domain_block_stats_read_bytes_total[5m]) / 1024 / 1024",
          "legendFormat": "{{ domain }} read"
        }, {
          "expr": "rate(libvirt_domain_block_stats_write_bytes_total[5m]) / 1024 / 1024",
          "legendFormat": "{{ domain }} write"
        }]
      },
      {
        "title": "Network Traffic",
        "type": "graph",
        "targets": [{
          "expr": "rate(libvirt_domain_interface_stats_rx_bytes_total[5m]) / 1024 / 1024",
          "legendFormat": "{{ domain }} rx"
        }, {
          "expr": "rate(libvirt_domain_interface_stats_tx_bytes_total[5m]) / 1024 / 1024",
          "legendFormat": "{{ domain }} tx"
        }]
      }
    ]
  }
}
```

### Сценарий 3: Использование kvm_stat в реальном времени

Мониторинг событий KVM без Prometheus — для быстрой диагностики.

**Установка:**
```bash
# Ubuntu/Debian
sudo apt install -y linux-tools-common linux-tools-$(uname -r)

# RHEL/Rocky
sudo dnf install -y kernel-tools
```

**Использование:**
```bash
# Вывод каждые 5 секунд (5 снимков)
sudo kvm_stat -1 5

# Фильтрация по событиям
sudo kvm_stat -x -1 3

# Дифференциальный анализ (до/после нагрузки)
sudo kvm_stat -c 10 > before_load.txt
# ... запуск нагрузки ...
sudo kvm_stat -c 10 > after_load.txt
diff before_load.txt after_load.txt

# Интерпретация результатов:
# exits > 100,000/сек на ядро — высокий overhead из-за VM-Exit
# halt_exits > 50,000/сек — нехватка CPU на хосте
# mmio_exits > 10,000/сек — использование эмулируемых устройств вместо VirtIO
# ept_mis > 10,000/сек — проблемы с трансляцией страниц
```

### Сценарий 4: Дашборд для отдельных ВМ

Создание per-VM дашборда в Grafana для детального мониторинга.

**PromQL для per-VMI метрик:**
```promql
# CPU Utilization по ядрам
sum(rate(libvirt_domain_info_vcpu_time_total[5m])) by (domain, vcpu) / 1e9 * 100

# Memory Working Set (RSS)
libvirt_domain_info_memory_stats_rss / 1024 / 1024

# Memory Balloon Effectiveness
(libvirt_domain_info_memory_stats_actual - libvirt_domain_info_balloon_current) / libvirt_domain_info_memory_stats_actual * 100

# Disk Latency (если есть block stats)
rate(libvirt_domain_block_stats_read_bytes_total[5m]) / rate(libvirt_domain_block_stats_read_requests_total[5m])

# Network Throughput
rate(libvirt_domain_interface_stats_rx_bytes_total[5m])
rate(libvirt_domain_interface_stats_tx_bytes_total[5m])
```

**JSON дашборда (фрагмент):**
```json
{
  "panels": [
    {
      "title": "VM {{ domain }} - CPU",
      "type": "timeseries",
      "targets": [{
        "expr": "sum(rate(libvirt_domain_info_vcpu_time_total{domain=~\"$vm\"}[5m])) by (vcpu) / 1e9 * 100",
        "legendFormat": "vCPU {{ vcpu }}"
      }],
      "fieldConfig": {
        "defaults": {
          "unit": "percent",
          "min": 0,
          "max": 100
        }
      }
    }
  ],
  "templating": {
    "list": [{
      "name": "vm",
      "type": "query",
      "query": "label_values(libvirt_domain_state, domain)",
      "refresh": 2
    }]
  }
}
```

### Сценарий 5: Алертинг через Alertmanager

**alertmanager.yml:**
```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'instance']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'slack'

  routes:
    - match:
        severity: critical
      receiver: 'pagerduty'

receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#kvm-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}\n{{ .Annotations.description }}{{ end }}'

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '<pagerduty-key>'
        severity: '{{ if eq .GroupLabels.severity "critical" }}critical{{ else }}warning{{ end }}'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — теория KVM/QEMU/libvirt.
- [Диагностика и решение проблем](./troubleshooting.md) — ручная диагностика, kvm_stat, логи.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — kvm_stat, turbostat, QMP.
- [Prometheus: Обзор](../../Prometheus/prometheus_overview.md) — архитектура и PromQL.
- [Grafana: Обзор](../../Grafana/grafana_overview.md) — визуализация и дашборды.
- [Alertmanager](../../Prometheus/Alertmanager/alertmanager_overview.md) — маршрутизация алертов.
- [node_exporter](../../Prometheus/Exporters/node_exporter/node_exporter_overview.md) — системные метрики.
