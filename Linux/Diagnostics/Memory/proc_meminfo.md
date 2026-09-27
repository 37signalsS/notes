# /proc/meminfo — статистика памяти ядра

## Определения

Виртуальный файл **/proc/meminfo** предоставляет исчерпывающую статистику об использовании ядром оперативной (RAM) и swap-памяти в реальном времени. Это первичный источник данных для большинства утилит системного мониторинга, таких как `free`, `top`, `htop`, `vmstat` и `node_exporter`.

> **Важное уточнение (KiB vs KB):** Несмотря на метку `kB` в выводе файла, значения указаны в **кибибайтах (KiB)** (1024 байта). Это историческое решение сохранено для совместимости со старым ПО мониторинга. Все расчеты в этом файле должны использовать 1024 как делитель, а не 1000.

## Основные концепции

### Ключевые показатели: MemAvailable vs MemFree

Ядро Linux стремится максимально эффективно использовать доступную оперативную память, поэтому "полностью свободная" память (`MemFree`) обычно составляет малую часть общего объёма, так как остальное занято страничным кэшем (Page Cache) для ускорения I/O.

- **MemFree**: Память, которая в данный момент абсолютно не задействована ни процессами, ни системным кэшем.
- **Buffers** и **Cached**: Память, используемая для временного хранения данных файлов и метаданных файловой системы. Ядро может немедленно освободить эту память, если она потребуется приложениям.
- **MemAvailable**: Самый важный показатель для SRE. Это оценка объёма памяти, который реально доступен для запуска новых приложений без ухода системы в swap. Он учитывает `MemFree`, `KReclaimable` и ту часть кэша, которую можно безопасно очистить, сохраняя при этом минимально необходимые резервы ядра (водяные знаки).

### Классификация типов памяти (LRU)

Для эффективного управления ядро делит страницы памяти на категории (LRU — Least Recently Used):

- **Активная (Active)** vs. **Неактивная (Inactive)**: Память, используемая в данный момент, и память, к которой давно не было обращений (первый кандидат на выгрузку в swap или удаление из кэша).
- **Анонимная (Active(anon), Inactive(anon))**: Память процессов, не связанная с файлами на диске (куча, стек, сегменты данных).
- **Файловая (Active(file), Inactive(file))**: Память, в которой закэшировано содержимое файлов.
- **Unevictable**: Память, заблокированная через `mlock` или используемая `ramfs`, которую ядро не имеет права выселять.

### Водяные знаки памяти (Memory Watermarks)

Ядро использует три порога (watermarks) для управления выделением и освобождением страниц. Эти пороги напрямую влияют на расчет `MemAvailable`:

| Порог | Описание |
| :--- | :--- |
| **min** | Критический уровень. При его достижении запускается прямое освобождение (direct reclaim), блокирующее процессы до высвобождения памяти. |
| **low** | Порог активации фонового демона `kswapd`, который начинает плавно освобождать память. |
| **high** | Целевой уровень, до которого `kswapd` пытается довести объём свободной памяти. |

Постоянное нахождение свободной памяти на уровне `min` указывает на критическую перегрузку. Текущие значения можно посмотреть в `/proc/zoneinfo`.

### NUMA-узлы в /proc/meminfo

На многопроцессорных системах с NUMA-архитектурой (Non-Uniform Memory Access) `/proc/meminfo` содержит блоки записей для каждого узла памяти. Эти записи критичны для диагностики зонального дефицита (zone depletion) и дисбаланса памяти:

```
Node 0 MemTotal:       16384000 kB
Node 0 MemFree:         1234560 kB
Node 0 MemAvailable:    9876543 kB
...
Node 1 MemTotal:       16384000 kB
Node 1 MemFree:         2345678 kB
```

**Интерпретация для SRE:**
- Разница `MemAvailable` между узлами указывает на дисбаланс. Если `Node 0` исчерпан, а `Node 1` свободен — процессы на `Node 0` тратят время на удаленный доступ через QPI/UPI (latency 2–5× выше, чем локальный).
- Для анализа топологии используйте `numactl --hardware` и сравните расстояния (`node distances`).
- Привязка памяти к узлу: `numactl --cpunodebind=0 --membind=0 <приложение>`.

### Взаимодействие с cgroup v2

В контейнерных средах `/proc/meminfo` показывает состояние **хоста**, а не ограничения контейнера. Это классическая ловушка для SRE:

| Источник | Что показывает | Где смотреть |
| :--- | :--- | :--- |
| `/proc/meminfo` (внутри контейнера) | Память хоста | Не использовать для оценки лимитов контейнера |
| `/sys/fs/cgroup/.../memory.max` | Жесткий лимит контейнера | cgroup v2 |
| `/sys/fs/cgroup/.../memory.current` | Текущее потребление контейнера | cgroup v2 |
| `docker stats` | Агрегированная статистика | Docker CLI |

**Практический эффект:** Приложение внутри контейнера, читающее `/proc/meminfo`, видит весь RAM хоста и может выделить больше памяти, чем разрешено `memory.max`, что приведет к OOM Killer внутри cgroup.

Для корректной диагностики контейнерной памяти используйте:
```bash
# На хосте
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.events
```

### MGLRU и его влияние на метрики

Начиная с ядра 6.1, Multi-Gen LRU (MGLRU) заменяет классические списки Active/Inactive на поколения (generations). Это влияет на интерпретацию `/proc/meminfo`:

- **Active(anon)/Inactive(anon)**: При MGLRU эти значения могут меняться быстрее, так как ядро точнее определяет "горячие" страницы. Рост `Inactive(anon)` не всегда означает проблему — это может быть нормальная работа MGLRU.
- **Проверка статуса MGLRU:**
  ```bash
  cat /sys/kernel/mm/lru_gen/enabled
  # → 0x0007 (включено для anonymous, file, swap)
  ```
- **Диагностический инсайт:** Если ` workingset_refault_anon` растет при включенном MGLRU — система испытывает реальный thrashing, а не просто агрессивный reclaim.

## Справочник параметров /proc/meminfo

### Основные метрики

| Параметр | Описание |
| :--- | :--- |
| `MemTotal` | Общий объем физической RAM, доступной ядру. |
| `MemFree` | Полностью свободная память. |
| `MemAvailable` | Оценка реально доступной памяти для приложений. |
| `Buffers` | Временное хранение сырых блоков диска (метаданные ФС). |
| `Cached` | Страничный кэш (page cache) для файлов. |
| `SwapCached` | Память, выгруженная в swap, но оставшаяся в RAM (для ускорения повторного доступа). |
| `Bounce` | Память под bounce buffers для DMA-устройств, не поддерживающих 32-битную адресацию. Актуально для старых архитектур (x86_64 обычно 0). |
| `FilePages` | Общий объем файловых страниц (file-backed). Включает и активные, и неактивные страницы кэша. |
| `Mapped` | Объем памяти, отображенной через `mmap()` (файлы и устройства). |

### Классификация и активность

| Параметр | Описание |
| :--- | :--- |
| `Active(anon)` | Активная анонимная память (динамические данные процессов). |
| `Inactive(anon)` | Анонимная память, готовая к выгрузке в swap. |
| `Active(file)` | Активный страничный кэш. |
| `Inactive(file)` | Файловый кэш, который ядро может очистить первым. |
| `Unevictable` | Память, которую нельзя выгрузить (mlock, ramfs). |
| `Mlocked` | Объем памяти, заблокированной процессами через системный вызов `mlock()`. |

### Память ядра и служебные структуры

| Параметр | Описание |
| :--- | :--- |
| `Slab` | Память под структуры данных ядра. |
| `SReclaimable` | Часть Slab, которую ядро может освободить (например, кэш inode). |
| `SUnreclaim` | Часть Slab, которую нельзя освободить (критично при поиске утечек в ядре). |
| `KReclaimable` | Суммарная очищаемая память ядра (SReclaimable + другие кэши с "shrinkers"). |
| `KernelStack` | Память для стеков выполнения потоков ядра. |
| `PageTables` | Память, занятая таблицами страниц (трансляция адресов). |
| `SecPageTables` | (Новое) Память под вторичные таблицы страниц (Virtualization/EPT/NPT). |
| `Percpu` | Память, выделенная для переменных, специфичных для каждого ядра CPU. |
| `VmallocUsed` | Объем памяти, выделенной через `vmalloc` (драйверы, модули). |
| `VmallocTotal` | Общий объем доступного виртуального адресного пространства для `vmalloc`. |
| `VmallocChunk` | Самый большой непрерывный свободный блок в `vmalloc`-области. |
| `WritebackTmp` | Временная память, используемая ядром при сбросе грязных страниц на диск. |

### Огромные страницы (Huge Pages)

| Параметр | Описание |
| :--- | :--- |
| `AnonHugePages` | Объем анонимной памяти, использующей Transparent Huge Pages (THP). |
| `ShmemHugePages` | Объем разделяемой памяти (`tmpfs`), использующей Huge Pages. |
| `HugePages_Total` | Общее количество явно выделенных Huge Pages (через sysctl). |
| `HugePages_Free` | Количество свободных Huge Pages в пуле. |
| `Hugepagesize` | Размер одной Huge Page (обычно 2MB на x86_64). |
| `HugePages_Rsvd` | Количество Huge Pages, зарезервированных для будущего использования. |
| `HugePages_Surp` | Количество "избыточных" Huge Pages, выделенных сверх `HugePages_Total` (только для THP). |
| `DirectMap4k/2M/1G` | Объем памяти, отображенный в ядро страницами соответствующего размера (индикатор эффективности TLB). |

### Swap, Сжатие и Лимиты

| Параметр | Описание |
| :--- | :--- |
| `SwapTotal / SwapFree` | Лимиты и остаток в области подкачки. |
| `Zswap / Zswapped` | (Ядра 6.x+) Память в сжатом пуле Zswap и исходный объем данных до сжатия. |
| `CommitLimit` | Максимальный объем виртуальной памяти (RAM + Swap * ratio), который можно выделить. |
| `Committed_AS` | Объем виртуальной памяти, фактически запрошенный всеми процессами (Overcommit). |
| `HardwareCorrupted` | Объем памяти, которую ядро пометило как неисправную (ECC ошибки). |

## Практические сценарии

### 1. Выявление утечек памяти в ядре

Если `MemAvailable` падает, а память процессов (`Active(anon)`) стабильна, проверьте `SUnreclaim`. Постоянный рост этого значения указывает на утечку в драйвере или модуле ядра.

```bash
# Мониторинг "грязной" памяти ядра
grep SUnreclaim /proc/meminfo
# → SUnreclaim:        152438 kB
```

### 2. Анализ эффективности Huge Pages

Высокое значение `PageTables` (более 1-2 ГБ) на серверах с большим объемом RAM указывает на накладные расходы на трансляцию адресов. В этом случае переход на Huge Pages значительно повысит производительность за счет снижения нагрузки на TLB.

```bash
grep -E "PageTables|HugePages" /proc/meminfo
```

### 3. Диагностика I/O Bottleneck (Dirty Pages)

Если система "фризит" при интенсивной записи, проверьте объем данных, ожидающих сброса на диск.

```bash
grep -E "Dirty|Writeback" /proc/meminfo
# Dirty: Объем памяти, измененной процессами, но еще не записанной на диск.
# Writeback: Объем памяти, который сбрасывается на диск в данный момент.
```

### 4. Оценка виртуализации и контейнеризации

Для гипервизоров критично отслеживать `SecPageTables`. Большие значения указывают на накладные расходы на управление вложенными таблицами страниц для ВМ.

```bash
grep SecPageTables /proc/meminfo
```

### 5. Оценка риска OOM (Out of Memory)

Сравните `Committed_AS` и `CommitLimit`. Если `Committed_AS` превышает `CommitLimit`, система находится в состоянии Overcommit, и при обращении к выделенной памяти может сработать OOM Killer.

```bash
grep -E "Commit(Limit|ted_AS)" /proc/meminfo
```

### 6. Проверка аппаратного состояния RAM

Для серверов с поддержкой ECC ядро может изолировать поврежденные участки памяти. Ненулевое значение `HardwareCorrupted` — повод для немедленной замены модуля RAM.

```bash
grep HardwareCorrupted /proc/meminfo
# → HardwareCorrupted:     0 kB
```

### 7. Анализ NUMA-узлов через Node-записи

На NUMA-системах `/proc/meminfo` содержит блоки `Node 0`, `Node 1` и т.д. Анализ этих блоков позволяет выявить дисбаланс памяти между сокетами:

```bash
# Извлечение всех Node-записей
grep -E "^Node" /proc/meminfo
# → Node 0 MemTotal:       16384000 kB
# → Node 0 MemFree:         1234560 kB
# → Node 1 MemTotal:       16384000 kB
# → Node 1 MemFree:         2345678 kB

# Сравнение доступной памяти по узлам
awk '/^Node.*MemAvailable/ {print $0}' /proc/meminfo
# → Node 0 MemAvailable:    9876543 kB
# → Node 1 MemAvailable:   14321987 kB

# Если разница > 20% — возможен дисбаланс NUMA
```

**Диагностика:** Используйте `numastat` для детального анализа и `numactl --cpunodebind` для привязки проблемных процессов.

### 8. Дифференциальный анализ (Snapshot Diff)

Для выявления медленных утечек или трендов сохраняйте снимки `/proc/meminfo` и сравнивайте их:

```bash
#!/bin/bash
# meminfo_diff.sh — сравнение двух снимков /proc/meminfo
SNAPSHOT1=${1:-/tmp/meminfo_before.txt}
SNAPSHOT2=${2:-/tmp/meminfo_after.txt}

if [ ! -f "$SNAPSHOT1" ] || [ ! -f "$SNAPSHOT2" ]; then
  echo "Usage: $0 <before.txt> <after.txt>"
  exit 1
fi

echo "=== Рост/падение ключевых метрик ==="
diff --old-line-format='REMOVED: %L' --new-line-format='ADDED: %L' \
     --unchanged-line-format='SAME: %L' \
     <(grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree" "$SNAPSHOT1") \
     <(grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree" "$SNAPSHOT2") \
  | grep -E 'REMOVED:|ADDED:' | sort -k2 -nr | head -20
```

**Использование:**
```bash
# Снимок 1
grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree" /proc/meminfo > /tmp/meminfo_before.txt

# ... ждем 10–60 минут ...

# Снимок 2
grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree" /proc/meminfo > /tmp/meminfo_after.txt

# Сравнение
./meminfo_diff.sh /tmp/meminfo_before.txt /tmp/meminfo_after.txt
```

### 9. Диагностика контейнеров: meminfo внутри и снаружи

В контейнере `/proc/meminfo` показывает память хоста, а не лимит контейнера. Это приводит к неверным диагнозам:

```bash
# ВНУТРИ контейнера (Docker без LXCFS)
cat /proc/meminfo | grep MemTotal
# → MemTotal:       65536128 kB  (всё RAM хоста!)

# На хосте — реальный лимит контейнера
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.max
# → 4G

# Текущее потребление контейнера
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current
# → 3145728 kB

# Сравнение: MemTotal хоста (64ГБ) ≠ memory.max контейнера (4ГБ)
```

**Решение:** Для диагностики контейнеров всегда используете cgroup-файлы на хосте. Если контейнер использует LXCFS, `/proc/meminfo` внутри контейнера покажет корректные ограничения.

### 10. Трайблшутинг Writeback и Dirty Pages

`Dirty` и `Writeback` в `/proc/meminfo` позволяют диагностировать проблемы с дисковым I/O без `iostat`:

```bash
# Мониторинг в реальном времени
watch -n1 "grep -E 'Dirty|Writeback' /proc/meminfo"
# → Dirty:          524288 kB
# → Writeback:       65536 kB

# Диагностика:
# - Dirty растет, Writeback ≈ 0: writeback заблокирован (диск перегружен или недоступен)
# - Dirty > 2-4 ГБ постоянно: disk bottleneck, нужно снижать vm.dirty_ratio
# - Writeback > Dirty: система активно сбрасывает данные (норма после spike)
```

**Корреляция с диском:**
```bash
# Если Dirty растет, проверьте диск
iostat -xz 1 5
# → await > 50ms на диске swap = дисковая узекое место
```

### 11. Быстрый health-check хоста

One-liner для быстрой оценки состояния памяти хоста:

```bash
awk '
/MemTotal/ {total=$2}
/MemAvailable/ {avail=$2}
/MemFree/ {free=$2}
/Active\(anon\)/ {anon=$2}
/Dirty/ {dirty=$2}
/SUnreclaim/ {unreclaim=$2}
/SwapTotal/ {swap_total=$2}
/SwapFree/ {swap_free=$2}
/Committed_AS/ {committed=$2}
END {
  pct_avail = (avail/total)*100
  pct_dirty = (dirty/total)*100
  pct_slab = (unreclaim/total)*100
  swap_used = swap_total - swap_free
  pct_swap = (swap_total > 0) ? (swap_used/swap_total)*100 : 0
  
  printf "MemAvailable: %4.1f%% (%d/%d MB)\n", pct_avail, avail/1024, total/1024
  printf "Dirty:        %4.1f%% (%d MB)\n", pct_dirty, dirty/1024
  printf "SUnreclaim:   %4.1f%% (%d MB)\n", pct_slab, unreclaim/1024
  printf "SwapUsed:     %4.1f%% (%d MB)\n", pct_swap, swap_used/1024
  
  if (pct_avail < 10) print "STATUS: CRITICAL — MemAvailable < 10%"
  else if (pct_avail < 20) print "STATUS: WARNING — MemAvailable < 20%"
  else print "STATUS: OK"
}' /proc/meminfo
# → MemAvailable:  45.2% (11500/25400 MB)
# → Dirty:          2.1% (533 MB)
# → SUnreclaim:     0.8% (203 MB)
# → SwapUsed:       5.0% (200 MB)
# → STATUS: OK
```

### 12. Baseline drift detection

Сохраните "здоровый" снимок `/proc/meminfo` в состоянии минимальной нагрузки и сравнивайте с текущим:

```bash
#!/bin/bash
# meminfo_baseline.sh — сравнение с baseline
BASELINE=/var/tmp/meminfo_baseline.txt
CURRENT=/tmp/meminfo_current.txt

# Сохранение baseline (выполнить один раз в "холодное" время)
if [ ! -f "$BASELINE" ]; then
  grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree|Committed_AS" /proc/meminfo > "$BASELINE"
  echo "Baseline saved to $BASELINE"
  exit 0
fi

# Текущий снимок
grep -E "MemAvailable|MemFree|Active\(anon\)|Inactive\(anon\)|Dirty|SUnreclaim|SwapFree|Committed_AS" /proc/meminfo > "$CURRENT"

echo "=== Отклонение от baseline ==="
paste "$BASELINE" "$CURRENT" | awk '{
  base=$2; curr=$5
  if (base > 0) {
    drift = ((curr - base) / base) * 100
    if (drift < -10 || drift > 10)
      printf "%.1f%%\t%s\n", drift, $1
  }
}'
# → -25.3%    MemAvailable:
# →  142.5%   Dirty:
```

## Трайблшутинг

### MemFree = 0, но система работает

**Симптом:** `MemFree` близок к нулю, `free -h` показывает `free: 0B`.

**Причина:** Ядро использует всю свободную RAM для Page Cache. Это нормальное поведение.

**Диагностика:** Проверьте `MemAvailable`. Если он > 20% — проблем нет. Если `MemAvailable` < 10% — система реально испытывает давление памяти.

### Dirty растет, Writeback ≈ 0

**Симптом:** `Dirty` постоянно растет (гигабайты), `Writeback` близок к нулю.

**Причина:** Дисковая подсистема перегружена или недоступна. Ядро не может сбросить грязные страницы.

**Действия:**
1. Проверьте `iostat -xz 1` — ищите высокий `await` (> 50ms) или `%util` ≈ 100%.
2. Временное решение: снизьте `vm.dirty_ratio` и `vm.dirty_background_ratio`.
3. Если диск недоступен (NFS, отвал SAN) — переведите запись в другой пул или остановите записывающие процессы.

### Committed_AS > CommitLimit, но OOM не происходит

**Симптом:** `Committed_AS` превышает `CommitLimit`, но процессы не убиваются.

**Причина:** `vm.overcommit_memory = 1` (Always). Ядро разрешает любой `malloc()`, но реальный доступ к памяти может вызвать OOM.

**Действия:** Установите `vm.overcommit_memory = 2` (Strict) для предсказуемости. Контролируйте `Committed_AS` через `node_exporter`.

### SUnreclaim растет, slabtop стабилен

**Симптом:** `SUnreclaim` в `/proc/meminfo` растет, но `slabtop` не показывает явного лидера.

**Причина:** Утечка в модуле ядра, который не отображается в стандартных кэшах slab (например, через `vmalloc` или `kmalloc` в драйвере).

**Действия:**
1. Проверьте `dmesg -T | grep -iE "leak|corruption|out of memory"` за последние события.
2. Выгрузите последние загруженные модули: `lsmod | sort -k 3` (по времени) и попробуйте `rmmod`.
3. Перезагрузка — единственный способ освободить `SUnreclaim` из kernel module.

### HugePages_Free = 0, но THP работает

**Симптом:** `HugePages_Free: 0`, но `AnonHugePages` > 0.

**Причина:** `HugePages_Total` — это статический пул для явно выделенных Huge Pages. Transparent Huge Pages (THP) работают независимо и используют динамические huge pages, которые не отображаются в `HugePages_Free`.

**Действия:** Для THP смотрите `AnonHugePages` и `/sys/kernel/mm/transparent_hugepage/enabled`. Статические Huge Pages настраиваются через `vm.nr_hugepages`.

## Best Practices

1. **Всегда используйте `MemAvailable`, а не `MemFree`.** `MemFree` бесполезен для оценки реально доступной памяти на современных системах с Page Cache.
2. **Собирайте baseline в "холодное" время.** Зафиксируйте значения `/proc/meminfo` при минимальной нагрузке (после загрузки, но перед пиком). Сравнивайте текущие показатели с baseline, а не с абсолютными порогами.
3. **Коррелируйте с `/proc/zoneinfo`.** Если `MemAvailable` падает, проверьте `free` по каждой зоне (ZONE_DMA, ZONE_NORMAL) — проблема может быть локальной.
4. **Для контейнеров используйте cgroup-файлы, а не `/proc/meminfo`.** Внутри контейнера `/proc/meminfo` показывает хост. Лимиты и текущее потребление — в `/sys/fs/cgroup/<group>/memory.max` и `memory.current`.
5. **Комбинируйте с `vmstat` и `sar`.** `/proc/meminfo` — точка в времени. `vmstat` показывает динамику (`si`/`so`, `bi`/`bo`), `sar -r` — историю.
6. **Используйте `node_exporter` для трендов.** Для графиков и алертов нагружайте Prometheus с `node_exporter`. `/proc/meminfo` — для интерактивной диагностики.
7. **Не полагайтесь на один индикатор.** `MemAvailable` + `PSI` (`/proc/pressure/memory`) + `vmstat` дают полную картину. Если `MemAvailable` высокий, но PSI `full avg10 > 5%` — система испытывает локальный pressure.
8. **Проверяйте NUMA-баланс на многосокетных системах.** Если `Node 0 MemAvailable` значительно ниже `Node 1`, ищите дисбаланс привязки процессов или memory leak на узле 0.

## Типичные инциденты и их диагностика

### Инцидент 1: "Сервер потребляет всю память"

**Симптом:** Мониторинг показывает высокое потребление RAM, но сервис работает нормально.

**Диагностика:**
```bash
# Проверка MemAvailable — реального показателя доступной памяти
grep -E "MemTotal|MemAvailable|MemFree|Cached|Buffers" /proc/meminfo
# → MemTotal:       32768000 kB
# → MemFree:         1048576 kB
# → MemAvailable:   20971520 kB  ← 20 ГБ доступно!
# → Cached:         18874368 kB  ← Page Cache
# → Buffers:          524288 kB
```

**Вывод:** `MemFree` близок к 0, но `MemAvailable` = 20 ГБ. Это нормальное поведение — ядро использует свободную RAM для Page Cache. Проблемы нет.

**Ключевое:** `MemAvailable` учитывает `MemFree` + `KReclaimable` + часть кэша, которую можно безопасно освободить. Это единственный корректный показатель доступной памяти.

---

### Инцидент 2: "OOM Killer убивает процессы при наличии свободной памяти"

**Симптом:** `dmesg` показывает OOM Kill, но `free` показывает свободную память.

**Диагностика:**
```bash
# 1. Проверка типа OOM
dmesg -T | grep -i "oom\|killed process" | tail -3
# → [Tue Sep 16 10:30:45 2026] Out of memory: Killed process 12345 (java)

# 2. Проверка Committed_AS vs CommitLimit
grep -E "Commit(Limit|ted_AS)" /proc/meminfo
# → CommitLimit:    16384000 kB
# → Committed_AS:   20000000 kB  ← Превышает лимит!

# 3. Проверка overcommit
cat /proc/sys/vm/overcommit_memory
# → 1  ← Always overcommit
```

**Причина:** `vm.overcommit_memory=1` разрешает любые аллокации. Процессы выделили больше, чем физически доступно, и при реальном обращении к памяти сработал OOM.

**Решение:** Установить `vm.overcommit_memory=2` (strict) и контролировать `Committed_AS`.

---

### Инцидент 3: "Контейнер убит OOM, хотя на хосте есть память"

**Симптом:** Docker/Kubernetes контейнер завершен с OOMKilled, но `free` на хосте показывает достаточно памяти.

**Диагностика:**
```bash
# 1. Проверка лимита контейнера
CGROUP="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' <container>).scope"
cat $CGROUP/memory.max
# → 4294967296 (4 ГБ)

# 2. Проверка текущего потребления
cat $CGROUP/memory.current
# → 4200000000 (почти 4 ГБ)

# 3. Проверка events
cat $CGROUP/memory.events
# → oom_kill 1  ← OOM сработал в cgroup
```

**Причина:** Лимит `memory.max=4GB` в cgroup. Процесс потребил > 4 ГБ, OOM Killer убил его внутри cgroup, не затрагивая хост.

**Ключевое:** Внутри контейнера `/proc/meminfo` показывает RAM хоста (64 ГБ), но реальный лимит — 4 ГБ в cgroup.

---

### Инцидент 4: "SUnreclaim растет без видимых причин"

**Симптом:** `SUnreclaim` в `/proc/meminfo` постоянно растет, процессы стабильны.

**Диагностика:**
```bash
# 1. Проверка slabinfo
sudo slabtop -o | head -15
# →  OBJS ACTIVE  USE OBJ SIZE  SLABS OBJ/SLAB CACHE SIZE
# → 200000 200000 100%  0.25K  10000        20     200000K

# 2. Проверка kmemleak (если доступен)
sudo sh -c 'echo scan > /sys/kernel/debug/kmemleak'
sudo cat /sys/kernel/debug/kmemleak | head -20

# 3. Проверка dmesg на ошибки
dmesg -T | grep -iE "leak|corruption|slab"
```

**Причина:** Утечка в модуле ядра (драйвер, файловая система). `SUnreclaim` — это slab, который ядро не может освободить.

**Решение:** Перезагрузка (единственный способ освободить `SUnreclaim`), обновление модуля/ядра.

---

### Инцидент 5: "Dirty pages растут, система фризит при записи"

**Симптом:** При интенсивной записи система становится неотзывчивой.

**Диагностика:**
```bash
# 1. Проверка Dirty/Writeback
grep -E "Dirty|Writeback" /proc/meminfo
# → Dirty:          5242880 kB  (5 ГБ грязных страниц)
# → Writeback:        65536 kB  (64 МБ в процессе записи)

# 2. Проверка дисковой подсистемы
iostat -xz 1 5
# → await > 50ms на диске — bottleneck

# 3. Проверка vm.dirty_ratio
cat /proc/sys/vm/dirty_ratio
# → 20  ← 20% от RAM может быть грязным
```

**Причина:** Диск не успевает сбрасывать грязные страницы. `Dirty` растет, процессы блокируются в `write()`.

**Решение:** Снизить `vm.dirty_ratio` и `vm.dirty_background_ratio`, оптимизировать I/O.

## Дополнительная информация

### См. также

- [`vmstat`](./vmstat.md) — мониторинг динамики памяти (si/so, bi/bo, free).
- [`smem`](./smem.md) — точный анализ PSS/USS.
- [`pmap`](./pmap.md) — карта памяти процесса.
- [Диагностика Swap и Page Faults](../../Core/memory/swap_diagnostics.md) — глубокий анализ проблем подкачки и Major Faults.
- [Механизмы кэширования и освобождения памяти](../../Core/memory/caching_and_reclaiming.md) — как ядро управляет Page Cache, kswapd и Direct Reclaim.
- [Дерево решений: диагностика проблем с памятью](./memory_troubleshooting_decision_tree.md) — алгоритм быстрой диагностики.
- [Container memory diagnostics](./container_memory_diagnostics.md) — диагностика памяти в контейнерах.
