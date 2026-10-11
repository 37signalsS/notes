# Обработка ошибок SQL-потока репликации

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS

## Определения

**SQL error in replication** — ошибка, возникающая при применении события из Relay Log SQL-потоком (или worker-потоком в MTS). Если код ошибки на реплике отличается от кода на источнике (или ошибка есть только на одной стороне), SQL-поток останавливается: `Replica_SQL_Running: No`, реплика ждёт решения администратора.

**Event group (группа событий)** — последовательность событий в бинарном логе. Для транзакционных таблиц event group соответствует транзакции, для нетранзакционных (MyISAM и др.) — одному SQL-оператору. Одна транзакция может содержать изменения и транзакционных, и нетранзакционных таблиц.

**`sql_slave_skip_counter` / `sql_replica_skip_counter`** — счётчик событий, которые реплика пропустит при следующем `START REPLICA`. Работает с событиями, а не с транзакциями: если позиция после пропуска оказывается в середине event group, реплика продолжает пропуск до конца группы. Переименована в 8.0.18 (`sql_slave_skip_counter` → `sql_replica_skip_counter`).

**`slave_skip_errors` / `replica_skip_errors`** — глобальная **нединамическая** переменная (задаётся только в `my.cnf`/командной строке, `SET GLOBAL` не работает): SQL-поток не останавливается, если оператор вернул код из списка. Переименована в 8.0.18.

**`ddl_exist_errors`** — символическое значение `replica_skip_errors`, эквивалентное списку кодов `1007,1008,1050,1051,1054,1060,1061,1068,1091,1146` (ошибки «объект уже существует / не существует» при DDL).

## Базовые концепции

### Когда SQL-поток останавливается, а когда — нет

- **Одинаковый код ошибки на источнике и реплике** — ошибка только логируется, репликация продолжается.
- **Разные коды (или ошибка только на одной стороне)** — SQL-поток завершается, пишет в error log и ждёт администратора.
- **Временные ошибки** (например, deadlock) — клиент ретраит транзакцию самостоятельно; ручной рестарт не нужен, пока поток не завершился нетривиальной ошибкой.
- **Нетранзакционные движки** (MyISAM): оператор может частично обновить таблицу и вернуть ошибку (multi-row INSERT с нарушением уникальности, убитый длинный UPDATE). Источник ожидает на реплике тот же код ошибки.
- **Разные движки на источнике и реплике**: один оператор может давать разный код (FK-нарушение на InnoDB-источнике vs отсутствие ошибки на MyISAM-реплике) — репликация остановится.
- **Фильтры репликации** применяются первыми: отфильтрованные транзакции не проверяются и не порождают ошибок.

### Что именно пропускает skip

`sql_replica_skip_counter` оперирует **событиями**, а не транзакциями:
- один оператор = обычно одно событие;
- операторы с `AUTO_INCREMENT` или `LAST_INSERT_ID()` = **два** события (правило N=1/N=2);
- при `binlog_transaction_compression` сжатый payload (`Transaction_payload_event`) считается одним значением — всё содержимое пропускается как блок;
- пропуск всегда добирает до конца event group: транзакция не остаётся применённой наполовину.

### Типичные коды ошибок применения

| Код | Символ | Сообщение / смысл | Типичная причина |
| :--- | :--- | :--- | :--- |
| 1007 | `ER_DB_CREATE_EXISTS` | database exists | `CREATE DATABASE` для существующей БД |
| 1008 | `ER_DB_DROP_EXISTS` | database doesn't exist | `DROP DATABASE` для отсутствующей БД |
| 1022 | `ER_DUP_KEY` | Can't write; duplicate key | дубликат ключа при записи |
| 1032 | `ER_KEY_NOT_FOUND` | Can't find record in ... | UPDATE/DELETE по несуществующей строке (чаще при ROW) |
| 1048 | `ER_BAD_NULL_ERROR` | Column ... cannot be null | NOT NULL-колонка без значения |
| 1050 | `ER_TABLE_EXISTS_ERROR` | Table ... already exists | `CREATE TABLE` для существующей таблицы |
| 1051 | `ER_BAD_TABLE_ERROR` | Unknown table ... | DROP/ALTER несуществующей таблицы |
| 1054 | `ER_BAD_FIELD_ERROR` | Unknown column ... | разрыв схемы |
| 1060 | `ER_DUP_FIELDNAME` | Duplicate column name | дубликат колонки в DDL |
| 1061 | `ER_DUP_INDEX` | Duplicate key name | дубликат индекса в DDL |
| 1062 | `ER_DUP_ENTRY` | Duplicate entry ... for key ... | вставка существующей строки |
| 1068 | `ER_DUP_KEYNAME` | Multiple primary key defined | повторный PRIMARY KEY в DDL |
| 1091 | `ER_CANT_DROP_FIELD_OR_KEY` | Can't drop ...; check that column/key exists | DROP несуществующего индекса/колонки |
| 1146 | `ER_NO_SUCH_TABLE` | Table ... doesn't exist | обращение к отсутствующей таблице |
| 1364 | `ER_NO_DEFAULT_FOR_FIELD` | Field ... doesn't have a default value | несовпадение схем / STRICT-режим |
| 1451 | `ER_ROW_IS_REFERENCED_2` | Cannot delete or update a parent row | FK-ограничение (ссылается родительская строка) |
| 1452 | `ER_NO_REFERENCED_ROW_2` | Cannot add or update a child row | FK-ограничение (отсутствует родительская строка) |

Коды берутся из `Last_SQL_Error` в `SHOW REPLICA STATUS` и из error log реплики.

## Приусловия

- **Версии:** `sql_slave_skip_counter` → `sql_replica_skip_counter` и `slave_skip_errors` → `replica_skip_errors` переименованы в **8.0.18**; `SHOW SLAVE STATUS` → `SHOW REPLICA STATUS` — в **8.0.22**. На 5.7 используйте старые имена.
- **Привилегии:** `SET GLOBAL sql_replica_skip_counter` требует `SYSTEM_VARIABLES_ADMIN` (на 5.7 — `SUPER`). `replica_skip_errors` меняется только через `my.cnf` и рестарт сервера.
- **Потоки остановлены:** перед любым пропуском остановлены оба потока (`STOP REPLICA;`), иначе `SET GLOBAL sql_replica_skip_counter` отклоняется.
- **Режим GTID определяет метод:** при `gtid_mode=ON` счётчик применить нельзя (`SET GLOBAL sql_replica_skip_counter` отклоняется) — используйте метод с `GTID_NEXT`.
- **Диагностический доступ:** нужен доступ к error log реплики и к relay log (`SHOW RELAYLOG EVENTS` или `mysqlbinlog` по пути из `relay_log_basename`).

## Практический блок

### Диагностика: что именно сломалось

```sql
SHOW REPLICA STATUS\G
-- Ключевые поля: Replica_SQL_Running, Last_SQL_Errno, Last_SQL_Error,
-- Relay_Master_Log_File, Exec_Master_Log_Pos, (для GTID) Executed_Gtid_Set
```

Содержимое relay log вокруг ошибки — тремя способами:

```sql
SHOW RELAYLOG EVENTS IN 'relay-bin.000123' FROM 12345;
-- → события relay log на реплике (имя файла — из Relay_Master_Log_File/Relay_Log_File)
```
```sql
SHOW BINLOG EVENTS IN 'binlog.000123' FROM 12345;
-- → то же событие на источнике (по Relay_Master_Log_File)
```
```bash
mysqlbinlog --verbose --base64-output=DECODE-ROWS /var/lib/mysql/relay-bin.000123 | head -80
# путь /var/lib/mysql/relay-bin.000123 — пример; реальный путь: SHOW VARIABLES LIKE 'relay_log_basename';
```

Для MTS ошибка возникает в worker-потоке: GTID проблемной транзакции — в поле `APPLYING_TRANSACTION` таблицы `performance_schema.replication_applier_status_by_worker`; детали ошибки и последней применённой транзакции — в той же таблице.

### Метод 1. Пропуск транзакции по GTID (`gtid_mode = ON`)

Единственный метод при `gtid_mode=ON`. Суть — «выполнить» пустую транзакцию с тем же GTID: реплика посчитает проблемную транзакцию уже применённой и auto-skip пропустит её при старте.

```sql
STOP REPLICA;
-- GTID берём из Last_SQL_Error (или из APPLYING_TRANSACTION при MTS)
SET GTID_NEXT='3E11FA47-71CA-11E1-9E33-C80AA9429562:542';  -- UUID:SEQNO проблемной транзакции
BEGIN;
COMMIT;
SET GTID_NEXT='AUTOMATIC';
START REPLICA;
```

Нюансы:
- **Каскадная репликация:** если на реплике включён бинарный лог и она может стать источником в будущем, пустая транзакция попадёт в поток репликации. Чтобы этого избежать: `FLUSH LOGS; PURGE BINARY LOGS TO 'binlog.000146';` (GTID сохраняется, сама транзакция удаляется из лога).
- **Multi-source:** имя канала не нужно при коммите пустой транзакции, но `START REPLICA FOR CHANNEL 'channel_name'` — обязательно.
- Полная механика GTID — `gtid.md` (раздел «Пропуск проблемной транзакции»), краткий рецепт — `management_debug.md`.

### Метод 2. Счётчик событий (без GTID: `gtid_mode` OFF / OFF_PERMISSIVE / ON_PERMISSIVE)

```sql
STOP REPLICA;
SET GLOBAL sql_replica_skip_counter = 1;  -- 8.0.18+; на 5.7: SET GLOBAL sql_slave_skip_counter = 1
START REPLICA;
SHOW REPLICA STATUS\G
```

Правила:
- **N=1 или N=2:** `N=1`, если следующий оператор не использует `AUTO_INCREMENT`/`LAST_INSERT_ID()`; иначе `N=2`.
- **Нет немедленного эффекта:** значение применяется при следующем `START REPLICA`, после чего автоматически сбрасывается в 0. Повторный skip требует нового `SET GLOBAL`.
- **Multi-source:** `START REPLICA FOR CHANNEL 'channel_name'` обязателен — иначе события пропустятся на неверном канале.
- **Проверка после:** `Replica_SQL_Running: Yes`, `Last_SQL_Error` пусто, позиции растут.

### Метод 3. Сдвиг позиции (`CHANGE REPLICATION SOURCE TO`)

Альтернатива счётчику: перезапуск с указанной позиции источника (начало следующего event group). Не учитывает event groups — позицию нужно определить точно, на начало группы. Нельзя применять при `SOURCE_AUTO_POSITION=1` без временного отключения:

```sql
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
  SOURCE_AUTO_POSITION=0,
  SOURCE_LOG_FILE='binlog.000145',   -- файл и позиция — начало следующей транзакции
  SOURCE_LOG_POS=235;
CHANGE REPLICATION SOURCE TO SOURCE_AUTO_POSITION=1;  -- вернуть GTID-автопозиционирование
START REPLICA;
```

### Метод 4. Маскирование ошибок (`replica_skip_errors`) — крайняя мера

**Переменная нединамическая:** `SET GLOBAL replica_skip_errors` не работает — значение задаётся в `my.cnf` и применяется только после рестарта сервера.

```ini
# my.cnf, секция [mysqld] — только временно!
replica_skip_errors = 1062,1032      # список кодов через запятую
# или: replica_skip_errors = ddl_exist_errors   (= 1007,1008,1050,1051,1054,1060,1061,1068,1091,1146)
# на 5.7 имя переменной: slave_skip_errors
```
```bash
sudo systemctl restart mysql   # → параметр применён
```

Отключение — убрать строку (или установить пустое значение) и снова перезапустить сервер:

```ini
replica_skip_errors =
```

Проверка текущего значения:

```sql
SHOW VARIABLES LIKE 'replica_skip_errors';
-- → replica_skip_errors | 1062,1032   (пусто, если не задано)
```

Предупреждение из документации: «не используйте эту опцию, пока не понимаете, почему возникают ошибки... бесконтрольное применение приводит к полной рассинхронизации реплики». Значение `all` (игнорировать все ошибки) лишает реплику любых гарантий целостности данных. `replica_skip_errors` — глобальная переменная: в multi-source действует на все каналы (per-channel настройки нет).

### Типовые сценарии

**Сценарий 1: Duplicate entry (1062).** Причина: на реплике вручную вставили строку с тем же PK/UNIQUE, затем с источника пришла такая же вставка (ROW). Правильное решение — найти конфликтующую строку на обеих сторонах, определить версию, удалить конфликтующую строку на реплике (`SET sql_log_bin=0; DELETE ...`) и запустить репликацию **без skip**. Skip оправдан только при осознанном решении потереть вставку.

**Сценарий 2: Can't find record (1032) при UPDATE/DELETE.** На реплике нет строки. Решение: вставить недостающую строку в том же виде (`SET sql_log_bin=0`) либо осознанно пропустить событие. Требует анализа, какой вариант консистентнее.

**Сценарий 3: Table already exists (1050) / doesn't exist (1146).** Часто покрывается значением `ddl_exist_errors`, но лучше проверить структуру: если совпадает — можно пропустить событие; если отличается — серьёзное расхождение схем, разбираться.

**Сценарий 4: FK-ошибки (1451/1452).** Обычно следствие применения части транзакции или ручных правок на реплике. Исправлять данные на реплике консистентно, а не маскировать код.

### Безопасный алгоритм действий при SQL-ошибке

1. **Сохранить контекст:** `SHOW REPLICA STATUS\G` — зафиксировать `Last_SQL_Errno`/`Last_SQL_Error`, файл/позицию, `Executed_Gtid_Set`.
2. **Проверить безопасность:** транзакция из неизвестного/недоверенного источника? Если да — разобраться до рестарта.
3. **Понять событие:** `SHOW RELAYLOG EVENTS` / `SHOW BINLOG EVENTS` / `mysqlbinlog`; для MTS — `APPLYING_TRANSACTION` в `replication_applier_status_by_worker`.
4. **Оценить влияние:** нужна ли транзакция на реплике? Нужна ли была на источнике (если нет — откатить там вручную)?
5. **Исправить причину, а не симптом:** правка данных на реплике (`SET sql_log_bin=0`) + перезапуск без skip.
6. **Skip — только когда причина понята и расхождение принято.** После любого skip при первой возможности — проверка консистентности (`pt-table-checksum`, методика — `consistency_checks.md`).
7. **`replica_skip_errors` держать нельзя** — снять (рестарт с пустым значением) сразу после инцидента.

## Валидация

После пропуска:

```sql
SHOW REPLICA STATUS\G
-- → Replica_SQL_Running: Yes
-- → Last_SQL_Error: (пусто)
-- → Exec_Master_Log_Pos: растёт при повторных вызовах
-- → Seconds_Behind_Source: 0 или тренд к 0 (интерпретация — lag_monitoring.md)
```
```sql
SELECT @@GLOBAL.gtid_executed;  -- при GTID: GTID проблемной транзакции присутствует (пропущена как применённая)
```

Для метода 2: `SHOW VARIABLES LIKE 'sql_replica_skip_counter';` после `START REPLICA` вернёт `0` (счётчик одноразовый).

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка повторяется сразу после skip | Пропущено событие, а ошибка в следующем | Анализировать следующее событие; skip только после понимания каждого случая |
| `SET GLOBAL sql_replica_skip_counter` отклонён | `gtid_mode=ON` или потоки работают | Остановить потоки; при `gtid_mode=ON` — метод 1 (`GTID_NEXT`) |
| `SET GLOBAL replica_skip_errors` «не работает» | Переменная нединамическая | Задать в `my.cnf` и перезапустить сервер |
| События пропущены на неверном канале | Multi-source без `FOR CHANNEL` при `START REPLICA` | Указывать `START REPLICA FOR CHANNEL 'channel_name'` |
| Пропущена часть транзакции | ROW-формат: event group ≠ 1 событие | Помнить: skip добирает до конца event group; считать события до конца транзакции |
| `replica_skip_errors` не снимается | Значение осталось в `my.cnf` | Убрать/опустошить параметр + рестарт |

## Граничные случаи

- **MTS:** ошибка в worker-потоке останавливает канал; GTID — из `APPLYING_TRANSACTION` (`replication_applier_status_by_worker`). Автоматическое устранение gaps с 5.7.13 — `parallel_replication_mts.md`.
- **Multi-source:** счётчик и маскирование — глобальные; пропускать строго с `FOR CHANNEL`.
- **Каскадная репликация:** пустая GTID-транзакция (метод 1) попадёт в поток, если реплика — источник для других; см. `FLUSH LOGS` + `PURGE BINARY LOGS` выше.
- **`binlog_transaction_compression`:** сжатый payload считается одним событием для счётчика.
- **Нетранзакционные движки:** частичное применение оператора возможно; источник ожидает тот же код ошибки на реплике.
- **`ASSIGN_GTIDS_TO_ANONYMOUS_TRANSACTIONS`:** GTID-присвоение каналу ≠ GTID-репликация; не-GTID методы пропуска для такого канала применимы, но метод 1 — нет.
- **Отложенная репликация** (`delayed_replication.md`): ошибка применения обнаружится с задержкой; окно задержки — точка восстановления для логических ошибок.

## Лучшие практика

- Приоритет — анализ и консистентная правка данных (`SET sql_log_bin=0`), skip — исключение.
- GTID-репликация (рекомендуемый режим) даёт транзакционно-точный пропуск через `GTID_NEXT`; без GTID пропуск неточен по природе.
- `replica_skip_errors` — только временно, только с пониманием каждого кода; `all` — практически никогда не оправдан.
- После любого skip — `pt-table-checksum` (методика — `consistency_checks.md`).
- Мониторинг `Last_SQL_Errno`/`Last_SQL_Error` — `lag_monitoring.md`, алертинг — `../monitoring.md`.

## Дополнительная информация

- **Связанные файлы:** `gtid.md` (GTID-механика и пропуск транзакции), `management_debug.md` (отладка и рецепт GTID_NEXT), `multi-source.md` (каналы и `FOR CHANNEL`), `parallel_replication_mts.md` (MTS и gaps), `lag_monitoring.md` (лаг), `consistency_checks.md` (pt-table-checksum), `delayed_replication.md` (отложенная репликация), `relay_logs_crashsafe.md` (relay log), `failover_switchover.md` (проверка перед промоушеном), `../troubleshooting-runbook.md`
- **Ключевые команды/переменные:** `SHOW REPLICA STATUS`, `SHOW RELAYLOG EVENTS`, `SHOW BINLOG EVENTS`, `SET GLOBAL sql_replica_skip_counter`, `replica_skip_errors` (startup-only), `GTID_NEXT`
- **Внешние ссылки:** [Replica Server Options and Variables (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-options-replica.html), [Skipping Transactions (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-administration-skip.html), [Replica Errors During Replication (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-features-errors.html), [Troubleshooting Replication (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-problems.html)
