# VPN Troubleshooting — универсальный чек-лист

## Определения

**VPN Troubleshooting** — систематический подход к диагностика и устранению проблем с VPN-туннелями. Данный документ представляет universальный чек-лист, применимый к любому VPN-протоколу (WireGuard, IPsec, OpenVPN, GRE, L2TP/IPsec).

> **См. также:** [WireGuard Troubleshooting](./wireguard_practical.md#типичные-ошибки-и-их-устранение), [IPsec Troubleshooting](./ipsec/ipsec_troubleshooting.md), [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)

---

## Универсальный чек-лист (по шагам)

### Шаг 1: Проверка сетевой связности (Underlay)

```bash
# Пинг удалённого IP (внешний IP туннельного эндпоинта)
ping -c 3 <remote_public_ip>

# Трассировка маршрута
traceroute <remote_public_ip>

# Проверка DNS (если используется hostname)
dig +short vpn.example.com
nslookup vpn.example.com
```

**Если пинг НЕ работает:**
- Проблема в маршрутизации (не VPN)
- Firewall блокирует ICMP
- Проблема с провайдером

### Шаг 2: Проверка firewall (iptables/nftables)

```bash
# Просмотр правил INPUT
sudo iptables -L INPUT -v -n | head -20
# или
sudo nft list ruleset | head -40

# Проверка конкретных портов для VPN-протокола:

# WireGuard: UDP 51820
sudo ss -ulnp | grep 51820

# IPsec: UDP 500, UDP 4500, ESP (proto 50)
sudo ss -ulnp | grep -E "500|4500"
sudo iptables -L INPUT -v -n | grep "proto 50"

# OpenVPN: UDP 1194 или TCP 443
sudo ss -ulnp | grep 1194
sudo ss -tlnp | grep 443

# L2TP: UDP 1701
sudo ss -ulnp | grep 1701

# GRE: IP protocol 47
sudo iptables -L INPUT -v -n | grep "47"
```

**Если порт не слушает:**
- VPN-сервис не запущен
- Сервис слушает другой порт
- Сервис привязан к другому интерфейсу

### Шаг 3: Проверка состояния VPN-интерфейса

```bash
# Просмотр всех интерфейсов
ip -br addr show

# Просмотр конкретного туннельного интерфейса
ip addr show <tunnel_interface>  # wg0, tun0, gre0, eth0.100

# Проверка MTU (критически важно!)
ip link show <tunnel_interface> | grep mtu
# → mtu 1420  (WireGuard)
# → mtu 1476  (GRE)
# → mtu 1500  (OpenVPN tun0 — проблема!)

# Просмотр статистики ошибок
ip -s link show <tunnel_interface>
# → RX: bytes=... packets=... errors=... dropped=...
# → TX: bytes=... packets=... errors=... dropped=...
```

**Если интерфейс DOWN:**
- VPN не запущен или упал
- Нет прав на создание интерфейса
- Конфликт имен

### Шаг 4: Проверка таблицы маршрутизации

```bash
# Просмотр маршрутов через туннель
ip route show dev <tunnel_interface>

# Проверка маршрута до конкретного IP
ip route get <remote_tunnel_IP>
# → <remote> dev <tunnel> src <local_IP> uid 0

# Просмотр всех маршрутов
ip route show

# Проверка policy routing (если используется)
ip rule list
```

**Если маршрут отсутствует:**
- VPN не добавил route
- AllowedIPs (WireGuard) не включают нужную подсеть
- Динамическая маршрутизация (OSPF/BGP) не сформировала маршрут

### Шаг 5: Проверка MTU и MSS

```bash
# Проверка Path MTU (DF bit)
ping -M do -s 1392 -c 3 <remote_tunnel_IP>
# Формула: payload + 28 (IP+ICMP) + overhead VPN <= физ_MTU

# Проверка MSS в активных TCP-соединениях
ss -ti | grep mss
# → mss 1360  (норма для VPN)
# → mss 1460  (проблема — MTU не уменьшен)

# Tracepath для определения MTU
tracepath <remote_tunnel_IP>
```

**Если MTU слишком велик:**
- Фрагментация или blackhole
- Установить MSS Clamping:
  ```bash
  sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
      -o <tunnel_interface> -j TCPMSS --clamp-mss-to-pmtu
  ```

### Шаг 6: Проверка handshakes и состояния туннеля

```bash
# WireGuard: проверка handshakes
sudo wg show <interface> latest-handshakes
# → <pubkey>    1234567890  (timestamp)
# Если handshakes нет — проблема с сетью или ключами

# IPsec: проверка SA
sudo swanctl --list-sas
# → connection: #1, ESTABLISHED, IKEv2, ...
# Если нет ESTABLISHED — проблема с аутентификацией

# IPsec: проверка в ядре
sudo ip xfrm state
sudo ip xfrm policy

# OpenVPN: проверка логов
sudo journalctl -u openvpn@server -n 50
# → TLS Error, AUTH_FAILED, etc.

# GRE: проверка keepalive
ip -d link show <gre_interface>
```

### Шаг 7: Проверка firewall для туннельного трафика

```bash
# Просмотр правил FORWARD
sudo iptables -L FORWARD -v -n

# Проверка NAT (MASQUERADE)
sudo iptables -t nat -L POSTROUTING -v -n

# Проверка conntrack для VPN-сессий
conntrack -L -p <protocol> --dport <port> 2>/dev/null

# Проверка dropped пакетов
sudo iptables -L FORWARD -v -n | grep DROP
sudo nft list ruleset | grep drop
```

---

## Типичные симптомы и решения

### Пинг работает, но TCP зависает

| Вероятная причина | Диагностика | Решение |
|-------------------|-------------|---------|
| **MTU слишком велик** | `ping -M do -s 1392 <ip>` — fail | Уменьшить MTU, MSS Clamping |
| **Firewall блокирует TCP** | `tcpdump -ni <iface> port 443` | Добавить правило для TCP |
| **Conntrack overflow** | `dmesg \| grep conntrack` | Увеличить `nf_conntrack_max` |

### VPN подключается, но нет доступа в интернет

| Вероятная причина | Диагностика | Решение |
|-------------------|-------------|---------|
| **IP-форвардинг отключен** | `sysctl net.ipv4.ip_forward` | `sysctl -w net.ipv4.ip_forward=1` |
| **Нет MASQUERADE** | `iptables -t nat -L -v -n` | Добавить `iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE` |
| **DNS не работает** | `resolvectl status` или `cat /etc/resolv.conf` | Настроить DNS в VPN-конфиге |
| **Split tunneling** | `ip route show` | Проверить AllowedIPs / push routes |

### VPN падает каждые N минут

| Вероятная причина | Диагностика | Решение |
|-------------------|-------------|---------|
| **NAT conntrack timeout** | `conntrack -L \| grep <vpn_port>` | Увеличить timeout: `sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=180` |
| **Keepalive не настроен** | Проверить конфиг VPN | Добавить `PersistentKeepalive=25` (WireGuard) или `keepalive 10 120` (OpenVPN) |
| **DPD срабатывает** | Логи IPsec: `Dying peer detected` | Увеличить `dpd_delay`/`dpd_timeout` |
| **Network flapping** | `ping <gateway>` в цикле | Проверить стабильность физической сети |

### Медленная скорость через VPN

| Вероятная причина | Диагностика | Решение |
|-------------------|-------------|---------|
| **MTU оптимизация** | `iperf3 -c <server>` | Увеличить MTU до максимума (1420 для WG) |
| **CPU bottleneck** | `htop` — нагрузка на ядро | Включить hardware offload, AES-NI |
| **Cipher не оптимален** | Проверить cipher в конфиге | Использовать AES-GCM или ChaCha20 |
| **Single queue** | `ethtool -l <nic>` | Включить multi-queue: `ethtool -L <nic> combined 4` |

---

## Универсальные команды диагностики

### Базовые

```bash
# Просмотр всех туннельных интерфейсов
ip -d link show | grep -E "(wg|tun|tap|gre|ipip|vxlan)" -A2

# Просмотр статистики ошибок
ip -s link show <interface>

# Проверка ARP/NDP
ip neigh show dev <interface>

# Просмотр conntrack
conntrack -L 2>/dev/null | head -20
```

### Продвинутые

```bash
# Захват трафика на туннельном интерфейсе
sudo tcpdump -ni <interface> -c 20

# Захват трафика на физическом интерфейсе (для VPN-протокола)
# WireGuard: UDP 51820
sudo tcpdump -ni eth0 udp port 51820 -c 10

# IPsec: ESP
sudo tcpdump -ni eth0 proto esp -c 10

# GRE: IP 47
sudo tcpdump -ni eth0 proto 47 -c 10

# OpenVPN: UDP 1194
sudo tcpdump -ni eth0 udp port 1194 -c 10

# Просмотр ошибок ядра
dmesg | tail -20

# Просмотр логов VPN-сервиса
journalctl -u <vpn_service> -n 50 --no-pager
```

---

## MTU/MSS: самая частая проблема

### Формула расчёта

```
Payload_max = MTU_physical - IP_header(20) - UDP_header(8) - VPN_overhead - TCP_header(20)

Пример для WireGuard (MTU physical = 1500):
Payload_max = 1500 - 20 - 8 - 60 - 20 = 1392 байта
```

### MSS Clamping (универсальный)

```bash
# Автоматическая подстройка MSS под PMTU
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o <tunnel_interface> -j TCPMSS --clamp-mss-to-pmtu

# Жёсткая установка MSS
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o <tunnel_interface> -j TCPMSS --set-mss 1360

# nftables
nft add rule inet filter forward oifname "<tunnel_interface>" \
    tcp flags syn tcp option maxseg size set 1360
```

### Проверка MSS

```bash
# Просмотр MSS в активных соединениях
ss -ti | grep mss
# → mss 1360   (норма)
# → mss 1460   (проблема — MTU не уменьшен)

# Просмотр MSS в заголовке SYN
sudo tcpdump -ni <interface> 'tcp[tcpflags] & (tcp-syn) != 0' -c 5 -v 2>/dev/null | grep mss
```

---

## Дополнительная информация

### Связанные документы

- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — глубокий разбор MTU, PMTUD, MSS Clamping
- **[IPsec Troubleshooting](./ipsec/ipsec_troubleshooting.md)** — специфичные ошибки IPsec
- **[WireGuard Troubleshooting](./wireguard_practical.md#типичные-ошибки-и-их-устранение)** — специфичные ошибки WireGuard
- **[GRE Troubleshooting](./gre/gre.md#диагностика-и-устранение-неисправностей)** — специфичные ошибки GRE
- **[Firewall templates](./vpn_firewall_templates.md)** — шаблоны правил для nftables/iptables
