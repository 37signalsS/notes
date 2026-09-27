# Управление RAID 6

## Определения

**RAID 6 (Redundant Array of Independent Disks Level 6)** — уровень дискового массива, использующий чередование данных (Striping) с двумя независимыми блоками чётности (P и Q). Выдерживает одновременный выход из строя двух любых дисков без потери данных.

**Двойная чётность (Dual Parity)** — два блока чётности, вычисляемые разными алгоритмами: P — классический XOR (аналог RAID 5), Q — на основе кодов Рида-Соломона (GF operations). Это позволяет восстановить данные при потере любых двух дисков.

**Write Penalty = 6** — при каждой операции записи выполняются 6 физических операций ввода-вывода: чтение данных, чтение чётности P, чтение чётности Q, запись данных, запись чётности P, запись чётности Q.

**Rebuild (Ресинхронизация)** — процесс восстановления данных на новом диске после замены вышедшего из строя накопителя. В RAID 6 данные восстанавливаются вычислением XOR по оставшимся блокам в каждой stripe.

---

## Основные концепции

### Технические характеристики

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Мин. дисков** | 4 | Минимум для реализации двух схем чётности. |
| **Отказоустойчивость** | 2 диска | Выход из строя трёх дисков приводит к потере массива. |
| **Штраф на запись** | 6 операций I/O | Read Data, Read Parity P, Read Parity Q, Write Data, Write Parity P, Write Parity Q. |
| **Полезная ёмкость** | (N-2) / N | Например, в массиве из 6 дисков по 10 ТБ доступно 40 ТБ. |
| **Chunk Size** | 512 КБ | По умолчанию в `mdadm`. Влияет на распределение блоков. |
| **Метаданные** | 1.2 (по умолчанию) | Суперблок в начале диска (4 КБ от начала). |

### Когда выбирать RAID 6

| Сценарий | RAID 5 | RAID 6 | Рекомендация |
| :--- | :--- | :--- | :--- |
| Диски < 8 ТБ, < 6 штук | Допустимо | Избыточно | RAID 5 |
| Диски 8–16 ТБ | Опасно (URE) | Рекомендуется | **RAID 6** |
| Диски > 16 ТБ | Категорически нет | Обязательно | **RAID 6** |
| 12+ дисков в массиве | Нет | Да | **RAID 6** |
| Критичные данные (без бэкапа в моменте) | Нет | Да | **RAID 6** |

### Производительность: чтение и запись

#### Write Penalty (Штраф на запись)

Каждая операция записи в RAID 6 выполняет 6 физических операций ввода-вывода:

| Операция | Описание |
| :--- | :--- |
| Read Data | Чтение старого блока данных (для вычисления новой чётности) |
| Read Parity P | Чтение старого блока чётности P (XOR) |
| Read Parity Q | Чтение старого блока чётности Q (Reed-Solomon) |
| Write Data | Запись нового блока данных |
| Write Parity P | Запись нового блока чётности P |
| Write Parity Q | Запись нового блока чётности Q |

**Формула эффективных IOPS:**

$$Effective IOPS = \frac{Raw IOPS \times N}{Read\% + (Write\% \times Penalty)}$$

*Пример:* 6 HDD (150 IOPS каждый) при нагрузке 70% чтение / 30% запись:
$900 / (0.7 + (0.3 \times 6)) = 900 / 2.5 = 360$ IOPS.

**Вывод:** RAID 6 хорош для нагрузок с высокой долей чтения (>80%) или для массивов, где безопасность важнее производительности записи.

#### Пропускная способность

| Уровень RAID | Чтение (N дисков) | Запись (N дисков) |
| :--- | :--- | :--- |
| RAID 6 | (N-2) × S | (N-2) × S / 6 |

*Где S — пропускная способность одного диска.*

**Пример:** RAID 6 из 8 SATA HDD (200 МБ/с):
- Чтение: 6 × 200 = 1200 МБ/с (теоретически)
- Запись: 6 × 200 / 6 = 200 МБ/с (теоретически)

### Поведение в деградированном состоянии

При отказе одного или двух дисков RAID 6 продолжает работать:

| Состояние | Дисков потеряно | Производительность | Избыточность |
| :--- | :--- | :--- | :--- |
| **Норма** | 0 | 100% | Двойная |
| **Degraded (1 диск)** | 1 | ~60-70% от нормы | Одинарная |
| **Degraded (2 диска)** | 2 | ~30-50% от нормы | Нет |
| **Failed** | 3+ | Массив потерян | — |

**Важно:** При двух потерянных дисках каждый запрос чтения требует XOR по оставшимся (N-2) дискам. Это создаёт экстремальную нагрузку на дисковую подсистему и CPU.

**Оценка времени ребилда RAID 6:**

```
T_rebuild ≈ Размер_массива / (Скорость_чтения × (N-2))
Пример: RAID 6 из 8 HDD по 10 ТБ (200 МБ/с)
60 ТБ / (200 МБ/с × 6) ≈ 50 000 секунд ≈ 14 часов
```

### Совместимость дисков

Как и RAID 5, RAID 6 **не допускает** использование дисков разного объёма:
- Фактический размер массива определяется самым маленьким диском.
- Используйте диски одинакового объёма, модели и производителя.
- При замене дисков на более емкие — `mdadm --grow --size=max` после замены всех дисков.

---

## Практические сценарии

### Предварительные требования

**Оборудование:**
- Минимум 4 диска (или раздела) одинакового объёма
- Рекомендуется Hot Spare для автоматического восстановления

**Программное обеспечение:**
```bash
# Установка mdadm (Debian/Ubuntu)
sudo apt update && sudo apt install mdadm

# Установка mdadm (RHEL/CentOS/Fedora)
sudo dnf install mdadm
```

---

### Создание массива

#### 1. Подготовка накопителей

```bash
# Создание GPT-разметки
for disk in /dev/sd{b,c,d,e}; do
    sudo parted $disk mklabel gpt
    sudo parted $disk mkpart primary 1M 100%
    sudo parted $disk set 1 raid on
done

# Очистка
for disk in /dev/sd{b,c,d,e}1; do
    sudo wipefs --all $disk
    sudo mdadm --zero-superblock $disk
done
```

#### 2. Создание массива

```bash
# Создание RAID 6 с PPL (Partial Parity Log) — рекомендуется
sudo mdadm --create --verbose /dev/md0 --level=6 --raid-devices=4 \
    --consistency-policy=ppl /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1

# Создание RAID 6 с Write-intent Bitmap
sudo mdadm --create --verbose /dev/md0 --level=6 --bitmap=internal \
    --raid-devices=4 /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1

# Проверка
cat /proc/mdstat
# → md0 : active raid6 sde1[3] sdd1[2] sdc1[1] sdb1[0]
#       14651351040 blocks super 1.2 level 6, 512k chunk, algorithm 2 [4/4] [UUUU]
```

> **Примечание:** `--consistency-policy=ppl` и `--bitmap=internal` не рекомендуется использовать одновременно.

#### 3. Форматирование и монтирование

```bash
# Создание файловой системы (ext4)
sudo mkfs.ext4 -L "raid6_data" /dev/md0

# Создание файловой системы (XFS)
sudo mkfs.xfs -L "raid6_data" /dev/md0

# Монтирование
sudo mkdir -p /mnt/raid6
sudo mount /dev/md0 /mnt/raid6

# Добавление в fstab
echo '/dev/md0 /mnt/raid6 ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
```

#### 4. Финализация конфигурации

```bash
# Добавление в mdadm.conf
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf

# Обновление initramfs
sudo update-initramfs -u
```

---

### Работа с файловой системой

#### Выравнивание (Alignment)

*   **Stripe Width** = `Chunk Size` × `(N - 2)`.
*   Пример: 6 дисков, Chunk 512K. Stripe Width = 512K × 4 = 2048K.

```bash
# Пример создания ext4 с выравниванием
sudo mkfs.ext4 -b 4096 -E stride=128,stripe-width=512 /dev/md0
# stride = Chunk / Block size = 512/4 = 128
# stripe-width = stride * (N-2) = 128 * 4 = 512
```

#### Scrubbing (Проверка целостности)

```bash
# Запуск проверки
echo check | sudo tee /sys/block/md0/md/sync_action

# Проверка ошибок
cat /sys/block/md0/md/mismatch_cnt
# → 0 (массив консистентен)

# Исправление (после анализа)
echo repair | sudo tee /sys/block/md0/md/sync_action
```

---

### Добавление Hot Spare

```bash
# Добавление горячего резерва
sudo mdadm /dev/md0 --add /dev/sdf1

# Проверка
cat /proc/mdstat
# → md0 : active raid6 sdf1[4](S) sde1[3] sdd1[2] sdc1[1] sdb1[0]
```

---

### Изменение конфигурации (Reshape)

#### Добавление диска и расширение

```bash
# 1. Добавить диск
sudo mdadm /dev/md0 --add /dev/sdg1

# 2. Расширить массив
sudo mdadm --grow /dev/md0 --raid-devices=5

# 3. Мониторинг
watch cat /proc/mdstat

# 4. Расширение ФС
sudo resize2fs /dev/md0
```

---

### LVM поверх RAID 6

```bash
# 1. Создание RAID 6
sudo mdadm --create /dev/md0 --level=6 --consistency-policy=ppl \
    --raid-devices=4 /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1

# 2. Создание PV
sudo pvcreate /dev/md0

# 3. Создание VG
sudo vgcreate vg_raid6 /dev/md0

# 4. Создание LV
sudo lvcreate -n lv_data -L 500G vg_raid6

# 5. Форматирование и монтирование
sudo mkfs.ext4 /dev/vg_raid6/lv_data
sudo mkdir -p /mnt/data
sudo mount /dev/vg_raid6/lv_data /mnt/data
```

---

## Обработка сбоев и восстановление

### Стандартная замена диска

```bash
# 1. Проверка состояния
cat /proc/mdstat
# → md0 : active raid6 sde1[3] sdd1[2] sdc1[1] _sb1[0]
#       [UU_U]

# 2. Пометить как сбойный
sudo mdadm /dev/md0 --fail /dev/sdb1

# 3. Удалить из массива
sudo mdadm /dev/md0 --remove /dev/sdb1

# 4. Добавить новый диск
sudo mdadm /dev/md0 --add /dev/sdb1

# 5. Мониторинг восстановления
watch -n 1 cat /proc/mdstat
```

### Аварийное восстановление при потере 2 дисков

Если вышло из строя **два диска** и данные с них невозможно считать, массив потерян. Если данные можно считать частично:

```bash
# 1. Создание образов дисков (ddrescue)
ddrescue -d -r3 /dev/sdb /mnt/recovery/disk1.img /mnt/recovery/disk1.log
ddrescue -d -r3 /dev/sdc /mnt/recovery/disk2.img /mnt/recovery/disk2.log

# 2. Сборка массива из образов
sudo mdadm --create --verbose /dev/md0 --level=6 --raid-devices=6 \
    /mnt/recovery/disk1.img /mnt/recovery/disk2.img missing missing /dev/sdd1 /dev/sde1
```

### mismatch_cnt > 0 после scrubbing

```bash
# Проверка SMART для всех дисков
for disk in /dev/sd{b,c,d,e}; do
    echo "=== $disk ==="
    sudo smartctl -H $disk
    sudo smartctl -A $disk | grep -E "Reallocated|Current_Pending|Offline_Uncorrectable"
done

# Если SMART в порядке — запуск repair
echo repair | sudo tee /sys/block/md0/md/sync_action
```

---

## Диагностика и решение проблем

### Массив не собирается автоматически при загрузке

```bash
# Проверка mdadm.conf
cat /etc/mdadm/mdadm.conf | grep md0

# Добавление информации о массиве
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf

# Обновление initramfs
sudo update-initramfs -u
```

### Массив получил другое имя (md127 вместо md0)

```bash
# Сборка по UUID
sudo mdadm --assemble /dev/md0 --uuid=<UUID_массива>

# Сохранение конфигурации
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```

---

## Лучшие практики

### Выбор дисков
*   Используйте диски одинакового объёма, модели и производителя
*   Избегайте дисков из одной партии
*   Для критичных систем — диски разных производителей, купленных в разное время

### Конфигурация
*   Используйте `--consistency-policy=ppl` для защиты от Write Hole
*   Включайте `--bitmap=internal` для ускорения rebuild
*   Сохраняйте `mdadm.conf` и обновляйте `initramfs` после каждого изменения

### Мониторинг
*   Регулярный scrubbing (не реже 1 раза в месяц)
*   Мониторинг SMART для каждого диска в массиве
*   Настраивайте уведомления через `mdmonitor` или внешние системы

---

## Edge Cases

### Диски разного объёма
RAID 6 автоматически использует размер самого маленького диска. Для расширения:
1. Замените все диски на одинаковые большего объёма
2. Выполните `sudo mdadm --grow /dev/md0 --size=max`
3. Расширьте ФС: `sudo resize2fs /dev/md0`

### Массив на SSD
*   Включите TRIM: `echo 'options md_mod start_ro=0' | sudo tee /etc/modprobe.d/md.conf`
*   Мониторьте износ через SMART
*   Write Penalty на SSD менее заметна для латентности, но критична для TBW
*   Рассмотрите RAID 10 для SSD — лучшая производительность записи

### RAID 60 (6+0)
Объединяет несколько групп RAID 6 в общий RAID 0:
- Отказоустойчивость: отказ двух дисков в каждой подгруппе
- Применение: сверхбольшие массивы (24+ дисков)

```bash
# Пример: два RAID 6 по 4 диска, объединённых в RAID 0
sudo mdadm --create /dev/md0 --level=6 --raid-devices=4 /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1
sudo mdadm --create /dev/md1 --level=6 --raid-devices=4 /dev/sdf1 /dev/sdg1 /dev/sdh1 /dev/sdi1
sudo mdadm --create /dev/md10 --level=0 --raid-devices=2 /dev/md0 /dev/md1
```

---

## Дополнительная информация

* [Обзор RAID и mdadm](./overview.md) — архитектура и базовые команды.
* [Уровни RAID](./raid-levels.md) — детальное сравнение производительности и рисков.
* [Мониторинг RAID-массивов](./monitoring.md) — настройка уведомлений и анализ логов.
* [Влияние RAID на I/O](../../Diagnostics/Performance/DiskIO/raid_io_impact.md) — Write Penalty, Stripe Size, BBU.
* [Управление RAID 5](./raid5-management.md) — сравнение с RAID 6.
