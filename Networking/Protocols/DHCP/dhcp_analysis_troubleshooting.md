# Анализ DHCP-трафика и troubleshooting

## Анализ DHCP-трафика в Wireshark

**Цель:** Изучить процесс взаимодействия DHCP-клиента и DHCP-сервера с помощью анализа сетевого трафика.

### Шаг 1: Запуск захвата трафика

1. Запустите **Wireshark** от имени администратора
2. Выберите основной сетевой интерфейс (например, `Ethernet` или `Wi-Fi`)
3. Начните захват пакетов

### Шаг 2: Генерация DHCP-трафика

| ОС | Команды |
|----|---------|
| **Windows** | 1. Откройте командную строку от имени администратора<br>2. `ipconfig /release` — освободить текущий IP<br>3. `ipconfig /renew` — получить новый IP |
| **macOS** | 1. Откройте терминал<br>2. `sudo ipconfig set en0 none` — освободить IP<br>3. `sudo ipconfig set en0 dhcp` — получить новый IP |
| **Linux** | 1. `sudo dhclient -r eth0` — освободить IP<br>2. `sudo dhclient eth0` — получить новый IP |

### Шаг 3: Анализ захваченных пакетов

1. Остановите захват в Wireshark
2. Примените фильтр: `dhcp` или `bootp`
3. Изучите последовательность DORA:
   - **DHCP Discover** — широковещательный запрос от клиента
   - **DHCP Offer** — предложение от сервера
   - **DHCP Request** — запрос выбранного предложения
   - **DHCP Ack** — подтверждение выдачи адреса

### Что наблюдать

| Пакет | Поля для анализа |
|-------|------------------|
| **DHCP Discover** | `op=1`, `chaddr` (MAC клиента), `ciaddr=0.0.0.0`, Message Type=Discover |
| **DHCP Offer** | `op=2`, `yiaddr` (предлагаемый IP), `siaddr` (TFTP сервер), Message Type=Offer, Bootp flags (Unicast/Broadcast) |
| **DHCP Request** | Requested IP Address, DHCP Server Identifier, Message Type=Request |
| **DHCP Ack** | `yiaddr` (выданный IP), Subnet Mask, Router, DNS, Lease Time, Renewal Time (T1) |

### Пример вывода Wireshark

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

---

## Освобождение и обновление DHCP-аренды

При изменении конфигурации DHCP-сервера или при возникновении проблем с подключением может потребоваться принудительное обновление аренды на клиенте.

**Применение:**
- После изменения пула адресов на сервере
- При смене DNS-серверов или шлюза
- При устранении конфликтов IP-адресов
- После исправления ошибок в конфигурации DHCP

### Команды для освобождения адреса

| ОС | Команда |
|----|---------|
| **Windows** | `ipconfig /release` (в командной строке от имени администратора) |
| **macOS** | `sudo ipconfig set en0 none` (в терминале) |
| **Linux** | `sudo ifdown eth0` или `sudo dhclient -r eth0` (для интерфейса eth0) |

### Команды для обновления адреса

| ОС | Команда |
|----|---------|
| **Windows** | `ipconfig /renew` |
| **macOS** | `sudo ipconfig set en0 DHCP` |
| **Linux** | `sudo ifup eth0` или `sudo dhclient eth0` |

---

## Авторитатный и неавторитативный DHCP-сервер

Опция `authoritative` в конфигурации DHCP-сервера определяет его поведение при обработке некорректных запросов.

### Авторитативный (Authoritative) сервер

Считается "главным" для данной подсети. Если такой сервер получает от клиента `DHCPREQUEST` с IP-адресом, который не принадлежит его пулу или некорректен для данной сети, он отправит клиенту сообщение `DHCPNAK`. Это заставит клиента прекратить использование неверного адреса и заново запустить процесс DORA для получения корректного адреса.

**Пример:** Сотрудник приносит рабочий ноутбук из дома. Ноутбук пытается использовать свой домашний IP-адрес в корпоративной сети. Авторитативный DHCP-сервер немедленно отправит `DHCPNAK`, и ноутбук получит новый, корпоративный IP.

### Неавторитативный (Non-authoritative) сервер

Если сервер не является авторитативным, он просто проигнорирует некорректный `DHCPREQUEST`. Клиент будет продолжать использовать неверный адрес до истечения его срока аренды, и все это время не сможет нормально работать в сети.

**Рекомендация:** В каждой подсети должен быть только один авторитативный DHCP-сервер.

---

## Типичные проблемы и решения

| Проблема | Симптомы | Решение |
|----------|----------|---------|
| **Клиент не получает IP** | `ipconfig` показывает `169.254.x.x` (APIPA) | Проверить доступность DHCP-сервера, наличие свободных адресов в пуле |
| **Конфликт IP-адресов** | Ошибки подключения, DHCPDECLINE от клиента | Включить ping check на сервере, проверить статические назначения |
| **Долгое получение IP** | Задержка 10–30 секунд при подключении | Проверить задержку сети до DHCP-сервера, настроить DHCP Relay |
| **Неверные параметры** | Неправильный шлюз, DNS | Проверить конфигурацию scope на DHCP-сервере |

## Связанные документы

- **[DHCP Overview](./dhcp_overview.md)** — общая информация, процесс DORA
- **[Время аренды](./dhcp_lease_time.md)** — Lease Time, продление
- **[DHCP Relay](./dhcp_relay.md)** — ретрансляция между подсетями
- **[Безопасность DHCP](./dhcp_security.md)** — атаки и защита

## RFC

- **RFC 2131** — спецификация DHCP
- **RFC 2132** — DHCP опции
