# ip tunnel: Управление туннелями

## Определения

**Сетевой туннель** — метод инкапсуляции пакетов одного протокола в пакеты другого для передачи через промежуточную сеть.

**`ip tunnel`** — команда `iproute2` для создания и управления туннелями (GRE, IPIP, SIT, VXLAN).

## Базовые концепции

### Типы туннелей в Linux

| Тип | Режим | Протокол | Внутренний/Внешний | Overhead |
|-----|-------|----------|-------------------|----------|
| **GRE** | `gre` | 47 | Любой/IPv4 | ~24 байта |
| **GRETAP** | `gretap` | 47 | Ethernet/IPv4 | ~42 байта |
| **IPIP** | `ipip` | 4 | IPv4/IPv4 | ~20 байт |
| **SIT** | `sit` | 41 | IPv6/IPv4 | ~20 байт |
| **VXLAN** | `vxlan` | UDP 4789 | Ethernet/UDP/IPv4 | ~50 байт |
| **IP6GRE** | `ip6gre` | 47 | Любой/IPv6 | ~24 байта |
| **IP6IP6** | `ip6tnl` | 41 | IPv6/IPv6 | ~40 байт |

### Общие параметры

* **local** — локальный IP-адрес туннеля
* **remote** — удалённый IP-адрес туннеля
* **dev** — физический интерфейс для привязки
* **ttl** — время жизни пакетов (по умолчанию 64)
* **key** — идентификатор туннеля (GRE)

## Практические сценарии

### GRE (Generic Routing Encapsulation)

Point-to-point туннель для любых протоколов.

```bash
# Создать GRE-туннель
sudo ip link add gre1 type gre remote 203.0.113.2 local 198.51.100.1 ttl 255 key 100

# Включить интерфейс
sudo ip link set gre1 up

# Назначить IP-адрес
sudo ip address add 10.0.0.1/30 dev gre1

# Добавить маршрут
sudo ip route add 10.0.1.0/24 dev gre1
```

> **Примечание:** Для multipoint GRE (mGRE) используется `mode gretap` или `mode gre` без `remote`.

### IPIP (IP-in-IP)

Инкапсуляция IPv4 в IPv4.

```bash
# Создать IPIP-туннель
sudo ip tunnel add ipip1 mode ipip remote 203.0.113.2 local 198.51.100.1

# Включить и настроить
sudo ip link set ipip1 up
sudo ip address add 10.0.0.1/30 dev ipip1
```

### SIT (IPv6-over-IPv4)

Туннель для передачи IPv6 через IPv4-инфраструктуру.

```bash
# Создать SIT-туннель
sudo ip tunnel add sit1 mode sit remote 203.0.113.2 local 198.51.100.1

# Включить и назначить IPv6
sudo ip link set sit1 up
sudo ip -6 address add 2001:db8::1/64 dev sit1
```

### VXLAN (Virtual Extensible LAN)

L2-оверлей поверх L3-сети.

```bash
# Unicast VXLAN (точка-точка)
sudo ip link add vxlan0 type vxlan id 100 remote 192.0.2.2 local 192.0.2.1 dev eth0 dstport 4789

# Multicast VXLAN (многоточечный)
sudo ip link add vxlan0 type vxlan id 100 group 239.1.1.1 dev eth0 dstport 4789

# Включить интерфейс
sudo ip link set vxlan0 up
```

### GRETAP (L2-туннель)

Инкапсуляция Ethernet-кадров в GRE.

```bash
# Создать GRETAP-туннель
sudo ip link add gretap1 type gretap remote 203.0.113.2 local 198.51.100.1

# Включить и добавить в мост
sudo ip link set gretap1 up
sudo ip link set gretap1 master br0
```

### Управление туннелями

```bash
# Просмотр всех туннелей
ip tunnel show
ip -d link show type gre
ip -d link show type vxlan

# Изменить параметры
sudo ip tunnel change ipip1 ttl 128

# Удалить туннель
sudo ip link del gre1
sudo ip tunnel del ipip1
```

### MTU и фрагментация

Туннели уменьшают эффективный MTU из-за оверхеда:

```bash
# GRE: 1500 - 24 = 1476
sudo ip link set gre1 mtu 1476

# IPIP/SIT: 1500 - 20 = 1480
sudo ip link set ipip1 mtu 1480

# VXLAN: 1500 - 50 = 1450
sudo ip link set vxlan0 mtu 1450
```

> **Важно:** Включить Path MTU Discovery: `sysctl -w net.ipv4.ip_no_pmtu_disc=0`

## Дополнительная информация

### Связанные темы

* **[GRE](../../../../Networking/Tunnels/gre.md)** — детальное описание GRE
* **[IPIP и SIT](../../../../Networking/Tunnels/ipip_and_sit.md)** — туннели IP-in-IP и 6in4
* **[VXLAN](../../../../Networking/Tunnels/vxlan.md)** — виртуальные расширяемые LAN
* **[Туннелирование](../../../../Networking/Tunnels/tunneling_overview.md)** — общие концепции

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Туннель не поднимается | Нет маршрута до remote | Проверить `ip route get <remote>` |
| Пакеты не проходят | MTU слишком большой | Уменьшить MTU туннеля |
| Высокая задержка | Фрагментация | Включить PMTUD, уменьшить MSS |
| VXLAN не работает | Порт заблокирован фаерволом | Открыть UDP 4789 |
