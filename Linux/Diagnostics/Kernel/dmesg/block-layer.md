# Диагностика Block Layer через dmesg

## Определения

**Block Layer** — подсистема ядра Linux, отвечающая за обработку запросов ввода-вывода между файловыми системами и устройствами хранения. Архитектура **blk-mq** (multi-queue, ядро 3.13+) заменила однопоточную модель, обеспечивая параллельную обработку I/O на многоядерных системах через программные очереди (per-CPU) и аппаратные очереди (per-controller).

**Сообщения Block Layer в dmesg** — диагностические выводы ядра, указывающие на ошибки ввода-вывода, проблемы с очередями запросов, таймауты команд и неисправности устройств хранения. Эти сообщения являются первым индикатором проблем с дисками, RAID-массивами, NVMe-накопителями и контейнерами хранилища (LVM, dm-*).

---

## Базовые концепции

### Архитектура blk-mq

```
Файловая система
       ↓
    bio (единица I/O)
       ↓
  request_queue (очередь запросов)
       ↓
   I/O Scheduler (mq-deadline/bfq/none)
       ↓
  Software Queue (per-CPU)
       ↓
  Hardware Queue (per-controller)
       ↓
   Устройство хранения
```

Ключевые параметры очереди:
*   **`nr_requests`** — максимальное количество запросов в очереди (по умолчанию 256, для NVMe рекомендуется 1024). Путь: `/sys/block/<device>/queue/nr_requests`.
*   **Hardware queue depth** — максимальное количество одновременных команд контроллера (NVMe: до 65535, SATA: 32).
*   **`queue_depth`** — глубина очереди SCSI-устройства. Путь: `/sys/block/<device>/device/queue_depth`.

### Типы ошибок Block Layer в dmesg

| Сообщение | Уровень | Описание |
|:---|:---|:---|
| `blk_update_request: I/O error` | err | Базовая ошибка ввода-вывода на устройстве |
| `Buffer I/O error` | err | Ошибка чтения/записи буферного блока |
| `end_request: I/O error` | err | Завершение запроса с ошибкой (старый формат) |
| `sd X:Y:Z: [sdX] tag#XX cmd timeout` | err | Таймаут SCSI/SATA команды |
| `ataX: COMRESET failed` | err | Потеря связи с SATA-устройством |
| `task abort: ...` | err | Принудительное завершение SCSI-задачи |
| `Partition table not valid` | warn | Повреждение таблицы разделов |

---

## Практические сценарии

### Поиск ошибок I/O в dmesg

```bash
# Все ошибки block layer
dmesg -T | grep -iE "blk_update_request|I/O error|Buffer I/O|end_request|io error"

# Ошибки конкретного устройства
dmesg -T | grep -iE "sd[a-z]|nvme|ata.*error|ata.*reset"

# Таймауты SCSI-команд
dmesg -T | grep -iE "cmd timeout|task abort|reset.*link|hard reset"
```

### Интерпретация blk_update_request

Сообщение `blk_update_request: I/O error, dev sdX, sector XXXXX op 0x0 (READ/WRITE)` содержит:
*   **`dev sdX`** — устройство
*   **`sector`** — сектор диска ( можно преобразовать в LBA: `sector / 2048` для 4K-секторов)
*   **`op 0x0`** — тип операции: `0x0` = READ, `0x1` = WRITE
*   **`flags`** — флаги запроса (DRA, FUA, SYNC)

**Действия:**
```bash
# 1. Определить устройство и раздел
lsblk /dev/sdX

# 2. Проверить SMART-состояние
sudo smartctl -a /dev/sdX | grep -E "SMART overall|Reallocated|Current_Pending|Offline_Uncorrectable"

# 3. Проверить hardware-сбросы линка
dmesg -T | grep -i "hard resetting link" | grep -i "sdX"

# 4. Проверить I/O scheduler устройства
cat /sys/block/sdX/queue/scheduler

# 5. Проверить nr_requests
cat /sys/block/sdX/queue/nr_requests
```

### Анализ таймаутов SCSI/SATA

```bash
# Поиск таймаутов и сбросов
dmesg -T | grep -iE "cmd timeout|task abort|COMRESET|hard reset|link reset"

# Интерпретация SCSI Sense Key
dmesg | grep -i "Sense Key"
# → Sense Key : Medium Error      — аппаратная ошибка.medium (坏道)
# → Sense Key : Hardware Error    — фатальный сбой контроллера/диска
# → Sense Key : Illegal Request   — невалидная команда (совместимость)
# → Sense Key : Unit Attention    — устройство было сброшено/перезапущено
```

### Диагностика NVMe через dmesg

```bash
# NVMe-specific ошибки
dmesg -T | grep -iE "nvme|nvme0|nvme1"

# Ключевые паттерны:
# → nvme nvme0: I/O 0 (Q0) timeout, completion polled
# → nvme nvme0: Properties changed -138
# → nvme0n1: detected error count: 5
# → AER: {Advanced Error Reporting} Corrected/Uncorrected

# Проверка ошибок AER
dmesg -T | grep -iE "aer|pcie.*error"
```

### Анализ queue depth issues

Когда очередь запросов заполняется:
```bash
# Проверка текущего состояния очереди
cat /sys/block/sdX/queue/nr_requests
cat /sys/block/sdX/inflight

# Если inflight ~= nr_requests, возможны задержки
# Решение: увеличить nr_requests
echo 1024 | sudo tee /sys/block/sdX/queue/nr_requests
```

Сообщения в dmesg при проблемах с очередью:
```
sd 0:0:0:0: [sda] tag#XX queue is frozen
sd 0:0:0:0: [sda] task abort: SCPI 0
```

### Диагностика LVM/device-mapper через dmesg

```bash
# Ошибки device-mapper
dmesg -T | grep -iE "dm-|device-mapper|dm_thin|thin_pool"

# Ключевые паттерны:
# → device-mapper: thin: Device does not support discards
# → device-mapper: thin: No free data blocks
# → device-mapper: bufio: dm_bufio_get_block: invalid block
```

### Корреляция с другими инструментами

```bash
# dmesg + iostat: сопоставление ошибок с I/O метриками
iostat -xz 1 5 | grep -A5 "sdX"

# dmesg + smartctl: проверка SMART после ошибок в dmesg
sudo smartctl -l error /dev/sdX

# dmesg + lsblk: определение типа устройства
lsblk -d -o NAME,ROTA,DISC-MAX,SCHED

# dmesg + cat /proc/diskstats: подсчет ошибок
cat /proc/diskstats | grep "sdX"
# Поля 10 (reads completed), 11 (reads merged), 12 (sectors read), 13 (ms spent reading)
# Поля 14 (writes completed), 15 (writes merged), 16 (sectors written), 17 (ms spent writing)
# Поле 10 (I/O in progress), 11 (ms spent doing I/Os), 12 (weighted ms doing I/Os)
```

---

## Дополнительная информация

### Связанные темы

*   [**I/O Scheduler**](../../../Core/kernel/io_schedulers.md) — архитектура mq-deadline, bfq, none, kyber.
*   [**SSD/NVMe Burst I/O**](../../../Core/kernel/ssd_burst_io.md) — архитектура блочного слоя, tag set, queue depth.
*   [**Обзор dmesg**](./index.md) — общая архитектура kmsg.
*   [**Использование dmesg**](./usage.md) — фильтрация и форматирование вывода.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
*   [**SMART-диагностика дисков**](../../Hardware/smartctl/index.md) — аппаратный мониторинг накопителей.
*   [**Диагностика iSCSI**](../../../Networking/iSCSI/iscsi_diagnostics.md) — ошибки SCSI-стека.
