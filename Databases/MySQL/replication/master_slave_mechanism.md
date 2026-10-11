# Механизм репликации в MySQL

**Актуально для:** MySQL 5.1+ / 5.7 / 8.0+ / 8.4 LTS

## Определения

**Репликация Source-Replica** — процесс автоматического копирования данных с основного сервера (**Источник / Source**) на один или несколько дополнительных серверов (**Реплика / Replica**).

**Потоки репликации (Replication Threads)** — системные процессы уровня ОС/СУБД, обеспечивающие передачу, буферизацию и применение событий бинарного лога.

**Replication Handshake** — начальная фаза установления соединения, на которой проверяются версии серверов, UUID, права доступа и согласовываются параметры (например, поддержка сжатия или GTID).

**Heartbeat Packet** — контрольный пакет, отправляемый источником реплике в периоды отсутствия новых данных. Позволяет реплике вовремя обнаружить разрыв соединения, не дожидаясь системного таймаута TCP.

**MTS (Multi-Threaded Slave)** — архитектура на стороне реплики, позволяющая применять транзакции параллельно силами нескольких рабочих потоков.

**Relay Log (Журнал ретрансляции)** — промежуточный набор файлов на стороне реплики, играющий роль буфера между получением данных из сети и их записью в базу данных.

## Предварительные требования

### ОС и ядро

- **Файловые дескрипторы:** `ulimit -n` должен быть не менее 65535 на источнике и реплике. Каждое сетевое соединение и файл лога consumes один дескриптор.
- **Потоки (Threads):** Каждый binlog dump thread на источнике и каждый I/O/SQL thread на реплике consumes системный поток. Убедитесь, что `pthread` limits не ограничивают создание дополнительных потоков.
- **Transparent Huge Pages (THP):** Отключите THP на всех узлах (`echo never > /sys/kernel/mm/transparent_hugepage/enabled`). THP causes fragmentation и замедляет запись Relay Log.
- **I/O Scheduler:** Для дисков с репликацией рекомендуется `deadline` или `noop` scheduler, если используется внешний RAID-контроллер с собственным кэшем.

### Сеть и TCP-стек

- **Порт 3306:** Открыт между источником и репликой. Проверьте файрволы (`iptables`/`nftables`/`firewalld`) и security groups.
- **TCP Keepalive:** Настройте `net.ipv4.tcp_keepalive_time = 60`, `tcp_keepalive_intvl = 10`, `tcp_keepalive_probes = 6`. Это позволяет оперативнее обнаруживать "мертвые" соединения, чем стандартный `replica_net_timeout` (60 секунд).
- **Размер буферов TCP:** Для высоконагруженных каналов увеличьте `net.core.rmem_default`, `net.core.wmem_default`, `net.ipv4.tcp_rmem`, `net.ipv4.tcp_wmem`. Размер буфера должен превышать `max_binlog_size` (по умолчанию 1 ГБ) для избежания пауз в передаче.
- **Время:** NTP или chrony настроен на всех узлах; максимальное расхождение < 100 мс. Дрожание clock skew искажает временные метки binlog и ломает мониторинг лага.

### Ресурсы и хранилище

- **Память:** Каждый replication thread consumes ~256 КБ стека. Для MTS с 16 воркерами Reserve ~4 МБ дополнительной памяти. Буферы `binlog_cache_size` и `replica_pending_jobs_size_max` (на MySQL 5.7 и раньше — `slave_pending_jobs_size_max`) также требуют памяти.
- **Диск:** Relay Log должен размещаться на устройстве с низким latency (< 5 мс). Если источник и реплика разделяют диск, concurrent I/O от других процессов может заблокировать запись Relay Log.
- **CPU:** MTS workers могут создавать значительную нагрузку на CPU при применении сложных DML. Убедитесь, что на реплике достаточно ядер для `replica_parallel_workers` плюс одна ядро на координатора.

### Зависимости

- **Percona Toolkit:** `pt-table-checksum` и `pt-table-sync` для проверки консистентности данных.
- **Performance Schema:** Включена по умолчанию в MySQL 8.0+. На 5.7 может потребоваться `performance_schema = ON` в `my.cnf`.
- **mysqlbinlog:** Утилита входит в дистрибутив MySQL, требуется для анализа и PITR.

## Основные концепции

### Архитектура и жизненный цикл события

Репликация в MySQL работает на основе логической передачи событий. Весь путь транзакции от `COMMIT` до применения на реплике состоит из следующих этапов:

1.  **Фиксация (Source):** Транзакция завершается на источнике. События записываются в **Binary Log**.
2.  **Считывание (Dump Thread):** Источник считывает события из бинлога. Если используется GTID, используется протокол `COM_BINLOG_DUMP_GTID`, позволяющий источнику самому определить недостающие транзакции на основе присланного репликой набора `gtid_executed`.
3.  **Передача (Network):** События упаковываются в пакеты и отправляются по TCP. Если включено сжатие (`binlog_transaction_compression`), данные передаются в сжатом виде (ZSTD).
4.  **Буферизация (Receiver / I/O Thread):** На реплике поток I/O принимает пакеты и немедленно записывает их в **Relay Log**. Это минимизирует время удержания сетевого ресурса.
5.  **Координация (Coordinator):** SQL-поток считывает Relay Log, анализирует метаданные зависимостей (Writesets) и решает, какому воркеру назначить транзакцию.
6.  **Применение (Workers):** Потоки воркеров выполняют SQL-команды или изменяют строки в локальной БД.

### Типы и состояния потоков репликации

| Поток | Расположение | Описание и типичные состояния |
| :--- | :--- | :--- |
| **Binlog Dump** | Источник | Читает бинлог и шлет события. Состояние `Sending binlog event` означает активную передачу. |
| **Replica I/O** | Реплика | Отвечает за сеть. Состояние `Waiting for master to send event` означает, что соединение живо, но данных нет. |
| **Replica SQL** | Реплика | Координатор в MTS. Читает Relay Log и раздает задачи воркерам. |
| **Workers** | Реплика | (Только MTS) Потоки, непосредственно пишущие данные. Состояние `Executing event` — активная работа. |

### Параллельная репликация (MTS) и WRITESET

Для ускорения применения данных MySQL 8.0 использует механизм **Writesets**.
- **Принцип:** При записи транзакции в бинлог источник вычисляет хеш (XXHASH64) первичных ключей всех затронутых строк.
- **Dependency Tracking:** Если две транзакции меняют разные строки (разные хеши), они помечаются как "независимые".
- **Результат:** Реплика может выполнять такие транзакции одновременно, даже если на источнике они шли последовательно. Это кардинально решает проблему лага на нагруженных системах.

**Настройка на источнике (MySQL 5.7 — 8.2):**
```ini
binlog_transaction_dependency_tracking = WRITESET
transaction_write_set_extraction = XXHASH64
```

> **Версии:** `binlog_transaction_dependency_tracking` объявлена устаревшей в MySQL 8.2.0 и **удалена в 8.4.0**, `transaction_write_set_extraction` **удалена в 8.3.0**. На MySQL 8.4 LTS эти параметры в `my.cnf` не указываются — указание приведёт к ошибке запуска.

Настройка MTS на реплике (режим группировки, число воркеров, дефолты по версиям, мониторинг) — в `parallel_replication_mts.md`.

### Полусинхронная репликация (Semisync)

В стандартном асинхронном режиме источник не ждет подтверждения: он пишет событие в binlog, отправляет реплике и сразу отвечает клиенту. Если источник падает сразу после этого, подтверждённая клиенту транзакция может не попасть ни в одну реплику — и данные теряются вместе с недоступным источником.

Semisync вводит фазу ожидания **ACK** от реплики: источник не отвечает клиенту, пока реплика не подтвердит получение события.

**Механизм подтверждения (Wait Points):**
1.  **AFTER_SYNC (Рекомендуемый):**
    - Клиент делает `COMMIT`.
    - Источник пишет в binlog и отправляет данные реплике.
    - Источник **ждет** ACK.
    - Реплика пишет в Relay Log и отправляет ACK.
    - Источник фиксирует данные в Storage Engine и отвечает клиенту.
    - *Плюс:* Полная сохранность данных при падении источника — транзакция гарантированно попала в binlog реплики.
2.  **AFTER_COMMIT (Legacy):**
    - Источник сначала фиксирует данные локально, а затем ждет ACK.
    - *Риск:* Другие клиенты могут увидеть данные, которых не окажется на реплике при Failover.

**Что semisync гарантирует и что не гарантирует.** ACK отправляется после записи события в relay log реплики, но **до** его применения в таблицы (`relay_log_recovery` и `innodb_flush_log_at_trx_commit` на реплике здесь ни при чём). Поэтому semisync — это защита от потери данных при отказе источника, а не замена бэкапам и не гарантия актуальности чтения с реплики. Реплика, дающая ACK, может быть уничтожена или потеряна вместе с источником до применения события.

**Установка плагинов (MySQL 8.0.26+):**

```sql
-- На источнике: проверить, что динамическая загрузка доступна
SHOW VARIABLES LIKE 'have_dynamic_loading';   -- → YES

-- На источнике
INSTALL PLUGIN rpl_semi_sync_source SONAME 'semisync_source.so';

-- На каждой реплике
INSTALL PLUGIN rpl_semi_sync_replica SONAME 'semisync_replica.so';
```

Требования и ограничения:

- Репликация **уже должна работать** — semisync не настраивается «с нуля».
- На инстансе нельзя одновременно установить старые (`rpl_semi_sync_master` / `rpl_semi_sync_slave`) и новые (`rpl_semi_sync_source` / `rpl_semi_sync_replica`) плагины. Набор доступных системных переменных зависит от установленной версии: со старыми плагинами недоступны переменные с `source`/`replica` в имени, и наоборот.
- Полусинхронный режим работает **только с каналом по умолчанию** (канал с пустым именем `""`). Multi-source с именованными каналами semisync не поддерживает — см. [multi-source.md](multi-source.md#3-полусинхронная-репликация-и-каналы).
- После установки `INSTALL PLUGIN` требуется привилегия `REPLICATION_SLAVE_ADMIN`.

**Включение.** После установки плагины выключены по умолчанию. Если включена только одна сторона, репликация остаётся асинхронной.

```sql
-- На источнике
SET GLOBAL rpl_semi_sync_source_enabled = 1;

-- На реплике
SET GLOBAL rpl_semi_sync_replica_enabled = 1;

-- Перезапуск потоков обязателен: настройки читаются при старте канала
STOP REPLICA;
START REPLICA;
```

Для постоянства настройки продублируйте в `my.cnf` — тогда она переживёт рестарт (в отличие от `SET GLOBAL`, который сбрасывается):

```ini
[mysqld]
rpl_semi_sync_source_enabled=1     # на источнике
rpl_semi_sync_replica_enabled=1    # на реплике
```

**Ключевые параметры источника** (`rpl_semi_sync_source_*`, доступны только при установленном плагине `rpl_semi_sync_source`):

| Параметр | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `rpl_semi_sync_source_enabled` | `OFF` | Включение режима на источнике |
| `rpl_semi_sync_source_timeout` | `10000` мс | Сколько ждать ACK, прежде чем **деградировать до асинхронного** режима и продолжить коммит |
| `rpl_semi_sync_source_wait_point` | `AFTER_SYNC` | `AFTER_SYNC` или `AFTER_COMMIT` (см. выше) |
| `rpl_semi_sync_source_wait_for_replica_count` | `1` | Сколько ACK нужно для успешного коммита (диапазон 1–65535) |
| `rpl_semi_sync_source_wait_no_replica` | `ON` | Ждать ли таймаут, если число реплик упало ниже `wait_for_replica_count`; при `OFF` — немедленный откат в async |
| `rpl_semi_sync_source_trace_level` | `32` | Битмаска трассировки (уровни 1, 16, 32, 64), диагностика пишется в error log |

Полное описание переменных, статусных счётчиков и сценариев — **[Полусинхронная репликация](./semi-sync-replication.md)** (основной файл по теме).

**Параметры реплики:**

| Параметр | Назначение |
| :--- | :--- |
| `rpl_semi_sync_replica_enabled` | Включение режима на реплике |
| `rpl_semi_sync_replica_trace_level` | Битмаска трассировки (по умолчанию `32`; уровни 1, 16, 32, 64), диагностика пишется в error log |

**Проверка работоспособности:**

```sql
-- На источнике: Rpl_semi_sync_source_status = 1 означает, что полусинхронный
-- режим работает сейчас (плагин включён и источник не откатился в async)
SHOW STATUS LIKE 'Rpl_semi_sync%';

-- Типичный результат при работе
-- Rpl_semi_sync_source_status              1
-- Rpl_semi_sync_source_yes_tx             1520341
-- Rpl_semi_sync_source_no_tx                    0
-- Rpl_semi_sync_source_clients                  1
```

Что означают счётчики:

- `Rpl_semi_sync_source_yes_tx` — число коммитов, подтверждённых репликой;
- `Rpl_semi_sync_source_no_tx` — число коммитов, которые **не дождались** ACK за `timeout` и ушли в асинхронный режим. Ненулевое и растущее значение — первый признак деградации semisync в async;
- `Rpl_semi_sync_source_clients` — число подключённых полусинхронных реплик;
- `Rpl_semi_sync_source_no_times` — число переключений источника в асинхронный режим;
- `Rpl_semi_sync_source_tx_avg_wait_time` — среднее время ожидания транзакции, мкс.

> **Имена с префиксами `master`/`slave`** (`rpl_semi_sync_master_*`, `rpl_semi_sync_slave_*`, плагины `rpl_semi_sync_master` / `rpl_semi_sync_slave`) появились раньше и **deprecated** начиная с MySQL 8.0.26. Планируя перенос конфигурации на 8.4 LTS, переводите её на новые имена — старые объявлены к удалению.

## Практические сценарии

### Мониторинг состояний и таймаутов

Для детальной инспекции работы потоков используйте **Performance Schema**:

```sql
-- Проверка сетевых задержек на уровне I/O потока
SELECT 
    CHANNEL_NAME, 
    LAST_HEARTBEAT_TIMESTAMP, 
    SERVICE_STATE 
FROM performance_schema.replication_connection_status;

-- Инспекция очередей координатора MTS
SELECT 
    WORKER_ID, 
    THREAD_ID, 
    LAST_APPLIED_TRANSACTION 
FROM performance_schema.replication_applier_status_by_worker;
```

### Тюнинг пропускной способности

При возникновении задержек в передаче данных проверьте следующие параметры:
- **`replica_net_timeout`:** (По умолчанию 60с, на MySQL 5.7 и раньше — `slave_net_timeout`) Как долго реплика ждет данных от источника перед тем, как признать соединение разорванным и переподключиться. В нестабильных сетях с частыми краткими обрывами значение следует **увеличивать**, а не уменьшать: слишком малое значение заставит реплику отключаться и переподключаться на каждом коротком затишье в потоке.
- **`replica_parallel_workers`:** Начать с 4, повысить до числа ядер CPU реплики (методика — `parallel_replication_mts.md`).

### Настройка Crash-Safety механизма

Для обеспечения выживаемости репликации при сбоях (Power Loss):
```ini
[mysqld]
# Автоматическое перескачивание логов при запуске
relay_log_recovery = ON

# Гарантированная синхронизация Relay Log
sync_relay_log = 1
```

> **Версии:** Хранение метаданных репликации в транзакционных таблицах (`master_info_repository = TABLE`, `relay_log_info_repository = TABLE`) — в MySQL 5.6/5.7 задаётся явно (дефолт `FILE`), с MySQL 8.0 — поведение по умолчанию (deprecated с 8.0.23). Обе переменные **удалены в MySQL 8.3.0** и на 8.4 LTS не настраиваются. Детали — `relay_logs_crashsafe.md`.

## Валидация

### Проверка handshake и соединения

```sql
-- Проверка прав пользователя репликации
SHOW GRANTS FOR 'repl_user'@'%';

-- Проверка server_uuid на источнике и реплике
SELECT @@server_uuid;

-- Проверка SSL-соединения (если используется)
SHOW STATUS LIKE 'Ssl_cipher';
```

### Валидация потоков репликации

```sql
-- Подсчет потоков на источнике (Binlog Dump)
SHOW STATUS LIKE 'Binlog%';
SHOW PROCESSLIST WHERE COMMAND = 'Binlog Dump';

-- Подсчет потоков на реплике (I/O и SQL)
SHOW PROCESSLIST WHERE USER = 'system user';

-- Проверка состояния каналов
SELECT CHANNEL_NAME, SERVICE_STATE 
FROM performance_schema.replication_connection_status;
```

### Валидация MTS и Writesets

Проверка числа воркеров, режима группировки и их состояния — в `parallel_replication_mts.md` (раздел «Валидация настройки»).

> **Версии:** Проверить `binlog_transaction_dependency_tracking` и `transaction_write_set_extraction` через `SHOW VARIABLES` имеет смысл только до MySQL 8.2 / 8.3 соответственно — далее эти переменные удалены и `SHOW VARIABLES` не вернёт строк.

### Валидация Relay Log

```bash
# Проверка целостности Relay Log (если реплика остановлена)
mysqlbinlog --verify-binlog-checksum /var/lib/mysql/relay-bin.000001
```

```sql
-- Состояние координатора MTS (отдельно от проверки контрольных сумм)
SELECT * FROM performance_schema.replication_applier_status_by_coordinator;
```

## Устранение неисправностей

### Сбой Handshake при подключении реплики

- **Симптом:** `Replica_IO_Running: Connecting`, `Last_IO_Error: error connecting to source`.
- **Причины:** Неверные права, несовпадение версий MySQL, блокировка порта файрволом, SSL-ошибка.
- **Решение:**
  1. Проверьте пользователя: `SELECT user, host FROM mysql.user WHERE user = 'repl';`.
  2. Проверьте права: `SHOW GRANTS FOR 'repl'@'replica_host';`.
  3. Проверьте сеть: `nc -zv source_host 3306`.
  4. Проверьте SSL: `SHOW STATUS LIKE 'Ssl_cipher';`.

### Binlog Dump Thread не отправляет события

- **Симптом:** На источнике `SHOW PROCESSLIST` показывает `Binlog Dump` в состоянии `Has sent all binlog to slave; waiting for binlog to be updated`, но реплика не получает новые данные.
- **Причины:**
  - На источнике нет новых транзакций (idle source).
  - Сетевая блокировка (пакет `tcp_keepalive` не проходит).
  - `max_binlog_size` достигнут, но новая ротация не запускается (нет активных транзакций).
- **Решение:**
  1. Проверьте активность на источнике: `SHOW BINARY LOG STATUS;`.
  2. Проверьте сеть: `tcpdump -i eth0 host replica_host and port 3306`.
  3. Проверьте `binlog_expire_logs_seconds` — возможно, старые логи удалены, а реплика запрашивает несуществующий файл.

### MTS: Coordinator зависает, воркеры бездействуют

Симптом (`Seconds_Behind_Source` растёт при `Replica_SQL_Running: Yes`, воркеры бездействуют), причины (режим `DATABASE` при одной БД, длинная транзакция/DDL в очереди координатора) и пошаговое решение — в `parallel_replication_mts.md` (раздел «Типичные проблемы и решения»).

### Relay Log поврежден после аварии

- **Симптом:** `Replica_SQL_Running: No`, `Last_SQL_Error: Relay log read failure: unexpected end of log file`.
- **Причина:** Аварийное выключение (power loss, OOM kill, `kill -9`) привело к частичной записи Relay Log.
- **Решение:**
  1. Убедитесь, что `relay_log_recovery = ON` в `my.cnf`.
  2. Перезапустите MySQL: `systemctl restart mysql`.
  3. Реплика автоматически удалит поврежденные Relay Logs и скачает их заново.
  4. Если `relay_log_recovery` выключен — вручную выполните `STOP REPLICA; RESET REPLICA; START REPLICA;`.

### Semisync: ACK timeout и лаг

- **Симптом:** клиенты ощущают дополнительные задержки на коммите (до `rpl_semi_sync_source_timeout` — по умолчанию 10 секунд), а `Seconds_Behind_Source` при этом растёт.
- **Диагностика — по счётчикам, а не по ощущениям:**
  ```sql
  SHOW STATUS LIKE 'Rpl_semi_sync%';
  ```
   Растущий `Rpl_semi_sync_source_no_tx` означает, что режим **деградировал в асинхронный**: источник перестал получать ACK вовремя и продолжает коммиты без подтверждения. Растёт также `Rpl_semi_sync_source_no_times` — число переключений в async.
- **Причины:**
  - `rpl_semi_sync_source_timeout` (по умолчанию 10000 мс) истёк.
  - Сетевая задержка (RTT) или потери превышают таймаут.
  - На реплике I/O-поток не может записать данные в relay log — диск переполнен или высокий I/O wait.
  - `rpl_semi_sync_source_wait_for_replica_count` выше, чем реальное число semisync-реплик, готовых подтвердить.
- **Решение:**
   1. Проверьте реальное число активных semisync-реплик и сопоставьте с `rpl_semi_sync_source_wait_for_replica_count`:
      ```sql
      SHOW STATUS LIKE 'Rpl_semi_sync_source_clients';
      SHOW STATUS LIKE 'Rpl_semi_sync_source_yes_tx';
      ```
  2. Проверьте диск на реплике: `df -h /var/lib/mysql`.
  3. Проверьте сеть между узлами: `mtr`, `iperf3`.
  4. Увеличьте `rpl_semi_sync_source_timeout` до 30000–60000 мс для гео-распределённых топологий **только если** рост таймаута не маскирует реальную проблему с сетью или диском.
  5. Увеличьте трассировку на реплике для деталей, например: `SET GLOBAL rpl_semi_sync_replica_trace_level = 48;` (битмаска уровней 1, 16, 32, 64; по умолчанию `32`, `0` — без диагностики).

### Heartbeat пропал, но соединение живо

- **Симптом:** `Seconds_Behind_Source` скачет или показывает `NULL`, хотя `Replica_IO_Running: Yes`.
- **Причина:** Источник перезагружался, и временные метки heartbeat сбросились. Или `SOURCE_HEARTBEAT_PERIOD` установлен некорректно.
- **Решение:**
  1. Проверьте `SOURCE_HEARTBEAT_PERIOD`: `SHOW VARIABLES LIKE 'heartbeat_period';`.
  2. Установите значение 30 секунд: `CHANGE REPLICATION SOURCE TO SOURCE_HEARTBEAT_PERIOD = 30;`.
  3. Используйте `pt-heartbeat` для независимого измерения лага.

### Дубликат UUID при инициализации реплики

- **Симптом:** `Fatal error: The slave I/O thread stops because source and slave have equal MySQL server UUIDs`.
- **Причина:** Реплика была создана физическим копированием диска источника, включая файл `auto.cnf`.
- **Решение:**
  1. Остановите MySQL на реплике.
  2. Удалите `auto.cnf` в data-директории.
  3. Запустите MySQL — новый UUID сгенерируется автоматически.
  4. Проверьте: `SELECT @@server_uuid;` на источнике и реплике — должны отличаться.

## Рекомендации

### Мониторинг и алертинг

- **Ключевые метрики:**
  - Количество Binlog Dump threads на источнике: `SHOW STATUS LIKE 'Binlog%';`.
  - Состояние I/O и SQL потоков: `SHOW REPLICA STATUS\G`.
  - Размер Relay Log: `du -sh /var/lib/mysql/relay-bin*`.
  - Состояние воркеров MTS: `performance_schema.replication_applier_status_by_worker`.
  - Задержка ACK в Semisync: `SHOW STATUS LIKE 'Rpl_semi_sync%';`.
- **Интервалы:** Для production-систем проверка каждые 30 секунд. Для стандартных — каждые 5 минут.
- **Инструменты:** Performance Schema (встроенный), Percona Monitoring and Management (PMM), Prometheus + Grafana с mysqld_exporter.

### Жесткое обеспечение безопасности и стабильности

- **Только ROW-формат:** Используйте `binlog_format = ROW` повсеместно. `STATEMENT` и `MIXED` несовместимы с Writesets и GTID-репликацией в сложных сценариях.
- **Crash-Safe репозитории:** В MySQL 8.0 параметры `master_info_repository` и `relay_log_info_repository` установлены в `TABLE` по умолчанию; в MySQL 5.7 установите их явно. Обе переменные вместе с опциями `--master-info-file` и `--relay-log-info-file` **удалены в MySQL 8.3.0** — на 8.4 LTS метаданные всегда хранятся в таблицах `mysql.slave_master_info` и `mysql.slave_relay_log_info`, настраивать ничего не нужно.
- **Отдельные диски:** Размещайте binlog, relay log и данные на отдельных физических устройствах. Это исключает contention и позволяет восстановить репликацию после заполнения одного из разделов.
- **Ограничение Relay Log:** Установите `relay_log_space_limit` (например, 10-20 ГБ) для предотвращения заполнения диска при остановке SQL-потока.
- **Права пользователя:** Используйте отдельного пользователя `repl_user` с минимальными правами (`REPLICATION SLAVE`, `REPLICATION CLIENT`). Никогда не используйте `root`.

### Процедурные рекомендации

- **TCP Keepalive:** Настройте `net.ipv4.tcp_keepalive_time = 60` на всех узлах для быстрого обнаружения разрывов.
- **Heartbeat:** Установите `SOURCE_HEARTBEAT_PERIOD = 30` для своевременного обнаружения проблем.
- **Semisync:** Используйте `AFTER_SYNC` для критичных данных. Увеличьте `rpl_semi_sync_source_timeout` для географически распределенных реплик.
- **MTS:** Начинайте с `replica_parallel_workers = 4`, увеличивайте до числа ядер CPU, но не более 16. `replica_parallel_type` должен быть `LOGICAL_CLOCK`.
- **Тестирование отказоустойчивости:** Регулярно проверяйте failover на тестовом стенде. Документируйте RTO и RPO.

### Автоматизация

```bash
#!/bin/bash
# Проверка состояния репликации
REPLICA_HOST="replica01"
MYSQL="mysql -h $REPLICA_HOST -u monitor -p'password' -e"

STATUS=$($MYSQL "SHOW REPLICA STATUS\G" 2>/dev/null | grep -E "Replica_IO_Running|Replica_SQL_Running|Seconds_Behind_Source" | head -3)

if echo "$STATUS" | grep -q "No"; then
    echo "CRITICAL: Replication thread is down on $REPLICA_HOST"
    # Отправка алерта в Slack/PagerDuty/Email
elif echo "$STATUS" | grep -q "NULL"; then
    echo "WARNING: Replication threads may be stopped on $REPLICA_HOST"
else
    echo "OK: Replication is running"
fi
```

### Настройка для production

- **`binlog_format = ROW`** — повсеместно. Обязателен для GTID и Group Replication.
- **`sync_binlog = 1`** — для максимальной надежности на источнике. На репликах можно `0` для производительности (если допустима потеря данных при сбое реплики).
- **`innodb_flush_log_at_trx_commit = 1`** — на источнике. На репликах `2` допустимо.
- **`relay_log_recovery = ON`** — обязательно для crash-safety.
- **`sync_relay_log = 1`** — если реплика критична для отказоустойчивости.
- **`replica_parallel_type = LOGICAL_CLOCK`** — единственный рекомендуемый режим MTS.
- **`SOURCE_HEARTBEAT_PERIOD = 30`** — для своевременного обнаружения разрывов.
- **`net.ipv4.tcp_keepalive_time = 60`** — на уровне ОС на всех узлах.

## Граничные случаи

### Failover во время длинной транзакции

- **Ситуация:** Источник падает посреди транзакции, длившейся 30 минут.
- **Механизм:** Транзакция не была зафиксирована, поэтому она не попала в binlog. Реплика не имеет частичного применения.
- **Решение:** Резервная реплика берет на себя роль источника. Если использовался Semisync AFTER_SYNC — данные гарантированно не потеряны, так как транзакция не была подтверждена клиенту.
- **Предупреждение:** Если использовался AFTER_COMMIT — возможна потеря последних незафиксированных транзакций.

### Сетевое разделение (Split Brain)

- **Ситуация:** Источник и реплика потеряли связь, но обе остались доступны для записи.
- **Механизм:** При восстановлении связи GTID-репликация автоматически определит расхождение и остановится с ошибкой 1236.
- **Решение:**
  1. Определите canonical источник (обычно тот, у кого больше данных).
  2. На реплике выполните `RESET REPLICA ALL; CHANGE REPLICATION SOURCE TO ...`.
  3. Если GTID не используется — возможна неконсистентность. Определите корректную позицию и перестройте репликацию.

### Очень большие транзакции (> 1 ГБ) и MTS

- **Ситуация:** Одна транзакция модифицирует миллионы строк.
- **Механизм:** В binlog записывается полное содержимое транзакции. MTS не может применить её параллельно, так как все строки зависят друг от друга. Координатор вынужден ждать завершения.
- **Решение:**
  1. Разбейте большие транзакции на батчи (по 10K–100K строк).
  2. Включите `binlog_transaction_compression = ON` для уменьшения объема.
  3. Увеличьте `net_read_timeout` и `net_write_timeout` на обеих сторонах.

### Источник перезагружается во время binlog dump

- **Ситуация:** Источник выполняет `FLUSH BINARY LOGS` или перезагружается, пока реплика скачивает большой binlog-файл.
- **Механизм:** Dump thread закрывает текущий файл и открывает новый. Реплика получает `ROTATE` event и начинает читать новый файл.
- **Решение:** Убедитесь, что `replica_net_timeout` меньше, чем время на перезагрузку источника. Иначе реплика попытается переподключиться и запросит позицию, которая уже не существует.

### Дрожание clock skew

- **Ситуация:** Системное время на реплике отстает или опережает время на источнике более чем на 1 секунду.
- **Механизм:** `Seconds_Behind_Source` рассчитывается как разница между `timestamp` события в binlog и системным временем реплики. При clock skew показатель становится некорректным.
- **Решение:**
  1. Настройте NTP на обеих машинах: `systemctl enable --now chronyd`.
  2. Проверьте синхронизацию: `chronyc tracking`.
  3. После синхронизации перезапустите репликацию: `STOP REPLICA; START REPLICA;`.

### Переход с File:Pos на GTID

- **Ситуация:** Необходимо мигрировать существующую репликацию на GTID без остановки продакшена.
- **Механизм:** MySQL поддерживает смешанный режим (`gtid_mode = ON_PERMISSIVE` / `OFF_PERMISSIVE`), но он нестабилен и не поддерживает автоматический failover.
- **Решение:**
  1. На источнике: `SET GLOBAL gtid_mode = ON_PERMISSIVE; SET GLOBAL enforce_gtid_consistency = ON;`.
  2. На реплике: выполните те же команды.
  3. Дождитесь применения всех транзакций: `SHOW REPLICA STATUS\G`.
  4. На источнике: `SET GLOBAL gtid_mode = ON;`.
  5. На реплике: `SET GLOBAL gtid_mode = ON;`.
  6. На реплике: `CHANGE REPLICATION SOURCE TO SOURCE_AUTO_POSITION = 1; START REPLICA;`.
  7. Мониторьте `gtid_executed` и `gtid_purged` на обеих сторонах.

### Повреждение binlog на источнике во время dump

- **Ситуация:** Бинарный лог на источнике поврежден (сбой диска, bit rot), и реплика получает некорректные события.
- **Механизм:** `mysqlbinlog --verify-binlog-checksum` обнаруживает несоответствие CRC32. Реплика падает с ошибкой 1236.
- **Решение:**
  1. На источнике: `mysqlbinlog --verify-binlog-checksum /var/lib/mysql/binlog.000001`.
  2. Если файл поврежден — `PURGE BINARY LOGS TO 'mysql-bin.0000XX';` (убедитесь, что реплики не требуют этот файл).
  3. На реплике: `STOP REPLICA; RESET REPLICA ALL; CHANGE REPLICATION SOURCE TO ...; START REPLICA;`.

## Очистка и откат

### Безопасный сброс репликации

```sql
-- Полный сброс (удаляет все метаданные репликации, Relay Logs и GTID-выполненные транзакции)
RESET REPLICA ALL;

-- Частичный сброс (сохраняет GTID, удаляет только Relay Log и метаданные)
RESET REPLICA;
```

**Когда использовать:**
- `RESET REPLICA ALL` — при полной переконфигурации репликации, изменении источника, переходе с GTID на не-GTID или наоборот.
- `RESET REPLICA` — при очистке Relay Log без смены источника.

**Предупреждение:** `RESET REPLICA ALL` удаляет `gtid_executed` на реплике. Если реплика имеет собственные транзакции, они будут потеряны.

### Очистка Relay Log

```sql
-- Остановка репликации
STOP REPLICA;

-- Очистка всех Relay Log (сброс позиции!)
RESET REPLICA;

-- Запуск репликации (скачает свежий Relay Log с источника)
START REPLICA;
```

**Автоматическая очистка:**
- `relay_log_space_limit` — ограничивает общий размер Relay Log. При достижении лимита I/O-поток останавливается.
- `relay_log_recovery = ON` — при запуске реплика автоматически удаляет неиспользуемые Relay Log.

### Восстановление после сбоя

1. **Проверка состояния:**
   ```sql
   SHOW REPLICA STATUS\G
   ```
   Убедитесь, что `Replica_IO_Running = Yes` и `Replica_SQL_Running = Yes`.

2. **Если SQL-поток остановлен с ошибкой:**
   ```sql
   STOP REPLICA;
   SET GLOBAL sql_slave_skip_counter = 1;
   START REPLICA;
   ```
   **В GTID-режиме:** Вместо `sql_slave_skip_counter` используйте пустую транзакцию (см. `management_debug.md`).

3. **Если I/O-поток остановлен с ошибкой:**
   ```sql
   STOP REPLICA IO_THREAD;
   START REPLICA IO_THREAD;
   ```
   Или полный перезапуск: `STOP REPLICA; START REPLICA;`.

### Откат конфигурации

Если изменения конфигурации (`my.cnf`) привели к нестабильной работе репликации:

1. Восстановите предыдущую версию `my.cnf` из резервной копии или VCS.
2. Перезапустите MySQL: `systemctl restart mysql`.
3. Проверьте статус: `SHOW REPLICA STATUS\G`.
4. Если репликация не стартует — проверьте ошибки в `error.log`.

### Удаление репликации

Если реплика больше не нужна:

1. Остановите репликацию: `STOP REPLICA;`.
2. Сбросьте метаданные: `RESET REPLICA ALL;`.
3. Удалите пользователя репликации на источнике:
   ```sql
   DROP USER IF EXISTS 'repl'@'replica_host';
   FLUSH PRIVILEGES;
   ```
4. На реплике удалите конфигурацию репликации из `my.cnf` (`server-id`, `relay-log`, `replica-*` параметры).
5. Перезапустите MySQL на реплике.

## Дополнительная информация

### Глубокий мониторинг через Performance Schema

В MySQL 8.0 Performance Schema является источником истины для метрик репликации.

```sql
-- Задержка применения транзакций (Lag)
SELECT CHANNEL_NAME,
       WORKER_ID,
       TIMESTAMPDIFF(MICROSECOND,
                     LAST_APPLIED_TRANSACTION_ORIGINAL_COMMIT_TIMESTAMP,
                     LAST_APPLIED_TRANSACTION_END_APPLY_TIMESTAMP) / 1000000 AS lag_seconds
FROM performance_schema.replication_applier_status_by_worker
WHERE LAST_APPLIED_TRANSACTION IS NOT NULL;

-- Состояние I/O потока и сетевые задержки
SELECT * FROM performance_schema.replication_connection_status\G

-- Состояние воркеров MTS
SELECT * FROM performance_schema.replication_applier_status_by_worker;
```

### Рекомендации по Crash-Safety

Для предотвращения повреждения репликации при внезапном выключении (Hard Reboot):

1. **Репозитории в таблицах (MySQL 5.7 — 8.2):** 
   ```ini
   master_info_repository = TABLE
   relay_log_info_repository = TABLE
   ```
   Обе переменные **удалены в MySQL 8.3.0**; начиная с 8.4 метаданные репликации всегда хранятся в транзакционных таблицах и параметр не требуется.
2. **Восстановление Relay Log:**
   ```ini
   relay_log_recovery = ON
   ```
   При запуске реплика удаляет старые Relay Logs и скачивает их заново с источника, основываясь на последней подтвержденной позиции в БД.
3. **Синхронизация логов:**
   ```ini
   sync_binlog = 1
   innodb_flush_log_at_trx_commit = 1
   ```

### Очистка бинарных логов

Процедуры ротации, очистки и управления местом подробно описаны в разделе **[Управление бинарными логами](./binlog_management.md)**. Никогда не удаляйте файлы логов через команды ОС (`rm`), используйте только SQL-команды `PURGE BINARY LOGS`.

### См. также

- **[Обзор репликации MySQL](./overview.md)** — архитектура, топологии и базовые понятия.
- **[Настройка репликации MySQL](./setup_guide.md)** — практическое руководство по запуску.
- **[GTID-репликация](./gtid.md)** — идентификаторы транзакций, автопозиционирование, продвинутые сценарии.
- **[Управление и отладка](./management_debug.md)** — решение проблем и диагностика ошибок.
- **[Форматы бинарного лога](./binlog_formats.md)** — влияние формата binlog (STATEMENT/ROW/MIXED) на механизм репликации.
- **[Управление бинарными логами](./binlog_management.md)** — ротация, очистка и мониторинг диска.
- **[Multi-Source репликация](./multi-source.md)** — консолидация данных из разных источников, мониторинг каналов.
