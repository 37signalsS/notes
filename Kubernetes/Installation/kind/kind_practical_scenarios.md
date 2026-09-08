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

### Продвинутые команды kind

Флаги и опции, которые не описаны в базовых сценариях, но критичны для автоматизации и отладки.

**Создание кластера с ожиданием готовности:**

```bash
# --wait блокирует выполнение до готовности всех узлов и control-plane
# Таймаут задается в формате duration (например, 120s, 5m)
kind create cluster --name dev --wait 120s
# → Creating cluster "dev" ...
# →  ✓ Ensuring node image (kindest/node:v1.37.0) 🖼
# →  ✓ Preparing nodes 📦
# →  ✓ Writing configuration 📜
# →  ✓ Starting control-plane 🕹️
# →  ✓ Installing CNI 🔌
# →  ✓ Installing StorageClass 💾
# → Set kubectl context to "kind-dev"
# → You can now use your cluster with:

# Проверка: команда вернется только когда все узлы будут Ready
kubectl get nodes
# → NAME                 STATUS   ROLES           AGE   VERSION
# → kind-control-plane   Ready    control-plane   62s   v1.37.0
```

**Удаление кластера с сохранением логов (--retain):**

```bash
# --retain сохраняет логи и контейнеры кластера после удаления
# Полезно для постмортем-анализа после падения кластера
kind delete cluster --name broken-cluster --retain
# → Deleting cluster "broken-cluster" ...

# Логи сохраняются в ~/.kind/logs/ или в указанном через kind export logs месте
ls ~/.kind/logs/
# → broken-cluster/
```

**Создание кластера с конкретным именем Docker-сети:**

```bash
# kind создает Docker-сеть с именем kind по умолчанию
# --name задает имя кластера, которое также используется для имени сети
kind create cluster --name myproject
# → Docker-сеть: kind-myproject-network (автоматически)
```

**Получение информации о кластере:**

```bash
# Информация о конкретном кластере
kind get kubeconfig --name dev
# → apiVersion: v1
# → clusters:
# → - cluster:
# →     certificate-authority-data: LS0t...
# →     server: https://127.0.0.1:54321
# →   name: kind-dev

# Проверка версии kind
kind version
# → v0.32.0

# Список всех кластеров с деталями
kind get clusters
# → dev
# → staging
```

**Удаление всех кластеров:**

```bash
# Удаление всех кластеров одновременно
kind delete clusters --all
# → Deleted clusters: ["dev", "staging", "test"]

# Или через пайп (если нужно исключить определенные)
kind get clusters | grep -v "prod" | xargs -I {} kind delete cluster --name {}
```

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

Для запуска образов, которых нет в реестре, их необходимо загрузить в Container Runtime узлов. kind не может обращаться к локальному Docker-хранилищу хоста напрямую — образы должны быть явно скопированы в каждый узел.

```bash
# 1. Сборка образа
docker build -t my-app:dev .

# 2. Загрузка в кластер (все узлы получат образ)
kind load docker-image my-app:dev --name my-cluster
# → image: "my-app:dev" with ID "sha256:abc123..." not yet present on node "kind-control-plane", loading...
# → image: "my-app:dev" with ID "sha256:abc123..." not yet present on node "kind-worker", loading...
```

**Загрузка из tar-архива (когда Docker-хранилище недоступно):**

```bash
# Сохранение образа в tar-архив на хосте
docker save -o my-app.tar my-app:dev

# Загрузка из архива в кластер
kind load image-archive my-app.tar --name my-cluster
# → image: "my-app:dev" with ID "sha256:abc123..." not yet present on node "kind-control-plane", loading...
```

**Массовая загрузка нескольких образов:**

```bash
# Загрузка списка образов одним вызовом
# kind принимает несколько аргументов через пробел
kind load docker-image my-app:dev my-app-db:dev my-app-cache:dev --name my-cluster
# → image: "my-app:dev" ... loading...
# → image: "my-app-db:dev" ... loading...
# → image: "my-app-cache:dev" ... loading...

# Или через цикл (если нужно логирование каждого образа)
for image in my-app:dev my-app-db:dev my-app-cache:dev; do
  echo "Загрузка $image..."
  kind load docker-image "$image" --name my-cluster
done
```

**Загрузка с несколькими тегами одного образа:**

```bash
# Если образ имеет несколько тегов, загружайте каждый отдельно
docker tag my-app:dev my-app:latest
docker tag my-app:dev my-app:v1.0.0

kind load docker-image my-app:dev my-app:latest my-app:v1.0.0 --name my-cluster
```

**Паттерн для CI/CD (загрузка после сборки):**

```yaml
# Пример этапа в GitHub Actions / GitLab CI
- name: Build and load to kind
  run: |
    docker build -t my-app:${CI_COMMIT_SHA} .
    kind load docker-image my-app:${CI_COMMIT_SHA} --name ci-cluster
    # Образ доступен в кластере без пуша в реестр
```

**Проверка загруженных образов внутри узла:**

```bash
# Подключение к узлу и проверка через crictl
docker exec kind-control-plane crictl images
# → IMAGE              TAG                 IMAGE ID            SIZE
# → my-app             dev                 abc123def456        123MB
# → kindest/node       v1.37.0            789xyz012abc        1.2GB

# Или через kubectl (если образ используется в поде)
kubectl get pods -o jsonpath='{.items[*].spec.containers[*].image}'
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

### Управление контекстами и kubeconfig

kind автоматически настраивает kubeconfig и контекст kubectl при создании кластера. Однако при работе с несколькими кластерами или в CI/CD-среде требуется ручное управление.

**Просмотр текущего контекста:**

```bash
# Текущий активный контекст
kubectl config current-context
# → kind-dev

# Все доступные контексты (включая kind)
kubectl config get-contexts
# → CURRENT   NAME       CLUSTER      AUTHINFO         NAMESPACE
# → *         kind-dev   kind-dev     kind-dev-user    default
# →           minikube   minikube     minikube         default
```

**Экспорт kubeconfig в конкретный файл:**

```bash
# По умолчанию kubeconfig записывается в ~/.kube/config (или KUBECONFIG)
# --kubeconfig позволяет указать произвольный путь
kind export kubeconfig --name dev --kubeconfig ./kubeconfig-dev.yaml

# Проверка содержимого
kubectl --kubeconfig ./kubeconfig-dev.yaml config view
```

**Объединение kubeconfig от нескольких кластеров:**

```bash
# Если KUBECONFIG содержит несколько файлов, kubectl объединяет их
export KUBECONFIG=~/.kube/config:./kubeconfig-staging:./kubeconfig-prod

# Теперь доступны все контексты
kubectl config get-contexts
# → CURRENT   NAME              CLUSTER           AUTHINFO          NAMESPACE
# →           kind-dev          kind-dev          kind-dev-user     default
# →           kind-staging      kind-staging      kind-staging-user default
# →           kind-prod         kind-prod         kind-prod-user    default

# Переключение между контекстами
kubectl config use-context kind-staging
# → Switched to context "kind-staging".
```

**Настройка Kontext по умолчанию для конкретного кластера:**

```bash
# Установка namespace по умолчанию для контекста
kubectl config set-context --current --namespace=monitoring

# Проверка
kubectl config view --minify
# → apiVersion: v1
# → clusters:
# → - cluster:
# →     server: https://127.0.0.1:54321
# →   name: kind-dev
# → contexts:
# → - context:
# →     cluster: kind-dev
# →     namespace: monitoring
# →     user: kind-dev-user
# →   name: kind-dev
# → current-context: kind-dev
```

**Удаление контекста из kubeconfig:**

```bash
# Удаление конкретного контекста
kubectl config delete-context kind-old-cluster

# Удаление кластера из kubeconfig
kubectl config delete-cluster kind-old-cluster

# Очистка неиспользуемых user/cluster записей
kubectl config unset users.kind-old-user
kubectl config unset clusters.kind-old-cluster
```

**Безопасность kubeconfig в CI/CD:**

```yaml
# В CI/CD НЕ используйте ~/.kube/config с правами admin
# Вместо этого создайте ServiceAccount с ограниченными правами

# 1. Создание ServiceAccount
kubectl create serviceaccount ci-deployer --namespace default

# 2. Назначение RBAC-прав (только для deploy)
kubectl create rolebinding ci-deployer-binding \
  --clusterrole=edit \
  --serviceaccount=default:ci-deployer \
  --namespace=default

# 3. Генерация kubeconfig для ServiceAccount
TOKEN=$(kubectl create token ci-deployer --namespace=default --duration=1h)

kubectl config set-cluster kind-dev --server=https://127.0.0.1:54321 --insecure-skip-tls-verify=true
kubectl config set-credentials ci-deployer --token=$TOKEN
kubectl config set-context ci-deployer --cluster=kind-dev --user=ci-deployer
kubectl config use-context ci-deployer

# 4. Использование в CI/CD
kubectl --kubeconfig=ci-kubeconfig.yaml get pods
```

### Работа с несколькими кластерами kind

kind позволяет запускать несколько изолированных кластеров одновременно, что полезно для параллельного тестирования,environments или миграций.

**Создание нескольких кластеров:**

```bash
# Создание кластеров для разных целей
kind create cluster --name dev --config kind-dev.yaml
kind create cluster --name staging --config kind-staging.yaml
kind create cluster --name test-migration --config kind-test.yaml

# Проверка всех кластеров
kind get clusters
# → dev
# → staging
# → test-migration
```

**Переключение между кластерами:**

```bash
# Через kubectl context
kubectl config use-context kind-dev
kubectl get pods

kubectl config use-context kind-staging
kubectl get pods

# Через флаг --context (без смены активного контекста)
kubectl --context kind-staging get pods
kubectl --context kind-dev logs my-pod
```

**Копирование образов между кластерами:**

```bash
# Если образ уже загружен в один кластер, можно скопировать его в другой
# через docker save/load

# 1. Сохранение образа из Docker-хранилища
docker save my-app:dev -o /tmp/my-app.tar

# 2. Загрузка в другой кластер
kind load image-archive /tmp/my-app.tar --name other-cluster

# Или, если образ уже в Docker (не в kind):
kind load docker-image my-app:dev --name cluster-a
kind load docker-image my-app:dev --name cluster-b
```

**Сравнение конфигураций кластеров:**

```bash
# Экспорт конфигурации каждого кластера
kind export kubeconfig --name cluster-a --kubeconfig /tmp/kubeconfig-a.yaml
kind export kubeconfig --name cluster-b --kubeconfig /tmp/kubeconfig-b.yaml

# Сравнение
diff /tmp/kubeconfig-a.yaml /tmp/kubeconfig-b.yaml
```

**Сценарий: тестирование миграции между кластерами:**

```bash
# 1. Создание исходного кластера с данными
kind create cluster --name source --config kind-source.yaml
kubectl --context kind-source apply -f app-with-data.yaml
kubectl --context kind-source rollout status deployment/my-app

# 2. Экспорт ресурсов из исходного кластера
kubectl --context kind-source get all --all-namespaces -o yaml > resources.yaml

# 3. Создание целевого кластера
kind create cluster --name target --config kind-target.yaml

# 4. Импорт ресурсов в целевой кластер
kubectl --context kind-target apply -f resources.yaml

# 5. Проверка работоспособности
kubectl --context kind-target get pods
kubectl --context kind-target rollout status deployment/my-app

# 6. Очистка
kind delete cluster --name source
kind delete cluster --name target
```

### Сетевые сценарии в kind

**Установка Cilium вместо kindnet:**

```bash
# 1. Создание кластера без встроенного CNI
cat <<EOF | kind create cluster --name cilium --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  kubeProxyMode: "none"
nodes:
- role: control-plane
- role: worker
EOF

# 2. Установка Cilium через Helm
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium --namespace kube-system

# 3. Ожидание готовности Cilium
kubectl -n kube-system rollout status daemonset/cilium

# 4. Проверка подов
kubectl -n kube-system get pods -l k8s-app=cilium
# → NAME           READY   STATUS    RESTARTS   AGE
# → cilium-xxxxx   1/1     Running   0          60s
# → cilium-abcde   1/1     Running   0          60s
```

**Установка Calico:**

```bash
# 1. Создание кластера без CNI
cat <<EOF | kind create cluster --name calico --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
nodes:
- role: control-plane
- role: worker
EOF

# 2. Установка Calico
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/calico.yaml

# 3. Ожидание готовности
kubectl -n kube-system rollout status daemonset/calico-node

# 4. Проверка
kubectl get pods -n kube-system -l k8s-app=calico-node
```

**Настройка DNS-резолвинга между кластерами:**

```bash
# kind не поддерживает DNS-резолвинг между кластерами по умолчанию
# Для доступа к сервисам одного кластера из другого используйте
# externalName сервисы или IP-адреса Docker-сети

# Получение IP-адреса узла кластера в Docker-сети
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' kind-control-plane
# → 172.18.0.2

# Доступ из одного контейнера (или кластера) к сервису другого
# через IP Docker-сети (не рекомендуется для production)
kubectl run test --image=busybox --rm -it --restart=Never -- nslookup my-service.default.svc.cluster.local
```

**Настройка Dual-Stack (IPv4 + IPv6):**

```yaml
# kind-dual-stack.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  ipFamily: dual
  podSubnet: "10.244.0.0/16,fd00:10:244::/56"
  serviceSubnet: "10.96.0.0/12,fd00:10:96::/108"
nodes:
- role: control-plane
- role: worker
```

```bash
# Создание dual-stack кластера
kind create cluster --name dual-stack --config kind-dual-stack.yaml

# Проверка IPv6-адресов подов
kubectl get pods -o wide
# → NAME                     READY   STATUS    RESTARTS   AGE   IP           NODE
# → nginx-xxxxx-yyyyy        1/1     Running   0          30s   10.244.0.5   kind-worker
# → nginx-xxxxx-zzzzz        1/1     Running   0          30s   fd00:10:244::5   kind-worker
```

### Удаление кластера

```bash
kind delete cluster --name my-cluster
kind delete clusters --all
```

---

### Интеграция с CI/CD

kind является стандартом для интеграционных тестов в CI/CD-пайплайнах благодаря скорости запуска (30-60 секунд) и отсутствию зависимости от внешних ресурсов.

**GitHub Actions (helm/kind-action):**

```yaml
# .github/workflows/ci.yml
name: Integration Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Create kind cluster
      uses: helm/kind-action@v1
      with:
        cluster_name: ci-cluster
        version: v0.32.0
        node_image: kindest/node:v1.37.0
        wait: 120s

    - name: Load image to cluster
      run: |
        docker build -t my-app:${{ github.sha }} .
        kind load docker-image my-app:${{ github.sha }} --name ci-cluster

    - name: Deploy and test
      run: |
        kubectl apply -f k8s/
        kubectl rollout status deployment/my-app --timeout=60s
        kubectl test
```

**GitLab CI (с KindeD-in-Docker или установкой kind):**

```yaml
# .gitlab-ci.yml
stages:
  - test

integration-test:
  stage: test
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: "/certs"
  before_script:
    # Установка kind
    - curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
    - chmod +x ./kind && mv ./kind /usr/local/bin/kind
    # Установка kubectl
    - curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    - chmod +x kubectl && mv kubectl /usr/local/bin/
    # Создание кластера
    - kind create cluster --name ci --wait 120s
    - kubectl cluster-info --context kind-ci
  script:
    - docker build -t my-app:$CI_COMMIT_SHA .
    - kind load docker-image my-app:$CI_COMMIT_SHA --name ci
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/my-app --timeout=60s
    - kubectl test
  after_script:
    - kind export logs ./kind-logs --name ci || true
    - kind delete cluster --name ci || true
  artifacts:
    when: always
    paths:
      - kind-logs/
    expire_in: 3 days
```

**Jenkins (Pipeline):**

```groovy
// Jenkinsfile
pipeline {
    agent any
    stages {
        stage('Setup kind') {
            steps {
                sh '''
                    curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.32.0/kind-linux-amd64
                    chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
                    kind create cluster --name jenkins-ci --wait 120s
                '''
            }
        }
        stage('Build & Load') {
            steps {
                sh '''
                    docker build -t my-app:${BUILD_NUMBER} .
                    kind load docker-image my-app:${BUILD_NUMBER} --name jenkins-ci
                '''
            }
        }
        stage('Deploy & Test') {
            steps {
                sh '''
                    kubectl apply -f k8s/
                    kubectl rollout status deployment/my-app --timeout=60s
                    kubectl test
                '''
            }
        }
    }
    post {
        always {
            sh 'kind export logs ./kind-logs --name jenkins-ci || true'
            sh 'kind delete cluster --name jenkins-ci || true'
            archiveArtifacts artifacts: 'kind-logs/**', allowEmptyArchive: true
        }
    }
}
```

**Параллельные тесты с несколькими кластерами:**

```bash
# Создание изолированных кластеров для параллельного тестирования
# Каждый job в матрице получает уникальный кластер
kind create cluster --name test-api --wait 60s &
kind create cluster --name test-worker --wait 60s &
kind create cluster --name test-scheduler --wait 60s &
wait

# Проверка готовности всех кластеров
kubectl --context kind-test-api get nodes
kubectl --context kind-test-worker get nodes
kubectl --context kind-test-scheduler get nodes

# Запуск тестов в параллельных процессах
kubectl --context kind-test-api apply -f test-api/ &
kubectl --context kind-test-worker apply -f test-worker/ &
kubectl --context kind-test-scheduler apply -f test-scheduler/ &
wait

# Очистка после тестов
kind delete cluster --name test-api
kind delete cluster --name test-worker
kind delete cluster --name test-scheduler
```

**Кэширование образов kind в CI/CD:**

```yaml
# GitHub Actions: кэширование образов kind для ускорения запуска
- name: Cache kind images
  uses: actions/cache@v4
  with:
    path: |
      ~/.cache/kind
    key: kind-images-${{ runner.os }}-${{ hashFiles('kind-config.yaml') }}
    restore-keys: |
      kind-images-${{ runner.os }}-
```

---

### Отладка и диагностика

**Низкоуровневая проверка внутри узла:**

```bash
# Подключение к узлу
docker exec -it my-cluster-control-plane bash

# Проверка контейнеров через crictl (внутри узла)
crictl ps
crictl ps -a  # включая остановленные контейнеры
crictl pods
crictl images

# Проверка логов CNI (kindnet)
tail -f /var/log/kindnetd.log

# Проверка сетевых интерфейсов узла
ip addr show

# Проверка системы (systemd внутри узла)
systemctl status kubelet
systemctl status containerd

# Просмотр логов kubelet
journalctl -u kubelet -f --no-pager -n 50
```

**Проверка состояния containerd внутри узла:**

```bash
# Список запущенных подов через CRI API
crictl pods
# → POD ID              STATE               NAME                NAMESPACE           ATTEMPT
# → abc123def456        SANDBOX             nginx-xxxxx         default             0

# Детальная информация о поде
crictl inspectp abc123def456

# Список контейнеров
crictl ps -a
# → CONTAINER ID    IMAGE            STATE    NAME   Attempt
# → xyz789abc012    nginx:1.27       RUNNING  nginx   0

# Логи конкретного контейнера
crictl logs xyz789abc012

# Проверка скандирования образов
crictl images --v 2
```

**Экспорт логов для анализа:**

```bash
# Экспорт всех логов кластера
kind export logs ./kind-logs-directory --name my-cluster
# → Exporting logs to "./kind-logs-directory"

# Структура экспортированных логов
ls ./kind-logs-directory/
# → kind-control-plane/
# │   ├── containers/
# │   ├── pods/
# │   └── systemd/
# └── kind-worker/
#     ├── containers/
#     ├── pods/
#     └── systemd/

# Быстрый поиск ошибок в логах
grep -r "error\|Error\|ERROR\|failed\|Failed\|FAILED" ./kind-logs-directory/ | head -20
```

**Обновление kubeconfig (Internal vs External):**

```bash
# По умолчанию используется для доступа с хоста (127.0.0.1)
kind export kubeconfig --name my-cluster

# --internal используется для доступа из других Docker-контейнеров
# (например, из CI/CD-контейнера или другого контейнера в Docker-сети)
kind export kubeconfig --name my-cluster --internal
# → В kubeconfig будет IP-адрес Docker-сети вместо 127.0.0.1
```

**Диагностика проблем с сетью:**

```bash
# Проверка DNS-резолвинга внутри кластера
kubectl run dns-test --image=busybox:1.36 --rm -it --restart=Never -- nslookup kubernetes.default.svc.cluster.local
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка доступности сервиса из пода
kubectl run curl-test --image=curlimages/curl --rm -it --restart=Never -- curl -s nginx-service.default.svc.cluster.local:80

# Проверка Pod-to-Pod связности
kubectl run ping-test --image=busybox:1.36 --rm -it --restart=Never -- ping -c 3 <pod-ip>

# Проверка iptables правил (внутри узла)
docker exec kind-control-plane iptables -L KUBE-SERVICES -n | head -20
```

**Диагностика проблем с storage:**

```bash
# Проверка StorageClass
kubectl get sc
# → NAME                   PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
# → standard (default)    rancher.io/local-path   Delete          WaitForFirstConsumer   false                  5m

# Проверка PVC
kubectl get pvc
# → NAME      STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → my-pvc    Bound    pvc-abc123def456                           10Gi       RWO            standard       2m

# Проверка PV
kubectl get pv
# → NAME                                       CAPACITY   ACCESS MODES   RECLAIMPOLICY   STATUS   CLAIM                   STORAGECLASS   AGE
# → pvc-abc123def456                           10Gi       RWO            Delete          Bound    default/my-pvc          standard       2m

# Описание проблемы с PVC
kubectl describe pvc my-pvc
kubectl describe pv pvc-abc123def456
```

**Диагностика проблем с Pod Scheduling:**

```bash
# Проверка событий (почему Pod не запускается)
kubectl get events --sort-by='.lastTimestamp' --field-selector reason=FailedScheduling
# → LAST SEEN   TYPE      REASON             OBJECT                MESSAGE
# → 5s          Warning   FailedScheduling   pod/nginx-xxxxx       0/2 nodes are available: 1 Insufficient cpu, 1 node(s) had taint {node-role.kubernetes.io/control-plane: }, that the pod didn't tolerate.

# Проверка лимитов ресурсов на узлах
kubectl describe nodes | grep -A 5 "Allocated resources"
# → Allocated resources:
# →   (Total limits may be over 100 percent, i.e., overcommitted.)
# →   Resource           Requests     Limits
# →   --------           --------     ------
# →   cpu                500m (12%)   0 (0%)
# →   memory             128Mi (3%)   512Mi (16%)

# Проверка taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
# → NAME                 TAINTS
# → kind-control-plane   [node-role.kubernetes.io/control-plane:NoSchedule]
# → kind-worker          <none>
```

---

## Дополнительная информация

### Поддерживаемые версии

Список поддерживаемых версий Kubernetes и образов узлов доступен в разделе **[Версии Kubernetes](./kind_concepts.md#поддерживаемые-версии-kubernetes)**.

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура, внутреннее устройство, производительность, лучшие практики
- [kind — конфигурация кластера](./kind_configuration.md) — YAML-конфигурация, kubeadm-патчи, порты, networking, шаблоны
- [Kubeconfig: подключение к кластеру](../../Operations/kubeconfig_and_connection.md) — структура kubeconfig, управление контекстами
- [Port-forward к подам и сервисам](../../Base/Pod/pod_practical_scenarios_commands.md#проброс-портов-port-forward) — kubectl port-forward, синтаксис и ограничения
- [Local Path Provisioner](../../Storage/local-path-provisioner.md) — локальное хранилище для PVC в kind
- [Официальная документация cloud-provider-kind](https://github.com/kubernetes-sigs/cloud-provider-kind)
- [Официальная документация kind](https://kind.sigs.k8s.io/)
