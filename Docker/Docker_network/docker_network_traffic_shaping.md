# Traffic shaping и ограничение полосы контейнеров Docker

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026)

## Определения

- **Traffic shaping (шейпинг)** — управление скоростью и приоритетами сетевого трафика: задержка, ограничение полосы, приоритизация классов трафика.
- **veth-пара (Virtual Ethernet)** — пара связанных виртуальных интерфейсов: один конец (`eth0`) — в контейнере, второй (`vethXXXX`) — на хосте, подключён к мосту (`br-<id>`). Трафик контейнера проходит через эту пару.
- **qdisc (queueing discipline)** — дисциплина очереди в Linux Traffic Control (`tc`): определяет, как пакеты ставятся в очередь и как ограничивается/распределяется полоса.
- **TBF (Token Bucket Filter)** — бесклассовая дисциплина для точечного ограничения скорости без иерархии: токены добавляются с фиксированной скоростью, избыток буферизуется (до `latency`) или отбрасывается.
- **CAKE (Common Applications Kept Enhanced)** — современная «универсальная» дисциплина: шейпинг + справедливое распределение очереди + защита от bufferbloat минимальной настройкой.
- **netem (Network Emulator)** — дисциплина для эмуляции условий сети: задержка, джиттер, потери, повреждение и дублирование пакетов. Работает только на egress.
- **IFB (Intermediate Functional Block)** — виртуальное устройство, на которое перенаправляется ingress-трафик для полноценного shaping: egress-shaping на `ifbX` эквивалентен ingress-shaping исходного интерфейса.
- **Egress shaping** — ограничение исходящего трафика (от контейнера наружу); применяется как qdisc на исходе хостового конца veth.
- **Ingress policing** — ограничение входящего трафика; нативный `ingress` qdisc в Linux только отбрасывает (police), не буферизирует. Полноценный ingress shaping — через перенаправление на виртуальный интерфейс `ifb`.
- **Noisy neighbor** — контейнер, потребляющий непропорционально большую полосу и деградирующий соседей на общем хосте/канале.

## Основные концепции

### Почему Docker не ограничивает полосу нативно

Docker имеет нативные лимиты на CPU (`--cpus`) и память (`--memory`), но **не имеет** флага ограничения сетевой полосы. Ограничение полосы контейнера — задача Linux Traffic Control (`tc`) на хосте, применённая к veth-интерфейсу контейнера. Это принципиально важно: сетевой QoS в Docker — не конфигурация демона, а конфигурация ядра хоста.

### Где применять tc: veth, мост или хост

| Объект | Команда | Что ограничивает |
| :--- | :--- | :--- |
| Хостовый конец veth (`vethXXXX`) | `tc qdisc add dev vethXXXX ...` | **один контейнер** (egress) |
| Мост (`br-<id>`) | `tc qdisc add dev br-<id> ...` | все контейнеры сети (суммарно) |
| Физический интерфейс (`eth0`) | `tc qdisc add dev eth0 ...` | весь хост |

Для per-container ограничения — veth. Для ограничения всей сети — мост. Механика `tc` (qdisc, классы, фильтры, CAKE, fq_codel, TBF) описана в [tc: управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md).

### Идентификация хостового veth контейнера

Имя veth нестабильно (пересоздаётся при перезапуске контейнера), поэтому сопоставление «контейнер → хостовый интерфейс» выполняется по атрибутам интерфейса, а не по имени.

**Метод 1 — iflink (основной).** Атрибут `iflink` конца veth в контейнере содержит `ifindex` его peer-а — хостового veth (свойство veth-пары из sysfs ABI ядра):

```bash
# 1. iflink eth0 контейнера = ifindex хостового veth
IFLINK=$(docker exec app cat /sys/class/net/eth0/iflink)

# 2. Найти интерфейс хоста с таким ifindex
ip -o link | awk -v idx="$IFLINK" -F': ' '$1 == idx {print $2}' | cut -d@ -f1
# → veth9a3b
```

**Метод 2 — MAC через FDB моста.** MAC-адрес `eth0` контейнера присутствует в таблице коммутации моста, привязанный к порту-veth:

```bash
MAC=$(docker inspect app --format '{{range .NetworkSettings.Networks}}{{.MacAddress}}{{end}}')
bridge fdb show | grep "$MAC"
# → 02:42:ac:12:00:02 dev veth9a3b ... master br-0a532e992162
```

**Обратный поиск (veth → контейнер).** По IP-адресу на хостовом конце veth:

```bash
ip -o addr show dev veth9a3b
# → inet 172.18.0.2/16 scope global veth9a3b
docker ps -q | xargs -I{} docker inspect --format '{{.Id}} {{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' {} | grep 172.18.0.2
```

> **Важно:** `ifindex` интерфейса контейнера **не равен** `ifindex` хостового veth — они находятся в разных network namespace. Сопоставление идёт через `iflink`, а не через `ifindex`.

### Egress vs ingress — асимметрия

- **Egress (исходящий от контейнера)**: shaping нативен — qdisc на исходе хостового veth буферизирует и ограничивает полосу.
- **Ingress (входящий к контейнеру)**: нативный `ingress` qdisc только **polices** (отбрасывает сверх лимита), не буферизирует. Полноценный ingress shaping — через `ifb` (Intermediate Functional Block): ingress-трафик перенаправляется на виртуальный `ifbX`, где применяется обычный egress-shaping.

```
Контейнер → eth0 → [vethXXXX на хосте] → br-<id> → eth0 → внешний мир
              egress: tc на vethXXXX (egress)
              ingress: tc на vethXXXX (ingress → ifb)
```

### Альтернатива: tc внутри контейнера

Если хост недоступен (например, контейнер запускает сторонний оператор), shaping можно применить изнутри контейнера на его `eth0` — qdisc привязывается к сетевому устройству в netns контейнера:

```bash
docker run -d --name app --cap-add NET_ADMIN my-app
docker exec app tc qdisc replace dev eth0 root tbf rate 10mbit burst 32kb latency 400ms
```

Ограничения подхода:

- Требуется `--cap-add NET_ADMIN` (и `iproute2` в образе) — расширение привилегий контейнера. С точки зрения безопасности хостовый подход предпочтительнее: `NET_ADMIN` в контейнере позволяет менять и другие параметры его netns.
- Ограничивается только **egress** от контейнера; ingress по-прежнему требует хостового `tc`/`ifb`.
- Правило живёт в netns контейнера и исчезает вместе с ним — персистентность не нужна, но правило не переживает перезапуск.

## Предварительные условия

- **Хост Linux** с пакетом `iproute2` (утилиты `tc`, `ip`, `bridge`): `sudo apt install iproute2` (Debian/Ubuntu) или `sudo dnf install iproute` (RHEL/Fedora).
- **Права root на хосте** — `tc` требует `CAP_NET_ADMIN` в netns хоста.
- **Модули ядра**: `sch_htb`, `sch_cake`, `sch_tbf`, `sch_netem` (обычно встроены или загружаются автоматически при первом использовании); `ifb` — для ingress-shaping (`sudo modprobe ifb`, по умолчанию создаётся 2 устройства `ifb0`/`ifb1`, число задаётся параметром `numifbs`; современная альтернатива — создание по требованию: `sudo ip link add ifb0 type ifb`).
- **Контейнер в bridge-сети** (собственный veth). В режимах `host` и `container:` собственного veth нет — per-container shaping недоступен (см. «Ограничения»).
- **Для замеров** — `iperf3` в контейнере и на сервере-получателе.

## Практические сценарии

### Сценарий 1: Ограничение egress одного контейнера

```bash
# 1. Найти хостовый конец veth контейнера (метод iflink — см. раздел выше)
IFLINK=$(docker exec app cat /sys/class/net/eth0/iflink)
VETH=$(ip -o link | awk -v idx="$IFLINK" -F': ' '$1 == idx {print $2}' | cut -d@ -f1)
# → veth9a3b

# 2a. Простое ограничение — CAKE (одной строкой, с защитой от bufferbloat)
sudo tc qdisc replace dev "$VETH" root cake bandwidth 10mbit

# 2b. Или TBF — точечное ограничение без классов
sudo tc qdisc replace dev "$VETH" root tbf rate 10mbit burst 32kb latency 400ms

# 2в. Или HTB — когда нужны классы и приоритеты (см. сценарий 4)
sudo tc qdisc add dev "$VETH" root handle 1: htb default 10
sudo tc class add dev "$VETH" parent 1: classid 1:1 htb rate 10mbit
sudo tc class add dev "$VETH" parent 1:1 classid 1:10 htb rate 10mbit

# 3. Проверка
tc -s qdisc show dev "$VETH"
# → cake 8001: root ... bandwidth 10Mbit ...
# → Sent 128461 bytes 1402 pkt (dropped 0, overlimits 0 ...)

# 4. Замер throughput из контейнера
docker exec app iperf3 -c <server> -t 10
# → ~10 Mbit/s (вместо полной полосы)
```

> Для одиночного лимита без классификации CAKE или TBF проще HTB: HTB оправдан, когда трафик нужно раскладывать по классам (сценарий 4). Используйте `replace` вместо `add`, чтобы не получать `RTNETLINK answers: File exists` при повторном применении.

### Сценарий 2: Ingress-ограничение через IFB

```bash
# 1. Создать и поднять ifb (современный способ — устройство по требованию)
sudo ip link add ifb0 type ifb 2>/dev/null || true
sudo ip link set dev ifb0 up
# Альтернатива: sudo modprobe ifb numifbs=4 (по умолчанию numifbs=2)

# 2. Перенаправить ingress veth на ifb0
VETH=veth9a3b
sudo tc qdisc add dev "$VETH" handle ffff: ingress
sudo tc filter add dev "$VETH" parent ffff: protocol ip u32 \
  match u32 0 0 action mirred egress redirect dev ifb0

# 3. Ограничить полосу на ifb0 (egress-shaping на ifb = ingress-shaping для veth)
sudo tc qdisc replace dev ifb0 root cake bandwidth 5mbit

# 4. Проверка
tc -s qdisc show dev ifb0
# → cake ... bandwidth 5Mbit ...
```

> Фильтр `protocol ip` матчит только IPv4. Для dual-stack добавьте второй фильтр с `protocol ipv6`. Проверка ingress-лимита: `docker exec app iperf3 -s` внутри контейнера, затем `iperf3 -c <IP-контейнера>` с хоста или другого хоста — ожидаемый throughput ~5 Mbit/s.

### Сценарий 3: Ограничение всей bridge-сети

```bash
# Все контейнеры сети app-net ограничены суммарно 100 Мбит/с
BRIDGE=br-0a532e992162
sudo tc qdisc replace dev "$BRIDGE" root cake bandwidth 100mbit

# Проверка
tc -s qdisc show dev "$BRIDGE"
```

Ограничение на мосте — **суммарное** для всей сети. Для индивидуальных лимитов применяйте правила к veth каждого контейнера (сценарий 1).

### Сценарий 4: Приоритизация трафика (QoS)

```bash
# HTB с двумя классами: интерактивный (SSH, гарантия 5Mbit) и bulk (80% полосы)
VETH=veth9a3b
sudo tc qdisc add dev "$VETH" root handle 1: htb default 20
sudo tc class add dev "$VETH" parent 1: classid 1:1 htb rate 100mbit ceil 100mbit
sudo tc class add dev "$VETH" parent 1:1 classid 1:10 htb rate 5mbit ceil 100mbit prio 1
sudo tc class add dev "$VETH" parent 1:1 classid 1:20 htb rate 80mbit ceil 100mbit prio 2

# Листовые дисциплины — защита от bufferbloat внутри классов
sudo tc qdisc add dev "$VETH" parent 1:10 fq_codel
sudo tc qdisc add dev "$VETH" parent 1:20 fq_codel

# Фильтры: SSH в приоритетный класс (обе стороны соединения)
sudo tc filter add dev "$VETH" protocol ip parent 1: prio 1 u32 \
  match ip sport 22 0xffff flowid 1:10
sudo tc filter add dev "$VETH" protocol ip parent 1: prio 1 u32 \
  match ip dport 22 0xffff flowid 1:10

# Проверка
tc -s class show dev "$VETH"
```

`rate` — гарантированная полоса, `ceil` — максимум с заимствованием у соседних классов. Более сложные схемы классификации (flower, DSCP-метки) — в [tc: управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md).

### Сценарий 5: Эмуляция сетевых условий (netem)

Полезно для тестирования устойчивости приложений (chaos engineering): задержка, джиттер, потери на трафике конкретного контейнера.

```bash
VETH=veth9a3b

# Задержка 100ms ± 10ms, потеря 1% пакетов
sudo tc qdisc replace dev "$VETH" root netem delay 100ms 10ms loss 1%

# Проверка
tc -s qdisc show dev "$VETH"
# → netem 8001: root ... limit 1000 delay 100.0ms 10.0ms loss 1%

# Проверка из контейнера
docker exec app ping -c 10 <target>
# → RTT ~100ms ± 10ms

# Комбинация «полоса + задержка»: TBF корнем, netem листом
sudo tc qdisc replace dev "$VETH" root handle 1: tbf rate 10mbit burst 32kb latency 400ms
sudo tc qdisc add dev "$VETH" parent 1:1 netem delay 100ms 10ms
```

> `netem` работает только на egress и не является шейпером (ограничение полосы — через `rate` netem или связку с TBF/HTB). Полный справочник по параметрам (corrupt, duplicate, reorder, распределения) — в [tc netem](../../Linux/Networking/Tools/iproute2/tc_netem.md).

### Сценарий 6: Персистентность правил

Правила `tc` теряются при перезагрузке. Восстановление — скрипт, привязанный к появлению veth:

```ini
# /etc/systemd/system/docker-tc.service
[Unit]
Description=Apply tc rules to Docker veth interfaces
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/docker-tc-apply

[Install]
WantedBy=multi-user.target
```

```bash
#!/usr/bin/env bash
# /usr/local/sbin/docker-tc-apply — применяет правила к veth контейнеров с меткой
set -euo pipefail
for c in $(docker ps -q --filter label=net.qos=limited); do
  IFLINK=$(docker exec "$c" cat /sys/class/net/eth0/iflink)
  VETH=$(ip -o link | awk -v idx="$IFLINK" -F': ' '$1 == idx {print $2}' | cut -d@ -f1 | head -1)
  [ -n "$VETH" ] && sudo tc qdisc replace dev "$VETH" root cake bandwidth 10mbit
done
```

Юнит на `After=docker.service` покрывает только правила, применяемые при загрузке хоста. veth создаётся при **старте контейнера**, поэтому для контейнеров, запускаемых позже, нужна привязка к событию появления интерфейса — udev-rule:

```
# /etc/udev/rules.d/99-docker-tc.rules
ACTION=="add", SUBSYSTEM=="net", KERNEL=="veth*", RUN+="/usr/local/sbin/docker-tc-apply"
```

> У udev `RUN` ограниченное окружение и таймаут: убедитесь, что `docker` и `ip` доступны по абсолютному пути в скрипте. Альтернатива — systemd `.path`-юнит на `/sys/class/net/veth*`.

Персистентность `ifb` (для ingress-сценария): `/etc/modules-load.d/ifb.conf` с содержимым `ifb` и `/etc/modprobe.d/ifb.conf` с `options ifb numifbs=4`.

## Проверка и валидация

| Что проверяем | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| qdisc на месте | `tc qdisc show dev "$VETH"` | строка `cake ... bandwidth 10Mbit` / `htb ...` / `netem ...` |
| Счётчики shaping | `tc -s qdisc show dev "$VETH"` | растущие `Sent` и `overlimits` при превышении лимита; `dropped` — при police или переполнении очереди |
| Фильтр классифицирует | `tc -s filter show dev "$VETH"` | растущие счётчики `Sent`/`packets` у нужного фильтра |
| Egress throughput | `docker exec app iperf3 -c <server> -t 10` | ~лимит (например, 10 Mbit/s) |
| Ingress throughput | `docker exec app iperf3 -s`, затем `iperf3 -c <IP-контейнера>` с хоста | ~лимит (например, 5 Mbit/s) |
| Задержка (netem) | `docker exec app ping -c 10 <target>` | RTT ≈ заданная задержка ± джиттер |
| Мониторинг в реальном времени | `watch -n 1 'tc -s qdisc show dev "$VETH"'` | динамика `backlog`, `dropped`, `overlimits` |

Счётчики `tc` (`overlimits`, `dropped`, `backlog`) — сигнал для алертов на насыщение канала; интеграция с метриками хоста описана в [Сетевая наблюдаемость Docker](./docker_network_observability.md).

## Устранение неисправностей

| Симптом | Причина | Диагностика |
| :--- | :--- | :--- |
| Правило tc не применяется | неверный veth (правило на другом интерфейсе) | сверка по `iflink` (см. «Идентификация veth»); `ip -o link show master <br>` |
| `RTNETLINK answers: File exists` | qdisc уже существует на интерфейсе | `tc qdisc replace` вместо `add`, или `tc qdisc del dev <veth> root` перед созданием |
| `RTNETLINK answers: Operation not permitted` | нет root/CAP_NET_ADMIN | выполнять `tc` на хосте от root; внутри контейнера — `--cap-add NET_ADMIN` |
| Ограничение не работает после пересоздания контейнера | veth пересоздаётся, правило теряется | персистентность через скрипт/udev (сценарий 6) |
| Ingress не ограничивается | `ingress` qdisc только polices; либо фильтр `protocol ip` не матчит IPv6 | использовать `ifb` для shaping; добавить фильтр `protocol ipv6` |
| Ingress не ограничивается, ifb пуст | модуль/устройство ifb не создано | `sudo modprobe ifb` или `sudo ip link add ifb0 type ifb`; `ip link show ifb0` |
| Буферизация, высокая задержка | qdisc без управления буфером (pfifo_fast по умолчанию) | CAKE или fq_codel вместо HTB-по-умолчанию; листовые fq_codel в классах |
| `tc: qdisc noqueue` на veth | на интерфейсе нет qdisc | `tc qdisc add dev <veth> root ...` |
| Правила пропали после reboot | tc не персистентен | systemd-юнит / udev-rule (сценарий 6) |
| Контейнер в режиме `host` не ограничивается | собственного veth нет | shaping только на физическом интерфейсе (затрагивает весь хост) |
| Throughput выше лимита | трафик идёт в обход ограниченного интерфейса (другая сеть, overlay) | `docker exec app ip route`; проверить, что весь трафик идёт через ограниченный veth |

## Рекомендации

- **Используйте CAKE для простых ограничений** — одна строка, защита от bufferbloat, справедливое разделение полосы; TBF — для точечного одиночного лимита; HTB — когда нужны классы и приоритеты.
- **Ограничивайте egress через veth, ingress — через ifb** — нативный ingress только отбрасывает пакеты.
- **Предпочитайте хостовый tc доступу NET_ADMIN в контейнере** — не расширяйте привилегии контейнера без необходимости.
- **Планируйте персистентность заранее** — правила `tc` не переживают перезагрузку и пересоздание контейнера; автоматизируйте привязку к veth.
- **Маркируйте контейнеры метками** (`--label net.qos=limited`) — скрипт находит veth по метке, а не по жёстко заданному имени.
- **Тестируйте замером** — `iperf3` из контейнера до сервера (egress) и до контейнера (ingress): ожидаемый throughput должен совпадать с лимитом.
- **Не накладывайте shaping на мост без необходимости** — ограничение моста суммарно ограничивает все сети на нём; per-container — через veth.
- **Мониторьте счётчики tc** — рост `overlimits` и `dropped` на veth — ранний сигнал перегрузки канала.
- **Документируйте лимиты** — в инвентаризации хоста фиксируйте, какие контейнеры ограничены и какой полосой.

## Откат и очистка

```bash
# Удалить shaping с veth (удаляет всю иерархию классов под корнем)
sudo tc qdisc del dev "$VETH" root

# Удалить ingress-redirect на veth
sudo tc qdisc del dev "$VETH" ingress

# Очистить ifb
sudo tc qdisc del dev ifb0 root 2>/dev/null || true
sudo ip link set dev ifb0 down

# Полный сброс правил на мосту
sudo tc qdisc del dev "$BRIDGE" root 2>/dev/null || true
```

Правила, применённые к veth, исчезают вместе с интерфейсом при остановке контейнера — отдельный откат для них не нужен. Отключение systemd-юнита: `sudo systemctl disable --now docker-tc.service`.

## Дополнительная информация

### Смежные темы

- [Обзор сетевой модели Docker](./docker_network.md) — veth-пары, мосты, packet flow.
- [Драйвер bridge](./drivers/bridge.md) — архитектура veth и моста.
- [tc: управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md) — qdisc, HTB, CAKE, TBF, IFB, flower (SSoT по tc).
- [tc netem: эмуляция сетевых проблем](../../Linux/Networking/Tools/iproute2/tc_netem.md) — задержка, потери, джиттер.
- [Диагностика Traffic Control](../../Linux/Diagnostics/Networking/tc_diagnostics.md) — проверка текущих qdisc.
- [QoS: policing и shaping](../../Networking/Concepts/qos.md) — ingress policing, IFB, DiffServ.
- [iperf3](../../Linux/Diagnostics/Networking/iperf3.md) — замер throughput.
- [Сетевая наблюдаемость](./docker_network_observability.md) — дропы и saturation.

### Ограничения

- Docker не имеет нативного флага ограничения полосы — все ограничения через `tc` на хосте.
- Имя veth нестабильно; сопоставление контейнер↔veth — по `iflink` (или MAC через FDB моста). `ifindex` интерфейса контейнера не совпадает с `ifindex` хостового veth.
- Ingress shaping через `ifb` добавляет hop и требует устройства `ifb`; в некоторых средах (rootless, Docker Desktop) недоступен.
- Режимы `host` и `container:` не создают veth — per-container shaping недоступен; shaping на физическом интерфейсе затрагивает весь хост.
- В Kubernetes сетевой стек управляется CNI (Calico, Cilium и др.), который может накладывать собственные tc-правила; подход данного файла применим к Docker-бриджам на узле, а не к подам.
