# Развертывание HA-кластера Kubernetes с Kubespray, Keepalived и HAProxy

В данном руководстве описывается процесс развертывания высокодоступного (HA) кластера Kubernetes с использованием Kubespray (Ansible), с настройкой виртуального IP (VIP) через Keepalived и HAProxy для обеспечения отказоустойчивости API-сервера.

## 1. Предварительные требования

*   **Инфраструктура**: Подготовленные виртуальные или физические машины. В данном примере используется 5 машин:
    *   3 для master-узлов (control plane).
    *   2 для worker-узлов.
*   **Сеть**: Все машины должны находиться в одной подсети. Настроенный VPN или другая форма внутренней сети для доступа к машинам.
*   **Управляющая машина**: Машина, с которой будет запускаться Ansible, с доступом по SSH ко всем узлам кластера.

## 2. Этап 1: Развертывание базового кластера с Kubespray

### 2.1. Подготовка Kubespray

1.  **Клонируйте репозиторий Kubespray**:
    ```bash
    git clone https://github.com/kubernetes-sigs/kubespray.git
    cd kubespray
    ```

2.  **Создайте копию инвентаря**:
    ```bash
    cp -rfp inventory/sample inventory/my-cluster
    ```

3.  **Настройте инвентарь `inventory/my-cluster/hosts.ini`**:
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

    [calico_rr]

    [k8s_cluster:children]
    kube_control_plane
    kube_node
    calico_rr
    ```
    *   `ansible_host`: Публичный IP для подключения Ansible (если применимо).
    *   `ip`: Внутренний IP узла.

### 2.2. Установка зависимостей и запуск плейбука

1.  **Установите зависимости Python**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Запустите плейбук Kubespray**:
    Эта команда запустит процесс установки Kubernetes на все узлы. Процесс может занять 15-20 минут.

    ```bash
    ansible-playbook -i inventory/my-cluster/hosts.ini --become --become-user=root cluster.yml
    ```
    *   Вам может потребоваться указать пользователя для подключения (`--user`) и пароль (`--ask-pass`).

## 3. Этап 2: Настройка HA с Keepalived, HAProxy и VIP

### 3.1. Настройка Keepalived и HAProxy

Kubespray может автоматически настроить Keepalived и HAProxy для создания виртуального IP (VIP), который будет обеспечивать единую точку доступа к API-серверам на всех master-узлах.

1.  **Настройте переменные для VIP в `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`**:
    ```yaml
    # IP-адрес, который будет использоваться как виртуальный
    loadbalancer_apiserver_localhost: false
    kube_apiserver_ip: 192.168.1.100 # Ваш VIP
    ```
2.  **Добавьте `ha-proxy.yml` в ваш `cluster.yml` или запустите отдельно**:
    Можно запустить плейбук для HAProxy отдельно, если базовый кластер уже установлен.

### 3.2. Получение `kubeconfig`

После установки кластера получите `kubeconfig` с одного из master-узлов для дальнейшей работы.

```bash
ssh user@master-1
cat /root/.kube/config
```
Скопируйте содержимое и сохраните на своей локальной машине. Измените IP-адрес сервера на IP `master-1`, чтобы проверить прямой доступ.

### 3.3. Перегенерация сертификатов для VIP

Чтобы Kubernetes API-сервер корректно работал с VIP, необходимо, чтобы этот IP-адрес был включен в его TLS-сертификаты.

**Выполните эти действия на каждом master-узле:**

1.  **Сделайте резервную копию сертификатов**:
    ```bash
    mkdir /etc/kubernetes/pki.bak
    mv /etc/kubernetes/pki/* /etc/kubernetes/pki.bak/
    ```

2.  **Добавьте VIP в `kubeadm-config.yaml`**:
    Откройте файл `/etc/kubernetes/kubeadm-config.yaml` и в секцию `apiServer.certSANs` добавьте ваш VIP.
    ```yaml
    apiServer:
      certSANs:
      - "192.168.1.100" # Ваш VIP
      - ...
    ```

3.  **Перегенерируйте сертификаты**:
    ```bash
    kubeadm init phase certs all --config /etc/kubernetes/kubeadm-config.yaml
    ```

4.  **Перезапустите `kube-apiserver`**:
    Поды `kube-apiserver` являются статическими и управляются `kubelet`. Удалите их, чтобы `kubelet` автоматически их пересоздал с новыми сертификатами.

    ```bash
    # Найти и удалить под kube-apiserver
    crictl ps -a | grep kube-apiserver
    crictl rm <container-id>
    # Или просто удалите под через kubectl, если уже есть доступ
    kubectl delete pod kube-apiserver-master-1 -n kube-system
    ```

### 3.4. Проверка доступа через VIP

Обновите ваш локальный `kubeconfig`:
*   Замените IP-адрес `server` на ваш **VIP** (`192.168.1.100`).
*   Измените порт на порт HAProxy (по умолчанию `6443`).

```yaml
server: https://192.168.1.100:6443
```
Теперь команда `kubectl get nodes` должна успешно выполняться, показывая, что доступ через VIP работает.

## 4. Этап 3: Конфигурация компонентов кластера

### 4.1. Настройка `kubelet`

Настройте `kubelet` на **каждом узле** (master и worker) для связи с API-сервером через VIP.

1.  **Отредактируйте файл `/etc/kubernetes/kubelet.conf`**:
    Замените IP-адрес `server` на VIP с портом.
    ```yaml
    server: https://192.168.1.100:6443
    ```
2.  **Перезапустите `kubelet`**:
    ```bash
    systemctl restart kubelet
    ```

### 4.2. Настройка `kube-proxy`

Обновите `ConfigMap` для `kube-proxy`, чтобы он также использовал VIP.

```bash
kubectl edit configmap kube-proxy -n kube-system
```
Найдите поле `server` и замените IP-адрес на VIP. После сохранения `ConfigMap` перезапустите поды `kube-proxy`:
```bash
kubectl delete pod -l k8s-app=kube-proxy -n kube-system
```

## 5. Этап 4: Развертывание окружения (Helm + Terragrunt)

### 5.1. Установка Metric Server

Metric Server необходим для работы Horizontal Pod Autoscaler (HPA) и для команд типа `kubectl top`.

1.  **Создайте `terragrunt.hcl` для Metric Server**:
    Настройте `terragrunt`, чтобы он использовал Helm-чарт `metrics-server`.

2.  **Разверните Metric Server**:
    ```bash
    cd infrastructure/prod/metrics-server/
    terragrunt apply
    ```

### 5.2. Развертывание мониторинга

Разверните базовый стек мониторинга (Prometheus, Grafana).

1.  **Создайте `terragrunt.hcl` для стека мониторинга**.

2.  **Разверните стек**:
    ```bash
    cd infrastructure/prod/monitoring/
    terragrunt apply
    ```

### 5.3. Проверка

После развертывания проверьте, что все поды запущены, и получите доступ к Grafana через `port-forward`.

```bash
kubectl port-forward svc/grafana 3000:80 -n monitoring
```
Откройте `http://localhost:3000` в браузере.

## 6. Дальнейшие шаги

После развертывания базового HA-контура можно приступить к настройке более сложных компонентов:
*   **Observability**: Настроить логирование (Loki) и трейсинг (Tempo/Jaeger).
*   **GitOps**: Внедрить ArgoCD или FluxCD для декларативного управления приложениями.
*   **Storage**: Настроить CSI-драйвер для постоянного хранения (Ceph, Linstor и т.д.).
*   **Autoscaling**: Настроить Cluster Autoscaler для автоматического масштабирования узлов.
*   **Identity & Access Management**: Интегрировать с Keycloak или другим IdP.
*   **Security**: Установить Kyverno или OPA Gatekeeper для управления политиками безопасности.
