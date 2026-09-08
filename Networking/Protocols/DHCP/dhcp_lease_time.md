# DHCP — Время аренды и типы сообщений

## Определения

**Lease Time (Время аренды)** — интервал времени, в течение которого клиент может использовать выделенный ему IP-адрес. DHCP является протоколом, основанным на аренде, что позволяет эффективно переиспользовать ограниченный пул адресов и предотвращать накопление неактивных записей.

**T1 (Renewal Time, Option 58)** — время начала продления. По умолчанию равно 50% от Lease Time. Клиент отправляет unicast-запрос `DHCPREQUEST` напрямую серверу, выдавшему адрес.

**T2 (Rebinding Time, Option 59)** — время начала повторного связывания. По умолчанию равно 87.5% от Lease Time. Если исходный сервер не ответил на запрос по T1, клиент отправляет broadcast `DHCPREQUEST` любому серверу в сегменте.

**Preferred Lifetime (IPv6)** — время, в течение которого IPv6-адрес считается предпочтительным для новых соединений. Аналог T1 для IPv6.

**Valid Lifetime (IPv6)** — общее время жизни IPv6-адреса. По истечении адрес удаляется из системы. Аналог Lease Time для IPv6.

### Типы назначения адресов
1. **Dynamic Allocation (Динамическое):** Адрес выдаётся из пула на определённый срок. По истечении срока адрес возвращается в пул, если не был продлён клиентом.
2. **Automatic Allocation (Автоматическое):** Сервер назначает клиенту постоянный IP-адрес из пула. Срок аренды формально бесконечен или автоматически продлевается до тех пор, пока клиент не освободит его.
3. **Static Allocation (Резервирование):** Привязка конкретного IP к MAC-адресу (IPv4) или DUID (IPv6). Выполняется администратором вручную. Подробности — [Резервирование IP в ISC DHCP](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_reservations.md).

## Основные концепции: Таймеры и жизненный цикл

### DHCPv4: Таймеры аренды (RFC 2131)
Сервер передаёт клиенту три ключевых значения времени (в секундах):
- **Lease Time (Option 51):** Полный срок аренды.
- **T1 (Renewal Time, Option 58):** Время начала продления (по умолчанию 50% от Lease Time). Клиент отправляет **unicast** запрос `DHCPREQUEST` серверу, выдавшему адрес.
- **T2 (Rebinding Time, Option 59):** Время начала повторного связывания (по умолчанию 87.5% от Lease Time). Если исходный сервер не ответил, клиент отправляет **broadcast** запрос `DHCPREQUEST` любому доступному серверу в сегменте.

### Жизненный цикл аренды — ASCII-диаграмма

```
Время ─────────────────────────────────────────────────────────────────────────────────►

0%                      T1 (50%)                                   T2 (87.5%)                      100%
|◄─────────────────►|◄──────────────────►|◄──────────────────────────►|◄─────────────────────────►|
|    ACTIVE          |    RENEWAL          |        REBINDING           |         EXPIRED           |
|                    |                     |                            |                           |
| Клиент использует  | Unicast REQUEST     | Broadcast REQUEST          | Клиент прекращает         |
| адрес нормально    | ──────────► сервер  | ──────────► все серверы    | использование адреса      |
|                    |                     |                            |                           |
|                    | Сервер отвечает     | Любой сервер отвечает      | Клиент:                  |
|                    | DHCPACK → продление | DHCPACK → продление        | - Удаляет IP из интерфейса|
|                    |                     |                            | - Начинает заново DORA    |
|                    | Если нет ответа →   | Если нет ответа →          |                           |
|                    | переход к T2        | переход к EXPIRED          |                           |

Примечание: Клиент отправляет DHCPREQUEST с ciaddr = текущий IP (unicast) на T1
            и broadcast (ciaddr = 0.0.0.0, giaddr = 0.0.0.0) на T2.
```

### Состояние аренды на стороне клиента и сервера

DHCP — это не просто «сервер выдал IP и забыл». Между клиентом и сервером существует отдельное состояние аренды, а IP-адрес — только одна его часть.

Когда клиент получает адрес, например `192.168.1.50`, он получает ещё и **lease time** (например, 8 часов). При обычной работе клиент не ждёт окончания lease — он пытается продлить его заранее.

Упрощённая временная диаграмма:

```
0% ───────── 50% ───────── 87.5% ───── 100%
              │              │
           renew          rebind       expire
```

- **T1 (50%):** клиент обращается к DHCP-серверу, который выдал lease, через unicast `DHCPREQUEST`.
- **T2 (87.5%):** если исходный сервер недоступен, клиент отправляет broadcast `DHCPREQUEST`, чтобы найти любой доступный DHCP-сервер в сегменте.

#### Поведение при перезагрузке

При перезагрузке клиент может попытаться вернуть себе прежний адрес. Однако DHCP-сервер не обязан его сохранить: он проверяет актуальность lease и состояние пула.

Поэтому ситуация, когда после перезагрузки клиент получает другой адрес (например, `.73` вместо `.50`), не обязательно означает ошибку DHCP.

#### Где смотреть состояние аренды на клиенте

```bash
# systemd-networkd
networkctl status eth0

# dhclient
cat /var/lib/dhcp/dhclient.leases
# → fixed-address, dhcp-lease-time, renew, rebind, expire

# NetworkManager
nmcli device show eth0 | grep -E "IP4\.(ADDRESS|GATEWAY|DNS)"
nmcli connection show <con_name> | grep -E "ipv4\.(addresses|gateway|dns-search)"
```

При проблемах с DHCP полезно смотреть не только `ip addr`, но и:
- кто выдал lease;
- когда он истекает;
- на каком этапе продления находится клиент.

### DHCPv6: Состояния адреса (RFC 8415)
В IPv6 концепция аренды расширена за счёт состояний адреса, что позволяет реализовать механизм «плавного» перехода (renumbering):
- **Preferred Lifetime:** Время, в течение которого адрес считается предпочтительным для установки новых соединений.
- **Valid Lifetime:** Общее время, в течение которого адрес считается валидным. По истечении этого срока пакеты с данным адресом источника будут отбрасываться ОС.
- **T1/T2:** Аналогично IPv4, управляют процессом обновления параметров IA_NA (Identity Association for Non-temporary Addresses).

| Состояние | Описание |
| :--- | :--- |
| **Preferred** | Адрес активен, используется для новых и старых соединений. |
| **Deprecated** | Срок Preferred истёк. Новые соединения не должны использовать этот адрес, но старые продолжают работать до конца Valid Lifetime. |
| **Invalid** | Срок Valid истёк. Адрес удаляется из системы, трафик блокируется. |

### Формулы расчёта таймеров

| Параметр | Формула (RFC 2131) | Пример (Lease = 24ч) |
| :--- | :--- | :--- |
| **T1 (Renewal)** | 0.5 × Lease Time | 12ч (43200 сек) |
| **T2 (Rebinding)** | 0.875 × Lease Time | 21ч (75600 сек) |
| **Lease Time** | Задаётся сервером | 24ч (86400 сек) |

Клиент может переопределить T1/T2, передав их в `DHCPREQUEST` (Option 58/59), но сервер игнорирует эти значения, если они больше `max-lease-time`.

## Типы сообщений DHCP

### Управляющие сообщения (IPv4)
- **DHCPACK (Acknowledgement):** Положительный ответ сервера. Подтверждает аренду и передаёт параметры.
- **DHCPNAK (Negative Ack):** Отрицательный ответ. Сервер сообщает клиенту, что запрашиваемый адрес недоступен (например, клиент переместился в другую подсеть).
- **DHCPDECLINE:** Сообщение от клиента серверу. Клиент обнаружил конфликт (адрес уже занят в сети, например, ответил на Gratuitous ARP).
- **DHCPRELEASE:** Клиент добровольно освобождает адрес до истечения срока.
- **DHCPINFORM:** Запрос параметров (DNS, NTP) без запроса IP-адреса. Используется при статической настройке IP.

### Эквиваленты в IPv6
- **Renew:** Прямой аналог запроса на продление.
- **Rebind:** Попытка продления через любой доступный сервер.
- **Release:** Освобождение адреса клиентом.
- **Decline:** Сообщение о конфликте адресов.
- **Information-Request:** Аналог `DHCPINFORM` (Stateless DHCPv6).

## Конфигурация на сервере

### ISC dhcpd.conf

```conf
# Глобальные параметры аренды
default-lease-time 86400;       # 24 часа (1 день)
max-lease-time 604800;          # 7 дней (максимум, если клиент запрашивает больше)

# Класс VoIP — более короткая аренда (устройства часто переподключаются)
class "voip-phones" {
    match if substring (option vendor-class-identifier, 0, 4) = "Cisco";
}

# Подсеть для VoIP — короткая аренда (4 часа)
subnet 10.0.20.0 netmask 255.255.255.0 {
    range 10.0.20.100 10.0.20.200;
    default-lease-time 14400;   # 4 часа
    max-lease-time 28800;       # 8 часов (максимум)
    option routers 10.0.20.1;
    option domain-name-servers 10.0.1.10;
}

# Подсеть для серверов — длинная аренда (7 дней)
subnet 10.0.10.0 netmask 255.255.255.0 {
    range 10.0.10.200 10.0.10.250;
    default-lease-time 604800;  # 7 дней
    max-lease-time 604800;      # 7 дней
    option routers 10.0.10.1;
}

# Статическое резервирование (аренда = max-lease-time)
host srv-db-01 {
    hardware ethernet 00:50:56:b1:22:33;
    fixed-address 10.0.10.50;
    default-lease-time -1;      # Бесконечная аренда
    max-lease-time -1;
}
```

### Kea DHCP (dhcrelay4 + kea-dhcp4)

```json
{
  "Dhcp4": {
    "lease-database": {
      "type": "memfile",
      "persist": true,
      "lfc-interval": 3600
    },
    "subnet4": [
      {
        "subnet": "10.0.10.0/24",
        "pools": [{ "pool": "10.0.10.200-10.0.10.250" }],
        "valid-lifetime": 86400,
        "renew-timer": 43200,
        "rebind-timer": 75600
      },
      {
        "subnet": "10.0.20.0/24",
        "pools": [{ "pool": "10.0.20.100-10.0.20.200" }],
        "valid-lifetime": 14400,
        "renew-timer": 7200,
        "rebind-timer": 12600
      }
    ],
    "reservations": [
      {
        "hw-address": "00:50:56:b1:22:33",
        "ip-address": "10.0.10.50",
        "valid-lifetime": -1
      }
    ]
  }
}
```

### Cisco IOS (DHCP-сервер)

```cisco
ip dhcp pool VOIP
 network 10.0.20.0 255.255.255.0
 default-lease-time 14400
 max-lease-time 28800
 dns-server 10.0.1.10
 option 66 ip 10.0.1.20

ip dhcp pool SERVERS
 host 10.0.10.50 255.255.255.0
 client-identifier 0100.5056.b122.33
 default-lease-time -1
 max-lease-time -1
```

## Практические команды клиента

### Linux

```bash
# Просмотр текущей аренды (NetworkManager)
nmcli device show eth0 | grep IP4.ADDRESS
nmcli device show eth0 | grep IP4.DNS
nmcli connection show <con_name> | grep ipv4.lease-time

# Просмотр DHCP-опций через dhclient
cat /var/lib/dhcp/dhclient.leases
# → Пример записи:
# lease {
#   interface "eth0";
#   fixed-address 10.0.10.100;
#   option subnet-mask 255.255.255.0;
#   option routers 10.0.10.1;
#   option dhcp-lease-time 86400;
#   option dhcp-message-type 5;     # DHCPACK
#   option dhcp-server-identifier 10.0.0.1;
#   renew 4 2026/08/26 12:00:00;    # T1
#   rebind 4 2026/08/26 18:48:00;   # T2
#   expire 4 2026/08/27 00:00:00;   # Lease expiration
# }

# Принудительное обновление
sudo dhclient -r eth7 && sudo dhclient -v eth0   # Release + Renew
nmcli con up <con_name>                            # Через NetworkManager

# Просмотр DHCP-клиента через journalctl
journalctl -u NetworkManager | grep -i "dhcp"

# Очистка DHCP-кеша (удаление файла аренды)
sudo rm /var/lib/dhclient/dhclient.leases && sudo dhclient eth0
```

### Windows

```cmd
# Просмотр текущей аренды
ipconfig /all
# → DHCP Enabled, Lease Obtained, Lease Expires, DHCP Server

# Принудительное обновление
ipconfig /release && ipconfig /renew

# Просмотр DHCP-аренд через PowerShell
Get-NetIPAddress -InterfaceAlias "Ethernet" | Select IPAddress, PrefixLength
Get-DhcpServerv4Lease -ScopeId 10.0.10.0

# Обновление для конкретного адаптера
Set-NetIPInterface -InterfaceAlias "Ethernet" -Dhcp Enabled
```

## Нюансы реализации (SRE и DevOps)

### Брошенные аренды (Abandoned Leases)
Когда сервер получает `DHCPDECLINE`, он помечает адрес как **Abandoned**.
- **Логика:** Сервер перестаёт выдавать этот адрес другим клиентам на определённый срок (например, `abandoned-lease-time` в ISC DHCP или Kea), предполагая наличие физического конфликта или устройства со статическим IP.
- **Мониторинг:** Накопление abandoned-адресов в пуле — критический сигнал о проблемах в сети или неправильном планировании IP-пространства.

```bash
# ISC DHCP: поиск abandoned-аренд в логе
grep "abandoning" /var/lib/dhcp/dhcpd.leases
journalctl -u isc-dhcp-server | grep "abandoning"

# Kea DHCP: мониторинг через REST API
curl -s http://localhost:8000/ | jq '.[] | select(.state=="expired-reclaimed")'
```

### Взаимодействие с Dynamic DNS (DDNS)
Время аренды напрямую влияет на актуальность записей в DNS:
- **DNS TTL:** Рекомендуется устанавливать TTL для записей A/AAAA равным или кратным T1 (50% Lease Time). Это гарантирует, что если клиент исчезнет, запись в DNS не будет указывать на «мертвый» IP слишком долго.
- **Очистка (Scavenging):** Если аренда истекает без продления, DHCP-сервер должен отправить запрос на удаление записи из DNS.

### Льготный период (Grace Period)
Многие серверы (Kea, ISC DHCP) поддерживают **Grace Period** — время после истечения Lease Time, в течение которого сервер не отдаёт адрес другому клиенту.
- Это позволяет избежать разрыва связи для клиентов, которые временно отключились от сети или не успели продлить аренду из-за кратковременных сбоев.
- **ISC DHCP:** Grace Period = `max-lease-time` (адрес не выдаётся новому клиенту до конца максимального срока).
- **Kea DHCP:** Параметр `expired-leases-reclaim-timer` (в секундах) — интервал переработки истекших аренд.

### Влияние на DHCP Snooping и DAI

| Событие | Влияние на DHCP Snooping | Действие |
| :--- | :--- | :--- |
| **Lease expired (клиент не продлил)** | Запись в Snooping DB не удаляется до `max-lease-time` | Клиент не может получить новый IP без полного DORA-цикла |
| **DHCPRELEASE (клиент освободил)** | Запись удаляется немедленно | Клиент может сразу получить новый IP |
| **DHCPDECLINE (конфликт)** | Запись помечается как `abandoned` | Клиент будет повторять DORA до успеха |
| **Rogue DHCP-ответ** | Snooping блокирует его на untrusted-порту | Клиент не получит IP от Rogue-сервера |
| **Failover (ick)** | Запись в Snooping DB сохраняется | Клиент продолжает использовать адрес до истечения Lease Time |

**Рекомендация:** При включении DHCP Snooping сначала разверните статические привязки для серверов и Relay, иначе их трафик будет блокирован. Подробности — [DHCP Security](./dhcp_security.md).

## Практические сценарии и оптимизация

| Сценарий | Lease Time | T1 (50%) | T2 (87.5%) | Обоснование |
| :--- | :--- | :--- | :--- | :--- |
| **Публичный Wi-Fi** | 30–120 мин | 15–60 мин | 26–105 мин | Высокая ротация. Длинная аренда приведёт к исчерпанию пула (Pool Exhaustion). |
| **Офисная сеть** | 12–24 часа | 6–12 ч | 10.5–21 ч | Баланс между нагрузкой на сеть и актуальностью данных в IPAM. |
| **Дата-центр / Серверы** | 7–30 дней | 3.5–15 д | 6–26 д | Максимальная стабильность сетевых соединений. |
| **IoT-устройства** | 1–7 дней | 12 ч–3.5 д | 21 ч–6 д | Низкая активность, но стабильная связность для телеметрии. |
| **Kiosk / Терминалы** | 24–72 часа | 12–36 ч | 21–63 ч | Стабильность для устройств, которые не перезагружаются. |
| **Миграция подсети** | 15–30 мин | 7.5–15 мин | 13–26 мин | Снижается заранее (за 24-48ч) до начала работ, чтобы клиенты быстрее «переехали» на новый шлюз. |
| **Корпоративный Wi-Fi (Roaming)** | 4–8 часов | 2–4 ч | 3.5–7 ч | Сбалансированное время для roaming между AP без потери связи. |
| **Гостевой Wi-Fi (PMF)** | 60–240 мин | 30–120 мин | 52–210 мин | Достаточно для сессии, но не загружает пул. |

## Управление базой данных аренды

### ISC DHCP: Формат dhcpd.leases

```text
lease 10.0.10.25 {
  starts 1 2026/07/20 12:00:00; # Формат: <день_недели> <дата> <время>
  ends 2 2026/07/21 12:00:00;
  cltt 1 2026/07/20 11:55:00;   # Client Last Transaction Time
  binding state active;         # Состояние: active, free, backup, abandoned
  next binding state free;
  hardware ethernet 00:50:56:b1:22:33;
  uid "\001\000PV\261\"3";      # Client Identifier (RFC 2132)
  client-hostname "srv-db-01";
}
```

**Состояния аренды (binding state):**
- `active` — адрес выдан клиенту
- `free` — адрес доступен для выдачи
- `backup` — резервная запись (при failover)
- `abandoned` — адрес заблокирован (конфликт)

### Kea DHCP: Бэкап и восстановление

```bash
# Kea хранит аренды в memfile (по умолчанию)
# Путь: /var/lib/kea/kea-leases4.csv

# Бэкап (при остановленном сервере)
cp /var/lib/kea/kea-leases4.csv /backup/kea-leases4.csv.$(date +%Y%m%d)

# Kea LFC (Lease File Cleanup) — автоматическая очистка
# Интервал: lfc-interval в dhcp4.json (по умолчанию 3600 сек)
```

### ISC DHCP: Бэкап и восстановление

```bash
# Бэкап (при остановленном сервере!)
sudo systemctl stop isc-dhcp-server
cp /var/lib/dhcp/dhcpd.leases /backup/dhcpd.leases.$(date +%Y%m%d)

# Восстановление из бэкапа (при остановленном сервере)
sudo systemctl stop isc-dhcp-server
cp /backup/dhcpd.leases.20260826 /var/lib/dhcp/dhcpd.leases
sudo systemctl start isc-dhcp-server
```

## Производительность и нагрузка

| Lease Time | DHCP-трафик (1000 клиентов) | Нагрузка на сеть | Нагрузка на сервер |
| :--- | :--- | :--- | :--- |
| **30 мин** | ~1200 пакетов/мин | Высокая | Высокая (1000 DORA-сессий/час) |
| **4 часа** | ~100 пакетов/мин | Средняя | Средняя |
| **24 часа** | ~17 пакетов/мин | Низкая | Низкая |
| **7 дней** | ~2.4 пакета/мин | Минимальная | Минимальная |

**Примечание:** При каждом обновлении (T1) клиент отправляет 1 пакет DHCPREQUEST и получает 1 пакет DHCPACK. При полном DORA-цикле (после истечения) — 4 пакета. Для 1000 клиентов с ареной 24 часа это ~2000 пакетов в час (или ~0.5 пакета в секунду на сеть), что пренебрежимо мало.

## Типичные ошибки и методы решения

| Проблема | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Клиент получает APIPA (169.254.x.x)** | Lease expired, сервер не ответил на Renew | `ipconfig /all`: Lease Expires | Проверить связность с сервером, DHCP Snooping |
| **Клиент теряет IP через 30 сек** | Lease Time = 30 сек (ошибка конфигурации) | `journalctl -u isc-dhcp-server` | Исправить `default-lease-time` |
| **DHCPNAK при продлении** | Клиент запрашивает адрес из другой подсети | `tcpdump`: DHCPNAK + giaddr | Добавить `authoritative;` или исправить subnets |
| **Адрес не освобождается после DHCPRELEASE** | Сервер не получил RELEASE (потеря пакета) | `grep "free"` в dhcpd.leases | Подождать до истечения Lease Time |
| **Отсутствие IP для новых клиентов** | Пул исчерпан (все адреса заняты) | `dhcp-leases-list` или `cat dhcpd.leases` | Увеличить `range` или сократить `default-lease-time` |
| **DNS запись указывает на мёртвый IP** | DNS TTL > Lease Time | `dig A hostname` + `ipconfig /all` | Установить DNS TTL ≤ T1 |

## Дополнительная информация

- [DHCP — Обзор протокола](./dhcp_overview.md) — базовые принципы и процессы DORA/SARR.
- [Диагностика DHCP](./dhcp_analysis_troubleshooting.md) — анализ трафика и решение проблем с арендой.
- [Безопасность DHCP](./dhcp_security.md) — защита от истощения пула (Starvation).
- [DHCP Relay](./dhcp_relay.md) — работа через маршрутизаторы.
- [Жёсткая защита L2](../VLAN/vlan_security_hardening.md) — SSoT для DHCP Snooping, DAI, IPSG.
- [Резервирование IP в ISC DHCP](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_reservations.md) — практическая реализация статических назначений.
- [ISC DHCP: Базовая настройка](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_basic_config.md) — конфигурация `dhcpd.conf` и таймеров.
- [ISC DHCP: Проверка и мониторинг](../../../Linux/Networking/Services/DHCP/isc_dhcp_server_verification.md) — анализ файла `dhcpd.leases` и диагностика.
- **Спецификации:**
  - [RFC 2131](https://datatracker.ietf.org/doc/html/rfc2131) — Dynamic Host Configuration Protocol.
  - [RFC 2132](https://datatracker.ietf.org/doc/html/rfc2132) — DHCP Options and BOOTP Vendor Class Identifier.
  - [RFC 8415](https://datatracker.ietf.org/doc/html/rfc8415) — Dynamic Host Configuration Protocol for IPv6 (DHCPv6).
  - [RFC 5007](https://datatracker.ietf.org/doc/html/rfc5007) — DHCPv6 Leasequery (запрос состояния аренды).
