# Выбор I/O Scheduler: практика для продакшена

## Определения

- **I/O Scheduler (Планировщик ввода-вывода):** Компонент блочного слоя ядра Linux, определяющий порядок обработки блочных запросов. Управляет очередностью, объединением (merge) и приоритизацией операций для баланса между throughput и latency.
- **blk-mq (Multi-Queue Block I/O):** Современная архитектура (ядро 3.13+) с пер-CPU программными очередями и аппаратными очередями контроллера. Заменила одноочередной блочный слой, устранив глобальную блокировку.
- **none (No-op):** Полное отсутствие планирования. Запросы передаются драйверу мгновенно. Оптимально для NVMe (64+ аппаратных очередей) и аппаратных RAID с собственным кэшем.
- **mq-deadline:** Адаптация классического Deadline под blk-mq. Разделяет очереди чтения и записи, назначает deadline каждому запросу. Чтение имеет приоритет над записью для предотвращения starva­tion приложений.
- **kyber:** Легковесный планировщик для быстрых NVMe. Использует систему токенов для ограничения активных запросов. Автоматически балансирует read/write latency.
- **BFQ (Budget Fair Queuing):** Планировщик с выделением «бюджета» каждому процессу. Обеспечивает справедливое распределение дискового времени. Эффективен для интерактивных нагрузок на HDD.
- **ionice:** Утилита для назначения приоритета класса I/O процессу. Работает с BFQ (класс 0-3) и mq-deadline (класс 2-7).

## Основные концепции

### Краткая таблица выбора

| Тип устройства | Рекомендуемый scheduler | Обоснование |
| :--- | :--- | :--- |
| **NVMe SSD** | `none` | 64+ аппаратных очередей, планирование на уровне ядра лишнее |
| **SATA SSD** | `mq-deadline` | Баланс между read/write latency |
| **HDD** | `bfq` или `mq-deadline` | BFQ — для интерактивных систем; mq-deadline — для серверов |
| **Аппаратный RAID** | `none` | Контроллер имеет собственный кэш и планировщик |
| **Виртуальные диски (VM)** | `none` | Гипервизор планирует I/O на уровне хоста |
| **Облачные диски** | `none` | Планирование делает провайдер |
| **iSCSI / NFS** | `mq-deadline` | Сетевая задержка требует балансировки |

### Архитектура blk-mq

```
Приложение
    ↓
VFS (read/write)
    ↓
bio (единица I/O)
    ↓
request_queue (очередь запросов)
    ↓
I/O Scheduler (none/mq-deadline/bfq/kyber)
    ↓
Software Queue (per-CPU) ← исключает конкуренцию за блокировки
    ↓
Hardware Queue (per-controller) ← NVMe: 64+ очередей
    ↓
Драйвер устройства → Физический диск
```

### mq-deadline: ключевые параметры тюнинга

| Параметр | Путь | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `read_expire` | `/sys/block/<dev>/queue/iosched/read_expire` | 500 мс | Максимальное время ожидания чтения |
| `write_expire` | `/sys/block/<dev>/queue/iosched/write_expire` | 5000 мс | Максимальное время ожидания записи |
| `writes_starved` | `/sys/block/<dev>/queue/iosched/writes_starved` | 2 | Сколько раз чтение может обогнать запись |
| `front_merges` | `/sys/block/<dev>/queue/iosched/front_merges` | 1 | Включить merges в начало очереди (0=выкл) |
| `fifo_batch` | `/sys/block/<dev>/queue/iosched/fifo_batch` | 16 | Количество запросов в одной «порции» |

### BFQ: ключевые параметры тюнинга

| Параметр | Путь | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `slice_idle` | `/sys/block/<dev>/queue/iosched/slice_idle` | 8 мс | Время простоя между процессами |
| `back_seek_max` | `/sys/block/<dev>/queue/iosched/back_seek_max` | 16K | Максимальный «обратный» seek |
| `back_seek_penalty` | `/sys/block/<dev>/queue/iosched/back_seek_penalty` | 2 | Штраф за обратный seek |
| `iso_readfreq` | `/sys/block/<dev>/queue/iosched/iso_readfreq` | 0 | Частота изолированных чтений |
| `low_latency` | `/sys/block/<dev>/queue/iosched/low_latency` | 1 | Режим низкой задержки (.interpolate `idle`) |

### Kyber: ключевые параметры тюнинга

| Параметр | Путь | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `read_lat_nsec` | `/sys/block/<dev>/queue/iosched/read_lat_nsec` | 2000000 (2 мс) | Целевая задержка чтения |
| `write_lat_nsec` | `/sys/block/<dev>/queue/iosched/write_lat_nsec` | 10000000 (10 мс) | Целевая задержка записи |

## Предварительные требования

```bash
# Проверка доступных планировщиков
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none

# Проверка rotational (0=SSD, 1=HDD)
cat /sys/block/sda/queue/rotational
# → 0 (SSD)

# Для NVMe:
cat /sys/block/nvme0n1/queue/rotational
# → 0
```

## Практические сценарии

### Шаг 1: Определение текущего планировщика

```bash
# Просмотр для всех устройств
for dev in /sys/block/sd* /sys/block/nvme*; do
    devname=$(basename $dev)
    sched=$(cat $dev/queue/scheduler)
    rot=$(cat $dev/queue/rotational)
    echo "$devname: scheduler=$sched rotational=$rot"
done
# → sda: [mq-deadline] kyber bfq none rotational=0
# → nvme0n1: [none] rotational=0
```

### Шаг 2: Смена планировщика на лету

```bash
# Переключение на mq-deadline для SATA SSD
echo mq-deadline | sudo tee /sys/block/sda/queue/scheduler

# Переключение на none для NVMe
echo none | sudo tee /sys/block/nvme0n1/queue/scheduler

# Проверка
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none
```

### Шаг 3: Валидация изменений

После смены планировщика необходимо проверить эффект:

```bash
# 1. Базовый замер IOPS и latency (до)
sudo fio --name=before --directory=/tmp --rw=randread --bs=4k \
  --ioengine=libaio --iodepth=32 --direct=1 --size=1G --runtime=30 --group_reporting

# 2. Смена планировщика
echo kyber | sudo tee /sys/block/sda/queue/scheduler

# 3. Повторный замер (после)
sudo fio --name=after --directory=/tmp --rw=randread --bs=4k \
  --ioengine=libaio --iodepth=32 --direct=1 --size=1G --runtime=30 --group_reporting

# 4. Сравнение
# → iops_before=50000 latency_before=0.64ms
# → iops_after=48000 latency_after=0.67ms
# → Вывод: kyber не дал прироста для данного устройства

# 5. Проверка через iostat
iostat -xz 1 3
# → Сравниваем await и aqu-sz до и после
```

### Шаг 4: Персистентная настройка через udev

Смена планировщика на лету сбрасывается при перезагрузке. Для постоянной настройки:

```bash
# Создание файла правил udev
sudo tee /etc/udev/rules.d/60-io-schedulers.rules << 'EOF'
# NVMe: без планирования (все очереди аппаратные)
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"

# SATA/SAS SSD: mq-deadline (баланс latency/throughput)
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="mq-deadline"

# HDD: bfq (интерактивная отзывчивость) или mq-deadline (сервер)
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="1", ATTR{queue/scheduler}="mq-deadline"
EOF

# Применение
sudo udevadm control --reload-rules && sudo udevadm trigger

# Проверка
cat /sys/block/sda/queue/scheduler
```

### Шаг 5: Тюнинг параметров mq-deadline

```bash
# Уменьшение read_expire для OLTP (быстрее отклик на чтение)
echo 250 | sudo tee /sys/block/sda/queue/iosched/read_expire

# Увеличение writes_starved для write-heavy нагрузок
echo 4 | sudo tee /sys/block/sda/queue/iosched/writes_starved

# Отключение front_merges если нагрузка случайная
echo 0 | sudo tee /sys/block/sda/queue/iosched/front_merges

# Проверка текущих значений
cat /sys/block/sda/queue/iosched/read_expire
cat /sys/block/sda/queue/iosched/writes_starved
```

### Шаг 6: Мониторинг через iostat

```bash
# Наблюдение за влиянием scheduler на latency
iostat -xz 1 10 | grep -E "Device|await|aqu-sz|%util"

# Или с полным выводом для анализа
iostat -xz 1 5
# → На что смотреть:
# → await — общая задержка (мс)
# → r_await / w_await — задержка чтения/записи отдельно
# → aqu-sz — средний размер очереди
# → %util — утилизация устройства
```

### Шаг 7: Проверка через ionice (приоритеты процессов)

```bash
# Запуск процесса с высоким приоритетом I/O (только с BFQ)
sudo ionice -c 1 -n 0 -p $(pgrep mysqld)
# → Класс 1 (Realtime), приоритет 0 (максимальный)

# Запуск фонового процесса с низким приоритетом
ionice -c 3 -p $(pgrep updatedb)

# Проверка текущего класса I/O процесса
ionice -p $(pgrep mysqld)
# → best-effort: prio=0

# Важно: ionice эффективен ТОЛЬКО с BFQ. С mq-deadline классы I/O игнорируются.
```

## Автоматизация и мониторинг

### Prometheus alert на изменение scheduler

```yaml
groups:
  - name: io_scheduler_alerts
    rules:
      - alert: IOSchedulerChangedUnexpectedly
        expr: |
          node_schedstat_io_scheduler != node_schedstat_io_scheduler offset 1h
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "I/O Scheduler изменён на {{ $labels.device }}"
          description: "Планировщик был изменён с {{ $labels.old_value }} на {{ $labels.new_value }}."
```

### Скрипт мониторинга эффективности scheduler

```bash
#!/bin/bash
# /usr/local/bin/check_scheduler_effectiveness.sh
DEVICE="${1:-sda}"

echo "=== Текущий scheduler ==="
cat /sys/block/$DEVICE/queue/scheduler

echo -e "\n=== Текущие параметры ==="
for param in read_expire write_expire writes_starved front_merges fifo_batch; do
    [ -f /sys/block/$DEVICE/queue/iosched/$param ] && \
    echo "$param: $(cat /sys/block/$DEVICE/queue/iosched/$param)"
done

echo -e "\n=== Текущая статистика (iostat, 1 интервал) ==="
iostat -xz 1 1 | grep -A1 "Device" | grep -v "^$"
```

## Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| После смены scheduler `await` вырос | Неподходящий scheduler для типа нагрузки | Вернуть предыдущий scheduler, провести тест `fio` |
| `ionice` не влияет на приоритет | Используется mq-deadline вместо BFQ | Переключиться на BFQ или принять, что ionice не работает |
| Scheduler сбрасывается после ребута | Нет udev-правил | Создать `/etc/udev/rules.d/60-io-schedulers.rules` |
| `bfq` вызывает рост CPU | Высокие накладные расходы BFQ на многоядерных системах | Переключиться на `mq-deadline` |
| На NVMe `none` показывает хуже, чем `mq-deadline` | Редкий случай: слишком мелкие блоки + высокая очередь | Проверить `iodepth` в `fio`, попробовать `kyber` |

## Ограничения и особые случаи

### Контейнеры (Docker, Kubernetes)

- Внутри контейнера scheduler определяется хостом. Изменение внутри контейнера требует `--privileged` или доступа к `/sys`.
- Рекомендуется настраивать scheduler на хосте через udev rules.

### Виртуализация

- В гостевой ВМ scheduler влияет только на виртуальное устройство. Реальное планирование делает гипервизор.
- Рекомендуется `none` для всех виртуальных дисков.

### Множество очередей NVMe

- NVMe может иметь 64+ аппаратных очередей (по одной на ядро CPU).
- `none` позволяет каждому ядру работать напрямую с очередью без оверхеда планировщика.
- `mq-deadline` на NVMe добавляет небольшой overhead, но может улучшить fairness.

## Дополнительная информация

### См. также

- [Планировщики I/O (overview)](../../../../Core/kernel/io_schedulers.md) — теоретические основы всех планировщиков.
- [Диагностика Block Layer через dmesg](../../../Diagnostics/Kernel/dmesg/block-layer.md) — ошибки блочного слоя.
- [fio — бенчмаркинг](../../../Diagnostics/Filesystem/fio.md) — проверка производительности после изменений.
- [Docker: I/O Performance Tuning](../../../../Docker/Docker_performance_tuning.md) — scheduler в контейнерах.
