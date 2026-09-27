# Влияние RAID на дисковый ввод-вывод (I/O)

## Определения

- **Write Penalty (Штраф за запись):** Увеличение количества физических операций ввода-вывода при одной логической операции записи в RAID-массив с контролем четности (parity). Для RAID 5 каждая запись малого блока требует 4 физических операции: чтение старых данных + чтение старой четности + запись новых данных + запись новой четности. Для RAID 6 — 6 операций.
- **Stripe Size / Chunk Size (Размер полосы / блока):** Объем данных, записываемый на один диск массива перед переходом на следующий. Определяет баланс между IOPS (мелкие блоки) и throughput (крупные блоки). Влияет на эффективность Read-Merge и Write-Merge.
- **BBU (Battery Backup Unit) / CacheVault:** Аппаратная батарейка или суперконденсатор на RAID-контроллере, обеспечивающий сохранность данных в кэше контроллера при отключении питания. Позволяет безопасно использовать режим write-back кэширования.
- **Write-Back vs Write-Through:** Режимы кэширования на RAID-контроллере. Write-Back подтверждает запись после попадания данных в кэш контроллера (быстрее, требует BBU). Write-Through подтверждает только после физической записи на диск (медленнее, безопаснее).
- **Rebuild (Ребилд / Восстановление):** Процесс пересчета и восстановления данных на замененном диске RAID-массива. Во время ребилдаraid-массив работает в degraded-режиме, производительность падает на 30-50%.
- **Read-Miss Penalty (Штраф промаха чтения):** Для RAID 5/6 при чтении блока, который не попал в кэш контроллера, необходимо прочитать данные со всех дисков и вычислить отсутствующий блок через XOR. Для RAID 5 это 2 дополнительных I/O.

## Основные концепции

### Механизм Write Penalty

Write Penalty — ключевой фактор, определяющий производительность записи в RAID-массивах с четностью.

#### RAID 5 (Write Penalty = 4)

При случайной записи 4K-блока контроллер выполняет:

```
1. Чтение старого блока данных      (read old data)       → 1 I/O
2. Чтение старого блока четности    (read old parity)     → 1 I/O
3. Вычисление нового XOR            (CPU-bound)           → 0 I/O
4. Запись новых данных              (write new data)      → 1 I/O
5. Запись новой четности            (write new parity)    → 1 I/O
                                                           ─────────
Итого: 4 физических I/O на 1 логическую операцию
```

Это означает, что при 10K IOPS случайной записи на каждом диске, RAID 5 из 4 дисков способен выдать только 2.5K IOPS (10K / 4).

#### RAID 6 (Write Penalty = 6)

Аналогично RAID 5, но с двумя блоками четности:

```
1. Чтение старых данных             → 1 I/O
2. Чтение старой четности P         → 1 I/O
3. Чтение старой четности Q         → 1 I/O
4. Вычисление нового XOR            → 0 I/O
5. Запись новых данных              → 1 I/O
6. Запись новой четности P          → 1 I/O
7. Запись новой четности Q          → 1 I/O
                                     ─────────
Итого: 6 физических I/O на 1 логическую операцию
```

#### RAID 10 (Write Penalty = 2)

Зеркалирование не требует вычисления четности:

```
1. Запись данных на диск A          → 1 I/O
2. Запись зеркальной копии на B     → 1 I/O
                                     ─────────
Итого: 2 физических I/O на 1 логическую операцию
```

### Влияние Stripe Size на производительность

Stripe Size определяет, как данные распределяются по дискам:

| Stripe Size | IOPS | Throughput | Когда использовать |
| :--- | :--- | :--- | :--- |
| **64 КБ** | Максимальные | Средняя | Транзакционные БД (OLTP), множество мелких файлов |
| **128 КБ** | Высокие | Хорошая | Общего назначения ( databases + файловый сервер) |
| **256 КБ** | Средние | Высокая | Виртуализация, смешанная нагрузка |
| **512 КБ–1 МБ** | Низкие | Максимальная | Потоковое видео, бэкапы, большие файлы |

**Правило:** Маленький stripe → хорошо для IOPS (случайные операции). Большой stripe → хорошо для throughput (последовательные операции).

### Кэш контроллера и BBU

RAID-контроллеры имеют собственный кэш (от 256 МБ до 32 ГБ), который критически влияет на производительность:

| Режим | Кэш записи | Безопасность | Производительность | Требование |
| :--- | :--- | :--- | :--- | :--- |
| **Write-Back** | Используется | Данные в кэше защищены BBU | Максимальная (особенно для случайной записи) | BBU/Supercap + CacheVault |
| **Write-Through** | Не используется | Данные сразу на диске | Средняя (ограничена скоростью дисков) | Не требуется |
| **Write-Ahead** | Журнал | Данные в журнале + на диске | Хорошая | Не требуется |

**Критически важно:** Отключение write-back кэширования без BBU может привести к потере данных при отключении питания. Если BBU разряжена, контроллер автоматически переключается в write-through.

### Write Hole (Отверстие записи)

Проблема классических RAID-контроллеров при отключении питания:

```
Сценарий: RAID 5, запись в процессе
1. Данные A' записаны на диск 1         ✓
2. Четность P' НЕ записана на диск 3    ✗ (питание отключено)
3. Результат: данные и четность рассинхронизированы
4. При ребилде используется рассинхронизированный блок → потенциальная порча данных
```

**Решения:**
- **BBU/Supercap:** Запись кэша на диск при восстановлении питания
- **Journaling на контроллере:** Запись журнала изменений перед применением
- **CoW-ФС (ZFS, Btrfs):** Атомарное обновление указателей исключает write hole
- **mdadm bitmap:** Журнализация изменений для программного RAID

## Предварительные требования

Для диагностики RAID-массивов необходимы стандартные инструменты:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y mdadm smartmontools sysstat

# RHEL/CentOS/Fedora
sudo dnf install -y mdadm smartmontools sysstat
```

Для аппаратного RAID:

```bash
# MegaRAID (Dell, LSI)
sudo megacli -LDInfo -Lall -aALL

# HP Smart Array
sudo hpacucli ctrl all show config

# Для modernstorcli (замена megacli)
sudo storcli /c0 /eall /sall show
```

## Практические сценарии

### Шаг 1: Определение типа RAID

```bash
# Программный RAID (mdadm)
cat /proc/mdstat
# → md0 : active raid5 sdb1[0] sdc1[1] sdd1[2]
#       2930270208 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/3] [UUU]

# Проверка уровня RAID
sudo mdadm --detail /dev/md0 | grep "Raid Level"
# → Raid Level : raid5

# LVM RAID
sudo lvs -a -o +devices
# → lv_data  vg_data  Rwi---  100g  [lvm_data_rimage_0(0),lvm_data_rimage_1(0)]

# Аппаратный RAID
sudo lsblk -o NAME,TYPE,SIZE,ROTA,TRAN,VENDOR
# → sda       disk   500G    0    sata   Samsung
# → sdb       disk   500G    0    sata   Samsung
```

### Шаг 2: Оценка Write Penalty

Если RAID-массив показывает высокий `await` при случайной записи, проверьте:

```bash
# 1. Характер нагрузки: случайная vs последовательная
iostat -xz 1 3
# → sda    r/s=100   w/s=5000  r_await=2.00  w_await=25.00  rareq-sz=4.00  wareq-sz=4.00
# → rareq-sz=4 и wareq-sz=4 → случайная запись 4K → Write Penalty = 4x

# 2. Расчет эффективных IOPS
# RAID 5: реальные IOPS = (количество_дисков × IOPS_диска) / Write_Penalty
# Для 4-дискового RAID 5 с дисками по 10K IOPS:
# 4 × 10000 / 4 = 10000 IOPS (случайная запись)
# RAID 10: 4 × 10000 / 2 = 20000 IOPS

# 3. Сравнение с fio
sudo fio --name=raid5_test --directory=/mnt/raid5 --rw=randwrite --bs=4k \
  --ioengine=libaio --iodepth=32 --direct=1 --size=1G --numjobs=4 --runtime=30 --group_reporting
```

### Шаг 3: Мониторинг состояния массива

```bash
# Статус программного RAID
cat /proc/mdstat
# → [UU]  — все диски в порядке
# → [U_]  — один диск выпал (degraded)
# → [UUU] — все 3 диска работают (RAID 5)

# Скорость ребилда (если идет восстановление)
cat /proc/mdstat | grep -E "resync|rebuild|reshape"
# → [==>....]  resync = 60.2% (7582464/12582912) finish=45.0min speed=24536K/sec

# Ограничение скорости ребилда (если влияет на приложения)
cat /proc/sys/dev/raid/speed_limit_max
# → 200000 (KB/s)

# Временное снижение (чтобы не нагружать диск)
echo 50000 | sudo tee /proc/sys/dev/raid/speed_limit_max
```

### Шаг 4: Диагностика BBU и кэша

```bash
# MegaRAID (Dell PERC)
sudo megacli -LDInfo -Lall -aALL | grep -E "Cache|Write|BBU"
# → Cache Policy    : WriteBack, Read Ahead, Direct, No Write Cache if Bad BBU
# → BBU Status      : OK

# Если BBU разряжен:
# → Cache Policy    : WriteThrough, Read Ahead, Direct, No Write Cache if Bad BBU
# → "No Write Cache if Bad BBU" означает, что write-back отключен из-за BBU

# HP Smart Array
sudo hpacucli ctrl all show config | grep -E "Cache|Battery"
# → Cache Status: OK
# → Battery/Capacitor Status: OK

# Проверка состояния BBU через sysfs (для некоторых контроллеров)
cat /sys/block/sda/device/enclosure*/slot*/power_supply*/status
```

### Шаг 5: Анализ влияния ребилда на I/O

```bash
# Мониторинг во время ребилда
watch -n2 "cat /proc/mdstat | grep -E 'resync|rebuild' && iostat -xz 1 1 | grep -E 'Device|sda|sdb|sdc'"

# Типичные наблюдения:
# → await на дисках вырастает в 3-5 раз
# → %util приближается к 100%
# → Приложения испытывают задержки

# Приоритет восстановления (谓词 Schedule)
cat /sys/block/md0/md/group_thread_cnt
# → 2 (количество потоков ребилда; увеличение ускоряет, но нагружает CPU)
```

### Шаг 6: Оптимизация для разных нагрузок

#### Для OLTP-баз данных (высокий IOPS, случайная запись)

```bash
# Рекомендация: RAID 10 (Write Penalty = 2)
# Минимальный stripe: 64K
# Write-Back кэш с BBU
# Если RAID 5/6 — увеличить stripe до 256K+ для снижения количества операций

# Проверка stripe size (mdadm)
sudo mdadm --detail /dev/md0 | grep -i chunk
# → chunk size : 512K

# Для аппаратного RAID:
sudo megacli -LDInfo -Lall -aALL | grep -i stripe
# → Strip Size : 64 KB
```

#### Для файлового сервера (последовательные операции)

```bash
# RAID 5 или RAID 6 допустимы (Write Penalty компенсируется larger sequential blocks)
# Stripe: 256K-1M
# Write-Back кэш

# Проверка sequential throughput
sudo fio --name=seq_test --directory=/mnt/raid --rw=write --bs=1M \
  --ioengine=libaio --iodepth=1 --direct=1 --size=4G --runtime=30
```

#### Для виртуализации (смешанная нагрузка)

```bash
# RAID 10 или RAID 50
# Stripe: 128K-256K
# Write-Back кэш с BBU
# Если диски >10 ТБ — RAID 6 или RAID 60 (защита от URE при ребилде)
```

## Автоматизация и мониторинг

### Prometheus alerts для RAID

```yaml
groups:
  - name: raid_alerts
    rules:
      - alert: RAIDArrayDegraded
        expr: md_disks_active{state="active"} < md_disks_total
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "RAID массив {{ $labels.device }} деградирован"
          description: "Активных дисков: {{ $value }}, требуются: больше. Проверьте /proc/mdstat."

      - alert: RAIDRebuildSlow
        expr: rate(md_rebuild_speed_bytes_per_sec[5m]) < 10485760
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Медленный ребилд на {{ $labels.device }}"
          description: "Скорость ребилда менее 10 МБ/с. Рассмотрите временное снижение нагрузки."

      - alert: RAIDHighWriteLatency
        expr: |
          avg by(device) (
            rate(node_disk_write_time_seconds_total{device=~"md.*"}[5m]) /
            rate(node_disk_writes_completed_total{device=~"md.*"}[5m])
          ) > 0.02
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка записи на RAID {{ $labels.device }}"
          description: "w_await > 20ms. Проверьте Write Penalty и BBU."
```

## Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `w_await` >> `r_await` на RAID 5 | Write Penalty при случайной записи 4K | `iostat -xz 1` (смотрим `wareq-sz`) | Переход на RAID 10 или увеличение stripe size |
| `await` растет при ребилде | Диски загружены восстановлением | `cat /proc/mdstat` (resync %) | Снизить `speed_limit_max`, отложить ребилд на окно обслуживания |
| Write-Through вместо Write-Back | BBU разряжен или неисправен | `megacli -LDInfo -Lall -aALL` | Заменить BBU/CacheVault |
| `biolatency` показывает пики >100ms | Write hole или ошибки на дисках | `dmesg | grep -iE "error|timeout"` | Проверить `smartctl`, заменить неисправный диск |
| RAID 5 на дисках >10 ТБ | URE при ребилде (вероятность ~100%) | `smartctl -l selftest` | Миграция на RAID 6/RAID 10 |
| Низкий random write IOPS | Write Penalty + маленький stripe | `fio --rw=randwrite --bs=4k` | Увеличить stripe, добавить диски, перейти на RAID 10 |

## Ограничения и особые случаи

### Hardware RAID vs Software RAID (mdadm)

| Критерий | Hardware RAID | Software RAID (mdadm) |
| :--- | :--- | :--- |
| Write-Back кэш | Да (с BBU) | Нет (использует Page Cache ОС) |
| Write Penalty | Контроллер оптимизирует | Ядро оптимизирует (менее эффективно) |
| Производительность CPU | Разгружает CPU хоста | Использует CPU хоста |
| Переносимость | Привязка к контроллеру | Переносимость между серверами |
| Стоимость | Высокая (контроллер + BBU) | Нулевая (ПО в составе ядра) |

### Виртуализация

- В гостевой ВМ RAID-массив виртуализируется. `iostat` показывает виртуальные диски.
- `%steal` > 5% указывает на проблему на уровне хоста, а не RAID.
- Для точной диагностики необходим доступ к метрикам хоста (гипервизора).

### SSD в RAID

- Write Penalty на SSD менее критична из-за высоких IOPS (десятки тысяч).
- RAID 5 на SSD допустим для read-heavy нагрузок.
- Для write-heavy нагрузок на SSD рекомендуется RAID 10.
- TRIM必须 быть поддерживается на уровне RAID-контроллера или ядра (mdadm 3.7+).

## Дополнительная информация

### См. также

- [Уровни RAID: технические характеристики](../../../../FileSystems/RAID/raid-levels.md) — детальный разбор каждого уровня RAID.
- [Диагностический чеклист I/O](./diagnostic_checklist.md) — пошаговый алгоритм поиска проблем.
- [fio — бенчмаркинг дисков](../../../Diagnostics/Filesystem/fio.md) — проверка производительности RAID-массивов.
- [SMART-мониторинг дисков](../../../Diagnostics/Hardware/smartctl/disk_health_check.md) — проверка здоровья дисков в RAID.
