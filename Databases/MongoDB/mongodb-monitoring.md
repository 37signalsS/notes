# MongoDB: Мониторинг и наблюдаемость

**Актуально для:** MongoDB 8.0.29, mongodb_exporter (percona/mongodb_exporter v0.53.0+), Prometheus 3.13.x/3.14.x, Grafana 11.x, PMM 2.x, Ops Manager 8.0

---

## Определения

**Мониторинг MongoDB** — сбор метрик состояния кластера (Replica Set, шардированный кластер), их экспорт в Prometheus, визуализация в Grafana и алертинг по SLO. Цель — обнаружить деградацию до исчерпания ресурсов (USE-методология) и до нарушения SLO.

*   **mongodb_exporter:** Prometheus-экспортер (Percona), собирающий метрики из `db.serverStatus()`, `rs.status()`, `db.health()`, `$collStats`, `$indexStats`, `getDiagnosticData`, `replSetGetStatus`, `replSetGetConfig`. Поддерживает MongoDB 6.0+. Флаг `--compatible-mode` обеспечивает совместимость имен метрик со старыми версиями (0.1x).
*   **RED-метод:** Rate (ops/sec), Errors (failed ops), Duration (latency) — для каждого критичного запроса.
*   **USE-метод:** Utilization, Saturation, Errors — для каждого ресурса (CPU, RAM, диск, сеть).
*   **SLI (Service Level Indicator):** измеряемая метрика качества (например, p99 latency чтения, доля успешных записей).
*   **SLO (Service Level Objective):** целевое значение SLI (например, p99 < 50мс, доступность 99.9%).
*   **Error Budget:** допустимый объём нарушений SLO за период. Исчерпание бюджета — сигнал заморозить изменения.
*   **Golden Signals:** latency, traffic, errors, saturation — четыре сигнала, на которые смотрят в первую очередь.
*   **Ops Manager:** Коммерческая платформа MongoDB (Enterprise Advanced) для мониторинга, бэкапов и автоматизации self-managed кластеров. Включает Agents (monitoring/backup/automation), веб-UI, алертинг.
*   **PMM (Percona Monitoring and Management):** Open-source платформа мониторинга (Grafana + Prometheus + ClickHouse + экспортеры) от Percona. Поддерживает MongoDB через `pmm-admin` и `mongodb_exporter`.
*   **SNMP (Simple Network Management Protocol):** Протокол мониторинга сетевого оборудования. MongoDB Enterprise поддерживает SNMP subagent (только `mongod`, не `mongos`).
*   **PSI (Pressure Stall Information):** Linux kernel mechanism (4.20+) для измерения насыщенности ресурсов (CPU, Memory, I/O) через `/proc/pressure/`. Детально: **[Pressure Stall Information (PSI)](../../Linux/Core/kernel/psi.md)**.
*   **Burn Rate:** скорость выгорания Error Budget — мультиоконное правило алертинга для SLO (1h окно для fast burn, 6h/24h для slow burn).

Общая теория мониторинга и алертинга: **[Мониторинг и алертинг](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)**, **[Методологии USE/RED/Golden Signals](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**.

---

## Базовые концепты

### Архитектура мониторинга

```
mongod (serverStatus, rs.status)
   │
   ├─► mongodb_exporter (:9216 /metrics)
   │        │
   │        ▼
   │     Prometheus (scrape 15–30s)
   │        │
   │        ▼
   │     Grafana (dashboards) + Alertmanager (алерты)
   │
   ├─► node_exporter (:9100 /metrics) — host-level USE метрики
   │        │
   │        ▼
   │     Prometheus → USE дашборды (CPU, RAM, Disk, Network)
   │
   └─► diagnostic log / system.profile (slow queries)
```

### Четыре группы метрик

| Группа | Что измеряет | Ключевые метрики | Методология |
| :--- | :--- | :--- | :--- |
| **Золотые сигналы** | latency, traffic, errors | `mongodb_op_latency`, `mongodb_op_counters`, `mongodb_errors` | RED / Golden Signals |
| **Репликация** | здоровье Replica Set, лаг | `mongodb_rs_members_state`, `mongodb_rs_optime_lag`, `mongodb_oplog_window` | Symptom-based |
| **Ресурсы (USE)** | CPU, RAM, диск, сеть | `mongodb_memory_resident`, `wiredTiger_cache_usage`, `node_*` | USE |
| **WiredTiger** | кэш, чекпоинты, тикеты | `wiredTiger_cache_bytes`, `wiredTiger_evictions`, `wiredTiger_concurrentTransactions` | USE / Cause-based |

### Ключевые метрики mongodb_exporter

| Метрика | Источник | Что означает | Тип |
| :--- | :--- | :--- | :--- |
| `mongodb_up` | ping | 1 = инстанс доступен | Gauge |
| `mongodb_rs_members_state{state="1"}` | rs.status() | 1 = есть Primary | Gauge |
| `mongodb_rs_optime_lag_seconds` | rs.printSecondaryReplicationInfo() | Лаг Secondary (сек) | Gauge |
| `mongodb_oplog_window_seconds` | rs.printReplicationInfo() | Oplog Window (сек) | Gauge |
| `mongodb_memory_resident_bytes` | serverStatus.mem | RSS процесса | Gauge |
| `mongodb_wiredtiger_cache_bytes_currently_in_cache` | serverStatus.wiredTiger.cache | Занято кэша | Gauge |
| `mongodb_wiredtiger_cache_bytes_max` | serverStatus.wiredTiger.cache | Макс. кэш (cacheSizeGB) | Gauge |
| `mongodb_wiredtiger_cache_evictions` | serverStatus.wiredTiger.cache | Вытеснения из кэша | Counter |
| `mongodb_connections_current` | serverStatus.connections | Текущие соединения | Gauge |
| `mongodb_connections_available` | serverStatus.connections | Свободные соединения | Gauge |
| `mongodb_network_bytes_in/out` | serverStatus.network | Трафик IN/OUT | Counter |
| `mongodb_op_counters_insert/query/update/delete` | serverStatus.opcounters | Ops/sec | Counter |
| `mongodb_global_lock_active_clients` | serverStatus.locks | Активные клиенты | Gauge |
| `mongodb_wiredtiger_concurrentTransactions_read/write` | serverStatus.wiredTiger | Доступные тикеты чтения/записи | Gauge |
| `mongodb_wiredtiger_checkpoint_*` | serverStatus.wiredTiger | Чекпойнты (время, размер, wait) | Counter/Gauge |

> **Примечание:** точные имена метрик зависят от версии экспортера (percona/mongodb_exporter v0.53.0+ использует `mongodb_*` префикс). Проверьте актуальные имена через `curl http://localhost:9216/metrics`. Флаг `--compatible-mode` включает старые имена метрик (0.1x).

### SLO для MongoDB

| SLI | Типичный SLO | Метрика | Burn Rate Alert |
| :--- | :--- | :--- | :--- |
| Доступность записи | 99.9% | доля успешных `insert/update` | `rate(mongodb_errors[5m]) / rate(mongodb_op_counters[5m]) > 0.001` |
| p99 latency чтения | < 50мс | `mongodb_op_latency` histogram | `histogram_quantile(0.99, rate(mongodb_op_latency_bucket[5m])) > 0.05` |
| Replication lag | < 10с | `mongodb_rs_optime_lag_seconds` | `mongodb_rs_optime_lag_seconds > 10` for 2m |
| Oplog Window | > 24ч | `mongodb_oplog_window_seconds` | `mongodb_oplog_window_seconds < 3600` for 5m |
| Cache hit ratio | > 99% | `1 - wiredTiger_cache_bytes_read_into_cache / total` | `rate(wiredTiger_cache_evictions[5m]) > 0` |

### USE-метрики на хосте (node_exporter)

Для полноценного USE-мониторинга MongoDB **обязателен** `node_exporter` на каждом хосте:

| Ресурс | Utilization | Saturation (PSI) | Errors |
| :--- | :--- | :--- | :--- |
| **CPU** | `1 - rate(node_cpu_seconds_total{mode="idle"}[5m])` | `rate(node_pressure_cpu_waiting_seconds_total[5m])` | `rate(node_cpu_seconds_total{mode="iowait"}[5m])` |
| **Memory** | `1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes` | `rate(node_pressure_memory_waiting_seconds_total[5m])` | `node_memory_SwapCached_bytes` (swap usage) |
| **Disk** | `rate(node_disk_io_time_seconds_total[5m])` | `rate(node_disk_io_time_weighted_seconds_total[5m]) / rate(node_disk_io_time_seconds_total[5m])` (avg queue depth) | `node_filesystem_readonly` (gauge) |
| **Network** | `rate(node_network_transmit_bytes_total[5m]) / speed` | `rate(node_network_transmit_drop_total[5m])` | `rate(node_network_receive_errs_total[5m])` |

> **Важно:** PSI (Pressure Stall Information) доступен в Linux 4.20+ (`CONFIG_PSI=y`). Это **единственный** надёжный способ измерения Saturation. См. **[PSI (Pressure Stall Information)](../../Linux/Core/kernel/psi.md)**.

---

## Подготовка окружения (Prerequisites)

| Требование | Минимальное значение | Рекомендуемое | Примечание |
| :--- | :--- | :--- | :--- |
| **MongoDB Server** | 4.4+ (Replica Set) | 8.0.29 | `serverStatus`, `rs.status` требуют RS или sharded cluster. Standalone не поддерживается для репликации метрик. |
| **mongodb_exporter** | 0.32+ | v0.53.0+ (latest) | Percona версия. Совместимость с MongoDB 6.0–8.0. Флаг `--compatible-mode` для миграции с 0.1x. |
| **Prometheus** | 2.40+ | 3.13.x/3.14.x (LTS) | Scrape interval 15–30s. Remote Write 2.0 для HA. |
| **Grafana** | 9.0+ | 11.x (LTS) | Дашборды JSON, Alerting UI. |
| **node_exporter** | 1.5+ | 1.12.x+ | Обязателен для USE метрик хоста (CPU, RAM, Disk, Network, PSI). Коллектор `--collector.pressure` для PSI. |
| **Права MongoDB** | `clusterMonitor` + `read` на `local` | Пользователь `exporter` с `clusterMonitor`, `read` на `local` | Для `rs.status()` нужен `read` на `local`. Для sharded cluster — `clusterMonitor` на config servers. |
| **RAM (exporter)** | 256 MB | 512 MB | JVM не используется; Go binary. При сборе с множества узлов — больше. |
| **Диск (Prometheus)** | 50 GB | 200+ GB SSD NVMe | Retention 15–30 дней сырых метрик. WAL + TSDB. |
| **Сеть** | 1 Gbps | 10 Gbps | Низкая латентность между mongod, exporter, Prometheus критична. |
| **CPU** | 1 vCPU | 2+ vCPU | Для exporter + Prometheus scrape. |
| **ОС** | Linux (Ubuntu 20.04+, RHEL 8+) | Linux, актуальный LTS | PSI требует kernel 4.20+. Production не на Windows. |
| **Kernel** | 4.20+ | 6.1+ | PSI (CPU/Memory/IO pressure), IRQ pressure (6.1+). |
| **Файловая система** | ext4 / xfs | xfs с `noatime` | Для Prometheus data dir и MongoDB data dir. |

**Создание пользователя для мониторинга:**
```javascript
use admin
db.createUser({
  user: "exporter",
  pwd: passwordPrompt(),
  roles: [
    { role: "clusterMonitor", db: "admin" },
    { role: "read", db: "local" }
  ]
})
```

**Установка mongodb_exporter (Linux):**
```bash
# Через Docker
docker run -d --name mongodb-exporter \
  -p 9216:9216 \
  -e MONGODB_URI="mongodb://exporter:password@mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0&authSource=admin" \
  percona/mongodb_exporter:v0.53.0

# Или бинарник (systemd)
wget https://github.com/percona/mongodb_exporter/releases/download/v0.53.0/mongodb_exporter-0.53.0.linux-amd64.tar.gz
tar -xzf mongodb_exporter-*.tar.gz
sudo cp mongodb_exporter /usr/local/bin/
sudo useradd -r -s /bin/false mongodb_exporter

# systemd unit
cat <<EOF | sudo tee /etc/systemd/system/mongodb_exporter.service
[Unit]
Description=MongoDB Exporter
After=network.target

[Service]
User=mongodb_exporter
ExecStart=/usr/local/bin/mongodb_exporter \
  --mongodb.uri="mongodb://exporter:password@mongo-1:27017/?replicaSet=rs0&authSource=admin" \
  --web.listen-address=":9216" \
  --collect.all
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now mongodb_exporter
```

**Установка node_exporter (для USE метрик):**
```bash
# Docker
docker run -d --name node-exporter \
  -p 9100:9100 \
  --pid="host" \
  -v "/:/host:ro,rslave" \
  quay.io/prometheus/node-exporter:v1.12.0 \
  --path.rootfs=/host \
  --collector.pressure

# systemd (binary)
wget https://github.com/prometheus/node_exporter/releases/download/v1.12.0/node_exporter-1.12.0.linux-amd64.tar.gz
tar -xzf node_exporter-*.tar.gz
sudo cp node_exporter /usr/local/bin/
sudo useradd -r -s /bin/false node_exporter
# systemd unit аналогично mongodb_exporter с портом 9100 и флагом --collector.pressure
```

**Проверка версий и совместимости:**
```bash
# mongodb_exporter metrics
curl -s http://localhost:9216/metrics | head -20
# # → mongodb_up{...} 1

# node_exporter metrics (PSI check)
curl -s http://localhost:9100/metrics | grep node_pressure
# # → node_pressure_cpu_waiting_seconds_total{...}

# Prometheus version
curl -s http://localhost:9090/api/v1/status/buildinfo | jq .data.version
# # → "3.14.0"

# MongoDB Replica Set статус
mongosh --eval "rs.status()" --quiet
# # → { "ok": 1, "members": [ { "stateStr": "PRIMARY" }, ... ] }

# MongoDB версия
mongosh --eval "db.version()" --quiet
# # → "8.0.29"
```

---

## Практические сценарии

### 1. Запуск mongodb_exporter

```bash
# Через Docker
docker run -d --name mongodb-exporter \
  -p 9216:9216 \
  -e MONGODB_URI="mongodb://exporter:password@mongo-1:27017,mongo-2:27017,mongo-3:27017/?replicaSet=rs0&authSource=admin" \
  percona/mongodb_exporter:v0.53.0

# Или бинарник
mongodb_exporter \
  --mongodb.uri="mongodb://exporter:password@mongo-1:27017/?replicaSet=rs0&authSource=admin" \
  --web.listen-address=":9216"
```

**Валидация:**
```bash
curl -s http://localhost:9216/metrics | grep mongodb_up
# → mongodb_up{...} 1
```

### 2. Конфигурация Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: "mongodb"
    scrape_interval: 15s
    static_configs:
      - targets: ["mongodb-exporter:9216"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
```

### 3. Sidecar-экспортер в Kubernetes (Operator)

```yaml
# Дополнительный контейнер в поде MongoDB
spec:
  statefulSet:
    spec:
      template:
        spec:
          containers:
          - name: mongodb-exporter
            image: percona/mongodb_exporter:v0.53.0
            ports:
            - containerPort: 9216
            env:
            - name: MONGODB_URI
              value: "mongodb://exporter:\$(PASS)@localhost:27017/admin?authSource=admin"
            envFrom:
            - secretRef:
                name: mongo-exporter-password
```

### 4. Prometheus алерты (SRE-набор)

```yaml
groups:
- name: mongodb_slo
  rules:
  # Золотые сигналы
  - alert: MongoDBPrimaryDown
    expr: sum by (replica_set) (mongodb_rs_members_state{state="1"}) == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Нет PRIMARY в {{ $labels.replica_set }}"
      description: "Потерян кворум или зависли выборы"

  - alert: MongoDBReplicationLag
    expr: mongodb_rs_optime_lag_seconds > 10
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Replication lag {{ $value }}с на {{ $labels.instance }}"

  - alert: MongoDBOplogWindowTooSmall
    expr: mongodb_oplog_window_seconds < 3600
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Oplog Window < 1ч на {{ $labels.instance }}"

  # USE-методология
  - alert: MongoDBWiredTigerCacheEvictions
    expr: rate(mongodb_wiredtiger_cache_evictions[5m]) > 0
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "WiredTiger cache evictions на {{ $labels.instance }} — working set > cacheSizeGB"

  - alert: MongoDBCachePressure
    expr: mongodb_wiredtiger_cache_bytes_currently_in_cache / mongodb_wiredtiger_cache_bytes_max > 0.9
    for: 5m
    labels:
      severity: warning

  - alert: MongoDBConnectionSaturation
    expr: mongodb_connections_current / (mongodb_connections_current + mongodb_connections_available) > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Connection pool saturation на {{ $labels.instance }}"

  - alert: MongoDBDiskFull
    expr: node_filesystem_avail_bytes{mountpoint="/var/lib/mongodb"} / node_filesystem_size_bytes{mountpoint="/var/lib/mongodb"} < 0.2
    for: 5m
    labels:
      severity: critical
```

### 5. RED-метрики для критичных коллекций

```javascript
// Включить профилирование для измерения latency (RED — Duration)
db.setProfilingLevel(1, { slowms: 50 })

// Топ-10 медленных операций (RED — Rate/Errors/Duration)
db.system.profile.find().sort({ millis: -1 }).limit(10).pretty()
```

> Для RED на уровне приложения используйте метрики драйвера (pymongo/Node.js driver metrics) или APM (OpenTelemetry). См. **[Database Observability](../../Concepts/Observability_and_Monitoring/database_observability.md)**.

### 6. Ops Manager (Enterprise Advanced)

Компоненты: **Monitoring Agent** (метрики), **Backup Agent** (бэкапы), **Automation Agent** (управление конфигурацией).

```bash
# Установка Monitoring Agent (Linux, пример)
# Скачивание agent из Ops Manager UI (Deployment → Agents → Downloads)
sudo rpm -ivh mongodb-mms-monitoring-agent-*.x86_64.rpm

# Конфигурация /etc/mongodb-mms/monitoring-agent.config
mmsGroupId=<ProjectID>
mmsApiKey=<AgentAPIKey>
mmsBaseUrl=https://ops-manager.example.com
```

**Возможности:**
*   Дашборды: операции, репликация, WiredTiger, сеть, диски.
*   Алерты: Primary down, replication lag, oplog window, disk space, cache evictions.
*   Backup: point-in-time recovery, snapshot-стратегии.
*   Automation: развёртывание/обновление кластеров из UI.

**Валидация:**
```bash
# Статус агента
sudo systemctl status mongodb-mms-monitoring-agent
# # → Active: active (running)

# В UI: Deployment → Processes — все mongod/mongos должны быть "Running"
```

### 7. PMM (Percona Monitoring and Management)

Альтернатива Prometheus+Grafana-стеку в одном пакете.

```bash
# Установка PMM Server (Docker)
docker run -d -p 80:80 -p 443:443 \
  -v /srv/pmm-data:/srv \
  --name pmm-server --restart always \
  percona/pmm-server:2

# Установка клиента на хосте MongoDB
curl -fsSL https://www.percona.com/get/pmm | bash

# Подключение к серверу
pmm-admin config --server-url=https://admin:admin@pmm.example.com

# Добавление MongoDB (через mongodb_exporter)
pmm-admin add mongodb \
  --username=exporter \
  --password='<password>' \
  --cluster="rs0" \
  --replica-set \
  --host=mongo1:27017
# # → OK. Successfully added MongoDB.
```

**Валидация:**
```bash
pmm-admin list
# # → pmm-admin 2.x | MongoDB ... | mongo1:27017

# В UI: http://pmm.example.com → MongoDB → Overview / Replication / Query Analytics (QAN)
```

**PMM vs самодельный стек:**

| Критерий | PMM | Prometheus + Grafana |
| :--- | :--- | :--- |
| Установка | Один пакет | Ручная сборка |
| QAN (Query Analytics) | Встроен (slow query analysis) | Через APM/OTel |
| Гибкость | Ограничена дашбордами PMM | Полная (PromQL, аннотации) |
| Хранение | ClickHouse (встроен) | Prometheus TSDB / Thanos |

### 8. SNMP-мониторинг (Enterprise)

MongoDB Enterprise может экспортировать метрики через SNMP subagent (AgentX) для интеграции с сетевым мониторингом (Zabbix, PRTG, Nagios).

**Ограничения:**
*   Только **Enterprise Edition** (Community выдаст `unknown option snmp-subagent`).
*   Только **`mongod`** (`mongos` не поддерживает SNMP).
*   **SNMP traps не поддерживаются** — только polling.
*   Не поддерживается на macOS.

**Настройка (Linux, net-snmp):**
```bash
# 1. Копирование MIB и конфигов (из состава MongoDB Enterprise)
cp MONGOD-MIB.txt /etc/snmp/mibs/
cp mongod.conf.subagent /etc/snmp/mongod.conf

# 2. Настройка AgentX-сокета в snmpd.conf
# master agentx
# agentXSocket /var/agentx/master

# 3. Запуск mongod как SNMP subagent
mongod --config /etc/mongod.conf --snmp-subagent

# 4. Проверка через snmpwalk
snmpwalk -v2c -c mongodb -m /etc/snmp/mibs/MONGOD-MIB.txt \
  127.0.0.1:161 1.3.6.1.4.1.34601
# # → MONGODB-MIB::mongodVersion.0 = STRING: "8.0.29"
```

**Отключение SNMP (если не нужен):**
```yaml
# mongod.conf
snmp:
  disabled: true
```

### 9. Grafana-дашборд: ключевые панели

| Панель | PromQL |
| :--- | :--- |
| Ops/sec | `rate(mongodb_op_counters_insert[5m])` |
| p99 latency | `histogram_quantile(0.99, rate(mongodb_op_latency_bucket[5m]))` |
| Replication lag | `mongodb_rs_optime_lag_seconds` |
| Oplog Window | `mongodb_oplog_window_seconds` |
| Cache usage | `mongodb_wiredtiger_cache_bytes_currently_in_cache / 1024 / 1024` |
| Connections | `mongodb_connections_current` |
| Resident memory | `mongodb_memory_resident_bytes / 1024 / 1024` |
| WiredTiger tickets (read) | `mongodb_wiredtiger_concurrentTransactions_read` |
| WiredTiger tickets (write) | `mongodb_wiredtiger_concurrentTransactions_write` |
| Cache evictions rate | `rate(mongodb_wiredtiger_cache_evictions[5m])` |
| Oplog window (hours) | `mongodb_oplog_window_seconds / 3600` |

---

## Граничные случаи и ограничения

### Шардированные кластеры

*   **Config servers:** Требуют отдельного экземпляра `mongodb_exporter` (или sidecar на каждом config server). Метрики `mongodb_sharding_*` доступны только на config servers.
*   **Mongos:** Экспортер подключается к `mongos` для получения кластерных метрик, но `rs.status()` недоступен — используйте `sh.status()`.
*   **Кардинальность:** При большом количестве шардов и чанков метрики `mongodb_sharding_chunks_*` могут создавать высокую кардинальность. Ограничьте через `relabel_configs` в Prometheus.

### Standalone (не Replica Set)

*   Метрики репликации (`mongodb_rs_*`, `mongodb_oplog_*`) недоступны.
*   Для мониторинга standalone используйте только `serverStatus` метрики + `node_exporter`.
*   Рекомендуется всегда использовать Replica Set даже для dev/staging.

### Высокая кардинальность метрик

*   Коллекторы `collstats` и `indexstats` (включаются флагом `--collect.all`) создают метрики на каждую коллекцию/индекс.
*   При >10k коллекций это перегружает Prometheus. Решение: не включать `--collect.all` в продакшене, собирать только глобальные метрики.
*   Альтернатива: использовать `mongodb_exporter` с фильтрами по БД/коллекциям или собирать per-collection метрики только по требованию.

### Версии и совместимость

*   MongoDB 8.0.x требует mongodb_exporter v0.40+ (v0.53.0+ рекомендуется).
*   MongoDB 4.4–6.0 работают с mongodb_exporter v0.32+.
*   MongoDB <4.4 — не поддерживаются актуальными версиями экспортера.

### PSI и node_exporter

*   PSI метрики доступны только при ядре 4.20+ с `CONFIG_PSI=y` и node_exporter 1.8.0+ с флагом `--collector.pressure`.
*   Без PSI Saturation оценивается косвенно (run queue, swap, взвешенное I/O время) — менее точно.

---

## Устранение неполадок

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`mongodb_up = 0`** | Экспортер не может подключиться | `curl :9216/metrics`, логи экспортера | Проверить URI, сеть, RBAC (`clusterMonitor`) |
| **Нет метрик репликации** | Нет прав на `local` БД | `db.runCommand({connectionStatus:1})` | Добавить `read` на `local` |
| **Метрики устарели** | Scrape interval слишком большой | `up{job="mongodb"}` | Уменьшить interval до 15с |
| **Кардинальность метрик** | Много label'ов (per-collection) | `count({__name__=~"mongodb_.*"})` | Ограничить label'ы в экспортере, отключить `--collect.all` |
| **Алерты шумят** | Слишком чувствительные пороги | Alertmanager stats | Настроить `for:` и пороги под SLO, использовать Burn Rate |
| **Ops Manager: агент не подключается** | Неверные `mmsGroupId`/`mmsApiKey` или firewall на `mmsBaseUrl` | `tail -f /var/log/mongodb-mms/monitoring-agent.log` | Проверить API key (Deployment → Agents), доступность Ops Manager URL |
| **PMM: `pmm-admin add mongodb` ошибка** | Нет пользователя `clusterMonitor` или неверный host/port | `pmm-admin list`; логи `pmm-admin` | Создать пользователя с `clusterMonitor`; проверить `authSource` |
| **SNMP: `unknown option snmp-subagent`** | Community Edition (SNMP только в Enterprise) | `mongod --version` → `modules: enterprise` | Установить MongoDB Enterprise или использовать mongodb_exporter |
| **SNMP: subagent не подключается к master** | AgentX-сокет не совпадает между `snmpd.conf` и `mongod.conf.subagent` | `grep agentX /etc/snmp/snmpd.conf /etc/snmp/mongod.conf` | Синхронизировать `agentXSocket` (например, `/var/agentx/master`) |
| **WiredTiger cache evictions растут** | Working set > cacheSizeGB | `db.serverStatus().wiredTiger.cache` | Увеличить `cacheSizeGB`, добавить RAM, оптимизировать индексы |
| **Replication lag скакает** | Долгие операции на primary, медленный диск на secondary | `rs.printSecondaryReplicationInfo()`, `iostat -xz 1` | Оптимизировать write-heavy запросы, использовать SSD на secondary |
| **Oplog Window < 1ч** | Oplog слишком мал для нагрузки | `rs.printReplicationInfo()` | Увеличить `oplogSizeMB` в mongod.conf (перезапуск не нужен в 8.0+) |
| **Connection pool saturation** | Приложение не закрывает соединения | `mongodb_connections_current / (current + available) > 0.8` | Настроить connection pool в приложении (maxPoolSize, leakDetectionThreshold) |
| **PSI метрик нет в node_exporter** | PSI отключен в ядре или старый node_exporter | `cat /proc/pressure/cpu`, версия node_exporter | Включить `psi=1` в GRUB, обновить node_exporter до 1.8.0+, флаг `--collector.pressure` |
| **Burn Rate алерты не срабатывают** | Не настроены recording rules для error rate | `promtool check rules` | Добавить recording rules для error rate, проверить SLO target |

---

## Лучшие практики (SRE)

1.  **SLO-first:** определите SLI/SLO до настройки алертов. Алерт — это нарушение SLO, а не «метрика вышла за порог».
2.  **RED + USE:** RED — для запросов, USE — для ресурсов. Не смешивайте.
3.  **Scrape 15–30с:** достаточно для обнаружения failover (10с heartbeat + electionTimeout 10с).
4.  **Error Budget:** отслеживайте бюджет ошибок; при исчерпании — заморозить релизы.
5.  **Алерты на лаг и Oplog Window:** это ранние индикаторы проблем с репликацией и бэкапами.
6.  **Cache evictions:** рост при отсутствии пиков = недостаток RAM (working set > cacheSizeGB).
7.  **Не алерьте на каждую метрику:** алерт — только на actionability. Остальное — на дашборд.
8.  **Тестируйте алерты:** включите Alertmanager в CI или периодически проверяйте вручную (`promtool test rules`).
9.  **Burn Rate для SLO:** используйте мультиоконные алерты (1h/5m, 6h/30m, 1d/2h) вместо статических порогов.
10. **Recording rules для тяжёлых запросов:** `histogram_quantile(rate(...[5m]))` предвычисляйте через recording rules — это снимает нагрузку с Prometheus.
11. **Runbook для каждого критического алерта:** без runbook алерт не сокращает MTTR. Шаблон: симптомы, диагностика, алгоритм действий, контакты.
12. **Label hygiene:** избегайте high-cardinality лейблов (`pod`, `instance` в group_by). Группируйте по `alertname` + `service`/`cluster`.
13. **PSI для Saturation:** используйте `node_pressure_*` метрики вместо косвенных индикаторов (load average, iowait).
14. **Валидация после изменений:** после изменения конфигурации MongoDB/exporter проверяйте `mongodb_up`, `mongodb_rs_members_state`, latency p99.

---

## Дополнительная информация

*   **[Администрирование](./mongodb-administration.md)** — `mongostat`, `mongotop`, `serverStatus`.
*   **[Высокая доступность](./high_availability.md)** — failover, Oplog Window.
*   **[Capacity Planning](./mongodb-capacity-planning.md)** — sizing ресурсов.
*   **[Мониторинг и алертинг (общая теория)](../../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)** — RED/USE/Golden Signals, Burn Rate, recording rules.
*   **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** — USE, RED, Golden Signals, матрица компонентов.
*   **[Database Observability](../../Concepts/Observability_and_Monitoring/database_observability.md)** — slow query, APM, connection pooling.
*   **[Pressure Stall Information (PSI)](../../Linux/Core/kernel/psi.md)** — детальное руководство по PSI, пороги, алерты.
*   **[Мониторинг MariaDB](../../Databases/MariaDB/monitoring.md)** — аналогичная тема для MariaDB (включая PMM).
*   **[Мониторинг MySQL](../../Databases/MySQL/monitoring.md)** — PMM для MySQL.
*   **[SNMP Exporter в Prometheus](../../Prometheus/kubernetes/operator/crd/scrapeconfig.md)** — SNMP Exporter интеграция.
*   [Percona MongoDB Exporter](https://github.com/percona/mongodb_exporter) — GitHub репозиторий, releases.
*   [MongoDB Prometheus Metrics](https://www.mongodb.com/docs/manual/reference/command/serverStatus/) — официальная документация метрик.
*   [MongoDB Ops Manager](https://www.mongodb.com/docs/ops-manager/current/) — документация Ops Manager.
*   [Percona PMM](https://docs.percona.com/percona-monitoring-and-management/) — документация PMM.
*   [SRE Workbook: Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/) — детально про Burn Rate.
