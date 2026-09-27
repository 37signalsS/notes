# ACL, атрибуты и временные метки файлов в Linux

## Определения

**Списки контроля доступа (Access Control Lists, ACL)** — расширенный механизм управления правами доступа, который дополняет стандартную модель DAC (Discretionary Access Control). ACL позволяют назначать гранулярные разрешения (чтение, запись, выполнение) для любого произвольного пользователя или группы, снимая ограничение классической триады «владелец-группа-остальные».

**Атрибуты файлов (File Attributes)** — специфические флаги уровня файловой системы (например, `immutable`, `append-only`), которые управляют поведением ядра при работе с объектом. Атрибуты имеют приоритет над правами доступа и действуют даже на суперпользователя **root**.

**Расширенные атрибуты (Extended Attributes, xattr)** — механизм хранения дополнительных метаданных файла в формате `ключ=значение`. На xattr базируются ACL, метки безопасности (SELinux), а также проверка целостности метаданных (EVM).

**Временные метки (Timestamps)** — данные в индексном дескрипторе (inode), фиксирующие время доступа, модификации содержимого и изменения статуса/метаданных файла.

## Основные концепции

### 1. Поддержка ACL и xattr

Для работы ACL файловая система должна быть смонтирована с поддержкой расширенных атрибутов и ACL. В современных дистрибутивах (Debian, RHEL, Ubuntu) на ФС `ext4` и `xfs` это включено по умолчанию.

**Проверка и включение:**
```bash
# Проверка опций монтирования
mount | grep acl

# Если поддержка не активна (для старых систем), перемонтировать:
sudo mount -o remount,acl /home
```
В файле `/etc/fstab` опция указывается в колонке параметров: `defaults,acl`.

### 2. Списки контроля доступа (ACL)

Наличие ACL у файла обозначается символом `+` в выводе `ls -l` (например, `-rw-r--r--+`).

*   **Access ACL:** права на конкретный файл или директорию.
*   **Default ACL:** настраивается только для директорий. Определяет права, которые будут автоматически наследоваться всеми новыми объектами внутри этой директории.
*   **Mask (Маска):** определяет **максимально возможные права** для всех именованных пользователей и групп (кроме владельца и категории `other`).
    *   *Логика:* Эффективные права пользователя = `Права_в_ACL` AND `Маска`.
    *   *Пример:* Если пользователю даны `rw-`, а маска установлена в `r--`, его эффективные права будут только `r--`.
    *   *Важно:* Маска влияет только на именованных пользователей и группы. Владелец (`user::`) и категория `other::` не ограничиваются маской.
    *   *Изменение маски:* `setfacl -m m:rwx <file>` — изменяет маску. При создании нового ACL-записи маска автоматически пересекается с текущим значением.

#### Структура ACL (порядок записей)

```
user::rw-          # Владелец (из стандартных прав)
user:john:r--      # Именованный пользователь
group::r--         # Основная группа
group:devs:rw-     # Именованная группа
mask::rwx          # Маска (ограничивает user:john и group:devs)
other::---         # Остальные (из стандартных прав)
```

#### Взаимодействие ACL с стандартными правами (DAC)

- Права `_owner` из стандартных прав и `user::` в ACL **всегда совпадают**.
- Права `_group` из стандартных прав и `group::` в ACL **всегда совпадают**.
- Категория `other::` в ACL **всегда совпадает** с `o=` из стандартных прав.
- При изменении стандартных прав (`chmod`) маска ACL **автоматически пересекается** с новым значением. Например, `chmod g+r` добавит чтение в маску, но `chmod g-w` уберёт запись из маски.

#### Проверка эффективных прав

```bash
# Проверить, какие права действительно будет иметь пользователь
getfacl <file>

# Для директорий — учитывать наследование по умолчанию
getfacl -d <dir>  # Default ACL
```

#### Пример вывода getfacl
```bash
getfacl myfile.txt
# file: myfile.txt
# owner: admin
# group: staff
user::rw-              # Права владельца
user:john:r--          # Права конкретного пользователя john
group::r--             # Права основной группы
mask::r--              # Текущая маска
other::---             # Права остальных
```

### 3. Атрибуты файловой системы (chattr)

Атрибуты жестко ограничивают операции с файлом на уровне ядра Linux. Они хранятся в inode и обрабатываются до проверок прав доступа (DAC) и SELinux/AppArmor.

#### Таблица атрибутов ext4 (поддерживаемых ядром)

| Атрибут | Название | Эффект | Сценарий |
| :--- | :--- | :--- | :--- |
| `i` | **immutable** | Запрет на изменение, удаление, переименование, создание ссылок. Действует и на root. | Защита `/etc/passwd`, бинарных файлов. |
| `a` | **append-only** | Разрешена только дозапись в конец файла. Запрещено удаление/перезапись. | Защита системных логов. |
| `A` | **noatime** | Не обновлять время последнего доступа (`atime`). | Оптимизация нагрузки на SSD/БД. |
| `d` | **nodump** | Файл игнорируется утилитой резервного копирования `dump`. | Исключение временных данных из бэкапа. |
| `s` | **secure deletion** | При удалении блоки данных затираются нулями. | Гарантированное уничтожение данных. |
| `u` | **undeletable** | При удалении данные сохраняются для возможностивосстановления. | Защита от случайного удаления. |
| `C` | **copy-on-write** | Для ext4 с `project` — копирование при записи. | Используется в QEMU/VM. |
| `E` | **compression** | Данные сжимаются при записи (ext4). | Экономия места. |
| `I` | **hashed directory** | Используется для больших директорий (ext4). | Оптимизация поиска. |
| `j` | **journaling** | Данные уже прошли через journal. | Внутреннее состояние ext4. |
| `J` | **no journal** | Отключить journal для этого файла. | Редко, только для специфических сценариев. |
| `t` | **tail packing** | Для ext3/4 — объединение с конца блока. | Внутреннее состояние ext4. |
| `T` | **top of directory hierarchy** | Оптимизация для catdir. | Внутреннее состояние ext4. |
| `X` | **dump raw** | `dump` копирует данные даже без атрибута `d`. | Внутреннее состояние ext4. |

#### Поддержка по ФС

| ФС | `i` | `a` | `A` | `d` | `s` | `u` | Примечание |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| ext2/3/4 | + | + | + | + | + | + | Полная поддержка |
| XFS | + | + | - | - | - | - | Только `i`, `a` |
| Btrfs | + | + | - | - | - | + | `i`, `a`, `u` |
| tmpfs | - | - | - | - | - | - | Не поддерживаются |
| NFS | - | - | - | - | - | - | Не поддерживаются |

#### Поведение при монтировании

```bash
# Проверить текущие опции монтирования
mount | grep /etc
# → /dev/sda1 on / type ext4 (rw,relatime)

# Запретить изменение атрибутов через mount
# /etc/fstab: /dev/sda1 / ext4 defaults,noatime 0 1
```

#### Команды управления

*   `lsattr <file>` — просмотр атрибутов.
*   `lsattr -R <dir>` — рекурсивный поиск.
*   `sudo chattr +i <file>` — установить атрибут.
*   `sudo chattr -i <file>` — снять атрибут.
*   `sudo chattr +a <file>` — append-only.
*   `sudo chattr -R +i <dir>` — рекурсивно установить immutable.

#### Приоритет атрибутов

```
Атрибуты (chattr) > SELinux/AppArmor > DAC (права доступа) > FUSE/сетевые ФС
```

- `immutable` (`+i`) **блокирует** `write`, `unlink`, `rename`, `link`, `chmod`, `chown`, `setxattr` — даже для root.
- `append-only` (`+a`) **блокирует** `write` с позиции ≠ конца, `truncate`, `unlink`, `rename`.
- Атрибуты **не влияют** на `read` — чтение всё ещё возможно по стандартным правам.

### 4. Временные метки (stat)

Команда `stat` извлекает данные напрямую из inode:

*   **Access (atime):** время последнего чтения или запуска.
    *   *Оптимизация `relatime`:* ядро обновляет `atime`, только если старое значение меньше `mtime`/`ctime`, или если прошло более 24 часов.
    *   *Режимы atime:*
        - `relatime` (по умолчанию в большинстве дистрибутивов) — обновлять редко.
        - `strictatime` — всегда обновлять при каждом `read` (замедляет SSD/БД).
        - `noatime` — не обновлять вообще (оптимизация производительности).
        - `nodiratime` — не обновлять для директорий.
*   **Modify (mtime):** время последнего изменения **содержимого** файла.
    *   Обновляется при `write`, `truncate`, `append`.
    *   Не обновляется при `chmod`, `chown`, `rename`, `setxattr`.
*   **Change (ctime):** время последнего изменения **метаданных** или статуса (права, владелец, имя, атрибуты). `ctime` обновляется автоматически при любом изменении `mtime`.
    *   Обновляется при: `chmod`, `chown`, `chgrp`, `rename`, `unlink`, `link`, `setxattr`, `chattr`, `truncate`.
    *   `ctime` **никогда не уменьшается** — он монотонно возрастает.
*   **Birth (btime):** время создания файла. Поддерживается не всеми ФС (ext4, XFS, Btrfs поддерживают).
    *   Выводится через `stat` как `Birth:`.
    *   Через `debugfs` можно получить `crtime` даже если `stat` не показывает.

#### Режимы atime и производительность

```bash
# Проверить текущий режим
mount | grep " / "
# → /dev/sda1 on / type ext4 (rw,relatime,noatime)

# Изменить через fstab
# /etc/fstab: /dev/sda1 / ext4 defaults,noatime 0 1

# Изменить через mount (без перезагрузки)
sudo mount -o remount,noatime /

# Проверить生效
stat -c "%m %A" /  # %m — время модификации
```

#### Влияние atime на SSD и БД

- `atime` увеличивает количество `write` на SSD (каждое чтение → обновление inode).
- Для БД (PostgreSQL, MySQL) критично `noatime` — иначе every `SELECT` вызывает `write` в inode.
- Для лог-файлов важен `nodiratime` — не обновлять atime директорий.

#### Взаимодействие с NFS

- `atime` **не обновляется** на NFS-клиентах по умолчанию (оптимизация сети).
- `ctime` синхронизируется при `fsync` или `commit`.
- `btime` **не поддерживается** в NFS.

#### Различия mtime vs ctime — практическое значение

| Операция | mtime | ctime |
| :--- | :---: | :---: |
| `echo >> file` | + | + |
| `chmod u+x file` | - | + |
| `chown file` | - | + |
| `mv file file2` | - | + |
| `setfacl` | - | + |
| `chattr +i` | - | + |
| `truncate file` | + | + |

#### Извлечение Birth Time через debugfs (если stat не справляется)

```bash
# 1. Найти inode
ls -i myfile.txt  # -> 12345
# 2. Вызвать debugfs (нужны права root и путь к устройству)
sudo debugfs -R 'stat <12345>' /dev/sda1 | grep crtime
```

## Практические сценарии

### Управление ACL

#### 1. Назначение прав пользователю и группе
```bash
# Дать пользователю john права на чтение и запись
setfacl -m u:john:rw- myfile.txt

# Дать группе devs право на выполнение
setfacl -m g:devs:--x myfile.txt
```

#### 2. Наследование прав (Default ACL)
Для создания общей папки, где все новые файлы автоматически доступны группе `editors`:
```bash
sudo setfacl -d -m g:editors:rwX /mnt/data/shared
```
*(Флаг `X` — установить бит выполнения только если это директория или у файла уже есть бит выполнения).*

#### 3. Удаление ACL
```bash
setfacl -x u:john myfile.txt   # Удалить запись для пользователя john
setfacl -b myfile.txt         # Очистить все ACL (вернуть к стандартной модели)
```

#### 4. Практические сценарии: ACL в DevOps/SRE/Sysadmin

**Сценарий 4: Гранулярный доступ к конфигурационным файлам (Sysadmin)**
```bash
# Ситуация: БД и приложение должны читать конфиг, но не менять его
# Владелец: root, группа: app

# 1. Назначить права на чтение конкретным пользователям
sudo setfacl -m u:postgres:r--,u:www-data:r-- /etc/myapp/config.yaml

# 2. Проверить результат
sudo getfacl /etc/myapp/config.yaml
# → user:postgres:r--
# → user:www-data:r--

# 3. Убедиться, что пользователи могут читать
sudo -u postgres cat /etc/myapp/config.yaml
sudo -u www-data cat /etc/myapp/config.yaml

# 4. Убедиться, что не могут писать
sudo -u postgres touch /etc/myapp/config.yaml 2>&1
# → Permission denied
```

**Сценарий 5: Общая директория с наследованием прав (DevOps)**
```bash
# Создать проектную папку, где все новые файлы автоматически
# будут доступны группе разработчиков

# 1. Настроить Default ACL для директории
sudo setfacl -d -m u::rwx,g::rwx,o::--- /srv/projects/shared
sudo setfacl -d -m g:developers:rwx /srv/projects/shared

# 2. Проверить Default ACL
sudo getfacl -d /srv/projects/shared
# → default:user::rwx
# → default:group::rwx
# → default:group:developers:rwx
# → default:mask::rwx
# → default:other::---

# 3. Создать тестовый файл
touch /srv/projects/shared/test.txt
sudo getfacl /srv/projects/shared/test.txt
# → group:developers:rwx (автоматически!)

# 4. Удалить ACL при уборке
sudo setfacl -k /srv/projects/shared  # Удалить Default ACL
sudo setfacl -k -R /srv/projects/shared  # Рекурсивно
```

**Сценарий 6: Устранение проблем с ACL (SRE)**
```bash
# Проба: пользователь не может доступ к файлу, хотя права выглядят нормально

# 1. Проверить стандартные права
ls -l myfile.txt
# → -rw-r----- 1 root app 0 ... myfile.txt

# 2. Проверить, есть ли ACL (символ +)
ls -l myfile.txt
# → -rw-r-----+ 1 root app 0 ... myfile.txt  ← есть ACL!

# 3. Просмотреть ACL
sudo getfacl myfile.txt
# → user:hacker:r--  ← подозрная запись!
# → mask::r--
# → other::---

# 4. Проверить эффективные права
sudo -u alice stat myfile.txt  # alice не в ACL, но в группе app
# → Effective: r-- (ограничена маской)

# 5. Очистить подозрительные ACL
sudo setfacl -x u:hacker myfile.txt
sudo setfacl -m m:rwx myfile.txt  # Сбросить маску

# 6. Проверить, что ACL больше нет
ls -l myfile.txt
# → -rw-r----- 1 root app 0 ... myfile.txt  ← нет +
```

### Использование атрибутов для защиты

#### 1. Защита критической конфигурации
```bash
sudo chattr +i /etc/resolv.conf
# Теперь даже root не сможет изменить файл, пока не снимет атрибут через chattr -i
```

#### 2. Рекурсивная проверка атрибутов
```bash
lsattr -R /etc | grep "\-i\-"
```

#### 3. Практические сценарии: атрибуты в DevOps/SRE/Sysadmin

**Сценарий 7: защита системных логов от манипуляций (Sysadmin/SRE)**
```bash
# Ситуация: логи должны быть доступны для чтения, но не удаляться/изменяться

# 1. Установить append-only на лог-файл
sudo chattr +a /var/log/nginx/access.log
# → Дозапись возможна, удаление/перезапись запрещено

# 2. Проверить атрибут
lsattr /var/log/nginx/access.log
# → -----a------- /var/log/nginx/access.log

# 3. Попробовать перезаписать (должно провалиться)
sudo > /var/log/nginx/access.log 2>&1
# → Operation not permitted

# 4. Попробовать удалить (должно провалиться)
sudo rm /var/log/nginx/access.log 2>&1
# → Operation not permitted

# 5. Дозапись работает
echo "test" | sudo tee -a /var/log/nginx/access.log
# → Успешно

# 6. Снять атрибут при необходимости
sudo chattr -a /var/log/nginx/access.log
```

**Сценарий 8: защита критических файлов системы (Sysadmin)**
```bash
# Ситуация: предотвратить изменение системных файлов даже при компрометации root

# 1. Защитить ключевые файлы
sudo chattr +i /etc/passwd
sudo chattr +i /etc/shadow
sudo chattr +i /etc/sudoers
sudo chattr +i /etc/hosts
sudo chattr +i /etc/resolv.conf

# 2. Проверить, что атрибуты установлены
sudo lsattr /etc/passwd /etc/shadow /etc/sudoers
# → ----i------- /etc/passwd
# → ----i------- /etc/shadow
# → ----i------- /etc/sudoers

# 3. Попробовать изменить (должно провалиться)
sudo echo "hacked" >> /etc/passwd 2>&1
# → Operation not permitted

# 4. Попробовать удалить (должно провалиться)
sudo rm /etc/passwd 2>&1
# → Operation not permitted

# 5. Снять атрибут (только в аварийной ситуации)
sudo chattr -i /etc/passwd
```

**Сценарий 9: защита Docker-образов и volumes (SRE)**
```bash
# Ситуация: предотвратить случайное удаление данных контейнера

# 1. Проверить, есть ли immutable на данных
sudo lsattr /var/lib/docker/volumes/myapp_data/_data/

# 2. Защитить критические данные
sudo chattr +i /var/lib/docker/volumes/myapp_data/_data/config.json

# 3. Попробовать изменить из контейнера
docker exec myapp rm /data/config.json 2>&1
# → Permission denied (или Operation not permitted)

# 4. Проверить атрибут через stat
sudo stat /var/lib/docker/volumes/myapp_data/_data/config.json
# → Flags: i (immutable)
```

**Сценарий 10: оптимизация производительности через noatime (DevOps)**
```bash
# Ситуация: SSD-диск медленно из-за постоянного обновления atime

# 1. Проверить текущий режим
mount | grep " / "
# → /dev/sda1 on / type ext4 (rw,relatime)

# 2. Проверить количество write через iostat
iostat -x 1 | grep sda
# → w/s: 500 (высокий показатель из-за atime)

# 3. Включить noatime в fstab
# /etc/fstab:
# /dev/sda1 / ext4 defaults,noatime 0 1

# 4. Применить без перезагрузки
sudo mount -o remount,noatime /

# 5. Проверить результат
mount | grep " / "
# → /dev/sda1 on / type ext4 (rw,noatime)

# 6. Проверить, что atime больше не обновляется
touch test.txt
stat test.txt
# → Access: 2024-01-01 00:00:00.000000000 +0000  ← не изменилось
```

### Диагностика временных меток

#### Поиск файлов по времени доступа
Используется для очистки кэшей или поиска неиспользуемых данных:
```bash
find /path/to/dir -type f -atime +30  # Файлы, к которым не обращались более 30 дней
```

#### Извлечение Birth Time через debugfs (если stat не справляется)
```bash
# 1. Найти inode
ls -i myfile.txt  # -> 12345
# 2. Вызвать debugfs (нужны права root и путь к устройству)
sudo debugfs -R 'stat <12345>' /dev/sda1 | grep crtime
```

#### Практические сценарии: временные метки в DevOps/SRE/Sysadmin

**Сценарий 11: аудит изменений через ctime (Sysadmin/SRE)**
```bash
# Ситуация: нужно выяснить, кто и когда изменил конфиг

# 1. Найти файлы, изменённые за последние 24 часа
find /etc -type f -ctime -1 -ls 2>/dev/null

# 2. Найти файлы, изменённые конкретным пользователем
sudo find /var/log -type f -ctime -1 -user deploy 2>/dev/null

# 3. Отследить изменения через auditd
sudo ausearch -m avc -ts recent | grep /etc/nginx/nginx.conf

# 4. Проверить, изменилось ли содержимое или только метаданные
stat /etc/nginx/nginx.conf
# → Modify: 2024-01-15 10:30:00  (содержимое?)
# → Change: 2024-01-15 10:35:00  (метаданные?)
# Если Change > Modify — изменились права/владелец

# 5. Сравнить mtime и ctime
stat -c "%n mtime:%y ctime:%C" /etc/nginx/nginx.conf
# Если ctime новее mtime — изменялись метаданные
```

**Сценарий 12: очистка устаревших данных по atime (Sysadmin)**
```bash
# Ситуация: кэш разросся, нужно очистить неиспользуемые файлы

# 1. Просмотреть, какие файлы не использовались долго
find /var/cache -type f -atime +30 -ls 2>/dev/null | head -20

# 2. Удалить их (проверка через dry-run)
find /var/cache -type f -atime +30 -delete

# 3. Для safety — сначала вывести, потом удалять
find /var/cache -type f -atime +30 -print
# → /var/cache/app/file1.bin
# → /var/cache/app/file2.bin
# Проверить, что это не критично

# 4. Удалить
find /var/cache -type f -atime +30 -delete

# 5. Проверить, что освободилось место
df -h /
```

**Сценарий 13: диагностика инцидента через метаданные (SRE)**
```bash
# Ситуация: подозрение на компрометацию — нужно выяснить историю файла

# 1. Получить полную информацию о файле
stat /opt/myapp/bin/myapp
# → Access: (755/-rwxr-xr-x)  Uid: (1000/app)   Gid: (1000/app)
# → Size: 12345          Blocks: 24         IO Block: 4096  regular file
# → Device: 8,10          Inode: 1234567     Links: 1
# → Access: 2024-01-15 10:30:00.000000000 +0000
# → Modify: 2024-01-15 10:30:00.000000000 +0000
# → Change: 2024-01-15 10:35:00.000000000 +0000
# → Birth: 2024-01-10 09:00:00.000000000 +0000

# 2. Проверить, есть ли атрибуты
lsattr /opt/myapp/bin/myapp
# → ------- /opt/myapp/bin/myapp (нет атрибутов)

# 3. Проверить ACL
sudo getfacl /opt/myapp/bin/myapp
# → user::rwx
# → group::r-x
# → other::r-x

# 4. Проверить xattr (возможно, есть capabilities)
getfattr -d /opt/myapp/bin/myapp
# → security.capability="..."

# 5. Отследить изменения через auditd
sudo ausearch -f 1234567 -ts recent | tail -20
```

## Дополнительная информация

*   **Расширенные атрибуты (xattrs):** ACL хранятся в пространстве имен `system.posix_acl_access`. Для просмотра всех метаданных: `getfattr -d <file>`.
*   **Пространства имен xattr:**
    - `user.*` — пользовательские атрибуты (доступны по стандартным правам).
    - `system.*` — системные (ACL, capabilities, EVM).
    - `security.*` — метки безопасности (SELinux, Smack, capabilities).
    - `trusted.*` — только для root.
*   **Целостность данных:** Изменения атрибутов и ACL критичны для форензики. Рекомендуется мониторинг через **[Wazuh FIM](../file-integrity-checking.md)**.
*   **Аудит системных вызовов:** Отслеживание изменений через **[auditd](../../../SystemAdministration/Logging/auditd.md)** ( syscalls `setxattr`, `chmod`, `chown`).
*   **Связь с моделью прав:** ACL расширяют стандартную модель. Подробнее: **[обзор прав доступа (DAC)](./overview_definitions.md)**.
*   **Специальные режимы:** влияние SUID/SGID — **[специальные права](./special_permissions.md)**.

#### Интеграция с Ansible (DevOps)

```yaml
# Пример использования ACL и атрибутов в Ansible
- name: "Настроить доступ к конфигу через ACL"
  ansible.posix.acl:
    path: /etc/myapp/config.yaml
    entity: postgres
    etype: user
    permissions: r--
    state: present

- name: "Установить append-only на логи"
  ansible.builtin.file:
    path: /var/log/myapp/app.log
    mode: "644"
    attributes: "+a"  # append-only

- name: "Защитить критический файл"
  ansible.builtin.file:
    path: /etc/resolv.conf
    mode: "644"
    attributes: "+i"  # immutable
```

#### Чек-лист диагностики

| Команда | Объект проверки |
| :--- | :--- |
| `getfacl <file>` | Наличие расширенных правил ACL |
| `getfacl -d <dir>` | Default ACL для директории |
| `lsattr <file>` | Специфические атрибуты (например, `i` - immutable) |
| `lsattr -R <dir>` | Рекурсивная проверка атрибутов |
| `getfattr -d <file>` | Все расширенные атрибуты (xattr) |
| `stat <file>` | Полные метаданные (atime, mtime, ctime, btime) |
| `stat -c "%a %A %n" <file>` | Права в восьмеричном и символьном виде |
| `find <path> -type f -perm -0002` | Поиск world-writable файлов |
| `find <path> -type f -atime +30` | Неиспользуемые файлы |
| `mount \| grep acl` | Поддержка ACL на уровне монтирования |

### См. также
* [Проверка целостности файлов в Linux](../file-integrity-checking.md) — мониторинг изменений атрибутов.
* [fstab и опции монтирования](../../../FileSystems/mounting/fstab.md) — настройка `acl` и `noatime` на уровне ФС.
* [Индексы файловой системы (Inode)](../../../FileSystems/links_inodes_dentries.md) — структура хранения временных меток.
