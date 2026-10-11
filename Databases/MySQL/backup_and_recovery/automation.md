# Автоматизация и верификация резервных копий MySQL

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS, XtraBackup 8.0.35-36, MySQL Shell 9.7.x

Скрипты автоматизации, ротация, smoke-тестирование и интеграция с локальным мониторингом.

> **Принцип:** Бэкап не считается существующим, пока его восстановление не протестировано. Подробнее — в **[Проверке целостности бэкапов](../../Concepts/backup_validation.md)**.

## Определения

**Автоматизация бэкапов** — выполнение резервного копирования по расписанию без участия оператора, с контролем результата и уведомлением.

**Smoke-тест (проверка восстанавливаемости)** — восстановление бэкапа в изолированной среде с последующей проверкой целостности данных.

**Ротация (Retention Policy)** — автоматическое удаление бэкапов старше заданного срока согласно политике хранения.

**Идемпотентность** — свойство задачи безопасно выполняться повторно без побочных эффектов. В контексте cron требует защиты от параллельных запусков.

**Flocks-блокировка** — advisory-блокировка на файловом дескрипторе, автоматически снимаемая при завершении процесса. Защищает от дублирующих запусков скриптов.

## Основные концепции

Автоматизация бэкапов — часть общей стратегии резервного копирования, описанной в **[Обзоре инструментов](./overview.md)**. Цель — минимизировать человеческий фактор и обеспечить соблюдение RPO/RTO.

### Жизненный цикл автоматизированного бэкапа

1. **Pre-flight проверки:** свободное место, доступность mysqld, валидность учетных данных.
2. **Идемпотентный запуск:** `flock` или файловый маркер предотвращают параллельное выполнение.
3. **Создание бэкапа:** физический (XtraBackup) или логический (MySQL Shell).
4. **Ротация:** удаление устаревших копий по политике.
5. **Верификация:** smoke-тест на отдельном инстансе или offline-проверка.
6. **Уведомление:** отправка статуса в мониторинг (Prometheus Pushgateway, локальный syslog).

### Идемпотентность в cron

Cron-задачи могут выполняться дважды при перезапуске демона или в кластере. Для защиты используются:

- **`flock -n`** — неблокирующая advisory-блокировка. Если файл заблокирован, скрипт завершается gracefully.
- **Файловые маркеры** — проверка наличия lock-файла с timestamp. Подробнее — в **[Идемпотентности](../../../Concepts/idempotency.md#9-%D0%B8%D0%B4%D0%B5%D0%BC%D0%BF%D0%BE%D1%82%D0%B5%D0%BD%D1%82%D0%BD%D0%BE%D1%81%D1%82%D1%8C-%D0%B2-cron-%D0%B8-scheduled-tasks)**.

### Политика хранения

| Тип бэкапа | Рекомендуемый срок | Обоснование |
| :--- | :--- | :--- |
| Физический (XtraBackup) | 7–14 дней | Большой объем; полный бэкап создаётся раз в день/неделю |
| Логический (MySQL Shell) | 14–30 дней | Меньший размер; используется для восстановления отдельных объектов |
| Бинарные логи (binlog) | 7–30 дней | Зависит от RPO; для PITR минимум 72 часа |

### Уведомления

Избегайте интеграции с внешними SaaS-сервисами для уведомлений. Используйте:
- Локальный syslog (`logger`).
- Мониторинг через Prometheus Pushgateway (self-hosted).
- Файловые маркеры статуса для внешних orcheстраторов (Nomad, systemd).

## Практические сценарии

### Сценарий 1: Ежедневный физический бэкап XtraBackup

```bash
#!/bin/bash
# /opt/scripts/mysql_backup.sh — Ежедневный бэкап XtraBackup + ротация
set -euo pipefail

BACKUP_DIR="/backups/mysql"
DATE=$(date +%F)
TIME=$(date +%H%M)
FULL_DIR="${BACKUP_DIR}/full_${DATE}_${TIME}"
LOG_FILE="/var/log/mysql_backup.log"
KEEP_DAYS=7
MYSQL_USER="backup_user"
MYSQL_PASS="StrongPassword!2024"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

# Идемпотентный запуск: защита от параллельных запусков
LOCKFILE="/var/run/mysql_backup.lock"
if ! flock -n "${LOCKFILE}" 2>/dev/null; then
  log "INFO: Бэкап уже выполняется — выход"
  exit 0
fi

# Проверка свободного места (минимум 50 ГБ)
AVAILABLE_GB=$(df -BG "${BACKUP_DIR}" | awk 'NR==2 {print $4}' | tr -d 'G')
if [ "${AVAILABLE_GB}" -lt 50 ]; then
  log "ERROR: Недостаточно места: ${AVAILABLE_GB} ГБ доступно"
  exit 1
fi

# Создание бэкапа
log "Начало бэкапа: ${FULL_DIR}"
xtrabackup --backup \
  --target-dir="${FULL_DIR}" \
  --user="${MYSQL_USER}" \
  --password="${MYSQL_PASS}" \
  --compress --compress-threads=4 \
  --compress-zstd-level=3 \
  2>> "${LOG_FILE}"

if [ $? -eq 0 ]; then
  log "Бэкап завершён успешно: ${FULL_DIR}"
else
  log "ERROR: Бэкап завершён с ошибкой"
  exit 1
fi

# Ротация: удаление бэкапов старше KEEP_DAYS дней
find "${BACKUP_DIR}" -type d -name "full_*" -mtime +${KEEP_DAYS} -exec rm -rf {} + 2>/dev/null
log "Ротация завершена: удалены бэкапы старше ${KEEP_DAYS} дней"

# Локальное уведомление (syslog)
logger -t mysql_backup "Backup completed: ${FULL_DIR}"
```

### Сценарий 2: Ежедневный логический бэкап MySQL Shell

```bash
#!/bin/bash
# /opt/scripts/mysql_shell_backup.sh — Ежедневный дамп MySQL Shell
set -euo pipefail

BACKUP_DIR="/backups/mysql/shell"
DATE=$(date +%F)
DUMP_DIR="${BACKUP_DIR}/dump_${DATE}"
LOG_FILE="/var/log/mysql_shell_backup.log"
KEEP_DAYS=30

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

LOCKFILE="/var/run/mysql_shell_backup.lock"
if ! flock -n "${LOCKFILE}" 2>/dev/null; then
  log "INFO: Дамп уже выполняется — выход"
  exit 0
fi

log "Начало дампа: ${DUMP_DIR}"
mysqlsh --uri backup_user@localhost \
  -e "util.dumpInstance('${DUMP_DIR}', {
    threads: 8,
    compression: 'zstd',
    showProgress: false
  })" 2>> "${LOG_FILE}"

if [ $? -eq 0 ]; then
  log "Дамп завершён успешно: ${DUMP_DIR}"
else
  log "ERROR: Дамп завершён с ошибкой"
  exit 1
fi

find "${BACKUP_DIR}" -type d -name "dump_*" -mtime +${KEEP_DAYS} -exec rm -rf {} + 2>/dev/null
log "Ротация завершена"
```

### Сценарий 3: Настройка планировщика

#### Вариант A: cron

```bash
# Открыть crontab
crontab -e

# Ежедневный физический бэкап в 03:00
0 3 * * * /opt/scripts/mysql_backup.sh >> /var/log/mysql_backup.log 2>&1

# Ежедневный логический дамп в 04:00
0 4 * * * /opt/scripts/mysql_shell_backup.sh >> /var/log/mysql_shell_backup.log 2>&1

# Еженедельная проверка целостности (восстановление в изолированную среду)
0 5 * * 0 /opt/scripts/mysql_backup_validate.sh >> /var/log/mysql_backup_validate.log 2>&1
```

> **Совет по расписанию:** Физический и логический бэкапы запускаются в разное время для минимизации конкуренции за I/O. Если сервер высоконагружен, увеличьте интервал между запусками.

#### Вариант B: systemd timer (альтернатива cron)

```ini
# /etc/systemd/system/mysql-backup.service
[Unit]
Description=MySQL daily backup
After=network.target mysql.service

[Service]
Type=oneshot
ExecStart=/opt/scripts/mysql_backup.sh
StandardOutput=journal
StandardError=journal

# /etc/systemd/system/mysql-backup.timer
[Unit]
Description=Daily MySQL backup at 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now mysql-backup.timer
# → Проверка: systemctl list-timers | grep mysql-backup
```

systemd timer обеспечивает:
- **Persistent=true** — запуск пропущенной задачи после восстановления питания.
- **Журналирование** — выход в `journalctl -u mysql-backup`.
- **Зависимости** — `After=mysql.service` гарантирует готовность СУБД.

### Сценарий 4: Smoke-тестирование бэкапов

#### Верификация физического бэкапа (XtraBackup)

```bash
#!/bin/bash
# /opt/scripts/mysql_backup_validate.sh — Проверка восстанавливаемости бэкапа
set -euo pipefail

LATEST_BACKUP="/backups/mysql/$(ls -t /backups/mysql | head -1)"
VALIDATE_DIR="/tmp/mysql_backup_validate_$(date +%s)"
MYSQL_PORT=3307

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

log "Подготовка бэкапа: ${LATEST_BACKUP}"
xtrabackup --prepare --target-dir="${LATEST_BACKUP}"

mkdir -p "${VALIDATE_DIR}/data"
xtrabackup --copy-back --target-dir="${LATEST_BACKUP}" --datadir="${VALIDATE_DIR}/data"

mysqld --datadir="${VALIDATE_DIR}/data" \
  --port="${MYSQL_PORT}" \
  --socket="${VALIDATE_DIR}/mysql.sock" \
  --skip-networking=0 \
  --bind-address=127.0.0.1 \
  --daemonize --pid-file="${VALIDATE_DIR}/mysqld.pid"

sleep 10

mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -e "
  CHECK TABLE mysql.user, mysql.db, mysql.tables_priv;
" 2>/dev/null

USER_COUNT=$(mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -N -e \
  "SELECT COUNT(*) FROM mysql.user" 2>/dev/null)
if [ "${USER_COUNT}" -gt 0 ]; then
  log "VERIFICATION PASSED: ${USER_COUNT} users found"
else
  log "VERIFICATION FAILED: no users found"
fi

mysqladmin --socket="${VALIDATE_DIR}/mysql.sock" -u root shutdown 2>/dev/null || true
rm -rf "${VALIDATE_DIR}"
log "Валидация завершена"
```

#### Расширенная верификация логического дампа (MySQL Shell)

```bash
#!/bin/bash
# /opt/scripts/mysql_shell_validate.sh — Проверка логического дампа
set -euo pipefail

LATEST_DUMP="/backups/mysql/shell/$(ls -t /backups/mysql/shell | head -1)"
VALIDATE_DIR="/tmp/mysql_shell_validate_$(date +%s)"
MYSQL_PORT=3308

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

mkdir -p "${VALIDATE_DIR}/data"
chown mysql:mysql "${VALIDATE_DIR}/data"

mysqld --initialize-insecure --datadir="${VALIDATE_DIR}/data"

mysqld --datadir="${VALIDATE_DIR}/data" \
  --port="${MYSQL_PORT}" \
  --socket="${VALIDATE_DIR}/mysql.sock" \
  --daemonize --pid-file="${VALIDATE_DIR}/mysqld.pid"

sleep 10

mysqlsh --uri root@localhost --port="${MYSQL_PORT}" \
  -e "util.loadDump('${LATEST_DUMP}', {
    threads: 4,
    ignoreExistingObjects: true
  })" 2>/dev/null

TABLE_COUNT=$(mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys')" 2>/dev/null)
if [ "${TABLE_COUNT}" -gt 0 ]; then
  log "VERIFICATION PASSED: ${TABLE_COUNT} application tables loaded"
else
  log "VERIFICATION FAILED: no application tables found"
fi

mysqladmin --socket="${VALIDATE_DIR}/mysql.sock" -u root shutdown 2>/dev/null || true
rm -rf "${VALIDATE_DIR}"
log "Валидация завершена"
```

### Сценарий 5: Архивация бинарных логов (для PITR)

```bash
#!/bin/bash
# /opt/scripts/mysql_binlog_archive.sh — Архивация бинарных логов
set -euo pipefail

BINLOG_DIR="/var/lib/mysql"
ARCHIVE_DIR="/backups/mysql/binlogs"
LOG_FILE="/var/log/mysql_binlog_archive.log"
KEEP_DAYS=30

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"; }

LOCKFILE="/var/run/mysql_binlog_archive.lock"
if ! flock -n "${LOCKFILE}" 2>/dev/null; then
  log "INFO: Архивация уже выполняется — выход"
  exit 0
fi

mysqlbinlog --read-from-remote-server --host=localhost \
  --user=backup_user --password='StrongPassword!2024' \
  --raw --to-last-log \
  --result-file="${ARCHIVE_DIR}/mysql-bin." \
  mysql-bin.000001 2>> "${LOG_FILE}"

find "${ARCHIVE_DIR}" -name "mysql-bin.*" -mtime +${KEEP_DAYS} -delete 2>/dev/null
log "Архивация бинарных логов завершена"
```

### Сценарий 6: Интеграция с локальным мониторингом

Добавьте в конец скрипта бэкапа для отправки метрик в self-hosted Prometheus Pushgateway:

```bash
#!/bin/bash
PUSHGATEWAY_URL="http://pushgateway:9091"

# Метрика: время последнего успешного бэкапа
echo "backup_last_success_timestamp $(date +%s)" | \
  curl --data-binary @- ${PUSHGATEWAY_URL}/metrics/job/mysql_backup/instance/$(hostname)

# Метрика: размер бэкапа в байтах
BACKUP_SIZE=$(du -sb "${FULL_DIR}" | awk '{print $1}')
echo "backup_size_bytes ${BACKUP_SIZE}" | \
  curl --data-binary @- ${PUSHGATEWAY_URL}/metrics/job/mysql_backup/instance/$(hostname)
```

**Алерт в Alertmanager:**

```yaml
- alert: MySQLBackupMissing
  expr: time() - backup_last_success_timestamp > 86400 * 2
  labels:
    severity: critical
  annotations:
    summary: "MySQL бэкап не выполнялся более 2 дней"
    description: "Последний успешный бэкап был {{ $value | humanizeDuration }} назад"
```

## Диагностика и устранение неисправностей

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `xtrabackup: [ERROR] unknown variable` | Отсутствие `--no-defaults` | Добавьте флаг к команде `mysqlbinlog` |
| `ERROR 1236` (Missing GTIDs) | Binlog удален на источнике | Восстановите из полного бэкапа + binlog до точки сбоя |
| Ошибка прав доступа | `backup_user` lacks `REPLICATION SLAVE` | Выдайте грант: `GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'backup_user'@'%'` |
| `flock: Permission denied` | Нет прав на создание lock-файла | Создайте lock-файл в `/var/run/` или измените путь на `/tmp/` |
| Скрипт не запускается по cron | Отсутствует права на выполнение | `chmod +x /opt/scripts/mysql_backup.sh`; проверьте `crontab -l` |
| Smoke-test падает с `InnoDB: Unable to lock` | Порт 3307 занят или данные не скопированы | Проверьте `lsof -i :3307`; убедитесь, что `--copy-back` завершился успешно |
| `util.loadDump()` зависает | Недостаточно потоков или память | Уменьшите `threads`; проверьте `ulimit -n` |

## Бест-практисы

1. **Идемпотентность:** Все скрипты должны безопасно выполняться повторно. Используйте `flock` или файловые маркеры.
2. **Минимальные права:** Создайте отдельного пользователя `backup_user` с минимально необходимыми привилегиями. Не используйте `root`.
3. **Изоляция smoke-test:** Запускайте верификацию на отдельном порту (`3307`, `3308`) в изолированном каталоге `/tmp/`.
4. **Логирование:** Все скрипты пишут в `/var/log/`. Используйте `logger` для отправки в syslog.
5. **Ротация логов:** Настройте `logrotate` для `/var/log/mysql_*.log` (еженедельно, 4 ротации).
6. **Мониторинг:** Отправляйте метрики в локальный Pushgateway. Настройте алерты в Alertmanager.
7. **Тестируйте регулярно:** Проводите drills восстановления на изолированном инстансе не реже раза в квартал. Документируйте RTO и RPO.
8. **Храните метаданные:** Файл `xtrabackup_binlog_info`, метаданные дампа MySQL Shell и скрипты восстановления должны храниться вместе с бэкапом.
9. **Отдельный раздел для binlog:** Используйте отдельный раздел или том для `/var/lib/mysql-binlog/` для упрощения мониторинга и ротации.
10. **Шифрование:** Шифруйте бэкапы на лету (`xtrabackup --encrypt=AES256`) и в покое. Ключи храните в отдельном контуре (Vault, sealed-secrets).

## Дополнительная информация

- **[Обзор инструментов бэкапа](./overview.md)** — общая стратегия, бест-практисы.
- **[Percona XtraBackup](./xtrabackup.md)** — физические бэкапы, инкрементальные бэкапы, восстановление таблиц.
- **[MySQL Shell Dump & Load](./mysql_shell_dump.md)** — логические дампы, загрузка.
- **[Point-in-Time Recovery](./pitr.md)** — восстановление на конкретный момент.
- **[Проверка целостности бэкапов](../../Concepts/backup_validation.md)** — теория и методы валидации.
- **[Безопасность бэкапов](../../Concepts/backup_security.md)** — шифрование, контроль доступа, хранение ключей.
- **[Идемпотентность](../../../Concepts/idempotency.md)** — защита от дублирующих запусков, паттерны `flock`.
- **[Pushgateway](../../../Prometheus/pushgateway.md)** — метрики бэкапов в Prometheus.
