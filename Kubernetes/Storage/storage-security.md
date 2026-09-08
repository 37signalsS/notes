# Безопасность хранилища в Kubernetes

## Определения

**Storage Security** — комплекс мер по защите данных, хранящихся в персистентных томах Kubernetes, от несанкционированного доступа, утечки, порчи и ransomware-атак. Охватывает шифрование (at rest и in transit), контроль доступа (RBAC), изоляцию (Pod Security) и аудит.

**Encryption at Rest** — шифрование данных на диске. В Kubernetes реализуется на уровне СХД (Ceph dm-crypt, LUKS), CSI-драйвера (Ceph CSI encryption) или на уровне ОС (dm-crypt/LUKS на хосте).

**RBAC (Role-Based Access Control)** — механизм разграничения доступа в Kubernetes. Определяет, кто может создавать, просматривать, изменять и удалять PV/PVC/StorageClass.

**Pod Security Admission (PSA)** — механизм Kubernetes, ограничивающий привилегии подов. Влияет на storage через ограничения `hostPath`, `privileged`, `volumeTypes`.

**Immutability (Неизменяемость)** — защита снапшотов и бэкапов от удаления или модификации. В对象ных хранилищах реализуется через Object Lock (S3), в Ceph — через protected snapshots.

**Связанные темы:**
- [Pod Security Context](../Security/pod_security_context.md) — безопасность подов.
- [RBAC](../Security/rbac/) — разграничение доступа.
- [Secrets](../Base/secrets/) — управление секретами.
- [Ceph — авторизация CephX](./Ceph/Administration/operations.md) — аутентификация в Ceph.

---

## Теоретический блок

### Уровни защиты storage

| Уровень | Что защищает | Механизмы |
|:---|:---|:---|
| **Физический** | Диски, серверы | Закрытые дата-центры, шифрование дисков (LUKS/dm-crypt) |
| **СХД** | Данные на уровне массива | Репликация, erasure coding, CephX аутентификация |
| **Kubernetes** | Объекты PV/PVC/SC | RBAC, Pod Security Admission, Network Policies |
| **CSI-драйвер** | Монтирование и доступ | Шифрование томов, ограничение доступа |
| **Приложение** | Данные в работающих контейнерах | Security Context (runAsNonRoot, readOnlyRootFilesystem) |

### Угрозы storage в Kubernetes

| Угроза | Описание | Защита |
|:---|:---|:---|
| **Кража данных** | Несанкционированный доступ к PVC | RBAC, шифрование at rest, Network Policies |
| **Ransomware** | Шифрование данных выкупом | Immutability (Object Lock), air-gapped бэкапы |
| **Утечка через под** | Под с доступом к чужому PVC | Pod Security, SELinux, RBAC на уровне namespace |
| **Split-brain** | Конкурентная запись в RWO-том | RWOP, anti-affinity правила |
| **Случайное удаление** | Удаление PVC/PV с активными данными | Finalizers, ReclaimPolicy: Retain |
| **Конфигурационный сбой** | Неверный StorageClass, экспорт NFS | Admission webhooks, валидация манифестов |

---

## Практический блок

### 1. Шифрование томов (Encryption at Rest)

#### 1.1 Ceph CSI dm-crypt

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-fast
provisioner: rbd.csi.ceph.com
parameters:
  clusterID: <ceph-cluster-id>
  pool: kube
  csi.storage.k8s.io/provisioner-secret-name: ceph-secret
  csi.storage.k8s.io/provisioner-secret-namespace: default
  csi.storage.k8s.io/node-stage-secret-name: ceph-secret
  csi.storage.k8s.io/node-stage-secret-namespace: default
  encrypted: "true"                    # Включить шифрование
  encryptionKMSID: "user-managed"      # Тип KMS
reclaimPolicy: Retain
allowVolumeExpansion: true
```

#### 1.2 Шифрование на уровне хоста (LUKS)

Если CSI-драйвер не поддерживает шифрование, можно зашифровать весь диск на хосте:

```bash
# 1. Создать LUKS-контейнер на диске
cryptsetup luksFormat /dev/sdb

# 2. Открыть контейнер
cryptsetup luksOpen /dev/sdb encrypted-data

# 3. Создать PV/VG/LV
pvcreate /dev/mapper/encrypted-data
vgcreate data-vg /dev/mapper/encrypted-data
lvcreate -L 100G -n app-lv data-vg

# 4. Форматировать и смонтировать
mkfs.ext4 /dev/data-vg/app-lv
mount /dev/data-vg/app-lv /mnt/data
```

### 2. RBAC для storage-ресурсов

#### 2.1 Запрет на создание PV/SC в namespace

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: storage-viewer
  namespace: development
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["storage.k8s.io"]
  resources: ["storageclasses"]
  verbs: ["get", "list", "watch"]
# Нет verbs: create, update, delete → разработчик не может создавать PVC
```

#### 2.2 Ограничение доступа к конкретным StorageClass

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: storage-user
  namespace: production
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch", "create", "delete"]
- apiGroups: ["storage.k8s.io"]
  resources: ["storageclasses"]
  verbs: ["get", "list"]  # Только чтение — нельзя создавать/изменять SC
---
# Запрет на использование privileged StorageClass
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: storage-restricted
  namespace: development
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["create"]
  resourceNames: []  # Ограничить через admission webhook или Kyverno
```

#### 2.3 ClusterRole для администраторов storage

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: storage-admin
rules:
- apiGroups: [""]
  resources: ["persistentvolumes", "persistentvolumeclaims"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["storage.k8s.io"]
  resources: ["storageclasses", "volumeattachments", "csinodes", "csidrivers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["snapshot.storage.k8s.io"]
  resources: ["volumesnapshots", "volumesnapshotcontents", "volumesnapshotclasses"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### 3. Pod Security для storage

#### 3.1 Запрет hostPath

```yaml
apiVersion: pod-security.kubernetes.io/v1
kind: Namespace
metadata:
  name: restricted-storage
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

При `restricted` режиме:
- `hostPath` volumes запрещены
- `privileged` контейнеры запрещены
- `hostNetwork`, `hostPID`, `hostIPC` запрещены
- Все volume types кроме `configMap`, `downwardAPI`, `emptyDir`, `projected`, `secret`, `persistentVolumeClaim`

#### 3.2 Security Context для подов с PVC

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 3000
    fsGroup: 2000          # Группа для файлов в PV
    fsGroupChangePolicy: OnRootMismatch  # Изменение прав только при необходимости
  containers:
  - name: app
    image: nginx
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: data
      mountPath: /usr/share/nginx/html
      readOnly: true         # Монтирование только для чтения
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: web-data
```

### 4. Защита от случайного удаления

#### 4.1 ReclaimPolicy: Retain

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: safe-storage
provisioner: driver.longhorn.io
reclaimPolicy: Retain    # PV сохраняется после удаления PVC
allowVolumeExpansion: true
```

#### 4.2 Finalizers на PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: critical-data
  finalizers:
    - kubernetes.io/pvc-protection  # Блокирует удаление пока PVC примонтирован
```

#### 4.3 Защищённые снимки (Ceph)

```bash
# Создать защищённый снимок
rbd snap create kube/data-snap-20260901 --pool kube
rbd snap protect kube/data-snap-20260901

# Попытка удаления будет отклонена
rbd snap rm kube/data-snap-20260901
# → removing protected snapshot is not allowed

# Снять защиту (если нужно удалить)
rbd snap unprotect kube/data-snap-20260901
```

### 5. Network Policies для storage

Ограничение сетевого доступа к NFS/Ceph-серверам:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-nfs-only
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 192.168.1.100/32   # NFS-сервер
    ports:
    - protocol: TCP
      port: 2049                   # NFS
  - to:                            # DNS
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
```

### 6. Anti-ransomware: Immutability

#### 6.1 S3 Object Lock (для Velero BSL)

```bash
# Создать бакет с Object Lock (при создании)
aws s3api create-bucket \
  --bucket velero-backups-immutable \
  --object-lock-enabled-for-bucket \
  --region us-east-1

# Установить retention policy
aws s3api put-object-lock-configuration \
  --bucket velero-backups-immutable \
  --object-lock-configuration '{
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "COMPLIANCE",
        "Days": 30
      }
    }
  }'
```

#### 6.2 Velero с Immutability

```yaml
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: immutable-bsl
  namespace: velero
spec:
  provider: aws
  objectStorage:
    bucket: velero-backups-immutable
  config:
    region: us-east-1
    s3ForcePathStyle: "false"
```

---

## Дополнительная информация

### Чеклист безопасности storage

- [ ] Шифрование at rest включено для критичных томов
- [ ] RBAC настроен: разработчики не могут создавать/изменять StorageClass
- [ ] Pod Security Admission в режиме `restricted` для production namespace'ов
- [ ] ReclaimPolicy: Retain для production данных
- [ ] Finalizers на критичных PVC
- [ ] Network Policies ограничивают доступ к NFS/Ceph серверам
- [ ] Immutability включена для бэкапов (Object Lock)
- [ ] Защищённые снимки (snap protect) для критичных данных
- [ ] Аудит доступа к storage-ресурсам (Kubernetes Audit Logging)
- [ ] Регулярная проверка уязвимостей CSI-драйверов

### См. также

- [Pod Security Context](../Security/pod_security_context.md) — безопасность подов.
- [Secrets — безопасность](../Base/secrets/security.md) — хранение секретов.
- [Ceph — CephX аутентификация](./Ceph/Administration/operations.md) — аутентификация в Ceph.
- [Velero — Immutability](../ToolsUtilities/velero-overview.md) — неизменяемые бэкапы.
