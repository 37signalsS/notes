# Руководство по подготовке узлов для установки Kubernetes через kubeadm

## Определения

**kubeadm** — официальная утилита для быстрой установки и управления жизненным циклом кластера Kubernetes (инициализация, обновление, управление сертификатами).

**CRI (Container Runtime Interface)** — стандарт интерфейса для взаимодействия `kubelet` со средой выполнения контейнеров.

**containerd** — промышленная среда выполнения контейнеров, поддерживающая стандарт CRI. Рекомендуемый Runtime для Kubernetes.

**cgroup v2 (Control Groups version 2)** — современная подсистема ядра Linux для управления ресурсами. Обязательна для стабильной работы Kubernetes 1.30+ на современных ядрах.

**nftables** — современная подсистема фильтрации пакетов в ядре Linux, заменяющая устаревший `iptables`. Рекомендуемый бэкенд для `kube-proxy` с версии v1.31.

---

## Основные концепции

### Этапы развёртывания инфраструктуры

Процесс подготовки разделен на логические этапы, которые должны быть выполнены на всех узлах (Control Plane и Worker):

1.  **Подготовка ОС**: Системные требования, уникальность имен, отключение swap.
2.  **Настройка ядра**: Загрузка модулей (`overlay`, `br_netfilter`) и активация `ip_forward`.
3.  **Конфигурация cgroups**: Установка cgroup v2 и настройка `SystemdCgroup` в рантайме.
4.  **Сетевой экран**: Открытие портов и настройка nftables.
5.  **Установка Runtime**: Установка и настройка `containerd`.
6.  **Установка компонентов Kubernetes**: Пакеты `kubeadm`, `kubelet` и `kubectl`.

### Совместимость и версии (2026)

| Компонент | Рекомендуемая версия | Поддерживаемые ОС |
| :--- | :--- | :--- |
| **Kubernetes** | v1.36.x | Ubuntu 22.04+, RHEL 9+, Debian 12+ |
| **containerd** | v2.0+ | Все вышеперечисленные |
| **Linux Kernel** | 5.15+ (рекомендуется 6.x) | Необходима поддержка cgroup v2 |

---

## Практические сценарии

### Шаг 1: Системные требования и ОС

#### Требования к ресурсам

- **Control Plane**: минимум 2 CPU, 4 ГБ RAM.
- **Worker**: минимум 1 CPU, 2 ГБ RAM (рекомендуется 4 ГБ+ для реальных нагрузок).

#### Первичная настройка (Все узлы)

```bash
# 1. Отключение SWAP (Обязательно)
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# 2. Уникальность Machine ID (важно для логов и сетевых плагинов)
cat /etc/machine-id
```

### Шаг 2: Настройка ядра и сети

```bash
# Загрузка модулей при загрузке
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter

# Параметры sysctl
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sudo sysctl --system
```

### Шаг 3: Установка и настройка containerd

#### Для Ubuntu/Debian:
```bash
sudo apt-get update && sudo apt-get install -y containerd
```

#### Для RHEL/Rocky Linux 9:
```bash
sudo dnf install -y containerd.io
```

#### Настройка cgroup v2 (SystemdCgroup)
Это критически важный шаг для стабильности.

```bash
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml

# Включение SystemdCgroup
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

sudo systemctl restart containerd
sudo systemctl enable containerd
```

### Шаг 4: Настройка сетевого экрана (Порты)

#### Control Plane узлы
| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 6443 | TCP | Kubernetes API Server |
| 2379-2380 | TCP | etcd server client API |
| 10250 | TCP | Kubelet API |
| 10259 | TCP | kube-scheduler |
| 10257 | TCP | kube-controller-manager |

#### Worker узлы
| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 10250 | TCP | Kubelet API |
| 30000-32767 | TCP | NodePort Services |

**Пример для Firewalld (RHEL/Rocky):**
```bash
sudo firewall-cmd --permanent --add-port=6443/tcp
sudo firewall-cmd --permanent --add-port=2379-2380/tcp
sudo firewall-cmd --reload
```

### Шаг 5: Установка пакетов Kubernetes (v1.36)

#### Для Ubuntu/Debian:
```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

#### Для RHEL/Rocky Linux 9:
```bash
cat <<EOF | sudo tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/repodata/repomd.xml.key
EOF

sudo dnf install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
sudo systemctl enable --now kubelet
```

---

## Дополнительная информация

### Диагностика перед инициализацией

Перед запуском `kubeadm init` убедитесь, что:
1.  **Cgroup v2 активен**: `stat -fc %T /sys/fs/cgroup` (должно быть `cgroup2fs`).
2.  **Рантайм доступен**: `sudo crictl info`.
3.  **Имена хостов уникальны**: `hostnamectl status`.

### Проактивная настройка crictl

```bash
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF
```

### См. также

- **[Инициализация кластера](./cluster_initialization.md)** — следующий этап: запуск первого мастера.
- **[Настройка High Availability](./ha_concepts.md)** — подготовка балансировщиков.
- **[Troubleshooting узлов](../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)** — глубокая диагностика.
