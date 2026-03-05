# Управление программным RAID (mdadm)

## Структура документации

| Файл | Описание |
| :--- | :--- |
| [RAID/overview.md](./RAID/overview.md) | Введение в RAID и mdadm, типы реализации |
| [RAID/raid-levels.md](./RAID/raid-levels.md) | Уровни RAID, рекомендации по выбору |
| [RAID/raid1-management.md](./RAID/raid1-management.md) | Создание и управление RAID 1 |
| [RAID/raid5-management.md](./RAID/raid5-management.md) | Создание и управление RAID 5  (устарел) |
| [RAID/monitoring.md](./RAID/monitoring.md) | Мониторинг состояния, уведомления |
| [RAID/raid-removal.md](./RAID/raid-removal.md) | Удаление RAID-массивов |
| [RAID/raid-vs-backup.md](./RAID/raid-vs-backup.md) | Отличие RAID от резервного копирования |

## Быстрый старт

### Создание RAID 1 (зеркало)

```bash
# 1. Подготовка разделов
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary 0% 100%
sudo parted /dev/sdb set 1 raid on
# Повторить для /dev/sdc

# 2. Создание массива
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sdb1 /dev/sdc1

# 3. Сохранение конфигурации
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u

# 4. Создание ФС и монтирование
sudo mkfs.ext4 /dev/md0
sudo mkdir -p /mnt/raid1
sudo mount /dev/md0 /mnt/raid1
```

### Мониторинг

```bash
# Быстрая проверка
cat /proc/mdstat

# Детальная информация
sudo mdadm --detail /dev/md0
```

### Замена сбойного диска

```bash
# 1. Определение сбойного диска
cat /proc/mdstat  # искать [_U] вместо [UU]

# 2. Пометка и удаление
sudo mdadm /dev/md0 --fail /dev/sdb1
sudo mdadm /dev/md0 --remove /dev/sdb1

# 3. Добавление нового диска
sudo mdadm /dev/md0 --add /dev/sdd1
# Начнётся rebuild, мониторинг: watch cat /proc/mdstat
```

## Ключевые рекомендации

| Сценарий | Рекомендуемый RAID |
| :--- | :--- |
| Загрузочный диск (`/boot`, `/`) | **RAID 1** |
| СУБД (OLTP, write-intensive) | **RAID 10** |
| Файловый сервер (4-6 дисков) | **RAID 6** |
| Домашний сервер (2 диска) | **RAID 1** |
| Бэкапы (write-once) | **RAID 6** |

> **RAID 5 устарел** для дисков >1ТБ. Используйте RAID 6 или RAID 10.

## Связанные темы

* [Диагностика дисков (SMART)](../Diagnostics/Hardware/smartctl.md)
* [LVM поверх RAID](../LVM/overview_concepts.md)
* [Настройка fstab](../mounting/fstab.md)
* [Загрузка и initramfs](../Core/kernel/boot_process.md)
* [Резервное копирование БД](../../Databases/Concepts/backups.md)
* [Восстановление таблиц разделов](./partition_tables_recovery.md) — MBR, GPT
* [Восстановление данных](./data_recovery.md) — логическое восстановление
