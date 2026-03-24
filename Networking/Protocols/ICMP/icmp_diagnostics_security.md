# ICMP: Диагностика и безопасность

## Диагностика проблем с ICMP

### Блокировка ICMP файрволом

**Симптомы:**

- `ping` не работает, но TCP-соединения устанавливаются
- `traceroute` показывает `* * *` на некоторых хопах

**Проверка:**

```bash
# Проверка доступности ICMP
tcpdump -i eth0 icmp
tcpdump -i eth0 'icmp[0] = 8 or icmp[0] = 0'
```

### Destination Unreachable (Type 3)

**Проблема:** Получение ICMP Type 3 указывает на проблемы доставки пакетов.

**Диагностика по кодам:**

```bash
# Net Unreachable (Code 0) — нет маршрута
tcpdump -i eth0 'icmp[0] = 3 and icmp[1] = 0'

# Host Unreachable (Code 1) — хост не отвечает
tcpdump -i eth0 'icmp[0] = 3 and icmp[1] = 1'

# Port Unreachable (Code 3) — UDP порт закрыт
tcpdump -i eth0 'icmp[0] = 3 and icmp[1] = 3'

# Fragmentation Needed (Code 4) — требуется фрагментация
tcpdump -i eth0 'icmp[0] = 3 and icmp[1] = 4'
```

**Интерпретация:**

| Код | Возможная причина | Решение |
|-----|-------------------|---------|
| 0 (Net Unreachable) | Нет маршрута в таблице маршрутизации | Проверить маршруты на шлюзе |
| 1 (Host Unreachable) | Хост выключен, ARP не отвечает | Проверить доступность хоста |
| 3 (Port Unreachable) | UDP порт закрыт | Проверить службу на хосте |
| 4 (Fragmentation Needed) | Пакет > MTU, флаг DF | Включить PMTUD или уменьшить MTU |

### Fragmentation Needed (Type 3, Code 4)

**Проблема:** Маршрутизатор отправляет ICMP "Fragmentation Needed", если пакет больше MTU следующего звена, а флаг DF (Don't Fragment) установлен.

**Решение:**

```bash
# Проверка MTU пути
tracepath example.com

# Временное решение (не рекомендуется)
ip link set dev eth0 mtu 1400
```

---

## Безопасность и ICMP

### ICMP в security-политиках

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

---

### ICMP-атаки

| Атака | Описание | Защита |
|-------|----------|--------|
| **Ping Flood** | Злоумышленник отправляет большой объем Echo Request | Rate limiting, фильтрация на периметре |
| **Ping of Death** | Отправка фрагментированных пакетов >65535 байт | Патчи ОС (устаревшая уязвимость) |
| **Smurf Attack** | Amplification-атака через broadcast-адрес | Блокировка directed broadcast |
| **ICMP Redirect Attack** | Ложные Redirect для перенаправления трафика | Игнорировать Redirect на хостах |
| **Destination Unreachable Spoofing** | Подделка ICMP Type 3 для разрыва TCP-соединений | Валидация ICMP-источника, TCP MD5 |

---

## ICMP в IPv6

В IPv6 ICMP стал **обязательным** и переименован в **ICMPv6** (RFC 4443). Дополнительные функции:

- **NDP (Neighbor Discovery Protocol)** — замена ARP
- **SLAAC (Stateless Address Autoconfiguration)** — автоконфигурация адресов
- **MLD (Multicast Listener Discovery)** — управление multicast-группами

---

## Связанные документы

**Протоколы:**
- **[IP](../ip.md)** — сетевой уровень
- **[TCP](../TCP/overview.md)** — транспортный уровень
- **[ARP](../arp.md)** — разрешение адресов

**Диагностика:**
- **[ping](../../Linux/Diagnostics/Networking/ping.md)** — проверка доступности
- **[traceroute](../../Linux/Diagnostics/Networking/traceroute_mtr.md)** — трассировка маршрута

**Безопасность:**
- **[iptables](../../Security/Firewalls/iptables.md)** — настройка файрвола
- **[TCP MD5](../TCP/tcp_md5_signature.md)** — защита от spoofing

## RFC

- **RFC 792** — спецификация ICMP для IPv4
- **RFC 4443** — ICMPv6 для IPv6 (обязательный протокол для IPv6)
- **RFC 4884** — Extended ICMP
