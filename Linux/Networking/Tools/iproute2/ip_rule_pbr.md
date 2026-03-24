# ip rule: правила маршрутизации и Policy-Based Routing

## Обзор

Ядро выбирает таблицу маршрутизации на основе правил.

```bash
ip rule show
# 0:      from all lookup local
# 32766:  from all lookup main
# 32767:  from all lookup default
```

---

## Формат правила

- **Приоритет** (число в начале) — правила обрабатываются по возрастанию
- **Условие** (`from all`) — селектор пакетов
- **Действие** (`lookup <таблица>`) — какую таблицу использовать

---

## Условия для правил

| Условие | Описание | Пример |
| :--- | :--- | :--- |
| `from <IP>` | Адрес отправителя | `from 192.168.1.0/24` |
| `to <IP>` | Адрес получателя | `to 10.0.0.0/8` |
| `iif <dev>` | Входной интерфейс | `iif eth1` |
| `oif <dev>` | Исходящий интерфейс | `oif eth0` |
| `tos <value>` | Поле TOS IP-пакета (см. [Type of Service](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Protocols/ip_packet_structure.md)) | `tos 0x10` |
| `fwmark <mark>` | Метка пакета (iptables) | `fwmark 0x2/0x2` |

### Комбинирование условий

```bash
# От сети 192.168.1.0/24 к сети 10.0.0.0/8
ip rule add from 192.168.1.0/24 to 10.0.0.0/8 table 100 priority 1000

# С префиксом not (исключить пакеты)
ip rule add not from 192.168.1.100 table main
```

---

## Пример добавления правила

```bash
# Все пакеты от 192.168.1.100 направлять в таблицу 100
ip rule add from 192.168.1.100 table 100 priority 1000
```

> **Подробно:** [Policy-Based Routing](../../Policy_Based_Routing/index.md) — использование PBR для разделения трафика

---

## Типичные проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `Network unreachable` | Нет маршрута | `ip route get <dest>` |
| `File exists` | Дубликат маршрута | `ip route show`, удалить старый |
| Неправильный интерфейс | Ошибка в `dev` | Проверить `ip link show` |
| Шлюз недоступен | Нет ARP-записи | `ip neighbour show` |

---

## Связанные документы

- **[ip route: основы](./ip_route_basics.md)** — структура маршрута, типы, таблицы
- **[ip route: практика](./ip_route_practical.md)** — добавление, удаление, проверка маршрутов
- **[Policy-Based Routing](../../Policy_Based_Routing/index.md)** — множественные таблицы
- **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_initcwnd.md)** — initcwnd, MSS
