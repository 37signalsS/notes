# systemd-repart: Декларативное управление разделами дисков

## Определения

* **`systemd-repart`** — системная утилита для декларативного создания, изменения и переразметки разделов диска при первой загрузке системы или обновлении образа. Работает на основе конфигурационных файлов в `/etc/repart.d/`, что делает управление разделами воспроизводимым и автоматизированным.
* **Repart-файл** — конфигурационный файл формата INI, описывающий параметры раздела (размер, тип, файловая система, точки монтирования). Расширение `.repart` или `.conf`. Хранится в `/usr/lib/repart.d/` (пакеты) или `/etc/repart.d/` (локальные настройки).
* **Auto-repart** — режим автоматической переразметки при первой загрузке. Если на диске нет разделов, описанных в repart-файлах, `systemd-repart` создаст их автоматически. Отключается через `--empty=skip`.
* **Семя (Seed)** — случайное значение, используемое для генерации UUID и GPT ID разделов. Позволяет делать образы воспроизводимыми при фиксированном семени.
* **GrowFS** — директива, указывающая `systemd-repart` автоматически расширять файловую систему раздела до заполнения доступного пространства. Полезно для облаков и контейнеров.
* **Слияние (Merge)** — механизм объединения соседних разделов с одинаковым типом. Используется для динамического изменения размера разделов без потери данных.
* **Оффсет (Offset)** — смещение начала раздела от начала диска. Позволяет зарезервировать пространство для загрузчика или других данных.

## Основные концепции

### Архитектура и место в системе

`systemd-repart` работает на ранних этапах загрузки, после `systemd-udevd`, но до монтирования файловых систем:

```
BIOS/UEFI загрузчик
        │
        ▼
  Ядро Linux
        │
        ▼
  systemd (PID 1)
        │
        ▼
  systemd-udevd (обнаружение дисков)
        │
        ▼
  systemd-repart (создание/изменение разделов)
        │
        ▼
  systemd-makefs (создание ФС)
        │
        ▼
  systemd-mount (монтирование)
        │
        ▼
  local-fs.target
```

### Типы разделов

`systemd-repart` поддерживает стандартные типы GPT-разделов:

| Тип | UUID | Описание |
| :--- | :--- | :--- |
| **Linux filesystem** | `0FC63DAF-8483-4772-8E79-3D69D8477DE4` | Обычный раздел Linux (ext4, xfs, btrfs) |
| **Linux extended boot** | `BC13C2FF-59E6-4262-A352-B2B5A4AC83AB` | Загрузочный раздел (ESP) |
| **Linux swap** | `0657FD6D-A4AB-43C4-84E5-0933C84B4F4F` | Раздел подкачки |
| **Linux home** | `933AC7E1-2EB4-4F13-B844-0E14E2AEF915` | Домашний раздел |
| **Linux server var** | `3D84CBBA-20AC-430A-952A-CF4C333E16B1` | Системный раздел /var |
| **Linux x86-64 root** | `4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709` | Корневой раздел для x86-64 |
| **Linux x86-64 /usr** | `8484680C-9521-482A-9D21-18C931FAEDDB` | Раздел /usr для x86-64 |

### Порядок приоритета repart-файлов

`systemd-repart` загружает конфигурацию из нескольких директорий:

1. `/usr/lib/repart.d/` —(rep-файлы из пакетов (низший приоритет)
2. `/etc/repart.d/` — локальные настройки администратора (высший приоритет)
3. `/run/repart.d/` — динамические конфигурации

При конфликте имен файлов используется порядок приоритета. Для просмотра итоговой конфигурации:

```bash
systemd-repart --dry-run --verbose
```

### Жизненный цикл repart-юнитов

`systemd-repart` работает через следующие systemd-юниты:

1. **`systemd-repart.service`** — основной сервис, выполняющий переразметку при загрузке.
2. **`systemd-repart-ask.service`** — запрос подтверждения при интерактивной загрузке (опционально).

```bash
# Проверка статуса
systemctl status systemd-repart

# Просмотр логов
journalctl -u systemd-repart
```

## Конфигурация

### Структура repart-файла

Файл `/etc/repart.d/10-root.conf`:

```ini
[Partition]
# Тип раздела (UUID или краткое имя)
Type=root-x86-64

# Минимальный размер
SizeMinBytes=10G

# Максимальный размер (необязательно)
SizeMaxBytes=50G

# Файловая система
Format=ext4

# Точка монтирования
MountPoint=/

# Опции монтирования
MountOptions=defaults,noatime

# Автоматическое расширение до заполнения
GrowFS=yes

# UUID (опционально, для воспроизводимости)
# UUID=12345678-1234-1234-1234-123456789abc

# Семя для генерации UUID
# Seed=12345678-1234-1234-1234-123456789abc

# Оффсет от начала диска
# OffsetBytes=1M

# Размер сектора
# SectorSize=4096

# Приоритет (чем выше, тем раньше создается)
# Priority=100

# Условие создания (опционально)
# ConditionPathExists=!/var/lib/repart/.done
# ConditionFirmware=efi
```

### Пример: минимальная разметка для сервера

Файл `/etc/repart.d/10-root.conf`:

```ini
[Partition]
Type=root-x86-64
SizeMinBytes=20G
SizeMaxBytes=100G
Format=ext4
MountPoint=/
GrowFS=yes
```

Файл `/etc/repart.d/20-efi.conf`:

```ini
[Partition]
Type=esp
SizeMinBytes=512M
SizeMaxBytes=1G
Format=vfat
MountPoint=/boot/efi
MountOptions=umask=0077
```

Файл `/etc/repart.d/30-swap.conf`:

```ini
[Partition]
Type=swap
SizeMinBytes=2G
SizeMaxBytes=8G
Format=swap
```

### Пример: разметка для облака (GCE/AWS)

Файл `/etc/repart.d/10-root.conf`:

```ini
[Partition]
Type=root-x86-64
SizeMinBytes=10G
# Без MaxBytes — раздел займет всё доступное пространство
Format=ext4
MountPoint=/
GrowFS=yes
```

Файл `/etc/repart.d/20-ephemeral.conf`:

```ini
[Partition]
Type=linux-generic
SizeMinBytes=50G
Format=ext4
MountPoint=/mnt/ephemeral
GrowFS=yes
# Дополнительные опции для ephemeral-дисков
Options=discard,nodiratime
```

### Пример: разметка с шифрованием

```ini
[Partition]
Type=cryptlusk
SizeMinBytes=50G
Format=ext4
MountPoint=/
GrowFS=yes
# Шифрование через LUKS2
Encrypt=yes
```

## Практические сценарии

### 1. Автоматическая разметка нового диска

```bash
# 1. Проверить текущее состояние
lsblk
# → NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
# → sda      8:0    0  20G  0 disk
# → └─sda1   8:1    0  20G  0 part /

# 2. Добавить новый диск
lsblk
# → NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
# → sda      8:0    0  20G  0 disk
# → └─sda1   8:1    0  20G  0 part /
# → sdb      8:16   0 100G  0 disk

# 3. Создать repart-файл для нового диска
sudo tee /etc/repart.d/40-data.conf <<EOF
[Partition]
Type=linux-generic
SizeMinBytes=50G
Format=ext4
MountPoint=/data
GrowFS=yes
EOF

# 4. Запустить переразметку
sudo systemd-repart /dev/sdb

# 5. Проверить
lsblk
# → NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
# → sda      8:0    0  20G  0 disk
# → └─sda1   8:1    0  20G  0 part /
# → sdb      8:16   0 100G  0 disk
# → └─sdb1   8:17   0 100G  0 part /data
```

### 2. Расширение корневого раздела

```bash
# 1. Проверить текущий размер
df -h /
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        20G   15G  4.0G  79% /

# 2. Обновить repart-файл
sudo tee /etc/repart.d/10-root.conf <<EOF
[Partition]
Type=root-x86-64
SizeMinBytes=50G
SizeMaxBytes=200G
Format=ext4
MountPoint=/
GrowFS=yes
EOF

# 3. Запустить переразметку
sudo systemd-repart

# 4. Расширить файловую систему
sudo resize2fs /dev/sda1
# Или для XFS: sudo xfs_growfs /

# 5. Проверить
df -h /
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   15G   33G  31% /
```

### 3. Создание разметки для контейнера (Docker/Podman)

```bash
# 1. Создать repart-файл
sudo tee /etc/repart.d/10-root.conf <<EOF
[Partition]
Type=root-x86-64
SizeMinBytes=10G
Format=ext4
MountPoint=/
GrowFS=yes
Options=discard,nobarrier
EOF

# 2. Применить к образу контейнера
sudo systemd-repart --image=/var/lib/machines/mycontainer.raw

# 3. Монтировать образ
sudo systemd-nspawn -i /var/lib/machines/mycontainer.raw
```

### 4. Интерактивная переразметка с подтверждением

```bash
# Запуск с запросом подтверждения для каждого действия
sudo systemd-repart --ask-password

# Пример вывода:
# Ready to create or modify partitions on /dev/sdb.
# This will create the following partitions:
#   NAME   SIZE  TYPE
#   root   50G   linux-generic
# Do you want to proceed? [y/N]:
```

### 5. Просмотр плана переразметки без применения

```bash
# Dry-run режим
sudo systemd-repart --dry-run

# Детальный вывод
sudo systemd-repart --dry-run --verbose

# Пример вывода:
# Would create partition 10-root on /dev/sdb:
#   Type: linux-generic (0FC63DAF-8483-4772-8E79-3D69D8477DE4)
#   Size: 50G
#   Format: ext4
#   MountPoint: /data
```

### 6. Автоматическая разметка при первом запуске (cloud-init)

```bash
# В cloud-init или Packer-скрипте:
sudo tee /etc/repart.d/10-root.conf <<EOF
[Partition]
Type=root-x86-64
SizeMinBytes=20G
Format=ext4
MountPoint=/
GrowFS=yes
EOF

# Включить systemd-repart
sudo systemctl enable systemd-repart

# При первой загрузке система автоматически создаст разделы
```

### 7. Переразметка с сохранением данных

```bash
# 1. Проверить текущее состояние
lsblk
# → NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
# → sda      8:0    0  20G  0 disk
# → └─sda1   8:1    0  20G  0 part /

# 2. Обновить repart-файл
sudo tee /etc/repart.d/10-root.conf <<EOF
[Partition]
Type=root-x86-64
SizeMinBytes=50G
Format=ext4
MountPoint=/
GrowFS=yes
EOF

# 3. Запустить переразметку с сохранением данных
sudo systemd-repart --dry-run --no-pager
# Проверить, что раздел будет расширен, а не пересоздан

# 4. Применить изменения
sudo systemd-repart

# 5. Расширить файловую систему
sudo resize2fs /dev/sda1
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `systemd-repart` не запускается | Юнит отключен | `systemctl is-enabled systemd-repart` | `sudo systemctl enable systemd-repart` |
| Раздел не создается | Неправильный тип или размер | `journalctl -u systemd-repart` | Проверьте `Type=` и `SizeMinBytes=` |
| Файловая система не создается | `Format=` не указан | `journalctl -u systemd-repart` | Добавьте `Format=ext4` (или другой тип) |
| Раздел не монтируется | `MountPoint=` не указан | `mount \| grep <device>` | Добавьте `MountPoint=/data` |
| GrowFS не работает | Раздел уже заполнен | `df -h` | Увеличьте `SizeMaxBytes` |
| Конфликт с существующими разделами | Repart-файл конфликтует с текущей разметкой | `fdisk -l /dev/sda` | Используйте `--empty=skip` |
| Недостаточно места | `SizeMinBytes` превышает доступное пространство | `lsblk` | Уменьшите `SizeMinBytes` |
| Ошибка UUID | Дублирование UUID | `blkid` | Удалите `UUID=` из repart-файла |

## Рекомендации по эксплуатации

1. **Всегда делайте dry-run** перед применением: `systemd-repart --dry-run --verbose`.
2. **Используйте `GrowFS=yes`** для разделов, которые должны автоматически расширяться.
3. **Указывайте `SizeMinBytes`** для гарантии минимального размера раздела.
4. **Не используйте `systemd-repart` на работающих системах** без предварительного тестирования.
5. **Для облаков** используйте `--image=` для разметки образов вне целевой системы.
6. **Храните repart-файлы в Git** для версионирования и воспроизводимости.
7. **Используйте семя (Seed)** для генерации предсказуемых UUID в воспроизводимых образах.
8. **Проверяйте условия** (`ConditionPathExists=`, `ConditionFirmware=`) для условной разметки.
9. **Для шифрования** комбинируйте с `systemd-cryptenroll` для автоматической разблокировки.
10. **Мониторьте логи** через `journalctl -u systemd-repart` для обнаружения ошибок.

## Ограничения и особенности

* **Только GPT:** `systemd-repart` работает только с GPT-разметкой. Для MBR используйте `fdisk` или `parted`.
* **Нет online-resize для некоторых ФС:** XFS и btrfs поддерживают online-resize, но ext4 требует `resize2fs` после `systemd-repart`.
* **Конфликт с LVM:** `systemd-repart` не управляет LVM. Для LVM используйте `lvm` и `vgdisplay`.
* **Версии systemd:** Полная поддержка требует systemd v248+. Проверяйте версию: `systemd --version`.
* **Контейнеры:** В Docker/контейнерах без systemd `systemd-repart` может не работать. Используйте `--image=` для разметки вне контейнера.
* **UEFI vs BIOS:** Некоторые типы разделов (ESP) доступны только в UEFI-режиме.
* **Потеря данных:** Неправильная конфигурация может привести к потере данных. Всегда делайте резервные копии.

## Дополнительная информация

### См. также

* [systemd-boot](../../SystemAdministration/grub.md) — загрузчик, требующий ESP-раздела.
* [systemd-cryptenroll](./systemd_cryptenroll.md) — шифрование разделов через LUKS2.
* [Управление дисками (LVM)](../../FileSystems/LVM/management_operations.md) — альтернатива для динамической разметки.
* [Cloud-init](../../../Concepts/event-driven-architecture.md) — автоматизация разметки в облаках.
* [Обзор systemd](./overview.md) — архитектура и компоненты системы.
