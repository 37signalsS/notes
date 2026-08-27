# IPsec: совместимость с оборудованием (Interop)

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл описывает построение site-to-site IPsec между Linux и сетевым оборудованием других вендоров: Cisco IOS/XE, MikroTik RouterOS, pfSense/OPNsense, Juniper SRX.

---

## Определения

**Interoperability** — способность IPsec-реализации разных вендоров корректно согласовывать SA и обмениваться данными. Зависит от соблюдения RFC и совместимости алгоритмов.

**Vendor-specific extension** — проприетарные расширения протоколов, которые могут нарушать совместимость (например, Cisco VTI, MikroTik IPsec proposals).

**IKEv2 interop** — согласование IKEv2 между разными стеками (strongSwan ↔ Cisco IOS, strongSwan ↔ MikroTik). Требует точного совпадения алгоритмов и параметров.

---

## Основные концепции

### Типичные проблемы совместимости

| Проблема | Причина | Решение |
|----------|---------|---------|
| NO_PROPOSAL_CHOSEN | Разные наборы алгоритмов | Синхронизировать proposals на обеих сторонах |
| AUTHENTICATION_FAILED | Разные методы ID | Синхронизировать local_id/remote_id |
| TS_UNACCEPTABLE | Несовпадение подсетей | Синхронизировать local_ts/remote_ts |
| INVALID_SYNTAX | Различия в формате сообщений | Использовать совместимые алгоритмы |
| SA сбрасывается | Несовместимые DPD/keepalive | Синхронизировать таймеры |

### Таблица совместимости алгоритмов

| Алгоритм | strongSwan | Cisco IOS/XE | MikroTik | pfSense | Juniper SRX |
|----------|------------|-------------|----------|---------|-------------|
| AES-256-GCM | ✅ | ✅ (15.1+) | ✅ (7.x) | ✅ | ✅ |
| AES-128-GCM | ✅ | ✅ (15.1+) | ✅ (7.x) | ✅ | ✅ |
| AES-256-CBC | ✅ | ✅ | ✅ | ✅ | ✅ |
| AES-128-CBC | ✅ | ✅ | ✅ | ✅ | ✅ |
| ChaCha20-Poly1305 | ✅ | ❌ | ✅ (7.4+) | ✅ | ❌ |
| ECP-384 | ✅ | ✅ | ✅ | ✅ | ✅ |
| ECP-256 | ✅ | ✅ | ✅ | ✅ | ✅ |
| X25519 | ✅ | ✅ (16.x) | ✅ (7.7+) | ✅ | ❌ |
| MODP-2048 | ✅ | ✅ | ✅ | ✅ | ✅ |
| MODP-4096 | ✅ | ✅ | ✅ | ✅ | ✅ |
| IKEv2 | ✅ | ✅ | ✅ | ✅ | ✅ |
| IKEv1 | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Практические сценарии

### Cisco IOS/XE ↔ Linux (strongSwan)

#### Cisco IOS (IKEv2 Site-to-Site)

```cisco
! crypto map configuration
crypto isakmp policy 10
 encr aes 256
 hash sha256
 authentication pre-share
 group 20
 lifetime 86400
crypto isakmp key PSK-KEY address 198.51.100.1

crypto ipsec transform-set IPSEC-SET esp-aes 256 esp-sha256-hmac
 mode tunnel

crypto map IPSEC-MAP 10 ipsec-isakmp
 set peer 198.51.100.1
 set transform-set IPSEC-SET
 match address VPN-ACL

! ACL для интересующего трафика
ip access-list extended VPN-ACL
 permit ip 192.168.2.0 0.0.0.255 192.168.1.0 0.0.0.255

! Применение к интерфейсу
interface GigabitEthernet0/0
 crypto map IPSEC-MAP
```

#### strongSwan ↔ Cisco

```bash
# /etc/swanctl/conf.d/cisco-interop.conf
connections {
    cisco-gw {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        # Совместимые алгоритмы для Cisco
        proposals = aes256-sha256-modp2048!

        local {
            auth = psk
            id = 198.51.100.1
        }
        remote {
            auth = psk
            id = 203.0.113.2
        }

        children {
            cisco-tunnel {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256-sha256-modp2048!
                start_action = trap
            }
        }
    }
}

secrets {
    ike-cisco {
        secret = "PSK-KEY"
    }
}
```

### MikroTik RouterOS ↔ Linux

#### MikroTik (IKEv2 Site-to-Site)

```routeros
# MikroTik RouterOS 7.x

# 1. IP Pool для туннеля
/ip pool add name=ipsec-pool ranges=10.10.10.2-10.10.10.10

# 2. IPsec Profile (IKE SA)
/ip ipsec profile
add name=ipsec-profile \
    hash-algorithm=sha256 \
    enc-algorithm=aes-256 \
    dh-group=modp2048 \
    lifetime=86400 \
    nat-traversal=yes \
    dpd-interval=30s \
    dpd-maximum-failures=5

# 3. IPsec Proposal (CHILD SA)
/ip ipsec proposal
add name=ipsec-proposal \
    auth-algorithms=sha256 \
    enc-algorithms=aes-256-gcm \
    lifetime=3600 \
    pfs-group=modp2048

# 4. IPsec Peer
/ip ipsec peer
add name=strongswan-peer \
    address=198.51.100.1 \
    profile=ipsec-profile

# 5. IPsec Identity
/ip ipsec identity
add peer=strongswan-peer \
    auth-method=pre-shared-key \
    secret="PSK-KEY"

# 6. IPsec Policy
/ip ipsec policy
add src-address=192.168.2.0/24 \
    dst-address=192.168.1.0/24 \
    tunnel=yes \
    sa-src-address=203.0.113.2 \
    sa-dst-address=198.51.100.1 \
    proposal=ipsec-proposal \
    action=encrypt \
    level=require
```

#### strongSwan ↔ MikroTik

```bash
# /etc/swanctl/conf.d/mikrotik-interop.conf
connections {
    mikrotik-gw {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        # Совместимые алгоритмы для MikroTik
        proposals = aes256gcm128-sha256-modp2048!

        local {
            auth = psk
            id = 198.51.100.1
        }
        remote {
            auth = psk
            id = 203.0.113.2
        }

        children {
            mikrotik-tunnel {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-sha256-modp2048!
                start_action = trap
            }
        }
    }
}

secrets {
    ike-mikrotik {
        secret = "PSK-KEY"
    }
}
```

### pfSense/OPNsense ↔ Linux

#### pfSense (IPsec Site-to-Site)

```bash
# Web UI: VPN → IPsec → Tunnels → Add

# Phase 1 (IKE SA):
# - Key Exchange Version: IKEv2
# - Encryption Algorithm: AES-256-GCM
# - Hash Algorithm: SHA384
# - DH Group: 20 (ECP-384)
# - Lifetime: 86400
# - Auth Method: Pre-Shared Key
# - Peer Identifier: 198.51.100.1
# - Local Identifier: 203.0.113.2

# Phase 2 (CHILD SA):
# - Mode: Tunnel IPv4
# - Protocol: ESP
# - Encryption: AES-256-GCM
# - Hash: (не используется для GCM)
# - PFS Group: 20 (ECP-384)
# - Lifetime: 3600
# - Local Network: 192.168.2.0/24
# - Remote Network: 192.168.1.0/24
```

#### strongSwan ↔ pfSense

```bash
# /etc/swanctl/conf.d/pfsense-interop.conf
connections {
    pfsense-gw {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        proposals = aes256gcm128-sha384-ecp384!

        local {
            auth = psk
            id = 198.51.100.1
        }
        remote {
            auth = psk
            id = 203.0.113.2
        }

        children {
            pfsense-tunnel {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-ecp384!
                start_action = trap
            }
        }
    }
}
```

### Juniper SRX ↔ Linux

#### Juniper SRX (IKEv2 Site-to-Site)

```
# set security ike proposal IKE-PROPOSAL proposal-authentication-algorithm sha-256
# set security ike proposal IKE-PROPOSAL proposal-encryption-algorithm aes-256-gcm
# set security ike proposal IKE-PROPOSAL proposal-dh-group modp-2048

# set security ike policy IKE-POLICY proposals IKE-PROPOSAL
# set security ike policy IKE-POLICY pre-shared-key ascii-text "PSK-KEY"

# set security ike gateway GW-STRONGSWAN ike-policy IKE-POLICY
# set security ike gateway GW-STRONGSWAN address 198.51.100.1
# set security ike gateway GW-STRONGSWAN version v2-only

# set security ipsec proposal IPSEC-PROPOSAL protocol esp
# set security ipsec proposal IPSEC-PROPOSAL encryption-algorithm aes-256-gcm
# set security ipsec proposal IPSEC-PROPOSAL authentication-algorithm hmac-sha-256-128

# set security ipsec policy IPSEC-POLICY proposals IPSEC-PROPOSAL

# set security ipsec vpn VPN-1 ike gateway GW-STRONGSWAN
# set security ipsec vpn VPN-1 ike ipsec-policy IPSEC-POLICY

# set security policies from-zone trust to-zone untrust policy VPN-POLICY match source-address 192.168.2.0/24
# set security policies from-zone trust to-zone untrust policy VPN-POLICY match destination-address 192.168.1.0/24
# set security policies from-zone trust to-zone untrust policy VPN-POLICY match application any
# set security policies from-zone trust to-zone untrust policy VPN-POLICY then permit tunnel ipsec-vpn VPN-1
```

---

## Управление и диагностика

### Диагностика interop

```bash
# 1. Проверка согласования proposal
sudo swanctl --log | grep -i "proposal\|NO_PROPOSAL"
# Или
sudo tcpdump -n -i any port 500 -w interop.pcap
# → Анализ в Wireshark: IKE → SA → Payload → Transform

# 2. Проверка authenticated identity
sudo swanctl --log | grep -i "id\|identity\|AUTHENTICATION"
# → Убедиться что local_id/remote_id совпадают с peer configuration

# 3. Проверка Traffic Selectors
sudo swanctl --log | grep -i "ts\|traffic"
# → local_ts на одной стороне = remote_ts на другой

# 4. Проверка в ядре
ip xfrm state
ip xfrm policy

# 5. Проверка syslog на оборудовании
# Cisco: show crypto isakmp sa
# MikroTik: /ip ipsec active-peers print
# pfSense: Status → IPsec → Details
# Juniper: show security ike security-associations
```

### Команды на оборудовании

| Вендор | Команда | Описание |
|--------|---------|----------|
| **Cisco IOS** | `show crypto isakmp sa` | Просмотр IKE SA |
| | `show crypto ipsec sa` | Просмотр IPsec SA |
| | `clear crypto isakmp` | Сброс IKE SA |
| | `debug crypto isakmp` | Отладка IKE |
| **MikroTik** | `/ip ipsec active-peers print` | Активные пиры |
| | `/ip ipsec installed-sa print` | Установленные SA |
| | `/log print where topics~"ipsec"` | Логи IPsec |
| **pfSense** | `Status → IPsec` | Статус через Web UI |
| | `ipsec statusall` | Статус через CLI |
| **Juniper** | `show security ike security-associations` | IKE SA |
| | `show security ipsec security-associations` | IPsec SA |

---

## Типовые проблемы interop

| Проблема | Сторона | Причина | Решение |
|----------|---------|---------|---------|
| **Cisco:** Tunnel UP, no traffic | Cisco | ACL не совпадает с TS | Синхронизировать ACL и `local_ts`/`remote_ts` |
| **MikroTik:** SA建立, data fails | MikroTik | PFS не совпадает | Отключить PFS или синхронизировать `dh-group` |
| **pfSense:** Phase 2 fail | pfSense | Encryption mismatch | Использовать AES-256-GCM на обеих сторонах |
| **Juniper:** DPD timeout | Juniper | NAT-T не работает | Включить NAT-T на Juniper |
| **Все:** Flapping | Все | Lifetime mismatch | Синхронизировать `ikelifetime` и `lifetime` |

---

## Дополнительная информация

### Рекомендуемые совместимые конфигурации

Для максимальной совместимости используйте:

| Параметр | Значение |
|----------|----------|
| **IKE version** | IKEv2 |
| **Encryption** | AES-256-GCM |
| **Hash** | SHA-256 |
| **DH Group** | MODP-2048 (group 14) |
| **IKE Lifetime** | 86400 сек (24 часа) |
| **ESP Lifetime** | 3600 сек (1 час) |
| **DPD Delay** | 30 сек |
| **DPD Timeout** | 120 сек |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, настройка strongSwan.
- **[Диагностика IPsec (legacy)](./ipsec_troubleshooting.md)** — отладка KAME/racoon.
- **[Динамическая маршрутизация](./ipsec_routing.md)** — OSPF/BGP для multi-vendor сетей.
- **[Высокая доступность IPsec](./ipsec_ha.md)** — failover для multi-vendor среды.
