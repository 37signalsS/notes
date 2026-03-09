# Настройка Keepalived и HAProxy для HA кластера Kubernetes

## Шаг 1: Установка и настройка Keepalived

**Установка на всех master-узлах:**

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y keepalived

# Rocky Linux/CentOS
sudo dnf install -y keepalived
```

**Конфигурация MASTER-узла** (`/etc/keepalived/keepalived.conf`):

```keepalived
global_defs {
   router_id kube_api_master
}

vrrp_instance VI_1 {
    state MASTER
    interface ens192  # !!! Замените на ваш сетевой интерфейс
    virtual_router_id 51
    priority 101

    advert_int 1
    authentication {
        auth_type PASS
        auth_pass "supersecret"
    }

    virtual_ipaddress {
        192.168.122.189/24  # !!! Замените на ваш VIP
    }
}
```

**Конфигурация BACKUP-узлов:**

```keepalived
global_defs {
   router_id kube_api_backup
}

vrrp_instance VI_1 {
    state BACKUP
    interface ens192  # !!! Замените на ваш сетевой интерфейс
    virtual_router_id 51
    priority 100     # Приоритет ниже, чем у MASTER

    advert_int 1
    authentication {
        auth_type PASS
        auth_pass "supersecret"
    }

    virtual_ipaddress {
        192.168.122.189/24  # !!! Тот же самый VIP
    }
}
```

**Запуск:**

```bash
sudo systemctl enable --now keepalived
```

## Шаг 2: Установка и настройка HAProxy

**Установка на всех master-узлах:**

```bash
# Ubuntu/Debian
sudo apt-get install -y haproxy

# Rocky Linux/CentOS
sudo dnf install -y haproxy
```

**Конфигурация на всех узлах** (`/etc/haproxy/haproxy.cfg`):

```haproxy
global
    log /dev/log    local0
    log /dev/log    local1 notice
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
    timeout connect 5000
    timeout client  50000
    timeout server  50000

frontend kubernetes-api
    bind 192.168.122.189:7443  # !!! Ваш VIP и порт
    mode tcp
    option tcplog
    default_backend kubernetes-api-masters

backend kubernetes-api-masters
    mode tcp
    balance roundrobin
    server master1 192.168.122.171:6443 check  # !!! IP первого master
    server master2 192.168.122.172:6443 check  # !!! IP второго master
    server master3 192.168.122.173:6443 check  # !!! IP третьего master

# (Опционально) Статистика HAProxy
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 10s
    stats admin if LOCALHOST
```

**Разрешение биндинга на "чужой" IP:**

```bash
sudo sysctl -w net.ipv4.ip_nonlocal_bind=1
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
```

**Запуск:**

```bash
sudo systemctl enable --now haproxy
```
