# Kubespray: Развертывание HA-кластера — Практика

## Definitions

Термины и определения см. в [основных концепциях](./kubespray_ha_concepts.md).

## Basic Concepts

### Инфраструктурные требования

**Минимальная конфигурация HA-кластера:**

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (odd для кворума) | 2+ | 4GB+ | 40GB+ |
| **Worker** | 2+ | 2+ | 4GB+ | 40GB+ |
| **etcd** | 3 (на master) | 2+ | 8GB+ | SSD 40GB+ |

> **Важно:** Количество master-узлов должно быть нечетным (3, 5) для обеспечения кворума etcd.

## Practical Scenarios

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

## Additional Information

Тестирование отказоустойчивости и troubleshooting см. в [дополнительных темах](./kubespray_ha_advanced.md). Общая информация — в [обзоре Kubespray](../overview.md).
