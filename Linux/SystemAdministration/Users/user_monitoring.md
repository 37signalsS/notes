# Мониторинг пользователей и сессий

## Определения

- **Сессия (Session)** — период активности пользователя в системе, начинающийся с момента успешной аутентификации и заканчивающийся выходом (logout) или завершением всех связанных процессов.
- **Интерактивный вход** — вход пользователя через терминал (TTY), псевдо-терминал (PTS/SSH) или графическую оболочку.
- **utmp / wtmp / btmp** — специализированные бинарные файлы в каталоге `/var/log` и `/run`, хранящие информацию о текущих сессиях, истории входов и неудачных попытках.
- **`loginctl`** — центральная утилита `systemd` для управления пользователями и их сессиями.
- **Session Recording (Запись сессий)** — механизм фиксации ввода-вывода терминала для последующего аудита (например, через `tlog` или `script`).
- **Real-time Observability (eBPF)** — мониторинг действий пользователей на уровне ядра (системные вызовы) с минимальными накладными расходами.
- **NSS (Name Service Switch)** — механизм диспетчеризации в библиотеке C (glibc), определяющий источники данных для поиска пользователей и групп. Конфигурируется в `/etc/nsswitch.conf`.
- **PAM (Pluggable Authentication Modules)** — модульный фреймворк, через который проходят все события аутентификации и создания сессий.
- **`nscd` (Name Service Cache Daemon)** — демон кэширования запросов NSS (`passwd`, `group`, `hosts`). По умолчанию кэширует `passwd` на 5 минут, что может скрывать актуальные изменения в `/etc/passwd` при мониторинге.
- **SSSD Cache** — кэш службы SSSD для LDAP/AD-пользователей. Обновляется асинхронно; принудительный сброс: `sss_cache -E` или `systemctl restart sssd`.
- **`utmpdump`** — утилита для дампа и восстановления бинарных файлов `utmp`/`wtmp`/`btmp`. Полезна при их повреждении или необходимости forensic-анализа.
- **`ac` / `acct`** — подсистема учета времени подключения (connect time accounting). `ac` показывает суммарное время сессий по пользователям; требует включенного пакета `acct`.
- **`auditd` execve tracking** — отслеживание всех запущенных пользователем команд через перехват системного вызова `execve` на уровне ядра. Обеспечивает неподделимость логов, так как работает ниже пользовательского пространства.
- **Session Types** — классификация сессий `systemd-logind`: `tty`, `x11`, `wayland`, `web`, `manager` (v256+).
- **`XDG_RUNTIME_DIR`** — временная директория в `/run/user/$UID`, создаваемая `pam_systemd.so`. Содержит сокеты D-Bus и файлы состояния сессии. Удаляется при выходе (если linger отключен).
- **`pam_systemd.so`** — PAM-модуль, создающий сессию в `logind` при аутентификации. Отсутствие модуля означает отсутствие cgroup-изоляции и управления сессиями через `loginctl`.
- **`KillUserProcesses`** — параметр `/etc/systemd/logind.conf`, определяющий, завершаются ли процессы пользователя при выходе из последней сессии (`yes`/`no`).
- **Linger** — режим, при котором фоновые процессы пользователя (`systemd --user`) продолжают работать после выхода из всех сессий. Включается через `sudo loginctl enable-linger <user>`.

## Базовые концепции

### Категории информации о пользователях

Для полноценного мониторинга необходимо анализировать данные на нескольких уровнях:

| Тип данных | Описание | Основные команды |
| :--- | :--- | :--- |
| **Идентификаторы** | UID, GID, состав групп (включая сетевые источники). | `id`, `getent`, `groups` |
| **Активные сессии** | Кто сейчас в системе, время входа, IP, TTY. | `who`, `w`, `loginctl`, `users` |
| **История входов** | Журнал успешных и неудачных попыток, перезагрузки. | `last`, `lastb`, `lastlog`, `faillock` |
| **Процессы** | Командные строки, иерархия и время работы. | `ps`, `pgrep`, `htop`, `pstree`, `execsnoop` |
| **Ресурсы** | Потребление CPU, RAM и I/O на пользователя/сессию. | `systemd-cgtop`, `top -u`, `pidstat -u` |
| **Файлы и Сеть** | Открытые файлы, сокеты, владение в ФС. | `find`, `lsof`, `ss -u` |
| **Аудит** | Системные вызовы `execve`, доступ к файлам, изменения в базе пользователей. | `auditd`, `ausearch`, `aureport` |

### Бинарные файлы сессий

Источники данных мониторинга — это не просто логи, а специализированные бинарные файлы с фиксированной структурой:

1. **`/run/utmp`**: Оперативное состояние (кто в сети прямо сейчас). Записывается при каждом логине/логауте. Читается `who`, `w`, `users`. Структура: массив записей `struct utmp` с полями `ut_type`, `ut_pid`, `ut_line`, `ut_id`, `ut_user`, `ut_host`, `ut_exit`, `ut_session`, `ut_tv`, `ut_addr_v6`. Файл пересоздается при каждой загрузке системы.
2. **`/var/log/wtmp`**: Накопительная история успешных входов, перезагрузок и остановок. Записывается при каждом завершении сессии. Читается командой `last`. Поддерживает ротацию (`wtmp.1`, `wtmp.2`).
3. **`/var/log/btmp`**: Журнал неудачных попыток входа (brute-force). Записывается только при неудаче. Читается командой `lastb`. Обычно имеет режим `0600` (только root).
4. **`/var/log/lastlog`**: База данных времени последнего входа для каждой учетной записи (по UID). Читается `lastlog`. На некоторых дистрибутивах использует Berkeley DB; на других — простой бинарный формат. Не является текстовым логом.
5. **Journald**: События `systemd-logind.service` и использование `run0`/`sudo`.
6. **Текстовые логи**: `/var/log/auth.log` (Debian/Ubuntu) или `/var/log/secure` (RHEL).

### NSS-кэширование и его влияние на мониторинг

При работе с централизованными каталогами (LDAP, AD, FreeIPA) информация кэшируется на уровне клиента. Это создает задержку между изменением учетной записи и её отражением в мониторинге:

- **nscd (Name Service Cache Daemon)**: General-purpose кэш. По умолчанию кэширует `passwd` и `group` на 5 минут. При мониторинге изменения вступают в силу с задержкой. Принудительный сброс: `sudo nscd -i passwd`.
- **SSSD**: Специализированный кэш для LDAP/AD. Хранит парольные хэши и атрибуты. Время жизни задается в `sssd.conf` (`ldap_user_search_base`, `cache_credentials`). Для сброса: `sss_cache -E` или перезапуск службы.
- **`getent` vs `cat`**: Всегда используйте `getent passwd user` вместо `cat /etc/passwd | grep user` в скриптах — это гарантирует актуальные данные из всех источников NSS, включая LDAP и SSSD.

### Cgroup-based ресурсный учет

В современных системах с `systemd` каждый пользователь и сессия имеют изолированные контрольные группы. Это позволяет точно измерять потребление ресурсов без скриптового парсинга `ps`:

- **`user-$UID.slice`**: Агрегирует все процессы пользователя во всех сессиях.
- **`session-N.scope`**: Группа процессов конкретной сессии.
- **`user.slice`**: Родительский слайс для всех пользователей.

Для просмотра иерархии:
```bash
systemd-cgls /user.slice/
```

### PAM-аудит и трассировка аутентификации

Каждое событие аутентификации проходит через PAM-стек. Для аудита используются модули:

- **`pam_lastlog.so`**: Вывод информации о последнем входе.
- **`pam_faillock.so`**: Подсчет неудачных попыток (заменил устаревший `pam_tally2`).
- **`pam_tty_audit.so`**: Запись всего ввода-вывода терминала в journald (устаревшая, заменена на `tlog`).
- **`pam_script.so` / `pam_exec.so`**: Запуск внешних скриптов при логине/логауте для интеграции с SIEM.

### Архитектура записи сессий

| Метод | Уровень | Запись | Воспроизведение | Накладные расходы |
| :--- | :--- | :--- | :--- | :--- |
| **tlog** | Ядро (eBPF) / userspace | JSON в journald или файл | `tlog-play` | Минимальные |
| **script** | Userspace | Файл typescript | `scriptreplay` | Средние |
| **auditd execve** | Ядро | Структурированные события в audit.log | `ausearch` / `aureport` | Низкие |
| **pam_tty_audit** | PAM | Журнал терминала в journald | `journalctl` | Высокие (объем логов) |

### Механизмы таймаута простоя

- **`logind.conf` — `StopIdleSessionSec=`** (v252+): Автоматическое завершение простаивающих сессий после указанного времени бездействия.
- **`KillUserProcesses=`**: Завершение всех процессов пользователя при выходе (`yes`/`no`).
- **`IdleAction=`**: Действие при бездействии всей системы (`ignore`, `suspend`, `reboot`, `halt`, `kexec`, `lock`).

### Системные журналы (SSoT)

Информация мониторинга берется из следующих источников:

1.  **`/run/utmp`**: Оперативное состояние (кто в сети прямо сейчас). Читается `who`, `w`, `users`.
2.  **`/var/log/wtmp`**: Накопительная история успешных входов. Читается командой `last`.
3.  **`/var/log/btmp`**: Журнал неудачных попыток (brute-force). Читается командой `lastb`.
4.  **`/var/log/lastlog`**: Дата и время последнего входа для каждой учетной записи. Читается `lastlog`.
5.  **Journald**: События `systemd-logind.service` и использование `run0`/`sudo`.
6.  **Текстовые логи**: `/var/log/auth.log` (Debian/Ubuntu) или `/var/log/secure` (RHEL).

## Практические сценарии

### Проверка идентификаторов и групп

```bash
# UID, GID и все группы пользователя
id username

# Вывод только числовых ID
id -u username  # UID
id -G username  # Все GID дополнительных групп

# Проверка через базу данных NSS (включая LDAP/AD/SSSD)
getent passwd username
# → username:x:1001:1001:Senior Dev:/home/username:/bin/bash

# Просмотр членов конкретной группы (sudo или wheel)
getent group sudo
```

### Мониторинг активных сессий

#### Классические утилиты

```bash
# Кто сейчас в системе (кратко)
who

# Подробная информация (время входа, IP, текущая команда, Load Average)
w

# Список только имен пользователей
users

# Полная сводка со всеми деталями (включая runlevel)
who -a

# Сессии с проверкой статуса терминала (+/- — доступность для записи)
who -T

# Вывод с заголовками и временем бездействия (Idle)
who -Hu
```

**Важно:** `who` читает `/var/run/utmp`. Если сессия не зарегистрирована в `utmp` (некоторые GUI-сессии, нестандартные SSH-конфигурации), `who` её не покажет. Для полной картины используйте `loginctl list-sessions`.

#### Углубленный анализ через `w`

Утилита `w` объединяет данные `uptime`, `who` и `ps`, показывая Load Average и активные процессы пользователей. Подробный разбор флагов, структуры вывода, troubleshooting и скриптовые паттерны см. в **[Утилита `w`](../../Diagnostics/Processes/w.md)**.

Основные паттерны для быстрой диагностики:

```bash
# Без заголовка (для парсинга)
w -h

# С PID процессов
w -p

# Только конкретный пользователь
w username

# Обнаружение аномально высокой нагрузки на терминал (возможен brute-force или майнинг)
w -h | awk 'NR>1 && $4+0 > 5.0 {print $0}'
```

#### Современное управление через systemd (loginctl)

```bash
# Список всех активных сессий (включая графические)
loginctl list-sessions

# Список авторизованных пользователей (включая фоновые процессы)
loginctl list-users

# Детальный статус пользователя (дерево процессов, время входа, cgroup)
loginctl user-status username

# Подробности конкретной сессии (IP, лидер сессии, свойства)
loginctl show-session <SESSION_ID>

# Заблокировать сессию (требует ввода пароля при разблокировке)
sudo loginctl lock-session <SESSION_ID>

# Разблокировать сессию
sudo loginctl unlock-session <SESSION_ID>

# Завершение конкретной сессии
sudo loginctl terminate-session <SESSION_ID>

# Завершение всех сессий и процессов пользователя (Logout)
sudo loginctl terminate-user username
```

### Анализ истории входов

```bash
# Последние входы в систему (считывает /var/log/wtmp)
last

# История входов конкретного пользователя
last username

# Поиск входов с конкретного терминала или IP
last pts/0
last 192.168.1.100

# Фильтрация по времени
last -s 2026-01-01  # С указанной даты
last -s 2026-01-01 -t 2026-02-01  # Диапазон

# Дополнительные флаги last
last -F  # Полные даты и время
last -i  # Показ IP-адресов вместо хостов
last -x  # Записи о выключениях (shutdown) и сменах runlevel

# Неудачные попытки входа (требует прав sudo)
sudo lastb

# Последний вход всех пользователей системы (включая системных)
lastlog
```

#### Глубокий анализ brute-force через `lastb`

```bash
# Топ-10 источников неудачных попыток
sudo lastb | awk '{print $3}' | sort | uniq -c | sort -rn | head -10

# Поиск burst-атак (более 10 попыток с одного IP за 5 минут)
sudo lastb -F -i | awk -v start="2026-09-13 18:00" -v end="2026-09-13 18:05" '
  $4 >= start && $4 <= end {print $3}' | sort | uniq -c | sort -rn | head -10

# Автоматическая блокировка через firewall (пример)
sudo iptables -A INPUT -s 192.168.1.100 -j DROP
```

#### Автоматизация `lastlog` и `last`

```bash
# Пользователи, никогда не входившие в систему (кроме системных)
lastlog -b 0 -t 0 | tail -n +4 | awk '($2 == "**Never") {print $1}'

# Активные пользователи (входили за последние 90 дней)
sudo lastlog -b 90 -t 0 | tail -n +4 | awk '($1 != "**Never") {print $1}'

# Поиск входов в нерабочее время (00:00-06:00)
last -F | awk '$4 >= "00:00" && $4 <= "06:00" && $1 != "reboot" && $1 != "wtmp" {print $0}'
```

### Проверка процессов и ресурсов

```bash
# Все процессы пользователя с полной командной строкой
ps -u username -f

# Процессы в виде дерева с PID
pstree -p username

# Поиск процессов по имени (только PID)
pgrep -u username -l

# Интерактивный мониторинг в реальном времени
top -u username
htop -u username

# Мониторинг потребления ресурсов по контрольным группам (systemd)
# Позволяет видеть нагрузку, создаваемую конкретным пользователем в user.slice
systemd-cgtop
```

#### Per-user мониторинг через `pidstat`

```bash
# Мониторинг CPU и памяти пользователя в реальном времени (интервал 1с)
pidstat -u -r -U username 1

# Вывод в CSV для последующего анализа
pidstat -u -r -U username 1 10 --human > user_stats.csv
```

Подробнее: **[Утилита `pidstat`](../../Diagnostics/Processes/pidstat.md)**.

#### Глубокая наблюдаемость: eBPF и tlog (2026)

Для отслеживания команд без задержек и независимо от Shell-истории:

```bash
# Отслеживание выполнения ВСЕХ новых процессов с указанием UID (execsnoop)
sudo execsnoop-bpfcc -u 1000

# Запись и воспроизведение терминальной сессии (tlog)
# Просмотр записей из journald
tlog-play -r journal -M TLOG_REC=...
```

### Аудит безопасности и авторизаций

```bash
# Анализ событий создания/удаления сессий через journalctl
journalctl -u systemd-logind.service

# Использование sudo конкретным пользователем
journalctl _COMM=sudo | grep username

# Использование run0 (альтернатива sudo в 2026)
journalctl _COMM=systemd-run | grep username

# Поиск ошибок аутентификации и блокировок (faillock)
sudo faillock --user username

# Сброс счетчика неудачных попыток (разблокировка)
sudo faillock --user username --reset
```

#### Аудит через `auditd`: отслеживание команд пользователя

```bash
# Правило: отслеживать все execve для UID 1000
sudo auditctl -a always,exit -F arch=b64 -S execve -F uid=1000 -k user_exec_1000

# Просмотр событий
sudo ausearch -k user_exec_1000 -i --start recent

# Отчет по запущенным командам за сегодня
sudo aureport --exec --start today --uid 1000
```

Подробнее: **[auditd — системный аудит](../Logging/auditd.md)**.

#### Аудит изменений в базе пользователей

```bash
# Отслеживание изменений /etc/passwd, /etc/shadow, /etc/group
sudo auditctl -w /etc/passwd -p wa -k passwd_modification
sudo auditctl -w /etc/shadow -p wa -k shadow_modification
sudo auditctl -w /etc/group -p wa -k group_modification

# Поиск событий
sudo ausearch -k passwd_modification -i
```

#### Аудит SSH-входов

```bash
# Успешные входы через SSH (journalctl)
journalctl -u sshd --grep="Accepted" --since "1 hour ago"

# Неудачные попытки SSH
journalctl -u sshd --grep="Failed" --since "1 hour ago"

# Топ-10 IP по неудачным попыткам
journalctl -u sshd --grep="Failed" | grep -oP 'from \K[0-9.]+' | sort | uniq -c | sort -rn | head -10
```

#### Восстановление поврежденного `utmp`

```bash
# Дамп бинарного файла в текстовый формат
sudo utmpdump /var/run/utmp > /tmp/utmp_dump.txt

# Если файл поврежден, перезагрузите систему (utmp пересоздается при загрузке)
# Для срочной очистки без перезагрузки используйте utmpdump + utmpdump -r (осторожно)
sudo utmpdump -r /tmp/utmp_dump.txt > /var/run/utmp
sudo chmod 644 /var/run/utmp
```

### Учет времени подключения (`ac`)

```bash
# Суммарное время сессий по пользователям за сегодня
ac -d

# Суммарное время для конкретного пользователя
ac username

# С детализацией по дням
ac -d username

# Исключить пользователя из отчета
ac -d --exclude root
```

### Проверка владения файлами и активности

```bash
# Поиск файлов пользователя во всей системе (с подавлением ошибок)
sudo find / -user username 2>/dev/null | head -n 20

# Список открытых файлов пользователя (сетевые сокеты, файлы данных)
sudo lsof -u username

# Только сетевые соединения пользователя
sudo lsof -i -u username
```

### Мониторинг пользователей в контейнерах

```bash
# Проверка UID/GID маппинга в контейнере
podman inspect <container> | jq '.[0].HostConfig.UsernsMode'

# Поиск процессов контейнера с владельцем
ps -eo pid,user,comm | grep containerd
```

## Дополнительная информация

### Принудительное управление активностью

В случае обнаружения нелегитимной активности:

1.  **Через `loginctl` (Рекомендуется):**
    ```bash
    # Завершение конкретной сессии
    sudo loginctl terminate-session <ID>
    # Завершение всех сессий и процессов пользователя (Logout)
    sudo loginctl terminate-user username
    ```
2.  **Классический метод через `kill`:**
    ```bash
    # Послать SIGTERM всем процессам пользователя
    sudo kill -15 -u username
    # Принудительное завершение (SIGKILL)
    sudo kill -9 -u username
    ```

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

# Проверка linger для пользователей с сервисами
while IFS=: read -r user _; do
    lingering=$(sudo loginctl show-user "$user" -p Linger 2>/dev/null | cut -d= -f2)
    if [ "$lingering" = "no" ] && systemctl --user -q list-units --type=service --state=running --no-pager --all | grep -q .; then
        echo "WARNING: $user has user services but linger is disabled"
    fi
done < <(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1}')
```

### Централизация мониторинга

Для предприятий требуется сбор событий со всех узлов:

```bash
# Пример rsyslog: пересылка auth.log и auditd на центральный сервер
# /etc/rsyslog.d/30-centralized.conf
*.* @logcentral.example.com:514

# Пример Vector: сбор journald и файлов
# vector.toml
[sources.user_audit]
type = "journald"
include_units = ["sshd", "systemd-logind"]

[sinks.elasticsearch]
type = "elasticsearch"
inputs = ["user_audit"]
```

### Лучшие практики (2026)

1.  **Мониторинг `Linger`**: Проверьте, разрешено ли пользователю оставлять процессы после выхода: `loginctl show-user username -p Linger`.
2.  **Аудит Brute-force**: Регулярно запускайте `lastb` или настройте `fail2ban`.
3.  **Аудит действий через `auditd`**: Для критических серверов настройте аудит системных вызовов `execve` для всех пользователей с UID >= 1000. Подробнее см. [auditd — системный аудит](../Logging/auditd.md).
4.  **Централизация**: Пересылайте `/var/log/audit/audit.log` и логи входов на удаленный сервер (Vector/ELK).
5.  **NSS-awareness**: Используйте `getent` вместо прямого чтения `/etc/passwd` в скриптах.
6.  **UTMP Integrity**: Периодически проверяйте `/run/utmp` на целостность: `sudo utmpdump /var/run/utmp | head`.
7.  **Session Recording**: В high-security средах включите `tlog` для всех критических пользователей.
8.  **Idle Management**: Настройте `StopIdleSessionSec=` в `logind.conf` для автоматической очистки неактивных сессий.
9.  **Cgroup Visibility**: Используйте `systemd-cgtop` или `ps -eo user,group,cgroup` для корреляции процессов с пользователями.
10. **Резервное копирование**: Регулярно создавайте бэкапы `/var/run/utmp`, `/var/log/wtmp`, `/var/log/btmp` для возможности восстановления после инцидентов.

### Сценарий автоматизации: Отчет по пользователю

```bash
#!/bin/bash
# user_report.sh - Расширенный отчет по активности
USER=$1
[ -z "$USER" ] && { echo "Usage: $0 <username>"; exit 1; }

echo "=== ОТЧЕТ ПО ПОЛЬЗОВАТЕЛЮ: $USER [$(date)] ==="
echo "--- Идентификаторы ---"
id "$USER"
echo "--- Активные сессии ---"
w "$USER"
echo "--- Статус systemd-logind ---"
loginctl user-status "$USER" --no-pager
echo "--- Последние входы (last) ---"
last -n 5 "$USER"
echo "--- Попытки взлома (faillock) ---"
sudo faillock --user "$USER"
echo "--- Открытые соединения (lsof) ---"
sudo lsof -i -u "$USER"
echo "--- Занятое место в Home ---"
sudo du -sh /home/"$USER" 2>/dev/null || echo "N/A"
```

### Типовые проблемы

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `w` показывает только текущего пользователя | Включен `hidepid` в `/proc` | `grep hidepid /proc/mounts`, используйте `sudo` |
| Поле `FROM` отображается `-` для SSH | `UseDNS no` в `sshd_config` | Включите `UseDNS yes` или используйте `w -n` |
| `last` не показывает старые записи | Ротация логов (logrotate) | Проверьте `/var/log/wtmp.*` |
| `lastb` пустой | `btmp` не записывается | Проверьте `auditd` или `pam_tty_audit` |
| `lastlog` не обновляется | Проблемы с PAM или NSS | Проверьте `pam_lastlog.so` в PAM-стеке |
| `faillock` не блокирует | Отключен `pam_faillock.so` | Проверьте `/etc/pam.d/common-auth` |
| `loginctl: Failed to connect to bus` | Нет `$XDG_RUNTIME_DIR` | Используйте `sudo` или проверьте `pam_systemd.so` |
| `utmp` поврежден | Некорректное завершение работы | `utmpdump -r` или перезагрузка |
| `nscd` показывает устаревшие данные | Кэш не истек | `sudo nscd -i passwd` или перезапуск |
| `sssd` показывает неактуальных пользователей | Кэш не сброшен | `sss_cache -E` или `systemctl restart sssd` |
| `getent` не видит пользователя | NSS не настроен | Проверьте `/etc/nsswitch.conf` |
| `ac` не показывает данные | Подсистема учета отключена | Включите `acct` через `systemctl enable --now acct` |
| `auditd` не пишет события | Буфер переполнен или правила не загружены | `auditctl -s`, `auditctl -l` |

### Граничные случаи и ограничения

1.  **Графические сессии в `utmp`:** Некоторые окружения GNOME/KDE не регистрируют сессии в `utmp`. Используйте `loginctl list-sessions` как источник истины.
2.  **NFS-домашние директории:** При монтировании NFS с `root_squash`, `find / -user username` может возвращать `Permission denied`. Используйте `sudo` или настройку `no_root_squash`.
3.  **Контейнеры:** Внутри контейнера `w`/`who` работают в изоляции namespace. Для мониторинга пользователей хоста требуются права на `/proc` хоста.
4.  **hidepid:** При монтировании `/proc` с `hidepid=2`, обычный пользователь видит только свои процессы. Это влияет на `w`, `ps`, `pgrep`.
5.  **SSH с `ForceCommand`:** Поле `WHAT` в `w` показывает принудительную команду, а не оболочку.
6.  **tmux/screen:** `w` показывает `tmux: client` или `screen` как текущий процесс. Для деталей используйте `tmux list-sessions` / `screen -ls`.
7.  **Подмена `argv[0]`:** Опытные пользователи могут изменять `argv[0]` своих процессов, что отразится в поле `WHAT`. Для верификации используйте `readlink /proc/<PID>/exe`.
8.  **`XDG_RUNTIME_DIR` в `sudo`:** При использовании `sudo` переменная окружения не наследуется по умолчанию. Для D-Bus-приложений используйте `sudo -E` или настройте `env_keep`.
9.  **Ротация `wtmp`/`btmp`:** Логи могут ротироваться (logrotate). Для анализа старых данных проверяйте `/var/log/wtmp.*` и `/var/log/btmp.*`.
10. **Миграция UID:** При изменении UID пользователя старые записи в `wtmp`/`lastlog` привязаны к старому UID и не будут найдены `last`/`lastlog` под новым именем.

### Откат (Rollback)

При ошибках конфигурации auditd или повреждении utmp:

```bash
# Очистка правил auditd
sudo auditctl -D

# Восстановление utmp из дампа
sudo utmpdump -r /tmp/utmp_dump.txt > /var/run/utmp
sudo chmod 644 /var/run/utmp

# Перезагрузка служб
sudo systemctl restart systemd-logind
```

### Смежные темы

- [Управление пользователями](./user_commands.md) — создание и модификация учетных записей.
- [Управление сессиями logind](../../Core/systemd/logind_session_management.md) — linger, inhibitors, сессии.
- [Утилита `w`](../../Diagnostics/Processes/w.md) — детальный разбор `w`, нагрузка, troubleshooting.
- [Утилита `ps`](../../Diagnostics/Processes/ps.md) — детальный анализ процессов.
- [Утилита `pidstat`](../../Diagnostics/Processes/pidstat.md) — per-user/per-process мониторинг CPU и памяти.
- [Аудит действий через auditd](../Logging/auditd.md) — системный аудит на уровне ядра.
- [Журналирование (journald)](../Logging/journald.md) — работа с системным журналом.
- [PAM (Pluggable Authentication Modules)](../../Security/pam_overview.md) — механизмы аутентификации.
