# Btrfs (B-Tree Filesystem)

## Определения

**Btrfs** (произносится "butter fs" или "b-tree fs") — современная файловая система с Copy-on-Write (CoW), разработанная Oracle для Linux. Сочетает функции ФС и менеджера томов, обеспечивая встроенные снапшоты, компрессию, дедупликацию и аппаратную избыточность.

**Ключевые понятия:**

- **Copy-on-Write (CoW)** — данные никогда не перезаписываются на месте. Изменения пишутся в новые блоки, а указатели (pointers) обновляются атомарно. Обеспечивает целостность данных при сбоях без двойной записи в журнал.
- **Subvolume (подтом)** — логическое разделение внутри одного пула Btrfs. Каждый subvolume имеет собственное дерево файлов и может быть смонтирован независимо. Subvolumes не резервируют место — они разделяют общий пул.
- **Snapshot** — мгновенный снимок subvolume на основе CoW. Занимает нулевой объём при создании (разделяет блоки с оригиналом). При изменении данных в оригинале или снапшоте затронутые блоки копируются (CoW).
- **B-tree** — основная структура данных для хранения метаданных и данных. Все объекты (файлы, каталоги, extents, снапшоты) хранятся в B-деревьях.
- **Chunk tree** — дерево, отображающее логические адреса на физические устройства (аналог LVM).
- **Checksum tree** — дерево хранения контрольных сумм для данных и метаданных. При каждом чтении проверяется целостность.
- **Space cache** — кэш информации о свободном пространстве для ускорения монтирования. `space_cache=v2` (ядро 5.5+) рекомендуется для NVMe.
- **COW (Copy-on-Write) для данных** — при записи в уже существующий файл создаётся новый extent. Старый extent освобождается после обновления всех указателей.
- **Nodatacow** — опция для отключения CoW на конкретных файлах или каталогах. Необходима для баз данных и виртуальных машин, где случайные записи вызывают фрагментацию.
- ** RAID 5/6 write hole** — нерешённая проблема Btrfs. При сбое питания данные могут оказаться в неконсистентном состоянии. **Не используйте Btrfs RAID 5/6 в production.**
- **Scrub** — фоновая проверка контрольных сумм всех блоков данных. Автоматически восстанавливает данные из зеркальных копий при обнаружении повреждений.
- **Balance** — операция перераспределения блоков между устройствами. Необходима при добавлении/удалении дисков или при фрагментации пространства.

## Основные концепции

### Архитектура

```
┌──────────────────────────────────────────────────┐
│  Приложение (open/read/write/close)               │
├──────────────────────────────────────────────────┤
│  VFS (Virtual File System)                        │
├──────────────────────────────────────────────────┤
│  Btrfs драйвер                                    │
│  ├── Subvolume trees (file data, metadata)        │
│  ├── Checksum tree (data + metadata checksums)    │
│  ├── Chunk tree (logical → physical mapping)      │
│  └── Device tree (физические устройства)          │
├──────────────────────────────────────────────────┤
│  Блочный слой (I/O scheduler, buffer cache)       │
├──────────────────────────────────────────────────┤
│  Физические устройства (sda, sdb, nvme0n1)        │
└──────────────────────────────────────────────────┘
```

**Keyrings:**
- **Root tree** — корень всех метаданных. Содержит указатели на все остальные деревья.
- **Log tree** — журнал для атомарных обновлений (при fsync).
- **Fixup tree** — временное хранилище для незавершённых транзакций.

### Subvolumes vs LVM

| Критерий | Btrfs Subvolumes | LVM Logical Volumes |
| :--- | :--- | :--- |
| **Резервирование места** | Общий пул (thin provisioning по умолчанию) | Фиксированный размер |
| **Снапшоты** | Мгновенные, CoW-based | CoW через LVM snapshot |
| **Компрессия** | Встроенная (Zstd, LZO, Zstd) | Нет |
| **Самовосстановление** | Да (checksums + scrub) | Нет |
| **Shrink** | Да (с ограничениями) | Да (офлайн) |
| **Мультиустройство** | RAID 0/1/10/5/6 |raid через mdadm или LVM RAID |
| **Производительность БД** | Низкая (CoW фрагментация) | Высокая |

### Опции монтирования

| Опция | Описание | Рекомендация |
| :--- | :--- | :--- |
| `compress=zstd` | Прозрачная компрессия (Zstd рекомендуется) | Рекомендуется для данных |
| `compress=lzo` | Компрессия LZO (быстрее, но менее эффективно) | Альтернатива Zstd |
| `noatime` | Отключение обновления времени доступа | Обязательно для production |
| `ssd` | Оптимизация для SSD (TRIM, аллокация) | Для SSD/NVMe |
| `ssd_spread` | Равномерное распределение по SSD | Для больших SSD |
| `discard=async` | Асинхронный TRIM (ядро 5.6+) | Для SSD (предотвращает фризы) |
| `space_cache=v2` | Улучшенный кэш свободного пространства | Рекомендуется (ядро 5.5+) |
| `nodatacow` | Отключение CoW для файлов/каталогов | Для БД, VM |
| `subvol=<name>` | Монтирование конкретного subvolume | Стандарт |
| `subvolid=<id>` | Монтирование по ID subvolume | Альтернатива |

```bash
# Форматирование с оптимальными параметрами
sudo mkfs.btrfs -d raid1 -m raid1 /dev/sdb1 /dev/sdc1
# -d: data profile (raid0, raid1, raid10, single)
# -m: metadata profile (raid0, raid1, raid10, single)

# Монтирование корневого subvolume
sudo mount -o compress=zstd,noatime /dev/sdb1 /mnt/btrfs

# Монтирование конкретного subvolume
sudo mount -o subvol=@data,compress=zstd,noatime /dev/sdb1 /mnt/data
```

### Проверка состояния

```bash
# Просмотр использования пространства
sudo btrfs filesystem usage /mnt/btrfs
# → Overall:
# →     Device size:                  20.00GiB
# →     Device allocated:              2.02GiB
# →     Device unallocated:           17.98GiB
# →     Device slack:                  0.00B
# →     Data, single:                 1.01GiB
# →     Metadata, single:             0.51GiB
# →     System, single:              16.00MiB

# Просмотр списка subvolumes
sudo btrfs subvolume list /mnt/btrfs
# → ID 256 gen 10 top level 5 path @
# → ID 257 gen 15 top level 5 path @home
# → ID 258 gen 20 top level 5 path @data

# Проверка статуса ФС
sudo btrfs filesystem show /dev/sdb1
# → Label: none  uuid: a1b2c3d4-...
# → 	Total devices 2 FS bytes used 2.02GiB
# → 	devid    1 size 10.00GiB used 1.01GiB path /dev/sdb1
# → 	devid    2 size 10.00GiB used 1.01GiB path /dev/sdc1
```

## Практические сценарии

### Создание subvolumes

```bash
# Создание subvolume для данных
sudo btrfs subvolume create /mnt/btrfs/@data

# Создание subvolume для логов
sudo btrfs subvolume create /mnt/btrfs/@logs

# Монтирование subvolume
sudo mount -o subvol=@data,compress=zstd /dev/sdb1 /mnt/data

# fstab для автоматического монтирования
# UUID=... /data btrfs defaults,subvol=@data,compress=zstd,noatime 0 0
# UUID=... /logs btrfs defaults,subvol=@logs,compress=zstd,noatime,nodatacow 0 0
```

### Создание снапшотов

```bash
# Создание read-only снапшота
sudo btrfs subvolume snapshot -r /mnt/btrfs/@data /mnt/btrfs/@data_snapshot_20260917

# Создание read-write снапшота (для клонирования)
sudo btrfs subvolume snapshot /mnt/btrfs/@data /mnt/btrfs/@data_clone

# Просмотр снапшотов
sudo btrfs subvolume list -t /mnt/btrfs
# → ID      GEN     TOP LEVEL       PATH
# → 258     20      5               @data_snapshot_20260917
# → 259     22      5               @data_clone

# Удаление снапшота
sudo btrfs subvolume delete /mnt/btrfs/@data_snapshot_20260917
```

### Бэкапы через send/receive

```bash
# Полный бэкап (полный снапшот)
sudo btrfs subvolume snapshot -r /mnt/btrfs/@data /mnt/btrfs/@backup
sudo btrfs send /mnt/btrfs/@backup | gzip > /backup/full_backup.gz
sudo btrfs subvolume delete /mnt/btrfs/@backup

# Инкрементальный бэкап
sudo btrfs send -p /mnt/btrfs/@backup_old /mnt/btrfs/@backup_new | gzip > /backup/incr_backup.gz

# Отправка на удалённый сервер
sudo btrfs send /mnt/btrfs/@backup | ssh remote_host "sudo btrfs receive /backup/"

# Восстановление
gunzip < /backup/full_backup.gz | sudo btrfs receive /mnt/restore/
```

### Компрессия

```bash
# Включение компрессии на существующем subvolume
sudo btrfs filesystem defragment -r -czstd /mnt/btrfs/@data

# Проверка эффективности компрессии
sudo btrfs filesystem defragment -r -czstd -v /mnt/btrfs/@data 2>&1 | grep "compress"
# → /file1.db: 1048576 -> 65536 (37.50%)

# Компрессия только для конкретных файлов
sudo chattr +c /mnt/btrfs/@data/large_logs.log

# Для каталога (рекурсивно)
sudo chattr -R +c /mnt/btrfs/@data/logs/
```

### Отключение CoW для БД

```bash
# Для PostgreSQL/MySQL данных — отключить CoW
sudo chattr +C /var/lib/postgresql/14/main/
sudo chattr +C /var/lib/mysql/

# Или через mount options для каталога
# В fstab: options для отдельного subvolume
sudo mount -o subvol=@pgdata,nodatacow,compress=zstd /dev/sdb1 /var/lib/postgresql

# Проверка
lsattr /var/lib/postgresql/14/main/
# → --------------C-- /var/lib/postgresql/14/main/base
```

### Scrub (проверка целостности)

```bash
# Запуск scrub
sudo btrfs scrub start /mnt/btrfs

# Проверка статуса scrub
sudo btrfs scrub status /mnt/btrfs
# → scrub started at Tue Sep 17 10:00:00 2026, running for 12 seconds
# → 	total bytes scrubbed: 1.15GiB with 0 errors
# → 	error details: none
# → 	corrected errors: 0, uncorrectable errors: 0, unverified errors: 0

# Автоматический scrub через systemd timer
sudo systemctl enable --now btrfs-scrub.timer

# Просмотр результатов scrub
sudo btrfs scrub status -d /mnt/btrfs
```

### Balance (перераспределение блоков)

```bash
# Базовый balance (перераспределение всех блоков)
sudo btrfs balance start /mnt/btrfs

# Balance с фильтром (только metadata)
sudo btrfs balance start -dusage=50 -musage=50 /mnt/btrfs

# Balance после добавления нового диска
sudo btrfs balance start -dconvert=raid1 -mconvert=raid1 /mnt/btrfs

# Мониторинг progress
sudo btrfs balance start -v /mnt/btrfs
```

### Замена дисков

```bash
# Замена диска в single/dup профиле
sudo btrfs device replace start /dev/old_sdb1 /dev/new_sdc1 /mnt/btrfs

# Проверка статуса
sudo btrfs device replace status /mnt/btrfs
# → Replace target devid 1 with devid 2 (0.02% finished, 0 bytes written)

# Завершение замены
sudo btrfs device replace start -r /dev/old_sdb1 /dev/new_sdc1 /mnt/btrfs

# Удаление старого устройства после замены
sudo btrfs device remove /dev/old_sdb1 /mnt/btrfs
```

### Управление размером

```bash
# Проверка использования по устройствам
sudo btrfs filesystem df /mnt/btrfs
# → Data, single: total=1.01GiB, used=950.00MiB
# → Metadata, dup: total=512.00MiB, used=300.00MiB
# → System, dup: total=16.00MiB, used=64.00KiB

# Изменение размера ФС (расширение)
sudo btrfs filesystem resize max /mnt/btrfs

# Уменьшение (с ограничениями)
sudo btrfs filesystem resize -5G /mnt/btrfs
```

### Диагностика ошибок

```bash
# Проверка ФС (требует отмонтирования)
sudo umount /mnt/btrfs
sudo btrfs check /dev/sdb1

# Принудительное исправление (опасно!)
sudo btrfs check --repair /dev/sdb1

# Более безопасная альтернатива: восстановление данных
sudo btrfs restore /dev/sdb1 /recovery/

# Проверка контрольных сумм на смонтированной ФС
sudo btrfs scrub start -Bd /mnt/btrfs

# Мониторинг ошибок Btrfs в dmesg
sudo dmesg -T | grep -i "btrfs"
# → BTRFS info (device sdb1): scrub: started on devid 1
# → BTRFS warning (device sdb1): checksum error at logical ...
```

## RAID-профили Btrfs

| Профиль | Описание | Мин. устройств | Избыточность |
| :--- | :--- | :--- | :--- |
| `single` | Без избыточности | 1 | Нет |
| `raid0` | Stripe (параллельная запись) | 2 | Нет |
| `raid1` | Зеркалирование | 2 | 1 mirror |
| `raid10` | Stripe + mirror | 4 | 1 mirror per stripe |
| `raid1c3` | Зеркалирование на 3 устройства | 3 | 2 copies |
| `raid1c4` | Зеркалирование на 4 устройства | 4 | 3 copies |
| `raid5` | **Нестабильный** (write hole!) | 3 | 1 parity |
| `raid6` | **Нестабильный** (write hole!) | 4 | 2 parity |

```bash
# Создание RAID1 массива
sudo mkfs.btrfs -d raid1 -m raid1 /dev/sdb1 /dev/sdc1

# Просмотр RAID-профиля
sudo btrfs filesystem show /dev/sdb1
# → 	devid    1 size 10.00GiB used 1.01GiB path /dev/sdb1
# → 	devid    2 size 10.00GiB used 1.01GiB path /dev/sdc1
# → 	fmts:raid1  data:raid1  metadata:raid1

# Изменение профиля
sudo btrfs balance start -dconvert=raid10 -mconvert=raid10 /mnt/btrfs
```

## Сравнение с другими ФС

| Критерий | Btrfs | ext4 | XFS | ZFS |
| :--- | :--- | :--- | :--- | :--- |
| **CoW** | Да | Нет | Нет (reflinks) | Да |
| **Снапшоты** | Да (subvolumes) | Нет (LVM) | Нет (LVM) | Да (datasets) |
| **Компрессия** | Да (Zstd/LZO) | Нет | Нет | Да (LZ4/Zstd) |
| **Checksums** | Да (данные + мета) | Метаданные | Метаданные | Да (данные + мета) |
| **Self-healing** | Да (зеркала) | Нет | Нет | Да (зеркала/RAID-Z) |
| **Встроенный RAID** | Да (0/1/10/5/6*) | Нет | Нет | Да (RAID-Z 1/2/3) |
| **Потребление RAM** | Среднее | Низкое | Низкое | **Высокое** |
| **Shrink** | Да | Да (офлайн) | Нет | Нет |
| **Reflinks** | Да | Нет | Да | Да (OpenZFS 2.2+) |
| **Zircon небезопасен** | **Да** (RAID5/6) | Нет | Нет | Нет |

*RAID 5/6 в Btrfs считаются небезопасными из-за write hole.

## Ограничения и подводные камни

1. **RAID 5/6 небезопасен:** Write hole на уровне метаданных может привести к невосстановимой потере массива. Используйте RAID 1/10 или внешний mdadm.
2. **Фрагментация при CoW:** Базы данных и VM испытывают сильную фрагментацию. Обязательно отключайте CoW (`nodatacow`) для рабочих нагрузок с случайной записью.
3. **`df -h` может показывать неверные данные:** Btrfs использует thin provisioning. Для реального использования проверяйте `btrfs filesystem usage`.
4. **Бэкапы через send/receive:** Инкрементальные бэкапы требуют snapshot-based подхода, что может быть непривычно для администраторов,ustomed к rsync/dump.
5. **Производительность случайной записи:** Btrfs значительно уступает ext4/XFS в random write workloads без отключения CoW.

## Дополнительная информация

### Связанные темы

- [ext4](./ext4.md) — стабильная журналируемая ФС
- [XFS](./xfs.md) — высокопроизводительная ФС для параллельных нагрузок
- [Сравнение типов ФС](./filesystem_types_comparison.md) — сравнительная таблица всех основных ФС
- [Проверка и восстановление ФС](./fsck.md) — e2fsck, xfs_repair, btrfs check
- [Журналирование](./journaling.md) — CoW vs journaling
- [Оптимизация производительности](./performance_tuning.md) — nodatacow, compress, I/O планировщики
- [Обзор RAID и mdadm](./RAID/overview.md) — альтернатива встроенному RAID Btrfs

### Документация

- [Btrfs Wiki](https://btrfs.wiki.kernel.org/) — официальная Wiki
- `man btrfs`, `man mkfs.btrfs`, `man btrfs-check`, `man btrfs-scrub`
- kernel documentation: `Documentation/filesystems/btrfs/` в исходниках ядра
- [Btrfs Feature Matrix](https://btrfs.wiki.kernel.org/index.php/Feature_matrix)
