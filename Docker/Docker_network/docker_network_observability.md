# Сетевая наблюдаемость Docker (Network Observability)

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026)

## Определения

- **Сетевая наблюдаемость контейнеров** — сбор и анализ метрик сетевого ввода-вывода контейнеров (байты, пакеты, ошибки, дропы) и состояния сетевого стека хоста (мосты, veth, conntrack) для обнаружения деградации до инцидента.
- **`docker stats`** — команда, показывающая потребление ресурсов контейнером в реальном времени, включая секцию `NET I/O` (принято/отправлено байт).
- **`/containers/<id>/stats`** — эндпоинт Docker API (API 1.25+), отдающий JSON с метриками CPU, памяти, блокового I/O и сети (`networks` — карта по интерфейсам).
- **cAdvisor** — агент сбора метрик контейнеров; экспортирует `container_network_*` метрики в Prometheus-формате.
- **Retransmit (повторная передача)** — повторная отправка TCP-сегмента из-за потери пакета; рост retransmits — ранний признак деградации сети или перегрузки.
- **Drop (дроп)** — отбрасывание пакета на уровне интерфейса или моста; растущие счётчики `rx_dropped`/`tx_dropped` — признак нехватки буферов или ошибок фильтрации.

## Основные концепции

### Что именно измеряется

Docker API и cAdvisor предоставляют per-interface сетевые метрики для каждого контейнера. Ключевые счётчики:

| Метрика | Что означает | На что указывает рост |
| :--- | :--- | :--- |
| `rx_bytes` / `tx_bytes` | Принятые/отправленные байты | Объём трафика, baseline для алертов на аномалии |
| `rx_packets` / `tx_packets` | Число пакетов | PPS-нагрузка, мелкие пакеты (DNS-амплификация) |
| `rx_errors` / `tx_errors` | Ошибки приёма/передачи | Проблемы NIC, драйвера, MTU-несоответствие |
| `rx_dropped` / `tx_dropped` | Отброшенные пакеты | Переполнение очередей, нехватка буферов, фильтрация |

Метрики доступны через `docker stats` (секция `NET I/O`), Docker API `/containers/<id>/stats` и cAdvisor (`container_network_receive_bytes_total` и т.д.). Стек сбора (Prometheus, cAdvisor, Grafana, OTel) описан в [Docker метриках](../Docker_metrics/docker_prometheus_integration.md) — здесь только сетевой срез.

### Почему сетевые метрики отдельно от CPU/памяти

Сетевые инциденты часто не видны в CPU и памяти: контейнер может потреблять мало ресурсов, но терять пакеты из-за MTU-несоответствия в туннеле, исчерпания conntrack или дропов на мосту. Сетевые метрики — единственный ранний сигнал для трёх классов проблем:

1. **Деградация throughput** — рост retransmits и дропов до падения доступности.
2. **Утечка соединений** — рост `conntrack`-записей и TIME_WAIT-сокетов.
3. **Аномальный трафик** — всплеск `tx_bytes` (исходящая атака, DNS-амплификация) или `rx_bytes` (сканирование).

### Состояние сетевого стека хоста

Метрики контейнера не показывают состояние моста и veth. Для полного покрытия наблюдайте за хостом:

| Объект | Команда | Что контролировать |
| :--- | :--- | :--- |
| Мосты и их адреса | `ip -o -4 addr show type bridge` | наличие `docker0` и `br-*`, адреса шлюзов |
| veth-пары | `ip -o link show type veth` | число пар (≈ число эндпоинтов), отсутствие «осиротевших» |
| Таблица conntrack | `conntrack -C` / `sysctl net.netfilter.nf_conntrack_count` | заполнение относительно `nf_conntrack_max` |
| Очереди моста | `tc -s qdisc show dev br-<id>` | дропы в `overlimits` |
| Сокеты демона | `ss -tulpn \| grep docker-proxy` | число `docker-proxy` процессов |

## Предварительные условия

- **Инструменты хоста** — `jq` (чтение Docker API), `iproute2` (`ip`, `ss`, `tc`), `conntrack-tools` (`conntrack -C/-L/-S`), `sysstat` (`nstat`), `bc` (расчёт доли conntrack), `ethtool` (L1-статистика NIC).
- **Права root** — `ss -p`, `conntrack`, `tc` и чтение netns требуют root/sudo.
- **Для сценариев 2 и 5** — cAdvisor (порт 8080) и node_exporter запущены и скрейпятся Prometheus; `promtool` для валидации правил (входит в дистрибутив Prometheus). Деплой cAdvisor: [деплой cAdvisor](../Docker_metrics/docker_cadvisor_deployment.md).
- **Для захвата трафика** — образ `nicolaka/netshoot` (tcpdump, ss, iperf3 в netns приложения).
- **Сетевые метрики доступны** только у контейнеров с собственным интерфейсом (bridge, macvlan, ipvlan, overlay); в режимах `container:` и `host` собственных счётчиков нет (см. «Ограничения»).

## Практические сценарии

### Сценарий 1: Метрики сети одного контейнера

```bash
# Текущие счётчики через docker stats (секция NET I/O)
docker stats --no-stream --format 'table {{.Name}}\t{{.NetIO}}'
# → NAME        NET I/O
# → api         1.2GB / 340MB

# Детально по интерфейсам через Docker API
# Версия в пути negotiable: демон Engine 29.x принимает API 1.40–1.54;
# эндпоинт /stats существует с API 1.25
curl -s --unix-socket /var/run/docker.sock \
  http://localhost/v1.54/containers/api/stats?stream=false \
  | jq '.networks'
# → {"eth0":{"rx_bytes":1288490188,"rx_packets":964689,
#           "rx_errors":0,"rx_dropped":0,
#           "tx_bytes":365072384,"tx_packets":412033,
#           "tx_errors":0,"tx_dropped":0}}
```

Ненулевые `rx_errors`/`rx_dropped` — сигнал к углублённой диагностике (см. сценарий 3).

### Сценарий 2: Prometheus-алерты на сетевые аномалии

cAdvisor экспортирует `container_network_*` метрики. Минимальный набор алертов:

```yaml
# /etc/prometheus/alerts/docker-network.yml
groups:
  - name: docker-network
    rules:
      - alert: ContainerNetworkErrors
        expr: rate(container_network_receive_errors_total{name!~"^(bridge|host|none|container)$"}[5m]) > 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Ошибки приёма сети у контейнера {{ $labels.name }}"

      - alert: ContainerNetworkDrops
        expr: rate(container_network_receive_packets_dropped_total{name!~"^(bridge|host|none|container)$"}[5m]) > 10
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Дропы пакетов у контейнера {{ $labels.name }}"

      - alert: ContainerNetworkSaturation
        expr: rate(container_network_transmit_bytes_total[5m])
              / on() (node_network_speed_bytes{device=~"eth.*"} or vector(1e9)) > 0.7
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} насыщает канал (>70%)"
```

Фильтр `name!~"^(bridge|host|none|container)$"` исключает инфраструктурные сети и снижает кардинальность (подробно: [снижение кардинальности Docker-метрик](../Docker_metrics/docker_metrics_interview_qa.md)). Имена метрик дропов включают `_packets_` — `container_network_receive_packets_dropped_total` и `container_network_transmit_packets_dropped_total` (полный перечень: [cAdvisor](../../Prometheus/Exporters/cadvisor.md)).

```bash
# Валидация синтаксиса правил перед применением
promtool check rules /etc/prometheus/alerts/docker-network.yml
# → SUCCESS: 3 rules found

# Перезагрузка правил без рестарта (при --web.enable-lifecycle)
curl -X POST http://localhost:9090/-/reload
# → 200 OK (пустой ответ)

# Проверка, что алерт видит данные: выражение в Prometheus UI
# rate(container_network_receive_packets_dropped_total[5m])
# → пустой результат при нулевых дропах — норма
```

### Сценарий 3: Диагностика дропов и ошибок

```bash
# 1. Счётчики ошибок на veth-конце хоста
ip -s link show veth<id>
# → RX: errors 0 dropped 12 ...
# → TX: errors 0 dropped 0 ...

# 2. Дропы на мосту
tc -s qdisc show dev br-<id>
# → qdisc noqueue 0: ...
# →  Sent 128461 bytes 1402 pkt (dropped 0, overlimits 0 ...)

# 3. TCP-retransmits на хосте (глобально)
nstat -az TcpRetransSegs TcpInErrs
# → TcpRetransSegs          4823      0.0

# 4. Захват трафика в netns приложения
docker run --rm -it --network container:<id> nicolaka/netshoot \
  tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-rst|tcp-syn) != 0'
```

Рост `TcpRetransSegs` при нулевых `rx_errors` обычно указывает на перегрузку или MTU-проблему в туннеле, а не на физический уровень.

### Сценарий 4: Мониторинг conntrack и утечки соединений

```bash
# Текущее заполнение таблицы conntrack
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 184320
# → net.netfilter.nf_conntrack_max = 262144

# Доля заполнения (алерт при >80%)
echo "scale=2; $(sysctl -n net.netfilter.nf_conntrack_count) * 100 / $(sysctl -n net.netfilter.nf_conntrack_max)" | bc
# → 70.31

# Топ-10 источников соединений
conntrack -L 2>/dev/null | awk '{print $5}' | sort | uniq -c | sort -rn | head
```

При приближении к лимиту в логах ядра появляются `nf_conntrack: table full, dropping packet` — контейнеры начинают терять связь. Лечение: рост `nf_conntrack_max` в sysctl (подробно: [исчерпание таблицы соединений](../Docker_troubleshooting/network_connectivity_issues.md)).

### Сценарий 5: Базовый dashboard (Grafana)

Минимальный набор панелей для сетевого здоровья Docker:

1. **Throughput per container** — `rate(container_network_receive_bytes_total[5m])` и `..._transmit_...`, grouped by `name`.
2. **Errors and drops** — `rate(container_network_receive_errors_total[5m])`, `rate(container_network_receive_packets_dropped_total[5m])` и `..._transmit_packets_dropped_...` (должны быть нулевыми).
3. **Conntrack fill ratio** — `node_netstat_Nf_conntrack_count / node_netstat_Nf_conntrack_count_max` (node_exporter).
4. **TCP retransmits** — `rate(node_netstat_TcpExt_TCPRetransFail[5m])` или `rate(node_netstat_Tcp_RetransSegs[5m])`.
5. **Number of veth pairs** — `count(node_network_receive_bytes_total{device=~"veth.*"})` как прокси плотности эндпоинтов.

```bash
# Валидация: метрики приходят от cAdvisor
curl -s http://<cadvisor-host>:8080/metrics \
  | grep -c '^container_network_receive_bytes_total'
# → число интерфейсов контейнеров (>0)

# Валидация: conntrack-метрики node_exporter
curl -s http://<node-exporter-host>:9100/metrics \
  | grep '^node_netstat_Nf_conntrack_count '
# → node_netstat_Nf_conntrack_count 184320
```

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика |
| :--- | :--- | :--- |
| Рост `rx_dropped` на veth | переполнение очереди моста, мелкие пакеты | `tc -s qdisc show dev br-<id>`; `ethtool -S eth0` |
| Рост `TcpRetransSegs`, нулевые ошибки | MTU-несоответствие в туннеле/VPN | `ping -M do -s 1472 <ip>`; `ip link show` |
| `nf_conntrack: table full` | утечка соединений или всплеск PPS | `conntrack -C`; `conntrack -L \| awk` |
| Всплеск `tx_bytes` у одного контейнера | исходящая атака, DNS-амплификация | `docker exec <c> ss -tulpn`; tcpdump в netns |
| `docker-proxy` процессов больше, чем портов | утечка прокси при частом пересоздании | `ss -tulpn \| grep docker-proxy \| wc -l` |
| Метрики сети отсутствуют у контейнера | контейнер в режиме `container:`/`host` (нет собственного интерфейса) | `docker inspect <c> --format '{{.HostConfig.NetworkMode}}'` |
| Алерт на дропы молчит при реальных дропах | неверное имя метрики (без `_packets_`) | `curl -s :8080/metrics \| grep dropped` — список реальных имён |
| Всплеск `rx_packets` при стабильных `rx_bytes` | мелкие пакеты: DNS-амплификация, сканирование | `tcpdump` в netns; `docker exec <c> ss -tulpn` |
| Метрики не объясняют разрыв связи | контейнер пересоздан или отключён от сети | `docker events --filter type=network` ([события жизненного цикла](../Docker_troubleshooting/debugging_with_docker_events.md)) |

## Рекомендации

- **Собирайте сетевые метрики всегда**, даже если CPU/память в норме — сетевые инциденты не коррелируют с ними.
- **Алертируйте на ошибки и дропы, а не только на throughput** — нулевые ошибки/дропы — инвариант здоровой сети; любое ненулевое значение требует внимания.
- **Мониторьте conntrack отдельно** — его исчерпание ломает связь всех контейнеров хоста одновременно, а не одного.
- **Используйте `docker stats` для быстрого взгляда, API/cAdvisor — для истории** — `docker stats` не хранит временные ряды.
- **Фильтруйте инфраструктурные сети** (`bridge|host|none|container`) в алертах и дашбордах — иначе кардинальность и шум растут без пользы.
- **Базелиньте throughput** — алерт на абсолютное значение бесполезен; алерт на отклонение от baseline и на saturation канала — полезен.
- **Коррелируйте метрики с событиями жизненного цикла** — `docker events --filter type=network` (connect/disconnect) объясняет разрывы связи, которые метрики показывают только как обрыв ряда; разбор: [Docker Events](../Docker_troubleshooting/debugging_with_docker_events.md).
- **Настройте `--housekeeping_interval` cAdvisor под частоту алертов** — по умолчанию 1s; при увеличении до 10s краткосрочные всплески дропов теряются. Для алертов на ошибки/дропы держите 1–5s или используйте `rate()` с окном, кратным интервалу (тюнинг: [cAdvisor](../../Prometheus/Exporters/cadvisor.md)).

## Дополнительная информация

### Смежные темы

- [Docker метрики: Prometheus-интеграция](../Docker_metrics/docker_prometheus_integration.md) — стек сбора, cAdvisor, Grafana.
- [Нативные метрики Docker](../Docker_metrics/docker_native_metrics.md) — `docker stats`, API `/stats`, `docker events`.
- [Устранение проблем сетевой связности](../Docker_troubleshooting/network_connectivity_issues.md) — conntrack, MTU, netshoot.
- [Обзор сетевой модели Docker](./docker_network.md) — архитектура стека, мосты, veth.
- [iperf3](../../Linux/Diagnostics/Networking/iperf3.md) — замер throughput между контейнерами.
- [Диагностика Traffic Control](../../Linux/Diagnostics/Networking/tc_diagnostics.md) — дропы в очередях моста.
- [Справочник метрик Docker Engine](../Docker_metrics/docker_engine_metrics_reference.md) — метрики демона на порту 9323.
- [Деплой cAdvisor](../Docker_metrics/docker_cadvisor_deployment.md) — запуск, `--docker_only`, `housekeeping_interval`.
- [cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md) — SSoT по метрикам `container_network_*`, PromQL и правилам алертинга.
- [Отладка с помощью Docker Events](../Docker_troubleshooting/debugging_with_docker_events.md) — `docker events --filter type=network`, корреляция с жизненным циклом сетей.

### Ограничения

- Метрики `docker stats` и API `/stats` — счётчики с момента старта контейнера; для истории нужен Prometheus/cAdvisor.
- Сетевые метрики недоступны для контейнеров в режиме `container:` (нет собственного интерфейса) и агрегируются в `host`-режиме на уровне хоста.
- `rx_errors`/`tx_errors` в Docker API отражают ошибки veth-интерфейса, а не физического NIC — для диагностики L1 используйте `ethtool` на хосте.
- Разрешение сетевых метрик ограничено `--housekeeping_interval` cAdvisor (по умолчанию 1s): при увеличении интервала краткосрочные всплески дропов и ошибок не попадают в выборку.
