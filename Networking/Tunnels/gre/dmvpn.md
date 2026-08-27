# DMVPN (Dynamic Multipoint VPN) — практическое руководство

## Определения

**DMVPN (Dynamic Multipoint VPN)** — архитектура VPN, разработанная Cisco, сочетающая **mGRE** (Multipoint GRE), **NHRP** (Next Hop Resolution Protocol) и **IPsec** для создания динамических site-to-site туннелей. Позволяет spoke-узлам (филиалам) автоматически устанавливать прямые туннели друг с другом (spoke-to-spoke) через hub-центр.

**Ключевые компоненты:**
- **mGRE (Multipoint GRE):** Один GRE-интерфейс терминирует множество туннелей (в отличие от point-to-point GRE)
- **NHRP:** Протокол разрешения адресов (аналог ARP для туннелей). Spoke-узлы регистрируют свои реальные IP в Hub, Hub отвечает на запросы spoke.
- **IPsec:** Шифрование трафика между узлами

> **См. также:** [GRE](./gre.md), [GRE: практические сценарии](./gre_practical_scenarios.md), [GRE vs WireGuard](./gre_vs_wireguard.md)

---

## Предварительные требования

### Версии ПО

| Компонент | Минимальная версия | Рекомендуемая |
|-----------|-------------------|---------------|
| **FRRouting (FRR)** | 7.0 | 9.1+ |
| **Ядро Linux** | 4.0 | 5.10+ |
| **IPsec (strongSwan)** | 5.7 | 6.0+ |

### Архитектура

```
                    ┌─────────────────┐
                    │   Hub (R1)      │
                    │   198.51.100.1  │
                    │   mGRE + NHRP   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
       ┌──────┴──────┐ ┌────┴────┐ ┌──────┴──────┐
       │  Spoke (R2) │ │Spoke(R3)│ │  Spoke (R4) │
       │ 203.0.113.2 │ │.113.3   │ │ 203.0.113.4 │
       │  NHRP Client│ │NHRP     │ │  NHRP Client│
       └─────────────┘ └─────────┘ └─────────────┘
```

---

## Основные концепции

### Как работает NHRP

1. **Регистрация:** Spoke-узлы отправляют NHRP Registration на Hub с указанием своих реальных (NBMA) IP и логических (tunnel) IP.
2. **Резолвинг:** Когда Spoke хочет отправить пакет другому Spoke, он запрашивает NHRP Resolution Request у Hub.
3. **Ответ:** Hub отвечает NHRP Resolution Reply с реальным IP удалённого Spoke.
4. **Direct Tunnel:** Spoke устанавливает прямой GRE-туннель к другому Spoke (minimize hub hairpinning).

### Режимы DMVPN

| Режим | Описание | Маршрутизация | Применение |
|-------|----------|---------------|------------|
| **DMVPN Phase 1** | Hub-and-spoke, все через Hub | Static/OSPF | Простые сети |
| **DMVPN Phase 2** | Spoke-to-spoke direct | EIGRP/BGP (no change) | Средние сети |
| **DMVPN Phase 3** | Spoke-to-spoke + routing | EIGRP/BGP (summary) | Large-scale |

### Сравнение DMVPN с альтернативами

| Параметр | DMVPN | WireGuard mesh | IPsec site-to-site | SD-WAN |
|----------|-------|----------------|-------------------|--------|
| **Динамические туннели** | Да (NHRP) | Ручная настройка | Ручная настройка | Да |
| **Spoke-to-spoke** | Автоматически | Нет (через hub) | Нет | Да |
| **Маршрутизация** | OSPF/BGP | Статика | Статика/OSPF | Встроенная |
| **Шифрование** | IPsec | ChaCha20 | ESP | Зависит от провайдера |
| **Масштаб** | 1000+ узлов | ~100 узлов | ~50 узлов | 10000+ |

---

## Практические сценарии

### Базовая конфигурация Hub (FRRouting)

```text
! /etc/frr/frr.conf
frr defaults traditional
hostname Hub-R1
!
interface tunnel0
 description DMVPN Hub
 ip address 10.0.0.1/24
 ip mtu 1400
 ip ospf area 0
 tunnel source eth0
 tunnel mode gre multipoint
 ip nhrp network-id 1
 ip nhrp map multicast dynamic
 ip nhrp redirect
 ip ospf network broadcast
!
router ospf
 ospf router-id 1.1.1.1
 network 10.0.0.0/24 area 0
 network 192.168.1.0/24 area 0
!
end
```

### Базовая конфигурация Spoke (FRRouting)

```text
! /etc/frr/frr.conf
frr defaults traditional
hostname Spoke-R2
!
interface tunnel0
 description DMVPN Spoke
 ip address 10.0.0.2/24
 ip mtu 1400
 ip ospf area 0
 tunnel source eth0
 tunnel mode gre multipoint
 ip nhrp network-id 1
 ip nhrp nhs 10.0.0.1
 ip nhrp map 10.0.0.1 198.51.100.1
 ip nhrp map multicast 198.51.100.1
 ip nhrp shortcut
 ip ospf network broadcast
!
router ospf
 ospf router-id 2.2.2.2
 network 10.0.0.0/24 area 0
 network 192.168.2.0/24 area 0
!
end
```

### IPsec шифрование (strongSwan)

```bash
# /etc/swanctl/conf.d/dmvpn.conf
connections {
    dmvpn {
        version = 2
        local_addrs = 198.51.100.1
        proposals = aes256-sha256-modp2048

        local {
            auth = psk
        }
        remote {
            auth = psk
            id = %any
        }

        children {
            esp {
                esp_proposals = aes256-sha256
                start_action = trap
            }
        }
    }
}

secrets {
    ike-dmvpn {
        secret = "DMVPN_Secret!"
    }
}
```

### Firewall

```bash
# nftables: разрешить DMVPN трафик
# GRE (IP protocol 47)
nft add rule inet filter input ip protocol 47 accept

# NHRP (UDP 544 для FRR)
nft add rule inet filter input udp dport 544 accept

# OSPF (IP protocol 89)
nft add rule inet filter input ip protocol 89 accept

# IPsec
nft add rule inet filter input ip protocol esp accept
nft add rule inet filter input udp dport 500 accept
nft add rule inet filter input udp dport 4500 accept
```

---

## Диагностика

```bash
# Просмотр NHRP (FRR)
vtysh -c "show ip nhrp"
# → 10.0.0.2/32 via 10.0.0.2, NBMA addr 203.0.113.2
# →   Flags: router tunnel static
# →   Expiry: —

# Просмотр NHRP brief
vtysh -c "show ip nhrp brief"
# → Type     Protocol  Via      NBMA           Flags
# → register 10.0.0.2/32 direct 203.0.113.2   /router

# Просмотр OSPF neighbors
vtysh -c "show ip ospf neighbor"
# → Neighbor ID     Pri State           Dead Time Address         Interface
# → 2.2.2.2           1 Full/DR         37.176s  10.0.0.2        tunnel0

# Просмотр GRE tunnel
ip -d link show tunnel0
# → gre remote any local ... ttl inherit pmtudisc ...
# →     nhrp network-id 1 ...

# Просмотр DMVPN tunnels
vtysh -c "show tunnel interface tunnel0"
```

---

## Типичные ошибки

| Симптом | Вероятная причина | Решение |
|---------|-------------------|---------|
| **Spoke не регистрируется на Hub** | NHRP network-id не совпадает | Проверить `ip nhrp network-id` на обоих узлах |
| **OSPF neighbor не formed** | MTU не уменьшен | Установить `ip mtu 1400` на tunnel0 |
| **Spoke-to-spoke не работает** | `ip nhrp redirect` не включен на Hub | Добавить `ip nhrp redirect` на Hub |
| **NHRP mapping stale** | Таймаут NHRP | Проверить `show ip nhrp` для stale entries |
| **GRE blocked by firewall** | Firewall блокирует IP 47 | Разрешить GRE (protocol 47) |

---

## Лучшие практики

1. **MTU:** Установить `ip mtu 1400` на всех DMVPN-интерфейсах для избежания фрагментации.

2. **Keepalive:** Использовать OSPF/BGP dead-timers для обнаружения отказов (а не keepalive GRE).

3. **BFD:** Для быстрого обнаружения отказов (<1 сек) настроить BFD через FRRouting:
   ```bash
   vtysh -c "conf t" -c "interface tunnel0" -c "bfd profile fast"
   ```

4. **IPsec:** Всегда включать IPsec для шифрования DMVPN-трафика.

5. **Масштабирование:** Использовать OSPF network type broadcast или NBMA для уменьшения количества LSA.

---

## Граничные случаи и ограничения

1. **NAT:** DMVPN (mGRE) требует NAT-T для IPsec. При использовании только GRE (без IPsec) NAT не поддерживается.

2. **Производительность:** DMVPN использует CPU для инкапсуляции GRE и обработки NHRP. Для каналов >10 Gbps рекомендуется аппаратная реализация.

3. **Зависимость от Cisco:** Основная реализация — Cisco IOS. Linux (FRR) поддерживает базовый DMVPN, но не все расширения.

4. **Сложность настройки:** DMVPN требует настройки GRE + NHRP + OSPF/BGP + IPsec. WireGuard проще для простых топологий.

5. **Замена:** SD-WAN решения (Cisco Viptela, VMware VeloCloud) постепенно вытесняют DMVPN в enterprise средах.

---

## Дополнительная информация

### Связанные документы

- **[GRE](./gre.md) — протокол GRE (базовый)**
- **[GRE: практические сценарии](./gre_practical_scenarios.md) — NHRP и DMVPN-примеры**
- **[GRE vs WireGuard](./gre_vs_wireguard.md) — сравнение протоколов**
- **[IPsec](../ipsec/ipsec.md) — шифрование для DMVPN**
- **[BFD через FRRouting](./gre_practical_scenarios.md#bfd-обнаружение-отказов-за-1-секунду) — быстрое обнаружение отказов**
