# WireGuard — практическое руководство в контексте туннелей

## Определения

**WireGuard** — современный протокол VPN-туннелирования, работающий на уровне L3. Использует UDP-транспорт (порт 51820) и криптографические примитивы нового поколения: Curve25519 (обмен ключами), ChaCha20 (шифрование), Poly1305 (аутентификация), BLAKE2s (хеширование).

**Ключевое отличие от классических VPN:** WireGuard реализован как модуль ядра Linux (не в userspace), что обеспечивает производительность, сопоставимую сGRE, но с нативным шифрованием.

> **См. также:** [Протокол WireGuard (детали протокола)](../../Vpn/wireguard.md), [GRE vs WireGuard](./gre/gre_vs_wireguard.md), [Сравнение VPN-технологий](./tunneling_overview.md)

---

## Предварительные требования

### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая |
|-----------|-------------------|---------------|
| **Ядро Linux** | 5.6 (нативная поддержка) | 5.15+ |
| **wireguard-tools** | 1.0 | 1.1+ |
| **iproute2** | 5.10 | 5.15+ |

### Проверка наличия модуля ядра

```bash
# Проверка модуля wireguard
modinfo wireguard | head -3
# → filename:       /lib/modules/$(uname -r)/kernel/drivers/net/wireguard.ko
# → license:        GPL v2

# Проверка загруженности
lsmod | grep wireguard
# → wireguard           110592  0

# Если модуль не загружен
sudo modprobe wireguard
```

### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install wireguard wireguard-tools

# RHEL/CentOS/Rocky 8+
sudo dnf install kmod-wireguard wireguard-tools

# Arch Linux
sudo pacman -S wireguard-tools
```

### Включение IP-форвардинга

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-wireguard.conf
sudo sysctl -p /etc/sysctl.d/90-wireguard.conf
```

---

## Основные концепции

### Архитектура и модель безопасности

WireGuard использует **модель坤的信任** (Trust Model):
- Нет аутентификации на уровне транспорта (нет handshake, как в IKE)
- Аутентификация происходит через **статические публичные ключи** (Curve25519)
- Каждый пакет зашифрован индивидуальным ключом сессии (ephemeral key)
- Результат: **0-RTT** при повторном подключении

### Сравнение с другими VPN

| Параметр | WireGuard | IPsec (IKEv2) | OpenVPN | GRE+IPsec |
|----------|-----------|---------------|---------|-----------|
| **Уровень** | L3 | L3 | L2/L3 | L3 |
| **Транспорт** | UDP 51820 | UDP 500/4500, ESP | TCP/UDP | IP 47 + ESP |
| **Шифрование** | ChaCha20-Poly1305 | AES-GCM/CBC | OpenSSL | AES-GCM |
| **Overhead** | 60 байт | 50-73 байт | 57-73 байт | 74-101 байт |
| **MTU** | 1420 | 1400-1420 | 1390-1420 | 1360-1400 |
| **Производительность** | ~7.8 Gbps | ~5.2 Gbps | ~1 Gbps | ~5.2 Gbps |
| **NAT Traversal** | Нативно (UDP) | NAT-T (ESP in UDP) | TCP bypass | Требует FOU |
| **Конфигурация** | 1 файл, 2 ключа | swanctl.conf + сертификаты | server.conf + ca/keys | strongSwan + GRE |
| **Мультикаст** | Нет | Route-based (да) | Нет | Да |

> **Подробное сравнение:** [GRE vs WireGuard](./gre/gre_vs_wireguard.md), [Расширенное сравнение VPN](./ipsec/ipsec.md#расширенное-сравнение-vpn)

### Формат конфигурации

WireGuard использует простой INI-подобный формат (`wg0.conf`):

```ini
[Interface]
# Локальные параметры (приватный ключ, адрес, iptables)
PrivateKey = <client_private_key>
Address = 10.0.0.2/32
DNS = 1.1.1.1

[Peer]
# Параметры удалённого узла (публичный ключ, endpoint, allowed-ips)
PublicKey = <server_public_key>
Endpoint = 203.0.113.1:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

---

## Практические сценарии

### Site-to-Site VPN (точка-точка)

**Задача:** Соединить две подсети (192.168.1.0/24 и 192.168.2.0/24) через WireGuard-туннель.

#### Шаг 1: Генерация ключей на обоих хостах

```bash
# На каждом хосте (выполняется 1 раз)
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key
chmod 600 /etc/wireguard/private.key

# Просмотр ключей
cat /etc/wireguard/public.key
# → aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789=
```

#### Шаг 2: Конфигурация Шлюза A (198.51.100.1)

```ini
# /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <A_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

# PostUp/PostDown:iptables правила для маршрутизации и NAT
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <B_public_key>
AllowedIPs = 192.168.2.0/24, 10.0.0.2/32
Endpoint = 203.0.113.2:51820
```

#### Шаг 3: Конфигурация Шлюза B (203.0.113.2)

```ini
# /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <B_private_key>
Address = 10.0.0.2/24
ListenPort = 51820

PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <A_public_key>
AllowedIPs = 192.168.1.0/24, 10.0.0.1/32
Endpoint = 198.51.100.1:51820
```

#### Шаг 4: Запуск и валидация

```bash
# Запуск на обоих хостах
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Проверка состояния
sudo wg show
# → interface: wg0
# →   public key: <pubkey>
# →   private key: (hidden)
# →   listening port: 51820
# →
# → peer: <remote_pubkey>
# →   endpoint: 203.0.113.2:51820
# →   allowed ips: 192.168.2.0/24, 10.0.0.2/32
# →   latest handshake: 5 seconds ago
# →   transfer: 1.2 MiB received, 856 KiB sent

# Пинг через туннель
ping -c 2 10.0.0.2
# → 64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.89 ms

# Проверка маршрута
ip route show dev wg0
# → 192.168.2.0/24 via 10.0.0.2 proto static
# → 10.0.0.2/32 proto kernel scope link src 10.0.0.1
```

### Remote Access VPN (удалённый доступ)

**Задача:** Подключить удалённого сотрудника к корпоративной сети (192.168.1.0/24) через WireGuard.

#### Серверная конфигурация

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
AllowedIPs = 10.0.0.2/32, 192.168.1.0/24

# Клиент 2 (Bob)
[Peer]
PublicKey = <bob_public_key>
AllowedIPs = 10.0.0.3/32, 192.168.1.0/24
```

#### Конфигурация клиента (Alice)

```ini
# ~/.config/wireguard/wg0.conf (Linux)
# или C:\Users\Alice\WireGuard\wg0.conf (Windows)
[Interface]
PrivateKey = <alice_private_key>
Address = 10.0.0.2/32
DNS = 192.168.1.53, 8.8.8.8

[Peer]
PublicKey = <server_public_key>
Endpoint = vpn.example.com:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

#### Добавление нового клиента на сервере

```bash
# Генерация ключей для нового клиента
CLIENT_PRIVKEY=$(wg genkey)
CLIENT_PUBKEY=$(echo "$CLIENT_PRIVKEY" | wg pubkey)
CLIENT_ADDR="10.0.0.4"

# Добавление через wg set (без перезапуска)
sudo wg set wg0 peer "$CLIENT_PUBKEY" allowed-ips 10.0.0.4/32,192.168.1.0/24

# Сохранение конфигурации для персистентности
sudo wg-quick save wg0
```

### WireGuard поверх существующего туннеля (Double Tunnel)

**Задача:** Шифровать GRE-туннель с помощью WireGuard (VXLAN over WireGuard).

```bash
# 1. Создание WireGuard-туннеля
sudo ip link add wg0 type wireguard
sudo wg set wg0 listen-port 51820 private-key /etc/wireguard/private.key \
    peer <remote_pubkey> endpoint 203.0.113.2:51820 \
    allowed-ips 0.0.0.0/0
sudo ip addr add 10.0.0.1/24 dev wg0
sudo ip link set wg0 up

# 2. Создание GRE поверх WireGuard
sudo ip link add gre0 type gre local 10.0.0.1 remote 10.0.0.2
sudo ip addr add 172.16.0.1/30 dev gre0
sudo ip link set gre0 up

# 3. Проверка
ip -d link show gre0
# → gre remote 10.0.0.2 local 10.0.0.1 ...
# Трафик: [GRE][WireGuard][UDP][IP] — шифрование на уровне WireGuard
```

### Нативная маршрутизация (без NAT)

Для сценариев, где NAT не нужен (например, site-to-site с уникальными подсетями):

```ini
# Сервер
[Interface]
PrivateKey = <key>
Address = 10.0.0.1/24

[Peer]
PublicKey = <remote_key>
AllowedIPs = 192.168.2.0/24  # Только маршруты удалённой сети
Endpoint = 203.0.113.2:51820
```

```bash
# Проверка таблицы маршрутизации
ip route show dev wg0
# → 192.168.2.0/24 via 10.0.0.2 proto static
```

---

## Диагностика

### Базовые команды

```bash
# Просмотр состояния WireGuard
sudo wg show
# → interface: wg0
# →   public key: ...
# →   listening port: 51820
# →   peer: ...
# →     latest handshake: 3 seconds ago
# →     transfer: 12.5 MiB received, 8.3 MiB sent

# Просмотр интерфейса
ip -d link show wg0
# → wireguard: ...
# →   listening port: 51820

# Просмотр статистики
ip -s link show wg0
# → RX: bytes=12345678 packets=9876 errors=0 dropped=0
# → TX: bytes=87654321 packets=6543 errors=0 dropped=0

# Проверка маршрута
ip route get 192.168.2.1
# → 192.168.2.1 via 10.0.0.2 dev wg0 src 10.0.0.1 uid 0
```

### Проверка handshakes и подключений

```bash
# Проверка handshakes (критически важно!)
sudo wg show wg0 latest-handshakes
# → <pubkey>    1234567890  (timestamp)
# Если handshakes нет — проблема с сетью или ключами

# Проверка transfer (трафик)
sudo wg show wg0 transfer
# → <pubkey>    12345678    87654321

# Проверка endpoints
sudo wg show wg0 endpoints
# → <pubkey>    203.0.113.2:51820

# Проверка allowed-ips
sudo wg show wg0 allowed-ips
# → <pubkey>    192.168.2.0/24, 10.0.0.2/32
```

### Диагностика через sysctl

```bash
# Проверка IP-форвардинга
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Проверка conntrack для WireGuard
conntrack -L -p udp --dport 51820 2>/dev/null
# → udp  17 29 src=198.51.100.1 dst=203.0.113.2 sport=51820 dport=51820 ...

# Проверка логов ядра
dmesg | grep wireguard
# → [wireguard] WireGuard 1.0.0 loaded
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| **`Unable to modify interface: Operation not permitted`** | Нет прав root | `whoami` | `sudo wg-quick up wg0` |
| **`wg:>` (WireGuard запускается, но нет handshakes)** | Firewall блокирует UDP 51820 | `sudo wg show latest-handshakes` — нет данных | Разрешить UDP 51820 на обоих хостах |
| **`No such device`** | Модуль wireguard не загружен | `lsmod \| grep wireguard` | `sudo modprobe wireguard` |
| **Handshake есть, но пинга нет** | AllowedIPs не включают нужные маршруты | `sudo wg show allowed-ips` | Добавить подсеть в AllowedIPs |
| **Пинг работает, TCP зависает** | MTU слишком велик для WireGuard | `ping -M do -s 1392 <remote>` | Установить MTU 1420: `ip link set wg0 mtu 1420` |
| **DNS не работает через VPN** | DNS не настроен или DNS leak | `resolvectl status wg0` | Добавить `DNS = 8.8.8.8` в [Interface] |
| **Туннель падает при смене IP** | Клиент сменил IP, сервер не обновился | `sudo wg show` — endpoint не обновляется | `PersistentKeepalive = 25` на клиенте |
| **`Handshake for peer did not complete after 5 seconds`** | Неправильный ключ или Endpoint | Проверить ключи на обоих концах | Убедиться, что PublicKey = pub другого хоста |
| **Двойной NAT, туннель не работает** | Carrier-grade NAT (CGNAT) | ` traceroute 203.0.113.2` — приватный hop | Использовать UDP-hole punching или relay |

---

## Лучшие практики

### Безопасность

1. **Хранение приватных ключей:**
   ```bash
   # Права доступа 600 (только root)
   sudo chmod 600 /etc/wireguard/private.key

   # Или использовать параметрконфигурации
   # В wg0.conf: PrivateKey = <key> (автоматически защищён)
   ```

2. **Ограничение AllowedIPs:**
   ```bash
   # НЕ используйте 0.0.0.0/0 на сервере для site-to-site
   # Плохо:
   AllowedIPs = 0.0.0.0/0
   # Хорошо:
   AllowedIPs = 192.168.2.0/24, 10.0.0.2/32
   ```

3. **Firewall для WireGuard:**
   ```bash
   # nftables: разрешить UDP 51820 только от известных IP
   nft add rule inet filter input udp dport 51820 ip saddr { 198.51.100.0/24, 203.0.113.0/24 } accept
   nft add rule inet filter input udp dport 51820 drop
   ```

### MTU-тюнинг

| Сценарий | Рекомендуемый MTU | Пояснение |
|----------|-------------------|-----------|
| **WireGuard (чистый)** | 1420 | 1500 - 20 (IP) - 8 (UDP) - 32 (WG) - 20 (запас) |
| **WireGuard + PPPoE** | 1400 | 1500 - 8 (PPPoE) - 60 (WG) - 32 (запас) |
| **WireGuard через IPsec** | 1360 | 1500 - 60 (IPsec) - 60 (WG) - 20 (запас) |

```bash
# Установка MTU
sudo ip link set wg0 mtu 1420

# MSS Clamping (для TCP)
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o wg0 -j TCPMSS --clamp-mss-to-pmtu
```

### Персистентность и автозагрузка

```bash
# Включение автозапуска
sudo systemctl enable wg-quick@wg0

# Остановка
sudo systemctl stop wg-quick@wg0

# Статус
sudo systemctl status wg-quick@wg0
```

### Резервное копирование конфигурации

```bash
# Бэкап ключей и конфигов
sudo tar czf /backup/wireguard-$(date +%F).tar.gz /etc/wireguard/

# Восстановление
sudo tar xzf /backup/wireguard-2025-01-15.tar.gz -C /
sudo systemctl restart wg-quick@wg0
```

---

## Граничные случаи и ограничения

1. **WireGuard не поддерживает мультикаст:** В отличие от GRE, WireGuard не может передавать multicast-трафик. Для multicast используйте GRE или VXLAN.

2. **Нет встроенного keepalive:** WireGuard не отправляет keepalive-пакеты по умолчанию. При работе через NAT необходимо задавать `PersistentKeepalive = 25`.

3. **Одна сессия на пару ключей:** WireGuard не поддерживает несколько параллельных сессий между одними и теми же ключами. При смене IP Endpoint автоматически обновляется.

4. **Нет PKI (инфраструктуры открытых ключей):** WireGuard не имеет встроенного CA. Для масштабирования (>50 хостов) требуется внешний PKI или автоматизация ключей.

5. **MTU:** WireGuard добавляет 60 байт оверхеда. При стеке протоколов (VXLAN + WireGuard) MTU должен быть уменьшен до 1360.

6. **Производительность в контейнерах:** В Docker/Kubernetes WireGuard требует `--cap-add=NET_ADMIN` и доступа к `/dev/net/tun`.

7. **Windows/macOS:** Клиенты WireGuard доступны для всех ОС, но конфигурация отличается (используется GUI или `wg-quick` через WSL).

---

## Дополнительная информация

### Связанные документы

- **[Протокол WireGuard (детали протокола)](../../Vpn/wireguard.md)** — криптография, Noise_IK handshake, dynamic IP rebinding
- **[GRE vs WireGuard](./gre/gre_vs_wireguard.md)** — сравнение протоколов, критерии выбора, миграция GRE→WireGuard
- **[IPsec vs WireGuard](./ipsec/ipsec.md#расширенное-сравнение-vpn)** — когда выбирать IPsec вместо WireGuard
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead и MSS Clamping
- **[NAT и VPN](../Concepts/nat/nat_and_vpn.md)** — работа WireGuard за NAT, PersistentKeepalive, CGNAT
- **[VPN и Service Mesh](../Concepts/vpn_vs_service_mesh.md)** — practical site-to-site пример с PostUp/PostDown
- **[WireGuard в Cilium](../../Kubernetes/Networking/Network/CNI/cilium.md)** — шифрование трафика в Kubernetes
