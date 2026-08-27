# OS тюнинг для Apache Kafka

**OS тюнинг** — это настройка параметров ядра Linux и подсистемы ввода-вывода для обеспечения стабильной производительности Kafka-брокера. Kafka критически зависит от Page Cache, сетевых буферов и эффективной работы с диском.

---

## Определения

- **Page Cache:** Кэш страниц в оперативной памяти ОС. Kafka использует его для хранения данных, что позволяет достичь высокой пропускной способности без выделения большого heap.
- **THP (Transparent Huge Pages):** Функция ядра Linux для автоматического управления большими страницами памяти. В Kafka вызывает latency spikes и должен быть отключен.
- **Swappiness:** Параметр ядра (0-100), определяющий склонность ОС к выгрузке страниц в swap. Для Kafka рекомендуется минимальное значение.
- **Dirty Pages:** Страницы в Page Cache, которые были изменены, но еще не записаны на диск.
- **File Descriptors:** Ограничение на количество открытых файлов (сетевые соединения + файлы данных Kafka).
- **vm.max_map_count:** Максимальное количество memory-mapped областей. Kafka использует mmap для индексов логов.
- **I/O Scheduler:** Алгоритм планирования дисковых операций. Для SSD рекомендуется `none` или `mq-deadline`.
- **noatime:** Опция монтирование файловой системы, отключающая обновление времени доступа к файлам.
- **JBOD (Just a Bunch of Disks):** Конфигурация без RAID, где каждый диск управляется отдельно. Kafka предпочитает JBOD с собственным управлением партициями.
- **Ulimit:** Ограничения пользователя на системные ресурсы.

---

## Основные концепции

### Почему OS критичен для Kafka

Kafka — это распределенная система хранения журналов, чья производительность ограничена не CPU, а:

1. **Page Cache:** Данные читаются из ОЗУ (если горячие), а не с диска
2. **Сеть:** Высокая пропускная способность критична для репликации и клиентов
3. **Диск:** Последовательная запись сегментов логов требует минимального времени seek

```
┌─────────────────────────────────────────────────────┐
│                    Kafka Broker                      │
├─────────────────────────────────────────────────────┤
│  Page Cache (60-70% RAM)                            │
│  ├── Данные топиков (горячие)                      │
│  └── Индексы смещений                               │
├─────────────────────────────────────────────────────┤
│  Network Buffers                                    │
│  ├── Socket buffers                                 │
│  └── TCP буферы                                     │
├─────────────────────────────────────────────────────┤
│  Disk I/O                                           │
│  ├── Сегменты логов (последовательная запись)       │
│  └── Индексы                                        │
└─────────────────────────────────────────────────────┘
```

### Влияние параметров ядра

| Параметр | Значение по умолчанию | Рекомендуемое | Влияние |
|----------|----------------------|---------------|---------|
| `vm.swappiness` | 60 | 1 | Предотвращает выгрузку Page Cache |
| `vm.dirty_ratio` | 20 | 10-15 | Ранний flush грязных страниц |
| `vm.dirty_background_ratio` | 10 | 5-7 | Фоновый flush без блокировки |
| `vm.max_map_count` | 65530 | 262144 | Для memory-mapped индексов |
| `net.core.rmem_max` | 212992 | 16777216 | Размер буфера приема |
| `net.core.wmem_max` | 212992 | 16777216 | Размер буфера отправки |
| `net.ipv4.tcp_rmem` | автоматически | 4096 87380 16777216 | Диапазон TCP буфера приема |
| `net.ipv4.tcp_wmem` | автоматически | 4096 65536 16777216 | Диапазон TCP буфера отправки |
| `net.ipv4.tcp_window_scaling` | 1 | 1 | Включить масштабирование TCP окна |
| `net.core.netdev_max_backlog` | 1000 | 10000-30000 | Очередь сетевого устройства |

### Transparent Huge Pages (THP)

THP может вызвать проблемы:
- **Latency spikes:** Дефрагментация страниц в фоне блокирует процесс
- **CPU overhead:** Ядро тратит ресурсы на управление огромными страницами
- **Непредсказуемость:** Время пауз становится нестабильным

**Всегда отключайте THP для Kafka:**
```bash
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
```

### Настройки файловой системы

| ФС | Опции монтирования | Особенности |
|----|-------------------|-------------|
| **XFS** | `noatime,nodiratime,logbufs=8,logbsize=256k` | Рекомендуется для Kafka, высокая производительность с большими файлами |
| **EXT4** | `noatime,data=writeback,nobarrier` | Альтернатива, требует отключения барьеров для производительности |
| **ZFS** | `noatime,lz4-compress` | Для кластеров с включенным сжатием |

**Важно:** Опция `nobarrier` или `data=writeback` может привести к потере данных при отключении питания, но Kafka имеет репликацию для защиты.

### File Descriptors

Каждое сетевое соединение и каждый открытый файл лога потребляет file descriptor:
- Рекомендуемое значение: `ulimit -n 1000000` или выше
- Каждый топик с множеством партиций открывает несколько файлов (данные + индексы)

### I/O Scheduler

| Тип диска | Рекомендуемый scheduler | Причина |
|-----------|------------------------|---------|
| **NVMe** | `none` или `none` | Нет механического seek |
| **SSD** | `mq-deadline` или `none` | Оптимизация для NAND |
| **HDD** | `mq-deadline` | Улучшение последовательного доступа |

Проверить и изменить:
```bash
# Текущий scheduler
cat /sys/block/sda/queue/scheduler

# Изменение (временное)
echo mq-deadline > /sys/block/sda/queue/scheduler
```

---

## Практические сценарии

### Сценарий 1: Базовый production-тюнинг

Файл `/etc/sysctl.d/99-kafka.conf`:
```bash
# Предотвращение выгрузки Page Cache
vm.swappiness = 1

# Ранний flush грязных страниц
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5

# Memory-mapped индексы
vm.max_map_count = 262144

# Сетевые буферы
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_window_scaling = 1
net.core.netdev_max_backlog = 30000

# TCP keepalive для обнаружения "мертвых" соединений
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 3
```

Применение:
```bash
sudo sysctl -p /etc/sysctl.d/99-kafka.conf
```

### Сценарий 2: Отключение THP

Файл `/etc/systemd/system/disable-thp.service`:
```ini
[Unit]
Description=Disable Transparent Huge Pages for Kafka

[Service]
Type=oneshot
ExecStart=/bin/bash -c "echo never > /sys/kernel/mm/transparent_hugepage/enabled && echo never > /sys/kernel/mm/transparent_hugepage/defrag"

[Install]
WantedBy=multi-user.target
```

Или вручную:
```bash
# Проверка текущего статуса
cat /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag

# Отключение
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
```

### Сценарий 3: Настройка File Descriptors

Файл `/etc/security/limits.d/kafka.conf`:
```bash
kafka  soft  nofile  1000000
kafka  hard  nofile  1000000
kafka  soft  nproc   65536
kafka  hard  nproc   65536
```

Проверка:
```bash
ulimit -n
su - kafka -c 'ulimit -n'
```

### Сценарий 4: Монтирование дисков для Kafka

Файл `/etc/fstab`:
```bash
# Для данных Kafka
/dev/sdb1 /kafka-data xfs defaults,noatime,nodiratime,logbufs=8,logbsize=256k 0 2

# Для логов Kafka (отдельный диск)
/dev/sdc1 /kafka-logs xfs defaults,noatime,nodiratime 0 2
```

Монтирование:
```bash
mkdir -p /kafka-data /kafka-logs
mount -a
```

### Сценарий 5: Настройка I/O Scheduler

Скрипт `/usr/local/bin/kafka-io-scheduler.sh`:
```bash
#!/bin/bash
DISKS=("sda" "sdb" "sdc" "sdd")

for disk in "${DISKS[@]}"; do
    if [ -f "/sys/block/$disk/queue/scheduler" ]; then
        current=$(cat /sys/block/$disk/queue/scheduler)
        if [[ "$current" == *"none"* ]] || [[ "$current" == *"mq-deadline"* ]]; then
            echo "Disk $disk: scheduler already set to optimal"
        else
            echo "Setting $disk to mq-deadline"
            echo mq-deadline > /sys/block/$disk/queue/scheduler
        fi
    fi
done
```

### Сценарий 6: Настройка сетевых параметров для cross-DC репликации

Для MirrorMaker 2 между дата-центрами с высокой задержкой:
```bash
# Увеличение TCP окон для пропускной способности × задержка
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
```

---

## Дополнительная информация

### Проверка текущих параметров

```bash
# Проверка всех параметров Kafka
cat /etc/sysctl.d/99-kafka.conf

# Проверка THP
cat /sys/kernel/mm/transparent_hugepage/enabled

# Проверка I/O scheduler
cat /sys/block/sda/queue/scheduler

# Проверка file descriptors
ulimit -n
cat /proc/$$(pgrep -f kafka)/limits | grep "open files"

# Проверка монтирования
mount | grep kafka-data
```

### Мониторинг

- **Page Cache:** `free -h` (смотреть на `buff/cache`)
- **Dirty Pages:** `cat /proc/meminfo | grep Dirty`
- **I/O wait:** `iostat -x 1` (смотреть на `%util` и `await`)
- **THP allocation:** `grep -i AnonHugePages /proc/meminfo`

### Автоматизация

Используйте Ansible или аналогичные инструменты для применения настроек на всех узлах кластера. Пример роли: [OS тюнинг в Ansible](./kafka_ansible_deployment.md).

### См. также
- **[JVM и GC тюнинг](./kafka_jvm_gc_tuning.md)** — настройки Java Virtual Machine
- **[Ansible деплой](./kafka_ansible_deployment.md)** — автоматизация настройки ОС
- **[Strimzi оператор](./strimzi_kafka_operator.md)** — параметры resources в Kubernetes
- **[Производительность Kafka](./kafka_overview.md)** — архитектура производительности
