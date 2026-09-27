# Определения

**Монтирование (Mounting)** — процесс логического подключения файловой системы (раздела диска, сетевого ресурса, образа или виртуальной ФС) к определенной директории в едином дереве каталогов Linux.

Эта директория называется **точкой монтирования (mount point)**. После завершения операции содержимое целевого устройства становится доступным для чтения и записи по указанному пути, скрывая исходное содержимое каталога (если оно было).

С точки зрения ядра, монтирование — это связывание структуры данных конкретной файловой системы с объектом в **VFS (Virtual File System)**. Каждый Mount Namespace имеет собственную корневую точку (`/`) и независимую таблицу связей VFS к конкретной ФС. Подробнее: [Mount Namespaces](../../Virtualization/mount_namespaces.md).

**Ключевые понятия:**
- **Точка монтирования (mount point)** — существующий каталог, в который «подставляется» содержимое устройства. При монтировании исходное содержимое каталога скрывается (даже если оно не пустое) и становится снова видимым только после размонтирования.
- **Суперблок (Superblock)** — структура ядра, описывающая смонтированную ФС. Содержит метаданные: размер, тип, состояние, опции.
- **`/etc/mtab`** — на современных системах является символической ссылкой на `/proc/mounts` или `/proc/self/mountinfo`. Отражает текущее динамическое состояние монтирований, включая временные.
- **`/proc/mounts`** — интерфейс ядра для чтения списка активных монтирований. Каждая строка содержит источник, точку монтирования, тип ФС и опции.
- **`/proc/self/mountinfo`** — расширенный формат с дополнительными полями: идентификаторы устройства (major:minor), распространение монтирования (shared/slave/private) и стек нижних ФС. Рекомендуется для диагностики в контейнерных средах.

# Основные концепции

## Методы монтирования

В современной экосистеме Linux выбор метода зависит от требуемой стабильности, скорости загрузки и динамичности окружения.

| Метод | Механизм | Сценарий использования | Сложность | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Ручное** | Команда `mount` | Временное подключение, отладка | Низкая | Для разовых задач |
| **Статическое** | `/etc/fstab` | Постоянные диски, разделы ОС | Низкая | Стандарт для локальных ФС |
| **Systemd mount** | Юниты `.mount` | Сетевые диски, сложные зависимости | Средняя | Современная замена fstab |
| **Systemd automount** | Юниты `.automount` | Ленивое монтирование (по запросу) | Средняя | Альтернатива Autofs |
| **Autofs** | Демон `autofs` | Корпоративные NFS/SMB шары | Высокая | Масштабируемые среды |
| **Udev** | Правила `udev` | Внешние USB/Thunderbolt носители | Высокая | Специфичное оборудование |

## Описание подходов

1. **Традиционный (`/etc/fstab`)**: Самый распространенный способ. При загрузке `systemd-fstab-generator` динамически создает временные `.mount` юниты из содержимого этого файла. Каждая строка содержит шесть полей: устройство, точку монтирования, тип ФС, опции, dump и pass. Подробнее: [fstab.md](./fstab.md).

2. **Декларативный (`systemd`)**: Позволяет задавать зависимости (например, монтировать только после старта `network-online.target`), использовать `BindsTo` для автоматического размонтирования при извлечении устройства и настраивать ленивое монтирование через `.automount`. Рекомендуется для NFS, CIFS и дисков, необходимых для работы конкретных сервисов. Подробнее: [scenarios/systemd_mount.md](./scenarios/systemd_mount.md).

3. **Динамический (`autofs`)**: Монтирование происходит в момент обращения процесса к директории и размонтируется по таймауту. Это предотвращает зависание всей системы при недоступности сетевого ресурса. Поддерживает wildcard-карты и интеграцию с LDAP/SSSD. Подробнее: [scenarios/autofs_mount.md](./scenarios/autofs_mount.md).

4. **Событийный (`udev`)**: Используется для автоматизации монтирования при физическом появлении устройства (hot-plug). В современных системах рекомендуется использовать `systemd-mount` или активацию готовых `.mount` юнитов через `ENV{SYSTEMD_WANTS}` вместо прямого вызова `/bin/mount` (из-за жестких таймаутов udev). Подробнее: [scenarios/udev_mount.md](./scenarios/udev_mount.md).

## Идентификация устройств

Для надежного монтирования и настройки fstab рекомендуется использовать UUID или LABEL вместо имен устройств (`/dev/sda1`), которые могут измениться при перестановке дисков.

```bash
# Получение UUID и TYPE
sudo blkid /dev/sdb1
# → /dev/sdb1: UUID="a1b2c3d4-e5f6-7890-abcd-ef1234567890" TYPE="ext4" PARTUUID="c3d4..."

# Древовидный обзор устройств с ФС
lsblk -f
# → NAME FSTYPE LABEL UUID                                 MOUNTPOINTS
# → sdb1 ext4   Data  a1b2c3d4-e5f6-7890-abcd-ef1234567890 /mnt/data
```

Подробнее о различиях между UUID и PARTUUID: [partitions_and_filesystems.md](../partitions_and_filesystems.md#UUID-vs-PARTUUID-ключевое-различие).

# Специальные типы монтирования

Linux поддерживает продвинутые механизмы управления деревом ФС:

## 1. Bind Mount (Монтирование привязкой)

Создает зеркало уже существующей директории или файла в другом месте. Исходная и целевая точки монтирования разделяют один inode и содержимое.

**Применение:**
- Проброс данных в `chroot`-окружения и контейнеры.
- Переназначение путей без изменения конфигурации приложений (например, перенаправление `/var/www/html` на `/data/www`).
- Монтирование видимости `/proc` и `/sys` в контейнерах (с флагами `MS_BIND`).

**Команды:**
```bash
# Временное монтирование
sudo mount --bind /source /target

# Постоянное решение через /etc/fstab
echo "/data/www /var/www/html none bind 0 0" | sudo tee -a /etc/fstab

# Изменение прав только для точки назначения (например, сделать RO)
sudo mount --bind /source /target
sudo mount -o remount,bind,ro /target
```

Подробнее: [scenarios/directory_mount.md](./scenarios/directory_mount.md) (Сценарий 3), [fstab.md](./fstab.md) (Создание Bind Mount).

## 2. Loop Mount (Петлевое монтирование)

Позволяет монтировать файлы как блочные устройства (через `/dev/loopX`). Драйвер петлевого устройства перехватывает блочные запросы I/O и преобразует их в операции чтения/записи смещений внутри ассоциированного файла.

**Применение:**
- Работа с ISO-образами дистрибутивов.
- Монтирование образов дисков виртуальных машин (qcow2, vmdk).
- Создание зашифрованных файловых контейнеров (LUKS).
- Использование разреженных файлов (Sparse Files) для резервирования места без физического выделения.

**Команды:**
```bash
# Простое монтирование (с autoclear — устройство удалится после umount)
sudo mount -o loop image.iso /mnt/iso

# Контролируемое монтирование через losetup (для разделов и Direct I/O)
sudo losetup --direct-io=on --sector-size=4096 -P -f --show disk.img
# → /dev/loop0
sudo mkfs.xfs /dev/loop0p1
sudo mount /dev/loop0p1 /mnt/data
```

Подробнее: [loop_devices.md](../loop_devices.md).

## 3. OverlayFS (Наложенная ФС)

Объединяет несколько директорий в одну виртуальную точку. Использует слои: `lowerdir` (read-only, базовый слой) и `upperdir` (read-write, слой изменений). При записи в `upperdir` файлы из `lowerdir` не изменяются (Copy-on-Write).

**Применение:**
- Базовая технология для слоев в Docker и Podman (драйвер `overlay2`).
- Live-дистрибутивы (monolithic read-only корень + записываемый tmpfs слой).
- Объединение нескольких источников данных в один вид (mergerfs-подобные сценарии).

**Команда:**
```bash
mount -t overlay overlay -o lowerdir=/ro_base,upperdir=/rw_layer,workdir=/work /merged
```

Подробнее: [virtual_filesystems.md](../virtual_filesystems.md) (Работа с OverlayFS), [Docker/Docker_fs/docker_overlayfs.md](../../Docker/Docker_fs/docker_overlayfs.md) (контекст контейнеров).

## 4. tmpfs (Временная ФС в RAM)

Файловая система в оперативной памяти. Данные теряются при размонтировании или перезагрузке, но обеспечивают максимальную скорость чтения/записи.

**Применение:**
- `/tmp`, `/dev/shm`, `/run` — временные данные, не требующие сохранения.
- Кэширование frequently accessed данных для снижения нагрузки на диск.
- Песочницы для сборки (build directories) с ограничением размера.

**Команда:**
```bash
# Монтирование tmpfs с ограничением размера и безопасными опциями
sudo mount -t tmpfs -o size=2G,noexec,nosuid,nodev tmpfs /tmp
```

Подробнее: [virtual_filesystems.md](../virtual_filesystems.md).

# Распространение монтирования (Mount Propagation)

В системах с пространствами имен (Namespaces), например в контейнерах, важно контролировать, как события монтирования передаются между родителем и потомком. Подробный разбор: [Mount Namespaces](../../Virtualization/mount_namespaces.md).

| Флаг | Поведение | Направление | Типичное использование |
| :--- | :--- | :--- | :--- |
| **Shared** | События передаются в обе стороны | Двустороннее | Монтирование нового диска на хосте видно во всех контейнерах |
| **Slave** | События передаются только от родителя к потомку | Одностороннее | Контейнер получает диски хоста, но не влияет на хост |
| **Private** | Полная изоляция. События не передаются | Изолированное | Полная изоляция файлового дерева контейнера |
| **Unbindable** | Запрещает bind mount данного ресурса | Защита от рекурсии | Предотвращение петель при рекурсивном монтировании |

**Рекурсивные флаги** (`rshared`, `rslave`, `rprivate`) применяют режим распространения ко всей иерархии внутри указанной точки монтирования.

**Практический контекст:** При создании контейнера стандартной практикой является установка `mount --make-rprivate /` для полной изоляции файлового дерева. В Docker по умолчанию корневая ФС контейнера имеет режим `shared` для корректной работы `systemd` внутри.

# Управление и диагностика

## Основные инструменты

- **`mount` / `umount`**: Базовые команды.
    - `umount -l` (Lazy): Размонтировать ФС немедленно, даже если она занята (очистка произойдет после закрытия всех дескрипторов). Полезно при зависании NFS/CIFS.
    - `umount -f` (Force): Принудительное отключение (в основном для NFS/CIFS при потере связи).
    - `umount -R` (Recursive): Размонтирует указанную точку и все вложенные в нее ФС.
- **`findmnt`**: Рекомендуемый инструмент для анализа. Позволяет видеть дерево зависимостей и параметры VFS.
    ```bash
    findmnt --tree          # Дерево монтирования с Propagation flags
    findmnt /data           # Какое устройство смонтировано в каталог
    findmnt -o SOURCE,TARGET,FSTYPE,OPTIONS  # Произвольные колонки
    ```
- **`remount`**: Изменение опций «на лету» (например, `ro` -> `rw`). Единственный способ изменения параметров для корневой ФС (`/`). Подробнее: [remount.md](./remount.md).
- **`systemd-mount`**: Современная утилита для создания временных `.mount` юнитов с корректной обработкой зависимостей.
    ```bash
    sudo systemd-mount /dev/sdb1 /mnt/tmp
    # → Started unit mnt-tmp.mount for /dev/sdb1
    ```

## Просмотр текущих монтирований

```bash
# Дерево всех смонтированных систем
findmnt

# Только конкретный тип ФС
findmnt -t nfs4

# Верификация синтаксиса /etc/fstab
findmnt --verify
# → Success: no errors or warnings detected

# Просмотр через /proc (сырой формат ядра)
cat /proc/mounts

# Расширенный формат с propagation flags и device major:minor
cat /proc/self/mountinfo
```

## Проверка перед перезагрузкой

**Никогда не перезагружайтесь сразу после редактирования `/etc/fstab`!** Ошибка в записи может привести к Emergency Mode.

Подробный алгоритм проверки и нюансы работы `mount -a` описаны в [fstab.md](./fstab.md#безопасная-проверка-конфигурации).

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`mount: can't find in /etc/fstab`** | Неверный UUID, LABEL или путь | Проверьте `blkid` или `lsblk -f` |
| **`mount: wrong fs type, bad option`** | Неверный тип ФС или несовместимые опции | Установите пакет (nfs-utils, cifs-utils) |
| **`target is busy`** | Процесс удерживает ФС или CWD внутри | `lsof +D /mnt/data` / `fuser -vm /mnt/data` |
| **`mount: /mnt: mount point does not exist`** | Директория не создана | `mkdir -p /mnt` |
| **System boots to emergency mode** | Ошибка в fstab при загрузке | `mount -o remount,rw /`, исправьте fstab |
| **NFS mount hangs** | Сервер недоступен или сеть | `soft,timeo=50,retrans=3` вместо `hard` |
| **`No such device` при загрузке** | Устройство недоступно в ранней стадии | Добавьте `nofail` или `x-systemd.device-timeout=10s` |

Подробнее: [fstab.md](./fstab.md) (Типичные ошибки и решения).

# Практические сценарии

| Задача | Рекомендуемое решение |
| :--- | :--- |
| Добавление второго жесткого диска | [Базовая разметка и fstab](./scenarios/basic_partition.md) |
| Production-сервер с LVM + LUKS (шифрование) | [LVM+LUKS сценарий](./scenarios/basic_partition.md#Сценарий-Production-сервер-с-LVM-+-LUKS-полное-шифрование-данных) |
| Перенос `/var/lib/docker` на новый раздел | [Монтирование директории](./scenarios/directory_mount.md) |
| Монтирование сетевой папки (SMB/NFS) | [Systemd mount units](./scenarios/systemd_mount.md) |
| Автомонтирование при обращении | [Настройка Autofs](./scenarios/autofs_mount.md) |
| Автомонтирование USB по подключению | [Udev-монтирование](./scenarios/udev_mount.md) |
| Проброс данных в контейнер или chroot | Bind Mount — [directory_mount.md](./scenarios/directory_mount.md) (Сценарий 3) |
| Восстановление системы через chroot | Bind Mount + chroot — [directory_mount.md](./scenarios/directory_mount.md) (Сценарий 7) |
| Мониторинг health check сетевых монтирований | [network_mount_monitoring.md](./scenarios/network_mount_monitoring.md) |
| Монтирование ISO-образа для установки | Loop Mount — [loop_devices.md](../loop_devices.md) |
| Временное хранилище в RAM для сборки | tmpfs — [virtual_filesystems.md](../virtual_filesystems.md) |
| Аварийное восстановление (read-only корень) | `mount -o remount,rw /` — [remount.md](./remount.md) |
| Восстановление при ошибке fstab (Emergency Mode) | [boot_failure_recovery.md](../../Diagnostics/Troubleshooting/boot_failure_recovery.md) |

## Безопасность монтирования

Для повышения безопасности разделов (особенно `/tmp`, `/var`, `/home`, сетевые шары) рекомендуется использовать следующие опции:

| Опция | Эффект | Рекомендуется для |
| :--- | :--- | :--- |
| `nosuid` | Игнорирование SUID/SGID битов (предотвращает повышение привилегий) | Все несистемные разделы |
| `noexec` | Запрет выполнения бинарных файлов | `/tmp`, `/var`, `/home` |
| `nodev` | Запрет интерпретации блочных/символьных устройств | Несистемные разделы |

Пример безопасной конфигурации для `/tmp`:
```text
tmpfs    /tmp    tmpfs    defaults,size=2G,noexec,nosuid,nodev    0    0
```

Подробнее: [fstab.md](./fstab.md) (Безопасность и опции монтирования).

# Дополнительная информация

## Инструменты и конфигурация
- **Команды:** Справочник по ключам `mount`, `umount` и `findmnt` в [commands.md](./commands.md).
- **Конфигурация:** Детальный разбор опций fstab в [fstab.md](./fstab.md).
- **Перемонтирование:** Механика и сценарии remount в [remount.md](./remount.md).
- **Мониторинг монтирований:** Здоровье NFS/CIFS, обнаружение stale mounts — [network_mount_monitoring.md](./scenarios/network_mount_monitoring.md).

## Сетевые ФС — углублённые материалы
- **NFS (клиент):** Монтирование NFS через fstab и systemd — см. секции в [fstab.md](./fstab.md) и [systemd_mount.md](./scenarios/systemd_mount.md).
- **NFS (сервер):** Полная настройка NFS-сервера — [NFS Index](../../Networking/Services/nfs/index.md).
- **NFS Performance:** Тюнинг `rsize/wsize`, `nconnect`, `actimeo`, pNFS — [nfs_performance.md](../../Networking/Services/nfs/nfs_performance.md).
- **NFS Troubleshooting:** Stale mount, D-state, RPC ошибки, `nfsidmap` — [nfs_troubleshooting.md](../../Networking/Services/nfs/nfs_troubleshooting.md).
- **NFS Monitoring:** `nfsstat`, `nfsiostat`, Prometheus/Grafana — [nfs_monitoring.md](../../Networking/Services/nfs/nfs_monitoring.md).
- **NFS Security:** Kerberos (RPCSEC_GSS), ACL, root_squash — [nfs_security.md](../../Networking/Services/nfs/nfs_security.md).
- **CIFS/Samba (клиент):** Монтирование CIFS через fstab — см. [fstab.md](./fstab.md).
- **CIFS/Samba (сервер):** Настройка Samba-сервера — [Samba Index](../../Networking/Services/samba/index.md).
- **Samba Security:** SMB Signing, Encryption, NTLM/Kerberos — [samba_security.md](../../Networking/Services/samba/samba_security.md).
- **Samba Troubleshooting:** NT_STATUS ошибки, idmap, Winbind — [samba_troubleshooting.md](../../Networking/Services/samba/samba_troubleshooting.md).
- **Samba Monitoring:** `smbstatus`, Prometheus/Grafana — [samba_monitoring.md](../../Networking/Services/samba/samba_monitoring.md).
- **Multipath I/O:** Архитектура, `/etc/multipath.conf`, failover — [iscsi_multipath.md](../../Networking/iSCSI/iscsi_multipath.md).

## Производительность и целостность данных
- **Тюнинг ФС:** Оптимизация через опции монтирования — [performance_tuning.md](../performance_tuning.md).
- **Сравнение ФС:** Выбор между ext4, XFS, Btrfs — [filesystem_types_comparison.md](../filesystem_types_comparison.md).
- **Журналирование:** Режимы `data=ordered/writeback`, барьеры — [journaling.md](../journaling.md).
- **TRIM/fstrim:** Обслуживание SSD — [fstrim_ssd_maintenance.md](../../SystemAdministration/fstrim_ssd_maintenance.md).
- **I/O Schedulers:** Выбор планировщика (none, mq-deadline, bfq) — [io_scheduler_selection.md](../../Diagnostics/Performance/DiskIO/io_scheduler_selection.md).
- **Read-only ФС:** Диагностика и восстановление — [read_only_filesystem_troubleshooting.md](../read_only_filesystem_troubleshooting.md).
- **fsck:** Проверка и восстановление ФС — [fsck.md](../fsck.md).

## Восстановление системы
- **fstab и загрузка:** Восстановление при ошибке fstab — [boot_failure_recovery.md](../../Diagnostics/Troubleshooting/boot_failure_recovery.md).
- **chroot recovery:** Восстановление через chroot — [chroot.md](../../Core/chroot.md).
- **Сброс пароля root:** Через GRUB/initrd — [linux_password_recovery.md](../../SystemAdministration/linux_password_recovery.md).

## Архитектура и изоляция
- **Mount Namespaces:** Изоляция монтирований в контейнерах — [Mount Namespaces](../../Virtualization/mount_namespaces.md).
- **VFS:** Понимание работы [VFS (Virtual File System)](../fs_internals.md).
- **Файловые системы:** Углублённые разборы — [ext4.md](../ext4.md), [xfs.md](../xfs.md), [btrfs.md](../btrfs.md).
- **Контейнеры:** OverlayFS, volumes, bind mounts — [docker_volumes.md](../../Docker/Docker_fs/docker_volumes.md), [docker_overlayfs.md](../../Docker/Docker_fs/docker_overlayfs.md).
- **Diagностика:** [filesystem_and_disk_space_diagnostics.md](../../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md).
