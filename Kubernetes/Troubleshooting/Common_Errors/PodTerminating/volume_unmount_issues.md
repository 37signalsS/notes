# Pod Terminating — проблемы размонтирования томов (Volume Unmount)

## Определения

**Размонтирование тома (Volume Unmount)** — финальный этап жизненного цикла тома на узле (Node), при котором Kubelet отключает файловую систему тома от дерева каталогов хоста. Выполняется строго после остановки всех контейнеров Pod.

**Устаревшее монтирование (Stale Mount)** — состояние, при котором точка монтирования остается активной в ядре ОС или в `mount namespace` Kubelet, хотя объект Pod уже удален из API. Это блокирует удаление PVC/PV и освобождение ресурсов хранилища.

**VFS Refcount (Счётчик ссылок)** — внутренний механизм ядра Linux. `umount` завершится ошибкой `target is busy`, если хотя бы один процесс удерживает открытый дескриптор файла или рабочую директорию внутри тома.

**D-state (Uninterruptible Sleep)** — состояние процесса, ожидающего завершения ввода-вывода (I/O). Такие процессы нельзя завершить сигналом `SIGKILL`, и они блокируют `umount`, так как ядро не может закрыть их дескрипторы.

**Kubelet Volume Manager** — подсистема Kubelet (reconciliation loop), которая сверяет желаемое состояние (Desired State) из API с текущим состоянием (Actual State) на узле и инициирует операции монтирования/размонтирования.

**Подпути (Volume Subpaths)** — механизм Kubernetes для монтирования части тома. Создает дополнительные `bind mounts` в `/var/lib/kubelet/pods/<pod-uid>/volume-subpaths/`. Некорректная очистка подпутей — самая частая причина блокировки основного тома.

**Распространение монтирования (Mount Propagation)** — режимы `None`, `HostToContainer`, `Bidirectional`. При `Bidirectional` контейнер может создавать монтирования, которые "утекают" на хост и требуют ручной очистки при аварии контейнера.

**Lazy Unmount (`umount -l`)** — "ленивое" размонтирование. Немедленно удаляет точку из иерархии ФС, делая её недоступной для новых процессов, но ресурсы освобождаются только после закрытия всех существующих файловых дескрипторов.

**EBUSY (Device or Resource Busy)** — системный код ошибки ядра Linux (`errno 16`), возвращаемый системным вызовом `umount()`, когда файловая система не может быть размонтирована из-за активных ссылок (dentry, inode, или файловых дескрипторов).

**CSI NodeUnstageVolume** — метод CSI-драйвера, вызываемый Kubelet после `umount` для финальной очистки: удаление Nodal Device Map, отключение iSCSI-сессии, очистка LUKS-контейнера. Выполняется на узле в `mount namespace` Kubelet.

**Задержка размонтирования (Unmount Delay)** — промежуток времени между отправкой команды `umount` и её фактическим завершением. При сетевых сбоях (NFS, Ceph) может составлять от минут до часов из-за retry-политик ядра.

---

## Базовые концепции

### Процесс очистки томов (Cleanup Workflow)

Когда Pod переходит в `Terminating`, Kubelet следует строгому алгоритму:

1.  **Graceful Shutdown контейнеров:** Ожидание завершения процессов.
2.  **Проверка Refcount:** Volume Manager проверяет, не используется ли том другими контейнерами того же Pod.
3.  **Очистка подпутей (Recursive Unmount):** Сначала очищаются все `bind mounts` в директории `volume-subpaths`.
4.  **NodeUnmount:** Выполняется системный вызов `umount` для пути в `/var/lib/kubelet/pods/<pod-uid>/volumes/`.
5.  **CSI NodeUnstage:** Вызов метода `NodeUnstageVolume` у CSI-драйвера для финализации очистки на уровне узла (удаление устройств, закрытие LUKS).
6.  **Controller Detach:** Внешний AD-контроллер отсоединяет диск от ВМ (облачный API или локальный драйвер).

> **Отличие от отсоединения (Detach):** Размонтирование (Unmount) — это локальная операция на узле (Kubelet вызывает `umount`). Отсоединение (Detach) — это операция на уровне хранилища (CSI-драйвер вызывает `ControllerUnpublishVolume`). Сначала размонтирование, потом отсоединение. См. [Финализаторы и CSI](./finalizer_issues.md).

### Дерево решений: диагностика проблем размонтирования

```
Pod в Terminating, том не размонтируется
│
├─ Events содержат FailedUnmount?
│   ├─ ДА
│   │   ├─ lsof +D показывает процессы? → Сценарий 1: Блокировка процессами
│   │   ├─ findmnt | grep volume-subpaths показывает монтирования? → Сценарий 2: Подпути
│   │   ├─ mountinfo пуст, ошибка в mount namespace? → Сценарий 3: Mount Namespace Kubelet
│   │   ├─ Команда df/ls зависает? → Сценарий 4: Сетевые ФС (NFS/Ceph)
│   │   ├─ audit.log содержит denied { unmount }? → Сценарий 5: SELinux/AppArmor
│   │   ├─ local-path-provisioner, emptyDir, hostPath? → Сценарий 6: Локальные драйверы
│   │   └─ LUKS-encrypted том? → Сценарий 7: Шифрованные тома
│   │
│   └─ НЕТ
│       └─ Проверьте Kubelet Volume Manager: journalctl -u kubelet --grep "VolumeManager"
│
├─ Pod в Terminating, нет Events с ошибками?
│   ├─ deletionTimestamp > 0, finalizers[] не пуст? → См. [Финализаторы и CSI](./finalizer_issues.md)
│   └─ terminationGracePeriodSeconds ещё не истёк? → Ожидайте, Kubelet ещё выполняет preStop
│
└─ Tom не удаляется (PVC/PV)?
    ├─ VolumeAttachment существует? → См. [Финализаторы и CSI](./finalizer_issues.md)
    └─ Финализатор kubernetes.io/pv-protection? → См. [Финализаторы и CSI](./finalizer_issues.md)
```

### Таблица инструментов

| Уровень | Инструмент | Назначение | Пример |
| :--- | :--- | :--- | :--- |
| **OS (на узле)** | `lsof` | Процессы, удерживающие файлы в томе. | `lsof +D /var/lib/kubelet/pods/<UID>/volumes` |
| **OS (на узле)** | `fuser` | PID процессов с открытыми файлами. | `fuser -vm /path/to/volume` |
| **OS (на узле)** | `findmnt` | Дерево активных монтирований. | `findmnt \| grep <UID>` |
| **OS (на узле)** | `nsenter` | Проверка mount namespace Kubelet. | `nsenter -t $(pidof kubelet) -m cat /proc/self/mountinfo` |
| **OS (на узле)** | `strace` | Системные вызовы процесса. | `strace -p <PID> -e umount` |
| **OS (на узле)** | `dmesg` | Ошибки ядра (filesystem, block). | `dmesg \| grep -i "umount\|busy\|ext4"` |
| **CRI** | `crictl` | Управление контейнерами на узле. | `crictl ps -a --pod <POD_UID>` |
| **K8s (API)** | `kubectl describe` | Events и состояние пода. | `kubectl describe pod <name>` |
| **K8s (API)** | `kubectl get pv/pvc` | Статус томов. | `kubectl get pv <name> -o yaml` |
| **CSI** | `csi.log` | Логи CSI-драйвера. | `kubectl logs -n kube-system -l app=csi-*` |

---

## Практические сценарии

### Быстрый чек-лист диагностики

```bash
# 1. Определите UID пода и путь тома
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
echo "Pod UID: $POD_UID"

# 2. Проверьте Events пода (ищите FailedUnmount)
kubectl describe pod <pod-name> | grep -A 20 Events
# Пример вывода с ошибкой:
#   Events:
#   Type     Reason       Age    From     Message
#   ----     ------       ----   ----     -------
#   Warning  UnmountVolume  30s    kubelet  error cleaning up mount: umount "/var/lib/kubelet/pods/abc-123/volumes/kubernetes.io~csi/pvc-xyz": exit status 32: umount: /var/lib/kubelet/pods/abc-123/volumes/kubernetes.io~csi/pvc-xyz: target is busy

# 3. Проверьте, не держит ли процесс (выполнять на узле)
ssh <node> "lsof +D /var/lib/kubelet/pods/$POD_UID/volumes 2>/dev/null | head -20"
# Пример вывода:
#   COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
#   java    12345 root 12r REG  253,1  1048576  123 /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz/data

# 4. Проверьте подпути
ssh <node> "findmnt | grep $POD_UID | grep volume-subpaths"

# 5. Проверьте mountinfo в namespace Kubelet
KUBE_PID=$(ssh <node> "pidof kubelet")
ssh <node> "nsenter -t $KUBE_PID -m grep $POD_UID /proc/self/mountinfo | head -10"

# 6. Проверьте CSI-драйвер (если применимо)
kubectl logs -n kube-system -l app=csi-driver --tail=50 | grep -i "unstage\|unmount\|error"
```

### Сценарий 1: Блокировка процессами (In-use)

**Симптом:** Логи Kubelet: `UnmountVolume.tearDown failed for volume ... volume is in use by another process` или `target is busy`.

**Причины:**
- Приложение не закрыло файловый дескриптор перед завершением.
- Sidecar-контейнер (логи, прокси) удерживает файлы в томе.
- Процесс в `D-state` (Uninterruptible Sleep) — невозможно убить `SIGKILL`.
- Мониторинг/антивирус сканирует файлы в томе.

**Диагностика:**
```bash
# Найти UID пода
POD_UID=$(kubectl get pod <name> -o jsonpath='{.metadata.uid}')

# Поиск процессов по пути тома (выполнять на узле)
ssh <node> "lsof +D /var/lib/kubelet/pods/$POD_UID/volumes"
# Пример вывода (процесс держит дескриптор):
#   COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
#   java    12345 root 12r REG  253,1  1048576  123 /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz/data

# Альтернатива через fuser (PID и тип доступа)
ssh <node> "fuser -vm /var/lib/kubelet/pods/$POD_UID/volumes/*/*"
# Пример вывода:
#   /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz/data:  12345m

# Проверка осиротевших контейнеров через CRI
ssh <node> "crictl ps -a --pod $POD_UID"
# Пример вывода (осиротевший контейнер):
#   CONTAINER ID  IMAGE         CREATED       STATE    NAME        attempts
#   a1b2c3d4e5f6  nginx:1.21    2 hours ago  exited   sidecar     5

# Проверка процессов в D-state
ssh <node> "ps -eo pid,stat,wchan,args | awk '\$2 ~ /D/ {print \$0}'"
# Пример вывода:
#   PID  STAT WCHAN          COMMAND
#   1234 D    nfs_file_read  [nfsiod]
```

**Решение:**
```bash
# 1. Если процесс — "осиротевший" контейнер:
ssh <node> "crictl stop <container-id> && crictl rm <container-id>"

# 2. Если процесс — sidecar (istio-proxy, fluentd и т.д.):
#    Убедитесь, что sidecar корректно завершается (см. graceful_shutdown.md)
#    Если процесс в D-state — подождите завершения I/O или перезагрузите узел

# 3. Если процесс сторонний (антивирус, мониторинг):
#    Настройте исключения в политике сканирования для путей /var/lib/kubelet/

# 4. Принудительное завершение (крайняя мера):
ssh <node> "fuser -ck /var/lib/kubelet/pods/$POD_UID/volumes/*/*"
# → WARNING: All processes using /var/lib/kubelet/pods/abc/volumes/... will be killed
# → 12345

# 5. Если том всё ещё не размонтируется после убийства процессов:
ssh <node> "umount -l /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~<driver>/<vol-name>"
```

### Сценарий 2: Зависшие подпути (Volume Subpaths)

**Симптом:** Основной том не размонтируется, хотя `lsof` ничего не находит в `volumes`. Ошибка `tearDown failed: subpath`.

**Причина:** Подпути — это `bind mounts`, которые ссылаются на тот же файловый объект, что и основной том. Если подпуть не размонтирован, `umount` основного тома завершается ошибкой `target is busy`, даже если все процессы завершены.

**Диагностика:**
```bash
# Проверка активных монтирований в директории подпутей
POD_UID=$(kubectl get pod <name> -o jsonpath='{.metadata.uid}')
ssh <node> "findmnt | grep $POD_UID | grep volume-subpaths"
# Пример вывода:
#   TARGET                                                     SOURCE                   FSTYPE OPTIONS
#   /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/1   /dev/sda1[/config/nginx] ext4   rw,relatime
#   /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/2   /dev/sda1[/config/nginx] ext4   rw,relatime

# Проверка количества активных подпутей
ssh <node> "ls -la /var/lib/kubelet/pods/$POD_UID/volume-subpaths/ | head -20"
```

**Решение:** Размонтируйте подпути рекурсивно в обратном порядке (от самого глубокого к корневому):
```bash
POD_UID=$(kubectl get pod <name> -o jsonpath='{.metadata.uid}')

# Список подпутей в порядке удаления (от самых глубоких)
ssh <node> "findmnt -rn -o TARGET | grep '$POD_UID/volume-subpaths' | tac"
# Пример вывода:
#   /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/2
#   /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/1
#   /var/lib/kubelet/pods/abc/volume-subpaths/shared-data/1

# Размонтирование
for subpath in $(ssh <node> "findmnt -rn -o TARGET | grep '$POD_UID/volume-subpaths' | tac"); do
  ssh <node> "umount -l '$subpath'" && echo "OK: $subpath" || echo "FAIL: $subpath"
done
# Пример вывода:
# OK: /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/2
# OK: /var/lib/kubelet/pods/abc/volume-subpaths/nginx-config/1
# OK: /var/lib/kubelet/pods/abc/volume-subpaths/shared-data/1

# После этого повторите размонтирование основного тома
ssh <node> "umount /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~<driver>/<vol-name>"
```

### Сценарий 3: Глубокая проверка через Mount Namespace

**Симптом:** Хост пуст (`lsof`, `findmnt` не показывают активных монтирований), но Kubelet сообщает об ошибке. Монтирование "застряло" в `mount namespace` Kubelet (внутри процесса).

**Причина:** Kubelet выполняет монтирование в собственном `mount namespace` (отдельном от хоста). Если монтирование не было корректно очищено в этом namespace, оно продолжает блокировать операции, даже если на основном хосте всё чисто.

**Диагностика и решение:**
```bash
# 1. Найти PID Kubelet
KUBE_PID=$(ssh <node> "pidof kubelet")
echo "Kubelet PID: $KUBE_PID"
# Пример: Kubelet PID: 1847

# 2. Проверка mountinfo в namespace Kubelet (ищите mount для Pod UID)
ssh <node> "nsenter -t $KUBE_PID -m grep $POD_UID /proc/self/mountinfo | head -10"
# Пример вывода (монтирование найдено в namespace):
#   1234 89:1 / /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz rw,relatime - ext4 /dev/sda1 rw

# 3. Размонтирование внутри namespace (если mountinfo показывает активное монтирование)
MOUNT_POINT=$(ssh <node> "nsenter -t $KUBE_PID -m grep $POD_UID /proc/self/mountinfo | awk '{print \$4}'")
ssh <node> "nsenter -t $KUBE_PID -m umount -l '$MOUNT_POINT'"
echo "Unmounted: $MOUNT_POINT"

# 4. Проверка результата
ssh <node> "nsenter -t $KUBE_PID -m grep $POD_UID /proc/self/mountinfo"
# → (пустой вывод — монтирование удалено)
```

### Сценарий 4: Проблемы сетевых ФС (NFS/Ceph/CIFS)

**Симптом:** Команда `df -h` или `ls` зависает. Тайм-аут RPC в логах. Kubelet не может завершить `umount` в течение `terminationGracePeriodSeconds`.

**Причина:** При потере связи с NFS/Ceph-сервером ядро пытается дождаться ответа до `timeo` (тайм-аут NFS-клиента). По умолчанию это может быть 600 секунд (100 * 0.6с). `umount` не может завершиться, пока ядро не получит ответ или не истечёт тайм-аут.

**Диагностика:**
```bash
# Проверка статуса NFS-монтирования
ssh <node> "nfsstat -m | grep -A 5 <nfs-server>"
# Пример вывода:
#   /var/lib/kubelet/pods/abc/volumes/kubernetes.io~nfs/data
#     mount from: 10.0.0.5:/exports/data
#     NFS server: 10.0.0.5
#     FTP: Hard Mount, Soft Mount: no
#     Timeo: 600, Retrans: 2, Int: no
#     Lookups: 100%  Hits: 100%  Misses: 0%

# Проверка RPC-статуса
ssh <node> "rpcinfo -p <nfs-server-ip>"
# Пример вывода:
#   program vers proto   port  service
#   100000    4   tcp    111  portmapper
#   100000    3   tcp    111  portmapper
#   100005    3   tcp  20048  mountd
#   100003    3   tcp   2049  nfs

# Проверка зависших NFS-процессов
ssh <node> "ps -eo pid,stat,wchan,args | grep nfs | grep -v grep"
# Пример вывода:
#   1234 D    nfs_file_read  [nfsiod]
#   1235 D    nfs_file_write [nfsiod]

# Проверка тайм-аутов NFS
ssh <node> "cat /proc/fs/nfs/leases | head -5" 2>/dev/null || \
ssh <node> "cat /sys/module/nfs/parameters/nfs.max_session_slots" 2>/dev/null
```

**Решение:**
```bash
# 1. Уменьшите тайм-аут NFS-клиента (на всех узлах кластера):
#    В /etc/fstab или в манифесте Pod:
#    options: hard,timeo=60,retrans=2
#    timeo=60 означает 60 * 0.1с = 6 секунд на попытку

# 2. Принудительное размонтирование (если сервер недоступен):
ssh <node> "umount -f -l /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~nfs/<vol-name>"
# → umount: /var/lib/kubelet/pods/.../data: target is busy (может потребоваться несколько попыток)

# 3. Если umount -f не помогает — "ленивое" размонтирование + ожидание:
ssh <node> "umount -l /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~nfs/<vol-name>"
# Точка монтирования исчезнет из иерархии немедленно, но ресурсы освободятся позже

# 4. Для CephFS — проверьте демон ceph-mds:
kubectl get pods -n rook-ceph | grep mds
kubectl logs -n rook-ceph <mds-pod> --tail=50 | grep -i "error\|timeout"

# 5. Мониторинг NFS-сбоев:
ssh <node> "dmesg | grep -i 'nfs\|rpc\|mount' | tail -20"
# Пример вывода:
#   [12345.678] nfs: server 10.0.0.5 not responding, still trying
#   [12350.123] nfs: server 10.0.0.5 not responding, still trying
#   [12400.456] nfs: server 10.0.0.5 OK
```

### Сценарий 5: Конфликты SELinux / AppArmor

**Симптом:** Ошибки `denied { unmount }` в `audit.log` или `dmesg`. Kubelet не может выполнить `umount` из-за контекста безопасности.

**Диагностика:**
```bash
# Проверка SELinux (CentOS/RHEL)
ssh <node> "ausearch -m avc -ts recent | grep unmount"
# Пример вывода:
#   type=AVC msg=audit(1690000000.123:456): avc:  denied  { unmount } for
#   pid=1847 comm="kubelet" scontext=system_u:system_r:kubelet_t:s0
#   tcontext=system_u:object_r:container_file_t:s0 tclass=filesystem permissive=0

# Проверка текущего режима SELinux
ssh <node> "getenforce"
# → Enforcing

# Проверка контекста тома
ssh <node> "ls -Z /var/lib/kubelet/pods/$POD_UID/volumes/"
# Пример вывода:
#   system_u:object_r:container_file_t:s0 /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz
```

**Решение:**
```bash
# 1. Убедитесь, что установлен container-selinux:
ssh <node> "rpm -q container-selinux"  # RHEL/CentOS
# → container-selinux-2.200.3-1.el9.noarch

# 2. Перемаркировка контекста (если том имеет неверную метку):
ssh <node> "restorecon -Rv /var/lib/kubelet/pods/$POD_UID/volumes/"
# → reset /var/lib/kubelet/pods/abc/volumes/kubernetes.io~csi/pvc-xyz from system_u:object_r:container_file_t:s0 to system_u:object_r:kubelet_t:s0

# 3. Временная проверка (disable SELinux):
ssh <node> "setenforce 0"
# → Если помогло — требуется permanentная настройка через semanage или политику

# 4. Для AppArmor — проверьте профиль Kubelet:
ssh <node> "aa-status | grep kubelet"
# → kubelet (/usr/local/bin/kubelet) <enforce>

# 5. Добавление исключения в policy (на любой ДОГМ):
ssh <node> "audit2allow -a -M kubelet_fix" && \
ssh <node> "semodule -i kubelet_fix.pp"
```

### Сценарий 6: Локальные драйверы (Local PV, hostPath, emptyDir)

**Симптом:** Pod удаляется, но файлы в `/var/lib/kubelet/pods/<uid>/volumes/` остаются. Каталоги не очищаются.

**Причины:**
- **Local PV** (openEBS, local-path-provisioner): Файлы данных физически не удаляются при `kubectl delete pv`. Это ожидаемое поведение.
- **hostPath**: Файлы принадлежат хосту. Kubelet удаляет только `bind mount`, но не саму директорию.
- **emptyDir**: Файлы создаются с UID 0 (root). Если контейнер запущен от другого UID, Kubelet может не иметь прав на удаление.

**Диагностика:**
```bash
# Проверка, остаются ли файлы после удаления пода
ssh <node> "ls -la /var/lib/kubelet/pods/$POD_UID/volumes/"

# Для emptyDir — проверка PID и UID
ssh <node> "ls -ln /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~empty-dir/"

# Для local-path-provisioner — проверка, удалён ли PV
kubectl get pv | grep <pv-name>
# Пример:
#   NAME       CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM
#   local-pv   10Gi       RWO            Delete           Released default/data-pvc
#   → STATUS = Released, но файлы на диске остались
```

**Решение:**
```bash
# 1. emptyDir — ручная очистка (если под уже удалён):
ssh <node> "rm -rf /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~empty-dir/"

# 2. Local PV — проверка reclaim policy:
#    Delete → файлы удаляются автоматически (если драйвер корректно очищает)
#    Retain → файлы остаются (требуется ручное удаление)
kubectl get pv <pv-name> -o jsonpath='{.spec.persistentVolumeReclaimPolicy}'
# → Retain

# 3. Для Retain — ручное удаление после снятия финализаторов:
kubectl delete pv <pv-name> --wait=false
ssh <node> "rm -rf /mnt/data/<pv-name>"  # путь зависит от драйвера

# 4. hostPath — файлы НЕ удаляются (это design). Используйте emptyDir для временных данных.
```

### Сценарий 7: Шифрованные тома (LUKS)

**Симптом:** Pod в `Terminating`, ошибка `umount` или `detaching device`. CSI-драйвер не может открыть/закрыть LUKS-контейнер.

**Причина:** LUKS-том требует корректного закрытия (`cryptsetup luksClose`) перед размонтированием. Если CSI-драйвер не имеет доступа к ключу шифрования или демон `cryptsetup` недоступен, том остаётся "открытым".

**Диагностика:**
```bash
# Проверка открытых LUKS-устройств
ssh <node> "lsblk -f | grep crypt"
# Пример вывода:
#   sdb                        LUKS        crypto   <UUID>  data-encrypted

# Проверка статуса LUKS
ssh <node> "cryptsetup status data-encrypted"
# Пример вывода:
#   /dev/mapper/data-encrypted is active and is in use.
#   type:    LUKS2
#   cipher:  aes-xts-plain64
#   keysize: 512 bits
#   key location: dm-crypt
#   device:  /dev/sdb
#   sector size:  512
#   offset:  32768 sectors
#   size:    20641792 sectors
#   mode:    read/write

# Проверка, не удерживает ли кто-то LUKS
ssh <node> "lsof /dev/mapper/data-encrypted"
# Пример: (пусто — можно закрывать)
```

**Решение:**
```bash
# 1. Размонтирование TOMОВОГО ФАЙЛА (первый шаг):
ssh <node> "umount /var/lib/kubelet/pods/$POD_UID/volumes/kubernetes.io~<driver>/<vol>"

# 2. Закрытие LUKS-контейнера:
ssh <node> "cryptsetup luksClose data-encrypted"

# 3. Проверка результата:
ssh <node> "lsblk -f | grep crypt"
# → (пусто — устройство закрыто)

# 4. Если cryptsetup hang — проверьте kernel logs:
ssh <node> "dmesg | grep -i 'dm-crypt\|crypt\|luks' | tail -10"
# Пример вывода:
#   [12345.678] device-mapper: crypt: recovering journal
```

---

## Мониторинг и алерты

### PromQL запросы

```promql
# Поды с ошибкой FailedUnmount (за последние 5 минут)
sum(rate(kube_pod_container_status_last_terminated_reason{reason="Error"}[5m])) by (namespace, pod)

# Время жизни пода от deletionTimestamp до завершения (должно быть < terminationGracePeriodSeconds)
histogram_quantile(0.99,
  sum(rate(kube_pod_container_terminated_reason_seconds_bucket[5m])) by (le, namespace, pod)
)

# Поды в Terminating дольше 60 секунд (potential проблема с unmount)
(kube_pod_status_phase{phase="Terminating"} == 1)
  and
(time() - kube_pod_created > 60)

# Ошибки CSI-драйвера (NodeUnstage failures)
sum(rate(csi_node_stage_volume_errors_total[5m])) by (driver_name)
```

### Готовые алерты (Prometheus AlertManager)

```yaml
groups:
- name: volume_unmount
  rules:
  - alert: PodStuckTerminatingUnmount
    expr: |
      kube_pod_status_phase{phase="Terminating"} == 1
      and
      (time() - kube_pod_created > 300)
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod stuck in Terminating > 5 min"
      description: "Pod {{ $labels.pod }} в {{ $labels.namespace }} завис в Terminating более 5 минут. Возможно, том не размонтируется."

  - alert: CSIUnmountErrors
    expr: |
      increase(csi_node_stage_volume_errors_total[5m]) > 0
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "CSI NodeUnstage errors detected"
      description: "CSI-драйвер {{ $labels.driver_name }}-report ошибки при unmount."
```

### Проверка логов Kubelet на узле

```bash
# Фильтрация логов Kubelet по VolumeManager
ssh <node> "journalctl -u kubelet --grep 'VolumeManager.*unmount' --since '1 hour ago'"
# Пример вывода:
#   Sep 03 10:15:00 node-1 kubelet[1847]: E0903 10:15:00.123 1847 reconciler.go:199]
#     UnmountVolume.tearDown failed for volume "pvc-xyz" volume is in use by another process

# Проверка ошибок umount
ssh <node> "journalctl -u kubelet --grep 'umount.*fail\|umount.*busy' --since '1 hour ago'"

# Проверка ошибок CSI
ssh <node> "journalctl -u kubelet --grep 'csi.*error\|csi.*fail' --since '1 hour ago'"
```

---

## Команды kubectl

| Команда | Назначение |
| :--- | :--- |
| `kubectl get pod <name> -o jsonpath='{.metadata.uid}'` | Получить UID пода (нужен для путей томов). |
| `kubectl describe pod <name> \| grep -A 20 Events` | Проверить ошибки FailedUnmount в Events. |
| `kubectl get pv <name> -o yaml \| grep -A 5 status` | Статус PV (Bound/Released/Failed). |
| `kubectl get pvc <name> -o jsonpath='{.spec.volumeName}'` | Найти PV, связанный с PVC. |
| `kubectl get volumeattachment` | Проверить VolumeAttachment (CSI detach). |
| `kubectl logs -n kube-system -l app=csi-* --tail=50` | Логи CSI-драйвера (ищите unmount errors). |
| `kubectl get pod <name> -o jsonpath='{.spec.containers[*].volumeMounts}'` | Какие тома монтируются в контейнеры. |
| `kubectl get pod <name> -o jsonpath='{.spec.volumes}'` | Типы томов (csi, emptyDir, hostPath, nfs). |
| `kubectl delete pod <name> --grace-period=0 --force` | Принудительное удаление (если том гарантированно чист). |
| `kubectl get events --field-selector reason=FailedUnmount` | Быстрый поиск подов с ошибкой unmount. |

---

## Граничные случаи и особенности

**Под с несколькими томами и разной скоростью завершения:**
Если один контейнер держит Tomas в `D-state`, а другой — нет, Kubelet будет ждать завершения обеих. `terminationGracePeriodSeconds` общий для всех контейнеров в Pod. Если one контейнер зависает в D-state на 30 секунд, а другой завершается за 5 секунд, Kubelet не сможет размонтировать том для второго контейнера до завершения первого.

**Bidirectional Mount Propagation:**
Если контейнер с `mountPropagation: Bidirectional` создаёт монтирование на хосте и умирает не очистив его, это монтирование остаётся активным и блокирует `umount` родительского тома. Это particularly dangerous с shared storage (NFS, Ceph). Всегда избегайте `Bidirectional`, если контейнер не является storage-related.

**Pod Disruption Budget и unmount:**
PDB не влияет на unmount напрямую, но `kubectl drain` не завершится, пока Pod не будет удалён (включая unmount томов). Если unmount зависает, drain узла будет блокирован.

**EmptyDir сolatile память:**
`emptyDir: medium: Memory` создаёт tmpfs-том. При завершении пода tmpfs размонтируется автоматически и мгновенно (нет проблем с D-state или busy).

**HostPath:**
Kubelet НЕ удаляет файлы, созданные в `hostPath`. Он удаляет только `bind mount`. Если приложение создало файлы в `hostPath`-томе, они останутся на хосте после удаления пода.

**TTL after finish:**
Kubernetes не имеет встроенного механизма очистки томов по TTL. Если Pod завершился успешно (состояние Succeeded), том всё равно остаётся смонтированным до удаления Pod-объекта.

---

**См. также:**
- [Финализаторы и проблемы CSI](./finalizer_issues.md) — если том не отсоединяется (Detach).
- [Диагностика Pod Terminating](./diagnostics.md) — основной алгоритм поиска причин зависания.
- [Определения Pod Terminating](./definitions.md) — системные механизмы завершения Pod.
