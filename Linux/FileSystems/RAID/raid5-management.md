# Управление RAID 5

## Определения

> **RAID 5 устарел** для дисков >1ТБ из-за риска URE при rebuild. Используйте RAID 6 или RAID 10 для новых систем.

**RAID 5** — уровень RAID с чередованием и распределённой чётностью. Требует минимум 3 диска, выдерживает сбой одного диска.

## Основные концепции

### Особенности RAID 5

| Параметр | Значение |
| :--- | :--- |
| Мин. дисков | 3 |
| Отказоустойчивость | 1 диск |
| Полезная ёмкость | (N-1) × размер_минимального_диска |
| Штраф на запись | 4 операции (read-modify-write) |

> **Риск URE:** Для дисков 2ТБ+ вероятность Unrecoverable Read Error при rebuild достигает 40%. Время rebuild 8ТБ диска = 12-24 часа.

## Практические сценарии

### Создание RAID 5

```bash
# Создание массива из 3 дисков
sudo mdadm --create --verbose /dev/md0 --level=5 --raid-devices=3 /dev/vdb /dev/vdc /dev/vdd

# Сохранение конфигурации
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```

Шаги создания аналогичны [созданию RAID 1](./raid1-management.md).

---

### Управление сбоями

#### Имитация сбоя (тестирование)

```bash
# Пометка диска как сбойного
sudo mdadm /dev/md0 --fail /dev/vdb

# Проверка статуса
cat /proc/mdstat
sudo mdadm --detail /dev/md0
```

#### Замена сбойного диска

```bash
# 1. Удаление сбойного диска
sudo mdadm /dev/md0 --remove /dev/vdb

# 2. Добавление нового диска (начнётся rebuild)
sudo mdadm /dev/md0 --add /dev/vde

# 3. Мониторинг восстановления
watch cat /proc/mdstat
```

---

### Расширение массива (Grow)

RAID 5 поддерживает добавление дисков "на лету" с перераспределением данных (reshape).

#### Шаг 1: Добавление диска как spare

```bash
sudo mdadm /dev/md0 --add /dev/vdb
```

#### Шаг 2: Запуск reshape

```bash
# Увеличение количества рабочих дисков с 3 до 4
sudo mdadm --grow /dev/md0 --raid-devices=4
```

**Мониторинг reshape:**

```bash
watch cat /proc/mdstat
# или
sudo mdadm --detail /dev/md0 | grep -E "reshape|Progress"
```

> **Время reshape:** Для массива 4×4ТБ может занять 6-12 часов. Производительность массива во время reshape снижена.

#### Шаг 3: Расширение файловой системы

После завершения reshape:

```bash
# Проверка нового размера
lsblk /dev/md0

# Расширение ext4
sudo resize2fs /dev/md0

# Для XFS
sudo xfs_growfs /mnt/raid5
```

#### Шаг 4: Обновление конфигурации

```bash
sudo mdadm --detail --scan | sudo tee /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```

---

### Изменение других параметров

#### Изменение размера chunk

```bash
# Только для неактивного массива!
sudo mdadm --stop /dev/md0
sudo mdadm --grow /dev/md0 --chunk=256
sudo mdadm --assemble /dev/md0
```

#### Добавление spare-диска

```bash
# Добавление горячего резерва (автоматическая замена при сбое)
sudo mdadm /dev/md0 --add /dev/vdf
```

---

### Конвертация RAID 5 → RAID 6

```bash
# Добавление диска и конвертация (требуется 4+ диска)
sudo mdadm --grow /dev/md0 --level=6 --raid-devices=4

# Мониторинг конвертации
watch cat /proc/mdstat
```

> **Рекомендация:** При расширении массива более 4 дисков **обязательно** конвертируйте в RAID 6.

## Дополнительная информация

См. также: [мониторинг RAID](./monitoring.md), [уровни RAID](./raid-levels.md#raid-5---чередование-с-распределённой-чётностью), [расширение RAID 1](./raid1-management.md#добавление-зеркала-расширение), [рекомендации по RAID 6](./raid-levels.md#raid-6---чередование-с-двойной-чётностью).
