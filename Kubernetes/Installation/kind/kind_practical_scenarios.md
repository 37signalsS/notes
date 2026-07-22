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
| `kind create cluster` | Создание нового кластера |
| `kind get clusters` | Список существующих кластеров |
| `kind delete cluster` | Удаление кластера |
| `kind load docker-image` | Загрузка локального Docker-образа напрямую в узлы кластера |
| `kind export kubeconfig` | Экспорт или обновление файла kubeconfig для доступа к кластеру |
| `kind export logs` | Выгрузка диагностических логов узлов и компонентов кластера |

---

## Практические сценарии

### Установка kind

**Linux (amd64 — 64-разрядная архитектура x86):**

```bash
# Скачивание бинарного файла актуальной версии v0.32.0 (середина 2026 года)
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

> **Примечание:** Актуальная версия на середину 2026 года — `v0.32.0`. В новых релизах используется балансировщик **Envoy** (вместо HAProxy) для HA-кластеров. Проверяйте обновления на странице [GitHub Releases](https://github.com/kubernetes-sigs/kind/releases).

---

### Создание базового кластера

```bash
# Минимальный кластер с именем по умолчанию (kind)
kind create cluster
# → Creating cluster "kind" ...

# Создание кластера с кастомным именем
kind create cluster --name my-cluster
# → Creating cluster "my-cluster" ...

# Создание кластера с применением файла конфигурации
kind create cluster --name my-cluster --config kind-config.yaml
# → Creating cluster "my-cluster" ...
```

Пример минимального конфигурационного файла доступен в разделе **[Минимальная конфигурация](./kind_configuration.md#минимальная-конфигурация)**.

---

### HA-кластер (High Availability — высокая доступность)

Для тестирования отказоустойчивости рекомендуется использовать многоузловую конфигурацию (несколько control-plane узлов).

```bash
kind create cluster --name ha-cluster --config kind-config-ha.yaml
# → Creating cluster "ha-cluster" ...
# →  • Ensuring node image (kindest/node:v1.36.0) 🖼  ...
# →  • Preparing nodes 📦 📦 📦 📦  ...
# →  • Starting control-plane 🕹️  ...
```

Подробный пример конфигурации HA-кластера с пробросом портов доступен в разделе **[HA-кластер (multi-node)](./kind_configuration.md#высокодоступный-кластер-ha--multi-node)**.

---

### Проверка кластера

```bash
# Список всех локальных кластеров kind
kind get clusters
# → my-cluster
# → ha-cluster

# Переключение контекста kubectl на созданный кластер
kubectl config use-context kind-my-cluster
# → Switched to context "kind-my-cluster".

# Статус узлов (Ready)
kubectl get nodes
# → NAME                 STATUS   ROLES           AGE   VERSION
# → my-cluster-control-plane   Ready    control-plane   2m    v1.36.0

# Статус критических системных компонентов
kubectl get pods -n kube-system
# → NAME                                         READY   STATUS    RESTARTS   AGE
# → coredns-xxxxxxxxx-xxxxx                      1/1     Running   0          2m
# → etcd-my-cluster-control-plane                1/1     Running   0          2m
```

---

### Загрузка локальных Docker-образов

Для того чтобы Kubernetes мог запустить локально собранный образ (которого нет в публичных реестрах типа Docker Hub), его нужно загрузить напрямую в Container Runtime узлов кластера.

```bash
# 1. Сборка образа на хосте
docker build -t my-app:dev .

# 2. Загрузка образа в кластер
kind load docker-image my-app:dev --name my-cluster
# → Image: "my-app:dev" with ID "sha256:..." not yet present on node "my-cluster-control-plane", loading...

# 3. Развертывание
kubectl create deployment my-app --image=my-app:dev
# → deployment.apps/my-app created
```

**Загрузка из tar-архива (полезно для CI/CD или передачи больших образов):**

```bash
docker save -o my-app.tar my-app:dev
kind load image-archive my-app.tar --name my-cluster
# → Image: "my-app:dev" with ID "sha256:..." not yet present on node "my-cluster-control-plane", loading...
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
# → deployment.apps/nginx-deployment created
# → service/nginx-service created

kubectl get pods -l app=nginx
# → NAME                                READY   STATUS    RESTARTS   AGE
# → nginx-deployment-xxxxxxxxx-xxxxx    1/1     Running   0          1m
```

---

### Удаление кластера

```bash
# Удаление конкретного кластера
kind delete cluster --name my-cluster
# → Deleting cluster "my-cluster" ...

# Удаление всех существующих кластеров kind
kind delete clusters --all
# → Deleted clusters: ["my-cluster", "ha-cluster"]
```

---

### Интеграция с CI/CD (Continuous Integration / Continuous Deployment)

**GitHub Actions (с использованием официального Action):**

```yaml
name: CI-Kubernetes-Test
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    
    # Использование официального экшена (v1 указывает на актуальный 1.x.x релиз, например v1.14.0+)
    - name: Setup kind
      uses: helm/kind-action@v1
      with:
        cluster_name: 'ci-cluster'
        version: v0.32.0
        # Опционально: загрузка файла конфигурации для настройки узлов
        # config: kind-config.yaml 
        
    - name: Run Integration Tests
      run: |
        kubectl apply -f manifests/
        kubectl wait --for=condition=ready pod -l app=test --timeout=120s
```

**GitLab CI (использование Docker-in-Docker):**

```yaml
test_kubernetes:
  image: docker:26-dind
  services:
    - docker:26-dind
  variables:
    KIND_VERSION: "v0.32.0"
  script:
    # Установка kind
    - curl -Lo ./kind https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-amd64
    - chmod +x ./kind
    
    # Установка kubectl (для запуска манифестов)
    - apk add --no-cache kubectl
    
    # Создание кластера
    - ./kind create cluster --name gitlab-test-cluster
    
    # Деплой и тестирование
    - kubectl apply -f manifests/
    - kubectl wait --for=condition=ready pod --all -n default --timeout=300s
```

---

### Отладка и диагностика

```bash
# Просмотр логов systemd и containerd внутри узла-контейнера
docker logs kind-control-plane
# → <вывод логов systemd>

# Экспорт полной диагностики (логи kubelet, containerd, journald) из всех узлов
kind export logs ./kind-logs-directory --name my-cluster
# → Exporting logs for cluster "my-cluster" to:
# → ./kind-logs-directory

# Прямое подключение к узлу для низкоуровневой отладки (например, проверки сети через crictl или ip)
docker exec -it my-cluster-control-plane bash
# → root@my-cluster-control-plane:/#

# Принудительное обновление и экспорт kubeconfig (если файл был утерян)
kind export kubeconfig --name my-cluster
# → Set kubectl context to "kind-my-cluster"
```

---

## Дополнительная информация

### Поддерживаемые версии

Список поддерживаемых версий Kubernetes и образов узлов доступен в разделе **[Версии Kubernetes](./kind_concepts.md#поддерживаемые-версии-kubernetes)**.

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — внутреннее устройство, сеть, хранилище
- [kind — конфигурация](./kind_configuration.md) — проброс портов, multi-node кластеры, патчи containerd
- [Официальная документация kind](https://kind.sigs.k8s.io/)
