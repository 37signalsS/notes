# GTID: практические сценарии

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS

## Определения

**GTID (Global Transaction Identifier)** — глобальный уникальный идентификатор транзакции во всей репликационной топологии. Формат: `UUID:transaction_id` (например, `3E11FA47-71CA-11E1-9E33-C80AA9429562:1-5`). Множества GTID записываются через запятую, диапазоны — через дефис: `UUID:1-100,UUID:105-200`.

**Executed_Gtid_Set** — множество GTID транзакций, которые **успешно применены** на данном сервере. Включает и локальные (непротоколированные через репликацию) транзакции — не только полученные от источника.

**Retrieved_Gtid_Set** — множество GTID транзакций, которые **получены** I/O-потоком с источника и записаны в Relay Log (ещё могут быть не применены SQL-потоком).

**gtid_purged** — GTID транзакций, которые были зафиксированы на сервере, но уже удалены из бинарного лога (purged). Подмножество `gtid_executed`. Определяет «нижнюю границу» для восстановления: транзакций из этого набора источник отправить не может, их физически нет в логах.

**AUTO_POSITION** — режим автоматического позиционирования при подключении реплики к источнику по GTID (без указания `SOURCE_LOG_FILE`/`SOURCE_LOG_POS`).

## Базовые концепции

### Преимущества GTID в операционных сценариях

- **Failover/Switchover упрощены:** не нужно искать точные `File:Pos`. Достаточно `AUTO_POSITION=1`.
- **Безопаснее восстановление:** проще определить, какие транзакции есть/нет на узле.
- **Клонирование реплик:** из бэкапа с GTID проще встраивать узел в существующую топологию.
- **Поиск расхождений по транзакциям:** `Executed_Gtid_Set` даёт чёткую картину применённых транзакций.

### Ключевые переменные

- `gtid_mode` — `OFF`, `OFF_PERMISSIVE`, `ON_PERMISSIVE`, `ON`. Переключение возможно **только на один шаг** за раз (нельзя перейти с `OFF_PERMISSIVE` сразу на `ON`). Значения `gtid_executed`/`gtid_purged` сохраняются корректными при любой смене `gtid_mode`.
- `enforce_gtid_consistency` — `OFF`, `WARN`, `ON` (`WARN` добавлен в MySQL 5.7.6). При `ON` запрещены не-GTID-совместимые конструкции (`CREATE TABLE ... SELECT`, `CREATE/DROP TEMPORARY TABLE` внутри транзакций). Должно быть `ON` до включения `gtid_mode=ON`.
- `gtid_executed` — GTID всех применённых транзакций на сервере (системная переменная).
- `gtid_purged` — GTID, удалённые из бинлога. Категории: транзакции реплики, зафиксированные с выключенным бинлогированием; транзакции из purged бинлог-файлов; GTID, добавленные явно через `SET @@GLOBAL.gtid_purged`.
- `binlog_gtid_simple_recovery` — `ON` (дефолт): при старте `gtid_executed`/`gtid_purged` вычисляются только по самому новому и самому старому бинлогу — быстро при большом числе файлов.

### GTID vs File:Pos при подключении

**С GTID (`AUTO_POSITION=1`):**
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='master',
  SOURCE_PORT=3306,
  SOURCE_USER='repl',
  SOURCE_PASSWORD='pass',
  SOURCE_AUTO_POSITION=1;
```

Реплика автоматически найдёт, с какой позиции продолжать, сравнивая свои `Executed_Gtid_Set` с тем, что есть на источнике.

**Без GTID:** явно указываем `SOURCE_LOG_FILE`, `SOURCE_LOG_POS` (в MySQL 5.7 и 8.0 до 8.0.23 — `MASTER_LOG_FILE`, `MASTER_LOG_POS`).

## Приусловия

- `gtid_mode = ON` **на источнике** — иначе подключение с `SOURCE_AUTO_POSITION=1` не удастся (реплика может быть в `ON_PERMISSIVE`/`OFF_PERMISSIVE`, источник обязан быть в `ON`).
- Одинаковый `gtid_mode` на всех узлах топологии; смешанный режим (`ON_PERMISSIVE`/`OFF_PERMISSIVE`) допустим только как переходный при миграции.
- Бинарный лог включён на источнике (GTID хранятся в бинлоге).
- Привилегии: `REPLICATION CLIENT` — для `SHOW BINARY LOG STATUS` / `SHOW REPLICA STATUS`; право устанавливать глобальные системные переменные — для `SET GLOBAL`.

## Практический блок

### 1. Проверка GTID-состояния

На любом узле:
```sql
SHOW VARIABLES LIKE 'gtid_mode';
SHOW VARIABLES LIKE 'enforce_gtid_consistency';
```

GTID, применённые на текущем сервере:
```sql
SELECT @@GLOBAL.gtid_executed AS gtid_executed;
-- или
SHOW BINARY LOG STATUS\G  -- содержит Executed_Gtid_Set (с 8.2; в 5.7/8.0 — SHOW MASTER STATUS)
```

GTID, полученные/применённые на реплике:
```sql
SHOW REPLICA STATUS\G
-- Retrieved_Gtid_Set, Executed_Gtid_Set
```

GTID, вычищенные из бинлога:
```sql
SELECT @@GLOBAL.gtid_purged AS gtid_purged;
```

Ожидаемый результат: `gtid_mode = ON`, `gtid_executed` растёт по мере фиксации транзакций, `gtid_purged` пуст на только что развёрнутом узле.

### 2. Сравнение GTID-наборов и проверка догоняния

**Детерминированная проверка «реплика догнала источник»** (вместо сравнения сырых наборов):
```sql
-- На источнике: SELECT @@GLOBAL.gtid_executed;  → '<набор_источника>'
-- На реплике:
SELECT WAIT_FOR_EXECUTED_GTID_SET('<набор_источника>', 60);
-- → 0 — все транзакции набора применены; 1 — не дождались за 60 сек; другое — ошибка
```
`WAIT_FOR_EXECUTED_GTID_SET()` проверяет условие `GTID_SUBSET(gtid_set, @@GLOBAL.gtid_executed)` и учитывает **все** применённые GTID (все каналы и клиентские сессии), независимо от состояния потоков репликации. Дефолтный `timeout=0` — ждать бесконечно; отрицательный timeout в strict mode — ошибка `ER_WRONG_ARGUMENTS`.

**Ручное сравнение наборов:**
```sql
-- Все ли транзакции набора источника применены на реплике?
SELECT GTID_SUBSET('<набор_источника>', @@GLOBAL.gtid_executed);
-- → 1 — да (подмножество); 0 — нет; NULL — если любой аргумент NULL

-- Какие транзакции есть на источнике, но не применены на реплике
SELECT GTID_SUBTRACT('<набор_источника>', @@GLOBAL.gtid_executed) AS not_applied;
-- → пустой набор '' — реплика догнала
```

**Важно:** `gtid_executed` реплики может содержать **локальные** транзакции (выполнены при `super_read_only = OFF`) и транзакции, применённые с выключенным бинлогированием. Поэтому «`gtid_executed` реплики ⊆ `gtid_executed` источника» — **неверный** критерий догоняния. Проверяйте в правильном направлении: набор источника ⊆ набор реплики (или через `WAIT_FOR_EXECUTED_GTID_SET`).

### 3. Failover с GTID (практика)

Полный runbook (промоушен, переподключение, возврат старого источника, автоматический failover) — см. `failover_switchover.md`. GTID-специфичное ядро:

- **Выбор кандидата:** реплика, чей `gtid_executed` **содержит все транзакции источника** и **не содержит «лишних» локальных** транзакций:
```sql
-- На каждом кандидате:
SELECT GTID_SUBSET('<набор_источника>', @@GLOBAL.gtid_executed);      -- → 1 — транзакции источника на месте
SELECT GTID_SUBTRACT(@@GLOBAL.gtid_executed, '<набор_источника>');     -- → '' — «лишних» локальных нет
```
- **Не выбирайте кандидата по «наибольшему `Executed_Gtid_Set`»:** набор может быть больше за счёт локальных транзакций, которых источник не знает, — при подключении остальных реплик к такому узлу возникнет рассинхрон (ошибка 1885).
- После промоушена остальных реплик подключаем с `SOURCE_AUTO_POSITION=1`:
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='new_master',
  SOURCE_PORT=3306,
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='repl_pass',
  SOURCE_AUTO_POSITION=1;
START REPLICA;
```

### 4. Подключение реплики из бэкапа (с GTID)

**Путь A — mysqldump:**
```bash
mysqldump --all-databases --single-transaction --set-gtid-purged=ON > dump.sql
# → в дампе: SET @@SESSION.sql_log_bin=0 и SET @@GLOBAL.gtid_purged = '+<набор>'
#   (знак '+' — добавление к существующему gtid_purged, в version-specific comment)
```
- `--set-gtid-purged` (дефолт `AUTO`): добавляет `SET @@GLOBAL.gtid_purged`, если на сервере `gtid_mode=ON` и `gtid_executed` не пуст. При загрузке дампа на новом узле `gtid_purged` заполняется автоматически — остаётся `CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION=1`.
- Частичный дамп (не все БД) требует **явного** `--set-gtid-purged={ON|OFF}`.
- `OFF` — для repair внутри топологии или для disjoint-топологий (тогда `SET @@SESSION.sql_log_bin=0` в дамп не добавляется).
- Не рекомендуется загружать дамп, содержащий системные таблицы, при `gtid_mode=ON` (DML по системным таблицам MyISAM не допускается).
- `--single-transaction` + `gtid_mode=ON` + `--set-gtid-purged=ON|AUTO` требует привилегии `RELOAD` или `FLUSH_TABLES`.

**Путь B — XtraBackup (`--slave-info`):** координаты источника записываются в файл `xtrabackup_slave_info` командой `CHANGE REPLICATION SOURCE TO` (File:Pos). В GTID-топологии: если в `xtrabackup_slave_info` записан `SOURCE_AUTO_POSITION=1` — используйте его; GTID-координаты для контроля также есть в `xtrabackup_binlog_info`. Детали — в `backup_replication.md`.

**Путь C — Clone Plugin (MySQL 8.0.17+):** при `CLONE INSTANCE FROM ...` состояние GTID передаётся автоматически — после перезапуска достаточно `CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION=1` (см. `gtid.md`, раздел «Автоматизация через Clone Plugin»).

**Ограничения ручного `SET @@GLOBAL.gtid_purged`** (ручное вмешательство — только при понимании последствий):
- новый набор должен **включать** все GTID, уже находящиеся в `gtid_purged` (добавлять можно, убирать нельзя);
- не должен включать GTID из `gtid_executed`, ещё не удалённые из бинлога, и GTID из `@@GLOBAL.gtid_owned` (транзакции в процессе);
- добавление GTID в `gtid_purged` **одновременно добавляет их в `gtid_executed`**;
- в MySQL 5.7.6+ задаётся при любом `gtid_mode`; до 5.7.6 — только при `gtid_mode=ON`.

**Валидация после развёртывания:**
```sql
SELECT @@GLOBAL.gtid_purged;
-- → набор покрывает все транзакции, зафиксированные в бэкапе
SHOW REPLICA STATUS\G
-- → Replica_IO_Running: Yes, Replica_SQL_Running: Yes, Last_IO_Error пуст
```
Если `gtid_purged` занижен (меньше реального набора транзакций бэкапа) — реплика применит транзакции повторно и получит ошибку дублирования ключа (1062).

### 5. RESET REPLICA vs RESET REPLICA ALL

Разница (MySQL 5.7 терминология `SLAVE`, в 8.0 — `REPLICA`):

| Команда | Что делает | Когда использовать |
| :--- | :--- | :--- |
| `RESET REPLICA` | Очищает Relay Log, сбрасывает Relay Log info/позиции, но **не удаляет** конфигурацию подключения (SOURCE_HOST/PORT/USER/PASSWORD и др.) из памяти/репозитория каналов | Хотим перезапустить репликацию с той же конфигурацией источника, но с «чистыми» Relay Logs (например, после исправления) |
| `RESET REPLICA ALL` | Полностью очищает всю конфигурацию репликации для канала (включая параметры подключения). Удаляет Relay Logs, master/relay info. Для всех каналов, если без `FOR CHANNEL` | Реплика больше **не будет** подключаться к старому источнику (промоушен в мастер, перенос топологии). Требует повторного `CHANGE REPLICATION SOURCE TO` |

Операционные детали (важно для SRE):
- Обе команды требуют привилегии `RELOAD` и **остановленных** потоков репликации (`STOP REPLICA`).
- `RESET REPLICA` удаляет **все** relay-log файлы, **даже неприменённые** — неприменённые транзакции теряются. При необходимости прочитайте их (`Retrieved_Gtid_Set` / relay-log) до сброса.
- `RESET REPLICA ALL` сбрасывает `SOURCE_DELAY` в **0** — на отложенной реплике (`delayed_replication.md`) задержка после сброса пропадает.
- Для одного канала в multi-source: `RESET REPLICA [ALL] FOR CHANNEL 'имя'` (см. `multi-source.md`).

**GTID-замечание:** обе команды влияют на состояние репликации, но не меняют `gtid_executed`/`gtid_purged` сервера автоматически. Работать аккуратно.

### 6. Типичные ошибки и их решения

| Ошибка | Что означает | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **1789** (`ER_SOURCE_HAS_PURGED_REQUIRED_GTIDS`; в 8.0 до 8.0.26 — `ER_MASTER_HAS_PURGED_REQUIRED_GTIDS`) | Источник удалил бинлоги с GTID, нужными реплике для догоняния | `binlog_expire_logs_seconds`/`expire_logs_days` очистил логи быстрее, чем реплика догнала | Список недостающих GTID — в error log источника (предупреждение `ER_FOUND_MISSING_GTIDS`). Получить недостающие транзакции с **другого** источника или заменить реплику более свежим бэкапом; автоматического восстановления нет |
| **1885** (`Replica has more GTIDs than source`) | Реплика «обгоняет» источник | `RESET MASTER`/`RESET BINARY LOGS AND GTIDS` на источнике при работающих репликах; локальные транзакции на реплике | Разбор по GTID-наборам (`GTID_SUBTRACT`) — `gtid.md` «Устранение неисправностей», `multi-source.md`; возврат реплики в топологию — `failover_switchover.md` раздел 3 |
| **1782** | `GTID_NEXT = 'ANONYMOUS'` при `gtid_mode = ON` — анонимная транзакция не может быть записана | Приложение/инструмент явно выставил `GTID_NEXT='ANONYMOUS'` на узле с `gtid_mode=ON` | Убрать `ANONYMOUS` из приложения; на время миграции — перевести узел в `ON_PERMISSIVE` |
| **1062** (Duplicate entry) | Повторное применение транзакций | `gtid_purged` после восстановления из бэкапа занижен (не покрывает все транзакции бэкапа) | Правильно выставить `gtid_purged` (раздел 4); в перспективе — восстановить из корректного бэкапа |
| **Не подключается с `AUTO_POSITION=1`** | Автопозиционирование недоступно | Источник не в `gtid_mode=ON` (обязателен для AUTO_POSITION) | Включить `gtid_mode=ON` на источнике (one-step переходы, см. «Базовые концепции») |

**Ловушка с `Retrieved` vs `Executed`:** `Retrieved_Gtid_Set` растёт (I/O догоняет), `Executed_Gtid_Set` отстаёт (SQL применяет) — нормальное состояние при лаге. Ключевой для определения применённых транзакций — `Executed_Gtid_Set` (мониторинг лага — `lag_monitoring.md`).

## Граничные случаи

- **Фильтры репликации не отфильтровывают GTID.** `replicate-do-*` применяется к данным транзакции, но GTID всё равно фиксируются на реплике — набор GTID реплики остаётся согласованным с источником, и `AUTO_POSITION` не требует заново запрашивать отфильтрованные транзакции.
- **Multi-source:** `gtid_executed` — объединение наборов всех каналов; операции сброса/ожидания — с `FOR CHANNEL` (см. `multi-source.md`).
- **Delayed replica:** работает с GTID корректно (источник отправляет все транзакции, включая отложенные; см. `delayed_replication.md`), но `RESET REPLICA ALL` сбрасывает `SOURCE_DELAY` в 0.
- **`GTID_ONLY=1` (8.0.27+):** не сохранять имена файлов и позиции в репозиториях метаданных; требует `REQUIRE_ROW_FORMAT=1`, `SOURCE_AUTO_POSITION=1` и row-based бинарный лог. При отключении `SOURCE_AUTO_POSITION` некоторые позиции становятся невалидными — потребуются явные `SOURCE_LOG_FILE`/`SOURCE_LOG_POS` (см. `failover_switchover.md`).
- **Отключение GTID на работающем сервере:** переходы только на один шаг в обратном порядке (`ON` → `ON_PERMISSIVE` → `OFF_PERMISSIVE` → `OFF`); см. MySQL Reference Manual, «Changing GTID Mode on Online Servers» (ссылка в «Дополнительной информации»).

## Лучшие практика

1. **Алертинг на рост `gtid_purged` на источнике.** Если `gtid_purged` приближается к `gtid_executed` — активная ротация логов; проверьте, что реплики не отстают (детали — `gtid.md`, «Лучшие практика»).
2. **Retention бинлогов > максимального лага реплики** (`binlog_expire_logs_seconds`/`expire_logs_days`), иначе при отставании реплики возникнет ошибка 1789.
3. **Аудит ручных изменений** `gtid_executed`/`gtid_purged` — любое вмешательство документируется и подтверждается.
4. **Никогда не правьте строки `mysql.gtid_executed` напрямую через DML** и не выполняйте `RESET BINARY LOGS AND GTIDS` (с 8.1; в 5.7/8.0 — `RESET MASTER`, deprecated в 8.2, удалён в 8.4) при живых репликах — GTID-история станет невидимой, расхождение невозможно диагностировать.
5. **Тестируйте failover на стенде** (плановый switchover и аварийный failover), документируйте RTO/RPO.
6. **Храните метаданные бэкапа вместе с копией** (`xtrabackup_slave_info`, `xtrabackup_binlog_info`) — без них подключение в репликацию невозможно (см. `backup_replication.md`).

## Дополнительная информация

- **Связанные файлы:** `gtid.md` (механика GTID, миграция на GTID, пропуск транзакций, устранение неисправностей), `failover_switchover.md` (runbook failover/switchover), `backup_replication.md` (XtraBackup и GTID), `multi-source.md`, `delayed_replication.md`, `lag_monitoring.md`, `../troubleshooting-runbook.md`
- **Ключевые переменные:** `gtid_mode`, `enforce_gtid_consistency`, `gtid_executed`, `gtid_purged`, `gtid_next`, `gtid_owned`, `binlog_gtid_simple_recovery`, `gtid_executed_compression_period`, `binlog_expire_logs_seconds`
- **Функции:** `GTID_SUBSET()`, `GTID_SUBTRACT()`, `WAIT_FOR_EXECUTED_GTID_SET()`
- **Команды:** `CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION=1`, `RESET REPLICA`, `RESET REPLICA ALL`, `SET @@GLOBAL.gtid_purged`, `SET GTID_NEXT`
- **Внешние ссылки:** [MySQL 8.4 Reference Manual — GTID Auto-Positioning](https://dev.mysql.com/doc/refman/8.4/en/replication-gtids-auto-positioning.html), [GTID Life Cycle](https://dev.mysql.com/doc/refman/8.4/en/replication-gtids-lifecycle.html), [Global Transaction ID System Variables](https://dev.mysql.com/doc/refman/8.4/en/replication-options-gtids.html), [Functions Used with GTIDs](https://dev.mysql.com/doc/refman/8.4/en/replication-gtids-functions.html), [Changing GTID Mode on Online Servers](https://dev.mysql.com/doc/refman/8.4/en/replication-mode-change-online.html), [Percona XtraBackup — GTID-based replica](https://docs.percona.com/percona-xtrabackup/8.4/create-gtid-replica.html)
