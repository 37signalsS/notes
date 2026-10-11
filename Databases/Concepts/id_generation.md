**Актуально для:** RFC 9562 (UUID, 2024) / PostgreSQL 18 / MySQL 8.0–9.x / MariaDB 11.7+ (2024–2026)

# Генерация идентификаторов: UUID, ULID, Snowflake ID, sequences

**Предварительные требования:** PostgreSQL 18 (для `uuidv7()`), MariaDB 11.7+ (для `UUID_v7()`), MySQL 8.0+; для Snowflake — заранее назначенные machine ID (статика, etcd/Consul, ordinal StatefulSet) и синхронизация часов (NTP/chrony).

## Определения

**Surrogate Key** — суррогатный первичный ключ, не имеющий бизнесного смысла и генерируемый системой (в отличие от natural key — email, ИНН, артикул). Зачем: natural key может измениться, а PK — основа FK и индексов.

**UUID (Universally Unique Identifier)** — 128-битный идентификатор, стандартизован RFC 9562 (2024, заменил RFC 4122). Представляется как 32 hex-символа в 5 группах: `xxxxxxxx-xxxx-Mxxx-Nxxx-xxxxxxxxxxxx`, где `M` — версия, `N` — вариант.

**ULID (Universally Unique Lexicographically Sortable Identifier)** — 128-битный идентификатор: 48-битная миллисекундная временная метка + 80 бит случайности, кодируется 26 символами Crockford Base32. Лексикографически сортируемый.

**Snowflake ID** — 64-битный идентификатор (Twitter, 2010): временная метка + идентификатор узла + порядковый номер в миллисекунде. Влезает в `BIGINT`, сортируется по времени.

**Sequence** — объект БД, выдающий монотонно возрастающие числа (`NEXTVAL`). Единственный источник правды — БД.

**AUTO_INCREMENT / IDENTITY** — колоночные автоинкременты (MySQL/MariaDB; SQL:2003 `GENERATED ALWAYS AS IDENTITY` в PostgreSQL/SQL Server).

**Monotonicity (монотонность)** — свойство «каждый следующий ID больше предыдущего». Важно для B-Tree: монотонные PK вставляются в конец индекса, случайные — в середину (фрагментация).

**Locality (локальность)** — насколько близки по значению новые ID. Высокая локальность = горячая страница индекса = быстрая вставка.

## Основные концепции

### UUID: версии и битовое устройство

**UUID v4 (случайный):** 122 бита случайности. Вероятность коллизии пренебрежимо мала: для 50% вероятности хотя бы одной коллизии нужно ~2.71 × 10^18 ID (≈1 млрд ID/с непрерывно в течение ~86 лет). На практике дубликаты появляются не из-за случайности, а из-за слабого RNG, битового флипа или копирования строк. Не сортируемый, не содержит времени. Генерация: PostgreSQL `gen_random_uuid()` (в ядре с PG 13, ранее — pgcrypto), MySQL `UUID()` (v1, не v4!), `UUID_TO_BIN(UUID(), 1)` для бинарного хранения.

**UUID v7 (временной, RFC 9562):**
```
| 48 бит: unix_ts_ms | 4 бита: ver=7 | 12 бит: rand_a | 2 бита: var | 62 бита: rand_b |
```
- 48-битная миллисекундная метка в старших битах → сортируемость и локальность.
- PostgreSQL 18 использует Method 3 для `rand_a`: 12 бит хранят субмиллисекундную долю времени (1/4096 мс), которая работает как счётчик. Монотонность гарантирована **в пределах одного backend** — даже при откате системных часов (используется возрастающий источник времени); уникальность между backend'ами — за счёт оставшихся 62 бит случайности. На системах с микросекундной точностью (macOS, MSVC) доступно 10 бит + 2 бита случайности.
- **PostgreSQL 18: нативная функция `uuidv7()`** (сентябрь 2025). В более старых версиях — расширение `pg_uuidv7` или генерация в приложении. Время UUID v7 извлекается функцией `uuid_extract_timestamp()` (PG 18 поддерживает v7).
- **MariaDB 11.7+: нативные `UUID_v7()` и `UUID_v4()`** (MDEV-32637, MDEV-11339). Не безопасны для statement-based replication.
- **MySQL (Oracle, 8.0–9.x): нативной UUIDv7 нет** (на 2026) — генерация в приложении либо `UUID_SHORT()` (см. раздел Sequences).
- RFC 9562 определяет также v6 (временной, другой порядок бит) и v8 (кастомный) — в ядре PostgreSQL/MySQL/MariaDB не реализованы.
- Валидность: до 10889 года (48 бит миллисекунд).

**UUID v1:** MAC-адрес + timestamp — раскрывает узел и время генерации; не применяется для PK.

**Хранение:** `uuid`-тип PostgreSQL (16 байт) или `BINARY(16)` MySQL. Строковое хранение (`CHAR(36)`) — на 20 байт больше и медленнее сравнение.

### ULID

```
| 48 бит: timestamp (мс) | 80 бит: randomness | → 26 символов Crockford Base32
```
- Лексикографическая сортировка = хронологическая.
- В пределах одной миллисекунды — 80 бит случайности (коллизии практически невозможны).
- Не стандартизован RFC; реализации есть в большинстве языков (ulid/java, ulid-py).
- Применение: event sourcing, логи, ключи в KV-хранилищах.

### Snowflake ID (64 бита)

```
| 1 бит: sign (0) | 41 бит: timestamp (мс, custom epoch) | 10 бит: machine ID | 12 бит: sequence |
```
- **41 бит timestamp:** 2^41 мс ≈ 69.7 лет от произвольной epoch (Twitter использовал 2010-11-04).
- **10 бит machine ID:** 1024 узла; обычно 5 бит DC + 5 бит worker.
- **12 бит sequence:** 4096 ID/мс на узел → ~4.09 млн ID/сек на узел, без координации между узлами.
- **Instagram-вариант:** 41 бит ts + 13 бит shard_id + 10 бит seq — ID сам является shard key.
- **Discord Snowflake:** аналогичная схема с другой epoch.
- **Критично:** clock skew назад → дубликаты ID. Генератор должен блокироваться при откате часов. Мониторинг: `chronyc tracking` / `ntpq -p` — алерт при системном offset, превышающем допуск генератора.

### MongoDB ObjectId (12 байт)

```
| 4 байта: unix_ts (секунды) | 5 байт: случайное значение процесса | 3 байта: счётчик |
```
- Дефолтный `_id` в MongoDB: уникален без координации (случайность процесса + счётчик), сортируется по времени с точностью до секунды.
- Время извлекается: `ObjectId.getTimestamp()`.
- 5 байт случайности генерируются один раз на процесс — коллизий между процессами на одном хосте не возникает.

### Redis INCR (ticket server)

- `INCR`/`INCRBY` — распределённый счётчик (паттерн «ticket server», Flickr): одна точка выделения 64-битных ID без сложной инфраструктуры.
- Ограничения (SRE): Redis — точка координации и отказа; ID монотонны, но не временны; без `appendonly yes` (AOF) после перезапуска счётчик сбрасывается → дубликаты. Проверяйте значение счётчика после failover.

### Sequences и AUTO_INCREMENT

**PostgreSQL:**
- `serial` (legacy) → `GENERATED ALWAYS AS IDENTITY` (SQL:2003, предпочтительно).
- `SEQUENCE` — отдельный объект, `NEXTVAL`/`CURRVAL`, `CACHE` для производительности (с разрывами при сбое).
- `uuidv7()` (PG 18) — нативный временной UUID.

**MySQL/MariaDB:**
- `AUTO_INCREMENT` — InnoDB: при `innodb_autoinc_lock_mode=2` (по умолчанию с 8.0) значения могут иметь разрывы при concurrent inserts; значения не переиспользуются после `DELETE`/rollback.
- `AUTO_INCREMENT` exhaustion: `TINYINT` (127, или 255 для UNSIGNED), `INT` (2.1 млрд, или 4.2 млрд для UNSIGNED), `BIGINT` (9.2 × 10^18) — выбирайте `BIGINT` сразу.
- `UUID_SHORT()` — 64-битный идентификатор: `(server_id & 255) << 56 + (server_startup_time_in_seconds << 24) + инкрементный счётчик`. Гарантия уникальности: `server_id` 0–255 уникален среди source/replica, часы не откатываются между рестартами mysqld, <16 млн вызовов/с между рестартами. Не работает с statement-based replication.

**Multi-master (Galera, Group Replication, multi-master sharding):**
- `auto_increment_increment` / `auto_increment_offset` — непересекающиеся диапазоны на узлах. Подробности — **[Топологии репликации](../MariaDB/replication/topologies.md)** и **[Репликация MySQL](../MySQL/replication/overview.md)**.
- В Citus уникальные ограничения (включая PK) на распределённых таблицах обязаны включать колонку дистрибуции — поэтому PK часто делают UUID v7/Snowflake: **[Citus](../citus.md)**.

### Сравнительная таблица

| Свойство | UUID v4 | UUID v7 | ULID | Snowflake | Sequence | ObjectId |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Размер** | 16 байт | 16 байт | 16 байт (26 символов) | 8 байт | 8 байт (BIGINT) | 12 байт |
| **Сортируемость по времени** | нет | да | да | да | да | да (секунды) |
| **Локальность (B-tree)** | плохая | хорошая | хорошая | отличная | отличная | хорошая (секунды) |
| **Генерация без координации** | да | да | да | да (с machine ID) | нет (только БД) | да (в пределах процесса) |
| **Коллизии** | ~невозможны | ~невозможны | ~невозможны | нет при уникальном machine ID | нет | практически нет |
| **Раскрывает время/узел** | нет | да (время) | да (время) | да (время, узел) | нет | да (время) |
| **Перечисляемость (security)** | нет | нет | нет | частично (timestamp) | да (1,2,3…) | частично |
| **Multi-master** | да | да | да | да | только с offset/increment | да |

## Практические сценарии

### Сценарий 1: Выбор стратегии

- **Одиночный PostgreSQL, OLTP:** `BIGINT GENERATED ALWAYS AS IDENTITY` — максимальная производительность вставок.
- **PostgreSQL 18+, нужен распределённый генератор:** `uuidv7()` — сортируемость + распределённость.
- **Sharding / multi-master:** Snowflake ID (приложение) или UUID v7.
- **Security-sensitive (публичные ID в URL):** UUID v4/v7 или ULID — не перечисляемые. Никогда не expose sequence (`/users/1`, `/users/2` — перечисление).
- **Event sourcing / логи:** ULID — сортируемость + компактность строки.
- **Высокая нагрузка > 1 млн ID/с на узел:** Snowflake (4096/мс/узел недостаточно → уменьшите epoch или расширьте sequence до 13+ бит).
- **MySQL без изменений приложения:** `UUID_SHORT()` — 64-битный, привязан к `server_id` и времени старта (точность — секунды).
- **MongoDB:** ObjectId как `_id` по умолчанию — 12 байт, сортируемый по времени.

### Сценарий 2: PostgreSQL — миграция serial → identity → uuidv7

```sql
-- Было (legacy)
CREATE TABLE orders (id serial PRIMARY KEY, ...);

-- Стало (SQL:2003 identity)
CREATE TABLE orders (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ...);

-- PostgreSQL 18+: временной UUID как PK
CREATE TABLE events (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- uuidv7() даёт локальность: новые строки вставляются в конец B-Tree PK
```

**Откат миграции** (expand/contract в обратную сторону): новый `bigint`-столбец с sequence → бэкфилл → переключение приложения → удаление uuid-столбца. Прямое `ALTER TYPE uuid → bigint` без рекреации невозможно. См. **[Expand/Contract](./migrations/expand_contract.md)**.

### Сценарий 3: MySQL — бинарное хранение UUID

```sql
-- Хранить как BINARY(16), не CHAR(36): экономия 20 байт/строка и быстрее сравнение
CREATE TABLE events (
    id BINARY(16) PRIMARY KEY,
    payload JSON NOT NULL
);

-- Вставка (MySQL 8.0+): UUID() возвращает v1; для v4/v7 — генерация в приложении
INSERT INTO events (id, payload) VALUES (UUID_TO_BIN(?, 1), ?);
-- UUID_TO_BIN(..., 1) переставляет временные биты вперёд → локальность индекса

-- Чтение обратно в строку
SELECT BIN_TO_UUID(id, 1) FROM events;
```

### Сценарий 4: Snowflake-генератор (псевдокод)

```python
EPOCH = 1609459200000  # 2021-01-01 UTC в мс
MACHINE_ID = 42        # 0..1023, назначается один раз при старте

def next_id(now_ms: int, last_ms: int, seq: int) -> tuple[int, int, int]:
    if now_ms == last_ms:
        seq = (seq + 1) & 0xFFF            # 12-битный счётчик
        if seq == 0:
            now_ms = wait_next_ms(last_ms)  # исчерпали 4096/мс — ждём
    else:
        seq = 0
    if now_ms < last_ms:
        raise ClockSkewError("clock moved backwards")  # блокировка при откате часов
    return ((now_ms - EPOCH) << 22) | (MACHINE_ID << 12) | seq, now_ms, seq
```

## Операции и команды

### PostgreSQL

```sql
-- Текущий тип PK и дефолт
SELECT column_name, data_type, column_default
FROM information_schema.columns WHERE table_name = 'orders';

-- Скорость генерации uuidv7 (PG 18)
SELECT count(*) FROM generate_series(1, 1000000), LATERAL (SELECT uuidv7()) s;
-- → 1000000 (замер времени: ~1–2 с на типовом железе)

-- Проверка сортируемости uuidv7 (в пределах одного backend — всегда t)
SELECT uuidv7() < uuidv7();

-- Извлечение времени из UUID v7 (PG 18)
SELECT uuid_extract_timestamp(id) FROM events;
```

### MySQL/MariaDB

```sql
-- AUTO_INCREMENT: текущий следующий ID и разрывы
SHOW TABLE STATUS LIKE 'orders';
-- → Auto_increment: 1234567 (разрывы нормальны: rollback, INSERT IGNORE, multi-insert)

-- Проверка режима автоинкремента
SHOW VARIABLES LIKE 'innodb_autoinc_lock_mode';
-- → 2 (interleaved, по умолчанию в 8.0+: разрывы возможны, но нет блокировок)

-- MariaDB 11.7+: нативные временной и случайный UUID
SELECT UUID_v7(), UUID_v4();
-- → 01921e85-f198-7490-9b89-7dd0d468543b, a2443495-1b94-415b-b6fa-fe8e79ba4812

-- MySQL: 64-битный идентификатор (уникален при уникальном server_id)
SELECT UUID_SHORT();
-- → 92395783831158784
```

## Поиск и устранение неисправностей

### Проблема: фрагментация индекса при случайных UUID

**Симптомы:** `INSERT` в таблицу с UUID v4 PK медленнее, чем с `serial`; `pg_statio_user_indexes` показывает рост `idx_blks_hit`/`idx_blks_read`, размер индекса > ожидаемого.

**Причина:** случайные UUID вставляются в случайные страницы B-Tree → page splits, fillfactor падает, индекс раздувается (в 2–4 раза).

**Решение:**
1. Миграция на UUID v7 (PG 18 `uuidv7()`) или Snowflake — локальность.
2. Для существующей таблицы: `REINDEX` после миграции (**[Индексы](./indexes.md)**).
3. Альтернатива: `BIGINT` PK + отдельный `uuid`-столбец для внешнего использования.

### Проблема: разрывы в AUTO_INCREMENT / sequence

**Симптомы:** ID идут 1, 2, 5, 13, 14…

**Причины (нормальные):** rollback транзакции, `INSERT IGNORE`, multi-row insert с ошибкой, `CACHE` у sequence (разрывы при перезапуске БД), multi-master offset.

**Решение:** разрывы — нормально, PK не обязан быть плотным. Если требуется плотная нумерация (нумерация документов) — отдельная таблица-счётчик с `SELECT ... FOR UPDATE` в транзакции, а не PK.

### Проблема: исчерпание типа

**Симптомы:** `ERROR 1467: Failed to read auto-increment value`, `nextval(): reached maximum value`.

**Причина:** `INT` (2.1 млрд) исчерпан при высокой нагрузке.

**Решение:** миграция `INT → BIGINT` через expand/contract (**[Expand/Contract](./migrations/expand_contract.md)**); для новых таблиц — сразу `BIGINT`.

### Проблема: дубликаты Snowflake ID

**Симптомы:** `PRIMARY KEY` violation при вставке сгенерированного ID.

**Причины:** clock skew назад, повторное назначение machine ID двум узлам, сбой генератора после перезапуска без сохранения последнего timestamp.

**Решение:**
1. Блокировка генератора при откате часов (ждать, пока время догонит `last_timestamp`).
2. Уникальное назначение machine ID: etcd/Consul-регистрация, статическая конфигурация, K8s StatefulSet ordinal.
3. Persist `last_timestamp` на диск при graceful shutdown.

### Проблема: перечисление публичных ID

**Симптомы:** сканеры перебирают `/api/orders/1..N`; утечка объёма бизнеса.

**Решение:** публичные ID — UUID v4/v7 или ULID; внутренние FK — `BIGINT sequence`. Два ключа: `id` (внутренний) и `public_id` (внешний, уникальный индекс).

## Лучшие практики

1. **`BIGINT` для PK всегда** — `INT` исчерпывается быстрее, чем кажется.
2. **PostgreSQL 18+:** `uuidv7()` по умолчанию для распределённых систем; `identity` для одиночных. **MariaDB 11.7+:** нативная `UUID_v7()`; **MySQL:** генерация в приложении или `UUID_SHORT()`.
3. **UUID хранить в бинарном виде** (`uuid`-тип / `BINARY(16)`), не строкой.
4. **Snowflake:** защищайте генератор от clock skew и дублирования machine ID.
5. **Публичные ID ≠ внутренние PK** — не expose sequence.
6. **Multi-master:** либо UUID v7/ULID, либо `auto_increment_increment/offset` (**[Топологии репликации](../MariaDB/replication/topologies.md)**).
7. **Не используйте UUID v1** — раскрывает MAC-адрес узла.
8. **Шардирование:** ID как shard key — Instagram-вариант Snowflake (**[Шардирование](./sharding.md)**).

## Дополнительная информация

### Смежные темы
- **[pgcrypto: генерация UUID](../PostgreSQL/Concepts/pgcrypto.md)** — `gen_random_uuid()`, `uuidv7()`, криптографические функции.
- **[TimescaleDB](../timescaledb.md)** — UUIDv7 для time-series.
- **[Citus](../citus.md)** — распределённые ID и шардирование.
- **[Шардирование](./sharding.md)** — ID как shard key, consistent hashing.
- **[Топологии репликации MariaDB](../MariaDB/replication/topologies.md)** — multi-master AUTO_INCREMENT.
- **[Репликация MySQL](../MySQL/replication/overview.md)** — Group Replication и автоинкремент.
- **[Проектирование схемы](./data_modeling.md)** — surrogate vs natural keys.
- **[Expand/Contract миграции](./migrations/expand_contract.md)** — миграция типа PK без даунтайма.
- **[Индексы](./indexes.md)** — влияние типа PK на B-Tree.
- **[MongoDB](../MongoDB/mongodb.md)** — ObjectId как `_id` по умолчанию.
- **[Redis](../redis_overview.md)** — `INCR` как генератор ID (ticket server).
