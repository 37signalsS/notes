# 6. Действия после установки

### 6.1. Проверка кластера

1.  Подключитесь к любому узлу control plane.
2.  Выполните команду `kubectl get nodes -o wide`, чтобы убедиться, что все узлы в статусе `Ready`.

    ```
    NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     EXTERNAL-IP   OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
    control-1   Ready    control-plane,master   1h    v1.20.2   192.168.1.11    <none>        CentOS Linux 7   3.10.0-1160...    containerd://1.4.3
    ...
    ```
    Обратите внимание на `CONTAINER-RUNTIME`, который должен быть `containerd`.

### 6.2. Работа с `containerd` через `crictl`

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
Подробнее об альтернативных средах выполнения см. в [этой заметке](../../../../Podman/alternatives_crio_containerd.md).

### 6.3. Управление и мониторинг

*   **Обновление сертификатов:** Сертификаты кластера живут 1 год. Их необходимо периодически обновлять. Подробнее см. [Управление сертификатами Kubernetes](../../../Operations/certificate_management.md).
*   **Графический интерфейс:** Для удобного управления кластером можно использовать IDE, такие как [Lens](../../../ToolsUtilities/lens.md).
*   **Доступ к кластеру:** Файл `kubeconfig` для доступа к кластеру (`admin.conf`) будет создан в директории `inventory/my-cluster/artifacts/`.

### 6.4. Работа с kubeconfig

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

Подробнее о работе с kubeconfig см. в [руководстве по подключению](../../../Operations/kubeconfig_and_connection.md).
