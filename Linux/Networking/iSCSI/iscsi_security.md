# iSCSI: Безопасность и аутентификация

Руководство по защите iSCSI-инфраструктуры: аутентификация, сетевая изоляция, шифрование и контроль доступа.

## Определения и сокращения

| Термин | Описание |
| :--- | :--- |
| **CHAP (Challenge-Handshake Authentication Protocol)** | Протокол аутентификации по логину/паролю. Поддерживается на уровне iSCSI (RFC 7143). Использует MD5 для хеширования. |
| **Mutual CHAP** | Взаимная аутентификация: таргет проверяет инициатор, а инициатор — таргет. Защищает от подмены сервера. |
| **ACL (Access Control List)** | Список IQN инициаторов, которым разрешён доступ к конкретной TPG. Управляется через `targetcli`. |
| **LUN Masking** | Ограничение видимости LUN для конкретного инициатора после установки сессии. Дополняет ACL, но не заменяет его. |
| **IPsec (Internet Protocol Security)** | Набор протоколов для шифрования IP-трафика на сетевом уровне (L3). ESP — шифрование + целостность, AH — только целостность. |
| **IKEv2 (Internet Key Exchange v2)** | Протокол согласования ключей для IPsec. Рекомендуется вместо IKEv1 (RFC 7296). |
| **WireGuard** | Современный VPN-протокол (Linux 5.6+). ChaCha20-Poly1305, Curve25519. Альтернатива IPsec для шифрования iSCSI. |
| **VLAN (Virtual LAN)** | Логическая изоляция сетевого трафика на уровне коммутатора (802.1Q). |
| **TPG (Target Portal Group)** | Группа порталов и настроек доступа (ACL, CHAP) внутри одного таргета. |
| **SELinux (Security-Enhanced Linux)** | Мандатная модель контроля доступа в ядре Linux. Ограничивает права процессов на уровне MAC. |
| **AppArmor** | Профильная модель контроля доступа (Ubuntu/Debian). Ограничивает файловый доступ и сетевые операции процессов. |
| **auditd** | Демон аудита Linux. Регистрирует системные вызовы и изменения конфигурации. |
| **PKI (Public Key Infrastructure)** | Инфраструктура управления открытыми ключами и сертификатами X.509. |

## Модель угроз iSCSI

iSCSI-трафик передаётся по стандартным Ethernet-сетям и подвержен следующим атакам:

| Угроза | Описание | Метод защиты |
| :--- | :--- | :--- |
| **Подмена таргета (Spoofing)** | Атакующий выдаёт себя за легитимный iSCSI-сервер | Mutual CHAP, сертификаты IKEv2 |
| **Man-in-the-Middle (MITM)** | Перехват и модификация трафика между инициатором и таргетом | IPsec/WireGuard (шифрование), Mutual CHAP |
| **Перехват данных (Sniffing)** | Чтение блочных данных в транзите | IPsec/WireGuard, VLAN (изоляция) |
| **Несанкционированный доступ** | Подключение неавторизованных инициаторов к LUN | ACL по IQN, CHAP, LUN Masking |
| **Отказ в обслуживании (DoS)** | Заведение ложных сессий, переполнение очередей | Firewall, rate limiting, ACL |
| **Повреждение данных** | Изменение PDU при передаче (Silent Data Corruption) | Header/Data Digest (CRC32C) |
| **Подмена discovery** | Ответ на SendTargets от rogue-сервера, перенаправление на вредоносный таргет | Discovery с аутентификацией (CHAP), статическая запись |
| **Brute-force CHAP** | Перебор паролей CHAP через offline-анализ дампа | Длинные пароли (>16 символов), IPsec, ротация ключей |
| **IQN spoofing** | Подделка IQN инициатора для обхода ACL | Mutual CHAP (UNDLE 11), ACL + CHAP вместе |
| **LUN masking bypass** | Доступ к чужим LUN через ошибки конфигурации | Отключение `auto_add_mapped_luns`, проверка ACL |

## Аутентификация CHAP

### Как работает CHAP

1. Таргет отправляет инициатору **challenge** (случайное число)
2. Инициатор вычисляет **MD5(challenge + secret)** и отправляет ответ
3. Таргет проверяет ответ, сверяя с вычисленным значением

**Важно:** Пароль **не передаётся** по сети в открытом виде. Однако при использовании MD5 и коротких секретах возможна offline-атака.

### Односторонний CHAP (таргет проверяет инициатора)

Таргет запрашивает у инициатора логин и пароль. Инициатор отвечает, но не проверяет подлинность таргета.

#### Настройка на таргете (LIO, targetcli)

```bash
sudo targetcli
cd /iscsi/iqn.2026-07.com.example:storage.target01/tpg1

# Включить CHAP для конкретного ACL
cd acls/iqn.2026-07.com.example:initiator01
set auth userid=iscsi_user
set auth password=StrongP@ssw0rd!
```

#### Настройка на инициаторе (open-iscsi)

```bash
# CHAP настраивается ДО выполнения Login
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 -p 192.168.1.20 \
  -o update -n node.session.auth.authmethod -v CHAP

sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 -p 192.168.1.20 \
  -o update -n node.session.auth.username -v iscsi_user

sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 -p 192.168.1.20 \
  -o update -n node.session.auth.password -v 'StrongP@ssw0rd!'

# Теперь выполнить Login
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 -p 192.168.1.20 --login
```

### Взаимный CHAP (Mutual)

Инициатор также проверяет таргет, что защищает от подмены сервера хранения.

#### Настройка на таргете

```bash
cd /iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01
set auth mutual_userid=target_chap_user
set auth mutual_password=TargetStr0ngP@ss!
```

#### Настройка на инициаторе

```bash
# Установить credentials инициатора (односторонний CHAP)
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.authmethod -v CHAP

sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.username -v iscsi_user

sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.password -v 'StrongP@ssw0rd!'

# Установить credentials таргета (для mutual CHAP)
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.username_in -v target_chap_user

sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> -o update \
  -n node.session.auth.password_in -v 'TargetStr0ngP@ss!'
```

### Проверка конфигурации CHAP

```bash
# Просмотр текущих параметров аутентификации
sudo iscsiadm -m node -T <TARGET_IQN> -p <IP> | grep auth
# -> node.session.auth.authmethod = CHAP
# -> node.session.auth.username = iscsi_user
# -> node.session.auth.username_in = target_chap_user
```

### Ограничения CHAP и безопасность

| Параметр | Значение | Рекомендация |
| :--- | :--- | :--- |
| **Алгоритм хеширования** | MD5 (RFC 1994) | MD5 криптографически небезопасен; компенсируется длиной секрета и шифрованием канала |
| **Offline dictionary attack** | Возможен при перехвате challenge/response | Используйте пароли >16 символов, комбинируйте с IPsec |
| **Передача пароля** | Хеш MD5, не открытым текстом | При MITM атакующий может replay challenge/response (MITM) |
| **Длительность сессии** | Аутентификация только при Login | Нет непрерывной проверки; используйте IPsec для постоянного шифрования |
| **Хранение секретов** | Открытым текстом в `/etc/iscsi/iscsid.conf` и `saveconfig.json` | Ограничьте права доступа: `chmod 600 /etc/iscsi/iscsid.conf` |
| **Реuse секретов** | Один secret на все инициаторы — риск имперсонации | Уникальный пароль для каждого инициатора |

### Рекомендации по усилению CHAP

```bash
# 1. Генерация криптографически стойкого пароля
openssl rand -base64 32
# -> k7X9z2... (32 байта = 256 бит энтропии)

# 2. Ограничение прав на файлы с секретами
sudo chmod 600 /etc/iscsi/iscsid.conf
sudo chown root:root /etc/iscsi/iscsid.conf

# 3. Проверка, что пароль не хранится в истории команд
history | grep -i iscsiadm.*password
# Если найден — очистить: history -c
```

### Альтернативы CHAP

| Механизм | RFC | Статус в Linux | Описание |
| :--- | :--- | :--- | :--- |
| **CHAP** | RFC 1994, 3720 | Стандарт | Де-факто для iSCSI. MD5. |
| **SPKM (Simple Public Key Mechanism)** | RFC 3720 §11 | Не реализован | Аутентификация на основе открытых ключей. Нет поддержки в LIO/open-iscsi. |
| **SRP (Secure Remote Password)** | RFC 3720 §11.2.3 | Не реализован | Протокол zero-knowledge. Не передаёт пароль и хеш. |
| **Kerberos** | RFC 3720 §11 | Не реализован | Требует KDC. Используется в NFSv4, но не в iSCSI. |
| **IPsec + IKEv2 certificates** | RFC 7296 | Стандарт | Рекомендуется для production. Сертификатная аутентификация. |
| **WireGuard** | Linux 5.6+ | Стандарт | Криптографические ключи вместо логинов. |

**Вывод:** В Linux-стеке iSCSI альтернатив CHAP фактически нет. Для production рекомендуется **CHAP + IPsec/WireGuard** как многоуровневая защита.

## LUN Masking vs ACL

Два механизма контроля доступа, которые работают на разных уровнях и **дополняют** друг друга:

### ACL (Access Control List)

- **Уровень:** iSCSI сессия (Login Phase)
- **Что контролирует:** Какие IQN-инициаторы **могут подключиться** к TPG
- **Управление:** `targetcli /iscsi/.../tpg1/acls/`
- **По умолчанию:** Все IQN запрещены (только явно добавленные разрешены)

### LUN Masking

- **Уровень:** LUN (после установки сессии)
- **Что контролирует:** Какие LUN **видны** конкретному инициатору
- **Реализация:**
  - На уровне массива (igroups в NetApp, masking views в Dell EMC)
  - На уровне LIO: `auto_add_mapped_luns` attribute
  - На уровне ОС/HBA: host-side фильтрация

### Различия

| Критерий | ACL | LUN Masking |
| :--- | :--- | :--- |
| **Когда действует** | При Login (до установки сессии) | После Login (во время I/O) |
| **Контролирует** | Доступ к TPG (portal group) | Доступ к конкретным LUN |
| **Фильтрация** | По IQN инициатора | По LUN ID |
| **Управление** | `targetcli acls` | `targetcli luns` / array mgmt |
| **Рекомендация** | Обязателен для всех сред | Рекомендуется для multi-tenant |

### Настройка LUN Masking в LIO

```bash
# Отключить автоматическую маппингу всех LUN для всех ACL
# (по умолчанию auto_add_mapped_luns=1 — небезопасно)
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 set attribute \
  auto_add_mapped_luns=0

# Явно замапить только нужные LUN для конкретного ACL
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns create \
  /backstores/block/disk01 \
  /iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01
```

### Проверка текущих маппингов

```bash
# Просмотр всех LUN, замапленных для ACL
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01 ls
# -> luns/
#     -> 0/ -> /backstores/block/disk01
```

## Сетевая изоляция

### VLAN для iSCSI-трафика

Выделение отдельного VLAN для блочного трафика хранения — базовая практика изоляции.

#### Настройка на коммутаторе (пример)

```
vlan 200
 name iSCSI-SAN
!
interface GigabitEthernet0/1
 switchport mode access
 switchport access vlan 200
 spanning-tree portfast
```

#### Настройка на Linux-хосте (netplan)

```yaml
# /etc/netplan/60-iscsi.yaml
network:
  version: 2
  ethernets:
    eth1:
      addresses: [192.168.200.10/24]
      routes:
        - to: 192.168.200.0/24
          via: 192.168.200.1
```

#### Настройка на Linux-хосте (NetworkManager)

```bash
sudo nmcli con add type ethernet con-name iSCSI \
  ifname eth1 ip4 192.168.200.10/24 \
  802.1q.id 200
```

### Лучшие практики сегментации SAN

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| **Выделенные NIC/HBA** | Отдельные адаптеры для iSCSI, не совмещать с пользовательским LAN | Обязательно |
| **Отдельные подсети** | Разные подсети для каждого пути (MPIO требует отдельные подсети) | Обязательно |
| **Физическая изоляция** | Отдельные коммутаторы для SAN (аэрозольные) | Рекомендуется |
| **Логическая изоляция** | VLAN + MTU 9000 + отключённый STP на портах хранения | Рекомендуется |
| **Jumbo Frames (MTU 9000)** | Согласовано на всех звеньях: initiator NIC -> switch -> target | Обязательно |
| **Egress filtering** | Блокировать выход трафика 3260/tcp из SAN-сегмента | Рекомендуется |
| **Port security** | Отключить неиспользуемые порты, MAC-лимитинг, 802.1X | Рекомендуется |
| **Flow Control** | Включить IEEE 802.3x Pause на iSCSI VLAN для предотвращения потерь | Опционально |

### Проверка MTU (Jumbo Frames)

```bash
# Проверка MTU между инициатором и таргетом
# Должен работать с payload 8972 байт (9000 - 28 заголовков)
ping -M do -s 8972 -c 3 192.168.200.20

# Если не работает — проверить MTU на интерфейсах
ip link show eth1 | grep mtu
# -> mtu 9000
```

## Firewall

### nftables (рекомендуется)

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet iscsi_filter {
    chain input {
        type filter hook input priority filter; policy drop;

        # Разрешить established/related
        ct state established,related accept

        # Разрешить iSCSI только с доверенных подсетей
        ip saddr 192.168.200.0/24 tcp dport 3260 accept
        ip saddr 10.0.0.0/8 tcp dport 3260 accept

        # Rate limiting против DoS
        ip saddr 192.168.200.0/24 tcp dport 3260 \
            meter rate-limit { ip saddr limit rate 10/second burst 20 packets } accept

        # Логирование заблокированных попыток
        tcp dport 3260 log prefix "iSCSI-DROP: " drop

        # Разрешить loopback
        iif lo accept
    }
}
```

### iptables (legacy)

```bash
# Разрешить iSCSI только с доверенных подсетей
sudo iptables -A INPUT -p tcp --dport 3260 -s 192.168.200.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3260 -j DROP

# Сохранить правила
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

### firewalld (RHEL/CentOS/Fedora)

```bash
# Создать zone для iSCSI
sudo firewall-cmd --permanent --new-zone=iscsi
sudo firewall-cmd --permanent --zone=iscsi --add-source=192.168.200.0/24
sudo firewall-cmd --permanent --zone=iscsi --add-port=3260/tcp
sudo firewall-cmd --permanent --zone=iscsi --set-target=ACCEPT

# Ограничить другие интерфейсы
sudo firewall-cmd --permanent --zone=public --remove-service=ssh
sudo firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="192.168.200.0/24" service name="ssh" accept'

sudo firewall-cmd --reload
sudo firewall-cmd --get-active-zones
```

### SYN cookies и параметры ядра

```bash
# Защита от SYN flood на iSCSI-сервере
sudo sysctl -w net.ipv4.tcp_syncookies=1
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=65535

# Увеличение таймаута для долгоживущих сессий
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=86400

# Сохранить
cat >> /etc/sysctl.d/99-iscsi-hardening.conf << 'EOF'
net.ipv4.tcp_syncookies = 1
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.netfilter.nf_conntrack_tcp_timeout_established = 86400
EOF
sudo sysctl --system
```

### Настройка ACL на уровне TPG (LIO)

ACL определяет, какие IQN-инициаторы имеют доступ к конкретной группе порталов.

```bash
sudo targetcli

# Просмотр существующих ACL
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls ls

# Добавление нового разрешённого инициатора
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls create \
  iqn.2026-07.com.example:initiator02

# Удаление ACL (блокировка доступа)
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls delete \
  iqn.2026-07.com.example:initiator02
```

**Важно:** ACL по умолчанию запрещает доступ всем. Доступ разрешается только явно добавленным IQN.

## Шифрование трафика

### IPsec для iSCSI

IPsec обеспечивает шифрование на сетевом уровне (L3), прозрачное для iSCSI. Два режима:

| Режим | Описание | Overhead | Применение |
| :--- | :--- | :--- | :--- |
| **Transport** | Шифрует только payload (без внешнего IP-заголовка) | Минимальный (50-53 байта) | Два хоста в одной сети |
| **Tunnel** | Инкапсулирует весь пакет (новый IP-заголовок) | Больше (56-73 байта) | Через промежуточные сети/шлюзы |

#### Transport mode (рекомендуется для iSCSI)

```bash
# /etc/ipsec.conf (strongswan)
conn iscsi-transport
    left=192.168.200.10      # Инициатор
    right=192.168.200.20     # Таргет
    leftauth=pubkey
    rightauth=pubkey
    leftcert=initiator-cert.pem
    rightid=%any
    ike=aes256-gcm16-modp2048!
    esp=aes256-gcm16!
    keyexchange=ikev2
    type=transport
    auto=start
    dpdaction=restart
```

#### Tunnel mode (для gateway-сценариев)

```bash
conn iscsi-tunnel
    left=192.168.200.10      # Инициатор
    leftsubnet=192.168.200.10/32
    right=192.168.200.20     # Таргет
    rightsubnet=192.168.200.20/32
    ike=aes256-gcm16-modp2048!
    esp=aes256-gcm16!
    keyexchange=ikev2
    type=tunnel
    auto=start
    dpdaction=restart
```

#### Аутентификация сертификатами (вместо PSK)

```bash
# Генерация сертификата для инициатора
openssl req -x509 -newkey rsa:4096 -keyout initiator-key.pem \
  -out initiator-cert.pem -days 365 -nodes \
  -subj "/CN=iscsi-initiator01"

# Генерация сертификата для таргета
openssl req -x509 -newkey rsa:4096 -keyout target-key.pem \
  -out target-cert.pem -days 365 -nodes \
  -subj "/CN=iscsi-target01"

# /etc/ipsec.conf
conn iscsi-cert
    left=192.168.200.10
    leftcert=initiator-cert.pem
    leftid=%fromcert
    right=192.168.200.20
    rightcert=target-cert.pem
    rightid=%fromcert
    ike=aes256-gcm16-modp2048!
    esp=aes256-gcm16!
    keyexchange=ikev2
    authby=pubkey
    auto=start
```

#### Шифрование: рекомендации по cipher suites

| Параметр | Рекомендация | Минимум (RFC 7146) |
| :--- | :--- | :--- |
| **IKE Phase 1** | `aes256-gcm16-modp2048!` | `aes256-sha256-modp2048!` |
| **ESP (Data Phase)** | `aes256-gcm16!` (AEAD) | `aes256-sha256!` |
| **DH Group** | modp2048 (2048 бит) или stronger | modp2048 (обязательный минимум) |
| **Лучший выбор** | AES-GCM (AEAD) — шифрование + целостность за один проход | — |

```bash
# Запуск IPsec
sudo systemctl enable --now strongswan-starter
sudo ipsec statusall

# Проверка SA
sudo ipsec statusall | grep -E "ESTIRMED|INSTALLED"

# Диагностика
sudo tcpdump -i eth1 proto 50 || proto udp port 500 || port 4500
```

#### Влияние IPsec на производительность

| Компонент | Нагрузка | Замечания |
| :--- | :--- | :--- |
| **CPU** | 10-30% (зависит от алгоритма) | С AES-NI: <5% |
| **Latency** | +5-50 мкс | Зависит от размера пакета |
| **Пропускная способность** | Снижение 10-20% | С аппаратным ускорением <5% |
| **Рекомендация** | Используйте AES-GCM + AES-NI | `aes-gcm` быстрее `aes-cbc+hmac-sha256` |

### WireGuard для iSCSI

WireGuard — лёгкая альтернатива IPsec. Работает в пространстве ядра (Linux 5.6+), использует ChaCha20-Poly1305.

#### Настройка site-to-site

```bash
# На инициаторе (192.168.200.10)
sudo ip link add wg0 type wireguard
sudo wg set wg0 listen-port 51820 \
  private-key /etc/wireguard/initiator.key \
  peer $(cat /etc/wireguard/target-pub.key) \
    endpoint 192.168.200.20:51820 \
    allowed-ips 192.168.200.20/32 \
    persistent-keepalive 25
sudo ip addr add 10.10.10.1/32 dev wg0
sudo ip link set wg0 up

# На таргете (192.168.200.20)
sudo ip link add wg0 type wireguard
sudo wg set wg0 listen-port 51820 \
  private-key /etc/wireguard/target.key \
  peer $(cat /etc/wireguard/initiator-pub.key) \
    endpoint 192.168.200.10:51820 \
    allowed-ips 10.10.10.1/32 \
    persistent-keepalive 25
sudo ip addr add 10.10.10.2/32 dev wg0
sudo ip link set wg0 up

# Firewall: разрешить iSCSI только через wg0
sudo iptables -A INPUT -i wg0 -p tcp --dport 3260 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3260 -j DROP
```

#### Сравнение WireGuard vs IPsec

| Критерий | WireGuard | IPsec (IKEv2) |
| :--- | :--- | :--- |
| **Шифрование** | ChaCha20-Poly1305 | AES-GCM / AES-CBC |
| **Аутентификация** | Ключи (Curve25519) | Сертификаты / PSK |
| **CPU overhead** | Ниже (нет IKE) | Выше (IKE negotiation) |
| **Нагрузка на CPU** | <5% при 10 GbE | 10-30% (без AES-NI) |
| **Сложность настройки** | Проще (2 ключа) | Сложнее (IKE phases) |
| **Спецификация** | Ядро Linux 5.6+ | RFC 4301-4309 |
| **Недостаток** | UDP (нет flow control) | Сложность, overhead |

### Когда выбирать WireGuard

- Среды с минимальными требованиями к настройке
- Encrypted iSCSI over untrusted networks (WAN/Internet)
- Среды, где IPsec избыточен (простые топологии)

### Когда выбирать IPsec

- Enterprise-среды с PKI-инфраструктурой
- Требуется сертификатная аутентификация (PCI-DSS, HIPAA)
- Совместимость с не-Linux системами (Windows, VMware)

## Аудит и мониторинг безопасности

### Что логировать

| Событие | Уровень | Место |
| :--- | :--- | :--- |
| Login/Logout сессий | INFO | `journalctl -u target` |
| Успешная аутентификация CHAP | INFO | `journalctl -u target` |
| Неуспешная аутентификация CHAP | WARNING | `journalctl -u target` |
| Нарушение ACL (IQN не найден) | WARNING | `journalctl -u target` |
| Изменение конфигурации (targetcli) | AUDIT | `auditd` |
| Открытие/закрытие LUN | INFO | `targetcli` / array logs |

### Централизованное логирование

```bash
# Отправка логов на центральный сервер (rsyslog)
cat >> /etc/rsyslog.d/50-iscsi.conf << 'EOF'
# iSCSI target logs
if $programname == 'target' then @@logserver.internal:514
& stop
EOF
sudo systemctl restart rsyslog
```

### Auditd правила для iSCSI

```bash
# Мониторинг изменений конфигурации iSCSI
sudo auditctl -w /etc/iscsi/ -p wa -k iscsi-config
sudo auditctl -w /sys/kernel/config/target/ -p wa -k iscsi-target-config
sudo auditctl -w /etc/iscsi/iscsid.conf -p wa -k iscsi-iscsid-conf

# Мониторинг бинарников
sudo auditctl -w /usr/sbin/targetcli -p x -k iscsi-targetcli
sudo auditctl -w /usr/sbin/iscsid -p x -k iscsi-iscsid

# Сохранить правила
sudo auditctl -l > /etc/audit/rules.d/iscsi.rules
```

### Алертинг на основе логов

```bash
# Пример: алерт при 10+ неуспешных попытках CHAP за 5 минут
journalctl -u target --since "5 min ago" | \
  grep -c "CHAP authentication failed" | \
  awk '{if ($1 >= 10) print "ALERT: " $1 " failed CHAP attempts in 5 min"}'
```

## Харденинг iSCSI-сервера

### SELinux для iSCSI (RHEL/Rocky/Alma)

```bash
# Проверка текущего статуса
getenforce
# -> Enforcing

# Просмотр SELinux-событий для iSCSI
sudo ausearch -m avc -ts recent | grep -i iscsi

# Генерация политики при ошибках
sudo ausearch -m avc -ts recent | audit2allow -M iscsi_custom
sudo semodule -i iscsi_custom.pp

# Если нужен нестандартный порт
sudo semanage port -a -t iscsi_port_t -p tcp 2360
```

### AppArmor для iSCSI (Ubuntu/Debian)

```bash
# Генерация профиля на основе наблюдаемого поведения
sudo aa-genprof iscsid

# Просмотр текущих профилей
sudo aa-status | grep iscsi

# Отладка (permissive mode для конкретного профиля)
sudo aa-complain /etc/apparmor.d/usr.sbin.iscsid
```

### Отключение ненужных сервисов

```bash
# Список сервисов, которые МОЖНО отключить на iSCSI-сервере
sudo systemctl disable --now avahi-daemon cups bluetooth

# Убедиться, что target/service запущен
sudo systemctl status target
```

### Ограничение количества сессий

```bash
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 set attribute \
  demo_mode_write_protect=0
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 set attribute \
  cache_dynamic_acls=1
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 set attribute \
  auto_add_mapped_luns=0
```

### Ротация ключей CHAP

Рекомендуется регулярно менять пароли CHAP. Процедура:

1. На таргете: обновить `userid`/`password` в ACL
2. На инициаторе: обновить `node.session.auth.username`/`password`
3. Перезапустить сессию:
   ```bash
   sudo iscsiadm -m node -T <IQN> -p <IP> --logout
   sudo iscsiadm -m node -T <IQN> -p <IP> --login
   ```

### Аудит доступа

```bash
# Просмотр активных сессий на таргете
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls ls

# Детальная информация о подключённых инициаторах
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/acls/iqn.2026-07.com.example:initiator01 info

# Логирование подключений
sudo journalctl -u target -f
```

## Векторы атак и защита

### MITM на Discovery

Атакующий отвечает на SendTargets-запросы с rogue target IQN, перенаправляя инициатор на вредоносный сервер.

**Защита:**
- Использовать статическую запись discovery (`iscsiadm -m discovery -t st -p <IP>`)
- Не выполнять discovery на незнакомых серверах
- Включить CHAP для discovery-сессии

### CHAP replay attack

Активный MITM может ретранслировать challenge/response в реальном времени.

**Защита:** Mutual CHAP + IPsec/WireGuard (шифрование канала)

### LUN masking bypass

Ошибки конфигурации (`auto_add_mapped_luns=1`, `generate_node_acls=1`) позволяют unauthorized LUN access.

**Защита:**
```bash
# Проверить безопасные атрибуты
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 get attribute | grep -E "auto_add|generate"
# -> auto_add_mapped_luns = 0
# -> generate_node_acls = 0
```

### Kernel vulnerabilities

Известные CVE для iSCSI-стека:
- CVE-2026-63887: heap overrun в `iscsi_encode_text_output()`
- CVE-2026-63888: buffer overread/double-free в iSCSI Text commands
- CVE-2026-23216: use-after-free в target subsystem

**Защита:**
```bash
# Проверка версии ядра
uname -r
# Рекомендуется:最新稳定 kernel

# Обновление пакетов open-iscsi
sudo apt update && sudo apt upgrade open-iscsi   # Debian/Ubuntu
sudo dnf update iscsi-initiator-utils             # RHEL/Rocky
```

## Диагностика проблем безопасности

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `iSCSI login failed due to authorization failure` | IQN инициатора не в ACL | Добавить IQN через `targetcli acls create` |
| `CHAP authentication failed` | Неверный логин/пароль | Проверить соответствие credentials на обоих сторонах |
| `CHAP target authentication failed` | Mutual CHAP: неверный `mutual_userid`/`mutual_password` | Проверить `username_in`/`password_in` на инициаторе |
| `Connection refused` | Firewall блокирует порт 3260 | Проверить `iptables -L -n` и `nft list ruleset` |
| `iSCSI connection timed out` | IPsec/WireGuard туннель не установлен | Проверить `ipsec statusall` или `wg show` |
| `No route to host` | Маршрутизация между сегментами | Проверить `ip route` и `traceroute` |
| `Permission denied` (SELinux) | SELinux блокирует доступ | `ausearch -m avc` + `audit2allow` |
| `LUN not found` | LUN не замаплен для ACL | `targetcli .../luns create` |

### Проверка CHAP через tcpdump

```bash
# Захват пакетов аутентификации (без расшифровки паролей)
sudo tcpdump -i eth1 port 3260 -vv -n | grep -i "login"
# -> Видны фазы Login: Security Negotiation -> Operational Negotiation
```

### Проверка IPsec туннеля

```bash
# Статус SA
sudo ipsec statusall

# Проверка шифрования
sudo tcpdump -i eth1 proto 50 -n | head -5

# Проверка с обеих сторон
sudo ipsec restart && sudo ipsec statusall
```

## См. также

- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — создание ACL и настройка CHAP на сервере
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — настройка аутентификации на клиенте
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — поиск проблем с подключением
