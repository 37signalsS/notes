# VPN: мониторинг, метрики и алертинг

**Актуально для:** WireGuard (wireguard-tools 1.0.x) / Prometheus 3.13.x (LTS) / 3.15.x, node_exporter 1.12.x, blackbox_exporter 0.29.x, Zabbix 7.0 LTS

## Определения

**Whitebox-мониторинг** — метрики «изнутри»: состояние интерфейса, свежесть handshake, объём переданных данных (источник — `wg show` / `wg show ... dump`). **Blackbox-мониторинг** — проверки «снаружи»: ICMP/TCP/DNS-пробы до Endpoint/VIP (источник — Prometheus Blackbox Exporter). **SLI (Service Level Indicator)** — измеримая величина надёжности (доступность, latency). **SLO (Service Level Objective)** — целевой порог на SLI + budget ошибок. **Canary-проверка** — постоянная сквозная проба реального пользовательского пути (через туннель), а не только его портов. **Burn rate** — скорость сжигания бюджета ошибок SLO (теория и multi-window алерты — [Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)).

## Основные концепции

### Что мониторить у VPN-сервиса

| Группа | Что | Источник метрики |
|--------|-----|------------------|
| Состояние сервиса | интерфейс поднят, процесс/`systemd` active | `wg show`, `node_systemd_unit_state` (нужен `--collector.systemd`), node_exporter |
| Свежесть соединения | возраст последнего handshake по каждому пиру | `wg show wg0 latest-handshakes` |
| Трафик | rx/tx байты на пир и на интерфейс | `wg show wg0 transfer`, `ip -s link` |
| Доступность «снаружи» | Endpoint/VIP отвечает, DNS внутренний снаружи доступен | Blackbox (icmp/tcp/dns) |
| HA-состояние | держатель VIP, keepalived MASTER/BACKUP | keepalived notify, textfile |
| Ошибки | dropped/errors на wg0, переполнение qdisc | `ip -s link`, `tc -s qdisc` |
| Оборудование | network error rate на физическом NIC | node_exporter `node_network_*` |

### Подходы к сбору

1. **node_exporter textfile collector** — дешёвый способ отдавать метрики из `wg show` в Prometheus (нет лишнего процесса). Каталог `collector.textfile.directory`, метрики записываются в `.prom` файл; механика (systemd timer вместо cron, атомарная замена файла) — [Textfile Collector](../Prometheus/Exporters/extensibility/textfile_collector.md).
2. **Чистый exporter** — отдельный HTTP-экспортер (пример самописного скрипта — в [Vpn/wireguard.md](./wireguard.md)). В составе node_exporter готового WireGuard-коллектора нет; из сообщества работает [MindFlavor/prometheus_wireguard_exporter](https://github.com/MindFlavor/prometheus_wireguard_exporter) (Rust, порт 9586, поддерживает friendly-имена пиров вместо base64-ключей и метрику `wireguard_latest_handshake_delay_seconds`). Для IPsec/OpenVPN — SNMP/текстфил аналогично.
3. **Blackbox Exporter** — end-to-end проверки: [обзор](../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md), [конфигурация модулей](../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md).
4. **Zabbix** — сбор через userparameter/`system.run` (см. раздел 5).

### Ограничение blackbox-проб для WireGuard

WireGuard по дизайну не отвечает на неаутентифицированные пакеты: сервер «молчит и невидим» для неавторизованного клиента (см. [модель протокола](https://www.wireguard.com/protocol/) — отсутствие ответа как защита от DoS). Практические следствия:

- **UDP-проба blackbox бесполезна для самого туннеля:** невалидный handshake-пакет будет молча отброшен, и живой сервер неотличим от закрытого порта — одинаковый «нет ответа» в обоих случаях. Не стройте `WGEndpointDown` на `probe_udp` по 51820.
- **Доступность узла** проверяйте ICMP-пробой до VIP (ядро отвечает на ICMP, даже когда туннель не поднят — это проверка хоста, а не туннеля).
- **Работоспособность содержимого туннеля** — только сквозной canary-запрос через туннель (сценарий 8): он как раз ловит случаи, когда порт открыт, а туннель битый (MTU, маршруты, ключи).
- TCP-пробы применимы к сервисам на том же шлюзе (SSH, HTTP-панели), а не к UDP 51820.

### SLI/SLO для VPN

Для практики достаточно трёх SLI:
- **availability** — доля успешных проб до Endpoint;
- **handshake freshness** — доля пиров с handshake моложе порога;
- **latency** — RTT до концентратора через туннель.

SLO настраивается как записи Prometheus + budget ошибок (общая теория — [SRE: SLI/SLO/SLA](../Concepts/sre_concepts_main.md)).

## Практические сценарии

### 1. Метрики WireGuard через textfile collector (node_exporter)

**Предварительные условия:**
- node_exporter запущен с `--collector.textfile.directory=/var/lib/node_exporter/textfile` (настройка и альтернатива в виде systemd timer — [Textfile Collector](../Prometheus/Exporters/extensibility/textfile_collector.md)).
- Скрипт выполняется от root (или с `CAP_NET_ADMIN`): `wg show` требует прав на netlink-интерфейс. node_exporter должен иметь право читать каталог — он запускается под своей учётной записью.
- Интерфейс называется `wg0`; для нескольких интерфейсов вызывайте скрипт по одному на интерфейс или переходите на `wg show all dump` (тогда первое поле каждой строки — имя устройства, и парсер надо адаптировать).

**Скрипт** `/usr/local/bin/wg_textfile.sh` (запуск по cron каждые 60 c):

```bash
#!/bin/bash
IFACE=wg0
DIR=/var/lib/node_exporter/textfile
mkdir -p "$DIR"
TMP="$DIR/wireguard.prom.$$"

# dump: 1-я строка — ключи интерфейса (private-key, public-key, listen-port, fwmark),
# далее по строке на пир: public-key, preshared-key, endpoint, allowed-ips,
# latest-handshake, transfer-rx, transfer-tx, persistent-keepalive.
if DUMP="$(wg show "$IFACE" dump 2>/dev/null)"; then
    UP=1
else
    UP=0
    DUMP=""
fi

{
    # Печатаем статус интерфейса отдельной метрикой: node_network_up{device="wg0"}
    # бесполезна — у L3-интерфейсов operstate = unknown, метрика всегда 0.
    echo "wireguard_interface_up{interface=\"$IFACE\"} $UP"
    # NR==1 пропускаем обязательно: иначе приватный ключ интерфейса станет
    # значением лейбла peer и утечёт в /metrics.
    printf '%s\n' "$DUMP" | awk -v t="$(date +%s)" '
        NR == 1 { next }
        {
            peer=$1; handshake=$5; rx=$6; tx=$7
            printf "wireguard_peer_latest_handshake{peer=\"%s\"} %d\n", peer, handshake
            # handshake = 0 (пир ни разу не подключался): возраст не выводим,
            # иначе age = "текущее время" даёт ложные срабатывания алертов
            if (handshake > 0)
                printf "wireguard_peer_handshake_age_seconds{peer=\"%s\"} %d\n", peer, (t - handshake)
            printf "wireguard_peer_rx_bytes{peer=\"%s\"} %d\n", peer, rx
            printf "wireguard_peer_tx_bytes{peer=\"%s\"} %d\n", peer, tx
        }'
} > "$TMP"
mv "$TMP" "$DIR/wireguard.prom"
```

**в crontab** (запуск от root по умолчанию):

```cron
* * * * * /usr/local/bin/wg_textfile.sh
```

Аналогичный же результат даёт systemd timer — пример unit'ов в [Textfile Collector](../Prometheus/Exporters/extensibility/textfile_collector.md).

**Проверка:**

```bash
systemctl restart node_exporter
curl -s localhost:9100/metrics | grep wireguard_
# → wireguard_interface_up{interface="wg0"} 1
# → wireguard_peer_latest_handshake{peer="..."} 1712345678
# → wireguard_peer_handshake_age_seconds{peer="..."} 42
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

**Scrape-конфиг** в Prometheus — проверяем VIP/Endpoint ICMP-пробой (модуль выше), а TCP-пробой — SSH на самом шлюзе (модуль ожидает баннер `SSH-2.0`, то есть проверяет, что хост и firewall живы). UDP-проба по 51820 не используется: WireGuard не отвечает на неаутентифицированные пакеты (см. «Ограничение blackbox-проб» выше).

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: vpn-icmp          # имя job фигурирует в алертах ниже (probe_success{job="vpn-icmp"})
    metrics_path: /probe
    params:
      module: [vpn_icmp]
    static_configs:
      - targets:
        - 203.0.113.50          # VIP концентратора
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

Проверка вручную, до Prometheus:

```bash
curl -s "http://localhost:9115/probe?target=203.0.113.50&module=vpn_icmp" | grep '^probe_success'
# → probe_success 1
```

Полная конфигурация модулей (в т.ч. DNS-пробы: проверяем, что внутренний DNS не утекает мимо туннеля) — [Blackbox modules](../Prometheus/Exporters/blackbox/blackbox_exporter_modules_configuration.md).

### 3. Метрики HA-пары (keepalived) через textfile

Для Active/Passive концентратора (см. [wireguard-ha.md](./wireguard-ha.md)) нужно видеть, кто из узлов держит VIP. Простейший источник — сам keepalived: его notify-хуки уже вызываются при каждой смене состояния, поэтому метрика всегда отражает текущую роль узла.

```bash
#!/bin/bash
# /usr/local/bin/keepalived_metric.sh <STATE>
# Подключается в keepalived.conf:
#   notify_master "/usr/local/bin/keepalived_metric.sh MASTER"
#   notify_backup "/usr/local/bin/keepalived_metric.sh BACKUP"
#   notify_fault  "/usr/local/bin/keepalived_metric.sh FAULT"
DIR=/var/lib/node_exporter/textfile
STATE="${1:-UNKNOWN}"
TMP="$DIR/keepalived.prom.$$"
{
    for s in MASTER BACKUP FAULT; do
        v=0; [ "$s" = "$STATE" ] && v=1
        echo "keepalived_state{state=\"$s\"} $v"
    done
} > "$TMP"
mv "$TMP" "$DIR/keepalived.prom"
```

Ровно одна из трёх серий равна 1 на каждом узле. Важное ограничение: метрика отражает состояние **только того узла, на котором снята**, поэтому «никто в паре не держит VIP» она не покажет (на резервном узле `state="MASTER"` равно 0 законно). Внешнее отсутствие VIP ловит ICMP-проба до адреса VIP (сценарий 2): `probe_success{job="vpn-icmp"} == 0` — это и есть глобальный детектор «VIP ни у кого». Логика выборов, GARP и nopreempt — в [wireguard-ha.md](./wireguard-ha.md).

Проверка:

```bash
cat /var/lib/node_exporter/textfile/keepalived.prom
# → keepalived_state{state="MASTER"} 1
# → keepalived_state{state="BACKUP"} 0
# → keepalived_state{state="FAULT"} 0
```

### 4. Правила алертинга (Prometheus)

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
        expr: wireguard_interface_up == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Интерфейс wg0 упал на {{ $labels.instance }}"

      - alert: WGPeerNeverHandshaked
        expr: wireguard_peer_latest_handshake == 0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Пир {{ $labels.peer }} ни разу не подключался"

      - alert: WGKeepalivedFault
        expr: keepalived_state{state="FAULT"} == 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Узел {{ $labels.instance }} переведён keepalived в FAULT"
```

Пояснения к правилам:

- `WGPeerHandshakeStale` срабатывает только по пирам, у которых age вообще экспортируется, — то есть уже подключавшимся ранее. Никогда не подключавшийся пир (age отсутствует) ловится отдельным `WGPeerNeverHandshaked` — это ошибка выдачи конфига или ключа, а не сетевой сбой.
- `WGInterfaceDown` опирается на `wireguard_interface_up` из своего скрипта, а не на `node_network_up`: у L3-интерфейсов `operstate = unknown`, и `node_network_up{device="wg0"}` там всегда 0 (та же ловушка описана для VTI/xfrm в [node_exporter](https://github.com/prometheus/node_exporter/blob/master/collector/netclass_linux.go) — метрика равна 1 только при `operstate == "up"`).
- `WGKeepalivedFault` — сигнал «узел сам себя выключил из выборов»; отсутствие VIP в паре целиком ловит `WGEndpointDown` (ICMP до VIP).

Синтаксис правил проверяйте до перезагрузки Prometheus:

```bash
promtool check rules /etc/prometheus/vpn_alerts.yml
# → SUCCESS: 5 rules found
```

Доставка алертов в мессенджеры — [Alertmanager](../Prometheus/alertmanager.md); готовые шаблоны и интерпретация blackbox-метрик — [Blackbox metrics and alerting](../Prometheus/Exporters/blackbox/blackbox_exporter_metrics_and_alerting.md). Методика подавления alert storm и multi-window burn-rate — [Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).

### 5. Сбор в Zabbix (system.run/userparameter)

```text
# UserParameter=wg.latency,ping -c1 -W1 10.0.0.1 | grep -oP 'time=\K[0-9.]+'
# UserParameter=wg.handshake_age_max,wg show wg0 latest-handshakes | awk -v t="$(date +%s)" '{if($2>0 && t-$2>m) m=t-$2} END{print m+0}'
```

Первый вернёт RTT до концентратора, второй — возраст самого «старого» handshake среди подключённых пиров (аналог `max(wireguard_peer_handshake_age_seconds)` для Prometheus). Триггер — `> 300` с задержкой 5m. Агент должен иметь право выполнять `wg show` (запуск от root или правило sudo) — как и в textfile-сценарии. Базовые понятия и установка агента — [Zabbix: концепции](../Zabbix/definitions_and_concepts.md), [Zabbix: установка](../Zabbix/installation.md).

### 6. SLI/SLO для VPN (записи Prometheus)

```yaml
groups:
  - name: vpn_sli
    rules:
      # Доля успешных ICMP-проб до VIP — основной SLI доступности
      - record: job:vpn_availability:ratio
        expr: sum(probe_success{job="vpn-icmp"})
              / count(probe_success{job="vpn-icmp"})

      # Доля пиров со свежим handshake (< 5 мин) от всех настроенных пиров.
      # Пиры, ни разу не подключавшиеся, в знаменателе есть, в числителе нет —
      # ошибка выдачи конфига сразу «просаживает» SLI.
      - record: job:vpn_handshake_fresh:ratio
        expr: count(wireguard_peer_handshake_age_seconds < 300)
              / count(wireguard_peer_latest_handshake)

      # Целевой SLO 99.5% как константа — удобно сравнивать с фактическим SLI
      - record: job:vpn_availability:slo
        expr: vector(0.995)
```

Пример алерта на скорость сжигания бюджета ошибок (SLO 99.5% → бюджет ошибок 0.5%; fast burn 1h):

```yaml
      - alert: VpnAvailabilityBudgetBurnFast
        expr: (1 - avg_over_time(job:vpn_availability:ratio[1h])) / 0.005 > 14.4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "VPN сжигает бюджет ошибок быстрее порога (1h window, 14.4x)"
```

Множитель 14.4 и multi-window схема (5m + 1h, 30m + 6h) — стандартный подход из [Рекомендаций по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md); пороги и бюджетирование — на базе [SRE: SLI/SLO](../Concepts/sre_concepts_main.md).

### 7. Grafana-дашборд: что показывать инженеру

Для быстрой диагностики «плохо или нет» достаточно 4-6 панелей на источник метрик:

| Панель | Метрика | Тип панели |
|--------|---------|------------|
| Время до последнего handshake (top-пиры) | `wireguard_peer_handshake_age_seconds` | Time series / Stat |
| Количество активных пиров | `count(wireguard_peer_latest_handshake > 0)` | Stat |
| Rx/Tx по всем пирам | `sum by (peer) (rate(wireguard_peer_rx_bytes[5m]))` | Time series / Bar gauge |
| Доступность Endpoint | `probe_success` (icmp/tcp) | Stat (red/green) |
| RTT до концентратора | `probe_duration_seconds` | Time series |
| Свежесть VIP (HA) | textfile `max(keepalived_state{state="MASTER"})` | Stat (1 = VIP у кого-то есть) |
| Canary внутри туннеля | `vpn_canary_ok` | Stat (red/green) |

Готовые дашборд-панели, экспорт через JSON и шаблоны для Prometheus-стека — в [Grafana: дашборды](../Grafana/grafana-dashboards.md) и [обзор Grafana](../Grafana/grafana_overview.md). Панель «Возраст handshake» — первое, что смотрит on-call инженер при тикете «не работает VPN»: она сразу отличает «клиент не подключается» от «интерфейс упал».

### 8. Canary-проверка через туннель (end-to-end)

Черный бокс через blackbox говорит, что порт открыт, но не что **сервис внутри VPN** работает. Добавьте «canary» — постоянную сквозную проверку трафика через туннель: отдельный узел-пир дёргает ресурс, доступный только через VPN, и публикует результат в textfile-коллектор.

```bash
#!/bin/bash
# /usr/local/bin/wg_canary.sh — запуск на отдельном «canary»-узле-пире
# (там же должен работать node_exporter с --collector.textfile.directory)
DIR=/var/lib/node_exporter/textfile
TARGET="http://10.0.0.1:9100/metrics"   # ресурс за концентратором, достижимый ТОЛЬКО через туннель
TMP="$DIR/vpn_canary.prom.$$"
if OUT=$(curl -fsS --max-time 10 -o /dev/null -w "%{time_total}" "$TARGET"); then
    OK=1; LAT="$OUT"
else
    OK=0; LAT="NaN"   # NaN — валидный литерал в формате экспозиции Prometheus
fi
{
    echo "vpn_canary_ok $OK"
    echo "vpn_canary_latency_seconds $LAT"
} > "$TMP"
mv "$TMP" "$DIR/vpn_canary.prom"
```

```cron
*/2 * * * * /usr/local/bin/wg_canary.sh
```

Алерт по трём подряд неудачам (интервал 2 мин, окно 5 мин):

```yaml
      - alert: VpnCanaryFailed
        expr: vpn_canary_ok == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Canary через туннель не проходит: содержимое VPN недоступно"
```

Это закрывает дыру «порты живые, но содержимое туннеля битое» (сломанный MTU, сбой маршрутизации, разъехавшиеся ключи — кейсы из [wireguard-performance.md](./wireguard-performance.md) и [wireguard-routing.md](./wireguard-routing.md)). Важно: canary-узел сам зависит от туннеля, поэтому его провал можно спутать с падением всего VPN — при разборе сопоставляйте `VpnCanaryFailed` с `WGPeerHandshakeStale` на том же пире (см. runbook ниже).

### 9. Runbook инцидентов (что делать при алерте)

К каждой алертной записи привяжите runbook:

| Инцидент | Первичная диагностика | Действия |
|----------|------------------------|----------|
| `WGPeerHandshakeStale` | свежа ли запись в textfile; `wg show` на шлюзе | проверить клиент: ключ не отозван (инвентарь [key-management](./wireguard-key-management.md)), сеть клиента не блокирует UDP |
| `WGPeerNeverHandshaked` | `wg show wg0 dump` — есть ли пир и его endpoint | ошибка выдачи: не тот публичный ключ у клиента, не отдан PSK, клиент не развернул конфиг. Сверить с [wireguard-key-management.md](./wireguard-key-management.md) |
| `WGEndpointDown` | RIP VIP / other-узел (HA) | фейловер-действия [wireguard-ha.md](./wireguard-ha.md); если VIP на месте — смотреть чёрный ICMP/TCP |
| `WGInterfaceDown` | `systemctl status wg-quick@wg0` | переподнять конфиг, проверить слушающий порт |
| `WGKeepalivedFault` | `journalctl -u keepalived -e`, результат `check_wg.sh` | узел сам ушёл из выборов: если это ожидаемо (плановые работы) — снять алерт; иначе разобрать health-check и VIP-холдер по [wireguard-ha.md](./wireguard-ha.md) |
| `VpnCanaryFailed` | `ip route get` до ресурса, канал через туннель; `probe_success` до VIP | MTU/MSS (см. §2 в [wireguard-performance](./wireguard-performance.md)), маршрутизация, ключи; исключить падение canary-узла через `WGPeerHandshakeStale` по нему же |

Runbook-стиль (формат, эскалация, Pager) — [SRE: SLI/SLO/SLA и практика](../Concepts/sre_concepts_main.md), управление инцидентами — [Управление инцидентами](../Concepts/Observability_and_Monitoring/incident_management.md); журнал событий входа/выхода — в [vpn-session-audit.md](./vpn-session-audit.md). В аннотациях алертов указывайте `runbook_url`, чтобы дежурный попадал сразу в нужную инструкцию.

## Устранение неисправностей

| Симптом | Причина | Диагностика и решение |
|---------|---------|----------------------|
| Метрик `wireguard_*` нет в `/metrics` | textfile-коллектор не включён или указывает на другой каталог; cron-задача не отработала; node_exporter не имеет прав читать каталог | `curl -s localhost:9100/metrics \| grep wireguard_`; сверить флаг `--collector.textfile.directory`, содержимое каталога и `crontab -l`; вручную запустить скрипт и посмотреть `ls -l /var/lib/node_exporter/textfile` |
| В лейбле `peer` вместо публичного ключа мусор или ключ интерфейса | парсер не пропустил первую строку `wg show dump` (там ключи интерфейса, а не пир) | Проверить awk-правило `NR == 1 { next }`; любой посторонний лейбл смотреть как потенциальную утечку секрета |
| `WGPeerHandshakeStale` дружно горит на всех пирах | рассинхронизация часов узла (age считается как `now − latest_handshake` по локальному времени) или textfile не обновляется | Сравнить время на шлюзе и в Prometheus (`chronyc tracking`), проверить mtime `.prom`-файла |
| `WGInterfaceDown` не гаснет при живом туннеле | алерт завязан на `node_network_up`: у L3-интерфейсов `operstate = unknown`, метрика всегда 0 | Перевести алерт на `wireguard_interface_up` из своего скрипта |
| `WGPeerNeverHandshaked` на «мёртвом» пире, который не должен подключаться (резерв) | в знаменатель/алерт попали служебные пиры | Исключить их релейблом при скрейпе или вести отдельный список ожидаемых клиентов |
| Алерт срабатывает на коротком обрыве и сам гаснет | `for` меньше реального времени переподключения, или маленький `scrape_interval` | Поднять `for` (обычно ≥ 2× интервала опроса) и `scrape_interval`, а не порог |
| `probe_success{job="vpn-icmp"} == 0`, хотя VPN вручную работает | ICMP блокируется на пути exporter→VIP или проба идёт из другого сегмента | Проверить `ping`/`traceroute` с хоста exporter; при запрете ICMP — TCP-проба до сервиса на шлюзе (SSH/HTTP) |
| Zabbix item `unsupported` для `wg.*` | агент запущен не от root либо `wg` не найден (`system.run` не использует login-shell PATH) | Указать полный путь к `wg`, добавить sudo-правило для пользователя агента |

Причины именно туннельных сбоев (handshake так и не устанавливается, MTU, маршруты) разбираются по базовым чек-листам: [Vpn/wireguard.md](./wireguard.md) и [универсальный troubleshooting туннелей](../Networking/Tunnels/vpn_troubleshooting_universal.md).

## Лучшие практики

1. **Три слоя, а не один.** Whitebox (`wg show` → textfile), blackbox (ICMP/TCP до узла/VIP) и canary (сквозь туннель) закрывают разные классы отказов; порт может быть открыт при полностью разбитом туннеле.
2. **Стабильные лейблы.** В метках держите только редко меняющиеся значения (`peer` = публичный ключ, `interface`). Endpoint/публичный адрес пира в лейблы не выносите: при роуминге за NAT он меняется и порождает новые временные ряды (cardinality growth).
3. **Пороги с запасом.** У подключённого с трафиком пира рукопожатие обновляется примерно каждые `REKEY_AFTER_TIME` = 120 с (см. [wireguard.md](./wireguard.md)). Порог «стейла» в 300 с (>2×REKEY) оставляет окно без ложных срабатываний.
4. **Согласование интервалов.** Период cron/timer для сборщика должен быть не больше `scrape_interval` Prometheus, иначе метрика будет «дрожать» между двумя значениями. Типичная пара: задача каждые 60 с, `scrape_interval` 60 с.
5. **Свежий файл — атомарно.** Пишите метрики во временный файл и подменяйте через `mv` на той же ФС (см. [Textfile Collector](../Prometheus/Exporters/extensibility/textfile_collector.md)); полузаписанный `.prom` node_exporter прочитает как битый.
6. **Проверяйте правила до применения.** `promtool check rules` для алертов, `amtool check-config` для Alertmanager — дешевле, чем узнать о синтаксической ошибке во время инцидента.
7. **Runbook в каждой аннотации.** Алерт без `runbook_url` — это задача, а не готовность; формат и эскалация — [Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md).
8. **Следите за самой системой мониторинга.** Если Prometheus/Alertmanager недоступны, алертов не будет. Dead man's switch (`Watchdog`, регулярный heartbeat наружу) — [Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md), раздел про Watchdog.
9. **Не публикуйте экспортёры в интернет.** Метрики (`node_exporter`, `blackbox_exporter`) доступны только с collector-хоста/management-сети или через сам VPN; `/metrics` содержит публичные ключи пиров и топологию.
10. **Пороги — в recording rules.** Держите вычисления (SLI, пороги) в записях Prometheus, а дашборды и алерты — поверх записанных метрик: одна формула не расползается по десяткам панелей.

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — команды диагностики `wg show`, самописный exporter
- **[Textfile Collector](../Prometheus/Exporters/extensibility/textfile_collector.md)** — SSoT по механизму: каталог, systemd timer, атомарная запись, типовые сценарии
- **[node_exporter](../Prometheus/Exporters/node_exporter.md)** — коллекторы (`netdev`, `systemd`), флаги, отсутствие готового WireGuard-коллектора
- **[Blackbox Exporter — обзор](../Prometheus/Exporters/blackbox/blackbox_exporter_overview.md)** — whitebox vs blackbox, размещение, безопасность
- **[Рекомендации по мониторингу и алертингу](../Concepts/Observability_and_Monitoring/monitoring_alerting_recommendations.md)** — burn rate, подавление, Watchdog
- **[Vpn/wireguard-ha.md](./wireguard-ha.md)** — алерты по HA (VIP, keepalived) как часть мониторинга концентратора
- **[Grafana: дашборды](../Grafana/grafana_overview.md)** — сборка панелей для WireGuard и слой Prometheus
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журнал подключений для разбора инцидентов входа