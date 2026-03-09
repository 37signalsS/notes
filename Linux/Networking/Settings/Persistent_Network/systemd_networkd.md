# systemd-networkd: настройка сети

## Обзор

`systemd-networkd` — встроенный менеджер сети в systemd. Работает без дополнительных зависимостей, идеален для серверов и минималистичных систем.

**Конфигурационные файлы:** `/etc/systemd/network/*.network`

### Типы файлов конфигурации

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| `*.link` | Физические параметры интерфейсов (имя, MAC, MTU) | `/etc/systemd/network/90-nic1-port0.link` |
| `*.network` | Сетевая конфигурация (IP, DHCP, маршруты, DNS) | `/etc/systemd/network/10-eth0.network` |
| `*.netdev` | Виртуальные интерфейсы (VLAN, мосты, туннели, VPN) | `/etc/systemd/network/10-bond0.netdev` |

**Важно:** Файлы `*.link` необязательны. Используются для изменения физических параметров, например, для переименования интерфейсов по MAC-адресу.

---

## Файл .link (переименование интерфейса)

```ini
# /etc/systemd/network/90-nic1-port0.link
[Match]
MACAddress=04:01:50:23:1f:02

[Link]
Name=nic1-port0
```

После применения интерфейс с указанным MAC-адресом получит имя `nic1-port0`. Это имя затем используется в файлах `*.network`.

---

## Файл .network: статическая конфигурация

### Базовый пример

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
Address=10.10.10.10/24
Gateway=10.10.10.1
DNS=8.8.8.8
DNS=1.1.1.1
```

### Несколько адресов и маршрутов

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
# Основной адрес
Address=10.10.10.10/24
# Дополнительный адрес (VIP)
Address=10.10.10.20/24
Gateway=10.10.10.1
DNS=8.8.8.8
DNS=1.1.1.1

# Статический маршрут
[Route]
Destination=192.168.100.0/24
Gateway=10.10.10.254

# Маршрут по умолчанию с метрикой
[Route]
Gateway=10.10.10.1
Metric=100

# Маршрут для policy-based routing (отдельная таблица)
[Route]
Gateway=192.168.110.1
Table=101
```

### Параметры [Route]

| Параметр | Описание |
| :--- | :--- |
| `Destination` | Сеть назначения (по умолчанию `0.0.0.0/0`) |
| `Gateway` | Шлюз |
| `Metric` | Приоритет маршрута (для резервирования каналов) |
| `Table` | ID таблицы маршрутизации (для [policy-based routing](../../../Policy_Based_Routing/index.md)) |

---

## DHCP-клиент

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DHCP=yes

[DHCP]
# Использовать DNS от DHCP
UseDNS=yes
# Использовать NTP от DHCP
UseNTP=yes
```

---

## Отключение IPv6

```ini
# /etc/systemd/network/80-lan0-dhcp.network
[Match]
Name=eth0

[Network]
DHCP=ipv4
LinkLocalAddressing=no
```

Опция `LinkLocalAddressing=no` предотвращает автоматическое назначение IPv6-адреса link-local.

---

## Управление и диагностика

```bash
# Включить службу
sudo systemctl enable --now systemd-networkd

# Перезапустить службу
sudo systemctl restart systemd-networkd

# Показать состояние интерфейсов
networkctl status

# Показать список интерфейсов
networkctl list

# Перечитать конфигурацию
sudo networkctl reload

# Журнал событий
journalctl -u systemd-networkd -f
```

---

## Интеграция с systemd-resolved (DNS)

`systemd-networkd` автоматически передает DNS-серверы в `systemd-resolved`. Проверка:

```bash
# Показать текущие DNS-серверы
resolvectl status

# Показать кэш DNS
resolvectl statistics
```

---

## Преимущества systemd-networkd

- Минимальные зависимости (часть systemd)
- Декларативная конфигурация
- Встроенная поддержка DHCP, DNS-over-TLS (через systemd-resolved)
- Хорошая интеграция с другими компонентами systemd

## Недостатки systemd-networkd

- Меньше возможностей для сложных сценариев (по сравнению с NetworkManager)
- Нет GUI-инструментов

---

## Policy-Based Routing в systemd-networkd

Для [policy-based routing](../../../Policy_Based_Routing/index.md) используется директива `[RoutingPolicyRule]`:

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
Address=192.168.110.100/24
DNS=8.8.8.8

# Маршрут по умолчанию для основной таблицы
[Route]
Gateway=192.168.110.1
Metric=100

# Маршрут по умолчанию для отдельной таблицы PBR
[Route]
Gateway=192.168.110.1
Table=101

# Правило PBR: пакеты с IP 192.168.110.100 используют таблицу 101
[RoutingPolicyRule]
From=192.168.110.100
Table=101
Priority=32765
```

### Параметры [RoutingPolicyRule]

| Параметр | Описание |
| :--- | :--- |
| `From` | Исходный IP-адрес (селектор `from` в `ip rule`) |
| `To` | Адрес назначения (селектор `to`) |
| `Table` | ID таблицы маршрутизации |
| `Priority` | Приоритет правила (чем меньше число, тем выше приоритет) |
| `IngressInterface` | Входящий интерфейс (селектор `iif`) |
| `OutgoingInterface` | Исходящий интерфейс (селектор `oif`) |
| `FWMark` | Метка пакетов (селектор `fwmark`) |
