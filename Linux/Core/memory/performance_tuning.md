# Оптимизация и тонкая настройка памяти

## Определения

* **Page Cache** (Страничный кэш): Основной кэш ядра для данных файлов, хранящихся в оперативной памяти. Ядро использует свободную RAM для кэширования чтений с диска, что значительно ускоряет повторные обращения. В современных ядрах Page Cache объединяет функции хранения данных и метаданных файлов. Подробнее: **[Кэширование и освобождение памяти](./caching_and_reclaiming.md)**.
* **Slab Cache** (Кэш слэбов): Память, выделенная ядром под собственные структуры данных (inode, dentry, task_struct, network buffers). Управляется Slab Allocator. Часть Slab (SReclaimable) может быть освобождена под давлением, другая (SUnreclaim) — нет. Подробнее: **[Slab Allocator](./slab_allocator.md)**.
* **Memory Overcommit**: Режим работы ядра, при котором процессам разрешается запрашивать больше виртуальной памяти, чем доступно физически (RAM + Swap).
* **OOM Killer (Out of Memory Killer)**: Механизм ядра, завершающий процессы при критической нехватке памяти. Подробнее: **[Механизм OOM Killer](../processes/oom_killer_mechanism.md)**.
* **MGLRU (Multi-Gen LRU)**: Современный алгоритм управления страницами (ядра 6.1+), заменяющий классический LRU. Группирует страницы по "поколениям" доступа, что снижает нагрузку на CPU до 40% и повышает точность выбора кандидатов на выгрузку.
* **DAMON (Data Access MONitor)**: Фреймворк для мониторинга и проактивного управления памятью. Позволяет реализовывать политики автоматического перемещения "холодных" страниц в медленную память или swap (Tiered Memory).
* **KSM (Kernel Samepage Merging)**: Механизм поиска и объединения идентичных страниц памяти между процессами для экономии RAM.
* **NUMA (Non-Uniform Memory Access)**: Архитектура многопроцессорных систем, где время доступа к памяти зависит от расположения процессора относительно модуля RAM.
* **HugePages**: Механизм использования страниц большого размера (2 МБ или 1 ГБ вместо 4 КБ) для минимизации объема таблиц страниц и снижения промахов TLB.
* **TLB (Translation Lookaside Buffer)**: Аппаратный кэш процессора для быстрого преобразования виртуальных адресов в физические.
* **Dirty Pages (Грязные страницы)**: Модифицированные данные в RAM, ожидающие записи на диск (Writeback).
* **Watermarks (Вотермарки)**: Пороги свободной памяти (`min`, `low`, `high`), при которых ядро начинает фоновое (`kswapd`) или прямое (`direct reclaim`) освобождение памяти.
* **kswapd**: Фоновый поток ядра (один на NUMA-узел), который асинхронно освобождает страницы при достижении вотермарка `low`.
* **Direct Reclaim**: Синхронный режим освобождения памяти, при котором сам процесс, запросивший память, блокируется и выполняет очистку/свопинг. Главная причина задержек (stalls) в работе приложений.
* **Committed_AS** (`/proc/meminfo`): Общий объем памяти, который ядро гарантирует выделить процессам (RAM + Swap). Если `Committed_AS > SwapTotal + RAM`, система работает в режиме overcommit и рискует столкнуться с OOM.
* **Zram**: Виртуальное блочное устройство в RAM со сжатием. Работает как быстрый swap-устройство, исключая дисковый I/O. Используется на бездисковых системах и для ускорения работы с памятью.
* **Zswap**: Механизм кэширования в RAM для страниц, направляемых в swap. Сжимает данные и хранит их в пуле в оперативной памяти. При переполнении пула данные сбрасываются на физический swap. Эффективно снижает I/O на диске.
* **vm.drop_caches**: Механизм принудительной очистки кэшей ядра (Page Cache, dentries, inodes) из оперативной памяти. Используется исключительно для диагностики и аварийных сценариев.

## Основные концепции

### Режимы Overcommit (vm.overcommit_memory)

Ядро поддерживает три стратегии выделения памяти:
1. **`0` (Heuristic)**: Ядро использует эвристику (по умолчанию), чтобы отклонять явно избыточные запросы.
2. **`1` (Always)**: Все запросы на выделение памяти одобряются. Полезно для приложений с разреженными массивами данных (Sparse arrays) или научных вычислений.
3. **`2` (Strict)**: Общий объем выделяемой памяти не может превышать лимит: `SwapTotal + (RAM * overcommit_ratio / 100)`. Рекомендуется для обеспечения предсказуемости и предотвращения хаотичного OOM.

> **Важно:** При `overcommit_memory=0` (по умолчанию) `malloc` может вернуть успех, но последующий доступ к памяти вызовет OOM Killer. Это одна из частых причин внезапных падений процессов без явного дефицита RAM. Для контроля используйте `grep Committed_AS /proc/meminfo`.

### Тюнинг Dirty Pages и Writeback

Параметры `vm.dirty_*` определяют поведение дискового ввода-вывода.
* **`vm.dirty_background_ratio`**: Порог асинхронного сброса. Для быстрых NVMe в 2025 году рекомендуются низкие значения (5–7%).
* **`vm.dirty_ratio`**: Порог блокирующего (синхронного) сброса. Превышение этого значения вызывает задержки приложений (I/O Throttle).

Подробные профили настройки см. в: **[Настройка writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md)**.

### Page Cache vs Slab Cache

Page Cache и Slab Cache — два независимых пула памяти, которые часто путают при диагностике:
* **Page Cache**: Данные файлов (бинарники, библиотеки, mmap-сегменты). Может быть освобожден ядром под давлением (clean pages удаляются, dirty — сбрасываются на диск).
* **Slab Cache**: Структуры данных ядра (inode, dentry, network buffers). Разделяется на `SReclaimable` (очищаемый) и `SUnreclaim` (неочищаемый).

Параметр **`vm.vfs_cache_pressure`** регулирует баланс между очисткой Slab (метаданные) и Page Cache (данные):
* `100` (default): Равный приоритет.
* `< 100` (например, `50`): Ядро менее охотно очищает inode/dentry, полезно для систем с миллионами файлов (объектные хранилища, веб-серверы).
* `> 100` (например, `200`): Агрессивная очистка метаданных (снижает производительность FS, но освобождает RAM).

### Управление вотермарками (2024-2025)

Если система "фризит" при выделении памяти, хотя `MemAvailable` еще велик, требуется тонкая настройка порогов:
* **`vm.watermark_boost_factor = 0`**: **Рекомендация 2025**. Отключение динамического буста вотермарков предотвращает избыточную активность свопа и "swap storms" на ядрах 5.0+.
* **`vm.watermark_scale_factor`**: Увеличивает зазор между `min`, `low` и `high`. Позволяет `kswapd` проснуться раньше. Типовое значение для нагруженных систем: **10–50** (вместо дефолтных 10).
* **`vm.min_free_kbytes`**: Резерв для атомарных аллокаций ядра. На системах с 64 ГБ+ RAM рекомендуется устанавливать **1 ГБ** (`1048576`), чтобы избежать перехода в `direct reclaim`.
* **`vm.vfs_cache_pressure`**: Баланс между очисткой Page Cache и кэшем метаданных. Подробнее: **[Slab Allocator](./slab_allocator.md)**.

### Алгоритм MGLRU (Multi-Gen LRU)

В новых ядрах (>= 6.1) MGLRU должен быть включен для всех типов страниц для снижения CPU overhead.
```bash
# Проверка (должно быть 0x0007 для x86_64)
cat /sys/kernel/mm/lru_gen/enabled
```

### HugePages и THP (Transparent Huge Pages)

#### Проблема TLB
На серверах с сотнями ГБ RAM стандартные страницы по 4 КБ создают огромные таблицы страниц (Pagetables), которые могут занимать гигабайты и не вытесняются в swap. Огромные страницы снижают эти накладные расходы.

| Тип | Плюсы | Минусы |
| :--- | :--- | :--- |
| **Standard HugePages** | Гарантированная память, отсутствие задержек на выделение. | Требует настройки приложения и резервирования при загрузке. |
| **THP** | Прозрачность для приложений. | Возможны задержки (Latency Spikes) из-за работы `khugepaged` и фрагментации. |

**Рекомендация 2025**: Для высоконагруженных СУБД (PostgreSQL, ClickHouse) используйте статические HugePages. Для общих нагрузок используйте THP в режиме `madvise`.

#### THP Defragmentation (khugepaged)

`khugepaged` — фоновый поток ядра, который объединяет стандартные страницы в HugePages. Его активность может вызывать задержки:
```bash
# Просмотр статистики дефрагментации
grep compact_stall /proc/vmstat
# Рост счетчика означает, что процессы ждут завершения дефрагментации.

# Отключение агрессивной дефрагментации THP (ядро >= 5.4)
echo 0 | sudo tee /sys/kernel/mm/transparent_hugepage/khugepaged/defrag
```

**Режимы THP:**
* `always`: Автоматическое объединение для всех процессов. Риск latency spikes.
* `madvise`: Объединение только для областей памяти, помеченных приложением через `madvise()`. **Рекомендуется для большинства рабочих нагрузок.**
* `never`: Полное отключение THP.

### Автоматическая балансировка NUMA

На мультисокетных системах ядро может автоматически перемещать страницы ближе к использующим их ядрам:
* **`kernel.numa_balancing = 1`**: Включает автоматическую балансировку (по умолчанию на большинстве дистрибутивов).
* **`kernel.numa_balancing_scan_size_mb`**: Объем памяти (в МБ) на узел, который сканируется за один проход. Значение по умолчанию — 256 МБ. Увеличение ускоряет балансировку, но повышает нагрузку на CPU.

### Zram и Zswap: сжатие в RAM

**Zram**: Создает виртуальное блочное устройство в RAM со сжатием. Работает как самостоятельный swap. Часто используется на бездисковых системах или для ускорения работы с памятью.

**Zswap**: Механизм кэширования в RAM для страниц, направляемых в swap. Сжимает данные и хранит их в пуле в оперативной памяти. Если пул переполняется, сжатые данные сбрасываются на физический swap. Эффективно снижает I/O на диске.

Настройка Zswap (ядро >= 5.11):
```bash
# Включение через модуль
echo 1 > /sys/module/zswap/parameters/enabled
echo zstd > /sys/module/zswap/parameters/compressor
echo 25 > /sys/module/zswap/parameters/max_pool_percent
```

**Современная настройка (zram-generator):**
В дистрибутивах Fedora, RHEL и Arch используется `zram-generator`.
Конфигурация `/etc/systemd/zram-generator.conf`:
```ini
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
```

### Принудительный сброс кэшей (vm.drop_caches)

Параметр `/proc/sys/vm/drop_caches` позволяет принудительно очистить кэши ядра:
* `1`: Очистка Page Cache.
* `2`: Очистка Slab Cache (dentries и inodes).
* `3`: Очистка всех кэшей.

**Важно:** Это операция исключительно диагностическая. После очистки ядро заново наполняет кэш чтениями с диска, создавая дополнительную нагрузку. Никогда не используйте `drop_caches` в production скриптах по расписанию — это искусственно снижает производительность.

```bash
# Очистка всех кэшей (требует root)
echo 3 | sudo tee /proc/sys/vm/drop_caches

# Временное отключение через sysctl (не рекомендуется)
sudo sysctl -w vm.drop_caches=3
```

### Memory QoS (cgroup v2)

Современный способ защиты памяти для сервисов:
* **`memory.min`**: Жесткая гарантия. Память никогда не будет отобрана ядром (риск немедленного OOM).
* **`memory.low`**: Мягкая гарантия (Best effort protection).
* **`memory.high`**: Порог замедления (throttling) процесса при превышении лимита памяти до убийства через OOM.
* **`memory.max`**: Жесткий лимит. При достижении процесс получает `-ENOMEM` или завершается OOM Killer.
* **`memory.reclaim`**: Позволяет принудительно запустить reclaim страниц для группы.
* **`memory.current`**: Текущее потребление памяти группы (включая Page Cache и Slab).

## Практические сценарии

### Диагностика узких мест

#### Проверка TLB и Page Tables
Если `Pagetables` в `/proc/meminfo` растут выше 1-2 ГБ, это прямой сигнал к переходу на HugePages.
```bash
grep Pagetables /proc/meminfo
```

#### Проверка задержек из-за фрагментации
```bash
cat /proc/vmstat | grep compact_stall
# Рост счетчика означает, что процессы ждут дефрагментации памяти для выделения HugePages.
```

#### Проверка SUnreclaim и Slab Leak
```bash
grep -E 'Slab|SReclaimable|SUnreclaim' /proc/meminfo
# SUnreclaim > 5% RAM = возможна утечка в драйвере ядра
```

#### Проверка Committed_AS и Overcommit
```bash
grep Committed_AS /proc/meminfo
# Если Committed_AS близок к SwapTotal + RAM, система близка к лимиту overcommit
```

### Настройка под нагрузку базы данных

Типовой профиль для PostgreSQL/MySQL на выделенном сервере:
```bash
# Минимизация свопинга
vm.swappiness = 1
# Строгий контроль выделения (защита от OOM)
vm.overcommit_memory = 2
vm.overcommit_ratio = 80
# Тюнинг Dirty Pages для избежания "I/O storms"
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
# Отключение агрессивной дефрагментации HugePages
echo never > /sys/kernel/mm/transparent_hugepage/enabled
```

### Оптимизация NUMA

В мультисокетных системах важно минимизировать задержки доступа к памяти через межпроцессорные шины (QPI/UPI).
* **`kernel.numa_balancing = 1`**: Разрешает ядру автоматически перемещать страницы ближе к использующим их ядрам.
* **`numactl`**: Используется для принудительной привязки процесса к узлу.
* **`numactl --interleave=all`**: Равномерное распределение памяти по всем узлам. Полезно для приложений, не оптимизированных под NUMA.

```bash
# Просмотр топологии
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 4 5 6 7
# → node 0 size: 65536 MB
# → node distances:
# → node   0   1
# →   0:  10  21   ← расстояние 21 = UPI interconnect
# →   1:  21  10

# Запуск процесса строго на узле 0 (CPU и память)
numactl --cpunodebind=0 --membind=0 my_application

# Interleave по всем узлам (для приложений без NUMA-оптимизации)
numactl --interleave=all my_application
```

#### Глубокий анализ NUMA: zone_reclaim_mode и interleave

**`vm.zone_reclaim_mode`** — управляет поведением ядра при нехватке памяти на конкретном NUMA-узле:

| Значение | Поведение | Рекомендация |
| :--- | :--- | :--- |
| `0` (default) | Ядро может выделять память с любого узла (fallback через QPI/UPI). | Рекомендуется для большинства серверов. |
| `1` | Локальный reclaim: ядро пытается освободить память на том же узле, где происходит аллокация. | Только для систем с очень высокой межузловой задержностью и предсказуемой локальностью. |

**Почему `zone_reclaim_mode=1` опасен:** Если на узле N мало свободной памяти, ядро будет агрессивно выгружать страницы в swap на локальном диске узла, даже если на узле N+1 есть достаточно свободной RAM. Это приводит к неоправданному свопингу.

```bash
# Проверка текущего значения
cat /proc/sys/vm/zone_reclaim_mode

# Отключение локального reclaim (рекомендуется)
sudo sysctl -w vm.zone_reclaim_mode=0
```

**`numactl --interleave=all`** — ключевой параметр для large in-memory приложений:

```bash
# Для PostgreSQL / ClickHouse / Redis на NUMA-системе
numactl --interleave=all pg_ctl start

# Эффект: память распределяется round-robin по узлам.
# Средняя латентность доступа: (10 + 21) / 2 = 15.5 нс
# Вместо: 100% доступ к локальному узлу (10 нс) или 100% к удаленному (21 нс)
# Преимущество: отсутствие "hot spot" на одном узле и предсказуемость.
```

**Автоматический NUMA daemon (`numad`):**

```bash
# Проверка наличия
which numad

# Запуск (мониторит и перераспределяет страницы автоматически)
sudo numad

# Статус
sudo numad -s
```

`numad` —фоновый демон, который:
- Мониторит распределение памяти по узлам.
- Автоматически перемещает страницы ближе к использующим их ядрам.
- Рекомендуется для динамических нагрузок, где `numactl --membind` слишком жестко.

**Диагностика NUMA-дисбаланса:**

```bash
# Проверка распределения памяти по узлам
numastat
# → node0: numa_hit = 12345678, numa_miss = 0
# → node1: numa_hit = 9876543, numa_miss = 2345678
# → high numa_miss = процессы на node0 часто обращаются к памяти на node1

# Детализация для конкретного процесса
numastat -p <PID>
# → PID      Node 0     Node 1     Total
# → 1234   512.34 MB   128.00 MB   640.34 MB
# → Если основная память на Node 1, а CPU на Node 0 — дисбаланс

# Проверка расстояний между узлами
numactl --hardware | grep -A 5 "node distances"
# → node distances:
# → node   0   1
# →   0:  10  21   ← 21 = remote access через QPI/UPI (latency 2-5× выше)
# →   1:  21  10
```

**NUMA и контейнеры (Kubernetes Topology Manager):**

В Kubernetes `Topology Manager` координирует CPU, Memory и Device Manager для NUMA-изолированного размещения:

```yaml
# kubelet config
topologyManagerPolicy: "single-numa-node"
topologyManagerScope: "pod"
```

- `single-numa-node`: Под размещается только на одном NUMA-узле (CPU, память и устройства).
- `restricted`: Ресурсы должны быть на пересечении допустимых узлов.
- `best-effort`: Пытается обеспечить NUMA-изоляцию, но не блокирует размещение.

```bash
# Проверка статуса Topology Manager
curl -sk https://localhost:10250/metrics | grep topology_manager
```

### Тюнинг Kernel Samepage Merging (KSM)

Для систем виртуализации (KVM) KSM позволяет значительно повысить плотность размещения ВМ.
```bash
# Включить сканирование
echo 1 > /sys/kernel/mm/ksm/run
# Оптимизация для NUMA (запрет объединения между нодами)
echo 0 > /sys/kernel/mm/ksm/merge_across_nodes
# Ограничение CPU на сканирование (кол-во страниц за проход)
echo 100 > /sys/kernel/mm/ksm/pages_to_scan
```

**Предупреждение:** KSM потребляет дополнительные CPU-ресурсы на сканирование и дедупликацию. На системах с высокой нагрузкой отключите KSM или ограничьте `pages_to_scan`.

### Настройка Memory QoS (cgroup v2)

Пример настройки защиты памяти для критического сервиса через `systemd`:
```bash
# /etc/systemd/system/postgresql.service.d/memory-qos.conf
[Service]
# Гарантировать 8ГБ памяти (ядро не будет ее отбирать)
MemoryMin=8G
# Защищать 12ГБ (ядро будет стараться не отбирать)
MemoryLow=12G
# Замедлять процесс при превышении 30ГБ
MemoryHigh=30G
# Жесткий лимит 32ГБ (OOM при превышении)
MemoryMax=32G
```

#### Принудительный Reclaim через cgroup v2

```bash
# Запустить reclaim 500 МБ для конкретной группы
echo 500M | sudo tee /sys/fs/cgroup/system.slice/postgresql.service/memory.reclaim
```

### vm.drop_caches — Аварийное использование

```bash
# Очистка Page Cache и dentries (только для диагностики!)
echo 3 | sudo tee /proc/sys/vm/drop_caches

# Проверка эффекта
watch -n1 "grep -E 'MemAvailable|Slab|SReclaimable' /proc/meminfo"
```

**Предупреждение:** После очистки производительность упадет до наполнения кэша. Никогда не добавляйте в cron или системные скрипты.

### Zram — Быстрый swap в RAM

Для систем с ограниченным дисковым I/O (SSD, embedded):
```bash
# 1. Создание устройства zram 2 ГБ
echo lz4 | sudo tee /sys/block/zram0/comp_algorithm
echo 2G | sudo tee /sys/block/zram0/disksize

# 2. Форматирование и включение
sudo mkswap /dev/zram0
sudo swapon /dev/zram0 -p 100

# 3. Проверка
zramctl
free -h
```

### Прометеус: алерты на тюнинг памяти

```yaml
groups:
  - name: memory_tuning_alerts
    rules:
      - alert: HighPageTables
        expr: node_memory_PageTables_bytes / node_memory_MemTotal_bytes > 0.02
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий объем таблиц страниц на {{ $labels.instance }}"
          description: "PageTables занимают {{ $value | humanizePercentage }} RAM. Рекомендуется переход на HugePages."

      - alert: HighSlabUnreclaim
        expr: node_memory_SUnreclaim_bytes / node_memory_MemTotal_bytes > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокий SUnreclaim на {{ $labels.instance }}"
          description: "SUnreclaim {{ $value | humanizePercentage }}. Возможна утечка в модуле ядра."

      - alert: HighKSMActivity
        expr: rate(node_ksm_pages_shared[5m]) > 1000
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "Высокая активность KSM на {{ $labels.instance }}"
          description: "KSM объединяет {{ $value }} страниц/сек. Контролируйте CPU usage."

      - alert: DirectReclaimStalls
        expr: rate(node_vmstat_pgsteal_kswapd[5m]) < 100 and rate(node_vmstat_pgscan_kswapd[5m]) > 5000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Direct Reclaim на {{ $labels.instance }}"
          description: "kswapd не справляется, процессы в direct reclaim."
```

### SRE: Ежедневный аудит памяти

```bash
#!/bin/bash
# runbook: daily_memory_audit.sh

echo "=== Общая картина ==="
free -h
echo ""
echo "=== Параметры ядра ==="
sysctl vm.swappiness vm.overcommit_memory vm.dirty_ratio vm.dirty_background_ratio vm.min_free_kbytes vm.watermark_boost_factor
echo ""
echo "=== Page Tables ==="
grep Pagetables /proc/meminfo
echo ""
echo "=== THP статус ==="
cat /sys/kernel/mm/transparent_hugepage/enabled
echo ""
echo "=== MGLRU статус ==="
cat /sys/kernel/mm/lru_gen/enabled
echo ""
echo "=== Slab ==="
grep -E 'Slab|SReclaimable|SUnreclaim' /proc/meminfo
echo ""
echo "=== NUMA топология ==="
numactl --hardware | head -n 10
echo ""
echo "=== PSI Memory ==="
cat /proc/pressure/memory
echo ""
echo "=== Топ процессов по RSS ==="
ps aux --sort=-%mem | head -n 11
echo ""
echo "=== Последние OOM события ==="
journalctl -k --grep="oom\|Out of memory\|Killed process" --since "24 hours ago" | tail -20
```

### SRE: Runbook — Memory Pressure

**Триазна:**
1. `vmstat 1` → `si`/`so` > 0 постоянный, `wa` > 20%, `free` близок к 0.
2. `cat /proc/pressure/memory` → `full avg10 > 5%`.
3. `free -h` → `available` < 10% RAM.

**Действия:**
1. **Идентификация виновника**: `ps aux --sort=-%mem | head` → процесс с максимальным RSS.
2. **Проверка cgroup**: `systemd-cgtop` или `cat /sys/fs/cgroup/<service>/memory.current`.
3. **Краткосрочное вмешательство**: Увеличение `memory.high` или `memory.max` для критичного сервиса.
4. **Снижение swappiness**: `sudo sysctl -w vm.swappiness=0` (временно).
5. **Очистка кэша** (аварийно): `sudo sysctl -w vm.drop_caches=3`.
6. **Постоянное устранение**: Увеличить RAM, настроить cgroup-лимиты, отключить THP, включить zram.

## Дополнительная информация

### Мониторинг давления (PSI)

Для оценки эффективности тюнинга используйте метрики **PSI**. Они показывают реальное время простоя процессов из-за ожидания памяти. Если `full avg10 > 5%`, тюнинг вотермарков или увеличение RAM неизбежны.
Подробнее: **[Pressure Stall Information (PSI)](../kernel/psi.md)**.

### Профилирование памяти (perf и bpftrace)

Для идентификации функций, вызывающих Major Faults:
```bash
# Сбор статистики по Major Faults
sudo perf record -e major-faults -a -g -- sleep 10
sudo perf report

# Гистограмма задержки Page Faults (eBPF)
sudo bpftrace -e 'software:page-faults:1 { @start[tid] = nsecs; }
    software:page-faults:0 /@start[tid]/ { @us = hist((nsecs - @start[tid]) / 1000); delete(@start[tid]); }'
```

### См. также
* **[Управление Swap](./swap_management.md)** — глубокая настройка подкачки, Zram и Zswap.
* **[Диагностика Swap и Page Faults](./swap_diagnostics.md)** — поиск причин задержек, дифференциальная диагностика.
* **[Диагностика /proc/meminfo](../../Diagnostics/Memory/proc_meminfo.md)** — расшифровка всех метрик памяти.
* **[Кэширование и освобождение памяти](./caching_and_reclaiming.md)** — Page Cache, kswapd, Direct Reclaim, Watermark Boosting.
* **[Slab Allocator](./slab_allocator.md)** — память ядра, не учитываемая в RSS процессов.
* **[Настройка writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md)** — профили tuning для NVMe и СУБД.
* **[Pressure Stall Information (PSI)](../kernel/psi.md)** — мониторинг давления на память, I/O и CPU.
* **[Справочник sysctl-параметров памяти](./sysctl_memory_reference.md)** — единый reference по всем параметрам vm.swappiness, dirty_ratio, overcommit и др.
* **[Фактическое потребление vs Reporting](./memory_reporting_vs_reality.md)** — разница между free, top, smem; почему free всегда показывает мало.
