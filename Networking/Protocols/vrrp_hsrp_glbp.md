# VRRP / HSRP / GLBP — First Hop Redundancy Protocols

## Определения

**FHRP (First Hop Redundancy Protocol)** — семейство протоколов, обеспечивающих отказоустойчивость шлюза по умолчанию в IP-сетях. Несколько маршрутизаторов образуют виртуальный шлюз (VIP); при отказе активного узла трафик бесшовно переключается на резервный.

**VRRP (Virtual Router Redundancy Protocol)** — стандартный протокол (RFC 5798, RFC 5798), используемый большинством вендоров (Cisco, Juniper, Huawei, Linux). Работает поверх IP с номером протокола **112** (не TCP/UDP).

**HSRP (Hot Standby Router Protocol)** — проприетарный протокол Cisco. Работает на UDP 1985. Используется только на оборудовании Cisco.

**GLBP (Gateway Load Balancing Protocol)** — проприетарный протокол Cisco, обеспечивающий Active/Active балансировку (в отличие от Active/Standby в VRRP/HSRP).

> **См. также:** [Keepalived: VRRP на Linux](../../Networking/ServicesAndTools/keepalived_overview.md), [VLAN: inter-VLAN routing](./VLAN/vlan_inter_vlan_routing.md), [HA: overview](../../Concepts/High_Availability/ha_overview.md)

## Основные концепции

### Сравнение протоколов

| Характеристика | VRRP | HSRP | GLBP |
|---|---|---|---|
| **Стандарт** | RFC 5798 (open standard) | Cisco prop. | Cisco prop. |
| **Транспорт** | IP протокол 112 | UDP 1885 | UDP 3222 |
| **Тип** | Active/Standby | Active/Standby | Active/Active |
| **Таймеры** | 1 сек (по умолчанию) | 3 сек (по умолчанию) | 3 сек |
| **Аутентификация** | Текстовая / None | Текстовая / MD5 | Текстовая / MD5 |
| **Виртуальный IP** | Один VIP на группу | Один VIP на группу | Один VIP, несколько AVFs |
| **Балансировка** | Нет (only failover) | Нет (only failover) | Да (Round-Robin, Hash, etc.) |
| **Оборудование** | Cisco, Juniper, Huawei, Linux | Только Cisco | Только Cisco |

### Работа VRRP

```
┌──────────────┐     ┌──────────────┐
│   MASTER     │     │   BACKUP     │
│ (priority=110)│    │ (priority=100)│
│   VIP:       │     │   VIP:       │
│ 192.168.10.1 │     │ 192.168.10.1 │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └──────────┬─────────┘
                  │
           ┌──────▼──────┐
           │  HOSTS      │
           │ GW:         │
           │ 192.168.10.1│
           └─────────────┘
```

**Процесс выборов:**
1. Все узлы в группе отправляют VRRP-анонсы (multicast 224.0.0.18 или unicast).
2. Узел с наивысшим приоритетом становится **MASTER**.
3. MASTER отправляет анонсы каждые `Advertisement_Interval` (по умолчанию 1 сек).
4. Если BACKUP не получает анонс в течение `3 × Advertisement_Interval`, он объявляет себя MASTER.
5. При восстановлении MASTER (если `preempt` включён), трафик переключается обратно.

**Ключевые термины:**

| Термин | Описание |
|---|---|
| **VRID (Virtual Router ID)** | Идентификатор виртуального роутера (0–255) |
| **VIP (Virtual IP)** | Виртуальный IP-адрес, общая точка входа |
| **Priority** | Приоритет узла (1–254, по умолчанию 100; 255 = ip owner) |
| **Preempt** | Разрешить узлу с более высоким приоритетом вернуть роль MASTER |
| **Advertisement Interval** | Интервал отправки VRRP-анонсов (по умолчанию 1 сек) |
| **Master Down Interval** | Время до объявления MASTER мёртвым (3 × Adv + Skew) |
| **Gratuitous ARP** | Объявление нового MAC для VIP после failover |

### Работа GLBP

```
┌──────────────┐     ┌──────────────┐
│   AVG        │     │   AVF        │
│ (AVG =Active │     │ (AVF =Active │
│  Virtual GW) │     │  Forwarder)  │
│ 192.168.10.1 │     │ MAC: 0000.  │
│ MAC: 0000.   │     │   abcd.1111  │
│   abcd.0001  │     │              │
└──────┬───────┘     └──────┬───────┘
       │                    │
       └──────────┬─────────┘
                  │
           ┌──────▼──────┐
           │  HOSTS      │
           │ GW:         │
           │ 192.168.10.1│
           └─────────────┘
```

**Компоненты GLBP:**

| Компонент | Описание |
|---|---|
| **AVG (Active Virtual Gateway)** | Один узел координирует балансировку (выбирается по приоритету) |
| **AVF (Active Virtual Forwarder)** | Каждый узел в группе является forwarder |
| **Virtual MAC** | Формат: `0000.00AB.CDxx`, где `xx` = номер forwarder (01–1023) |
| **Load Balancing** | Round-Robin, Host-dependent, Weighted |

**Принцип работы:**
1. AVG назначает each peer уникальный Virtual MAC (AVF).
2. Хосты отправляют ARP-запрос на VIP.
3. AVG отвечает с MAC одного из AVF (по алгоритму балансировки).
4. Трафик идёт напрямую к AVF (не через AVG).
5. При отказе AVF, его MAC переназначается другому узлу.

### Хуки Keepalived (notify)

Keepalived позволяет выполнять пользовательские скрипты при смене состояний:

```
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 110
    advert_int 1
    
    authentication {
        auth_type PASS
        auth_pass secret_password
    }
    
    virtual_ipaddress {
        192.168.10.1/24
    }
    
    track_script {
        check_nginx
    }
    
    notify_master "/etc/keepalived/notify.sh MASTER"
    notify_backup "/etc/keepalived/notify.sh BACKUP"
    notify_fault  "/etc/keepalived/notify.sh FAULT"
}
```

**notify.sh:**
```bash
#!/bin/bash
STATE=$1
case $STATE in
    MASTER)
        curl -s -X POST https://api.example.com/dns/update \
          -d '{"host":"app.example.com","ip":"10.0.1.100"}'
        ;;
    BACKUP)
        curl -s -X POST https://api.example.com/dns/remove \
          -d '{"host":"app.example.com"}'
        ;;
    FAULT)
        echo "VRRP FAULT detected" | logger -t keepalived
        ;;
esac
```

## Практический блок

### VRRP на Cisco IOS

```
! MASTER
interface Vlan10
 ip address 192.168.10.2 255.255.255.0
 vrrp 10 ip 192.168.10.1
 vrrp 10 priority 110
 vrrp 10 preempt
 vrrp 10 authentication text mypassword

! BACKUP
interface Vlan10
 ip address 192.168.10.3 255.255.255.0
 vrrp 10 ip 192.168.10.1
 vrrp 10 priority 100
 vrrp 10 preempt
 vrrp 10 authentication text mypassword
```

### VRRP на Juniper Junos

```
# MASTER
set interfaces irb unit 10 family inet address 192.168.10.2/24
set protocols vrrp group 10 interface irb.10
set protocols vrrp group 10 virtual-address 192.168.10.1
set protocols vrrp group 10 priority 110
set protocols vrrp group 10 preempt
set protocols vrrp group 10 authentication-key mypassword

# BACKUP
set protocols vrrp group 10 priority 100
```

### VRRP на Linux (Keepalived)

```bash
# Установка
sudo apt install keepalived

# Конфигурация (/etc/keepalived/keepalived.conf)
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 110
    advert_int 1
    
    authentication {
        auth_type PASS
        auth_pass secret_password
    }
    
    virtual_ipaddress {
        192.168.10.1/24 dev eth0
    }
    
    track_script {
        check_nginx
    }
}

vrrp_script check_nginx {
    script "/usr/bin/curl -sf http://localhost/health"
    interval 2
    weight -20
    fall 3
    rise 2
}
```

### Firewall для VRRP

```bash
# VRRP использует IP-протокол 112 (не UDP/ТСР порт!)

# iptables (на каждом узле — разрешить VRRP от двух пиров)
sudo iptables -A INPUT -p 112 -s 10.0.1.2 -j ACCEPT
sudo iptables -A INPUT -p 112 -s 10.0.1.3 -j ACCEPT
sudo iptables -A OUTPUT -p 112 -d 10.0.1.2 -j ACCEPT
sudo iptables -A OUTPUT -p 112 -d 10.0.1.3 -j ACCEPT

# nftables (современный)
sudo nft add rule inet filter input ip protocol vrrp ip saddr { 10.0.1.2, 10.0.1.3 } accept
```

### Диагностика

| Команда | Описание |
|---|---|
| `show vrrp brief` (Cisco) | Статус VRRP-групп |
| `show vrrp` (Cisco) | Детали: roles, таймеры, VIP |
| `show standby brief` (Cisco) | Аналог для HSRP |
| `tcpdump -i eth0 -nn vrrp` | Захват VRRP-анонсов |
| `ip addr show eth0` | Проверка VIP на интерфейсе |
| `journalctl -u keepalived -f` | Логи keepalived |
| `keepalived --status` | Текущее состояние |

### Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| VIP не появляется | Firewall блокирует протокол 112 | Разрешить vrrp между пирами |
| Два узла одновременно MASTER | Однонаправленная блокировка VRRP | Восстановить симметрию правил FW |
| Split-brain | Разные `virtual_router_id` | Сверить VRID во всех конфигах |
| Failover не работает | `preempt` отключён | Включить preempt на MASTER |
| Uзел навсегда FAULT | Провал track_script | Проверить `journalctl -u keepalived` |
| VIP «завис» после остановки | Keepalived не снял VIP | `ip addr del 10.0.1.10/24 dev eth0` |

## Дополнительная информация

- **RFC 5798** — VRRP (Virtual Router Redundancy Protocol)
- **RFC 2281** — HSRP (Hot Standby Router Protocol)
- **[Keepalived: обзор и настройка](../../Networking/ServicesAndTools/keepalived_overview.md)** — VRRP на Linux, BFD, мониторинг
- **[VLAN: inter-VLAN routing](./VLAN/vlan_inter_vlan_routing.md)** — FHRP в контексте VLAN
- **[HA: overview](../../Concepts/High_Availability/ha_overview.md)** — архитектура отказоустойчивости
- **[Angie HA с Keepalived](../../WebServers/Angie/angie_ha_with_keepalived.md)** — praktisk examples
