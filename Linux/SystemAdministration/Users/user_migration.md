# Перенос пользователей между системами Linux

## Определения

- **Миграция пользователей** — комплексный процесс переноса учетных данных (логин, пароль, UID/GID), домашних директорий, системных квот и специфических настроек (например, subuid/subgid) между различными инстансами ОС Linux.
- **Идентификаторы (UID/GID)** — числовые значения, используемые ядром для идентификации владельца процесса или файла.
- **Remapping (Переназначение)** — процесс изменения UID/GID пользователя при миграции для предотвращения конфликтов с существующими учетными записями на целевой системе.
- **systemd-userdbd** — современный диспетчер (2025–2026), объединяющий данные пользователей из различных источников, обеспечивающий консистентность при использовании портативных аккаунтов.
- **`getent`** — утилита для запроса баз данных NSS (Name Service Switch). При миграции критично использовать `getent` вместо прямого чтения `/etc/passwd`, чтобы учитывать записи из LDAP/SSSD/systemd-homed.
- **`pwck`** — утилита проверки целостности `/etc/passwd` и `/etc/shadow` на дубликаты, битые ссылки и синтаксические ошибки.
- **`vipw`** — безопасное редактирование `/etc/passwd` с блокировкой файла от одновременных изменений.
- **`sss_override`** — утилита SSSD для экспорта/импорта локальных переопределений атрибутов пользователей при переходе на централизованный каталог.
- **`idmapd`** — демон NFSv4, отвечающий за сопоставление числовых UID/GID между клиентом и сервером. При миграции на NFS-инфраструктуру требует настройки `/etc/idmapd.conf`.
- **Атомарность миграции** — свойство операции, при котором либо все изменения (учетная запись + домашний каталог + метаданные) применяются полностью, либо не применяются вовсе. Критично для Production-сред.
- **Недеструктивная миграция** — метод, при котором исходная система остается работоспособной до момента завершения проверки на целевой системе.

## Базовые концепции

### Типы миграции

| Тип | Описание | Применимость |
| :--- | :--- | :--- |
| **Локальная (Imperial)** | Прямое копирование записей из `/etc/passwd`, `/etc/shadow`, `/etc/group`. | Малые системы, отсутствие домена. |
| **Декларативная** | Использование инструментов автоматизации (Ansible, SaltStack) для создания идентичных учетных записей. | Масштабируемые инфраструктуры. |
| **Портативная** | Использование механизмов **[systemd-homed](./systemd-homed.md)** (LUKS-образ). | Современные рабочие станции, серверы с systemd v245+. |
| **Централизованная** | Переход на сетевые службы каталогов (**[LDAP, SSSD](./LDAP_SSSD/index.md)**). | Корпоративные среды. |
| **Гибридная** | Сочетание локальных записей с централизованными атрибутами через `sss_override`. | Промежуточная стадия миграции. |

### Атомарность и недеструктивность

Миграция пользователя — не просто копирование файлов, а изменение состояния двух критичных ресурсов:
1. **Ядро (Kernel Credentials)** — запись в `/etc/passwd` определяет, кто имеет доступ к процессам и файлам.
2. **Файловая система (Inode Metadata)** — UID/GID хранятся в каждом inode. Простое копирование файлов через `cp` или `tar` без флага `--same-owner` приведет к потере владения.

**Правило:** Доменный пользователь (UID=1000) на исходной системе и тот же UID на целевой системе — это **разные** учетные записи, если GECOS, домашний каталог или пароль отличаются. Для ядра важен только числовой идентификатор.

### Ключевые риски и факторы (2026)

1.  **Конфликты идентификаторов:** Если UID на целевой системе занят, простая синхронизация файлов через `rsync` приведет к потере доступа или неверному наследованию прав.
2.  **Алгоритмы хэширования:** При переносе из старых систем (CentOS 7, `SHA512`) в современные (Ubuntu 24.04+, `YESCRYPT`) необходимо убедиться, что PAM на целевой системе поддерживает старый формат хэша.
3.  **Расширенные атрибуты:** Игнорирование SELinux-контекстов или ACL при копировании нарушит работу политик безопасности.
4.  **Дополнительные ID (subuid/subgid):** Для работы контейнеров (Podman, Docker Rootless) требуется обязательный перенос диапазонов из `/etc/subuid` и `/etc/subgid`.
5.  **NSS и кэши:** При миграции в домен (LDAP/SSSD) локальный пользователь может быть перекрыт записью из кэша. Используйте `getent passwd` для проверки фактического источника данных.
6.  **Живые процессы:** Миграция активного пользователя (с запущенными процессами, открытыми файлами) без предварительного завершения сессий приведет к утечкам дескрипторов и невозможности корректного завершения работы.
7.  **Сетевые файловые системы (NFS):** NFSv4 использует внутренний маппинг UID/GID через `idmapd`. При переносе данных между хостами убедитесь, что настройки `/etc/idmapd.conf` синхронизированы, иначе владельцы файлов будут отображаться как `nobody`.
8.  **Сервисные аккаунты:** Миграция системных пользователей (UID < 1000) требует дополнительной осторожности: необходимо сохранить UID, так как многие бинарные файлы имеют SUID-бит, привязанный к конкретному UID.

## Практические сценарии

### Подготовка и аудит (Pre-flight Checklist)

Перед началом миграции выполните полный аудит исходной системы:

```bash
# 1. Проверка доступности UID/GID на целевой системе
getent passwd <UID_OR_NAME>
getent group <GID_OR_NAME>

# 2. Проверка хэша пароля
# Убедитесь, что префикс в /etc/shadow (например, $y$ для yescrypt) поддерживается целевой ОС.
sudo awk -F: '$1 == "username" {print $2}' /etc/shadow

# 3. Проверка расширенных атрибутов (SELinux/ACL)
getfacl -R /home/username
ls -laZ /home/username

# 4. Проверка subuid/subgid диапазонов
grep "^username:" /etc/subuid
grep "^username:" /etc/subgid

# 5. Проверка активных процессов и сессий
loginctl list-sessions | grep username
ps -u username
```

### Метод 1: Ручной перенос (Классический)

Подходит для точечного переноса с полным контролем атрибутов.

#### Шаг 1: Экспорт данных на исходном сервере
```bash
export TARGET_USER="username"
grep "^${TARGET_USER}:" /etc/passwd > user_passwd.txt
sudo grep "^${TARGET_USER}:" /etc/shadow > user_shadow.txt
grep "^${TARGET_USER}:" /etc/group > user_group.txt

# Экспорт диапазонов для контейнеризации (обязательно!)
grep "^${TARGET_USER}:" /etc/subuid > user_subuid.txt || true
grep "^${TARGET_USER}:" /etc/subgid > user_subgid.txt || true

# Экспорт ACL (если используются)
getfacl -R /home/${TARGET_USER} > user_acl.txt

# Экспорт SELinux контекстов (если используется)
secon -r /home/${TARGET_USER} > user_selinux.txt 2>/dev/null || true
```

#### Шаг 2: Синхронизация файлов через rsync
Используйте флаги для сохранения всей метаинформации:
- `-a` (архивный режим), `-H` (жесткие ссылки), `-A` (ACL), `-X` (SELinux/xattrs).
```bash
rsync -aHAXz --progress /home/username/ root@new-server:/home/username/
```

**Пояснение флагов:**
- `-a`: рекурсивное копирование с сохранением прав, временных меток, симлинков
- `-H`: сохранение жестких ссылок
- `-A`: сохранение ACL
- `-X`: сохранение расширенных атрибутов (включая SELinux)
- `-z`: сжатие при передаче по сети
- `--progress`: отображение прогресса

#### Шаг 3: Импорт и корректировка прав
На целевом сервере:
```bash
sudo cat user_passwd.txt >> /etc/passwd
sudo cat user_shadow.txt >> /etc/shadow
sudo cat user_group.txt >> /etc/group
sudo cat user_subuid.txt >> /etc/subuid
sudo cat user_subgid.txt >> /etc/subgid

# Если UID изменился, выполните рекурсивную смену владельца
sudo chown -R username:username /home/username

# Восстановление ACL (если использовались)
setfacl --restore=user_acl.txt

# Проверка SELinux контекстов
restorecon -R /home/username
```

#### Шаг 4: Валидация
```bash
# Проверка входа
su - username -c "id && ls -la ~"

# Проверка SSH
sudo -u username ssh-keygen -l -f /home/username/.ssh/authorized_keys 2>/dev/null || true

# Проверка целостности баз
sudo pwck -r
sudo grpck -r
```

### Метод 2: Массовая миграция (newusers)

Утилита `newusers` принимает файл в формате `/etc/passwd`.

```bash
# Формат: username:passwd:UID:GID:GECOS:home:shell
# Пароли могут быть в открытом виде или в формате crypt
cat > users.txt << 'EOF'
dev1:x:2001:2001:Developer One:/home/dev1:/bin/bash
dev2:x:2002:2002:Developer Two:/home/dev2:/bin/bash
ops1:x:2003:2003:Ops Engineer:/home/ops1:/bin/bash
EOF

# Массовый импорт
sudo newusers < users.txt
```

**Важно:** `newusers` не поддерживает subuid/subgid и расширенные атрибуты. После выполнения необходимо:
1. Вручную добавить диапазоны в `/etc/subuid` и `/etc/subgid`.
2. Настроить ACL/SELinux контексты.
3. Для миграции данных используйте `rsync` с флагами `-aHAXz`.

### Метод 3: Перенос портативных аккаунтов (systemd-homed)

Самый быстрый метод для систем с `systemd-homed`. Подробное руководство: **[systemd-homed](./systemd-homed.md)**.

```bash
# Экспорт в зашифрованный tarball на источнике
sudo homectl export username /tmp/username.homedir

# Импорт на целевой системе
sudo homectl import username /tmp/username.homedir

# Импорт с переименованием
sudo homectl import new-username /tmp/username.homedir
```

**Ограничения:**
- Не поддерживает NFS в качестве хранилища.
- Root (UID 0) не может управляться через systemd-homed.
- При конфликте UID используйте `--uid-map=auto` для автоматического remapping.

### Метод 4: Перенос инфраструктурных компонентов

Не забудьте перенести сопутствующие данные:
- **Cron-задания**: `/var/spool/cron/crontabs/username` (Debian) или `/var/spool/cron/username` (RHEL).
- **Почта**: `/var/mail/username`.
- **Sudo-права**: Проверьте файлы в `/etc/sudoers.d/`.
- **Systemd-сервисы**: Пользовательские сервисы в `/etc/systemd/user/` и `~/.config/systemd/user/`.
- **SSH-ключи и known_hosts**: `/home/username/.ssh/`.
- **GPG-ключи**: `/home/username/.gnupg/`.
- **Docker/Podman конфиги**: `~/.docker/`, `~/.local/share/containers/`.
- **Веб-браузеры и приложения**: Профили в `~/.config/`, `~/.local/`.

### Метод 5: Декларативная миграция (Ansible)

Для массовых миграций используйте Ansible-плейбуки. Это обеспечивает идемпотентность и возможность повторного запуска.

```yaml
# tasks/users/migrate_user.yml
- name: Ensure user exists on target
  ansible.builtin.user:
    name: "{{ username }}"
    uid: "{{ uid }}"
    group: "{{ username }}"
    home: "/home/{{ username }}"
    shell: /bin/bash
    create_home: no

- name: Sync home directory
  ansible.builtin.synchronize:
    src: "/home/{{ username }}/"
    dest: "/home/{{ username }}/"
    recursive: yes
    archive: yes
    acls: yes
    xattrs: yes
    delete: no
  delegate_to: "{{ source_host }}"

- name: Fix ownership after sync
  ansible.builtin.file:
    path: "/home/{{ username }}"
    owner: "{{ username }}"
    group: "{{ username }}"
    recurse: yes

- name: Add subuid/subgid ranges
  ansible.builtin.lineinfile:
    path: "/etc/subuid"
    line: "{{ username }}:100000:65536"
    create: yes
  become: yes
```

### Метод 6: Миграция с использованием жестких ссылок (Hard Links)

Для больших домашних директорий (терабайты данных) используйте `rsync` с `--link-dest` для создания дедуплицированной копии. Это позволяет выполнить миграцию за минимальное время, а затем окончательно перенести данные при следующем запуске.

```bash
# Первый проход: создание жестких ссылок на уже существующие файлы
rsync -aHAXz --link-dest=/home/username /source/username/ /mnt/new_disk/username/

# Второй проход (после переноса): окончательная синхронизация
rsync -aHAXz --delete /source/username/ /home/username/
```

### Миграция сервисных аккаунтов

При переносе системных пользователей (например, `_nginx`, `postgres`) сохраните исходный UID, так как многие бинарные файлы имеют SUID-бит, привязанный к конкретному идентификатору.

```bash
# Проверка SUID-файлов, привязанных к пользователю
find / -uid 105 -perm -4000 2>/dev/null

# Миграция через useradd с явным указанием UID
sudo useradd -u 105 -g 105 -s /usr/sbin/nologin -c "Nginx Service" _nginx
```

### Живая миграция (Live Migration)

Для минимизации простоя используйте tmux/screen для сохранения сессий:

```bash
# На исходном сервере: сохранение сессий в tmux
tmux new-session -d -s migration 'bash --login'
tmux send-keys -t migration 'sudo systemctl stop sshd' Enter

# На новом сервере: запуск SSH на том же порту
# После обновления DNS/IP, пользователи автоматически подключаются к новому серверу
```

**Важно:** Живая миграция без остановки сервисов возможна только для идемпотентных операций (read-only). Любые изменения в `/etc/passwd` или `/etc/shadow` требуют перезагрузки NSS-кэша (sssd) или перелогина.

### Post-migration валидация

Автоматический скрипт проверки после миграции:

```bash
#!/bin/bash
# verify_migration.sh — пост-миграционная валидация
USERNAME=$1
TARGET_HOST=$2

echo "=== Проверка пользователя $USERNAME на $TARGET_HOST ==="

# 1. Проверка записи в NSS
ssh "$TARGET_HOST" "getent passwd $USERNAME"

# 2. Проверка UID/GID
ssh "$TARGET_HOST" "id $USERNAME"

# 3. Проверка домашней директории
ssh "$TARGET_HOST" "ls -la /home/$USERNAME"

# 4. Проверка прав на .ssh
ssh "$TARGET_HOST" "namei -mo /home/$USERNAME/.ssh/authorized_keys"

# 5. Проверка входа
ssh "$TARGET_HOST" "su - $USERNAME -c 'echo Login OK'"

# 6. Проверка subuid/subgid
ssh "$TARGET_HOST" "grep ^$USERNAME: /etc/subuid /etc/subgid"

echo "=== Валидация завершена ==="
```

## Глубокое переназначение (System-wide Remapping)

Если UID пользователя изменился (например, с 1000 на 2000), необходимо найти и исправить права на все его файлы вне домашней директории (например, в `/var/www` или `/opt`).

```bash
# Поиск файлов старого UID и смена на новый
sudo find / -uid 1000 -exec chown -h 2000 {} +

# Аналогично для GID
sudo find / -gid 1000 -exec chgrp -h 2000 {} +
```

### Автоматизация через Perl (для больших объемов)

Для миллионов файлов `find` может быть медленным. Используйте Perl для прямого обхода файловой системы:

```bash
sudo perl -e '
  use File::Find;
  find(sub {
    return if -l;
    if ((stat)[4] == 1000) {
      chown(2000, -1, $_) or warn "Failed: $_\n";
    }
  }, "/");
'
```

### Обработка смонтированных файловых систем

Если файлы находятся на отдельном разделе или NFS, смонтируйте его отдельно и выполните remapping:

```bash
# Для отдельного раздела
sudo mount /dev/sdb1 /mnt/data
sudo find /mnt/data -uid 1000 -exec chown 2000 {} +

# Для NFS (требует остановки сервисов, использующих файлы)
sudo systemctl stop nfs-server
sudo find /export/users -uid 1000 -exec chown 2000 {} +
sudo systemctl start nfs-server
```

### Валидация после remapping

```bash
# Проверка остатков старого UID
sudo find / -uid 1000 2>/dev/null | head

# Проверка статистики
sudo find / -uid 2000 | wc -l
```

## Дополнительная информация

### Специфика дистрибутивов (Cross-Distro)

| Параметр | RHEL / CentOS | Debian / Ubuntu |
| :--- | :--- | :--- |
| **Группа sudo** | `wheel` | `sudo` |
| **UID системных** | < 1000 | < 1000 (иногда < 500) |
| **Shell по умолчанию** | `/bin/bash` | `/bin/bash` |
| **Логи** | `adm`, `systemd-journal` | `adm`, `systemd-journal` |
| **Cron** | `/var/spool/cron/username` | `/var/spool/cron/crontabs/username` |
| **Mail** | `/var/spool/mail/username` | `/var/mail/username` |

### Пост-миграционный аудит

```bash
# 1. Проверка входа и окружения
su - username -c "id && ls -la ~"

# 2. Проверка битых ссылок и прав на SSH
namei -mo /home/username/.ssh/authorized_keys

# 3. Проверка целостности баз данных
sudo pwck -r
sudo grpck -r

# 4. Проверка subuid/subgid
cat /etc/subuid | grep username
cat /etc/subgid | grep username

# 5. Проверка активных сессий (не должно быть старой)
loginctl list-sessions | grep username

# 6. Синхронизация Podman (если UID/GID изменились)
sudo -u username podman system migrate
```

### Типовые проблемы

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission Denied` (SSH) | Неверные права на `.ssh`. | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/*`. |
| Ошибка хэша пароля | Несоответствие алгоритмов. | Сбросьте пароль через `passwd` или установите `libpam-yescrypt`. |
| Нет прав `sudo` | Разные имена групп. | Добавьте пользователя в `wheel` (RHEL) или `sudo` (Debian). |
| `useradd: UID already exists` | Целевой UID занят. | Используйте `useradd -o` для non-unique или выберите другой UID. |
| Файлы принадлежат `nobody` после rsync | Несовпадение UID между хостами. | Создайте пользователя с тем же UID перед rsync или используйте `chown`. |
| `newusers: cannot lock /etc/passwd` | Другой процесс редактирует файл. | Убедитесь, что нет запущенных `vipw`/`useradd`. |
| `homectl import: UID already exists` | Конфликт UID при импорте. | Используйте `homectl import --uid-map=auto` или удалите конфликтующую запись. |
| `podman: permission denied` | Не настроены subuid/subgid. | Добавьте диапазоны в `/etc/subuid` и `/etc/subgid`, затем `podman system migrate`. |
| `su: Authentication failure` | Неверный пароль или PAM блокировка. | Проверьте `faillock --user username`. |
| `chown: invalid user` | UID существует, но пользователь не найден в NSS. | Выполните `getent passwd <uid>` для диагностики. |
| `Permission denied` при работе с `docker` | Пользователь не добавлен в группу `docker`. | `sudo gpasswd -a username docker` и перелогин/`exec su - $USER`. |
| `grpck: group 'x' has a duplicate entry` | Дублирование группы в `/etc/group` и `/etc/gshadow`. | Удалите дубликат через `vigr` или `grpck -s`. |
| `acl: Operation not supported` | Файловая система не поддерживает ACL. | Проверьте `mount | grep <fs>`, добавьте `acl` в опции монтирования в `/etc/fstab`. |
| `rsync: failed to set permissions` | Отсутствуют права на целевом хосте. | Запустите rsync от root или через SSH с ключом root. |

### Лучшие практики (2026)

1.  **Декларативность:** Для массовых миграций используйте Ansible/SaltStack вместо ручных скриптов.
2.  **UPG:** Следуйте архитектуре User Private Groups — каждый пользователь = уникальная группа.
3.  **Безопасное редактирование:** Всегда используйте `vipw`/`vigr` вместо прямого редактирования `/etc/passwd`/`/etc/group`.
4.  **Целостность:** Периодически запускайте `pwck -r` и `grpck -r` для проверки баз данных.
5.  **NSS:** Используйте `getent passwd` вместо `cat /etc/passwd` в скриптах для поддержки LDAP/SSSD.
6.  **Subuid/Subgid:** Обязательно переносите диапазоны для пользователей, работающих с rootless-контейнерами.
7.  **Атрибуты:** Используйте `rsync -aHAXz` для сохранения ACL, xattrs и SELinux-контекстов.
8.  **Пароли:** Для переноса хэшей паролей убедитесь, что алгоритм поддерживается целевой системой (YESCRYPT vs SHA-512).
9.  **Аудит:** Логируйте изменения через `auditd`: `sudo auditctl -w /etc/passwd -p wa -k passwd_modification`.
10. **Резервное копирование:** Перед миграцией создайте снапшот `/etc/passwd`, `/etc/shadow`, `/etc/group` и домашних директорий.

### Compliance-проверки

```bash
# CIS Benchmark: Поиск пользователей с UID 0
awk -F: '($3 == 0) {print $1}' /etc/passwd

# Поиск пользователей с несколькими группами (возможная избыточность)
getent passwd | awk -F: '{print $1, $4}' | while read user gid; do
    supplementary=$(id -Gn "$user" | wc -w)
    if [ "$supplementary" -gt 5 ]; then
        echo "Пользователь $user состоит в $supplementary группах"
    fi
done

# Проверка групп с паролем (не заблокированы)
sudo awk -F: '($2 != "" && $2 != "!" && $2 != "*") {print $1}' /etc/gshadow

# Проверка subuid/subgid покрытия
while IFS=: read -r user _; do
    grep -q "^$user:" /etc/subuid || echo "WARNING: $user missing in /etc/subuid"
    grep -q "^$user:" /etc/subgid || echo "WARNING: $user missing in /etc/subgid"
done < <(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1}')
```

### Откат (Rollback)

В случае критических ошибок после миграции:

```bash
# 1. Отключение нового пользователя (блокировка пароля)
sudo passwd -l username

# 2. Удаление записи из /etc/passwd и /etc/shadow
sudo vipw
# Удалите строку username вручную или:
sudo userdel username

# 3. Восстановление домашней директории из бэкапа
sudo rsync -aHAXz --progress /backup/username/ /home/username/

# 4. Восстановление старой записи (если бэкап /etc/passwd сделан)
sudo cp /etc/passwd.bak /etc/passwd
sudo cp /etc/shadow.bak /etc/shadow
sudo cp /etc/group.bak /etc/group
```

### Граничные случаи и ограничения

1.  **Миграция root (UID 0):** Не рекомендуется. Любое изменение записи root может сделать систему непригодной для загрузки. Используйте `sudo` или `run0` для администрирования вместо создания дубликатов root.
2.  **Миграция на NFS:** Требует синхронизации `/etc/idmapd.conf` и идентичных UID/GID на клиенте и сервере.
3.  **Миграция с SELinux enforcing:** Необходимо восстановить контексты через `restorecon -R /home/username` после копирования файлов.
4.  **Миграция пользователей с открытыми файлами:** Все процессы пользователя должны быть завершены перед миграцией данных. Используйте `loginctl terminate-user username` или `pkill -u username`.
5.  **Криптографические ключи (GPG/SSH):** При переносе через `rsync` убедитесь, что права на `~/.ssh` и `~/.gnupg` строгие (`700` и `600`), иначе SSH/GPG проигнорируют ключи.

### Смежные темы

- [Управление пользователями](./user_commands.md) — команды `useradd`, `usermod`.
- [Файлы конфигурации пользователей](./users_config_files.md) — структура `/etc/passwd`, `/etc/shadow`.
- [rsync — синхронизация файлов](../rsync.md) — детальный разбор флагов и алгоритмов.
- [systemd-homed](./systemd-homed.md) — работа с портативными образами.
- [LDAP и SSSD](./LDAP_SSSD/index.md) — интеграция в централизованные системы.
- [Приватные группы (UPG)](./user_private_groups.md) — архитектура UID=GID.
- [Политики паролей (chage)](./password_policy_chage.md) — управление сроком действия паролей.
- [Хэширование паролей](./password_hashing.md) — алгоритмы Yescrypt/Argon2.
