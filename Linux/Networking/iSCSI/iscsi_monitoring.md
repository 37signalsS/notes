# iSCSI: Мониторинг и наблюдаемость

Руководство по настройке мониторинга производительности iSCSI-стека, сбору метрик, настройке алертинга и анализу логов.

## Определения

| Термин | Описание |
| :--- | :--- |
| **IOPS (Input/Output Operations Per Second)** | Количество операций ввода-вывода в секунду. Ключевая метрика для баз данных. |
| **Throughput (Пропускная способность)** | Объем данных, передаваемых в единицу времени (MB/s, GB/s). |
| **Latency (Задержка)** | Время от момента отправки запроса до получения ответа (мкс, мс). |
| **Retransmission** | Повторная передача TCP-сегмента при потере. Индикатор проблем сети. |
| **Queue Depth** | Глубина очереди команд ввода-вывода. Влияет на параллелизм и задержку. |

## Зачем мониторить iSCSI

| Проблема | Последствие | Что отслеживать |
|----------|-------------|-----------------|
| Потеря сессии | Приложение не может читать/писать данные | `iscsiadm -m session`, `iscsi_active_sessions` |
| Рост latency | Зависание БД, таймауты приложений | `r_await`/`w_await` в `iostat` |
| Retransmissions TCP | Всплески latency, Head-of-Line Blocking | `nstat -az`, `TcpRetransSegs` |
| Сбой пути multipath | Деградация HA, single point of failure | `multipath -ll`, `multipath_active_paths` |
| Заполнение очереди I/O | Блокировка запросов, рост latency | `avgqu-sz` в `iostat` |
| Ошибки протокола | Разрыв сессий, потеря данных | `iscsi_err` в логах, `journalctl` |
| Перегрузка target | Отказ в обслуживании новых подключений | Метрики LIO (`io_count`, `active_sessions`) |

## Архитектура мониторинга iSCSI

```text
┌─────────────────────────────────────────────────────────────┐
│                      Grafana Dashboard                       │
│  (сессии, latency, throughput, retransmissions, paths)       │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                       Prometheus                             │
│  (scrape, alert rules, recording rules)                      │
└───┬──────────┬──────────┬──────────┬──────────┬─────────────┘
    │          │          │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼───────┐
│ node_ │ │ text  │ │ SNMP  │ │Black- │ │ custom    │
│export │ │ file  │ │Export │ │box    │ │ iSCSI     │
│  er   │ │collec.│ │  er   │ │Export │ │ exporter  │
└───────┘ └───────┘ └───────┘ └───────┘ └───────────┘
    │          │          │          │          │
    ▼          ▼          ▼          ▼          ▼
 /proc/    /var/lib   SNMP MIB   TCP probe  iscsiadm
 diskstats node_exp  (IF-MIB)   port 3260  -m session
           /iscsi.prom
```

### Источники метрик

| Источник | Что даёт | Как использовать |
|----------|----------|------------------|
| **`/proc/diskstats`** | Статистика блочных устройств (IOPS, throughput, latency) | `node_exporter` (автоматически) |
| **`/sys/class/net/*/statistics/`** | Счётчики сетевого интерфейса | `node_exporter` (автоматически) |
| **`iscsiadm -m session`** | Состояние iSCSI-сессий, ошибки, таймауты | Кастомный скрипт → textfile collector |
| **`multipath -ll`** | Состояние путей multipath | Кастомный скрипт → textfile collector |
| **`nstat -az`** | TCP-ретрансмиссии, ошибки протокола | `node_exporter` (через `netstat` collector) |
| **`/sys/kernel/config/target/`** | Метрики LIO target (сессии, LUN, ошибки) | Кастомный скрипт → textfile collector |
| **`journalctl -u iscsid`** | Логи демона iSCSI | `rsyslog`/`vector`/`promtail` → Loki |
| **SNMP** (IF-MIB, IP-MIB) | Стандартные сетевые метрики | SNMP Exporter + Prometheus |
| **tcpdump/Wireshark** | Глубокий анализ протокола | Отладка, не для мониторинга |

## Ключевые метрики iSCSI

### Метрики хоста (Initiator)

| Метрика | Источник | Критичность | Описание |
| :--- | :--- | :--- | :--- |
| **r_await / w_await** | `iostat -xy` | Высокая | Средняя задержка чтения/записи (мс). Для SSD: <1 мс, для HDD: <10 мс. |
| **avgqu-sz** | `iostat -xy` | Средняя | Средняя длина очереди устройств. >32 для SSD — признак проблемы. |
| **%util** | `iostat -xy` | Средняя | Утилизация устройства. >80% — узкое место. |
| **TcpRetransSegs** | `nstat -az` | Высокая | Счётчик TCP-ретрансмиссий. Рост = потер пакетов. |
| **TcpExtTCPLostRetransmit** | `nstat -az` | Критическая | Потерянные повторные передачи = повреждение данных или разрыв соединения. |
| **iscsi_err** | `/var/log/syslog` | Критическая | Протокольные ошибки iSCSI (авторизация, таймауты). |
| **session_timeo** | `iscsiadm -m session -P 3` | Высокая | Срабатывания replacement_timeout = нестабильная сеть. |

### Метрики сервера (Target, LIO)

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| **active_sessions** | `targetcli /iscsi/.../tpg1/acls` | Количество подключённых инициаторов |
| **read_only** | `/sys/kernel/config/target/...` | Флаг «только чтение» на LUN (аварийный режим) |
| **io_count** | `/proc/diskstats` | Количество операций I/O на block-устройстве |
| **incoming_bytes / outgoing_bytes** | `sar -n DEV` | Объем сетевого трафика на интерфейсе |

### Метрики LIO Target через sysfs

LIO (Linux-IO) — ядерный iSCSI target в Linux. Его метрики доступны через configfs и sysfs:

```bash
# Просмотр всех iSCSI-таргетов
ls /sys/kernel/config/iscsi/
# → iqdn.2026-01.com.example:storage.target01

# Количество активных сессий на таргете
cat /sys/kernel/config/iscsi/*/tpg1/nexus
# → 256 (макс. количество подключений)

# Список подключённых инициаторов (ACL)
ls /sys/kernel/config/iscsi/*/tpg1/acls/
# → iqn.2026-01.com.example:host01
# → iqn.2026-01.com.example:host02

# Количество LUN
ls /sys/kernel/config/iscsi/*/tpg1/luns/
# → lun0, lun1, lun2

# Статус ALUA для каждого LUN
cat /sys/kernel/config/iscsi/*/tpg1/luns/*/alua_tg_pt_state
# → active/optimized (норма)
# → active/unoptimized (пониженная производительность)
# → standby (резервный путь)
# → offline (недоступен)

# Статистика I/O через /proc/diskstats (для block-устройства target)
cat /proc/diskstats | grep sdb
# → 8 16 32896 245 1938 8741 11968 41263 0 6659 65628
#   поле 4: чтений завершено
#   поле 8: записей завершено
```

```bash
# Через targetcli (если установлен)
sudo targetcli /iscsi/iqn.2026-01.com.example:storage.target01/tpg1 ls
# → LUN-ы, ACL, порты

# Количество сессий через targetcli
sudo targetcli /iscsi/iqn.2026-01.com.example:storage.target01/tpg1/acls ls | grep -c "node_"
```

#### Метрики через /proc/net/softnet_stat (сетевой стек)

Для мониторинга сетевого стека target-сервера:

```bash
# Проблемы с обработкой softirq (может влиять на iSCSI target)
cat /proc/net/softnet_stat | awk '{print $2}'
# → 0 (dropped: должен быть 0)

# Ошибки socket overflow
cat /proc/net/softnet_stat | awk '{print $3}'
# → 0 (squeeze: должен быть 0)
```

## Сбор метрик

### iostat (sysstat)

Базовый инструмент для мониторинга блочных устройств.

```bash
# Установка
sudo apt install sysstat -y
sudo systemctl enable --now sysstat

# Текущая статистика по всем устройствам
iostat -xy 2 5
# → Вывод каждые 2 секунды, 5 итераций

# Только iSCSI-устройства (sdX, mapper/mpathX)
iostat -xy -d sdb,sdc,mapper/mpatha 2
```

**Пример вывода:**
```text
Device   r/s    w/s   rkB/s   wkB/s  rrqm/s  wrqm/s  %rrqm  %wrqm  r_await  w_await  aqu-sz  rareq-sz  wareq-sz  svctm  %util
sdb    150.00  200.00  2400.00  12800.00  0.00    15.00  0.00   7.00    0.50     2.10    0.72    16.00     64.00    1.14   40.00
```

**На что обращать внимание:**
- `r_await`/`w_await` > 5 мс для SSD — проверять сеть и_multipath
- `%util` > 80% — узкое место в дисковой подсистеме
- `wrqm/s` высокий — демонстрируется batching записей (нормально)

### sar (sysstat)

Исторические данные для анализа трендов.

```bash
# Сетевой трафик за последний час
sar -n DEV -s $(date -d "1 hour ago" +%H:%M:%S) | grep eth1

# TCP-ретрансмиссии за последний час
sar -n TCP,ETCP -s $(date -d "1 hour ago" +%H:%M:%S)

# Анализ через интерфейс iSCSI (eth1)
sar -n DEV -i 10 -f /var/log/sysstat/sa$(date +%d)
```

**Ключевые поля вывода sar -n DEV:**
- `rxpck/s` / `txpck/s` — пакетов в секунду (приём/передача)
- `rxkB/s` / `txkB/s` — КБайт в секунду (приём/передача)
- `rxerr/s` / `txerr/s` — ошибки на уровне L2 (должно быть 0)
- `rxdrop/s` / `txdrop/s` — отброшенные ядром (должно быть 0)

**На что обращать внимание:**
- `rxerr/s` > 0 — проблемы с кабелем, коммутатором или драйвером NIC
- `rxdrop/s` > 0 — переполнение буфера приёмника, проблемы с IRQ affinity

### nstat — TCP-метрики в реальном времени

```bash
# Все TCP-метрики (краткий вывод)
nstat -az | grep -E "Retrans|Err|Lost|Timeout"

# Только ретрансмиссии
nstat -az TcpExtTcpRetransSegs

# Потери пакетов на уровне ядра
nstat -az TcpExtTCPLostRetransmit

# Ошибки TCP
nstat -az TcpExtTCPAbortOnTimeout

# Полный вывод для диагностики
nstat -az 2>/dev/null | awk '/^Tcp/ || /^Ip/ {print}'
```

**Ключевые счётчики nstat:**

| Счётчик | Описание | Порог алерта |
|---------|----------|--------------|
| `TcpRetransSegs` | Сегменты TCP, отправленные повторно | Рост >10/мин |
| `TcpExtTCPLostRetransmit` | Потерянные повторные передачи | >0 (критично) |
| `TcpExtTCPTimeouts` | Таймауты TCP | >5/мин |
| `TcpExtTCPAbortOnTimeout` | Аборты соединения по таймауту | >0 |
| `TcpExtTCPSpuriousRTOs` | Ложные RTO (retransmission timeout) | >10/мин |
| `TcpExtTCPSackRecovery` | Recovery через Selective ACK | Рост — индикатор проблем |
| `TcpExtTCPRenoRecovery` | Recovery через Reno (менее эффективен) | >0 |
| `TcpExtTCPMemoryPressures` | Давление на память TCP | >0 |
| `IpExtInErrors` | Ошибки на уровне IP | >0 |

### iscsiadm — статус сессий

```bash
# Краткий статус
sudo iscsiadm -m session
# → tcp: [1] 192.168.200.20:3260,1 iqn.2026-07.com.example:storage.target01 (non-flash)

# Детальный статус (уровень 3)
sudo iscsiadm -m session -P 3
# → Показывает: iqn, IP, порт, интерфейс, состояние, таймауты, ошибки
```

**Ключевые поля вывода `-P 3`:**
- `State` — `LOGGED IN` (норма), `FAILED` (проблема)
- `Auth` — `CHAP` / `None`
- `Timeo` — текущие таймауты

### Мониторинг Multipath

```bash
# Статус всех multipath-путей
sudo multipath -ll
# → mpatha (WWID) dm-0 LIO-ORG,disk1
#   active ready running — путь исправен
#   faulty blocked — проблема

# Логи multipathd в реальном времени
sudo journalctl -u multipathd -f

# Детальный вывод с форматированием
multipathd show paths format "%d %t %T %p %s %z"
# → H:0 C:0 t:0 L:0 0 0 sdg  1 active ready running  0  [volatile]
#   H=host, C=channel, t=target, L=LUN
#   s=символьное состояние, z=приоритет
```

**Ключевые состояния multipath:**
- `active ready running` — путь активен и работает
- `active ready faulty` — путь помечен как ошибочный
- `standby ready running` — резервный путь готов
- `faulty blocked` — путь заблокирован (проблема)

### Blackbox Exporter (TCP-мониторинг)

Blackbox Exporter Prometheus позволяет проверять доступность iSCSI-порталов на уровне TCP и HTTP.

#### Установка

```bash
wget https://github.com/prometheus/blackbox_exporter/releases/latest/download/blackbox_exporter-*.linux-amd64.tar.gz
tar xzf blackbox_exporter-*.linux-amd64.tar.gz
sudo cp blackbox_exporter-*/blackbox_exporter /usr/local/bin/
```

#### Конфигурация (`/etc/blackbox_exporter/config.yml`)

```yaml
modules:
  tcp_connect:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: ip4
      ip_protocol_fallback: false
  icmp:
    prober: icmp
    timeout: 5s
```

#### Конфигурация Prometheus для Blackbox

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'blackbox_iscsi'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
          - 192.168.200.20:3260  # iSCSI Portal 1
          - 192.168.200.21:3260  # iSCSI Portal 2
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115  # Адрес blackbox_exporter
```

#### Прометей-запросы для Blackbox

```promql
# Доступность iSCSI-портала (1 = доступен, 0 = недоступен)
probe_success{job="blackbox_iscsi"}

# Время TCP-подключения к порталу
probe_duration_seconds{job="blackbox_iscsi"}

# Алерт: iSCSI Portal недоступен
# probe_success{job="blackbox_iscsi"} == 0
```

## Настройка Prometheus

### Экспорт метрик iSCSI

Для интеграции с Prometheus используется `textfile collector` из `node_exporter`.

#### Скрипт сбора метрик

```bash
#!/bin/bash
# /usr/local/bin/iscsi_metrics.sh
# Собирает метрики iSCSI и записывает в текстовый файл
# Важно: запись атомарная (mv), чтобы избежать partial reads при скрапинге

PROM_DIR="/var/lib/node_exporter/textfile_collector"
mkdir -p "$PROM_DIR"
OUT="$PROM_DIR/iscsi.prom"
OUT_TMP="$PROM_DIR/iscsi.prom.$$"

# Метрика: количество активных сессий
SESSIONS=$(sudo iscsiadm -m session 2>/dev/null | grep -c "tcp:")
echo "iscsi_active_sessions $SESSIONS" > "$OUT_TMP"

# Метрика: статус сессий (1 = logged in, 0 = not)
while IFS= read -r line; do
    TARGET_IQN=$(echo "$line" | awk '{print $3}')
    PORTAL=$(echo "$line" | awk '{print $2}')
    STATE=$(echo "$line" | grep -c "logged in")
    echo "iscsi_session_state{target=\"$TARGET_IQN\",portal=\"$PORTAL\"} $STATE" >> "$OUT_TMP"
done < <(sudo iscsiadm -m session -P 1 2>/dev/null | grep "Target:")

# Метрика: TCP-ретрансмиссии
RETRANS=$(nstat -az TcpExtTcpRetransSegs 2>/dev/null | awk '/TcpExtTcpRetransSegs/ {print $2}')
echo "iscsi_tcp_retransmissions_total ${RETRANS:-0}" >> "$OUT_TMP"

# Метрика: ошибки iSCSI в kernel ring buffer
ERRS=$(dmesg 2>/dev/null | grep -c -i "iscsi")
echo "iscsi_kernel_errors_total ${ERRS:-0}" >> "$OUT_TMP"

# Метрика: состояние multipath (количество faulty путей)
FAULTY=$(multipath -ll 2>/dev/null | grep -c "faulty" || echo 0)
echo "iscsi_multipath_faulty_paths $FAULTY" >> "$OUT_TMP"

# Метрика: активные multipath-устройства
MAPS=$(multipath -ll 2>/dev/null | grep -c "^mpath" || echo 0)
echo "iscsi_multipath_maps_total $MAPS" >> "$OUT_TMP"

# Атомарная запись: mv не прерывается, Prometheus всегда видит либо старый, либо новый файл
mv "$OUT_TMP" "$OUT"
```

#### Установка скрипта

```bash
sudo install -m 755 /dev/stdin /usr/local/bin/iscsi_metrics.sh << 'SCRIPT'
#!/bin/bash
# ... (содержимое скрипта выше)
SCRIPT

# Создание директории для textfile collector
sudo mkdir -p /var/lib/node_exporter/textfile_collector
sudo chown node_exporter:node_exporter /var/lib/node_exporter/textfile_collector
```

#### Вариант запуска: systemd timer (рекомендуется вместо cron)

```ini
# /etc/systemd/system/iscsi-metrics.service
[Unit]
Description=iSCSI Metrics Collector for Prometheus
After=network.target iscsid.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/iscsi_metrics.sh
User=node_exporter
Group=node_exporter
```

```ini
# /etc/systemd/system/iscsi-metrics.timer
[Unit]
Description=Run iSCSI metrics collection every 30 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=30s
AccuracySec=1s

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now iscsi-metrics.timer

# Проверка последнего запуска
sudo systemctl status iscsi-metrics.service
sudo journalctl -u iscsi-metrics.service -n 20
```

#### Настройка node_exporter

```bash
# В /etc/default/node_exporter (Debian/Ubuntu):
NODE_EXPORTER_OPTS="--collector.textfile.directory=/var/lib/node_exporter/textfile_collector"

# В /etc/sysconfig/node_exporter (RHEL/CentOS):
NODE_EXPORTER_ADD_OPTS="--collector.textfile.directory=/var/lib/node_exporter/textfile_collector"

# Или через systemd unit (проверить ExecStart в /etc/systemd/system/node_exporter.service)
# Добавить флаг: --collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

### Запросы PromQL (примеры)

```promql
# Активные сессии
iscsi_active_sessions

# Все сессии утеряны
iscsi_active_sessions == 0

# Сессия упала с целевого значения (алерт)
iscsi_active_sessions < 2

# Рост TCP-ретрансмиссий за 5 минут
rate(iscsi_tcp_retransmissions_total[5m]) > 0

# Высокий уровень ретрансмиссий (>10/сек)
rate(iscsi_tcp_retransmissions_total[5m]) > 10

# Высокая утилизация устройства (из node_exporter + iostat)
rate(node_disk_io_time_seconds_total{device=~"sd.*|mpath.*"}[5m]) > 0.8

# Задержка чтения/записи (ms) — из node_exporter
rate(node_disk_read_time_seconds_total{device=~"sd.*|mpath.*"}[5m])
  / rate(node_disk_reads_completed_total{device=~"sd.*|mpath.*"}[5m]) * 1000 > 5

# Multipath: есть faulty пути
iscsi_multipath_faulty_paths > 0

# Через Blackbox Exporter: iSCSI Portal недоступен
probe_success{job="blackbox_iscsi"} == 0

# Время TCP-подключения к порталу > 2 секунды
probe_duration_seconds{job="blackbox_iscsi"} > 2

# Ошибки ядра iSCSI
increase(iscsi_kernel_errors_total[1h]) > 0
```

## Алертинг (Alerting)

### Prometheus Alertmanager — правила

```yaml
# /etc/prometheus/rules/iscsi_alerts.yml
groups:
  - name: iscsi_alerts
    rules:
      # === КРИТИЧЕСКИЕ ===

      - alert: iSCSISessionDown
        expr: iscsi_active_sessions == 0
        for: 1m
        labels:
          severity: critical
          component: iscsi
        annotations:
          summary: "iSCSI: нет активных сессий"
          description: "Все iSCSI-сессии на {{ $labels.instance }} утеряны."
          runbook: "Проверить сетевую доступность портала 3260, логи iscsid, multipath -ll"

      - alert: iSCSISessionsDropped
        expr: iscsi_active_sessions < 2 and iscsi_active_sessions > 0
        for: 1m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: количество сессий ниже ожидаемого"
          description: "На {{ $labels.instance }} {{ $value }} активных сессий (ожидалось >= 2)."

      - alert: MultipathDegraded
        expr: iscsi_multipath_faulty_paths > 0
        for: 1m
        labels:
          severity: critical
          component: multipath
        annotations:
          summary: "iSCSI Multipath: есть faulty пути"
          description: "На {{ $labels.instance }} {{ $value }} faulty путей multipath."
          runbook: "Проверить `multipath -ll`, логи multipathd, кабели/коммутаторы"

      - alert: iSCSIPortalDown
        expr: probe_success{job="blackbox_iscsi"} == 0
        for: 1m
        labels:
          severity: critical
          component: iscsi
        annotations:
          summary: "iSCSI: портал {{ $labels.instance }} недоступен"
          description: "TCP-подключение к порту 3260 не устанавливается."
          runbook: "Проверить Target-сервер, firewall на порту 3260, маршрутизацию"

      # === ПРЕДУПРЕЖДЕНИЯ ===

      - alert: iSCSIRetransmissionsHigh
        expr: rate(iscsi_tcp_retransmissions_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: высокий уровень TCP-ретрансмиссий"
          description: "Более 10 ретрансмиссий/сек на {{ $labels.instance }}."
          runbook: "Проверить `nstat -az | grep Retrans`, сеть, MTU, Jumbo Frames"

      - alert: iSCSILatencyHigh
        expr: |
          rate(node_disk_io_time_seconds_total{device=~"sd.*|mpath.*"}[5m]) > 0.8
        for: 10m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: высокая утилизация устройства"
          description: "Утилизация {{ $labels.device }} превышает 80% в течение 10 минут."
          runbook: "Проверить `iostat -xy 1`, очередь I/O, throughput"

      - alert: iSCSILatencyReadHigh
        expr: |
          rate(node_disk_read_time_seconds_total{device=~"sd.*|mpath.*"}[5m])
          / rate(node_disk_reads_completed_total{device=~"sd.*|mpath.*"}[5m]) * 1000 > 5
        for: 5m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: высокая задержка чтения ({{ $value }} мс)"
          description: "Средняя задержка чтения на {{ $labels.device }} превышает 5 мс."
          runbook: "Проверить `iostat -xy 1`, multipath, сеть"

      - alert: iSCSISessionRecovery
        expr: increase(node_kernel_recvmmsg_errors_total[10m]) > 0
        for: 1m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: срабатывание session recovery"
          description: "Обнаружены ошибки восстановления сессий на {{ $labels.instance }}."
          runbook: "Проверить логи `journalctl -u iscsid`, `iscsiadm -m session -P 3`"

      - alert: iSCSITargetUnreachable
        expr: probe_duration_seconds{job="blackbox_iscsi"} > 2
        for: 5m
        labels:
          severity: warning
          component: iscsi
        annotations:
          summary: "iSCSI: высокий RTT к порталу {{ $labels.instance }}"
          description: "Время TCP-подключения {{ $value }} сек (норма < 0.5 сек)."
          runbook: "Проверить сеть, `ping -M do -s 8972 <target_ip>`, `mtr`"
```

## Анализ логов

### Источники логов iSCSI

| Источник | ОС/Система | Назначение |
|----------|------------|------------|
| `/var/log/syslog` | Debian/Ubuntu | Общие системные логи (включая iSCSI) |
| `/var/log/messages` | RHEL/CentOS | Общие системные логи |
| `journalctl -u iscsid` | Systemd | Логи демона iSCSI |
| `journalctl -k` | Systemd | Kernel ring buffer (iSCSI/SCSI ошибки) |
| `dmesg` | Все | Kernel ring buffer (аналог journalctl -k) |
| `/var/log/kern.log` | Debian/Ubuntu | Только ядерные логи |

### Централизованный сбор логов

```bash
# Основные источники логов iSCSI
/var/log/syslog          # Debian/Ubuntu
/var/log/messages        # RHEL/CentOS
journalctl -u iscsid     # Systemd journal

# Фильтрация событий iSCSI за последний час
sudo journalctl -u iscsid --since "1 hour ago" | grep -iE "session|login|error|timeout"

# Только ошибки iSCSI из kernel ring buffer
sudo dmesg | grep -iE "iscsi|scsi" | grep -iE "error|fail|timeout|abort"

# Логи multipathd
sudo journalctl -u multipathd --since "1 hour ago"
```

#### Фильтрация через rsyslog

Для выноса iSCSI-событий в отдельный файл:

```bash
# /etc/rsyslog.d/30-iscsi.conf
# Все сообщения iscsid в отдельный файл
:programname, isequal, "iscsid" /var/log/iscsid.log

# Сообщения ядра, связанные с iSCSI/SCSI
:msg, contains, "iSCSI" /var/log/iscsi_kernel.log
:msg, contains, "scsi" /var/log/iscsi_kernel.log & stop
```

```bash
# Перезапуск rsyslog
sudo systemctl restart rsyslog
```

#### Ротация логов

```bash
# /etc/logrotate.d/iscsi
/var/log/iscsid.log /var/log/iscsi_kernel.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 syslog adm
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate
    endscript
}
```

### Типичные сообщения в логах

| Сообщение | Уровень | Описание | Действие |
| :--- | :--- | :--- | :--- |
| `iSCSI Login successful` | INFO | Успешное подключение | Норма |
| `iSCSI connection timeout` | WARNING | Потеря соединения, срабатывание recovery | Проверить сеть, multipath |
| `iSCSI login failed: authorization failure` | ERROR | Ошибка CHAP или ACL | Проверить `iscsid.conf`, ACL на Target |
| `iSCSI login failed: initiator not authorized` | ERROR | IQN инициатора не в ACL | Добавить IQN в ACL target-сервера |
| `scsi hostX: iSCSI: session recovery timed out` | CRITICAL | Сессия не восстановлена, устройство OFFLINE | Переподключение, проверка Target |
| `iscsiX: host alloc failed` | ERROR | Не удалось выделить SCSI-хост | Перезапуск iscsid, проверка памяти |
| `Multipath path failure` | WARNING | Один из путей multipath упал | `multipath -ll`, проверка кабелей |
| `Multipath path thrashing` | WARNING | Регулярные переключения путей | Увеличить `fast_io_fail_tmo` |
| `TCP: out of memory` | WARNING | Нехватка памяти для TCP-буферов | Увеличить `net.core.rmem_max` |
| `iscsiX: TCP connection reset` | WARNING | TCP RST от Target | Проверить Target, firewall |

### tcpdump для глубокого анализа

```bash
# Захват iSCSI-трафика (для анализа в Wireshark)
sudo tcpdump -i eth1 port 3260 -w /tmp/iscsi_debug.pcap -c 1000

# Анализ конкретных фаз (без записи в файл)
sudo tcpdump -i eth1 port 3260 -v 2>&1 | grep -iE "login|read|write|reject"

# Захват только SYN-пакетов (проверка TCP Handshake)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-syn != 0' -c 20

# Захват только ошибок (RST-пакеты)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Фильтрация по конкретному хосту
sudo tcpdump -i eth1 host 192.168.200.20 and port 3260 -w /tmp/iscsi_host.pcap
```

**Wireshark-фильтры:**
- `iscsi` — все iSCSI-пакеты
- `iscsi.opcode == 0x03` — SCSI Read
- `iscsi.opcode == 0x04` — SCSI Write
- `iscsi.status != 0x00` — ошибки протокола
- `iscsi.opcode == 0x01` — Login Request
- `iscsi.opcode == 0x02` — Login Response
- `tcp.flags.reset == 1` — TCP RST (сброс соединения)

## Скрипты автоматизации

### Проверка здоровья iSCSI (health check)

```bash
#!/bin/bash
# /usr/local/bin/iscsi_health_check.sh
# Быстрая проверка состояния iSCSI-стека
# Использование: iscsi_health_check.sh [portal_ip]

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

echo "=== iSCSI Health Check ==="
echo "Дата: $(date)"
echo "Хост: $(hostname)"
echo ""

# 1. Проверка демона iscsid
echo -n "1. iscsid: "
if systemctl is-active --quiet iscsid; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}FAILED (is not running)${NC}"
    ((ERRORS++))
fi

# 2. Количество активных сессий
echo -n "2. Активные сессии: "
SESSION_COUNT=$(iscsiadm -m session 2>/dev/null | grep -c "tcp:" || echo 0)
if [ "$SESSION_COUNT" -gt 0 ]; then
    echo -e "${GREEN}$SESSION_COUNT${NC}"
else
    echo -e "${RED}0 (нет сессий)${NC}"
    ((ERRORS++))
fi

# 3. Статус каждой сессии
echo ""
echo "3. Детали сессий:"
iscsiadm -m session 2>/dev/null | while read -r line; do
    PORTAL=$(echo "$line" | awk '{print $2}')
    IQN=$(echo "$line" | awk '{print $3}')
    echo "   Portal: $PORTAL | IQN: $IQN"

    # Проверка состояния
    STATE=$(iscsiadm -m session -P 1 2>/dev/null | grep -A1 "$PORTAL" | grep "State" | awk '{print $NF}')
    if [ "$STATE" = "LOGGED" ]; then
        echo -e "   Состояние: ${GREEN}LOGGED IN${NC}"
    else
        echo -e "   Состояние: ${RED}$STATE${NC}"
        ((ERRORS++))
    fi
done

# 4. Проверка multipath
echo ""
echo -n "4. Multipath: "
if command -v multipath &>/dev/null; then
    FAULTY=$(multipath -ll 2>/dev/null | grep -c "faulty" || echo 0)
    if [ "$FAULTY" -eq 0 ]; then
        echo -e "${GREEN}OK (0 faulty paths)${NC}"
    else
        echo -e "${RED}$FAULTY faulty paths${NC}"
        ((ERRORS++))
    fi
else
    echo -e "${YELLOW}multipath не установлен${NC}"
fi

# 5. TCP-ретрансмиссии
echo -n "5. TCP Retransmissions: "
RETRANS=$(nstat -az TcpExtTcpRetransSegs 2>/dev/null | awk '/TcpExtTcpRetransSegs/ {print $2}' || echo 0)
if [ "$RETRANS" -lt 100 ]; then
    echo -e "${GREEN}$RETRANS${NC}"
else
    echo -e "${YELLOW}$RETRANS (высокое значение)${NC}"
fi

# 6. Доступность портала (если указан)
if [ -n "${1:-}" ]; then
    echo -n "6. Портал $1:3260: "
    if timeout 3 bash -c "echo >/dev/tcp/$1/3260" 2>/dev/null; then
        echo -e "${GREEN}доступен${NC}"
    else
        echo -e "${RED}недоступен${NC}"
        ((ERRORS++))
    fi
fi

echo ""
if [ "$ERRORS" -eq 0 ]; then
    echo -e "Итог: ${GREEN}OK${NC}"
    exit 0
else
    echo -e "Итог: ${RED}$ERRORS ошибок${NC}"
    exit 1
fi
```

```bash
# Установка
sudo install -m 755 /dev/stdin /usr/local/bin/iscsi_health_check.sh << 'SCRIPT'
#!/bin/bash
# ... (содержимое выше)
SCRIPT

# Запуск
sudo /usr/local/bin/iscsi_health_check.sh 192.168.200.20
```

## Интеграция с Grafana

### Дашборд iSCSI

Ключевые панели для дашборда:

| Панель | Тип | Запрос PromQL | Описание |
|--------|-----|---------------|----------|
| **Активные сессии** | Stat | `iscsi_active_sessions` | Количество активных iSCSI-сессий |
| **Multipath faulty** | Stat | `iscsi_multipath_faulty_paths` | Количество faulty путей (должно быть 0) |
| **Throughput чтения** | Time Series | `rate(node_disk_read_bytes_total{device=~"sd.*\|mpath.*"}[5m])` | Пропускная способность чтения |
| **Throughput записи** | Time Series | `rate(node_disk_written_bytes_total{device=~"sd.*\|mpath.*"}[5m])` | Пропускная способность записи |
| **Latency чтения** | Time Series | `rate(node_disk_read_time_seconds_total{device=~"sd.*\|mpath.*"}[5m]) / rate(node_disk_reads_completed_total{device=~"sd.*\|mpath.*"}[5m]) * 1000` | Средняя задержка чтения (мс) |
| **Latency записи** | Time Series | `rate(node_disk_write_time_seconds_total{device=~"sd.*\|mpath.*"}[5m]) / rate(node_disk_writes_completed_total{device=~"sd.*\|mpath.*"}[5m]) * 1000` | Средняя задержка записи (мс) |
| **Retransmissions** | Time Series | `rate(iscsi_tcp_retransmissions_total[5m])` | TCP-ретрансмиссии в секунду |
| **Portal доступность** | Time Series | `probe_success{job="blackbox_iscsi"}` | TCP-доступность порталов (1/0) |
| **Queue depth** | Gauge | `node_disk_io_time_seconds_total{device=~"sd.*\|mpath.*"} * 1000` | Утилизация устройства (%) |

### Рекомендации по дашборду

1. **Временные ряды (Time Series)** — основные графики: throughput, latency, retransmissions
2. **Stat-панели** — для текущих значений: сессии, multipath, portal доступность
3. **Table** — для списка сессий и состояния multipath-путей
4. **Thresholds** — используйте цветовые пороги (green/yellow/red) для latency и throughput
5. **Variables** — добавьте variable `$instance` для фильтрации по хостам

## Опорные значения (Baselines)

### Производительность iSCSI (референтные значения)

| Параметр | HDD (7200 RPM) | SSD (SATA) | SSD (NVMe) | Источник |
|----------|----------------|------------|------------|----------|
| **IOPS (read)** | 100-200 | 50K-90K | 200K-500K | `iostat -xy` |
| **IOPS (write)** | 100-150 | 40K-80K | 150K-400K | `iostat -xy` |
| **Latency (read)** | 5-15 мс | 0.1-0.5 мс | 0.02-0.1 мс | `r_await` в `iostat` |
| **Latency (write)** | 5-20 мс | 0.1-1 мс | 0.02-0.2 мс | `w_await` в `iostat` |
| **Throughput (10GbE)** | 200-400 MB/s | 400-600 MB/s | 600-1100 MB/s | `sar -n DEV` |

### Сетевые пороги

| Метрика | Норма | Предупреждение | Критично |
|---------|-------|----------------|----------|
| **TCP Retransmissions** | 0-5/мин | 10-50/мин | >50/мин |
| **r_await (SSD)** | <1 мс | 1-5 мс | >5 мс |
| **r_await (HDD)** | <10 мс | 10-20 мс | >20 мс |
| **%util** | <50% | 50-80% | >80% |
| **avgqu-sz (SSD)** | <2 | 2-8 | >32 |
| **avgqu-sz (HDR)** | <4 | 4-16 | >32 |
| **rxerr/s** | 0 | >0 | >10/сек |
| **Multipath faulty paths** | 0 | 0 | >0 |
| **iSCSI login timeout** | <1 сек | 1-5 сек | >5 сек |

### Проверка.Timestamp

Для проверки актуальности данных используйте:

```bash
# Время последней модификации .prom файла
ls -la /var/lib/node_exporter/textfile_collector/iscsi.prom
# → файл должен обновляться каждые 30 секунд

# Проверка, что Prometheus скрапит метрику
curl -s http://localhost:9100/metrics | grep iscsi_active_sessions
```

## См. также

- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — детальный разбор ошибок и методы отладки
- **[Оптимизация производительности iSCSI](./iscsi_performance.md)** — тюнинг TCP, Jumbo Frames, NUMA
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — настройка и мониторинг путей
- **[Безопасность iSCSI](./iscsi_security.md)** — CHAP, ACL, изоляция SAN
- **[Основные концепции iSCSI](./iscsi_concepts.md)** — теория протокола
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — установка и настройка open-iscsi
