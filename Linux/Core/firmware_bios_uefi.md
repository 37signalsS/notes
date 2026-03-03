# BIOS и UEFI: Прошивка и старт системы

## Определения

### BIOS (Basic Input/Output System)

**BIOS** — низкоуровневое ПО, хранящееся на микросхеме материнской платы. Инициализирует и тестирует аппаратные компоненты при включении (POST), затем загружает загрузчик ОС с MBR-диска.

### UEFI (Unified Extensible Firmware Interface)

**UEFI** — современный стандарт прошивки, заменяющий BIOS. Представляет собой мини-ОС, предоставляющую стандартизированный интерфейс для взаимодействия ОС с оборудованием. Работает с GPT-дисками, запускает EFI-приложения напрямую, поддерживает Secure Boot.

### Ключевые отличия

| Характеристика | BIOS | UEFI |
| :--- | :--- | :--- |
| **Схема разделов** | MBR | GPT |
| **Макс. объем диска** | ~2.2 ТБ | ~9.4 ЗБ |
| **Режим процессора** | 16-битный | 32/64-битный |
| **Безопасность** | Отсутствует | Secure Boot |
| **Интерфейс** | Текстовый | Графический (опционально) |
| **Стартовый код** | MBR (LBA 0, 512 байт) | `.efi`-файл на ESP (FAT32) |
| **Конфигурация** | Настройки в CMOS | Переменные в NVRAM (`efibootmgr`) |
| **Сеть** | Нет | Поддержка сети (PXE) |
| **Время загрузки** | Медленнее | Быстрее (Parallel init) |

### Путь загрузки: BIOS + MBR

**Этапы:**

1. **POST (Power-On Self Test):** Проверка базового оборудования
2. **Чтение MBR (LBA 0):** BIOS читает первый сектор (512 байт), проверяет сигнатуру `0x55AA`
3. **Передача управления:** Код в MBR (stage 1 загрузчика) загружает stage 2 (например, `core.img` GRUB)
4. **Загрузчик ОС (GRUB):** Находит конфигурацию (`/boot/grub/grub.cfg`), загружает ядро (`vmlinuz`) и `initramfs`
5. **Переход к ядру:** Передача управления ядру с параметрами командной строки

**Ограничения BIOS:**

- Диски до **2.2 ТБ** (MBR)
- 16-битный режим, доступ к памяти до 1 МБ
- Нет механизмов безопасности (Secure Boot)

### Путь загрузки: UEFI + GPT

**Этапы:**

1. **Инициализация UEFI:** Прошивка инициализирует оборудование, загружает драйверы (DXE-фаза)
2. **UEFI Boot Manager:** Читает записи из NVRAM, определяет EFI-приложение для запуска
3. **ESP (EFI System Partition):** Раздел FAT32 с загрузчиками (`.efi`-файлы)
4. **Secure Boot:** Проверка цифровой подписи EFI-приложения (цепочка: `shim.efi` → `grubx64.efi` → ядро)
5. **Запуск EFI-приложения:** UEFI запускает загрузчик (GRUB, systemd-boot) или ядро с **EFI stub**
6. **Переход к ядру:** Аналогично BIOS

**Преимущества UEFI:**

- Диски до **9.4 ЗБ** (GPT)
- 32/64-битный режим с полным доступом к памяти
- **Secure Boot** для проверки подлинности
- Графический интерфейс, поддержка мыши и сети
- Быстрая загрузка (parallel init)

## Практические сценарии

### 1. Проверка текущего режима загрузки

```bash
# Проверка наличия UEFI (каталог существует = UEFI)
ls /sys/firmware/efi

# Альтернативно: через mount
mount | grep efivarfs

# Проверка типа разделов (MBR или GPT)
fdisk -l /dev/sda | grep 'Disklabel'
# Вывод: "Disklabel type: gpt" или "Disklabel type: dos" (MBR)

# Проверка через parted
parted /dev/sda print | grep 'Partition Table'
```

### 2. Управление EFI-записями (UEFI)

```bash
# Показать текущие записи загрузки
efibootmgr -v

# Изменить порядок загрузки (0001 = первый приоритет)
efibootmgr -o 0001,0002,0003

# Добавить новую запись
efibootmgr -c -d /dev/sda -p 1 -L "My Linux" -l '\EFI\ubuntu\shimx64.efi'

# Удалить запись
efibootmgr -b 0003 -B
```

### 3. Управление параметрами прошивки

Вход в BIOS/UEFI Setup (клавиши `Del`, `F2`, `F10`, `Esc` при старте):

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| **Boot Order** | Приоритет загрузочных устройств | SSD → USB → Network (PXE) |
| **Secure Boot** | Проверка подписи загрузчика | Включено для безопасности |
| **VT-x/AMD-V** | Аппаратная виртуализация | Включено для гипервизоров |
| **Fast Boot** | Быстрая загрузка | Включено, если нет проблем |
| **CSM/Legacy** | Совместимость с BIOS | Выключено для чистого UEFI |

### 4. Диагностика проблем

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Чёрный экран после POST | Неверный порядок загрузки | Проверить Boot Order в BIOS/UEFI |
| `error: no such partition` | Повреждён GRUB или раздел | Восстановить GRUB с LiveUSB |
| Secure Boot violation | Неподписанный загрузчик | Отключить Secure Boot или подписать загрузчик |
| Звуковые сигналы POST | Аппаратная ошибка | Расшифровать коды сигналов (память, видео) |

### 5. Восстановление GRUB (UEFI)

```bash
# С LiveUSB: смонтировать корневой раздел и ESP
mount /dev/sda2 /mnt
mount /dev/sda1 /mnt/boot/efi  # ESP раздел

# Смонтировать псевдо-ФС
mount --bind /dev /mnt/dev
mount --bind /proc /mnt/proc
mount --bind /sys /mnt/sys

# Chroot и переустановить GRUB
chroot /mnt
grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=GRUB
update-grub  # или grub-mkconfig -o /boot/grub/grub.cfg
exit

# Перезагрузка
reboot
```

## Дополнительная информация

### Глоссарий терминов

| Термин | Определение |
| :--- | :--- |
| **Reset Vector** | Адрес (`0xFFFFFFF0` для x86), с которого CPU начинает выполнение после сброса |
| **POST** | Power-On Self Test — ранняя самодиагностика оборудования |
| **MBR** | Master Boot Record — первый сектор диска (512 байт), загрузочный код + таблица разделов |
| **GPT** | GUID Partition Table — современная разметка с глобальными уникальными идентификаторами |
| **ESP** | EFI System Partition — раздел FAT32 для EFI-загрузчиков (`.efi`-файлы) |
| **NVRAM** | Энергонезависимая память UEFI для переменных и записей загрузки |
| **Secure Boot** | Механизм проверки криптографических подписей загрузчика и ядра |
| **shim.efi** | Прослойка, подписанная Microsoft, для загрузки GRUB с подписью дистрибутива |
| **EFI stub** | Возможность ядра Linux запускаться напрямую как EFI-приложение |
| **DXE** | Driver Execution Environment — фаза загрузки драйверов в UEFI |

### Связанные темы

- **[Boot Process](./kernel/boot_process.md)** — загрузка ядра после передачи управления от загрузчика
- **[GRUB](../PackageManagement/grub.md)** — настройка загрузчика GRUB
- **[Разметка диска](../FileSystems/partitions_and_filesystems.md)** — MBR и GPT
- **[PXE Boot](../Networking/Concepts/pxe_boot.md)** — сетевая загрузка

### Дополнительные ресурсы

- **UEFI Specification:** [uefi.org](https://uefi.org/specifications)
- **GRUB Manual:** [gnu.org/software/grub/manual](https://www.gnu.org/software/grub/manual/grub.html)
- **efibootmgr:** [man page](https://man7.org/linux/man-pages/man8/efibootmgr.8.html)
- **Systemd Boot:** [systemd-boot](https://www.freedesktop.org/software/systemd/man/systemd-boot.html)
