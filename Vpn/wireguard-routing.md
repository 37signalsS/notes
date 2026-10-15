# WireGuard: расширенная маршрутизация

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x); нативная поддержка в ядре Linux 5.6+. Протокол WireGuard v1.

## Определения

**Crypto-key routing** — модель WireGuard: маршрут определяется не таблицей ядра, а списком `AllowedIPs` каждого пира (криптографическая адресация). **Table** — опция конфигурации `wg-quick`, управляющая записью маршрутов (`auto` — main, `N` — конкретная таблица, `off` — не трогать таблицы). **fwmark (firewall mark)** — целочисленная метка, проставляемая Netfilter на пакеты и используемая `ip rule` для выбора таблицы маршрутизации. **PBR (Policy-Based Routing)** — маршрутизация по правилам, а не по адресу назначения. **ECMP (Equal-Cost Multi-Path)** — балансировка потоков по нескольким маршрутам одинаковой стоимости. **FRR (FRRouting)** — набор демонов динамической маршрутизации (OSPF, BGP, IS-IS) для Linux.

## Основные концепции

### Как `wg-quick` управляет маршрутами

При подъёме интерфейса `wg-quick` добавляет в main-таблицу маршрут для каждой сети из `AllowedIPs` (назначение → `dev wg0`) и снимает их при остановке. Для нетривиальных схем этого недостаточно:

- **`Table = off`** — `wg-quick` не трогает таблицы вообще; маршруты настраиваются вручную (например, через `systemd-networkd` или PBR). Рекомендуется, если с одной стороны — интернет-default, а с другой — VPN-default, или несколько интерфейсов WireGuard.
- **`Table = 100`** — все маршруты пишутся в отдельную таблицу 100; выбор между main и 100 выполняется `ip rule`.
- **`fwmark`** — `Table = off` и явный `fwmark = 0xca6c` позволяют ставить метку и разводить трафик по правилам, минуя проблему рекурсии маршрутов.

Пакет, отправленный в `wg0`, не обязан «возвращаться» тем же путём: асимметрия маршрутов ломается на сетях со strict RPF (см. [Асимметричная маршрутизация](../Networking/Concepts/asymmetric_routing.md)).

### Динамическая маршрутизация поверх WireGuard

WireGuard — чистый unicast-L3 туннель без multicast, поэтому **OSPF «из коробки» не работает** (в отличие от GRE, см. [GRE vs WireGuard](../Networking/Tunnels/gre/gre_vs_wireguard.md)). Пути обхода:

- **BGP** — работает, т.к. это unicast TCP: достаточно, чтобы пиры «видели» друг друга (multihop eBGP/iBGP через loopback). Канонический выбор для site-to-site с несколькими концентраторами и ECMP.
- **OSPF** — требует point-to-point adjacency: либо OSPF в режиме `network point-to-point` между двумя WG-концами (link между адресами туннеля), либо через BGP-как-транспорт. На практике BGP проще и предсказуемее.
- **FRR** запускается на концентраторе и обменивается маршрутами через туннель, в то время как сам WireGuard остаётся «кабелем».

Шаблон для IPsec с FRR уже описан — [IPsec: динамическая маршрутизация](../Networking/Tunnels/ipsec/ipsec_routing.md); здесь тот же приём для WireGuard.

### Множественные интерфейсы и сегментация

Для сегментации (разные клиенты/подсети/уровни доверия) применяется несколько интерфейсов с разными таблицами. Лимит пиров на интерфейс высок (ядро — до 2^20, `wireguard-go` — до 2^16), поэтому делить флот заставляет не он, а управляемость и изоляция уровней доверия (см. [wireguard-ha.md](./wireguard-ha.md)).

## Практические сценарии

### 1. Split tunnel по правилам (PBR + fwmark)

**Задача:** трафик в интернет — напрямую, в корпоративную сеть — через VPN, а «служебный» диапазон — не через VPN ни при каких условиях.

```ini
# wg0.conf
[Interface]
PrivateKey = <private_key>
Address = 10.0.0.2/24
Table = off
# Метка для VPN-трафика (произвольная)
PostUp = ip rule add fwmark 0xca6c table 100 pref 50
PostDown = ip rule del fwmark 0xca6c table 100 pref 50

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 10.0.0.0/24, 10.20.0.0/16
PersistentKeepalive = 25
```

```bash
# Вручную: маршрут корпоративных сетей в отдельную таблицу
ip route add 10.0.0.0/24 dev wg0 table 100
ip route add 10.20.0.0/16 dev wg0 table 100
ip route add default via 192.168.1.1 dev eth0 table 100

# Правило выбора таблицы для пакетов, помеченных fwmark (из PostUp)
ip rule add fwmark 0xca6c table 100 pref 50

# Netfilter ставит метку на новые соединения к корпоративным сетям
nft add rule inet filter output ip daddr { 10.0.0.0/24, 10.20.0.0/16 } \
  meta mark set 0xca6c
```

**Проверка:**
```bash
ip rule show
# → 50:  from all fwmark 0xca6c lookup 100
ip route get 10.20.0.7
# → 10.20.0.7 dev wg0 src 10.0.0.2 table 100 ...
ip route get 8.8.8.8
# → 8.8.8.8 via 192.168.1.1 dev eth0 (default main) ...
```

Общая механика правил и таблиц — [PBR (ip rule)](../Linux/Networking/Tools/iproute2/ip_rule_pbr.md).

### 2. Site-to-site с BGP поверх WireGuard (ECMP)

**Задача:** два концентратора, общий анонс подсетей, отказоустойчивость за счёт двух путей.

FRR на каждом концентраторе:
```bash
sudo apt install frr
sudo sed -i 's/bgpd=no/bgpd=yes/' /etc/frr/daemons
sudo systemctl enable --now frr
```

```text
# /etc/frr/frr.conf (концентратор 1: 10.0.0.1, анонс 192.168.1.0/24)
frr defaults traditional
hostname vpn-hub1
router bgp 65001
  bgp router-id 10.0.0.1
  neighbor 10.0.0.2 remote-as 65001   # пир через wg0
  neighbor 10.0.0.3 remote-as 65001   # второй концентратор
  address-family ipv4 unicast
    network 192.168.1.0/24
    neighbor 10.0.0.2 soft-reconfiguration inbound
    neighbor 10.0.0.3 soft-reconfiguration inbound
exit
```

Клиенты получают два маршрута к удалённым подсетям (ECMP):
```bash
ip route show
# → 192.168.2.0/24 proto bgp metric 20
#        nexthop via 10.0.0.2 dev wg0 weight 1
#        nexthop via 10.0.0.3 dev wg0 weight 1
```

При отказе одного концентратора FRR снимает маршрут, трафик переходит на второй — это и есть предсказуемый путь «масштабирования WG» из [wireguard-ha.md](./wireguard-ha.md)). База BGP: [BGP](../Networking/Protocols/bgp.md).

### 3. OSPF point-to-point через WireGuard (альтернатива BGP)

**Задача:** для пары «офис-офис», когда BGP избыточен.

```text
# /etc/frr/frr.conf — сосед по туннелю 10.0.0.2/30
router ospf
  ospf router-id 10.0.0.1
  network 10.0.0.0/30 area 0
  network 192.168.1.0/24 area 0
  redistribute static
exit
```

OSPF поверх WG корректен только между точками туннеля (unicast hello на соседа), без мультикаста. Предпочтительнее BGP при числе узлов >2 (нет избыточности типа hub-and-spoke без route-reflector). Схема и firewall-правила — по аналогии с [IPsec-вариантом](../Networking/Tunnels/ipsec/ipsec_routing.md).

### 4. Несколько интерфейсов с независимыми таблицами

```ini
# wg0 — клиенты remote access (таблица auto)
# wg1 — site-to-site офиса (таблица off)
[Interface]
PrivateKey = <private_key_site>
Address = 10.30.0.1/24
ListenPort = 51821
Table = off
PostUp = ip route add 192.168.30.0/24 dev wg1 table 101
PostDown = ip route del 192.168.30.0/24 dev wg1 table 101
```

Изоляция таблиц (100/101/102) позволяет нескольким туннелям и default-маршрутам сосуществовать без взаимного вытеснения.

### 5. Диагностика маршрутизации

```bash
# Актуальный путь до ресурса
ip route get 192.168.30.5
# → 192.168.30.5 dev wg1 src 10.30.0.1 table 101 ... (если статья в 101)

# Правила и таблицы
ip rule show
ip route show table 101
ip route show table all | grep -E "wg0|wg1"

# Что WireGuard считает маршрутами пира
sudo wg show wg0 allowed-ips

# Логи FRR
journalctl -u frr -f | grep BGP
sudo vtysh -c "show ip bgp summary"
```

## Операции и команды

### Основные команды wg-quick

| Команда | Описание |
|---------|----------|
| `sudo wg-quick up wg0` | Поднять интерфейс WireGuard |
| `sudo wg-quick down wg0` | Опустить интерфейс WireGuard |
| `sudo wg-quick save wg0` | Сохранить текущее состояние в конфиг |
| `sudo wg show` | Показать состояние интерфейса и пиров |
| `sudo wg show wg0 transfer` | Показать статистику передачи данных |

### Команды маршрутизации и правил

| Команда | Описание |
|---------|----------|
| `ip rule show` | Показать правила политики маршрутизации |
| `ip route show table <N>` | Показать маршруты в таблице N |
| `ip route get <address>` | Показать путь до конкретного адреса |
| `nft add rule ...` | Добавить правило в nftables для маркировки пакетов |
| `journalctl -u frr -f` | Следить за логами FRRouting в реальном времени |

### Команды FRRouting

| Команда | Описание |
|---------|----------|
| `sudo vtysh -c "show ip bgp summary"` | Показать сводку по BGP-пирам |
| `sudo vtysh -c "show ip ospf neighbor"` | Показать OSPF-соседей |
| `sudo vtysh -c "show ip route bgp"` | Показать маршруты, полученные через BGP |
| `sudo vtysh -c "show ip route ospf"` | Показать маршруты, полученные через OSPF |

## Troubleshooting

### Типичные проблемы и решения

| Симптом | Возможная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| Маршруты не добавляются при `Table = off` | Ожидаемое поведение | `wg show` показывает, что интерфейс активен | Настроить маршруты вручную через `ip route` или использовать PBR |
| Трафик не идет через ожидаемый туннель | Неправильная таблица маршрутизации или правила | `ip rule show` и `ip route show table all` | Проверить приоритеты правил и номера таблиц |
| asymметричная маршрутизация вызывает проблемы с RPF | Strict Reverse Path Forwarding на интерфейсах | `sysctl net.ipv4.conf.all.rp_filter` | Отключить strict режим или настроить альтернативный путь возврата |
| BGP/OSPF не устанавливает соседство | Блокировка портов или неправильная конфигурация FRR | `vtysh -c "show ip bgp summary"` или `vtysh -c "show ip ospf neighbor"` | Проверить конфигурацию FRR и открыть необходимые порты (TCP 179 для BGP, протокол 89 для OSPF) |
| Маршруты не redistributются между протоколами | Отсутствие команды redistribute в конфигурации FRR | `vtysh -c "show running-config"` | Добавить соответствующие команды redistribute в конфигурацию FRR |

### Специфические сценарии диагностики

**Проверка работы PBR с fwmark:**
```bash
# Создать тестовое соединение
curl -v http://10.20.0.1
# Проверить, что пакеты помечены правильной меткой
nft list chain inet filter output
# Проверить, что используется правильная таблица маршрутизации
ip rule show
ip route get 10.20.0.1
```

**Проверка ECMP:**
```bash
# Убедиться, что есть несколько одинаковых маршрутов
ip route show 192.168.2.0/24
# Проверить статистику распределения нагрузки
ip -s route show 192.168.2.0/24
```

## Best Practices

### Конфигурация и безопасность

1. **Использование Table и fwmark для сложной маршрутизации:**
   - Для простых сценариев достаточно `Table = auto` (по умолчанию)
   - Для PBR и изоляции трафика используйте комбинацию `Table = off` + явные `ip rule` и `fwmark`
   - Всегда очищайте правила в `PostDown`, чтобы избежать накопления устаревших правил

2. **Изоляция трафика через несколько интерфейсов:**
   - При необходимости完全 изолировать разные типы трафика (например, remote access и site-to-site) используйте отдельные интерфейсы WireGuard
   - Назначайте каждому интерфейсу свою таблицу маршрутизации для предотвращения конфликтов

3. **Динамическая маршрутизация:**
   - Для site-to-site сценариев с несколькими концентраторами предпочитайте BGP поверх WireGuard
   - Для простых пар «офис-офис» OSPF point-to-point может быть достаточным
   - Всегда проверяйте совместимость версий FRR и WireGuard-инструментов

4. **Мониторинг и отладка:**
   - Регулярно проверяйте `wg show` для мониторинга handshake иtransfer
   - Используйте `ip rule show` и `ip route show table all` для отладки сложной маршрутизации
   - Настройте логирование FRR для отслеживания изменений в топологии

### Производительность и надежность

1. **MTU и фрагментация:**
   - При использовании динамической маршрутизации учитывайте дополнительный overhead от протоколов маршрутизации
   - Проверяйте MTU на всем пути: клиент → WireGuard → динамический протокол → назначение

2. **Отказоустойчивость:**
   - При использовании BGP поверх WireGuard настройте適当ные hold-timers для быстрого обнаружения сбоев
   - Рассмотрите использование BGP multipath для автоматической балансировки нагрузки

3. **Масштабирование:**
   - Для больших флотов клиентов рассмотрите архитектуру с несколькими концентраторами
   - Используйте BGP любыйcast или DNS-балансировку для распределения нагрузки между концентраторами

## Дополнительная информация

- **[PBR и ip rule](../Linux/Networking/Tools/iproute2/ip_rule_pbr.md)** — правила выбора таблиц, fwmark, сценарии
- **[IPsec: динамическая маршрутизация](../Networking/Tunnels/ipsec/ipsec_routing.md)** — тот же FRR-подход на базе route-based IPsec
- **[Асимметричная маршрутизация](../Networking/Concepts/asymmetric_routing.md)** — почему RPF ломает split tunnel и как это чинить
- **[WireGuard](../Vpn/wireguard.md)** — основная информация о протоколе WireGuard
- **[WireGuard: высокая доступность](../Vpn/wireguard-ha.md)** — схемы резервирования и масштабирования концентраторов
- **[WireGuard: управление ключами](../Vpn/wireguard-key-management.md)** — инвентаризация и ротация ключей для больших сетей