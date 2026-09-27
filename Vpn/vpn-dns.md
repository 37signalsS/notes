# DNS внутри VPN (Split DNS)

## Определения

**Split DNS (раздельный DNS)** — схема, при которой одни зоны (внутренние) резолвятся через DNS-сервер внутри VPN-туннеля, а остальные — через обычный интернет-резолвер. **DNS over tunnel** — доставка DNS-запросов до внутреннего сервера через туннельный интерфейс (10.0.0.x), а не через внешний канал. **MagicDNS** — автоматический DNS поверх mesh-VPN (Tailscale), раздающий имена узлов сети без ручных зон.

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

В WireGuard клиенту DNS задаётся директивой интерфейса (wg-quick при поднятии обновляет `/etc/resolv.conf` через resolvconf/systemd-resolved):

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

- **dnsmasq** — лёгкий conditional forwarding (внутренние зоны → внутренний DNS, остальное → интернет), кэширование, статические записи. SSoT: [dnsmasq](../Networking/Protocols/DNS/dnsmasq.md).
- **unbound** — локальный резолвер с `local-zone`/`local-data`, валидацией DNSSEC. SSoT: [unbound](../Networking/Protocols/DNS/unbound_resolver.md).
- **BIND/PowerDNS** — полноценные авторитативные/кэширующие серверы при крупной инфраструктуре DNS.
- **MagicDNS** (Tailscale) — автоматический вариант, см. [Vpn/tailscale.md](./tailscale.md).

## Практические сценарии

### 1. Split DNS для WireGuard через dnsmasq (классика)

**Серверная часть** — dnsmasq слушает адрес 10.0.0.1 в VPN-подсети (`/etc/dnsmasq.d/vpn.conf`):

```conf
# Слушать только VPN-интерфейс
interface=wg0
bind-interfaces
listen-address=::1,10.0.0.1

# Внутреннюю зону — во внутренний DNS
server=/corp.example/10.20.0.53

# Остальные запросы — на публичные резолверы
server=8.8.8.8
server=1.1.1.1

# Статические записи для теста
address=/vpn-gw.int/10.0.0.1
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

### 3. Split DNS при full tunnel (всё через VPN)

Если `AllowedIPs = 0.0.0.0/0`, весь интернет-трафик клиента идёт через концентратор, и DNS-запросы клиента тоже надо закрыть в туннель — иначе запросы к внутренним зонам уйдут через внешний канал. Варианты:

- серверный DNS в подсети туннеля (как выше) с указанием `DNS = 10.0.0.1`;
- DNS-проксирование/маскарадинг на шлюзе, чтобы client resolver не «выглядывал» наружу.

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

При нескольких внутренних зонах (`corp.example`, `office.internal`) клиенту удобнее домен поиска, чем полные имена:

```ini
[Interface]
DNS = 10.0.0.1
# systemd-resolved через wg-quick допускает и зону поиска (опция зависит от версии);
# строго настраивается в /etc/systemd/resolved.conf
```

```bash
# /etc/systemd/resolved.conf (пример ручного задания на клиенте)
[Resolve]
DNS=10.0.0.1
Domains=corp.example office.internal
```

`resolvectl status wg0` должен показать список `Domains:`. Детали настройки resolver в systemd-пресетах — [systemd-resolved](../Linux/Core/systemd/systemd_resolved.md); тонкости у `wg-quick` на Windows/macOS (DNS пишут GUI-клиенты, см. [Vpn/wireguard.md](./wireguard.md)).

### 7. DNS64 для IPv6-only клиентов

Когда VPN даёт клиенту IPv6, но внутренний сервис — только IPv4 (см. [vpn-ipv6.md](./vpn-ipv6.md)), DNS64 синтезирует AAAA для IPv4-only зон: клиент уходит в IPv6 внутри туннеля во «понятный» префикс, а шлюз транслирует в IPv4. Пример на unbound:

```conf
server:
    module-config: "dns64 validator iterator"
    dns64-prefix: 64:ff9b::/96
```

Без DNS64 IPv6-only клиент не сможет открыть IPv4-only ресурс, даже если NAT64 на шлюзе есть. Подробности — [NAT64/DNS64](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md) и [vpn-ipv6.md](./vpn-ipv6.md).

## Дополнительная информация

- **[dnsmasq — локальный DNS/DHCP-сервер](../Networking/Protocols/DNS/dnsmasq.md)** — conditional forwarding, статические записи, диагностика
- **[Vpn/tailscale.md](./tailscale.md)** — MagicDNS и автоматическое распределение DNS в mesh-VPN
- **[DNS-мониторинг и производительность](../Networking/Protocols/DNS/dns_monitoring.md)** — метрики и наблюдаемость резолверов
- **[Vpn/vpn-ipv6.md](./vpn-ipv6.md)** — DNS64/NAT64 для IPv6-only клиентов
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — canary-проверки доступности DNS внутри туннеля