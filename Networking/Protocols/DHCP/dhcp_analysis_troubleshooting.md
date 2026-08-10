# Диагностика и анализ трафика DHCP

## Определения

**Анализ трафика DHCP (Dynamic Host Configuration Protocol)** — процесс перехвата и декодирования пакетов протокола для выявления ошибок в конфигурации, сетевых задержек или несанкционированных действий (Rogue DHCP).

**Диагностика (troubleshooting) DHCP** — систематический процесс поиска причин отказа в выдаче IP-адресов, охватывающий уровни от L2 (связность) до L7 (логика сервера).

**APIPA (Automatic Private IP Addressing)** — механизм самоназначения адреса из сети `169.254.0.0/16` (IPv4), когда DHCP-сервер недоступен. В IPv6 аналогичную роль играют **Link-Local** адреса (`fe80::/10`), назначаемые всегда.

## Сравнение процессов DORA (v4) и SARR (v6)

Для эффективной диагностики необходимо понимать различия в хендшейках протоколов:

| Этап | DHCPv4 (DORA) | DHCPv6 (SARR) | Транспорт |
| :--- | :--- | :--- | :--- |
| **1. Поиск** | **D**iscover (Broadcast) | **S**olicit (Multicast `ff02::1:2`) | UDP 67/68 (v4), 547/546 (v6) |
| **2. Ответ** | **O**ffer (Unicast/Broadcast) | **A**dvertise (Unicast) | - |
| **3. Запрос** | **R**equest (Broadcast) | **R**equest (Multicast) | - |
| **4. Финал** | **A**cknowledge (Unicast) | **R**eply (Unicast) | - |

**Нюанс IPv6:** DHCPv6 часто не передаёт шлюз по умолчанию. Клиент получает его через **Router Advertisements (RA)**. Если IPv6-адрес получен, но интернета нет — проверяйте флаги RA (M/O) и наличие маршрутов.

## Практические сценарии диагностики

### Анализ на стороне клиента

#### Принудительное обновление (Force Renew)
| ОС | Команда |
| :--- | :--- |
| **Windows** | `ipconfig /release` && `ipconfig /renew` |
| **Linux (dhclient)** | `sudo dhclient -r` && `sudo dhclient -v eth0` |
| **Linux (NetworkManager)** | `nmcli con up <con_name>` |

#### Проверка IPv6 и DAD
Если адрес помечен как `tentative`, возможно, механизм **DAD (Duplicate Address Detection)** обнаружил конфликт.
```bash
ip -6 addr show eth0
# Ищем флаг "tentative" или "dadfailed"
```

### Анализ на стороне сервера и Relay Agent

#### Поиск в системных журналах
Наиболее частая ошибка — **Pool Exhaustion** (исчерпание пула).
```bash
# Просмотр логов в реальном времени
journalctl -u isc-dhcp-server -f | grep -E "no free leases|abandoning"
```
- **Abandoned Leases:** Если сервер помечает адрес как `abandoning`, значит он получил `DHCPDECLINE` (клиент обнаружил, что адрес занят).

#### Проверка базы данных аренды
```bash
# Просмотр текущих активных аренд
grep "lease" /var/lib/dhcp/dhcpd.leases -A 10
```

### Анализ трафика (tcpdump и Wireshark)

#### Рекомендуемые фильтры tcpdump
```bash
# Захват IPv4 DHCP с детализацией (включая giaddr и опции)
sudo tcpdump -i eth0 -n udp port 67 or port 68 -vv

# Захват IPv6 DHCP
sudo tcpdump -i eth0 -n udp port 546 or port 547 -vv

# Проверка прохождения через Relay (фильтрация по giaddr)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0"
```

#### Поля для анализа в Wireshark
- **`dhcp.ip.client` (`ciaddr`):** Текущий IP клиента (при продлении).
- **`dhcp.ip.gateway` (`giaddr`):** IP ретранслятора. Если он неверен, сервер не сможет сопоставить запрос с нужным пулом (subnet).
- **`dhcp.option.dhcp_server_id`:** IP сервера, чьё предложение выбрал клиент. Помогает найти **Rogue DHCP**.
- **`ipv6.dhcpv6.option.ia_na`:** Параметры назначения адреса в IPv6.

## Диагностика DHCPv6 и взаимодействие с RA

В IPv6 DHCP работает в связке с Router Advertisements. Проверьте флаги в пакетах RA (ICMPv6 Type 134):
- **Managed Address Config (M-flag):** Если `1`, клиент должен запрашивать IP у DHCPv6 (Stateful).
- **Other Config (O-flag):** Если `1`, клиент запрашивает только опции (DNS, NTP) у DHCPv6 (Stateless).

Если флаги установлены неверно на маршрутизаторе, клиент никогда не отправит `Solicit`.

## Типичные проблемы и методы решения

| Проблема | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **APIPA (169.254.x.x)** | Нет L2-связности или DHCP Snooping блокирует сервер | `tcpdump` на сервере: приходят ли запросы? | Проверить VLAN, порты коммутатора (Trusted/Untrusted). |
| **No Free Leases** | Исчерпание пула адресов | Лог: `no free leases` | Увеличить `range` или сократить `default-lease-time`. |
| **DHCP Relay Failure** | Неверный `giaddr` или отсутствие маршрута к нему | `tcpdump` на сервере: поле `giaddr` равно `0.0.0.0`? | Проверить конфиг ретранслятора (`ip helper-address`). |
| **Конфликт IP (NAK)** | Наличие статических IP внутри пула DHCP | `tcpdump`: пакет `DHCPNAK` или `DHCPDECLINE` | Исключить статику через `reserved-range` или `ping-check`. |
| **DNS не обновляется** | Ошибки DDNS или отсутствие прав в BIND | Лог сервера: `unable to add forward map` | Проверить `tsig` ключи и права доступа к зонам DNS. |

## Дополнительная информация

- [Обзор DHCP](./dhcp_overview.md) — базовые принципы и процессы DORA/SARR.
- [Время аренды и типы сообщений](./dhcp_lease_time.md) — детальный разбор таймеров и типов пакетов.
- [Безопасность DHCP](./dhcp_security.md) — защита от Rogue DHCP и атак истощения.
- [Настройка ISC DHCP Relay](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_relay.md) — практическая диагностика ретрансляции.
- **Спецификации:** [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131) (Troubleshooting section), [RFC 8415](https://datatracker.ietf.org/doc/html/rfc8415) (v6).