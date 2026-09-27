# Управление правами файлов: Краткая справка

## Определения

**Управление правами** — практическая деятельность по настройке доступа к ресурсам файловой системы (файлам, директориям, устройствам) с использованием стандартных и расширенных механизмов Linux.

**Umask (User File-Creation Mask)** — системная маска, определяющая биты прав доступа, которые будут **автоматически сброшены** (запрещены) при создании новых объектов в текущей сессии.

**DAC (Discretionary Access Control)** — модель дискреционного контроля доступа, реализуемая через биты `rwx` для владельца, группы и остальных. Подробнее: **[обзор прав доступа](./overview_definitions.md)**.

## Базовые концепции

### Матрица ответственности

| Действие | Кто может | Команда |
| :--- | :--- | :--- |
| Изменить права | Владелец файла или `root` | `chmod` |
| Сменить владельца | Только `root` | `chown` |
| Сменить группу | Владелец (если состоит в целевой группе) или `root` | `chgrp`, `chown` |

**Важно:** `root` (UID 0) обходит большинство проверок DAC. Любые операции с правами на системных объектах требуют `sudo`.

## Стандартные права для типовых объектов

| Объект | Директории | Файлы | Примечание |
| :--- | :--- | :--- | :--- |
| Системные бинарники | `755` | `755` | Выполнение для всех |
| Системные конфиги | `755` | `644` | Запись только для root |
| Секретные ключи (SSH, TLS) | `700` | `600` | Никто кроме владельца |
| Домашние директории | `750` | `644` | Групповой доступ |
| Общие папки команды | `2770` + SGID | `660` | Наследование группы |
| Логи приложений | `750` | `640` | Группа `adm`/`root` |
| Временные файлы (tmp) | `1777` | `600` | Sticky Bit |
| Веб-контент | `755` | `644` | Запись только для www-data |
| База данных (PG/MySQL) | `700` | `600` | Только служебный пользователь |

## Практические сценарии

### 1. Просмотр метаданных (ls, stat)

```bash
# Базовая информация (права, владелец, группа)
ls -l file.txt

# Информация с числовыми UID/GID (полезно при отладке NFS/контейнеров)
ls -ln file.txt

# Вывод прав в восьмеричном формате
stat -c "%a %A %n" file.txt
# → 644 -rw-r--r-- file.txt

# Полная информация из inode (atime, mtime, ctime, Birth)
stat file.txt

# Только числовые права и имя
stat -c "%a %U %G %n" /etc/passwd
# → 644 root root /etc/passwd

# Проверка, является ли файл симлинком
ls -lL file.txt
```

### 2. Изменение прав (chmod)

```bash
# Символьный режим (u - user, g - group, o - others, a - all)
chmod u+x,go-w script.sh

# Числовой режим (r=4, w=2, x=1)
chmod 755 script.sh       # rwxr-xr-x (стандарт для бинарников)
chmod 600 secret.key      # rw------- (стандарт для приватных ключей)

# Рекурсивное изменение (используйте с осторожностью!)
chmod -R 755 /var/www/html

# Рекурсивное изменение: директории 755, файлы 644
find /var/www/html -type d -exec chmod 755 {} +
find /var/www/html -type f -exec chmod 644 {} +

# Снятие SUID-бита без изменения остальных прав
chmod u-s /usr/local/bin/custom_tool
```

### 3. Смена владельца и группы (chown, chgrp)

```bash
# Смена владельца
sudo chown dev_user app.log

# Смена группы
sudo chgrp dev_team app.log

# Владелец и группа в одну команду
sudo chown dev_user:dev_team app.log

# Установка владельца и его основной группы (из /etc/passwd)
sudo chown bob: file.txt

# Рекурсивная смена владельца всей директории
sudo chown -R www-data:www-data /var/www/site

# Массовая смена группы по маске
sudo find /srv/projects -type f -user deploy -exec chown deploy:developers {} +

# Смена только группы (владелец остается)
sudo chgrp -R developers /srv/projects
```

### 4. Копирование с сохранением прав (cp, rsync)

```bash
# Копирование с сохранением владельца, группы, прав и временных меток
cp -a /src/app/ /dst/app/

# Копирование с сохранением прав (без hardlinks)
cp -rp /src/app/ /dst/app/

# Rsync с сохранением прав (рекомендуется для деплоя)
rsync -avz --delete /src/app/ user@host:/dst/app/

# Rsync только изменения прав
rsync -avz --chmod=Du=rwx,Dg=rx,Do=,Fu=rw,Fg=r,Fo= /src/ /dst/

# Проверка результата
stat -c "%a %U %G %n" /dst/app/config.yaml
```

### 5. Создание объектов с заданными правами (install)

Утилита `install` объединяет `cp`, `chmod` и `chown` в один шаг. Рекомендуется для скриптов установки и деплоя.

```bash
# Создание директории с правами 700
install -d -m 700 /home/user/private_dir

# Копирование файла с установкой владельца и прав
sudo install -o root -g root -m 644 my_service.conf /etc/my_service.conf

# Установка скрипта с владельцем root и правом выполнения
sudo install -o root -g root -m 755 deploy.sh /usr/local/bin/deploy.sh
```

### 6. Настройка umask

Расчет: `Base (666/777) - umask = Result`.

| Маска | Файлы | Директории | Сценарий |
| :--- | :--- | :--- | :--- |
| `0022` | `644` | `755` | Стандарт (владелец — всё, остальные — чтение) |
| `0027` | `640` | `750` | Групповой доступ, остальные исключены |
| `0077` | `600` | `700` | Максимальная приватность (только владелец) |

```bash
# Установка в символьном режиме (права, которые ОСТАЮТСЯ)
umask u=rwx,g=rx,o=   # Аналог 0027

# Проверка текущего значения
umask
# → 0022

# Постоянная настройка для shell: добавить в ~/.bashrc
# umask 0027

# Настройка через systemd unit
# /etc/systemd/system/myapp.service
# [Service]
# UMask=0077
# User=myapp

# Проверка примененной маски в systemd
systemctl show myapp.service -p UMask
# → UMask=0077

# Глобальная настройка для новых пользователей
# /etc/login.defs
# UMASK 027
```

### 7. Поиск и аудит (find)

```bash
# Поиск файлов с SUID-битом
find /usr/bin -type f -perm /4000

# Поиск файлов, доступных для записи всем (world-writable) — риск безопасности
find / -type f -perm -0002 -ls 2>/dev/null

# Поиск файлов с точным соответствием прав (644)
find . -type f -perm 644

# Поиск по владельцу
find /var/www -type f -user www-data

# Поиск по группе
find /srv -type f -group developers

# Поиск директорий без права на вход для остальных
find /home -type d -perm -o=x ! -perm -o=w

# Поиск файлов, не изменявшихся более 90 дней (очистка кэша)
find /var/cache -type f -atime +90

# Поиск файлов, изменённых за последние 24 часа (аудит)
find /etc -type f -mtime -1

# Рекурсивный поиск файлов с SUID/SGID (аудит безопасности)
find / -xdev -type f \( -perm -4000 -o -perm -2000 \) -exec ls -ld {} \; 2>/dev/null

# Поиск world-writable директорий без Sticky Bit (риск)
find / -xdev -type d -perm -0002 ! -perm -1000 -ls 2>/dev/null
```

### 8. Массовое применение прав

```bash
# Директории → 755, файлы → 644 (веб-проект)
find /var/www/html -type d -exec chmod 755 {} +
find /var/www/html -type f -exec chmod 644 {} +

# Смена владельца только для файлов определённого владельца
sudo find /srv -type f -user deploy -exec chown deploy:www-data {} +

# Создание структуры директорий с SGID и default ACL
sudo find /srv/projects -type d -exec chmod 2775 {} +
sudo find /srv/projects -type d -exec setfacl -d -m g:developers:rwx {} +

# Удаление всех ACL рекурсивно
sudo find /srv -exec setfacl -b {} +

# Рекурсивная с immutable на системные файлы (осторожно!)
# sudo find /etc/critical -type f -exec chattr +i {} +
```

### 9. Диагностика типичных проблем

```bash
# Проблема: chmod/chown не применяется
# 1. Проверить, не immutable ли файл
lsattr /path/to/file
# → ----i-------- /path/to/file
# Решение: sudo chattr -i /path/to/file

# 2. Проверить, не смонтирован ли раздел с nosuid/nodev/noexec/ro
findmnt -T /path/to/file
# → /dev/sda1 / ext4 ro,noatime 0 0
# Решение: перемонтировать с rw или исправить fstab

# 3. Проверить, нет ли SELinux/AppArmor блокировки
ls -Z /path/to/file
sudo ausearch -m avc -ts recent | grep /path/to/file

# 4. Проверить цепочку директорий
namei -l /path/to/file

# Проблема: "Permission denied" при выполнении скрипта
# 1. Проверить права на скрипт
ls -l deploy.sh
# → -rw-r--r-- (нет x!)
chmod +x deploy.sh

# 2. Проверить shebang и CRLF
head -1 deploy.sh | cat -A
# → #!/bin/bash$  (правильно)
# → #!/bin/bash^M$ (проблема — запустить dos2unix deploy.sh)

# 3. Проверить, не смонтирован ли раздел с noexec
findmnt -T deploy.sh

# Проблема: SUID-бит не действует
# 1. Проверить, есть ли право x у владельца
ls -l /usr/bin/passwd
# → -rwsr-xr-x (правильно)
# → -rwSr-xr-x (проблема — заглавная S, нет x)
chmod u+x /usr/bin/passwd

# 2. Проверить опции монтирования
mount | grep -E '(nosuid|noexec)' /usr

# 3. Проверить, является ли файл скриптом (SUID игнорируется для #! интерпретаторов)
file /usr/bin/passwd
```

### 10. Права для DevOps-инструментов

```bash
# SSH-ключи (обязательные права)
chmod 700 ~/.ssh/
chmod 600 ~/.ssh/id_ed25519
chmod 644 ~/.ssh/id_ed25519.pub
chmod 600 ~/.ssh/config
chmod 600 ~/.ssh/authorized_keys

# Git hooks
chmod +x .git/hooks/pre-commit
chmod +x .git/hooks/post-commit

# Docker volumes на хосте
sudo chown -R 1000:1000 /var/lib/docker/volumes/myapp_data/_data
sudo chmod 755 /var/lib/docker/volumes/myapp_data/_data

# Проверка прав в контейнере
docker exec myapp stat -c "%a %U %G %n" /app/config.yml

# Ansible: права на удалённые файлы
# ansible.builtin.file:
#   path: /etc/myapp.conf
#   mode: '0600'
#   owner: root
#   group: root
```

### 11. Работа с ACL (setfacl/getfacl)

```bash
# Назначить права пользователю и группе
sudo setfacl -m u:john:rw-,g:devs:r-- /app/config.yml

# Default ACL для наследования в директории
sudo setfacl -d -m u::rwx,g::rwx,o::--- /srv/projects/shared

# Просмотр ACL
getfacl /app/config.yml

# Удаление ACL (возврат к стандартной модели DAC)
sudo setfacl -b /app/config.yml
```

### 12. Атрибуты файловой системы (chattr)

```bash
# Защита от изменения (даже для root)
sudo chattr +i /etc/passwd
sudo chattr +i /etc/shadow

# Append-only для логов
sudo chattr +a /var/log/nginx/access.log

# Просмотр атрибутов
lsattr /etc/passwd
# → ----i-------- /etc/passwd

# Снятие атрибута
sudo chattr -i /etc/passwd
```

## Дополнительная информация

*   **Специальные биты:** Подробно про SUID, SGID и Sticky Bit — **[специальные права доступа](./special_permissions.md)**.
*   **ACL и Атрибуты:** Настройка `setfacl` и `chattr +i` — **[ACL, атрибуты и временные метки](./acl_immutable_timestamps.md)**.
*   **Диагностика:** Если `chmod 777` не помогает — **[Чек-лист диагностики прав доступа](./overview_definitions.md#чек-лист-диагностики)**.
*   **Контейнеры:** Особенности `COPY --chown` в Docker — **[Инструкции Dockerfile](../../../../Docker/Dockerfile/Instructions/copying_files.md)**.
*   **Теория DAC/MAC:** Подробный обзор моделей, ограничений и LSM — **[обзор прав доступа](./overview_definitions.md)**.
*   **User Namespace:** Изоляция UID/GID в контейнерах — **[обзор прав доступа](./overview_definitions.md#практические-сценарии-user-namespaces-и-контейнерная-безопасность)**.
*   **Linux Capabilities:** Гранулярные привилегии вместо SUID — **[обзор прав доступа](./overview_definitions.md#linux-capabilities-гранулярные-привилегии)**.

### См. также
* [Управление пользователями и группами](../../../../Linux/SystemAdministration/users_management.md) — создание UID и GID.
* [Индексы файловой системы (Inode)](../../../../Linux/FileSystems/links_inodes_dentries.md) — как хранятся права на диске.
* [Hardening контейнеров](../../../../Docker/Docker_security/container_hardening.md) — `no-new-privileges`, `cap-drop`, AppArmor/SELinux в контейнерах.
* [Конфигурация systemd](../../../../Linux/Core/systemd/systemd_units_overview.md) — `UMask=`, `NoNewPrivileges=`, `RestrictSUIDSGID=`.
* [Git hooks](../../../../Git/git_hooks.md) — права на хуки и деплой-скрипты.
