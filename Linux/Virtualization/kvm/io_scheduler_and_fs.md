# I/O планировщики и выбор файловой системы для KVM

Данный файл описывает выбор I/O планировщика (scheduler) для блочных устройств и сравнение файловых систем (ext4, XFS, Btrfs, ZFS) в контексте KVM-хостов. Стратегии хранения описаны в [Образы ВМ — Основные концепции](../vm_images/basic_concepts.md).

## Определения

**I/O Scheduler** — алгоритм ядра Linux, определяющий порядок и способ обработки блочных запросов к диску. Цель — максимизация пропускной способности (throughput) или минимизация задержки (latency) в зависимости от типа нагрузки.

**mq-deadline (Multi-Queue Deadline)** — I/O планировщик, гарантирующий, что каждый запрос будет обработан в течение заданного времени (deadline). Сбалансированный выбор для большинства workloads. Работает с multi-queue блочными устройствами.

**BFQ (Budget Fair Queuing)** — I/O планировщик, обеспечивающий справедливое распределение пропускной способности между процессами. Хорош для десктопов и интерактивных нагрузок, но добавляет overhead для высокопроизводительных NVMe.

**none (No Scheduler / Noop)** — отсутствие I/O планировщика. Запросы обрабатываются в порядке поступления. Оптимально для NVMe и SSD, где аппаратная очередь достаточно умна для оптимизации.

**noop** — устаревший термин для `none` в более ранних версиях ядра.

**ext4** — журналируемая файловая система, стандарт для большинства Linux-дистрибутивов. Поддерживает до 1 EB, snapshot через LVM, online defrag.

**XFS** — журналируемая файловая система, оптимизированная для больших файлов и высокой производительности. Высокая масштабируемость для parallel I/O.

**Btrfs** — файловая система с CoW (Copy-on-Write), встроенными снапшотами, сжатием и дедупликацией. Не рекомендуется для high-performance workloads из-за проблем с lateness.

**ZFS** — файловая система/ Volume Manager с CoW, RAID-Z, дедупликацией, шифрованием. Высокая надежность, но требует существительных ресурсов RAM.

## Базовые концепции

### Сравнение I/O планировщиков

| Планировщик | Тип очереди | Латентность | Throughput | CPU overhead | Рекомендация |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **none** | Single/Multi | Минимальная | Максимальный | Минимальный | NVMe, SSD (production) |
| **mq-deadline** | Multi-Queue | Низкая | Высокий | Низкий | SSD, SATA, универсальный |
| **BFQ** | Multi-Queue | Средняя | Средний | Средний | Десктоп, interactive |

**Выбор для KVM-хостов:**

| Тип устройства | Рекомендованный scheduler | Обоснование |
| :--- | :--- | :--- |
| **NVMe SSD** | `none` | Аппаратная очередь оптимизирует запросы |
| **SATA SSD** | `mq-deadline` | Баланс latency/throughput |
| **SAS HDD** | `mq-deadline` | Дедлайн предотвращает starvation |
| **RAID массив** | `mq-deadline` | Контроль порядка запросов |

### Настройка I/O scheduler

```bash
# Просмотр текущего scheduler
cat /sys/block/nvme0n1/queue/scheduler
# → [none] mq-deadline bfq

# Временная смена (до перезагрузки)
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler

# Постоянная настройка через udev
cat <<EOF | sudo tee /etc/udev/rules.d/60-io-scheduler.rules
# NVMe — none
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"

# SATA SSD — mq-deadline
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"

# HDD — mq-deadline
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="mq-deadline"
EOF

# Применение
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Сравнение файловых систем

| Критерий | ext4 | XFS | Btrfs | ZFS |
| :--- | :--- | :--- | :--- | :--- |
| **Макс. размер** | 1 EB | 8 EB | 16 EB | 256 ZB |
| **Снапшоты** | Через LVM | Через LVM | Нативные CoW | Нативные CoW |
| **Сжатие** | Нет | Нет | zstd, lzo, zlib | lz4, zstd |
| **Дедупликация** | Нет | Нет | Да (experimental) | Да (production) |
| ** RAID** | mdadm | mdadm | Btrfs RAID | RAID-Z (native) |
| **Online defrag** | Да | Да (_extentsize) | Нет | N/A (CoW) |
| **Поиск файлов** | Good | Good | Средний | Медленный |
| **RAM overhead** | Минимальный | Минимальный | Средний | Высокий (ARC) |
| **Рекомендация** | Универсальный | Большие файлы, DB | Desktop, backup | Storage server |

### Рекомендации по файловым системам для KVM

| Сценарий | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Хранилище образов ВМ** | XFS + noatime | Высокий throughput, минимальный overhead |
| **База данных (PostgreSQL)** | XFS + noatime + O_DIRECT | Предсказуемая latency |
| **Логи** | ext4 + noatime | Простота, надежность |
| **Backup storage** | ZFS или Btrfs | Снапшоты, дедупликация |
| **Десктоп/Workstation** | Btrfs | Снапшоты, сжатие |

### Мониторинг I/O

```bash
# Текущая статистика
iostat -xz 1 5
# → r/s, w/s, rkB/s, wkB/s, await, %util

# Мониторинг через proc
cat /proc/diskstats
cat /sys/block/nvme0n1/stat

# Анализ задержек (biolatency через bpftrace)
sudo bpftrace -e 'tracepoint:block:block_rq_complete { @usecs = hist(args->io_duration / 1000); }'
```

## Практические сценарии

### Сценарий 1: Оптимизация NVMe для ВМ

```bash
# 1. Установка none scheduler
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler

# 2. Увеличение очереди
echo 1024 | sudo tee /sys/block/nvme0n1/queue/nr_requests

# 3. Отключение merge (для random workloads)
echo 0 | sudo tee /sys/block/nvme0n1/queue/nomerges

# 4. Настройка read_ahead
echo 128 | sudo tee /sys/block/nvme0n1/queue/read_ahead_kb
```

### Сценарий 2: Настройка XFS для хранения образов ВМ

```bash
# Форматирование
mkfs.xfs -f -L vm-storage /dev/sdb1

# Монтирование с оптимизациями
mount -o noatime,nodiratime,logbufs=8,logbsize=256k /dev/sdb1 /var/lib/libvirt/images

# Добавление в fstab
echo '/dev/sdb1 /var/lib/libvirt/images xfs noatime,nodiratime,logbufs=8,logbsize=256k 0 0' | sudo tee -a /etc/fstab

# Проверка
xfs_info /var/lib/libvirt/images
```

### Сценарий 3: Бенчмарк I/O через fio

```bash
# Sequential read (simulating VM image loading)
fio --name=seq-read --directory=/var/lib/libvirt/images \
  --rw=read --bs=1M --size=1G --numjobs=4 --runtime=30 \
  --group_reporting --output-format=json

# Random write (simulating database workload)
fio --name=rand-write --directory=/var/lib/libvirt/images \
  --rw=randwrite --bs=4k --size=256M --numjobs=8 \
  --runtime=60 --group_reporting --iodepth=32 \
  --output-format=json

# Mixed random read/write (simulating typical VM workload)
fio --name=mixed --directory=/var/lib/libvirt/images \
  --rw=randrw --bs=4k --size=256M --numjobs=4 \
  --runtime=60 --group_reporting --iodepth=16 \
  --rwmixread=70 --output-format=json
```

### Сценарий 4: Миграция ext4 → XFS

```bash
# 1. Резервное копирование
rsync -avHAX /var/lib/libvirt/images/ /backup/vm-images/

# 2. Остановка ВМ
virsh shutdown --all

# 3. Форматирование
mkfs.xfs -f /dev/sdb1

# 4. Монтирование
mount /dev/sdb1 /var/lib/libvirt/images

# 5. Восстановление данных
rsync -avHAX /backup/vm-images/ /var/lib/libvirt/images/

# 6. Обновление fstab
```

## Дополнительная информация

- [Образы ВМ — Основные концепции](../vm_images/basic_concepts.md) — стратегии хранения, CoW.
- [Оптимизация KVM (2025–2026)](./performance_tuning_2026.md) — io_uring, vhost, IOThreads.
- [Сравнение ФС](../../Linux/FileSystems/filesystem_types_comparison.md) — детальное сравнение ext4, XFS, Btrfs, ZFS.
- [XFS](../../Linux/FileSystems/xfs.md) — архитектура, тюнинг.
- [ext4](../../Linux/FileSystems/ext4.md) — архитектура,limitations.
