# Kubespray: Установка — Практические сценарии

## Установка Kubespray и зависимостей

1. **Клонировать репозиторий:**

   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   ```

2. **Установить зависимости Ansible:**

   ```bash
   pip install -r requirements.txt
   ```

## Конфигурация Inventory

1. **Скопировать пример inventory:**

   ```bash
   cp -rfp inventory/sample inventory/my-cluster
   ```

2. **Отредактировать `inventory/my-cluster/inventory.ini`:**

   **Пример для HA-кластера (3 master + 2 worker):**

   ```ini
   [all]
   control-1 ansible_host=192.168.1.11
   control-2 ansible_host=192.168.1.12
   control-3 ansible_host=192.168.1.13
   worker-1 ansible_host=192.168.1.21
   worker-2 ansible_host=192.168.1.22

   [kube_control_plane]
   control-1
   control-2
   control-3

   [etcd]
   control-1
   control-2
   control-3

   [kube_node]
   worker-1
   worker-2

   [k8s_cluster:children]
   kube_control_plane
   kube_node
   ```

   > **Примечание:** Для небольших кластеров `etcd` можно размещать на узлах control plane. Для HA-кластеров см. [Развертывание HA-кластера](../HA/index.md).

## Конфигурация переменных (group_vars)

### 6.1. `inventory/my-cluster/group_vars/all/all.yml`

```yaml
# Управлять etcd через kubeadm (критично для управления сертификатами)
etcd_kubeadm_enabled: true

# Локальный прокси на API-сервер на каждой ноде
loadbalancer_apiserver_localhost: true

# Позволяет kubelet подгружать необходимые модули ядра
kubelet_load_modules: true

# Отключает использование kubeadm (классический способ установки)
kubeadm_enabled: false

# Read-only порт (10255) для сбора метрик без авторизации
kube_read_only_port: 10255
```

> **Важно:** Параметр `etcd_kubeadm_enabled: true` критичен для последующего [управления сертификатами](../../../Operations/certificate_management.md).

### 6.2. `inventory/my-cluster/group_vars/all/docker.yml` (опционально)

Настройки для Docker (если используется вместо containerd):

```yaml
# Overlay2 как драйвер хранилища для Docker
docker_storage_options: -s overlay2
```

### 6.3. `inventory/my-cluster/group_vars/all/download.yml`

Оптимизация загрузки артефактов:

```yaml
# Файлы и образы скачиваются один раз на один узел,
# затем копируются на остальные узлы кластера
download_run_once: true
```

### 6.4. `inventory/my-cluster/group_vars/etcd.yml`

Настройки для компонента etcd:

```yaml
# Уменьшает количество записей в журнале операций в памяти
etcd_snapshot_count: "5000"

# Приоритет I/O для etcd
etcd_ionice: '-c2 -n0'

# Лимит памяти для etcd (0 - без ограничений)
etcd_memory_limit: 0
```

### 6.5. `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`

Основные параметры кластера:

```yaml
# Версия Kubernetes (укажите актуальную стабильную версию)
kube_version: v1.31.0

# Среда выполнения контейнеров (Docker устарел, используем containerd)
container_manager: containerd

# Сетевой CNI-плагин (рекомендуется Calico)
kube_network_plugin: calico

# Сеть для сервисов типа ClusterIP
kube_service_addresses: 10.232.0.0/16

# Сеть для подов
kube_pods_subnet: 10.233.0.0/16

# Режим работы kube-proxy (IPVS производительнее iptables)
kube_proxy_mode: ipvs

# Имя кластера
cluster_name: k8s-cluster

# Отключает небезопасный порт API-сервера
kube_apiserver_insecure_port: 0

# Отключает OIDC и basic auth, оставляем только токен
kube_oidc_auth: false
kube_basic_auth: false

# Копирование kubeconfig на локальную машину
kubeconfig_localhost: true
kubectl_localhost: true

# Аутентификация и авторизация kubelet через вебхуки
kubelet_authentication_token_webhook: true
kubelet_authorization_mode_webhook: true

# Локальный кеширующий DNS на каждом узле
enable_nodelocaldns: true

# Принудительная регенерация сертификатов
auto_renew_certificates: true
```

> **Важно:** Версия Kubernetes должна соответствовать версии Kubespray. Проверьте поддерживаемые версии в файле `roles/download/defaults/main.yml` (переменная `kubelet_checksums`).

### 6.6. Настройки сетевого плагина

**Для Calico** (`k8s-net-calico.yml`):

```yaml
# Режим инкапсуляции: CrossSubnet для L2-доменов
calico_ipip_mode: CrossSubnet
```

**Для Flannel** (`k8s-net-flannel.yml`):

```yaml
# Бэкенд: host-gw для статических маршрутов в L2-сети
flannel_backend_type: "host-gw"

# Регулярное выражение для выбора сетевого интерфейса
flannel_interface_regexp: '192\.168\.1\.\d{1,3}'
```

Подробнее о CNI-плагинах: [CNI, kube-proxy и их роли](../../../Networking/Network/cni_kube_proxy_roles.md).

## Запуск развертывания

Выполните плейбук `cluster.yml` из корневой директории Kubespray:

```bash
# Для пользователя root
ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml

# Для non-root пользователя с sudo
ansible-playbook -i inventory/my-cluster/inventory.ini --become --user=myuser cluster.yml
```

> **Время выполнения:** 15–30 минут в зависимости от количества узлов и скорости сети.

---

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, этапы установки
- **[Дополнительная информация](./additional_info.md)** — действия после установки, troubleshooting
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре без интернета
