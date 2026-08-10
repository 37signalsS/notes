# L2 Switching и VLAN: Практические сценарии

## Определения

*   **iproute2** — стандартный пакет утилит для управления сетевым стеком Linux (замена `net-tools`).
*   **Linux Bridge** — подсистема ядра, реализующая виртуальный L2-коммутатор.
*   **VLAN-aware Bridge** — современный режим работы моста, позволяющий управлять тегами на портах без создания множества виртуальных интерфейсов.
*   **Q-in-Q (IEEE 802.1ad)** — метод двойного тегирования (VLAN stacking), используемый для проброса клиентских VLAN через сеть провайдера.

## Базовые концепции

Перед выполнением сценариев изучите теоретическую базу в **[Определения и концепции L2 Switching и VLAN](./definitions_and_concepts.md)**.

### Ключевые принципы настройки в Linux

1.  **Сабинтерфейсы:** Традиционный подход `eth0.10` создаёт виртуальное устройство для каждого тега. Удобно для малого количества VLAN.
2.  **Trunk-порт:** Физический интерфейс хоста должен быть подключён к порту коммутатора в режиме `trunk`.
3.  **MTU и Overhead:** Каждый тег 802.1Q добавляет 4 байта. Для Q-in-Q требуется увеличение MTU физического линка до 1508+ байт, чтобы избежать фрагментации IP-пакетов (стандарт 1500).
4.  **Promiscuous Mode:** Для работы мостов и некоторых конфигураций `macvlan` интерфейс должен принимать все кадры.

## Практические сценарии

### Сценарий 1: Настройка VLAN на уровне хоста

#### Вариант A: iproute2 (Временная настройка)
```bash
# Создание интерфейса VLAN 10 поверх eth0
sudo ip link add link eth0 name eth0.10 type vlan id 10
sudo ip addr add 192.168.10.100/24 dev eth0.10
sudo ip link set eth0.10 up
```

#### Вариант B: systemd-networkd (Персистентная настройка)
Рекомендуется для Debian, Arch, Fedora. Требуется два файла в `/etc/systemd/network/`.

```ini
# 10-vlan10.netdev
[NetDev]
Name=eth0.10
Kind=vlan

[VLAN]
Id=10

# 20-eth0.network (привязка к физическому интерфейсу)
[Match]
Name=eth0

[Network]
VLAN=eth0.10
```

#### Вариант C: Netplan (Ubuntu)
```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  vlans:
    eth0.10:
      id: 10
      link: eth0
      addresses: [192.168.10.100/24]
```

---

### Сценарий 2: Виртуализация (VLAN-aware Bridge)

**Задача:** Создать один мост, который будет работать как Trunk-порт для виртуальных машин, распределяя их по разным VLAN.

```bash
# 1. Создание моста с включенной фильтрацией VLAN
sudo ip link add name br0 type bridge vlan_filtering 1
sudo ip link set eth0 master br0
sudo ip link set br0 up

# 2. Настройка портов моста (eth0 как Trunk для VLAN 10, 20)
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20

# 3. Назначение VLAN для виртуального интерфейса VM (vnet0) как Access-порт
# Трафик от VM (без тега) будет помечаться ID 10 при входе в мост
sudo bridge vlan add dev vnet0 vid 10 pvid untagged
```

---

### Сценарий 3: Q-in-Q (VLAN Stacking)

**Задача:** Пробросить трафик клиента (с его собственными тегами) через VLAN 1000 провайдера.

```bash
# 1. Увеличение MTU на физическом интерфейсе
sudo ip link set dev eth0 mtu 1508

# 2. Создание внешнего (Service) тега
sudo ip link add link eth0 name eth0.1000 type vlan protocol 802.1ad id 1000

# 3. Создание внутреннего (Customer) тега поверх сервисного
sudo ip link add link eth0.1000 name eth0.1000.10 type vlan protocol 802.1Q id 10
sudo ip addr add 10.0.0.1/24 dev eth0.1000.10
```

---

### Сценарий 4: Меж-VLAN маршрутизация (Router-on-a-Stick)

**Задача:** Настроить Linux как шлюз для двух подсетей.

```bash
# Включение пересылки пакетов
sudo sysctl -w net.ipv4.ip_forward=1

# Настройка адресов-шлюзов
sudo ip addr add 192.168.10.1/24 dev eth0.10
sudo ip addr add 192.168.20.1/24 dev eth0.20

# Маскировка трафика (NAT), если нужен выход в интернет через eth1
sudo iptables -t nat -A POSTROUTING -o eth1 -j MASQUERADE
```

---

### Сценарий 5: Диагностика и поиск неисправностей

#### Анализ таблицы MAC-адресов (FDB)
Позволяет увидеть, на каких портах моста находятся конкретные устройства.
```bash
# Просмотр базы данных пересылки (Forwarding Database)
bridge fdb show dev br0
# → 52:54:00:12:34:56 vlan 10 master br0
```

#### Проверка тегов в реальном времени
```bash
# Захват кадров с выводом L2-заголовков (флаг -e)
sudo tcpdump -i eth0 -e -n vlan 10
```

#### Просмотр статистики VLAN-интерфейсов
```bash
# Детальная информация и счетчики ошибок
ip -s -d link show eth0.10
```

## Дополнительная информация

### Сравнение технологий виртуализации L2

| Технология | Изоляция | Сложность | Масштабируемость |
| :--- | :--- | :--- | :--- |
| **VLAN (802.1Q)** | Высокая | Низкая | Лимит 4094 ID |
| **MACVLAN** | Экстремальная | Средняя | Требует поддержки моста в NIC |
| **VXLAN** | Экстремальная | Высокая | 16 млн ID (через L3 сеть) |

**Связанные документы:**
- **[VLAN: Определения и концепции](./definitions_and_concepts.md)** — теоретическая база.
*   **[VLAN в Linux: Диагностика](../../Protocols/VLAN/vlan_linux_diagnostics.md)** — SSoT по инструментам отладки.
- **[Сетевой драйвер macvlan](../../../Docker/Docker_network/drivers/macvlan.md)** — использование в контейнерах.
- **[Linux Bridge](../../../Linux/Networking/Concepts/linux_bridge.md)** — детальный разбор мостов.
