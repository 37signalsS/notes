# ICMP: Высокая доступность (bonding, VRRP, keepalived)

## Определения

**Bonding ( NIC teaming )** — объединение нескольких сетевых интерфейсов в один логический для отказоустойчивости и/или увеличения пропускной способности. В Linux реализуется через модуль ядра `bonding`.

**VRRP (Virtual Router Redundancy Protocol)** — протокол резервирования шлюзов по умолчанию. Несколько маршрутизаторов образуют виртуальный шлюз (VIP); активный (Master) отправляет VRRP-адвертементы, резервные (Backup) ждут его падения.

**keepalived** — userspace-демон, реализующий VRRP и LVS (Linux Virtual Server). Используется для предоставленияHighly Available IP-адреса и health checks.

**ICMP в HA-контексте** — использование ICMP Echo Request/Reply как механизм health checking для определения работоспособности узлов и принятия решения о фейловере.

## Основные концепции

### Bonding и ICMP

В bonded-интерфейсах ICMP-трафик обрабатывается следующим образом:

- **active-backup:** только один интерфейс (slave) активен. Если он падает, bonding переключается на резервный. ICMP с bonded-интерфейса продолжает работать, но есть краткий outage (миллисекунды) на переключение.
- **balance-rr / balance-xor / 802.3ad (LACP):** трафик распределяется по нескольким slave-интерфейсам. ICMP-пакеты идут через любой доступный slave.
- **Главная проблема bonding:** при переключении slave MAC-адрес bonded-интерфейса не меняется (если используете `fail_over_mac=1` или `follow`), поэтому ARP-кэш соседей остается валидным. ICMP ping через bonded-интерфейс продолжает работать прозрачно.

**Важно:** при переключении active→backup в режиме active-backup switch может видеть flap порта, что приводит к:
- Очистке MAC-таблицы
- Короткому потерю связности (ping loss)
- Обновлению STP (если bonding над коммутатором)

### VRRP и ICMP

VRRP advertisement-ы отправляются multicast. ICMP ping на VIP работает только на Master-узле.

**Поведение при фейловере:**
1. Master падает (или перестает отвечать на ICMP).
2. Backup замечает отсутствие advertisement (3 * Advertisement Interval).
3. Backup повышает приоритет и забирает VIP.
4. ICMP ping на VIP снова отвечает.

**Критическая настройка:** `advert_int` (интервал advertisement) влияет на скорость фейловера и ICMP downtime.

| Параметр | Значение | Влияние на ICMP |
| :--- | :--- | :--- |
| `advert_int` | 1 сек | Быстрый фейловер, но больше multicast-трафика |
| `master_advert_int` | 3 сек (по умолчанию) | Стандартный баланс |
| `preempt` | on/off | Если on — Backup немедленно забирает VIP при восстановлении Master |

### keepalived и health checks

keepalived может проверять здоровье узлов через ICMP и принимать решение о фейловере на основе результатов.

## Практические сценарии

### 1. Bonding: проверка переключения через ping

```bash
# Создание bonded-интерфейса (active-backup)
sudo modprobe bonding
sudo ip link add bond0 type bond mode active-backup miimon 100
sudo ip link set eth0 master bond0
sudo ip link set eth1 master bond0
sudo ip addr add 10.0.0.5/24 dev bond0
sudo ip link set bond0 up

# Мониторинг переключения через ping
sudo ping -i 0.2 10.0.0.1 &
# В это время выдерните кабель eth0:
# → временные потери пакетов (обычно < 500ms)
# → после переключения пинг продолжается

# Проверка статуса bonding
cat /proc/net/bonding/bond0
# → Bonding Mode: active-backup (fail_over_mac=1)
# → Slave Interface: eth0
# → MII Status: up
# → MII Polling Interval (ms): 100
```

### 2. keepalived: VRRP с ICMP health check

**Конфигурация (`/etc/keepalived/keepalived.conf`):**

```conf
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 150
    advert_int 1

    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }

    # Health check через ICMP (проверка шлюза)
    track_interface {
        eth0
    }

    # Проверка: если шлюз 10.0.0.1 недоступен — снизить приоритет
    track_script {
        check_gw
        weight -50
    }
}

vrrp_script check_gw {
    script "ping -c 1 -W 2 10.0.0.1"
    interval 2
    timeout 5
    fall 2
    rise 2
}
```

**Backup узел (такой же конфиг, но `state BACKUP`, `priority 100`):**

```conf
vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }
}
```

**Проверка работы:**

```bash
# На Master:
ip addr show eth0 | grep 10.0.0.100
# → inet 10.0.0.100/24 scope global secondary eth0

# Ping VIP с клиента:
ping -c 3 10.0.0.100
# → 64 bytes from 10.0.0.100: icmp_seq=1 ttl=64 time=0.5ms

# Отключение Master:
sudo systemctl stop keepalived

# На Backup VIP появился автоматически:
# → 10.0.0.100 переехал на резервный узел

# Пинг в это время теряет 1-2 пакета (failover time)
```

### 3. keepalived: LVS NAT с health check

```conf
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 150
    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }
}

virtual_server 10.0.0.100 443 {
    delay_loop 3
    lb_algo rr
    lb_kind NAT

    real_server 10.0.0.10 443 {
        weight 1
        ICMP_check {
            connect_timeout 3
            nb_get_retry 3
            delay_before_retry 3
        }
    }

    real_server 10.0.0.11 443 {
        weight 1
        ICMP_check {
            connect_timeout 3
            nb_get_retry 3
            delay_before_retry 3
        }
    }
}
```

### 4. VRRP и ICMP Redirect взаимодействие

**Проблема:** в некоторых конфигурациях VRRP может генерировать ICMP Redirect, когда Backup забирает VIP.

**Решение:** отключить отправку Redirect на bonded/VIP-интерфейсах:

```bash
sysctl -w net.ipv4.conf.all.send_redirects=0
sysctl -w net.ipv4.conf.eth0.send_redirects=0
```

### 5. Мониторинг bonded-интерфейса через ping

```bash
# Мониторинг каждого slave отдельно
ping -I eth0 10.0.0.1
ping -I eth1 10.0.0.1

# Проверка, какой slave активен
cat /sys/class/net/bond0/bonding/active_slave
# → eth0

# Проверка счетчиков ошибок на каждом slave
cat /sys/class/net/eth0/statistics/tx_errors
cat /sys/class/net/eth1/statistics/tx_errors
```

### 6. Проверка LACP (802.3ad) через ping

```bash
# Создание LACP bond
sudo ip link add bond0 type bond mode 802.3ad
sudo ip link set eth0 master bond0
sudo ip link set eth1 master bond0
sudo ip link set bond0 up

# Проверка агрегации
cat /proc/net/bonding/bond0
# → Bonding Mode: IEEE 802.3ad Dynamic link aggregation
# → Slave Interface: eth0
# → MII Status: up
# → Speed: 1000 Mbps

# Ping через bonded-интерфейс (трафик идет по обоим slave)
sudo ping -c 100 -I bond0 10.0.0.1
# → проверьте, что потери 0% (оба канала работают)
```

## Дополнительная информация

*   **[Маршрутизация в Linux](../../../Linux/SystemAdministration/routing.md)** — управление таблицами маршрутизации.
*   **[ICMP Redirect](./icmp_redirect.md)** — влияние Redirect на VRRP.
*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — hardening.
*   **[Сетевая диагностика Linux](../../../Linux/Diagnostics/Networking/ping.md)** — утилита ping.
