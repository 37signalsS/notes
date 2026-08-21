# Автоматизация и верификация резервных копий MySQL

Скрипты автоматизации, настройка cron, ротация и smoke-тестирование бэкапов.

> **Принцип:** Бэкап не считается существующим, пока его восстановление не протестировано. Подробнее — в **[Проверке целостности бэкапов](../../Concepts/backup_validation.md)**.

## Скрипт для ежедневного физического бэкапа XtraBackup

```bash
#!/bin/bash
# /opt/scripts/mysql_backup.sh — Ежедневный бэкап XtraBackup + ротация

set -euo pipefail

BACKUP_DIR="/backups/mysql"
DATE=$(date +%F)
TIME=$(date +%H%M)
FULL_DIR="${BACKUP_DIR}/full_${DATE}_${TIME}"
LOG_FILE="/var/log/mysql_backup.log"
KEEP_DAYS=7   # Хранить бэкапы 7 дней
MYSQL_USER="backup_user"
MYSQL_PASS="StrongPassword!2024"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

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

# Проверка кода возврата
if [ $? -eq 0 ]; then
  log "Бэкап завершён успешно: ${FULL_DIR}"
else
  log "ERROR: Бэкап завершён с ошибкой"
  exit 1
fi

# Ротация: удаление бэкапов старше KEEP_DAYS дней
find "${BACKUP_DIR}" -type d -name "full_*" -mtime +${KEEP_DAYS} -exec rm -rf {} + 2>/dev/null
log "Ротация завершена: удалены бэкапы старше ${KEEP_DAYS} дней"

# Уведомление (опционально)
# curl -X POST "https://hooks.slack.com/services/xxx" -d "{\"text\": \"MySQL backup completed: ${FULL_DIR}\"}"
```

## Скрипт для ежедневного логического бэкапа MySQL Shell

```bash
#!/bin/bash
# /opt/scripts/mysql_shell_backup.sh — Ежедневный дамп MySQL Shell

set -euo pipefail

BACKUP_DIR="/backups/mysql/shell"
DATE=$(date +%F)
DUMP_DIR="${BACKUP_DIR}/dump_${DATE}"
LOG_FILE="/var/log/mysql_shell_backup.log"
KEEP_DAYS=30   # Хранить логические дампы дольше (они меньше по размеру)

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

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

# Ротация
find "${BACKUP_DIR}" -type d -name "dump_*" -mtime +${KEEP_DAYS} -exec rm -rf {} + 2>/dev/null
log "Ротация завершена"
```

## Настройка cron

```bash
# Открыть crontab
crontab -e

# Ежедневный физический бэкап в 03:00
0 3 * * * /opt/scripts/mysql_backup.sh >> /var/log/mysql_backup.log 2>&1

# Ежедневный логический дамп в 04:00 (после физического, чтобы не конфликтовать по I/O)
0 4 * * * /opt/scripts/mysql_shell_backup.sh >> /var/log/mysql_shell_backup.log 2>&1

# Еженедельная проверка целостности (восстановление в изолированную среду)
0 5 * * 0 /opt/scripts/mysql_backup_validate.sh >> /var/log/mysql_backup_validate.log 2>&1
```

> **Совет по расписанию:** Физический и логический бэкапы запускаются в разное время для минимизации конкуренции за I/O. Если сервер highly loaded, увеличьте интервал между запусками.

## Скрипт верификации бэкапа (Smoke Test)

```bash
#!/bin/bash
# /opt/scripts/mysql_backup_validate.sh — Проверка восстанавливаемости бэкапа

set -euo pipefail

LATEST_BACKUP="/backups/mysql/$(ls -t /backups/mysql | head -1)"
VALIDATE_DIR="/tmp/mysql_backup_validate_$(date +%s)"
MYSQL_PORT=3307   # Отдельный порт для тестового инстанса

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# Подготовка бэкапа
log "Подготовка бэкапа: ${LATEST_BACKUP}"
xtrabackup --prepare --target-dir="${LATEST_BACKUP}"

# Копирование в изолированный каталог
mkdir -p "${VALIDATE_DIR}/data"
xtrabackup --copy-back --target-dir="${LATEST_BACKUP}" --datadir="${VALIDATE_DIR}/data"

# Запуск временного MySQL инстанса на отдельном порту
mysqld --datadir="${VALIDATE_DIR}/data" \
  --port="${MYSQL_PORT}" \
  --socket="${VALIDATE_DIR}/mysql.sock" \
  --skip-networking=0 \
  --bind-address=127.0.0.1 \
  --daemonize --pid-file="${VALIDATE_DIR}/mysqld.pid"

# Ожидание готовности
sleep 10

# Проверка целостности (проверка всех таблиц)
mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -e "
  CHECK TABLE mysql.user, mysql.db, mysql.tables_priv;
" 2>/dev/null

# Бизнес-проверка (пример: количество пользователей)
USER_COUNT=$(mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -N -e \
  "SELECT COUNT(*) FROM mysql.user" 2>/dev/null)
if [ "${USER_COUNT}" -gt 0 ]; then
  log "VERIFICATION PASSED: ${USER_COUNT} users found"
else
  log "VERIFICATION FAILED: no users found"
fi

# Остановка и очистка
mysqladmin --socket="${VALIDATE_DIR}/mysql.sock" -u root shutdown 2>/dev/null || true
rm -rf "${VALIDATE_DIR}"
log "Валидация завершена"
```

### Расширенная верификация (MySQL Shell Smoke Test)

```bash
#!/bin/bash
# /opt/scripts/mysql_shell_validate.sh — Проверка логического дампа

set -euo pipefail

LATEST_DUMP="/backups/mysql/shell/$(ls -t /backups/mysql/shell | head -1)"
VALIDATE_DIR="/tmp/mysql_shell_validate_$(date +%s)"
MYSQL_PORT=3308

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

# Подготовка изолированной среды
mkdir -p "${VALIDATE_DIR}/data"
chown mysql:mysql "${VALIDATE_DIR}/data"

# Инициализация чистого инстанса
mysqld --initialize-insecure --datadir="${VALIDATE_DIR}/data"

# Запуск временного инстанса
mysqld --datadir="${VALIDATE_DIR}/data" \
  --port="${MYSQL_PORT}" \
  --socket="${VALIDATE_DIR}/mysql.sock" \
  --daemonize --pid-file="${VALIDATE_DIR}/mysqld.pid"

sleep 10

# Загрузка дампа
mysqlsh --uri root@localhost --port="${MYSQL_PORT}" \
  -e "util.loadDump('${LATEST_DUMP}', {
    threads: 4,
    ignoreExistingObjects: true
  })" 2>/dev/null

# Проверка: количество таблиц после загрузки
TABLE_COUNT=$(mysql --socket="${VALIDATE_DIR}/mysql.sock" -u root -N -e \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema NOT IN ('mysql','information_schema','performance_schema','sys')" 2>/dev/null)
if [ "${TABLE_COUNT}" -gt 0 ]; then
  log "VERIFICATION PASSED: ${TABLE_COUNT} application tables loaded"
else
  log "VERIFICATION FAILED: no application tables found"
fi

# Остановка и очистка
mysqladmin --socket="${VALIDATE_DIR}/mysql.sock" -u root shutdown 2>/dev/null || true
rm -rf "${VALIDATE_DIR}"
log "Валидация завершена"
```

## Скрипт архивации бинарных логов (для PITR)

```bash
#!/bin/bash
# /opt/scripts/mysql_binlog_archive.sh — Архивация бинарных логов

set -euo pipefail

BINLOG_DIR="/var/lib/mysql"
ARCHIVE_DIR="/backups/mysql/binlogs"
LOG_FILE="/var/log/mysql_binlog_archive.log"
KEEP_DAYS=30

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"; }

# Копирование текущих бинарных логов
mysqlbinlog --read-from-remote-server --host=localhost \
  --user=backup_user --password='StrongPassword!2024' \
  --raw --to-last-log \
  --result-file="${ARCHIVE_DIR}/mysql-bin." \
  mysql-bin.000001 2>> "${LOG_FILE}"

# Ротация архивов
find "${ARCHIVE_DIR}" -name "mysql-bin.*" -mtime +${KEEP_DAYS} -delete 2>/dev/null
log "Архивация бинарных логов завершена"
```

## Интеграция с мониторингом (Prometheus Pushgateway)

```bash
#!/bin/bash
# Добавить в конец скрипта бэкапа для отправки метрик

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

## Дополнительная информация

- **[Обзор инструментов бэкапа](./overview.md)** — общая стратегия, бест-практики.
- **[Percona XtraBackup](./xtrabackup.md)** — физические бэкапы.
- **[MySQL Shell Dump & Load](./mysql_shell_dump.md)** — логические дампы.
- **[Point-in-Time Recovery](./pitr.md)** — восстановление на конкретный момент.
- **[Проверка целостности бэкапов](../../Concepts/backup_validation.md)** — теория и методы валидации.
- **[Pushgateway](../../../Prometheus/pushgateway.md)** — метрики бэкапов в Prometheus.
