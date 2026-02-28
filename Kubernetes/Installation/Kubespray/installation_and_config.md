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
    ```

2.  **`inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`**:
    Основные параметры кластера.

    ```yaml
    # Версия Kubernetes
    kube_version: v1.20.2 # Выберите актуальную версию, поддерживаемую Kubespray

    # Среда выполнения контейнеров. Docker устарел, используем containerd
    container_manager: containerd

    # Сетевой CNI-плагин. Рекомендуется Calico.
    kube_network_plugin: calico

    # Сеть для сервисов
    kube_service_addresses: 10.232.0.0/16
    # Сеть для подов
    kube_pods_subnet: 10.233.0.0/16

    # Режим работы kube-proxy. IPVS производительнее iptables
    kube_proxy_mode: ipvs

    # Включить локальный кеширующий DNS на каждом узле для ускорения DNS-запросов
    enable_nodelocaldns: true

    # Принудительная регенерация сертификатов при необходимости
    # (полезно при обновлениях)
    auto_renew_certificates: true
    ```

3.  **`inventory/my-cluster/group_vars/k8s_cluster/k8s-net-calico.yml`**:
    Настройки для сетевого плагина Calico.

    ```yaml
    # Режим инкапсуляции трафика между узлами.
    # IPIP - производительный режим для сетей, где узлы находятся в одном L2-домене.
    # Для VXLAN укажите 'VXLAN'.
    calico_ipip_mode: CrossSubnet
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

## 4. Дополнительная информация

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
* [Дополнительные примеры](./additional_info_and_examples.md) — примеры конфигурации.
