# Отложенная репликация (Delayed Replication)

**Актуально для:** MySQL 8.0.23+ / 8.4 LTS (синтаксис `SOURCE_DELAY`; в MySQL 5.6–8.0.22 — устаревший `CHANGE MASTER TO MASTER_DELAY`). Отложенная репликация поддерживается и в MySQL 9.x (раздел 19.4.11 Reference Manual); замечания по семантике `Seconds_Behind_Source` в 9.7 — в разделе «Граничные случаи».

## Определения

**Отложенная репликация (Delayed Replication)** — режим, при котором реплика намеренно применяет транзакции не раньше чем через N секунд после их фиксации на непосредственном источнике (immediate source). Задержка задаётся параметром `SOURCE_DELAY` (по умолчанию 0 — задержки нет).

**`SQL_Delay`** — поле `SHOW REPLICA STATUS`: неотрицательное целое, сколько секунд реплика обязана отставать от источника (то, что задано в `SOURCE_DELAY`).

**`SQL_Remaining_Delay`** — поле `SHOW REPLICA STATUS`: сколько секунд задержки осталось до применения текущего события, пока `Replica_SQL_Running_State` = `Waiting until SOURCE_DELAY seconds after master executed event`; во всех остальных случаях `NULL`.

**`DESIRED_DELAY` / `REMAINING_DELAY`** — столбцы таблиц Performance Schema `replication_applier_configuration` и `replication_applier_status` — те же значения задержки в машинночитаемом виде (для мониторинга).

**`immediate_commit_timestamp` / `original_commit_timestamp`** — две временные метки бинарного лога, по которым в MySQL 8.4 измеряется задержка (см. «Replication Delay Timestamps» в документации).

## Теоретический блок

### Зачем нужна

- **Защита от логических ошибок на источнике**: случайное `DROP TABLE`, `DELETE`/`UPDATE` без WHERE, ошибочная миграция. Если ошибка обнаружена в течение окна задержки, реплика её ещё не применила — можно остановить применение и использовать ноду как точку восстановления.
- **Снимок состояния «как было N минут назад»** без восстановления из бэкапа (аналитика, аудит).
- **Буфер для DR**: отложенная реплика во вторичном ЦО даёт окно реакции перед тем, как ошибка реплицируется географически.

**Не замена бэкапу**: защита работает только в пределах окна задержки; ошибка, обнаруженная позже, уже применена.

### Как работает

- **Задержка — на уровне транзакции, а не события** (в MySQL 8.4; в версиях до 8.0.23 задержка накладывалась на события). Фактическая пауза вносится только на `gtid_log_event` или `anonymous_gtid_log_event`; остальные события транзакции следуют за ними без ожидания.
- **Точка отсчёта — время фиксации транзакции на непосредственном источнике**, извлекаемое из метки времени в событии бинарного лога. Отсюда: на цепочке реплик задержка считается от коммита на immediate source, а метки времени событий сохраняются при прохождении через промежуточные реплики.
- **I/O-поток (receiver) работает без задержки**: он читает бинарный лог источника и пишет в Relay Log в обычном режиме. Пауза — только в SQL-потоке (applier; при MTS — на координаторе, который последовательно читает транзакции и назначает их воркерам). Поэтому Relay Log на отложенной реплике копит события за весь период задержки.
- **Исключения**: для format description events и log file rotation events задержки нет — они влияют только на внутреннее состояние SQL-потока.
- **`Seconds_Behind_Source` на отложенной реплике** ≈ `SQL_Delay` + реальный лаг применения, когда I/O-поток догнал источник. Метрика основана на временных метках событий, поэтому при рассинхронизации часов (NTP) её точность падает.
- **`START REPLICA` / `STOP REPLICA` действуют немедленно и игнорируют любую задержку** — остановка SQL-потока посреди цикла ожидания выполняется мгновенно, что и делает приём пригодным для экстренного «замораживания».
- **`RESET REPLICA` сбрасывает задержку в 0** (и требует остановленных потоков + привилегии `RELOAD`).
- **Персистентность**: `SOURCE_DELAY` — часть конфигурации канала, хранится в crash-safe репозиториях репликации (`mysql.slave_master_info`) и переживает перезапуск `mysqld`.

### Ограничения

- **Окно защиты = `SOURCE_DELAY`**: задержка должна превышать типичное время обнаружения ошибки человеком/мониторингом.
- **Дисковое пространство**: Relay Log растёт на объём записи источника за период задержки. Оценка: `binlog_МБ/час × SOURCE_DELAY / 3600`. При исчерпании `relay_log_space_limit` I/O-поток останавливается — см. `relay_logs_crashsafe.md`.
- **Расхождение часов**: поскольку отсчёт ведётся от метки времени в событии (часы источника), разница часов серверов искажает фактическую задержку — синхронизируйте узлы через NTP.
- **Не защищает от ошибок, обнаруженных позже окна**, и не защищает от ошибок, сделанных на самой реплике.
- **Failover с отложенной реплики теряет данные за окно задержки**: кандидат на промоушен отстаёт от источника на `SOURCE_DELAY` + лаг.

## Практический блок

### Приусловия

| Что нужно | Значение |
| :--- | :--- |
| Работающая репликация | см. `setup_guide.md` (отложенная репликация — надстройка над обычной) |
| Привилегия на конфигурацию | `REPLICATION_SLAVE_ADMIN` (или устаревшая `SUPER`) для `CHANGE REPLICATION SOURCE TO`, `START REPLICA`, `STOP REPLICA` |
| Привилегия для `RESET REPLICA` | `RELOAD` (потоки должны быть остановлены) |
| Учётка репликации на источнике | `REPLICATION_APPLIER` + привилегии на реплицируемые объекты |
| Включённый binlog на источнике | условие работы репликации в принципе |
| NTP на всех узлах | точность фактической задержки |

### Настройка задержки

#### Новая реплика, File:Pos

```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='source_host',
  SOURCE_PORT=3306,
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='repl_pass',
  SOURCE_LOG_FILE='binlog.000123',
  SOURCE_LOG_POS=456789,
  SOURCE_DELAY=3600;  -- задержка 1 час (в секундах)
START REPLICA;
```

#### Новая реплика, GTID с AUTO_POSITION

```sql
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='source_host',
  SOURCE_PORT=3306,
  SOURCE_USER='repl_user',
  SOURCE_PASSWORD='repl_pass',
  SOURCE_AUTO_POSITION=1,
  SOURCE_DELAY=1800;  -- 30 минут
START REPLICA;
```

#### Изменение задержки на существующей реплике

Документированный безопасный паттерн для `CHANGE REPLICATION SOURCE TO` — остановить потоки, изменить, запустить (опции, не указанные в операторе, сохраняют свои значения):

```sql
STOP REPLICA;
CHANGE REPLICATION SOURCE TO SOURCE_DELAY=7200;  -- 2 часа
START REPLICA;
```

#### Multi-source: задержка на конкретном канале

```sql
STOP REPLICA FOR CHANNEL 'marketing_db';
CHANGE REPLICATION SOURCE TO SOURCE_DELAY=3600 FOR CHANNEL 'marketing_db';
START REPLICA FOR CHANNEL 'marketing_db';
```

#### Устаревший синтаксис (MySQL 5.6–8.0.22)

```sql
CHANGE MASTER TO MASTER_DELAY=1800;  -- до 8.0.23; в 8.0.23+ оператор deprecated
```

#### Снять задержку

```sql
STOP REPLICA;
CHANGE REPLICATION SOURCE TO SOURCE_DELAY=0;
START REPLICA;
```

### Проверка состояния отложенной реплики

```sql
SHOW REPLICA STATUS\G
```

Ключевые поля:
- `SQL_Delay` — текущая задержка в секундах (0 = отложенная репликация не настроена)
- `SQL_Remaining_Delay` — секунды до применения текущего события; `NULL`, если ожидание не активно
- `Replica_SQL_Running_State` — состояние SQL-потока; при ожидании задержки равно строке `Waiting until SOURCE_DELAY seconds after master executed event` (то же значение, что и `State` потока в `SHOW PROCESSLIST`)
- `Seconds_Behind_Source` — ≈ `SQL_Delay` + реальный лаг применения

Пример вывода:

```sql
SQL_Delay: 3600
SQL_Remaining_Delay: 1234
Replica_SQL_Running_State: Waiting until SOURCE_DELAY seconds after master executed event
Seconds_Behind_Source: 3612
```

→ реплика применяет события с отставанием ~1 час, до применения ближайшего события осталось ~20 минут, суммарное отставание ~1 час 12 секунд.

Машинночитаемый эквивалент (для Prometheus/Zabbix):

```sql
SELECT CHANNEL_NAME, DESIRED_DELAY
FROM performance_schema.replication_applier_configuration;

SELECT CHANNEL_NAME, REMAINING_DELAY, SERVICE_STATE
FROM performance_schema.replication_applier_status;
```

### Мониторинг

- **Порог алерта на `Seconds_Behind_Source` должен учитывать настроенную задержку**: для отложенной реплики «норма» — это `≈ SQL_Delay`, а не 0. Алерт «S_B_S > 60c» на реплике с `SOURCE_DELAY=3600` будет ложным постоянно.
- **Рост `Seconds_Behind_Source` значительно выше `SQL_Delay`** — признак реального лага применения (ресурсы, блокировки, однопоток); диагностика — в `lag_monitoring.md`.
- **`pt-heartbeat`** измеряет лаг применения независимо от `Seconds_Behind_Source`; на отложенной реплике он покажет `SOURCE_DELAY` + реальный лаг — см. `lag_monitoring.md`.
- **`Relay_Log_Space` vs `relay_log_space_limit`** — контролируйте с учётом задержки (Relay Log копит события за весь период `SOURCE_DELAY`); см. `relay_logs_crashsafe.md`.

### Сценарий: откат ошибочного изменения через отложенную реплику

Исходные данные: на источнике в 14:00 выполнен ошибочный `DELETE FROM critical_table WHERE ...`; `SOURCE_DELAY=3600` (1 час); ошибка замечена в 14:05.

#### Шаг 1. Немедленно остановить применение

```sql
-- На отложенной реплике
STOP REPLICA;  -- действует немедленно, игнорируя SOURCE_DELAY
```

#### Шаг 2. Найти GTID проблемной транзакции на источнике

```bash
# На источнике: найти транзакцию по времени/таблице
mysqlbinlog --base64-output=DECODE-ROWS -v \
  /var/lib/mysql/binlog.000123 | grep -B2 -A20 'critical_table'
# → SET @@SESSION.GTID_NEXT= '3E11FA47-71CA-11E1-9E33-C80AA9429562:2345'
```

#### Шаг 3. Проверить, применила ли реплика проблемную транзакцию

```sql
SHOW REPLICA STATUS\G
-- Retrieved_Gtid_Set:  ... :2340-2360   (что получено в Relay Log)
-- Executed_Gtid_Set:   ... :2340-2344   (что применено)
```

Если GTID проблемной транзакции (`:2345`) **есть в `Retrieved_Gtid_Set`, но отсутствует в `Executed_Gtid_Set`** — транзакция получена, но ещё не применена: реплика находится в безопасном состоянии. Это точная проверка; `SQL_Remaining_Delay` такого ответа не даёт — он показывает лишь остаток текущего цикла ожидания.

#### Шаг 4. Догнать реплику до безопасной точки (опционально, для точности)

Если нужно применить всё до problematic-транзакции включительно-без-неё:

```sql
START REPLICA SQL_THREAD UNTIL SQL_BEFORE_GTIDS = '3E11FA47-71CA-11E1-9E33-C80AA9429562:2345';
```

→ SQL-поток применит транзакции до указанной и остановится перед ней. Условие `UNTIL`:
- отображается в `SHOW REPLICA STATUS` (`Until_Condition`, `Until_Log_File`/`Until_Log_Pos` для file:pos-варианта);
- действует, пока потоки работают, и снимается при их остановке;
- работает только с `SQL_THREAD` (при `IO_THREAD` alone условие игнорируется);
- file:pos-вариант: `UNTIL SOURCE_LOG_FILE='binlog.000123', SOURCE_LOG_POS=456789` (8.0.23+; до того — `MASTER_LOG_FILE`/`MASTER_LOG_POS`);
- `SQL_AFTER_GTIDS` несовместим с многопоточным применением (MTS): выдаётся предупреждение и реплика переключается в single-threaded режим; для MTS используйте `UNTIL SQL_AFTER_MTS_GAPS`;
- для старта с `UNTIL` после перезапуска `mysqld` предотвращайте автозапуск SQL-потока (`skip_slave_start`, 8.0.24+).

Применение «догона» быстрое: задержка отсчитывается от времени коммита, а для исторических транзакций условие «прошло N секунд с коммита» уже выполнено.

#### Шаг 5. Промоутить реплику в источник

```sql
STOP REPLICA;
SET GLOBAL super_read_only = OFF;
SET GLOBAL read_only = OFF;
```

**Не выполняйте `RESET REPLICA` до извлечения данных**: оператор удаляет все relay-log файлы (даже неприменённые) и сбрасывает `SOURCE_DELAY` в 0, требует `RELOAD` и остановленных потоков. Он нужен только при последующей переконфигурации ноды.

Остальные реплики переключите на новый источник по стандартному сценарию — см. `failover_switchover.md`.

#### Шаг 6. Если ошибочная транзакция уже применена

Приём с отложенной репликой не работает — окно задержки истекло. Восстановление: бэкап + point-in-time recovery по бинлогам — см. `../backup_and_recovery/pitr.md`.

### Граничные случаи

- **MTS (`replica_parallel_workers > 0`)**: отложенное применение работает — задержка вносится на `gtid_log_event`, который обрабатывает coordinator.
- **MySQL 9.x**: отложенная репликация поддерживается (раздел 19.4.11 Reference Manual 9.7). Начиная с MySQL 9.5 в документации описан дополнительный метод измерения лага на основе timestamp'ов событий; в MySQL 9.7 изменена семантика `NULL` для `Seconds_Behind_Source` (поле `NULL`, если applier не работает либо relay log исчерпан и receiver не работает; `0`, если receiver работает, а relay log исчерпан). Для 9.x сверяйтесь с документацией целевой версии.
- **Рестарт `mysqld`**: задержка сохраняется (crash-safe репозиторий канала); после старта потоков цикл ожидания возобновляется.

## Диагностика и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `SQL_Delay: 0` после настройки | Задержка задана без остановки потоков или на другом канале | `STOP REPLICA [FOR CHANNEL ...]` → `CHANGE REPLICATION SOURCE TO SOURCE_DELAY=N` → `START REPLICA`; проверьте канал через `FOR CHANNEL` |
| `SQL_Remaining_Delay` всегда `NULL` | Задержка не активна: `SQL_Delay=0`, SQL-поток остановлен, либо транзакций нет и реплика idle | Проверьте `SQL_Delay` и `Replica_SQL_Running`; `NULL` в idle — штатное поведение |
| `Seconds_Behind_Source` растёт бесконечно | Реальный лаг применения сверх задержки; или I/O-поток остановлен | Сравните `S_B_S` с `SQL_Delay`; проверьте `Replica_IO_Running`, позиции/GTID (`lag_monitoring.md`) |
| `Replica_SQL_Running_State` не содержит «Waiting until SOURCE_DELAY…» | Задержка не настроена или поток не в цикле ожидания | Проверьте `SQL_Delay`; при `SOURCE_DELAY>0` и активном потоке состояние должно появляться при ожидании |
| Relay Log занял всё место | `SOURCE_DELAY` велик при высокой записи на источник | Оценка `binlog_МБ/час × SOURCE_DELAY / 3600`; резерв под relay log или разумный `relay_log_space_limit` (`relay_logs_crashsafe.md`) |
| `START REPLICA ... UNTIL` не останавливается | Указан только `IO_THREAD` (условие `UNTIL` игнорируется) | Используйте `SQL_THREAD` (или запуск обоих потоков) |
| `UNTIL SQL_AFTER_GTIDS` + MTS | Не совместимы: предупреждение и переключение в single-thread | `UNTIL SQL_BEFORE_GTIDS` или `UNTIL SQL_AFTER_MTS_GAPS` |
| Промоушен «вслепую» без проверки GTID | Ошибочная транзакция могла уже примениться | Всегда сверяйте `Retrieved_Gtid_Set` / `Executed_Gtid_Set` (Шаг 3) до промоушена |

## Лучшие практики

- **Окно > время обнаружения**: типичные значения `SOURCE_DELAY` — 300–3600 с; менее 5 минут редко полезно, более часа требует серьёзного контроля за диском.
- **GTID обязателен** для точного отката: проверка применения и `UNTIL SQL_BEFORE_GTIDS` работают только с GTID.
- **NTP на всех узлах** — иначе фактическая задержка искажается.
- **Документируйте наличие задержки** в runbook'е failover: кандидат с `SOURCE_DELAY` теряет данные за окно задержки; перед промоушеном в плановом switchover снимите задержку (`SOURCE_DELAY=0`) и дождитесь полного догона.
- **Алертинг с учётом задержки**: базовый порог = `SQL_Delay` + допуск; отдельный алерт на `Relay_Log_Space`.
- **Не используйте `sql_replica_skip_counter`** как инструмент «пропустить задержку» — механика пропуска транзакций описана в `replication_sql_errors.md`; для точечного отката предпочитайте `UNTIL`.

## Дополнительная информация

- **Связанные файлы:** `failover_switchover.md` (промоушен и переключение), `lag_monitoring.md` (лаг и `Seconds_Behind_Source`), `relay_logs_crashsafe.md` (Relay Log и `relay_log_space_limit`), `gtid.md` (GTID и `gtid_executed`), `replication_sql_errors.md` (пропуск транзакций), `multi-source.md` (каналы), `parallel_replication_mts.md` (MTS), `setup_guide.md` (базовая настройка репликации), `../backup_and_recovery/pitr.md` (PITR по бинлогам)
- **Ключевые переменные/поля:** `SOURCE_DELAY`/`MASTER_DELAY`, `SQL_Delay`, `SQL_Remaining_Delay`, `Replica_SQL_Running_State`, `Seconds_Behind_Source`, `relay_log_space_limit`, `replica_parallel_workers`
- **Performance Schema:** `replication_applier_configuration` (`DESIRED_DELAY`), `replication_applier_status` (`REMAINING_DELAY`)
- **Внешние ресурсы:** [MySQL 8.4: Delayed Replication](https://dev.mysql.com/doc/refman/8.4/en/replication-delayed.html), [START REPLICA (UNTIL)](https://dev.mysql.com/doc/refman/8.4/en/start-replica.html), [RESET REPLICA](https://dev.mysql.com/doc/refman/8.4/en/reset-replica.html), [SHOW REPLICA STATUS](https://dev.mysql.com/doc/refman/8.4/en/show-replica-status.html), [CHANGE REPLICATION SOURCE TO](https://dev.mysql.com/doc/refman/8.4/en/change-replication-source-to.html)
