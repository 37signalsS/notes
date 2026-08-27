# DHCP — Обзор протокола

## Определения

**DHCP (Dynamic Host Configuration Protocol — протокол динамической настройки узла)** — сетевой протокол прикладного уровня (L7), предназначенный для автоматической конфигурации сетевых параметров устройств. DHCP избавляет администраторов от ручного назначения IP-адресов, предотвращая конфликты и минимизируя ошибки конфигурации.

**BOOTP (Bootstrap Protocol, RFC 951)** — предшественник DHCP, появившийся в 1985 году. DHCP расширяет BOOTP, добавив механизм аренды (leases) и динамическую выдачу адресов. BOOTP-клиенты могут работать с DHCP-сервером благодаря обратной совместимости (opcode `BOOTREQUEST`/`BOOTREPLY` сохранён в DHCP).

**Основные версии:**
- **DHCPv4 (RFC 2131):** Используется для сетей IPv4. Основан на широковещательных (broadcast) запросах.
- **DHCPv6 (RFC 8415):** Используется для сетей IPv6. Основан на многоадресной рассылке (multicast) и тесно взаимодействует с протоколом ICMPv6.

**Архитектурные компоненты:**
- **DHCP-сервер** — управляет пулом адресов и базой данных аренды (leases). Может быть выделенным устройством, виртуальной машиной или встроенным в маршрутизатор.
- **DHCP-клиент** — устройство, запрашивающее настройки (ПК, сервер, IoT-устройство, принтер).
- **DHCP Relay Agent (Ретранслятор)** — устройство (обычно маршрутизатор), которое пересылает запросы между разными подсетями. Подробности — [DHCP Relay](./dhcp_relay.md).

**Транспортные порты:**
- **IPv4:** Сервер — `67/UDP`, Клиент — `68/UDP`.
- **IPv6:** Сервер — `547/UDP`, Клиент — `546/UDP`.

## Структура DHCPv4-пакета

Пакет DHCP инкапсулируется в UDP и содержит поля, унаследованные от BOOTP:

| Поле | Размер | Описание |
| :--- | :--- | :--- |
| `op` (opcode) | 1 байт | Тип сообщения: `BOOTREQUEST` (1) от клиента, `BOOTREPLY` (2) от сервера. |
| `htype` / `hlen` | 1+1 байт | Тип и длина аппаратного адреса (6 для Ethernet). |
| `hops` | 1 байт | Счётчик прыжков через ретрансляторы (клиент = 0). |
| `xid` | 4 байта | Уникальный идентификатор транзакции. Клиент генерирует случайное число и использует его для сопоставления запросов с ответами. |
| `ciaddr` | 4 байта | Current IP Address — текущий IP клиента (заполняется при продлении аренды). |
| `yiaddr` | 4 байта | Your IP Address — IP-адрес, предлагаемый сервером клиенту. |
| `siaddr` | 4 байта | Server IP Address — адрес сервера, используемого на этапе загрузки (BOOTP/DHCP). |
| `giaddr` | 4 байта | Gateway IP Address — адрес ретранслятора (заполняется Relay Agent). Критически важен для маршрутизации ответа. |
| `chaddr` | 16 байт | Client Hardware Address — MAC-адрес клиента (используется для идентификации и Reservaton). |
| `sname` | 64 байта | Опциональное имя сервера (Boot Server Host Name). |
| `file` | 128 байт | Путь к файлу загрузки (Boot File Name) — используется в PXE. |
| `options` | перем. | Область опций DHCP — до 312 байт (RFC 2131), содержит все настройки. Начинается с_magical cookie_ `0x63825363`. |

## Основные концепции

### DHCPv4: Процесс DORA и типы сообщений
Классическое взаимодействие клиента и сервера в IPv4 состоит из четырёх этапов: **D**iscover -> **O**ffer -> **R**equest -> **A**cknowledge.

1. **Discover (Обнаружение):** Клиент отправляет широковещательный пакет (`255.255.255.255`, UDP 67) для поиска серверов. В поле `ciaddr` = `0.0.0.0`, `xid` — случайное число.
2. **Offer (Предложение):** Сервер резервирует адрес из пула и отправляет клиенту `DHCPOFFER` с параметрами (IP в `yiaddr`, маска, шлюз, DNS). Ответ может быть unicast (если клиент поддерживает) или broadcast.
3. **Request (Запрос):** Клиент выбирает одно предложение (обычно первое) и отправляет `DHCPREQUEST` broadcast с указанием ID выбранного сервера в `Server Identifier` (Option 54). Другие серверы, не выбранные клиентом, возвращают адрес обратно в пул.
4. **Acknowledgement (Подтверждение):** Сервер фиксирует аренду в `dhcpd.leases` (или БД Kea) и отправляет `DHCPACK`. Клиент получает финальную конфигурацию.

#### Временная диаграмма DORA
```
Клиент                          Сервер
  |---- DHCPDISCOVER ----------->|  (Broadcast, xid=0xABCDEF01)
  |<--- DHCPOFFER --------------|  (yiaddr=192.168.1.100)
  |---- DHCPREQUEST ----------->|  (Broadcast, Server ID=10.0.0.1)
  |<--- DHCPACK ----------------|  (Финальные параметры)
  |                             |
  |  Клиент настраивает IP      |
  |  и начинает работу          |
```

**Полный список сообщений DHCPv4:**
- **DHCPNAK (Negative Ack):** Отказ сервера в выдаче адреса (например, адрес уже занят или клиент переместился в другую сеть).
- **DHCPDECLINE:** Сообщение от клиента о том, что предложенный адрес уже используется в сети (обнаружено через ARP).
- **DHCPRELEASE:** Добровольное освобождение адреса клиентом (отправляет при отключении от сети).
- **DHCPINFORM:** Запрос параметров (DNS, маршруты) без запроса IP-адреса. Используется при статической настройке IP.

### DHCPv6: Процесс SARR и режимы работы
В IPv6 процесс использует термины: **S**olicit -> **A**dvertise -> **R**equest -> **R**eply.

1. **Solicit (Поиск):** Клиент ищет серверы через multicast-адрес `ff02::1:2`.
2. **Advertise (Объявление):** Серверы сообщают о своей готовности предоставить адрес.
3. **Request (Запрос):** Клиент запрашивает конкретные параметры у выбранного сервера.
4. **Reply (Ответ):** Сервер подтверждает назначение адреса.

#### Идентификаторы DHCPv6

**DUID (DHCP Unique Identifier)** — уникальный идентификатор сервера или клиента в DHCPv6. Типы DUID:
- **DUID-LLT (Link-Layer Type):** Генерируется на основе MAC-адреса и времени (рекомендуется для серверов).
- **DUID-LL (Link-Layer):** Генерируется на основе MAC-адреса (стабильнее LLT).
- **DUID-EN (Enterprise Number):** Использует код организации (IANA Private Enterprise Number).

**IAID (Identity Association Identifier)** — идентификатор конкретного интерфейса клиента. Позволяет управлять адресами для разных сетевых интерфейсов независимо.

**Типы IA (Identity Association):**
- **IA_NA (Non-temporary):** Ассоциация для постоянных адресов (аналог IPv4-аренды).
- **IA_TA (Temporary):** Ассоциация для временных адресов (Privacy Extensions, RFC 4941).
- **IA_PD (Prefix Delegation):** Ассоциация для делегирования префиксов (используется в IPv6-провайдерах для передачи /48 или /56 подсетей клиенту).

#### Режимы назначения адресов в IPv6:
- **SLAAC (Stateless Address Autoconfiguration):** DHCPv6 не используется. Клиент настраивает адрес сам на основе Router Advertisements (RA).
- **Stateful DHCPv6:** Аналог DHCPv4. Сервер полностью управляет выдачей адресов и хранит состояние (базу аренды).
- **Stateless DHCPv6:** Комбинированный метод. Клиент получает IP-адрес через SLAAC, а DHCPv6 использует только для получения дополнительных параметров (DNS, домен поиска) через сообщение `Information-Request`.

### Механизмы предотвращения конфликтов
Протокол включает проверку на наличие дубликатов IP-адресов перед их окончательным назначением:
- **В IPv4:** Клиент после получения `DHCPACK` может отправить **Gratuitous ARP**. Если кто-то ответил — адрес занят, клиент отправляет `DHCPDECLINE`.
- **В IPv6:** Используется механизм **DAD (Duplicate Address Detection)** через протокол ICMPv6 (Neighbor Solicitation).

### Сравнение DHCPv4 и DHCPv6

| Характеристика | DHCPv4 | DHCPv6 |
| :--- | :--- | :--- |
| **Адресация** | IPv4 (32 бит) | IPv6 (128 бит) |
| **Метод поиска** | Broadcast (`255.255.255.255`) | Multicast (`ff02::1:2`) |
| **Идентификатор клиента** | MAC-адрес (`chaddr`) | DUID + IAID |
| **Настройка шлюза** | Опция 3 (Router) | Через Router Advertisements (RA) |
| **Маска подсети** | Опция 1 (Subnet Mask) | Через Router Advertisements (RA) |
| **Предотвращение конфликтов** | ARP / Gratuitous ARP | ICMPv6 DAD |
| **Временные адреса** | Нет (статика или APIPA) | IA_TA + Privacy Extensions |
| **Делегирование префиксов** | Нет | IA_PD (RFC 3633) |

## Ключевые опции DHCP (SRE и DevOps)

Опции позволяют передавать специфические параметры, критически важные для автоматизации инфраструктуры:

### Базовые сетевые параметры

| Опция | Код | Описание |
| :--- | :--- | :--- |
| **Subnet Mask** | 1 | Маска подсети клиента. |
| **Time Offset** | 2 | Смещение времени от UTC (в секундах). |
| **Router** | 3 | Список IP-адресов шлюзов по умолчанию (Gateway). |
| **Time Server** | 4 | Список IP-адресов серверов времени (NTP/SNTP). |
| **DNS Servers** | 6 | Список IP-адресов DNS-серверов. |
| **Domain Name** | 15 | Доменное имя поиска (например, `corp.example.com`). |
| **Broadcast Address** | 28 | Широковещательный адрес подсети. |

### Время аренды и продления

| Опция | Код | Описание |
| :--- | :--- | :--- |
| **IP Address Lease Time** | 51 | Полный срок аренды (в секундах). |
| **Renewal Time (T1)** | 58 | Время начала unicast-продления (по умолчанию 50% от Lease Time). |
| **Rebinding Time (T2)** | 59 | Время начала broadcast-пересвязывания (по умолчанию 87.5% от Lease Time). |

### Классические и специализированные опции

| Опция | Код | Описание |
| :--- | :--- | :--- |
| **Vendor Class ID** | 60 | Позволяет серверу идентифицировать тип устройства (например, `"PXEClient"`). Используется для передачи разных настроек разному оборудованию. |
| **Client Identifier** | 61 | Уникальный идентификатор клиента (может отличаться от MAC-адреса). |
| **WINS/NBNS Servers** | 44 | Список серверов NetBIOS Name Resolution (для старых Windows-сетей). |
| **NetBIOS Scope** | 47 | Область NetBIOS (используется редко). |
| **Boot Server (PXE)** | 66 | IP-адрес TFTP-сервера для PXE-загрузки. |
| **Bootfile (PXE)** | 67 | Путь к файлу загрузчика на TFTP-сервере. |
| **Classless Static Routes** | 121 | Передача таблицы статических маршрутов с произвольной маской (CIDR). Превосходит Option 3 для сложных сетей. |
| **Relay Agent Information** | 82 | Метаданные о физическом расположении клиента (номер порта, VLAN). Подробности — [DHCP Relay](./dhcp_relay.md). |
| **Captive Portal API** | 114 | URL-адрес для взаимодействия с Captive Portal (RFC 8910), упрощает обнаружение порталов современными ОС. |
| **DNS Search List** | 119 | Список доменов для поиска (напр., `corp.example.com,example.com`). |

## Динамическое обновление DNS (DDNS)

DHCP-сервер может автоматически обновлять DNS-записи (A/AAAA и PTR) при назначении или освобождении адреса. Это критически важно для внутренних корпоративных сетей, где DNS-имена используются для доступа к ресурсам.

**Механизм работы (RFC 2136):**
1. Клиент отправляет `DHCPREQUEST` с флагом `E` (но DDNS-обновления обычно инициируются сервером, а не клиентом).
2. DHCP-сервер вычисляет имя клиента (из Option 12 или шаблона) и обновляет **A/AAAA-запись** в зоне DNS.
3. Сервер обновляет **PTR-запись** (обратный маппинг IP -> имя) в зоне `in-addr.arpa` или `ip6.arpa`.
4. При освобождении адреса (`DHCPRELEASE` или истечение аренды) сервер удаляет или помечает записи как недействительные.

**Настройка в ISC DHCP:**
```conf
ddns-update-style interim;          # Интерактивное обновление (безопаснее, чем "none")
ddns-update-immortal on;            # Не удалять записи при освобождении (опционально)
update-static-leases on;            # Обновлять DNS для статических резерваций

zone corp.example.com. {
    primary 127.0.0.1;              # Локальный DNS-сервер
    key ddns-key;                   # TSIG-ключ для аутентификации
}
```

**Важные ограничения:**
- DDNS требует настройки **TSIG-ключей** между DHCP-сервером и DNS-сервером.
- Windows DNS серверы поддерживают **GSS-TSIG** (Kerberos-based) вместо TSIG.
- В_DYNAMIC_ DNS-зонах рекомендуется установить короткий TTL (300-600 сек), чтобы записи быстрее обновлялись.

## PXE Boot через DHCP

**PXE (Preboot Execution Environment)** — стандарт загрузки операционных систем по сети. DHCP-сервер предоставляет клиенту информацию о TFTP-сервере и файле загрузчика.

### Последовательность PXE-загрузки
```
Клиент (BIOS/UEFI)          DHCP-сервер            TFTP-сервер
     |                          |                      |
     |--- DHCPDISCOVER -------->|                      |
     |    (Option 60=PXEClient) |                      |
     |<-- DHCPOFFER ------------|                      |
     |    (Option 66=10.0.0.200)|                      |
     |    (Option 67=pxelinux.0)|                      |
     |--- DHCPREQUEST --------->|                      |
     |<-- DHCPACK --------------|                      |
     |                          |                      |
     |--- TFTP Request -------->|--------------------->|
     |    (pxelinux.0)          |                      |
     |<-- TFTP Data ------------|<---------------------|
     |                          |                      |
     |  Загрузчик выполняется   |                      |
     |  и запрашивает конфиг    |                      |
```

**Ключевые опции для PXE:**
- **Option 60 (Vendor Class):** Клиент передаёт `"PXEClient"`, сервер определяет, что это PXE-запрос.
- **Option 66 (Next Server):** IP-адрес TFTP-сервера.
- **Option 67 (Bootfile):** Имя файла загрузчика (`pxelinux.0` для BIOS, `grubx64.efi` для UEFI).
- **Option 93 (Client System Architecture):** Клиент сообщает архитектуру (BIOS=0, UEFI=7, x86_64=9).

### Условия для PXE через Relay
Если клиент и TFTP-сервер находятся в разных подсетях:
1. DHCP Relay должен корректно пересылать PXE-опции.
2. TFTP-сервер должен быть доступен из подсети клиента (маршрутизация).
3. Межсетевые экраны должны разрешать TFTP (UDP 69) и DHCP (UDP 67/68).

Подробности — [PXE Boot](../../../Linux/Networking/Concepts/pxe_boot.md).

## Практические команды

### На стороне клиента

#### Linux (dhclient)
```bash
# Принудительное обновление аренды (-release + renew)
sudo dhclient -r eth0 && sudo dhclient -v eth0

# Просмотр текущей аренды
cat /var/lib/dhcp/dhclient.leases

# Просмотр DHCP-клиентского лога
journalctl -u NetworkManager | grep -i dhcp
```

#### Linux (NetworkManager / nmcli)
```bash
# Просмотр DHCP-параметров соединения
nmcli connection show <имя_коннекта> | grep -i dhcp

# Принудительное обновление DHCP
nmcli con up <имя_коннекта>

# Настройка статического IP (без DHCP)
nmcli con mod <имя_коннекта> ipv4.method manual ipv4.addresses 192.168.1.100/24
nmcli con mod <имя_коннекта> ipv4.gateway 192.168.1.1
nmcli con mod <имя_коннекта> ipv4.dns "8.8.8.8,8.8.4.4"
```

#### Windows
```powershell
# Просмотр текущей аренды
ipconfig /all | findstr /i "dhcp"

# Принудительное обновление
ipconfig /release && ipconfig /renew

# Сброс TCP/IP стека (включая DHCP)
netsh int ip reset

# Просмотр DHCP-аренд в реестре
reg query "HKLM\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces" /s | findstr /i "dhcp"
```

### На стороне сервера и Relay

#### Проверка конфигурации
```bash
# ISC DHCP: проверка синтаксиса конфига
dhcpd -t -cf /etc/dhcp/dhcpd.conf
# → Internet Systems Consortium DHCP Server ... configuration file syntax, check failed.

# Kea DHCP: проверка конфигурации
kea-dhcp4 -t -c /etc/kea/kea-dhcp4.conf
# → Configuration file is valid.

# systemd-networkd: проверка DHCP-ретранслятора
networkctl status
```

#### Анализ трафика
```bash
# Захват DHCP-трафика с детализацией опций
sudo tcpdump -i eth0 -n udp port 67 or port 68 -vv -X

# Захват DHCPv6
sudo tcpdump -i eth0 -n udp port 546 or port 547 -vv

# Фильтрация по giaddr (пакеты прошедшие через Relay)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0"

# Wireshark-фильтры
# dhcp.ip.gateway != 0.0.0.0          # Все пакеты с giaddr (прошли через relay)
# bootp.option.dhcp == 1               # Только DHCPDISCOVER
# bootp.option.dhcp == 5               # Только DHCPACK
# dhcp.option.option82                 # Option 82 (Relay Agent Information)
```

#### Просмотр аренд
```bash
# ISC DHCP: текущие аренды
cat /var/lib/dhcp/dhcpd.leases

# Kea DHCP: запрос через REST API
curl -X GET http://localhost:8000/api/kea/v2/leases \
  -H "Authorization: Bearer <token>" | jq .

# Поиск аренды по MAC-адресу
grep -i "00:11:22:33:44:55" /var/lib/dhcp/dhcpd.leases -A 10
```

## Дополнительная информация

- **Механизм аренды:** Таймеры T1/T2 и жизненный цикл адреса — [DHCP Lease Time](./dhcp_lease_time.md).
- **Безопасность:** DHCP Snooping, Dynamic ARP Inspection — [DHCP Security](./dhcp_security.md).
- **Ретрансляция:** Работа через маршрутизаторы — [DHCP Relay](./dhcp_relay.md).
- **Диагностика:** Анализ трафика и tcpdump — [DHCP Troubleshooting](./dhcp_analysis_troubleshooting.md).
- **Настройка сервера:** ISC DHCP и Kea — [ISC DHCP Overview](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_overview.md).
- **Спецификации:**
  - [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131) — Dynamic Host Configuration Protocol (DHCPv4).
  - [RFC 8415](https://datatracker.ietf.org/doc/html/rfc8415) — Dynamic Host Configuration Protocol for IPv6 (DHCPv6).
  - [RFC 3442](https://datatracker.ietf.org/doc/html/rfc3442) — Classless Static Routes (Option 121).
  - [RFC 2136](https://datatracker.ietf.org/doc/html/rfc2136) — Dynamic Updates in DNS (DDNS).
  - [RFC 3633](https://datatracker.ietf.org/doc/html/rfc3633) — IPv6 Prefix Delegation (IA_PD).
