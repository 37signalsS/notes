# Kubespray: Развертывание HA-кластера — Практика

## Определения

Основные термины и архитектурные концепции HA-кластера Kubespray представлены в [основных концепциях](./kubespray_ha_concepts.md).

## Основные концепции

### Инфраструктурные требования

Минимальные аппаратные требования для HA-кластера (etcd совмещен с Control Plane):

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (нечетное число) | 2+ | 4 ГБ+ | 40 ГБ+ |
| **Worker** | 2+ | 2+ | 4 ГБ+ | 40 ГБ+ |
| **etcd** | 3 (на master) | 2+ | 8 ГБ+ | SSD 40 ГБ+ |

> **Важно:** Количество master-узлов должно быть нечетным (3, 5, 7) для обеспечения кворума etcd. Общие требования к среде см. в [требованиях к HA-кластеру](../../HA_Cluster_Bare_Metal/k8s_ha_environment_requirements.md).

---

## Практические сценарии

### 1. Конфигурация Inventory (INI формат)

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

[calico_rr]

[vault]
vault-1

[all:vars]
ansible_user=root
ansible_ssh_private_key_file=~/.ssh/id_rsa
```

### 2. Сценарий A: HA через Keepalived + HAProxy (Классический)

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**

```yaml
# Включение локального балансировщика (HAProxy на каждом master)
loadbalancer_apiserver_localhost: true

# VIP для доступа к API
apiserver_loadbalancer_domain: "lb.k8s.local"
loadbalancer_apiserver:
  address: "192.168.1.100"  # VIP адрес
  port: 6443

# Версия Kubernetes
kube_version: v1.31.0

# Container runtime (containerd рекомендуется)
container_manager: containerd

# Сетевой плагин
kube_network_plugin: calico

# Режим kube-proxy (ipvs производительнее для HA)
kube_proxy_mode: ipvs
```

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**

```yaml
# Включение Keepalived
enable_keepalived: true

# Конфигурация Keepalived
keepalived_virtual_router_id: 51
keepalived_priority: 100  # Будет переопределено для master/backup
keepalived_auth_pass: "k8s-ha-secret"

# Разрешить небезопасный порт API (опционально)
kube_apiserver_insecure_port: 0
```

### 3. Сценарий B: HA через Kube-vip (Рекомендуемый современный)

Этот метод не требует HAProxy и работает через Static Pods.

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**

```yaml
# Включение Kube-vip
kube_vip_enabled: true
kube_vip_address: "192.168.1.100"
kube_vip_interface: "eth0"
kube_vip_arp_enabled: true  # Режим Layer 2 (ARP)
```

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**

```yaml
loadbalancer_apiserver:
  address: "192.168.1.100"
  port: 6443
```

### 4. Развертывание кластера

**Запуск playbook:**

```bash
cd kubespray

# Полное развертывание
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become --become-user=root \
  cluster.yml
```

**Пошаговое выполнение (для отладки):**

```bash
# 1. Подготовка узлов (установка зависимостей, настройка ядра)
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become bootstrap-os.yml

# 2. Развертывание кластера (основной этап)
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become cluster.yml

# 3. Переустановка/восстановление при сбоях
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become recover-node.yml
```

---

### 5. Сценарий: HA-кластер 3+3 с локальным балансировщиком (без VIP)

Этот сценарий подходит для учебных и тестовых кластеров, где не требуется единая точка входа через VIP. Кластер сохраняет отказоустойчивость — продолжает работать при потере одного мастера.

#### Инфраструктура

| Роль | Количество | Пример IP |
| :--- | :--- | :--- |
| **Control Plane + etcd** | 3 | 10.128.0.2, 10.128.0.35, 10.128.0.16 |
| **Worker** | 3 | 10.128.0.31, 10.128.0.18, 10.128.0.38 |

#### Конфигурация Inventory (YAML формат)

**Файл `inventory/my-cluster/hosts.yaml`:**

```yaml
all:
  hosts:
    node1:
      ansible_host: 10.128.0.2
      ip: 10.128.0.2
    node2:
      ansible_host: 10.128.0.35
      ip: 10.128.0.35
    node3:
      ansible_host: 10.128.0.16
      ip: 10.128.0.16
    node4:
      ansible_host: 10.128.0.31
      ip: 10.128.0.31
    node5:
      ansible_host: 10.128.0.18
      ip: 10.128.0.18
    node6:
      ansible_host: 10.128.0.38
      ip: 10.128.0.38

  children:
    kube_control_plane:
      hosts:
        node1:
        node2:
        node3:

    kube_node:
      hosts:
        node4:
        node5:
        node6:

    etcd:
      hosts:
        node1:
        node2:
        node3:

    k8s_cluster:
      children:
        kube_control_plane:
        kube_node:
```

#### Настройка переменных

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**

```yaml
kube_version: v1.31.0
container_manager: containerd
kube_network_plugin: calico
kube_proxy_mode: ipvs

# Локальный балансировщик на worker-нодах (nginx-proxy)
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443
```

#### Развёртывание

```bash
# Подготовка машины управления
sudo apt update && sudo apt install -y git python3-pip python3.11-venv

# Клонирование Kubespray
git clone https://github.com/kubernetes-sigs/kubespray.git
cd kubespray

# Установка зависимостей
pip install -r requirements.txt

# Копирование примера inventory
cp -rfp inventory/sample inventory/my-cluster

# Генерация inventory из IP-адресов через встроенный скрипт
IPS="10.128.0.2 10.128.0.35 10.128.0.16 10.128.0.31 10.128.0.18 10.128.0.38"
declare -a IPS=(${IPS//,/ })
CONFIG_FILE=inventory/my-cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}

# Настройка SSH-ключа для доступа к узлам
scp -i ~/.ssh/your-key.pem ~/.ssh/your-key.pem user@node1:~/.ssh/id_rsa
chmod 600 ~/.ssh/id_rsa

# Запуск развёртывания
ansible-playbook -i inventory/my-cluster/hosts.yaml \
  --become --become-user=root -v cluster.yml
```

---

## Проверка и валидация

### 1. Проверка VIP (Keepalived / Kube-vip)

```bash
# На мастер-узле с MASTER статусом
ip a show dev eth0 | grep 192.168.1.100
# → inet 192.168.1.100/32 scope global eth0

# Проверка статуса Keepalived (если используется)
systemctl status keepalived

# Журнал VRRP
journalctl -u keepalived -f
```

### 2. Проверка балансировщика (HAProxy / nginx-proxy)

```bash
# Для HAProxy: проверка бэкендов (должны быть UP)
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | \
  grep -E "kubernetes-api-masters.*UP"

# Для nginx-proxy: проверка API через разные worker-ноды
kubectl --server=https://10.128.0.31:6443 get nodes  # через worker-1
kubectl --server=https://10.128.0.18:6443 get nodes  # через worker-2
```

### 3. Проверка Kubernetes API

```bash
# Подключение через VIP
kubectl --server=https://192.168.1.100:6443 get nodes

# Проверка статуса всех мастеров
kubectl get nodes -l node-role.kubernetes.io/control-plane
# → node1  Ready  control-plane  ...
# → node2  Ready  control-plane  ...

# Проверка etcd кластера
kubectl get pods -n kube-system -l component=etcd
```

---

## Ограничения и рекомендации

| Аспект | Keepalived + HAProxy | Kube-vip | nginx-proxy (local) |
| :--- | :--- | :--- | :--- |
| **Единая точка входа** | Да (VIP) | Да (VIP) | Нет |
| **Production готовность** | Рекомендуется | Рекомендуется | Тесты / Dev |
| **Отказоустойчивость** | Высокая | Высокая | Средняя |
| **Сложность настройки** | Средняя | Низкая | Минимальная |

---

## Дополнительная информация

**См. также:**
- [Основные концепции HA](./kubespray_ha_concepts.md)
- [Дополнительные темы и Troubleshooting](./kubespray_ha_advanced.md)
- [Обзор Kubespray](../overview.md)

**Внешние ресурсы:**
- [Документация Kubespray](https://kubespray.io/)
- [Kube-vip ARP/BGP Modes](https://kube-vip.io/docs/about/architecture/)
