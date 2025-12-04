# Развертывание кластера Kubernetes локально с использованием `kind`

## 1. Определения

*   **kind (Kubernetes in Docker)**: Инструмент для запуска локальных кластеров Kubernetes с использованием контейнеров Docker в качестве "узлов" кластера. Kind предназначен для тестирования Kubernetes, локальной разработки и CI/CD, предоставляя быструю и легкую среду для работы с кластерами Kubernetes.

## 2. Основные понятия

### Основные принципы работы kind

*   **Каждый узел — это Docker-контейнер:** `kind` запускает `kubelet` и другие компоненты внутри контейнеров Docker.
*   **Быстрое создание и удаление:** Кластеры создаются и уничтожаются за считанные минуты, что удобно для частых тестов и экспериментов.
*   **Поддержка Multi-node:** Позволяет имитировать более реалистичные сценарии с несколькими управляющими (control-plane) и рабочими (worker) узлами.

### Установка kind

Для развертывания кластера `kind` необходимо установить сам инструмент `kind` и Docker.

Инструкции по установке можно найти на [официальном сайте](https://kind.sigs.k8s.io/docs/user/quick-start/#installation).

Пример установки `kind` для Linux:

```bash
# Пример для Linux (используйте актуальную версию с официального сайта)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
mv ./kind ~/.local/bin/kind # Или другой путь, включенный в вашу переменную PATH
```
*(Примечание: `v0.20.0` - это пример версии, используйте актуальную с официального сайта)*

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

## 3. Практические сценарии

### 3.1. Создание кластера Kubernetes с kind

1.  **Сохраните конфигурацию кластера** в файл, например, `kind-config.yaml`.
    ```yaml
    kind: Cluster
    apiVersion: kind.x-k8s.io/v1alpha4
    nodes:
    - role: control-plane
    - role: worker
    ```

2.  **Создайте кластер**, используя сохраненный файл конфигурации:
    ```bash
    kind create cluster --name my-kind-cluster --config kind-config.yaml
    ```
    Где `my-kind-cluster` — это имя вашего кластера. Если `--name` не указан, создается кластер с именем `kind`.

3.  **Проверка контекста `kubectl`**:
    `kind` автоматически настраивает `kubectl` для взаимодействия с новым кластером.
    Чтобы убедиться, что `kubectl` указывает на ваш новый кластер `kind`:
    ```bash
    kubectl config get-contexts
    kubectl config use-context kind-my-kind-cluster
    ```
    Контекст будет иметь префикс `kind-` и имя вашего кластера.

4.  **Проверка состояния узлов кластера**:
    ```bash
    kubectl get nodes
    ```

### 3.2. Развертывание простого приложения

1.  **Создайте манифест развертывания и сервиса**, например, `nginx-deployment.yaml`:
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

2.  **Примените манифест**:
    ```bash
    kubectl apply -f nginx-deployment.yaml
    ```

3.  **Проверьте состояние подов и сервисов**:
    ```bash
    kubectl get pods
    kubectl get svc
    ```

4.  **Доступ к приложению**:
    Чтобы получить доступ к приложению Nginx, необходимо найти порт, который `NodePort` выделил на узле.
    ```bash
    kubectl get svc nginx-service
    ```
    Вывод покажет `NodePort`, например `3xxxx:30080/TCP`.
    IP-адрес узла можно получить из `kind get kubeconfig --name my-kind-cluster` (для получения информации о кластере) или обычно это `localhost`.
    Доступ будет по адресу `localhost:3xxxx`.

### 3.3. Загрузка Docker-образов в кластер

Поскольку кластер `kind` работает в Docker, он не имеет прямого доступа к локально собранным образам на хост-машине. Чтобы использовать локальный образ, его нужно сначала загрузить в кластер:

```bash
kind load docker-image my-app:latest --name my-kind-cluster
```
Где `my-kind-cluster` — имя вашего кластера, а `my-app:latest` — имя и тег образа.

### 3.4. Получение информации о кластере

Чтобы просмотреть список всех активных кластеров `kind`:

```bash
kind get clusters
```

### 3.5. Удаление кластера kind

Для удаления кластера `kind` используйте команду:
```bash
kind delete cluster --name my-kind-cluster
```
Если `--name` не указан, будет удален кластер с именем `kind`.

<h2>4. Расширенные детали</h2>

<h3>Настройка узлов кластера</h3>

В конфигурации `kind` можно указать дополнительные параметры для узлов, что позволяет создавать более сложные и функциональные кластеры.

*   **`extraPortMappings`**: Проброс портов с хост-машины в контейнеры узлов. Это позволяет обращаться к сервисам внутри кластера напрямую с хоста по определенным портам.
    Пример:
    ```yaml
    extraPortMappings:
    - containerPort: 30000 # Порт внутри контейнера узла
      hostPort: 30000      # Порт на хост-машине
      listenAddress: "127.0.0.1" # IP-адрес на хосте, на котором будет слушаться порт
      protocol: TCP
    ```

*   **`extraMounts`**: Добавление дополнительных монтирований (bind mounts) в контейнеры узлов. Полезно для локальной разработки, передачи файлов или использования локальных хранилищ.
    Пример:
    ```yaml
    extraMounts:
    - hostPath: /path/on/host    # Путь на хост-машине
      containerPath: /path/in/container # Путь внутри контейнера узла
    ```

*   **`kubeadmConfigPatches`**: Применение патчей к конфигурации `kubeadm` для более тонкой настройки компонентов Kubernetes. Это может быть полезно для изменения параметров `kube-apiserver`, `kube-controller-manager` и других.
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

*   **`image`**: Указание пользовательского образа Docker для узла (например, с определенной версией Kubernetes или предварительно установленными инструментами).
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