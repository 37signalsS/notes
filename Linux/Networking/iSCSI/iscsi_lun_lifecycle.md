# iSCSI: Жизненный цикл LUN (создание, расширение, миграция, удаление)

Руководство по управлению LUN на протяжении всего жизненного цикла: от создания до удаления, включая расширение "на лету" и миграцию.

## Определения

| Термин | Описание |
| :--- | :--- |
| **LUN (Logical Unit Number)** | Логический диск, предоставляемый iSCSI-таргетом инициатору. На стороне initiator'а отображается как блочное устройство `/dev/sdX` или `/dev/mapper/mpathX`. |
| **Backstore** | Источник данных для LUN на стороне target. Типы: block (физ. диск), fileio (файл), ramdisk. |
| **Rescan** | Процесс обнаружения изменений в LUN (новые LUN, изменение размера) без переподключения. |
| **LUN Resize (Expansion)** | Увеличение размера LUN без потери данных. Требует: resize на target → rescan на initiator → расширение ФС. |
| **LUN Migration** | Перенос данных с одного LUN на другой. Включает: создание нового LUN → копирование → переключение → удаление старого. |
| **Thin Provisioning** | Виртуальное выделение дискового пространства. Физический объём выделяется по мере записи данных. |
| **Thick Provisioning** | Полное выделение дискового пространства при создании LUN. Все блоки заняты сразу. |
| **LUN Masking** | Ограничение видимости LUN для определённых инициаторов через ACL на target. |

## Управление LUN на стороне Target

### Создание LUN

```bash
# Подключение к targetcli
sudo targetcli

# Навигация
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1

# 1. Создание backstore (block)
/backstores/block create /dev/vg_storage/lv_data1 data1

# 2. Создание backstore (fileio — для тестов)
/backstores/fileio create /var/lib/iscsi/disk1.img 50G true

# 3. Создание LUN, привязанный к backstore
/luns create /backstores/block/data1

# 4. Просмотр созданного LUN
ls /luns
# → lun0

# 5. Настройка ACL (кто может подключаться)
/acl create iqn.2026-07.com.example:node01
/acl create iqn.2026-07.com.example:node02

# 6. Настройка TPG attributes
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 \
  set attribute cache_dynamic_acls=1
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 \
  set attribute demo_mode_write_protect=0

# Выход
exit
```

### Просмотр всех LUN

```bash
# Через targetcli
sudo targetcli
/iscsi ls

# Через sysfs
ls /sys/kernel/config/target/iscsi/*/tpg*/luns/
# → lun0  lun1  lun2

# Информация о конкретном LUN
cat /sys/kernel/config/target/iscsi/iqn.*/tpg1/luns/lun0/size
# → 107374182400  (100 GB в секторах)

# Просмотр backstores
targetcli ls /backstores
```

### Изменение размера LUN (на target)

```bash
# Увеличение LVM LV (источник LUN)
sudo lvextend -L +50G /dev/vg_storage/lv_data1

# Проверка нового размера
sudo lvs /dev/vg_storage/lv_data1
# → LV       VG        Attr       LSize   Pool Origin Data%
# → lv_data1 vg_storage -wi------- 150.00g

# iSCSI LUN автоматически отразит новый размер после rescan на initiator
```

### Удаление LUN

```bash
# ⚠️ ОПАСНО: убедитесь, что все инициаторы отключены!

# 1. Отключение всех сессий
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1 \
  clearconfig true
# или удаление конкретного LUN
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns/luns delete lun0

# 2. Удаление backstore
/backstores/block/delete data1

# 3. Сохранение
saveconfig
exit
```

## Управление LUN на стороне Initiator

### Обнаружение и подключение

```bash
# Discovery всех доступных LUN
sudo iscsiadm -m discovery -t sendtargets -p 192.168.1.200
# → 192.168.1.200:3260,1 iqn.2026-07.com.example:storage.target01

# Login (подключение)
sudo iscsiadm -m node -T iqn.2026-07.com.example:storage.target01 \
  -p 192.168.1.200 --login

# Просмотр подключённых LUN
sudo iscsiadm -m session -P 3
# → iSCSI Transport Type: tcp
# → iSCSI Network Portal: 192.168.1.200:3260,1
# → ...
# → scsi13 : Channel 00 Id 0 Lun 0
# →   Attached scsi disk sda       Type: 00
# → scsi14 : Channel 00 Id 0 Lun 1
# →   Attached scsi disk sdb       Type: 00

# Просмотр новых LUN через sysfs
ls /sys/class/scsi_disk/
# → 0:0:0:0  0:0:1:0  0:0:2:0
```

### Rescan (обнаружение изменений)

```bash
# Полный rescan всех iSCSI-сессий
sudo iscsiadm -m session --rescan

# Rescan конкретного устройства
echo 1 | sudo tee /sys/class/scsi_device/*/device/rescan

# Проверка нового размера
lsblk
sudo blockdev --getsize64 /dev/sda
```

### Расширение ФС после resize LUN

```bash
# 1. Проверка текущего размера
df -h /mnt/data
# → /dev/sda1   100G   45G   50G  48% /mnt/data

# 2. Расширение раздела (если LUN — целый диск без разделов)
sudo growpart /dev/sda 1
# или если LUN = целый диск:
# (не требуется)

# 3. Расширение PV (если используется LVM)
sudo pvresize /dev/sda

# 4. Расширение LV
sudo lvextend -l +100%FREE /dev/vg_data/lv_data

# 5. Расширение ФС
# ext4:
sudo resize2fs /dev/vg_data/lv_data
# xfs:
sudo xfs_growfs /mnt/data

# 6. Проверка
df -h /mnt/data
# → /dev/mapper/vg_data-lv_data   150G   45G  100G  31% /mnt/data
```

### Расширение multipath-устройства

```bash
# 1. Rescan SCSI (все пути к LUN)
for disk in /sys/class/scsi_device/*/device/rescan; do
    echo 1 | sudo tee "$disk"
done

# 2. Перечитать карту multipath
sudo multipath -r

# 3. Проверить новый размер
lsblk | grep mpath

# 4. PV → VG → LV → ФС
sudo pvresize /dev/mapper/mpatha
sudo lvextend -l +100%FREE -r /dev/vg_data/lv_data
```

## Миграция LUN

### Сценарий: миграция данных с одного LUN на другой

```bash
# Исходные данные: LUN /dev/sda → /mnt/data (100 GB)
# Целевой LUN: /dev/sdb (200 GB)

# 1. Подключение нового LUN
sudo iscsiadm -m node -T <NEW_IQN> -p <NEW_IP> --login
sudo iscsiadm -m session --rescan

# 2. Проверка нового устройства
lsblk
# → sdb   200G

# 3. Создание ФС на новом LUN
sudo mkfs.xfs /dev/sdb

# 4. Монтирование временного mount point
sudo mkdir -p /mnt/new_data
sudo mount /dev/sdb /mnt/new_data

# 5. Копирование данных
sudo rsync -avHAXSP --progress /mnt/data/ /mnt/new_data/

# 6. Верификация
sudo diff -r /mnt/data /mnt/new_data
# (если пустой вывод — данные скопированы корректно)

# 7. Обновление /etc/fstab
# Заменить старый LUN на новый:
# БЫЛО: /dev/sda1  /mnt/data  xfs  defaults  0 0
# СТАЛО: /dev/sdb   /mnt/data  xfs  defaults  0 0

# 8. Перемонтирование
sudo umount /mnt/data
sudo umount /mnt/new_data
sudo mount -a

# 9. Проверка
df -h /mnt/data
# → /dev/sdb   200G   45G  150G  23% /mnt/data

# 10. Отключение старого LUN
sudo umount /dev/sda1
sudo iscsiadm -m node -T <OLD_IQN> -p <OLD_IP> --logout
```

### Сценарий: live-миграция без даунтайма

Для критичных сервисов используйте snapshot-based миграцию:

```bash
# 1. Создание LVM snapshot на старом LUN
sudo lvcreate -L 10G -s -n lv_data_snap /dev/vg_data/lv_data

# 2. Монтирование snapshot для копирования
sudo mkdir -p /mnt/snap
sudo mount -o ro /dev/vg_data/lv_data_snap /mnt/snap

# 3. Начальное копирование (rsync)
sudo rsync -avHAXSP /mnt/snap/ /mnt/new_data/

# 4. Отключение snapshot (для финального rsync)
sudo umount /mnt/snap
sudo lvremove -f /dev/vg_data/lv_data_snap

# 5. Финальный rsync (с разницей)
sudo rsync -avHAXSP --delete /mnt/data/ /mnt/new_data/

# 6. Переключение сервисов (brief downtime)
# Остановить сервис, перемонтировать, запустить
```

## Тонкое и толстое provisionирование

### Thin Provisioning

```bash
# На стороне LVM (target)
sudo lvcreate -L 200G -T vg_storage/thin_pool
sudo lvcreate -V 100G -T vg_storage/thin_pool -n lv_data1

# Преимущества: экономия места, гибкость
# Недостаток: danger of overcommitment (данных больше, чем физ. места)
```

### Thick Provisioning

```bash
# Обычное создание LV
sudo lvcreate -L 100G -n lv_data1 vg_storage

# Преимущества: предсказуемость, стабильная производительность
# Недостаток: полное выделение места сразу
```

### Сравнение

| Критерий | Thin | Thick |
| :--- | :--- | :--- |
| **Выделение места** | По мере записи | Полностью сразу |
| **Экономия места** | Да | Нет |
| **Производительность** | Начальная overhead | Стабильная |
| **Overcommitment** | Возможен | Невозможен |
| **Снапшоты** | Быстрые | Требуют space |
| **Production** | С осторожностью | Рекомендуется |

## Диагностика проблем

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| LUN не отображается после rescan | ACL не настроен или LUN не создан | `targetcli .../tpg1/luns ls`, проверить ACL |
| `Device busy` при отключении | ФС примонтирована или process использует | `umount`, `fuser -km /mnt/data`, затем logout |
| `No space left on device` (thin) | Thin pool исчерпан | Расширить thin pool или provisioner |
| `I/O error` после resize | Rescan не выполнен | `iscsiadm -m session --rescan` + `rescan-scsi-bus.sh` |
| `Filesystem larger than device` | ФС расширена, но LUN нет | Проверить реальный размер: `blockdev --getsize64 /dev/sdX` |

## См. также

- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — создание LUN на сервере
- **[Настройка iSCSI Initiator](./iscsi_initiator_setup.md)** — подключение LUN
- **[Настройка Multipath I/O](./iscsi_multipath.md)** — отказоустойчивость путей
- **[Управление LVM](../../FileSystems/LVM/operations/lvm_resize.md)** — расширение LV
- **[SCSI-3 Persistent Reservations](./iscsi_persistent_reservations.md)** — блокировки для доступа
