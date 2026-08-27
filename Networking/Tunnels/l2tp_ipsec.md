# L2TP/IPsec — практическое руководство

## Определения

**L2TP/IPsec** — комбинация двух протоколов: **L2TP** (Layer 2 Tunneling Protocol) для туннелирования L2-кадров и **IPsec** (Internet Protocol Security) для шифрования и аутентификации. L2TP сам по себе не шифрует данные, поэтому всегда используется в связке с IPsec.

**Ключевые характеристики:**
- **Уровень:** L2 (туннель) + L3 (шифрование)
- **Транспорт:** UDP 1701 (L2TP), ESP/UDP 500/4500 (IPsec)
- **Шифрование:** IPsec ESP (AES-256-GCM)
- **Аутентификация:** IPsec (PSK или сертификаты) + L2TP (PPP: MSCHAPv2, EAP)
- **Overhead:** 57–73 байт (L2TP 4-8 + IPsec ESP 40-65)

> **См. также:** [IPsec](./ipsec/ipsec.md), [TUN vs TAP](./tun_vs_tap.md), [MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)

---

## Предварительные требования

### Установка

```bash
# Debian/Ubuntu (xl2tpd + strongSwan)
sudo apt update && sudo apt install xl2tpd strongswan libcharon-extra-plugins

# RHEL/CentOS/Rocky (xl2tpd + libreswan)
sudo dnf install xl2tpd libreswan
```

### Модули ядра

```bash
# Проверка модуля L2TP
modinfo l2tp_core | head -3
# → filename: .../kernel/net/l2tp/l2tp_core.ko

modinfo l2tp_netlink | head -3
# → filename: .../kernel/net/l2tp/l2tp_netlink.ko

# Загрузка модулей
sudo modprobe l2tp_core
sudo modprobe l2tp_netlink
sudo modprobe l2tp_eth

# Проверка загруженности
lsmod | grep l2tp
# → l2tp_netlink           16384  0
# → l2tp_core              28672  1 l2tp_netlink
```

---

## Основные концепции

### Архитектура стека

```
┌─────────────────────────────────────────┐
│           Приложение (TCP/UDP)          │
├─────────────────────────────────────────┤
│           PPP (L2TP Session)           │  ← L2TP добавляет PPP-заголовок
├─────────────────────────────────────────┤
│           L2TP (UDP 1701)              │  ← L2TP туннель
├─────────────────────────────────────────┤
│           IPsec ESP (UDP 4500)         │  ← Шифрование IPsec
├─────────────────────────────────────────┤
│           IPv4/IPv6                    │
└─────────────────────────────────────────┘
```

### Сравнение с другими VPN

| Параметр | L2TP/IPsec | WireGuard | OpenVPN | IPsec (чистый) |
|----------|------------|-----------|---------|----------------|
| **Уровень** | L2 | L3 | L2/L3 | L3 |
| **Шифрование** | IPsec ESP | ChaCha20 | OpenSSL | ESP |
| **Overhead** | 57–73 байт | 60 байт | 57–73 байт | 50–73 байт |
| **NAT Traversal** | NAT-T (UDP 4500) | UDP 51820 | TCP 443 | NAT-T |
| **Аутентификация** | PPP (MSCHAPv2, EAP) | Статические ключи | PKI, LDAP | PKI, PSK, EAP |
| **Производительность** | ~500 Mbps | ~7.8 Gbps | ~1 Gbps | ~5.2 Gbps |
| **Нативная поддержка ОС** | Все ОС (встроена) | Linux 5.6+, Win 10+ | Требует клиента | Все ОС |

---

## Практические сценарии

### Сервер L2TP/IPsec (Linux)

#### Шаг 1: Настройка IPsec (strongSwan)

```bash
# /etc/swanctl/conf.d/l2tp-ipsec.conf
connections {
    l2tp-server {
        version = 2
        local_addrs = 198.51.100.1
        proposals = aes256-sha256-modp2048

        dpd_delay = 30s

        local {
            auth = psk
            id = 198.51.100.1
        }
        remote {
            auth = psk
            id = %any
        }

        children {
            l2tp {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256-sha256
                start_action = trap
            }
        }
    }
}

secrets {
    ike-l2tp {
        secret = "V3ryStr0ngPSK!"
    }
}
```

```bash
# Загрузка конфигурации
sudo swanctl --load-all
```

#### Шаг 2: Настройка xl2tpd

```bash
# /etc/xl2tpd/xl2tpd.conf
[global]
port = 1701
auth file = /etc/ppp/chap-secrets

[lns default]
ip range = 10.10.10.2-10.10.10.100
local ip = 10.10.10.1
require chap = yes
refuse pap = no
require authentication = yes
name = l2tp-server
ppp debug = yes
pppoptfile = /etc/ppp/options.l2tpd.server
length bit = yes
```

#### Шаг 3: Настройка PPP

```bash
# /etc/ppp/options.l2tpd.server
name l2tp-server
require-chap
ms-dns 8.8.8.8
ms-dns 8.8.4.4
asyncmap 0
auth
hide-password
idle 1800
mtu 1400
mru 1400
nodefaultroute
proxyarp
lock
connect-delay 5000
```

#### Шаг 4: Учётные данные клиентов

```bash
# /etc/ppp/chap-secrets
# user      server    password          IP-address
client1     l2tp-server   "P4ssw0rd!"    *
client2     l2tp-server   "S3cureP4ss!"  *
```

#### Шаг 5: Firewall

```bash
# nftables
# Разрешить L2TP (UDP 1701)
nft add rule inet filter input udp dport 1701 accept

# Разрешить IPsec
nft add rule inet filter input ip protocol esp accept
nft add rule inet filter input udp dport 500 accept
nft add rule inet filter input udp dport 4500 accept

# Маскарад для клиентов
nft add rule inet nat postrouting oifname "eth0" ip saddr 10.10.10.0/24 masquerade
```

#### Шаг 6: Запуск

```bash
# Запуск IPsec
sudo systemctl enable strongswan
sudo systemctl start strongswan

# Запуск L2TP
sudo systemctl enable xl2tpd
sudo systemctl start xl2tpd

# Проверка
sudo swanctl --list-sas
# → l2tp: #1, ESTABLISHED, IKEv2, ...
```

### Клиент L2TP/IPsec

#### Windows (встроенная поддержка)

```
1. Параметры → Сеть и Интернет → VPN → Добавить VPN-подключение
2. Провайдер: Windows (встроенный)
3. Тип подключения: L2TP/IPsec с предварительным ключом
4. Имя сервера: vpn.example.com
5. Ключ предварительной аутентификации: V3ryStr0ngPSK!
6. Имя пользователя: client1
7. Пароль: P4ssw0rd!
```

#### Linux (xl2tpd + strongSwan)

```bash
# /etc/ipsec.conf
conn %default
    ikelifetime=60m
    keylife=20m
    rekeymargin=3m
    keyingtries=1
    keyexchange=ikev2
    authby=secret
    type=transport

conn l2tp-client
    left=%defaultroute
    leftprotoport=17/1701
    right=198.51.100.1
    rightprotoport=17/1701
    auto=add
```

```bash
# /etc/ipsec.secrets
198.51.100.1 %any : PSK "V3ryStr0ngPSK!"
```

```bash
# /etc/xl2tpd/xl2tpd.conf
[lns default]
ip range = 10.10.10.2-10.10.10.100
local ip = 10.10.10.1
require chap = yes
refuse pap = no
require authentication = yes
name = l2tp-server
```

```bash
# Запуск
sudo systemctl enable xl2tpd strongswan
sudo systemctl start xl2tpd strongswan

# Подключение
sudo ipsec up l2tp-client
sudo systemctl restart xl2tpd

# Проверка
ip addr show l2tpeth0
# → l2tpeth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1400 ...
# →     inet 10.10.10.2/24 scope global l2tpeth0
```

---

## Диагностика

### Базовые команды

```bash
# Просмотр IPsec SA
sudo swanctl --list-sas

# Просмотр L2TP туннелей
sudo ip l2tp show tunnel
# → Tunnel 1, encap UDP
# →   From 198.51.100.1 to 203.0.113.2
# →   Peer tunnel 1
# →   UDP source / dest ports: 1701/1701
# →   ...
```

### Типичные ошибки

| Симптом | Вероятная причина | Решение |
|---------|-------------------|---------|
| **IPsec SA не устанавливается** | PSK не совпадает | Проверить `/etc/ipsec.secrets` на обоих концах |
| **IPsec UP, но L2TP не коннектится** | Firewall блокирует UDP 1701 | Разрешить UDP 1701 в rules |
| **L2TP коннектится, но нет IP** | PPP не может получить IP | Проверить `ip range` в xl2tpd.conf |
| **MTU проблемы** | L2TP + IPsec overhead | Установить `mtu 1400` в PPP options |
| **`CHAP authentication failed`** | Неверный логин/пароль | Проверить `/etc/ppp/chap-secrets` |

---

## Лучшие практики

### Безопасность

1. **Используйте сильный PSK:**
   ```bash
   # Генерация PSK
   openssl rand -base64 32
   # → V3ryStr0ngPSK!...
   ```

2. **Не используйте MSCHAPv2 без EAP:**
   ```bash
   # Вместо MSCHAPv2 используйте EAP-MSCHAPv2 или сертификаты
   ```

3. **Ограничьте IP-адреса сервера:**
   ```bash
   # В xl2tpd.conf
   lns default
       lac = 198.51.100.0/24  # Только доверенные клиенты
   ```

### MTU

L2TP/IPsec добавляет значительный overhead. Рекомендуемый MTU:

| Компонент | Overhead |
|-----------|----------|
| PPP Header | 8 байт |
| L2TP Header | 8 байт |
| UDP Header | 8 байт |
| IP Header | 20 байт |
| IPsec ESP Header | 8 байт |
| IPsec ESP Trailer + ICV | 32–52 байта |
| **Итого** | **84–104 байта** |

```bash
# Рекомендуемый MTU для L2TP/IPsec: 1400
# В PPP options:
mtu 1400
mru 1400
```

---

## Граничные случаи и ограничения

1. **Производительность:** L2TP/IPsec работает медленнее WireGuard или чистого IPsec из-за двойной инкапсуляции.

2. **NAT Traversal:** L2TP требует IPsec NAT-T (UDP 4500) для работы через NAT.

3. **Dual-stack:** L2TP поддерживает IPv4 и IPv6, но настройка IPv6 сложнее.

4. **Мультикаст:** L2TP не поддерживает multicast в standard-режиме.

5. **Совместимость:** L2TP/IPsec встроен во все ОС (Windows, macOS, iOS, Android), что делает его хорошим выбором для Remote Access.

6. **Замена:** В новых deployment рекомендуется WireGuard или чистый IPsec (IKEv2).

---

## Дополнительная информация

### Связанные документы

- **[IPsec](./ipsec/ipsec.md)** — детали IPsec, который используется для шифрования L2TP
- **[TUN vs TAP](./tun_vs_tap.md)** — виртуальные интерфейсы
- **[MTU и VPN](../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead
- **[WireGuard](./wireguard_practical.md)** — современная альтернатива L2TP/IPsec
- **[OpenVPN](./openvpn.md)** — ещё один вариант Remote Access VPN
