# Kubespray: Развертывание HA-кластера — Практика

## Определения

**HA-кластер Control Plane** — конфигурация Kubernetes с 3+ узлами Control Plane для обеспечения отказоустойчивости API-сервера.

**VIP (Virtual IP)** — виртуальный IP-адрес, обеспечивающий единую точку входа к API-серверам через протокол VRRP.

**Keepalived** — демон управления VIP, обеспечивающий автоматическое переключение при отказе MASTER-узла.

**HAProxy** — балансировщик нагрузки, распределяющий трафик между API-серверами Control Plane.

Подробные термины и архитектурные концепции см. в [основных концепциях HA](./kubespray_ha_concepts.md).

## Основные концепции

### Инфраструктурные требования

**Минимальная конфигурация HA-кластера:**

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (odd для кворума) | 2+ | 4GB+ | 40GB+ |
| **Worker** | 2+ | 2+ | 4GB+ | 40GB+ |
| **etcd** | 3 (на master) | 2+ | 8GB+ | SSD 40GB+ |

> **Важно:** Количество master-узлов должно быть нечетным (3, 5) для обеспечения кворума etcd.

## Практические сценарии

### Конфигурация Inventory

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

### Настройка переменных для HA

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

### Развертывание HA-кластера

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
# 1. Подготовка узлов (установка зависимостей)
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become bootstrap-os.yml

# 2. Развертывание кластера
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become cluster.yml

# 3. Проверка
ansible-playbook -i inventory/my-cluster/inventory.ini \
  --become recover-node.yml
```

### Проверка HA-конфигурации

#### Проверка VIP

```bash
# На master-узле с MASTER статусом
ip a show dev eth0 | grep 192.168.1.100

# Проверка статуса Keepalived
systemctl status keepalived

# Журнал VRRP
journalctl -u keepalived -f
```

#### Проверка HAProxy

```bash
# Статус HAProxy
systemctl status haproxy

# Проверка бэкендов (должны быть UP)
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | \
  grep -E "kubernetes-api-masters.*UP"

# Лог HAProxy
tail -f /var/log/haproxy.log
```

#### Проверка Kubernetes API

```bash
# Подключение через VIP
kubectl --server=https://192.168.1.100:6443 get nodes

# Проверка всех master-узлов
kubectl get nodes -l node-role.kubernetes.io/control-plane

# Проверка etcd кластера
kubectl get pods -n kube-system -l component=etcd
```

### Сценарий: HA-кластер 3+3 с локальным балансировщиком (без Keepalived)

Этот сценарий подходит для учебных и тестовых кластеров, где не требуется единая точка входа через VIP. Кластер сохраняет отказоустойчивость — продолжает работать при потере одного мастера.

#### Инфраструктура

| Роль | Количество | Пример IP |
| :--- | :--- | :--- |
| **Control Plane + etcd** | 3 | 10.128.0.2, 10.128.0.35, 10.128.0.16 |
| **Worker** | 3 | 10.128.0.31, 10.128.0.18, 10.128.0.38 |

#### Конфигурация Inventory

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

> **Важно:** Группы `kube_control_plane` и `etcd` должны содержать одинаковые хосты для обеспечения отказоустойчивости etcd.

#### Настройка переменных

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**

```yaml
# Версия Kubernetes
kube_version: v1.31.0

# Container runtime
container_manager: containerd

# Сетевой плагин
kube_network_plugin: calico

# Режим kube-proxy
kube_proxy_mode: ipvs

# Локальный балансировщик на worker-нодах (nginx-proxy)
loadbalancer_apiserver_localhost: true
loadbalancer_apiserver_port: 6443
```

> **Примечание:** При `loadbalancer_apiserver_localhost: true` Kubespray автоматически разворачивает nginx-proxy на каждой worker-ноде. Этот proxy балансирует трафик к API-серверам control plane. Переменная `enable_keepalived` **не указывается** или устанавливается в `false`.

#### Развёртывание

```bash
# Подготовка машины управления (Python 3.11+, pip, Ansible)
sudo apt update && sudo apt install -y git python3-pip python3.11-venv

# Клонирование Kubespray
git clone https://github.com/kubernetes-sigs/kubespray.git
cd kubespray

# Установка зависимостей
pip install -r requirements.txt

# Копирование примера inventory
cp -rfp inventory/sample inventory/my-cluster

# Генерация inventory из IP-адресов
IPS="10.128.0.2 10.128.0.35 10.128.0.16 10.128.0.31 10.128.0.18 10.128.0.38"
declare -a IPS=(${IPS//,/ })
CONFIG_FILE=inventory/my-cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}

# Проверка и корректировка ролей в hosts.yaml
# (убедиться что node1-node3 в kube_control_plane и etcd, node4-node6 в kube_node)

# Настройка SSH-ключа
scp -i ~/.ssh/your-key.pem ~/.ssh/your-key.pem user@node1:~/.ssh/id_rsa
chmod 600 ~/.ssh/id_rsa

# Запуск развёртывания
ansible-playbook -i inventory/my-cluster/hosts.yaml \
  --become --become-user=root -v cluster.yml
```

**Время выполнения:** 20–30 минут для кластера из 6 нод.

#### Проверка работоспособности

```bash
# Настройка kubectl
mkdir -p ~/.kube
scp node1:/etc/kubernetes/admin.conf ~/.kube/config
chmod 600 ~/.kube/config

# Проверка нод
kubectl get nodes -o wide
# → Все 6 нод в статусе Ready, версия Kubernetes 1.31

# Проверка подов
kubectl get pods -n kube-system -o wide
# → nginx-proxy поды на worker-нодах, компоненты control plane на master-нодах

# Проверка API через разные worker-ноды
kubectl --server=https://10.128.0.31:6443 get nodes  # через worker-1
kubectl --server=https://10.128.0.18:6443 get nodes  # через worker-2
kubectl --server=https://10.128.0.38:6443 get nodes  # через worker-3
```

> **Результат:** Все три команды должны вернуть список нод. Это подтверждает что nginx-proxy на worker-нодах корректно балансирует трафик к API-серверам.

#### Ограничения и рекомендации

| Аспект | Описание |
| :--- | :--- |
| **Единая точка входа** | Отсутствует — клиенты подключаются через разные worker-ноды |
| **Production готовность** | Не рекомендуется для production — используйте внешний балансировщик с VIP |
| **Отказоустойчивость** | Кластер переживает потерю одного мастера (из 3), но требует ручной перенастройки клиента |
| **Следующий шаг** | Для production см. [развёртывание с Keepalived + HAProxy](#развертывание-ha-кластера) |

## Дополнительная информация

Тестирование отказоустойчивости и troubleshooting см. в [дополнительных темах](./kubespray_ha_advanced.md). Общая информация — в [обзоре Kubespray](../overview.md).
