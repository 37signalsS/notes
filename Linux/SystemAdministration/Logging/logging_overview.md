# Обзор системы логирования в Linux

## Определения

**Системные журналы (логи)** — файлы, в которые записываются системные сообщения и события. Анализ логов — ключевой навык для диагностики проблем, отслеживания производительности и расследования инцидентов безопасности.

**Архитектура логирования в современных Linux:**

| Компонент | Назначение | Основной документ |
| :--- | :--- | :--- |
| `systemd-journald` | Централизованный сбор логов в бинарном формате | [journald](./journald.md) |
| `journalctl` | Просмотр и анализ логов journald | [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) |
| `rsyslog` | Фильтрация, обработка и пересылка логов | [rsyslog](./rsyslog.md) |
| `auditd` | Аудит событий безопасности на уровне ядра | [auditd](./auditd.md) |
| `logrotate` | Ротация и архивация текстовых логов | [logrotate](#ротация-логов) |

Компоненты работают совместно: `journald` собирает сообщения, `rsyslog` забирает их для фильтрации и пересылки, `logrotate` управляет размером файлов.

## Базовые концепции

### Расположение логов в Linux

В современных Linux-системах логи записываются в несколько мест одновременно, в зависимости от конфигурации и типа события:

| Расположение | Описание |
| :--- | :--- |
| `/var/log/journal/` | Постоянные (persistent) журналы `systemd-journald` — бинарные файлы |
| `/run/log/journal/` | Временные (volatile) журналы `systemd-journald` — очищаются при перезагрузке |
| `/var/log/syslog` (Debian/Ubuntu) или `/var/log/messages` (RHEL/CentOS) | Главный системный лог в текстовом формате |
| `/var/log/auth.log` (Debian/Ubuntu) или `/var/log/secure` (RHEL/CentOS) | События аутентификации (SSH — Secure Shell, sudo — Substitute User and do, PAM — Pluggable Authentication Modules) |
| `/var/log/kern.log` | Сообщения ядра (дублируются из `dmesg`) |
| `/var/log/dmesg` | Сообщения ядра при загрузке |
| `/var/log/boot.log` | Лог процесса загрузки системы |
| `/var/log/audit/audit.log` | Журнал аудита безопасности (`auditd`) |
| `/var/log/nginx/`, `/var/log/apache2/`, `/var/log/postgresql/`, `/var/log/mysql/` | Логи приложений (каждое приложение пишет в свою директорию) |
| `/var/log/cron.log` | Логи планировщика `cron` (если включено) |
| `/var/log/wtmp`, `/var/run/utmp`, `/var/log/btmp`, `/var/log/lastlog` | Журналы входов пользователей (двоичные файлы) |

По умолчанию `systemd-journald` собирает все сообщения в бинарный журнал. Служба `rsyslog` (если установлена) забирает сообщения из `journald` и записывает их в текстовые файлы `/var/log/`.

### Форматы журналов

В Linux логи записываются в нескольких форматах:

| Формат | Где используется | Описание |
| :--- | :--- | :--- |
| **Бинарный журнал (structured binary)** | `systemd-journald` | Каждая запись — набор пар `ключ=значение` с метаданными (PID — Process ID, UID — User ID, юнит, приоритет, время, исполняемый файл). Индексирован для быстрого поиска |
| **Syslog (RFC 5424 / RFC 3164)** | `rsyslog`, legacy-приложения | Текстовый формат: `<приоритет>дата хост процесс[PID]: сообщение`. RFC (Request for Comments) — стандарты интернета |
| **Plain text (произвольный)** | Приложения (nginx, apache, postgresql) | Каждая строка — запись. Формат зависит от приложения: Common Log Format, combined, custom |
| **JSON (структурированный)** | Современные приложения, контейнеры | `{"timestamp":"...", "level":"info", "message":"...", "service":"..."}`. JSON (JavaScript Object Notation) — удобен для автоматизации |
| **Двоичные файлы (binary)** | `wtmp`, `utmp`, `btmp`, `lastlog`, файлы журнала `journald` | Не читаемы текстовыми редакторами, требуют специальных утилит (`last`, `who`, `journalctl`) |

**Рекомендация для production (промышленной эксплуатации):** использовать структурированное логирование (JSON) в приложениях — это упрощает автоматизированный анализ, корреляцию событий и интеграцию с централизованными системами (ELK — Elasticsearch, Logstash, Kibana, Loki).

### Инструменты для просмотра логов

| Инструмент | Что показывает | Когда использовать |
| :--- | :--- | :--- |
| **`journalctl`** | Логи `systemd-journald` (ядро, сервисы, приложения) | Основной инструмент для системных логов. Фильтрация по юниту, времени, приоритету, PID. Подробнее: [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) |
| **`dmesg`** | Сообщения ядра (буфер ring buffer) | Диагностика драйверов, оборудования, проблем загрузки. Подробнее: [dmesg](../../Diagnostics/Kernel/dmesg/index.md) |
| **`tail -f /var/log/...`** | Текстовые логи в реальном времени | Быстрый просмотр логов приложений (nginx, mysql, cron) |
| **`grep`, `zgrep`, `zcat`** | Поиск по текстовым логам (в т.ч. сжатым `.gz`) | Поиск ошибок, паттернов в архивных логах |
| **`less`** | Постраничный просмотр с поиском (`/`, `?`) и фильтрацией (`&`) | Интерактивный анализ больших текстовых логов |
| **`last`, `lastb`, `who`, `w`** | Журналы входов пользователей (`wtmp`, `btmp`, `utmp`) | Аудит доступа, обнаружение несанкционированных входов |
| **`ausearch`** | Журнал аудита `auditd` (`/var/log/audit/audit.log`) | Детальный аудит безопасности, системных вызовов. Подробнее: [auditd](./auditd.md) |
| **`coredumpctl`** | Дампы памяти аварийно завершённых процессов | Анализ причин сбоев приложений |

### Категории журналов безопасности

В контексте безопасности Linux журналы делятся на три категории:

| Категория | Файлы | Назначение | Инструменты просмотра |
| :--- | :--- | :--- | :--- |
| **Журналы входа пользователей** | `/var/log/wtmp`, `/var/run/utmp` | История входов пользователей, текущие сессии | `last`, `who`, `users`, `ac`, `lastlog` |
| **Журналы специальных событий** | `/var/log/auth.log` (Debian), `/var/log/secure` (RHEL), `/var/log/messages` | Аутентификация, авторизация, системные события | `journalctl`, `grep`, `ausearch` |
| **Журналы процессов** | `/var/log/pacct` | История выполненных команд (при включённом `acct`) | `lastcomm`, `ac` |

#### Журналы входа пользователей

| Файл | Описание | Команда |
| :--- | :--- | :--- |
| `/var/log/wtmp` | История всех входов/выходов (двоичный) | `last` |
| `/var/run/utmp` | Текущие активные сессии (двоичный) | `who`, `w`, `users` |
| `/var/log/btmp` | Неудачные попытки входа (двоичный) | `lastb` |
| `/var/log/lastlog` | Последний вход каждого пользователя | `lastlog` |

**Команды для анализа:**

```bash
# История входов (читает /var/log/wtmp)
last
# → user     pts/0        192.168.1.10     Mon Jan 01 10:00   still logged in
last -n 10          # Последние 10 записей
last username       # Входы конкретного пользователя
last reboot         # История перезагрузок

# Текущие сессии (читает /var/run/utmp)
who                 # Кто сейчас в системе
# → user     pts/0        2026-01-01 10:00 (192.168.1.10)
w                   # Кто + чем занят
# → 10:00:01 up 1 day, user 1, load average: 0.00, 0.01, 0.05
users               # Только имена пользователей
# → user1 user2

# Время активности (читает /var/log/wtmp)
ac                  # Общее время в часах по пользователям
# → total      120.50
ac -p username      # Время конкретного пользователя

# Последний вход каждого пользователя (читает /var/log/lastlog)
lastlog             # Все пользователи
# → Username         Port     From             Latest
# → root             pts/0    192.168.1.10     Mon Jan 01 10:00:00 +0000 2026
lastlog -u username # Конкретный пользователь

# Неудачные попытки входа (читает /var/log/btmp)
lastb               # Требует root
# → user     ssh:notty    192.168.1.11     Mon Jan 01 11:00 - 11:00  (00:00)
```

#### Журналы специальных событий

| Файл | Дистрибутив | Описание |
| :--- | :--- | :--- |
| `/var/log/auth.log` | Debian/Ubuntu | События аутентификации (SSH, sudo, PAM) |
| `/var/log/secure` | RHEL/CentOS | Аналогично `auth.log` |
| `/var/log/messages` | RHEL/CentOS | Общие системные сообщения |
| `/var/log/syslog` | Debian/Ubuntu | Аналогично `messages` |
| `/var/log/faillog` | Все | Неудачные попытки входа |

**Примеры анализа:**

```bash
# Попытки входа по SSH
grep sshd /var/log/auth.log

# Неудачные попытки sudo
grep sudo /var/log/auth.log | grep failed

# Просмотр через journalctl
journalctl -t sshd
journalctl -t sudo

# Поиск подозрительной активности
grep -i "failed\|invalid\|error" /var/log/auth.log
```

### Стандартные файлы и директории логов

Большинство служб пишут логи в `/var/log/` (поведение настраивается через `rsyslog`):

| Файл/Директория | Описание |
| :--- | :--- |
| `/var/log/syslog` (Debian/Ubuntu) или `/var/log/messages` (RHEL/CentOS) | Главный системный лог |
| `/var/log/auth.log` (Debian/Ubuntu) или `/var/log/secure` (RHEL/CentOS) | События аутентификации (SSH, sudo). Для детального аудита см. [auditd](./auditd.md) |
| `/var/log/dmesg` | Сообщения ядра при загрузке. Подробнее: [dmesg](../../Diagnostics/Kernel/dmesg/index.md) |
| `/var/log/boot.log` | Лог процесса загрузки |
| `/var/log/apt/` или `/var/log/yum.log` | Логи менеджера пакетов |
| `/var/log/nginx/`, `/var/log/apache2/`, `/var/log/postgresql/` | Логи приложений |

### Централизованное логирование

**Проблемы локального хранения:**

- Потребление дискового пространства и I/O (Input/Output — ввод/вывод)
- Угроза безопасности (логи проще удалить/подделать)
- Сложность анализа в больших инфраструктурах
- Отсутствие агрегации и корреляции между хостами

**Решения:**

- Традиционные: `rsyslog` (подробнее в [rsyslog.md](./rsyslog.md))
- Современные: Fluentd, Vector, Kafka, Loki, Elasticsearch

Подробнее о централизованном логировании в контексте наблюдаемости: [Observability and Monitoring](../../../Concepts/Observability_and_Monitoring/observability_definitions.md).

### Ротация логов

Утилита **`logrotate`** — автоматическая ротация, сжатие и удаление логов в Linux. Ограничивает рост файлов: переносит старые логи, сжимает их, удаляет устаревшие копии и при необходимости выполняет команды после ротации.

- **Запуск:** не работает постоянно в фоне. Запускается cron (`/etc/cron.daily/logrotate`) или systemd-таймер (`logrotate.timer`), обычно раз в сутки. При запуске читает конфиги, проверяет условия ротации и выполняет действия.
- **Конфигурация:** `/etc/logrotate.conf` (глобальные настройки), `/etc/logrotate.d/` (конфиги для каждого сервиса)
- **Пример:** См. [Пример конфигурации logrotate](#пример-конфигурации-logrotate)

#### Стратегии ротации

| Стратегия | Механизм | Плюсы | Минусы |
| :--- | :--- | :--- | :--- |
| **Стандартная (`postrotate`)** | `mv` старого файла → создание нового → `kill -HUP` сервису | Не теряет строки | Сервис должен поддерживать SIGHUP (Signal Hang Up) |
| **`copytruncate`** | Копирует лог в архив → обнуляет оригинал | Сервис не нужно перезапускать, дескриптор не меняется | Небольшое окно между копированием и обнулением — часть строк может потеряться |

**Когда использовать `copytruncate`:** Сервис не поддерживает переоткрытие логов по сигналу. Пример:

```conf
/var/log/app.log {
    daily
    rotate 7
    compress
    copytruncate
}
```

**Когда использовать `postrotate` + SIGHUP:** Потеря строк недопустима. Сервис должен поддерживать сигнал для переоткрытия логов (nginx: `nginx -s reopen`).

```conf
/var/log/nginx/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 $(cat /var/run/nginx.pid)
    endscript
}
```

**Проблема при неправильной ротации:** Если `logrotate` удаляет файл (`rm`), а сервис продолжает держать дескриптор открытым, процесс пишет в удалённый файл. Место на диске не освобождается, `df` и `du` показывают расхождение. Диагностика: [Удалённые открытые файлы](../../Diagnostics/Filesystem/filesystem_and_disk_space_diagnostics.md#механизм-удалённых-открытых-файлов).

## Практические сценарии

### Отправка тестовых сообщений: `logger`

```bash
# Базовое сообщение
logger "Тестовое сообщение"

# С указанием facility и priority
logger -t myscript -p local0.info "Скрипт выполнен успешно"

# На удаленный сервер
logger -n 192.168.1.100 -p local0.info "Удаленное сообщение"
```

**Параметры:**

- `-t tag` — тег сообщения (имя скрипта/процесса)
- `-p facility.priority` — категория и уровень (например, `local0.info`)
- `-n server` — отправка на удаленный хост

### Анализ логов: базовые утилиты

| Утилита | Назначение |
| :--- | :--- |
| `tail -f` | Просмотр в реальном времени |
| `tac` | Вывод файла задом наперёд (свежие записи сверху) |
| `less` | Поиск (`/`, `?`), фильтрация (`&`) |
| `grep` | Поиск по шаблону |
| `zcat` / `zgrep` | Работа со сжатыми логами (`.gz`) |

### Методология диагностики проблем логирования

| Проблема | Порядок диагностики |
| :--- | :--- |
| Сервис не запускается | 1. `journalctl -u <сервис> -b`<br>2. `systemctl status <сервис>`<br>3. `/var/log/<app>/` |
| Ошибки аутентификации | 1. `journalctl -p err -b`<br>2. `/var/log/auth.log` или `/var/log/secure`<br>3. `ausearch -m USER_LOGIN` |
| Проблемы ядра/драйверов | 1. `journalctl -k -b`<br>2. [dmesg -T](../../Diagnostics/Kernel/dmesg/index.md)<br>3. `dmesg --level=err,warn` |
| Дисковое пространство | 1. `journalctl --disk-usage`<br>2. [Очистка журнала](../../Diagnostics/journalctl/journalctl_management.md)<br>3. `du -sh /var/log/*`<br>4. Проверка `logrotate` |
| Проблемы загрузки | 1. `journalctl --list-boots`<br>2. `journalctl -b -1`<br>3. [reboot_troubleshooting](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) |
| Инцидент безопасности | 1. `ausearch -m SYSCALL`<br>2. `/var/log/audit/audit.log`<br>3. `journalctl _UID=0` |

## Дополнительная информация

### Пример конфигурации `logrotate`

**Пример для Nginx:**

```conf
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 nginx adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}
```

**Пример для приложения (`/etc/logrotate.d/myapp`):**

```conf
/var/log/myapp/*.log {
    daily
    rotate 14
    maxsize 100M
    compress
    delaycompress
    missingok
    notifempty
    create 0640 myapp myapp
    sharedscripts
    postrotate
        systemctl reload myapp >/dev/null 2>&1 || true
    endscript
}
```

**Директивы:**

| Директива | Описание |
| :--- | :--- |
| `daily` / `weekly` / `monthly` | Периодичность проверки ротации |
| `rotate N` | Хранить N архивных копий |
| `maxsize 100M` | Ротировать при проверке, если файл превысил 100 МБ |
| `compress` | Сжимать старые логи (gzip) |
| `delaycompress` | Сжимать файл на следующем цикле ротации |
| `missingok` | Продолжать работу, если лог-файл отсутствует |
| `notifempty` | Не ротировать пустой файл |
| `create 0640 owner group` | Создать новый лог-файл с заданными правами и владельцем |
| `sharedscripts` | Выполнить `postrotate` один раз для всей группы файлов |
| `postrotate ... endscript` | Команды после ротации |

**Команды:**

```bash
# Проверить конфиг без изменений (dry-run)
logrotate -d /etc/logrotate.d/myapp

# Принудительно запустить ротацию, игнорируя расписание
sudo logrotate -f /etc/logrotate.conf

# Подробный вывод того, что происходит
sudo logrotate -v /etc/logrotate.conf
```

### Принудительная синхронизация: `sync`

```bash
sync  # Запись буферов на диск
```

Полезна перед выключением системы или для гарантии записи критических данных.

### Связанные компоненты и основные документы

- **journald / journalctl:** [journald](./journald.md), [journalctl](../../Diagnostics/journalctl/journalctl_overview.md)
- **rsyslog:** [rsyslog](./rsyslog.md)
- **auditd:** [auditd](./auditd.md)
- **Утилиты для работы с текстом:** [tac](../../Shell/tac.md) (вывод задом наперёд), [grep](../../Shell/grep.md)
- **Анализ сбоев и паники ядра:** [**Анализ ошибок и сбоев**](./error_and_crash_analysis.md), [**Паника ядра**](../../Core/kernel/kernel_panic.md)
- **Централизованное логирование:** [observability_definitions](../../../Concepts/Observability_and_Monitoring/observability_definitions.md)
