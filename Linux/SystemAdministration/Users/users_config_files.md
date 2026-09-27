# Файлы конфигурации пользователей и групп в Linux

## Определения

- **`/etc/passwd`** — текстовая база данных («паспорт» системы), содержащая основную информацию об учетных записях. Доступен для чтения всем (`644`), так как UID/имена нужны утилитам вроде `ls`.
- **`/etc/shadow`** — защищенный файл (`600` или `640`), хранящий хэши паролей и параметры политик их устаревания. Доступен только суперпользователю.
- **`/etc/group`** — файл, определяющий группы в системе и их первичный состав.
- **`/etc/gshadow`** — файл с зашифрованными паролями групп и списком администраторов групп (используется для `newgrp`).
- **`/etc/nsswitch.conf`** — конфигурация диспетчера Name Service Switch, определяющая источники и порядок поиска данных (files, sssd, dns).
- **`/etc/shells`** — список путей к допустимым оболочкам (shell). Используется `sshd` и `chsh` для проверки прав.
- **`/etc/subuid` / `/etc/subgid`** — файлы, определяющие диапазоны подчиненных идентификаторов для User Namespaces (контейнеризация, Rootless-режимы).
- **`/etc/skel`** — директория-шаблон, содержимое которой копируется в `HOME` нового пользователя при `useradd -m`.
- **`/etc/login.defs`** — глобальные политики создания пользователей (диапазоны UID/GID, алгоритмы хэширования, umask по умолчанию, сроки действия паролей).
- **`/etc/default/useradd`** — настройки по умолчанию для утилиты `useradd` (путь к `/home`, shell, шаблон `/etc/skel`).
- **`/etc/security/limits.conf`** и **`/etc/security/limits.d/`** — конфигурация PAM-модуля `pam_limits.so` для установки постоянных ограничений ресурсов (nofile, nproc, memlock).
- **`/etc/pam.d/common-session`** (Debian/Ubuntu) или **`/etc/pam.d/system-auth`** (RHEL) — PAM-конфигурация, содержащая модуль `pam_mkhomedir.so` для автоматического создания домашних директорий.
- **utmp / wtmp / btmp** — специализированные бинарные файлы в `/var/run/` и `/var/log/`, хранящие историю текущих и завершенных сессий.
- **`/var/log/lastlog`** — база данных времени последнего входа каждого пользователя.
- **`/var/log/faillock`** — каталог (или файл) с счетчиками неудачных попыток аутентификации.
- **`vipw` / `vigr`** — утилиты для безопасного редактирования `passwd/group` с блокировкой (locking) от одновременных правок.

## Базовые концепции

### Детальный разбор /etc/passwd
**Формат:** `username:password:UID:GID:GECOS:home_directory:shell`

| Поле | Описание | Технические нюансы |
| :--- | :--- | :--- |
| **username** | Уникальное имя. | До 32 символов (рекомендация), латиница, цифры, дефис. |
| **password** | Флаг пароля. | Символ `x` означает, что хэш находится в `/etc/shadow`. |
| **UID** | User ID. | 0 — root, 1-999 — системные, 1000+ — пользователи. |
| **GID** | Primary Group ID. | Идентификатор основной группы пользователя. |
| **GECOS** | Комментарий. | Порядок: Full Name, Room, Work Phone, Home Phone, Other. |
| **home_directory** | Домашняя папка. | Абсолютный путь. |
| **shell** | Оболочка входа. | `/usr/sbin/nologin` запрещает вход, но оставляет возможность владеть процессами. |

### Детальный разбор /etc/shadow
**Формат:** `username:password:last_change:min:max:warn:inactive:expire:reserved`

| Поле | Описание | Примечание |
| :--- | :--- | :--- |
| **password** | Хэш пароля. | `$y$` — **[Yescrypt](./password_hashing.md)**, `$6$` — SHA-512. `!` или `*` — блок входа. |
| **last_change** | Дата смены. | Дней с 01.01.1970. Значение `0` принуждает сменить пароль при входе. |
| **min** | Минимум дней. | Интервал между сменами (0 — нет ограничений). |
| **max** | Максимум дней. | Срок жизни (дефолт `99999` — бессрочно). |
| **warn** | Предупреждение. | За сколько дней до истечения начать предупреждать. |
| **inactive** | Период покоя. | Дней после истечения `max` до полной блокировки. |
| **expire** | Дата истечения. | Абсолютная дата блокировки (дней с эпохи Unix). |

### Детальный разбор /etc/login.defs

Файл задает глобальные политики, влияющие на создание и управление учетными записями. В современных системах часть параметров может дублироваться в `/etc/default/useradd`, но `/etc/login.defs` остается authoritative source для PAM и shadow-утилит.

| Параметр | Описание | Типичное значение |
| :--- | :--- | :--- |
| **`UID_MIN` / `UID_MAX`** | Диапазон UID для обычных пользователей. | `UID_MIN 1000` / `UID_MAX 60000` |
| **`GID_MIN` / `GID_MAX`** | Диапазон GID для обычных групп. | Аналогично UID. |
| **`PASS_MAX_DAYS`** | Максимальный срок действия пароля. | `99999` |
| **`PASS_MIN_DAYS`** | Минимальный интервал между сменами. | `0` |
| **`PASS_WARN_AGE`** | За сколько дней предупреждать об истечении. | `7` |
| **`USERGROUPS_ENAB`** | Создавать ли приватную группу с именем пользователя. | `yes` (см. [UPG](./user_private_groups.md)) |
| **`ENCRYPT_METHOD`** | Алгоритм хэширования паролей по умолчанию. | `YESCRYPT` (Debian 12+, Ubuntu 24.04+) |
| **`UMASK`** | Маска создания файлов для новых пользователей. | `022` или `002` |

**Важность для DevOps:** Параметры `PASS_MAX_DAYS` и `ENCRYPT_METHOD` применяются только к новым пользователям. Для существующих используйте `chage` и `authselect`/`pam-auth-update`.

### Детальный разбор /etc/skel

Директория-шаблон, содержимое которой копируется в домашнюю директорию нового пользователя. В современных системах копирование может делегироваться `systemd-tmpfiles` или `pam_mkhomedir.so`.

**Типичное содержимое:**
- `.bashrc`, `.profile`, `.bash_logout` — конфигурация shell.
- `.ssh/` — директория для SSH-ключей (обычно создается с правами `700`).
- `.config/`, `.local/` — пользовательские конфигурации приложений.

**Связь с systemd-tmpfiles:**
```ini
# /etc/tmpfiles.d/user.conf
d /home/username 0750 username username -
```
При использовании `systemd-tmpfiles` копирование `/etc/skel` не происходит автоматически; необходимо дублировать содержимое вручную или через скрипт.

### Детальный разбор /etc/shells

Файл содержит список допустимых оболочек входа. При попытке входа (`sshd`, `login`) или смене shell (`chsh`) система проверяет, указана ли оболочка в этом файле.

**Важные нюансы:**
- Если shell пользователя отсутствует в `/etc/shells`, вход блокируется даже при корректном пароле.
- `/usr/sbin/nologin` и `/bin/false` обычно присутствуют в файле, но блокируют интерактивный вход.
- Для ограничения доступа к `su` или `sudo` используйте PAM-модуль `pam_listfile.so`, а не удаление shell из файла.

### Детальный разбор /etc/group и /etc/gshadow

**Формат `/etc/group`:** `group_name:password:GID:user_list`

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| **group_name** | Имя группы | `developers` |
| **password** | Флаг пароля (обычно `x`). | `x` |
| **GID** | Числовой идентификатор группы. | `1001` |
| **user_list** | Список членов (через запятую). | `alice,bob,charlie` |

**Формат `/etc/gshadow`:** `group_name:password:admins:members`

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| **group_name** | Имя группы | `developers` |
| **password** | Зашифрованный пароль или `!`. | `$6$...` или `!` |
| **admins** | Администраторы группы (через запятую). | `alice` |
| **members** | Полный список членов. | `alice,bob,charlie` |

> **Важно:** Пароли групп редко используются. Устанавливайте `!` в поле пароля, чтобы предотвратить аутентификацию через `newgrp`.

### PAM-контекст файлов пользователей

Файлы `/etc/passwd`, `/etc/shadow`, `/etc/group` используются PAM-модулями напрямую:

- **`pam_unix.so`** — стандартный модуль аутентификации, читающий `/etc/shadow`.
- **`pam_mkhomedir.so`** — создает домашнюю директорию из `/etc/skel` при первом входе LDAP-пользователя.
- **`pam_sss.so`** — делегирует аутентификацию в SSSD, который затем обращается к NSS.
- **`pam_access.so`** — применяет правила из `/etc/security/access.conf` к пользователям из любых источников NSS.

**Связь с nsswitch.conf:** Порядок источников в `nsswitch.conf` определяет, какой модуль PAM будет использоваться для поиска пользователя. Если `passwd: files sss`, то `pam_unix.so` сработает для локальных пользователей, а `pam_sss.so` — для сетевых.

### SELinux / AppArmor контекст

На системах с mandatory access control (MAC) файлы пользователей имеют специальные контексты безопасности:

```bash
# Проверка контекста /etc/shadow (SELinux)
ls -laZ /etc/shadow
# → system_u:object_r:shadow_t:s0 /etc/shadow

# Проверка AppArmor профиля для passwd
aa-status | grep passwd
```

**Политика:** Контексты должны оставаться `shadow_t` (SELinux) или соответствовать профилю AppArmor. Изменение прав без учета MAC приведет к отказам в доступе, даже если стандартные права Unix корректны.

### Сессионные файлы и история входов

| Файл | Назначение | Формат |
| :--- | :--- | :--- |
| **`/var/run/utmp`** | Текущие активные сессии. | Бинарный; читается `who`, `w`. |
| **`/var/log/wtmp`** | История всех входов/выходов. | Бинарный; читается `last`. |
| **`/var/log/btmp`** | История неудачных попыток входа. | Бинарный; читается `lastb`. |
| **`/var/log/lastlog`** | Время последнего входа каждого UID. | Бинарный; читается `lastlog`. |
| **`/var/log/faillock`** | Счетчики неудачных аутентификаций. | Бинарный; управляется `faillock`. |

**Технический нюанс:** `utmp` хранится в `/var/run/` (tmpfs) и теряется при перезагрузке. `wtmp` и `btmp` пишутся на диск и сохраняются между перезагрузками.

### Диспетчер Name Service Switch (/etc/nsswitch.conf)

Файл определяет стратегию поиска данных. В 2026 году управление этим файлом часто делегируется утилите `authselect` (RHEL) или PAM-конфигураторам.

**Пример:** `passwd: files sssd`
1. Система ищет в `files` (`/etc/passwd`).
2. Если не найдено, обращается к `sssd` (LDAP/AD).

**Статусы и условия:**
- `[NOTFOUND=return]`: если источник ответил, что пользователя нет — прекратить поиск (не идти к следующему).
- `SUCCESS`: запись найдена, поиск завершен.

**Управление через authselect (RHEL/Debian):**
```bash
# Просмотр текущей конфигурации
sudo authselect current

# Выбор профиля с sssd
sudo authselect select sssd with-mkhomedir --force

# Проверка результата
cat /etc/nsswitch.conf
```

**Важные замечания:**
- Порядок источников критичен. При `passwd: sss files` LDAP-пользователи будут иметь приоритет над локальными, что может привести к неожиданному поведению при дублировании имен.
- Источник `systemd` в строке `passwd`/`group` активирует поддержку `systemd-userdbd`. Без этого пользователи, созданные через `systemd-homed` или `DynamicUser=yes`, не будут видны в `id`/`getent`.
- Источник `compat` (NIS) устарел и не рекомендуется к использованию в новых системах.

### Кэширование NSS: nscd vs systemd-userdbd

В старых системах для кэширования использовался `nscd` (Name Service Cache Daemon). В 2026 году он считается устаревшим (legacy) и заменен архитектурой `systemd-userdbd`, который:
- Кэширует результаты через D-Bus без отдельного демона.
- Поддерживает гибридные источники (файлы + LDAP + homed) консистентно.
- Автоматически обновляет кэш при изменениях в `/etc/passwd`.

**Когда nscd еще встречается:** На системах RHEL 7, CentOS 7, а также в контейнерах, где systemd не используется. В таких случаях убедитесь, что `nscd` не кэширует устаревшие записи после миграции пользователей.

### Современная архитектура: systemd-userdbd (2026)

Сервис **`systemd-userdbd.service`** объединяет данные из `/etc/passwd`, **[systemd-homed](./systemd-homed.md)** и **[SSSD](./LDAP_SSSD/index.md)** в единый JSON-интерфейс через D-Bus. Это позволяет видеть пользователей, даже если они отсутствуют в физических файлах на диске, обеспечивая «виртуальную» базу данных.

## Практические сценарии

### Безопасное редактирование

```bash
# Редактирование основного файла пользователей
sudo vipw

# Редактирование файла паролей (shadow)
sudo vipw -s

# Редактирование групп
sudo vigr
```

### Проверка целостности и структуры

```bash
# Проверка passwd и shadow на наличие дубликатов и битых путей
sudo pwck -r

# Проверка group и gshadow
sudo grpck -r
```

### Анализ и фильтрация

```bash
# Список всех пользователей с интерактивным shell
grep -E '(/bin/bash|/bin/zsh)$' /etc/passwd

# Поиск пользователей с пустым полем пароля в passwd
sudo awk -F: '$2 == "" {print $1}' /etc/passwd

# Извлечение только имен и домашних директорий
awk -F: '{print $1, $6}' /etc/passwd

# Пользователи с непустыми паролями (реальный хэш в shadow) вместе с их домашними директориями.
# Хэши хранятся в /etc/shadow, поэтому файлы объединяются по имени пользователя (поле 1)
sudo awk -F: 'NR==FNR {h[$1]=$2; next} h[$1] !~ /^[!*!]*$/ && h[$1] != "" {print $1, $6}' /etc/shadow /etc/passwd
```

Последняя команда решает типовую задачу аудита: в `/etc/shadow` ищутся записи, у которых второе поле содержит настоящий хэш (не пустое и не `*`/`!` — маркеры отключённой аутентификации), а из `/etc/passwd` подтягивается шестое поле — домашний каталог. Для сетевых пользователей (LDAP/AD) используйте `getent passwd` и `getent shadow` вместо прямого чтения файлов.

### Мониторинг изменений (auditd)

```bash
# Настройка аудита через auditd
sudo auditctl -w /etc/passwd -p wa -k passwd_modification
sudo auditctl -w /etc/shadow -p wa -k shadow_modification
sudo auditctl -w /etc/group -p wa -k group_modification
sudo auditctl -w /etc/gshadow -p wa -k gshadow_modification
sudo auditctl -w /etc/nsswitch.conf -p wa -k nsswitch_modification

# Просмотр событий
sudo ausearch -k passwd_modification --start recent
```

Для персистентности после перезагрузки добавьте правила в `/etc/audit/rules.d/audit.rules`:
```bash
-w /etc/passwd -p wa -k passwd_modification
-w /etc/shadow -p wa -k shadow_modification
-w /etc/group -p wa -k group_modification
-w /etc/gshadow -p wa -k gshadow_modification
-w /etc/nsswitch.conf -p wa -k nsswitch_modification
```

### Валидация соответствия CIS/FSTEC

```bash
#!/bin/bash
# validate_configs.sh — базовый аудит конфигурационных файлов

echo "=== Права на критичные файлы ==="
stat -c '%a %U:%G %n' /etc/passwd /etc/shadow /etc/group /etc/gshadow

echo "=== UID 0 (только root) ==="
awk -F: '($3 == 0) {print $1}' /etc/passwd

echo "=== Пустые пароли ==="
sudo awk -F: '($2 == "" || $2 == "!") {print $1}' /etc/shadow

echo "=== Системные пользователи с интерактивным shell ==="
awk -F: '($3 < 1000 && $3 != 0 && $7 != "/usr/sbin/nologin" && $7 != "/bin/false") {print $1}' /etc/passwd

echo "=== Пользователи без домашней директории ==="
awk -F: '($6 == "" || $6 == "/") {print $1}' /etc/passwd

echo "=== Дубликаты UID ==="
awk -F: '{print $3}' /etc/passwd | sort | uniq -d

echo "=== Дубликаты GID ==="
awk -F: '{print $3}' /etc/group | sort | uniq -d

echo "=== Группы с паролем (не заблокированы) ==="
sudo awk -F: '($2 != "" && $2 != "!" && $2 != "*") {print $1}' /etc/gshadow

echo "=== Проверка /etc/shells ==="
grep -E '^/bin/(sh|csh|tcsh)$' /etc/shells || echo "OK: опасных shells нет"
```

### Проверка golden image (фиксированный набор пользователей)

```bash
#!/bin/bash
# validate_golden_image.sh — проверка соответствия образа эталону

EXPECTED_USERS=("root" "bin" "daemon" "_nginx" "_postgres" "_prometheus")
EXPECTED_GROUPS=("root" "bin" "daemon" "_nginx" "_postgres" "_prometheus")
EXPECTED_SHELLS=("/usr/sbin/nologin" "/bin/false" "/bin/bash" "/bin/sh")

echo "=== Проверка наличия сервисных пользователей ==="
for user in "${EXPECTED_USERS[@]}"; do
    if ! id "$user" &>/dev/null; then
        echo "ОТСУТСТВУЕТ: $user"
    fi
done

echo "=== Проверка UID системных пользователей ==="
for user in "${EXPECTED_USERS[@]}"; do
    uid=$(id -u "$user" 2>/dev/null)
    if [ -n "$uid" ] && [ "$uid" -ge 1000 ]; then
        echo "WARNING: $user имеет UID $uid (ожидалось < 1000)"
    fi
done

echo "=== Проверка shell пользователей ==="
while IFS=: read -r user _ uid shell _; do
    if [ "$uid" -ge 1000 ] && [ "$shell" != "/bin/bash" ] && [ "$shell" != "/bin/zsh" ]; then
        echo "WARNING: $user имеет нестандартный shell: $shell"
    fi
done < /etc/passwd

echo "=== Проверка /etc/skel на измененные файлы ==="
SKEL_MD5=$(find /etc/skel -type f -exec md5sum {} \; 2>/dev/null | sort | md5sum | cut -d' ' -f1)
echo "MD5 /etc/skel: $SKEL_MD5"
```

### Работа в chroot/контейнерах

При создании chroot-окружения или контейнерного образа необходимо обеспечить корректность файлов пользователей внутри изолированной ФС:

```bash
# 1. Копирование базовых файлов в chroot
sudo cp /etc/passwd /etc/shadow /etc/group /etc/gshadow /mnt/chroot/etc/
sudo cp /etc/nsswitch.conf /mnt/chroot/etc/

# 2. Копирование /etc/skel
sudo cp -a /etc/skel /mnt/chroot/etc/

# 3. Проверка целостности внутри chroot
sudo chroot /mnt/chroot pwck -r
sudo chroot /mnt/chroot grpck -r

# 4. Проверка видимости пользователей
sudo chroot /mnt/chroot getent passwd root
```

**Важно:** Внутри контейнера без systemd-userdbd используйте только локальные файлы. Избегайте строк `systemd` в `nsswitch.conf` внутри контейнеров, если сервис не запущен.

### Настройка Rootless-диапазонов (subuid/subgid)

```bash
# Формат: username:start_id:range
# Добавление 65536 идентификаторов для контейнеров Podman
echo "developer:100000:65536" | sudo tee -a /etc/subuid
echo "developer:100000:65536" | sudo tee -a /etc/subgid

# Проверка покрытия для всех обычных пользователей
while IFS=: read -r user _ uid _; do
    if [ "$uid" -ge 1000 ] && [ "$uid" -lt 60000 ]; then
        grep -q "^$user:" /etc/subuid || echo "WARNING: $user отсутствует в /etc/subuid"
        grep -q "^$user:" /etc/subgid || echo "WARNING: $user отсутствует в /etc/subgid"
    fi
done < <(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1}')
```

### Атомарное резервное копирование

```bash
#!/bin/bash
# backup_user_dbs.sh — атомарный снапшот конфигурационных файлов

BACKUP_DIR="/var/backups/user_configs"
DATE=$(date +%F_%H%M%S)

sudo mkdir -p "$BACKUP_DIR"

# Использование файловых дескрипторов для атомарности
sudo bash -c "
exec 3>/etc/passwd
exec 4>/etc/shadow
exec 5>/etc/group
exec 6>/etc/gshadow
exec 7>/etc/nsswitch.conf
exec 8>/etc/login.defs
exec 9>/etc/shells

cp /etc/passwd $BACKUP_DIR/passwd.$DATE
cp /etc/shadow $BACKUP_DIR/shadow.$DATE
cp /etc/group $BACKUP_DIR/group.$DATE
cp /etc/gshadow $BACKUP_DIR/gshadow.$DATE
cp /etc/nsswitch.conf $BACKUP_DIR/nsswitch.conf.$DATE
cp /etc/login.defs $BACKUP_DIR/login.defs.$DATE
cp /etc/shells $BACKUP_DIR/shells.$DATE

# Создание архивов
tar -czf $BACKUP_DIR/user_configs.$DATE.tar.gz \
    -C $BACKUP_DIR passwd.$DATE shadow.$DATE group.$DATE gshadow.$DATE \
    nsswitch.conf.$DATE login.defs.$DATE shells.$DATE
"

echo "Бэкап создан: $BACKUP_DIR/user_configs.$DATE.tar.gz"
```

### Управление authselect (RHEL/Debian)

```bash
# Просмотр текущего профиля
sudo authselect current

# Применение профиля с автоматическим созданием home
sudo authselect select sssd with-mkhomedir --force

# Откат на локальную аутентификацию
sudo authselect select winbind with-mkhomedir --force

# Проверка конфигурации
cat /etc/nsswitch.conf
ls -la /etc/pam.d/system-auth /etc/pam.d/password-auth
```

## Дополнительная информация

### Безопасность и Харденинг

1.  **Права доступа:** Ошибка в правах на `/etc/shadow` (`644` вместо `600/640`) — это критическая уязвимость, позволяющая выполнить Offline Brute-force.
2.  **Эскалация через GECOS:** Не записывайте чувствительные данные в поле комментария. В некоторых старых системах манипуляции с GECOS могли приводить к переполнению буфера в утилитах `finger` или `chfn`.
3.  **Ограничение shells:** Удаляйте из `/etc/shells` интерпретаторы, которые не должны использоваться для входа (например, `/bin/sh`, если основным является `bash`), чтобы снизить поверхность атаки.
4.  **Беспарольный вход:** Если второе поле в `/etc/passwd` пустое (не содержит даже `x`), некоторые конфигурации PAM могут разрешить вход без пароля.
5.  **Атомарность изменений:** Всегда используйте `vipw`/`vigr` для редактирования файлов. Прямое редактирование через `nano`/`vim` при сбое питания или сети приведет к повреждению базы и невозможности входа.
6.  **Защита через атрибуты:** Для предотвращения случайного изменения критичных файлов используйте `chattr +i /etc/passwd /etc/shadow /etc/group /etc/gshadow`. Для удаления атрибута используйте `chattr -i`.
7.  **SELinux/AppArmor:** Не отключайте MAC. При изменении контекста файлов пользователей используйте `restorecon` или `aa-complain` вместо полного отключения.
8.  **Аудит:** Настройте `auditd` для отслеживания изменений в `/etc/passwd`, `/etc/shadow`, `/etc/group`:
    ```bash
    sudo auditctl -w /etc/passwd -p wa -k passwd_modification
    sudo auditctl -w /etc/shadow -p wa -k shadow_modification
    sudo auditctl -w /etc/group -p wa -k group_modification
    sudo auditctl -w /etc/gshadow -p wa -k gshadow_modification
    ```

### Резервное копирование и восстановление

```bash
# Снимок состояния перед правками
sudo cp /etc/passwd /etc/passwd.bak_$(date +%F)
sudo cp /etc/shadow /etc/shadow.bak_$(date +%F)
sudo cp /etc/group /etc/group.bak_$(date +%F)
sudo cp /etc/gshadow /etc/gshadow.bak_$(date +%F)
sudo cp /etc/nsswitch.conf /etc/nsswitch.conf.bak_$(date +%F)

# Атомарное восстановление (в случае ошибки)
sudo cp /etc/passwd.bak_2026-09-14 /etc/passwd
sudo cp /etc/shadow.bak_2026-09-14 /etc/shadow
sudo cp /etc/group.bak_2026-09-14 /etc/group
sudo cp /etc/gshadow.bak_2026-09-14 /etc/gshadow

# Проверка после восстановления
sudo pwck -r
sudo grpck -r
```

**Важно:** Резервные копии `/etc/shadow` и `/etc/gshadow` должны храниться с правами `600` и защищаться так же, как исходные файлы.

### Troubleshooting

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `useradd: user ... already exists` | Дублирование UID или имени. | Проверьте `getent passwd username`; используйте `useradd -o` если нужен не-unique UID. |
| `pwck: user ... has no password` | У пользователя пустой пароль. | Установите пароль через `passwd` или заблокируйте через `usermod -L`. |
| `grpck: group 'x' has a duplicate entry` | Дублирование группы в `/etc/group` и `/etc/gshadow`. | Удалите дубликат через `vigr` или `grpck -s`. |
| `vipw/vigr: cannot lock /etc/passwd` | Другой процесс редактирует файл. | Убедитесь, что нет запущенных `vipw`/`useradd`; проверьте `/etc/passwd.lock`. |
| `su: Authentication failure` | Неверный пароль или PAM блокировка. | Проверьте `faillock --user username`. |
| `chsh: shell not in /etc/shells` | Указан недопустимый shell. | Добавьте shell в `/etc/shells` или используйте `sudo usermod -s`. |
| `Permission denied` при входе через SSH | Неверные права на `.ssh` или `/etc/shadow`. | Проверьте `namei -mo /home/username/.ssh/authorized_keys` и права на `/etc/shadow`. |
| Пользователь создан, но не виден в `id` | NSS не содержит нужный источник или `systemd-userdbd` не запущен. | Проверьте `nsswitch.conf` и `systemctl status systemd-userdbd`. |
| `newgrp: authentication failure` | Неверный пароль группы или PAM блокировка. | Проверьте пароль через `sudo gpasswd groupname`. |
| `getent: unknown username` | Пользователь не найден ни в одном источнике NSS. | Проверьте `getent passwd username`; убедитесь, что `nsswitch.conf` корректен. |

### Лучшие практики (2026)

1.  **Декларативность:** Для системных пользователей всегда используйте **[systemd-sysusers](./systemd-sysusers.md)**.
2.  **Портативность:** Для рабочих станций внедряйте **[systemd-homed](./systemd-homed.md)**.
3.  **Безопасность:** Для системных аккаунтов всегда устанавливайте Shell в `/usr/sbin/nologin`.
4.  **Имена:** Системные пользователи должны начинаться с `_` (например, `_nginx`).
5.  **UPG:** Используйте приватные группы (UPG) по умолчанию для ограничения доступа к файлам. *Подробнее:* [Приватные группы (UPG)](./user_private_groups.md).
6.  **Безопасное редактирование:** Всегда используйте `vipw`/`vigr` вместо прямого редактирования файлов.
7.  **Целостность:** Периодически запускайте `pwck -r` и `grpck -r` для проверки баз данных.
8.  **Аудит:** Проверяйте `/etc/passwd` на дубликаты UID 0: `awk -F: '$3 == 0 {print $1}' /etc/passwd`.
9.  **Атрибуты:** Используйте `chattr +i` для защиты критичных файлов на production-хостах.
10. **NSS:** Используйте `getent` вместо прямого чтения файлов в скриптах для поддержки LDAP/SSSD/homed.

### Резервное копирование и аудит

```bash
# Снимок состояния перед правками
sudo cp /etc/passwd /etc/passwd.bak_$(date +%F)

# Настройка аудита через auditd
sudo auditctl -w /etc/shadow -p wa -k shadow_modification
```

### Смежные темы

- [Управление пользователями](./user_commands.md) — инструменты `useradd`, `usermod`.
- [Хэширование паролей](./password_hashing.md) — детально про алгоритмы Yescrypt/Argon2.
- [Политики chage](./password_policy_chage.md) — управление полями `max`, `min`, `warn`.
- [systemd-homed](./systemd-homed.md) — JSON-записи как альтернатива `/etc/passwd`.
- [LDAP и SSSD](./LDAP_SSSD/index.md) — внешние источники в `nsswitch.conf`.
- [User Namespaces в Podman](../../../Podman/podman_rootless.md) — глубокий разбор `subuid`.
- [Приватные группы (UPG)](./user_private_groups.md) — архитектура User Private Groups.
- [Управление группами](./group_commands.md) — `groupadd`, `gpasswd`, делегирование прав.
- [Специальные права доступа (SUID/SGID)](../../../Linux/Security/Concepts/File_Permissions/special_permissions.md) — механизмы смены EUID.
- [Обзор PAM](../../../Linux/Security/pam_overview.md) — модули аутентификации.
