# IPsec: высокая доступность и failover

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл описывает построение Highly Available (HA) IPsec-инфраструктуры: Active/Passive кластеры, failover, VRRP и автоматическое переключение.

---

## Определения

**Active/Passive (Hot Standby)** — режим, при котором основной шлюз (Active) обрабатывает весь трафик, а резервный (Passive) находится в режиме ожидания. При отказе Active, трафик переключается на Passive.

**VRRP (Virtual Router Redundancy Protocol)** — протокол обеспечения виртуального IP-адреса для группы маршрутизаторов. VRRP VIP используется как gateway для внутренних хостов.

**Health check** — механизм проверки работоспособности удалённого узла или туннеля. Обычно: ping, DPD, check script.

**Split-brain** — ситуация, когда оба узла кластера считают себя Active и обрабатывают трафик одновременно. Приводит к конфликтам и потере данных.

**Floating IP** — IP-адрес, который может мигрировать между узлами кластера при failover.

---

## Основные концепции

### Архитектура Active/Passive IPsec

```
                    +-------------------+
                    |   VRRP VIP       |
                    |   192.168.1.1    |
                    +--------+----------+
                             |
                    +--------v----------+
                    |   Keepalived      |
                    |   (VRRP daemon)   |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
     +--------v----------+     +-----------v---------+
     |   Active Gateway  |     |   Passive Gateway   |
     |   (Master)        |     |   (Backup)          |
     |   192.168.1.2     |     |   192.168.1.3       |
     |   IPsec UP        |     |   IPsec DOWN        |
     +--------+----------+     +-----------+---------+
              |                             |
              +-------------+---------------+
                            |
                   +--------v----------+
                   |   Удалённый шлюз  |
                   |   192.168.2.1     |
                   +-------------------+
```

### Варианты HA для IPsec

| Вариант | Сложность | Время failover | Потеря пакетов | Применение |
|---------|-----------|----------------|----------------|------------|
| **VRRP + Scripts** | Низкая | 3-10 сек | 10-30 пакетов | Малые сети |
| **Keepalived + IPsec** | Средняя | 1-5 сек | 5-15 пакетов | Средние сети |
| **Heartbeat + DRBD** | Высокая | < 1 сек | 1-5 пакетов | Крупные сети |
| **ECMP + BGP** | Высокая | < 1 сек | 0 | Крупные, динамические |

---

## Практические сценарии

### Keepalived + strongSwan (Active/Passive)

#### Установка Keepalived

```bash
# Debian/Ubuntu
sudo apt install keepalived

# RHEL/CentOS/Rocky/Alma
sudo dnf install keepalived
```

#### Конфигурация Active Gateway (`/etc/keepalived/keepalived.conf`)

```bash
vrrp_instance IPSEC_VRRP {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass ipsec-ha
    }

    virtual_ipaddress {
        192.168.1.1/24 dev eth0
    }

    # Проверка работоспособности IPsec
    track_script {
        check_ipsec
    }

    # Мигрируемый IPsec (Floating IP)
    notify_master "/usr/local/bin/ipsec-failover.sh master"
    notify_backup "/usr/local/bin/ipsec-failover.sh backup"
    notify_fault  "/usr/local/bin/ipsec-failover.sh fault"
}
```

#### Конфигурация Passive Gateway (`/etc/keepalived/keepalived.conf`)

```bash
vrrp_instance IPSEC_VRRP {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 90
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass ipsec-ha
    }

    virtual_ipaddress {
        192.168.1.1/24 dev eth0
    }

    track_script {
        check_ipsec
    }

    notify_master "/usr/local/bin/ipsec-failover.sh master"
    notify_backup "/usr/local/bin/ipsec-failover.sh backup"
    notify_fault  "/usr/local/bin/ipsec-failover.sh fault"
}
```

#### Health-check скрипт

```bash
#!/bin/bash
# /usr/local/bin/check_ipsec.sh

REMOTE_GATEWAY="203.0.113.2"
CONN_NAME="site-to-site"

check_ipsec() {
    # Проверка 1: strongSwan SA
    if command -v swanctl &>/dev/null; then
        SA_COUNT=$(swanctl --list-sas 2>/dev/null | grep "$CONN_NAME" | grep -c "ESTABLISHED")
        if [ "$SA_COUNT" -gt 0 ]; then
            return 0
        fi
    fi

    # Проверка 2: ESP-трафик
    ESP_TRAFFIC=$(ip -s xfrm state 2>/dev/null | grep -c "proto esp")
    if [ "$ESP_TRAFFIC" -gt 0 ]; then
        return 0
    fi

    # Проверка 3: Ping через туннель
    if ping -c 1 -W 2 "$REMOTE_GATEWAY" &>/dev/null; then
        return 0
    fi

    return 1
}

check_ipsec
```

```bash
# Конфигурация check в keepalived
# /etc/keepalived/keepalived.conf (внутри vrrp_instance)
vrrp_script check_ipsec {
    script "/usr/local/bin/check_ipsec.sh"
    interval 2
    weight -20
    fall 3
    rise 2
}
```

#### Скрипт failover

```bash
#!/bin/bash
# /usr/local/bin/ipsec-failover.sh

ACTION=$1
CONN_NAME="site-to-site"
REMOTE_IP="203.0.113.2"

case "$ACTION" in
    master)
        echo "[$(date)] Becoming MASTER — initiating IPsec tunnel"
        # Запустить IPsec если не активен
        swanctl --initiate --child "$CONN_NAME" 2>/dev/null || true
        # Или для LibreSwan:
        # ipsec up "$CONN_NAME" 2>/dev/null || true
        ;;
    backup)
        echo "[$(date)] Becoming BACKUP — terminating IPsec tunnel"
        # Остановить IPsec
        swanctl --terminate --child "$CONN_NAME" 2>/dev/null || true
        # Или для LibreSwan:
        # ipsec down "$CONN_NAME" 2>/dev/null || true
        ;;
    fault)
        echo "[$(date)] FAULT detected — attempting recovery"
        # Попытка восстановления
        systemctl restart strongswan
        sleep 5
        swanctl --load-all
        ;;
esac
```

#### Запуск

```bash
# На обоих шлюзах
sudo systemctl enable keepalived
sudo systemctl start keepalived

# Проверка
sudo ip addr show eth0
# → inet 192.168.1.1/24 scope global eth0 (на Active)
# → inet 192.168.1.2/24 scope global eth0 (на Passive)

sudo ipsec status
# → ESTABLISHED (на Active)
# → no SAs established (на Passive)
```

### Ручное переключение

```bash
# На Active: понизить приоритет
sudo ip addr del 192.168.1.1/24 dev eth0 2>/dev/null || true
sudo keepalived -R -p /var/run/keepalived.pid

# Или остановить keepalived (give up MASTER)
sudo systemctl stop keepalived

# На Passive: подняться как MASTER
sudo systemctl start keepalived
```

### Тестирование failover

```bash
# 1. Запустить непрерывный ping
ping -i 0.1 192.168.2.1 &

# 2. На Active: симулировать отказ
sudo systemctl stop strongswan
# Или:
sudo ip xfrm state flush

# 3. Наблюдать переключение
# На Passive: проверить поднятие IPsec
watch -n 1 'swanctl --list-sas'
# → ESTABLISHED (через 1-5 сек)

# 4. Проверить потерю пакетов
# Обычно 5-15 пакетов при failover
```

### Keepalived с нотификациями (Slack/Telegram)

```bash
#!/bin/bash
# /usr/local/bin/ipsec-notify.sh

ACTION=$1
WEBHOOK="${ALERT_WEBHOOK:-}"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

case "$ACTION" in
    master)
        MSG="✅ IPsec Gateway became MASTER: $(hostname)"
        ;;
    backup)
        MSG="⚠️ IPsec Gateway became BACKUP: $(hostname)"
        ;;
    fault)
        MSG="❌ IPsec FAULT detected on: $(hostname)"
        ;;
esac

if [ -n "$WEBHOOK" ]; then
    curl -s -X POST -H 'Content-type: application/json' \
        --data "{\"text\": \"$MSG\"}" \
        "$WEBHOOK" >/dev/null 2>&1
fi

logger "ipsec-ha: $MSG"
```

---

## Управление и диагностика

### Команды Keepalived

```bash
# Статус VRRP
sudo systemctl status keepalived

# Логи
sudo journalctl -u keepalived -f

# Проверка VIP
ip addr show | grep -A2 "vrrp"
# → inet 192.168.1.1/24 scope global secondary eth0

# Тест VRRP
sudo tcpdump -n -i eth0 vrrp -c 5
```

### Диагностика HA

```bash
# 1. Проверка синхронизации Keepalived
sudo journalctl -u keepalived | grep -i "transition\|MASTER\|BACKUP"

# 2. Проверка состояния IPsec на обоих узлах
echo "=== Active ==="
ssh active-gw "swanctl --list-sas"
echo "=== Passive ==="
ssh passive-gw "swanctl --list-sas"

# 3. Проверка XFRM на обоих узлах
echo "=== Active ==="
ssh active-gw "ip xfrm state | grep -c 'proto esp'"
echo "=== Passive ==="
ssh passive-gw "ip xfrm state | grep -c 'proto esp'"

# 4. Проверка маршрута
ip route get 192.168.2.1
# → 192.168.2.1 via 192.168.1.1 dev eth0
```

---

## Типовые проблемы HA

| Проблема | Причина | Решение |
|----------|---------|---------|
| **Split-brain** | Оба узла в состоянии MASTER | Проверить `virtual_router_id`, `auth_pass`, multicast |
| **VIP не мигрирует** | Сетевой интерфейс не мониторится | Проверить `track_interface`, `track_script` |
| **IPsec не поднимается при failover** | `notify_master` скрипт не работает | Проверить права, пути к командам |
| **Потеря > 50 пакетов** | Медленный failover | Уменьшить `advert_int`, проверить health check |
| **Конфликт VIP** | Duplicated VRID в сети | Изменить `virtual_router_id` |
| **Сплит-шлюз** | Оба шлюза претендуют на один VIP | Проверить multicast connectivity |

---

## Дополнительная информация

### Рекомендуемые параметры VRRP

| Параметр | Значение | Описание |
|----------|----------|----------|
| `advert_int` | 1 сек | Интервал объявления VRRP |
| `priority` | 100 (Master), 90 (Backup) | Разница >= 10 |
| `virtual_router_id` | 51 (по умолчанию) | Уникальный в пределах сети |
| `auth_pass` | 8 символов | Общий пароль для VRRP |
| `min_replicas` | 1 | Минимальное количество реплик |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, настройка strongSwan.
- **[Динамическая маршрутизация](./ipsec_routing.md)** — OSPF/BGP для автоматического переключения маршрутов.
- **[Мониторинг IPsec](./ipsec_monitoring.md)** — алертинг и health check.
- **[Производительность IPsec](./ipsec_performance.md)** — нагрузка при failover.
