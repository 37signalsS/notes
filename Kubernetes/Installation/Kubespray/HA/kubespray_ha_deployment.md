# Kubespray: Развертывание HA-кластера — Практика

## Определения

**Inventory (Инвентарь)** — конфигурационный файл (INI или YAML), описывающий логическую топологию кластера: разделение узлов на роли (master, worker, etcd) и параметры подключения к ним.

**Group Vars (Групповые переменные)** — иерархическая система настроек в Kubespray, позволяющая переопределять параметры Kubernetes, сетевых плагинов и балансировщиков на уровне всего кластера или отдельных групп узлов.

**Bootstrap-OS** — этап предварительной настройки операционной системы (плейбук `bootstrap-os.yml`), включающий установку базовых зависимостей (python, curl), настройку параметров ядра (sysctl) и управление службами (отключение swap, firewall).

**VIP (Virtual IP)** — отказоустойчивый IP-адрес, обеспечивающий единую точку входа для API-сервера.

---

## Основные концепции

### Инфраструктурные требования

Минимальные аппаратные требования для HA-кластера (etcd совмещен с Control Plane) зависят от ожидаемой нагрузки. Ниже приведены базовые значения для стабильной работы:

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (нечетное число) | 2+ | 4 ГБ+ | 40 ГБ+ |
| **Worker** | 2+ | 2+ | 4 ГБ+ | 40 ГБ+ |
| **etcd** | 3 (на master) | 2+ | 8 ГБ+ | SSD 40 ГБ+ |

> **Важно:** Количество master-узлов должно быть нечетным (3, 5, 7) для обеспечения кворума etcd. Общие требования к среде см. в [требованиях к HA-кластеру](../../HA_Cluster_Bare_Metal/k8s_ha_environment_requirements.md).

### Подготовка машины управления

Развертывание рекомендуется выполнять с отдельной Linux-системы.

1. **Создание виртуального окружения:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. **Установка зависимостей:**
   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   pip install -r requirements.txt
   ```
3. **Настройка SSH:** Убедитесь, что публичный ключ машины управления добавлен в `authorized_keys` на всех целевых узлах, и пользователь имеет права `sudo` без пароля.

---

## Практические сценарии

### 1. Конфигурация Inventory (INI формат)

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

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**
```yaml
# Включение локального балансировщика (HAProxy на каждом master)
loadbalancer_apiserver_localhost: true

# VIP для доступа к API
apiserver_loadbalancer_domain: "lb.k8s.local"
loadbalancer_apiserver:
  address: "192.168.1.100"  # VIP адрес
  port: 6443

kube_version: v1.31.0
container_manager: containerd
kube_network_plugin: calico
kube_proxy_mode: ipvs
```

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**
```yaml
enable_keepalived: true
keepalived_virtual_router_id: 51
keepalived_priority: 100
keepalived_auth_pass: "k8s-ha-secret"
# Исключение небезопасного порта
kube_apiserver_insecure_port: 0
```

### 3. Сценарий B: HA через Kube-vip (Современный метод)

**Файл `inventory/my-cluster/group_vars/all/all.yml`:**
```yaml
kube_vip_enabled: true
kube_vip_address: "192.168.1.100"
kube_vip_interface: "eth0"
kube_vip_arp_enabled: true
```

**Файл `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`:**
```yaml
loadbalancer_apiserver:
  address: "192.168.1.100"
  port: 6443
```

### 4. Сценарий: HA-кластер 3+3 с локальным балансировщиком (без VIP)

Применяется в средах, где использование плавающего IP ограничено (например, в некоторых облаках или при отсутствии доступа к L2). Балансировка на уровне узла (local nginx-proxy) обеспечивает выживаемость при сбое одного мастера.

#### Конфигурация Inventory (YAML формат)
**Файл `inventory/my-cluster/hosts.yaml`:**
```yaml
all:
  hosts:
    node1: {ansible_host: 10.128.0.2, ip: 10.128.0.2}
    node2: {ansible_host: 10.128.0.35, ip: 10.128.0.35}
    node3: {ansible_host: 10.128.0.16, ip: 10.128.0.16}
    node4: {ansible_host: 10.128.0.31, ip: 10.128.0.31}
    node5: {ansible_host: 10.128.0.18, ip: 10.128.0.18}
    node6: {ansible_host: 10.128.0.38, ip: 10.128.0.38}
  children:
    kube_control_plane:
      hosts: {node1: {}, node2: {}, node3: {}}
    kube_node:
      hosts: {node4: {}, node5: {}, node6: {}}
    etcd:
      hosts: {node1: {}, node2: {}, node3: {}}
    k8s_cluster:
      children: {kube_control_plane: {}, kube_node: {}}
```

#### Настройка и развертывание
1. **Переменные (`k8s-cluster.yml`):**
   ```yaml
   loadbalancer_apiserver_localhost: true
   loadbalancer_apiserver_port: 6443
   ```
2. **Генерация инвентаря скриптом:**
   ```bash
   IPS="10.128.0.2 10.128.0.35 10.128.0.16 10.128.0.31 10.128.0.18 10.128.0.38"
   CONFIG_FILE=inventory/my-cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS}
   ```
3. **Запуск плейбука:**
   ```bash
   ansible-playbook -i inventory/my-cluster/hosts.yaml --become cluster.yml
   ```

### 5. Команды управления и обслуживания

* **Полное развертывание:** `ansible-playbook -i inventory/my-cluster/hosts.yaml --become cluster.yml`
* **Подготовка ОС:** `ansible-playbook -i inventory/my-cluster/hosts.yaml --become bootstrap-os.yml`
* **Восстановление узла:** `ansible-playbook -i inventory/my-cluster/hosts.yaml --become recover-node.yml`
* **Масштабирование воркеров:** `ansible-playbook -i inventory/my-cluster/hosts.yaml --become scale.yml`

---

## Проверка и валидация

### 1. Проверка VIP и Keepalived

```bash
# Проверка наличия VIP на интерфейсе (на лидере)
ip a show eth0 | grep 192.168.1.100

# Проверка статуса службы
systemctl status keepalived

# Просмотр VRRP логов
journalctl -u keepalived -f
```

### 2. Проверка балансировщиков (HAProxy / nginx-proxy)

```bash
# HAProxy: Проверка статуса бэкендов через сокет
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep -E "kubernetes-api-masters.*UP"

# Nginx-proxy: Проверка API через локальный порт на воркере
kubectl --server=https://10.128.0.31:6443 get nodes
```

### 3. Проверка Kubernetes API и etcd

```bash
# Проверка через VIP
kubectl --server=https://192.168.1.100:6443 get nodes

# Статус подов etcd
kubectl get pods -n kube-system -l component=etcd

# Проверка здоровья etcd кластера
kubectl exec -n kube-system -it etcd-master-1 -- etcdctl endpoint health --cluster
```

---

## Дополнительная информация

### Сравнение методов балансировки

| Аспект | Keepalived + HAProxy | Kube-vip | nginx-proxy (local) |
| :--- | :--- | :--- | :--- |
| **Единая точка входа** | Да (VIP) | Да (VIP) | Нет |
| **Production готовность** | Рекомендуется | Рекомендуется | Тесты / Dev |
| **Отказоустойчивость** | Высокая | Высокая | Средняя |
| **Сложность настройки** | Средняя | Низкая | Минимальная |

### См. также
- [Основные концепции HA](./kubespray_ha_concepts.md)
- [Дополнительные темы и Troubleshooting](./kubespray_ha_advanced.md)
- [Обзор Kubespray](../overview.md)

### Внешние ресурсы
- [Документация Kubespray](https://kubespray.io/)
- [Kube-vip ARP/BGP Modes](https://kube-vip.io/docs/about/architecture/)
