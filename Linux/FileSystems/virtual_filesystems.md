# Виртуальные и псевдофайловые системы Linux

## Определения

- **VFS (Virtual File System):** Высокоуровневый слой абстракции в ядре Linux, предоставляющий унифицированный программный интерфейс (POSIX API) для взаимодействия с разнородными файловыми системами. VFS позволяет приложениям использовать стандартные вызовы (`open`, `read`, `write`) независимо от физической природы хранилища (диск, сеть, оперативная память).
- **Псевдофайловая система (Pseudo-filesystem):** Специализированная файловая система, содержимое которой не существует на физическом носителе. Она представляет собой программный интерфейс ядра, оформленный в виде иерархии файлов и каталогов. Данные в таких ФС генерируются ядром динамически («на лету»).
- **Интерфейс «Ядро — Пространство пользователя»:** Основная функция псевдо-ФС — предоставление доступа к структурам данных ядра, системной статистике и механизмам управления параметрами ОС без введения новых системных вызовов.
- **Ramfs:** Простейшая псевдо-ФС в оперативной памяти, не имеющая ограничений по размеру и не поддерживающая swap. В отличие от tmpfs, ramfs не создаёт резервных копий inode и не ограничивает количество файлов, что делает её опасной для production из-за риска исчерпания RAM.
- **Devtmpfs:** Специализированная ФС, автоматически создающая узлы устройств (`/dev/*`) при регистрации драйверов. В современных системах используется совместно с `systemd-udevd`.

## Основные концепции

### Архитектура: VFS как диспетчер

VFS выступает в роли посредника, который перенаправляет запросы от приложений к конкретным драйверам файловых систем. Для псевдо-ФС VFS вызывает функции-обработчики, которые считывают или записывают данные непосредственно в структуры данных в оперативной памяти ядра.
Подробный разбор структур VFS (Superblock, Inode, Dentry) см. в разделе **[Внутреннее устройство ФС](./fs_internals.md)**.

### Принципы работы псевдо-ФС

Все псевдо-ФС следуют общей модели:
1. **Монтирование:** Ядро регистрирует ФС в mount-таблице текущего namespace.
2. **Обработка запросов:** При обращении к файлу VFS вызывает методы (`read`, `write`, `getattr`) обработчиков псевдо-ФС.
3. **Генерация данных:** Обработчики формируют содержимое на основе структур данных ядра (списки процессов, счётчики, конфигурационные параметры).
4. **Кэширование:** Часть данных кэшируется в Page Cache или slab для ускорения повторных обращений.

### Классификация псевдофайловых систем

| Категория | Назначение | Примеры |
| :--- | :--- | :--- |
| **Общего назначения** | Хранение данных в RAM (высокая скорость) | `tmpfs`, `ramfs`, `devtmpfs` |
| **Информационные** | Экспорт статистики и состояния системы | `procfs`, `sysfs` |
| **Конфигурационные** | Динамическая настройка объектов ядра | `configfs`, `cgroupfs` |
| **Отладочные** | Глубокий анализ, трассировка и дампы | `debugfs`, `tracefs`, `pstore` |
| **Безопасность** | Интерфейсы механизмов защиты и изоляции | `securityfs`, `selinuxfs`, `bpffs`, `nsfs` |
| **Производительность** | Работа с большими страницами памяти | `hugetlbfs` |
| **Внутренние** | Служебные системы для IPC и сетевых объектов | `pipefs`, `sockfs`, `anon_inodefs` |
| **Прошивка** | Доступ к переменным прошивки (UEFI/EFI) | `efivarfs` |

## Ключевые псевдофайловые системы

### Временные системы (tmpfs и ramfs)

**tmpfs** — динамическая файловая система в оперативной памяти с поддержкой swap и ограничениями.
- **Особенности для SRE:**
    - **Динамичность:** Потребляет ровно столько RAM, сколько занимают файлы.
    - **Параметры монтирования:** Позволяет ограничивать не только объем (`size`), но и количество файлов (`nr_inodes`).
    - **HugePages:** Современные ядра поддерживают опцию `huge=always` для размещения `tmpfs` в больших страницах памяти, что снижает нагрузку на TLB.
    - **Swap:** При нехватке RAM данные могут быть выгружены в swap (в отличие от ramfs).
- **Типичные точки монтирования:** `/tmp`, `/var/tmp`, `/dev/shm`, `/run`, `/run/lock`.
- **Безопасность:** Обязательно используйте `noexec,nosuid,nodev` для `/tmp` и `/dev/shm`, если приложения не требуют исполнения кода из этих каталогов.

**ramfs** — устаревшая бесконечная ФС в RAM без ограничений.
- **Риски:** Отсутствие лимита `size` позволяет любому процессу заполнить всю RAM, что приводит к OOM Killer или зависанию.
- **Где используется:** Крайне редко; в некоторых embedded-системах как простейший временный носитель.
- **Альтернатива:** Всегда используйте `tmpfs` с явным `size=`.

### Системные интерфейсы (procfs и sysfs)

- **`procfs` (`/proc`):** Содержит информацию о процессах и системную статистику. [Подробнее про procfs](./virtual_fs_proc.md).
- **`sysfs` (`/sys`):** Отражает иерархическую структуру устройств, драйверов и модулей ядра. [Подробнее про sysfs](./virtual_fs_sys.md).

### Конфигурационные системы (configfs и cgroupfs)

**configfs** — ФС для динамического создания и настройки объектов ядра из userspace. В отличие от sysfs (который только читает состояние), configfs позволяет создавать объекты.
- **Типичное использование:** Настройка iSCSI targets, USB Gadget, kernel keyring, `configs` для драйверов.
- **Монтирование:** Обычно автоматически монтируется в `/sys/kernel/config` или `/config`.

```bash
# Проверка монтирования
mount | grep configfs
# → configfs on /sys/kernel/config type configfs (rw,relatime)

# Пример: создание iSCSI target (требует root)
mkdir /sys/kernel/config/target/iscsi/iqn.2024-01.com.example:target1
```

**cgroupfs** — ФС для управления контрольными группами (cgroups). Детальный разбор контроллеров, лимитов и иерархии см. в **[Контрольные группы (cgroups)](../Core/cgroups.md)**.
- **Ключевые пути (cgroups v2):** `/sys/fs/cgroup/` — единая иерархия с файлами `memory.max`, `cpu.max`, `io.max`.
- **Монтирование:** Автоматически systemd. Для ручного управления: `mount -t cgroup2 none /sys/fs/cgroup`.

### Отладочные системы (debugfs, tracefs, pstore)

**debugfs** — ФС для отладки ядра, предоставляет доступ к внутренним структурам данных.
- **Включение:** Ядро должно быть собрано с `CONFIG_DEBUG_FS=y`.
- **Монтирование:** Обычно автоматически в `/sys/kernel/debug`.
- **Сценарии использования:**
    - Исследование ext4 inode и extents (`debugfs -R "extents /file" /dev/sda1`).
    - Просмотр переменной окружения ядра (`cat /sys/kernel/debug/kprobes/list`).
    - Отладка dynamic debug (`echo "module xxx +p" > /sys/kernel/debug/dynamic_debug/control`).

```bash
# Монтирование (если не смонтировано)
sudo mount -t debugfs none /sys/kernel/debug

# Просмотр информации о slab-кэшах
cat /sys/kernel/debug/slabinfo | head -20
```

**tracefs** — специализированная ФС для трассировки ядра (ftrace).
- **Включение:** `CONFIG_TRACING=y`.
- **Монтирование:** Обычно в `/sys/kernel/tracing` (или `/sys/kernel/debug/tracing`).
- **Ключевые файлы:** `trace` (текущий буфер), `available_tracers`, `events/` (точки трассировки).

```bash
# Активация трассировки open()
echo 1 | sudo tee /sys/kernel/tracing/events/syscalls/sys_enter_open/enable
sudo cat /sys/kernel/tracing/trace_pipe | head -50
```

**pstore** — интерфейс для доступа к сообщениям ядра, сохраненным в энергонезависимой памяти (NVRAM) после аварийного завершения системы (Kernel Panic). Критически важен для "посмертного" анализа.
- **Путь:** `/sys/fs/pstore/` (или `/sys/fs/pstore` в зависимости от конфигурации).
- **Форматы:** `dmesg-ramoops-*` (логи dmesg), `panic-*` (регистры паники).

```bash
# Монтирование (если не монтируется автоматически)
sudo mount -t pstore pstore /sys/fs/pstore

# Просмотр лога паники
sudo cat /sys/fs/pstore/dmesg-ramoops-0
```

### Безопасность (securityfs, selinuxfs)

**securityfs** — общая ФС для подсистем безопасности ядра.
- **Путь:** `/sys/kernel/security/`.
- **Использование:** Предоставляет интерфейсы для AppArmor, SELinux, SMACK. Обычно монтируется автоматически при загрузке соответствующих модулей.

**selinuxfs** — специализированная ФС для политик SELinux.
- **Путь:** `/sys/fs/selinux/`.
- **Ключевые файлы:** `enforce` (режим enforcing/permissive), `policy` (политика безопасности), `booleans/` (переключаемые политики).

```bash
# Проверка статуса SELinux
cat /sys/fs/selinux/enforce
# → 1 (enforcing) или 0 (permissive)

# Просмотр доступных булевых политик
ls /sys/fs/selinux/booleans/
```

### Сеть и IPC (sockfs, pipefs, anon_inodefs)

**sockfs** — внутренняя ФС для сокетов (`S_IFSOCK`), невидимая в обычном дереве каталогов. Используется ядром для представления сетевых сокетов.
- **Инспекция:** `ss -x` показывает UNIX-сокеты; `lsof -U` — процессы, их держащие.

**pipefs** — внутренняя ФС для именованных каналов (`S_IFIFO`).
- **Особенность:** Именованные каналы (FIFO) существуют в pipefs, но доступны через обычный путь в корневой ФС благодаря VFS.

**anon_inodefs** — используется для анонимных inode, созданных ядром для специальных целей (eventfd, timerfd, signalfd, memfd).
- **Пример:** `ls -l /proc/<PID>/fd/ | grep anon` показывает анонимные дескрипторы.

### Производительность (hugetlbfs)

**hugetlbfs** — файловая система для работы с HugePages (большими страницами памяти).
- **Размер страницы:** Обычно 2MB (x86_64) или 1GB (с поддержкой 1GB pages).
- **Применение:** СУБД (PostgreSQL, Oracle), высокопроизводительное кэширование, снижение TLB misses.
- **Резервирование:** `echo 1024 > /proc/sys/vm/nr_hugepages` (постоянное) или `echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages` (влияет только на текущий запуск).

```bash
# Создание точки монтирования
sudo mkdir /mnt/huge
sudo mount -t hugetlbfs nodev /mnt/huge

# Проверка доступных HugePages
cat /proc/meminfo | grep -E "HugePages|Hugetlb"
# → HugePages_Total:    1024
# → HugePages_Free:     1024
```

### Прошивка (efivarfs)

**efivarfs** — ФС для чтения и записи переменных UEFI (NVRAM) напрямую из ОС.
- **Путь:** `/sys/firmware/efi/efivars/` (или `/sys/fs/efi/vars/` в старых ядрах).
- **Безопасность:** Некорректная запись может сделать систему незагружаемой. Используйте `efibootmgr` вместо прямого редактирования.
- **Важные переменные:** `BootOrder`, `Boot####`, `SecureBoot`, `SetupMode`.

```bash
# Просмотр всех переменных (осторожно!)
sudo ls /sys/firmware/efi/efivars/

# Изменение порядка загрузки (предпочитаемый способ)
sudo efibootmgr -o 0001,0002,0003
```

### eBPF и серая зона (bpffs)

**bpffs** — ФС для закрепления (pinning) программ eBPF и карт, чтобы они продолжали работать после завершения создавшего их процесса.
- **Путь:** `/sys/fs/bpf/`.
- **Использование:** Мониторинг сети (tc, XDP), трассировка, безопасность (LSM), производительность.
- **Очистка:** Удаление файлов в bpffs автоматически выгружает соответствующие программы.

```bash
# Монтирование (обычно автоматическое)
sudo mount -t bpf none /sys/fs/bpf

# Просмотр закрепленных программ
sudo ls /sys/fs/bpf/prog_*
sudo ls /sys/fs/bpf/map_*
```

### Пространства имен (nsfs)

**nsfs** — внутренняя ФС, используемая для представления пространств имен (Namespaces) процессов.
- **Доступ:** Через `/proc/<PID>/ns/`.
- **Типы namespaces:** `cgroup`, `ipc`, `mnt`, `net`, `pid`, `user`, `uts`.
- **Идентификация:** Каждый namespace имеет уникальный inode, который можно использовать для сравнения (например, проверка, находятся ли два процесса в одном net namespace).

```bash
# Сравнение net namespace двух процессов
readlink /proc/1234/ns/net
# → net:[4026531993]
readlink /proc/5678/ns/net
# → net:[4026531993] (одинаковые — общий namespace)

# Вход в namespace другого процесса
sudo nsenter -t 1234 -n ip addr
```

## Практические сценарии

### 1. Посмертный анализ через pstore

Если сервер перезагрузился из-за Kernel Panic, логи последнего момента могут быть доступны в `pstore`.

**Предпосылки:** Сервер не управляется по IPMI/iDRAC, доступ к консоли ограничен, требуется анализ причины падения.

```bash
# 1. Монтирование pstore (если не монтируется автоматически)
sudo mkdir -p /sys/fs/pstore
sudo mount -t pstore pstore /sys/fs/pstore

# 2. Просмотр лога паники (dmesg) из прошлой сессии
sudo cat /sys/fs/pstore/dmesg-ramoops-0 | less

# 3. Проверка времени падения
sudo dmesg -T | grep -i "kernel panic\|oops" | tail -5

# 4. Если pstore пуст — проверьте конфигурацию ядра
grep CONFIG_RAMOOPS /boot/config-$(uname -r)
# → CONFIG_RAMOOPS=y
# → CONFIG_RAMOOPS_SIZE=134217728 (128MB)
```

**Валидация:**
```bash
# Размер и количество записей
ls -la /sys/fs/pstore/
# → dmesg-ramoops-0  4096  2024-01-15 03:22
```

**Очистка:**
```bash
# Удаление старых записей (обычно автоматическое при новой панике)
sudo rm /sys/fs/pstore/*
```

**Ограничения:**
- Размер ограничен параметром `ramoops.mem_size` (обычно 128MB–1GB). При частых падениях старые записи перезаписываются.
- Требует поддержку в ядре (`CONFIG_RAMOOPS`, `CONFIG_PSTORE`).

### 2. Оптимизация HugePages для баз данных

Монтирование `hugetlbfs` для использования БД.

**Предпосылки:** PostgreSQL/Oracle на сервере с >64GB RAM, высокая нагрузка, TLB misses.

```bash
# 1. Создание точки монтирования
sudo mkdir /mnt/huge

# 2. Монтирование системы
sudo mount -t hugetlbfs nodev /mnt/huge

# 3. Резервирование страниц в ядре
echo 1024 | sudo tee /proc/sys/vm/nr_hugepages

# 4. Проверка резерва
cat /proc/meminfo | grep -E "HugePages|Hugetlb"
```

**Валидация:**
```bash
# Проверка, что PostgreSQL использует HugePages
sudo -u postgres cat /proc/$(pgrep -o postgres)/smaps | grep -i huge
```

**Постоянная настройка (fstab/systemd):**
```bash
# /etc/fstab
hugetlbfs  /mnt/huge  hugetlbfs  defaults  0  0

# Или systemd mount unit
# /etc/systemd/system/hugetlbfs.mount
[Unit]
Description=HugePages Filesystem

[Mount]
What=hugetlbfs
Where=/mnt/huge
Type=hugetlbfs

[Install]
WantedBy=multi-user.target
```

### 3. Защита Tmpfs (Hardening)

При использовании `tmpfs` в `/tmp` или `/dev/shm` важно ограничивать права для повышения безопасности.

**Предпосылки:** Сервер с веб-приложениями, требующими изоляции между пользователями/сервисами.

```bash
# Монтирование с запретом SUID-битов и исполнения кода
sudo mount -t tmpfs -o size=512M,noexec,nosuid,nodev tmpfs /tmp

# Проверка опций
mount | grep /tmp
# → tmpfs on /tmp type tmpfs (rw,noexec,nosuid,nodev,relatime,size=512M)
```

**Постоянная настройка через fstab:**
```bash
# /etc/fstab
tmpfs   /tmp    tmpfs   defaults,noatime,noexec,nosuid,nodev,size=512M  0  0
tmpfs   /dev/shm  tmpfs   defaults,noatime,noexec,nosuid,nodev,size=256M  0  0
```

**Ограничения:**
- `noexec` блокирует исполнение бинарников, но не динамических библиотек через `ld.so`. Для полной изоляции используйте отдельный mount namespace.
- Размер `size=` влияет на общий лимит RAM+Swap. При превышении — `ENOSPC`.

### 4. Работа с OverlayFS (Слоеная ФС)

Хотя `overlayfs` является "стековой" (stacking) ФС, она активно использует механизмы VFS для объединения нескольких каталогов в один (база контейнеров Docker/Podman). Детальный разбор работы OverlayFS в контексте Docker — в **[Драйвере хранения OverlayFS](../../Docker/Docker_fs/docker_overlayfs.md)**.

**Сценарий: standalone OverlayFS для обновления файлов**

```bash
# Объединение нижнего слоя (read-only) и верхнего (writable)
sudo mkdir -p /mnt/merged /mnt/lower /mnt/upper /mnt/work
sudo mount -t overlay overlay -o lowerdir=/usr/bin,upperdir=/mnt/upper,workdir=/mnt/work /mnt/merged
```

**Валидация:**
```bash
# Проверка, что изменения записываются в upperdir
echo "test" | sudo tee /mnt/merged/test.txt
ls -la /mnt/upper/
# → test.txt

# Проверка белых точек (whiteout)
sudo touch /mnt/upper/.wh.test.txt
ls -la /mnt/merged/
# → test.txt исчез
```

### 5. Диагностика и управление через debugfs

**Предпосылки:** Необходимость восстановления удаленных файлов на ext4, анализ структуры ФС, отладка проблем с inode.

```bash
# 1. Монтирование debugfs (обычно в /sys/kernel/debug)
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null || true

# 2. Просмотр списка недавно удаленных файлов (ext4)
sudo debugfs -R "lsdel" /dev/sda1 | head -20

# 3. Восстановление конкретного inode (inode номер из lsdel)
sudo debugfs -R "dump <12345> /tmp/recovered_file" /dev/sda1
```

**Валидация:**
```bash
# Проверка, что файл восстанавливается корректно
file /tmp/recovered_file
# → ASCII text
```

**Ограничения:**
- Работает только с offline-ФС или при монтировании read-only. Для активной ФС используйте `extundelete`.
- На production-дисках монтируйте в read-only: `mount -o remount,ro /mnt/data`.

### 6. Мониторинг slab-памяти через /proc и debugfs

**Предпосылки:** `slabtop` показывает высокий процент `kmalloc` или `dentry`, требуется диагностика утечек.

```bash
# 1. Просмотр топ-кэшей slab
sudo slabtop -s c | head -20

# 2. Детальная информация через debugfs
cat /sys/kernel/debug/slabinfo | grep -E "dentry|inode|kmalloc" | head -10

# 3. Проверка давления на dentry/inode кэш
cat /proc/sys/fs/dentry-state
# → 12345 6789 45 0 0 0  # [количество] [возраст] [макс_%] ...

cat /proc/sys/fs/inode-state
# → 123456 7890 45 0 0 0 ...

# 4. Принудительное освобождение кэша (временно)
echo 3 | sudo tee /proc/sys/vm/drop_caches
```

### 7. Управление efivarfs и troubleshooting UEFI

**Предпосылки:** Необходимость изменения порядка загрузки, удаления старых записей, отключения SecureBoot.

```bash
# 1. Проверка монтирования efivarfs
mount | grep efivarfs
# → efivarfs on /sys/firmware/efi/efivars type efivarfs (rw,nosuid,nodev,noexec,relatime)

# 2. Просмотр BootOrder
sudo efibootmgr -v | grep BootOrder

# 3. Изменение порядка загрузки
sudo efibootmgr -o 0001,0002,0003

# 4. Удаление старой записи
sudo efibootmgr -b 0004 -B
```

**Валидация:**
```bash
# Проверка результата
sudo efibootmgr -v
```

**Ограничения:**
- Прямое редактирование файлов в `/sys/firmware/efi/efivars/` может сломать загрузчик. Используйте `efibootmgr`.
- В режиме `SetupMode` (Secure Boot отключен) система уязвима для cold boot атак.

### 8. eBPF через bpffs: мониторинг и трассировка

**Предпосылки:** Необходимость отслеживания сетевых событий, производительности или событий ядра без модификации кода.

```bash
# 1. Монтирование bpffs (если не смонтировано)
sudo mount -t bpf none /sys/fs/bpf 2>/dev/null || true

# 2. Загрузка программы через iproute2 (трассировка TCP SYN)
sudo tc qdisc add dev eth0 clsact
sudo tc filter add dev eth0 ingress bpf da obj tc_bpf.o sec section

# 3. Просмотр закрепленных программ
sudo ls /sys/fs/bpf/
# → prog_1  map_1

# 4. Удаление программы
sudo tc filter del dev eth0 ingress
```

**Валидация:**
```bash
# Проверка активности
sudo bpftool prog list
# → 1: cgroup_skb  tag 1234567890abcdef  gpl
```

**Ограничения:**
- Требует ядро ≥4.1 для базовых программ, ≥5.x для продвинутых возможностей (BPF CO-RE, libbpf).
- Программы привязаны к версии ядра; перезагрузка требует повторной загрузки.

### 9. nsfs и диагностика пространств имен

**Предпосылки:** Контейнер с странным поведением сети или процессов, требуется проверка изоляции.

```bash
# 1. Просмотр всех namespaces процесса
ls -la /proc/1234/ns/
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 cgroup -> cgroup:[4026531835]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 ipc -> ipc:[4026531839]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 mnt -> mnt:[4026531840]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 net -> net:[4026531993]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 pid -> pid:[4026531836]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 user -> user:[4026531837]
# → lrwxrwxrwx 1 root root 0 Jan 1 00:00 uts -> uts:[4026531838]

# 2. Сравнение namespace с хостом
readlink /proc/1/ns/net
# → net:[4026531839] (init namespace, обычно отличается от контейнера)

# 3. Вход в namespace контейнера
sudo nsenter -t $(docker inspect --format '{{.State.Pid}}' mycontainer) -n ip addr show eth0
```

### 10. tmpfs для разделяемых данных в Docker/Podman

**Предпосылки:** Необходимость передать временные данные между несколькими контейнерами или между хостом и контейнером без записи на диск.

```bash
# Docker: монтирование tmpfs с ограничениями
docker run --tmpfs /run:rw,noexec,nosuid,size=64m \
  --tmpfs /tmp:rw,noexec,nosuid,size=128m \
  nginx:alpine

# Проверка
docker exec <container> df -h /tmp
# → tmpfs  128M  0M  128M  0% /tmp
```

**Валидация:**
```bash
# Проверка опций монтирования внутри контейнера
docker exec <container> mount | grep /tmp
# → tmpfs on /tmp type tmpfs (rw,noexec,nosuid,relatime,size=131072k)
```

### 11. Отладка утечек памяти в ramfs/tmpfs

**Предпосылки:** `/tmp` или `/dev/shm` заполнены, неизвестно, какой процесс пишет.

```bash
# 1. Определение объема tmpfs
df -h /tmp /dev/shm

# 2. Поиск крупных файлов
sudo du -ah /tmp | sort -rh | head -20

# 3. Определение процессов, держащих файлы в tmpfs
sudo lsof +D /tmp | awk '{print $1, $2, $7}' | sort -u

# 4. Проверка удаленных, но открытых файлов
sudo lsof +L1 | grep /tmp
```

## Безопасность

### Жёсткие опции монтирования для временных ФС

| ФС | Опции | Обоснование |
| :--- | :--- | :--- |
| **tmpfs** | `noexec,nosuid,nodev` | Запрет исполнения SUID-бинарников из RAM. |
| **hugetlbfs** | `nosuid,nodev,noexec` | Защита от выполнения кода в HugePages. |
| **pstore** | `ro` (read-only) | Запрет записи в энергонезависимую память. |
| **efivarfs** | `ro` (по умолчанию) | Запись в NVRAM требует root; лишний доступ — риск. |

### Изоляция через mount namespaces

Для контейнеров и service-песочниц используйте отдельные mount namespaces с принудительным `private` propagation:

```bash
# Изоляция точки монтирования
sudo mount --make-private /tmp
sudo unshare --mount --mount-proc /proc -- /bin/bash
```

### Ограничения доступа к отладочным ФС

`debugfs` и `tracefs` предоставляют доступ к внутренним структурам ядра. В production ограничьте доступ:

```bash
# Ограничение доступа к debugfs
sudo chmod 750 /sys/kernel/debug
sudo chown root:developers /sys/kernel/debug
```

## Типичные ошибки и диагностика

| Проблема | Причина и решение |
| :--- | :--- |
| **tmpfs заполняет RAM** | Отсутствует `size=` в опциях монтирования. Добавьте `size=512M` в fstab или опции `mount`. |
| **ramfs приводит к OOM** | Нет лимита размера. Замените на `tmpfs` или настройте `size=` через mount option. |
| **/dev/shm заполнен, приложения падают** | Система разделяемой памяти (POSIX shm, mmap) использует tmpfs по умолчанию. Увеличьте `size=` в `/etc/fstab`. |
| **HugePages не резервируются** | `nr_hugepages` превышает `HugePages_Free` или ядро собрано без `CONFIG_HUGETLBFS`. Проверьте `dmesg | grep -i huge`. |
| **pstore пуст после паники** | `CONFIG_RAMOOPS` отключен или `ramoops.mem_size=0`. Проверьте boot parameters. |
| **bpffs: permission denied** | Ядро без `CONFIG_BPF_SYSCALL` или недостаточно прав CAP_SYS_ADMIN. |
| **efivarfs: read-only filesystem** | Запись в NVRAM требует `CAP_SYS_ADMIN` и включенного EFI maintenance mode. |

## Лучшие практики

1. **Всегда указывайте `size=` для tmpfs** в `/etc/fstab`. Это предотвращает исчерпание RAM.
2. **Используйте `noatime`** (или `lazytime`) для tmpfs, если там хранятся часто читаемые файлы.
3. **Для `/tmp` и `/dev/shm`** применяйте `noexec,nosuid,nodev` в production.
4. **Не монтируйте `debugfs` и `tracefs`** на production-хостах без необходимости; они дают доступ к чувствительным структурам ядра.
5. **HugePages резервируйте заранее** (через `nr_hugepages`), а не динамически, чтобы избежать фрагментации.
6. **Для efivarfs используйте `efibootmgr`** вместо прямого редактирования файлов.
7. **bpffs монтируйте с `mode=0755,uid=0,gid=root`**, если используется только rootless-инструментами.

## Дополнительная информация

### См. также
- [Виртуальная ФС /proc](./virtual_fs_proc.md) — детальный разбор интерфейса процессов.
- [Контрольные группы (cgroups)](../Core/cgroups.md) — управление ресурсами через `cgroupfs`.
- [Пространства имен (Namespaces)](../Core/namespaces.md) — механизмы изоляции, использующие `nsfs`.
