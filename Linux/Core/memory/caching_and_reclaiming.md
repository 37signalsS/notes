# Кэширование и освобождение памяти в Linux

## Определения

* **Page Cache** (Страничный кэш): Основной механизм ядра для кэширования данных файлов в оперативной памяти. В современных ядрах (2.4+) он полностью объединяет в себе функции хранения данных и метаданных файлов.
* **Buffer Cache** (Буферный кэш): Исторически отдельный кэш для блоков диска. В современных ядрах является подмножеством Page Cache. Использует структуры `buffer_head` для описания соответствия страниц памяти физическим блокам диска.
* **Folio**: Современная абстракция над страницами (введена в ядре 5.16), позволяющая ядру управлять группой физически смежных страниц как единым целым. Это снижает накладные расходы на управление списками LRU, уменьшает количество блокировок и ускоряет работу с быстрыми NVMe за счет использования "больших страниц" (Large Folios).
* **iomap**: Новый фреймворк для выполнения I/O операций, заменяющий устаревшие `buffer_head` для современных файловых систем (XFS, ext4, Btrfs). Обеспечивает прямую связь между Page Cache и дисковыми адресами без промежуточных структур данных.
* **Page Reclaim** (Освобождение страниц): Процесс вытеснения страниц из памяти (сброс "грязных" на диск или удаление "чистых") для удовлетворения новых запросов на аллокацию.
* **kswapd**: Фоновый поток ядра (один на каждый NUMA-узел), который выполняет освобождение памяти при достижении определенных порогов (водяных знаков).
* **Direct Reclaim** (Прямое освобождение): Синхронный режим, в котором процесс, запросивший память, блокируется и сам выполняет освобождение страниц, так как `kswapd` не справляется. Это главная причина задержек (stalls) в работе приложений.
* **Memory Watermarks** (Водяные знаки): Пороги свободной памяти (`min`, `low`, `high`), определяющие поведение подсистемы управления памятью.
* **LRU (Least Recently Used)**: Классический алгоритм выбора страниц для вытеснения, основанный на времени последнего обращения. Использует два списка: Active и Inactive.
* **MGLRU (Multi-Gen LRU)**: Многопоколенный алгоритм LRU (ядра 6.1+). Заменяет бинарные списки Active/Inactive на набор "поколений", что значительно точнее отражает реальную активность использования памяти и снижает нагрузку на CPU.
* **Refault**: Ситуация, когда страница была недавно вытеснена, но потребовалась снова. Указывает на слишком агрессивное вытеснение или нехватку RAM (**Thrashing**).
* **Shrinkers**: Механизмы обратного вызова (callbacks) в ядре, позволяющие подсистемам (например, Slab-аллокатору) освобождать свою память (кэши инод, дендриев) при дефиците ресурсов.
* **Zones (Зоны памяти)**: Логическое разделение физической RAM на диапазоны адресов. На x86_64: `ZONE_DMA` (0–16 МБ), `ZONE_DMA32` (16 МБ–4 ГБ), `ZONE_NORMAL` (4 ГБ–значение зависит от ядра), `ZONE_HIGHMEM` (>896 МБ на 32-битных системах; на x86_64 с CONFIG_HIGHMEM64G — до 64 ГБ). Каждая зона имеет собственные водяные знаки и списки LRU. Reclaim происходит независимо в каждой зоне.
* **Compaction (Компакция)**: Процесс дефрагментации памяти, при котором ядро объединяет разрозненные страницы в более крупные contiguous-блоки для успешного выделения HugePages или Order-1+ страниц. Ведет к `compact_stall` и `compact_success` в `/proc/vmstat`. Проактивная компакция (`/proc/sys/vm/compact_memory`) запускается ядром фоном.
* **Readahead (Упреждающее чтение)**: Механизм ядра, который заранее загружает данные в Page Cache при последовательном доступе к файлу. Размер управляется через `/sys/block/<dev>/queue/read_ahead_kb` (по умолчанию 128 КБ). Для случайного I/O (СУБД) readahead следует отключать.

## Основные концепции

### Экономика памяти в Linux

Ядро Linux следует принципу: **"Свободная память — это потраченная впустую память"**. Поэтому оно стремится занять всю доступную RAM страничным кэшем. 
Важно различать метрики в выводе `free -h`:
- **`free`**: Память, которая вообще не используется (абсолютно пустая).
- **`available`**: Реальный объем памяти, доступный приложениям. Включает в себя кэши и Slab (SReclaimable) за вычетом "грязных" страниц и минимальных резервов ядра.

### Единая архитектура кэширования (Unification)

В современных системах Page Cache и Buffer Cache интегрированы:
1. **Файловый доступ**: При чтении файла через `read()` данные попадают в Page Cache.
2. **Метаданные и сырые блоки**: При чтении метаданных (иноды, суперблоки) или работе с `/dev/sda` ядро также использует страницы Page Cache, но помечает их через дескрипторы блоков (`buffer_head`).

Ядро постепенно мигрирует от `buffer_head` к фреймворку **iomap** и **Folios**:
- **Folios** позволяют управлять 2МБ и более крупными блоками данных как единым целым, что критично для производительности на NVMe с пропускной способностью 10+ ГБ/с.
- **DAX (Direct Access)**: Для систем с NVDIMM (энергонезависимой памятью) Linux позволяет приложениям работать с памятью напрямую, полностью исключая Page Cache и накладные расходы на копирование.

### Алгоритмы выбора кандидатов (Reclaim Algorithms)

#### 1. Классический LRU (Active/Inactive Lists)
Ядро поддерживает два списка для каждой зоны памяти (Anonymous и File-backed):
* **Active List**: "Горячие" страницы.
* **Inactive List**: Кандидаты на вытеснение.
**Механизм "второго шанса"**: При обращении к странице в Inactive списке она помечается как `referenced`. При втором обращении она перемещается в Active. Если Active список переполняется, страницы сбрасываются в Inactive, теряя статус `referenced`.

#### 2. MGLRU (Multi-Gen LRU)
Вместо двух списков используется набор поколений (generations). Это позволяет ядру:
- **Снижать CPU overhead**: Тратить до 40% меньше ресурсов на сканирование памяти.
- **PSI Feedback**: MGLRU динамически ускоряет вытеснение страниц, если метрики PSI показывают рост давления на память.
- **KVM Secondary MMU Aging**: С ядра 6.11 MGLRU эффективно отслеживает использование памяти внутри виртуальных машин через "теневые" таблицы страниц (Secondary MMU), минимизируя блокировки MMU и повышая производительность виртуализации.
- **Working Set Protection**: MGLRU лучше защищает рабочее множество приложения от вымывания однократными операциями чтения (например, бэкапами).

### Приоритеты: Anonymous vs File-backed

При дефиците RAM ядро балансирует между очисткой кэша файлов (которые можно просто отбросить) и выгрузкой анонимной памяти в Swap.
* **`vm.swappiness`**: Регулирует агрессивность свопинга. В современных ядрах диапазон расширен до **200**.
* **Fractional Cost Model**: Ядро рассчитывает количество страниц для сканирования из каждого списка на основе `swappiness` и уровня рефаултов. Если `workingset_refault` для файлов высок, ядро поймет, что кэш файлов "горячий", и начнет агрессивнее вытеснять анонимные страницы в swap.

### Механизмы освобождения памяти

Освобождение памяти запускается, когда количество свободных страниц падает ниже водяных знаков.

1. **Фоновое освобождение (kswapd)**:
   - Просыпается при `free < low`.
   - Плавно вытесняет страницы, пока `free` не достигнет `high`.
   - Работает асинхронно, не вызывая задержек в приложении.
   
2. **Прямое освобождение (Direct Reclaim)**:
   - Начинается при `free < min`.
   - Процесс блокируется (stall) и сам занимается поиском и освобождением страниц.
   - Вызывает резкие всплески `avg10` в PSI и деградацию производительности.

3. **Проактивное освобождение (Cgroup v2)**:
   - Через интерфейс `memory.reclaim` в cgroup v2 можно принудительно заставить ядро освободить заданный объем памяти для группы процессов, не дожидаясь системного дефицита.

### Зоны памяти и per-zone reclaim

Физическая RAM делится на зоны (Zones), каждая из которых обслуживает определенный диапазон адресов и имеет собственные водяные знаки. На x86_64:
- **ZONE_DMA** (0–16 МБ): Для устройств, не поддерживающих 32-битную адресацию (ISA, ранние PCI).
- **ZONE_DMA32** (16 МБ–4 ГБ): Для 32-битных DMA-устройств (сетевые карты, RAID-контроллеры).
- **ZONE_NORMAL** (4 ГБ–порог): Основная зона для ядра и пользовательских пространств. На x86_64 с 64-битным ядром начинается с 4 ГБ.
- **ZONE_HIGHMEM** (на 32-битных системах >896 МБ): Память, не permanently mapped в ядро. На x86_64 с `CONFIG_HIGHMEM64G` эта зона отсутствует, так как ядро может отображать всю RAM.

**Важность для reclaim:**
- Если `ZONE_NORMAL` заполнена, но `ZONE_DMA` свободна, ядро **не** может переместить страницы между зонами для reclaim. Это называется **зональным дефицитом (zone depletion)**.
- `kswapd` работает отдельно для каждой зоны. Если в какой-то зоне `free < low`, просыпается соответствующий `kswapd`.
- Параметр `vm.min_free_kbytes` распределяется пропорционально размеру зон.

**Диагностика зон:**
```bash
# Просмотр всех зон и их watermarks
cat /proc/zoneinfo | grep -E "Node|free|min|low|high|protection|scanned"
# → node 0, zone   Normal
#   pages free     12345
#          min      1000
#          low      1250
#          high     1500
#   pages scanned  5000 (kswapd активно сканирует)

# Если для Normal free ≈ min, а для DMA free = high — проблема в Normal, а не в системе в целом
```

### Компакция памяти (Memory Compaction)

Когда ядро не может выделить contiguous-блоки нужного размера (например, для THP), оно запускает компактацию:
- **Проактивная компакция**: Фоновая задача (`kcompactd`) перемещает страницы заранее, чтобы подготовить contiguous-блоки.
- **Реактивная компакция**: Запускается при запросе Order-1+ страниц, если `compact_blocks` не достигли цели.

**Ключевые счетчики в `/proc/vmstat`:**
- `compact_stall`: Количество раз, когда процесс ждал завершения компакции.
- `compact_success`: Успешные компакции.
- `compact_fail`: Неудачи из-за фрагментации или недостатка памяти.

```bash
# Анализ компакции
grep -E "compact_stall|compact_success|compact_fail" /proc/vmstat
# → compact_stall       1234
# → compact_success     1200
# → compact_fail         34
# → успех > 95% = норма, постоянные fail = проблемная фрагментация
```

**Взаимодействие с reclaim:**
Компакция и reclaim часто конкурируют за ресурсы CPU. При включенном THP (`always` или `madvise`) ядро может тратить до 20% CPU на компакцию и `khugepaged`.

### Упреждающее чтение (Readahead)

При последовательном чтении файла ядро предзагружает следующие блоки в Page Cache. Это снижает latency, но может заполнять RAM "холодными" данными, если прогноз ошибочен.

**Параметры:**
- `/sys/block/<dev>/queue/read_ahead_kb`: Глобальный readahead для блочного устройства (по умолчанию 128 КБ).
- `fadvise64(..., POSIX_FADV_RANDOM)`: Приложение может отключить readahead для файла.
- `blockdev --setra 0 /dev/sda`: Отключение readahead на уровне устройства.

**Когда отключать:**
- СУБД (PostgreSQL, MySQL, ClickHouse) с собственным буферным менеджером.
- Файлы с случайным доступом (логи, объектные хранилища).
- Виртуальные машины (гипервизор сам управляет caching).

```bash
# Проверка текущего readahead
cat /sys/block/sda/queue/read_ahead_kb
# → 128

# Отключение для SSD/HDD со случайной нагрузкой
echo 0 | sudo tee /sys/block/sda/queue/read_ahead_kb

# Для NVMe с последовательными нагрузками можно оставить 128 или увеличить до 256
echo 256 | sudo tee /sys/block/nvme0n1/queue/read_ahead_kb
```

### Приоритеты reclaim (Priority Levels)

Ядро использует 12 уровней приоритета (0–12) при сканировании страниц:
- **DEF_PRIORITY (12)**: Обычный фон (kswapd).
- **0 (критический)**: При `free < min` или когда `scanned > swappiness * файловые_страницы`.

Приоритет влияет на то, сколько страниц ядро сканирует из каждого списка (Anonymous vs File-backed). На низких приоритетах ядро предпочитает сканировать анонимные страницы (готовые к swap), на высоких — файловый кэш (легко удаляется).

```bash
# Просмотр текущего приоритета reclaim (требует debugfs)
cat /proc/sys/vm/kswapd_threads 2>/dev/null || echo "N/A в ядре < 5.9"
# В современных ядрах kswapd_threads отсутствует; приоритет определяется динамически.
```

### Механизм Watermark Boosting (расширенный)

При резком росте аллокаций ядро может временно повышать `min` и `low` через `boost`. Это заставляет `kswapd` работать агрессивнее, но может вызвать `swap storms` при burst-нагрузках.

**Рекомендация 2025**: На серверах с высокой вариабельностью нагрузки (`kswapd` работает постоянно) отключите буст:
```bash
echo 0 | sudo tee /proc/sys/vm/watermark_boost_factor
```

Если оставить включенным (`10` по умолчанию), контролируйте через `dmesg` сообщения `watermark_boost`.

### NUMA и Page Cache / Reclaim

В NUMA-системах Page Cache распределяется по узлам пропорционально доступу:
- Ядро предпочитает хранить страницы файлов на том же узле, который их читал.
- `kernel.numa_balancing` перемещает страницы ближе к "горячим" ядрам.
- При дефиците на узле N, `kswapd` узла N может выгружать страницы в swap на локальное устройство.

**Важно:** Fallback на межпроцессорную шину (QPI/UPI) снижает производительность в 2–5 раз. Для диагностики:
```bash
# Проверка меж-узлового доступа (латентность)
numactl --hardware
# → node distances:
# →   0:  10  21
# →   1:  21  10

# Если node 0 перегружен, а node 1 свободен — возможен imbalanced reclaim
```

### Связь Page Cache и Writeback

Page Cache и Writeback — два лица одного процесса:
1. Приложение пишет → данные попадают в Page Cache (dirty pages).
2. Ядро отслеживает процент грязных страниц через `vm.dirty_ratio` / `vm.dirty_background_ratio`.
3. При превышении порогов запускаются потоки writeback (`kworker`, `flush-x`), которые сбрасывают данные на диск.
4. Если диск медленный, dirty pages накапливаются, занимая RAM и снижая `MemAvailable`.

**Ключевая метрика:** `Dirty` в `/proc/meminfo`. Если `Dirty` > 1–2 ГБ постоянно — дисковая подсистема не справляется.

```bash
# Мониторинг dirty pages
watch -n1 "grep -E 'Dirty|Writeback' /proc/meminfo"
# → Dirty:          524288 kB
# → Writeback:       65536 kB
# → Если Dirty растет, а Writeback ≈ 0 — writeback заблокирован
```

Подробнее: **[Настройка writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md)**.

## Практические сценарии

### Анализ состояния через /proc/zoneinfo

```bash
cat /proc/zoneinfo | grep -A 5 "Node"
# → pages free     12345
# →        min      1000
# →        low      1250
# →        high     1500
```
Если `free` стабильно держится около `low`, `kswapd` работает в постоянном режиме. Если падает до `min` — начался Direct Reclaim.

### Тюнинг параметров водяных знаков

1. **`vm.min_free_kbytes`**: Устанавливает базовый уровень `min`.
   - На серверах с 64 ГБ+ RAM рекомендуется устанавливать **1 ГБ** (`1048576`), чтобы минимизировать риск входа в Direct Reclaim при резких всплесках нагрузки.
   
2. **`vm.watermark_scale_factor`**: Управляет зазором между `min`, `low` и `high`.
   - Значение по умолчанию — 10 (0.1% от памяти).
   - Увеличение (до 50-100) заставляет `kswapd` просыпаться раньше, создавая более широкий буфер для компенсации всплесков I/O.

### Принудительный сброс файлового кэша на диск

Грязные страницы (изменённые данные в Page Cache, ещё не записанные на диск) ядро сбрасывает асинхронно потоками writeback. Для принудительной синхронизации существует простая консольная команда:

```bash
sync   # Сброс всех грязных страниц и буферов из RAM на диски; возвращается управление после постановки задач записи
```

Команда обязательна перед операциями, требующих целостности данных на носителе:

```bash
# Перевод ФС в read-only (например, перед работами с оборудованием)
sync && sudo mount -o remount,ro /data

# Перед отключением диска, созданием снапшота ВМ или перезагрузкой
sync
```

Не путать со «выгрузкой самого кэша из памяти» — это отдельная операция через запись цифры в `/proc/sys/vm/drop_caches`. Она не заменяет `sync`, а дополняет его, и является диагностическим приёмом (тестирование чтения с «холодного» кэша), а не штатной эксплуатационной практикой: после очистки ядро заново наполняет кэш чтениями с диска, создавая дополнительную нагрузку.

```bash
echo 3 | sudo tee /proc/sys/vm/drop_caches   # 1 — pagecache, 2 — иноды/дентри (Slab), 3 — всё
```

Подробнее о механике writeback: [kworker flush](../../Diagnostics/Performance/DiskIO/kworker_flush.md), [тюнинг writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md).

### Диагностика эффективности через PSI

PSI (Pressure Stall Information) — ключевой инструмент для оценки "голодания" по памяти.
```bash
cat /proc/pressure/memory
# some avg10 > 5% — процессы начали ждать освобождения памяти (Warning).
# full avg10 > 1% — система реально "тормозит" из-за Memory Pressure (Critical).
```

### Оценка Refaults и Thrashing

```bash
vmstat -s | grep -i refault
# workingset_refault_anon: возврат вытесненных анонимных страниц из swap.
# workingset_refault_file: возврат вытесненных страниц из кэша файлов.
```
Если счетчики растут со скоростью более 1000/сек, это верный признак **Thrashing** (система тратит больше времени на перемещение данных, чем на полезную работу).

### Runbook: обнаружение kswapd storm

`kswapd storm` — состояние, при котором фоновый reclaim не может угнаться за нагрузкой, и `kswapd` работает на 100% CPU, постоянно очищая кэши и свопая.

**Триазна:**
1. `top` / `htop` → `kswapd0` потребляет > 50% одного CPU-ядра.
2. `vmstat 1` → `si`/`so` > 0 постоянный, `free` не растет.
3. `cat /proc/pressure/memory` → `some avg10 > 10%`.

**Действия:**
1. **Быстрая разгрузка**: Увеличьте `vm.min_free_kbytes` (временно) или отключите THP:
   ```bash
   echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
   ```
2. **Выявление "виновника"**: Проверьте, какой процесс генерирует самый высокий `pgmajfault`:
   ```bash
   ps -eo pid,comm,majflt --sort=-majflt | head -n 10
   ```
3. **Кэш-анализ**: Определите, является ли проблема "горячим" кэшем или нехваткой RAM для процессов:
   ```bash
   awk '/Active\(anon\)|Inactive\(anon\)|Active\(file\)|Inactive\(file\)/' /proc/meminfo
   # Если Active(file)+Inactive(file) > 70% RAM — кэш переполнен, можно принудительно сбросить
   ```
4. **Аварийный сброс кэша** (только если `si`/`so` > 0, а `free` близок к `min`):
   ```bash
   echo 3 | sudo tee /proc/sys/vm/drop_caches
   ```
5. **Постоянное устранение**: Увеличить RAM, снизить `vm.dirty_ratio`, настроить cgroup-лимиты.

### Runbook: Direct Reclaim в контейнерах

В Docker/Kubernetes Direct Reclaim часто маскируется под OOMKilled или throttling.

**Триазна:**
1. `docker stats` → контейнер показывает `PIDS` ограничение или `MEM USAGE / LIMIT` близко к 100%.
2. `cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.events` → рост `low`, `high`, `max`.
3. `cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.pressure` → `full avg10 > 5%`.

**Действия:**
1. **Увеличение лимитов**: `docker update --memory=4g <container>` или adjust `resources.limits.memory` в Deployment.
2. **Добавление `memory.high`**: Установите мягкий лимит ниже `memory.max`, чтобы throttle начался раньше OOM:
   ```bash
   echo 3G | sudo tee /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.high
   ```
3. **Оптимизация workfload**: Если контейнер использует mmap (Java, Node.js), увеличьте `vm.min_free_kbytes` на хосте.
4. **Zram на хосте**: Установите `vm.swappiness=10` и включите zram на хосте, чтобы контейнер мог использовать быстрый swap без дисковых задержек.

### Runbook: Cache Pressure Triage

**Сценарий:** `MemAvailable` падает, `free` близок к `min`, процессы "фризят", но RSS стабилен.

**Дифференциальная диагностика:**

| Симптом | Page Cache Pressure | Slab Pressure | Anon Memory Leak |
|---------|-------------------|---------------|------------------|
| `Active(file)` растет | Да | Нет | Нет |
| `SUnreclaim` растет | Нет | Да | Нет |
| `Active(anon)` растет | Нет | Нет | Да |
| `MemAvailable` падает | Да | Да | Да |
| `pgmajfault` растет | Да | Иногда | Да |

**Действия по типу:**
1. **Page Cache Pressure**: Проверьте `Dirty` в `/proc/meminfo`. Если `Dirty` > 2 ГБ — проблема в writeback. Тюнинг: снизить `vm.dirty_ratio` и `vm.dirty_background_ratio`.
2. **Slab Pressure**: Проверьте `SUnreclaim` и `slabtop`. Если растет один кэш (например, `dentry`) — возможна утечка в VFS. Тюнинг: `vm.vfs_cache_pressure = 200` (агрессивная очистка).
3. **Anon Memory Leak**: Проверьте `top` / `ps aux --sort=-%mem`. Найдите процесс с растущим RSS. Тюнинг: cgroup-лимиты или перезапуск процесса.

### Диагностика per-zone watermarks

Для систем с несколькими NUMA-узлами или ограниченным DMA:
```bash
# Детальный анализ каждой зоны
cat /proc/zoneinfo | awk '
/^  pages free/ { free=$2 }
/min/ { min=$2 }
/low/ { low=$2 }
/high/ { high=$2 }
/scanned/ { scan=$2 }
/protection/ { prot=$2 }
NR%8==0 { 
  printf "Zone: %-20s free=%6d min=%6d low=%6d high=%6d scan=%6d prot=%d\n", 
  zone, free, min, low, high, scan, prot 
}
' zone=""

# Если free < low для Normal, но free > high для DMA — проблема локальна
```

### Тюнинг Readahead по типу нагрузки

```bash
# 1. СУБД (PostgreSQL, MySQL, ClickHouse): отключить полностью
echo 0 | sudo tee /sys/block/sda/queue/read_ahead_kb
echo 0 | sudo tee /sys/block/nvme0n1/queue/read_ahead_kb

# 2. Файловый сервер / Веб-сервер: умеренный readahead (256 КБ)
echo 256 | sudo tee /sys/block/sda/queue/read_ahead_kb

# 3. Последовательные чтения (видео, бэкапы): агрессивный (1–2 МБ)
echo 2048 | sudo tee /sys/block/sda/queue/read_ahead_kb

# 4. Постоянная настройка через udev (сохраняется после перезагрузки)
cat > /etc/udev/rules.d/99-readahead.rules << 'EOF'
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/read_ahead_kb}="0"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/read_ahead_kb}="256"
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/read_ahead_kb}="0"
EOF
udevadm control --reload-rules && udevadm trigger
```

### SRE: Ежедневный аудит кэшей и reclaim

```bash
#!/bin/bash
# runbook: daily_cache_audit.sh
echo "=== Общая картина ==="
free -h
echo ""

echo "=== Зоны и watermarks ==="
cat /proc/zoneinfo | grep -E "Node|free|min|low|high|scanned" | head -n 30
echo ""

echo "=== Reclaim активность ==="
grep -E "kswapd|pgscan|pgsteal|compact" /proc/vmstat | head -n 15
echo ""

echo "=== Page Cache vs Anon ==="
awk '/Active\(anon\)|Inactive\(anon\)|Active\(file\)|Inactive\(file\)/' /proc/meminfo
echo ""

echo "=== Dirty Pages ==="
grep -E "Dirty|Writeback" /proc/meminfo
echo ""

echo "=== Slab ==="
grep -E "Slab|SReclaimable|SUnreclaim" /proc/meminfo
echo ""

echo "=== THP / Компакция ==="
cat /sys/kernel/mm/transparent_hugepage/enabled
grep compact_stall /proc/vmstat
echo ""

echo "=== NUMA топология ==="
numactl --hardware | head -n 15
echo ""

echo "=== PSI Memory ==="
cat /proc/pressure/memory
echo ""

echo "=== Топ процессов по Major Faults ==="
ps -eo pid,comm,majflt --sort=-majflt | head -n 11
```

### Прометеус: алерты на кэширование и reclaim

```yaml
groups:
  - name: cache_reclaim_alerts
    rules:
      - alert: HighKswapdActivity
        expr: rate(node_vmstat_pgscan_kswapd[5m]) > 5000
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Высокая активность kswapd на {{ $labels.instance }}"
          description: "kswapd сканирует {{ $value }} страниц/сек. Проверьте watermark настройки."

      - alert: DirectReclaimDetected
        expr: rate(node_vmstat_pgsteal_kswapd[5m]) < 100 and rate(node_vmstat_pgscan_direct[5m]) > 1000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Direct Reclaim на {{ $labels.instance }}"
          description: "kswapd не справляется, процессы блокируются на reclaim."

      - alert: HighPageCachePressure
        expr: (node_memory_Active_file_bytes + node_memory_Inactive_file_bytes) / node_memory_MemTotal_bytes > 0.75
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "Высокое давление на Page Cache на {{ $labels.instance }}"
          description: "File-backed pages занимают {{ $value | humanizePercentage }} RAM."

      - alert: HighDirtyPages
        expr: node_memory_Dirty_bytes / node_memory_MemTotal_bytes > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий объем грязных страниц на {{ $labels.instance }}"
          description: "Dirty pages {{ $value | humanizePercentage }}. Проверьте writeback скорость."

      - alert: HighCompactionStalls
        expr: rate(node_vmstat_compact_stall[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Частые stall'ы компакции на {{ $labels.instance }}"
          description: "Процессы ждут дефрагментации. Проверьте THP настройки."

      - alert: Thrashing
        expr: rate(node_vmstat_workingset_refault_anon[5m]) + rate(node_vmstat_workingset_refault_file[5m]) > 1000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Thrashing на {{ $labels.instance }}"
          description: "Высокий refault rate {{ $value }} pages/sec. Увеличивайте RAM или уменьшайте working set."
```

## Дополнительная информация

### Связь со Slab и Swap

* **SReclaimable**: Часть Slab-аллокатора (кэши объектов ядра), которая может быть очищена шринкерами. Сюда входят `dentry` и `inode_cache`.
* **Swap**: Последний рубеж перед OOM Killer. Если кэш файлов исчерпан или "горяч", ядро выгружает анонимную память. Подробнее: **[Управление Swap](./swap_management.md)**.

### Влияние vm.vfs_cache_pressure

Параметр определяет приоритет очистки Slab (метаданные ФС) относительно Page Cache. 
* **100**: Баланс.
* **> 100**: Агрессивная очистка Slab (экономит память, но замедляет `ls`, `find` и другие операции с ФС).
* **< 100**: Ядро будет стремиться сохранить иноды в памяти, предпочитая очищать страничный кэш.

Подробнее о тюнинге всех параметров: **[Оптимизация и тонкая настройка памяти](./performance_tuning.md)**.

### Связь с другими механизмами

- **[Pressure Stall Information (PSI)](../kernel/psi.md)** — как PSI показывает давление на память из-за reclaim.
- **[Оптимизация памяти](./performance_tuning.md)** — детальный тюнинг watermarks, THP, NUMA, KSM, Zram/Zswap, Memory QoS.
- **[Диагностика Swap и Page Faults](./swap_diagnostics.md)** — диагностика swap, Major Faults, Zram/Zswap.
- **[Slab Allocator](./slab_allocator.md)** — SReclaimable/SUnreclaim, shrinkers, утечки ядра.
- **[/proc/meminfo — статистика памяти ядра](../../Diagnostics/Memory/proc_meminfo.md)** — расшифровка всех метрик.
- **[Настройка writeback](../../Diagnostics/Performance/DiskIO/writeback_tuning.md)** — профили tuning для Dirty Pages.
- **[vmstat — статистика виртуальной памяти](../../Diagnostics/Memory/vmstat.md)** — мониторинг reclaim активности.
