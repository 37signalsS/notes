# Развертывание HA-кластера Kubernetes с помощью Kubespray

## Определения

* **HA-кластер (High Availability Cluster):** Кластер, спроектированный для обеспечения непрерывной работы и отсутствия единой точки отказа (Single Point of Failure, SPoF). В контексте Kubernetes это означает запуск нескольких экземпляров компонентов Control Plane (особенно `kube-apiserver`) на разных узлах.
* **Kubespray:** Инструмент на базе Ansible, который автоматизирует развертывание и управление жизненным циклом production-ready кластеров Kubernetes. Подробнее см. в [Kubespray: Обзор](./Kubespray/overview.md).
* **VIP (Virtual IP):** Единый виртуальный IP-адрес, который служит точкой входа для доступа к API-серверам кластера. Подробнее см. в [Виртуальный IP-адрес (VIP)](../../../WebServers/Angie/angie_ha_with_keepalived.md#виртуальный-ip-адрес-vip).
* **Keepalived:** Сервис, который обеспечивает отказоустойчивость VIP, перемещая его между мастер-узлами в случае сбоя активного узла. Подробнее см. в [Keepalived](../../Networking/ServicesAndTools/keepalived_overview.md).
* **HAProxy:** Высокопроизводительный балансировщик нагрузки, который принимает трафик, поступающий на VIP, и распределяет его между всеми доступными экземплярами `kube-apiserver` на мастер-узлах. Подробнее см. в [HAProxy](../../WebServers/Haproxy/haproxy_overview.md).

## Основные концепции

Цель создания HA-кластера — устранить `kube-apiserver` как единую точку отказа. Для этого разворачивается несколько (обычно три) мастер-узлов, на каждом из которых работает свой экземпляр `kube-apiserver`.

Архитектура отказоустойчивости выглядит следующим образом:

1. **Keepalived** запускается на всех мастер-узлах и по протоколу VRRP определяет, какой из них будет "главным" (MASTER) в данный момент. Этот узел получает **VIP**.
2. Если текущий "главный" узел перестает отвечать, Keepalived запускает процесс выборов, и другой узел становится "главным", забирая VIP себе. Это обеспечивает постоянную доступность VIP в сети.
3. **HAProxy** также работает на всех мастер-узлах. Он настроен так, чтобы принимать трафик на VIP (порт 6443) и перенаправлять его на реальные IP-адреса работающих `kube-apiserver` (например, `192.168.1.10:6443`, `192.168.1.11:6443` и т.д.). Это обеспечивает балансировку нагрузки и гарантирует, что запросы не отправляются на неработающий API-сервер.

Таким образом, все компоненты кластера и внешние пользователи обращаются к одному стабильному адресу (VIP), а связка Keepalived + HAProxy прозрачно управляет отказами и распределением нагрузки. Kubespray способен автоматически настраивать эту связку.

## Практические сценарии

### Настройка HA-кластера с нуля

#### 1. Предварительные требования

* **Инфраструктура**: Подготовленные виртуальные или физические машины. В данном примере используется 5 машин:
  * 3 для master-узлов (control plane).
  * 2 для worker-узлов.
* **Сеть**: Все машины должны находиться в одной подсети.
* **Управляющая машина**: Машина, с которой будет запускаться Ansible, с доступом по SSH ко всем узлам кластера.

#### 2. Этап 1: Развертывание базового кластера с Kubespray

1. **Клонируйте репозиторий Kubespray**:

    ```bash
    git clone https://github.com/kubernetes-sigs/kubespray.git
    cd kubespray
    ```

2. **Создайте копию инвентаря**:

    ```bash
    cp -rfp inventory/sample inventory/my-cluster
    ```

3. **Настройте инвентарь `inventory/my-cluster/hosts.ini`**:
    Заполните файл IP-адресами ваших машин.

    ```ini
    [all]
    master-1 ansible_host=192.168.1.10 ip=192.168.1.10
    master-2 ansible_host=192.168.1.11 ip=192.168.1.11
    master-3 ansible_host=192.168.1.12 ip=192.168.1.12
    worker-1 ansible_host=192.168.1.20 ip=192.168.1.20
    worker-2 ansible_host=192.168.1.21 ip=192.168.1.21

    [kube_control_plane]
    master-1
    master-2
    master-3

    [etcd]
    master-1
    master-2
    master-3

    [kube_node]
    worker-1
    worker-2

    [k8s_cluster:children]
    kube_control_plane
    kube_node
    ```

    * `ansible_host`: IP для подключения Ansible.
    * `ip`: Внутренний IP узла.

4. **Установите зависимости Python**:

    ```bash
    pip install -r requirements.txt
    ```

5. **Запустите плейбук Kubespray**:
    Эта команда запустит процесс установки Kubernetes на все узлы.

    ```bash
    ansible-playbook -i inventory/my-cluster/hosts.ini --become --become-user=root cluster.yml
    ```

#### 3. Этап 2: Настройка HA с Keepalived, HAProxy и VIP

Kubespray может автоматически настроить Keepalived и HAProxy для создания виртуального IP (VIP), который будет обеспечивать единую точку доступа к API-серверам на всех master-узлах.

1. **Настройте переменные для VIP в `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`**:

    ```yaml
    # IP-адрес, который будет использоваться как виртуальный
    loadbalancer_apiserver_localhost: false
    kube_apiserver_ip: 192.168.1.100 # Ваш VIP
    ```

2. **Перезапустите плейбук `cluster.yml`** или запустите отдельно плейбук для HAProxy, если базовый кластер уже установлен.

#### 4. Этап 3: Конфигурация компонентов для работы через VIP

1. **Перегенерация сертификатов для VIP**
    Чтобы Kubernetes API-сервер корректно работал с VIP, необходимо, чтобы этот IP-адрес был включен в его TLS-сертификаты. Это нужно сделать на **каждом master-узле**.

    a. **Добавьте VIP в `kubeadm-config.yaml`**:
       Откройте файл `/etc/kubernetes/kubeadm-config.yaml` и в секцию `apiServer.certSANs` добавьте ваш VIP.

       ```yaml
       apiServer:
         certSANs:
         - "192.168.1.100" # Ваш VIP
         - ...
       ```

    b. **Перегенерируйте сертификаты**:

       ```bash
       kubeadm init phase certs all --config /etc/kubernetes/kubeadm-config.yaml
       ```

    c. **Перезапустите `kube-apiserver`**:
       Поды `kube-apiserver` являются статическими. Удалите их, чтобы `kubelet` автоматически их пересоздал с новыми сертификатами.

       ```bash
       # Пример удаления пода на master-1
       kubectl delete pod kube-apiserver-master-1 -n kube-system
       ```

2. **Проверка доступа через VIP и обновление `kubeconfig`**
    * Получите `kubeconfig` с любого master-узла.
    * В файле `kubeconfig` замените IP-адрес `server` на ваш **VIP** и порт HAProxy (по умолчанию `6443`).

    ```yaml
    server: https://192.168.1.100:6443
    ```

    * Проверьте доступ: `kubectl get nodes`.

3. **Настройка `kubelet`**
    На **каждом узле** (master и worker) настройте `kubelet` для связи с API-сервером через VIP.
    * Отредактируйте файл `/etc/kubernetes/kubelet.conf`, заменив IP-адрес `server` на VIP.

        ```yaml
        server: https://192.168.1.100:6443
        ```

    * Перезапустите `kubelet`:

        ```bash
        systemctl restart kubelet
        ```

4. **Настройка `kube-proxy`**
    * Обновите `ConfigMap` для `kube-proxy`, чтобы он также использовал VIP.

        ```bash
        kubectl edit configmap kube-proxy -n kube-system
        ```

    * Найдите поле `server` и замените IP-адрес на VIP.
    * Перезапустите поды `kube-proxy`:

        ```bash
        kubectl delete pod -l k8s-app=kube-proxy -n kube-system
        ```

#### 5. Этап 4: Развертывание дополнительных компонентов (опционально)

После настройки кластера можно развернуть дополнительные сервисы, например, с помощью Helm и Terragrunt.

1. **Установка Metric Server**:
    Metric Server необходим для работы HPA и команды `kubectl top`.

    ```bash
    # Пример развертывания через Terragrunt
    cd infrastructure/prod/metrics-server/
    terragrunt apply
    ```

2. **Развертывание мониторинга**:
    Разверните стек мониторинга ([Prometheus](Kubespray/overview.md), [Grafana](../../Grafana/grafana_overview.md)).

    ```bash
    # Пример развертывания через Terragrunt
    cd infrastructure/prod/monitoring/
    terragrunt apply
    ```

    После развертывания можно получить доступ к Grafana через `port-forward`:

    ```bash
    kubectl port-forward svc/grafana 3000:80 -n monitoring
    ```
