# OpenVPN — практическое руководство

## Определения

**OpenVPN** — open-source VPN-протокол, реализованный в пользовательском пространстве (userspace). Использует библиотеку OpenSSL для шифрования (TLS 1.2/1.3) и модуль ядра TUN/TAP для создания виртуальных интерфейсов.

**Ключевые характеристики:**
- **Уровень:** L3 (TUN) или L2 (TAP)
- **Транспорт:** TCP 443 или UDP 1194
- **Шифрование:** OpenSSL (AES-256-GCM, ChaCha20-Poly1305)
- **Аутентификация:** PKI (сертификаты), PSK, LDAP, RADIUS
- **Overhead:** 57–73 байт (TUN), 73–91 байт (TAP)

> **См. также:** [TUN vs TAP](./tun_vs_tap.md), [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md), [WireGuard](./wireguard_practical.md)

---

## Предварительные требования

### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install openvpn easy-rsa

# RHEL/CentOS/Rocky
sudo dnf install openvpn easy-rsa

# Arch Linux
sudo pacman -S openvpn easy-rsa
```

### Проверка модуля TUN

```bash
# Проверка наличия /dev/net/tun
ls -la /dev/net/tun
# → crw-rw---- 1 root root 10, 200 ... /dev/net/tun

# Если отсутствует
sudo mknod /dev/net/tun c 10 200
sudo chmod 600 /dev/net/tun
```

---

## Основные концепции

### Архитектура и режимы работы

| Режим | Интерфейс | Уровень | Применение |
|-------|-----------|---------|------------|
| **TUN (по умолчанию)** | tun0 | L3 | Remote Access VPN, site-to-site |
| **TAP** | tap0 | L2 | Bridging, виртуализация, не-IP протоколы |

### Сравнение с другими VPN

| Параметр | OpenVPN | WireGuard | IPsec (IKEv2) |
|----------|---------|-----------|---------------|
| **Производительность** | ~1 Gbps (userspace) | ~7.8 Gbps (ядро) | ~5.2 Gbps (ядро) |
| **NAT Traversal** | TCP 443 (обход любого firewall) | UDP 51820 | NAT-T (UDP 4500) |
| **Аутентификация** | PKI, PSK, LDAP, RADIUS | Статические ключи | PKI, PSK, EAP |
| **Гибкость** | Высокая (скрипты, плагины) | Низкая | Средняя |
| **Простота настройки** | Средняя | Очень простая | Сложная |

> **Подробнее:** [GRE vs WireGuard](./gre/gre_vs_wireguard.md#сравнение-с-другими-vpn), [Расширенное сравнение VPN](./ipsec/ipsec.md#расширенное-сравнение-vpn)

---

## Практические сценарии

### Site-to-Site VPN (PKI)

#### Шаг 1: Настройка CA (Certificate Authority)

```bash
# Инициализация PKI
make-cadir ~/openvpn-ca
cd ~/openvpn-ca

# Настройка vars
cat > vars << 'EOF'
set_var EASYRSA_REQ_COUNTRY    "RU"
set_var EASYRSA_REQ_PROVINCE   "Moscow"
set_var EASYRSA_REQ_CITY       "Moscow"
set_var EASYRSA_REQ_ORG        "Example Corp"
set_var EASYRSA_REQ_EMAIL      "admin@example.com"
set_var EASYRSA_REQ_OU         "IT"
set_var EASYRSA_ALGO           "ec"
set_var EASYRSA_DIGEST         "sha512"
EOF

# Инициализация PKI
./easyrsa init-pki

# Создание CA
./easyrsa build-ca nopass

# Создание сертификатов для шлюзов
./easyrsa build-server-full gw1.example.com nopass
./easyrsa build-server-full gw2.example.com nopass

# Генерация ключей DH (для legacy-режима)
./easyrsa gen-dh

# Создание сертификатов для клиентов
./easyrsa build-client-full client1.example.com nopass
```

#### Шаг 2: Конфигурация Сервера (gw1)

```bash
# /etc/openvpn/server.conf
port 1194
proto udp
dev tun

ca   /etc/openvpn/ca.crt
cert /etc/openvpn/gw1.example.com.crt
key  /etc/openvpn/gw1.example.com.key
dh   /etc/openvpn/dh.pem

# Подсеть для VPN-клиентов
server 10.8.0.0 255.255.255.0

# Маршруты до удалённых подсетей
push "route 192.168.1.0 255.255.255.0"

# DNS для клиентов
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"

# Шифрование
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2
tls-cipher TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384

# Keepalive
keepalive 10 120

# Привилегии
user nobody
group nogroup

# Персистентность
persist-key
persist-tun

# Логирование
status /var/log/openvpn/status.log
log-append /var/log/openvpn/openvpn.log
verb 3
```

#### Шаг 3: Конфигурация Клиента (gw2)

```bash
# /etc/openvpn/client.conf
client
dev tun
proto udp

remote 198.51.100.1 1194

resolv-retry infinite
nobind

persist-key
persist-tun

ca   /etc/openvpn/ca.crt
cert /etc/openvpn/gw2.example.com.crt
key  /etc/openvpn/gw2.example.com.key

cipher AES-256-GCM
auth SHA256
tls-version-min 1.2

verb 3
```

#### Шаг 4: Firewall и запуск

```bash
# nftables: разрешить OpenVPN
nft add rule inet filter input udp dport 1194 accept

# Запуск сервера
sudo systemctl enable openvpn@server
sudo systemctl start openvpn@server

# Проверка
ip addr show tun0
# → tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1500 ...
# →     inet 10.8.0.1 peer 10.8.0.2/32 scope global tun0
```

### Remote Access VPN (для сотрудников)

#### Серверная конфигурация

```bash
# /etc/openvpn/server.conf
port 443
proto tcp
dev tun

ca   /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key  /etc/openvpn/server.key
dh   /etc/openvpn/dh.pem

server 10.8.0.0 255.255.255.0

# Пуш-маршруты для корпоративной сети
push "route 192.168.1.0 255.255.255.0"
push "route 172.16.0.0 255.240.0.0"

# Split tunneling (только корпоративные маршруты через VPN)
push "redirect-gateway def1 bypass-dhcp"

# DNS
push "dhcp-option DNS 192.168.1.53"

# Шифрование
cipher AES-256-GCM
auth SHA256
tls-crypt /etc/openvpn/ta.key

# Масштабирование
max-clients 100

# Привилегии
user nobody
group nogroup
persist-key
persist-tun
```

#### Генерация tls-crypt ключа

```bash
# Генерация ключа для шифрования TLS- handshakes (защита от DoS)
openvpn --genkey secret /etc/openvpn/ta.key
```

#### Конфигурация клиента (Windows/Linux/macOS)

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
cert client.crt
key  client.key
tls-crypt ta.key

cipher AES-256-GCM
auth SHA256

verb 3

# Redirect all traffic through VPN (full tunnel)
# redirect-gateway def1 bypass-dhcp

# Split tunneling (only corporate subnets)
# route 192.168.1.0 255.255.255.0
# route 172.16.0.0 255.240.0.0
```

### Bridge-режим (TAP для L2-доступа)

Для сценариев, когда клиенту нужен L2-доступ к корпоративной сети (DHCP, broadcast):

```bash
# /etc/openvpn/server.conf
dev tap
port 1194
proto udp

ca   /etc/openvpn/ca.crt
cert /etc/openvpn/server.crt
key  /etc/openvpn/server.key

# Bridging с физическим интерфейсes
server-bridge 192.168.1.1 255.255.255.0 192.168.1.100 192.168.1.200

#Push-опции
push "dhcp-option DNS 192.168.1.53"
```

```bash
# Настройка моста на сервере
sudo ip link add br0 type bridge
sudo ip link set eth0 master br0
sudo ip link set tap0 master br0
sudo ip link set br0 up
sudo ip addr add 192.168.1.1/24 dev br0
```

---

## Диагностика

### Базовые команды

```bash
# Просмотр состояния OpenVPN
sudo systemctl status openvpn@server

# Просмотр логов
sudo journalctl -u openvpn@server -f
# или
sudo tail -f /var/log/openvpn/openvpn.log

# Просмотр интерфейсов
ip -br addr show tun0
# → tun0      UP             10.8.0.1/24

# Просмотр маршрутов
ip route show dev tun0
# → 10.8.0.0/24 proto kernel scope link src 10.8.0.1

# Просмотр подключённых клиентов
cat /var/log/openvpn/status.log
# → Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
# → client1.example.com,203.0.113.50:54321,12345678,87654321,2025-01-15 10:30:00
```

### Проверка MTU

```bash
# Проверка MTU на tun0
ip link show tun0 | grep mtu
# → mtu 1500

# Если MTU не уменьшен (проблема!)
# Установка MTU
sudo ip link set tun0 mtu 1390

# Проверка Path MTU
ping -M do -s 1362 -c 1 10.8.0.2
# → 1362 + 28 (IP+ICMP) + 57-73 (OpenVPN) ≈ 1450-1463
```

### Проверка через management интерфейс

```bash
# В server.conf добавить:
# management 127.0.0.1 7505

# Подключение к management
telnet 127.0.0.1 7505
# → >status
# → OpenVPN Client List:
# →  Common Name    Real Address         Bytes Received  Bytes Sent   Connected Since
# →  client1        203.0.113.50:54321   12345678        87654321     2025-01-15 10:30:00
# → >kill client1   # Отключение клиента
```

---

## Типичные ошибки и их устранение

| Симптом | Вероятная причина | Диагностика | Решение |
|---------|-------------------|-------------|---------|
| **`TLS Error: TLS handshake failed`** | Сертификат не совпадает, clock skew | `openssl x509 -in server.crt -noout -dates` | Синхронизировать время (NTP), проверить сертификаты |
| **`Cannot open TUN/TAP`** | Нет /dev/net/tun или нет прав | `ls -la /dev/net/tun` | `mknod /dev/net/tun c 10 200`, `setcap cap_net_admin+ep /usr/sbin/openvpn` |
| **`Initialization Sequence Completed` но пинга нет** | Firewall блокирует туннель или IP-форвардинг отключен | `sysctl net.ipv4.ip_forward` | Включить `ip_forward=1`, добавить правила FORWARD |
| **TCP-соединения зависают** | MTU не уменьшен, MSS превышает MTU | `ping -M do -s 1362 <tunnel_ip>` | Установить `tun-mtu 1390` или MSS Clamping |
| **Клиент подключается, но DNS не работает** | DNS не push-ится или /etc/resolv.conf перезаписывается | `resolvectl status tun0` | Добавить `script-security 2` и `up /etc/openvpn/update-resolv-conf` |
| **`AUTH_FAILED`** | Неверный сертификат или PSK | Проверить логи клиента | Убедиться, что сертификат не отозван (CRL) |
| **Туннель падает через каждые N минут** | Keepalive не настроен или firewall сбрасывает conntrack | `conntrack -L -p tcp --dport 1194` | Добавить `keepalive 10 120` |
| **`Connection reset, restarting`** | Сервер перезапущен или network flapping | Логи сервера | Проверить стабильность сети |

---

## Лучшие практики

### Безопасность

1. **Используйте tls-crypt** (не просто tls-auth):
   ```bash
   # Генерация tls-crypt ключа
   openvpn --genkey secret /etc/openvpn/ta.key
   # В конфиге: tls-crypt /etc/openvpn/ta.key
   ```

2. **Ограничьтеcipher и TLS:**
   ```
   cipher AES-256-GCM
   auth SHA256
   tls-version-min 1.2
   tls-cipher TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384
   ```

3. **RLS (Certificate Revocation List):**
   ```bash
   # Отзыв сертификата
   ./easyrsa revoke client1.example.com
   ./easyrsa gen-crl

   # В сервер.conf
   crl-verify /etc/openvpn/crl.pem
   ```

4. **Firewall:**
   ```bash
   # Разрешить только UDP 1194 (или TCP 443)
   nft add rule inet filter input udp dport 1194 accept
   nft add rule inet filter input udp dport 1194 drop
   ```

### MTU-тюнинг

| Сценарий | Рекомендуемый MTU | Пояснение |
|----------|-------------------|-----------|
| **OpenVPN TUN (UDP)** | 1390 | 1500 - 60-73 (OpenVPN overhead) - 40 (запас) |
| **OpenVPN TUN (TCP)** | 1380 | TCP добавляет дополнительный оверхед |
| **OpenVPN TAP** | 1500 | L2 in L2, минимальный оверхед |

```bash
# В server.conf
tun-mtu 1390

# Или через MSS Clamping
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o tun0 -j TCPMSS --clamp-mss-to-pmtu
```

### Персистентность

```bash
# Автозапуск OpenVPN
sudo systemctl enable openvpn@server
sudo systemctl start openvpn@server

# Шаблонный systemd-юнит для нескольких экземпляров
# /etc/systemd/system/openvpn@.service
[Unit]
Description=OpenVPN Tunnel %I
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/sbin/openvpn --config /etc/openvpn/%i.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## Граничные случаи и ограничения

1. **Производительность:** OpenVPN работает в userspace и потребляет больше CPU, чем WireGuard или IPsec. Для каналов >1 Gbps рекомендуется WireGuard.

2. **TCP-over-TCP:** При использовании OpenVPN поверх TCP (proto tcp) возникает проблема TCP-over-TCP meltdown. Рекомендуется UDP (proto udp).

3. **MTU:** OpenVPN добавляет 57–73 байт оверхеда. При стеке протоколов MTU должен быть уменьшен до 1360.

4. **Сертификаты:** OpenVPN требует PKI инфраструктуры. Для простых сценариев WireGuard проще.

5. **Windows:** OpenVPN требует установки TAP-драйвера на Windows. WireGuard имеет нативный клиент.

6. **Мультикаст:** OpenVPN не поддерживает multicast в TUN-режиме. Для multicast используйте GRE.

---

## Дополнительная информация

### Связанные документы

- **[TUN vs TAP](./tun_vs_tap.md)** — виртуальные интерфейсы, используемые OpenVPN
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead и MSS Clamping
- **[WireGuard — практическое руководство](./wireguard_practical.md)** — современная альтернатива OpenVPN
- **[GRE vs WireGuard](./gre/gre_vs_wireguard.md)** — сравнение протоколов
- **[IPsec](./ipsec/ipsec.md)** — ещё одна альтернатива для site-to-site
