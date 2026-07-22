# Local Path Provisioner

## Определения

**Local Path Provisioner** — Kubernetes-провижинер от Rancher, позволяющий использовать локальное хранилище на узлах кластера через стандартный механизм PVC/PV. Динамически создаёт `PersistentVolume` из пути на файловой системе хоста, являясь легковесной альтернативой сложным СХД и прямому использованию `HostPath`.

## Базовые концепции

### Принцип работы

Provisioner работает как `Deployment`, отслеживающий создание PVC с указанным `StorageClass`.

**Алгоритм при создании PVC:**

1. Pod с PVC планируется на узел.
2. Provisioner запускает временный "helper" под на этом же узле.
3. Helper под выполняет `mkdir -p` для создания директории в сконфигурированном пути (например, `/opt/local-path-provisioner/<pvc-name>`).
4. Создаётся `PersistentVolume`, указывающий на эту директорию.
5. PVC связывается с PV (статус `Bound`).

**При удалении PVC:**

- Helper под выполняет `rm -rf` для очистки директории.
- PV удаляется.

**Преимущество:** Абстракция от прямого использования `HostPath`, повышенная безопасность и упрощённое управление.

### Сравнение с альтернативами

| Решение | Плюсы | Минусы | Когда использовать |
|---------|-------|--------|------------------|
| **Local Path Provisioner** | Простота, высокая производительность, стандартные PVC/PV | Данные привязаны к узлу, нет репликации, нет контроля ёмкости | Dev/Test, кэширование, временные данные |
| **HostPath** | Максимальная производительность | Небезопасно, неудобно для динамического управления | **Не рекомендуется** |
| **NFS/Сетевые ФС** | Доступ со всех узлов, `ReadWriteMany` | Производительность ограничена сетью, требуется отдельный сервер | Общие данные, RWX-требования |
| **Longhorn/Ceph** | Репликация, миграция, снимки, отказоустойчивость | Высокая сложность, нагрузка на сеть/CPU | Production, важные данные ([Longhorn](./longhorn.md)) |

### Ограничения

| Ограничение | Описание | Обход |
|-------------|----------|-------|
| **Привязка к узлу** | Том физически на одном узле. При перемещении пода доступ к данным теряется | Использовать `affinity` для жёсткой привязки подов к узлам |
| **Нет контроля ёмкости** | PVC размер игнорируется. Приложение использует всё пространство диска | Отдельные диски/разделы, квоты на уровне LVM |
| **Только RWO** | `ReadWriteMany` не поддерживается | Использовать NFS/CephFS для RWX |

### volumeBindingMode: WaitForFirstConsumer

**Критически важный параметр** для локальных хранилищ.

| Режим | Описание |
|-------|----------|
| `Immediate` | PV создаётся сразу при создании PVC (без учёта узла) |
| `WaitForFirstConsumer` | PV создаётся после планирования первого пода |

**Важно:** Для локальных хранилищ всегда используйте `WaitForFirstConsumer`. Это гарантирует, что PV будет создан на том узле, где будет работать приложение.

## Практические сценарии

### Установка

#### Способ 1: Манифест (YAML)

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.36/deploy/local-path-storage.yaml
```

#### Способ 2: Helm

```bash
helm repo add rancher https://charts.rancher.io
helm repo update
helm install local-path rancher/local-path-provisioner --namespace local-path-storage --create-namespace
```

### Конфигурация

Конфигурация осуществляется через `ConfigMap` `local-path-config` в namespace `local-path-storage`.

#### Базовая конфигурация

Все тома создаются в `/opt/local-path-provisioner` на любом узле:

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/opt/local-path-provisioner"]
    }
  ]
}
```

#### Несколько StorageClass для разных дисков

**Шаг 1:** Обновление `ConfigMap` для поддержки нескольких путей:

```json
{
  "nodePathMap": [
    {
      "node": "DEFAULT_PATH_FOR_NON_LISTED_NODES",
      "paths": ["/mnt/fast-ssd", "/mnt/slow-hdd"]
    }
  ]
}
```

**Шаг 2:** Создание соответствующих `StorageClass`:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path-ssd
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
parameters:
  hostDir: /mnt/fast-ssd
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path-hdd
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
parameters:
  hostDir: /mnt/slow-hdd
```

### Использование со StatefulSet

StatefulSet — основной сценарий использования для локальных хранилищ, требующий строгой привязки данных.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-sts-headless
spec:
  clusterIP: None
  selector:
    app: my-sts-app
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-sts
spec:
  serviceName: "my-sts-headless"
  replicas: 2
  selector:
    matchLabels:
      app: my-sts-app
  template:
    metadata:
      labels:
        app: my-sts-app
    spec:
      affinity:
        # Привязка к узлам с меткой worker=true
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: "node-role.kubernetes.io/worker"
                operator: In
                values: ["true"]
        # Распределение подов по разным узлам
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values: ["my-sts-app"]
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-path-ssd"
      resources:
        requests:
          storage: 1Gi
```

**Объяснение параметров affinity:**

| Параметр | Назначение |
|----------|------------|
| `nodeAffinity` | Привязывает поды только к узлам с меткой `worker=true` |
| `podAntiAffinity` | Запрещает размещение двух подов с меткой `app: my-sts-app` на одном узле (предотвращает конкуренцию за ресурсы узла) |

## Дополнительная информация

Базовые концепции хранения: [PersistentVolume и PVC](./pv_and_pvc.md). Контроллер для stateful-приложений: [StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md). Альтернатива для RWX: [NFS Provisioner](./nfs-subdir-external-provisioner.md).

Официальный репозиторий: [rancher/local-path-provisioner](https://github.com/rancher/local-path-provisioner). Документация: [Rancher Docs](https://rancher.com/docs/).
