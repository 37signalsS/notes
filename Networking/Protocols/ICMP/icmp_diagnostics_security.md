# ICMP: Диагностика и безопасность

## Определения

**Диагностика ICMP** — использование ICMP-сообщений для выявления проблем сети и настройки security-политик.

**ICMPv6** — расширенная версия ICMP для IPv6 (RFC 4443), обязательный протокол, включающий NDP, SLAAC, MLD.

## Основные концепции

### Блокировка ICMP файрволом

При блокировке ICMP на файрволе наблюдаются:

- `ping` не работает, но TCP-соединения устанавливаются
- `traceroute` показывает `* * *` на некоторых хопах
- PMTUD не работает (black hole), если заблокирован Type 3 Code 4

**Проверка:**

```bash
tcpdump -i eth0 icmp
tcpdump -i eth0 'icmp[0] = 8 or icmp[0] = 0'
```

### Рекомендуемые security-политики

| Тип ICMP | Политика | Обоснование |
|----------|----------|-------------|
| Echo Request/Reply | Разрешить с rate limiting | Мониторинг доступности |
| Destination Unreachable | Разрешить | Критично для TCP/UDP |
| Time Exceeded | Разрешить | Необходим для traceroute |
| Redirect | Блокировать | Риск атак перенаправления |
| Timestamp | Блокировать | Утечка информации |

### ICMP-атаки

| Атака | Описание | Защита |
|-------|----------|--------|
| **Ping Flood** | Большой объём Echo Request | Rate limiting, фильтрация на периметре |
| **Ping of Death** | Фрагментированные пакеты >65535 байт | Патчи ОС (устаревшая уязвимость) |
| **Smurf Attack** | Amplification через broadcast | Блокировка directed broadcast |
| **ICMP Redirect Attack** | Ложные Redirect для перенаправления трафика | Игнорировать Redirect на хостах |
| **Destination Unreachable Spoofing** | Подделка ICMP Type 3 для разрыва TCP-соединений | Валидация ICMP-источника |

### ICMP в IPv6 (ICMPv6)

В IPv6 ICMP стал **обязательным** и получил дополнительные функции:

- **NDP (Neighbor Discovery Protocol)** — замена ARP
- **SLAAC (Stateless Address Autoconfiguration)** — автоконфигурация адресов
- **MLD (Multicast Listener Discovery)** — управление multicast-группами

## Практические сценарии

### Настройка iptables для ICMP

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

### Диагностика MTU пути

При получении ICMP Fragmentation Needed (Type 3 Code 4) — [подробнее в icmp_destination_unreachable](./icmp_destination_unreachable.md#fragmentation-needed-but-df-set-type-3-code-4):

```bash
# Проверка MTU пути
tracepath example.com

# Временное решение (не рекомендуется для продакшена)
ip link set dev eth0 mtu 1400
```

Подробнее: [Path MTU Discovery](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md#path-mtu-discovery-pmtud).
