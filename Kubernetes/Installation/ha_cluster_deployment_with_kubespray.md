# Kubespray: Развертывание HA-кластера

## 1. Определения

**HA-кластер (High Availability)** — кластер Kubernetes с несколькими узлами Control Plane для устранения единой точки отказа (SPoF).

**VIP (Virtual IP)** — виртуальный IP-адрес, который служит единой точкой входа к API-серверам через механизм VRRP.

**Kubespray** — инструмент автоматизации развертывания Kubernetes на базе Ansible, поддерживающий встроенную настройку HA через Keepalived + HAProxy.

> **Основное руководство:** Подробное описание архитектуры Keepalived + HAProxy см. в [Настройка HA с kubeadm](./kudeadm/kubeadm_ha_with_keepalived_haproxy.md).

## 2. Основные концепции

### Архитектура HA через Kubespray

Kubespray автоматизирует настройку HA следующим образом:

```
                    ┌─────────────────┐
                    │      VIP        │
                    │  192.168.1.100  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───────┐ ┌───▼────────┐ ┌───▼────────┐
     │   Master-1     │ │  Master-2  │ │  Master-3  │
     │  Keepalived    │ │ Keepalived │ │ Keepalived │
     │    MASTER      │ │  BACKUP    │ │  BACKUP    │
     │   HAProxy:6443 │ │HAProxy:6443│ │HAProxy:6443│
     │ apiserver:6444 │ │apiserver:6444│ │apiserver:6444│
     └────────────────┘ └────────────┘ └────────────┘
```

**Компоненты:**

| Компонент | Назначение | Порт |
| :--- | :--- | :--- |
| **Keepalived** | Управление VIP через VRRP | 112 (VRRP) |
| **HAProxy** | Балансировка трафика к API-серверам | 6443 (VIP), 6444 (local) |
| **kube-apiserver** | API Kubernetes | 6444 (локально) |

### Отличия от ручного kubeadm

| Аспект | Kubespray | Ручной kubeadm |
| :--- | :--- | :--- |
| **Автоматизация** | Полная (Ansible) | Ручная настройка |
| **Keepalived/HAProxy** | Устанавливается автоматически | Ручная установка |
| **Сертификаты** | Авто-генерация с VIP | Ручное добавление SAN |
| **Время развертывания** | 15-30 минут | 1-2 часа |

## 3. Практические сценарии

### 3.1. Инфраструктурные требования

**Минимальная конфигурация HA-кластера:**

| Роль | Количество | CPU | RAM | Диск |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 3 (odd для кворума) | 2+ | 4GB+ | 40GB+ |
| **Worker** | 2+ | 2+ | 4GB+ | 40GB+ |
| **etcd** | 3 (на master) | 2+ | 8GB+ | SSD 40GB+ |

> **Важно:** Количество master-узлов должно быть нечетным (3, 5) для обеспечения кворума etcd.

### 3.2. Конфигурация Inventory

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

### 3.3. Настройка переменных для HA

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

### 3.4. Развертывание HA-кластера

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

### 3.5. Проверка HA-конфигурации

**Проверка VIP:**

```bash
# На master-узле с MASTER статусом
ip a show dev eth0 | grep 192.168.1.100

# Проверка статуса Keepalived
systemctl status keepalived

# Журнал VRRP
journalctl -u keepalived -f
```

**Проверка HAProxy:**

```bash
# Статус HAProxy
systemctl status haproxy

# Проверка бэкендов (должны быть UP)
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | \
  grep -E "kubernetes-api-masters.*UP"

# Лог HAProxy
tail -f /var/log/haproxy.log
```

**Проверка Kubernetes API:**

```bash
# Подключение через VIP
kubectl --server=https://192.168.1.100:6443 get nodes

# Проверка всех master-узлов
kubectl get nodes -l node-role.kubernetes.io/control-plane

# Проверка etcd кластера
kubectl get pods -n kube-system -l component=etcd
```

### 3.6. Тестирование отказоустойчивости

**Тест 1: Отключение MASTER узла**

```bash
# На текущем MASTER узле
systemctl stop keepalived

# На другом узле проверить появление VIP
ip a show dev eth0 | grep 192.168.1.100

# API должен оставаться доступным
kubectl get nodes
```

**Тест 2: Отключение kube-apiserver**

```bash
# На одном из master
systemctl stop kube-apiserver

# HAProxy должен исключить узел из ротации
echo "show stat" | socat stdio /var/run/haproxy/admin.sock | \
  grep kubernetes-api-masters
```

**Тест 3: Отключение etcd**

```bash
# На одном из master
systemctl stop etcd

# Кластер должен оставаться работоспособным (2 из 3)
kubectl get pods --all-namespaces
```

## 4. Дополнительная информация

### Конфигурационные файлы Kubespray

| Файл | Назначение |
| :--- | :--- |
| `inventory/my-cluster/inventory.ini` | Хосты и роли |
| `group_vars/all/all.yml` | Общие переменные |
| `group_vars/k8s_cluster/k8s-cluster.yml` | Параметры K8s |
| `group_vars/etcd/etcd.yml` | Настройки etcd |

### Переменные для HA

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `loadbalancer_apiserver_localhost` | `false` | Включить локальный HAProxy |
| `enable_keepalived` | `true` | Включить Keepalived |
| `keepalived_virtual_router_id` | `51` | VRRP router ID |
| `kube_apiserver_insecure_port` | `0` | Небезопасный порт API |

### Troubleshooting

**Проблема: VIP не назначается**

```bash
# Проверка VRRP трафика
tcpdump -n -i eth0 vrrp

# Проверка логов Keepalived
journalctl -u keepalived -n 50
```

**Проблема: HAProxy не видит бэкенды**

```bash
# Проверка доступности API-серверов
curl -k https://192.168.1.10:6444/healthz

# Перезапуск HAProxy
systemctl restart haproxy
```

**Проблема: etcd кворум потерян**

```bash
# Статус etcd на каждом узле
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/ssl/etcd/ssl/ca.pem \
  --cert=/etc/ssl/etcd/ssl/peer-$(hostname).pem \
  --key=/etc/ssl/etcd/ssl/peer-$(hostname)-key.pem \
  endpoint health
```

### Связанные документы

- **[Kubespray: Обзор](./Kubespray/overview.md)** — общая информация
- **[Kubespray: Установка](./Kubespray/installation.md)** — базовая установка
- **[HA с kubeadm](./kudeadm/kubeadm_ha_with_keepalived_haproxy.md)** — ручная настройка HA
- **[Keepalived обзор](../Networking/ServicesAndTools/keepalived_overview.md)** — детали Keepalived
- **[HAProxy обзор](../WebServers/Haproxy/haproxy_overview.md)** — детали HAProxy

### Внешние ресурсы

- **Kubespray Documentation:** [kubespray.io](https://kubespray.io/)
- **GitHub:** [kubernetes-sigs/kubespray](https://github.com/kubernetes-sigs/kubespray)
- **VRRP RFC:** [RFC 5798](https://datatracker.ietf.org/doc/html/rfc5798)
