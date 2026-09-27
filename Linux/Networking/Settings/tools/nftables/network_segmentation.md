# nftables — сегментирование сети

## Определения

**Сегментирование сети (Network Segmentation)** — разделение сетевой инфраструктуры на изолированные сегменты для ограничения распространения атак (Lateral Movement), минимизации поверхности атаки и упрощения контроля доступа.

**Микросегментирование (Microsegmentation)** — детализированный контроль трафика на уровне отдельных узлов, приложений или контейнеров, независимо от их физического расположения. В nftables реализуется через фильтрацию по IP/MAC в сочетании с динамическими наборами.

**Маршрутизатор (Router)** — устройство L3 (Network Layer — сетевой уровень), обеспечивающее передачу пакетов между разными IP-подсетями. В nftables фильтрация маршрутизируемого трафика происходит в цепочках `forward` семейств `ip`, `ip6` или `inet`.

**Прозрачный межсетевой экран (Transparent Firewall)** — устройство L2 (Data Link Layer — канальный уровень), фильтрующее трафик внутри одного широковещательного домена (L2-сегмента) без изменения настроек IP на узлах.

**ARP (Address Resolution Protocol)** — протокол разрешения адресов. При сегментации на L2 критически важно разрешать ARP-запросы, иначе узлы потеряют связь даже при разрешенном IP-трафике.

**Zone-based firewall (Зональный файрвол)** — паттерн, при котором политики безопасности привязаны к абстрактным зонам (например, `lan`, `dmz`, `mgmt`), а не к конкретным интерфейсам. В nftables реализуется через матчеры `iifname`/`oifname` и именованные карты.

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| ** NIC** | 2 порта | 3+ порта для DMZ/изолированных сегментов |
| ** CPU** | 2 ядра | 4+ ядра при нагрузке >1Gbps с интенсивной фильтрацией |
| ** RAM** | 512 MB | 2 GB+ для больших таблиц conntrack и sets |

### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **Ядро Linux** | 5.3+ (нативный `bridge` conntrack), 5.15+ рекомендуется |
| **nftables** | 1.0.0+ |
| **iproute2** | 5.x+ |
| **bridge-utils** | для управления мостами (`ip link`, `bridge`) |
| **Права** | root (sudo) |
| **Служба** | `nftables` (systemd) для персистентности |

### Проверка окружения

```bash
# Версия ядра
uname -r
# → 5.15.0-78-generic

# Наличие nftables
which nft && nft --version
# → nft v1.0.9

# Проверка загруженных модулей ядра
lsmod | grep -E 'nf_conntrack|nf_defrag_ipv4|nf_nat|bridge'
# → nf_conntrack          163840  1 bridge
# → bridge                327680  0
# → nf_nat                245760  1 nf_conntrack

# Размер таблицы conntrack
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144

# Статус службы nftables
sudo systemctl status nftables
```

## Основные концепции

Сегментирование в nftables реализуется через следующие механизмы:

### 1. Архитектура семейств таблиц

| Семейство | Уровень OSI | Применение для сегментации |
| :--- | :--- | :--- |
| **`inet`** | L3 (IPv4/v6) | Рекомендуется для большинства сценариев: единые правила для IPv4 и IPv6. |
| **`ip`** / **`ip6`** | L3 | Специфичные таблицы для IPv4 или IPv6 при необходимости разделения. |
| **`bridge`** | L2 | Фильтрация трафика внутри Linux Bridge, включая VLAN-aware мосты. |
| **`netdev`** | L1/L2 | Ingress/egress фильтрация до передачи стеку Netfilter. |

### 2. Цепочки и хуки

При сегментации используются следующие хуки:

| Хук | Семейство | Назначение |
| :--- | :--- | :--- |
| **`forward`** | `inet`/`ip`/`ip6` | Фильтрация транзитного трафика между сегментами. Основная точка для L3-сегментации. |
| **`input`** | `inet`/`ip`/`ip6` | Фильтрация трафика, предназначенного самому файрволу. |
| **`ingress`/`egress`** | `netdev` | Самая ранняя/поздняя точка фильтрации на интерфейсе. |
| **`forward`** | `bridge` | Фильтрация L2-трафика внутри моста. |

### 3. Механизмы оптимизации

**Сеты (Sets):**
Именованные наборы элементов (адреса, порты, интерфейсы), позволяющие обрабатывать тысячи объектов за один проход за счет использования хэш-таблиц. В контексте сегментации используются для хранения списков разрешенных/запрещенных IP, пар MAC→порт, VLAN→зона.

**Мапы (Maps):**
Структуры «ключ-значение», позволяющие сопоставлять данные (например, IP-адрес источника → вердикт или IP → порт). Карты вердиктов (`vmap`) особенно эффективны для маршрутизации трафика между зонами.

**Конкатенации (Concatenations):**
Объединение нескольких полей (например, `ip saddr . ip daddr . tcp dport`) в одну проверку для ускорения обработки и компактного хранения в наборах.

**Verdict Maps (Карты вердиктов):**
Позволяют направлять трафик в разные цепочки или выносить вердикты (`accept`, `drop`) на основе совпадения по набору данных. Идеально для матриц доступа между зонами.

### 4. Отслеживание соединений (conntrack) в сегментации

При сегментации критически важно понимать влияние conntrack:
- **Stateful inspection** минимизирует нагрузку: `ct state established,related accept` размещается в начале цепочки.
- **Conntrack exhaustion** — риск при высоких нагрузках. Необходимо мониторить `conntrack -S` и настраивать `nf_conntrack_max`.
- **Утечки состояний** при изменении правил: атомарное применение через `nft -f` исключает несоответствия.

### 5. Атомарность применений

Все изменения правил через `nft -f <файл>` применяются атомарно. Либо весь набор правил загружается успешно, либо ни одно изменение не вступает в силу. Это исключает «разрывные» состояния, когда часть правил применена, а часть — нет. Для сегментации это критично: промежуточное состояние с частично разрешенными правилами может открыть временную брешь.

### 6. Встроенные счетчики

Каждое правило nftables имеет встроенные счетчики пакетов и байт. Просмотр:
```bash
nft list ruleset -a
# → tcp dport 22 accept # packets 1542 bytes 98720
```

### 7. Трассировка пакетов (nftrace)

Для отладки сегментации можно включить трассировку на отдельное правило:
```bash
nft add rule inet filter forward ip saddr 192.168.1.0/24 meta nftrace set 1
nft monitor trace
```

### 8. Сравнение L2 vs L3 сегментации

| Критерий | L3 (forward) | L2 (bridge) |
| :--- | :--- | :--- |
| **Семейство** | `inet`/`ip`/`ip6` | `bridge`/`netdev` |
| **Уровень OSI** | Сетевой | Канальный |
| **Требует маршрутизации** | Да | Нет |
| **Изменение IP на узлах** | Требует настройки шлюзов | Не требуется |
| **Производительность** | Высокая | Высокая (hardware offload возможен) |
| **Фильтрация VLAN** | Через `ip`/`ip6` families | Нативно в bridge family |
| **ARP-трафик** | Не виден | Виден и фильтруем |

## Практические сценарии

### Сценарий 1. Сегментация на уровне маршрутизатора (L3) с использованием `inet`

**Задача**: Изолировать сегменты `LAN`, `Servers` и `DMZ`, используя современные возможности nftables для оптимизации.

#### Архитектура

-   **LAN**: `192.168.1.0/24` (интерфейс `eth1`)
-   **Servers**: `172.16.10.0/24` (интерфейс `eth2`)
-   **DMZ**: `10.0.50.0/24` (интерфейс `eth3`)

#### Матрица доступа

| Источник (Зона) | Назначение (Зона) | Сервис | Действие |
| :--- | :--- | :--- | :--- |
| LAN | Servers | SSH (22), PostgreSQL (5432) | Разрешить |
| LAN | DMZ | HTTP (80), HTTPS (443) | Разрешить |
| Servers | Internet | DNS (53), NTP (123) | Разрешить |
| DMZ | Servers | Только логирование | Отклонить |

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f

# Очистка текущих правил
flush ruleset

table inet filter {
    # Именованный набор для разрешенных пар "Источник . Назначение . Порт"
    set allowed_access {
        type ipv4_addr . ipv4_addr . inet_service
        flags interval
        elements = {
            192.168.1.0/24 . 172.16.10.0/24 . 22,   # LAN -> Servers (SSH)
            192.168.1.0/24 . 172.16.10.0/24 . 5432, # LAN -> Servers (DB)
            192.168.1.0/24 . 10.0.50.0/24 . 80,     # LAN -> DMZ (HTTP)
            192.168.1.0/24 . 10.0.50.0/24 . 443     # LAN -> DMZ (HTTPS)
        }
    }

    chain forward {
        type filter hook forward priority filter; policy drop;

        # 1. Разрешить установленные соединения (Stateful Inspection)
        ct state established,related accept
        
        # 2. Сброс некорректных пакетов
        ct state invalid drop

        # 3. Фильтрация на основе конкатенаций и наборов
        # Сопоставляем кортеж (SADDR, DADDR, DPORT) с набором @allowed_access
        ip saddr . ip daddr . th dport @allowed_access accept

        # 4. Специфичное правило для DNS (LAN -> Internet)
        iifname "eth1" oifname "eth0" udp dport 53 accept
        
        # 5. Логирование и отклонение остального (для отладки)
        log prefix "FW_FORWARD_REJECT: "
    }
}
```

#### Активация маршрутизации в Linux

```bash
# Включить пересылку пакетов в ядре (IPv4 и IPv6)
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/95-forwarding.conf
echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.d/95-forwarding.conf
sysctl -p /etc/sysctl.d/95-forwarding.conf
# → net.ipv4.ip_forward = 1
# → net.ipv6.conf.all.forwarding = 1
```

### Сценарий 2. Прозрачный межсетевой экран (L2 Bridge)

**Задача**: Внедрить фильтрацию трафика между группами узлов в одной подсети без изменения их настроек IP, используя таблицу семейства `bridge`.

#### Особенности

-   Все узлы находятся в подсети `172.30.0.0/24`.
-   Межсетевой экран работает как "умный коммутатор" (Bridge).
-   Фильтрация возможна по MAC-адресам, EtherType и инкапсулированным IP-пакетам.

#### Настройка моста (Bridge)

```bash
# Создание моста и добавление интерфейсов (через iproute2)
ip link add name br0 type bridge
ip link set dev eth1 master br0
ip link set dev eth2 master br0
ip link set br0 up
```

#### Конфигурация nftables (семейство bridge)

```bash
#!/usr/sbin/nft -f

flush ruleset

table bridge filter {
    chain forward {
        type filter hook forward priority filter; policy drop;

        # 1. Критически важно для работы L2: разрешить ARP
        ether type arp accept

        # 2. Разрешить установленные соединения (Stateful L2)
        ct state established,related accept

        # 3. Фильтрация по IP внутри моста
        # Разрешить SSH с админского хоста на сервер базы данных
        ip saddr 172.30.0.10 ip daddr 172.30.0.50 tcp dport 22 accept
        
        # 4. Запретить всё остальное, кроме DHCP-запросов
        udp dport 67-68 accept
    }
}
```

> **Примечание**: Для более простой реализации "в один клик" см. паттерн **[nftables — OneButtonFirewall](./one_button_firewall.md)**.

### Сценарий 3. VLAN-aware сегментация

**Задача**: Разделить трафик нескольких VLAN на одном физическом интерфейсе с помощью VLAN-aware моста и nftables.

#### Архитектура

| VLAN ID | Название | Подсеть | Интерфейс моста |
| :--- | :--- | :--- | :--- |
| 10 | Management | 10.0.10.0/24 | br0 |
| 20 | Servers | 10.0.20.0/24 | br0 |
| 30 | IoT | 10.0.30.0/24 | br0 |

#### Настройка VLAN-aware моста

```bash
# Создание моста с VLAN filtering
ip link add name br0 type bridge vlan_filtering 1
ip link set dev eth0 master br0
ip link set br0 up

# Настройка портов
bridge vlan add dev eth0 vid 10 pvid untagged
bridge vlan add dev eth0 vid 20 pvid untagged
bridge vlan add dev eth0 vid 30 pvid untagged

# Удаление VLAN 1 (по умолчанию)
bridge vlan del dev eth0 vid 1 self
```

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f
flush ruleset

table bridge filter {
    # Запретить VLAN hopping
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        # Разрешить только один тег на фрейм (защита от VLAN hopping)
        ether type vlan accept
        ether type 0x88a8 drop  # QinQ (802.1ad) запрещен
        
        # Разрешить ARP
        ether type arp accept
        
        # Stateful для IP внутри VLAN
        ct state established,related accept
        
        # VLAN 10 -> VLAN 20: только SSH
        vlan id 10 ip daddr 10.0.20.0/24 tcp dport 22 accept
        
        # VLAN 10 -> Internet: разрешить
        vlan id 10 accept
        
        # VLAN 20 -> Internet: только DNS и NTP
        vlan id 20 udp dport {53, 123} accept
        vlan id 20 tcp dport {53, 123} accept
        
        # VLAN 30 (IoT) -> только MQTT и обновление
        vlan id 30 tcp dport {1883, 8883} accept
        vlan id 30 udp dport {123, 53} accept
        
        # Логирование остального
        log prefix "VLAN_FILTER_DROP: "
    }
}
```

### Сценарий 4. Мультиенансовая изоляция с пер-тенантными таблицами

**Задача**: Организовать строгую изоляцию между несколькими организациями (тенантами) на одном физическом файрволе.

#### Архитектура

| Тенант | VLAN / Подсеть | Интерфейс | Разрешения |
| :--- | :--- | :--- | :--- |
| Tenant-A | `10.1.0.0/16` | `eth1` | Outbound Internet, Tenant-B (SSH) |
| Tenant-B | `10.2.0.0/16` | `eth2` | Outbound Internet, Tenant-A (SSH) |
| Shared | `10.255.0.0/24` | `eth3` | Общие сервисы (DNS, NTP) |

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f
flush ruleset

# Общая таблица для mesh-трафика между тенантами
table inet tenant_mesh {
    set tenant_a {
        type ipv4_addr
        elements = { 10.1.0.0/16 }
    }
    
    set tenant_b {
        type ipv4_addr
        elements = { 10.2.0.0/16 }
    }
    
    set allowed_cross_tenant {
        type ipv4_addr . ipv4_addr . inet_service
        elements = {
            10.1.0.0/16 . 10.2.0.0/16 . 22,
            10.2.0.0/16 . 10.1.0.0/16 . 22
        }
    }
    
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        # Stateful
        ct state established,related accept
        ct state invalid drop
        
        # Cross-tenant через набор
        ip saddr . ip daddr . tcp dport @allowed_cross_tenant accept
        
        # Разрешить shared services
        ip daddr 10.255.0.0/24 accept
        
        # Запретить прямой доступ к Internet другим тенантам
        ip saddr 10.1.0.0/16 oifname "eth0" udp dport 53 accept
        ip saddr 10.2.0.0/16 oifname "eth0" udp dport 53 accept
        
        log prefix "TENANT_BLOCK: "
    }
}

# Пер-тенантные таблицы для input/output на самом файрволе
table inet tenant_a_input {
    chain input {
        type filter hook input priority filter; policy drop;
        iifname "lo" accept
        ct state established,related accept
        ip saddr 10.1.0.0/16 tcp dport 22 accept
        log prefix "TENANT_A_INPUT_DROP: "
    }
}

table inet tenant_b_input {
    chain input {
        type filter hook input priority filter; policy drop;
        iifname "lo" accept
        ct state established,related accept
        ip saddr 10.2.0.0/16 tcp dport 22 accept
        log prefix "TENANT_B_INPUT_DROP: "
    }
}
```

### Сценарий 5. Зональный паттерн (Zone-based Firewall)

**Задача**: Реализовать паттерн зонального файрвола, аналогичный firewalld, через карты вердиктов nftables.

#### Матрица зон

| Зона | Интерфейс | Описание |
| :--- | :--- | :--- |
| `public` | `eth0` | Внешний интерфейс (Интернет) |
| `internal` | `eth1` | Внутренняя сеть |
| `dmz` | `eth2` | Демилитаризованная зона |
| `mgmt` | `eth3` | Управление |

#### Карта зон

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet zones {
    # Карта интерфейс -> зона
    map iface_zone {
        type ifname : zone
        elements = {
            "eth0" = "public",
            "eth1" = "internal",
            "eth2" = "dmz",
            "eth3" = "mgmt"
        }
    }
    
    # Карта разрешений зона -> зона -> вердикт
    set zone_policy {
        type ipv4_addr . ipv4_addr : verdict
        elements = {
            # internal -> dmz: только HTTP/HTTPS
            10.0.1.0/24 . 10.0.2.0/24 : accept,
            # dmz -> internal: запрещено
            10.0.2.0/24 . 10.0.1.0/24 : drop,
            # mgmt -> все: разрешено
            10.0.3.0/24 . 0.0.0.0/0 : accept
        }
    }
    
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        ct state established,related accept
        ct state invalid drop
        
        # Применение зональной политики
        ip saddr . ip daddr @zone_policy
        
        # Default log
        log prefix "ZONE_DROP: "
    }
}
```

### Сценарий 6. Сегментация с защитой DHCP и DNS

**Задача**: Изолировать сегмент с IoT-устройствами, разрешив только DHCP и DNS, и предотвратив бродкаст-шторм.

#### Особенности

-   IoT-сегмент: `10.0.50.0/24` (интерфейс `eth3`)
-   DHCP: `10.0.50.1`
-   DNS: только к корпоративным резолверам

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet iot_isolation {
    set allowed_dns {
        type ipv4_addr
        elements = { 10.0.0.53, 10.0.0.54 }
    }
    
    set iot_macs {
        type ether_addr
        elements = {
            aa:bb:cc:dd:ee:ff,  # Камера 1
            11:22:33:44:55:66   # Датчик 1
        }
    }
    
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        ct state established,related accept
        ct state invalid drop
        
        # Разрешить DHCP
        udp dport 67-68 accept
        
        # DNS только к разрешенным резолверам
        udp dport 53 ip daddr @allowed_dns accept
        tcp dport 53 ip daddr @allowed_dns accept
        
        # Запретить broadcast/multicast из IoT
        ip daddr 255.255.255.255 drop
        ip daddr 224.0.0.0/4 drop
        
        # MAC-фильтрация (опционально)
        ether saddr @iot_macs accept
        
        log prefix "IOT_BLOCK: "
    }
    
    chain input {
        type filter hook input priority filter; policy drop;
        iifname "lo" accept
        ct state established,related accept
        ip saddr 10.0.50.0/24 tcp dport 22 accept  # Управление IoT
        log prefix "IOT_INPUT_DROP: "
    }
}
```

### Сценарий 7. Изоляция плоскости управления (Management Plane)

**Задача**: Организовать выделенный сегмент управления с доступом только для админов.

#### Архитектура

| Сегмент | Подсеть | Доступ |
| :--- | :--- | :--- |
| Management | `10.255.255.0/24` | Только из corporate VPN / jump host |
| Production | `192.168.0.0/16` | Доступ из management только на management-порты |
| Storage | `10.0.100.0/24` | iSCSI/NFS только из production |

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet mgmt_isolation {
    set mgmt_sources {
        type ipv4_addr
        elements = { 10.0.200.0/24 }  # Corporate VPN pool
    }
    
    set mgmt_services {
        type inet_service
        elements = { 22, 443, 161, 623 }  # SSH, HTTPS, SNMP, IPMI
    }
    
    chain input {
        type filter hook input priority filter; policy drop;
        
        iifname "lo" accept
        
        # Доступ к management-интерфейсу только из VPN
        iifname "eth3" ip saddr @mgmt_sources tcp dport @mgmt_services accept
        
        # ICMP только из management
        iifname "eth3" ip saddr @mgmt_sources icmp type echo-request accept
        
        ct state established,related accept
        
        log prefix "MGMT_INPUT_DROP: "
    }
    
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        ct state established,related accept
        ct state invalid drop
        
        # Management -> Production: только management-порты
        ip saddr 10.255.255.0/24 ip daddr 192.168.0.0/16 tcp dport {22, 443, 161} accept
        
        # Production -> Storage: iSCSI/NFS
        ip saddr 192.168.0.0/16 ip daddr 10.0.100.0/24 tcp dport {3260, 2049} accept
        
        # Запретить обход через management
        ip saddr 10.255.255.0/24 oifname "eth0" drop
        
        log prefix "MGMT_FORWARD_DROP: "
    }
}
```

### Сценарий 8. Сегментация с динамическими списками и таймаутом

**Задача**: Автоматически изолировать скомпрометированные хосты на основе порогового значения.

#### Конфигурация nftables

```bash
#!/usr/sbin/nft -f
flush ruleset

table inet dynamic_segmentation {
    set quarantine_list {
        type ipv4_addr
        flags timeout
        timeout 1h
    }
    
    set threshold_count {
        type ipv4_addr . counter
    }
    
    chain forward {
        type filter hook forward priority filter; policy drop;
        
        ct state established,related accept
        ct state invalid drop
        
        # Карантин
        ip saddr @quarantine_list drop
        
        # Детекция аномалии (пример: >1000 SYN/sec)
        tcp flags syn limit rate over 1000/second update @quarantine_list { ip saddr timeout 1h }
        
        # Логирование подозрительной активности
        tcp flags syn log prefix "SYN_FLOOD_DETECT: "
        
        log prefix "DYNAMIC_DROP: "
    }
}
```

## Валидация результатов

### Проверка загруженных правил

```bash
# Просмотр всех таблиц и цепочек
sudo nft list ruleset

# Просмотр конкретной таблицы
sudo nft list table inet filter

# Просмотр с handle (для удаления)
sudo nft -a list chain inet filter forward
```

### Проверка счетчиков правил

```bash
# Просмотр конкретной цепочки
sudo nft list chain inet filter forward

# Ожидаемый вывод:
# → tcp dport 22 accept # packets 1542 bytes 98720
# → ct state established,related accept # packets 12450 bytes 8765432
```

### Проверка маршрутизации

```bash
# Таблица маршрутизации
ip route show

# Проверка forwarding
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Проверка conntrack
sudo conntrack -L -o extended | grep ESTABLISHED
```

### Проверка сегментации (тестирование)

```bash
# Тест: LAN -> Servers (SSH) - должен пройти
nc -zv 172.16.10.10 22
# → Connection succeeded

# Тест: LAN -> DMZ (HTTP) - должен пройти
nc -zv 10.0.50.10 80
# → Connection succeeded

# Тест: DMZ -> Servers (PostgreSQL) - должен быть заблокирован
nc -zv 172.16.10.20 5432
# → Connection timed out

# Тест: IoT -> Internet (запрещено, кроме DNS)
curl http://10.0.50.1:8080
# → Connection timed out
```

### Проверка моста (L2)

```bash
# Статус моста
bridge link show

# Таблица FDB
bridge fdb show

# VLAN-фильтрация
bridge vlan show
```

### Статистика по состояниям

```bash
sudo conntrack -L -o extended | awk '{print $4}' | sort | uniq -c
# → 12 ESTABLISHED
# → 3 TIME_WAIT
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Правила не применяются** | `nft list ruleset` пуст | Проверить синтаксис: `nft --check -f` | Исправить ошибку в файле |
| **Сегменты видят друг друга** | Соединения проходят | `nft list chain` — политика drop? | Проверить order правил, policy |
| **Потеря SSH при применении** | Соединение обрывается | Локальная консоль | Использовать атомарную загрузку |
| **ARP-запросы блокируются** | Узлы не получают MAC | `tcpdump -i br0 arp` | Разрешить `ether type arp accept` |
| **DHCP не работает** | Узлы не получают IP | `tcpdump -i eth0 port 67` | Проверить `udp dport 67-68 accept` |
| **Conntrack переполнен** | `dmesg` показывает `table full` | `conntrack -S` — `drop > 0` | Увеличить `nf_conntrack_max` |
| **Высокая нагрузка CPU** | `top` показывает high softirq | `cat /proc/softirqs` | Уменьшить правила, добавить limit rate |
| **VLAN-трафик не проходит** | Нет connectivity между VLAN | `bridge vlan show` | Проверить PVID, allowed VLAN |
| **Внутренние узлы не видят DNS** | nslookup падает | `tcpdump -i eth0 port 53` | Проверить allowed DNS резолверы |

## Краевые случаи и ограничения

1.  **Атомарность:** nftables применяет изменения атомарно. Ошибка в синтаксисе halfway не частично активирует правила. Для сегментации это критично: промежуточное состояние с частично разрешенными правилами может открыть временную брешь.
2.  **IPv6:** Если семейство `inet` используется, правило `tcp dport 80 accept` создаст записи и для IPv6. Для IPv6-only используйте `ip6` семейство.
3.  **ARP в bridge family:** ARP-трафик обрабатывается только в семействе `bridge`. Правило `ether type arp accept` обязательно для прозрачных мостов.
4.  **VLAN 1:** На VLAN-aware мостах VLAN 1 присутствует по умолчанию на всех портах. В production рекомендуется удалять его (`bridge vlan del dev eth0 vid 1 self`), чтобы предотвратить неконтролируемый broadcast.
5.  **MTU:** MTU моста автоматически падает до минимального среди портов. Если к мосту подключен интерфейс с MTU 1500, весь мост будет ограничен 1500 байт, даже если остальные порты поддерживают 9000.
6.  **Конкатенации и интервалы:** При использовании concatenated sets с флагом `interval` диапазоны IP (`192.168.1.0/24`) раскрываются в отдельные элементы. Для больших диапазонов используйте `type ipv4_addr` без concatenation.
7.  **Conntrack и мосты:** В ядрах < 5.3 conntrack для bridge family не поддерживался нативно. Проверьте версию ядра.
8.  **Асимметричная маршрутизация:** если ответный трафик возвращается через другой интерфейс, stateful firewall дропает пакеты. Решение: `rp_filter=2` или единый шлюз для входящего/исходящего трафика.
9.  **Dynamic sets и memory:** Наборы с флагом `timeout` хранятся в памяти. При большом количестве атакующих IP убедитесь, что `nf_conntrack_max` достаточно.
10. **Hairpin mode:** по умолчанию мост не рефлексирует кадр обратно в порт-источник. Если внутренние узлы должны общаться друг с другом через мост (например, при избыточной топологии), включите hairpin: `bridge link set dev <iface> hairpin on`.
11. **Storm Control:** В Linux аппаратный storm control отсутствует. Для ограничения broadcast/multicast используйте `tc` (traffic control) в связке с nftables.
12. **Bridge VLAN filtering и performance:** Включение `vlan_filtering 1` добавляет минимальную нагрузку. На высокоскоростных интерфейсах (10G+) проверяйте производительность через `iperf3`.

## Best Practices

1.  **Default Deny:** каждая базовая цепочь (`input`, `forward`, `output`) должна иметь политику `drop`. Разрешения добавляются явно.
2.  **Stateful Inspection в первой позиции:** размещайте `ct state established,related accept` сразу после проверки `invalid`, чтобы минимизировать нагрузку на CPU.
3.  **Ограничение логирования:** всегда используйте `limit rate` с выражением `log`, чтобы избежать переполнения журнала при DDoS.
4.  **Использование sets для производительности:** для списков из 100+ элементов используйте именованные наборы (sets) вместо последовательных проверок.
5.  **Verdict Maps для матриц:** используйте карты вердиктов для матриц доступа между зонами — это ускоряет обработку и упрощает поддержку.
6.  **Проверка синтаксиса перед загрузкой:** `nft --check -f /etc/nftables.conf`.
7.  **Резервное копирование:** сохраняйте предыдущий ruleset перед каждым изменением.
8.  **Атомарность:** используйте `nft -f` вместо пошагового добавления правил через `nft add`.
9.  **Мониторинг:** настройте алерты на рост dropped-пакетов в цепочках.
10. **Документация:** комментируйте каждое правило в конфигурационном файле, особенно исключения.
11. **Тестирование в lab:** перед внедрением в production протестируйте конфигурацию в изолированной среде с `tcpdump`.
12. **Персистентность:** используйте `systemd`-сервис `nftables` для автоматической загрузки правил при загрузке системы.
13. **Верификация после применения:** всегда проверяйте `nft list ruleset` и тестовые соединения после применения правил.
14. **VLAN-aware мосты:** удаляйте VLAN 1 по умолчанию, настраивайте PVID явно.
15. **Bridge conntrack:** для stateful фильтрации в bridge family требуется ядро 5.3+.

## Очистка окружения

```bash
# 1. Удаление всех правил
sudo nft flush ruleset

# 2. Удаление таблиц (если созданы отдельные)
sudo nft delete table inet tenant_mesh
sudo nft delete table inet tenant_a_input
sudo nft delete table inet tenant_b_input
sudo nft delete table inet mgmt_isolation
sudo nft delete table inet dynamic_segmentation
sudo nft delete table inet iot_isolation
sudo nft delete table bridge filter

# 3. Удаление моста (если использовался)
sudo ip link set dev eth1 nomaster
sudo ip link set dev eth2 nomaster
sudo ip link delete br0

# 4. Отключение службы
sudo systemctl disable --now nftables
```

## Дополнительная информация

### См. также

-   **[Сетевая сегментация и микросегментация](../../../../../Networking/Concepts/network_segmentation_and_microsegmentation.md)** — концептуальный обзор.
-   **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — устройство таблиц и цепочек.
-   **[nftables — моделирование угроз](./threat_modeling.md)** — алгоритм проектирования правил.
