# Управление кластером RKE через kubectl

## 1. Определения

**RKE (Rancher Kubernetes Engine)** — дистрибутив Kubernetes от Rancher Labs, предназначенный для развертывания production-кластеров на bare-metal и виртуальных машинах.

**Rancher** — платформа управления Kubernetes, предоставляющая веб-UI для развертывания, мониторинга и управления кластерами (включая RKE).

**kubeconfig** — YAML-файл с конфигурацией доступа к Kubernetes API (контексты, пользователи, кластеры).

> **Примечание:** RKE2 (Rancher Government Kubernetes) — следующая версия RKE с улучшенной безопасностью. Не путать с RKE1.

## 2. Основные концепции

### Отличия RKE от kubeadm

| Аспект | kubeadm | RKE |
| :--- | :--- | :--- |
| **Установка** | Команды `kubeadm init/join` на узлах | Через `cluster.yml` + `./rke up` |
| **Конфигурация** | Ручная на каждом узле | Декларативная (YAML) |
| **Управление** | kubectl + kubeadm | Rancher UI + kubectl |
| **kubectl на узлах** | Устанавливается автоматически | Не устанавливается (только через Rancher) |
| **HA** | Ручная настройка | Встроенная поддержка |

### Архитектура доступа

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────┐
│   kubectl   │ ───► │  kubeconfig  │ ───► │  RKE API Server │
│  (локально) │      │ (~/.kube/)   │      │   (порт 6443)   │
└─────────────┘      └──────────────┘      └─────────────────┘
                                                    │
                                  ┌─────────────────┼─────────────────┐
                                  │                 │                 │
                         ┌────────▼───────┐ ┌──────▼──────┐ ┌───────▼──────┐
                         │  Control Plane │ │ Worker Node │ │ Worker Node  │
                         │    (etcd+API)  │ │             │ │              │
                         └────────────────┘ └─────────────┘ └──────────────┘
```

## 3. Практические сценарии

### 3.1. Установка kubectl

**Linux (AMD64):**

```bash
# Скачивание актуальной версии
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

# Проверка контрольной суммы (опционально)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check

# Установка исполняемого файла
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Проверка
kubectl version --client
```

**macOS (Homebrew):**

```bash
brew install kubectl
kubectl version --client
```

**Windows (PowerShell):**

```powershell
curl.exe -LO "https://dl.k8s.io/release/v1.31.0/bin/windows/amd64/kubectl.exe"
```

> **Важно:** Версия kubectl должна совпадать с версией кластера (допускается отклонение ±1 минорную версию).

### 3.2. Получение kubeconfig из Rancher UI

**Шаги:**

1. **Открыть Rancher UI** (`https://rancher.your-domain.com`)

2. **Выбрать кластер:**
   - Перейти в `Cluster Management` или `Dashboard`
   - Кликнуть на нужный RKE-кластер

3. **Получить kubeconfig:**
   - Нажать кнопку `Kubeconfig File` (верхний правый угол)
   - Или `Explore` → `⋮` → `Download KubeConfig`

4. **Сохранить локально:**

   ```bash
   mkdir -p $HOME/.kube
   nano $HOME/.kube/config  # Вставить содержимое из буфера
   chmod 600 $HOME/.kube/config
   ```

5. **Проверить доступ:**

   ```bash
   kubectl get nodes
   kubectl get pods --all-namespaces
   ```

### 3.3. Работа с несколькими контекстами

**Просмотр контекстов:**

```bash
kubectl config get-contexts
```

**Переключение контекста:**

```bash
kubectl config use-context c-m-xxxxxxxxx  # Имя из Rancher
```

**Слияние конфигураций:**

Если уже есть `~/.kube/config` (например, от kubeadm):

```bash
# Резервное копирование
cp ~/.kube/config ~/.kube/config.backup

# Установка переменной для нового файла
export KUBECONFIG=~/.kube/config:~/.kube/rke-config

# Проверка доступных контекстов
kubectl config get-contexts

# Переключение на RKE контекст
kubectl config use-context c-m-xxxxxxxxx
```

### 3.4. Управление через kubectl

**Базовые операции:**

```bash
# Статус узлов
kubectl get nodes -o wide

# Описание узла
kubectl describe node worker-1

# Список подов во всех namespace
kubectl get pods --all-namespaces

# Создание deployment
kubectl create deployment nginx --image=nginx:1.27
kubectl expose deployment nginx --port=80 --type=NodePort

# Просмотр логов
kubectl logs -f <pod-name> -n <namespace>
```

**Масштабирование:**

```bash
kubectl scale deployment nginx --replicas=3
```

**Обновление приложений:**

```bash
kubectl set image deployment/nginx nginx=nginx:1.28
kubectl rollout status deployment/nginx
```

### 3.5. RKE через CLI (альтернатива Rancher UI)

**Установка RKE CLI:**

```bash
# Linux
curl -L https://github.com/rancher/rke/releases/download/v1.6.0/rke_linux-amd64 -o rke
chmod +x rke
sudo mv rke /usr/local/bin/
```

**Создание cluster.yml:**

```yaml
# cluster.yml
nodes:
  - address: 192.168.1.10
    internal_address: 192.168.1.10
    user: root
    role: [controlplane, worker, etcd]
  - address: 192.168.1.11
    internal_address: 192.168.1.11
    user: root
    role: [worker]
  - address: 192.168.1.12
    internal_address: 192.168.1.12
    user: root
    role: [worker]

services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h

ssh_key_path: ~/.ssh/id_rsa
```

**Развертывание:**

```bash
rke up --config cluster.yml
```

**Получение kubeconfig:**

```bash
# После rke up создается файл kube_config_cluster.yml
export KUBECONFIG=$(pwd)/kube_config_cluster.yml
kubectl get nodes
```

### 3.6. Troubleshooting

**Проблема: Certificate expired**

```bash
# Проверка сертификатов
kubectl get nodes
# Ошибка: x509: certificate has expired or is not yet valid

# Решение через Rancher UI:
# Cluster Management → ⋮ → Rotate Certificates
```

**Проблема: Connection refused**

```bash
# Проверка доступности API
curl -k https://<rke-api-ip>:6443/healthz

# Проверка firewall
telnet <rke-api-ip> 6443
```

**Проблема: Unauthorized**

```bash
# Проверка токена в kubeconfig
kubectl config view --raw -o jsonpath='{.users[0].user.token}'

# Перегенерация токена через Rancher:
# Users & Authentication → API Keys → Create Key
```

## 4. Дополнительная информация

### Сравнение методов управления

| Метод | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Rancher UI** | Визуальный интерфейс, мониторинг | Требует ресурсов на Rancher |
| **kubectl** | Стандартный инструмент, скрипты | Только CLI |
| **RKE CLI** | Полная автоматизация | Меньше возможностей чем UI |
| **Terraform RKE provider** | Infrastructure as Code | Сложнее настройка |

### Безопасность

**Рекомендации:**

1. **Хранение kubeconfig:**
   ```bash
   chmod 600 ~/.kube/config
   chown $USER:$USER ~/.kube/config
   ```

2. **Ограничение прав:**
   - Использовать ServiceAccount с минимальными правами
   - Избегать использования admin.conf в production

3. **Ротация сертификатов:**
   - RKE: автоматическая (1 год)
   - Через Rancher: `Cluster Management` → `Rotate Certificates`

### Интеграция с CI/CD

**GitLab CI пример:**

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  variables:
    KUBE_CONFIG: $RKE_KUBECONFIG  # Base64 encoded
  script:
    - echo $KUBE_CONFIG | base64 -d > /tmp/kubeconfig
    - export KUBECONFIG=/tmp/kubeconfig
    - kubectl apply -f k8s/
```

**GitHub Actions пример:**

```yaml
- name: Set up kubeconfig
  run: |
    mkdir -p ~/.kube
    echo "${{ secrets.RKE_KUBECONFIG }}" | base64 -d > ~/.kube/config
    chmod 600 ~/.kube/config

- name: Deploy to RKE
  run: kubectl apply -f k8s/
```

### Связанные документы

- **[kubeadm: Быстрый старт](./kudeadm/kubeadm_quickstart.md)** — альтернативный метод установки
- **[kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)** — детали конфигурации
- **[RKE2 документация](https://docs.rke2.io/)** — следующая версия RKE

### Внешние ресурсы

- **Rancher Documentation:** [ranchermanager.docs.rancher.com](https://ranchermanager.docs.rancher.com/)
- **RKE GitHub:** [github.com/rancher/rke](https://github.com/rancher/rke)
- **kubectl Reference:** [kubernetes.io/docs/reference/kubectl/](https://kubernetes.io/docs/reference/kubectl/)
