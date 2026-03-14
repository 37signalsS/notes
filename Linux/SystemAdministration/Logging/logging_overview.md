# Обзор системы логирования в Linux

## Определения

**Системные журналы (логи)** — файлы, в которые записываются системные сообщения и события. Анализ логов — ключевой навык для диагностики проблем, отслеживания производительности и расследования инцидентов безопасности.

**Архитектура логирования в современных Linux:**

| Компонент | Назначение |
| :--- | :--- |
| `systemd-journald` | Централизованный сбор логов в бинарном формате | [journald.md](./journald.md) |
| `journalctl` | Просмотр и анализ логов journald | [journalctl.md](../../../Diagnostics/journalctl.md) |
| `rsyslog` | Фильтрация, обработка и пересылка логов | [rsyslog.md](./rsyslog.md) |
| `auditd` | Аудит событий безопасности на уровне ядра | [auditd.md](./auditd.md) |
| `logrotate` | Ротация и архивация текстовых логов | [logrotate](#ротация-логов-logrotate) |

Компоненты работают совместно: `journald` собирает сообщения, `rsyslog` забирает их для фильтрации и пересылки, `logrotate` управляет размером файлов.

## Базовые концепции

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
last -n 10          # Последние 10 записей
last username       # Входы конкретного пользователя
last reboot         # История перезагрузок

# Текущие сессии (читает /var/run/utmp)
who                 # Кто сейчас в системе
w                   # Кто + чем занят
users               # Только имена пользователей

# Время активности (читает /var/log/wtmp)
ac                  # Общее время в часах по пользователям
ac -p username      # Время конкретного пользователя

# Последний вход каждого пользователя (читает /var/log/lastlog)
lastlog             # Все пользователи
lastlog -u username # Конкретный пользователь

# Неудачные попытки входа (читает /var/log/btmp)
lastb               # Требует root
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

- Потребление дискового пространства и I/O
- Угроза безопасности (логи проще удалить/подделать)
- Сложность анализа в больших инфраструктурах
- Отсутствие агрегации и корреляции между хостами

**Решения:**

- Традиционные: `rsyslog` (подробнее в [rsyslog.md](./rsyslog.md))
- Современные: Fluentd, Vector, Kafka, Loki, Elasticsearch

Подробнее о централизованном логировании в контексте наблюдаемости: [Observability and Monitoring](../../../Concepts/Observability_and_Monitoring/observability_overview.md).

### Ротация логов (`logrotate`)

Утилита `logrotate` архивирует, сжимает и удаляет старые логи.

- **Конфигурация:** `/etc/logrotate.conf`, `/etc/logrotate.d/`
- **Пример:** См. [Пример конфигурации logrotate](#пример-конфигурации-logrotate)

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
| `less` | Поиск (`/`, `?`), фильтрация (`&`) |
| `grep` | Поиск по шаблону |
| `zcat` / `zgrep` | Работа со сжатыми логами (`.gz`) |

### Методология диагностики проблем логирования

| Проблема | Порядок диагностики |
| :--- | :--- |
| Сервис не запускается | 1. `journalctl -u <сервис> -b`<br>2. `systemctl status <сервис>`<br>3. `/var/log/<app>/` |
| Ошибки аутентификации | 1. `journalctl -p err -b`<br>2. `/var/log/auth.log` или `/var/log/secure`<br>3. `ausearch -m USER_LOGIN` |
| Проблемы ядра/драйверов | 1. `journalctl -k -b`<br>2. [dmesg -T](../../Diagnostics/Kernel/dmesg/index.md)<br>3. `dmesg --level=err,warn` |
| Дисковое пространство | 1. `journalctl --disk-usage`<br>2. `du -sh /var/log/*`<br>3. Проверка `logrotate` |
| Проблемы загрузки | 1. `journalctl --list-boots`<br>2. `journalctl -b -1`<br>3. [reboot_troubleshooting](../../Diagnostics/Troubleshooting/reboot_troubleshooting.md) |
| Инцидент безопасности | 1. `ausearch -m SYSCALL`<br>2. `/var/log/audit/audit.log`<br>3. `journalctl _UID=0` |

## Дополнительная информация

### Пример конфигурации `logrotate`

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

**Директивы:**

- `daily` — ротация ежедневно
- `rotate 14` — хранить 14 архивов
- `compress` — сжимать архивы
- `postrotate...endscript` — команды после ротации

**Проверка:**

```bash
sudo logrotate -d /etc/logrotate.conf  # "Сухой запуск"
```

### Принудительная синхронизация: `sync`

```bash
sync  # Запись буферов на диск
```

Полезна перед выключением системы или для гарантии записи критических данных.

---

**Файлы по компонентам:**

- journald: [journald.md](./journald.md)
- journalctl: [journalctl.md](../../../Diagnostics/journalctl.md)
- rsyslog: [rsyslog.md](./rsyslog.md)
- auditd: [auditd.md](./auditd.md)
- Анализ сбоев: [Core/processes/troubleshooting.md](../../Core/processes/troubleshooting.md), [Core/kernel/kernel_panic.md](../../Core/kernel/kernel_panic.md)
