# Создание кластера с kubeadm

## 1. Определения

| Термин | Описание |
| :--- | :--- |
| **Control Plane** | Управляющая плоскость Kubernetes (API Server, etcd, Controller Manager, Scheduler). |
| **Worker Node** | Узел кластера, на котором запускаются пользовательские поды. |
| **CNI (Container Network Interface)** | Сетевой плагин для обеспечения коммуникации между подами. |
| **Pod Network CIDR** | Диапазон IP-адресов, выделяемых для подов в кластере. |

## 2. Основные концепции

### 2.1. Требования к узлам

| Требование | Описание |
| :--- | :--- |
| **ОС** | Ubuntu 20.04+, Debian 11+, CentOS 9+, Rocky Linux 9+ |
| **CPU** | Минимум 2 ядра (рекомендуется 4+) |
| **RAM** | Минимум 2 ГБ (рекомендуется 4+ ГБ) |
| **Сеть** | Уникальный hostname, статический IP, доступ между узлами |
| **Виртуализация** | Включена (для container runtime) |

### 2.2. Поддерживаемые версии

| Компонент | Версия |
| :--- | :--- |
| **Kubernetes** | 1.33 (stable) |
| **containerd** | 1.7+ |
| **CNI плагины** | Calico 3.28+, Cilium 1.16+, Flannel 0.25+ |

> **Примечание:** `kubeadm` поддерживает установку последних 3 версий Kubernetes. Актуальная информация: [kubernetes.io/releases](https://kubernetes.io/releases/).

## 3. Практические сценарии

### 3.1. Сценарий: Создание одно-мастерного кластера

#### Шаг 1: Подготовка всех узлов (Master и Workers)

**1.1. Отключение swap**

Kubernetes требует отключения swap для корректной работы планировщика.

```bash
# Временно отключить до перезагрузки
sudo swapoff -a

# Постоянно отключить (закомментировать строку swap в /etc/fstab)
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
```

**1.2. Настройка сетевых параметров**

```bash
# Включить маршрутизацию для трафика pod-to-pod
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes-cri.conf
net.bridge.bridge-nf-call-iptables  = 1
net.ipv4.ip_forward                 = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF

# Применить настройки
sudo sysctl --system
```

**1.3. Установка container runtime (containerd)**

> **Важно:** Docker deprecated как CRI. Рекомендуется использовать containerd напрямую.

```bash
# Установка containerd
sudo apt-get update
sudo apt-get install -y containerd

# Создание конфигурации
sudo mkdir -p /etc/containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Включить systemd cgroup driver (требуется для K8s)
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Перезапуск containerd
sudo systemctl restart containerd
sudo systemctl enable containerd
```

**1.4. Установка Kubernetes (`kubeadm`, `kubelet`, `kubectl`)**

```bash
# Добавление репозитория Kubernetes
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.33/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.33/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Установка
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# Закрепление версий
sudo apt-mark hold kubelet kubeadm kubectl

# Включение kubelet (запустится после инициализации)
sudo systemctl enable --now kubelet
```

#### Шаг 2: Инициализация Master-узла

**2.1. Запуск инициализации**

```bash
# Для Calico (рекомендуется)
sudo kubeadm init --pod-network-cidr=192.168.0.0/16

# Для Flannel
# sudo kubeadm init --pod-network-cidr=10.244.0.0/16
```

**2.2. Настройка доступа к кластеру**

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

**2.3. Сохранение команды join**

```bash
# kubeadm выведет команду вида:
# kubeadm join <ip>:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>
# Сохраните её для присоединения worker-узлов
```

#### Шаг 3: Установка сетевого плагина (CNI)

> **Важно:** Узлы не перейдут в `Ready` до установки CNI.

**Calico (рекомендуется для production):**

```bash
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/tigera-operator.yaml
kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.28.0/manifests/custom-resources.yaml
```

**Flannel (для dev/test):**

```bash
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```

**Проверка:**

```bash
kubectl get nodes
kubectl get pods -n kube-system
```

#### Шаг 4: Присоединение Worker-узлов

На **каждой worker-ноде** выполните команду `kubeadm join`:

```bash
sudo kubeadm join <ip-мастера>:6443 --token <токен> --discovery-token-ca-cert-hash sha256:<хэш>
```

**Проверка на master:**

```bash
kubectl get nodes
# Статус должен быть Ready через 1-2 минуты
```

### 3.2. Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| **Узел не Ready** | Проверить CNI: `kubectl get pods -n kube-system` |
| **containerd не запускается** | Проверить конфиг: `containerd config test` |
| **kubelet падает** | Логи: `journalctl -u kubelet -f` |
| **Pod не запускается** | `kubectl describe pod <pod-name>`, `kubectl logs <pod-name>` |
| **Сеть не работает** | Проверить `sysctl net.bridge.bridge-nf-call-iptables` |
| **Токен истёк** | Создать новый: `kubeadm token create --print-join-command` |

## 4. Дополнительная информация

### 4.1. Связанные темы

*   [Управление узлами кластера](./kubeadm_node_management.md)
*   [HA кластер с Keepalived + HAProxy](./kubeadm_ha_with_keepalived_haproxy.md)
*   [CNI плагины — сравнение](../../Networking/Network/cni_overview.md)
*   [Container runtime](../../Concepts/container_runtime.md)
*   [kind](../kind_quickstart.md) — альтернатива для локальной разработки
*   [Talos](../local_cluster_with_talosctl.md) — безопасная ОС для K8s

### 4.2. Следующие шаги

1.  **Проверка кластера:** `kubectl get nodes`, `kubectl get pods -A`
2.  **Установка метрик:** [metrics-server](../../MonitoringLogging/metrics-server.md)
3.  **Настройка storage:** [CSI драйверы](../../Storage/CSI/csi_overview.md)
4.  **Мониторинг:** [Prometheus + Grafana](../../MonitoringLogging/prometheus_overview.md)
