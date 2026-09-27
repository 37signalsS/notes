# Определения

**Сценарий переноса каталога (Directory migration scenario)** — комплексная процедура перемещения содержимого существующей системной директории (например, `/var/log`, `/var/lib/docker`, `/home`) на выделенный физический диск, раздел или логический том.

Основная цель операции — предотвращение переполнения корневого раздела (`/`), изоляция данных для повышения отказоустойчивости, оптимизация производительности или упрощение процедур резервного копирования.

# Основные концепции

## Принципы миграции без простоя

Для успешной миграции без потери данных и нарушения работы системы необходимо соблюдать следующие принципы:

1.  **Консистентность (Consistency)**: Остановка всех процессов, пишущих в целевой каталог. Использование `lsof` или `fuser` для поиска открытых дескрипторов.
2.  **Сохранение метаданных**: Использование инструментов (преимущественно `rsync -aAX`), поддерживающих сохранение прав доступа, расширенных атрибутов (xattr), ACL и контекстов SELinux.
3.  **Атомарность переключения**: Подготовка нового раздела во временной точке монтирования и быстрая подмена оригинального каталога.
4.  **Безопасный откат (Rollback)**: Переименование оригинального каталога вместо его немедленного удаления.

## Bind Mount: внутреннее устройство

Bind mount создает зеркало уже существующей директории или файла в другом месте дерева ФС. Исходная и целевая точки монтирования разделяют один и тот же inode и содержимое на уровне ядра. Это отличается от символической ссылки, которая работает на уровне имен и требует отдельного разрешения пути ядром.

**Механика на уровне VFS:**
- Ядро создает новую запись в таблице монтирований mount namespace, указывающую на тот же суперблок и ту же корневую директорию исходной ФС.
- Любое изменение в одной точке немедленно видно в другой, так как они указывают на одни и те же inodes.
- Bind mount наследует права доступа исходной директории. Для изменения прав только на точке назначения требуется двойной `remount,bind`.

## Распространение монтирования (Mount Propagation)

При создании bind mount важно понимать режимы распространения:

| Режим | Поведение | Применение в миграции |
| :--- | :--- | :--- |
| **Private** | Изоляция от родительского namespace | Стандарт для изолированных каталогов данных |
| **Shared** | События передаются в обе стороны | Не рекомендуется для миграции (риск циклических монтирований) |
| **Slave** | Только получение событий от родителя | Полезно для контейнеров, получающих проброшенные директории |
| **Unbindable** | Запрещает повторный bind mount | Защита от рекурсии при сложных переносах |

По умолчанию новые bind mount наследуют режим распространения от источника. Для изоляции мигрируемого каталога выполните:
```bash
sudo mount --make-private /mnt/newdata
```

## Атомарное переключение

Ключевое преимущество rename над удалением: переименование оригинального каталога (`/var/log` → `/var/log.old`) атомарно и не требует размонтирования. Это позволяет мгновенно откатить изменения, просто вернув имя:
```bash
# Откат за 1 команду
sudo mount --move /mnt/newlog /var/log
```

Команда `mount --move` атомарно перемещает точку монтирования в новое место внутри того же mount namespace, что критично для сервисов, удерживающих открытые файловые дескрипторы.

## Особенности файловых систем при миграции

| ФС | Особенности миграции |
| :--- | :--- |
| **ext4** | Стандартный выбор. `tune2fs -O ^has_journal` требует unmount. Проверяйте `reserved_blocks_count`. |
| **XFS** | Нельзя изменить размер блока или включить/выключить journaling после создания. Используйте `xfs_growfs` для расширения онлайн. |
| **Btrfs** | Поддерживает онлайн-изменение большинства параметров через `btrfs property`. Подходит для сценариев с сжатием `zstd`. |
| **tmpfs** | Данные теряются при отключении питания. Используется только для кэшей и временных данных. |

# Предварительная проверка и подготовка

## Проверка здоровья диска

Перед миграцией данных на новый носитель выполните проверку SMART-атрибутов:
```bash
sudo smartctl -H /dev/sdb
# → SMART overall-health self-assessment test result: PASSED

sudo smartctl -A /dev/sdb | grep -E 'Reallocated_Sector_Ct|Current_Pending_Sector|UDMA_CRC_Error_Count'
# → Reallocated_Sector_Ct   0x0032   100   100   010    Old_age   Always       -       0
# → Current_Pending_Sector  0x0012   100   100   000    Old_age   Always       -       0
```

**Пороговые значения для принятия решения:**
- `Reallocated_Sector_Ct > 0`: диск имеет переназначенные сектора, ненадежен для данных.
- `Current_Pending_Sector > 0`: сектора с неисправимыми ошибками, возможна потеря данных.
- `UDMA_CRC_Error_Count > 0`: проблемы с кабелем или разъемом SATA.

## Проверка пространства и inodes

```bash
# Свободное место на целевом разделе
df -h /mnt/newdata

# Доступные inodes (критично для каталогов с тысячами мелких файлов)
df -i /mnt/newdata

# Оценка размера и количества файлов исходного каталога
sudo du -sh /var/log
sudo find /var/log -type f | wc -l
```

**Формула резервирования:** `target_size >= source_size * 1.2` (20% запас для роста и фрагментации).

## Проверка процессов и дескрипторов

```bash
# Поиск процессов, пишущих в целевой каталог
sudo lsof +D /var/log

# Альтернативный способ: показывает PID, пользователя и тип доступа
sudo fuser -vm /var/log
# → /var/log:  1234c 5678w   (c=current dir, w=write)

# Проверка открытых сокетов и FIFO
sudo lsof +L1 /var/log | grep deleted
# → Удаленные файлы, которые все еще удерживаются процессами
```

## Создание контрольных сумм (опционально)

Для верификации целостности после миграции:
```bash
# Создание базы контрольных сумм исходных данных
sudo find /var/log -type f -exec sha256sum {} + | sort > /tmp/checksums_before.txt

# После миграции
sudo find /mnt/newlog -type f -exec sha256sum {} + | sort > /tmp/checksums_after.txt

# Сравнение
diff /tmp/checksums_before.txt /tmp/checksums_after.txt
# → Нет отличий = миграция прошла успешно
```

## Подготовка точки монтирования

```bash
# Создание директории с правильными правами
sudo mkdir -p /mnt/newlog
sudo chown root:root /mnt/newlog
sudo chmod 755 /mnt/newlog

# Проверка, что точка монтирования пуста
sudo mount /dev/sdb1 /mnt/newlog
ls -la /mnt/newlog
sudo umount /mnt/newlog
```

# Практические сценарии

## Сценарий 1: Перенос /var/log на новый диск

Типовая задача при переполнении корневого раздела системными журналами.

### 1. Предварительная проверка

```bash
# Проверка SMART
sudo smartctl -H /dev/sdb

# Проверка пространства
df -h /mnt/newlog
df -i /mnt/newlog

# Проверка процессов
sudo lsof +D /var/log
sudo fuser -vm /var/log
```

### 2. Остановка служб логирования

```bash
sudo systemctl stop rsyslog.service systemd-journald.service
```

### 3. Копирование данных

Смонтируйте новый раздел (например, `/dev/sdb1`) во временную директорию:
```bash
sudo mount /dev/sdb1 /mnt
sudo rsync -aAXv --progress /var/log/ /mnt/
```

**Опции rsync:**
- `-a` (archive): режим архивации (рекурсивно, сохраняет права, времена, владельцев).
- `-A`: сохраняет ACL.
- `-X`: сохраняет расширенные атрибуты (xattr).
- `-v`: подробный вывод для отслеживания прогресса.

*Примечание: Слэш в конце `/var/log/` инструктирует rsync копировать содержимое каталога, а не сам каталог.*

### 4. Верификация миграции

```bash
# Проверка количества файлов
sudo find /var/log -type f | wc -l
sudo find /mnt -type f | wc -l
# → Количества должны совпадать

# Проверка контрольных сумм (если созданы заранее)
diff /tmp/checksums_before.txt <(sudo find /mnt -type f -exec sha256sum {} + | sort)
# → Нет отличий
```

### 5. Атомарное переключение

```bash
# Резервирование старых данных
sudo mv /var/log /var/log.old
sudo mkdir /var/log

# Получение UUID нового диска
UUID=$(lsblk -dno UUID /dev/sdb1)

# Добавление в /etc/fstab (опция noatime рекомендуется для SSD)
echo "UUID=$UUID /var/log ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab

sudo systemctl daemon-reload
sudo mount /var/log
```

### 6. Верификация и восстановление контекста

Если в системе включен SELinux, необходимо восстановить контексты безопасности:
```bash
sudo restorecon -Rv /var/log
```

Запустите службы и проверьте их статус:
```bash
sudo systemctl start systemd-journald.service rsyslog.service
sudo systemctl status rsyslog.service
```

### 7. Очистка

После подтверждения успешной работы (в течение 7 дней):
```bash
sudo rm -rf /var/log.old
```

## Сценарий 2: Перенос /var/lib/docker на LVM-том

LVM позволяет гибко расширять пространство в будущем, что критично для хранения образов и контейнеров.

### 1. Создание логического тома

Предположим, у вас есть группа томов `vg_data`:
```bash
sudo lvcreate -L 50G -n lv_docker vg_data
sudo mkfs.xfs /dev/mapper/vg_data-lv_docker
```

### 2. Миграция данных Docker

```bash
# Полная остановка Docker и связанных компонентов
sudo systemctl stop docker.socket docker.service

# Монтирование и копирование
sudo mount /dev/mapper/vg_data-lv_docker /mnt
sudo rsync -aAXv /var/lib/docker/ /mnt/

# Переименование и создание точки монтирования
sudo mv /var/lib/docker /var/lib/docker.old
sudo mkdir /var/lib/docker

# Настройка fstab
echo "/dev/mapper/vg_data-lv_docker /var/lib/docker xfs defaults 0 0" | sudo tee -a /etc/fstab
sudo systemctl daemon-reload
sudo mount /var/lib/docker

# Запуск
sudo systemctl start docker
```

## Сценарий 3: Использование Bind Mount для переназначения путей

Bind mount позволяет смонтировать одну директорию в другую, что удобно для быстрого "переброса" данных без изменения конфигурации приложений.

### 1. Перенос данных

Например, перенесем данные сайта из `/var/www/html` в `/data/www`:
```bash
sudo mkdir -p /data/www
sudo rsync -aAXv /var/www/html/ /data/www/
```

### 2. Настройка монтирования

Временное решение:
```bash
sudo mount --bind /data/www /var/www/html
```

Постоянное решение через `/etc/fstab`:
```bash
# Формат: [Источник] [Точка монтирования] none bind 0 0
echo "/data/www /var/www/html none bind 0 0" | sudo tee -a /etc/fstab
```

### 3. Сделать Bind Mount доступным только для чтения

Для защиты данных от случайной записи:
```bash
# После создания bind mount
sudo mount -o remount,bind,ro /var/www/html

# В fstab: /data/www /var/www/html none bind,ro 0 0
```

### 4. Рекурсивный Bind Mount

Для проброса всей иерархии каталога (включая вложенные монтирования):
```bash
sudo mount --rbind /data/www /var/www/html

# В fstab: /data/www /var/www/html none rbind 0 0
```

**Внимание:** `--rbind` также пробрасывает флаги распространения (shared/slave). Для изоляции:
```bash
sudo mount --make-rprivate /var/www/html
```

## Сценарий 4: Перенос /home с сохранением пользовательских данных

Сценарий требует особой осторожности, так как `/home` содержит данные активных пользователей.

### 1. Подготовка

```bash
# Оповещение пользователей о planned maintenance
sudo wall "System maintenance in 30 minutes. Please save your work."

# Проверка активных сессий
who | grep -v '^$'
sudo loginctl list-sessions
```

### 2. Остановка пользовательских процессов

```bash
# Остановка служб, работающих из /home (например, веб-серверы)
sudo systemctl stop nginx apache2

# Принудительное завершение оставшихся процессов (ОСТОРОЖНО)
sudo fuser -km /home
```

### 3. Миграция

```bash
sudo mount /dev/sdc1 /mnt
sudo rsync -aAXv --exclude='*/.cache' /home/ /mnt/
```

Опция `--exclude='*/.cache'` позволяет пропустить кэш браузеров и приложений, который не критичен для переноса.

### 4. Атомарное переключение

```bash
sudo mv /home /home.old
sudo mkdir /home

# В fstab используйте UUID для стабильности
echo "UUID=$(lsblk -dno UUID /dev/sdc1) /home ext4 defaults,noatime,nodev 0 2" | sudo tee -a /etc/fstab

sudo systemctl daemon-reload
sudo mount /home
```

### 5. Верификация

```bash
# Проверка, что пользователи могут войти в систему
su - testuser
# → Должен произойти успешный вход в домашний каталог

# Проверка контекстов SELinux
sudo restorecon -Rv /home
```

## Сценарий 5: Перенос /var с использованием временного корня

Сложный сценарий для систем, где `/var` содержит множество взаимосвязанных служб.

### 1. Анализ зависимостей

```bash
# Поиск всех служб, зависящих от /var
systemctl list-dependencies --reverse /var
# → syslog.service, docker.service, cron.service...

# Создание списка для остановки
sudo systemctl stop rsyslog docker cron
```

### 2. Подготовка в Rescue Mode (альтернатива)

Если остановка всех служб невозможна без downtime:
```bash
# Перезагрузка в Rescue Mode
sudo systemctl isolate rescue.target

# Монтирование основной системы
sudo mount /dev/sda1 /mnt
sudo mount /dev/sdb1 /mnt/var

# Копирование
sudo rsync -aAXv /mnt/var/ /mnt/var_new/

# Переключение из chroot
sudo chroot /mnt
mv /var /var.old
mkdir /var
echo "UUID=... /var ext4 defaults 0 2" >> /etc/fstab
exit
sudo reboot
```

## Сценарий 6: Bind Mount в контейнерной среде

Использование `--rbind` для проброса директорий в контейнеры.

```bash
# Подготовка директории с данными
sudo mkdir -p /data/nginx/html
sudo rsync -aAXv /var/www/html/ /data/nginx/html/

# Создание bind mount с правильными контекстами SELinux
sudo mount --bind /data/nginx/html /var/www/html
sudo mount --make-private /var/www/html

# Для контейнера Docker
docker run -d \
  --name nginx \
  -v /data/nginx/html:/usr/share/nginx/html:ro \
  nginx:alpine

# Проверка монтирования внутри контейнера
docker exec nginx ls -la /usr/share/nginx/html
```

**Внимание:** В Docker volume mount и bind mount — разные механизмы. Bind mount (`-v /host/path:/container/path`) пробрасывает конкретную директорию хоста, тогда как volume mount управляется Docker'ом.

## Сценарий 7: chroot recovery — восстановление системы через bind mount

При выходе из строя загрузчика, повреждении fstab или отсутствии ключей LUKS восстановление выполняется из LiveCD (rescue mode) через chroot с пробросом системных директорий через bind mount.

### Когда применяется
- Ошибка в `/etc/fstab` → Emergency Mode
- Повреждение initramfs → система не находит корневой раздел
- Сломан GRUB → нет меню загрузки
- Забыт пароль root → сброс через chroot
- Повреждение LUKS-метаданных

### Шаг 1: Загрузка в rescue mode

```bash
# Из LiveCD/USB или через IPMI/iDRAC
# Система загружается в RAM, файловые системы не смонтированы
```

### Шаг 2: Монтирование корневого раздела

```bash
# Определение корневого раздела
lsblk -f
# → NAME   FSTYPE LABEL UUID                                 MOUNTPOINTS
# → sda2   ext4         a1b2c3d4-e5f6-...                   /
# → sda1   vfat         B1C2-D3E4                            /boot/efi

# Если LUKS:
sudo cryptsetup open /dev/sda3 crypt_root
sudo vgchange -ay vg_system

# Монтирование корня
sudo mount /dev/mapper/vg_system-lv_root /mnt
# или
sudo mount /dev/sda2 /mnt
```

### Шаг 3: Bind mount системных директорий

Критический шаг: chroot не работает без `/dev`, `/proc`, `/sys`. Эти директории должны быть проброшены через bind mount.

```bash
# Проброс /dev — содержит устройства (/dev/sda, /dev/null, etc.)
sudo mount --bind /dev /mnt/dev

# Проброс /proc — содержит информацию о процессах и ядре
sudo mount --bind /proc /mnt/proc

# Проброс /sys — содержит информацию о системе
sudo mount --bind /sys /mnt/sys

# Проброс /run — содержит PID-файлы сокетов и текущие mount points
sudo mount --bind /run /mnt/run

# Проброс /boot (если отдельный раздел)
sudo mount /dev/sda1 /mnt/boot

# Проброс EFI (если отдельный)
sudo mount /dev/sda1 /mnt/boot/efi
```

**Почему именно `/dev`, `/proc`, `/sys`:**
- `/dev` — chroot нужен доступ к блочным устройствам для установки загрузчика
- `/proc` — нужен для работы `mount`, `ps`, определения корня ФС
- `/sys` — нужен для доступа к информации об устройствах и драйверах

### Шаг 4: Вход в chroot

```bash
sudo chroot /mnt /bin/bash

# Теперь вы "внутри" системы. Проверка:
whoami         # → root
mount          # → Должны видеть смонтированные разделы
cat /etc/fstab # → Конфигурация монтирования
```

### Шаг 5: Восстановление

**Вариант A: Ошибка в fstab:**
```bash
# Исправление fstab
nano /etc/fstab

# Проверка
cat /etc/fstab
mount -a  # Должно отработать без ошибок

exit
sudo umount -R /mnt
reboot
```

**Вариант B: Переустановка GRUB:**
```bash
# В chroot
grub-install /dev/sda
update-grub  # или grub2-mkconfig -o /boot/grub2/grub.cfg

exit
sudo umount -R /mnt
reboot
```

**Вариант C: Сброс пароля root:**
```bash
# В chroot
passwd root
# Введите новый пароль дважды

exit
sudo umount -R /mnt
reboot
```

**Вариант D: Восстановление initramfs:**
```bash
# В chroot
update-initramfs -u   # Debian/Ubuntu
# или
dracut -f             # RHEL/CentOS

exit
sudo umount -R /mnt
reboot
```

**Вариант E: Забытый пароль LUKS:**
```bash
# Из LiveCD (не chroot)
sudo cryptsetup luksAddKey /dev/sda3  # Добавление нового ключа
# или
sudo cryptsetup luksDump /dev/sda3     # Просмотр информации

# Если есть backup-ключ:
sudo cryptsetup open --key-file /backup/luks.key /dev/sda3 crypt_root
```

### Шаг 6: Безопасный выход из chroot

```bash
# В chroot
exit

# Размонтирование в ОБРАТНОМ порядке (важно!)
sudo umount /mnt/boot/efi
sudo umount /mnt/boot
sudo umount /mnt/run
sudo umount /mnt/sys
sudo umount /mnt/proc
sudo umount /mnt/dev
sudo umount /mnt

# Если LUKS
sudo vgchange -a n vg_system
sudo cryptsetup close crypt_root

# Перезагрузка
sudo reboot
```

**Важно:** Порядок размонтирования обратный порядку монтирования. Невыполнение этого правила может привести к повреждению данных.

### Чеклист восстановления

| Задача | Команда | Результат |
| :--- | :--- | :--- |
| Mount root | `mount /dev/... /mnt` | Корень примонтирован |
| Bind /dev | `mount --bind /dev /mnt/dev` | Устройства доступны |
| Bind /proc | `mount --bind /proc /mnt/proc` | Процессы видны |
| Bind /sys | `mount --bind /sys /mnt/sys` | Система доступна |
| Bind /run | `mount --bind /run /mnt/run` | Сокеты доступны |
| chroot | `chroot /mnt /bin/bash` | Вход в систему |
| Проверка fstab | `cat /etc/fstab` | Конфигурация корректна |
| Восстановление | Нужная операция | GRUB/passwd/initramfs |
| umount -R | `umount -R /mnt` | Безопасный выход |
| reboot | `reboot` | Система загружается |

# Верификация после миграции

## Проверка монтирования

```bash
# Подтверждение точки монтирования
findmnt /var/log
# → TARGET  SOURCE   FSTYPE OPTIONS
# → /var/log /dev/sdb1 ext4   rw,noatime,relatime

# Проверка через /proc
grep ' /var/log ' /proc/mounts
# → /dev/sdb1 /var/log ext4 rw,noatime,relatime 0 0

# Проверка propagation flags
cat /proc/self/mountinfo | grep ' /var/log '
# → 45 28 8:17 / /var/log rw,relatime private - ext4 /dev/sdb1 rw
```

## Проверка сервисов

```bash
# Проверка, что journald пишет в новый каталог
sudo systemctl restart systemd-journald
sudo journalctl --vacuum-time=1s
# → Удаление старых записей прошло успешно

# Проверка, что логи пишутся
echo "test message" | sudo tee /var/log/syslog
sudo tail -1 /var/log/syslog
# → test message
```

## Проверка контекстов SELinux

```bash
# Просмотр текущих контекстов
sudo ls -laZ /var/log
# → drwxr-xr-x. root root system_u:object_r:var_log_t:s0 journal

# Проверка логов audit на предмет denials
sudo ausearch -m avc -ts recent | grep /var/log
# → Нет записей = контексты корректны
```

## Проверка производительности

```bash
# Тест записи на целевом разделе
sudo dd if=/dev/zero of=/var/log/testfile bs=1G count=1 oflag=dsync
# → 1073741824 bytes (1.1 GB) copied, 2.345 s, 458 MB/s

# Очистка тестового файла
sudo rm /var/log/testfile
```

# Безопасность миграции

## Рекомендуемые опции монтирования

| Опция | Эффект | Рекомендуется для |
| :--- | :--- | :--- |
| `nosuid` | Игнорирование SUID/SGID битов | Все несистемные разделы |
| `noexec` | Запрет выполнения бинарных файлов | `/var/log`, `/home`, `/tmp` |
| `nodev` | Запрет интерпретации блочных/символьных устройств | Все несистемные разделы |
| `noatime` | Отключение обновления времени доступа | Все разделы для снижения I/O |
| `nodiratime` | Отключение обновления времени доступа для директорий | Дополнение к noatime |

Пример безопасной конфигурации для `/var/log`:
```text
UUID=... /var/log ext4 defaults,nosuid,nodev,noexec,noatime 0 2
```

## Контексты SELinux

После миграции данные с диска могут иметь неправильные контексты безопасности:
```bash
# Автоматическое восстановление контекстов
sudo restorecon -Rv /var/log

# Проверка и исправление без изменения других атрибутов
sudo chcon -R --reference=/var/log /var/log
```

## Правовая чистота (Immutable атрибуты)

Для защиты критичных каталогов от изменения:
```bash
# Установка immutable флага (требует umount или специального права)
sudo chattr +i /data/www/html/index.html
# → Файл нельзя удалить или изменить, даже root

# Проверка флагов
sudo lsattr /data/www/html/
# → ----i----------- /data/www/html/index.html
```

# Автоматизация и IaC

## Ansible

```yaml
- name: Перенос /var/log на новый диск
  hosts: all
  become: yes
  vars:
    mount_device: /dev/sdb1
    mount_point: /var/log
    fstype: ext4
    mount_opts: "defaults,noatime,nosuid,nodev,noexec"

  tasks:
    - name: Проверка наличия устройства
      stat:
        path: "{{ mount_device }}"
      register: device_check

    - name: Проверка текущего монтирования
      command: findmnt -no SOURCE "{{ mount_point }}"
      register: current_mount
      ignore_errors: yes
      changed_when: false

    - name: Остановка служб логирования
      systemd:
        name: "{{ item }}"
        state: stopped
      loop:
        - rsyslog.service
        - systemd-journald.service

    - name: Создание временной точки монтирования
      file:
        path: /mnt
        state: directory
        mode: '0755'

    - name: Монтирование нового раздела
      mount:
        path: /mnt
        src: "{{ mount_device }}"
        fstype: "{{ fstype }}"
        state: mounted

    - name: Копирование данных с верификацией
      command: rsync -aAXv {{ mount_point }}/ /mnt/

    - name: Проверка количества файлов
      command: "{{ item }}"
      register: file_counts
      loop:
        - "find {{ mount_point }} -type f | wc -l"
        - "find /mnt -type f | wc -l"
      until: file_counts.results[0].stdout == file_counts.results[1].stdout
      retries: 5
      delay: 10

    - name: Резервирование старого каталога
      command: mv {{ mount_point }} {{ mount_point }}.old
      args:
        removes: "{{ mount_point }}"

    - name: Создание новой точки монтирования
      file:
        path: "{{ mount_point }}"
        state: directory
        mode: '0755'

    - name: Получение UUID устройства
      command: lsblk -dno UUID {{ mount_device }}
      register: device_uuid
      changed_when: false

    - name: Добавление в fstab
      lineinfile:
        path: /etc/fstab
        line: "UUID={{ device_uuid.stdout }} {{ mount_point }} {{ fstype }} {{ mount_opts }} 0 2"
        create: yes

    - name: Перезагрузка systemd daemon
      systemd:
        daemon_reload: yes

    - name: Монтирование нового раздела
      mount:
        path: "{{ mount_point }}"
        src: "UUID={{ device_uuid.stdout }}"
        fstype: "{{ fstype }}"
        opts: "{{ mount_opts }}"
        state: mounted

    - name: Восстановление контекстов SELinux
      command: restorecon -Rv {{ mount_point }}
      when: ansible_selinux.status == "enabled"

    - name: Запуск служб логирования
      systemd:
        name: "{{ item }}"
        state: started
      loop:
        - systemd-journald.service
        - rsyslog.service

    - name: Удаление резервной копии (опционально)
      file:
        path: "{{ mount_point }}.old"
        state: absent
      when: cleanup_old_data | default(false)
```

## Shell-скрипт (идемпотентный)

```bash
#!/usr/bin/env bash
set -euo pipefail

MOUNT_DEVICE="/dev/sdb1"
MOUNT_POINT="/var/log"
TEMP_MOUNT="/mnt"
FSTYPE="ext4"
MOUNT_OPTS="defaults,noatime,nosuid,nodev,noexec"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Проверка прав
if [[ $EUID -ne 0 ]]; then
    log_error "Запустите скрипт с sudo или от root"
    exit 1
fi

# 1. Проверка SMART
log_info "Проверка SMART..."
if ! smartctl -H "$MOUNT_DEVICE" | grep -q "PASSED"; then
    log_error "SMART проверка не пройдена. Прервано."
    exit 1
fi

# 2. Проверка пространства
log_info "Проверка пространства..."
SOURCE_SIZE=$(sudo du -sm "$MOUNT_POINT" | cut -f1)
TARGET_AVAILABLE=$(df -m "$TEMP_MOUNT" | awk 'NR==2 {print $4}')
if [[ $TARGET_AVAILABLE -lt $((SOURCE_SIZE * 120 / 100)) ]]; then
    log_error "Недостаточно места на целевом разделе. Нужно: $((SOURCE_SIZE * 120 / 100)) MB, доступно: $TARGET_AVAILABLE MB"
    exit 1
fi

# 3. Проверка процессов
log_info "Поиск процессов в $MOUNT_POINT..."
PIDS=$(sudo fuser -vm "$MOUNT_POINT" 2>/dev/null | grep -oP '\d+(?=c|\d+w)' || true)
if [[ -n "$PIDS" ]]; then
    log_warn "Найдены процессы, использующие $MOUNT_POINT: $PIDS"
    read -p "Остановить службы логирования? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo systemctl stop rsyslog.service systemd-journald.service
    else
        log_error "Прервано пользователем."
        exit 1
    fi
fi

# 4. Монтирование и копирование
log_info "Монтирование $MOUNT_DEVICE в $TEMP_MOUNT..."
sudo mount "$MOUNT_DEVICE" "$TEMP_MOUNT"

log_info "Копирование данных (это может занять время)..."
sudo rsync -aAXv "$MOUNT_POINT/" "$TEMP_MOUNT/"

# 5. Верификация
log_info "Верификация..."
SOURCE_COUNT=$(sudo find "$MOUNT_POINT" -type f | wc -l)
TARGET_COUNT=$(sudo find "$TEMP_MOUNT" -type f | wc -l)
if [[ $SOURCE_COUNT -ne $TARGET_COUNT ]]; then
    log_error "Количество файлов не совпадает: $SOURCE_COUNT vs $TARGET_COUNT"
    exit 1
fi
log_info "Количество файлов совпадает: $SOURCE_COUNT"

# 6. Переключение
UUID=$(lsblk -dno UUID "$MOUNT_DEVICE")
FSTAB_ENTRY="UUID=$UUID $MOUNT_POINT $FSTYPE $MOUNT_OPTS 0 2"

log_info "Резервирование $MOUNT_POINT..."
sudo mv "$MOUNT_POINT" "${MOUNT_POINT}.old"
sudo mkdir "$MOUNT_POINT"

log_info "Добавление в fstab..."
echo "$FSTAB_ENTRY" | sudo tee -a /etc/fstab

log_info "Монтирование нового раздела..."
sudo systemctl daemon-reload
sudo mount "$MOUNT_POINT"

# 7. Восстановление контекстов
log_info "Восстановление контекстов SELinux..."
sudo restorecon -Rv "$MOUNT_POINT" || true

# 8. Запуск служб
log_info "Запуск служб логирования..."
sudo systemctl start systemd-journald.service rsyslog.service

log_info "Проверка статуса..."
sudo systemctl status rsyslog.service --no-pager

log_info "Миграция завершена успешно!"
log_info "Резервная копия сохранена в ${MOUNT_POINT}.old"
log_info "Удалите её через 7 дней после подтверждения работоспособности:"
log_info "  sudo rm -rf ${MOUNT_POINT}.old"
```

## Puppet

```puppet
mount { '/var/log':
  ensure  => 'mounted',
  device  => '/dev/sdb1',
  fstype  => 'ext4',
  options => 'defaults,noatime,nosuid,nodev,noexec',
  remounts => true,
}

# Копирование данных через exec
exec { 'migrate_var_log':
  command     => '/usr/bin/rsync -aAXv /var/log.old/ /var/log/',
  refreshonly => true,
  subscribe   => Mount['/var/log'],
  require     => Exec['backup_var_log'],
}

exec { 'backup_var_log':
  command => '/bin/mv /var/log /var/log.old',
  creates => '/var/log.old',
}
```

## Chef

```ruby
mount '/var/log' do
  device '/dev/sdb1'
  fstype 'ext4'
  options ['defaults', 'noatime', 'nosuid', 'nodev', 'noexec']
  action [:mount, :enable]
end

# Копирование данных
execute 'migrate /var/log' do
  command 'rsync -aAXv /var/log.old/ /var/log/'
  action :nothing
  subscribes :run, "mount[/var/log]", :immediately
end
```

# Диагностика и решение проблем

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **`target is busy`** | Процесс удерживает каталог или CWD внутри | `sudo fuser -km /var/log` или `sudo lsof +D /var/log` |
| **`Permission denied` при rsync** | Недостаточно прав для чтения исходных файлов | Запустите rsync с `sudo` |
| **`No space left on device`** | Недостаточно места на целевом разделе | `df -h /mnt`, проверьте inodes `df -i /mnt` |
| **`SELinux policy prevents...`** | Неправильные контексты безопасности | `sudo restorecon -Rv /var/log` |
| **`Stale file handle` после миграции** | Открытые дескрипторы указывают на старый inode | Перезапустите сервисы, использующие каталог |
| **Потеря данных при откате** | Оригинальный каталог удален вместо переименования | Используйте `mv`, а не `rm` в процессе миграции |
| **`mount: wrong fs type`** | Целевое устройство не имеет ФС или повреждено | `sudo mkfs.ext4 /dev/sdb1` (данные будут утеряны!) |
| **Данные пишутся в старый каталог** | Bind mount или fstab не настроен | `findmnt /var/log` для проверки точки монтирования |

## Поиск процессов, блокирующих откат

```bash
# Поиск процессов, удерживающих каталог
sudo lsof +D /var/log.old

# Принудительное завершение (ОПАСНО — может привести к потере данных)
sudo fuser -km /var/log.old
```

## Восстановление после сбоя

Если миграция прервана на этапе переключения:
```bash
# Проверка, что старая точка монтирования активна
findmnt /var/log

# Если нет — быстрый откат
sudo umount /var/log || true
sudo mv /var/log /var/log.new
sudo mv /var/log.old /var/log
sudo mount /var/log
```

## Проверка целостности данных

```bash
# Проверка файлов на наличие повреждений (если ФС поддерживает)
sudo fsck.ext4 -n /dev/sdb1

# Для XFS (только на смонтированной ФС)
sudo xfs_check /dev/sdb1
```

## Очистка после успешной миграции

```bash
# Удаление резервной копии через 7 дней
sudo rm -rf /var/log.old

# Или перемещение на внешний носитель для архивации
sudo tar -czf /backup/var_log_backup.tar.gz /var/log.old
sudo rm -rf /var/log.old
```

# Удаление миграции и откат

## Полный откат к исходному состоянию

```bash
# 1. Остановка сервисов
sudo systemctl stop rsyslog.service systemd-journald.service

# 2. Размонтирование нового раздела
sudo umount /var/log

# 3. Удаление из fstab
sudo sed -i '/UUID=.* \/var.log /d' /etc/fstab
sudo systemctl daemon-reload

# 4. Удаление новой точки монтирования
sudo rmdir /var/log

# 5. Восстановление старого каталога
sudo mv /var/log.old /var/log

# 6. Запуск сервисов
sudo systemctl start rsyslog.service systemd-journald.service
```

## Очистка диска

```bash
# Полное удаление данных с диска (если он больше не нужен)
sudo wipefs -a /dev/sdb1
sudo blkdiscard /dev/sdb1  # Для SSD
```

# Дополнительная информация

*   **[Конфигурация fstab](../fstab.md)** — описание опций монтирования и параметров проверки.
*   **[Сценарий базовой разметки](./basic_partition.md)** — подготовка физического диска (GPT, MBR).
*   **[Управление LVM](../../LVM/overview_concepts.md)** — создание и расширение логических томов.
*   **[SELinux: Механизмы и настройка](../../../Security/Mechanisms/SELinux.md)** — работа с контекстами безопасности при переносе данных.
*   **[Диагностика дискового пространства](../../../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md)** — поиск "тяжелых" каталогов через `du` и `ncdu`.
*   **[Mount Namespaces](../../../Virtualization/mount_namespaces.md)** — изоляция монтирований в контейнерах.
*   **[Перемонтирование (Remount)](../remount.md)** — изменение опций монтирования без размонтирования.
*   **[Специальные типы монтирования](../index.md)** — обзор bind mount, loop mount, OverlayFS, tmpfs.
