# Kubespray: Offline установка — Post-Install управление

## Определения

**Post-Install управление** — операции по настройке, масштабированию и обслуживанию кластера Kubernetes после завершения установки через Kubespray в offline-режиме.

**CiliumNetworkPolicy** — ресурс Kubernetes для декларативного управления правилами сетевого доступа (L3/L4) между подами; часть CNI Cilium.

---

## Основные концепции

### Операции управления

| Задача | Команда | SSoT |
| :--- | :--- | :--- |
| **Добавить ноду** | `scale.yml` | [cluster_management.md](../cluster_management.md) |
| **Обновить k8s** | `upgrade-cluster.yml` | [cluster_management.md](../cluster_management.md) |
| **Изменить сеть** | `--tags cilium,network` | Ниже |
| **Удалить ноду** | `remove-node.yml` | [cluster_management.md](../cluster_management.md) |
| **Бэкап etcd** | `etcdctl snapshot save` | [cluster_management.md](../cluster_management.md) |

### Файлы конфигурации offline-кластера

| Файл | Назначение |
| :--- | :--- |
| `group_vars/all/offline.yml` | Offline настройки, registry |
| `group_vars/all/containerd.yml` | Containerd конфигурация |
| `group_vars/k8s_cluster/k8s-cluster.yml` | Основные параметры K8s |
| `group_vars/k8s_cluster/k8s-net-cilium.yml` | Настройки Cilium |
| `group_vars/k8s_cluster/addons.yml` | Аддоны (Helm, Ingress, MetalLB) |

---

## Практические сценарии

### Изменение сетевых настроек Cilium

```yaml
# group_vars/k8s_cluster/k8s-net-cilium.yml
cilium_mtu: "1450"
cilium_tunnel_mode: geneve
cilium_kube_proxy_replacement: true
```

**Применение изменений:**

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b --tags "cilium,network" -v
```

### Применение CiliumNetworkPolicy

**Пример политики (frontend → backend):**

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

### Диагностика Cilium и Hubble

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

### Мониторинг через Hubble UI

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

## Дополнительная информация

### Связанные темы

Масштабирование и обновление кластера описано в [cluster_management.md](../cluster_management.md), валидация установки — в [проверке кластера](./cluster_verification.md), решение проблем — в [troubleshooting](./troubleshooting.md). Сетевые плагины — в [CNI definitions](../../../Networking/Network/CNI/definitions.md).
