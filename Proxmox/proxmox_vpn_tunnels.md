# VPN-туннели в Proxmox VE

## Определения

**WireGuard** -- современный VPN-протокол, обеспечивающий безопасное и эффективное шифрование сетевого трафика. Использует криптографические примитивыChaCha20, Poly1305, Curve25519. Реализован как модуль ядра Linux, обеспечивая производительность, сопоставимую с GRE.

**Tailscale** -- коммерческий VPN-сервис на базе WireGuard, обеспечивающий mesh-топологию с централизованным управлением ключами и аутентификацией через OAuth/OIDC. Работает через координатор (coordination server).

**Site-to-Site VPN** -- соединение между двумя сетями (офис, дата-центр) через зашифрованный туннель. Позволяет устройствам в разных сетях видеть друг друга как в единой LAN.

**Mesh VPN** -- топология VPN, где каждое устройство имеет прямое соединение с каждым другим устройством (full mesh) или через промежуточные узлы. Обеспечивает отказоустойчивость и низкую задержку.

**NAT Traversal** -- техника обхода NAT для установления прямого соединения между устройствами за разными NAT. WireGuard использует UDP hole punching.

**PSK (Pre-Shared Key)** -- предварительный общий ключ, добавляющий дополнительный уровень шифрования поверх асимметричной криптографии WireGuard.

**Key Rotation** -- регулярная замена ключей шифрования для ограничения времени использования компрометированного ключа.

## Теоретический блок

### Архитектура VPN в Proxmox

```
┌─────────────────────────────────────────┐
│  Proxmox Host                            │
│  ├── WireGuard kernel module             │
│  ├── wg0 interface (tunnel endpoint)     │
│  ├── Routing table                       │
│  └── Firewall rules                      │
├─────────────────────────────────────────┤
│  VM/LXC Containers                       │
│  ├── Internal traffic → routed via wg0   │
│  └── External traffic → via default gw   │
└─────────────────────────────────────────┘
         │
         │ WireGuard tunnel (UDP 51820)
         │
┌─────────────────────────────────────────┐
│  Remote Site / Cloud                     │
│  ├── WireGuard peer                     │
│  └── Internal network                   │
└─────────────────────────────────────────┘
```

### Топологии VPN

| Топология | Описание | Использование |
| :--- | :--- | :--- |
| **Hub-and-Spoke** | Один центральный узел, все остальные подключаются к нему | Малые офисы, remote workers |
| **Full Mesh** | Каждый узел связан с каждым | Дата-центры, CI/CD |
| **Site-to-Site** | Два узла связаны туннелем | Соединение офиса и облака |

### WireGuard vs Tailscale

| Характеристика | WireGuard | Tailscale |
| :--- | :--- | :--- |
| **Управление ключами** | Ручное (статические ключи) | Автоматическое (coordination server) |
| **Аутентификация** | PSK / ключи | OAuth, OIDC, SAML |
| **Mesh** | Ручная настройка | Автоматический mesh |
| **NAT Traversal** | Требует настройки | Автоматический (DERP relay) |
| **Стоимость** | Бесплатно | Бесплатный план + paid |
| **Производительность** | Нативная (ядро) | Зависит от relay |

## Практические сценарии

### 1. WireGuard Site-to-Site между двумя узлами Proxmox

**Узел A (10.0.0.1):**

```bash
# Установка WireGuard
apt install wireguard

# Генерация ключей
wg genkey | tee /etc/wireguard/private.key | wg pubkey > /etc/wireguard/public.key
chmod 600 /etc/wireguard/private.key

# Конфигурация (/etc/wireguard/wg0.conf)
[Interface]
Address = 10.100.0.1/24
ListenPort = 51820
PrivateKey = <private_key_A>
# Firewall rules
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <public_key_B>
Endpoint = 10.0.0.2:51820
AllowedIPs = 10.100.0.2/32, 192.168.1.0/24
PersistentKeepalive = 25
```

**Узел B (10.0.0.2):**

```bash
# Конфигурация (/etc/wireguard/wg0.conf)
[Interface]
Address = 10.100.0.2/24
ListenPort = 51820
PrivateKey = <private_key_B>
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <public_key_A>
Endpoint = 10.0.0.1:51820
AllowedIPs = 10.100.0.1/32, 192.168.0.0/24
PersistentKeepalive = 25
```

**Запуск:**

```bash
# На обоих узлах
systemctl enable wg-quick@wg0
systemctl start wg-quick@wg0

# Проверка
wg show
# → interface: wg0
#   peer: <public_key>
#     endpoint: 10.0.0.2:51820
#     allowed ips: 10.100.0.2/32, 192.168.1.0/24
#     latest handshake: 12 seconds ago

# Пинг через туннель
ping 10.100.0.2
```

### 2. WireGuard для Remote Access

```bash
# Сервер (Proxmox host)
[Interface]
Address = 10.100.0.1/24
ListenPort = 51820
PrivateKey = <server_private_key>
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

[Peer]
PublicKey = <client_public_key>
AllowedIPs = 10.100.0.2/32
# Для полного туннеля (весь трафик через VPN):
# AllowedIPs = 0.0.0.0/0

# Клиент (laptop/desktop)
[Interface]
Address = 10.100.0.2/24
PrivateKey = <client_private_key>
DNS = 1.1.1.1

[Peer]
PublicKey = <server_public_key>
Endpoint = <server_public_ip>:51820
AllowedIPs = 0.0.0.0/0  # Full tunnel
PersistentKeepalive = 25
```

### 3. Tailscale на Proxmox

```bash
# Установка Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Включение
tailscale up --advertise-routes=192.168.0.0/24,10.0.0.0/8

# Проверка
tailscale status
# →Hostname        IPv4            IPv6                    Status
# node1           100.64.0.1      fd7a:...                active

# Настройка exit node (для full tunnel)
tailscale up --advertise-exit-node

# Использование exit node с клиента
tailscale up --exit-node=<node-name>
```

### 4. Firewall для WireGuard

```bash
# Открытие порта WireGuard в Proxmox firewall
# В host.fw:
[RULES]
IN ACCEPT -p udp --dport 51820 -source 0.0.0.0/0

# Или только с определенных IP:
IN ACCEPT -p udp --dport 51820 -source 10.0.0.0/8
IN ACCEPT -p udp --dport 51820 -source 192.168.0.0/16

# Forwarding rules
iptables -A FORWARD -i wg0 -o vmbr0 -j ACCEPT
iptables -A FORWARD -i vmbr0 -o wg0 -j ACCEPT
```

### 5. Мониторинг VPN

```bash
# Статус WireGuard
wg show
wg show wg0 latest-handshakes
wg show wg0 transfer

# Логи
journalctl -u wg-quick@wg0

# Мониторинг через Prometheus
# Экспорт метрик через node_exporter textfile collector
cat > /var/lib/node_exporter/textfile_collector/wireguard.prom << EOF
# HELP wireguard_peer_transfer_bytes_total Total bytes transferred
# TYPE wireguard_peer_transfer_bytes_total counter
wireguard_peer_transfer_bytes_total{interface="wg0",peer="<public_key>"} $(wg show wg0 transfer | awk 'NR>1 {print $3}')
EOF
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Peer не отвечает | Firewall блокирует UDP 51820 | Откройте порт: `iptables -A INPUT -p udp --dport 51820 -j ACCEPT` |
| Handshake не проходит | Неверные ключи | Проверьте: `wg show` -- нет handshake |
| Трафик не маршрутизируется | Неправильные AllowedIPs | Проверьте маршруты: `ip route show table all` |
| NAT traversal не работает | Симметричный NAT | Используйте DERP relay (Tailscale) или статический IP |
| Высокая задержка | Маршрут через relay | Настройте прямое соединение или ближайший DERP |
| Пакеты теряются | MTU mismatch | Уменьшите MTU: `wg set wg0 mtu 1420` |

## Лучшие практики

1. **Используйте статические ключи**: Не генерируйте ключи динамически; храните их в securely.
2. **Настройте Keepalive**: `PersistentKeepalive = 25` для NAT traversal.
3. **Ограничьте AllowedIPs**: Не используйте `0.0.0.0/0`unless necessary (full tunnel).
4. **Мониторинг**: Отслеживайте handshake, transfer, packet loss.
5. **Firewall**: Разрешайте только необходимые порты и протоколы.
6. **Backup ключей**: Резервируйте приватные ключи; при потере потребуется перенастройка пиров.
7. **Tailscale для сложных топологий**: Автоматический mesh и NAT traversal упрощают управление.

## Граничные случаи

- **WireGuard и Docker**: WireGuard работает в ядре; контейнеры Docker могут маршрутизироваться через wg0.
- **MTU**: WireGuard добавляет заголовок (~60 байт); уменьшите MTU на интерфейсе wg0.
- **Multiple peers**: Proxmox host может быть peer для нескольких удаленных сетей одновременно.
- **Split tunneling**: Часть трафика через VPN, часть через интернет; настраивается через AllowedIPs.

## Дополнительная информация

### Связанные темы

- [WireGuard -- SSoT](../Vpn/wireguard.md)
- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
- [Firewall в Proxmox](./proxmox_firewall_advanced.md)
