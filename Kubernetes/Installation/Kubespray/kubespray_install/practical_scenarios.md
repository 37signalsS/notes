# Kubespray: Установка — Практические сценарии

## Практические сценарии

### Установка Kubespray и зависимостей

1. **Подготовить машину управления** (узла, с которой будет запускаться Ansible):

   ```bash
   # Обновить репозитории
   sudo apt update

   # Установить базовые пакеты
   sudo apt install -y git python3-pip software-properties-common

   # Добавить репозиторий для Python 3.9 (опционально, если нужна конкретная версия)
   sudo add-apt-repository -y ppa:deadsnakes/ppa
   sudo apt update
   sudo apt install -y python3.9 python3.9-venv

   # Получить pip для нужной версии Python
   curl -sS https://bootstrap.pypa.io/get-pip.py | python3.9
   ```

   > **Примечание:** После установки пакетов может потребоваться перезайти в SSH-сессию, чтобы обновились переменные окружения (PATH). Это нормальная ситуация — если Ansible не находится через `which ansible`, выйдите и снова войдите на сервер.

2. **Клонировать репозиторий** (выполнять от обычного пользователя, не root):

   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   ```

3. **Установить зависимости Ansible:**

   ```bash
   # Python 3.9
   python3.9 -m pip install -r requirements.txt
   ```

### Настройка SSH-доступа

Kubespray требует SSH-доступ с машины управления ко всем узлам кластера. Если узлы созданы в облаке (Yandex Cloud, AWS и т.д.), публичные ключи уже добавлены на целевые машины. Необходимо скопировать приватный ключ на машину управления:

```bash
# С локальной машины скопировать приватный ключ
scp -i ~/.ssh/your-key.pem ~/.ssh/your-key.pem user@control-plane:~/.ssh/id_rsa

# На машине управления выставить правильные права
chmod 600 ~/.ssh/id_rsa
```

Альтернативно — использовать стандартный путь `~/.ssh/id_rsa` или указать ключ в inventory через переменную `ansible_ssh_private_key_file`.

### Конфигурация Inventory

1. **Скопировать пример inventory:**

   ```bash
   cp -rfp inventory/sample inventory/my-cluster
   ```

2. **Сгенерировать inventory через declarator** (опционально):

   Kubespray включает утилиту `declarator` для автоматической генерации `inventory.ini` из списка IP-адресов:

   ```bash
   # Указать IP-адреса узлов
   IPS="10.128.0.2 10.128.0.35 10.128.0.1"

   # Сгенерировать inventory
   declare -a IPS=(${IPS//,/ })
   CONFIG_FILE=inventory/my-cluster/hosts.yaml python3.9 contrib/inventory_builder/inventory.py ${IPS[@]}
   ```

   Результат появится в `inventory/my-cluster/hosts.yaml` (или `inventory.ini`).

3. **Отредактировать inventory вручную:**

   После генерации необходимо проверить и при необходимости исправить роли узлов. Kubespray по умолчанию может добавить несколько узлов в группу `kube_control_plane` — для учебных кластеров это нежелательно.

   **Пример для учебного кластера (1 control plane + 2 worker):**

   ```ini
   [all]
   node1 ansible_host=10.128.0.2
   node2 ansible_host=10.128.0.35
   node3 ansible_host=10.128.0.1

   [kube_control_plane]
   node1

   [etcd]
   node1

   [kube_node]
   node2
   node3

   [k8s_cluster:children]
   kube_control_plane
   kube_node
   ```

   **Рекомендация:** Для учебных/тестовых кластеров лучше явно разделить роли: одна нода как control plane + etcd, остальные — только worker. Для продакшн-кластеров минимум 3 control plane ноды.

   **Пример для HA-кластера (3 control plane + 2 worker):**

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

   **Примечание:** Для небольших кластеров `etcd` можно размещать на узлах control plane. Для HA-кластеров см. [Развертывание HA-кластера](../HA/index.md).

### Конфигурация переменных (group_vars)

#### `inventory/my-cluster/group_vars/all/all.yml`

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

**Важно:** Параметр `etcd_kubeadm_enabled: true` критичен для последующего [управления сертификатами](../../../Operations/certificate_management.md).

#### `inventory/my-cluster/group_vars/all/docker.yml` (опционально)

Настройки для Docker (если используется вместо containerd):

```yaml
# Overlay2 как драйвер хранилища для Docker
docker_storage_options: -s overlay2
```

#### `inventory/my-cluster/group_vars/all/download.yml`

Оптимизация загрузки артефактов:

```yaml
# Файлы и образы скачиваются один раз на один узел,
# затем копируются на остальные узлы кластера
download_run_once: true
```

#### `inventory/my-cluster/group_vars/etcd.yml`

Настройки для компонента etcd:

```yaml
# Уменьшает количество записей в журнале операций в памяти
etcd_snapshot_count: "5000"

# Приоритет I/O для etcd
etcd_ionice: '-c2 -n0'

# Лимит памяти для etcd (0 - без ограничений)
etcd_memory_limit: 0
```

#### `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`

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

**Важно:** Версия Kubernetes должна соответствовать версии Kubespray. Проверьте поддерживаемые версии в файле `roles/download/defaults/main.yml` (переменная `kubelet_checksums`).

#### Настройки сетевого плагина

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

Подробнее о CNI-плагинах: [CNI и kube-proxy: навигатор](../../../Networking/Network/cni_kube_proxy_roles.md).

### Запуск развертывания

Выполните плейбук `cluster.yml` из корневой директории Kubespray:

```bash
# Для пользователя root
ansible-playbook -i inventory/my-cluster/hosts.yaml cluster.yml

# Для non-root пользователя с sudo (рекомендуется)
ansible-playbook -i inventory/my-cluster/hosts.yaml --become --user=myuser -v cluster.yml
```

**Флаги:**

- `--become` (`-b`) — выполнение команд через sudo на целевых узлах
- `-v` — verbose-вывод для отслеживания прогресса
- `--user=<username>` — пользователь для SSH-подключения

**Время выполнения:** 15–30 минут в зависимости от количества узлов и скорости сети. Для учебных кластеров (~3 ноды) — около 18–20 минут.

### Проверка кластера после установки

После успешного завершения Ansible playbook `cluster.yml` выполните проверку:

1. **Подключиться к узлу control plane:**

   ```bash
   ssh user@control-plane-ip
   ```

2. **Проверить статус узлов:**

   ```bash
   kubectl get nodes -o wide
   ```

   **Ожидаемый вывод:**

   ```
   NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
   control-1   Ready    control-plane,master   1h    v1.31.0   192.168.1.11    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   worker-1    Ready    <none>                 1h    v1.31.0   192.168.1.21    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   ```

   Обратите внимание на `CONTAINER-RUNTIME` — должен быть `containerd://`.

3. **Запустить тестовый под для проверки работоспособности:**

   ```bash
   kubectl run test-busybox --image=busybox --restart=Never --command -- sleep 3600
   kubectl get pods
   ```

   Если под успешно создался и перешёл в статус `Running` — кластер функционирует. Для учебных целей можно удалить:

   ```bash
   kubectl delete pod test-busybox
   ```

   > **Примечание:** Запуск пода без команд (`busybox` без `sleep`) приведёт к CrashLoopBackOff, так как контейнер завершает работу немедленно. Это нормальное поведение — главное, что под создаётся и запускается.

### Работа с crictl

Kubespray использует `containerd` как среду выполнения контейнеров. Docker не устанавливается. Для диагностики на уровне узлов применяется `crictl` — CLI для Container Runtime Interface.

**Запущенные контейнеры на узле** (аналог `docker ps`):

```bash
sudo crictl ps
```

**Запущенные поды на текущем узле:**

```bash
sudo crictl pods
```

**Просмотр логов контейнера:**

```bash
sudo crictl logs <CONTAINER_ID>
```

Подробнее о средах выполнения: [Альтернативные среды выполнения](../../../Docker/alternative_runtimes_and_tools.md).

### Настройка kubeconfig

При настройке `kubeconfig_localhost: true` Kubespray копирует `admin.conf` на локальную машину в `inventory/<cluster>/artifacts/admin.conf`.

1. **Найти файл на локальной машине:**

   ```
   inventory/my-cluster/artifacts/admin.conf
   ```

2. **Проверить кластер без установки переменной:**

   ```bash
   kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
   ```

3. **Установить переменную окружения:**

   ```bash
   export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
   ```

4. **Скопировать в домашнюю директорию:**

   ```bash
   mkdir -p ~/.kube
   cp inventory/my-cluster/artifacts/admin.conf ~/.kube/config
   chmod 600 ~/.kube/config
   ```

Подробнее: [kubeconfig и подключение](../../../Operations/kubeconfig_and_connection.md).

---

## Дополнительная информация

### Связанные темы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, требования, этапы установки
- **[Дополнительная информация](./additional_info.md)** — концепции post-install проверки
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре
