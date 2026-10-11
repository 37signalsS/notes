# MariaDB MaxScale: Readconnroute и schemarouter

**Актуально для:** MaxScale 25.10.x

## Определения

*   **readconnroute** — лёгкий роутер, балансирующий **соединения** (не запросы): при подключении клиента выбирается один сервер, и все запросы сессии идут на него. Сервер фиксирован на время сессии; routing hints игнорируются.
*   **schemarouter** — роутер-шардирование: строит единую логическую БД из нескольких физических серверов, маршрутизируя запросы по базе/таблице.
*   **router_options** (readconnroute) — маска ролей серверов, к которым разрешено подключаться: `master`, `slave`, `synced`, `running` (default).
*   **master_accept_reads** (readconnroute) — исключает Primary из выбора сервера (default `true`, т.е. Primary допускается). Неактивен, если `router_options` содержит `master`.
*   **max_replication_lag** (readconnroute) — максимальный допустимый лаг репликации (duration, default `0s` = лаг игнорируется). Реплика допускается только при лаге **строго меньше** значения; чтобы не допускать никакого лага — `max_replication_lag=1s`.
*   **preferred_labels** (readconnroute) — приоритет серверов по пользовательским меткам (параметр `labels` в секции сервера).
*   **rank** — ранг сервера: `primary` (default) или `secondary`. readconnroute всегда использует `primary`-серверы раньше `secondary`, пока они подходят под `router_options`. На мониторы rank не влияет.
*   **SHOW SHARDS** — диагностическая команда schemarouter: карта «база.таблица → сервер».
*   **Table family sharding** — шардирование на уровне таблиц внутри одной базы (разные таблицы одной БД на разных серверах; с MaxScale 2.3.0).
*   **refresh_interval / max_staleness** (schemarouter) — минимальный интервал обновления карты баз (default `300s`) и окно использования устаревших записей при обновлении (default `150s`).
*   **ignore_tables / ignore_tables_regex / allow_duplicates** (schemarouter) — контроль проверки дубликатов баз/таблиц на шардах.
*   **invalidate / clear** — module commands schemarouter для обновления и очистки кэша карты баз.

## Теоретический блок

### readconnroute: соединение vs запрос

readwritesplit разбирает каждый запрос и маршрутизирует его individually. readconnroute проще: одно соединение клиента = одно соединение к одному бэкенду. Следствия:

*   Нет переключения сервера mid-session: если бэкенд упал — сессия закрывается (переподключения нет; роутер никогда не reconnectится к изначально выбранному серверу).
*   Нет анализа SQL — минимальные накладные расходы CPU.
*   **По умолчанию не запрещает запись** даже при `router_options=slave`: для read-only порта обязателен `readonly` filter.
*   Если все серверы из `router_options` недоступны, но Primary жив — при `router_options=slave` подключение пойдёт на Primary (если `master_accept_reads` не выставлен в `false`).
*   `LOAD DATA LOCAL INFILE` с бинарными данными не поддерживается.

**Выбор сервера:** список серверов обрабатывается от первого к последнему; при равном весе и статусе выбирается тот, что первым указан в `servers`. Серверы с `rank=secondary` используются только когда нет подходящих `primary`-серверов. Legacy-механизм взвешивания `weightby` удалён в 2.5 — для приоритизации используйте `rank` и `preferred_labels`.

### readconnroute: параметры

| Параметр | Тип | Default | Динамический | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| `router_options` | enum_mask | `running` | Yes | Роли серверов: `master`, `slave`, `synced`, `running` |
| `master_accept_reads` | boolean | `true` | Yes | Исключить Primary из выбора; неактивен при `router_options` с `master` |
| `max_replication_lag` | duration | `0s` | Yes | Реплика допускается только при лаге строго меньше значения |
| `preferred_labels` | string list | нет | Yes | Группы серверов по меткам в порядке предпочтения |

Все параметры динамические: изменяются в рантайме через `maxctrl alter service`, действуют только для новых сессий.

### schemarouter: логика маршрутизации

*   Запросы, модифицирующие сессию (`SET`, пользовательские переменные) — на **все** серверы.
*   `USE <db>` / `COM_INIT_DB` — на все серверы, содержащие эту БД. При подключении с default database — она устанавливается только на серверах, где эта БД есть.
*   Запрос с таблицами — на сервер, содержащий **все** таблицы запроса; если такого нет — на последний использованный или первый доступный.
*   Неизвестные таблицы / команды без таблиц — на сервер с текущей БД по умолчанию; без default database — на последний использованный или первый доступный.
*   Запрос с routing hint — на сервер, указанный в hint.
*   Транзакции (`BEGIN`/`COMMIT`/`ROLLBACK`) — на все серверы (MaxScale 6.4.5+, т.е. 21.06.5+ — во всех актуальных версиях); ранее — на первый доступный.
*   XA-транзакции, административные и репликационные команды — в отдельных случаях на первый доступный сервер; для контроля используйте routing hints.
*   `LOAD DATA LOCAL INFILE` — на первый доступный сервер, содержащий перечисленные в запросе таблицы.
*   Дубликаты баз/таблиц на разных шардах — ошибка `ERROR 5000 (DUPDB)` (кроме системных `mysql`, `information_schema`, `performance_schema`, `sys`).
*   Имена баз и таблиц сравниваются **без учёта регистра**: `test.t1` и `test.T1` — одна и та же таблица.

### schemarouter: карта баз и кэширование

Карта «база/таблица → сервер» строится отдельно для каждого пользователя: MaxScale отправляет `SHOW DATABASES` на все серверы от имени подключающегося клиента (учётные данные сервиса `user`/`password` используются для получения auth-данных; права сопоставляются с хоста MaxScale, а не клиента). Кэш обновляется не чаще `refresh_interval` (default 300s); при устаревании записи — `max_staleness` (default 150s) окно использования, затем новые соединения блокируются до обновления. Построение карты ожидают и остальные сессии, которым нужен тот же кэш (с 2.4.19).

Начиная с 24.02 schemarouter автоматически включает `auth_all_servers` и собирает auth-данные со всех серверов (параметр был deprecated в 24.02.0, затем un-deprecated — см. [Пулинг соединений](./maxscale_connection_pooling.md)).

## Практические сценарии

**Примечание:** в секциях сервисов ниже используется `servers=` — историческое имя параметра. С 24.02 актуальное имя — `targets=` (принимает также имена сервисов); в 25.10 оба имени работают.

### Prerequisites

*   readconnroute: монитор, размечающий роли (mariadbmon/galeramon).
*   schemarouter: монитор, дающий серверам статус `Running`/`Down` (подходит `galeramon` даже без Galera — schemarouter интересует только этот статус); либо `initial_status=up` в секции сервера при отсутствии монитора (default без монитора — `down`).
*   schemarouter: сервисный пользователь с `USAGE`+`SELECT` на шардируемых БД, созданный на всех шардах; уникальность баз/таблиц по шардам.
*   Учётные данные сервиса в конфиге можно шифровать через `maxpasswd` (см. [Обзор](./maxscale_overview.md)).

### Шаг 1: readconnroute — read-only порт

```ini
# /etc/maxscale.cnf

[Read-Service]
type=service
router=readconnroute
servers=replica1,replica2,replica3

# Учётные данные сервиса для получения auth-данных (Mandatory)
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ

# Только реплики; при падении всех реплик — fallback на Primary
router_options=slave

# Чтения не идут на Primary: исключает Primary из выбора сервера.
# Неактивен, если router_options содержит master.
master_accept_reads=false

# Реплика допускается только при лаге строго меньше 10s
# (default 0s — лаг игнорируется; 1s — не допускать никакого лага)
max_replication_lag=10s

filters=ReadOnlyFilter

[ReadOnlyFilter]
type=filter
module=readonly

[Read-Listener]
type=listener
service=Read-Service
protocol=MariaDBClient
port=3307
```

**Пояснения:**

*   `router_options=master,slave` — подключение к любому серверу; `synced` — только синхронизированные узлы Galera; `running` (default) — все доступные.
*   `preferred_labels=banana,mango` — серверы с меткой `banana` предпочтительнее `mango`; если нет — любой валидный по `router_options`. Метки задаются параметром `labels` в секциях серверов. Полезно для отдельных сервисов (бэкапы, отчёты) с приоритетом конкретных узлов.
*   При равном весе серверы обрабатываются в порядке перечисления в `servers` — первый подходящий и выбирается.

**Валидация:**

```bash
# На какой реплике оказалась сессия
mysql -u app_user -p -h maxscale-host -P 3307 -e "SELECT @@hostname;"
# → replica2 (один из servers; повторные подключения распределяются по репликам)

# Запись блокируется readonly filter (детали — в maxscale_security.md)
mysql -u app_user -p -h maxscale-host -P 3307 -e "INSERT INTO t VALUES (1);"
# → ошибка от фильтра readonly

# Диагностика роутера: queries — число запросов через сервис
maxctrl show service Read-Service
```

### Шаг 2: readconnroute — write-порт (только Primary)

```ini
[Write-Service]
type=service
router=readconnroute
servers=db-node-1,db-node-2,db-node-3
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ
router_options=master

[Write-Listener]
type=listener
service=Write-Service
protocol=MariaDBClient
port=3308
```

Приложение использует два порта: 3308 — запись, 3307 — чтение. Это легковесная альтернатива readwritesplit, но требует, чтобы приложение само разделяло чтение и запись. При `router_options=master` параметр `master_accept_reads` неактивен.

**Валидация:**

```bash
mysql -u app_user -p -h maxscale-host -P 3308 -e "SELECT @@hostname;"
# → db-node-1 (текущий Primary)
```

### Шаг 3: readconnroute — выделенные сервисы (preferred_labels + rank)

Отдельный порт для отчётов/бэкапов: нагрузка изолируется на выбранные реплики, но при их отказе сервис не теряет доступность.

```ini
# Серверы: метки и ранги
[replica-1]
type=server
address=10.0.1.11
port=3306
labels=report
rank=primary

[replica-2]
type=server
address=10.0.1.12
port=3306
labels=report
rank=primary

[replica-3]
type=server
address=10.0.1.13
port=3306
rank=primary

[dr-replica]
type=server
address=10.0.2.21
port=3306
rank=secondary

[Report-Service]
type=service
router=readconnroute
servers=replica-1,replica-2,replica-3,dr-replica
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ
router_options=slave

# Сначала серверы с меткой report, затем — любые валидные по router_options
preferred_labels=report

[Report-Listener]
type=listener
service=Report-Service
protocol=MariaDBClient
port=3309
```

**Логика:** `preferred_labels=report` — сначала `replica-1`/`replica-2`; если оба недоступны — `replica-3` и далее любой валидный сервер. `rank=secondary` — `dr-replica` используется только когда нет подходящих `primary`-серверов.

### Шаг 4: schemarouter — простое шардирование по базам

```ini
# /etc/maxscale.cnf

[Shard-Router]
type=service
router=schemarouter
servers=shard1,shard2
user=myuser
# password=5A5A...  # зашифрованный maxpasswd; открытый пароль — только для стенда

# Интервал обновления карты баз
refresh_interval=300s

# Окно использования устаревших записей
max_staleness=150s

# Разрешить дубликаты таблиц (25.01+; иначе — ignore_tables_regex)
allow_duplicates=false

# Игнорировать дубликаты в конкретных БД (PCRE2, по именам баз)
# ignore_tables_regex=^db1|^db2|^db3\.t

# Точный список полных имён таблиц, исключаемых из проверки дубликатов
# ignore_tables=db1.t1,db2.t2

# Обновлять карту mid-session при неудачном USE (работает с 6.2.0; default false)
# refresh_databases=false

[Shard-Listener]
type=listener
service=Shard-Router
protocol=MariaDBClient
port=3306

# Монитор нужен хотя бы для статуса Running/Down;
# galeramon подходит даже без Galera
[Shard-Monitor]
type=monitor
module=galeramon
servers=shard1,shard2
user=monitor_user
password=СЛОЖНЫЙ_ПАРОЛЬ
```

**Пояснения:**

*   `user`/`password` — учётные данные для получения auth-данных и построения карты баз; достаточно `USAGE`+`SELECT` на шардируемых БД.
*   `allow_duplicates=true` (25.01+) — эффективная замена `ignore_tables_regex=.*` для отключения проверки дубликатов.
*   `ignore_tables_regex` — не динамический параметр (Dynamic: No): для изменения нужно уничтожить и пересоздать объект (`maxctrl destroy filter <filter>` + `maxctrl create filter ...`), либо правка статического конфига с перезапуском MaxScale.

**Валидация:**

```sql
-- Подключение как приложение
mysql -u app_user -p -h maxscale-host -P 3306

-- Карта шардирования
SHOW SHARDS;
-- → Database | Server
-- → db1.t1   | shard1
-- → db1.t2   | shard1
-- → db2.t1   | shard2

-- Сессия прозрачно переключается между шардами
USE db1;
SELECT * FROM t1;          -- → shard1
USE db2;
SELECT * FROM t1;          -- → shard2
```

### Шаг 5: schemarouter — table family sharding

База `db` есть на обоих серверах, но таблицы разные: `shard1.db.tbl1`, `shard2.db.tbl2`. Запросы с полным квалификатором маршрутизируются правильно:

```sql
-- Идёт на shard1
SELECT * FROM db.tbl1;

-- Идёт на shard2
SELECT * FROM db.tbl2;
```

Не поддерживается:

```sql
USE db;
SELECT * FROM tbl1;  -- может попасть не на тот шард
```

### Шаг 6: Диагностика и управление в рантайме

```bash
# Module commands (с 25.10 — имя объекта вместо модуля)
maxctrl call command Shard-Router invalidate
# → запланировать обновление карты (предпочтительно)

maxctrl call command Shard-Router clear
# → полная очистка: новые соединения ждут обновления

# Старая форма (обязательна на 25.01 и ранее):
maxctrl call command schemarouter invalidate Shard-Router

# Все зарегистрированные module commands
maxctrl list commands

# Router diagnostics: shard_map_hits / shard_map_misses
maxctrl show service Shard-Router

# Динамические параметры — без перезапуска MaxScale
maxctrl alter service Read-Service max_replication_lag=20s
maxctrl alter service Read-Service master_accept_reads=true
```

**`invalidate` vs `clear`:** `invalidate` планирует обновление (предпочтительно); `clear` заставляет все новые соединения ждать полного обновления — при большой карте это блокирует клиентов. Паттерн эксплуатации: высокий `refresh_interval` + `invalidate` по расписанию в off-peak.

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Запись прошла на реплику через readconnroute | Нет `readonly` filter | Добавьте `filters=ReadOnlyFilter` (Шаг 1) |
| Сессия закрылась при падении бэкенда | readconnroute не переподключается | Это ограничение роутера; приложение должно переподключаться; для прозрачного reconnect используйте readwritesplit |
| Чтения идут на Primary, хотя реплики есть | `master_accept_reads=true` (default) при `router_options` без `master`, либо все реплики отстали больше `max_replication_lag` | `master_accept_reads=false`; проверьте лаг (`maxctrl list servers`) |
| При `router_options=slave` подключение ушло на Primary | Все реплики недоступны — это штатный fallback | Проверьте реплики; `master_accept_reads=false` убирает fallback |
| `ERROR 5000 (DUPDB)` | Одна БД/таблица на двух шардах | Уберите дубликат или настройте `ignore_tables` / `ignore_tables_regex` / `allow_duplicates=true` |
| Новая БД не видна клиенту | Кэш карты устарел (`refresh_interval`) | Подождите обновления или `invalidate`; `SHOW DATABASES` генерируется роутером (модификаторы вроде `LIKE` игнорируются, имена в нижнем регистре) |
| Клиент зависает при подключении | Обновление карты блокирует соединения (`max_staleness` превышен) | Увеличьте `max_staleness` или используйте `invalidate` вместо `clear` |
| `SELECT * FROM t1` без БД — не тот шард | Нет default database; запрос без квалификатора | Указывайте БД явно или используйте routing hints |
| Кросс-шардный UNION/JOIN даёт ошибку | Не поддерживается: запрос идёт на один шард, где второй таблицы нет (`ERROR 1146 (42S02): Table ... doesn't exist`) | Выполняйте части отдельно и объединяйте на клиенте; для кросс-шардных JOIN — Spider storage engine |
| Prepared statement из переменной (`PREPARE stmt FROM @a`) или `EXECUTE IMMEDIATE` маршрутизирован неверно | Ограничение schemarouter | Готовьте statements явно |
| `USE db` на шардированной БД — часть таблиц недоступна | Команда `USE` идёт только на один сервер | Учитывайте при split базы между шардами; `SHOW TABLES` при table family sharding тоже неполный — используйте `SHOW SHARDS` |
| XA-транзакция или административная команда попала не на тот шард | Такие команды идут на первый доступный сервер | Направляйте через routing hints |
| Сервер schemarouter не используется | Без монитора сервер в статусе `down` (default `initial_status`) | Настройте монитор (`galeramon`) или `initial_status=up` в секции сервера |
| Гранты пользователя работают не на том шарде | Гранты сопоставляются с хоста MaxScale, а не клиента | Проверьте `GRANT ... TO 'user'@'<maxscale-host>'` на нужном шарде |

## Best Practices

1.  **readconnroute** — когда приложение само разделяет чтение/запись и нужно минимум накладных расходов; иначе — readwritesplit.
2.  **Всегда `readonly` filter** на read-only порту readconnroute.
3.  **`preferred_labels` + `rank`** — для выделенных сервисов (бэкап, отчёты) с приоритетом конкретных реплик; DR-узлы — в `rank=secondary`.
4.  **schemarouter** — шардирование «по базам» с единой точкой входа; не для кросс-шардных JOIN/UNION.
5.  **Полный квалификатор таблиц** (`db.tbl`) обязателен для table family sharding.
6.  **`refresh_interval` + `invalidate`** — обновляйте карту в off-peak, а не `clear`.
7.  **Транзакции в schemarouter:** `BEGIN`/`COMMIT` идут на все шарды (6.4.5+), но без внешней синхронизации глобальная консистентность не гарантирована. Рекомендуемый способ — `SET autocommit=0` / `SET autocommit=1`; для явных `BEGIN` без него — routing hints.
8.  **Монитор для schemarouter обязателен** (хотя бы для статуса Running/Down); без монитора — `initial_status=up` на серверах.
9.  **Динамические параметры** меняйте через `maxctrl alter service` — перезапуск MaxScale не нужен; изменения действуют на новые сессии.
10. **Откат изменений:** удалите секции listener/service из статического конфига и перезапустите MaxScale, либо `maxctrl destroy listener <listener>` / `maxctrl destroy service <service>` (из рантайма); убедитесь, что приложения переключены на другой порт до удаления.

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — архитектура и поток запроса.
*   **[Read/Write Split](./maxscale_readwritesplit.md)** — statement-level маршрутизация, server ranks.
*   **[Безопасность](./maxscale_security.md)** — readonly filter.
*   **[Пулинг соединений](./maxscale_connection_pooling.md)** — auth_all_servers, persistpoolmax.
*   **[Мониторинг](./maxscale_monitoring.md)** — метрики и алерты.
*   **[Failover и Switchover](./maxscale_failover.md)** — смена Primary.
*   **[Binlog Router](./maxscale_binlogrouter.md)** — прокси репликации.
*   [Readconnroute (официальная документация)](https://mariadb.com/docs/maxscale/reference/maxscale-routers/maxscale-readconnroute)
*   [SchemaRouter (официальная документация)](https://mariadb.com/docs/maxscale/reference/maxscale-routers/maxscale-schemarouter)
