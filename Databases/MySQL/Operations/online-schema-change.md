# Online Schema Change в MySQL: изменение схемы без простоя

**Актуально для:** MySQL 8.0.x / 8.4 LTS / 9.x Innovation, Percona Toolkit 3.x, gh-ost 1.1.x

Online Schema Change (OSC) — изменение структуры таблицы без длительной блокировки чтения
и записи. В MySQL есть три уровня реализации: встроенные Online DDL (алгоритмы
`INSTANT`, `INPLACE`, `COPY`), внешние инструменты копирования с синхронизацией
(`pt-online-schema-change`, `gh-ost`) и «ручной» вариант через теневую таблицу.
Выбор уровня определяется размером таблицы и типом изменения: на таблице в сотни
гигабайт встроенный Online DDL часто неприменим, и единственным безопасным путём
остаётся копирование.

Партнёры по теме: [Индексы в MySQL](../indexing.md) — добавление индекса;
[Репликация MySQL](../replication/overview.md) — влияние на отставание реплик;
[Обслуживание и обновления MySQL](../maintenance-and-upgrades.md) — регулярное
обслуживание и дефрагментация.

## Определения

| Термин | Значение |
| :--- | :--- |
| Online DDL | Возможность менять схему, разрешая параллельные DML-операции, заданная клаузами `ALGORITHM` и `LOCK` |
| `ALGORITHM` | Требуемый сервером способ выполнения: `INSTANT`, `INPLACE`, `COPY` или `DEFAULT` |
| `LOCK` | Допустимый уровень блокировки: `NONE`, `SHARED`, `EXCLUSIVE` или `DEFAULT` |
| Metadata lock (MDL) | Блокировка уровня таблицы; не зависит от InnoDB-транзакций и блокирует даже `SELECT` (фазы и приоритеты — [Metadata locks](../Concepts/metadata_locking.md)) |
| Cut-over | Момент переключения теневой таблицы на её место |
| Sentry table | Пустая таблица-«часовой» в gh-ost, удерживающая `RENAME` до готовности подмены |
| Throttle | Приостановка копирования из-за высокой нагрузки или отставания реплик |
| Critical load | Порог, при котором инструмент не приостанавливается, а прерывает работу |

## Базовые концепции

### Три уровня вместимости

| Уровень | Что делает | Требует копирования данных | Применимо к таблице любого размера |
| :--- | :--- | :--- | :--- |
| `INSTANT` | Меняет только метаданные | Нет | Да |
| `INPLACE` | Перестраивает таблицу, разрешая DML | Частично или полностью | Ограниченно: долгая блокировка метаданных в начале и конце |
| `COPY` | Копирует таблицу целиком под блокировкой | Да, полностью | Нет |
| `pt-osc` / `gh-ost` | Создают теневую таблицу, копируют, синхронизируют, подменяют | Да, построчно | Да |

Ключевое различие между ними — **источник нагрузки**. Online DDL нагружает диск и
redo log самим сервером. OSC нагружает сервер триггерами (pt-osc) или потоком
событий binlog (gh-ost) плюс серией мелких запросов копирования.

### Матрица поддержки операций

`Instant` — да, `In Place` — да, `Rebuilds Table` — перестраивает таблицу,
`Permits Concurrent DML` — параллельные DML разрешены, `Only Modifies Metadata` —
изменяются только метаданные.

**Операции над колонками**

| Операция | Instant | In Place | Rebuilds Table | Permits Concurrent DML | Only Modifies Metadata |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Добавление колонки | Да* | Да | Нет* | Да* | Да |
| Удаление колонки | Да* | Да | Да | Да | Да |
| Переименование колонки | Да* | Да | Нет | Да* | Да |
| Изменение порядка колонок | Нет | Да | Да | Да | Нет |

**Операции над индексами**

| Операция | Instant | In Place | Rebuilds Table | Permits Concurrent DML | Only Modifies Metadata |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Создание вторичного индекса | Нет | Да | Нет | Да | Нет |
| Добавление виртуальной колонки | Да* | Да | Нет | Да | Да |
| Создание индекса по виртуальной колонке | Нет | Да | Нет | Да | Нет |
| Удаление индекса | Нет | Да | Нет | Да | Да |
| Переименование индекса | Да* | Да | Нет | Да | Да |
| Добавление первичного ключа | Нет | Да | Да | Да | Нет |
| Удаление первичного ключа | Нет | Нет | Да | Нет | Нет |

`*` — применимость `INSTANT` зависит от версии сервера; см. таблицу версий ниже.

> **Важная оговорка про `ADD COLUMN`.** Добавление колонки не перестраивает таблицу
> ни при `INSTANT`, ни при `INPLACE` — это операция над метаданными и значениями по
> умолчанию. Тем не менее всегда запрашивайте `ALGORITHM=INSTANT` явно: до 8.0.12
> по умолчанию выбирался `INPLACE`, а до 8.0.29 `INSTANT` умел добавлять колонку
> только в конец. Явный запрос либо гарантирует мгновенную операцию, либо сразу
> завершается `ERROR 1846` — без молчаливого перехода на тяжёлый алгоритм.

**Что ещё поддерживает `INSTANT`** (MySQL 8.0.12+): добавление и удаление виртуальной
колонки, добавление и удаление значения по умолчанию для колонки, изменение определения
колонки `ENUM` или `SET`, изменение типа индекса, переименование таблицы.

### Версии: когда появилась поддержка

| Операция | Версия | Что изменилось |
| :--- | :--- | :--- |
| `INSTANT` как алгоритм по умолчанию для `ADD COLUMN` | 8.0.12 | До этого по умолчанию был `INPLACE` |
| `ALGORITHM=INSTANT` для переименования колонки | 8.0.28 | Ранее только `INPLACE` и `COPY` |
| `ALGORITHM=INSTANT` для `DROP COLUMN` | 8.0.29 | До 8.0.29 по умолчанию был `INPLACE` |
| Добавление колонки в любую позицию (а не только в конец) | 8.0.29 | До этого `INSTANT` умел добавлять колонку только последней |

### Механизм «версий строк» и его предел

Мгновенное добавление или удаление колонки не изменяет сами страницы: сервер создаёт
новую версию определения строки. Одна операция `ALTER TABLE ... ALGORITHM=INSTANT`,
добавляющая или удаляющая колонки, создаёт новую версию строки, и версии накапливаются.

Ограничения:

| Параметр | Значение | Смысл |
| :--- | :--- | :--- |
| Максимум версий строки | 64 | Превышение блокирует дальнейшие мгновенные операции |
| Максимум колонок во внутреннем представлении | 1022 | `ERROR 4158` при превышении |
| Проверка размера строки | С 8.0.29 — при `ADD COLUMN` | `ERROR 4092` при превышении |

Отследить накопление версий:

```sql
SELECT NAME, TOTAL_ROW_VERSIONS
FROM INFORMATION_SCHEMA.INNODB_TABLES
WHERE TOTAL_ROW_VERSIONS > 0
ORDER BY TOTAL_ROW_VERSIONS DESC
LIMIT 10;
-- → NAME               | TOTAL_ROW_VERSIONS
-- → shop/orders        |                   3
```

> **Эксплуатационный вывод:** серия из десятков `ADD COLUMN` в рамках одного релиза на
> одной таблице приближает таблицу к пределу в 64 версии. Следите за `TOTAL_ROW_VERSIONS`
> и планируйте реконструкцию таблицы, если значение приближается к пределу.

### Как выбрать инструмент

```
Нужно ли менять структуру большой таблицы (>100 GB) на продакшене?
│
├─ Нет → встроенный Online DDL с явными ALGORITHM и LOCK
│
└─ Да → большой ли риск отставания реплик из-за нагрузки на диск?
    │
    ├─ Да → OSC-инструмент: gh-ost (предпочтительно) или pt-online-schema-change
    │
    └─ Нет → встроенный Online DDL, но в окно низкой нагрузки и с контролем лага
```

**gh-ost против pt-online-schema-change**

| Критерий | pt-online-schema-change | gh-ost |
| :--- | :--- | :--- |
| Механизм синхронизации | Триггеры на исходной таблице | События binlog, без триггеров |
| Триггеры на таблице | Работает через `--preserve-triggers` (MySQL 5.7.2+) | Не поддерживаются (ограничение gh-ost) |
| Режим с репликой | Нет | Основной режим — подключение к реплике с миграцией на мастере; `--migrate-on-replica` — миграция на самой реплике (мастер не затрагивается) |
| Приостановка cut-over | Через `--pause-file` | `--postpone-cut-over-flag-file` и интерактивные команды |
| Cut-over | Атомарная подмена имён | Атомарная двухшаговая подмена с sentry table |
| SBR на мастере | Работает | Миграция на реплике не поддерживается — обязателен ROW; при SBR gh-ost работает в основном режиме (через реплику, миграция на мастере) |
| Порог приостановки по умолчанию | `--max-load` = `Threads_running=25` | не задан, задаётся явно |

## Пререквизиты

**Инструменты:**

- `percona-toolkit` 3.7.x (pt-online-schema-change, pt-table-checksum)
- `gh-ost` 1.1+ — бинарник из [releases](https://github.com/github/gh-ost/releases)

**Права отдельной учётной записи инструмента** (не прикладной):

- pt-osc: `SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, TRIGGER, INDEX`
  на таблице; для контроля лага реплик — `REPLICATION CLIENT` и `PROCESS`,
  либо отдельная учётная запись на репликах (`--replica-user`,
  `--replica-password`)
- gh-ost: `ALTER, CREATE, DELETE, DROP, INDEX, INSERT, LOCK TABLES, SELECT,
  TRIGGER, UPDATE` на базе данных; плюс (`SUPER, REPLICATION SLAVE`) либо
  (`REPLICATION CLIENT, REPLICATION SLAVE`) на `*.*`. `SUPER` нужен только
  для `STOP SLAVE`/`START SLAVE` при переключении формата binlog
  (`--switch-to-rbr`); если формат уже ROW — `--assume-rbr` исключает
  необходимость в `SUPER`

**Условия:**

- gh-ost: `binlog_format = ROW` (образ `FULL`) хотя бы на одном сервере
  топологии; реплика — с включёнными `log_bin` и `log_replica_updates`
  (до 8.0.26 — `log_slave_updates`);
  схема таблицы на мастере и реплике идентична; репликация идёт (миграция
  через отстающую реплику невозможна)
- Таблица имеет `PRIMARY KEY` или `UNIQUE KEY` — оба инструмента
  итерируют строки по ключу; у gh-ost ключ не должен содержать `NULL`
  (переопределение — `--allow-nullable-unique-key`)
- Свободное место: примерно 2× размер таблицы (теневая копия с индексами)
- pt-osc: таблица, на которую ссылаются внешние ключи, не мигрируется
  без `--alter-foreign-keys-method`; самоссылающиеся FK не поддерживаются
- gh-ost: таблица не должна иметь триггеров и внешних ключей
  (ограничения инструмента)

## Практические сценарии

### Сценарий 1. Определить, какой алгоритм доступен

Сервер сам сообщает, поддерживает ли он запрошенный алгоритм:

```sql
-- Добавление колонки с требованием INSTANT
ALTER TABLE shop.orders ADD COLUMN channel VARCHAR(32), ALGORITHM=INSTANT;
-- → Query OK, 0 rows affected (0.02 sec)
```

```sql
-- Запрос неподдерживаемого алгоритма: сервер отказывает сразу, до начала работы
ALTER TABLE shop.orders ADD COLUMN tmp INT, ALGORITHM=INSTANT, LOCK=SHARED;
-- → ERROR 1846 (0A000): ALGORITHM=INSTANT is not supported. Reason: LOCK INPLACE is not supported. Try ALGORITHM=COPY.
```

Ключевое поведение: **если указать `ALGORITHM` явно и сервер не может её обеспечить,
операция завершается ошибкой до начала работы.** Не переходит молча на более тяжёлый
алгоритм. Это основная защита от инцидента — всегда указывайте `ALGORITHM` явно.

Проверить на стенде заранее — на копии таблицы, с явным `ALGORITHM`:

```sql
CREATE TABLE shop.orders_dryrun LIKE shop.orders;
INSERT INTO shop.orders_dryrun SELECT * FROM shop.orders LIMIT 10000;

ALTER TABLE shop.orders_dryrun ADD COLUMN channel VARCHAR(32), ALGORITHM=INSTANT;
-- → ERROR 1846 (0A000): ALGORITHM=INSTANT is not supported. Reason: LOCK INPLACE is not supported. Try ALGORITHM=COPY.
--   либо
-- → Query OK, 0 rows affected (0.14 sec)

DROP TABLE shop.orders_dryrun;
```

> **`EXPLAIN ALTER TABLE` в MySQL не существует.** `EXPLAIN` работает только для
> `SELECT`, `TABLE`, `DELETE`, `INSERT`, `REPLACE`, `UPDATE` — DDL он не объясняет.
> Единственный способ узнать заранее, какой алгоритм будет выбран, — выполнить
> `ALTER` с явным `ALGORITHM` на копии таблицы и посмотреть на ошибку или время.

### Сценарий 2. Добавление колонки с параллельной записью (`LOCK=NONE`)

```sql
ALTER TABLE shop.orders
    ADD COLUMN channel VARCHAR(32) AFTER status,
    ALGORITHM=INPLACE, LOCK=NONE;
-- → Query OK, 0 rows affected (412.83 sec)
```

Прогресс операции (MySQL 8.0+) — стадии `ALTER` в `performance_schema`:

```sql
SELECT THREAD_ID, EVENT_NAME, WORK_COMPLETED, WORK_ESTIMATED
FROM performance_schema.events_stages_current
WHERE EVENT_NAME LIKE 'alter table%';
-- → THREAD_ID | EVENT_NAME                             WORK_COMPLETED  WORK_ESTIMATED
-- → 42        | stage/sql/alter table (read PK and...  51234567        1823456789
```

И классический индикатор — состояние сессии в `SHOW PROCESSLIST`:

```sql
SHOW PROCESSLIST;
-- → Id: 42  User: root  Command: Query  State: copy to tmp table
-- →   Info: ALTER TABLE shop.orders ...
```

> **Осторожно:** `LOCK=NONE` разрешает параллельный DML на время перестройки, но начало
> и конец операции всё равно требуют эксклюзивной блокировки метаданных. На большой
> таблице начальная блокировка может длиться долго — это и есть причина, по которой
> добавление колонки на таблице в сотни гигабайт делают через OSC.

### Сценарий 3. Удаление и переименование колонки (8.0.28+ / 8.0.29+)

```sql
-- Переименование: INSTANT доступен с 8.0.28
ALTER TABLE shop.orders RENAME COLUMN cost TO amount, ALGORITHM=INSTANT;
-- → Query OK, 0 rows affected (0.01 sec)

-- Удаление: INSTANT доступен с 8.0.29
ALTER TABLE shop.orders DROP COLUMN obsolete_flag, ALGORITHM=INSTANT;
-- → Query OK, 0 rows affected (0.03 sec)
```

Ограничение общее для INSTANT: операцию нельзя комбинировать с другими изменениями,
не поддерживающими `INSTANT`.

### Сценарий 4. Создание индекса на большой таблице через gh-ost

Два рабочих режима. **Основной** (по умолчанию): gh-ost подключается к
реплике как обычный клиент и как реплика, автоматически находит мастера
и мигрирует на нём, читая binlog реплики — наименее нагружающий мастер
режим, единственный при SBR на мастере. **`--migrate-on-replica`**:
миграция на самой реплике, мастер не затрагивается. `--allow-on-master` —
только для прямого подключения к мастеру (тогда реплика не используется).
Пример — миграция на реплике:

```bash
# /etc/gh-ost.cnf:
# [client]
# user=gh_ost_user
# password=...
gh-ost \
  --host=replica1.internal \
  --conf=/etc/gh-ost.cnf \
  --database=shop \
  --table=orders \
  --alter="ADD INDEX idx_channel_status (channel, status)" \
  --migrate-on-replica \
  --concurrent-rowcount \
  --exact-rowcount \
  --max-load='Threads_running=60' \
  --critical-load='Threads_running=90' \
  --critical-load-interval-millis=5000 \
  --max-lag-millis=2000 \
  --chunk-size=1000 \
  --cut-over=atomic \
  --cut-over-lock-timeout-seconds=3 \
  --default-retries=120 \
  --initially-drop-ghost-table \
  --initially-drop-old-table \
  --postpone-cut-over-flag-file=/var/lib/gh-ost/postpone.flag \
  --execute 2>&1 | tee /var/log/gh-ost/orders_idx_channel_status.log
# → # Migrating shop.orders
# → # Migrating 1823456789 rows; 99% done; 1m12s elapsed; 45s remaining
# → # Copying `shop`.`orders`: 47% 04:29.9; Rows: 12345678; Flushed: 1234567; Sessions: 1; Repl: 0; QPS: 1200
```

| Опция | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `--chunk-size` | `1000` | Строк в итерации копирования; допустимый диапазон 10–100000 |
| `--max-lag-millis` | `1500` | Отставание реплики, при котором копирование приостанавливается |
| `--cut-over` | `atomic` | `atomic` (рекомендуется) или `two-step` (алгоритм Facebook) |
| `--cut-over-lock-timeout-seconds` | `3` | Максимальное время удержания блокировок при попытке подмены |
| `--max-load` | не задан | `status=threshold`; при превышении gh-ost приостанавливается |
| `--critical-load` | не задан | При превышении gh-ost прекращает работу |
| `--critical-load-interval-millis` | `0` | При `0` выход немедленный; иначе — вторая проверка через указанный интервал |
| `--postpone-cut-over-flag-file` | не задан | Пока файл существует, gh-ost откладывает подмену таблиц |
| `--exact-rowcount` | выкл | Точный подсчёт строк вместо оценки |
| `--serve-socket-file` | выбирается автоматически | Unix-сокет для интерактивных команд (сценарий 5); TCP — `--serve-tcp-port` |
| `--initially-drop-ghost-table`, `--initially-drop-old-table` | выкл | Удалить остатки предыдущей миграции перед стартом |
| `--assume-rbr` | выкл | Формат binlog уже ROW: не переключать его, не требует `SUPER` |
| `--switch-to-rbr` | выкл | Переключить `binlog_format` в ROW (требует `SUPER`) |
| `--throttle-control-replicas` | все реплики | Список реплик для проверки лага |

Практика: сначала прогнать без `--execute` (noop-режим). gh-ost выполнит проверки
и покажет, что именно собирается делать, не меняя ничего. Для выработки доверия
к инструменту на своей топологии — `--test-on-replica`: миграция на реплике с
остановкой репликации перед подменой и обратным переключением; обе таблицы
остаются для сравнения.

### Сценарий 5. Управление gh-ost на лету

gh-ost слушает на Unix-сокете (по умолчанию) или TCP и принимает
текстовые команды:

```bash
gh-ost --serve-socket-file=/var/run/gh-ost.sock ...   # запуск с явным сокетом
# либо --serve-tcp-port=10001 для TCP

# Команды отправляются на сокет через netcat:
echo status | nc -U /var/run/gh-ost.sock
# → Migrating `shop`.`orders`; Ghost table is `shop`.`_orders_gst`
# → chunk-size: 1000; max lag: 1500ms; max-load: map[Threads_running:60]
# → Copy: 47%; Applied: 1234567; Backlog: 0/100; Lag: 0.01s; HeartbeatLag: 0.01s
```

| Команда | Действие |
| :--- | :--- |
| `status` | Подробное состояние миграции (прогресс, лаг, пороги) |
| `sup` | Краткое состояние |
| `throttle` | Принудительно приостановить миграцию |
| `no-throttle` | Снять принудительную приостановку |
| `unpostpone` | Разрешить отложенный cut-over и выполнить его |
| `postpone-cut-over-flag-file=<path>` | Отложить cut-over, записав flag-файл в указанный путь |
| `panic` | Аварийно остановить миграцию |
| `chunk-size=<n>`, `max-lag-millis=<ms>`, `max-load=...`, `critical-load=...`, `throttle-control-replicas=...` | Изменить параметры на лету (применяются к следующей итерации копирования) |
| `coordinates`, `applier`, `inspector` | Текущие binlog-координаты, хосты applier и inspector |
| `help` | Список команд |

Текущее значение параметра — команда с `?`:
`echo chunk-size=? | nc -U /var/run/gh-ost.sock`.

Отложить подмену до окна обслуживания:

```bash
touch /var/lib/gh-ost/postpone.flag
# → # Migrating 100% done; 3m12s elapsed; 0s remaining
# → # Postponed cut-over. Waiting indefinitely.

# В назначенное окно
rm /var/lib/gh-ost/postpone.flag
# → # Starting cut-over
# → # Cut-over completed successfully
```

Флаг-файл работает, только если его путь совпадает с путём в
`--postpone-cut-over-flag-file`; интерактивно то же делает команда
`postpone-cut-over-flag-file=/var/lib/gh-ost/postpone.flag`.

### Сценарий 6. Создание индекса через pt-online-schema-change

```bash
pt-online-schema-change \
  --host=master.internal \
  --user=ptosc_user \
  --ask-pass \
  --alter "ADD INDEX idx_channel_status (channel, status)" \
  --max-load 'Threads_running=40' \
  --critical-load 'Threads_running=70' \
  --max-lag 2 \
  --check-interval 2 \
  --progress time,60 \
  --chunk-size 1000 \
  --dry-run \
  --print \
  D=shop,t=orders
# → --alter "ADD INDEX idx_channel_status (channel, status)"
# → CREATE TABLE `shop`.`_orders_new` (... KEY `idx_channel_status` (channel,status) ...) ENGINE=InnoDB;
# → DROP TRIGGER IF EXISTS `shop`.`pt_osc_shop_orders_ins`;
# → ... остальные шаги плана без выполнения
```

Ключевые опции:

| Опция | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `--max-load` | `Threads_running=25` | Приостановка копирования при превышении |
| `--critical-load` | `Threads_running=50` | Прерывание работы при превышении |
| `--max-lag` | `1s` | Приостановка при превышении отставания реплик |
| `--check-interval` | `1` | Интервал проверки отставания, секунды |
| `--progress` | `time,30` | Периодичность отчётов о прогрессе (STDERR) |
| `--check-plan` | `yes` | Проверка плана исполнения запросов, которыми оперирует инструмент; при плохом плане — остановка |
| `--chunk-time` | `0.5` | Динамическая подстройка размера чанка под это время выполнения запроса |
| `--chunk-size-limit` | `4.0` | Допустимое превышение оценки размера чанка; `0` — без проверки |
| `--sleep` | `0` | Пауза после каждого чанка, секунды (например, `0.1`) |
| `--dry-run` | выкл | Создать и изменить теневую таблицу без триггеров и копирования |
| `--print` | выкл | Выполняемые SQL-команды в STDOUT |
| `--execute` | выкл | Реальное выполнение (обязателен для миграции) |
| `--pause-file` | не задан | Пока файл существует, копирование приостановлено |
| `--[no]drop-old-table` | `yes` | Удалить исходную таблицу после успешной подмены; `--no-drop-old-table` сохраняет её для сверки |
| `--[no]check-unique-key-change` | `yes` | Отказ от миграции при добавлении уникального индекса: копирование через `INSERT IGNORE` молча теряет дубликаты |
| `--tries` | `create_triggers:10:1, copy_rows:10:0.25, swap_tables:10:1` | Повторы критических операций при lock-wait timeout и deadlock |
| `--set-vars` | `wait_timeout=10000, innodb_lock_wait_timeout=1, lock_wait_timeout=60` | Переменные сессии инструмента |

Все опции указываются **до** DSN; DSN (`D=shop,t=orders`) —
последний аргумент команды. Опция после DSN не распознаётся.
`--dry-run` создаёт и изменяет теневую таблицу, но не создаёт
триггеры и не копирует данные; без `--execute` инструмент
выполняет проверки безопасности и выходит.

```bash
# Реальное выполнение
pt-online-schema-change ... D=shop,t=orders --execute
# → Copying `shop`.`orders`:  25% 03:30.9; Rows: 9123456; Flushed: 4567890; Sessions: 1; Repl: 0; QPS: 450
```

### Сценарий 7. Что делать, если миграция упала

Отказ на любом этапе OSC оставляет исходную таблицу на месте — конструкция теневой
таблицы спроектирована так, чтобы при сбое просто остановиться.

```bash
# Остатки миграции: у обоих инструментов имена с ведущим подчёркиванием
mysql -e "SHOW TABLES LIKE '\_orders\_%'"
# → Tables_in_shop
# → _orders_new   pt-online-schema-change: теневая таблица с новой схемой
# → _orders_old   pt-online-schema-change: исходная таблица после подмены
# → _orders_gho   gh-ost: ghost-таблица
# → _orders_ghc   gh-ost: таблица чекпоинтов
# (суффикс таблиц gh-ost зависит от версии — уточняйте выводом SHOW TABLES)

# Размер теневых таблиц (инструмент копирования живёт, пока работает процесс)
mysql -e "SELECT TABLE_NAME, (DATA_LENGTH+INDEX_LENGTH)/1024/1024 AS mb
          FROM INFORMATION_SCHEMA.TABLES
          WHERE TABLE_SCHEMA='shop' AND TABLE_NAME LIKE '\_orders\_%'"
```

| Ситуация | Действие |
| :--- | :--- |
| Инструмент прерван по `--critical-load`, теневые таблицы остались | Удалить теневые таблицы (`DROP TABLE`), повторить с более консервативными порогами; перед повторным запуском gh-ost — `--initially-drop-ghost-table --initially-drop-old-table` |
| Процесс убит на копировании | gh-ost: повторный запуск с теми же параметрами возобновляет миграцию с чекпоинта. pt-osc: копирование начинается заново; возобновление возможно через `--resume <job_id>`, если предыдущий запуск был с `--history`, `--no-drop-new-table` и `--no-drop-triggers` |
| Cut-over не выполнен, данные синхронизированы | gh-ost: интерактивная команда `unpostpone` или снятие flag-файла; pt-osc: повторный запуск доводит миграцию до подмены |
| Cut-over выполнен, но началась авария | Вернуть исходное состояние см. «Откат cut-over» |

> **Очистка после успешной миграции.** pt-osc по умолчанию удаляет
> `_orders_old` сразу после подмены (`--drop-old-table` по умолчанию
> `yes`); чтобы сверить данные перед удалением, запускайте с
> `--no-drop-old-table`. gh-ost удаляет свои таблицы самостоятельно.

Откат выполненной подмены (имена таблиц возвращаются обратно):

```sql
-- После подмены: shop.orders — новая таблица, shop._orders_old —
-- исходные данные (сохранена при запуске с --no-drop-old-table)
RENAME TABLE shop.orders      TO shop._orders_abandoned,
             shop._orders_old TO shop.orders;
```

> **Осторожно:** откат cut-over — операция с переименованием таблиц на работающей системе.
> Все три `RENAME` выполняются атомарно в одном операторе, но между моментом сбоя подмены
> и этим откатом приложение писало в новую таблицу. Откат уничтожает эти изменения.
> Применять только при полной остановке записи в таблицу.

### Сценарий 8. Проверка результата миграции

```bash
# Сверка данных: запускать на источнике (или на инстансе,
# где произошёл cut-over); чтение обеих таблиц не блокирует DML
pt-table-checksum --replicate=percona --host=master.internal \
  --tables shop._orders_old,shop.orders
# → TS             ERRORS  DIFFS  ROWS       CHUNKS  SKIPPED  TIME   TABLE
# → 10-03T14:22:01 0       0      1823456789 1       0        03:30  shop._orders_old
# → 10-03T14:25:32 0       0      1823456789 1       0        03:29  shop.orders

# Контрольные суммы записываются в таблицу --replicate:
# совпадение this_cnt и this_crc означает идентичность данных
mysql -e "SELECT tbl, this_cnt, this_crc FROM percona.checksums
          WHERE db='shop' ORDER BY tbl"
# → tbl           this_cnt    this_crc
# → _orders_old   1823456789  993177018473
# → orders        1823456789  993177018473
```

Дополнительно:

```sql
-- Контрольная сумма таблицы (оператор, не запрос)
CHECKSUM TABLE shop.orders;
-- → Table        Checksum
-- → shop.orders  993177018473

-- Структура после подмены
SHOW CREATE TABLE shop.orders\G
-- → CREATE TABLE `orders` (... KEY `idx_channel_status` (`channel`,`status`) ...) ENGINE=InnoDB

-- Индекс действительно используется
EXPLAIN SELECT * FROM shop.orders WHERE channel = 'web' AND status = 'new';
-- → key: idx_channel_status  rows: 15  Extra: Using index condition
```

### Сценарий 9. Оценка влияния на реплики

```sql
-- До запуска: состояние IO-потока (подключение к источнику)
SELECT CHANNEL_NAME, SERVICE_STATE, LAST_ERROR_MESSAGE
FROM performance_schema.replication_connection_status\G

-- Состояние SQL-потока (применение)
SELECT CHANNEL_NAME, SERVICE_STATE, LAST_ERROR_MESSAGE
FROM performance_schema.replication_applier_status\G

-- Наблюдение за рабочими потоками в процессе копирования
SELECT CHANNEL_NAME, WORKER_ID, THREAD_ID, SERVICE_STATE,
       LAST_SEEN_TRANSACTION, APPLYING_TRANSACTION
FROM performance_schema.replication_applier_status_by_worker\G
```

Порог `--max-lag` (pt-osc) срабатывает по `Seconds_Behind_Source`
(в MySQL 8.0 — `Seconds_Behind_Master`) на всех подключённых
репликах; gh-ost измеряет собственный лаг по heartbeat-событиям
миграции (поля `Lag` и `HeartbeatLag` в выводе `status`).
Инструмент не «догоняет» отставание — он останавливается и ждёт.
Это осознанное поведение: лучше дольше, чем усугубить лаг.

### Сценарий 10. Порядок работы в производстве (runbook)

```
1. Убедиться, что бэкап свежий и восстановление отработано
2. Оценить объём: SELECT COUNT(*), DATA_LENGTH + INDEX_LENGTH из TABLES;
   проверить свободное место (~2× размер таблицы)
3. Столбец/индекс добавляется? → проверить доступность INSTANT:
   пробный ALTER на копии таблицы с явным ALGORITHM
4. Поддерживается ли INSTANT (или операция мелкая)?
   ├─ Да → ALTER с явными ALGORITHM=INSTANT и LOCK=NONE в окно низкой нагрузки
   └─ Нет → OSC-инструмент
5. Для OSC: подготовить отдельного пользователя с минимальными правами
6. Прогнать инструмент в проверочном режиме (pt-osc: `--dry-run`
   без `--execute`; gh-ost: без `--execute` — noop) — проверить план
7. Запустить в мониторингом состоянии; задать консервативные пороги нагрузки и лага
8. Дождаться 100% копирования; проверить лаг реплик
9. Отложить cut-over до окна (flag-файл / pause-file)
10. В окне: снять флаг, выполнить cut-over
11. Проверить: SHOW CREATE TABLE, EXPLAIN, pt-table-checksum
12. Удалить теневые таблицы, если они остались
13. Удалить пользователя инструмента, если он больше не нужен
```

## Устранение неисправностей (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `ERROR 1846`: `ALGORITHM=INSTANT is not supported` | Операция не поддерживает INSTANT либо требуемый `LOCK` недостижим | Прочитать текст `Reason` в ошибке; выбрать подходящую комбинацию `ALGORITHM`/`LOCK` или перейти на OSC |
| `ERROR 4092`: превышен максимально допустимый размер строки | Добавление колонки выводит строку за пределы | Проверить суммарную длину `VARCHAR` в строке; уменьшить длину новой колонки или перейти на `INPLACE`/`COPY` |
| `ERROR 4158`: `Column can't be added ... anymore` | Достигнут предел в 1022 колонки во внутреннем представлении | Реконструировать таблицу |
| `ERROR 1846` при `LOCK=SHARED` | Запрошенный уровень блокировки недостижим для данной операции (см. `Reason` в тексте ошибки) | Выбрать допустимую комбинацию `ALGORITHM`/`LOCK` или перейти на OSC |
| Подмены не происходит, миграция «висит» на 100% | Включено отложенное переключение | Проверить flag-файл `--postpone-cut-over-flag-file`; для pt-osc — `--pause-file` |
| pt-osc отказывается работать | На исходной таблице уже есть триггеры | Убрать триггеры или использовать `--preserve-triggers`; альтернатива — встроенный Online DDL (gh-ost триггеры не поддерживает) |
| pt-osc отказывается добавлять уникальный индекс | Защита по умолчанию: копирование использует `INSERT IGNORE`, дубликаты молча теряются (`--check-unique-key-change=yes`) | Проверить дубликаты запросом из вывода инструмента; при их отсутствии — повторить с `--no-check-unique-key-change`, либо использовать встроенный Online DDL |
| pt-osc отказывается работать с таблицей, на которую ссылаются FK | Метод обработки ограничений не задан | Задать `--alter-foreign-keys-method` (`rebuild_constraints`, `drop_swap` или `none`); самоссылающиеся FK не поддерживаются |
| gh-ost отказывается мигрировать таблицу | На таблице есть триггеры или внешние ключи | Ограничение gh-ost; использовать pt-osc (триггеры — `--preserve-triggers`) или встроенный Online DDL |
| pt-osc / gh-ost отказываются запускаться | У таблицы нет `PRIMARY KEY` или `UNIQUE KEY` (у gh-ost также ключ с `NULL`-колонками) | Оба инструмента копируют порциями по ключу; без ключа — только встроенный DDL |
| gh-ost требует ROW-формат binlog | Statement-Based Replication на реплике не поддерживается | Переключить `binlog_format = ROW` |
| pt-osc прерывается с ошибкой про replication filters | На сервере заданы фильтры репликации (`binlog_ignore_db`, `replicate_do_db` и т. п.) | Проверка `--check-replication-filters` (по умолчанию `yes`) защищает от потери изменений на фильтрующей реплике; убрать фильтры или пересмотреть топологию |
| INPLACE-ALTER прерывается ошибкой про online alter log | Параллельный DML во время перестройки заполнил буфер изменений | Увеличить `innodb_online_alter_log_max_size` (по умолчанию 128 МБ) или снизить нагрузку на время `ALTER` |
| Резкий лаг реплик во время копирования | Копирование создаёт большой поток событий | Снизить `--chunk-size`, отключить binlog на теневой таблице или перенести копирование на реплику |
| `TOTAL_ROW_VERSIONS` близок к 64 | Накопление версий строк от серии INSTANT-операций | Запланировать реконструкцию таблицы |

## Лучшие практики

- **Всегда указывать `ALGORITHM` и `LOCK` явно.** Неявный выбор означает, что версия
  сервера или состояние таблицы определят метод — и это произойдёт в проде.
- **Инструменту — отдельный пользователь с минимальными правами.** У pt-osc и gh-ost
  разные наборы привилегий; выдача прав от имени прикладной учётной записи нарушает
  принцип наименьших привилегий и затрудняет аудит.
- **Первый запуск всегда — проверочный**, без `--execute`. Большинство неприятностей
  обнаруживается на этапе плана.
- **Пороги нагрузки задавать консервативно.** Значения по умолчанию у pt-osc
  (`Threads_running=25` и `50`) взяты из практики Facebook и для многих инсталляций
  слишком агрессивны либо слишком мягки — калибруйте по своему нормальному состоянию.
- **Cut-over делать в отдельное окно.** Копирование можно крутить весь день, подмену —
  нет.
- **Сверять данные после подмены.** `pt-table-checksum` занимает минуты и снимает
  вопрос «а не потеряли ли мы строки».
- **Готовить откат заранее.** Выяснить реальные имена теневых таблиц нужно до cut-over:
  после подмены они уже другие.
- **gh-ost — сначала `--test-on-replica`.** Миграция на реплике с остановкой
  репликации перед подменой и обратным переключением: обе таблицы остаются на
  месте для сравнения, мастер не затрагивается.
- **Держите старую таблицу до сверки.** pt-osc удаляет `_orders_old` сразу после
  подмены; `--no-drop-old-table` оставляет её для `pt-table-checksum`.

## Дополнительная информация

### Ограничения Online DDL со стороны продукта

- `FULLTEXT` и `SPATIAL` индексы выполняются `ALGORITHM=INPLACE`, но **не разрешают параллельный DML** — запись блокируется на время операции. Первый `FULLTEXT`-индекс перестраивает таблицу при отсутствии пользовательской колонки `FTS_DOC_ID`
  с блокировкой записи.
- Multi-valued индексы — функциональные индексы поверх скрытой виртуальной колонки; применимый `ALGORITHM` проверяется пробным `ALTER` с явным значением на копии таблицы.
- На очень больших таблицах `ALGORITHM=INPLACE` способен вызвать лаг реплик из-за объёма
  изменений в redo log.
- Удаление первичного ключа не поддерживает ни `INSTANT`, ни `INPLACE`.
- Добавление вторичного индекса — `INPLACE` без перестройки таблицы: индекс строится
  отдельным проходом по кластерному индексу. Таблица не копируется, но операция
  нагружает диск и redo log, поэтому на больших таблицах способна вызвать лаг реплик.

### Внешние ресурсы

- [MySQL Reference Manual: InnoDB Online DDL Operations](https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl-operations.html)
- [MySQL Reference Manual: ALTER TABLE Statement](https://dev.mysql.com/doc/refman/8.0/en/alter-table.html)
- [Percona Toolkit: pt-online-schema-change](https://docs.percona.com/percona-toolkit/pt-online-schema-change.html)
- [Percona Toolkit: pt-table-checksum](https://docs.percona.com/percona-toolkit/pt-table-checksum.html)
- [gh-ost: Cut-over step](https://github.com/github/gh-ost/blob/master/doc/cut-over.md)
- [gh-ost: Interactive commands](https://github.com/github/gh-ost/blob/master/doc/interactive-commands.md)

### См. также

- **[Индексы в MySQL](../indexing.md)** — безопасное добавление индексов, невидимые
  индексы, версии поддержки.
- **[Обслуживание и обновления MySQL](../maintenance-and-upgrades.md)** —
  дефрагментация, `OPTIMIZE TABLE`, обновление статистики.
- **[Репликация MySQL](../replication/overview.md)** — отставание реплик, формат binlog.
- **[Проверки консистентности репликации](../replication/consistency_checks.md)** —
  `pt-table-checksum` в контексте сверки источника и реплики.
- **[Стратегии миграций БД](../../Concepts/migrations/migration_basics.md)** —
  общие принципы миграций и откат.
- **[Типовые сценарии миграций](../../Concepts/migrations/scenarios.md)** — сценарий
  Online Schema Change в общем виде.
- **[Безопасные массовые операции с данными](../../Concepts/safe_large_scale_data_modification.md)** —
  батчинг и `pt-archiver`.
- **[Metadata locks](../Concepts/metadata_locking.md)** — механика MDL, фазы
  блокировок Online DDL, приоритет запросов.
- **[Внешние ключи](../foreign_keys.md)** — ограничения FK для `gh-ost` и
  `pt-online-schema-change`.