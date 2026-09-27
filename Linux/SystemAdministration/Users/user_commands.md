# Управление пользователями в Linux (Императивный подход)

## Определения

- **`useradd`** — низкоуровневая утилита для создания пользователей, наиболее гибкая для использования в скриптах. Является стандартом в RHEL/CentOS/Suse и доступна во всех основных дистрибутивах.
- **`adduser`** — высокоуровневая утилита, поведение которой сильно варьируется:
  - **Debian/Ubuntu:** интерактивная Perl-обёртка над `useradd`, автоматически создающая домашние папки и запрашивающая пароль.
  - **Alpine (BusyBox):** самостоятельная утилита с флагами: `-D` (без пароля), `-S` (системный), `-H` (без home).
  - **RHEL/CentOS:** символическая ссылка на `useradd`.
- **`usermod`** — утилита для модификации любых параметров существующей учетной записи.
- **`userdel`** — утилита для удаления пользователя и (опционально) его ресурсов.
- **`chsh`** — изменение командной оболочки (shell) пользователя без редактирования `/etc/passwd` вручную.
- **`newusers`** — утилита для массового создания/обновления пользователей из файла в формате `/etc/passwd`.
- **`vipw`** — безопасное редактирование `/etc/passwd` с блокировкой файла от одновременных изменений.
- **`vigr`** — безопасное редактирование `/etc/group` с блокировкой.
- **`pwck`** — проверка целостности `/etc/passwd` и `/etc/shadow` на дубликаты и битые ссылки.
- **`grpck`** — проверка целостности `/etc/group` и `/etc/gshadow`.
- **`groups`** — вывод списка всех групп, в которых состоит пользователь.
- **`newgrp`** — запуск новой оболочки с измененной первичной группой (изменение вступает в силу только в новом процессе).
- **`su`** — переключение пользователя (по умолчанию на root) с запросом пароля целевого аккаунта.
- **`run0`** — современная (v256+) замена `sudo` в экосистеме `systemd`. Работает через создание временных юнитов и API менеджера служб, не используя SUID-биты.
- **`loginctl`** — утилита `systemd` для управления сессиями пользователей (list-sessions, terminate-user, enable-linger).
- **`faillock`** — управление счетчиком неудачных попыток входа (заменил устаревший `pam_tally2`).
- **`userdbctl`** — утилита `systemd` (v256+) для инспекции и управления пользователями через `systemd-userdbd` в едином пространстве имен.
- **`getent`** — универсальный инструмент для опроса баз данных NSS (Name Service Switch). Позволяет видеть пользователей не только из локальных файлов, но и из LDAP/AD/SSSD.
- **`id`** — вывод реальных и эффективных UID/GID пользователя.
- **`whoami`** — быстрый вывод имени текущего эффективного пользователя.
- **`ulimit`** — команда оболочки для управления ограничениями ресурсов (файлы, процессы) текущей сессии.

## Базовые концепции

### Настройки и политики по умолчанию

Параметры императивного управления задаются в трех ключевых точках:

1.  **`/etc/default/useradd`** — настройки по умолчанию для `useradd` (путь к `/home`, Shell, шаблон `/etc/skel`).
2.  **`/etc/login.defs`** — глобальные политики (алгоритмы хэширования, диапазоны UID для системных/обычных пользователей).
3.  **`/etc/security/limits.conf`** и **`/etc/security/limits.d/`** — конфигурация PAM-модуля `pam_limits.so` для установки постоянных ограничений ресурсов (nofile, nproc, memlock, cpu и т.д.).

```bash
# Просмотр настроек useradd по умолчанию
useradd -D

# Пример вывода (RHEL/Debian):
# GROUP=100
# HOME=/home
# INACTIVE=-1
# EXPIRE=
# SHELL=/bin/bash
# SKEL=/etc/skel
# CREATE_MAIL_SPOOL=yes
```

### Детализация работы `useradd`

При создании пользователя `useradd -m username` выполняет следующие действия:
1.  Добавляет запись в `/etc/passwd` (формат: `username:x:UID:GID:GECOS:home:shell`).
2.  Добавляет запись в `/etc/group` для первичной группы (в моде UPG — группа с именем пользователя).
3.  Создает запись в `/etc/shadow` с хэшем пароля (или `!` для системных пользователей).
4.  Создает домашнюю директорию (`/home/username`).
5.  Копирует содержимое `/etc/skel` в домашнюю директорию.
6.  Устанавливает владельца директории (`chown username:username /home/username`).

Если флаг `-m` пропущен, домашняя директория не создается, что приводит к ошибке входа.

### Приватные группы (UPG)

Механизм UPG раскрыт в отдельном документе: [Приватные группы пользователей (UPG)](./user_private_groups.md). Кратко: современный стандарт — для каждого пользователя создается группа с тем же именем и GID = UID; файлы по умолчанию недоступны другим пользователям, а supplementary-группы расширяют права без смены первичной группы файлов.

### Name Service Switch (NSS) и конфигурация `/etc/nsswitch.conf`

Файл `/etc/nsswitch.conf` определяет порядок поиска данных:
```text
passwd:         files systemd
group:          files systemd
shadow:         files
```

- `files` — локальные файлы `/etc/passwd`, `/etc/group`, `/etc/shadow`.
- `systemd` — данные из `systemd-userdbd` (включая `systemd-homed`).
- `sssd` — кэшированные данные из LDAP/AD.

Порядок важен: источники проверяются слева направо, и при нахождении записи поиск прекращается.

### Ограничения ресурсов (ulimit / limits.conf)

Ограничения делятся на две категории:

| Тип | Источник | Область действия | Пример |
| :--- | :--- | :--- | :--- |
| **Жесткие (Hard)** | `/etc/security/limits.conf`, `/etc/security/limits.d/` | Все сессии пользователя | `hard nofile 65536` |
| **Мягкие (Soft)** | Тот же источник + `ulimit` в shell | Текущая сессия | `soft nproc 4096` |

Жесткий лимит (`hard`) является верхней границей и может быть изменен только root. Мягкий (`soft`) пользователь может повышать самостоятельно до значения `hard`.

### Современная архитектура и systemd-userdbd (2026)

В современных системах традиционные файлы (`/etc/passwd`) дополняются данными из **[systemd-homed](./systemd-homed.md)** и **[SSSD/LDAP](./LDAP_SSSD/index.md)**. Сервис **`systemd-userdbd.service`** выступает в роли диспетчера, объединяя эти источники в единый JSON-интерфейс через D-Bus. Это гарантирует, что утилиты `id`, `getent` и команды управления работают консистентно независимо от бэкенда.

## Диагностика пользователей

```bash
# Проверка идентификаторов и групп (числовые и имена)
id username

# Проверка через NSS (включая сетевые источники)
getent passwd username
# → username:x:1000:1000:User Comment:/home/username:/bin/bash

# Просмотр лимитов текущего пользователя
ulimit -a
```

## Практические сценарии

### Создание пользователей

```bash
# Интерактивное создание (рекомендуется для Debian/Ubuntu)
sudo adduser test-user

# Создание с домашней директорией и shell по умолчанию
sudo useradd -m test-user

# Создание с конкретным путем к Home и Shell
sudo useradd -m -d /home/custom-dir -s /bin/zsh test-user

# Создание с комментарием (GECOS)
sudo useradd -m -c "Senior DevOps Engineer" dev-user

# Создание с первичной группой и списком дополнительных
sudo useradd -m -g developers -G wheel,docker,libvirt dev-user

# Создание системного пользователя (без входа, UID из системного диапазона)
sudo useradd -r -s /usr/sbin/nologin -c "Prometheus Exporter" _prometheus

# Создание с конкретным UID
sudo useradd -m -u 1500 test-user

# Создание с датой истечения срока действия учетной записи
sudo useradd -m -e 2026-12-31 temp-user

# Блокировка входа при истечении срока пароля (через 5 дней)
sudo useradd -m -f 5 test-user
```

### Установка и управление паролем

```bash
# Установка пароля интерактивно
sudo passwd username

# Блокировка входа по паролю (ставит '!' в /etc/shadow)
sudo passwd -l username

# Разблокировка
sudo passwd -u username

# Принудительная смена пароля при следующем логине
sudo passwd --expire username
```
*Для детального управления жизненным циклом используйте [chage](./password_policy_chage.md).*

### Изменение параметров (usermod)

```bash
# Добавление в группу БЕЗ удаления из текущих (КРИТИЧНО: флаг -a)
sudo usermod -aG docker username

# Переименование пользователя (логина)
sudo usermod -l new-login old-login

# Смена домашней папки с ПЕРЕНОСОМ всех файлов
sudo usermod -d /home/new-home -m username

# Смена первичной группы
sudo usermod -g new_primary_group username

# Установка Shell (например, для блокировки входа)
sudo usermod -s /usr/sbin/nologin username

# Установка даты истечения срока (формат ГГГГ-ММ-ДД)
sudo usermod -e 2027-01-01 username
```

### Использование run0 (Альтернатива sudo)

В дистрибутивах с `systemd` v256+ доступна утилита `run0`, которая не требует SUID-битов.

```bash
# Выполнение команды от root (аналог sudo htop)
run0 htop

# Выполнение от имени конкретного пользователя
run0 --user=_prometheus /usr/local/bin/check_metrics.sh
```

### Удаление пользователей

```bash
# Полное удаление с Home и почтовым ящиком
sudo userdel -r username

# Принудительное удаление активного пользователя (убивает процессы)
sudo userdel -f username
```

### Аудит активности

```bash
# История последних входов (из /var/log/wtmp)
last username

# Информация о последнем входе всех пользователей (из /var/log/lastlog)
lastlog

# Список текущих сессий через logind
loginctl list-sessions
```

## Дублирование root (UID 0)

В Linux права определяются UID. Любой пользователь с UID=0 является root.

### Почему это критически опасно

Ядро Linux проверяет именно равенство UID нулю для обхода стандартных проверок прав доступа. Пользователь с UID 0:
- Может читать/записывать любые файлы, независимо от прав.
- Может изменять ядерные параметры (`sysctl`).
- Может загружать/выгружать модули ядра.
- Может изменять iptables/nftables правила.
- Не виден в `sudo` аудите как escalation — уже root.

Аудит (`auditd`, `journalctl`) может отличать `root` от дубликатов только по имени, но не по правам.

### Метод 1: Императивный (useradd)
Ключ `-o` (non-unique) позволяет использовать занятый UID.
```bash
sudo useradd -o -u 0 -g 0 -d /root -s /bin/bash rescue_admin
```

### Метод 2: Ручное редактирование (vipw)
```bash
sudo vipw
# Добавьте строку: rescue_admin:x:0:0:Emergency Admin:/root:/bin/bash
```

### Метод 3: Через userdbctl (systemd v256+)
```bash
sudo userdbctl --import rescue_admin --uid=0 --gid=0 --home-dir=/root --shell=/bin/bash
```

> **Важно:** Это создает огромную дыру в безопасности и затрудняет аудит. Используйте `sudo` или `run0` вместо создания дубликатов root.

## Дополнительная информация

### Проверка перед удалением (Checklist)

```bash
# 1. Проверить процессы пользователя
ps -u username

# 2. Проверить cron-задания
sudo crontab -u username -l

# 3. Проверить файлы во всей системе
sudo find / -user username 2>/dev/null | head -n 20
```

### Сценарий автоматизации (Bash)

```bash
#!/bin/bash
# add_corp_user.sh - Декларативное создание с проверкой
USER=$1
if id "$USER" &>/dev/null; then
    echo "Ошибка: Пользователь $USER уже существует."
    exit 1
fi
sudo useradd -m -s /bin/bash -G corp_users -c "Created via script $(date +%F)" "$USER"
echo "Пользователь $USER создан."
```

### Безопасное редактирование файлов пользователей

Для предотвращения повреждения БД при одновременном редактировании используйте `vipw` и `vigr`:

```bash
# Безопасное редактирование /etc/passwd
sudo vipw

# Безопасное редактирование /etc/shadow
sudo vipw -s

# Безопасное редактирование /etc/group
sudo vigr
```

Эти утилиты блокируют файлы (`/etc/passwd.lock`) на время редактирования, предотвращая race conditions.

### Проверка целостности баз данных

```bash
# Проверка /etc/passwd и /etc/shadow
sudo pwck -r

# Проверка /etc/group и /etc/gshadow
sudo grpck -r
```

Флаги `-r` включают только чтение (dry-run), не внося исправления автоматически.

### Массовое создание пользователей (newusers)

Утилита `newusers` принимает файл в формате `/etc/passwd`:

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

### Блокировка и разблокировка учетных записей

```bash
# Блокировка входа по паролю (ставит '!' в /etc/shadow)
sudo passwd -l username

# Разблокировка
sudo passwd -u username

# Полная блокировка учетной записи (через chage)
sudo usermod -L username
sudo chage -E 0 username

# Разблокировка
sudo usermod -U username
sudo chage -E -1 username
```

### Смена командной оболочки (chsh)

```bash
# Просмотр текущего shell
grep "^$(whoami):" /etc/passwd | cut -d: -f7

# Смена shell интерактивно
chsh

# Смена shell напрямую
sudo usermod -s /bin/zsh username
```

### Управление группами через императивные команды

Для детального управления группами (groupadd, groupmod, groupdel, gpasswd) см. **[Управление группами](./group_commands.md)**.

Базовые операции для пользователя:

```bash
# Добавление в группу БЕЗ удаления из текущих (КРИТИЧНО: флаг -a)
sudo usermod -aG docker username

# Добавление в несколько групп
sudo usermod -aG docker,libvirt,kvm username

# Просмотр текущих групп пользователя
groups username
id -Gn username

# Удаление из группы (требует gpasswd или usermod с явным указанием)
sudo gpasswd -d username docker
```

### Управление квотами диска

Для ограничения места на диске используйте `quota`:

```bash
# Установка пакета (Debian/Ubuntu)
sudo apt install quota

# Включение на файловой системе (добавить в /etc/fstab: usrquota,grpquota)
sudo mount -o remount,usrquota,grpquota /

# Инициализация
sudo quotacheck -cugm /
sudo quotaon /

# Просмотр квот пользователя
sudo quota -u username

# Установка мягкой (soft) и жесткой (hard) квоты (64K блоков = 256 MB)
sudo setquota -u username 65536 131072 0 0 /
```

### Планировщик задач (cron/at)

```bash
# Просмотр crontab пользователя
sudo crontab -u username -l

# Редактирование crontab
sudo crontab -u username -e

# Выполнение одноразовой задачи (at)
echo "systemctl restart nginx" | sudo at 03:00 2026-12-31

# Просмотр очереди at
sudo atq
sudo atrm <job-id>
```

### Управление лимитами ресурсов

```bash
# Просмотр всех лимитов текущего пользователя
ulimit -a

# Установка мягкого лимита открытых файлов (только для текущей сессии)
ulimit -n 65536

# Постоянные лимиты через limits.conf
sudo tee -a /etc/security/limits.d/99-custom.conf << 'EOF'
# Формат: domain type item value
*               soft    nofile          65536
*               hard    nofile          131072
*               soft    nproc           4096
username        soft    memlock          unlimited
EOF
```

### Управление сессиями (su, sg, loginctl)

```bash
# Переключение на пользователя с окружением login
su - username

# Выполнение команды от имени пользователя
su - username -c "id && df -h"

# Выполнение команды с временным GID (sg)
sg docker -c "docker images"

# Список сессий пользователя
loginctl list-sessions
loginctl user-status username

# Завершение всех сессий пользователя (force logout)
sudo loginctl terminate-user username

# Включение linger (процессы продолжают работать после logout)
sudo loginctl enable-linger username
sudo loginctl disable-linger username
```

### Инспекция пользователей через userdbctl (systemd v256+)

```bash
# Список всех пользователей в userdb
sudo userdbctl

# Поиск конкретного пользователя
sudo userdbctl username

# Экспорт в JSON
sudo userdbctl --json
```

### Управление счетчиком неудачных входов (faillock)

```bash
# Проверка состояния для пользователя
sudo faillock --user username

# Сброс счетчика
sudo faillock --user username --reset

# Глобальная конфигурация (PAM)
# /etc/security/faillock.conf
deny = 5
unlock_time = 900
```

### Пользовательские systemd-сервисы

Для запуска фоновых задач от имени пользователя используйте `systemd-run --user`:

```bash
# Запуск однократной задачи
systemd-run --user --on-active=10 /usr/local/bin/backup.sh

# Просмотр пользовательских сервисов
systemctl --user list-units

# Включение автозапуска (linger должен быть включен)
systemctl --user enable --now myscript.service
```

### Распространенные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `useradd: UID уже существует` | Попытка занять UID без флага `-o`. | Используйте `-o` или автовыбор. |
| `usermod: пользователь удален из групп` | Использование `-G` без `-a`. | Всегда используйте `-aG`. |
| `Permission denied` при `passwd` | Истек пароль или права. | Используйте `sudo` или проверьте `pam_tally2`/`faillock`. |
| Не создается Home | Пропущен флаг `-m`. | Используйте `usermod -d -m` для исправления. |

### Лучшие практики (2026)

1.  **Декларативность:** Для системных пользователей всегда используйте **[systemd-sysusers](./systemd-sysusers.md)**.
2.  **Портативность:** Для рабочих станций внедряйте **[systemd-homed](./systemd-homed.md)**.
3.  **Безопасность:** Для системных аккаунтов всегда устанавливайте Shell в `/usr/sbin/nologin`.
4.  **Имена:** Системные пользователи должны начинаться с `_` (например, `_nginx`).
5.  **UPG:** Используйте приватные группы (UPG) по умолчанию для ограничения доступа к файлам.
6.  **Безопасное редактирование:** Всегда используйте `vipw`/`vigr` вместо прямого редактирования файлов.
7.  **Целостность:** Периодически запускайте `pwck -r` и `grpck -r` для проверки баз данных.
8.  **Аудит:** Проверяйте `/etc/passwd` на дубликаты UID 0: `awk -F: '$3 == 0 {print $1}' /etc/passwd`.
9.  **Квоты:** Настраивайте дисковые квоты для пользователей с большими объемами данных.
10. **Фоновая активность:** Для сервисных аккаунтов, которым нужны фоновые процессы после выхода, используйте `loginctl enable-linger`.

### Troubleshooting

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `useradd: UID уже существует` | Попытка занять UID без флага `-o`. | Используйте `-o` или автовыбор. |
| `usermod: пользователь удален из групп` | Использование `-G` без `-a`. | Всегда используйте `-aG`. |
| `Permission denied` при `passwd` | Истек пароль или права. | Используйте `sudo` или проверьте `pam_tally2`/`faillock`. |
| Не создается Home | Пропущен флаг `-m`. | Используйте `usermod -d -m` для исправения. |
| `pwck: user ... has no password` | У пользователя пустой пароль. | Установите пароль через `passwd` или заблокируйте через `usermod -L`. |
| `newusers: cannot lock /etc/passwd` | Другой процесс редактирует файл. | Убедитесь, что нет запущенных `vipw`/`useradd`. |
| `su: Authentication failure` | Неверный пароль или PAM блокировка. | Проверьте `faillock --user username`. |
| `ulimit: maximum user processes exceeded` | Превышен лимит процессов. | Увеличьте `nproc` в `/etc/security/limits.d/`. |

### Безопасность и харденинг

1.  **Права на файлы:**
    - `/etc/passwd`: `644` (`root:root`)
    - `/etc/shadow`: `600` или `640` (`root:shadow`)
    - `/etc/group`: `644` (`root:root`)
    - `/etc/gshadow`: `640` (`root:shadow`)

2.  **Пустые пароли:** Запрещены политиками. Проверка: `sudo awk -F: '($2 == "") {print $1}' /etc/shadow`.

3.  **UID 0:** Регулярно проверяйте: `awk -F: '$3 == 0 {print $1}' /etc/passwd`. Должен быть только `root`.

4.  **Оболочки входа:** Удалите неиспользуемые интерпретаторы из `/etc/shells`, чтобы снизить поверхность атаки.

5.  **Sudo-права:** Используйте `sudo` вместо дублирования root. Для временного доступа используйте `run0` (systemd v256+).

6.  **Аудит:** Настройте `auditd` для отслеживания изменений в `/etc/passwd`, `/etc/shadow`, `/etc/group`:
    ```bash
    sudo auditctl -w /etc/passwd -p wa -k passwd_modification
    sudo auditctl -w /etc/shadow -p wa -k shadow_modification
    ```

### Compliance-проверки

```bash
# CIS Benchmark: Поиск пользователей с UID 0
awk -F: '($3 == 0) {print $1}' /etc/passwd

# Поиск пустых паролей
sudo awk -F: '($2 == "" || $2 == "!") {print $1}' /etc/shadow

# Поиск пользователей с непустым shell, но без пароля
awk -F: '($7 != "/sbin/nologin" && $7 != "/bin/false" && $2 == "!") {print $1}' /etc/shadow

# Проверка системных пользователей с интерактивным shell
awk -F: '($3 < 1000 && $3 != 0 && $7 != "/sbin/nologin" && $7 != "/bin/false") {print $1}' /etc/passwd
```

## Дополнительная информация

### Смежные темы

- [Управление группами](./group_commands.md) — `groupadd`, `groupmod`, `gpasswd`, делегирование прав.
- [Политики паролей (chage)](./password_policy_chage.md) — управление сроком действия паролей.
- [Мониторинг сессий](./user_monitoring.md) — `loginctl`, `last`, `lastlog`, `faillock`.
- [Файлы конфигурации](./users_config_files.md) — разбор `/etc/passwd`, `/etc/shadow`, NSSwitch.
- [Определения пользователей и групп](./users_definitions.md) — UID/GID, UPG, User Namespaces.
- [Приватные группы (UPG)](./user_private_groups.md) — архитектура парадигмы User=Group.
- [Перенос пользователей](./user_migration.md) — миграция между системами, remapping UID/GID.
- [Декларативное управление (systemd-sysusers)](./systemd-sysusers.md) — создание системных пользователей через конфиги.
- [Портативные аккаунты (systemd-homed)](./systemd-homed.md) — шифрованные LUKS2-образы для домашних директорий.
- [LDAP и SSSD](./LDAP_SSSD/index.md) — централизованное управление идентификацией.
- [Управление сессиями logind](../../Core/systemd/logind_session_management.md) — linger, inhibitors, сессии.
- [Управление привилегиями (sudo/run0)](../privilege_management.md) — делегирование прав.
