# Загрузчик GRUB

## Определения

### GRUB (Grand Unified Bootloader)

**GRUB** — загрузчик операционной системы, работающий до загрузки ОС. Обладает собственными минимальными драйверами для работы с железом, обращаясь к BIOS или напрямую к оборудованию. Предоставляет интерфейс для выбора ОС, версии ядра и позволяет редактировать параметры загрузки (клавиша `E`).

### Этапы загрузки GRUB (Legacy BIOS)

1. **Stage 1**: Загрузка кода из MBR (446 байт). Из-за малого размера содержит только указатель на следующий этап.
2. **Stage 1.5** (опционально): Загружается из первых 62 секторов диска. Содержит драйверы файловых систем для доступа к `/boot/grub/`. Требовался для старого железа с ограничением BIOS (первые 1024 цилиндра/~500 МБ).
3. **Stage 2**: Основная часть GRUB загружается из `/boot/grub/`. Читает конфигурацию `grub.cfg` и предоставляет меню выбора ОС.

### initrd vs initramfs

- **initrd (Initial RAM Disk)**: Файл-образ блочного устройства с файловой системой внутри. Требовал от ядра встроенного модуля хотя бы одной файловой системы для работы.
- **initramfs (Initial RAM File System)**: Архив (cpio), распаковываемый в виртуальную файловую систему `tmpfs` (часть ядра). Ядро работает с `tmpfs` напрямую, что устраняет недостаток initrd.

Оба служат временной корневой файловой системой для загрузки модулей ядра (драйверов SCSI, файловых систем, LVM, RAID) до монтирования реального корня.

## Базовые концепции

### Путь загрузки: BIOS + MBR + GRUB

1. BIOS выполняет POST и обращается к порядку загрузки.
2. BIOS загружает первый сектор диска (MBR, 512 байт).
3. Из MBR запускается Stage 1 загрузчика GRUB.
4. GRUB загружает Stage 1.5 (при необходимости) и Stage 2.
5. GRUB читает `/boot/grub/grub.cfg`, загружает ядро (`vmlinuz`) и `initramfs` в память.
6. Ядру передаются параметры: корень (`root=`), файловая система, дополнительные опции (например, `rhgb`, `quiet`).
7. Управление передается ядру.

### Путь загрузки: UEFI + GPT + GRUB

1. UEFI ищет загрузочную запись в NVRAM.
2. Загружает `.efi`-файл загрузчика с раздела ESP (EFI System Partition, FAT32).
3. Запускается GRUB (файл `grubx64.efi` или через `shim.efi`).
4. GRUB обращается к `/boot/grub/` (обычно на той же ФС, что и ESP) и далее процесс аналогичен.

### LVM и /boot

- **GRUB Legacy**: Не поддерживал LVM. Требовался отдельный стандартный раздел для `/boot`.
- **GRUB 2**: Поддерживает LVM напрямую, отдельный раздел для `/boot` не обязателен.
- **Рекомендация RHEL**: Несмотря на поддержку LVM, RedHat рекомендует размещать `/boot` на стандартном разделе для возможности загрузки ядра и initramfs при проблемах с LVM (требуется LiveCD).

### Параметры ядра в GRUB

Строка `linux` в `grub.cfg` содержит:

- Путь к ядру (`vmlinuz-...`)
- Параметр `root=` (устройство корневой ФС)
- Дополнительные флаги: `rhgb` (анимация загрузки), `quiet` (скрыть вывод), `nomodeset` и др.

## Практические сценарии

### Просмотр параметров текущей загрузки

```bash
cat /proc/cmdline
```

### Редактирование параметров загрузки (временное)

В меню GRUB нажать `E` на нужной записи, изменить параметры, нажать `Ctrl+X` для загрузки. Изменения действуют только для текущей загрузки.

### Постоянное изменение параметров ядра

Не редактировать `grub.cfg` напрямую — файл перезаписывается при обновлениях.

1. Отредактировать `/etc/default/grub` (параметр `GRUB_CMDLINE_LINUX_DEFAULT`).
2. Перегенерировать конфигурацию:

```bash
# RHEL/CentOS
sudo grub2-mkconfig -o /boot/grub2/grub.cfg

# Debian/Ubuntu
sudo update-grub
```

### Добавление модулей в initramfs (dracut)

При миграции ВМ между гипервизорами (например, с VMware ESXi на KVM) могут потребоваться дополнительные драйверы.

1. Просмотр содержимого initramfs:

```bash
lsinitrd /boot/initramfs-$(uname -r).img | less
```

1. Создание конфигурации добавления модулей:

```bash
# Создать файл в /etc/dracut.conf.d/
# Пример: /etc/dracut.conf.d/vmware.conf
add_drivers+=" mpt3sas vmw_balloon vmw_vmci vmd "
```

1. Пересоздание initramfs:

```bash
# RHEL/CentOS
sudo dracut --force

# Debian/Ubuntu
sudo update-initramfs -u
```

### Восстановление GRUB

При повреждении загрузчика (например, после ошибки в fstab) используется LiveCD/LiveUSB:

1. Смонтировать корневую ФС и `/boot` (если он отдельно).
2. `chroot` в систему.
3. Переустановить GRUB:

```bash
# BIOS
grub2-install /dev/sda

# UEFI
grub2-install --target=x86_64-efi --efi-directory=/boot/efi
```

## Дополнительная информация

### Диагностика проблем GRUB

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `error: no such partition` | Неправильный раздел /boot | Проверить `ls` в GRUB rescue |
| `error: file not found` | Удалено ядро или grub.cfg | Переустановить GRUB |
| `error: invalid signature` | Проблема с Secure Boot | Отключить Secure Boot или обновить shim |
| `GRUB rescue>` | Поврежден загрузчик | Использовать GRUB rescue commands |
| Двойная загрузка не видна | os-prober не включен | Включить `GRUB_DISABLE_OS_PROBER=false` |

**GRUB rescue commands:**

```
ls                    # Показать разделы
ls (hd0,1)/           # Просмотреть содержимое раздела
set root=(hd0,1)      # Установить корневой раздел
linux /vmlinuz ...    # Загрузить ядро вручную
initrd /initrd.img    # Загрузить initrd
boot                  # Загрузиться
```

### Связанные темы

**Процесс загрузки:**

- **[Процесс загрузки ядра](../../Core/kernel/boot_process.md)** — этапы от GRUB до systemd
- **[BIOS и UEFI](../../Core/firmware_bios_uefi.md)** — прошивка, ранняя загрузка
- **[Восстановление пароля](./linux_password_recovery.md)** — использование GRUB для сброса пароля

**Файловые системы и LVM:**

- **[LVM](../../FileSystems/LVM/overview_concepts.md)** — логические тома
- **[LVM и загрузка](../../FileSystems/LVM/advanced_topics.md)** — загрузка с LVM

**Systemd:**

- **[Параметры ядра](../../Core/kernel/kernel_interfaces.md)** — /proc/cmdline
- **[Systemd загрузка](../../Core/systemd/boot_troubleshooting.md)** — диагностика загрузки systemd

### Безопасность GRUB

**Пароль на GRUB:**
Защита от несанкционированного изменения параметров загрузки:

```bash
# Создать хэш пароля
grub-mkpasswd-pbkdf2

# Добавить в /etc/grub.d/40_custom
set superusers="admin"
password_pbkdf2 admin grub.pbkdf2.sha512...

# Обновить конфигурацию
sudo update-grub  # Debian/Ubuntu
sudo grub2-mkconfig -o /boot/grub2/grub.cfg  # RHEL/CentOS
```

**Secure Boot:**

- GRUB должен быть подписан для работы с Secure Boot
- Используйте `shim.efi` для загрузки в системах с Secure Boot
- Отключение Secure Boot может потребоваться для кастомных ядер
