# Многохостовые сети Docker без Swarm

**Актуально для:** Docker Engine 29.x (актуальный релиз — 29.8.x, сентябрь 2026)

## Определения

- **Многохостовая сеть (multi-host network)** — сеть, в которой контейнеры на разных физических хостах взаимодействуют напрямую, как будто находятся в одном сегменте.
- **Ограничение bridge** — пользовательская `bridge`-сеть существует только в пределах одного хоста (`scope: local`); контейнеры на разных хостах в разных bridge-сетях не видят друг друга напрямую.
- **Ограничение overlay** — встроенный драйвер `overlay` требует активированного Swarm-режима (`docker swarm init`); без Swarm создание overlay-сети завершается ошибкой.
- **macvlan/ipvlan multi-host** — контейнеры на разных хостах с macvlan в одном L2-сегменте (один VLAN, одна подсеть) общаются через физическую сеть как обычные L2-узлы — без overlay и без Swarm. ipvlan в режиме L3 работает и без общего L2: подсети контейнеров маршрутизируются между хостами на уровне IP.
- **Ручной VXLAN-туннель** — туннель, созданный средствами ядра Linux (`ip link add ... type vxlan`) между хостами, поверх которого поднимается bridge с контейнерами.
- **VPN-мост** — схема, в которой хосты соединены через VPN-туннель (WireGuard), а bridge-сети контейнеров маршрутизируются через этот туннель.

## Основные концепции

### Почему bridge не работает между хостами

Bridge-сеть — это Linux-мост (`br-<id>`) на одном хосте. Контейнеры подключены к нему через veth-пары. Мост не имеет представления о других хостах: трафик не покидает хост, а правила фильтрации Docker изолируют bridge-сети друг от друга. Поэтому два контейнера на разных хостах в разных bridge-сетях не имеют маршрута друг к другу.

### Четыре подхода без Swarm

| Подход | Уровень | Требования | Когда |
| :--- | :--- | :--- | :--- |
| **macvlan/ipvlan в общем L2** | L2/L3 | общий VLAN, promiscuous на порту коммутатора | контейнеры как полноценные узлы сети |
| **Ручной VXLAN** | L2 overlay | `ip link` на каждом хосте, UDP-порт | полный контроль, без плагинов |
| **VPN-мост (WireGuard)** | L3 tunnel | WireGuard между хостами, маршрутизация | хосты в разных подсетях/ЦОД |
| **Сторонний overlay-драйвер** | L2/L3 | установленный плагин (Weave — архивирован в 2024) | шифрование, политики без Swarm |

### Порты и протоколы

| Схема | Порт/протокол | Назначение |
| :--- | :--- | :--- |
| Ручной VXLAN | UDP 4789 | плоскость данных VXLAN (порт IANA); multicast-режим дополнительно требует поддержки multicast (IGMP) в underlay |
| VPN-мост (WireGuard) | UDP 51820 | туннель WireGuard (порт по умолчанию) |
| Weave | TCP 6783; TCP/UDP 6784 | control/data плоскости — по документации Weave Net; не подтверждено в актуальных источниках (сайт документации недоступен после архивации репозитория) |
| Swarm `overlay` | UDP 4789 + порты Swarm | data path overlay; полный список — в [сетевом взаимодействии Swarm](../../Docker_swarm/swarm_networking.md) |

### macvlan/ipvlan multi-host — как это работает

Контейнеры с macvlan получают собственный MAC и IP из физической подсети. Если два хоста подключены к одному L2-сегменту (один VLAN) и macvlan-сети на обоих хостах используют одну подсеть и один parent-интерфейс, контейнеры на разных хостах видят друг друга через физический коммутатор — как любые два узла в одном VLAN. Overlay и Swarm не нужны.

Ограничение: сам хост не видит macvlan-контейнеры без дополнительного macvlan-shim интерфейса (подробно: [драйвер macvlan](./drivers/macvlan.md)).

ipvlan в режиме L3 не требует общего L2-сегмента: трафик маршрутизируется на уровне IP через стек хоста, а подсети контейнеров должны быть маршрутизируемы между хостами (через физическую сеть или туннель). Режимы L2/L3/L3S и их ограничения — в [драйвере ipvlan](./drivers/ipvlan.md).

### Ручной VXLAN — как это работает

Ядро Linux поддерживает VXLAN нативно. На каждом хосте создаётся VXLAN-интерфейс с общим VNI, под ним — bridge, к которому подключаются контейнеры. Трафик между хостами инкапсулируется в UDP. Это то же, что делает встроенный `overlay`-драйвер, но вручную и без Swarm.

### VPN-мост — как это работает

Хосты соединены WireGuard-туннелем. Bridge-сети контейнеров на каждом хосте маршрутизируются через туннель (статические маршруты или `allowedips`). Контейнеры остаются в своих bridge-сетях, но подсети достижимы через VPN. Подробно о WireGuard в контейнерах: [WireGuard](../../Vpn/wireguard.md), [VPN в контейнерах](../../Networking/Tunnels/vpn_in_containers.md).

## Предварительные условия

- **Права root/sudo** — интерфейсы, bridge и маршруты создаются на хосте (`ip link`, `ip route`, `sysctl`), не внутри контейнера.
- **Docker Engine 29.x** на каждом хосте; для сторонних плагинов — плагин установлен и зарегистрирован (`docker info --format '{{json .Plugins}}'`).
- **Ядро Linux** с модулем `vxlan` (проверка: `modinfo vxlan`), утилиты `iproute2` и `bridge-utils` для ручного VXLAN.
- **Маршрутизация** — `net.ipv4.ip_forward=1` для VPN-моста и маршрутизации между bridge и туннелем.
- **Сетевая инфраструктура**:
  - macvlan L2 — общий VLAN и promiscuous-режим (или VLAN-trunk) на порту коммутатора;
  - ручной VXLAN — L3-связность между хостами и открытый UDP 4789 (или multicast в underlay);
  - VPN-мост — WireGuard между хостами, открытый UDP 51820;
  - Weave — control/data порты плагина (см. «Порты и протоколы»).
- **Свободное адресное пространство** — подсети многохостовых сетей не должны пересекаться с подсетями хостов, VPN и корпоративными диапазонами. Docker проверяет пересечения только внутри своего демона и не видит внешние маршруты хоста — планирование адресации и пулы: [IPAM и планирование ёмкости](./docker_network_ipam_scale.md).

## Практические сценарии

### Сценарий 1: macvlan multi-host в общем VLAN

Два хоста в одном VLAN, контейнеры как узлы физической сети.

```bash
# На обоих хостах — одна подсеть и один parent
# Хосты в VLAN 100 (parent eth0.100); IP управления — 192.168.1.0/24
# (Хост A — 192.168.1.10, Хост B — 192.168.1.11)
docker network create -d macvlan \
  --subnet 192.168.100.0/24 \
  --gateway 192.168.100.1 \
  -o parent=eth0.100 \
  -o macvlan_mode=bridge \
  prod-vlan

# Контейнеры на разных хостах (IP уникальны в пределах подсети)
# Хост A:
docker run -d --name app-a --network prod-vlan \
  --ip 192.168.100.11 nginx:alpine
# Хост B:
docker run -d --name app-b --network prod-vlan \
  --ip 192.168.100.12 nginx:alpine

# Валидация: драйвер и связность через физическую сеть
docker network inspect prod-vlan -f '{{.Driver}}'
# → macvlan
docker exec app-a ping -c 2 192.168.100.12
# → 2 packets transmitted, 2 received, 0% packet loss

# Очистка
docker rm -f app-a app-b
docker network rm prod-vlan
```

Требования: порт коммутатора в promiscuous-режиме (или VLAN-trunk), одинаковая подсеть и parent на обоих хостах, отсутствие конфликтов IP. `--gateway` — шлюз физической сети VLAN 100, а не IP хоста.

### Сценарий 2: Ручной VXLAN между двумя хостами

```bash
# На обоих хостах (подставьте IP партнёра)
# Хост A: 10.0.0.10, Хост B: 10.0.0.11

# Bridge поверх VXLAN
sudo ip link add br-vxlan type bridge
sudo ip link set br-vxlan up

# VXLAN-интерфейс: VNI 100, UDP 4789, MTU 1450 (overhead VXLAN — 50 байт)
# Multicast-режим (group) требует поддержки multicast в underlay;
# в большинстве ЦОД надёжнее unicast: remote 10.0.0.11 (на Хосте B — remote 10.0.0.10)
sudo ip link add vxlan100 type vxlan id 100 \
  dev eth0 dstport 4789 group 239.1.1.1 ttl 25 mtu 1450
sudo ip link set vxlan100 master br-vxlan
sudo ip link set vxlan100 up

# IP — только на bridge: vxlan100 — slave моста, отдельный IP ему не нужен
sudo ip addr add 10.10.100.1/24 dev br-vxlan

# Docker-сеть на существующем bridge.
# --subnet и --gateway обязаны совпадать с IP bridge: без них демон выделит
# подсеть из default-address-pools, и на двух хостах они могут разойтись
docker network create -d bridge \
  --subnet 10.10.100.0/24 \
  --gateway 10.10.100.1 \
  -o com.docker.network.bridge.name=br-vxlan \
  -o com.docker.network.bridge.enable_ip_masquerade=false \
  vxlan-net

# Контейнеры
# Хост A:
docker run -d --name app-a --network vxlan-net --ip 10.10.100.11 nginx:alpine
# Хост B:
docker run -d --name app-b --network vxlan-net --ip 10.10.100.12 nginx:alpine

# Валидация
ip -d link show vxlan100
# → vxlan100: <...> mtu 1450 ... vxlan id 100 ... dstport 4789 ...
docker exec app-a ping -c 2 10.10.100.12
# → 2 packets transmitted, 2 received, 0% packet loss

# Очистка
docker rm -f app-a app-b
docker network rm vxlan-net
sudo ip link del br-vxlan   # slave vxlan100 удаляется вместе с мостом
```

Внимание: ручной VXLAN требует настройки на каждом хосте и не управляется Docker — пересоздание сети Docker не перенастраивает туннель. `enable_ip_masquerade=false` отключает NAT для сети: контейнеры сохраняют исходные IP, но выход в интернет через этот bridge отсутствует без дополнительных маршрутов.

### Сценарий 3: VPN-мост через WireGuard

```bash
# Хосты соединены WireGuard (wg0), подсети:
# Хост A: docker-net 172.30.1.0/24, wg-пир 10.8.0.2
# Хост B: docker-net 172.30.2.0/24, wg-пир 10.8.0.1

# На Хосте A — маршрут к подсети Хоста B через туннель
sudo ip route add 172.30.2.0/24 via 10.8.0.2 dev wg0

# На Хосте B — симметрично
sudo ip route add 172.30.1.0/24 via 10.8.0.1 dev wg0

# Включение маршрутизации (если не включено)
sudo sysctl -w net.ipv4.ip_forward=1

# Валидация: туннель и связность контейнеров
sudo wg show
# → interface: wg0
# →   listening port: 51820
# →   latest handshake: X seconds ago
docker exec app-a ping -c 2 172.30.2.10
# → 2 packets transmitted, 2 received, 0% packet loss

# Очистка
sudo ip route del 172.30.2.0/24 via 10.8.0.2 dev wg0   # на Хосте A
sudo ip route del 172.30.1.0/24 via 10.8.0.1 dev wg0   # на Хосте B
sudo wg-quick down wg0                                    # если туннель поднят через wg-quick
```

Для персистентности маршрутов — в `/etc/network/interfaces.d/` или systemd-networkd, иначе маршруты пропадут при перезагрузке.

Особенности VPN-моста:
- **MTU**: overhead WireGuard — ~60 байт, MTU на wg0 — 1420 при физическом MTU 1500; при «зависающих» TCP-сессиях при живом ping проверьте PMTUD и примените MSS Clamping.
- **Masquerade**: правило Docker `-s <подсеть-bridge> ! -o <bridge> -j MASQUERADE` маскарадит трафик контейнеров, уходящий через wg0 — на принимающей стороне виден IP хоста-отправителя, а не контейнера. Для сохранения исходных IP отключите masquerade для сети (`com.docker.network.bridge.enable_ip_masquerade=false`) и добавьте явное разрешение FORWARD.

### Сценарий 4: Сторонний overlay-драйвер (Weave)

```bash
# Установка Weave на каждом хосте (пример)
# Хост A:
sudo weave launch 10.0.0.11   # IP партнёра
# Хост B:
sudo weave launch 10.0.0.10

# Сеть через плагин
docker network create -d weave --name weave-net

# Контейнеры на разных хостах видят друг друга по имени
docker run -d --name app-a --network weave-net --network-alias app my-app
# На Хосте B:
docker run -d --name app-b --network weave-net --network-alias app my-app

# Валидация
docker exec app-a getent hosts app
# → 10.32.0.2   app
```

Weave обеспечивает шифрование трафика и собственный DNS — то, чего нет во встроенных драйверах без Swarm.

**Статус плагина (важно):** компания Weaveworks прекратила деятельность, репозиторий `weaveworks/weave` архивирован 20 июня 2024 и доступен только для чтения; сайт документации docs.weave.works недоступен. Плагин не развивается и не рекомендуется для новых внедрений — перед использованием проверьте активные форки или альтернативы. Учтите также, что большинство современных overlay-решений (Flannel, Calico, Cilium) реализованы как CNI-плагины Kubernetes, а не как драйверы libnetwork Docker, и в чистом Docker без Swarm не работают.

## Устранение неисправностей

| Симптом | Причина | Диагностика |
| :--- | :--- | :--- |
| macvlan-контейнеры на разных хостах не видят друг друга | разные VLAN/подсети или promiscuous выключен на порту | `ip link show parent`; проверка VLAN на коммутаторе |
| Хост не пингует macvlan-контейнер | хост не видит macvlan без shim-интерфейса | создать macvlan-shim (`ip link add ... type macvlan mode bridge`) |
| Ручной VXLAN не проходит трафик | разный VNI, нет маршрута, MTU | `ip -d link show vxlan*`; `ping -M do -s 1400` |
| VPN-мост: контейнеры не пингуют | нет маршрута к подсети партнёра или `ip_forward=0` | `ip route`; `sysctl net.ipv4.ip_forward` |
| Сторонний драйвер: `network driver not found` | плагин не зарегистрирован | `docker info --format '{{json .Plugins}}'` |
| Overlay без Swarm: ошибка создания | `overlay` требует Swarm | `docker info --format '{{.Swarm.LocalNodeState}}'` |
| VXLAN: multicast не проходит | underlay без multicast (IGMP/multicast routing) | переключитесь на unicast: `remote <IP партнёра>` |
| VXLAN/WireGuard: ping проходит, TCP виснет | сломана PMTUD (блокируются ICMP), MTU туннеля меньше 1500 | `ip link show vxlan100 \| grep mtu`; MSS Clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o <iface> -j TCPMSS --clamp-mss-to-pmtu` |
| VPN-мост: связь есть, но приложение видит чужой source IP | masquerade Docker для трафика через wg0 | `iptables -t nat -S POSTROUTING` (или `nft list ruleset`); отключите masquerade для сети |

## Рекомендации

- **Если есть Swarm — используйте `overlay`**; ручные схемы оправданы только без оркестратора. На Engine 29.x с nftables-бэкендом overlay-сети не поддерживаются — для Swarm оставайтесь на iptables-бэкенде (см. [интеграцию с iptables](./troubleshooting/iptables_integration.md)).
- **macvlan multi-host — самый простой путь** при общем L2-сегменте: контейнеры как полноценные узлы сети, без туннелей и плагинов.
- **Ручной VXLAN — только при полном контроле** и понимании, что Docker не управляет туннелем; персистентность — на администраторе.
- **VPN-мост — когда хосты в разных подсетях** и L2-сегмент общий недоступен; маршрутизация через WireGuard надёжна и шифрует трафик.
- **Сторонний overlay — когда нужны шифрование или политики** без Swarm; проверяйте статус поддержки плагина.
- **Планируйте IP-адресацию заранее** — при multi-host без централизованного IPAM конфликты адресов обнаруживаются только по факту потери связи. В Swarm параметры IPAM синхронизируются через config-only сети с `--config-from` (см. [справочник CLI](./cli.md)); в standalone-режиме сети создаются на каждом хосте вручную с идентичными `--subnet`, `--gateway` и `parent`.
- **Документируйте схему** — в инвентаризации хоста фиксируйте тип многохостовой сети, VNI/VLAN, подсети и IP партнёров.

## Дополнительная информация

### Смежные темы

- [Обзор сетевой модели Docker](./docker_network.md) — драйверы и их ограничения.
- [Драйвер macvlan](./drivers/macvlan.md) — L2 multi-host, режимы, promiscuous.
- [Драйвер ipvlan](./drivers/ipvlan.md) — L3-альтернатива macvlan.
- [Драйвер overlay](./drivers/overlay.md) — встроенный многохостовый драйвер (требует Swarm).
- [Docker Swarm: сетевое взаимодействие](../../Docker_swarm/swarm_networking.md) — routing mesh, overlay в Swarm.
- [WireGuard](../../Vpn/wireguard.md) — VPN-мост между хостами.
- [VPN в контейнерах](../../Networking/Tunnels/vpn_in_containers.md) — WireGuard/OpenVPN в Docker.
- [VXLAN](../../Networking/Tunnels/vxlan.md) — механика инкапсуляции.
- [libnetwork и плагины](./docker_network_plugins.md) — сторонние драйверы.
- [IPAM и планирование ёмкости](./docker_network_ipam_scale.md) — `default-address-pools`, пересечения подсетей, config-only сети.
- [Справочник CLI](./cli.md) — config-only сети с `--config-from`, Go-шаблоны `inspect`.
- [ip tunnel (iproute2)](../../Linux/Networking/Tools/iproute2/ip_tunnel.md) — VXLAN multi-host с VLAN filtering, MSS Clamping, очистка туннелей.
- [MTU и VPN](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — overhead туннелей и расчёт MTU.

### Ограничения

- Ручной VXLAN и VPN-мост не управляются Docker: пересоздание сети или перезагрузка хоста требует перенастройки туннеля/маршрутов.
- macvlan multi-host требует поддержки promiscuous-режима на порту коммутатора; в облачных и Wi-Fi-сетях часто недоступен.
- Сторонние overlay-драйверы имеют собственный жизненный цикл; совместимость с версией Engine проверяется перед внедрением.
- Weave Net не развивается: репозиторий архивирован 20.06.2024 (read-only), документация недоступна; сценарий 4 приведён для понимания механизма стороннего драйвера, а не как рекомендация к внедрению.
