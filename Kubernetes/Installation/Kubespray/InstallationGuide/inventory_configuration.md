# 3. Конфигурация Inventory

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
