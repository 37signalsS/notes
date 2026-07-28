# Загрузчик GRUB: Настройка и восстановление

## Определения

- **GRUB (Grand Unified Bootloader):** Универсальный загрузчик, работающий до старта операционной системы. Обладает собственными драйверами для доступа к оборудованию и файловым системам, предоставляет меню выбора ОС и ядер.
- **Блок окружения (GRUB Environment Block):** Файл `grubenv` (обычно 1024 байта), используемый для хранения переменных между перезагрузками (например, `saved_entry`).
- **Stage 1 (Legacy BIOS):** Начальный код загрузчика в MBR (446 байт). Его единственная задача — указать на местоположение следующего этапа.
- **Stage 2:** Основной код GRUB, загружаемый из `/boot/grub/`. Обрабатывает конфигурацию `grub.cfg` и предоставляет интерфейс пользователю.
- **initramfs (Initial RAM File System):** Временная корневая файловая система (архив cpio), распаковываемая ядром в память для загрузки драйверов, необходимых для монтирования реального корня (LVM, RAID, шифрование). Подробнее: [Процесс загрузки ядра](../Core/kernel/boot_process.md).
- **vmlinuz:** Сжатый, самораспаковывающийся образ ядра Linux.

## Базовые концепции

### Структура конфигурации

Конфигурация GRUB 2 распределена по нескольким компонентам, чтобы избежать ручного редактирования основного файла.

| Файл / Директория | Назначение |
| :--- | :--- |
| `/etc/default/grub` | Основные настройки (тайм-аут, параметры ядра, тема). |
| `/etc/grub.d/` | Скрипты генерации меню (00_header, 10_linux, 30_os-prober, 40_custom). |
| `/boot/grub/grub.cfg` | Итоговый конфиг. **Не редактировать вручную**, перезаписывается. |
| `/boot/grub/grubenv` | Хранилище переменных окружения (редактируется через `grub-editenv`). |

### Поддержка технологий хранения

- **LVM и RAID:** GRUB 2 поддерживает загрузку с LVM и программных RAID-массивов (mdraid). Отдельный раздел `/boot` без LVM/RAID рекомендуется для упрощения восстановления в критических ситуациях.
- **BIOS и UEFI:** GRUB поддерживает оба режима. В современных UEFI-системах (Fedora 34+, RHEL 9+) конфигурация в `/boot/efi/EFI/distro/grub.cfg` является лишь заглушкой (stub), которая перенаправляет загрузчик на `/boot/grub2/grub.cfg`. Подробнее о различиях: [BIOS и UEFI](../Core/firmware_bios_uefi.md).

### Командная строка ядра

Параметры передаются ядру через строку `linux` в конфигурации.

- `root=`: Указывает устройство с корневой ФС (рекомендуется UUID).
- `ro / rw`: Режим монтирования корня при старте.
- `quiet splash`: Скрытие технических логов и показ анимации.
- `rd.break`: Остановка загрузки в initramfs (полезно для [восстановления пароля](./linux_password_recovery.md)).
- `console=ttyS0,115200`: Перенаправление вывода на последовательный порт.
- `net.ifnames=0`: Отключение предсказуемых имен сетевых интерфейсов (возврат к `eth0`).

## Практические сценарии

### 1. Управление параметрами загрузки

**Временное изменение (для одной загрузки):**
В меню GRUB нажать `e` на нужной записи, отредактировать строку `linux`, нажать `Ctrl+X` для старта.

**Постоянное изменение:**

1. Отредактировать `/etc/default/grub`:

   ```bash
   GRUB_CMDLINE_LINUX_DEFAULT="quiet splash intel_iommu=on"
   ```

2. Обновить конфигурацию:

   ```bash
   # Debian / Ubuntu / Arch
   sudo update-grub

   # RHEL / CentOS / Fedora (BIOS)
   sudo grub2-mkconfig -o /boot/grub2/grub.cfg

   # RHEL / CentOS / Fedora (UEFI) - современные версии
   sudo grub2-mkconfig -o /boot/grub2/grub.cfg
   # (Заглушка в /boot/efi/EFI/*/grub.cfg подхватит этот файл)
   ```

### 2. Работа с блоком окружения (`grubenv`)

Блок окружения используется для сохранения выбора пользователя.

```bash
# Просмотр текущих переменных
grub-editenv list

# Установка загрузки по умолчанию на конкретную запись (по имени или индексу)
sudo grub-set-default 0

# Настройка автоматического сохранения последнего выбранного пункта
# В /etc/default/grub:
GRUB_DEFAULT=saved
GRUB_SAVEDEFAULT=true
```

### 3. Настройка последовательной консоли (Serial Console)

Критично для headless-серверов и облачных сред.

1. Отредактировать `/etc/default/grub`:

   ```text
   GRUB_TERMINAL="serial console"
   GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
   GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=ttyS0,115200n8"
   ```

2. Обновить конфигурацию GRUB.

### 4. Управление initramfs (dracut и mkinitramfs)

При изменении конфигурации LVM/RAID или миграции ВМ необходимо пересобрать initramfs.

**Debian / Ubuntu:**

```bash
# Добавить модуль
echo "lvm2" >> /etc/initramfs-tools/modules
# Обновить для текущего ядра
sudo update-initramfs -u
```

**RHEL / CentOS / Fedora (dracut):**

```bash
# Просмотр содержимого текущего образа
lsinitrd /boot/initramfs-$(uname -r).img | less

# Пересборка с принудительной перезаписью
sudo dracut --force
```

### 5. Восстановление GRUB

При повреждении загрузчика используется LiveUSB.

**Для систем BIOS:**

1. Загрузиться с LiveUSB.
2. Смонтировать корень: `mount /dev/sda1 /mnt`.
3. Установить GRUB на диск: `sudo grub-install --root-directory=/mnt /dev/sda`.

**Для систем UEFI (chroot метод):**

1. Смонтировать корень и ESP:

   ```bash
   mount /dev/sda2 /mnt
   mount /dev/sda1 /mnt/boot/efi
   ```

2. Смонтировать системные API:

   ```bash
   for i in /dev /dev/pts /proc /sys /run; do mount -B $i /mnt$i; done
   ```

3. Перейти в систему и переустановить:

   ```bash
   chroot /mnt
   grub-install --target=x86_64-efi --efi-directory=/boot/efi
   update-grub
   exit
   ```

## Дополнительная информация

### Диагностика и ручная загрузка

#### Режим Rescue (`grub rescue>`)
Возникает, если GRUB не нашел свои модули или конфигурацию.

- `ls`: Список разделов (например, `(hd0,gpt2)`).
- `set`: Текущие пути (`prefix`, `root`).
- `set root=(hd0,gpt2)`
- `set prefix=(hd0,gpt2)/boot/grub`
- `insmod normal` -> `normal` (переход в обычный режим).

#### Оболочка GRUB (`grub>`)
Позволяет загрузить ядро вручную, если меню повреждено.

```bash
grub> ls (hd0,gpt2)/boot/              # Поиск ядра и initramfs
grub> set root=(hd0,gpt2)
grub> linux /vmlinuz root=/dev/sda2 ro # Указать корень системы
grub> initrd /initrd.img               # Загрузить initramfs
grub> boot
```

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error: no such partition` | Неверный UUID или индекс раздела | Проверить `ls` в rescue, поправить `prefix` |
| `error: file not found` | Удалено ядро или конфиг | Переустановка из chroot |
| `error: invalid signature` | Secure Boot блокирует ядро | Проверить подпись (Shim) или отключить Secure Boot |
| `error: out of disk` | Проблема чтения за пределами BIOS лимитов | Использование отдельного `/boot` в начале диска |

### Безопасность

**Пароль на редактирование меню:**

1. Сгенерировать хэш: `grub-mkpasswd-pbkdf2`.
2. Добавить в `/etc/grub.d/40_custom`:

   ```text
   set superusers="admin"
   password_pbkdf2 admin grub.pbkdf2.sha512.10000...
   ```

3. Обновить конфиг. После этого для нажатия `e` потребуется пароль.

Связанные темы: [Этапы загрузки ядра](../Core/kernel/boot_process.md), [Микропрограммы BIOS/UEFI](../Core/firmware_bios_uefi.md), [Диагностика загрузки](../Core/systemd/boot_troubleshooting.md).
