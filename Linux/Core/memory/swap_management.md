# Управление Swap (подкачкой) в Linux

## Определения

* **Swap (подкачка)** — пространство на дисковом носителе, используемое ядром Linux для выгрузки неактивных анонимных страниц при дефиците оперативной памяти (RAM).
* **Анонимные страницы (Anonymous Pages)** — сегменты памяти, не связанные с файлом на диске (стек процесса, куча, данные `malloc`). При нехватке памяти они выгружаются в swap.
* **File-backed страницы** — страницы, отображенные на файлы (бинарные файлы, библиотеки). Могут быть удалены из RAM без записи в swap, так как восстанавливаются чтением с диска.
* **Swappiness** (`vm.swappiness`) — параметр, определяющий баланс между вытеснением анонимных страниц и очисткой файлового кэша. В современных ядрах (>= 5.8) диапазон значений расширен до **200**.
* **MGLRU (Multi-Gen LRU)** — алгоритм (с ядра 6.1), группирующий страницы по "поколениям" доступа, что повышает точность выбора кандидатов на выгрузку.
* **PSI (Pressure Stall Information)** — механизм отслеживания задержек (stalls), вызванных нехваткой ресурсов. Позволяет оценить реальное влияние swap на производительность приложений.
* **Memory Swap Max/High (cgroups v2)** — механизмы ограничения использования swap для конкретных групп процессов или контейнеров.
* **Swap Cache** — внутренний кэш ядра, в котором хранятся "грязные" swap-записи, ожидающие записи на диск. Размер отображается в `/proc/meminfo` как `SwapCached`. Это не дублирование данных в RAM, а буфер для оптимизации I/O.
* **Swap Entry** — структура данных ядра, описывающая расположение страницы в области подкачки (swap area) или swap-файле.
* **Hibernation Resume Offset** — смещение в байтах внутри swap-файла, с которого ядро должно начать чтение образа памяти при выходе из гибернации. Требуется для swap-файлов на BTRFS и некоторых других ФС.

## Основные концепции

### Назначение Swap

1. **Высвобождение ресурсов**: Перемещение редко используемых анонимных страниц в swap для освобождения RAM под активные процессы и Page Cache.
2. **Защита от OOM (Out Of Memory)**: Наличие swap дает ядру "подушку безопасности" для маневра. Без swap при исчерпании RAM немедленно активируется **[OOM Killer](../processes/oom_killer_mechanism.md)**.
3. **Оптимизация Page Cache**: Swap позволяет системе агрессивнее использовать RAM для дискового кэша, что ускоряет чтение файлов.

### Внутренний механизм работы

Ядро управляет swap через несколько ключевых компонентов:

1. **Swap Map**: Для каждого swap-области (раздела или файла) ядро поддерживает битовую карту, отслеживающую свободные и занятые страницы подкачки. При выгрузке страницы ядро записывает её в swap, обновляет Swap Map и сохраняет Swap Entry в таблице страниц процесса.
2. **Swap Cache**: Перед записью на диск сжатые swap-страницы попадают в Swap Cache. Это позволяет ядру coalescing-ить (объединять) смежные записи и снижать количество I/O-операций. Размер `SwapCached` в `/proc/meminfo` показывает объем данных в этом буфере.
3. **Page Replacement**: При нехватке RAM ядро (через kswapd или direct reclaim) выбирает "жертву" по алгоритму LRU/MGLRU. Анонимные страницы отправляются в swap, file-backed — удаляются (так как их можно восстановить с диска).
4. **Swap-in**: При обращении к выгруженной странице происходит Major Page Fault, ядро ищет Swap Entry, читает данные с диска обратно в RAM и обновляет таблицу страниц.

### Взаимодействие с MGLRU и PSI

* **MGLRU** (с ядра 6.1): Группирует страницы по поколениям доступа. "Старые" анонимные страницы быстрее попадают в список кандидатов на выгрузку в swap, снижая количество ошибочных выгрузок. Статус: `cat /sys/kernel/mm/lru_gen/enabled`.
* **PSI**: Позволяет отличить "полезный" свопинг (прогрев кэша) от деградации. Если `memory.full avg10 > 5%`, система реально теряет производительность. Подробнее: **[Pressure Stall Information (PSI)](../kernel/psi.md)**.

### Работа в современных средах

#### Cgroups v2 и лимиты Swap

В cgroups v2 (современный стандарт) управление swap осуществляется через файлы в `/sys/fs/cgroup/<group>/`:
* `memory.swap.max`: Жесткий лимит. При достижении процессы группы не смогут использовать больше swap.
* `memory.swap.high`: Мягкий лимит ("throttle"). При превышении ядро начинает агрессивно возвращать страницы группы в RAM или ограничивать их выделение.
* `memory.swap.current`: Текущее потребление swap группой.

#### Оптимизация для SSD и NVMe

Для минимизации износа и задержек на NVMe-носителях:
1. **Discard**: Рекомендуется использовать опцию монтирования `discard=once` в `/etc/fstab` (выполняет TRIM всей области swap один раз при загрузке).
2. **Alignment**: Раздел swap должен быть выровнен по границе 1 МБ.
3. **Swap-файлы**: При использовании swap-файла на SSD/NVMe дополнительные опции `discard` обычно не требуются, так как файл обрабатывается механизмом `fstrim` файловой системы.

### Выбор типа Swap: Раздел против Файла

| Характеристика | Swap-раздел | Swap-файл |
| :--- | :--- | :--- |
| **Производительность** | Традиционно считался быстрее, но на современных SSD/NVMe разница отсутствует. | Идентична разделу. |
| **Гибкость** | **Низкая** — требует переразметки диска. | **Высокая** — легко изменить размер или удалить. |
| **Применение** | Устаревающий стандарт. | Современный стандарт (Ubuntu, Fedora, Arch). |

### Настройка параметра vm.swappiness

Параметр определяет соотношение "стоимости" выгрузки анонимных и файловых страниц.
* **0–10**: Минимальное использование swap. Рекомендуется для баз данных (PostgreSQL, MySQL), JVM-приложений (Elasticsearch, Kafka) и систем с быстрым диском, чтобы избежать задержек.
* **60**: Значение по умолчанию (баланс).
* **100**: Равный приоритет между очисткой кэша и использованием swap.
* **101–200 (ядро >= 5.8)**: Агрессивная выгрузка в swap. Полезно, если файловый кэш критически важен для производительности, а диск быстрый.

```bash
# Просмотр текущего значения
cat /proc/sys/vm/swappiness

# Временное изменение
sudo sysctl -w vm.swappiness=10
```

Подробное описание тюнинга: **[Оптимизация и тонкая настройка памяти](./performance_tuning.md)**.

### NUMA и Swap

В мультисокетных системах (NUMA) ядро предпочитает выгружать страницы в локальный swap-устройство для соответствующего узла. При недоступности локального swap происходит fallback на устройства других узлов через QPI/UPI, что снижает производительность. Для управления привязкой процессов и памяти используйте `numactl`. Подробнее о тюнинге NUMA: **[Оптимизация и тонкая настройка памяти](./performance_tuning.md)**.

## Практические сценарии

### Инспекция текущего состояния

```bash
# Список активных устройств и их использование
swapon --show

# Сводная информация по памяти
free -h

# Проверка PSI (если включено в ядре)
cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

### Производственные пороги и дифференциальная диагностика

| Метрика | Порог внимания | Критический порог | Интерпретация |
| :--- | :--- | :--- | :--- |
| **SwapUsed / SwapTotal** | > 25% | > 60% | Высокое использование swap увеличивает латентность. |
| **si/so в vmstat** | > 0 постоянный | > 50 страниц/сек | Активный обмен означает thrashing или перегрузку. |
| **wa (I/O wait)** | > 5% | > 20% | Дисковые задержки от swap-операций. |
| **PSI Memory full** | > 5% avg10 | > 15% avg10 | Процессы теряют время на ожидание swap/ reclaim. |
| **SwapCached** | > 20% SwapTotal | > 50% SwapTotal | Много "грязных" записей в буфере — возможен swap storm. |

**Дифференциальная диагностика:**
* **Swap Thrashing**: Высокие `si`/`so`, высокий `wa`, низкий `free`, процессы "зависают". Причина — Working Set не помещается в RAM.
* **Утечка памяти процесса**: `free` падает, но `si`/`so` низкие. Используйте `smem -s swap` для поиска виновника.
* **Slab Leak**: `SUnreclaim` в `/proc/meminfo` растет, `SwapCached` высокий. Подробнее: **[Slab Allocator](./slab_allocator.md)**.

### Создание Swap-файла (Standard)

Для файловых систем ext4 и XFS:
```bash
# 1. Создание файла (4 ГБ)
sudo fallocate -l 4G /swapfile

# 2. Установка прав (критично для безопасности!)
sudo chmod 600 /swapfile

# 3. Форматирование и включение
sudo mkswap /swapfile
sudo swapon /swapfile

# 4. Автозагрузка (/etc/fstab)
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Создание Swap-файла (BTRFS)

На BTRFS рекомендуется использовать встроенную утилиту (с btrfs-progs 6.1+), которая автоматически отключает CoW и компрессию:
```bash
# 1. Создание отдельного subvolume (рекомендуется для исключения из снапшотов)
sudo btrfs subvolume create /swap

# 2. Создание swap-файла
sudo btrfs filesystem mkswapfile --size 4G /swap/swapfile

# 3. Включение
sudo swapon /swap/swapfile
```
*Примечание: Swap-файлы на BTRFS не поддерживаются на RAID-массивах (только single device).*

### Автоматизация через Ansible

Для массового развертывания swap в кластере используйте модуль `ansible.posix.sysctl` и `ansible.builtin.command`:
```yaml
- name: Создать swap-файл
  ansible.builtin.command:
    cmd: "fallocate -l {{ swap_size }} /swapfile"
    creates: /swapfile
  when: swap_size is defined

- name: Установить права
  ansible.builtin.file:
    path: /swapfile
    owner: root
    group: root
    mode: '0600'

- name: Инициализировать swap
  ansible.builtin.command:
    cmd: mkswap /swapfile
  when: not ansible_facts.ansible_local.swap_initialized | default(false)

- name: Включить swap
  ansible.builtin.command:
    cmd: swapon /swapfile

- name: Добавить в fstab
  ansible.posix.mount:
    src: /swapfile
    fstype: swap
    opts: sw
    state: present

- name: Настроить swappiness
  ansible.posix.sysctl:
    name: vm.swappiness
    value: '{{ swappiness | default(10) }}'
    sysctl_file: /etc/sysctl.d/99-swap.conf
    state: present
```

### Приоритеты устройств подкачки

Если у вас несколько устройств (например, Zram и SSD), можно задать приоритет (чем выше число, тем выше приоритет):
```bash
# Включение с приоритетом 100
sudo swapon /dev/zram0 -p 100

# В /etc/fstab
/dev/zram0 none swap pri=100 0 0
```

Ядро использует устройство с наивысшим приоритетом до заполнения, затем переходит к следующему.

### Тюнинг под рабочие нагрузки

| Рабочая нагрузка | vm.swappiness | Дополнительно |
| :--- | :--- | :--- |
| **Базы данных (PostgreSQL, MySQL)** | 1–10 | `vm.overcommit_memory=2`, отключить THP. |
| **JVM (Elasticsearch, Kafka)** | 1–5 | `-XX:+AlwaysPreTouch`, фиксированный heap. |
| **Высоконагруженный web** | 10–20 | `vm.vfs_cache_pressure=50`. |
| **Виртуализация / VPS** | 10 | `vm.min_free_kbytes` повышен, `zram` активен. |
| **Бездисковые системы (Raspberry Pi)** | 100 | Только `zram`, swap-раздел отсутствует. |

### Рекомендации по объему

| Тип системы | Рекомендация | Комментарий |
| :--- | :--- | :--- |
| **Десктоп** | RAM + 2 ГБ | Для поддержки гибернации. |
| **Сервер БД** | 1–4 ГБ | "Подушка" для защиты от OOM при пиках. |
| **Kubernetes Node** | **Включен** | Рекомендуется `LimitedSwap` для K8s 1.31+. |
| **Zram / Zswap** | 50% от RAM | Оптимально для систем с быстрым CPU и медленным диском. |

### Аварийные сценарии

#### Система зависла из-за thrashing

Если `wa` близок к 100% и система не реагирует на клавиатуру:

```bash
# 1. Переключитесь в другой tty (Ctrl+Alt+F2) или используйте Magic SysRq
# 2. Принудительно синхронизируйте данные
sudo sync

# 3. Увеличьте swappiness, чтобы ядро прекратило выгрузку
sudo sysctl -w vm.swappiness=0

# 4. Отключите swap
sudo swapoff -a

# 5. Очистите кэш (осторожно!)
# sudo sysctl -w vm.drop_caches=3

# 6. Включите swap обратно с низким swappiness
sudo swapon -a
sudo sysctl -w vm.swappiness=10
```

#### Не включается swap-файл

```bash
# Проверка ошибок
sudo swapon /swapfile
# → swapon: /swapfile: found swap signature, but size is wrong

# Пересоздание (не теряет данные при использовании файла вместо раздела)
sudo mkswap /swapfile
sudo swapon /swapfile
```

#### Обнаружение утечки swap

```bash
# Топ процессов по swap
smem -t -k -s swap -r | head

# Историческая активность swap
sar -W 1 10
```

### Kubernetes и Swap (v1.31+)

С версии 1.31 поддержка Swap в Kubernetes является **Stable (GA)**.
**Требования:**
* Использование **cgroup v2**.
* Настройка `KubeletConfiguration` (`/var/lib/kubelet/config.yaml`):
```yaml
failSwapOn: false
memorySwap:
  swapBehavior: LimitedSwap
```
**LimitedSwap**: Объем swap для контейнера ограничивается пропорционально его Memory Request. Это предотвращает неконтролируемое использование диска и падение производительности всего узла.

### Мониторинг и алерты (Prometheus)

Для node_exporter отслеживайте метрики `node_slabs_*` и `node_memory_*`:

```yaml
# Alert: Swap usage is high
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
```

## Дополнительная информация

### Zswap и Zram: Сжатие в RAM

* **Zswap**: Механизм кэширования в RAM для страниц, направляемых в swap. Сжимает данные и хранит их в пуле в оперативной памяти. Если пул переполняется, сжатые данные сбрасываются на физический swap. Эффективно снижает I/O на диске.
  * **Практическая настройка** (ядро >= 5.11):
    ```bash
    # Включение через модуль
    echo 1 > /sys/module/zswap/parameters/enabled
    echo zstd > /sys/module/zswap/parameters/compressor
    echo 25 > /sys/module/zswap/parameters/max_pool_percent
    ```
* **Zram**: Создает виртуальное блочное устройство в RAM со сжатием. Работает как самостоятельный swap. Часто используется на бездисковых системах или для ускорения работы с памятью.

**Современная настройка (zram-generator):**
В дистрибутивах Fedora, RHEL и Arch используется `zram-generator`.
Конфигурация `/etc/systemd/zram-generator.conf`:
```ini
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
```

### Гибернация (Hibernation)

Для гибернации размер swap должен быть не меньше объема используемой RAM. Необходимо:
1. Настроить параметр загрузчика `resume=UUID=<swap_uuid>`.
2. (Для BTRFS) Указать `resume_offset` (вычисляется через `btrfs-inspect-internal map-swapfile -r /path/to/swapfile`).
3. Убедиться, что ядро compiled with `CONFIG_PM_STD_PARTITION=""` или указано правильное устройство.

### Параметры ядра и загрузчика

Для тонкого контроля поведения swap используйте параметры в `/etc/sysctl.d/99-swap.conf`:
```ini
# Минимизировать свопинг на SSD
vm.swappiness = 10

# Отключить динамический буст вотермарков (предотвращает swap storms)
vm.watermark_boost_factor = 0

# Увеличить зазор между min/low/high для раннего пробуждения kswapd
vm.watermark_scale_factor = 50

# Резерв для атомарных аллокаций ядра (на системах 64GB+)
vm.min_free_kbytes = 1048576
```

### Взаимосвязь с другими механизмами

* **[Pressure Stall Information (PSI)](../kernel/psi.md)**: Основной источник метрик давления для современных систем.
* **[OOM Killer](../processes/oom_killer_mechanism.md)**: Финальный этап дефицита памяти.
* **[Оптимизация памяти](./performance_tuning.md)**: Настройка `vm.swappiness` и `vm.vfs_cache_pressure` для снижения активности свопинга.
* **[Диагностика Swap и Page Faults](./swap_diagnostics.md)**: Глубокий анализ задержек и PSI.
* **[Slab Allocator](./slab_allocator.md)**: Утечки в кэшах ядра (SUnreclaim) часто являются причиной вытеснения приложений в swap.
* **[/proc/meminfo](../../Diagnostics/Memory/proc_meminfo.md)**: Детальная расшифровка метрик памяти, включая SwapTotal/SwapFree и Zswap.
* **[vmstat](../../Diagnostics/Memory/vmstat.md)**: Мониторинг активности swap (si/so) в реальном времени.
* **[Справочник sysctl-параметров памяти](./sysctl_memory_reference.md)**: Единый reference по vm.swappiness, overcommit, watermarks и др.

### Литература и ссылки

* [Kubernetes Documentation: Swap Support](https://kubernetes.io/docs/concepts/architecture/nodes/#swap-memory)
* [Kernel.org: Multi-Gen LRU (MGLRU)](https://www.kernel.org/doc/html/latest/admin-guide/mm/multigen_lru.html)
* [ArchWiki: Btrfs Swap file](https://wiki.archlinux.org/title/Btrfs#Swap_file)
