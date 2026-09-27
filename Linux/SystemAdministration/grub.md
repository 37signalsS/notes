# Загрузчик GRUB: Настройка и восстановление

## Определения

- **GRUB (Grand Unified Bootloader):** Универсальный загрузчик, работающий до старта операционной системы. Обладает собственными драйверами для доступа к оборудованию и файловым системам, предоставляет меню выбора ОС и ядер.
- **Блок окружения (GRUB Environment Block):** Файл `grubenv` (обычно 1024 байта), используемый для хранения переменных между перезагрузками (например, `saved_entry`). На UEFI-системах хранится в ESP, на BIOS — в корне `/boot/` или в первом секторе специального раздела `bios_grub`.
- **Stage 1 (Legacy BIOS):** Начальный код загрузчика в MBR (446 байт). Его единственная задача — указать на местоположение следующего этапа.
- **Stage 1.5:** Промежуточный этап в Legacy BIOS, содержащий драйверы файловых систем. Располагается в области между MBR и первым разделом.
- **Stage 2 / Core Image:** Основной код GRUB (`core.img`), загружаемый Stage 1. Содержит модули и обрабатывает конфигурацию `grub.cfg`.
- **grub.cfg:** Итоговый конфигурационный файл GRUB, генерируемый скриптами в `/etc/grub.d/`. **Не редактировать вручную**, перезаписывается при вызове `update-grub` / `grub2-mkconfig`.
- **grub-install:** Утилита для записи загрузчика на диск (MBR/ESP). Копирует `boot.img`/`core.img` и модули.
- **grub-mkconfig:** Утилита для генерации `grub.cfg` на основе `/etc/grub.d/` и `/etc/default/grub`.
- **grubby:** Утилита (RHEL/Fedora) для редактирования загрузочных записей в `grubenv` без полной перегенерации `grub.cfg`. Используется `dnf`/`rpm` автоматически при установке/удалении ядер.
- **os-prober:** Утилита для обнаружения других ОС на разделе, используемая скриптом `30_os-prober` для добавления записей в меню.
- **recordfail:** Механизм GRUB, который записывает в `grubenv` факт неудачной загрузки. При двух неудачах подряд GRUB автоматически показывает меню вместо тихого загрузки.
- **initramfs (Initial RAM File System):** Временная корневая файловая система (архив cpio), распаковываемая ядром в память для загрузки драйверов, необходимых для монтирования реального корня (LVM, RAID, шифрование). Подробнее: [Процесс загрузки ядра](../Core/kernel/boot_process.md).
- **vmlinuz:** Сжатый, самораспаковывающийся образ ядра Linux.
- **Shim:** Небольшой загрузчик, подписанный ключом Microsoft, который обеспечивает доверенную загрузку GRUB в режиме **Secure Boot**.
- **MOK (Machine Owner Key):** Ключ, добавляемый пользователем в прошивку через `mokutil` для подписи сторонних модулей ядра (NVIDIA, vfio-pci) при включенном Secure Boot.

## Базовые концепции

### Архитектура и процесс загрузки

GRUB 2 работает по модульному принципу. Вместо одного монолитного Stage 1.5/2, он использует:

**BIOS/Legacy:**
1. `boot.img` (446 байт, Stage 1) записывается в MBR. Его единственная задача — загрузить `core.img`.
2. `core.img` содержит драйверы файловых систем и загружается из области между MBR и первым разделом (или с `/boot/`).
3. `core.img` загружает модули из `/boot/grub/i386-pc/` и парсит `grub.cfg`.

**UEFI:**
1. Прошивка загружает `grubx64.efi` (или `shimx64.efi` → `grubx64.efi`) из ESP (FAT32).
2. `grubx64.efi` содержит встроенный `core.img` и ищет `grub.cfg` на доступных файловых системах.
3. В современных дистрибутивах (Fedora 34+, RHEL 9+, Debian 12+) `/boot/efi/EFI/distro/grub.cfg` является заглушкой (stub), которая перенаправляет на `/boot/grub2/grub.cfg`. Подробнее о различиях: [BIOS и UEFI](../Core/firmware_bios_uefi.md).

**Важно:** В UEFI-системах с Secure Boot цепочка подписей: прошивка → `shim.efi` (подписан Microsoft) → `grubx64.efi` (подписан дистрибутивом) → ядро (подпись опциональна).

### Структура конфигурации

Конфигурация GRUB 2 распределена по нескольким компонентам, чтобы избежать ручного редактирования основного файла.

**Почему нельзя редактировать `/boot/grub/grub.cfg` напрямую:** этот файл является автоматически генерируемым и состоит из сотен строк сложного кода и скриптов. Стоит случайно стереть там одну скобку, и сервер превратится в неработоспособный загрузчик, который не сможет найти ядро на диске. Более того, при первом же обновлении системы Linux все ручные правки будут безвозвратно удалены. Все изменения вводятся через `/etc/default/grub` или `/etc/default/grub.d/` с последующим вызовом `update-grub` / `grub2-mkconfig`.

| Файл / Директория | Назначение |
| :--- | :--- |
| `/etc/default/grub` | Основные настройки (тайм-аут, параметры ядра, тема, поведение меню). |
| `/etc/grub.d/` | Скрипты генерации меню (`00_header`, `10_linux`, `30_os-prober`, `40_custom`). |
| `/boot/grub/grub.cfg` | Итоговый конфиг. **Не редактировать вручную**, перезаписывается. |
| `/boot/grub/grubenv` | Хранилище переменных окружения (редактируется через `grub-editenv`). |
| `/etc/default/grub.d/` | Директория для drop-in конфигураций (приоритет лексикографический, например `99-custom`). |

**Пайплайн генерации `grub.cfg`:**
1. `grub-mkconfig` (или `update-grub`) запускает все скрипты из `/etc/grub.d/` в порядке `NN_*`.
2. Каждый скрипт выводит фрагменты GRUB Script на stdout.
3. Объединенный вывод записывается в `/boot/grub/grub.cfg`.
4. `00_header` генерирует общие настройки (тайм-аут, `recordfail`, `gfxterm`).
5. `10_linux` находит ядра и генерирует `menuentry`.
6. `30_os-prober` ищет другие ОС (Windows, BSD).
7. `40_custom` добавляет пользовательские записи.

**Структура `menuentry` в `grub.cfg`:**
```bash
menuentry 'Ubuntu, with Linux 6.5.0-27-generic' --class ubuntu --class gnu-linux --class gnu --class os {
    recordfail
    load_video
    gfxmode 1920x1080
    insmod gzio
    insmod part_msdos
    insmod ext2
    set root='hd0,msdos1'
    if [ x$feature_platform_search_hint = xy ]; then
      search --no-floppy --fs-uuid --set=root --hint='hd0,msdos1' 1234-ABCD
    else
      search --no-floppy --fs-uuid --set=root 1234-ABCD
    fi
    linux   /boot/vmlinuz-6.5.0-27-generic root=UUID=1234-ABCD ro quiet splash
    initrd  /boot/initrd.img-6.5.0-27-generic
}
```

### Поддержка технологий хранения

- **LVM и RAID:** GRUB 2 поддерживает загрузку с LVM и программных RAID-массивов (mdraid). Отдельный раздел `/boot` без LVM/RAID рекомендуется для упрощения восстановления в критических ситуациях.
- **Шифрование (LUKS):** GRUB поддерживает загрузку с зашифрованных разделов `/boot` (LUKS1 поддерживается нативно, LUKS2 — с ограничениями в зависимости от версии). Требует параметра `GRUB_ENABLE_CRYPTODISK=y`.
- **NVMe:** Загрузка с NVMe работает через драйвер `nvme` в GRUB. Для старых версий GRUB может потребоваться параметр `root=UUID=...` вместо `root=/dev/nvmeXnYpZ`.
- **BIOS и UEFI:** GRUB поддерживает оба режима. В современных UEFI-системах (Fedora 34+, RHEL 9+) конфигурация в `/boot/efi/EFI/distro/grub.cfg` является лишь заглушкой (stub), которая перенаправляет загрузчик на `/boot/grub2/grub.cfg`. Подробнее о различиях: [BIOS и UEFI](../Core/firmware_bios_uefi.md).

### Переменные окружения и конфигурация

**Ключевые переменные в `/etc/default/grub`:**

| Переменная | Назначение | Примечание |
| :--- | :--- | :--- |
| `GRUB_DEFAULT` | Запись по умолчанию (индекс, имя, или `saved`) | `saved` + `GRUB_SAVEDEFAULT=true` запоминает последний выбор |
| `GRUB_TIMEOUT_STYLE` | `menu`, `countdown`, `hidden` | `hidden` скрывает меню, `countdown` показывает таймер |
| `GRUB_TIMEOUT` | Тайм-аут в секундах (0 = мгновенная загрузка) | 0 требует `recordfail` для показа меню при сбое |
| `GRUB_DISTRIBUTOR` | Имя дистрибутива для записи в меню | Обычно определяется автоматически |
| `GRUB_CMDLINE_LINUX_DEFAULT` | Параметры ядра по умолчанию | Показываются в меню, применяются ко всем записям |
| `GRUB_CMDLINE_LINUX` | Параметры ядра для всех записей | Даже для recovery-режима |
| `GRUB_DISABLE_OS_PROBER` | `true` / `false` | Отключение автоматического обнаружения Windows/BSD |
| `GRUB_DISABLE_RECOVERY` | `true` / `false` | Скрытие записей recovery mode |
| `GRUB_DISABLE_SUBMENU` | `true` / `false` | Отключение вложенных подменю для нескольких ядер |
| `GRUB_TERMINAL` | `console`, `serial`, `serial console` | Управление выводом GRUB |
| `GRUB_SERIAL_COMMAND` | Параметры последовательной консоли | `serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1` |
| `GRUB_THEME` | Путь к теме (PNG + txt) | `/boot/grub/themes/starfield/theme.txt` |
| `GRUB_GFXMODE` | Разрешение видео | `1920x1080`, `auto` |
| `GRUB_GFXPAYLOAD_LINUX` | Разрешение для ядра | `keep` сохраняет разрешение GRUB |
| `GRUB_ENABLE_CRYPTODISK` | `y` / `n` | Поддержка загрузки с зашифрованного `/boot` |
| `GRUB_DISABLE_LINUX_UUID` | `true` / `false` | Использовать `/dev/sdX` вместо UUID |

**Drop-in конфигурации:**
Файлы в `/etc/default/grub.d/` обрабатываются лексикографически. Это позволяет отдельным пакетам (TuneD, FreeIPA, custom scripts) добавлять параметры без редактирования основного файла.

```bash
# /etc/default/grub.d/99-custom.cfg
GRUB_CMDLINE_LINUX_DEFAULT="${GRUB_CMDLINE_LINUX_DEFAULT} intel_iommu=on"
GRUB_TIMEOUT=5
```

### Командная строка ядра

Параметры передаются ядру через строку `linux` в конфигурации.

- `root=`: Указывает устройство с корневой ФС (рекомендуется UUID).
- `ro / rw`: Режим монтирования корня при старте.
- `quiet splash`: Скрытие технических логов и показ анимации.
- `rd.break`: Остановка загрузки в initramfs (полезно для [восстановления пароля](./linux_password_recovery.md)).
- `console=ttyS0,115200`: Перенаправление вывода на последовательный порт.
- `net.ifnames=0`: Отключение предсказуемых имен сетевых интерфейсов (возврат к `eth0`).
- `systemd.unit=emergency.target`: Загрузка в emergency mode.
- `systemd.unit=rescue.target`: Загрузка в rescue mode.
- `systemd.debug_shell`: Root shell на TTY9.
- `nomodeset`: Отключение видеодрайверов для диагностики GPU проблем.

## Практические сценарии

### 1. Управление параметрами загрузки

**Временное изменение (для одной загрузки):**
В меню GRUB нажать `e` на нужной записи, отредактировать строку `linux`, нажать `Ctrl+X` для старта.

**Постоянное изменение:**

1. Отредактировать `/etc/default/grub`:
   ```bash
   GRUB_CMDLINE_LINUX_DEFAULT="quiet splash intel_iommu=on"
   # Включение поиска других ОС (Windows и т.д.)
   GRUB_DISABLE_OS_PROBER=false
   ```

2. Обновить конфигурацию:
   ```bash
   # Debian / Ubuntu / Arch
   sudo update-grub
   # → Generating grub configuration file ...
   # → Found linux image: /boot/vmlinuz-...

   # RHEL / CentOS / Fedora (универсальный способ для современных версий)
   sudo grub2-mkconfig -o /boot/grub2/grub.cfg
   ```

### 2. Работа с блоком окружения (`grubenv`) и выбором загрузки

```bash
# Просмотр текущих переменных
grub-editenv list
# → saved_entry=0
# → recordfail=1

# Установка загрузки по умолчанию на конкретную запись (по имени или индексу)
sudo grub-set-default 0
sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.5.0-27-generic"

# Однократный запуск следующей загрузки с конкретной записи (не изменяет saved_entry)
sudo grub-reboot 2
sudo grub-reboot "Advanced options for Ubuntu>Ubuntu, with Linux 6.5.0-27-generic"

# Настройка автоматического сохранения последнего выбранного пункта
# В /etc/default/grub:
GRUB_DEFAULT=saved
GRUB_SAVEDEFAULT=true
```

**Сброс `recordfail`:**
```bash
# Если система не падала, но GRUB показывает меню из-за сброса recordfail
sudo grub-editenv /boot/grub/grubenv unset recordfail
```

### 3. Управление загрузочными записями через `grubby` (RHEL/Fedora)

`grubby` редактирует `grubenv` напрямую, без перегенерации всего `grub.cfg`. Это быстрее и безопаснее для скриптов.

```bash
# Просмотр всех записей
sudo grubby --info=ALL | grep -E "^title|^kernel"
# → title="Red Hat Enterprise Linux (4.18.0-425.3.1.el8.x86_64) 8.7 (Ootpa)"
# → kernel="/boot/vmlinuz-4.18.0-425.3.1.el8.x86_64"

# Установка записи по умолчанию
sudo grubby --set-default-index=0
sudo grubby --set-default="/boot/vmlinuz-4.18.0-425.3.1.el8.x86_64"

# Добавление параметра ко всем ядрам
sudo grubby --update-kernel=ALL --args="systemd.unified_cgroup_hierarchy=1"

# Удаление параметра у конкретного ядра
sudo grubby --remove-args="nokaslr" --update-kernel=/boot/vmlinuz-4.18.0-425.3.1.el8.x86_64

# Перезагрузка с конкретным ядром (однократно)
sudo grub-reboot "Red Hat Enterprise Linux (4.18.0-477.10.1.el8_8.x86_64) 8.8 (Ootpa)"
```

### 4. Настройка последовательной консоли (Serial Console)

Критично для headless-серверов и облачных сред (IPMI, DRAC, iDRAC).

1. Отредактировать `/etc/default/grub`:
   ```text
   GRUB_TERMINAL="serial console"
   GRUB_SERIAL_COMMAND="serial --speed=115200 --unit=0 --word=8 --parity=no --stop=1"
   GRUB_CMDLINE_LINUX_DEFAULT="console=tty0 console=ttyS0,115200n8"
   ```

2. Обновить конфигурацию GRUB:
   ```bash
   sudo update-grub
   ```

**Для UEFI-систем с только serial-доступом** (без видео):
   ```text
   GRUB_TERMINAL="serial"
   GRUB_SERIAL_COMMAND="serial --speed=57600 --unit=0 --word=8 --parity=no --stop=1"
   ```

### 5. Управление initramfs (dracut и mkinitramfs)

При изменении конфигурации LVM/RAID или миграции ВМ необходимо пересобрать initramfs.

**Debian / Ubuntu:**
```bash
# Добавить модуль
echo "lvm2" >> /etc/initramfs-tools/modules
# Обновить для текущего ядра
sudo update-initramfs -u
# → update-initramfs: Generating /boot/initrd.img-...

# Просмотр содержимого
lsinitramfs /boot/initrd.img-$(uname -r) | less
```

**RHEL / CentOS / Fedora (dracut):**
```bash
# Просмотр содержимого текущего образа
lsinitrd /boot/initramfs-$(uname -r).img | less

# Пересборка с принудительной перезаписью
sudo dracut --force

# Пересборка с добавлением драйвера
sudo dracut --force --add lvm
```

**Arch Linux (mkinitcpio):**
```bash
# Просмотр конфигурации
cat /etc/mkinitcpio.conf

# Пересборка всех образов
sudo mkinitcpio -P
```

### 6. Темы GRUB

GRUB поддерживает темы в формате PNG + текстовый файл `theme.txt`.

```bash
# Установка темы (пример для Ubuntu)
sudo apt install grub2-themes-starfield

# В /etc/default/grub:
GRUB_THEME="/boot/grub/themes/starfield/theme.txt"

# Настройка разрешения
GRUB_GFXMODE=1920x1080
GRUB_GFXPAYLOAD_LINUX=keep

# Обновление
sudo update-grub
```

**Структура темы:**
```
/boot/grub/themes/starfield/
├── theme.txt
├── background.png
├── icons/
│   ├── os_debian.png
│   └── os_linux.png
```

### 7. Пользовательские записи меню (Custom Menu Entries)

Для загрузки ISO, других дистрибутивов или специальных конфигураций используйте `40_custom` или отдельный файл в `/etc/grub.d/`.

**Загрузка ISO (для установки или rescue):**
```bash
# /etc/grub.d/40_custom
menuentry "Ubuntu 24.04 ISO" {
    set iso_path="/iso/ubuntu-24.04-desktop-amd64.iso"
    loopback loop $iso_path
    linux (loop)/casper/vmlinuz boot=casper iso-scan/filename=$iso_path noprompt noeject
    initrd (loop)/casper/initrd
}
```

**Chainloading Windows:**
```bash
# /etc/grub.d/40_custom
menuentry "Windows Boot Manager" {
    insmod part_gpt
    insmod fat
    set root='hd0,gpt1'
    chainloader /EFI/Microsoft/Boot/bootmgfw.efi
}
```

### 8. Безопасность GRUB

**Пароль на редактирование меню:**
1. Сгенерировать хэш: `grub-mkpasswd-pbkdf2`.
2. Добавить в `/etc/grub.d/40_custom`:
   ```text
   set superusers="admin"
   password_pbkdf2 admin grub.pbkdf2.sha512.10000...
   ```
3. Обновить конфиг.

**Рекомендации:**
- `GRUB_DISABLE_RECOVERY=true` — скрытие recovery-записей (они не требуют пароля).
- `GRUB_DISABLE_SUBMENU=y` — упрощение структуры меню.
- Используйте `GRUB_CMDLINE_LINUX` (не `DEFAULT`) для критичных параметров безопасности (`lockdown=integrity`), чтобы они применялись в recovery-режиме.
- Файлы в `/etc/grub.d/` должны иметь права `755`, владелец `root`.
- `/boot/grub/grub.cfg` должен иметь права `644` (содержит хэши паролей).
- На UEFI-системах защитите ESP (FAT32) от несанкционированной записи через `chattr +i` или монтирование с `ro`.

### 9. Восстановление GRUB

При повреждении загрузчика используется LiveUSB. **Подробные процедуры восстановления описаны в [Восстановление при сбоях загрузки](../Diagnostics/Troubleshooting/boot_failure_recovery.md).**

Краткая сводка:
- **BIOS:** `grub-install --root-directory=/mnt /dev/sda`
- **UEFI (chroot):** `grub-install --target=x86_64-efi --efi-directory=/boot/efi && update-grub`

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
Позволяет загрузить ядро вручную, если меню повреждено. Доступ через клавишу `C` в меню.

**Пример ручной загрузки:**
```bash
grub> ls (hd0,gpt2)/boot/              # Поиск ядра и initramfs
grub> set root=(hd0,gpt2)
grub> linux /vmlinuz root=/dev/sda2 ro # Указать корень системы
grub> initrd /initrd.img               # Загрузить initramfs
grub> boot                             # Запуск
```

### Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `error: no such partition` | Неверный UUID или индекс раздела | Проверить `ls` в rescue, поправить `prefix` |
| `error: file not found` | Удалено ядро или конфиг | Переустановка из chroot |
| `invalid signature` | Secure Boot блокирует ядро | Использовать `shim`, проверить подпись или отключить Secure Boot |
| `out of disk` | Проблема чтения за пределами BIOS лимитов | Использование отдельного `/boot` в начале диска |
| `grub-install: error: cannot find EFI directory` | Не примонтирован ESP | `mount /dev/sda1 /boot/efi` и повторить |
| `error: sparse file not allowed` | Файловая система FAT32 не поддерживает sparse файлы | Использовать `mcopy` или переформатировать ESP |

### Особенности RAID1 и многодисковых систем

При загрузке с RAID1 установите GRUB на **обоих** дисках. Если один диск выйдет из строя, второй позволит загрузиться.

```bash
# Установка на оба диска RAID1
sudo grub-install /dev/sda
sudo grub-install /dev/sdb

# Проверка
sudo grub-install --recheck /dev/sda
```

Для mdadm RAID1 с метаданными 1.0 (суперблок в конце раздела) GRUB видит раздел как обычный. Для метаданных 0.9/1.0 требуется отдельный `/boot` вне RAID или метаданные 1.0.

### Загрузка с NVMe

Имена NVMe устройств (`/dev/nvme0n1p1`) стабильны, но для GRUB лучше использовать UUID:
```bash
# Проверка UUID
blkid /dev/nvme0n1p2

# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="root=UUID=1234-ABCD ro"
```

### Проблемы Secure Boot и MOK

- **Временное отключение:** Зайдите в UEFI Setup (Del/F2 при загрузке) → Boot → Secure Boot → Disabled.
- **Добавление MOK:** `sudo mokutil --import /path/to/MOK.der` → перезагрузка → enroll ключ в MOK manager.
- **Проверка подписи:** `sbverify --cert /path/to/db.crt /boot/efi/EFI/ubuntu/shimx64.efi`.

### Аудит и compliance (Sysadmin)

```bash
# Вывод всех GRUB-записей
sudo grubby --info=ALL

# Проверка параметров загрузки
grep GRUB_CMDLINE /etc/default/grub

# Проверка наличия recovery-записей
sudo update-grub | grep -i recovery

# Проверка Secure Boot статуса
bootctl status | grep "Secure Boot"
```

### Автоматизация и управление конфигурацией

Для мультихостовых сред используйте:
- **Ansible:** модуль `lineinfile` для `/etc/default/grub`, затем `command: update-grub`.
- **GitOps:** храните `/etc/default/grub` и `/etc/grub.d/` в Git, применяйте через CI/CD с автоматическим `update-grub` и `grub-install`.
- **Проверка изменений:**
  ```bash
  # Докстер before/after
  sudo diff <(sudo grubby --info=ALL) <(sudo grubby --info=ALL) 2>/dev/null
  # Или сравнение grub.cfg
  sudo diff /boot/grub/grub.cfg /boot/grub/grub.cfg.bak
  ```

### Сравнение с systemd-boot

| Характеристика | GRUB | systemd-boot |
| :--- | :--- | :--- |
| **Сложность** | Высокая (модульная архитектура) | Низкая |
| **Поддержка ФС** | ext2/3/4, Btrfs, XFS, FAT, NTFS, LVM, RAID | Только FAT (ESP) |
| **Secure Boot** | Shim + grubx64.efi | Нативная поддержка в systemd-stub |
| **Меню** | Мощное, темы, субменю | Простое меню |
| **Сценарии** | GRUB Script (условная логика) | Ограниченные переменные |
| **Использование** | МультиОС, сложные конфигурации | Системы с одной ОС, UKI |

Подробнее: [Процесс загрузки ядра](../Core/kernel/boot_process.md).

### Ссылки

- [Восстановление при сбоях загрузки](../Diagnostics/Troubleshooting/boot_failure_recovery.md)
- [Процесс загрузки ядра](../Core/kernel/boot_process.md)
- [Модули ядра](../Core/kernel/kernel_modules.md) — загрузка/выгрузка драйверов, blacklist через GRUB
- [Базовый чеклист производительности](performance_baseline.md) — параметры ядра для загрузки через GRUB
- [Параметры sysctl](../Core/kernel/sysctl_production.md) — полный список tunables
- [Восстановление пароля root](linux_password_recovery.md) — сброс через single-user mode
