# Практические сценарии использования PV и PVC

## Определения

**`PersistentVolume (PV)`** — объект Kubernetes, представляющий абстракцию над физическим хранилищем (NFS, iSCSI, Ceph, Longhorn, локальный диск). Создаётся администратором (статическое) или автоматически через StorageClass (динамическое). Связан с PVC через `claimRef`.

**`PersistentVolumeClaim (PVC)`** — запрос пользователя на выделение хранилища определённого размера и типа. Kubernetes автоматически связывает PVC с подходящим PV (binding) или создаёт новый PV через provisioner.

**`StorageClass`** — определяет параметры хранилища (provisioner, тип диска, режим привязки, политику возврата). Каждый StorageClass имеет unique имя и привязан к конкретному provisioner.

**`Reclaim Policy (reclaimPolicy)`** — определяет судьбу PV после удаления PVC: `Delete` (удаляется вместе с данными) или `Retain` (данные сохраняются, PV требует ручной очистки). Поведение зависит от версии Kubernetes (K8s 1.33+ GA).

**`Access Mode`** — режим доступа к тому: `ReadWriteOnce` (RWO) — один узел на запись; `ReadOnlyMany` (ROX) — много узлов на чтение; `ReadWriteMany` (RWX) — много узлов на запись; `ReadWriteOncePod` (RWOP) — один под на запись (GA в K8s 1.29).

**`volumeMode`** — режим представления тома: `Filesystem` (монтируется как директория) или `Block` (пробрасывается какraw блочное устройство `/dev/sdX`).

**`ClaimRef`** — ссылка внутри PV на конкретный PVC. Позволяет зарезервировать PV для определённого PVC или привязать его вручную. Используется для static provisioning и миграции данных.

**`Generic Ephemeral Volume`** — эфемерный том, жизненный цикл которого привязан к поду. Удаляется вместе с подом. Используется для временных данных, требующих SSD или большого объёма.

**`VolumeSnapshot`** — снимок состояния PVC в момент времени. Требует наличия VolumeSnapshotClass и поддержки CSI-драйвером. Используется для бэкапов и клонирования.

**`volumeBindingMode`** — режим привязки StorageClass: `Immediate` (PV создаётся сразу) или `WaitForFirstConsumer` (PV создаётся после назначения пода на узел). Критично для топологии и локальных дисков.

### Связанные концепции

- **Теория и жизненный цикл:** [Persistent Volumes и PVC](./pv_and_pvc.md)
- **Продвинутые механизмы (Binding, RWOP, ClaimRef):** [Расширенные сценарии](./pv_pvc_advanced.md)
- **Настройка классов:** [StorageClass](./storageclass.md)
- **CSI-драйверы:** [Сравнение CSI](./CSI/csi_drivers_comparison.md) | [CSI Advanced](./CSI/csi_advanced.md)

---

## 1. Динамическое выделение (CSI / On-premise)

Самый распространённый сценарий: PVC автоматически создаёт PV через provisioner (Longhorn, Ceph RBD, NFS CSI, Local Path Provisioner).

### Сценарий 1.1: Блочное хранилище (Longhorn / Ceph RBD)

Подходит для баз данных (PostgreSQL, MongoDB), где требуется высокая производительность и режим `ReadWriteOnce` (RWO).

```yaml
# 1. StorageClass для блочного хранилища (Longhorn)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  fsType: ext4
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
---
# 2. PVC (создаёт разработчик)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc-ssd
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 20Gi
---
# 3. Использование в Поде
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
- **Расширение:** Убедитесь, что `allowVolumeExpansion: true` — это позволит увеличивать тома без пересоздания.
- **Примечание:** Для AWS EBS/Azure Disk/GCP PD замените provisioner и параметры StorageClass (подробнее в [CSI сравнение](./CSI/csi_drivers_comparison.md)).

---

## 2. Сетевое хранилище (Shared Storage)

Используется для общих файлов, медиа-контента или статики веб-серверов. Поддерживает `ReadWriteMany` (RWX) — доступ с нескольких узлов одновременно.

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

**Примечание:** Для динамического NFS-провижинирования используйте [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md) или современный [NFS CSI Driver](./CSI/csi_drivers_comparison.md).

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

## 3. Raw Block Volume (Блочный режим)

Используется для приложений, работающих напрямую с блочными устройствами: базы данных (PostgreSQL, MySQL), Ceph, Velero, виртуальные машины.

### Сценарий 3.1: Raw Block Volume с Ceph RBD

```yaml
# 1. StorageClass для блочного режима
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ceph-block
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: kubernetes
  csi.storage.k8s.io/provisioner-secret-name: csi-rbd-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
  csi.storage.k8s.io/node-stage-secret-name: csi-rbd-secret
  csi.storage.k8s.io/node-stage-secret-namespace: default
reclaimPolicy: Delete
allowVolumeExpansion: true
---
# 2. PVC с volumeMode: Block
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: block-pvc
spec:
  accessModes:
    - ReadWriteOnce
  volumeMode: Block
  storageClassName: ceph-block
  resources:
    requests:
      storage: 50Gi
---
# 3. Под с блочным томом
apiVersion: v1
kind: Pod
metadata:
  name: block-app
spec:
  containers:
  - name: app
    image: alpine
    command: ["sh", "-c", "ls -la /dev/block && dd if=/dev/block of=/dev/null bs=1M count=10"]
    volumeMounts:
    - name: block-volume
      mountPath: /dev/block
  volumes:
  - name: block-volume
    persistentVolumeClaim:
      claimName: block-pvc
```

**Важные особенности:**
- **Нет файловой системы:** Raw Block Volume не форматируется — приложение само управляет данными.
- **Не расширяется:** `allowVolumeExpansion` не поддерживается для `volumeMode: Block`.
- **Монтирование:** Том пробрасывается как `/dev/sdX` в контейнер. Проверьте права доступа (обычно требуется `privileged: true` или capabilities).
- **CSI-драйвер:** Не все драйверы поддерживают блочный режим. Проверьте в [CSI сравнение](./CSI/csi_drivers_comparison.md).

---

## 4. Локальное хранилище (Local Persistent Volumes)

Используется для задач с экстремальными требованиями к I/O (NVMe) или когда внешняя СХД отсутствует.

### Сценарий 4.1: Статический Local PV
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

*Примечание: Для автоматизации этого процесса используйте [Local Path Provisioner](./local-path-provisioner.md).*

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

## 5. Stateful-приложения (StatefulSet)

Основной способ развертывания баз данных и брокеров сообщений.

### Сценарий 5.1: Автоматические тома через volumeClaimTemplates

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

### Сценарий 5.2: Масштабирование StatefulSet

```bash
# Увеличение количества реплик
kubectl scale statefulset redis --replicas=5

# Проверка PVC (новые PVC создаются автоматически)
kubectl get pvc -l app=redis

# Уменьшение (PVC НЕ удаляются автоматически!)
kubectl scale statefulset redis --replicas=2
# PVC redis-data-redis-3 и redis-data-redis-4 останутся
```

**Удаление лишних PVC вручную:**
```bash
kubectl delete pvc redis-data-redis-3 redis-data-redis-4
```

### Сценарий 5.3: Бэкап данных StatefulSet

**Вариант A: Ручной бэкап через копирование PVC:**
```bash
# 1. Остановить под (если возможно)
kubectl scale statefulset redis --replicas=0

# 2. Создать бэкап PVC через VolumeSnapshot (если CSI поддерживает)
kubectl create -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: redis-snapshot-$(date +%Y%m%d)
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: redis-data-redis-0
EOF

# 3. Вернуть поды
kubectl scale statefulset redis --replicas=3
```

**Вариант B: CronJob для автоматического бэкапа (через Velero):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: redis-backup
spec:
  schedule: "0 2 * * *"  # Каждый день в 02:00
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: velero/velero:v1.15.0
            command: ["velero", "backup", "create", "redis-$(date +%Y%m%d)", "--include-namespaces", "default", "--selector", "app=redis"]
          restartPolicy: OnFailure
```

### Сценарий 5.4: Persistent Volume Retention Policy (K8s 1.32+)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain    # PVC сохраняются при удалении StatefulSet
    whenScaled: Delete     # PVC удаляются при уменьшении replicas
  volumeClaimTemplates:
  - metadata:
      name: pgdata
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "fast-ssd"
      resources:
        requests:
          storage: 50Gi
```

---

## 6. Продвинутые операции (Snapshots & Cloning)

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

## 7. Эфемерное хранилище (Generic Ephemeral Volumes)

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

### Диагностика проблем с PV/PVC

```bash
# 1. Проверить статус PVC
kubectl get pvc -A
kubectl describe pvc <name> -n <namespace>

# 2. Проверить статус PV
kubectl get pv
kubectl describe pv <name>

# 3. Проверить события (самый быстрый способ найти причин)
kubectl get events -n <namespace> --field-selector reason=FailedBinding

# 4. Проверить StorageClass
kubectl get sc
kubectl describe sc <name>

# 5. Проверить CSI-драйвер
kubectl get csidrivers
kubectl get pods -n kube-system | grep csi

# 6. Проверить VolumeSnapshot
kubectl get volumesnapshots -A
kubectl get volumesnapshotcontents
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `PersistentVolumeClaim is not bound` | PVC не может найти подходящий PV | Проверьте `storageClassName`, `accessModes`, размер PVC vs PV |
| `ProvisioningFailed` | CSI-драйвер не может создать PV | Проверьте логи CSI-подов: `kubectl logs -n kube-system csi-provisioner-xxx` |
| `Waiting for a volume to be created` | SC `WaitForFirstConsumer` ждёт под | Запустите под с PVC — PV создастся после scheduling |
| `Multi-Attach error` | RWO PVC подключён к нескольким узлам | Убедитесь, что под мигрирует на один узел. Для RWX используйте NFS/CephFS |
| `Unable to attach or mount` | Узел не может подключить диск | Проверьте availability zone, quota, права доступа CSI |
| `The volume has been recently resized` | Слишком частое расширение | Подождите 6 часов между расширениями (ограничение K8s) |
| `VolumeExpansionNotSupported` | StorageClass не поддерживает расширение | Обновите SC: `allowVolumeExpansion: true` (создайте новый SC) |
| `FailedMount` | Ошибка монтирования ФС | Проверьте тип ФС, права, compatibility с volumeMode |

### Изменение размера тома (Expansion)
Если `StorageClass` поддерживает `allowVolumeExpansion: true`:
1. Увеличьте `storage` в PVC манифесте.
2. Примените: `kubectl apply -f pvc.yaml`.
3. Дождитесь события `FileSystemResizePending` и убедитесь, что под запущен (некоторые ФС требуют монтирования для расширения).

**Восстановление при ошибке расширения (K8s 1.34+ GA):**
```bash
# Если расширение застряло в ошибке
kubectl patch volumeattachment <name> --type merge -p '{"metadata":{"annotations":{"volume.kubernetes.io/resizer":"true"}}}'
```

### Проблемы с правами доступа (Permissions)
Если под не может писать в том:
- Используйте `fsGroup` в `securityContext`:
```yaml
spec:
  securityContext:
    fsGroup: 2000
    fsGroupChangePolicy: "OnRootMismatch"  # Оптимизация для больших томов
```
- Kubernetes автоматически выполнит `chown -R` при монтировании (для RWO томов).
- Для `RunAsNonRoot` укажите `runAsUser` совместимый с правами на томе.

### Диагностика Pending PVC
```bash
# 1. Посмотреть события
kubectl describe pvc <name>

# 2. Проверить StorageClass
kubectl get sc

# 3. Проверить шедулинг пода (если SC имеет WaitForFirstConsumer)
kubectl describe pod <name>

# 4. Проверить квоты namespace
kubectl get resourcequota -n <namespace>

# 5. Проверить limиты CPU/Memory
kubectl describe node <node-name> | grep -A 5 "Allocated resources"
```

---

## Безопасность

### RBAC для PV/PVC

```yaml
# Запрет пользователям создавать PVC в определённом namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pvc-restricted
  namespace: production
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch"]
  # Без "create", "update", "delete" — пользователь не сможет создавать PVC
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pvc-restricted-binding
  namespace: production
subjects:
- kind: Group
  name: devs
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pvc-restricted
  apiGroup: rbac.authorization.k8s.io
```

### NetworkPolicy для изоляции Storage

```yaml
# Запретить доступ к NFS-серверу除了 из определённых подов
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: nfs-isolation
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: database
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 192.168.1.100/32  # NFS-сервер
    ports:
    - protocol: TCP
      port: 2049
```

### Шифрование данных (dm-crypt)

Для критичных данных используйте шифрование на уровне тома:
```bash
# Создать зашифрованный Secret для Longhorn
kubectl create secret generic longhorn-encryption \
  --from-literal=CIPHER=aes-xts-plain64 \
  --from-literal=KEY=$(dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64) \
  -n longhorn-system
```

---

## Производительность

### Факторы, влияющие на производительность

| Фактор | Влияние | Рекомендация |
| :--- | :--- | :--- |
| **Тип диска** | NVMe >> SSD >> HDD | Используйте NVMe для баз данных |
| **Файловая система** | ext4 vs xfs vs zfs | ext4 для маленьких томов, xfs для больших |
| **replicationFactor** | 1x vs 3x | 3x = 3x записи, но отказоустойчивость |
| **Размер I/O** | Маленькие блоки = больше overhead | Используйте aligned I/O (4K блоки) |
| **Режим доступа** | RWO < RWX | RWO быстрее (нет network overhead) |

### Оптимизация mountOptions

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: optimized-ssd
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "1"          # Для dev/test — 1x replicate
  staleReplicaTimeout: "2880"
mountOptions:
  - noatime                      # Отключить обновление atime
  - nodiratime                   # Отключить обновление diratime
  - data=writeback               # Быстрее запись, но риск при crash
reclaimPolicy: Delete
allowVolumeExpansion: true
```

### Мониторинг производительности

```bash
# Проверить использование диска
kubectl exec -it <pod> -- df -h /data

# Проверить I/O через /proc/diskstats
kubectl exec -it <pod> -- cat /proc/diskstats

# Метрики Longhorn (если установлен)
kubectl port-forward -n longhorn-system svc/longhorn-manager 9500:9500
curl http://localhost:9500/metrics | grep longhorn_volume
```

---

## Дополнительная информация

- [Persistent Volumes и PVC (теория)](./pv_and_pvc.md) — жизненный цикл, binding, reclaim.
- [Расширенные сценарии (ClaimRef, RWOP, Transfer)](./pv_pvc_advanced.md).
- [StorageClass — настройка классов хранения](./storageclass.md).
- [Local Path Provisioner](./local-path-provisioner.md) — легковесный локальный провижинер.
- [CSI Drivers — сравнение и эксплуатация](./CSI/csi_drivers_comparison.md).
- [CSI Advanced — снимки, топология, шифрование](./CSI/csi_advanced.md).
- [Troubleshooting PVC](../Troubleshooting/Common_Errors/CreateContainerConfigError/pvc_issues.md).
- [Ceph RBD — блочное хранилище](./Ceph/ceph_rbd_usage/definitions_and_concepts.md).
