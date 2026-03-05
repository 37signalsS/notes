# Управление RAID 1 (зеркалирование)

## Определения

**RAID 1** — уровень RAID с зеркалированием данных между двумя или более дисками. Обеспечивает отказоустойчивость к сбою одного диска (при 2 дисках) или нескольких (при большем числе зеркал).

## Основные концепции

### Подходы к созданию

| Подход | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Разделы диска** | RAID создаётся на разделах с флагом `raid` | Гибкость, возможность иметь другие разделы на диске |
| **Целые диски** | RAID создаётся напрямую на дисках `/dev/sdX` | Простота, диски выделяются целиком под RAID |

> **Рекомендация:** Для загрузочных массивов — разделы. Для файловых хранилищ — целые диски.

## Практические сценарии

### Создание RAID 1

#### Подготовка дисков

**Способ 1: Разделы диска (рекомендуется)**

```bash
# Создание раздела на /dev/sdb
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary 0% 100%
sudo parted /dev/sdb set 1 raid on

# Повторить для /dev/sdc
sudo parted /dev/sdc mklabel gpt
sudo parted /dev/sdc mkpart primary 0% 100%
sudo parted /dev/sdc set 1 raid on
```

**Способ 2: Целые диски**

```bash
# Пропустить создание разделов, использовать /dev/sdb и /dev/sdc напрямую
```

#### Очистка старых метаданных

```bash
# Проверка наличия старых метаданных
sudo mdadm --examine /dev/sdb1    # для разделов
sudo mdadm --examine /dev/sdb     # для целых дисков

# Очистка (ВНИМАНИЕ: удаляет все данные!)
sudo wipefs --all /dev/sdb1       # удалить все signatures
sudo mdadm --zero-superblock /dev/sdb1  # удалить только RAID-метаданные
```

> **`wipefs` vs `--zero-superblock`:** `wipefs --all` удаляет все подписи (ФС, LVM, RAID). `--zero-superblock` удаляет только метаданные RAID. Для новой сборки используйте оба: сначала `wipefs`, потом `--zero-superblock`.

#### Создание массива

```bash
# Из разделов
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/sdb1 /dev/sdc1

# Из целых дисков (потребуется подтверждение)
sudo mdadm --create --verbose /dev/md0 --level=1 --raid-devices=2 /dev/sdb /dev/sdc
```

> **Метаданные и загрузка:** По умолчанию используется версия метаданных 1.2, которая не всегда поддерживается GRUB для `/boot`. Для загрузочного раздела укажите `--metadata=1.0`:
>
> ```bash
> sudo mdadm --create /dev/md0 --level=1 --metadata=1.0 --raid-devices=2 /dev/sdb1 /dev/sdc1
> ```

#### Сохранение конфигурации

```bash
# Сохранение в mdadm.conf
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf

# Обновление initramfs (чтобы ядро видело массив при загрузке)
sudo update-initramfs -u   # Debian/Ubuntu
# или
sudo dracut --force        # RHEL/CentOS
```

#### Создание ФС и монтирование

```bash
# Создание файловой системы
sudo mkfs.ext4 /dev/md0

# Монтирование
sudo mkdir -p /mnt/raid1
sudo mount /dev/md0 /mnt/raid1

# Добавление в /etc/fstab (по UUID)
UUID=$(sudo blkid -s UUID -o value /dev/md0)
echo "UUID=$UUID /mnt/raid1 ext4 defaults 0 0" | sudo tee -a /etc/fstab

# Проверка
sudo mount -a
df -h /mnt/raid1
```

Подробнее: [Настройка fstab](../mounting/fstab.md)

---

### Мониторинг и управление сбоями

#### Определение сбойного диска

```bash
# Быстрая проверка
cat /proc/mdstat

# Детальный статус
sudo mdadm --detail /dev/md0

# Поиск failed-дисков
sudo mdadm --detail /dev/md0 | grep -E "failed|faulty"
```

#### Горячая замена диска (hot spare)

```bash
# 1. Пометка диска как сбойного (если не произошло автоматически)
sudo mdadm /dev/md0 --fail /dev/sdb1

# 2. Удаление сбойного диска
sudo mdadm /dev/md0 --remove /dev/sdb1

# 3. Добавление нового диска (начнётся rebuild)
sudo mdadm /dev/md0 --add /dev/sdd1
```

**Мониторинг rebuild:**

```bash
watch cat /proc/mdstat
# или
sudo mdadm --detail /dev/md0 | grep -E "Rebuild|Resync"
```

#### Холодная замена (после перезагрузки)

Если система загрузилась в degraded-режиме:

```bash
# 1. Остановка массива
sudo mdadm --stop /dev/md0

# 2. Принудительная сборка с рабочим диском
sudo mdadm --assemble --run /dev/md0 /dev/sdc1

# 3. Добавление нового диска
sudo mdadm /dev/md0 --add /dev/sdd1

# 4. Проверка
cat /proc/mdstat
```

#### Добавление зеркала (расширение)

```bash
# Добавление третьего зеркала к существующему RAID 1
sudo mdadm /dev/md0 --add /dev/sde1

# Изменение количества устройств (если требуется)
sudo mdadm --grow /dev/md0 --raid-devices=3
```

> **Важно:** RAID 1 с 3+ дисками даёт повышенную отказоустойчивость, но полезная ёмкость остаётся равной ёмкости одного диска.

---

### Удаление RAID 1

См. полную инструкцию: [Удаление RAID-массива](./raid-removal.md)

```bash
# 1. Размонтирование
sudo umount /dev/md0

# 2. Удаление из fstab
sudo nano /etc/fstab  # удалить строку с /dev/md0

# 3. Остановка массива
sudo mdadm --stop /dev/md0

# 4. Очистка метаданных
sudo mdadm --zero-superblock /dev/sdb1
sudo mdadm --zero-superblock /dev/sdc1

# 5. Удаление из mdadm.conf
sudo nano /etc/mdadm/mdadm.conf  # удалить строку с ARRAY

# 6. Обновление initramfs
sudo update-initramfs -u
```

## Дополнительная информация

* [Мониторинг RAID](./monitoring.md)
* [Уровни RAID](./raid-levels.md#raid-1---зеркалирование-mirroring)
* [Удаление RAID](./raid-removal.md)
* [Настройка fstab](../mounting/fstab.md)
* [initramfs и загрузка](../../Core/kernel/boot_process.md#initramfs)
