# Хранилище и резервное копирование Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры для on-premise развёртываний

## Определения

**Хранилище и резервное копирование для юникернелов** — это методы обеспечения persistent данных, их репликации и восстановления в среде, где сам юникернел по дизайну не содержит persistent state. Включает сетевые файловые системы (NFS, CephFS), блочные устройства (iSCSI, Ceph RBD), virtio-blk/virtio-scsi и стратегии backup/restore.

Базовая информация — в [Обзоре Unikernel](./unikernel_overview.md), сравнение с контейнерами/VM — в [Преимуществах и ограничениях](./unikernel_advantages_disadvantages.md).

## Основные концепции

### Модели хранения

| Модель | Пример | Характеристики |
| :--- | :--- | :--- |
| **Network File System** | NFS, CephFS | Совместный доступ, подходит для configs/logs |
| **Block Device** | iSCSI, Ceph RBD, virtio-blk | Высокая производительность, подходит для БД |
| **Object Storage** | S3-совместимое | Архивы, бэкапы, большие файлы |
| **In-memory** | tmpfs | Кэш, временные данные |

### Внешнее хранилище для юникернелов

Поскольку юникернел не содержит файловой системы в привычном понимании, данные должны храниться:
1. **Вне образа:** На сетевом хранилище (NFS/Ceph), доступном через virtio-blk или virtio-net.
2. **Через приложение:** Database/S3/MinIO как внешний сервис.
3. **В гипервизоре:** Файловые системы хоста, проброшенные через virtio-blk.

## Практические сценарии

### 1. Virtio-blk (блочное устройство)

#### Создание и подключение

```bash
# Создание образа диска
qemu-img create -f qcow2 /var/lib/libvirt/images/unikernels/my-service-data.qcow2 10G

# Подключение через virsh
virsh attach-disk my-service /var/lib/libvirt/images/unikernels/my-service-data.qcow2 vdb --type disk --mode readonly

# Или через XML
<disk type='file' device='disk'>
  <driver name='qemu' type='qcow2' cache='writeback' io='threads'/>
  <source file='/var/lib/libvirt/images/unikernels/my-service-data.qcow2'/>
  <target dev='vdb' bus='virtio'/>
</disk>
```

#### Форматирование внутри юникернела

```bash
# Внутри ОС гостя (если есть shell)
mkfs.ext4 /dev/vdb
mkdir /data
mount /dev/vdb /data
```

### 2. NFS

#### Настройка NFS-сервера на хосте

```bash
# Установка
sudo apt install nfs-kernel-server

# Создание экспорта
sudo mkdir -p /srv/nfs/unikernels
sudo chown nobody:nogroup /srv/nfs/unikernels

# /etc/exports
echo "/srv/nfs/unikernels 10.0.10.0/24(rw,sync,no_subtree_check,no_root_squash)" | sudo tee -a /etc/exports

# Применение
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server

# Проверка
showmount -e localhost
# → /srv/nfs/unikernels 10.0.10.0/24
```

#### Монтирование в юникернеле

```bash
# Внутри гостевой ОС
mount -t nfs 10.0.10.1:/srv/nfs/unikernels /data
df -h /data
# → 10.0.10.1:/srv/nfs/unikernels 100G 0 100G 0% /data
```

### 3. Ceph

#### Ceph RBD (блочное устройство)

```bash
# Создание pool
ceph osd pool create rbd 128

# Создание образа
rbd create unikernel-data --size 10G --pool rbd

# Список образов
rbd ls rbd
# → unikernel-data

# Подключение через kernel RBD
sudo rbd map rbd/unikernel-data --pool rbd
sudo mkfs.ext4 /dev/rbd0
sudo mount /dev/rbd0 /mnt/ceph
```

#### CephFS (файловая система)

```bash
# Монтирование CephFS
sudo mkdir /mnt/cephfs
sudo mount -t ceph 10.0.0.1:6789:/ /mnt/cephfs -o name=unikernel,secretfile=/etc/ceph/secret

# Использование
df -h /mnt/cephfs
# → 10.0.0.1:6789:/ 1000G 0 1000G 0% /mnt/cephfs
```

### 4. iSCSI

#### Настройка iSCSI target (host)

```bash
# Установка
sudo apt install targetcli-fb

# Создание target
sudo targetcli <<EOF
cd /backstores/block
create unikernel-data /dev/vg0/unikernel-data
cd /iscsi
create iqn.2026-09.com.example:unikernel-data
cd /iscsi/iqn.2026-09.com.example:unikernel-data/tpg1
luns create /backstores/block/unikernel-data
cd acls
create iqn.2026-09.com.example:client
EOF

# Запуск
sudo systemctl restart target
```

#### Подключение с хоста (initiator)

```bash
# Установка
sudo apt install open-iscsi

# Обнаружение
sudo iscsiadm -m discovery -t sendtargets -p 10.0.0.1
# → 10.0.0.1:3260,1 iqn.2026-09.com.example:unikernel-data

# Подключение
sudo iscsiadm -m node -T iqn.2026-09.com.example:unikernel-data -p 10.0.0.1 -l

# Форматирование
sudo mkfs.ext4 /dev/sdc
```

### 5. Persistent данные для приложений

#### Паттерн: External Database

```python
# Приложение внутри юникернела использует внешнюю БД
import redis

r = redis.Redis(host='10.0.0.10', port=6379, db=0)
r.set('key', 'value')
```

#### Паттерн: Object Storage (S3/MinIO)

```python
# Приложение сохраняет файлы в S3
import boto3

s3 = boto3.client('s3', endpoint_url='http://minio:9000')
s3.upload_file('/tmp/upload.txt', 'my-bucket', 'upload.txt')
```

### 6. Резервное копирование

#### Стратегии

| Стратегия | RPO | RTO | Инструменты |
| :--- | :--- | :--- | :--- |
| **Rebuild from Source** | 0 | 1–5 мин | Git + CI/CD |
| **Snapshot** | 0 | <1 сек | Kraft Metis, QEMU dirty-bitmaps |
| **Image Registry** | Последний push | 5–10 сек | Harbor, Nexus |
| **External Storage** | Зависит от FS | Зависит | NFS, Ceph, rsync |

#### Snapshot через QEMU dirty-bitmaps

```bash
# Создание bitmap
curl --unix-socket /tmp/fc.socket -X PUT \
  "http://localhost/bitmaps/my-service" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"node": "my-service", "name": "snap-1", "disabled": false}'

# Создание snapshot
virsh snapshot-create-as my-service snap-1 --disk-only

# Восстановление
virsh snapshot-revert my-service snap-1
```

#### Backup через rsync

```bash
#!/bin/bash
# /usr/local/bin/backup-unikernel.sh
BACKUP_DIR="/backup/unikernels"
DATE=$(date +%Y%m%d)

# Backup данных NFS
sudo rsync -av --delete /srv/nfs/unikernels/ $BACKUP_DIR/nfs/

# Backup образов
sudo rsync -av /var/lib/libvirt/images/unikernels/ $BACKUP_DIR/images/

# Retention: 7 дней
find $BACKUP_DIR -type f -mtime +7 -delete
```

#### Backup Ceph RBD

```bash
# Создание snapshot
rbd snap create rbd/unikernel-data@snap-$(date +%Y%m%d)

# Экспорт
rbd export-diff rbd/unikernel-data@snap-$(date +%Y%m%d) /backup/unikernel-data.diff

# Восстановление
rbd import-diff /backup/unikernel-data.diff rbd/unikernel-data
```

## Устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Виртуальный диск не появляется в гостевой ОС** | virtio-blk не загружен в образ, или диск не подключен через libvirt | `lsblk`, `lspci`, `dmesg \| grep virtio` | Добавить `virtio-blk` в список klibs при сборке, проверить XML домена (`virsh dumpxml`), убедиться что `<target dev='vdb' bus='virtio'/>` присутствует |
| **NFS: stale file handle после перезагрузки сервера** | Экспорт смонтирован без `hard,intr`, или NFSv4 state восстановился с другим minor version | `mount \| grep nfs`, `dmesg \| grep nfs`, `showmount -e localhost` | Использовать `hard,intr` или `soft,timeo=5,retrans=3` в опциях монтирования; для NFSv4 проверить `idmapd.conf` и consistency domain |
| **Ceph RBD: map возвращает «device busy»** | Снапшот активен, или другой клиент подключен к тому же образу | `rbd status rbd/unikernel-data`, `rbd snap ls rbd/unikernel-data` | Удалить/merge старый снапшот, отключить неиспользуемые маппинги (`rbd unmap`), проверить `rbd lock list` |
| **iSCSI: target не виден через discover** | Firewall на целевом сервере блокирует 3260/TCP, или ACL не настроен | `targetcli ls`, `firewall-cmd --list-all`, `iscsiadm -m node` | Открыть 3260/TCP, проверить ACL (`targetcli /iscsi/.../acls ls`), убедиться что `target` запущен |
| **rsync backup зависает или останавливается** | Нет места на целевом носителе, или сетевой путь разорван | `df -h $BACKUP_DIR`, `rsync --progress`, `journalctl -u nfs` | Проверить место, добавить `--timeout=60 --contimeout=30`, использовать `screen`/`tmux` для длинных операций |
| **Snapshot восстановлен, но данные устарели** | RPO > 0, snapshot был создан давно, или WAL не сброшен | `virsh snapshot-current my-service`, `virsh snapshot-list` | Проверить время создания снапшота, для transactional workloads использовать `fsfreeze` перед snapshot |
| **Гость зависает при монтировании NFS/CephFS** | Нет доступа к сети, firewall блокирует 2049/NFS или 6789/Ceph, или guest kernel не имеет поддержки FS | `ping 10.0.10.1`, `iptables -L -n`, `cat /proc/filesystems` | Проверить сетевую связность, открыть порты в `UNIKERNEL` chain, добавить модуль ФС в образ |
| **Бэкап не восстанавливается: Permission denied** | Права на файл backup/образ изменились, или LUKS/SELinux контекст неверен | `ls -la $BACKUP_DIR`, `ls -Z $BACKUP_DIR` (если SELinux), `cryptsetup luksOpen` | Исправить права (`chmod 600` для sensitive данных), восстановить контекст (`restorecon -Rv`), проверить LUKS заголовок |
| **Производительность диска в 2–3 раза ниже ожидаемой** | IOThread не настроен, или QEMU использует shared IOThread, или диск на rotational media | `iostat -x 1`, `cat /sys/block/vdb/queue/rotational`, `virsh dumpxml` | Назначить отдельный IOThread (`<iothread>1</iothread>`), использовать SSD/NVMe, отключить `cache=writeback` если требуется consistency |
| **Live migration падает с ошибкой диска** | Разные пути к образу на source/destination, или образ не на shared storage | `virsh migrate --verbose`, `virsh domblklist my-service` | Унифицировать пути, использовать shared storage (NFS, CephFS) или `--copy-storage-all` |
| **CephFS: монтирование падает с «no permission»** | CephX ключ неверен, или пользователь не имеет прав на пул | `ceph auth get client.unikernel`, `ceph osd pool auth get rbd` | Проверить `secretfile=/etc/ceph/secret`, права пользователя `unikernel` на pool `rbd` и directory `/` |
| **qcow2 образ разросся до неожиданного размера** | `cache=writeback` и отсутствие `discard=unmap`, или guest не отправляет TRIM | `qemu-img info /var/lib/libvirt/images/unikernels/my-service-data.qcow2`, `qemu-img check -r all` | Использовать `discard=unmap` и `detect-zeroes=unmap` в XML, или периодически `qemu-img convert -O qcow2 -c` |
| **Kraft Metis snapshot: restore занимает > 1 сек** | Snapshot был создан с dirty state, или образ на rotational HDD | `kraft snapshot ls`, `iostat -x 1` | Убедиться что snapshot создаётся на quiesced FS (`fsfreeze`), использовать SSD для golden images |

## Лучшие практики

### Подготовка хоста

- **RAID/ZD:** Для production используйте RAID 10 (ZFS RAID-Z2/RAID-Z3 для архивов) на storage нодах. Не используйте single-disk для persistent данных.
- **Файловые системы:** XFS для large files (>1 ТБ) и high concurrency. ext4 для совместимости и small files. Включите `noatime,nodiratime` в опциях монтирования для NFS/блочных устройств.
- **SSD/NVMe как default:** Для storage-heavy workloads используйте NVMe over Fabrics (NVMe-oF) или SSD с SLC caching. rotational HDD допустим только для архивов.
- **Libvirt pool:** Создавайте отдельный libvirt storage pool для unikernel образов (`virsh pool-create-as unikernels dir --target /var/lib/libvirt/images/unikernels`). Настройте `pool.autostart` и `pool.build` для автоматического монтирования.
- **Сеть:** Выделите отдельный VLAN или физический интерфейс для storage трафика (NFS, iSCSI, Ceph). Используйте bonding `active-backup` для redundancy.

### Изоляция и производительность

- **IOThreads:** Для storage-heavy workloads назначайте отдельный IOThread на диск, избегайте shared IOThread для >2 дисков. См. [Производительность и тюнинг](./performance_tuning.md).
- **cgroups blkio:** Ограничивайте I/O на уровне libvirt (`<iotune>`), чтобы предотвратить noisy neighbor. Для multi-tenant хостов используйте отдельные cgroups blkio.
- **Virtio queue size:** Увеличивайте `queue-size` для virtio-blk до 256 на high-throughput workloads. Меньше 128 — bottleneck для NVMe.
- **Cache mode:** Используйте `cache=none` + `aio=native` для maximum performance и `cache=writeback` для maximum compatibility. Never `cache=unsafe` в production.

### Резервное копирование и disaster recovery

- **3-2-1 правило:** 3 копии данных, 2 носителя, 1 off-site/offline. Для on-prem: daily backup на NAS, weekly на tape/external HDD, monthly off-site.
- **RPO/RTO baseline:** Определите RPO/RTO для каждого workload. Snapshot-стратегия для RPO=0, rsync/NFS для RPO=1ч, rebuild-from-source для stateless.
- **Immutable backups:** Храните backups в объектном storage с WORM (Write Once Read Many) или на ленте. Защищайте от ransomware/accidental deletion.
- **Restore testing:** Тестируйте восстановление не реже 1 раза в квартал. Документируйте RTO и сравнивайте с целевым.
- **Automated backup:** Используйте cron/systemd timer для rsync и Ceph snapshots. Логируйте все операции в центральный syslog/SIEM.

### Безопасность и compliance

- **Шифрование at rest:** Используйте LUKS2 для блочных устройств, или Ceph built-in encryption (dm-crypt). Для NFS — ограничьте доступ по IP и Kerberos.
- **Изоляция сети:** Storage сети должны быть isolated от user-facing сети. Используйте firewall (`nftables`/`iptables`) для ограничения доступа к NFS (2049), Ceph (6789, 3300), iSCSI (3260).
- **libvirt secrets:** Резервное копирование `/etc/libvirt/secrets` обязательно. Используйте separate pool для sensitive данных с отдельным набором ACL.
- **Audit:** Включите auditd для логирования операций libvirt (`/etc/libvirt/qemu.conf` `audit_log=1`), монтирований NFS/Ceph, и изменений storage pool.

### Мониторинг и алертинг

- **Базовые метрики:** `iostat -x 1` await, %util, `cat /proc/diskstats`, `lsblk -d -o name,rota`, `df -h`, `mount | grep -E 'nfs|ceph'`.
- **Пороги алертов:** Disk queue depth > 32, await > 20ms для SSD, await > 100ms для HDD, NFS stale > 0 в час, Ceph OSD down, iSCSI session disconnected, libvirt pool space < 20%.
- **Скорость репликации:** Мониторьте `rsync` throughput, Ceph recovery speed, NFS latency (`nfsstat -c`).
- **Capacity planning:** Отслеживайте рост данных monthly. Прогнозируйте исчерпание на 3–6 месяцев вперед.

### Изменения в production

- **По одному параметру:** Вносите изменения в storage config, network policies, cgroups по одному параметру за раз. Запускайте baseline performance test до и после.
- **Backout plan:** Перед изменением pool, snapshot или network config имейте rescue-режим: отдельный NFS export для recovery, или live ISO с troubleshooting инструментами.
- **Change management:** Документируйте все изменения storage инфраструктуры. Используйте git для конфигурации libvirt pools, NFS exports, Ceph config.

## Граничные случаи

- **NFSv3 vs NFSv4:** NFSv3 — stateless, проще в troubleshooting, но менее безопасен. NFSv4 — stateful, имеет better locking и performance, но сложнее в отладке при падении сервера. Для production предпочитайте NFSv4.1 или NFSv4.2 с pNFS.
- **Ceph RBD на NVMe vs SSD:** RBD на NVMe даёт >100k IOPS, но требует соответствующей конфигурации (`bluestore_min_alloc_size`). На SSD — 10–50k IOPS. rotational HDD — <500 IOPS. Учитывайте это при capacity planning.
- **qcow2 cow-файлы с backing chain:** Длинная backing chain (>3 уровня) degrades performance. Используйте `qemu-img rebase -f qcow2 -b new_base.qcow2 overlay.qcow2` для сброса. Для immutable images используйте `qcow2` с `-o cluster_size=64K,preallocation=metadata`.
- **iSCSI multipath:** На хостах с dual-NIC настройте multipath (`multipathd`) для redundancy. Без multipath отказ линка = потеря диска. Проверяйте `multipath -ll` регулярно.
- **Guest без поддержки virtio-blk:** Некоторые устаревшие образы используют IDE вместо virtio. Производительность в 5–10 раз ниже. Мигрируйте на virtio-blk или virtio-scsi.
- **Снапшоты на readonly rootfs:** Если guest booted from read-only image, snapshot работает только для writable overlay. Для полного восстановления используйте `qemu-img create -b base.qcow2 -F qcow2 -f qcow2 overlay.qcow2` с immutable base.
- **Storage pool autostart:** При перезагрузке libvirt host pool может не смонтироваться автоматически. Настройте `virsh pool-autostart unikernels` и проверяйте `virsh pool-list --all`.
- **Ceph cluster в mini/micro deployment:** Для <3 OSD Ceph теряет redundancy. Используйте `min_size=1` только для dev/test. Для production — минимум 3 OSD, лучше 5+.
- **Восстановление после полного сбоя хоста:** Имейте disaster recovery runbook: восстановление libvirt pools из NFS, импорт VG из LVM metadata backup, переключение на standby хост. Тестируйте DR не реже 1 раза в год.

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md)
- [Оркестрация и управление](./orchestration_and_management.md)
- [Сеть: продвинутые сценарии](./networking_advanced.md)

### Ссылки
- [LVM — iSCSI Multipath](../../Linux/Networking/iSCSI/iscsi_concepts.md)
- [Ceph — RBD](../../Kubernetes/Storage/Ceph/ceph_rbd_usage/definitions_and_concepts.md)
- [NFS — обзор](../../Linux/Networking/Services/nfs/nfs_setup.md)
- [Virtio — блочные устройства](https://www.linux-kvm.org/page/Virtio)
