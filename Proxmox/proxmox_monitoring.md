# Мониторинг Proxmox через Prometheus и Grafana

## Определения

**pve-exporter (prometheus-pve-exporter)** — экспортер для Prometheus, собирающий метрики из Proxmox VE API: состояние узлов, VM/LXC, хранилищ, сети, кластера, HA и Ceph. Работает через REST API Proxmox, не требует агентов на узлах.

**node_exporter** — стандартный экспортер Prometheus для сбора системных метрик Linux: CPU, RAM, диск, сеть, файловые системы, systemd-сервисы. Устанавливается на каждый узел Proxmox.

**ipmi_exporter** — экспортер для сбора метрик аппаратного управления (IPMI/BMC): температура, питание, вентиляторы, состояние здоровья сервера.

**Alertmanager** — компонент стека Prometheus для маршрутизации, группировки и отправки алертов (email, Slack, Telegram, PagerDuty).

**textfile collector** — механизм node_exporter для сбора кастомных метрик из файлов. Используется для метрик, недоступных через стандартные экспортеры (кворум кластера, HA-состояние).

## Теоретический блок

### Архитектура мониторинга Proxmox

```
┌─────────────────────────────────────────────────────────────────┐
│                     Monitoring Stack                             │
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │  Prometheus  │────►│  Alertmanager│────►│  Slack/TG/   │    │
│  │              │     │              │     │  PagerDuty   │    │
│  └──────┬───────┘     └──────────────┘     └──────────────┘    │
│         │                                                        │
│         │ scrape                                                 │
│         ▼                                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Targets                                 │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │   │
│  │  │ pve-exporter│  │node_exporter│  │ipmi_exporter│     │   │
│  │  │   :9221     │  │   :9100     │  │   :9290     │     │   │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │   │
│  └─────────┼────────────────┼────────────────┼─────────────┘   │
│            │                │                │                   │
└────────────┼────────────────┼────────────────┼──────────────────┘
             │                │                │
             ▼                ▼                ▼
┌────────────────────────────────────────────────────────────────┐
│                Proxmox Cluster                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │  node1   │  │  node2   │  │  node3   │  │  BMC/IPMI│      │
│  │ (pve-exp │  │ (pve-exp │  │ (pve-exp │  │          │      │
│  │ +node_exp)│  │ +node_exp)│  │ +node_exp)│  │          │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
└────────────────────────────────────────────────────────────────┘
```

### Группы метрик Proxmox

| Группа | Источник | Ключевые метрики |
|--------|----------|-------------------|
| **Узлы** | pve-exporter | `pve_up`, `pve_cpu_usage`, `pve_memory_usage`, `pve_disk_usage` |
| **VM/LXC** | pve-exporter | `pve_vm_status`, `pve_vm_cpu_usage`, `pve_vm_memory_usage` |
| **Хранилища** | pve-exporter | `pve_storage_usage`, `pve_storage_avail` |
| **Сеть** | node_exporter | `node_network_receive_bytes_total`, `node_network_transmit_bytes_total` |
| **Диск** | node_exporter | `node_disk_io_time_seconds_total`, `node_filesystem_avail_bytes` |
| **Ceph** | pve-exporter / ceph_exporter | `ceph_osd_up`, `ceph_osd_utilization`, `ceph_pg_active` |
| **HA** | textfile collector | кворум, состояние CRM/LRM, fencing |
| **Аппаратура** | ipmi_exporter | `ipmi_temperature_celsius`, `ipmi_fan_speed_rpm`, `ipmi_voltage` |

### Proxmox API токен для pve-exporter

```bash
# Минимальные права: read-only на ноды и VM
pveum useradd monitoring@pam --comment "Prometheus monitoring"
pveum user token add monitoring@pam prometheus --privsep 0
# → Сохранить token_id и secret
```

## Практические сценарии

### Установка pve-exporter

```bash
# На сервере мониторинга (Debian/Ubuntu)
apt install -y prometheus-pve-exporter

# Конфигурация (/etc/default/prometheus-pve-exporter)
PVE_USER="monitoring@pam!prometheus"
PVE_PASSWORD="your-api-token-secret"
PVE_URL="https://pve1.example.com:8006"
PVE_VERIFY_SSL="false"

# systemd unit (/etc/systemd/system/prometheus-pve-exporter.service)
[Unit]
Description=Prometheus Proxmox Exporter
After=network.target

[Service]
Type=simple
User=prometheus-pve-exporter
EnvironmentFile=/etc/default/prometheus-pve-exporter
ExecStart=/usr/bin/prometheus-pve-exporter \
  --web.listen-address=":9221" \
  --pve.url="${PVE_URL}" \
  --pve.user="${PVE_USER}" \
  --pve.password="${PVE_PASSWORD}" \
  --pve.verify-ssl="${PVE_VERIFY_SSL}"
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now prometheus-pve-exporter
# Проверка: curl http://localhost:9221/metrics
```

### Установка node_exporter на узлах Proxmox

```bash
# На каждом узле Proxmox
useradd --no-create-home --shell /bin/false node_exporter

wget https://github.com/prometheus/node_exporter/releases/download/v1.8.2/node_exporter-1.8.2.linux-amd64.tar.gz
tar xzf node_exporter-1.8.2.linux-amd64.tar.gz
cp node_exporter-1.8.2.linux-amd64/node_exporter /usr/local/bin/

# systemd unit
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
  --collector.processes \
  --collector.tcpstat
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node_exporter
```

### Конфигурация Prometheus scrape

```yaml
# /etc/prometheus/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Proxmox узлы (pve-exporter)
  - job_name: "proxmox"
    static_configs:
      - targets:
          - "monitoring-server:9221"
    params:
      cluster:
        - "true"
    scrape_interval: 30s

  # Proxmox узлы (node_exporter)
  - job_name: "proxmox-nodes"
    static_configs:
      - targets:
          - "node1:9100"
          - "node2:9100"
          - "node3:9100"
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.+):(\d+)'
        target_label: instance
        replacement: '${1}'

  # Ceph (если используется)
  - job_name: "ceph"
    static_configs:
      - targets:
          - "node1:9283"
          - "node2:9283"
          - "node3:9283"

  # IPMI (аппаратный мониторинг)
  - job_name: "ipmi"
    static_configs:
      - targets:
          - "node1:9290"
          - "node2:9290"
          - "node3:9290"
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.+):\d+'
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: "localhost:9290"
```

### Кастомные метрики через textfile collector

```bash
# На каждом узле Proxmox
mkdir -p /var/lib/node_exporter/textfile_collector

# Cron job для экспорта кластерных метрик
cat > /usr/local/bin/proxmox-cluster-metrics.sh << 'SCRIPT'
#!/bin/bash
DIR="/var/lib/node_exporter/textfile_collector"

# Кворум кластера
QUORUM=$(pvecm status 2>/dev/null | grep -oP 'Quorate:\s+\K\w+')
echo "pve_cluster_quorum{status=\"${QUORUM}\"} 1" > "${DIR}/pve_cluster.prom.$$"

# Количество узлов
NODES=$(pvecm status 2>/dev/null | grep -oP 'Nodes:\s+\K\d+')
echo "pve_cluster_nodes ${NODES}" >> "${DIR}/pve_cluster.prom.$$"

# HA-ресурсы
HA_STARTED=$(ha-manager status 2>/dev/null | grep -c "started" || echo 0)
HA_ERROR=$(ha-manager status 2>/dev/null | grep -c "error" || echo 0)
echo "pve_ha_resources_started ${HA_STARTED}" >> "${DIR}/pve_cluster.prom.$$"
echo "pve_ha_resources_error ${HA_ERROR}" >> "${DIR}/pve_cluster.prom.$$"

# Ceph health
CEPH_HEALTH=$(ceph -s 2>/dev/null | grep "health:" | awk '{print $2}')
if [ -n "$CEPH_HEALTH" ]; then
  if [ "$CEPH_HEALTH" = "HEALTH_OK" ]; then
    echo "pve_ceph_health 1" >> "${DIR}/pve_cluster.prom.$$"
  else
    echo "pve_ceph_health 0" >> "${DIR}/pve_cluster.prom.$$"
  fi
fi

mv "${DIR}/pve_cluster.prom.$$" "${DIR}/pve_cluster.prom"
SCRIPT

chmod +x /usr/local/bin/proxmox-cluster-metrics.sh

# Crontab
echo "*/1 * * * * root /usr/local/bin/proxmox-cluster-metrics.sh" > /etc/cron.d/pve-metrics
```

### Правила алертинга (Alert Rules)

```yaml
# /etc/prometheus/rules/proxmox_alerts.yml
groups:
  - name: proxmox_cluster
    rules:
      # Кластер lost quorum
      - alert: ProxmoxClusterQuorumLost
        expr: pve_cluster_quorum{status="No"} == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Proxmox cluster lost quorum"
          description: "Cluster quorum is lost. Immediate action required."

      # Узел недоступен
      - alert: ProxmoxNodeDown
        expr: pve_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Proxmox node {{ $labels.node }} is down"
          description: "Node {{ $labels.node }} has been unreachable for more than 2 minutes."

      # Высокая загрузка CPU узла
      - alert: ProxmoxNodeHighCPU
        expr: pve_cpu_usage > 0.9
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "High CPU on node {{ $labels.node }}"
          description: "CPU usage on {{ $labels.node }} is above 90% for 15 minutes."

      # Мало памяти на узле
      - alert: ProxmoxNodeLowMemory
        expr: (1 - pve_memory_usage) < 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Low memory on node {{ $labels.node }}"
          description: "Available memory on {{ $labels.node }} is below 10%."

      # Хранилище заполнено
      - alert: ProxmoxStorageFull
        expr: (pve_storage_usage / pve_storage_total) > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Storage {{ $labels.storage }} on {{ $labels.node }} is {{ $value | humanizePercentage }} full"
          description: "Storage {{ $labels.storage }} is critically full. Risk of VM I/O errors."

      # VM в состоянии error
      - alert: ProxmoxVMError
        expr: pve_vm_status{status="stopped"} == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "VM {{ $labels.name }} ({{ $labels.vmid }}) is stopped"
          description: "VM {{ $labels.name }} has been stopped unexpectedly."

      # IO delay высокий
      - alert: ProxmoxHighIODelay
        expr: pve_disk_io_wait > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High IO delay on {{ $labels.node }}"
          description: "IO wait on {{ $labels.node }} is above 50% for 10 minutes."

  - name: proxmox_ha
    rules:
      # HA fencing сработал
      - alert: ProxmoxHAFencing
        expr: increase(pve_ha_fencing_count[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "HA fencing event detected on {{ $labels.node }}"
          description: "Fencing was triggered on node {{ $labels.node }}. Check node health."

      # HA ресурс в error
      - alert: ProxmoxHAResourceError
        expr: pve_ha_resources_error > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "HA resource in error state"
          description: "{{ $value }} HA resource(s) are in error state."

  - name: ceph_alerts
    rules:
      # Ceph не HEALTH_OK
      - alert: CephClusterNotHealthy
        expr: pve_ceph_health != 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Ceph cluster is not healthy"
          description: "Ceph cluster health is not OK. Check ceph status."

      # OSD упал
      - alert: CephOSDDown
        expr: ceph_osd_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Ceph OSD {{ $labels.osd }} is down"
          description: "OSD {{ $labels.osd }} is down. Data availability may be affected."

      # Ceph near full
      - alert: CephNearFull
        expr: ceph_osd_utilization > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Ceph OSD {{ $labels.osd }} is {{ $value }}% full"
          description: "OSD is nearing capacity. Plan expansion or cleanup."
```

### Настройка Alertmanager

```yaml
# /etc/alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m

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
      repeat_interval: 1h
    - match:
        severity: warning
      receiver: 'slack'
      repeat_interval: 4h

receivers:
  - name: 'default'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ .CommonAnnotations.summary }}'

  - name: 'pager'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#critical-alerts'
    pagerduty_configs:
      - service_key: '<pagerduty-key>'

  - name: 'slack'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#alerts'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

### Настройка Grafana дашбордов

**Рекомендуемые дашборды (Grafana.com):**

| ID | Название | Описание |
|----|----------|----------|
| 10347 | Proxmox Cluster Overview | Обзор кластера: узлы, VM, хранилища |
| 1860 | Node Exporter Full | Системные метрики Linux узлов |
| 11074 | Proxmox VE Dashboard | Узлы, VM, сеть, диск |
| 14031 | Ceph Cluster Dashboard | Мониторинг Ceph |

**Настройка datasource в Grafana:**

```json
{
  "name": "Prometheus",
  "type": "prometheus",
  "url": "http://prometheus-server:9090",
  "access": "proxy",
  "isDefault": true
}
```

**Ключевые PromQL запросы для дашбордов:**

```promql
# Обзор узлов
pve_up
pve_cpu_usage * 100
pve_memory_usage * 100

# VM по статусу
count by (status) (pve_vm_status)

# Топ-5 VM по CPU
topk(5, pve_vm_cpu_usage * 100)

# Использование хранилищ
pve_storage_usage / pve_storage_total * 100

# Сетевая активность узла
rate(node_network_receive_bytes_total{device=~"vmbr.*"}[5m])

# IO delay
pve_disk_io_wait

# Ceph OSD utilization
ceph_osd_utilization
```

### Интеграция с systemd-resolved (Proxmox)

```bash
# На сервере мониторинга, если используется systemd-resolved
cat > /etc/systemd/resolved.conf.d/monitoring.conf << 'EOF'
[Resolve]
DNS=127.0.0.1
FallbackDNS=8.8.8.8
Domains=~cluster.local
EOF

systemctl restart systemd-resolved
```

## Диагностика и устранение неполадок

### pve-exporter не собирает метрики

```bash
# Проверка доступности API
curl -k -H "Authorization: PVEAPIToken=monitoring@pam!prometheus=<SECRET>" \
  https://pve1:8006/api2/json/nodes

# Проверка логов pve-exporter
journalctl -u prometheus-pve-exporter -f

# Проверка метрик
curl http://localhost:9221/probe?target=https://pve1:8006
```

### node_exporter не отвечает

```bash
# Проверка статуса сервиса
systemctl status node_exporter

# Проверка порта
ss -tlnp | grep 9100

# Проверка firewall
iptables -L -n | grep 9100
```

### Prometheus не scrape targets

```bash
# Проверка конфигурации
promtool check config /etc/prometheus/prometheus.yml

# Просмотр targets в UI
# http://prometheus:9090/targets

# Проверка метрик
curl 'http://prometheus:9090/api/v1/query?query=pve_up'
```

### Высокое потребление памяти Prometheus

```yaml
# Оптимизация retention и storage
global:
  scrape_interval: 30s
  evaluation_interval: 30s

storage:
  tsdb:
    retention.time: 30d
    retention.size: 10GB
```

## Лучшие практики

1. **Отдельная сеть мониторинга**: Выделите VLAN/subnet для трафика метрик. Не смешивайте с пользовательским трафиком.

2. **Два экземпляра pve-exporter**: Для HA разверните 2+ инстанса pve-exporter за балансировщиком или через DNS round-robin.

3. **Scrape interval**: 15–30 секунд для node_exporter, 30–60 секунд для pve-exporter. Меньше 10s — перегрузка API Proxmox.

4. **Retention**: Храните метрики 30–90 дней для оперативного мониторинга, 1+ год для capacity planning.

5. **Alert routing**: Настраивайте разные получателей для warning и critical. Критические алерты — немедленно в PagerDuty/Telegram, warning — в Slack.

6. **Группировка алертов**: Не спамьте — группируйте по узлу/сервису с `group_wait: 30s`.

7. **IPMI мониторинг**: Обязательно настройте ipmi_exporter для отслеживания температуры, питания и вентиляторов. Аппаратные сбои — основная причина простоев.

8. **Ceph метрики**: Если используется Ceph, включите `ceph_exporter` или встроенные метрики Ceph Manager.

9. **Резервное копирование конфигурации**: Храните `prometheus.yml`, правила алертов и Grafana дашборды в Git.

10. **Тестирование алертов**: Регулярно проверяйте, что алерты срабатывают корректно. Используйте `promtool test rules` для тестирования.

## Граничные случаи

- **pve-exporter и кластер**: Один экземрляр pve-exporter опрашивает все узлы кластера через API одного узла. При недоступности этого узла метрики других узлов также не собираются. Решение: несколько pve-exporter с разными target-узлами.

- **vmbr интерфейсы**: node_exporter показывает метрики для `vmbr*` интерфейсов, но без разбивки по VM. Для агрегации трафика по VM используйте `ebtables` или eBPF.

- **Ceph метрики**: В гиперконвергентном кластере Ceph метрики доступны через `ceph_exporter` (порт 9283) или через Prometheus module в Ceph Manager.

- **API rate limiting**: При большом количестве scrape-источников Proxmox API может начать отвечать медленно. Мониторьте latency pve-exporter.

## Дополнительная информация

### Связанные темы

- [Prometheus — Обзор](../Prometheus/overview.md)
- [Prometheus — Экспортеры](../Prometheus/Exporters/node_exporter/node_exporter.md)
- [Grafana — Обзор](../Grafana/grafana_overview.md)
- [Обзор Proxmox VE](./proxmox_overview.md)
- [Кластеризация и HA](./proxmox_cluster.md)
