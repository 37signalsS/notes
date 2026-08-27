# ICMP Destination Unreachable (Цель недоступна)

## Определения

**Destination Unreachable (Тип 3 для IPv4, Тип 1 для IPv6)** — служебное сообщение протокола ICMP, уведомляющее отправителя о невозможности доставки IP-пакета до конечного узла или конкретного приложения.

**Основные параметры:**
- **IPv4:** Тип 3.
- **IPv6:** Тип 1.
- **Код (Code):** 0–15 (детализация конкретной причины отказа в доставке).

Сообщение ICMP Destination Unreachable всегда содержит **оригинальный IP-заголовок** проблемного пакета (а в IPv4 также первые 64 байта данных), что позволяет отправителю идентифицировать, какой именно трафик был затронт.

## Основные концепции

### Назначение

Сообщения о недостижимости критически важны для стабильности сети:
1.  **Оптимизация ресурсов:** позволяют стеку протоколов (TCP/UDP) немедленно прекратить бесперспивные повторные передачи, не дожидаясь таймаутов на прикладном уровне.
2.  **Диагностика:** помогают точно локализовать место разрыва связи (маршрутизатор или хост) и причину (нет маршрута, порт закрыт, запрещено фильтром).
3.  **Path MTU Discovery (PMTUD):** в IPv4 используется специальный код (Type 3 Code 4) для уведомления о том, что пакет слишком велик для передачи через сегмент сети без фрагментации.

### Источники сообщений

| Источник | Генерируемые причины |
| :--- | :--- |
| **Маршрутизатор** | Нет пути к сети, хост не отвечает на ARP/NDP, пакет слишком велик (DF-бит), доступ запрещен правилами (ACL). |
| **Хост назначения** | Нужный протокол не поддерживается, порт (приложение) не прослушивается. |

### Таблица основных кодов (v4 vs v6)

| Описание причины | Код IPv4 (Type 3) | Код IPv6 (Type 1) | Примечание |
| :--- | :--- | :--- | :--- |
| **No Route to Destination** | 0 (Net Unr.) | 0 (No route) | Маршрутизатор не знает, куда слать пакет. |
| **Host/Address Unreachable** | 1 (Host Unr.) | 3 (Address Unr.) | Ошибка разрешения L2 (ARP/NDP) или узел выключен. |
| **Protocol Unreachable** | 2 | — | В IPv6 заменено на ICMPv6 Type 4 (Parameter Problem). |
| **Port Unreachable** | 3 | 4 | UDP-порт закрыт. Для TCP используется флаг RST. |
| **Fragmentation Needed** | 4 | **Type 2** | **Критично для PMTUD.** В IPv6 вынесено в отдельный тип. |
| **Source Route Failed** | 5 | — | Ошибка при использовании опции Source Routing. |
| **Communication Prohibited** | 9, 10, 13 | 1 | Пакет отброшен брандмауэром или ACL (цель `REJECT`). |
| **Source Address Failed** | — | 5 | Нарушение политики входящей маршрутизации (IPv6). |

**Полные коды IPv4 (RFC 792, дополнения):**

| Код | Название | Описание | Использование |
| :--- | :--- | :--- | :--- |
| 0 | Net Unreachable | Маршрутизатор не знает путь к сети. | Часто в таблицах маршрутов с нулевым next-hop. |
| 1 | Host Unreachable | ARP/NDP не удался, хост недоступен на L2. | L2-проблемы, выключенный хост, защита от спуфинга. |
| 2 | Protocol Unreachable | Протокол (TCP/UDP/..) не поддерживается хостом. | Host-only без указанного протокола. |
| 3 | Port Unreachable | Порт закрыт (UDP). | Открытые порты определяются по отсутствию ответа. |
| 4 | Fragmentation Needed | Пакет > MTU и DF=1. Содержит Next-Hop MTU. | PMTUD, MSS Clamping. |
| 5 | Source Route Failed | Опция Source Routing не удалась. | Устаревшая, почти не используется. |
| 6 | Destination Network Unknown | Сеть назначения неизвестна. | Редко, в старом оборудовании. |
| 7 | Destination Host Unknown | Хост назначения неизвестен. | На этапе ARP. |
| 8 | Source Host Isolated | Изоляция источника (policy). | IEEE 802.1X, защита. |
| 9 | Communication Admin Prohibited | Доступ запрещен административно (v4). | Аналогично Code 13 в некоторых реализациях. |
| 10 | Network Unreachable for ToS | Нет маршрута для указанного ToS. | QoS-aware routing. |
| 11 | Communication Admin Prohibited | Доступ запрещен административно. | ACL, iptables REJECT в RHEL/CentOS. |
| 12 | Reach Error | Ошибка достижимости (v6). | Не используется в IPv4. |
| 13 | Precedence Uniq. Violation | Нарушениеprecedence (v4). | Устаревшая QoS. |
| 14 | Precedence Cutoff | Превышен precedence (v4). | Устаревшая QoS. |
| 15 | Best-effort precedence | Лучшее effort precedence (v4). | Устаревшая. |
| 16–15 | Reserved | Зарезервировано. | — |

**Полные коды ICMPv6 (Type 1, RFC 4443):**

| Код | Название | Описание |
| :--- | :--- | :--- |
| 0 | No Route | Маршрут не найден (IPv6 аналог Net Unreachable). |
| 1 | Communication Admin Prohibited | Доступ запрещен ACL/firewall. |
| 2 | Beyond Scope of Source Address | Адрес назначения вне зоны источника. |
| 3 | Address Unreachable | L2 недоступен (NDP сбой). |
| 4 | Port Unreachable | Порт закрыт (UDP/TCP). |
| 5 | Source Address Failed Policy | Нарушение политики входящей маршрутизации. |
| 6 | Reject Route | Маршрут помечен как reject. |
| 7 | Error in Source Routing Header | Ошибка в заголовке Source Routing. |

### Формат сообщения

ICMP Destination Unreachable состоит из:
1.  **ICMP-заголовка:** Type (3 для IPv4), Code, Checksum.
2.  **Поля "не используется" (Unused):** 32 бита в IPv4 / 32 бита в IPv6.
3.  **Оригинальный IP-заголовок:** Первые 20+ байтов забракованного пакета (в IPv4 включает также первые 64 байта полезной нагрузки — RFC 792).
4.  **Next-Hop MTU (Code 4):** Дополнительное поле в 32 бита, указывающее MTU следующего узла (только для Code 4).

Для IPv6: сообщение содержит оригинальный IPv6 заголовок (40 байт) + первые 1280 байт данных (RFC 4443).

## Практические сценарии

### Настройка через iptables / nftables

**REJECT vs DROP:** при настройке брандмауэра администратор выбирает тип реакции на запрещенный пакет:

*   **DROP:** пакет молча удаляется. Отправитель долго ждёт таймаута, прежде чем выдать ошибку. Затрудняет сетевую разведку.
*   **REJECT:** пакет отбрасывается с отправкой ICMP Destination Unreachable (обычно Code 13 для v4 или Code 1 для v6). Позволяет приложению мгновенно выдать ошибку "Connection Refused".

**iptables (IPv4):**
```bash
# REJECT с ICMP Port Unreachable для UDP
iptables -A INPUT -p udp -j REJECT --reject-with icmp-port-unreachable

# REJECT с ICMP Host Unreachable
iptables -A INPUT -p tcp -j REJECT --reject-with icmp-host-unreachable

# REJECT с ICMP Admin Prohibited (Code 13)
iptables -A INPUT -j REJECT --reject-with icmp-admin-prohibited
```

**ip6tables (IPv6):**
```bash
# REJECT с ICMPv6 Port Unreachable для UDP
ip6tables -A INPUT -p udp -j REJECT --reject-with icmp6-port-unreachable

# REJECT с ICMPv6 Address Unreachable
ip6tables -A INPUT -p tcp -j REJECT --reject-with icmp6-addr-unreachable
```

**nftables (современный):**
```bash
# таблица для IPv4
nft add table inet filter
nft 'add chain inet filter input { type filter hook input priority 0; }'
nft add rule inet filter input ip protocol udp reject with icmp type admin-prohibited
nft add rule inet filter input ip protocol tcp reject with icmp type port-unreachable

# таблица для IPv6
nft add table inet filter6
nft 'add chain inet filter6 input { type filter hook input priority 0; }'
nft add rule inet filter6 input ip6 nexthdr udp reject with icmpv6 type port-unreachable
```

**Проверка:**
```bash
# IPv4
echo "test" | nc -u -w1 192.168.1.100 9999
# → connect: No route to host (если REJECT)

# IPv6
echo "test" | nc -u -w1 ::1 9999
# → connect: No route to host (если REJECT)

# Проверка правил
iptables -L INPUT -v -n | grep REJECT
ip6tables -L INPUT -v -n | grep REJECT
```

### Недостижимость сети (IPv4 Code 0 / IPv6 Code 0)

**Сценарий:** ошибка в таблице маршрутизации или падение магистрального канала.

1.  Пакет приходит на маршрутизатор.
2.  Маршрутизатор не находит подходящего маршрута (включая `default gateway`).
3.  Маршрутизатор отбрасывает пакет и отправляет отправителю ICMP Destination Unreachable (Code 0).
4.  **Реакция:** приложение получает системную ошибку "No route to host".

**Диагностика:**
```bash
# Проверка маршрута
ip route get 10.10.10.100
# → RTNETLINK answers: Network is unreachable

# Просмотр маршрутов
ip route show
# → следует проверить наличие default маршрута

# tcpdump для подтверждения ICMP
sudo tcpdump -ni eth0 'icmp and icmp[0] = 3 and icmp[1] = 0'
# → IP router.local > client.local: ICMP 10.10.10.100 unreachable (net unreachable), length 48
```

### Порт закрыт (IPv4 Code 3 / IPv6 Code 4)

**Сценарий:** попытка обращения к UDP-сервису, который не запущен.

1.  Пакет успешно доставляется на целевой хост.
2.  Ядро ОС видит, что на указанном порту нет слушающего сокета.
3.  ОС отправляет ICMP Port Unreachable (IPv4 Code 3, IPv6 Code 4).
4.  **Диагностика:** утилиты сканирования (nmap) определяют закрытые UDP-порты именно по этому сообщению. Если ответа нет (DROP), порт считается `open|filtered`.

**Проверка:**
```bash
# Проверка порта с помощью nc
nc -u -zv 192.168.1.100 12345
# → nc: connect to 192.168.1.100 port 12345 (udp) failed: No route to host

# Анализ с помощью nmap
nmap -sU -p 12345 192.168.1.100
# → 12345/udp closed (ICMP Destination Unreachable получен)

# Просмотр входящих ICMP с кодом 3
sudo tcpdump -ni eth0 'icmp and icmp[1] = 3'
# → IP target.local > client.local: ICMP 192.168.1.100 udp port 12345 unreachable, length 56
```

**Для TCP:** вместо ICMP Port Unreachable хост отправляет TCP RST (флаг сброса соединения). Это происходит на уровне TCP, так как ICMP Port Unreachable зарезервирован для UDP и других протоколов без установки соединения.

### Требуется фрагментация и PMTUD (IPv4 Code 4)

**Сценарий:** работа через туннели (VPN/PPPoE) с уменьшенным MTU.

1.  Хост отправляет пакет 1500 байт с флагом **DF (Don't Fragment)**.
2.  Маршрутизатор туннеля видит, что MTU линка — 1400 байт.
3.  Маршрутизатор отбрасывает пакет и шлёт ICMP Type 3 Code 4, указывая `Next-Hop MTU: 1400`.
4.  **Проблема:** если этот ICMP-пакет заблокирован ("чёрная дыра"), соединение зависнет после передачи первых данных (например, SSH-баннера).

**Диагностика PMTUD:**
```bash
# Тест с DF=1 и разными размерами
ping -M do -s 1472 10.10.10.100
# → Если работает: MTU >= 1500. Если "Message too long": PMTUD сломан.

# Просмотр ICMP PTB
sudo tcpdump -ni eth0 'icmp and icmp[0] = 3 and icmp[1] = 4'
# → IP router.local > client.local: ICMP 10.10.10.100 destination-unreachable (fragmentation needed and DF set), length 48

# Проверка TCP MSS
ss -ni | grep -o 'mss:[0-9]*'
# → mss:1400 (если PMTUD корректно уменьшил размер)
```

**Исправление:**
```bash
# sysctl: включить PMTU Discovery (по умолчанию включено)
sysctl -w net.ipv4.ip_no_pmtu_disc=0

# или настроить MSS Clamping на border router (nftables)
nft add rule inet filter forward tcp flags syn tcp option max segment size set 1380
```

### Блокировка администратором (Code 11/13)

**Сценарий:** firewall (iptables REJECT) или ACL блокируют трафик.

```bash
# Пример правила iptables с REJECT
iptables -A FORWARD -s 10.0.0.0/8 -d 192.168.0.0/16 -j REJECT --reject-with icmp-admin-prohibited

# Проверка
sudo tcpdump -ni eth0 'icmp and icmp[0] = 3 and icmp[1] = 13'
# → IP firewall.local > client.local: ICMP 192.168.0.50 comm administratively prohibited, length 76
```

**Интерпретация:** получение Code 13 означает, что пакет нарушил политику доступа (а не просто попал на закрытый порт). Это может указывать на:
- Наличие брандмауэра (информация для разведки).
- Неправильную конфигурацию политик (false positive).
- Активное блокирование (DDoS-защита, bogon filtering).

### OS Fingerprinting через ответы

Различия в ICMP Destination Unreachable между ОС позволяют проводить разведку:

| Параметр | Linux | Windows | Cisco IOS |
| :--- | :--- | :--- | :--- |
| **IP-ID прибавка** | +1 | +1 | 0 |
| **TTL ответа** | 64 | 128 | 255 |
| **Размер пакета** | Минимальный | +4 байта | Минимальный |
| **Код при блокировке** | Code 13 | Code 13 | Code 13 |
| **Ответ на broadcast** | Игнорирует | ICMP (безопаснее) | Игнорирует |

**Сбор информации:**
```bash
# Отправляем UDP на закрытый порт и анализируем ответ
hping3 -c 1 -2 -p 9999 -V 192.168.1.100
# → TTL=64 → Linux, TTL=128 → Windows, TTL=255 → сетевое оборудование
```

### Мониторинг и отладка

**tcpdump:** фильтры для захвата ICMP Destination Unreachable:

```bash
# Все ICMP Type 3
sudo tcpdump -ni eth0 'icmp[0] = 3'

# Только Port Unreachable
sudo tcpdump -ni eth0 'icmp[0] = 3 and icmp[1] = 3'

# Fragmentation Needed (PMTUD)
sudo tcpdump -ni eth0 'icmp[0] = 3 and icmp[1] = 4'

# ICMPv6 Type 1
sudo tcpdump -ni eth0 'icmp6 and ip6[40] = 1'
```

**Статистика из ядра:**
```bash
# Статистика ICMPv4
cat /proc/net/snmp | grep -i icmp
# → Icmp: InErrors, InDestUnreachs, InTimeExcds, OutDestUnreachs

# Статистика ICMPv6
cat /proc/net/snmp6 | grep -i icmp
# → Icmp6: InDestUnreachs, OutDestUnreachs

# nstat — легковесный счётчик
nstat -az | grep -i icmp
nstat -az | grep -i destunreach
```

**Аномалии к отслеживанию:**
- Внезапный рост `InDestUnreachs` — может указывать на сетевую проблему или атаку.
- `OutDestUnreachs` с неожиданными кодами — проверьте правила firewall.
- `InErrors` повышение — возможна злоупотребление ICMP rate limiting (см. ниже).

### Защита от злоупотребления

ICMP Destination Unreachable может быть использован в атаках:

1.  **ICMP Flood:** массовая генерация Destination Unreachable может перегрузить процессор.
2.  **Rate Limiting:** kernel Linux автоматически рейт-лимитит ICMP:

```bash
# Просмотр настроек
sysctl net.ipv4.icmp_ratelimit    # 1000 сообщений/сек
sysctl net.ipv4.icmp_ratelimit_mask # 880 = 0x370 (типы 4,5,6,7,8,9)
sysctl net.ipv4.icmp_errors_use_inbound_ifaddr
sysctl net.ipv4.icmp_echo_ignore_broadcasts

# Тонкая настройка
echo 'net.ipv4.icmp_ratelimit = 100' >> /etc/sysctl.d/99-icmp-hardening.conf
echo 'net.ipv4.icmp_errors_use_inbound_ifaddr = 1' >> /etc/sysctl.d/99-icmp-hardening.conf
```

3.  **Защита через iptables:**
```bash
# Ограничение Destination Unreachable до 5/сек
iptables -A OUTPUT -p icmp --icmp-type destination-unreachable -m limit --limit 5/sec --limit-burst 10 -j ACCEPT
iptables -A OUTPUT -p icmp --icmp-type destination-unreachable -j DROP
```

## Дополнительная информация

*   **[Обзор протокола ICMP](./icmp_overview.md)** — общая справочная таблица типов ICMP (IPv4/IPv6), структура сообщений, RFC 4844.
*   **[MTU, PMTUD и диагностика в VPN/облаках](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — детальный разбор "чёрных дыр", MSS Clamping, настройка в туннелях и облаке.

**Стандарты:** [RFC 792](https://rfc-editor.org/rfc/rfc792.html) (IPv4), [RFC 4443](https://rfc-editor.org/rfc/rfc4443.html) (IPv6), [RFC 1191](https://rfc-editor.org/rfc/rfc1191.html) (PMTUD), [RFC 8200](https://rfc-editor.org/rfc/rfc8200.html) (IPv6).
