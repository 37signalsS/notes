# Remote Access VPN — сравнение технологий и выбор

## Определения

**Remote Access VPN** — технология, позволяющая удалённым пользователям (сотрудникам, подрядчикам) получить доступ к корпоративной сети через зашифрованный туннель. В отличие от Site-to-Site VPN (постоянное соединение между сетями), Remote Access подключает отдельных клиентов по требованию.

> **См. также:** [WireGuard](./wireguard_practical.md), [OpenVPN](./openvpn.md), [IPsec](./ipsec/ipsec.md), [L2TP/IPsec](./l2tp_ipsec.md)

---

## Сравнение технологий

### Общая таблица

| Параметр | WireGuard | OpenVPN | IPsec (IKEv2) | L2TP/IPsec |
|----------|-----------|---------|---------------|------------|
| **Производительность** | Очень высокая | Средняя | Высокая | Средняя |
| **Простота настройки** | Очень простая | Средняя | Сложная | Сложная |
| **NAT Traversal** | Отлично (UDP) | Отлично (TCP 443) | Хорошо (NAT-T) | Хорошо (NAT-T) |
| **Аутентификация** | Статические ключи | PKI, LDAP, RADIUS | PKI, EAP, PSK | PPP (MSCHAPv2, EAP) |
| **Split Tunneling** | Да (AllowedIPs) | Да (route) | Да (traffic selectors) | Да (PPP routes) |
| **Kill Switch** | Да (PostUp/PostDown) | Да (firewall rules) | Да (iptables) | Ограничен |
| **Роуминг** | Нативно (смена IP) | Требует переподключения | MOBIKE | Нет |
| **Клиенты ОС** | Linux, Win, macOS, iOS, Android | Все ОС (TAP/TUN) | Все ОС (нативные) | Все ОС (нативные) |
| **Overhead** | 60 байт | 57–73 байт | 50–73 байт | 57–73 байт |
| **MTU** | 1420 | 1390–1420 | 1400–1420 | 1400 |

### Когда что выбирать

| Сценарий | Рекомендация | Причина |
|----------|-------------|---------|
| **Startup / small team** | **WireGuard** | Простота, 5 минут на настройку |
| **Enterprise (LDAP/RADIUS)** | **OpenVPN** или **IPsec** | Интеграция с AD/LDAP |
| **Legacy devices** | **L2TP/IPsec** или **IPsec** | Нативная поддержка ОС |
| **Высокоскоростной канал** | **WireGuard** | Производительность ядра |
| **Обход strict firewall** | **OpenVPN TCP 443** | Маскировка под HTTPS |
| **Мобильные сотрудники** | **WireGuard** или **IKEv2** | Роуминг, быстрое переподключение |
| **PKI инфраструктура** | **IPsec** или **OpenVPN** | Сертификатная аутентификация |

---

## Практические сценарии

### WireGuard Remote Access (рекомендуется)

#### Сервер

```ini
# /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Клиент 1 (Alice)
[Peer]
PublicKey = <alice_public_key>
AllowedIPs = 10.0.0.2/32

# Клиент 2 (Bob)
[Peer]
PublicKey = <bob_public_key>
AllowedIPs = 10.0.0.3/32
```

#### Клиент (Alice)

```ini
# ~/.config/wireguard/wg0.conf
[Interface]
PrivateKey = <alice_private_key>
Address = 10.0.0.2/32
DNS = 192.168.1.53, 8.8.8.8

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

#### Добавление нового клиента

```bash
# На сервере
CLIENT_PRIVKEY=$(wg genkey)
CLIENT_PUBKEY=$(echo "$CLIENT_PRIVKEY" | wg pubkey)
sudo wg set wg0 peer "$CLIENT_PUBKEY" allowed-ips 10.0.0.4/32
sudo wg-quick save wg0

# Вывести ключи клиенту
echo "Private: $CLIENT_PRIVKEY"
echo "Public: $CLIENT_PUBKEY"
```

### OpenVPN Remote Access (для LDAP/RADIUS)

#### Сервер

```bash
# /etc/openvpn/server.conf
port 443
proto tcp
dev tun

ca   /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key  /etc/openvpn/server.key

server 10.8.0.0 255.255.255.0
push "route 192.168.1.0 255.255.255.0"
push "dhcp-option DNS 192.168.1.53"

# LDAP аутентификация
plugin /usr/lib/openvpn/plugins/openvpn-plugin-auth-pam.so openvpn
verify-client-cert none

cipher AES-256-GCM
tls-crypt /etc/openvpn/ta.key
```

#### Клиент

```ini
# client.ovpn
client
dev tun
proto tcp
remote vpn.example.com 443
resolv-retry infinite
nobind
persist-key
persist-tun
ca   ca.crt
tls-crypt ta.key
cipher AES-256-GCM
verb 3
```

### IPsec IKEv2 Remote Access (для enterprise)

#### Сервер (strongSwan)

```bash
# /etc/swanctl/conf.d/remote-access.conf
connections {
    remote-access {
        version = 2
        local_addrs = 0.0.0.0
        proposals = aes256gcm128-sha384-ecp384

        pools = remote-pool

        local {
            auth = pubkey
            certs = vpn.crt
        }
        remote {
            auth = eap-tls
            cacerts = ca.crt
            id = %any
        }

        children {
            remote-tunnel {
                esp_proposals = aes256gcm128-sha384-ecp384
                rekey_time = 3600s
            }
        }
    }
}

pools {
    remote-pool {
        addrs = 10.100.0.0/24
        dns = 192.168.1.53, 8.8.8.8
    }
}
```

### L2TP/IPsec (для legacy devices)

См. [L2TP/IPsec](./l2tp_ipsec.md)

---

## Безопасность

### Сравнение криптографии

| Компонент | WireGuard | OpenVPN | IPsec (IKEv2) | L2TP/IPsec |
|-----------|-----------|---------|---------------|------------|
| **Key Exchange** | Curve25519 | TLS 1.2/1.3 | ECP-384, X25519 | IKE (DH) |
| **Encryption** | ChaCha20-Poly1305 | AES-256-GCM | AES-256-GCM | AES-256-GCM |
| **Auth** | Poly1305 (AEAD) | HMAC-SHA256 | HMAC-SHA384 | PPP (MSCHAPv2) |
| **PFS** | Да (ephemeral keys) | Да (TLS) | Да (DH rekey) | Да (IPsec rekey) |

### Рекомендации

1. **WireGuard:** Используйте статические ключи, надёжно храните приватные ключи
2. **OpenVPN:** Включите tls-crypt, tls-version-min 1.2, cipher AES-256-GCM
3. **IPsec:** Используйте IKEv2 + EAP-TLS или сертификаты (не PSK для enterprise)
4. **L2TP/IPsec:** Избегайте MSCHAPv2, используйте EAP

---

## MTU и производительность

### Overhead таблица

| Протокол | Overhead (байт) | MTU (при physical 1500) |
|----------|-----------------|-------------------------|
| **WireGuard** | 60 | 1420 |
| **OpenVPN (UDP)** | 57–73 | 1390–1420 |
| **IPsec (ESP Tunnel)** | 50–73 | 1400–1420 |
| **L2TP/IPsec** | 57–73 | 1400 |

### MSS Clamping

```bash
# Универсальный MSS Clamping для любого VPN
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o <tunnel_interface> -j TCPMSS --clamp-mss-to-pmtu

# Жёсткая установка MSS
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o <tunnel_interface> -j TCPMSS --set-mss 1360
```

---

## Дополнительная информация

### Связанные документы

- **[WireGuard — практическое руководство](./wireguard_practical.md)** — настройка site-to-site и remote access
- **[OpenVPN](./openvpn.md)** — настройка сервера и клиента
- **[IPsec](./ipsec/ipsec.md)** — настройка IKEv2 remote access
- **[L2TP/IPsec](./l2tp_ipsec.md)** — настройка для legacy-устройств
- **[VPN Troubleshooting](./vpn_troubleshooting_universal.md)** — universальный чек-лист
- **[Firewall templates](./vpn_firewall_templates.md)** — шаблоны правил
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead
