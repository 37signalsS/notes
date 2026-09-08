# Persistent Volumes и Persistent Volume Claims (PV и PVC)

## Определения

**`PersistentVolume` (PV)** — ресурс кластера, представляющий собой абстракцию над физическим или сетевым хранилищем (NFS, iSCSI, облачные диски AWS EBS/GCP PD, Ceph RBD/FS, Longhorn). Имеет жизненный цикл, независимый от подов, использующих этот объем. Содержит технические параметры реализации: тип СХД, объем, пути монтирования и ID томов.

**`PersistentVolumeClaim` (PVC)** — запрос пользователя или приложения на выделение дискового пространства. Аналогично тому, как Pod потребляет ресурсы узла (CPU/RAM), PVC потребляет ресурсы PV. PVC определяет необходимый размер, режим доступа и класс хранилища. После успешного связывания с PV, PVC переходит в статус `Bound`.

**`StorageClass` (SC)** — объект, определяющий «профили» предлагаемого хранения. SC позволяет администраторам описывать различные классы (например, "fast-ssd" vs "slow-hdd") и автоматизировать создание томов через динамическое выделение.

**`Container Storage Interface` (CSI)** — стандартный интерфейс для взаимодействия Kubernetes с внешними системами хранения. Большинство современных функций (снимки, расширение, шифрование) реализуются через CSI-драйверы.

Подробнее о StorageClass: [StorageClass (классы хранения)](./storageclass.md). Расширенные возможности CSI (снимки, клонирование, топология): [Продвинутые возможности CSI](./CSI/csi_advanced.md). Практические примеры: [Практические сценарии использования PV и PVC](./pv_and_pvc_scenarios.md).

---

## Основные концепции

### Режим тома (volumeMode)

Параметр `volumeMode` определяет, как том будет представлен внутри пода:

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **`Filesystem`** | (По умолчанию). Том монтируется как файловая система в указанный путь. | Стандартные приложения, хранение файлов. |
| **`Block`** | Том предоставляется как необработанное блочное устройство (raw block device). | Базы данных, высокопроизводительные системы, требующие прямого доступа к диску. |

### Роли и ответственность

Система PV/PVC обеспечивает разделение обязанностей между администратором инфраструктуры и разработчиком приложений.

| Роль | Задача | Объекты |
|---|---|---|
| **Администратор** | Настройка физических СХД, установка CSI-драйверов, создание пулов и StorageClass. | PV, StorageClass |
| **Разработчик** | Определение потребностей приложения (объем, режим доступа) без привязки к реализации СХД. | PVC, Pod |

### Алгоритм связывания PV и PVC (Binding Loop)

Kubernetes связывает PVC с PV по строгому алгоритму:

1. **StorageClassName**: PV с совпадающим классом. Если в PVC класс не указан, ищется PV без класса (или используется Default StorageClass).
2. **AccessModes**: PV должен поддерживать все режимы доступа, указанные в PVC.
3. **VolumeMode**: Совпадение `Filesystem` или `Block`.
4. **Размер**: PV не меньше запрошенного.
5. **Best Fit**: Выбирается наименьший подходящий PV. Если PVC запрашивает 5 ГБ, а доступен только PV на 100 ГБ, PVC будет привязан к нему, и остаток места будет недоступен.
6. **Selector**: Если в PVC указан `selector`, PV должен иметь соответствующие метки.

### Режимы выделения хранилища

#### Статическое выделение (Static Provisioning)

Администратор вручную создает набор PV в кластере, ссылаясь на заранее созданные тома в СХД.

**Процесс:**
```
┌─────────────────┐
│ Администратор   │
│                 │
│ 1. Создаёт PV   │──────┐
│    (манифест)   │      │
└─────────────────┘      │
                         ▼
                  ┌─────────────────┐
                  │  Kubernetes     │
                  │  Control Plane  │
                  │                 │
                  │ 2. PV доступен  │
                  │    в кластере   │
                  └─────────────────┘
                         │
                         │ (ожидает PVC)
                         ▼
                  ┌─────────────────┐
┌─────────────────┐│  Контроллер   │
│ Разработчик     ││  Persistent   │
│                 ││  Volume       │
│ 3. Создаёт PVC  │─────► Bind     │
│    (манифест)   ││               │
└─────────────────┘│ 4. Связывание │
                   │    PV + PVC   │
                   └─────────────────┘
                            │
                            │ (Bound)
                            ▼
                   ┌─────────────────┐
                   │  Pod ссылается  │
                   │  на PVC         │
                   │                 │
                   │ 5. Том          │
                   │    монтируется  │
                   └─────────────────┘
```

#### Динамическое выделение (Dynamic Provisioning) — рекомендуемый метод

Автоматическое создание физических томов и объектов PV при появлении PVC.

**Процесс:**
```
┌─────────────────────────┐
│ Администратор           │
│                         │
│ 1. Создаёт StorageClass │──────┐
│    (provisioner +       │      │
│     параметры)          │      │
└─────────────────────────┘      │
                                 │
                                 │ (StorageClass готов)
                                 ▼
                        ┌─────────────────┐
                        │  Kubernetes     │
                        │  Control Plane  │
                        └─────────────────┘
                                 │
                                 │ (ожидает PVC)
                                 ▼
                        ┌─────────────────┐
┌───────────────────────┤  Контроллер     │
│ Разработчик           │  StorageClass   │
│                       │                 │
│ 2. Создаёт PVC        │ 3. Обнаруживает │
│    storageClassName:  │    PVC          │
│    "gold-ssd"         │                 │
└───────────────────────┤ 4. Вызывает     │
                        │    provisioner  │
                        │                 │
                        │ 5. Создаёт      │
                        │    физический   │
                        │    том (СХД API)│
                        │                 │
                        │ 6. Создаёт PV   │
                        │    (манифест)   │
                        └─────────────────┘
                                 │
                                 │ (PV создан)
                                 ▼
                        ┌─────────────────┐
                        │  Автоматическое │
                        │  связывание     │
                        │  PV + PVC       │
                        │  (Bound)        │
                        └─────────────────┘
```

### Запуск баз данных в Kubernetes (StatefulSet)

Запуск нагруженных БД в контейнерах имеет свои особенности:

- **Производительность:** Любая сетевая СХД добавляет задержки (latency). Для высоконагруженных систем (OLTP) рекомендуется использовать локальные диски через `Local Persistent Volumes` или NVMe-over-Fabric.
- **Отказоустойчивость:** Kubernetes не управляет репликацией данных внутри БД. Рекомендуется использовать **Операторы** (CloudNativePG для Postgres, VictoriaMetrics Operator), которые автоматизируют бэкапы и переключение (failover). Подробнее см. в **[Стратегиях резервного копирования Kubernetes](../Operations/backup-strategies.md)**.
- **Рекомендация:** Для критически важных БД часто выгоднее оставить базу вне K8s (Bare-metal/Managed DB), подключая приложения из кластера по сети.

---

## Внутренние механизмы

### Роль контроллеров и компонентов хранения

1. **PV Controller:** Занимается связыванием PVC с PV и следит за их жизненным циклом.
2. **CSI Sidecars:**
   - `external-provisioner`: следит за PVC и создает тома в СХД.
   - `external-attacher`: управляет привязкой томов к узлам (Attach/Detach).
   - `external-resizer`: обрабатывает запросы на расширение томов.
   - `external-health-monitor`: (v1.19+, Beta) отслеживает состояние здоровья томов на уровне СХД.
3. **Kubelet (Volume Manager):** Выполняет фактическое монтирование устройства (`mount`) и создание файловой системы на узле.
4. **Storage Capacity Tracking:** Позволяет шедулеру учитывать доступное место в СХД перед назначением пода на узел (важно для локальных томов или топологий).

### Механизмы защиты (Finalizers)

Kubernetes предотвращает случайное удаление используемых данных через `finalizers`:
- `kubernetes.io/pvc-protection`: Не дает удалить PVC, пока он используется активным подом.
- `kubernetes.io/pv-protection`: Не дает удалить PV, пока он привязан к PVC.

### Режимы доступа (accessModes)

| Режим | Описание | Типичные СХД |
|---|---|---|
| **`ReadWriteOnce` (RWO)** | Доступ на чтение/запись одному узлу. Несколько подов на одном узле могут использовать том. | AWS EBS, vSphere, iSCSI |
| **`ReadOnlyMany` (ROX)** | Доступ только на чтение многим узлам одновременно. | NFS, CephFS |
| **`ReadWriteMany` (RWX)** | Доступ на чтение/запись многим узлам одновременно. | NFS, CephFS, Longhorn |
| **`ReadWriteOncePod` (RWOP)** | **GA в 1.29**. Эксклюзивный доступ только одному поду во всем кластере. Гарантирует отсутствие коррупции при переезде пода. | Современные CSI-драйверы |

### Жизненный цикл и состояния PV

| Состояние | Описание |
|---|---|
| **`Available`** | Свободен, ждет привязки к PVC. |
| **`Bound`** | Успешно закреплен за конкретным PVC. |
| **`Released`** | PVC удален, но данные еще на месте. Том не может быть повторно использован автоматически. |
| **`Failed`** | Ошибка при автоматической очистки или удалении. |

**Важные нюансы:**
- **Status Released**: Чтобы вернуть том в `Available` вручную, нужно отредактировать PV и удалить `claimRef` из спецификации.
- **Статус v1.31+**: Поле `status.lastPhaseTransitionTime` помогает отслеживать длительность нахождения в текущем состоянии.

### Политика возврата (reclaimPolicy)

| Политика | Действие после удаления PVC | Сфера применения |
|---|---|---|
| **`Retain`** | PV переходит в `Released`. Данные на СХД сохраняются. | Production, критичные данные. |
| **`Delete`** | Объект PV удаляется, вызывается удаление тома в СХД. | Динамическое выделение, Dev/Test. |

---

## Практические сценарии

### Сценарий 1: Статическое выделение (NFS)

Администратор заранее знает параметры NFS-сервера и создаёт PV вручную:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-static-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /srv/nfs/data
    server: 192.168.1.100
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: nfs-pvc
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 50Gi
```

```bash
kubectl get pv,pvc
# → NAME                       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM
# → nfs-static-pv              100Gi      RWX            Retain           Bound    default/nfs-pvc
# → NAME                        STATUS   VOLUME         CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → nfs-pvc                     Bound    nfs-static-pv  100Gi      RWX                           5s
```

### Сценарий 2: Динамическое выделение (CSI-драйвер)

При использовании CSI-драйвера (Longhorn, Ceph, NFS provisioner) Kubernetes автоматически создаёт PV при создании PVC:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dynamic-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 20Gi
```

```bash
# После создания PVC автоматически создаётся PV
kubectl get pv,pvc
# → NAME                    CAPACITY   RECLAIM POLICY   STATUS   CLAIM               STORAGECLASS
# → pvc-8f2a1b3c-...       20Gi       Delete           Bound    default/dynamic-pvc longhorn
```

### Сценарий 3: Локальные диски (Local PV)

Для томов, привязанных к конкретному узлу, используется `nodeAffinity` и `volumeBindingMode: WaitForFirstConsumer`:

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

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-fast
provisioner: kubernetes.io/no-provisioner
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
```

**Ключевой момент:** без `WaitForFirstConsumer` диск может быть создан на узле A, а под запланирован на узел B — под не сможет примонтировать том.

### Сценарий 4: StatefulSet с volumeClaimTemplates

Автоматическое создание томов для каждого пода StatefulSet:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: "postgres"
  replicas: 3
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 50Gi
```

**Важно:**
- Под `postgres-0` всегда получает PVC `data-postgres-0` (Stable ID)
- При удалении StatefulSet его PVC **сохраняются** по умолчанию (можно изменить через `persistentVolumeClaimRetentionPolicy`)

### Сценарий 5: Расширение тома (Volume Expansion)

```bash
# 1. Проверьте, что StorageClass разрешает расширение
kubectl get sc longhorn -o yaml | grep allowVolumeExpansion
# → allowVolumeExpansion: true

# 2. Увеличьте размер PVC
kubectl patch pvc dynamic-pvc -p '{"spec":{"resources":{"requests":{"storage":"40Gi"}}}}'

# 3. Проверьте результат
kubectl get pvc dynamic-pvc
# → NAME           STATUS   VOLUME        CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → dynamic-pvc    Bound    pvc-8f2a...   40Gi       RWO            longhorn       5m

# 4. Проверьте файловую систему в поде (если под запущен)
kubectl exec <pod-name> -- df -h /data
# → /dev/longhorn/pvc-xxx  40G  1.2G  38G  3% /data
```

**Важно:** расширение возможно только вверх. Уменьшение размера тома **не поддерживается**.

### Сценарий 6: Снимки и восстановление

```yaml
# 1. Создание VolumeSnapshot
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: prod-snapshot-2026-08-06
spec:
  volumeSnapshotClassName: longhorn
  source:
    persistentVolumeClaimName: dynamic-pvc
---
# 2. Восстановление из снимка
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-pvc
spec:
  dataSource:
    name: prod-snapshot-2026-08-06
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 40Gi
```

### Сценарий 7: Клонирование тома

Создание копии существующего PVC для тестирования:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: db-clone
spec:
  dataSource:
    name: source-db-pvc
    kind: PersistentVolumeClaim
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
```

### Сценарий 8: Generic Ephemeral Volume

Временный том, привязанный к жизненному циклу пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: worker
spec:
  containers:
  - name: worker
    image: worker:latest
    volumeMounts:
    - name: scratch
      mountPath: /scratch
  volumes:
  - name: scratch
    ephemeral:
      volumeClaimTemplate:
        spec:
          storageClassName: fast-ssd
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 50Gi
```

**Отличие от `emptyDir`:** поддерживает все возможности CSI (шифрование, снимки, high-performance SSD). PVC автоматически удаляется при завершении пода.

### Сценарий 9: Топология и мультизональные кластеры

Для кластеров, растянутых между несколькими зонами доступности:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: regional-ssd
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowedTopologies:
- matchLabelExpressions:
  - key: topology.ebs.csi.aws.com/zone
    values:
    - us-east-1a
    - us-east-1b
parameters:
  type: gp3
  encrypted: "true"
```

### Топология и локальные диски (Node Affinity)

Для томов, привязанных к узлу (Local PV) или зоне (AWS EBS), используется `nodeAffinity`. При этом в StorageClass обязательно должен быть установлен `volumeBindingMode: WaitForFirstConsumer`.

### Динамическое расширение тома (Volume Expansion)

1. Убедитесь, что в `StorageClass` установлено `allowVolumeExpansion: true`.
2. Отредактируйте PVC, увеличив размер: `kubectl patch pvc <pvc-name> -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'`.
3. **RecoverVolumeExpansionFailure (v1.29+, Beta):** Позволяет откатить неудачную попытку расширения, если в СХД нет места.

### Изменение параметров тома (ModifyVolume)

В современных версиях (v1.31+, Beta) можно изменять IOPS и throughput "на лету" через объект `VolumeAttributesClass` без пересоздания диска.

### Работа со снимками и клонированием

- **Volume Snapshots**: Создание снимка PVC и последующее восстановление из него. Подробнее: [Volume Snapshots](./CSI/csi_advanced.md#api-снапшотов-томов-volume-snapshots).
- **Volume Cloning**: Создание прямой копии PVC внутри того же Namespace. Подробнее: [Volume Cloning](./CSI/csi_advanced.md#клонирование-томов-volume-cloning).

---

## Безопасность

### RBAC для storage-ресурсов

По умолчанию обычные пользователи **не могут** управлять PV (cluster-scoped ресурс). PVC доступны в рамках Namespace.

```yaml
# Разрешить создание PVC в конкретном Namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pvc-creator
  namespace: production
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["create", "get", "list", "watch"]
- apiGroups: ["storage.k8s.io"]
  resources: ["storageclasses"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pvc-creator-binding
  namespace: production
subjects:
- kind: User
  name: developer
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pvc-creator
  apiGroup: rbac.authorization.k8s.io
```

### Защита от потери данных

| Механизм | Назначение | Как активировать |
|----------|------------|------------------|
| **`reclaimPolicy: Retain`** | Сохраняет данные при удалении PVC | В StorageClass или PV |
| **Finalizers** | Блокирует удаление используемых PVC/PV | Автоматически |
| **`ReclaimPolicy: Delete` + backup** | Автоматическое удаление + резервное копирование | Настроить backup до использования Delete |
| **Volume Snapshots** | Точки восстановления | VolumeSnapshot + VolumeSnapshotClass |
| **ResourceQuota** | Лимит на количество PVC/объём хранилища | ResourceQuota в Namespace |

### Шифрование томов

```yaml
# Пример: шифрование через CSI-драйвер (AWS EBS)
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  # Для использования собственного ключа KMS:
  # kmsKeyId: arn:aws:kms:us-east-1:123456789:key/xxx
```

### Network Policies для storage-компонентов

Ограничение сетевого доступа к CSI-драйверам и storage-сервисам:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-longhorn-only
  namespace: longhorn-system
spec:
  podSelector:
    matchLabels:
      app: longhorn-manager
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: longhorn-system
```

---

## Устранение неполадок

### Диагностические команды

```bash
# Проверка состояния PVC
kubectl get pvc --all-namespaces
kubectl describe pvc <name>

# Проверка состояния PV
kubectl get pv
kubectl describe pv <name>

# Проверка StorageClass
kubectl get storageclass
kubectl describe storageclass <name>

# Логи CSI-драйвера
kubectl logs -n kube-system <csi-controller-pod>
kubectl logs -n kube-system <csi-node-pod>

# Проверка событий
kubectl get events --field-selector reason=ProvisioningFailed
```

### Типичные проблемы

| Проблема | Симптомы | Причины | Решение |
|----------|----------|---------|---------|
| **PVC в Pending** | `kubectl describe pvc` показывает `Waiting for a volume to be created` | Нет подходящего PV и не работает динамическое provisionining | Проверьте наличие StorageClass и статус provisioner |
| **PVC в Pending (AZ mismatch)** | Под не запускается, диск создан в другой зоне | `volumeBindingMode: Immediate` в мультизонном кластере | Измените на `WaitForFirstConsumer` |
| **Multi-Attach error** | Под не может примонтировать RWO-том на другом узле | Предыдущий под ещё не завершил detach | Дождитесь завершения detach или используйте `WaitForFirstConsumer` |
| **PVC в Lost** | PV удалён или недоступен | Физический диск удалён, ошибка CSI-драйвера | Проверьте CSI-драйвер и физическое хранилище |
| **Расширение тома не работает** | `kubectl describe pvc` показывает `Waiting for resize` | CSI-драйвер не поддерживает онлайн-расширение | Перезапустите под или проверьте версию CSI |
| **Недостаточно места** | ProvisioningFailed: no space | Исчерпано физическое место в СХД | Освободите место или добавьте узлы |
| **Permission denied** | Под не может писать в том | Неправильные права доступа (UID/GID) | Используйте `fsGroup` в `securityContext` пода |

### Проверка Pending PVC

```bash
# 1. Посмотреть события
kubectl describe pvc <name>
# → Events:
#   Warning  ProvisioningFailed  failed to provision volume...

# 2. Проверить StorageClass
kubectl get sc
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUMEBINDINGMODE
# → longhorn (default)   driver.longhorn.io             Delete          Immediate

# 3. Проверить, что provisioner работает
kubectl get pods -n longhorn-system
# → longhorn-manager-xxxxx   1/1     Running

# 4. Проверить лимиты ResourceQuota
kubectl get resourcequota -n <namespace>
```

### Восстановление после сбоя узла

```bash
# 1. Проверьте статус томов
kubectl get pv,pvc -o wide | grep Released
# → pvc-xxx   50Gi   Retain   Released   pvc-xxx   fast-ssd

# 2. Если PV в Released — удалите claimRef для возврата в Available
kubectl patch pv <pv-name> -p '{"spec":{"claimRef": null}}'

# 3. Дождитесь связывания с новым PVC
kubectl get pv <pv-name> -w
# → STATUS: Available → Bound
```

---

## Дополнительная информация

- Базовые концепции: [StorageClass](./storageclass.md).
- Практические примеры: [Практические сценарии PV и PVC](./pv_and_pvc_scenarios.md).
- Продвинутые механизмы: [Расширенные сценарии](./pv_pvc_advanced.md).
- Локальное хранилище: [Local Path Provisioner](./local-path-provisioner.md).
- Динамический NFS: [NFS Subdir External Provisioner](./nfs-subdir-external-provisioner.md).
- Сравнение драйверов: [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md).
- Официальная документация: [Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/).
