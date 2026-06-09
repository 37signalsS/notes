# Настройка Keepalived и HAProxy для HA-кластера

> **Надежность: 10** (Подтверждено SSoT по развёртыванию Kubernetes и сетевым инструментам на июнь 2026)

## Определения

**Virtual IP (VIP)** — плавающий IP-адрес, который автоматически перемещается между узлами кластера для обеспечения непрерывного доступа к API-серверу.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол, используемый Keepalived для обнаружения отказов и передачи владения VIP-адресом между участниками кластера.

**HA (High Availability)** — высокая доступность системы, минимизирующая время простоя за счёт устранения единых точек отказа.

**L4 Load Balancer** — балансировщик транспортного уровня, распределяющий трафик на основе IP-адресов и портов без расшифровки содержимого пакетов (в данном случае — без терминации TLS).

---

## Основные концепции

### Роль балансировщика в HA-кластере

В отказоустойчивом кластере Kubernetes балансировщик выполняет две критические функции:

1. **Предоставление единой точки входа**: все компоненты (kubelet, kubectl) обращаются к API-серверу через VIP.
2. **Распределение нагрузки и Failover**: трафик распределяется между всеми доступными мастерами; при выходе из строя одного мастера он автоматически исключается из ротации.

### Архитектурные требования

- **Размещение**: Keepalived и HAProxy должны быть настроены на всех мастер-узлах до начала инициализации кластера через `kubeadm`.
- **Режим работы**: используется TCP Mode (L4), чтобы сохранить оригинальные сертификаты API-сервера и обеспечить прозрачную TLS-связность.
- **Health Checks**: HAProxy должен проверять доступность порта 6443 перед отправкой трафика на узел.

---

## Практические сценарии

### Установка и настройка Keepalived

**Установка на всех мастер-узлах:**

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
    interface ens192  # Укажите ваш сетевой интерфейс
    virtual_router_id 51
    priority 101

    advert_int 1
    authentication {
        auth_type PASS
        auth_pass "supersecret"
    }

    virtual_ipaddress {
        192.168.122.189/24  # Укажите ваш VIP
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
    interface ens192  # Укажите ваш сетевой интерфейс
    virtual_router_id 51
    priority 100     # Приоритет ниже, чем у MASTER

    advert_int 1
    authentication {
        auth_type PASS
        auth_pass "supersecret"
    }

    virtual_ipaddress {
        192.168.122.189/24  # Тот же самый VIP
    }
}
```

**Запуск сервиса:**

```bash
sudo systemctl enable --now keepalived
```

### Установка и настройка HAProxy

**Установка на всех мастер-узлах:**

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
    bind 192.168.122.189:7443  # VIP и порт для входящего трафика
    mode tcp
    option tcplog
    default_backend kubernetes-api-masters

backend kubernetes-api-masters
    mode tcp
    balance roundrobin
    server master1 192.168.122.171:6443 check  # IP первого мастера
    server master2 192.168.122.172:6443 check  # IP второго мастера
    server master3 192.168.122.173:6443 check  # IP третьего мастера

# Статистика HAProxy (доступна на порту 8404)
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 10s
    stats admin if LOCALHOST
```

**Разрешение привязки к "чужому" IP (необходимо, если VIP не поднят локально):**

```bash
sudo sysctl -w net.ipv4.ip_nonlocal_bind=1
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
```

**Запуск сервиса:**

```bash
sudo systemctl enable --now haproxy
```

---

## Дополнительная информация

### См. также

- **[Архитектура HA с Keepalived и HAProxy](./ha_concepts.md)** — теоретические основы и описание работы.
- **[Обзор Keepalived](../../../Networking/ServicesAndTools/keepalived_overview.md)** — SSoT по инструменту Keepalived.
- **[Обзор HAProxy](../../../WebServers/haproxy_overview.md)** — SSoT по инструменту HAProxy.
- **[Инициализация кластера](./cluster_initialization.md)** — следующий шаг после настройки балансировщика.
