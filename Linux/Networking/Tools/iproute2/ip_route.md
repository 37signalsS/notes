# ip route: Управление маршрутизацией

## Определения

**`ip route`** — команда `iproute2` для управления таблицей маршрутизации ядра Linux.

**Маршрутизация** — процесс определения пути для сетевого трафика на основе IP-адреса назначения.

> **Концепции:** См. [Сетевой уровень OSI](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md).

## Базовые концепции

### Структура маршрута

```
10.0.0.0/8 via 192.168.1.1 dev eth0 proto static metric 100
│            │              │         │        │
│            │              │         │        └─ Приоритет
│            │              │         └─ Источник (static, dhcp, ra)
│            │              └─ Интерфейс
│            └─ Шлюз
└─ Сеть назначения
```

### Типы маршрутов

| Тип | Описание | Пример |
|-----|----------|--------|
| **unicast** | Обычный маршрут | `10.0.0.0/8 via 192.168.1.1` |
| **default** | Шлюз по умолчанию | `default via 192.168.1.1` |
| **local** | Локальная сеть | `192.168.1.0/24 dev eth0` |
| **blackhole** | Отбрасывать пакеты | `blackhole 10.0.0.0/8` |
| **unreachable** | Недостижимо (ICMP error) | `unreachable 10.0.0.0/8` |
| **prohibit** | Запрещено (ICMP forbidden) | `prohibit 10.0.0.0/8` |

### Таблицы маршрутизации

| Таблица | ID | Описание |
|---------|-----|----------|
| **local** | 255 | Локальные маршруты (ядро) |
| **main** | 254 | Основная таблица (по умолчанию) |
| **default** | 253 | Пустая таблица по умолчанию |
| **custom** | 1-252 | Пользовательские (для PBR) |

> **PBR:** [Policy-Based Routing](../../linux_policy_based_routing.md)

## Практические сценарии

### Просмотр маршрутов

```bash
# Основная таблица
ip route show

# Краткий вывод
ip r

# Конкретная таблица
ip route show table main

# Все таблицы
ip route show table all

# Только IPv6
ip -6 route show
```

### Добавление маршрутов

```bash
# Маршрут к сети
sudo ip route add 10.0.0.0/8 via 192.168.1.1 dev eth0

# Шлюз по умолчанию
sudo ip route add default via 192.168.1.1 dev eth0

# Маршрут к хосту (/32)
sudo ip route add 8.8.8.8 via 192.168.1.1

# Маршрут с метрикой (приоритетом)
sudo ip route add 10.0.0.0/8 via 192.168.1.2 metric 50

# Маршрут в custom-таблицу
sudo ip route add 10.0.0.0/8 via 192.168.1.1 table 100
```

> **Важно:** Если уже есть маршрут по умолчанию, `ip route add default` вернёт ошибку `File exists`. Сначала удалите существующий.

### Удаление маршрутов

```bash
# Удалить конкретный маршрут
sudo ip route del 10.0.0.0/8 via 192.168.1.1

# Удалить шлюз по умолчанию
sudo ip route del default

# Удалить из таблицы
sudo ip route del 10.0.0.0/8 table 100
```

### Проверка маршрута

```bash
# Проверить маршрут до IP
ip route get 8.8.8.8
# Вывод: 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 1000
#         ↑ шлюз        ↑ интерфейс  ↑ исходящий IP

# Проверить для IPv6
ip -6 route get 2001:db8::1
```

### Маршруты по умолчанию (нюансы DHCP)

При получении адреса по DHCP:
1. DHCP-сервер передаёт шлюз по умолчанию
2. При удалении DHCP-адреса шлюз **автоматически удаляется**

```bash
# Сценарий:
# 1. eth0 получил 192.168.1.10/24 + default via 192.168.1.1 по DHCP
# 2. Добавлен статический 192.168.1.11/24
# 3. Удаление DHCP-адреса:
sudo ip address del 192.168.1.10/24 dev eth0
# Результат: default route удалён!

# Решение: Добавить статический маршрут перед удалением
sudo ip route add default via 192.168.1.1 dev eth0
sudo ip address del 192.168.1.10/24 dev eth0
```

### Продвинутые сценарии

#### Initcwnd (TCP)

```bash
# Увеличить начальное окно перегрузки
sudo ip route change default via 192.168.1.1 dev eth0 initcwnd 30

# Проверить
ip route show | grep initcwnd
```

> **Подробно:** [Оптимизация TCP](../../Concepts/tcp_tuning.md)

#### Multiple default routes

```bash
# Два шлюза по умолчанию с разной метрикой
sudo ip route add default via 192.168.1.1 dev eth0 metric 100
sudo ip route add default via 192.168.1.2 dev eth1 metric 200
# Приоритет у eth0 (metric 100 < 200)
```

#### Blackhole (защита)

```bash
# Отбрасывать трафик (для защиты или тестирования)
sudo ip route add blackhole 10.0.0.0/8
```

## Дополнительная информация

### Связанные темы

* **[Сетевой уровень](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md)** — основы маршрутизации
* **[Policy-Based Routing](../../linux_policy_based_routing.md)** — множественные таблицы
* **[Оптимизация TCP](../../Concepts/tcp_tuning.md)** — initcwnd, MSS
* **[ip address](./ip_address.md)** — управление адресами

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Network unreachable` | Нет маршрута | `ip route get <dest>` |
| `File exists` | Дубликат маршрута | `ip route show`, удалить старый |
| Неправильный интерфейс | Ошибка в `dev` | Проверить `ip link show` |
| Шлюз недоступен | Нет ARP-записи | `ip neighbour show` |
