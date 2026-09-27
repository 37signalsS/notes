# Восстановление системы при сбоях загрузки

## Определения

**Сбой загрузки (Boot Failure)** — состояние, при котором операционная система не может достичь целевого состояния (target/runlevel) для работы пользователя. Локализуется на этапах: BIOS/UEFI → Загрузчик (GRUB) → Ядро → Initramfs → Systemd.

**Initramfs (Initial RAM Filesystem)** — временная файловая система в оперативной памяти, используемая ядром для монтирования корневого раздела (загрузка драйверов дисков, сети, LVM, LUKS).

**Chroot (Change Root)** — системная операция переключения текущего корневого каталога на другой. Основной метод восстановления системы «извне» (с LiveCD).

**Bootloader (GRUB)** — программа, запускаемая BIOS/UEFI, которая загружает ядро (`vmlinuz`) и `initramfs` в память и передает на них управление. В современных системах — GRUB 2.

**Kernel Panic** — невосстановимая ошибка ядра, при которой дальнейшая работа невозможна. Выводится на консоль и записывается в ring buffer (`dmesg`). Требует анализа дампа или загрузки с альтернативным ядром.

**UUID (Universally Unique Identifier)** — 128-битный идентификатор раздела, используемый в `/etc/fstab` и параметрах загрузки для надежного указания устройств. Не меняется при переподключении дисков (в отличие от `/dev/sdX`).

**fstab (File System Table)** — файл `/etc/fstab`, описывающий точки монтирования и параметры файловых систем. Ошибки в этом файле (неверный UUID, опции) — частая причина сбоя загрузки на этапе `local-fs.target`.

**Secure Boot** — механизм UEFI, проверяющий цифровую подпись загрузчика, ядра и модулей. При нарушении подписи система останавливается на этапе Shim/GRUB.

**ESP (EFI System Partition)** — раздел FAT32 с флагом `boot` на UEFI-системах, содержащий загрузчики (`.efi` файлы). При повреждении или удалении система перестает загружаться с сообщением об отсутствии загрузочного устройства.

**Initrd (Initial RAM Disk)** — устаревший формат начального образа (блочное устройство). В современных системах заменен на `initramfs` (архив cpio в tmpfs).

## Основные концепции

### Матрица режимов прерывания загрузки

| Метод | Параметр GRUB | Окружение | Доступ | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **Emergency** | `systemd.unit=emergency.target` | Systemd (init) | Root пароль | Ошибки в `/etc/fstab`, мелкий ремонт. |
| **Rescue** | `systemd.unit=rescue.target` | Systemd (init) | Root пароль | Ремонт сервисов, сети (локально). |
| **init=/bin/bash** | `init=/bin/bash` | Bash (вместо init) | Прямой (No Pass) | Если забыт пароль root или сломан init. |
| **rd.break** | `rd.break` | Initramfs shell | Прямой (No Pass) | Только для RHEL/CentOS/Fedora (ранний этап). |

### Boot Chain и точки восстановления

Загрузка Linux проходит через последовательность этапов, каждый из которых может стать точкой отказа:

| Этап | Компонент | Что происходит | Симптом сбоя | Метод восстановления |
| :--- | :--- | :--- | :--- | :--- |
| **1. Firmware** | BIOS/UEFI | POST, поиск загрузочного устройства | Нет сигнала, ошибка NVRAM | Сброс CMOS, выбор загрузочного устройства |
| **2. Загрузчик** | GRUB | Загрузка `vmlinuz` + `initramfs` | `grub rescue>`, `error: file not found` | Ручная загрузка, `grub-install` |
| **3. Ядро** | vmlinuz | Распаковка, инициализация драйверов | Kernel Panic, зависание | Старое ядро из меню GRUB, параметры загрузки |
| **4. Initramfs** | /init | Монтирование корня, LVM/RAID/LUKS | `(initramfs) >` | `fsck`, проверка UUID, `rd.break` |
| **5. Systemd** | PID 1 | Активация сервисов по таргету | Зависание на логотипе, `emergency.target` | `systemd.unit=rescue.target`, journal анализ |
| **6. Userspace** | Службы | Параллельный запуск демонов | Failed units, зависание | `systemctl reset-failed`, `systemd-analyze` |

### Цели systemd (targets) и их различия

| Цель | Монтирование ФС | Сеть | Службы | Пароль root | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `default.target` | Да | Да | Все | Нет | Обычная работа |
| `rescue.target` | Все локальные | Нет | Минимум | Да | Ремонт, сброс пароля |
| `emergency.target` | Только `/` (ro) | Нет | Только PID 1 | Да | Критические сбои, fstab |
| `multi-user.target` | Да | Да | Без GUI | Нет | Серверный режим |

### Особенности UEFI и Secure Boot

- **ESP partition:** При повреждении ESP (форматирование, удаление файлов `.efi`) система теряет загрузчик. Восстановление: `grub-install` с примонтированным ESP.
- **Secure Boot блокировка:** Если Shim/GRUB не проходит проверку подписи, система останавливается. Временное отключение Secure Boot в настройках UEFI (на большинстве серверов через IPMI) позволяет загрузиться.
- **MOK (Machine Owner Key):** Для загрузки с неподписанными модулями (например, драйверы NVIDIA, vfio-pci) используйте `mokutil --import` для добавления ключа в firmware.

### Загрузочный раздел `/boot`

Раздел `/boot` содержит ядро (`vmlinuz-*`), `initramfs` и конфигурацию GRUB. Если он переполнен или поврежден, загрузка прерывается на этапе GRUB или initramfs.

```bash
# Проверка размера /boot
df -h /boot
# → /dev/sda1  512M  380M  132M  75% /boot

# Просмотр установленных ядер
dpkg -l | grep linux-image    # Debian/Ubuntu
rpm -qa | grep kernel         # RHEL/Fedora

# Удаление старых ядер (Debian/Ubuntu)
sudo apt autoremove --purge
```

### Параметры ядра для диагностики

Параметры передаются через строку `linux` в конфигурации GRUB. Ключевые для восстановления:

- `init=/bin/bash` — запуск bash вместо systemd (универсальный метод)
- `rd.break` — остановка в initramfs (RHEL-подобные)
- `systemd.unit=emergency.target` — аварийный режим
- `systemd.unit=rescue.target` — режим спасения
- `systemd.debug_shell` — root-оболочка на TTY9
- `nomodeset` — отключение видеодрайверов (зависание на логотипе)
- `earlyprintk=ttyS0,115200` — вывод логов на последовательную консоль (зависание на раннем этапе)

## Практические сценарии

### 1. Прямой захват управления (init=/bin/bash)

Универсальный метод для всех дистрибутивов, если повреждена система инициализации или утерян пароль.

1.  В меню GRUB нажмите **`e`**.
2.  В строке `linux ...` замените `ro` на `rw` (или оставьте как есть, но потом перемонтируйте) и добавьте `init=/bin/bash`.
3.  Нажмите **`Ctrl+X`**.

**Действия после загрузки:**
```bash
# Если корень в ro, перемонтируем в rw
mount -o remount,rw /
# → (результат: корень доступен для записи)

# Теперь можно править конфиги или сбросить пароль
passwd root
```

---

### 2. Остановка в Initramfs (rd.break)

Используется преимущественно в Red Hat-подобных системах. Загрузка останавливается *до* передачи управления основной системе инициализации.

1.  Добавьте `rd.break` в строку `linux`.
2.  После загрузки в консоль `switch_root:/#`:
```bash
mount -o remount,rw /sysroot
chroot /sysroot
# Далее выполняются действия внутри системы
```

---

### 3. Полный Chroot из LiveCD (Золотой стандарт)

Если система не реагирует на параметры загрузки, используйте Live-образ.

**Пошаговый алгоритм:**
```bash
# 1. Монтирование корневого раздела (пример для /dev/sda2)
mount /dev/sda2 /mnt

# 2. Проброс виртуальных ФС (критично для работы mtab, grub, apt/yum)
for i in /dev /dev/pts /proc /sys /run; do mount -B $i /mnt$i; done

# 3. Вход в систему
chroot /mnt /bin/bash

# 4. Внутри chroot можно:
grub-install /dev/sda    # Восстановить загрузчик
update-initramfs -u      # Пересобрать образ ядра
# → update-initramfs: Generating /boot/initrd.img-...

# 5. Выход и очистка
exit
for i in /mnt/dev/pts /mnt/dev /mnt/proc /mnt/sys /mnt/run /mnt; do umount $i; done
reboot
```

---

### 4. Режим «grub rescue>»

Если вы видите приглашение `grub rescue>`, значит загрузчик не нашел свой раздел с модулями.

```bash
grub rescue> ls
# → (hd0) (hd0,gpt1) (hd0,gpt2)

grub rescue> set prefix=(hd0,gpt2)/boot/grub
grub rescue> set root=(hd0,gpt2)
grub rescue> insmod normal
grub rescue> normal
```
Если после `normal` появилось меню GRUB — загрузитесь и выполните `grub-install`.

---

### 5. Ошибки в Initramfs shell

Симптом: консоль `(initramfs) >`. Причина: ядро не смогло смонтировать корневую ФС.

**Диагностика:**
```bash
(initramfs) ls /dev/sd*
# Проверка ФС (чаще всего помогает)
(initramfs) fsck /dev/sda2 -y
(initramfs) exit
```

---

### 6. Kernel Panic и загрузка старого ядра

**Kernel Panic** возникает при критической ошибке ядра (несовместимые модули, поврежденный initramfs, ошибки драйверов).

**Диагностика:**
```bash
# Просмотр последних сообщений ядра (ring buffer)
sudo dmesg -H | tail -n 50

# Поиск ключевых слов
sudo dmesg | grep -iE "panic|oops|bug|call trace|exception"

# Просмотр журнала предыдущей загрузки
journalctl -b -1 -p err
```

**Действия:**
1.  В меню GRUB выберите **Advanced options** → предыдущее ядро.
2.  Если предыдущее ядро тоже падает — загрузитесь с параметром `nomodeset` для отключения видеодрайверов.
3.  После загрузки удалите проблемное ядро:
    ```bash
    # Debian/Ubuntu
    sudo apt remove linux-image-<версия>

    # RHEL/Fedora
    sudo dnf remove kernel-<версия>
    ```
4.  Пересоберите `initramfs`:
    ```bash
    sudo update-initramfs -u -k all    # Debian/Ubuntu
    sudo dracut --force                # RHEL/Fedora
    ```

---

### 7. Ошибки UUID в `/etc/fstab`

Симптом: зависание на `(initramfs)` или вход в `emergency.target` после обновления ядра.

**Диагностика:**
```bash
# Просмотр текущих UUID
sudo blkid

# Проверка fstab
cat /etc/fstab

# Проверка созданных mount-юнитов
systemctl list-unit-files --type=mount --state=failed
```

**Исправление:**
1.  Загрузитесь в `init=/bin/bash` или `rd.break`.
2.  Перемонтируйте корень в rw: `mount -o remount,rw /sysroot` (для rd.break) или `mount -o remount,rw /`.
3.  Отредактируйте `/etc/fstab`, заменив старый UUID на новый (из `blkid`).
4.  Пересоберите `initramfs`:
    ```bash
    update-initramfs -u    # Debian/Ubuntu
    dracut --force         # RHEL/Fedora
    ```
5.  Выйти и перезагрузиться.

---

### 8. `/boot` переполнен или поврежден

**Симптом:** GRUB сообщает `error: file not found` или `error: no such partition`.

**Диагностика:**
```bash
# Проверка размера
df -h /boot

# Просмотр установленных ядер
dpkg -l | grep linux-image    # Debian/Ubuntu
rpm -qa | grep kernel         # RHEL/Fedora
```

**Решение:**
1.  Загрузитесь с LiveCD.
2.  Смонтируйте корневой раздел и выполните chroot (см. Сценарий 3).
3.  Удалите старые ядра:
    ```bash
    # Debian/Ubuntu
    sudo apt autoremove --purge
    sudo update-initramfs -u -k all

    # RHEL/Fedora
    sudo dnf remove $(rpm -q kernel | sort | head -n -2)
    sudo dracut --force
    ```
4.  Восстановите GRUB: `grub-install /dev/sda && update-grub`.
5.  Выйти и перезагрузиться.

---

### 9. Восстановление загрузчика GRUB

Если GRUB не отображается или выдает ошибки (но ядро и initramfs целы):

**Вариант A: Переустановка GRUB (BIOS)**
```bash
# С LiveCD
mount /dev/sda2 /mnt
grub-install --root-directory=/mnt /dev/sda
```

**Вариант B: Переустановка GRUB (UEFI)**
```bash
mount /dev/sda2 /mnt
mount /dev/sda1 /mnt/boot/efi    # ESP раздел
for i in /dev /dev/pts /proc /sys /run; do mount -B $i /mnt$i; done
chroot /mnt
grub-install --target=x86_64-efi --efi-directory=/boot/efi
update-grub
exit
reboot
```

---

### 10. Восстановление UEFI записей (efibootmgr)

Симптом: система зависает на черном экране с сообщением `BootOrder` или `BootFailed`.

**Диагностика:**
```bash
# Просмотр текущих записей
sudo efibootmgr -v

# Проверка порядка загрузки
sudo efibootmgr -n 0001    # Тестовая загрузка с entry 0001
```

**Решение:**
1.  Загрузитесь с LiveCD в UEFI режиме.
2.  Смонтируйте ESP: `mount /dev/sda1 /mnt/boot/efi`.
3.  Переустановите GRUB:
    ```bash
    grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=GRUB
    ```
4.  Исправьте порядок загрузки:
    ```bash
    sudo efibootmgr --bootorder 0001,0002 --active
    ```

---

### 11. Использование `systemd.debug_shell`

Если systemd зависает на раннем этапе, но ядро и initramfs загрузились:

1.  Добавьте `systemd.debug_shell` в строку `linux` в GRUB.
2.  После загрузки нажмите **`Ctrl+Alt+F9`** (или переключитесь на TTY9).
3.  Вы получите root-оболочку с полным доступом к systemd:
    ```bash
    # Просмотр состояния сервисов
    systemctl list-units --state=failed

    # Запуск problem.service
    systemctl start problem.service

    # Просмотр логов
    journalctl -xb
    ```

---

### 12. Восстановление после сбоя LUKS/LVM на корне

Если корень зашифрован (LUKS) или находится на LVM:

**LUKS:**
```bash
# В initramfs shell
cryptsetup luksOpen /dev/sda3 mydisk
# Ввод пароля LUKS

# Просмотр разделов LUKS
cryptsetup luksDump /dev/sda3
```

**LVM:**
```bash
# Активация VG
vgscan
vgchange -ay

# Просмотр логических томов
lvdisplay

# Монтирование корня
mount /dev/mapper/vg0-root /mnt
```

После восстановления доступа пересоберите initramfs, чтобы драйверы LUKS/LVM включались автоматически:
```bash
# Debian/Ubuntu
echo "lvm2" | sudo tee -a /etc/initramfs-tools/modules
sudo update-initramfs -u

# RHEL/Fedora
sudo dracut --force --add lvm
```

## Дополнительная информация

### Симптомы и решения (Quick Reference)

| Симптом | Вероятная причина | Первое действие |
| :--- | :--- | :--- |
| `grub rescue>` | Смещение разделов, удаление `/boot` | `set prefix`, `insmod normal`, затем `grub-install` |
| `(initramfs) >` | Ошибка ФС, неверный UUID в fstab | `fsck`, проверка `blkid`, исправление fstab |
| Зависание на логотипе | Ошибка драйвера видео или диска | Удалить `quiet splash`, добавить `nomodeset` |
| Kernel Panic | Несовместимость модулей, поврежденный initramfs | Загрузка старого ядра, `nomodeset` |
| `/boot` полный | Нет места для нового ядра/initramfs | Удаление старых ядер, `apt autoremove` |
| Вход в `emergency.target` | Ошибка монтирования в fstab | Проверка `journalctl -xb`, исправление UUID |
| `error: file not found` (GRUB) | Удалено ядро или initramfs | Восстановление из chroot, `grub-install` |
| Отсутствие загрузочного устройства | Поврежден ESP (UEFI) | Переустановка GRUB, `efibootmgr` |
| Забыт пароль LUKS | Невозможно расшифровать корень | Восстановление данных с LiveCD, ` cryptsetup luksOpen` |
| Владелец файлов сброшен | `chown` на `/` после chroot | Не выполнять `chown` на корневую ФС извне |

### Устранение неполадок

#### `mount: wrong fs type, bad option, bad superblock`

**Причина:** Поврежденная файловая система или неверные опции монтирования.

**Решение:**
```bash
# Проверка ФС
fsck /dev/sda2 -y

# Просмотр типов ФС
blkid /dev/sda2
# → /dev/sda2: UUID="..." TYPE="ext4"

# Исправление fstab
sudo nano /etc/fstab
```

#### `You are in emergency mode. Run "journalctl -xb" to see system logs`

**Причина:** Ошибка в `/etc/fstab` или не удалось смонтировать раздел.

**Решение:**
```bash
# Перемонтировать корень в rw
mount -o remount,rw /

# Просмотр логов
journalctl -xb | grep -iE "error|fail|mount"

# Исправление fstab
nano /etc/fstab

# Перезагрузка
systemctl reboot
```

#### `Failed to start Load Kernel Modules`

**Причина:** Поврежденный initramfs или отсутствуют модули ядра.

**Решение:**
```bash
# Пересборка initramfs
update-initramfs -u -k all    # Debian/Ubuntu
dracut --force                # RHEL/Fedora
```

#### `cryptsetup: unknown filesystem type` при загрузке LUKS

**Причина:** Отсутствует модуль `dm-crypt` в initramfs.

**Решение:**
```bash
# Debian/Ubuntu
echo "dm-crypt" | sudo tee -a /etc/initramfs-tools/modules
sudo update-initramfs -u

# RHEL/Fedora
sudo dracut --force --add crypt
```

#### `grub-install: error: cannot find EFI directory`

**Причина:** Не примонтирован ESP раздел.

**Решение:**
```bash
# Найти ESP раздел
lsblk -f
# → sda1  vfat  500M  /boot/efi

# Примонтировать
mount /dev/sda1 /boot/efi

# Повторить установку
grub-install --target=x86_64-efi --efi-directory=/boot/efi
```

### Рекомендации после восстановления

1.  **Проверка целостности ФС:** `sudo fsck -f /dev/sdaX` (для всех разделов).
2.  **Обновление initramfs:** пересоберите initramfs после любых изменений в LVM/RAID/fstab.
3.  **Проверка GRUB:** `sudo update-grub`, убедитесь что все ядра обнаружены.
4.  **Тестовая перезагрузка:** после восстановления выполните `sudo reboot` и убедитесь что система загружается нормально.
5.  **Резервное копирование:** создайте резервную копию `/boot/grub/grub.cfg` и `/etc/fstab`.
6.  **Мониторинг:** настройте алерты на переполнение `/boot` (запуск `df -h /boot` через cron).
7.  **Документирование:** запишите причину сбоя и выполненные действия для дальнейшего анализа.

### См. также

- [**Диагностика загрузки (systemd)**](../../Core/systemd/boot_troubleshooting.md) — команды `journalctl -b`, `systemd-analyze`, работа с failed-юнитами.
- [**Загрузчик GRUB**](../../SystemAdministration/grub.md) — настройка конфига, переустановка загрузчика, режим rescue.
- [**Проверка целостности ФС (fsck)**](../../FileSystems/fsck.md) — ключи и сценарии исправления дисков.
