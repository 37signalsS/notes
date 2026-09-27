# WireGuard

## Определения

**WireGuard** — современный VPN-протокол, разработанный с целью обеспечения безопасной и эффективной передачи данных в интернете. Он чрезвычайно простой, но в то же время быстрый и инновационный. Изначально он был доступен только для ОС семейства Linux, но позже стал кроссплатформенным.

WireGuard создает виртуальные сетевые интерфейсы (например, `wg0`), которые можно конфигурировать стандартными средствами Linux (назначать IP-адреса, маски подсети и т.д.).

На каждом устройстве, подключенном к виртуальной сети WireGuard, должен находиться конфигурационный файл, содержащий его собственный закрытый ключ и открытые ключи других участников этой VPN-сети (пиров). Когда IP-пакет отправляется в сетевой интерфейс WireGuard, он шифруется с использованием сессионного ключа, полученного в результате рукопожатия с пиром, и отправляется по UDP на соответствующий этому пиру Endpoint.

## Основные концепции

### Архитектура и модель безопасности

WireGuard использует **модель предварительного обмена ключами** (Pre-Shared Public Key Model):
- Нет аутентификации на уровне транспорта (нет handshake, как в IKE)
- Аутентификация происходит через **статические публичные ключи** (Curve25519)
- Каждый пакет зашифрован индивидуальным ключом сессии (ephemeral key)
- Результат: **0-RTT** при повторном подключении

WireGuard реализован как модуль ядра Linux (не в userspace), что обеспечивает производительность, сопоставимую с GRE, но с нативным шифрованием.

### Жизненный цикл соединения и протокол Noise_IK

WireGuard использует **протокол Noise** (конкретно: `Noise_IK`), который обеспечивает:
- Аутентификацию через публичные ключи
- Перфектную прямую секретность (Perfect Forward Secrecy) благодаря ephemeral ключам
- Минимальный поверхностный след (не требует handshake до попытки обмена)

**Последовательность handshake:**
1. Инициатор генерирует ephemeral ключ (Cur25519)
2. Вычисляет shared secret через ECDH (свой ephemeral + публичный ключ получателя)
3. Хеширует результат через HKDF (на основе BLAKE2s) для получения сессионного ключа
4. Шифрует пакет с использованием ChaCha20-Poly1305
5. Получатель повторяет операцию в обратную сторону
6. После handshake все последующие пакеты используют **симметричное шифрование** (ChaCha20-Poly1305)

**Важно:** Асимметричное шифрование (ECDH/Curve25519) используется **только для начального обмена ключами**. После установления соединения всё шифруется быстро и эффективно с использованием симметричного ключа. Это снижает нагрузку на CPU по сравнению с TLS-подобными VPN.

### Криптографические примитивы

WireGuard использует **современные и минималистичные криптографические примитивы**, включённые в библиотеку CryptoBlake2s:

| Назначение | Алгоритм |
|------------|----------|
| Ключевой обмен | Curve25519 |
| Аутентификация пакетов | Poly1305 |
| Шифрование | ChaCha20 |
| Хеш-функции | BLAKE2s |
| KDF (ключевая производная) | HKDF на основе BLAKE2s |

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

> **Подробное сравнение:** [GRE vs WireGuard](../Networking/Tunnels/gre/gre_vs_wireguard.md), [Расширенное сравнение VPN](../Networking/Tunnels/ipsec/ipsec.md#расширенное-сравнение-vpn)

### Формат конфигурации

WireGuard использует простой INI-подобный формат (`wg0.conf`):

```ini
[Interface]
# Локальные параметры (приватный ключ, адрес, iptables)
PrivateKey = <client_private_key>
Address = 10.0.0.2/32
DNS = 1.1.1.1
MTU = 1420

[Peer]
# Параметры удалённого узла (публичный ключ, endpoint, allowed-ips)
PublicKey = <server_public_key>
Endpoint = 203.0.113.1:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
```

### Принципы работы симметричного и асимметричного шифрования

WireGuard использует симметричное шифрование для шифрования трафика между пирами после первоначальной аутентификации:

1. **Асимметричное шифрование (Curve25519)** используется на этапе установления соединения (handshake):
   - Обмениваются ephemeral (временными) ключами
   - Производится согласование общего симметричного ключа (через протокол Noise_IK и алгоритм ECDH на Curve25519)
   - Этот симметричный ключ **уникален для каждой сессии**
2. **Симметричное шифрование (ChaCha20)** используется для **основного шифрования трафика** между пирами:
   - После завершения обмена ключами, весь пользовательский трафик (IP-пакеты) шифруется ChaCha20 с тем самым сессионным ключом
   - Аутентификация производится **Poly1305**, прикреплённой к каждому пакету (MAC)

**Почему так?**
- Асимметричное шифрование (ECDH/Curve25519) дорого по ресурсам, поэтому используется **только для начального обмена ключами**
- После установления соединения всё шифруется **быстро и эффективно** с использованием **симметричного ключа**, полученного из асимметрического обмена

### Динамический IP и обновление Endpoint

Если публичный IP-адрес сервера WireGuard меняется, клиенты теряют к нему доступ. Это происходит потому, что WireGuard при запуске определяет и "запоминает" свой IP-адрес. После смены IP сервер продолжает ожидать подключения на старом, уже неактуальном адресе, что приводит к разрыву VPN-соединения.

**Решение:** Создание systemd-таймера, который будет периодически выполнять скрипт. Скрипт принудительно переинициализирует слушающий сокет WireGuard, заставляя его определить новый IP-адрес без полного перезапуска службы.

**Предупреждение:** Этот метод решает проблему только на стороне сервера. Если вы используете файрвол (например, `ufw`, `iptables`) или облачные правила безопасности, вам также необходимо автоматизировать обновление правил для нового IP-адреса, чтобы разрешить трафик на порт WireGuard.

#### Создание скрипта для перепривязки сокета

Скрипт будет выполнять команду `wg set`, которая заставляет WireGuard перечитать свой сетевой интерфейс и обновить IP-адрес.

Создайте файл `/usr/local/bin/wg-rebind.sh`:

```bash
#!/bin/bash
#
# Скрипт для принудительной перепривязки слушающего сокета WireGuard.
# Это необходимо для серверов, работающих с динамическим IP-адресом.

# --- Переменные ---
readonly IFACE="wg0"
readonly PORT="51820"
# --- Конец переменных ---

set -o nounset
set -o errexit
set -o pipefail

echo "Rebinding WireGuard interface '$IFACE' to port $PORT..."

# Команда `wg set ... listen-port` заставляет WireGuard перепривязать сокет,
# что позволяет ему определить новый публичный IP-адрес сервера.
wg set "$IFACE" listen-port "$PORT"

echo "Successfully rebound."
```

Установите правильные права и сделайте скрипт исполняемым:

```bash
sudo chown root:root /usr/local/bin/wg-rebind.sh
sudo chmod 755 /usr/local/bin/wg-rebind.sh
```

#### Создание юнитов Systemd

Нам понадобится два файла: `service` для запуска скрипта и `timer` для его периодического вызова.

Создайте файл сервиса `/etc/systemd/system/wg-rebind.service`:

```ini
[Unit]
Description=Rebind WireGuard listening port to its dynamic IP
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wg-rebind.sh
```

Создайте файл таймера `/etc/systemd/system/wg-rebind.timer`:

Этот таймер будет запускать сервис каждые 3 минуты.

```ini
[Unit]
Description=Run wg-rebind.service every 3 minutes

[Timer]
# Запустить через 1 минуту после загрузки
OnBootSec=1min
# Запускать каждые 3 минуты после активации
OnUnitActiveSec=3min

[Install]
WantedBy=timers.target
```

#### Активация таймера

После создания файлов перезагрузите конфигурацию systemd, а затем включите и запустите таймер.

```bash
# Перечитать конфигурацию systemd
sudo systemctl daemon-reload

# Включить и немедленно запустить таймер
sudo systemctl enable --now wg-rebind.timer
```

### Генерация ключей

- **Приватный ключ** (private key) — хранится в секрете, используется для дешифрования и подписания.
- **Публичный ключ** (public key) — может быть передан другим участникам, используется для шифрования и верификации.

```bash
wg genkey | tee privatekey | wg pubkey > publickey
```

Каждый сервер сохраняет свой приватный ключ и передаёт свой публичный ключ другому участнику.

### Настройка интерфейса

Каждый сервер настраивает виртуальный интерфейс `wg0`, указывая:

- свой **приватный ключ**
- свой **виртуальный IP** (например, 10.0.0.x/24)
- публичный ключ и endpoint второго сервера

**Пример конфигурации для сервера A** (`/etc/wireguard/wg0.conf`):

```ini
[Interface]
PrivateKey = <A_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

[Peer]
PublicKey = <B_public_key>
AllowedIPs = 10.0.0.2/32
Endpoint = <B_public_ip>:51820
PersistentKeepalive = 25
```

### Аутентификация и обмен ключами

WireGuard **не использует традиционный процесс обмена ключами (как в TLS/SSL)**. Вместо этого:

- Аутентификация основана на **предварительном обмене публичными ключами**
- Обе стороны знают публичный ключ друг друга заранее
- Приватные ключи **никогда не покидают** серверы

### Установление соединения

Когда сервер A хочет отправить пакет на сервер B:

- A формирует зашифрованный пакет с использованием публичного ключа B
- Внутри используется временный ключ (ephemeral key) для обмена

Сервер B принимает пакет, расшифровывает его с помощью своего приватного ключа и отвечает.

После первого обмена пакеты шифруются и дешифруются в режиме **peer-to-peer** без необходимости посредников.

### Проверка состояния соединения

```bash
sudo wg show
```

### Типы шифрования

WireGuard использует **современные и минималистичные криптографические примитивы**, включённые в **библиотеку CryptoBlake2s**:

| Назначение | Алгоритм |
|------------|----------|
| Ключевой обмен | Curve25519 |
| Аутентификация пакетов | Poly1305 |
| Шифрование | ChaCha20 |
| Хеш-функции | BLAKE2s |
| KDF (ключ. производная) | HKDF на основе BLAKE2s |

## Практические сценарии

### Предварительные требования

#### Версии ядра и пакетов

| Компонент | Минимальная версия | Рекомендуемая |
|-----------|-------------------|---------------|
| **Ядро Linux** | 5.6 (нативная поддержка) | 5.15+ |
| **wireguard-tools** | 1.0 | 1.1+ |
| **iproute2** | 5.10 | 5.15+ |

#### Проверка наличия модуля ядра

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

#### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install wireguard wireguard-tools

# RHEL/CentOS/Rocky 8+
sudo dnf install kmod-wireguard wireguard-tools

# Arch Linux
sudo pacman -S wireguard-tools
```

#### Включение IP-форвардинга

```bash
sudo sysctl -w net.ipv4.ip_forward=1
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/90-wireguard.conf
sudo sysctl -p /etc/sysctl.d/90-wireguard.conf
```

### WireGuard в Docker (интеграция с DOCKER-USER)

Запуск WireGuard в Docker требует особой настройки из-за ограничений контейнеров. Основная проблема — контейнер не имеет доступа к модулю ядра `wireguard` и сетевым пространствам имён по умолчанию.

**Требования:**
- Модуль ядра `wireguard` загружен на хосте
- Контейнер имеет права `NET_ADMIN` и `SYS_MODULE`
- Доступ к `/dev/net/tun`
- Сетевое пространство хоста (для маршрутизации)

**Docker Compose конфигурация:**

```yaml
# docker-compose.yml
version: '3.8'

services:
  wireguard:
    image: linuxserver/wireguard
    container_name: wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Moscow
      - SERVERURL=vpn.example.com
      - SERVERPORT=51820
      - PEERS=3
      - PEERDNS=1.1.1.1
    volumes:
      - ./wg0-config:/config
      - /lib/modules:/lib/modules:ro
    ports:
      - 51820:51820/udp
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    restart: unless-stopped
```

**Интеграция с DOCKER-USER chain (iptables):**

Docker создаёт собственную цепочку `DOCKER-USER`, которая обрабатывает трафик к контейнерам до того, как он достигнет `DOCKER` chain. Это место для размещения правил VPN:

```bash
# Разрешить трафик на порт WireGuard из доверенных подсетей
sudo iptables -A DOCKER-USER -p udp --dport 51820 -s 198.51.100.0/24 -j ACCEPT

# Блокировать весь остальной UDP на порт 51820
sudo iptables -A DOCKER-USER -p udp --dport 51820 -j DROP

# Разрешить established/related соединения
sudo iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

**Проблема: маршрутизация**

Docker по умолчанию создает изолированную сеть. Для маршрутизации VPN-трафика:

```bash
# Добавление маршрута до VPN-подсети через Docker-сеть
sudo ip route add 10.0.0.0/24 via $(docker inspect wireguard -f '{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}')
```

### Настройка Split Tunneling (раздельная маршрутизация)

Split Tunneling позволяет направлять только часть трафика через VPN, а остальной — напрямую.

**Конфигурация клиента с Split Tunneling:**

```ini
[Interface]
PrivateKey = <client_private_key>
Address = 10.0.0.2/24
DNS = 1.1.1.1

[Peer]
PublicKey = <server_public_key>
Endpoint = <server_public_ip>:51820
# Только корпоративные подсети через VPN
AllowedIPs = 10.0.0.0/24, 192.168.100.0/24, 172.16.0.0/12
PersistentKeepalive = 25
```

**Проверка маршрутизации:**

```bash
# Запуск VPN
sudo wg-quick up wg0

# Проверка маршрутов
ip route show
# → 10.0.0.0/24 dev wg0 proto kernel scope link src 10.0.0.2
# → 192.168.100.0/24 dev wg0 scope link
# → 172.16.0.0/12 dev wg0 scope link
# → default via 192.168.1.1 dev eth0  (основной шлюз)

# Тест: трафик к корпоративному ресурсу идет через VPN
traceroute 192.168.100.50
# → 1  10.0.0.1  15.2ms  (через VPN)

# Тест: трафик в интернет идет напрямую
traceroute 8.8.8.8
# → 1  192.168.1.1  2.1ms  (напрямую)
```

### Настройка Kill Switch (защита от утечки IP)

Kill Switch блокирует весь трафик при разрыве VPN-соединения, предотвращая утечку реального IP.

**Предварительные требования:**
- WireGuard настроен и работает
- Доступ root

**Шаг 1: Создание скрипта Kill Switch**

```bash
sudo nano /etc/wireguard/killswitch.sh
```

```bash
#!/bin/bash
#
# Kill Switch для WireGuard
# Блокирует трафик при разрыве VPN

IFACE="wg0"
# IP сервера WireGuard (разрешен всегда для поддержания туннеля)
WG_SERVER_IP="10.0.0.1"
# Интерфейс физической сети
PHYS_IFACE="eth0"

set -o nounset
set -o errexit
set -o pipefail

enable_killswitch() {
    echo "Enabling Kill Switch..."

    # Очистка правил
    iptables -F
    iptables -t nat -F

    # Разрешение loopback
    iptables -A INPUT -i lo -j ACCEPT
    iptables -A OUTPUT -o lo -j ACCEPT

    # Разрешение установленных соединений
    iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

    # Разрешение трафика только через VPN-интерфейс
    iptables -A OUTPUT -o $IFACE -j ACCEPT

    # Разрешение трафика к VPN-серверу (для поддержания туннеля)
    iptables -A OUTPUT -o $PHYS_IFACE -d $WG_SERVER_IP -p udp --dport 51820 -j ACCEPT

    # Блокировка всего остального
    iptables -A OUTPUT -j DROP

    echo "Kill Switch enabled."
}

disable_killswitch() {
    echo "Disabling Kill Switch..."
    iptables -F
    iptables -t nat -F
    iptables -P INPUT ACCEPT
    iptables -P OUTPUT ACCEPT
    iptables -P FORWARD ACCEPT
    echo "Kill Switch disabled."
}

case "$1" in
    enable)
        enable_killswitch
        ;;
    disable)
        disable_killswitch
        ;;
    *)
        echo "Usage: $0 {enable|disable}"
        exit 1
        ;;
esac
```

```bash
sudo chmod +x /etc/wireguard/killswitch.sh
```

**Шаг 2: Интеграция с WireGuard**

Добавьте в `/etc/wireguard/wg0.conf`:

```ini
[Interface]
...
PostUp = /etc/wireguard/killswitch.sh enable
PostDown = /etc/wireguard/killswitch.sh disable
```

**Шаг 3: Проверка**

```bash
# Запуск VPN с Kill Switch
sudo wg-quick up wg0

# Проверка правил
sudo iptables -L -n
# → Chain OUTPUT (policy ACCEPT)
# → target     prot opt source               destination
# → ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0            state ESTABLISHED,RELATED
# → ACCEPT     all  --  0.0.0.0/0            0.0.0.0/0            out-interface wg0
# → DROP       all  --  0.0.0.0/0            0.0.0.0/0

# Тест: остановите VPN и проверьте, что трафик не идет
sudo wg-quick down wg0
curl --max-time 5 ifconfig.me
# → curl: (28) Connection timed out
```

### WireGuard с systemd-networkd

Альтернатива `wg-quick` — использование `systemd-networkd` для управления WireGuard-интерфейсами. Это обеспечивает лучшую интеграцию с systemd и более тонкий контроль.

**Создание файла `/etc/systemd/network/wg0.netdev`:**

```ini
[NetDev]
Name=wg0
Kind=wireguard

[WireGuard]
PrivateKey = <server_private_key>
ListenPort = 51820

[WireGuardPeer]
PublicKey = <client_public_key>
AllowedIPs = 10.0.0.2/32
Endpoint = 203.0.113.2:51820
PersistentKeepalive = 25
```

**Создание файла `/etc/systemd/network/wg0.network`:**

```ini
[Match]
Name=wg0

[Network]
Address=10.0.0.1/24
IPForward=yes
```

**Активация:**

```bash
sudo systemctl restart systemd-networkd
sudo networkctl status wg0
# → 3: wg0
# →     Link File: /etc/systemd/network/wg0.netdev
# →     Network File: /etc/systemd/network/wg0.network
# →     Type: wireguard
# →     State: routable (configuring)
# →   Address: 10.0.0.1/24
```

### PostUp/PostDown: продвинутые сценарии

PostUp и PostDown — директивы, которые выполняются при поднятии/опускании интерфейса. Они критически важны для автоматизации firewall и маршрутизации.

**Пример с Multiple Peers и Per-Peer Firewall:**

```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

# Глобальные правила: разрешить FORWARD для всех
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT

[Peer]
PublicKey = <alice_public_key>
AllowedIPs = 10.0.0.2/32, 192.168.1.0/24
# Per-peer: ограничить доступ к определённым портам
# (требует внешнего скрипта, так как wg-quick не поддерживает per-peer PostUp)

[Peer]
PublicKey = <bob_public_key>
AllowedIPs = 10.0.0.3/32
```

**Пример с nftables:**

```ini
[Interface]
PrivateKey = <server_private_key>
Address = 10.0.0.1/24
ListenPort = 51820

PostUp = nft add rule inet filter input iifname eth0 udp dport 51820 accept
PostDown = nft delete rule inet filter input iifname eth0 udp dport 51820 accept
PostUp = nft add rule inet filter forward iifname wg0 oifname eth0 accept
PostDown = nft delete rule inet filter forward iifname wg0 oifname eth0 accept
```

### Ротация ключей

WireGuard не имеет встроенного механизма ротации ключей. Для обновления ключа без разрыва соединения:

```bash
# На клиенте: генерация нового ключа
wg genkey | tee /etc/wireguard/private.key.new | wg pubkey > /etc/wireguard/public.key.new

# На сервере: добавление нового ключа
sudo wg set wg0 peer <new_client_pubkey> allowed-ips 10.0.0.4/32

# Перезагрузка клиента с новым ключом
sudo wg-quick down wg0 && sudo wg-quick up wg0

# На сервере: удаление старого ключа
sudo wg set wg0 peer <old_client_pubkey> remove

# Сохранение конфигурации
sudo wg-quick save wg0
```

### Резервное копирование и восстановление

```bash
# Бэкап ключей и конфигов
sudo tar czf /backup/wireguard-$(date +%F).tar.gz /etc/wireguard/

# Восстановление
sudo tar xzf /backup/wireguard-2025-01-15.tar.gz -C /
sudo systemctl restart wg-quick@wg0
```

### Развёртывание клиентов на десктопах и мобильных устройствах

WireGuard можно поднять вручную (`wg-quick`) либо через официальные клиенты. Для массового развёртывания удобен формат импорта конфига.

**Windows:**
- Установить клиент с [wireguard.com](https://www.wireguard.com/install/), импортировать `wg0.conf` (кнопка Import Tunnel). GUI создаёт сетевую адаптер и сохраняет пин-код.
- При поднятии tunnel Windows убирает Office DNS-правила: указывайте `DNS` явно в конфиге, иначе после подключения могут перестать резолвиться внешние имена (классический баг).

**macOS:**
- Официальный клиент из App Store; аналогичный импорт конфига.
- Для конфигурации через system профили (роскошный rollout) используется `wireguard-go`-режим или расширение Network Extension. При проблемах с DNS — проверьте порядок в `scutil --dns` и деликатно пропишите серверные резолверы (см. [vpn-dns.md](./vpn-dns.md)).

**iOS / Android:**
- Официальные приложения WireGuard (без root на Android). Конфиг передаётся QR-кодом (в приложении Scan from QR) — этим пользуются панели вроде wg-easy (см. [wireguard-key-management.md](./wireguard-key-management.md)).
- Мобильные клиенты не поддерживают запуск `PostUp/PostDown`, поэтому правила Nat/firewall на клиенте надо задавать статически либо отказаться от них (Stateful и DNS-специфика — в [vpn-dns.md](./vpn-dns.md)).

**Практическая проверка клиента:**

```bash
# Linux-клиент: статус пира
sudo wg show wg0
# → peer: <server_pubkey>
# →   endpoint: 203.0.113.1:51820
# →   allowed ips: 10.0.0.0/24
# →   latest handshake: 2 seconds ago
# →   transfer: 12.3 MiB received, 4.5 MiB sent
```

Массовое развёртывание конфигов на флот (Ansible, GitOps) — [VPN Automation](../Networking/Tunnels/vpn_automation.md).

### Интеграция с мониторингом

WireGuard не предоставляет встроенных метрик, но состояние можно получить через `wg show` и экспортировать в Prometheus или другие системы мониторинга.

**Пример скрипта экспорта метрик (Python):**

```python
#!/usr/bin/env python3
import subprocess
import re
import time

def parse_wg_show():
    result = subprocess.run(['sudo', 'wg', 'show'], capture_output=True, text=True)
    output = result.stdout

    metrics = []
    current_interface = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith('interface:'):
            current_interface = line.split(':')[1].strip()
        elif line.startswith('peer:'):
            peer = line.split(':')[1].strip()
        elif 'latest handshake:' in line:
            handshake = line.split(':')[1].strip()
            # Конвертация в timestamp
            metrics.append(f'wireguard_handshake_seconds{{interface="{current_interface}",peer="{peer}"}} {handshake}')
        elif 'transfer:' in line:
            rx, tx = line.split(':')[1].strip().split(',')
            metrics.append(f'wireguard_transfer_bytes{{interface="{current_interface}",peer="{peer}",direction="rx"}} {rx.split()[0]}')
            metrics.append(f'wireguard_transfer_bytes{{interface="{current_interface}",peer="{peer}",direction="tx"}} {tx.split()[0]}')

    return '\n'.join(metrics)

print(parse_wg_show())
```

**Exporter systemd service:**

```ini
[Unit]
Description=WireGuard Prometheus Exporter
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/wg_exporter.py
Restart=always

[Install]
WantedBy=multi-user.target
```

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

### Анализ трафика

Для более детального анализа сетевого трафика, включая WireGuard, можно использовать `tcpdump` или Wireshark. Подробнее см. [Wireshark и анализ сетевого трафика](../Networking/ServicesAndTools/Wireshark/definitions.md).

```bash
# Прослушивание трафика на интерфейсе wg0, порт 22 (SSH)
sudo tcpdump -i wg0 port 22

# Прослушивание всего UDP трафика на порту 51820 (стандартный порт WireGuard)
sudo tcpdump -i any udp port 51820
```

### Проверка работы таймера обновления Endpoint

```bash
# Проверить статус таймера:
systemctl list-timers | grep wg-rebind

# Посмотреть логи выполнения сервиса:
journalctl -u wg-rebind.service -f
```

## Лучшие практики

### Безопасность

1. **Хранение приватных ключей:**
   ```bash
   # Права доступа 600 (только root)
   sudo chmod 600 /etc/wireguard/private.key

   # Или использовать параметр конфигурации
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
   nft add rule inet filter input udp dport 51820 ip saddr { 198.51.100.0/24, 203.113.0/24 } accept
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

## Граничные случаи и ограничения

1. **WireGuard не поддерживает мультикаст:** В отличие от GRE, WireGuard не может передавать multicast-трафик. Для multicast используйте GRE или VXLAN.

2. **Нет встроенного keepalive:** WireGuard не отправляет keepalive-пакеты по умолчанию. При работе через NAT необходимо задавать `PersistentKeepalive = 25`.

3. **Одна сессия на пару ключей:** WireGuard не поддерживает несколько параллельных сессий между одними и теми же ключами. При смене IP Endpoint автоматически обновляется.

4. **Нет PKI (инфраструктуры открытых ключей):** WireGuard не имеет встроенного CA. Для масштабирования (>50 хостов) требуется внешний PKI или автоматизация ключей.

5. **MTU:** WireGuard добавляет 60 байт оверхеда. При стеке протоколов (VXLAN + WireGuard) MTU должен быть уменьшен до 1360.

6. **Производительность в контейнерах:** В Docker/Kubernetes WireGuard требует `--cap-add=NET_ADMIN` и доступа к `/dev/net/tun`.

7. **Windows/macOS:** Клиенты WireGuard доступны для всех ОС, но конфигурация отличается (используется GUI или `wg-quick` через WSL).

8. **Ограничение на количество пиров:** В одном конфигурационном файле может быть до 256 пиров (ограничение реализации). Для большего количества требуется несколько интерфейсов или внешний контроллер.

## Дополнительная информация

### Связанные документы

- **[WireGuard — практическое руководство](../Networking/Tunnels/wireguard_practical.md)** — site-to-site и remote access сценарии
- **[GRE vs WireGuard](../Networking/Tunnels/gre/gre_vs_wireguard.md)** — сравнение протоколов, критерии выбора, миграция GRE→WireGuard
- **[VPN Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md)** — универсальный чек-лист диагностики
- **[VPN в контейнерах](../Networking/Tunnels/vpn_in_containers.md)** — Docker и Kubernetes
- **[VPN Automation — Ansible и Terraform](../Networking/Tunnels/vpn_automation.md)** — управление конфигурацией через IaC
- **[NAT и VPN](../Networking/Concepts/nat/nat_and_vpn.md)** — работа WireGuard за NAT, PersistentKeepalive, CGNAT
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead и MSS Clamping
- **[OpenVPN](../Networking/Tunnels/openvpn.md)** — классический альтернативный протокол (PKI, TCP 443)
- **[IPsec (IKEv2)](../Networking/Tunnels/ipsec/ipsec.md)** — альтернатива для enterprise с EAP-RADIUS
- **[Remote Access VPN — выбор](../Networking/Tunnels/remote_access_vpn.md)** — WireGuard vs OpenVPN vs IPsec: когда что брать
- **[Расширенная маршрутизация WireGuard](./wireguard-routing.md)** — PBR, fwmark, OSPF/BGP поверх туннеля
- **[IPv6 внутри VPN](./vpn-ipv6.md)** — адресация, dual-stack, IPv6 firewall
- **[Аудит сессий VPN](./vpn-session-audit.md)** — журналирование подключений, NFLOG, RADIUS accounting
- **[Mesh-VPN решения](./mesh-vpn-overview.md)** — Nebula, Netbird, Netmaker
- **[VPN под DPI](./vpn-dpi-obfuscation.md)** — работа в ограничивающих сетях, обфускация
- **[Zero Trust](../Networking/Concepts/zero_trust_overview.md)** — модель доступа, при которой VPN не единственный слой
- **[Proxy vs VPN](../Networking/Concepts/proxy-vs-vpn.md)** — когда туннель, а когда прокси
- **[SSH-туннели и bastion](../Linux/Security/ssh/ssh_usage_and_tunnels.md)** — доступ-+выход через промежуточные узлы
- **[Rosenpass: Постквантовая защита для WireGuard](./rosenpass_overview.md)** — интеграция постквантовой криптографии
- **[WireGuard — высокая доступность](./wireguard-ha.md)** — Active/Passive концентратор, Keepalived, ECMP/Anycast
- **[WireGuard — управление ключами](./wireguard-key-management.md)** — флот клиентов, PKI/Vault, web-панели
- **[WireGuard — производительность и тюнинг](./wireguard-performance.md)** — kernel vs userspace, MTU/MSS, RSS/RPS
- **[WireGuard — защита концентратора](./wireguard-security.md)** — rate limiting handshake, anti-DDoS, hardening
- **[VPN: мониторинг и алертинг](./vpn-monitoring.md)** — метрики, Blackbox Exporter, SLI/SLO
- **[DNS внутри VPN](./vpn-dns.md)** — split DNS, DNS over tunnel, MagicDNS
- **[Аутентификация и SSO/MFA для VPN](./vpn-authentication.md)** — OIDC, LDAP/RADIUS, TOTP
- **[iptables и Docker: интеграция и DOCKER-USER](../Docker/Docker_network/troubleshooting/iptables_integration.md)** — управление правилами фильтрации для контейнеров
- **[Сетевые политики Docker](../Docker/Docker_network/docker_network_policies.md)** — Defense-in-Depth, `--internal` сети, отключение ICC
