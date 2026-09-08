# Диагностика Swap и Page Faults в Linux

## Определения

* **Demand Paging** (Подкачка по требованию): Механизм "ленивого" выделения памяти. Ядро не выделяет физическую страницу (Frame) сразу при вызове `malloc`, а ждет первого обращения к адресу, вызывая Page Fault.
* **Page Fault (ошибка страницы)**: Прерывание процессора, возникающее, когда программа обращается к виртуальной странице памяти, которая не сопоставлена с физической RAM.
* **Minor Page Fault**: Страница уже находится в памяти (например, в Page Cache или разделяемой памяти другого процесса), но не в таблице страниц текущего процесса. Обрабатывается очень быстро (десятки микросекунд).
* **Major Page Fault**: Страница отсутствует в RAM и требует чтения с диска (из исполняемого файла, библиотеки или swap). Главная причина задержек (stalls) при работе приложений.
* **SwapCached**: Объем страниц в Swap Cache, которые были изменены в RAM и ожидают записи обратно в swap-область. Высокое значение означает интенсивный обмен, но не всегда проблему (см. **[Управление Swap](./swap_management.md)**).
* **pgfault** (`/proc/vmstat`): Общее количество Page Faults с момента загрузки. Включает как Minor, так и Major Faults.
* **pgmajfault** (`/proc/vmstat`): Количество Major Page Faults. Это ключевой счетчик для диагностики swap-зависимых задержек.
* **workingset_refault_anon** (`/proc/vmstat`): Количество возвратов вытесненных анонимных страниц (из swap) в рабочее множество. Рост > 1000/сек — признак Thrashing.
* **workingset_refault_file** (`/proc/vmstat`): Возвраты вытесненных файловых страниц из Page Cache. Высокое значение указывает на недостаток RAM для кэша.
* **Swap Free / Swap Total** (`/proc/meminfo`): Общий объем swap и свободное место. `SwapUsed = SwapTotal - SwapFree`.
* **Committed_AS** (`/proc/meminfo`): Общий объем памяти, который ядро гарантирует выделить процессам (RAM + Swap). Если `Committed_AS > SwapTotal + RAM`, система работает в режиме overcommit и рискует столкнуться с OOM.
* **`/proc/swaps`**: Файл, содержащий список активных swap-областей, их типы, размеры и приоритеты. Используется для быстрой инвентаризации.

## Основные концепции

### Почему растет Swap при свободной памяти

Использование swap не всегда означает проблему. Ядро Linux старается максимально эффективно использовать RAM для **Page Cache** (дискового кэша).
* **Стратегия ядра**: Если анонимная страница (память процесса) не использовалась долгое время, ядру выгоднее "выбросить" ее в swap, чтобы использовать освободившиеся 4 КБ для кэширования горячих файлов с диска.
* **Когда это проблема**: Только при **активном и постоянном обмене** (высокие показатели `si`/`so` в `vmstat`), что указывает на то, что "горячий" набор данных (Working Set) не помещается в RAM.

### Алгоритмы Reclaim и дефицит памяти

Ядро проходит через несколько стадий при нехватке памяти:
1. **Background Reclaim (`kswapd`)**: Фоновый процесс просыпается, когда свободная память падает ниже вотермарка `low`. Он пытается мягко очистить кэши и вытолкнуть неактивные страницы в swap.
2. **Direct Reclaim**: Если память падает ниже вотермарка `min`, сам процесс, запросивший память, вынужден остановиться и заниматься очисткой/свопингом. Это вызывает резкие скачки задержек (Latency Spikes).
3. **OOM Killer**: Если очистка не помогла, ядро принудительно завершает процесс.

### Современные механизмы: MGLRU и PSI

1. **MGLRU (Multi-Gen LRU)**: С ядра 6.1 заменяет старый алгоритм активных/неактивных списков. Группирует страницы по "поколениям" доступа, что позволяет ядру точнее понимать, какие страницы действительно "старые", снижая количество ошибочных выгрузок в swap.
   * **Проверка статуса**: `cat /sys/kernel/mm/lru_gen/enabled` (бит 0 — включено, бит 1 — включено для всех типов).
2. **PSI**: Позволяет отличить "полезный" свопинг от деградации. Если `full avg10 > 5-10%` в `/proc/pressure/memory`, система реально теряет производительность. Подробнее: **[Pressure Stall Information (PSI)](../kernel/psi.md)**.

### NUMA и Swap

В мультисокетных системах (NUMA) ядро предпочитает выгружать страницы в локальный swap-устройство. При недоступности локального swap происходит fallback через QPI/UPI, что снижает производительность. Для диагностики:
* **Привязка swap к NUMA-узлу**: `swapon --show` покажет устройство. Для принудительной локальной привязки используйте `numactl --membind=0` при создании swap-файла.
* **Кросс-узельный свопинг**: Если `si`/`so` в `vmstat` растут, а локальный диск не загружен (`iostat` показывает низкий `await`), проверяйте fallback на межпроцессорные шины.
Подробнее о тюнинге NUMA: **[Оптимизация и тонкая настройка памяти](./performance_tuning.md)**.

### Cgroups v2 и лимиты Swap

В cgroups v2 управление swap ограничивается через файлы в `/sys/fs/cgroup/<group>/`:
* **`memory.swap.current`**: Текущее потребление swap.
* **`memory.swap.max`**: Жесткий лимит. При достижении процессы получают `-ENOMEM`.
* **`memory.failcnt`**: Счетчик сбоев аллокаций из-за превышения лимита. Рост `failcnt` без роста `memory.usage_in_bytes` означает, что bottleneck именно в swap.
* **`memory.events`**: Содержит `low`, `high`, `max`, `oom`, `oom_kill` — полезно для корреляции с событиями OOM.

Для диагностики используйте `systemd-cgtop` или прямые чтения из cgroup. Подробнее: **[Ограничение ресурсов контейнеров](../../../Docker/Docker_security/resource_limits.md)**.

### Взаимодействие THP и Swap

**Transparent Huge Pages (THP)** могут как снижать, так и увеличивать нагрузку на swap:
* **Снижение**: THP уменьшает количество записей в Swap Map (одна запись на 2 МБ вместо 512 записей по 4 КБ), снижая overhead.
* **Увеличение**: `khugepaged` может запускать дефрагментацию, вызывая всплески `compact_stall` и временный рост Page Faults.
Диагностика: `cat /sys/kernel/mm/transparent_hugepage/enabled` и `grep compact_stall /proc/vmstat`.

## Практические сценарии

### Алгоритм комплексной диагностики

#### 1. Быстрая оценка системы (vmstat и sar)

```bash
vmstat 1
# si/so: активный свопинг. Постоянные si/so > 0 — признак дефицита.
# wa: I/O wait. Высокий wa при свопинге означает дисковые задержки.

# История Page Faults и свопинга (требует sysstat)
sar -B 1 5 # Статистика страниц (majflt/s, pgscank/s)
sar -W 1 5 # Статистика swap (pswpin/s, pswpout/s)
```

#### 2. Визуализация и PSI (htop и atop)

* **htop**: Нажмите `F2` → `Meters` → `Memory Pressure` (добавьте в правую/левую колонку). Вы увидите графики `some` и `full` PSI прямо в интерфейсе.
* **atop**:
  * `MINFLT` / `MAJFLT`: количество малых и серьезных ошибок страниц.
  * `SWAPSZ`: объем памяти процесса, находящийся в swap.
  * Режим памяти (клавиша `m`): Показывает `VSIZE`, `RSIZE`, `PSIZE` (PSS).

#### 3. Превентивная защита (systemd-oomd)

Если в системе настроен `systemd-oomd` (стандарт в Ubuntu 22.04+, Fedora), он может убивать процессы до срабатывания ядерного OOM Killer на основе PSI.
```bash
# Проверка статуса мониторинга cgroups
oomctl dump
# → Swap Used Limit: 90.00%
# → Default Memory Pressure Limit: 60.00%
```

#### 4. Глубокий анализ Page Faults (perf и bpftrace)

**perf**: Позволяет увидеть, какие функции ядра или приложения вызывают Major Faults.
```bash
# Сбор статистики по Major Faults для всей системы
sudo perf record -e major-faults -a -g -- sleep 10
sudo perf report
```

**bpftrace**: Измерение задержки обработки Page Faults (требует eBPF).
```bash
# Гистограмма задержек Page Faults (в микросекундах)
sudo bpftrace -e 'software:page-faults:1 { @start[tid] = nsecs; } 
    software:page-faults:0 /@start[tid]/ { @us = hist((nsecs - @start[tid]) / 1000); delete(@start[tid]); }'
```

#### 5. Идентификация конкретных потребителей (smem и pidstat)

`smem` — наиболее точный инструмент, учитывающий PSS (Proportional Set Size).
```bash
# Топ процессов по реально занимаемому Swap
smem -t -k -s swap -r | head
```

`pidstat` — детальный мониторинг Major Faults в реальном времени:
```bash
pidstat -r 1
# majflt/s: ищите процессы с постоянным ростом этого счетчика.
```

### Диагностика сжатого Swap (Zram/Zswap)

Если используется Zram, обычные утилиты покажут использование "диска", но реально это RAM.
```bash
# Статистика Zram
zramctl
# DATA: реальный объем данных, COMPR: объем после сжатия.

# Статистика Zswap (кэш перед диском)
grep -r . /sys/kernel/debug/zswap/
# zswap_stored_pages: количество страниц в кэше.
```

### Быстрая триазна: free, swapon и /proc/swaps

Перед глубоким анализом выполните быструю инвентаризацию swap:
```bash
# 1. Сводка по памяти и swap
free -h
#              total        used        free      shared  buff/cache   available
# Mem:          31Gi       5.1Gi       2.1Gi       256Mi        24Gi        25Gi
# Swap:         4Gi       512Mi       3.5Gi
# → SwapUsed > 25% требует внимания при наличии Major Faults

# 2. Список активных swap-устройств
swapon --show
# NAME      TYPE  SIZE USED PRIO
# /dev/sda2 partition 4G 512M -2
# /dev/zram0 partition 2G 0M 100

# 3. Детализация из /proc
cat /proc/swaps
# Filename                Type        Size    Used    Priority
# /dev/sda2               partition   4194300 524288   -2
# /dev/zram0              partition    2097144      0    100
```

### Глубокий анализ /proc/meminfo

```bash
# Ключевые поля для диагностики swap
grep -E "SwapTotal|SwapFree|SwapCached|Committed_AS|VmallocChunk|Pagetables" /proc/meminfo
# SwapTotal:        4194304 kB
# SwapFree:         3670016 kB
# SwapCached:         16384 kB
# Committed_AS:    8388608 kB
# → Committed_AS (8 GB) > SwapTotal (4 GB) + часть RAM: overcommit риск

# Анализ Slab (взаимосвязь с swap)
grep -E "SReclaimable|SUnreclaim" /proc/meminfo
# SReclaimable:     524288 kB
# SUnreclaim:       262144 kB
# → Высокий SUnreclaim означает, что ядро не может освободить кэши и вытесняет процессы в swap
```

### Глубокий анализ /proc/vmstat

```bash
# Page Faults и swap I/O
grep -E "pgfault|pgmajfault|pswpin|pswpout|workingset_refault" /proc/vmstat
# pgfault                 1523421
# pgmajfault               89123
# pswpin                      456
# pswpout                     789
# workingset_refault_anon    2341
# workingset_refault_file     456
# → pgmajfault > 0 при низком available = активный swap-in
# → workingset_refault_anon > 1000/сек = Thrashing

# Исторический рост (сравнение с snapshot через 10 секунд)
sleep 10 && grep -E "pgfault|pgmajfault|pswpin|pswpout" /proc/vmstat
```

### Корреляция с дисковым I/O

Swap-операции видны в `iostat` и `iotop` как высокий `await` и активность на swap-устройстве:
```bash
# iostat: ищите высокий await (> 10 мс) на диске swap
iostat -xz 1 5
#Device      r/s     w/s     rkB/s     wkB/s   rrqm/s   wrqm/s  %util await  await_r  await_w
#sda         10.0    50.0    400.0   2000.0     0.0     5.0  12.0   2.5     1.0      3.0
# → высокий await на sda при активном swapon = дисковая узкое место

# iotop: сортировка по DISK WRITE для поиска kswapd или swap-процессов
sudo iotop -oP
# → kolip_palwrite  0.00 B/s    2.00 MB/s  [kswapd0]
```

### Диагностика cgroup v2 swap

Для контейнерных сред (Docker, Kubernetes) проверяйте лимиты swap:
```bash
# Для конкретного контейнера
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.swap.current
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.swap.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.failcnt
# → failcnt > 0 = контейнер пытался выделить swap, но уперся в лимит

# Сводка по всем cgroups
systemd-cgtop -m swap
# или через find
find /sys/fs/cgroup -name memory.swap.current -exec sh -c 'echo "{}: $(cat {})"' \;
```

### Расширенный анализ через sar

```bash
# Page Faults в реальном времени (sysstat)
sar -B 1 10
# 10:00:01 AM  majflt/s  pgfree/s pgscank/s pgscand/s  pgsteal/s %vmeff
# 10:00:02 AM      45.60   12500.0     800.0     200.0    1500.0   85.00
# → majflt/s > 0 постоянно = проблемы

# Исторические данные за день
sar -W -f /var/log/sysstat/sa10
# 12:00:01 AM     pswpin/s pswpout/s
# 12:00:01 AM         0.00      0.00
# ...
# 08:00:01 AM       12.50     18.00
# → пик swap-активности с 08:00 = утренний вход пользователей / запуск задач
```

### perf: идентификация функций-виновников

```bash
# Топ функций по Major Faults
sudo perf record -e major-faults -a -g -- sleep 10
sudo perf report --stdio | head -50
# → Сортировка по количеству Major Faults для каждого процесса/функции

# Для конкретного процесса
sudo perf record -e major-faults -p $(pidof postgres) -- sleep 10
sudo perf report
```

### SRE аудит и runbook

#### Ежедневный аудит swap

```bash
#!/bin/bash
# runbook: daily_swap_audit.sh
echo "=== Swap Overview ==="
free -h
echo "=== Active Swap Devices ==="
swapon --show
echo "=== Top 5 processes by swap ==="
smem -t -k -s swap -r | head -6
echo "=== PSI Memory ==="
cat /proc/pressure/memory
echo "=== Recent OOM events ==="
journalctl -k --grep="oom\|Out of memory" --since "24 hours ago" | tail -20
echo "=== High Major Faults ==="
ps -eo pid,comm,majflt --sort=-majflt | head -10
```

#### Runbook: реакция на Thrashing

1. **Триазна**: `vmstat 1` → `si`/`so` > 0 постоянный, `wa` > 20%, `free` близок к 0.
2. **Идентификация виновника**: `smem -t -k -s swap -r | head` → процесс с максимальным `SWAP`.
3. **Остановка процесса**: `kill -SIGTERM <pid>` → если не помогает, `kill -9`.
4. **Снижение swappiness**: `sudo sysctl -w vm.swappiness=0` (временно).
5. **Выгрузка swap**: `sudo swapoff -a && sudo swapon -a` (осторожно на production!).
6. **Постоянное устранение**: Увеличить RAM, настроить cgroup-лимиты, отключить THP.

#### Runbook: миграция swap на Zram

Если swap на медленном диске вызывает латентность:
```bash
# 1. Отключить старый swap
sudo swapoff -a

# 2. Включить zram (ядро >= 3.15, или модуль zram)
echo 1 | sudo tee /sys/block/zram0/reset
echo lz4 | sudo tee /sys/block/zram0/comp_algorithm
echo 2G | sudo tee /sys/block/zram0/disksize
sudo mkswap /dev/zram0
sudo swapon /dev/zram0

# 3. Обновить /etc/fstab: заменить /dev/sda2 на /dev/zram0
# 4. Мониторить: zramctl, /proc/swaps
```

### Мониторинг и алерты (Prometheus / Node Exporter)

Для node_exporter отслеживайте метрики swap и page faults:

```yaml
# Alert: High swap usage
- alert: HighSwapUsage
  expr: (node_memory_SwapTotal - node_memory_SwapFree) / node_memory_SwapTotal > 0.6
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High swap usage on {{ $labels.instance }}"
    description: "Swap usage is {{ $value | humanizePercentage }}."

# Alert: Active swapping detected
- alert: ActiveSwapThrashing
  expr: rate(node_vmstat_pswpin[5m]) + rate(node_vmstat_pswpout[5m]) > 50
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Active swapping on {{ $labels.instance }}"
    description: "Swap in/out rate is {{ $value }} pages/sec."

# Alert: Major page faults spike
- alert: HighMajorFaults
  expr: rate(node_vmstat_pgmajfault[5m]) > 1000
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "High major page faults on {{ $labels.instance }}"
    description: "Major faults rate is {{ $value }} faults/sec."

# Alert: Memory pressure via PSI
- alert: MemoryPressureFull
  expr: avg_over_time(node_pressure_memory_full_avg10[5m]) > 0.05
  for: 3m
  labels:
    severity: critical
  annotations:
    summary: "Memory pressure full on {{ $labels.instance }}"
    description: "PSI full avg10 is {{ $value | humanizePercentage }}."
```

### Анализ логов ядра

```bash
# OOM Killer события
journalctl -k --grep="oom\|Out of memory\|Killed process" --since "7 days ago"
# [12345.678] Out of memory: Killed process 1234 (java) total-vm:1048576kB

# События swap
journalctl -k --grep="swap\|page allocation" --since "24 hours ago"
# → ищите "page allocation failure" (значит min_free_kbytes недостаточно)

# Включение отладочного логирования swap (временно)
echo 1 | sudo tee /proc/sys/vm/swap_debug
# затем
dmesg | tail -50
```

## Дополнительная информация

### Изучение зон памяти и вотермарков

Если вы видите активность `direct reclaim` (процессы "зависают" на аллокациях), проверьте уровни свободной памяти:
```bash
cat /proc/zoneinfo | grep -E "Node|free|low|high"
# Если free < low, kswapd уже работает.
# Если free < min, система в режиме Direct Reclaim (критично).
```

### Взаимосвязь с другими механизмами

* **[Pressure Stall Information (PSI)](../kernel/psi.md)**: Основной источник метрик давления для современных систем.
* **[OOM Killer](../processes/oom_killer_mechanism.md)**: Финальный этап дефицита памяти.
* **[Оптимизация памяти](./performance_tuning.md)**: Настройка `vm.swappiness` и `vm.vfs_cache_pressure` для снижения активности свопинга.
* **[Slab Allocator](./slab_allocator.md)**: Утечки в кэшах ядра (SUnreclaim) часто являются причиной вытеснения приложений в swap.
* **[Управление Swap](./swap_management.md)**: Глубиная настройка swap, Zram/Zswap, production thresholds, аварийные сценарии и автоматизация.
* **[/proc/meminfo](../../Diagnostics/Memory/proc_meminfo.md)**: Детальная расшифровка метрик памяти, включая SwapTotal/SwapFree и Zswap.
* **[vmstat](../../Diagnostics/Memory/vmstat.md)**: Мониторинг активности swap (si/so) в реальном времени.

### Zram против Zswap: диагностическая матрица

| Критерий | Zram | Zswap |
| :--- | :--- | :--- |
| **Принцип** | swap полностью в RAM (сжатие) | Кэш в RAM перед физическим swap |
| **Дисковый swap** | Не требуется | Рекомендуется для сброса переполнения |
| **Производительность** | Очень высокая (нет дискового I/O) | Высокая (сжатие в RAM) |
| **Сценарий** | Бездисковые системы, IoT, слабые диски | Ноутбуки, серверы с быстрым SSD/NVMe |
* **Диагностика Zram**: `zramctl` → `DATA` близко к `COMPR` = низкая эффективность сжатия (нехватка CPU или несжимаемые данные).
* **Диагностика Zswap**: `cat /sys/kernel/debug/zswap/` → `stored_pages` растет, `pool_total_size` растет, `max_pool_percent` достигнут = переполнение, сброс на диск.

### Гибернация и Resume Offset

Если система зависает при выходе из гибернации:
```bash
# Проверка resume= в параметрах ядра
cat /proc/cmdline | grep resume
# → resume=UUID=<swap_uuid> (правильно) или отсутствует (ошибка)

# Для BTRFS swap-файла: проверка resume_offset
sudo btrfs filesystem show --kernel
btrfs-inspect-internal map-swapfile -r /swap/swapfile
# → physical offset должен совпадать с resume_offset в cmdline
```

### Overcommit и диагностика перерасхода

Режим `vm.overcommit_memory` влияет на поведение swap при выделении памяти:
```bash
cat /proc/sys/vm/overcommit_memory
# 0 = Heuristic (ядро само решает)
# 1 = Always (все запросы одобряются)
# 2 = Strict (строгий лимит)

# Проверка committed_as
grep Committed_AS /proc/meminfo
# Если Committed_AS близок к SwapTotal + RAM, система близка к лимиту overcommit
```
При `overcommit_memory=0` (по умолчанию) `malloc` может вернуть успех, но последующий доступ к памяти вызовет OOM Killer. Это одна из частых причин внезапных падений процессов без явного дефицита RAM.

### Логи ядра (dmesg и journald)

```bash
# Поиск OOM и page allocation failures
journalctl -k --grep="oom\|Out of memory\|page allocation\|swap" --since "7 days ago" | tail -30

# Типичные события:
# "page allocation failure: order:0, mode:0x..."
# → Нехватка PAGE_SIZE страниц, min_free_kbytes требует увеличения
# "Out of memory: Killed process 1234 (java) total-vm:1048576kB"
# → OOM Killer активировался
# "swap_io: swapfile read/write errors"
# → Проблемы с swap-устройством (отключен диск, ошибка файловой системы)
```

### Полезные утилиты

| Инструмент | Назначение | Ссылка |
| :--- | :--- | :--- |
| **`vmstat`** | Базовый мониторинг si/so, wa, свободной памяти в реальном времени. | [`vmstat.md`](../../Diagnostics/Memory/vmstat.md) |
| **`sar`** | Исторические данные по страницам (`-B`) и swap (`-W`). | [`sar.md`](../../Diagnostics/Performance/sar.md) |
| **`zramctl`** | Диагностика сжатой подкачки в RAM (DATA/COMPR). | — |
| **`smem`** | Точный подсчет PSS/Swap между процессами. | [`smem.md`](../../Diagnostics/Memory/smem.md) |
| **`oomctl`** | Управление и мониторинг `systemd-oomd`. | — |
| **`pidstat -r`** | Поиск процессов-виновников Major Faults. | [`pidstat.md`](../../Diagnostics/Processes/pidstat.md) |
| **`iostat`** | Корреляция swap-активности с дисковым I/O и задержками. | — |
| **`iotop`** | Идентификация процессов, генерирующих swap-операции. | — |
| **`perf`** | Профилирование Major Faults по функциям ядра/приложений. | [`perf.md`](../../Diagnostics/Performance/perf.md) |
| **`bpftrace`** | Измерение задержки Page Faults на уровне ядра (eBPF). | — |
| **`systemd-cgtop`** | Диагностика swap по cgroups v2. | — |
