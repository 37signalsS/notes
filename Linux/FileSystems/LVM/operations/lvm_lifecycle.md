# Жизненный цикл LVM

## Определения

**Жизненный цикл LVM (LVM Lifecycle)** — совокупность этапов существования системы логических томов: от инициализации физических носителей и агрегации ресурсов до эксплуатации, миграции и окончательной утилизации. Каждый этап имеет строго определённый порядок действий и требования к целостности данных.

**Активация (Activation)** — процесс перевода группы томов (VG) или логического тома (LV) в состояние готовности к использованию ядром Linux. Активация выполняется через интерфейс Device Mapper, который создаёт блочные устройства `/dev/mapper/` и регистрирует их в ядре. Деактивированные тома недоступны для ввода-вывода, но сохраняют целостность данных.

**Экспорт/Импорт (Export/Import)** — механизм подготовки группы томов для физического переноса между разными операционными системами или аппаратными узлами. Экспорт помечает метаданные VG как «неактивные» и «экспортированные», что позволяет другому хосту безопасно импортировать группу без конфликтов UUID.

**Метаданные LVM** — служебная информация, описывающая структуру VG, PE-карту и параметры томов. Хранится в начале PV (Metadata Area, MDA) в текстовом формате и дублируется в `/etc/lvm/backup/` и `/etc/lvm/archive/`. Метаданные — ключевой элемент целостности: их повреждение приводит к недоступности всех томов в группе.

**PV Move (pvmove)** — механизм онлайн-миграции физических экстентов между PV без остановки сервисов. Используется при замене дисков, балансировке нагрузки или подготовке к выводу носителя из эксплуатации.

**VG Split/Merge (vgsplit/vgmerge)** — операции разделения и слияния групп томов для передачи PV между VG. Позволяют организовать гибкое управление ресурсами без потери данных.

## Базовые концепции

### Принцип иерархии и порядка операций

Управление LVM — это иерархический процесс. Ошибки на нижних уровнях (PV) каскадно влияют на работоспособность всей системы.

```text
Уровень 3: LV (Логический том)     → файловая система, данные
    ↑
Уровень 2: VG (Группа томов)      → пул ресурсов, PE/LE
    ↑
Уровень 1: PV (Физический том)    → физические диски, метки LVM
    ↑
Уровень 0: Block Device            → /dev/sd*, /dev/nvme*, /dev/mapper/*
```

**Критическое правило:** Порядок операций при расширении — «снизу вверх» (PV → VG → LV → ФС). При уменьшении — «сверху вниз» (ФС → LV → VG → PV). Нарушение этого порядка приводит к потере данных.

### Этапы жизненного цикла

| Этап | Уровень | Описание | Ключевые команды |
| :--- | :--- | :--- | :--- |
| **1. Инициализация** | PV | Запись LVM-меток и резервирование места под метаданные на диске | `pvcreate`, `pvremove` |
| **2. Агрегация** | VG | Создание пула ресурсов, определение размера PE | `vgcreate`, `vgextend`, `vgreduce` |
| **3. Выделение** | LV | Нарезка виртуальных блочных устройств | `lvcreate`, `lvremove`, `lvrename` |
| **4. Эксплуатация** | LV/ФС | Работа с ФС, создание снимков, расширение томов | `mount`, `lvextend`, `lvcreate --snapshot` |
| **5. Миграция** | PV/VG | Перемещение данных между дисками или системами | `pvmove`, `vgexport`, `vgimport`, `vgsplit`, `vgmerge` |
| **6. Утилизация** | Все | Демонтаж структур в порядке, строго обратном созданию | `lvremove`, `vgremove`, `pvremove` |

### Механизм активации: Device Mapper и udev

При активации VG/LVM происходит следующее:

1. **Сканирование:** LVM сканирует все блочные устройства в поисках меток (`pvscan`)
2. **Чтение метаданных:** Для каждого найденного PV читаются метаданные VG из MDA
3. **Построение карты:** Device Mapper создаёт таблицу маппинга LE→PE для каждого LV
4. **Регистрация:** Создаются блочные устройства `/dev/mapper/vg_data-lv_app` и `/dev/vg_data/lv_app`
5. **Уведомление:** udev получает событие и создаёт символические ссылки

**Автоматическая активация:** Современные дистрибутивы активируют LVM автоматически при загрузке через:
- `systemd`服务 `lvm2-pvscan@.service` — сканирует PV при обнаружении устройства
- Правила `udev` — вызывают `pvscan` при появлении нового блочного устройства
- `initramfs` — для корневых VG активация происходит на этапе загрузки

**Ручная активация:**
```bash
# Активация всех VG
sudo vgchange -ay

# Активация конкретной VG
sudo vgchange -ay vg_data

# Активация конкретного LV
sudo lvchange -ay /dev/vg_data/lv_app

# Деактивация LV (требует отмонтирования)
sudo lvchange -an /dev/vg_data/lv_app
```

### Частичная активация и потеря PV

Если один из PV в группе отсутствует (повреждён, отключён), VG не активируется автоматически. Команда `vgchange -ay --partial` позволяет принудительно активировать уцелевшие LV.

**Риски частичной активации:**
- Файловая система может быть повреждена из-за отсутствующих экстентов
- Рекомендуется активация в режиме только чтения (RO)
- Данные на отсутствующих PV будут недоступны

```bash
# Проверка отсутствующих PV
sudo vgs -o pv_missing
# → VG      #PV #LV #SN Attr   VSize   VFree   PV Missing
# → data_vg   2   1   0 wz-pn- <20.00g <5.00g  1

# Частичная активация (только чтение)
sudo vgchange -ay --partial --partial vg_data
# → 1 logical volume(s) in volume group "vg_data" now active
```

**Восстановление после потери PV:**
1. Удаление отсутствующего PV из VG: `sudo vgreduce --removemissing vg_data`
2. Замена диска и добавление нового PV: `sudo pvcreate /dev/sdX && sudo vgextend vg_data /dev/sdX`
3. Восстановление данных из резервной копии или снапшота

### Метаданные: хранение и защита

LVM обеспечивает тройное хранение метаданных:

| Расположение | Формат | Назначение | Доступность |
| :--- | :--- | :--- | :--- |
| **MDA на PV** | Текстовый (ASCII) | Описание структуры VG в начале каждого PV | Доступно всегда при работоспособном диске |
| **/etc/lvm/backup/** | Текстовый | Актуальная копия метаданных каждой VG | Доступно в файловой системе |
| **/etc/lvm/archive/** | Текстовый | История изменений (автоматический бэкап **до** команды) | Доступно в файловой системе |

**Критически важно:** Метаданные на PV — это единственный источник истины. Файлы в `/etc/lvm/` — это резервные копии. При восстановлении используется именно MDA на PV.

**Автоматическое резервное копирование:**
- При каждой команде, изменяющей структуру VG (`lvcreate`, `lvextend`, `vgextend`, `pvmove` и др.), LVM автоматически создаёт копию текущих метаданных в `/etc/lvm/archive/`
- Актуальная версия хранится в `/etc/lvm/backup/`
- История позволяет откатиться к любому предыдущему состоянию

### Интеграция с systemd

LVM интегрируется с `systemd` через следующие службы:

| Служба | Назначение | Автозапуск |
| :--- | :--- | :--- |
| `lvm2-pvscan@.service` | Автоматическое сканирование PV при обнаружении устройства | Да (udev trigger) |
| `lvm2-monitor.service` | Мониторинг состояния томов через `dmeventd` | Да |
| `lvm2-lvmpolld.service` | Поллинг для длительных операций (pvmove) | Да |
| `lvm2-activation@.service` | Активация VG при загрузке | Да (initramfs) |

**Проверка статуса служб:**
```bash
# Проверка статуса мониторинга
sudo systemctl status lvm2-monitor.service
# → ● lvm2-monitor.service - Monitoring of LVM2 mirrors and snapshots
# →    Loaded: loaded (/usr/lib/systemd/system/lvm2-monitor.service; enabled)

# Просмотр логов LVM
sudo journalctl -u lvm2-monitor.service
```

## Предварительные требования

### Необходимые пакеты

| Пакет | Дистрибутив | Назначение |
| :--- | :--- | :--- |
| `lvm2` | Все | Основной инструментарий LVM |
| `device-mapper` | Все | Ядерный модуль для управления блочными устройствами |
| `udev` | Все | Правила для автоматической активации |
| `systemd` | Все | Интеграция с системой инициализации |

### Проверка версий

```bash
# Проверка версии LVM
sudo lvm version
# → LVM version:     2.03.11 (2021-01-08)
# → Library version: 1.02.168 (2021-01-08)
# → Driver version:  4.45.0

# Проверка ядерного модуля Device Mapper
lsmod | grep dm
# → dm_mod              245760  8 dm_mirror,dm_thin_pool,dm_log

# Проверка доступных systemd служб
systemctl list-unit-files | grep lvm
# → lvm2-activation@.service              static
# → lvm2-lvmpolld.service                 enabled
# → lvm2-monitor.service                  enabled
# → lvm2-pvscan@.service                  static
```

### Права доступа

Все операции LVM требуют.root-привилегий. Убедитесь, что:
- Пользователь имеет права `sudo` без пароля для LVM-команд
- Сервисы не блокируют устройства (проверка через `lsof` или `fuser`)

```bash
# Проверка активных процессов, использующих LV
sudo lsof /dev/mapper/vg_data-lv_app
sudo fuser -vm /dev/mapper/vg_data-lv_app
```

## Практические сценарии

### Сценарий 1: Полный цикл — от создания до удаления

**Шаг 1: Подготовка носителей**
```bash
# Проверка доступных дисков
lsblk
# → NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# → sdc      8:32   0   20G  0 disk

# Инициализация PV
sudo pvcreate /dev/sdc
# → Physical volume "/dev/sdc" successfully created.

# Верификация
sudo pvs /dev/sdc
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdc           lvm2 ---  20.00g 20.00g
```

**Шаг 2: Создание и нарезка пула**
```bash
# Создание VG
sudo vgcreate vg_data /dev/sdc
# → Volume group "vg_data" successfully created

# Создание LV
sudo lvcreate -L 10G -n lv_app vg_data
# → Logical volume "lv_app" created.

# Верификация
sudo lvs vg_data
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_app  vg_data -wi-a-----  10.00g
```

**Шаг 3: Создание ФС и монтирование**
```bash
# Создание ext4
sudo mkfs.ext4 /dev/vg_data/lv_app

# Монтирование
sudo mkdir -p /mnt/app
sudo mount /dev/vg_data/lv_app /mnt/app

# Проверка
df -hT /mnt/app
# → Filesystem              Type  Size  Used Avail Use% Mounted on
# → /dev/mapper/vg_data-lv_app ext4   10G   34M  9.3G   1% /mnt/app
```

**Шаг 4: Демонтаж (Удаление)**
Удаление выполняется строго в обратном порядке.
```bash
# Размонтирование
sudo umount /mnt/app

# Удаление LV
sudo lvremove /dev/vg_data/lv_app
# → Do you really want to remove and DISCARD active logical volume "lv_app"? [y/n]: y
# → Logical volume "lv_app" successfully removed.

# Удаление VG
sudo vgremove vg_data
# → Volume group "vg_data" successfully removed

# Удаление PV (очистка меток)
sudo pvremove /dev/sdc
# → Labels on physical volume "/dev/sdc" successfully wiped.

# Верификация
sudo pvs
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdc           lvm2 ---  20.00g 20.00g
```

### Сценарий 2: Перенос группы томов на другой сервер

Используется при физическом перемещении дисков между хостами. Метаданные VG помечаются как «экспортированные», что позволяет безопасно импортировать группу на другом сервере.

**На исходном сервере:**
```bash
# 1. Отмонтирование всех LV в VG
sudo umount /mnt/data

# 2. Деактивация VG (все LV должны быть неактивны)
sudo vgchange -an vg_data
# → 0 logical volume(s) in volume group "vg_data" now active

# 3. Экспорт (пометка метаданных как экспортированных)
sudo vgexport vg_data
# → Volume group "vg_data" successfully exported

# Верификация
sudo vgs
# → VG      #PV #LV #SN Attr   VSize   VFree
# → vg_data   1   1   0 wzx-- <20.00g <5.00g
#                ^^^^ (флаг 'x' означает exported)
```

**На целевом сервере:**
```bash
# 1. Сканирование PV (поиск экспортированных VG)
sudo pvscan
# → PV /dev/sdc    is in exported VG vg_data [20.00 GiB / 5.00 GiB free]

# 2. Импорт (снятие пометки «экспортировано»)
sudo vgimport vg_data
# → Volume group "vg_data" successfully imported

# 3. Активация
sudo vgchange -ay vg_data
# → 1 logical volume(s) in volume group "vg_data" now active

# 4. Монтирование
sudo mount /dev/vg_data/lv_data /mnt/data

# Верификация
sudo lvs vg_data
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_data vg_data -wi-a-----  15.00g
```

### Сценарий 3: Клонирование дисков и обработка дубликатов UUID

При клонировании дисков на уровне СХД или с помощью `dd` возникает конфликт UUID. LVM не позволит активировать VG с дублирующимися UUID.

**Симуляция проблемы:**
```bash
# Попытка импорта клонированного диска
sudo pvscan
# → Found duplicate PV XYZ-123-abc-... using /dev/sdb
# → Found duplicate PV XYZ-123-abc-... using /dev/sdc
# → WARNING: Duplicate VG name vg_data - ignoring /dev/sdc
```

**Решение с помощью vgimportclone:**
```bash
# 1. Проверка конфликтующих PV
sudo pvs
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdb   vg_data lvm2 a--  20.00g  5.00g
# → /dev/sdc           lvm2 ---  20.00g 20.00g
#                      ^^^^ (VG не назначена из-за дубликата)

# 2. Импорт клона с переименованием VG и сменой UUID
sudo vgimportclone --basevgname vg_data_clone /dev/sdc
# → Volume group "vg_data" successfully cloned to "vg_data_clone"

# Верификация
sudo vgs
# → VG            #PV #LV #SN Attr   VSize   VFree
# → vg_data           1   1   0 wz--n- <20.00g <5.00g
# → vg_data_clone     1   1   0 wz--n- <20.00g <5.00g

sudo pvs
# → PV         VG            Fmt  Attr PSize  PFree
# → /dev/sdb   vg_data       lvm2 a--  20.00g  5.00g
# → /dev/sdc   vg_data_clone lvm2 a--  20.00g  5.00g
```

### Сценарий 4: Восстановление метаданных (Disaster Recovery)

LVM позволяет откатить состояние всей группы томов (VG) к предыдущему чекпоинту из архива метаданных.

**Шаг 1: Поиск нужной точки отката**
```bash
sudo vgcfgrestore --list vg_data
# → File:   /etc/lvm/archive/vg_data_00040-12345.vg
# → VG Name: vg_data
# → Description:  Created before executing 'lvextend -L +5G vg_data/lv_app'
# → 
# → File:   /etc/lvm/archive/vg_data_00041-12345.vg
# → VG Name: vg_data
# → Description:  Created before executing 'lvremove vg_data/lv_old'
# → 
# → File:   /etc/lvm/archive/vg_data_00042-12345.vg
# → VG Name: vg_data
# → Description:  Created before executing 'lvextend -L +10G vg_data/lv_app'
```

**Шаг 2: Тестовое восстановление (рекомендуется)**
```bash
# Проверка без фактического применения
sudo vgcfgrestore --test -f /etc/lvm/archive/vg_data_00040-12345.vg vg_data
# → Test mode: Metadata will NOT be written and no changes will be made.
```

**Шаг 3: Фактическое восстановление**
```bash
sudo vgcfgrestore -f /etc/lvm/archive/vg_data_00040-12345.vg vg_data
# → Restored volume group vg_data

# Активация VG
sudo vgchange -ay vg_data
# → 1 logical volume(s) in volume group "vg_data" now active

# Проверка
sudo lvs vg_data
# → LV      VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_app  vg_data -wi-------  10.00g
```

**Важно:** После восстановления метаданных LV могут стать неактивными. Необходимо повторно выполнить `vgchange -ay`.

### Сценарий 5: Оперативная миграция данных (pvmove)

pvmove выполняет онлайн-миграцию физических экстентов между PV без остановки сервисов. Используется при замене дисков, балансировке нагрузки или подготовке к выводу носителя.

```bash
# 1. Проверка исходного состояния
sudo pvs
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdb   vg_data lvm2 a--  20.00g  5.00g
# → /dev/sdc   vg_data lvm2 a--  20.00g 20.00g

# 2. Миграция всех экстентов с /dev/sdb на /dev/sdc
sudo pvmove /dev/sdb /dev/sdc
# → pvmove: Moving 15.00 GiB of logical volume vg_data/lv_app from /dev/sdb to /dev/sdc.

# 3. Проверка результата
sudo pvs
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdb           lvm2 a--  20.00g 20.00g
# → /dev/sdc   vg_data lvm2 a--  20.00g  5.00g

# 4. Удаление исходного PV из VG
sudo vgreduce vg_data /dev/sdb
# → Removed "/dev/sdb" from volume group "vg_data"

# 5. Очистка меток LVM
sudo pvremove /dev/sdb
# → Labels on physical volume "/dev/sdb" successfully wiped.
```

**Тонкости pvmove:**
- Операция выполняется транзакционно: прерывание не повреждает данные
- Используйте `-i` для интервала обновления прогресса: `pvmove -i 5 /dev/sdb`
- Для фонового режима: `pvmove -b /dev/sdb` (мониторинг через `lvs`)
- С настроенными тегами можно мигрировать конкретные LV: `pvmove -t database /dev/sdb`

### Сценарий 6: Передача пространства между VG (vgsplit + vgmerge)

Задача: передать диск (или его часть) из одной VG в другую без потери данных.

**Шаг 1: Подготовка (pvmove)**
Если целевой диск занят LV, переместите данные с него.
```bash
# Проверка, какие LV используют целевой PV
sudo pvs -o pv_name,vg_name,lv_name
# → PV         VG      LV
# → /dev/sdc   vg_old  lv_app
# → /dev/sdc   vg_old  lv_db
# → /dev/sdb   vg_old  lv_data

# Миграция данных с /dev/sdc на другие PV
sudo pvmove /dev/sdc
# → pvmove: Moving 15.00 GiB of logical volume vg_old/lv_app from /dev/sdc to /dev/sdb.

# Проверка, что PV свободен
sudo pvs /dev/sdc
# → PV         VG      Fmt  Attr PSize  PFree
# → /dev/sdc           lvm2 ---  20.00g 20.00g
```

**Шаг 2: Отделение диска во временную группу**
```bash
sudo vgsplit vg_old vg_transfer /dev/sdc
# → Volume group "vg_transfer" successfully split from "vg_old"

# Верификация
sudo vgs
# → VG          #PV #LV #SN Attr   VSize   VFree
# → vg_old        1   2   0 wz--n- <20.00g  5.00g
# → vg_transfer   1   0   0 wz--n- <20.00g 20.00g
```

**Шаг 3: Слияние с целевой VG**
```bash
sudo vgmerge vg_new vg_transfer
# → Volume group "vg_transfer" successfully merged into "vg_new"

# Верификация
sudo vgs
# → VG      #PV #LV #SN Attr   VSize    VFree
# → vg_new    2   3   0 wz--n- <40.00g <25.00g
```

**Важно:** Все LV в переносимой VG должны быть деактивированы перед `vgsplit`.

### Сценарий 7: Восстановление загрузки при проблемах с LVM

Если система не находит VG при загрузке (ошибка `Volume group not found`), необходимо восстановить initramfs.

**Для Debian / Ubuntu:**
```bash
# Загрузка с LiveCD и монтирование корня
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /mnt

# Chroot в целевую систему
sudo chroot /mnt

# Добавление модуля LVM в initramfs
echo "lvm2" | tee -a /etc/initramfs-tools/modules

# Обновление образа
update-initramfs -u

# Обновление GRUB
update-grub
```

**Для RHEL / Rocky / Fedora (dracut):**
```bash
# Загрузка с LiveCD
sudo vgchange -ay vg_system
sudo mount /dev/vg_system/lv_root /mnt
sudo chroot /mnt

# Принудительное включение модуля LVM
dracut --force --add lvm --regenerate-all

# Обновление GRUB
grub2-mkconfig -o /boot/grub2/grub.cfg
```

**Верификация:**
```bash
# Проверка наличия LVM в initramfs
lsinitramfs /boot/initrd.img-$(uname -r) | grep lvm
# → usr/sbin/lvm
# → usr/lib/x86_64-linux-gnu/libdevmapper.so.1.02.1

# Проверка конфигурации initramfs (RHEL)
lsinitrd /boot/initramfs-$(uname -r).img | grep lvm
```

### Сценарий 8: Массовое управление через теги

Теги LVM позволяют выполнять действия над группой объектов одновременно, что критично для управления большими инфраструктурами.

```bash
# 1. Назначение тегов
sudo vgchange --addtag production vg_data
sudo lvchange --addtag database vg_data/lv_db_01
sudo lvchange --addtag database vg_data/lv_db_02
sudo lvchange --addtag webserver vg_data/lv_web

# 2. Просмотр объектов с определенным тегом
sudo lvs @database
# → LV       VG      Attr       LSize   Pool Origin Data%  Meta%
# → lv_db_01 vg_data -wi------- 100.00g
# → lv_db_02 vg_data -wi------- 100.00g

# 3. Массовая деактивация по тегу
sudo lvchange -an @database
# → 2 logical volume(s) in volume group "vg_data" now inactive

# 4. Массовая активация по тегу
sudo lvchange -ay @database
# → 2 logical volume(s) in volume group "vg_data" now active

# 5. Комбинированные запросы (AND/OR)
sudo lvs @database,@webserver
sudo lvs @production && lvs @database
```

### Сценарий 9: Проверка здоровья и мониторинг состояния

```bash
# 1. Проверка физических дисков
sudo pvs
# → PV         VG      Fmt  Attr PSize   PFree
# → /dev/sdb   data_vg lvm2 a--  <20.00g <5.00g
# → /dev/sdc   data_vg lvm2 a--  <20.00g 20.00g

# 2. Проверка свободного места в группах
sudo vgs
# → VG      #PV #LV #SN Attr   VSize   VFree
# → data_vg   2   3   0 wz--n- <40.00g <25.00g

# 3. Поиск переполненных томов или снимков
sudo lvs -o lv_name,data_percent,snap_percent
# → LV          Data%  Snap%
# → lv_app      85.23
# → lv_snapshot      -  45.67

# 4. Проверка атрибутов (активность, тип)
sudo lvs -a -o lv_name,lv_attr,devices
# → LV              Attr       Devices
# → lv_app          -wi-ao---- 1
# → [lvol0]         -wi------- 1

# 5. Проверка целостности метаданных
sudo vgck data_vg
# → No errors found

# 6. Проверка journal для ошибок LVM
sudo journalctl -k | grep -i "device-mapper\|lvm\|dm-"
```

## Дополнительная информация

### Лучшие практики

1. **Резервное копирование метаданных:** Регулярно создавайте ручные копии `/etc/lvm/backup/` и `/etc/lvm/archive/`. Храните их за пределами управляемой системы.

2. **Мониторинг свободного места:** Настройте алерты на достижение 80% и 90% заполнения VG:
   ```bash
   # Проверка свободного места
   sudo vgs --noheadings --nosuffix --units g -o vg_name,v_free
   # → data_vg 5.00
   ```

3. **Документация:** Ведите журнал изменений размеров и конфигурации. Фиксируйте дату, оператора, исходный и целевой размеры.

4. **Тестирование:** На non-production окружении проверяйте критические операции (vgexport, vgsplit, vgcfgrestore) перед выполнением на боевых серверах.

5. **Именование:** Используйте осмысленные имена PV/VG/LV. Избегайте имён, содержащих пробелы или специальные символы.

6. **Минимизация downtime:** Для критичных сервисов используйте онлайн-операции (pvmove, lvextend) и планируйте работы в окно минимальной нагрузки.

### Граничные случаи и ограничения

1. **Размер PE:** При создании VG размер PE фиксируется. Все последующие операции кратны этому размеру. Для массивов >100 ТБ рекомендуется увеличивать PE до 32–128 МиБ.

2. **Максимальный размер LV:** Зависит от архитектуры:
   - 32-битные ядра: ~2 ТБ (с 4 МиБ PE)
   - 64-битные ядра: ~8 ЭиБ (теоретический предел)

3. **Дублирование UUID:** При клонировании дисков (rsync, dd) возникают дубли UUID. Используйте `vgimportclone` для переименования VG.

4. **Загрузка:** Если корневой раздел (`/`) находится на LVM, расширение может потребовать пересборки initramfs.

5. **Thin Pool overflow:** Если тонкий пул заполняется на 100%, том переходит в режим read-only. Решение: расширение пула или удаление данных.

6. **VDO Pool exhaustion:** Аналогично thin pool — при заполнении VDO Pool устройство становится read-only. Требует `fstrim` для освобождения неиспользуемых блоков.

7. **Снимки при расширении:** Активные снимки могут влиять на производительность расширения. Рекомендуется удалять временные снимки перед масштабными операциями.

8. **Partial activation:** При частичной активации VG данные на отсутствующих PV недоступны. ФС может работать некорректно.

### Устранение неполадностей

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Volume group not found` | VG не активирована или отсутствует PV | Выполнить `vgscan`, проверить `lvm.conf` фильтры, выполнить `vgchange -ay` |
| `Physical volume not found` | Диск не подключён или отсутствует метка LVM | Проверить `lsblk`, выполнить `pvscan`, проверить фильтры |
| `Couldn't find device with uuid` | Устаревшие метаданные или удалённый диск | Выполнить `vgreduce --removemissing VG_NAME` для очистки |
| `Duplicate PV UUID` | Клонирование дисков | Использовать `vgimportclone` для переименования VG и смены UUID |
| `Logical volume contains a filesystem in use` | ФС смонтирована или используется процессом | Выполнить `umount`, затем повторить операцию. Для root — загрузка с LiveCD |
| `Metadata checksum error` | Повреждение MDA на PV | Использовать `pvck --repair` или восстановить из `/etc/lvm/backup/` |
| `Thin pool is full` | Тонкий пул заполнен на 100% | Расширить пул: `lvextend -L +SIZE VG/pool`. ФС перейдёт в read-only |
| `VDO pool is full` | VDO Pool исчерпан | Расширить пул или выполнить `fstrim -v /mountpoint` для освобождения блоков |
| `Part of LV is missing` | Физический диск повреждён или отключён | Проверить `pvs`, восстановить диск или выполнить `vgreduce --removemissing` |
| `metadata not found` | Повреждение области метаданных PV | Использовать `pvck --repair` или восстановить из `/etc/lvm/backup/` |

### Диагностические команды

```bash
# Быстрая проверка состояния всех уровней
sudo pvs && sudo vgs && sudo lvs

# Проверка активных процессов, использующих LV
sudo lsof /dev/mapper/vg_data-lv_app
sudo fuser -vm /dev/mapper/vg_data-lv_app

# Проверка journal для ошибок LVM
sudo journalctl -k | grep -i "device-mapper\|lvm\|dm-"

# Просмотр метаданных VG
sudo vgcfgrestore --list vg_data

# Проверка целостности PV
sudo pvck /dev/sdb1

# Проверка целостности VG
sudo vgck vg_data

# Просмотр атрибутов с расшифровкой
sudo lvdisplay /dev/vg_data/lv_app
```

### См. также
- **[LVM — Управление томами](../management_operations.md)** — общие операции и мониторинг.
- **[LVM — Замена диска](./lvm_disk_replacement.md)** — детальный разбор pvmove и замены носителей.
- **[LVM — Практические сценарии восстановления](../advanced_topics/practical_scenarios.md)** — восстановление PV, удалённых LV, тонких пулов.
