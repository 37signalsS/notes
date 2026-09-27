# Интеграция GRE с IPsec: защищённое туннелирование

## Определения и назначение

**GRE over IPsec (Generic Routing Encapsulation over IP Security)** — архитектурный подход к построению защищённых виртуальных сетей, объединяющий возможности протокола GRE (инкапсуляция любых L3-протоколов, поддержка мультикаста и динамической маршрутизации) с функциями безопасности стека IPsec (шифрование, контроль целостности и аутентификация).

Данная комбинация превращает классический Policy-based IPsec (основанный на правилах выбора трафика) в **Route-based VPN**. Это позволяет операционной системе рассматривать VPN-канал как обычный сетевой интерфейс, через который можно запускать протоколы маршрутизации (OSPF, BGP) и применять стандартные инструменты управления трафиком (QoS, Firewall).

**Ключевые характеристики:**

| Параметр | Значение |
|----------|----------|
| **Протокол транспорта** | IP 47 (GRE) поверх IP 50 (ESP) |
| **Порты управления** | UDP 500 (IKE), UDP 4500 (NAT-T) |
| **Режим IPsec** | Предпочтительно Transport Mode (для минимизации оверхеда) |
| **Топологии** | Site-to-Site, Hub-and-Spoke (DMVPN) |
| **Оверхед (Overhead)** | ~56–96 байт (зависит от режима и алгоритмов) |

---

## Архитектура и принципы работы

### Варианты инкапсуляции

Взаимодействие GRE и IPsec может быть реализовано в двух режимах, определяющих структуру результирующего пакета.

#### 1. Transport Mode (Транспортный режим) — Рекомендуемый

Используется, когда IPsec терминируется на тех же узлах, что и GRE-туннель. IPsec защищает только полезную нагрузку (заголовок GRE и данные внутри него).

*   **Структура пакета:** `[Внешний IP][ESP Header][GRE Header][Внутренний IP][Данные][ESP Trailer][ESP Auth]`
*   **Преимущество:** Минимальный оверхед (отсутствует дополнительный внешний IP-заголовок IPsec).
*   **Применение:** Два Linux-хоста, Cisco-to-Linux, Linux-to-MikroTik.

#### 2. Tunnel Mode (Туннельный режим)

Используется, если GRE-туннель проходит через промежуточные шлюзы IPsec. Исходный GRE-пакет целиком инкапсулируется в новый IP-пакет IPsec.

*   **Структура пакета:** `[Новый Внешний IP][ESP Header][Старый Внешний IP][GRE Header][Внутренний IP][Данные][ESP Trailer][ESP Auth]`
*   **Недостаток:** Увеличенный оверхед из-за двойного внешнего IP-заголовка.
*   **Применение:** GRE-туннель между двумя LAN, проходящий через промежуточные IPsec-шлюзы.

### Проблема MTU и расчёт оверхеда

Использование двух уровней инкапсуляции значительно снижает объём полезных данных в пакете.

**Пример расчёта оверхеда (физический MTU 1500, Transport Mode):**

| Уровень / Заголовок | Размер (байт) | Остаток MTU |
|---------------------|---------------|-------------|
| **Физический канал (Ethernet)** | — | 1500 |
| **Внешний IP-заголовок** | 20 | 1480 |
| **ESP Header + IV** | 16–24 | 1456 |
| **GRE Header** | 4–12 | 1444 |
| **Внутренний IP-заголовок** | 20 | 1424 |
| **ESP Trailer + ICV (Auth)** | 16–20 | **1404** |

**Пример расчёта оверхеда (физический MTU 1500, Tunnel Mode):**

| Уровень / Заголовок | Размер (байт) | Остаток MTU |
|---------------------|---------------|-------------|
| **Физический канал (Ethernet)** | — | 1500 |
| **Новый внешний IP** | 20 | 1480 |
| **ESP Header + IV** | 16–24 | 1456 |
| **Старый внешний IP** | 20 | 1436 |
| **GRE Header** | 4–12 | 1424 |
| **Внутренний IP-заголовок** | 20 | 1404 |
| **ESP Trailer + ICV (Auth)** | 16–20 | **1384** |

**Практические рекомендации:**
*   **Установка MTU:** На GRE-интерфейсе рекомендуется выставлять **1400** (Transport) или **1360** (Tunnel) байт.
*   **MSS Clamping:** Принудительное ограничение TCP MSS до **1360** (для MTU 1400) или ниже для предотвращения фрагментации.
*   **ICMP:** Разрешение сообщений `Destination Unreachable` (Fragmentation Needed) для корректной работы Path MTU Discovery.

---

## Современные методы реализации в Linux

### 1. VTI (Virtual Tunnel Interface)

Нативный для Linux (и Cisco) способ создания «чистого» интерфейса IPsec, который ведёт себя как GRE.

*   **Особенности:** Не требует явного создания GRE-туннеля; связывает интерфейс с политиками IPsec через `mark` (метки).
*   **Плюс:** Простота настройки маршрутизации.
*   **Минус:** Ограниченная поддержка мультикаста в некоторых реализениях.

### 2. XFRM Interfaces (xfrm-i)

Современный метод (ядро 4.19+), пришедший на смену VTI.

*   **Принцип:** Использует `if_id` для связки интерфейса с политиками (SPD) и состояниями (SAD).
*   **Преимущества:** Полная изоляция трафика, поддержка Network Namespaces, отсутствие проблем с «магическими» метками `mark`.

### 3. GRE + IPsec через strongSwan (XFRM с автоматической привязкой)

strongSwan может автоматически создавать и управлять XFRM-интерфейсами, привязанными к политкам IPsec. Это наиболее гибкий метод, позволяющий запускать маршрутизацию (OSPF/BGP) поверх защищённого GRE-канала.

---

## Практические сценарии настройки

### StrongSwan (IKEv2 / swanctl) — Полная конфигурация

#### Transport Mode (Linux-to-Linux)

Рекомендуемая конфигурация для Site-to-Site VPN между двумя Linux-хостами:

```hcl
# /etc/swanctl/conf.d/gre-ipsec.conf
connections {
    gre-ipsec {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        proposals = aes256gcm128-sha256-modp3072
        version = 2

        local {
            auth = psk
            id = 198.51.100.1
        }

        remote {
            auth = psk
            id = 203.0.113.2
        }

        children {
            gre-transport {
                local_ts = 198.51.100.1/32[gre]
                remote_ts = 203.0.113.2/32[gre]
                esp_proposals = aes256gcm128-sha256
                mode = transport
                start_action = trap
                dpd_action = restart
            }
        }
    }
}

secrets {
    ike-1 {
        secret = "V3ryStr0ngP4ssw0rd"
    }
}
```

#### Tunnel Mode (через промежуточные шлюзы)

```hcl
# /etc/swanctl/conf.d/gre-ipsec-tunnel.conf
connections {
    gre-ipsec-tunnel {
        remote_addrs = 198.51.100.2
        local_addrs = 10.0.0.1
        proposals = aes256gcm128-sha256-modp3072
        version = 2

        local {
            auth = psk
            id = 10.0.0.1
        }

        remote {
            auth = psk
            id = 198.51.100.2
        }

        children {
            gre-tunnel {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-sha256
                mode = tunnel
                start_action = trap
            }
        }
    }
}

secrets {
    ike-1 {
        secret = "V3ryStr0ngP4ssw0rd"
    }
}
```

#### Сертификатная аутентификация (Production)

Для промышленного использования вместо PSK рекомендуется сертификатная аутентификация:

```hcl
connections {
    gre-ipsec-cert {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        proposals = aes256gcm128-sha256-modp3072
        version = 2

        local {
            auth = x509
            id = gw1.example.com
            certs = /etc/swanctl/certs/gw1.crt
            publish = /etc/swanctl/certs/gw1.crt
        }

        remote {
            auth = x509
            id = gw2.example.com
            cacerts = /etc/swanctl/cacerts/ca.crt
        }

        children {
            gre-transport {
                local_ts = 198.51.100.1/32[gre]
                remote_ts = 203.0.113.2/32[gre]
                esp_proposals = aes256gcm128-sha256
                mode = transport
                start_action = trap
            }
        }
    }
}
```

### Cisco IOS (Классический GRE over IPsec)

Полная конфигурация на маршрутизаторе Cisco с IKEv2:

```cisco
! === Шаг 1: IKEv2 ===
crypto ikev2 proposal PROP1
 encryption aes-gcm-256
 prf sha256
 group 14

crypto ikev2 policy POL1
 proposal PROP1

crypto ikev2 keyring KEY1
 peer GATEWAY2
  address 203.0.113.2
  pre-shared-key V3ryStr0ngP4ssw0rd

crypto ikev2 profile PROF1
 match identity remote address 203.0.113.2 255.255.255.255
 identity local address 198.51.100.1
 authentication remote pre-share
 authentication local pre-share
 keyring local KEY1

! === Шаг 2: IPsec ===
crypto ipsec transform-set TSET esp-gcm 256
 mode transport

crypto ipsec profile IPSEC_PROF
 set transform-set TSET
 set ikev2-profile PROF1

! === Шаг 3: GRE-туннель ===
interface Tunnel0
 ip address 10.0.0.1 255.255.255.252
 ip mtu 1400
 ip tcp adjust-mss 1360
 tunnel source 198.51.100.1
 tunnel destination 203.0.113.2
 tunnel mode gre ip
 tunnel protection ipsec profile IPSEC_PROF
 no keepalive

! === Шаг 4: Маршрутизация ===
router ospf 1
 network 10.0.0.0 0.0.0.3 area 0
 network 192.168.1.0 0.0.0.255 area 0
```

**Важные моменты:**
*   `no keepalive` — отключает GRE keepalive на стороне Cisco при подключении к Linux-хосту (Linux не поддерживает Cisco-style keepalive).
*   `ip mtu 1400` + `ip tcp adjust-mss 1360` — предотвращают фрагментацию и «зависание» TCP.
*   `mode transport` в `transform-set` — экономит 20 байт оверхеда.

### MikroTik RouterOS (GRE over IPsec)

MikroTik RouterOS 7.x поддерживает построение защищённых GRE-туннелей через комбинацию IPsec и GRE-интерфейса. Данная схема превращает Policy-based IPsec в Route-based VPN, что позволяет запускать OSPF/BGP поверх защищённого канала.

**Когда использовать GRE over IPsec на MikroTik:**
*   Необходимость передачи мультикаста или broadcast-трафика между офисами.
*   Запуск динамической маршрутизации (OSPF, BGP) поверх VPN.
*   Прозрачное построение туннеля поверх IP-сети без изменения underlying infrastructure.

#### Transport Mode (рекомендуется)

На MikroTik IPsec терминируется на тех же узлах, что и GRE-туннель, поэтому применяется Transport Mode:

Структура пакета: `[Внешний IP][ESP Header][GRE Header][Внутренний IP][Данные]`

#### Полная конфигурация (Site-to-Site)

Сценарий: защищённый канал между головным офисом (gw-moscow) и филиалом (gw-spb).

| Узел | Внешний IP | Локальная сеть | GRE-адрес |
|------|-----------|---------------|-----------|
| gw-moscow | 172.16.150.10 | 192.168.21.0/24 | 10.10.1.1/30 |
| gw-spb | 172.16.150.2 | 192.168.50.0/24 | 10.10.1.2/30 |

**gw-moscow:**

```routeros
# === Moscow (gw-moscow) ===

# IPsec Profile (IKE SA)
/ip ipsec profile
add name=gre-ipsec-profile \
    hash-algorithm=sha256 \
    enc-algorithm=aes-256-gcm \
    dh-group=modp2048 \
    lifetime=86400 \
    nat-traversal=yes \
    dpd-interval=30s \
    dpd-maximum-failures=5

# IPsec Proposal (CHILD SA)
/ip ipsec proposal
add name=gre-ipsec-proposal \
    auth-algorithms=sha256 \
    enc-algorithms=aes-256-gcm \
    lifetime=3600 \
    pfs-group=modp2048

# IPsec Peer
/ip ipsec peer
add name=gw-spb \
    address=172.16.150.2 \
    profile=gre-ipsec-profile

# IPsec Identity (PSK + ID)
/ip ipsec identity
add peer=gw-spb \
    auth-method=pre-shared-key \
    secret="V3ryStr0ngP4ssw0rd" \
    id=moscow-id

# IPsec Policy
/ip ipsec policy
add src-address=192.168.21.0/24 \
    dst-address=192.168.50.0/24 \
    sa-src-address=172.16.150.10 \
    sa-dst-address=172.16.150.2 \
    proposal=gre-ipsec-proposal \
    action=encrypt \
    level=require

# GRE-туннель
/interface gre
add name=gre-to-spb \
    local-address=172.16.150.10 \
    remote-address=172.16.150.2 \
    mtu=1400 \
    dscp=inherit

# Адресация
/ip address
add address=10.10.1.1/30 interface=gre-to-spb

# Маршрут до филиала
/ip route
add dst-address=192.168.50.0/24 gateway=10.10.1.2

# Файрвол
/ip firewall filter
add chain=input protocol=gre src-address=172.16.150.2 action=accept \
    comment="Allow GRE from SPb"
add chain=input protocol=esp src-address=172.16.150.2 action=accept \
    comment="Allow ESP from SPb"
add chain=input protocol=udp src-address=172.16.150.2 dst-port=500 action=accept \
    comment="Allow IKE from SPb"
add chain=input protocol=udp src-address=172.16.150.2 dst-port=4500 action=accept \
    comment="Allow NAT-T from SPb"
```

**gw-spb:**

```routeros
# === SPb (gw-spb) ===

# IPsec Profile
/ip ipsec profile
add name=gre-ipsec-profile \
    hash-algorithm=sha256 \
    enc-algorithm=aes-256-gcm \
    dh-group=modp2048 \
    lifetime=86400 \
    nat-traversal=yes \
    dpd-interval=30s \
    dpd-maximum-failures=5

# IPsec Proposal
/ip ipsec proposal
add name=gre-ipsec-proposal \
    auth-algorithms=sha256 \
    enc-algorithms=aes-256-gcm \
    lifetime=3600 \
    pfs-group=modp2048

# IPsec Peer
/ip ipsec peer
add name=gw-moscow \
    address=172.16.150.10 \
    profile=gre-ipsec-profile

# IPsec Identity
/ip ipsec identity
add peer=gw-moscow \
    auth-method=pre-shared-key \
    secret="V3ryStr0ngP4ssw0rd" \
    id=spb-id

# IPsec Policy
/ip ipsec policy
add src-address=192.168.50.0/24 \
    dst-address=192.168.21.0/24 \
    sa-src-address=172.16.150.2 \
    sa-dst-address=172.16.150.10 \
    proposal=gre-ipsec-proposal \
    action=encrypt \
    level=require

# GRE-туннель
/interface gre
add name=gre-to-moscow \
    local-address=172.16.150.2 \
    remote-address=172.16.150.10 \
    mtu=1400 \
    dscp=inherit

# Адресация
/ip address
add address=10.10.1.2/30 interface=gre-to-moscow

# Маршрут до головного офиса
/ip route
add dst-address=192.168.21.0/24 gateway=10.10.1.1

# Файрвол
/ip firewall filter
add chain=input protocol=gre src-address=172.16.150.10 action=accept \
    comment="Allow GRE from Moscow"
add chain=input protocol=esp src-address=172.16.150.10 action=accept \
    comment="Allow ESP from Moscow"
add chain=input protocol=udp src-address=172.16.150.10 dst-port=500 action=accept \
    comment="Allow IKE from Moscow"
add chain=input protocol=udp src-address=172.16.150.10 dst-port=4500 action=accept \
    comment="Allow NAT-T from Moscow"
```

#### Двусторонняя статическая маршрутизация

Типичная ошибка — настройка маршрута только с одной стороны. Без ответного маршрута пакет доходит до удалённого офиса, но ответный трафик возвращается через underlay или не уходит вовсе.

Правило: если на gw-moscow настроен маршрут `192.168.50.0/24 → gre-to-spb`, то на gw-spb должен быть маршрут `192.168.21.0/24 → gre-to-moscow`.

#### Проверка работоспособности

```routeros
# Статус IPsec
/ip ipsec active-peers print
/ip ipsec installed-sa print

# Статус GRE
/interface gre print detail

# Маршруты
/ip route print where gateway~"10.10.1"

# Пинг
/tool ping 10.10.1.2
/tool ping 192.168.50.1
```

#### Устранение неисправностей

**Ошибка: пинги до удалённой подсети идут, а ответный трафик не возвращается**

Причина: отсутствует ответный статический маршрут или указан неверный шлюз.

Диагностика:
```routeros
/ip route print where dst-address~"192.168"
```

Решение: убедиться, что маршрут на удалённом узле указывает на GRE-интерфейс, а не на внешний IP.

**Ошибка: IPsec SA поднята, GRE интерфейс UP, но трафик не идёт**

Причина: несовпадение Traffic Selectors или отсутствие маршрута.

Диагностика:
```routeros
/ip ipsec policy print
/ip ipsec active-peers print
```

Решение: проверить, что `src-address`/`dst-address` в политике совпадают с реальными подсетями.

**Ошибка: выбран неверный шлюз для маршрута**

Причина: в MikroTik при настройке маршрута в выпадающем списке интерфейсов может отображаться не GRE-интерфейс, а IPsec-интерфейс.

Решение: явно указать GRE-интерфейс в качестве шлюза для маршрута до удалённой подсети.

**Ошибка: GRE туннель поднимается, но пинги между офисами не проходят**

Причина: IPsec не защищает трафик из-за несовпадения proposals или отсутствия DPD.

Диагностика:
```routeros
/ip ipsec active-peers print
/ip firewall connection print
```

Решение: синхронизировать proposals на обеих сторонах, включить DPD.

#### Лучшие практики

*   **Transport Mode:** предпочтителен для минимизации оверхеда (20 байт против Tunnel Mode).
*   **MTU:** на GRE-интерфейсе выставлять `mtu=1400` для компенсации оверхеда ESP.
*   **Аутентификация:** использовать PSK с явным указанием `id` на обеих сторонах.
*   **Статическая маршрутизация:** настраивать двусторонние маршруты до локальных подсетей через GRE-интерфейс.
*   **DPD:** включить `dpd-interval` для быстрого обнаружения разрыва туннеля.

### VTI (Virtual Tunnel Interface) — Полная настройка

VTI позволяет создать виртуальный интерфейс, связанный с политикой IPsec, без явного GRE-заголовка.

**Linux (strongSwan + VTI):**

```hcl
# /etc/swanctl/conf.d/vti.conf
connections {
    vti-conn {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        proposals = aes256gcm128-sha256-modp3072
        version = 2

        local { auth = psk }
        remote { auth = psk }

        children {
            vti-child {
                local_ts = 0.0.0.0/0
                remote_ts = 0.0.0.0/0
                esp_proposals = aes256gcm128-sha256
                mode = tunnel
                start_action = trap
                if_id_in = 1
                if_id_out = 1
            }
        }
    }
}

secrets {
    ike-1 { secret = "V3ryStr0ngP4ssw0rd" }
}
```

```bash
# Загрузка конфигурации
sudo swanctl --load-all

# Ручной запуск туннеля
sudo swanctl --initiate --child vti-child

# Создание VTI-интерфейса (после поднятия туннеля)
sudo ip link add vti0 type vti local 198.51.100.1 remote 203.0.113.2 key 1
sudo ip addr add 10.0.0.1/30 dev vti0
sudo ip link set vti0 up
sudo ip link set vti0 mtu 1400

# Добавление маршрута
sudo ip route add 192.168.2.0/24 via 10.0.0.2 dev vti0
```

**Cisco (VTI):**

```cisco
crypto ikev2 profile PROF1
 ...
 match identity remote address 203.0.113.2 255.255.255.255
 identity local address 198.51.100.1
 authentication remote pre-share
 authentication local pre-share
 keyring local KEY1

crypto ipsec profile IPSEC_PROF
 set transform-set TSET
 set ikev2-profile PROF1

interface Tunnel0
 ip address 10.0.0.1 255.255.255.252
 tunnel mode ipsec ipv4
 tunnel source 198.51.100.1
 tunnel destination 203.0.113.2
 tunnel protection ipsec profile IPSEC_PROF
```

### XFRM Interfaces — Полная настройка

XFRM-интерфейсы — современная замена VTI. Каждый интерфейс привязывается к политикам IPsec через `if_id`.

**Linux (strongSwan + XFRM):**

```hcl
# /etc/swanctl/conf.d/xfrm.conf
connections {
    xfrm-conn {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        proposals = aes256gcm128-sha256-modp3072
        version = 2

        local { auth = psk }
        remote { auth = psk }

        children {
            xfrm-child {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-sha256
                mode = tunnel
                start_action = trap
                if_id_in = 10
                if_id_out = 10
            }
        }
    }
}

secrets {
    ike-1 { secret = "V3ryStr0ngP4ssw0rd" }
}
```

```bash
# Загрузка конфигурации
sudo swanctl --load-all

# Создание XFRM-интерфейса (ID=10 должен совпадать с if_id в swanctl.conf)
sudo ip link add xfrm0 type xfrm dev eth0 if_id 10
sudo ip addr add 10.0.0.1/30 dev xfrm0
sudo ip link set xfrm0 up
sudo ip link set xfrm0 mtu 1400

# Добавление маршрута
sudo ip route add 192.168.2.0/24 via 10.0.0.2 dev xfrm0

# Проверка привязки
ip xfrm policy | grep if_id
```

### Решение проблем MTU и MSS в GRE+IPsec

Инкапсуляция ESP добавляет оверхед (от 50 до 73 байт). Для стабильной работы TCP необходимо:

```bash
# MSS Clamping через iptables
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --clamp-mss-to-pmtu

# Жёсткая установка MSS (для MTU 1400 → MSS = 1400 - 40 = 1360)
sudo iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
    -o gre0 -j TCPMSS --set-mss 1360

# nftables
nft add rule inet filter forward oifname "gre0" tcp flags syn \
    tcp option maxseg size set rt mtu
```

### Настройка файрвола

GRE+IPsec требует разрешения нескольких протоколов:

```bash
# nftables (рекомендуется)
nft add rule inet filter input ip saddr 203.0.113.2 ip protocol esp accept
nft add rule inet filter input ip saddr 203.0.113.2 udp dport 500 accept
nft add rule inet filter input ip saddr 203.0.113.2 udp dport 4500 accept
nft add rule inet filter input ip saddr 203.0.113.2 ip protocol gre accept

# iptables (legacy)
sudo iptables -A INPUT -s 203.0.113.2 -p esp -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.2 -p udp --dport 500 -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.2 -p udp --dport 4500 -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.2 -p 47 -j ACCEPT
```

### Постоянная конфигурация (Persistence)

**systemd-networkd (XFRM):**

Файл `/etc/systemd/network/30-xfrm.netdev`:
```ini
[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=10
Parent=eth0
```

Файл `/etc/systemd/network/30-xfrm.network`:
```ini
[Match]
Name=xfrm0

[Network]
Address=10.0.0.1/30

[Route]
Destination=192.168.2.0/24
Gateway=10.0.0.2
```

**Netplan (Ubuntu):**

```yaml
network:
  version: 2
  tunnels:
    xfrm0:
      mode: xfrm
      id: 10
      link: eth0
      addresses:
        - 10.0.0.1/30
      routes:
        - to: 192.168.2.0/24
          via: 10.0.0.2
```

---

## Диагностика и устранение неисправностей

### Пошаговый чек-лист

**Этап 1 — Проверка IPsec (IKE):**
```bash
# Статус ассоциаций strongSwan
sudo swanctl --list-sas

# Проверка загруженных конфигураций
sudo swanctl --list-conns

# Логи демона charon
sudo swanctl --log
sudo journalctl -u strongswan -f
```

**Этап 2 — Проверка IPsec (ядро / XFRM):**
```bash
# Security Associations Database (SAD)
ip xfrm state

# Security Policy Database (SPD)
ip xfrm policy

# Статистика пакетов (ошибки, дропы)
ip -s xfrm state

# Проверка конкретного SPI
ip xfrm state spi 0x12345678
```

**Этап 3 — Проверка GRE-интерфейса:**
```bash
# Статус интерфейса
ip link show gre0

# Детальная информация (Key, TTL, эндпоинты)
ip -d link show gre0

# Статистика
ip -s link show gre0

# Проверка маршрута
ip route get 10.0.0.2
```

**Этап 4 — Проверка прохождения трафика:**
```bash
# Анализ трафика (должны быть видны ESP-пакеты)
sudo tcpdump -i any host 203.0.113.2 -nn

# Проверка MTU через туннель
ping -M do -s 1372 10.0.0.2

# Трассировка маршрута
traceroute 192.168.2.1
```

### Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
|---------|-------------------|---------|
| `NO_PROPOSAL_CHOSEN` | Несовпадение алгоритмов шифрования | Синхронизировать `proposals`/`esp_proposals` на обеих сторонах |
| `AUTHENTICATION_FAILED` | Неверный PSK или ID сертификата | Проверить `secrets` и соответствие `local_id`/`remote_id` |
| `TS_UNACCEPTABLE` | Ошибка в Traffic Selectors (подсетях) | Убедиться, что `local_ts` совпадает с `remote_ts` на другой стороне |
| Туннель UP, трафик не идёт | Firewall блокирует ESP (IP 50) | Разрешить IP 50, UDP 500/4500 в файрволе |
| Туннель UP, TCP зависает | MSS превышает MTU туннеля | Настроить MSS Clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -o gre0 -j TCPMSS --clamp-mss-to-pmtu` |
| Интерфейс DOWN, пинг нет | GRE keepalive / проблема Underlay | Проверить `ip link show gre0`, пингануть `remote` IP |
| `XFRM吔制品找不到` | `if_id` не совпадает | Проверить `ip xfrm policy` — `if_id` должен совпадать с `if_id` в swanctl.conf |
| Ошибки `state expired` | Долгое простояние без трафика | Увеличить lifetime в swanctl.conf или настроить DPD (`dpd_action = restart`) |
| Дропы в `ip -s xfrm state` | Неверные ключи / SPI | Перезапустить strongSwan: `swanctl --load-all && swanctl --initiate --child <name>` |
| Мультикаст не работает | VTI не поддерживает multicast | Перейти на XFRM-интерфейсы или использовать GRE без IPsec для multicast |

---

## Дополнительная информация

### Сравнение с альтернативами

| Технология | Преимущества | Недостатки |
|------------|--------------|------------|
| **GRE over IPsec** | Универсальность, мультикаст, OSPF/BGP | Высокий оверхед, сложность отладки |
| **VTI / XFRM** | Упрощённая маршрутизация, нативная поддержка в Linux | Специфично для Linux/Cisco |
| **WireGuard** | Высокая производительность, низкий оверхед (~60 байт), нативное шифрование | Отсутствие формальной сертификации, нет мультикаста |
| **OpenVPN** | Проходит через любые Firewall (TCP), гибкая аутентификация | Низкая производительность (userspace), одно соединение на туннель |

### Связанные документы

*   [Протокол GRE](./gre.md) — базовый разбор заголовков и принципов GRE.
*   [GRE: практические сценарии](./gre_practical_scenarios.md) — настройка GRE-туннелей в Linux и Cisco.
*   [GRE vs WireGuard](./gre_vs_wireguard.md) — сравнение протоколов, критерии выбора.
*   [Мониторинг GRE](./gre_monitoring.md) — наблюдаемость, Prometheus, алертинг.
*   [IPsec (основной документ)](../ipsec/ipsec.md) — архитектура IKEv2, настройка strongSwan, XFRM.
*   [MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — диагностика и решение проблем фрагментации.
