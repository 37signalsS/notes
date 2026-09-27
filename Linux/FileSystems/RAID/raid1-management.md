# Управление RAID 1 (Зеркалирование)

## Определения

**RAID 1 (Redundant Array of Independent Disks Level 1)** — технология объединения накопителей, при которой данные идентично записываются на два или более диска. Основная цель — обеспечение высокой доступности данных (избыточность).

**Зеркалирование (Mirroring)** — синхронная запись блоков данных на все физические устройства массива. При чтении RAID 1 позволяет параллельно считывать разные блоки с разных дисков, что может повысить скорость случайного чтения (Random Read).

**Write Penalty = 2** — при каждой операции записи ОС выполняет две физические операции ввода-вывода (по одной на каждое зеркало). Это ключевое ограничение RAID 1: производительность записи не превышает скорость самого медленного диска в массиве.

**Degraded Mode (Деградированное состояние)** — режим работы массива, при котором один или несколько дисков недоступны. RAID 1 продолжает работать, обслуживая запросы через оставшееся зеркало, но без избыточности. Любая последующая потеря диска приведёт к полной потере данных.

---

## Основные концепции

### Метаданные и загрузка системы
Для разделов, участвующих в процессе загрузки (особенно `/boot`), критически важен выбор версии метаданных.
*   **Метаданные 1.0:** Суперблок располагается в конце раздела. Это позволяет BIOS/UEFI и загрузчику GRUB считывать данные напрямую, как с обычного раздела, еще до инициализации драйвера `md`.
*   **Метаданные 1.2:** Суперблок располагается в начале диска (смещение 4 КБ). Стандарт по умолчанию для современных систем. Не подходит для `/boot`, так как загрузчик не сможет прочитать данные до инициализации `md`.
*   **Отказоустойчивость загрузчика:** Массив защищает данные, но не загрузчик. GRUB должен быть установлен в MBR/ESP каждого диска-участника массива вручную. См. раздел [Установка GRUB на оба диска](#установка-grub-на-оба-диска).

### Write-intent Bitmap (Битовая карта записи)
Механизм, отслеживающий «грязные» (несинхронизированные) блоки.
*   **Зачем:** После сбоя питания (Dirty Shutdown) массив не будет пересинхронизироваться полностью (Full Resync), а обновит только измененные блоки, что в десятки раз ускоряет восстановление.
*   **Типы:** Может быть внутренней (встроена в метаданные) или внешней (отдельный файл на другом диске).
*   **Рекомендация:** Включайте `bitmap=internal` при создании массива — стоимость минимальна, а выигрыш при восстановлении значителен.

### Целостность данных и Bit rot
RAID 1 защищает от отказа диска, но не гарантирует целостность данных при «тихой порче» (Bit rot).
*   **Проблема:** Если блок на одном диске поврежден, RAID может вернуть неверные данные, так как у него нет механизма проверки контрольных сумм. При ресинхронизации повреждённые данные могут быть скопированы на здоровое зеркало.
*   **Решение:** Использование ZFS или Btrfs поверх RAID 1, которые умеют исправлять ошибки на лету за счёт встроенных контрольных сумм (checksums) на каждом блоке.

### Производительность: чтение и запись

#### Запись
Производительность записи в RAID 1 ограничена скоростью самого медленного диска. Write Penalty = 2 означает удвоение количества операций ввода-вывода:

| Параметр | Значение |
| :--- | :--- |
| Write Penalty | 2 (каждая запись идёт на оба диска) |
| Максимальная скорость записи | min(S₁, S₂), где S — скорость записи диска |
| Влияние разницы скоростей | Массив работает на скорости самого медленного диска |

**Практическое следствие:** Использование дисков с существенной разницей в скорости записи (например, SSD + HDD) приводит к тому, что быстрый диск не раскрывает свой потенциал.

#### Чтение
RAID 1 позволяет читать данные параллельно с обоих дисков, что увеличивает пропускную способность случайного чтения:

| Параметр | Значение |
| :--- | :--- |
| Параллельное чтение | Да (максимум N × S для N дисков) |
| Random Read | Линейно растёт с количеством дисков |
| Sequential Read | Теоретически N × S, практически ~1.5–1.8×S (из-за задержек планирования) |

**Оптимизация:** Для рабочих нагрузок с преобладанием случайного чтения (базы данных, веб-серверы) RAID 1 даёт заметный прирост производительности. Для последовательного чтения выигрыш менее выражен.

### Поведение в деградированном состоянии

При отказе одного диска RAID 1 работает через оставшееся зеркало без потери данных, но с ограничениями:

1. **Производительность:** Чтение и запись идут через один диск, пропускная способность падает вдвое.
2. **Отсутствие избыточности:** Любая следующая ошибка диска — полная потеря данных.
3. **Нагрузка при восстановлении:** Во время rebuild剩余的диск испытывает повышенную нагрузку на чтение, что может замедлить работу приложений.

**Оценка времени ребилда RAID 1:**

```
T_rebuild ≈ Размер_массива / Скорость_чтения_оставшегося_диска
Пример: 4 ТБ массив на SATA HDD (200 МБ/с)
4 ТБ / 200 МБ/с ≈ 20 000 секунд ≈ 5.6 часов
```

> **Важно:** Время ребилда пропорционально размеру массива. Для дисков 16+ ТБ процесс может занимать 12–24 часа. Использование Write-intent Bitmap сокращает время на 50–90% при сбоях питания (синхронизируются только изменённые блоки).

### Совместимость дисков в RAID 1

В отличие от RAID 5/6, RAID 1 допускает использование дисков разного объёма:

*   **Фактический размер зеркала:** Определяется самым маленьким диском в массиве. Если диск 4 ТБ зеркалируется с диском 2 ТБ, доступно только 2 ТБ.
*   **Рекомендация:** Используйте диски одинакового объёма и модели. Это упрощает обслуживание и исключает путаницу при мониторинге.
*   **Замена дисков:** При замене диска на больший объём массив автоматически использует только размер старого диска. Для расширения необходимо выполнить `mdadm --grow --size=max` после замены обоих дисков.

---

## Практические сценарии

### Предварительные требования

**Оборудование:**
- Минимум 2 диска (или раздела) одинакового или большего объёма
- Для загрузочного RAID 1: оба диска должны быть доступны BIOS/UEFI при старте
- Рекомендуется резервный диск (Hot Spare) для автоматического восстановления

**Программное обеспечение:**
```bash
# Установка mdadm (Debian/Ubuntu)
sudo apt update && sudo apt install mdadm

# Установка mdadm (RHEL/CentOS/Fedora)
sudo dnf install mdadm

# Проверка версии
mdadm --version
# → mdadm - v4.2 - 2023-...
```

**Начальное состояние:**
```bash
# Проверка что диски доступны
lsblk
# → NAME   SIZE TYPE MOUNTPOINTS
#   sdb    500G disk
#   sdc    500G disk

# Проверка что на дисках нет активных файловых систем
sudo blkid /dev/sdb /dev/sdc
```

---

### Создание RAID 1

#### 1. Подготовка накопителей
Рекомендуется использовать GPT-разделы с небольшим отступом в конце диска (100–500 МБ) для компенсации разницы в объеме дисков разных вендоров.

```bash
# Создание GPT-разметки
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdc mklabel gpt

# Создание разделов типа 'Linux raid'
sudo parted /dev/sdb mkpart primary 1M 100%
sudo parted /dev/sdb set 1 raid on

sudo parted /dev/sdc mkpart primary 1M 100%
sudo parted /dev/sdc set 1 raid on

# Проверка
sudo parted /dev/sdb print
# → Number  Start   End     Size    Type     Flags
#   1       1049kB  500GB   500GB   primary  raid
```

#### 2. Очистка и проверка
```bash
# Удаление старых подписей (ФС, LVM, RAID)
sudo wipefs --all /dev/sdb1 /dev/sdc1

# Очистка суперблока RAID (если был ранее)
sudo mdadm --zero-superblock /dev/sdb1 /dev/sdc1

# Проверка что диски чисты
sudo blkid /dev/sdb1 /dev/sdc1
# → (пустой вывод)
```

#### 3. Создание массива
```bash
# Обычный массив с внутренним Bitmap
sudo mdadm --create --verbose /dev/md0 --level=1 --bitmap=internal --raid-devices=2 /dev/sdb1 /dev/sdc1

# Массив для /boot (Metadata 1.0)
sudo mdadm --create /dev/md0 --level=1 --metadata=1.0 --raid-devices=2 /dev/sdb1 /dev/sdc1

# Проверка
cat /proc/mdstat
# → md0 : active raid1 sdc1[1] sdb1[0]
#       524287744 blocks super 1.2 [2/2] [UU]
#       [>..........]  recovery = 3.2% (8402944/262143872) finish=10.5min speed=412480K/sec
```

#### 4. Форматирование и монтирование
```bash
# Создание файловой системы (ext4)
sudo mkfs.ext4 -L "raid1_data" /dev/md0

# Создание файловой системы (XFS)
sudo mkfs.xfs -L "raid1_data" /dev/md0

# Монтирование
sudo mkdir -p /mnt/raid1
sudo mount /dev/md0 /mnt/raid1

# Добавление в fstab для автозагрузки
echo '/dev/md0 /mnt/raid1 ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
```

#### 5. Установка GRUB на оба диска

Критически важно для загрузочного RAID 1 — GRUB должен быть установлен на MBR/ESP обоих дисков:

```bash
# Установка GRUB на первый диск
sudo grub-install /dev/sdb
# → Installing for i386-pc platform.
# → Installation finished. No error reported.

# Установка GRUB на второй диск
sudo grub-install /dev/sdc
# → Installing for i386-pc platform.
# → Installation finished. No error reported.

# Обновление конфигурации GRUB
sudo update-grub
# → Generating grub configuration file ...
#   Found linux image: /boot/vmlinuz-...
#   Found initrd image: /boot/initrd.img-...
```

#### 6. Финализация конфигурации
```bash
# Добавление в mdadm.conf
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf

# Обновление initramfs
sudo update-initramfs -u

# Проверка что массив определится при следующей загрузке
sudo mdadm --detail --scan
# → ARRAY /dev/md0 level=raid1 num-devices=2 metadata=1.2 UUID=...
```

---

### Работа с файловой системой

#### Выравнивание (Alignment)
Для оптимальной производительности файловая система должна быть выровнена по границе stripe:

```bash
# RAID 1: Stripe Width = размер блока (1 диск)
# Для ext4: stride = chunk_size / block_size
# По умолчанию chunk = 512K, block = 4K → stride = 128

# Пример создания ext4 с выравниванием
sudo mkfs.ext4 -b 4096 -E stride=128,stripe-width=128 /dev/md0

# Проверка выравнивания после создания
sudo dumpe2fs -h /dev/md0 | grep -i "stride\|stripe"
```

#### Scrubbing (Проверка целостности)
Регулярная проверка выявляет расхождения между зеркалами:

```bash
# Запуск проверки
echo check | sudo tee /sys/block/md0/md/sync_action

# Мониторинг прогресса
watch cat /proc/mdstat

# Проверка результатов
cat /sys/block/md0/md/mismatch_cnt
# → 0 (массив консистентен)

# Исправление обнаруженных расхождений
echo repair | sudo tee /sys/block/md0/md/sync_action
```

> **Внимание:** В RAID 1 команда `repair` перезаписывает данные с одного диска на другой. Если причина расхождения — аппаратная ошибка чтения, `repair` может перезаписать верные данные неверными. Всегда анализируйте `mismatch_cnt` перед запуском `repair`.

---

### Добавление Hot Spare (Горячий резерв)
Резервный диск, который автоматически заменит вышедший из строя.

```bash
# Добавление горячего резерва
sudo mdadm /dev/md0 --add /dev/sdd1

# Проверка
cat /proc/mdstat
# → md0 : active raid1 sdd1[2](S) sdc1[1] sdb1[0]
#       524287744 blocks super 1.2 [2/2] [UU]
```

**Поведение при отказе диска:**
1. Сбойный диск автоматически помечается как failed
2. Spare начинает rebuild без вмешательства администратора
3. Время восстановления — от нескольких минут до часов

---

### Увеличение количества зеркал (Reshape)
Превращение RAID 1 из двух дисков в трехстороннее зеркало.

```bash
# 1. Добавить новый диск как spare
sudo mdadm /dev/md0 --add /dev/sde1

# 2. Увеличить число активных устройств
sudo mdadm --grow /dev/md0 --raid-devices=3

# 3. Мониторинг
watch cat /proc/mdstat
# → md0 : active raid1 sde1[2] sdc1[1] sdb1[0]
#       resync=DONE [3/3] [UUU]
```

---

### Увеличение объема массива (Grow)
При замене всех дисков на более емкие:

1. Замените диски по одному, дожидаясь ресинхронизации каждого.
2. Расширьте массив: `sudo mdadm --grow /dev/md0 --size=max`.
3. Расширьте ФС: `sudo resize2fs /dev/md0` (ext4) или `sudo xfs_growfs /mnt/raid`.

```bash
# Проверка текущего размера
sudo mdadm --detail /dev/md0 | grep "Array Size"

# Расширение на максимум (после замены дисков)
sudo mdadm --grow /dev/md0 --size=max

# Расширение ФС (ext4)
sudo resize2fs /dev/md0

# Расширение ФС (XFS)
sudo xfs_growfs /mnt/raid1
```

---

### Миграция в RAID 5
Если требуется увеличить объем без потери избыточности:

```bash
# Требуется минимум 3 диска (2 из RAID 1 + 1 новый)
sudo mdadm --grow /dev/md0 --level=5 --raid-devices=3 --add /dev/sdf1
```

> **Важно:** Миграция RAID 1 → RAID 5 — длительный процесс (часы-сутки). Массив работает в degraded state до завершения. Перед миграцией убедитесь в наличии актуального бэкапа.

---

### LVM поверх RAID 1

Для гибкого управления томами можно разместить LVM поверх RAID 1:

```bash
# 1. Создание RAID 1
sudo mdadm --create /dev/md0 --level=1 --bitmap=internal \
    --raid-devices=2 /dev/sdb1 /dev/sdc1

# 2. Создание Physical Volume (PV)
sudo pvcreate /dev/md0
# → Physical volume "/dev/md0" successfully created.

# 3. Создание Volume Group (VG)
sudo vgcreate vg_raid1 /dev/md0
# → Volume group "vg_raid1" successfully created

# 4. Создание Logical Volume (LV)
sudo lvcreate -n lv_data -L 200G vg_raid1
# → Logical volume "lv_data" created.

# 5. Форматирование и монтирование
sudo mkfs.ext4 /dev/vg_raid1/lv_data
sudo mkdir -p /mnt/data
sudo mount /dev/vg_raid1/lv_data /mnt/data

# 6. Проверка
sudo lvs
# → LV     VG       Attr       LSize   Pool Origin Data%  Meta%
#   lv_data vg_raid1 -wi-a----- 200.00g
```

**Преимущества LVM поверх RAID 1:**
- Онлайн-расширение томов без остановки сервисов
- Снапшоты для бэкапов и отката
- Тонкое выделение (Thin Provisioning) при необходимости

---

## Обработка сбоев и восстановление

### 1. Диагностика

Метка `[_U]` или `[U_]` в `/proc/mdstat` указывает на деградацию.

```bash
# Быстрая проверка
cat /proc/mdstat
# → md0 : active raid1 sdc1[1]
#       524287744 blocks super 1.2 [1/1] [_U]

# Детальный просмотр
sudo mdadm --detail /dev/md0
# → /dev/md0
#           Version : 1.2
#     Creation Time : ...
#        Raid Level : raid1
#        Array Size : 524287744 (500.00 GiB 536.87 GB)
#     Used Dev Size : 524287744 (500.00 GiB 536.87 GB)
#      Raid Devices : 2
#     Total Devices : 2
#       Persistence : Superblock is persistent
#       State : active, degraded
#      Active Devices : 1
#     Working Devices : 1
#      Failed Devices : 0
#       Spare Devices : 0
#              Name : ...
#                UUID : ...
#              Events : 12345

# Просмотр суперблока на физическом диске
sudo mdadm --examine /dev/sdb1
# → /dev/sdb1
#           Magic : ...
#         Version : 1.2
#    Feature Map : 0x1
#    Array UUID : ...
#        Name : ...
#   Creation Time : ...
#      Raid Level : raid1
#   Raid Devices : 2
#   Avail Dev Size : 524287744 (500.00 GiB 536.87 GB)
#       Array Size : 524287744 (500.00 GiB 536.87 GB)
#    Bitmap Offset : 32K
#       New Offset : 2048K
#   State : active
#   Active Devices : 1
#   Working Devices : 1
#   Failed Devices : 0
#       Spare Devices : 0
#      Sync Speed : 412480 (sec/sec)
#       Reshape Pos : 0
#   Chunk Size : 512K
#      New Chunk : 512K
#         Events : 12345
#       Resync Status : 23% complete
```

### 2. Замена диска

```bash
# Пометить как сбойный (если не определился автоматически)
sudo mdadm /dev/md0 --fail /dev/sdb1
# → mdadm: set /dev/sdb1 faulty in /dev/md0

# Удалить из массива
sudo mdadm /dev/md0 --remove /dev/sdb1
# → mdadm: hot removed /dev/sdb1 from /dev/md0

# Физическая замена диска (hot-plug или выключение)

# Очистка нового диска
sudo wipefs --all /dev/sdb1
sudo mdadm --zero-superblock /dev/sdb1

# Добавление нового диска
sudo mdadm /dev/md0 --add /dev/sdb1
# → mdadm: added /dev/sdb1

# Мониторинг ресинхронизации
watch -n 1 cat /proc/mdstat
# → md0 : active raid1 sdb1[2] sdc1[1]
#       524287744 blocks super 1.2 [2/2] [UU]
#       [>..........]  recovery = 3.2% finish=10.5min speed=412480K/sec
```

### 3. Мониторинг ресинхронизации

```bash
# Прогресс восстановления
watch cat /proc/mdstat

# Скорость восстановления (КБ/с)
cat /proc/sys/dev/raid/speed_limit_min
cat /proc/sys/dev/raid/speed_limit_max

# Увеличение скорости (временно)
echo 500000 | sudo tee /proc/sys/dev/raid/speed_limit_max

# Проверка bitmap
sudo mdadm --examine /dev/sdc1 | grep bitmap
# → bitmap : 1/10 pages [32KB], 65536KB [2048 chunks]
```

---

## Диагностика и решение проблем

### Массив не собирается автоматически при загрузке

**Причина:** Отсутствует запись в `mdadm.conf` или `initramfs` не содержит информацию о массиве.

```bash
# Проверка mdadm.conf
cat /etc/mdadm/mdadm.conf | grep md0

# Если отсутствует — добавить
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf

# Обновить initramfs
sudo update-initramfs -u

# Проверка что массив определяется
sudo mdadm --assemble --scan
```

### Массив получил другое имя (md127 вместо md0)

**Причина:** Отсутствует `mdadm.conf` или UUID не совпадают.

```bash
# Найти массив
cat /proc/mdstat

# Собрать по UUID
sudo mdadm --assemble /dev/md0 --uuid=<UUID_массива>

# Или собрать по компонентам
sudo mdadm --assemble /dev/md0 /dev/sdb1 /dev/sdc1

# Сохранить конфигурацию
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```

### Reshape завершился с ошибкой

**Причина:** Недостаточно места, сбой питания или аппаратная ошибка.

```bash
# Проверка текущего состояния reshape
cat /proc/mdstat
# → md0 : active raid1 sde1[2] sdc1[1] sdb1[0]
#       524287744 blocks super 1.2 [3/3] [UUU]
#       [=====>........]  reshape = 25.3% finish=20min speed=412480K/sec

# Если reshape прерван — возобновление
sudo mdadm --grow /dev/md0 --raid-devices=3

# Если reshape невозможен — восстановление из метаданных
sudo mdadm --examine /dev/sdb1 | grep "Array State"
```

### Конфликт метаданных при сборке

**Причина:** Разные версии mdadm или different data-offset.

```bash
# Определение data-offset
sudo mdadm --examine /dev/sdb1 | grep "Data Offset"
# → Data Offset : 2048 sectors

# Указание offset при создании массива
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 \
    --data-offset=1024K /dev/sdb1 /dev/sdc1
```

### Массив деградирован, но работает нормально

Это штатное состояние. RAID 1 продолжает обслуживать запросы через оставшееся зеркало.

```bash
# Проверка что массив доступен
df -h /mnt/raid1
# → /dev/md0  500G  120G  360G  25% /mnt/raid1

# Проверка что нет ошибок в логах
dmesg | grep -i "md0\|error\|fault"
```

**Рекомендация:** Запланируйте замену диска в ближайшее время. Массив работает без избыточности — любая следующая ошибка диска приведёт к потере данных.

---

## Лучшие практики

### Выбор дисков
*   Используйте диски одинакового объёма, модели и производителя
*   Избегайте дисков из одной партии — время наработки на отказ у них близко
*   Для критичных систем — диски разных производителей, купленных в разное время
*   Enterprise-grade SSD/HDD для серверных нагрузок

### Конфигурация
*   Включайте `bitmap=internal` при создании массива
*   Используйте `metadata=1.0` для `/boot`, `metadata=1.2` для данных
*   Настраивайте Hot Spare для автоматического восстановления
*   Сохраняйте `mdadm.conf` и обновляйте `initramfs` после каждого изменения

### Мониторинг
*   Регулярный scrubbing (не реже 1 раза в месяц)
*   Мониторинг SMART для каждого диска в массиве
*   Настраивайте уведомления через `mdmonitor` или внешние системы
*   Контролируйте `mismatch_cnt` после scrubbing

### Безопасность
*   Не используйте RAID 1 как замену бэкапу — он не защищает от логических ошибок
*   Регулярно тестируйте восстановление из бэкапа
*   Храните копии критичных данных на независимых носителях

---

## Edge Cases

### Диски разного объёма
RAID 1 автоматически использует размер самого маленького диска. Для расширения:
1. Замените оба диска на одинаковые большего объёма
2. Выполните `sudo mdadm --grow /dev/md0 --size=max`
3. Расширьте ФС: `sudo resize2fs /dev/md0`

### Сбой обоих зеркал одновременно
Крайне редкая, но возможная ситуация (одинаковое время наработки, одинаковые условия эксплуатации). RAID 1 не защищает от этого — требуется бэкап.

### Конвертация RAID 1 → RAID 0
Потеря избыточности без добавления дисков. Опасна — используйте только для временных данных:
```bash
sudo mdadm --grow /dev/md0 --level=0
```

### Конвертация RAID 1 → RAID 5
Требует добавления минимум одного диска. Позволяет увеличить полезный объём:
```bash
# RAID 1 (2 диска) + 1 новый диск → RAID 5 (3 диска)
sudo mdadm /dev/md0 --add /dev/sdf1
sudo mdadm --grow /dev/md0 --level=5 --raid-devices=3
```

### Массив на SSD
*   Включите TRIM: `echo 'options md_mod start_ro=0' | sudo tee /etc/modprobe.d/md.conf`
*   Мониторьте износ через SMART: `smartctl -a /dev/sdX | grep "Percentage_Used"`
*   Wear Leveling: в RAID 1 SSD изнашиваются одинаково — заменяйте комплектом

---

## Дополнительная информация

* [Обзор RAID и mdadm](./overview.md) — архитектура и базовые команды.
* [Мониторинг RAID-массивов](./monitoring.md) — настройка уведомлений и анализ логов.
* [Удаление RAID-массива](./raid-removal.md) — безопасный демонтаж массива.
* [Уровни RAID](./raid-levels.md) — сравнение характеристик и рисков URE.
