# Minikube: Практические сценарии

## Definitions

**Minikube** — инструмент для запуска локального однонодового кластера Kubernetes. Используется для разработки, тестирования и обучения.

**Драйвер Minikube** — механизм виртуализации для запуска кластера (docker, virtualbox, kvm2, hyperkit, hyper-v, none).

---

## Basic Concepts

### Требования

| Компонент | Версия | Назначение |
| :--- | :--- | :--- |
| **Docker** | 18.03+ | Container runtime (обязательно) |
| **Minikube** | Последняя | Инструмент развёртывания |
| **kubectl** | Любая | Управление кластером (опционально, встроен в Minikube) |
| **CPU** | 2 ядра | Минимум, рекомендовано 4 |
| **Память** | 2 ГБ | Минимум, рекомендовано 4-8 ГБ |
| **Диск** | 20 ГБ | Минимум, рекомендовано 40 ГБ |

### Поддерживаемые версии Kubernetes

Minikube поддерживает последнюю версию Kubernetes + 6 предыдущих минорных версий.

| Версия Kubernetes | Статус | EOL |
| :--- | :--- | :--- |
| 1.33 | Активная поддержка | Апрель 2027 |
| 1.32 | Активная поддержка | Декабрь 2026 |
| 1.31 | Активная поддержка | Август 2026 |

> **Примечание:** Версии 1.30 и ниже достигли EOL. Проверяйте [release notes](https://github.com/kubernetes/minikube/releases) для актуальных образов.

---

## Practical Scenarios

### Установка

#### Docker Desktop

**Требование:** Docker Desktop должен быть установлен и запущен.

**Проверка:** `docker system info`

**Установка:**

| ОС | Команда |
| :--- | :--- |
| **macOS** | Скачать с [docker.com](https://www.docker.com/products/docker-desktop/) |
| **Linux** | `curl -fsSL https://get.docker.com \| sh` |
| **Windows** | Скачать с [docker.com](https://www.docker.com/products/docker-desktop/) |

#### Minikube

**macOS (Homebrew):** `brew install minikube`

**Linux (binary):** `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube`

**Windows (Chocolatey):** `choco install minikube`

**Проверка:** `minikube version`

#### kubectl (опционально)

Minikube включает встроенную версию kubectl. Для установки отдельной версии:

**macOS:** `brew install kubectl`

**Linux:** `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl`

**Проверка:** `kubectl version --client`

---

### Запуск кластера

#### Базовый запуск

```bash
minikube start
```

**Что происходит:** проверка драйвера, скачивание образа узла, создание контейнера/VM, инициализация Kubernetes, настройка kubeconfig.

**Результат:** кластер запущен, kubectl настроен на использование контекста `minikube`.

### Запуск с параметрами

**Выделение ресурсов:** `minikube start --cpus=4 --memory=8192mb`

**Версия Kubernetes:** `minikube start --kubernetes-version=v1.33.0`

**Драйвер:** `minikube start --driver=virtualbox`

**Сеть:** `minikube start --insecure-registry="10.0.0.0/24"`

### Проверка состояния

**Статус:** `minikube status`

**Узлы:** `minikube kubectl -- get nodes` или `kubectl get nodes`

**Ожидаемый вывод:**
```
NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   2m    v1.33.0
```

**Namespace:** `minikube kubectl -- get namespaces`

---

### Работа с кластером

### Развёртывание приложений

**Деплоймент:** `kubectl create deployment nginx --image=nginx:1.27`

**Проверка:** `kubectl get pods`

**Сервис:** `kubectl expose deployment nginx --port=80 --type=NodePort`

**URL сервиса:** `minikube service nginx --url`

### Доступ к Dashboard

`minikube dashboard` — открывает Kubernetes Dashboard в браузере.

### SSH-доступ к узлу

`minikube ssh` — подключение к узлу.

**Внутри узла:**
- Проверка компонентов: `kubectl get pods -n kube-system`
- Логи kubelet: `journalctl -u kubelet`

### Копирование файлов

**В кластер:** `minikube cp ./config.yaml /home/docker/config.yaml`

**Из кластера:** `minikube cp /var/log/pods/mypod.log ./logs/`

---

### Управление кластером

### Остановка и запуск

**Остановка (сохранение данных):** `minikube stop`

**Запуск:** `minikube start`

### Перезапуск

`minikube restart`

### Удаление кластера

**Текущий:** `minikube delete`

**Конкретный:** `minikube delete -p cluster-name`

**Все:** `minikube delete --all`

---

### Работа с аддонами

### Список аддонов

```bash
minikube addons list
```

**Пример вывода:**

```
|         ADDON NAME          | PROFILE  |    STATUS    |
|-----------------------------|----------|--------------|
| dashboard                   | minikube | ✅ enabled   |
| default-storageclass        | minikube | ✅ enabled   |
| ingress                     | minikube | 💡 disabled  |
| metrics-server              | minikube | 💡 disabled  |
| registry                    | minikube | 💡 disabled  |
| storage-provisioner         | minikube | ✅ enabled   |
```

### Включение аддонов

**Ingress:** `minikube addons enable ingress`

**Metrics-server:** `minikube addons enable metrics-server`

**Registry:** `minikube addons enable registry`

### Настройка Ingress

```bash
minikube addons enable ingress
kubectl get pods -n ingress-nginx
kubectl apply -f ingress.yaml
```

---

### Работа с изображениями Docker

### Загрузка образов в Minikube

**Сборка внутри Minikube:**
```bash
eval $(minikube docker-env)
docker build -t myapp:1.0 .
kubectl create deployment myapp --image=myapp:1.0
```

### Использование локального Registry

```bash
minikube addons enable registry
docker tag myapp:1.0 localhost:5000/myapp:1.0
docker push localhost:5000/myapp:1.0
kubectl create deployment myapp --image=localhost:5000/myapp:1.0
```

---

### Multi-node кластеры

### Создание multi-node кластера

```bash
minikube start --nodes=3 --cpus=2 --memory=4096mb
kubectl get nodes
```

**Вывод:**
```
NAME           STATUS   ROLES           AGE   VERSION
minikube       Ready    control-plane   5m    v1.33.0
minikube-m02   Ready    <none>          4m    v1.33.0
minikube-m03   Ready    <none>          3m    v1.33.0
```

**Добавление узлов:** `minikube node add --worker`

**Удаление узлов:** `minikube node remove minikube-m03`

---

### Отладка и мониторинг

**Просмотр логов:**
- Все поды в namespace: `kubectl logs -n kube-system -l app=coredns`
- Конкретный под: `kubectl logs <pod-name> -n <namespace>`

**Описание ресурсов:**
- Узел: `kubectl describe node minikube`
- Под: `kubectl describe pod <pod-name>`

**Метрики ресурсов:** `minikube addons enable metrics-server`, затем `kubectl top nodes`, `kubectl top pods`

---

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `docker system info` не работает | Docker не запущен | Запустить Docker Desktop |
| `Unable to connect to the server` | Кластер остановлен | `minikube start` |
| `context "minikube" does not exist` | kubeconfig повреждён | `minikube start` (пересоздаст) |
| Pod в статусе `Pending` | Нет ресурсов | `minikube stop && minikube start --cpus=4 --memory=8192mb` |
| `ImagePullBackOff` | Образ недоступен | Проверить имя образа, использовать `eval $(minikube docker-env)` |

---

## Additional Information

- **Официальная документация:** [minikube.sigs.k8s.io](https://minikube.sigs.k8s.io/docs/)
- **GitHub:** [kubernetes/minikube](https://github.com/kubernetes/minikube)
- **Определения и концепции:** [minikube_concepts.md](./minikube_concepts.md)
- **kubeconfig и подключение:** [../../Operations/kubeconfig_and_connection.md](../../Operations/kubeconfig_and_connection.md)
