# Minikube: Практические сценарии

## 1. Подготовка окружения

### 1.1. Установка Docker Desktop

**Требование:** Docker Desktop должен быть установлен и запущен.

**Проверка:**

```bash
docker system info
```

**Установка:**

| ОС | Команда |
| :--- | :--- |
| **macOS** | Скачать с [docker.com](https://www.docker.com/products/docker-desktop/) |
| **Linux** | `curl -fsSL https://get.docker.com | sh` |
| **Windows** | Скачать с [docker.com](https://www.docker.com/products/docker-desktop/) |

### 1.2. Установка Minikube

**macOS (Homebrew):**

```bash
brew install minikube
```

**Linux (binary):**

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

**Windows (Chocolatey):**

```powershell
choco install minikube
```

**Проверка установки:**

```bash
minikube version
```

### 1.3. Установка kubectl (опционально)

Minikube включает встроенную версию kubectl. Для установки отдельной версии:

```bash
# macOS
brew install kubectl

# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Проверка
kubectl version --client
```

---

## 2. Запуск кластера

### 2.1. Базовый запуск

```bash
minikube start
```

**Что происходит:**

1. Проверка драйвера по умолчанию (docker)
2. Скачивание образа узла (kindest/node)
3. Создание контейнера/VM
4. Инициализация Kubernetes
5. Настройка kubeconfig

**Результат:**

```
😄  minikube v1.32.0 on Darwin arm64
✨  Automatically selected the docker driver
📌  Using Docker Desktop with the default (kubernetes) kubelet
🔥  Creating docker container (CPUs=2, Memory=2200MB) ...
🐳  Preparing Kubernetes v1.28.3 on Docker 24.0.7 ...
    ▪ Generating certificates and keys ...
    ▪ Booting up control plane ...
    ▪ Configuring RBAC rules ...
🔎  Verifying Kubernetes components...
🌟  Enabled addons: storage-provisioner, default-storageclass
🏄  Done! kubectl is now configured to use "minikube" cluster
```

### 2.2. Запуск с параметрами

**Выделение ресурсов:**

```bash
minikube start --cpus=4 --memory=8192mb
```

**Выбор версии Kubernetes:**

```bash
minikube start --kubernetes-version=v1.28.0
```

**Выбор драйвера:**

```bash
minikube start --driver=virtualbox
```

**Настройка сети:**

```bash
minikube start --insecure-registry="10.0.0.0/24"
```

### 2.3. Проверка состояния

**Статус кластера:**

```bash
minikube status
```

**Список узлов:**

```bash
# Через встроенный kubectl
minikube kubectl -- get nodes

# Через установленный kubectl
kubectl get nodes
```

**Ожидаемый вывод:**

```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   2m    v1.28.3
```

**Все пространства имён:**

```bash
minikube kubectl -- get namespaces
```

---

## 3. Работа с кластером

### 3.1. Развёртывание приложений

**Создание деплоймента:**

```bash
kubectl create deployment nginx --image=nginx:1.27
```

**Проверка подов:**

```bash
kubectl get pods
```

**Создание сервиса:**

```bash
kubectl expose deployment nginx --port=80 --type=NodePort
```

**Получение URL сервиса:**

```bash
minikube service nginx --url
```

### 3.2. Доступ к Dashboard

```bash
minikube dashboard
```

Откроется веб-интерфейс Kubernetes Dashboard в браузере.

### 3.3. SSH-доступ к узлу

```bash
minikube ssh
```

**Внутри узла:**

```bash
# Проверка компонентов K8s
kubectl get pods -n kube-system

# Просмотр логов
journalctl -u kubelet
```

### 3.4. Копирование файлов

```bash
# Копирование файла в кластер
minikube cp ./config.yaml /home/docker/config.yaml

# Копирование файла из кластера
minikube cp /var/log/pods/mypod.log ./logs/
```

---

## 4. Управление кластером

### 4.1. Остановка и запуск

**Остановка (сохранение данных):**

```bash
minikube stop
```

**Запуск после остановки:**

```bash
minikube start
```

### 4.2. Перезапуск

```bash
minikube restart
```

### 4.3. Удаление кластера

**Удаление текущего кластера:**

```bash
minikube delete
```

**Удаление конкретного кластера:**

```bash
minikube delete -p cluster-name
```

**Удаление всех кластеров:**

```bash
minikube delete --all
```

---

## 5. Работа с аддонами

### 5.1. Список аддонов

```bash
minikube addons list
```

**Пример вывода:**

```
|-----------------------------|----------|--------------|--------------------------------|
|         ADDON NAME          | PROFILE  |    STATUS    |           MAINTAINER           |
|-----------------------------|----------|--------------|--------------------------------|
| dashboard                   | minikube | ✅ enabled   | Kubernetes                     |
| default-storageclass        | minikube | ✅ enabled   | Kubernetes                     |
| ingress                     | minikube | 💡 disabled  | Kubernetes                     |
| metrics-server              | minikube | 💡 disabled  | Kubernetes                     |
| registry                    | minikube | 💡 disabled  | Kubernetes                     |
| storage-provisioner         | minikube | ✅ enabled   | Kubernetes                     |
|-----------------------------|----------|--------------|--------------------------------|
```

### 5.2. Включение аддонов

**Ingress-контроллер:**

```bash
minikube addons enable ingress
```

**Metrics-server:**

```bash
minikube addons enable metrics-server
```

**Registry:**

```bash
minikube addons enable registry
```

### 5.3. Настройка Ingress

```bash
# Включение
minikube addons enable ingress

# Проверка подов ingress
kubectl get pods -n ingress-nginx

# Пример Ingress-ресурса
kubectl apply -f ingress.yaml
```

---

## 6. Работа с изображениями Docker

### 6.1. Загрузка образов в Minikube

**Сборка образа внутри Minikube:**

```bash
# Оценка окружения Docker
eval $(minikube docker-env)

# Сборка образа
docker build -t myapp:1.0 .

# Развёртывание
kubectl create deployment myapp --image=myapp:1.0
```

### 6.2. Использование локального Registry

```bash
# Включение аддона
minikube addons enable registry

# Push образа
docker tag myapp:1.0 localhost:5000/myapp:1.0
docker push localhost:5000/myapp:1.0

# Развёртывание
kubectl create deployment myapp --image=localhost:5000/myapp:1.0
```

---

## 7. Multi-node кластеры

### 7.1. Создание multi-node кластера

```bash
minikube start --nodes=3 --cpus=2 --memory=4096mb
```

**Проверка узлов:**

```bash
kubectl get nodes
```

**Вывод:**

```
NAME           STATUS   ROLES           AGE   VERSION
minikube       Ready    control-plane   5m    v1.28.3
minikube-m02   Ready    <none>          4m    v1.28.3
minikube-m03   Ready    <none>          3m    v1.28.3
```

### 7.2. Добавление узлов

```bash
minikube node add --worker
```

### 7.3. Удаление узлов

```bash
minikube node remove minikube-m03
```

---

## 8. Отладка и мониторинг

### 8.1. Просмотр логов

```bash
# Логи всех подов в namespace
kubectl logs -n kube-system -l app=coredns

# Логи конкретного пода
kubectl logs <pod-name> -n <namespace>
```

### 8.2. Описание ресурсов

```bash
# Описание узла
kubectl describe node minikube

# Описание пода
kubectl describe pod <pod-name>
```

### 8.3. Метрики ресурсов

```bash
# Требует включённого metrics-server
minikube addons enable metrics-server

# Просмотр использования CPU/памяти
kubectl top nodes
kubectl top pods
```

---

## 9. Конфигурация kubeconfig

### 9.1. Проверка конфигурации

```bash
# Путь к файлу
echo $KUBECONFIG
# Или по умолчанию: ~/.kube/config

# Просмотр содержимого
kubectl config view
```

### 9.2. Переключение контекстов

```bash
# Список контекстов
kubectl config get-contexts

# Переключение на minikube
kubectl config use-context minikube

# Текущий контекст
kubectl config current-context
```

### 9.3. Экспорт конфигурации

```bash
# Копирование файла
cp ~/.kube/config ./backup-kubeconfig

# Для конкретного кластера
kubectl config view --minify --flatten > cluster-config.yaml
```

---

## 10. Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`docker system info` не работает** | Docker не запущен | Запустить Docker Desktop |
| **`Unable to connect to the server`** | Кластер остановлен | `minikube start` |
| **`context "minikube" does not exist`** | kubeconfig повреждён | `minikube start` (пересоздаст) |
| **Pod в статусе `Pending`** | Нет ресурсов | `minikube stop && minikube start --cpus=4 --memory=8192mb` |
| **`ImagePullBackOff`** | Образ недоступен | Проверить имя образа, использовать `eval $(minikube docker-env)` |

---

## Связанные документы

- **[Minikube: Определения и концепции](./minikube_concepts.md)** — базовая теория
- **[kind: Практические сценарии](../kind/kind_practical_scenarios.md)** — альтернатива на Docker
- **[kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)** — работа с контекстами
- **[LGTM Stack на Minikube](../LGTM_Stack/lgtm_otel_minikube_overview.md)** — пример развёртывания мониторинга
