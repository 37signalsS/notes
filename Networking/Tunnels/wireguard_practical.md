# WireGuard — практическое руководство в контексте туннелей

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x)

Практическое руководство по развёртыванию WireGuard в типовых сетевых сценариях. Теоретическая часть (протокол рукопожатия `Noise_IKpsk2`, криптография, модель `cryptokey routing`), форматы конфигурации, диагностика, тюнинг MTU и граничные случаи собраны в хабе [Vpn/wireguard.md](../../Vpn/wireguard.md); здесь — пошаговые сценарии, которых там нет.

> **См. также:** [Протокол WireGuard (детали протокола)](../../Vpn/wireguard.md), [GRE vs WireGuard](./gre/gre_vs_wireguard.md), [Сравнение VPN-технологий](./tunneling_overview.md)

---

## Предварительные требования

Общая подготовка — установка пакетов, проверка модуля ядра, включение IP-форвардинга и генерация ключей — описана в [Vpn/wireguard.md](../../Vpn/wireguard.md#практические-сценарии). Для сценариев ниже необходимы:

- WireGuard на всех узлах (модуль ядра Linux либо userspace-клиент);
- `net.ipv4.ip_forward = 1` на шлюзах, маршрутизирующих транзитный трафик;
- UDP-порт (по умолчанию `51820`) открыт между узлами; ключи сгенерированы (`wg genkey` / `wg pubkey`).

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

# PostUp/PostDown: iptables-правила для маршрутизации и NAT
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

**Задача:** Инкапсулировать GRE-туннель внутрь WireGuard (GRE over WireGuard) — например, чтобы добавить шифрование и аутентификацию поверх уже существующей GRE-инфраструктуры.

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

Обратите внимание на MTU: GRE добавляет к заголовку ещё 24 байта, поэтому при вложенности общий MTU нужно уменьшать каскадно (расчёт — [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)).

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

## Дополнительная информация

Диагностика, типичные ошибки, тюнинг MTU, лучшие практики и граничные случаи — в [Vpn/wireguard.md](../../Vpn/wireguard.md) (разделы [Диагностика](../../Vpn/wireguard.md#диагностика), [Лучшие практики](../../Vpn/wireguard.md#лучшие-практики), [Граничные случаи и ограничения](../../Vpn/wireguard.md#граничные-случаи-и-ограничения)).

### Связанные документы

- **[Протокол WireGuard (детали протокола)](../../Vpn/wireguard.md)** — криптография, `Noise_IKpsk2` handshake, dynamic IP rebinding
- **[GRE vs WireGuard](./gre/gre_vs_wireguard.md)** — сравнение протоколов, критерии выбора, миграция GRE→WireGuard
- **[IPsec vs WireGuard](./ipsec/ipsec.md#расширенное-сравнение-vpn)** — когда выбирать IPsec вместо WireGuard
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead и MSS Clamping
- **[NAT и VPN](../Concepts/nat/nat_and_vpn.md)** — работа WireGuard за NAT, PersistentKeepalive, CGNAT
- **[VPN и Service Mesh](../Concepts/vpn_vs_service_mesh.md)** — practical site-to-site пример с PostUp/PostDown
- **[WireGuard в Cilium](../../Kubernetes/Networking/Network/CNI/cilium.md)** — шифрование трафика в Kubernetes
