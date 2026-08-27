# ICMP: Мониторинг в продакшене

## Определения

**ICMP-мониторинг** — проактивный контроль доступности узлов, качества канала и целостности маршрутизации на основе ICMP-сообщений (Echo Request/Reply, Time Exceeded, Destination Unreachable). В продакшене используется как первичный L3-check для алертинга и SLA.

**Blackbox-мониторинг** — подход, при котором система проверяет цель извне, не устанавливая агента на проверяемом узле. Для ICMP это означает отправку Echo Request с внешнего ноды Prometheus/Zabbix.

**Probe-метрики** — числовые показатели, собранные во время ICMP-проверки: RTT, потери, jitter.

## Основные концепции

### Зачем мониторить ICMP в продакшене

| Аспект | Что даёт мониторинг |
| :--- | :--- |
| **Доступность L3** | Быстрое обнаружение падения узла/сегмента сети |
| **Качество канала** | Рост RTT/jitter указывает на перегрузку или деградацию |
| **MTU-проблемы** | Появление ICMP Destination Unreachable (Type 3 Code 4) сигнализирует о PMTU Black Hole |
| **Маршрутизация** | Аномалии в ICMP Redirect или рост Time Exceeded указывают на петли |
| **DoS-атаки** | Всплеск InMsgs/InErrors = ICMP Flood |

### Метрики ядра Linux для мониторинга

Ядро Linux ведет счетчики ICMPv4/IPv6, доступные через `/proc/net/snmp` и `/proc/net/snmp6`:

| Метрика (IPv4) | Описание | Threshold |
| :--- | :--- | :--- |
| `IcmpInMsgs` | Всего получено ICMP | базовый |
| `IcmpInErrors` | Ошибки контрольной суммы | > 0 аномалия |
| `IcmpInDestUnreachs` | Destination Unreachable | рост = проблемы маршрутизации |
| `IcmpInTimeExcds` | Time Exceeded | рост = петли или traceroute-flood |
| `IcmpInEchos` | Echo Request получено | базовый |
| `IcmpInEchoReps` | Echo Reply получено | базовый |
| `IcmpInParmProbs` | Parameter Problem | > 0 = ошибки в заголовках |
| `IcmpOutMsgs` | Отправлено ICMP | базовый |

| Метрика (IPv6) | Описание | Threshold |
| :--- | :--- | :--- |
| `Icmp6InMsgs` | Всего ICMPv6 | базовый |
| `Icmp6InPktTooBigs` | Packet Too Big | рост = PMTUD проблемы |
| `Icmp6InDestUnreachs` | Destination Unreachable | рост |
| `Icmp6InTimeExcds` | Time Exceeded | рост |
| `Icmp6InNeighborSolicits` | NDP NS | базовый |
| `Icmp6InNeighborAdverts` | NDP NA | базовый |

## Практические сценарии

### 1. Blackbox Exporter (Prometheus) — ICMP probe

Blackbox Exporter умеет проверять ICMP напрямую. Это самый распространенный способ L3-мониторинга в Kubernetes/裸金属.

**Требование:** capability `cap_net_raw+ep` на бинарнике blackbox_exporter.

```bash
# Установка capability (без SUID root)
sudo setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter

# Проверка
getcap /usr/local/bin/blackbox_exporter
# → /usr/local/bin/blackbox_exporter cap_net_raw+ep
```

**Конфигурация модуля (`blackbox.yml`):**

```yaml
modules:
  icmp:
    prober: icmp
    timeout: 5s
    source_ip_address: 10.0.0.1
    preferred_ip_protocol: "ip4"
```

**ServiceMonitor (Kubernetes):**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: icmp-monitoring
  namespace: monitoring
spec:
  jobLabel: blackbox
  selector:
    matchLabels:
      app: blackbox-exporter
  endpoints:
    - port: web
      interval: 30s
      path: /probe
      params:
        module:
          - icmp
      relabelings:
        - sourceLabels: [__param_target]
          targetLabel: target
        - sourceLabels: [__param_target]
          replacement: ${1}
          targetLabel: instance
```

**Prometheus scrape config (裸金属):**

```yaml
scrape_configs:
  - job_name: 'blackbox-icmp'
    metrics_path: /probe
    params:
      module: [icmp]
    static_configs:
      - targets:
        - 10.0.0.10
        - 10.0.0.11
        - 10.0.0.12
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

### 2. Prometheus Alert Rules для ICMP

```yaml
groups:
  - name: icmp_alerts
    rules:
      - alert: HostDown
        expr: probe_success{job="blackbox-icmp"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Хост {{ $labels.instance }} недоступен (ICMP)"
          description: "ICMP probe не отвечает более 1 минуты."

      - alert: HighPacketLoss
        expr: rate(IcmpInDestUnreachs[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий рост ICMP Destination Unreachable на {{ $labels.instance }}"
          description: "Более 10 ICMP unreachable/сек — возможна проблема маршрутизации."

      - alert: ICMPSuspiciousFlood
        expr: rate(IcmpInMsgs[1m]) > 1000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "ICMP Flood на {{ $labels.instance }}"
          description: "Более 1000 ICMP/сек — возможна DoS-атака."

      - alert: MTUProblem
        expr: rate(Icmp6InPktTooBigs[5m]) > 5 or rate(IcmpInDestUnreachs{icmp_code="4"}[5m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "PMTUD проблемы на {{ $labels.instance }}"
          description: "Частые ICMP Packet Too Big / Fragmentation Needed."

      - alert: RoutingLoop
        expr: rate(IcmpInTimeExcds[5m]) > 20
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Возможная петля маршрутизации на {{ $labels.instance }}"
          description: "Более 20 ICMP Time Exceeded/сек."
```

### 3. Zabbix ICMP checks

Zabbix имеет встроенный Simple Check типа `icmpping`.

```bash
# Через Zabbix Agent (active/passive):
# Ключ: icmpping[<target>,<packets>,<interval>,<size>,<timeout>]

icmpping[10.0.0.10,4,1,56,5]   # 4 пакета, интервал 1с, размер 56б, таймаут 5с
icmpping6[2001:db8::1,4,1,56,5] # Аналогично для IPv6
```

**Preprocessing для деталей:**

```bash
# Если нужен не просто up/down, а RTT:
# Используйте system.run или внешний скрипт:
ping -c 1 -W 2 10.0.0.10 | awk -F'time=' '/time=/ {print $2}' | awk '{print $1}'
```

**Zabbix Agent конфиг для ICMP:**

```ini
# /etc/zabbix/zabbix_agentd.conf
# Встроенный модуль icmpping доступен без дополнительных параметров.
# Для IPv6 убедитесь, что агент скомпилирован с поддержкой IPv6.
```

### 4. Grafana дашборд для ICMP

**Панель: ICMP метрики ядра**

```json
{
  "title": "ICMP InMsgs / InErrors",
  "targets": [
    {
      "expr": "rate(IcmpInMsgs[1m])",
      "legendFormat": "InMsgs {{instance}}"
    },
    {
      "expr": "rate(IcmpInErrors[1m])",
      "legendFormat": "InErrors {{instance}}"
    }
  ],
  "type": "graph"
}
```

**Панель: Blackbox probe_success**

```json
{
  "title": "ICMP Availability",
  "targets": [
    {
      "expr": "probe_success{job=\"blackbox-icmp\"}",
      "legendFormat": "{{instance}}"
    }
  ],
  "type": "stat",
  "options": {
    "reduceOptions": {
      "values": false,
      "calcs": ["lastNotNull"]
    }
  }
}
```

**Панель: ICMP RTT (Blackbox)**

```json
{
  "title": "ICMP RTT (ms)",
  "targets": [
    {
      "expr": "probe_duration_seconds{job=\"blackbox-icmp\"} * 1000",
      "legendFormat": "{{instance}}"
    }
  ],
  "unit": "ms",
  "type": "graph"
}
```

### 5. Мониторинг через node_exporter textfile collector

Если Blackbox Exporter не используется, можно экспортировать ICMP-статистику через node_exporter textfile collector:

```bash
#!/bin/bash
# /usr/local/bin/icmp_stats.sh
ICMP=$(cat /proc/net/snmp | grep -A1 '^Icmp:' | tail -1)
ICMP6=$(cat /proc/net/snmp6 | grep '^Icmp6' | head -1)

cat <<EOF > /var/lib/node_exporter/icmp.prom
# HELP icmp_in_msgs_total Total ICMP messages received
# TYPE icmp_in_msgs_total counter
icmp_in_msgs_total ${ICMP%% *}
# HELP icmp_in_errors_total ICMP errors received
# TYPE icmp_in_errors_total counter
icmp_in_errors_total $(echo $ICMP | awk '{print $2}')
# HELP icmp_in_dest_unreachs_total Destination Unreachable received
# TYPE icmp_in_dest_unreachs_total counter
icmp_in_dest_unreachs_total $(echo $ICMP | awk '{print $5}')
# HELP icmp_in_time_excds_total Time Exceeded received
# TYPE icmp_in_time_excds_total counter
icmp_in_time_excds_total $(echo $ICMP | awk '{print $6}')
EOF
```

### 6. Корреляция ICMP с TCP retransmits

Одни RTT/jitter недостаточно. В продакшене важно коррелировать ICMP-метрики с TCP retransmits:

```bash
# TCP retransmits через nstat:
nstat -az | grep TcpRetransSegs

# Correlate с ping:
mtr -rwc 100 10.0.0.10 > /tmp/mtr_report.txt

# Если RTT/RMS стабилен, а TcpRetransSegs растет — проблема в middlebox (NLB, firewall state timeout)
```

**Alerting правило:**

```yaml
- alert: PacketLossWithTCPRetrans
  expr: probe_duration_seconds{job="blackbox-icmp"} > 0.2 and rate(TcpRetransSegs[5m]) > 100
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Высокий RTT + TCP retransmits на {{ $labels.instance }}"
    description: "Возможна проблема с middlebox или деградация канала."
```

## Дополнительная информация

*   **[Blackbox Exporter — обзор](../../../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — архитектура probe-мониторинга.
*   **[Blackbox Exporter — установка](../../../Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md)** — развертывание.
*   **[Blackbox Exporter — метрики и алертинг](../../../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md)** — детальный разбор метрик.
*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — firewall-правила для ICMP-мониторинга.
*   **[traceroute и mtr](../../../Linux/Diagnostics/Networking/traceroute_mtr.md)** — инструменты трассировки.
*   **[nstat](../../../Linux/Diagnostics/Networking/nstat.md)** — сбор kernel-счетчиков.
