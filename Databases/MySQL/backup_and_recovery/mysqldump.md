# mysqldump — логический дамп MySQL

**Актуально для:** MySQL 5.7 (EOL 2023-10) / 8.0 (EOL 2026-04) / 8.4 LTS

> **Статус:** `mysqldump` не deprecated и остаётся штатным инструментом, однако для MySQL 8.0.21+ и 8.4+ предпочтителен многопоточный **[MySQL Shell Dump & Load](./mysql_shell_dump.md)**. `mysqldump` остаётся обязательным инструментом там, где MySQL Shell недоступен, на унаследованных хостах 5.7, для частичного дампа и для переноса схемы.

## Определения

**`mysqldump`** — клиентская утилита MySQL, выполняющая логический дамп: обход таблиц и выгрузка их в виде последовательности SQL-инструкций (`CREATE TABLE`, `INSERT`). Работает через обычный SQL-протокол, поэтому не зависит от внутреннего формата файлов данных и может использоваться для переноса между серверами, версиями и архитектурами.

**`--single-transaction`** — флаг, который открывает одну транзакцию (`START TRANSACTION WITH CONSISTENT SNAPSHOT`) и удерживает её на всё время дампа. InnoDB в силу MVCC продолжает обслуживать чтение и запись, а клиент видит согласованный снимок на момент старта. Единственный способ снять логический дамп InnoDB без блокировки записи.

**Global read lock (GRL)** — `FLUSH TABLES WITH READ LOCK`. Блокирует **все** операции записи во всём инстансе, включая `INSERT`, `UPDATE`, `DELETE` и DDL. `--source-data`/`--dump-replica` включают `--lock-all-tables`, если не указан `--single-transaction`; с `--single-transaction` GRL берётся лишь на мгновение в начале дампа — в момент фиксации позиции binlog.

**Backup lock (instance backup lock)** — `LOCK INSTANCE FOR BACKUP` (MySQL 8.0+, привилегия `BACKUP_ADMIN`). Блокирует DDL, `TRUNCATE`, `OPTIMIZE`, `REPAIR`, операции с файлами, не отражаемыми в redo log, и управление учётными записями, но **не** блокирует DML. Подробное сравнение с GRL — в **[Механизмы блокировки при бэкапе](./overview.md#механизмы-блокировки-при-бэкапе)**.

**Позиция бинарного лога в дампе** — строка `CHANGE REPLICATION SOURCE TO` (8.0.23+; ранее `CHANGE MASTER TO`), вставленная в дамп флагом `--source-data=2`. Позволяет начать репликацию или PITR ровно с состояния, зафиксированного дампом.

**`--ignore-error`** — флаг, подавляющий указанные ошибки, чтобы дамп продолжился: `--ignore-error=err1,err2,...` (список кодов через запятую, добавлен в MySQL 5.7.1). Применяется для кодов, означающих лишь недоступность отдельных таблиц. Если указан `--force`, он имеет приоритет и игнорирует все ошибки.

## Основные концепции

### Почему `--single-transaction` — основа консистентности

Без `--single-transaction` `mysqldump` (при `--lock-tables`, входящем в `--opt`) берёт `LOCK TABLES ... READ LOCAL` отдельно для каждой базы: таблицы блокируются до конца выгрузки этой базы, но консистентности **между базами** нет, и при параллельном DDL структура в дампе может перестать соответствовать данным.

С `--single-transaction` дамп — это **один** последовательный `SELECT` в рамках одной транзакции. InnoDB изолирует эту транзакцию через MVCC, поэтому:

- DML продолжает работать с полной скоростью;
- приложение видит обычное поведение;
- данные в дампе соответствуют одному моменту времени.

Цена — дамп не увидит изменений, произошедших после старта транзакции. Для PITR это компенсируется позицией binlog: binlog содержит все изменения, а значит повторное применение binlog поверх дампа восстановит полноту.

### Почему `mysqldump` иногда «висит»

Это самая частая проблема на практике и классический вопрос на собеседовании. Причина — **транзакция, открытая до старта дампа**.

Механизм: `START TRANSACTION WITH CONSISTENT SNAPSHOT` получает снимок **мгновенно** — других транзакций он не ждёт. Но незавершённая транзакция удерживает MDL (metadata lock) на таблицах, к которым она обращалась, до своего коммита; если за ней встала в очередь DDL (`ALTER TABLE`, `TRUNCATE`), DDL запрашивает `MDL_EXCLUSIVE` и блокирует все новые обращения к таблице — включая чтение `mysqldump`. На нагруженной базе с часовыми транзакциями (батч-импорт, `DELETE` больших объёмов, ручной `LOCK TABLES`) дамп может висеть часами, не потребляя ресурсов.

Проверка на сервере:

```sql
-- Транзакции, работающие дольше 60 секунд
SELECT trx_id, trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS seconds_running,
       trx_mysql_thread_id, trx_query
FROM information_schema.innodb_trx
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60
ORDER BY trx_started;
-- → trx_id: 918273645 seconds_running: 7402 trx_query: DELETE FROM audit_log WHERE ...
```

Меры:
1. Устранить источник — завершить или сократить длинную транзакцию.
2. Снять дамп с реплики, где нет длинных пишущих транзакций.
3. Перейти на `mysqlsh util.dumpInstance()`, где механизм snapshot другой.

> **Важно:** `--single-transaction` гарантирует согласованность только для InnoDB. Таблицы MyISAM, MEMORY и любые сторонние движки в него не входят — они копируются как есть и могут оказаться в рассогласованном состоянии относительно InnoDB-таблиц.

### Таблица критичных флагов

| Флаг | Назначение | Типичная ошибка при отсутствии |
| :--- | :--- | :--- |
| `--single-transaction` | Согласованный снимок InnoDB без блокировки записи | Дамп с рассинхронизированными данными при параллельной записи |
| `--source-data=2` | Позиция binlog в дампе (для PITR и репликации); требует `RELOAD` и включённый `log_bin` | Невозможно начать PITR, придётся подбирать позицию вручную |
| `--dump-replica[=1\|2]` | `CHANGE REPLICATION SOURCE TO` с координатами **source'а реплики** (для развёртывания новой реплики); автоматически останавливает/перезапускает SQL thread; перекрывает `--source-data` | Новая реплика стартует не с тех координат source'а |
| `--all-databases` | Все базы, включая `mysql` и `sys` | Дамп одной базы, когда нужны все |
| `--routines` | Хранимые процедуры и функции | Потеря всей серверной логики БД |
| `--triggers` | Триггеры (**включён по умолчанию**) | Указывается явно для самодокументируемости скрипта |
| `--events` | События планировщика | Теряются отчёты и регламентные операции |
| `--users` | Учётные записи и гранты в виде `CREATE USER` / `GRANT` (**только MySQL 9.3+**; там же `--include-user`, `--exclude-user`, `--add-drop-user`; несовместим с `--flush-privileges`). В 5.7/8.0/8.4 опции нет — пользователи живут в схеме `mysql` и выгружаются через `--all-databases` | Теряются все пользователи и их привилегии |
| `--no-tablespaces` | Не выгружать `CREATE TABLESPACE` | `Access denied` у непривилегированного пользователя на MySQL 8.0.21+ (чтение `INFORMATION_SCHEMA.FILES` требует `PROCESS`) |
| `--where` | Частичное условие `SELECT` | Невозможно выгрузить подмножество данных без ручного вырезания SQL |
| `--hex-blob` | Двоичные данные в HEX | Битые BLOB и бинарные строки в дампе |
| `--tz-utc` | Часовой пояс в TIMESTAMP (**включён по умолчанию**, отключается `--skip-tz-utc`) | Сдвиг времён при восстановлении на другой машине |
| `--ignore-error=1213,1205` | Пропускать указанные ошибки (список кодов через запятую, с 5.7.1): deadlock и lock wait timeout | Дамп обрывается на первой конфликтной транзакции; пропустить все ошибки — `--force` |
| `--force` | Продолжать дамп при любых SQL-ошибках (невалидные VIEW попадают в дамп как SQL-комментарий); приоритет над `--ignore-error` | Дамп обрывается на первой ошибке |
| `--flush-logs` | Ротация binlog в момент снимка (требует `RELOAD`) — чистое окно для PITR | PITR приходится собирать по всем binlog-файлам, включая предшествующие дампу |
| `--column-statistics=0` | Отключить чтение гистограмм (клиент 8.0 → сервер 5.x) | `Unknown table 'COLUMN_STATISTICS' in information_schema (1109)` |
| `--network-timeout` | Максимальный `max_allowed_packet` и большие сетевые таймауты для больших таблиц (включён по умолчанию с 8.0.1) | Обрыв дампа больших таблиц по медленной сети |
| `--max-allowed-packet=1G` | Максимальный размер пакета | `Got a packet bigger than 'max_allowed_packet' bytes` |
| `--set-gtid-purged` | Запись `Executed_Gtid_Set` для развёртывания реплики | `@@GLOBAL.GTID_PURGED` конфликт при загрузке дампа |

> **Обратите внимание на поведение по умолчанию:** включён `--opt` — shorthand для `--add-drop-table --add-locks --create-options --disable-keys --extended-insert --lock-tables --quick --set-charset` — и `--triggers`. `--routines`, `--events`, `--users` (9.3+) и `--source-data` по умолчанию **выключены** — их нужно указывать явно. Именно поэтому «по умолчанию» дамп теряет процедуры и события, хотя триггеры сохраняет.

### Депрекейтнутые и переименованные флаги

| Старое | Новое | Начиная с |
| :--- | :--- | :--- |
| `--master-data` | `--source-data` | MySQL 8.0.26 (старое имя работает как псевдоним) |
| `--dump-slave` | `--dump-replica` | MySQL 8.0.26 (старое имя работает как псевдоним) |
| `--apply-slave-statements` | `--apply-replica-statements` | MySQL 8.0.26 |
| `--delete-master-logs` | `--delete-source-logs` | MySQL 8.0.26 |
| `--include-master-host-port` | `--include-source-host-port` | MySQL 8.0.26 |

В MySQL 5.7 существуют **только** старые имена.

> **Совместимость терминологии в дампе (8.2+):** `--output-as-version=SERVER|BEFORE_8_2_0|BEFORE_8_0_23` позволяет снять дамп с сервера 8.2+ в терминологии, понятной более старым серверам — полезно при переносе дампов между версиями.

> **Грабли версий 8.0.26–8.0.29:** предупреждение о депрекейте утилит MySQL выводилось в **stdout**. При использовании перенаправки `mysqldump ... > dump.sql` строка `WARNING: --master-data is deprecated...` попадала в начало файла дампа и делала его невосстановимым — `mysql` отклонял файл с `ERROR 1064 (42000) at line 1`. Исправлено в MySQL 8.0.30 (предупреждения уходят в stderr). Практический вывод: дамп, созданный клиентом 8.0.26–8.0.29 с депрекейтнутым флагом, может оказаться непригодным — всегда проверяйте первые строки файла перед восстановлением.

### Права пользователя

Подробная таблица требований приведена в **[Пользователь бэкапа](./overview.md#пользователь-бэкапа-принцип-наименьших-привилегий)**. Кратко для `mysqldump`:

```sql
-- Рабочий минимум для консистентного полного дампа MySQL 8.0+
-- (совпадает с разделом «Пользователь бэкапа» в overview.md)
CREATE USER 'backup_user'@'localhost' IDENTIFIED BY 'StrongPassword!2024';
GRANT SELECT, RELOAD, SHOW DATABASES, REPLICATION CLIENT,
      LOCK TABLES, SHOW VIEW, EVENT, TRIGGER
  ON *.* TO 'backup_user'@'localhost';
-- REPLICATION CLIENT нужен --source-data / --dump-replica
-- (SHOW MASTER STATUS / SHOW REPLICA STATUS); для --source-data
-- также обязателен RELOAD и включённый log_bin
-- PROCESS нужен для --all-databases без --no-tablespaces на 8.0.21+
```

## Предварительные условия

- **Клиент `mysqldump` той же ветки, что и сервер.** Смешивание веток — источник ошибок: клиент 8.0 против сервера 5.7 падает с `Unknown table 'COLUMN_STATISTICS' in information_schema (1109)` (лекарство — `--column-statistics=0`; клиенты 8.1+ отключают гистограммы автоматически для серверов < 8.0.2).
- **Привилегии** из раздела «Права пользователя»; для `--source-data` — включённый `log_bin`.
- **Для PITR:** binlog включён до момента дампа и доступны все binlog-файлы от позиции дампа до целевого момента.
- **Свободное место:** несжатый дамп сопоставим по объёму с данными; при восстановлении — место под него на целевом хосте.
- **Сеть:** для больших таблиц по медленной сети — `--network-timeout` (включён по умолчанию с 8.0.1): максимальный packet и большие таймауты чтения/записи.

## Практические сценарии

### Сценарий 1: Базовый полный дамп с PITR-готовностью

```bash
#!/bin/bash
set -euo pipefail

DEST="/backups/mysql"
STAMP=$(date +%F_%H%M)

mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --single-transaction \
  --source-data=2 \
  --flush-logs \
  --routines --triggers --events \
  --no-tablespaces \
  --hex-blob --tz-utc \
  --all-databases 2>/tmp/mysqldump.err \
  | zstd -T0 -3 > "${DEST}/all_${STAMP}.sql.zst"

# exit_code=$? — с pipefail падение mysqldump НЕ маскируется успехом zstd
# → 0

# --flush-logs ротирует binlog в момент снимка (при --single-transaction
# и --source-data — один раз, в момент кратковременного GRL): все изменения
# после дампа оказываются в одном свежем binlog-файле — окно для PITR
# становится тривиальным. Требует RELOAD.

# Обязательная проверка: в начало файла не должна попасть строка WARNING
zstd -dc "${DEST}/all_${STAMP}.sql.zst" | head -2
# → -- MySQL dump 10.13  Distrib 8.4.12, for Linux (x86_64)
```

> **Важно:** `set -o pipefail` обязателен. Без него код возврата пайпа равен коду последней команды (`zstd`), и упавший на середине дамп будет записан «успешно». Это самая распространённая причина «битых» архивов бэкапа.

Восстановление с проверкой:

```bash
zstd -dc "${DEST}/all_2026-10-03_0300.sql.zst" \
  | mysql --user=root --password --default-character-set=utf8mb4
# → (без вывода при успехе)
```

### Сценарий 2: Дамп отдельной базы

```bash
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --single-transaction --routines --triggers --events \
  --no-tablespaces \
  mydb | zstd -T0 -3 > "/backups/mysql/mydb_$(date +%F).sql.zst"
# → 0
```

### Сценарий 3: Частичный дамп — выгрузка подмножества данных

Ключевой сценарий, отсутствующий в большинстве справочников: получить дамп только части данных без последующего вырезания SQL.

```bash
# Все записи одного дня
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --single-transaction --no-tablespaces \
  --where="created_at >= '2026-10-01' AND created_at < '2026-10-02'" \
  mydb orders | zstd -T0 -3 > /backups/mysql/orders_2026-10-01.sql.zst
# → 0

# Одна таблица без её содержимого (только схема)
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --no-data --no-tablespaces \
  mydb orders > /backups/mysql/orders_schema.sql
# → 0

# Только содержимое без схемы (в схему, созданную заранее)
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --single-transaction --no-create-info --no-tablespaces \
  mydb orders > /backups/mysql/orders_data.sql
# → 0
```

> **Ограничение:** `--where` принимает **один** литерал условия, применяемый ко всем таблицам дампа. Для разных условий на разные таблицы запускайте `mysqldump` отдельно на каждую таблицу.

### Сценарий 4: Дамп с устойчивостью к конфликтам блокировок

```bash
# Пропускать deadlock (1213) и lock wait timeout (1205) — дамп не должен
# падать из-за одной конфликтной транзакции в пиковую нагрузку
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --single-transaction --no-tablespaces \
  --skip-lock-tables \
  --ignore-error=1213,1205 \
  --all-databases 2>> /var/log/mysqldump.err \
  | zstd -T0 -3 > "${DEST}/all_$(date +%F_%H%M).sql.zst"
# → 0
```

Контроль пропущенных таблиц обязателен — иначе «успешный» дамп окажется неполным:

```bash
grep -i "could not execute\|error\|skipped" /var/log/mysqldump.err
# → если строки есть — дамп неполон, таблицы отсутствуют
```

> **Почему `--skip-lock-tables`:** `--lock-tables` (входит в `--opt`) блокирует таблицы `READ LOCAL` **отдельно для каждой базы** и не даёт консистентности между базами; для InnoDB при `--single-transaction` блокировки не нужны вовсе — снимок даёт MVCC. Явное отключение убирает бессмысленные блокировки. Для MyISAM без `--single-transaction` `--lock-tables`, наоборот, обязателен — иначе таблица может попасть в дамп в неконсистентном состоянии.

### Сценарий 5: Дамп с реплики

```bash
# Предпочтительно: снимать нагрузку с источника.
# Требование: STOP_REPLICA SQL_THREAD на время дампа, иначе позиция binlog
# будет указывать на состояние, отстающее от данных реплики.
mysql -e "STOP REPLICA SQL_THREAD;"

mysqldump --source-data=2 --single-transaction \
  --routines --triggers --events --no-tablespaces \
  --all-databases 2>/tmp/dump.err | zstd -T0 -3 > /backups/replica_all.sql.zst
RC=$?

mysql -e "START REPLICA SQL_THREAD;"
# → Replica_IO_Running: Yes  Replica_SQL_Running: Yes
```

Валидация синхронизации после старта:

```sql
SHOW REPLICA STATUS\G
-- → Replica_IO_Running: Yes
-- → Replica_SQL_Running: Yes
-- → Seconds_Behind_Source: 0
```

> **Альтернатива — `--dump-replica[=1|2]` (до 8.0.26 — `--dump-slave`):** если цель дампа — не PITR, а развёртывание **новой реплики** с тем же source'ом, `--dump-replica` запишет в дамп `CHANGE REPLICATION SOURCE TO` с координатами source'а (из `Relay_Master_Log_File`/`Exec_Master_Log_Pos`), сам остановит и перезапустит SQL thread и перекроет `--source-data`. С `--apply-replica-statements` в дамп добавятся `STOP REPLICA` перед координатами и `START REPLICA` в конце. **Не применяйте** `--dump-replica`, если сервер, на который будет загружен дамп, работает с `gtid_mode=ON` и `SOURCE_AUTO_POSITION=1`. Текущий сценарий (ручной `STOP REPLICA SQL_THREAD` + `--source-data`) записывает позицию binlog самой реплики — это правильный выбор для PITR с реплики.

### Сценарий 6: Извлечение одной таблицы из готового SQL-дампа

Когда разбирать доступен только гигантский `.sql`, а не его исходная команда.

```bash
# Определить границы: начало — CREATE TABLE, конец — закрывающий ;
# Для дампов с --single-transaction каждая таблица обёрнута в
# /*!40101 SET @saved_cs_client = @@character_set_client */;
grep -n "^CREATE TABLE\|^-- MySQL dump\|^/\*!40101" /backups/all.sql | head -20
# → 124850:CREATE TABLE `orders` (

# Извлечь по найденным границам
sed -n '124850,128050p' /backups/all.sql > /tmp/orders.sql
mysql mydb < /tmp/orders.sql
# → 0
```

Точный и безопасный способ через `sed` по имени таблицы с учётом её последующих `INSERT`:

```bash
TABLE="orders"
awk -v t="\`$TABLE\`" '
  $0 ~ "^CREATE TABLE " t { inblock=1 }
  inblock && /^UNLOCK TABLES;/ { print; inblock=0; exit }
  inblock { print }
' /backups/all.sql > /tmp/orders.sql
```

> **Ограничение:** извлечение из SQL-дампа не консистентно с данными, записанными после начала дампа. Для строгой консистентности используйте PITR — **[восстановление одной таблицы](./pitr.md#сценарий-6-восстановление-одной-таблицы-из-закрытого-бинарного-лога)**.

### Сценарий 7: Верификация целостности дампа без полного восстановления

```bash
# 1. Структурная проверка: файл не обрыван и начинается корректно
zstd -t /backups/mysql/all_2026-10-03_0300.sql.zst && echo "archive OK"
# → archive OK

zstd -dc /backups/mysql/all_2026-10-03_0300.sql.zst | head -1
# → -- MySQL dump 10.13  Distrib 8.4.12, for Linux (x86_64)
# Если вместо этого WARNING: -- ... — дамп создан клиентом 8.0.26–8.0.29 с
# депрекейтнутым флагом и не восстановится (см. «Грабли версий» выше)

# 2. Закрыт ли последний оператор
zstd -dc /backups/mysql/all_2026-10-03_0300.sql.zst | tail -3
# → /*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
# → /*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;
# Наличие завершающих SET означает, что файл не оборван на середине INSERT.

# 3. Сбалансированность: каждый CREATE имеет закрывающий ;
zstd -dc /backups/mysql/all_2026-10-03_0300.sql.zst \
  | grep -c "^CREATE TABLE"
# → 248
```

Полное тестовое восстановление в изолированный инстанс описано в **[Автоматизация и верификация](./automation.md#сценарий-4-smoke-тестирование-бэкапов)**.

### Сценарий 8: Дамп учётных записей и грантов

```bash
# MySQL 9.3+: только учётные записи и гранты (CREATE USER / GRANT).
# --users без --databases/--all-databases дампирует исключительно
# пользователей — без таблиц
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --users --add-drop-user 2>/tmp/users.err \
  > "/backups/mysql/users_$(date +%F).sql"
# → 0

# Точечный выбор (формат user@host), например прикладные аккаунты:
# mysqldump --users --include-user=app@web1 --include-user=app@web2
# Исключение системных: --exclude-user=mysql.sys@localhost ...
```

```bash
# MySQL 5.7 / 8.0 / 8.4: опции --users нет — пользователи и гранты
# живут в схеме mysql и выгружаются с --all-databases;
# --flush-privileges добавит FLUSH PRIVILEGES после схемы mysql
mysqldump --user=backup_user --password="$MYSQL_PWD" \
  --all-databases --flush-privileges \
  --routines --triggers --events --no-tablespaces \
  2>>/var/log/mysqldump.err | zstd -T0 -3 > "/backups/mysql/all_$(date +%F_%H%M).sql.zst"
# → 0
```

> `--users` несовместим с `--flush-privileges` — одновременное указание вызывает ошибку. В 5.7–8.4 полный перенос грантов — это восстановление дампа `--all-databases` на чистом сервере; для переноса только грантов на живой сервер выгружайте `--databases mysql` и восстанавливайте избирательно либо генерируйте `GRANT`-инструкции из `SHOW GRANTS FOR ...`.

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Дамп висит часами | Незавершённая транзакция удерживает MDL, за ней встала в очередь DDL (`MDL_EXCLUSIVE`) | Проверить `information_schema.innodb_trx`; снять дамп с реплики |
| `Got a packet bigger than 'max_allowed_packet' bytes` | Слишком большой `INSERT` (многострочный) или большой BLOB | `--max-allowed-packet=1G` (максимум 1 ГБ) на клиенте и на сервере |
| `Access denied; you need (at least one of) the PROCESS privilege(s)` | MySQL 8.0.21+, не задан `--no-tablespaces` | Добавить `--no-tablespaces` |
| `ERROR 1412: Table definition has changed` | Во время дампа выполнен DDL | Повторить дамп; вынести DDL в отдельное окно |
| `ERROR 1064 ... at line 1` при восстановлении | Строка `WARNING:` попала в дамп (клиент 8.0.26–8.0.29) | Пересоздать дамп; не использовать депрекейтнутые флаги |
| `@@GLOBAL.GTID_PURGED` конфликт при загрузке | `GTID_PURGED` целевого сервера не пуст, а дамп содержит `SET @@GLOBAL.GTID_PURGED` | На чистом целевом инстансе: `RESET MASTER` (обнуляет `GTID_PURGED`), затем загрузка дампа — дамп установит `GTID_PURGED` самостоятельно; ручная предустановка не требуется |
| Дамп завершился без ошибки, но таблиц мало | `--ignore-error` скрыл пропущенные таблицы | Проверять stderr; не использовать `--ignore-error` без контроля |
| `Unknown table 'COLUMN_STATISTICS' in information_schema (1109)` | Клиент `mysqldump` 8.0 (гистограммы включены по умолчанию) против сервера 5.7 и старше | `--column-statistics=0`; клиенты 8.1+ отключают гистограммы автоматически для серверов < 8.0.2; в идеале — клиент той же ветки |
| `Binary logging not active` при `--source-data` | `log_bin=OFF` | Включить binlog — он обязателен для PITR |
| Дамп пустой или почти пустой | Условие `--where` отсёкло все строки; база пуста; случайно указан `--no-data` | Проверить условие на выборке `SELECT COUNT(*)`; убедиться в имени базы; убрать `--no-data` |
| Дамп обрывается на невалидном VIEW (ссылается на удалённую таблицу) | View потеряла базовую таблицу | `--force` — дамп продолжится, определение view попадёт в дамп как SQL-комментарий; `--force` имеет приоритет над `--ignore-error` |
| Дамп с `--dump-replica` не применяется на целевом сервере | Целевой сервер в `gtid_mode=ON` с `SOURCE_AUTO_POSITION=1` | Документация предупреждает: не использовать `--dump-replica`/`--dump-slave` для таких целей; настроить репликацию вручную |

## Ограничения и особенности

1. **Только InnoDB для консистентности.** `--single-transaction` не защищает MyISAM, MEMORY и сторонние движки. Смешанный инстанс требует либо `FLUSH TABLES WITH READ LOCK`, либо перевода таблиц на InnoDB.
2. **Медленное восстановление.** Восстановление — это последовательный разбор SQL и построчный `INSERT`. На базах в сотни гигабайт часы на загрузку нормальны; для таких объёмов физический бэкап быстрее на порядок.
3. **Не переносит настройки экземпляра.** Логический дамп не содержит `my.cnf`, сертификатов TLS, keyring и состояния сервера. Их нужно восстанавливать отдельно.
4. **Чувствителен к `max_allowed_packet`.** Многострочные `INSERT` могут превысить лимит; на клиенте и сервере должно стоять одинаковое достаточно большое значение.
5. **Дамп — это SQL, а не бинарный формат.** Любая его правка (в том числе `sed`) делает согласованность не гарантированной.
6. **Снимок `--single-transaction` распространяется на данные таблиц.** Определения `routines`, `triggers`, `events` читаются отдельными запросами `SHOW CREATE` и не входят в MVCC-снимок: при одновременных изменениях их текст может не совпадать со снимком данных.
7. **Чувствителен к смешиванию версий клиента и сервера.** Клиент 8.0 против сервера 5.7 падает с ошибкой 1109 (`COLUMN_STATISTICS`) — нужны `--column-statistics=0` или клиент той же ветки (см. «Устранение неполадок»).
8. **Не заменяет физический бэкап для RTO.** Логический дамп — инструмент гибкости и переноса, а не скорости восстановления.

## Бест-практики

1. **Всегда `set -o pipefail`** в скриптах с пайпами — иначе падение дампа маскируется кодом возврата компрессора.
2. **Всегда полный набор флагов:** `--single-transaction --routines --events --no-tablespaces --source-data=2`. Дамп без `--routines` теряет процедуры и функции, без `--events` — задания планировщика. `--triggers` включён по умолчанию, но указывается явно: в скрипте должен быть виден полный состав выгружаемых объектов.
3. **Пишите пароль через `MYSQL_PWD` или файл `--defaults-extra-file` с правами `600`,** а не аргументом командной строки: аргументы видны в `ps` всем пользователям системы.
4. **Проверяйте первую строку дампа** перед признанием архива пригодным.
5. **Держите `max_allowed_packet` одинаковым** на клиенте и сервере, минимум 256 МБ для продакшена.
6. **Снимайте дамп с реплики**, а не с источника, сняв `STOP REPLICA SQL_THREAD` на время дампа.
7. **`--where` — для данных, а не для продакшен-стратегии.** Частичный дамп не является резервной копией.
8. **Используйте `--source-data=2`, а не `--master-data=2`,** на MySQL 8.0.26+ и не смешивайте версии клиента и сервера.
9. **Храните лог дампа (`stderr`) вместе с архивом** — в нём видны пропущенные таблицы и предупреждения.
10. **Для MySQL 8.0.21+ предпочитайте `mysqlsh util.dumpInstance()`:** многопоточность, встроенная консистентность и меньший объём. `mysqldump` держите для совместимости, частичного дампа и унаследованных систем 5.7.
11. **Добавляйте `--flush-logs`** к дампу с `--source-data` — binlog ротируется в момент снимка, и окно PITR начинается с одного файла.
12. **Для развёртывания реплики из дампа реплики используйте `--dump-replica`** вместо ручного снятия координат — он сам остановит SQL thread и запишет координаты source'а.
13. **Дампите учётные записи регулярно:** гранты не входят в дамп отдельных баз — либо `--all-databases --flush-privileges` (5.7–8.4), либо `--users` (9.3+).

## Дополнительная информация

### См. также

- **[Обзор инструментов бэкапа](./overview.md)** — сравнение физических и логических методов, консистентность, привилегии, выбор инструмента.
- **[MySQL Shell Dump & Load](./mysql_shell_dump.md)** — многопоточная альтернатива для MySQL 8.0+.
- **[Point-in-Time Recovery](./pitr.md)** — восстановление на произвольный момент, в том числе одной таблицы из binlog.
- **[Автоматизация и верификация](./automation.md)** — скрипты, `flock`, ротация, smoke-тестирование, метрики.
- **[Проверка целостности и тестовое восстановление](../../Concepts/backup_validation.md)** — уровни валидации архивов.
- **[Управление бинарным логом](../replication/binlog_management.md)** — ротация и архивирование binlog для PITR.
- **[GTID-репликация](../replication/gtid.md)** — `--set-gtid-purged` и развёртывание реплики из дампа.
- **[Хранилища MySQL](../Operations/storage_engines_deep_dive.md)** — почему `--single-transaction` не работает для не-InnoDB движков.
- **[Настройка репликации MySQL](../replication/setup_guide.md)** — использование дампа как источника реплики.

### Внешние ресурсы

- **[mysqldump — MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html)** — полный справочник флагов и требуемых привилегий.
- **[Using mysqldump for Backups — MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/using-mysqldump.html)** — перезагрузка дампов, `--tab`, советы по бэкапам.
- **[mysqldump — MySQL 5.7 Reference Manual](https://dev.mysql.com/doc/refman/5.7/en/mysqldump.html)** — для legacy-версий (только старые имена флагов).
- **[MySQL Shell Dump & Load Guide](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-utilities-dump-instance-schema.html)** — рекомендуемая альтернатива для 8.0+.
