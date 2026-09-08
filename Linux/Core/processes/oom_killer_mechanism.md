# Механизм OOM Killer в Linux

## Определения

**OOM Killer (Out-of-Memory Killer)** — это защитный механизм ядра Linux, который активируется при критической нехватке оперативной памяти и невозможности выделения новых страниц. Его задача — предотвратить крах всей системы (Kernel Panic) путем принудительного завершения процессов для освобождения ресурсов.

**Memory Overcommit** — стратегия ядра, позволяющая процессам выделять (allocate) больше виртуальной памяти, чем фактически доступно в физической RAM и Swap. OOM Killer является «последним рубежом» при использовании агрессивных политик Overcommit.

**oom_score** — числовой рейтинг «плохости» процесса (от 0 до 1000). Чем выше значение, тем вероятнее, что процесс будет выбран в качестве жертвы.

**OOM Reaper** — специальный поток ядра (введен в v4.6), который асинхронно освобождает память убитого процесса. Это решает проблему «зависших зомби», когда процесс уже получил SIGKILL, но не может освободить память, так как заблокирован (например, в состоянии D).

**Watermarks (Водяные знаки)** — пороговые значения свободной памяти в зонах (min, low, high), управляющие фоновым освобождением страниц (kswapd) и прямым reclaim.

**Direct Reclaim** — попытка ядра освободить память в контексте того процесса, который запросил страницу. Блокирует процесс и может привести к состоянию D.

**GFP Flags (Get Free Pages flags)** — флаги, передаваемые аллокатору памяти (например, `GFP_KERNEL`, `GFP_ATOMIC`). Определяют поведение ядра при нехватке памяти: может ли процесс ждать (sleep), может ли ядро использовать swap, и можно ли вызвать OOM.

## Основные концепции

### Жизненный цикл срабатывания OOM

Процесс активации OOM Killer — это многоступенчатый алгоритм защиты:

1.  **Page Fault / Allocation Failure:** Процесс запрашивает память (через `malloc` -> `brk`/`mmap` или при page fault), но ядро не находит свободных страниц.
2.  **GFP Mask Check:** Ядро анализирует флаги `gfp_mask`. Если флаг `__GFP_NOFAIL` установлен, ядро будет ждать вечно. Если `GFP_ATOMIC` — не может уснуть, поэтому прямой OOM.
3.  **Direct Reclaim / kswapd:** Ядро пытается освободить память: очищает Page Cache, сбрасывает грязные страницы, вытесняет страницы в Swap.
4.  **Compaction:** Если memory fragmentation высока, ядро пытается дефрагментировать зоны (compaction), чтобы выделить high-order страницы.
5.  **Check Overcommit:** Если очистка не помогла, ядро проверяет настройки `vm.overcommit_memory`. Если лимит превышен — инициируется OOM.
6.  **Badness Calculation:** Функция `oom_badness()` сканирует дерево задач и вычисляет рейтинг каждого процесса.
7.  **OOM Notifier:** Ядро вызывает registered notifier chains (например, для cgroups или subsystem-specific handlers).
8.  **Signal Delivery:** Выбранному процессу отправляется сигнал **SIGKILL (9)**.
9.  **Reaping:** OOM Reaper немедленно начинает «отбирать» страницы памяти у процесса, помечая их как свободные, даже до того, как процесс окончательно завершится.

### Память и зоны (Zones)

Физическая память в Linux разделена на зоны из-за аппаратных ограничений архитектуры x86/x86_64:

| Зона | Аппаратное ограничение | Назначение |
| :--- | :--- | :--- |
| **ZONE_DMA** | Первые 16 МБ на x86 | Устройства с ограниченным DMA (старые карты). |
| **ZONE_DMA32** | Первые 4 ГБ на x86_64 | 32-битные устройства, нуждающиеся в адресации ниже 4G. |
| **ZONE_NORMAL** | Обычная RAM | Стандартное размещение страниц ядра и пользовательских процессов. |
| **ZONE_HIGHMEM** | > 896 МБ на 32-битном x86 | Страницы, не permanently mapped в kernel space. На x86_64 совмещена с NORMAL. |
| **ZONE_MOVABLE** | Настраиваемая | Страницы, которые можно мигрировать (для уменьшения фрагментации). |

**Почему это важно для OOM:** OOM Killer выбирает жертву по всей системе, но аллокатор работает в пределах конкретной зоны. Если `ZONE_DMA` исчерпана, ядро не может использовать память из `ZONE_NORMAL` для DMA-устройств, что может спровоцировать OOM даже при наличии свободной RAM в других зонах.

### Водяные знаки (Watermarks) и фоновый reclaim

Ядро поддерживает три порога для каждой зоны памяти:

- **`min` (min_free_kbytes):** Критический уровень. При достижении этого значения активируется **direct reclaim** — процессы начинают освобождать страницы своими силами, что блокирует их и снижает производительность.
- **`low`:** Порог пробуждения **kswapd** — фонового потока ядра, который освобождает страницы без блокировки процессов.
- **`high`:** Порог остановки kswapd. Когда свободная память возвращается выше этого уровня, фоновый reclaim прекращается.

**Настройка watermarks:**
```bash
# Просмотр текущих watermarks для зон
cat /proc/zoneinfo | grep -A4 'Node 0'
# →   min   low   high   managed   free   ...
# →   4537  5671  6805   8192000   123456

# Прямая настройка (требует root)
echo 65536 > /proc/sys/vm/min_free_kbytes
```

**Влияние на OOM:** Агрессивный `min_free_kbytes` резервирует большой запас, уменьшая доступную для процессов память и увеличивая частоту reclaim. Слишком низкий порог — приводит к внезапным OOM, когда процессы используют всю память до `min`.

### Алгоритм вычисления oom_score (oom_badness)

Ядро стремится минимизировать ущерб, выбирая процессы по следующим критериям:

- **Потребление памяти:** Базовое значение — это процент использования физической RAM (RSS) + Swap относительно общей доступной памяти системы.
- **CPU time:** Процессы, потребившие много CPU времени, имеют более высокий приоритет к сохранению (lower badness).
- **Приоритет (nice):** Более низкий nice (более высокий приоритет) снижает вероятность убийства.
- **Корректировка (`oom_score_adj`):** Значение из `/proc/PID/oom_score_adj` (от -1000 до 1000) прибавляется к базовому рейтингу.
- **Влияние Cgroups v2:** В современных системах OOM Killer может учитывать иерархию контрольных групп. Если лимит превышен внутри cgroup, ядро сначала попытается убить процесс именно внутри этой группы.
- **Иммунитет:**
    - **PID 1 (init/systemd):** Обладает абсолютным иммунитетом.
    - **Kernel Threads:** Никогда не выбираются в качестве жертвы.
    - **Значение -1000:** Процесс полностью исключается из алгоритма выбора.

### Влияние cgroups v2 на OOM

В cgroups v2 (ядро 5.x+, systemd) механизм OOM работает на двух уровнях:

1.  **Cgroup-local OOM:** Срабатывает при превышении `memory.max`. Жертва выбирается ТОЛЬКО внутри этой контрольной группы.
2.  **System-wide OOM:** Срабатывает при исчерпании всей доступной памяти хоста. Ядро сканирует все процессы системы, включая те, что находятся в cgroups.

**Ключевые параметры cgroups v2:**

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `memory.min` | Hard guarantee | Память, которую ОС **никогда** не заберет у группы. |
| `memory.low` | Best-effort | ОС старается не трогать эту память при pressure. |
| `memory.high` | Throttle | Мягкий лимит. При превышении процессы замедляются (reclaim). |
| `memory.max` | Hard limit | Абсолютный потолок. Превышение -> Immediate OOM. |
| `memory.oom.group` | Boolean | Групповое завершение: при OOM в любом процессе убивается ВСЯ группа. |

### tmpfs, HugePages и скрытые потребители

Не все потребители памяти видны в стандартных утилитах (`top`, `htop`):

- **tmpfs / shm:** Память в `/dev/shm` и других tmpfs-монтированиях учитывается как shared file-backed (shmem). При переполнении tmpfs может триггерить OOM, хотя `free -h` показывает свободную RAM.
- **HugePages:** Если выделены статические HugePages, они резервируются в момент загрузки и не участвуют в обычном reclaim. Однако динамические HugePages (Transparent Huge Pages, THP) потребляют дополнительную память и могут усугубить фрагментацию.
- **Page Tables:** На системах с тысячами процессов таблицы страниц (Page Tables) могут занимать гигабайты. Учитываются в `/proc/meminfo` как `PageTables`.
- **Kernel Slab:** Кэши структур данных ядра (inodes, dentries, network buffers). Учитываются как `Slab` в `/proc/meminfo`.

### Pressure Stall Information (PSI) и современный OOM

Начиная с ядра 4.20, механизм **PSI** позволяет оценивать «давление» на память в реальном времени. Это привело к появлению **systemd-oomd** — пользовательского демона, который:
- Мониторит файлы в `/proc/pressure/memory`.
- Убивает процессы превентивно, если система тратит слишком много времени на ожидание памяти (Thrashing).
- Работает на уровне cgroups, что делает его гораздо более эффективным для серверов.

## Практические сценарии

### Анализ текущих кандидатов на вылет

Скрипт для быстрого просмотра рейтингов всех процессов:

```bash
# Топ-10 процессов по вероятности быть убитыми OOM
printf "%-10s %-10s %s\n" "SCORE" "PID" "COMMAND"
for p in /proc/[0-9]*; do
    pid=${p##*/}
    [ -r $p/oom_score ] && printf "%-10s %-10s %s\n" \
        "$(cat $p/oom_score)" "$pid" "$(cat $p/comm)"
done 2>/dev/null | sort -nr | head -10
```

### Декодирование записи в dmesg

При срабатывании OOM ядро оставляет детальный отчет. Пример:
`Out of memory: Killed process 1234 (java) total-vm:8GB, anon-rss:4GB, file-rss:0kB`
- **anon-rss:** Память, выделенная самим приложением (динамические структуры, куча). Именно её OOM Killer пытается освободить.
- **file-rss:** Кэшированные файлы. Если это значение велико, возможно, проблема не в приложении, а в интенсивном I/O.
- **shmem-rss:** Память из tmpfs и разделяемых сегментов. Часто игнорируется, но может быть основным потребителем.

### Защита критичного процесса

Для предотвращения завершения важных служб (например, базы данных) можно вручную настроить их приоритет:

* **Иммунитет**: Установка значения **`-1000`** в `/proc/PID/oom_score_adj` полностью исключает процесс из кандидатов на завершение.
* **Снижение риска**: Установка отрицательных значений (например, `-500`) пропорционально снижает вероятность убийства процесса.

```bash
# Сделать процесс "неприкасаемым" (требует root)
echo -1000 > /proc/$(pidof my_service)/oom_score_adj
```

**Примечание:** Kubernetes использует этот механизм для управления QoS классами (`Guaranteed` поды получают `-997`). Для systemd-сервисов предпочтительнее использовать `OOMScoreAdjust=` в unit-файле (см. [Управление OOM Killer](./oom_killer_management.md)).

### Stress-тестирование поведения OOM

Безопасная проверка реакции системы на нехватку памяти:

```bash
# Установка утилиты (RHEL/Debian/Ubuntu)
sudo apt install stress-ng   # Debian/Ubuntu
sudo dnf install stress-ng   # RHEL/Fedora

# Тест: занять 90% доступной RAM в фоне
stress-ng --vm 1 --vm-bytes 90% --vm-keep --timeout 60 &

# Параллельный мониторинг
watch -n1 'free -h; echo "---"; cat /proc/pressure/memory; echo "---"; vmstat 1 3'

# В другом окне: проверка логов в реальном времени
dmesg -w | grep -i "out of memory\|oom\|killed process"
```

**Ожидаемый результат:** Через 30–60 секунд `stress-ng` будет убит OOM Killer (exit code 137). Если система зависла — проверяйте настройки `vm.panic_on_oom` и `vm.oom_dump_tasks`.

### Анализ фрагментации и зон памяти

При `order > 0` в логе OOM ядро не смогло найти непрерывный блок страниц:

```bash
# Состояние зон и фрагментация
cat /proc/zoneinfo | grep -E 'Node|free|min|low|high|fragmentation'

# Детализация фрагментации по порядкам выделения (buddyinfo)
cat /proc/buddyinfo
# → Node 0, zone   Normal  1234  567  123  45  12  3  0  0  0
# Каждый столбец: количество свободных блоков размера 2^order страниц.
# Если столбцы > 0 пусты при наличии free pages — фрагментация критична.

# Проверка настройки compaction
grep compact_struc /proc/vmstat
cat /proc/sys/vm/compaction_proactiveness
```

**Решение фрагментации:**
- Включение `CONFIG_COMPACTION` и `CONFIG_MIGRATION` в ядре (по умолчанию включены).
- Использование `movablecore` boot parameter для увеличения ZONE_MOVABLE.
- Нагрузочное тестирование (boot-time compaction) или `echo 1 > /proc/sys/vm/compact_memory`.

### Взаимодействие с Swap, zswap и zram

Swap отодвигает момент срабатывания OOM, но добавляет латентность:

```bash
# Проверка конфигурации swap
swapon --show
cat /proc/swaps

# Настройка swappiness (0–100)
# 0 = минимизировать свопинг, 100 = агрессивно использовать swap
cat /proc/sys/vm/swappiness
sysctl -w vm.swappiness=10

# Мониторинг swap-активности
vmstat 1 10
# si (swap in) и so (swap out) не должны быть постоянными > 0 на production.
```

**zswap** (compressed swap cache в RAM) и **zram** (сжатый блочное устройство в RAM):
- zswap хранит сжатые страницы в RAM, откладывая реальный swap на диск. При нехватке памяти zswap может вытеснять свои собственные страницы, что выглядит как swap-активность без реального диска.
- zram создает виртуальный блоковый устройств в RAM. Полезно на устройствах с медленным/отсутствующим физическим swap.

```bash
# Проверка zswap
grep . /sys/module/zswap/parameters/* 2>/dev/null
cat /sys/block/zram0/disk_usage_size 2>/dev/null

# Включение zswap (если отключено)
echo 1 > /sys/module/zswap/parameters/enabled
```

### Восстановление после OOM (Post-Incident Checklist)

После срабатывания OOM Killer SRE должен выполнить постмортем:

```bash
# 1. Определить жертву и триггер
dmesg -T | grep -E "oom|killed process" | tail -20

# 2. Проверить, сервис ли перезапустился
systemctl status my_service
journalctl -u my_service --since "10 minutes ago"

# 3. Проверить отсутствие "зомби"-ресурсов
ps aux | grep '<defunct>'
cat /sys/fs/cgroup/system.slice/my_service.service/memory.current

# 4. Проверить swap и overcommit
free -h
cat /proc/sys/vm/overcommit_memory
grep -E 'Commit|Swap' /proc/meminfo

# 5. Настроить защиту, чтобы предотвратить повторение
# Вариант A: systemd unit
systemctl edit my_service
# → [Service]
# → OOMScoreAdjust=-500
# → OOMPolicy=restart

# Вариант B: sysctl (осторожно!)
sysctl -w vm.overcommit_memory=2
sysctl -w vm.overcommit_ratio=80
```

### Мониторинг приближающегося OOM

Простой скрипт для мониторинга и алертинга:

```bash
#!/bin/bash
# /usr/local/bin/oom_watchdog.sh
# Требования: bc, mail/sendmail или webhook

THRESHOLD_MEM_AVAILABLE_PCT=10
THRESHOLD_SWAP_FREE_PCT=15
THRESHOLD_PSI_FULL=5.0

check_memory() {
    local mem_available=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    local mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo)
    local pct=$(echo "scale=1; 100 * $mem_available / $mem_total" | bc)
    if (( $(echo "$pct < $THRESHOLD_MEM_AVAILABLE_PCT" | bc -l) )); then
        echo "CRITICAL: Available memory ${pct}% < ${THRESHOLD_MEM_AVAILABLE_PCT}%"
        return 1
    fi
    return 0
}

check_swap() {
    local swap_free=$(awk '/SwapFree/{print $2}' /proc/meminfo)
    local swap_total=$(awk '/SwapTotal/{print $2}' /proc/meminfo)
    [ "$swap_total" -eq 0 ] && return 0
    local pct=$(echo "scale=1; 100 * $swap_free / $swap_total" | bc)
    if (( $(echo "$pct < $THRESHOLD_SWAP_FREE_PCT" | bc -l) )); then
        echo "CRITICAL: Free swap ${pct}% < ${THRESHOLD_SWAP_FREE_PCT}%"
        return 1
    fi
    return 0
}

check_psi() {
    [ ! -f /proc/pressure/memory ] && return 0
    local full=$(awk '/^full/{gsub(/avg10=/,"",$2); split($2,a," "); print a[1]}' /proc/pressure/memory)
    if (( $(echo "$full > $THRESHOLD_PSI_FULL" | bc -l) )); then
        echo "CRITICAL: Memory PSI full=${full}% > ${THRESHOLD_PSI_FULL}%"
        return 1
    fi
    return 0
}

if ! check_memory || ! check_swap || ! check_psi; then
    echo "ALERT: $(hostname) - $(date)" | systemd-send-email --admin
    # или webhook: curl -X POST ...
fi
```

Добавление в cron (проверка каждые 2 минуты):
```bash
*/2 * * * * root /usr/local/bin/oom_watchdog.sh >> /var/log/oom_watchdog.log 2>&1
```

### tmpfs и разделяемая память

`tmpfs` (включая `/dev/shm`) использует RAM и Swap. При заполнении tmpfs OOM Killer может убить процессы, даже если `free -h` показывает достаточно памяти:

```bash
# Проверка использования tmpfs
df -h /dev/shm /run /tmp

# Поиск процессов, потребляющих shmem
sudo smem -w | grep shmem
# или
sudo lsof /dev/shm | tail

# Ограничение размера tmpfs
mount -o remount,size=512M /dev/shm

# Постоянная настройка в /etc/fstab
tmpfs /dev/shm tmpfs defaults,size=512M 0 0
```

## Дополнительная информация

### OOM Reaper и состояние D

Если процесс завис в **Uninterruptible Sleep (состояние D)** из-за проблем с диском (например, зависшая NFS-шара), старые ядра не могли освободить его память после SIGKILL. **OOM Reaper** решает это, проходя по таблицам страниц процесса и освобождая их, не дожидаясь пробуждения процесса. Тем не менее, сам процесс останется в таблице PID в состоянии зомби до тех пор, пока ресурс не освободится.

### Коды возврата

Процесс, убитый OOM Killer, завершается с кодом **137** (128 + 9). В контейнерах и Kubernetes это основной индикатор для статуса `OOMKilled`.

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **OOM при наличии свободного cache** | `vm.min_free_kbytes` слишком высокий или фрагментация | Уменьшение `min_free_kbytes`, проверка `buddyinfo` |
| **Медленный OOM (Freeze)** | Медленный swap (HDD), `vm.swappiness=100` | Переход на SSD, zswap/zram, уменьшение swappiness |
| **Системный panic вместо OOM** | `vm.panic_on_oom=1` | См. [Управление OOM Killer](./oom_killer_management.md) |
| **Java-процесс убит, несмотря на -1000** | OOM в cgroup (Docker/K8s), а не системный | Проверка `memory.max` и `oom_kill` в cgroup events |
| **Silent OOM в контейнере** | cgroups v2 убивает дочерний процесс, PID 1 жив | Проверка `memory.events` внутри контейнера |

### См. также

- [**Диагностика OOM Killer**](./oom_killer_diagnostics.md) — пошаговый разбор логов и bpftrace.
- [**Управление OOM Killer**](./oom_killer_management.md) — настройка `oom_score_adj` и systemd-oomd.
- [**Давление на ресурсы (PSI)**](../kernel/psi.md) — превентивный мониторинг и метрики.
