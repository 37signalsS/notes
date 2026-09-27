# PMTUD / MTU Probing — Практическое руководство

## Определения

**PMTUD (Path MTU Discovery)** — механизм определения максимального размера MTU на всём маршруте до удалённого хоста. Работает путём отправки пакетов с флагом DF (Don't Fragment) и получения ICMP «Fragmentation Needed» от промежуточных маршрутизаторов.

**PMTUD Black Hole** — ситуация, когда промежуточный маршрутизатор блокирует ICMP «Fragmentation Needed», а ядро отправителя не может определить правильный MTU. Пакеты тихо дропаются, соединение «висит».

**tcp_mtu_probing** — sysctl-параметр ядра Linux, управляющий PMTU probing: `0` = отключён, `1` = поиск MTU, `2` = поиск + blackhole detection.

**tcp_base_mss** — начальное значение MSS для PMTU probing. По умолчанию 1024. Используется при `tcp_mtu_probing=1` для первого探测.

**PLPMTUD (Packetization Layer PMTU Discovery)** — RFC 4821/8899, более надёжный механизм, работающий на транспортном уровне. Используется QUIC, SCTP, TCP с `tcp_mtu_probing=2`.

**MSS Clamping** — техника ограничения MSS через iptables/nftables для компенсации overhead туннелей (GRE, IPsec, VXLAN).

---

## Теоретический блок

### Алгоритм PMTUD

```
Отправитель                    Промежуточный маршрутизатор         Получатель
    │                                    │                              │
    │  Пакет (DF=1, size=1500)           │                              │
    │ ──────────────────────────────────►│                              │
    │                                    │  MTU=1400, пакет > MTU       │
    │                                    │  → ICMP Frag Needed (MTU=1400)│
    │  ICMP Frag Needed (MTU=1400)       │                              │
    │ ◄──────────────────────────────────│                              │
    │                                    │                              │
    │  Кэширую PMTU=1400                 │                              │
    │  Пакет (DF=1, size=1400)           │                              │
    │ ──────────────────────────────────►│─────────────────────────────►│
```

### PMTUD Black Hole

```
Отправитель                    Маршрутизатор (блокирует ICMP)     Получатель
    │                                    │                              │
    │  Пакет (DF=1, size=1500)           │                              │
    │ ──────────────────────────────────►│                              │
    │                                    │  ICMP blocked!               │
    │                                    │  → Тихий дроп пакета         │
    │                                    │                              │
    │  ........ таймаут, ретрансмиссия ....                            │
    │                                    │                              │
    │  Пакет (DF=1, size=1500)           │                              │
    │ ──────────────────────────────────►│  Тихий дроп снова           │
    │                                    │                              │
    │  → TCP зависает, данные не идут    │                              │
```

### Симптомы PMTUD Black Hole

- TCP handshake завершается успешно (SYN/ACK проходят, они маленькие)
- Первые маленькие данные проходят (меньше MTU промежуточного звена)
- Большие передачи зависают или идут очень медленно
- `ping` работает (ICMP, не DF)
- `tracepath` показываетMTU на промежуточном хопе
- `ss -tin` показывает растущие ретрансмиссии

### sysctl-параметры

| Параметр | Значение | Описание |
|---|---|---|
| `net.ipv4.tcp_mtu_probing` | `0` | Отключён (по умолчанию) |
| | `1` | PMTU lookup (использует `tcp_base_mss`) |
| | `2` | PMTU + blackhole detection (рекомендуется) |
| `net.ipv4.tcp_base_mss` | `1024` | Начальный MSS для probing |
| `net.ipv4.ip_no_pmtu_disc` | `0` | PMTUD включён (по умолчанию) |
| | `1` | Отключить PMTUD для UDP |
| | `2` | Отключить PMTUD для всех протоколов |

### MSS Clamping

MSS Clamping — альтернатива/дополнение PMTUD. Устанавливает максимальный MSS через netfilter:

```bash
# iptables: ограничить MSS до 1360 (для GRE overhead)
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu

# iptables: явный MSS
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --set-mss 1360

# nftables
nft add rule ip mangle forward tcp flags syn set mss clamp to pmtu
nft add rule ip mangle forward tcp flags syn set mss 1360
```

### Кэширование PMTU

```bash
# Просмотр кэша PMTU
ip tcp_metrics show
# → 10.0.0.1 cache rtt 1.234ms rttvar 0.123ms cwnd 10 ssthresh 7 pmtu 1400

# Очистка кэша
ip tcp_metrics flush
ip tcp_metrics flush 10.0.0.1

# Сброс при смене маршрута
ip tcp_metrics flush all
```

---

## Практический блок

### Проверка текущего состояния

```bash
# Проверить MTU на интерфейсе
ip link show eth0 | grep mtu
# → mtu 1500

# Tracepath для определения PMTU
tracepath 10.0.0.1
# → 1: nobody    1500.000ms ...
# → 2: 10.0.0.1  1420.000ms PMTU 1420

# Ping с DF для проверки MTU
ping -M do -s 1472 10.0.0.1
# → 1472 + 28 (IP+ICMP) = 1500 = MTU → OK
# → Frag needed and DF set → MTU < 1500

# Проверка PMTU через ss
ss -tin dst 10.0.0.1 | grep pmtu
# → pmtu:1500

# Проверка sysctl
sysctl net.ipv4.tcp_mtu_probing net.ipv4.tcp_base_mss
```

### Включение PMTU probing

```bash
# /etc/sysctl.d/99-pmtud.conf
net.ipv4.tcp_mtu_probing = 2
net.ipv4.tcp_base_mss = 1024
net.ipv4.ip_no_pmtu_disc = 0

# Применение
sudo sysctl --system
```

### Настройка для туннелей (GRE/IPsec/WireGuard)

```bash
# MSS Clamping для GRE туннеля
# GRE overhead = 24 байта → MTU = 1500 - 24 = 1476 → MSS = 1436
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --set-mss 1436

# MSS Clamping для IPsec (ESP, AES-GCM)
# IPsec overhead ~60-80 байт → MTU ≈ 1420 → MSS ≈ 1380
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o eth0 -j TCPMSS --clamp-mss-to-pmtu

# WireGuard: MSS Clamping автоматический (wg-quick)
# В whimsical: PostUp/PostDown
# PostUp = iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o wg0 -j TCPMSS --clamp-mss-to-pmtu
```

### Diagnostics

```bash
# Мониторинг ICMP Fragmentation Needed
nstat -az | grep -i frag
# → IpExtInMcastPkts (не related)

# Найти проблемы с MTU через tcpdump
tcpdump -i eth0 -n 'icmp[icmp-type] == 3 and icmp[icmp-code] == 4'
# → ICMP Destination Unreachable: Fragmentation Needed

# Проверка через eBPF
bpftrace -e 'kprobe:ip_rcv { @[net啃啃啃啃啃啃啃啃啃啃啃啃啃] = count(); }'

# Поиск мёртвых соединений из-за MTU
ss -tin state established | awk '/retrans/ { print $0 }'

# Проверка current PMTU
ip tcp_metrics show | grep -o 'pmtu [0-9]*' | sort | uniq -c
```

### Troubleshooting decision tree

```
Соединение зависает после handshake?
│
├─ Ping работает? → Да
│   ├─ tracepath показывает MTU < 1500? → Да
│   │   ├─ ICMP blocked? → Да → PMTUD Black Hole → MSS Clamping или tcp_mtu_probing=2
│   │   └─ ICMP unblocked? → Маршрутизатор не поддерживает fragmentation
│   └─ tracepath показывает MTU = 1500? → Проблема не в MTU
│
└─ Ping не работает? → Проблема не в MTU (маршрутизация, firewall)
```

### Prometheus alerting

```yaml
groups:
  - name: mtu_alerts
    rules:
      - alert: HighTCPRetransmits
        expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate ретрансмиссий — возможна MTU проблема"

      - alert: PathMTUChanged
        expr: changes(node_netstat_Tcp_CurrEstab[5m]) > 10
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "Частые переподключения — проверьте MTU"
```

---

## Дополнительная информация

### Связанные файлы

- [IP Fragmentation](../../../Networking/OSI_TCP_IP_Model/Network_layer/Protocols/ip_fragmentation.md) — SSoT по фрагментации
- [MTU and VPN](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — MTU в контексте VPN
- [GRE隧道](../../../Networking/Tunnels/gre/gre.md) — MSS Clamping для GRE
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — полная диагностика

### RFC

- **RFC 1191** — Path MTU Discovery (1990)
- **RFC 4821** — PLPMTUD (2007)
- **RFC 8899** — PLPMTUD更新 (2020)
- **RFC 1122** §3.3.3 — Fragmentation / PMTUD

### Важные замечания

1. **`tcp_mtu_probing=2` рекомендуется** для production — включает blackhole detection.
2. **MSS Clamping Required** для всех туннелей (GRE, IPsec, VXLAN) где overhead > 0.
3. **IPv6 требует PMTUD** — фрагментация запрещена на промежуточных маршрутизаторах.
4. **NAT может ломать PMTUD** — если NAT-устройство не возвращает ICMP Fragmentation Needed.
5. **Для containerized workloads** проверяйтеMTU CNI-плагина (обычно 1450 для VXLAN, 1410 для Geneve).
