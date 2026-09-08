# Настройка Keepalived и HAProxy для HA-кластера

## Определения

**Keepalived** — демон пользовательского пространства, реализующий протокол VRRP (Virtual Router Redundancy Protocol) для назначения VIP (Virtual IP) одному из узлов группы. Используется в Kubernetes для организации отказоустойчивой Control Plane Endpoint. Основные компоненты: ядро VRRP (обменannounce-пакетами), health-check движок (проверка работоспособности сервисов), notify-скрипты (реакция на смену ролей).

**HAProxy (High Availability Proxy)** — высокопроизводительный TCP/HTTP балансировщик. В контексте Kubernetes HA используется как L4 (TCP) балансировщик, распределяющий входящий трафик с VIP на健康的 kube-apiserver-ы (порт 6443). Отвечает за health-check бэкендов и перенаправление трафика при отказе API-сервера.

**Virtual IP (VIP)** — виртуальный IP-адрес, не привязанный к физическому интерфейсу. Автоматически перемещается между узлами Keepalived-группы при отказе текущего MASTER. Используется как Control Plane Endpoint для kubectl, kubelet и kube-proxy. Подробнее: [Концепции HA API-сервера](./ha_concepts.md).

**VRRP (Virtual Router Redundancy Protocol)** — протокол уровня 3, обеспечивающий автоматическое назначение VIP активному узлу и обнаружение сбоев. Keepalived реализует VRRP с тремя состояниями: MASTER (владеет VIP), BACKUP (ожидание), FAULT (отключён). Подробнее: [VRRP state machine](./ha_concepts.md).

**nopreempt** — режим VRRP, при котором восстановившийся MASTER с более высоким приоритетом **не** отбирает VIP обратно. Рекомендуется для Kubernetes, чтобы избежать лишних переключений VIP и кратковременных разрывов соединений. Подробнее: [nopreempt в ha_concepts](./ha_concepts.md).

**Gratuitous ARP** — неспровоцированный ARP-ответ, с помощью которого Keepalived уведомляет сеть о том, что VIP переместился на другой MAC-адрес. Используется в режиме Multicast для обновления ARP-таблиц в L2-сегменте.

**Unicast VRRP** — режим работы Keepalived, при котором VRRP-пакеты отправляются на конкретные IP-адреса соседей (через `unicast_peer`), а не в Multicast-группу 224.0.0.18. Рекомендуется для 2026 года: работает везде, где заблокирован Multicast.

**ip_nonlocal_bind** — параметр ядра Linux (`net.ipv4.ip_nonlocal_bind = 1`), позволяющий процессам привязываться к IP-адресам, которые ещё не назначены интерфейсу. Критично для HAProxy на BACKUP-узлах, которые не владеют VIP, но должны быть готовы принять трафик при переключении.

**Control Plane Endpoint** — стабильная точка входа (VIP:Port или DNS-имя), через которую все компоненты кластера обращаются к API-серверу. Задаётся через `--control-plane-endpoint` при `kubeadm init`. Обычно: `VIP:7443` (балансировщик) → `Master:6443` (API-сервер).

---

## Основные концепции

### Архитектурные требования

Для стабильной работы Keepalived + HAProxy необходимо:

| Требование | Описание | Проверка |
| :--- | :--- | :--- |
| **Синхронизация времени** | Все узлы через NTP (`chronyd`). Рассинхронизация вызывает проблемы с TLS-сертификатами | `chronyc tracking` |
| **Уникальность Router ID** | `virtual_router_id` должен быть уникальным в L2-сегменте | `grep virtual_router_id /etc/keepalived/keepalived.conf` на всех узлах |
| **Разница приоритетов** | Разрыв приоритетов должен превышать максимальный вес `vrrp_script` | MASTER: 105, BACKUP: 100 |
| **Порт балансировщика** | Frontend HAProxy слушает порт, отличный от 6443 (стандарт — 7443 или 8443) | `ss -tlnp \| grep 7443` |
| **Firewall** | VRRP (протокол 112), порт 7443, порт 6443 — разрешены | `iptables -L -n \| grep -E "112\|7443\|6443"` |
| **ip_nonlocal_bind** | Включён на **всех** Control Plane-узлах | `sysctl net.ipv4.ip_nonlocal_bind` |
| **CRI установлен** | containerd или CRI-O должны работать до развёртывания Keepalived/HAProxy | `systemctl status containerd` |

### Архитектура: путь трафика

```
                          ┌─────────────────────────────────────────────┐
                          │         Kubernetes Cluster                  │
                          │                                             │
kubectl ──► VIP:7443 ───► │ ┌──────────┐    ┌──────────────────────┐   │
  kubelet ──► VIP:7443 ─► │ │Keepalived│───►│ HAProxy (L4, TCP)   │   │
  kube-proxy ──────────►  │ │ (VRRP)   │    │ :7443 → :6443       │   │
                          │ └──────────┘    └──────┬───────────────┘   │
                          │                        │                    │
                          │        ┌───────────────┼───────────────┐   │
                          │        ▼               ▼               ▼   │
                          │   ┌─────────┐    ┌─────────┐    ┌─────────┐│
                          │   │Master-1 │    │Master-2 │    │Master-3 ││
                          │   │  :6443  │    │  :6443  │    │  :6443  ││
                          │   └─────────┘    └─────────┘    └─────────┘│
                          └─────────────────────────────────────────────┘
```

1. **Клиент** обращается к `https://VIP:7443`
2. **Keepalived** направляет пакет на узел, владеющий VIP (MASTER)
3. **HAProxy** на MASTER принимает TCP-соединение на порту 7443
4. **HAProxy** проверяет готовность API-серверов через HTTP-чек `/healthz`
5. **Трафик** пересылается на один из здоровых бэкендов ( Master:6443)

### Два варианта развёртывания

| Характеристика | Systemd-сервисы | Static Pods |
| :--- | :--- | :--- |
| **Управление** | Systemd-юниты (`systemctl`) | Kubelet через манифесты |
| **Порядок запуска** | Сервисы запускаются **до** `kubeadm init` | Запускаются одновременно с Control Plane |
| **Обновление** | Через пакетный менеджер (`apt upgrade`) | Через редактирование манифестов |
| **Диагностика** | `journalctl -u keepalived/haproxy` | `crictl ps`, манифесты в `/etc/kubernetes/manifests/` |
| **Рекомендация** | Отдельные LB-узлы или до инициализации | На тех же узлах, что и Control Plane |
| **Когда использовать** | LB на выделенных серверах | Развёртывание на Control Plane-узлах |

### VRRP: параметры переключения

| Параметр | Описание | Значение по умолчанию | Рекомендация |
| :--- | :--- | :--- | :--- |
| `priority` | Приоритет узла (0-255). Выше = чаще MASTER | 100 | MASTER: 105, BACKUP: 100 |
| `advert_int` | Интервал отправки VRRP-announce (сек) | 1 | 1 сек |
| `nopreempt` | Запрет возврата VIP при восстановлении | выключен | **Включать** в production |
| `fall` | Неудачных проверок до снятия VIP | 3 | 3 |
| `rise` | Успешных проверок до получения VIP | 2 | 2 |
| `virtual_router_id` | Уникальный ID VRRP-группы (0-251) | 51 | Уникальный в L2-сегменте |
| `auth_type` | Тип аутентификации (PASS, AH) | PASS | PASS |
| `garp_master_delay` | Задержка Gratuitous ARP при Become MASTER | 0 | 0-1 |

**Почему nopreempt критичен:** При `preempt` (по умолчанию) восстановившийся MASTER с `priority=105` немедленно отбирает VIP у BACKUP с `priority=100`. Это вызывает кратковременный (1-3 секунды) разрыв **всех** API-соединений. При `nopreempt` VIP остаётся на текущем узле до его отказа — предсказуемее и безопаснее.

---

## Практические сценарии

### Шаг 1: Системная подготовка

#### Включение ip_nonlocal_bind (на всех Control Plane-узлах)

```bash
# Разрешить привязку к VIP до его назначения интерфейсу
cat <<EOF | sudo tee /etc/sysctl.d/60-k8s-ha.conf
net.ipv4.ip_nonlocal_bind = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system

# Проверка
sysctl net.ipv4.ip_nonlocal_bind
# → net.ipv4.ip_nonlocal_bind = 1
```

#### Установка Keepalived (на всех Control Plane-узлах)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y keepalived

# Проверка версии (2.2+ рекомендуется)
keepalived --version
# → Keepalived v2.2.x
```

**RHEL/CentOS/Rocky:**
```bash
sudo dnf install -y keepalived

# Проверка
keepalived --version
```

**Включение и запуск:**
```bash
sudo systemctl enable keepalived
sudo systemctl start keepalived
sudo systemctl status keepalived
# → active (running)
```

#### Установка HAProxy (на всех Control Plane-узлах)

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y haproxy

# Проверка версии (3.x рекомендуется, LTS)
haproxy -v
# → HAProxy version 3.4.x
```

**RHEL/CentOS/Rocky:**
```bash
sudo dnf install -y haproxy

# Проверка
haproxy -v
```

**Включение и запуск:**
```bash
sudo systemctl enable haproxy
sudo systemctl start haproxy
sudo systemctl status haproxy
# → active (running)
```

### Шаг 2: Конфигурация Keepalived

#### Master-узел (priority=105)

Файл: `/etc/keepalived/keepalived.conf`

```keepalived
global_defs {
    router_id K8S_MASTER_1
    enable_script_security
    script_user root
    # Максимальное количество VIP на интерфейсе (по умолчанию 5)
    # max_auto_priority -1 (auto, based on CPU cores)
}

# Проверка работоспособности локального HAProxy
vrrp_script check_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight 5
    fall 3
    rise 2
}

vrrp_instance K8S_VIP {
    state BACKUP          # Рекомендуется BACKUP + priority на всех узлах
    interface eth0        # Проверьте: ip -br addr show
    virtual_router_id 51  # Уникальный в L2-сегменте
    priority 105          # Выше чем на BACKUP-узлах
    advert_int 1
    nopreempt             # Не отбирать VIP при восстановлении

    authentication {
        auth_type PASS
        auth_pass "k8s_ha_secret"
    }

    # Unicast (рекомендуется для 2026 года)
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

    # Notify-скрипты (опционально, для логирования/мониторинга)
    notify_master "/etc/keepalived/notify.sh master"
    notify_backup "/etc/keepalived/notify.sh backup"
    notify_fault  "/etc/keepalived/notify.sh fault"
}
```

#### Backup-узел (priority=100)

```keepalived
global_defs {
    router_id K8S_MASTER_2
    enable_script_security
    script_user root
}

vrrp_script check_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight 5
    fall 3
    rise 2
}

vrrp_instance K8S_VIP {
    state BACKUP
    interface eth0
    virtual_router_id 51  # Тот же ID, что и на MASTER
    priority 100          # Ниже чем на MASTER
    advert_int 1
    nopreempt

    authentication {
        auth_type PASS
        auth_pass "k8s_ha_secret"
    }

    unicast_src_ip 192.168.1.11   # IP этого узла
    unicast_peer {
        192.168.1.10              # IP первого мастера
        192.168.1.12              # IP третьего мастера
    }

    virtual_ipaddress {
        192.168.1.100/24 dev eth0 label eth0:vip
    }

    track_script {
        check_haproxy
    }

    notify_master "/etc/keepalived/notify.sh master"
    notify_backup "/etc/keepalived/notify.sh backup"
    notify_fault  "/etc/keepalived/notify.sh fault"
}
```

#### Notify-скрипт (одинаковый на всех узлах)

Файл: `/etc/keepalived/notify.sh`

```bash
#!/bin/bash
# Notify-скрипт для Keepalived
# Аргументы: $1 = master|backup|fault

STATE=$1
HOSTNAME=$(hostname)
VIP="192.168.1.100"
LOGFILE="/var/log/keepalived-notify.log"

log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [$HOSTNAME] $1" >> "$LOGFILE"
}

case "$STATE" in
    master)
        log_message "MASTER: VIP $VIP назначен на этом узле"
        # Опционально: уведомление в Telegram/Slack
        # curl -s -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
        #   -d chat_id=<CHAT_ID>&text="VIP $VIP → MASTER on $HOSTNAME"
        ;;
    backup)
        log_message "BACKUP: Узел перешёл в режим резерва"
        ;;
    fault)
        log_message "FAULT: Узел обнаружила проблему с VIP"
        ;;
esac
```

```bash
sudo chmod +x /etc/keepalived/notify.sh
```

### Шаг 3: Конфигурация HAProxy

Файл: `/etc/haproxy/haproxy.cfg`

#### Рекомендуемая конфигурация (Production-ready)

```haproxy
# ──────────────────────────────────────────────────────────
# Global settings
# ──────────────────────────────────────────────────────────
global
    log /dev/log local0
    log /dev/log local1 notice
    chroot /var/lib/haproxy
    daemon
    maxconn 4000

    # SSL-настройки (опционально, для усиления безопасности)
    # ssl-default-bind-ciphersuites TLS_AES_128_GCM_SHA256:TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256
    # ssl-default-bind-options prefer-client-ciphers no-sslv3 no-tlsv10 no-tlsv11

    # Управление через сокет (для диагностики)
    stats socket /var/run/haproxy.sock mode 660 level admin expose-fd listeners
    stats timeout 30s

# ──────────────────────────────────────────────────────────
# Default settings
# ──────────────────────────────────────────────────────────
defaults
    log global
    mode tcp
    option tcplog
    option dontlognull
    option redispatch          # Перенаправлять соединения при отказе бэкенда
    retries 3

    timeout connect 10s
    timeout client  1h         # 1 час для kubectl exec/logs -f (long-running)
    timeout server  1h         # 1 час для долгоживущих соединений
    timeout check   5s
    timeout http-request 10s
    timeout http-keep-alive 10s

    # Лимит ошибок для предотвращения flapping
    default-server inter 3s fall 3 rise 2

# ──────────────────────────────────────────────────────────
# Stats endpoint (для мониторинга)
# ──────────────────────────────────────────────────────────
frontend stats
    bind *:9000
    mode http
    stats enable
    stats uri /stats
    stats refresh 10s
    stats auth admin:k8s_ha_stats_password
    stats admin if LOCALHOST

# ──────────────────────────────────────────────────────────
# Frontend: принимает трафик на VIP
# ──────────────────────────────────────────────────────────
frontend k8s_api
    bind *:7443
    default_backend k8s_api_servers

# ──────────────────────────────────────────────────────────
# Backend: балансировка на kube-apiserver
# ──────────────────────────────────────────────────────────
backend k8s_api_servers
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200

    # Каждый сервер: IP:PORT check check-ssl verify none
    # inter: интервал проверки, fall: до marked DOWN, rise: до marked UP
    server master1 192.168.1.10:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master2 192.168.1.11:6443 check check-ssl verify none inter 3s fall 3 rise 2
    server master3 192.168.1.12:6443 check check-ssl verify none inter 3s fall 3 rise 2
```

#### Параметры таймаутов

| Параметр | Значение | Почему именно так |
| :--- | :--- | :--- |
| `timeout connect 10s` | Время на установку TCP-соединения с бэкендом | 10 секунд достаточно для локальной сети |
| `timeout client 1h` | Максимальное время жизни клиентского соединения | `kubectl exec`, `kubectl logs -f`, `kubectl port-forward` создают долгоживущие streaming-соединения. При 50 секундах они разрывались бы |
| `timeout server 1h` | Максимальное время ответа от бэкенда | Аналогично: API-сервер может долго обрабатывать large list/watch запросы |
| `timeout check 5s` | Время на выполнение health-check | Слишком мало → ложные DOWN, слишком много → медленное переключение |
| `option redispatch` | Перенаправлять соединения при отказе бэкенда | Без этого соединение с павшим бэкендом будет потеряно |

#### Проверка и применение конфигурации

```bash
# Валидация синтаксиса (обязательно перед restart!)
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Применение без остановки (graceful reload)
sudo systemctl reload haproxy

# Проверка статуса
sudo systemctl status haproxy
# → active (running)
```

### Шаг 4: Настройка Firewall

#### iptables/nftables

```bash
# VRRP (протокол 112) — обязателен для Keepalived
sudo iptables -A INPUT -p vrrp -j ACCEPT

# HAProxy frontend (VIP → клиент)
sudo iptables -A INPUT -p tcp --dport 7443 -j ACCEPT

# kube-apiserver (для health-check HAProxy → API)
sudo iptables -A INPUT -p tcp --dport 6443 -j ACCEPT

# Stats endpoint (только с localhost или доверенных IP)
sudo iptables -A INPUT -p tcp --dport 9000 -s 127.0.0.1/32 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9000 -j DROP

# Сохранение правил
sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

#### firewalld (RHEL/CentOS)

```bash
sudo firewall-cmd --permanent --add-protocol=vrrp
sudo firewall-cmd --permanent --add-port=7443/tcp
sudo firewall-cmd --permanent --add-port=6443/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-protocols
sudo firewall-cmd --list-ports
```

#### ufw (Ubuntu)

```bash
sudo ufw allow in proto vrrp
sudo ufw allow 7443/tcp
sudo ufw allow 6443/tcp
sudo ufw reload
sudo ufw status
```

### Шаг 5: Развёртывание как Static Pods (альтернатива)

Если Keepalived и HAProxy должны управляться kubelet (а не systemd), разместите манифесты в `/etc/kubernetes/manifests/` **до** запуска `kubeadm init`.

#### Keepalived Static Pod

Файл: `/etc/kubernetes/manifests/keepalived.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: keepalived
  namespace: kube-system
  labels:
    component: keepalived
    tier: control-plane
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: keepalived
    image: docker.io/osixia/keepalived:2.0.20
    args:
    - --dont-fork
    - --log-console
    - --use-file=/etc/keepalived/keepalived.conf
    volumeMounts:
    - mountPath: /etc/keepalived/keepalived.conf
      name: conf
      readOnly: true
    - mountPath: /dev
      name: dev
    - mountPath: /etc/keepalived/checks
      name: checks
      readOnly: true
    securityContext:
      capabilities:
        add:
        - NET_ADMIN
        - NET_BROADCAST
        - NET_RAW
  volumes:
  - hostPath:
      path: /etc/keepalived/keepalived.conf
    name: conf
  - hostPath:
      path: /dev
    name: dev
  - hostPath:
      path: /etc/keepalived/checks
    name: checks
```

#### HAProxy Static Pod

Файл: `/etc/kubernetes/manifests/haproxy.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: haproxy
  namespace: kube-system
  labels:
    component: haproxy
    tier: control-plane
spec:
  hostNetwork: true
  priorityClassName: system-node-critical
  containers:
  - name: haproxy
    image: docker.io/library/haproxy:3.4-alpine
    args:
    - -f
    - /usr/local/etc/haproxy/haproxy.cfg
    volumeMounts:
    - mountPath: /usr/local/etc/haproxy/haproxy.cfg
      name: conf
      readOnly: true
    - mountPath: /var/run
      name: sock
    ports:
    - containerPort: 7443
      hostPort: 7443
      name: https-api
      protocol: TCP
    - containerPort: 9000
      hostPort: 9000
      name: stats
      protocol: TCP
  volumes:
  - hostPath:
      path: /etc/haproxy/haproxy.cfg
    name: conf
  - hostPath:
      path: /var/run/haproxy
    name: sock
```

### Шаг 6: Альтернатива — Nginx Stream Module

Если HAProxy по каким-то причинам не подходит, можно использовать Nginx с модулем `stream` (L4 TCP-балансировщик):

#### Установка Nginx

```bash
# Ubuntu/Debian (nginx-full включает stream)
sudo apt install -y nginx-full

# RHEL/CentOS
sudo dnf install -y nginx-mod-stream
```

#### Конфигурация (nginx.conf)

```nginx
# В секции http{} — не Required для stream
# В корне nginx.conf или отдельный файл /etc/nginx/conf.d/k8s-upstream.conf

stream {
    log_format k8s_log '$remote_addr [$time_local] '
                       '$protocol $status $bytes_sent $bytes_received '
                       '$session_time';
    access_log /var/log/nginx/k8s_access.log k8s_log;

    upstream k8s_api {
        least_conn;
        server 192.168.1.10:6443 max_fails=3 fail_timeout=10s;
        server 192.168.1.11:6443 max_fails=3 fail_timeout=10s;
        server 192.168.1.12:6443 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 7443;
        proxy_pass k8s_api;
        proxy_connect_timeout 10s;
        proxy_timeout 1h;           # Аналог timeout server в HAProxy
        proxy_next_upstream on;      # Аналог option redispatch
        proxy_next_upstream_tries 3;
    }
}
```

#### Сравнение HAProxy vs Nginx Stream

| Критерий | HAProxy | Nginx Stream |
| :--- | :--- | :--- |
| **HTTP health-check** | Нативная поддержка `/healthz` | Требует Lua или separate healthcheck |
| **Сокет управления** | Да (`show stat`, `show servers state`) | Нет нативного |
| **TLS-терминация** | Да (L7) | Да (L7) |
| **Connection draining** | Да (через `option redispatch`) | Да (через `proxy_next_upstream`) |
| **Конфигурация** | Единый файл `/etc/haproxy/haproxy.cfg` | `nginx.conf` + модули |
| **Логирование** | Структурированное (syslog) | Стандартное Nginx |
| **Рекомендация** | **Для Kubernetes** | Если уже используется Nginx |

### Шаг 7: Diagnostics и мониторинг

#### Диагностические команды

| Команда | Цель |
| :--- | :--- |
| `ip addr show label *:vip` | Проверка активного владельца VIP |
| `ip a \| grep 192.168.1.100` | Быстрая проверка, на каком узле VIP |
| `journalctl -u keepalived -f` | Мониторинг логов переключения ролей |
| `journalctl -u keepalived --since "1 hour ago" \| grep -E "MASTER\|BACKUP"` | История переключений |
| `journalctl -u haproxy -f` | Мониторинг HAProxy |
| `haproxy -c -f /etc/haproxy/haproxy.cfg` | Валидация синтаксиса конфигурации |
| `echo "show stat" \| socat /var/run/haproxy.sock stdio` | Просмотр состояния бэкендов |
| `echo "show info" \| socat /var/run/haproxy.sock stdio` | Общая информация о HAProxy |
| `echo "show servers state" \| socat /var/run/haproxy.sock stdio` | Текущее состояние серверов |
| `echo "disable server k8s_api_servers/master1" \| socat /var/run/haproxy.sock stdio` | Временное отключение бэкена |
| `echo "enable server k8s_api_servers/master1" \| socat /var/run/haproxy.sock stdio` | Включение бэкена |
| `echo "get weight k8s_api_servers/master1" \| socat /var/run/haproxy.sock stdio` | Просмотр веса сервера |
| `curl -k https://192.168.1.100:7443/healthz` | Проверка доступности API через VIP |
| `curl -k https://192.168.1.100:9000/stats;echo` | Доступ к статистике HAProxy (через браузер) |

#### Мониторинг через Prometheus (опционально)

Keepalived можно экспортировать в Prometheus через `keepalived-exporter`:

```bash
# Установка keepalived-exporter
# https://github.com/expressen-gmbh/keepalived_exporter

# В keepalived.conf добавить:
# keepalived_exporter {
#     address ":9120"
#     scrape_interval "10s"
# }

# В prometheus.yml:
# - job_name: 'keepalived'
#   static_configs:
#     - targets: ['192.168.1.10:9120', '192.168.1.11:9120', '192.168.1.12:9120']
```

### Шаг 8: Типичные ошибки и решения

| Ошибка | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **VIP «плавает»** | VIP постоянно переключается между узлами | Слишком малый `advert_int` или сбой сети | Увеличьте `advert_int` до 2-3 сек; проверьте `tcpdump -i eth0 vrrp` |
| **Split-brain** | VIP поднят на нескольких узлах одновременно | Firewall блокирует VRRP-пакеты или неверный `virtual_router_id` | `iptables -A INPUT -p vrrp -j ACCEPT`; проверьте `virtual_router_id` одинаков |
| **VIP не переключается** | MASTER недоступен, но VIP не переходит на BACKUP | VRRP заблокирован firewall илиicast_src_ip неверен | Проверьте `ip a`; `journalctl -u keepalived -f`; `tcpdump -i eth0 vrrp` |
| **HAProxy 503** | Балансировщик работает, но все бэкены DOWN | API-сервер не отвечает на `/healthz` или сертификат истёк | `curl -k https://master1:6443/healthz`; проверьте сертификаты `kubeadm certs check-expiration` |
| **haproxy: bind error** | HAProxy не запускается, `Address already in use` | Другой процесс слушает порт 7443 | `ss -tlnp \| grep 7443`; убейте конфликтующий процесс |
| **notify-скрипт не работает** | VIP переключается, но уведомлений нет | Скрипт не executable или синтаксическая ошибка | `chmod +x /etc/keepalived/notify.sh`; проверьте вручную: `bash -x /etc/keepalived/notify.sh master` |
| **keepalived: VRRP socket error** | `Problem binding parentId of VRRP instance` | Сокет VRRP уже используется | Убедитесь, что не запущены два экземпляра keepalived |
| **connection refused** | `kubectl` выдает `The connection to the server was refused` | VIP доступен, но HAProxy не пересылает трафик | Проверьте `journalctl -u haproxy`; `echo "show stat" \| socat /var/run/haproxy.sock stdio` |
| **timeout при exec** | `kubectl exec` обрывается через 50 сек | Стандартный timeout 50 секунд | Увеличьте `timeout client` и `timeout server` до `3600000ms` (1 час) |

### Шаг 9: Тестирование Failover

```bash
# 1. Определите текущий MASTER
ip addr show | grep 192.168.1.100
# → inet 192.168.1.100/24 scope global secondary eth0:vip

# 2. Запустите непрерывный опрос API
while true; do
  kubectl get nodes > /dev/null 2>&1 && echo -n "." || echo -n "X"
  sleep 1
done
# Вывод: .............  (точки = OK, X = ошибка)

# 3. Остановите Keepalived на MASTER
sudo systemctl stop keepalived

# 4. Результат
# → Допускается 1-2 "X", после чего точки должны возобновиться
# → VIP появится на другом узле
# → Время failover: 1-3 секунды

# 5. Проверка
ip addr show | grep 192.168.1.100
# → Теперь на другом узле

# 6. Восстановление
sudo systemctl start keepalived
# → При nopreempt VIP останется на текущем MASTER
# → При preempt VIP вернётся обратно (если включено)
```

### Шаг 10: Откат и очистка

```bash
# Остановка сервисов
sudo systemctl stop keepalived
sudo systemctl stop haproxy

# Удаление VIP (если остался)
sudo ip addr del 192.168.1.100/24 dev eth0 label eth0:vip 2>/dev/null

# Удаление конфигов
sudo rm -f /etc/keepalived/keepalived.conf
sudo rm -f /etc/haproxy/haproxy.cfg

# Удаление пакетов
# Ubuntu/Debian
sudo apt purge -y keepalived haproxy
sudo apt autoremove -y

# RHEL/CentOS
sudo dnf remove -y keepalived haproxy

# Очистка sysctl
sudo rm -f /etc/sysctl.d/60-k8s-ha.conf
sudo sysctl --system

# Очистка firewall
sudo iptables -D INPUT -p vrrp -j ACCEPT
sudo iptables -D INPUT -p tcp --dport 7443 -j ACCEPT
sudo iptables -D INPUT -p tcp --dport 6443 -j ACCEPT
```

---

## Дополнительная информация

### Безопасность

1. **Пароль VRRP**: Замените `k8s_ha_secret` на сложный пароль. Должен быть одинаковым на всех узлах группы.
2. **Stats endpoint**: Защитите паролем (`stats auth`) и ограничьте доступ через firewall.
3. **Firewall**: Порт 6443 (API) и 7443 (VIP) — только для доверенных сетей.
4. **Логирование**: Настройте ротацию логов: `/etc/logrotate.d/keepalived` и `/etc/logrotate.d/haproxy`.
5. **SELinux**: На RHEL/CentOS убедитесь, что SELinux не блокирует keepalived: `setsebool -P haproxy_connect_any 1`.

### Best Practices

1. **Используйте Unicast** — Multicast заблокирован в большинстве сред (2026).
2. **Включайте nopreempt** — предотвращает лишние переключения VIP.
3. **Настройте notify-скрипты** — для мониторинга и уведомлений.
4. **Используйте HTTP health-check** (`/healthz`) вместо TCP — проверяет реальную готовность API.
5. **Увеличьте timeout client/server до 1 часа** — для `kubectl exec/logs -f`.
6. **Проверяйте синтаксис HAProxy перед restart** — `haproxy -c -f ...`.
7. **Храните конфиги в Git** — для воспроизводимости и версионирования.
8. **Делайте бэкапы конфигов** — перед каждым изменением.
9. **Мониторьте через Stats/UI** — порт 9000 с аутентификацией.
10. **Тестируйте failover регулярно** — не реже 1 раза в месяц.

### См. также

- **[Концепции HA API-сервера](./ha_concepts.md)** — VRRP state machine, Multicast vs Unicast, kube-vip comparison, etcd quorum.
- **[Инициализация кластера](./cluster_initialization.md)** — использование параметра `--control-plane-endpoint`.
- **[Подготовка узлов](../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — установка пакетов и настройка системы.
- **[Верификация HA](../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)** — тестирование failover и Health Check.
- **[Подготовка окружения](../HA_Cluster_Bare_Metal/k8s_ha_environment_requirements.md)** — требования к инфраструктуре.
