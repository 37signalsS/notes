# ip netns: Управление сетевыми пространствами имён

## Определения

**Network namespace** — изолированное сетевое окружение ядра Linux с собственными интерфейсами, таблицей маршрутизации, правилами фаервола и сокетами.

**`ip netns`** — утилита `iproute2` для создания, удаления и управления network namespace.

> Network namespace — основа контейнеризации (Docker, Kubernetes). Поды Kubernetes используют один namespace на под.

## Базовые концепты

### Изоляция namespace

Каждый namespace имеет:

* Собственные сетевые интерфейсы (включая `lo`)
* Отдельную таблицу маршрутизации
* Независимые правила iptables/nftables
* Изолированные сетевые сокеты (порты)

### Типы namespace

| Тип | Описание |
|-----|----------|
| **default** | Основной namespace хоста (все физические интерфейсы) |
| **custom** | Пользовательские namespace для контейнеров, тестирования |

## Практические сценарии

### Создание и удаление

```bash
# Создать namespace
sudo ip netns add my_namespace

# Проверить создание
ip netns list

# Удалить namespace (интерфейсы должны быть удалены или перемещены)
sudo ip netns delete my_namespace
```

### Выполнение команд внутри namespace

```bash
# Показать интерфейсы (будет виден только lo)
sudo ip netns exec my_namespace ip link

# Показать адреса
sudo ip netns exec my_namespace ip address show

# Запустить shell внутри namespace
sudo ip netns exec my_namespace bash

# Тестирование связности
sudo ip netns exec my_namespace ping 8.8.8.8
```

### Связь между namespace (veth-пары)

`veth` (virtual ethernet) — виртуальный интерфейс-пара: пакеты, отправленные в один конец, появляются на другом.

```bash
# Создать veth-пару
sudo ip link add veth-host type veth peer name veth-ns

# Переместить один конец в namespace
sudo ip link set veth-ns netns my_namespace

# Настроить IP на стороне хоста
sudo ip address add 10.0.0.1/24 dev veth-host
sudo ip link set veth-host up

# Настроить IP внутри namespace
sudo ip netns exec my_namespace ip address add 10.0.0.2/24 dev veth-ns
sudo ip netns exec my_namespace ip link set veth-ns up
sudo ip netns exec my_namespace ip link set lo up

# Проверить связность
ping 10.0.0.2
sudo ip netns exec my_namespace ping 10.0.0.1
```

### Доступ к namespace извне (через /var/run/netns)

```bash
# Создать persistent-namespace (доступен без ip netns exec)
sudo ip netns add persistent_ns

# Примонтировать namespace для доступа через pid
sudo mount --bind /var/run/netns/persistent_ns /var/run/netns/persistent_ns

# Теперь можно использовать с ip link
sudo ip link set dev eth1 netns persistent_ns
```

### Отладка и мониторинг

```bash
# Список всех namespace
ip netns list

# PID процессов в namespace
ip netns pids my_namespace

# Показать таблицу маршрутизации
sudo ip netns exec my_namespace ip route show

# Показать ARP-таблицу
sudo ip netns exec my_namespace ip neighbour show

# Статистика интерфейсов
sudo ip netns exec my_namespace ip -s link show
```

### Продвинутые сценарии

#### Мост между namespace

```bash
# Создать мост на хосте
sudo ip link add name br0 type bridge
sudo ip link set br0 up

# Подключить veth к мосту
sudo ip link set veth-host master br0

# Теперь namespace имеет доступ к сети хоста через мост
```

#### NAT для namespace

```bash
# Включить IP-форвардинг
sudo sysctl -w net.ipv4.ip_forward=1

# Добавить NAT-правило для выхода в интернет
sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE

# Добавить маршрут по умолчанию в namespace
sudo ip netns exec my_namespace ip route add default via 10.0.0.1
```

**Пояснение MASQUERADE:**

* `POSTROUTING` — цепочка для модификации пакетов перед отправкой наружу
* `-s 10.0.0.0/24` — трафик из внутренней сети
* `-o eth0` — внешний интерфейс хоста
* `MASQUERADE` — автоматическая подмена IP источника на IP внешнего интерфейса
* `! -o br0` (опционально) — исключение трафика, идущего в bridge

> **См. также:** [NAT](../../../../Networking/Concepts/nat/overview.md#snat-vs-masquerade-linux-iptablesnftables)

## Дополнительная информация

### Связанные темы

* **[Namespaces](../../../../Linux/Core/namespaces.md)** — полное руководство по Linux namespaces
* **[Docker network](../../../../Docker/Docker_network/docker_network.md)** — сетевая модель Docker
* **[Kubernetes network](../../../../Kubernetes/Networking/Network/network_overview.md)** — сеть в Kubernetes
* **[veth](../../Concepts/linux_network_interfaces.md)** — виртуальные интерфейсы

### Ограничения

* Namespace удаляется только когда все процессы внутри завершены
* Для доступа к namespace из разных терминалов требуется `/var/run/netns`
* Производительность veth ниже физических интерфейсов (оверлей)
