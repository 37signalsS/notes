# Создание кластера с kubeadm

## Практические сценарии

### Сценарий: Создание одно-мастерного кластера

#### Шаг 1: Подготовка всех узлов (Master и Workers)

1. **Установка среды выполнения контейнеров (Docker)**

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

2. **Установка инструментов Kubernetes (`kubeadm`, `kubelet`, `kubectl`)**

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

1. **Запуск инициализации кластера**
    Команда `kubeadm init` развернет компоненты control-plane. Флаг `--pod-network-cidr` обязателен для большинства сетевых плагинов.

    ```bash
    # Для Flannel используется эта подсеть
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16
    ```

    После успешного выполнения `kubeadm` выведет инструкции по настройке `kubectl` и команду `kubeadm join` с токеном. Сохраните эту команду.

2. **Настройка доступа к кластеру для локального пользователя**

    ```bash
    mkdir -p $HOME/.kube
    sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
    sudo chown $(id -u):$(id -g) $HOME/.kube/config
    ```

#### Шаг 3: Установка сетевого плагина (CNI)

> **Важно:** Кластер не будет полностью функционален (узлы не перейдут в состояние `Ready`) до установки CNI.

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

См. также: [Управление узлами кластера](./kubeadm_node_management.md)
