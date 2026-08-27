# Наблюдаемость VLAN: мониторинг и диагностика в продакшене

## Определения

**SNMP (Simple Network Management Protocol)** — протокол прикладного уровня (L7) для сбора телеметрии с сетевых устройств. Позволяет опрашивать MIB-деревья (Management Information Base), включая `dot1qVlanFdbTable`, `dot1qVlanStatistics`, `dot3Stats` для анализа VLAN-трафика.

**NetFlow / IPFIX (IP Flow Information Export)** — протокол сбора статистики о сетевых потоках. Позволяет классифицировать трафик по VLAN ID (через `vlan` match-правило), агрегировать битрейты и строить топологию трафика.

**Bridge FDB (Forwarding Database)** — таблица коммутующего устройства, сопоставляющая MAC-адреса с портами и VLAN. В Linux управляется через `bridge fdb` и `/sys/class/net/<bridge>/bridge/fdb_flush`.

**BPDU (Bridge Protocol Data Unit)** — служебные кадры STP, используемые для координации топологии. Перехват BPDU позволяет отследить аномалии STP.

> **Назначение:** Этот документ — SSoT для production-наблюдаемости VLAN. Охватывает SNMP-опрос коммутаторов, NetFlow-анализ, Linux-инструменты (tcpdump, bridge, ethtool), а также интеграцию с Prometheus и стеком Grafana.

## Базовые концепции

### Архитектура наблюдаемости VLAN

В production среде мониторинг VLAN требует трех уровней наблюдаемости:

| Уровень | Инструменты | Что измеряем |
| :--- | :--- | :--- |
| **Устройство (Device-level)** | SNMP, Telnet/SSH, Syslog | CAM/FDB table size, port errors, VLAN status |
| **Потоки (Flow-level)** | NetFlow/IPFIX/sFlow | Traffic volume per VLAN, top talkers, broadcast ratio |
| **Хост (Host-level)** | tcpdump, bridge, ethtool, ip -s | Packet drops, VLAN tag visibility, MAC flapping |

### Ключевые метрики для алертинга

| Метрика | Порог | Инструмент | Описание |
| :--- | :--- | :--- | :--- |
| **Broadcast Ratio** | >5% от throughput | NetFlow/IPFIX, sFlow | Признак broadcast storm или петли |
| **CAM Table Utilization** | >75% | SNMP (.1.3.1.1.1.1.1.1) | Риск поломки CAM и перехода в режим хаба |
| **MAC Flapping Count** | >10 moves/мин | Syslog, `bridge fdb monitor` | Возможная петля или конфликт MAC |
| **VLAN Hopping Attempts** | >0 | Syslog (DTP events), tcpdump | Атака Switch Spoofing |
| **Port VLAN Mismatch** | >0 | SNMP, `show interfaces trunk` | Native VLAN mismatch |

## Практические сценарии

### Сценарий 1: Настройка Prometheus SNMP Exporter для опроса VLAN на коммутаторах

#### Требования (Prerequisites)

| Требование | Значение |
| :--- | :--- |
| **SNMP** | v2c/v3 доступен на всех коммутаторах |
| **Prometheus** | Рабочее окружение (v2.45+) |
| **snmp_exporter** | Установлен (v0.27+) |
| **MIBы** | `SNMPv2-MIB`, `BRIDGE-MIB`, `IP-MIB`, `CISCO-VLAN-MEMBERSHIP-MIB` |

#### Конфигурация snmp_exporter

```yaml
# /etc/snmp/snmp.yml — snmp_exporter generator
modules:
  vlan_switch:
    version: 2
    auth:
      community: public
    walk:
      - 1.3.6.1.2.1.1.3        # sysUpTime
      - 1.3.6.1.2.1.2.2.1.10   # ifInOctets (интерфейсы)
      - 1.3.6.1.2.1.2.2.1.16   # ifOutOctets
      - 1.3.6.1.2.1.17.4.3.1.1 # dot1dTpFdbAddress (CAM table entries)
      - 1.3.6.1.2.1.17.4.3.1.2 # dot1dTpFdbPort (порт для MAC)
      - 1.3.6.1.2.1.17.7.1.2.2.1.2  # dot1qTpFdbTable (VLAN-aware CAM)
      - 1.3.6.1.2.1.2.2.1.14   # ifInErrors
      - 1.3.6.1.2.1.31.1.1.1.6 # ifHCInOctets (64-bit counters)
      - 1.3.6.1.2.1.31.1.1.1.10 # ifHCOutOctets
    max_repetitions: 25
    retries: 3
    timeout: 10s
```

**Параметры:**
- `max_repetitions: 25` — количество OID, возвращаемых в одном GetBulk-ответе (SNMPv2c/v3). Увеличение ускоряет обход больших таблиц (CAM/FDB), но повышает нагрузку на CPU устройства.
- `retries: 3` — количество повторных попыток при таймауте. В production рекомендуется 2–3 для баланса между надежностью и временем опроса.
- `timeout: 10s` — таймаут ожидания ответа. Для удаленных коммутаторов через WAN увеличьте до 15–30s.

#### Паттерн Multi-Target для опроса нескольких коммутаторов

SNMP Exporter использует паттерн **Multi-Target** — один экземпляр экспортера опрашивает множество коммутаторов. Prometheus передает адрес целевого устройства в параметре запроса:

```yaml
# prometheus.yml — Multi-Target паттерн
scrape_configs:
  - job_name: 'network-vlan'
    metrics_path: /snmp
    params:
      module: [vlan_switch]
    static_configs:
      - targets:
        - 192.168.1.10  # switch-access-01
        - 192.168.1.11  # switch-access-02
        - 192.168.1.20  # switch-core-01
        - 192.168.1.21  # switch-core-02
    relabel_configs:
      # Передаем IP устройства как параметр target
      - source_labels: [__address__]
        target_label: __param_target
      # Указываем порт snmp_exporter (не коммутатора!)
      - target_label: __address__
        replacement: snmp-exporter:9116
      # Сохраняем оригинальный IP как label instance
      - source_labels: [__param_target]
        target_label: instance
      # Добавляем метку с именем коммутатора
      - source_labels: [__param_target]
        regex: '(.+)'
        target_label: switch
        replacement: '${1}'
```

> **Почему Multi-Target:** SNMP Exporter — stateless. Он не хранит историю, а только транслирует SNMP-данные в формат Prometheus. Один экземпляр может обслуживать десятки коммутаторов без деградации.

#### Ожидаемый результат (Validation)

```bash
# Проверка snmp_exporter работает
curl -s http://localhost:9116/targets | grep switch

# Проверка метрик VLAN
curl -s 'http://localhost:9116/snmp?target=switch-prod-01&module=vlan_switch' | grep dot1qTpFdbTable
# → dot1qTpFdbTable{instance="switch-prod-01",vid="10"} 42
```

#### Алерты в Prometheus (Production)

```yaml
groups:
  - name: vlan_alerts
    rules:
      - alert: CAMTableHighUtilization
        expr: |
          (
            dot1qTpFdbTable{vid!=""} / 16000 * 100
          ) > 75
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "CAM table >75% on {{ $labels.instance }} (VLAN {{ $labels.vid }})"
          description: "Текущее использование: {{ $value | printf \"%.1f\" }}%"

      - alert: MACFlappingDetected
        expr: changes(switch_mac_flapping_total[2m]) > 10
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "MAC flapping detected on {{ $labels.instance }}"
          description: "Обнаружено {{ $value }} moves MAC-адреса за 2 минуты"

      - alert: BroadcastStormRisk
        expr: |
          (
            rate(snmp_ifHCOutOctets{ifType="6"}[5m]) > 0
            and
            rate(snmp_ifBroadcast{ifType="6"}[5m])
            / rate(snmp_ifHCOutOctets{ifType="6"}[5m]) > 0.05
          )
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Broadcast ratio >5% on {{ $labels.instance }}/{{ $labels.ifDescr }}"
          description: "Broadcast ratio: {{ $value | printf \"%.2f\" }}%"

      - alert: PortErrorsIncreasing
        expr: |
          rate(snmp_ifInErrors[5m]) > 0
          or rate(snmp_ifOutErrors[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Port errors on {{ $labels.instance }}/{{ $labels.ifDescr }}"
```

#### PromQL-запросы для VLAN-метрик

**Топ-10 VLAN по объему трафика:**
```promql
# Трафик по VLAN (в байтах/секунду)
topk(10,
  sum by (vid) (
    rate(snmp_dot1qVlanEgressOctets[5m])
  )
)
```

**Использование CAM-таблицы по VLAN (в процентах):**
```promql
# Процент использования CAM относительно максимального размера (16000 записей — типичный максимум для enterprise коммутаторов)
(
  dot1qTpFdbTable{vid!=""}
  /
  16000
) * 100
```

**Обнаружение MAC flapping (количество смен порта за 5 минут):**
```promql
# Количество изменений позиции MAC в FDB
changes(switch_mac_flapping_total[5m])
```

**Сравнение трафика ingress/egress по интерфейсам:**
```promql
# Отношение входящего к исходящему трафику по интерфейсам
rate(snmp_ifHCInOctets[5m]) / rate(snmp_ifHCOutOctets[5m])
```

**Broadcast ratio по интерфейсам:**
```promql
# Процент broadcast-трафика от общего
(
  rate(snmp_ifBroadcast[5m])
  /
  rate(snmp_ifHCOutOctets[5m])
) * 100
```

**Обнаружение аномалий в FDB (рост таблицы >10% за час):**
```promql
# Рост CAM-таблицы: текущее значение / значение час назад
dot1qTpFdbTable{vid!=""}
/
dot1qTpFdbTable{vid!=""} offset 1h
> 1.10
```

**Общая загрузка VLAN-интерфейсов:**
```promql
# Суммарный трафик по всем VLAN на конкретном коммутаторе
sum by (instance) (
  rate(snmp_ifHCInOctets{instance="switch-core-01"}[5m])
  +
  rate(snmp_ifHCOutOctets{instance="switch-core-01"}[5m])
)
```

### Сценарий 2: Linux-level мониторинг VLAN в реальном времени

#### Отслеживание MAC-адресов через bridge fdb

```bash
# Непрерывный просмотр FDB с фильтром по VLAN
watch -n 2 'bridge fdb show | grep "vlan 10"'

# Мониторинг в реальном времени (выводит новые записи)
bridge fdb monitor

# Проверка количества MAC-адресов в FDB (аналог CAM table size)
bridge fdb show | wc -l
```

#### Диагностика через /proc и sysfs

```bash
# Статистика VLAN-интерфейса (RX/TX пакеты, drops)
cat /proc/net/dev | grep eth0.10

# Просмотр VLAN-интерфейсов в /sys
ls /sys/class/net/eth0.10/statistics/
# → rx_packets, tx_packets, rx_dropped, tx_dropped

# Проверка hardware offloading для VLAN
ethtool -k eth0 | grep -E "vlan|ntuple"
```

#### Захват трафика с tcpdump для анализа VLAN

```bash
# Захват только tagged-трафика
sudo tcpdump -i eth0 -e -nn 'vlan'

# Фильтрация по конкретному VLAN ID
sudo tcpdump -i eth0 -e -nn 'vlan 10'

# Поиск broadcast-кадров (признак broadcast storm)
sudo timeout 60 tcpdump -i eth0 -n 'ether broadcast' -w /tmp/broadcast.pcap
mergecap /tmp/broadcast.pcap | wc -l
```

#### Ожидаемый результат (Validation)

```bash
# FDB должен показывать MAC-адреса с привязкой к VLAN
bridge fdb show dev br0 | head -5
# → 52:54:00:12:34:56 vlan 10 master br0

# Статистика: drops должны быть 0
cat /sys/class/net/eth0.10/statistics/rx_dropped
# → 0
```

#### Особые случаи (Edge Cases)

- **Hardware offload скрывает теги:** при включённом `rx-vlan-offload` `tcpdump -i eth0 -e` не показывает 802.1Q тег. Для диагностики: `sudo ethtool -K eth0 rx-vlan-offload off`.
- **MAC flapping в виртуальных средах:** при использовании VLAN-aware Bridge и VM с пересоздаваемыми интерфейсами один и тот же MAC может появляться на разных портах. Используйте `sticky MAC` или `port-security` на коммутаторе.
- **CAM table overflow в контейнерных средах:** при запуске сотен контейнеров с уникальными MAC каждый container добавляет запись в FDB. Настраивайте MAC limit: `ip link set br0 type bridge vlan_default_pvid 0`.

### Сценарий 3: NetFlow-анализ трафика по VLAN

#### Сравнение протоколов потокового мониторинга

| Протокол | Модель | Тип агрегации | Поддержка VLAN | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **NetFlow v9** | Шаблонная | На устройстве | `match vlan id` | Для сетей Cisco |
| **IPFIX (v10)** | Шаблонная | На устройстве | `match vlan id` | **Стандарт для мультибрендовых сетей** |
| **sFlow** | Сэмплирование | Без агрегации | В заголовке L2 | Для L2-коммутации и high-speed каналов |

**Ключевые отличия sFlow от NetFlow/IPFIX:**
- **sFlow** работает на уровне сэмплирования (по умолчанию 1 из 1000 пакетов), экспортируя полный заголовок пакета (L2-L4) без агрегации. Это делает его незаменимым для выявления L2-инцидентов (broadcast storms, MAC flooding), но непригодным для точного подсчета трафика по VLAN.
- **NetFlow/IPFIX** агрегирует пакеты в потоки на устройстве, значительно снижая объем экспортируемых данных (в сотни раз по сравнению с sFlow), но теряя детализацию отдельных пакетов.

#### Конфигурация на Cisco (IPFIX)

```cisco
! Экспорт трафика по VLAN с классификацией по VID
flow exporter VLAN-EXPORTER
 destination 192.168.100.10
 transport udp 2055
 export-protocol ipfix
!
flow monitor VLAN-MONITOR
 exporter VLAN-EXPORTER
 cache timeout active 60
 cache timeout inactive 15
 match vlan id
 match ipv4 source address
 match ipv4 destination address
 match transport source-port
 match transport destination-port
 collect counter bytes long
 collect counter packets long
 collect interface output
!
interface Vlan10
 ip flow monitor VLAN-MONITOR input
 ip flow monitor VLAN-MONITOR output
```

#### Конфигурация на Juniper Junos

```junos
# 1. Определение шаблона для flow monitoring
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE template-options inactive-timeout 15
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE template-options active-timeout 60
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match source-address
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match destination-address
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match protocol
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match source-port
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match destination-port
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match input-interface
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template match output-interface
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template collect bytes
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template collect packets
set services flow-monitoring NETFLOW-VLAN template template-name VLAN-TEMPLATE ipv4-template collect tcp-flags

# 2. Определение collector и exporter
set services flow-monitoring NETFLOW-VLAN collector COLLECTOR-1
set services flow-monitoring NETFLOW-VLAN collector COLLECTOR-1 address 192.168.100.10
set services flow-monitoring NETFLOW-VLAN collector COLLECTOR-1 port 2055
set services flow-monitoring NETFLOW-VLAN exporter EXPORTER-1
set services flow-monitoring NETFLOW-VLAN exporter EXPORTER-1 collector COLLECTOR-1
set services flow-monitoring NETFLOW-VLAN exporter EXPORTER-1 source-address 10.0.0.1

# 3. Применение к VLAN-интерфейсу (input sampling)
set interfaces irb unit 10 family inet sampling input
set interfaces irb unit 10 family inet input-virtual-reassembly
```

**Примечание:** На Juniper VLAN ID неявно определяется через `input-interface` (irb unit = VLAN ID). Для явного match по VLAN ID используйте `match vlan-id` в IPv4 template.

#### Конфигурация на Arista EOS

```arista
! 1. Flow Record для VLAN-трафика
flow record VlanFlowRecord
 match ipv4 source address
 match ipv4 destination address
 match ipv4 protocol
 match transport source-port
 match transport destination-port
 match vlan id
 match input interface
 match output interface
 collect counter bytes long
 collect counter packets long
 collect counter flows
 collect transport tcp flags

! 2. Flow Exporter
flow exporter VlanFlowExporter
 destination 192.168.100.10
 source Management0
 transport udp 2055
 template data timeout 60

! 3. Flow Monitor
flow monitor VlanFlowMonitor
 record VlanFlowRecord
 exporter VlanFlowExporter
 cache timeout active 60
 cache timeout inactive 15
 cache entries 500000

! 4. Применение к SVI (VLAN-интерфейсу)
interface Vlan10
 ip flow monitor VlanFlowMonitor input
 ip flow monitor VlanFlowMonitor output
```

**Особенности Arista EOS:**
- `cache entries 500000` — размер Flow Cache. Для leaf-коммутаторов в数据中心 рекомендуется не менее 256K записей.
- Arista поддерживает `sFlow` нативно через `sflow agent-id Management0` + `sflow destination 192.168.100.10:6343`.

#### Анализ в Linux (nfdump + sFlow)

```bash
# Захват NetFlow на Linux через nfdump
# (требуется flow-tools или nfdump)
nfdump -R /var/cache/nfsen/profilesData/live/ -s record/vlan -o csv
# → Выводит трафик по VLAN ID с битрейтами

# Фильтрация по конкретному VLAN
nfdump -R /var/cache/nfsen/profilesData/live/ -s record/vlan -o extended 'vlan 10'

# Альтернатива: sFlow через sflowtool
sflowtool -4 -d 6343 -e 'vlan' > /tmp/sflow_vlan.json

# Агрегация по VLAN за последний час
nfdump -R /var/cache/nfsen/profilesData/live/ -T -t 'last-1h' -s record/vlan -o extended
```

#### Ожидаемый результат (Validation)

```bash
# Топ-5 VLAN по трафику
nfdump -R /var/cache/nfsen/profilesData/live/ -s record/bytes -o extended | head -5
# → Vlan 10: 1.2 Gb/s
# → Vlan 20: 800 Mb/s

# Топ-10 источников в VLAN 10
nfdump -R /var/cache/nfsen/profilesData/live/ -s record/bytes -o extended \
  'vlan 10 and srcip 10.10.0.0/16' | head -10
```

## Дополнительная информация

### Таблица команд диагностики

| Команда | Платформа | Описание | Частота вызова |
| :--- | :--- | :--- | :--- |
| `show mac address-table` | Cisco IOS | Просмотр CAM-таблицы | При инциденте |
| `show mac address-table count` | Cisco IOS | Количество записей по VLAN | Постоянный мониторинг |
| `show mac address-table count vlan <id>` | Cisco IOS | Количество MAC в конкретной VLAN | При инциденте |
| `bridge fdb show` | Linux | Просмотр FDB моста | При инциденте |
| `bridge fdb show vlan <id>` | Linux | FDB с фильтром по VLAN | При инциденте |
| `cat /proc/net/vlan/config` | Linux | Список VLAN-интерфейсов | При старте |
| `bridge fdb monitor` | Linux | Real-time FDB updates | Continuous (debug) |
| `snmpwalk -v2c -c public <IP> .1.3.6.1.2.1.17.7.1.2.2` | SNMP | dot1qTpFdbTable (VLAN FDB) | Prometheus |
| `nfdump -R <path> -s record/vlan -o extended` | Linux | Агрегация по VLAN | При анализе |
| `tcpdump -i <iface> -e -nn 'vlan <id>'` | Linux | Захват по VLAN | При инциденте |

### Интервалы опроса

| Метрика | Интервал | Обоснование |
| :--- | :--- | :--- |
| **CAM table size** | 5-10 min | CAM растёт постепенно; слишком частый опрос создает нагрузку на CPU коммутатора |
| **MAC flapping events** | 1-2 min | Нужно быстрое срабатывание — петля может привести к полной неработоспособности сети |
| **Broadcast ratio** | 1 min | Быстрая реакция на storm; broadcast storm может забить канал за секунды |
| **Port error counters** | 5 min | Избыточный шум при частом опросе; ошибки редко возникают внезапно |
| **Flow data (NetFlow)** | 1-5 min | Баланс между точностью и нагрузкой; Active timeout = 60s обеспечивает детализацию |

### Recording Rules для.network метрик

Для ускорения дашбордов и снижения нагрузки на Prometheus используйте Recording Rules:

```yaml
# recording_rules.yml
groups:
  - name: vlan_recording_rules
    interval: 30s
    rules:
      # Трафик по VLAN (байты/секунду)
      - record: vlan:traffic_bytes_per_second:rate5m
        expr: |
          sum by (vid) (
            rate(snmp_dot1qVlanEgressOctets[5m])
          )

      # Использование CAM-таблицы (процент)
      - record: vlan:cam_utilization_percent:instant
        expr: |
          (
            dot1qTpFdbTable{vid!=""}
            /
            16000
          ) * 100

      # Broadcast ratio (процент)
      - record: vlan:broadcast_ratio_percent:rate5m
        expr: |
          (
            rate(snmp_ifBroadcast[5m])
            /
            rate(snmp_ifHCOutOctets[5m])
          ) * 100

      # Суммарный трафик по коммутатору
      - record: switch:total_traffic_bytes_per_second:rate5m
        expr: |
          sum by (instance) (
            rate(snmp_ifHCInOctets[5m])
            +
            rate(snmp_ifHCOutOctets[5m])
          )
```

> **Формат имени Recording Rule:** `level:metric:operations` — где `level` (group/namespace), `metric` (имя метрики), `operations` (rate, sum, avg и т.д.). Подробнее: [Правила в Prometheus](../../Prometheus/rules.md).

### Alertmanager: маршрутизация VLAN-алертов

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  receiver: 'default'
  group_by: ['alertname', 'instance']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    # Критические алерты — немедленно в Slack + PagerDuty
    - match:
        severity: critical
      receiver: 'critical-vlan'
      group_wait: 10s
      repeat_interval: 1h
    # Warning — в Slack с задержкой
    - match:
        severity: warning
      receiver: 'warning-vlan'
      repeat_interval: 4h

receivers:
  - name: 'default'
    slack_configs:
      - channel: '#network-alerts'
        send_resolved: true

  - name: 'critical-vlan'
    pagerduty_configs:
      - service_key: '<PD_SERVICE_KEY>'
    slack_configs:
      - channel: '#network-critical'
        send_resolved: true
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'

  - name: 'warning-vlan'
    slack_configs:
      - channel: '#network-warnings'
        send_resolved: true
```

### Grafana: структура дашборда для VLAN

Рекомендуемая структура дашборда (создается через JSON или UI):

**Row 1: Обзор**
- **Панель "Total Traffic per VLAN"** — Time series, запрос: `vlan:traffic_bytes_per_second:rate5m`
- **Панель "CAM Utilization"** — Gauge, запрос: `vlan:cam_utilization_percent:instant`

**Row 2: Алертинг**
- **Панель "MAC Flapping Events"** — State timeline, запрос: `changes(switch_mac_flapping_total[5m])`
- **Панель "Broadcast Ratio"** — Time series, запрос: `vlan:broadcast_ratio_percent:rate5m`

**Row 3: Детали по коммутаторам**
- **Панель "Switch Traffic"** — Table, запрос: `switch:total_traffic_bytes_per_second:rate5m`
- **Панель "Port Errors"** — Time series, запрос: `rate(snmp_ifInErrors[5m]) + rate(snmp_ifOutErrors[5m])`

**Row 4: NetFlow**
- **Панель "Top Talkers per VLAN"** — Table, данные из nfdump/clickhouse
- **Панель "Flow Distribution"** — Pie chart, агрегация по VLAN

**Template Variables (Templates):**
```json
{
  "name": "instance",
  "query": "label_values(snmp_ifHCInOctets, instance)",
  "type": "query",
  "refresh": 2
}
```

### Streaming Telemetry (gNMI) как альтернатива SNMP

Для современных высоконагруженных сетей (Spine-Leaf, 100G+) SNMP становится бутылочным горлышком. **Streaming Telemetry** решает эту проблему через push-модель и gNMI (gRPC Network Management Interface).

| Характеристика | SNMP | Streaming Telemetry (gNMI) |
| :--- | :--- | :--- |
| **Модель** | Pull (опрос по расписанию) | Push (данные потоком) |
| **Протокол** | UDP 161/162 | gRPC/HTTP2 (порт 830) |
| **Формат** | MIB/OID | YANG модели (OpenConfig) |
| **Производительность** | Ограничение на bulk walk | Высокая (бинарный формат, Protobuf) |
| **Частота обновлений** | Секунды-минуты | Миллисекунды |
| **Поддержка vendors** | Универсальная | Cisco, Arista, Juniper (2026) |

**Пример subscribe-запроса (gNMI):**
```bash
# Подписка на VLAN-статистику через gNMI (Python + pygnmi)
from pygnmi.client import gNMIclient

target = ('192.168.1.10', 830)
path = '/network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state'

with gNMIclient(target=target, username='admin', password='secure', insecure=True) as client:
    subscription = client.subscribe([
        {'path': path, 'mode': 'STREAM', 'sample_interval': 1000000000}  # 1 сек
    ])
    for notification in subscription:
        print(notification)
```

**Интеграция с Prometheus:** Используйте [gnmi_exporter](https://github.com/openconfig/gnmi) или [Telegraf с gNMI input](https://github.com/influxdata/telegraf/tree/master/plugins/inputs/gnmi) для трансляции gNMI-данных в Prometheus-формат.

### Типичные ошибки и их решения (Troubleshooting)

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **SNMP Exporter не возвращает данные** | `curl http://localhost:9116/snmp?target=...` — 502 или timeout | Неверный community string или firewall блокирует UDP 161 | Проверьте `snmpwalk -v2c -c <community> <target>` напрямую. Убедитесь, что UDP 161 доступен. |
| **Metric cardinality explosion** | Prometheus использует >10GB RAM, графики грузятся >30 сек | Слишком много уникальных label комбинаций (например, `ifDescr` для каждого порта) | Используйте `ifIndex` вместо `ifDescr` или агрегируйте через Recording Rules. |
| **NetFlow данные не поступают** | nfdump не показывает записей | Flow Exporter на коммутаторе не настроен или UDP 2055 заблокирован | Проверьте `show flow exporter` на коммутаторе. Убедитесь, что коллектор слушает UDP 2055. |
| **CAM table утекает** | `dot1qTpFdbTable` растет >90% | MAC flood атака илимножество VM с уникальными MAC | Включите port-security с `mac limit`. На Linux: `bridge link set dev <port> mcast_flood off`. |
| **MAC flapping false positives** | Алерты срабатывают без реальной проблемы | VM мигрирует между хостами (vMotion, live migration) | Увеличьте порог алерта или используйте `vmware-dvfilter` для фильтрации известных миграций. |
| **sFlow не показывает VLAN ID** | В sFlow-данных отсутствует поле `vlan` | sFlow-агент не настроен на инкапсуляцию L2 заголовка | Включите `sflow header-size 128` на коммутаторе для захвата полного заголовка. |
| **Grafana не рисует графики** | "No data" на панелях | Неверные PromQL-запросы или метрики не собраны | Проверьте Prometheus Targets (все ли экспортеры UP). Используйте Explore в Grafana для отладки запросов. |

**Общий порядок диагностики:**
1. **Проверьте доступность:** `ping`, `snmpwalk`, `nfdump -R` — убедитесь, что данные доходят до коллектора.
2. **Проверьте экспортеры:** Prometheus UI → Status → Targets — все ли таргеты в состоянии UP.
3. **Проверьте метрики:** `curl http://localhost:9116/snmp?target=... | grep vlan` — есть ли нужные метрики.
4. **Проверьте PromQL:** Grafana → Explore → Prometheus — выполните запрос вручную.
5. **Проверьте алерты:** Prometheus UI → Alerts — в каком состоянии алерты.

### Связанные документы

- **[VLAN в Linux: механизмы и диагностика](./vlan_linux_diagnostics.md)** — SSoT по Linux tools (iproute2, /proc, tcpdump).
- **[Spanning Tree Protocol (STP)](../stp.md)** — поиск петлей и MAC flapping.
- **[Безопасность портов и VLAN Hopping](./vlan_dtp_security.md)** — аномалии DTP, Port Security violation.
- **[L2 Switching и VLAN: Практические сценарии](../../Concepts/vlan_l2_switching/practical_scenarios.md)** — сценарий 5 (диагностика), сценарий 9 (incident response).

### См. также

- **[SNMP — обзор](../snmp_overview.md)** — протокол сетевого управления, MIB/OID, безопасность.
- **[NetFlow/IPFIX — мониторинг потоков](../sdn/netflow.md)** — глубокий анализ flow-данных.
- **[Экспортеры Prometheus](../../Prometheus/Exporters/overview.md)** — паттерн Multi-Target и каталог экспортеров.