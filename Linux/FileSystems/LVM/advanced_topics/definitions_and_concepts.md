# LVM: Расширенные темы — Определения и концепции

## LVM и процесс загрузки Linux

### Загрузка с LVM

Если корневая файловая система (`/`) находится на LVM-томе, для загрузки используется `initramfs` (initial RAM file system).

**Процесс загрузки:**

1. **BIOS/UEFI** → загрузчик (GRUB)
2. **GRUB** → загружает ядро + `initramfs`
3. **initramfs** → содержит утилиты LVM (`lvm`, `pvscan`, `vgscan`, `lvscan`)
4. **Активация LVM** → `vgchange -ay` активирует VG и LV
5. **Монтирование корня** → ядро монтирует корневую ФС с LV
6. **Продолжение загрузки** → переход к `/sbin/init`

### Ограничение: `/boot` на LVM

**Важно:** Каталог `/boot` **не должен** находиться на LVM.

**Причина:**

- GRUB должен прочитать ядро и `initramfs` **до** активации LVM
- Загрузчик не имеет доступа к утилитам LVM
- Исключение: GRUB2 с поддержкой LVM (не рекомендуется для production)

**Рекомендуемая схема:**

| Раздел | Размер | Тип | Описание |
| :--- | :--- | :--- | :--- |
| `/dev/sda1` | 512 МБ – 1 ГБ | ext4/xfs | `/boot` (обычный раздел) |
| `/dev/sda2` | Остальное место | LVM PV | Все остальные разделы через LVM |

**Альтернатива:** Использовать шифрованный `/boot` с GRUB2 (требует дополнительной настройки).

---

## LVM и файловые системы

### Взаимодействие LVM и ФС

LVM управляет блочными устройствами, но **не отменяет ограничений файловых систем**.

### Точность размеров

**Проблема:** Утилиты LVM и ФС могут по-разному интерпретировать единицы:

| Единица | LVM | Файловые системы |
| :--- | :--- | :--- |
| `GB` | 10^9 (1 000 000 000 байт) | 10^9 |
| `GiB` | 2^30 (1 073 741 824 байт) | 2^30 |

**Рекомендация при уменьшении:**

1. Сначала сжимайте ФС до размера **меньшего**, чем целевой размер LV
2. Затем уменьшайте LV
3. Затем расширяйте ФС до максимального размера LV

### partprobe и перечитывание таблицы разделов

**Проблема:** После изменения таблицы разделов (`fdisk`, `parted`) ядро может не увидеть изменения без перезагрузки.

**Решение:**

```bash
# Перечитать таблицу разделов
sudo partprobe /dev/sdb

# Проверить
lsblk
```

**Если `partprobe` не работает:**

- Размонтируйте все разделы на диске
- Используйте `partx -u /dev/sdb`
- В крайнем случае — перезагрузка

---

## Troubleshooting: Проблемы загрузки с LVM

### Проблема: «Volume group not found» после рестарта

**Симптомы:**
- Система не загружается, initramfs выдаёт ошибку `Volume group not found`
- Drop to initramfs shell или emergency mode
- VG не активируется автоматически при загрузке

**Причина:** Модуль `lvm2` не включён в initramfs или конфигурация LVM не обновлена после изменений.

**Решение:**

#### 1. Временное решение (загрузка с LiveCD/USB)

```bash
# Смонтировать корневую ФС
mount /dev/mapper/vg-root /mnt
mount --bind /proc /mnt/proc
mount --bind /sys /mnt/sys
mount --bind /dev /mnt/dev
chroot /mnt

# Проверить и активировать VG
vgscan
vgchange -ay

# Пересобрать initramfs (см. ниже)
```

#### 2. Включение lvm2 в initramfs

**Debian/Ubuntu:**
```bash
# Добавить модуль lvm2 в конфигурацию
echo "lvm2" >> /etc/initramfs-tools/modules

# Проверить наличие hook
ls /etc/initramfs-tools/hooks/lvm2

# Пересобрать initramfs
update-initramfs -u -k $(uname -r)

# Обновить загрузчик
update-grub
```

**RHEL/CentOS/Fedora:**
```bash
# Проверить наличие lvm2 в dracut
dracut --list-modules | grep lvm

# Добавить lvm в конфигурацию
echo 'add_dracutmodules+=" lvm "' >> /etc/dracut.conf.d/lvm.conf

# Пересобрать initramfs
dracut --force --regenerate-all
```

**Arch Linux:**
```bash
# Добавить lvm2 в mkinitcpio.conf
# /etc/mkinitcpio.conf
HOOKS=(base udev autodetect microcode modconf block lvm2 filesystems)

# Пересобрать initramfs
mkinitcpio -P
```

#### 3. Проверка после сборки

```bash
# Убедиться, что lvm2 попал в initrd
lsinitcpio /boot/initramfs-*.img | grep lvm    # Arch
lsinitrd /boot/initramfs-*.img | grep lvm      # RHEL/CentOS

# Проверить активацию VG
vgscan
vgchange -ay
```

### Профилактика

- Всегда выполнять `update-initramfs -u` после изменений в LVM (vgrename, vgextend, pvmove)
- Регулярно проверять содержимое initramfs на наличие lvm-утилит
- Тестировать загрузку после изменений в конфигурации хранилища

---

## Ссылки

- [Практические сценарии](./practical_scenarios.md) — операции с пространством, swap, восстановление
- [Дополнительная информация](./advanced_topics.md) — диагностика, troubleshooting
