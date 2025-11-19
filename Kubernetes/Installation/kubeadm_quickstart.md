# Быстрый старт с kubeadm

Это руководство описывает базовые шаги по созданию простого кластера Kubernetes на нескольких виртуальных или физических машинах с ОС на базе Debian/Ubuntu с помощью утилиты `kubeadm`.

## Концепция

`kubeadm` — это официальный инструмент для быстрой инициализации (bootstrapping) кластеров Kubernetes. Он берет на себя основные задачи: создание control-plane, управление токенами для присоединения узлов и т.д. Однако он не управляет подготовкой инфраструктуры (машины, сеть) и установкой зависимостей.

> **Примечание:** Для развертывания отказоустойчивого (High-Availability) кластера Kubernetes с помощью `kubeadm` см. подробное руководство в [Установка отказоустойчивого кластера Kubernetes на Bare-Metal](../Installation/install_k8s.md).

## Шаг 1: Подготовка всех узлов (Master и Workers)

На **каждой** машине, которая будет частью кластера, необходимо выполнить следующие действия.

### 1.1. Установка среды выполнения контейнеров

Kubernetes требует наличия container runtime. В данном примере используется Docker.

```bash
# Установка зависимостей
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl

# Установка Docker
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 1.2. Установка инструментов Kubernetes

```bash
# Добавление официального GPG ключа Google Cloud
sudo curl -fsSLo /usr/share/keyrings/kubernetes-archive-keyring.gpg https://packages.cloud.google.com/apt/doc/apt-key.gpg

# Добавление репозитория Kubernetes
echo "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Установка kubelet, kubeadm и kubectl
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# Закрепление версий, чтобы избежать случайных обновлений
sudo apt-mark hold kubelet kubeadm kubectl
```

## Шаг 2: Инициализация Master-узла

Эти команды выполняются **только на той машине, которая будет control-plane**.

### 2.1. Запуск инициализации кластера

Команда `kubeadm init` развернет компоненты control-plane. Флаг `--pod-network-cidr` обязателен для большинства сетевых плагинов (CNI).

```bash
# Для Flannel используется эта подсеть
sudo kubeadm init --pod-network-cidr=10.244.0.0/16
```

После успешного выполнения команда выведет:
1.  Инструкции по настройке `kubectl` для текущего пользователя.
2.  Команду `kubeadm join` с токеном, которую нужно будет выполнить на worker-нодах. **Обязательно сохраните эту команду.**

### 2.2. Настройка доступа к кластеру для пользователя

```bash
# Создаем директорию для конфигурации
mkdir -p $HOME/.kube

# Копируем конфигурацию администратора в домашнюю директорию
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config

# Устанавливаем права доступа
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

### 2.3. Установка сетевого плагина (CNI)

Кластер не будет полностью функционален до установки CNI. В транскрипте использовался Flannel.

```bash
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml
```

После этого master-узел должен перейти в состояние `Ready`. Проверить можно командой `kubectl get nodes`.

## Шаг 3: Присоединение Worker-узлов

На **каждой worker-ноде** выполните команду `kubeadm join`, которую вы сохранили на шаге 2.1.

```bash
# Пример команды
sudo kubeadm join <ip-мастера>:<порт-мастера> --token <токен> --discovery-token-ca-cert-hash sha256:<хэш>
```

После выполнения этой команды узел присоединится к кластеру. Через некоторое время он также должен появиться в выводе `kubectl get nodes` со статусом `Ready`.

Если вы потеряли токен или команду, на master-ноде можно сгенерировать новую:
```bash
kubeadm token create --print-join-command
```

