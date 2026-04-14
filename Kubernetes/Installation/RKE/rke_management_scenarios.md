# RKE: Управление и troubleshooting

## Определения

**troubleshooting** — процесс диагностики и устранения проблем в работе Kubernetes-кластера.

**ротация сертификатов** — периодическая замена TLS-сертификатов компонентов кластера для поддержания безопасности.

**ServiceAccount** — объект Kubernetes для аутентификации процессов в кластере (используется в CI/CD).

## Базовые концепции

### Компоненты RKE для управления

* **RKE CLI** — утилита для развертывания и управления кластером через YAML-конфигурацию
* **kubectl** — стандартный инструмент управления Kubernetes
* **Rancher UI** — веб-интерфейс для визуального управления
* **Cattle Cluster Agent** — агент на узлах кластера, передающий информацию в Rancher Server

### Жизненный цикл сертификатов

* Сертификаты RKE действительны 1 год
* Автоматическая ротация через Rancher UI
* Ручная ротация при истечении срока действия

## Практические сценарии

### Базовые операции kubectl

**Статус узлов:**

```bash
kubectl get nodes -o wide
```

**Описание узла:**

```bash
kubectl describe node worker-1
```

**Список подов:**

```bash
kubectl get pods --all-namespaces
kubectl get pods -n kube-system  # Системные поды
```

**Создание deployment:**

```bash
kubectl create deployment nginx --image=nginx:1.27
kubectl expose deployment nginx --port=80 --type=NodePort
```

**Просмотр логов:**

```bash
kubectl logs -f <pod-name> -n <namespace>
kubectl logs -f <pod-name> -c <container-name>  # Многоконтейнерный под
```

**Масштабирование:**

```bash
kubectl scale deployment nginx --replicas=3
```

**Обновление приложений:**

```bash
kubectl set image deployment/nginx nginx=nginx:1.28
kubectl rollout status deployment/nginx
kubectl rollout history deployment/nginx
```

### RKE через CLI

**Установка RKE CLI:**

```bash
# Linux
curl -L https://github.com/rancher/rke/releases/download/v1.6.0/rke_linux-amd64 -o rke
chmod +x rke
sudo mv rke /usr/local/bin/

# Проверка
rke --version
```

**Создание cluster.yml:**

```yaml
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
    s3:
      access_key: <S3_ACCESS_KEY>
      secret_key: <S3_SECRET_KEY>
      bucket_name: rke-backups
      endpoint: s3.amazonaws.com

ssh_key_path: ~/.ssh/id_rsa
```

**Развертывание кластера:**

```bash
rke up --config cluster.yml
```

**Получение kubeconfig:**

```bash
# После rke up создается файл kube_config_cluster.yml
export KUBECONFIG=$(pwd)/kube_config_cluster.yml
kubectl get nodes
```

**Обновление кластера:**

```bash
rke up --config cluster.yml --upgrade
```

**Удаление кластера:**

```bash
rke remove --config cluster.yml
```

### Troubleshooting

**Проблема: Certificate expired**

```bash
# Проверка
kubectl get nodes
# Ошибка: x509: certificate has expired or is not yet valid

# Решение через Rancher UI:
# Cluster Management → ⋮ → Rotate Certificates

# Решение через RKE CLI:
rke cert rotate --config cluster.yml
```

**Проблема: Connection refused**

```bash
# Проверка доступности API
curl -k https://<rke-api-ip>:6443/healthz

# Проверка firewall
telnet <rke-api-ip> 6443
nc -zv <rke-api-ip> 6443

# Проверка сервиса kube-apiserver
kubectl get pods -n kube-system | grep apiserver
```

**Проблема: Unauthorized**

```bash
# Проверка токена в kubeconfig
kubectl config view --raw -o jsonpath='{.users[0].user.token}'

# Перегенерация токена через Rancher:
# Users & Authentication → API Keys → Create Key
```

**Проблема: Node NotReady**

```bash
# Проверка статуса узла
kubectl describe node <node-name>

# Проверка kubelet
systemctl status kubelet
journalctl -u kubelet -f

# Проверка сетегого плагина
kubectl get pods -n kube-system | grep -E 'calico|cilium|flannel'
```

**Проблема: etcd кворум потерян**

```bash
# Проверка членов etcd
kubectl get pods -n kube-system | grep etcd

# Восстановление из snapshot (RKE CLI):
rke etcd snapshot-restore --name <snapshot-name> --config cluster.yml
```

### Безопасность

**Хранение kubeconfig:**

```bash
chmod 600 ~/.kube/config
chown $USER:$USER ~/.kube/config
```

**Создание ServiceAccount для CI/CD:**

```yaml
# service-account.yml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-cd-deployer
  namespace: default
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ci-cd-deployer-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
  - kind: ServiceAccount
    name: ci-cd-deployer
    namespace: default
```

```bash
kubectl apply -f service-account.yml

# Получение токена
kubectl create token ci-cd-deployer -n default
```

### Интеграция с CI/CD

**GitLab CI:**

```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:latest
  variables:
    KUBE_CONFIG: $RKE_KUBECONFIG  # Base64 encoded
    KUBECONFIG: /tmp/kubeconfig
  script:
    - echo $KUBE_CONFIG | base64 -d > $KUBECONFIG
    - chmod 600 $KUBECONFIG
    - kubectl apply -f k8s/
```

**GitHub Actions:**

```yaml
- name: Set up kubeconfig
  run: |
    mkdir -p ~/.kube
    echo "${{ secrets.RKE_KUBECONFIG }}" | base64 -d > ~/.kube/config
    chmod 600 ~/.kube/config

- name: Deploy to RKE
  run: kubectl apply -f k8s/
```

## Дополнительная информация

**Полезные команды для диагностики:**

```bash
# Проверка событий кластера
kubectl get events --all-namespaces --sort-by='.lastTimestamp'

# Проверка ресурсов узла
kubectl top nodes
kubectl top pods --all-namespaces

# Проверка persistent volumes
kubectl get pv,pvc --all-namespaces
```

**См. также:** [RKE: Основные концепции](./rke_concepts.md), [RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md), [kubeadm: Быстрый старт](../kubeadm/index.md).
