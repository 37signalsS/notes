# Онлайн-изменение схемы (Online DDL) в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

| Термин | Значение |
|---|---|
| **Online DDL** | Изменение схемы, при котором не требуется блокировка таблицы на всё время операции. InnoDB выполняет её, применяя оптимизации и избегая копирования таблицы |
| **`ALGORITHM`** | Clause `ALTER TABLE`, задающий **наименее эффективный** алгоритм, который готов принять пользователь |
| **`LOCK`** | Clause `ALTER TABLE`, задающий стратегию блокирования, которую готов принять пользователь |
| **`LOCK=NONE`** | Разрешает весь параллельный DML. Эквивалент — `ALTER ONLINE TABLE` |
| **Non-canonical storage format** | Неканонический формат хранения, который может возникнуть в tablespace после операций INSTANT. Нормализуется через `ALTER TABLE ... FORCE` с `ALGORITHM=INPLACE` |
| **`FTS_DOC_ID`** | Скрытая колонка, добавляемая InnoDB при создании FULLTEXT-индекса. Её наличие блокирует INSTANT для `ADD COLUMN` |
| **Online alter log** | Временный лог, фиксирующий изменения, которые DML выполняют параллельно с операцией |

## Требования и предпосылки

Перед запуском онлайн-DDL убежесь, что выполнены предпосылки:

### Привилегии

| Операция | Требуемые привилегии |
|---|---|
| `ALTER TABLE` | `ALTER` на таблицу или базу |
| `RENAME TABLE` | `DROP`, `CREATE`, `INSERT` на источник и приёмник |
| `pt-online-schema-change` | `ALTER`, `CREATE`, `INSERT`, `DELETE`, `TRIGGER`, `EVENT`, `LOCK TABLES` на таблицу |
| `gh-ost` | `SUPER` или `CONNECTION ADMIN`, `REPLICATION SLAVE`, `REPLICATION CLIENT`, `EVENT`, `TRIGGER` для создания/удаления триггеров на staging-таблице |

### Требования к таблице

- Таблица должна использовать движок **InnoDB** (Online DDL поддерживаются только им).
- Для `ALGORITHM=INSTANT` таблица не должна содержать скрытую колонку `FTS_DOC_ID` (т.е. не иметь FULLTEXT-индекса) и иметь `ROW_FORMAT` отличный от `COMPRESSED`.
- Таблицы с более чем одним FULLTEXT-индексом нельзя перестроить никакой операцией `ALTER TABLE` при `ALGORITHM=INPLACE`.
- Таблицы с существующими пользовательскими триггерами не подходят для `pt-online-schema-change` (он создаёт свои триггеры).

### Требования к системе

- **Дисковое пространство:** `tmpdir` и `datadir` должны иметь свободное место не менее размера исходной таблицы (временные таблицы `#sql*` могут стать больше таблицы в некоторых случаях).
- **Переменные InnoDB:** при длительном DDL на большой таблице рекомендуется увеличить `innodb_online_alter_log_max_size` и `innodb_log_file_size` — см. [InnoDB: долговечность и настройка записи](./innodb_durability_tuning.md).
- **Репликация:** при включённой репликации используйте `SET SESSION binlog_alter_two_phase = TRUE` для сокращения лага репликации (MariaDB 10.8+).

## Основные концепции

### Иерархия алгоритмов

Алгоритмы образуют иерархию «от наименее эффективного к наиболее эффективному»:

```
COPY  →  INPLACE  →  NOCOPY  →  INSTANT
```

Ключевое правило: **если указан `COPY`, используется `COPY`. Если указан любой другой алгоритм, InnoDB трактует выбор как наименее эффективный приемлемый и берёт самый эффективный из поддерживаемых операцией.**

Документированные примеры:

- `ALGORITHM=INPLACE` и операция поддерживает `INSTANT` → выполняется `INSTANT`.
- `ALGORITHM=NOCOPY` → выполняется самый эффективный из набора (`NOCOPY`, `INSTANT`).
- `ALGORITHM=DEFAULT` или отсутствие clause → самый эффективный поддерживаемый операцией алгоритм. Если операция не поддерживает INSTANT, но поддерживает NOCOPY — берётся NOCOPY, и так далее.

Соотношение множеств поддерживаемых операций — **вложенность, а не расширение**: операции, поддерживаемые `INPLACE`, образуют надмножество поддерживаемых `NOCOPY`, а `NOCOPY` — надмножество поддерживаемых `INSTANT`.

> [!note] Что даёт `NOCOPY`
> Назначение `NOCOPY` — сузить `INPLACE`, вырезав операции, при которых InnoDB всё равно перестраивал бы кластерный индекс, а вместе с ним и всю таблицу. Практически `NOCOPY` добавляет к возможностям `INSTANT` именно индексные операции (`ADD INDEX`, `ADD SPATIAL INDEX`, `ADD FOREIGN KEY` при `foreign_key_checks=OFF`), которые в `INPLACE` выполняются без перестроения таблицы.
>
> Отдельный случай: `DROP COLUMN` индексированной колонки недопустим при `INSTANT` (поскольку подразумевает `DROP INDEX`), но разрешён при `NOCOPY`.

### Почему явный `ALGORITHM` полезен

Если операция не поддерживает запрошенный алгоритм, InnoDB **возвращает ошибку, а не откатывается к `COPY`**:

```sql
SET SESSION alter_algorithm='INPLACE';
ALTER TABLE tab MODIFY COLUMN c INT;
-- → ERROR 1846 (0A000): ALGORITHM=INPLACE is not supported. Reason: Cannot change column type INPLACE. Try ALGORITHM=COPY
```

Логика задокументирована явно: ошибка предпочтительнее, чем копирование таблицы и неожиданно низкая производительность. Для планирования изменений это означает, что `ALTER TABLE ... ALGORITHM=X` служит проверкой: операция либо выполнится с заданной ценой, либо откажется сразу.

Для DML-параллелизма накладывают `LOCK`:

```sql
ALTER TABLE tab ADD COLUMN c VARCHAR(50), ALGORITHM=INPLACE, LOCK=NONE;
```

### ALGORITHM=INSTANT: поддерживаемые операции и ограничения

Поддерживаются: `ADD COLUMN` (независимо от позиции в списке колонок), `DROP COLUMN`, `MODIFY COLUMN` (переупорядочивание, изменение длины `VARCHAR`, добавление значения `ENUM`/`SET` в конец списка, снятие system versioning), `ALTER COLUMN ... SET/DROP DEFAULT`, `CHANGE COLUMN` (переименование без изменения типа и атрибутов), `DROP FOREIGN KEY`, `DROP CONSTRAINT` (CHECK), `AUTO_INCREMENT=...`, `PAGE_COMPRESSED=1` и `PAGE_COMPRESSION_LEVEL=...`, `RENAME TO`, `RENAME TABLE`.

Не поддерживаются: `ADD`/`DROP PRIMARY KEY`, `ADD INDEX` (включая FULLTEXT и SPATIAL), `ADD FOREIGN KEY`, `MODIFY ... NOT NULL`, смена типа колонки, `ROW_FORMAT=...`, `KEY_BLOCK_SIZE=...`, `PAGE_COMPRESSED` из `1` в `0`, `DROP SYSTEM VERSIONING`, `FORCE`, `ENGINE=InnoDB`, `OPTIMIZE TABLE`.

```sql
ALTER TABLE tab ADD COLUMN c VARCHAR(50), ALGORITHM=INSTANT;
-- → ERROR 1846 (0A000): ALGORITHM=INSTANT is not supported. Reason: Changing table options requires the table to be rebuilt. Try ALGORITHM=INPLACE
```

Документированные ограничения INSTANT:

| Ограничение | Следствие |
|---|---|
| Таблица содержит скрытую колонку `FTS_DOC_ID` (то есть уже есть FULLTEXT-индекс) | `ADD COLUMN` не может быть INSTANT |
| `ROW_FORMAT=COMPRESSED` | INSTANT для `ADD COLUMN` недоступен |
| Добавление колонки `NOT NULL` | Требуется значение `DEFAULT` — подразумеваемое типом или заданное явно. Выражение не обязано быть константой, но не должно ссылаться на колонки таблицы |
| Данные файлов после INSTANT `ADD COLUMN` | Не могут быть импортированы в более старые версии MariaDB или MySQL без предварительного перестроения |
| Generated-колонки | Поддерживают не все операции, доступные обычным колонкам |
| Non-canonical storage format | Возникает при INSTANT для `ADD COLUMN`, `DROP COLUMN`, переупорядочивания. Скрытая запись метаданных в начале кластерного индекса хранит `DEFAULT` каждой колонки и может добавить накладные расходы к последующим DML. Нормализация — `ALTER TABLE ... FORCE` с `ALGORITHM=INPLACE` |

Документация отдельно предупреждает: `There are some known bugs that could lead to issues when an InnoDB DDL operation is performed using the INSTANT algorithm. This algorithm will usually be chosen by default if the operation supports the algorithm.` — то есть дефект может быть неочевиден, поскольку INSTANT выбирается по умолчанию.

### ALGORITHM=INPLACE: когда таблица всё равно перестраивается

Формулировка документации: `The table is rebuilt, which means that all of the data is reorganized substantially, and the indexes are rebuilt. As a result, the operation is quite expensive.`

Эта цена applies к: `ADD COLUMN`, `DROP COLUMN`, переупорядочиванию колонок, смене типа между `NULL` и `NOT NULL`, `ADD PRIMARY KEY`, `ROW_FORMAT=...`, `KEY_BLOCK_SIZE=...`, `FORCE`, `ENGINE=InnoDB`, `OPTIMIZE TABLE` (когда `innodb_defragment` и `innodb_optimize_fulltext_only` обе выключены).

Без перестроения выполняются операции, меняющие только метаданные: добавление значения `ENUM`/`SET`, `ALTER COLUMN SET/DROP DEFAULT`, `CHANGE COLUMN`, `DROP INDEX`, `ADD`/`DROP FOREIGN KEY`, `DROP SYSTEM VERSIONING`, `RENAME TO`, `AUTO_INCREMENT=...`.

Дополнительно документировано: `INPLACE is a bit of a misnomer, since some operations may still require the table to be rebuilt for some storage engines` — точнее было бы назвать алгоритм `ENGINE`, поскольку конкретную реализацию выбирает движок.

Частный случай с `DROP PRIMARY KEY`: `InnoDB only supports this operation with ALGORITHM set to COPY. Concurrent DML is not permitted.` Исключение — одновременное удаление старого и добавление нового первичного ключа, тогда операция выполняется с `ALGORITHM=INPLACE`.

### Ресурсы, которые расходуют онлайн-DDL

| Ресурс | Параметр | Поведение |
|---|---|---|
| Временные логи DML | `innodb_online_alter_log_max_size` | Global, Dynamic: Yes, default `134217728`, диапазон `65536`…`2^64-1`. При превышении операция онлайн-DDL завершается ошибкой и все незакоммиченные изменения откатываются |
| Временные файлы сортировки | `innodb_tmpdir` | Global, Dynamic: Yes, default пусто — файлы создаются в обычном `tmpdir`. Альтернативный путь должен находиться вне `datadir` |
| Временные таблицы перестроения | Автоматически | Файлы вида `#sql${PID}_${THREAD_ID}_${TMP_TABLE_COUNT}.ibd` и `#sql-ib${TABLE_ID}.ibd` появляются в `datadir` |

Документация предупреждает: хранилище для временных объектов «can add up to the size of the original table, or more in some cases». Это планирование дискового пространства, а не только времени.

Про `ALGORITHM=COPY` на InnoDB: операция перестраивает таблицу с текущими значениями `innodb_file_per_table` и `innodb_default_row_format`, вставляет записи по одной в каждый индекс, не использует sort buffer, создаёт много redo log и заметно меньше undo log.

Связь `innodb_tmpdir` с sort-файлами онлайн-DDL в документации **не заявлена**: переменная описана как «temporary non-tablespace files». Если размещаете `tmpdir` на отдельном устройстве, ориентируйтесь на общий объём временных файлов, а не на предположение о конкретном назначении каталога.

### Стратегии блокирования

| Стратегия | Поведение | Параллельный DML |
|---|---|---|
| `DEFAULT` | Берётся наименее строгая блокировка, поддерживаемая операцией | Максимально возможный для операции |
| `NONE` | Без блокировки таблицы | Весь |
| `SHARED` | После взятия блокировки чтения | Только чтение |
| `EXCLUSIVE` | После взятия блокировки записи | Никакой |

Неподдерживаемая стратегия даёт ошибку, а не ослабление. `ALTER ONLINE TABLE` эквивалентен `LOCK=NONE`.

> [!warning] Эксклюзивное окно есть всегда
> Документация: `Regardless of which locking strategy is used to perform a DDL operation, InnoDB will have to exclusively lock the table for a short time at the start and end of the operation's execution. This means that any active transactions that may have accessed the table must be committed or aborted for the operation to continue.`
>
> Это утверждение не делает исключений для `LOCK=NONE` и `ALGORITHM=INSTANT`, то есть INSTANT сокращает окно, но не отменяет его. Подробно — в [Блокировки метаданных](../Concepts/metadata_locking.md).
>
> Отдельные ограничения: если у таблицы есть FULLTEXT-индекс, её нельзя перестроить при `LOCK=NONE`; то же верно для SPATIAL-индекса. За один раз разрешено добавлять не более одного FULLTEXT-индекса при `ALGORITHM=INPLACE`, и то же ограничение действует для `NOCOPY`. Таблицу с более чем одним FULLTEXT-индексом нельзя перестроить никакой операцией `ALTER TABLE` при `ALGORITHM=INPLACE`.

Добавление FULLTEXT-индекса через `NOCOPY` имеет отдельную оговорку: для таблицы без пользовательского `FTS_DOC_ID` таблица будет перестроена один раз, и эта первая операция обязана выполняться с `ALGORITHM=INPLACE`.

### Управление ожиданием: `WAIT n` и `NOWAIT`

Обе конструкции входят в синтаксис `ALTER TABLE` и переопределяют `lock_wait_timeout` для конкретного оператора. Документированный синтаксис `WAIT n | NOWAIT` применяется к `ALTER TABLE`, `CREATE INDEX`, `DROP INDEX`, `DROP TABLE`, `LOCK TABLE`, `OPTIMIZE TABLE`, `RENAME TABLE`, `TRUNCATE TABLE`, `SELECT ... FOR UPDATE`, `SELECT ... LOCK IN SHARE MODE`. `WAIT 0` эквивалентен `NOWAIT`.

```sql
ALTER TABLE orders ADD COLUMN status VARCHAR(16), ALGORITHM=INSTANT, NOWAIT;
```

Практическая ценность: без явного `WAIT`/`NOWAIT` DDL ждёт до истечения `lock_wait_timeout`, и всё это время приложение может исчерпать пул соединений. Версию появления конструкций и код ошибки для `NOWAIT` официальная документация не указывает — см. предупреждение в [transactions_and_locking.md](./transactions_and_locking.md).

### `alter_algorithm` и `old_alter_table`

| Переменная | Статус |
|---|---|
| `alter_algorithm` | Introduced 10.3.7. Scope Global, Session, Dynamic: Yes, Data Type enumerated, default `DEFAULT`, значения `DEFAULT`, `COPY`, `INPLACE`, `NOCOPY`, `INSTANT`. **Deprecated с MariaDB 11.5 и игнорируется** |
| `old_alter_table` | Alias для `alter_algorithm`. **Deprecated с 10.3.7, Removed с MariaDB 11.2.0** |

`alter_algorithm` задаёт подразумеваемый `ALGORITHM` для случая, когда clause не указан, и работает как сессионная настройка:

```sql
SET SESSION alter_algorithm='INPLACE';
ALTER TABLE tab ADD COLUMN c VARCHAR(50);
-- Операция фактически выполнится алгоритмом INSTANT — как более эффективным из допустимых
```

Документация перечисляет причины удаления функциональности: `alter_algorithm` вводил случаи, когда `ALTER TABLE` не работал без явного `ALGORITHM`; разные значения на primary и replica могли приводить к неожиданной остановке реплик; настройка мешала `ALTER TABLE FORCE`, используемому `mariadb-upgrade`.

> [!warning] Не полагайтесь на `alter_algorithm` в 11.8 и 12.3
> Переменная продолжает отображаться в `SHOW VARIABLES`, но её значение игнорируется. Планируйте версию 11.8 / 12.3 — задавайте `ALGORITHM` в самом SQL. Для 10.11 и 11.4 переменная рабочая.

## Практические сценарии

### 1. Безопасное добавление колонки

```sql
ALTER TABLE orders
  ADD COLUMN status VARCHAR(16) DEFAULT 'new',
  ALGORITHM=INSTANT;
```

```bash
mariadb -e "SELECT COUNT(*) FROM orders WHERE status IS NULL;"
# → COUNT(*)
# → 0
```

Если операция прошла, но `ALGORITHM=INSTANT` выдал ошибку, причина читается из текста ошибки — обычно это наличие FULLTEXT-индекса (`FTS_DOC_ID`), `ROW_FORMAT=COMPRESSED` или попытка сменить тип. Проверить скрытую колонку и row format:

```sql
SELECT ROW_FORMAT FROM information_schema.TABLES
WHERE TABLE_SCHEMA='shop' AND TABLE_NAME='orders';
-- → ROW_FORMAT
-- → Dynamic
```

```sql
SHOW INDEX FROM orders WHERE Index_type = 'FULLTEXT';
-- → (пусто — FULLTEXT-индексов нет)
```

### 2. Строгий DDL в пайплайне изменений

Правило: **никогда не выполнять DDL без явного `ALGORITHM` в автоматизации.** Иначе тихая деградация до `COPY` превратится в многочасовую блокировку таблицы.

```sql
-- Приемлемо: добавление индекса в пределах NOCOPY
ALTER TABLE orders ADD INDEX idx_status (status), ALGORITHM=NOCOPY;

-- Приведёт к ошибке 1846, а не к ночному копированию таблицы
ALTER TABLE orders MODIFY COLUMN status ENUM('new','paid','shipped'), ALGORITHM=INSTANT;
```

```bash
mariadb -e "SHOW WARNINGS;"
# → (пусто — операция принята с заявленными ограничениями)
```

### 3. Оценка стоимости до запуска

Проверить, изменится ли INSTANT-колонка на уровне таблицы, и какой алгоритм выберется по умолчанию:

```sql
SELECT TABLE_NAME, ROW_FORMAT, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH
FROM information_schema.TABLES
WHERE TABLE_SCHEMA='shop'
ORDER BY DATA_LENGTH + INDEX_LENGTH DESC
LIMIT 10;
```

```text
+------------+-------------+------------+-------------+--------------+
| TABLE_NAME | ROW_FORMAT  | TABLE_ROWS | DATA_LENGTH | INDEX_LENGTH |
+------------+-------------+------------+-------------+--------------+
| orders     | Dynamic     |     4820113 |   2147483648 |    268435456 |
| order_items| Dynamic     |    20488117 |   1073741824 |    134217728 |
+------------+-------------+------------+-------------+--------------+
```

Для `orders` операция с `ALGORITHM=INPLACE` без перестроения практически исключена — добавление колонки её перестраивает. Единственный способ избежать перестроения — `INSTANT`.

### 4. Планирование дискового пространства

Перед DDL на большой таблице оцените необходимое место: временные логи ограничены `innodb_online_alter_log_max_size`, а временные таблицы могут занять объём порядка размера исходной таблицы.

```bash
df -h /var/lib/mysql
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/vdb1        50G   28G   22G  56% /var/lib/mysql
```

```sql
SET GLOBAL innodb_online_alter_log_max_size = 2147483648;
SELECT @@GLOBAL.innodb_online_alter_log_max_size;
# → 2147483648
```

Увеличение лимита сокращает вероятность отказа операции, но увеличивает время, которое таблица может оставаться заблокированной в конце операции при применении накопленного лога. Это осознанный размен между вероятностью сбоя и длительностью финального окна.

### 5. Ресайз redo log как условие успешного онлайн-DDL

Онлайн-DDL нагружает запись так же, как тяжёлая транзакция. Если redo log мал, высокий темп DML во время операции вызывает частые чекпоинты:

```sql
SET GLOBAL innodb_log_file_size = 2147483648;
```

Ограничения и ошибки этого шага разобраны в [InnoDB: долговечность и настройка записи](./innodb_durability_tuning.md).

### 6. `ALTER` в окружении с репликацией

DDL реплицируется через binlog. Два практических следствия:

- `ALGORITHM` на replica вычисляется заново. Расхождение настроек между источником и репликой — одна из причин, по которым `alter_algorithm` была объявлена deprecated: такие расхождения могли приводить к неожиданной остановке реплик.
- Тяжёлые операции `INPLACE` с перестроением порождают много redo log и binlog, что замедляет применение и расширяет лаг репликации. `LOCK=NONE` не означает, что операция не пишет в binlog.

Планируйте DDL так, чтобы он успевал завершиться до начала пиковой нагрузки, а лаг репликации наблюдался параллельно.

Для сокращения лага репликации на MariaDB 10.8+ включите двухфазную репликацию DDL — операция начинает реплицироваться на реплики сразу после начала выполнения на источнике, а не после завершения:

```sql
SET SESSION binlog_alter_two_phase = TRUE;
ALTER TABLE big_table ADD COLUMN status VARCHAR(16), ALGORITHM=INPLACE, LOCK=NONE;
```

### Мониторинг выполнения DDL

MariaDB поддерживает progress reporting для `ALTER TABLE` — информация доступна через `SHOW PROCESSLIST` и `information_schema.PROCESSLIST`:

```sql
-- Мониторинг прогресса DDL в реальном времени
SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, PROCESSLIST_INFO
FROM information_schema.PROCESSLIST
WHERE COMMAND = 'Query' AND STATE LIKE '%alter%';

-- Пример вывода во время выполнения:
-- ID: 123
-- COMMAND: Query
-- TIME: 342
-- STATE: copy to tmp table
-- PROCESSLIST_INFO: copy to tmp table (46%)
```

```bash
# Через mariadb-admin (удобно для скриптов мониторинга)
mariadb-admin -u monitor -pr processlist | grep -i alter
# → | 123 | admin | host:12345 | shop | Query | 342 | copy to tmp table | copy to tmp table (46%) |
```

Через клиент `mariadb` прогресс отображается автоматически:

```sql
ALTER TABLE large_table ADD INDEX idx_status (status);
Stage: 1 of 2 'copy to tmp table'    46% of stage
```

Для мониторинга через Prometheus/Grafana можно отследить:
- `TIME` в `information_schema.PROCESSLIST` — длительность DDL
- Рост файлов `#sql*` в `datadir` — временные таблицы перестроения
- `SHOW ENGINE INNODB STATUS` — количество pending log и чекпоинтов

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
|---|---|---|---|
| `ERROR 1846 (0A000): ALGORITHM=INSTANT is not supported. Reason: ...` | Операция требует перестроения | Текст `Reason` называет причину | Перейти на `NOCOPY` или `INPLACE`, предварительно оценив перестроение |
| `ERROR 1846 ... Cannot change column type INPLACE. Try ALGORITHM=COPY` | Смена типа поддерживается только копированием | Текст ошибки | Принять `COPY` в окно обслуживания либо использовать `gh-ost`/`pt-online-schema-change` |
| `ERROR 1845 (0A000): ALGORITHM=INSTANT is not supported for this operation. Try ALGORITHM=INPLACE` | Операция несовместима с INSTANT | Текст ошибки | Использовать `INPLACE`; для `MODIFY ... NOT NULL` другого пути нет |
| Онлайн-DDL провалился после длительного времени | Превышен `innodb_online_alter_log_max_size` | `SHOW VARIABLES LIKE 'innodb_online_alter_log_max_size'`, лог ошибок | Увеличить лимит; учесть, что при превышении все незакоммиченные изменения откатываются |
| `ROW_FORMAT=COMPRESSED` исключает INSTANT для `ADD COLUMN` | Документированное ограничение | `SELECT ROW_FORMAT FROM information_schema.TABLES` | Перестроить таблицу без сжатия либо оставить `ALGORITHM=INPLACE` |
| `ADD COLUMN` не получает INSTANT при наличии FULLTEXT-индекса | Скрытая колонка `FTS_DOC_ID` | `SHOW INDEX FROM t WHERE Index_type='FULLTEXT'` | Убрать FULLTEXT-индекс или использовать `INPLACE` |
| Перестроение не удаётся с `ALGORITHM=INPLACE` | Более одного FULLTEXT-индекса, либо FULLTEXT/SPATIAL с `LOCK=NONE` | `SHOW INDEX` | Изменить стратегию блокирования или перестроение вне `LOCK=NONE` |
| `DROP COLUMN` отклонён при `ALGORITHM=INSTANT` | Операция подразумевает `DROP INDEX` | Текст ошибки | Использовать `ALGORITHM=NOCOPY` — этот случай для него разрешён |
| `SET SESSION alter_algorithm` не влияет на поведение | Переменная deprecated и игнорируется с 11.5 | `SHOW VARIABLES LIKE 'alter_algorithm'` | Задавать `ALGORITHM` в SQL; в 10.11 и 11.4 переменная рабочая |
| DDL в очереди, приложение встаёт | Долгая транзакция удерживает метаданные | `performance_schema.metadata_locks`, `SHOW FULL PROCESSLIST` | См. [metadata_locking.md](../Concepts/metadata_locking.md); применять `NOWAIT` |
| Рост I/O и лага репликации во время DDL | Перестроение генерирует много redo log и binlog | `SHOW ENGINE INNODB STATUS`, метрики лага репликации | Перенести в окно низкой нагрузки; выбрать менее дорогой алгоритм |
| После INSTANT-заметны накладные расходы на DML | Non-canonical storage format | — | Нормализация: `ALTER TABLE ... FORCE` с `ALGORITHM=INPLACE` |

## Лучшие практики

- **Всегда задавайте `ALGORITHM` в автоматизированных изменениях схемы.** Это превращает тихую деградацию до `COPY` в явную ошибку `ERROR 1846` до начала копирования.
- **Добавляйте столбцы через `INSTANT`, индексы — через `NOCOPY`.** Это покрывает большинство изменений без перестроения.
- **Объединяйте изменения в один `ALTER TABLE`.** Документация рекомендует это для случаев, когда несколько операций каждая требуют перестроения: перестроение выполняется один раз.
- **Не рассчитывайте на отсутствие блокировки.** Эксклюзивное окно в начале и конце есть при любой стратегии; выигрыш даёт только его сокращение.
- **Держите `tmpdir` и `datadir` на дисках с запасом.** Временные таблицы могут занять объём порядка исходной таблицы или больше.
- **Учитывайте блокировки при выборе стратегии для таблиц с FULLTEXT и SPATIAL.** `LOCK=NONE` для них недоступен.
- **Нормализуйте non-canonical storage format после массовых INSTANT-операций**, если профиль нагрузки чувствителен к накладным расходам DML: `ALTER TABLE ... FORCE` с `ALGORITHM=INPLACE`.
- **Не используйте `alter_algorithm` как основной механизм управления.** Он deprecated с 11.5 и игнорируется; задавайте `ALGORITHM` в SQL.
- **Применяйте `NOWAIT`/`WAIT n` в автоматизации.** Ожидание по умолчанию — до истечения `lock_wait_timeout`, и оно способно исчерпать пул соединений.
- **Наблюдайте за лагом репликации во время DDL.** `LOCK=NONE` не означает, что операция не пишет в binlog.
- **Включайте `binlog_alter_two_phase = TRUE` для тяжёлого DDL на реплицируемых таблицах** (MariaDB 10.8+) — сокращает лаг репликации.
- **Очищайте временные файлы после DDL.** Проверьте отсутствие остаточных `#sql*`-файлов в `datadir`:

```bash
ls -la /var/lib/mysql | grep '#sql'
# → (пусто — все временные файлы удалены InnoDB после DDL)
```

Если временные файлы остались (например, после аварийного завершения), очистите их только после уверенности, что DDL завершился и таблица нормализована.

- **Проверяйте целостность после DDL:**

```sql
CHECK TABLE orders;
ANALYZE TABLE orders;
SHOW INDEX FROM orders;
```

## Ограничения и неподтверждённое

- **Версия появления `WAIT n` / `NOWAIT`** в официальной документации MariaDB не указана.
- **Код ошибки, возвращаемой `NOWAIT`**, официально не документирован: `ERROR 1205` описан как результат истечения таймаута метаданных, а диапазон кодов 3500–3599 в справочнике ошибок MariaDB отсутствует.
- **Связь `innodb_tmpdir` с sort-файлами онлайн-DDL** документацией не заявлена; переменная описана как «temporary non-tablespace files».
- **Влияние `innodb_default_row_format` на доступность INSTANT** не подтверждено. Ограничение документировано только на уровне табличного option `ROW_FORMAT=COMPRESSED`.
- **`LOCK_TYPE` в `performance_schema.metadata_locks`** в документации MariaDB перечислен только как семейство `BACKUP_*`, хотя пример на той же странице показывает `SHARED_READ` — см. [metadata_locking.md](../Concepts/metadata_locking.md).

## Дополнительная информация

### Документация MariaDB

- [InnoDB Online DDL Overview](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/innodb-online-ddl-overview) — иерархия алгоритмов, стратегии блокирования, поведение `COPY`/`INPLACE` на InnoDB
- [Operations with ALGORITHM=INSTANT](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/innodb-online-ddl-operations-with-the-instant-alter-algorithm)
- [Operations with ALGORITHM=INPLACE](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/innodb-online-ddl-operations-with-the-inplace-alter-algorithm)
- [Operations with ALGORITHM=NOCOPY](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/innodb-online-ddl-operations-with-the-nocopy-alter-algorithm)
- [Instant Add Column for InnoDB → Limitations](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-online-ddl/instant-add-column-for-innodb) — `FTS_DOC_ID`, `ROW_FORMAT=COMPRESSED`, требования к `DEFAULT`
- [ALTER TABLE](https://mariadb.com/docs/server/reference/sql-statements/data-definition/alter/alter-table) — clauses `ALGORITHM`, `LOCK`, `WAIT`/`NOWAIT`, обоснование удаления `alter_algorithm`
- [WAIT and NOWAIT](https://mariadb.com/docs/server/reference/sql-statements/transactions/wait-and-nowait) — полный список поддерживаемых операторов
- [InnoDB System Variables](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables) — `innodb_online_alter_log_max_size`, `innodb_tmpdir`
- [Server System Variables](https://mariadb.com/docs/server/server-management/variables-and-modes/server-system-variables) — `alter_algorithm`, `old_alter_table`

### Смежные документы базы знаний

- [Блокировки метаданных](../Concepts/metadata_locking.md) — очередь DDL, диагностика держателей, два таймаута
- [DDL vs DML](../Concepts/DDL_vs_DML.md) — место DDL в конкуренции с DML
- [Транзакции и блокировки](./transactions_and_locking.md) — isolation, таймауты, `WAIT`/`NOWAIT`
- [InnoDB: долговечность и настройка записи](./innodb_durability_tuning.md) — page flushing, размер redo log, влияние на DDL
- [Обслуживание MariaDB](./maintenance.md) — `OPTIMIZE TABLE`, `ANALYZE TABLE`, дефрагментация
- [Движки хранения](./storage_engines.md) — выбор движка, онлайн-миграция между движками
- [Нулевое время простоя при обновлении](./Operations/zero_downtime_upgrade.md) — DDL в контексте мажорного обновления
- **[Индексы](../Concepts/indexes.md)** — почему `CREATE INDEX` и `DROP INDEX` относятся к DDL
- **[Хранимые объекты](./Concepts/stored_objects_management.md)** — триггеры и процедуры, влияние DDL на них
- **[Online Schema Change (MySQL)](../MySQL/Operations/online-schema-change.md)** — pt-osc и gh-ost для больших таблиц, где встроенный Online DDL неприменим