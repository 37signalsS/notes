# vCluster — Безопасность и синхронизация

## 1. Безопасность: ResourceQuota и LimitRange

### Ограничение ресурсов vCluster

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

**Важно:** При накладывании квот учитывайте ресурсы Control Plane vCluster:

- etcd: ~100-200MB RAM, 100m CPU
- API Server: ~200-300MB RAM, 200m CPU
- CoreDNS: ~50MB RAM, 50m CPU
- Syncer: ~100MB RAM, 100m CPU

---

## 2. Безопасность: Rootless Mode

### Запуск без привилегий суперпользователя

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

---

## 3. Синхронизация ресурсов

### Sync to Host (из vCluster в Host)

Ресурсы, синхронизируемые по умолчанию:

- Pods
- Services
- Endpoints
- Secrets
- ConfigMaps
- PersistentVolumeClaims
- Ingresses (требует включения)

### Sync from Host (из Host в vCluster)

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
      # Выбор узлов по лейблам
      selector:
        matchLabels:
          vcluster-ready: "true"
    persistentVolumes:
      enabled: true
```

---

## 4. Лучшие практики

1. **Изолируйте по командам** — один vCluster на команду
2. **Настройте квоты** — ResourceQuota для контроля ресурсов
3. **Мониторьте Control Plane** — метрики самого vCluster
4. **Используйте Helm** — для управления конфигурацией
5. **Backup etcd** — для production-кластеров

---

## 5. Ограничения

- **Ресурсы на кластер** — ~500MB-1GB RAM на каждый vCluster
- **Сетевая сложность** — требуется настройка Network Policies
- **Не все ресурсы синхронизируются** — некоторые CRD требуют Enterprise

---

## 6. Связанные документы

- **[Обзор и архитектура](./vcluster_overview.md)** — базовые определения
- **[Установка и развертывание](./vcluster_installation.md)** — установка CLI и создание vCluster
- **[Подключение и доступ](./vcluster_connectivity.md)** — kubeconfig, Ingress, Storage
- **[Namespaces](../Base/namespace.md)** — основы namespace'ов
- **[RBAC](../Security/rbac/rbac_overview.md)** — управление доступом

### Репозиторий и документация

- [GitHub: loft-sh/vcluster](https://github.com/loft-sh/vcluster)
- [Официальная документация](https://www.vcluster.com/docs)
- [Helm Chart](https://github.com/loft-sh/vcluster/tree/main/chart)
