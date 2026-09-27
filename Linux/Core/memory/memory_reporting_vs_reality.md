# Фактическое потребление памяти vs Reporting в Linux

## Определения

**Reporting памяти** — отображение потребления RAM через стандартные утилиты (`free`, `top`, `htop`, `ps`). Эти инструменты показывают разные "взгляды" на одно и то же явление, что часто приводит к ложным выводам о "нехватке" памяти.

**Фактическое потребление (Real Usage)** — объем физической RAM, который процесси/system используют для хранения данных, необходимых для работы. Включает анонимную память (RSS) и резервы ядра, но НЕ включает Page Cache, который ядро может освободить в любой момент.

**Page Cache (кэш файлов)** — память, используемую ядром для кэширования чтений с диска. Ядро стремится занять всю свободную RAM кэшем ("свободная память — потраченная впустую память"). При нехватке RAM ядро может освободить clean-страницы кэша мгновенно.

**MemAvailable** — метрика из `/proc/meminfo`, отражающая реальный объем памяти, доступный для запуска новых приложений без свопинга. Учитывает `MemFree`, `KReclaimable` и ту часть кэша, которую можно безопасно очистить.

## Основные концепции

### Почему `free` почти всегда показывает мало свободной памяти

Команда `free -h` показывает шесть колонок:

```
              total        used        free      shared  buff/cache   available
Mem:           15Gi       8.0Gi       1.0Gi       256Mi       6.0Gi       6.5Gi
```

| Колонка | Что означает | Почему вводит в заблуждение |
| :--- | :--- | :--- |
| `total` | Общий объем RAM | — |
| `used` | RAM минус free минус buff/cache | Включает Page Cache, который может быть освобожден |
| `free` | Абсолютно неиспользуемая память | Ядро намеренно держит её мало, используя для кэша |
| `shared` | Память через tmpfs, /dev/shm | Незначительно для диагностики |
| `buff/cache` | Page Cache + Buffer Cache + Slab | Это НЕ используется приложениями, ядро может освободить |
| **`available`** | **Реально доступная память** | **Единственный корректный показатель для оценки** |

**Правило SRE:** Смотрите на `available`, а НЕ на `free`. Значение `free: 0B` при `available: 8GB` — это нормальное поведение ядра, а не проблема.

### Разница между `used` в `free` и реальным потреблением

```
used = total - free - buff/cache
```

Эта формула включает в `used` часть Page Cache, что создает ложное ощущение высокого потребления. Реальное потребление приложений — это RSS (Resident Set Size) процессов, которые можно увидеть через `ps` или `smem`.

**Пример:**
```bash
free -h
# → used: 12 ГБ, available: 10 ГБ
# Вывод: система "использует" 12 ГБ, но реально доступно 10 ГБ

# Реальное потребление процессов:
ps aux --sort=-rss | awk '{sum+=$6} END {print sum/1024 " МБ"}'
# → 4500 МБ (4.5 ГБ) — вот реальное потребление
```

### `top`/`htop`: RES vs SHR vs %MEM

| Поле | Описание | Когда растет |
| :--- | :--- | :--- |
| **VIRT (VSZ)** | Виртуальное адресное пространство (включает mmap, зарезервированную память). | При большом количестве mmap-файлов или JCC. Не индикатор потребления RAM. |
| **RES (RSS)** | Физическая память процесса (включая Shared). | При утечке памяти или росте рабочего набора. |
| **SHR** | Разделяемая память (библиотеки, tmpfs). Может использоваться несколькими процессами. | Нормально, если растет вместе с RSS. |
| **%MEM** | `(RSS / MemTotal) * 100`. | Учитывает Shared дважды — не суммируйте для 전체 системы! |

**Ключевая проблема:** `RES` в `top` включает разделяемую память (SHR). Если 10 процессов используют одну библиотеку (100 МБ), `top` покажет `RES = 100 МБ` для каждого, создавая иллюзию потребления 1 ГБ, хотя реально занято только 100 МБ.

**Решение:** Используйте `smem` для точного расчета PSS (Proportional Set Size).

### PSS vs RSS: точное измерение

| Метрика | Формула | Описание |
| :--- | :--- | :--- |
| **RSS** | Сумма всех резидентных страниц | Включает Shared дважды. |
| **PSS** | `Shared / N_processes + Private` | Разделяемая память пропорциональна числу процессов. Наиболее точный показатель. |
| **USS** | Только Private страницы | Память, которая будет освобождена при завершении процесса. |

**Пример:**
```bash
# Точное измерение через smem
smem -tk -s pss -r | head
# →   PID User     Command                         Swap      USS      PSS      RSS
# →  1234 root     postgres                          0    45.0M    48.2M    52.1M

# Группировка по процессам (суммарное потребление)
sudo ps_mem
# →  Private  +   Shared  =  RAM used    Program
# →  45.0 MiB  +   3.2 MiB =  48.2 MiB  postgres (5)
```

### Сравнение инструментов

| Инструмент | Показывает | Точность | Когда использовать |
| :--- | :--- | :--- | :--- |
| `free -h` | Глобальная картина (total/used/free/buff/cache/available) | Средняя | Быстрая оценка системы |
| `top`/`htop` | RSS/VSZ каждого процесса | Средняя (.Shared) | Мониторинг в реальном времени |
| `ps aux --sort=-rss` | RSS/VSZ для снимка | Средняя | Поиск топ-процессов |
| `smem -s pss` | PSS/USS для каждого процесса | Высокая | Точный анализ потребления |
| `ps_mem` | Private + Shared = RAM used | Высокая | Группировка по программам |
| `pmap -X <PID>` | Детализация по сегментам (RSS/PSS/Swap) | Очень высокая | Анализ конкретного процесса |
| `/proc/<pid>/smaps_rollup` | Агрегированные PSS/Anon/File | Очень высокая | Автоматизация мониторинга |

### Почему `top` показывает %MEM > 100% суммарно

Если сложить `%MEM` всех процессов в `top`, результат часто превышает 100%. Причины:

1. **Shared Memory (SHR):** Одна и та же страница (библиотека) учитывается в RSS каждого процесса.
2. **Page Cache:** Ядро может использовать одну страницу для разных процессов (общие библиотеки).
3. **Overcommit:** Ядро разрешает процессам "обещать" больше памяти, чем есть.

**Решение:** Используйте `smem -s pss` для корректной оценки.

### Влияние Copy-on-Write (CoW) на отображение

После `fork()` родитель и потомок используют одни и те же физические страницы (Copy-on-Write). `top` покажет RSS дважды, но реальное потребление RAM не удвоилось.

```bash
# Родитель: RSS = 500 МБ
# После fork() 100 потомков:
# top покажет: 101 * 500 МБ = 50.5 ГБ (ложно)
# Реальная нагрузка: 500 МБ + уникальные страницы потомков
# smem -s pss покажет реальную картину
```

### Контейнеры: видимость памяти

В контейнере `top` и `free` показывают память хоста, а не лимит контейнера:

```bash
# Внутри контейнера
free -h
# → Mem: 64Gi  (показывает RAM хоста!)

# Реальный лимит контейнера
cat /sys/fs/cgroup/memory.max
# → 4294967296  (4 ГБ)

# Текущее потребление контейнера
cat /sys/fs/cgroup/memory.current
# → 3221225472  (3 ГБ)
```

**Важно:** Kubelet использует `memory.current` из cgroup, а не `free -h`. Процесс внутри контейнера может думать, что у него 64 ГБ, но OOM Kill сработает при 4 ГБ.

### Метрики, которые НЕ видны в standard tools

| Что скрыто | Где смотреть |
| :--- | :--- |
| Page Cache (файловый кэш) | `/proc/meminfo` → `Cached`, `Active(file)`, `Inactive(file)` |
| Slab (память ядра) | `/proc/meminfo` → `Slab`, `SReclaimable`, `SUnreclaim` |
| Page Tables (таблицы страниц) | `/proc/meminfo` → `PageTables` |
| KernelStack | `/proc/meminfo` → `KernelStack` |
| Swap используется процессом | `/proc/<pid>/status` → `VmSwap` |
| PSS (Proportional Set Size) | `smem -s pss` или `/proc/<pid>/smaps_rollup` |

## Практические сценарии

### Быстрая оценка: free vs реальность

```bash
#!/bin/bash
# runbook: memory_reality_check.sh
echo "=== free -h (reporting) ==="
free -h

echo ""
echo "=== Реальное потребление процессов (smem) ==="
sudo smem -t -k -s pss -r | head -10

echo ""
echo "=== Суммарное потребление по программам ==="
sudo ps_mem | tail -n 15

echo ""
echo "=== Page Cache и Slab ==="
grep -E 'Cached|Slab|SReclaimable|SUnreclaim|PageTables|KernelStack' /proc/meminfo

echo ""
echo "=== PSI Memory ==="
cat /proc/pressure/memory
```

### Диагностика: "Сервер использует 99% RAM"

```bash
# Шаг 1: Проверка available
free -h
# → Mem: 16Gi, used: 15Gi, available: 12Gi
# → Если available > 20% от total — проблема нет, это Page Cache

# Шаг 2: Проверка Page Cache
grep -E 'Cached|Active\(file\)|Inactive\(file\)' /proc/meminfo
# → Cached: 10 ГБ — это кэш файлов, ядро освободит при необходимости

# Шаг 3: Проверка PSI
cat /proc/pressure/memory
# → some avg10=0.00 — система не испытывает давления

# Шаг 4: Проверка swap
free -h | grep Swap
# → Swap: 2Gi, used: 0Mi — swap не используется

# ВЫВОД: 99% "used" — это нормальный Page Cache. Проблемы нет.
```

### Диагностика: "RSS процесса больше MemTotal"

```bash
# Шаг 1: Проверка RSS через ps
ps -p <PID> -o rss,vsz,comm
# → RSS: 70000000 (70 ГБ), VSZ: 128000000 (128 ГБ)

# Шаг 2: Проверка через smem (PSS)
sudo smem -p -k -s pss -P <process_name>
# → PSS: 35000000 (35 ГБ) — реальное потребление

# Шаг 3: Проверка shared memory
cat /proc/<PID>/smaps_rollup | grep -E "Rss|Pss|Shared"
# → Rss: 70000000 kB
# → Pss: 35000000 kB
# → Shared_Clean: 35000000 kB  ← 35 ГБ разделяются с другими процессами

# ВЫВОД: RSS > MemTotal из-за shared memory (библиотеки, JVM).
# Реальное потребление (PSS) = 35 ГБ. Это нормально для кластера.
```

### Диагностика: "Process RSS растет, но free не падает"

```bash
# Шаг 1: Проверка типа роста
sudo smem -t -k -s pss -r | grep <process_name>
# → PSS растет? Или только RSS?

# Шаг 2: Проверка smaps_rollup
cat /proc/<PID>/smaps_rollup | grep -E "Private_Clean|Private_Dirty|Shared_Clean|Shared_Dirty"
# → Private_Dirty растет = утечка памяти (heap/stack)
# → Shared растет = нормально (загрузка библиотек, tmpfs)

# Шаг 3: Проверка Page Cache
grep -E 'Active\(file\)|Inactive\(file\)' /proc/meminfo
# → Если Active(file) растет — ядро кэширует файлы, это нормально

# Шаг 4: Мониторинг через pidstat
pidstat -r -p <PID> 60
# → Если RSS растет, а PSS стабилен — рост Shared (не проблема)
# → Если RSS и PSS растут — проблема в Private (утечка)
```

### Runbook: ежедневный аудит памяти

```bash
#!/bin/bash
# runbook: daily_memory_audit.sh

echo "=== 1. Глобальная картина ==="
free -h
echo ""

echo "=== 2. Доступная память (ключевая метрика) ==="
avail=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
total=$(grep MemTotal /proc/meminfo | awk '{print $2}')
pct=$(echo "scale=1; $avail * 100 / $total" | bc)
echo "MemAvailable: ${pct}% от MemTotal"
if [ $(echo "$pct < 20" | bc) -eq 1 ]; then
    echo "ПРЕДУПРЕЖДЕНИЕ: MemAvailable < 20%"
fi
echo ""

echo "=== 3. Топ-10 процессов по PSS (реальное потребление) ==="
sudo smem -t -k -s pss -r | head -11
echo ""

echo "=== 4. Суммарное потребление по программам ==="
sudo ps_mem | tail -n 11
echo ""

echo "=== 5. Page Cache и Slab ==="
grep -E 'Cached|Slab|SReclaimable|SUnreclaim|PageTables|Dirty' /proc/meminfo
echo ""

echo "=== 6. Swap ==="
free -h | grep Swap
echo ""

echo "=== 7. PSI Memory ==="
cat /proc/pressure/memory
echo ""

echo "=== 8. OOM события за 24 часа ==="
journalctl -k --grep="oom\|Out of memory\|Killed process" --since "24 hours ago" | tail -5
```

## Дополнительная информация

### Типичные ошибки интерпретации

| Ошибка | Реальность | Правильная интерпретация |
| :--- | :--- | :--- |
| "`free` показывает 0 МБ — катастрофа!" | Ядро использует RAM для Page Cache | Смотрите на `available`. Если он высокий — проблемы нет. |
| "RSS процесса = 50 ГБ, но RAM = 32 ГБ" | RSS включает shared memory дважды | Используйте `smem -s pss` для точного измерения. |
| "%MEM суммарно = 150% — утечка!" | %MEM не учитывает shared memory | Используйте `smem` или `ps_mem` для суммарной оценки. |
| "Swap используется — проблема!" | Swap может использоваться для прогрева кэша | Проверьте `si/so` в `vmstat`. Если 0 — проблемы нет. |
| "top показывает 99% used" | top включает Page Cache в used | Смотрите `available` в `free -h` или `buff/cache`. |

### Связь с другими механизмами

- **[Метрики процесса (VSS, RSS, PSS)](./process_memory_metrics.md)** — детальный разбор метрик процесса.
- **[/proc/meminfo — статистика памяти ядра](../../Diagnostics/Memory/proc_meminfo.md)** — расшифровка всех полей.
- **[Кэширование и освобождение памяти](./caching_and_reclaiming.md)** — как ядро управляет Page Cache.
- **[Slab Allocator](./slab_allocator.md)** — память ядра, не учитываемая в RSS процессов.
- **[Диагностика Swap и Page Faults](./swap_diagnostics.md)** — когда swap является проблемой.
- **[Оптимизация памяти](./performance_tuning.md)** — sysctl-параметры и тюнинг.
- **[smem](../../Diagnostics/Memory/smem.md)** — утилита для точного расчета PSS/USS.
