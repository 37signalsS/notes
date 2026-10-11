**Актуально для:** MariaDB 10.6 / 10.11 / 11.2 / 11.4 / 12.3

# Бинарное логирование

## Определения

**Бинарный лог (binary log / binlog)** — файл журнала событий (WAL — Write-Ahead Log), в котором MariaDB фиксирует все изменения данных (DML) и определения структур (DDL) после их выполнения. Бинарный лог лежит в основе репликации, Point-in-Time Recovery (PITR) и forensic-анализа.

**Формат бинарного лога (`binlog_format`)** — способ представления событий в binlog. Поддерживаются `STATEMENT` (текст запроса), `ROW` (изменения строк) и `MIXED` (автовыбор, значение по умолчанию в MariaDB).

**GTID (Global Transaction Identifier)** — уникальный идентификатор транзакции, записанной в binlog. В MariaDB состоит из трёх компонент: `domain_id` (источник), `server_id` (сервер), `seq_no` (последовательный номер). Используется для idempotent-восстановления и смены мастера.

**mariadb-binlog** — утилита для чтения и применения бинарных логов. В MariaDB это нативная утилита (не `mysqlbinlog` из MySQL), поддерживающая расшифровку зашифрованных логов через соединение с сервером.

**encrypt_binlog** — системная переменная, управляющая шифрованием бинарных логов на диске. Для работы требует загруженного плагина управления ключами (`file_key_management`, `aws_key_management`, HashiCorp Vault).

**binlog_expire_logs_seconds** — системная переменная (введена в MariaDB 10.6.1), определяющая срок хранения binlog в секундах. С 10.6.1 является предпочтительным аналогом `expire_logs_days`; обе переменные являются алиасами.

**binlog_storage_engine** — системная переменная (MariaDB 12.3+), позволяющая хранить события бинарного лога внутри табличного пространства InnoDB вместо отдельных файлов. Увеличивает надёжность за счёт встроенного восстановления InnoDB.

## Основные концепции

### Архитектура бинарного логирования

Бинарный лог MariaDB состоит из:
- **Индексного файла** (по умолчанию `<log_bin>.index`) — текстовый файл со списком путей к сегментам binlog.
- **Сегментов binlog** (по умолчанию `<log_bin>.<NNNNNNN>`) — бинарные файлы фиксированного размера (по умолчанию 1 ГБ, управляется `max_binlog_size`), содержащие события.
- **Событий** — Atomic-записи о транзакциях, изменениях данных и DDL.

Поток событий:
1. Транзакция фиксируется в InnoDB buffer pool.
2. События записываются в binlog cache (per-thread).
3. При фиксации транзакции (`COMMIT`) содержимое cache сбрасывается в binlog-сегмент.
4. Ротация сегмента происходит при достижении `max_binlog_size`, выполнении `FLUSH BINARY LOGS` или `PURGE BINARY LOGS`.

### Форматы binlog: сравнение с точки зрения безопасности

| Формат | Безопасность | Объём | Рекомендация |
| :--- | :--- | :--- | :--- |
| `STATEMENT` | Низкая. Логирует SQL-текст; опасен для недетерминированных функций, триггеров, временных таблиц | Минимальный | Только для legacy-сред с идентичными инстансами; требует тщательного аудита |
| `MIXED` | Средняя. Автовыбор между STATEMENT и ROW; небезопасные STATEMENT автоматически переводятся в ROW | Средний | Значение по умолчанию MariaDB; приемлемо для большинства сред |
| `ROW` | Высшая. Логирует изменения на уровне строк; все значения полей, включая `BLOB`/`TEXT` (регулируется `binlog_row_image`) | Максимальный | Рекомендован для security-first сред, фильтрации репликации и compliance |

**Важно:** `binlog_format` динамически изменяемый, но его смена на работающем репликационном топологии может привести к несовместимости. Настройте параметр в `my.cnf` до запуска репликации.

### Взаимодействие с TDE и шифрованием

Шифрование бинарных логов (`encrypt_binlog = ON`) защищает данные на диске, но требует:
- Загруженного плагина управления ключами (`file_key_management`, `aws_key_management` или HashiCorp Vault).
- Ключа с ID `1` (системный ключ для бинарных логов и redo-логов InnoDB).

При включенном `encrypt_binlog` утилита `mariadb-binlog` не может расшифровывать логи локально (MDEV-8813). Для forensic используйте `--read-from-remote-server`, чтобы сервер расшифровал логи.

### Взаимодействие с репликацией и GTID

GTID-транзакции в binlog позволяют:
- Отслеживать репликацию: сравнение `@@gtid_binlog_pos` (источник) и `@@gtid_slave_pos` (реплика).
- Выполнять PITR с точностью до транзакции, а не только по временным меткам.
- Автоматически восстанавливать репликацию после сбоя (`gtid_strict_mode = ON`).

### Взаимодействие с аудитом

Бинарные логи и `server_audit` дополняют друг друга:
- **Аудит (`server_audit`)** фиксирует `кто` и `что` сделал на уровне SQL-команд.
- **Бинарные логи** фиксируют `какие данные` были изменены. Позволяют восстановить состояние данных до/после инцидента.

Для полной картины инцидента используйте оба механизма. Подробнее: **[Аудит](audit.md)**.

## Предварительные требования

- MariaDB 10.6 / 10.11 / 11.2 / 11.4 / 12.3 запущена и доступна через `sudo mariadb`
- Права `sudo` для редактирования `my.cnf` и перезапуска сервиса
- Достаточное дисковое пространство: выделите отдельный раздел/точку монтирования для binlog. Рекомендуемый объём — не менее 20% от размера `datadir` в высоконагруженных системах.
- Для шифрования binlog: настроенный плагин управления ключами (`file_key_management` или HashiCorp Vault). Подробнее: **[Шифрование данных (TDE)](tde.md)**.
- Для forensic-анализа: утилита `mariadb-binlog` (входит в пакет `MariaDB-server` или `mariadb-client`).

## Практические сценарии

### Сценарий 1: Базовая конфигурация binlog для forensic и репликации

```ini
[mariadb]
# Включение бинарного логирования
log_bin = /var/log/mysql/mariadb-bin

# Формат: ROW обеспечивает максимальную безопасность и восстанавливаемость
binlog_format = ROW

# Срок хранения: 30 дней (2592000 секунд)
# Используйте binlog_expire_logs_seconds (предпочтительно, с 10.6.1) или expire_logs_days (алиас)
binlog_expire_logs_seconds = 2592000

# Максимальный размер сегмента binlog (1 ГБ по умолчанию)
max_binlog_size = 1G

# Идентификатор сервера (обязателен для репликации и GTID)
server-id = 1

# GTID: домен и строгий режим (защита от дублирования транзакций)
gtid_domain_id = 1
gtid_strict_mode = ON

# Физическая гарантия записи: 1 = сброс на диск после каждой транзакции
sync_binlog = 1

# Проверка целостности событий при репликации
binlog_checksum = CRC32

# Разрешить вызов хранимых процедур с недетерминированными функциями из binlog
log_bin_trust_function_creators = OFF
```

**Примечание:** `binlog_expire_logs_seconds` и `expire_logs_days` являются алиасами (с MariaDB 10.6.1). Изменение одной переменной автоматически отражается в другой. Используйте `binlog_expire_logs_seconds` для точности в high-volume средах.

**Проверка:**
```sql
SHOW VARIABLES LIKE 'log_bin';
-- → log_bin = /var/log/mysql/mariadb-bin

SHOW VARIABLES LIKE 'binlog_format';
-- → binlog_format = ROW

SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';
-- → binlog_expire_logs_seconds = 2592000

SHOW VARIABLES LIKE 'expire_logs_days';
-- → expire_logs_days = 30.000000 (алиас)

SHOW VARIABLES LIKE 'sync_binlog';
-- → sync_binlog = 1

SHOW VARIABLES LIKE 'gtid_domain_id';
-- → gtid_domain_id = 1
```

### Сценарий 2: Шифрование бинарных логов

#### Вариант А: File Key Management (простой, для single-server)

```ini
[mariadb]
# Плагин управления ключами (распространяется с MariaDB, не установлен по умолчанию)
plugin_load_add = file_key_management
file_key_management_filename = /etc/mysql/encryption/keyfile.enc
file_key_management_filekey = FILE:/etc/mysql/encryption/keyfile.key
file_key_management_encryption_algorithm = AES_CTR

# Шифрование бинарных логов
encrypt_binlog = ON

# Шифрование временных таблиц на диске (рекомендуется при включении encrypt_binlog)
encrypt_tmp_disk_tables = ON
```

**Создание ключевого файла:**
```bash
# Создание директории с правами 750
sudo mkdir -p /etc/mysql/encryption
sudo chown -R mysql:mysql /etc/mysql/encryption
sudo chmod 750 /etc/mysql/encryption

# Генерация ключевого файла (32 байта для AES-256)
sudo openssl rand -hex 32 > /etc/mysql/encryption/keyfile.key
sudo chown mysql:mysql /etc/mysql/encryption/keyfile.key
sudo chmod 600 /etc/mysql/encryption/keyfile.key
```

**Проверка:**
```sql
SHOW VARIABLES LIKE 'encrypt_binlog';
-- → encrypt_binlog = ON

SHOW PLUGINS LIKE 'file_key_management';
-- → file_key_management | ACTIVE | ENCRYPTION | ...

-- Проверка, что бинарные логи зашифрованы
SHOW GLOBAL VARIABLES LIKE 'encrypt_binlog';
-- → encrypt_binlog = ON
```

#### Вариант Б: Интеграция с HashiCorp Vault (production, multi-server)

```ini
[mariadb]
plugin_load_add = hashicorp_key_management
hashicorp_key_management_url = https://vault.example.com:8200
hashicorp_key_management_auth_path = auth/kubernetes/login
hashicorp_key_management_secret_path = transit/keys/mariadb-binlog
hashicorp_key_management_encryption_algorithm = AES_CTR

encrypt_binlog = ON
```

Подробнее о Vault-интеграции: **[Шифрование данных (TDE)](tde.md)**.

### Сценарий 3: Forensic-анализ через mariadb-binlog

#### Поиск DDL-операций за период

```bash
# Поиск всех DDL-операций за последний час
mariadb-binlog --read-from-remote-server \
  --start-datetime="$(date -u -d '1 hour ago' '+%Y-%m-%d %H:%M:%S')" \
  --stop-datetime="$(date -u '+%Y-%m-%d %H:%M:%S')" \
  --base64-output=DECODE-ROWS -v \
  /var/log/mysql/mariadb-bin.000001 | grep -E "DROP|DELETE|GRANT|CREATE USER|ALTER USER"
```

**Примечание:** При включенном `encrypt_binlog` добавьте `--read-from-remote-server`, чтобы сервер расшифровал логи (MDEV-8813). Укажите параметры подключения: `--host`, `--user`, `--password`.

#### Поиск действий конкретного пользователя

```bash
mariadb-binlog --start-datetime="2026-08-20 00:00:00" \
  --stop-datetime="2026-08-20 23:59:59" \
  --base64-output=DECODE-ROWS -v \
  /var/log/mysql/mariadb-bin.000003 | grep -B 2 -A 5 "app_user"
```

#### Восстановление данных через PITR

Сценарий: случайное удаление таблицы в 14:30. Бэкап был сделан в 00:00.

```bash
# 1. Восстанавливаем полный бэкап
mariadb -u root < backup_00_00.sql

# 2. Извлекаем данные из бинарных логов с момента бэкапа до ошибки
# Используем GTID для точности (MariaDB 10.6+)
mariadb-binlog --start-datetime="2026-08-17 00:00:00" \
               --stop-datetime="2026-08-17 14:30:00" \
               --base64-output=DECODE-ROWS -v \
               /var/lib/mysql/binlog.000010 > recovery_pitr.sql

# 3. Накатываем логи на восстановленную базу
mariadb -u root < recovery_pitr.sql
```

Подробнее о PITR и бэкапах: **[Резервное копирование и восстановление](../backup_and_recovery.md)**.

### Сценарий 4: Управление ротацией и хранением

#### Ручная ротация

```sql
-- Принудительная ротация (создание нового binlog-сегмента)
FLUSH BINARY LOGS;

-- Удаление старых логов вручную
PURGE BINARY LOGS BEFORE NOW() - INTERVAL 30 DAY;

-- Удаление логов до определённого GTID
PURGE BINARY LOGS TO 'mariadb-bin.000123';
```

#### Автоматическая ротация

Настройте `binlog_expire_logs_seconds` (предпочтительно) или `expire_logs_days`:

```ini
[mariadb]
# 30 дней в секундах
binlog_expire_logs_seconds = 2592000
```

**Важно:** Установите срок хранения больше, чем максимальный лаг любой реплики. Иначе мастер может удалить логи, необходимые реплике для синхронизации, что приведёт к ошибке `Error 1236: ... master has purged binary logs`.

#### Мониторинг использования диска

```bash
# Размер каталога с binlog
du -sh /var/log/mysql/

# Количество и размер сегментов
ls -lh /var/log/mysql/mariadb-bin.*

# Проверка индекса binlog на несуществующие файлы
cat /var/log/mysql/mariadb-bin.index | while read f; do [ -f "$f" ] || echo "MISSING: $f"; done
```

### Сценарий 5: binlog_storage_engine = innodb (MariaDB 12.3+)

Хранение binlog внутри InnoDB вместо файловой системы:

```ini
[mariadb]
# Хранить binlog в InnoDB (атомарные логи, MariaDB 12.3+)
binlog_storage_engine = innodb

# При использовании binlog_storage_engine=innodb max_binlog_size управляется InnoDB
# Отдельный путь к файлам не требуется
```

**Преимущества:**
- Встроенное восстановление InnoDB при сбоях.
- Атомарность записи событий.
- Отсутствие риска повреждения файловой системы.

**Ограничения:**
- Доступно только в MariaDB 12.3+.
- Изменение параметра требует полного дампа и пересоздания репликации.
- Занимает место в табличном пространстве InnoDB.

### Сценарий 6: Запрет опасных фильтров binlog

**Важно:** Параметры `binlog-do-db` и `binlog-ignore-db` небезопасны и не рекомендуются. Они фильтруют события на основе текущей базы (`USE`), а не реально изменяемых таблиц. Это создаёт риски при кросс-базовых запросах и делает невозможным полное PITR.

**Используйте вместо них репликационные фильтры на стороне реплики** (`replicate-wild-do-table`, `replicate-ignore-table`). Подробнее: **[Фильтрация репликации](../replication/filtering.md)**.

### Сценарий 7: Проверка статуса binlog

```sql
-- Текущая позиция в binlog
SHOW MASTER STATUS;
-- → File: mariadb-bin.000003, Position: 12345, Binlog_Do_DB: , Binlog_Ignore_DB:

-- GTID-позиция
SELECT @@gtid_binlog_pos;
-- → 1-1-12345

-- Список всех binlog-файлов
SHOW BINARY LOGS;
-- → Log_name: mariadb-bin.000003, File_size: 123456789, Encrypted: Yes

-- Проверка формата
SHOW VARIABLES LIKE 'binlog_format';
-- → binlog_format = ROW

-- Проверка статуса шифрования
SHOW GLOBAL VARIABLES LIKE 'encrypt_binlog';
-- → encrypt_binlog = ON

-- Проверка параметров ротации
SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';
SHOW VARIABLES LIKE 'expire_logs_days';
SHOW VARIABLES LIKE 'max_binlog_size';
```

## Проверка целостности и аудит binlog

```sql
-- Список всех binlog-файлов с размером и статусом шифрования
SHOW BINARY LOGS;

-- Проверка binlog-индекса на несуществующие файлы (через ОС)
-- $ cat /var/log/mysql/mariadb-bin.index | while read f; do [ -f "$f" ] || echo "MISSING: $f"; done

-- Проверка, что binlog не содержит событий из legacy-форматов
mariadb-binlog --base64-output=DECODE-ROWS -v /var/log/mysql/mariadb-bin.000001 | head -20
```

## Типичные ошибки и устранение неполадок

### Ошибка: `Could not find target log file` при использовании `mariadb-binlog`

**Симптом:** `ERROR: Could not find target log file`.

**Причина:** Файл binlog удалён политикой ротации или путь в индексе неверен.

**Решение:**
```bash
# Проверка индекса
cat /var/log/mysql/mariadb-bin.index

# Проверка, существуют ли файлы
ls -la /var/log/mysql/mariadb-bin.*

# Если индекс содержит несуществующие файлы — очистите его или пересоздайте
```

### Ошибка: `mariadb-binlog` не может прочитать зашифрованный binlog локально

**Симптом:** `ERROR 1969: Failed to decrypt binary log`.

**Причина:** `encrypt_binlog = ON`, а `mariadb-binlog` запущен без доступа к плагину управления ключами или без `--read-from-remote-server` (MDEV-8813).

**Решение:**
```bash
# Используйте --read-from-remote-server для расшифровки на стороне сервера
mariadb-binlog --read-from-remote-server --host=localhost --user=root --password \
  --start-datetime="2026-08-20 00:00:00" \
  /var/log/mysql/mariadb-bin.000003 > decrypted.sql
```

### Ошибка: `binlog файлы занимают всё место на диске`

**Симптом:** Диск `/var/log` заполнен, сервер зависает.

**Причина:** `binlog_expire_logs_seconds = 0` (отключена автоматическая ротация) или `expire_logs_days = 0`.

**Решение:**
```sql
-- Включение ротации (30 дней)
SET GLOBAL binlog_expire_logs_seconds = 2592000;

-- Принудительное удаление старых логов
PURGE BINARY LOGS BEFORE NOW() - INTERVAL 30 DAY;

-- Проверка размера
SHOW BINARY LOGS;
```

Для персистентности добавьте в `my.cnf`:
```ini
[mariadb]
binlog_expire_logs_seconds = 2592000
```

### Ошибка: `Error 1236: Slave I/O: ... master has purged binary logs`

**Симптом:** Реплика разрывается с ошибкой `master has purged binary logs`.

**Причина:** Мастер удалил binlog-файлы, которые ещё необходимы реплике.

**Решение:**
1. Увеличьте `binlog_expire_logs_seconds` на мастере (больше максимального лага реплики).
2. Пересоздайте реплику с текущим дампом (`re-seeding`).

### Ошибка: Изменение `binlog_format` ломает репликацию

**Симптом:** Реплика останавливается после смены `binlog_format`.

**Причина:** `binlog_format` не реплицируется автоматически. Смена формата на мастере не затрагивает реплику.

**Решение:**
1. Смените `binlog_format` на мастере и на всех репликах одновременно.
2. Перезапустите репликацию.
3. Используйте `ROW` для новых топологий — это самый безопасный формат.

### Ошибка: `binlog_checksum` mismatch при репликации

**Симптом:** Реплика останавливается с ошибкой checksum mismatch.

**Причина:** Разные значения `binlog_checksum` на мастере и реплике.

**Решение:**
```sql
-- Проверка значения на мастере
SHOW VARIABLES LIKE 'binlog_checksum';
-- → binlog_checksum = CRC32

-- Установите то же значение на реплике
STOP SLAVE;
SET GLOBAL binlog_checksum = CRC32;
START SLAVE;
```

## Лучшие практики

1. **binlog_format = ROW для security-first сред.** Логирует изменения данных, а не SQL-текст. Защищает от недетерминированных функций и позволяет точно восстановить данные.
2. **binlog_expire_logs_seconds вместо expire_logs_days.** Точный контроль в секундах (с MariaDB 10.6.1). Установите срок больше максимального лага реплики.
3. **encrypt_binlog = ON.** Шифрует binlog на диске. Требует плагин управления ключами. Подробнее: **[Шифрование данных (TDE)](tde.md)**.
4. **sync_binlog = 1.** Физическая гарантия записи каждой транзакции на диск. Критично для durability.
5. **GTID включён.** `gtid_domain_id` + `gtid_strict_mode = ON` упрощают forensic и восстановление репликации.
6. **Отдельный раздел для binlog.** Выделите отдельный раздел/точку монтирования. Это упрощает мониторинг и предотвращает заполнение корневого раздела.
7. **Права на файлы.** Каталог binlog: `chmod 750`, владелец `mysql:mysql`. Файлы: `chmod 660`.
8. **Не используйте binlog-do-db / binlog-ignore-db.** Небезопасны для кросс-базовых запросов. Используйте `replicate-wild-do-table` на реплике.
9. **mariadb-binlog вместо mysqlbinlog.** В MariaDB используйте нативную утилиту `mariadb-binlog`. Она поддерживает расшифровку через сервер и GTID.
10. **binlog_checksum = CRC32.** Обнаруживает повреждение или подмену событий при репликации.
11. **Мониторинг размера.** Добавьте алерт на utilisation binlog-раздела > 80%.
12. **Тестируйте PITR на staging.** Регулярно проверяйте, что вы можете восстановить данные из последнего бэкапа + binlog.

## Дополнительная информация

### Ссылки на подразделы

- **[Обзор безопасности](../security/index.md)** — общая модель безопасности MariaDB.
- **[Шифрование данных (TDE)](../security/tde.md)** — `file_key_management`, HashiCorp Vault, `encrypt_binlog`.
- **[Аудит](../security/audit.md)** — `server_audit` плагин, взаимосвязь с бинарными логами.
- **[Ролевая модель (RBAC)](../security/rbac.md)** — разграничение привилегий, `PROXY`-пользователи.
- **[SSL/TLS](../security/ssl-tls.md)** — `require_secure_transport`, шифрование репликации.
- **[Конфигурация MariaDB](../configuration.md)** — `binlog_storage_engine`, `binlog_format`.
- **[Резервное копирование и восстановление](../backup_and_recovery.md)** — PITR через `mariadb-binlog`, физические бэкапы.
- **[Стандартная репликация](../replication/overview.md)** — GTID, `sync_binlog`, `gtid_strict_mode`.
- **[Фильтрация репликации](../replication/filtering.md)** — `replicate-wild-do-table`, предупреждения о `binlog-do-db`.
- **[Клиентские утилиты](../client_utilities.md)** — `mariadb-binlog`, `mariadb-dump`.

### Смежные темы

- **[Начальная закалка](../security/hardening.md)** — `mariadb-secure-installation`, включение binlog.
- **[Миграция с MySQL](../Operations/migration_mysql_to_mariadb.md)** — особенности миграции binlog и GTID.
- **[Устранение неполадок репликации](../replication/troubleshooting.md)** — ошибки `Error 1236`, GTID, `mariadb-binlog`.

### Внешние ресурсы

- [Managing Binary Log Encryption](https://mariadb.com/docs/server/security/encryption/data-at-rest-encryption/managing-binary-log-encryption)
- [Replication and Binary Log System Variables](https://mariadb.com/docs/server/ha-and-performance/standard-replication/replication-and-binary-log-system-variables)
- [Binary Log Formats](https://mariadb.com/docs/server/server-management/server-monitoring-logs/binary-log/binary-log-formats)
- [Securing MariaDB Logs](https://github.com/mariadb-corporation/mariadb-docs/blob/main/server/security/securing-mariadb/securing-mariadb-logs.md)
- [MDEV-8813: mariadb-binlog cannot decrypt encrypted binary logs](https://jira.mariadb.org/browse/MDEV-8813)
