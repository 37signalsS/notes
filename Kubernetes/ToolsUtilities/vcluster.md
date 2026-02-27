# vCluster

## Определения

**vCluster** — это инструмент для создания легковесных виртуальных Kubernetes-кластеров, работающих внутри отдельных namespace'ов хостового кластера. Каждый vCluster имеет собственный Control Plane (API Server, Controller Manager, Scheduler, etcd) и полностью изолирован от других vCluster.

## Основные концепции

### Архитектура

- **Host Cluster** — физический Kubernetes-кластер, на котором запускаются vCluster
- **vCluster** — виртуальный кластер, работающий внутри namespace'а host-кластера
- **Control Plane** — компоненты vCluster (API Server, etcd, CoreDNS), работающие как поды внутри namespace'а
- **Sync Back Controller** — компонент, синхронизирующий ресурсы между vCluster и host-кластером

### Отличия от Namespace

| Характеристика | Namespace | vCluster |
|---------------|-----------|----------|
| Собственный API Server | Нет | Да |
| Изоляция RBAC | Ограниченная | Полная |
| Изоляция CRD | Нет | Да |
| Изоляция etcd | Нет | Да |
| Управление через kubectl | Частично | Полностью |

## Безопасность

### ResourceQuota и LimitRange

vCluster работает внутри namespace'а host-кластера. Ограничения накладываются стандартными механизмами:

```yaml
# values.yaml
policies:
  resourceQuota:
    hard:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "20"
  limitRange:
    default:
      memory: 512Mi
      cpu: 500m
    defaultRequest:
      memory: 256Mi
      cpu: 250m
```

**Важно:** При накладывании квот необходимо учитывать ресурсы, потребляемые самим Control Plane vCluster (etcd, API Server, CoreDNS).

### Rootless Mode

Запуск vCluster без привилегий суперпользователя:

```yaml
# values.yaml
controlPlane:
  statefulSet:
    security:
      runAsUser: 10000
      runAsGroup: 10000
      fsGroup: 10000
```

### Network Policy

Ограничение сетевого взаимодействия vCluster с хост-кластером:

```yaml
# values.yaml
# NetworkPolicy настраивается отдельно на уровне namespace
```

## Синхронизация ресурсов

### Sync to Host (из vCluster в Host)

Ресурсы, синхронизируемые из vCluster в хост-кластер (по умолчанию):

- Pods
- Services
- Endpoints
- Secrets
- ConfigMaps
- PersistentVolumeClaims
- Ingresses (требует настройки)

### Sync from Host (из Host в vCluster)

Ресурсы, поднимаемые из хост-кластера в vCluster:

- Nodes (по labels)
- StorageClasses
- IngressClasses
- PersistentVolumes
- ConfigMaps
- Secrets
- CustomResourceDefinitions (Enterprise)

### Пример: Синхронизация StorageClass

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

Примечание: Синхронизируются все StorageClasses хост-кластера, выборочная фильтрация недоступна.

### Пример: Синхронизация Ingress

```yaml
# values.yaml
sync:
  toHost:
    ingresses:
      enabled: true
  fromHost:
    ingressClasses:
      enabled: true
```

## Практические сценарии

### Развертывание vCluster

```bash
vcluster create my-vcluster -n my-namespace
```

### Подключение к vCluster

```bash
vcluster connect my-vcluster -n my-namespace --export-kubeconfig > kubeconfig.yaml
export KUBECONFIG=kubeconfig.yaml
kubectl get ns
```

### Использование Storage из Host-кластера

1. Синхронизировать StorageClass:
```yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

2. Создать PVC в vCluster:
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  storageClassName: managed-nfs-storage
  resources:
    requests:
      storage: 1Gi
```

### Использование Ingress из Host-кластера

1. Синхронизировать IngressClass:
```yaml
sync:
  fromHost:
    ingressClasses:
      enabled: true
```

2. Создать Ingress в vCluster:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  ingressClassName: system-ingress
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

### Удаление vCluster

```bash
helm uninstall my-vcluster -n my-namespace
kubectl delete namespace my-namespace
```

## Дополнительная информация

* **Официальная документация:** [vcluster.com](https://www.vcluster.com/)
* **Сравнение с Rancher Local Cluster:** vCluster легче, требует меньше ресурсов
* **Enterprise функции:** Синхронизация Nodes, advanced sync options
