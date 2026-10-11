# Топологии репликации MySQL: каскадная, кольцевая, multi-master

**Актуально для:** MySQL 8.0.23+ / 8.4 LTS (синтаксис `CHANGE REPLICATION SOURCE TO`, `START REPLICA`; имя `log_replica_updates` — с 8.0.26, ранее `log_slave_updates`). До 8.0.23 операторы называются `CHANGE MASTER TO` / `START SLAVE`.

## Определения

*   **Каскадная репликация (Cascading Replication)** — топология, в которой реплика сама является источником для другой реплики (replica → replica). Промежуточная реплика называется **промежуточным узлом (intermediate source)**.
*   **Звезда (Star)** — базовая топология `Source → N реплик`: каждая реплика подключена непосредственно к источнику. Простейшая и наиболее распространённая схема.
*   **`log_replica_updates`** — системная переменная (с MySQL 8.0.26; ранее `log_slave_updates`, сохраняется как deprecated alias), включающая запись применённых от источника событий в собственный бинарный лог реплики. Обязательна для каскадной репликации: без неё промежуточная реплика не передаёт события дальше. По умолчанию `ON` (в 8.0+). Требует включённого binary logging: при `--skip-log-bin` переменная автоматически отключается.
*   **Кольцевая репликация (Ring Replication)** — топология, в которой узлы образуют кольцо: каждый узел реплицирует следующему, последний — первому. Поддерживает запись на всех узлах (multi-master) — с осторожностью.
*   **Multi-master (classic)** — классическая асинхронная репликация с записью на нескольких узлах (в отличие от Group Replication — без синхронной сертификации и автоматического разрешения конфликтов).
*   **Ромбовидная топология (Diamond)** — один источник дублируется двумя путями к одной реплике: `A → B`, `A → C`, `B → D`, `C → D`. Реплика D получает одни и те же транзакции от двух источников.
*   **Multi-source** — одна реплика одновременно принимает изменения от нескольких независимых источников (по каналу на каждый). Полное описание — SSoT в `multi-source.md`.
*   **`auto_increment_increment` / `auto_increment_offset` — системные переменные для генерации уникальных AUTO_INCREMENT-значений на разных источниках в кольцевых и source-to-source (multi-master) топологиях.

## Базовые концепции

### Каскадная репликация (Chain / Tree)

Топология: `Source → Replica1 → Replica2 → Replica3`.

**Зачем:**

*   **Снижение нагрузки на источник**: источник отдаёт binlog только одному промежуточному узлу, а не всем репликам. Полезно при большом числе реплик (десятки).
*   **Географическое распределение**: промежуточный узел в другом ЦОД, реплики за ним — локально.
*   **Изоляция**: реплики для аналитики не нагружают сеть источника.

**Требования:**

*   На промежуточной реплике обязательно `log_replica_updates = ON` (по умолчанию ON в 8.0+, но проверьте) и включённый `log_bin`.
*   Уникальный ненулевой `server_id` (1..4294967295) на каждом узле топологии — обязательное условие репликации.
*   GTID-репликация (`gtid_mode = ON`, `enforce_gtid_consistency = ON`) упрощает каскад: позиции отслеживаются автоматически (`SOURCE_AUTO_POSITION = 1`).

**Ограничения:**

*   **Суммарный лаг** складывается из лагов всех звеньев. Replica2 отстаёт от Source на (лаг Replica1 + собственный лаг).
*   **Точка отказа**: если Replica1 падает, Replica2 и Replica3 перестают получать обновления.
*   **Failover сложнее**: при промоушене Replica1 нужно перенастроить всю цепочку ниже (механика — в `failover_switchover.md`).
*   **Фильтры каскадно отсекают трафик**: события, отфильтрованные на промежуточном узле (`replicate-ignore-db` и аналоги), не применяются и не попадают в его binlog — downstream-реплики их не получат никогда.

### Кольцевая репликация (Ring)

Топология: `A → B → C → A` (каждый узел — источник для следующего).

**Особенности:**

*   Поддерживает запись на всех узлах (multi-master), но **без автоматического разрешения конфликтов** (в отличие от Group Replication).
*   Требует `auto_increment_increment` / `auto_increment_offset` для уникальности AUTO_INCREMENT.
*   **С GTID кольцо не зацикливается**: транзакция, вернувшаяся на уже исполнивший её узел, отсекается авто-пропуском по `gtid_executed` (GTID уже использован — ошибки нет, транзакция игнорируется). Без GTID (позиционная репликация) событие циркулирует по кольцу бесконечно — нужны фильтры.
*   **Главная опасность — write-write конфликты**: одна и та же строка, обновлённая на двух узлах, приводит к ошибке применения (`Duplicate entry` / `Can't find record`) на одном из узлов.
*   Для production multi-master рекомендуется Group Replication / InnoDB Cluster.

### Multi-master (classic, не Group Replication)

Два и более узла, на которые разрешена запись, связанные асинхронной репликацией.

**Отличия от Group Replication:**

*   Нет синхронной сертификации — конфликты не обнаруживаются автоматически.
*   RPO > 0 (асинхронность).
*   Требует ручной стратегии разрешения конфликтов или строгого разделения записи по узлам (шардирование на уровне приложения).

**Когда оправдан:**

*   Географически распределённая запись с разделением по регионам (каждый регион пишет в свой источник).
*   Миграция между версиями/движками.
*   **Не оправдан** для типичного HA — используйте Group Replication или Source-Replica + Orchestrator/ProxySQL.

### Ромбовидная топология (Diamond)

Топология: `A → B`, `A → C`, `B → D`, `C → D` (например, репликация в два ЦОД и схождение в третьем).

*   Реплика D получает каждую транзакцию дважды — от B и от C.
*   **С GTID двойное применение исключено**: механизм авто-пропуска (auto-skip) гарантирует, что транзакция, уже исполненная на D, не применится повторно при получении её от второго источника.
*   Без GTID двойное применение приводит к ошибкам применения (дубликаты ключей).
*   Требует уникальных `server_id` и корректного `gtid_executed` на всех узлах.

### AUTO_INCREMENT в multi-master

Для уникальности значений на разных источниках:

```ini
# Узел A
auto_increment_increment = 2
auto_increment_offset = 1   # генерирует 1, 3, 5, 7, ...

# Узел B
auto_increment_increment = 2
auto_increment_offset = 2   # генерирует 2, 4, 6, 8, ...
```

**Правила (верифицированы по MySQL 8.4 Reference Manual):**

*   Формула ряда: `auto_increment_offset + N × auto_increment_increment`, N = 0, 1, 2, ... — первое значение равно offset.
*   `auto_increment_increment` — интервал между значениями; `auto_increment_offset` — стартовая точка. Диапазон обоих: 1..65535, по умолчанию 1.
*   Установка 0 → значение становится 1; значение >65535 или <0 → становится 65535; нечисловое значение → ошибка, переменная не меняется.
*   Если `auto_increment_offset > auto_increment_increment`, значение `auto_increment_offset` **игнорируется** (но не сбрасывается в 1).
*   Область видимости: Global + Session, переменные динамические (`SET GLOBAL`/`SET SESSION`). Изменение глобального значения действует **только на новые сессии** — уже открытые сессии используют своё значение до переподключения; перезапуск сервера для изменения не требуется.
*   В Group Replication (multi-primary) эти параметры управляются автоматически.

## Требования и подготовка (Prerequisites)

*   **Версии**: MySQL 8.0.23+ для `CHANGE REPLICATION SOURCE TO` (до 8.0.23 — `CHANGE MASTER TO`); переименования операторов `SHOW/START/STOP/RESET REPLICA` — с 8.0.22.
*   **Идентификация узлов**: уникальный ненулевой `server_id` (1..4294967295) на каждом сервере; `server_uuid` генерируется автоматически при первом запуске и хранится в `auto.cnf` в datadir — файл создаётся автоматически, править его вручную запрещено.
*   **GTID** (рекомендуется): `gtid_mode = ON`, `enforce_gtid_consistency = ON` — для `SOURCE_AUTO_POSITION = 1` и упрощения failover.
*   **Каскад**: `log_bin = ON` и `log_replica_updates = ON` на всех промежуточных узлах.
*   **Инструменты**: `pt-heartbeat` (Percona Toolkit) для точного измерения сквозного лага — методика в `lag_monitoring.md`.

## Практические сценарии

### Сценарий 1: Каскадная репликация (Source → Replica1 → Replica2)

**На Source:**
```ini
[mysqld]
server_id = 1
log_bin = /var/log/mysql/mysql-bin
gtid_mode = ON
enforce_gtid_consistency = ON
```

**На Replica1 (промежуточный узел):**
```ini
[mysqld]
server_id = 2
log_bin = /var/log/mysql/mysql-bin
log_replica_updates = ON   # обязательно: записывает применённые события в свой binlog
gtid_mode = ON
enforce_gtid_consistency = ON
read_only = 1
```

**На Replica2:**
```ini
[mysqld]
server_id = 3
log_bin = /var/log/mysql/mysql-bin
log_replica_updates = ON
gtid_mode = ON
enforce_gtid_consistency = ON
read_only = 1
```

```sql
-- Replica1 подключается к Source
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_AUTO_POSITION=1;
START REPLICA;

-- Replica2 подключается к Replica1 (не к Source!)
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='replica1_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password',
    SOURCE_AUTO_POSITION=1;
START REPLICA;
```

**Проверка:**
```sql
-- На Replica1: убедитесь, что log_replica_updates включён
SHOW VARIABLES LIKE 'log_replica_updates';
-- → ON

-- На Replica2: проверьте, что источник — Replica1
SHOW REPLICA STATUS\G
-- → Source_Host: replica1_ip
-- → Replica_SQL_Running: Yes
```

### Сценарий 2: Multi-master с AUTO_INCREMENT

**Узел A:**
```ini
[mysqld]
server_id = 1
auto_increment_increment = 2
auto_increment_offset = 1
```

**Узел B:**
```ini
[mysqld]
server_id = 2
auto_increment_increment = 2
auto_increment_offset = 2
```

```sql
-- На A: репликация от B
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='b_ip', SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password', SOURCE_AUTO_POSITION=1;
START REPLICA;

-- На B: репликация от A
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='a_ip', SOURCE_USER='repl_user',
    SOURCE_PASSWORD='password', SOURCE_AUTO_POSITION=1;
START REPLICA;
```

**Проверка уникальности:**
```sql
-- На A
INSERT INTO t (name) VALUES ('from_a');
SELECT id FROM t;  -- → 1, 3, 5, ...

-- На B
INSERT INTO t (name) VALUES ('from_b');
SELECT id FROM t;  -- → 2, 4, 6, ...
```

После репликации оба узла содержат все строки (на A видны и 2, 4, 6, ...): уникальность достигается разнесением значений, а не разделением данных.

### Сценарий 3: Диагностика каскадного лага

```sql
-- На каждом звене: лаг репликации
SHOW REPLICA STATUS\G
-- → Seconds_Behind_Source

-- Точнее: через Performance Schema (не зависит от состояния потоков)
SELECT CHANNEL_NAME, SERVICE_STATE,
       COUNT_RECEIVED_HEARTBEATS, COUNT_RECEIVED_TRANSACTIONS
FROM performance_schema.replication_connection_status;
```

**Важно:** `Seconds_Behind_Source` в каскадной топологии показывает лаг только относительно непосредственного источника, а не относительно корневого Source. Для точного сквозного лага используйте `pt-heartbeat` из Percona Toolkit (методика — в `lag_monitoring.md`).

## Валидация

*   На каждом звене: `Replica_IO_Running: Yes`, `Replica_SQL_Running: Yes`, `Seconds_Behind_Source: 0`.
*   **GTID-сверка**: `SELECT @@GLOBAL.gtid_executed;` — у Replica2 множество должно содержать все GTID источника (после синхронизации — равенство).
*   На Source: `SHOW REPLICAS;` — все подключённые реплики видны.
*   **Сквозной тест**: `INSERT` на Source → строка появляется на Replica2 (конечное звено цепочки).

## Устранение неисправностей (Troubleshooting)

### Типичные проблемы каскадной репликации

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Replica2 не получает данные | `log_replica_updates = OFF` на Replica1 | Включить `log_replica_updates = ON` в `[mysqld]` и перезапустить Replica1 (переменная задаётся при запуске сервера) |
| Replica2 не получает данные | `log_bin = OFF` на Replica1 | Включить бинарный лог на промежуточном узле |
| Replica2 не получает данные | Фильтры `replicate-*` на Replica1 отсекают события до записи в binlog | Проверить `Replicate_Do_DB` / `Replicate_Ignore_DB` / `Replicate_Wild_*` в `SHOW REPLICA STATUS`; помнить, что отфильтрованные события не передаются downstream |
| Ошибка 1593 (`Last_IO_Errno`) | Совпадающий `server_uuid`: datadir скопирован/клонирован вместе с `auto.cnf` | Удалить `auto.cnf` из datadir, перезапустить — UUID генерируется заново. (Опция `--replicate-same-server-id` допускает равные UUID, но в каскаде нежелательна) |
| Purged GTID: `Last_IO_Errno: 1789` (`ER_SOURCE_HAS_PURGED_REQUIRED_GTIDS`) — конкретная причина; `Last_IO_Errno: 1236` (`ER_SOURCE_FATAL_ERROR_READING_BINLOG`) — обёртка с тем же текстом («...MASTER_AUTO_POSITION = 1, but the master has purged binary logs...»); на 8.4 также `MY-013114` («the source purged required binary logs»). Механизм — в `gtid.md` | Источник удалил binlog с нужными GTID | Увеличить `binlog_expire_logs_seconds` (дефолт 2592000 сек = 30 дней), воспроизвести недостающие транзакции из другого источника или пересоздать реплику из бэкапа |
| Бесконечный цикл в ring (без GTID) | События циркулируют по кольцу | Включить GTID (авто-пропуск по `gtid_executed`) либо настроить фильтры (`replicate-ignore-db`, `replicate-wild-ignore-table`) для разрыва цикла |
| Write-write конфликт в ring/multi-master | Одна строка обновлена на двух узлах | Разделение записи по узлам на уровне приложения; конфликт проявляется ошибкой применения на одном из узлов |

### Проверка, что промежуточный узел передаёт дальше

```sql
-- На Replica1: есть ли полученные транзакции в своём binlog?
SHOW BINARY LOG STATUS;
-- → File, Position должны расти при записи на Source

-- Сравните GTID:
SELECT @@GLOBAL.gtid_executed;
-- На Replica1 должен содержать GTID источника
```

## Лучшие практика и очистка

1.  **GTID везде** — каскад, diamond и failover упрощаются (`SOURCE_AUTO_POSITION=1`).
2.  **`log_replica_updates = ON`** на всех промежуточных узлах (дефолт в 8.0+, но проверьте).
3.  **Мониторьте лаг каждого звена** — суммарный лаг каскада = сумма лагов.
4.  **Ограничивайте глубину каскада**: каждое звено добавляет лаг и точку отказа; цепочки из 4+ звеньев практически неуправляемы при failover.
5.  **Ring/multi-master classic — только с разделением записи** по узлам; для HA используйте Group Replication.
6.  **`read_only = ON`** на всех незаписываемых узлах (репликации фильтры и applier-потоки не затрагивает).
7.  **Очистка — удаление звена из цепочки**: на downstream-реплике `STOP REPLICA;` затем `CHANGE REPLICATION SOURCE TO SOURCE_HOST='<root_source>', SOURCE_USER='repl_user', SOURCE_PASSWORD='password', SOURCE_AUTO_POSITION=1; START REPLICA;` — с GTID позиции в логах указывать не нужно.
8.  **Очистка — удаление multi-master-связи**: `STOP REPLICA; RESET REPLICA;` (или `RESET REPLICA ALL` для всех каналов) на узле, из которого убирается связь.

## Дополнительная информация

### См. также

*   **[Репликация: обзор](overview.md)** — механизмы и GTID.
*   **[GTID](gtid.md)** — идентификаторы транзакций, авто-пропуск.
*   **[Failover и switchover](failover_switchover.md)** — переключение, промоушен звена каскада.
*   **[Multi-source репликация](multi-source.md)** — одна реплика ← несколько источников (SSoT по топологии).
*   **[Мониторинг лага](lag_monitoring.md)** — pt-heartbeat и P_S.
*   **[Высокая доступность](../high_availability.md)** — Group Replication, InnoDB Cluster.
*   **[MariaDB: топологии](../../MariaDB/replication/topologies.md)** — аналог для MariaDB.

### Внешние ресурсы

*   [MySQL Replication](https://dev.mysql.com/doc/refman/8.4/en/replication.html)
*   [CHANGE REPLICATION SOURCE TO](https://dev.mysql.com/doc/refman/8.4/en/change-replication-source-to.html)
*   [Replication Source Options and Variables (auto_increment_increment / auto_increment_offset)](https://dev.mysql.com/doc/refman/8.4/en/replication-options-source.html)
*   [GTID Auto-Positioning](https://dev.mysql.com/doc/refman/8.4/en/replication-gtids-auto-positioning.html)
