# SSD: Burst I/O и деградация производительности

## Definitions

**Burst I/O на SSD** — явление, при котором кратковременные пиковые нагрузки приводят к резкому росту latency и падению throughput, несмотря на высокие заявленные характеристики накопителя.

**Write Amplification (WA)** — коэффициент, показывающий, во сколько раз фактический объём записи на NAND превышает объём данных, полученных от хоста. `WA = (запись на NAND) / (запись от хоста)`.

**Garbage Collection (GC)** — фоновый процесс контроллера SSD по перемещению валидных данных из частично заполненных блоков для их последующего стирания и освобождения под новые записи.

## Basic Concepts

### Архитектурные причины деградации

Проблема коренится в физике NAND flash и работе контроллера SSD.

**1. Garbage Collection**

NAND flash нельзя перезаписать напрямую — блок необходимо сначала стереть. При интенсивной записи контроллер активирует фоновую garbage collection: перемещает валидные страницы из «грязных» блоков в новые, чтобы освободить блоки для стирания.

Этот процесс создаёт **микропаузы** — запросы от хоста ожидают, пока контроллер завершит внутреннюю переупаковку.

**2. Write Amplification**

Мелкий random I/O заставляет контроллер перезаписывать целые блоки NAND, хотя изменились лишь отдельные страницы. Фактический объём записи многократно превышает полезный трафик.

```
WA = 1   — идеально (последовательная запись)
WA = 3–10 — типично для мелкого random I/O
```

Последствия: повышенный износ flash-ячеек (сокращение ресурса TBW) и рост latency из-за дополнительных внутренних операций.

**3. Queue Depth saturation**

Контроллер SSD имеет ограниченную глубину очереди команд. Когда burst-нагрузка исчерпывает очередь, новые запросы ждут обработки на стороне хоста. Результат — **скачки latency**, при этом CPU может оставаться свободным.

Связанные параметры:
- `/sys/block/sdX/queue/nr_requests` — глубина очереди на стороне Linux
- `iodepth` в fio — глубина очереди на стороне приложения

**4. SLC-кэш exhaustion**

Большинство потребительских и часть enterprise SSD используют SLC-кэш (псевдо-SLC на базе TLC/QLC). При непрерывной записи кэш заполняется, и контроллер переключается на прямую запись в TLC/QLC — throughput падает в 3–10 раз.

### Взаимосвязь факторов

```
Мелкий random I/O / Burst-запись
    ↓
Write Amplification ↑
    ↓
Garbage Collection активнее
    ↓
Контроллер занят внутренней переупаковкой
    ↓
Queue Depth заполняется → latency растёт, throughput падает
```

## Practical Scenarios

### Минимизация эффекта burst I/O

**1. Асинхронный I/O для параллельных операций**

Используйте асинхронные интерфейсы вместо синхронных операций:

- **`io_uring`** — современный интерфейс ядра (5.1+), минимизирует накладные расходы на системные вызовы. Подробности: [io_uring](../../Core/kernel/io_uring.md).
- **`libaio`** — Linux AIO, legacy-альтернатива с ограничениями.

**2. Настройка очереди команд**

```bash
# Проверить текущее значение
cat /sys/block/sdX/queue/nr_requests

# Увеличить (например, до 128)
echo 128 > /sys/block/sdX/queue/nr_requests
```

Большая очередь позволяет обрабатывать больше запросов параллельно, но не решает проблему GC внутри SSD.

**3. Выбор I/O Scheduler**

```bash
# Проверить текущий планировщик
cat /sys/block/sdX/queue/scheduler

# Для NVMe — none (FCFS) или mq-deadline
echo none > /sys/block/sdX/queue/scheduler

# Для SATA/SAS SSD — mq-deadline
echo mq-deadline > /sys/block/sdX/queue/scheduler
```

`none` минимизирует накладные расходы на быстрых NVMe. `mq-deadline` обеспечивает предсказуемые задержки для SATA SSD. Подробности: [I/O Schedulers](../../Core/kernel/io_schedulers.md).

**4. Direct I/O для мелкого random I/O**

Обход kernel page cache устраняет двойное кэширование и лишние копирования:

```bash
# Тест с direct I/O
dd if=/dev/zero of=testfile bs=4k oflag=direct

# В приложениях: флаги O_DIRECT (C), direct=1 (fio)
```

В `fio`: `--ioengine=libaio --direct=1` или `--ioengine=io_uring --direct=1`. Подробности: [fio](../../Diagnostics/Filesystem/fio.md).

**5. Регулярный TRIM**

Своевременный TRIM снижает нагрузку на garbage collection. Подробности: [fstrim: обслуживание SSD](../../SystemAdministration/fstrim_ssd_maintenance.md).

```bash
# Ручной запуск
sudo fstrim -v /

# Активация автоматического таймера
sudo systemctl enable --now fstrim.timer
```

**6. Мониторинг latency и IOPS**

```bash
# iostat — общая картина каждую секунду
iostat -x 1 /dev/sdX

# biosnoop (требует bcc-tools) — latency каждого запроса
sudo biosnoop

# blktrace — низкоуровневая трассировка
blktrace -d /dev/sdX -o - | blkparse -i -
```

Ключевые метрики в `iostat -x`:
- `await` — среднее время ожидания запроса (мс); для SSD норма < 1 мс, > 5 мс — деградация
- `%util` — утилизация устройства; близко к 100% означает bottleneck
- `w_await` — задержка записи (ключевой индикатор GC-пауз)

Типичные значения производительности:

| Тип накопителя | Seq Read (МБ/с) | Seq Write (МБ/с) | Rand Read 4K (IOPS) |
| :--- | :--- | :--- | :--- |
| **HDD 7200 RPM** | 100–200 | 80–150 | 100–200 |
| **SATA SSD** | 500–550 | 450–500 | 50K–100K |
| **NVMe PCIe 3.0** | 2000–3500 | 1500–3000 | 300K–600K |
| **NVMe PCIe 4.0** | 5000–7500 | 4000–6500 | 600K–1M+ |

Подробные бенчмарки: [fio](../../Diagnostics/Filesystem/fio.md).

### Диагностика теплового троттлинга

NVMe-накопители могут снижать производительность при перегреве (> 70°C):

```bash
# Проверить температуру NVMe
sudo smartctl -a /dev/nvme0 | grep Temperature
sudo nvme smart-log-add /dev/nvme0
```

При троттлинге: улучшить охлаждение, ограничить throughput на уровне приложения.

## Additional Information

### Over-Provisioning (OP)

Enterprise SSD имеют зарезервированную область (7–28% от ёмкости), недоступную пользователю. Больший OP снижает write amplification и даёт больше «свободных» блоков для garbage collection.

### Enterprise vs потребительские SSD

| Параметр | Потребительский SSD | Enterprise SSD |
| :--- | :--- | :--- |
| **SLC-кэш** | Динамический (TLC/QLC в псевдо-SLC) | Минимальный или отсутствует |
| **Запись при исчерпании кэша** | Падение в 3–10× | Стабильная |
| **DRAM-кэш** | Не всегда есть | Всегда |
| **Power-loss protection** | Нет | Конденсаторы (PLP) |
| **Смешанные нагрузки** | Значительная деградация | Предсказуемое поведение |

### Связанные темы

[I/O Schedulers](../../Core/kernel/io_schedulers.md), [io_uring](../../Core/kernel/io_uring.md), [fio — бенчмарки I/O](../../Diagnostics/Filesystem/fio.md), [Оптимизация производительности ФС](../../FileSystems/performance_tuning.md), [Диагностика I/O](../../Diagnostics/Performance/disk_io_troubleshooting.md), [fstrim: обслуживание SSD](../../SystemAdministration/fstrim_ssd_maintenance.md), [smartctl — мониторинг здоровья дисков](../../Diagnostics/Hardware/smartctl/disk_health_check.md).
