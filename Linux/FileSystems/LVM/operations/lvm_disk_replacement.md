# Замена физического диска в LVM

## Определения

**pvmove** — утилита LVM, предназначенная для перемещения физических экстентов (PE) с одного физического тома (PV) на другой (или другие) в пределах одной группы томов (VG) без остановки работы системы. Основной инструмент онлайн-миграции данных. Работает на уровне Device Mapper: временно создаёт зеркальный LV для перемещаемых данных, обеспечивая непрерывность доступа.

**Migration (Миграция данных)** — процесс переноса содержимого физического тома на новые носители для вывода старого оборудования из эксплуатации, балансировки нагрузки или подготовки к ремонту/ замене. Выполняется без остановки сервисов.

**Extent (Экстент)** — минимальный блок дискового пространства в LVM (обычно **4 МиБ**, задаётся при создании VG). Все операции pvmove кратны размеру экстента.

**lvconvert --replace** — команда для прямой замены PV в RAID-томе (raid1/5/6/10). Инициирует rebuild массива на новом диске. Более эффективна, чем pvmove для RAID, поскольку использует встроенный механизм dm-raid.

**vgreduce --removemissing** — команда для аварийного удаления отсутствующих (missing) PV из VG. Используется при физическом выходе диска из строя. Все LV, полностью или частично расположенные на удалённом PV, будут безвозвратно удалены.

**Thin Pool** — пул тонкого провизионирования, состоящий из LV данных и LV метаданных. При перемещении thin pool через pvmove метаданные перемещаются отдельно и могут вызывать кратковременные блокировки (stalls) записи.

**Device Mapper** — фреймворк ядра Linux, обеспечивающий отображение блочных устройств. LVM использует его для работы с LV, pvmove, RAID и thin provisioning.

## Базовые концепции

Замена физического диска в LVM выполняется в режиме онлайн благодаря механизму Device Mapper. Данные перемещаются поблочно, при этом логический том остается доступным для чтения и записи.

### Ключевые принципы

- **Область действия:** Миграция возможна только внутри одной Volume Group (VG). Напрямую между разными VG данные переместить нельзя. Для переноса между VG используйте `vgsplit` / `vgmerge` или `pvmove` после объединения VG.
- **Доступное пространство:** В целевой VG должно быть достаточно свободных PE для размещения всех данных мигрируемого PV. Проверяйте через `vgs -o vg_name,vg_free`.
- **Транзакционность:** Процесс перемещения каждого экстента атомарен. Если процесс прервется (сбой питания), он автоматически возобновится с последнего чекпоинта при повторном запуске `pvmove` без аргументов.
- **Механизм работы:** LVM временно создает зеркальный LV для перемещаемых данных, что обеспечивает непрерывность доступа. Фактически pvmove создаёт temporary mirror, а после завершения удаляет исходный PV.
- **Безопасность данных:** `pvmove` полностью безопасен — в процессе миграции все логические тома остаются доступными для чтения и записи. Если во время миграции произойдет сбой питания, повторный запуск `pvmove` просто продолжит перенос с места остановки.
- **Особенность переноса:** Переносится весь объём экстентов LV, включая пустое пространство (в отличие от ZFS и Btrfs, которые переносят только реально занятые блоки).

### Предварительная проверка (Pre-flight Checklist)

Перед запуском pvmove необходимо выполнить проверку:

1. **Достаточно места в VG:**
   ```bash
   sudo vgs -o vg_name,vg_free,vg_size
   # VG      VFree   VSize
   # my_vg   50.00g  200.00g
   ```
   Свободного места должно быть не меньше объёма данных на мигрируемом PV.

2. **Нет заблокированных LV:**
   ```bash
   sudo lvs -o lv_name,lv_attr,devices | grep "ae"
   ```
   LV с флагами `ae` (active, exposed) не должны блокировать миграцию.

3. **Нет активных snapshot:**
   ```bash
   sudo lvs -o lv_name,lv_attr,segtype | grep snap
   ```
   Активные снимки могут замедлить pvmove.

4. **Целевой PV доступен:**
   ```bash
   sudo pvs -o pv_name,pv_attr | grep "a"
   ```
   PV должен иметь атрибут `a` (allocatable).

5. **Thin pool не заполнен:**
   ```bash
   sudo lvs -o lv_name,segtype,data_percent | grep thin
   ```
   Thin pool на 100% может прервать миграцию.

### Производительность и тюнинг

- **Фоновый режим (`-b` / `--background`):** Рекомендуется для больших объемов (сотни ГиБ), чтобы не блокировать терминал. Мониторинг через `lvs` или `pvmove --status`.
- **Интервал опроса (`-i` / `--interval`):** Задает частоту (в сек) проверки завершения копирования сегмента. Низкий интервал ускоряет миграцию, но создает нагрузку на запись метаданных VG. Рекомендуемый диапазон: 5–30 сек.
- **Приоритет I/O (`ionice`):** Чтобы миграция не мешала работе приложений, используйте минимальный приоритет:
  ```bash
  sudo ionice -c 3 pvmove -b /dev/sdb
  ```
- **Ограничение пропускной способности:** Для ограничения нагрузки на диск можно использовать `pvmove --interval` с увеличенным интервалом или `ionice -c3` в сочетании с `nice -n19`.
- **Мониторинг прогресса:**
  ```bash
  # Текущий статус pvmove
  sudo lvs -o+move_pv,move_pe

  # Просмотр через pvmove --status (если запущен в фоне)
  sudo pvmove --status

  # Проверка I/O через iostat
  iostat -x 5
  ```

## Практические сценарии

### Сценарий 1: Плановая замена диска (полный цикл)

Пошаговый процесс замены диска с проверкой на каждом этапе.

**Шаг 1: Подготовка нового диска**
```bash
# Очистка сигнатур (если диск б/у или с остаточными метками)
sudo wipefs --all /dev/sdd

# Создание PV на новом диске
sudo pvcreate /dev/sdd
# → Physical volume "/dev/sdd" successfully created.

# Проверка
sudo pvs /dev/sdd
# → PV         VG   Fmt  Attr PSize   PFree
# → /dev/sdd        lvm2 ---  <50.00g <50.00g
```

**Шаг 2: Расширение группы томов**
```bash
sudo vgextend my_vg /dev/sdd
# → Volume group "my_vg" successfully extended

# Проверка
sudo vgs my_vg
# → VG      #PV #LV #SN Attr   VSize   VFree
# → my_vg    3   5   0 wz--n- <200g   50.00g
```

**Шаг 3: Запуск миграции данных**
```bash
# Запуск с контролем прогресса каждые 10 секунд
sudo pvmove -i 10 /dev/sdc
# → /dev/sdc: Moved: 0.52%
# → /dev/sdc: Moved: 100.00%

# Или в фоновом режиме с ionice
sudo ionice -c 3 pvmove -b /dev/sdc -i 30
```

**Шаг 4: Мониторинг (в отдельном терминале)**
```bash
# Проверка прогресса
sudo lvs -o+move_pv,move_pe
# → LV      movePV  movePE
# → lv_data /dev/sdd  1280/5120

# Проверка I/O
iostat -x 5
```

**Шаг 5: Вывод старого диска из группы**
```bash
# Проверка, что PV пуст
sudo pvs -o pv_name,vg_name,pv_free /dev/sdc
# → PV         VG   PFree
# → /dev/sdc        0

# Удаление PV из VG
sudo vgreduce my_vg /dev/sdc
# → Removed "/dev/sdc" from volume group "my_vg"
```

**Шаг 6: Очистка LVM-меток**
```bash
sudo pvremove /dev/sdc
# → Labels on physical volume "/dev/sdc" successfully wiped.

# Проверка
sudo pvs /dev/sdc
# → (пусто — PV удалён)
```

**Шаг 7: Финальная проверка**
```bash
sudo vgs my_vg
sudo lvs my_vg
sudo pvs
```

### Сценарий 2: Аварийная остановка и диагностика

Если процесс миграции завис или вызывает критическую нагрузку.

**Шаг 1: Принудительная остановка**
```bash
sudo pvmove --abort
# → Cancellation of pvmove in progress

# Проверка остановки
sudo lvs -o+move_pv,move_pe
# → (пусто — миграция остановлена)
```
*Уже перемещенные данные останутся на новом месте, LV продолжит работу.*

**Шаг 2: Анализ проблем**
Проверьте наличие ошибок ввода-вывода (I/O errors):
```bash
dmesg | grep -i "error\|fail\|offline"
sudo journalctl -k --since "1 hour ago" | grep -i "sd\|block\|lvm"
```

**Шаг 3: Возобновление**
Для продолжения просто введите:
```bash
sudo pvmove
# pvmove возобновит с места остановки
```

### Сценарий 3: Замена диска в RAID-массиве LVM

Для томов типа `raid1/5/6/10` вместо `pvmove` эффективнее использовать встроенный механизм MD-подсистемы.
```bash
# Прямая замена старого PV на новый в RAID-томе
sudo lvconvert --replace /dev/old_pv /dev/new_pv my_vg/raid_lv
# → Logical volume my_vg/raid_lv converted.

# Проверка прогресса rebuild
sudo lvs -o lv_name,copy_percent,devices my_vg
# → LV       Copy% Devices
# → raid_lv  45.23 /dev/sdd(0-1023),/dev/sdb(0-1023)

cat /proc/mdstat | grep md
# → md127 : active raid1 sdd[0] sdb[1]
#     [====>................]  recovery = 22.45% ...
```
*Это инициирует штатное перестроение (rebuild) массива на новом диске.*

**Когда использовать lvconvert --replace vs pvmove:**

| Критерий | `lvconvert --replace` | `pvmove` |
| :--- | :--- | :--- |
| Тип LV | RAID (raid1/5/6/10) | Любой (linear, striped, mirror) |
| Скорость rebuild | Оптимизирована (dm-raid) | Медленнее (зеркальный LV) |
| Доступность LV | Доступен (read-only на время rebuild) | Доступен (чтение/запись) |
| Использование PV | Замена одного PV на другой | Перенос всех данных между PV |

### Сценарий 4: Аварийный вывод «мертвого» диска (Missing PV)

Если диск физически вышел из строя и его данные потеряны.

**Шаг 1: Диагностика**
```bash
sudo vgs
# → VG      #PV #LV #SN Attr   VSize  VFree
# → my_vg    2   3   0 wz-pn- 100.00g 20.00g
#                                   ^ p = partial

sudo pvs
# → PV         VG      Fmt  Attr PSize   PFree
# → /dev/sdb   my_vg    lvm2 a-p  <50.00g     0
# → /dev/sdc   my_vg    lvm2 a-p  <50.00g     0
# → /dev/sdd   my_vg    lvm2 ---  <50.00g <50.00g  ← новый диск
```

**Шаг 2: Удаление missing PV**
```bash
sudo vgreduce --removemissing --force my_vg
# → WARNING: Removing partial PV /dev/sdb.
# → WARNING: Logical volume my_vg/lv_data contains device mapper aspects.
# → Volume group "my_vg" successfully reduced
```

**Внимание:** Все логические тома, которые находились на этом диске (даже частично), будут безвозвратно удалены. Перед выполнением убедитесь, что нет возможности восстановить диск.

**Шаг 3: Проверка после удаления**
```bash
sudo vgs my_vg
# → VG      #PV #LV #SN Attr   VSize  VFree
# → my_vg    2   1   0 wz--n- 100.00g 40.00g

sudo lvs my_vg
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_data my_vg   -wi-------  20.00g
```

### Сценарий 5: Миграция конкретного логического тома

Если нужно освободить место на диске только для одного LV.
```bash
# Перемещение lv_data с /dev/sdc на /dev/sdd
sudo pvmove -n lv_data /dev/sdc /dev/sdd
# → pvmove: Moving 10.00 GiB of logical volume my_vg/lv_data from /dev/sdc to /dev/sdd.

# Проверка
sudo lvs -o lv_name,devices my_vg
# → LV      Devices
# → lv_data /dev/sdd(0-2559)
```

### Сценарий 6: Бесшовная конвертация в RAID (Online)

Ключевое преимущество LVM — возможность конвертировать обычный диск в RAID без остановки сервиса. Все логические тома остаются примонтированными и доступными.

**Исходная ситуация:** Диск `/dev/sdc` используется в VG `vg_data`, требуется перейти на RAID1 для отказоустойчивости.

**Шаг 1: Создание degraded RAID1**
```bash
# Создаём RAID1 с одним диском (missing = отсутствует второе устройство)
sudo mdadm --create /dev/md127 --level=1 --raid-devices=2 /dev/sdb missing
# → mdadm: array /dev/md127 started.
```

**Шаг 2: Добавление RAID в VG**
```bash
sudo pvcreate /dev/md127
sudo vgextend vg_data /dev/md127
```

**Шаг 3: Миграция данных**
```bash
# Перенос всех данных с sdc на RAID
sudo pvmove -i 10 /dev/sdc /dev/md127
# → /dev/sdc: Moved: 12.34%
# → /dev/sdc: Moved: 100.00%
```

**Важно:** Во время миграции логические тома остаются доступными для чтения/записи, но возможно снижение производительности дисковой системы.

**Шаг 4: Вывод исходного диска из VG**
```bash
sudo vgreduce vg_data /dev/sdc
```

**Шаг 5: Добавление исходного диска в RAID**
```bash
sudo mdadm /dev/md127 --add /dev/sdc
# → mdadm: added /dev/sdc
# Начнётся rebuild RAID1 на новый диск
```

**Проверка статуса RAID:**
```bash
cat /proc/mdstat
# → md127 : active raid1 sdc[2] sdb[0]
#     104320 blocks super 1.2 [2/1] [_U]
#     [====>................]  recovery = 22.45% ...

sudo mdadm --detail /dev/md127
```

### Сценарий 7: Миграция с шифрованием (LUKS)

При использовании LVM-over-LUKS процесс замены диска требует дополнительных шагов для расшифрования нового диска.

**Исходная ситуация:** VG `vg_secure` находится на LUKS-контейнере `/dev/mapper/encrypted_sdb`. Требуется замена `/dev/sdb` на `/dev/sdc`.

**Шаг 1: Подготовка нового диска с LUKS**
```bash
# Шифрование нового диска
sudo cryptsetup luksFormat /dev/sdc
sudo cryptsetup luksOpen /dev/sdc encrypted_sdc

# Создание PV на расшифрованном устройстве
sudo pvcreate /dev/mapper/encrypted_sdc
sudo vgextend vg_secure /dev/mapper/encrypted_sdc
```

**Шаг 2: Миграция данных**
```bash
sudo pvmove /dev/mapper/encrypted_sdb /dev/mapper/encrypted_sdc
```

**Шаг 3: Вывод старого диска**
```bash
sudo vgreduce vg_secure /dev/mapper/encrypted_sdb
sudo pvremove /dev/mapper/encrypted_sdb
sudo cryptsetup luksClose encrypted_sdb
```

> **Важно:** При автоматическом расшифровании при загрузке (в `/etc/crypttab`) необходимо обновить UUID нового диска.

### Сценарий 8: Нюансы для Тонких томов (Thin Pools)

Thin pool состоит из двух компонентов: LV данных (`tpool`) и LV метаданных (`tpool_tmeta`). При перемещении через pvmove оба компонента должны быть перемещены вместе.

**Подготовка:**
```bash
# Проверка структуры thin pool
sudo lvs -o lv_name,lv_size,segtype,devices vg_data
# → LV         LSize    SegType  Devices
# → tp_data    100.00g  thin-pool /dev/sdb(0-25599)
# → tp_data_tmeta 4.00m  linear   /dev/sdb(25600-25600)

# Проверка заполненности пула
sudo lvs -o lv_name,data_percent,metadata_percent | grep thin
# → tp_data   65.30   12.50
```

**Шаг 1: Проверка готовности**
```bash
# Thin pool НЕ должен быть заполнен на 100%
# Если data_percent > 90%, расширьте пул перед миграцией
sudo lvextend -L +10G vg_data/tp_data
```

**Шаг 2: Миграция thin pool**
```bash
# pvmove переместит оба компонента (data + tmeta)
sudo pvmove -i 10 /dev/sdb /dev/sdd
```

**Примечание:** Метаданные thin pool имеют небольшой размер (обычно 4–64 МиБ), но их перемещение может вызвать кратковременные блокировки (stalls) записи во всем пуле. Это нормальное поведение.

### Сценарий 9: Миграция между VG (vgsplit/vgmerge)

Когда диск нужно переместить из одной VG в другую. Напрямую pvmove между VG невозможен, но можно использовать комбинацию команд.

**Способ 1: Через pvmove после объединения VG (рекомендуется)**

```bash
# 1. Экспорт source VG (на另一 хосте или при отключении)
sudo vgexport source_vg

# 2. Импорт на целевом хосте
sudo vgimport source_vg

# 3. Объединение VG
sudo vgmerge target_vg source_vg

# 4. Миграция PV в пределах объединённой VG
sudo pvmove /dev/sdb /dev/sdc
```

**Способ 2: Через vgsplit (для разделения VG)**

```bash
# Разделение VG на две части
sudo vgsplit source_vg new_vg /dev/sdc
# → Volume group "source_vg" successfully split
# → 1 PV moved. Use "vgreduce source_vg /dev/sdc" to complete the split.
```

> **Подробнее:** [LVM — Управление томами](../management_operations.md) — шпаргалка по командам `vgsplit`, `vgmerge`, `vgexport`, `vgimport`.

### Сценарий 10: Миграция с iSCSI/Multipath

При работе с сетевыми блочными устройствами (iSCSI) через multipathpvmove требует дополнительной настройки фильтров.

**Подготовка:** Убедитесь, что multipath настроен и видит все пути:
```bash
sudo multipath -ll
# → mpatha (36001405...) dm-0 NETAPP,LUN
# size=50G features='1 queue_if_no_path' hwhandler='0' wp=rw
# `-+- policy='round-robin 0' prio=0 status=active
#   `- 3:0:0:0 sdb 8:16  active ready running
#   `- 4:0:0:0 sdc 8:32  active ready running
```

**Настройка LVM фильтра:** В `/etc/lvm/lvm.conf`:
```
filter = [ "a|/dev/mapper/mpath.*|", "r|/dev/sd.*|" ]
```

**Миграция:**
```bash
# Создание PV через multipath-устройство
sudo pvcreate /dev/mapper/mpatha

# pvmove работает через multipath transparently
sudo pvmove /dev/mapper/mpath_old /dev/mapper/mpath_new
```

> **Подробнее:** [LVM — iSCSI Multipath](../../Networking/iSCSI/iscsi_multipath.md) — настройка multipath и фильтров LVM.

### Сценарий 11: Мониторинг pvmove в реальном времени

Скрипт для автоматического мониторинга длительной миграции:

```bash
#!/bin/bash
# monitor_pvmove.sh — мониторинг pvmove каждые 30 секунд

LOG_FILE="/var/log/pvmove_$(date +%Y%m%d_%H%M%S).log"

echo "=== Мониторинг pvmove started: $(date) ===" | tee "$LOG_FILE"

while true; do
    # Проверка, запущен ли pvmove
    if ! pgrep -x pvmove > /dev/null; then
        echo "=== pvmove завершён: $(date) ===" | tee -a "$LOG_FILE"
        break
    fi

    # Статус миграции
    PROGRESS=$(sudo lvs -o+move_pv,move_pe --noheadings 2>/dev/null)
    if [ -n "$PROGRESS" ]; then
        echo "[$(date +%H:%M:%S)] Migration status:" | tee -a "$LOG_FILE"
        echo "$PROGRESS" | tee -a "$LOG_FILE"
    fi

    # I/O статистика
    echo "[$(date +%H:%M:%S)] I/O stats:" | tee -a "$LOG_FILE"
    iostat -d -x 1 1 | tail -n +3 | tee -a "$LOG_FILE"

    sleep 30
done

echo "=== Мониторинг завершён: $(date) ===" | tee -a "$LOG_FILE"
```

Запуск:
```bash
chmod +x monitor_pvmove.sh
sudo ./monitor_pvmove.sh &
```

## Дополнительная информация

### Нюансы: LVM и смешанные типы дисков

- **SSD + HDD в одной VG:** LVM не выравнивает производительность — часть LV на SSD будет быстрой, часть на HDD — медленной. Для большинства случаев это не рекомендуется. Исключение: выделение SSD для critical LV через `pvmove -n critical_lv /dev/ssd_pv`.
- **Разные размеры дисков:** LVM корректно работает с дисками разного размера, но RAID будет ограничен размером наименьшего диска. При замене диска на больший — дополнительное пространство станет доступно в VG.

### Лучшие практики

1. **Всегда выполняйте предварительную проверку** (Сценарий: Предварительная проверка) перед запуском pvmove.
2. **Используйте фоновый режим** (`-b`) для миграций > 10 ГиБ. Мониторинг через `lvs -o+move_pv,move_pe`.
3. **ionice -c3** для снижения нагрузки на производительность приложений. Комбинируйте с `nice -n19` для процесса pvmove.
4. **Не прерывайте миграцию** без необходимости. pvmove безопасен и возобновляется автоматически.
5. **Проверяйте free space** в VG перед миграцией. Недостаток места прервёт операцию.
6. **Для RAID-томов используйте `lvconvert --replace`** вместо pvmove — это быстрее и эффективнее.
7. **Thin pool не должен быть заполнен** на 100% перед pvmove. Расширьте пул заранее.
8. **После замены выполняйте `vgcfgbackup`** для сохранения актуальных метаданных.

### Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `pvmove: device not found` | Целевой PV недоступен | `sudo pvs` — проверить наличие PV, `pvcreate` если необходимо |
| `pvmove: not enough free extends` | Недостаточно места в VG | `sudo vgs` — проверить VFree, добавить PV через `vgextend` |
| `pvmove: abort requested` | Предыдущая миграция не завершена | `sudo pvmove --abort`, затем повторить |
| `pvmove: device is used by another process` | Другой процесс блокирует PV | `lsof /dev/sdc` — найти процесс, завершить или перезапустить |
| `vgreduce --removemissing: missing LV` | LV частично на missing PV | Подтвердить потерю данных или восстановить диск |
| `pvmove: read-only filesystem` | Thin pool заполнен | Расширить thin pool: `lvextend -L +SIZE VG/pool` |
| `pvmove hang / no progress` | I/O ошибки на диске | `dmesg \| grep error`, проверить SMART: `smartctl -a /dev/sdc` |
| `Couldn't find device with uuid` | Устаревшие метаданные | `vgreduce --removemissing VG` для очистки |

### Диагностические команды

```bash
# Статус pvmove (если запущен)
sudo lvs -o+move_pv,move_pe

# Проверка VG и PV
sudo vgs -o vg_name,vg_size,vg_free,vg_attr
sudo pvs -o pv_name,vg_name,pv_size,pv_free,pv_attr

# Проверка I/O ошибок
dmesg | tail -50 | grep -i "error\|fail\|offline"
sudo smartctl -a /dev/sdc

# Мониторинг I/O в реальном времени
iostat -x 5

# Проверка active_lv
sudo lvs -o lv_name,lv_attr | grep "^-.*a"

# Журнал LVM
sudo journalctl -u lvm2-lvmpolld --since "1 hour ago"

# Просмотр архива метаданных
sudo vgcfgrestore --list my_vg
```

### См. также
- **[LVM — Обзор и концепции](../overview_concepts.md)** — архитектура Device Mapper, принципы работы.
- **[LVM — Создание PV, VG и LV](./pv_vg_creation.md)** — инициализация новых дисков.
- **[LVM — Жизненный цикл](./lvm_lifecycle.md)** — общая логика управления, pvmove в контексте жизненного цикла.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — архитектура и мониторинг thin pool.
- **[LVM — Управление томами](../management_operations.md)** — шпаргалка по командам `vgsplit`, `vgmerge`, `vgexport`, `vgimport`.
