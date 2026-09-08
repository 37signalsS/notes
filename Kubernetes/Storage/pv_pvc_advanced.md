# Расширенные сценарии работы с PV и PVC

## Определения

**`Binding Algorithm`** — алгоритм контроллера `pv-controller`, который связывает PersistentVolumeClaim (PVC) с подходящим PersistentVolume (PV) по совпадению StorageClassName, AccessModes, VolumeMode, размера и селектора. Процесс односторонний:一旦 PV привязан к PVC, обратная связь не происходит.

**`Best Fit`** — стратегия выбора PV из всех подходящих: контроллер выбирает PV с размером, наиболее близким к запрошенному, минимизируя потери пространства.

**`ReadWriteOncePod` (RWOP)** — расширенный режим доступа (GA в K8s 1.29), гарантирующий эксклюзивный доступ к тому на уровне конкретного пода, а не узла. Предотвращает порчу данных при split-brain сценариях.

**`Volume Expansion`** — процесс увеличения размера существующего тома без удаления PVC. Требует `allowVolumeExpansion: true` в StorageClass и поддержки CSI-драйвера.

**`Volume Attributes Class`** — объект (GA в K8s 1.34), позволяющий изменять параметры производительности тома (IOPS, пропускную способность) на лету без пересоздания диска.

**`Generic Ephemeral Volume`** — временный том с жизненным циклом пода, использующий все возможности динамического провижининга (Snapshot, Clone, VolumeAttributesClass).

**`ClaimRef`** — поле в PV, позволяющее администратору забронировать том для конкретного PVC или переносить PV между Namespace.

**`Finalizer`** — механизм защиты от случайного удаления: PVC и PV блокируют удаление, пока они связаны с активными подами.

**Смежные темы:**
- [Базовые концепции PV и PVC](./pv_and_pvc.md) — основы, режимы доступа, политики возврата.
- [Практические сценарии PV и PVC](./pv_and_pvc_scenarios.md) — YAML-манифесты для NFS, Ceph, Longhorn.
- [StorageClass](./storageclass.md) — параметры динамического провижининга и `VolumeAttributesClass`.
- [Volume Claims в StatefulSet](../Base/StatefulSet/statefulset_core_concepts.md#persistentvolumeclaim-pvc) — специфика работы с шаблонами.

---

## Основные концепции

### Алгоритм связывания PV и PVC (Binding Loop)

Kubernetes связывает PVC с PV по строгому алгоритму. Процесс выполняется контроллером `pv-controller`:

1. **StorageClassName**: PV с совпадающим классом. Если в PVC класс не указан, ищется PV без класса (или используется Default StorageClass).
2. **AccessModes**: PV должен поддерживать все режимы доступа, указанные в PVC.
3. **VolumeMode**: Совпадение `Filesystem` или `Block`.
4. **Размер**: PV должен иметь емкость не меньше запрошенной в PVC.
5. **Selector**: Если в PVC указан `selector`, PV должен иметь соответствующие метки.
6. **Best Fit**: Из всех подходящих PV выбирается тот, чей размер наиболее близок к запрошенному (минимизация потерь пространства).

#### Нюансы Best Fit
- Если PVC запрашивает 5 ГБ, а доступен только PV на 100 ГБ, PVC будет привязан к нему. Оставшиеся 95 ГБ будут фактически недоступны.
- PVC остается в статусе `Pending`, пока не появится PV, удовлетворяющий **всем** критериям.

### Режимы объема (Volume Mode)

Определяют, как том представляется внутри контейнера:

| Режим | Описание | Применение |
|---|---|---|
| **`Filesystem`** (Default) | Том монтируется как директория. K8s сам создает ФС (ext4/xfs), если её нет. | Обычные приложения, логи, конфигурации. |
| **`Block`** | Том пробрасывается как "сырое" блочное устройство (`/dev/sdb`). ФС отсутствует. | Высоконагруженные БД (Oracle, SAP), виртуализация (KubeVirt), Ceph OSD. |

### Эксклюзивный доступ (ReadWriteOncePod)

Режим доступа (GA в 1.29), обеспечивающий строгую изоляцию на уровне пода, а не узла:
- **RWO (ReadWriteOnce)**: Несколько подов на **одном узле** могут одновременно использовать том.
- **RWOP (ReadWriteOncePod)**: Только **один под во всем кластере** может монтировать том. Это предотвращает порчу данных при "split-brain" сценариях, когда старый под еще не завершился, а новый уже пытается писать в тот же диск.

### Механизмы защиты (Finalizers)

Kubernetes защищает данные от случайного удаления через финализаторы:
- `kubernetes.io/pvc-protection`: Блокирует удаление PVC, пока он примонтирован к активному поду.
- `kubernetes.io/pv-protection`: Блокирует удаление PV, пока он связан с любым PVC.
- **Политика возврата (Reclaim Policy)**: Начиная с K8s 1.33 GA, политика (Delete/Retain) соблюдается всегда, независимо от порядка удаления объектов (PV или PVC).

---

## Жизненный цикл PV и PVC

### Полный жизненный цикл PersistentVolume

```
┌─────────────────┐
│  Администратор  │
│  или CSI-       │
│  драйвер        │
└────────┬────────┘
         │ Создаёт PV (статически или динамически)
         ▼
┌─────────────────┐
│  PV Status:     │
│  Available      │──── PVC не привязан
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  pv-controller  │
│  Находит подход.│
│  PVC            │
└────────┬────────┘
         │ Связывает PVC с PV
         ▼
┌─────────────────┐
│  PV Status:     │
│  Bound          │──── PVC привязан
└────────┬────────┘
         │
         ├─── Удаление PVC ──────────────────────────────┐
         │                                                │
         │                                                ▼
         │                                    ┌─────────────────┐
         │                                    │  Reclaim Policy │
         │                                    └────────┬────────┘
         │                                             │
         │                          ┌──────────────────┼──────────────────┐
         │                          │                  │                  │
         │                          ▼                  ▼                  ▼
         │                   ┌──────────┐      ┌──────────┐      ┌──────────┐
         │                   │  Delete  │      │  Retain  │      │  Recycle │
         │                   │  (удал.  │      │  (сохр.  │      │  (очистка│
         │                   │  тома)   │      │  тома)   │      │  и осв.) │
         │                   └──────────┘      └──────────┘      └──────────┘
         │                          │                  │
         │                          ▼                  ▼
         │                   ┌──────────┐      ┌──────────┐
         │                   │   PV     │      │   PV     │
         │                   │  удалён  │      │ Released │
         │                   └──────────┘      └────┬─────┘
         │                                          │
         │                                          ▼
         │                                   ┌──────────┐
         │                                   │ Удалить  │
         │                                   │ claimRef │
         │                                   └────┬─────┘
         │                                        │
         │                                        ▼
         │                                 ┌──────────┐
         │                                 │ Available│
         │                                 │ (повтор. │
         │                                 │ 使用)    │
         │                                 └──────────┘
         │
         └─── Удаление PV ────────────────────────────────┐
                                                          │
                                                          ▼
                                               ┌─────────────────┐
                                               │  PV удалён      │
                                               │  (если Retain   │
                                               │  — том сохранён)│
                                               └─────────────────┘
```

### Статусы PV

| Статус | Описание | Когда наступает |
|--------|----------|-----------------|
| `Available` | PV доступен, не привязан к PVC | Создание или завершение Retain |
| `Bound` | PV привязан к конкретному PVC | Успешное связывание |
| `Released` | PVC удалён, но PV ещё не освобождён | Удаление PVC с Retain |
| `Failed` | Автоматическое удаление не удалось | Ошибка в СХД при Delete |

### Статусы PVC

| Статус | Описание | Когда наступает |
|--------|----------|-----------------|
| `Pending` | Ожидает связывания с PV | Нет подходящего PV или WaitForFirstConsumer |
| `Bound` | Успешно связан с PV | pv-controller нашёл подходящий PV |
| `Lost` | PV недоступен или удалён из СХД | Ошибка CSI, удаление тома администратором |

---

## Практические сценарии

### Сценарий 1: Динамическое расширение тома (Volume Expansion)

Позволяет увеличить размер диска без удаления PVC и потери данных.

```bash
# 1. Проверить текущий размер PVC
kubectl get pvc my-pvc -o jsonpath='{.spec.resources.requests.storage}'
# → 10Gi

# 2. Увеличить размер
kubectl patch pvc my-pvc -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'

# 3. Дождаться завершения расширения
kubectl get pvc my-pvc -o watch
# →等到 STATUS=Bound, не Pending

# 4. Проверить событие
kubectl describe pvc my-pvc | grep -A 5 Events
```

**Особенности расширения:**
- **Online vs Offline:** Большинство CSI-драйверов поддерживают Online-расширение (без остановки пода)
- **Восстановление после сбоя (K8s 1.34 GA):** Если расширение невозможно, можно уменьшить значение в PVC до доступного максимума без удаления тома
- **Ограничения:** Некоторые драйверы требуют перезагрузки пода или офлайн-расширения

```bash
# Проверить, поддерживает ли SC расширение
kubectl get sc -o json | jq '.items[] | {name: .metadata.name, allowExpansion: .allowVolumeExpansion}'
# → {"name":"longhorn","allowExpansion":true}

# Проверить CSI-драйвер
kubectl get csidriver
```

### Сценарий 2: Generic Ephemeral Volumes (Эфемерные PVC)

Позволяют использовать все возможности динамического провижининга (SSD, снапшоты) для временных данных с жизненным циклом пода.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: scratch-app
spec:
  securityContext:
    fsGroup: 2000
  containers:
  - name: worker
    image: alpine
    command: ["sh", "-c", "while true; do date >> /scratch/log.txt; sleep 60; done"]
    volumeMounts:
    - name: scratch-space
      mountPath: /scratch
  volumes:
  - name: scratch-space
    ephemeral:
      volumeClaimTemplate:
        spec:
          storageClassName: "longhorn"
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 20Gi
```

**Преимущества перед hostPath:**
- Использует все возможности StorageClass (WaitForFirstConsumer, snapshottable)
- Автоматическое удаление при завершении пода
- Поддержка fsGroup и securityContext

### Сценарий 3: Клонирование тома (Volume Cloning)

Создание независимой копии существующего тома в том же Namespace.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: clone-of-production-db
spec:
  storageClassName: longhorn
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 50Gi
  dataSource:
    name: production-db-pvc
    kind: PersistentVolumeClaim
```

```bash
# Проверить статус клонирования
kubectl get pvc clone-of-production-db -o watch
# →等到 STATUS=Bound

# Проверить, что размер >= оригинала
kubectl get pvc clone-of-production-db -o jsonpath='{.spec.resources.requests.storage}'
```

**Особенности:**
- Размер нового тома должен быть **>=** оригинала
- Данные копируются при первом обращении (copy-on-write) или полностью (зависит от CSI)
- Используйте для создания тестовых сред из production

### Сценарий 4: Восстановление из снимка (Volume Snapshot Restore)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-from-snapshot
spec:
  storageClassName: longhorn
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 50Gi
  dataSource:
    name: prod-snapshot-2026-08-06
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

```bash
# Проверить доступные снимки
kubectl get volumesnapshot -o wide

# Проверить статус восстановления
kubectl get pvc restored-from-snapshot -o watch
```

### Сценарий 5: Привязка к конкретному PV (ClaimRef)

Администратор может зарезервировать PV для конкретного PVC:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: dedicated-ssd-for-db
spec:
  capacity:
    storage: 100Gi
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: longhorn
  local:
    path: /mnt/ssd1
  claimRef:
    name: production-db-pvc
    namespace: production
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - node-worker-1
```

### Сценарий 6: Передача владения PV между Namespace (Ownership Transfer)

Для перемещения PV между Namespace (миграция):

```bash
# 1. Изменить reclaimPolicy на Retain
kubectl patch pv <pv-name> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'

# 2. Удалить старый PVC
kubectl delete pvc <pvc-name> -n <old-namespace>

# 3. Проверить статус PV
kubectl get pv <pv-name>
# → STATUS: Released

# 4. Удалить claimRef
kubectl patch pv <pv-name> -p '{"spec":{"claimRef":null}}'

# 5. Проверить статус
kubectl get pv <pv-name>
# → STATUS: Available

# 6. Создайте новый PVC в целевом Namespace
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-pvc
  namespace: new-namespace
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 100Gi
  volumeName: <pv-name>
  storageClassName: longhorn
EOF
```

### Сценарий 7: Защита данных от случайного удаления (Finalizers)

```bash
# Проверить финализаторы на PVC
kubectl get pvc <name> -o jsonpath='{.metadata.finalizers}'
# → ["kubernetes.io/pvc-protection"]

# Проверить финализаторы на PV
kubectl get pv <name> -o jsonpath='{.metadata.finalizers}'
# → ["kubernetes.io/pv-protection"]

# Попытка удалить PVC, который используется подом
kubectl delete pvc <name>
# → Error: The PersistentVolumeClaim "<name>" is bound to a PersistentVolume...

# Принудительное удаление (ОПАСНО — может привести к потере данных!)
kubectl delete pvc <name> --force --grace-period=0
```

### Сценарий 8: Диагностика проблем с PV/PVC

```bash
# Полная диагностика Pending PVC
kubectl describe pvc <name>
# → Секция Events:原因

# Проверить, какие PVC используют конкретный StorageClass
kubectl get pvc --all-namespaces -o json | jq -r '.items[] | select(.spec.storageClassName=="longhorn") | "\(.metadata.namespace)/\(.metadata.name)"'

# Проверить PVC без StorageClass (используют Default)
kubectl get pvc --all-namespaces -o json | jq -r '.items[] | select(.spec.storageClassName==null) | "\(.metadata.namespace)/\(.metadata.name)"'

# Проверить PV в статусе Released
kubectl get pv -o json | jq '.items[] | select(.status.phase=="Released") | {name: .metadata.name, capacity: .spec.capacity.storage, claimRef: .spec.claimRef}'

# Проверить PVC в статусе Lost
kubectl get pvc --all-namespaces | grep Lost

# Проверить финализаторы на всех PVC
kubectl get pvc --all-namespaces -o json | jq '.items[] | select(.metadata.finalizers != null) | {namespace: .metadata.namespace, name: .metadata.name, finalizers: .metadata.finalizers}'

# Проверить события ошибок
kubectl get events --field-selector reason=ProvisioningFailed
kubectl get events --field-selector reason=ProvisioningSucceeded

# Проверить CSI-драйвер
kubectl get pods -n <csi-namespace> -o wide

# Проверить лимиты
kubectl get resourcequota -n <namespace>
```

---

## Диагностика и Troubleshooting

### Диагностические команды

```bash
# Проверить PVC
kubectl get pvc --all-namespaces
kubectl describe pvc <name> -n <namespace>

# Проверить PV
kubectl get pv
kubectl describe pv <name>

# Проверить StorageClass
kubectl get storageclass
kubectl describe storageclass <name>

# Проверить CSI-драйвер
kubectl get csidriver
kubectl get pods -n <csi-namespace>

# Проверить события
kubectl get events --field-selector reason=ProvisioningFailed
kubectl get events --field-selector reason=ProvisioningSucceeded

# Проверить финализаторы
kubectl get pvc -o json | jq '.items[] | select(.metadata.finalizers != null) | {name: .metadata.name, ns: .metadata.namespace, finalizers: .metadata.finalizers}'

# Проверить лимиты
kubectl get resourcequota -n <namespace>
```

### Типичные проблемы

| Состояние PVC | Вероятная причина | Действие |
|---|---|---|
| `Pending` (no PV) | Нет подходящих PV и не работает SC. | `kubectl describe pvc`, проверьте наличие `StorageClass`. |
| `Pending` (WaitForFirstConsumer) | Под не назначен на узел. | Проверьте статус пода. Возможно, он не может быть запланирован из-за ресурсов или Taints. |
| `Bound` но под не может записать | fsGroup не установлен или permissions. | Добавьте `securityContext.fsGroup` в под. |
| `Terminating` | Используется подом или активен финализатор. | Проверьте `kubectl get pod --all-namespaces` на предмет использования PVC. |
| `Lost` | PV недоступен или удалён из СХД. | Проверьте CSI-драйвер, логи, статус тома в СХД. |
| `WaitingForCondition` (Resize) | Расширение требует перезагрузки пода или ограничено драйвером. | Перезапустите под. Проверьте события: `kubectl describe pvc`. |
| `Released` | PVC удалён, но PV не освобождён. | Удалите claimRef: `kubectl patch pv <name> -p '{"spec":{"claimRef":null}}'`. |
| `Multi-Attach error` | RWO-том примонтирован к нескольким узлам. | Дождитесь завершения detach, используйте `WaitForFirstConsumer`. |
| `VolumeExpansion` завис | Файловая система не поддерживает онлайн-расширение. | Перезапустите под для офлайн-расширения. |

### Безопасность storage

**RBAC для управления PV/PVC:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: storage-admin
  namespace: production
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: storage-admin-binding
  namespace: production
subjects:
- kind: User
  name: admin@example.com
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: storage-admin
  apiGroup: rbac.authorization.k8s.io
```

**Защита данных:**
- Всегда используйте `reclaimPolicy: Retain` для production данных
- Настройте backup через VolumeSnapshot
- Используйте `ReadWriteOncePod` для критичных БД
- Не удаляйте PVC через `--force --grace-period=0` без проверки

---

## Дополнительная информация

- [Persistent Volumes и PVC](./pv_and_pvc.md) — базовые концепции, lifecycle, roles
- [Практические сценарии PV и PVC](./pv_and_pvc_scenarios.md) — YAML-манифесты
- [StorageClass](./storageclass.md) — параметры динамического провижининга
- [CSI Advanced — снимки, клонирование, топология](./CSI/csi_advanced.md)
- [Longhorn](./longhorn.md) — установка и настройка
- [Local Path Provisioner](./local-path-provisioner.md) — локальный провижинер
- [Официальная документация: Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)
- [Официальная документация: Generic Ephemeral Volumes](https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/#generic-ephemeral-volumes)
- [Официальная документация: Volume Snapshots](https://kubernetes.io/docs/concepts/storage/volume-snapshots/)
