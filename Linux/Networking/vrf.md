# VRF (Virtual Routing and Forwarding) в Linux

## Определения

* **VRF (Virtual Routing and Forwarding)** — технология сетевой изоляции на уровне L3 (сетевой уровень OSI), позволяющая создавать несколько независимых таблиц маршрутизации (Routing Tables) внутри одного экземпляра операционной системы.
* **VRF-интерфейс (L3 Master Device)** — виртуальный сетевой интерфейс, выступающий в роли «контейнера» для других устройств. Он ассоциирует привязанные к нему интерфейсы с конкретной таблицей маршрутизации.
* **Slave-интерфейс** — физический или виртуальный сетевой интерфейс (например, `eth0`, `vlan10`), привязанный к VRF-мастеру. Трафик этого интерфейса обрабатывается исключительно в рамках FIB (Forwarding Information Base) данного VRF.

## Основные концепции

### Механизм работы

В Linux VRF реализован через инфраструктуру **L3 Master Device**. Когда пакет поступает на slave-интерфейс или генерируется локально процессом, привязанным к VRF, ядро выполняет поиск в таблице маршрутизации (FIB lookup), связанной с этим VRF, игнорируя таблицу `main`.

1.  **Ingress:** Пакет помечается идентификатором VRF при поступлении на интерфейс.
2.  **Routing:** Ядро использует таблицу маршрутизации, указанную в параметрах VRF-интерфейса.
3.  **Egress:** Пакет покидает систему через slave-интерфейс, принадлежащий тому же VRF.

### Сравнение VRF и Network Namespaces (NetNS)

| Характеристика | VRF | Network Namespaces (NetNS) |
| :--- | :--- | :--- |
| **Уровень изоляции** | Только L3 (маршрутизация). | Полный стек (L2-L7, порты, Netfilter). |
| **Управление** | Единое пространство имен, все интерфейсы видны в `ip link`. | Раздельные пространства имен, полная изоляция видимости. |
| **Производительность** | Высокая (минимальные накладные расходы). | Чуть ниже из-за переключения контекста и veth-пар. |
| **Общие ресурсы** | Общие сокеты, память, файловая система. | Изолированные ресурсы. |
| **Основной кейс** | Мультитенантность маршрутизации, Management VRF. | Контейнеризация, полная изоляция сервисов. |

### Взаимодействие с Loopback

В контексте VRF интерфейс `lo` продолжает работать глобально, однако каждый VRF может иметь свои локальные маршруты. Для корректной работы локальных соединений внутри VRF (например, `ping` на локальный адрес интерфейса в VRF) ядро автоматически создает правила маршрутизации.

### Netfilter и Conntrack

По умолчанию `conntrack` в Linux не разделяет соединения по VRF. Если в разных VRF используются одинаковые IP-адреса (IP overlap), это может привести к коллизиям в таблице состояний.
*   Для решения этой проблемы используется **VRF-aware conntrack** (доступно в новых ядрах).
*   В `nftables` можно использовать селекторы `iifname` или `meta l3mdev` для разграничения правил фильтрации между доменами маршрутизации.

### Параметры ядра (sysctl)

Для корректной работы мульти-VRF среды необходимо настроить следующие параметры:

*   **`net.ipv4.tcp_l3mdev_accept = 1`** — позволяет TCP-сервисам (например, SSH) принимать входящие соединения из любого VRF, даже если они слушают на `0.0.0.0`.
*   **`net.ipv4.udp_l3mdev_accept = 1`** — аналогично для UDP-сервисов (DNS, SNMP).
*   **`net.ipv4.raw_l3mdev_accept = 1`** — разрешает работу ICMP (ping) и других raw-сокетов в контексте VRF.
*   **`net.ipv6.conf.all.keep_addr_on_down = 1`** — предотвращает удаление IPv6-адресов при кратковременном переходе slave-интерфейса в состояние DOWN во время привязки к VRF.

## Практические сценарии

### Создание и базовая настройка

```bash
# 1. Создать VRF-интерфейс, привязанный к таблице маршрутизации 100
sudo ip link add vrf-blue type vrf table 100

# 2. Активировать интерфейс
sudo ip link set vrf-blue up

# 3. Привязать физический интерфейс к VRF
# ВАЖНО: Привязка сбрасывает текущее состояние интерфейса и может удалить IP-адреса
sudo ip link set eth1 master vrf-blue
sudo ip link set eth1 up

# 4. Проверить конфигурацию
ip vrf show
# → Name              Table
# → -----------------------
# → vrf-blue            100
```

### Управление маршрутизацией

При использовании VRF таблицы маршрутизации полностью разделены.

```bash
# Добавить маршрут по умолчанию в таблицу VRF
sudo ip route add default via 192.168.1.1 dev eth1 vrf vrf-blue

# Просмотр таблицы маршрутизации конкретного VRF
ip route show vrf vrf-blue
# → default via 192.168.1.1 dev eth1

# Предотвращение утечки трафика (Leakage) в таблицу main
# Добавление unreachable маршрута с метрикой выше основной
sudo ip route add unreachable default table 100 metric 8192
```

### Настройка VRF с VLAN

Распространенный сценарий — изоляция трафика разных VLAN в разных VRF.

```bash
# Создание VLAN интерфейса
sudo ip link add link eth1 name eth1.10 type vlan id 10

# Привязка VLAN к VRF
sudo ip link set eth1.10 master vrf-blue
sudo ip link set eth1.10 up

# Назначение IP-адреса
sudo ip addr add 10.0.0.1/24 dev eth1.10
```

### Запуск приложений в VRF

1.  **Неадаптированные приложения:** Используйте `ip vrf exec`. Это помещает процесс в `cgroup`, ассоциированную с VRF.
    ```bash
    # Запуск curl через конкретный VRF
    ip vrf exec vrf-blue curl icanhazip.com
    ```
2.  **VRF-aware приложения:** Современное ПО (FRRouting, Bird, Strongswan, sshd) может самостоятельно привязываться к VRF через опции конфигурации или `setsockopt(SO_BINDTODEVICE)`.

### Постоянная конфигурация

Методы сохранения настроек после перезагрузки:

*   **Netplan (Ubuntu):** См. **[Настройка Netplan](./Settings/Persistent_Network/ubuntu_netplan.md)**.
*   **NetworkManager (RHEL/CentOS):** См. **[NetworkManager VRF](./Settings/Persistent_Network/centos_rhel_networkmanager.md)**.
*   **systemd-networkd:** Настраивается через `.netdev` и `.network` файлы.

## Диагностика

### Проверка сетевых соединений

```bash
# Поиск активных сокетов в контексте VRF
ss -ntlp
# → Local Address:Port ... Device
# → 0.0.0.0:22            ... vrf-blue

# Проверка маршрута для конкретного IP внутри VRF
ip route get 8.8.8.8 vrf vrf-blue
# → 8.8.8.8 dev eth1 table 100 src 10.0.0.1 uid 0
```

### Анализ трафика

При использовании `tcpdump` на slave-интерфейсе виден «сырой» трафик. При использовании на VRF-интерфейсе виден трафик после L3-обработки.

```bash
# Захват трафика на VRF-мастере
sudo tcpdump -i vrf-blue
```

## Дополнительная информация

### Связанные темы

*   **[`ip link`](./Tools/iproute2/ip_link.md)** — управление сетевыми интерфейсами.
*   **[`ip route`](./Tools/iproute2/ip_route.md)** — расширенная настройка маршрутизации.
*   **[Маршрутизация по политикам (PBR)](./Policy_Based_Routing/index.md)** — использование `ip rule` и отличия от VRF.
*   **[Таблицы маршрутизации в Linux](../SystemAdministration/routing.md)** — общие принципы работы FIB.

### Полезные ссылки

*   [Kernel Documentation: VRF](https://www.kernel.org/doc/Documentation/networking/vrf.txt)
*   [Virtual Routing and Forwarding (VRF) — Virtualization Wiki](https://en.wikipedia.org/wiki/Virtual_routing_and_forwarding)
*   [Linux VRF Tutorial (ozlabs.org)](https://www.kernel.org/doc/html/latest/networking/vrf.html)
