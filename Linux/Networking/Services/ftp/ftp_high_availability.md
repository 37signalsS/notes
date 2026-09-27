# FTP: Высокая доступность (High Availability)

---

## Определения

**Высокая доступность (High Availability, HA)** — свойство системы, обеспечивающее непрерывность работы и минимальное время простоя (обычно 99.99% и выше). Достигается через резервирование, отказоустойчивость и автоматическое восстановление.

**Keepalived** — демон, обеспечивающий виртуальную IP-адресацию (VIP) и мониторинг состояния сервисов через протокол VRRP (Virtual Router Redundancy Protocol). Используется для создания active-passive кластеров.

**HAProxy** — высокопроизводительный балансировщик нагрузки и reverse proxy, поддерживающий TCP/HTTP балансировку, health checks и SSL termination.

**Active-Passive** — схема HA, где один узел активен (обрабатывает запросы), а второй находится в режиме ожидания (standby). При отказе активного узла происходит автоматическое переключение.

**Active-Active** — схема HA, где все узлы активны и обрабатывают запросы одновременно. Обеспечивает балансировку нагрузки и отказоустойчивость.

**DNS Round-Robin** — метод балансировки нагрузки, при котором DNS-сервер возвращает разные IP-адреса для одного доменного имени. Простой, но не учитывает загрузку серверов.

---

## Основные концепции

### Архитектурные схемы

**Active-Passive (Keepalived):**
```
                     ┌─────────────┐
                     │   VIP       │
                     │ 10.0.0.100  │
                     └──────┬──────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
    ┌─────────▼─────────┐     ┌──────────▼──────────┐
    │   Active Node     │     │   Passive Node      │
    │   10.0.0.1        │     │   10.0.0.2          │
    │   vsftpd          │     │   vsftpd            │
    └───────────────────┘     └─────────────────────┘
```

**Active-Active (HAProxy):**
```
                     ┌─────────────┐
                     │   VIP       │
                     │ 10.0.0.100  │
                     └──────┬──────┘
                            │
                    ┌───────▼───────┐
                    │    HAProxy    │
                    │  (Balance)    │
                    └───────┬───────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
    ┌─────────▼─────────┐     ┌──────────▼──────────┐
    │   FTP Node 1      │     │   FTP Node 2        │
    │   10.0.0.1        │     │   10.0.0.2          │
    │   vsftpd          │     │   vsftpd            │
    └───────────────────┘     └─────────────────────┘
```

**DNS Round-Robin:**
```
DNS-запрос: ftp.example.com
    ↓
Ответ: 10.0.0.1, 10.0.0.2
    ↓
Клиент подключается к 10.0.0.1
```

### Критерии выбора схемы

| Критерий | Active-Passive | Active-Active | DNS Round-Robin |
| :--- | :--- | :--- | :--- |
| **Сложность** | Низкая | Средняя | Низкая |
| **Производительность** | Низкая (один узел) | Высокая (два узла) | Средняя |
| **Отказоустойчивость** | Высокая | Высокая | Средняя |
| **Балансировка** | Нет | Да | Да (простая) |
| **Стоимость** | Низкая (2 узла) | Средняя (2 узла) | Низкая (DNS) |
| **Синхронизация данных** | Обязательна | Обязательна | Не требуется |

### Синхронизация данных

Для Active-Passive и Active-Active необходима синхронизация данных между узлами:

| Метод | Синхронизация | Производительность | Сложность |
| :--- | :--- | :--- | :--- |
| **DRBD** | Блочная (real-time) | Высокая | Средняя |
| **NFS** | Файловая (shared) | Средняя | Низкая |
| **GlusterFS** | Файловая (distributed) | Средняя | Средняя |
| **rsync** | Файловая (periodic) | Низкая | Низкая |

---

## Практические сценарии

### 1. Active-Passive с Keepalived

#### Установка Keepalived

```bash
# На обоих узлах
sudo apt update
sudo apt install keepalived -y
```

#### Конфигурация Active Node

```bash
# /etc/keepalived/keepalived.conf (Active)
global_defs {
    router_id FTP_MASTER
    script_user root
    enable_script_security
}

vrrp_script chk_vsftpd {
    script "/usr/bin/killall -0 vsftpd"
    interval 2
    weight -20
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1
    
    authentication {
        auth_type PASS
        auth_pass ftpsecret
    }
    
    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }
    
    track_script {
        chk_vsftpd
    }
    
    notify_master "/etc/keepalived/notify.sh master"
    notify_backup "/etc/keepalived/notify.sh backup"
    notify_fault "/etc/keepalived/notify.sh fault"
}
```

#### Конфигурация Passive Node

```bash
# /etc/keepalived/keepalived.conf (Passive)
global_defs {
    router_id FTP_BACKUP
    script_user root
    enable_script_security
}

vrrp_script chk_vsftpd {
    script "/usr/bin/killall -0 vsftpd"
    interval 2
    weight -20
    fall 2
    rise 2
}

vrrp_instance VI_1 {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    
    authentication {
        auth_type PASS
        auth_pass ftpsecret
    }
    
    virtual_ipaddress {
        10.0.0.100/24 dev eth0
    }
    
    track_script {
        chk_vsftpd
    }
    
    notify_master "/etc/keepalived/notify.sh master"
    notify_backup "/etc/keepalived/notify.sh backup"
    notify_fault "/etc/keepalived/notify.sh fault"
}
```

#### Скрипт уведомлений

```bash
# /etc/keepalived/notify.sh
#!/bin/bash
STATE=$1
case $STATE in
    master)
        echo "$(date): Node became MASTER" >> /var/log/keepalived-state.log
        systemctl start vsftpd
        ;;
    backup)
        echo "$(date): Node became BACKUP" >> /var/log/keepalived-state.log
        systemctl stop vsftpd
        ;;
    fault)
        echo "$(date): Node in FAULT state" >> /var/log/keepalived-state.log
        systemctl stop vsftpd
        ;;
esac
```

#### Синхронизация данных (rsync)

```bash
# Cron job на Active Node (каждые 5 минут)
# /etc/cron.d/ftp-sync
*/5 * * * * root rsync -avz --delete /home/vsftpd/ backup@10.0.0.2:/home/vsftpd/
```

### 2. Active-Active с HAProxy

#### Конфигурация HAProxy

```bash
# /etc/haproxy/haproxy.cfg
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660 level admin expose-fd listeners
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

defaults
    log     global
    mode    tcp
    option  tcplog
    option  dontlognull
    timeout connect 5000
    timeout client  50000
    timeout server  50000

frontend ftp_front
    bind *:21
    default_backend ftp_servers

backend ftp_servers
    balance roundrobin
    option tcp-check
    server ftp1 10.0.0.1:21 check inter 5s fall 3 rise 2
    server ftp2 10.0.0.2:21 check inter 5s fall 3 rise 2

# Пассивные порты (отдельный backend)
frontend ftp_data_front
    bind *:40000-40100
    default_backend ftp_data_servers

backend ftp_data_servers
    balance roundrobin
    server ftp1 10.0.0.1:40000-40100 check inter 5s fall 3 rise 2
    server ftp2 10.0.0.2:40000-40100 check inter 5s fall 3 rise 2
```

### 3. DNS Round-Robin

```bash
# /etc/bind/db.example.com (BIND)
$TTL 86400
@   IN  SOA ns1.example.com. admin.example.com. (
        2026091401  ; Serial
        3600        ; Refresh
        900         ; Retry
        604800      ; Expire
        86400       ; Negative Cache TTL
)

@   IN  NS  ns1.example.com.
ns1 IN  A   10.0.0.10

ftp IN  A   10.0.0.1
ftp IN  A   10.0.0.2
```

---

## Дополнительная информация

### Диагностика

```bash
# Проверка Keepalived
sudo systemctl status keepalived
sudo journalctl -u keepalived -f

# Проверка VIP
ip addr show eth0 | grep 10.0.0.100

# Проверка HAProxy stats
echo "show stat" | socat stdio /run/haproxy/admin.sock

# Проверка синхронизации
rsync -avzn --delete /home/vsftpd/ backup@10.0.0.2:/home/vsftpd/
```

### Частые ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **VIP не переключается** | Неверный router_id | Проверьте `virtual_router_id` |
| **Split-brain** | Сетевая изоляция узлов | Настройте additional health checks |
| **Данные не синхронизируются** | rsync не работает | Проверьте SSH-ключи и права |
| **HAProxy не балансирует** | Неверные health checks | Проверьте `option tcp-check` |

### Рекомендации для production

1. **Мониторинг:** Настройте алертинг на переключение HA.
2. **Тестирование:** Регулярно проверяйте failover.
3. **Бэкап:** Создавайте бэкапы конфигурации Keepalived/HAProxy.
4. **Документация:** Опишите процедуру восстановления.
5. **Тестирование:** Проводите chaos-тестирование.

### Связанные темы

- **[Keepalived: обзор](../../../Networking/ServicesAndTools/keepalived_overview.md)** — архитектура Keepalived
- **[HAProxy: overview](../../WebServers/haproxy_overview.md)** — балансировщик нагрузки
- **[rsync: синхронизация](../../SystemAdministration/rsync.md)** — инкрементальная синхронизация
- **[vsftpd: настройка](./vsftpd_setup.md)** — базовая конфигурация vsftpd
