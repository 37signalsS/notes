# Просмотр информации LVM

## Определения

**Команды краткого вывода (Reporting commands)** — утилиты `pvs`, `vgs`, `lvs`, выводящие информацию в компактном табличном виде (одна строка на объект). Оптимальны для оперативного мониторинга, автоматизации и скриптов. Поддерживают фильтрацию через `-S` и форматирование вывода.

**Команды подробного вывода (Display commands)** — утилиты `pvdisplay`, `vgdisplay`, `lvdisplay`, предоставляющие детальный многострочный отчет о каждом объекте, включая UUID, метаданные и внутренние параметры сегментов. Используются для глубокой диагностики.

**Команды сканирования (Scanning commands)** — утилиты `pvscan`, `vgscan`, `lvscan`, предназначенные для поиска LVM-объектов на всех доступных блочных устройствах и обновления системного кэша. Автоматически вызываются `udev` при подключении нового диска.

**dmeventd (Device Mapper Event Daemon)** — системный демон, отвечающий за автоматический мониторинг состояния LVM-объектов. Уведомляет LVM о изменениях (заполнение thin pool, развитие снимков, деградация RAID). Управляется через `lvm2-monitor.service`.

**lvm.conf** — главный конфигурационный файл LVM, определяющий фильтры устройств, политики распределения, пороги автоматического расширения и параметры логирования. Расположен в `/etc/lvm/lvm.conf`.

## Базовые концепции

### Иерархия инструментов мониторинга

Инструментарий LVM разделён на уровни, соответствующие архитектуре PV → VG → LV.

| Объект | Краткий отчёт | Подробный отчёт | Сканирование | Область анализа |
| :--- | :--- | :--- | :--- | :--- |
| **Physical Volume (PV)** | `sudo pvs` | `sudo pvdisplay` | `sudo pvscan` | Физические диски, разделы, метки, свободные экстенты |
| **Volume Group (VG)** | `sudo vgs` | `sudo vgdisplay` | `sudo vgscan` | Группы томов, размер PE, суммарные ресурсы, флаги |
| **Logical Volume (LV)** | `sudo lvs` | `sudo lvdisplay` | `sudo lvscan` | Логические разделы, сегменты, точки монтирования, атрибуты |

### Столбец Attr: расшифровка атрибутов

Атрибуты выводятся строкой из 10 символов. Каждая позиция описывает определённую характеристику объекта.

#### Атрибуты Logical Volume (LV)

| Позиция | Символ | Значение |
| :--- | :--- | :--- |
| 1 | `v` | Virtual LV |
| 1 | `V` | Thin volume |
| 1 | `s` | Snapshot LV |
| 1 | `o` | Origin LV |
| 1 | `m` | Mirrored LV |
| 1 | `r` | RAID LV |
| 2 | `w` | Writable (RW) |
| 2 | `r` | Read-only (RO) |
| 3 | `a` | Allocation: anywhere |
| 3 | `i` | Allocation: inherited |
| 3 | `n` | Allocation: normal |
| 4 | `m` | Fixed minor number |
| 5 | `a` | Active |
| 5 | `s` | Suspended |
| 5 | `I` | Invalid snapshot (missing origin) |
| 5 | `S` | Invalid thin volume |
| 6 | `o` | Open (mounted or in use) |
| 6 | `-` | Closed |
| 7 | `s` | Snapshot target |
| 7 | `m` | Mirror target |
| 7 | `t` | Thin pool/volume target |
| 7 | `r` | RAID target |
| 8 | `z` | Zeroing enabled (thin pool) |
| 8 | `-` | Zeroing disabled |
| 9 | `p` | Partial (missing PV extents) |
| 9 | `r` | Refresh needed |
| 9 | `-` | Healthy |
| 10 | `k` | Skip activation |
| 10 | `-` | Normal activation |

**Примеры:**
- `twi-aotz--` — thin pool, writable, active, open, zeroing
- `Vwi-aotz--` — thin volume, writable, active, open, zeroing
- `swi-a-s---` — snapshot, writable, active, closed, snapshot target
- `rwi-aor---` — RAID, writable, active, open, healthy
- `twi-p-s---` — thin pool, partial (missing PV), suspended

#### Атрибуты Physical Volume (PV)

| Позиция | Символ | Значение |
| :--- | :--- | :--- |
| 1 | `a` | Allocatable |
| 1 | `n` | Not allocatable (fully allocated or reserved) |
| 2 | `z` | Resizable |
| 2 | `-` | Not resizable |
| 3 | `x` | Exported |
| 3 | `-` | Not exported |
| 4 | `r` | Resize missing (partial allocation) |
| 4 | `-` | Normal |

**Примеры:**
- `a--` — allocatable, not resizable, not exported (стандартный PV)
- `axr` — allocatable, exported, resize missing
- `n--` — not allocatable (все экстенты заняты)

#### Атрибуты Volume Group (VG)

| Позиция | Символ | Значение |
| :--- | :--- | :--- |
| 1 | `w` | Writable (разрешена запись) |
| 1 | `r` | Read-only (только чтение) |
| 2 | `z` | Resizable (разрешено расширение) |
| 2 | `-` | Not resizable |
| 3 | `x` | Exported |
| 3 | `-` | Not exported |
| 4 | `p` | Partial (отсутствуют PV) |
| 4 | `-` | Complete (все PV доступны) |
| 5 | `c` | Clustered |
| 5 | `-` | Not clustered |
| 6 | `s` | Snapshot (содержит снимки) |
| 6 | `-` | No snapshots |
| 7 | `n` | Not resizable (устаревший флаг) |

**Примеры:**
- `wz-pn-` — writable, resizable, partial (missing PV), normal
- `wz--nc` — writable, resizable, complete, normal, clustered
- `r-x---` — read-only, exported

### Интерпретация вывода команд Display

Команды `pvdisplay`, `vgdisplay`, `lvdisplay` предоставляют детальную информацию. Ниже — ключевые поля каждого отчёта.

#### pvdisplay — ключевые поля

| Поле | Описание | На что обращать внимание |
| :--- | :--- | :--- |
| `PV Name` | Путь к физическому устройству | `/dev/sdX`, `/dev/mapper/...` |
| `VG Name` | Имя группы томов | Принадлежность к VG |
| `PV Size` | Размер физического тома | Фактический размер диска |
| `Allocatable` | Доступность для распределения | `YES` / `NO` |
| `PE Size` | Размер физического экстента | Кратность для расширения |
| `Total PE` | Общее количество PE | Доступные ресурсы |
| `Allocated PE` | Использованные PE | Загрузка диска |
| `Free PE` | Свободные PE | Потенциал расширения |
| `Metadata Area` | Область метаданных MDA | Адрес и размер MDA |
| `Metadata Sequence No` | Номер версии метаданных | Увеличивается при каждом изменении VG |
| `PV UUID` | Уникальный идентификатор | Используется для восстановления |

#### vgdisplay — ключевые поля

| Поле | Описание | На что обращать внимание |
| :--- | :--- | :--- |
| `VG Name` | Имя группы томов | Уникальность в системе |
| `VG Size` | Суммарный размер VG | Сумма всех PV за вычетом MDA |
| `PE Size` | Размер физического экстента | Фиксируется при создании VG |
| `Total PE` | Общее количество PE | Кратность для LV |
| `Allocated PE` | Использованные PE | Занятость пула |
| `Free PE` | Свободные PE | Потенциал для `lvextend` |
| `VG UUID` | Уникальный идентификатор | Используется для `vgcfgrestore` |
| `VG Status` | Состояние (writable/exported) | Активность VG |
| `Max LV` | Максимальное число LV | Лимит (0 = без ограничений) |
| `Cur LV` | Текущее число LV | Использовано |
| `Open LV` | Открытые LV | Активные файловые системы |
| `Max PV` | Максимальное число PV | Лимит |
| `Cur PV` | Текущее число PV | Использовано |

#### lvdisplay — ключевые поля

| Поле | Описание | На что обращать внимание |
| :--- | :--- | :--- |
| `LV Name` | Имя логического тома | Имя в `/dev/VG/LV` |
| `LV Path` | Полный путь | `/dev/mapper/VG-LV` |
| `LV Status` | Состояние (active/suspended) | Активность |
| `LV Size` | Размер логического тома | Фактический размер |
| `Current LE` | Текущее число LE | Кратность PE |
| `Allocated LE` | Выделенные LE | Использование |
| `Segments` | Количество сегментов | Фрагментация |
| `Segment Type` | Тип сегмента | linear, striped, thin, mirror, raid |
| `Stripe Count` | Число полос (для striped) | Производительность |
| `Devices` | Физические устройства | Маппинг LE→PE |
| `LV UUID` | Уникальный идентификатор | Восстановление |

### Справочник полей для команд -o

Каждая команда поддерживает вывод произвольных полей через параметр `-o`. Ниже — наиболее используемые поля.

#### Поля для pvs

| Поле | Описание |
| :--- | :--- |
| `pv_name` | Имя PV |
| `pv_fmt` | Формат метаданных (lvm2) |
| `pv_attr` | Атрибуты PV |
| `pv_size` | Размер PV |
| `pv_free` | Свободное место |
| `pv_used` | Использованное место |
| `pv_uuid` | UUID PV |
| `vg_name` | Имя VG |
| `pv_pe_count` | Количество PE |
| `pv_pe_alloc_count` | Использованные PE |

#### Поля для vgs

| Поле | Описание |
| :--- | :--- |
| `vg_name` | Имя VG |
| `vg_attr` | Атрибуты VG |
| `vg_size` | Размер VG |
| `vg_free` | Свободное место |
| `vg_free_count` | Количество свободных PE |
| `vg_extent_count` | Общее число PE |
| `vg_uuid` | UUID VG |
| `pv_count` | Количество PV |
| `lv_count` | Количество LV |
| `snap_count` | Количество снимков |
| `vg_missing_pv_count` | Отсутствующие PV |

#### Поля для lvs

| Поле | Описание |
| :--- | :--- |
| `lv_name` | Имя LV |
| `lv_path` | Полный путь LV |
| `lv_attr` | Атрибуты LV |
| `lv_size` | Размер LV |
| `seg_count` | Количество сегментов |
| `segtype` | Тип сегмента |
| `stripes` | Число полос |
| `stripe_size` | Размер полосы |
| `devices` | Физические устройства |
| `lv_uuid` | UUID LV |
| `origin` | Origin (для снимков) |
| `data_percent` | Заполнение thin pool |
| `metadata_percent` | Заполнение метаданных thin pool |
| `copy_percent` | Прогресс копирования (mirror/RAID) |
| `lv_active` | Состояние активации |
| `lv_layout` | Компоновка (linear, striped, thin, mirror, raid) |

## Практические сценарии

### Сценарий 1: Общая диагностика блочных устройств

Первым шагом рекомендуется использовать `lsblk` для понимания физической топологии.

```bash
lsblk
# → NAME                  MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# → sdb                   8:16    0   20G  0 disk
# → └─data_vg-lv_data     253:0    0   10G  0 lvm  /mnt/data
# → sdc                   8:32    0   30G  0 disk
# → └─data_vg-lv_backup   253:1    0   15G  0 lvm  /mnt/backup
```

### Сценарий 2: Анализ свободного места и PE

Используется для принятия решения о расширении.

```bash
# Просмотр свободных экстентов (PE) в группах
sudo vgs -o vg_name,vg_size,vg_free,vg_free_count
# → VG      VSize   VFree  Free
# → data_vg <20.00g <5.00g 1279

# Просмотр распределения PV в VG
sudo pvs -o pv_name,vg_name,pv_free,pv_attr
# → PV         VG      PFree  Attr
# → /dev/sdb   data_vg <2.00g a--
# → /dev/sdc   data_vg <3.00g a--
```

### Сценарий 3: Мониторинг тонких пулов (Thin Provisioning)

Для тонких томов критично следить за физическим заполнением пула.

```bash
sudo lvs -o lv_name,data_percent,metadata_percent,lv_attr
# → LV          Data%  Meta%  Attr
# → thin_lv     15.40         Vwi-a-tz--
# → thin_pool   77.00  12.50  twi-aotz--
```

*Если `Data%` достигнет 100%, запись во все тонкие тома этого пула будет заблокирована.*

> **См. также:** [LVM — Тонкое провизионирование](../thin-provisioning.md) — детальный разбор работы thin pool и автоматического расширения.

### Сценарий 4: Мониторинг снимков (Snapshots)

Снимки создают по принципу Copy-on-Write и требуют контроля заполнения.

```bash
sudo lvs -o lv_name,snap_percent,lv_attr,origin
# → LV        Snap%  Attr        Origin
# → lv_snap1  45.67  swi-a-s---  lv_data
```

*Если `Snap%` приблизится к 100%, снимок будет автоматически удалён.*

> **См. также:** [LVM — Снимки](../snapshots.md) — теория CoW и автоматическое расширение снимков.

### Сценарий 5: Мониторинг RAID

Для RAID-массивей критичен прогресс синхронизации (rebuild).

```bash
sudo lvs -o lv_name,copy_percent,lv_attr
# → LV        Copy%  Attr
# → lv_raid1  85.30  rwi-aor---
```

*Если `Copy%` не достигает 100%, массив находится в состоянии rebuild и работает в degraded mode.*

> **См. также:** [LVM — Продвинутые темы](../advanced_topics/advanced_topics.md) — настройка и мониторинг RAID.

### Сценарий 6: Мониторинг кэша (dm-cache)

Кэш-пулы ускоряют чтение/запись за счёт быстрого накопителя (NVMe/SSD).

```bash
sudo lvs -o lv_name,cache_read_hits,cache_write_hits,lv_attr
# → LV       RD_Hits  WR_Hits  Attr
# → lv_data  1234567  890123   twi-aotz--
```

*Кэш-попадание (hit rate) = RD_Hits / (RD_Hits + WR_Hits). Рекомендуется > 90%.*

> **См. также:** [LVM — Продвинутые темы](../advanced_topics/advanced_topics.md) — создание и настройка dm-cache.

### Сценарий 7: Кастомизация вывода и фильтрация

LVM предоставляет мощные средства фильтрации через параметр `-S` (Selection).

```bash
# Найти все активные тома размером более 5 ГБ
sudo lvs -S 'lv_size > 5G && lv_active = "active"'

# Вывод в формате JSON для автоматизации
sudo lvs --reportformat json

# Использование специфических единиц измерения (MiB, GiB)
sudo lvs --units g

# Показать только определённые поля
sudo lvs -o lv_name,lv_size,lv_attr,devices
```

### Сценарий 8: Сортировка и выбор полей

```bash
# Сортировка томов по проценту заполнения (сначала самые полные)
sudo lvs --sort -data_percent

# Показать все доступные поля для формирования отчёта
sudo pvs -o help
sudo vgs -o help
sudo lvs -o help

# Комбинированный вывод с расшифровкой
sudo lvs -a -o lv_name,lv_attr,segtype,stripe_count,devices
```

### Сценарий 9: Сканирование и активация

Используется после подключения новых дисков или при восстановлении системы.

```bash
sudo vgscan
# → Reading all physical volumes.  This may take a while...
# → Found volume group "data_vg" using metadata type lvm2

sudo lvscan
# → ACTIVE            '/dev/data_vg/lv_data' [10.00 GiB] inherit
# → INACTIVE          '/dev/data_vg/lv_backup' [5.00 GiB] inherit
```

*Если статус `INACTIVE`, том нужно активировать:*

```bash
# Активация всех LV в VG
sudo vgchange -ay data_vg

# Активация конкретного LV
sudo lvchange -ay data_vg/lv_backup

# Проверка результата
sudo lvs data_vg
# → LV       VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_data  data_vg -wi-ao---- 10.00g
# → lv_backup data_vg -wi-a----  5.00g
```

### Сценарий 10: Автоматический健康-чек скрипт

Скрипт для регулярной проверки состояния всех LVM-объектов. Рекомендуется запускать через `cron` или `systemd timer`.

```bash
#!/bin/bash
# lvm_health_check.sh — проверка здоровья LVM
set -euo pipefail

echo "=== LVM Health Check $(date) ==="

echo -e "\n[1] PV Status:"
sudo pvs --noheadings -o pv_name,vg_name,pv_attr,pv_free | while read pv vg attr free; do
    if [[ "$attr" == *"x"* ]]; then
        echo "  WARNING: $pv ($vg) is EXPORTED"
    fi
done

echo -e "\n[2] VG Free Space:"
sudo vgs --noheadings -o vg_name,vg_free,vg_free_count | while read vg free count; do
    if (( count < 100 )); then
        echo "  CRITICAL: $vg has only $free ($count PE) free"
    elif (( count < 256 )); then
        echo "  WARNING: $vg has $free ($count PE) free"
    else
        echo "  OK: $vg has $free ($count PE) free"
    fi
done

echo -e "\n[3] Thin Pool Usage:"
sudo lvs --noheadings -o lv_name,vg_name,data_percent,metadata_percent,lv_attr 2>/dev/null | while read lv vg data meta attr; do
    if [[ "$attr" == *"t"* ]]; then
        data_int=${data%.*}
        if (( data_int > 90 )); then
            echo "  CRITICAL: $vg/$lv at ${data}% (thin pool near full)"
        elif (( data_int > 80 )); then
            echo "  WARNING: $vg/$lv at ${data}%"
        else
            echo "  OK: $vg/$lv at ${data}%"
        fi
    fi
done

echo -e "\n[4] Snapshot Usage:"
sudo lvs --noheadings -o lv_name,vg_name,snap_percent,lv_attr 2>/dev/null | while read lv vg snap attr; do
    if [[ "$attr" == *"s"* ]] && [[ -n "$snap" ]]; then
        snap_int=${snap%.*}
        if (( snap_int > 80 )); then
            echo "  CRITICAL: $vg/$lv snapshot at ${snap}% (near auto-delete)"
        elif (( snap_int > 60 )); then
            echo "  WARNING: $vg/$lv snapshot at ${snap}%"
        else
            echo "  OK: $vg/$lv snapshot at ${snap}%"
        fi
    fi
done

echo -e "\n[5] Missing PVs:"
missing=$(sudo vgs --noheadings -o vg_missing_pv_count 2>/dev/null | tr -d ' ')
if [[ "$missing" -gt 0 ]] 2>/dev/null; then
    echo "  CRITICAL: VG has missing PVs"
else
    echo "  OK: All PVs present"
fi

echo -e "\n[6] Metadata Integrity:"
for vg in $(sudo vgs --noheadings -o vg_name 2>/dev/null); do
    if ! sudo vgck "$vg" >/dev/null 2>&1; then
        echo "  CRITICAL: $vg metadata check FAILED"
    else
        echo "  OK: $vg metadata OK"
    fi
done

echo -e "\n=== Health Check Complete ==="
```

### Сценарий 11: Пороги алертования (SRE/DevOps)

Рекомендуемые пороги для настройки мониторинга (Prometheus, Zabbix, Nagios и др.).

| Метрика | Порог WARNING | Порог CRITICAL | Действие |
| :--- | :--- | :--- | :--- |
| **Thin Pool Data%** | > 80% | > 90% | Расширить пул: `lvextend -L +SIZE` |
| **Thin Pool Meta%** | > 70% | > 85% | Расширить метаданные: `lvextend --poolmetadatasize` |
| **Snapshot Usage%** | > 60% | > 80% | Рассмотреть удаление или увеличение |
| **VG Free Space** | < 10% | < 5% | Добавить PV или переместить данные |
| **LV Usage%** | > 85% | > 95% | Расширить LV: `lvextend -r` |
| **Missing PVs** | > 0 | > 0 | Немедленная диагностика, `vgreduce --removemissing` |
| **RAID Degraded** | `d` flag | `D` flag | Замена диска, rebuild |
| **Cache Hit Rate** | < 80% | < 60% | Увеличить размер кэш-пула |

### Сценарий 12: Однострочники для быстрой диагностики

```bash
# Все активные LV с размерами
sudo lvs -o lv_name,vg_name,lv_size,lv_attr -S 'lv_active = "active"'

# Все thin pool больше 80%
sudo lvs -S 'data_percent > 80 && segtype = "thin-pool"' -o lv_name,vg_name,data_percent

# Все PV с меньше чем 10% свободного
sudo pvs -S 'pv_free < 10% of vg' -o pv_name,vg_name,pv_free

# Все LV, использующие определённый PV
sudo lvs -o lv_name,devices | grep "/dev/sdb"

# Все снимки с использованием > 50%
sudo lvs -S 'snap_percent > 50' -o lv_name,origin,snap_percent

# Отсутствующие PV
sudo pvs -o pv_name,vg_name,pv_attr | grep "r"

# Все LV с флагом partial (повреждены)
sudo lvs -o lv_name,lv_attr | grep "p"

# Быстрая сводка по всем уровням
sudo pvs && echo "---" && sudo vgs && echo "---" && sudo lvs
```

### Сценарий 13: Мониторинг через systemd и dmeventd

```bash
# Проверка статуса сервиса мониторинга
sudo systemctl status lvm2-monitor.service
# → ● lvm2-monitor.service - Monitoring of LVM2 mirrors and snapshots
# →    Loaded: loaded (/usr/lib/systemd/system/lvm2-monitor.service; enabled)
# →    Active: active (running) since ...

# Просмотр логов dmeventd
sudo journalctl -u lvm2-monitor.service --since "1 hour ago"

# Проверка, включён ли автоматический мониторинг в lvm.conf
grep -E "monitoring|snapshot_autoextend|thin_pool_autoextend" /etc/lvm/lvm.conf
# →     snapshot_autoextend_threshold = 80
# →     snapshot_autoextend_percent = 20
# →     thin_pool_autoextend_threshold = 80
# →     thin_pool_autoextend_percent = 20
# →     monitoring = 1
```

### Сценарий 14: Вывод в формате JSON/YAML для автоматизации

```bash
# JSON для парсинга в скриптах
sudo lvs --reportformat json -o lv_name,lv_size,lv_attr,segtype
# → {
# →   "report": [
# →     {
# →       "lv": [
# →         {"lv_name": "lv_data", "lv_size": "10737418240", "lv_attr": "twi-aotz--", "segtype": "thin-pool"},
# →         {"lv_name": "lv_app", "lv_size": "5368709120", "lv_attr": "Vwi-aotz--", "segtype": "thin"}
# →       ]
# →     }
# →   ]
# → }

# Скрипт для парсинга JSON (jq)
sudo lvs --reportformat json -o lv_name,lv_size,segtype | jq '.report[0].lv[] | select(.segtype == "thin-pool")'

# CSV для экспорта в Excel/Google Sheets
sudo lvs --reportformat csv -o lv_name,lv_size,lv_attr
```

## Дополнительная информация

### Лучшие практики

1. **Регулярный健康-чек:** Запускайте скрипт проверки (Сценарий 10) ежедневно через `cron` или `systemd timer`.

2. **Настройка алертов:** Экспортируйте метрики LVM в систему мониторинга (Prometheus, Zabbix) и настройте алерты по порогам из Сценария 11.

3. **Автоматическое расширение thin pool:** Убедитесь, что в `lvm.conf` включены `thin_pool_autoextend_threshold` и `thin_pool_autoextend_percent`:

   ```bash
   # /etc/lvm/lvm.conf
   thin_pool_autoextend_threshold = 80
   thin_pool_autoextend_percent = 20
   monitoring = 1
   ```

4. **Логирование:** Настройте `dmeventd` для записи событий в `syslog` или `journald`:

   ```bash
   # /etc/lvm/lvm.conf
   log {
       file = "/var/log/lvm2.log"
       level = 7
   }
   ```

5. **Документирование:** Ведите журнал изменений размеров и конфигурации. Фиксируйте дату, оператора, исходный и целевой размеры.

6. **Тестирование:** На non-production окружении проверяйте критические операции (pvmove, vgsplit, vgcfgrestore) перед выполнением на боевых серверах.

### Граничные случаи и ограничения

1. **Устаревшие команды:** `vgscan`, `lvscan`, `pvscan` считаются устаревшими в новых версиях LVM. Используйте `vgs`, `lvs`, `pvs` как основной инструмент.

2. **Фильтры в lvm.conf:** Если устройство не видно в `pvs`, проверьте фильтры в `/etc/lvm/lvm.conf`:

   ```bash
   devices {
       filter = [ "a|.*|", "r|.*|" ]  # Пример: принять все
   }
   ```

3. **Множественные VG с одинаковым именем:** При клонировании дисков могут возникнуть конфликты имён. Используйте `vgimportclone` для переименования.

4. **Partial VG:** Если отсутствуют PV, VG не активируется автоматически. Используйте `vgchange -ay --partial` для принудительной активации (только для чтения).

5. **Thin pool满:** При заполнении thin pool на 100% все LV в пуле переходят в read-only. Расширение через `lvextend -L +SIZE VG/pool`.

6. **Снимки и производительность:** Активные снимки снижают производительность записи из-за COW-операций. Удаляйте временные снимки после использования.

7. **Кластерные VG:** В кластерных конфигурациях команды вывода могут отображать устаревшие данные. Используйте `--partial` для получения актуальной информации.

### Устранение неполадций

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `pvs` не показывает PV | Фильтр в `lvm.conf` | Проверить `filter` в `devices {}` |
| `vgs` не находит VG | VG не активирована или отсутствует PV | `vgscan`, проверить `lvm.conf` фильтры |
| `lvs` показывает `INACTIVE` | LV не активирован | `lvchange -ay VG/LV` или `vgchange -ay VG` |
| Thin pool Data% > 100% | Авто-расширение не сработало | `lvextend -L +SIZE VG/pool`, проверить `monitoring = 1` |
| Snapshot удалён автоматически | Достигнут порог `snapshot_autoextend_threshold` | Увеличить порог или создать новый снимок |
| `Metadata Sequence No` растёт | Частые изменения VG | Нормальное поведение; при > 10000 рассмотреть `vgcfgbackup` |
| `Partial` в PV/VG атрибутах | Физический диск недоступен | Проверить подключение диска, `vgreduce --removemissing` |
| RAID в degraded mode | Один из дисков недоступен | Заменить диск, `lvconvert --repair VG/LV` |
| Cache Hit Rate низкий | Кэш-пул слишком мал | Увеличить размер кэш-пула: `lvextend` |
| `lvdisplay` не показывает LV | LV скрыт или удалён | `lvs -a` для отображения всех LV |

### Диагностические команды

```bash
# Быстрая проверка состояния всех уровней
sudo pvs && sudo vgs && sudo lvs

# Проверка активных процессов, использующих LV
sudo lsof /dev/mapper/data_vg-lv_data
sudo fuser -vm /dev/mapper/data_vg-lv_data

# Проверка journal для ошибок LVM
sudo journalctl -k | grep -i "device-mapper\|lvm\|dm-"

# Просмотр метаданных VG
sudo vgcfgrestore --list data_vg

# Проверка целостности PV
sudo pvck /dev/sdb

# Проверка целостности VG
sudo vgck data_vg

# Просмотр атрибутов с расшифровкой
sudo lvdisplay /dev/data_vg/lv_data
sudo vgdisplay data_vg
sudo pvdisplay /dev/sdb
```

### См. также
- **[LVM — Управление томами](../management_operations.md)** — общие операции и мониторинг.
- **[LVM — Создание PV, VG и LV](./pv_vg_creation.md)** — инициализация структур.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — детальный разбор Data% и Meta%.
- **[LVM — Снимки](../snapshots.md)** — теория CoW и мониторинг снимков.
- **[LVM — Продвинутые темы](../advanced_topics/advanced_topics.md)** — RAID, кэширование, metadata integrity.
- **[LVM — Жизненный цикл](./lvm_lifecycle.md)** — интеграция с systemd и dmeventd.
