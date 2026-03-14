# Kubespray: Offline установка — Шаг 4: Развертывание кластера

## Подготовка master-1-k8s

### Установка Docker

```bash
apt install docker.io -y
```

### Проверка прокси (если указывался)

Файл: `group_vars/all/all.yml`

```yaml
# Удалить или закомментировать:
# http_proxy: ""
# https_proxy: ""
```

## Запуск развертывания

```bash
cd /opt/kuber_off/
source venv/bin/activate
cd kubespray/

ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin
```

**Время выполнения:** 15-30 минут в зависимости от количества узлов.

## Проверка кластера

### Статус узлов

```bash
kubectl get nodes -o wide
```

**Ожидаемый результат:**

```
NAME            STATUS   ROLES           AGE   VERSION   INTERNAL-IP     OS-IMAGE
master-1-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.101   Ubuntu 24.04
master-2-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.102   Ubuntu 24.04
master-3-k8s    Ready    control-plane   1h    v1.34.3   192.168.1.103   Ubuntu 24.04
node-1-k8s      Ready    <none>          1h    v1.34.3   192.168.1.104   Ubuntu 24.04
node-2-k8s      Ready    <none>          1h    v1.34.3   192.168.1.105   Ubuntu 24.04
```

### Проверка системных подов

```bash
kubectl get pods -n kube-system
```

**Ключевые компоненты:**

```bash
# Cilium
kubectl get pods -n kube-system -l k8s-app=cilium

# Hubble
kubectl get pods -n kube-system -l k8s-app=hubble

# CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns

# kube-proxy (если не удалён)
kubectl get pods -n kube-system -l k8s-app=kube-proxy
```

### Проверка Cilium

```bash
kubectl -n kube-system exec -it ds/cilium -- cilium status
```

**Ожидаемый вывод:**

```
KubeProxyReplacement:    True   [ens33  192.168.1.104 (Direct Routing)]
Cluster health:          5/5 reachable
```

### Проверка Hubble

```bash
# Статус Hubble
kubectl -n kube-system exec -it ds/cilium -- hubble status

# Наблюдение за трафиком
kubectl -n kube-system exec -it ds/cilium -- hubble observe --follow
```

## Работа с kubeconfig

### Копирование admin.conf

```bash
# С master-1-k8s
mkdir -p ~/.kube
cp /etc/kubernetes/admin.conf ~/.kube/config
```

### Проверка доступа

```bash
kubectl cluster-info
kubectl get namespaces
```

## Связанные документы

- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — загрузка в Harbor
- **[Шаг 5: Настройка MetalLB и Ingress](./step5_metallb_ingress.md)** — настройка LoadBalancer
- **[Дополнительная информация](./offline_additional.md)** — troubleshooting
- **[Kubespray: Управление кластером](../cluster_management.md)** — масштабирование и обновление

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
