# Bare-metal / On-Premise развёртывание Prometheus

## Определения

**Bare-metal развёртывание Prometheus** — установка и настройка Prometheus на физических серверах или виртуальных машинах без использования Kubernetes. Включает управление через systemd, статическую конфигурацию, file-based service discovery (`file_sd_configs`) и ручное масштабирование.

**file_sd_configs (File-Based Service Discovery)** — механизм Prometheus для динамического обнаружения целей через JSON/YAML-файлы. В отличие от API-based SD (Kubernetes, Consul), не требует внешних зависимостей — достаточно файловой системы. Идеален для on-premise сред с минимальной автоматизацией.

> **См. также:** [Service Discovery и Relabeling](../service_discovery_and_relabeling.md) — общие концепции SD; [Конфигурация](../configuration.md) — параметры prometheus.yml; [Установка через APT](./with_apt.md); [Capacity Planning](./capacity_planning.md).

---

## Базовые концепции

### Когда выбирать bare-metal

| Критерий | Bare-metal/VM | Kubernetes |
|:---|:---|:---|
| **Инфраструктура** | Физические серверы, VMware, Proxmox | K8s кластер |
| **Управление** | systemd + SSH | kubectl, Helm, Operator |
| **Service Discovery** | `file_sd`, `static_configs`, Consul SD | Kubernetes SD |
| **Масштабирование** | Ручное (добавление серверов) | Автоматическое (Operator) |
| **Обновление** | RPM/DEB пакеты или бинарники | Helm upgrade, Operator |
| **Сложность** | Низкая (2-3 сервера) | Средняя-высокая |

### Архитектура bare-metal стека

```
┌─────────────────────────────────────────────────────┐
│                  Monitoring Server                   │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ Prometheus   │  │ Alertmanager │  │ Grafana    │ │
│  │ (port 9090)  │  │ (port 9093)  │  │ (port 3000)│ │
│  └──────┬──────┘  └──────────────┘  └────────────┘ │
│         │                                            │
│  ┌──────┴──────────────────────────────────────┐    │
│  │         file_sd + static_configs            │    │
│  └──────────────────┬──────────────────────────┘    │
└─────────────────────┼───────────────────────────────┘
                      │ HTTP scrape (port 9100, etc.)
        ┌─────────────┼─────────────────────┐
        │             │                     │
   ┌────┴────┐  ┌────┴────┐          ┌────┴────┐
   │ Web-01  │  │ DB-01   │   ...    │ App-01  │
   │ :9100   │  │ :9104   │          │ :8080   │
   └─────────┘  └─────────┘          └─────────┘
     Node Exp.    Postgres Exp.        App metrics
```

### Рекомендуемая структура каталогов

```
/etc/prometheus/
├── prometheus.yml          # Основной конфиг
├── web-config.yml          # TLS, auth
├── rules/                  # Alerting + Recording rules
│   ├── node_alerts.yml
│   └── recording_rules.yml
├── file_sd/                # Цели для file_sd
│   ├── nodes.yml
│   ├── databases.yml
│   └── web_servers.yml
└── targets/                # Легаси static targets (опционально)

/var/lib/prometheus/        # TSDB data
├── chunks_head/
├── wal/
└── blocks/

/opt/prometheus/            # Бинарник и вспомогательные工具
├── prometheus
├── promtool
└── prometheus.yml.example
```

---

## Практические сценарии

### Установка Prometheus (бинарник + systemd)

```bash
# 1. Создание пользователя
useradd --no-create-home --shell /bin/false prometheus

# 2. Скачивание (замените версию)
PROM_VERSION=3.1.0
wget https://github.com/prometheus/prometheus/releases/download/v${PROM_VERSION}/prometheus-${PROM_VERSION}.linux-amd64.tar.gz
tar xzf prometheus-${PROM_VERSION}.linux-amd64.tar.gz

# 3. Установка бинарников
cp prometheus-${PROM_VERSION}.linux-amd64/prometheus /usr/local/bin/
cp prometheus-${PROM_VERSION}.linux-amd64/promtool /usr/local/bin/

# 4. Установка конфигов и веб-интерфейса
mkdir -p /etc/prometheus/rules /etc/prometheus/file_sd
cp prometheus-${PROM_VERSION}.linux-amd64/prometheus.yml /etc/prometheus/
cp -r prometheus-${PROM_VERSION}.linux-amd64/consoles /etc/prometheus/
cp -r prometheus-${PROM_VERSION}.linux-amd64/console_libraries /etc/prometheus/

# 5. Права
chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool
```

systemd unit:

```ini
# /etc/systemd/system/prometheus.service
[Unit]
Description=Prometheus Monitoring System
Documentation=https://prometheus.io/docs/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/var/lib/prometheus \
  --storage.tsdb.retention.time=30d \
  --storage.tsdb.retention.size=10GB \
  --web.listen-address=:9090 \
  --web.enable-lifecycle \
  --web.enable-admin-api \
  --storage.tsdb.wal-compression=true
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now prometheus
systemctl status prometheus
```

### Установка Node Exporter на хостах

```bash
# На КАЖДОМ мониторимом хосте
NODE Exp_VERSION=1.8.2
useradd --no-create-home --shell /bin/false node_exporter
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xzf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
cp node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/

# systemd unit
cat > /etc/systemd/system/node_exporter.service << 'EOF'
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
  --collector.systemd \
  --collector.processes
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now node_exporter
```

### Настройка file_sd_configs

file_sd — основной механизм обнаружения целей в on-premise среде. Файлы обновляются автоматически при изменении (Prometheus перечитывает их без перезапуска).

**Формат YAML (рекомендуется):**

```yaml
# /etc/prometheus/file_sd/nodes.yml
- targets:
    - 10.0.0.1:9100
    - 10.0.0.2:9100
    - 10.0.0.3:9100
  labels:
    env: production
    dc: dc1
    role: web

- targets:
    - 10.0.1.1:9100
    - 10.0.1.2:9100
  labels:
    env: production
    dc: dc1
    role: database
```

**Формат JSON (альтернатива):**

```json
[
  {
    "targets": ["10.0.0.1:9100", "10.0.0.2:9100"],
    "labels": {
      "env": "production",
      "dc": "dc1",
      "role": "web"
    }
  }
]
```

**Конфигурация Prometheus для file_sd:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'node'
    file_sd_configs:
      - files:
          - /etc/prometheus/file_sd/nodes.yml
        refresh_interval: 30s
    relabel_configs:
      # Формируем instance из target
      - source_labels: [__address__]
        regex: '(.+):\d+'
        target_label: instance
      # Добавляем role из labels
      - source_labels: [role]
        target_label: job
```

### Автоматическое обновление file_sd через Ansible

```yaml
# Роль Ansible для генерации file_sd файлов
- name: Generate file_sd targets
  template:
    src: file_sd_nodes.yml.j2
    dest: /etc/prometheus/file_sd/nodes.yml
    owner: prometheus
    group: prometheus
    mode: '0644'
  notify: reload prometheus

# Шаблон (templates/file_sd_nodes.yml.j2)
#---
#{% for host in groups['monitoring_targets'] %}
#- targets:
#    - "{{ hostvars[host]['ansible_host'] }}:{{ node_exporter_port | default(9100) }}"
#  labels:
#    env: "{{ hostvars[host]['env'] | default('production') }}"
#    dc: "{{ hostvars[host]['dc'] | default('unknown') }}"
#    role: "{{ hostvars[host]['role'] | default('generic') }}"
#{% endfor %}
```

### Обновление Prometheus (rolling)

```bash
# 1. Скачать новую версию
PROM_NEW=3.2.0
wget https://github.com/prometheus/prometheus/releases/download/v${PROM_NEW}/prometheus-${PROM_NEW}.linux-amd64.tar.gz
tar xzf prometheus-${PROM_NEW}.linux-amd64.tar.gz

# 2. Замена бинарников
cp prometheus-${PROM_NEW}.linux-amd64/prometheus /usr/local/bin/prometheus.new
cp prometheus-${PROM_NEW}.linux-amd64/promtool /usr/local/bin/promtool.new

# 3. Валидация конфига
/usr/local/bin/promtool.new check config /etc/prometheus/prometheus.yml
/usr/local/bin/promtool.new check rules /etc/prometheus/rules/*.yml

# 4. Атомарная замена
mv /usr/local/bin/prometheus.new /usr/local/bin/prometheus
mv /usr/local/bin/promtool.new /usr/local/bin/promtool

# 5. Перезапуск (данные в TSDB сохраняются)
systemctl restart prometheus

# 6. Верификация
curl -s http://localhost:9090/-/healthy
curl -s http://localhost:9090/api/v1/status/buildinfo | jq .data.version
```

### Настройка Alertmanager (bare-metal)

```yaml
# /etc/prometheus/alertmanager.yml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.corp.local:587'
  smtp_from: 'alertmanager@corp.local'
  smtp_auth_username: 'alertmanager'
  smtp_auth_password: '${SMTP_PASSWORD}'

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pager'
      group_wait: 10s
    - match:
        severity: warning
      receiver: 'slack'

receivers:
  - name: 'default'
    email_configs:
      - to: 'ops@corp.local'
  - name: 'pager'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_KEY}'
  - name: 'slack'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK}'
        channel: '#alerts'
        send_resolved: true
```

```bash
# Установка Alertmanager
ALERT_VERSION=0.28.0
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERT_VERSION}/alertmanager-${ALERT_VERSION}.linux-amd64.tar.gz
tar xzf alertmanager-${ALERT_VERSION}.linux-amd64.tar.gz
cp alertmanager-${ALERT_VERSION}.linux-amd64/alertmanager /usr/local/bin/
cp alertmanager-${ALERT_VERSION}.linux-amd64/amtool /usr/local/bin/

# systemd unit
cat > /etc/systemd/system/alertmanager.service << 'EOF'
[Unit]
Description=Alertmanager
After=network.target

[Service]
Type=simple
User=prometheus
ExecStart=/usr/local/bin/alertmanager \
  --config.file=/etc/prometheus/alertmanager.yml \
  --storage.path=/var/lib/alertmanager \
  --web.listen-address=:9093
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now alertmanager
```

### Базовые recording rules

```yaml
# /etc/prometheus/rules/recording_rules.yml
groups:
  - name: node_recording
    interval: 30s
    rules:
      - record: instance:node_cpu_utilization:ratio
        expr: 1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

      - record: instance:node_memory_utilization:ratio
        expr: 1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

      - record: instance:node_disk_utilization:ratio
        expr: 1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})

  - name: node_alerts
    rules:
      - alert: NodeHighCPU
        expr: instance:node_cpu_utilization:ratio > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on {{ $labels.instance }}"
          description: "CPU usage is {{ $value | humanizePercentage }}"

      - alert: NodeHighMemory
        expr: instance:node_memory_utilization:ratio > 0.90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory on {{ $labels.instance }}"

      - alert: NodeDiskSpaceLow
        expr: instance:node_disk_utilization:ratio > 0.85
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Disk space low on {{ $labels.instance }}"
```

---

## Дополнительная информация

### Безопасность bare-metal Prometheus

| Мера | Реализация |
|:---|:---|
| **TLS на Web UI** | `--web.config.file=web-config.yml` с секцией `tls_server_config` |
| **Basic Auth** | Секция `basic_auth_users` в `web-config.yml` |
| **Firewall** | Разрешить порты 9090 (Prometheus), 9093 (Alertmanager), 9100 (Node Exporter) только с monitoring-сервера |
| **RBAC через Nginx** | Reverse proxy с ограничением доступа к API |

```yaml
# web-config.yml
tls_server_config:
  cert_file: /etc/prometheus/tls/server.crt
  key_file: /etc/prometheus/tls/server.key
basic_auth_users:
  admin: $2y$12$hashed_password_here
```

### Мониторинг самого Prometheus (self-monitoring)

```yaml
# В prometheus.yml — scraping самого себя
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'alertmanager'
    static_configs:
      - targets: ['localhost:9093']
```

Ключевые метрики для саммониторинга:
- `prometheus_tsdb_head_series` — количество активных серий
- `prometheus_tsdb_storage_blocks_bytes` — размер TSDB
- `prometheus_rule_evaluation_duration_seconds` — время выполнения правил
- `prometheus_notifications_sent_total` — доставленные алерты
- `prometheus_config_last_reload_successful` — успешность перезагрузки конфига

### Миграция с Consul SD на file_sd

Если вы мигрируете с Consul на file_sd (или наоборот):

```bash
# Экспорт целей из Consul в file_sd формат
curl -s http://consul:8500/v1/catalog/service/node-exporter | \
  jq '[.[] | {targets: [.ServiceAddress + ":" + (.ServicePort | tostring)], labels: {env: .ServiceMeta.env, dc: .Node.Datacenter}}]' \
  > /etc/prometheus/file_sd/nodes.yml
```

### Ссылки

- [PrometheusGetting Started](https://prometheus.io/docs/prometheus/latest/getting_started/)
- [File-based Service Discovery](https://prometheus.io/docs/prometheus/latest/http_sd/)
- [systemd service](https://prometheus.io/docs/guides/systemd/)
