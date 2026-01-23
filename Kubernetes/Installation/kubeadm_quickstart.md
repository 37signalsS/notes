# Быстрый старт с kubeadm

## Определения

*   **kubeadm**: Официальный инструмент командной строки для простой инициализации (bootstrapping) production-ready кластеров Kubernetes.
*   **kubelet**: Агент, который работает на каждом узле кластера. Он обеспечивает, чтобы контейнеры были запущены в подах.
*   **kubectl**: Основной инструмент командной строки для взаимодействия с API-сервером Kubernetes и управления объектами кластера.
*   **Bootstrapping**: Процесс первоначальной загрузки и инициализации кластера, включающий развертывание компонентов Control Plane и последующее присоединение узлов.

## Основные концепции

`kubeadm` упрощает создание кластера, но важно понимать его зону ответственности и общий рабочий процесс.

### Жизненный цикл кластера с kubeadm

*   **Фокус**: `kubeadm` сфокусирован на командах `init` (создание Control Plane) и `join` (присоединение узлов).
*   **Вне зоны ответственности**: `kubeadm` **не занимается** подготовкой инфраструктуры (виртуальных машин, сети), установкой зависимостей (например, Docker) и управлением конфигурацией кластера после его создания.

### Рабочий процесс

1.  **Подготовка узлов**: На всех будущих узлах кластера (master и worker) устанавливается среда выполнения контейнеров (например, Docker) и пакеты `kubeadm`, `kubelet`, `kubectl`.
2.  **Инициализация master-узла**: На одном из узлов выполняется команда `kubeadm init`. Эта команда развертывает компоненты Control Plane в виде статических подов (`etcd`, `kube-apiserver` и т.д.).
3.  **Установка сетевого плагина (CNI)**: Сразу после инициализации необходимо установить CNI-плагин (например, Flannel, Calico), чтобы поды на разных узлах могли общаться друг с другом. Без этого кластер не будет полностью функционален.
4.  **Присоединение worker-узлов**: На остальных узлах выполняется команда `kubeadm join` (с токеном, полученным на шаге 2) для их подключения к кластеру.

## Практические сценарии

### Сценарий: Создание одно-мастерного кластера

#### Шаг 1: Подготовка всех узлов (Master и Workers)

На **каждой** машине, которая будет частью кластера, необходимо выполнить следующие действия.

1.  **Установка среды выполнения контейнеров (Docker)**
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

2.  **Установка инструментов Kubernetes (`kubeadm`, `kubelet`, `kubectl`)**
    ```bash
    # Добавление официального GPG ключа Google Cloud
    sudo curl -fsSLo /usr/share/keyrings/kubernetes-archive-keyring.gpg https://packages.cloud.google.com/apt/doc/apt-key.gpg
    
    # Добавление репозитория Kubernetes
    echo "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee /etc/apt/sources.list.d/kubernetes.list
    
    # Установка
    sudo apt-get update
    sudo apt-get install -y kubelet kubeadm kubectl
    
    # Закрепление версий, чтобы избежать случайных обновлений
    sudo apt-mark hold kubelet kubeadm kubectl
    ```

#### Шаг 2: Инициализация Master-узла

Эти команды выполняются **только на машине, которая будет control-plane**.

1.  **Запуск инициализации кластера**
    Команда `kubeadm init` развернет компоненты control-plane. Флаг `--pod-network-cidr` обязателен для большинства сетевых плагинов.
    ```bash
    # Для Flannel используется эта подсеть
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16
    ```
    После успешного выполнения команда выведет инструкции по настройке `kubectl` и команду `kubeadm join` с токеном. **Обязательно сохраните эту команду.**

2.  **Настройка доступа к кластеру для локального пользователя**
    ```bash
    mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config
    ```

#### Шаг 3: Установка сетевого плагина (CNI)

Кластер не будет полностью функционален (узлы не перейдут в состояние `Ready`) до установки CNI.

```bash
# Установка Flannel
kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml
```
После этого master-узел должен перейти в состояние `Ready`. Проверить: `kubectl get nodes`.

#### Шаг 4: Присоединение Worker-узлов

На **каждой worker-ноде** выполните команду `kubeadm join`, которую вы сохранили на шаге 2.

```bash
# Пример команды
sudo kubeadm join <ip-мастера>:<порт-мастера> --token <токен> --discovery-token-ca-cert-hash sha256:<хэш>
```
После выполнения этой команды узел присоединится к кластеру. Через некоторое время он также должен появиться в выводе `kubectl get nodes` со статусом `Ready`.

## Дополнительная информация

### Управление токеном присоединения

Если вы потеряли токен или его срок действия истек, на master-ноде можно сгенерировать новую команду для присоединения:
```bash
kubeadm token create --print-join-command
```

### Сброс состояния узла

Для отсоединения узла от кластера и полной очистки всех изменений, сделанных `kubeadm`, используется команда `reset`. Это полезно, если нужно инициализировать узел заново.
```bash
sudo kubeadm reset
```