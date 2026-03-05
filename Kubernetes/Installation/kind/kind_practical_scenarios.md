# kind: Практические сценарии

## Установка kind

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

---

## Создание кластера

### Базовый кластер (1 control-plane + 1 worker)

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

### Multi-node кластер для тестирования HA

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

## Проверка кластера

```bash
# Список кластеров
kind get clusters

# Контекст kubectl
kubectl config get-contexts
kubectl config use-context kind-my-cluster

# Статус узлов
kubectl get nodes
```

---

## Загрузка локальных Docker-образов

```bash
# Сборка образа
docker build -t my-app:dev .

# Загрузка в кластер kind
kind load docker-image my-app:dev --name my-cluster

# Развертывание
kubectl create deployment my-app --image=my-app:dev
```

---

## Развертывание простого приложения

```yaml
# nginx-deployment.yaml
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
        image: nginx:1.25.5
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
# Применение манифеста
kubectl apply -f nginx-deployment.yaml

# Проверка
kubectl get pods
kubectl get svc

# Доступ к приложению
kubectl get svc nginx-service
# Доступ по адресу localhost:<NodePort>
```

---

## Удаление кластера

```bash
# Удаление конкретного кластера
kind delete cluster --name my-cluster

# Удаление всех кластеров
kind delete clusters --all
```

---

## Интеграция с CI/CD

**Пример GitHub Actions:**

```yaml
- name: Create kind cluster
  uses: helm/kind-action@v1
  with:
    cluster_name: 'test-cluster'
    config: kind-config.yaml
```

---

## Связанные документы

- **[kind: Концепции](./kind_concepts.md)** — определения, архитектура, сравнение
- **[kind: Конфигурация](./kind_configuration.md)** — подробное описание конфигурации YAML
