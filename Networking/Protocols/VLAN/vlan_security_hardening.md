# Жёсткая защита L2: DHCP Snooping, DAI, IPSG, BPDU Guard, Storm Control

## Определения

**DHCP Snooping** — механизм коммутатора L2, который классифицирует порты на `trusted` (доверенные, к серверу) и `untrusted` (недоверенные, к клиентам). Блокирует поддельные DHCP-ответы от клиентских портов и строит таблицу привязок `[MAC + IP + VLAN + Port]`.

**IP Source Guard (IPSG)** — механизм, использующий базу DHCP Snooping для динамической установки ACL на порт. Пропускаются только пакеты с теми же источниковыми IP и MAC, что и запись в таблице Snooping.

**Dynamic ARP Inspection (DAI)** — проверка ARP-пакетов на соответствие базе DHCP Snooping. Блокирует ARP-спуфинг (Man-in-the-Middle на L2).

**BPDU Guard** — функция STP, немедленно выводящая порт в состояние `err-disabled` при получении BPDU. Применяется на Access-портах для предотвращения подключения посторонних коммутаторов.

**Root Guard** — функция STP, блокирующая порт в состоянии `root-inconsistent`, если через него получен BPDU с лучшим Bridge ID. Предотвращает назначение чужого Root Bridge.

**Storm Control** — ограничение скорости broadcast/multicast/unknown-unicast трафика на порту. Активируется при превышении порога (обычно 1-5% от пропускной способности порта).

**802.1X (Port-Based Network Access Control)** — стандарт IEEE для аутентификации устройств перед предоставлением доступа к сети. Клиент (Supplicant) проходит аутентификацию через Authenticator (коммутатор) у Authentication Server (RADIUS). По результатам аутентификации порт назначается в нужный VLAN.

**MAC Authentication Bypass (MAB)** — альтернатива 802.1X для устройств без поддержки EAP (принтеры, IP-камеры). Коммутатор использует MAC-адрес устройства как логин/пароль для аутентификации через RADIUS.

**MACsec (802.1AE)** — стандарт шифрования на уровне L2. Защищает кадры от прослушивания, подмены и атак типа Man-in-the-Middle на физическом линке. Работает на портах point-to-point.

**RA Guard** — механизм, блокирующий нелегитимные Router Advertisement в VLAN. Предотвращает атаки через подмену шлюза на уровне IPv6 Neighbor Discovery.

**DHCP Guarding** — аналог DHCP Snooping для IPv6. Блокирует нелегитимные RA и DHCPv6-ответы.

> **Назначение:** Этот документ — SSoT для комплексной жёсткой защиты L2 в production. Охватывает DHCP Snooping, DAI, IPSG, BPDU Guard, Root Guard, Storm Control, Port Security, 802.1X/MAB, MACsec, RA Guard, PVLAN и IPv6 L2-безопасность с production-конфигурациями для Cisco, Juniper, Huawei и Linux.

## Базовые концепции

### Цепочка защиты First-Hop Security (FHS)

```
Port Security → DHCP Snooping → IPSG → DAI → ARP Inspection
                      ↗       ↘
             Storm Control   BPDU Guard
                                  ↓
                      802.1X / MAB → RADIUS → VLAN Assignment
                                  ↓
                            MACsec (L2 encryption)
```

База данных DHCP Snooping является единственным источником истины для IPSG и DAI.

### Профили портов

| Профиль | Применение | Защита | Команды |
| :--- | :--- | :--- | :--- |
| **Access (User)** | Подключение конечных устройств | Port Security, BPDU Guard, Storm Control, DHCP Snooping untrusted, 802.1X | `switchport mode access`, `bpduguard enable`, `storm-control`, `dot1x pae authenticator` |
| **Access (Device)** | Принтеры, камеры (без EAP) | MAB, Port Security, Storm Control | `mab`, `switchport port-security` |
| **Trunk (Uplink)** | Связь между коммутаторами/к гипервизору | DHCP Snooping trusted, Root Guard, Native VLAN isolation, MACsec | `switchport mode trunk`, `ip dhcp snooping trust`, `rootguard` |
| **Bridge (Linux)** | Виртуализация, VLAN-aware bridge | FDB limit, bridge priority, VLAN pruning, nftables | `vlan_filtering 1`, `bridge fdb`, `bridge vlan` |

### Типы атак на L2 и их защита

| Атака | Описание | Защита |
| :--- | :--- | :--- |
| **MAC Flooding** | Переполнение CAM-таблицы для перевода коммутатора в режим хаба | Port Security, FDB limit |
| **ARP Spoofing** | Подмена MAC-адреса шлюза для MITM | DAI + DHCP Snooping |
| **DHCP Spoofing** | Поддельный DHCP-сервер выдаёт неверные IP/шлюзы | DHCP Snooping |
| **VLAN Hopping** | Обход изоляции VLAN через двойные теги или DTP | `switchport nonegotiate`, `vlan dot1q tag native`, отключение DTP |
| **DHCP Starvation** | Исчерпание пула DHCP через поддельные запросы | DHCP Snooping rate-limit |
| **Broadcast Storm** | Зацикливание broadcast-трафика | Storm Control, BPDU Guard |
| **CAM Table Overflow** | Переполнение MAC-таблицы | Port Security с лимитом |
| **RA Spoofing** | Поддельный IPv6 Router Advertisement | RA Guard |
| **MAC Spoofing** | Подмена MAC-адреса для обхода ACL | 802.1X, MACsec |

## Практические сценарии

### Сценарий 1: Комплексная защита Access-порта (Cisco IOS)

#### Конфигурация

```cisco
! --- Шаблон Port-Security + DHCP Snooping + Storm Control ---
interface range GigabitEthernet1/0/1 - 48
 description *** User Access Ports ***
 switchport mode access
 switchport access vlan 10
 switchport nonegotiate

! Port Security: максимум 2 устройства на порт
 switchport port-security
 switchport port-security maximum 2
 switchport port-security mac-address sticky
 switchport port-security aging time 30
 switchport port-security aging type inactivity
 switchport port-security violation restrict

! BPDU Guard: блокируем попытки подключить сторонний коммутатор
 spanning-tree bpduguard enable
 spanning-tree bpdufilter enable

! Storm Control: лимитируем broadcast/multicast
 storm-control broadcast level 1.00
 storm-control multicast level 1.00
 storm-control action shutdown
 storm-control action trap

! DHCP Snooping: порт недоверенный
 ip dhcp snooping limit rate 15
! --- Конец шаблона ---
```

#### Глобальная конфигурация DHCP Snooping

```cisco
! Включение для VLAN 10 (Production)
ip dhcp snooping vlan 10,20,30
ip dhcp snooping
! Исключаем сервисные порты из snooping
no ip dhcp snooping vlan 1
! Доверенный uplink к DHCP-серверу
interface GigabitEthernet0/1
 ip dhcp snooping trust
! Доверенный uplink к роутеру (SVI)
interface Vlan10
 ip dhcp snooping trust
```

#### Ожидаемый результат (Validation)

```bash
! Проверка Port Security
show port-security interface Gi1/0/5
! → Security Violation Mode: Restrict
! → Max MAC Addresses: 2
! → Sticky MAC: 00:11:22:33:44:55

! Проверка DHCP Snooping
show ip dhcp snooping binding
! → MacAddress         IP address        Lease(sec)  Type           VLAN  Interface
! → 00:11:22:33:44:55  192.168.10.50     3600      dhcp-snooping   10    Gi1/0/5

show ip dhcp snooping database
! → Total writes: 42
! → Last written: 00:05:32 ago

! Проверка Storm Control статуса
show storm-control interface Gi1/0/5
! → Broadcast | 1.00% | 125000 | OK
```

#### Особые случаи (Edge Cases)

- **Violation Restrict vs Shutdown:** `restrict` логирует и блокирует MAC, но порт остается включённым; `shutdown` выводит порт в err-disabled. Для критичных сред используйте `restrict` с последующей авто-восстановлением.
- **DHCP Snooping и IPv6:** для DHCPv6 используйте `ipv6 dhcp snooping`. Аналогично, `ipv6 nd suppression` для RA Guard.
- **Sticky MAC persistence:** sticky MAC записываются в `running-config`, но не в `startup-config`. Требуется `copy running-config startup-config` после добавления.

### Сценарий 2: Защита Trunk-порта (Cisco IOS + Juniper)

#### Cisco — Trunk с Root Guard и Native VLAN

```cisco
interface GigabitEthernet1/0/24
 description *** Uplink to Core ***
 switchport mode trunk
 switchport nonegotiate
 switchport trunk native vlan 999
 switchport trunk allowed vlan 10,20,30,999

! Root Guard: не допускаем посторонний Root Bridge
 spanning-tree guard root

! DHCP Snooping trusted (applink к серверу)
 ip dhcp snooping trust

! Принудительное тегирование Native VLAN (профилактика VLAN Hopping)
vlan dot1q tag native
```

#### Juniper — аналогичная конфигурация

```bash
set interfaces ge-0/0/24 description "Uplink to Core"
set interfaces ge-0/0/24 unit 0 family ethernet-switching port-mode trunk
set interfaces ge-0/0/24 unit 0 family ethernet-switching native-vlan-id 999
set interfaces ge-0/0/24 unit 0 family ethernet-switching vlan members [10, 20, 30, 999]

! Root Guard (переводим BPDU в root-protect)
set protocols rstp interface ge-0/0/24 root-protect

! DHCP Snooping (в Junos — dhcp-security)
set protocols dhcp-security global
set protocols dhcp-security binding-table
set protocols dhcp-security arp-inspection vlan [10 20 30]
```

#### Huawei VRP

```huawei
interface GigabitEthernet0/0/24
 description *** Uplink to Core ***
 port link-type trunk
 port trunk allow-pass vlan 10 20 30 999
 port trunk pvid vlan 999

! Root Guard
 stp root-protection

! DHCP Snooping
dhcp snooping enable
interface GigabitEthernet0/0/24
 dhcp snooping trusted
```

#### Ожидаемый результат (Validation)

```cisco
show spanning-tree interface Gi1/0/24
! → Port 24 (GigabitEthernet1/0/24) Designated Forwarding
! → Guard: Root-Protect Enabled

show interfaces trunk
! → Port        Mode         Encapsulation  Status        Allowed VLANs
! → Gi1/0/24    trunk        802.1q         operational   10,20,30,999(P)
```

### Сценарий 3: Жёсткая защита Linux Bridge (VLAN-aware)

#### Конфигурация

```bash
# 1. Создание моста с vlan_filtering и STP
sudo ip link add name br0 type bridge vlan_filtering 1 stp_state 1
sudo ip link set eth0 master br0

# 2. Удаление VLAN 1 по умолчанию (Black Hole)
sudo bridge vlan del dev eth0 vid 1
sudo bridge vlan del dev eth0 vid 1 self

# 3. Настройка trunk на eth0 (только необходимые VLAN)
sudo bridge vlan add dev eth0 vid 10
sudo bridge vlan add dev eth0 vid 20
sudo bridge vlan add dev eth0 vid 999 pvid untagged

# 4. Ограничение количества MAC-адресов в FDB (аналог Port Security)
sudo ip link set br0 type bridge fdb_max_global 1000
sudo ip link set br0 type bridge fdb_max_per_port 10

# 5. Ограничение broadcast (Storm Control аналог через tc)
sudo tc qdisc add dev br0 ingress
sudo tc filter add dev br0 parent fff: protocol all \
  flower type flower dst_mac ff:ff:ff:ff:ff:ff \
  police rate 10mbit burst 100k drop

# 6. Защита от ARP-спуфинга через nftables
sudo nft add table inet arp_guard
sudo nft add chain inet arp_guard input { type filter hook input priority -150 \; }
# Блокировка ARP-ответов с неверным IP (_static binding)
sudo nft add rule inet arp_guard input arp operation reply \
  arp ip saddr != 192.168.10.1 drop
# Блокировка gratuitous ARP от клиентских портов
sudo nft add rule inet arp_guard input arp operation announcement \
  iifname "eth0*" drop

# 7. Защита от MAC Spoofing (nftables)
sudo nft add table inet mac_guard
sudo nft add chain inet mac_guard input { type filter hook input priority -150 \; }
# Разрешить только известные MAC на порту
sudo nft add rule inet mac_guard input iifname "eth0" \
  ether saddr != { 00:11:22:33:44:55, aa:bb:cc:dd:ee:ff } drop

# 8. RA Guard для IPv6 (nftables)
sudo nft add table inet ipv6_guard
sudo nft add chain inet ipv6_guard input { type filter hook input priority -150 \; }
# Блокировка RA (ICMPv6 type 134) от клиентских портов
sudo nft add rule inet ipv6_guard input \
  icmpv6 type router-advertisement iifname "eth0*" drop
```

#### Ожидаемый результат (Validation)

```bash
# Проверка FDB limit
ip link show br0 | grep fdb
# → bridge fdb_max_global 1000 fdb_max_per_port 10

# Проверка storm control (tc filter)
tc filter show dev br0 ingress
# → filter ingress 8000: 8000: flower \
# →   police rate 10Mbit burst 100Kb

# Проверка VLAN (без VLAN 1)
bridge vlan show
# → port    vlan ids
# → eth0    10 20 999 pvid untagged

# Проверка nftables правил
sudo nft list ruleset | grep -A5 arp_guard
# → table inet arp_guard {
# →     chain input {
# →         type filter hook input priority -150; policy accept;
# →         arp operation reply arp ip saddr != 192.168.10.1 drop
# →     }
# → }
```

#### Особые случаи (Edge Cases)

- **tc + bridge:** `tc filter ... flower` работает на уровне bridge, но не на уровне отдельных портов. Для per-port storm control используйте hardware-фильтры или отдельный tc на каждом порту.
- **FDB max limits:** при достижении лимита `fdb_max_global` новые MAC-адреса начинают затапливаться (flood) вместо добавления в таблицу.
- **Linux + Port Security:** аппаратное Port Security недоступно в Linux. Используйте `tc` для rate-limiting или nftables для MAC-фильтрации, или переходите на OVS с flow-правилами.
- **nftables и bridge:** nftables работает на уровне L3, не перехватывает L2-фреймы (broadcast, multicast). Для защиты от L2-атак используйте bridge-specific инструменты (`bridge`, `tc`).

### Сценарий 4: 802.1X + VLAN Assignment (Cisco IOS)

#### Конфигурация

```cisco
! Глобальная настройка 802.1X
aaa new-model
radius-server host 10.200.0.5 key SECRET_RADIUS
aaa authentication dot1x default group radius
aaa authorization network default group radius

! Включение 802.1X глобально
dot1x system-auth-control

! Настройка Access-порта с 802.1X
interface GigabitEthernet1/0/10
 description *** 802.1X User Port ***
 switchport mode access
 switchport access vlan 100

! Включение 802.1X на порту
 dot1x pae authenticator
 dot1x timeout tx-period 10
 dot1x max-req 3

! Гостевой VLAN (для неаутентифицированных)
 authentication event fail action next-method
 authentication event server dead action authorize vlan 999
 authentication event server alive action reinitialize

! Включение MAB для устройств без EAP
 mab
 authentication order dot1x mab
 authentication fallback mab
```

#### RADIUS-сервер (FreeRADIUS — пример записи)

```
# clients.conf
client switch-core {
    ipaddr = 10.0.0.1
    secret = SECRET_RADIUS
}

# mods-config/files/authorize
user1    Cleartext-Password := "password1"
    Tunnel-Type = VLAN,
    Tunnel-Medium-Type = IEEE-802,
    Tunnel-Pure-Id = 10

printer1  Auth-Type := Accept,
    Tunnel-Type = VLAN,
    Tunnel-Medium-Type = IEEE-802,
    Tunnel-Pure-Id = 200
```

#### Huawei VRP

```huawei
# AAA и RADIUS
radius-server template CORP_RADIUS
 radius-server shared-key cipher SECRET_RADIUS
 radius-server authentication 10.200.0.5 1812
 radius-server accounting 10.200.0.5 1813

aaa
 authentication-scheme dot1x_auth
  authentication-mode radius
 accounting-scheme dot1x_acct
  accounting-mode radius
 domain default
  authentication-scheme dot1x_auth
  accounting-scheme dot1x_acct
  radius-server template CORP_RADIUS

# Включение 802.1X
dot1x enable
dot1x timer tx-period 10

interface GigabitEthernet0/0/10
 dot1x enable
 dot1x port-method mac
 dot1x max-user 1
 authentication event fail action authorize vlan 999
```

### Сценарий 5: MACsec (802.1AE) — шифрование L2 (Cisco)

```cisco
! Настройка MACsec на двух концах линка
key chain MACSEC_KEY
 key 1
  key-string 0 MySecretKey12345678901234567890

interface GigabitEthernet1/0/24
 description *** Encrypted Uplink ***
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30

! Включение MACsec
 macsec network-link
 macsec keychain MACSEC_KEY
 macsec primary-cak
 macsec confidentiality-offset 0
```

### Сценарий 6: Private VLAN (PVLAN) — изоляция внутри VLAN (Cisco)

```cisco
! Создание PVLAN
vlan 100
 name SHARED_SUBNET
 private-vlan primary

vlan 101
 name SERVERS
 private-vlan isolated

vlan 102
 name CLIENT_GROUP_A
 private-vlan community

vlan 103
 name CLIENT_GROUP_B
 private-vlan community

vlan 100
 private-vlan association 101,102,103

! Привязка портов
interface GigabitEthernet1/0/1
 description *** Server (Isolated) ***
 switchport mode private-vlan
 switchport private-vlan host-association 100 101
 switchport private-vlan host

interface range GigabitEthernet1/0/2-5
 description *** Client Group A (Community) ***
 switchport mode private-vlan
 switchport private-vlan host-association 100 102
 switchport private-vlan host

interface GigabitEthernet1/0/24
 description *** Uplink to Router (Promiscuous) ***
 switchport mode private-vlan
 switchport private-vlan mapping 100 101,102,103

! Validation
show vlan private-vlan
! → Primary  Secondary  Type          Ports
! → 100      101        isolated      ...
! → 100      102        community     ...
```

## Тюнинг и безопасность

### Рекомендуемые пороги Storm Control

| Тип трафика | Порог | Обоснование |
| :--- | :--- | :--- |
| **Broadcast** | 1–2% от пропускной способности порта | Нормальный broadcast ~0.1–0.5%; превышение 1% — аномалия |
| **Multicast** | 2–5% | Многое зависит от приложений (IPTV, video); вoffice-сетях ≤2% |
| **Unknown Unicast** | 1–2% | Нормальный unknown unicast — единичные кадры на öğrenение MAC |
| **Storm Action** | `shutdown` + `trap` | Порт уходит в err-disabled, администратор получает SNMP-уведомление |

### Err-disabled Recovery

```cisco
! Автоматическое восстановление портов
errdisable recovery cause bpduguard
errdisable recovery cause security-violation
errdisable recovery cause storm-control
errdisable recovery cause dhcp-rate-limit
errdisable recovery cause arp-inspection
errdisable recovery interval 300

! Проверка состояния
show errdisable recovery
! → ErrDisable Reason          Timer Status
! → bpduguard                  Enabled
! → security-violation         Enabled
! → storm-control              Enabled

! Ручное восстановление
interface Gi1/0/5
 shutdown
 ! (пауза 5 сек)
 no shutdown
```

### DHCP Snooping: Trusted vs Untrusted

| Порт | Тип | DHCP Snooping | Обоснование |
| :--- | :--- | :--- | :--- |
| **Uplink к серверу** | Trunk | `trusted` | Сервер отправляет ответы, не фильтруем |
| **Uplink к роутеру** | SVI | `trusted` | Роутер может быть DHCP-ретранслятором |
| **Access к клиенту** | Access | `untrusted` + `rate-limit 15` | Клиент не должен отправлять DHCP-ответы |
| **Access к принтеру** | Access | `untrusted` + MAB | Принтер аутентифицируется по MAC, DHCP normal |

### DHCP Snooping: Persistence таблицы привязок

По умолчанию таблица DHCP Snooping теряется при перезагрузке коммутатора. Для сохранения настройте запись в файл:

```cisco
! Указываем место для сохранения (USB или bootflash)
ip dhcp snooping database bootflash:dhcp_snooping.db

! Или на TFTP-сервере (для кластера коммутаторов)
ip dhcp snooping database tftp://10.200.0.10/dhcp_snooping.db

! Интервал записи (по умолчанию 300 сек)
ip dhcp snooping database write-delay 60
```

**Проверка:**
```cisco
show ip dhcp snooping database
! → Total writes: 42
! → Last written: 00:01:02 ago
! → File: bootflash:dhcp_snooping.db
```

### DAI: Validation и Static ARP

```cisco
! Статические ARP для критичных серверов (не проверяются DAI)
arp access-list CRITICAL_SERVERS
 permit ip host 10.200.0.5 host 00aa.bb11.cc22

ip arp inspection filter CRITICAL_SERVERS vlan 10,20

! Логирование DAI (для аудита)
ip arp inspection log-buffer entries 1024
ip arp inspection log-buffer logs 1024 interval 10
```

## Диагностика и устранение неисправностей

### Типичные ошибки

1. **DHCP Snooping блокирует легитимные ответы:** Порт к DHCP-серверу не помечен как `trusted`. Решение: `ip dhcp snooping trust` на uplink-порту.
2. **DAI блокирует весь ARP-трафик:** DHCP Snooping не настроен, таблица привязок пуста. Решение: включите DHCP Snooping или добавьте статические ARP-записи.
3. **IPSG отклоняет весь трафик:** Таблица DHCP Snooping пуста (клиенты не получили IP через relay). Решение: проверьте `ip helper-address` на SVI.
4. **802.1X: клиент не аутентифицируется:** RADIUS-сервер недоступен или неверный shared secret. Решение: `test aaa new-model` и проверка RADIUS-логов.
5. **PVLAN: isolated-хост не видит promiscuous:** Порт не переведён в режим `private-vlan host`. Решение: `switchport private-vlan host` на порту.
6. **MACsec: линк не поднимается:** Несовпадение ключей между концами или поддержка MACsec не включена на NIC. Решение: проверьте `show macsec`.

### Пошаговая процедура диагностики

```
1. PORT SECURITY
   └─ show port-security interface <iface> (статус, лимиты, нарушения)
   └─ show port-security address (все MAC в таблице)
   └─ show mac address-table address <mac> (где находится MAC)

2. DHCP SNOOPING
   └─ show ip dhcp snooping binding (таблица привязок)
   └─ show ip dhcp snooping binding dynamic (только динамические)
   └─ show ip dhcp snooping trust (какие порты trusted)
   └─ show ip dhcp snooping statistics (counters)

3. DAI
   └─ show ip arp inspection vlan <vid> (statistic: drop/permit)
   └─ show ip arp inspection log-buffer (последние инциденты)
   └─ show arp access-list <name> (статические ARP)

4. IPSG
   └─ show ip source binding (все привязки)
   └─ show ip verify source (статус проверки на порту)

5. STP / BPDU
   └─ show spanning-tree interface <iface> (Guard: Root-Protect/BPDU Guard)
   └─ show spanning-tree inconsistentports ( root-inconsistent порты)

6. 802.1X / MAB
   └─ show dot1x interface <iface> (состояние аутентификации)
   └─ show authentication sessions interface <iface> (детали сессии)
   └─ show aaa servers (доступность RADIUS)

7. STORM CONTROL
   └─ show storm-control interface <iface> (текущий уровень vs порог)
   └─ show interfaces counter broadcast (общая статистика)
```

### Команды диагностики

| Команда | Платформа | Описание | Когда вызывать |
| :--- | :--- | :--- | :--- |
| `show port-security address` | Cisco | Статические + sticky MAC-адреса | При конфликте MAC |
| `show ip dhcp snooping binding` | Cisco | Таблица привязок [MAC+IP+VLAN+Port] | При rogue DHCP |
| `show ip arp inspection` | Cisco | DAI статистика (drop/allow) | При ARP спуфинге |
| `ip dhcp snooping binding dynamic` | Cisco | Только динамические привязки | Аудит постоянный |
| `show storm-control` | Cisco | Текущие пороги и статус | При broadcast storm |
| `show dot1x` | Cisco | Состояние 802.1X на всех портах | Проблемы аутентификации |
| `show authentication sessions` | Cisco | Детали RADIUS-сессии | Диагностика 802.1X |
| `show macsec` | Cisco | Состояние MACsec-шифрования | Проблемы с L2-шифрованием |
| `show vlan private-vlan` | Cisco | PVLAN-ассоциации | Проблемы изоляции |
| `bridge fdb show` | Linux | FDB таблица моста | Инцидент: MAC flapping |
| `tc -s filter ls dev br0 ingress` | Linux | Статистика storm control | Инцидент: broadcast storm |
| `nft list ruleset` | Linux | Все nftables правила | Проверка nftables-защиты |

### Автоматический мониторинг

```cisco
! SNMP-триггеры для key L2-событий
snmp-server enable traps port-security
snmp-server enable traps port-security trap-rate 1
snmp-server enable traps vlan-membership
snmp-server enable traps spanning-tree
snmp-server host 10.200.0.10 version 2c SECRET community

! Syslog для аудита
logging host 10.200.0.10
logging trap informational
logging source-interface Loopback0
```

```bash
# Linux: мониторинг nftables drop-событий через auditd
sudo auditctl -w /proc/net/nf_conntrack -p r -k nft_drop
sudo ausearch -k nft_drop --raw | aureport --summary

# Мониторинг MAC flapping (kern.log)
journalctl -k -f | grep -i "mac.*flap"
```

## Edge Cases

### 1. DHCP Starvation Attack
Злоумышленник отправляет тысячи DHCPDISCOVER с разными MAC, исчерпывая пул адресов. Защита: `ip dhcp snooping limit rate 15` на access-портах.

### 2. Double 802.1Q Tagging (VLAN Hopping)
Если на Trunk-порту разрешены все VLAN, злоумышленник может инкапсулировать кадро в двойной тег. Защита: `switchport trunk allowed vlan` + `vlan dot1q tag native`.

### 3. MAC Flapping в виртуальных средах
При миграции VM (Live Migration) один MAC временно появляется на разных портах. Коммутатор может интерпретировать это как атаку. Защита: увеличьте порог `mac move threshold` или используйте `sticky MAC` на vSphere dvSwitch.

### 4. ARP Proxy и False Positives
Если на маршрутизаторе включен ARP Proxy, DAI может блокировать легитимные ARP-ответы с MAC роутера. Решение: добавьте static ARP в ACL `arp access-list`.

### 5. IPv6 SLAAC и RA Guard
В IPv6-сетях хосты получают IP через SLAAC (Router Advertisement). Поддельный RA может перенаправить весь IPv6-трафик. Защита: RA Guard на access-портах (`ipv6 nd raguard`).

### 6. MAB и 동적 VLAN
При использовании MAB + динамический VLAN assignment (через RADIUS) порт может временно находиться в guest VLAN до завершения аутентификации. Убедитесь, что RADIUS-сервер отвечает быстро (<5 сек).

## Best Practices

1. **Начинайте с DHCP Snooping** — это фундамент для DAI и IPSG. Без него эти механизмы не работают.
2. **Включайте `switchport nonegotiate`** на всех access-портах — отключает DTP и предотвращает VLAN Hopping.
3. **Ограничивайте Trunk:** `switchport trunk allowed vlan` — не пропускайте все VLAN через trunk.
4. **Используйте `vlan dot1q tag native`** — защищает от Native VLAN mismatch и VLAN Hopping.
5. **Настройте err-disabled recovery** с интервалом 300 сек — это сокращает время простоя при ложных срабатываниях.
6. **Документируйте trusted-порты** — ведите реестр портов с `ip dhcp snooping trust` для аудита.
7. **Используйте PVLAN** вместо ACL для изоляции хостов внутри одного VLAN — это проще в управлении.
8. **802.1X для пользователей, MAB для устройств** — комбинация покрывает все типы устройств.
9. **MACsec для point-to-point линков** — шифруйте трафик между коммутаторами/к гипервизору.
10. **RA Guard для IPv6** — если используете SLAAC, обязательно блокируйте поддельные RA.
11. **Настраивайте storm control пороги до инцидента** — определите baseline正常ного трафика и установите порог выше baseline.
12. **Включите SNMP/Syslog** для L2-событий — это позволяет обнаруживать атаки в реальном времени.

## Дополнительная информация

### Таблица команд диагностики

| Команда | Платформа | Описание | Когда вызывать |
| :--- | :--- | :--- | :--- |
| `show port-security address` | Cisco | Статические + sticky MAC-адреса | При конфликте MAC |
| `show ip dhcp snooping binding` | Cisco | Таблица привязок [MAC+IP+VLAN+Port] | При rogue DHCP |
| `show ip arp inspection` | Cisco | DAI статистика (drop/allow) | При ARP спуфинге |
| `ip dhcp snooping binding dynamic` | Cisco | Только динамические привязки | Аудит постоянный |
| `show storm-control` | Cisco | Текущие пороги и статус | При broadcast storm |
| `bridge fdb show` | Linux | FDB таблица моста | Инцидент: MAC flapping |
| `tc -s filter ls dev br0 ingress` | Linux | Статистика storm control | Инцидент: broadcast storm |

### Процедура авто-восстановления (err-disabled recovery)

```cisco
! Автоматическое восстановление через 300 секунд
errdisable recovery cause bpduguard
errdisable recovery cause security-violation
errdisable recovery cause storm-control
errdisable recovery interval 300
```

### Резервные меры при недоступности коммутатора

Если коммутатор недоступен, но есть подозрение на атаку — используйте Linux-хост с tcpdump для перехвата:

```bash
# Поиск двойных тегов (VLAN Hopping атака)
sudo tcpdump -i eth0 -e 'vlan and vlan'

# Поиск Rogue DHCP (ответы от неожиданных серверов)
sudo tcpdump -i eth0 -n 'udp port 67 or udp port 68' | \
  awk '{print $NF}' | sort | uniq -c | sort -rn

# Мониторинг BPDU на access-портах (нарушение BPDU Guard)
sudo tcpdump -i eth0 -e 'ether proto 0x42'

# Мониторинг RA-пакетов (IPv6 RA Spoofing)
sudo tcpdump -i eth0 -e 'icmp6 and ip6[40] = 134'

# Мониторинг ARP-спуфинга
sudo tcpdump -i eth0 -e 'arp' | grep -v "request" | head -20
```

### Связанные документы

- **[Безопасность на канальном уровне: DTP и Port Security](./vlan_dtp_security.md)** — DTP, Port Security, Violation режимы.
- **[DHCP Snooping — атаки и защита](../DHCP/dhcp_security.md)** — глубокая теория DHCP Snooping, IPSG, DAI.
- **[Spanning Tree Protocol (STP)](../stp.md)** — BPDU Guard, Root Guard, Loop Detection.
- **[Trunk и Native VLAN](./vlan_trunk_native.md)** — безопасная конфигурация trunk и Native VLAN mismatch.
- **[L2 Switching и VLAN: Практические сценарии](../../Concepts/vlan_l2_switching/practical_scenarios.md)** — сценарий 9 (incident response).
- **[Проектирование VLAN: production-ready топологии](../../Concepts/vlan_l2_switching/vlan_design_patterns.md)** — Enterprise Campus, PVLAN, Leaf-Spine, production checklist.
- **[Network Segmentation и Microsegmentation](../../Concepts/network_segmentation_and_microsegmentation.md)** — Defense in Depth, VLAN + Security Groups + NetworkPolicy.
- **[Linux VRF](../../../Linux/Networking/vrf.md)** — виртуализация таблиц маршрутизации для изоляции.
- **[Ansible — сетевая автоматизация](../../../Ansible/ansible_network_automation.md)** — автоматизация Security Hardening через Ansible.

### См. также

- **[QoS и приоритизация L2](../qos.md#уровень-l2-data-link)** — Storm Control и rate limiting на уровне L2.
- **[VLAN — обзор](./vlan.md)** — общие принципы сегментации и типы расширений (QinQ, PVLAN).
- **[MAC-адреса](../../Concepts/mac_address.md)** — IPSG, Port Security и CAM-таблица.
