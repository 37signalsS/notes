# Практические сценарии диагностики дискового ввода-вывода (I/O)

Данный документ содержит прикладные кейсы по выявлению и устранению проблем производительности дисковой подсистемы в Linux. Каждый сценарий описывает симптомы, теоретическую причину, методику диагностики и remediation с фокусом на DevOps/SRE-практики — без облачных технологий и AI.

## Определения

- **I/O Wait (`%wa`)**: Процент времени CPU, проведенный в ожидании завершения операций I/O при отсутствии другой полезной нагрузки. Может вводить в заблуждение на многоядерных системах и NVMe-устройствах из-за тиковой модели учета.
- **Pressure Stall Information (PSI)**: Механизм ядра Linux (v4.20+) для измерения реальной задержки процессов из-за нехватки ресурсов. Метрики `some` (хотя бы один процесс ждет) и `full` (все процессы ждут) в `/proc/pressure/io` показывают фактическое влияние на приложения, в отличие от `%iowait`.
- **Latency (Await)**: Среднее время выполнения запроса, включая время в очереди планировщика (queue latency) и время обслуживания устройством (service time). Формула: `await = (Δ Field_7 + Δ Field_11) / (Δ Field_4 + Δ Field_8)` из `/proc/diskstats`.
- **IOPS (Input/Output Operations Per Second)**: Количество операций ввода-вывода в секунду. Для SSD/NVMe важно различать Random (4K) и Sequential (128K+) IOPS.
- **Throughput (Пропускная способность)**: Объем данных, передаваемых в единицу времени (МБ/с). На SSD/NVMe может быть высокой даже при низком `%util` из-за параллельной обработки.
- **Uninterruptible Sleep (D-state)**: Состояние процесса, заблокированного в системном вызове (обычно I/O). Увеличивает `Load Average`. Процесс в `D-state` не реагирует на сигналы, включая `SIGKILL`, пока не завершится операция.
- **avgqu-sz (Average Queue Size)**: Средняя длина очереди запросов к устройству. Рассчитывается из Weighted I/O time (поле 14 `/proc/diskstats`). Для HDD порог перегрузки — >2, для SSD/NVMe >4–8.
- **Writeback**: Фоновый процесс сброса «грязных» страниц из Page Cache на физический носитель потоками `kworker`/`kthread`. Управляется параметрами `vm.dirty_ratio`, `vm.dirty_background_ratio`.
- **blk-mq (Multi-Queue Block I/O)**: Современная архитектура стека I/O ядра Linux с несколькими очередями запросов (по одной на каждое ядро CPU). Критична для NVMe, который имеет 64+ аппаратных очереди. В архитектуре blk-mq метрика `svctm` полностью устарела.
- **io_uring**: Интерфейс асинхронного ввода-вывода Linux (ядро 5.1+), работающий через shared ring buffer между userspace и kernelspace. Обходит классические системные вызовы (`read`/`write`), поэтому не виден в `iotop` и `pidstat -d`.
- **f_await (Flush Await)**: Среднее время выполнения операций сброса кэша (flush). В ядрах 5.5+ данные берутся из полей 19–20 `/proc/diskstats`. Критично для баз данных, где `fsync`/`fdatasync` вызывают flush.
- **r_await / w_await**: Задержка отдельно для чтения и записи. Асимметрия (`w_await` >> `r_await`) указывает на проблему с записью (writeback, журналирование).

## Основные концепции

### Иерархия диагностики

Эффективный поиск проблем I/O должен следовать логике от влияния на систему к конкретному аппаратному сектору:

1. **Общая оценка (System-wide)**: Влияет ли I/O на отзывчивость системы? (PSI, Load Average, vmstat).
2. **Уровень устройств (Block Device)**: Какой именно диск или раздел перегружен? (`iostat`, `/proc/diskstats`, `sar -d`).
3. **Уровень процессов (Process-specific)**: Кто именно генерирует нагрузку? (`iotop`, `pidstat`, `/proc/<pid>/io`).
4. **Уровень ФС и файлов (Filesystem)**: К каким файлам идут обращения? (`fatrace`, `lsof`, `opensnoop`).
5. **Уровень ядра и прерываний (Kernel/IRQ)**: Как ядро обрабатывает запросы? (`wchan`, `perf`, `interrupts`).
6. **Блочная трассировка (Block Tracing)**: Детальный анализ очередей и задержек (`blktrace`, eBPF).
7. **Аппаратный уровень (Hardware)**: Есть ли физические ошибки? (`smartctl`, `dmesg`, `nvme smart-log`).

### Почему классические метрики вводят в заблуждение

На современных NVMe и SSD/NVMe традиционные метрики часто не отражают реальность:
- **`%util` на 100%**: Для NVMe с 64 аппаратными очередями 100% утилизации означает только то, что устройство обрабатывало запросы на каждом интервале сэмплирования, а не насыщение. Ориентируйтесь на `avgqu-sz` и `await`.
- **`svctm` устарела (DEPRECATED)**: В архитектуре blk-mq невозможно корректно рассчитать среднее время обслуживания без учета параллелизма. Игнорируйте эту метрику.
- **Средний `await`**: Прячет «хвостовые задержки» (Tail Latency). 99% быстрых запросов могут скрыть 1% критически медленных (>100 мс), вызывающих фризы приложений.
- **`iowait` на многоядерных системах**: На 32-ядерном сервере `%wa = 3%` может означать, что одно ядро простаивает 100% времени. Используйте PSI или `mpstat -P ALL 1`.

### Почему iowait не отражает реальность

В современных многоядерных системах `%iowait` теряет смысл:
1. **Тиковая модель**: Ядро инкрементирует `iowait` только если CPU простаивает (`idle`) и в очереди есть задача в `D-state`. Если на ядре есть runnable-задача, время ожидания не попадает в счетчик.
2. **Маскировка полезной нагрузкой**: Если в системе всегда есть вычисления, CPU занят ими, и `iowait` остается нулевым при катастрофических задержках диска.
3. **PSI advantage**: Метрика `some avg10` в `/proc/pressure/io` показывает фактическое время простоя процессов, а не CPU.

### cgroups и изоляция I/O

В системах с cgroups v2 доступен `io.pressure` для измерения давления внутри контрольных групп. Лимиты `io.max` могут создавать искусственный троттлинг, который выглядит как деградация диска. В cgroups v1 PSI недоступен, используйте `blkio.io_service_bytes` для косвенной оценки.

### Невидимый ввод-вывод

Традиционные утилиты (`iotop`, `pidstat`) полагаются на `taskstats` и системные вызовы. На каждом уровне стека I/O связь между конечным устройством и исходным процессом может теряться:
- **Writeback**: Физический сброс выполняют `kworker`, а не исходный процесс.
- **io_uring**: Обход классических `read`/`write`.
- **Lock Contention**: Процесс в `D-state` на `inode_lock`, но диск простаивает.
- **FUSE/NFS**: Задержки на уровне userspace или сети.

## Предварительные требования

### Аппаратные требования
- Доступ к целевому блочному устройству (`/dev/sdX`, `/dev/nvmeXnY`).
- Для eBPF-инструментов (`bpftrace`, `bcc-tools`) требуется ядро 4.9+ с `CONFIG_BPF=y` и `CONFIG_BPF_SYSCALL=y`.
- Для PSI требуется ядро 4.20+ с `CONFIG_PSI=y`.
- Для TASK_DELAY_ACCT требуется `CONFIG_TASK_DELAY_ACCT=y` (нужна для `iotop`, `pidstat`).

### Программные требования

```bash
# Debian/Ubuntu
sudo apt install sysstat iotop bpfcc-tools bpftrace perf-tools-unstable smartmontools nvme-cli fatrace pidstat

# RHEL/CentOS/Fedora
sudo dnf install sysstat iotop bcc-tools bpftrace perf smartmontools nvme-cli fatrace pidstat

# Arch Linux
sudo pacman -S sysstat iotop bpftrace perf smartmontools nvme-cli fatrace procps-ng

# openSUSE/SLES
sudo zypper install sysstat iotop bpftrace perf smartmontools nvme-cli fatrace procps
```

### Проверка конфигурации ядра

```bash
# Статистика задержек задач
grep TASK_DELAY_ACCT /boot/config-$(uname -r)
# → CONFIG_TASK_DELAY_ACCT=y

# Pressure Stall Information
grep CONFIG_PSI /boot/config-$(uname -r)
# → CONFIG_PSI=y

# eBPF
grep -E "CONFIG_BPF=|CONFIG_BPF_SYSCALL=" /boot/config-$(uname -r)
# → CONFIG_BPF=y
# → CONFIG_BPF_SYSCALL=y
```

### Включение сбора данных

```bash
# Включение статистики задержек задач (если отключено)
echo 1 > /proc/sys/kernel/task_delayacct

# Проверка PSI
[ -e /proc/pressure/io ] && echo "PSI Enabled" || echo "PSI Disabled — добавьте psi=1 в GRUB"

# Включение исторического сбора sysstat
sudo sar -o 1 0
```

## Практические сценарии

### Сценарий 1: Высокий I/O wait при "пустом" iotop

**Симптомы:** `top`/`vmstat` показывает `%wa > 30%` или `b` (процессы в D-state) > 10, но `iotop -o` не выявляет процессов с активной записью или чтением.

**Причина:** Интенсивный **Writeback** или нагрузка на метаданные (журналирование). `iotop` часто не может сопоставить фоновый сброс данных потоками `kworker` с исходным процессом-писателем. В системах с большим объемом RAM (128+ ГБ) dirty pages могут достигать гигантских значений, вызывая burst-записи.

**Диагностика:**
```bash
# 1. Общая картина: PSI подтверждает давление на I/O
cat /proc/pressure/io
# → some avg10=25.00 avg60=10.05 avg300=5.00 total=1234567
# some avg10 > 5-10% — приложения уже испытывают задержки из-за диска.

# 2. Объем грязных страниц
cat /proc/meminfo | grep -E "Dirty|Writeback"
# → Dirty: 2048 MB (критически высокое значение провоцирует агрессивный сброс)
# → Writeback: 512 MB (сейчас выполняется сброс)

# 3. Анализ очередей и свопинга через vmstat
vmstat 1 5
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  b     swpd   free   buff  cache      si   so    bi    bo   in   cs us sy id wa st
# →  12      0  102400  20480 6144000      0    0  4096  8192 1000 200  5  2 60 33  0
# → b=12: 12 процессов в D-state (uninterruptible sleep)
# → bi/bo > 4096: высокая блоковая активность

# 4. Поиск "виновников" через bpftrace (трассировка dirtying страниц)
sudo bpftrace -e 'tracepoint:writeback:writeback_dirty_page { @[comm] = count(); }'
# → result: [postgres] 12500 (показывает, кто "грязнит" память быстрее всех)

# 5. Проверка cgroups (если используется контейнеризация)
cat /sys/fs/cgroup/*/io.stat 2>/dev/null || echo "cgroups v1 или не настроены"
# Для cgroups v2:
cat /sys/fs/cgroup/MyContainer/io.pressure
# → some avg10=30.00 (давление внутри конкретной контрольной группы)

# 6. Идентификация kworker-потоков
ps -eo pid,state,wchan:30,comm | grep " D "
# → 1234 D balance_dirty_pages kworker/2:1
# → 5678 D io_schedule my_app
```

**Ожидаемый результат:** Указан конкретный процесс (или `kworker`/`jbd2`), источник dirty pages и уровень давления через PSI. Валидация: после применения tuning параметры `vm.dirty_*` должны снизить burst-запись и `b` в `vmstat` должен упасть до 0–2.

**Решение:**
- Оптимизация параметров `vm.dirty_ratio`, `vm.dirty_background_ratio`, `vm.dirty_bytes`. Подробнее: [Роль kworker и процессов writeback](./kworker_flush.md).
- Для СХД: увеличение `vm.dirty_bytes` для размазывания writeback во времени.
- Для контейнеров: проверка `io.max` в cgroups v2.

---

### Сценарий 2: Микро-задержки и "длинный хвост" (Tail Latency)

**Симптомы:** Средняя задержка (`await`) в норме (1–2 мс), но приложение периодически "замирает" на 500+ мс, пользователи жалуются на фризы.

**Причина:** Конкуренция за блокировки на уровне ФС (VFS/inode), очереди планировщика или внутренний GC SSD. Также возможен flush-шторм (высокое `f_await` при низком общем `await`), указывающий на отсутствие PLP (Power Loss Protection) или переполнение SLC-кэша.

**Диагностика:**
```bash
# 1. Анализ распределения задержек (гистограмма)
sudo biolatency-bpfcc -D 1 10
# → Ищите значения в корзинах > 100–128 ms.
# → Флаг -D покажет разбивку по дискам (nvme0n1, sda).

# 2. Трассировка конкретных долгих запросов
sudo biosnoop-bpfcc | awk '$NF > 100'
# → Показывает запросы, выполнявшиеся более 100 мс (COMM, PID, LAT(ms), DISK).

# 3. Проверка f_await (flush задержка) — важно для БД и журналирования
iostat -xz 1 3 | grep -E "Device|nvme|sda"
# → nvme0n1    await=1.20  f_await=45.00 (flush задержка в 37 раз выше!)
# → Высокий f_await указывает на отсутствие PLP или переполнение SLC-кэша.

# 4. Анализ lock contention (VFS/inode)
sudo perf lock record sleep 30
sudo perf lock report
# → Ищите функции с наибольшим временем удержания: ext4_inode_lock, xfs_ilock

# 5. Проверка wchan процессов в D-state
ps -eo pid,state,wchan:30,comm | grep " D "
# → 5678 D jbd2_log_wait_commit my_app (ожидание фиксации транзакции)
# → 9012 D ext4_inode_lock my_app (конкуренция за inode)
```

**Ожидаемый результат:** Гистограмма `biolatency` показывает "хвост" >100 ms, `biosnoop` идентифицирует PID-виновника, `perf lock` указывает на конкретную блокировку. Валидация: после устранения contention tail latency падает до P99 < 10 ms.

**Решение:**
- Для VFS contention: переход на XFS (лучшая масштабируемость), использование `noatime`, вынос журнала на отдельный диск.
- Для flush-штормов: проверка наличия PLP на SSD/NVMe, увеличение `vm.dirty_ratio` для редких, но крупных fsync.
- Для SSD GC: ориентация на P99 latency, а не на средние значения; при переполнении SLC-кэша — использование `fio` для тестирования.

---

### Сценарий 3: Высокая задержка при низком `%util` (внешний троттлинг)

**Симптомы:** Приложение работает медленно, `await` достигает 100–500 мс, но `%util` в `iostat` всего 20–40%. `iotop` показывает низкую активность. Многоядерный `%iowait` низок.

**Причина:** Исчерпание лимитов IOPS или пропускной способности на уровне ниже, чем целевое устройство видит ОС. Возможные источники:
- **Гипервизор / VM**: Дросселирование IOPS виртуального диска при превышении лимита пула (`%steal` > 5% подтверждает это).
- **SAN / СХД**: Ограничение IOPS или throughput на уровне массива, порта FC или backend.
- **RAID-контроллер**: Низкий размер stripe, отсутствие кэширования или переполнение контроллера.
- **dm-crypt (LUKS)**: Шифрование добавляет overhead CPU, который маскирует проблему как CPU-bound.

**Диагностика:**
```bash
# 1. Сверка await и %util
iostat -xz 1
# → sda       await=150.00  avgqu-sz=4.50  %util=20.00  r/s=50  w/s=50
# → await высокий, %util низкий, avgqu-sz > 2 — классический признак внешнего троттлинга

# 2. Проверка %steal на виртуализации
mpstat -P ALL 1
# → %steal на одном или нескольких ядрах > 5% — подтверждает overselling

# 3. Проверка аппаратных таймаутов
dmesg | grep -iE "timeout|blocked|reset|abort"
# → nvme nvme0: I/O 123 QID 4 timeout, completion polled
# → sd 0:0:0:0: [sda] FAILED Result: hostbyte=DID_OK driverbyte=DRIVER_OK

# 4. Анализ очереди планировщика
cat /sys/block/sda/queue/nr_requests
# → 128 (размер очереди планировщика; если запросы накапливаются быстрее, чем обрабатываются — очереди растут)

# 5. Проверка dm-crypt overhead
iotop -Pa -o
# → Если dm-crypt/cryptsetup показывает высокий %CPU — шифрование является узким местом
```

**Ожидаемый результат:** Определен источник троттлинга (hypervisor, SAN, RAID controller, dm-crypt). Валидация: после устранения ограничения `await` падает до baseline (<5 ms для SSD, <20 ms для HDD).

**Решение:**
- Для VM: увеличение IOPS/throughput лимитов в гипервизоре, переход на paravirtualized драйверы (`virtio-blk`, `vmw_pvscsi`).
- Для SAN: увеличение лимитов на массиве, проверка zoning/masking, использование multiple paths.
- Для RAID: увеличение stripe size, проверка состояния контроллера, включение write-back кэширования с BBU.
- Для dm-crypt: использование AES-NI (проверка `cat /proc/cpuinfo | grep aes`), отключение `fsync` для не критичных данных.

---

### Сценарий 4: Маскировка нагрузки через io_uring

**Симптомы:** База данных (PostgreSQL 16+, ScyllaDB, RocksDB) или высоконагруженное приложение создает значительную дисковую нагрузку, но `iotop` и `pidstat` показывают нулевой или минимальный I/O.

**Причина:** Использование интерфейса `io_uring`, который работает в обход классических системных вызовов (`read`/`write`), на которых базируется большинство утилит `procps`. Операции выполняются через shared ring buffer между userspace и kernelspace, и `taskstats` не учитывает их корректно.

**Диагностика:**
```bash
# 1. Трассировка активности io_uring через perf
sudo perf record -e 'io_uring:*' -a sleep 5
sudo perf report
# → Показывает события io_uring_link, io_uring_create, io_uring_submit_sqe

# 2. Поиск открытых io_uring-дескрипторов у процесса
ls -la /proc/<PID>/fd/ | grep anon_inode:io_uring
# → если вывод не пуст — процесс использует io_uring

# 3. Трассировка через bpftrace (трассировка отправки запросов)
sudo bpftrace -e 'tracepoint:io_uring:io_uring_submit_sqe { @[comm] = count(); }'
# → [postgres] 4500 (показывает, кто отправляет запросы)

# 4. Блочный уровень (видит io_uring)
sudo biolatency-bpfcc -D 1 10
sudo biosnoop-bpfcc | head -n 20
# → Видит все запросы на уровне блочного устройства, независимо от интерфейса

# 5. Проверка конфигурации PostgreSQL (если это БД)
sudo -u postgres psql -c "SHOW io_uring;"
# → on (если поддерживается)
```

**Ожидаемый результат:** Подтверждено использование io_uring через perf/bpftrace, идентифицирован PID-виновник. Валидация: `biosnoop-bpfcc` показывает активность, которая не видна в `iotop`/`pidstat`.

**Решение:**
- Использовать современные eBPF-инструменты (`biotop`, `biosnoop-bpfcc`, `biolatency-bpfcc`), которые работают на уровне блочных устройств.
- Для мониторинга: `perf record -e 'block:block_rq_issue'` или `bpftrace` на `tracepoint:block:block_rq_issue`.
- Для PostgreSQL: мониторинг через `pg_stat_io` (PostgreSQL 16+) или `pg_stat_database`.

---

### Сценарий 5: Деградация RAID-массива

**Симптомы:** Резкое падение производительности чтения/записи, рост Load Average, `await` растет в 2–10 раз.

**Диагностика:**
```bash
# 1. Проверка статуса программного RAID (mdadm)
cat /proc/mdstat
# → [UUU_U] (символ "_" указывает на выпавший диск)
# → md0: active raid10 sda1 sdb1 sdc1 sdd1
# →      12582912 blocks super 1.2 512K chunks
# →      [====>....]  resync = 60.2% (7582464/12582912) finish=45.0min speed=24536K/sec

# 2. Анализ скорости ребилда (если он идет)
cat /proc/sys/dev/raid/speed_limit_max
cat /proc/sys/dev/raid/speed_limit_min
# → speed_limit_max = 200000 (KB/s) — ограничение ребилда

# 3. Проверка LVM (если используется)
lvs -a -o +devices
# → myvg/mylv   1.00g myvg_rimage_0(0),myvg_rimage_1(0)
# → myvg/rimage_0  1.00g /dev/sda1(1)
# → myvg/rimage_1  1.00g /dev/sdb1(1)

# 4. Анализ ошибок через dmesg
dmesg | grep -iE "md:|raid|sd.*error|nvme.*error"
# → md/raid10:md0: Disk failure on sdd1, disabling device.
# → sd 2:0:0:0: [sdd] FAILED Result: hostbyte=DID_BAD_TARGET

# 5. Проверка аппаратного RAID (megaraid, hpacucli)
sudo megacli -LDInfo -Lall -aALL
# или:
sudo hpacucli ctrl all show config
```

**Ожидаемый результат:** Определен статус массива (degraded, resync, failed), источник проблемы (выпавший диск, ошибка контроллера). Валидация: после замены диска и завершения ребилда `await` возвращается к baseline.

**Решение:**
- Замена неисправного диска. Для минимизации влияния ребилда на приложения можно временно снизить `speed_limit_max`:
  ```bash
  echo 50000 > /proc/sys/dev/raid/speed_limit_max
  ```
- Для аппаратного RAID: проверка кэша контроллера (BBU/CacheVault), обновление прошивки.
- Для LVM on RAID: проверка `vgdisplay -v` и `lvdisplay -m` для соответствия PV/VG/LV.

---

### Сценарий 6: Проблемы выравнивания разделов (Misalignment)

**Симптомы:** Низкая производительность записи на SSD/NVMe или аппаратные RAID, особенно при мелких блоках (4K–8K). Высокий `await` при низком `%util`.

**Диагностика:**
```bash
# 1. Проверка выравнивания разделов (parted)
sudo parted /dev/sda align-check opt 1
# → 1 aligned (если "not aligned" — каждая запись требует Read-Modify-Write цикла)

# 2. Проверка физического размера сектора
cat /sys/block/sda/queue/physical_block_size
cat /sys/block/sda/queue/logical_block_size
# → physical_block_size = 4096 (4K физический сектор)
# → logical_block_size = 512 (логическая эмуляция — может вызывать misalignment)

# 3. Проверка начала раздела
sudo fdisk -l /dev/sda
# → Device     Start    End Sectors Size Type
# → /dev/sda1  2048     ...   (старт с 2048 = 1MB, правильно для 4K native)

# 4. Для RAID: проверка stripe alignment
cat /sys/block/sda/queue/optimal_io_size
# → optimal_io_size = 524288 (512K) — размер stripe для RAID5/RAID6
# Раздел должен начинаться с границы optimal_io_size
```

**Ожидаемый результат:** Разделы выровнены на границу 4K (или 1MB для совместимости). Валидация: `fio --randalign=1` показывает отсутствие Read-Modify-Write penalty.

**Решение:**
- Пересоздание разделов с выравниванием на 1MB (2048 sectors для 512e, 256 sectors для 4K native).
- Для RAID: выравнивание размера раздела под stripe size массива.
- Для NVMe: использование `nvme id-ctrl` для проверки физических параметров.

---

### Сценарий 7: Зависание NFS/CIFS-ресурса

**Симптомы:** Процессы зависают в `D-state`, `Load Average` растет, `iotop` показывает низкую локальную активность, но NFS-клиент "висит".

**Причина:** Зависший NFS-сервер или сетевая проблема. При использовании жесткого монтирования (`hard`) процессы блокируются в `D-state` на неопределенное время. Поток writeback уходит в `D-state` при попытке сброса грязных страниц на NFS.

**Диагностика:**
```bash
# 1. Идентификация процессов в D-state
ps -eo pid,state,wchan:30,comm | grep " D "
# → 5678 D rpc_wait_bit_killable my_app
# → 9012 D nfs_wait_bit_unreserved_logging kworker/2:1

# 2. Проверка состояния NFS-монтирования
nfsstat -m
# → /mnt/nfs from server:/export nfs rw,vers=4.2,rsize=1048576,wsize=1048576,...

# 3. Проверка доступности сервера
showmount -e server
# → export list for server:
# → /export 192.168.1.0/24

# 4. Проверка сетевой задержки
rttest server:/export /mnt/nfs 2>/dev/null || ping -c 3 server

# 5. Проверка опций монтирования
mount | grep nfs
# → server:/export on /mnt/nfs type nfs (rw,relatime,vers=4.2,...)
# → если hard — процессы зависнут намертво
# → если soft — вернется EIO после timeout
```

**Ожидаемый результат:** Определен зависший NFS-сервер или сетевая проблема. Валидация: после восстановления сервера процессы выходят из `D-state`, или после переключения на `soft`/`intr` mount процесс завершается по сигналу.

**Решение:**
- Для быстрого восстановления: `umount -f /mnt/nfs` (force unmount).
- Для предотвращения: использование `soft,intr` опций или `hard,timeo=600,retrans=3` с последующей обработкой EIO в приложении.
- Для writeback на NFS: включение `sync` или `noac` (no attribute caching), снижение `vm.dirty_ratio` на клиенте.

---

### Сценарий 8: Перегрузка журнала ФС (jbd2)

**Симптомы:** Высокая задержка записи, `await` на 3–5 раз выше, чем на чтение (`w_await` >> `r_await`), `iotop` показывает `jbd2/<dev>` с высокой записью.

**Причина:** Массовые мелкие файлы (тысячи `create`/`unlink`/`rename`), агрессивное журналирование (`data=journal` в ext4) или переполнение журнала. Журнал (`jbd2`) выполняет синхронную запись метаданных на диск, что создает bottleneck.

**Диагностика:**
```bash
# 1. Анализ раздельной задержки чтения/записи
iostat -xz 1
# → sda       r/s=100   w/s=5000   r_await=2.00   w_await=25.00
# → w_await в 12 раз выше r_await — проблема с записью метаданных

# 2. Поиск процессов с высоким w_await через pidstat
pidstat -d -p ALL 1
# → PID    kB_wr/s  iodelay  Command
# → 1234   10240    15000    my_app (высокий iodelay — задержка из-за I/O)

# 3. Трассировка файловых операций
sudo fatrace -t -p 1234 | head -n 50
# → 12:00:01 my_app(1234): C /var/spool/myapp/newfile.tmp
# → 12:00:01 my_app(1234): U /var/spool/myapp/oldfile.tmp
# → Массовые create/unlink — нагрузка на журнал

# 4. Проверка размера журнала
tune2fs -l /dev/sda1 | grep -i "journal size\|block count"
# → Journal size: 128M (маленький журнал вызывает частые checkpoint)
```

**Ожидаемый результат:** Определен тип нагрузки (множество мелких файлов, `data=journal`, маленький журнал). Валидация: после изменения параметров `w_await` падает до уровня `r_await` или оба значения становятся < 5 ms.

**Решение:**
- Отключение `data=journal` (переход на `data=writeback` или `data=ordered`) — тестировать на производительность.
- Увеличение размера журнала: `tune2fs -J size=512M /dev/sda1`.
- Переход на XFS (лучшая масштабируемость для тысяч мелких файлов).
- Вынос журнала на отдельный физический диск (RAID1 для журнала ext4).

---

### Сценарий 9: Swap-шторм, маскирующийся под диск

**Симптомы:** Дисковая активность (`bi`/`bo` в `vmstat`) высокая, `await` растет, но приложение не является явно I/O-bound. PSI показывает давление как на memory, так и на I/O.

**Причина:** Нехватка RAM вызывает активный swap (`si`/`so` в `vmstat`) и compact zone (Transparent Huge Pages). Ядро постоянно подгружает страницы из swap и сжимает THP, создавая фоновый I/O, который маскируется под нагрузку приложений.

**Диагностика:**
```bash
# 1. Проверка swap-активности
vmstat 1 5
# → procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
# →  b     swpd   free   buff  cache      si   so    bi    bo   in   cs us sy id wa st
# →  5    10240  10240  20480 2048000    500  300  4096  2048 1000 200 10  5 50 35  0
# → si=500, so=300: активный swap in/out
# → bi/bo высокие: фоновый I/O от swap и THP

# 2. Проверка THP-компакции
cat /proc/sys/vm/nr_compact_migrations
cat /proc/sys/vm/compact_memory
# → nr_compact_mutations растет — ядро активно сжимает THP

# 3. Анализ PSI (memory vs I/O)
cat /proc/pressure/memory
# → some avg10=80.00 (нехватка памяти)

cat /proc/pressure/io
# → some avg10=15.00 (давление на I/O как следствие нехватки памяти)

# 4. Поиск процессов, потребляющих память
ps aux --sort=-%mem | head -n 10
# → postgres  1500  45.2  1.2  ... (потребляет 45% RAM)
```

**Ожидаемый результат:** Подтверждена нехватка RAM, активный swap и THP-компакция. Валидация: после добавления RAM или снижения `vm.swappiness` swap-активность падает до 0.

**Решение:**
- Немедленно: `swapoff -a` (внимание: может убить процессы при нехватке RAM).
- Долгосрочно: добавление RAM, настройка `vm.swappiness=10` (для серверов) или `vm.swappiness=0` (только при критической нехватке).
- Для THP: `echo always > /sys/kernel/mm/transparent_hugepage/enabled` (отключение THP) или `madvise` для приложений.

## Методология валидации

Каждый сценарий должен завершаться валидацией:

1. **Базовый сценарий (Baseline):** Зафиксируйте метрики в нормальном состоянии (`iostat -xz 1 10`, `cat /proc/pressure/io`).
2. **Стресс-тест:** Воспроизведите проблему (`fio`, `stress-ng`, `dd if=/dev/zero of=/tmp/test bs=4K count=1000000 oflag=direct`).
3. **Диагностика:** Примените методики из сценария.
4. **Валидация:** После remediation метрики должны вернуться к baseline.
5. **Мониторинг:** Настройте алерты для предотвращения рецидивов.

## Автоматизация и мониторинг

### Сбор данных для анализа

```bash
# Исторический сбор через sar (sysstat)
sar -d -p 1 3600 > disk_stats.txt

# iostat в JSON формате (sysstat 12+)
iostat -dxo JSON 1 10 > iostat.json

# Парсинг iostat через Python
python3 -c "
import json, subprocess
result = subprocess.run(['iostat', '-dxo', 'JSON', '1', '3'], capture_output=True, text=True)
data = json.loads(result.stdout)
for stat in data['sysstat']['hosts'][0]['statistics']:
    for disk in stat['disk']:
        if disk['await'] > 20:
            print(f\"ALERT: {disk['device']} await={disk['await']}ms\")
        if float(disk['%util']) > 90 and float(disk['aqu_sz']) < 2:
            print(f\"WARNING: {disk['device']} высокий %util при низкой очереди — возможно, SSD/NVMe параллельная обработка\")
"

# Мониторинг PSI через /proc/pressure/io
watch -n1 'cat /proc/pressure/io'
```

### Prometheus alerts (node_exporter)

```yaml
groups:
  - name: disk_io_alerts
    rules:
      - alert: HighIOWait
        expr: |
          (
            node_cpu_seconds_total{mode="iowait"} /
            ignoring(cpu) group_left sum(node_cpu_seconds_total)
          ) * 100 > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий I/O Wait на {{ $labels.instance }}"
          description: "CPU проводит >10% времени в ожидании I/O. Проверьте PSI и iostat."

      - alert: CriticalIOPressureFull
        expr: |
          node_pressure_io_waiting_seconds_total{pagetype="full",slot="avg10"} > 0.1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Критическое давление на I/O ({{ $labels.instance }})"
          description: "Все процессы ждут I/O {{ $value | humanizePercentage }} времени за 10 секунд. Проверьте await и avgqu-sz в iostat."

      - alert: HighDiskLatency
        expr: node_disk_io_time_weighted_seconds_total / node_disk_io_time_seconds_total > 0.02
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка диска {{ $labels.device }} на {{ $labels.instance }}"
          description: "Средняя задержка > 20 ms. Проверьте await через iostat."
```

## Ограничения и особые случаи

### Многоядерные системы

`%iowait` — системная метрика, распределенная по всем ядрам. На 32-ядерном сервере `%wa = 3%` может означать, что одно ядро простаивает 100% времени. Используйте PSI или `mpstat -P ALL 1` для точного анализа.

### Виртуализация (KVM, VMware, Xen)

- `%steal` в `iostat`/`mpstat` показывает время, «украденное» гипервизором. Постоянный `%steal > 5%` — признак overselling или noisy neighbor.
- Паравиртуализированные драйверы (`virtio-blk`, `vmw_pvscsi`) могут кэшировать запросы, скрывая реальную задержку от гостевой ОС.
- В гипервизорных средах throttling часто применяется на уровне хоста; гость видит только результат.

### cgroups v1 vs v2

- **cgroups v1**: `io.stat` существует только для blkio контроллера. Нет PSI (`io.pressure` отсутствует). Используйте `cat /sys/fs/cgroup/blkio/*/io.stat`.
- **cgroups v2**: `io.pressure` доступен, что позволяет измерять давление на I/O внутри контейнера. Лимиты `io.max` создают искусственный троттлинг.
- Внутри контейнера `iotop` видит только процессы этого контейнера.

### Сетевые ФС (NFS, FUSE, CIFS)

- NFS добавляет сетевую задержку, которая в `iotop` выглядит как обычный I/O wait. Используйте `nfsstat -m` и `nfsiostat`.
- FUSE-файловые системы (`sshfs`) блокируют процесс в пользовательском пространстве. Видно по `wchan` (`fuse_dev_read`).
- При зависании NFS-сервера поток writeback уходит в `D-state` на неопределённое время. Единственное решение — `umount -f` или перезагрузка.

### 32-битные системы

На архитектурах, отличных от x86_64, формат `/proc/<pid>/io` остается совместимым, но некоторые eBPF-утилиты могут требовать перекомпиляции.

### SSD и NVMe

- **Write Amplification**: Внутренний GC SSD может увеличивать физическую запись в 3–10 раз относительно логической. `await` может быть низким, но износ носителя ускоряется.
- **SLC-кэш**: Высокий `await` после заполнения SLC-кэша — нормальное поведение consumer SSD. Ориентируйтесь на P99 latency, а не на средние значения.
- **Flush-штормы**: Высокое `f_await` при низком общем `await` указывает на отсутствие PLP (Power Loss Protection).

### RAID и шифрование

- **Hardware RAID**: Контроллер скрывает отдельные диски. `iostat` показывает только виртуальное устройство. Для диагностики используйте утилиты вендора (`megacli`, `hpacucli`).
- **dm-crypt (LUKS)**: Шифрование добавляет overhead на CPU. При высокой нагрузке процесс `dm-crypt` может потреблять CPU, маскируя проблему как CPU-bound.

## См. также

- [Диагностический чеклист ввода-вывода](./diagnostic_checklist.md) — пошаговый алгоритм поиска проблем.
- [Низкий iowait при высокой задержке](./iowait_and_latency.md) — разбор ложных показателей CPU.
- [Невидимый ввод-вывод](./invisible_io.md) — причины, по которым `iotop` может не показывать нагрузку (io_uring, writeback, lock contention).
