# Безопасность DHCP — атаки и защита

## Определения

Протокол **DHCP (Dynamic Host Configuration Protocol — протокол динамической настройки узла)** по умолчанию не имеет встроенных механизмов аутентификации или шифрования. Это делает его уязвимым для атак на канальном уровне (L2), так как клиент доверяет любому серверу, ответившему на его широковещательный запрос.

**Дополнительные определения:**

- **DHCP Snooping** — механизм коммутатора, фильтрующий нелегитимные DHCP-сообщения и строящий базу привязок `[MAC + IP + Lease + VLAN + Port]`. Является фундаментом для IPSG, DAI и 802.1X.
- **First-Hop Security (FHS)** — набор функций коммутаторов доступа (L2), защищающих первые «прыжки» сети от атак: DHCP Snooping, IP Source Guard, Dynamic ARP Inspection, Port Security.
- **Rogue DHCP** — несанкционированный DHCP-сервер, установленный злоумышленником для перехвата трафика (MITM), фишинга (подмена DNS) или блокировки доступа.

**Основные угрозы:**
- **DHCP Starvation (Истощение пула):** DoS-атака, направленная на исчерпание всех доступных IP-адресов сервера.
- **Rogue DHCP Server (Поддельный сервер):** Установка несанкционированного сервера для перехвата трафика (Man-in-the-Middle) или блокировки доступа.
- **IP/MAC Spoofing:** Использование чужих сетевых идентификаторов для обхода систем контроля доступа.
- **Rogue DHCP Relay:** Несанкционированный ретранслятор, перехватывающий запросы клиентов для подмены `giaddr` или вставки ложной Option 82. Подробности — [DHCP Relay](./dhcp_relay.md).
- **DHCP Option Overload:** Атака, при которой злоумышленник использует переполнение опций для сбоя парсинга DHCP-пакета на сервере или клиенте.

## Модель угроз: IPv4 и IPv6

### Атаки в сетях IPv4

1. **Starvation:** Атакующий генерирует тысячи запросов `DHCPDISCOVER` с поддельными MAC-адресами (через `macchanger` или `yersinia`). Сервер резервирует под них весь пул, и легитимные клиенты не могут получить адрес. Атака масштабируется на несколько VLAN, если аплинк-порты не защищены.
2. **Rogue Server:** Поддельный сервер отвечает на запросы быстрее легитимного, назначая себя шлюзом по умолчанию (Default Gateway) или подменяя адреса DNS для фишинга. В corporate-сетях часто используется `dnsmasq` или `kea-dhcp4` на ноутбуке злоумышленника.
3. **DHCP Starvation + Rogue:** Комбинированная атака. Сначала исчерпывается пул, затем Rogue-сервер выдаёт адреса с вредоносными DNS. Направлена на массовый компрометс.
4. **Option 82 Spoofing:** Если коммутатор добавляет Option 82 (Circuit ID, Remote ID), злоумышленник может подменить метаданные в Relay-пакете, чтобы сервер выдал адрес из доверенного пула.
5. **DHCP Option Overload:** Атакующий отправляет пакеты с максимально заполненными опциями (до 312 байт в RFC 2131), что может вызвать переполнение буфера на некоторых реализациях DHCP-серверов.
6. **DHCP Release/Decline Storm:** Атакующий массово отправляет `DHCPRELEASE` или `DHCPDECLINE`, заставляя сервер освобождать адреса и перегружать базу данных аренды.

### Атаки в сетях IPv6

В IPv6 задача усложняется из-за наличия двух механизмов назначения адресов (SLAAC и DHCPv6) и протокола NDP.

1. **RA Spoofing:** Атакующий рассылает поддельные **Router Advertisements (RA)**, объявляя себя маршрутизатором. Это позволяет перехватить трафик даже без участия DHCPv6. Связанные угрозы — [IPv6 Overview](../../../Networking/Protocols/ipv6_overview.md).
2. **NDP Spoofing:** Подмена ответов Neighbor Advertisement для перехвата трафика внутри подсети (аналог ARP-спуфинга в IPv4).
3. **DHCPv6 Starvation:** Хотя пул адресов IPv6 огромен, атака направлена на ресурсы сервера (CPU, RAM), забивая их фиктивными записями о DUID.
4. **SLAAC Attack:** Злоумышленник отправляет поддельные RA с флагом `M=0 O=0`, заставляя клиенты использовать SLAAC-адреса вместо DHCPv6, что лишает администратора контроля над адресами.
5. **DHCPv6 Rogue Server:** Аналог Rogue DHCP в IPv4. Сервер выдаёт фиктивные адреса и DNS через Reply.

## Механизмы защиты (First-Hop Security)

Для защиты сети используются функции коммутаторов доступа (L2), известные как **First-Hop Security (FHS)**. Комплексная защита описана в [Жёсткая защита L2](../VLAN/vlan_security_hardening.md).

### DHCP Snooping — фундамент безопасности

Коммутатор анализирует DHCP-трафик и разделяет порты на:
- **Trusted (Доверенные):** Порты, ведущие к легитимному серверу (обычно аплинки). Разрешены любые сообщения.
- **Untrusted (Недоверенные):** Клиентские порты. Сообщения от серверов (`DHCPOFFER`, `DHCPACK`, `ADVERTISE`) на них **блокируются**.

**Snooping Binding Database:** Коммутатор строит таблицу соответствия `[MAC + IP + Lease Time + VLAN + Port]`. Эта база является единственным источником истины для IPSG и DAI.

**Управление базой Snooping:**
- **Статические привязки:** Для серверов со статическими IP добавляйте `ip source binding <MAC> vlan <VLAN> ip <IP> interface <INT>`, чтобы IPSG не блокировал их трафик.
- **Sticky MAC:** Если включён Port Security с `sticky`, коммутатор автоматически добавляет MAC в Snooping-таблицу.
- **Экспорт/импорт:** В Cisco IOS可通过 `show ip dhcp snooping binding` экспортировать таблицу. В emergencies (после перезагрузки) можно восстановить из резервной копии.

### IP Source Guard (IPSG)

Использует базу данных Snooping для предотвращения **IP Spoofing**.
- На порт устанавливается динамический ACL.
- Пропускаются только те пакеты, чей источник IP и MAC совпадает с записью в базе Snooping.
- Пакеты со статическими IP, не прописанными в базе, отбрасываются (требуется ручное добавление статических привязок).

**Режимы работы IPSG:**
- **IP + MAC Filtering:** Самый строгий. Пропускает только пакеты с правильной комбинацией IP и MAC из Snooping-таблицы.
- **IP-only Filtering:** Более мягкий. Проверяет только IP-адрес источника (MAC не проверяется).

### Dynamic ARP Inspection (DAI)

Защита от **ARP-спуфинга**. Коммутатор проверяет ARP-ответы на соответствие базе Snooping. Если связка IP-MAC в ARP-пакете не совпадает с базой, пакет отбрасывается.

**Привязки DAI:**
- **Static ARP:** `arp access-list` + `ip arp inspection filter` для критичных серверов.
- **Trusted ARP:** Порты, ведущие к маршрутизаторам, помечаются как `trusted` для DAI (не проверяются).

### Option 82 как инструмент безопасности

Ретранслятор или коммутатор вставляет в запрос `Circuit ID` (номер порта) и `Remote ID` (имя коммутатора).
- Сервер может выдавать IP только если запрос пришёл с конкретного порта.
- Защита от перемещения устройств между портами без перенастройки сервера.
- **Опасность:** Злоумышленник может подменить Option 82, если коммутатор не блокирует пакеты с существующей Option 82 на untrusted-портах.

**Настройка сервера для работы с Option 82:**
- ISC DHCP: `option-82` в конфиге сервера; при наличии опции сервер проверяет `giaddr` и Circuit ID.
- Kea DHCP: Параметр `check-option-82` в hooks `libdhcp_mysql` или `libdhcp_postgresql`.
- При `authoritative;` сервер отправит `DHCPNAK` при несоответствии Circuit ID.

### IPv6 Specific: RA Guard и DHCPv6 Guard

- **RA Guard (RFC 6105):** Блокирует сообщения Router Advertisement на портах, к которым не подключены легитимные маршрутизаторы. Важно: RA Guard проверяет ICMPv6 Type 134, но **не** защищает от NDP Spoofing (используйте SEND).
- **DHCPv6 Guard:** Аналог DHCP Snooping для IPv6. Блокирует ответы серверов на клиентских портах.
- **IPv6 ND Inspection:** Проверяет legitimacy Router Advertisement и Neighbor Advertisement.

### SEND (Secure Neighbor Discovery, RFC 3971)

Протокол аутентификации NDP-сообщений с использованием криптографических сертификатов (CGA + RSA). Решает проблему NDP Spoofing, но требует поддержки на обоих концах и редко используется в production.

## Сравнение механизмов защиты L2

| Механизм | Что защищает | Источник данных | Уровень | Направлен на |
| :--- | :--- | :--- | :--- | :--- |
| **Port Security** | MAC-адрес порта | Статическая настройка / Sticky | L2 | MAC Flooding, Rogue Devices |
| **DHCP Snooping** | Роль сервера / База привязок | DHCP-трафик (динамика) | L2 | Rogue DHCP, Starvation |
| **IPSG** | IP-адрес источника | База DHCP Snooping | L2/L3 | IP Spoofing |
| **DAI** | ARP-таблицу | База DHCP Snooping | L2 | ARP Spoofing / MITM |
| **RA Guard** | Router Advertisement | ICMPv6 Type 134 | L3 | RA Spoofing (IPv6) |
| **DHCPv6 Guard** | DHCPv6-ответы | DHCPv6-трафик | L3 | Rogue DHCPv6 Server |
| **SEND** | NDP-сообщения | Криптографические сертификаты | L3 | NDP Spoofing (IPv6) |

## Продвинутые концепции

### DHCP Authentication (RFC 3118)

Стандарт описывает механизм аутентификации сообщений DHCP с использованием HMAC.
- **Проблема:** Требует поддержки на стороне клиента (Windows/Linux/macOS) и управления ключами.
- **Реальность:** В корпоративных сетях практически не используется, так как механизмы FHS (Snooping) на коммутаторах проще в эксплуатации и эффективнее.
- **Исключение:** DHCPv6 Authentication (RFC 3315 §21) — в некоторых автономных системах (авиация, военные) используется для защиты от подмены серверов.

### SAVI (Source Address Validation Improvement, RFC 7039)

**SAVI** — это фреймворк, объединяющий проверку адресов для всех методов (SLAAC, DHCPv6, статика). SAVI обеспечивает строгую привязку IP-адреса к порту коммутатора в dual-stack сетях.
- **FCFS SAVI:** First-Come-First-Served — первый пакет определяет привязку.
- **DSA SAVI:** Детерминированный — только DHCPv6-сообщения создают привязки.

### 802.1X и NAC — Zero Trust для DHCP

Вramework **Network Access Control (NAC)** интегрируется с DHCP через 802.1X:
1. Клиент подключается к порту → коммутатор блокирует весь трафик (except 802.1X EAP).
2. Аутентификация через RADIUS → получение VLAN и параметров доступа.
3. После успешной аутентификации → порт открывается, DHCP-сессия начинается.
4. **Dynamic VLAN Assignment:** RADIUS может назначить VLAN на основе профиля пользователя, что автоматически направляет DHCP-запрос в нужный сегмент.

**Связка 802.1X + DHCP Snooping:**
- Коммутатор не включает порт до аутентификации 802.1X → DHCP Snooping не нужен для начальной фильтрации.
- После аутентификации → DHCP Snooping продолжает защищать от Rogue DHCP на уровне порта.
- RADIUS может передать VLAN, который коммутатор автоматически добавит в Trusted-список для DHCP Snooping.

### Связь DHCP Snooping с Failover

В ISC DHCP и Kea DHCP при настройке **Failover** (active-standby или load-balancing):
- Оба сервера должны иметь доступ к общей базе аренд (MySQL/PostgreSQL для Kea).
- DHCP Snooping на коммутаторах должен доверять **обоим** серверам ( оба аплинка — trusted).
- При переключении failover base DHCP Snooping binding не очищается автоматически — клиенты сохраняют адреса до истечения Lease Time.

## Практическая настройка и диагностика

### Cisco IOS

```cisco
! === Глобальная конфигурация DHCP Snooping ===
ip dhcp snooping
ip dhcp snooping vlan 10,20,30

! Rate Limiting на клиентских портах (защита от Starvation)
interface range GigabitEthernet1/0/1 - 48
 ip dhcp snooping limit rate 15
 ip arp inspection vlan 10
 ip verify source

! Trust Port (аплинк к DHCP-серверу)
interface GigabitEthernet0/1
 ip dhcp snooping trust
 no ip arp inspection vlan 10

! Статическая привязка для сервера (чтобы IPSG не блокировал)
ip source binding AA:BB:CC:DD:EE:FF vlan 10 ip 192.168.10.100 interface Gi0/2

! === Диагностика ===
show ip dhcp snooping                    # Статус и VLAN
show ip dhcp snooping binding            # Таблица привязок [MAC+IP+VLAN+Port]
show ip dhcp snooping statistics         # Статистика (пакеты, нарушения)
show ip arp inspection statistics        # Статистика DAI
show ip arp inspection vlan 10           # Статус DAI для VLAN
```

### Juniper JunOS

```junos
# === DHCP Snooping (в Junos — dhcp-security) ===
set firewall family inet dhcp-security
set system services dhcp-local-server group clients interface ge-0/0/1.0

# Включение DHCP Snooping для VLAN
set access firewall family inet filter dhcp-snooping term allow from protocol udp
set access firewall family inet filter dhcp-snooping term allow from source-port 68
set access firewall family inet filter dhcp-snooping term allow from destination-port 67
set access firewall family inet filter dhcp-snooping term allow then accept

# Доверенный сервер (аплинк)
set forwarding-options dhcp-relay group clients server 10.0.0.1
set forwarding-options dhcp-relay interface ge-0/0/0.0

# Rate Limiting
set forwarding-options dhcp-relay overrides rate-limit 15

# === Динамическая ARP-инспекция ===
set firewall family inet dhcp-security-ipv6
set access firewall family inet filter arp-inspection term allow from ether-type 0x0806
set access firewall family inet filter arp-inspection term allow then accept

# === Диагностика ===
show dhcp snooping binding              # Таблица привязок
show dhcp statistics                     # Статистика DHCP
show arp inspection statistics           # Статистика DAI
```

### Arista EOS

```eos
! === DHCP Snooping ===
ip dhcp snooping
no ip dhcp snooping information option  ! Отключить Option 82 (если не нужен)
ip dhcp snooping vlan 10,20

! Rate Limiting
interface Ethernet1
  ip dhcp snooping limit rate 15

! Trust Port
interface Ethernet48
  ip dhcp snooping trust

! Статическая привязка
ip source binding AA:BB:CC:DD:EE:FF vlan 10 192.168.10.100

! === Диагностика ===
show ip dhcp snooping binding
show ip dhcp snooping statistics
```

### MikroTik RouterOS

```routeros
# === DHCP Snooping ===
/ip dhcp-server snooping set interface=bridge1 allow-dhcp-snooping=yes

# Доверенные интерфейсы (аплинки)
/ip dhcp-server snooping set interface=ether1 trusted=yes

# Rate Limiting
/ip firewall filter add chain=input protocol=udp dst-port=67 action=limit \
  limit=15/second limit-burst=20 comment="DHCP Snooping Rate Limit"

# === Динамическая ARP-инспекция ===
/ip arp inspection set interface=bridge1 enabled=yes
/ip arp inspection set interface=ether1 trusted=yes

# === Диагностика ===
/ip dhcp-server snooping print
/ip arp inspection print stats
```

### Linux (nftables)

```bash
# Базовая защита от Rogue DHCP на Linux-шлюзе
# Разрешаем DHCP только от легитимного сервера
nft add table ip dhcp_filter
nft add chain ip dhcp_filter input { type filter hook input priority 0 \; policy accept \; }

# Блокируем DHCP-ответы (server → client) на всех интерфейсах кроме trusted
nft add rule ip dhcp_filter input udp sport 67 udp dport 68 iifname != "eth0" drop

# Блокируем DHCP-ответы от неизвестных серверов
nft add rule ip dhcp_filter input udp sport 67 udp dport 868 iip saddr != 10.0.0.1 drop

# Rate Limiting для DHCP-запросов (защита от Starvation)
nft add rule ip dhcp_filter input udp sport 68 udp dport 67 limit rate 15/second accept
nft add rule ip dhcp_filter input udp sport 68 udp dport 67 drop
```

### Обнаружение Rogue DHCP в Linux

```bash
# Поиск DHCP-серверов через nmap (широковещательный опрос)
sudo nmap --script broadcast-dhcp-discover
# → Для каждого найденного сервера покажет IP, domain, lease time

# Поиск DHCP-серверов через masscan (быстрее, чем nmap)
sudo masscan 255.255.255.255 --rate=1000 -pU:67

# Мониторинг "чужих" ответов через tcpdump
# Ищем ответы (port 68), приходящие не от нашего сервера
sudo tcpdump -i eth0 'udp port 68 and not src host <IP_SERVER>' -vv
# → Если пакеты появляются — Rogue DHCP активен

# Wireshark-фильтры для обнаружения атак
# dhcp.option.dhcp_server_id != 10.0.0.1      — все ответы не от нашего сервера
# bootp.option.dhcp == 1                       — только DISCOVER (поиск аномалий)
# bootp.option.dhcp == 5                       — только ACK (для поиска Rogue)
# dhcp.ip.gateway != 0.0.0.0                   — пакеты через Relay
# dhcp.option.option82                         — Option 82 ( Relay Agent Information)
```

### Системы обнаружения (SIEM и мониторинг)

**Syslog для DHCP Snooping (Cisco):**
```cisco
! Включение syslog для Snooping Violations
ip dhcp snooping limit rate 15
logging host 10.0.0.50 transport tcp port 514
logging trap informational
service timestamps log datetime msec localtime show-timezone
```

**SNMP Traps:**
```cisco
snmp-server enable traps dhcp snooping
snmp-server host 10.0.0.50 version 2c community <Community>
```

**Корреляция в SIEM (псевдокод):**
```
# Правило: Обнаружение Rogue DHCP
WHERE event_type = "DHCP_SNOOPING_VIOLATION"
  AND source_mac NOT IN (known_server_macs)
  AND count_events > 5 IN 60s
THEN ALERT("Possible Rogue DHCP detected", severity=critical)
```

## Управление DHCP Snooping Database

### Экспорт и импорт
```bash
# Cisco IOS: просмотр таблицы
show ip dhcp snooping binding
# MAC Address       IP Address      Lease    VLAN  Interface
# AA:BB:CC:DD:EE:FF 192.168.10.100  3600     10    Gi0/2

# Сохранение в файл (после перезагрузки восстанавливается)
copy running-config startup-config
```

### Статические привязки для серверов
```cisco
! Для серверов со статическими IP — ручное добавление в Snooping
ip source binding AA:BB:CC:DD:EE:FF vlan 10 ip 192.168.10.100 interface Gi0/2

! Проверка
show ip dhcp snooping binding | include AA:BB:CC
```

### Rate Limiting — рекомендуемые значения

| Сценарий | Лимит | Обоснование |
| :--- | :--- | :--- |
| **Access Port (User)** | 15-20 pps | Нормальный клиент генерирует 4-6 DHCP-пакетов за сессию |
| **Trunk (Inter-switch)** | 100-200 pps | Учитывает пакеты от нескольких VLAN |
| **Server Port** | Unlimited | DHCP-сервер генерирует ответы для многих клиентов |
| **Guest WiFi** | 5-10 pps | Ограничиваем атаки от гостевых устройств |

## Рекомендации SRE и DevOps

1. **L2 Hardening:** Всегда включайте DHCP Snooping и Port Security на портах доступа. Это «первая линия обороны».
2. **Мониторинг:** Настройте алертинг в SIEM на события `Snooping Violation`. Это явный признак атаки или ошибки в топологии.
3. **Лимиты (Rate Limiting):** Используйте `ip dhcp snooping limit rate` (напр. 15-20 пакетов в секунду) для защиты CPU коммутатора от DOS-атак.
4. **Статические IP:** Для серверов со статическими IP создавайте `ip source binding` вручную, чтобы IPSG не блокировал их трафик.
5. **Фаза развертывания:** Включайте DHCP Snooping **после** создания статических привязок для серверов и Relay, иначе их трафик будет блокирован.
6. **Резервный план:** В случае массового сбоя DHCP-сервера — отключите DHCP Snooping (`no ip dhcp snooping vlan <VLAN>`) временно, чтобы восстановить связность.
7. **Отказ от Option 82:** Если Option 82 не используется — отключите его (`no ip dhcp snooping information option`), чтобы избежать атак на эту опцию.
8. **Dual-Stack:** В IPv6 используйте `ipv6 dhcp snooping` и RA Guard. Без них IPv6-сеть полностью уязвима для RA Spoofing.
9. **Автоматизация:** Настройте централизованное развертывание конфигурации FHS через Ansible/Netmiko, чтобы избежать ручных ошибок.
10. **Тестирование:** Перед включением Snooping в production протестируйте в лаборатории — убедитесь, что все легитимные DHCP-серверы и Relay добавлены в Trusted.

## Типичные ошибки и методы решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Клиенты не получают IP после включения Snooping** | DHCP-сервер или Relay не добавлен в Trusted | `interface <INT> ip dhcp snooping trust` |
| **Sticky MAC не работает** | Port Security не включён или нет `sticky` | Включить `switchport port-security mac-address sticky` |
| **IPSG блокирует статические серверы** | Нет `ip source binding` для сервера | Добавить `ip source binding` для серверного MAC/IP |
| **Option 82 блокирует легитимные запросы** | Коммутатор и Relay добавляют Option 82 одновременно | Отключить Option 82 на коммутаторе или настроить `append` на Relay |
| **DHCPv6 клиенты не получают адрес** | RA Guard блокирует легитимные RA | Добавить trusted-порт маршрутизатора в RA Guard |
| **Starvation после включения Rate Limiting** | Легитимный DHCP-сервер превышает лимит | Увеличить `limit rate` на trusted-порту сервера |

## Дополнительная информация

- [Обзор DHCP](./dhcp_overview.md) — базовые принципы и процессы DORA/SARR.
- [DHCP Relay](./dhcp_relay.md) — работа через маршрутизаторы и Option 82.
- [Диагностика DHCP](./dhcp_analysis_troubleshooting.md) — анализ трафика в Wireshark.
- [Жёсткая защита L2](../VLAN/vlan_security_hardening.md) — SSoT для DHCP Snooping, DAI, IPSG, BPDU Guard, Storm Control (конфиги Cisco, Juniper, Linux).
- [Протокол ARP](../arp.md) — принципы работы и защита от ARP Spoofing.
- **Спецификации:**
  - [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131) — Dynamic Host Configuration Protocol.
  - [RFC 3118](https://datatracker.ietf.org/doc/html/rfc3118) — Authentication for DHCP Messages.
  - [RFC 6105](https://datatracker.ietf.org/doc/html/rfc6105) — IPv6 Router Advertisement Guard.
  - [RFC 7039](https://datatracker.ietf.org/doc/html/rfc7039) — Source Address Validation Improvement (SAVI).
  - [RFC 3971](https://datatracker.ietf.org/doc/html/rfc3971) — Secure Neighbor Discovery (SEND).
  - [RFC 3046](https://datatracker.ietf.org/doc/html/rfc3046) — DHCP Relay Agent Information Option (Option 82).
