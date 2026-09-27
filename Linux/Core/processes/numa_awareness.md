# NUMA-awareness для процессов

## Определения

**NUMA (Non-Uniform Memory Access)** — архитектура multiprocessing, при которой время доступа к памяти зависит от физического расположения процессора относительно памяти. В NUMA-системах каждый процессор (или группа процессоров) имеет локальную память; обращение к «чужой» памяти другого узла происходит через межузловую шину (Intel QPI/UPI, AMD Infinity Fabric) и занимает в 1.5–3 раза больше времени.

**NUMA-узел (NUMA node)** — логическая единица, объединяющая一组 CPU-ядер и их локальную память. В современных системах каждый физический процессор обычно формирует один NUMA-узел (1-socket = 1 node, 2-socket = 2 nodes). Чиплетные архитектуры (AMD EPYC) могут иметь 4–8 NUMA-узлов на один сокет.

**Local/Remote memory access** — обращение к локальной памяти (на том же NUMA-узле) выполняется быстрее, чем к удалённой (на другом узле). Типичные задержки:
- **Local:** 70–100 нс
- **Remote:** 130–200+ нс

**Interleaving** — распределение страниц памяти по NUMA-узлам по кругу (round-robin). Используется для балансировки памяти при отсутствии привязки к конкретному узлу.

**Node affinity (cpunodebind)** — привязка процесса к конкретному NUMA-узлу, гарантирующая что его потоки и память будут размещены на одном узле.

**First-Touch Policy** — политика по умолчанию в Linux: страница памяти размещается на NUMA-узле того процесса, который первым записал в неё данные.

## Основные концепции

### Типичные NUMA-топологии

| Архитектура | Количество NUMA-узлов | Примеры |
| :--- | :--- | :--- |
| **1-Socket Desktop/Server** | 1 | Intel Core i7/i9, AMD Ryzen |
| **2-Socket Server** | 2 | Intel Xeon Scalable, AMD EPYC (2P) |
| **4-Socket Server** | 4 | Intel Xeon MP, IBM POWER |
| **AMD EPYC (чиплеты)** | 4–8 на сокет | EPYC 7003/9004 (8 CCD = 8 NUMA-nodes) |
| **ARM Server** | 2–8 | Ampere Altra, AWS Graviton |

### Оптимизация locality

**Проблема:** Если процесс на NUMA-узле 0 обращается к памяти, выделенной на узле 1, каждая операция чтения/записи проходит через межузловую шину. При密集ном работе с памятью (БД, кэши, DPDK) это снижает производительность на 30–70%.

**Решения:**
1. **CPU pinning** — привязка процесса к ядрам одного NUMA-узла.
2. **Memory binding** — выделение памяти только на локальном узле.
3. **Interleaving** — для больших данных, где локальность не критична.
4. **AutoNUMA** — автоматическая миграция страниц ядром (ядро 3.8+).

### Влияние на производительность

| Сценарий | Local access | Remote access | Разница |
| :--- | :--- | :--- | :--- |
| **Latency (random read)** | 70 нс | 140 нс | ×2 |
| **Bandwidth** | 50 ГБ/с | 25 ГБ/с | ×2 |
| **LLC命中 (L3 cache)** | 10 нс | 30+ нс | ×3 |
| **БД (OLTP)** | 100K TPS | 60K TPS | ×1.7 |
| **DPDK packet processing** | 14.8 Mpps | 9.2 Mpps | ×1.6 |

### Автоматические политики ядра: AutoNUMA

**AutoNUMA (Automatic NUMA)** — механизм ядра Linux (активен с ядра 3.8, по умолчанию с 3.13+), который автоматически отслеживает паттерны доступа к памяти и мигрирует страницы ближе к процессу, который имиrequently пользуется.

**Параметры AutoNUMA:**

```bash
# Просмотр текущих настроек
cat /proc/sys/kernel/numa_balancing
# → 1 (включено)

# Включение/отключение
echo 1 | sudo tee /proc/sys/kernel/numa_balancing

# Период сканирования (мс)
cat /proc/sys/kernel/numa_balancing_scan_delay_ms
# → 1000

# Размер сканируемого окна (страниц)
cat /proc/sys/kernel/numa_balancing_scan_size_mb
# → 256
```

**Как работает:**
1. Ядро периодически сканирует страницы процесса.
2. Если процесс обращается к удалённой странице, ядро помечает её для миграции.
3. При следующем сканировании страница перемещается на локальный узел.
4. Миграция стоит ~10 мкс на страницу, поэтому для больших объемов памяти миграция может занимать секунды.

**Когда отключать:**
- В realtime-системах (миграция вызывает latency spikes).
- В DPDK/high-frequency trading (предсказуемость важнее автоматики).
- Когда память уже оптимально распределена (ручной тюнинг).

## Практические сценарии

### Просмотр NUMA-топологии

```bash
# Полная информация о системе
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 0 size: 32768 MB
# → node 0 free: 24567 MB
# → node 1 cpus: 8 9 10 11 12 13 14 15
# → node 1 size: 32768 MB
# → node 1 free: 28901 MB
# → node distances:
# → node   0   1
# →   0:  10  21
# →   1:  21  10

# Более компактный вид
lscpu | grep -i numa
# → NUMA node(s):        2
# → NUMA node0 CPU(s):   0-7
# → NUMA node1 CPU(s):   8-15

# Просмотр распределения памяти по узлам
numastat
# → node0: numa_hit 12345678 numa_miss 0 numa_foreign 0
# → node1: numa_hit 9876543 numa_miss 0 numa_foreign 0

# Детальная статистика по процессу
numastat -p $(pgrep postgres)
# → Per-node process memory usage (in MBs)
# → PID   Node 0  Node 1  Total
# → 1234   2048    512     2560
```

### Привязка процесса к NUMA-узлу (numactl)

```bash
# Запуск процесса на узле 0 (CPU + память)
numactl --cpunodebind=0 --membind=0 ./my_app

# Запуск на конкретных ядрах (внутри одного узла)
numactl --cpunodebind=0 --cpuexclude=2-3 ./my_app

# Interleaving памяти по обоим узлам (для больших БД)
numactl --interleave=all ./postgres

# Only bind memory, allow all CPUs
numactl --membind=0 ./my_app

# Only bind CPUs, allow memory from any node
numactl --cpunodebind=0 ./my_app
```

### Интерливинг памяти: когда и зачем

**Интерливинг (interleaving)** — политика распределения страниц по NUMA-узлам по кругу: страница 0 → узел 0, страница 1 → узел 1, страница 2 → узел 0, и т.д.

**Когда использовать:**
- Базы данных с большим рабочим набором (PostgreSQL, MySQL, Redis) — балансировка нагрузки на память.
- Кэши (memcached, встроенные кэши) — равномерное распределение traffic.
- Научные вычисления с большими массивами данных.

**Когда НЕ использовать:**
- Приложения с жесткой привязкой к CPU (DPDK, real-time).
- Малые рабочие наборы, помещающиеся в L3 cache одного узла.

```bash
# Интерливинг для PostgreSQL
numactl --interleave=all /usr/lib/postgresql/15/bin/postgres -D /var/lib/postgresql/15/main

# Интерливинг через systemd
# /etc/systemd/system/postgresql.service
[Service]
ExecStart=
ExecStart=/usr/bin/numactl --interleave=all /usr/lib/postgresql/15/bin/postgres -D /var/lib/postgresql/15/main
```

### Настройка в systemd

```ini
# /etc/systemd/system/myapp.service
[Service]
ExecStart=/usr/bin/my_app

# Привязка к NUMA-узлу 0
NUMAPolicy=bind
NUMAMemPolicy=0

# Или интерливинг по всем узлам
NUMAPolicy=interleave
NUMAMemPolicy=all
```

```bash
# Проверка применения
systemctl show myapp -p NUMAPolicy -p NUMAMemPolicy
# → NUMAPolicy=bind
# → NUMAMemPolicy=0

# Проверка через /proc
cat /proc/$(pgrep myapp)/numa_maps | head -5
# → default anon=1234 dirty=1234 N0=1200 N1=34
# → ↑ N0=1200 страниц на узле 0, N1=34 на узле 1
```

### Мониторинг NUMA

```bash
# Просмотр numa_maps для процесса
cat /proc/<PID>/numa_maps
# → default anon=262144 dirty=262144 N0=250000 N1=12144
# → | anon=262144: количество анонимных страниц
# → | dirty=262144: «грязные» страницы (изменённые)
# → | N0=250000: страницы на узле 0
# → | N1=12144: страницы на узле 1

# Иерархический numa_maps
cat /proc/<PID>/numa_maps | awk '{print $1, $2, $NF}'

# Просмотр распределения памяти в системе
cat /proc/meminfo | grep -i numa
# → NUMA hit: 12345678
# → NUMA miss: 0
# → NUMA foreign: 0
# → NUMA interleave: 0

# Мониторинг в реальном времени
watch -n1 'numastat -p $(pgrep my_app)'

# Статистика миграций страниц
grep -i migrate /proc/vmstat
# → numa_hit 12345678
# → numa_miss 0
# → numa_foreign 0
# → numa_pte_updates 1234
# → numa_hint_faults 5678
# → numa_hint_faults_local 4567  ← 80% локальных миграций
```

### Диагностика проблем NUMA

```bash
# 1. Поиск процесса с «размазанной» памятью
for pid in $(pgrep -f postgres); do
    echo "PID $pid:"
    cat /proc/$pid/numa_maps | grep -E "^default" | awk '{print $NF}'
done

# 2. Поиск remote access через perf
sudo perf stat -e node-loads,node-load-misses,node-stores,node-store-misses -p <PID> sleep 5
# → 12345678  node-loads
# →  3456789  node-load-misses  (28% remote access — плохо!)

# 3. Проверка distance таблицы
numactl --hardware | grep -A 10 "node distances"

# 4. Анализ traffic между узлами
sudo perf record -e node:* -a sleep 5
sudo perf report

# 5. Проверка AutoNUMA
cat /proc/sys/kernel/numa_balancing
# → 1 = включено
# → 0 = отключено

# 6. Поиск процессов с высоким remote access
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    remote=$(grep -o 'N[0-9]*=[0-9]*' /proc/$pid/numa_maps 2>/dev/null | \
        awk -F= 'NR>1 {sum += $2} END {print sum}')
    if [ -n "$remote" ] && [ "$remote" -gt 10000 ]; then
        echo "PID $pid: $remote remote pages"
    fi
done 2>/dev/null
```

### PostgreSQL: оптимальная NUMA-конфигурация

```bash
# Вариант 1: Интерливинг (рекомендуется для больших БД)
numactl --interleave=all \
    /usr/lib/postgresql/15/bin/postgres \
    -D /var/lib/postgresql/15/main

# Вариант 2: Привязка к одному узлу (для маленьких БД)
numactl --cpunodebind=0 --membind=0 \
    /usr/lib/postgresql/15/bin/postgres \
    -D /var/lib/postgresql/15/main

# Вариант 3: Частичный интерливинг (средние БД)
numactl --membind=0-1 --cpunodebind=0-1 \
    /usr/lib/postgresql/15/bin/postgres \
    -D /var/lib/postgresql/15/main
```

**Результаты бенчмарков (pgbench):**

| Политика | TPS (2-socket) | Latency |
| :--- | :--- | :--- |
| Default (auto) | 85K | 12 мс |
| Interleave=all | 102K | 10 мс |
| Bind to node 0 | 78K | 13 мс |
| Bind + membind | 75K | 14 мс |

### Redis: NUMA-оптимизация

```bash
# Запуск Redis на одном NUMA-узле
numactl --cpunodebind=0 --membind=0 redis-server /etc/redis/redis.conf

# Или интерливинг для кэша
numactl --interleave=all redis-server /etc/redis/redis.conf
```

### DPDK: строгая привязка

```bash
# DPDK требует жесткой привязки к CPU и памяти
numactl --cpunodebind=0 --membind=0 \
    ./dpdk-app -l 0-3 -n 4 -- \
    --prefix=/var/run/dpdk \
    --proc-type=primary
```

### Linux kernel: tune for NUMA

```bash
# Просмотр парамеров
sysctl vm.zone_reclaim_mode
# → 0 = выключено (память берётся с любого узла)
# → 1 =回收 память с локального узла
# → 2 = перекомпакция +回收
# → 4 = перезапись dirty pages

# Для DPDK/real-time: отключить zone reclaim
sudo sysctl -w vm.zone_reclaim_mode=0

# Настройка AutoNUMA
sudo sysctl -w kernel.numa_balancing=1

# Минимальный scan delay
sudo sysctl -w kernel.numa_balancing_scan_delay_ms=1000
```

## Дополнительная информация

### Матрица решений: какую NUMA-политику выбрать

| Сценарий | Рекомендация | Причина |
| :--- | :--- | :--- |
| **PostgreSQL / MySQL (OLTP)** | `numactl --interleave=all` | Балансировка памяти; рабочий набор больше L3 |
| **Redis (кэш)** | `numactl --cpunodebind=0 --membind=0` | Малый рабочий набор; максимальная locality |
| **DPDK / NFV** | `numactl --cpunodebind=0 --membind=0` | Строгая привязка; предсказуемость |
| **Memcached** | `numactl --interleave=all` | Балансировка traffic по узлам |
| **Video encoding** | Default или `--cpunodebind=0` | CPU-bound; память не критична |
| **Scientific computing** | `--interleave=all` (если массив > L3) | Балансировка bandwidth |
| **Real-time audio** | `--cpunodebind=0 --membind=0` + isolcpus | Минимальный jitter |
| **Virtual machines** | Оставить AutoNUMA включённым | Гипервизор управляет распределением |

### Общие ошибки

1. **Запуск БД без привязки:** PostgreSQL по умолчанию распределяет память по «first-touch», что часто приводит к неравномерному распределению. Решение: `--interleave=all`.

2. **Привязка к одному узлу на 2-socket системе:** Один узел получает 50% памяти и CPU. Решение: использовать `--interleave=all` или запускать по экземпляру на каждый узел.

3. **Забыть про membind:** `--cpunodebind` привязывает CPU, но не память. Страницы могут быть выделены на другом узле. Решение: использовать `--cpunodebind + --membind` вместе.

4. **Отключение AutoNUMA без компенсации:** После отключения `numa_balancing` необходимо вручную привязывать процессы, иначе память останется на «wrong» узле.

### Связанные темы

- [Привязка к процессору (CPU Pinning)](../cpu_pinning.md) — детали `taskset`, `sched_setaffinity`, `cpuset`.
- [Контрольные группы (cgroups)](../cgroups.md) — `cpuset` в cgroups для изоляции NUMA.
- [Планирование процессов](./scheduling.md) — взаимодействие NUMA с планировщиком.
- [I/O Multiplexing: select, poll, epoll](./epoll_io_multiplexing.md) — epoll + NUMA-awareness.
- [DPDK и io_uring vs AF_XDP](../../Networking/Concepts/dpdk/dpdk_io_uring_vs_afxdp.md) — NUMA в контексте высокопроизводительных сетевых технологий.

### См. также

- [Изоляция CPU](../kernel/cpu_isolation.md) — `isolcpus`, `nohz_full`, `rcu_nocbs` для строгой изоляции.
- [PSI — статистика давления на ресурсы](../kernel/psi.md) — мониторинг давления на память.
