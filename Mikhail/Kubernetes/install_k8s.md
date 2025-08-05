# Установка отказоустойчивого кластера Kubernetes на Bare-Metal с помощью kubeadm

Это руководство представляет собой пошаговую инструкцию по развертыванию отказоустойчивого (High-Availability) кластера Kubernetes на физических серверах ("bare-metal"). Мы будем использовать `kubeadm` для инициализации кластера и `containerd` в качестве среды выполнения контейнеров.

---

## 1. Требования к окружению

### 1.1. Аппаратные требования

*   **Мастер-узел (Control Plane):** Минимум 2 CPU, 2 ГБ RAM, 20 ГБ диска.
*   **Рабочий узел (Worker Node):** Минимум 2 CPU, 4 ГБ RAM, 20 ГБ диска.

### 1.2. Программные требования

*   **ОС:** Ubuntu 22.04 LTS или новее / CentOS 9 Stream на всех узлах.
*   **Сеть:** Статические IP-адреса для всех узлов и открытые порты (см. [документацию Kubernetes](https://kubernetes.io/docs/reference/ports-and-protocols/)).
*   **Доступ:** SSH-доступ с правами `sudo` на все узлы.

---

## 2. Подготовка всех узлов

Следующие шаги необходимо выполнить на **каждом** узле кластера (мастер- и рабочих).

### 2.1. Обновление системы

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

### 2.2. Настройка имен хостов и сети

Присвойте уникальное имя каждому узлу:
```bash
sudo hostnamectl set-hostname <имя-узла>
```

Добавьте IP-адреса и имена всех узлов в файл `/etc/hosts` на каждом узле.
```
# /etc/hosts
<IP-адрес-мастера-1> master-1
<IP-адрес-мастера-2> master-2
<IP-адрес-балансировщика> kubeapi-vip
<IP-адрес-воркера-1> worker-1
```
> **NOTE:** Для продуктивных сред рекомендуется использовать внутренний DNS-сервер вместо ручного редактирования `/etc/hosts` для большей надежности и управляемости.

### 2.3. Отключение Swap

Kubernetes требует, чтобы swap был отключен для стабильной работы.
```bash
# Отключаем swap немедленно
sudo swapoff -a
# Убираем swap из fstab, чтобы он не включился после перезагрузки
sudo sed -i '/ swap / s/^/#/' /etc/fstab
```

### 2.4. Настройка модулей ядра и sysctl

Эти параметры необходимы для корректной работы сети в Kubernetes.
```bash
# Включаем модуль br_netfilter для корректной работы сетевых мостов
sudo modprobe br_netfilter

# Добавляем его в автозагрузку
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
br_netfilter
EOF

# Настраиваем параметры sysctl для сети
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward                 = 1
EOF

# Применяем параметры без перезагрузки
sudo sysctl --system
```

---

## 3. Установка компонентов

Эти шаги также выполняются на **каждом** узле.

### 3.1. Установка среды выполнения контейнеров (containerd)

```bash
# Устанавливаем containerd
sudo apt-get install -y containerd

# Создаем конфигурационный файл по умолчанию
sudo mkdir -p /etc/containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Включаем опцию SystemdCgroup, чтобы kubelet и containerd работали с одним cgroup-драйвером
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Перезапускаем и включаем containerd для применения изменений
sudo systemctl restart containerd
sudo systemctl enable containerd
```

### 3.2. Установка инструментов Kubernetes (kubeadm, kubelet, kubectl)

```bash
# 1. Определите актуальную версию Kubernetes, например, на странице релизов:
# https://github.com/kubernetes/kubernetes/releases
K8S_VERSION="1.30" # Замените на нужную минорную версию (например, 1.29, 1.30)

# 2. Добавляем официальный GPG-ключ Kubernetes
sudo curl -fsSL "https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/Release.key" | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# 3. Добавляем репозиторий Kubernetes
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${K8S_VERSION}/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# 4. Устанавливаем компоненты
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# 5. Фиксируем версии, чтобы избежать случайных обновлений при системном apt upgrade
sudo apt-mark hold kubelet kubeadm kubectl
```

---

## 4. Настройка отказоустойчивого Control Plane (HA)

Для продуктивных сред необходимо использовать кластер с несколькими мастер-узлами.

### 4.1. Схема работы

1.  **Балансировщик нагрузки (Load Balancer):** Настраивается перед мастер-узлами. Он принимает трафик на виртуальный IP-адрес (VIP) и порт `6443` и направляет его на один из работоспособных мастер-узлов. В качестве балансировщика можно использовать **HAProxy**, **Nginx** или **keepalived**.
2.  **Мастер-узлы:** Инициализируются с указанием на VIP балансировщика.
3.  **Рабочие узлы:** Подключаются к кластеру через VIP, а не через IP конкретного мастера.

### 4.2. Инициализация первого мастер-узла

На **первом** мастер-узле выполните:
```bash
# Замените LOAD_BALANCER_IP на VIP вашего балансировщика
# --pod-network-cidr требуется для многих CNI, например, Calico
sudo kubeadm init \
  --control-plane-endpoint "LOAD_BALANCER_IP:6443" \
  --pod-network-cidr=192.168.0.0/16 \
  --upload-certs
```
*   `--control-plane-endpoint`: Общая точка входа для всех мастеров.
*   `--upload-certs`: Загружает сертификаты в кластер, чтобы их могли скачать другие мастера.
*   `--pod-network-cidr`: Диапазон IP-адресов для подов. Убедитесь, что он не пересекается с другими сетями.

После успешной инициализации `kubeadm` выведет две команды `join`: одну для других мастеров, вторую для рабочих узлов. **Сохраните их.**

### 4.3. Настройка `kubectl`

Чтобы управлять кластером с мастер-узла:
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

### 4.4. Добавление остальных мастер-узлов

На **остальных** мастер-узлах выполните команду `kubeadm join`, которую вы получили на шаге 4.2 (команда для мастеров).

### 4.5. Добавление рабочих узлов

На **каждом** рабочем узле выполните команду `kubeadm join` для рабочих узлов.

---

## 5. Установка сетевого плагина (CNI)

Кластер не будет полностью функционален до установки сетевого плагина. Этот шаг выполняется **один раз** с любого мастер-узла.

В качестве примера используем **Calico**.
> **Важно:** Версии Calico и Kubernetes должны быть совместимы. Всегда сверяйтесь с [официальной документацией Calico](https://docs.projectcalico.org/getting-started/kubernetes/self-managed-on-premises/on-premises) для получения актуальной команды установки.

```bash
# Команда для установки Calico. URL может меняться, проверяйте документацию.
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/calico.yaml
```

После установки плагина проверьте состояние всех подов в `kube-system`:
```bash
kubectl get pods -n kube-system
```
Все поды должны перейти в состояние `Running`.

Проверьте состояние узлов:
```bash
kubectl get nodes
```
Все узлы должны быть в состоянии `Ready`.

---

## 6. Развертывание тестового приложения

Для проверки работоспособности кластера развернем Nginx, используя декларативный подход.

1.  **Создайте файл `nginx-test.yaml`:**
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
            image: nginx:1.25.4
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

2.  **Примените манифест:**
    ```bash
    kubectl apply -f nginx-test.yaml
    ```

3.  **Узнайте выделенный порт:**
    ```bash
    kubectl get service nginx-service
    ```
    В выводе вы увидите порт, например `3xxxx`, в строке `80:3xxxx/TCP`.

4.  **Проверьте доступ:**
    Откройте в браузере `http://<IP-адрес-любого-воркера>:<NodePort>`. Вы должны увидеть страницу приветствия Nginx.