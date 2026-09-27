# Мониторинг dmesg: экспорт и алертинг

## Определения

**Мониторинг dmesg** — процесс сбора, централизации и алертинга сообщений ядра через системы мониторинга (Prometheus, Grafana, Loki, ELK). Включает экспорт kmsg в форматах, доступных для машинного анализа, настройку alerting-правил на критические события (OOM, MCE, I/O errors, hardware failures) и создание дашбордов для визуализации состояния ядра.

---

## Базовые концепции

### Архитектура мониторинга dmesg

```
Kernel Ring Buffer (kmsg)
  ├─ Прямой чтение (dmesg -J)
  │    ↓
  │  Экспортёр (dmesg_exporter / custom script)
  │    ↓
  │  Prometheus / Loki / ELK
  │    ↓
  │  Grafana / Kibana (дашборды)
  │    ↓
  │  Alertmanager (алерты)
  │
  ├─ journald (systemd-journald)
  │    ↓
  │  Promtail / Fluentd / Filebeat
  │    ↓
  │  Loki / Elasticsearch
  │
  └─ netconsole (удалённый приём)
       ↓
     syslog-ng / rsyslog (удалённый хост)
       ↓
     Централизованное хранилище
```

---

## Практические сценарии

### Экспорт dmesg в JSON для обработки

```bash
# Экспорт в JSON (util-linux 2.37+)
dmesg -J > /tmp/dmesg.json

# Фильтрация ошибок через jq
dmesg -J | jq -r '.[] | select(.level=="err" or .level=="crit") | "\(.timestamp) [\(.facility):\(.level)] \(.message)"'

# Сериализация для Prometheus
dmesg -J | jq -c '.[] | select(.level=="err") | {timestamp: .timestamp, facility: .facility, level: .level, message: .message}'
```

### Сбор dmesg через Promtail (Loki)

```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: dmesg
    static_configs:
      - targets:
          - localhost
        labels:
          job: dmesg
          host: ${HOSTNAME}
          __path__: /var/log/dmesg*

  - job_name: kmsg
    static_configs:
      - targets:
          - localhost
        labels:
          job: kmsg
          host: ${HOSTNAME}
    pipeline_stages:
      - regex:
          expression: '^(?P<timestamp>.*) \[(?P<level>.*)\] (?P<message>.*)'
      - labels:
          level:
          facility:
```

### Алертинг на критические события ядра (Prometheus)

```yaml
# Prometheus alerting rules для dmesg
groups:
  - name: kernel_alerts
    rules:
      # OOM Killer
      - alert: KernelOOM
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)oom.*kill|killed process"[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "OOM Killer active on {{ $labels.host }}"
          description: "OOM Killer killed processes in last 5 minutes"
          runbook_url: "https://wiki/runbook/oom"

      # Kernel Panic
      - alert: KernelPanic
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)kernel panic|kernel.*oops|BUG:"[5m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Kernel Panic/Oops on {{ $labels.host }}"

      # Hardware errors (MCE, EDAC)
      - alert: HardwareMemoryError
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)mce|edac|correctable|uncorrectable memory"[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Memory hardware error on {{ $labels.host }}"

      # I/O errors
      - alert: BlockIOError
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)blk_update_request.*I/O error|Buffer I/O error"[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Block I/O errors on {{ $labels.host }}"

      # NIC errors
      - alert: NICError
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)nic.*link.*down|carrier.*lost|rx_missed"[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "NIC errors on {{ $labels.host }}"

      # Thermal throttling
      - alert: ThermalThrottle
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)thermal|throttl|overheat"[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Thermal throttling on {{ $labels.host }}"

      # Conntrack table full
      - alert: ConntrackTableFull
        expr: |
          count_over_time({job="dmesg"} |~ "(?i)nf_conntrack.*table full"[5m]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack table full on {{ $labels.host }}"
```

### Дашборд dmesg в Grafana

```json
{
  "panels": [
    {
      "title": "Kernel Errors by Type",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum by (level) (count_over_time({job=\"dmesg\"} |~ \"(?i)error|fail|crit\" [5m]))",
          "legendFormat": "{{ level }}"
        }
      ]
    },
    {
      "title": "OOM Events",
      "type": "stat",
      "targets": [
        {
          "expr": "sum(count_over_time({job=\"dmesg\"} |~ \"(?i)oom.*kill\" [1h]))",
          "legendFormat": "OOM kills"
        }
      ]
    },
    {
      "title": "Hardware Errors",
      "type": "timeseries",
      "targets": [
        {
          "expr": "sum by (host) (count_over_time({job=\"dmesg\"} |~ \"(?i)mce|edac|aer\" [5m]))",
          "legendFormat": "{{ host }}"
        }
      ]
    }
  ]
}
```

### Сбор dmesg через rsyslog

```bash
# Настройка rsyslog для пересылки dmesg
cat <<'EOF' | sudo tee /etc/rsyslog.d/50-dmesg.conf
# Пересылка dmesg в централизованное хранилище
if $syslogfacility-text == 'kern' then @@logserver:514
& stop
EOF

# Перезапуск rsyslog
sudo systemctl restart rsyslog
```

### Netconsole для удалённого мониторинга

Netconsole отправляет сообщения ядра (dmesg) по UDP в реальном времени на удалённый хост. Работает даже при падении сети и disk subsystem — единственное требование: сетевой интерфейс должен быть поднят.

**Формат параметров модуля:**
```
netconsole=@<src-interface>,<src-port>@<dst-ip>,<dst-port>/<dst-mac>
```

| Параметр | Описание | Пример |
|:---|:---|:---|
| `@<interface>` | Локальный интерфейс для отправки | `@/eth0` |
| `<src-port>` | Исходный UDP-порт (0 = случайный) | `@/eth0,6666` |
| `@<dst-ip>` | IP-адрес приёмника | `@192.168.1.100` |
| `<dst-port>` | Порт приёмника | `@192.168.1.100/514` |
| `<dst-mac>` | MAC-адрес (для L2-приёма без IP) | `/aa:bb:cc:dd:ee:ff` |

**Быстрый запуск (тестирование):**

```bash
# Загрузка модуля с отправкой на удалённый хост
sudo modprobe netconsole netconsole=@/eth0,@192.168.1.100/514

# Проверка загрузки
lsmod | grep netconsole
dmesg | grep netconsole
```

**Постоянная настройка:**

```bash
# Метод 1: modprobe.d (рекомендуется)
cat <<'EOF' | sudo tee /etc/modprobe.d/netconsole.conf
options netconsole netconsole=@/eth0,@192.168.1.100/514
EOF

# Метод 2: Параметр ядра (GRUB)
# Добавить в /etc/default/grub:
# GRUB_CMDLINE_LINUX="... netconsole=@/eth0,@192.168.1.100/514"
# sudo update-grub
```

**Настройка приёмника:**

```bash
# Способ 1: nc (netcat) — для быстрой проверки
nc -lu 514

# Способ 2: rsyslog — для централизованного сбора
cat <<'EOF' | sudo tee /etc/rsyslog.d/51-netconsole.conf
# Приём netconsole по UDP
module(load="imudp")
input(type="imudp" port="514" address="0.0.0.0")

# Запись в файл по хосту-источнику
template(name="NetconsoleLog" type="string"
    string="/var/log/netconsole/%fromhost-ip%.log")

if $fromhost-ip != '127.0.0.1' then {
    action(type="omfile" dynaFile="NetconsoleLog")
    stop
}
EOF
sudo systemctl restart rsyslog

# Способ 3: vector — для отправки в Loki/ELK
# sources:
#   netconsole:
#     type: syslog
#     mode: udp
#     address: 0.0.0.0:514
```

**Безопасность:**

```bash
# Ограничение источника по IP (iptables)
sudo iptables -A INPUT -p udp --dport 514 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 514 -j DROP

# Вgenic: netconsole не шифрует данные. Используйте только в доверенных сетях.
# Для зашифрованной передачи: ipsec, WireGuard или SSH-туннель.
```

**Диагностика:**

```bash
# Проверка, что netconsole активен
dmesg | grep "netconsole: network logging started"

# Проверка конфигурации
cat /proc/net/netconsole

# Формат вывода:
# remote_ip  remote_port  local_ip  local_port  interface  level
# 192.168.1.100  514  0.0.0.0  6666  eth0  7
```

### Скрипт сбора dmesg для инцидентов

```bash
#!/bin/bash
# /usr/local/bin/dmesg_collect.sh
# Сбор dmesg для post-mortem анализа

INCIDENT_DIR="/var/log/incidents/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$INCIDENT_DIR"

# Полный dmesg
dmesg -T > "$INCIDENT_DIR/dmesg_full.log"

# Только ошибки
dmesg -T | grep -iE "error|fail|crit|panic|oops|mce|aer" > "$INCIDENT_DIR/dmesg_errors.log"

# JSON формат
dmesg -J > "$INCIDENT_DIR/dmesg.json" 2>/dev/null

# Hardware info
cat /proc/cpuinfo > "$INCIDENT_DIR/cpuinfo"
cat /proc/meminfo > "$INCIDENT_DIR/meminfo"
lsblk > "$INCIDENT_DIR/lsblk"

# Journalctl kernel
journalctl -k -b > "$INCIDENT_DIR/journalctl_kernel.log"

# Сжатие
tar czf "$INCIDENT_DIR.tar.gz" -C "$INCIDENT_DIR" .
rm -rf "$INCIDENT_DIR"

echo "Dmesg collected: $INCIDENT_DIR.tar.gz"
```

---

## Дополнительная информация

### Связанные темы

*   [**Обзор dmesg**](../../Diagnostics/Kernel/dmesg/index.md) — архитектура kmsg.
*   [**Использование dmesg**](../../Diagnostics/Kernel/dmesg/usage.md) — JSON-вывод, фильтрация.
*   [**Promtail**](../../../Monitoring/Promtail/) — сбор логов в Loki.
*   [**Grafana Alerting**](../../../Grafana/alerting/best_practices.md) — best practices алертинга.
*   [**sysctl Production**](../../Core/kernel/sysctl_production.md) — production-настройки kernel.
*   [**Анализ ошибок**](../../SystemAdministration/Logging/error_and_crash_analysis.md) — RCA kernel errors.
