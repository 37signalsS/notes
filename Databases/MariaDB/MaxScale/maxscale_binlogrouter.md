# MariaDB MaxScale: Binlog Router

**Актуально для:** MaxScale 25.10.x

## Определения

*   **binlogrouter** — роутер-прокси репликации: подключается к Primary, скачивает бинлоги и хранит их локально (модуль хранения — pinloki). Реплики подключаются к MaxScale как к обычному Primary.
*   **pinloki** — внутренний механизм хранения бинлогов MaxScale.
*   **GTID-only** — binlogrouter работает только с GTID-репликацией (`MASTER_LOG_FILE`/`MASTER_LOG_POS` не поддерживаются).
*   **expiration_mode** — режим утилизации старых бинлогов: `purge` (удаление) или `archive` (перемещение в `archivedir`); режимы взаимоисключающие.
*   **bootstrap** — сброс стартовой GTID-позиции binlogrouter при потере/повреждении хранилища бинлогов.
*   **CDC (Change Data Capture)** — применение прочитанных изменений к целевой системе; binlogrouter умеет CDC в Exasol по ODBC (параметры `odbc_*`, MaxScale 25.10.3+).
*   **Encryption Key Manager** — глобальный параметр `key_manager` (`none`/`file`/`kmip`/`vault`, default `none`), хранилище ключей для шифрования бинлогов (`encryption_key_id`).

## Как работает

### Зачем binlogrouter

1.  **Снижение нагрузки на Primary:** одно соединение MaxScale→Primary вместо N соединений реплик→Primary. Значимо при большом числе реплик.
2.  **HA репликации:** при падении Primary реплики продолжают читать бинлоги из MaxScale до последней реплицированной позиции. Смена Primary — без переподключения реплик и без их ведома.
3.  **Архивирование/компрессия:** бинлоги архивируются на отдельную файловую систему (например, NFS) и сжимаются (zstandard). Если архивирование запущено с Primary, у которого сохранена полная история, архивом будет полная копия Primary.

### Поток данных

Primary (binlog_dump) → MaxScale (pinloki, `datadir`) → реплики (listener, `MariaDBClient`). Имя базы файлов задаёт Primary; в `datadir` файлы имеют вид `.<имя>.<шестизначный_номер>`, первый файл — `.000001`. Файл `binlog.index` содержит упорядоченный по номеру список файлов и автоматически перегенерируется при любом изменении содержимого `datadir`.

### Ограничения

*   Только GTID-репликация.
*   Только MariaDB-источники (включая Galera).
*   Источник должен иметь `binlog_checksum=CRC32`.
*   `RESET SLAVE ALL` не поддерживается (только `RESET SLAVE`).
*   Не используйте `auto_rejoin` монитора, если монитор наблюдает за binlogrouter — mariadbmon пошлёт команды, которые binlogrouter не поддерживает (ограничение будет снято в будущей версии).
*   Старые зашифрованные бинлоги не перешифровываются новой версией ключа ([MXS-4140](https://jira.mariadb.org/browse/MXS-4140)).

## Prerequisites

*   GTID-репликация на источнике.
*   `binlog_checksum=CRC32` на источнике.
*   inotify-лимиты ядра (см. Шаг 9).
*   Минимум один listener, к которому подключаются реплики, и один server, из которого MaxScale берёт информацию о пользователях БД.
*   Для Galera: `wsrep_gtid_mode=ON`, `log_bin=pinloki`, уникальный `gtid_domain_id` на каждом узле, общий `wsrep_gtid_domain_id`, MariaDB 10.5.1+.
*   Если включено шифрование бинлогов — сконфигурированный `key_manager` (см. Шаг 7).

## Шаг 1: Конфигурация с автоматическим выбором Primary

```ini
# /etc/maxscale.cnf

[server1]
type=server
address=192.168.0.1
port=3306

[server2]
type=server
address=192.168.0.2
port=3306

[MariaDB-Monitor]
type=monitor
module=mariadbmon
servers=server1,server2
user=maxuser
password=СЛОЖНЫЙ_ПАРОЛЬ
monitor_interval=10s

[Replication-Proxy]
type=service
router=binlogrouter
cluster=MariaDB-Monitor

# Автоматический выбор Primary из монитора
select_master=true

# Хранение бинлогов
datadir=/var/lib/maxscale/binlogs

# Архивирование старых логов
expiration_mode=archive
archivedir=/mnt/binlog-archive
expire_log_minimum_files=3
expire_log_duration=24h

# Компрессия (кроме последних файлов)
compression_algorithm=zstandard
number_of_noncompressed_files=2

# ID MaxScale при подключении к Primary и обслуживании реплик
server_id=1234

# Таймаут сети к Primary
net_timeout=10s

user=maxuser
password=СЛОЖНЫЙ_ПАРОЛЬ

[Replication-Listener]
type=listener
service=Replication-Proxy
protocol=MariaDBClient
port=3306
```

Вместо `cluster=<монитор>` серверы можно перечислить прямо в сервисе: `servers=server1,server2` (серверы должны наблюдаться монитором).

### Параметры binlogrouter

Все параметры — не dynamic (изменение требует перезапуска), кроме `rpl_semi_sync_slave_enabled`.

| Параметр | Тип | Default | Описание |
| :--- | :--- | :--- | :--- |
| `datadir` | path | `/var/lib/maxscale/binlogs` | Каталог хранения бинлогов |
| `archivedir` | string | — | Каталог архива; обязателен при `expiration_mode=archive`; должен существовать при старте MaxScale; пользователь maxscale должен иметь права |
| `server_id` | count | `1234` | server_id при подключении к Primary и при раздаче бинлогов репликам |
| `net_timeout` | duration | `10s` | Таймаут соединения и чтения с Primary |
| `select_master` | boolean | `false` | Автовыбор Primary из серверов монитора (`cluster=`) или списка (`servers=`); используются только серверы со статусом Master; при нескольких Primary — первый доступный |
| `expiration_mode` | enum | `purge` | `purge` (удаление) или `archive` (перемещение в `archivedir`) |
| `expire_log_duration` | duration | `0s` | Возраст файла от последней модификации, после которого он подходит для purge/archive; `0s` отключает автопurge |
| `expire_log_minimum_files` | number | `2` | Минимум файлов, которые авто-purge/archive не тронет; всегда хранится хотя бы один файл |
| `compression_algorithm` | enum | `none` | `none` или `zstandard` (единственный поддерживаемый алгоритм) |
| `number_of_noncompressed_files` | count | `2` | Минимум несжатых файлов; всегда несжат хотя бы один (последний, в который пишется) |
| `ddl_only` | boolean | `false` | В бинлоги пишутся только DDL-события (`CREATE`/`ALTER`/`DROP`); `INSERT`/`UPDATE`/`DELETE` не пишутся |
| `encryption_key_id` | string | `""` | ID ключа шифрования бинлогов (см. Шаг 7) |
| `encryption_cipher` | enum | `AES_GCM` | `AES_GCM`, `AES_CBC`, `AES_CTR`; поддерживаются ключи 128/192/256 bit |
| `rpl_semi_sync_slave_enabled` | boolean | `false` | **Dynamic: Yes.** semi-sync при репликации от MariaDB: binlogrouter подтверждает каждое полученное событие; на источнике должен быть `rpl_semi_sync_master_enabled` |

**Пояснения:**

*   `select_master=true` — Primary «липкий»: при перезапуске выбирается тот же. При получении `CHANGE MASTER TO` команда применяется, а `select_master` выключается до перезапуска — это позволяет монитору делать failover/switchover и пользователю перенаправить binlogrouter вручную. Стартовая GTID-позиция берётся из последнего реплицированного GTID; если репликации ещё не было — с начала бинлогов.
*   `expiration_mode=archive` + `archivedir` — директория должна существовать при старте MaxScale; пользователь maxscale должен иметь права.
*   `ddl_only=true` — писать в бинлоги только DDL (полезно для трекинга изменений схемы; пустой сервер поднимается, указав на такой binlogrouter).

## Шаг 2: Подключение реплик к binlogrouter

Если `select_master=true` и MaxScale уже реплицирует — реплики просто переключаются:

```bash
mariadb -u USER -p -h replica-IP -P 3306
STOP SLAVE;
CHANGE MASTER TO
  master_host="maxscale-IP",
  master_port=3306,
  master_user="USER",
  master_password="ПАРОЛЬ",
  master_use_gtid=slave_pos;
START SLAVE;
SHOW SLAVE STATUS\G
```

Ручная настройка (без `select_master`):

```bash
mariadb -u USER -p -h maxscale-IP -P 3306
CHANGE MASTER TO
  master_host="primary-IP",
  master_port=3306,
  master_user="USER",
  master_password="ПАРОЛЬ",
  master_use_gtid=slave_pos;
START SLAVE;
```

## Шаг 3: Bootstrap (восстановление позиции)

Если бинлоги потеряны или повреждены — остановите MaxScale, очистите `datadir` (или задайте другой), задайте стартовую GTID-позицию (обычно — минимальный GTID среди реплик):

```bash
mariadb -u USER -p -h maxscale-IP -P 3306
STOP SLAVE;
SET @@global.gtid_slave_pos = "0-1000-1234,1-1001-5678";
START SLAVE;
```

При `select_master=true` и полной бинлог-истории на Primary достаточно перезапуска MaxScale. При ручном `CHANGE MASTER TO` порядок: сначала `CHANGE MASTER TO`, затем `SET @@global.gtid_slave_pos`, затем `START SLAVE`. Репликам менять ничего не нужно.

**Важно:** даже при `select_master=true` позицию `@@global.gtid_slave_pos` нужно задавать явно, если на Primary purge'лись бинлоги — поток с самого начала доступен, только пока на Primary есть первый файл.

## Шаг 4: Galera-источник

```ini
# На каждом узле Galera
[mariadb]
log_slave_updates = ON
log_bin = pinloki
gtid_domain_id = 1001   # уникален на каждом узле
binlog_format = ROW

[galera]
wsrep_on = ON
wsrep_gtid_mode = ON
wsrep_gtid_domain_id = 42   # одинаков на всех узлах
```

Конфигурация binlogrouter та же, но `select_master=true` обязателен, а монитор — `galeramon`.

## Шаг 5: Ручное управление файлами

Обычно в `datadir` менять ничего не нужно; некорректные изменения вызывают сбои. До версии 23.08 изменения запрещены категорически, кроме bootstrap.

```bash
mariadb -u USER -p -h maxscale-IP -P 3306

# Список файлов и размеров (отличаются от таковых на Primary)
SHOW BINARY LOGS;

# Позиция, куда пишется следующий event (имя/позиция — свои, не Primary)
SHOW MASTER STATUS;

# Ручная purge (останавливается на файле, который читает подключённая реплика)
PURGE BINARY LOGS TO 'binlog.000123';

# Текущий GTID
SELECT @@gtid_slave_pos;

# Ручная компрессия любого файла, кроме последнего (MaxScale 24.02+)
zstd --rm -z binlog.001234
```

Права ручного вмешательства:

*   Удалять файлы вручную — в порядке создания, от меньшего номера к большему; предпочтительнее авто-purge через конфигурацию.
*   Файлы из архива копируются обратно в обратном порядке (от большего к меньшему); после истечения `expire_log_duration` они будут заархивированы снова. Автоматического способа использовать архивные файлы нет — только копирование обратно.
*   Не оставлять разрывов в нумерации; сохранять имена файлов при копировании; не копировать поверх существующих.
*   `PURGE { BINARY | MASTER } LOGS TO <filename>`: файл должен быть из `SHOW BINARY LOGS`; форма с timestamp не поддерживается; purge идёт в порядке создания и останавливается на файле, который читается репликой. MaxScale обнаруживает занятость файла только когда реплика подключена и запрашивает из него события — потенциально нужный файл всё равно не трогайте.

## Шаг 6: Поддерживаемый SQL

`CHANGE MASTER TO` — синтаксис как у MariaDB, но только значения: `MASTER_HOST`, `MASTER_PORT`, `MASTER_USER`, `MASTER_PASSWORD`, `MASTER_USE_GTID`, `MASTER_SSL`, `MASTER_SSL_CA`, `MASTER_SSL_CAPATH`, `MASTER_SSL_CERT`, `MASTER_SSL_CRL`, `MASTER_SSL_CRLPATH`, `MASTER_SSL_KEY`, `MASTER_SSL_CIPHER`, `MASTER_SSL_VERIFY_SERVER_CERT`. `MASTER_LOG_FILE`/`MASTER_LOG_POS` не поддерживаются.

Далее: `STOP SLAVE`, `START SLAVE`, `RESET SLAVE` (без `ALL`), `SHOW BINARY LOGS`, `PURGE { BINARY | MASTER } LOGS TO`, `SHOW MASTER STATUS`, `SHOW SLAVE STATUS`, `SET @@global.gtid_slave_pos`, `SHOW VARIABLES LIKE '...'`.

**`SHOW SLAVE STATUS`** — формат как у обычной реплики, но часть значений — неизменяемые константы. Реальные (меняются) поля:

| Поле | Значение |
| :--- | :--- |
| `Slave_IO_State` | `Waiting for primary to send event` при работающей репликации |
| `Master_Host` | адрес текущего Primary |
| `Master_User` | пользователь репликации |
| `Master_Port` | порт Primary |
| `Master_Log_File` | последний файл, в который пишет binlogrouter |
| `Read_Master_Log_Pos` | позиция последнего записанного события |
| `Slave_IO_Running` / `Slave_SQL_Running` | `Yes`/`No` |
| `Exec_Master_Log_Pos` | то же, что `Read_Master_Log_Pos` |
| `Gtid_IO_Pos` | последний реплицированный GTID |

**`SELECT`** — реальные значения возвращаются для: `@@gtid_slave_pos`, `@@gtid_current_pos`, `@@gtid_binlog_pos` (все три — последний реплицированный GTID), `version()`/`@@version`, `UNIX_TIMESTAMP()`. Остальные запрашиваемые переменные — фиксированные константы: `@@version_comment` = `pinloki`, `@@global.gtid_domain_id` = `0`, `@master_binlog_checksum` = `CRC32`, `@@session.auto_increment_increment` = `1`, `@@character_set_client/connection/results` = `utf8`, `@@character_set_server` = `utf8mb4`, `@@collation_server` = `utf8mb4_general_ci`, `@@collation_connection` = `utf8_general_ci`, `@@init_connect` = `""`, `@@interactive_timeout`/`@@wait_timeout` = `28800`, `@@license` = `BSL`, `@@lower_case_table_names` = `0`, `@@max_allowed_packet` = `16777216`, `@@net_write_timeout` = `60`, `@@performance_schema` = `0`, `@@query_cache_size` = `1048576`, `@@query_cache_type` = `OFF`, `@@sql_mode` = `""`, `@@system_time_zone` = `UTC`, `@@time_zone` = `SYSTEM`, `@@tx_isolation` = `REPEATABLE-READ`. Неизвестное поле возвращается как есть.

**`SHOW VARIABLES LIKE '...'`** — `LIKE` обязателен (без него не поддерживается) и работает только на точное совпадение; возвращаются `gtid_slave_pos`, `gtid_current_pos`, `gtid_binlog_pos` и `server_id`.

## Шаг 7: Шифрование бинлогов

```ini
# Глобально: ключевой менеджер (file-based)
key_manager=file
file.keyfile=/etc/maxscale/keyfile

[Replication-Proxy]
...
encryption_key_id=binlog-key-1
# encryption_cipher=AES_GCM   # default
```

*   Ключ с заданным ID должен присутствовать в `key_manager`; при versioning ключей новые бинлоги шифруются последней версией, старые остаются на своих версиях и читаются, пока эти версии доступны.
*   После включения шифрования сменить `encryption_key_id` нельзя; ключ и key manager должны оставаться доступны — иначе репликация от выбранного Primary остановится (повторный запуск повторит попытку получения ключа).
*   Перешифровать бинлоги другим ключом нельзя напрямую; это возможно через второй MaxScale с другим ключом (тоже и способ расшифровки).

## Шаг 8: CDC в Exasol по ODBC (MaxScale 25.10.3+)

Кроме раздачи бинлогов репликам, binlogrouter может применять прочитанные изменения к базе Exasol по ODBC: зафиксированные транзакции уплотняются, батчами загружаются в staging-таблицы и применяются `MERGE` в GTID-порядке; репликация асинхронна. Требуется пакет `maxscale-exasol`. CDC включается непустым `odbc_connection_str`; при пустом строке все остальные `odbc_*` игнорируются. Пользователь в строке соединения создаёт staging-таблицы, мержит и дропает их — нужны привилегии на DDL в целевых схемах.

| Параметр | Тип | Default | Описание |
| :--- | :--- | :--- | :--- |
| `odbc_connection_str` | string | `""` | ODBC-строка; непустое значение включает CDC. Ссылка на драйвер через `current`-symlink (`DRIVER=/usr/lib64/maxscale/exasol/current/lib/libexaodbc.so`) сохраняет работоспособность при обновлениях |
| `odbc_include_tables` | stringlist | `""` | `schema.table` для репликации; пусто — все таблицы |
| `odbc_insert_only_tables` | stringlist | `""` | таблицы только на INSERT (UPDATE/DELETE дропаются); подключается независимо от `odbc_include_tables`; схема с такой таблицей защищена от `DROP SCHEMA` |
| `odbc_case` | enum | `keep` | `keep`/`sensitive`/`insensitive` — сравнение идентификаторов целевой БД (`sensitive`/`insensitive` выполняют `ALTER SYSTEM SET SQL_IDENTIFIER_COMPARISON` — системное изменение на всём Exasol) |
| `odbc_create_table_from_sql` | boolean | `false` | создавать таблицу сразу по `CREATE TABLE`; иначе лениво из первого row-event |
| `odbc_stop_on_error` | boolean | `true` | останавливать CDC на неудачной транзакции (true — видно расхождение; false — pipeline живёт, но Exasol расходится) |
| `odbc_manage_user_grants` | boolean | `false` | реплицировать пользователей и гранты (включает `odbc_create_table_from_sql`) |
| `odbc_perf_ncycles` | count 1–4 | `4` | параллельных циклов bulk-load (столько же staging-таблиц); `1` — сериализует загрузку |
| `odbc_perf_max_buffered_rows` | count | `750000` | порог строк для отправки batch |
| `odbc_perf_max_idle_rows` | count | `400000` | нижний порог при простое pipeline; `0` отключает idle-триггер |
| `odbc_perf_batch_size` | size | `200Mi` | максимальный размер batch в wire-формате; большие батчи дробятся |
| `odbc_perf_nthreads` | count | `0` | лимит потоков CDC; `0` — без лимита |

Все `odbc_*` — не dynamic: вступают в силу только после перезапуска MaxScale, даже при изменении через `maxctrl alter service`. GTID-позиция CDC сохраняется, поэтому после рестарта репликация продолжается с места остановки.

## Шаг 9: Системные лимиты (inotify)

binlogrouter использует inotify. Проверьте и при необходимости поднимите лимиты:

```bash
sysctl fs.inotify.max_user_instances
# → 128 (default) — удвоить-утроить для binlogrouter
sudo sysctl -w fs.inotify.max_user_instances=512
```

`max_queued_events` и `max_user_watches` обычно достаточны; разумно удвоить вместе с `max_user_instances`.

## Шаг 10: Обновление с legacy-версий (<2.5)

Binlogrouter не читает данные, сохранённые версией ниже 2.5; по умолчанию он запрашивает поток с «пустого» состояния (с начала времён) — для живой системы это непригодно. Метод с минимальным даунтаймом (новый MaxScale ≥2.5 уже готов):

1.  Переключите реплики напрямую на Primary (`STOP SLAVE; CHANGE MASTER TO master_host="primary-IP", ...; START SLAVE;`).
2.  Остановите старый MaxScale, запустите новый; проверьте работоспособность.
3.  Выдайте `CHANGE MASTER TO` к binlogrouter или включите `select_master`.
4.  `maxctrl list servers` — убедитесь, что все серверы на месте; выберите минимальный GTID среди отображаемых и задайте его binlogrouter: `STOP SLAVE; SET @@global.gtid_slave_pos = "0-1000-1234,1-1001-5678"; START SLAVE;`.
5.  Верните реплики на binlogrouter (Шаг 2).

Убедитесь, что `datadir` нового binlogrouter отличается от старого (или старые данные убраны). Если на Primary purge'лись бинлоги — `@@global.gtid_slave_pos` задаётся явно даже при `select_master=true`.

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Реплики не подключаются | `master_use_gtid=slave_pos` не указан | binlogrouter только GTID: используйте `master_use_gtid=slave_pos` |
| `CHANGE MASTER TO` с `MASTER_LOG_FILE` отвергнут | Не поддерживается | Используйте GTID-позицию |
| Реплика запрашивает GTID, которого нет в бинлогах MaxScale | Бинлоги purge'лись или bootstrap с неполной историей | Bootstrap с позиции из `maxctrl list servers` (минимальный GTID) или переподключение к Primary с полной историей |
| Репликация остановилась после purge | Удалён файл, нужный реплике | Авто-purge останавливается на читаемом файле; для ручной purge проверяйте `SHOW BINARY LOGS` и подключённых реплик |
| Авто-purge/archive остановились раньше срока | Файл читается подключённой репликой | Это защита: MaxScale видит занятость, только когда реплика подключена и запрашивает события; увеличьте `expire_log_duration`/`expire_log_minimum_files` |
| Поля `SHOW SLAVE STATUS` не меняются | Это константы binlogrouter | Не баг: реальные поля перечислены в Шаг 6; мониторьте `Gtid_IO_Pos` |
| `SHOW VARIABLES` без `LIKE` отвергнут | `LIKE` обязателен и только точное совпадение | Используйте `SHOW VARIABLES LIKE 'gtid_slave_pos'` |
| MaxScale не стартует после правки datadir | Разрыв нумерации или повреждённый `binlog.index` | Восстановите нумерацию или bootstrap (Шаг 3) |
| inotify-ошибки в логах | Исчерпан `fs.inotify.max_user_instances` | Поднимите лимит (Шаг 9) |
| `auto_rejoin` ломает binlogrouter | mariadbmon шлёт неподдерживаемые команды | Отключите `auto_rejoin` для монитора, наблюдающего binlogrouter |
| Архив не пишется | `archivedir` не существует при старте | Создайте директорию до старта MaxScale; проверьте права пользователя maxscale |
| Репликация остановилась после включения `encryption_key_id` | Ключ недоступен в key manager | Верните ключ в key manager; рестарт повторит попытку; сменить `encryption_key_id` нельзя |
| `PURGE BINARY LOGS BEFORE '...'` не работает | Форма с timestamp не поддерживается | Только `PURGE BINARY LOGS TO '<файл>'` |

## Best Practices

1.  **`select_master=true` + mariadbmon** — автоматический выбор Primary и прозрачный switchover для реплик.
2.  **`expiration_mode=archive`** вместо purge, если бинлоги нужны для аудита/восстановления; архив на отдельной ФС.
3.  **`compression_algorithm=zstandard`** — экономия диска; последние `number_of_noncompressed_files` файлов остаются несжатыми.
4.  **`expire_log_duration`** — исходите из максимального простоя реплики: файл должен пережить самый длинный даунтайм.
5.  **Не трогайте `datadir` вручную** без крайней необходимости; для сброса позиции — bootstrap.
6.  **Semi-sync на источнике** + `rpl_semi_sync_slave_enabled=true` — меньше потерь при failover.
7.  **`ddl_only=true`** — лёгкий способ трекинга DDL и быстрого поднятия пустого узла.
8.  **Уникальный `server_id`** в топологии репликации; для контроля лага сравнивайте `Gtid_IO_Pos` binlogrouter (`SHOW SLAVE STATUS`) с GTID на Primary.
9.  **Шифрование бинлогов** — только при готовности держать key manager и ключ доступными постоянно: без ключа репликация останавливается, а сменить ключ ID после включения нельзя.

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — общая архитектура.
*   **[Failover и Switchover](./maxscale_failover.md)** — mariadbmon и switchover для binlogrouter.
*   **[Репликация MariaDB](../replication/overview.md)** — GTID, классическая репликация.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera и HA.
*   **[Binlogrouter (официальная справка)](https://mariadb.com/docs/maxscale/reference/maxscale-routers/maxscale-binlogrouter.md)** — эталонный список параметров и SQL.
