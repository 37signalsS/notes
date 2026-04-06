# Мониторинг RAID-массивов

## Определения

**Мониторинг RAID** — непрерывное отслеживание состояния массива, дисков-участников и процессов восстановления (rebuild/reshape).

## Основные концепции

### Источники информации

| Источник | Команда | Описание |
| :--- | :--- | :--- |
| `/proc/mdstat` | `cat /proc/mdstat` | Быстрый статус всех массивов (ядро) |
| `mdadm --detail` | `mdadm --detail /dev/mdX` | Детальная информация о массиве |
| `mdadm --examine` | `mdadm --examine /dev/sdX` | Информация о суперблоке диска |
| SMART | `smartctl -a /dev/sdX` | Здоровье физических дисков |

## Практические сценарии

### Быстрая проверка состояния

```bash
# Статус всех массивов в реальном времени
watch -n 1 cat /proc/mdstat
```

**Расшифровка вывода:**

```
Personalities : [raid1] [raid6] [raid5] [raid4]
md0 : active raid1 sdb1[1] sda1[0]
      1048576 blocks super 1.2 [2/2] [UU]
      bitmap: 0/8 pages [0KB], 65536KB chunk

md1 : active raid5 sdd1[3] sdc1[2] sdb1[1]
      2097152 blocks super 1.2 level 5, 512k chunk, algorithm 2 [3/3] [UUU]
```

| Символ | Значение |
| :--- | :--- |
| `[UU]` | Все диски в RAID 1 работают |
| `[UUU]` | Все 3 диска в RAID 5 работают |
| `[_U]` | Один диск в RAID 1 сбойный |
| `[U_]` | Один диск в RAID 1 сбойный (другой) |
| `[U_U]` | Один диск в RAID 5 сбойный |
| `[>..........]` | Идёт rebuild/resync (прогресс) |
| `recovery = 45.2%` | Процент восстановления |

### Детальная информация о массиве

```bash
sudo mdadm --detail /dev/md0
```

**Ключевые поля вывода:**

```
Version : 1.2
Creation Time : Wed Mar  4 10:00:00 2025
    Raid Level : raid1
    Array Size : 1048576 (1024.00 MiB)
 Used Dev Size : 1048576 (1024.00 MiB)
  Raid Devices : 2
 Total Devices : 2
   Persistence : Superblock is persistent

    Update Time : Wed Mar  4 12:00:00 2025
          State : active, clean   # ← Статус массива
 Active Devices : 2
Working Devices : 2
 Failed Devices : 0
  Spare Devices : 0

           Name : server:0
           UUID : a1b2c3d4:e5f6g7h8:i9j0k1l2:m3n4o5p6
         Events : 12345

    Number   Major   Minor   RaidDevice State
       0       8        1        0      active sync   /dev/sda1
       1       8       17        1      active sync   /dev/sdb1
```

| State | Значение |
| :--- | :--- |
| `active, clean` | Нормальное состояние |
| `active, degraded` | Массив работает, но есть сбойные диски |
| `inactive` | Массив не активен (требует сборки) |
| `resyncing` | Идёт синхронизация |
| `recovering` | Идёт восстановление после сбоя |

### Проверка суперблока диска

```bash
# Проверка метаданных RAID на диске
sudo mdadm --examine /dev/sda1

# Краткий вывод (только наличие RAID)
sudo mdadm --examine --brief /dev/sda1
```

**Что проверяем:**

* Наличие метаданных RAID (если диск должен быть в массиве)
* UUID массива (должен совпадать у всех дисков)
* Статус диска (`Active`, `Spare`, `Failed`)

### Проверка SMART дисков в RAID

```bash
# Базовая проверка SMART
sudo smartctl -a /dev/sda

# Для дисков за аппаратным RAID-контроллером
sudo smartctl -d megaraid,0 -a /dev/sda    # LSI MegaRAID
sudo smartctl -d 3ware,0 -a /dev/twe0      # 3ware RAID
```

> **Важно:** Для `mdadm` (программный RAID) диски видны напрямую — `smartctl -a /dev/sdX` работает без ключей `-d`.

Подробнее: [smartctl для RAID](../../Diagnostics/Hardware/smartctl/index.md#проверка-дисков-в-raid-массивах)

---

### Настройка уведомлений о сбоях

**Способ 1: mdadm монитор через systemd**

Создаём службу `/etc/systemd/system/mdmonitor.service`:

```ini
[Unit]
Description=MD array monitoring
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/sbin/mdadm --monitor --scan --daemonise --program=/sbin/mdadm_notify
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

**Способ 2: Ручной запуск мониторинга**

```bash
# Запуск мониторинга с отправкой email
sudo mdadm --monitor --scan --daemonise --mail=admin@example.com

# Запуск мониторинга с выполнением скрипта при событии
sudo mdadm --monitor --scan --daemonise --program=/usr/local/bin/raid_alert.sh
```

**Конфигурация:** `/etc/mdadm/mdadm.conf`

```bash
# Добавить email для уведомлений
MAILADDR admin@example.com

# Или программа-обработчик
PROGRAM /usr/local/bin/raid_alert.sh
```

---

### Диагностика проблем

#### Массив в режиме degraded

```bash
# Определить сбойный диск
sudo mdadm --detail /dev/md0 | grep -E "failed|faulty"

# Или через /proc/mdstat
cat /proc/mdstat
```

#### Массив не собирается после перезагрузки

```bash
# Принудительная сборка
sudo mdadm --assemble --run /dev/md0

# Если не помогает — сканирование и сборка всех массивов
sudo mdadm --assemble --scan

# Проверка, видит ли ядро массивы
cat /proc/mdstat
```

#### Rebuild завис или идёт медленно

```bash
# Проверка прогресса
watch cat /proc/mdstat

# Ограничение скорости rebuild (по умолчанию 200000 KB/s)
# Увеличить до 50000 KB/s
echo 50000 > /proc/sys/dev/raid/speed_limit_min

# Вернуть к значению по умолчанию
echo 200000 > /proc/sys/dev/raid/speed_limit_min
```

#### Проверка консистентности массива (scrub)

```bash
# Запуск проверки на битые сектора (не деструктивно)
echo check > /sys/block/md0/md/sync_action

# Или исправление с перераспределением
echo repair > /sys/block/md0/md/sync_action

# Прогресс проверки
cat /sys/block/md0/md/sync_completed
```

## Дополнительная информация

См. также: [управление RAID 1](./raid1-management.md#мониторинг-и-управление-сбоями), [управление RAID 5](./raid5-management.md#управление-сбоями), [SMART мониторинг](../../Diagnostics/Hardware/smartctl/index.md), [диагностика hardware](../../Diagnostics/Hardware/hardware_listing.md).
