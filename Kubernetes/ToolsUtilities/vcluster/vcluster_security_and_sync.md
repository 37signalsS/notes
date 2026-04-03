# vCluster — Безопасность и синхронизация

## Definitions

**ResourceQuota** — Kubernetes-ресурс, ограничивающий суммарное потребление ресурсов (CPU, память, количество объектов) внутри namespace vCluster.

**LimitRange** — Kubernetes-ресурс, задающий значения по умолчанию и ограничения для CPU/памяти отдельных подов и контейнеров.

**Rootless Mode** — режим запуска контейнеров vCluster без привилегий root (не-root пользователь), повышающий безопасность.

**Syncer** — компонент vCluster, отвечающий за двустороннюю синхронизацию ресурсов между виртуальным и хостовым кластером.

## Basic Concepts

### Направления синхронизации

| Направление | Описание | Ресурсы |
| :--- | :--- | :--- |
| **toHost** (vCluster → Host) | Экспорт рабочих нагрузок в host-кластер | Pods, Services, Endpoints, Secrets, ConfigMaps, PVC, Ingresses |
| **fromHost** (Host → vCluster) | Импорт инфраструктуры host-кластера | StorageClasses, IngressClasses, Nodes, PersistentVolumes |

### Ресурсы, синхронизируемые по умолчанию

Pods, Services, Endpoints, Secrets, ConfigMaps, PersistentVolumeClaims синхронизируются автоматически. Ingresses, StorageClasses, IngressClasses требуют явного включения в `values.yaml`.

### Потребление ресурсов Control Plane

При настройке ResourceQuota необходимо учитывать ресурсы самого vCluster:

| Компонент | CPU | Memory |
| :--- | :--- | :--- |
| etcd | 100m | 100–200Mi |
| API Server | 200m | 200–300Mi |
| CoreDNS | 50m | ~50Mi |
| Syncer | 100m | ~100Mi |

## Practical Scenarios

### Настройка ResourceQuota и LimitRange

```yaml
# values.yaml
policies:
  resourceQuota:
    hard:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "20"
      services: "10"
      secrets: "50"
      configmaps: "50"
  limitRange:
    default:
      memory: 512Mi
      cpu: 500m
    defaultRequest:
      memory: 256Mi
      cpu: 250m
```

### Запуск в Rootless Mode

```yaml
# values.yaml
controlPlane:
  statefulSet:
    security:
      runAsUser: 10000
      runAsGroup: 10000
      fsGroup: 10000
      runAsNonRoot: true
```

### Синхронизация ресурсов из host-кластера

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
    ingressClasses:
      enabled: true
    nodes:
      enabled: true
      selector:
        matchLabels:
          vcluster-ready: "true"
    persistentVolumes:
      enabled: true
```

## Additional Information

### Лучшие практики

1. Изолируйте по командам — один vCluster на команду.
2. Настраивайте квоты — ResourceQuota для контроля ресурсов.
3. Мониторьте Control Plane — метрики самого vCluster.
4. Используйте Helm — для управления конфигурацией.
5. Backup etcd — для production-кластеров.

### Ограничения

- **Ресурсы на кластер** — ~500MB–1GB RAM на каждый vCluster.
- **Сетевая сложность** — требуется настройка Network Policies.
- **Не все ресурсы синхронизируются** — некоторые CRD требуют Enterprise.

Подробная документация: [официальная документация vCluster](https://www.vcluster.com/docs), [репозиторий GitHub](https://github.com/loft-sh/vcluster). Обзор и архитектура: [vcluster_overview.md](./vcluster_overview.md). Установка и развертывание: [vcluster_installation.md](./vcluster_installation.md). Подключение и доступ: [vcluster_connectivity.md](./vcluster_connectivity.md). Основы namespace'ов: [namespace.md](../Base/namespace.md). Управление доступом: [rbac_overview.md](../Security/rbac/rbac_overview.md).
