# NFS: Выбор файловой системы для сервера

---

## Определения

**Файловая система NFS-сервера** — базовая ФС, на которой хранятся данные, экспортируемые по NFS. Выбор ФС напрямую влияет на производительность, надёжность и возможности управления (квоты, снапшоты, восстановление).

**XFS** — высокопроизводительная журналируемая ФС, оптимизированная для параллельного ввода-вывода и больших объёмов данных. Нативно поддерживает project quotas, online defrag, проектные квоты.

**ext4** — зрелая журналируемая ФС с широкой поддержкой. Поддерживает квоты через внутренний механизм ( journaled) или классические файлы `aquota.*`.

**btrfs** — ФС с(copy-on-write), снапшотами, дедупликацией и встроенной репликацией (send/receive). Активно развивается для NFS-серверов.

---

## Теоретический блок

### Сравнение XFS и ext4 для NFS-сервера

| Характеристика | XFS | ext4 |
| :--- | :--- | :--- |
| **Производительность (мелкие файлы)** | Высокая (аллокация extents) | Средняя |
| **Производительность (крупные файлы)** | Отличная | Хорошая |
| **Производительность (параллельная запись)** | Отличная (аллокатор Allocation Groups) | Средняя (ограничения journal) |
| **Максимальный размер ФС** | 8 ЭБ | 1 ЭБ |
| **Максимальный файл** | 8 ЭБ | 16 ТБ |
| **Квоты** | Нативные (uquota, gquota, pquota) | Внутренние ( journaled) или классические |
| **Снапшоты** | Нет (через LVM/ZFS/Btrfs) | Нет (через LVM) |
| **Онлайн-дефрагментация** | Да (`xfs_fsr`) | Да (`e4defrag`) |
| **Ресайз (расширение)** | Только онлайн, без уменьшения | Онлайн и оффлайн |
| **Журнал** | Отдельный или встроенный | Встроенный |
| **Стабильность** | Очень высокая | Очень высокая |
| **Рекомендация для NFS** | **Предпочтительно** | Подходит для中小型 сред |

### Когда выбирать XFS

- **Высоконагруженные NFS-серверы** с параллельным доступом множества клиентов
- **Крупные объёмы данных** (> 10 ТБ)
- **Работа с большими файлами** (видео, базы данных, бэкапы)
- **Требуются project quotas** (для изоляции директорий)
- **Кластерные среды** (GFS2 на базе XFS)

### Когда выбирать ext4

- **中小型 среды** (< 10 ТБ)
- **Простота администрирования** и мониторинга
- **Необходимость online-resize** (включая уменьшение)
- **Совместимость** со старыми системами и инструментами
- **Множество мелких файлов** ( journaling работает быстрее)

### btrfs для NFS-сервера

| Преимущество | Описание |
| :--- | :--- |
| **Снапшоты** | Мгновенные снимки данных без остановки NFS |
| **Дедупликация** | Экономия места при хранении похожих данных |
| **Отправка/получение** | Инкрементальная репликация между серверами |
| **Встроенная проверка целостности** | Checksumming всех данных и метаданных |
| **Онлайн-ресайз** | Расширение и сжатие без остановки |

**Ограничения:** btrfs NFS-сервер может иметь проблемы с производительностью при heavy random writes. Рекомендуется для archival/backup-сценариев.

---

## Практический блок

### Форматирование и настройка XFS

```bash
# Создание раздела
sudo mkfs.xfs -f /dev/sdb1

# Монтирование с оптимальными опциями для NFS
sudo mount -t xfs -o noatime,nodiratime,logbufs=8,logbsize=256k /dev/sdb1 /srv/nfs/data

# В /etc/fstab (постоянное монтирование):
/dev/sdb1  /srv/nfs/data  xfs  defaults,noatime,nodiratime,logbufs=8,logbsize=256k  0  0
```

#### Оптимизация XFS для NFS

```bash
# Увеличение размера лог-буфера (для heavy writes)
sudo mount -o remount,logbufs=8,logbsize=256k /srv/nfs/data

# Включение inode allocation по умолчанию
sudo mkfs.xfs -f -i size=512 /dev/sdb1  # 512-byte inodes (по умолчанию 256)

# Проверка текущих опций
xfs_info /srv/nfs/data
```

### Форматирование и настройка ext4

```bash
# Создание раздела с внутренними квотами
sudo mkfs.ext4 -O quota /dev/sdb1

# Монтирование
sudo mount -t ext4 -o noatime,nodiratime,data=writeback,barrier=0 /dev/sdb1 /srv/nfs/data

# В /etc/fstab:
/dev/sdb1  /srv/nfs/data  ext4  defaults,noatime,nodiratime,data=writeback,barrier=0,usrquota,grpquota  0  2
```

#### Оптимизация ext4 для NFS

```bash
# Включение внутренних квот (на отмонтированной ФС)
sudo tune2fs -O quota /dev/sdb1

# Увеличение journal size (для heavy writes)
sudo tune2fs -J size=512 /dev/sdb1

# Отключение barrier (только при наличии BBU на RAID-контроллере)
sudo tune2fs -o journal_data_writeback /dev/sdb1

# Проверка настроек
sudo tune2fs -l /dev/sdb1 | grep -E "Journal|Quota|Block size"
```

### Настройка NFS-экспорта для выбранной ФС

#### XFS

```text
# /etc/exports
/srv/nfs/data 10.0.0.0/24(rw,sync,no_subtree_check,no_root_squash,async)
```

**Рекомендации:**
- Используйте `sync` для критичных данных (БД)
- Используйте `async` для временных файлов/логов (только с BBU)
- `no_subtree_check` рекомендуется для целых разделов

#### ext4

```text
# /etc/exports
/srv/nfs/data 10.0.0.0/24(rw,sync,no_subtree_check,no_root_squash)
```

**Рекомендации:**
- Аналогично XFS
- Для квот: `repquota -aus /srv/nfs/data`

### Настройка квот для NFS-клиентов

#### XFS (проектные квоты)

```bash
# На сервере:
# 1. Определение проекта
echo "100:/srv/nfs/data/team1" | sudo tee -a /etc/projects
echo "team1:100" | sudo tee -a /etc/projid

# 2. Инициализация
sudo xfs_quota -x -c 'project -s team1' /srv/nfs/data

# 3. Установка лимита (10 ГБ)
sudo xfs_quota -x -c 'limit -p bhard=10g team1' /srv/nfs/data

# 4. Проверка
sudo xfs_quota -x -c 'report -h -p' /srv/nfs/data
```

#### ext4 (внутренние квоты)

```bash
# На сервере:
# 1. Установка лимита для пользователя
sudo setquota -u nfsnobody 8G 10G 0 0 /srv/nfs/data

# 2. Проверка
sudo repquota -aus /srv/nfs/data
```

### Мониторинг состояния ФС

```bash
# XFS
xfs_info /srv/nfs/data
xfs_db -r -c "freesp -s" /dev/sdb1
sudo xfs_fsr /srv/nfs/data  # дефрагментация

# ext4
sudo tune2fs -l /dev/sdb1 | grep -E "Free|Block count"
sudo e4defrag /srv/nfs/data

# Общие команды
df -hT /srv/nfs/data
du -sh /srv/nfs/data/*
iostat -xz 1
```

---

## Дополнительная информация

### Миграция между ФС

```bash
# Миграция с ext4 на XFS (без даунтайма через rsync):
# 1. Подготовка нового диска
sudo mkfs.xfs -f /dev/sdc1
sudo mkdir -p /mnt/new_nfs
sudo mount /dev/sdc1 /mnt/new_nfs

# 2. Репликация данных
sudo rsync -avz --progress /srv/nfs/data/ /mnt/new_nfs/

# 3. Остановка NFS
sudo systemctl stop nfs-server

# 4. До-репликация (delta)
sudo rsync -avz --delete /srv/nfs/data/ /mnt/new_nfs/

# 5. Переключение
sudo umount /srv/nfs/data
sudo umount /mnt/new_nfs
sudo mount /dev/sdc1 /srv/nfs/data

# 6. Запуск NFS
sudo systemctl start nfs-server
```

### Рекомендации для production

| Сценарий | Рекомендуемая ФС | Опции монтирования |
| :--- | :--- | :--- |
| **Общее хранилище** | XFS | `noatime,nodiratime,logbufs=8` |
| **Базы данных на NFS** | XFS | `noatime,sync,logbufs=8` |
| **Логи/временные файлы** | ext4 | `noatime,data=writeback` |
| **Бэкапы** | XFS или btrfs | `noatime` (btrfs: `compress=zstd`) |
| **Медиа/видео** | XFS | `noatime,allocsize=1m` |
| **Dev/Test** | ext4 | `defaults` |

### Чеклист выбора ФС

- [ ] Определён объём данных (< 10 ТБ → ext4, > 10 ТБ → XFS)
- [ ] Определён тип нагрузки (heavy random I/O → XFS, sequential → XFS/ext4)
- [ ] Проверена необходимость квот (project quotas → XFS)
- [ ] Проверена необходимость снапшотов (btrfs или LVM)
- [ ] Проверена совместимость с DRBD/Pacemaker (обе ФС поддерживаются)
- [ ] Настроены оптимальные опции монтирования
- [ ] Протестирована производительность (fio)

### Связанные темы

- **[NFS: Основные концепции](./index.md)** — архитектура и версии NFS.
- **[NFS: Настройка сервера](./nfs_setup.md)** — конфигурация сервера.
- **[NFS: Квоты](../../../../Linux/FileSystems/disk_quotas.md)** — настройка квот.
- **[NFS: HA](./nfs_ha.md)** — выбор ФС для кластеров.
- **[NFS: Производительность](./nfs_performance.md)** — тюнинг.
