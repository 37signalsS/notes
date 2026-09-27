# RKE: Высокая доступность (HA)

> [!WARNING]
> **RKE1 достиг конца жизненного цикла (EOL) 31 июля 2025 года.**
> Поддержка прекращена. Данные рекомендации применимы к существующим RKE1-кластерам. Для новых кластеров используйте RKE2.

## Определения

**Высокая доступность (High Availability, HA)** — архитектурный подход, исключающий единую точку отказа (SPOF). Для RKE-кластера это означает наличие минимум 3 control plane + etcd узлов и отказоустойчивой точки входа (VIP/Load Balancer) перед API-сервером.

**Stacked Topology** — топология, при которой etcd и компоненты control plane (API Server, Scheduler, Controller Manager) работают на одном узле. RKE использует эту топологию по умолчанию, совмещая роли `[controlplane, etcd]` на одних узлах.

**External etcd Topology** — топология с выделенными узлами только для etcd. Более надежна для production, но требует вручную определенных узлов с ролью `etcd` без совмещения с control plane.

**Control Plane Endpoint** — виртуальный IP-адрес (VIP) или DNS-имя, которое всегда указывает на доступный API-сервер. Клиенты (kubectl, kubelet, kube-proxy) подключаются по этому адресу, а не по IP конкретного мастера.

**Кворум (Quorum)** — минимальное количество работоспособных узлов etcd для принятия решений. Формула: `Q = (N / 2) + 1`. Для 3 узлов — кворум = 2, допустим 1 отказ. Для 5 узлов — кворум = 3, допустимы 2 отказа.

**Leader Election** — механизм выбора активного экземпляра `kube-scheduler` и `kube-controller-manager` через lease-объекты в API-сервере. Гарантирует, что только один экземпляр выполняет работу.

**Split-Brain** — ситуация network partition, при которой части кластера считают себя главными. Предотвращается кворумом etcd.

---

## Базовые концепции

### Архитектура HA кластера RKE

RKE1 работает иначе, чем kubeadm/Kubespray: все компоненты запускаются как Docker-контейнеры, а управление происходит через SSH. Это накладывает специфические ограничения на HA-архитектуру.

#### Ключевая особенность: SSH-зависимость

RKE CLI подключается к каждому узлу по SSH для управления контейнерами. В HA-сценарии RKE CLI должен иметь SSH-доступ ко **всем** узлам кластера (включая etcd-only узлы). Это означает:
- SSH-ключи должны быть скопированы на все узлы заранее
- Сетевая связность между машиной с RKE CLI и всеми узлами обязательна
- RKE CLI не является частью кластера — это внешняя утилита

#### Сравнение топологий для RKE

| Топология | etcd узлы | Control Plane | Worker | Отказоустойчивость | Рекомендация |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Stacked (по умолчанию)** | На тех же узлах, что и CP | 3 узла `[controlplane, etcd]` | 2+ узла | Средняя | Dev/Test, Small Prod |
| **External etcd** | 3 отдельных узла `[etcd]` | 3 узла `[controlplane]` | 3+ узла | Высокая | Medium/Large Production |

> [!IMPORTANT]
> В RKE1.etcd-узлы НЕ могут быть внешними (external etcd) в той же степени, как в kubeadm. RKE1 управляет etcd как Docker-контейнером на узлах с ролью `etcd`. Однако можно выделить отдельные узлы только с ролью `etcd`, исключив с них control plane.

### Механизм отказоустойчивости

#### При падении worker-узла:
1. Pod-disruption-budget (PDB) определяет, можно ли терять поды
2. `kube-controller-manager` обнаруживает недоступность ноды через `node-monitor-grace-period` (по умолчанию 40 секунд)
3. Поды с нарушением PDB не перезапускаются до восстановления
4. Поды без PDB перезапускаются на других worker-узлах

#### При падении control plane-узла:
1. Оставшиеся 2 API-сервера продолжают работать
2. `kube-scheduler` и `kube-controller-manager` проводят leader election
3. Если etcd на этом узле — кворум поддерживается при наличии 2 из 3 etcd узлов
4. API-серверы обращаются к оставшимся etcd узлам

#### При потере кворума etcd:
1. etcd переходит в режим **только чтение** (read-only)
2. Новые поды не могут быть созданы
3. Существующие поды продолжают работать
4. API-сервер не может обновлять состояние кластера
5. Восстановление: добавление новых etcd узлов или восстановление из снимка

### Требования к сети для HA

| Параметр | Требование | Почему важно |
| :--- | :--- | :--- |
| **Задержка между узлами** | < 10 ms | etcd требует быстрого консенсуса |
| **Пропускная способность** | >= 1 Gbps | Репликация данных etcd, трафик API |
| **Packet Loss** | < 0.1% | Потеря пакетов замедляет Raft-консенсус |
| **DNS** | Резолвинг VIP для API-сервера | kubelet и kube-proxy подключаются по DNS |
| **NTP** | Синхронизация времени на всех узлах | Разброс времени нарушает сертификаты и логи |

### Важные порты для HA

| Порт | Протокол | Назначение | Между кем |
| :--- | :--- | :--- | :--- |
| 22 | TCP | SSH | RKE CLI → все узлы |
| 2379 | TCP | etcd client | API Server → etcd |
| 2380 | TCP | etcd peer | etcd ↔ etcd (кворум) |
| 6443 | TCP | Kubernetes API | VIP → API Server, kubectl → VIP |
| 8472 | UDP | VXLAN (Canal) | Все узлы кластера |
| 9099 | TCP | Canal health | Все узлы → Prometheus |
| 10250 | TCP | kubelet API | API Server → Worker |

---

## Практические сценарии

### Конфигурация HA кластера (cluster.yml)

**Stacked Topology (3 узла controlplane+etcd, 2 worker):**

```yaml
# cluster.yml — HA Stacked Topology
nodes:
  # Control Plane + etcd узлы (3 штуки для кворума)
  - address: 192.168.1.10
    user: ubuntu
    role: [controlplane, etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke
    labels:
      node-role: master

  - address: 192.168.1.11
    user: ubuntu
    role: [controlplane, etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke
    labels:
      node-role: master

  - address: 192.168.1.12
    user: ubuntu
    role: [controlplane, etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke
    labels:
      node-role: master

  # Worker узлы
  - address: 192.168.1.20
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke
    labels:
      node-role: worker
    taints:
      - key: "dedicated"
        value: "worker"
        effect: "NoSchedule"

  - address: 192.168.1.21
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke
    labels:
      node-role: worker

services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h
    quota_backend_bytes: 8589934592  # 8GB

  kube-api:
    service_cluster_ip_range: 10.43.0.0/16
    service_node_port_range: 30000-32767
    extra_args:
      event-ttl: "168h"

  kube-controller:
    cluster_cidr: 10.42.0.0/16

  kubelet:
    cluster_dns_server: 10.43.0.10

network:
  plugin: canal

authentication:
  strategy: x509

ingress:
  provider: nginx

dns:
  provider: coredns
```

**External etcd Topology (3 etcd, 3 controlplane, 3 worker):**

```yaml
# cluster.yml — HA External etcd Topology
nodes:
  # Etcd узлы (только etcd, без control plane)
  - address: 192.168.1.10
    user: ubuntu
    role: [etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.11
    user: ubuntu
    role: [etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.12
    user: ubuntu
    role: [etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke

  # Control Plane узлы (без etcd)
  - address: 192.168.1.20
    user: ubuntu
    role: [controlplane]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.21
    user: ubuntu
    role: [controlplane]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.22
    user: ubuntu
    role: [controlplane]
    ssh_key_path: ~/.ssh/id_rsa_rke

  # Worker узлы
  - address: 192.168.1.30
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.31
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke

  - address: 192.168.1.32
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke

services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h
```

### Настройка Load Balancer перед API-сервером

Для HA необходим внешний балансировщик, направляющий трафик на доступный API-сервер. На bare-metal используют Keepalived + HAProxy.

#### Keepalived + HAProxy

**Установка на выделенную машину (или на каждом control plane-узле):**

```bash
# Установка HAProxy и Keepalived
sudo apt update && sudo apt install -y haproxy keepalived

# Проверка версий
haproxy -v
# → HAProxy version 2.6.12
keepalived --version
# → Keepalived v2.2.8
```

**Конфигурация HAProxy (`/etc/haproxy/haproxy.cfg`):**

```cfg
global
    log /dev/log local0
    maxconn 4096
    stats socket /run/haproxy/admin.sock mode 660 level admin

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  30s
    timeout server  30s
    retries 3

# Frontend: VIP на порту 6443
frontend k8s_api
    bind *:6443
    default_backend k8s_api_backend

# Backend: API-серверы кластера
backend k8s_api_backend
    option httpchk GET /healthz
    http-check expect status 200
    default-server inter 10s downinter 5s rise 2 fall 2 slowstart 60s maxconn 250 maxqueue 250 weight 100
    server master-01 192.168.1.10:6443 check
    server master-02 192.168.1.11:6443 check
    server master-03 192.168.1.12:6443 check

# Stats panel (опционально)
listen stats
    bind *:8404
    stats enable
    stats uri /stats
    stats refresh 10s
```

**Конфигурация Keepalived (`/etc/keepalived/keepalived.conf`):**

```cfg
# Глобальные опции
global_defs {
    router_id LVS_DEVEL
    script_user root
    enable_script_security
}

# VRRP чек-скрипт
vrrp_script check_haproxy {
    script "/usr/bin/pgrep -x haproxy"
    interval 2
    weight 2
    fall 2
    rise 2
}

# VRRP инстанс
vrrp_instance VI_1 {
    state MASTER
    interface eth0
    virtual_router_id 51
    priority 101
    advert_int 1

    authentication {
        auth_type PASS
        auth_pass mypassword  # Замените на безопасный пароль
    }

    virtual_ipaddress {
        192.168.1.100/24  # VIP — замените на ваш
    }

    track_script {
        check_haproxy
    }

    notify_master "/bin/echo 'MASTER' > /tmp/keepalived-state"
    notify_backup "/bin/echo 'BACKUP' > /tmp/keepalived-state"
    notify_fault  "/bin/echo 'FAULT'  > /tmp/keepalived-state"
}
```

> [!IMPORTANT]
> На **каждом** control plane-узле должен быть установлен Keepalived. Один узел — MASTER (получает VIP), остальные — BACKUP. При падении MASTER, VIP переключается на BACKUP с наивысшим приоритетом.

**Запуск и проверка:**

```bash
# Перезапуск сервисов
sudo systemctl restart haproxy keepalived
sudo systemctl enable haproxy keepalived

# Проверка состояния Keepalived
sudo systemctl status keepalived
# → active (running)

# Проверка VIP
ip addr show eth0 | grep 192.168.1.100
# → inet 192.168.1.100/24 scope global secondary eth0

# Проверка HAProxy
curl -k https://192.168.1.100:6443/healthz
# → ok

# Тест failover: остановите HAProxy на MASTER
sudo systemctl stop haproxy
# → VIP должен переключиться на BACKUP-узел
```

#### kube-vip (альтернатива)

[kube-vip](https://kube-vip.io/) — cloud-native решение, работающее как Static Pod. Не требует отдельной машины.

```bash
# Генерация манифеста для kube-vip
export VIP=192.168.1.100
export INTERFACE=eth0
docker run --rm ghcr.io/kube-vip/kube-vip:v0.8.0 manifest pod \
  --interface $INTERFACE \
  --address $VIP \
  --controlPlane \
  --leaderElection | kubectl apply -f -
```

### Верификация HA кластера

```bash
# 1. Проверка узлов (все 3 master должны быть Ready)
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE   VERSION
# → master-01  Ready    controlplane,etcd,worker   30d   v1.28.10
# → master-02  Ready    controlplane,etcd,worker   30d   v1.28.10
# → master-03  Ready    controlplane,etcd,worker   30d   v1.28.10
# → worker-01  Ready    worker                     30d   v1.28.10
# → worker-02  Ready    worker                     30d   v1.28.10

# 2. Проверка доступности API через VIP
curl -k https://192.168.1.100:6443/healthz
# → ok

# 3. Проверка состояния etcd кластера
kubectl get --raw /healthz/etcd
# → ok

# 4. Проверка etcd кворума (на одном из etcd-узлов)
ssh ubuntu@192.168.1.10 "docker exec etcd etcdctl endpoint status --write-out=table"
# → +---------------------------+------------------+---------+---------+
# → |         ENDPOINT          |        ID        | VERSION | DB SIZE |
# → +---------------------------+------------------+---------+---------+
# → | https://192.168.1.10:2379 | 8e9a5b...        | 3.5.10  | 45 MB   |
# → | https://192.168.1.11:2379 | a1b2c3...        | 3.5.10  | 45 MB   |
# → | https://192.168.1.12:2379 | d4e5f6...        | 3.5.10  | 45 MB   |
# → +---------------------------+------------------+---------+---------+

# 5. Проверка leader election
kubectl get lease -n kube-system
# → NAME                  HOLDER                                    AGE
# → kube-controller-manager   master-02_c3b4a1...                    30d
# → kube-scheduler            master-01_d2e5f6...                    30d

# 6. Проверка компонентов
kubectl get componentstatuses
# → NAME                 STATUS    MESSAGE             ERROR
# → controller-manager   Healthy   ok
# → scheduler            Healthy   ok
# → etcd-0               Healthy   {"health":"true"}

# 7. Проверка, что API-серверы доступны через VIP
for i in 1 2 3; do
  echo "Request $i:"
  curl -sk https://192.168.1.100:6443/healthz
done
# → ok
# → ok
# → ok
```

### Тестирование failover

#### Тест 1: Остановка одного control plane-узла

```bash
# Остановка Docker на одном мастер-узле (имитация отказа)
ssh ubuntu@192.168.1.10 "sudo systemctl stop docker"

# Проверка: кластер должен продолжать работать
kubectl get nodes
# → master-01  NotReady   ...  (через 40-50 секунд)
# → master-02  Ready      ...
# → master-03  Ready      ...

# Проверка API через VIP (должен работать через оставшиеся мастер-узла)
curl -k https://192.168.1.100:6443/healthz
# → ok

# Восстановление
ssh ubuntu@192.168.1.10 "sudo systemctl start docker"
# Через 1-2 минуты узел вернется в Ready
kubectl get nodes
# → master-01  Ready  ...
```

#### Тест 2: Потеря кворума etcd (2 из 3 etcd-узлов)

```bash
# Остановка Docker на 2 из 3 etcd-узлов
ssh ubuntu@192.168.1.10 "sudo systemctl stop docker"
ssh ubuntu@192.168.1.11 "sudo systemctl stop docker"

# Проверка: etcd потеряет кворум
kubectl get --raw /healthz/etcd
# → error: etcd cluster is unavailable

# Создание подов будет невозможно
kubectl run test --image=nginx
# → Error from server: etcd cluster is unavailable

# Существующие поды продолжают работать!
kubectl get pods -A
# → (все поды в Running)

# Восстановление
ssh ubuntu@192.168.1.10 "sudo systemctl start docker"
ssh ubuntu@192.168.1.11 "sudo systemctl start docker"
# Через 1-2 минуты кворум восстановится
kubectl get --raw /healthz/etcd
# → ok
```

#### Тест 3: Failover VIP (Keepalived)

```bash
# Проверка текущего MASTER
ssh ubuntu@192.168.1.10 "ip addr show eth0 | grep 192.168.1.100"
# → inet 192.168.1.100/24 scope global secondary eth0  (MASTER)

# Остановка Keepalived на MASTER
ssh ubuntu@192.168.1.10 "sudo systemctl stop keepalived"

# Проверка: VIP должен переключиться на BACKUP
ssh ubuntu@192.168.1.11 "ip addr show eth0 | grep 192.168.1.100"
# → inet 192.168.1.100/24 scope global secondary eth0  (новый MASTER)

# Проверка API через VIP (должен работать)
curl -k https://192.168.1.100:6443/healthz
# → ok

# Восстановление Keepalived на старом MASTER
ssh ubuntu@192.168.1.10 "sudo systemctl start keepalived"
# → Старый MASTER вернется, но VIP останется на текущем MASTER
# (в зависимости от приоритетов и конфигурации preempt)
```

### Масштабирование HA кластера

#### Добавление worker-узла

```bash
# 1. Подготовить новый узел (Docker, SSH)
# 2. Добавить узел в cluster.yml
# 3. Запустить обновление
rke up --config cluster.yml

# 4. Проверка
kubectl get nodes -o wide
# → worker-03  Ready  worker  5m  v1.28.10  192.168.1.33
```

#### Добавление control plane + etcd узла (расширение кворума)

```bash
# 1. Подготовить новый узел
# 2. Добавить узел в cluster.yml с ролью [controlplane, etcd]
# 3. Запустить обновление
rke up --config cluster.yml

# 4. Проверка кворума
ssh ubuntu@192.168.1.10 "docker exec etcd etcdctl member list --write-out=table"
# → Членов должно стать 4 (но кворум останется 3)
```

#### Замена etcd-узла

```bash
# 1. Добавить новый etcd-узел в cluster.yml
# 2. Запустить rke up (новый узел присоединится к кластеру)
rke up --config cluster.yml

# 3. Удалить старый etcd-узел из cluster.yml
# 4. Запустить rke up (старый узел будет удален)
rke up --config cluster.yml

# 5. Проверка кворума
ssh ubuntu@new-etcd-node "docker exec etcd etcdctl member list --write-out=table"
```

### Disaster Recovery для HA кластера

#### Восстановление etcd из снимка

```bash
# 1. Создайте снимок на работоспособном etcd-узле (если есть доступ)
rke etcd snapshot-save --name pre-dr-backup --config cluster.yml

# 2. Остановите Docker на ВСЕХ узлах кластера
for node in 192.168.1.10 192.168.1.11 192.168.1.12 192.168.1.20 192.168.1.21; do
  ssh ubuntu@$node "sudo systemctl stop docker"
done

# 3. Восстановите etcd из снимка на ВСЕХ etcd-узлах
rke etcd snapshot-restore --name pre-dr-backup --config cluster.yml

# 4. Запустите Docker на всех узлах
for node in 192.168.1.10 192.168.1.11 192.168.1.12 192.168.1.20 192.168.1.21; do
  ssh ubuntu@$node "sudo systemctl start docker"
done

# 5. Проверка
kubectl get nodes
kubectl get --raw /healthz/etcd
```

> [!WARNING]
> При восстановлении etcd ВСЕ изменения после создания снимка будут потеряны. Убедитесь, что вы используете самый актуальный снимок.

---

## Эксплуатация и поиск неисправностей

### Типичные HA-проблемы

| Проблема | Симптомы | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **VIP недоступен** | `kubectl` не может подключиться к API | Keepalived не запущен или VIP не назначен | Проверьте `systemctl status keepalived`, `ip addr show` |
| **Split-brain VIP** | VIP назначен на 2 узла одновременно | Неправильная настройка `virtual_router_id` или `auth_pass` | Убедитесь, что `virtual_router_id` и `auth_pass` одинаковы на всех узлах |
| **etcd кворум потерян** | `kubectl get --raw /healthz/etcd` возвращает ошибку | 2+ etcd-узла недоступны | Восстановите etcd-узлы или восстановите из снимка |
| **Leader election loop** | `kube-controller-manager` перезапускается | API-сервер недоступен для обновления lease | Проверьте API-сервер, etcd |
| **Рассинхронизация времени** | Сертификаты "не действительны", логи с ошибками времени | NTP не настроен | Настройте chrony/ntpd на всех узлах |

### Мониторинг HA-кластера

```bash
# Проверка состояния Keepalived
ssh ubuntu@master-01 "sudo systemctl status keepalived"
# → active (running) — MASTER

# Проверка VIP
ip addr show eth0 | grep 192.168.1.100

# Проверка etcd кворума
ssh ubuntu@master-01 "docker exec etcd etcdctl endpoint health --cluster"
# → https://192.168.1.10:2379 is healthy: committed proposal took 15ms
# → https://192.168.1.11:2379 is healthy: committed proposal took 18ms
# → https://192.168.1.12:2379 is healthy: committed proposal took 12ms

# Проверка leader election
kubectl get lease -n kube-system

# Проверка размер etcd
ssh ubuntu@master-01 "docker exec etcd etcdctl endpoint status --write-out=table"
```

---

## Дополнительная информация

### Рекомендации по HA для RKE

* **Минимум 3 etcd-узла** для production. Кворум = 2, допустим 1 отказ.
* **Выделенные etcd-узлы** для medium/large кластеров (отдельно от control plane).
* **SSD/NVMe диски** для etcd — критически важны для стабильности кворума.
* **Keepalived + HAProxy** или **kube-vip** для балансировки API-серверов.
* **Синхронизация времени** (NTP/chrony) на ВСЕХ узлах — обязательно.
* **Резервное копирование etcd** каждые 6 часов (minimum) + перед каждым изменением.
* **Тестирование failover** регулярно — это единственная способ убедиться в HA.

### Ограничения RKE1 для HA

* **SSH-зависимость**: RKE CLI требует SSH-доступа ко всем узлам. Потеря SSH-доступа блокирует управление.
* **Docker-only**: RKE1 не поддерживает containerd. Весь HA-стек работает через Docker.
* **Нет автомасштабирования**: Добавление/удаление узлов только через правку `cluster.yml`.
* **EOL**: RKE1 не получает обновлений. HA-кластер на RKE1 — это legacy-инфраструктура.

### Сравнение HA-подходов

| Подход | RKE1 | RKE2 | kubeadm | Kubespray |
| :--- | :--- | :--- | :--- | :--- |
| **Runtime** | Docker | containerd | Любой CRI | containerd/CRI-O |
| **Управление** | SSH + RKE CLI | Локальный запуск | Локальный запуск | Ansible |
| **Load Balancer** | Keepalived/HAProxy | Keepalived/HAProxy | Keepalived/HAProxy/kube-vip | Keepalived/HAProxy |
| **etcd** | Docker-контейнер | Системный сервис | Статический под | Системный сервис |
| **Восстановление** | rke etcd snapshot-restore | etcdutl snapshot restore | etcdutl snapshot restore | etcdutl snapshot restore |

---

**См. также:**
* [RKE: Основные концепции](./rke_concepts.md)
* [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md)
* [Высокая доступность Kubernetes на Bare-Metal](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
* [Keepalived: Обзор](../../../Networking/ServicesAndTools/keepalived_overview.md)
* [HAProxy: Обзор](../../../WebServers/haproxy_overview.md)
* [etcd: Архитектура и концепции](../../Concepts/etcd_overview.md)
