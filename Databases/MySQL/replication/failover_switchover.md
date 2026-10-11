# Failover и Switchover в MySQL репликации

**Актуально для:** MySQL 8.0.23+ / 8.4 LTS (синтаксис `STOP REPLICA`, `RESET REPLICA`, `CHANGE REPLICATION SOURCE TO`; `RESET BINARY LOGS AND GTIDS` — с MySQL 8.1, `SHOW BINARY LOG STATUS` — с MySQL 8.2; в 8.0 — `RESET MASTER` / `SHOW MASTER STATUS`, deprecated в 8.2 и удалены в 8.4). Asynchronous Connection Failover — с MySQL 8.0.22. Переименование плагинов semi-sync (`rpl_semi_sync_source_*`) — с 8.0.26. Замечания по MySQL 9.x — в разделе «Граничные случаи».

## Определения

**Switchover (плановое переключение)** — контролируемое переключение роли источника на реплику при живом старом источнике: запись блокируется, реплика догоняет, выполняется промоушен, остальные реплики переподключаются. Потеря данных — нулевая при GTID-верификации догона. Типичный повод — обслуживание (патч, миграция, замена оборудования).

**Failover (аварийное переключение)** — переключение на реплику при недоступности текущего источника. Цель — восстановить запись с минимальными потерями; RPO зависит от топологии (async > 0, semi-sync ≈ 0 для подтверждённых транзакций).

**Split-brain** — ситуация, когда два узла одновременно принимают запись как источники, что приводит к расхождению данных. В классической репликации предотвращается fencing'ом (`super_read_only`) и процедурой, а не механизмом — в отличие от Group Replication (кворум Paxos, см. `../high_availability.md`).

**Fencing** — гарантированная блокировка записи на узле: `super_read_only = ON` (блокирует даже пользователей с `SUPER`), сетевой изоляция, вывод из ротации прокси.

**read_only / super_read_only** — системные переменные защиты от записей. `read_only = ON` блокирует запись для всех без `SUPER`; `super_read_only = ON` — для всех, включая `SUPER`. Применение реплицированных событий SQL-потоком не блокируется этими переменными — иначе репликация на read-only репликах была бы невозможна. На репликах держать `super_read_only = ON` постоянно.

**RPO / RTO** — максимально допустимая потеря данных (Recovery Point Objective) и время восстановления доступности записи (Recovery Time Objective). Целевые значения по топологиям — в таблице `../high_availability.md`.

## Базовые концепции

### Switchover vs Failover

| Аспект | Switchover (плановый) | Failover (аварийный) |
| :--- | :--- | :--- |
| Старый источник | Жив, доступен | Недоступен или ненадёжен |
| Потеря данных | Нулевая (верификация догона) | Возможна: RPO зависит от async/semi-sync и GTID |
| Ключевая проверка | `WAIT_FOR_EXECUTED_GTID_SET` / `SOURCE_POS_WAIT` (не только `Seconds_Behind_Source`) | Сравнение `Executed_Gtid_Set` через `GTID_SUBSET` / `GTID_SUBTRACT` |
| Кандидат | Заранее выбран и проверен | Выбирается по максимальному применённому GTID-набору |
| Трафик приложения | Переключается по плану (ProxySQL / Orchestrator) | Переключается сразу после промоушена |

### Роль read_only/super_read_only (fencing)

- `super_read_only = ON` на реплике — защита от случайной прямой записи даже для администраторов; репликация при этом продолжает работать.
- При промоушене: `read_only = OFF`, `super_read_only = OFF` (требуется `SYSTEM_VARIABLES_ADMIN` или deprecated `SUPER`).
- После switchover бывший источник перевести в `super_read_only = ON` сразу после остановки записи — до решения о возврате в топологию.

### Почему GTID безопаснее для failover

- `Executed_Gtid_Set` однозначно идентифицирует применённые транзакции; `SOURCE_AUTO_POSITION=1` при переподключении запрашивает только недостающее.
- Без GTID — File:Pos (`Relay_Master_Log_File` / `Exec_Master_Log_Pos`): больше ручных проверок и риск ошибки позиции.
- `GTID_ONLY=1` (8.0.27+) — не сохранять имена файлов и позиции в репозиториях метаданных; требует `REQUIRE_ROW_FORMAT=1` и `SOURCE_AUTO_POSITION=1`, row-based бинарный лог.

### Что происходит с semi-sync при смене источника

- При отказе источника все коммиченные транзакции находятся на реплике (в relay log) — failover на подтвердившую реплику lossless (документация 8.4: «failover to the replica is lossless because the replica is up to date»). Источник после такого failover не должен использоваться («the source should not be reused after the failover»).
- Wait point: при `AFTER_SYNC` источник ждёт ACK до коммита — клиент не видит транзакцию, которой нет на реплике. При `AFTER_COMMIT` источник опережает реплику — последние коммиты могут быть потеряны (`rpl_semi_sync_master_wait_point`).
- На новом источнике должен быть активен source-side плагин: `rpl_semi_sync_source_enabled = ON` (8.0.26+; старое имя `rpl_semi_sync_master_enabled` — плагины старого и нового имени несовместимы на одном инстансе). Если переменная была ON на всех узлах — промоутенный узел сразу работает как semi-sync источник.
- Автодеградация в async при таймауте (`rpl_semi_sync_master_timeout`, дефолт 10000 мс) — детали в `semi-sync-replication.md`.
- Мониторинг: `Rpl_semi_sync_master_status` (0 = плагин выключен или деградировал), `Rpl_semi_sync_master_clients`, `Rpl_semi_sync_master_yes_tx` / `no_tx`.

## Приусловия

| Операция | Необходимая привилегия |
| :--- | :--- |
| `SHOW REPLICA STATUS`, `SHOW BINARY LOG STATUS` | `REPLICATION_CLIENT` (или deprecated `SUPER`) |
| `STOP REPLICA`, `START REPLICA`, `CHANGE REPLICATION SOURCE TO` | `REPLICATION_SLAVE_ADMIN` (или deprecated `SUPER`) |
| `RESET REPLICA`, `RESET BINARY LOGS AND GTIDS`, `FLUSH TABLES WITH READ LOCK` | `RELOAD` |
| `SET GLOBAL read_only` / `super_read_only` | `SYSTEM_VARIABLES_ADMIN` (или deprecated `SUPER`) |

Прочее:

- GTID (`gtid_mode=ON`, `enforce_gtid_consistency=ON`) — настоятельно рекомендуется; без него сценарий File:Pos.
- Уникальные `server_id`; `log_bin=ON` на всех кандидатах; `log_replica_updates=ON` (по умолчанию) — обязательно для каскадов.
- Учётная запись репликации должна существовать на каждом потенциальном источнике (для Asynchronous Connection Failover — одинаковые логин и пароль на всех источниках списка + `SELECT` на `performance_schema`).
- `binlog_expire_logs_seconds` — с запасом для самого медленного догона (иначе `AUTO_POSITION` упадёт на purged binlogs).
- Актуальный бэкап кандидата, runbook, мониторинг лага (`lag_monitoring.md`).

## Практический блок

### 1. Switchover (плановое)

Обозначения: `M1` — текущий источник, `R1` — реплика-кандидат. Основной сценарий — GTID; вариант File:Pos — отдельным блоком.

#### Шаг 1. Проверить кандидата
```sql
-- На R1
SHOW REPLICA STATUS\G
```
Критерии готовности:
- `Replica_IO_Running = Yes`, `Replica_SQL_Running = Yes`
- `Last_IO_Error` и `Last_SQL_Error` пусты
- нет «лишних» локальных транзакций в `Executed_Gtid_Set` (кандидат должен быть чистым — иначе при переподключении остальных реплик к R1 возникнут GTID-конфликты; см. `gtid.md`)
- для отложенной реплики (`SQL_Delay > 0`) сначала снять задержку и дождаться догона (см. `delayed_replication.md`)

#### Шаг 2. Заблокировать запись на M1
```sql
-- На M1 (SYSTEM_VARIABLES_ADMIN или SUPER)
SET GLOBAL super_read_only = ON;
```
`super_read_only` блокирует запись для всех, включая `SUPER`; текущие транзакции должны завершиться самостоятельно. `FLUSH TABLES WITH READ LOCK` (требует `RELOAD`) здесь не обязателен — он нужен для согласованного снапшота, а не для блокировки записи; при `super_read_only=ON` запись уже закрыта.

#### Шаг 3. Зафиксировать позицию M1
```sql
-- На M1
SELECT @@GLOBAL.gtid_executed;
-- → '3E11FA47-71CA-11E1-9E33-C80AA9429562:1-578'   (запомнить как M1_pos)
```

#### Шаг 4. Дождаться полного догона на R1 (GTID)
```sql
-- На R1
SELECT WAIT_FOR_EXECUTED_GTID_SET('M1_pos', 60);
-- → 0   все транзакции из M1_pos применены
-- → 1   таймаут: НЕ продолжать switchover
```
`WAIT_FOR_EXECUTED_GTID_SET()` проверяет условие `GTID_SUBSET(gtid_set, @@GLOBAL.gtid_executed)`; учитывает все применённые GTID (все каналы и клиентские сессии), независимо от состояния потоков репликации. Дефолтный `timeout=0` — ждать бесконечно; отрицательный timeout в strict mode — ошибка `ER_WRONG_ARGUMENTS`.

File:Pos-вариант (без GTID):
```sql
-- На M1
SHOW BINARY LOG STATUS\G
-- → File: source-bin.000003, Position: 123456
-- На R1
SELECT SOURCE_POS_WAIT('source-bin.000003', 123456, 60);
-- → число событий, на которых ждали (>=0) — догнал
-- → -1 — таймаут; NULL — SQL-поток не запущен или ошибка
```
`SOURCE_POS_WAIT()` (8.0.26+; `MASTER_POS_WAIT` deprecated с 8.0.26) блокируется, пока реплика не прочитает и не применит события до указанной позиции; возвращает немедленно, если позиция уже пройдена.

Почему недостаточно только `Seconds_Behind_Source == 0`: значение 0 не гарантирует полноту догона в пограничных случаях (I/O-поток не работает, обрыв сети, NULL-семантика в 9.7) — GTID-проверка детерминирована; caveats — в `lag_monitoring.md`.

#### Шаг 5. Остановить репликацию и обнулить конфигурацию на R1
```sql
-- На R1
STOP REPLICA;
RESET REPLICA ALL;
```
`RESET REPLICA ALL` (требует `RELOAD`, потоки должны быть остановлены) очищает репозитории метаданных, удаляет ВСЕ relay-логи (даже неприменённые), сбрасывает `SOURCE_DELAY` в 0 и стирает конфигурацию подключения — R1 становится независимым источником. В multi-source очищает все каналы; для одного канала — `RESET REPLICA ALL FOR CHANNEL 'имя'`. GTID-историю (`gtid_executed` / `gtid_purged`) не трогает.

#### Шаг 6. Разрешить запись на R1
```sql
-- На R1
SET GLOBAL read_only = OFF;
SET GLOBAL super_read_only = OFF;
```

#### Шаг 7. Переподключить остальные реплики к R1
```sql
-- На каждой оставшейся реплике (включая бывший M1)
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST = 'r1_host',
  SOURCE_PORT = 3306,
  SOURCE_USER = 'repl',
  SOURCE_PASSWORD = 'repl_pass',
  SOURCE_AUTO_POSITION = 1;
START REPLICA;
```
При GTID начальная позиция определяется автоматически (`AUTO_POSITION` запрашивает у R1 недостающие транзакции). Убедитесь, что `repl`@`replica_ip` существует на R1 и может подключаться (`GRANT REPLICATION SLAVE, REPLICATION CLIENT`).
File:Pos: добавить `SOURCE_LOG_FILE='source-bin.000003', SOURCE_LOG_POS=123456` из `SHOW BINARY LOG STATUS` на R1.

#### Шаг 8. Валидация
```sql
-- На R1
SHOW BINARY LOG STATUS\G;   -- новая позиция источника
SHOW REPLICAS;              -- подключённые реплики (8.0.22+)
-- На каждой реплике
SHOW REPLICA STATUS\G
```
Чек-лист:
- [ ] `Replica_IO_Running=Yes`, `Replica_SQL_Running=Yes`, ошибок нет
- [ ] `Last_IO_Error` / `Last_SQL_Error` пусты
- [ ] бывший M1 переведён в `super_read_only=ON` (fencing до решения о возврате)
- [ ] трафик приложения переключён (ProxySQL hostgroups — `../ProxySQL/proxysql_failover.md`; graceful takeover Orchestrator — `../orchestrator.md`)
- [ ] после switchover — проверка консистентности (`consistency_checks.md`)

### 2. Failover (аварийный)

Источник M1 недоступен. Реплики R1, R2.

#### Шаг 1. Собрать состояние со всех доступных реплик
```sql
SHOW REPLICA STATUS\G
```
Фиксировать: `Executed_Gtid_Set`, `Retrieved_Gtid_Set`, `Last_IO_Error`, `Last_SQL_Error`, `Replica_SQL_Running_State`, `Relay_Master_Log_File` / `Exec_Master_Log_Pos` (File:Pos). `Seconds_Behind_Source` при недоступном источнике ненадёжен (может быть NULL: applier не работает или relay-log исчерпан — семантика 9.7; см. `lag_monitoring.md`).

#### Шаг 2. Выбрать кандидата
GTID-сравнение (на каждом кандидате):
```sql
-- Содержит ли кандидат все транзакции другого кандидата?
SELECT GTID_SUBSET('<gtid_executed_другого_кандидата>', @@GLOBAL.gtid_executed);
-- → 1 — да (надмножество); 0 — нет (есть неприменённые транзакции)
-- Какие транзакции из набора источника кандидат НЕ применил (должно быть пусто):
SELECT GTID_SUBTRACT('<gtid_executed_источника_если_известен>', @@GLOBAL.gtid_executed);
```
Правила выбора:
- Кандидат с наиболее полным `Executed_Gtid_Set` (надмножество наборов остальных).
- Исключить кандидатов с «лишними» локальными транзакциями (записи при `super_read_only=OFF`) — их `gtid_executed` содержит GTID, которых нет в потоке источника; при промоушене остальные реплики не смогут догнать такой набор (ошибка при `AUTO_POSITION`; см. `gtid.md`).
- Проверить `Last_SQL_Error` — кандидат с ошибкой применения не годится.
- File:Pos: максимальная пара `Relay_Master_Log_File` + `Exec_Master_Log_Pos`.
- Отложенная реплика: сначала `SOURCE_DELAY=0` и полный догон (`delayed_replication.md`).
- При сомнении в доступности M1 (flapping) — не промоутить; дождаться стабилизации сети.

#### Шаг 3–5. Промоушен и переподключение
Повторить шаги 5–7 из switchover:
```sql
-- На кандидате
STOP REPLICA;
RESET REPLICA ALL;
SET GLOBAL read_only = OFF;
SET GLOBAL super_read_only = OFF;
SHOW BINARY LOG STATUS\G;   -- зафиксировать позицию нового источника
-- На остальных репликах
CHANGE REPLICATION SOURCE TO ... SOURCE_AUTO_POSITION = 1;
START REPLICA;
```

#### Шаг 6. Переключить трафик приложения на новый источник.

#### Шаг 7. Валидация
Чек-лист шага 8 switchover + мониторинг лага.

#### Шаг 8. Старый источник (M1) — не трогать
Не подключать как источник и не подключать как реплику «как есть». При semi-sync все коммиченные транзакции были на реплике, но M1 мог коммитнуть транзакции после последней репликации (async-пропасть). Возврат — раздел 3.

### 3. Возврат старого источника в топологию (rejoin)

Проблема: на M1 могли коммитнуться транзакции, которых нет на новом источнике R1 (RPO > 0 при async).

Анализ расхождений:
```sql
-- На M1 и на R1
SELECT @@GLOBAL.gtid_executed;
-- Транзакции, которые есть на M1, но нет на R1 (выполнить на любом узле, имеющем оба набора):
SELECT GTID_SUBTRACT('<gtid_executed_M1>', '<gtid_executed_R1>');
-- → пусто — M1 не опережает R1, можно подключать как реплику
-- → непусто — есть расхождение, нужен вариант A или B
```

**Вариант A (предпочтительный):** восстановить M1 из бэкапа R1 (xtrabackup / PITR — `../backup_and_recovery/pitr.md`) и подключить как реплику к R1 с `SOURCE_AUTO_POSITION=1`.

**Вариант B (advanced, только если «лишние» транзакции ценны):** перенести изменения с M1 на R1 вручную (`SET sql_log_bin=0` + применение изменений) либо внедрить пустые транзакции / скорректировать `gtid_purged` по методике «Using GTIDs for Failover and Scaleout» (см. `gtid.md`). Требует полного понимания GTID-механики.

Перед подключением M1 к R1:
```ini
# my.cnf на M1 — потоки не стартуют автоматически после рестарта
[mysqld]
skip_replica_start = ON    # до 8.0.23: skip_slave_start
```
```sql
-- На M1
SET GLOBAL super_read_only = ON;   -- fencing до окончательного решения
```
Запрещено: `RESET BINARY LOGS AND GTIDS` (с 8.1; в 5.7/8.0 — `RESET MASTER`, deprecated в 8.2, удалён в 8.4) на M1 «для очистки истории» — оператор удаляет `gtid_executed` / `gtid_purged` и все binlog-файлы, расхождение становится невидимым; операция не предназначена для запуска при живых репликах (поведение не определено).

### 4. Автоматическое переключение соединения (Asynchronous Connection Failover, 8.0.22+)

Что это: механизм автоматического переподключения I/O-потока реплики к альтернативному источнику из списка при обрыве соединения. Механизм НЕ промоутит реплику и не переключает запись — он поддерживает синхронизацию реплик после того, как новый источник выбран (вручную или Orchestrator).

Требования:

- `gtid_mode=ON` и `SOURCE_AUTO_POSITION=1` на канале;
- одинаковая учётная запись репликации (логин и пароль) на ВСЕХ источниках списка;
- учётные данные заданы через `CHANGE REPLICATION SOURCE TO` (хранятся в crash-safe репозиториях и доступны при автоматическом перезапуске);
- `GRANT SELECT ON performance_schema.*` для учётной записи репликации.

Настройка:
```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST = 'm1_host',
  SOURCE_PORT = 3306,
  SOURCE_USER = 'repl',
  SOURCE_PASSWORD = 'repl_pass',
  SOURCE_AUTO_POSITION = 1,
  SOURCE_CONNECTION_AUTO_FAILOVER = 1,
  SOURCE_RETRY_COUNT = 3,
  SOURCE_CONNECT_RETRY = 10;
START REPLICA;

-- Добавить альтернативные источники в список (вес 1..100; 100 — высший):
SELECT asynchronous_connection_failover_add_source('', 'r1_host', 3306, '', 60);
SELECT asynchronous_connection_failover_add_source('', 'r2_host', 3306, '', 60);
```

Ключевые параметры и дефолты:

- `SOURCE_RETRY_COUNT=86400` и `SOURCE_CONNECT_RETRY=60` (дефолты 8.0/8.4) — повтор попыток одного и того же источника в течение 60 дней: механизм failover не активируется вовремя. Документированные значения для failover: `SOURCE_RETRY_COUNT=3`, `SOURCE_CONNECT_RETRY=10`. (В MySQL 9.x дефолт изменён на 10 попыток / 10 минут.)
- Механизм срабатывает только при обрыве или остановке приёмника из-за недоступности источника или сети; `STOP REPLICA` вручную — не триггер.
- Механизм также переключается, если подключённый источник не имеет максимального веса в списке.
- Для managed-групп (Group Replication): `asynchronous_connection_failover_add_managed(channel, 'GroupReplication', group_name, host, port, '', 80, 60)` — веса primary 80 / secondary 60; с 8.0.27 активируется автоматически на primary single-primary группы (member action `mysql_start_failover_channels_if_primary`).

Функции управления списком: `asynchronous_connection_failover_add_source(channel, host, port, network_namespace, weight)`, `_delete_source(channel, host, port, network_namespace)`, `_add_managed()`, `_delete_managed()`, `_reset()` (8.0.27+, очищает обе P_S-таблицы).

Мониторинг:
```sql
SELECT * FROM performance_schema.replication_asynchronous_connection_failover;
SELECT * FROM performance_schema.replication_asynchronous_connection_failover_managed;
SELECT CHANNEL_NAME, SOURCE_CONNECTION_AUTO_FAILOVER, SOURCE_RETRY_COUNT, SOURCE_CONNECT_RETRY
  FROM performance_schema.replication_connection_configuration;
```
(Таблицы-источники списков: `mysql.replication_asynchronous_connection_failover`, `mysql.replication_asynchronous_connection_failover_managed`.)

Уровень автоматизации выше (выбор кандидата, промоушен, перестроение топологии, переключение прокси):

- **Orchestrator** — `../orchestrator.md`: discovery, автоматический failover, graceful takeover, Raft для HA самого Orchestrator. Upstream-репозиторий архивирован (февраль 2025), разработку с 2026 ведёт ProxySQL (`github.com/ProxySQL/orchestrator`, с 4.30.0 — нативная интеграция hostgroups ProxySQL); Percona поддерживает свой форк для K8s-операторов.
- **MHA** (Master High Availability Manager) — legacy-инструмент, не развивается; вытеснен Orchestrator.
- **Group Replication / InnoDB Cluster** — встроенный автоматический failover на основе кворума; другой механизм, не классическая репликация — `../high_availability.md`.

### Граничные случаи

- **MTS (`slave_parallel_workers > 0`)**: применение координируется coordinator-потоком; failover-логика (сравнение GTID, промоушен) не меняется. Детали — `parallel_replication_mts.md`.
- **Multi-source**: все операции `CHANGE REPLICATION SOURCE TO` требуют `FOR CHANNEL 'имя'`; `RESET REPLICA ALL` очищает все каналы — `multi-source.md`.
- **Каскадная топология**: промоушен промежуточной реплики требует перенастройки всей цепочки ниже (суммарный лаг складывается) — `topologies.md`.
- **MySQL 9.x**: семантика `Seconds_Behind_Source` изменилась (NULL, если applier не работает или relay-log исчерпан и приёмник не работает; 0, если приёмник работает, а relay-log исчерпан); дефолты `SOURCE_RETRY_COUNT` / `SOURCE_CONNECT_RETRY` — 10 попыток / 10 минут; измерение лага по timestamp'ам событий (9.5+) — `lag_monitoring.md`.

## Диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `WAIT_FOR_EXECUTED_GTID_SET` вернул 1 | Реплика не догнала за timeout | Проверить `Last_SQL_Error`, лаг, нагрузку; не промоутить |
| `SOURCE_POS_WAIT` вернул -1 / NULL | Таймаут / SQL-поток не запущен | `START REPLICA SQL_THREAD`, проверить ошибки |
| Ошибка при `AUTO_POSITION` после failover («...has purged binary logs», «GTID ... not found») | Расхождение GTID: у реплики/источника транзакции, которых нет на другой стороне | `GTID_SUBTRACT` → раздел 3 (rebuild или reconcile) |
| Ошибка подключения реплики к новому источнику (auth / access denied) | `repl`-аккаунт отсутствует на новом источнике или не может подключиться с хоста реплики | `CREATE USER` / `GRANT REPLICATION SLAVE, REPLICATION CLIENT` на новом источнике для `repl`@`replica_ip` |
| `Seconds_Behind_Source` = NULL при failover | Applier не работает или relay-log исчерпан (семантика 9.7) | Ориентироваться на GTID-сравнение, не на `Seconds_Behind_Source` |
| `RESET REPLICA` отказывается выполняться | Потоки репликации запущены | `STOP REPLICA;` перед `RESET REPLICA` |
| Старый источник ожил и принимает запись | `read_only` / `super_read_only` выключены — угроза split-brain | Немедленно `SET GLOBAL super_read_only=ON`, изолировать узел, анализ расхождений |
| `Rpl_semi_sync_master_status` = 0 на новом источнике | Source-side плагин не активен или деградация в async | `SET GLOBAL rpl_semi_sync_source_enabled=ON` (или `rpl_semi_sync_master_enabled` для старого плагина); проверить таймаут |
| Orchestrator не детектирует сбой | Проблемы с правами MySQL, сетевые фильтры, SPOF-установка | Проверить пользователя Orchestrator, порты, Raft-кворум (`../orchestrator.md`) |

## Лучшие практика

- **GTID + `SOURCE_AUTO_POSITION=1` везде** — failover становится детерминированным; без GTID — только File:Pos с ручными проверками.
- **`super_read_only=ON` на всех репликах постоянно** — дешёвый fencing; снимать только на время промоушена.
- **Плановые switchover по runbook** с `WAIT_FOR_EXECUTED_GTID_SET`; аварийные — по разделу 2; тестировать оба сценария на стенде, документировать RTO/RPO (`master_slave_mechanism.md`).
- **Запас бинарных логов** (`binlog_expire_logs_seconds`) для самого медленного догона — иначе переподключение упадёт на purged binlogs.
- **Мониторинг**: лаг (`lag_monitoring.md`), `Rpl_semi_sync_*`, P_S-таблицы репликации; алерты с учётом задержек (`delayed_replication.md`).
- **После любого failover/switchover** — проверка консистентности (`consistency_checks.md`), особенно если применялся `sql_replica_skip_counter` или был сомнительный выбор кандидата.
- **Не промоутить при flapping** — убедиться в стабильности сети/узла; Orchestrator считает источник живым, пока реплики получают события.
- **Каскады и multi-source** — промоушен промежуточного узла требует перенастройки цепочки; операции с каналами — через `FOR CHANNEL`.
- **Задержанные реплики** — не кандидаты без снятия `SOURCE_DELAY` и полного догона.

## Дополнительная информация

- **Связанные файлы:** `gtid.md` (GTID-механика и чек-лист failover), `lag_monitoring.md` (лаг и `Seconds_Behind_Source`), `semi-sync-replication.md` (полусинхронность), `delayed_replication.md` (промоушен отложенной реплики), `multi-source.md` (каналы), `topologies.md` (каскады), `parallel_replication_mts.md` (MTS), `consistency_checks.md` (проверка после failover), `relay_logs_crashsafe.md` (relay-log и crash-safety), `replication_sql_errors.md` (ошибки применения), `setup_guide.md` (базовая настройка), `setup.md` (учётная запись репликации и SSL), `management_debug.md`, `../troubleshooting-runbook.md`, `../orchestrator.md`, `../ProxySQL/proxysql_failover.md`, `../high_availability.md`, `../backup_and_recovery/pitr.md`
- **Ключевые переменные:** `read_only`, `super_read_only`, `gtid_mode`, `enforce_gtid_consistency`, `gtid_executed`, `gtid_purged`, `source_connection_auto_failover`, `source_retry_count`, `source_connect_retry`, `rpl_semi_sync_source_enabled`, `rpl_semi_sync_source_timeout`, `skip_replica_start`
- **Ключевые функции:** `WAIT_FOR_EXECUTED_GTID_SET()`, `GTID_SUBSET()`, `GTID_SUBTRACT()`, `SOURCE_POS_WAIT()`, `asynchronous_connection_failover_add_source()` / `_delete_source()` / `_add_managed()` / `_delete_managed()` / `_reset()`
- **P_S-таблицы:** `replication_connection_configuration`, `replication_connection_status`, `replication_applier_configuration` (`DESIRED_DELAY`), `replication_applier_status`, `replication_asynchronous_connection_failover`, `replication_asynchronous_connection_failover_managed`
- **Внешние ресурсы:**
  - [MySQL 8.4: Switching Sources and Replicas with Asynchronous Connection Failover](https://dev.mysql.com/doc/refman/8.4/en/replication-asynchronous-connection-failover.html)
  - [MySQL 8.4: Functions Used with Global Transaction Identifiers (GTIDs)](https://dev.mysql.com/doc/refman/8.4/en/gtid-functions.html)
  - [MySQL 8.4: Position-Based Synchronization Functions](https://dev.mysql.com/doc/refman/8.4/en/replication-functions-synchronization.html)
  - [MySQL 8.4: SHOW BINARY LOG STATUS Statement](https://dev.mysql.com/doc/refman/8.4/en/show-binary-log-status.html)
  - [MySQL 8.4: RESET REPLICA Statement](https://dev.mysql.com/doc/refman/8.4/en/reset-replica.html)
  - [MySQL 8.4: RESET BINARY LOGS AND GTIDS Statement](https://dev.mysql.com/doc/refman/8.4/en/reset-binary-logs-and-gtids.html)
  - [MySQL 8.4: Semisynchronous Replication](https://dev.mysql.com/doc/refman/8.4/en/replication-semisync.html)
  - [MySQL 8.4: Using GTIDs for Failover and Scaleout](https://dev.mysql.com/doc/refman/8.4/en/replication-gtids-failover.html)
  - [Orchestrator (ProxySQL)](https://github.com/ProxySQL/orchestrator)
