# Мониторинг отставания репликации

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS

## Определения

**Отставание репликации (Replication Lag)** — временной разрыв между моментом фиксации транзакции на источнике (Master/Source) и моментом её применения на реплике (Slave/Replica).

**IO-лаг** — задержка между записью события в бинарный лог источника и записью его в Relay Log реплики I/O-потоком (receiver thread).

**SQL-лаг** — задержка между записью события в Relay Log и его применением SQL-потоком (applier) или воркерами MTS.

**Seconds_Behind_Source (SBM; до MySQL 8.0.22 — `Seconds_Behind_Master`)** — поле `SHOW REPLICA STATUS`: оценка разницы во времени между applier- и receiver-потоками реплики.

**Heartbeat-лаг** — лаг, измеренный по heartbeat-записи (`pt-heartbeat`): разница между меткой времени, записанной на источнике, и временем применения этой записи на реплике. Единственный метод, измеряющий суммарный IO+SQL лаг независимо от состояния потоков.

## Базовые концепции

### Как формируется лаг репликации

Репликация асинхронна по умолчанию. Полусинхронная репликация влияет на подтверждение записи на источнике (см. `semi-sync-replication.md`), но отставание на реплике по-прежнему может накапливаться.

Основные потоки, влияющие на лаг:
- **Binlog Dump** (источник): отдача событий по сети
- **I/O-поток / receiver (`Replica_IO_Running`)**: приём и сохранение событий в Relay Log
- **SQL-поток / applier, а в MTS — координатор + воркеры (`Replica_SQL_Running`)**: чтение Relay Log и применение транзакций

MTS влияет только на SQL-лаг; IO-лаг определяется сетью и приёмом. Если `Read_Source_Log_Pos` сильно отстаёт от текущей позиции в бинлоге источника — проблема в сети/I/O-потоке, а не в MTS.

### Как формируется Seconds_Behind_Source

`Seconds_Behind_Source` — разница во времени между applier- и receiver-потоками, рассчитываемая SQL-потоком по временным меткам событий в Relay Log. Ключевые семантики (MySQL 8.4 Reference Manual, `SHOW REPLICA STATUS`):

- **Полезен только в быстрых сетях.** При медленной сети applier часто догоняет медленно читающий receiver, и SBM показывает `0`, хотя receiver отстаёт от источника.
- **Часы.** Расчёт корректен, если разница часов реплики и источника постоянна с момента старта receiver-потока; любые корректировки (в том числе NTP) вносят clock skew и снижают надёжность показателя.
- **`NULL` (MySQL 8.4):** applier-поток не работает, либо applier потребил весь Relay Log и receiver-поток не работает. В более старых версиях: `NULL`, если любой из потоков не работает или не подключён к источнику.
- **`0` при работающем receiver и исчерпанном Relay Log** — штатное «догнал».
- **`0` при обрыве связи**, который receiver ещё не заметил (пока не истёк `replica_net_timeout`, дефолт 60с) — ложное «догнал».
- **Транзиентные значения:** когда applier догнал receiver, SBM=0; пока applier применяет только что полученное событие, SBM может показывать большое значение до завершения применения.
- **SBM показывает SQL-лаг, а не IO-лаг:** если receiver сильно отстаёт от источника, но applier догнал полученное, SBM будет мал при реальном отставании по позиции.

### Что влияет на накопление лага

| Фактор | Влияет | Пояснение |
| :--- | :--- | :--- |
| **Длительные транзакции на источнике** | ↑ SQL-лаг | Большие транзакции (LOAD DATA, массовые UPDATE/DELETE без батчинга) долго реплицируются и долго применяются на реплике |
| **Нагрузка на реплике (CPU/IOPS)** | ↑ SQL-лаг | На реплике часто меньше ресурсов, либо есть read-only нагрузка (отчёты), конкурирующая за IO |
| **Блокировки на реплике** | ↑ SQL-лаг | Длинные блокировки (бэкапы, аналитика, DDL) мешают применению транзакций SQL-потоком/воркерами |
| **Сеть** | ↑ IO-лаг | Большая задержка/пропускная способность между узлами |
| **Однопоточная репликация** | ↑ SQL-лаг | Без MTS реплика применяет строго последовательно — плохо при множестве конкурентных транзакций |
| **Параллелизм с зависимостями** | варьируется | MTS (`LOGICAL_CLOCK`) хорошо снижает лаг при независимых транзакциях; при сильных зависимостях выигрыш меньше |
| **Relay Log на медленном диске** | ↑ IO+SQL | Замедляет как приём, так и чтение координатором |
| **`replica_preserve_commit_order`** | влияет | Сохраняет порядок фиксации, но может немного увеличить лаг при конкуренции воркеров |
| **`binlog_transaction_compression`** | ↓ IO-лаг | Сжимает транзакции в бинлоге — экономит пропускную способность сети |

## Приусловия

- **Привилегии:** `REPLICATION CLIENT` — `SHOW REPLICA STATUS`; `SELECT` на `performance_schema` — P_S-таблицы репликации; `PROCESS` — `SHOW PROCESSLIST`. Для экспортёра Prometheus: `GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.*` (рекомендуется `MAX_USER_CONNECTIONS 3`, чтобы скробы не перегружали сервер).
- **NTP** на источнике и всех репликах (влияние на SBM — см. выше).
- **Performance Schema включён** (8.0+ по умолчанию): временные метки транзакций в P_S-таблицах репликации (`replication_connection_status`, `replication_applier_status_by_coordinator`, `replication_applier_status_by_worker`) **не собираются при выключенном P_S**.
- **Percona Toolkit** — для `pt-heartbeat` (установка из официальных репозиториев Percona: `percona-release enable pt release`, затем установка пакета `percona-toolkit`).
- **Версии:** P_S-таблицы репликации с метками времени — 5.7+; поле `Seconds_Behind_Source` переименовано из `Seconds_Behind_Master` в 8.0.22; имена полей `Master_*`/`Slave_*` в `SHOW REPLICA STATUS` переименованы в `Source_*`/`Replica_*` в 8.0.23.

## Практический блок

### 1. Быстрая проверка состояния репликации

```sql
SHOW REPLICA STATUS\G
-- multi-source: конкретный канал
SHOW REPLICA STATUS FOR CHANNEL 'channel_name'\G
```

Ключевые поля для оценки лага/состояния:

| Поле | Ожидание | Пояснение |
| :--- | :--- | :--- |
| `Replica_IO_Running` | `Yes` | Состояние приёма бинлога (`No`/`Connecting` — проблема подключения; смотреть `Last_IO_Error`) |
| `Replica_SQL_Running` | `Yes` | Состояние применения (`No` — смотреть `Last_SQL_Error`) |
| `Last_IO_Errno` / `Last_SQL_Errno` | `0` | Коды последних ошибок потоков; первым делом при `Running=No` |
| `Seconds_Behind_Source` | < порога | Оценка SQL-лага; интерпретация — в разделе 2 |
| `Replica_SQL_Running_State` | `Replica has read all relay log; waiting for more updates` | Applier догнал и ждёт событий; в MTS воркеры в `SHOW PROCESSLIST` в состоянии `Waiting for an event from Coordinator` |
| `Source_Log_File` / `Read_Source_Log_Pos` (до 8.0.23 — `Master_Log_File`/`Read_Master_Log_Pos`) | растут при записи на источнике | До какой позиции I/O-поток дошёл |
| `Relay_Source_Log_File` / `Exec_Source_Log_Pos` (до 8.0.23 — `Relay_Master_Log_File`/`Exec_Master_Log_Pos`) | близки к `Source_Log_File`/`Read_Source_Log_Pos` | До какой позиции SQL-поток применил |
| `Relay_Log_Space` | < `relay_log_space_limit` с запасом | Суммарный размер всех Relay Log файлов (следить за свободным местом) |
| `Retrieved_Gtid_Set` / `Executed_Gtid_Set` (при GTID) | второй ⊇ первый без «лишних» | Что получено vs что применено; сравнение наборов — в `gtid_practical.md` |
| `Auto_Position` | `1` (при GTID) | Используется ли автоматическая позиция |

### 2. Оценка лага по SBM

SBM — быстрый, но косвенный индикатор (семантика — в разделе «Как формируется Seconds_Behind_Source»). Правила применения:

- **Доверять как оценке SQL-лага** только в быстрых сетях и при синхронизированных часах.
- **`0` не означает «реплика в синхронии»**, пока не подтверждено: receiver не отстаёт от источника (сравните позиции/GTID — раздел 7) и сеть не в состоянии «обрыв ещё не замечен».
- **`NULL` — потоки не работают** (в 8.4: applier не работает, либо relay-log исчерпан и receiver не работает) — это состояние требует диагностики, а не интерпретации лага.
- **При сомнениях в SBM** — измеряйте лаг через P_S-метки (раздел 3) или `pt-heartbeat` (раздел 4).

### 3. Точный лаг через Performance Schema

Временные метки коммита и применения доступны в P_S и не зависят от корректности расчёта SBM:

```sql
-- Лаг применения по каждому воркеру (и для однопоточной реплики):
-- END_APPLY − ORIGINAL_COMMIT = сколько секунд транзакция «летела» от
-- фиксации на источнике до применения на реплике
SELECT CHANNEL_NAME,
       WORKER_ID,
       LAST_APPLIED_TRANSACTION,
       TIMESTAMPDIFF(MICROSECOND,
                     LAST_APPLIED_TRANSACTION_ORIGINAL_COMMIT_TIMESTAMP,
                     LAST_APPLIED_TRANSACTION_END_APPLY_TIMESTAMP) / 1000000 AS lag_seconds
FROM performance_schema.replication_applier_status_by_worker
WHERE LAST_APPLIED_TRANSACTION IS NOT NULL;

-- Прогресс координатора MTS: какая транзакция обрабатывается прямо сейчас
SELECT CHANNEL_NAME,
       SERVICE_STATE,
       LAST_PROCESSED_TRANSACTION,
       PROCESSING_TRANSACTION,
       LAST_ERROR_NUMBER,
       LAST_ERROR_MESSAGE
FROM performance_schema.replication_applier_status_by_coordinator;

-- Состояние I/O-потока: полученные транзакции и heartbeat-сигналы источника
SELECT CHANNEL_NAME,
       SERVICE_STATE,
       THREAD_ID,
       RECEIVED_TRANSACTION_SET,
       LAST_HEARTBEAT_TIMESTAMP,
       COUNT_RECEIVED_HEARTBEATS,
       COUNT_RECEIVED_TRANSACTIONS
FROM performance_schema.replication_connection_status\G

-- Общее состояние применения: остаток отложенной репликации и число ретраев
SELECT CHANNEL_NAME,
       SERVICE_STATE,
       REMAINING_DELAY,
       COUNT_TRANSACTIONS_RETRIES
FROM performance_schema.replication_applier_status;
```

Пояснения:
- `LAST_APPLIED_TRANSACTION_IMMEDIATE_COMMIT_TIMESTAMP` — метка фиксации на непосредственном источнике; разница с `..._ORIGINAL_COMMIT_TIMESTAMP` показывает задержку предыдущего звена каскада.
- `COUNT_TRANSACTIONS_RETRIES` растёт при неудачных попытках применения (максимум ретраев — `replica_transaction_retries`); рост — сигнал деградации применения.
- `Replica_IO_State`/`Replica_SQL_Running_State` в P_S не сохраняются: состояние потока берётся из `information_schema.PROCESSLIST` по `THREAD_ID` из P_S-таблицы.
- В MySQL 8.4 данные показываются и для однопоточной реплики (одна строка — единственный applier-поток); при MTS — по строке на каждый воркер.

### 4. pt-heartbeat — эталонное измерение лага

`pt-heartbeat` (Percona Toolkit) записывает heartbeat-запись на источнике и измеряет, когда она применилась на реплике. Измеряет **суммарный IO+SQL лаг**, работает при остановленных потоках (лаг растёт неограниченно — виден истинный отрыв) и в каскадных топологиях.

```bash
# 1. На источнике: создать таблицу и запустить daemon обновления
#    (структура таблицы определяется инструментом через --create-table;
#     учётные данные можно хранить в ~/.my.cnf вместо DSN)
pt-heartbeat --create-table --database percona --table heartbeat \
  --update --daemonize --interval 1 \
  h=source_host,u=monitor_user,p=password

# 2. На реплике: непрерывный мониторинг (проверка каждые --interval + --skew секунд;
#    --skew по умолчанию 0.5 — сдвиг, чтобы читать уже обновлённую запись)
pt-heartbeat --monitor --interval 1 --database percona --table heartbeat \
  h=replica_host,u=monitor_user,p=password

# 3. Однократная проверка — для скриптов и алертов
pt-heartbeat --check --database percona --table heartbeat \
  h=replica_host,u=monitor_user,p=password
# → лаг в секундах, например "0s" при синхронности

# 4. Каскад: на реплике 2-го уровня — читать запись конкретного источника
#    (записи идентифицируются по @@server_id источника, поэтому одна
#     таблица обслуживает несколько источников/иерархий)
pt-heartbeat --check --source-server-id 1 --database percona --table heartbeat \
  h=replica2_host,u=monitor_user,p=password

# 5. Если у пользователя нет INSERT — обновление без вставки строки
pt-heartbeat --update --no-insert-heartbeat-row ... h=source_host

# 6. Остановить daemon
pt-heartbeat --stop --database percona --table heartbeat h=source_host
```

Интерпретация и эксплуатация:
- **Отрицательный лаг** — рассинхрон часов источника и реплики (NTP).
- **На отложенной реплике** покажет `SOURCE_DELAY` + реальный лаг (см. `delayed_replication.md`).
- **Очистка:** `pt-heartbeat --stop`, затем `DROP TABLE percona.heartbeat;` на источнике — удаление реплицируется на реплики автоматически.
- **`mysqld_exporter --collect.heartbeat`** собирает лаг, измеренный `pt-heartbeat` (pt-heartbeat — reference-реализация heartbeat для экспортёра) — см. раздел 8.

### 5. Лаг в каскадной топологии

`Seconds_Behind_Source` показывает лаг только относительно **непосредственного** источника, а не корневого. Суммарный лаг каскада — сумма лагов звеньев. Для точного лага до корневого источника:
- `pt-heartbeat --check --source-server-id <id_корневого_источника>` (раздел 4);
- либо P_S: `LAST_APPLIED_TRANSACTION_ORIGINAL_COMMIT_TIMESTAMP` (корневой коммит) против `LAST_APPLIED_TRANSACTION_END_APPLY_TIMESTAMP` — разница включает все звенья.

### 6. Диагностика причин накопления лага

```sql
-- Занятость воркеров MTS (когда включён)
SELECT CHANNEL_NAME, WORKER_ID, SERVICE_STATE, LAST_APPLIED_TRANSACTION
FROM performance_schema.replication_applier_status_by_worker
WHERE CHANNEL_NAME = 'main'
ORDER BY WORKER_ID;

-- Активные транзакции/блокировки на реплике, мешающие применению
SHOW PROCESSLIST;
SELECT * FROM information_schema.INNODB_TRX ORDER BY trx_started ASC;
-- MySQL 8.0+: блокировки и ожидания (INNODB_LOCKS/INNODB_LOCK_WAITS удалены в 8.0;
-- на 5.7 — information_schema.INNODB_LOCKS / INNODB_LOCK_WAITS)
SELECT * FROM performance_schema.data_locks;
SELECT * FROM performance_schema.data_lock_waits;

-- Relay Log пространство
SHOW VARIABLES LIKE 'relay_log_space_limit';
SHOW STATUS LIKE 'Relay_Log_Space';
```

Дополнительно: длинные транзакции на источнике (`information_schema.INNODB_TRX` на источнике), DDL на источнике (применение ждёт завершения DDL целиком), конкуренция read-only нагрузки за IO на реплике.

### 7. Сравнение позиций и GTID (когда SBM недостоверен)

```sql
SHOW REPLICA STATUS\G
-- Сравнить:
--   Source_Log_File + Read_Source_Log_Pos  (до какой позиции I/O-поток дошёл)
--   Relay_Source_Log_File + Exec_Source_Log_Pos (до какой позиции SQL-поток применил)
```

Важно: отставание по позициям — это объём событий, а не время; для перевода в секунды нужна интенсивность записи на источнике. При GTID сравнивайте наборы: реплика догнала источника, если её `Executed_Gtid_Set` содержит все GTID источника (`GTID_SUBSET`) и не содержит «лишних» локальных транзакций (`GTID_SUBTRACT`) — запросы и семантика в `gtid_practical.md`.

### 8. Экспорт метрик (Prometheus)

```bash
# Права для экспортёра (один раз на каждом мониторимом сервере)
mysql -e "CREATE USER 'exporter'@'localhost' IDENTIFIED BY 'password' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'localhost';"

# Проверить фактическое имя метрики лага на своём инстансе
curl -s http://localhost:9104/metrics | grep -i behind
# → mysql_slave_status_seconds_behind_source {…} 0
```

- Коллектор `slave_status` у `mysqld_exporter` пробует `SHOW ALL SLAVES STATUS`, затем `SHOW SLAVE STATUS`, затем `SHOW REPLICA STATUS`; префикс метрик остаётся `mysql_slave_status_*` независимо от версии. Суффикс зависит от версии сервера: <8.0.22 → `..._seconds_behind_master`, ≥8.0.22 → `..._seconds_behind_source` (полный разбор имён — в `../monitoring.md`, раздел «Рекомендуемые правила алертинга»).
- `mysqld_exporter --collect.heartbeat` — лаг, измеренный `pt-heartbeat`, вместо/в дополнение к SBM.
- Базовый порог вмешательства в KB — 60с (см. `../monitoring.md`); конкретный порог определяется SLA/RPO:

```yaml
- alert: MySQLReplicationLag
  expr: mysql_slave_status_seconds_behind_source > 60
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "MySQL: лаг репликации > 60с ({{ $value }}s)"
```

- Состояние потоков алертится отдельно от лага: метрики `*_io_running`/`*_sql_running` (имена зависят от версии колонок — проверьте на инстансе: `curl -s http://localhost:9104/metrics | grep -i running`).

### 9. Практические приёмы снижения лага

| Приём | Когда применять | Комментарий |
| :--- | :--- | :--- |
| **Включить MTS** | SQL-лаг растёт при наличии свободных CPU/IO | См. `parallel_replication_mts.md`. Ключевые: `replica_parallel_workers`, `replica_parallel_type=LOGICAL_CLOCK` |
| **Оптимизация на реплике** | Много конкуренции за ресурсы | Разнести IO (отдельный диск под relay/data), ограничить тяжёлые read-only запросы, следить за буферами |
| **Снизить длительность транзакций на источнике** | Много «тяжёлых» массовых операций | Батчинг (обновлять порциями), избегать длинных транзакций, по возможности разбивать DML |
| **`binlog_transaction_compression=ON`** | IO-лаг из-за пропускной способности сети | Уменьшает объём транзакций в бинлоге (экономит сеть, небольшой CPU-оверхед) |
| **`replica_preserve_commit_order=ON`** | Нужно сохранить порядок фиксации (критично для некоторых приложений) | Меньше параллельности, но безопаснее по зависимостям; может незначительно увеличить лаг |
| **Мониторинг Relay Log места** | Риск переполнения при большом лаге | При достижении `relay_log_space_limit` I/O-поток остановится (опасно). Лимит не абсолютен — см. Граничные случаи |
| **Сеть/коннект** | IO-лаг стабильно высокий | Проверка RTT, MTU, сжатие/SSL влияние (SSL добавляет оверхед) |

### 10. Валидация мониторинга

```sql
-- Тестовая среда: имитировать SQL-лаг (НЕ в проде!)
STOP REPLICA SQL_THREAD;
-- Ожидание: SBM растёт / становится NULL (8.4: applier не работает);
-- pt-heartbeat --check показывает растущий лаг; алерт срабатывает
START REPLICA SQL_THREAD;
```

```bash
# Проверить, что экспортёр отдаёт метрику лага
curl -s http://localhost:9104/metrics | grep -i behind
# → mysql_slave_status_seconds_behind_source {…} <число>

# Однократный замер heartbeat-лага для сравнения с SBM
pt-heartbeat --check --database percona --table heartbeat h=replica_host,u=monitor_user
```

### 11. Минимальный мониторинг-чеклист (prod)

- [ ] `Replica_IO_Running == Yes` и `Replica_SQL_Running == Yes` (по всем каналам в multi-source)
- [ ] `Last_IO_Errno == 0` и `Last_SQL_Errno == 0`
- [ ] Лаг < порога алерта, подтверждённый не только SBM: P_S-метки (раздел 3) или `pt-heartbeat --check` (раздел 4) в пределах SLA
- [ ] `Relay_Log_Space` < `relay_log_space_limit` с запасом (лимит не абсолютен — см. Граничные случаи)
- [ ] `COUNT_TRANSACTIONS_RETRIES` не растёт (P_S `replication_applier_status`)
- [ ] Свободное место на разделе с Relay Log достаточно

### 12. Типичные сценарии из практики

**Сценарий 1: SBM растёт, но IO-поток догнал источник**
- Причина: SQL-поток не успевает применять (ресурсы/блокировки/однопоток). Смотреть `Exec_Source_Log_Pos` vs `Read_Source_Log_Pos` — они близки, но SBM растёт.
- Действие: включить MTS, снять блокировки, уменьшить конкуренцию на реплике.

**Сценарий 2: `Relay_Log_Space` быстро растёт, SBM большой**
- Причина: сильное отставание, Relay Log копит события.
- Действие: срочно разбираться с применением (MTS/ресурсы). Не трогать `relay_log_purge` вручную без понимания — он управляется репликацией.

**Сценарий 3: После перезапуска реплики SBM какое-то время NULL/нестабилен**
- Нормально. После старта потоков координатор/SQL-поток «догоняет» и SBM пересчитывается.

**Сценарий 4: Источник недоступен, а SBM показывает 0**
- Причина: applier догнал полученное в Relay Log, receiver ещё не заметил обрыв (или обрыв наступил после исчерпания relay-log — тогда SBM в 8.4 станет `NULL`).
- Действие: не интерпретировать `0` как здоровье — проверять `Replica_IO_Running`, `Last_IO_Error`, позиции/GTID (раздел 7).

**Сценарий 5: Отложенная репликация — SBM растёт до ≈`SQL_Delay`**
- Штатное поведение: applier ожидает `SOURCE_DELAY`. `SQL_Remaining_Delay` показывает остаток текущего цикла ожидания (`NULL` вне ожидания), `Replica_SQL_Running_State` = `Waiting until SOURCE_DELAY seconds after master executed event`. Детали — в `delayed_replication.md`.

## Граничные случаи

- **`relay_log_space_limit` не абсолютен:** при достижении лимита receiver останавливает чтение бинлога, пока applier не догонит и не удалит неиспользуемые Relay Log; но если applier не может удалить логи (ему нужны события), receiver временно игнорирует лимит — объём Relay Log может превысить заданный.
- **Источник недоступен / обрыв сети:** SBM может показывать `0`, пока Relay Log не исчерпан (ложное «догнал»); обрыв receiver замечает через `replica_net_timeout` (дефолт 60с). См. сценарий 4.
- **Отложенная репликация:** `SQL_Remaining_Delay` (`NULL` вне ожидания); heartbeat-лаг = `SOURCE_DELAY` + реальный лаг.
- **Multi-source:** все P_S-таблицы и `SHOW REPLICA STATUS` — по каналам (`CHANNEL_NAME`); для конкретного канала — `SHOW REPLICA STATUS FOR CHANNEL '...'`.
- **`GTID_ONLY=1`:** `Read_Source_Log_Pos` = 0 после старта сервера до первого контакта с источником — позиционные проверки лага в этот период некорректны.
- **Рассинхрон часов:** pt-heartbeat показывает отрицательный лаг; SBM недостоверен после корректировок NTP.
- **Очень большие транзакции (>1 ГБ) и DDL:** SBM растёт во время применения и мгновенно падает до `0` после `COMMIT`/завершения DDL — не путать с «внезапным восстановлением»; смотрите P_S-метки (раздел 3).
- **Performance Schema выключен:** временные метки транзакций не собираются — раздел 3 недоступен, остаются SBM и pt-heartbeat.

## Лучшие практика

1. **Не полагаться только на SBM:** базовый алерт — состояние потоков + лаг; для критичных систем — `pt-heartbeat` (раздел 4) и/или `--collect.heartbeat` в экспортёре.
2. **Порог лага — от SLA/RPO;** базовый порог вмешательства в KB — 60с (см. `../monitoring.md`).
3. **NTP на всех узлах** репликационной цепочки.
4. **Раздельные реплики** для аналитики/бэкапов — чтобы read-only нагрузка не конкурировала с applier за IO.
5. **Мониторить место** под Relay Log и соотношение `Relay_Log_Space`/`relay_log_space_limit`.
6. **Следить за ретраями** применения (`COUNT_TRANSACTIONS_RETRIES`) — рост означает деградацию применения.
7. **Тестировать failover** только на репликах с подтверждённым нулевым лагом (проверка догоняния — в `failover_switchover.md`).

## Дополнительная информация

- **Связанные файлы:** `management_debug.md`, `parallel_replication_mts.md`, `relay_logs_crashsafe.md`, `semi-sync-replication.md`, `failover_switchover.md`, `gtid.md`, `gtid_practical.md`, `delayed_replication.md`, `topologies.md`, `consistency_checks.md`, `../monitoring.md`
- **Ключевые переменные:** `replica_net_timeout`, `relay_log_space_limit`, `relay_log_purge`, `replica_parallel_workers`, `replica_preserve_commit_order`, `sync_relay_log`, `replica_transaction_retries`, `SOURCE_DELAY`/`SQL_Delay`
- **Performance Schema:** `replication_applier_status`, `replication_applier_status_by_coordinator`, `replication_applier_status_by_worker`, `replication_connection_status`, `replication_connection_configuration`
- **Внешние ссылки:** [SHOW REPLICA STATUS (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/show-replica-status.html), [Performance Schema Replication Tables (MySQL 8.4)](https://dev.mysql.com/doc/refman/8.4/en/performance-schema-replication-tables.html), [pt-heartbeat (Percona Toolkit)](https://docs.percona.com/percona-toolkit/pt-heartbeat.html), [mysqld_exporter (Prometheus)](https://github.com/prometheus/mysqld_exporter)
