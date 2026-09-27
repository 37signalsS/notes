# dmsetup: диагностика Device Mapper и LVM

## Определения

**dmsetup** — утилита командной строки для управления device-mapper. Предоставляет прямой доступ к таблицам маппинга, статусу устройств и статистике, минуя слой LVM. Является основным инструментом для глубокой диагностики LVM, RAID, LUKS и thin provisioning.

**Device Mapper Table** — структура данных в ядре, определяющая маппинг логических блоков на физические. Формат строки: `<logical_start_sector> <num_sectors> <target_type> <target_args>`. Типы таргетов: `linear`, `striped`, `snapshot`, `thin`, `crypt`, `mirror`.

**Target Type (Тип таргета)** — алгоритм, определяющий как блоки отображаются на устройства. Каждый target имеет уникальный формат аргументов.

**Status** — текущее состояние устройства device-mapper. Формат зависит от target type: `linear` → `0/<sectors>`, `thin` → `<sector>/<sector> <data_percent>`, `snapshot` → `0/<sectors> S/<percent>`.

**Dependence (Зависимости)** — список физических устройств (major:minor), от которых зависит device-mapper устройство. Используется для трассировки от `dm-*` к физическим дискам.

**Event (События)** — изменения состояния device-mapper устройства (threshold crossed, pool full, thinpool out-of-space). Мониторинг через `dmeventd` или `dmsetup monitor`.

## Базовые концепции

### Архитектура взаимодействия

```
Приложение
    ↓
Файловая система (ext4/xfs)
    ↓
Block Device (/dev/vg_data/lv_data)
    ↓
Device Mapper (dm-*)
    ↓
Target: linear / striped / thin / snapshot / crypt
    ↓
Physical Device (/dev/sda, /dev/nvme0n1)
```

### Основные команды dmsetup

| Команда | Назначение | Пример |
|:---|:---|:---|
| `ls` | Список всех DM-устройств | `dmsetup ls` |
| `status` | Статус всех или конкретного устройства | `dmsetup status` |
| `table` | Таблица маппинга | `dmsetup table` |
| `info` | Метаданные устройства | `dmsetup info` |
| `deps` | Зависимости (физ. устройства) | `dmsetup deps /dev/dm-0` |
| `ls --tree` | Дерево зависимостей | `dmsetup ls --tree` |
| `remove` | Удаление DM-устройства | `dmsetup remove /dev/dm-X` |
| `suspend` | Приостановка I/O | `dmsetup suspend /dev/dm-X` |
| `resume` | Возобновление I/O | `dmsetup resume /dev/dm-X` |
| `wait` | Ожидание изменения статуса | `dmsetup wait /dev/dm-X` |

## Практические сценарии

### Шаг 1: Полный обзор системы

```bash
# Список всех DM-устройств
sudo dmsetup ls
# → control
# → vg_data-lv_data (253:0)
# → vg_data-lv_thin (253:1)
# → vg_data-thin_pool (253:2)
# → vg_data-lv_snap (253:3)

# Табличный вид
sudo dmsetup ls --tree
# → vg_data-lv_data (253:0)
#    └─ vg_data-lv_thin (253:1)
#       └─ vg_data-thin_pool (253:2)
#          └─ vg_data-lv_snap (253:3)
```

### Шаг 2: Трассировка dm-* → физический диск

```bash
# Когда iostat показывает высокий await на dm-0

# 1. Определение зависимостей
sudo dmsetup deps /dev/dm-0
# → 8:1 8:17 (major:minor физических устройств)

# 2. Преобразование major:minor в имена
lsblk -ln -o MAJ:MIN,NAME | grep "8:1\|8:17"
# → 8:1 sda1
# → 8:17 sdb1

# 3. Или через sysfs
ls -l /sys/block/dm-0/slaves/
# → sda1 sdb1

# 4. Параллельный мониторинг
iostat -xz 1 3 | grep -E "Device|dm-|sd[a-z]"
```

### Шаг 3: Анализ thin pool

```bash
# Статус thin pool
sudo dmsetup status vg_data-thin_pool
# → 0 209715200 thin-pool 0 245760 76800 245760 2 3 1 1 0 1000 0 0 0

# Разбор полей:
# 0           — смещение
# 209715200   — размер (секторов)
# thin-pool   — тип таргета
# metadata block_count, metadata used, data block_count, data used, needs_check, etc.

# Статус отдельного thin LV
sudo dmsetup status vg_data-lv_thin
# → 0 419430400 thin 0 83886080
# → 0          — смещение
# 419430400    — размер (секторов)
# thin         — тип таргета
# 0            —起源 (origin)
# 83886080     — использованные блоки
```

### Шаг 4: Таблица маппинга

```bash
# Таблица для linear LV
sudo dmsetup table vg_data-lv_data
# → 0 209715200 linear 8:1 0

# Разбор:
# 0            — логическое начало (сектор)
# 209715200    — количество секторов
# linear       — тип таргета
# 8:1          — физическое устройство (major:minor)
# 0            — смещение на физическом устройстве

# Таблица для striped LV
sudo dmsetup table vg_data-lv_striped
# → 0 419430400 striped 2 128 nr_pages 8:1 0 8:17 0

# Таблица для thin pool
sudo dmsetup table vg_data-thin_pool
# → 0 209715200 thin-pool 0 245760 76800 245760 2 3 1 1 0 1000 0 0 0

# Таблица для thin LV
sudo dmsetup table vg_data-lv_thin
# → 0 419430400 thin 253:2 0
# → (thin pool device) (origin)
```

### Шаг 5: Информация об устройстве

```bash
# Полная информация
sudo dmsetup info vg_data-lv_data
# → Name:              vg_data-lv_data
# → State:             ACTIVE
# → Read Ahead Sectors: 256
# → Event Number:      0
# → Major, Minor:      253, 0
# → UUID:              LVM-xxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Или в табличном виде
sudo dmsetup info -c
# → Name                 Maj Min PM  State  Ev  Rsnr  UUID
# → vg_data-lv_data      253   0  A   ACTIVE   0   256  LVM-xxx

# Проверка состояния (ACTIVE/INACTIVE/SUSPENDED)
sudo dmsetup status vg_data-lv_data
# → 0 209715200 linear
```

### Шаг 6: Мониторинг событий

```bash
# Запуск мониторинга (в фоне)
sudo dmsetup monitor &

# Ожидание события (блокирующий вызов)
sudo dmsetup wait vg_data-thin_pool
# → (блокируется до изменения статуса)

# Проверка логов dmeventd
journalctl -u dmeventd -f
```

### Шаг 7: Диагностика проблем

```bash
# Проблема: dm-0 показывает высокий %util, но физические диски простаивают

# 1. Проверить, является ли LV thin
sudo dmsetup table /dev/dm-0 | awk '{print $3}'
# → thin или linear

# 2. Если thin — проверить metadata
sudo dmsetup status vg_data-thin_pool | awk '{print $6}'
# → metadata_percent (если >80% — проблема)

# 3. Если linear — проверить запись в journal
journalctl -k | grep -i "dm-\|error\|reset"

# 4. Сравнение await на dm и физ. дисках
iostat -xz 1 5 | awk '/^Device|^dm-|^sd/{print}'
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
|:---|:---|:---|
| `device-mapper: reload ioctl failed` | Устройство используется или suspended | Проверить `dmsetup status`, `lsof /dev/dm-*` |
| `Couldn't find device with uuid` | Физическое устройство не найдено | Проверить `lsblk`, `pvscan`, фильтры в `lvm.conf` |
| `thin_pool is out of data space` | Thin pool заполнен на 100% | `lvextend vg_data/thin_pool`, `fstrim -v /mountpoint` |
| `snapshot invalid` | COW-буфер исчерпан | `lvremove` снимка, пересоздание с большим chunk size |
| `device-mapper: table: 253:0: linear: Invalid argument` | Повреждение таблицы маппинга | `vgcfgrestore`, восстановление из backup |

### Сравнение с LVM-командами

| Задача | dmsetup | LVM-эквивалент |
|:---|:---|:---|
| Список томов | `dmsetup ls` | `lvs` |
| Статус | `dmsetup status /dev/dm-0` | `lvs -o lv_name,lv_attr,devices` |
| Зависимости | `dmsetup deps /dev/dm-0` | `lvs -o +devices` |
| Таблица маппинга | `dmsetup table /dev/dm-0` | `lvs -a -o +seg_devices` |
| Информация | `dmsetup info /dev/dm-0` | `lvdisplay /dev/vg/lv` |
| Удаление | `dmsetup remove /dev/dm-0` | `lvremove /dev/vg/lv` |

### См. также
- **[LVM — Просмотр информации](./lvm_view_info.md)** — LVM-команды для просмотра.
- **[LVM — Диагностика I/O](../../Diagnostics/Performance/DiskIO/lvm_io_performance.md)** — влияние LVM на производительность.
- **[LVM — Thin Provisioning](../thin-provisioning.md)** — архитектура thin pool и мета-данные.
- **[I/O Schedulers](../../../Core/kernel/io_schedulers.md)** — планировщики ввода-вывода.
