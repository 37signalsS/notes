# ip address: Управление IP-адресами

## Определения

**`ip address`** (`ip a`) — команда `iproute2` для управления IP-адресами на сетевых интерфейсах. Поддерживает IPv4 и IPv6.

> **Важно:** Настройки через `ip address` временные. Для постоянного сохранения см. [Постоянная настройка сети](../../Settings/Persistent_Network/systemd_networkd.md).

## Базовые концепции

### Типы адресов

| Тип | Описание | Пример |
|-----|----------|--------|
| **primary** | Основной адрес интерфейса | `192.168.1.10/24` |
| **secondary** | Дополнительный адрес | `192.168.1.11/24` |
| **anycast** | Anycast-адрес (IPv6) | `fe80::1` |
| **mcast** | Multicast-адрес | `ff02::1` |

### Primary vs Secondary

* **Primary** — используется для исходящих соединений по умолчанию
* **Secondary** — дополнительные адреса, не влияют на маршрут по умолчанию

### Флаги адресов

| Флаг | Описание |
|------|----------|
| **global** | Глобальный адрес (доступен везде) |
| **host** | Локальный адрес (loopback) |
| **link** | Link-local (fe80::/10 для IPv6) |
| **dynamic** | Получен по DHCP |
| **mngtmpaddr** | Для генерации временных адресов (IPv6 privacy) |
| **noprefixroute** | Не создавать маршрут для префикса |

## Практические сценарии

### Просмотр адресов

```bash
# Все адреса
ip address show

# Краткий вывод (одна строка на интерфейс)
ip -br address show

# Только IPv4
ip -4 address show

# Только IPv6
ip -6 address show

# Конкретный интерфейс
ip address show eth0

# JSON-вывод (для скриптов)
ip -j address show eth0
```

### Добавление адресов

```bash
# Добавить основной адрес
sudo ip address add 192.168.1.10/24 dev eth0

# Добавить secondary адрес
sudo ip address add 192.168.1.11/24 dev eth0

# Добавить IPv6
sudo ip -6 address add 2001:db8::1/64 dev eth0

# Добавить с меткой (для отслеживания)
sudo ip address add 10.0.0.1/24 dev eth0 label eth0:mgmt
```

### Удаление адресов

```bash
# Удалить конкретный адрес
sudo ip address del 192.168.1.10/24 dev eth0

# Удалить по метке
sudo ip address del 10.0.0.1/24 dev eth0:mgmt
```

> **⚠️ Критично для DHCP:** Если удалить primary-адрес, полученный по DHCP, **шлюз по умолчанию также будет удалён** из таблицы маршрутизации, даже если есть secondary-адреса.

```bash
# Пример проблемы:
# 1. eth0 получил 192.168.1.10/24 + шлюз 192.168.1.1 по DHCP
# 2. Добавлен secondary: 192.168.1.11/24
# 3. Удаление primary:
sudo ip address del 192.168.1.10/24 dev eth0
# Результат: Маршрут по умолчанию через 192.168.1.1 удалён!
# Пинг до 8.8.8.8: "Network is unreachable"
```

**Решение:** Перед удалением DHCP-адреса добавить статический маршрут по умолчанию.

### Временные адреса (IPv6 Privacy)

```bash
# Включить генерацию временных адресов
sudo sysctl -w net.ipv6.conf.eth0.use_tempaddr=2

# Проверить
ip -6 address show eth0 | grep temporary
```

### Очистка всех адресов

```bash
# Удалить все адреса с интерфейса
sudo ip address flush dev eth0

# Удалить только IPv4
sudo ip -4 address flush dev eth0

# Удалить только IPv6
sudo ip -6 address flush dev eth0
```

### Отладка

```bash
# Проверить, какой адрес используется для исходящих
ip route get 8.8.8.8

# Мониторинг изменений
ip monitor address
```

## Дополнительная информация

### Связанные темы

* **[ip route](./ip_route.md)** — управление маршрутизацией
* **[Постоянная настройка сети](../../Settings/Persistent_Network/systemd_networkd.md** — сохранение настроек
* **[IPv6](../../Settings/ipv6_configuration/firewall.md)** — настройка IPv6
* **[DHCP](../../../../Networking/Protocols/DHCP/dhcp_overview.md)** — протокол динамической настройки

### Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Потеря шлюза после `del` | Удалён DHCP primary | Добавить статический маршрут |
| Дубликат IP | Конфликт в сети | `arping -D eth0 <ip>` |
| IPv6 не работает | Отключен в ядре | `sysctl net.ipv6.conf.all.disable_ipv6` |
| Адрес не виден | Не тот интерфейс | `ip -br a`, проверить `dev` |
