# Мониторинг Proxmox VE (Prometheus, Grafana, Alertmanager)

**Актуально для:** Proxmox VE 8.x / 9.x, prometheus-pve-exporter ≥ 3.5 (метрики с `_bytes` / `pve_cpu_usage_ratio`), Node Exporter v1.12.x, Prometheus 3.x

## Определения

**prometheus-pve-exporter (pve-exporter)** — экспортер Prometheus, собирающий данные через REST API Proxmox (`/api2/json`): узлы, QEMU/LXC, хранилища, HA, репликация, подписка, QDevice, гости без backup-джобы. Агенты на узлах PVE не нужны; работает с одного host, опрашивающего target через параметр `target=`. HTTP-путь метрик — **`/pve`** (не `/metrics`).

**node_exporter** — системные метрики Linux (CPU, RAM, диск, сеть, filesystem, systemd, hwmon). Ставится на **каждый** узел PVE. Полный SSoT — [Node Exporter](../Prometheus/Exporters/node_exporter.md).

**ipmi_exporter** — метрики BMC/IPMI (питание, вентиляторы, температура). SSoT — [IPMI/BMC](../Prometheus/Exporters/ipmi_exporter.md).

**textfile collector** — коллектор node_exporter: читает `*.prom` из каталога. Подходит для значений, которых нет в pve-exporter (например, `pvecm status` → кворум corosync).

**Alertmanager** — маршрутизация и группировка алертов. Конфигурация маршрутов — SSoT [Alertmanager](../Prometheus/alertmanager.md); здесь — только PVE-специфичные примеры.

**Blackbox exporter** — probing внешних endpoint’ов (HTTPS API PVE на :8006, web UI) по HTTP/TCP/ICMP.

**ID гостя в метриках pve-exporter** — единый label `id` формы `node/<name>`, `qemu/<vmid>`, `lxc/<vmid>`, `storage/<node>/<storage>`, `cluster/<…>`. Все ресурсные метрики фильтруются через `id`, а не через отдельные label’ы `node=`/`vmid=`.

## Теоретический блок

### Архитектура

```text
                    ┌──────────────┐     ┌──────────────┐
                    │ Alertmanager │◄────│  Prometheus  │
                    │  (routes,    │     │  (scrape,    │
                    │   inhibit)   │     │   rules)     │
                    └──────┬───────┘     └──────┬───────┘
                           │                    │ scrape
              Slack/TG/PD  ▼                    ▼
                    ┌──────────────────────────────────────┐
                    │ Targets                              │
                    │  pve-exporter :9221  (/pve?target=…) │
                    │  node_exporter :9100 (на каждом PVE) │
                    │  ipmi_exporter :9290 (BMC)           │
                    │  ceph mgr      :9283 (если Ceph)     │
                    │  blackbox      :9115 (probe :8006)   │
                    └──────────────────┬───────────────────┘
                                       │ HTTPS API / agents
                                       ▼
                    ┌──────────────────────────────────────┐
                    │ PVE cluster  node1 / node2 / node3   │
                    │  pve-cluster, pvedaemon, HA, storage │
                    └──────────────────────────────────────┘
```

### Модель данных pve-exporter (актуальные имена)

> Выдуманные имена вроде `pve_cpu_usage`, `pve_vm_status`, `pve_storage_avail` **не существуют**. Ниже — метрики upstream [prometheus-pve-exporter](https://github.com/prometheus-pve/prometheus-pve-exporter).

| Группа | Метрики | Смысл / фильтр по `id` |
|--------|---------|------------------------|
| Статус | `pve_up` | 1 = online/running; `id="node/pve1"`, `qemu/100`, `lxc/200`, `storage/pve1/local-lvm` |
| CPU | `pve_cpu_usage_ratio`, `pve_cpu_usage_limit` | ratio 0–1 (gauge, **не** `rate()`); limit — число vCPU |
| Память | `pve_memory_usage_bytes`, `pve_memory_size_bytes` | size = доступно гостю/узлу |
| Диск/ storage | `pve_disk_usage_bytes`, `pve_disk_size_bytes` | для storage — занято/размер; для guest — root image |
| Сеть гостя | `pve_network_receive_bytes_total`, `pve_network_transmit_bytes_total` | counters с момента старта гостя |
| IO гостя | `pve_disk_read_bytes_total`, `pve_disk_written_bytes_total` | не для всех storage-типов |
| Uptime | `pve_uptime_seconds` | node / qemu / lxc |
| Info | `pve_guest_info`, `pve_storage_info`, `pve_node_info`, `pve_version_info` | name, node, type, tags, plugintype, version |
| HA | `pve_ha_state{id,state=…}` | enum: guest — `started`/`stopped`/`error`/`fence`/…; node — `online`/`maintenance`/`fence`/`gone` |
| Locks | `pve_lock_state{id,state=…}` | `backup`, `migrate`, `snapshot`, … |
| Backup | `pve_not_backed_up_total`, `pve_not_backed_up_info` | гости **вне** any backup job |
| Репликация | `pve_replication_failed_syncs`, `…_last_sync_timestamp_seconds`, `pve_replication_info` | fail_count, синк, узел-пара |
| QDevice | `pve_qdevice_up`, `pve_qdevice_info` | corosync QDevice connected |
| Подписка | `pve_subscription_status`, `pve_subscription_next_due_timestamp_seconds` | active/expired/…, срок |
| Onboot | `pve_onboot_status` | автостарт гостя |
| API exporter’а | `pve_api_calls_duration_seconds`, scrape target-metrics | включается `--collector.pve-api-metrics` / `target-metrics` |

Коллекторы делятся на **cluster** (нужен `?cluster=1`) и **node** (`?node=1`):

| Коллектор | Параметр scrape | Что даёт |
|-----------|-----------------|----------|
| `status`, `version`, `node`, `cluster`, `resources`, `backup-info`, `qdevice` | `cluster=1` | кластерная картина (одинакова с любого узла) |
| `config`, `replication`, `subscription` | `node=1` | per-node / per-guest |
| `pve-api-metrics`, `target-metrics` | флаги CLI | собственная производительность exporter’а |

**Большие кластеры:** отдельные jobs — cluster-metrics (`cluster=1&node=0`) с одного/нескольких target’ов и node-metrics (`cluster=0&node=1`) со **всех** узлов (иначе неполная картина node/replication/subscription).

**Кворум corosync** в официальном списке метрик pve-exporter не вынесен отдельным `quorate=`; для SRE-алерта надёжнее textfile + `pvecm status` (сценарий ниже) либо API `cluster/status`. `pve_qdevice_up` — для топологий с QDevice.

### Права API: только PVEAuditor

Upstream требует read-only роль **PVEAuditor** на path `/`. Полные права (`Administrator`) для scrape — нарушение least privilege. Формат заголовка:

```text
Authorization: PVEAPIToken=<user>@<realm>!<token-name>=<token-secret>
```

Приватность токена (`privsep=1`) — см. [Security](./proxmox_security.md).

## Практические сценарии

### 1. Пользователь и API-токен на узле PVE

```bash
# Роль PVEAuditor встроена (read-only). Realm — pve или pam.
pveum user add monitoring@pve --comment "Prometheus PVE exporter"
pveum acl modify / --users monitoring@pve --roles PVEAuditor

# Токен: privsep=1 — секрет вида user@realm!token=uuid (см. Security)
pveum user token add monitoring@pve prometheus --privsep 1
# → privsep: 1
# → value: <UUID-секрет>   ← сохранить один раз; повторно не выводится
```

Проверка с хоста мониторинга:

```bash
curl -sk -H "Authorization: PVEAPIToken=monitoring@pve!prometheus=<UUID>" \
  https://pve1.example.com:8006/api2/json/nodes
# → {"data":[{"node":"pve1",...}, ...]}
```

### 2. Конфигурация exporter’а (`pve.yml`)

Современный pve-exporter управляет auth **файлом** `pve.yml` или env (`PVE_USER`, `PVE_TOKEN_NAME`, `PVE_TOKEN_VALUE`, `PVE_VERIFY_SSL`), **не** CLI-флагами `--pve.user`/`--pve.password`.

```yaml
# /etc/prometheus/pve.yml  (mode 0600, owner = пользователь сервиса)
default:
  user: monitoring@pve
  token_name: prometheus
  token_value: "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
  verify_ssl: true          # false только для самоподписанных; лучше CA/Let's Encrypt

# Необязательно: второй module для «чужого» или non-cluster узла
other-site:
  user: monitoring@pve
  token_name: prometheus
  token_value: "YYYYYYYY-YYYY-YYYY-YYYY-YYYYYYYYYYYY"
  verify_ssl: false
```

```bash
install -d -m 0750 -o root -g prometheus /etc/prometheus
install -m 0640 -o root -g prometheus /dev/null /etc/prometheus/pve.yml
# заполнить pve.yml и выставить права
chmod 640 /etc/prometheus/pve.yml
```

### 3. Установка pve-exporter (отдельный monitoring-сервер)

```bash
# Debian/Ubuntu: системный пакет (версия может отставать от PyPI)
apt install -y prometheus-pve-exporter
# либо актуальная:
python3 -m pip install 'prometheus-pve-exporter>=3.5'

# Или Docker (официальный образ):
# docker run -d --name pve-exporter -p 127.0.0.1:9221:9221 \
#   -v /etc/prometheus/pve.yml:/etc/prometheus/pve.yml:ro \
#   --restart unless-stopped prompve/prometheus-pve-exporter
```

systemd-юнит (типовой для пакета/pip):

```ini
# /etc/systemd/system/prometheus-pve-exporter.service
[Unit]
Description=Prometheus Proxmox VE Exporter
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/pve_exporter \
  --config.file=/etc/prometheus/pve.yml \
  --web.listen-address=:9221
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadOnlyPaths=/etc/prometheus

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now prometheus-pve-exporter

# Метрики кластера (target = узел PVE или localhost, если exporter на PVE):
curl -s 'http://127.0.0.1:9221/pve?target=pve1&cluster=1&node=1' | grep -E '^pve_up\{' | head
# → pve_up{id="node/pve1"} 1
# → pve_up{id="qemu/100"} 1
```

### 4. node_exporter на узлах PVE (кратко)

Полная установка, коллекторы, systemd — [Node Exporter](../Prometheus/Exporters/node_exporter.md). Для PVE важно:

- путь для textfile: `--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`;
- не выключать `node_filesystem_*` (мониторинг storage ZFS/LVM);
- cgroup v2 на PVE 8/9 — коллекторы `cpu`, `memory` работают «из коробки»;
- порт `:9100` закрыть firewall’ом для непустых сетей (см. [Firewall](./proxmox_firewall_advanced.md)).

### 5. Scrape-конфигурация Prometheus

```yaml
# /etc/prometheus/prometheus.yml (фрагмент; полный стек — Prometheus Overview)
global:
  scrape_interval: 30s
  evaluation_interval: 30s

scrape_configs:
  # Кластерная картина: достаточно одного (или round-robin) узла
  - job_name: pve-cluster
    metrics_path: /pve
    scrape_timeout: 25s
    params:
      module: [default]
      cluster: ["1"]
      node: ["0"]
    static_configs:
      - targets: ["mon1:9221"]
        labels: { site: "dc1" }

  # Per-node: каждый узел PVE своим target’ом
  - job_name: pve-node
    metrics_path: /pve
    scrape_timeout: 25s
    params:
      module: [default]
      cluster: ["0"]
      node: ["1"]
    static_configs:
      - targets: ["pve1:9221", "pve2:9221", "pve3:9221"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: mon1:9221   # один exporter на monitoring-сервере

  # Системные метрики узлов
  - job_name: pve-nodes
    static_configs:
      - targets: ["pve1:9100", "pve2:9100", "pve3:9100"]
    relabel_configs:
      - source_labels: [__address__]
        regex: "(.+):\d+"
        target_label: instance
        replacement: "${1}"

  # Probe HTTPS API PVE (не TCP-«зелёный» порт, а ответ API)
  - job_name: pve-api-probe
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ["https://pve1:8006", "https://pve2:8006"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115   # blackbox_exporter

  # Ceph (если hyperconverged): Ceph Manager → Prometheus module
  - job_name: ceph
    static_configs:
      - targets: ["pve1:9283", "pve2:9283", "pve3:9283"]
```

**Самоподписанный сертификат PVE:** лучше доверить CA узла на monitoring-хосте; `verify_ssl: false` в `pve.yml` — временная мера (см. [ACME/Let's Encrypt](./proxmox_acme_ssl.md)).

### 6. Textfile: кворум, HA и «лишний» heartbeat

```bash
# На каждом PVE-узле (от root, cron/systemd timer)
install -d -m 0755 /var/lib/node_exporter/textfile_collector

cat > /usr/local/bin/pve-textfile-metrics.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
DIR=/var/lib/node_exporter/textfile_collector
OUT="${DIR}/pve_cluster.prom"
TMP="${OUT}.$$"

QUORUM=$(pvecm status 2>/dev/null | awk '/Quorate:/ {print tolower($2)}')
NODES=$(pvecm status 2>/dev/null | awk '/^Nodes:/ {print $2}')

# 1 = quorate
case "${QUORUM:-unknown}" in
  yes) Q=1 ;;
  no)  Q=0 ;;
  *)   Q=-1 ;;
esac

cat > "$TMP" << EOF
# HELP pve_cluster_quorate Corosync quorate (1) / not (0); -1 unknown
# TYPE pve_cluster_quorate gauge
pve_cluster_quorate ${Q}
# HELP pve_cluster_nodes Number of cluster nodes reported by pvecm
# TYPE pve_cluster_nodes gauge
pve_cluster_nodes ${NODES:-0}
EOF

# HA: счётчик ресурсов в error (ha-manager; пусто = 0)
ERR=$(ha-manager status 2>/dev/null | awk '$3=="error"' | wc -l)
cat >> "$TMP" << EOF
# HELP pve_ha_manager_resources_error HA resources in error state
# TYPE pve_ha_manager_resources_error gauge
pve_ha_manager_resources_error ${ERR}
EOF

mv -f "$TMP" "$OUT"
SCRIPT

chmod 0755 /usr/local/bin/pve-textfile-metrics.sh
cat > /etc/systemd/system/pve-textfile-metrics.service << 'EOF'
[Unit]
Description=Proxmox textfile metrics for node_exporter

[Service]
Type=oneshot
ExecStart=/usr/local/bin/pve-textfile-metrics.sh
EOF

cat > /etc/systemd/system/pve-textfile-metrics.timer << 'EOF'
[Unit]
Description=Refresh Proxmox textfile metrics

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now pve-textfile-metrics.timer
```

### 7. Алерты (работающие PromQL)

```yaml
# /etc/prometheus/rules/proxmox.yml
groups:
  - name: proxmox-cluster
    rules:
      - alert: ProxmoxNodeDown
        expr: pve_up{id=~"node/.*"} == 0
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "PVE node {{ $labels.id }} is down"
          description: "pve_up == 0 более 2 минут."

      - alert: ProxmoxQuorumLost
        expr: pve_cluster_quorum == 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Corosync quorum lost"
          description: "Кластер не quorate; записи/HA ненадёжны."

      - alert: ProxmoxQDeviceDown
        expr: pve_qdevice_up == 0
        for: 2m
        labels: { severity: warning }
        annotations:
          summary: "QDevice disconnected"

  - name: proxmox-capacity
    rules:
      - alert: ProxmoxStorageFilling
        expr: |
          (
            pve_disk_usage_bytes{id=~"storage/.*"}
            /
            pve_disk_size_bytes{id=~"storage/.*"}
          ) > 0.90
        for: 10m
        labels: { severity: critical }
        annotations:
          summary: "Storage {{ $labels.id }} is {{ $value | humanizePercentage }} full"

      - alert: ProxmoxNodeHighCPU
        expr: pve_cpu_usage_ratio{id=~"node/.*"} > 0.90
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "High CPU on {{ $labels.id }}"

      - alert: ProxmoxNodeHighIOwait
        expr: |
          (
            sum by (instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m]))
            /
            count by (instance) (node_cpu_seconds_total{mode="iowait"})
          ) > 0.30
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "IO wait > 30% on {{ $labels.instance }}"

  - name: proxmox-guests
    rules:
      # Гость с тегом critical упал
      - alert: ProxmoxCriticalGuestDown
        expr: |
          (
            pve_guest_info{tags=~".*critical.*"}
            * on(id) group_left(name)
            pve_up{}
          ) == 0
        for: 3m
        labels: { severity: critical }
        annotations:
          summary: "Critical guest {{ $labels.name }} ({{ $labels.id }}) is down"

      - alert: ProxmoxGuestHAFailed
        expr: pve_ha_state{state="error"} == 1
        for: 2m
        labels: { severity: critical }
        annotations:
          summary: "HA state error for {{ $labels.id }}"

      - alert: ProxmoxHAFencing
        expr: pve_ha_state{state="fence"} == 1
        labels: { severity: critical }
        annotations:
          summary: "Fencing on {{ $labels.id }}"

      - alert: ProxmoxGuestNotBackedUp
        expr: pve_not_backed_up_total > 0
        for: 1h
        labels: { severity: warning }
        annotations:
          summary: "{{ $value }} guest(s) not covered by any backup job"

      - alert: ProxmoxReplicationFailing
        expr: pve_replication_failed_syncs > 0
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Replication job {{ $labels.id }} failed_syncs={{ $value }}"

      - alert: ProxmoxSubscriptionExpired
        expr: pve_subscription_status{status="expired"} == 1
        labels: { severity: warning }
        annotations:
          summary: "PVE subscription expired on {{ $labels.id }}"
```

```bash
promtool check rules /etc/prometheus/rules/proxmox.yml
# → SUCCESS
```

Routing/inhibit/receivers — в SSoT [Alertmanager](../Prometheus/alertmanager.md) (`matchers:`, не устаревший `match:`). Минимальный severity-маршрут:

```yaml
route:
  routes:
    - matchers: [severity="critical"]
      receiver: pager
      repeat_interval: 1h
    - matchers: [severity="warning"]
      receiver: chat
      repeat_interval: 12h
```

### 8. Grafana

**Дашборды:**

| ID | Название | Назначение |
|----|----------|------------|
| 10347 | Proxmox via Prometheus (Pietro Saccardi) | официально рекомендуемый exporter’ом |
| 1860 | Node Exporter Full | системные метрики узлов |

Искать на grafana.com: `Proxmox pve_exporter`. Provisioning datasource — SSoT [Grafana](../Grafana/grafana_overview.md).

**Промежуточные PromQL** (с реальными именами):

```promql
# Доля узлов online
avg(pve_up{id=~"node/.*"})

# CPU узлов, %
pve_cpu_usage_ratio{id=~"node/.*"} * 100

# Заполнение storage, %
100 * pve_disk_usage_bytes{id=~"storage/.*"}
  / ignoring(id) group_right
    pve_disk_size_bytes{id=~"storage/.*"}

# Гости по типу
count by (type) (pve_guest_info)

# Топ-5 гостей по CPU
topk(5, pve_cpu_usage_ratio{id=~"qemu/.*|lxc/.*"} * 100)

# Активный HA fencing / error
max by (id) (pve_ha_state{state=~"fence|error"})

# IO wait с node_exporter
100 * sum by (instance) (rate(node_cpu_seconds_total{mode="iowait"}[5m]))
  / on(instance) group_left
    count by (instance) (node_cpu_seconds_total{mode="iowait"})
```

Не используйте `rate()` на `pve_cpu_usage_ratio` — это gauge 0–1.

## Диагностика и устранение неполадок

### exporter отвечает 401 / метрики пустые

```bash
# Токен и роль
pveum user token list monitoring@pve
pveum acl list / | grep monitoring

# Живой запрос
curl -sk -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: PVEAPIToken=monitoring@pve!prometheus=<UUID>" \
  https://pve1:8006/api2/json/version
# → 200

curl -s 'http://127.0.0.1:9221/pve?target=pve1&cluster=1' | head
journalctl -u prometheus-pve-exporter -e --no-pager | tail -40
```

| Причина | Действие |
|---------|----------|
| Неверный `token_value` | Пересоздать токен; сверить `token_name` |
| Нет `Sys.Audit` / `VM.Audit` | `pveum role modify PVEAuditor -privs …` |
| `verify_ssl: true` + самоподписанный | Импорт CA **или** ACME |
| Метрики без `node/…` | Забыт `node=1`; узел не в `cluster` |
| Секрет в world-readable `pve.yml` | `chmod 640`, владелец `prometheus` |

### Prometheus: targets down

```bash
promtool check config /etc/prometheus/prometheus.yml
# http://prometheus:9090/targets
curl -s 'http://prometheus:9090/api/v1/query?query=up{job=~"pve.*"}'
```

Часто: exporter слушает localhost, а Prometheus с другого хоста; firewall :9221; `metrics_path` не `/metrics`, а `/pve`.

### Высокая нагрузка API / долгий scrape

```bash
# Длительность вызовов API (если включён коллектор)
curl -s 'http://127.0.0.1:9221/metrics' | grep pve_api | head
```

- Отключить `--collector.config` (1 API-call на гость) на больших кластерах.
- Разделить jobs cluster/node, увеличить `scrape_interval` для pve до 60s.
- Ограничить число параллельных scrapes к одному PVE node.

### Prometheus ест память

```yaml
storage:
  tsdb:
    retention.time: 30d
    retention.size: 20GB
```

Детали retention / downsampling — [Prometheus Overview](../Prometheus/overview.md).

### textfile-метрики не появляются

```bash
# node_exporter должен иметь флаг каталога
systemctl show node_exporter -p ExecStart
ls -l /var/lib/node_exporter/textfile_collector/*.prom
curl -s localhost:9100/metrics | grep pve_cluster_quorum
```

## Лучшие практики

1. **Один PVEAuditor + token**, `privsep=1`; без «пробного» Administrator.
2. **`pve.yml` 0640**; секреты не в git; предпочесть Let’s Encrypt вместо `verify_ssl: false` ([ACME](./proxmox_acme_ssl.md)).
3. **Разделяйте scrape**: `cluster=1&node=0` — один узел/round-robin; `node=1` — все узлы.
4. **`:9221`, `:9100` — только VLAN мониторинга** ([Firewall](./proxmox_firewall_advanced.md)); exporter’ы не в интернет.
5. **IO delay** считать по `node_cpu_seconds_total{mode="iowait"}`, не по несуществующим `pve_disk_io_wait`.
6. **Теги гостей** (`critical`, `dba`) + join с `pve_guest_info` — фильтрация алертов без дублирования списков.
7. **Backup gap** — `pve_not_backed_up_total` в weekly-review ([Backup](./proxmox_backup_server.md), [DR](./proxmox_disaster_recovery.md)).
8. **IPMI/BMC** — обязательно ([IPMI Exporter](../Prometheus/Exporters/ipmi_exporter.md)); аппаратура — частая причина простоев.
9. **Ceph** — Ceph Manager Prometheus module (:9283), не кастомные скрипты ([Ceph](../Kubernetes/Storage/Ceph/ceph_overview.md)).
10. **Git для всего**: `prometheus.yml`, `rules/`, `pve.yml` (без секретов), дашборды; `promtool test rules` в CI.
11. **Один exporter на узле PVE** — легче, чем дубли; HA monitoring-стека — отдельная задача (2 Prometheus / federation), не два pve-exporter без смысла.

## Граничные случаи

- **Один pve-exporter = одна точка отказа** для cluster-metrics: при падении mon-host «слепнет» вся кластерная картина; node_exporter на узлах при этом продолжает жить — не путать с health самого PVE.
- **`pve_network_*_bytes_total` / disk counters** сбрасываются при рестарте гостя — на дашбордах используйте `increase()`/`rate()` с осторожностью и осознанием сброса.
- **Устаревшие gauge-варианты** `pve_network_receive_bytes` (без `_total`) помечены deprecated — в новых версиях могут исчезнуть; переходите на `*_total`.
- **ZFS** : node_exporter видит dataset’ы как filesystem; для arcstats нужны дополнительные коллекторы/экспортеры (не PVE-specific).
- **VM в pauser/suspended** — `pve_up == 0` при ожидаемом выключении: фильтруйте тегами или `pve_ha_state`, не алертуйте на всё подряд.
- **Ceph на :9283** — если mgr module выключен, target падает; либо включить module, либо убрать job.
- **Windows-guest agent** — qemu-guest-agent улучшает freeze/thaw при backup; метрики гостя при этом остаются API-level (pve-exporter), не агент-level.

## Дополнительная информация

### Связанные темы

- [prometheus-pve-exporter (upstream)](https://github.com/prometheus-pve/prometheus-pve-exporter)
- [Prometheus — Обзор](../Prometheus/overview.md)
- [Node Exporter](../Prometheus/Exporters/node_exporter.md)
- [IPMI/BMC Exporter](../Prometheus/Exporters/ipmi_exporter.md)
- [Alertmanager](../Prometheus/alertmanager.md)
- [Blackbox Exporter](../Prometheus/Exporters/blackbox/)
- [Grafana — Обзор](../Grafana/grafana_overview.md)
- [Обзор Proxmox VE](./proxmox_overview.md)
- [Кластер и HA](./proxmox_cluster.md)
- [Logging и задачи PVE](./proxmox_logging.md)
- [Backup Server](./proxmox_backup_server.md) · [Disaster Recovery](./proxmox_disaster_recovery.md)
- [Firewall](./proxmox_firewall_advanced.md) · [Networking](./proxmox_networking.md)
- [Security (токены)](./proxmox_security.md) · [ACME/Let's Encrypt](./proxmox_acme_ssl.md)
- [Storage](./proxmox_storage.md) · [Performance](./proxmox_performance.md)
- [Ceph](../Kubernetes/Storage/Ceph/ceph_overview.md)
