# Мониторинг IPv6 в production

## Определения

**Мониторинг IPv6** — процесс сбора, агрегации и анализа метрик, связанных с работой стека IPv6 в Linux-системе. Включает отслеживание состояния адресации, NDP, ICMPv6, PMTUD, conntrack и маршрутизации.

**Blackbox-мониторинг** — подход проверки сетевой доступности с внешнего узла (Prometheus Blackbox Exporter). Позволяет выявлять проблемы PMTUD, NDP-блокировок и маршрутизации до того, как они повлияют на приложения.

**SNMP6 (ICMPv6 MIB)** — ядерные счетчики ICMPv6, доступные через `/proc/net/snmp6`. Содержат метрики ошибок, NDP-обмена, PMTUD и flood-атак.

## Основные концепции

### Ключевые метрики IPv6 для мониторинга

| Группа | Метрики | Источник | Зачем мониторить |
| :--- | :--- | :--- | :--- |
| **ICMPv6** | `Icmp6InMsgs`, `Icmp6InErrors`, `Icmp6InPktTooBigs` | `/proc/net/snmp6`, `nstat` | Обнаружение PMTUD Black Hole, flood-атак |
| **NDP** | `Icmp6InNeighborSolicits`, `Icmp6InNeighborAdverts` | `/proc/net/snmp6` | Стабильность обнаружения соседей |
| **Conntrack IPv6** | `nf_conntrack_count`, `nf_conntrack_max` | `/proc/sys/net/netfilter/` | Предотвращение переполнения таблицы |
| **Соседи (NDP)** | Состояния `REACHABLE`, `STALE`, `FAILED`, `INCOMPLETE` | `ip -6 neigh show` | Диагностика L2-проблем, атак NDP spoofing |
| **Маршрутизация** | Количество маршрутов, маршрут по умолчанию | `ip -6 route show` | Проверка политики маршрутизации |
| **PMTUD** | `Ip6OutTooBig` | `/proc/net/snmp6` | Выявление проблем с MTU |
| **Адреса** | Количество глобальных, link-local, temporary | `ip -6 addr show` | Мониторинг динамики адресации |

### Мониторинг через Prometheus

#### Node Exporter — текстовые файлы

Node Exporter не экспортирует IPv6-метрики напрямую. Для耪етки SNMP6-счетчиков используется текстовый collector:

```bash
# /etc/node-exporter/textfile/ipv6_metrics.prom.sh
#!/bin/bash
OUTFILE="/var/lib/node_exporter/textfile/ipv6_metrics.prom"

cat > "$OUTFILE" << EOF
# HELP node_icmp6_in_errors ICMPv6 input errors
# TYPE node_icmp6_in_errors gauge
node_icmp6_in_errors $(awk '/^Icmp6InErrors/ {print $2}' /proc/net/snmp6)

# HELP node_icmp6_in_pkt_too_big ICMPv6 Packet Too Big received
# TYPE node_icmp6_in_pkt_too_big gauge
node_icmp6_in_pkt_too_big $(awk '/^Icmp6InPktTooBigs/ {print $2}' /proc/net/snmp6)

# HELP node_icmp6_in_neighbor_solicits ICMPv6 Neighbor Solicitations received
# TYPE node_icmp6_in_neighbor_solicits gauge
node_icmp6_in_neighbor_solicits $(awk '/^Icmp6InNeighborSolicits/ {print $2}' /proc/net/snmp6)

# HELP node_icmp6_in_neighbor_adverts ICMPv6 Neighbor Advertisements received
# TYPE node_icmp6_in_neighbor_adverts gauge
node_icmp6_in_neighbor_adverts $(awk '/^Icmp6InNeighborAdverts/ {print $2}' /proc/net/snmp6)

# HELP node_icmp6_in_echo_replies ICMPv6 Echo Replies received
# TYPE node_icmp6_in_echo_replies gauge
node_icmp6_in_echo_replies $(awk '/^Icmp6InEchoReps/ {print $2}' /proc/net/snmp6)

# HELP node_ndp_entries_total NDP neighbor cache entries
# TYPE node_ndp_entries_total gauge
node_ndp_entries_total $(ip -6 neigh show | wc -l)

# HELP node_ndp_failed_entries NDP entries in FAILED state
# TYPE node_ndp_failed_entries gauge
node_ndp_failed_entries $(ip -6 neigh show nud failed | wc -l)

# HELP node_ndp_stale_entries NDP entries in STALE state
# TYPE node_ndp_stale_entries gauge
node_ndp_stale_entries $(ip -6 neigh show nud stale | wc -l)

# HELP node_ipv6_global_addresses IPv6 global unicast addresses
# TYPE node_ipv6_global_addresses gauge
node_ipv6_global_addresses $(ip -6 addr show scope global | grep -c "inet6")

# HELP node_conntrack_ipv6_count conntrack IPv6 entries
# TYPE node_conntrack_ipv6_count gauge
node_conntrack_ipv6_count $(conntrack -L -f ipv6 2>/dev/null | wc -l)

# HELP node_conntrack_ipv6_max conntrack IPv6 max entries
# TYPE node_conntrack_ipv6_max gauge
node_conntrack_ipv6_max $(sysctl -n net.netfilter.nf_conntrack_max)
EOF
```

```bash
# Crontab: каждую минуту
* * * * * /usr/local/bin/ipv6_metrics.prom.sh
```

#### Blackbox Exporter — ICMPv6 probe

```yaml
# /etc/blackbox_exporter/config.yml
modules:
  icmpv6:
    prober: icmp6
    timeout: 5s
    icmp6:
      preferred_ip_protocol: ip6

  tcp6_connect:
    prober: tcp6
    timeout: 5s

  http6_ip:
    prober: http6
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
```

**Prometheus job:**

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'blackbox_icmpv6'
    metrics_path: /probe
    params:
      module: [icmpv6]
    static_configs:
      - targets:
          - 2001:4860:4860::8888    # Google DNS IPv6
          - 2001:4860:4860::8844    # Google DNS IPv6 (alt)
          - 2606:4700:4700::1111   # Cloudflare DNS
          - fd00::1                 # Gateway (Link-Local)
        labels:
          probe_type: icmpv6
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9115
```

### Alerting-правила

```yaml
# prometheus_rules/ipv6_alerts.yml
groups:
  - name: ipv6_alerts
    rules:
      # PMTUD Black Hole: ICMPv6 Packet Too Big не приходят
      - alert: IPv6PMTUDBlackHole
        expr: |
          rate(node_icmp6_in_pkt_too_big[5m]) == 0
          and
          node_network_transmit_bytes_total{device!="lo"} > 1000000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Возможен IPv6 PMTUD Black Hole"
          description: "Нет ICMPv6 Packet Too Big при активном трафике. Проверьте файрвол."

      # NDP FAILED-состояния
      - alert: IPv6NDPFailed
        expr: node_ndp_failed_entries > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "IPv6 NDP: есть FAILED-записи"
          description: "{{ $value }} NDP-записей в состоянии FAILED на {{ $labels.instance }}"

      # Conntrack IPv6 переполняется
      - alert: IPv6ConntrackNearLimit
        expr: |
          node_conntrack_ipv6_count / node_conntrack_ipv6_max > 0.85
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "IPv6 conntrack таблица заполнена на {{ $value | humanizePercentage }}"

      # ICMPv6 InErrors растёт
      - alert: IPv6ICMPv6Errors
        expr: rate(node_icmp6_in_errors[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий уровень ICMPv6 ошибок"
          description: "{{ $value }}/s ICMPv6 ошибок на {{ $labels.instance }}"

      # SLAAC/RA не работает
      - alert: IPv6RADown
        expr: rate(node_icmp6_in_neighbor_solicits[5m]) == 0
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "IPv6 RA/NDP неактивен"
          description: "Нет NDP-трафика 15 минут. Возможно, RA отключены."
```

### Мониторинг через Grafana

**Ключевые панели для IPv6-дашборда:**

| Панель | Метрика | Тип |
| :--- | :--- | :--- |
| ICMPv6 InErrors/s | `rate(node_icmp6_in_errors[5m])` | Graph |
| ICMPv6 Packet Too Big/s | `rate(node_icmp6_in_pkt_too_big[5m])` | Graph |
| NDP FAILED-записи | `node_ndp_failed_entries` | Stat |
| NDP STALE-записи | `node_ndp_stale_entries` | Graph |
| Conntrack IPv6 utilization | `node_conntrack_ipv6_count / node_conntrack_ipv6_max` | Gauge |
| IPv6 глобальные адреса | `node_ipv6_global_addresses` | Stat |
| Blackbox ICMPv6 RTT | `probe_icmp6_time_seconds` | Graph |
| Blackbox ICMPv6 success | `probe_success{job="blackbox_icmpv6"}` | Stat |

## Практические сценарии

### 1. Быстрая проверка состояния IPv6-стека

```bash
# Проверка включенных IPv6-адресов
ip -6 addr show scope global | wc -l
# → Должно быть > 0

# Проверка маршрута по умолчанию
ip -6 route show default
# → default via ... proto ra

# Проверка NDP-таблицы
ip -6 neigh show | awk '{print $5}' | sort | uniq -c | sort -rn
# → REACHABLE 15
# → STALE 3
# → FAILED 0  ← если > 0, проблема

# Проверка conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Проверка ICMPv6-счетчиков
nstat -az | grep -E 'Icmp6In|Icmp6Out' | head -20
```

### 2. Prometheus Blackbox ICMPv6 probe (тестирование)

```bash
# Ручной тест через Blackbox Exporter
curl -s "http://localhost:9115/probe?target=2001:4860:4860::8888&module=icmpv6" | grep probe_success
# → probe_success 1

# Проверка RTT
curl -s "http://localhost:9115/probe?target=2001:4860:4860::8888&module=icmpv6" | grep probe_icmp6_time
# → probe_icmp6_time_seconds 0.012
```

### 3. Мониторинг NDP через ip monitor

```bash
# Логирование всех NDP-событий в реальном времени
ip -6 monitor neigh | tee /var/log/ipv6_ndp.log

# Статистика переходов состояний
ip -6 neigh show | awk '{print $5}' | sort | uniq -c | sort -rn
# → REACHABLE 25
# → STALE 8
# → DELAY 1
# → FAILED 0
# → INCOMPLETE 0
```

### 4. Автоматический мониторинг через systemd timer

```ini
# /etc/systemd/system/ipv6-monitor.service
[Unit]
Description=IPv6 Stack Health Check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ipv6_health_check.sh
```

```ini
# /etc/systemd/system/ipv6-monitor.timer
[Unit]
Description=Run IPv6 health check every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

```bash
#!/bin/bash
# /usr/local/bin/ipv6_health_check.sh
set -e

LOG="/var/log/ipv6_health.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 1. Проверка IPv6 forwarding
FWD=$(sysctl -n net.ipv6.conf.all.forwarding)
if [ "$FWD" != "0" ] && [ "$FWD" != "1" ]; then
    echo "$TIMESTAMP ERROR: IPv6 forwarding value unexpected: $FWD" >> "$LOG"
fi

# 2. Проверка NDP FAILED-записей
FAILED=$(ip -6 neigh show nud failed | wc -l)
if [ "$FAILED" -gt 0 ]; then
    echo "$TIMESTAMP WARNING: NDP FAILED entries: $FAILED" >> "$LOG"
    ip -6 neigh show nud failed >> "$LOG"
fi

# 3. Проверка conntrack utilization
MAX=$(sysctl -n net.netfilter.nf_conntrack_max)
COUNT=$(cat /proc/sys/net/netfilter/nf_conntrack_count)
if [ "$MAX" -gt 0 ]; then
    PCT=$((COUNT * 100 / MAX))
    if [ "$PCT" -gt 85 ]; then
        echo "$TIMESTAMP CRITICAL: conntrack at ${PCT}% ($COUNT/$MAX)" >> "$LOG"
    fi
fi

# 4. Проверка ICMPv6 InErrors
ICMP6_ERRS=$(awk '/^Icmp6InErrors/ {print $2}' /proc/net/snmp6)
if [ "$ICMP6_ERRS" -gt 0 ]; then
    echo "$TIMESTAMP WARNING: ICMPv6 InErrors: $ICMP6_ERRS" >> "$LOG"
fi

# 5. Проверка PMTUD (Packet Too Big)
PTB=$(awk '/^Icmp6InPktTooBigs/ {print $2}' /proc/net/snmp6)
if [ "$PTB" -gt 100 ]; then
    echo "$TIMESTAMP INFO: ICMPv6 Packet Too Big count: $PTB (check MTU)" >> "$LOG"
fi
```

```bash
sudo systemctl enable --now ipv6-monitor.timer
```

## Дополнительная информация

### Типичные ошибки мониторинга

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Blackbox Exporter не пингует IPv6 | Конфигурация модуля `icmp6` отсутствует | Добавить модуль `icmp6` в `config.yml` |
| Node Exporter не показывает IPv6-метрики | Нет textfile collector для SNMP6 | Настроить cron-скрипт с текстовыми метриками |
| Prometheus не скрейпит IPv6-цели | Неверный формат адреса в `static_configs` | Использовать квадратные скобки или `-` в job_name |
| Grafana не показывает ICMPv6 данные | Метрика не экспортируется | Проверить `nstat -az | grep Icmp6` |

### Best Practices

1. **Blackbox ICMPv6 probes:** Настройте проверки до ключевых IPv6-шлюзов и DNS (Google 2001:4860:4860::8888, Cloudflare 2606:4700:4700::1111).
2. **conntrack мониторинг:** Устанавливайте алерт при 85% заполнения таблицы. В IPv6 без NAT давление на conntrack ниже, но при VLAN-транкинге может быть significant.
3. **NDP FAILED-мониторинг:** Любые FAILED-записи — индикатор L2-проблем или NDP-спуфинга.
4. **PMTUD:** Мониторинг `Icmp6InPktTooBigs`. Если он == 0 при активном трафике — возможен Black Hole.
5. **Логирование NDP:** Используйте `ip -6 monitor neigh` в systemd-сервисе для записи критических событий.
6. **Prometheus labels:** Добавляйте label `stack=ipv6` для раздельного анализа IPv4/IPv6-метрик.

### См. также

- **[Диагностика IPv6](./diagnostics.md)** — инструменты поиска ошибок NDP, PMTUD.
- **[Firewall для IPv6](./firewall.md)** — мониторинг правил nftables через `-a` (counters).
- **[ICMP: Мониторинг в продакшене](../../../../Networking/Protocols/ICMP/icmp_monitoring.md)** — Blackbox Exporter, alerting-правила.
- **[Kubernetes Dual-Stack](./kubernetes_dual_stack.md)** — IPv6 в Kubernetes-кластерах.
- **[ICMPv6 счетчики](../../../../Networking/Protocols/ICMP/icmp_monitoring.md#метрики-ядра-linux-для-мониторинга)** — SNMP6 MIB.
