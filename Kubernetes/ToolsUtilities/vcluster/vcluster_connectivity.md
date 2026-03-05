# vCluster — Подключение и доступ

## 1. Подключение к vCluster

### Автоматическое создание kubeconfig

```bash
vcluster connect my-vcluster -n my-namespace
```

### Экспорт kubeconfig в файл

```bash
vcluster connect my-vcluster -n my-namespace \
  --export-kubeconfig > kubeconfig.yaml

# Использование
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

### Подключение с указанием команды

```bash
vcluster connect my-vcluster -n my-namespace -- kubectl get pods
```

---

## 2. Получение kubeconfig из Secret

```bash
# kubeconfig хранится в Secret
kubectl get secret -n <vcluster-namespace> <vcluster-name> \
  -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

# Использование
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

---

## 3. Использование Storage из Host-кластера

### Шаг 1: Включение синхронизации StorageClass

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

**Примечание:** Синхронизируются все StorageClasses хост-кластера.

### Шаг 2: Создание PVC в vCluster

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  storageClassName: managed-nfs-storage  # Из host-кластера
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 1Gi
```

---

## 4. Использование Ingress из Host-кластера

### Шаг 1: Включение синхронизации IngressClass

```yaml
# values.yaml
sync:
  fromHost:
    ingressClasses:
      enabled: true
  toHost:
    ingresses:
      enabled: true
```

### Шаг 2: Создание Ingress в vCluster

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  ingressClassName: system-ingress  # Из host-кластера
  rules:
    - host: myapp.vcluster.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

---

## 5. Ingress для доступа к API vCluster

Для доступа к Kubernetes API vCluster извне через Ingress controller host-кластера:

```yaml
# values.yaml
controlPlane:
  ingress:
    enabled: true
    host: "vcluster1.example.com"
    annotations:
      nginx.ingress.kubernetes.io/ssl-passthrough: "true"
  proxy:
    extraSANs:
      - "vcluster1.example.com"
      - "192.168.1.100"
```

**Требования:**

- Ingress Controller с поддержкой SSL passthrough
- DNS запись на vcluster1.example.com

---

## 6. Связанные документы

- **[Обзор и архитектура](./vcluster_overview.md)** — базовые определения
- **[Установка и развертывание](./vcluster_installation.md)** — установка CLI и создание vCluster
- **[Безопасность и синхронизация](./vcluster_security_and_sync.md)** — ResourceQuota, синхронизация ресурсов
