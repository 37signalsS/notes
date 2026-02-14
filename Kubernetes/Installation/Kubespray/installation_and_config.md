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

### 3.1. Установка и конфигурация кластера

#### Шаг 1: Установка зависимостей

После клонирования `kubespray` необходимо установить зависимости из `requirements.txt`.

Сначала обновите `pip`:

```bash
pip install --upgrade pip
```

Затем установите зависимости:

```bash
pip install -r requirements.txt
```

#### Шаг 2: Конфигурация Inventory

1. Скопируйте пример inventory из `inventory/sample` в новую директорию, например, `inventory/my-cluster`.

    ```bash
    cp -rfp inventory/sample inventory/my-cluster
    ```

2. Отредактируйте файл `inventory/my-cluster/inventory.ini`. В нем определяются хосты и их роли в кластере.

    **Пример `inventory.ini`:**

    ```ini
    [all]
    master-1.s000006.example.com ansible_host=172.22.193.2 ip=172.22.193.2 ansible_ssh_user=root etcd_member_name=etcd1
    master-2.s000006.example.com ansible_host=172.22.193.3 ip=172.22.193.3 ansible_ssh_user=root etcd_member_name=etcd2
    master-3.s000006.example.com ansible_host=172.22.193.4 ip=172.22.193.4 ansible_ssh_user=root etcd_member_name=etcd3
    ingress-1.s000006.example.com ansible_host=172.22.193.5 ip=172.22.193.5 ansible_ssh_user=root
    node-1.s000006.example.com ansible_host=172.22.193.6 ip=172.22.193.6 ansible_ssh_user=root
    node-2.s000006.example.com ansible_host=172.22.193.7 ip=172.22.193.7 ansible_ssh_user=root

    [kube_control_plane]
    master-1.s000006.example.com
    master-2.s000006.example.com
    master-3.s000006.example.com

    [etcd]
    master-1.s000006.example.com
    master-2.s000006.example.com
    master-3.s000006.example.com

    [kube_node]
    node-1.s000006.example.com
    node-2.s000006.example.com
    ingress-1.s000006.example.com

    [kube_ingress]
    ingress-1.s000006.example.com

    [k8s-cluster:children]
    kube_control_plane
    kube_node
    ```

#### Шаг 3: Конфигурация переменных (group_vars)

В Ansible переменные для групп хостов определяются в каталоге `group_vars`.

* **Для всех хостов:** Переменные, применяемые ко всем хостам из inventory, можно указать в файле `group_vars/all/all.yml`. Если переменных много, их можно разложить на несколько файлов в директории `group_vars/all/`.
* **Для конкретной группы:** Для группы `etcd` переменные будут находиться в `group_vars/etcd.yml` или в каталоге `group_vars/etcd/`.

**Пример `group_vars/all/all.yml`:**

```yaml
# Позволяет kubelet подгружать необходимые модули ядра
kubelet_load_modules: true
# Отключает использование kubeadm (используется классический способ установки)
kubeadm_enabled: false
# Включает read-only порт (10255) для сбора метрик без авторизации
kube_read_only_port: 10255
```

**Пример `group_vars/all/docker.yml`:**

```yaml
# Устанавливает `overlay2` как драйвер хранилища для Docker
docker_storage_options: -s overlay2
```

**Пример `group_vars/all/download.yml`:**

```yaml
# Оптимизация загрузки: файлы и образы скачиваются один раз на один узел,
# а затем копируются на остальные узлы кластера.
download_run_once: true
```

**Пример `group_vars/etcd.yml`:**

```yaml
# Уменьшает количество записей в журнале операций, хранимых в памяти,
# для снижения потребления памяти etcd.
etcd_snapshot_count: "5000"
# Устанавливает приоритет I/O для etcd
etcd_ionice: '-c2 -n0'
# Лимит памяти для etcd (0 - без ограничений)
etcd_memory_limit: 0
```

**Пример `group_vars/k8s-cluster/k8s-cluster.yml`:**

```yaml
# Версия Kubernetes для установки
kube_version: v1.34.5

# Отключаем все методы аутентификации, оставляя только по токену
kube_oidc_auth: false
kube_basic_auth: false

# Сетевой CNI-плагин
kube_network_plugin: flannel
# Сеть для сервисов типа ClusterIP
kube_service_addresses: 10.100.0.0/16
# Сеть для подов
kube_pods_subnet: 10.0.0.0/16

# Отключаем небезопасный порт API-сервера
kube_apiserver_insecure_port: 0
# Режим работы kube-proxy
kube_proxy_mode: iptables
cluster_name: s000000.1local

# Копирование kubeconfig на локальную машину для управления кластером
kubeconfig_localhost: true
kubectl_localhost: true

# Включаем аутентификацию и авторизацию kubelet через вебхуки по токену
kubelet_authentication_token_webhook: true
kubelet_authorization_mode_webhook: true
```

**Пример `group_vars/k8s-cluster/k8s-net-flannel.yml`:**

```yaml
# Указываем бэкенд для Flannel. host-gw - самый быстрый и простой режим,
# так как он создает статические маршруты между узлами в одной L2-сети.
flannel_backend_type: "host-gw"
# Указываем Flannel, на каком сетевом интерфейсе работать.
# Он выберет тот интерфейс, IP-адрес которого совпадет с регулярным выражением.
flannel_interface_regexp: '172\.21\.0\.\d{1,3}'
```

#### Шаг 4: Запуск развертывания

После подготовки всех файлов конфигурации (`inventory.ini` и переменных в `group_vars`) запустите главный плейбук `cluster.yml` из корневой директории Kubespray:

```bash
ansible-playbook cluster.yml 
  -i inventory/my-cluster/inventory.ini 
  -u myuser -b 
  --private-key=~/.ssh/id_rsa
```

(Параметры: `-i` — путь к инвентарю, `-u` — пользователь SSH, `-b` — повышение привилегий, `--private-key` — путь к SSH-ключу.)

### 3.2. Проверка и доступ к кластеру

Если в конфигурации был установлен параметр `kubeconfig_localhost: true`, Kubespray скопирует файл `admin.conf` на вашу локальную машину.

Подробнее о работе с kubeconfig читайте в [руководстве по подключению](../../Operations/kubeconfig_and_connection.md).

1. **Найдите файл kubeconfig:** Он будет находиться в `inventory/имя_вашего_кластера/artifacts/admin.conf`.
2. **Выполните команду для проверки статуса узлов:**

    ```bash
    kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
    ```

3. **(Опционально) Установите переменную окружения `KUBECONFIG`:**

    ```bash
    export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
    # Теперь можно выполнять команды kubectl без флага --kubeconfig
    kubectl get nodes
    ```

    В выводе вы должны увидеть все узлы кластера со статусом `Ready`.

## 4. Дополнительная информация

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
* [Дополнительные примеры](./additional_info_and_examples.md) — примеры конфигурации.
