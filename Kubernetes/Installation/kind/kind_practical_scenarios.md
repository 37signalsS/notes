# kind — практические сценарии

## Определения

Основные определения и архитектура инструмента представлены в файле **[kind — определения и концепции](./kind_concepts.md)**.

**kind-кластер** — изолированная среда Kubernetes, управляемая через CLI (Command Line Interface) `kind`.

---

## Основные концепции

### Требования

Полный список системных требований и поддерживаемых ОС (Операционных Систем) представлен в разделе **[Требования](./kind_concepts.md#требования)**.

### Команды kind

| Команда | Описание |
| :--- | :--- |
| `kind create cluster` | Создание нового кластера |
| `kind get clusters` | Список существующих кластеров |
| `kind delete cluster` | Удаление кластера |
| `kind load docker-image` | Загрузка Docker-образа в кластер |
| `kind export kubeconfig` | Экспорт kubeconfig кластера |

---

## Практические сценарии

### Установка kind

**Linux (amd64 — 64-разрядная архитектура x86):**

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

Пример минимального конфигурационного файла доступен в разделе **[Минимальная конфигурация](./kind_configuration.md#минимальная-конфигурация)**.

---

### HA-кластер (High Availability — высокая доступность)

Для тестирования отказоустойчивости рекомендуется использовать многоузловую конфигурацию.

```bash
kind create cluster --name ha-cluster --config kind-config-ha.yaml
```

Подробный пример конфигурации HA-кластера с пробросом портов доступен в разделе **[HA-кластер (multi-node)](./kind_configuration.md#ha-кластер-multi-node)**.

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

### Интеграция с CI/CD (Continuous Integration / Continuous Deployment)

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

## Дополнительная информация

### Поддерживаемые версии

Список поддерживаемых версий Kubernetes и образов узлов доступен в разделе **[Версии Kubernetes](./kind_concepts.md#поддерживаемые-версии-kubernetes)**.

### Ссылки

- [kind — определения и концепции](./kind_concepts.md)
- [kind — конфигурация](./kind_configuration.md)
- [Официальная документация](https://kind.sigs.k8s.io/)
