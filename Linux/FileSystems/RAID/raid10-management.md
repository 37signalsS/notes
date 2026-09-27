# Управление RAID 10

## Определения

**RAID 10 (1+0, Stripe of Mirrors)** — комбинация RAID 1 (зеркалирование) и RAID 0 (чередование). Диски объединяются в зеркальные пары, которые затем чередуются для максимальной производительности чтения и записи.

**Write Penalty = 2** — при каждой операции записи выполняются 2 физические операции ввода-вывода (по одной на каждое зеркало в паре). Это значительно меньше, чем в RAID 5/6.

**Near/Offset/Far layout** — способы размещения зеркальных копий относительно друг друга. `near` (по умолчанию) размещает копии на соседних позициях stripe, `far` — на удалённых, обеспечивая лучшую балансировку чтения.

---

## Основные концепции

### Технические характеристики

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Мин. дисков** | 4 (чётное число) | Минимум для двух зеркальных пар. |
| **Отказоустойчивость** | 1 диск в каждой паре | Минимум 1 диск, tối đa N/2 дисков (по одному в паре). |
| **Штраф на запись** | 2 операции I/O | Запись на оба зеркала в паре. |
| **Полезная ёмкость** | 50% | Половина общего объёма дисков. |
| **Chunk Size** | 512 КБ | По умолчанию в `mdadm`. |
| **Метаданные** | 1.2 (по умолчанию) | Суперблок в начале диска. |

### Когда выбирать RAID 10

| Сценарий | RAID 5 | RAID 6 | RAID 10 | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| OLTP база данных (высокий IOPS) | Write Penalty | Write Penalty | Минимум задержек | **RAID 10** |
| Виртуализация (mixed I/O) | Средне | Средне | Предсказуемо | **RAID 10** |
| Write-heavy нагрузка (>40% записи) | Плохо | Очень плохо | Хорошо | **RAID 10** |
| Файловый сервер (чтение) | Хорошо | Хорошо | Хорошо | Любой |
| Хранилище на HDD 16+ ТБ | Опасно | Рекомендуется | Дорого | RAID 6 |

### Производительность: чтение и запись

#### Write Penalty (Штраф на запись)

```
1. Запись данных на диск A (зеркало 1)   → 1 I/O
2. Запись зеркальной копии на диск B      → 1 I/O
                                         ─────────
Итого: 2 физических I/O на 1 логическую операцию
```

**Формула эффективных IOPS:**

$$Effective IOPS = \frac{Raw IOPS \times N}{Read\% + (Write\% \times Penalty)}$$

*Пример:* 8 SSD (10 000 IOPS каждый) при нагрузке 70% чтение / 30% запись:
$80,000 / (0.7 + (0.3 \times 2)) = 80,000 / 1.3 = 61,538$ IOPS.

**Вывод:** RAID 10 обеспечивает максимальную производительность записи среди всех уровней RAID.

#### Пропускная способность

| Уровень RAID | Чтение (N дисков) | Запись (N дисков) |
| :--- | :--- | :--- |
| RAID 10 | N × S | (N/2) × S |

*Где S — пропускная способность одного диска.*

**Пример:** RAID 10 из 8 SATA SSD (550 МБ/с):
- Чтение: 8 × 550 = 4400 МБ/с
- Запись: 4 × 550 = 2200 МБ/с

### Поведение в деградированном состоянии

| Состояние | Дисков потеряно | Производительность | Избыточность |
| :--- | :--- | :--- | :--- |
| **Норма** | 0 | 100% | Двойная (зеркала) |
| **Degraded (1 пара)** | 1 | ~80-90% | Одинарная (в этой паре) |
| **Degraded (2+ пары)** | 2+ | ~50-70% | Нет в повреждённых парах |
| **Failed** | 2 в одной паре | Массив потерян | — |

**Важно:** RAID 10 восстанавливается значительно быстрее RAID 5/6, так как ребилд копирует только данные одного диска, а не пересчитывает чётность по всем.

**Оценка времени ребилда RAID 10:**

```
T_rebuild ≈ Размер_диска / Скорость_чтения
Пример: RAID 10, диск 4 ТБ, SATA HDD (200 МБ/с)
4 ТБ / 200 МБ/с ≈ 20 000 секунд ≈ 5.6 часов
```

### Совместимость дисков

В отличие от RAID 5/6, RAID 10 **допускает** использование дисков разного объёма (как RAID 1):
- Фактический размер зеркала определяется самым маленьким диском в паре.
- Рекомендуется использовать диски одинакового объёма и модели.

---

## Практические сценарии

### Предварительные требования

**Оборудование:**
- Минимум 4 диска (чётное число для симметричных пар)
- Для максимальной отказоустойчивости — количество дисков кратно 2

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
# Создание RAID 10 (4 диска, 2 зеркальные пары)
sudo mdadm --create --verbose /dev/md0 --level=10 --raid-devices=4 \
    /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1

# Создание RAID 10 (6 дисков, 3 зеркальные пары)
sudo mdadm --create --verbose /dev/md0 --level=10 --raid-devices=6 \
    /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1 /dev/sdf1 /dev/sdg1

# Проверка
cat /proc/mdstat
# → md0 : active raid10 sdg1[5] sdf1[4] sde1[3] sdd1[2] sdc1[1] sdb1[0]
#       2930270208 blocks super 1.2 near-copies [6/6] [UUUUUU]
```

#### 3. Форматирование и монтирование

```bash
# Создание файловой системы (ext4 для БД)
sudo mkfs.ext4 -L "raid10_data" /dev/md0

# Создание файловой системы (XFS для файлового сервера)
sudo mkfs.xfs -L "raid10_data" /dev/md0

# Монтирование
sudo mkdir -p /mnt/raid10
sudo mount /dev/md0 /mnt/raid10

# Добавление в fstab
echo '/dev/md0 /mnt/raid10 ext4 defaults,noatime 0 2' | sudo tee -a /etc/fstab
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

Для RAID 10 stripe width = chunk size (так как данные дублируются в паре):

```bash
# Пример создания ext4 с выравниванием
sudo mkfs.ext4 -b 4096 -E stride=128,stripe-width=128 /dev/md0
# stride = Chunk / Block size = 512/4 = 128
# stripe-width = stride (для RAID 10 = 1 stripe unit)
```

#### Scrubbing (Проверка целостности)

```bash
# Запуск проверки
echo check | sudo tee /sys/block/md0/md/sync_action

# Проверка ошибок
cat /sys/block/md0/md/mismatch_cnt

# Исправление (перезапись с одного зеркала на другое)
echo repair | sudo tee /sys/block/md0/md/sync_action
```

> **Внимание:** В RAID 10 команда `repair` перезаписывает данные с одного диска зеркала на другой. Всегда анализируйте `mismatch_cnt` перед запуском.

---

### Добавление Hot Spare

```bash
# Добавление горячего резерва
sudo mdadm /dev/md0 --add /dev/sdh1

# Проверка
cat /proc/mdstat
# → md0 : active raid10 sdh1[6](S) sdg1[5] sdf1[4] sde1[3] sdd1[2] sdc1[1] sdb1[0]
```

---

### Изменение конфигурации (Reshape)

#### Увеличение числа зеркальных пар

```bash
# 1. Добавить новые диски как spare
sudo mdadm /dev/md0 --add /dev/sdi1
sudo mdadm /dev/md0 --add /dev/sdj1

# 2. Увеличить число активных устройств
sudo mdadm --grow /dev/md0 --raid-devices=6

# 3. Мониторинг
watch cat /proc/mdstat

# 4. Расширение ФС
sudo resize2fs /dev/md0
```

---

### LVM поверх RAID 10

```bash
# 1. Создание RAID 10
sudo mdadm --create /dev/md0 --level=10 --raid-devices=4 \
    /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1

# 2. Создание PV
sudo pvcreate /dev/md0

# 3. Создание VG
sudo vgcreate vg_raid10 /dev/md0

# 4. Создание LV
sudo lvcreate -n lv_db -L 200G vg_raid10

# 5. Форматирование и монтирование
sudo mkfs.xfs /dev/vg_raid10/lv_db
sudo mkdir -p /mnt/db
sudo mount /dev/vg_raid10/lv_db /mnt/db
```

---

## Обработка сбоев и восстановление

### Стандартная замена диска

```bash
# 1. Проверка состояния
cat /proc/mdstat
# → md0 : active raid10 sdg1[5] sdf1[4] sde1[3] sdd1[2] _dc1[1] sdb1[0]
#       [UUU_UU]

# 2. Пометить как сбойный
sudo mdadm /dev/md0 --fail /dev/sdc1

# 3. Удалить из массива
sudo mdadm /dev/md0 --remove /dev/sdc1

# 4. Физическая замена диска (hot-plug или выключение)

# 5. Очистка нового диска
sudo wipefs --all /dev/sdc1
sudo mdadm --zero-superblock /dev/sdc1

# 6. Добавление нового диска
sudo mdadm /dev/md0 --add /dev/sdc1

# 7. Мониторинг восстановления
watch -n 1 cat /proc/mdstat
```

### Миграция RAID 1 → RAID 10

```bash
# Исходное состояние: RAID 1 из 2 дисков
# Требуется: добавить 2 диска для RAID 10

# 1. Добавить новые диски
sudo mdadm /dev/md0 --add /dev/sdd1
sudo mdadm /dev/md0 --add /dev/sde1

# 2. Изменить уровень и количество устройств
sudo mdadm --grow /dev/md0 --level=10 --raid-devices=4

# 3. Мониторинг
watch cat /proc/mdstat
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
*   Для максимальной отказоустойчивости — диски разных производителей, купленных в разное время
*   Enterprise-grade SSD/HDD для серверных нагрузок

### Конфигурация
*   Используйте `--bitmap=internal` для ускорения rebuild
*   Сохраняйте `mdadm.conf` и обновляйте `initramfs` после каждого изменения
*   Для OLTP БД: chunk size 64K-128K (оптимально для мелких транзакций)

### Мониторинг
*   Регулярный scrubbing (не реже 1 раза в месяц)
*   Мониторинг SMART для каждого диска в массиве
*   Настраивайте уведомления через `mdmonitor` или внешние системы

### Безопасность
*   Не используйте RAID 10 как замену бэкапу — он не защищает от логических ошибок
*   Регулярно тестируйте восстановление из бэкапа

---

## Edge Cases

### Диски разного объёма
RAID 10 допускает диски разного размера, но фактический объём зеркала определяется самым маленьким диском в паре. Для расширения:
1. Замените оба диска в паре на одинаковые большего объёма
2. Выполните `sudo mdadm --grow /dev/md0 --size=max`
3. Расширьте ФС: `sudo resize2fs /dev/md0`

### Сбой обоих зеркал одновременно
Крайне редкая ситуация. RAID 10 не защищает от этого — требуется бэкап.

### Массив на SSD
*   Включите TRIM: `echo 'options md_mod start_ro=0' | sudo tee /etc/modprobe.d/md.conf`
*   Мониторьте износ через SMART
*   В RAID 10 SSD изнашиваются одинаково — заменяйте комплектом

### Near vs Far layout
*   **Near (по умолчанию):** Зеркальные копии на соседних позициях. Лучше для последовательных записей.
*   **Far:** Зеркальные копии на удалённых позициях. Лучше для случайного чтения, но медленнее запись.

```bash
# Указание layout при создании
sudo mdadm --create /dev/md0 --level=10 --layout=far --raid-devices=4 \
    /dev/sdb1 /dev/sdc1 /dev/sdd1 /dev/sde1
```

---

## Дополнительная информация

* [Обзор RAID и mdadm](./overview.md) — архитектура и базовые команды.
* [Уровни RAID](./raid-levels.md) — детальное сравнение производительности и рисков.
* [Мониторинг RAID-массивов](./monitoring.md) — настройка уведомлений и анализ логов.
* [Влияние RAID на I/O](../../Diagnostics/Performance/DiskIO/raid_io_impact.md) — Write Penalty, Stripe Size, BBU.
* [RAID и резервное копирование](./raid-vs-backup.md) — фундаментальные различия.
