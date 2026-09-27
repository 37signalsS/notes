# Тюнинг производительности RAID-массивей

## Определения

**Stripe Size / Chunk Size (Размер полосы / блока)** — объём данных, записываемый на один диск массива перед переходом на следующий. Определяет баланс между IOPS (мелкие блоки) и throughput (крупные блоки).

**Stripe Width (Ширина полосы)** — общее количество блоков данных в одной «строке» массива. Для RAID 5: `(N-1) × Chunk Size`. Для RAID 10: `Chunk Size`.

**I/O Scheduler (Планировщик ввода-вывода)** — подсистема ядра, управляющая порядком и приоритетом обработки блочных запросов. Ключевые: `none`, `mq-deadline`, `bfq`, `kyber`.

**Read-Miss Penalty (Штраф промаха чтения)** — для RAID 5/6 при чтении блока, который не попал в кэш, необходимо прочитать данные со всех дисков и вычислить отсутствующий блок через XOR.

**Rebuild Speed (Скорость восстановления)** — скорость фонового процесса ресинхронизации массива после замены диска. Настраивается через `speed_limit_min` и `speed_limit_max` в sysfs.

---

## Основные концепции

### Выбор Chunk Size под типичную нагрузку

Chunk Size — ключевой параметр, определяющий производительность RAID-массива.

| Нагрузка | Рекомендуемый Chunk Size | Обоснование |
| :--- | :--- | :--- |
| **OLTP БД (случайные 4K-8K)** | 4K–64K | Один запрос попадает в один chunk, минимизируя read-modify-write |
| **Виртуализация (mixed I/O)** | 128K–256K | Баланс между IOPS и throughput |
| **Файловый сервер (смешанный)** | 256K–512K | Универсальный размер |
| **Потоковое видео / бэкапы** | 512K–1M | Максимальный throughput для последовательных операций |
| **PostgreSQL (8K page)** | 8K | Соответствие размеру страницы БД |
| **MySQL InnoDB (16K page)** | 16K–64K | Кратность странице + запас для merge |

**Формула расчёта:**

```
Оптимальный chunk_size = размер типичного I/O запроса × количество_дисков

Пример: OLTP БД с 8K страницами, RAID 10 из 8 дисков
chunk_size = 8K × 1 = 8K (для RAID 10, stripe width = chunk size)
```

**Изменение chunk size на существующем массиве:**

```bash
# Проверка текущего chunk size
sudo mdadm --detail /dev/md0 | grep "Chunk Size"

# Изменение (требует ресинхронизации!)
sudo mdadm --grow /dev/md0 --chunk=128

# Мониторинг
watch cat /proc/mdstat
```

> **Важно:** Изменение chunk size — длительный процесс. Массив работает в degraded state до завершения.

### Выбор I/O Scheduler для RAID

| Тип диска | Рекомендуемый scheduler | Обоснование |
| :--- | :--- | :--- |
| **NVMe SSD** | `none` | Минимальная задержка, планировщик не нужен |
| **SATA/SAS SSD** | `mq-deadline` | Баланс между latency и throughput |
| **HDD (сервер)** | `mq-deadline` | Предсказуемость и группировка запросов |
| **HDD (интерактивная)** | `bfq` | Справедливое распределение между процессами |
| **iSCSI / NFS** | `mq-deadline` | Сетевая задержка требует балансировки |

**Проверка текущего scheduler:**

```bash
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none
```

**Переключение scheduler:**

```bash
# Временно
echo mq-deadline | sudo tee /sys/block/sda/queue/scheduler

# Постоянно через udev
cat <<'EOF' | sudo tee /etc/udev/rules.d/60-io-schedulers.rules
# NVMe: none
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"
# SATA/SAS SSD: mq-deadline
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"
# HDD: mq-deadline (сервер) или bfq (интерактивная)
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="mq-deadline"
EOF

sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Тюнинг sysctl для RAID

```bash
# /etc/sysctl.d/99-raid-performance.conf

# Скорость ресинхронизации (КБ/с)
# Минимальная скорость (по умолчанию 1000)
dev.raid.speed_limit_min = 50000

# Максимальная скорость (по умолчанию 200000)
dev.raid.speed_limit_max = 500000

# Количество одновременных операций reshape (ядро 4.12+)
# dev.raid.max_sector_ratio = 10000

# Применение
sudo sysctl --system
```

### Влияние ребилда на производительность

Во время ребилда массив работает в degraded state. Ключевые параметры:

| Параметр | По умолчанию | Рекомендация | Влияние |
| :--- | :--- | :--- | :--- |
| `speed_limit_min` | 1000 КБ/с | 50 000 КБ/с | Минимальная скорость восстановления |
| `speed_limit_max` | 200 000 КБ/с | 500 000 КБ/с | Максимальная скорость восстановления |

**Управление скоростью во время рабочих часов:**

```bash
# Уменьшить скорость в рабочее время (чтобы не влиять на приложения)
echo 10000 | sudo tee /proc/sys/dev/raid/speed_limit_max

# Увеличить в окно обслуживания (ночь/выходные)
echo 500000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

**Автоматическое управление через cron:**

```bash
# /etc/cron.d/raid-speed
# Днём (8-20) — медленно
0 8 * * 1-5 root echo 10000 > /proc/sys/dev/raid/speed_limit_max
# Ночью (20-8) — быстро
0 20 * * 1-5 root echo 500000 > /proc/sys/dev/raid/speed_limit_max
# Выходные — быстро
0 8 * * 6,0 root echo 500000 > /proc/sys/dev/raid/speed_limit_max
0 20 * * 6,0 root echo 500000 > /proc/sys/dev/raid/speed_limit_max
```

### Оптимизация для чтения vs записи

| Параметр | Оптимизация для чтения | Оптимизация для записи |
| :--- | :--- | :--- |
| **Chunk Size** | Малый (4K-64K) | Большой (256K-1M) |
| **RAID уровень** | RAID 5/6 (хорошее чтение) | RAID 10 (минимум penalty) |
| **Кэш контроллера** | Read-ahead | Write-back (с BBU) |
| **sysctl** | `vm.dirty_ratio` низкое | `vm.dirty_ratio` высокое |
| **ФС** | `noatime` | `barrier=0` (опасно!) |

### Write-back кэш и BBU

Для аппаратных RAID-контроллеров с BBU:

| Режим | Кэш записи | Безопасность | Производительность |
| :--- | :--- | :--- | :--- |
| **Write-Back** | Используется | Данные в кэше защищены BBU | Максимальная |
| **Write-Through** | Не используется | Данные сразу на диске | Средняя |

```bash
# Проверка статуса BBU (MegaRAID)
sudo storcli /c0 /bbu show all

# Переключение в Write-Back (если BBU заряжена)
sudo storcli /c0 set wrcache=WB

# Переключение в Write-Through (если BBU разряжена)
sudo storcli /c0 set wrcache=WT
```

### Файловая система и опции монтирования

```bash
# Оптимальные опции для RAID 5/6 (ext4)
/dev/md0 /mnt/raid ext4 defaults,noatime,nodiratime,barrier=0,data=writeback 0 2

# Оптимальные опции для RAID 10 (XFS)
/dev/md0 /mnt/raid xfs defaults,noatime,nodiratime,logbufs=8,logbsize=256k 0 2

# Оптимальные опции для RAID (ZFS)
# zfs set atime=off pool/data
# zfs set logbias=throughput pool/data
# zfs set recordsize=128k pool/data
```

> **Внимание:** `barrier=0` отключает барьеры записи. Используйте только с BBU или при высоком риске потери данных.

---

## Практические сценарии

### Сценарий 1: Оптимизация RAID 5 для OLTP БД

**Проблема:** Высокая latency записи из-за Write Penalty = 4.

**Решение:**
```bash
# 1. Уменьшить chunk size до 64K
sudo mdadm --grow /dev/md0 --chunk=64

# 2. Переключить scheduler на mq-deadline
echo mq-deadline | sudo tee /sys/block/md0/queue/scheduler

# 3. Включить write-back кэш (если есть BBU)
sudo storcli /c0 set wrcache=WB

# 4. Оптимизировать sysctl
echo 10 | sudo tee /proc/sys/vm/dirty_ratio
echo 5 | sudo tee /proc/sys/vm/dirty_background_ratio

# 5. Оптимизировать опции ФС
sudo mount -o remount,noatime,nodiratime /mnt/raid
```

### Сценарий 2: Ускорение ребилда RAID 6

**Проблема:** Ребилд массива 100+ ТБ занимает сутки.

**Решение:**
```bash
# 1. Увеличить скорость восстановления
echo 500000 | sudo tee /proc/sys/dev/raid/speed_limit_max
echo 100000 | sudo tee /proc/sys/dev/raid/speed_limit_min

# 2. Снизить нагрузку на массив (если возможно)
# Остановить не критичные сервисы
sudo systemctl stop nginx apache2

# 3. Мониторинг прогресса
watch -n 5 "cat /proc/mdstat | grep -E 'rebuild|resync'"

# 4. После завершения — вернуть нормальную скорость
echo 200000 | sudo tee /proc/sys/dev/raid/speed_limit_max
echo 1000 | sudo tee /proc/sys/dev/raid/speed_limit_min
```

### Сценарий 3: Оптимизация RAID 10 для виртуализации

**Проблема:** Смешанная нагрузка (чтение + запись), высокий IOPS.

**Решение:**
```bash
# 1. Chunk size 128K (баланс)
sudo mdadm --create /dev/md0 --level=10 --chunk=128 --raid-devices=8 \
    /dev/sd{b,c,d,e,f,g,h,i}1

# 2. Scheduler none (если NVMe) или mq-deadline (если SATA)
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler

# 3. Оптимизировать read-ahead
echo 4096 | sudo tee /sys/block/md0/queue/read_ahead_kb

# 4. Мониторинг IOPS
iostat -xz 1 | grep md0
```

### Сценарий 4: Снижение влияния scrubbing на приложения

**Проблема:** Scrubbing замедляет работу приложений.

**Решение:**
```bash
# 1. Ограничить скорость scrubbing
echo 50000 | sudo tee /proc/sys/dev/raid/speed_limit_min
echo 100000 | sudo tee /proc/sys/dev/raid/speed_limit_max

# 2. Запускать scrubbing в ночное время
# /etc/cron.d/raid-scrub
0 2 * * 0 root echo check > /sys/block/md*/md/sync_action

# 3. После завершения — вернуть нормальную скорость
echo 1000 | sudo tee /proc/sys/dev/raid/speed_limit_min
echo 200000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

---

## Диагностика производительности

### Быстрая проверка

```bash
# Состояние массива
cat /proc/mdstat

# I/O статистика
iostat -xz 1 5 | grep -E "Device|md"

# Детальная статистика md
cat /sys/block/md0/md/stripe_cache_size
cat /sys/block/md0/md/sync_speed
```

### Ключевые метрики

| Метрика | Норма | Проблема | Решение |
| :--- | :--- | :--- | :--- |
| `await` (чтение) | < 10 мс (SSD), < 20 мс (HDD) | Высокая задержка | Проверить scheduler, chunk size |
| `await` (запись) | < 20 мс (SSD), < 50 мс (HDD) | Write Penalty | Перейти на RAID 10, увеличить chunk |
| `%util` | < 80% | Перегрузка дисков | Добавить диски, снизить нагрузку |
| `mismatch_cnt` | 0 | Расхождения данных | Scrubbing, проверка SMART |
| `rebuild %` | Растёт | Идёт восстановление | Нормально, мониторить |

### Анализ с помощью fio

```bash
# Тест случайного чтения 4K (OLTP)
fio --name=randread --rw=randread --bs=4k --size=10G \
    --filename=/mnt/raid/testfile --direct=1 --ioengine=libaio \
    --iodepth=32 --numjobs=4 --runtime=60 --group_reporting

# Тест случайной записи 4K (OLTP)
fio --name=randwrite --rw=randwrite --bs=4k --size=10G \
    --filename=/mnt/raid/testfile --direct=1 --ioengine=libaio \
    --iodepth=32 --numjobs=4 --runtime=60 --group_reporting

# Тест последовательного чтения (файловый сервер)
fio --name=seqread --rw=read --bs=128k --size=10G \
    --filename=/mnt/raid/testfile --direct=1 --ioengine=libaio \
    --iodepth=16 --numjobs=1 --runtime=60 --group_reporting
```

---

## Шпаргалка по настройке

### RAID 5 (HDD, файловый сервер)
```bash
sudo mdadm --grow /dev/md0 --chunk=512
echo mq-deadline | sudo tee /sys/block/md0/queue/scheduler
echo 200000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

### RAID 6 (HDD 16+ ТБ, архив)
```bash
sudo mdadm --grow /dev/md0 --chunk=1024
echo mq-deadline | sudo tee /sys/block/md0/queue/scheduler
echo 500000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

### RAID 10 (SSD, OLTP БД)
```bash
sudo mdadm --grow /dev/md0 --chunk=64
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler
echo 4096 | sudo tee /sys/block/md0/queue/read_ahead_kb
```

### RAID 10 (SSD, виртуализация)
```bash
sudo mdadm --grow /dev/md0 --chunk=128
echo mq-deadline | sudo tee /sys/block/md0/queue/scheduler
echo 2048 | sudo tee /sys/block/md0/queue/read_ahead_kb
```

---

## Дополнительная информация

* [Влияние RAID на I/O](../../Diagnostics/Performance/DiskIO/raid_io_impact.md) — Write Penalty, Stripe Size, BBU.
* [Планировщики I/O](../../Diagnostics/Performance/DiskIO/io_scheduler_selection.md) — mq-deadline, bfq, kyber.
* [Мониторинг RAID-массивов](./monitoring.md) — настройка уведомлений и анализ логов.
* [Уровни RAID](./raid-levels.md) — сравнение характеристик и рисков.
* [fio: Тестирование производительности](../../Diagnostics/Filesystem/fio.md) — бенчмаркинг дисковой подсистемы.
