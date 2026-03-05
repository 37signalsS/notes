# vCluster — Установка и развертывание

## 1. Установка vCluster CLI

### macOS (Homebrew)

```bash
brew install loft-sh/vcluster/vcluster
```

### Linux

```bash
curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64"
sudo install -c -m 0755 vcluster /usr/local/bin
```

### Windows (Chocolatey)

```bash
choco install vcluster
```

### Проверка установки

```bash
vcluster --version
```

---

## 2. Развертывание vCluster

### Базовая команда

```bash
vcluster create my-vcluster -n my-namespace
```

### С указанием версии Kubernetes

```bash
vcluster create my-vcluster -n my-namespace \
  --kubernetes-version 1.31.0
```

### С использованием K3s

```bash
vcluster create my-vcluster -n my-namespace \
  --distro k3s
```

### С кастомными values

```bash
vcluster create my-vcluster -n my-namespace \
  -f values.yaml
```

### Пример values.yaml

```yaml
# values.yaml
controlPlane:
  statefulSet:
    scheduling:
      podManagementPolicy: Parallel
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 2Gi

syncer:
  extraArgs:
    - --service-account=my-vcluster-sa
```

---

## 3. Удаление vCluster

### Через vCluster CLI

```bash
vcluster delete my-vcluster -n my-namespace
```

### Вручную

```bash
# Удаление Helm релиза
helm uninstall my-vcluster -n my-namespace

# Удаление namespace
kubectl delete namespace my-namespace
```

---

## 4. Связанные документы

- **[Обзор и архитектура](./vcluster_overview.md)** — базовые определения
- **[Подключение и доступ](./vcluster_connectivity.md)** — kubeconfig, Ingress, Storage
- **[Безопасность и синхронизация](./vcluster_security_and_sync.md)** — ResourceQuota, синхронизация ресурсов
