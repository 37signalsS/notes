# Логирование cron-задач и скриптов

## Определения

**Логирование cron-задач и shell-скриптов** — процесс записи результатов выполнения запланированных задач и произвольных скриптов в систему логирования Linux. Позволяет отслеживать, что выполнялось, когда и с каким результатом, что критично для аудита, отладки и мониторинга.

**Проблема:** по умолчанию вывод cron-задач отправляется пользователю по email (через `MAILTO`), что ненадёжно и не централизовано. Современный подход — перенаправление вывода в journald или файлы.

## Базовые концепции

### Каналы логирования для cron/скриптов

| Канал | Механизм | Плюсы | Минусы |
|:---|:---|:---|:---|
| **journald** | `logger`, `systemd-cat` | Централизовано, структурировано, индексировано | Требует systemd |
| **Файл** | `>> /var/log/script.log` | Просто, наглядно | Нет ротации, ручная настройка |
| **Syslog** | `logger -p facility.priority` | Интеграция с rsyslog/syslog-ng | Ограниченный формат |
| **Email** | `MAILTO` в crontab | Встроен в cron | Ненадёжно, не масштабируется |

### Утилита `logger`

`logger` — стандартная утилита Linux для отправки сообщений в syslog/journald.

```bash
# Базовый синтаксис
logger [опции] сообщение

# Основные параметры
-p FACILITY.PRIORITY  # Уровень (local0.info, user.err)
-t TAG                # Тег (имя программы)
--id PID             # Добавить PID
-n SERVER             # Отправить на удалённый сервер
-P PORT              # Порт удалённого сервера
-d                   # UDP (по умолчанию TCP)
-T                   # TCP
```

## Практические сценарии

### Сценарий 1: Базовое логирование cron-задачи

```bash
# crontab -e
# Логирование в journald
0 2 * * * /opt/scripts/backup.sh 2>&1 | logger -t backup-script -p local0.info

# С разделением stdout и stderr
0 3 * * * /opt/scripts/cleanup.sh >> /var/log/cleanup.log 2>&1

# С отправкой в syslog
0 4 * * * /opt/scripts/rotate-logs.sh 2>&1 | logger -t logrotate-custom -p local0.notice
```

### Сценарий 2: Структурированные JSON-логи из скриптов

```bash
#!/bin/bash
# /opt/scripts/backup.sh

LOG_TAG="backup-script"
LOG_LEVEL="info"

log_json() {
    local level="$1"
    local msg="$2"
    shift 2
    local extra=""
    while [ $# -gt 0 ]; do
        extra="${extra},\"${1%%=*}\":\"${1#*=}\""
        shift
    done
    echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",\"level\":\"${level}\",\"service\":\"${LOG_TAG}\",\"message\":\"${msg}\"${extra}}"
}

# Начало бэкапа
log_json "info" "backup_started" "type=full" "target=/backup" | logger -t $LOG_TAG -p local0.info

START=$(date +%s)

# Выполнение бэкапа
if tar czf /backup/db-$(date +%Y%m%d).tar.gz /var/lib/postgresql 2>/dev/null; then
    END=$(date +%s)
    DURATION=$((END - START))
    SIZE=$(du -sh /backup/db-$(date +%Y%m%d).tar.gz | cut -f1)
    log_json "info" "backup_completed" "duration=${DURATION}s" "size=${SIZE}" | logger -t $LOG_TAG -p local0.info
else
    log_json "error" "backup_failed" "exit_code=$?" | logger -t $LOG_TAG -p local0.err
    exit 1
fi
```

### Сценарий 3: Логирование через systemd-cat (для скриптов без systemd unit)

```bash
#!/bin/bash
# /opt/scripts/maintenance.sh

# Отправка stdout в journald
exec > >(systemd-cat -t maintenance-script -p local0.info) 2>&1

echo "Начало технического обслуживания"
echo "Время: $(date)"
echo "Хост: $(hostname)"

# Выполнение операций
apt-get update && apt-get upgrade -y

echo "Техническое обслуживание завершено"
```

### Сценарий 4: Централизованное логирование cron через rsyslog

```conf
# /etc/rsyslog.d/30-cron-local.conf

# Все сообщения от cron-скриптов в отдельный файл
:programname, isequal, "backup-script" /var/log/cron/backup.log
:programname, isequal, "cleanup-script" /var/log/cron/cleanup.log
:programname, isequal, "maintenance-script" /var/log/cron/maintenance.log

# Общий файл для всех cron-скриптов
if $programname startswith "script-" then /var/log/cron/all-scripts.log
& stop
```

```bash
# /etc/logrotate.d/cron-scripts
/var/log/cron/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate 2>/dev/null || systemctl restart rsyslog >/dev/null 2>&1 || true
    endscript
}
```

### Сценарий 5: Логирование через systemd timer (вместо cron)

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Database backup
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/scripts/backup.sh
StandardOutput=journal
StandardError=journal
SyslogIdentifier=backup-script
```

```ini
# /etc/systemd/system/backup.timer
[Unit]
Description=Daily backup timer

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Просмотр логов
journalctl -u backup.service --since today
# Или по тегу
journalctl -t backup-script --since today
```

### Сценарий 6: Скрипт с логированием и алертингом

```bash
#!/bin/bash
# /opt/scripts/disk_check.sh

set -euo pipefail

LOG_TAG="disk-check"
THRESHOLD=90

check_disk() {
    local usage=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
    local host=$(hostname)
    
    if [ "$usage" -gt "$THRESHOLD" ]; then
        echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",\"level\":\"critical\",\"service\":\"${LOG_TAG}\",\"message\":\"Disk usage above threshold\",\"host\":\"${host}\",\"usage_percent\":${usage},\"threshold\":${THRESHOLD}}"
        # Алерт
        echo "CRITICAL: Disk usage ${usage}% on ${host}" | mail -s "Disk Alert" admin@example.com
    else
        echo "{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",\"level\":\"info\",\"service\":\"${LOG_TAG}\",\"message\":\"Disk usage OK\",\"host\":\"${host}\",\"usage_percent\":${usage}}"
    fi
}

check_disk | logger -t $LOG_TAG -p local0.info
```

## Диагностика

### Просмотр логов cron-задач

```bash
# Все cron-сообщения
journalctl -t CRON --since "1 hour ago"

# Конкретный скрипт
journalctl -t backup-script --since today

# Ошибки выполнения
journalctl -p err --since "1 hour ago" | grep -i cron

# syslog
grep backup-script /var/log/syslog

# Классические логи cron
grep CRON /var/log/syslog
```

### Типичные проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Нет логов в journald** | `2>&1` не перенаправлен | Добавить `2>&1 \| logger -t tag` |
| **Вывод дублируется** | И `MAILTO`, и `logger` | Убрать `MAILTO` или установить `MAILTO=""` |
| **Пустой вывод** | Скрипт не пишет в stdout | Перенаправить весь вывод через `exec > >(logger -t tag) 2>&1` |
| **Потеря логов** | journalctl --vacuum удалил | Настроить `Storage=persistent` и лимиты |

## Дополнительная информация

### Лучшие практики

1. **Всегда перенаправляйте stderr** — `2>&1` или `exec 2>&1`.
2. **Используйте `logger -t`** — тег позволяет фильтровать логи по скрипту.
3. **Структурированный вывод** — JSON-формат упрощает парсинг и алертинг.
4. **`Persistent=true` в timer** — garantия выполнения после простоя.
5. **Логируйте начало и конец** — для измерения длительности выполнения.
6. **Используйте systemd timer вместо cron** — лучшая интеграция с journald.
7. **Ротация файловых логов** — если пишете в файл, настройте logrotate.
8. **Не логируйте секреты** — пароли, токены, ключи не должны попадать в логи.
9. **Мониторьте выполнение** — алерты на отсутствие ожидаемых логов.
10. **Документируйте cron-расписание** — `crontab -l` + описание в README.

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [systemd-journald](./journald.md)
- [logrotate](./logrotate.md)
