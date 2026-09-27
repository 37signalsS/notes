# NFS: Мониторинг и алертинг

---

## Определения

**NFS-мониторинг** — процесс сбора, анализа и визуализации метрик сетевой файловой системы для обеспечения её доступности, производительности и предсказуемости в продакшен-среде.

**node_exporter** — агент Prometheus, собирающий метрики уровня ОС, включая NFS-статистику из `/proc/net/rpc/nfsd`, `/proc/net/rpc/rpc`, `/proc/self/mountstats`.

**nfsstat** — утилита для отображения статистики NFS-клиента и сервера (RPC-вызовы, повторы, ошибки).

**nfsiostat** — утилита для мониторинга задержек и пропускной способности каждой точки монтирования NFS.

**SLA (Service Level Agreement)** — соглашение об уровне сервиса, определяющее допустимый простой NFS (например, 99.9% доступности = 8.76 часов простоя в год).

**SLO (Service Level Objective)** — внутренняя цель по доступности/производительности (например, latency < 50ms для 99-го перцентиля).

---

## Теоретический блок

### Источники метрик NFS

| Источник | Тип | Метрики | Доступность |
| :--- | :--- | :--- | :--- |
| `/proc/net/rpc/nfsd` | Сервер | thread usage, packet stats, hero stats | На NFS-сервере |
| `/proc/net/rpc/rpc` | Клиент | RPC calls, retrans, timeouts | На NFS-клиенте |
| `/proc/self/mountstats` | Клиент | Per-mount RTT, exe time, operations | На NFS-клиенте |
| `nfsstat -c` | Клиент | calls, retrans, authrefresh | CLI |
| `nfsstat -s` | Сервер | server stats | CLI |
| `nfsiostat` | Клиент | avg RTT, avg exe, throughput | CLI |
| `showmount -e` | Сервер | экспорт список | CLI |
| node_exporter | Prometheus | nfs_* метрики | Агент |

### Ключевые метрики для мониторинга

| Метрика | Описание | Норма | Алерт |
| :--- | :--- | :--- | :--- |
| **retrans** | Количество повторных RPC-запросов | < 1% от calls | > 2% — критично |
| **th_usage** | Использование потоков nfsd | < 80% | > 80% — увеличить threads |
| **avg RTT** | Среднее время сетевого RTT | < 5 мс (LAN) | > 10 мс — проблема сети |
| **avg exe** | Среднее время выполнения операции | близко к RTT | >> RTT — проблема дисков |
| **rpc_calls** | Количество RPC-вызовов в секунду | Зависит от нагрузки | Резкий рост |
| **rpc_bad_xids** | Ошибки идентификации запросов | 0 | > 0 — проблема авторизации |
| **nfs_mount_return_error** | Ошибки монтирования | 0 | > 0 — проблема доступности |

### Архитектура мониторинга

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  NFS-сервер     │     │  NFS-клиент     │     │  NFS-клиент     │
│  node_exporter  │     │  node_exporter  │     │  node_exporter  │
│  (nfs_* метрики)│     │  (nfs_* метрики)│     │  (nfs_* метрики)│
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                         ┌───────▼───────┐
                         │   Prometheus  │
                         │   (сбор)      │
                         └───────┬───────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼───┐ ┌─────▼─────┐
              │  Grafana  │ │Alert  │ │  Loki     │
              │  (дашборд)│ │Manager│ │  (логи)   │
              └───────────┘ └───────┘ └───────────┘
```

---

## Практический блок

### Шаг 1: Настройка node_exporter на NFS-сервере

```bash
# Установка (если не установлена)
wget https://github.com/prometheus/node_exporter/releases/download/v1.7.0/node_exporter-1.7.0.linux-amd64.tar.gz
tar xzf node_exporter-1.7.0.linux-amd64.tar.gz
sudo cp node_exporter-1.7.0.linux-amd64/node_exporter /usr/local/bin/

# Systemd unit файл /etc/systemd/system/node_exporter.service
```

```ini
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
    --collector.nfs \
    --collector.nfsd \
    --collector.mountstats \
    --web.listen-address=:9100
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

### Шаг 2: Настройка Prometheus

Добавьте job в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'nfs-server'
    static_configs:
      - targets: ['10.0.0.5:9100']
    scrape_interval: 15s

  - job_name: 'nfs-clients'
    static_configs:
      - targets:
          - '10.0.0.10:9100'
          - '10.0.0.11:9100'
          - '10.0.0.12:9100'
    scrape_interval: 15s
```

### Шаг 3: Экспорт метрик NFS через скрипт

Если node_exporter недоступен, создайте кастомный экспортер:

```bash
#!/bin/bash
# /usr/local/bin/nfs_metrics.sh
# Экспорт метрик NFS в формате Prometheus

METRICS_FILE="/var/lib/node_exporter/nfs.prom"

# Серверные метрики
NFS_THREADS=$(cat /proc/fs/nfsd/threads)
TH_USAGE=$(awk '{print $1}' /proc/net/rpc/nfsd | head -1)

# Клиентские метрики
RPC_CALLS=$(nfsstat -c | awk '/calls/ {print $1}')
RPC_RETRANS=$(nfsstat -c | awk '/retrans/ {print $2}')

cat > "$METRICS_FILE" << EOF
# HELP nfs_server_threads Количество потоков nfsd
# TYPE nfs_server_threads gauge
nfs_server_threads $NFS_THREADS

# HELP nfs_server_th_usage Использование потоков (0-1)
# TYPE nfs_server_th_usage gauge
nfs_server_th_usage $TH_USAGE

# HELP nfs_client_rpc_calls Количество RPC-вызовов
# TYPE nfs_client_rpc_calls counter
nfs_client_rpc_calls $RPC_CALLS

# HELP nfs_client_rpc_retrans Количество повторных отправок
# TYPE nfs_client_rpc_retrans counter
nfs_client_rpc_retrans $RPC_RETRANS
EOF
```

```bash
# Cron каждые 30 секунд
* * * * * /usr/local/bin/nfs_metrics.sh
```

### Шаг 4: Алерт-правила для Prometheus

```yaml
# /etc/prometheus/rules/nfs_alerts.yml
groups:
  - name: nfs_alerts
    rules:
      # Сервер недоступен
      - alert: NFSServerDown
        expr: up{job="nfs-server"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "NFS-сервер {{ $labels.instance }} недоступен"
          description: "NFS-сервер не отвечает на scrape-запросы более 2 минут"

      # Высокий retrans rate
      - alert: NFSHighRetransRate
        expr: |
          rate(nfs_client_rpc_retrans[5m]) / rate(nfs_client_rpc_calls[5m]) > 0.02
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень повторов NFS на {{ $labels.instance }}"
          description: "Retrans rate {{ $value | humanizePercentage }} превышает 2%"

      # Переполнение потоков nfsd
      - alert: NFSServerHighThreadUsage
        expr: nfs_server_th_usage > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование потоков nfsd"
          description: "Использование потоков {{ $value | humanizePercentage }} превышает 80%"

      # Недостаточно потоков nfsd
      - alert: NFSServerLowThreads
        expr: nfs_server_threads < 32
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Мало потоков nfsd: {{ $value }}"
          description: "Рекомендуется минимум 32 потока для production"

      # NFS-экспорт недоступен
      - alert: NFSExportInaccessible
        expr: absent(up{job="nfs-server"} == 1)
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "NFS-экспорт недоступен"

      # Высокая задержка NFS
      - alert: NFSHighLatency
        expr: nfs_request_duration_seconds{quantile="0.99"} > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка NFS {{ $labels.instance }}"
          description: "P99 latency {{ $value }}s превышает 500ms"

      # Клиентские ошибки монтирования
      - alert: NFSClientMountErrors
        expr: increase(node_nfs_mount_return_error_total[1h]) > 0
        labels:
          severity: warning
        annotations:
          summary: "Ошибки монтирования NFS на {{ $labels.instance }}"
          description: "{{ $value }} ошибок монтирования за час"

      # Использование диска на NFS-сервере
      - alert: NFSServerDiskFull
        expr: |
          (node_filesystem_avail_bytes{fstype="nfs"} / node_filesystem_size_bytes{fstype="nfs"}) < 0.15
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "NFS-диск заполнен на {{ $value | humanizePercentage }}"
          description: "Осталось менее 15% места на NFS-хранилище"
```

### Шаг 5: Визуализация в Grafana

#### Основной дашборд NFS

Импортируйте готовый дашборд или создайте свой с-panel:

**Panel 1: NFS Server Health**
```promql
# Thread usage
nfs_server_th_usage

# Threads count
nfs_server_threads

# RPC calls rate
rate(nfs_server_rpc_calls_total[5m])
```

**Panel 2: Client Performance**
```promql
# Retrans rate
rate(nfs_client_rpc_retrans[5m]) / rate(nfs_client_rpc_calls[5m]) * 100

# RPC calls per second
rate(nfs_client_rpc_calls[5m])
```

**Panel 3: Mount Point Latency**
```promql
# Average RTT (from /proc/self/mountstats)
node_nfs_mountstats_transport_rtts{protocol="tcp"}

# Average execution time
node_nfs_mountstats_transport_exe_time{protocol="tcp"}
```

#### Готовые дашборды Grafana

| ID | Название | Описание |
| :--- | :--- | :--- |
| 11463 | NFS Server | Метрики сервера nfsd |
| 14351 | NFS Client | Клиентская статистика |
| 14503 | NFS Overview | Обзорная панель |

```bash
# Импорт через CLI:
grafana-cli plugins import 11463
```

### Шаг 6: Сбор логов NFS

#### Через journald

```bash
# Логи NFS-сервера:
journalctl -u nfs-server -f

# Логи NFS-клиента:
journalctl -t nfs-utils -f

# Экспорт в Loki через Promtail:
# /etc/promtail/config.yml
scrape_configs:
  - job_name: nfs-server
    static_configs:
      - targets: ['localhost']
        labels:
          job: nfs-server
          host: nfs1
    journal:
      labels:
        job: nfs-server
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        regex: 'nfs-server\.service'
        target_label: unit
```

#### Через auditd

```bash
# Аудит доступа к NFS-экспортам:
sudo auditctl -w /srv/nfs/ -p rwxa -k nfs_access
sudo auditctl -w /etc/exports -p wa -k nfs_config

# Поиск событий:
sudo ausearch -k nfs_access --start recent
```

---

## Дополнительная информация

### Автоматизация мониторинга

```bash
# Скрипт проверки здоровья NFS (для cron healthcheck):
#!/bin/bash
NFS_SERVER="10.0.0.5"

# Проверка доступности
if ! ping -c 1 -W 2 $NFS_SERVER &>/dev/null; then
    echo "CRITICAL: NFS server $NFS_SERVER unreachable" | \
        mail -s "NFS Alert" admin@example.com
    exit 2
fi

# Проверка экспортов
if ! showmount -e $NFS_SERVER &>/dev/null; then
    echo "WARNING: NFS exports not accessible" | \
        mail -s "NFS Alert" admin@example.com
    exit 1
fi

# Проверка retrans
RETRANS=$(nfsstat -c | awk '/retrans/ {print $2}')
CALLS=$(nfsstat -c | awk '/calls/ {print $1}')
if [ "$CALLS" -gt 0 ]; then
    RATE=$(echo "scale=2; $RETRANS * 100 / $CALLS" | bc)
    if (( $(echo "$RATE > 2" | bc -l) )); then
        echo "WARNING: Retrans rate ${RATE}%" | \
            mail -s "NFS Alert" admin@example.com
    fi
fi
```

### Интеграция с ELK/Loki

```yaml
# Fluent Bit конфигурация для NFS-логов:
[INPUT]
    Name              tail
    Path              /var/log/syslog
    Parser            syslog
    Tag               nfs.*

[FILTER]
    Name              grep
    Match             nfs.*
    Regex             message .*nfsd.*

[OUTPUT]
    Name              loki
    Match             nfs.*
    Labels            job=nfs, hostname=${HOSTNAME}
    Label_Keys        $level
```

### Чеклист мониторинга NFS

- [ ] Настроен node_exporter с коллекторами `nfs`, `nfsd`, `mountstats`
- [ ] Настроен Prometheus с scrape-интервалом 15 сек
- [ ] Настроены алерты: NFSServerDown, HighRetransRate, HighThreadUsage
- [ ] Настроен Grafana дашборд с ключевыми метриками
- [ ] Настроен сбор логов nfsd в Loki/ELK
- [ ] Настроен аудит доступа к NFS-экспортам (auditd)
- [ ] Настроен регулярный health-check скрипт
- [ ] Настроены уведомления (email/Slack/PagerDuty) при алертах

### Связанные темы

- **[NFS: Основные концепции](./index.md)** — архитектура и версии NFS.
- **[NFS: Производительность](./nfs_performance.md)** — метрики производительности.
- **[NFS: Диагностика](./nfs_troubleshooting.md)** — инструменты диагностики.
- **[NFS в Kubernetes](../../../../Kubernetes/Storage/CSI/csi_nfs_production.md)** — мониторинг NFS в K8s.
- **[Prometheus](../../../../Prometheus/)** — настройка Prometheus.
- **[Grafana](../../../../Grafana/)** — настройка Grafana.
