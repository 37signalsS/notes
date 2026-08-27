# NAT и VPN

## Определения

**NAT и VPN** — два механизма, которые часто взаимодействия друг с другом в продакшен-инфраструктурах. VPN-туннели (IPsec, WireGuard, OpenVPN) инкапсулируют трафик, что создаёт проблемы для NAT-устройств, работающих с заголовками L3/L4.

**Основная проблема:** NAT модифицирует заголовки пакетов (IP-адреса, порты), но VPN-туннели либо инкапсулируют оригинальный пакет целиком (IPsec ESP), либо используют UDP для передачи (WireGuard, OpenVPN), что затрудняет трансляцию.

## Теоретический блок

### Проблемы VPN через NAT

| Протокол | Инкапсуляция | Проблема с NAT | Решение |
| :--- | :--- | :--- | :--- |
| **IPsec (ESP)** | IP-протокол 50 (без портов) | PAT не работает — нет портов для трансляции | NAT-Traversal: инкапсуляция ESP в UDP/4500 |
| **IPsec (AH)** | IP-протокол 51 | AH защищает IP-заголовок → NAT ломает checksum | AH несовместим с NAT; использовать ESP |
| **OpenVPN** | UDP/1194 или TCP/443 | Работает через NAT (UDP/TCP есть порты) | Клиентский IP теряется; `push "redirect-gateway"` |
| **WireGuard** | UDP/51820 | Работает через NAT (UDP есть порты) | Endpoint tracking; `PersistentKeepalive=25` |
| **L2TP/IPsec** | UDP/500 + UDP/4500 | Двойная инкапсуляция; проблемы с MTU | NAT-T + увеличение MTU на 100+ байт |

### IPsec NAT-Traversal (NAT-T)

IPsec ESP (Encapsulating Security Payload) использует IP-протокол 50 — это «голый» протокол без портов TCP/UDP. PAT-шлюз не может транслировать ESP-пакеты, так как нечего подменять в поле порта.

**NAT-T решение:** Инкапсуляция ESP в UDP/4500. При обнаружении NAT (через IKE NAT-D payloads) IPsec-стек автоматически переключается на UDP/4500.

```
Без NAT-T:
[IP src=A dst=B][ESP (proto 50)][Encrypted Data]

С NAT-T:
[IP src=NAT_IP dst=B][UDP/4500][ESP][Encrypted Data]
                      ↑ NAT может транслировать UDP-порты
```

**Как обнаруживается NAT:**
1. During IKE Phase 1 (Main Mode) отправляются NAT-D payloads (хеш от IP:Port).
2. Если NAT присутствует, хеш не совпадает (IP/Port были изменены NAT'ом).
3. IKE переключается на Aggressive Mode и инициирует NAT-T (UDP/4500).

### WireGuard за NAT

WireGuard работает через UDP, поэтому NAT не является проблемой для базовой连通ности. Однако есть нюансы:

| Проблема | Описание | Решение |
| :--- | :--- | :--- |
| **Endpoint tracking** | NAT-шлюз удаляет запись conntrack через таймаут (обычно 30 сек) | `PersistentKeepalive=25` — keepalive каждые 25 сек |
| **Double NAT** | Два уровня NAT → задержки handshake | Использовать STUN для определения внешнего IP |
| **Roaming** | Смена IP-адреса (Wi-Fi → LTE) → сессия падает | WireGuard поддерживает roaming, но peer должен обновить endpoint |
| **CGNAT** | Провайдерский NAT блокирует UDP-туннели | Использовать TCP fallback или obfsproxy |

### OpenVPN за NAT

OpenVPN работает через UDP или TCP, поэтому проходит через NAT без проблем. Основные сценарии:

| Режим | Описание | NAT-проблема |
| :--- | :--- | :--- |
| **NAT (по умолчанию)** | Сервер SNAT-ит трафик клиентов | Клиентский IP теряется для других клиентов |
| **Topology subnet** | Все клиенты в одной подсети | Сервер видит реальный IP клиента через `ifconfig-pool` |
| **redirect-gateway** | Весь трафик клиента через VPN | Клиентский IP не важен — всё через VPN-шлюз |

## Практический блок

### IPsec NAT-T (strongSwan)

```bash
# /etc/ipsec.conf (strongSwan)
conn my-vpn
    left=203.0.113.1          # Публичный IP шлюза
    leftsubnet=0.0.0.0/0
    right=%any               # Любой клиент
    rightsourceip=10.0.0.0/24
    # NAT-T включается автоматически при обнаружении NAT
    # Принудительное включение:
    force_keepalive=yes
    keepalive=25s

# Проверка NAT-T
ipsec statusall
# → NAT-T should be enabled if NAT is detected
```

### WireGuard за NAT

```bash
# Конфигурация сервера (/etc/wireguard/wg0.conf)
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <server_private_key>

[Peer]
PublicKey = <client_public_key>
AllowedIPs = 10.0.0.2/32

# Конфигурация клиента (за NAT)
[Interface]
Address = 10.0.0.2/24
PrivateKey = <client_private_key>

[Peer]
PublicKey = <server_public_key>
Endpoint = 203.0.113.1:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25    # ← КРИТИЧНО за NAT
```

**Проверка:**
```bash
# На сервере: проверить, что клиент подключился
sudo wg show
# → peer: <client_public_key>
#   endpoint: 100.64.0.5:12345    ← Адрес CGNAT-шлюза клиента
#   allowed ips: 10.0.0.2/32
#   latest handshake: 25 seconds ago  ← PersistentKeepalive работает

# Проверка conntrack
conntrack -L -p udp --dport 51820
# → Должна показать активную запись для UDP/51820
```

### OpenVPN за NAT

```bash
# Сервер: /etc/openvpn/server.conf
port 1194
proto udp
dev tun
server 10.8.0.0 255.255.255.0
# push "redirect-gateway def1 bypass-dhcp"  ← Весь трафик через VPN
push "dhcp-option DNS 8.8.8.8"

# Клиент: /etc/openvpn/client.conf
client
dev tun
proto udp
remote 203.0.113.1 1194
resolv-retry infinite
nobind

# Проверка: клиентский IP в логах
journalctl -u openvpn | grep "peer"
# → Peer Connection Initiated with ...
```

### Диагностика VPN через NAT

```bash
# 1. Проверить, что VPN-туннель работает
ping 10.0.0.1    # (от клиента к серверу VPN)

# 2. Проверить conntrack для VPN
conntrack -L -p udp --dport 51820
# → Должна быть активная запись

# 3. Проверить NAT-трансляцию
conntrack -L -s 100.64.0.5
# → Должна показать SNAT: 100.64.0.5 → 203.0.113.1

# 4. Проверить MTU (VPN добавляет заголовки)
ping -M do -s 1400 -c 2 10.0.0.1
# → Если не проходит — уменьшить MTU на интерфейсе VPN

# 5. Проверить, что persistent keepalive работает
sudo wg show | grep "latest handshake"
# → latest handshake: X seconds ago (не более 30 сек)
```

## Дополнительная информация

- **[Теория NAT](./overview.md)** — концепции NAT, conntrack, CGNAT.
- **[IPsec: диагностика](../../../Networking/Tunnels/ipsec/ipsec_troubleshooting.md)** — диагностика IPsec-туннелей.
- **[WireGuard](../../../Vpn/wireguard.md)** — настройка WireGuard.
- **[Практические сценарии NAT](./practical_scenarios.md)** — DNAT, Hairpin NAT, диагностика.
