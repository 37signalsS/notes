# Бинарное логирование для безопасности в MariaDB

Бинарные логи (binary log) — критический инструмент для расследования инцидентов и восстановления данных. Они фиксируют все изменения данных и могут использоваться как "чёрный ящик" при атаках.

## Настройка бинарного логирования

```ini
[mariadb]
# Включение бинарного логирования
log_bin = /var/log/mysql/mariadb-bin.log

# Формат: ROW safest (видны все изменения), STATEMENT компактнее
binlog_format = ROW

# Хранение логов 30 дней (для расследований)
expire_logs_days = 30

# Идентификатор сервера (обязателен для репликации)
server-id = 1
```

## Использование для расследования инцидентов

```bash
# Поиск всех DDL-операций за последний час
mysqlbinlog --start-datetime="$(date -d '1 hour ago' '+%Y-%m-%d %H:%M:%S')" \
  --stop-datetime="$(date '+%Y-%m-%d %H:%M:%S')" \
  --base64-output=DECODE-ROWS -v \
  /var/log/mysql/mariadb-bin.log | grep -A 5 "DROP\|DELETE\|GRANT\|CREATE USER"

# Поиск действий конкретного пользователя
mysqlbinlog --start-datetime="2026-08-20 00:00:00" \
  /var/log/mysql/mariadb-bin.log | grep -B 2 -A 5 "app_user"
```

## Шифрование бинарных логов

Дополнительная защита: шифрование самих логов, чтобы при краже файлов логов злоумышленник не мог прочитать изменения данных.

```ini
[mariadb]
# Требует file_key_management или hashicorp_key_management (см. TDE)
binlog_encryption = ON
```

```sql
-- Проверка, что бинарные логи зашифрованы
SHOW VARIABLES LIKE 'binlog_encryption';
-- → binlog_encryption = ON
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Шифрование данных (TDE)](tde.md)** — настройка key management для `binlog_encryption`.
- **[Аудит](audit.md)** — плагин `server_audit` как дополнительный уровень логирования.
- **[Конфигурация MariaDB](../configuration.md)** — параметры `binlog_format`, `expire_logs_days`.
