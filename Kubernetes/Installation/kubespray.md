# Kubespray

## 1. Определения

**Kubespray** — это проект с открытым исходным кодом, который объединяет **Ansible** и **kubeadm** для автоматизации процесса установки и управления жизненным циклом кластеров Kubernetes.

В то время как `kubeadm` является инструментом **для инициализации отдельных узлов кластера**, Kubespray автоматизирует выполнение команд `kubeadm` на всех хостах (мастер- и рабочих узлах) с помощью Ansible-плейбуков. Это позволяет декларативно описывать состояние кластера и применять его к целевым серверам.

## 2. Основные концепции

### Ключевые возможности

*   **Автоматизация:** Полностью автоматизированное развертывание, масштабирование и обновление кластеров.
*   **Гибкость:** Поддерживает большое количество операционных систем (Ubuntu, CentOS, и др.).
*   **Настраиваемость:** Позволяет легко настраивать компоненты кластера, включая:
    *   Сетевые плагины (CNI), такие как Calico, Cilium, Flannel.
    *   DNS-провайдеры (например, CoreDNS).
    *   Различные среды выполнения контейнеров.
*   **Отказоустойчивость (HA):** Встроенная поддержка для создания высокодоступных Control Plane.

### Недостатки и рекомендации

*   **Медленная скорость изменений:** Так как Kubespray основан на Ansible (Python) и использует большое количество ролей, любые изменения в конфигурации кластера могут занимать много времени.
*   **Установка дополнений:** Установку дополнительных компонентов (например, DNS или систем мониторинга) рекомендуется выполнять отдельно, а не в рамках Kubespray. Это связано с медленной скоростью работы и потенциальными ошибками, которые усложняют процесс обновления и отката.
*   **Обновления и масштабирование:** Kubespray предоставляет отдельные Ansible-плейбуки для добавления новых узлов и для обновления кластера. Однако следует помнить, что эти процессы также могут быть медленными.
*   **Основной файл конфигурации:** Центральным файлом для описания кластера является `cluster.yml`.

## 3. Практические сценарии

### 3.1. Установка и конфигурация кластера

#### Шаг 1: Установка зависимостей

После клонирования директории `kubespray` необходимо установить зависимости.

1.  Найдите файл `requirements.txt`.

2.  Обновите `pip`:

    ```bash
    pip install --upgrade pip
    ```

3.  Установите зависимости:

    ```bash
    pip install -r requirements.txt
    ```

#### Шаг 2: Конфигурация Inventory

1.  Скопируйте пример inventory из `inventory/sample` в новую директорию, например, `inventory/my-cluster`.
    ```bash
    cp -rfp inventory/sample inventory/my-cluster
    ```
2.  Отредактируйте файл `inventory/my-cluster/inventory.ini`. В нем определяются хосты и их роли в кластере.

    **Пример `inventory.ini`:**
    ```ini
    [all]
    master-1.s000006.slurm.io ansible_host=172.22.193.2 ip=172.22.193.2 ansible_ssh_user=root etcd_member_name=etcd1
    master-2.s000006.slurm.io ansible_host=172.22.193.3 ip=172.22.193.3 ansible_ssh_user=root etcd_member_name=etcd2
    master-3.s000006.slurm.io ansible_host=172.22.193.4 ip=172.22.193.4 ansible_ssh_user=root etcd_member_name=etcd3
    ingress-1.s000006.slurm.io ansible_host=172.22.193.5 ip=172.22.193.5 ansible_ssh_user=root
    node-1.s000006.slurm.io ansible_host=172.22.193.6 ip=172.22.193.6 ansible_ssh_user=root
    node-2.s000006.slurm.io ansible_host=172.22.193.7 ip=172.22.193.7 ansible_ssh_user=root

    [kube_control_plane]
    master-1.s000006.slurm.io
    master-2.s000006.slurm.io
    master-3.s000006.slurm.io

    [etcd]
    master-1.s000006.slurm.io
    master-2.s000006.slurm.io
    master-3.s000006.slurm.io

    [kube_node]
    node-1.s000006.slurm.io
    node-2.s000006.slurm.io
    ingress-1.s000006.slurm.io

    [kube_ingress]
    ingress-1.s000006.slurm.io

    [k8s-cluster:children]
    kube_control_plane
    kube_node
    ```

#### Шаг 3: Конфигурация переменных (group_vars)

В Ansible переменные для групп хостов определяются в каталоге `group_vars`.

*   **Для всех хостов:** Переменные, применяемые ко всем хостам из inventory, можно указать в файле `group_vars/all/all.yml`. Если переменных много, их можно разложить на несколько файлов в директории `group_vars/all/`.
*   **Для конкретной группы:** Для группы `etcd` переменные будут находиться в `group_vars/etcd.yml` или в каталоге `group_vars/etcd/`.

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

После того как все файлы конфигурации (`inventory.ini` и переменные в `group_vars`) подготовлены, можно запустить главный плейбук `cluster.yml` из корневой директории Kubespray. Этот файл обычно является "точкой входа", которая импортирует основной плейбук `playbooks/cluster.yml`.

```bash
ansible-playbook cluster.yml \
  -i inventory/my-cluster/inventory.ini \
  -u myuser -b \
  --private-key=~/.ssh/id_rsa
```
*   `ansible-playbook cluster.yml`: Запускает выполнение плейбука.
*   `-i inventory/my-cluster/inventory.ini`: Указывает путь к вашему файлу инвентаря.
*   `-u myuser` или `--user=myuser`: Задает имя пользователя для SSH-подключения к узлам.
*   `-b` или `--become`: Указывает Ansible повысить привилегии (например, через `sudo`) для выполнения задач, требующих прав `root`.
*   `--private-key=~/.ssh/id_rsa`: Указывает путь к вашему приватному SSH-ключу для аутентификации на узлах.

### 3.2. Проверка и доступ к кластеру

Если в конфигурации был установлен параметр `kubeconfig_localhost: true`, Kubespray скопирует файл `admin.conf` на вашу локальную машину.

1.  **Найдите файл kubeconfig:** Он будет находиться в `inventory/имя_вашего_кластера/artifacts/admin.conf`.
2.  **Выполните команду для проверки статуса узлов:**
    ```bash
    kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
    ```
3.  **(Опционально) Установите переменную окружения `KUBECONFIG`:**
    ```bash
    export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
    # Теперь можно выполнять команды kubectl без флага --kubeconfig
    kubectl get nodes
    ```
    В выводе вы должны увидеть все узлы кластера со статусом `Ready`.

### 3.3. Управление кластером: Масштабирование

#### Добавление Worker Node
1.  **Обновите inventory:** Добавьте новые узлы в `inventory.ini` в группу `[kube_node]`.
2.  **Запустите плейбук `scale.yml`:**
    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini scale.yml
    ```

#### Добавление Master Node (Control Plane)
1.  **Обновите inventory:** Добавьте новые master-узлы в `inventory.ini` в группы `[kube_control_plane]` и `[etcd]`.
2.  **Запустите плейбук `cluster.yml`:** Для добавления master-узлов используется основной плейбук.
    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml
    ```

### 3.4. Управление кластером: Обновление

#### Проверка доступной версии для обновления
Перед обновлением выясните, до какой версии Kubernetes можно обновиться с вашей версией Kubespray.
1.  Перейдите в директорию `roles/download/defaults`.
2.  Откройте файл `main.yml` и найдите переменную `kubelet_checksums`.

#### Процесс обновления
1.  **Измените версию** в `group_vars/k8s-cluster/k8s-cluster.yml`:
    ```yaml
    kube_version: v1.35.0
    ```
2.  **Запустите плейбук `upgrade-cluster.yml`:**
    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini upgrade-cluster.yml
    ```
    > **Важно:** Плейбук `upgrade-cluster.yml` выполняет задачи последовательно на каждом узле, а не параллельно, для большей безопасности.

#### Проверка после обновления
1.  **Проверьте версию API Server и `kubelet`:**
    ```bash
    kubectl version
    kubectl get nodes
    ```
2.  **Проверьте версии компонентов Control Plane**, посмотрев на версию образа (`Image`) в описании их подов:
    ```bash
    kubectl describe pod <pod-name> -n kube-system
    ```

#### Возможные проблемы и важные моменты при обновлении
*   **Правило одной минорной версии:** Обновлять кластер можно только последовательно, на одну минорную версию за раз (например, с `1.34` на `1.35`).
*   **Устаревшие API и манифесты:** В новых версиях Kubernetes могут быть удалены API. Проверяйте манифесты на использование устаревших `apiVersion`.
*   **Изменение опций компонентов:** Параметры запуска компонентов могут измениться. Kubespray обычно это обрабатывает, но кастомные конфигурации могут потребовать ручной корректировки.
*   **Проверка `release notes`:** Критически важно изучить официальные `release notes` для новой версии Kubernetes.

## 4. Дополнительная информация

### 4.1. Системные поды после установки
После установки в пространстве имен `kube-system` будут развернуты системные поды. Их состав зависит от конфигурации.
*   **Control Plane (Static Pods):** `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*`.
*   **Сетевые компоненты:** `kube-flannel-*` (или Calico, Cilium), `kube-proxy-*`.
*   **DNS и сервисы:** `coredns-*`, `dns-autoscaler`, `nodelocaldns-*`.
*   **Дополнения (Addons):** `kubernetes-dashboard-*`, `nginx-proxy-ingress-*` и др.

Подробнее о пространствах имен и о том, как Kubespray их использует, можно прочитать в документе [о пространствах имен](../Base/namespace.md#namespaces-и-kubespray).

### 4.2. Пример: Выделенные ноды для Ingress
Этот подход использует `taints` и `tolerations` для изоляции Ingress-подов на выделенных узлах. Подробное объяснение механизма: **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md)**.

**`group_vars/k8s-cluster/addons.yml`**
```yaml
# Параметры для дополнительного ПО
ingress_nginx_enabled: true
ingress_nginx_host_network: true # Прокидывает сетевой неймспейс узла внутрь контейнера
ingress_nginx_configmap: # Настройки ConfigMap для Ingress-контроллера
  server-tokens: "false" # Не показывать версию Nginx
  proxy-body-size: "2048m" # Максимальный размер тела запроса
  proxy-buffer-size: "16k" # Размер буфера для прокси
  worker-shutdown-timeout: "180s" # Таймаут для graceful shutdown воркеров
ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: "" # Запускать поды только на нодах с этой меткой
ingress_nginx_tolerations: # Позволяет подам запускаться на "отравленных" нодах
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

**`group_vars/all/kube-ingress.yml`** (не существует по-умолчанию, создается пользователем)
```yaml
# На ноды из группы 'kube_ingress' будет установлена соответствующая метка
node_labels:
  node-role.kubernetes.io/ingress: ""

# На эти же ноды будет добавлено "отравление" (taint)
node_taints:
  - "node-role.kubernetes.io/ingress:NoSchedule"
```

### 4.3. Пример: Конфигурация MetalLB
**MetalLB** — это реализация балансировщика нагрузки для bare-metal кластеров, которая позволяет использовать сервисы типа `LoadBalancer`.

**`group_vars/k8s-cluster/addons.yml`**
```yaml
# Включаем MetalLB
metallb_enabled: true
metallb_speaker_enabled: true

# Определяем пулы IP-адресов, которые MetalLB будет использовать
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "5.75.169.149/32"
        - "91.99.78.20/32"
      # auto_assign: false # Можно отключить автоматическое назначение адресов для этого пула
```

*   `metallb_enabled: true`: Включает установку MetalLB.
*   `metallb_speaker_enabled: true`: Включает компонент `speaker`, который отвечает за анонсирование IP-адресов по протоколам L2 (ARP) или BGP.
*   `metallb_config`: Содержит конфигурацию пулов адресов. В данном примере определен один пул `primary` с двумя IP-адресами, которые могут быть назначены сервисам типа `LoadBalancer`.