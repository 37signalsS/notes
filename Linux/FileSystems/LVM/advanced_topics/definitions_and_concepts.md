# LVM: Расширенные темы — Определения и концепции

## Определения

**LVM и загрузка** — взаимодействие LVM с процессом загрузки Linux, ограничения размещения `/boot`, инициализация LVM через `initramfs`.

**LVM и файловые системы** — совместное использование LVM и ФС, особенности изменения размеров, перечитывание таблицы разделов.

> **Примечание:** Базовые концепции загрузки с LVM, ограничения `/boot`, взаимодействие с ФС и `partprobe` описаны в [advanced_topics.md](./advanced_topics.md#lvm-и-процесс-загрузки-linux).

---

## Базовые концепции

См. [advanced_topics.md](./advanced_topics.md#lvm-и-процесс-загрузки-linux) — загрузка с LVM, ограничение `/boot`, взаимодействие с ФС, `partprobe`.

---

## Практические сценарии

### Troubleshooting загрузки с LVM

#### Проблема: «Volume group not found» после рестарта

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

## Дополнительная информация

### Связанные файлы

- [Определения и концепции LVM](../overview_concepts.md)
- [Базовые концепции: загрузка, ФС](./advanced_topics.md)
- [Операции с пространством, swap, восстановление](./practical_scenarios.md)
