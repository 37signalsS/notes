# Резервное копирование и восстановление в Linux

## Определения

- **Резервное копирование (Backup):** Процесс создания копий данных для их последующего восстановления в случае потери, повреждения или кибератаки.
- **Восстановление (Recovery):** Процесс возврата данных, приложений или всей системы в работоспособное состояние из резервных копий.
- **Консистентность данных (Data Consistency):** Состояние данных, при котором они внутренне согласованы. Различают **Crash-consistent** (состояние как после внезапного выключения) и **Application-consistent** (приложение сбросило все буферы на диск).
- **RPO (Recovery Point Objective):** Целевая точка восстановления; максимально допустимый период потери данных (например, "не более 15 минут данных").
- **RTO (Recovery Time Objective):** Целевое время восстановления; максимально допустимый простой системы.
- **Правило 3-2-1-1-0:** Современная интерпретация классического правила: 3 копии, на 2 разных носителях, 1 копия вне площадки (Off-site), 1 копия неизменяемая (Immutable/WORM) или в изолированном контуре (Air-gap), 0 ошибок после тестирования восстановления.
- **Неизменяемость (Immutability):** Защита бэкапа от удаления или модификации (включая администратора) на определенный срок.
- **GFS (Grandfather-Father-Son):** Стратегия ротации бэкапов: ежедневные (Son), еженедельные (Father), ежемесячные (Grandfather) копии с разными сроками хранения.
- **Синтетический полный (Synthetic Full):** Полная копия, созданная на стороне хранилища из последнего полного бэкапа и последующих инкрементальных. Ускоряет восстановление, так как не требует наличия всей цепочки.
- **Quiesce / fsfreeze:** Механизм «заморозки» I/O приложения или файловой системы перед созданием снапшота для получения application-consistent копии.
- **Каталог бэкапа (Backup Catalog):** Индекс всех архивов, содержащих метаданные (дата, тип, размер, checksum), необходимый для поиска и восстановления конкретных файлов.
- **Верификация (Verification):** Процесс проверки целостности бэкапа (checksum, пробное восстановление) для подтверждения, что копия пригодна для использования.

## Основные концепции

### Уровни защиты данных

В зависимости от инфраструктуры применяются разные подходы:

1.  **Уровень гипервизора (VM Snapshots):** Бэкап всей виртуальной машины целиком. Позволяет восстановить систему за минуты ("Full VM Restore"), но требует больших объемов хранения.
2.  **Уровень файловой системы (Snapshots):** Использование возможностей ZFS, Btrfs или LVM. Мгновенное создание снимков без влияния на производительность.
3.  **Уровень приложения (Database/App Backup):** Использование нативных инструментов (например, `pg_dump` для PostgreSQL). Гарантирует 100% консистентность на логическом уровне.
4.  **Уровень файлов (File-level):** Копирование конкретных директорий и файлов (например, через `rsync` или `borg`).

### Стратегии и типы копий

- **Полный (Full):** Все выбранные данные. Долго, надежно.
- **Инкрементальный (Incremental):** Только изменения с момента *последнего* бэкапа. Экономит место, но восстановление требует всей цепочки.
- **Дифференциальный (Differential):** Только изменения с момента *последнего полного* бэкапа. Проще восстанавливать, чем инкрементальный.
- **Синтетический полный:** Создается на стороне сервера бэкапов путем объединения старого полного бэкапа и новых инкрементальных (используется в Borg и Restic).

### Охват бэкапа (Scope)

Не все данные равноценны. Определение охвата — первый шаг перед выбором инструмента.

**Что включать в бэкап:**
- **Системные конфигурации:** `/etc/`, `/root/`, `/usr/local/`
- **Данные приложений:** `/var/www/`, `/var/lib/`, `/srv/`, `/opt/`
- **Базы данных:** Дампы или WAL-архивы (не сами файлы БД без quiesce)
- **Состояние пакетов:** `dpkg --get-selections`, `rpm -qa`, список Snap-пакетов
- **Разметка дисков:** `sfdisk -d /dev/sda > partition_table.sfdisk`
- **Загрузчик:** `/boot/` (ядро + initramfs), GRUB configuration
- **Сетевые конфигурации:** `/etc/network/interfaces`, `/etc/netplan/`, `/etc/firewall/`
- **Сертификаты и ключи:** `/etc/ssl/`, `/etc/letsencrypt/`, SSH-ключи (с осторожностью)

**Что исключать (важно для компактности и безопасности):**
- `/proc/`, `/sys/`, `/dev/`, `/run/` — виртуальные ФС, не восстановимые
- `/tmp/`, `/var/tmp/` — временные файлы
- Кэш пакетных менеджеров: `/var/cache/apt/`, `/var/cache/dnf/`
- Браузерные кэши, логи (если не требуются для compliance)
- `.git/` репозитории (восстанавливаются из Git)

### Retention Policy (Политика хранения)

Политика определяет, как долго хранить бэкапы разных типов.

**GFS (Grandfather-Father-Son) — классика:**
| Период | Тип | Хранить | Пример |
| :--- | :--- | :--- | :--- |
| Ежедневно | Differential / Incremental | 7–14 дней | Son |
| Еженедельно | Full | 4–8 недель | Father |
| Ежемесячно | Full | 6–12 месяцев | Grandfather |
| Ежегодно | Full | 3–7 лет | Архив |

**Реализация в Borg:**
```bash
# Создание с тегами для ротации
borg create --comment daily /backup/borg::$(date +%Y%m%d) /data
borg prune --list --keep-daily=7 --keep-weekly=4 --keep-monthly=12 /backup/borg
```

### Сжатие: trade-offs

| Алгоритм | Скорость | Степень сжатия | Потребление CPU | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **gzip** | Быстро | Средняя (2:1–3:1) | Низкая | По умолчанию для сетевых бэкапов |
| **lz4** | Очень быстро | Низкая (2:1) | Очень низкая | Для SSD/NVMe, где важна скорость |
| **zstd** | Быстро | Высокая (3:1–5:1) | Средняя | Оптимальный баланс для большинства сценариев |
| **xz** | Медленно | Высокая (4:1–6:1) | Высокая | Для холодного хранения (archival) |

### Шифрование и управление ключами

Шифрование бэкапа бесполезно без защиты ключа.

**Правила хранения ключей:**
1. **Никогда не храните ключ рядом с бэкапом.** Если бэкап украдут, ключ не должен быть доступен.
2. **Ключ = секрет.** Используйте менеджер секретов (Vault, `pass`, Hardware Security Module).
3. **Резервная копия ключа:** Сделайте 2–3 бумажные копии ключевой фразы, храните в сейфе.
4. **Разделение ответственности:** В организациях используйте Shamir's Secret Sharing для разделения ключа между DBA и Security.

**Пример: Borg с отдельным ключом:**
```bash
# Инициализация репозитория с ключом вне репозитория
export BORG_PASSPHRASE="$(pass show backup/borg-repo)"
borg init --encryption=repokey /backup/borg-repo

# Проверка: ключ хранится в ключringe, а не в репозитории
borg info /backup/borg-repo
# → Keyfile: /home/user/.config/borg/keys/...
```

### fsfreeze: согласованные снапшоты ФС

Для application-consistent снапшотов на уровне ФС используйте `fsfreeze` (ext4, XFS) или `xfs_freeze` (XFS-specific).

```bash
# Заморозка ФС (блокировка новых записей)
sudo fsfreeze -f /mnt/data

# Создание снапшота (LVM, ZFS)
sudo lvcreate -L 5G -s -n snap_data /dev/vg0/data

# Разморозка ФС
sudo fsfreeze -u /mnt/data
```

> **Важно:** `fsfreeze` работает только при условии, что ФС смонтирована read-write и не используется как корневая. Для корневой ФС используйте `xfs_freeze` во время early boot или через `systemd`-сервис.

### Каталог и индексация бэкапов

Без каталога бэкап бесполезен: вы не сможете быстро найти нужный файл в 100-архивном хранилище.

**Практические требования к каталогу:**
- Имя архива содержит дату и тип: `2026-09-13_full_etc.tar.zst`
- Храните manifest-файл (список файлов с размерами и checksum) отдельно от архива
- Используйте `tar --index-file` или перенаправляйте `tar -tvf` в файл
- Для Borg/Restic: `borg list` и `restic ls` — это и есть каталог

## Практические сценарии

### 1. Классические инструменты (`tar`, `dd`, `rsync`)

Эти инструменты являются базовыми и предустановлены почти везде.

- **`tar` с инкрементами:**
  ```bash
  # Создание с метаданными (.snar)
  tar -cvzf backup-$(date +%F).tar.gz -g backup.snar /etc /var/www
  ```
- **`dd` для клонирования дисков:**
  ```bash
  # Клонирование sda в сжатый образ
  sudo dd if=/dev/sda status=progress | gzip -c > sda_image.gz
  ```
- **`rsync` для зеркалирования:**
  ```bash
  rsync -avzP --delete /src/ user@remote:/dst/
  ```

#### Файловое копирование (`cp`, `scp`, `rsync`)

Файловый уровень (file-level) — базовый метод резервного сохранения: создание точной копии каталога на другом разделе или узле. Задача формулируется как перенос каталога целиком, включая разрешения доступа, информацию о владении и прочие метаданные — с целью бэкапа либо с целью переноса каталога на другой раздел или узел (например, выделение домашнего каталога на отдельный раздел).

**Почему штатное копирование не годится для бэкапа.** При обычном копировании (`cp` без опций сохранения, `scp`) создаются новые объекты файловой системы, и метаданные источника не переносятся:

- **Разрешения доступа:** новый файл создаётся с правами источника за вычетом setuid/setgid/sticky-битов, после чего ОС применяет `umask` (или default ACL) — итоговые права могут оказаться строже исходных. (Для справки: новые объекты, создаваемые иными средствами, получают права из `umask`: `0777 & ~umask` для каталогов и `0666 & ~umask` для файлов — биты исполнения для файлов не устанавливаются.)
- **Владелец и группа:** пользователь, запустивший копирование, и его первичная группа; сохранить исходного владельца может только root.
- **Временные метки:** устанавливаются в момент копирования, а не сохраняются исходные.
- **Ссылки:** `cp` разыменовывает символические ссылки по умолчанию только при нерекурсивном копировании; `cp -r` копирует симлинки как ссылки, но жёсткие ссылки разрываются — каждая становится отдельным файлом с новым inode.
- **Расширенные атрибуты (xattr) и контексты SELinux** не переносятся.
- Если целевая файловая система не поддерживает атрибуты (FAT32, exFAT), ни одна из опций не поможет.

**Опции сохранения атрибутов** — соответствие `cp` и `rsync`:

| Что сохраняется | `cp` | `rsync` |
| :--- | :--- | :--- |
| Рекурсивное копирование | `-r` | `-r` |
| Символические ссылки как ссылки (без разыменования) | `-d` (`-P`) | `-l` (входит в `-a`) |
| Жёсткие ссылки как ссылки | входит в `-a` (`--preserve=links`) | `-H` |
| Разрешения доступа (mode, включая ACL) | `--preserve=mode` (входит в `-p`) | `-p` |
| Временные метки (atime/mtime) | `--preserve=timestamps` (входит в `-p`) | `-t` |
| Владелец и группа | `--preserve=owner,group` (входит в `-p`) | `-o -g` |
| Файлы устройств и специальные файлы | копируются по умолчанию с `-r` | `-D` (входит в `-a`) |
| Расширенные атрибуты и контекст SELinux | `--preserve=context,xattr` (входит в `-a`) | `-X` |
| Архивный режим | `-a` (= `-dR --preserve=all`) — включает всё перечисленное выше | `-a` (= `-rlptgoD`) — не включает `-H`, `-A`, `-X` |
| Полное сохранение метаданных | `-a` | `-aHAX` |

**Роль rsync.** В отличие от `cp`/`scp`, rsync умеет быструю синхронизацию каталогов: перед переносом он сравнивает файлы на источнике и приёмнике по конфигурируемым атрибутам (размер и время модификации; опционально — контрольные суммы) и передаёт только различия (дельта-алгоритм). Это удобно для поддержания двух местоположений в синхронном состоянии, репликации данных между серверами, создания зеркал ресурсов и регулярного резервного сохранения (источник — оригинал, приёмник — копия); на этой возможности базируются готовые решения (например, `rsnapshot`) и самописные скрипты. По сети rsync по умолчанию работает поверх SSH (при указании путей вида `user@host:`), используя механизм обмена ключами. `scp` — простое копирование поверх SSH без синхронизации: при каждом запуске файлы передаются целиком.

**Практический сценарий: копирование каталога с сохранением атрибутов.**

```bash
# Подготовка данных (chown требует прав root)
mkdir -p work/sub
echo "test" > work/file1
echo "test" > work/sub/file2
chmod 660 work/file1
sudo chown someuser:somegroup work/file1

# 1) Штатное копирование — метаданные не переносятся (при umask 0022)
mkdir -p backup
cp -r work backup/
ls -l backup/work/file1
# → -rw-r----- 1 <текущий пользователь> <его группа> ... file1
# права 660 стали 640: к правам источника применилась umask;
# владелец — тот, кто запустил копирование, а не someuser

# 2) Архивное копирование — метаданные сохраняются
rm -rf backup/work
sudo cp -a work backup/
ls -l backup/work/file1
# → -rw-rw---- 1 someuser somegroup ... file1
```

Аналогично работает rsync — локально и по сети (завершающий слеш в источнике означает «содержимое каталога», см. [rsync](./rsync.md)):

```bash
# Локально
rsync -a work/ backup/work/

# По SSH с полным сохранением метаданных (ACL, xattrs, жёсткие ссылки)
rsync -aHAX work/ user@backup-server:/backup/work/
```

**Валидация.** Сравните атрибуты источника и копии: `ls -l` (права, владелец), `stat` (временные метки), `ls -li` (жёсткие ссылки — совпадение inode у связанных файлов), `getfacl` и `ls -Z` (ACL и SELinux-контексты).

**Типичные ошибки:**
- Права строже исходных — применилась `umask`; используйте `cp -a` или `rsync -a`.
- Владелец не сохранился — копирование выполнено не от root.
- Жёсткие ссылки разорвались — rsync без `-H`.
- ACL или контексты SELinux потеряны — rsync без `-A`/`-X`.

Подробнее: опции `cp` — [Файловые операции](../Shell/file_operations.md), rsync — [rsync — синхронизация файлов](./rsync.md), перенос домашнего каталога — [Миграция пользователей](./Users/user_migration.md).

### 2. Снимки на уровне ФС (LVM, ZFS)

- **LVM Snapshot:**
  ```bash
  # Создание снимка размером 5G для тома my_lv
  sudo lvcreate -L 5G -s -n my_lv_snap /dev/vg0/my_lv
  # После копирования данных снимок необходимо удалить:
  sudo lvremove /dev/vg0/my_lv_snap
  ```
  *Подробнее: **[LVM — снимки](../FileSystems/LVM/snapshots.md)**.*

### 3. Современные инструменты с дедупликацией (Borg, Restic, Kopia)

Это стандарт 2025–2026 годов для эффективного хранения.

- **BorgBackup (через Borgmatic):**
  Borgmatic — это YAML-обертка над Borg, упрощающая конфигурацию.
  ```bash
  # Запуск бэкапа по конфигу
  borgmatic --config /etc/borgmatic/config.yaml
  ```
- **Restic (Бэкап в S3):**
  ```bash
  # Инициализация и бэкап
  export RESTIC_REPOSITORY="s3:s3.amazonaws.com/my-bucket"
  restic backup /data
  ```

### 4. Аварийное восстановление (Bare Metal Recovery)

Инструменты для восстановления ОС на новое оборудование ("с нуля").

- **ReaR (Relax-and-Recover):** Генерирует загрузочный ISO и восстанавливает разметку дисков и данные.
  ```bash
  # Создание образа восстановления
  sudo rear mkrescue
  ```
- **Clonezilla:** Побайтовое или посекторное клонирование. Идеально для массового развертывания идентичных станций.

### 5. Бэкап состояния системы (System State)

Помимо данных, резервную копию должны иметь конфигурации, без которых восстановление невозможно.

```bash
#!/bin/bash
# /usr/local/bin/system_state_backup.sh
# Создание archive с состоянием системы (не данные!)
set -euo pipefail

BACKUP_DIR="/backup/system_state"
DATE=$(date +%F)
mkdir -p "$BACKUP_DIR"

# 1. Разметка дисков
sfdisk -d /dev/sda > "$BACKUP_DIR/partition_table_$DATE.sfdisk"
sfdisk -d /dev/sdb >> "$BACKUP_DIR/partition_table_$DATE.sfdisk"

# 2. Список пакетов (Debian/Ubuntu)
dpkg --get-selections > "$BACKUP_DIR/pkglist_$DATE.txt"
apt-mark showmanual >> "$BACKUP_DIR/pkglist_$DATE.txt"

# RHEL/CentOS/Fedora:
# rpm -qa > "$BACKUP_DIR/pkglist_$DATE.txt"

# 3. Список сервисов systemd
systemctl list-unit-files --type=service --state=enabled > "$BACKUP_DIR/services_$DATE.txt"

# 4. GRUB конфигурация
cp -a /boot/grub/grub.cfg "$BACKUP_DIR/"
cp -a /etc/default/grub "$BACKUP_DIR/"

# 5. Сетевые конфигурации
cp -a /etc/network/interfaces "$BACKUP_DIR/" 2>/dev/null || true
cp -a /etc/netplan/ "$BACKUP_DIR/" 2>/dev/null || true
cp -a /etc/firewall/ "$BACKUP_DIR/" 2>/dev/null || true

# 6. Работа с зеркалами (MDADM)
mdadm --detail --scan > "$BACKUP_DIR/mdadm_$DATE.conf"

# 7. LVM метаданные
vgcfgbackup -f "$BACKUP_DIR/vgcfg_$DATE" vg0

# 8. Архивация
tar -C / -czf "$BACKUP_DIR/system_state_$DATE.tar.gz" \
  --exclude=/proc --exclude=/sys --exclude=/dev \
  --exclude=/run --exclude=/tmp --exclude=/mnt \
  etc/root/var/backup

echo "System state backup completed: $BACKUP_DIR/system_state_$DATE.tar.gz"
```

### 6. Бэкап баз данных

Бэкап на уровне файлов (`rsync /var/lib/postgresql`) не гарантирует консистентность. Используйте нативные инструменты.

**PostgreSQL — `pg_dump` / `pg_dumpall`:**
```bash
# Логическая копия одной базы (не блокирует чтение)
sudo -u postgres pg_dump -Fc -f /backup/mydb_$(date +%F).dump mydb

# Все базы + роли
sudo -u postgres pg_dumpall -g > /backup/globals_$(date +%F).sql

# Восстановление:
sudo -u postgres pg_restore -d mydb /backup/mydb_2026-09-13.dump
```

**PostgreSQL — `pgBackRest` (рекомендуется для production):**
```bash
# Настройка stanza
sudo -u postgres pgbackrest --stanza=main stanza-create

# Полный бэкап
sudo -u postgres pgbackrest --stanza=main backup --type=full

# Инкрементальный
sudo -u postgres pgbackrest --stanza=main backup --type=incr

# Восстановление:
sudo systemctl stop postgresql
sudo -u postgres pgbackrest --stanza=main restore
sudo systemctl start postgresql
```

**MySQL / MariaDB — `mysqldump`:**
```bash
# Дамп одной базы
mysqldump --single-transaction --routines --triggers \
  -u root -p mydb > /backup/mydb_$(date +%F).sql

# Восстановление:
mysql -u root -p mydb < /backup/mydb_2026-09-13.sql
```

**MySQL — `xtrabackup` (физический бэкап, быстрее для больших БД):**
```bash
# Полный бэкап (InnoDB)
xtrabackup --backup --target-dir=/backup/xtrabackup/full

# Подготовка (apply log)
xtrabackup --prepare --target-dir=/backup/xtrabackup/full

# Восстановление:
systemctl stop mysql
rm -rf /var/lib/mysql/*
xtrabackup --copy-back --target-dir=/backup/xtrabackup/full
chown -R mysql:mysql /var/lib/mysql
systemctl start mysql
```

### 7. BorgBackup: нативный usage (без Borgmatic)

Borgmatic удобен, но понимание нативного Borg необходимо для отладки и нестандартных сценариев.

```bash
# Инициализация репозитория (на внешнем диске или SSH)
borg init --encryption=repokey /mnt/backup/borg-repo

# Создание архива
borg create --stats --compression zstd \
  /mnt/backup/borg-repo::$(date +%Y%m%d-%H%M) \
  /etc /var/www /home

# Список архивов
borg list /mnt/backup/borg-repo

# Просмотр содержимого архива
borg list /mnt/backup/borg-repo::20260913-0200 /etc/

# Извлечение всего архива
borg extract /mnt/backup/borg-repo::20260913-0200

# Извлечение одного файла
borg extract /mnt/backup/borg-repo::20260913-0200 etc/nginx/nginx.conf

# Проверка целостности
borg check /mnt/backup/borg-repo

# Ротация (prune)
borg prune --list --keep-daily=7 --keep-weekly=4 --keep-monthly=12 \
  /mnt/backup/borg-repo
```

### 8. Restic: локальный backend и S3

Restic поддерживает множество бэкендов: локальный каталог, SFTP, S3, Azure, GCS.

```bash
# Локальный репозиторий (для тестов или на внешнем диске)
export RESTIC_REPOSITORY=/mnt/backup/restic-repo
export RESTIC_PASSWORD_FILE=/etc/restic/password.txt
restic init

# Бэкап
restic backup /etc /var/www

# Восстановление конкретного файла
restic restore latest --target /tmp/restore -- etc/nginx/nginx.conf

# Проверка
restic check

# Снимки (snapshots)
restic snapshots

# Очистка старых по политике
restic forget --keep-daily=7 --keep-weekly=4 --keep-monthly=12 --prune
```

**Restic + S3 (совместимое хранилище, например MinIO):**
```bash
export RESTIC_REPOSITORY="s3:https://minio.example.com/backups"
export RESTIC_PASSWORD_FILE=/etc/restic/password.txt
export AWS_ACCESS_KEY_ID=minioadmin
export AWS_SECRET_ACCESS_KEY=minioadmin

restic backup /data
restic snapshots
```

### 9. Kopia: универсальный инструмент с GUI

Kopia поддерживает файловые бэкапы, снимки и имеет веб-интерфейс (KopiaUI).

```bash
# Инициализация репозитория (файловый)
kopia repository create filesystem --path /mnt/backup/kopia-repo

# Создание политики (directory-based)
kopia policy set /etc --compression=zstd --encryption-enabled

# Бэкап
kopia snapshot create /etc /var/www

# Список снапшотов
kopia snapshot list

# Восстановление
kopia snapshot restore latest --target /tmp/restore

# Проверка целостности
kopia repository verify
```

### 10. Восстановление (Restore Procedures)

Восстановление — не менее важная операция, чем бэкап. Ниже стандартные процедуры.

**Из tar-архива:**
```bash
# Полное восстановление
tar -xzvf backup-2026-09-13.tar.gz -C /restore/

# С проверкой (dry-run)
tar -tzf backup-2026-09-13.tar.gz | less

# Восстановление конкретного файла
tar -xzvf backup-2026-09-13.tar.gz etc/nginx/nginx.conf -C /restore/
```

**Из Borg:**
```bash
# Полное восстановление
borg extract /backup/borg-repo::20260913-0200

# Список файлов перед восстановлением
borg list /backup/borg-repo::20260913-0200 etc/nginx/

# Восстановление в указанную директорию
borg extract /backup/borg-repo::20260913-0200 --target /tmp/restore
```

**Из Restic:**
```bash
# Восстановление последнего снапшота
restic restore latest --target /restore/

# Снимок конкретного пути
restic restore snap-a1b2c3 --target /restore/ -- /var/www/html
```

**Инкрементальный tar (цепочка):**
```bash
# Восстановление требует наличия всех архивов цепочки
# 1. Базовый полный архив
tar -xzvf base.tar.gz

# 2. Все инкрементальные в порядке создания
tar -xzvf incr1.tar.gz
tar -xzvf incr2.tar.gz
tar -xzvf incr3.tar.gz
```

**Из LVM-снапшота (слияние):**
```bash
# Для не-корневых томов
sudo umount /dev/vg0/data
sudo lvconvert --merge /dev/vg0/snap_data_2026-09-13
sudo mount /dev/vg0/data /mnt/data

# Для корневого тома — слияние при следующей загрузке
sudo lvconvert --merge /dev/vg0/snap_root
sudo reboot
```

### 11. Автоматизация: cron и systemd timers

```bash
# /etc/cron.d/daily-backup — классический cron
0 2 * * * root /usr/local/bin/backup.sh >> /var/log/backup.log 2>&1

# systemd timer — предпочтительно (логи, зависимости, условия)
# /etc/systemd/system/backup.service
[Unit]
Description=Daily backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/backup.timer
[Unit]
Description=Run backup daily at 02:00

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация
systemctl daemon-reload
systemctl enable --now backup.timer

# Проверка
systemctl list-timers | grep backup
# → Fri 2026-09-13 02:00:00 UTC 1 day left ...
```

### 12. Мониторинг и алертинг бэкапов

Бэкап без мониторинга = бэкап, о существовании которого никто не узнает при сбое.

**Минимальный скрипт проверки:**
```bash
#!/bin/bash
# /usr/local/bin/check_backup_freshness.sh
BACKUP_DIR="/backup/borg"
MAX_AGE_HOURS=26
LOG_FILE="/var/log/backup_check.log"

LATEST=$(borg list --last 1 --format "{time}" "$BACKUP_DIR" 2>/dev/null)
if [ -z "$LATEST" ]; then
    echo "CRITICAL: No backups found" | tee -a "$LOG_FILE"
    exit 2
fi

BACKUP_EPOCH=$(date -d "$LATEST" +%s)
NOW_EPOCH=$(date +%s)
AGE_HOURS=$(( (NOW_EPOCH - BACKUP_EPOCH) / 3600 ))

if [ "$AGE_HOURS" -gt "$MAX_AGE_HOURS" ]; then
    echo "CRITICAL: Latest backup is $AGE_HOURS hours old" | tee -a "$LOG_FILE"
    exit 2
fi

echo "OK: Latest backup is $AGE_HOURS hours old" >> "$LOG_FILE"
exit 0
```

**Prometheus blackbox exporter или node_exporter:**
```bash
# Если используете node_exporter textfile collector:
echo 'backup_last_success_timestamp{job="borg"} '"$(date +%s)" > /var/lib/node_exporter/backup.prom.$$ \
  && mv /var/lib/node_exporter/backup.prom.$$ /var/lib/node_exporter/backup.prom
```

### 13. DR Runbook: пример восстановления файлового сервера

```markdown
# Runbook: Восстановление файлового сервера /srv/data

## RTO: 2 часа | RPO: 24 часа

### Предусловия
- [ ] Объявлен инцидент
- [ ] Резервная копия проверена: `borg list /backup/borg-repo`
- [ ] Целевой том смонтирован: `/mnt/restore`

### Шаги
1. Остановка сервиса (если требуется консистентность)
   ```bash
   systemctl stop nfs-server
   ```

2. Восстановление данных
   ```bash
   borg extract /backup/borg-repo::20260913-0200 /srv/data
   ```

3. Проверка прав
   ```bash
   chown -R nfsnobody:nfsnobody /srv/data
   ```

4. Проверка целостности
   ```bash
   find /srv/data -type f | wc -l
   # → должно совпадать с эталоном
   ```

5. Запуск сервиса
   ```bash
   systemctl start nfs-server
   systemctl status nfs-server
   ```

### Откат
Если восстановление не удалось — вернитесь к точке snapshot (если есть) или используйте более старый архив.
```

### 14. Дополнительные инструменты

**Duplicity / Duply (инкрементальный бэкап через GPG, remote storage):**
```bash
# Duply — обертка над Duplicity
duply mybackup backup
duply mybackup restore /tmp/restore
```

**Rsync с hard-links (бэкап с компактным хранением):**
```bash
# --link-dest создает hard-links на неизмененные файлы
rsync -av --link-dest=/backup/previous/ /src/ /backup/current/
cp -al /backup/current /backup/$(date +%Y%m%d)
```

**Bacula / Bareos (enterprise, centralized):**
```bash
# bconsole
*run
Select Job: BackupClient1
```

## Безопасность резервных копий

Бэкап — это критическая точка отказа безопасности. Если злоумышленник получит доступ к бэкапу, он получит все данные.

### 1. Шифрование на стороне клиента (Source-side encryption)

Данные должны шифроваться *до* передачи в хранилище. Инструменты типа Restic/Borg/Kopia делают это по умолчанию.

**Для простых архивов (tar + age/gpg):**
```bash
# Шифрование через age (современно, просто)
tar -cvf - /data | age -r age1... > data.tar.age

# Расшифровка
age -d -i age.key data.tar.age | tar -xvf -

# Шифрование через GPG
tar -cvf - /data | gpg --symmetric --cipher-algo AES256 -o data.tar.gz.gpg
gpg --decrypt data.tar.gz.gpg | tar -xvf -
```

### 2. Управление ключами шифрования

Ключ — самый ценный актив системы бэкапа.

| Правило | Обоснование |
| :--- | :--- |
| **Никогда не храните ключ рядом с бэкапом** | Если украдут диск с бэкапом, ключ не должен быть на нем |
| **Ключ = секрет** | Используйте Vault, `pass`, или HSM |
| **Резервная копия ключа** | Бумажная копия фразы-пароля в сейфе |
| **Разделение ответственности** | Shamir's Secret Sharing для организации |
| **Ротация ключей** | Периодическая смена паролей репозитория |

### 3. Неизменяемость (Immutability)

В S3-совместимых хранилищах используйте `Governance` или `Compliance` mode, чтобы запретить удаление бэкапов в течение N дней.

Для локальных репозиториев:
```bash
# Append-only через Borg (SSH)
borg create --stats /remote/borg::$(date +%Y%m%d) /data

# На стороне сервера: chattr +i на директорию
sudo chattr +i /backup/borg-repo
```

### 4. Air-gap

Периодическое копирование данных на носители, физически отключенные от сети. Это единственная защита от ransomware, получившего доступ к сети.

## Валидация и тестирование

**Бэкап не считается существующим, пока не проведено успешное тестовое восстановление.**

### Автоматическая проверка

| Инструмент | Команда проверки | Что проверяет |
| :--- | :--- | :--- |
| **Borg** | `borg check` | Целостность репозитория, archive segments |
| **Restic** | `restic check` | Целостность репозитория, потерянные блоки |
| **Kopia** | `kopia repository verify` | Интегритет snapshot'ов и связей |
| **tar** | `tar -tzf` + checksum | Возможность чтения архива |
| **restic** | `restic restore --dry-run` | Список файлов без извлечения |

### Drill-тесты

- **File-level restore:** Раз в квартал восстановите произвольный файл из каждого типа бэкапа.
- **Full restore in isolated env:** Раз в квартал восстановите полный сервис в изолированной среде (VM/контейнер).
- **Corruption simulation:** Удалите один архив и проверьте, что цепочка еще работает (для инкрементальных).

### Мониторинг и алертинг

Настройте алертинг на:
- Отсутствие свежего бэкапа (>26 часов для ежедневных)
- Ошибки в логах выполнения (exit code != 0)
- Аномально малый размер бэкапа (пустой архив)
- Превышение COW-буфера при LVM-снапшотах

```bash
# Пример cron-задачи для проверки свежести Borg
0 6 * * * root /usr/local/bin/check_backup_freshness.sh || \
  mail -s "BACKUP ALERT" ops@example.com < /var/log/backup_check.log
```

## Дополнительная информация

### Сравнение инструментов

| Инструмент | Дедупликация | Шифрование | Назначение | Платформа |
| :--- | :---: | :---: | :--- | :--- |
| **BorgBackup** | Да (chunk-level) | Да (AES-256) | Локально/SSH, immutable | Linux/macOS |
| **Restic** | Да (chunk-level) | Да (AES-256) | Локально/S3/SFTP | Cross-platform |
| **Kopia** | Да (chunk-level) | Да | Локально/Облако + GUI | Cross-platform |
| **Duplicity** | Да (rsync-инкременты) | Да (GPG) | Облака/SFTP, legacy | Linux/macOS |
| **rsnapshot** | Нет (hard-links) | Нет | Локальные ротационные бэкапы | Linux/macOS |
| **Bacula/Bareos** | Нет | Да | Enterprise, centralized | Linux/Windows/macOS |
| **Veeam Agent** | Да | Да | Enterprise/Hybrid | Linux/Windows |
| **Velero** | Нет | Да | Kubernetes | K8s native |
| **ReaR** | Нет | Нет | Bare Metal Recovery | Linux |

### Ссылки на специализированные домены (SSoT)

Для глубокого анализа смежных тем используйте профильные разделы:

- **RAID vs Backup:** Отличие отказоустойчивости и сохранности данных — **[RAID vs Backup](../FileSystems/RAID/raid-vs-backup.md)**.
- **DR Patterns:** Паттерны Cold/Warm/Hot Standby, Runbook, DiRT — **[Disaster Recovery Patterns](../../Concepts/disaster_recovery.md)**.
- **iSCSI Backup:** Снапшоты LUN, application-consistent, air-gap — **[iSCSI Backup](../Networking/iSCSI/iscsi_backup.md)**.
- **Бэкап БД:** pg_dump, pgBackRest, XtraBackup, консистентность — **[Стратегии бэкапов БД](../../Databases/Concepts/backups.md)**.
- **Мониторинг бэкапов:** Dead Man's Switch, метрики — **[Мета-мониторинг](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)**.
- **Сжатие:** gzip/zstd/lz4/xz — **[Утилиты сжатия](./file-compression.md)**.

### Типичные ошибки и диагностика

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Бэкап пустой** | Неправильный путь или исключение | `borg list`, `tar -tzf` | Проверьте пути, exclude-правила |
| **Снапшот переполнен** | COW-буфер исчерпан | `lvs -o+snap_percent` | Увеличить размер или чаще удалять |
| **Бэкап зависает** | Нет места, сеть, I/O wait | `df -h`, `iostat`, `ping` | Освободить место, проверить сеть |
| **Восстановление падает** | Не хватает места на целевом | `df -h /restore` | Увеличить целевой том |
| **Restic/Borg не находят ключ** | `BORG_PASSPHRASE` не экспортирован | `env | grep -i borg/restic` | Экспортировать переменную или указать файл |
| **rsync копирует всё заново** | Истек source или destination удален | `rsync -n` (dry-run) | Проверить пути, права, `--delete` |
| **Шифрование не работает** | Ключ не защищен, в репозитории | `borg info` | Ключ должен быть вне репозитория |
| **Восстановленная БД не стартует** | Неконсистентный бэкап (crash-consistent) | `postgresql.log`, `mysqld.log` | Использовать application-consistent метод |

### См. также

- **[rsync — синхронизация файлов](./rsync.md)** — база для многих систем бэкапа.
- **[Файловые операции (`cp`, `mv`, `rm`)](../Shell/file_operations.md)** — полный справочник опций `cp`, сравнение `cp -a` и `cp -r`.
- **[Миграция пользователей](./Users/user_migration.md)** — перенос домашнего каталога на другой сервер через `rsync -aHAXz`.
- **[LVM — снимки](../FileSystems/LVM/snapshots.md)** — COW-снапшоты и тонкая прозвязка.
- **[Утилита dd](../FileSystems/dd.md)** — низкоуровневое клонирование и образы.
- **[Стратегии бэкапов БД](../../Databases/Concepts/backups.md)** — специфика ACID-консистентности.
- **[Утилиты сжатия файлов (gzip, bzip2, xz, zip)](./file-compression.md)** — компрессоры для файлов и потоков.
- **[RAID vs Backup](../FileSystems/RAID/raid-vs-backup.md)** — почему RAID не заменяет бэкап.
- **[Disaster Recovery Patterns](../../Concepts/disaster_recovery.md)** — паттерны Cold/Warm/Hot Standby, Runbook, DiRT.
- **[iSCSI Backup](../Networking/iSCSI/iscsi_backup.md)** — снапшоты LUN, quiesce, air-gap для iSCSI.
- **[Мета-мониторинг: мониторинг бэкапов](../../Concepts/Observability_and_Monitoring/meta-monitoring.md)** — Dead Man's Switch для контроля cron-заданий.
- **[Аудит и логирование](./Logging/logging_overview.md)** — мониторинг заданий бэкапа.
- **[Шифрование дисков (LUKS)](../Security/Concepts/encryption_basics.md)** — шифрование резервных копий на уровне ФС.
- **[systemd-cryptenroll](../Core/systemd/systemd_cryptenroll.md)** — автоматическое расшифрование LUKS с TPM2/FIDO2.
- **[Таймеры systemd](../Core/systemd/timers.md)** — современная замена cron для планирования бэкапов.
