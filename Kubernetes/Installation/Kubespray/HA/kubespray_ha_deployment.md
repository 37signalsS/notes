# Kubespray: Развертывание HA-кластера — Практика

## Определения

**Inventory (Инвентарь)** — конфигурационный файл (INI или YAML), описывающий логическую топологию кластера: разделение узлов на роли (master, worker, etcd) и параметры подключения к ним. Рекомендуемый формат — `hosts.yaml` (YAML).

**Group Vars (Групповые переменные)** — иерархическая система настроек в Kubespray, позволяющая переопределять параметры Kubernetes, сетевых плагинов и балансировщиков на уровне всего кластера или отдельных групп узлов. Основные файлы: `all/all.yml` (общие настройки), `k8s_cluster/k8s-cluster.yml` (параметры кластера).

**Inventory Builder** — встроенный инструмент Kubespray (`contrib/inventory_builder/inventory.py`) для автоматической генерации файла `hosts.yaml` на основе списка IP-адресов. Упрощает создание инвентаря для кластеров стандартной топологии (все узлы в одной группе).

**Become** — механизм Ansible для повышения привилегий на целевых узлах (обычно до `root`). Флаг `--become` (или `-b`) обязателен для большинства плейбуков Kubespray, включая все HA-плейбуки.

**Bootstrap-OS** — этап предварительной настройки операционной системы (плейбук `bootstrap-os.yml`), включающий установку базовых зависимостей (python, curl), настройку параметров ядра (sysctl), отключение swap и управление службами (firewall, NTP).

**VIP (Virtual IP)** — плавающий IP-адрес, обеспечивающий единую точку входа для API-сервера. Может управляться через Keepalived (VRRP, L2) или Kube-vip (L2/L3).

**Kubeadm** — базовый инструмент Kubernetes, который Kubespray использует для инициализации компонентов кластера, управления сертификатами и настройки статических подов Control Plane.

**Kubectl drain** — команда подготовки узла к обслуживанию: перемещает все поды на другие узлы (с учётом PodDisruptionBudget), исключая DaemonSet-поды и поды без контроллера. Обязательна перед выводом узла из эксплуатации.

**Kubectl cordon/uncordon** — `cordon` помечает узел как непригодный для планирования новых подов; `uncordon` снимает эту пометку. Используется для плавного обслуживания узлов без прерывания работающих подов.

---

## Основные концепции

### Инфраструктурные требования

Минимальные аппаратные требования для HA-кластера (etcd совмещен с Control Plane) зависят от ожидаемой нагрузки. Ниже приведены базовые значения для стабильной работы:

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (нечётное число) | 2+ | 4 ГБ+ | 40 ГБ+ |
| **Worker** | 2+ | 2+ | 4 ГБ+ | 40 ГБ+ |
| **etcd** | 3 (на master) | 2+ | 8 ГБ+ | SSD 40 ГБ+ |

> **Важно:** Количество master-узлов должно быть нечётным (3, 5, 7) для обеспечения кворума etcd. Общие требования к среде см. в [требованиях к HA-кластеру](../../HA_Cluster_Bare_Metal/k8s_ha_environment_requirements.md).

**Программные требования на Control Node:**
- Python 3.10+ и `python3-venv` / `python3-pip`
- Ansible 2.14+ (согласно `requirements.txt` репозитория)
- Git
- SSH-доступ ко всем целевым узлам по ключу
- Права `sudo` без пароля на целевых узлах

### Подготовка машины управления

Развертывание рекомендуется выполнять с отдельной Linux-системы.

1. **Установка системных зависимостей** (Ubuntu/Debian):
   ```bash
   sudo apt update && sudo apt install -y \
     git python3-pip python3-venv software-properties-common
   ```

2. **Клонирование и создание виртуального окружения:**
   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   python3 -m venv venv
   source venv/bin/activate
   pip install -U pip
   pip install -r requirements.txt
   ```

3. **Настройка SSH-доступа:**
   ```bash
   # Генерация ключа
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_kubespray

   # Копирование на все целевые узлы
   ssh-copy-id -i ~/.ssh/id_kubespray.pub root@192.168.1.10
   ssh-copy-id -i ~/.ssh/id_kubespray.pub root@192.168.1.11
   # ... повторить для всех узлов
   ```

4. **Проверка SSH-доступа:**
   ```bash
   ansible -i inventory/my-cluster/hosts.yaml all -m ping
   # → master-1 | SUCCESS => {"changed": false, "ping": "pong"}
   # → master-2 | SUCCESS => {"changed": false, "ping": "pong"}
   ```

> **Важно:** Пользователь Ansible (указанный в `ansible_user`) должен иметь права `sudo` без пароля. На Ubuntu/Debian это настраивается через файл `/etc/sudoers.d/<user>`.

---

## Практические сценарии

### 1. Конфигурация Inventory

#### YAML формат (рекомендуемый)

YAML-формат提供更多 гибкости и поддерживает вложенную структуру групп.

**Файл `inventory/my-cluster/hosts.yaml`:**
```yaml
all:
  hosts:
    master-1: {ansible_host: 192.168.1.10, ip: 192.168.1.10}
    master-2: {ansible_host: 192.168.1.11, ip: 192.168.1.11}
    master-3: {ansible_host: 192.168.1.12, ip: 192.168.1.12}
    worker-1: {ansible_host: 192.168.1.20, ip: 192.168.1.20}
    worker-2: {ansible_host: 192.168.1.21, ip: 192.168.1.21}
  children:
    kube_control_plane:
      hosts:
        master-1: {}
        master-2: {}
        master-3: {}
    kube_node:
      hosts:
        worker-1: {}
        worker-2: {}
    etcd:
      hosts:
        master-1: {}
        master-2: {}
        master-3: {}
    k8s_cluster:
      children:
        kube_control_plane: {}
        kube_node: {}
```

#### Автоматическая генерация через Inventory Builder

Для стандартных топологий (все узлы с двойной ролью master+worker, или разделение master/worker) можно использовать скрипт:

```bash
# Создание директории инвентаря
cp -rfp inventory/sample inventory/my-cluster

# Генерация hosts.yaml из списка IP
IPS=(192.168.1.10 192.168.1.11 192.168.1.12 192.168.1.20 192.168.1.21)
CONFIG_FILE=inventory/my-cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}
```

> **Важно:** Inventory Builder создаёт упрощённую топологию, где master-узлы также являются worker-узлами. Для HA-конфигурации с выделенными master-узлами рекомендуется редактировать `hosts.yaml` вручную, исключив master-узлы из группы `kube_node`.

#### INI формат

Использование INI формата удобно для небольших статичных инвентарей.

**Файл `inventory/my-cluster/inventory.ini`:**
```ini
[all]
master-1 ansible_host=192.168.1.10 ip=192.168.1.10
master-2 ansible_host=192.168.1.11 ip=192.168.1.11
master-3 ansible_host=192.168.1.12 ip=192.168.1.12
worker-1 ansible_host=192.168.1.20 ip=192.168.1.20
worker-2 ansible_host=192.168.1.21 ip=192.168.1.21

[kube_control_plane]
master-1
master-2
master-3

[etcd]
master-1
master-2
master-3

[kube_node]
worker-1
worker-2

[k8s_cluster:children]
kube_control_plane
kube_node

[all:vars]
ansible_user=root
ansible_ssh_private_key_file=~/.ssh/id_rsa
```

### 2. Сценарий A: HA через Keepalived + HAProxy (Классический метод)

Kubespray автоматически настраивает Keepalived и HAProxy как Static Pods (или системные сервисы) на мастер-узлах. Схема с разделением портов: HAProxy слушает `6443` (внешний), kube-apiserver — `6444` (внутренний).

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**
```yaml
# Включение локального балансировщика (рекомендуется как дополнение)
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443

# Control Plane Endpoint (VIP)
apiserver_loadbalancer_domain: "lb.k8s.local"
loadbalancer_apiserver:
  address: "192.168.1.100"  # VIP адрес
  port: 6443

# Версии компонентов
kube_version: v1.31.0
container_manager: containerd
kube_network_plugin: calico
kube_proxy_mode: ipvs

# Отключение небезопасного HTTP-порта API-сервера
kube_apiserver_insecure_port: 0
```

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**
```yaml
# --- Keepalived ---
enable_keepalived: true
keepalived_virtual_router_id: 51
keepalived_priority: 101
keepalived_password: "k8s-ha-secret"
keepalived_interface: "eth0"

# Unicast-режим (если Multicast заблокирован в сети)
# keepalived_unicast_peers:
#   - 192.168.1.11
#   - 192.168.1.12
```

> **Важно:** `keepalived_password` должен быть одинаковым для всех узлов группы VRRP. Используйте сложный пароль. При Multi-Master развертывании через Static Pods Kubespray автоматически настраивает порты: HAProxy — `6443`, kube-apiserver — `6444`.

### 3. Сценарий B: HA через Kube-vip (Современный метод)

Kube-vip работает как Static Pod и объединяет функции управления VIP и балансировки трафика. Рекомендуемый метод для bare-metal сред.

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**
```yaml
# --- Kube-vip ---
kube_vip_enabled: true
kube_vip_address: "192.168.1.100"
kube_vip_interface: "eth0"

# Режим работы: L2 (ARP) или L3 (BGP)
kube_vip_arp_enabled: true  # true = L2 (ARP), false = L3 (BGP)

# Control Plane VIP (API-сервер)
kube_vip_controlplane_vip: true

# Service LB (опционально, замена MetalLB в простых конфигурациях)
# kube_vip_services_vip: false
# kube_vip_lb_class: ""
```

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**
```yaml
loadbalancer_apiserver:
  address: "192.168.1.100"
  port: 6443
```

> **Важно:** При использовании Kube-vip порт API-сервера и внешний порт совпадают (6443). Kube-vip проксирует трафик на локальный API-сервер. Убедитесь, что `kube_vip_interface` соответствует интерфейсу, который виден другим узлам в сегменте.

### 4. Сценарий C: HA-кластер с локальным балансировщиком (без VIP)

Применяется в средах, где использование плавающего IP невозможно или нежелательно (например, в средах с ограниченной L2-связностью). Локальный nginx-proxy на каждом узле обеспечивает внутреннюю связность кластера (`kubelet` -> `apiserver`).

**Файл `inventory/my-cluster/hosts.yaml`:**
```yaml
all:
  hosts:
    master-1: {ansible_host: 10.128.0.2, ip: 10.128.0.2}
    master-2: {ansible_host: 10.128.0.35, ip: 10.128.0.35}
    master-3: {ansible_host: 10.128.0.16, ip: 10.128.0.16}
    worker-1: {ansible_host: 10.128.0.31, ip: 10.128.0.31}
    worker-2: {ansible_host: 10.128.0.18, ip: 10.128.0.18}
    worker-3: {ansible_host: 10.128.0.38, ip: 10.128.0.38}
  children:
    kube_control_plane:
      hosts: {master-1: {}, master-2: {}, master-3: {}}
    kube_node:
      hosts: {worker-1: {}, worker-2: {}, worker-3: {}}
    etcd:
      hosts: {master-1: {}, master-2: {}, master-3: {}}
    k8s_cluster:
      children: {kube_control_plane: {}, kube_node: {}}
```

**Переменные (`k8s-cluster.yml`):**
```yaml
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443
```

**Развертывание:**
```bash
ansible-playbook -i inventory/my-cluster/hosts.yaml --become cluster.yml
```

> **Ограничение:** Этот метод не обеспечивает внешнюю доступность API-сервера для `kubectl` и CI/CD. Внутренняя связность кластера (kubelet, kube-proxy, scheduler) работает через локальный nginx-proxy на каждом узле.

### 5. Команды управления и обслуживания

#### Основные плейбуки

| Плейбук | Назначение | Важные флаги |
| :--- | :--- | :--- |
| **`cluster.yml`** | Полное развертывание кластера или добавление Control Plane / etcd узлов | `--tags=etcd` (только etcd), `--tags=certificates,kubeadm` (ротация сертификатов) |
| **`scale.yml`** | Добавление новых worker-узлов | `--limit=node_name` (только новый узел) |
| **`upgrade-cluster.yml`** | Последовательное обновление всех компонентов (rolling update) | Требует изменения `kube_version` в переменных |
| **`remove-node.yml`** | Безопасный вывод узла из эксплуатации | `-e node=node_name` (целевой узел) |
| **`reset.yml`** | Полная очистка узлов от компонентов Kubernetes | **Внимание:** все данные будут удалены |
| **`bootstrap-os.yml`** | Предварительная настройка ОС (зависимости, sysctl, swap) | Запускается автоматически перед `cluster.yml` |
| **`facts.yml`** | Сбор актуальных данных о состоянии узлов | Используется для диагностики |

#### Примеры команд

```bash
# Полное развертывание кластера
ansible-playbook -i inventory/my-cluster/hosts.yaml --become cluster.yml

# Добавление worker-узла (с --limit для ускорения)
ansible-playbook -i inventory/my-cluster/hosts.yaml --become scale.yml --limit=worker-3

# Обновление версии Kubernetes
# 1. Изменить kube_version в group_vars/k8s_cluster/k8s-cluster.yml
# 2. Запустить обновление
ansible-playbook -i inventory/my-cluster/hosts.yaml --become upgrade-cluster.yml

# Удаление узла из кластера
ansible-playbook -i inventory/my-cluster/hosts.yaml --become remove-node.yml -e node=worker-2

# Ротация сертификатов
ansible-playbook -i inventory/my-cluster/hosts.yaml cluster.yml --tags=certificates,kubeadm

# Ротация только сертификатов etcd
ansible-playbook -i inventory/my-cluster/hosts.yaml cluster.yml --tags=etcd

# Полный сброс кластера (переиспользование узлов)
ansible-playbook -i inventory/my-cluster/hosts.yaml --become reset.yml
```

> **Важно:** Перед обновлением версии Kubernetes создайте бэкап etcd. Обновление возможно только на одну минорную версию за раз (v1.34 → v1.35, но не v1.33 → v1.35). Подробности — в [Управлении кластером](../cluster_management.md).

---

## Пост-деплой: следующие шаги

После успешного развертывания кластера:

### 1. Копирование kubeconfig

```bash
# Автоматически (если включена переменная kubeconfig_localhost)
ls inventory/my-cluster/artifacts/admin.conf

# Вручную (с мастер-узла)
scp root@192.168.1.10:/etc/kubernetes/admin.conf ~/.kube/config
```

> **Важно:** Файл `admin.conf` содержит root-доступ к кластеру. Храните его в安全ном месте и не коммитьте в Git.

### 2. Проверка состояния узлов

```bash
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                  AGE   VERSION   INTERNAL-IP
# → master-1   Ready    control-plane,master   10m   v1.31.0   192.168.1.10
# → master-2   Ready    control-plane,master   10m   v1.31.0   192.168.1.11
# → master-3   Ready    control-plane,master   10m   v1.31.0   192.168.1.12
# → worker-1   Ready    <none>                 10m   v1.31.0   192.168.1.20
# → worker-2   Ready    <none>                 10m   v1.31.0   192.168.1.21
```

### 3. Проверка системных подов

```bash
kubectl get pods -n kube-system -o wide
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → coredns-5dd5756b68-xxxxx                   1/1     Running   0          10m
# → etcd-master-1                              1/1     Running   0          10m
# → kube-apiserver-master-1                    1/1     Running   0          10m
# → kube-controller-manager-master-1           1/1     Running   0          10m
# → kube-proxy-xxxxx                           1/1     Running   0          10m
# → kube-scheduler-master-1                    1/1     Running   0          10m
```

### 4. Проверка DNS-разрешения

```bash
kubectl run test-dns --image=busybox:1.36 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1
```

### 5. Проверка сетевого плагина

```bash
# Calico
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide

# Cilium
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
```

---

## Проверка и валидация

### 1. Проверка VIP и Keepalived

```bash
# Проверка наличия VIP на интерфейсе (на лидере)
ip a show eth0 | grep 192.168.1.100
# → inet 192.168.1.100/32 scope global eth0

# Проверка статуса службы
systemctl status keepalived
# → Active: active (running)

# Просмотр VRRP логов (переключения)
journalctl -u keepalived --since "1 hour ago" | grep -i "transition"
# → VRRP_Instance(VI_1) Transitioning MASTER -> BACKUP
# → VRRP_Instance(VI_1) Transitioning BACKUP -> MASTER

# Проверка virtual_router_id и приоритетов
cat /etc/keepalived/keepalived.conf | grep -E "virtual_router_id|priority|state"
```

### 2. Проверка Kube-vip

```bash
# Статус пода
kubectl get pods -n kube-system -l name=kube-vip -o wide
# → kube-vip-master-1   1/1     Running   0          10d   master-1

# Логи лидера
kubectl logs -n kube-system -l name=kube-vip --tail=20
# → INFO[0005] Node master-1 is now the leader
# → INFO[0006] Broadcasting gratuitous ARP on eth0
```

### 3. Проверка балансировщиков (HAProxy / nginx-proxy)

```bash
# HAProxy: Проверка статуса бэкендов через сокет
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep -E "kubernetes-api.*UP"
# → kubernetes-api-masters,master-1,0,0,0,0,...,UP,...
# → kubernetes-api-masters,master-2,0,0,0,0,...,UP,...

# Конфигурация HAProxy (проверка health check)
cat /etc/haproxy/haproxy.cfg | grep -A5 "backend kubernetes-api"
# → backend kubernetes-api
# →   balance roundrobin
# →   option httpchk GET /healthz
# →   server master-1 10.0.1.11:6444 check inter 2000 fall 3 rise 2

# Nginx-proxy: Проверка API через локальный порт на воркере
kubectl --server=https://10.128.0.31:6443 get nodes
```

### 4. Проверка Kubernetes API и etcd

```bash
# Проверка через VIP
kubectl --server=https://192.168.1.100:6443 get nodes

# Статус подов etcd
kubectl get pods -n kube-system -l component=etcd -o wide

# Проверка здоровья etcd кластера
kubectl exec -n kube-system -it etcd-master-1 -- \
  etcdctl endpoint health --cluster \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
# → https://10.0.1.11:2379 is healthy
# → https://10.0.1.12:2379 is healthy
# → https://10.0.1.13:2379 is healthy

# Статус etcd (лидер, размер DB)
kubectl exec -n kube-system -it etcd-master-1 -- \
  etcdctl endpoint status --cluster -w table \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
# → | ENDPOINT        | VERSION | DB SIZE | IS LEADER | ...
```

---

## Edge Cases и особенности

### Разные методы HA на разных этапах

На практике методы HA часто комбинируются:
- **Kube-vip** (или Keepalived) для внешнего VIP + **`loadbalancer_apiserver_localhost: true`** для локальной балансировки на каждом узле.
- Такая связка обеспечивает максимальную отказоустойчивость: внешний VIP для клиентов + внутренняя балансировка для кластерных компонентов.

### Конфликт Keepalived и Kube-vip

Если одновременно активны Keepalived и Kube-vip на одном узле, возникает конфликт порта 6443. Kubespray автоматически предотвращает это через переменные `enable_keepalived` и `kube_vip_enabled` — только один метод должен быть активен.

**Признаки конфликта:**
- Порт 6443 уже занят при запуске kube-apiserver.
- Несколько процессов пытаются назначить VIP на один IP.

**Решение:** Убедитесь, что в `all.yml` установлено только одно значение:
```yaml
# Только один из вариантов:
kube_vip_enabled: true
# enable_keepalived: false
```

### Dual-stack (IPv4 + IPv6)

При использовании dual-stack кластера VIP должен быть назначен на стек, который используется для внутренней связи. Убедитесь, что `kube_vip_address` (или `loadbalancer_apiserver.address`) указан для нужного стека.

### Разделение портов API-сервера

При использовании Keepalived + HAProxy Kubespray автоматически разделяет порты:
- **HAProxy:** `6443` (внешний, VIP)
- **kube-apiserver:** `6444` (внутренний, бэкенд)

При использовании Kube-vip:
- **Kube-vip:** `6443` (внешний)
- **kube-apiserver:** `6443` (тот же порт, Kube-vip проксирует)

### Восстановление узла после сбоя

Если мастер-узел временно недоступен и восстановился:

1. **Keepalived:** При `nopreempt=true` (рекомендуется) восстановившийся узел автоматически становится BACKUP. VIP не мигрирует обратно до следующего сбоя текущего MASTER.
2. **Kube-vip:** Узел участвует в Leader Election. При восстановлении он может стать лидером при следующем цикле выборов, если текущий лидер недоступен.
3. **etcd:** Узел автоматически синхронизирует данные с кворумом при восстановлении сетевой связности.

---

## Best Practices

1. **Используйте нечётное число master-узлов** (3, 5) для обеспечения кворума etcd.
2. **Включайте `loadbalancer_apiserver_localhost: true`** даже при наличии внешнего VIP — это обеспечивает внутреннюю связность при недоступности VIP.
3. **Версионируйте инвентарь в Git** — используйте GitOps для отслеживания изменений в `group_vars` и `inventory`.
4. **Создавайте бэкапы etcd** перед каждым обновлением: `etcdctl snapshot save /backup/etcd-$(date +%Y%m%d).db`.
5. **Используйте `--limit`** при добавлении отдельных узлов для ускорения выполнения плейбуков.
6. **Проверяйте статус узлов** (`kubectl get nodes`) перед запуском обновлений — все узлы должны быть `Ready`.
7. **Настройте firewall** для VRRP (proto 112) и API-сервера (порт 6443/6444) между мастер-узлами.
8. **Не используйте `reset.yml`** на production-кластерах без понимания последствий — это полная очистка узлов.

---

## Дополнительная информация

### Сравнение методов балансировки

| Аспект | Keepalived + HAProxy | Kube-vip | nginx-proxy (local) |
| :--- | :--- | :--- | :--- |
| **Единая точка входа** | Да (VIP) | Да (VIP) | Нет (только локально) |
| **Production готовность** | Рекомендуется | Рекомендуется | Тесты / Dev |
| **Отказоустойчивость** | Высокая (VRRP + Health Check) | Высокая (Leader Election) | Средняя (TCP proxy) |
| **Health Check** | HTTP /healthz (HAProxy) + VRRP (Keepalived) | HTTP /healthz (Kube-vip) | Passively (TCP connect) |
| **Connection Draining** | Да (option redispatch) | Да (при leader switch) | Нет |
| **Split-brain защита** | VRRP Priorities + Health Checks | Leader Election (K8s) | Отсутствует |
| **Сложность настройки** | Средняя | Низкая | Минимальная |
| **Тип запуска** | Systemd или Static Pod | Static Pod | Контейнер (containerd) |
| **Внешняя доступность** | Да | Да | Нет |

### См. также

- [Основные концепции HA](./kubespray_ha_concepts.md)
- [Дополнительные темы и Troubleshooting](./kubespray_ha_advanced.md)
- [Управление кластером](../cluster_management.md)
- [Обзор Kubespray](../overview.md)

### Внешние ресурсы

- [Kubespray Documentation](https://kubespray.io/)
- [Kube-vip Architecture](https://kube-vip.io/docs/about/architecture/)
- [Kubeadm HA Topology](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/)
