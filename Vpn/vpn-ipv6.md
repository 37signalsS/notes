# IPv6 внутри VPN

## Определения

**ULA (Unique Local Address)** — диапазон `fc00::/8`, аналог RFC1918 для IPv6 (обычно используется `fd00::/8`). **Dual Stack** — одновременная работа модуля IPv4 и IPv6 на узле/сети. **NAT64/DNS64** — трансляция IPv6→IPv4 на шлюзе (пакетам IPv6-only сетей даётся доступ к IPv4-ресурсам). **SIT/6in4** — переходный механизм: инкапсуляция IPv6 в IPv4-пакеты. **SLAAC** — автоматическая конфигурация адреса IPv6 через Router Advertisement.

## Основные концепции

### Что «IPv6 в VPN» покрывает

1. **Адресация туннеля** — присвоение интерфейсу `Address = fdxx:xxxx::1/64` вместо/вместе с IPv4 (в конфиге WireGuard это обычный префикс).
2. **Транспорт по IPv6** — сам Endpoint (внешний адрес концентратора) может быть IPv6: клиент достукивается до шлюза по глобальному IPv6.
3. **IPv6-трафик клиентов** — `AllowedIPs = ::/0` для full tunnel IPv6; split tunnel добавляет только VPN-префикс.
4. **DNS** — AAAA-записи внутренних сервисов и DNS64 для IPv6-only клиентов.

### Модель адресации

| Назначение | Диапазон | Пример |
|------------|----------|--------|
| VPN-подсеть | ULA `fd00::/8` | `fd7a:115c:a1e0:ab12::/64` (конфиденциальный префикс) |
| Концентратор | один адрес интерфейса | `fd7a:115c:a1e0:ab12::1/128` |
| Клиент | /128 по пиру | `fd7a:115c:a1e0:ab12::2/128` |
| Транспорт Endpoint | глобальный IPv6 | `[2001:db8:1::10]:51820` |

ULA не маршрутизируется наружу — идеальный выбор для «внутренней» VPN-сети без конфликта с реальным IPv6 провайдера.

### Особенности по сравнению с IPv4

- Адресное пространство позволяет не думать об экономии: каждому пиру выделяется /128, подсети — /64.
- `wg-quick` и ядро работают с IPv6 нативно: в `AllowedIPs` можно указывать и `0.0.0.0/0`, и `::/0` одновременно.
- **Happy Eyeballs** на клиенте выбирает более быстрый транспорт: даже если IPv6 VPN настроен, приложения могут предпочесть IPv4 (см. [Dual Stack](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)).
- MTU: IPv6 не фрагментируется на промежуточных маршрутизаторах (PMTUD обязателен), поэтому неправильный MTU в туннеле заметнее ломает связь. Снизьте MTU и включите MSS Clamping в обе стороны (v6).

## Практические сценарии

### 1. WireGuard-туннель с IPv6-адресацией (dual-stack)

```ini
[Interface]
PrivateKey = <private_key>
Address = 10.0.0.1/24, fd7a:115c:a1e0:ab12::1/64
ListenPort = 51820
# Принимать входящие и IPv6 тоже
IPv6 = on   # по умолчанию on для wg-quick

[Peer]
PublicKey = <client_public_key>
AllowedIPs = 10.0.0.2/32, fd7a:115c:a1e0:ab12::2/128
```

Клиент:

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24, fd7a:115c:a1e0:ab12::2/64
DNS = 10.0.0.1, fd7a:115c:a1e0:ab12::1

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 10.0.0.0/24, fd7a:115c:a1e0:ab12::/64
PersistentKeepalive = 25
```

Проверка:

```bash
sudo wg show wg0 allowed-ips
# → <pubkey>  10.0.0.2/32, fd7a:115c:a1e0:ab12::2/128
ping6 fd7a:115c:a1e0:ab12::1
# → 64 bytes from fd7a:115c:a1e0:ab12::1: icmp_seq=1 time=12.3 ms
```

### 2. Endpoint концентратора по IPv6

Если у шлюза есть глобальный IPv6, Endpoint можно указать как `[2001:db8:1::10]:51820`. Клиенту по-прежнему нужен IPv4-fallback для случая, когда сеть без IPv6 (добавьте второй [`Peer`] с тем же ключом не получится — лучше DNS с записями A и AAAA, либо два отдельные конфига).

### 3. Split tunnel IPv6

```ini
# Только внутренний IPv6-префикс через туннель, глобальный IPv6 — напрямую
AllowedIPs = 10.0.0.0/24, fd7a:115c:a1e0:ab12::/64
# Не указывайте ::/0, если не хотите гнать весь IPv6 через VPN
```

### 4. Firewall IPv6 для концентратора (nftables)

```bash
# Таблица inet покрывает оба семейства
nft add rule inet filter input ct state invalid drop
nft add rule inet filter input iif "lo" accept
# Разрешить UDP 51820 по IPv6 (только известные saddr — по аналогии с IPv4)
nft add rule inet filter input udp dport 51820 ip6 saddr { fd00::/8 } accept
nft add rule inet filter input udp dport 51820 drop
# Форвардинг IPv6 из туннеля
nft add rule inet filter forward iif "wg0" accept
```

Общий hardening IPv6-стека — [Сетевая безопасность Linux](../Linux/Security/Mechanisms/Kernel/hardening.md) и разделы по IPv6 в каталоге `Linux/Networking/Settings/ipv6_configuration/`.

### 5. IPv6-only клиент и NAT64/DNS64

Когда клиент сидит в IPv6-only сети, а внутренние сервисы — только IPv4, на шлюзе поднимается NAT64/DNS64 (например, `tayga` или `jool`). Внутренний DNS (см. [vpn-dns.md](./vpn-dns.md)) отдаёт клиенту «синтезированные» AAAA из IPv4-ответов через DNS64. Полное описание механизма и альтернатив (SIT/6in4 для перехода) — [Переходные механизмы IPv6](../Linux/Networking/Settings/ipv6_configuration/concepts.md).

## Диагностика

```bash
# Маршрут через туннель по IPv6
ip -6 route get fd7a:115c:a1e0:ab12::2
# → fd7a:115c:a1e0:ab12::2 dev wg0 src fd7a:115c:a1e0:ab12::1
#   (metric 1024, pref medium)

# Трафик в туннеле
sudo tcpdump -i wg0 "ip6 and port 53"

# MTU-проблемы IPv6: проверка без фрагментации
ping6 -M do -s 1372 fd7a:115c:a1e0:ab12::1
# Нет reply → снижайте MTU и включайте MSS Clamping для ip6

# MSS Clamping для TCP over IPv6
ip6tables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

## Дополнительная информация

- **[Протокол IPv6](../Networking/Protocols/ipv6_overview.md)** — адресация, отличия от IPv4, переходные механизмы
- **[Dual Stack](../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)** — сосуществование стеков, Happy Eyeballs
- **[vpn-dns.md](./vpn-dns.md)** — split DNS; DNS64 для IPv6-only клиентов