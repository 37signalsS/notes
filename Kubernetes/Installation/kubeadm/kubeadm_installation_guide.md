# Руководство по установке Kubernetes через kubeadm

> **Надежность: 10** (Подтверждено SSoT по развёртыванию Kubernetes и актуальными данными на июнь 2026)

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

- **containerd**: управляет контейнерами.
- **kubelet**: агент Kubernetes, взаимодействующий с CRI.
- **kubeadm**: утилита для выполнения административных операций.

---

## Практические сценарии

### Шаг 1: Подготовка операционной системы

#### Системные требования

| Ресурс | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **RAM** | 2 ГБ | 4+ ГБ | Для Control Plane — от 4 ГБ |
| **CPU** | 2 ядра | 4+ ядра | Минимум 2 ядра для Control Plane |
| **Диск** | 20 ГБ | 50+ ГБ | Зависит от объёма логов и образов |

#### Сетевые настройки и Firewall

- Уникальные hostname для всех узлов.
- Отключение swap (критично для стабильности `kubelet`):

```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
```

- Открытие портов (если используется Firewall):
  - **Control Plane**: 6443, 2379-2380, 10250, 10259, 10257.
  - **Worker Nodes**: 10250, 30000-32767.

### Шаг 2: Настройка ядра Linux

Необходимо загрузить модули для работы сетевого моста и включить форвардинг трафика:

```bash
# Загрузка модулей
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter

# Настройка параметров sysctl
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

# Настройка systemd cgroup driver (критично!)
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

sudo systemctl restart containerd
sudo systemctl enable containerd
```

### Шаг 4: Установка пакетов Kubernetes

```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg

# Добавление репозитория (на примере v1.35)
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.35/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.35/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

### Дальнейшие шаги

После завершения установки пакетов на всех узлах необходимо перейти к инициализации кластера:

1. **[Инициализация первого мастера](./cluster_initialization.md#инициализация-первого-мастера-ha-подготовка)**.
2. **Установка CNI-плагина**.
3. **Присоединение рабочих узлов**.

---

## Дополнительная информация

### Сценарии развёртывания

| Сценарий | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Single-node** | Один узел для Control Plane и рабочих нагрузок | Разработка, обучение, легкие тесты |
| **Standard** | Один мастер-узел и несколько рабочих узлов | Небольшие проекты, некритичные среды |
| **High Availability** | 3+ мастера с балансировщиком и воркеры | Продуктовые среды, критичные сервисы |

### Проверка работоспособности

После инициализации кластера выполните проверку базовых функций:

```bash
# Проверка статуса узлов
kubectl get nodes

# Тестовый запуск приложения
kubectl run nginx --image=nginx
kubectl get pods -o wide
```

### Диагностика установки

Если компоненты не запускаются:

- Проверьте статус `containerd`: `systemctl status containerd`.
- Проверьте логи `kubelet`: `journalctl -u kubelet -f`.
- Убедитесь, что `SystemdCgroup = true` в `/etc/containerd/config.toml`.

### См. также

- **[Инициализация кластера](./cluster_initialization.md)** — подробные инструкции по созданию и масштабированию кластера.
- **[Настройка High Availability](./ha_concepts.md)** — подготовка балансировщика для отказоустойчивых сред.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — проверка и продление сертификатов через `kubeadm`.
