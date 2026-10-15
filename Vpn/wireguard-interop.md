# WireGuard: совместимость с сетевым оборудованием (MikroTik, pfSense, OPNsense)

**Актуально для:** MikroTik RouterOS 7.1+ (peer-поля `client-*` для QR — 7.15+/7.21+) / pfSense Plus & CE (пакет WireGuard) / OPNsense (плагин os-wireguard)

## Определения

**Site-to-site WireGuard** — туннель между двумя шлюзами (маршрутизаторами/файрволами), соединяющий LAN-подсети филиалов; конечные хосты VPN-клиентами не являются.

**Peer (RouterOS)** — запись `/interface/wireguard/peers`, сопоставляющая публичный ключ удалённого узла с фильтром `allowed-address` (какие IP разрешено получать/куда отправлять).

**Tunnel / Instance (pfSense / OPNsense)** — локальный VPN-интерфейс со своей парой ключей и адресом; **Peer** — запись о той стороне туннеля (аналог `[Peer]` в `wg0.conf`).

**AllowedIPs = cryptokey routing** — на всех платформах одновременно: (1) фильтр входящих источников и назначений для пира; (2) то, куда платформа направляет трафик. На RouterOS диапазоны `allowed-address` не должны пересекаться между пирами одного интерфейса, а туннельный IP пира обязан лежать в подсети адреса самого интерфейса.

**Responder** — роль «только отвечающего» (серверная сторона): RouterOS-свойство `responder=yes` у пира; на pfSense/OPNsense аналогично достигается отсутствием endpoint у пира либо статической конфигурацией. Без responder обе стороны будут инициировать рукопожатия — это допустимо, но при NAT инициатором должна быть сторона, доступная извне.

## Основные концепции

Протокол один и тот же (`wireguard` в ядре Linux у pfSense/OPNsense — FreeBSD-порт `wireguard-go`/интеграция, у RouterOS — встроенная реализация), различаются только оболочка и именование:

| Платформа | Интерфейс | Пир | Где ключи | Маршруты из AllowedIPs |
|---|---|---|---|---|
| Linux (`wg-quick`) | `wg0` в `/etc/wireguard/` | `[Peer]` в conf | конфиг-файлы | `wg-quick` добавляет сам (таблица auto) |
| MikroTik RouterOS 7 | `/interface/wireguard` | `/interface/wireguard/peers` | в базе RouterOS | проверьте `/ip route`; при отсутствии — статический маршрут `gateway=<wg-iface>` |
| pfSense | Tunnels (GUI) | Peers (GUI) | config.xml (есть «Hide Secrets» — только UI) | через назначенный интерфейс и правила; маршруты WAN/шлюзов — System → Routing |
| OPNsense | Instances (GUI) | Peers (GUI) | конфиг плагина | опциональное назначение интерфейса + правила |

Общие правила, одинаковые для всех сторон:

- **UDP-достижимость** порта listen-порта до инициатора; за NAT — `PersistentKeepalive` со стороны за NAT и endpoint у инициатора ([NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md)).
- **MTU по умолчанию 1420** на RouterOS и в `wg-quick`; pfSense/OPNsense задаётся при назначении интерфейса (типично 1420).
- **В `allowed-address`/`AllowedIPs` пира** входят: туннельный IP соседа `/32` **и** все LAN-подсети, до которых идёт туннель. Отсутствие LAN-подсети — частая причина «handshake есть, внутренние хосты не пингуются».
- **Нативный IPsec предпочтительнее**, если на той стороне Cisco/Juniper без поддержки WireGuard или нужен IKEv2+EAP для мобильных клиентов — [IPsec Interop](../Networking/Tunnels/ipsec/ipsec_interoperability.md), [сравнение протоколов](../Networking/Tunnels/ipsec/ipsec.md).

## Практические сценарии

### 1. Linux ↔ MikroTik RouterOS 7 (site-to-site)

Топология: HQ-Linux `203.0.113.10`, LAN `192.168.1.0/24`, туннель `10.100.0.1/24`, порт 51820. Филиал MikroTik `198.51.100.1`, LAN `10.10.0.0/24`, туннель `10.100.0.2/24`, порт 13231 (дефолт RouterOS).

**Linux (HQ):**

```bash
# Ключи
sudo wg genkey | sudo tee /etc/wireguard/private.key | wg pubkey | sudo tee /etc/wireguard/public.key
# → <linux_pub>
```

```ini
# /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <linux_priv>
Address = 10.100.0.1/24
ListenPort = 51820
PostUp = sysctl -w net.ipv4.ip_forward=1
PostUp = iptables -A FORWARD -i wg0 -s 192.168.1.0/24 -d 10.10.0.0/24 -j ACCEPT
PostUp = iptables -A FORWARD -i wg0 -s 10.10.0.0/24 -d 192.168.1.0/24 -j ACCEPT
PostDown = iptables -D FORWARD -i wg0 -s 192.168.1.0/24 -d 10.10.0.0/24 -j ACCEPT
PostDown = iptables -D FORWARD -i wg0 -s 10.10.0.0/24 -d 192.168.1.0/24 -j ACCEPT

[Peer]
# MikroTik филиала
PublicKey = <mikrotik_pub>
AllowedIPs = 10.100.0.2/32, 10.10.0.0/24
Endpoint = 198.51.100.1:13231
```

```bash
sudo wg-quick up wg0
```

**MikroTik (филиал):**

```routeros
# 1. Интерфейс: private-key создастся автоматически; public-key появится после add
/interface/wireguard add listen-port=13231 mtu=1420 name=wg-site1 comment="HQ-Linux"

# 2. Туннельный адрес
/ip address add address=10.100.0.2/24 interface=wg-site1

# 3. Пир: HQ-Linux инициирует, поэтому responder=yes
/interface/wireguard/peers add interface=wg-site1 name=hq-linux responder=yes \
    public-key="<linux_pub>" \
    allowed-address=10.100.0.1/32,192.168.1.0/24 \
    endpoint-address=203.0.113.10 endpoint-port=51820

# 4. Публичный ключ MikroTik для конфига Linux:
/interface/wireguard print detail where name=wg-site1
# → public-key: "<mikrotik_pub>"

# 5. Firewall: пропускать UDP 13231 и транзит между LAN (до правил drop!)
/ip firewall filter add chain=input protocol=udp dst-port=13231 action=accept \
    comment="WireGuard HQ"
/ip firewall filter add chain=forward src-address=192.168.1.0/24 \
    dst-address=10.10.0.0/24 action=accept comment="HQ->branch"
/ip firewall filter add chain=forward src-address=10.10.0.0/24 \
    dst-address=192.168.1.0/24 action=accept comment="branch->HQ"

# 6. Маршрут до LAN HQ: проверить и при необходимости добавить
/ip route print detail where gateway=wg-site1
/ip route add dst-address=192.168.1.0/24 gateway=wg-site1 comment="LAN HQ via WG"
```

**Проверка:**

```bash
# Linux
sudo wg show wg0
# → latest handshake: 4 seconds ago
# → transfer: 1.2 KiB received, 948 B sent

ping -c1 10.100.0.2          # туннельный IP MikroTik
ping -c1 10.10.0.1           # LAN-хост за MikroTik
```

```routeros
# MikroTik
/interface/wireguard/peers/print detail where name=hq-linux
# → last-handshake: 00:00:05
# → current-endpoint-address: 203.0.113.10
ping 10.100.0.1
```

**Клиенты филиала с телефона (QR):** RouterOS умеет генерировать клиентский конфиг и QR — поля `client-address`, `client-dns`, `client-endpoint`, `client-allowed-address` (AllowedIPs клиентской части настраиваются с 7.21) у пира, далее `show-client-config`. Для раздачи флота серверным Linux удобнее генераторы из [wireguard-key-management.md](./wireguard-key-management.md).

### 2. Linux ↔ pfSense (site-to-site)

Топология та же; pfSense — филиал: WAN `198.51.100.1`, туннель `10.100.0.2/24`, LAN `10.10.0.0/24`.

1. **Установка пакета:** System → Package Manager → Available Packages → **wireguard** → Install.
2. **Включение:** VPN → WireGuard → Settings → **Enable** → Save.
3. **Tunnel:** VPN → WireGuard → Tunnels → Add:
   - Enabled: Checked; Description: `HQ-Linux`; Listen Port: `51820`;
   - Interface Keys: **Generate** (скопируйте публичный ключ — он уйдёт в Linux-конфиг);
   - Interface Addresses: `10.100.0.2/24` → Save.
4. **Peer:** в том же Tunnel → Add Peer:
   - Public Key: `<linux_pub>`;
   - Allowed IPs: `10.100.0.1/32, 192.168.1.0/24`;
   - Endpoint: `203.0.113.10`, Endpoint Port: `51820` (если endpoint пуст — pfSense ждёт входящих, для инициации с Linux заполните);
   - Save.
5. **Назначение интерфейса:** Interfaces → Assignments → добавьте wg-туннель как OPTx, включите интерфейс.
6. **Критично — шлюз по умолчанию:** System → Routing → Default Gateway IPv4 укажите **явно** (например, WANGW), не `Automatic` — иначе firewall может выбрать WireGuard в качестве default gateway.
7. **Правила:** Firewall → Rules → WAN: `UDP` к порту 51820 `pass`; Firewall → Rules → OPTx (назначенный WG-интерфейс): `pass` для `10.100.0.0/24` ↔ `192.168.1.0/24`/`10.10.0.0/24`. Правила на **назначенном** интерфейсе получают reply-to (трафик выйдет туда же, откуда пришёл) — используйте их, а не только группу Tunnels.
8. **Hostname-эндпоинты:** интервал резолва задаётся в Settings → **Endpoint Hostname Resolve Interval** (по умолчанию 300 с).

На стороне Linux конфиг аналогичен сценарию 1 (Endpoint `198.51.100.1:51820`, AllowedIPs `10.100.0.2/32, 10.10.0.0/24`).

### 3. Linux ↔ OPNsense (site-to-site)

1. **Плагин:** System → Firmware → Plugins → `os-wireguard` → Install (в свежих версиях OPNsense WireGuard входит в основную систему — если пункта VPN → WireGuard нет, ставьте плагин).
2. **Instance:** VPN → WireGuard → Instances → +:
   - Enabled: Checked; Name: `hq`; Listen Port: `51820`;
   - Tunnel Address: `10.100.0.2/24` (не /32 — подсеть туннеля);
   - поле DNS Server (advanced mode) оставьте **пустым**, иначе WireGuard перезапишет DNS-конфигурацию OPNsense → Save.
3. **Peer:** VPN → WireGuard → Peers → +:
   - Public Key: `<linux_pub>`;
   - Allowed IPs: `10.100.0.1/32, 192.168.1.0/24`;
   - Endpoint Address: `203.0.113.10`, Endpoint Port: `51820`;
   - Instances: `hq` → Save → **Apply**.
4. **Интерфейс (рекомендуется):** Interfaces → Assignments → назначьте wg0 → включите интерфейс. Назначение создаёт alias подсети туннеля для правил и позволяет разводить правила по инстансам.
5. **Правила:** WAN — pass UDP 51820; назначенный wg-интерфейс — pass трафик туннеля и LAN (`10.100.0.0/24` ↔ `10.10.0.0/24`, `192.168.1.0/24`).

Два OPNsense между собой описаны в официальном how-to [WireGuard Site-to-Site](https://docs.opnsense.org/manual/how-tos/wireguard-s2s.html) (transfer-подсеть `10.2.2.0/24` в их примере); модель пиров та же.

### 4. Один концентратор, несколько филиалов на оборудовании

Схема «звезда»: Linux-шлюз — центр, каждый филиал (MikroTik/pfSense/OPNsense) — отдельный пир с уникальным `/32` туннельного адреса и своими LAN в `allowed-address`. Динамическая маршрутизация (BGP/OSPF поверх WG) на стороне Linux раскрыта в [wireguard-routing.md](./wireguard-routing.md); на RouterOS BGP/FRR нет — филиалы получают статические маршруты или используют Policy Routing.

### 5. Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| Нет handshake | Не совпали публичные ключи; firewall блокирует UDP | `wg show` / `/interface/wireguard/peers/print detail` — last-handshake пуст | Сверить ключи; открыть UDP-порт на WAN |
| Handshake есть, LAN не пингуются | В `allowed-address`/`AllowedIPs` нет удалённой LAN; нет forward-правил; `ip_forward`/forwarding выключен | `wg show allowed-ips`; `ip route`; цепочки forward | Добавить подсеть пира; разрешить forward |
| RouterOS: «Unable to add peer» | Пересечение `allowed-address` между пирами одного интерфейса | `/interface/wireguard/peers print` | Сузить диапазоны, каждый пир — свой `/32` |
| pfSense: трафик уходит не в туннель, а на WAN | Default Gateway = Automatic, WG-интерфейс выбран как шлюз | System → Routing | Явный IPv4/IPv6-шлюз WAN |
| pfSense/OPNsense: односторонний трафик | Правила только на группе Tunnels, нет reply-to | Правила на WAN и на назначенном интерфейсе | Перенести правила на назначенный интерфейс |
| Туннель поднят, крупные пакеты висят | MTU | `ping -M do -s 1400 <tunnel-ip>` | MTU 1420/1400 на обеих сторонах; MSS Clamping |
| За NAT на стороне филиала нет handshake | Нет endpoint/keepalive у инициатора | `current-endpoint-address` пуст | `persistent-keepalive=25s` у пира инициатора, endpoint NAT-стороны |

## Дополнительная информация

- **[WireGuard](./wireguard.md)** — базовый документ: протокол, конфиг Linux, MTU
- **[WireGuard — расширенная маршрутизация](./wireguard-routing.md)** — fwmark, BGP/OSPF поверх туннеля
- **[WireGuard — высокая доступность](./wireguard-ha.md)** — VIP/Anycast для центрального шлюза
- **[NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md)** — работа за NAT, PersistentKeepalive, CGNAT
- **[IPsec: совместимость с оборудованием](../Networking/Tunnels/ipsec/ipsec_interoperability.md)** — когда оборудование требует IPsec (Cisco/Juniper)
- **[IPsec — когда что выбирать](../Networking/Tunnels/ipsec/ipsec.md)** — сравнение WireGuard vs IPsec vs OpenVPN
- Документация: [MikroTik WireGuard](https://manual.mikrotik.com/docs/virtual-private-networks/wireguard), [pfSense WireGuard](https://docs.netgate.com/pfsense/en/latest/vpn/wireguard/index.html), [OPNsense WireGuard how-tos](https://docs.opnsense.org/manual/how-tos/wireguard-client.html)
