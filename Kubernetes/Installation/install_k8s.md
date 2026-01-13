# Установка отказоустойчивого кластера Kubernetes на Bare-Metal с помощью kubeadm

## Определения

*   **Bare-Metal** — физические серверы, в противоположность виртуальным машинам. Установка на "голое железо" дает максимальную производительность, но требует ручного управления инфраструктурой.
*   **kubeadm** — официальный инструмент от Kubernetes для быстрой инициализации (bootstrapping) кластеров. Он автоматизирует создание control-plane, управление токенами присоединения и другие базовые задачи, но не управляет подготовкой серверов.
*   **containerd** — стандартизированная среда выполнения контейнеров. Это легковесный и эффективный runtime, который управляет жизненным циклом контейнеров на узлах кластера. Является заменой Docker Engine (dockershim), поддержка которого удалена из Kubernetes.
*   **Отказоустойчивый кластер (High-Availability, HA)** — конфигурация кластера, в которой критически важные компоненты (в данном случае, Control Plane) дублируются на нескольких серверах для предотвращения единой точки отказа.

---

## Основные концепции

Для построения отказоустойчивого кластера Kubernetes используется схема со "стекированным" (stacked) Control Plane, где компоненты `etcd` и API-сервера располагаются на одних и тех же мастер-узлах.

Ключевые элементы архитектуры:

1.  **Балансировщик нагрузки (Load Balancer)**: Внешний компонент (например, HAProxy, Nginx или F5), который располагается перед всеми мастер-узлами. Он принимает трафик на единый виртуальный IP-адрес (VIP) и порт `6443` (порт API-сервера Kubernetes) и распределяет его между работоспособными мастерами. Это обеспечивает единую точку входа (`control-plane-endpoint`) для всего кластера.
2.  **Мастер-узлы (Control Plane Nodes)**: Минимум три физических или виртуальных машины. Они инициализируются с указанием на VIP балансировщика. Благодаря этому `kubelet` и другие компоненты всегда "общаются" с балансировщиком, а не с конкретным мастером.
3.  **Рабочие узлы (Worker Nodes)**: Подключаются к кластеру через тот же VIP, что делает их независимыми от IP-адресов конкретных мастеров.

---

## Практический сценарий: Установка кластера

Это пошаговое руководство по развертыванию HA-кластера.

### 1. Требования к среде

#### Аппаратные требования
*   **Мастер-узел (Control Plane):** Минимум 3 узла, 2 CPU, 2 ГБ RAM, 20 ГБ диска на каждом.
*   **Рабочий узел (Worker Node):** Минимум 2 узла, 2 CPU, 4 ГБ RAM, 20 ГБ диска на каждом.
*   **Балансировщик:** 1 узел с установленным HAProxy/Keepalived или аналогичным ПО.

#### Программные требования
*   **ОС:** Ubuntu 22.04 LTS или новее.
*   **Сеть:** Статические IP-адреса для всех узлов. Порты должны быть открыты согласно [официальной документации](https://kubernetes.io/docs/reference/ports-and-protocols/).
*   **Доступ:** SSH-доступ с правами `sudo` на все узлы.

### 2. Подготовка всех узлов (Master и Worker)

Следующие шаги выполняются на **каждом** узле будущего кластера.

#### Обновление системы
```bash
sudo apt-get update && sudo apt-get upgrade -y
```

#### Настройка имен хостов и `/etc/hosts`
Присвойте уникальное имя каждому узлу (`master-1`, `master-2`, `worker-1` и т.д.):
```bash
sudo hostnamectl set-hostname <имя-узла>
```
На каждом узле добавьте в `/etc/hosts` IP-адреса всех участников кластера.
```
# /etc/hosts
<IP-адрес-балансировщика> kubeapi-vip
<IP-адрес-мастера-1> master-1
<IP-адрес-мастера-2> master-2
<IP-адрес-мастера-3> master-3
<IP-адрес-воркера-1> worker-1
...
```
> **NOTE:** Для продуктивных сред рекомендуется использовать внутренний DNS-сервер вместо ручного редактирования `/etc/hosts`.

#### Предварительная проверка и настройка системы

Эти шаги выполняются на **каждом** сервере будущего кластера.

##### 1. Проверка текущего состояния (на ВСЕХ серверах):

Текущее ядро
```bash
uname -r
```

Доступные ядра
```bash
ls /boot/vmlinuz-*
```

Cgroups версия
```bash
stat -fc %T /sys/fs/cgroup
```

Активный SWAP
```bash
swapon --show
```

Загруженные сетевые модули
```bash
lsmod | grep -E "br_netfilter|overlay"
```

Текущие контейнеры
```bash
docker ps --format "table {{.Names}}\t{{.Status}}"
```

##### 2. Обновление системы (по одному серверу):
```bash
sudo apt update
sudo apt upgrade -y
```
Проверка доступных ядер после обновления
```bash
ls /boot/vmlinuz-*  # Должно быть новое ядро (в моем случае это 6.8.0-90)
```
**ВАЖНО: НЕ перезагружаем пока! Сначала выполним все настройки.**

##### 3. Настройка системных параметров:

1. Отключаем SWAP
```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab
echo "SWAP отключен: $(swapon --show | wc -l) активных"
```

2. Настраиваем cgroups v2 в GRUB
```bash
sudo sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub
sudo update-grub
echo "GRUB обновлён: $(grep GRUB_CMDLINE_LINUX /etc/default/grub)"
```

3. Загружаем сетевые модули
```bash
sudo modprobe br_netfilter
sudo modprobe overlay
echo -e "br_netfilter\noverlay" | sudo tee /etc/modules-load.d/k8s.conf
echo "Модули загружены:"
lsmod | grep -E "br_netfilter|overlay"
```

4. Настраиваем sysctl параметры
```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.netfilter.nf_conntrack_max = 262144
EOF

sudo sysctl --system
echo "Проверка параметров:"
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables
```

##### 4. Быстрая проверка готовности
После выполнения всех команд на каждом сервере у вас будет:

1. Система готова к работе с Kubernetes:
SWAP полностью отключен (swapon --show = 0 активных)
Cgroups v2 активирован (stat -fc %T /sys/fs/cgroup = cgroup2fs)
GRUB настроен с параметром systemd.unified_cgroup_hierarchy=1
Сетевые модули загружены (br_netfilter, overlay)
Sysctl параметры установлены (ip_forward=1, bridge-nf-call-iptables=1)

2. Все проверки пройдены:
```bash
echo "1. SWAP: $(swapon --show | wc -l) активных (должно быть 0)"
echo "2. Cgroups: $(stat -fc %T /sys/fs/cgroup) (должно быть cgroup2fs)"
echo "3. Сеть: ip_forward=$(sysctl -n net.ipv4.ip_forward) (должно быть 1)"
echo "4. Модули: br_netfilter=$(lsmod | grep -c br_netfilter), overlay=$(lsmod | grep -c overlay)"
```

##### 5. Что НЕ сделано (и не должно быть сделано сейчас):
* Перезагрузка (выполним позже, после всех настроек)
* Установка Kubernetes компонентов (это следующий этап)
* Изменение работы существующих контейнеров (они работают как и раньше)

### 3. Установка компонентов (на всех узлах)

#### Установка среды выполнения `containerd`
```bash
sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Включаем опцию SystemdCgroup, чтобы kubelet и containerd работали с одним cgroup-драйвером
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl enable containerd
```

#### Установка `kubeadm`, `kubelet`, `kubectl`
```bash
# 1. Определяем версию Kubernetes
# Используем последнюю стабильную версию.
K8S_VERSION="1.35"

# 2. Добавляем официальный GPG-ключ и репозиторий Kubernetes
sudo curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/Release.key" | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# 3. Добавляем репозиторий Kubernetes
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# 4. Устанавливаем компоненты
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# 5. Фиксируем версии, чтобы избежать случайных обновлений при системном apt upgrade
sudo apt-mark hold kubelet kubeadm kubectl
```

### 4. Настройка Control Plane

#### Инициализация первого мастер-узла
На **первом** мастере выполните:
```bash
# Замените LOAD_BALANCER_IP на VIP вашего балансировщика
# --pod-network-cidr требуется для многих CNI, например, Calico
sudo kubeadm init \
  --control-plane-endpoint "LOAD_BALANCER_IP:6443" \
  --pod-network-cidr=192.168.0.0/16 \
  --upload-certs
```
*   `--control-plane-endpoint`: Общая точка входа для всех мастеров (VIP).
*   `--upload-certs`: Загружает сертификаты в кластер, чтобы их могли скачать другие мастера.
*   `--pod-network-cidr`: Диапазон IP-адресов для подов. Убедитесь, что он не пересекается с другими сетями.

После успешной инициализации `kubeadm` выведет две команды `join`: одну для других мастеров, вторую для рабочих узлов. **Сохраните их.**

#### Настройка `kubectl`
Чтобы управлять кластером с мастер-узла:
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

#### Присоединение остальных мастер-узлов
На **втором и третьем** мастер-узлах выполните команду `kubeadm join` для мастеров, полученную ранее.

#### Присоединение рабочих узлов
На **каждом** рабочем узле выполните команду `kubeadm join` для воркеров.

### 5. Установка сетевого плагина (CNI)

Этот шаг выполняется **один раз** с любого мастер-узла после инициализации кластера. В качестве примера используем **Calico**.

```bash
# URL может меняться. Проверяйте совместимость Calico и Kubernetes в официальной документации.
# https://docs.projectcalico.org/getting-started/kubernetes/self-managed-on-premises/on-premises
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.31.0/manifests/calico.yaml
```

Проверьте, что все системные поды и узлы перешли в состояние `Running` и `Ready`:
```bash
kubectl get pods -n kube-system
kubectl get nodes
```

### 6. Проверка работоспособности кластера
Развернем тестовое приложение Nginx.

1.  **Создайте манифест `nginx-test.yaml`:**
    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx-deployment
      labels:
        app: nginx
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: nginx
      template:
        metadata:
          labels:
            app: nginx
        spec:
          containers:
          - name: nginx
            image: nginx:latest
            ports:
            - containerPort: 80
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-service
    spec:
      type: NodePort
      selector:
        app: nginx
      ports:
        - protocol: TCP
          port: 80
          targetPort: 80
    ```

2.  **Примените манифест и проверьте сервис:**
    ```bash
    kubectl apply -f nginx-test.yaml
    kubectl get service nginx-service
    ```
    Узнайте `NodePort` (порт вида `3xxxx`) и проверьте доступ по адресу `http://<IP-любого-воркера>:<NodePort>`.

---

## Дополнительная информация

### Kubeadm vs. Kubespray

Хотя `kubeadm` является официальным инструментом для инициализации кластера, он требует значительного количества ручных операций. Для полной автоматизации развертывания production-ready кластеров часто используют **Kubespray**.

*   **Kubeadm**:
    *   **Плюсы**: Официальный, гибкий, дает глубокое понимание процесса установки.
    *   **Минусы**: Требует ручной настройки узлов, сети и компонентов. Автоматизация ложится на плечи инженера.

*   **[Kubespray](./kubespray.md)**:
    *   **Плюсы**: Полностью автоматизирует развертывание с помощью Ansible. Поддерживает большое количество конфигураций.
    *   **Минусы**: Более высокий уровень абстракции усложняет отладку. Может быть медленным из-за большого количества Ansible-ролей.