# SSD и NVMe: Burst I/O и деградация производительности

## Определения

**Burst I/O (Взрывной ввод-вывод)** — кратковременная пиковая производительность SSD, значительно превышающая его возможности в установившемся режиме (**Steady State**). Обусловлена наличием быстрых буферов (DRAM, SLC-кэш).

**Steady State** — режим производительности SSD после заполнения SLC-кэша и стабилизации фоновой сборки мусора. Именно это значение указывается в спецификациях (например, "до 500K IOPS" на упаковке часто относится к burst, а steady state может быть в 3–5 раз ниже).

**Write Amplification (WA — усиление записи)** — отношение объема данных, фактически записанных в NAND-ячейки, к объему данных, полученных от ОС. Идеальное значение WA = 1.0; для случайной записи без оптимизаций может достигать 10+.

**Garbage Collection (GC — сборка мусора)** — фоновый процесс контроллера по очистке блоков памяти от невалидных данных. Интенсивный GC вызывает скачки задержек (**Tail Latency**).

**HMB (Host Memory Buffer)** — технология NVMe для DRAM-less накопителей, позволяющая контроллеру использовать часть системной оперативной памяти хоста для хранения таблиц трансляции адресов (L2P). Это снижает задержки доступа по сравнению с хранением таблиц в медленной NAND.

**Zoned Namespaces (ZNS) / Flexible Data Placement (FDP)** — технологии NVMe 2.0+, позволяющие хост-системе напрямую управлять размещением данных. FDP (более современная и простая в интеграции) использует Placement IDs для разделения потоков данных с разным временем жизни, минимизируя WA.

**SLC-кэш (Single-Level Cell Cache)** — участок NAND-ячеек, работающий в быстром 1-битном режиме (SLC), в который попадают данные при первоначальной записи. Размер кэша обычно составляет 3–20% от общего объема диска.

**Thermal Throttling (Тепловое ограничение)** — механизм снижения производительности SSD при превышении рабочей температуры (обычно >70–80°C). Контроллер снижает частоту операций, что проявляется как внезапное падение IOPS и рост задержек.

**Queue Depth (Глубина очереди)** — максимальное количество операций ввода-вывода, которые устройство может обработать параллельно. Для NVMe типичные значения: 32–128 (consumer), 256–1024 (enterprise).

**Page Cache (Кэш страниц)** — область оперативной памяти, которую ядро Linux использует для кэширования данных файловой системы. Запись в Page Cache возвращает управление приложению мгновенно, но физическая запись на диск откладывается.

**Writeback** — фоновый процесс ядра (потоки `kworker/u*:flush-*`), асинхронно сбрасывающий «грязные» (dirty) страницы Page Cache на физическое устройство.

**I/O Priority (ioprio)** — класс и приоритет процесса в планировщике ввода-вывода ядра. Влияет на порядок обработки запросов при использовании планировщиков `bfq` или `kyber`; при планировщике `none` приоритизация работает только на уровне cgroup v2 (`io.weight`).

**IOPS (Input/Output Operations Per Second)** — количество операций ввода-вывода, выполняемое устройством за секунду. Для SSD критично различать случайные (4K randread/randwrite) и последовательные (1M seqread/seqwrite) IOPS.

**Throughput (Пропускная способность)** — объем данных, передаваемых за единицу времени (MB/s, GB/s). Обычно ограничивается интерфейсом (SATA III — 600 MB/s, PCIe 4.0 x4 — ~8 GB/s, PCIe 5.0 x4 — ~16 GB/s).

**Tail Latency (Хвостовые задержки)** — перцентили задержек P95, P99, P99.9. Для SSD/NVMe именно tail latency определяет пользовательский опыт и SLA баз данных, а не средние значения (mean).

## Основные концепции

### Причины деградации производительности

1.  **Исчерпание SLC-кэша:** TLC/QLC диски используют часть объема в быстром 1-битном режиме. При непрерывной записи кэш переполняется, и скорость падает до нативной (в 5–10 раз). Контроллер вынужден одновременно писать новые данные и уплотнять старые.

2.  **Агрессивная сборка мусора (GC):** При заполнении диска (>80%) контроллер начинает перемещать данные «на лету» во время записи пользователя. Это создает микропаузы и увеличивает задержки P99/P99.9.

3.  **Влияние PLP (Power Loss Protection) на синхронную запись:**
    - **Enterprise SSD (с PLP):** Имеют конденсаторы, позволяющие подтверждать `fsync` сразу после попадания в RAM-кэш. Это критично для WAL баз данных.
    - **Consumer SSD (без PLP):** Вынуждены сбрасывать данные на NAND при каждом `fsync`, что вызывает падение производительности БД на порядки.

4.  **Насыщение очередей и Hybrid Polling:** При экстремальных нагрузках прерывания создают оверхед. Ядро Linux поддерживает **Hybrid Polling** — режим, при котором ядро начинает активный опрос контроллера непосредственно перед ожидаемым завершением операции, снижая Latency и нагрузку на CPU.

5.  **Page Cache Writeback Storms:** Когда приложение выполняет массовую запись, ядро накапливает "грязные" страницы в Page Cache и затем сбрасывает их на диск большими порциями. Это создает всплески нагрузки (burst), при которых SSD исчерпывает SLC-кэш и переходит в steady state с низкой скоростью. Параметр `vm.dirty_ratio` / `vm.dirty_background_ratio` напрямую влияет на амплитуду этих всплесков.

6.  **Тепловое throttling:** При длительной нагрузке или плохой вентиляции контроллер NVMe снижает скорость работы. Это особенно заметно на Gen5-накопителях, потребляющих до 3A на линию 3.3V.

### Архитектура стека ввода-вывода (2025–2026)

- **blk-mq (Multi-Queue):** Параллельный слой ядра, распределяющий очереди по ядрам CPU, что устраняет узкие места на многоядерных системах.
- **NVMe Passthrough (`io_uring_cmd`):** Прямая передача команд контроллеру из Userspace (через `io_uring`). Исключает трансляцию блочного слоя, снижая Latency на 30–40%.
- **cgroups v2 io.latency:** В отличие от жесткого throttling (io.max), этот механизм динамически ограничивает низкоприоритетные процессы только тогда, когда задержки высокоприоритетной группы (например, БД) превышают заданный порог.

### Блочный слой ядра и устройство SSD

Взаимодействие приложения с SSD происходит через несколько абстракций:

1.  **Системный вызов (`write`/`read` или `io_uring`):** Приложение передает данные.
2.  **Page Cache:** Данные кэшируются в RAM. При синхронном вызове (`O_SYNC`, `fsync`) запись блокирует приложение до сброса на диск.
3.  **bio (Block I/O):** Ядро создает структуры `bio`, описывающие диапазон секторов и направление. Несколько `bio` группируются в запрос.
4.  **request_queue:** Очередь устройства, содержащая параметры тюнинга (scheduler, nr_requests, optimal_io_size и др.).
5.  **tag set:** Множество тегов (идентификаторов), ограничивающих параллелизм. Глубина аппаратной очереди (hardware queue depth) определяется тегами. При исчерпании тегов новые запросы ожидают освобождения.
6.  **Драйвер устройства:** Переводит запросы в команды NVMe/ATA/SCSI и отправляет через PCIe.

**Важно для DevOps:** Глубина очереди, видимая в `/sys/block/nvme0n1/queue/nr_requests`, должна быть >= hardware queue depth, чтобы теги не становились узким местом. Для NVMe enterprise typical hardware depth = 256–1024.

### Асимметрия чтения и записи

SSD/NVMe имеют выраженную асимметрию производительности:
- **Чтение:** Производительность чтения остается стабильной независимо от заполненности диска, так как не затрагивает GC.
- **Запись:** Скорость записи падает при заполнении SLC-кэша и росте фрагментации. При >80% заполнения деградация становится критичной.

Для SATA SSD разница может составлять 2–3x, для QLC NVMe — до 10x между burst и steady state записи.

### Влияние фрагментации и типа ячеек

- **SLC (1 бит):** Высокая скорость, низкая задержка, высокий ресурс (P/E cycles ~10000+). Используется как кэш.
- **MLC (2 бита):** Средняя скорость, средний ресурс (~3000–10000 P/E).
- **TLC (3 бита):** Базовая технология современных consumer SSD. Ресурс ~1000–3000 P/E. Зависит от SLC-кэша.
- **QLC (4 бита):** Низкая скорость записи, низкий ресурс (~100–1000 P/E). Сильно зависит от SLC-кэша и DRAM.

Фрагментация на уровне ОС почти не влияет на скорость чтения SSD, но увеличивает **Write Amplification** (WA) — контроллеру приходится перемещать больше блоков при GC.

## Практические сценарии

### Мониторинг и диагностика

```bash
# Просмотр SMART-статистики и критических предупреждений
sudo nvme smart-log /dev/nvme0

# Проверка активации Host Memory Buffer (HMB)
sudo nvme get-feature /dev/nvme0 -f 0x0d

# Анализ задержек через iostat
iostat -x 1 /dev/nvme0n1
# await > 0.5 мс для NVMe часто указывает на начало деградации (Steady State).
```

#### Критические SMART-атрибуты для мониторинга

```bash
# Полный дамп SMART через nvme-cli
sudo nvme smart-log /dev/nvme0

# Для SATA SSD
sudo smartctl -A /dev/sda
```

| Атрибут | NVMe (smart-log) | SATA (smartctl) | Порог тревоги |
| :--- | :--- | :--- | :--- |
| **Percentage Used** | `Percentage Used` | `Media_Wearout_Indicator` | > 80% — план замены |
| **Температура** | `Temperature` | `Temperature_Celsius` | > 70°C — проверка вентиляции |
| **Доступные резервы** | `Available Spare` | `Available Spare` | < 10% — срочная замена |
| **Напряжение** | `Vcc Voltage` | `5V` / `12V` | Вне диапазона ±5% |
| **Ошибки чтения** | `Read Errors` | `Read_Error_Rate` | Рост > 0 |
| **Ошибки записи** | `Write Errors` | `Write_Error_Rate` | Рост > 0 |
| **Время наработки** | `Power On Hours` | `Power_On_Hours` | Для оценки износа |
| **Переallocated sectors** | — | `Reallocated_Sector_Ct` | > 0 — предотказное состояние |

```bash
# Мониторинг температуры в реальном времени
watch -n 1 'cat /sys/block/nvme0n1/device/hwmon1/temp1_input'
# → результат: значение в миллиградусах (например, 45000 = 45°C)

# Проверка throtling через dmesg
dmesg -T | grep -i "nvme.*throttl"
```

### Оптимизация на уровне ядра

1.  **Выбор планировщика:** Для NVMe стандартом является `none`. Планировщики типа `mq-deadline` или `bfq` добавляют задержку, превышающую время отклика самого накопителя.
    ```bash
    echo none | sudo tee /sys/block/nvme0n1/queue/scheduler
    ```

2.  **Тюнинг глубины очереди и Hybrid Polling:**
    ```bash
    # Увеличение nr_requests для сглаживания Burst-пиков
    echo 256 | sudo tee /sys/block/nvme0n1/queue/nr_requests
    # Включение опроса (требует поддержки в драйвере/ФС)
    echo 1 | sudo tee /sys/block/nvme0n1/queue/io_poll
    ```

3.  **Использование io_uring:** Перевод приложений (RocksDB, PostgreSQL 17+) на асинхронный движок с `O_DIRECT` минимизирует влияние Burst I/O.

### Полный справочник параметров очереди (sysfs)

```bash
# Просмотр всех параметров очереди
ls -la /sys/block/nvme0n1/queue/

# Ключевые параметры для тюнинга:
cat /sys/block/nvme0n1/queue/nr_requests           # Макс. запросов в очереди
cat /sys/block/nvme0n1/queue/iosched/quantum       # Квант времени для CFQ (не используется)
cat /sys/block/nvme0n1/queue/read_ahead_kb         # Readahead в KB
cat /sys/block/nvme0n1/queue/max_sectors_kb        # Макс. размер запроса в KB
cat /sys/block/nvme0n1/queue/optimal_io_size        # Оптимальный размер I/O (обычно 128K для NVMe)
cat /sys/block/nvme0n1/queue/physical_block_size    # Физический размер сектора
cat /sys/block/nvme0n1/queue/logical_block_size     # Логический размер сектора
cat /sys/block/nvme0n1/queue/minimum_io_size        # Мин. размер I/O
cat /sys/block/nvme0n1/queue/discard_max_hw_bytes   # Макс. размер TRIM команды
cat /sys/block/nvme0n1/queue/io_poll                # Поддержка Hybrid Polling (0/1)
cat /sys/block/nvme0n1/queue/rotational             # 0 для SSD/NVMe
```

#### Рекомендуемые значения для NVMe

```bash
# Оптимизированный набор для high-performance NVMe
sudo tee /sys/block/nvme0n1/queue/nr_requests <<< 1024
sudo tee /sys/block/nvme0n1/queue/read_ahead_kb <<< 0
sudo tee /sys/block/nvme0n1/queue/max_sectors_kb <<< 1024
sudo tee /sys/block/nvme0n1/queue/discard_max_hw_bytes <<< 0  # Отключить авто-discard
```

**Пояснение:**
- `nr_requests=1024`: Увеличивает глубину очереди для лучшей утилизации параллелизма NVMe.
- `read_ahead_kb=0`: Для баз данных и случайных нагрузок пред读 не нужен.
- `max_sectors_kb=1024`: Ограничивает размер запроса, предотвращая слишком большие I/O, которые могут блокировать другие операции.
- `discard_max_hw_bytes=0`: Отключает автоматические discard (fstrim.timer предпочтительнее).

### Персистентная настройка через udev

```text
# /etc/udev/rules.d/60-ssd-io-tuning.rules

# NVMe: максимальная производительность
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/nr_requests}="1024"
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/read_ahead_kb}="0"
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/rotational}="0"

# SATA SSD: баланс задержек и производительности
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/nr_requests}="512"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/read_ahead_kb}="128"
```

Применение:
```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --type=devices --action=add
```

### Бенчмаркинг с fio (Burst vs Steady State)

```bash
# Тест 1: Burst sequential write (SLC-кэш полон после первого прогона)
fio --name=burst_seq_write \
    --rw=write --bs=1M --size=10G --filename=/tmp/testfile \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=1 \
    --group_reporting --time_based --runtime=30

# Тест 2: Steady state sequential write (после предварительного заполнения)
# Сначала заполняем диск полностью 2 раза для истощения SLC-кэша:
dd if=/dev/zero of=/tmp/testfile bs=1M count=0 oflag=direct conv=fdatasync 2>/dev/null || true
fio --name=steady_seq_write \
    --rw=write --bs=1M --size=10G --filename=/tmp/testfile \
    --ioengine=libaio --direct=1 --iodepth=32 --numjobs=1 \
    --group_reporting --time_based --runtime=60

# Тест 3: Случайная запись 4K (имитация БД)
fio --name=randwrite_4k \
    --rw=randwrite --bs=4k --size=4G --filename=/tmp/testfile \
    --ioengine=io_uring --direct=1 --iodepth=64 --numjobs=4 \
    --group_reporting --time_based --runtime=30 \
    --fsync=1  # Для измерения влияния fsync (PLP)

# Тест 4: Чтение после записи (read after write)
fio --name=randread_4k \
    --rw=randread --bs=4k --size=4G --filename=/tmp/testfile \
    --ioengine=io_uring --direct=1 --iodepth=64 --numjobs=4 \
    --group_reporting --time_based --runtime=30
```

**Интерпретация результатов:**
- Разница между `burst_seq_write` и `steady_seq_write` показывает размер SLC-кэша и скорость перехода в steady state.
- `randwrite_4k` с `fsync=1` на consumer SSD покажет падение IOPS в 5–10 раз по сравнению с enterprise SSD с PLP.
- P99 latency в fio output (`lat` или `clat` percentile) — ключевая метрика для tail latency.

### Управление свободным пространством

**Over-Provisioning (OP):** Резервирование 10–20% объема диска (оставить неразмеченным). Это дает контроллеру пространство для GC, снижает WA и стабилизирует производительность при длительных нагрузках.

```bash
# Проверка текущего OP через nvme
sudo nvme get-feature /dev/nvme0 -f 0x0c  # Режим питания (косвенный индикатор)
sudo nvme id-ns /dev/nvme0 -n 1           # Размер namespace

# Создание namespace меньшего размера для OP (пример для 960GB NVMe)
# Если диск имеет 1000.2 GB (960 GiB), создаем namespace на 800 GB:
sudo nvme create-ns /dev/nvme0 -s 1562820000 -c 1562820000 -m 0
# Затем обновляем карту блоков:
sudo nvme ns-rescan /dev/nvme0
```

### Восстановление после деградации

**Сценарий 1: Внезапное падение производительности**

```bash
# Шаг 1: Проверка температуры
sudo nvme smart-log /dev/nvme0 | grep Temperature
# Если > 80°C — проблема в охлаждении.

# Шаг 2: Проверка заполненности
df -h /mnt/data
# Если > 90% — выполните TRIM и освободите место.

# Шаг 3: Выполнение TRIM
sudo fstrim -v /mnt/data

# Шаг 4: Проверка, снизилась ли задержка
iostat -x 1 10 /dev/nvme0n1
# await должен вернуться к < 0.5 мс после TRIM + освобождения места.
```

**Сценарий 2: SLC-кэш исчерпан (после длительной записи)**

```bash
# Диагностика: запись резко замедлилась
# Решение: прерываем запись, даем контроллеру время на GC (5–10 мин)
# Либо перезагружаем сервер (полный сброс кэша контроллера)
sudo systemctl reboot
```

**Сценарий 3: Замена диска при критическом износе**

```bash
# Критерии замены:
# - Percentage Used > 90%
# - Available Spare < 5%
# - Рост uncorrectable errors

# Рекомендация: замена при Percentage Used > 80% для enterprise SSD.
```

### Мониторинг через Prometheus / Node Exporter

Метрики для отслеживания SSD здоровья и производительности:

```yaml
# prometheus.yml - scrape configs
scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
```

Ключевые метрики (через node_exporter):

| Метрика | Описание | Порог |
| :--- | :--- | :--- |
| `node_disk_io_time_seconds_total` | Общее время I/O | Рост без роста throughput |
| `node_disk_io_now` | Текущие I/O в прогрессе | > 0 для NVMe при простое |
| `node_disk_read_time_seconds_total` | Время чтения | Сравнение с historical baseline |
| `node_disk_write_time_seconds_total` | Время записи | Рост при degration |
| `node_nvme_device_power_cycles_total` | Циклы питания | Внезапный рост после сбоев |
| `node_nvme_device_unsafe_shutdowns_total` | Аварийные отключения | > 0 — проверка питания |
| `node_nvme_temperature_span` | Разница температур | > 20°C — охлаждение |
| `node_hwmon_temp_celsius` | Температура | > 70°C |
| `node_filesystem_size_bytes` | Заполненность ФС | > 85% |

### cgroups v2: изоляция SSD I/O

```bash
# Установка веса I/O для группы сервиса
echo "100" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.weight

# Жесткое ограничение скорости записи (MB/s)
echo "wbps=10485760" | sudo tee /sys/fs/cgroup/system.slice/backup.service/io.max

# Ограничение по задержке (микросекунды)
echo "rt=125000" | sudo tee /sys/fs/cgroup/system.slice/database.service/io.latency

# Просмотр статистики
cat /sys/fs/cgroup/system.slice/database.service/io.stat
# → nvme0n1 1048576 0 0 0 0 0 0 0 0
```

### Файловые системы: рекомендации для NVMe

| Файловая система | Рекомендации | Особенности |
| :--- | :--- | :--- |
| **XFS** | `noatime`, `allocsize=1M` для больших файлов | Лучшая масштабируемость, отличная работа с NVMe |
| **ext4** | `noatime`, `data=writeback` для БД | Стабильность, но выше латентность чем XFS |
| **Btrfs** | `ssd`, `discard=async`, `space_cache=v2` | Хорошо подходит для snapshot-ов, но сложнее отладка |
| **F2FS** | Нативная для flash, `noatime`, `mode=adaptive` | Лучшая производительность случайной записи на TLC/QLC |
| **ZFS** | `atime=off`, `logbias=throughput`, `primarycache=metadata` | Требует careful tuning, но максимальная надежность |

```bash
# Пример /etc/fstab для NVMe с XFS
UUID=xxxx /mnt/data xfs defaults,noatime,nodiratime,allocsize=1M 0 2

# Для Btrfs с async discard
UUID=yyyy /mnt/backup btrfs defaults,noatime,discard=async,space_cache=v2 0 2
```

### Влияние на базы данных (PostgreSQL / MySQL)

```sql
-- PostgreSQL: конфигурация для NVMe с PLP
shared_buffers = 8GB            # ~25% RAM
work_mem = 64MB                 # Для сложных сортировок
maintenance_work_mem = 512MB    # Для VACUUM, CREATE INDEX
wal_buffers = 64MB
checkpoint_completion_target = 0.9  # Равномерный сброс WAL
effective_io_concurrency = 256     # Для async prefetch (NVMe)

-- Важно: для consumer SSD без PLP используйте fsync=full
-- Для enterprise SSD с PLP можно рассмотреть unsynced_writes для аналитики
```

```ini
# MySQL / Percona: настройка для NVMe
[mysqld]
innodb_flush_method = O_DIRECT
innodb_io_capacity = 5000
innodb_io_capacity_max = 10000
innodb_flush_neighbors = 0
innodb_adaptive_flushing = 1
innodb_flush_log_at_trx_commit = 1  # Для durability; 2 для async (риск при сбое)
sync_binlog = 1                    # Для binlog durability
```

### Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `await > 0.5 мс` на NVMe | Деградация (SLC-кэш исчерпан, GC) | Выполнить `fstrim`, освободить место, проверить температуру |
| `await > 5 мс` на NVMe | Тепловой throttling или аппаратный сбой | Проверить `nvme smart-log`, `dmesg`, охлаждение |
| `%util = 100%`, но `aqu-sz < 4` | NVMe не насыщен (старая метрика) | Ориентироваться на `aqu-sz` и P99 latency |
| `iostat` показывает 0, но `await` высокий | Проблема в cache miss или scheduler | Проверить `biolatency-bpfcc` |
| Высокий `iowait` на NVMe | Насыщение очереди или блокировка в Page Cache | Увеличить `nr_requests`, проверить `vm.dirty_ratio` |
| `nr_requests` exhausted | Глубина очереди слишком мала | Увеличить до 1024 для NVMe |
| `fio` показывает низкий IOPS | Используется scheduler `mq-deadline`/`bfq` | Переключить на `none` |
| `fstrim` падает с "not supported" | LUKS/LVM без discard, или USB без UASP | Проверить `lsblk -D`, включить флаги `discard` |
| Троттлинг на холодном старте | ASPM / APST не дают диску "проснуться" | Отключить `nvme_core.default_ps_max_latency_us=0` |
| `smartctl` PASSED, но диск тормозит | Проблема на уровне PCIe/AER | Проверить `dmesg | grep -i nvme`, `lspci -vv` |

### Мониторинг через bpftrace / eBPF

```bash
# Гистограмма задержек всех дисковых операций
sudo biolatency-bpfcc 10

# Отслеживание каждого запроса в реальном времени
sudo biosnoop-bpfcc

# Задержки по процессам
sudo biodelay-bpfcc

# Задержки io_uring операций
sudo bpftrace -e '
tracepoint:io_uring:io_uring_complete {
    @latency[args->opcode] = hist((nsecs - @start[args->req]) / 1000);
}
'
```

### Рекомендации

1.  **Over-provisioning:** Оставляйте 10–20% диска неразмеченным (unallocated). Это дает контроллеру SSD пространство для маневров Garbage Collection.
2.  **noatime:** Используйте опцию монтирования `noatime` в `/etc/fstab` для минимизации лишних записей.
3.  **Охлаждение:** Контролируйте температуру NVMe через `smartctl` или `nvme smart-log`. При >75°C снижайте нагрузку или улучшайте охлаждение.
4.  **Периодический TRIM:** Используйте `fstrim.timer` вместо опции монтирования `discard`.
5.  **Мониторинг SMART:** Настройте алерты на `Percentage Used > 80%` и `Available Spare < 10%`.
6.  **Выбор диска:** Для баз данных с интенсивной записью используйте enterprise SSD с PLP и DRAM. Consumer TLC/QLC подходят только для read-heavy или архивных workloads.

### См. также

- **Планировщики:** [Планировщики ввода-вывода](./io_schedulers.md) — детали архитектуры blk-mq и выбора планировщика.
- **Асинхронный ввод-вывод:** [io_uring — асинхронный ввод-вывод](./io_uring.md) — прямой доступ и высокая производительность.
- **Обслуживание SSD:** [Обслуживание SSD (TRIM)](../../SystemAdministration/fstrim_ssd_maintenance.md) — управление свободным пространством.
- **Диагностика I/O:** [Диагностика дискового ввода-вывода](../../Diagnostics/Performance/disk_io_troubleshooting.md) — общий алгоритм диагностики.
- **Диагностика NVMe:** [Диагностика ошибок NVMe](../../Diagnostics/Hardware/nvme-errors-diagnostics.md) — решение проблем со связью и контроллером.
- **Основы хранения:** [Основы хранения данных](../../FileSystems/disk_storage_fundamentals.md) — сектора, блоки, типы носителей.
