# Настройка VLAN в Linux и диагностика

## Настройка VLAN в Linux

### Создание VLAN-интерфейсов

```bash
# Создать VLAN 10 на eth0
ip link add link eth0 name eth0.10 type vlan id 10

# Создать VLAN 20 на eth0
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

### Настройка через NetworkManager (nmtui/nmcli)

```bash
nmcli connection add type vlan ifname enp0s3.20 dev enp0s3 id 20
nmcli connection modify enp0s3.20 ipv4.addresses 192.168.20.1/24
nmcli connection modify enp0s3.20 ipv4.method manual
nmcli connection up enp0s3.20
```

### Постоянная конфигурация (Netplan, Ubuntu)

**Полная документация:** **[Настройка Netplan](../../Linux/Networking/Settings/Persistent_Network/index.md#3-ubuntu-1710-netplan)** — примеры bonding, VLAN, маршрутов и DNS.

```yaml
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

---

## Диагностика VLAN

### Проверка конфигурации

```bash
# Показать VLAN-интерфейсы
ip -d link show | grep vlan

# Проверка статистики
ip -s link show eth0.10

# tcpdump для отладки тегов
tcpdump -i eth0 -e vlan
tcpdump -i eth0 'vlan[0:2] & 0x0fff = 10'  # Только VLAN 10
```

### Типичные проблемы

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| **Native VLAN mismatch** | Потеря пакетов на trunk | Убедиться, что native VLAN совпадает на обоих концах |
| **VLAN не разрешён на trunk** | Трафик не проходит | Добавить VLAN в allowed list на trunk-порту |
| **Отсутствие L3-маршрутизации** | Нет связи между VLAN | Настроить inter-VLAN routing на маршрутизаторе/L3-коммутаторе |

---

## MTU и VLAN

**Вопрос:** Требуется ли изменять MTU при включении VLAN tagging?

**Ответ:** **Нет, не требуется.**

**Обоснование:**

Стандартный Ethernet-кадр:
- 14 байт — заголовок Ethernet
- до 1500 байт — данные
- 4 байта — CRC32 (контрольная сумма)
- **Итого:** 1518 байт

С тегом 802.1Q добавляется 4 байта → **1522 байта**.

**Почему не нужно менять MTU:**

- Современные коммутаторы и сетевые карты по умолчанию поддерживают **baby giant frames** (1522 байта)
- MTU относится к **IP-уровню** (L3) и не включает заголовок Ethernet (L2)
- VLAN тег добавляется на L2 и не влияет на расчёт MTU для IP-пакетов

**Когда может потребоваться настройка:**

- Старое оборудование (15+ лет) может не поддерживать кадры >1518 байт
- При использовании **Q-in-Q** (802.1ad, два тега VLAN) → размер кадра 1526 байт
- В специфических сценариях с jumbo frames требуется согласование MTU по всей цепочке

## Связанные документы

- **[VLAN Overview](./vlan_overview.md)** — общая информация о VLAN
- **[Формат кадра 802.1Q](./vlan_8021q_frame.md)** — структура тега
- **[Меж-VLAN маршрутизация](./vlan_inter_vlan_routing.md)** — Router-on-a-Stick
- **[Настройка Netplan](../../Linux/Networking/Settings/Persistent_Network/index.md)** — постоянная конфигурация
- **[QoS](../Concepts/qos.md)** — приоритезация трафика через PCP-биты

## Стандарты

- **IEEE 802.1Q** — стандарт тегирования VLAN
- **IEEE 802.1ad** — Q-in-Q (stacked VLANs)
