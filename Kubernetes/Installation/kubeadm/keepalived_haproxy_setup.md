# Настройка Keepalived и HAProxy для HA-кластера

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
- **Привязка IP**: Необходимо разрешить сервисам привязку к IP-адресу, который еще не назначен интерфейсу (VIP).

---

## Практические сценарии

### Шаг 1: Установка и настройка Keepalived

**Установка на всех мастер-узлах:**

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y keepalived

# Rocky Linux/RHEL 9
sudo dnf install -y keepalived
```

**Конфигурация MASTER-узла** (`/etc/keepalived/keepalived.conf`):
*Использование скрипта проверки позволяет переключать VIP, если HAProxy перестал работать.*

```keepalived
global_defs {
   router_id kube_api_master
}

# Скрипт для проверки доступности HAProxy
vrrp_script check_haproxy {
    script "killall -0 haproxy" # Проверка наличия процесса
    interval 2
    weight 2
}

vrrp_instance VI_1 {
    state MASTER
    interface eth0  # Замените на имя вашего интерфейса
    virtual_router_id 51
    priority 101
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass "k8s_secret_pass"
    }
    virtual_ipaddress {
        192.168.1.100/24  # Ваш Virtual IP (VIP)
    }
    track_script {
        check_haproxy
    }
}
```

### Шаг 2: Установка и настройка HAProxy

**Конфигурация HAProxy** (`/etc/haproxy/haproxy.cfg`):
*Полная конфигурация с оптимальными тайм-аутами для API Server.*

```haproxy
global
    log /dev/log local0
    log /dev/log local1 notice
    daemon

defaults
    log global
    mode tcp
    option tcplog
    option dontlognull
    timeout connect 5s
    timeout client 50s
    timeout server 50s

frontend kubernetes-api
    bind 192.168.1.100:7443  # VIP и свободный порт
    default_backend kubernetes-api-masters

backend kubernetes-api-masters
    balance roundrobin
    option tcp-check
    server master1 192.168.1.10:6443 check fall 3 rise 2
    server master2 192.168.1.11:6443 check fall 3 rise 2
    server master3 192.168.1.12:6443 check fall 3 rise 2
```

### Шаг 3: Системные настройки и Firewall

**Разрешение привязки VIP:**
```bash
echo "net.ipv4.ip_nonlocal_bind=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

**Настройка Firewall (на примере ufw):**
Необходимо разрешить VRRP-трафик между узлами:
```bash
sudo ufw allow in on eth0 to any proto vrrp
sudo ufw allow 7443/tcp
sudo ufw allow 6443/tcp
```

---

## Дополнительная информация

### Проверка работоспособности

После настройки выполните проверку на каждом узле:
1. `systemctl status keepalived haproxy` — статус сервисов.
2. `ip addr show eth0` — наличие VIP на мастере.
3. `nc -v 192.168.1.100 7443` — проверка доступности порта балансировщика.

### См. также

- **[Архитектура HA с Keepalived и HAProxy](./ha_concepts.md)** — описание принципов работы и схем.
- **[Инициализация кластера](./cluster_initialization.md)** — использование VIP при запуске `kubeadm init`.
- **[Обзор HAProxy](../../../WebServers/haproxy_overview.md)** — подробная информация о настройке балансировщика.
