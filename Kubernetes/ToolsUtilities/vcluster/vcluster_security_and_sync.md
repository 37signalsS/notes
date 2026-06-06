# vCluster — Безопасность и синхронизация

## Определения

**ResourceQuota** — Kubernetes-ресурс, ограничивающий суммарное потребление ресурсов CPU (Central Processing Unit), памяти и количество объектов внутри namespace (пространства имен) vCluster в хост-кластере.

**LimitRange** — Kubernetes-ресурс, задающий значения ресурсов по умолчанию и ограничения для отдельных подов и контейнеров внутри vCluster.

**Rootless Mode (Безрутовый режим)** — режим запуска компонентов vCluster от имени не-привилегированного пользователя, что исключает наличие прав root внутри контейнеров и повышает общую безопасность системы.

**Syncer (Синхронизатор)** — ключевой компонент vCluster, отвечающий за двустороннюю синхронизацию ресурсов (Pods, Services, PVC (PersistentVolumeClaim) и др.) между виртуальным и хостовым кластерами.

## Основные концепции

### Направления синхронизации

| Направление | Описание | Типы ресурсов |
| :--- | :--- | :--- |
| **toHost** (vCluster → Host) | Экспорт рабочих нагрузок в хост-кластер для исполнения | Pods, Services, Endpoints, Secrets, ConfigMaps, PVC, Ingresses |
| **fromHost** (Host → vCluster) | Импорт инфраструктурных объектов хост-кластера | StorageClasses, IngressClasses, Nodes, PersistentVolumes |

### Ресурсы, синхронизируемые по умолчанию

Базовые ресурсы Kubernetes (Pods, Services, Endpoints, Secrets, ConfigMaps, PersistentVolumeClaims) синхронизируются автоматически. Расширенные ресурсы (Ingresses, StorageClasses, IngressClasses) требуют явной активации в конфигурационном файле `values.yaml`.

### Потребление ресурсов Control Plane

При настройке **ResourceQuota** в хост-кластере необходимо учитывать ресурсы, потребляемые компонентами самого vCluster. Типовые запросы для дистрибутива Kubernetes (vanilla):

| Компонент | CPU Request | Memory Request |
| :--- | :--- | :--- |
| **API Server** | 200m | 256Mi |
| **etcd** | 100m | 128Mi |
| **Syncer** | 100m | 128Mi |
| **CoreDNS** | 50m | 32Mi |

Полная таблица ресурсов для различных дистрибутивов приведена в [vCluster — Обзор и архитектура](./vcluster_overview.md).

## Практические сценарии

### Настройка ResourceQuota и LimitRange

Пример ограничения ресурсов для namespace vCluster через `values.yaml`:

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

Настройка запуска от не-root пользователя (UID 10000) для повышения безопасности:

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

### Синхронизация инфраструктурных ресурсов из host-кластера

Включение импорта классов хранилищ и узлов для использования в виртуальном кластере:

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

## Дополнительная информация

### Лучшие практики

- **Изоляция:** используйте один vCluster на команду или проект для минимизации радиуса поражения.
- **Квотирование:** всегда устанавливайте ResourceQuota для предотвращения истощения ресурсов хост-кластера.
- **Безопасность:** предпочитайте Rootless Mode для всех production-инсталляций.
- **Мониторинг:** настройте сбор метрик с компонентов Control Plane и Syncer.

### Внутренние ссылки

- [vCluster — Обзор и архитектура](./vcluster_overview.md)
- [vCluster — Установка и развертывание](./vcluster_installation.md)
- [vCluster — Подключение и доступ](./vcluster_connectivity.md)
- [Основы namespace'ов](../Base/namespace.md)
- [Управление доступом (RBAC)](../Security/rbac/rbac_overview.md)

### Внешние ссылки

- [vCluster Security Documentation](https://www.vcluster.com/docs/architecture/security)
- [Syncer Resource Syncing](https://www.vcluster.com/docs/architecture/syncer)
