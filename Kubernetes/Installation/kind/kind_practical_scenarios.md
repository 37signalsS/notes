# kind — практические сценарии

## Определения

Основные определения и архитектура инструмента представлены в файле **[kind — определения и концепции](./kind_concepts.md)**.

**kind-кластер** — изолированная среда Kubernetes, управляемая через CLI (Command Line Interface) `kind`.

---

## Основные концепции

### Требования

Полный список системных требований и поддерживаемых ОС (Операционных Систем) представлен в разделе **[Требования к системе](./kind_concepts.md#требования-к-системе)**.

### Основные команды kind

| Команда | Описание |
| :--- | :--- |
| `kind create cluster` | Создание нового кластера. |
| `kind get clusters` | Список существующих кластеров. |
| `kind delete cluster` | Удаление кластера. |
| `kind load docker-image` | Загрузка локального Docker-образа напрямую в узлы кластера. |
| `kind export kubeconfig` | Экспорт или обновление файла kubeconfig для доступа к кластеру. |
| `kind export logs` | Выгрузка диагностических логов узлов и компонентов кластера. |

---

## Практические сценарии

### Установка kind

**Linux (amd64 — 64-разрядная архитектура x86):**

```bash
# Скачивание бинарного файла актуальной версии v0.32.0 (август 2026 года)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

kind version
# → kind v0.32.0 go1.22.x linux/amd64
```

**macOS (Homebrew):**

```bash
brew install kind
```

**Windows (PowerShell):**

```powershell
curl.exe -Lo kind-windows-amd64.exe https://kind.sigs.k8s.io/dl/v0.32.0/kind-windows-amd64
Move-Item .\kind-windows-amd64.exe c:\some-dir-in-your-PATH\kind.exe
```

> **Примечание:** Актуальная версия на август 2026 года — `v0.32.0`. В новых релизах используется балансировщик **Envoy** (вместо HAProxy) для HA-кластеров. Проверяйте обновления на странице [GitHub Releases](https://github.com/kubernetes-sigs/kind/releases).

---

### Создание базового кластера

```bash
# Минимальный кластер с именем по умолчанию (kind)
kind create cluster
# → Creating cluster "kind" ...

# Создание кластера с кастомным именем
kind create cluster --name my-cluster
# → Creating cluster "my-cluster" ...

# Использование конкретной версии Kubernetes (например, v1.37.0)
kind create cluster --image kindest/node:v1.37.0
# →  • Ensuring node image (kindest/node:v1.37.0) 🖼 ...
```

Пример минимального конфигурационного файла доступен в разделе **[Минимальная конфигурация](./kind_configuration.md#минимальная-конфигурация)**.

---

### HA-кластер (High Availability — высокая доступность)

Для тестирования отказоустойчивости рекомендуется использовать многоузловую конфигурацию.

```bash
kind create cluster --name ha-cluster --config kind-config-ha.yaml
# → Creating cluster "ha-cluster" ...
# →  • Ensuring node image (kindest/node:v1.37.0) 🖼  ...
# →  • Preparing nodes 📦 📦 📦 📦  ...
# →  • Starting control-plane 🕹️  ...
```

Подробный пример конфигурации HA-кластера с пробросом портов доступен в разделе **[HA-кластер (multi-node)](./kind_configuration.md#высокодоступный-кластер-ha--multi-node)**.

---

### Поддержка типа LoadBalancer (cloud-provider-kind)

По умолчанию в kind сервисы `type: LoadBalancer` находятся в состоянии `Pending`. Начиная с 2024–2025 годов, стандартным способом решения этой проблемы (помимо MetalLB) является использование **cloud-provider-kind**.

```bash
# 1. Установка cloud-provider-kind (как бинарный файл или через Go)
go install sigs.k8s.io/cloud-provider-kind@latest

# 2. Запуск провайдера в отдельном терминале (должен работать постоянно)
cloud-provider-kind

# 3. В другом терминале создаем сервис
kubectl expose deployment nginx --port=80 --type=LoadBalancer

# 4. Проверка получения внешнего IP
kubectl get svc
# → NAME    TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → nginx   LoadBalancer   10.96.114.155   172.18.0.100  80:31254/TCP   10s
```

---

### Проверка кластера

```bash
# Список всех локальных кластеров kind
kind get clusters

# Переключение контекста kubectl
kubectl config use-context kind-my-cluster

# Ожидание готовности узлов (полезно для скриптов)
kubectl wait --for=condition=Ready nodes --all --timeout=60s

# Статус критических системных компонентов
kubectl get pods -n kube-system
```

---

### Загрузка локальных Docker-образов

Для запуска образов, которых нет в реестре, их необходимо загрузить в Container Runtime узлов.

```bash
# 1. Сборка образа
docker build -t my-app:dev .

# 2. Загрузка в кластер
kind load docker-image my-app:dev --name my-cluster
```

**Загрузка из tar-архива:**

```bash
docker save -o my-app.tar my-app:dev
kind load image-archive my-app.tar --name my-cluster
```

---

### Развертывание тестового приложения

```yaml
# nginx-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deployment
spec:
  replicas: 3
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
        image: nginx:1.27
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

```bash
kubectl apply -f nginx-deployment.yaml
kubectl get pods -l app=nginx
```

---

### Удаление кластера

```bash
kind delete cluster --name my-cluster
kind delete clusters --all
```

---

### Интеграция с CI/CD

**GitHub Actions:**

```yaml
- name: Setup kind
  uses: helm/kind-action@v1
  with:
    cluster_name: 'ci-cluster'
    version: v0.32.0
    node_image: kindest/node:v1.37.0
```

---

### Отладка и диагностика

**Низкоуровневая проверка внутри узла:**

```bash
# Подключение к узлу
docker exec -it my-cluster-control-plane bash

# Проверка контейнеров через crictl (внутри узла)
crictl ps
crictl images

# Проверка логов CNI (kindnet)
tail -f /var/log/kindnetd.log

# Проверка сетевых интерфейсов узла
ip addr show
```

**Экспорт логов для анализа:**

```bash
kind export logs ./kind-logs-directory --name my-cluster
```

**Обновление kubeconfig (Internal vs External):**

```bash
# По умолчанию используется для доступа с хоста (127.0.0.1)
kind export kubeconfig --name my-cluster

# --internal используется для доступа из других Docker-контейнеров
kind export kubeconfig --name my-cluster --internal
```

---

## Дополнительная информация

### Поддерживаемые версии

Список поддерживаемых версий Kubernetes и образов узлов доступен в разделе **[Версии Kubernetes](./kind_concepts.md#поддерживаемые-версии-kubernetes)**.

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — внутреннее устройство, сеть, хранилище
- [kind — конфигурация](./kind_configuration.md) — проброс портов, multi-node кластеры, патчи containerd
- [Официальная документация cloud-provider-kind](https://github.com/kubernetes-sigs/cloud-provider-kind)
- [Официальная документация kind](https://kind.sigs.k8s.io/)
