# Восстановление системы при сбоях загрузки

## Definitions

**Сбой загрузки (Boot Failure)** — состояние, при котором операционная система не может достичь целевого состояния (target/runlevel) для работы пользователя. Локализуется на этапах: BIOS/UEFI → Загрузчик (GRUB) → Ядро → Initramfs → Systemd.

**Initramfs (Initial RAM Filesystem)** — временная файловая система в оперативной памяти, используемая ядром для монтирования корневого раздела (загрузка драйверов дисков, сети, LVM, LUKS).

**Chroot (Change Root)** — системная операция переключения текущего корневого каталога на другой. Основной метод восстановления системы «извне» (с LiveCD).

## Основные концепции

### Матрица режимов прерывания загрузки

| Метод | Параметр GRUB | Окружение | Доступ | Когда использовать |
| :--- | :--- | :--- | :--- | :--- |
| **Emergency** | `systemd.unit=emergency.target` | Systemd (init) | Root пароль | Ошибки в `/etc/fstab`, мелкий ремонт. |
| **Rescue** | `systemd.unit=rescue.target` | Systemd (init) | Root пароль | Ремонт сервисов, сети (локально). |
| **init=/bin/bash** | `init=/bin/bash` | Bash (вместо init) | Прямой (No Pass) | Если забыт пароль root или сломан init. |
| **rd.break** | `rd.break` | Initramfs shell | Прямой (No Pass) | Только для RHEL/CentOS/Fedora (ранний этап). |

### Стратегии восстановления

1.  **Интервенция (GRUB):** Передача параметров ядру для остановки загрузки на ранних этапах.
2.  **Внешнее монтирование (Rescue Media):** Загрузка с LiveCD/LiveUSB для работы с файловой системой «холодным» способом.
3.  **Облачное восстановление:** Отсоединение диска и его монтирование к другой виртуальной машине (Worker VM).

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

## Дополнительная информация

### Симптомы и решения (Quick Reference)

| Симптом | Вероятная причина | Первое действие |
| :--- | :--- | :--- |
| `grub rescue>` | Смещение разделов, удаление `/boot` | `set prefix`, `insmod normal` |
| `(initramfs) >` | Ошибка ФС, неверный UUID в fstab | `fsck`, проверка `blkid` |
| Зависание на логотипе | Ошибка драйвера видео или диска | Удалить `quiet splash`, добавить `nomodeset` |
| Kernel Panic | Несоответствие initrd и ядра | Загрузка старого ядра из меню GRUB |

### См. также

- [**Диагностика загрузки (systemd)**](../../Core/systemd/boot_troubleshooting.md) — команды `journalctl -b`, `systemd-analyze`.
- [**Восстановление пароля root**](../../SystemAdministration/linux_password_recovery.md) — детализация по SELinux и `/.autorelabel`.
- [**Загрузчик GRUB**](../../SystemAdministration/grub.md) — глубокая настройка и структура конфига.
- [**Проверка целостности ФС (fsck)**](../../FileSystems/fsck.md) — ключи и сценарии исправления дисков.
- [**Chroot — смена корневого каталога**](../../Core/chroot.md) — детали реализации и безопасности.
