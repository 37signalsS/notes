# Проверка консистентности репликации (pt-table-checksum / pt-table-sync)

**Актуально для:** MySQL 5.7 / 8.0 / 8.4 LTS, Percona Toolkit 3.7.1-4 (релиз 2026-07-01; опции и инструменты `--slave-*` deprecated — алиасы `--replica-*`, переименование landed в 3.5.0)

## Определения

**Репликационная консистентность (data consistency)** — соответствие данных между источником и репликой. При нормальной асинхронной репликации данные по логике **должны** совпадать, но на практике расхождения возможны: ошибки применения, ручные правки, `sql_replica_skip_counter`, сбои.

**pt-table-checksum** — инструмент Percona Toolkit для обнаружения расхождений. Выполняет checksum-запросы **на источнике**, результаты реплицируются на реплики и сравниваются. Работает чанками (chunks), троттлится под нагрузку.

**pt-table-sync** — инструмент генерации/применения SQL для устранения расхождений. Требует **крайней осторожности** в production: изменяет данные.

**Chunk** — порция строк таблицы, checksummируемая одним запросом `REPLACE..SELECT`. Размер адаптируется под скорость выполнения (таргет — `--chunk-time=0.5` с).

**CRC32** — функция контрольной суммы по умолчанию (`--function=CRC32`). Быстрая и малонагруженная, но **не криптографическая** — возможны коллизии. Альтернативы: `MD5`, `SHA1` (встроенные в MySQL), `FNV1A_64`/`MURMUR_HASH` (требуют UDF из Percona Server / Percona Toolkit UDF).

## Теоретический блок

### Почему важна проверка консистентности

- **`SHOW REPLICA STATUS` не проверяет содержимое строк** — он показывает состояние потоков и позицию, но не данные. `Seconds_Behind_Source = 0` не означает идентичности данных.
- **ROW-репликация** теоретически безопаснее, но расхождения всё же возможны: ручные UPDATE/DELETE на реплике, `SET GLOBAL sql_log_bin=0`, ошибки применения, `sql_replica_skip_counter`.
- **STATEMENT-репликация** — выше риск расхождений при недетерминированных функциях (`NOW()`, `UUID()`, `RAND()` без привязки).
- **После failover/switchover** — целесообразно проверить консистентность, особенно если были сомнения в выборе кандидата или использовался `sql_replica_skip_counter`.
- **Перед бэкапом с реплики** — бэкап с рассинхронизированной реплики расширяет RPO (см. **[Бэкап и репликация](backup_replication.md)**).

### Принцип работы pt-table-checksum

1. Запускается **на источнике** (DSN указывает на источник). Создаёт таблицу `percona.checksums` (`--replicate`, default `percona.checksums`; `--create-replicate-table` default yes — создаёт БД/таблицу при отсутствии; `--empty-replicate-table` default yes — очищает суммы для проверяемой таблицы в начале её проверки).
2. Делит таблицу на чанки по индексу (предпочтительно PRIMARY/UNIQUE; без индекса — одним чанком, если строк немного). Размер чанка адаптивно таргетит `--chunk-time=0.5` с; стартовое значение `--chunk-size=1000` (явная установка `--chunk-size` **отключает** адаптацию — в большинстве случаев предпочтительнее `--chunk-time`).
3. Каждый чанк checksummируется **одним запросом `REPLACE..SELECT`**, результат пишется в `percona.checksums` и **реплицируется** на все реплики.
4. После каждой таблицы (`--replicate-check` default yes) инструмент простым `SELECT` сверяет суммы на всех обнаруженных репликах: `this_crc`/`this_cnt` против `source_crc`/`source_cnt`.
5. Печатает строку результата на таблицу (см. «Анализ результатов»).

**Защиты и троттлинг (важны для production):**

- Сессионный `innodb_lock_wait_timeout=1` — при lock wait инструмент становится **жертвой**, а не блокирует чужие запросы.
- `--max-load=Threads_running=25` (default) — `SHOW GLOBAL STATUS` после каждого чанка, пауза при превышении.
- `--max-lag=1s` (default) — `Seconds_Behind_Source` всех подключённых реплик после каждого чанка, пауза до догона.
- `--check-plan` (default yes) — `EXPLAIN` перед chunk-запросами, чанки с плохим планом пропускаются.
- `--chunk-size-limit=2.0` (default) — пропуск чанков, чей размер превышает желаемый более чем в 2 раза.
- Отказ работать при фильтрах репликации (`--check-replication-filters` default yes) и при отсутствии таблиц на репликах (`--check-replica-tables` default yes).
- `CTRL-C` безопасен (доделает текущий чанк); убитый запрос ретраится один раз; `--resume` продолжает с последнего чанка последней таблицы.

### Ограничения (LIMITATIONS)

- **Требуется STATEMENT-репликация для прохождения сумм**: инструмент ставит `binlog_format=STATEMENT` в сессии на источнике, но реплики не наследуют сессионное значение. Поэтому чек-суммы **не пройдут дальше ROW-реплики, которая сама является источником** для следующих реплик (chained replication). На простой топологии source → replica ROW работает.
- Инструмент **предполагает идентичность схем** на источнике и всех репликах — расхождение структур ломает проверку.
- Таблицы **RocksDB пропускаются** (ограничения движка).
- Percona XtraDB Cluster — только поддерживаемые сетапы (recursion-method `dsn`).
- Реплики должны быть **обнаруживаемы** (`--recursion-method` default `processlist,hosts`); если реплик не найдено — предупреждение и **non-zero exit status** (`NO_REPLICAS_FOUND`), diffs найдены не будут.
- `--check-binlog-format` (default yes): инструмент сверяет `binlog_format` на всех серверах и прерывает работу при различиях. `--no-check-binlog-format` отключает проверку — используйте осознанно.

### Когда использовать pt-table-sync

**Только после подтверждённых расхождений pt-table-checksum.**

- С `--sync-to-source` или `--replicate` изменения делаются **на источнике** как no-op `REPLACE`, которые реплицируются на реплику. Это единственный безопасный путь: прямая запись на реплику обычно и является причиной расхождений.
- `REPLACE` работает только при наличии **уникального индекса**. Без уникального ключа изменить данные можно только на реплике напрямую — инструмент обнаружит это и **умрёт**, пока не указать `--no-check-replica` (опасно).
- **Source-source pair**: прямая запись на destination реплицируется обратно на источник — нужен `--no-bin-log` (или `--sync-to-source` + `--no-check-replica`).
- Инструмент **не синхронизирует структуру, индексы и другие объекты схемы** — только данные.
- **Побочный эффект**: при `--sync-to-source` другие реплики того же источника тоже получат no-op изменения через репликацию.

## Практический блок

### 0. Предусловия

- **Percona Toolkit** установлен; на Debian/Ubuntu нужен `libdbd-mysql-perl`, на RHEL/CentOS — `perl-DBD-MySQL`.
- **Привилегии** (выделенный пользователь, не `root`; учётка должна существовать на всех узлах либо используйте `--replica-user`):

| Где | Привилегия | Зачем |
| :--- | :--- | :--- |
| Источник | `SELECT` на проверяемых таблицах | чтение данных для чанкинга |
| Источник | `INSERT`, `DELETE` на БД `--replicate` | `REPLACE INTO percona.checksums` = INSERT+DELETE |
| Источник | `CREATE` на БД `--replicate` | создание `percona.checksums` при отсутствии |
| Источник | `PROCESS` | обнаружение реплик через `SHOW PROCESSLIST` |
| Источник | `REPLICATION CLIENT` | `SHOW REPLICA STATUS` (обнаружение топологии) |
| Источник | `SUPER` (Percona docs) / `SESSION_VARIABLES_ADMIN` на MySQL 8.0.14+ | сессионный `SET binlog_format=STATEMENT` (restricted session variable; `SYSTEM_VARIABLES_ADMIN`/`SUPER` эквивалентно) |
| Реплики | `SELECT` | сверка checksum-сумм |

- **Сетевой доступ** инструмента ко всем узлам топологии.
- **Индекс для чанкинга** (PRIMARY/UNIQUE) на проверяемых таблицах; для безопасного `pt-table-sync` уникальный индекс обязателен.
- **Отсутствие фильтров репликации** (`replicate_do_db` и т. п.) — иначе инструмент откажется работать.
- Обнаружение репликов: метод `processlist` (default), `hosts` (требует `report_host`/`report_port`), `dsn=h=...,D=percona,t=dsns` (таблица DSN-ов), `none`.

### 1. Проверка консистентности (pt-table-checksum)

Базовый запуск (проверяет все БД, суммы пишет в `percona.checksums` на источнике):

```bash
pt-table-checksum \
  --replicate=percona.checksums \
  h=master_host,u=pt_user,p=pt_pass
# → TS ERRORS DIFFS ROWS DIFF_ROWS CHUNKS SKIPPED TIME TABLE
```

Запуск с ограничением области и троттлингом:

```bash
pt-table-checksum \
  --replicate=percona.checksums \
  --databases=app_db \
  --tables=orders,customers \
  --chunk-time=0.5 \
  --max-load=Threads_running=25 \
  --max-lag=1s \
  --progress=time,30 \
  h=master_host,u=pt_user,p=pt_pass
# → строка на таблицу; DIFFS=0 при консистентности
```

**Ключевые опции:**

| Опция | Default | Назначение |
| :--- | :--- | :--- |
| `--replicate` | `percona.checksums` | таблица для хранения сумм (можно `db.table`) |
| `--replicate-check` | yes | сверять суммы на репликах после каждой таблицы |
| `--replicate-check-only` | no | не checksummировать заново, только сверять уже посчитанные; печатает **только** таблицы с расхождениями (другой формат вывода) |
| `--databases` / `-d` | — | ограничить БД; `--ignore-databases` — исключить |
| `--tables` / `-t` | — | ограничить таблицы; `--ignore-tables`, `--ignore-tables-regex` |
| `--where` | — | `WHERE`-условие для выборки строк |
| `--columns` / `-c` | — | checksummировать только указанные колонки |
| `--chunk-time` | `0.5` | таргет времени выполнения чанка; адаптивный размер |
| `--chunk-size` | `1000` | стартовый размер; явная установка **отключает** адаптацию |
| `--chunk-size-limit` | `2.0` | пропуск чанков больше N×желаемого размера; `0` отключает проверку |
| `--chunk-index` | auto | предпочитаемый индекс для чанкинга (`FORCE INDEX`) |
| `--function` | `CRC32` | `MD5`, `SHA1`, `FNV1A_64`, `MURMUR_HASH` (последние два — UDF) |
| `--max-lag` | `1s` | пауза, пока лаг любой реплики больше значения |
| `--max-load` | `Threads_running=25` | пауза при превышении статусных переменных |
| `--check-interval` | `1` | интервал проверок лага (с) |
| `--check-replica-lag` | — | мониторить лаг только указанной реплики (полезно при delayed replication — см. **[Отложенная репликация](delayed_replication.md)**) |
| `--check-replication-filters` | yes | отказ при фильтрах репликации |
| `--check-replica-tables` | yes | проверка наличия таблиц и колонок на репликах |
| `--check-plan` | yes | `EXPLAIN`-проверка планов чанков |
| `--fail-on-stopped-replication` | no | падать при остановленной репликации |
| `--resume` | no | продолжить с последнего чанка после полного останова |
| `--run-time` / `--retries` | — | ограничение времени / ретраи при ошибках |
| `--progress` | — | прогресс-бар (`time,30`, `percentage,1`) |
| `--quiet` | no | меньше вывода (ошибки — в STDERR) |
| `--pid` / `--pause-file` | — | PID-файл / файл паузы (удобно для cron и обхода пиков) |
| `--replica-user` / `--replica-password` | — | отдельный пользователь для подключений к репликам |
| `--recursion-method` | `processlist,hosts` | метод обнаружения реплик |
| `--channel` | — | канал multi-source (см. **[Multi-source репликация](multi-source.md)**) |
| `--explain` | no | показать, как инструмент будет checksummировать таблицу (dry-run-подобное) |
| `--binary-index` | no | границы чанков типа BLOB (бинарные ключи, нестандартные charset) |
| `--replicate-database` | — | `USE` только указанной БД (workaround для фильтров) |
| `--truncate-replicate-table` | no | truncate всей таблицы сумм в начале (все предыдущие суммы теряются) |

**Нет опций `--print` и `--sleep`** (частая ошибка в runbook'ах): dry-run — это `--explain`, а троттлинг регулируется `--chunk-time`/`--max-load`/`--max-lag`.

### 2. Анализ результатов

Формат вывода — строка на таблицу:

```text
TS           ERRORS  DIFFS  ROWS  DIFF_ROWS  CHUNKS  SKIPPED  TIME  TABLE
10-20T08:36:50      0      0   200          0       1       0  0.005  db1.tbl1
10-20T08:36:50      0      2  80000       1200      80       0 15.200  db1.tbl2
```

| Колонка | Значение |
| :--- | :--- |
| `TS` | метка времени завершения checksumming таблицы (без года) |
| `ERRORS` | число ошибок/предупреждений при проверке таблицы (детали — в STDERR) |
| `DIFFS` | **число чанков, отличающихся от источника** на одной или более репликах; `> 0` — есть расхождения (с `--no-replicate-check` всегда 0) |
| `ROWS` | строк, выбранных и checksummированных (может отличаться от числа строк в таблице при `--where`) |
| `DIFF_ROWS` | **максимальное** число отличающихся строк в одном чанке |
| `CHUNKS` | число чанков |
| `SKIPPED` | чанки, пропущенные из-за плохого плана/размера/lock wait/kill (с версии 2.2.5 → non-zero exit status) |
| `TIME` | время checksumming таблицы |

Ручной отчёт по таблице сумм (колонки 3.x: `db, tbl, chunk, chunk_index, lower_boundary, upper_boundary, this_crc, this_cnt, source_crc, source_cnt, ts`):

```sql
SELECT db, tbl, SUM(this_cnt) AS total_rows, COUNT(*) AS chunks
FROM percona.checksums
WHERE (source_cnt <> this_cnt OR source_crc <> this_crc
       OR ISNULL(source_crc) <> ISNULL(this_crc))
GROUP BY db, tbl;
```

> Имена `master_crc`/`master_cnt` — от toolkit 1.0; в Percona Toolkit 3.x колонки называются `source_crc`/`source_cnt`.

`--replicate-check-only` печатает другой формат — параграф на реплику с расхождениями:

```text
Differences on h=127.0.0.1,P=12346
TABLE      CHUNK  CNT_DIFF  CRC_DIFF  CHUNK_INDEX  LOWER_BOUNDARY  UPPER_BOUNDARY
db1.tbl1   1      0         1         PRIMARY      1               100
db1.tbl1   6      0         1         PRIMARY      501             600
```

**Exit status** (битмаска — удобно для cron/мониторинга):

| Флаг | Бит | Значение |
| :--- | :--- | :--- |
| `ERROR` | 1 | некритическая ошибка |
| `ALREADY_RUNNING` | 2 | `--pid`-файл существует и PID жив |
| `CAUGHT_SIGNAL` | 4 | пойман SIGHUP/SIGINT/SIGPIPE/SIGTERM |
| `NO_REPLICAS_FOUND` | 8 | реплики не обнаружены |
| `TABLE_DIFF` | 16 | **найдено хотя бы одно расхождение** |
| `SKIP_CHUNK` | 32 | пропущен хотя бы один чанк |
| `SKIP_TABLE` | 64 | пропущена хотя бы одна таблица |
| `REPLICATION_STOPPED` | 128 | реплика недоступна или остановлена |

`255` — фатальная ошибка (инструмент умер; текст — в STDERR). `0` — всё чисто. Проверка конкретного флага: `pt-table-checksum ...; rc=$?; [ $((rc & 16)) -ne 0 ] && echo "DIFFS FOUND"`.

### 3. Синхронизация расхождений (pt-table-sync) — ТОЛЬКО при подтверждённых расхождениях

**Правило: сначала `--print` (или `--dry-run`), потом решать о применении.** Требуется указать минимум один из `--print`, `--execute`, `--dry-run`.

Печатаем SQL, который приведёт реплику к её источнику:

```bash
pt-table-sync \
  --print \
  --sync-to-source \
  h=replica_host,u=pt_user,p=pt_pass
# → SQL-запросы (REPLACE/INSERT/UPDATE/DELETE), применяемые НА ИСТОЧНИКЕ
```

> **Критично:** DSN — это **реплика**, а не источник. Инструмент подключается к реплике, читает `SHOW REPLICA STATUS`, находит её источник и применяет изменения **на источнике** — они реплицируются на реплику как no-op `REPLACE`. (`--sync-to-master` — deprecated-алиас, будет удалён.)

Если SQL корректен — выполняем:

```bash
pt-table-sync \
  --execute --verbose \
  --sync-to-source \
  h=replica_host,u=pt_user,p=pt_pass
# → # Syncing h=replica_host ...
# → # DELETE REPLACE INSERT UPDATE ALGORITHM START    END      EXIT DATABASE.TABLE
# → #      0       0      3      0 Chunk     13:00:00 13:00:17 2    app_db.t1
```

По **всем** репликам источника (используя результаты `pt-table-checksum`):

```bash
pt-table-sync --execute --replicate percona.checksums h=master_host,u=pt_user,p=pt_pass

# Только одна реплика из числа обнаруженных:
pt-table-sync --execute --replicate percona.checksums \
  --sync-to-source h=replica_host,u=pt_user,p=pt_pass
```

Без `--replicate` (независимые хосты, не в одной топологии): первый DSN — источник, остальные — destination; инструмент **умрёт**, если destination — реплика (`--check-replica` default yes):

```bash
pt-table-sync --execute h=host1,D=db,t=tbl h=host2
```

**Ключевые опции:**

| Опция | Default | Назначение |
| :--- | :--- | :--- |
| `--print` | — | напечатать SQL без выполнения (валидный SQL, можно запустить вручную) |
| `--execute` | — | выполнить синхронизацию (**данные изменяются!** без `--verbose` — молча) |
| `--dry-run` | — | анализ + выбор алгоритма + печать и выход; implies `--verbose`; **нули в выводе ≠ «нет изменений»** |
| `--verbose` / `-v` | no | вывод результатов синхронизации (накопительная: дважды — SQL выборки чанков) |
| `--explain-hosts` | — | показать, как инструмент интерпретирует DSN-ы, и выйти |
| `--sync-to-source` | — | DSN — реплика; синхронизировать её с источником (changes on source; `--wait=60`, `--lock=1`, транзакции отключены по умолчанию) |
| `--replicate` | — | взять расхождения из таблицы `pt-table-checksum` (implies `--wait=60`, changes on source) |
| `--channel` | — | канал multi-source (когда `SHOW REPLICA STATUS` возвращает несколько строк) |
| `--algorithms` | `Chunk,Nibble,GroupBy,Stream` | порядок алгоритмов поиска различий |
| `--chunk-size` | `1000` | размер чанка (строк или данных `k`/`M`/`G`) |
| `--columns` / `-c` | — | сравнивать только указанные колонки |
| `--where` | — | `WHERE`-ограничение; **mutually exclusive с `--replicate`** |
| `--replace` | auto | писать `INSERT`/`UPDATE` как `REPLACE` (автовключается при конфликтах уникальных ключей) |
| `--lock` | 0 | блокировки: `1` — на цикл синхронизации, `2` — на таблицу, `3` — `FTWRL` на все серверы |
| `--[no]transaction` | yes | транзакции вместо `LOCK TABLES` (InnoDB; `REPEATABLE READ` + `WITH CONSISTENT SNAPSHOT`) |
| `--wait` / `-w` | зависит от опций | ждать догона реплики перед сравнением (с `--sync-to-source` — 60 с); ошибка `SOURCE_POS_WAIT returned -1` — таймаут |
| `--timeout-ok` | no | продолжать после таймаута `--wait` (опасно для консистентного сравнения) |
| `--[no]bin-log` | yes | писать SQL в бинарлог; `--no-bin-log` → `SET SQL_LOG_BIN=0` (нужен для source-source без PK) |
| `--[no]check-child-tables` | yes | проверка child-таблиц с `ON DELETE/UPDATE CASCADE`: `REPLACE` = `DELETE`+`INSERT`, каскад может **удалить все строки child-таблиц** — таблица пропускается с ошибкой |
| `--[no]check-replica` | yes | отказ, если destination — реплика (прямая запись на реплику небезопасна) |
| `--[no]check-source` | yes | проверять, что обнаруженный источник — настоящий источник |
| `--[no]check-triggers` | yes | проверка триггеров на destination-таблице |
| `--[no]foreign-key-checks` / `--[no]unique-checks` | yes | `SET FOREIGN_KEY_CHECKS` / `SET UNIQUE_CHECKS` |
| `--replica-user` / `--replica-password` | — | пользователь с меньшими привилегиями для подключений к репликам (должен существовать на всех) |
| `--function` | `CRC32` | `MD5`, `SHA1`, `FNV_64`, `MURMUR_HASH` (UDF) |
| `--float-precision` | нет | округление `FLOAT`/`DOUBLE` для сравнения (избежать false-positive из-за представления) |

**Exit status pt-table-sync:** `0` — успех; `1` — внутренняя ошибка; `2` — хотя бы одна таблица отличалась на destination; `3` — комбинация 1 и 2.

### 4. Валидация после синхронизации

1. Повторная проверка: `pt-table-checksum --replicate=percona.checksums --replicate-check-only ...` (или полный прогон) — `DIFFS=0`, exit status `0`.
2. Поиск **причины** расхождения (ручные правки, `sql_log_bin=0`, `sql_replica_skip_counter`, фильтры) — иначе расхождения повторятся.
3. Интеграция exit status в мониторинг/алертинг (см. «Лучшие практики»).

## Диагностика и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NO_REPLICAS_FOUND` (exit 8), warning «no replicas found» | реплики не обнаружены: `SHOW PROCESSLIST` пуст, `report_host` не задан | `--recursion-method hosts` (настроить `report_host`/`report_port`) или `dsn=...`; если нужно только писать суммы без сверки — `--recursion-method none` + `--no-replicate-check` |
| «Replication filters found», отказ при старте | на реплике заданы `replicate_do_db`/`binlog_ignore_db` и т. п. | убрать фильтры; либо осознанно `--no-check-replication-filters` (+ `--replicate-database`) |
| `ERRORS > 0` в выводе | ошибки доступа или отсутствие таблицы/колонок на реплике | детали в STDERR; дать `SELECT`/`SHOW VIEW`; `--check-replica-tables` диагностирует |
| `SKIPPED > 0` | чанки пропущены: плохой план, размер > `--chunk-size-limit`, lock wait, kill | `--chunk-index`, `--explain`, увеличить `--chunk-size-limit`; смотреть план |
| `DIFFS > 0` | реальное расхождение данных | анализ чанков (`--replicate-check-only` показывает границы) → `pt-table-sync --print` → `--execute` |
| pt-table-sync умирает: destination — реплика | защита `--check-replica`: прямая запись на реплику запрещена | использовать `--sync-to-source`/`--replicate` (изменения на источнике); `--no-check-replica` — только осознанно |
| «Child table ... skipped» | FK с `ON DELETE CASCADE` + `REPLACE` (DELETE+INSERT каскадирует) | проверить схему; при необходимости `--no-foreign-key-checks` |
| `SOURCE_POS_WAIT returned -1` | реплика не догнала источника за `--wait` | увеличить `--wait`; `--timeout-ok` — только если согласны с риском |
| Multi-source: не может определить источник | `SHOW REPLICA STATUS` возвращает несколько строк | `--channel=channel_name` |
| `percona.checksums` растёт / старые суммы мешают | суммы за прошлые проверки | `--truncate-replicate-table` или ручная чистка; таблица сама реплицируется на реплики |
| Проверка «зависает» на одной таблице | долгий чанк / блокировки | `--chunk-time`, `--chunk-size`, `--pause-file` для паузы на время пика |
| MyISAM-таблицы | нет транзакций, иная семантика блокировок | чанкинг работает, но проверяйте в окна минимальной нагрузки; предпочтительно переносить на InnoDB |

## Лучшие практики

- **Регулярность**: еженедельный cron плюс принудительный прогон **после failover/switchover** и после применения `sql_replica_skip_counter`.
- **Ограничивайте область** (`--databases`/`--tables`), не запускайте в пиковую нагрузку; `--pid`/`--pause-file` для безопасного cron.
- **Троттлинг под вашу нагрузку**: `--chunk-time`, `--max-load`, `--max-lag`.
- **Выделенный пользователь** с минимальными привилегиями (см. «Предусловия»), никогда не `root`.
- **`super_read_only = ON`** на репликах — защита от случайной прямой записи.
- **CRC32 быстр, но не криптостойкий** (коллизии) — для критичных данных `--function=MD5`/`SHA1` (ценой CPU).
- **Бэкап перед `--execute`**; `--print` первым; тест на стенде.
- **Ищите причину** расхождения — sync без анализа причины маскирует проблему.
- **Очистка**: после проверок очистите `percona.checksums` (или `--truncate-replicate-table`), чтобы старые суммы не путали следующий `--replicate-check-only`.
- **Мониторинг**: `rc=$?` + битмаска exit status (`& 16` — расхождения, `& 8` — реплики не найдены) в алертинге.

## Дополнительная информация

- **Связанные файлы:** `lag_monitoring.md`, `failover_switchover.md`, `replication_sql_errors.md`, `delayed_replication.md`, `multi-source.md`, `binlog_formats.md`, `management_debug.md`, `backup_replication.md`, `../backup_and_recovery/xtrabackup.md`
- **Инструменты:** Percona Toolkit (`pt-table-checksum`, `pt-table-sync`, `pt-heartbeat` — истинный лаг, см. `lag_monitoring.md`)
- **Предостережение:** `pt-table-sync --execute` изменяет данные. Применять только после подтверждённых расхождений и обязательного бэкапа.
- **Внешние ресурсы:**
  - [pt-table-checksum — документация](https://docs.percona.com/percona-toolkit/pt-table-checksum.html)
  - [pt-table-sync — документация](https://docs.percona.com/percona-toolkit/pt-table-sync.html)
  - [How to avoid hash collisions when using MySQL's CRC32 function](https://www.percona.com/blog/2014/10/13/how-to-avoid-hash-collisions-when-using-mysqls-crc32-function/)
  - [Percona Toolkit UDF (FNV_64, MURMUR_HASH)](https://docs.percona.com/percona-server/8.0/udf-percona-toolkit.html)
