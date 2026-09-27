# Производительность LVM: влияние на дисковый ввод-вывод

## Определения

- **LVM (Logical Volume Manager):** Программный уровень виртуализации дискового пространства в Linux. Позволяет объединять физические диски (PV) в группы (VG) и создавать логические тома (LV) любого размера, не привязываясь к физическим границам разделов.
- **dm-* (Device Mapper):** Подсистема ядра Linux, реализующая логический уровень блочных устройств. LVM, RAID, LUKS, thin provisioning — все используют device-mapper. Устройства отображаются как `dm-0`, `dm-1` и т.д.
- **Thin Provisioning (Тонкое провизионирование):** Механизм динамического выделения физического пространства thin pool по мере записи данных. Виртуальный размер thin LV может превышать физический размер пула.
- **Thin Pool:** Пул физических блоков, из которого thin LV получают пространство. Состоит из data LV (данные) и metadata LV (метаданные о распределении блоков).
- **COW (Copy-on-Write):** Механизм, используемый LVM-снимками. При модификации данных сначала старый блок копируется в снимок, затем записывается новый. Снимки замедляют запись proportional количеству активных снимков.
- **Stripe (Чередование):** Распределение данных LV по нескольким PV для увеличения throughput. Аналог RAID 0 на уровне LVM.
- **Discard/TRIM:** Команда ОС для информирования устройства о неиспользуемых блоках. Критична для thin provisioning — без TRIM thin pool заполняется даже после удаления файлов.
- **dmeventd (Device Mapper Event Daemon):** Системный демон, мониторящий состояние LVM-объектов (thin pool, RAID, снимки). Автоматически расширяет thin pool при достижении порога заполнения.

## Основные концепции

### Архитектурные слои LVM и их влияние на I/O

```
Приложение
    ↓
Файловая система (ext4/xfs)
    ↓
Логический том (LV) ← здесь происходит виртуализация
    ↓
Device Mapper (dm-*) ← маршрутизация I/O
    ↓  (если thin)       (если stripe)        (если snapshot)
  thin pool             несколько PV            COW блоки
    ↓
Физические диски (PV: /dev/sda, /dev/nvme0n1)
```

Каждый добавленный слой увеличивает задержку. Для diagnosis важно знать, на каком уровне проблема.

### Влияние типов LV на I/O

| Тип LV | Overhead на запись | Overhead на чтение | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Linear** | Минимальный | Минимальный | Стандарт, большинство случаев |
| **Striped** | Минимальный | Увеличен throughput | Высокий throughput (несколько PV) |
| **Thin** | Средний (аллокация блоков) | Минимальный | Виртуализация, контейнеры, снимки |
| **Snapshot (COW)** | Высокий (копирование + запись) | Минимальный | Бэкапы, тестирование |
| **RAID (LVM)** | Аналогичен mdadm | Аналогичен mdadm | Избыточность через LVM |

### Thin Provisioning: скрытые проблемы

1. **Metadata Overhead:** Thin pool хранит карту блоков в metadata LV. При большом количестве малых файлов metadata может заполниться раньше data.
2. **Fragmentation:** Thin LV фрагментируются, так как блоки выделяются динамически. Чтение может Become random вместо sequential.
3. **Pool Overflow:** Заполнение thin pool на 100% делает ВСЕ LV в пуле read-only. Это критическая ситуация.
4. **Snapshot CoW Storm:** При активном снимке и обновлении исходного тома каждый изменяемый блок копируется в снимок. Много снимков = драматическое замедление записи.

### TRIM/Discard для thin provisioning

TRIM критически важен для thin provisioning:

```
Без TRIM:
  Файл удалён → ФС помечает блок как свободный → Thin pool всё ещё считает его занятым
  → Thin pool заполняется → Read-only mode

С TRIM:
  Файл удалён → ФС отправляет TRIM → Thin pool освобождает блок
  → Thin pool освобождается → Сохраняется работоспособность
```

## Предварительные требования

```bash
# Базовые инструменты LVM
sudo apt install lvm2    # Debian/Ubuntu
sudo dnf install lvm2    # RHEL/CentOS

# Проверка поддержки thin provisioning
sudo lvs -a -o +devices
sudo dmsetup status
```

## Практические сценарии

### Шаг 1: Определение типа LV и его влияния

```bash
# Просмотр всех LV с типами
sudo lvs -a -o lv_name,lv_attr,lv_size,segtype,devices
# → lv_data   -wi-a-----  100.00g  linear  /dev/sda1(0)
# → lv_thin   Vwi-a-t--  200.00g  thin    thin_pool(0)
# → lv_snap   Swi-a-----   50.00g  snapshot  lv_data(0)

# Идентификация через dm-*
ls -l /dev/mapper/
# → vg_data-lv_data -> ../dm-0
# → vg_data-lv_thin -> ../dm-1
# → vg_data-lv_snap -> ../dm-2

# Соответствие dm-* и физических дисков
ls -l /sys/block/dm-0/slaves/
# → sda1 sdb1 (какие физические диски у Linear LV)
```

### Шаг 2: Анализ thin pool

```bash
# Статус thin pool (data% и metadata%)
sudo lvs -o lv_name,lv_attr,data_percent,metadata_percent vg_data/thin_pool
# → thin_pool  twi-a-t--  100.00g  75.23   12.45
# → data_percent=75% → пулу осталось 25%
# → metadata_percent=12% → метаданные в норме

# Если data_percent > 80% → расширение
sudo lvextend -L +50G /dev/vg_data/thin_pool

# Проверка free space в pool
sudo vgs -o vg_name,vg_free
# → vg_data   50.00g (свободное место в VG для расширения)

# Если VG исчерпан — добавить физический диск
sudo pvcreate /dev/sdc
sudo vgextend vg_data /dev/sdc
```

### Шаг 3: Мониторинг thin pool (автоматическое расширение)

```bash
# Проверка dmeventd
systemctl status dmeventd
# → Active: active (running)

# Настройка автоматического расширения
sudo grep -E "thin_pool" /etc/lvm/lvm.conf
# → thin_pool_autoextend_threshold = 80
# → thin_pool_autoextend_percent = 20

# Если авто-расширение не работает:
sudo sed -i 's/thin_pool_autoextend_threshold = 100/thin_pool_autoextend_threshold = 80/' /etc/lvm/lvm.conf
sudo systemctl restart dmeventd
```

### Шаг 4: Диагностика COW-снимков

```bash
# Список снимков
sudo lvs -a -o lv_name,lv_attr,lv_size,snap_percent,devices
# → lv_snap  Swi-a-s--  50.00g  15.23  lv_data(0)
# → snap_percent=15% → снимок использует 15% от исходного тома

# Если snap_percent растет быстро:
# → Происходит интенсивная запись в исходный том
# → Каждый изменённый блок копируется в снимок
# → Решение: удалить снимок или перенести данные

# Удаление снимка (освобождает место)
sudo lvremove /dev/vg_data/lv_snap
```

### Шаг 5: Оптимизация stripe для throughput

```bash
# Создание striped LV для увеличения throughput
sudo lvcreate -L 200G -i 4 -I 128k -n lv_fast vg_data
# -i 4 — использовать 4 PV (чередование)
# -I 128k — размер stripe 128K

# Проверка
sudo lvs -o lv_name,stripes,stripe_size
# → lv_fast   4   128.00k

# Тест throughput
sudo fio --name=stripe_test --directory=/mnt/lv_fast --rw=read --bs=1M \
  --ioengine=libaio --iodepth=1 --direct=1 --size=2G --runtime=30
```

### Шаг 6: Отладка dm-* → физический диск

```bash
# Когда iostat показывает высокий await на dm-0, нужно найти физический диск

# Способ 1: через sysfs
ls -l /sys/block/dm-0/slaves/
# → sda1 sdb1

# Способ 2: через lvm
sudo lvs -o +devices
# → lv_data  vg_data  linear  /dev/sda1(0),/dev/sdb1(0)

# Способ 3: через dmsetup
sudo dmsetup deps /dev/mapper/vg_data-lv_data
# → 8:1 8:17 (major:minor номера физических устройств)

# Способ 4: параллельный iostat для всех устройств
iostat -xz 1 3 | grep -E "Device|dm-|sd[a-z]"
# → Сравниваем await на dm-0 и на sda/sdb
# → Если await на sda нормальный, а на dm-0 высокий → проблема в LVM-слое
```

### Шаг 7: Влияние thin snapshots на I/O

```bash
# Создание thin-снимка
sudo lvcreate -s -n snap_vm1 --thinpool vg_data/thin_pool /dev/vg_data/lv_vm1

# Мониторинг влияния на I/O
watch -n2 "sudo lvs -o lv_name,data_percent,metadata_percent vg_data/thin_pool && iostat -xz 1 1 | grep -E 'Device|dm-'"

# Если запись замедлилась после создания снимка:
# → Каждый изменённый блок копируется в снимок (COW)
# → Если снимок >50% заполнен — серьёзное замедление
# → Решение: удалить снимок или увеличить chunk size пула
```

## Автоматизация и мониторинг

### Prometheus метрики для LVM thin pool

```bash
#!/bin/bash
# /usr/local/bin/lvm_thin_exporter.sh
# Экспорт метрик thin pool для Prometheus

OUTPUT="/var/lib/node_exporter/textfile/lvm_thin.prom"

for pool in $(sudo lvs --noheadings -o lv_name,vg_name --sort lv_name | grep "tp\|thin" | awk '{print $2"/"$1}'); do
    vg=$(echo $pool | cut -d'/' -f1)
    lv=$(echo $pool | cut -d'/' -f2)
    data=$(sudo lvs -o data_percent --noheadings $pool | tr -d ' .')
    meta=$(sudo lvs -o metadata_percent --noheadings $pool | tr -d ' .')
    echo "lvm_thin_pool_data_percent{vg=\"$vg\",lv=\"$lv\"} $data" > ${OUTPUT}.tmp
    echo "lvm_thin_pool_meta_percent{vg=\"$vg\",lv=\"$lv\"} $meta" >> ${OUTPUT}.tmp
done
mv ${OUTPUT}.tmp $OUTPUT
```

### Алерты

```yaml
groups:
  - name: lvm_alerts
    rules:
      - alert: LVMThinPoolNearlyFull
        expr: lvm_thin_pool_data_percent > 80
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Thin pool {{ $labels.lv }} заполнен на {{ $value }}%"
          description: "Расширьте thin pool или выполните fstrim."

      - alert: LVMThinPoolCritical
        expr: lvm_thin_pool_data_percent > 95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "КРИТИЧЕСКОЕ заполнение thin pool {{ $labels.lv }}"
          description: "Thin pool может перейти в read-only. Немедленно расширьте."
```

## Типичные ошибки и устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `await` на dm-0 выше, чем на sda | Overhead device-mapper или thin provisioning | `lvs -o +devices`, сравнение `iostat` | Проверить тип LV, использовать linear вместо thin |
| Thin pool в read-only | Заполнение pool на 100% | `sudo lvs -o data_percent vg/pool` | Расширить pool, `lvchange -ay` для восстановления |
| Запись замедлилась после создания снимка | COW overhead | Мониторинг `snap_percent` | Удалить снимок, увеличить chunk size |
| TRIM не освобождает место в thin pool | ФС не поддерживает discard или не настроен | `fstrim -v /mountpoint`, проверка `discard` в fstab | Настроить `fstrim.timer` или добавить `discard` |
| `dm-0` heeft высокий `%util`, но физические диски простаивают | Thin pool metadata bottleneck | `sudo lvs -o metadata_percent` | Расширить metadata LV |
| LVM RAID: ребилд замедляет приложения | Двойная нагрузка (данные + ребилд) | `cat /proc/mdstat`, `iostat` | Снизить `speed_limit_max` |

## Ограничения и особые случаи

### Thin Pool и Overcommit

Thin provisioning позволяет overcommit: виртуальный размер LV может превышать физический. Это удобно, но опасно:
- При заполнении pool все LV становятся read-only
- Нет automatic enforcement (в отличие от memory overcommit)
- Рекомендация: мониторить `data_percent` и устанавливать алерты на 80%

### COW и базы данных

COW-снимки нежелательны для БД с интенсивной записью:
- Каждый обновлённый блок копируется в снимок
- Фрагментация растёт экспоненциально
- Решение: использовать `snapper` (Btrfs) или `pg_basebackup` (PostgreSQL)

### cgroups v2 и LVM

Writeback в cgroups v2 учитывает лимиты `memory.high`/`memory.max`:
- Если контейнер исчерпал `memory.max`, writeback может throttled
- Thin pool в контейнере может заполниться из-за того, что writeback не работает
- Рекомендация: настраивать `memory.swap.max=0` для контейнеров с БД

## Дополнительная информация

### См. также

- [LVM Thin Provisioning](../../../../FileSystems/LVM/thin-provisioning.md) — подробный разбор thin pool.
- [LVM: расширенные темы](../../../../FileSystems/LVM/advanced_topics/advanced_topics.md) — RAID в LVM, снимки, performance.
- [fstrim: обслуживание SSD](../../../../SystemAdministration/fstrim_ssd_maintenance.md) — TRIM для thin provisioning.
- [Диагностический чеклист I/O](./diagnostic_checklist.md) — пошаговый алгоритм поиска проблем.
