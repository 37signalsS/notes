# Руководство по установке Kubernetes через kubeadm

## Определения

**kubeadm** — официальная утилита для быстрой установки и управления жизненным циклом кластера Kubernetes (инициализация, обновление, управление сертификатами).

**CRI (Container Runtime Interface)** — стандартный интерфейс для взаимодействия `kubelet` со средой выполнения контейнеров.

**containerd** — промышленная среда выполнения контейнеров, поддерживающая стандарт CRI. Рекомендуемый Runtime для Kubernetes.

**cgroup driver** — механизм управления ресурсами (CPU, Memory) в Linux. Для Kubernetes критично совпадение драйвера между `kubelet` и Runtime (рекомендуется `systemd`).

---

## Основные концепции

### Этапы развёртывания кластера

Процесс установки разделён на два основных этапа:
1. **Подготовка инфраструктуры** (этот документ): настройка ОС, загрузка модулей ядра, установка Container Runtime и пакетов Kubernetes.
2. **Инициализация и масштабирование** (см. **[Инициализацию кластера](./cluster_initialization.md)**): создание Control Plane, установка сетевого плагина и добавление рабочих узлов.

### Архитектура узла после установки

На каждом узле после завершения подготовки работают следующие компоненты:
- **containerd**: низкоуровневая среда управления контейнерами.
- **kubelet**: основной агент Kubernetes, отвечающий за запуск подов.
- **kubeadm**: инструмент для выполнения административных операций и обновлений.

---

## Практические сценарии

### Шаг 1: Подготовка операционной системы

#### Системные требования

| Ресурс | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **RAM** | 2 ГБ | 4+ ГБ | Минимум 4 ГБ для узлов Control Plane |
| **CPU** | 2 ядра | 4+ ядра | API-сервер чувствителен к количеству ядер |
| **Диск** | 20 ГБ | 50+ ГБ | Зависит от интенсивности логирования и образов |

#### Сетевые настройки и безопасность

- **Hostname**: должен быть уникальным для каждого узла.
- **Swap**: должен быть полностью отключен (иначе `kubelet` не запустится):
```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
```
- **Порты**: убедитесь, что трафик разрешен (особенно порт 6443 для API и порты CNI, например 179/UDP для Calico).

### Шаг 2: Настройка ядра Linux и сетевого моста

Необходимо разрешить прохождение трафика через мосты для корректной работы сетевых плагинов:

```bash
# Загрузка необходимых модулей ядра
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter

# Настройка параметров sysctl для сети
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sudo sysctl --system
```

### Шаг 3: Установка и настройка containerd

```bash
sudo apt-get update && sudo apt-get install -y containerd

# Генерация конфигурации по умолчанию
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml

# Включение systemd cgroup driver (обязательно для стабильности)
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

sudo systemctl restart containerd
sudo systemctl enable containerd
```

#### Настройка crictl (проактивная диагностика)
Настройте утилиту `crictl`, чтобы она знала, к какому сокету подключаться для управления контейнерами:

```bash
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 2
debug: false
EOF
```

### Шаг 4: Установка пакетов Kubernetes (v1.36)

```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg

# Добавление официального репозитория
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

---

## Дополнительная информация

### Сценарии развёртывания

| Сценарий | Описание |
| :--- | :--- |
| **Single-node** | Все компоненты на одном узле. Снимите taint: `kubectl taint nodes --all node-role.kubernetes.io/control-plane-` |
| **Multi-node** | Разделение на Control Plane и Worker узлы. Классическая схема. |
| **High Availability** | Использование нескольких мастеров и балансировщика (Keepalived/HAProxy). |

### Диагностика установки

Если после установки `kubelet` не переходит в статус active:
1. Проверьте логи: `journalctl -u kubelet -f`.
2. Убедитесь, что Docker не установлен параллельно (конфликт сокетов).
3. Проверьте статус рантайма: `crictl info`.

### См. также

- **[Инициализация кластера](./cluster_initialization.md)** — следующий этап: запуск `kubeadm init`.
- **[Настройка High Availability](./ha_concepts.md)** — подготовка балансировщика для отказоустойчивости.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — продление сертификатов после установки.
