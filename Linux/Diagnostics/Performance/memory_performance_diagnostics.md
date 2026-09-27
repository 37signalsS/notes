# Диагностика производительности памяти

## Определения

**Memory Performance Diagnostics** — процесс анализа потребления RAM, выявления утечек, оценки давления (memory pressure) и влияния подкачки (swap) на производительность. Ключевые инструменты: `free`, `vmstat`, `smem`, `slabtop`, PSI, `/proc/meminfo`.

**Available Memory** — реальный объём памяти, доступный для запуска новых процессов без свопинга. Формула: `MemAvailable = MemFree + Buffers + Cached - LowWaterMark`. **Именно `MemAvailable`, а не `MemFree`** — ключевая метрика. `MemFree` почти всегда мал (ядро кэширует активно).

**OOM Killer** — механизм ядра, завершающий процессы при критической нехватке памяти. Срабатывает когда `Committed_AS > CommitLimit` (при `overcommit_memory=2`) или при нехватке страниц для аллокации. Жертва выбирается по `oom_score` (наивысший = первый убивает).

**Transparent Huge Pages (THP)** — автоматическое использование страниц 2MB/1GB вместо 4KB. **Проблема:** `khugepaged` (фоновый поток) может вызывать latency spikes при компактификации. Database серверы (PostgreSQL, MongoDB, Redis) рекомендуют отключение THP или `madvise`.

**Slab Allocator** — кэш ядра для объектов ядра (dentry, inode, inode_cache, buffer_head). Высокий `SReclaimable` в `/proc/meminfo` — нормальное поведение (кэш используется). Проблема только если `SUnreclaim` растёт без причины (утечка в модулях ядра).

**Swap Thrashing** — ситуация, когда система активно перемещает страницы между RAM и swap, создавая дополнительную нагрузку на диск. Индикатор: `vmstat` → `si/so > 0`. Сильный swap thrashing = приложение фактически не работает.

---

## Основные концепции

### Быстрая оценка состояния памяти

```bash
# Шаг 1: Доступная память
free -m

# Шаг 2: Активный swap?
vmstat 1 3
# → si/so столбцы: > 0 = swap активен

# Шаг 3: Давление памяти
cat /proc/pressure/memory

# Шаг 4: Кто потребляет?
ps aux --sort=-%mem | head -10

# Шаг 5: Структура памяти
grep -E "MemTotal|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|Dirty|Slab|SReclaimable|SUnreclaim" /proc/meminfo
```

### Интерпретация free -m

```
$ free -m
              total        used        free      shared  buff/cache   available
Mem:          15892        8456         312         245        7124        6832
Swap:          2048         512        1536
```

| Метрика | Значение | Интерпретация |
|:---|:---|:---|
| `total` | 15892 MB | Общий объём RAM |
| `used` | 8456 MB | Использовано приложениями |
| `free` | 312 MB | Полностью свободная память (почти всегда мало!) |
| `buff/cache` | 7124 MB | Кэш ядра (файловая система, slab) |
| **`available`** | **6832 MB** | **Реально доступная память** (ключевая метрика!) |
| `Swap used` | 512 MB | Активный swap (если > 0 — расследовать) |

**Правило:** `available / total > 30%` — норма. `available < 20% от total` — тревога.

### Интерпретация /proc/meminfo

```bash
$ grep -E "MemTotal|MemAvailable|Dirty|Writeback|Slab|SReclaimable|SUnreclaim|SwapTotal|SwapFree|Committed_AS|AnonPages|Mapped|Shmem|HugePages" /proc/meminfo
```

| Поле | Что означает | Норма | Тревога |
|:---|:---|:---|:---|
| `MemAvailable` | Доступная память | > 30% от MemTotal | < 20% |
| `Dirty` | Страницы, ожидающие записи на диск | < 5% от RAM | > 10% |
| `Writeback` | Страницы в процессе записи | 0 | > 0持续но |
| `Slab` | Кэш объектов ядра | Стабильно | Растёт без причины |
| `SUnreclaim` | Невосстанавливаемый slab | < 20% от Slab | Растёт (утечка) |
| `SwapFree` | Свободный swap | > 50% от SwapTotal | < 20% |
| `Committed_AS` | Зарезервированная память | < CommitLimit | > CommitLimit |
| `AnonPages` | Страницы приложений (не кэш) | Стабильно | Растёт (утечка) |
| `HugePages_Total` | Зарезервированные HP | Как настроено | Неиспользуемые |

### Мониторинг swap

```bash
# Мгновенный снимок
vmstat 1 5
# → si: swap-in (страницы возвращаются из swap в RAM)
# → so: swap-out (страницы уходят из RAM в swap)
# → si/so > 0持续но = проблема

# Исторические данные
sar -W 1 10
# → pswpin/s, pswpout/s

# Per-process swap
for pid in $(pgrep java); do
    echo "PID $pid: $(awk '/VmSwap/{print $2}' /proc/$pid/status) kB"
done
```

| si/so | Оценка | Действие |
|:---|:---|:---|
| si=0, so=0 | Норма | — |
| si>0, so=0 | Возврат из swap | Мониторинг (может быть нормально) |
| si=0, so>0 | Вытеснение в swap | Расследовать: какая память вытесняется |
| si>0, so>0 | Thrashing! | Критично: приложение не работает нормально |

### OOM Killer: диагностика и управление

```bash
# Поиск OOM-событий
dmesg | grep -i "oom-killer"
# или
journalctl -k | grep -i "oom"

# Текущий oom_score для процесса
cat /proc/<PID>/oom_score

# Настройка oom_score_adj (защита критичных процессов)
echo -1000 > /proc/<PID>/oom_score_adj   # Защитить (никогда не убивать)
echo 1000 > /proc/<PID>/oom_score_adj    # Приоритет убийства

# В systemd юните
[Service]
OOMScoreAdjust=-500
```

| oom_score_adj | Поведение |
|:---|:---|
| -1000 | Полная защита (никогда не убивать) |
| -500 | Защищён (убивать в последнюю очередь) |
| 0 | Нейтрально (по умолчанию) |
| 500-1000 | Приоритет убийства |

### Transparent Huge Pages: влияние на производительность

```bash
# Текущее состояние
cat /sys/kernel/mm/transparent_hugepage/enabled
# → [always] madvise never

# Проверка активности khugepaged
grep -i "compact" /proc/vmstat
# → compact_success, compact_fail, compact_daemon_migrate

# Отключение
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag

# Постоянное отключение (GRUB)
# Добавить: transparent_hugepage=never
```

**Когда отключать THP:**
- Database серверы (PostgreSQL, MySQL, MongoDB, Redis)
- Приложения с высоким frequency alloc/dealloc
- Системы с Limited RAM (< 8GB)
- Когда есть latency spikes без видимой причины

**Когда THP полезен:**
- Large Java/Go приложения (сделать `madvise` вместо `always`)
- Виртуализация (KVM guest)
- High-memory серверы (≥64GB)

### Slab allocator: когда беспокоиться

```bash
# Текущее состояние
slabtop -s c | head -20

# Или через /proc/slabinfo
cat /proc/slabinfo | awk 'NR>2{print $1, $3*$4}' | sort -k2 -rn | head -10
```

| Объект | Норма | Проблема |
|:---|:---|:---|
| `dentry` | 100K–1M | Растёт без причины (FS cache leak) |
| `inode_cache` | 50K–500K | Аналогично dentry |
| `ext4_inode_cache` | 10K–100K | Файловая система с많ими файлами |
| `kmalloc-*` | Стабильно | Растёт = утечка в модулях ядра |
| `SUnreclaim` | < 20% от Slab | Растёт = ядро не освобождает память |

---

## Практические сценарии

### Сценарий 1: «Памяти мало, но приложение работает»

**Симптом:** `free -m` показывает мало `free`, но `available` достаточный.

```bash
$ free -m
              total    used    free   buff/cache   available
Mem:          15892    8456     312        7124        6832

# Вердикт: available = 6832 MB (43% от total) — НОРМА
# free = 312 MB — это НОРМАЛЬНО (ядро использует кэш)
```

**Действие:** Не требуется. `free` мало — это нормально. Кэш (`buff/cache`) автоматически освобождается при необходимости.

### Сценарий 2: Uтечка памяти в приложении

**Симптом:** RSS процесса растёт со временем, OOM killer срабатывает.

```bash
# Мониторинг RSS
while true; do
    echo "$(date): $(awk '/VmRSS/{print $2}' /proc/<PID>/status) kB"
    sleep 60
done

# Топ потребителей
ps aux --sort=-%mem | head -10

# smem для корректного учёта PSS (Proportional Set Size)
smem -tk -s pss | head -15

# Проверка AnonPages (память приложений)
grep AnonPages /proc/meminfo
# → AnonPages: 12500000 kB  (12GB — растёт?)
```

**Решение:**
1. Профилирование памяти приложения (jemalloc, heaptrack, valgrind)
2. Временное: restart приложения по cron (костыль)
3. Постоянное: исправление утечки + `memory.max` в cgroup

### Сценарий 3: Swap storm

**Симптом:** Система зависает, `vmstat` показывает огромные `si/so`.

```bash
$ vmstat 1 5
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
 8  2  524288  10240  51200 204800 8500 12000  200  800 15000 8500 35 15 10 35  5
```

**Алгоритм:**
```bash
# 1. Кто в swap?
for pid in $(ls /proc/ | grep -E '^[0-9]+$'); do
    swap=$(awk '/VmSwap/{print $2}' /proc/$pid/status 2>/dev/null)
    if [ "$swap" -gt 10000 ] 2>/dev/null; then
        name=$(cat /proc/$pid/comm 2>/dev/null)
        echo "${swap} kB — PID $pid ($name)"
    fi
done | sort -rn | head -10

# 2. swappiness
cat /proc/sys/vm/swappiness
# → 60 (слишком агрессивно для сервера)

# 3. Давление
cat /proc/pressure/memory
# → some avg10=85.20  full avg10=62.30
```

**Решение:**
1. `sysctl vm.swappiness=10` (снизить агрессивность)
2. `swapoff -a && swapon -a` (очистить swap, если RAM достаточно)
3. Долгосрочное: увеличить RAM или оптимизировать приложение

### Сценарий 4: Memory overcommit

**Симптом:** Приложение не может выделить память, хотя `free` показывает свободную.

```bash
# Проверка overcommit
cat /proc/sys/vm/overcommit_memory
# → 0 ( heuristic: ядро «угадывает»)

cat /proc/meminfo | grep Committed
# → Committed_AS: 25000000 kB
# → CommitLimit: 20000000 kB
# → Committed_AS > CommitLimit = перекоммит!

# Строгий режим
sysctl vm.overcommit_memory=2
sysctl vm.overcommit_ratio=80
```

**Параметры:**

| overcommit_memory | Поведение | Рекомендация |
|:---|:---|:---|
| 0 | Heuristic (по умолчанию) | Работает, но непредсказуемо |
| 1 | Всегда разрешать | Для Redis, fork() heavy |
| 2 | Строгий (CommitLimit) | Для баз данных, критичных систем |

---

## Дополнительная информация

### Связанные темы

- [**vmstat**](../Memory/vmstat.md) — подробная справочная по vmstat
- [**/proc/meminfo**](../Memory/proc_meminfo.md) — расшифровка всех полей
- [**Slab allocator**](../../Core/memory/slab_allocator.md) — slab кэши ядра
- [**Swap management**](../../Core/memory/swap_management.md) — настройка swap
- [**Swap diagnostics**](../../Core/memory/swap_diagnostics.md) — диагностика swap
- [**Virtual vs Physical Memory**](../../Core/memory/virtual_vs_physical_memory.md) — концепции
- [**Memory tuning**](../../Core/memory/performance_tuning.md) — тюнинг памяти
- [**sysctl memory**](../../Core/kernel/sysctl_production.md#параметры-памяти) — sysctl для памяти
- [**OOM Killer**](../../Core/processes/oom_killer_mechanism.md) — механизм OOM
- [**OOM Killer Management**](../../Core/processes/oom_killer_management.md) — управление OOM
- [**Container Memory**](./container_performance_diagnostics.md) — память в контейнерах
- [**smem**](../Memory/smem.md) — корректный учёт памяти
- [**pmap**](../Memory/pmap.md) — карта памяти процесса

### Чек-лист быстрой диагностики памяти

```bash
# 1. Общая картина
free -m

# 2. Swap активен?
vmstat 1 3

# 3. Давление
cat /proc/pressure/memory

# 4. Кто потребляет?
ps aux --sort=-%mem | head -10

# 5. Детали
grep -E "MemAvailable|Dirty|Slab|SUnreclaim|SwapFree|Committed_AS|AnonPages" /proc/meminfo

# 6. OOM события
dmesg | grep -i oom | tail -5

# 7. THP
cat /sys/kernel/mm/transparent_hugepage/enabled
```
