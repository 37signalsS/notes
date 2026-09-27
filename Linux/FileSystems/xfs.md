# XFS (X File System)

## Определения

**XFS** — высокопроизводительная 64-битная журналируемая файловая система, разработанная SGI для IRIX, а затем портированная в Linux. Становится стандартом для RHEL/CentOS 7+, Fedora, а также для высоконагруженных серверных рабочих нагрузок.

**Ключевые понятия:**

- **Allocation Groups (AG)** — диск делится на независимые группы распределения (по умолчанию по 1 GiB). Каждая AG имеет собственные структуры для управления блоками и inode. Это позволяет параллельным потокам одновременно выделять место без блокировок.
- **Allocation Group locks (AGFL)** — блокировки на уровне AG, обеспечивающие параллелизм. В отличие от ext4, где блокировки на уровне block group, XFS позволяет масштабировать запись на десятки ядер CPU.
- **Inode allocation** — inode выделяются динамически по мере необходимости. Проблема исчерпания inode отсутствует.
- **Extents** — непрерывные диапазоны блоков. XFS использует extent-based выделение с самого начала (в отличие от ext4, который добавил extents позже).
- **B+ tree** — структура данных для хранения extent-карты и каталогов. Каждый каталог в XFS реализован как B+ дерево, что ускоряет поиск в каталогах с миллионами файлов.
- **Log (журнал)** — отдельная область диска (или realtime-девайс) для записи транзакций. Журнал XFS записывает только метаданные; гарантирует, что данные будут сброшены на диск до фиксации метаданных (аналог `data=ordered`).
- **Reflinks (Copy-on-Write на уровне файлов)** — доступны с ядра 4.9+. Позволяют мгновенно клонировать файлы через `cp --reflink` без физического копирования данных. Копия разделяет блоки с оригиналом до момента записи (CoW).
- **Realtime device** — опциональное выделенное устройство для хранения данных с гарантированной пропускной способностью. Журнал и метаданные хранятся на основном устройстве.
- **Stripe unit / stripe width** — параметры для оптимального распределения данных при работе с аппаратными RAID-контроллерами или striped LVM.
- **Unwritten extents** — extents, выделенные для файла, но ещё не записанные (preallocation). При обращении к таким блокам ядро возвращает нули.
- **Coalesceextent** — внутренняя операция объединения смежных extents для снижения фрагментации.

## Основные концепции

### Архитектура

```
┌──────────────────────────────────────────────┐
│  Приложение (open/read/write/close)           │
├──────────────────────────────────────────────┤
│  VFS (Virtual File System)                    │
├──────────────────────────────────────────────┤
│  XFS драйвер (xfs_file_write_inode...)       │
├──────────────────────────────────────────────┤
│  Allocation Groups (AG0, AG1, ...)           │
│  ├── AG0: inode alloc, block alloc, free space│
│  ├── AG1: ...                                 │
│  └── AGn: ...                                 │
├──────────────────────────────────────────────┤
│  Журнал (Log) — отдельная область диска       │
├──────────────────────────────────────────────┤
│  Блочный слой (I/O scheduler, buffer cache)  │
├──────────────────────────────────────────────┤
│  Физическое хранилище                         │
└──────────────────────────────────────────────┘
```

**Параллелизм:** Каждый поток работает со своей Allocation Group, что обеспечивает линейное масштабирование IOPS с ростом числа ядер CPU. На системах с 32+ ядрами XFS значительно превосходит ext4 по производительности параллельной записи.

### Журналирование

XFS записывает в журнал только метаданные. Данные записываются до фиксации транзакции в журнале (гарантируется ядром). Это аналог `data=ordered` в ext4.

**Ключевые особенности:**
- Журнал может быть на основном устройстве (по умолчанию) или на отдельном realtime-устройстве.
- Размер журнала: обычно 256 КБ–64 МБ (автоматически при `mkfs.xfs`).
- При монтировании происходит Log Replay — доигрывание незавершённых транзакций.

### Опции монтирования

| Опция | Описание | Рекомендация |
| :--- | :--- | :--- |
| `noatime` | Отключение обновления времени доступа | Обязательно для production |
| `lazytime` | Отложенный сброс временных меток | Альтернатива `noatime` |
| `allocsize=1M` | Размер preallocation для sequential write | Для больших файлов (логи, медиа) |
| `logbufs=8` | Количество буферов журнала | Увеличение производительности журнала |
| `logbsize=256k` | Размер буфера журнала | Оптимально для high-IOPS |
| `nobarrier` | Отключение барьеров записи | **Только** с BBU/ИБП |
| `discard` | Онлайн TRIM | Для SSD |
| `inode64` | Разрешение выделения inode за пределами 1 TiB | Рекомендуется всегда |
| `ftype=1` | Сохранение type-бита в каталоге (для overlay2) | Обязательно для Docker |
| `reflink=1` | Включение поддержки CoW-клонов | Рекомендуется (ядро 4.9+) |
| `prjquota` | Проектные квоты | Для контейнеров и shared storage |

```bash
# Пример форматирования для Docker overlay2
sudo mkfs.xfs -f -n ftype=1,reflink=1 /dev/sdb1

# Пример fstab для высоконагруженной БД
UUID=... /var/lib/postgresql xfs defaults,noatime,nodiratime,logbsize=256k,allocsize=1M 0 2

# Пример fstab для Docker
UUID=... /var/lib/docker xfs defaults,noatime,nodiratime,ftype=1,reflink=1 0 2
```

### Проверка параметров

```bash
# Просмотр информации о ФС
xfs_info /dev/sdb1
# → meta-data=/dev/sdb1           isize=512    agcount=4, agsize=65536 blks
# →          =                    sectsz=512   attr=2, projid32bit=1
# → data     =                    bsize=4096   blocks=262144, imaxpct=25
# →          =                    sunit=0      swidth=0, blks=0
# → naming   =version 2           bsize=4096   ascii-ci=0 ftype=1
# → log      =internal            bsize=4096   blocks=2560, version=2
# →          =                    sectsz=512   sunit=0 blks, lazy-count=1
# → realtime =none                extsz=4096   blocks=0, rtextents=0
# → reflink  =1

# Проверка ftype и reflink (критично для Docker)
xfs_info /mnt/data | grep -E "ftype|reflink"
# → naming   =version 2              bsize=4096   ascii-ci=0 ftype=1
# → reflink  =1

# Проверка количестваAGMENT groups
xfs_info /dev/sdb1 | grep agcount
```

## Практические сценарии

### Создание и настройка

```bash
# Базовое форматирование
sudo mkfs.xfs /dev/sdb1

# С оптимальными параметрами для БД
sudo mkfs.xfs -f -d su=128k,sw=4 /dev/sdb1
# su: stripe unit (размер chunk RAID)
# sw: stripe width (количество дисков в RAID)

# С ftype=1 для Docker
sudo mkfs.xfs -f -n ftype=1 /dev/sdb1

# С reflink=1 для быстрых клонов
sudo mkfs.xfs -f -m reflink=1 /dev/sdb1

# Монтирование
sudo mount -o noatime /dev/sdb1 /data
```

### Online resize (только расширение)

```bash
# XFS не поддерживает уменьшение (shrink)!
# Только расширение:

# 1. Расширить LV (если LVM)
sudo lvextend -L +50G /dev/vg_data/lv_data

# 2. Расширить XFS (онлайн, без отмонтирования)
sudo xfs_growfs /data

# Проверка
xfs_info /dev/vg_data/lv_data | grep "data     ="
```

### Работа с reflinks

```bash
# Копирование с CoW (мгновенно, без физического копирования)
cp --reflink /mnt/data/large_db_backup.sql /mnt/data/backup_copy.sql

# Проверка поддержки reflinks
xfs_info /mnt/data | grep reflink
# → reflink  =1

# Дедупликация с помощью reflinks
cp --reflink=always original.img clone.img
# original.img и clone.img разделяют блоки до записи
```

### Создание stripe-оптимизированной ФС

```bash
# Для аппаратного RAID-контроллера
# su = chunk size RAID (например, 128K)
# sw = количество дисков в stripe

sudo mkfs.xfs -f -d su=128k,sw=4 /dev/sdb1

# Для striped LVM (lvcreate --stripes 4)
sudo mkfs.xfs -f -d su=64k,sw=4 /dev/vg_data/lv_striped
```

### Диагностика ошибок

```bash
# Проверка ФС (требует отмонтирования)
sudo umount /dev/sdb1
sudo xfs_repair /dev/sdb1

# Принудительное восстановление журнала
sudo xfs_repair -L /dev/sdb1
# -L: обнуление журнала (опасно! только если ФС не монтируется)

# Only check (без исправлений)
sudo xfs_repair -n /dev/sdb1

# Проверка через проброс суперблока
sudo xfs_repair -o bs=4096 /dev/sdb1

# Мониторинг ошибок XFS в dmesg
sudo dmesg -T | grep -i "xfs"
# → XFS (sdb1): Mounting filesystem
# → XFS (sdb1): Starting recovery (log: 2560 blocks)
# → XFS (sdb1): Ending recovery (log: 2560 blocks)
```

### Восстановление удалённых файлов

```bash
# XFS не имеет встроенного механизма восстановления удалённых файлов
# Используйте xfsdump/xfsrestore или xfs_fsr

# Экспорт через xfsdump
sudo xfsdump -L "backup" -f /backup/xfs_dump.img /data

# Восстановление через xfsrestore
sudo xfsrestore -f /backup/xfs_dump.img /data

# Для восстановления конкретных файлов используйте testdisk или photorec
```

###дефрагментация

```bash
# Онлайн-дефрагментация (без отмонтирования)
sudo xfs_fsr /dev/sdb1

# Дефрагментация конкретного файла
sudo xfs_fsr /data/large_file.img

# Проверка фрагментации
sudo xfs_db -r /dev/sdb1 -c "frag" -c "quit"
# → fragment count=1234, free=567, best=432
```

### Перенос ФС между дисками

```bash
# XFS не поддерживает copy (xfs_copy) на уровне ядра
# Используйте rsync или dd

# rsync с сохранением всех атрибутов
sudo rsync -aAXHv --progress /mnt/old_xfs/ /mnt/new_xfs/

# dd (для полного копирования)
sudo dd if=/dev/old_sdb1 of=/dev/new_sdc1 bs=4M status=progress conv=fdatasync
```

## Сравнение с ext4

| Критерий | XFS | ext4 |
| :--- | :--- | :--- |
| **Параллелизм** | Отличный (Allocation Groups) | Ограниченный (block group locks) |
| **Online shrink** | Нет | Да |
| **Online fsck** | Да | Нет |
| **Reflinks** | Да (ядро 4.9+) | Нет |
| **Dynamic inodes** | Да | Нет (фиксированные) |
| **Stripe support** | Нативная (su/sw) | Нет |
| **Квоты** | Нативные (xfs_quota) | Через tune2fs + repquota |
| **Дефрагментация** | Онлайн (xfs_fsr) | Офлайн (e4defrag) |
| **Восстановление удалённых файлов** | Крайне затруднено | Возможно (extundelete) |
| **RHEL/CentOS** | Стандарт с RHEL 7 | Стандарт до RHEL 6 |

## Ограничения и подводные камни

1. **Нет online-shrink:** Расширить можно, уменьшить — нет. Планируйте размер заранее.
2. **Нет встроенного RAID/снапшотов:** Зависимость от LVM или mdadm.
3. **Восстановление удалённых файлов:** Крайне затруднено. Регулярно делайте бэкапы.
4. **ftype=1 обязателен для Docker:** Без него overlay2 не работает корректно (отсутствует d_type support).
5. **stripe unit/width:** Неправильные значения снижают производительность на RAID. Проверяйте через `xfs_info`.

## Дополнительная информация

### Связанные темы

- [ext4](./ext4.md) — альтернативная журналируемая ФС
- [Btrfs](./btrfs.md) — CoW-ФС с снапшотами и компрессией
- [Сравнение типов ФС](./filesystem_types_comparison.md) — сравнительная таблица всех основных ФС
- [Проверка и восстановление ФС](./fsck.md) — e2fsck, xfs_repair, btrfs check
- [Журналирование](./journaling.md) — JBD2, CIL, CoW
- [Оптимизация производительности](./performance_tuning.md) — noatime, barrier, I/O планировщики
- [Дисковые квоты](./disk_quotas.md) — настройка квот для XFS
- [Stratis](./stratis.md) — менеджер хранилищ на основе XFS

### Документация

- [XFS.org](https://xfs.org/) — официальный сайт
- `man xfs`, `man mkfs.xfs`, `man xfs_repair`, `man xfs_info`
- kernel documentation: `Documentation/filesystems/xfs/` в исходниках ядра
- [XFS FAQ](https://xfs.org/index.php/XFS_FAQ)
