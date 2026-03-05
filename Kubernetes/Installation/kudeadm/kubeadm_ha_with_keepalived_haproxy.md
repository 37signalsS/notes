# High Availability API-сервера с Keepalived и HAProxy

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **HA Control Plane** | Архитектура с несколькими master-узлами для устранения единой точки отказа (SPOF). |
| **Virtual IP (VIP)** | Плавающий IP-адрес, перемещающийся между узлами кластера. |
| **Control Plane Endpoint** | Единая точка входа для доступа к API-серверу (`<VIP>:<PORT>` или DNS). |
| **L4 Load Balancer** | Балансировщик транспортного уровня (TCP), не терминирующий TLS. |

## 2. Основные концепции

### 2.1. Проблема

В кластере с несколькими master-узлами каждый запускает `kube-apiserver` на порту `6443`. При использовании IP одного узла:

* При отказе узла доступ к API теряется.
* Требуется ручное переключение клиентов (`kubectl`, `kubelet`, `kubeadm join`).

### 2.2. Решение: VIP + L4-балансировщик

```
                    ┌─────────────────────────────────────────┐
                    │           Virtual IP (VIP)              │
                    │         192.168.122.189:7443            │
                    └─────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
              ┌─────▼─────┐   ┌──────▼──────┐   ┌──────▼──────┐
              │ Keepalived│   │ Keepalived  │   │ Keepalived  │
              │  MASTER   │   │   BACKUP    │   │   BACKUP    │
              │           │   │             │   │             │
              │  HAProxy  │   │   HAProxy   │   │   HAProxy   │
              │           │   │             │   │             │
              │ API:6443  │   │  API:6443   │   │  API:6443   │
              └───────────┘   └─────────────┘   └─────────────┘
```

**Компоненты:**

| Компонент | Назначение | Принцип работы |
| :--- | :--- | :--- |
| **Keepalived** | Обеспечение доступности VIP | Протокол VRRP, приоритеты MASTER/BACKUP |
| **HAProxy** | Балансировка трафика к API | TCP mode (`mode tcp`), health checks |

### 2.3. Архитектурные решения

| Решение | Описание |
| :--- | :--- |
| **VIP на другом порту** | HAProxy слушает `VIP:7443`, так как `6443` занят локальным API |
| **TCP балансировка** | HAProxy не терминирует TLS, трафик прозрачно передаётся API Server |
| **Health checks** | HAProxy проверяет доступность API Server перед отправкой трафика |
| **Размещение на хостах** | Keepalived + HAProxy запускаются на хостах (не в K8s) для bootstrap |

## 3. Практические сценарии

### 3.1. Требования

| Компонент | Требование |
| :--- | :--- |
| **Количество master-узлов** | 3 (нечётное число для кворума etcd) |
| **ОС** | Ubuntu 20.04+, Debian 11+, Rocky Linux 9+ |
| **Сеть** | Статические IP, доступ между узлами, свободный VIP |
| **Порты** | 6443 (API), 7443 (HAProxy VIP), 8404 (HAProxy stats, опционально) |

### 3.2. Шаг 1: Установка и настройка Keepalived

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

### 3.3. Шаг 2: Установка и настройка HAProxy

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

### 3.4. Шаг 3: Инициализация кластера kubeadm

**На первом master-узле:**

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.122.189:7443" \
  --upload-certs
```

**На остальных master-узлах:**

```bash
# Используйте команду из вывода kubeadm init
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**На worker-узлах:**

```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### 3.5. Проверка

**Проверка VIP:**

```bash
# На MASTER-узле VIP должен быть активен
ip a | grep 192.168.122.189

# Тест failover: остановить keepalived на MASTER
sudo systemctl stop keepalived
# VIP должен переместиться на BACKUP
```

**Проверка HAProxy:**

```bash
# Статистика (если включена)
curl http://<master-ip>:8404/stats

# Проверка доступности API через VIP
curl -k https://192.168.122.189:7443/healthz
```

**Проверка кластера:**

```bash
kubectl get nodes
kubectl get pods -n kube-system
```

### 3.6. Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **VIP не назначается** | `systemctl status keepalived`, `journalctl -u keepalived` | Проверить интерфейс, priority, `virtual_router_id` |
| **HAProxy не стартует** | `haproxy -c -f /etc/haproxy/haproxy.cfg` | Проверить синтаксис, доступность бэкендов |
| **API недоступен через VIP** | `curl -k https://VIP:7443/healthz` | Проверить `ip_nonlocal_bind`, firewall |
| **Бэкенды DOWN** | `curl http://IP:8404/stats` | Проверить доступность API Server на узлах |
| **VRRP конфликты** | `tcpdump -i <interface> vrrp` | Убедиться в уникальности `virtual_router_id` |

## 4. Дополнительная информация

### 4.1. Связанные темы

* [Быстрый старт с kubeadm](./kubeadm_quickstart.md)
* [HA кластер на bare metal](../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
* [Keepalived обзор](../../Networking/ServicesAndTools/keepalived_overview.md)
* [HAProxy обзор](../../WebServers/Haproxy/haproxy_overview.md)
* [Высокая доступность Kubernetes](../../Base/high_availability.md)

### 4.2. Альтернативы

| Решение | Среда | Описание |
| :--- | :--- | :--- |
| **Cloud Load Balancer** | AWS/GCP/Azure | NLB/ELB для балансировки API Server |
| **kube-vip** | Bare-metal, VM | VIP внутри Kubernetes (DaemonSet) |
| **MetalLB + Ingress** | Bare-metal | Балансировка для сервисов, не для API |

### 4.3. Best Practices

| Практика | Описание |
| :--- | :--- |
| **Нечётное число master** | 3 или 5 узлов для кворума etcd |
| **Размещение в разных стойках** | Избегание SPOF на уровне инфраструктуры |
| **Мониторинг VIP** | Проверка доступности VIP и HAProxy |
| **Тестирование failover** | Регулярная проверка переключения MASTER → BACKUP |
| **Firewall правила** | Открыть порты 6443, 7443, 8404 между master |
