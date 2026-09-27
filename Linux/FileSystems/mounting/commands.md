# Определения

**Команды монтирования** — набор системных утилит командной строки, предназначенных для управления подключением (монтированием), отключением (размонтированием) и анализом состояния файловых систем в иерархии каталогов Linux.

В отличие от Windows, где каждому разделу присваивается буква диска (C:, D:), в Linux вся дисковая подсистема представлена единым деревом каталогов. Новый раздел становится доступным для записи только после монтирования в некоторую точку этого дерева.

# Основные концепции

## mount — подключение файловых систем

Команда `mount` связывает файловую систему на физическом устройстве или сетевом ресурсе с определенным каталогом (**точкой монтирования**).

*   **Синтаксис**: `mount [опции] <источник> <точка_монтирования>`
*   **Автоопределение**: Ядро автоматически определяет тип ФС, обращаясь к `libblkid`.

**Интуитивная аналогия:** точка монтирования работает как окно между каталогом Linux и содержимым диска. До монтирования каталог пуст или содержит свои файлы; после монтирования всё, что записывается в каталог, физически попадает на диск. При `umount` окно закрывается: каталог снова становится пустым, но данные на диске не удаляются.

### Ключевые опции команды mount

| Опция | Эффект | Типичное использование |
| :--- | :--- | :--- |
| `-a` (`--all`) | Монтирует все файловые системы из `/etc/fstab` (кроме `noauto`) | Проверка конфигурации после редактирования fstab |
| `-o` (`--options`) | Список параметров через запятую | `ro`, `rw`, `noatime`, `loop`, `bind`, `discard` |
| `-t` (`--types`) | Явное указание типа ФС | `ext4`, `xfs`, `nfs4`, `cifs`, `tmpfs`, `overlay` |
| `-r` (`--read-only`) | Монтирование в режиме «только чтение» (синоним `-o ro`) | Защита данных перед работами с оборудованием |
| `-w` (`--read-write`) | Монтирование в режиме «чтение-запись» (синоним `-o rw`) | Восстановление доступа к корневой ФС |
| `-n` (`--no-mtab`) | Не записывать запись в `/etc/mtab` | В средах без записи в корень (initramfs, контейнеры) |
| `-L` (`--label`) | Монтирование по метке ФС | `mount -L BACKUP /mnt/backup` |
| `-U` (`--uuid`) | Монтирование по UUID | `mount -U 550e8400... /mnt/data` |

### Специальные режимы

1.  **Bind Mount (`--bind`)**: Делает часть существующей иерархии доступной в другом месте.
    ```bash
    sudo mount --bind /var/www /home/user/web
    ```
2.  **Move (`--move`)**: Атомарно перемещает смонтированную ФС в другую точку.
    ```bash
    sudo mount --move /mnt/old /mnt/new
    ```
3.  **Loop Mount (`-o loop`)**: Монтирование образа файла как блочного устройства.
    ```bash
    sudo mount -o loop ubuntu.iso /mnt/iso
    ```
    Подробнее о петлевых устройствах: [Петлевые устройства (Loop Devices)](../loop_devices.md).

### /proc/mounts vs /etc/mtab

На современных системах `/etc/mtab` является символической ссылкой на `/proc/mounts` или `/proc/self/mountinfo`. Этот файл отражает текущее динамическое состояние всех монтирований, включая временные.

*   **`/proc/mounts`**: Сырой вывод ядра, обновляется ядром напрямую.
*   **`/proc/self/mountinfo`**: Расширенный формат с полями `major:minor`, propagation flags и стеком нижних ФС. Рекомендуется для диагностики в контейнерных средах.
*   **`/etc/mtab`**: Исторически использовался для записи состояния. В systemd-системах обычно симлинк на `/proc/mounts`.

## umount — отключение файловых систем

Безопасно завершает работу с ФС, гарантируя сброс буферов записи.

*   **Синтаксис**: `umount [опции] <точка_монтирования | устройство>`

После отмонтирования точка монтирования становится пустой. Файлы не удаляются — они остаются на устройстве, просто доступ к ним через эту точку временно закрыт.

### Обработка ошибок «target is busy»

Если ФС занята процессами, используйте следующие флаги:

*   `-l` (`--lazy`): Немедленно отключает ФС от иерархии, фактическое размонтирование произойдет после освобождения всех ресурсов.
*   `-f` (`--force`): Принудительное отключение (эффективно только для сетевых ФС типа NFS/CIFS).
*   `-R` (`--recursive`): Размонтирует указанную точку и все вложенные в нее ФС.

**Алгоритм диагностики busy-состояния:**

```bash
# 1. Быстрая проверка: есть ли открытые дескрипторы
sudo lsof +D /mnt/data | grep -E 'cwd|txt|DEL'

# 2. Поиск процессов через fuser
sudo fuser -vm /mnt/data

# 3. Поиск через mountinfo (для bind mounts и nested)
grep ' /mnt/data ' /proc/self/mountinfo
```

> **Важно:** `umount -f` для локальных ФС (ext4/xfs) не работает. Используйте `lazy unmount` или завершите процессы вручную.

## findmnt — инспекция и верификация

Современная замена прямому чтению `/proc/mounts`. Рекомендуется для анализа дерева зависимостей.

*   **Дерево монтирования**: `findmnt --tree` (показывает иерархию и Propagation flags).
*   **Поиск источника**: `findmnt /data` (показывает, какое устройство смонтировано в каталог).
*   **Верификация fstab**:
    ```bash
    findmnt --verify
    # → Success: no errors or warnings detected
    ```

### Практические форматы вывода

```bash
# Краткий вывод только опций
findmnt -no OPTIONS /data

# Произвольные колонки
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS,PROPAGATION

# Фильтр по типу ФС
findmnt -t nfs4,ext4,xfs

# JSON для автоматизации
findmnt -J

# Дерево с флагами распространения
findmnt --tree --output TARGET,PROPAGATION
```

## Инструменты идентификации (blkid, lsblk)

Используются для поиска UUID и меток (LABEL) перед добавлением записей в `fstab`.

*   **blkid**: Низкоуровневый вывод атрибутов блочных устройств.
    ```bash
    sudo blkid /dev/sda1
    # → /dev/sda1: UUID="a1b2..." TYPE="ext4" PARTUUID="c3d4..."
    ```
    Подробное объяснение различия между UUID и PARTUUID, их изменение при пересоздании ФС и влияние на загрузку описано в [Разделы и файловые системы — UUID vs PARTUUID](../partitions_and_filesystems.md#UUID-vs-PARTUUID-ключевое-различие).

*   **lsblk**: Древовидный обзор устройств.
    ```bash
    lsblk -f
    # → NAME FSTYPE LABEL UUID                                 MOUNTPOINTS
    # → sda1 ext4   ROOT  a1b2c3d4-e5f6-7890-abcd-ef1234567890 /
    ```

### Практические шаблоны для SRE

```bash
# Получить только UUID конкретного диска
lsblk -no UUID /dev/sdb1
# → a1b2c3d4-e5f6-7890-abcd-ef1234567890

# Проверить флаг RO на уровне устройства (аппаратный или программный)
lsblk -o NAME,RO,SIZE,FSTYPE,MOUNTPOINTS /dev/sdb1

# Дерево с размерами в человекочитаемом формате
lsblk -h

# JSON для автоматизации
lsblk -J -o NAME,SIZE,FSTYPE,MOUNTPOINTS,UUID
```

## mountpoint — проверка состояния

Утилита для использования в скриптах. Проверяет, является ли каталог точкой монтирования.

```bash
mountpoint -q /mnt/data && echo "Смонтировано" || echo "Не смонтировано"
# → Смонтировано
```

### Практические паттерны в скриптах

```bash
# Идемпотентный скрипт монтирования
MOUNT_POINT="/mnt/data"
DEVICE="/dev/sdb1"

if ! mountpoint -q "$MOUNT_POINT"; then
    echo "Монтируем $DEVICE -> $MOUNT_POINT"
    sudo mount "$DEVICE" "$MOUNT_POINT"
else
    echo "Уже смонтировано"
fi

# Проверка с типом ФС (mountpoint не умеет проверять тип, используем findmnt)
EXPECTED_FSTYPE="ext4"
CURRENT_FSTYPE=$(findmnt -no FSTYPE "$MOUNT_POINT")

if [[ "$CURRENT_FSTYPE" != "$EXPECTED_FSTYPE" ]]; then
    echo "Ошибка: ожидается $EXPECTED_FSTYPE, получен $CURRENT_FSTYPE"
    exit 1
fi
```

## systemd-mount — временное монтирование

Современная утилита, которая создает временный `.mount` юнит. Полезна для автоматизации, так как корректно обрабатывает зависимости systemd.

```bash
sudo systemd-mount /dev/sdb1 /mnt/tmp
# → Started unit mnt-tmp.mount for /dev/sdb1
```

### Практические сценарии systemd-mount

```bash
# Монтирование с зависимостью от сети
sudo systemd-mount --owner=alice --collect --fsck=no --options=noatime,ro /dev/sdb1 /mnt/tmp

# Монтирование как пользователь (user unit)
systemd-mount --user /dev/sdb1 /mnt/tmp

# Автоматическое размонтирование по бездействию (временный автомонт)
sudo systemd-run --unit=mnt-tmp --property=TimeoutStopSec=300 -- systemd-mount /dev/sdb1 /mnt/tmp
```

## Вспомогательные команды

### losetup — управление петлевыми устройствами

Утилита для управления связями между файлами и блочными устройствами `/dev/loopX`. Подробное описание механизмов и сценариев: [Петлевые устройства (Loop Devices)](../loop_devices.md).

```bash
# Список активных устройств
losetup -a

# Первое свободное устройство
losetup -f

# Создание read-only петли
sudo losetup -r /dev/loop0 image.iso

# Удаление связи
sudo losetup -d /dev/loop0
```

### swapon / swapoff — управление swap

Аналогично монтированию, но для разделов подкачки. В современных ядрах swap может быть файлом или разделом.

```bash
# Активация swap-раздела
sudo swapon /dev/sdb2

# Активация swap-файла
sudo swapon /swapfile

# Деактивация всего swap
sudo swapoff -a

# Просмотр статуса
swapon --show
```

> **Важно:** Изменение размера swap-файла или раздела невозможно «на лету». Требуется `swapoff` → изменение → `swapon`.

### df и du — проверка результата монтирования

```bash
# Проверка точек монтирования и использования места
df -hT /mnt/data
# → Filesystem     Type  Size  Used Avail Use% Mounted on
# → /dev/sdb1      ext4  100G   20G   80G  20% /mnt/data

# Дерево использования места
du -sh /mnt/data/* | sort -h | tail -10
```

# Практические сценарии

### 1. Предварительная проверка перед монтированием

```bash
MOUNT_POINT="/mnt/data"
DEVICE="/dev/sdb1"

# Проверка существования устройства
if [[ ! -b "$DEVICE" ]]; then
    echo "Ошибка: устройство $DEVICE не найдено"
    exit 1
fi

# Проверка наличия ФС
if ! sudo blkid -o value -s TYPE "$DEVICE" 2>/dev/null | grep -q .; then
    echo "Ошибка: на устройстве $DEVICE нет файловой системы"
    exit 1
fi

# Проверка существования точки монтирования
if [[ ! -d "$MOUNT_POINT" ]]; then
    echo "Создаем точку монтирования $MOUNT_POINT"
    sudo mkdir -p "$MOUNT_POINT"
fi

# Проверка, не смонтировано ли уже
if mountpoint -q "$MOUNT_POINT"; then
    echo "Уже смонтировано"
else
    sudo mount "$DEVICE" "$MOUNT_POINT"
fi
```

### 2. Поиск процесса, блокирующего размонтирование

```bash
# Поиск через lsof
sudo lsof +D /mnt/data
# → COMMAND  PID  USER   FD   TYPE DEVICE SIZE/OFF  NODE NAME
# → bash    1234  user  cwd    DIR   8,1     4096     2 /mnt/data

# Поиск через fuser
sudo fuser -vm /mnt/data
# →                      USER        PID ACCESS COMMAND
# → /mnt/data:           user       1234 ..c.. bash
```

### 3. Монтирование всех ресурсов из fstab с валидацией

Краткий сценарий проверки конфигурации. Подробный алгоритм и нюансы работы `mount -a` (включая ограничение на строчный флаг `-a`) — в [fstab.md](./fstab.md#безопасная-проверка-конфигурации).

```bash
# 1. Синтаксическая проверка
findmnt --verify
# → Success: no errors or warnings detected

# 2. Применение конфигурации
sudo systemctl daemon-reload
sudo mount -a

# 3. Проверка результата
df -hT /mnt/data
```

### 4. Получение только UUID конкретного диска

```bash
lsblk -no UUID /dev/sdb1
# → a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

### 5. Идемпотентный скрипт проверки здоровья монтирований

```bash
#!/usr/bin/env bash
set -euo pipefail

EXPECTED_MOUNTS=(
    "/dev/sda1:/"
    "/dev/sdb1:/mnt/data"
    "server:/share:/mnt/nfs:nfs4"
)

for entry in "${EXPECTED_MOUNTS[@]}"; do
    IFS=':' read -r device mountpoint fstype <<< "$entry"
    
    # Проверка существования точки
    if [[ ! -d "$mountpoint" ]]; then
        echo "FAIL: $mountpoint — точка не существует"
        continue
    fi
    
    # Проверка статуса
    if ! mountpoint -q "$mountpoint"; then
        echo "FAIL: $mountpoint — не смонтировано"
        continue
    fi
    
    # Проверка источника
    source=$(findmnt -no SOURCE "$mountpoint")
    if [[ "$source" != *"$device"* ]]; then
        echo "FAIL: $mountpoint — источник $source не соответствует $device"
        continue
    fi
    
    # Проверка типа ФС (если указан)
    if [[ -n "${fstype:-}" ]]; then
        actual_fstype=$(findmnt -no FSTYPE "$mountpoint")
        if [[ "$actual_fstype" != "$fstype" ]]; then
            echo "FAIL: $mountpoint — тип $actual_fstype не соответствует $fstype"
            continue
        fi
    fi
    
    echo "OK: $mountpoint"
done
```

### 6. Обработка NFS/CIFS зависаний

```bash
# Проверка, что mount с опцией soft (не ждет вечно)
findmnt -no OPTIONS /mnt/nfs | grep -q 'soft' || {
    echo "Перемонтируем NFS с безопасными опциями..."
    sudo mount -o remount,soft,timeo=50,retrans=3 /mnt/nfs
}

# Принудительный размонтировать зависшей NFS (lazy)
sudo umount -l /mnt/nfs
```

### 7. Временный tmpfs для сборки

```bash
# Создание временного tmpfs для артефактов сборки
sudo mount -t tmpfs -o size=2G,noexec,nosuid,nodev build_tmp /tmp/build

# ... выполнение сборки ...

# Очистка
sudo umount /tmp/build
```

### 8. Проверка безопасности опций монтирования

```bash
# Проверка, что /tmp смонтирован с noexec,nosuid,nodev
check_mount_options() {
    local mountpoint="$1"
    local required_opts=("$@")
    local opts
    opts=$(findmnt -no OPTIONS "$mountpoint" | tr ',' '\n' | sort)
    
    for opt in "${required_opts[@]}"; do
        if ! echo "$opts" | grep -qx "$opt"; then
            echo "FAIL: $mountpoint — отсутствует опция $opt"
            return 1
        fi
    done
    echo "OK: $mountpoint"
}

check_mount_options /tmp noexec nosuid nodev
check_mount_options /dev/shm nosuid nodev
```

# Диагностика и типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`target is busy`** | Процесс удерживает ФС или CWD внутри | `lsof +D /mnt/data` / `fuser -vm /mnt/data`, затем `umount -l` |
| **`mount: can't find in /etc/fstab`** | Неверный UUID, LABEL или путь | Проверьте `blkid` или `lsblk -f` |
| **`mount: wrong fs type, bad option`** | Неверный тип ФС или несовместимые опции | Установите пакет (nfs-utils, cifs-utils) |
| **`mount: /mnt: mount point does not exist`** | Директория не создана | `mkdir -p /mnt` |
| **`No such device`** | Устройство не подключено или не распознано | Проверьте `lsblk`, `dmesg` |
| **NFS mount hangs** | Сервер недоступен или сетевая проблема | Используйте `soft,timeo=50,retrans=3` вместо `hard` |
| **`special device /dev/sdX does not exist`** | Устройство переименовано или отсутствует | Используйте UUID/LABEL вместо путей к устройствам |

### Пошаговая диагностика проблемного монтирования

```bash
# 1. Проверка, что точка монтирования существует и доступна
ls -la /mnt/data

# 2. Проверка состояния устройства
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,RO /dev/sdb1

# 3. Проверка, что точка не смонтирована с неверными опциями
findmnt -o TARGET,SOURCE,FSTYPE,OPTIONS | grep /mnt/data

# 4. Проверка логов ядра
dmesg | tail -20

# 5. Проверка, нет ли зависших процессов
sudo fuser -vm /mnt/data 2>/dev/null || echo "Нет блокирующих процессов"

# 6. Принудительная очистка (только для NFS/CIFS или при desperate ситуации)
sudo umount -l /mnt/data
```

# Дополнительная информация

*   **На лету**: [Перемонтирование (remount)](./remount.md) для изменения опций без остановки работы.
*   **Автоматизация**: [Настройка /etc/fstab](./fstab.md) для постоянного монтирования.
*   **Методы**: Сравнение autofs, udev и systemd в [index.md](./index.md).
*   **Диагностика**: [filesystem_and_disk_space_diagnostics.md](../../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md).
*   **Pet-level устройства**: [Петлевые устройства (Loop Devices)](../loop_devices.md) — losetup, sparse файлы, hot-resize.
