# LVM: Практические сценарии восстановления и оптимизации

## Определения

**Восстановление метаданных (Metadata Recovery)** — процесс реанимации структуры групп томов и логических томов из резервных копий конфигурации или дампов метаданных физических томов.

**Миграция Swap (Swap Migration)** — перенос области подкачки (Swap) с выделенного логического тома LVM в файл или на другой носитель для освобождения места в группе томов или упрощения управления.

**vgsplit / vgmerge** — стандартные утилиты LVM для перемещения существующих логических томов (вместе с их физическими экстентами) между разными группами томов.

**thin_repair / thin_dump** — системные утилиты для восстановления поврежденных метаданных тонких пулов (Thin Pools), когда стандартные средства LVM не могут активировать пул.

## Базовые концепции

### Механизмы защиты данных

LVM обеспечивает высокую отказоустойчивость благодаря автоматическому резервированию метаданных:
1.  **Backup (`/etc/lvm/backup/`):** содержит последнее актуальное состояние каждой VG.
2.  **Archive (`/etc/lvm/archive/`):** хранит историю изменений. Файлы создаются автоматически **до** выполнения любой команды, изменяющей структуру VG. Это позволяет откатиться к состоянию, например, до удаления LV.

### Стратегии миграции

Миграция ресурсов может происходить как внутри одной VG (`pvmove`), так и между разными VG (`vgsplit`). Перенос данных между независимыми хостами требует использования процедур экспорта/импорта (`vgexport`/`vgimport`).

## Практические сценарии

### Сценарий 1: Восстановление PV после повреждения заголовка

Используется, если диск физически исправен, но LVM перестал распознавать его как PV (ошибка `unknown device` или `can't read LVM label`).

**Шаг 1: Поиск UUID поврежденного тома**
UUID можно найти в последнем бэкапе метаданных в `/etc/lvm/backup/`.
```bash
sudo grep -A 10 "physical_volumes" /etc/lvm/backup/vg_data
# → pv0 {
# →     id = "XYZ-123-abc-..."
```

**Шаг 2: Восстановление метки PV**
```bash
sudo pvcreate --uuid "XYZ-123-abc-..." --restorefile /etc/lvm/backup/vg_data /dev/sdb1
```

**Шаг 3: Восстановление структуры группы томов**
```bash
sudo vgcfgrestore vg_data
sudo vgchange -ay vg_data
```

### Сценарий 2: Восстановление случайно удаленного LV

Если вы выполнили `lvremove`, данные на диске остаются целыми, пока экстенты не будут выделены под новый LV и затерты.

**Шаг 1: Поиск нужного архива**
Найдите файл архива, созданный непосредственно перед командой удаления.
```bash
sudo vgcfgrestore --list vg_data
# → File: /etc/lvm/archive/vg_data_00005-98765.vg
# → Description: Created before executing 'lvremove -f vg_data/lv_critical'
```

**Шаг 2: Тестовое и финальное восстановление**
```bash
# Проверка (рекомендуется)
sudo vgcfgrestore --test -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data

# Восстановление метаданных
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00005-98765.vg vg_data
sudo vgchange -ay vg_data
```

### Сценарий 3: Перенос Swap с LV в файл (Освобождение VG)

Сценарий полезен, когда Swap занимает место в VG, необходимое для расширения других томов.

**Шаг 1: Отключение текущего Swap**
```bash
sudo swapoff -v /dev/vg_system/lv_swap
```

**Шаг 2: Создание файла подкачки**
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

**Шаг 3: Обновление `/etc/fstab`**
Замените путь к LV на `/swapfile`.

**Шаг 4: Удаление старого LV**
```bash
sudo lvremove /dev/vg_system/lv_swap
```

### Сценарий 4: Передача пространства между VG (vgsplit + vgmerge)

Задача: передать диск (или его часть) из `vg_old` в `vg_new`.

**Шаг 1: Подготовка (pvmove)**
Если диск `/dev/sdc1` занят другими LV в `vg_old`, переместите данные с него.
```bash
sudo pvmove /dev/sdc1
```

**Шаг 2: Отделение диска в новую временную группу**
```bash
sudo vgsplit vg_old vg_transfer /dev/sdc1
# → Volume group "vg_transfer" successfully split from "vg_old"
```

**Шаг 3: Слияние групп**
```bash
sudo vgmerge vg_new vg_transfer
# → Volume group "vg_transfer" successfully merged into "vg_new"
```

### Сценарий 5: Восстановление поврежденного Тонкого пула

Если тонкий пул не активируется из-за повреждения метаданных (например, после аварийного отключения питания).

**Шаг 1: Проверка состояния**
```bash
sudo lvs -a -o name,attr,metadata_percent
# Атрибут 'M' (metadata out of space) или отсутствие активации пула.
```

**Шаг 2: Ремонт метаданных (Offline)**
```bash
# Деактивация пула (если возможно)
sudo lvchange -an vg_data/thin_pool

# Попытка автоматического восстановления метаданных
sudo lvconvert --repair vg_data/thin_pool
```

### Сценарий 6: Восстановление деградированного LVM RAID

Если один из дисков в LVM RAID 1/5/6 вышел из строя.

**Шаг 1: Идентификация сбойного PV**
```bash
sudo lvs -a -o name,copy_percent,devices
# → raid_lv  100.00  [raid_lv_rimage_0](0), [raid_lv_rimage_1](unknown)
```

**Шаг 2: Замена сбойного устройства**
```bash
# Если новый диск уже добавлен в VG
sudo lvconvert --repair vg_data/raid_lv
```

## Дополнительная информация

### См. также
- **[LVM — Расширенные темы (Загрузка и Диагностика)](./advanced_topics.md)** — фильтры `lvm.conf` и `initramfs`.
- **[LVM — Тонкое провизионирование](../thin-provisioning.md)** — архитектура и мониторинг пулов.
- **[LVM — Замена диска](../operations/lvm_disk_replacement.md)** — плановая миграция через `pvmove`.
