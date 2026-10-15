# DNS внутри VPN (Split DNS)

**Актуально для:** WireGuard/wg-quick (wireguard-tools 1.0.x), dnsmasq 2.8x, unbound 1.5+ (DNS64-модуль добавлен в версии 1.5.0), systemd-resolved

## Определения

**Split DNS (раздельный DNS)** — схема, при которой одни зоны (внутренние) резолвятся через DNS-сервер внутри VPN-туннеля, а остальные — через обычный интернет-резолвер. **DNS over tunnel** — доставка DNS-запросов до внутреннего сервера через туннельный интерфейс (10.0.0.x), а не через внешний канал. **MagicDNS** — автоматический DNS поверх mesh-VPN (Tailscale), раздающий имена узлов сети без ручных зон. **DNS leak (утечка DNS)** — резолвинг имён клиента через внешний канал, минуя туннель: запросы видны провайдеру, а внутренние имена могут «утечь» в публичный резолвер. **Search domain (домен поиска)** — суффикс, который клиент приписывает коротким именам (`db` → `db.corp.example`); в systemd-resolved домен с префиксом `~` резолвится исключительно через данный интерфейс.

## Основные концепции

### Почему без split DNS корпоративные имена не работают

Клиент VPN резолвит имена через системный резолвер (например, `8.8.8.8`), который ничего не знает про внутренние зоны (`corp.example`, `db.internal`). В результате:

- внутренние имена не разрешаются или разрешаются неправильно (публичные записи);
- трафик к внутренним сервисам идёт через интернет, а не через туннель;
- утечка запросов о внутренней топологии наружу.

Решение — направить в туннель **DNS-сервер, знающий внутренние зоны**, и раздавать клиентам его адрес.

### Три уровня настройки

| Уровень | Где | Что настраивается |
|---------|-----|-------------------|
| 1. Серверный DNS | DNS-сервер в VPN-подсети (dnsmasq/unbound) | Внутренние зоны + forward остальных запросов |
| 2. Клиентский VPN-конфиг | `wg0.conf` клиента | Директива `DNS = <ip>` у WireGuard, `server=...`/`local-zone` у DNS |
| 3. Маршрутизация | AllowedIPs/владельцы DNS | Адрес DNS-сервера должен попадать в туннель (AllowedIPs) |

В WireGuard клиенту DNS задаётся директивой интерфейса. `wg-quick` при поднятии применяет её через `resolvconf -a tun.<iface> -m 0 -x` (openresolv или shim системного resolver'а), при снятии — через `resolvconf -d tun.<iface> -f`; если `resolvconf` недоступен, DNS не применяется — тогда настройку делают вручную через `PostUp` с `resolvectl` (см. сценарий 6):

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24
DNS = 10.0.0.1

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 10.0.0.0/24
PersistentKeepalive = 25
```

Адрес `10.0.0.1` обязательно должен быть в `AllowedIPs`, иначе запросы к DNS-серверу пойдут мимо туннеля.

### Где взять серверный DNS

- **dnsmasq** — лёгкий conditional forwarding (внутренние зоны → внутренний DNS, остальное → интернет), кэширование, статические записи. Подробнее: [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md).
- **unbound** — локальный резолвер с `local-zone`/`local-data`, валидацией DNSSEC. Подробнее: [unbound](../Networking/Protocols/DNS/unbound_resolver.md).
- **BIND/PowerDNS** — полноценные авторитативные/кэширующие серверы при крупной инфраструктуре DNS.
- **MagicDNS** (Tailscale) — автоматический вариант, см. [Vpn/tailscale.md](./tailscale.md).

## Установка и настройка

**Предусловия** (сервер `10.0.0.1` — WireGuard-шлюз в VPN-подсети `10.0.0.0/24`):

```bash
# Сервер: установлен DNS-сервер, интерфейс wg0 поднят
sudo apt install dnsmasq        # или unbound
sudo wg show wg0
# → interface: wg0
#   public key: ...
#   10.0.0.1/24

# Порт 53 свободен на VPN-адресе. systemd-resolved слушает 127.0.0.53 — конфликта нет,
# но локальный dnsmasq или NetworkManager могут занять 0.0.0.0:53
sudo ss -ulnp | grep :53

# Клиент: wireguard-tools (wg-quick) и resolvconf (openresolv) либо systemd-resolved
wg-quick --version
# → 1.0.20210914
command -v resolvconf || command -v resolvectl
# → /usr/sbin/resolvconf  (или /usr/bin/resolvectl)
```

**Порядок настройки split DNS:**

1. Поднять DNS-сервер в VPN-подсети (сценарии 1–2), открыв порт 53 только для `wg0`.
2. Раздавать клиентам адрес этого сервера: `DNS = 10.0.0.1` в клиентском конфиге WireGuard (или `push "dhcp-option DNS ..."` в OpenVPN — сценарий 8).
3. Проверить, что адрес DNS-сервера входит в `AllowedIPs` клиента (иначе запросы пойдут мимо туннеля).
4. Валидация: `dig @10.0.0.1 db.corp.example` с клиента и `ip route get 10.0.0.1` (→ `dev wg0`).

## Практические сценарии

### 1. Split DNS для WireGuard через dnsmasq (классика)

**Серверная часть** — dnsmasq слушает адрес 10.0.0.1 в VPN-подсети (`/etc/dnsmasq.d/vpn.conf`):

```conf
# Слушать только VPN-интерфейс
interface=wg0
bind-interfaces
listen-address=::1
listen-address=10.0.0.1

# Внутреннюю зону — во внутренний DNS
server=/corp.example/10.20.0.53

# Остальные запросы — на публичные резолверы
server=8.8.8.8
server=1.1.1.1

# Статические записи для теста
address=/vpn-gw.int/10.0.0.1
```

Валидация и запуск:

```bash
sudo dnsmasq --test
# → dnsmasq: syntax check OK
sudo systemctl restart dnsmasq
```

**Клиентская часть** — конфиг из «Основных концепций» выше с `DNS = 10.0.0.1`.

**Проверка:**

```bash
# С клиента: внутренняя зона резолвится через туннель
dig @10.0.0.1 db.corp.example +short
# → 10.20.0.55

# Внешняя зона — тоже работает (форвардинг)
dig @10.0.0.1 example.com +short
# → 93.184.216.34

# Трафик к DNS идёт через wg0
ip route get 10.0.0.1
# → 10.0.0.1 dev wg0 src 10.0.0.2
```

### 2. Множественные зоны и DNSSEC через unbound

`/etc/unbound/unbound.conf` на сервере 10.0.0.1:

```conf
server:
    interface: 10.0.0.1
    access-control: 10.0.0.0/24 allow
    # локальные зоны без интернет-запроса
    local-zone: "corp.example." transparent
    local-data: "auth.corp.example. IN A 10.20.0.10"
    # всё остальное — вверх
    forward-zone:
        name: "."
        forward-addr: 1.1.1.1
```

`local-zone ... transparent` — внутренние имена резолвятся из `local-data` и внутренних форвардов, а не падают в интернет. Подробности: [unbound resolver](../Networking/Protocols/DNS/unbound_resolver.md).

```bash
# Проверка конфига до перезапуска
sudo unbound-checkconf /etc/unbound/unbound.conf
# → unbound-checkconf: no errors in /etc/unbound/unbound.conf
```

### 3. Split DNS при full tunnel (всё через VPN)

Если `AllowedIPs = 0.0.0.0/0`, весь интернет-трафик клиента идёт через концентратор, и DNS-запросы клиента тоже надо закрыть в туннель — иначе запросы к внутренним зонам уйдут через внешний канал. Варианты:

- серверный DNS в подсети туннеля (как выше) с указанием `DNS = 10.0.0.1`;
- DNS-проксирование/маскарадинг на шлюзе, чтобы client resolver не «выглядывал» наружу;
- на клиенте с systemd-resolved — исключительная маршрутизация всего DNS через туннель: `PostUp = resolvectl domain %i ~.` (все запросы идут только через `wg0`).

### 4. Диагностика DNS внутри VPN

```bash
# Какой резолвер сейчас используется
resolvectl status wg0
# → Current DNS Server: 10.0.0.1
# → DNS Servers: 10.0.0.1

# Прямой запрос к серверному DNS
dig @10.0.0.1 anydb.corp.example

# Трафик DNS на сервере
sudo tcpdump -i wg0 port 53
# → ... 10.0.0.2.42753 > 10.0.0.1.53: 1+ A? db.corp.example. (33)

# Проблема: клиент резолвит не через туннель
# Проверить маршрут до DNS-адреса
ip route get 10.0.0.1
# Если маршрут идёт не через wg0 — AllowedIPs не покрывает DNS-адрес
```

Логи dnsmasq подскажут, что именно форвардится: [dnsmasq diagnostics](../Networking/Protocols/DNS/dnsmasq.md).

### 5. Проверка утечек DNS (dns leak test)

Утечка — когда клиент VPN резолвит имена через внешний канал, а не через туннель (видно в логах провайдера/внутренней инфраструктуре). Быстрая проверка с произвольного узла:

```bash
# 1) Какой внешний IP видит резолвер туннеля? (кто на самом деле отвечает)
dig +short myip.opendns.com @resolver1.opendns.com
# → 203.0.113.50   ← внешний IP концентратора (OK — туннель держит)
# → 84.52.9.1      ← IP публичного канала клиента (УТЕЧКА)

# 2) Какой резолвер реально используется системой (не из конфига)
resolvectl status | grep -A3 "Current DNS Server"
# → 10.0.0.1 (OK) / 8.8.8.8 (утечка/не настроен split)

# 3) Проверка, что внутренняя зона НЕ доступна снаружи туннеля
dig @8.8.8.8 db.corp.example +short
# → пусто/служебный ответ — правильно (внутренние имена не светятся наружу)

# 4) Все ли интерфейсы закрывают DNS наружу (сетевой раздел)
sudo tcpdump -i any "udp and (port 53 or port 853)" 2>/dev/null | head
```

Полный автомат-тест аналогичен blackbox-проверкам из [vpn-monitoring.md](./vpn-monitoring.md): можно добавить метрику `vpn_dns_no_leak 1|0` в textfile-коллектор (см. раздел про canary в [vpn-monitoring.md](./vpn-monitoring.md)).

### 6. Search domain и split с несколькими зонами

При нескольких внутренних зонах (`corp.example`, `office.internal`) клиенту удобнее домен поиска, чем полные имена. `wg-quick` принимает в `DNS` не только IP-адреса, но и не-IP имена — они становятся доменами поиска:

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24
DNS = 10.0.0.1, corp.example
```

`wg-quick` передаёт это в `resolvconf` (`nameserver 10.0.0.1` + `search corp.example`). На системах с systemd-resolved, где нет shim `resolvconf`, настройку применяют вручную через `PostUp`:

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24
PostUp = resolvectl dns %i 10.0.0.1; resolvectl domain %i ~corp.example
PreDown = resolvectl revert %i
```

Префикс `~` перед доменом делает его «исключительно маршрутизируемым»: зона `corp.example` резолвится только через `wg0`, а остальные зоны остаются на резолверах хоста. Для full-tunnel (весь DNS через туннель) — `resolvectl domain %i ~.` (см. сценарий 3).

```bash
# Проверка: у интерфейса wg0 должен быть резолвер и домен
resolvectl status wg0
# → Current DNS Server: 10.0.0.1
# → DNS Servers: 10.0.0.1
# → DNS Domain: ~corp.example

# Короткое имя резолвится через домен поиска (glibc учитывает search list)
getent hosts db
# → 10.20.0.55   db.corp.example
```

Детали настройки resolver в systemd-пресетах — [systemd-resolved](../Linux/Core/systemd/systemd_resolved.md); тонкости у `wg-quick` на Windows/macOS (DNS пишут GUI-клиенты, см. [Vpn/wireguard.md](./wireguard.md)).

### 7. DNS64 для IPv6-only клиентов

Когда VPN даёт клиенту IPv6, но внутренний сервис — только IPv4 (см. [vpn-ipv6.md](./vpn-ipv6.md)), DNS64 синтезирует AAAA для IPv4-only зон: клиент уходит в IPv6 внутри туннеля во «понятный» префикс, а шлюз транслирует в IPv4. DNS64-модуль в unbound доступен с версии 1.5.0. Пример на unbound:

```conf
server:
    module-config: "dns64 validator iterator"
    dns64-prefix: 64:ff9b::/96
```

Без DNS64 IPv6-only клиент не сможет открыть IPv4-only ресурс, даже если NAT64 на шлюзе есть. Подробности — [NAT64/DNS64](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md) и [vpn-ipv6.md](./vpn-ipv6.md).

### 8. Split DNS для OpenVPN

OpenVPN раздаёт DNS-сервер и домен поиска клиенту через DHCP-опции (push), а клиент применяет их скриптом `update-resolv-conf`:

```ini
# /etc/openvpn/server.conf (сервер)
push "dhcp-option DNS 10.8.0.1"
push "dhcp-option DOMAIN corp.example"
```

```ini
# /etc/openvpn/client.conf (клиент)
script-security 2
up /etc/openvpn/update-resolv-conf
down /etc/openvpn/update-resolv-conf
```

Скрипт `update-resolv-conf` (из состава OpenVPN) правит `/etc/resolv.conf` при подключении и восстанавливает исходное состояние при отключении; для systemd-resolved применяется вариант `update-systemd-resolved` (работает через D-Bus). Проверка:

```bash
resolvectl status tun0
# → Current DNS Server: 10.8.0.1
# → DNS Domain: corp.example
```

Контекст настройки OpenVPN за NAT и полный конфиг — [NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md); типовые проблемы с push-ом DNS — [OpenVPN](../Networking/Tunnels/openvpn.md).

## Устранение неполадок

| Симптом | Причина | Диагностика | Решение |
|---------|---------|-------------|---------|
| `Name or service not known` для внутренних имён | DNS-сервер не задан в клиентском конфиге или адрес DNS не в `AllowedIPs` | `resolvectl status`, `ip route get 10.0.0.1` | Задать `DNS = 10.0.0.1`; включить адрес DNS-сервера в `AllowedIPs` |
| Внутренние имена резолвятся, но запросы уходят наружу (утечка) | Не настроен split: системный resolver по умолчанию публичный | `dig @8.8.8.8 db.corp.example +short` (сценарий 5) | Настроить split DNS (сценарии 1–2, 6) |
| `wg-quick up` падает с `resolvconf: command not found` | Нет resolvconf/openresolv и нет shim systemd-resolved | `command -v resolvconf` | Установить `openresolv` или применять `PostUp` с `resolvectl` (сценарий 6) |
| После `wg-quick down` не работает внешний DNS | resolvconf не восстановил исходный resolv.conf | `cat /etc/resolv.conf` | Повторить `wg-quick down`; при systemd-resolved — `resolvectl revert wg0` |
| dnsmasq не отвечает на адресе 10.0.0.1 | `listen-address` не совпадает с адресом `wg0`, либо порт 53 занят | `sudo ss -ulnp \| grep :53`, `sudo dnsmasq --test` | Выровнять `listen-address` с адресом интерфейса (по одной директиве на адрес), освободить порт |
| unbound отвечает NXDOMAIN/REFUSED для внутренней зоны | Зона не покрыта `local-zone`/`local-data` или нет форварда для зоны | `sudo unbound-checkconf`, `dig @10.0.0.1 db.corp.example` | Добавить `local-data`/`server=` для зоны; проверить `access-control` |
| DNSSEC-валидация ломает неподписанную внутреннюю зону | Зона не подписана, валидатор отвергает ответы | `dig @10.0.0.1 db.corp.example +dnssec` (SERVFAIL) | `domain-insecure: "corp.example"` в unbound (сценарий 2) |

## Лучшие практики

- **DNS-сервер — в туннельной подсети, и только на ней.** Слушать `wg0` (`interface=wg0` + `bind-interfaces` у dnsmasq, `access-control: 10.0.0.0/24 allow` у unbound), чтобы внутренний resolver не был доступен извне.
- **Адрес DNS-сервера всегда включать в `AllowedIPs`** клиента — иначе split DNS не работает даже при правильном `DNS =`.
- **Валидировать конфиги перед применением:** `dnsmasq --test`, `unbound-checkconf`, `wg-quick strip <conf>` (выводит конфиг без wg-quick-специфичных ключей — полезно для передачи `wg setconf`).
- **DNSSEC для внешних форвардов** (validator в unbound); для неподписанных внутренних зон явно указывать `domain-insecure`.
- **Домены поиска — через `~` (исключительная маршрутизация), а не через подмену глобального resolver'а**, чтобы split-сценарий случайно не перехватывал весь интернет-трафик.
- **`log-queries` только при отладке** — запросы пишут в лог и нагружают диск (см. [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md)).
- **Проверять утечки после каждого изменения** конфига (сценарий 5) и держать canary-проверку в мониторинге (см. [vpn-monitoring.md](./vpn-monitoring.md)).
- **Откат изменений:** `wg-quick down <conf>` снимает интерфейс вместе с DNS-настройками; удаление `/etc/dnsmasq.d/vpn.conf` + `systemctl restart dnsmasq` убирает серверный split.

## Дополнительная информация

- **[dnsmasq — локальный DNS/DHCP-сервер](../Networking/Protocols/DNS/dnsmasq.md)** — conditional forwarding, статические записи, диагностика
- **[Unbound — рекурсивный резолвер](../Networking/Protocols/DNS/unbound_resolver.md)** — `local-zone`/`local-data`, DNSSEC, DNS64
- **[Vpn/tailscale.md](./tailscale.md)** — MagicDNS и автоматическое распределение DNS в mesh-VPN
- **[DNS-мониторинг и производительность](../Networking/Protocols/DNS/dns_monitoring.md)** — метрики и наблюдаемость резолверов
- **[Vpn/vpn-ipv6.md](./vpn-ipv6.md)** — DNS64/NAT64 для IPv6-only клиентов
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — canary-проверки доступности DNS внутри туннеля
- **[Vpn/wireguard.md](./wireguard.md)** — клиентский конфиг wg-quick, особенности Windows/macOS
- **[systemd-resolved](../Linux/Core/systemd/systemd_resolved.md)** — per-link DNS и домены маршрутизации (`~`)
- **[OpenVPN](../Networking/Tunnels/openvpn.md)** — push DHCP-опций и update-resolv-conf
