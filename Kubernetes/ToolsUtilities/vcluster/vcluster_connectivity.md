# vCluster — Подключение и доступ

## Definitions

**vCluster connectivity** — совокупность методов подключения к виртуальному кластеру и настройки доступа к ресурсам host-кластера (Storage, Ingress, API). Включает механизмы получения kubeconfig, синхронизацию ресурсов и организацию внешнего доступа.

**kubeconfig vCluster** — файл конфигурации для доступа к Kubernetes API виртуального кластера. Содержит учетные данные syncer-прокси, а не прямого API Server.

## Basic Concepts

### Способы получения kubeconfig

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| `vcluster connect` | Автоматическое создание временной конфигурации | Быстрое подключение, разовые операции |
| `--export-kubeconfig` | Экспорт в файл для повторного использования | CI/CD, долгосрочный доступ |
| Secret vCluster | Прямое получение из `Secret` в host-кластере | Автоматизация, восстановление доступа |

### Синхронизация ресурсов host-кластера

vCluster может синхронизировать ресурсы в двух направлениях:

| Направление | Ресурсы | Назначение |
| :--- | :--- | :--- |
| **fromHost** | StorageClass, IngressClass | Использование инфраструктуры host-кластера |
| **toHost** | Ingress, Service, Endpoints | Публикация сервисов vCluster через host |

### Доступ к API vCluster извне

Для внешнего доступа к Kubernetes API vCluster используется Ingress controller host-кластера с поддержкой SSL passthrough, так как API Server требует TLS-соединения с клиентскими сертификатами.

## Practical Scenarios

### Подключение через vcluster CLI

```bash
# Интерактивное подключение (временный kubeconfig)
vcluster connect my-vcluster -n my-namespace

# Экспорт kubeconfig в файл
vcluster connect my-vcluster -n my-namespace \
  --export-kubeconfig > kubeconfig.yaml

# Использование экспортированного kubeconfig
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes

# Выполнение команды без экспорта
vcluster connect my-vcluster -n my-namespace -- kubectl get pods
```

### Получение kubeconfig из Secret

```bash
# kubeconfig хранится в Secret host-кластера
kubectl get secret -n <vcluster-namespace> <vcluster-name> \
  -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

### Использование StorageClass из host-кластера

**Шаг 1: Включение синхронизации StorageClass**

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

> Синхронизируются все StorageClasses хост-кластера.

**Шаг 2: Создание PVC в vCluster**

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

### Использование IngressClass из host-кластера

**Шаг 1: Включение синхронизации IngressClass**

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

**Шаг 2: Создание Ingress в vCluster**

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

### Ingress для доступа к API vCluster

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

Требования: Ingress Controller с поддержкой SSL passthrough, DNS-запись на `vcluster1.example.com`.

## Additional Information

Подробное описание структуры kubeconfig: [kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md). Обзор и архитектура vCluster: [vcluster_overview.md](./vcluster_overview.md). Установка и развертывание: [vcluster_installation.md](./vcluster_installation.md). Безопасность и синхронизация ресурсов: [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).
