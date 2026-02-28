# Local Path Provisioner

## Определения

**Local Path Provisioner** — это Kubernetes-провижинер от [Rancher](https://rancher.com/), который позволяет использовать локальное хранилище на узлах кластера через стандартный механизм `PersistentVolumeClaim` (PVC) и `PersistentVolume` (PV). Он предоставляет способ динамического создания `PersistentVolume` из пути на файловой системе хоста, являясь легковесной альтернативой сложным системам хранения и прямому использованию `HostPath`.

## Основные концепции

### Принцип работы

Провижинер работает как `Deployment`, который отслеживает создание PVC с указанным `StorageClass`. Когда под, запрашивающий такой PVC, планируется на узел, провижинер:
1.  Запускает временный "helper" под на этом же узле.
2.  Этот под выполняет простую команду `mkdir -p` для создания директории в заранее сконфигурированном пути на хосте (например, `/opt/local-path-provisioner/<pvc-name>`).
3.  Создает `PersistentVolume`, который указывает на эту директорию.
4.  При удалении PVC и PV, "helper" под выполняет `rm -rf` для очистки директории.

Этот подход позволяет абстрагироваться от прямого использования `HostPath` в манифестах приложений, что повышает безопасность и упрощает управление.

### Сравнение с альтернативами

| Решение | Плюсы | Минусы |
| :--- | :--- | :--- |
| **Local Path Provisioner** | Простота, высокая производительность (прямой доступ к диску), использование стандартных PVC/PV. | Данные привязаны к узлу, нет репликации, нет контроля ёмкости. |
| **HostPath** | Максимальная производительность. | Небезопасно (можно смонтировать системные директории), неудобно для динамического управления. |
| **NFS/Сетевые ФС** | Данные доступны со всех узлов, поддерживается `ReadWriteMany`. | Производительность ограничена скоростью сети, требует отдельного сервера. |
| **Longhorn/Ceph/etc.** | Репликация, миграция данных, снимки, отказоустойчивость. | Высокая сложность, дополнительная нагрузка на сеть и CPU (особенно Longhorn, использующий iSCSI). |

### Ограничения

- **Привязка данных к узлу:** Созданный том физически находится на одном узле. Если под будет перемещен на другой узел, он потеряет доступ к своим данным. Приложения, использующие `local-path-provisioner`, должны быть жестко привязаны к своим узлам.
- **Отсутствие контроля ёмкости:** Провижинер не учитывает размер, указанный в PVC (`spec.resources.requests.storage`). Приложение сможет использовать все доступное пространство на диске хоста. Для ограничения рекомендуется использовать отдельные диски/разделы или квоты на уровне LVM.
- **`AccessMode: ReadWriteOnce` (RWO):** Так как нижележащая файловая система (ext4, xfs) не является кластерной, тома могут быть смонтированы в режиме записи только к одному поду одновременно. `ReadWriteMany` (RWX) не поддерживается.

### `volumeBindingMode: WaitForFirstConsumer`

Это ключевой параметр `StorageClass` для работы с локальными хранилищами. Он указывает Kubernetes отложить создание (`binding`) `PersistentVolume` до тех пор, пока не будет создан и запланирован на конкретный узел первый под, использующий данный `PersistentVolumeClaim`. Это гарантирует, что PV будет создан именно на том узле, где будет работать приложение.

## Практические сценарии

### Установка

Установка производится применением одного манифеста с официального [GitHub-репозитория](https://github.com/rancher/local-path-provisioner).

```bash
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.24/deploy/local-path-storage.yaml
```

### Конфигурация

Конфигурация провижинера осуществляется через `ConfigMap` `local-path-config` в неймспейсе `local-path-storage`.

#### Пример базовой конфигурации

Все тома будут создаваться в директории `/opt/local-path-provisioner` на любом узле кластера.

```json
// config.json
{
        "nodePathMap":[
           {
                   "node":"DEFAULT_PATH_FOR_NON_LISTED_NODES",
                   "path":"/opt/local-path-provisioner"
           }
        ]
}
```

#### Создание нескольких `StorageClass` для разных дисков

Можно настроить разные `StorageClass` для дисков разной производительности (например, SSD и HDD).

1.  **Обновляем `ConfigMap`:**
    ```json
    // config.json
    {
            "nodePathMap":[
               {
                       "node":"DEFAULT_PATH_FOR_NON_LISTED_NODES",
                       "paths":["/mnt/fast-ssd", "/mnt/slow-hdd"]
               }
            ]
    }
    ```

2.  **Создаем два `StorageClass`:**
    ```yaml
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
      name: local-path-ssd
    provisioner: rancher.io/local-path
    reclaimPolicy: Delete
    volumeBindingMode: WaitForFirstConsumer
    parameters:
      hostDir: /mnt/fast-ssd # Явно указываем путь
    ---
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
      name: local-path-hdd
    provisioner: rancher.io/local-path
    reclaimPolicy: Delete
    volumeBindingMode: WaitForFirstConsumer
    parameters:
      hostDir: /mnt/slow-hdd # Явно указываем путь
    ```

### Использование со `StatefulSet`

`StatefulSet` — идеальный кандидат для использования с `local-path-provisioner`, так как он требует стабильных идентификаторов и хранилища. Для корректной работы необходимо использовать правила `affinity`.

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
        # 1. Привязываем поды к узлам с определенной меткой (например, worker=true)
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: "node-role.kubernetes.io/worker"
                operator: In
                values:
                - "true"
        # 2. Гарантируем, что два пода с одинаковой меткой не окажутся на одном узле
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - my-sts-app
            topologyKey: "kubernetes.io/hostname"
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  # 3. Определяем шаблон для динамического создания PVC
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "local-path-ssd" # Используем наш быстрый StorageClass
      resources:
        requests:
          storage: 1Gi # Размер игнорируется, но его указание — хорошая практика
```

**Объяснение `affinity`:**
- `nodeAffinity` привязывает поды `StatefulSet` только к определенным узлам (в данном примере — ко всем "воркерам").
- `podAntiAffinity` с `topologyKey: "kubernetes.io/hostname"` запрещает планировщику размещать два пода с меткой `app: my-sts-app` на одном и том же узле, обеспечивая распределение реплик для отказоустойчивости.

## Дополнительная информация
- [Kubernetes: StatefulSet](../Concepts/statefulset_overview.md)
- [Kubernetes: PersistentVolume](../Concepts/persistent_volume_overview.md)
- [Kubernetes: StorageClass](../Concepts/storageclass_overview.md)

