# Практические сценарии использования PV и PVC

## Определения

В данном файле собраны практические примеры и YAML-манифесты для работы с `PersistentVolume` (PV) и `PersistentVolumeClaim` (PVC) в реальных окружениях.

- **Теория и концепции:** [Persistent Volumes и PVC](./pv_and_pvc.md).
- **Продвинутые механизмы (Binding, Mode, RWOP):** [Расширенные сценарии](./pv_pvc_advanced.md).
- **Настройка классов:** [StorageClass](./storageclass.md).

---

## 1. Динамическое выделение (CSI / Cloud)

Самый распространенный сценарий в облаках (AWS, GCP, Azure) и современных On-premise СХД.

### Сценарий 1.1: Блочное хранилище (AWS EBS / Ceph RBD)
Подходит для баз данных (PostgreSQL, MongoDB), где требуется высокая производительность и режим `ReadWriteOnce` (RWO).

```yaml
# 1. Запрос на выделение (PVC)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc-ssd
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: gp3 # В AWS или ceph-ssd
  resources:
    requests:
      storage: 20Gi
---
# 2. Использование в Поде
apiVersion: v1
kind: Pod
metadata:
  name: storage-app
spec:
  containers:
  - name: app
    image: alpine
    command: ["sh", "-c", "while true; do date >> /data/log.txt; sleep 60; done"]
    volumeMounts:
    - name: storage
      mountPath: /data
  volumes:
  - name: storage
    persistentVolumeClaim:
      claimName: data-pvc-ssd
```

**Особенности:**
- **Топология:** Если кластер растянут между AZ, используйте `volumeBindingMode: WaitForFirstConsumer` в StorageClass, чтобы диск был создан в той же зоне, что и под.
- **Шифрование:** В облачных SC можно добавить параметры шифрования (KMS).

---

## 2. Сетевое хранилище (Shared Storage)

Используется для общих файлов, медиа-контента или статики веб-серверов.

### Сценарий 2.1: Статическое выделение NFS
Администратор заранее знает параметры NFS-сервера и создает PV вручную.

```yaml
# 1. PV (создает админ)
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-static-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteMany # Позволяет многим узлам писать одновременно
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /srv/nfs/data
    server: 192.168.1.100
---
# 2. PVC (создает разработчик)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nfs-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 50Gi # Должен быть <= размеру PV
```

### Сценарий 2.2: Deployment с общим томом (RWX)
Пример масштабируемого Nginx, где все реплики видят один и тот же контент.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-cluster
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        volumeMounts:
        - name: html
          mountPath: /usr/share/nginx/html
      volumes:
      - name: html
        persistentVolumeClaim:
          claimName: nfs-pvc
```

---

## 3. Локальное хранилище (Local Persistent Volumes)

Используется для задач с экстремальными требованиями к I/O (NVMe) или когда внешняя СХД отсутствует.

### Сценарий 3.1: Статический Local PV
Требует ручного создания PV с привязкой к конкретному узлу через `nodeAffinity`.

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-ssd-pv
spec:
  capacity:
    storage: 500Gi
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  local:
    path: /mnt/disks/ssd1
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - node-worker-1
```
*Примечание: Для автоматизации этого процесса часто используют [Local Path Provisioner](./local-path-provisioner.md).*

---

## 4. Stateful-приложения (StatefulSet)

Основной способ развертывания баз данных и брокеров сообщений.

### Сценарий 4.1: Автоматические тома через volumeClaimTemplates

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
spec:
  serviceName: "redis"
  replicas: 3
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "fast-ssd"
      resources:
        requests:
          storage: 10Gi
```

**Важно:**
- **Sticky ID:** Под `redis-0` всегда будет получать PVC `redis-data-redis-0`.
- **Retention:** По умолчанию при удалении StatefulSet его PVC **сохраняются**. Это можно изменить через `.spec.persistentVolumeClaimRetentionPolicy` (GA в 1.32).

---

## 5. Продвинутые операции (Snapshots & Cloning)

### Сценарий 5.1: Клонирование существующего тома
Позволяет быстро создать копию БД для тестирования.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: clone-of-db
spec:
  storageClassName: gp3
  accessModes: [ "ReadWriteOnce" ]
  resources:
    requests:
      storage: 20Gi # Должен быть >= оригиналу
  dataSource:
    kind: PersistentVolumeClaim
    name: source-db-pvc
```

### Сценарий 5.2: Восстановление из Snapshot
Требует наличия `VolumeSnapshot` объекта.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restore-pvc
spec:
  dataSource:
    name: prod-snapshot-2026-08-06
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  resources:
    requests:
      storage: 20Gi
```

---

## 6. Эфемерное хранилище (Generic Ephemeral Volumes)

Используется для временных данных, которым нужны SSD или большой объем, но которые должны удаляться вместе с подом.

```yaml
kind: Pod
metadata:
  name: scratch-app
spec:
  containers:
  - name: worker
    image: worker-image
    volumeMounts:
    - name: temp-data
      mountPath: /scratch
  volumes:
  - name: temp-data
    ephemeral:
      volumeClaimTemplate:
        spec:
          storageClassName: "fast-ssd"
          accessModes: [ "ReadWriteOnce" ]
          resources:
            requests:
              storage: 50Gi
```

---

## Практические советы и Troubleshooting

### Изменение размера тома (Expansion)
Если `StorageClass` поддерживает `allowVolumeExpansion: true`:
1. Увеличьте `storage` в PVC манифесте.
2. Примените: `kubectl apply -f pvc.yaml`.
3. Дождитесь события `FileSystemResizePending` и убедитесь, что под запущен (некоторые ФС требуют монтирования для расширения).

### Проблемы с правами доступа (Permissions)
Если под не может писать в том:
- Используйте `fsGroup` в `securityContext`:
```yaml
spec:
  securityContext:
    fsGroup: 2000
```
- Kubernetes автоматически выполнит `chown -R` при монтировании (для RWO томов).

### Диагностика Pending PVC
```bash
# 1. Посмотреть события
kubectl describe pvc <name>

# 2. Проверить StorageClass
kubectl get sc

# 3. Проверить шедулинг пода (если SC имеет WaitForFirstConsumer)
kubectl describe pod <name>
```

---

## Дополнительная информация

- [Local Path Provisioner](./local-path-provisioner.md) — легковесный локальный провижинер.
- [Продвинутые возможности CSI](./CSI/csi_advanced.md) — детали снимков и топологии.
- [Troubleshooting PVC](../../Troubleshooting/Common_Errors/CreateContainerConfigError/pvc_issues.md).
- [VictoriaMetrics на StatefulSet](../../VictoriaMetrics/deployment/kubernetes_statefulset.md).
