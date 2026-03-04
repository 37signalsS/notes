# Kubespray: Установка кластера

## 1. Определения

**Kubespray** — инструмент для автоматизации развертывания кластеров Kubernetes на базе Ansible. Подробнее в [обзоре](./overview.md).

**Inventory** — файл `inventory.ini`, определяющий хосты и их роли в кластере.

**Group vars** — переменные для групп хостов в директории `group_vars/`.

## 2. Основные концепции

### Компоненты конфигурации

* **Inventory** — файл `inventory.ini`, определяющий состав кластера.
* **Group vars** — переменные для групп хостов:
  * `all/` — общие переменные для всех хостов.
  * `k8s-cluster/` — переменные для компонентов Kubernetes.
* **Плейбуки** — основной плейбук `cluster.yml` для развертывания.

### Требования

* Python 3 + pip
* Ansible (устанавливается через `requirements.txt`)
* SSH-доступ до целевых хостов

### Этапы установки

Процесс установки разбит на 6 этапов:

1. **[Предварительные требования к узлам](#3-предварительные-требования-к-узлам)** — подготовка серверов.
2. **[Установка Kubespray и зависимостей](#4-установка-kubespray-и-зависимостей)** — клонирование и установка пакетов.
3. **[Конфигурация Inventory](#5-конфигурация-inventory)** — определение состава кластера.
4. **[Конфигурация переменных (group_vars)](#6-конфигурация-переменных-group_vars)** — настройка параметров.
5. **[Запуск развертывания](#7-запуск-развертывания)** — выполнение Ansible playbook.
6. **[Действия после установки](#8-действия-после-установки)** — проверка кластера.

## 3. Предварительные требования к узлам

Перед запуском Kubespray убедитесь, что каждый узел кластера (control plane и worker) соответствует требованиям:

* **ОС:** Поддерживаемый дистрибутив Linux (Ubuntu, CentOS, Rocky Linux, Debian).
* **SSH-доступ:** Настроен доступ по SSH-ключам с машины запуска Ansible. Рекомендуется пользователь `root` или пользователь с беспарольным `sudo`.
* **Отключен SELinux:**
  ```bash
  sudo setenforce 0
  # Отключить навсегда в /etc/selinux/config
  ```
* **Отключен Swap:**
  ```bash
  sudo swapoff -a
  # Закомментировать строку о swap в /etc/fstab
  ```
* **Отключен Firewall:** (firewalld, ufw)
  ```bash
  sudo systemctl stop firewalld
  sudo systemctl disable firewalld
  ```
* **DNS:** Все узлы должны разрешать FQDN друг друга. Рекомендуется локальный DNS-сервер.
* **Python:** На всех узлах должен быть установлен Python (Kubespray обычно устанавливает автоматически).

## 4. Установка Kubespray и зависимостей

1. **Клонировать репозиторий:**
   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   ```

2. **Установить зависимости Ansible:**
   ```bash
   pip install -r requirements.txt
   ```

## 5. Конфигурация Inventory

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

   > **Примечание:** Для небольших кластеров `etcd` можно размещать на узлах control plane. Для HA-кластеров см. [Развертывание HA-кластера](./ha_cluster_deployment_with_kubespray.md).

## 6. Конфигурация переменных (group_vars)

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

> **Важно:** Параметр `etcd_kubeadm_enabled: true` критичен для последующего [управления сертификатами](../../Operations/certificate_management.md).

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

Подробнее о CNI-плагинах: [CNI, kube-proxy и их роли](../../Networking/Network/cni_kube_proxy_roles.md).

## 7. Запуск развертывания

Выполните плейбук `cluster.yml` из корневой директории Kubespray:

```bash
# Для пользователя root
ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml

# Для non-root пользователя с sudo
ansible-playbook -i inventory/my-cluster/inventory.ini --become --user=myuser cluster.yml
```

> **Время выполнения:** 15–30 минут в зависимости от количества узлов и скорости сети.

## 8. Действия после установки

### 8.1. Проверка кластера

1. **Подключиться к любому узлу control plane.**

2. **Проверить статус узлов:**
   ```bash
   kubectl get nodes -o wide
   ```

   **Ожидаемый результат:**
   ```
   NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
   control-1   Ready    control-plane,master   1h    v1.31.0   192.168.1.11    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   worker-1    Ready    <none>                 1h    v1.31.0   192.168.1.21    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   ```

   Обратите внимание на `CONTAINER-RUNTIME` — должен быть `containerd`.

### 8.2. Работа с containerd через crictl

Поскольку Docker не используется, для взаимодействия с контейнерами на уровне узла применяется `crictl`:

* **Запущенные контейнеры** (аналог `docker ps`):
  ```bash
  sudo crictl ps
  ```

* **Запущенные поды на текущем узле:**
  ```bash
  sudo crictl pods
  ```

* **Логи контейнера:**
  ```bash
  sudo crictl logs <CONTAINER_ID>
  ```

Подробнее: [Альтернативные среды выполнения](../../../Podman/alternatives_crio_containerd.md).

### 8.3. Работа с kubeconfig

Если установлен параметр `kubeconfig_localhost: true`, Kubespray скопирует `admin.conf` на локальную машину:

1. **Найти файл:**
   ```
   inventory/my-cluster/artifacts/admin.conf
   ```

2. **Проверить статус узлов:**
   ```bash
   kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
   ```

3. **Установить переменную окружения:**
   ```bash
   export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
   ```

4. **Скопировать в домашнюю директорию (опционально):**
   ```bash
   mkdir -p ~/.kube
   cp inventory/my-cluster/artifacts/admin.conf ~/.kube/config
   ```

Подробнее: [kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md).

### 8.4. Управление и мониторинг

* **Обновление сертификатов:** Сертификаты живут 1 год. Требуется периодическое обновление. См. [Управление сертификатами](../../Operations/certificate_management.md).
* **Графический интерфейс:** Используйте [Lens](../../../ToolsUtilities/lens.md) или другие IDE.
* **Мониторинг:** Разверните [Prometheus](../../MonitoringLogging/Prometheus/prometheus_overview.md) и [Grafana](../../../Grafana/grafana_overview.md).

## 9. Дополнительная информация

* **[Обзор Kubespray](./overview.md)** — определения и основные концепции.
* **[Управление кластером](./cluster_management.md)** — масштабирование и обновление.
* **[Примеры конфигураций](./examples.md)** — Ingress, MetalLB, системные поды.
* **[HA-кластер через Kubespray](../ha_cluster_deployment_with_kubespray.md)** — развертывание высокодоступного кластера.
* **[kubeadm: Быстрый старт](../kudeadm/kubeadm_quickstart.md)** — альтернативный ручной метод.
* **[Управление сертификатами](../../Operations/certificate_management.md)** — обновление сертификатов кластера.
* **[kind](../kind_quickstart.md)** — локальные кластеры для разработки.
* **[Talos](../local_cluster_with_talosctl.md)** — безопасная ОС для K8s.
