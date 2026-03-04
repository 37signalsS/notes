# kind: Локальные кластеры Kubernetes в Docker

## 1. Определения

**kind (Kubernetes IN Docker)** — инструмент для запуска локальных кластеров Kubernetes, где каждый узел кластера запускается как Docker-контейнер. Предназначен для тестирования Kubernetes, локальной разработки и CI/CD.

**kindest/node** — официальный Docker-образ узла kind, содержащий все компоненты Kubernetes для запуска внутри контейнера.

## 2. Основные концепции

### Архитектура kind

| Компонент | Описание |
| :--- | :--- |
| **Узел как контейнер** | Каждый узел (control-plane, worker) — изолированный Docker-контейнер с kubelet и компонентами K8s |
| **Docker-in-Docker** | kind использует вложенную виртуализацию через Docker API хоста |
| **Изоляция сетей** | Каждый кластер создает собственную Docker-сеть для изоляции трафика |

### Преимущества и ограничения

| Преимущества | Ограничения |
| :--- | :--- |
| Быстрое создание/удаление (секунды-минуты) | Не предназначен для production |
| Поддержка multi-node кластеров | Ограниченная производительность (оверлей сети, storage) |
| Воспроизводимость конфигураций через YAML | Зависимость от Docker на хосте |
| Интеграция с CI/CD | Ограниченный доступ к железу хоста |

### Сравнение с аналогами

| Инструмент | Назначение | Отличие от kind |
| :--- | :--- | :--- |
| **[minikube](https://minikube.sigs.k8s.io/docs/)** | Локальная разработка | Запускает полноценную VM, тяжелее |
| **[talosctl](./local_cluster_with_talosctl.md)** | Локальная разработка | Использует Talos OS, безопаснее, но сложнее |
| **k3d** | Локальная разработка | Запускает k3s (облегченный K8s) в контейнерах |

## 3. Практические сценарии

### 3.1. Установка kind

**Требования:**
- Docker версии 18.03+
- Linux/macOS/Windows

**Установка на Linux:**

```bash
# Скачивание актуальной версии (проверьте версию на https://github.com/kubernetes-sigs/kind/releases)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Проверка установки
kind version
```

> **Примечание:** Версия `v0.24.0` актуальна на начало 2025. Проверяйте [releases](https://github.com/kubernetes-sigs/kind/releases) для свежих версий.

### 3.2. Создание кластера

**Базовый кластер (1 control-plane + 1 worker):**

```yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
```

```bash
kind create cluster --name my-cluster --config kind-config.yaml
```

**Проверка:**

```bash
# Список кластеров
kind get clusters

# Контекст kubectl
kubectl config get-contexts
kubectl config use-context kind-my-cluster

# Статус узлов
kubectl get nodes
```

### 3.3. Multi-node кластер для тестирования HA

```yaml
# kind-config-ha.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 6443
    hostPort: 6443
    protocol: TCP
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
```

```bash
kind create cluster --name ha-cluster --config kind-config-ha.yaml
```

### 3.4. Загрузка локальных Docker-образов

```bash
# Сборка образа
docker build -t my-app:dev .

# Загрузка в кластер kind
kind load docker-image my-app:dev --name my-cluster

# Развертывание
kubectl create deployment my-app --image=my-app:dev
```

### 3.5. Проброс портов для доступа к сервисам

```yaml
# kind-config-ports.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 30000
    listenAddress: "127.0.0.1"
    protocol: TCP
- role: worker
  extraPortMappings:
  - containerPort: 30001
    hostPort: 30001
    protocol: TCP
```

### 3.6. Монтирование томов с хоста

```yaml
# kind-config-mounts.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /data/k8s-storage
    containerPath: /mnt/storage
    readOnly: false
```

### 3.7. Удаление кластера

```bash
# Удаление конкретного кластера
kind delete cluster --name my-cluster

# Удаление всех кластеров
kind delete clusters --all
```

## 4. Дополнительная информация

### Поддерживаемые версии Kubernetes

kind поддерживает несколько версий Kubernetes одновременно. Образы доступны для:
- 1.31, 1.30, 1.29, 1.28, 1.27 (актуальные на 2025)

**Использование конкретной версии:**

```yaml
nodes:
- role: control-plane
  image: kindest/node:v1.31.0
```

### Переменные окружения

| Переменная | Описание |
| :--- | :--- |
| `KIND_EXPERIMENTAL_DOCKER_NETWORK` | Docker-сеть для кластера |
| `KIND_NODE_IMAGE` | Образ узла по умолчанию |

### Интеграция с CI/CD

**Пример GitHub Actions:**

```yaml
- name: Create kind cluster
  uses: helm/kind-action@v1
  with:
    cluster_name: 'test-cluster'
    config: kind-config.yaml
```

### Связанные документы

- **[Локальный кластер с Talos](./local_cluster_with_talosctl.md)** — альтернатива с Talos OS
- **[kubeadm: Быстрый старт](./kudeadm/kubeadm_quickstart.md)** — базовая утилита инициализации
- **[kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)** — работа с контекстами

### Конфигурация кластера kind

Конфигурация кластера `kind` определяется с помощью YAML-файла. Это позволяет точно настроить количество и роли узлов, проброс портов и другие параметры.

Пример минимальной конфигурации кластера с одним управляющим узлом и одним рабочим узлом:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
```

## Практические сценарии

### Создание кластера Kubernetes с kind

1. **Сохраните конфигурацию кластера** в файл, например, `kind-config.yaml`.

    ```yaml
    kind: Cluster
    apiVersion: kind.x-k8s.io/v1alpha4
    nodes:
    - role: control-plane
    - role: worker
    ```

2. **Создайте кластер**, используя сохраненный файл конфигурации:

    ```bash
    kind create cluster --name my-kind-cluster --config kind-config.yaml
    ```

    Где `my-kind-cluster` — это имя вашего кластера. Если `--name` не указан, создается кластер с именем `kind`.

3. **Проверка контекста `kubectl`**:
    `kind` автоматически настраивает `kubectl` для взаимодействия с новым кластером.
    Чтобы убедиться, что `kubectl` указывает на ваш новый кластер `kind`:

    ```bash
    kubectl config get-contexts
    kubectl config use-context kind-my-kind-cluster
    ```

    Контекст будет иметь префикс `kind-` и имя вашего кластера.

4. **Проверка состояния узлов кластера**:

    ```bash
    kubectl get nodes
    ```

### Развертывание простого приложения

1. **Создайте манифест развертывания и сервиса**, например, `nginx-deployment.yaml`:

    ```yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: nginx-deployment
      labels:
        app: nginx
    spec:
      replicas: 1
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
            image: nginx:1.25.5 # Используйте фиксированную версию
            ports:
            - containerPort: 80
    ---
    apiVersion: v1
    kind: Service
    metadata:
      name: nginx-service
    spec:
      selector:
        app: nginx
      ports:
        - protocol: TCP
          port: 80
          targetPort: 80
      type: NodePort
    ```

2. **Примените манифест**:

    ```bash
    kubectl apply -f nginx-deployment.yaml
    ```

3. **Проверьте состояние подов и сервисов**:

    ```bash
    kubectl get pods
    kubectl get svc
    ```

4. **Доступ к приложению**:
    Чтобы получить доступ к приложению Nginx, необходимо найти порт, который `NodePort` выделил на узле.

    ```bash
    kubectl get svc nginx-service
    ```

    Вывод покажет `NodePort`, например `3xxxx:30080/TCP`.
    IP-адрес узла можно получить из `kind get kubeconfig --name my-kind-cluster` (для получения информации о кластере) или обычно это `localhost`.
    Доступ будет по адресу `localhost:3xxxx`.

### Загрузка Docker-образов в кластер

Для использования локально собранных Docker-образов в `kind` кластере, их необходимо загрузить:

```bash
kind load docker-image my-app:latest --name my-kind-cluster
```

Здесь `my-kind-cluster` — имя кластера, `my-app:latest` — имя и тег образа.

### Получение информации о кластере

Чтобы просмотреть список всех активных кластеров `kind`:

```bash
kind get clusters
```

### Удаление кластера kind

Для удаления кластера `kind` используйте команду:

```bash
kind delete cluster --name my-kind-cluster
```

Если `--name` не указан, будет удален кластер с именем `kind`.

## Дополнительная информация

### Настройка узлов кластера

В конфигурации `kind` можно указать дополнительные параметры для узлов, что позволяет создавать более сложные и функциональные кластеры.

* **`extraPortMappings`**: Проброс портов с хост-машины в контейнеры узлов. Это позволяет обращаться к сервисам внутри кластера напрямую с хоста по определенным портам.
    Пример:

    ```yaml
    extraPortMappings:
    - containerPort: 30000 # Порт внутри контейнера узла
      hostPort: 30000      # Порт на хост-машине
      listenAddress: "127.0.0.1" # IP-адрес на хосте, на котором будет слушаться порт
      protocol: TCP
    ```

* **`extraMounts`**: Добавление дополнительных монтирований (bind mounts) в контейнеры узлов. Полезно для локальной разработки, передачи файлов или использования локальных хранилищ.
    Пример:

    ```yaml
    extraMounts:
    - hostPath: /path/on/host    # Путь на хост-машине
      containerPath: /path/in/container # Путь внутри контейнера узла
    ```

* **`kubeadmConfigPatches`**: Применение патчей к конфигурации `kubeadm` для более тонкой настройки компонентов Kubernetes. Это может быть полезно для изменения параметров `kube-apiserver`, `kube-controller-manager` и других.
    Пример:

    ```yaml
    kubeadmConfigPatches:
    - |
      apiVersion: kubeadm.k8s.io/v1beta3
      kind: InitConfiguration
      nodeRegistration:
        kubeletExtraArgs:
          node-labels: "ingress-ready=true"
    ```

* **`image`**: Указание пользовательского образа Docker для узла (например, с определенной версией Kubernetes или предварительно установленными инструментами).
    Пример:

    ```yaml
    image: kindest/node:v1.28.0 # Использование конкретного образа узла
    ```

Пример конфигурации `kind-config.yaml` с дополнительными параметрами:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 30000
    listenAddress: "127.0.0.1"
    protocol: TCP
  extraMounts:
  - hostPath: /path/on/host
    containerPath: /path/in/container
- role: worker
  image: kindest/node:v1.28.0 # Использование конкретного образа узла
- role: worker
```
