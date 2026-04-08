# Настройка VLAN в Linux и диагностика

## Определения

**iproute2** — набор утилит Linux (`ip`, `ss`) для управления сетевыми интерфейсами, маршрутизацией и VLAN.

**Linux Bridge** — программный мост в ядре Linux, объединяющий сетевые интерфейсы в один логический сегмент L2.

**Open vSwitch (OVS)** — программный коммутатор с поддержкой VLAN, trunk, QoS и SDN.

## Базовые концепции

### Принцип настройки VLAN в Linux

VLAN-интерфейсы создаются как сабинтерфейсы физического NIC с указанием `id`. Физический интерфейс должен быть подключён к trunk-порту коммутатора.

Для постоянной конфигурации используются NetworkManager или Netplan.

### MTU и VLAN tagging

Стандартный Ethernet-кадр: 14 байт (заголовок) + до 1500 байт (данные) + 4 байта (CRC32) = **1518 байт**.

С тегом 802.1Q добавляется 4 байта → **1522 байта** (baby giant frame).

**MTU не требуется изменять** при включении VLAN tagging, потому что:
- Современные коммутаторы и NIC поддерживают baby giant frames (1522 байта) по умолчанию
- MTU относится к IP-уровню (L3) и не включает заголовок Ethernet (L2)
- VLAN тег добавляется на L2 и не влияет на расчёт MTU для IP-пакетов

**Исключения:**
- Старое оборудование (15+ лет) может не поддерживать кадры >1518 байт
- **Q-in-Q** (802.1ad, два тега) → кадр 1526 байт
- Jumbo frames требуют согласования MTU по всей цепочке

## Практические сценарии

### Создание VLAN-интерфейсов (iproute2)

Временная настройка — сохраняется до перезагрузки:

```bash
# Создать VLAN-интерфейсы
ip link add link eth0 name eth0.10 type vlan id 10
ip link add link eth0 name eth0.20 type vlan id 20

# Назначить IP-адреса
ip addr add 192.168.10.1/24 dev eth0.10
ip addr add 192.168.20.1/24 dev eth0.20

# Активировать интерфейсы
ip link set eth0.10 up
ip link set eth0.20 up

# Проверка
ip -d link show
```

### Настройка через NetworkManager (nmcli)

Постоянная конфигурация:

```bash
nmcli connection add type vlan ifname enp0s3.20 dev enp0s3 id 20
nmcli connection modify enp0s3.20 ipv4.addresses 192.168.20.1/24
nmcli connection modify enp0s3.20 ipv4.method manual
nmcli connection up enp0s3.20
```

### Постоянная конфигурация (Netplan, Ubuntu)

Подробная документация: **[Настройка Netplan](../../../Linux/Networking/Settings/Persistent_Network/index.md#3-ubuntu-1710-netplan)** — примеры bonding, VLAN, маршрутов и DNS.

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.1/24]
    eth0.20:
      id: 20
      link: eth0
      addresses: [192.168.20.1/24]
```

```bash
sudo netplan apply
```

---

### Диагностика VLAN

#### Проверка конфигурации

```bash
# Показать VLAN-интерфейсы
ip -d link show | grep vlan

# Проверка статистики
ip -s link show eth0.10

# tcpdump для отладки тегов
tcpdump -i eth0 -e vlan
tcpdump -i eth0 'vlan[0:2] & 0x0fff = 10'  # Только VLAN 10
```

#### Типичные проблемы

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| **Native VLAN mismatch** | Потеря пакетов на trunk | Убедиться, что native VLAN совпадает на обоих концах |
| **VLAN не разрешён на trunk** | Трафик не проходит | Добавить VLAN в allowed list на trunk-порту |
| **Отсутствие L3-маршрутизации** | Нет связи между VLAN | Настроить меж-VLAN маршрутизацию на маршрутизаторе/L3-коммутаторе |

## Дополнительная информация

**Стандарты:**
- **IEEE 802.1Q** — стандарт тегирования VLAN
- **IEEE 802.1ad** — Q-in-Q (stacked VLANs, двойное тегирование)

**Смежные темы:**
- **[Формат кадра 802.1Q](./vlan_8021q_frame.md)** — структура тега
- **[Меж-VLAN маршрутизация](./vlan_inter_vlan_routing.md)** — Router-on-a-Stick, сабинтерфейсы
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — trunk-порты
- **[QoS](../../Concepts/qos.md)** — приоритезация трафика через PCP-биты
- **[Настройка Netplan](../../../Linux/Networking/Settings/Persistent_Network/index.md)** — постоянная конфигурация сети
