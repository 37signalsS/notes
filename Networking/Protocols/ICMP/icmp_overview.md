# Протокол ICMP (Internet Control Message Protocol) — Обзор

## Определения

**ICMP (Internet Control Message Protocol)** — служебный протокол сетевого уровня (L3), используемый устройствами IP-сети для передачи сообщений об ошибках, управления и диагностики. ICMP является неотъемлемой частью стека TCP/IP и работает поверх [IP](../IP_addressing/ip_overview.md), дополняя его механизм обратной связи.

**Ключевая особенность:** ICMP не передаёт пользовательские данные в традиционном смысле, а служит для обмена управляющей информацией между маршрутизаторами и хостами.

**Место в модели ISO/OSI:** ICMP относится к **сетевому уровню** (L3), так как решает задачи этого уровня, хотя технически его пакеты инкапсулируются в IP-дейтаграммы. Спецификация описана в [RFC 792](https://www.rfc-editor.org/rfc/rfc792) (IPv4) и [RFC 4443](https://www.rfc-editor.org/rfc/rfc4443) (IPv6).

**Номера протоколов IP:** ICMP для IPv4 инкапсулируется в IP-пакет с номером протокола `1`; ICMPv6 для IPv6 — с номером протокола `58`.

## Основные концепции

### Назначение ICMP

1. **Диагностика сети** — проверка доступности узлов (`ping`) и трассировка маршрута (`traceroute`).
2. **Сообщения об ошибках** — уведомление отправителя о невозможности доставить пакет, истечении времени жизни (TTL) или необходимости фрагментации.
3. **Управление маршрутизацией** — оптимизация путей доставки пакетов через Redirect-сообщения.
4. **Механизмы IPv6 (ICMPv6)** — заменяет ARP через Neighbor Discovery (NDP), обеспечивает автоматическую настройку адресов (SLAAC) и обнаружение Path MTU.

### Классификация сообщений ICMP

ICMP-сообщения подразделяются на **типы** (Type) и **коды** (Code). Каждый тип описывает категорию события, а код — конкретную причину. Полный перечень ниже.

#### Справочная таблица типов ICMP (IPv4, RFC 792 + дополнения)

| Тип | Код | Название | Краткое назначение |
| :--- | :--- | :--- | :--- |
| **0** | 0 | Echo Reply | Ответ на ICMP Echo Request (ping). |
| **3** | 0–15 | Destination Unreachable | Цель недоступна (см. таблицу кодов ниже). |
| **4** | 0 | Source Quench | [Устарел, deprecated RFC 6633] Управление перегрузкой. |
| **5** | 0–3 | Redirect | Оптимизация маршрута через альтернативный шлюз. |
| **8** | 0 | Echo Request | Запрос проверки доступности (ping, `traceroute -I`). |
| **11** | 0–1 | Time Exceeded | TTL достиг 0 (Code 0) или таймаут сборки фрагментов (Code 1). |
| **12** | 0–2 | Parameter Problem | Ошибка в IP-заголовке (неверный бит, опция). |
| **13 / 14** | 0 | Timestamp / Timestamp Reply | Запрос/ответ с временными метками. |
| **15 / 16** | 0 | Information Request/Reply | Устаревшие типы для определения сети. |

**Коды Destination Unreachable (Type 3, IPv4):**

| Код | Описание |
| :--- | :--- |
| 0 | Net Unreachable — маршрутизатор не знает путь к сети. |
| 1 | Host Unreachable — хост недоступен (ARP/NDP не удался). |
| 2 | Protocol Unreachable — протокол не поддерживается хостом. |
| 3 | Port Unreachable — порт закрыт (UDP); для TCP используется RST. |
| 4 | Fragmentation Needed & DF Set — **ключевой для PMTUD**. |
| 5 | Source Route Failed — ошибка опции источникового маршрута. |
| 6 | Destination Network Unknown — сеть назначения неизвестна. |
| 7 | Destination Host Unknown — хост назначения неизвестен. |
| 9, 10 | Communication Prohibited — доступ запрещён политикой. |
| 13 | Communication Administratively Prohibited — блокировка ACL/firewall. |

#### Ключевые типы ICMPv6 (RFC 4443 + RFC 4861/4862)

| Тип | Название | Краткое назначение |
| :--- | :--- | :--- |
| **1** | Destination Unreachable | Ошибки доставки (аналог v4 Type 3). |
| **2** | Packet Too Big | Пакет превышает MTU пути; **ключевой для IPv6 PMTUD**. |
| **3** | Time Exceeded | TTL (Hop Limit) = 0 или таймаут сборки фрагментов. |
| **4** | Parameter Problem | Ошибка в заголовке IPv6 или расширении. |
| **128 / 129** | Echo Request / Reply | Ping в IPv6. |
| **130–132** | MLD | Multicast Listener Discovery (замена IGMP для IPv6). |
| **133** | Router Solicitation (RS) | Хост запрашивает Router Advertisement. |
| **134** | Router Advertisement (RA) | Рекламирует префиксы, параметры MTU, TTL (SLAAC). |
| **135** | Neighbor Solicitation (NS) | Замена ARP-запросу; резолвинг L3→L2. |
| **136** | Neighbor Advertisement (NA) | Замена ARP-ответу; отвечает на NS. |
| **137** | Redirect Message | Оптимизация маршрута для хоста. |

### Типы сетевых ошибок

ICMP помогает диагностировать два типа проблем:

*   **Спонтанные (временные) ошибки** — проблемы, которые могут разрешиться при повторной отправке (переполнение буфера, временная перегрузка).
*   **Постоянные (структурные) ошибки** — требуют вмешательства:
    *   TTL пакета достиг 0 (петля маршрутизации).
    *   Отсутствует маршрут до сети назначения.
    *   Блокировка трафика брандмауэром.
    *   Неправильная конфигурация MTU (Black Hole).

**Важное правило:** ICMP-сообщения об ошибках никогда не генерируются в ответ на другие ICMP-сообщения об ошибках, чтобы избежать бесконечных циклов трафика. Единственное исключение — сообщения **Parameter Problem** и **Packet Too Big** в ICMPv6, которые могут генерироваться в ответ на любые пакеты, включая ICMP.

### Структура ICMP-сообщения

ICMP-пакет инкапсулируется непосредственно в IP-заголовок (номер протокола `1` для IPv4 и `58` для IPv6).

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
| :--- | :--- | :--- |
| **Type** | 8 бит | Тип сообщения (например, 3 — Destination Unreachable). |
| **Code** | 8 бит | Код (уточнение причины, например, 3 — Port Unreachable). |
| **Checksum** | 16 бит | Контрольная сумма всего ICMP-сообщения. |
| **Variable Data** | Переменная | Зависит от типа; в сообщениях об ошибках содержит заголовок и часть данных проблемного пакета. |

**Особенности контрольной суммы:**

*   Checksum покрывает весь ICMP-пакет, включая переменную часть.
*   В IPv6 контрольная сумма включает псевдозаголовок IPv6 (адреса источника/назначения и длина), что обеспечивает защиту от подмены адресов на сетевом уровне.
*   Для вычисления контрольной суммы поле Checksum временно обнуляется.
*   **Ошибка контрольной суммы:** если проверка не проходит, пакет отбрасывается без уведомления отправителя.

### RFC 4884: Расширенные сообщения ICMP

Современные реализации ICMP поддерживают расширения (Multi-Part Messages), которые позволяют включать в сообщение об ошибке дополнительные данные:

*   **MPLS Label Stack:** Информация о метках MPLS на узле, где возникла ошибка.
*   **Interface Information:** Данные об интерфейсе, на котором был отброшен пакет.
*   **Address Report:** Адреса, связанные с ошибкой (для NAT64/DNS64).

Это критично для работы `traceroute` в сетях провайдеров, где пакет может проходить через MPLS-туннели. Расширенные сообщения позволяют передавать информацию о конкретных метках MPLS и интерфейсах, что даёт полное представление о топологии сети провайдера.

**Структура расширенного сообщения (RFC 4884):**

```
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|     Type      |     Code      |          Checksum             |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Message Body (fixed)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
+                     ICMP Message Body                         |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                   Extensions Length (if present)            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Extension Object 1                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Extension Object 2                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### ICMP Rate Limiting (Ограничение скорости)

Для защиты от DoS-атак и экономии ресурсов CPU маршрутизаторы ограничивают количество ICMP-сообщений, генерируемых в секунду.

*   **Эффект на диагностику:** В выводе `mtr` или `traceroute` это выглядит как потери пакетов (Loss%) на промежуточных узлах при 0% потерь на конечном узле. Это не является признаком проблемы в сети.

**Настройка Rate Limiting в Linux (iptables):**

```bash
# Ограничить скорость ответов на Echo Request до 5 пакетов/секунду
iptables -A INPUT -p icmp --icmp-type echo-request \
  -m limit --limit 5/sec --limit-burst 10 -j ACCEPT
```

**Настройка Rate Limiting через sysctl:**

```bash
# Ограничение скорости ICMP в Linux
sysctl -w net.ipv4.icmp_ratelimit=100
# → Ограничивает количество ICMP-сообщений до 100 в секунду (с запасом)

sysctl -w net.ipv4.icmp_ratelimit_mask=880
# → Маска: тип 8 (Echo Request) и тип 0 (Echo Reply)
```

### Параметры фрагментации IP (ipfrag_*)

Linux ведет собственный reassembly-буфер для IP-фрагментов. Настройки фрагментации влияют на уязвимость к атакам и стабильность PMTUD.

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `net.ipv4.ipfrag_high_thresh` | Максимальный размер reassembly-буфера (байты) | `4194304` (4 MB) |
| `net.ipv4.ipfrag_low_thresh` | Порог для принудительной сборки фрагментов | `3145728` (3 MB) |
| `net.ipv4.ipfrag_time` | Время хранения фрагмента в буфере (секунды) | `15` |
| `net.ipv4.ipfrag_max_dist` | Включить случайный таймаут (защита от атак) | `1` |

```bash
# Проверка текущих значений
sysctl net.ipv4.ipfrag_high_thresh
sysctl net.ipv4.ipfrag_time

# Просмотр статистики фрагментации
cat /proc/net/snmp | grep -i frag
# → IpFragOKs  IpFragFails  IpFragCreates
# → 12345      0            67890

# Отслеживание несобранных фрагментов
nstat -az | grep -i frag
```

### DNS и PMTUD

DNS-запросы часто зависают из-за ICMP Black Hole, особенно при использовании DNS over TCP (большие ответы, AXFR) или DNSSEC.

**Симптом:** `dig` или `nslookup` зависают, хотя мелкие запросы проходят.

```bash
# Диагностика DNS + MTU
dig @8.8.8.8 example.com +tcp
# → Если зависает на получении ответа — проблема PMTUD

# Проверка MTU для DNS
ping -M do -s 1472 8.8.8.8
tracepath 8.8.8.8

# Решение: MSS Clamping для DNS-трафика
iptables -t mangle -A OUTPUT -p tcp --dport 53 -j TCPMSS --clamp-mss-to-pmtu
```

### ICMP Timestamp и Address Mask (deprecated)

**ICMP Timestamp Request (Type 13) / Reply (Type 14):**
- Используются для синхронизации времени и измерения RTT.
- Часто блокируются файрволами, так как泄露 информации о времени системы.
- Могут использоваться для OS fingerprinting.

**ICMP Address Mask Request (Type 17) / Reply (Type 18):**
- Исторический тип для запроса маски подсети.
- Может использоваться для сбора информации о сети (reconnaissance).
- **Рекомендация:** блокировать всегда.

```bash
# Блокировка Timestamp и Address Mask
iptables -A INPUT -p icmp --icmp-type timestamp-request -j DROP
iptables -A INPUT -p icmp --icmp-type address-mask-request -j DROP
```

### Path MTU Discovery и ICMP

**Path MTU Discovery (PMTUD)** — механизм определения минимального MTU на пути следования. Работает следующим образом:

1. Отправитель устанавливает флаг **DF (Don't Fragment)** и размер = PMTU.
2. Если MTU на промежуточном маршрутизаторе меньше — пакет отбрасывается.
3. Маршрутизатор возвращает ICMP-сообщение:
    *   **IPv4:** Type 3, Code 4 (Fragmentation Needed) с указанием следующего MTU.
    *   **IPv6:** Type 2 (Packet Too Big) с указанием следующего MTU.
4. Отправитель кэширует PMTU и снижает размер пакетов.

**Проблема PMTU Black Hole:** Если файрвол блокирует ICMP Type 3 Code 4 (IPv4) или Type 2 (IPv6), PMTUD ломается. Симптом: мелкие пакеты (DNS, SSH) проходят, большие (HTTP, SCP) зависают.

**Диагностика PMTUD:**

```bash
# Проверить работу PMTUD: ping с запретом фрагментации (DF=1)
ping -M do -s 1472 8.8.8.8
# → Если "Message too long" или пакет не проходит, MTU < 1500

# tracepath — автоматически определяет MTU на пути
tracepath -n 8.8.8.8
# → 1500 снизу, 1480 в туннеле — значит MTU=1480

# Захватить ICMP-сообщения о фрагментации
sudo tcpdump -i eth0 'icmp and (icmp[0] == 3 and icmp[1] == 4)'
# → покажет ICMP Type 3 Code 4 (Fragmentation Needed)
```

**Решение при PMTU Black Hole:**

```bash
# MSS Clamping через iptables — принудительно уменьшить MSS для TCP
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS \
  --clamp-mss-to-pmtu
# → Подбирает MSS на основе пути, избегая больших пакетов

# Или задать фиксированный MSS
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
  -o gre1 -j TCPMSS --set-mss 1360
```

**Проверка статистики ICMPv6 в Linux:**

```bash
# Статистика ICMPv6 из ядра
cat /proc/net/snmp6 | grep -i icmp6
# → Icmp6InMsgs  Icmp6InErrors  Icmp6InDestUnreachs  Icmp6InPktTooBigs  ...
# → 1234         0              3                    1

# Перехват только NDP-трафика (Neighbor Solicitation/Advertisement)
sudo tcpdump -i eth0 -n 'icmp6 && (ip6[40] == 135 || ip6[40] == 136)'
# → 12:34:56.789 IP6 fe80::1 > fd00::43: ICMP6, neighbor solicitation
#   12:34:57.012 IP6 fd00::43 > fe80::1: ICMP6, neighbor advertisement

# Проверка членства в мультикаст-группах IPv6
ip -6 maddr show
# → группы MLD, в т.ч. ff02::1 (все узлы) и ff02::2 (все роутеры)
```

### Эволюция: ICMPv4 vs ICMPv6

В сетях IPv6 ICMPv6 (протокол 58) объединяет функции нескольких протоколов:

1.  **Замена ARP:** Используется **Neighbor Discovery Protocol (NDP)** (Type 135/136).
2.  **Автонастройка (SLAAC):** Хосты получают префиксы через Router Advertisement (Type 134).
3.  **Path MTU Discovery (PMTUD):** Поскольку в IPv6 нет фрагментации на маршрутизаторах, сообщение **Packet Too Big** (Type 2) жизненно важно.
4.  **Multicast Listener Discovery (MLD):** Заменяет протокол IGMP.

**Критическое правило для IPv6:** Полное блокирование ICMPv6 делает узел неработоспособным в IPv6-сети. Минимально необходимо разрешить: NDP (Types 133–136), Packet Too Big (Type 2), Time Exceeded (Type 3), Destination Unreachable (Type 1).

### MLD и multicast в IPv6

MLD (Multicast Listener Discovery, Types 130–132) используется для управления membership в multicast-группах. В продакшене важно понимать:

- ** Solicitation (131):** хост запрашивает информацию о multicast-группах на сегменте.
- ** Report (132):** хост сообщает о желании получать multicast-трафик.
- ** Done (131):** хост покидает группу.

**Практика:** если MLD заблокирован на файрволе, multicast-сервисы (mDNS, LLMNR, DHCPv6 relay) перестают работать.

```bash
# Проверка multicast membership
ip -6 maddr show
# → ff02::1    all nodes on eth0
# → ff02::2    all routers on eth0
# → ff02::fb   mDNS on eth0

# Захват MLD
sudo tcpdump -i eth0 -n 'icmp6 && icmp6[0] >= 130 && icmp6[0] <= 132'
```

## Практические сценарии

### Диагностика доступности

| Тип | Код | Название | Использование |
| :--- | :--- | :--- | :--- |
| **8 / 0** | 0 | Echo Request/Reply | `ping` — проверка связности ([подробнее](./icmp_echo_ping.md)) |
| **128 / 129** | 0 | Echo Request/Reply (v6) | `ping6` — доступность в IPv6 |

**Базовые команды ping:**

```bash
# Проверка связности с ограничением количества пакетов
ping -c 4 8.8.8.8
# → PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
# 64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=10.2 ms
# ...
# — 8.8.8.8 ping statistics —
# 4 packets transmitted, 4 received, 0% packet loss

# Пинг с конкретного интерфейса/адреса
ping -I 10.0.0.5 8.8.8.8
# → отправляет запрос с указанного источника

# Пинг в IPv6 (Linux: ping -6, либо ping6 на старых системах)
ping -6 2001:4860:4860::8888
# → PING 2001:4860:4860::8888(2001:4860:4860::8888) 56 data bytes
# 64 bytes from 2001:4860:4863::8888: icmp_seq=1 ttl=117 time=10.5 ms

# Пинг широковещательного адреса IPv6 (все узлы в сегменте)
ping6 -c 2 ff02::1%eth0
# → обязательно указывать интерфейс через % или -I
```

**Коды возврата ping:**

| Код | Значение |
| :--- | :--- |
| 0 | Успех — получен хотя бы один ответ. |
| 1 | Ошибка — 100% потеря пакетов. |
| 2 | Системная ошибка — неверные параметры или сбой DNS. |

### Сообщения об ошибках

| Тип (v4/v6) | Код (v4/v6) | Название | Описание |
| :--- | :--- | :--- | :--- |
| **3 / 1** | 0–15 | Destination Unreachable | Цель недоступна ([подробнее](./icmp_destination_unreachable.md)) |
| **3 / 1** | **3 / 4** | **Port Unreachable** | UDP-порт закрыт на целевом хосте |
| **3 / 1** | **4 / —** | **Fragmentation Needed** | Проблема MTU (в v6 — Packet Too Big, Type 2) |
| **11 / 3** | 0 | Time Exceeded (TTL) | Основа работы `traceroute` ([подробнее](./icmp_time_exceeded.md)) |
| **5 / 137** | 0–3 | Redirect | Оптимизация маршрута ([подробнее](./icmp_redirect.md)) |
| **12 / 4** | 0–2 | Parameter Problem | Ошибка в IP-заголовке |

### Parameter Problem (Type 12)

Сообщение генерируется, когда маршрутизатор или хост обнаруживает ошибку в IP-заголовке пакета.

| Код | Название | Когда возникает |
| :--- | :--- | :--- |
| **0** | Pointer error | Указатель на ошибочный байт |
| **1** | Missing option | Обязательная опция отсутствует |
| **2** | Bad length | Неверная длина пакета |

**Практические сценарии:**
```bash
# Захват Parameter Problem
sudo tcpdump -i eth0 'icmp[0] == 12' -nn
# → IP router > client: ICMP parameter problem

# Частая причина: неверный MTU с опциями IP (длина заголовка > 20 байт)
# Пример: фрагментация пакета с опцией Record Route
```

### Диагностика и отладка в Linux

**Методология диагностики (bottom-up):** диагностика должна следовать иерархии уровней — от простого к сложному.

```bash
# === Уровень L3: проверка ICMP-связности ===

# 1. Базовый ping с таймаутом
ping -c 1 -W 2 8.8.8.8
# → 64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=10.2 ms  ✓
# → (или: Destination Host Unreachable / 100% packet loss)  ✗

# 2. Пинг с ограничением TTL (диагностика петлей)
ping -t 5 8.8.8.8
# → Linux (-t), Windows (-i 5)

# 3. Статистика ICMP из ядра
cat /proc/net/snmp | grep Icmp
# → Icmp:  InMsgs  InErrors  InDestUnreachs  InTimeExcds  InParmProbs  ...
# → Icmp:  12345  0  3  1  0  ...

# 4. Расширенная статистика (современная альтернатива netstat -s)
nstat -az | grep -E 'Icmp|Icmp6'
# → Icmp: InMsgs  12345
# → Icmp6: InMsgs  678

# 5. Захват ICMP-трафика в реальном времени
sudo tcpdump -i eth0 icmp -nn
# → 12:34:56.789012 IP 8.8.8.8 > 10.0.0.1: ICMP echo reply, id 1234, seq 1, length 64
# → 12:34:57.123456 IP 10.0.0.1 > 8.8.8.8: ICMP echo request, id 1234, seq 2, length 64

# 6. Фильтрация по типу ICMP в tcpdump
sudo tcpdump -i eth0 'icmp[0] == 3' -nn    # Type 3 — Destination Unreachable
sudo tcpdump -i eth0 'icmp[0] == 11' -nn   # Type 11 — Time Exceeded
sudo tcpdump -i eth0 'icmp6 and icmp6[0] == 2' -nn  # ICMPv6 Type 2 — Packet Too Big
```

**Диагностика пошагово (алгоритм действий при проблемах):**

1. `ip addr show` — проверить наличие IP-адреса на интерфейсе.
2. `ip route get 8.8.8.8` — проверить, есть ли маршрут и куда он ведёт.
3. `ping -c 3 8.8.8.8` — проверить L3-связность.
4. Если ping не проходит → `ip neigh show` (ARP-кэш), `arp -a` (соседи L2).
5. Если ICMP заблокирован → использовать альтернативы: `nc -zv 8.8.8.8 53` (TCP-ping), `hping3` ([см. альтернативы ping](../../Troubleshooting/ping_alternatives.md)).

**Примечание (root-less ping):** В современных Linux-дистрибутивах `ping` не требует прав root. Работает через capability `cap_net_raw+p` или параметр ядра `net.ipv4.ping_group_range`, позволяющий открывать SOCK_DGRAM-сокеты для ICMP:

```bash
cat /proc/sys/net/ipv4/ping_group_range
# → 0 2147483647  ← любой пользователь может пинговать (по умолчанию в некоторых дистрибутивах)
```

### Трассировка маршрута и анализ потерь

**traceroute** использует ICMP Type 11 (Time Exceeded) или UDP-запросы для картографирования пути:

```bash
# ICMP-режим (Linux, аналог tracert в Windows)
traceroute -I -n 8.8.8.8
# → 1: 10.0.0.1  0.5ms
# → 2: 192.168.1.1  5.2ms
# → 3: 8.8.8.8  10.5ms  ← конечный узел (получен Echo Reply)

# TCP-режим (лучший обход firewall)
traceroute -T -p 443 -n 8.8.8.8

# mtr — непрерывная трассировка с накоплением статистики
mtr -n -c 10 8.8.8.8
# → показывает процент потерь на каждом хопе
```

**Интерпретация потерь в mtr:** если потери есть на промежуточных узлах, но **0% потерь на конечном узле**, это, скорее всего, **ICMP Rate Limiting** на маршрутизаторе, а не реальная проблема в сети.

### Безопасность и разведка

*   **OS Fingerprinting:** Разные ОС по-разному формируют ICMP-ответы (например, значения TTL или размеры данных), что позволяет злоумышленникам определить тип ОС. Таблица типичных начальных TTL:

| Начальное TTL | Типичная ОС |
| :--- | :--- |
| **64** | Linux, macOS, современные BSD, Android |
| **128** | Windows (от XP до 11/Server) |
| **254–255** | Сетевое оборудование (Cisco IOS, JunOS, Mikrotik) |

*   **Smurf Attack:** Использование широковещательного ICMP-запроса для генерации лавины ответов на жертву. Современные ОС игнорируют широковещательные пинги, но защита дополниительно настраивается через `icmp_echo_ignore_broadcasts`.
*   **ICMP Tunneling:** Скрытая передача данных внутри ICMP-пакетов для обхода файрволов. Защита — ограничение размера пакета (`iptables -m length --length 100:128`) и DPI (глубокая проверка поля данных).
*   **Cloud-окружения (AWS, Azure, GCP):** По умолчанию ICMP часто частично или полностью блокируется. Если `ping` между EC2-инстансами не работает, проверьте Security Group (правило `All ICMP - IPv4 / All ICMP - IPv6`) и NACL. Без ICMP недоступен `traceroute`, а PMTUD работает некорректно — используйте TCP-пинг или `nc` для проверки доступности.

### Механизм харденинга (sysctl)

В современных системах рекомендуется жёстко ограничивать прием ICMP-сообщений. Полный набор sysctl-настроек для базовой защиты:

```bash
# === /etc/sysctl.d/99-network-hardening.conf ===

# Защита от IP Spoofing (Strict Reverse Path Filtering)
net.ipv4.conf.all.rp_filter=1
net.ipv4.conf.default.rp_filter=1

# Отключение ICMP Redirect (защита от MITM)
net.ipv4.conf.all.accept_redirects=0
net.ipv4.conf.default.accept_redirects=0
net.ipv6.conf.all.accept_redirects=0
net.ipv6.conf.default.accept_redirects=0

# Запрет на отправку Redirect (для хостов, а не роутеров)
net.ipv4.conf.all.send_redirects=0
net.ipv4.conf.default.send_redirects=0

# Защита от ICMP Flood и Smurf Attack
net.ipv4.icmp_echo_ignore_broadcasts=1
net.ipv4.icmp_ratelimit=100
net.ipv4.icmp_ratelimit_mask=880

# Отключение Source Routing (источниковый маршрут)
net.ipv4.conf.all.accept_source_route=0
net.ipv4.conf.default.accept_source_route=0
net.ipv6.conf.all.accept_source_route=0

# Защита от немаршрутизируемых адресов
net.ipv4.conf.all.route_localnet=0
```

```bash
# Применить настройки
sudo sysctl --system
```

## Дополнительная информация

*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — фильтрация, защита от атак, рекомендуемая политика firewall.
*   **[Утилита ping](../../../Linux/Diagnostics/Networking/ping.md)** — подробное руководство по использованию с флагами и интерпретацией вывода.
*   **Стандарты:** [RFC 792](https://rfc-editor.org/rfc/rfc792.html) (ICMPv4), [RFC 4443](https://rfc-editor.org/rfc/rfc4443.html) (ICMPv6), [RFC 4884](https://rfc-editor.org/rfc/rfc4884.html) (Extensions), [RFC 1191](https://rfc-editor.org/rfc/rfc1191.html) (PMTUD IPv4), [RFC 8200](https://rfc-editor.org/rfc/rfc8200.html) (IPv6), [RFC 4861](https://rfc-editor.org/rfc/rfc4861.html) (NDP), [RFC 6633](https://rfc-editor.org/rfc/rfc6633.html) (отказ Source Quench).
