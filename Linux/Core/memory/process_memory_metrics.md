# Метрики потребления памяти процесса

## Определения

* **VSS (Virtual Set Size / VSZ)**: Общий объём виртуального адресного пространства, который процесс зарезервировал в ядре. Включает в себя код, данные, стек, кучу, разделяемые библиотеки и память, выделенную через `malloc`, но ещё не использованную физически.
* **RSS (Resident Set Size)**: Объём физической памяти (RAM), которую процесс фактически занимает в данный момент. Делится на анонимную (Anonymous), файловую (File-backed) и разделяемую (Shared) части.
* **PSS (Proportional Set Size)**: Показатель, учитывающий разделяемую память (Shared Memory) пропорционально количеству процессов, которые её используют. Считается наиболее точным индикатором вклада процесса в общую нагрузку на RAM.
* **USS (Unique Set Size)**: Объём физической памяти, который принадлежит исключительно данному процессу (Private). Это объём, который будет освобожден немедленно при завершении процесса.
* **WSS (Working Set Size)**: Рабочий набор — объём памяти, который был необходим процессу за последние интервалы времени для выполнения задач без задержек. Это динамическая метрика, определяющая порог "тормозов" системы (Thrashing).
* **SHR (Shared Memory)**: Объём резидентной памяти, которая может быть потенциально разделена с другими процессами (библиотеки, `tmpfs`, сегменты System V IPC).
* **Swap (Подкачка)**: Объём данных процесса, которые были выгружены из RAM на диск.

* **VmHWM (High Water Mark)**: Пиковое значение RSS за всё время жизни процесса. Поле в `/proc/<pid>/status`. Показывает максимальную нагрузку на RAM, которую процесс когда-либо создавал.
* **VmSwap**: Объём данных процесса, выгруженных в swap (физический или zswap/zram). Вычисляется как `VmSwap` в `/proc/<pid>/status`.
* **VmPTE**: Объём памяти, занятый таблицами страниц (Page Tables) для этого процесса. На системах с тысячами процессов может достигать гигабайт.
* **VmRSS**: Текущее значение RSS. Поле в `/proc/<pid>/status`.
* **VmPeak**: Пиковое значение VSS за всё время жизни процесса.

## Основные концепции

### Детализация RSS: Anonymous, File-backed и Shared

RSS не является монолитной величиной. Для точной диагностики его следует разделять на компоненты, доступные через `/proc/<pid>/smaps_rollup` или `/proc/<pid>/smaps`:

1. **Private Anonymous (Private_Anon)**: Память кучи (heap), стека (stack), динамически выделенная через `malloc`/`brk`/`mmap` (MAP_PRIVATE). Не связана с файлами на диске. Основной индикатор утечек памяти.
2. **Private File (Private_File)**: Фрагменты исполняемого файла, библиотек и отображенных файлов (`mmap` MAP_PRIVATE), которые были изменены (Copy-on-Write). Ядро не может освободить эту память без сброса изменений.
3. **Shared Anonymous (Shared_Anon)**: Разделяемая анонимная память (System V IPC, POSIX shared memory, анонимные `mmap` с `MAP_SHARED`).
4. **Shared File (Shared_File)**: Разделяемые файловые отображения (общие библиотеки, исполняемые файлы, `mmap` MAP_SHARED). Ядро может отобрать эти страницы, если другие процессы также их используют.

**Ключевой инсайт для SRE:** Если `Private_Anon` растёт со временем — это утечка памяти в приложении. Если растёт `Shared_File` — это нормальная работа кэша ядра или совместно используемых библиотек.

### Влияние Copy-on-Write (CoW) на RSS

После `fork()` родитель и потомок используют одни и те же физические кадры (Copy-on-Write). RSS в `top` покажет память дважды, но реальное потребление RAM не удвоилось. PSS/USS корректно учитывают этот эффект.

**Практический эффект:**
```bash
# Процесс-родитель fork() 100 рабочих процессов
# RSS родителя: 500 МБ
# RSS каждого потомка: 500 МБ
# Сумма RSS: 50.5 ГБ (в топ)
# Реальная нагрузка на RAM: ~500 МБ + уникальные страницы потомков
# PSS даст реальную картину.
```

### Разделяемая память (System V IPC и POSIX)

Разделяемые сегменты IPC часто становятся "невидимыми" в стандартных инструментах:
- **System V (shmget/shmat)**: Появляется в `pmap` как `[sysv]` или анонимный регион. Входит в RSS и Shared RSS.
- **POSIX (shm_open/mmap)**: Появляется как анонимный `mmap` с флагом `s` (shared).
- **tmpfs (/dev/shm)**: Файловая система в RAM. Содержимое учитывается в RSS как File-backed Shared.

**Диагностика:**
```bash
# Поиск процессов, использующих /dev/shm
sudo lsof /dev/shm | head
```

### Взаимодействие NUMA и метрик процесса

На мультисокетных системах ядро учитывает NUMA-узлы при расчете RSS:
- `smem` поддерживает флаг `--numa` для отображения распределения памяти по узлам.
- `numastat` показывает, сколько памяти процесс потребляет локально (`numa_foreign`) и на чужом узле (`numa_interleave`).

```bash
# Распределение памяти процесса по NUMA-узлам
numastat -p <PID>
# →   PID      Node 0     Node 1     Total
# →   1234   512.34 MB   128.00 MB   640.34 MB
```

Рост `numa_foreign` указывает на деградацию производительности из-за доступа к удаленному узлу через QPI/UPI.

### Page Tables и накладные расходы

Таблицы страниц (Page Tables) для каждого процесса занимают место в RAM и не выгружаются в swap. Они учитываются в `/proc/meminfo` как `PageTables`, а для конкретного процесса — как `VmPTE` в `/proc/<pid>/status`.

На системах с 10,000+ процессов или процессами с огромным адресным пространством (JVM с `-Xmx64g`) Page Tables могут занимать гигабайты. Переход на HugePages снижает этот overhead.

```bash
# Проверка общего объема таблиц страниц
grep PageTables /proc/meminfo

# Проверка для конкретного процесса
grep VmPTE /proc/<PID>/status
```

### Влияние Memory Overcommit на VSS

Режим `vm.overcommit_memory` определяет, будет ли `malloc()` возвращать успех, когда запрашиваемый объём превышает доступный:

| Режим | Поведение | Риск |
| :--- | :--- | :--- |
| **0** (Heuristic) | Ядро отклоняет явно невозможные запросы по эвристике | При ложном успехе malloc → OOM при первом доступе |
| **1** (Always) | Все malloc() возвращают успех | Гарантированный OOM при нагрузке |
| **2** (Strict) | Ограничение: `SwapTotal + RAM * overcommit_ratio / 100` | Предсказуемое поведение, требует настройки ratio |

`Committed_AS` в `/proc/meminfo` показывает общий объём памяти, который процессы "пообещали" использовать. Если `Committed_AS > SwapTotal + MemTotal`, система работает на грани OOM.

```bash
# Проверка overcommit и Committed_AS
cat /proc/sys/vm/overcommit_memory
grep -E 'Committed_AS|CommitLimit' /proc/meminfo
```

### Взаимосвязь метрик с OOM Score

Ядро Linux выбирает процесс для завершения (OOM Kill) на основе `oom_score`, который рассчитывается из:
1. **RSS + Swap** процесса (базовый вес).
2. **oom_score_adj** (от -1000 до +1000) из `/proc/<PID>/oom_score_adj`.
3. Принадлежности к cgroup с превышенным лимитом.

**Ключевое правило:** Процесс с огромным VSS, но маленьким RSS, имеет низкий `oom_score`. Процесс с умеренным RSS, но запущенный в cgroup с жёстким `memory.max`, будет убит первым, даже если в системе есть "более тяжелые" процессы.

```bash
# Текущий oom_score и oom_score_adj
cat /proc/<PID>/oom_score
cat /proc/<PID>/oom_score_adj
```

## Практические сценарии

### Анализ с помощью стандартных утилит

```bash
# Просмотр VSS (VSZ) и RSS для конкретного процесса
ps -o pid,vsz,rss,comm -p <PID>
# →   PID    VSZ   RSS COMMAND
# →  1234 150240  4096 nginx
```

### Точный анализ PSS и USS через smem и ps_mem

Утилиты `smem` и `ps_mem` рассчитывают PSS и USS, суммируя данные из `/proc/<pid>/smaps`.

```bash
# Сортировка процессов по потреблению PSS (в КБ)
smem -tk -s pss -r | head
# →   PID User     Command                         Swap      USS      PSS      RSS
# →  1234 root     nginx                              0     2.1M     3.5M     8.2M

# Удобный отчет по суммарному потреблению группами процессов
sudo ps_mem
# →  Private  +   Shared  =  RAM used	Program
# →  3.1 MiB  +   1.2 MiB =  4.3 MiB	nginx (4)
```

### Детальная разбивка через интерфейс /proc

1.  **`/proc/<pid>/smaps_rollup`**: Рекомендуемый способ в 2024-2025 гг. Агрегирует данные по всей карте памяти процесса без накладных расходов на парсинг тысяч строк `smaps`.
    ```bash
    cat /proc/<PID>/smaps_rollup
    # → Rss:                8520 kB
    # → Pss:                5120 kB
    # → Pss_Anon:           2048 kB
    # → Pss_File:           3072 kB
    # → Private_Dirty:      2000 kB (почти всегда равно USS)
    ```

2.  **`/proc/<pid>/status`**: Быстрый обзор лимитов и текущего состояния.
    ```bash
    grep -E "VmRSS|VmHWM|VmSwap|VmPeak" /proc/<PID>/status
    # → VmPeak:          150240 kB (пиковый VSS)
    # → VmHWM:             8192 kB (High Water Mark — пиковый RSS)
    # → VmRSS:             4096 kB (текущий RSS)
    # → VmSwap:             512 kB (объем в свопе)
    ```

3.  **`/proc/<pid>/statm`**: Формат для быстрой машинной обработки (значения в страницах памяти).
    * Поля: `size` (VSS), `resident` (RSS), `shared` (Shared), `text` (Code), `lib`, `data`, `dt`.

### Таймсериес-мониторинг через pidstat

`pidstat` позволяет отслеживать потребление памяти процессом в реальном времени, что критично для выявления утечек до фазы OOM:

```bash
# Мониторинг RSS, VSZ и Swap конкретного PID каждые 5 секунд
pidstat -r -p <PID> 5
# →   UID       PID    VSZ   RSS   %MEM   Command
# →  12:00:01  root   256M  128M   1.2    java
# →  12:00:06  root   270M  142M   1.3    java  ← рост RSS = утечка
# →  12:00:11  root   285M  158M   1.5    java

# Мониторинг всех процессов, сортировка по RSS
pidstat -r -h -p ALL 5 | head -20
```

Для длительного мониторинга (сутки) перенаправьте вывод в CSV:
```bash
pidstat -r -p <PID> 60 > memory_log_$(date +%Y%m%d).csv
```

### Глубокий анализ сегментов через pmap

`pmap` расширенным режимом (`-X`) извлекает практически все метрики из `smaps`. Это наиболее точный способ анализа в современных системах:

```bash
# Максимально информативный вывод с PSS и Swap
sudo pmap -X <PID> | head -30
# → Address           Kbytes     RSS   PSS   Shared_Clean  Shared_Dirty  Private_Clean  Private_Dirty  Swap  Mode  Mapping
# → 0000564f89a00000    1024     512   256    256           0             256            0            0  rw--  [heap]
# → 00007f3e8b000000   81920    4096  1024   3072          0             1024           0            0  r-x-- libc-2.31.so

# Поиск крупнейших анонимных сегментов
sudo pmap -x <PID> | grep anon | sort -k2 -nr | head
```

### Анализ NUMA-привязки процесса

На мультисокетных системах необходимо учитывать, что RSS может распределяться между узлами неравномерно:

```bash
# Топология NUMA
numactl --hardware

# Распределение памяти конкретного PID по узлам
numastat -p <PID>
# →   PID      Node 0     Node 1     Total
# →   1234   512.34 MB   128.00 MB   640.34 MB

# Если Node 1 значительно больше, но процесс работает на CPU Node 0 —
# это источник задержек (remote memory access через QPI/UPI).
```

### Тестирование лимитов памяти через systemd-run

Для быстрого проверки поведения приложения при нехватке RAM без изменения unit-файлов:

```bash
# Запуск команды с лимитом 512 МБ и memory.high=400M
sudo systemd-run --scope -p MemoryMax=512M -p MemoryHigh=400M --unit=test-mem-limit /usr/bin/my_app --arg

# Мониторинг давления памяти в реальном времени
sudo systemd-cgtop -m memory

# Очистка после теста
sudo systemctl stop test-mem-limit
```

### Метрики Prometheus (Node Exporter)

Для построения дашбордов и алертов используются метрики `node_exporter`. В контексте процесса важны:

```yaml
# Пример PromQL запросов для SRE-дашборда:

# Топ-5 процессов по RSS (требует node_exporter + process_exporter)
topk(5, process_resident_memory_bytes{job="node"})

# Суммарный swap процессов
sum(process_virtual_memory_swap_bytes{job="node"})

# OOM Score кандидатов (требует custom exporter)
topk(5, node_process_oom_score{job="node"})
```

### Runbook: Диагностика утечки памяти

**Симптом:** `MemAvailable` падает, `top`/`ps` показывает рост RSS у конкретного процесса.

```bash
# 1. Быстрый снимок лидеров
ps aux --sort=-%mem | head -10

# 2. Проверка динамики за 5 минут
pidstat -r -p <PID> 300 1 | tail -10

# 3. Детализация: PSS vs RSS
sudo smem -t -k -s pss -r | grep <process_name>

# 4. Детализация: какой именно сегмент растет
sudo pmap -X <PID> | grep -E 'heap|anon|stack|private' | sort -k3 -nr | head

# 5. Если Private_Anon растет — это heap leak
#    Если Private_File растет — это mmap/mapped file leak
#    Если Shared растет — проверьте tmpfs, /dev/shm, IPC

# 6. Аварийное действие:
#    - Установить cgroup-лимит через systemd-run
#    - Или перезапустить процесс с core dump для анализа
sudo systemctl restart <service>
```

### Runbook: Анализ памяти контейнера

В контейнерах RSS процесса скрывается за cgroup-лимитами. Стандартный `top` внутри контейнера показывает только видимость cgroup, а не реальную нагрузку на хост:

```bash
# Внутри контейнера (cgroup v2)
cat /sys/fs/cgroup/memory.stat
# → anon          524288
# → file          131072
# → kernel_stack  4096
# → slab          65536
# → workingset_refault  1024

# На хосте (анализ конкретного контейнера)
CONTAINER_ID=$(docker inspect --format '{{.Id}}' <container_name>)
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.stat

# Сравнение cgroup v1 vs v2:
# v1: cat memory.usage_in_bytes, cat memory.stat
# v2: cat memory.current, cat memory.stat
# v2 дополнительно: cat memory.events (low, high, max, oom)
```

### Дифференциальная диагностика аномалий

| Симптом | Возможная причина | Действие SRE |
| :--- | :--- | :--- |
| **VSS огромный, RSS небольшой** | Приложение mmap'ит большие файлы или GC резервирует адресное пространство | Нормально. Контролируйте `Private_Anon` и `VmHWM`. |
| **RSS растет, PSS стабилен** | Рост Shared File (кэш ядра) или CoW после fork | Проверьте `Shared_File` в `smaps_rollup`. Если `Private_Anon` не растет — утечки нет. |
| **RSS падает после `drop_caches`** | File-backed RSS был очищен ядром | Нормально. После `echo 3 > /proc/sys/vm/drop_caches` File RSS исчезает, но Private Anon остается. |
| **USS растет, PSS не растет** | Рост уникальной памяти (heap/stack leak) | Подает сигнал к перезапуску/расследованию. |
| **VmSwap растет, RSS стабилен** | Процесс не трогает страницы, они выгружаются в swap | Проверьте `vm.swappiness`. Для СУБД установите `swappiness=1`. |
| **Numastat: high numa_foreign** | Процесс на Node 0, память выделена на Node 1 | Используйте `numactl --cpunodebind=0 --membind=0` или включите `kernel.numa_balancing=1`. |
| **RSS > MemTotal (в топе)** | Оверкаунтинг разделяемой памяти | Используйте `smem` или `PSS` для реальной оценки. |

### Практический чек-лист SRE при эскалации по памяти

При получении алерта "High Memory Usage" выполните последовательность:

1. **Общая картина:**
   ```bash
   free -h && echo "---" && grep -E 'Committed_AS|CommitLimit' /proc/meminfo
   ```

2. **Топ процессов по USS (реальная нагрузка):**
   ```bash
   sudo smem -t -k -s uss -r | head -15
   ```

3. **Топ процессов по RSS (стандартный мониторинг):**
   ```bash
   ps aux --sort=-rss | head -10
   ```

4. **Проверка cgroup-лимитов (если контейнеры):**
   ```bash
   systemd-cgtop -m memory
   # или
   docker stats --no-stream
   ```

5. **Проверка slab и ядерной памяти:**
   ```bash
   grep -E 'Slab|SReclaimable|SUnreclaim|KernelStack' /proc/meminfo
   sudo slabtop -o -s c | head -10
   ```

6. **Проверка PSI (давление на память):**
   ```bash
   cat /proc/pressure/memory
   # → some avg10=0.50 avg60=0.20 avg300=0.05 total=12345
   # avg10 > 0.1 = высокое давление
   ```

7. **Проверка NUMA дисбаланса (если applicable):**
   ```bash
   numastat
   ```

### Связь с другими механизмами

- **[Виртуальная и физическая память](./virtual_vs_physical_memory.md)** — как виртуальные адреса превращаются в физические кадры и как это влияет на RSS.
- **[Механизм OOM Killer](../processes/oom_killer_mechanism.md)** — как `oom_score` учитывает RSS, USS и cgroup-лимиты.
- **[Кэширование и освобождение памяти](./caching_and_reclaiming.md)** — как ядро отбирает File-backed RSS у процессов.
- **[Slab Allocator](./slab_allocator.md)** — память ядра, не учитываемая в RSS процессов, но влияющая на `MemAvailable`.
- **[Оптимизация памяти](./performance_tuning.md)** — тюнинг overcommit, NUMA, THP, который меняет поведение метрик.
- **[Диагностика Swap и Page Faults](./swap_diagnostics.md)** — почему процесс находится в swap.
- **[smem](../../Diagnostics/Memory/smem.md)** — глубокий разбор утилиты для точного расчета PSS/USS.
- **[pmap](../../Diagnostics/Memory/pmap.md)** — детальный анализ сегментов виртуальной памяти.
- **[Фактическое потребление vs Reporting](./memory_reporting_vs_reality.md)** — разница между free, top, smem; почему free всегда показывает мало.
- **[/proc/meminfo — статистика памяти ядра](../../Diagnostics/Memory/proc_meminfo.md)** — расшифровка глобальных метрик, влияющих на процессы.
