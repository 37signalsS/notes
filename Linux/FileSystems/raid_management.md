# Управление программным RAID (mdadm)

## Определения

### mdadm

**`mdadm` (Multiple Devices Admin)** — стандартная утилита Linux для создания и управления программными RAID-массивами через модуль ядра **MD (Multiple Devices)**. Позволяет создавать массивы уровней 0/1/4/5/6/10, выполнять горячую замену дисков, расширение и мониторинг.

Подробное введение в RAID, сравнение типов реализации (программный/аппаратный/FakeRAID) и уровни RAID — в **[Введение в RAID и mdadm](./RAID/overview.md)** (SSoT).

## Основные концепции

### Архитектура программного RAID

Программный RAID в Linux работает через модуль ядра `md`. Массивы видны как блочные устройства `/dev/mdX` и `/proc/mdstat`. Конфигурация сохраняется в `/etc/mdadm/mdadm.conf` и включается в `initramfs` для ранней сборки при загрузке.

### Метаданные (superblock)

`mdadm` хранит метаданные массива на каждом диске. Версии метаданных:

| Версия | Формат | Расположение | Когда использовать |
| :--- | :--- | :--- | :--- |
| `0.90` | Устаревший | Конец устройства | Загрузочные разделы (`/boot`), совместимость со старыми загрузчиками |
| `1.0` | Новый | Конец устройства | Когда нужен доступ к ФС до сборки массива |
| `1.1` | Новый | Начало устройства | По умолчанию для данных |
| `1.2` | Новый | Смещение 4К от начала | По умолчанию для `mdadm --create` |

### Конфигурация и загрузка

После создания массива необходимо:

1. Сохранить конфигурацию в `mdadm.conf`
2. Обновить `initramfs` для сборки массива на ранней стадии загрузки

```bash
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```

## Практические сценарии

### Создание RAID 1 (зеркало)

```bash
# Подготовка разделов
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary 0% 100%
sudo parted /dev/sdb set 1 raid on
# Повторить для /dev/sdc

# Создание массива
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sdb1 /dev/sdc1

# Создание ФС и монтирование
sudo mkfs.ext4 /dev/md0
sudo mkdir -p /mnt/raid1
sudo mount /dev/md0 /mnt/raid1
```

Подробное руководство по RAID 1: **[RAID 1 Management](./RAID/raid1-management.md)**.

### Мониторинг состояния

```bash
# Быстрая проверка
cat /proc/mdstat

# Детальная информация
sudo mdadm --detail /dev/md0
```

Полное руководство по мониторингу и уведомлениям: **[RAID Monitoring](./RAID/monitoring.md)**.

### Замена сбойного диска

```bash
# Пометка и удаление
sudo mdadm /dev/md0 --fail /dev/sdb1
sudo mdadm /dev/md0 --remove /dev/sdb1

# Добавление нового диска
sudo mdadm /dev/md0 --add /dev/sdd1
```

Процесс rebuilding отслеживается через `watch cat /proc/mdstat`.

### Рекомендации по выбору уровня RAID

| Сценарий | Рекомендуемый RAID |
| :--- | :--- |
| Загрузочный диск (`/boot`, `/`) | **RAID 1** |
| СУБД (OLTP, write-intensive) | **RAID 10** |
| Файловый сервер (4–6 дисков) | **RAID 6** |
| Домашний сервер (2 диска) | **RAID 1** |
| Бэкапы (write-once) | **RAID 6** |

> **RAID 5 устарел** для дисков >1 ТБ из-за риска URE при rebuild. Используйте RAID 6 или RAID 10.

Подробный разбор уровней — в **[RAID Levels](./RAID/raid-levels.md)**.

## Дополнительная информация

Удаление массивов: **[RAID Removal](./RAID/raid-removal.md)**. Отличие RAID от резервного копирования: **[RAID vs Backup](./RAID/raid-vs-backup.md)**.

Смежные темы: диагностика дисков [SMART](../Diagnostics/Hardware/smartctl/index.md), [LVM поверх RAID](./LVM/overview_concepts.md), [fstab для RAID](mounting/fstab.md), [загрузка и initramfs](../Core/kernel/boot_process.md), [восстановление таблиц разделов](./partition_tables_recovery.md), [восстановление данных](./data_recovery.md).
