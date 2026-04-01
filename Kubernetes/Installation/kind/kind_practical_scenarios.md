# kind: Практические сценарии

## Definitions

**kind** — инструмент для запуска локальных Kubernetes-кластеров, где каждый узел работает как Docker-контейнер.

**kind-кластер** — изолированная среда Kubernetes, управляемая через kind CLI.

---

## Basic Concepts

### Требования

| Компонент | Версия | Примечание |
| :--- | :--- | :--- |
| Docker | 18.03+ | Обязательное требование |
| Go | 1.16+ | Только для сборки из исходников |
| kubectl | Любая | Для управления кластером |
| ОС | Linux/macOS/Windows | Полная поддержка |

### Команды kind

| Команда | Описание |
| :--- | :--- |
| `kind create cluster` | Создание нового кластера |
| `kind get clusters` | Список существующих кластеров |
| `kind delete cluster` | Удаление кластера |
| `kind load docker-image` | Загрузка Docker-образа в кластер |
| `kind export kubeconfig` | Экспорт kubeconfig кластера |

---

## Practical Scenarios

### Установка kind

**Linux (amd64):**

```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
kind version
```

**macOS (Homebrew):**

```bash
brew install kind
```

**Windows (PowerShell):**

```powershell
curl.exe -Lo kind-windows-amd64.exe https://kind.sigs.k8s.io/dl/v0.31.0/kind-windows-amd64
Move-Item .\kind-windows-amd64.exe c:\some-dir-in-your-PATH\kind.exe
```

> **Примечание:** Версия `v0.31.0` актуальна на 2026 год. Проверяйте [releases](https://github.com/kubernetes-sigs/kind/releases).

---

### Создание базового кластера

```bash
# Минимальный кластер
kind create cluster --name my-cluster

# С конфигурацией
kind create cluster --name my-cluster --config kind-config.yaml
```

**Конфигурация (kind-config.yaml):**

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
```

---

### HA-кластер (multi-node)

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

---

### Проверка кластера

```bash
# Список кластеров
kind get clusters

# Контекст kubectl
kubectl config use-context kind-my-cluster

# Статус узлов и подов
kubectl get nodes
kubectl get pods -A
```

---

### Загрузка локальных Docker-образов

```bash
# Сборка и загрузка
docker build -t my-app:dev .
kind load docker-image my-app:dev --name my-cluster

# Развертывание
kubectl create deployment my-app --image=my-app:dev
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
        readinessProbe:
          httpGet:
            path: /
            port: 80
          initialDelaySeconds: 5
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
kubectl get pods
kubectl get svc nginx-service
# Доступ: localhost:<NodePort>
```

---

### Удаление кластера

```bash
# Конкретный кластер
kind delete cluster --name my-cluster

# Все кластеры
kind delete clusters --all
```

---

### Интеграция с CI/CD

**GitHub Actions:**

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Setup kind
      uses: helm/kind-action@v1
      with:
        cluster_name: 'test-cluster'
        config: kind-config.yaml
        version: v0.31.0
    - name: Run tests
      run: |
        kubectl apply -f manifests/
        kubectl wait --for=condition=ready pod -l app=test --timeout=120s
```

**GitLab CI:**

```yaml
test:
  image: docker:24-dind
  services:
    - docker:24-dind
  script:
    - curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.31.0/kind-linux-amd64
    - chmod +x ./kind
    - ./kind create cluster --name test-cluster
    - kubectl apply -f manifests/
```

---

### Отладка и диагностика

```bash
# Логи узлов
docker logs kind-control-plane

# Экспорт логов кластера
kind export logs ./log-directory --name my-cluster

# Подключение к узлу
docker exec -it kind-control-plane bash

# Экспорт kubeconfig
kind export kubeconfig --name my-cluster
```

---

## Additional Information

### Версии Kubernetes

| Kubernetes | Образ | Статус |
| :--- | :--- | :--- |
| 1.35 | `kindest/node:v1.35.0` | Активная |
| 1.34 | `kindest/node:v1.34.0` | Активная |
| 1.33 | `kindest/node:v1.33.0` | Активная |

> **Примечание:** Версии 1.32 и ниже достигли EOL (февраль 2026).

### Ссылки

- [kind: Концепции](./kind_concepts.md)
- [kind: Конфигурация](./kind_configuration.md)
- [Официальная документация](https://kind.sigs.k8s.io/)
