# ip route: практические сценарии

## Просмотр маршрутов

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

---

## Разбор вывода ip route show

### Пример конфигурации

- Интерфейс: `enp0s3`
- IP-адрес: `192.168.110.50/24`
- Шлюз по умолчанию: `192.168.110.1`

```bash
ip route show
# default via 192.168.110.1 dev enp0s3
# 192.168.110.0/24 dev enp0s3 proto kernel scope link src 192.168.110.50
```

### Разбор второй записи (локальная сеть)

| Поле | Значение | Описание |
| :--- | :--- | :--- |
| `192.168.110.0/24` | Сеть назначения | Пакеты в эту подсеть |
| `dev enp0s3` | Интерфейс | Уходят через `enp0s3` |
| `proto kernel` | Источник | Добавлен ядром при назначении IP |
| `scope link` | Область | Действителен только для этого интерфейса |
| `src 192.168.110.50` | Source IP | Адрес отправителя для этого правила |

### Первая запись (шлюз по умолчанию)

- `default via 192.168.110.1` — пакеты вне локальной сети отправляются на шлюз
- **Важно:** При отправке пакетов на шлюз IP-адрес назначения не изменяется. В Ethernet-фрейме в качестве MAC-адреса получателя указывается MAC-адрес шлюза. Шлюз меняет IP отправителя (NAT) или пересылает пакет дальше.

---

## Таблица local

```bash
ip route show table local
# broadcast 127.0.0.0 dev lo proto kernel scope link src 127.0.0.1
# local 127.0.0.0/8 dev lo proto kernel scope host src 127.0.0.1
# local 127.0.0.1 dev lo proto kernel scope host src 127.0.0.1
# broadcast 127.255.255.255 dev lo proto kernel scope link src 127.0.0.1
# broadcast 192.168.110.0 dev enp0s3 proto kernel scope link src 192.168.110.50
# local 192.168.110.50 dev enp0s3 proto kernel scope host src 192.168.110.50
# broadcast 192.168.110.255 dev enp0s3 proto kernel scope link src 192.168.110.50
```

### Типы записей в таблице local

| Тип | Описание |
| :--- | :--- |
| `unicast` | Обычный маршрут: интерфейс + next hop |
| `local` | Пакеты отправляются локально (без выхода во внешнюю сеть) |
| `broadcast` | Широковещательное сообщение |
| `unreachable` | Пакет выбрасывается + ICMP «host unreachable» |
| `blackhole` | Пакет выбрасывается без сообщения |
| `prohibit` | Пакет выбрасывается + ICMP «administratively prohibited» |

### Область действия (scope) в local

| Scope | Описание |
| :--- | :--- |
| `host` | Действительна только для этого хоста |
| `link` | Действительна только для этого интерфейса |

---

## Добавление маршрутов

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

---

## Удаление маршрутов

```bash
# Удалить конкретный маршрут
sudo ip route del 10.0.0.0/8 via 192.168.1.1

# Удалить шлюз по умолчанию
sudo ip route del default

# Удалить из таблицы
sudo ip route del 10.0.0.0/8 table 100
```

---

## Проверка маршрута

```bash
# Проверить маршрут до IP
ip route get 8.8.8.8
# Вывод: 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.10 uid 1000
#         ↑ шлюз        ↑ интерфейс  ↑ исходящий IP

# Проверить для IPv6
ip -6 route get 2001:db8::1
```

---

## Маршруты по умолчанию (нюансы DHCP)

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

---

## Продвинутые сценарии

### Initcwnd (TCP)

```bash
# Увеличить начальное окно перегрузки
sudo ip route change default via 192.168.1.1 dev eth0 initcwnd 30

# Проверить
ip route show | grep initcwnd
```

> **Подробно:** [Оптимизация TCP](../../Concepts/tcp_tuning/tcp_initcwnd.md)

### Multiple default routes

```bash
# Два шлюза по умолчанию с разной метрикой
sudo ip route add default via 192.168.1.1 dev eth0 metric 100
sudo ip route add default via 192.168.1.2 dev eth1 metric 200
# Приоритет у eth0 (metric 100 < 200)
```

### Blackhole (защита)

```bash
# Отбрасывать трафик (для защиты или тестирования)
sudo ip route add blackhole 10.0.0.0/8
```

---

## Связанные документы

- **[ip route: основы](./ip_route_basics.md)** — структура маршрута, типы, таблицы
- **[Policy-Based Routing](../../Policy_Based_Routing/index.md)** — множественные таблицы
- **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_initcwnd.md)** — initcwnd, MSS
