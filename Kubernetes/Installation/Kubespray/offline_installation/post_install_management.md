# Kubespray: Offline установка — Post-Install управление

## Управление через Kubespray

### Операции управления

| Задача | Команда |
| :--- | :--- |
| **Добавить ноду** | Добавить в `inventory.ini` + `scale.yml` |
| **Обновить k8s** | Поменять `kube_version` + `upgrade-cluster.yml` |
| **Изменить сеть** | Править `group_vars/k8s_cluster/k8s-net-cilium.yml` + `--tags cilium` |
| **Удалить ноду** | `remove-node.yml` с обновлённым inventory |

### Масштабирование кластера

**Добавление worker-ноды:**

```ini
# Добавить в inventory.ini
[kube_node]
node-1-k8s
node-2-k8s
node-3-k8s  # Новая нода
```

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  scale.yml -b -u admin
```

**Добавление master-ноды:**

```ini
# Добавить в inventory.ini
[kube_control_plane]
master-1-k8s
master-2-k8s
master-3-k8s
master-4-k8s  # Новая master-нода

[etcd]
master-1-k8s
master-2-k8s
master-3-k8s
master-4-k8s  # etcd на master
```

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin
```

### Обновление Kubernetes

**Важно:** Обновлять можно только на одну минорную версию за раз.

```yaml
# group_vars/k8s_cluster/k8s-cluster.yml
kube_version: v1.35.0  # Было v1.34.3
```

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  upgrade-cluster.yml -b -u admin
```

### Изменение сетевых настроек

```yaml
# group_vars/k8s_cluster/k8s-net-cilium.yml
cilium_mtu: "1450"
cilium_tunnel_mode: geneve
cilium_kube_proxy_replacement: true
```

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "cilium,network" -v
```

---

## Управление Cilium

### Сетевые политики

**Пример CiliumNetworkPolicy:**

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: default
spec:
  endpointSelector:
    matchLabels:
      app: backend
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: frontend
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
```

**Применение:**

```bash
kubectl apply -f policy.yaml
```

### Диагностика сети

```bash
# Статус кластера
kubectl -n kube-system exec -it ds/cilium -- cilium status

# Проверка здоровья
kubectl -n kube-system exec -it ds/cilium -- cilium health status

# Наблюдение за трафиком
kubectl -n kube-system exec -it ds/cilium -- hubble observe --follow

# Статус BGP (если используется)
kubectl -n kube-system exec -it ds/cilium -- cilium bgp summary
```

### Мониторинг через Hubble

**Доступ к Hubble UI:**

```bash
kubectl port-forward -n kube-system svc/hubble-ui 8080:80
# Открыть: http://localhost:8080
```

**Команды Hubble:**

```bash
# Наблюдение за всеми событиями
kubectl -n kube-system exec -it ds/cilium -- hubble observe

# Только DNS события
kubectl -n kube-system exec -it ds/cilium -- hubble observe --type dns

# Только HTTP события
kubectl -n kube-system exec -it ds/cilium -- hubble observe --type http

# События для конкретного пода
kubectl -n kube-system exec -it ds/cilium -- \
  hubble observe --pod <pod-name>
```

---

## Управление конфигурацией

### Изменение переменных cluster

**Файлы конфигурации:**

| Файл | Назначение |
| :--- | :--- |
| `group_vars/all/offline.yml` | Offline настройки, registry |
| `group_vars/all/containerd.yml` | Containerd конфигурация |
| `group_vars/k8s_cluster/k8s-cluster.yml` | Основные параметры K8s |
| `group_vars/k8s_cluster/k8s-net-cilium.yml` | Настройки Cilium |
| `group_vars/k8s_cluster/addons.yml` | Аддоны (Helm, Ingress, MetalLB) |

### Применение изменений конфигурации

```bash
# После изменения group_vars
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin
```

**Или с тегами для ускорения:**

```bash
# Только сеть
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "network,cilium" -v

# Только аддоны
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "kubernetes-apps" -v
```

---

## Резервное копирование

### Бэкап etcd

```bash
# На master-ноде
ETCDCTL_ENDPOINTS=https://127.0.0.1:2379
ETCDCTL_CACERT=/etc/ssl/etcd/ssl/ca.pem
ETCDCTL_CERT=/etc/ssl/etcd/ssl/peer-$(hostname).pem
ETCDCTL_KEY=/etc/ssl/etcd/ssl/peer-$(hostname)-key.pem

etcdctl snapshot save backup.db
```

### Бэкап конфигурации

```bash
# Сохранение inventory и group_vars
tar -czf kubespray-config-backup.tar.gz \
  inventory/offline_cluster/
```

---

## Связанные документы

- **[Troubleshooting](./troubleshooting.md)** — решение проблем
- **[Проверка кластера](./cluster_verification.md)** — валидация установки
- **[Kubespray: Управление кластером](../cluster_management.md)** — масштабирование и обновление
- **[CNI и kube-proxy](../../../Networking/Network/CNI/definitions.md)** — сетевые плагины

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
