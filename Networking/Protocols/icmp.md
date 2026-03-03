# Протокол ICMP (Internet Control Message Protocol)

## Определения

**ICMP (Internet Control Message Protocol)** — служебный протокол сетевого уровня (L3), используемый устройствами IP-сети для передачи сообщений об ошибках, управления и диагностики. ICMP является неотъемлемой частью стека TCP/IP и работает поверх [IP](./ip.md), дополняя его механизм обратной связи.

**Ключевая особенность:** ICMP не передаёт пользовательские данные, а служит для обмена служебной информацией между маршрутизаторами и хостами.

## Основные концепции

### Назначение ICMP

1. **Диагностика сети** — проверка доступности узлов и измерения задержек
2. **Сообщения об ошибках** — уведомление отправителя о проблемах доставки
3. **Управление маршрутизацией** — оптимизация путей доставки пакетов

### Структура ICMP-сообщения

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Type      |     Code      |          Checksum             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         Variable Data                         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

| Поле | Размер | Описание |
|------|--------|----------|
| **Type** | 8 бит | Тип сообщения (определяет назначение) |
| **Code** | 8 бит | Детализация типа сообщения |
| **Checksum** | 16 бит | Контрольная сумма всего сообщения |
| **Variable Data** | var | Зависит от типа; обычно содержит IP-заголовок + 8 байт данных проблемного пакета |

## Практические сценарии

### Основные типы ICMP-сообщений

#### Диагностика доступности

| Type | Code | Название | Использование |
|------|------|----------|---------------|
| **8/0** | 0 | Echo Request/Reply | `ping` — проверка доступности |
| **13/14** | 0 | Timestamp Request/Reply | Синхронизация времени, измерение RTT |

**Пример ping:**
```bash
$ ping -c 4 8.8.8.8
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=12.3 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=11.8 ms
```

#### Сообщения об ошибках

| Type | Code | Название | Описание |
|------|------|----------|----------|
| **3** | 0-15 | Destination Unreachable | Недостижимость цели |
| | 0 | Net Unreachable | Сеть недоступна |
| | 1 | Host Unreachable | Хост недоступен |
| | 2 | Protocol Unreachable | Протокол не поддерживается |
| | **3** | **Port Unreachable** | Порт закрыт (часто используется для сканирования) |
| | 4 | Fragmentation Needed | Требуется фрагментация, установлен DF |
| | 6 | Destination Network Unknown | Сеть неизвестна |
| | 7 | Destination Host Unknown | Хост неизвестен |
| **5** | 0-3 | Redirect | Перенаправление к лучшему шлюзу |
| **11** | 0 | Time Exceeded (TTL) | Истечение TTL (используется в `traceroute`) |
| | 1 | Time Exceeded (Fragment) | Превышено время сборки фрагментов |
| **12** | 0-2 | Parameter Problem | Ошибка в заголовке пакета |

**Пример traceroute:**
```bash
$ traceroute -n 8.8.8.8
 1  192.168.1.1  2.345 ms  2.123 ms  2.456 ms
 2  10.0.0.1     5.678 ms  5.432 ms  5.789 ms
 3  203.0.113.1  8.901 ms  8.765 ms  9.012 ms
 ...
```
`traceroute` отправляет пакеты с увеличивающимся TTL (1, 2, 3...) и получает ICMP Time Exceeded от каждого маршрутизатора на пути.

#### Управление маршрутизацией

| Type | Название | Описание |
|------|----------|----------|
| **9** | Router Advertisement | Маршрутизатор объявляет о своём присутствии |
| **10** | Router Solicitation | Хост запрашивает информацию о маршрутизаторах |

### Диагностика проблем с ICMP

#### Блокировка ICMP файрволом

**Симптомы:**
- `ping` не работает, но TCP-соединения устанавливаются
- `traceroute` показывает `* * *` на некоторых хопах

**Проверка:**
```bash
# Проверка доступности ICMP
tcpdump -i eth0 icmp
tcpdump -i eth0 'icmp[0] = 8 or icmp[0] = 0'
```

#### Fragmentation Needed (Type 3, Code 4)

**Проблема:** Маршрутизатор отправляет ICMP "Fragmentation Needed", если пакет больше MTU следующего звена, а флаг DF (Don't Fragment) установлен.

**Решение:**
```bash
# Проверка MTU пути
tracepath example.com

# Временное решение (не рекомендуется)
ip link set dev eth0 mtu 1400
```

### Безопасность и ICMP

#### ICMP в security-политиках

**Рекомендации:**
- **Разрешить:** Echo Request/Reply (для мониторинга), Destination Unreachable, Time Exceeded
- **Ограничить:** Rate limiting для предотвращения ICMP flood
- **Блокировать:** Redirect (может использоваться для атак), Timestamp (утечка информации)

**Пример правила iptables:**
```bash
# Разрешить ping с rate limiting
iptables -A INPUT -p icmp --icmp-type echo-request -m limit --limit 1/s -j ACCEPT
iptables -A INPUT -p icmp --icmp-type echo-reply -j ACCEPT

# Разрешить критичные сообщения об ошибках
iptables -A INPUT -p icmp --icmp-type destination-unreachable -j ACCEPT
iptables -A INPUT -p icmp --icmp-type time-exceeded -j ACCEPT

# Блокировать redirect
iptables -A INPUT -p icmp --icmp-type redirect -j DROP
```

#### ICMP-атаки

| Атака | Описание | Защита |
|-------|----------|--------|
| **Ping Flood** | Злоумышленник отправляет большой объем Echo Request | Rate limiting, фильтрация на периметре |
| **Ping of Death** | Отправка фрагментированных пакетов >65535 байт | Патчи ОС (устаревшая уязвимость) |
| **Smurf Attack** | Amplification-атака через broadcast-адрес | Блокировка directed broadcast |
| **ICMP Redirect Attack** | Ложные Redirect для перенаправления трафика | Игнорировать Redirect на хостах |

## Дополнительная информация

### ICMP в IPv6

В IPv6 ICMP стал **обязательным** и переименован в **ICMPv6** (RFC 4443). Дополнительные функции:
- **NDP (Neighbor Discovery Protocol)** — замена ARP
- **SLAAC (Stateless Address Autoconfiguration)** — автоконфигурация адресов
- **MLD (Multicast Listener Discovery)** — управление multicast-группами

### Связанные документы
- [IP](./ip.md) — сетевой уровень
- [TCP](./TCP/overview.md) — транспортный уровень
- [traceroute](../../Linux/Networking/Tools/traceroute.md) — утилита диагностики
- [ping](../../Linux/Networking/Tools/ping.md) — утилита проверки доступности

### RFC
- **RFC 792** — спецификация ICMP для IPv4
- **RFC 4443** — ICMPv6 для IPv6
- **RFC 4884** — Extended ICMP
