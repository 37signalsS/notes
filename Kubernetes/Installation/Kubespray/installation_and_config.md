# Kubespray: Установка и конфигурация кластера

## 1. Определения

**Kubespray** — инструмент для автоматизации развертывания кластеров Kubernetes на базе Ansible. Подробнее в [обзоре](./overview.md).

## 2. Основные концепции

### Компоненты конфигурации

* **Inventory** — файл `inventory.ini`, определяющий хосты и их роли в кластере.
* **Group vars** — переменные для групп хостов в директории `group_vars`:
  * `all/` — общие переменные для всех хостов.
  * `k8s-cluster/` — переменные для компонентов Kubernetes.
* **Плейбуки** — основной плейбук `cluster.yml` для развертывания.

### Требования

* Python 3 + pip
* Ansible (устанавливается через `requirements.txt`)
* SSH-доступ до целевых хостов

## 3. Практические сценарии

### 3.1. Предварительные требования к узлам

Перед запуском Kubespray убедитесь, что каждый узел кластера (control plane и worker) соответствует следующим требованиям:

*   **ОС:** Поддерживаемый дистрибутив Linux (например, Ubuntu, CentOS).
*   **SSH-доступ:** Настроен доступ по SSH-ключам с машины, где будет запускаться Ansible. Рекомендуется использовать пользователя `root` или пользователя с беспарольным `sudo`.
*   **Отключен SELinux:**
    ```bash
    sudo setenforce 0
    # Отключить навсегда в /etc/selinux/config
    ```
*   **Отключен Swap:**
    ```bash
    sudo swapoff -a
    # Закомментировать строку о swap в /etc/fstab
    ```
*   **Отключен Firewall:** (например, `firewalld` или `ufw`)
    ```bash
    sudo systemctl stop firewalld
    sudo systemctl disable firewalld
    ```
*   **DNS:** Все узлы должны иметь возможность разрешать FQDN друг друга. Рекомендуется настроить для этого локальный DNS-сервер.
*   **Python:** На всех узлах должен быть установлен Python (обычно Kubespray справляется с этим автоматически).

### 3.2. Установка и конфигурация

#### Шаг 1: Клонирование Kubespray и установка зависимостей

1.  **Клонировать репозиторий:**
    ```bash
    git clone https://github.com/kubernetes-sigs/kubespray.git
    cd kubespray
    ```

2.  **Установить зависимости Ansible:**
    ```bash
    pip install -r requirements.txt
    ```

#### Шаг 2: Конфигурация Inventory

1.  Скопируйте пример inventory из `inventory/sample` в новую директорию, например, `inventory/my-cluster`.
    ```bash
    cp -rfp inventory/sample inventory/my-cluster
    ```
2.  Отредактируйте файл `inventory/my-cluster/inventory.ini`, чтобы он отражал состав вашего кластера. Для небольших кластеров `etcd` можно размещать на узлах control plane.

    **Пример `inventory.ini`:**
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

#### Шаг 3: Конфигурация переменных (`group_vars`)

Это наиболее важный шаг, где определяется конфигурация кластера.

1.  **`inventory/my-cluster/group_vars/all/all.yml`**:
    Здесь указывается, что `etcd` должен устанавливаться и управляться через `kubeadm`. Это критически важно для последующего [управления сертификатами](../../Operations/certificate_management.md).

    ```yaml
    # Управлять etcd через kubeadm
    etcd_kubeadm_enabled: true
    # На каждой ноде будет запущен локальный прокси на API-сервер
    loadbalancer_apiserver_localhost: true
    # Позволяет kubelet подгружать необходимые модули ядра
    kubelet_load_modules: true
    # Отключает использование kubeadm (используется классический способ установки)
    kubeadm_enabled: false
    # Включает read-only порт (10255) для сбора метрик без авторизации
    kube_read_only_port: 10255
    ```

2.  **`inventory/my-cluster/group_vars/all/docker.yml`** (опционально):
    Настройки для Docker (если используется вместо containerd).

    ```yaml
    # Устанавливает `overlay2` как драйвер хранилища для Docker
    docker_storage_options: -s overlay2
    ```

3.  **`inventory/my-cluster/group_vars/all/download.yml`**:
    Оптимизация загрузки артефактов.

    ```yaml
    # Оптимизация загрузки: файлы и образы скачиваются один раз на один узел,
    # а затем копируются на остальные узлы кластера.
    download_run_once: true
    ```

4.  **`inventory/my-cluster/group_vars/etcd.yml`**:
    Настройки для компонента etcd.

    ```yaml
    # Уменьшает количество записей в журнале операций, хранимых в памяти,
    # для снижения потребления памяти etcd.
    etcd_snapshot_count: "5000"
    # Устанавливает приоритет I/O для etcd
    etcd_ionice: '-c2 -n0'
    # Лимит памяти для etcd (0 - без ограничений)
    etcd_memory_limit: 0
    ```

5.  **`inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`**:
    Основные параметры кластера.

    ```yaml
    # Версия Kubernetes (укажите актуальную стабильную версию)
    kube_version: v1.31.0

    # Среда выполнения контейнеров. Docker устарел, используем containerd
    container_manager: containerd

    # Сетевой CNI-плагин. Рекомендуется Calico.
    kube_network_plugin: calico

    # Сеть для сервисов типа ClusterIP
    kube_service_addresses: 10.232.0.0/16
    # Сеть для подов
    kube_pods_subnet: 10.233.0.0/16

    # Режим работы kube-proxy. IPVS производительнее iptables
    kube_proxy_mode: ipvs

    # Имя кластера
    cluster_name: k8s-cluster

    # Отключаем небезопасный порт API-сервера
    kube_apiserver_insecure_port: 0

    # Отключаем OIDC и basic auth, оставляем только токен
    kube_oidc_auth: false
    kube_basic_auth: false

    # Копирование kubeconfig на локальную машину для управления кластером
    kubeconfig_localhost: true
    kubectl_localhost: true

    # Включаем аутентификацию и авторизацию kubelet через вебхуки по токену
    kubelet_authentication_token_webhook: true
    kubelet_authorization_mode_webhook: true

    # Включить локальный кеширующий DNS на каждом узле для ускорения DNS-запросов
    enable_nodelocaldns: true

    # Принудительная регенерация сертификатов при необходимости
    # (полезно при обновлениях)
    auto_renew_certificates: true
    ```

6.  **`inventory/my-cluster/group_vars/k8s_cluster/k8s-net-calico.yml`** (или `k8s-net-flannel.yml`):
    Настройки для сетевого плагина.

    **Для Calico:**
    ```yaml
    # Режим инкапсуляции трафика между узлами.
    # IPIP - производительный режим для сетей, где узлы находятся в одном L2-домене.
    # Для VXLAN укажите 'VXLAN'.
    calico_ipip_mode: CrossSubnet
    ```

    **Для Flannel:**
    ```yaml
    # Указываем бэкенд для Flannel. host-gw - самый быстрый и простой режим,
    # так как он создает статические маршруты между узлами в одной L2-сети.
    flannel_backend_type: "host-gw"
    # Указываем Flannel, на каком сетевом интерфейсе работать.
    # Он выберет тот интерфейс, IP-адрес которого совпадет с регулярным выражением.
    flannel_interface_regexp: '192\.168\.1\.\d{1,3}'
    ```

#### Шаг 4: Запуск развертывания

Выполните плейбук `cluster.yml` из корневой директории Kubespray, указав путь к вашему inventory.

```bash
# Если вы используете пользователя root для SSH
ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml

# Если вы используете non-root пользователя с sudo
ansible-playbook -i inventory/my-cluster/inventory.ini --become --user=myuser cluster.yml
```

Процесс установки может занять 15-30 минут.

### 3.3. Действия после установки

#### Проверка кластера

1.  Подключитесь к любому узлу control plane.
2.  Выполните команду `kubectl get nodes -o wide`, чтобы убедиться, что все узлы в статусе `Ready`.

    ```
    NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     EXTERNAL-IP   OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
    control-1   Ready    control-plane,master   1h    v1.20.2   192.168.1.11    <none>        CentOS Linux 7   3.10.0-1160...    containerd://1.4.3
    ...
    ```
    Обратите внимание на `CONTAINER-RUNTIME`, который должен быть `containerd`.

#### Работа с `containerd` через `crictl`

Поскольку в кластере не используется Docker, для взаимодействия с контейнерами на уровне узла используется утилита `crictl`.

*   **Посмотреть запущенные контейнеры** (аналог `docker ps`):
    ```bash
    sudo crictl ps
    ```
*   **Посмотреть запущенные поды на текущем узле:**
    ```bash
    sudo crictl pods
    ```
*   **Посмотреть логи контейнера:**
    ```bash
    sudo crictl logs <CONTAINER_ID>
    ```
Подробнее об альтернативных средах выполнения см. в [этой заметке](../../../Podman/alternatives_crio_containerd.md).

#### Управление и мониторинг

*   **Обновление сертификатов:** Сертификаты кластера живут 1 год. Их необходимо периодически обновлять. Подробнее см. [Управление сертификатами Kubernetes](../../Operations/certificate_management.md).
*   **Графический интерфейс:** Для удобного управления кластером можно использовать IDE, такие как [Lens](../../ToolsUtilities/lens.md).
*   **Доступ к кластеру:** Файл `kubeconfig` для доступа к кластеру (`admin.conf`) будет создан в директории `inventory/my-cluster/artifacts/`.

#### Работа с kubeconfig

Если в конфигурации установлен параметр `kubeconfig_localhost: true`, Kubespray скопирует файл `admin.conf` на локальную машину.

1.  **Найти файл kubeconfig:**
    Файл находится в `inventory/my-cluster/artifacts/admin.conf`.

2.  **Проверить статус узлов:**
    ```bash
    kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
    ```

3.  **Установить переменную окружения `KUBECONFIG`:**
    ```bash
    export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
    # Теперь можно выполнять команды kubectl без флага --kubeconfig
    kubectl get nodes
    ```

4.  **Скопировать kubeconfig в домашнюю директорию (опционально):**
    ```bash
    mkdir -p ~/.kube
    cp inventory/my-cluster/artifacts/admin.conf ~/.kube/config
    ```

Подробнее о работе с kubeconfig см. в [руководстве по подключению](../../Operations/kubeconfig_and_connection.md).

## 4. Дополнительная информация

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
* [Дополнительные примеры](./additional_info_and_examples.md) — примеры конфигурации.
