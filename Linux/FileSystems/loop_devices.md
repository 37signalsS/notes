# Loop Devices

## Определения

**Loop device** — псевдоустройство в Linux, связывающее обычный файл с виртуальным блочным устройством `/dev/loopX`. Позволяет работать с файлом-образом как с физическим диском: форматировать, монтировать, шифровать.

**losetup** — утилита для управления ассоциациями между файлами и loop-устройствами.

## Основные концепции

### Принцип работы

Ядро транслирует все операции чтения/записи к `/dev/loopX` в соответствующие операции с привязанным файлом-образом. Драйвер loop-устройств находится в пространстве ядра, что обеспечивает прозрачность: приложения не отличают loop-устройство от физического блочного устройства.

### Автоматическое и ручное назначение

- **Автоматическое:** `mount -o loop file.img /mnt` — ядро само находит свободный `/dev/loopX` и привязывает файл
- **Ручное:** `losetup /dev/loop0 file.img` — явное управление, позволяет задать параметры (offset, sizelimit) перед монтированием

## Практические сценарии

### Управление loop-устройствами через losetup

```bash
# Привязать файл к loop-устройству
sudo losetup /dev/loop0 /opt/disk.img

# Проверить все активные ассоциации
losetup -a

# Получить подробную информацию о конкретном устройстве
losetup /dev/loop0

# Отсоединить устройство
sudo losetup -d /dev/loop0
```

### Монтирование ISO-образа

```bash
# Автоматический режим (ядро само создаёт loop-устройство)
sudo mount -o loop /path/to/image.iso /mnt/iso

# Ручной режим с проверкой
sudo losetup -f --show /path/to/image.iso  # -f: первый свободный, --show: вывести имя
# Вывод: /dev/loop0
sudo mount /dev/loop0 /mnt/iso
```

### Создание и монтирование виртуального диска

```bash
# Создать файл-образ 1 ГБ
fallocate -l 1G /opt/disk.img

# Форматировать в ext4
mkfs.ext4 /opt/disk.img

# Смонтировать
sudo mount -o loop /opt/disk.img /mnt/virtual_disk
```

### Монтирование с offset (образы с разделами)

Когда файл-образ содержит таблицу разделов (например, образ SD-карты Raspberry Pi), монтирование требует указания смещения:

```bash
# Посмотреть таблицу разделов образа
fdisk -l /opt/rpi_image.img

# Вывод:
# Device             Boot  Start    End Sectors  Size Id Type
# rpi_image.img1         8192  53247   45056   22M  c W95 FAT32
# rpi_image.img2        53248 623359  570112  278M 83 Linux

# Размер сектора: 512 байт. Offset для второго раздела: 53248 * 512 = 27262976
sudo mount -o loop,offset=27262976 /opt/rpi_image.img /mnt/rpi_root
```

Альтернативный подход через losetup с partition scan:

```bash
sudo losetup -P -f --show /opt/rpi_image.img  # -P: сканировать разделы
# Создаёт /dev/loop0, /dev/loop0p1, /dev/loop0p2
sudo mount /dev/loop0p2 /mnt/rpi_root
```

### Шифрование образа через LUKS

Loop-устройства часто используются для зашифрованных файлов-контейнеров:

```bash
# 1. Привязать файл к loop-устройству
sudo losetup /dev/loop0 /opt/secret.img

# 2. Инициализировать LUKS
sudo cryptsetup luksFormat /dev/loop0

# 3. Открыть контейнер
sudo cryptsetup open /dev/loop0 vault

# 4. Создать ФС и смонтировать
sudo mkfs.ext4 /dev/mapper/vault
sudo mount /dev/mapper/vault /mnt/secure

# 5. Закрыть (в обратном порядке)
sudo umount /mnt/secure
sudo cryptsetup close vault
sudo losetup -d /dev/loop0
```

Подробное описание LUKS — [storage_overview.md](./storage_overview.md#шифрование-диска-с-помощью-luks).

## Дополнительная информация

Типы устройств — [device_types.md](./device_types.md) | Создание образов — [dd.md](./dd.md) | Виртуальные ФС — [virtual_filesystems.md](./virtual_filesystems.md) | Шифрование LUKS — [storage_overview.md](./storage_overview.md#шифрование-диска-с-помощью-luks) | Монтирование — [mounting/index.md](./mounting/index.md)
