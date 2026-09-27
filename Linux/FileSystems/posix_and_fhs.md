# POSIX и FHS — стандарты файловой системы

## Определения

- **POSIX (Portable Operating System Interface):** Семейство стандартов IEEE, определяющих интерфейсы взаимодействия между операционной системой и приложениями. Для файловых систем стандарт регламентирует семантику системных вызовов (`open`, `read`, `write`), механизмы блокировок, права доступа и обязательный набор метаданных. POSIX гарантирует, что одна и та же программа будет вести себя одинаково на любом совместимом Unix-подобном дистрибутиве (Linux, FreeBSD, macOS).
- **FHS (Filesystem Hierarchy Standard):** Стандарт, определяющий структуру каталогов и назначение путей в Unix-подобных системах. Он обеспечивает совместимость программ и предсказуемость среды для администраторов. FHS является обязательным для LSB-сертифицированных дистрибутивов.
- **LSB (Linux Standard Base):** Более широкий стандарт для дистрибутивов Linux, который включает в себя FHS как одну из составляющих частей, гарантируя совместимость бинарных файлов и скриптов.
- **UsrMerge:** Архитектурная инициатива по переносу содержимого критических каталогов (`/bin`, `/sbin`, `/lib`) в `/usr`. В современных системах корень (`/`) содержит только символические ссылки на соответствующие подкаталоги в `/usr`. Это упрощает snapshot-ы корня и LiveCD-загрузку.
- **XDG Base Directory Specification:** Стандарт (от freedesktop.org), определяющий, где приложения должны хранить свои конфигурации, данные и кэш в домашней директории пользователя (замена «скрытым» файлам типа `.apprc`).

## POSIX-семантика файловых операций

### Системные вызовы и гарантии

POSIX регламентирует поведение ключевых системных вызовов, что критично для понимания атомарности и безопасности:

| Системный вызов / Флаг | Семантика | Риски при непонимании |
| :--- | :--- | :--- |
| **`open(path, O_CREAT \| O_EXCL)`** | Атомарно создаёт файл; падает с `EEXIST`, если файл уже существует. | Неиспользование `O_EXCL` приводит к race condition (TOCTOU) при создании lock-файлов. |
| **`open(path, O_TRUNC)`** | Обнуляет существующий файл до 0 байт. | Потеря данных при опечатке в пути; всегда проверяйте путь через `O_PATH` или `stat` перед `O_TRUNC`. |
| **`open(path, O_APPEND)`** | Каждая `write()` атомарно дописывается в конец файла. | Без `O_APPEND` запись из нескольких процессов требует `lseek` + `write` с `fcntl`-блокировкой. |
| **`write(fd, buf, n)`** | Может быть частичным (`n` < запрошено) для pipe/FIFO, non-blocking fd или при signal interruption. | Предположение «write пишет всё» — классическая ошибка; требуется цикл `while (written < n)`. |
| **`read(fd, buf, n)`** | Возвращает 0 на EOF, -1 на ошибку. | 0 != ошибка; это сигнал завершения файла. |
| **`fcntl(fd, F_SETLK)`** | POSIX advisory lock (shared/exclusive). | Advisory означает «по договорённости»; без `fcntl` lock процесс может игнорировать блокировку. |
| **`rename(old, new)`** | Атомарная замена файла в пределах одной ФС. | Классический механизм atomic write; crash-безопасно. |
| **`link(old, new)`** | Создаёт жёсткую ссылку (тот же inode). | Жёсткие ссылки невозможны между разными ФС и для директорий (кроме `.` и `..`). |
| **`symlink(target, linkpath)`** | Создаёт символическую ссылку. | dangling symlink если `target` не существует; проверяется только при открытии. |

### Атомарность и гарантии durability

POSIX не гарантирует durability данных до вызова `fsync()` или `fdatasync()`. Ядро может держать данные в Page Cache неопределённое время. Для критичных данных (базы, транзакции):

```bash
# Гарантированная запись на диск
sync
sudo blockdev --flushbufs /dev/sda1
```

### Record locking (fcntl advisory locks)

POSIX advisory locks не привязаны к inode в целом, а к `(pid, fd)`-паре. Это означает:
- Lock наследуется при `fork()` (ребёнок имеет тот же lock)
- Lock автоматически снимается при `close(fd)`
- Lock не конфликтует с `lockf()` (который использует тот же `fcntl`-механизм под капотом)

## POSIX-атрибуты и Inode

Согласно POSIX, каждый объект файловой системы должен быть описан структурой метаданных (Inode). Ключевые атрибуты:

| Атрибут | Описание | Примечание |
| :--- | :--- | :--- |
| **UID / GID** | ID владельца и группы. | Основа разграничения прав доступа. |
| **Mode** | Тип файла и маска прав (rwxrwxrwx). | Включает SUID, SGID и Sticky Bit. |
| **atime** | Время последнего доступа (access). | Может быть отключено (`noatime`) для производительности. |
| **mtime** | Время последнего изменения контента (modify). | Основной триггер для систем сборки и бэкапов. |
| **ctime** | Время изменения метаданных (change). | Обновляется при смене прав или владельца, а не только данных. |
| **Link Count** | Счетчик жестких ссылок. | Файл удаляется физически только когда Link Count = 0. |

### SUID, SGID, Sticky Bit

| Бит | Обычный файл | Директория | Практическое применение |
| :--- | :--- | :--- | :--- |
| **SUID (4)** | Выполняется с правами владельца файла. | Игнорируется (Linux). | `/usr/bin/passwd` — изменение `/etc/shadow`. |
| **SGID (2)** | Выполняется с правами группы файла. | Новые файлы наследуют GID директории. | `/usr/bin/wall`, общие директории (`/shared/projects`). |
| **Sticky (1)** | Игнорируется. | Удалять файлы может только владелец файла. | `/tmp`, `/var/tmp` — защита от `rm -rf` другим пользователем. |

### POSIX ACL

Помимо базовой маски `rwx` для владельца/группы/остальных, POSIX.1e определяет расширенные ACL (Access Control Lists):

```bash
# Просмотр расширенных ACL
getfacl /etc/nginx/nginx.conf

# Установка ACL: пользователь deploy — rwx, группа devs — rx
setfacl -m u:deploy:rwx,g:devs:rx /srv/www
setfacl -d -m u:deploy:rwx,g:devs:rx /srv/www  # наследование для новых файлов

# Резервное копирование ACL
getfacl -R /srv/www > /backup/srv_www.acl
```

**SRE-важность:** ACL критичны при разделении доступа между deploy-юзером и nginx-группой без изменения GID всего каталога.

### File capabilities

POSIX capabilities разбивают привилегии root на отдельные биты (`CAP_NET_BIND_SERVICE`, `CAP_SYS_ADMIN`). Это безопаснее SUID:

```bash
# Nginx слушает 80-й порт без root
sudo setcap 'cap_net_bind_service=+ep' /usr/sbin/nginx

# Проверка
getcap /usr/sbin/nginx
# → /usr/sbin/nginx = cap_net_bind_service+ep
```

## Философия «Всё есть файл»

Интерфейс VFS (Virtual File System) позволяет абстрагировать доступ к ресурсам:
- **Обычные файлы:** Текст, бинарные данные.
- **Директории:** Специальные файлы, содержащие список имен и ссылок на Inode.
- **Устройства:** Блочные (`/dev/sda`) и символьные (`/dev/tty`).
- **Каналы (Pipes):** Механизм IPC (Inter-Process Communication).
- **Сокеты:** Сетевые и локальные (Unix Domain Sockets) точки взаимодействия.
- **События (eventfd, signalfd):** Файловые дескрипторы для уведомлений ядра (epoll).
- **Совместная память (memfd, shm):** `memfd_create()` — анонимный файл в RAM, совместно используемый процессами.

## Иерархия каталогов (FHS 3.0+)

| Путь | Назначение | Особенности (SRE Note) |
| :--- | :--- | :--- |
| `/` | **Root** | Корень системы. Не должен содержать лишних файлов. Размер ≤ 2 ГБ на production. |
| `/bin` | **User Binaries** | Критичные утилиты. Теперь обычно симлинк на `/usr/bin`. |
| `/boot` | **Bootloader** | Ядро и файлы GRUB. Часто отдельный раздел (vfat/ext2/4). |
| `/dev` | **Devices** | Виртуальная ФС `devtmpfs` с файлами устройств. |
| `/etc` | **Configuration** | Только текстовые конфиги. Динамические данные здесь — антипаттерн. |
| `/home` | **User Homes** | Данные пользователей. Рекомендуется выделять в отдельный раздел/LVM. |
| `/lib` | **Shared Libraries** | Библиотеки для `/bin` и `/sbin`. Симлинк на `/usr/lib`. |
| `/media` | **Removable Media** | Точки монтирования для USB, CD-ROM (автоматические). |
| `/mnt` | **Mount** | Временные точки монтирования для ручных операций. |
| `/opt` | **Optional Software** | Проприетарное или стороннее ПО «всё в одном» (например, Google Chrome). |
| `/proc` | **Process Info** | Псевдо-ФС с информацией о процессах и параметрах ядра. |
| `/root` | **Root Home** | Домашний каталог root. Всегда на корневом разделе. |
| `/run` | **Runtime Data** | Данные процессов (PID, сокеты). Хранится в `tmpfs` (RAM). |
| `/sbin` | **System Binaries** | Утилиты администрирования. Симлинк на `/usr/sbin`. |
| `/srv` | **Service Data** | Данные сайтов, FTP, баз данных. Используется редко, чаще заменяется на `/var/www` или `/opt`. |
| `/sys` | **System Info** | Псевдо-ФS для управления драйверами и оборудованием. |
| `/tmp` | **Temporary** | Временные файлы. Обычно очищается при загрузке. |
| `/usr` | **User Hierarchy** | Основной объем системного ПО. Должен быть доступен в Read-Only. |
| `/var` | **Variable Data** | Логи, кэши, spool-очереди. Обязателен отдельный раздел для защиты от переполнения `/`. |

### Директория /usr и UsrMerge

Современные дистрибутивы (Ubuntu 23.04+, Debian 12+, Fedora) перенесли содержимое `/bin`, `/sbin`, `/lib` в `/usr`:

```bash
# Проверка UsrMerge: /bin → /usr/bin
ls -ld /bin /sbin /lib /lib64

# → lrwxrwxrwx 1 root root 7 /bin -> usr/bin
# → lrwxrwxrwx 1 root root 7 /sbin -> usr/sbin
```

**Преимущества для SRE:**
- Snapshot корневого разлеления (`/`) захватывает только 5–10% данных; основной объём в `/usr` можно сделать отдельным read-only разделом.
- LiveCD-загрузка работает единообразно: монтируется `/usr` один раз.

### /run — временные данные процессов

`/run` — это `tmpfs`, монтируемый ядром на ранней стадии загрузки. Директории создаются systemd или скриптами `tmpfiles.d`:

```bash
# Что создаётся в /run
systemd-tmpfiles --create --prefix /run

# → /run/user/1000/ (runtime user state)
# → /run/lock/ (lock-файлы)
# → /run/systemd/ (systemd runtime state)
```

## Переменные окружения и PATH

### Ключевые переменные

| Переменная | Назначение | SRE-примечание |
| :--- | :--- | :--- |
| **`PATH`** | Список директорий для поиска исполняемых файлов. | Без полного PATH команды ищутся только в `/bin` и `/usr/bin`. |
| **`HOME`** | Домашняя директория пользователя. | Используется большинством CLI-утилит для хранения конфигов. |
| **`LANG` / `LC_*`** | Локализация. | Неустановленная `LANG=C.UTF-8` приводит к сбоям в awk, sort, sed. |
| **`TMPDIR`** | Директория для временных файлов (переопределяет `/tmp`). | Используется компиляторами, сборщиками; при нехватке места в `/tmp` сборка падает. |
| **`XDG_*`** | Стандартизированные пути для конфигов/кэша. | См. раздел практических сценариев. |

### PATH и безопасность

```bash
# Проверка PATH: нет ли '.' или writable директорий в начале
echo "$PATH" | tr ':' '\n' | nl

# Уязвимый PATH: '.' или /tmp в начале
# → 1 .
# → 2 /usr/local/sbin
# → 3 /usr/local/bin
# ...

# Исправление: удалить пустые и '.' элементы
PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '^\.$' | paste -sd:)
```

## Разрешение путей (Path Resolution)

Алгоритм, по которому ядро преобразует строку пути в inode:

1. **Текущий рабочий каталог (CWD):** Если путь относительный, ядро начинает с dentry текущего каталога процесса.
2. **Поиск компонентов:** Для каждого компонента пути (`/usr/bin/ls` → `usr`, `bin`, `ls`):
   - Проверяется dentry cache (dcache). При промахе — чтение директории с диска.
   - Для каждого каталога проверяются права `x` (execute/search).
3. **Символические ссылки:** При встрече symlink ядро выполняет повторный поиск по целевому пути.
4. **Кэширование:** Результат кэшируется в dcache (TTL зависит от пересоздания dentry).

### mount propagation и view

```bash
# Видимость точки монтирования в namespace
ls /proc/1/ns/mnt
ls /proc/self/ns/mnt

# Проверка shared-монтирований (видно во всех namespace)
findmnt -o TARGET,PROPAGATION /
# → / shared
```

### Pathconf и лимиты

```bash
# Максимальная длина пути и имени файла для текущей ФС
pathconf /tmp FILESIZEBITS
pathconf /tmp PATH_MAX
pathconf /tmp NAME_MAX
# → NAME_MAX может быть 255 (ext4) или 508 (XFS)
```

## Практические сценарии

### 1. Работа со стандартами XDG

Для чистоты в домашней директории скрипты должны учитывать переменные окружения:
```bash
# Использование путей по умолчанию, если переменные не заданы
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}"

mkdir -p "$CONFIG_DIR/myapp"
```

### 2. Верификация UsrMerge

Проверка того, что система следует современной иерархии:
```bash
for dir in /bin /sbin /lib /lib64; do
    [ -L "$dir" ] && echo "$dir is a symlink (UsrMerge Active)"
done
```

### 3. Аудит PATH (SRE hardening)

Поиск уязвимостей в PATH:
```bash
# Найти пустые элементы PATH и точки входа в начале
echo "$PATH" | tr ':' '\n' | nl

# Убедиться, что /usr/local/sbin присутствует (часто забывают)
command -v iftop || echo "WARNING: /usr/local/sbin not in PATH"
```

### 4. Проверка POSIX-совместимости (Rights)

При монтировании сетевых ФС (NFS, SMB) важно проверять поддержку POSIX-атрибутов:
```bash
# Создание файла и проверка смены владельца (chown)
touch /mnt/nfs/test_posix
sudo chown 1000:1000 /mnt/nfs/test_posix
stat /mnt/nfs/test_posix # Если UID/GID не изменились — ФС не POSIX-совместима
```

### 5. Разделение /tmp и /var/tmp

- **`/tmp` (tmpfs):** Используйте для мелких временных файлов.
- **`/var/tmp` (Disk):** Используйте для больших данных (например, образов при сборке), которые должны пережить перезагрузку или не влезают в RAM.

### 6. Диагностика FHS-нарушений (SRE audit)

Скрипт для проверки, что критичные пути соответствуют FHS:
```bash
#!/bin/bash
# fhs_audit.sh — проверка соответствия FHS 3.0
set -euo pipefail

echo "=== Checking /bin ==="
if [ -L /bin ]; then
    echo "OK: /bin is symlink (UsrMerge)"
else
    echo "WARN: /bin is real directory — UsrMerge may be inactive"
fi

echo "=== Checking /usr shared ==="
if mountpoint -q /usr; then
    echo "OK: /usr is separate mount"
else
    echo "WARN: /usr is on root filesystem — snapshot granularity reduced"
fi

echo "=== Checking /var/log symlinks ==="
if [ -L /var/log ]; then
    echo "WARN: /var/log should not be symlink"
fi

echo "=== Checking /run tmpfs ==="
findmnt -n -o SOURCE --target /run | grep -q tmpfs && echo "OK: /run is tmpfs" || echo "FAIL: /run is not tmpfs"
```

### 7. Настройка TMPDIR для сборок

```bash
# Для CI/CD: переопределить TMPDIR на отдельный раздел
export TMPDIR=/var/tmp/build
mkdir -p "$TMPDIR"
# → Сборка больших артефактов не завалит /tmp (tmpfs)
```

### 8. Проверка dentry и dcache (отладка path resolution)

```bash
# Просмотр dentry-кэша для конкретного пути
sudo cat /proc/sys/fs/dentry-state
# → 12345 12340 1800 0 0 0 0 (highwater, nr_dentry, age)

# Принудительная инвалидация dcache (debug)
echo 3 > /proc/sys/vm/drop_caches
```

### 9. Проверка ACL и capabilities

```bash
# Проверка POSIX ACL на критичных конфигах
getfacl /etc/ssh/sshd_config

# Проверка file capabilities
getcap /usr/bin/ping /usr/bin/newgrp /usr/sbin/pppd
```

### 10. LSB-совместимость проверка

```bash
# Проверка наличия критичных для LSB путей
for path in /bin/sh /lib/ld-linux.so.2 /usr/bin/lsb_release; do
    [ -e "$path" ] && echo "OK: $path" || echo "MISSING: $path"
done
```

### 11. Диагностика mount propagation

```bash
# Найти все shared-монтирования (часто источник проблем с Docker/K8s)
findmnt -o TARGET,PROPAGATION -t ext4,xfs

# Включить private propagation для /mnt
mount --make-private /mnt
```

### 12. Проверка и исправление сломанных symlinks в /usr

```bash
# Найти broken symlinks в /usr (может сломать систему после обновления)
sudo find /usr -xtype l -ls

# Проверить, что /usr указывает на правильное место
readlink -f /usr/bin
# → /usr/bin (not a symlink itself, but under /usr)
```

## Типичные ошибки и диагностика

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **PATH pollution** | `command not found` для утилит в `/usr/local/sbin`. | Установка софта добавила путь, но текущая сессия не подхватила. | `export PATH="/usr/local/sbin:$PATH"` или перелогин. |
| **Устаревший /bin** | Утилиты в `/bin` не обновляются. | UsrMerge отключён; пакеты пишут в `/usr/bin`. | Включить UsrMerge или следить за `/bin` вручную. |
| **/tmp переполнен** | Ошибки записи в сборках, кэш приложений. | tmpfs слишком мал. | Увеличить `tmpfs` в `/etc/fstab` или использовать `/var/tmp`. |
| **/var/log заполнен** | ФС в RO, сервисы падают. | Логи не ротируются. | Проверить `logrotate`, очистить `/var/log`. |
| **FHS нарушение** | Сервис не стартует, конфиг не находится. | Конфиг положен не в `/etc/<app>`, а в `/opt/<app>/etc`. | Придерживаться FHS или указать путь явно. |
| **TOCTOU race** | Иногда lock-файл не срабатывает. | Проверка существования файла и его создание разделены во времени. | Использовать `O_CREAT|O_EXCL`. |
| **Dangling symlink** | «No such file or directory» на существующий путь. | Цель symlink удалена. | `find / -xtype l` для поиска. |
| **ACL не работают** | `setfacl` не влияет на доступ. | ФС смонтирована без `acl` опции. | Добавить `acl` в `/etc/fstab`. |
| **/run сброс после reboot** | PID-файл остаётся после перезагрузки. | Сервис полагается на `/run/<app>.pid`, но `/run` в tmpfs. | Использовать `/run/lock` или systemd RuntimeDirectory. |

## Лучшие практики

### 1. FHS compliance

- Размещайте конфиги только в `/etc/<app>/`. Динамические данные (кэш, PID) — в `/run/<app>/` или `/var/<app>/`.
- Избегайте размещения данных приложений в `/opt/<app>/data` если они изменяются во время работы — используйте `/var/lib/<app>/`.
- `/usr` должен быть доступен в Read-Only на production; исключение — локальные пакеты в `/usr/local`.

### 2. PATH hardening

- Никогда не добавляйте `.` или `/tmp` в PATH.
- Для root PATH должен включать `/usr/local/sbin` и `/usr/sbin`.
- Используйте `hash -r` после установки нового ПО, чтобы обновить хэш-shell.

### 3. tmpfs размеры

- `/run` — достаточно 20% RAM (по умолчанию 10%).
- `/tmp` — выделяйте не более 25% RAM; при необходимости используйте отдельный раздел.
- `/dev/shm` — равна половине RAM; для PostgreSQL/SAP ограничьте через `/etc/fstab` (например, `size=2G`).

### 4. ACL и permissions

- Вместо chmod 777 используйте ACL для тонкого контроля.
- Устанавливайте `acl` опцию в `/etc/fstab` для всех разделов, где нужен детальный контроль.
- Используйте `getfacl`/`setfacl` для массового управления, сохраняйте ACL в `/etc/acl/` для backup.

### 5. Мониторинг целостности

```bash
# Мониторинг изменений в /etc (AIDE, Tripwire, или простой find)
sudo find /etc -type f -exec md5sum {} \; > /var/backups/etc_checksums.md5
diff /var/backups/etc_checksums.md5 <(sudo find /etc -type f -exec md5sum {} \;)
```

### 6. UsrMerge совместимость

- Все новые пути в скриптах пишите относительно `/usr` (например, `/usr/bin/mytool`).
- При переносе системы на раздельный `/usr` проверьте `grub` и `initramfs`: они должны содержать модули для доступа к `/usr`.

## Дополнительная информация

- **Связанные темы:**
  - [Виртуальные ФС (procfs, sysfs)](./virtual_filesystems.md) — детально про `/proc` и `/sys`.
  - [Права доступа к файлам](../Security/Concepts/File_Permissions/overview_definitions.md) — реализация POSIX Permissions.
  - [Монтирование и fstab](./mounting/index.md) — управление иерархией.
  - [Типы файлов в Linux](./file_types.md) — 7 типов файлов по POSIX.
  - [Inode и Dentry](./links_inodes_dentries.md) — физическая реализация метаданных.
  - [Навигация по ФС: cd, pwd](../Shell/file_navigation.md) — базовые команды навигации в контексте FHS.
