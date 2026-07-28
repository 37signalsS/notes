# VXLAN — виртуальная расширяемая локальная сеть

## Определения

**VXLAN (Virtual Extensible LAN)** — протокол туннелирования для создания оверлейных сетей в крупных виртуализированных средах и облачных дата-центрах ([RFC 7348](https://datatracker.ietf.org/doc/html/rfc7348)).

**Ключевые характеристики:**

- **Уровень:** L2 (инкапсуляция Ethernet в UDP)
- **Транспорт:** UDP порт `4789` (IANA), `8472` (Linux по умолчанию до стандартизации)
- **Идентификатор:** VNI (24 бита) — до 16 миллионов изолированных сетей
- **Шифрование:** Отсутствует (традиционно используется поверх [IPsec](./ipsec/ipsec.md) или MACsec)

**VTEP (VXLAN Tunnel End Point)** — логический интерфейс (точка), выполняющая инкапсуляцию (ingress) и декапсуляцию (egress) VXLAN-трафика.

## Основные концепции

### Формат заголовка VXLAN (8 байт)

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|R|R|R|R|I|R|R|R|            Reserved                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                VXLAN Network Identifier (VNI) |   Reserved    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

- **I-бит:** Должен быть равен 1 (указывает на корректный VNI).
- **VNI (24 бита):** Уникальный идентификатор виртуальной сети.

### Инкапсуляция и Overhead

```
[Внешний Ethernet][Внешний IP][UDP][VXLAN Header][Внутренний Ethernet Frame]
```

**Размер оверхеда (Overhead):** ~50 байт (в IPv4).
- Внешний Ethernet: 14 байт
- IPv4 Header: 20 байт
- UDP Header: 8 байт
- VXLAN Header: 8 байт

### Типы VNI

1.  **L2-VNI (Bridging):** Используется для расширения L2-домена между разными хостами. Ведёт себя как виртуальный коммутатор.
2.  **L3-VNI (Routing):** Используется в архитектуре **IRB (Integrated Routing and Bridging)** для передачи трафика между разными подсетями внутри оверлея.

### Плоскость управления (Control Plane)

В отличие от Data Plane (инкапсуляция UDP), Control Plane определяет, как VTEP узнают о расположении MAC/IP адресов.

- **Flood and Learn (Multicast):** Традиционный метод. Использует multicast-группы для рассылки BUM-трафика (Broadcast, Unknown Unicast, Multicast) и обучения.
- **Static FDB:** Ручное прописывание таблиц пересылки. Подходит для простых топологий точка-точка.
- **BGP EVPN (Ethernet VPN):** Современный стандарт (RFC 7432). Использует протокол BGP для обмена информацией о MAC и IP адресах. Позволяет избежать широковещательного шторма и поддерживает многопутевую передачу (ECMP).

## Практические сценарии в Linux

### 1. Unicast (точка — точка)

Самый простой способ соединить два хоста без использования Multicast.

```bash
# Хост A (192.168.1.10)
ip link add vxlan10 type vxlan id 100 remote 192.168.1.20 local 192.168.1.10 dev eth0 dstport 4789
ip link set vxlan10 up
ip address add 10.0.0.1/24 dev vxlan10

# Хост B (192.168.1.20)
ip link add vxlan10 type vxlan id 100 remote 192.168.1.10 local 192.168.1.20 dev eth0 dstport 4789
ip link set vxlan10 up
ip address add 10.0.0.2/24 dev vxlan10
```

### 2. Multicast (динамическое обучение)

VTEP подписываются на multicast-группу для обнаружения друг друга.

```bash
# На всех участниках
ip link add vxlan10 type vxlan id 100 group 239.1.1.1 dev eth0 dstport 4789
ip link set vxlan10 up
```

### 3. VXLAN + Bridge (L2-сегмент)

Обычно VXLAN-интерфейс добавляется в Bridge для объединения с виртуальными машинами или контейнерами.

```bash
ip link add br-vxlan type bridge
ip link set vxlan10 master br-vxlan
ip link set veth-container master br-vxlan
```

## Эксплуатация и тюнинг

### Аппаратное ускорение (Offload)

Современные сетевые карты (NIC) могут выполнять инкапсуляцию, расчет контрольных сумм и сегментацию трафика (TSO/LRO) аппаратно.

**Проверка:**
```bash
ethtool -k eth0 | grep vxlan
# → tx-vxlan-segmentation: on
# → tx-checksum-vxlan-non-generic: on
```

### Настройка MTU

Инкапсуляция добавляет 50 байт оверхеда, что критично при стандартном MTU 1500.

1.  **Режим Jumbo Frames (Рекомендуется):** Установить MTU 9000-9216 на физических интерфейсах (Underlay). Это позволит оверлею использовать честные 1500 байт.
2.  **Уменьшение MTU оверлея:** Если Underlay ограничен 1500 байтами, установите на VXLAN-интерфейсах MTU **1450**.
    - В некоторых облаках (например, при двойной инкапсуляции) может потребоваться **1442** или даже **1400**.

```bash
ip link set dev vxlan10 mtu 1450
```

### Диагностика

```bash
# Просмотр таблицы FDB (MAC -> Remote VTEP IP)
bridge fdb show dev vxlan10

# Детальная информация об интерфейсе
ip -d link show vxlan10

# Мониторинг VXLAN трафика (внешние пакеты)
tcpdump -ni eth0 udp port 4789

# Мониторинг трафика внутри туннеля
tcpdump -ni vxlan10
```

## Сравнение технологий

| Протокол | Overhead | Масштаб | Транспорт | Control Plane |
| :--- | :--- | :--- | :--- | :--- |
| **VXLAN** | 50 B | 16M VNI | UDP 4789 | Flood-n-Learn / BGP EVPN |
| **Geneve** | 50+ B | 16M VNI | UDP 6081 | Гибкий (TLV), стандарт в OVN |
| **NVGRE** | 42 B | 16M VSID | GRE (IP 47) | Microsoft (Hyper-V) |
| **GRETAP** | 42 B | < 4096 | GRE | Статический / Простой L2 |

## Ограничения и риски

- **Проблема MTU:** Неправильная настройка ведет к фрагментации или полной потере пакетов (особенно при TCP/TLS).
- **Отсутствие шифрования:** Трафик внутри Underlay передается в открытом виде.
- **Нагрузка на CPU:** Без аппаратного ускорения инкапсуляция может потреблять значительные ресурсы CPU при высоком PPS (Packets Per Second).

## См. также

- [Обзор туннелирования](./tunneling_overview.md)
- [BGP и EVPN](../Protocols/bgp.md)
- [Сетевой драйвер Overlay в Docker](../../Docker/Docker_network/drivers/overlay.md)
- [Настройка SDN в Proxmox](../../Proxmox/proxmox_networking.md)
- [Проблемы MTU и фрагментация](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)
