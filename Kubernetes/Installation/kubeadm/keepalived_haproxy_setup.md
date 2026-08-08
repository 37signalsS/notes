# Настройка Keepalived и HAProxy для HA-кластера

## Определения

**Virtual IP (VIP)** — виртуальный IP-адрес, обеспечивающий единую точку входа (Control Plane Endpoint). Он автоматически перемещается на исправный узел при отказе текущего мастера.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол, на котором базируется работа Keepalived. Позволяет группе узлов формировать один виртуальный маршрутизатор.

**Unicast VRRP** — режим работы Keepalived, при котором VRRP-пакеты отправляются на конкретные IP-адреса соседей, а не в Multicast-группу. Необходим в облаках и сетях, где Multicast заблокирован.

**Gratuitous ARP** — механизм, с помощью которого Keepalived уведомляет сетевое оборудование о том, что VIP-адрес переместился на другой MAC-адрес.

---

## Основные концепции

### Архитектурные требования и подготовка

Для стабильной работы отказоустойчивой связки на мастер-узлах необходимо соблюдение следующих условий:

1.  **Синхронизация времени**: Все узлы должны быть синхронизированы через NTP (например, `chronyd`). Рассинхронизация может привести к проблемам с TLS-сертификатами API.
2.  **Уникальность Router ID**: Поле `virtual_router_id` должно быть уникальным в пределах сегмента сети L2, чтобы избежать конфликтов с другими кластерами.
3.  **Приоритеты (Priority)**: Разница в приоритетах между MASTER и BACKUP должна быть достаточной, чтобы веса `vrrp_script` могли корректно влиять на переключение.
4.  **Разделение портов**: Если балансировщик работает на тех же узлах, что и API-сервер, его `frontend` должен слушать порт, отличный от 6443 (стандарт — 7443 или 8443).

---

## Практические сценарии

### Шаг 1: Системная подготовка

Разрешите процессам привязываться к виртуальному IP, который еще не назначен интерфейсу:

```bash
cat <<EOF | sudo tee /etc/sysctl.d/60-k8s-ha.conf
net.ipv4.ip_nonlocal_bind = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system
```

### Шаг 2: Установка и настройка Keepalived

**Конфигурация для Unicast режима (рекомендуется для 2026 года):**
Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
    router_id K8S_NODE_1
    enable_script_security
    script_user root
}

# Проверка работоспособности локального HAProxy
vrrp_script check_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight 5
    fall 3
    rise 2
}

vrrp_instance VI_1 {
    state BACKUP          # Рекомендуется использовать BACKUP + priority на всех узлах
    interface eth0        # Проверьте имя интерфейса через 'ip a'
    virtual_router_id 51
    priority 100          # На основном мастере поставьте 105
    advert_int 1
    nopreempt             # Предотвращает возврат VIP при восстановлении старого мастера

    authentication {
        auth_type PASS
        auth_pass "k8s_secret_pass"
    }

    # Настройка Unicast (укажите IP всех мастеров)
    unicast_src_ip 192.168.1.10   # IP текущего узла
    unicast_peer {
        192.168.1.11              # IP других мастеров
        192.168.1.12
    }

    virtual_ipaddress {
        192.168.1.100/24 dev eth0 label eth0:vip
    }

    track_script {
        check_haproxy
    }
}
```

### Шаг 3: Установка и настройка HAProxy (v3.4 LTS)

Файл: `/etc/haproxy/haproxy.cfg`

```haproxy
global
    log /dev/log local0
    log /dev/log local1 notice
    daemon
    maxconn 2000
    # Настройка управления через сокет (для диагностики)
    stats socket /var/run/haproxy.sock mode 660 level admin

defaults
    log global
    mode tcp
    option tcplog
    option dontlognull
    timeout connect 10s
    timeout client 1m
    timeout server 1m
    timeout check 5s

frontend k8s-api
    bind 192.168.1.100:7443
    default_backend k8s-api-masters

backend k8s-api-masters
    balance roundrobin
    # HTTP Health Check: проверяет реальную готовность API
    option httpchk GET /healthz
    http-check expect status 200
    
    # Режим check-ssl необходим, так как API работает по HTTPS
    server master1 192.168.1.10:6443 check check-ssl verify none
    server master2 192.168.1.11:6443 check check-ssl verify none
    server master3 192.168.1.12:6443 check check-ssl verify none
```

### Шаг 4: Настройка Firewall

Разрешите VRRP и трафик балансировщика:

```bash
# Для iptables/nftables
sudo iptables -A INPUT -p vrrp -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 7443 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 6443 -j ACCEPT

# Для ufw
sudo ufw allow in proto vrrp
sudo ufw allow 7443,6443/tcp
```

---

## Дополнительная информация

### Диагностика и верификация

| Команда | Цель |
| :--- | :--- |
| `ip addr show label *:vip` | Проверка активного владельца VIP |
| `journalctl -u keepalived -f` | Мониторинг логов переключения ролей |
| `haproxy -c -f /etc/haproxy/haproxy.cfg` | Валидация синтаксиса конфигурации |
| `echo "show stat" | socat /var/run/haproxy.sock stdio` | Просмотр состояния бэкендов в HAProxy |

**Типичные проблемы:**
1.  **Split-brain**: VIP поднят на нескольких узлах одновременно. Причина: Firewall блокирует VRRP пакеты или неверно настроен Unicast.
2.  **HAProxy 503**: Балансировщик работает, но API-серверы помечены как `DOWN`. Проверьте сертификаты и доступность порта 6443 с самого балансировщика.
3.  ** flapping VIP**: Постоянное перемещение VIP. Причина: Слишком малый `advert_int` при высокой нагрузке на сеть.

### См. также

- **[Концепции HA API-сервера](./ha_concepts.md)** — теоретическое обоснование и выбор топологии.
- **[Инициализация кластера](./cluster_initialization.md)** — использование параметра `--control-plane-endpoint`.
- **[Диагностика сети в Linux](../../Linux/Diagnostics/Networking/network_troubleshooting.md)** — общие инструменты отладки стека TCP/IP.
