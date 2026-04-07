# Анализ DHCP-трафика и troubleshooting

## Определения

**Анализ DHCP-трафика** — процесс захвата и декодирования DHCP-пакетов сетевым анализатором (Wireshark) для диагностики проблем конфигурации клиентов.

**Troubleshooting DHCP** — систематическая диагностика проблем получения/обновления IP-адресов и сетевых параметров.

## Основные концепции

### Авторитатный и неавторитатный DHCP-сервер

Опция `authoritative` в конфигурации DHCP-сервера определяет его поведение при обработке некорректных запросов.

#### Авторитативный (Authoritative) сервер

Считается «главным» для данной подсети. Если такой сервер получает от клиента `DHCPREQUEST` с IP-адресом, который не принадлежит его пулу или некорректен для данной сети, он отправит клиенту сообщение `DHCPNAK`. Это заставит клиента прекратить использование неверного адреса и заново запустить процесс DORA.

**Пример:** Сотрудник приносит рабочий ноутбук из дома. Ноутбук пытается использовать свой домашний IP-адрес в корпоративной сети. Авторитативный DHCP-сервер немедленно отправит `DHCPNAK`, и ноутбук получит новый, корпоративный IP.

#### Неавторитативный (Non-authoritative) сервер

Если сервер не является авторитативным, он просто проигнорирует некорректный `DHCPREQUEST`. Клиент будет продолжать использовать неверный адрес до истечения его срока аренды, и все это время не сможет нормально работать в сети.

**Рекомендация:** В каждой подсети должен быть только один авторитативный DHCP-сервер. Подробное описание процесса DORA — в [DHCP Overview](./dhcp_overview.md).

## Практические сценарии

### Анализ DHCP-трафика в Wireshark

**Цель:** Изучить взаимодействие DHCP-клиента и сервера, выявить сбои в процессе DORA.

#### Шаг 1: Захват трафика

1. Запустите **Wireshark** от имени администратора
2. Выберите основной сетевой интерфейс (`Ethernet` или `Wi-Fi`)
3. Начните захват пакетов

#### Шаг 2: Генерация DHCP-трафика

| ОС | Команды |
|----|---------|
| **Windows** | 1. Откройте командную строку от имени администратора<br>2. `ipconfig /release` — освободить текущий IP<br>3. `ipconfig /renew` — получить новый IP |
| **macOS** | 1. Откройте терминал<br>2. `sudo ipconfig set en0 none` — освободить IP<br>3. `sudo ipconfig set en0 dhcp` — получить новый IP |
| **Linux** | 1. `sudo dhclient -r eth0` — освободить IP<br>2. `sudo dhclient eth0` — получить новый IP |

#### Шаг 3: Анализ захваченных пакетов

1. Остановите захват в Wireshark
2. Примените фильтр: `dhcp` или `bootp`
3. Изучите последовательность DORA (детали полей — в [DHCP Overview](./dhcp_overview.md#основные-концепции)):

| Пакет | Поля для анализа |
|-------|------------------|
| **DHCP Discover** | `op=1`, `chaddr` (MAC клиента), `ciaddr=0.0.0.0`, Message Type=Discover |
| **DHCP Offer** | `op=2`, `yiaddr` (предлагаемый IP), `siaddr` (TFTP сервер), Message Type=Offer, Bootp flags (Unicast/Broadcast) |
| **DHCP Request** | Requested IP Address, DHCP Server Identifier, Message Type=Request |
| **DHCP Ack** | `yiaddr` (выданный IP), Subnet Mask, Router, DNS, Lease Time, Renewal Time (T1) |

#### Пример вывода Wireshark

```
Frame 1: DHCP Discover
    Boot Protocol: Request (1)
    Client Hardware Address: aa:bb:cc:dd:ee:ff
    Client IP Address: 0.0.0.0
    Your IP Address: 0.0.0.0
    Option: Message Type (Discover)

Frame 2: DHCP Offer
    Boot Protocol: Reply (2)
    Client Hardware Address: aa:bb:cc:dd:ee:ff
    Client IP Address: 0.0.0.0
    Your IP Address: 192.168.1.100
    Server IP Address: 192.168.1.1
    Option: Message Type (Offer)
    Option: Subnet Mask (255.255.255.0)
    Option: Router (192.168.1.1)
    Option: Domain Name Server (8.8.8.8)

Frame 3: DHCP Request
    Boot Protocol: Request (1)
    Requested IP Address: 192.168.1.100
    DHCP Server Identifier: 192.168.1.1
    Option: Message Type (Request)

Frame 4: DHCP Ack
    Boot Protocol: Reply (2)
    Your IP Address: 192.168.1.100
    Option: Message Type (Ack)
    Option: IP Address Lease Time (86400 seconds)
    Option: Renewal Time Value (43200 seconds)
```

#### Когда применять

- После изменения пула адресов на сервере
- При смене DNS-серверов или шлюза
- При устранении конфликтов IP-адресов
- После исправления ошибок в конфигурации DHCP

### Типичные проблемы и решения

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| **Клиент не получает IP** | `ipconfig` показывает `169.254.x.x` (APIPA) | Проверить доступность DHCP-сервера, наличие свободных адресов в пуле |
| **Конфликт IP-адресов** | Ошибки подключения, DHCPDECLINE от клиента | Включить ping check на сервере, проверить статические назначения |
| **Долгое получение IP** | Задержка 10–30 секунд при подключении | Проверить задержку сети до DHCP-сервера, настроить [DHCP Relay](./dhcp_relay.md) |
| **Неверные параметры** | Неправильный шлюз, DNS | Проверить конфигурацию scope на DHCP-сервере |

## Дополнительная информация

- Время аренды и продление: [DHCP Lease Time](./dhcp_lease_time.md)
- Ретрансляция между подсетями: [DHCP Relay](./dhcp_relay.md)
- Атаки и защита: [DHCP Security](./dhcp_security.md)
- Спецификация: [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131), [RFC 2132](https://datatracker.ietf.org/doc/html/rfc2132)
