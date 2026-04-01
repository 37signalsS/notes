# Kubespray: Offline установка — Шаг 4: Развертывание кластера

## Определения

**cluster.yml** — основной Ansible-плейбук Kubespray для развёртывания кластера Kubernetes на всех узлах.

**kubeconfig** — файл конфигурации для доступа к Kubernetes API; содержит данные о кластере, пользователе и контексте.

**admin.conf** — файл kubeconfig с правами администратора кластера, генерируемый kubeadm.

---

## Основные концепции

### Цель этапа

Запуск Ansible-плейбука для развёртывания Kubernetes на подготовленных узлах:

- Установка компонентов Kubernetes (kubelet, kubeadm, kubectl)
- Настройка containerd как runtime
- Инициализация Control Plane и etcd
- Развёртывание CNI (Cilium) и аддонов (CoreDNS, Hubble)

### Время выполнения

15–30 минут в зависимости от количества узлов.

### Ожидаемый результат

- Все узлы в статусе `Ready`
- Все системные поды в статусе `Running`
- Cilium показывает `Cluster health: N/N reachable`
- Доступен kubeconfig для управления кластером

---

## Практические сценарии

### Подготовка master-1-k8s

#### Установка Docker

```bash
apt install docker.io -y
```

#### Проверка прокси (если указывался)

Файл: `group_vars/all/all.yml`

```yaml
# Удалить или закомментировать:
# http_proxy: ""
# https_proxy: ""
```

### Запуск развёртывания

```bash
cd /opt/kuber_off/
source venv/bin/activate
cd kubespray/

ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin
```

### Проверка кластера

Полная проверка кластера описана в [cluster_verification.md](./cluster_verification.md).

#### Краткая проверка

```bash
# Статус узлов
kubectl get nodes -o wide

# Статус системных подов
kubectl get pods -n kube-system

# Статус Cilium
kubectl -n kube-system exec -it ds/cilium -- cilium status
```

### Работа с kubeconfig

#### Копирование admin.conf

```bash
# С master-1-k8s
mkdir -p ~/.kube
cp /etc/kubernetes/admin.conf ~/.kube/config
```

#### Проверка доступа

```bash
kubectl cluster-info
kubectl get namespaces
```

---

## Дополнительная информация

### Связанные темы

Подготовка закрытого контура описана в [шаге 3](./step3_offline_env.md), настройка MetalLB и Ingress — в [шаге 5](./step5_metallb_ingress.md). Полная проверка кластера — в [cluster_verification.md](./cluster_verification.md), решение проблем — в [troubleshooting.md](./troubleshooting.md). Управление кластером — в [cluster_management.md](../cluster_management.md).
