# ClickHouse — Файловая система и хранение

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**XFS** — высокопроизводительная файловая система Linux, рекомендуемая ClickHouse для продакшена (лучше справляется с большими файлами и параллельной записью).

**ext4** — универсальная файловая система Linux; работает с ClickHouse, но уступает XFS на больших объёмах и высокой конкурентности.

**noatime** — опция монтирования, отключающая обновление времени доступа (atime); снижает нагрузку на диск.

**TRIM/discard** — механизм передачи освобождённых блоков SSD-контроллеру; поддерживается XFS и ext4.

**RAID** — избыточный массив дисков; для ClickHouse предпочтительнее JBOD/RAID-0 с репликацией на уровне ClickHouse.

**Swap** — подкачка; должна быть отключена или минимизирована для ClickHouse, чтобы избежать задержек при агрегациях в памяти.

**I/O scheduler** — планировщик диска (`mq-deadline`, `none`, `kyber`); для NVMe — `none` или `mq-deadline`.

## Основные концепции

### XFS vs ext4

| Характеристика | XFS | ext4 |
| :--- | :--- | :--- |
| Производительность больших файлов | Высокая | Средняя |
| Параллельная запись | Отличная | Хорошая |
| Восстановление после сбоя | Быстрое (journal) | Дольше (fsck) |
| Максимальный размер файла | 8 ЭБ | 16 ТБ |
| Рекомендация ClickHouse | **Предпочтительная** | Допустимая |

**Почему XFS:** ClickHouse хранит каждую колонку в отдельном файле и активно пишет крупные части при merges. XFS лучше масштабируется на параллельной записи и больших файлах.

### Опции монтирования

```bash
# Рекомендуемые опции для XFS (fstab)
/dev/nvme0n1  /var/lib/clickhouse  xfs  noatime,nodiratime,discard  0  0

# Для ext4
/dev/nvme0n1  /var/lib/clickhouse  ext4  noatime,nodiratime,discard  0  0
```

- **noatime, nodiratime** — не обновлять время доступа (снижает запись метаданных).
- **discard** — включить TRIM для SSD (или периодический `fstrim`).

### Планировщик диска

```bash
# Проверить текущий планировщик
cat /sys/block/nvme0n1/queue/scheduler
# → [none] mq-deadline kyver bfq

# Для NVMe: none или mq-deadline
echo 'none' | sudo tee /sys/block/nvme0n1/queue/scheduler

# Для HDD: mq-deadline
echo 'mq-deadline' | sudo tee /sys/block/sda/queue/scheduler
```

### RAID и диски

- **JBOD (Just a Bunch of Disks)** — предпочтительный вариант: каждый диск отдельно, репликация на уровне ClickHouse.
- **RAID-10** — допустим для локальных дисков без репликации ClickHouse.
- **RAID-5/6** — не рекомендуется: медленная перезапись при merges.
- **LVM** — допустим, но добавляет слой абстракции; предпочтительнее прямые разделы.

### Swap

```bash
# Отключить swap (рекомендуется)
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Или оставить минимальный swap с низким приоритетом
sudo sysctl vm.swappiness=1
```

**Почему:** ClickHouse выполняет агрегации и JOIN в памяти. При нехватке RAM лучше ошибка `MEMORY_LIMIT_EXCEEDED` (Code 241), чем уход в swap с падением производительности в 10–100 раз.

### I/O тестирование

```bash
# Тест последовательной записи
dd if=/dev/zero of=/var/lib/clickhouse/test bs=1M count=1024 oflag=direct

# Тест случайной записи (fio)
fio --name=randwrite --ioengine=libaio --iodepth=32 \
    --rw=randwrite --bs=4k --direct=1 --size=1G --numjobs=4 \
    --runtime=60 --group_reporting
```

## Практические сценарии

### Подготовка диска для ClickHouse

```bash
# 1. Создать раздел XFS
sudo mkfs.xfs /dev/nvme0n1

# 2. Смонтировать с оптимальными опциями
sudo mkdir -p /var/lib/clickhouse
sudo mount -o noatime,nodiratime,discard /dev/nvme0n1 /var/lib/clickhouse

# 3. Добавить в fstab
echo '/dev/nvme0n1 /var/lib/clickhouse xfs noatime,nodiratime,discard 0 0' | sudo tee -a /etc/fstab

# 4. Проверить
df -T /var/lib/clickhouse
# → xfs
mount | grep clickhouse
# → noatime,nodiratime,discard
```

### Мониторинг I/O

```bash
# Загрузка диска
iostat -xz 1

# Ожидание I/O (await) должно быть < 10 мс для NVMe
# %util не должен быть 100% постоянно
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Медленные merges | HDD или неправильный планировщик | NVMe; `none`/`mq-deadline` |
| `Too many parts` | Медленные диски, частые мелкие вставки | Батчинг; `async_insert`; NVMe |
| Высокий `await` | Перегрузка диска | Распределить merges; проверить RAID |
| Swap активен | Нехватка RAM | Отключить swap; увеличить RAM; `max_memory_usage` |
| Диск заполнен | Нет TTL / мониторинга | TTL; алерт на `disk_usage > 85%` |
| TRIM не работает | `discard` не включён | Добавить `discard` или `fstrim` по cron |

## Лучшие практики

1. **XFS** — файловая система по умолчанию для продакшена.
2. **noatime,nodiratime,discard** — обязательные опции монтирования.
3. **NVMe SSD** — для данных и Keeper-логов.
4. **JBOD + репликация ClickHouse** — вместо RAID-5/6.
5. **Отключить swap** или `vm.swappiness=1`.
6. **Планировщик `none`/`mq-deadline`** для NVMe.
7. **Мониторить `iostat`** — `await`, `%util`, `svctm`.

## Дополнительная информация

### Смежные темы

- Требования к железу и ОС — **[Производительность](./clickhouse-performance.md)**.
- Tiered Storage (S3) — **[Интеграция ClickHouse и S3](./clickhouse_s3_integration.md)**.
- Общая теория файловых систем — **[Linux: Файловые системы](../../Linux/FileSystems/)**.

### Ресурсы

- [Документация: Требования к железу](https://clickhouse.com/docs/operations/requirements)
- [Документация: Файловая система](https://clickhouse.com/docs/operations/tips)
