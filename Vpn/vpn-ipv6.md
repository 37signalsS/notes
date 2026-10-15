# IPv6 внутри VPN

**Актуально для:** WireGuard/wg-quick (wireguard-tools 1.0.x), Linux iproute2 6.x, iputils ≥20150815 (`ping6` объединён с `ping`), nftables ≥0.9 (ядро ≥4.14)

## Определения

**ULA (Unique Local Address)** — диапазон `fc00::/7` по RFC 4193, аналог RFC 1918 для IPv6; локально назначаемая половина — `fd00::/8` (бит L=1) с псевдослучайным 40-битным Global ID. **Dual Stack** — одновременная работа модулей IPv4 и IPv6 на узле/сети. **NAT64/DNS64** — трансляция IPv6→IPv4 на шлюзе (пакетам IPv6-only сетей даётся доступ к IPv4-ресурсам). **SIT/6in4** — переходный механизм: инкапсуляция IPv6 в IPv4-пакеты (протокол IP 41). **SLAAC** — автоматическая конфигурация адреса IPv6 через Router Advertisement. **PMTUD** — обнаружение Path MTU: в IPv6 маршрутизаторы не фрагментируют пакеты, а отправляют ICMPv6 Type 2 (Packet Too Big).

## Основные концепции

### Что «IPv6 в VPN» покрывает

1. **Адресация туннеля** — присвоение интерфейсу `Address = fdxx:xxxx::1/64` вместо/вместе с IPv4 (в конфиге WireGuard это обычный префикс).
2. **Транспорт по IPv6** — сам Endpoint (внешний адрес концентратора) может быть IPv6: клиент достукивается до шлюза по глобальному IPv6.
3. **IPv6-трафик клиентов** — `AllowedIPs = ::/0` для full tunnel IPv6; split tunnel добавляет только VPN-префикс.
4. **DNS** — AAAA-записи внутренних сервисов и DNS64 для IPv6-only клиентов.

### Модель адресации

| Назначение | Диапазон | Пример |
|------------|----------|--------|
| VPN-подсеть | ULA `fd00::/8` | `fd12:3456:789a:bcde::/64` (Global ID — псевдослучайный) |
| Концентратор | один адрес интерфейса | `fd12:3456:789a:bcde::1/64` |
| Клиент | /128 на пир в AllowedIPs | `fd12:3456:789a:bcde::2/128` |
| Транспорт Endpoint | глобальный IPv6 | `[2001:db8:1::10]:51820` |

ULA не маршрутизируется в глобальный Интернет — подходящий выбор для «внутренней» VPN-сети без конфликта с реальным IPv6 провайдера. Внимание: `fd7a:115c:a1e0::/48` — зарезервированный префикс Tailscale (ранее `fd7a:115c:a1e0:ab12::/64`); в средах с Tailscale выбирайте другой Global ID, чтобы избежать пересечения префиксов.

### Режимы адресации клиентов

- **Статический /128 на пир** — стандарт для WireGuard: адрес клиента фиксируется в `AllowedIPs` концентратора. Масштабируется до сотен пиров, адрес ведётся в учётной системе (см. [wireguard-key-management.md](./wireguard-key-management.md)).
- **SLAAC/RA для downstream** — WireGuard сам не генерирует Router Advertisement; если за концентратором есть Ethernet-сегмент, раздавать ULA-подсеть хостам можно через `radvd` (типовая связка: WG-туннель → radvd → SLAAC-хосты). DHCPv6 — альтернатива для централизованной выдачи.

### Особенности по сравнению с IPv4

- Адресное пространство позволяет не думать об экономии: каждому пиру выделяется /128, подсети — /64.
- `wg-quick` и ядро работают с IPv6 нативно: в `AllowedIPs` можно указывать и `0.0.0.0/0`, и `::/0` одновременно; при default-route в любом семействе `wg-quick` использует `ip-rule` для переопределения шлюза. Отдельного ключа «включить IPv6» в wg-quick нет — и быть не должно (см. сценарий 1).
- **Happy Eyeballs** (RFC 8305) на клиенте выбирает более быстрый транспорт: даже если IPv6 VPN настроен, приложения могут предпочесть IPv4 (см. [Dual Stack](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)).
- MTU: WireGuard добавляет 60 байт overhead при IPv4-транспорте и 80 байт при IPv6-транспорте (UDP 8 + WG 32 + внешний IP 20/40 + тег 16). Для пути 1500 байт безопасное значение MTU туннеля — **1420** (подходит обоим семействам; при исключительно IPv4-транспорте хватит 1440). `wg-quick` автодетектирует MTU из маршрута к Endpoint, но для однородности сети разумно задать `MTU = 1420` явно. Ниже **1280** опускаться нельзя — минимальный MTU IPv6 по RFC 8200. IPv6 не фрагментируется на промежуточных маршрутизаторах (PMTUD обязателен), поэтому неправильный MTU в туннеле заметнее ломает связь: мелкие пакеты ходят, крупные TCP-сессии «зависают».

## Практические сценарии

Предварительные требования: `wireguard-tools`, `nftables`, включённый IPv6 forwarding на концентраторе (`net.ipv6.conf.all.forwarding=1`).

### 1. WireGuard-туннель с IPv6-адресацией (dual-stack)

Концентратор:

```ini
[Interface]
PrivateKey = <private_key>
Address = 10.0.0.1/24, fd12:3456:789a:bcde::1/64
ListenPort = 51820
MTU = 1420

[Peer]
PublicKey = <client_public_key>
AllowedIPs = 10.0.0.2/32, fd12:3456:789a:bcde::2/128
```

Клиент:

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24, fd12:3456:789a:bcde::2/64
DNS = 10.0.0.1, fd12:3456:789a:bcde::1
MTU = 1420

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 10.0.0.0/24, fd12:3456:789a:bcde::/64
PersistentKeepalive = 25
```

Важно: строки вида `IPv6 = on` в `[Interface]` недопустимы — такого ключа нет ни у wg-quick, ни у wg(8); `wg-quick` передаст его в `wg setconf`, и конфиг не применится. IPv6 включается самим фактом наличия IPv6-адресов в `Address`/`AllowedIPs`.

Проверка:

```bash
sudo wg-quick up wg0
ip -6 addr show dev wg0
# → 2: wg0 ... fd12:3456:789a:bcde::2/64 ...
sudo wg show wg0 allowed-ips
# → <pubkey>  10.0.0.2/32, fd12:3456:789a:bcde::2/128
ping -6 fd12:3456:789a:bcde::1
# → 64 bytes from fd12:3456:789a:bcde::1: icmp_seq=1 time=12.3 ms
```

### 2. Endpoint концентратора по IPv6

Если у шлюза есть глобальный IPv6, Endpoint указывается как `[2001:db8:1::10]:51820`. Нюанс резолва: WireGuard резолвит hostname Endpoint **один раз, при подъёме интерфейса**, и использует **первый** адрес из ответа `getaddrinfo` — записи A и AAAA вместе автоматического fallback между семействами не дают (на dual-stack хосте обычно побеждает IPv6, и клиент без IPv6-пути не переключится на A-запись). Второй `[Peer]` с тем же ключом не создашь — дубликат pubkey отвергается. Варианты обеспечения fallback:

- два отдельных конфига (IPv4- и IPv6-Endpoint) и ручной выбор;
- hostname, резолвящийся только в IPv4, плюс второй конфиг для IPv6-only сетей;
- периодический перезапуск или `contrib/reresolve-dns/reresolve-dns.sh` из wireguard-tools для обновления Endpoint по DNS.

### 3. Split tunnel IPv6

```ini
# Только внутренний IPv6-префикс через туннель, глобальный IPv6 — напрямую
AllowedIPs = 10.0.0.0/24, fd12:3456:789a:bcde::/64
# Не указывайте ::/0, если не хотите гнать весь IPv6 через VPN
```

### 4. Firewall IPv6 для концентратора (nftables)

Сначала форвардинг — без него трафик между пирами не пойдёт:

```bash
sudo sysctl -w net.ipv6.conf.all.forwarding=1
# → net.ipv6.conf.all.forwarding = 1
```

Правила (таблица `inet` покрывает оба семейства):

```bash
# Входящий WG-порт: источники — глобальные адреса клиентов из Интернета,
# а не ULA (ULA-источники возможны только от внутренних site-to-site пиров)
nft add rule inet filter input udp dport 51820 ct state new limit rate over 100/minute drop
nft add rule inet filter input udp dport 51820 accept

# ICMPv6 Type 2 (Packet Too Big) обязателен для PMTUD:
# блокировка = «чёрная дыра» MTU (мелкие пакеты проходят, крупные сессии виснут)
nft add rule inet filter input icmpv6 type packet-too-big accept
nft add rule inet filter input icmpv6 type echo-request accept

# Форвардинг IPv6 из туннеля
nft add rule inet filter forward iifname "wg0" accept

# MSS Clamping для TCP over IPv6 в туннеле (аналог ip6tables ... -j TCPMSS --clamp-mss-to-pmtu)
nft add rule inet filter forward tcp flags syn /(syn|rst) tcp option maxseg size set rt mtu
```

Операционные замечания:

- Правила, добавленные через `nft add rule`, живы до перезагрузки — для постоянного применения размещайте их в `/etc/nftables.conf` (Debian/RHEL: `systemctl enable --now nftables`).
- `ip6tables` по-прежнему работает (обычно как фронтенд над nftables) и эквивалентен: `ip6tables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`. Для новых конфигураций предпочтителен нативный синтаксис nftables.
- Полный hardening IPv6-стека и критических типов ICMPv6 (NDP, MLD) — [Firewall для IPv6](../Linux/Networking/Settings/ipv6_configuration/firewall.md) и [Сетевая безопасность Linux](../Linux/Security/Mechanisms/Kernel/hardening.md).

### 5. IPv6-only клиент и NAT64/DNS64

Когда клиент сидит в IPv6-only сети, а внутренние сервисы — только IPv4, на шлюзе поднимается NAT64/DNS64 (например, `tayga` или `jool`). DNS64 синтезирует AAAA из A-записи, используя Well-Known Prefix `64:ff9b::/96` (RFC 6052); внутренний DNS (см. [vpn-dns.md](./vpn-dns.md), раздел про DNS64 на unbound) отдаёт клиенту «синтезированные» AAAA. Полное описание механизма, конфигурации Tayga и альтернатив (SIT/6in4 для перехода) — [Сценарии NAT64](../Networking/Concepts/nat/practical_scenarios.md#технологии-перехода-на-ipv6-nat64) и [Переходные механизмы IPv6](../Linux/Networking/Settings/ipv6_configuration/concepts.md).

## Диагностика

```bash
# Маршрут через туннель по IPv6
ip -6 route get fd12:3456:789a:bcde::2
# → fd12:3456:789a:bcde::2 dev wg0 src fd12:3456:789a:bcde::1
#   (metric 1024, pref medium)

# Endpoint, до которого клиент реально достучался
sudo wg show wg0 endpoints
# → <pubkey>  [2001:db8:1::10]:51820

# Трафик в туннеле
sudo tcpdump -i wg0 "ip6 and port 53"

# MTU-проблемы IPv6: проверка без фрагментации.
# Для MTU туннеля 1420 пейлоад = 1420 - 40 (IPv6) - 8 (ICMPv6) = 1372
ping -6 -M do -s 1372 fd12:3456:789a:bcde::1
# Нет reply → снижайте MTU и включайте MSS Clamping для ip6

# Счётчики PMTUD: рост Icmp6InPktTooBigs при активном трафике — норма,
# нулевой счётчик при «зависших» крупных сессиях — признак Black Hole
nstat -az | grep Icmp6InPktTooBigs

# Перехват Packet Too Big (Type 2) на внешнем интерфейсе
sudo tcpdump -i <ext-if> "icmp6[0] == 2"
```

| Симптом | Вероятная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| `ping -6` проходит, TCP-сессии зависают | PMTUD Black Hole: заблокирован ICMPv6 Type 2 | `sudo tcpdump -i <ext-if> "icmp6[0] == 2"`, `nstat -az \| grep Icmp6InPktTooBigs` | Разрешить Type 2, настроить MSS Clamping |
| Туннель поднимается, но трафик между пирами не идёт | Выключен IPv6 forwarding | `sysctl net.ipv6.conf.all.forwarding` → `0` | `sysctl -w net.ipv6.conf.all.forwarding=1` |
| `wg-quick up` сообщает об ошибке парсинга | Недопустимый ключ в конфиге (например, `IPv6 = on`) | Вывод `wg-quick up` с указанием строки | Удалить строку, полагаться на `Address`/`AllowedIPs` |
| Endpoint по hostname не меняется после смены IP | WireGuard резолвает имя один раз при старте | `wg show wg0 endpoints` vs актуальный DNS | Перезапуск интерфейса или `reresolve-dns.sh` |
| `ping -6 -M do -s 1372` не проходит | MTU туннеля больше реального пути (PPPoE, CGNAT) | `tracepath6` до Endpoint | Понизить `MTU` в конфиге (например, 1412 для PPPoE) |

## Лучшие практики

- Генерируйте Global ID ULA псевдослучайно (RFC 4193) и ведите учёт префиксов — при слиянии сетей коллизия ULA потребует переадресации.
- Держите `MTU = 1420` по всей сети как единое значение; не опускайтесь ниже 1280 (RFC 8200).
- Никогда не блокируйте ICMPv6 Type 2 на всём пути (включая hardware firewall) — это обязательный механизм PMTUD, а не опциональная диагностика.
- MSS Clamping включайте в обе стороны (SYN и SYN+ACK) на границе туннеля.
- Kill-switch для IPv6 (аналог примера из `wg-quick(8)` для IPv4) — через `PostUp`/`PreDown` с `ip6tables`, чтобы правила гарантированно снимались вместе с интерфейсом при `wg-quick down`:

  ```ini
  PostUp = ip6tables -I OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT
  PreDown = ip6tables -D OUTPUT ! -o %i -m mark ! --mark $(wg show %i fwmark) -m addrtype ! --dst-type LOCAL -j REJECT
  ```

- Откат/очистка после тестов: `sudo wg-quick down wg0` (правила из `PostUp`/`PreDown` снимаются автоматически), удаление `/etc/wireguard/wg0.conf`, `sudo nft delete table inet filter` (если правила применялись вручную), `sudo sysctl -w net.ipv6.conf.all.forwarding=0` — при необходимости вернуть исходное значение.

## Дополнительная информация

- **[Протокол IPv6](../Networking/Protocols/ipv6_overview.md)** — адресация, отличия от IPv4, переходные механизмы
- **[Dual Stack](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)** — сосуществование стеков, Happy Eyeballs
- **[Туннелирование IPv6 в Linux](../Linux/Networking/Settings/ipv6_configuration/tunneling.md)** — SIT/GRE/VXLAN, MTU-таблицы
- **[Диагностика IPv6](../Linux/Networking/Settings/ipv6_configuration/diagnostics.md)** — NDP, PMTUD, счётчики
- **[vpn-dns.md](./vpn-dns.md)** — split DNS; DNS64 для IPv6-only клиентов
