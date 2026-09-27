# Оптимизация производительности файловых систем

## Определения

### Оптимизация производительности файловых систем

**Оптимизация производительности ФС** — это комплекс мер по настройке уровней хранения (Hardware), блочного слоя ядра (Block Layer), параметров виртуальной памяти (VM) и метаданных файловой системы для достижения баланса между пропускной способностью (**Throughput**), задержками (**Latency**) и надежностью данных.

### Слой блочного ввода-вывода (Block I/O Layer)

Инфраструктура ядра, обрабатывающая запросы от ФС к драйверам устройств. В современных ядрах (5.x+) используется архитектура **blk-mq** (Multi-Queue), позволяющая распараллеливать I/O-операции на многоядерных CPU. Запросы от VFS преобразуются в структуры **bio**, которые направляются через request queue устройства к драйверу. Глубина аппаратной очереди (hardware queue depth) для NVMe составляет 32–1024, и её значение должно соответствовать `nr_requests` в `/sys/block/<dev>/queue/`.

### Page Cache (Кэш страниц)

Основной кэш ядра для данных файлов, хранящихся в оперативной памяти. Ядро использует свободную RAM для кэширования чтений с диска, что значительно ускоряет повторные обращения. В современных ядрах Page Cache объединяет функции хранения данных и метаданных файлов. При синхронном вызове (`O_SYNC`, `fsync`) запись блокирует приложение до физического сброса на диск; при асинхронном (`O_DSYNC`) — до сброса метаданных.

### Slab Cache (Кэш слэбов)

Память, выделенная ядром под собственные структуры данных (inode, dentry, task_struct, network buffers). Управляется Slab Allocator и делится на `SReclaimable` (очищаемый под давлением) и `SUnreclaim` (неочищаемый). В отличие от Page Cache, Slab Cache не учитывается в RSS процессов, но может занимать гигабайты RAM на системах с миллионами файлов.

### Writeback (Обратная запись)

Фоновый механизм отложенной записи «грязных» (dirty) страниц из RAM на диск. Управляется потоками `kworker` и подсистемой `balance_dirty_pages()`. Ключевые параметры: `vm.dirty_background_ratio` (порог асинхронного сброса), `vm.dirty_ratio` (порог блокирующего сброса), `vm.dirty_expire_centisecs` (время старения страницы), `vm.dirty_writeback_centisecs` (интервал проверки старых страниц).

### BDI (Backing Device Info)

Структура данных ядра, описывающая характеристики конкретного блочного устройства. Подсистема writeback использует BDI для балансировки нагрузки и применения специфичных лимитов. Статистика BDI доступна в `/sys/class/bdi/<MAJOR:MINOR>/`.

---

## Основные концепции

### Стек ввода-вывода и современные механизмы

1.  **blk-mq (Multi-Queue):** Устраняет узкое место одной очереди, распределяя запросы по аппаратным очередям накопителя (особенно критично для NVMe).
2.  **io_uring:** Современный интерфейс асинхронного I/O, снижающий накладные расходы на системные вызовы за счет разделяемых между ядром и пользователем колец (rings). Использует Submission Queue (SQ) и Completion Queue (CQ) в разделяемой памяти. Для дискового I/O требуется `O_DIRECT` для обхода Page Cache. В ядрах 6.x+ доступен Zero-Copy Networking (`SEND_ZC`, `RECV_ZC`).
3.  **Direct I/O (`O_DIRECT`):** Обход кэша страниц ядра (Page Cache). Используется СУБД для самостоятельного управления буферами.
4.  **`O_SYNC` / `O_DSYNC`:** `O_SYNC` блокирует вызов до физического сброса данных и метаданных; `O_DSYNC` — только метаданных. Оба режима значительно снижают производительность, но гарантируют durability.

### Журналирование и его влияние

Журналирование — основной источник накладных расходов на запись.
- **Вынос журнала (External Log):** Размещение журнала XFS или Ext4 на отдельном быстром устройстве (NVMe/Optane) ускоряет операции с метаданными (создание/удаление файлов) в разы.
- **Режимы Ext4:** `data=writeback` дает максимальную скорость, но не гарантирует сохранность данных при сбое. `data=ordered` — стандартный баланс.
Подробнее см. в **[Журналирование файловых систем](./journaling.md)**.

### Опции монтирования для тюнинга

*   **`noatime` / `lazytime`:**
    *   `noatime` полностью отключает обновление времени доступа.
    *   `lazytime` (ядро 4.0+) хранит время доступа в памяти и сбрасывает на диск только при обновлении других метаданных или размонтировании. Это лучший баланс.
*   **`commit=N` (Ext4):** Увеличение интервала сброса данных журнала (по умолчанию 5с) до 30-60с снижает нагрузку на диск ценой риска потери последних секунд записи.
*   **`discard=async` (Btrfs, ядро 5.6+):** Асинхронная отправка команд TRIM на SSD, что предотвращает "фризы" при массовом удалении файлов.
*   **`nobarrier`:** Отключает барьеры записи. **Критически опасно** без BBU (батарейки) на RAID-контроллере.

### Настройка параметров ядра (Sysctl)

Параметры `vm.*` определяют поведение Page Cache (кэша страниц):

*   **`vm.dirty_background_ratio`:** Процент памяти, при заполнении которого "грязными" (незаписанными) данными ядро начинает фоновую запись на диск. Обычно 5-10%.
*   **`vm.dirty_ratio`:** Максимальный процент памяти для грязных данных. При достижении этого порога процессы блокируются и начинают сами записывать данные на диск. Обычно 10-20%.
*   **`vm.dirty_expire_centisecs`:** Время жизни данных в памяти перед пометкой на сброс (обычно 3000 — 30 сек).
*   **`vm.dirty_writeback_centisecs`:** Интервал пробуждения потоков сброса данных (обычно 500 — 5 сек).
*   **`vm.vfs_cache_pressure`:** Приоритет очистки метаданных (inode/dentry) по сравнению с данными файлов. При значении `< 100` ядро неохотно удаляет метаданные из памяти (полезно для FS с миллионами файлов).

### Планировщики ввода-вывода (I/O Schedulers)

Современный выбор (blk-mq):
*   **`none`:** Рекомендуется для NVMe и высокоскоростных SSD.
*   **`mq-deadline`:** Стандарт для SATA SSD и HDD.
*   **`kyber`:** Низкие задержки на быстрых накопителях.
*   **`bfq`:** Плавность работы на медленных HDD под нагрузкой.
Подробнее см. в **[I/O Schedulers](../Core/kernel/io_schedulers.md)**.

### Writeback storms и BDI

При массовой записи ядро накапливает грязные страницы в Page Cache и сбрасывает их на диск большими порциями. Это создает всплески нагрузки, при которых SSD исчерпывает SLC-кэш и переходит в steady state с низкой скоростью. Каждое блочное устройство представлено через BDI (Backing Device Info), что позволяет ядру балансировать writeback между разными дисками. На системах с 128+ ГБ RAM значения по умолчанию `vm.dirty_ratio` (20%) становятся опасными: 10% от 128 ГБ = 12.8 ГБ, что при сбросе создает "дисковый шторм". Решение — использовать абсолютные значения через `vm.dirty_bytes` и `vm.dirty_background_bytes`.

### Page Cache vs Slab Cache

Page Cache и Slab Cache — два независимых пула памяти:
- **Page Cache:** Данные файлов (бинарники, библиотеки, mmap-сегменты). Может быть освобожден ядром под давлением.
- **Slab Cache:** Структуры данных ядра (inode, dentry, network buffers). Разделяется на `SReclaimable` и `SUnreclaim`.

Параметр **`vm.vfs_cache_pressure`** регулирует баланс между очисткой Slab и Page Cache: `< 100` удерживает метаданные в памяти, `> 100` агрессивно их очищает.

### cgroups v2 I/O control

В современных системах cgroups v2 предоставляют единую иерархию для контроля дискового I/O:
- **`io.weight`:** Относительный вес (1–10000) для распределения полосы пропускания между группами.
- **`io.max`:** Жесткие лимиты (BPS/IOPS). Имеют приоритет над `ionice`.
- **`io.latency`:** Динамическое ограничение низкоприоритетных процессов при превышении задержек высокоприоритетной группы.

```bash
# Установка веса I/O для группы сервиса
echo "100" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.weight

# Жесткое ограничение скорости записи 10 MB/s
echo "wbps=10485760" | sudo tee /sys/fs/cgroup/system.slice/backup.service/io.max

# Ограничение по задержке 125 мс
echo "rt=125000" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.latency
```

### SSD/NVMe специфика

**Burst vs Steady State:** Consumer SSD имеют быстрый SLC-кэш (3–20% объема), дающий burst-производительность в 3–10 раз выше steady state. При заполнении кэша скорость падает до нативной. Enterprise SSD с PLP (Power Loss Protection) и DRAM сохраняют стабильную скорость.

**Ключевые параметры очереди NVMe:**
- `nr_requests`: Глубина очереди (256–1024 для NVMe).
- `read_ahead_kb`: 0 для случайных нагрузок (БД), 128–256 для последовательных.
- `max_sectors_kb`: Максимальный размер запроса (обычно 128K–1M).
- `io_poll`: Hybrid Polling для снижения задержек.

**Over-Provisioning (OP):** Резервирование 10–20% объема диска неразмеченным пространством дает контроллеру место для Garbage Collection, снижает Write Amplification и стабилизирует производительность.

**Тепловое throttling:** При >70–80°C контроллер снижает скорость. Мониторинг через `nvme smart-log` или `smartctl`.

**fstrim.timer:** Периодический TRIM (раз в неделю через systemd-timer) предпочтительнее опции монтирования `discard`, которая вызывает "фризы" при массовом удалении.

---

## Продвинутый тюнинг (FS-Specific)

### Оптимизация XFS

XFS отлично масштабируется для параллельных нагрузок.
- **Allocation Groups (`agcount`):** Диск делится на независимые группы. Увеличение их числа при `mkfs.xfs` позволяет большему количеству потоков одновременно выделять место.
- **Log Buffers (`logbsize`):** Увеличение размера буфера лога в памяти (до `256k`) при монтировании ускоряет транзакции метаданных.
- **Выравнивание RAID:** Параметры `sunit` (chunk size) и `swidth` (число дисков * sunit) позволяют XFS выравнивать запись по границам страйпа RAID.
- **`allocsize=1M`:** Для больших файлов на NVMe уменьшает фрагментацию.

### Оптимизация Ext4

- **`stride` и `stripe-width`:** Аналоги параметров выравнивания XFS для RAID.
- **`lazy_itable_init`:** Ускоряет создание ФС, инициализируя таблицы inode в фоновом режиме после монтирования.
- **`inode_readahead_blks`:** Количество блоков, которые ядро читает вперед при сканировании таблицы inode.
- **`data=writeback`:** Для БД на SSD с UPS — максимальная скорость, но риск потери данных при сбое.

### Оптимизация Btrfs

- **`compress=zstd:N`:** Сжатие прозрачно снижает физический объем I/O, часто увеличивая скорость за счет процессора.
- **`ssd` / `ssd_spread`:** Оптимизация алгоритмов выделения места под физику SSD.
- **`autodefrag`:** Помогает при фрагментации, возникающей из-за CoW (Copy-on-Write) в базах данных.
- **`discard=async`:** Асинхронный TRIM (ядро 5.6+).

### Оптимизация NFS

- **`vers=4.2`:** Использование NFSv4.2 с поддержкой `copy_file_range` и `seek` для снижения overhead.
- **`rsize`/`wsize`:** Увеличение до 1M для последовательных нагрузок.
- **`noatime`:** Отключение обновления времени доступа на клиенте.
- **`soft`/`hard`:** `hard` с `intr` — безопасный вариант для критичных данных; `soft` — для не критичных, но может привести к тихому повреждению при зависании сервера.

---

## Практические сценарии

### Сценарий 1: База данных (OLTP, PostgreSQL)

**Цель:** Минимизация задержек записи (Latency) и предотвращение I/O-фризов.

```bash
# /etc/sysctl.d/99-database.conf
vm.dirty_background_ratio = 3
vm.dirty_ratio = 10
vm.swappiness = 10
vm.vfs_cache_pressure = 50

# /etc/fstab (XFS)
UUID=... /var/lib/postgresql xfs defaults,noatime,logbsize=256k 0 2

# Планировщик для NVMe
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler

# PostgreSQL.conf — базовый профиль для NVMe
shared_buffers = '8GB'
work_mem = '64MB'
maintenance_work_mem = '512MB'
wal_buffers = '64MB'
checkpoint_completion_target = 0.9
effective_io_concurrency = 256
```

**Валидация:**
```bash
# Проверка параметров
sysctl vm.dirty_background_ratio vm.dirty_ratio vm.vfs_cache_pressure
# → 3, 10, 50

# Мониторинг в реальном времени
iostat -xz 1 5 /dev/nvme0n1
# await < 1ms, aqu-sz < 2

# PSI давление на I/O
cat /proc/pressure/io
# → some avg10 < 5%
```

Полный конфиг PostgreSQL для NVMe см. в **[SSD: Burst I/O и деградация](../Core/kernel/ssd_burst_io.md)**.

### Сценарий 2: Файловое хранилище (Медиа, Бэкапы)

**Цель:** Максимальная пропускная способность (Throughput) последовательного I/O.

```bash
# Увеличение опережающего чтения (Read-ahead) до 4МБ
sudo blockdev --setra 8192 /dev/sdb

# Увеличение буферов записи
vm.dirty_background_ratio = 20
vm.dirty_ratio = 40

# Монтирование с увеличенным интервалом фиксации
sudo mount -o remount,commit=60 /mnt/storage
```

**Валидация:**
```bash
# Проверка read-ahead
blockdev --getra /dev/sdb
# → 8192

# Тест последовательной записи
fio --name=seq_write --rw=write --bs=1M --size=10G --filename=/mnt/storage/test \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=1 --time_based --runtime=30
```

### Сценарий 3: Сборка ПО / Множество мелких файлов

**Цель:** Ускорение работы с метаданными.

```bash
# Удержание dentry/inode в памяти
sysctl -w vm.vfs_cache_pressure=50

# Режим writeback для ext4 (риск потери данных!)
tune2fs -O journal_data_writeback /dev/sdc1
# fstab: data=writeback,noatime
```

**Валидация:**
```bash
# Проверка количества dentry в slab
slabtop -s c | grep dentry
# → dentry: 50000 объектов

# Время сборки
time make -j$(nproc)
```

### Сценарий 4: Контейнеры (Docker overlay2)

**Цель:** Стабильная производительность контейнеров на XFS/ext4 без "фризов" writeback.

Docker overlay2 на XFS требует опции `-o noprobe` на ядрах < 5.11 для правильного определения underlying device. На ext4 возможна фрагментация из-за CoW.

```bash
# /etc/sysctl.d/99-container-fs.conf
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15
vm.vfs_cache_pressure = 100  # стандартное значение для контейнеров

# /etc/fstab (XFS для Docker)
UUID=... /var/lib/docker xfs defaults,noatime,nodiratime 0 2

# Ограничение I/O для контейнера (cgroups v2)
echo "wbps=10485760" | sudo tee /sys/fs/cgroup/system.slice/docker-<id>.scope/io.max
```

**Валидация:**
```bash
# Проверка типа ФС
docker info | grep "Storage Driver"
# → Storage Driver: overlay2

# Проверка опций монтирования
findmnt -o TARGET,OPTIONS /var/lib/docker
# → /var/lib/docker xfs rw,noatime,nodiratime,...

# Мониторинг writeback контейнера
cat /proc/meminfo | grep -E "Dirty|Writeback"
```

### Сценарий 5: Логирование и ротация

**Цель:** Минимизация влияния массовой записи логов на производительность приложений.

```bash
# ionice для фоновой записи логов
sudo ionice -c 3 -p $(pgrep -f rsyslogd)

# systemd-юнит для журналирования
# /etc/systemd/system/rsyslog.service.d/override.conf
[Service]
IOSchedulingClass=idle
IOSchedulingPriority=7

# fstrim.timer для SSD
sudo systemctl enable --now fstrim.timer

# Логирование на отдельный диск (если возможно)
# /etc/fstab
UUID=... /var/log xfs defaults,noatime,commit=30 0 2
```

**Валидация:**
```bash
# Проверка приоритета I/O
systemctl show rsyslog -p IOSchedulingClass,IOSchedulingPriority
# → IOSchedulingClass=idle, IOSchedulingPriority=7

# Мониторинг активности
iostat -xz 1 5 /dev/sdb
# await < 10ms, %util < 30%
```

### Сценарий 6: Медиасервер (Jellyfin/Emby)

**Цель:** Высокая пропускная способность при одновременном потоковом вещании.

```bash
# /etc/sysctl.d/99-media-server.conf
vm.dirty_background_ratio = 20
vm.dirty_ratio = 40
vm.swappiness = 10

# /etc/fstab (XFS)
UUID=... /mnt/media xfs defaults,noatime,allocsize=1M 0 2

# Увеличение read-ahead для последовательного доступа
sudo blockdev --setra 16384 /dev/sdc
```

**Валидация:**
```bash
# Проверка параллельных потоков
iostat -xz 1 5 /dev/sdc
# await < 5ms, aqu-sz < 4 при 8 потоках

# Тест через fio (последовательное чтение)
fio --name=seq_read --rw=read --bs=1M --size=20G --filename=/mnt/media/testfile \
    --ioengine=libaio --direct=1 --iodepth=64 --numjobs=8 --time_based --runtime=30
```

### Сценарий 7: CI/CD раннер

**Цель:** Быстрый запуск задач без перегрева и "фризов" при массовой записи.

```bash
# /etc/sysctl.d/99-ci-runner.conf
vm.dirty_background_ratio = 10
vm.dirty_ratio = 20
vm.swappiness = 10

# systemd-юнит для runner
# /etc/systemd/system/gitlab-runner.service.d/override.conf
[Service]
IOSchedulingClass=best-effort
IOSchedulingPriority=4
Nice=-5

# Очистка кэша после джобы
cat << 'EOF' > /usr/local/bin/ci-cache-cleanup.sh
#!/bin/bash
sync
echo 3 | sudo tee /proc/sys/vm/drop_caches
EOF
chmod +x /usr/local/bin/ci-cache-cleanup.sh
```

**Валидация:**
```bash
# Проверка настроек
systemctl show gitlab-runner -p IOSchedulingClass,IOSchedulingPriority,Nice
# → IOSchedulingClass=best-effort, IOSchedulingPriority=4, Nice=-5

# Мониторинг во время задачи
iostat -xz 1 5 /dev/nvme0n1
```

---

## Устранение неполадок

### Проблема 1: I/O stall (процессы "зависают" на записи)

**Симптомы:** `await` > 20 мс (HDD) или > 1 мс (NVMe), `aqu-sz` растет, процессы в состоянии `D` (`balance_dirty_pages`).

**Диагностика:**
```bash
# 1. Проверка очереди и задержек
iostat -xz 1 5 /dev/nvme0n1

# 2. Поиск процессов в D-state
ps -eo pid,state,wchan:30,comm | grep " D "

# 3. Проверка dirty pages
watch -n1 "grep -E 'Dirty|Writeback' /proc/meminfo"
```

**Решение:**
```bash
# Временное снижение порогов
sudo sysctl -w vm.dirty_background_bytes=134217728
sudo sysctl -w vm.dirty_bytes=536870912

# Приостановка топ-писателей
sudo iotop -oP -d 1 | head -n 10
sudo kill -STOP <pid>
```

### Проблема 2: Writeback storm

**Симптомы:** Диск 100% загружен (`%util = 100%`), `await` > 100 мс, `Dirty` растет, `Writeback` не успевает.

**Решение:** См. "Предварительный анализ" в разделе writeback_tuning.md. Немедленно переключитесь на абсолютные значения `vm.dirty_bytes`.

### Проблема 3: Планировщик I/O не применяется

**Симптом:** `cat /sys/block/sda/queue/scheduler` показывает неожиданный планировщик после перезагрузки.

**Решение:** Убедитесь, что устройство не используется LVM/multipath. Примените настройки через udev правила:

```bash
# /etc/udev/rules.d/60-ssd-io-tuning.rules
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
```

Применение:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --type=devices --action=add
```

### Проблема 4: TRIM не работает

**Симптом:** `fstrim -v /` выводит "the discard operation is not supported".

**Решение:**
```bash
# Проверка поддержки TRIM
lsblk -D
# → DISC-GRAN должен быть > 0

# Проверка LUKS
sudo cryptsetup status <name> | grep discard
# → flags: allow_discards

# Для LVM Thin Pool
sudo lvs -o+discards
```

### Проблема 5: NFS "зависает" при записи

**Симптом:** Процессы в `D-state`, `kworker` не возвращается, `NFS_Writeback` растет.

**Решение:**
```bash
# Принудительное размонтирование
sudo umount -f /mnt/nfs

# Проверка опций монтирования
mount | grep nfs
# → async предпочтительнее sync
```

### Проблема 6: Исчерпание inode

**Симптом:** `df -h` показывает свободное место, но `df -i` показывает 0 свободных inode.

**Решение:**
```bash
# Поиск директории с большим количеством файлов
find / -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head
# Удаление временных файлов или пересоздание ФС с большим количеством inode
```

---

## Лучшие практики

### 1. TuneD интеграция

Используйте TuneD для централизованного управления профилями производительности. Кастомные профили храните в Git:

```bash
sudo tee /etc/tuned/postgres-server/tuned.conf << 'EOF'
[main]
summary=Optimized for PostgreSQL on NVMe
include=throughput-performance

[sysctl]
vm.swappiness = 10
vm.dirty_ratio = 20
vm.dirty_background_ratio = 5
vm.vfs_cache_pressure = 50

[disk]
alpm=disable

[bootloader]
cmdline=intel_iommu=on isolcpus=4-7
EOF

sudo tuned-adm profile postgres-server
```

### 2. Мониторинг и оповещения

Ключевые метрики для отслеживания:

| Метрика | Источник | Порог |
| :--- | :--- | :--- |
| `await` | `iostat` | > 1 мс (NVMe), > 20 мс (HDD) |
| `aqu-sz` | `iostat` | > 2 |
| `Dirty` | `/proc/meminfo` | > 5% RAM |
| `vfs_cache_pressure` | `sysctl` | Отклонение от baseline |
| `node_memory_Dirty_bytes` | Prometheus | > 5% RAM |

Полный набор алертов для writeback см. в **[Настройка writeback: параметры ядра](../Diagnostics/Performance/DiskIO/writeback_tuning.md)**.

### 3. Change Management

1. **Тестируйте изменения в staging** перед production.
2. **Версионируйте конфигурации** (`/etc/sysctl.d/`, `/etc/fstab`, udev rules) в Git.
3. **Документируйте отклонения** от стандартных профилей.
4. **Используйте `tuned-adm verify`** для проверки консистентности.
5. **Создавайте откаты:** сохраняйте исходные значения sysctl перед изменением.

### 4. Валидация изменений

После применения любых настроек проверьте:

```bash
# 1. Параметры sysctl применены
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.vfs_cache_pressure

# 2. Dirty pages не накапливаются бесконечно
watch -n5 "grep -E 'Dirty|Writeback' /proc/meminfo"

# 3. Нет аномальной активности kworker
top -bn1 | grep kworker

# 4. Нет процессов в D-state
ps -eo pid,state,wchan:30,comm | grep " D " | grep -c balance_dirty_pages
# Ожидаемо: 0 или единичные случаи при кратковременных пиках
```

### 5. Откат изменений

```bash
# Восстановление стандартных значений ядра
sudo rm -f /etc/sysctl.d/99-custom-tuning.conf
sudo sysctl --system

# Проверка, что значения вернулись к defaults
sysctl vm.dirty_ratio vm.dirty_background_ratio vm.vfs_cache_pressure
# → 20, 10, 100
```

---

## Дополнительная информация

### См. также

- **[Журналирование файловых систем](./journaling.md)** — режимы, JBD2, CIL, write barriers.
- **[I/O Schedulers](../Core/kernel/io_schedulers.md)** — детали архитектуры blk-mq и выбора планировщика.
- **[Настройка writeback: параметры ядра](../Diagnostics/Performance/DiskIO/writeback_tuning.md)** — тонкая настройка `vm.dirty_*` и диагностика writeback storms.
