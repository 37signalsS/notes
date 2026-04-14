# Загрузчик GRUB

## Определения

### GRUB (Grand Unified Bootloader)

**GRUB** — загрузчик операционной системы, работающий до загрузки ОС. Обладает собственными минимальными драйверами для работы с железом, обращаясь к BIOS или напрямую к оборудованию. Предоставляет интерфейс для выбора ОС, версии ядра и позволяет редактировать параметры загрузки (клавиша `E`).

### Этапы загрузки GRUB (Legacy BIOS)

1. **Stage 1**: Загрузка кода из MBR (446 байт). Из-за малого размера содержит только указатель на следующий этап.
2. **Stage 1.5** (опционально): Загружается из первых 62 секторов диска. Содержит драйверы файловых систем для доступа к `/boot/grub/`. Требовался для старого железа с ограничением BIOS (первые 1024 цилиндра/~500 МБ).
3. **Stage 2**: Основная часть GRUB загружается из `/boot/grub/`. Читает конфигурацию `grub.cfg` и предоставляет меню выбора ОС.

### initrd vs initramfs

Кратко: оба служат временной корневой ФС для загрузки модулей ядра до монтирования реального корня.

- **initrd**: файл-образ блочного устройства с ФС внутри (устарел).
- **initramfs**: архив cpio, распаковываемый в `tmpfs` (часть ядра) — современный стандарт.

> **Подробное описание:** [initramfs и этапы загрузки ядра](../Core/kernel/boot_process.md#initramfs-initial-ram-file-system)

## Базовые концепции

### Путь загрузки: BIOS + MBR + GRUB

GRUB загружается после POST и чтения MBR BIOS. Краткий процесс:

1. BIOS → MBR (512 байт) → Stage 1 GRUB.
2. Stage 1 → Stage 1.5 (опционально) → Stage 2 (`/boot/grub/`).
3. GRUB читает `grub.cfg`, загружает `vmlinuz` + `initramfs`, передаёт управление ядру.

> **Подробный путь BIOS/UEFI:** [BIOS + MBR путь загрузки](../Core/firmware_bios_uefi.md#путь-загрузки-bios--mbr)

### Путь загрузки: UEFI + GPT + GRUB

UEFI загружает `.efi`-файл GRUB (`grubx64.efi` или через `shim.efi`) с раздела ESP (FAT32). Далее процесс аналогичен BIOS-пути.

> **Подробный путь UEFI:** [UEFI + GPT путь загрузки](../Core/firmware_bios_uefi.md#путь-загрузки-uefi--gpt)

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

При миграции ВМ между гипервизорами (например, с VMware ESXi на KVM) могут потребоваться дополнительные драйверы. Также это критично для систем с LVM или RAID.

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

### Включение lvm2 в initramfs

Если корневая ФС находится на LVM, модуль `lvm2` должен быть включён в initramfs для активации VG при загрузке.

**Debian/Ubuntu:**

```bash
echo "lvm2" >> /etc/initramfs-tools/modules
update-initramfs -u
update-grub
```

**RHEL/CentOS/Fedora:**

```bash
echo 'add_dracutmodules+=" lvm "' >> /etc/dracut.conf.d/lvm.conf
dracut --force
grub2-mkconfig -o /boot/grub2/grub.cfg
```

**Проверка:**

```bash
# Убедиться, что lvm2 попал в initramfs
lsinitrd /boot/initramfs-$(uname -r).img | grep lvm
```

**Troubleshooting:** **[Загрузка с LVM — Volume group not found](../FileSystems/LVM/advanced_topics/definitions_and_concepts.md#проблема-volume-group-not-found-после-рестарта)**

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

**Связанные темы:** процесс загрузки — [Process загрузки ядра](../Core/kernel/boot_process.md), [BIOS и UEFI](../Core/firmware_bios_uefi.md); восстановление доступа — [Восстановление пароля](./linux_password_recovery.md); LVM — [LVM Overview](../FileSystems/LVM/overview_concepts.md); диагностика systemd — [Boot Troubleshooting](../Core/systemd/boot_troubleshooting.md).
