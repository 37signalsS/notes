# Диагностика и устранение проблем хранилища в Kubernetes

## Определения

**Storage Troubleshooting** — систематический процесс диагностики и устранения проблем, связанных с выделением, привязкой, монтированием и эксплуатацией персистентных томов в Kubernetes. Включает анализ состояния PV/PVC, проверку CSI-драйвера, диагностику узлов и файловой системы.

**PVC (Persistent Volume Claim)** — основной объект, через который приложение запрашивает хранилище. Статус PVC (`Pending`, `Bound`, `Lost`) является первичным индикатором проблемы.

**VolumeAttachment** — кластерный ресурс, отражающий факт привязки (attach) тома к конкретному узлу. Зависший `VolumeAttachment` блокирует монтирование тома на других узлах.

**Provisioner** — компонент CSI-драйвера, отвечающий за создание физического тома в СХД. Ошибки provisioner видны в Events PVC.

**Связанные темы:**
- [Persistent Volumes и PVC](./pv_and_pvc.md) — жизненный цикл, режимы доступа.
- [StorageClass](./storageclass.md) — параметры динамического выделения.
- [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md) — первичная диагностика CSI.
- [Мониторинг CSI](./CSI/csi_monitoring_rules.md) — метрики и алерты.

---

## Теоретический блок

### Классификация проблем

| Уровень | Типичные симптомы | Группа причин |
|:---|:---|:---|
| **PVC** | `Pending`, `Lost`, `ProvisioningFailed` | StorageClass, provisioner, квоты, размер |
| **VolumeAttachment** | Под не стартует, `Attach` завис | CSI-драйвер, iSCSI/NFS, multipath, права |
| **Монтирование** | `MountVolume.SetUp failed`, `permission denied` | ФС,ount options, SELinux, AppArmor |
| **Файловая система** | `Read-only file system`, `No space left` | fsck,擴大, mount options, quotas |
| **Производительность** | Высокая latency, тайм-ауты | IOPS, сеть, NUMA, I/O scheduler |
| **Узел** | Под не планируется, `nodeAffinity` | Топология, taints, capacity |

### Алгоритм первичной диагностики

```
1. kubectl get pvc -A
   └─ PVC в Lost? → Проверить PV и физическое хранилище
   └─ PVC в Pending? → Перейти к шагу 2
   └─ PVC Bound? → Проверить под (шаг 5)

2. kubectl describe pvc <name>
   └─ Events: ProvisioningFailed → Причина в тексте ошибки
   └─ Events: No PV available → Проверить StorageClass и provisioner
   └─ Events: Waiting for first consumer → WaitForFirstConsumer (норма)

3. Проверить provisioner:
   kubectl get pods -n <csi-namespace>
   kubectl logs -n <csi-namespace> <pod> -c <container> | tail -50

4. Проверить CSI-драйвер:
   kubectl get csidrivers
   kubectl get volumeattachments

5. Проверить под:
   kubectl describe pod <name> | grep -A5 "Events"
   kubectl logs <pod> -c <container> | grep -i "mount\|error"
```

---

## Практический блок

### 1. PVC в статусе Pending

#### 1.1 ProvisioningFailed — нет прав доступа

**Симптом:** `kubectl describe pvc` показывает ошибку `provisioner ... failed to provision volume with StorageClass "...": rpc error: code = PermissionDenied`

**Причина:** CSI-драйвер не имеет прав для создания тома в СХД (отсутствуют credentials, ключи CephX, токен AWS и т.д.).

**Решение:**
```bash
# 1. Найти секрет, используемый StorageClass
kubectl get sc <sc-name> -o jsonpath='{.parameters}'

# 2. Проверить, что секрет существует и содержит нужные ключи
kubectl get secret <secret-name> -n <namespace> -o yaml

# 3. Проверить логи CSI-контроллера
kubectl logs -n kube-system csi-controller-0 -c <driver-container> | grep -i "error\|permission"

# 4. Убедиться, что Secret привязан к правильному сервисному аккаунту
kubectl get sa <sa-name> -n <namespace> -o yaml
```

#### 1.2 ProvisioningFailed — нет места в СХД

**Симптом:** `Failed to provision volume with StorageClass "...": rpc error: code = Internal ... no space left`

**Решение:**
```bash
# Для Ceph:
ceph osd df
ceph osd pool stats <pool-name>

# Для Longhorn:
kubectl get nodes.longhorn.io -n longhorn-system -o wide
kubectl get volumes.longhorn.io -n longhorn-system

# Для NFS:
df -h <nfs-mount-point>
```

#### 1.3 Waiting for first consumer

**Симптом:** PVC в `Pending`, Events показывают `waiting for first consumer to be created before binding`

**Причина:** `volumeBindingMode: WaitForFirstConsumer` — это нормальное поведение. Том будет создан после назначения пода на узел.

**Проверка:** Убедитесь, что под с ссылкой на этот PVC может быть запланирован (есть подходящий узел с нужными taints/tolerations).

#### 1.4 StorageClass не найден

**Симптом:** `storageclass "xxx" not found`

```bash
# Проверить доступные StorageClass
kubectl get sc

# Проверить, есть ли default StorageClass
kubectl get sc -o json | jq '.items[] | select(.metadata.annotations["storageclass.kubernetes.io/is-default-class"]=="true") | .metadata.name'
```

### 2. Под не стартует из-за Volume

#### 2.1 Multi-Attach error

**Симптом:** `Multi-Attach error for volume "pvc-xxx" Volume is already exclusively attached to one node and can't be attached to another`

**Причина:** RWO-том пытается подключиться к нескольким узлам одновременно (при неожиданном перемещении пода до завершения detach на старом узле).

**Решение:**
```bash
# 1. Проверить, на каком узле сейчас том
kubectl get volumeattachments | grep <pv-name>

# 2. Принудительно отвязать том (если старый под мёртв)
kubectl delete volumeattachment <name>

# 3. Для предотвращения — использовать ReadWriteOncePod (RWOP)
#    или WaitForFirstConsumer в StorageClass
```

#### 2.2 AttachdetachController timeout

**Симптом:** Под в `ContainerCreating`, Events: `AttachVolume.Attach failed due to timeout`

```bash
# 1. Проверить CSI node-plugin на целевом узле
kubectl get pods -n <csi-namespace> -o wide | grep <node-name>

# 2. Проверить iSCSI/NFS зависимости на узле
# Для iSCSI:
sudo systemctl status iscsid
sudo iscsiadm -m session

# Для NFS:
sudo systemctl status nfs-client.target
sudo showmount -e <nfs-server>

# 3. Проверить multipath (для SAN-хранилищ)
sudo multipath -ll
```

#### 2.3 Pending из-за неподходящего узла

**Симптом:** Под в `Pending` с `0/N nodes are available: n No preemption is needed`

```bash
# Проверить, почему под не планируется
kubectl describe pod <name> | grep -A10 "Events"

# Проверить taints на узлах
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints

# Проверить nodeAffinity в поде
kubectl get pod <name> -o jsonpath='{.spec.affinity}'
```

### 3. MountVolume.SetUp failed

#### 3.1 NFS: Permission denied

**Симптом:** `MountVolume.SetUp failed for volume "pvc-xxx" : mount failed: exit status 32 mount.nfs: access denied by server`

```bash
# 1. Проверить экспорт на NFS-сервере
# На NFS-сервере:
cat /etc/exports
exportfs -v

# 2. Проверить, что IP узла разрешён в экспорт-листе
# В /etc/exports должно быть:
# /data 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)

# 3. Применить изменения
sudo exportfs -ra

# 4. Проверить доступность с узла
showmount -e <nfs-server-ip>
```

#### 3.2 iSCSI: не удалось подключить сессию

**Симптом:** `MountVolume.SetUp failed: volume mount failed: iscsi: login failed to <target>`

```bash
# 1. Проверить статус iSCSI-сессий
sudo iscsiadm -m session
sudo iscsiadm -m session -P 3

# 2. Переподключиться
sudo iscsiadm -m node -T <target-iqn> -p <portal-ip> --login

# 3. Проверить, что устройство появилось
lsblk
sudo multipath -ll  # если используется multipath
```

#### 3.3 SELinux блокирует монтирование

**Симптом:** `permission denied` при монтировании, хотя NFS/iSCSI работает.

```bash
# Проверить SELinux
getenforce
ausearch -m avc -ts recent

# Для NFS: добавить опцию mountOptions: context=system_u:object_r:container_file_t:s0
# Или временно:
sudo setenforce 0  # ТОЛЬКО для диагностики
```

### 4. VolumeExpansion завис

#### 4.1 Расширение в ошибке

**Симптом:** `kubectl get pvc` показывает `Conditions: Type=Resizing, Status=True` или `FileSystemResizePending`

```bash
# 1. Проверить статус расширения
kubectl describe pvc <name> | grep -A5 "Conditions"

# 2. Проверить логи external-resizer
kubectl logs -n kube-system csi-resizer-0 | grep -i "<pvc-name>"

# 3. Если расширение застряло в ошибке (K8s 1.29+ Beta, 1.34+ GA):
#    Уменьшить значение в PVC до доступного максимума
kubectl patch pvc <name> -p '{"spec":{"resources":{"requests":{"storage":"<доступный_максимум>"}}}}'

# 4. Если FS не расширилась онлайн:
kubectl delete pod <pod-using-pvc>
# Под пересоздастся, ФС расширится при монтировании
```

#### 4.2 StorageClass не поддерживает расширение

**Симптом:** `PersistentVolumeClaim "pvc-xxx" is invalid: spec.resources[storage]: Forbidden: field is immutable after creation`

```bash
# Проверить StorageClass
kubectl get sc <name> -o jsonpath='{.allowVolumeExpansion}'
# → true или false

# Если false — создать новый SC с allowVolumeExpansion: true
# и мигрировать данные (rsync между PVC или Velero)
```

### 5. Диагностика производительности

#### 5.1 Высокая latency на PVC

```bash
# 1. Запустить fio в поду с проблемным PVC
kubectl run fio-test --rm -it --image=linuxtools/fio -- \
  fio --name=test --directory=/data --rw=randread --bs=4k \
  --size=100M --numjobs=1 --runtime=30 --group_reporting

# 2. Проверить метрики kubelet
# В Prometheus:
# kubelet_volume_stats_available_bytes
# kubelet_volume_stats_used_bytes

# 3. Проверить узел
iostat -x 1 5
iotop -o
```

#### 5.2 NFS-сервер как bottleneck

```bash
# На NFS-сервере:
nfsstat -s     # статистика сервера
nfsiostat 1    # I/O статистика

# На клиенте (K8s-узле):
nfsiostat 1    # I/O статистика клиента
mount | grep nfs  # проверить mount options (rsize, wsize, nfsvers)
```

### 6. Общие команды диагностики

```bash
# === Уровень PVC/PV ===
kubectl get pvc -A -o wide
kubectl get pv -o wide
kubectl describe pvc <name> -n <ns>
kubectl describe pv <name>

# === Уровень CSI ===
kubectl get csidrivers
kubectl get volumeattachments
kubectl get volumesnapshotclasses -A
kubectl get volumesnapshots -A

# === Уровень CSI-драйвера ===
kubectl get pods -n kube-system | grep csi
kubectl logs -n kube-system <csi-controller-pod> -c <driver> --tail=100
kubectl logs -n kube-system <csi-node-pod> -c <driver> --tail=100

# === Уровень узла ===
kubectl describe node <name> | grep -A5 "Conditions"
kubectl get events --field-selector reason=FailedAttachVolume -A

# === Уровень СХД (Longhorn) ===
kubectl get volumes.longhorn.io -n longhorn-system
kubectl get engines.longhorn.io -n longhorn-system
kubectl get replicas.longhorn.io -n longhorn-system

# === Уровень СХД (Ceph) ===
ceph -s
ceph osd df
ceph health detail
ceph osd pool stats
```

---

## Дополнительная информация

### Чеклист перед инцидентом

- [ ] CSI-драйвер и sidecar-контейнеры работоспособны
- [ ] Все узлы в статусе `Ready`
- [ ] iSCSI/NFS зависимости установлены на каждом узле
- [ ] StorageClass настроен с правильным `volumeBindingMode`
- [ ] Квоты (ResourceQuota) не исчерпаны
- [ ] Мониторинг (kubelet_volume_stats) работает
- [ ] Бэкапы (Velero/CSI Snapshots) настроены и проверены

### См. также

- [StorageClass — поиск и устранение неисправностей](./storageclass.md#поиск-и-устранение-неисправностей)
- [Диагностика NFS в продакшене](./CSI/csi_nfs_production.md)
- [Мониторинг CSI-драйверов](./CSI/csi_monitoring_rules.md)
- [Стратегии резервного копирования](../Operations/backup-strategies.md)
