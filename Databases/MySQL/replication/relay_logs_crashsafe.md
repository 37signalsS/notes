# Relay Logs и Crash-Safe репликация

**Актуально для:** MySQL 5.6 / 5.7 / 8.0 / 8.4 LTS

## Определения

**Relay Log** — файлы на реплике, в которые I/O-поток (receiver) записывает события бинарного лога, полученные с источника. SQL-поток (applier; при MTS — координатор и воркеры) читает события из Relay Log и применяет их. Relay Log — буфер между приёмом по сети и применением; он восстанавливаем, так как источник хранит свой binlog.

**Relay Log Space** — суммарный размер всех файлов Relay Log на реплике. Контролируется через `relay_log_space_limit`.

**Metadata repositories** — хранилища позиций репликации: connection metadata repository (`mysql.slave_master_info`) — позиция I/O-потока и учётные данные подключения; applier metadata repository (`mysql.slave_relay_log_info`) — позиция SQL-потока; applier worker metadata repository (`mysql.slave_worker_info`, при MTS) — позиции воркеров. В MySQL 5.6/5.7 по умолчанию — файлы `master.info` / `relay-log.info` в datadir; с MySQL 8.0 — таблицы InnoDB (дефолт).

**Crash-Safe Replication** — конфигурация, при которой позиции репликации переживают сбой сервера: метаданные в транзакционных таблицах InnoDB + `relay_log_recovery = ON`. При TABLE-репозитории обновление позиции коммитится в той же транзакции, что и применённые события — информация о прогрессе всегда согласована с тем, что реально применено в БД, даже при внезапной остановке сервера.

**relay_log_recovery** — автоматическое восстановление Relay Log при старте сервера: отбрасывает неприменённые (возможно, повреждённые) relay log и запрашивает недостающие события с источника, начиная с последней применённой позиции.

## Базовые концепции

### Назначение Relay Log

1. **Буферизация**: I/O-поток не ждёт применения SQL-потоком — он просто пишет события в Relay Log. Это разграничивает приём по сети и применение.
2. **Выравнивание по скорости**: при временных проблемах с применением (блокировки, ресурсный дефицит) Relay Log накапливает события, позволяя I/O-потоку догнать источник по получению.
3. **Устойчивость**: в случае перезапуска реплики SQL-поток продолжает применение с последней сохранённой позиции в Relay Log.

### Файлы, имена и ротация

- Базовое имя: `host_name-relay-bin` (default-канал) и `host_name-relay-bin-channel_name` (остальные каналы); файлы создаются в datadir с числовым суффиксом. Полный путь — read-only переменная `relay_log_basename` (макс. 256 символов).
- `relay_log` — не динамическая переменная: задаёт базовое имя и каталог (абсолютный путь). Значение также используется как базовое имя индекса, если не задан `relay_log_index`. Relay log не может использовать те же имена, что и binlog — сервер не стартует.
- Ротация происходит при: старте I/O-потока, `FLUSH LOGS` / `FLUSH RELAY LOGS`, превышении `max_relay_log_size`.
- Очистка: SQL-поток удаляет relay log после полного применения событий (`relay_log_purge = ON`, дефолт). `STOP REPLICA` не удаляет relay log; `RESET REPLICA` удаляет все relay log-файлы и сбрасывает репозитории.

### Размер и лимиты

- `max_relay_log_size` — дефолт `0`: ротация по `max_binlog_size`. Диапазон: 4096 байт .. 1 ГБ (или 0). Динамическая.
- `relay_log_space_limit` — дефолт `0` (без лимита). **Не динамическая** (только `my.cnf` + рестарт). При достижении лимита I/O-поток останавливается до тех пор, пока SQL-поток не применит и не удалит часть relay log.
- Лимит **не абсолютный**: если SQL-потоку нужны события из relay log, который ещё нельзя удалить, I/O-поток временно превышает лимит — иначе возникла бы тупиковая ситуация. Не задавайте `relay_log_space_limit` меньше, чем 2× `max_relay_log_size` (или 2× `max_binlog_size` при `max_relay_log_size=0`): существует шанс, что I/O-поток ждёт свободного места, а удалить нечего.

### Метаданные репликации и crash-safety хранилища

| Версия | `master_info_repository` / `relay_log_info_repository` | Пояснение |
| :--- | :--- | :--- |
| MySQL 5.6 / 5.7 | **`FILE` по умолчанию** — задать `TABLE` явно | Файлы `master.info` / `relay-log.info` не crash-safe: позиция может отставать от применённых транзакций |
| MySQL 8.0 | `TABLE` по умолчанию | Переменные deprecated с 8.0.23; можно не указывать |
| MySQL 8.3.0 | **Удалены** | Метаданные всегда в таблицах |
| MySQL 8.4 LTS | — | Настраивать ничего не нужно |

- Таблицы `mysql.slave_master_info` и `mysql.slave_relay_log_info` создаются на InnoDB; обновление applier-репозитория коммитится вместе с транзакциями — позиция всегда согласована с применённым.
- **Не редактируйте** строки `mysql.slave_master_info` / `mysql.slave_relay_log_info` вручную — это не поддерживается и ведёт к неопределённому поведению.
- **Бэкап**: включайте `mysql.slave_master_info` и `mysql.slave_relay_log_info` в бэкап реплики — они нужны при создании новой реплики из снапшота.
- **Безопасность**: `mysql.slave_master_info` содержит имя и пароль пользователя репликации — ограничьте доступ к таблице и к бэкапам, её включающим.
- **GTID_ONLY** (8.0.27+): опция `CHANGE REPLICATION SOURCE TO` не записывать file/pos в репозитории — меньше записей при GTID-репликации.
- **Multi-source**: TABLE-репозиторий обязателен (иначе добавление канала падает с `ER_SLAVE_NEW_CHANNEL_WRONG_REPOSITORY`) — см. `multi-source.md`.

### relay_log_recovery

- Дефолт `OFF`; **read-only at runtime** (не динамическая) — задаётся только при старте сервера (`my.cnf` или `--relay-log-recovery`).
- При старте сервера: отбрасывает неприменённые relay log и перечитывает события с источника с последней применённой позиции.
- **MTS**: с 5.7.13 автоматически устраняет разрывы (gaps) в последовательности транзакций; до 5.7.13 требовалась ручная процедура с `START REPLICA UNTIL SQL_AFTER_MTS_GAPS`. Методика — `parallel_replication_mts.md`, раздел «Crash-safety и MTS».
- **Взаимодействие**: `relay_log_recovery = ON` + `relay_log_purge = OFF` — риск inconsistency (восстановление может читать неочищенные relay log); такая комбинация не crash-safe.
- Рекомендация: `ON` для production.

### sync_relay_log, sync_relay_log_info, sync_master_info

- Дефолт `10000` (MySQL 5.7, 8.0, 8.4): fsync relay log после каждых 10000 записей.
- `sync_relay_log_info` / `sync_master_info` — fsync файлов `relay-log.info` / `master.info` при FILE-репозитории. При TABLE-репозитории crash-safety позиции обеспечивается транзакциями InnoDB и не зависит от этих переменных.

| Значение `sync_relay_log` | Поведение | Компромисс |
| :--- | :--- | :--- |
| `0` | Нет принудительной sync (доверяем ОС) | Максимальная производительность; при крахе теряется хвост relay log (до 10000 записей) — он будет перечитан с источника |
| `10000` (дефолт) | Sync каждые 10000 записей | Баланс IO и объёма перечитывания |
| `1` | Sync после каждой записи | Минимальный объём перечитывания после краха, но сильный IO-оверхед на I/O-потоке |

**Почему relay log можно не синхронизировать строго:** в отличие от binlog источника, relay log восстанавливается — `relay_log_recovery = ON` перечитывает потерянный хвост с источника. `sync_relay_log = 1` имеет смысл, когда критичен объём повторного запроса событий после краха и есть IO-ресурс.

## Приусловия

- **Версия MySQL**: 5.6/5.7 — задавать `*_info_repository = TABLE` явно; 8.0 — не указывать (deprecated с 8.0.23); 8.4 — переменных нет.
- **Привилегии**: `SYSTEM_VARIABLES_ADMIN` (или `SUPER`) для `SET GLOBAL` динамических переменных (`relay_log_purge`, `max_relay_log_size`); `relay_log`, `relay_log_space_limit`, `relay_log_recovery` меняются только через `my.cnf` + рестарт; `REPLICATION_SLAVE_ADMIN` для управления потоками.
- **Диск**: relay log — на отдельном томе; запас места под отставание (при delayed replication — обязательно на всю величину задержки).
- **Бэкап метаданных** репликации включён в процедуру (см. «Метаданные репликации» выше).

## Практический блок

### Рекомендуемая конфигурация (production)

```ini
[mysqld]
# Расположение и размеры (путь — пример, подставьте свой)
relay_log = /var/lib/mysql/relay-bin
max_relay_log_size = 1024M   # 0 = ротация по max_binlog_size; 4096 байт .. 1 ГБ
relay_log_space_limit = 0    # 0 = без лимита; при ограниченном диске — >= 2x max_relay_log_size

# Crash-safe / восстановление
relay_log_recovery = ON      # только при старте сервера (не динамическая)
relay_log_purge = ON         # дефолт; не отключайте вместе с relay_log_recovery

# Синхронизация relay log
sync_relay_log = 10000       # дефолт; 1 — если критичен объём перечитывания после краха
```

> MySQL 5.6/5.7 — добавьте: `master_info_repository = TABLE` и `relay_log_info_repository = TABLE`. MySQL 8.0 — можно не указывать (deprecated с 8.0.23). MySQL 8.4 — переменных нет, метаданные всегда в таблицах.

### Мониторинг Relay Log

Текущий суммарный размер и лимит:
```sql
SHOW STATUS LIKE 'Relay_Log_Space';
-- → Relay_Log_Space | <байты>

SHOW VARIABLES LIKE 'relay_log_space_limit';
-- → relay_log_space_limit | 0
```

Позиция применения и текущий файл:
```sql
SHOW REPLICA STATUS\G
-- → Relay_Log_File: relay-bin.000003
-- → Relay_Log_Pos: 123456
```

Проверка crash-safe параметров:
```sql
SHOW VARIABLES LIKE 'relay_log_recovery';   -- → ON
SHOW VARIABLES LIKE 'relay_log_purge';      -- → ON
SHOW VARIABLES LIKE 'sync_relay_log';       -- → 10000
SHOW VARIABLES LIKE 'max_relay_log_size';   -- → 1024M
```

Проверка репозиториев (только MySQL 5.6/5.7; на 8.3+ переменных нет — пустой результат):
```sql
SHOW VARIABLES LIKE '%_info_repository%';
-- → master_info_repository | TABLE
-- → relay_log_info_repository | TABLE
```

Уровень ОС:
```bash
du -sh /var/lib/mysql/relay-bin*   # реальное место relay log
df -h /var/lib/mysql               # свободное место на томе
```

### Операции

- `FLUSH RELAY LOGS` — принудительная ротация relay log.
- `RESET REPLICA` — удаляет все relay log-файлы и сбрасывает репозитории (только при переинициализации реплики — теряет позицию).
- `STOP REPLICA SQL_THREAD` / `START REPLICA SQL_THREAD` — остановка применения (обслуживание); relay log при этом продолжает копиться.
- Изменение `relay_log`, `relay_log_space_limit`, `relay_log_recovery`: правка `my.cnf` + рестарт `mysqld` (переменные не динамические).

### Диагностика проблем с Relay Log

#### Сценарий 1: `Relay_Log_Space` растёт, реплика сильно отстаёт
- Причина: SQL-поток не успевает применять (ресурсы, блокировки, однопоток). I/O-поток продолжает писать в Relay Log.
- Действие: включить MTS, устранить блокировки, добавить ресурсы. См. `lag_monitoring.md`, `parallel_replication_mts.md`.

#### Сценарий 2: I/O-поток остановился из-за `relay_log_space_limit`
```sql
SHOW REPLICA STATUS\G
-- Ищем: Replica_IO_Running = No; Last_IO_Error может упоминать space limit
```
- Действие: либо увеличить `relay_log_space_limit` (`my.cnf` + рестарт, переменная не динамическая), либо ускорить применение. **Не** удаляйте relay log-файлы вручную — это приведёт к потере позиции и потребует перестройки реплики.

#### Сценарий 3: Реплика не стартует после краша
- При `relay_log_recovery = ON` + TABLE-репозитории восстановление автоматическое; если реплика всё равно не стартует — смотрите error.log.
- Частые причины:
  - на источнике purged нужные binlog — реплика не может перечитать события; восстановление из бэкапа реплики или rebuild через PITR (`../backup_and_recovery/pitr.md`);
  - повреждение диска/ФС (relay log или datadir);
  - legacy FILE-репозиторий (MySQL 5.6/5.7 без явного `TABLE`) — позиция могла потеряться; пересчёт позиции через GTID/File:Pos (`gtid.md`, `management_debug.md`).

### Валидация конфигурации

1. Проверьте значения переменных (ожидаемый вывод — в блоке «Мониторинг» выше); на 5.6/5.7 оба репозитория должны быть `TABLE`.
2. Crash-тест: имитируйте сбой (`kill -9 <pid>` mysqld или выключение питания ВМ), запустите сервер и проверьте:
```sql
SHOW REPLICA STATUS\G
-- → Replica_IO_Running: Yes
-- → Replica_SQL_Running: Yes
-- → Last_SQL_Error: (пусто)
-- → Relay_Log_Pos: продолжает с прежней позиции, Seconds_Behind_Source догоняет до 0
```
3. Согласованность позиции: `SELECT * FROM mysql.slave_relay_log_info;` — значение соответствует `Relay_Log_File` / `Relay_Log_Pos` из `SHOW REPLICA STATUS`.

### Откат изменений

- `relay_log_recovery = OFF`: `my.cnf` + рестарт (переменная не динамическая).
- Снять лимит: `relay_log_space_limit = 0` в `my.cnf` + рестарт.
- `relay_log_purge` — динамическая: `SET GLOBAL relay_log_purge = ON;`
- Очистка relay log происходит автоматически после применения; ручная чистка файлов не требуется и недопустима.

## Граничные случаи

- **Delayed replication**: relay log растёт на всю величину задержки (`SOURCE_DELAY`) — закладывайте место с запасом; детали — `delayed_replication.md`.
- **`relay_log_purge = OFF`**: relay log хранятся (для ручного анализа); вместе с `relay_log_recovery = ON` — не crash-safe.
- **Multi-source**: TABLE-репозиторий обязателен; relay log на канал имеют суффикс `-channel`; воркеры — на каждый канал. См. `multi-source.md`.
- **GTID_ONLY = 1** (8.0.27+): file/pos не персистятся в репозиториях при GTID-репликации.
- **`relay_log_space_limit` не абсолютный**: I/O-поток может временно превышать лимит, пока applier не сможет удалить relay log.
- **Имена**: `relay_log` / `relay_log_index` не могут совпадать с именами binlog — сервер не стартует.
- **Потеря хвоста relay log** при `sync_relay_log = 0` безопасна при `relay_log_recovery = ON`: неприменённые события перечитываются с источника.

## Лучшие практика

- `relay_log_recovery = ON` на всех production-репликах.
- TABLE-репозитории: в MySQL 5.6/5.7 — явно в `my.cnf`; в 8.0+ — дефолт.
- `sync_relay_log` — оставить дефолт `10000`; повышать до `1` только при критичном объёме перечитывания и наличии IO-ресурса.
- Отдельный том под relay log; алерт при приближении `Relay_Log_Space` к `relay_log_space_limit` (если задан) и при резком росте.
- `relay_log_space_limit` только при ограниченном диске: значение ≥ 2× `max_relay_log_size` с запасом 20–50% под худший лаг.
- Включайте `mysql.slave_master_info` / `mysql.slave_relay_log_info` в бэкап; ограничьте доступ к `slave_master_info` (пароль репликации).
- Не удаляйте relay log вручную и не редактируйте репозитории вручную.

## Дополнительная информация

- **Связанные файлы:** `lag_monitoring.md`, `parallel_replication_mts.md` (раздел «Crash-safety и MTS»), `delayed_replication.md`, `multi-source.md`, `master_slave_mechanism.md`, `management_debug.md`, `gtid.md`, `failover_switchover.md`, `../backup_and_recovery/pitr.md`
- **Ключевые переменные:** `relay_log` (не динам., дефолт `host_name-relay-bin`), `relay_log_index` (не динам., дефолт `host_name-relay-bin.index`), `max_relay_log_size` (динам., дефолт 0), `relay_log_space_limit` (не динам., дефолт 0), `relay_log_purge` (динам., дефолт ON), `relay_log_recovery` (не динам., дефолт OFF), `sync_relay_log` (динам., дефолт 10000), `sync_relay_log_info` / `sync_master_info` (динам., дефолт 10000), `master_info_repository` / `relay_log_info_repository` (дефолт FILE в 5.6/5.7, TABLE в 8.0; удалены в 8.3.0)
- **Внешние ссылки:** [Replica Server Options and Variables (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replication-options-replica.html), [The Relay Log (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replica-logs-relaylog.html), [Replication Metadata Repositories (8.4)](https://dev.mysql.com/doc/refman/8.4/en/replica-logs-status.html), [Handling an Unexpected Halt of a Replica (8.0)](https://dev.mysql.com/doc/refman/8.0/en/replication-solutions-unexpected-replica-halt.html)
