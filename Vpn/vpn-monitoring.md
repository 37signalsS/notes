# VPN: мониторинг, метрики и алертинг

## Определения

**Whitebox-мониторинг** — метрики «изнутри»: состояние интерфейса, свежесть handshake, объём переданных данных (источник — `wg show`/`wg stats`). **Blackbox-мониторинг** — проверки «снаружи»: ICMP/TCP/DNS-пробы до Endpoint/VIP (источник — Prometheus Blackbox Exporter). **SLI (Service Level Indicator)** — измеримая величина надёжности (доступность, latency). **SLO (Service Level Objective)** — целевой порог на SLI + budget ошибок.

## Основные концепции

### Что мониторить у VPN-сервиса

| Группа | Что | Источник метрики |
|--------|-----|------------------|
| Состояние сервиса | интерфейс поднят, процесс/`systemd` active | `wg show`, systemd, node_exporter |
| Свежесть соединения | возраст последнего handshake по каждому пиру | `wg show wg0 latest-handshakes` |
| Трафик | rx/tx байты на пир и на интерфейс | `wg show wg0 transfer`, `ip -s link` |
| Доступность «снаружи» | Endpoint/VIP отвечает, DNS внутренний снаружи доступен | Blackbox (icmp/tcp/dns) |
| HA-состояние | держатель VIP, keepalived MASTER/BACKUP | keepalived notify, textfile |
| Ошибки | dropped/errors на wg0, переполнение qdisc | `ip -s link`, `tc -s qdisc` |
| Оборудование | network error rate на физическом NIC | node_exporter `node_network_*` |

### Подходы к сбору

1. **node_exporter textfile collector** — дешёвый способ отдавать метрики из `wg show` в Prometheus (нет лишнего процесса). Каталог `collector.textfile.directory`, метрики записываются в `.prom` файл.
2. **Чистый exporter** — отдельный HTTP-экспортер (пример самописного скрипта — в [Vpn/wireguard.md](./wireguard.md)). Готовых «голых» экспортеров в ядре нет; для IPsec/OpenVPN — SNMP/текстфил аналогично.
3. **Blackbox Exporter** — end-to-end проверки: [обзор](../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md), [конфигурация модулей](../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md).
4. **Zabbix** — сбор через userparameter/`system.run` (см. раздел 4).

### SLI/SLO для VPN

Для практики достаточно трёх SLI:
- **availability** — доля успешных проб до Endpoint;
- **handshake freshness** — доля пиров с handshake моложе порога;
- **latency** — RTT до концентратора через туннель.

SLO настраивается как записи Prometheus + budget ошибок (общая теория — [SRE: SLI/SLO/SLA](../Concepts/sre_concepts_main.md)).

## Практические сценарии

### 1. Метрики WireGuard через textfile collector (node_exporter)

**Скрипт** `/usr/local/bin/wg_textfile.sh` (запуск по cron каждые 60 c):

```bash
#!/bin/bash
IFACE=wg0
DIR=/var/lib/node_exporter/textfile
mkdir -p "$DIR"
TMP="$DIR/wireguard.prom.$$"
wg show "$IFACE" dump | awk -v t="$(date +%s)" '
    $1 == "interface" { next }
    {
        peer=$1; handshake=$5; rx=$6; tx=$7
        printf "wireguard_peer_latest_handshake{peer=\"%s\"} %d\n", peer, handshake
        printf "wireguard_peer_handshake_age_seconds{peer=\"%s\"} %d\n", peer, (t - handshake)
        printf "wireguard_peer_rx_bytes{peer=\"%s\"} %d\n", peer, rx
        printf "wireguard_peer_tx_bytes{peer=\"%s\"} %d\n", peer, tx
    }'
mv "$TMP" "$DIR/wireguard.prom"
```

**в crontab** (node_exporter запущен с `--collector.textfile.directory=/var/lib/node_exporter/textfile`):

```cron
* * * * * /usr/local/bin/wg_textfile.sh
```

**Проверка:**

```bash
systemctl restart node_exporter
curl -s localhost:9100/metrics | grep wireguard_peer
# → wireguard_peer_latest_handshake{peer="..."} 1712345678
```

Такой же приём используется для Proxmox VPN (см. [Proxmox: мониторинг VPN](../Proxmox/proxmox_vpn_tunnels.md)).

### 2. Blackbox Exporter: пробы до Endpoint и DNS

**Модуль** `/etc/blackbox_exporter/blackbox.yml` (запись короче существующего SSoT):

```yaml
modules:
  vpn_icmp:
    prober: icmp
  vpn_tcp:
    prober: tcp
    timeout: 5s
    tcp:
      query_response:
        - expect: "^SSH-2.0"
```

**Scrape-конфиг** в Prometheus — проверяем VIP/Endpoint (ICMP), а OpenVPN TCP 443 (TCP), внешний DNS снаружи (убеждаемся, что DNS через VPN не утекает). Полная конфигурация модулей — [Blackbox modules](../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md).

### 3. Правила алертинга (Prometheus)

`/etc/prometheus/vpn_alerts.yml`:

```yaml
groups:
  - name: vpn
    rules:
      - alert: WGPeerHandshakeStale
        expr: wireguard_peer_handshake_age_seconds > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Пир {{ $labels.peer }} не обновлял handshake >5 минут"

      - alert: WGEndpointDown
        expr: probe_success{job="vpn-icmp"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "VPN Endpoint недоступен"

      - alert: WGInterfaceDown
        expr: node_interface_up{device="wg0"} == 0
        labels:
          severity: critical
```

Доставка алертов в мессенджеры — [Alertmanager](../Prometheus/alertmanager.md); готовые шаблоны и интерпретация blackbox-метрик — [Blackbox metrics and alerting](../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md).

### 4. Сбор в Zabbix (system.run/userparameter)

```text
# UserParameter=wg.latency,ping -c1 -W1 10.0.0.1 | grep -oP 'time=\K[0-9.]+'
# UserParameter=wg.handshake_ok,/usr/local/bin/wg_ok.sh
```

Базовые понятия и установка агента — [Zabbix: концепции](../Zabbix/definitions_and_concepts.md), [Zabbix: установка](../Zabbix/installation.md).

### 5. SLI/SLO для VPN (записи Prometheus)

```yaml
groups:
  - name: vpn_sli
    rules:
      - record: job:vpn_availability:ratio
        expr: sum(probe_success{job="vpn-icmp"})
              / count(probe_success{job="vpn-icmp"})

      - record: job:vpn_slo:ratio
        expr: (1 - 0.005) # 99.5% SLO → budget 0.5%, алертить при превышении
```

Порог и бюджетирование — на базе [SRE: SLI/SLO](../Concepts/sre_concepts_main.md).

### 6. Grafana-дашборд: что показывать инженеру

Для быстрой диагностики «плохо или нет» достаточно 4-6 панелей на источник метрик:

| Панель | Метрика | Тип панели |
|--------|---------|------------|
| Время до последнего handshake (top-пиры) | `wireguard_peer_handshake_age_seconds` | Time series / Stat |
| Количество активных пиров | `count(wireguard_peer_latest_handshake > 0)` | Stat |
| Rx/Tx по всем пирам | `sum by (peer) (rate(wireguard_peer_rx_bytes[5m]))` | Time series / Bar gauge |
| Доступность Endpoint | `probe_success` (icmp/tcp) | Stat (red/green) |
| RTT до концентратора | `probe_duration_seconds` | Time series |
| Свежесть VIP (HA) | textfile `keepalived_state{state="MASTER"} 1` | Stat |

Готовые дашборд-панели, экспорт через JSON и шаблоны для Prometheus-стека — в [Grafana: дашборды](../Grafana/grafana-dashboards.md) и [обзор Grafana](../Grafana/grafana_overview.md). Панель «Возраст handshake» — первое, что смотрит on-call инженер при тикете «не работает VPN»: она сразу отличает «клиент не подключается» от «интерфейс упал».

### 7. Canary-проверка через туннель (end-to-end)

Черный бокс через blackbox говорит, что порт открыт, но не что **сервис внутри VPN** работает. Добавьте «canary» — постоянную сквозную проверку трафика через туннель:

```bash
# Node 1 — canary-пир: каждые 2 мин проверяет ресурс внутри VPN снаружи
curl -fsS --max-time 5 http://metrics.internal:9090/-/healthy && \
  echo "OK  now=$(date -u +%s)" >> /var/log/vpn-canary.log

# или проще — стабильный iperf3/HTTP-проба внутри туннеля
curl -fsS --max-time 10 -o /dev/null -w "%{http_code} %{time_total}\n" \
  http://10.0.0.1:9100/metrics
```

Статус через textfile-коллектор в Prometheus (метрика `vpn_canary_ok 1|0`), алерт `VpnCanaryFailed` при 3 подряд неудачах. Это закрывает дыру «порты живые, но содержимое туннеля битое» (сломанный MTU, сбой маршрутизации, разъехавшиеся ключи — кейсы из [wireguard-performance.md](./wireguard-performance.md) и [wireguard-routing.md](./wireguard-routing.md)).

### 8. Runbook инцидентов (что делать при алерте)

К каждой алертной записи привяжите runbook:

| Инцидент | Первичная диагностика | Действия |
|----------|------------------------|----------|
| `WGPeerHandshakeStale` | свежа ли запись в textfile; `wg show` на шлюзе | проверить клиент: ключ не отозван (инвентарь [key-management](./wireguard-key-management.md)), сеть клиента не блокирует UDP |
| `WGEndpointDown` | RIP VIP / other-узел (HA) | фейловер-действия [wireguard-ha.md](./wireguard-ha.md); если VIP на месте — смотреть чёрный ICMP/TCP |
| `WGInterfaceDown` | `systemctl status wg-quick@wg0` | переподнять конфиг, проверить слушающий порт |
| `VpnCanaryFailed` | `ip route get` до ресурса, канал через туннель | MTU/MSS (см. §2 в [wireguard-performance](./wireguard-performance.md)), маршрутизация, ключи |

Runbook-стиль (формат, эскалация, Pager) — [SRE: SLI/SLO/SLA и практика](../Concepts/sre_concepts_main.md); журнал событий входа/выхода — в [vpn-session-audit.md](./vpn-session-audit.md).

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — команды диагностики `wg show`, самописный exporter
- **[Blackbox Exporter — обзор](../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — whitebox vs blackbox, размещение, безопасность
- **[Vpn/wireguard-ha.md](./wireguard-ha.md)** — алерты по HA (VIP, keepalived) как часть мониторинга концентратора
- **[Grafana: дашборды](../Grafana/grafana_overview.md)** — сборка панелей для WireGuard и слой Prometheus
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журнал подключений для разбора инцидентов входа