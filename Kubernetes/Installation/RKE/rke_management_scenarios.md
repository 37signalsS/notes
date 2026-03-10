# RKE: Управление и troubleshooting

## 1. Управление через kubectl

### Базовые операции

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

### Масштабирование

```bash
kubectl scale deployment nginx --replicas=3
```

### Обновление приложений

```bash
kubectl set image deployment/nginx nginx=nginx:1.28
kubectl rollout status deployment/nginx
```

## 2. RKE через CLI (альтернатива Rancher UI)

### Установка RKE CLI

```bash
# Linux
curl -L https://github.com/rancher/rke/releases/download/v1.6.0/rke_linux-amd64 -o rke
chmod +x rke
sudo mv rke /usr/local/bin/
```

### Создание cluster.yml

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

### Развертывание

```bash
rke up --config cluster.yml
```

### Получение kubeconfig

```bash
# После rke up создается файл kube_config_cluster.yml
export KUBECONFIG=$(pwd)/kube_config_cluster.yml
kubectl get nodes
```

## 3. Troubleshooting

### Проблема: Certificate expired

```bash
# Проверка сертификатов
kubectl get nodes
# Ошибка: x509: certificate has expired or is not yet valid

# Решение через Rancher UI:
# Cluster Management → ⋮ → Rotate Certificates
```

### Проблема: Connection refused

```bash
# Проверка доступности API
curl -k https://<rke-api-ip>:6443/healthz

# Проверка firewall
telnet <rke-api-ip> 6443
```

### Проблема: Unauthorized

```bash
# Проверка токена в kubeconfig
kubectl config view --raw -o jsonpath='{.users[0].user.token}'

# Перегенерация токена через Rancher:
# Users & Authentication → API Keys → Create Key
```

## 4. Безопасность

### Хранение kubeconfig

```bash
chmod 600 ~/.kube/config
chown $USER:$USER ~/.kube/config
```

### Ограничение прав

- Использовать ServiceAccount с минимальными правами
- Избегать использования admin.conf в production

### Ротация сертификатов

- RKE: автоматическая (1 год)
- Через Rancher: `Cluster Management` → `Rotate Certificates`

## 5. Интеграция с CI/CD

### GitLab CI пример

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

### GitHub Actions пример

```yaml
- name: Set up kubeconfig
  run: |
    mkdir -p ~/.kube
    echo "${{ secrets.RKE_KUBECONFIG }}" | base64 -d > ~/.kube/config
    chmod 600 ~/.kube/config

- name: Deploy to RKE
  run: kubectl apply -f k8s/
```

## Связанные документы

- **[RKE: Основные концепции](./rke_concepts.md)** — определения и архитектура
- **[RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)** — установка и kubeconfig
- **[kubeadm: Быстрый старт](../kubeadm/ha_keepalived_haproxy/index.md)** — альтернативный метод установки

## Внешние ресурсы

- **Rancher Documentation:** [ranchermanager.docs.rancher.com](https://ranchermanager.docs.rancher.com/)
- **RKE GitHub:** [github.com/rancher/rke](https://github.com/rancher/rke)
- **kubectl Reference:** [kubernetes.io/docs/reference/kubectl/](https://kubernetes.io/docs/reference/kubectl/)
