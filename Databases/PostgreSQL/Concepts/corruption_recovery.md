# Восстановление при повреждении данных (Corruption Recovery)

**Актуально для:** PostgreSQL 13–18

В данном документе рассматриваются методы диагностики, локализации и устранения физических и логических повреждений в структурах данных PostgreSQL, а также действия первой реакции, которые определяют, останутся ли данные вообще востребованными.

## Определения

- **Повреждение данных (Data Corruption)** — состояние, при котором физическое содержимое страниц базы данных на диске не соответствует ожидаемому формату или логическим правилам СУБД.
- **Страница (Page)** — блок данных фиксированного размера (по умолчанию 8 КБ, `BLCKSZ` задаётся при компиляции), базовая единица ввода-вывода и хранения в PostgreSQL.
- **Контрольная сумма страницы (Data Checksum)** — хеш-значение, вычисляемое для каждой data-страницы при записи на диск и проверяемое при чтении. Включается для всего кластера целиком (`initdb -k` или офлайн `pg_checksums --enable`), для отдельных баз/таблиц — не бывает. Текущее состояние: `SHOW data_checksums;`.
- **Bit rot (тихая порча данных)** — самопроизвольное изменение битов на носителе, которое может годами оставаться незамеченным без регулярной проверки контрольных сумм.
- **Partial Page Write (разрыв страницы)** — ситуация, когда сбой питания происходит во время записи страницы, и на диске оказывается смесь старых и новых данных. Защита — `full_page_writes = on` (полные образы страниц в WAL).
- **Нулевая страница (zero page)** — страница, полностью заполненная нулями. PostgreSQL читает её как «новую, пустую»; типичный признак обнулённого блока — ошибка `unexpected zero page`. Часто это следствие сбоя записи или ошибки администратора, а не битого диска.
- **Логическое повреждение** — нарушение связей между структурами (например, индекс ссылается на несуществующую строку в таблице), при этом физический формат страниц корректен. Чексуммы его **не** обнаруживают — для этого нужен `amcheck`.
- **CLOG (Commit Log, `pg_xact`)** — SLRU-хранилище статуса транзакций (in-progress / committed / aborted / sub-committed), 2 бита на транзакцию. Файлы именуются 4 hex-цифрами (`0000`, `0001`, …), каждый сегмент — 256 КБ = 1 048 576 транзакций (32 страницы по 8 КБ).
- **Visibility Map (VM)** — отдельный форк relation (`<filenode>_vm`), хранящий по 2 бита на страницу: all-visible и all-frozen. Используется index-only scans и VACUUM; его повреждение диагностируется расширением `pg_visibility`.

## Базовые концепции

### Что защищают чексуммы, а что — нет

Контрольные суммы защищают **только data-страницы**: внутренние структуры (pg_control, CLOG, WAL) и временные файлы не покрыты. Чексуммы ловят физическую порчу при чтении, но не ловят логическую коррупцию и вообще бесполезны, если не включены. `amcheck` эффективен против тех отказов, которые чексуммы не ловят, в том числе при отключённых чексуммах.

### Классификация повреждений

| Класс | Где проявляется | Типичный симптом | Ремонт |
| :--- | :--- | :--- | :--- |
| Страница таблицы (heap) | `base/<dboid>/<filenode>` | `checksum verification failed` | Восстановление / `zero_damaged_pages` / обнуление страницы |
| Индекс | `base/<dboid>/<filenode>` (`relkind = 'i'`) | `unexpected zero page`, `failed to find tuple` | `REINDEX` (дешёвый и надёжный) |
| Системные индексы (`pg_catalog`) | `base/1/` | `FATAL: index "pg_class_oid_index" contains unexpected zero page` | `ignore_system_indexes` + `REINDEX` |
| CLOG (`pg_xact`) | `pg_xact/XXXX` | `could not access status of transaction` | Бэкап; крайняя мера — нулевой сегмент |
| WAL / `pg_control` | `pg_wal/`, `global/pg_control` | база не стартует, `invalid xlog record` | PITR из архива WAL; `pg_resetwal` последним средством |

### Первая реакция (runbook)

Перед любыми ремонтом или диагностикой — зафиксировать доказательства. Попытки починить «на живую» чаще всего разрушают потенциально восстановимые данные, а ремонт уничтожает улики, по которым определяется причина (и предотвращается повторение):

1. Остановить кластер (не работать на живом сервере).
2. Снять **файловый** копию всего каталога данных (`pg_dump` не годится — он не покажет битые страницы).
3. Хранить копию на отключаемом носителе; всю дальнейшую работу проводить **только с копией**.

```bash
pg_ctl stop -m immediate -D /var/lib/postgresql/data
rsync -aHAX /var/lib/postgresql/data/ /mnt/evidence/pgdata-copy/   # → копия на диске
# Копию не монтировать в RW; pg_hexedit и подобные low-level инструменты — только против копии
```

## Инструменты диагностики

### 1. amcheck (логическая проверка B-Tree и heap)

Встроенное расширение для проверки целостности B-Tree индексов и их соответствия таблицам (heap). Устанавливается суперпользователем (`CREATE EXTENSION amcheck;` — расширение не trusted); с PG 15 право `EXECUTE` можно выдать другим ролям. Функции берут `AccessShareLock` — тот же, что `SELECT`, — поэтому проверку можно запускать на работающей базе.

- `bt_index_check(index, heapallindexed)` — лёгкая проверка инвариантов индекса; при `heapallindexed => true` дополнительно проверяет, что **каждая строка таблицы** представлена в индексе.
- `bt_index_parent_check(index, heapallindexed, rootdescend)` — надмножество проверок `bt_index_check`, включая связи parent/child; `rootdescend => true` переищивает листовые кортежи от корня.
- `verify_heapam(relation, ...)` — проверка самого heap (PG 14+): в отличие от B-Tree функций, **возвращает строку на каждое найденное повреждение** (`blkno`, `offnum`, `attnum`, `msg`), а не бросает исключение. Проверяет таблицы, последовательности, matviews.

```sql
CREATE EXTENSION amcheck;

-- Проверка конкретного индекса (named-нотация; аргументы со значениями по умолчанию)
SELECT bt_index_parent_check('idx_users_id'::regclass, true);

-- Глубокая проверка всех B-Tree индексов схемы public с верификацией соответствия куче.
-- Исключены temp-таблицы (могут быть из другой сессии) и не готовые/невалидные индексы.
SELECT bt_index_check(index => c.oid, heapallindexed => true),
       c.relname, c.relpages
FROM pg_index i
JOIN pg_opclass op ON i.indclass[0] = op.oid
JOIN pg_am am ON op.opcmethod = am.oid
JOIN pg_class c ON i.indexrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE am.amname = 'btree' AND n.nspname = 'public'
  AND c.relpersistence != 't'
  AND c.relkind = 'i' AND i.indisready AND i.indisvalid
ORDER BY c.relpages DESC;

-- Проверка heap: непустой результат = повреждение (номер блока и офсет в выводе)
SELECT * FROM verify_heapam('public.orders'::regclass);
```

Ключевые свойства: исключение amcheck **не может быть false positive** (оно возбуждается в ситуациях, которые «по определению не должны случаться»), но и **универсального способа починить то, что нашёл amcheck, не существует** — только локализация и восстановление. Подробности процесса выдаются в лог на `DEBUG1`/`DEBUG2`.

### 2. pg_amcheck (CLI-обёртка, PG 16+)

Клиентская утилита, запускающая проверки amcheck против одной или нескольких баз, с фильтрами по схемам/таблицам/индексам и параллельными соединениями:

```bash
pg_amcheck --all --heapallindexed --parent-check   # → ошибка/не-нулевой код при повреждении
```

### 3. pg_visibility (проверка Visibility Map)

Расширение из contrib (PG 9.6+) для examining и верификации VM: `pg_visibility_map()`, `pg_visibility()`, `pg_visibility_map_summary()`. Детекторы повреждений — `pg_check_visible()` и `pg_check_frozen()`: непустой результат означает, что VM повреждён. `pg_truncate_visibility_map()` принудительно пересобирает VM при следующем VACUUM.

```sql
CREATE EXTENSION pg_visibility;
SELECT * FROM pg_check_visible('public.orders'::regclass);    -- → 0 rows = VM цела
SELECT * FROM pg_check_frozen('public.orders'::regclass);
```

### 4. pageinspect (низкоуровневый анализ через SQL)

Позволяет читать содержимое страниц напрямую, минуя стандартные механизмы доступа (требует суперпользователя — расширение не trusted). Полезен, чтобы определить `xmin`/`xmax` и понять, какие данные ещё можно спасти:

```sql
CREATE EXTENSION pageinspect;

-- Заголовок страницы (блок 42 таблицы 'logs')
SELECT * FROM page_header(get_raw_page('logs', 42));

-- Строки (items) на битой странице
SELECT lp, t_ctid, t_xmin, t_xmax, t_infomask, t_data
FROM heap_page_items(get_raw_page('logs', 42));
```

### 5. pg_checksums (чексуммы кластера)

Проверяет, включает или отключает чексуммы данных. **Все режимы, включая `--check`, требуют чисто остановленного кластера** — онлайн-мониторинг через `pg_checksums` невозможен (для онлайн-проверок служат `amcheck`/`pg_visibility`). Утилита требует той же мажорной версии, что и кластер.

```bash
pg_ctl stop -D /var/lib/postgresql/data

# Проверка всего кластера: код возврата 0 = ошибок нет, 1+ = найден хотя бы один сбой
pg_checksums --check --progress -D /var/lib/postgresql/data
# → pg_checksums: checking files...  # → exit code 0

# Точечная проверка одной relation по filenode (PG 12+)
pg_checksums --check -f 16385 -D /var/lib/postgresql/data

# Включение чексумм офлайн: каждый блок с изменённой суммой перезаписывается на месте.
# На большом кластере — часы; ничего не должно писать в каталог данных.
pg_checksums --enable -D /var/lib/postgresql/data
pg_ctl start -D /var/lib/postgresql/data
```

Особенности: при прерывании `--enable/--disable` конфигурация остаётся прежней и операцию можно повторить; `--disable` правит только `pg_control`; в реплицируемой конфигурации нужно согласованно остановить все узлы (либо уничтожить standby и пересоздать их после операции на первичном).

### 6. pg_filedump (анализ файлов вне СУБД)

Внешняя утилита (проект `df7cb/pg_filedump` на GitHub, работает с файлами PG 9.0+) для форматированного дампа heap/index/control-файлов — даже когда база не запускается. Принимает **путь к файлу**, а не каталог данных (`-D` здесь — список типов для декодирования кортежей):

```bash
# Отформатированный дамп с интерпретацией item'ов
pg_filedump -i -f /var/lib/postgresql/data/base/16384/16385

# Конкретный диапазон блоков + проверка чексумм блоков
pg_filedump -i -R 42 42 -k /var/lib/postgresql/data/base/16384/16385
```

### 7. pg_controldata и уровень ОС

```bash
pg_controldata /var/lib/postgresql/data | grep -E "Database block size|Data page checksum version|Latest checkpoint"
# → Database block size: 8192 / Data page checksum version: 1 / ...

dmesg -T | tail -50            # → аппаратные ошибки I/O
smartctl -a /dev/sda           # → реальные секторы, ошибки носителя
```

## Практические сценарии

### Сценарий 1: Физическое повреждение страницы (checksum failure)

Симптом в логах: `ERROR: invalid page in block 12345 of relation base/16384/16385: checksum verification failed`.

1. **Первая реакция** — runbook выше (стоп + файловая копия).
2. **Локализация** — имя объекта по `filenode` из сообщения; номер базы в пути — OID базы:
   ```sql
   SELECT relname, relkind FROM pg_class WHERE relfilenode = 16385;
   -- → 'orders' / 'r' (таблица) или 'i' (индекс)
   SELECT pg_relation_filepath('public.orders');
   -- → base/16384/16385
   ```
3. **Анализ ОС**: `dmesg`, `smartctl`, логи RAID-контроллера (состояние BBU). Физические ошибки БД часто следствие деградации железа — восстановление на том же железе без диагностики бессмысленно.
4. **Ремонт по типу объекта**:
   - повреждён **индекс** → `REINDEX INDEX ...;` (или `REINDEX TABLE ...;`);
   - повреждена **таблица** → см. сценарий 6.
5. **Спасение данных с битых страниц** (только на копии!): `SET ignore_checksum_failure = on;` пропускает ошибку с WARNING и продолжает чтение — это **может вернуть мусор, спровоцировать краш или скрыть коррупцию**; если повреждён заголовок блока, ошибка возникнет и с этой настройкой. Допустимо на выброшенной копии кластера, когда терять уже нечего:
   ```sql
   SET ignore_checksum_failure = on;
   COPY (SELECT * FROM damaged_table) TO '/tmp/dump.csv';   # → часть строк спасена
   ```

### Сценарий 2: Повреждение пользовательского индекса

Симптомы: `ERROR: index "idx_x" contains unexpected zero page at block 0` (с подсказкой `HINT: Please REINDEX it.`), `failed to find tuple ...`, расхождения, найденные `bt_index_check`.

```sql
REINDEX INDEX idx_x;                       -- блокирует записи, не чтение
REINDEX INDEX CONCURRENTLY idx_x;          -- PG 12+: без блокировки записей
REINDEX TABLE CONCURRENTLY public.orders;  -- все индексы таблицы
```

`REINDEX ... CONCURRENTLY` не поддерживается для `SYSTEM` и для индексов exclusion-ограничений. Если конкурентная перестройка прервалась с ошибкой, индекс остаётся «invalid» (файл с суффиксом `ccnew`) — удалите его (`DROP INDEX`) и повторите попытку. Для индексов, повреждённых известными багами (например, GiST в старых минорных версиях), после установки фикса — `REINDEX` всех затронутых индексов.

### Сценарий 3: Повреждение системных индексов (pg_catalog)

Симптом: база не пускает даже на чтение — `FATAL: index "pg_class_oid_index" contains unexpected zero page at block 0`.

1. Запустить кластер с игнорированием системных индексов (чтение системных таблиц без них; параметр действует на момент старта сессии):
   ```bash
   pg_ctl start -D /var/lib/postgresql/data -o "-c ignore_system_indexes=on"
   ```
2. Пересоздать повреждённые системные индексы:
   ```sql
   REINDEX INDEX pg_class_oid_index;
   -- либо все системные индексы базы: REINDEX SYSTEM mydb;
   ```
3. Перезапустить кластер обычно (без флага). Если повреждений много — сначала `pg_dumpall`, затем `initdb` и восстановление.

### Сценарий 4: Повреждение CLOG (pg_xact)

Симптомы: `ERROR: could not access status of transaction 1234567`, `could not read from file "pg_xact/003A"`.

1. **Предпочтительный путь** — восстановление из бэкапа с PITR.
2. Если бэкапа нет и файл действительно отсутствует — создать пустой сегмент нужного размера (256 КБ, имя — 4 hex-цифры):
   ```bash
   dd if=/dev/zero of=/var/lib/postgresql/data/pg_xact/003A bs=256k count=1
   chown postgres:postgres /var/lib/postgresql/data/pg_xact/003A
   chmod 600 /var/lib/postgresql/data/pg_xact/003A
   ```
   Нули означают статус **in-progress** для всех транзакций диапазона (не «aborted»): их строки становятся невидимы для любых снапшотов — база остаётся непротиворечивой, но строки этих транзакций потеряны.
3. Если дыра в **конце** диапазона XID — чище подвинуть `next_xid` за неё: `pg_resetwal -x <новый_xid>`.
4. После любого из вариантов — немедленно `pg_dumpall`, `initdb`, restore.

### Сценарий 5: База не стартует (WAL / pg_control)

Симптомы: `invalid xlog record at ...`, PANIC при recovery, `pg_control` не читается.

1. **PITR из архива WAL** — основной путь (см. [Бэкап и восстановление](./backup_and_recovery.md)).
2. Если recovery падает с PANIC из-за ссылок WAL на невалидные страницы — разрешить продолжение recovery (только на старте, только в recovery/standby):
   ```
   # postgresql.conf перед стартом; после старта — убрать
   ignore_invalid_pages = on
   ```
3. **`pg_resetwal` — последнее средство**, если старта нет и PITR невозможен. Только на **остановленном** кластере той же мажорной версии, пользователем, установившим сервер (утилита откажется работать при наличии lock-файла; после краха lock-файл можно удалить, только будучи уверенным, что серверных процессов нет):
   ```bash
   pg_resetwal -n -D /var/lib/postgresql/data     # dry run: что будет изменено
   pg_resetwal -f -D /var/lib/postgresql/data     # -f обязателен при нечистом выключении или битом pg_control
   pg_resetwal -f --wal-segsize=16 -D /var/lib/postgresql/data   # если размер сегмента WAL не определяется
   ```
   Полезные опции: `-l <walfile>` (начало WAL вручную, вместе с `--wal-segsize`), `-o <next_oid>`, `-x <next_xid>`, `-e <epoch>`, `-u <oldest_xid>`.
4. После сброса сервер стартует, но данные **непредсказуемы** (частично зафиксированные транзакции): немедленно `pg_dumpall`, затем `initdb` и восстановление из дампа.

### Сценарий 6: Спасение данных с одной битой страницы

**Документированный способ — `zero_damaged_pages`** (Developer Options, суперпользователь): при обнаружении повреждённого заголовка страницы сервер выдаёт WARNING и обнуляет страницу **в памяти**, продолжая работу. Строки с этой страницы теряются, но все остальные читаемы. Обнулённые страницы **не сбрасываются на диск**, поэтому перед отключением параметра таблицу/индекс рекомендуется пересоздать:

```sql
SET zero_damaged_pages = on;
COPY (SELECT * FROM damaged_table) TO '/tmp/dump.csv';   # → строки с целых страниц
-- Пересоздать таблицу из выгрузки (REINDEX недостаточен для heap)
SET zero_damaged_pages = off;
```

**`dd`-обнуление страницы на диске — крайняя мера** для остановленного кластера (когда сервер вообще не может прочесть таблицу): нулевая страница читается как пустая, но строки на ней потеряны, а индексы, ссылающиеся на её кортежи, становятся недействительны:

```bash
# Только на остановленном кластере, с предварительной копией файла!
dd if=/dev/zero of=/var/lib/postgresql/data/base/16384/16385 bs=8192 seek=10 count=1 conv=notrunc
# → страница 10 пуста; далее REINDEX всех индексов таблицы и выгрузка данных
```

### Сценарий 7: Профилактическое сканирование (scrubbing)

Против «тихой порчи» — регулярная проверка чексумм и индексов:

```sql
-- amcheck по всем B-Tree индексам (онлайн, блокировка уровня SELECT)
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT c.oid AS idx
             FROM pg_index i
             JOIN pg_class c ON i.indexrelid = c.oid
             JOIN pg_am am ON c.relam = am.oid
             WHERE am.amname = 'btree'
               AND c.relkind = 'i' AND i.indisready AND i.indisvalid
               AND c.relpersistence != 't'
    LOOP
        PERFORM bt_index_check(r.idx::regclass, true);
    END LOOP;
END $$;
```

```bash
# pg_amcheck (PG 16+): параллельно по всем базам
pg_amcheck --all --heapallindexed
# pg_checksums --check — только в окне обслуживания (чистая остановка), cron с проверкой кода возврата
```

## Поиск и устранение неисправностей

| Симптом | Вероятная причина | Первоочередное действие |
| :--- | :--- | :--- |
| `invalid page in block N ... checksum verification failed` | Физическая порча страницы (диск, контроллер, ОЗУ) | Runbook первой реакции; локализация по `filenode`; `dmesg`/`smartctl`; индекс → `REINDEX`, heap → сценарий 6 |
| `index "..." contains unexpected zero page at block N` + `HINT: Please REINDEX it.` | Обнулённая страница индекса | `REINDEX INDEX` (для системных — сценарий 3) |
| `failed to find tuple ...` / расхождение индекса и таблицы | Логическая коррупция индекса | Локализация `bt_index_check`, затем `REINDEX` |
| `could not access status of transaction N` | Повреждение/отсутствие файла CLOG | Восстановление из бэкапа; крайняя мера — нулевой сегмент `pg_xact` (сценарий 4) |
| `could not read block N from file ...` | Файл усечён (закончилось место), повреждение ФС | `df`, проверка ФС, восстановление из бэкапа |
| `invalid xlog record at ...` / PANIC в recovery | Повреждение WAL | PITR из архива WAL; `ignore_invalid_pages` для завершения recovery; `pg_resetwal` последним средством |
| amcheck/`verify_heapam` сообщают повреждение | Логическая коррупция (чексуммы её не ловят) | `blkno`/`offnum` из вывода → `REINDEX` / восстановление; универсального ремонта нет |

## Лучшие практики

1. **`data_checksums`**: включать при `initdb` (`initdb -k`; в PG 18 включены по умолчанию). На существующем кластере — офлайн `pg_checksums --enable`. Проверка состояния: `SHOW data_checksums;`.
2. **`full_page_writes = on`** — защита от разрывов страниц при сбоях питания. Выключать запрещено.
3. **Регулярный scrubbing**: `pg_amcheck --all --heapallindexed` (PG 16+) или DO-блок amcheck; `pg_visibility`-проверки; `pg_checksums --check` в окне обслуживания.
4. **Железо**: BBU RAID-контроллера, SSD с защитой от потери питания, ECC RAM; мониторинг `dmesg`/SMART.
5. **Никогда `fsync = off`** на продакшене — крах ОС/питания с высокой вероятностью даёт повреждения. Аналогично: файловая система с барьерами записи + хранилище, эти барьеры соблюдающий (исторический виновник — LVM).
6. **Миграция ОС**: при переносе кластера через `pg_basebackup`/streaming replication исходная и целевая ОС должны иметь одну версию glibc/locale — смена glibc влияет на collation и может привести к повреждению данных (типичные границы: CentOS 7→8, Ubuntu 18.04→20.04).
7. **Файловая система**: ZFS/Btrfs с избыточностью (mirror/RAIDZ/RAID1) обнаруживают и **восстанавливают** повреждённые блоки; без избыточности — только обнаруживают. ФС-уровневые чексуммы дополняют, но не заменяют `data_checksums`.
8. **Изоляция WAL**: `pg_wal` на отдельный физический диск или RAID 1.
9. **Мониторинг логов**: оповещения на `checksum verification failed`, `unexpected zero page`, `could not access status of transaction`, `PANIC`, `FATAL`.
10. **Валидация после ремонта**: `amcheck` без ошибок, `pg_checksums --check` с кодом 0 (офлайн), сверка счётчиков строк с бэкапом, smoke-тест приложения.

## Вопросы на собеседованиях

1. Чем `checksum verification failed` отличается от `unexpected zero page`? (порча содержимого страницы vs обнулённая/неинициализированная страница; второе часто от сбоя записи или администратора)
2. Почему `pg_checksums --check` нельзя запустить на работающем кластере и что использовать онлайн? (требует чистой остановки; онлайн — `amcheck`, `pg_visibility`)
3. Что делает `ignore_checksum_failure` и почему это не ремонт? (пропускает ошибку с WARNING, может вернуть мусор или спровоцировать краш; только на копии для спасения)
4. Чем `zero_damaged_pages` лучше обнуления страницы через `dd`? (обнуление в памяти, на диск не пишется; `dd` — только на остановленном кластере, теряет данные страницы и ломает индексы)
5. Как определить, что повреждён индекс, а не таблица? (`pg_class.relkind = 'i'` по `filenode`; `amcheck` ошибается на индексе; `REINDEX` решает)
6. Что проверяет `heapallindexed`? (что каждая строка таблицы представлена в индексе)
7. Чем `verify_heapam` отличается от `bt_index_check`? (проверяет heap, а не индекс; возвращает строки с `blkno`/`offnum` вместо исключения)
8. Почему после `pg_resetwal` нужен немедленный `pg_dumpall`? (частично зафиксированные транзакции оставляют кластер в неопределённом состоянии)

## Дополнительная информация

### Смежные темы
- **[Бэкап и восстановление](./backup_and_recovery.md)** — PITR, `pg_basebackup`, архивация WAL.
- **[Архитектура PostgreSQL](./architecture.md)** — устройство страниц, буферы и WAL.
- **[Внутреннее устройство VACUUM](./vacuum_internals.md)** — freeze, wraparound, `pg_resetwal` в контексте VACUUM.
- **[Вспомогательные расширения](./extensions_utility.md)** — установка `amcheck`/`pageinspect`/`pg_visibility`.
- **[Наблюдаемость](../Operations/observability.md)** — мониторинг ошибок в логах.

### Внешние источники
- [PostgreSQL Wiki: Corruption](https://wiki.postgresql.org/wiki/Corruption) — first response, причины, `pg_hexedit`.
- [pg_filedump (GitHub)](https://github.com/df7cb/pg_filedump) — низкоуровневый дамп relation-файлов.
- [Christophe Pettus: Corruption War Stories (FOSDEM 2017)](https://thebuild.com/presentations/corruption-war-stories-fosdem-2017.pdf) — разбор реальных случаев повреждений и техник спасения данных с потерями.
