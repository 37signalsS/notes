# vCluster

## Определения

**vCluster** — это инструмент для создания легковесных виртуальных Kubernetes-кластеров, работающих внутри отдельных namespace'ов хостового кластера. Каждый vCluster имеет собственный Control Plane (API Server, Controller Manager, Scheduler, etcd) и полностью изолирован от других vCluster.

## Основные концепции

### Архитектура

- **Host Cluster** — физический Kubernetes-кластер, на котором запускаются vCluster
- **vCluster** — виртуальный кластер, работающий внутри namespace'а host-кластера
- **Control Plane** — компоненты vCluster (API Server, etcd, CoreDNS), работающие как поды внутри namespace'а
- **Sync Back Controller** — компонент, синхронизирующий ресурсы между vCluster и host-кластером
- **etcd** — встроенная база данных для хранения состояния vCluster
- **CoreDNS** — DNS-сервер внутри vCluster

### Матрица совместимости

| Host Cluster | vCluster K8s |
|--------------|--------------|
| 1.30+ | 1.30, 1.31, 1.32, 1.33 |

**Обозначения:**
- Официально протестировано (100%)
- OK — предполагается работа, официально не протестировано

### Варианты развёртывания Control Plane

- **Kubernetes (vanilla)** — полный K8s API
- **K3s** — облегчённый дистрибутив
- **K0s** — минималистичный дистрибутив

### Варианты Backing Store

- **etcd** — встроенный etcd (рекомендуется для production)
- **Database** — внешняя БД (Enterprise)

## Варианты использования

### Разработка Kubernetes-контроллеров

vCluster особенно полезен при разработке Custom Resource Definition (CRD):
- Каждая команда может иметь свой vCluster с собственной версией CRD
- Полная изоляция CRD между командами
- Быстрое создание/удаление кластеров без затрат на отдельные VM

### Изоляция окружений

- Dev/Stage/Prod в рамках одного host-кластера
- Изоляция лучше, чем namespace (собственный API Server, RBAC, CRD)
- Быстрое развёртывание (секунды вместо часов)

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

### Ingress для доступа к API vCluster

Для доступа к Kubernetes API vCluster используется Ingress controller host-кластера:

```yaml
# values.yaml
controlPlane:
  ingress:
    enabled: true
    host: "vcluster1.example.com"
  proxy:
    extraSANs:
      - "vcluster1.example.com"
      - "192.168.1.100"
```

**Требования к Ingress Controller:**
- Для сквозного SSL требуется настройка пропуска HTTPS-трафика

### Получение kubeconfig

После развёртывания vCluster kubeconfig создаётся в Secret:

```bash
# Получить kubeconfig
kubectl get secret -n <vcluster-namespace> <vcluster-name> -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

# Использовать
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
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
