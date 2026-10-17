# Тестирование баз данных (Database Testing)

**Актуально для:** PostgreSQL 16.x

## Определения

**Database Testing** — проверка работы СУБД и SQL-кода: схемы (DDL), ограничений (constraints, triggers, indexes), процедур/функций/триггеров и миграций. Направление объединяет три задачи:

- **Schema/Migration Testing** — корректность и идемпотентность применения миграций;
- **Unit-тесты SQL/функций** — проверка хранимых процедур и функций с фиксированными данными;
- **Integration/Data Integrity** — поведение при реальных объёмах, конкурентном доступе, каскадных ограничениях.

**DDL (Data Definition Language)** — подмножество SQL для определения структуры: `CREATE`, `ALTER`, `DROP`, `TRUNCATE` таблиц, индексов, констрейнтов.

**DML (Data Manipulation Language)** — подмножество SQL для изменения данных: `SELECT`, `INSERT`, `UPDATE`, `DELETE`.

**Миграция (migration)** — управляемое изменение схемы БД (DDL и DML) с версионированием, направленное на эволюцию структуры данных без потери данных и простоя.

**Идемпотентность** — свойство операции: многократное применение даёт тот же результат, что и однократное. Для миграций: повторный `flyway migrate` не должен ломать схему.

**pgTAP** — популярная библиотека unit-тестирования для PostgreSQL (TAP-протокол, набор функций-ассертов, запуск через `pg_prove`).

**TAP (Test Anything Protocol)** — текстовый протокол отчётности тестов (строки `ok 1`, `not ok 2`), де-факто стандарт для Perl-подобных экосистем.

**dbt (data build tool)** — фреймворк для трансформаций данных в БД: модели, тесты, документация. Используется для data quality-тестов.

**Flyway** — инструмент миграций БД с поддержкой версионирования SQL-скриптов (V1__init.sql, V2__add_column.sql и т.д.).

**Liquibase** — XML/YAML-based alternative к Flyway для управления миграциями.

**Testcontainers** — библиотека для запуска временных Docker-контейнеров СУБД в тестах (см. [Testcontainers Overview](./testcontainers_overview.md)).

**CI/CD** — непрерывная интеграция/доставка. Для тестов БД означает автоматический запуск миграций и тестов на каждом PR.

**Health check** — проверка доступности БД (например, `pg_isready` для PostgreSQL).

**Резервная копия (backup)** — копия данных для восстановления. Для тестов важно проверять не только создание, но и **восстановление** (`pg_restore`/`pg_backrest`).

## Архитектура и принцип работы

Тестирование БД состоит из нескольких слоёв, каждый из которых покрывает свою часть риска:

1. **Слой схемы (DDL)** — проверка структуры: таблицы, колонки, типы, констрейнты, индексы, первичные/внешние ключи.
2. **Слой бизнес-логики** — проверка хранимых процедур, функций, триггеров с фиксированными данными (unit-тесты).
3. **Слой миграций** — проверка идемпотентности и корректности переходов между версиями схемы.
4. **Слой данных** — проверка целостности данных: уникальность, not-null, референциальная целостность, бизнес-правила (data quality).
5. **Слой инфраструктуры** — проверка доступности, резервных копий, репликации, health checks.

### Тестирование миграций

Миграции (DDL/DML в стиле `expand` → `migrate` → `contract`) проверяются на:

- **Идемпотентность**: повторное применение миграции не должно ломать схему.
- **Forward/backward**: возможность отката (rollback) без потери данных — см. [Стратегии отката миграций](../Databases/Concepts/migrations/rollback_strategies.md).
- **Расширяемость**: expansion-фаза `expand_contract` не нарушает старых запросов.
- **Консистентность индексов/констрейнтов**: новые ограничения не конфликтуют с существующими данными.
- **Performance-регрессии**: новые индексы улучшают, а не ухудшают планы (см. [Бенчмаркинг СУБД](../Databases/Concepts/benchmarking.md)).

`expand_contract`, ордер-стратегии и общие практики миграций — в [migration_basics](../Databases/Concepts/migrations/migration_basics.md) и [migration_practices](../Databases/Concepts/migrations/migration_practices.md).

### Подходы к тестированию SQL

| Подход | Инструмент | Тип проверки |
| :--- | :--- | :--- |
| **Unit** | pgTAP (Postgres), tSQLt/`sql-test` (SQL Server), `dbt tests` (dbt) | Функции, триггеры, ограничения в изоляции |
| **Integration** | pytest + psycopg / testcontainers | Флоу-тесты с реальной схемой и данными (см. [Testcontainers](./testcontainers_overview.md)) |
| **Migration** | Flyway/liquibase + тест-раннер | Последовательное применение миграций на чистую БД |
| **Data quality** | `dbt test` (уникальность, not-null, referential) | Проверка согласованности данных |
| **Property/Fuzz** | SQLsmith, random data | Устойчивость к произвольным данным |

### pgTAP: модель

Библиотека расширяет Postgres функциями-ассертами (по соглашению `ok()`, `is()`, `col_eq()`, `table_ok()`, `runs` и др.) и запускается через `pg_prove`:

```sql
-- test_functions.sql
BEGIN;
SELECT plan(2);

SELECT has_function('public', 'total_amount');
SELECT is(total_amount(1), 250.00, 'total для заказа 1');

ROLLBACK;
```

Запуск:

```bash
pg_prove -d testdb -h localhost -U postgres test_functions.sql
# test_functions.sql .. ok
# All tests successful.
```

### Как структурировать тесты БД

- **Изоляция через транзакции**: тест в `BEGIN` + `ROLLBACK` — БД не меняется, параллелизм безопасен.
- **Тестовое состояние**: создание схемы/данных в `setUp` (или через тест-хелперы), чистка после.
- **Фикстуры**: см. [Управление тестовыми данными](./test_data_management.md), для СУБД — специальные файлы `fixtures/*.sql`.
- **Среда**: сходство test → staging структуры гарантируется миграциями (Flyway).
- **DevOps**: в CI используйте отдельную схему на тест (`test_${CI_PIPELINE_ID}`), чтобы избежать конфликтов при параллельных прогонах. Health check перед стартом тестов — `pg_isready -d testdb`.

## Практические сценарии

### Сценарий 1: Настройка pgTAP

**Prerequisites:** PostgreSQL 16.x, права superuser на тестовую БД.

```bash
# установка через apt / build
apt-get install pgtap          # Debian/Ubuntu
CREATE EXTENSION pgtap;        # в целевой БД
```

После установки доступны функции-ассерты и `pg_prove` (часть пакета pgtap).

**Валидация:**

```bash
psql -d testdb -c "SELECT tap_count() > 0;"
# → t
```

### Сценарий 2: Миграционный тест (Flyway + pgTAP)

**Prerequisites:** Flyway CLI 10.x+, файлы миграций в `sql/`, pgTAP установлен.

1. Применить миграции: `flyway migrate -url=jdbc:postgresql://localhost/testdb`.
2. Тест схемы:

```sql
BEGIN;
SELECT plan(3);
SELECT table_exists('public', 'orders');
SELECT col_is_pk('public', 'orders', 'id');
SELECT index_exists('public', 'orders', 'orders_customer_idx');
ROLLBACK;
```

3. Прогнать в CI после каждого PR, меняющего миграции.

**Валидация:**

```bash
pg_prove -d testdb -h localhost -U postgres schema_test.sql
# schema_test.sql .. ok
# All tests successful.
```

### Сценарий 3: Тест хранимой функции на edge-кейсах

**Prerequisites:** Функция `apply_discount(price, discount)` определена в схеме `public`.

```sql
BEGIN;
SELECT plan(4);
SELECT is(apply_discount(100, 0),    100.00, '0% discount');
SELECT is(apply_discount(100, 50),    50.00, '50% discount');
SELECT is(apply_discount(100, -10),   NULL,  'negative → error');
SELECT throws_ok(
  $$SELECT apply_discount(100, 101)$$,
  '22023'  -- invalid_parameter_value
);
ROLLBACK;
```

**Валидация:**

```bash
pg_prove -d testdb -U postgres functions_test.sql
# functions_test.sql .. ok
# All tests successful.
```

### Сценарий 4: Интеграционный тест через Testcontainers

**Prerequisites:** Docker, Testcontainers library (Python/Java/Go), миграции применены через Flyway или Liquibase.

Поднимается одноразовая Postgres с версией продакшн-скальбирования; применяются миграции и запускается приложение-тест (подробнее — [Testcontainers Overview](./testcontainers_overview.md)).

**Валидация:**
- Testcontainers автоматически удаляет контейнер после тестов.
- Проверьте: `SELECT count(*) FROM orders;` > 0 после seed.

### Сценарий 5: Интеграция в CI/CD (GitLab)

**Prerequisites:** PostgreSQL 16.x, Flyway CLI, pgTAP.

```yaml
db-tests:
  stage: test
  services:
    - postgres:16
  variables:
    POSTGRES_DB: testdb
  script:
    - flyway migrate
    - pg_prove -d testdb -U postgres tests/
```

**Валидация:**
- Джоба проходит только если все `pg_prove` тесты `ok`.
- Используйте `before_script` для health check: `pg_isready -d testdb -T 30`.

### Сценарий 6: Data quality через dbt tests

**Prerequisites:** dbt 1.x, модели в `models/marts/`.

```sql
-- models/marts/users.yml
models:
  - name: users
    tests:
      - not_null:
          column_name: id
      - unique:
          column_name: email
      - accepted_values:
          column_name: status
          values: ['active', 'inactive', 'blocked']
```

`dbt test` — проверка соответствия данным бизнес-правил.

**Валидация:**

```bash
dbt test --models marts.users
# 14:23:31 | Completed with 3 failures and 28 successes
```

### Сценарий 7: Тестирование резервных копий и health checks (DevOps/SRE)

**Prerequisites:** pgBackRest 2.x или WAL-G, доступ к pg_hba.conf, pgTAP для валидации restore.

1. Создать бэкап:

```bash
pg_backrest --stanza=mystaging --type=full backup
# → 2026-10-17 ... INFO: backup size=50GB, archive size=2GB
```

2. Проверить целостность (не просто создание, а **валидация**):

```bash
pg_backrest --stanza=mystaging --type=info
# → stanza: mystaging, prior: 2026-10-17, status: expired
pg_backrest --delta --link-all --db-path=/var/lib/postgresql/test_restore
# → restore: test_restore/
```

3. Health check перед тестами:

```bash
pg_isready -d testdb -h localhost -p 5432
# → /var/run/postgresql:5432 - accepting connections
```

4. Проверка репликации (DevOps):

```bash
psql -d postgres -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;"
#  10.0.1.10 | streaming | async
```

**Валидация:**
- Восстановленная БД проходит те же pgTAP-тесты: `pg_prove -d restored_db -U postgres tests/`.
- Health check проходит в течение 30 секунд после старта.

### Связь с юнит-уровнем

Тесты БД — низу пирамиды тестирования вместе с unit (см. [Unit/Integration/E2E](./testing_types_unit_integration_e2e.md)). В топ-интервью часто спрашивают именно pgTAP/TAP — осознание «тесты СУБД не заменяют прикладные, но защищают схемный слой».

## Операции и команды

| Категория | Команда | Описание |
| :--- | :--- | :--- |
| Установка pgTAP | `apt-get install pgtap` | Debian/Ubuntu package |
| Активация расширения | `CREATE EXTENSION pgtap;` | В целевой БД |
| Запуск unit-тестов | `pg_prove -d testdb -U postgres tests/` | Пакетный запуск всех тестов |
| Health check | `pg_isready -d testdb -T 30` | Проверка доступности с таймаутом |
| Миграции | `flyway migrate -url=jdbc:postgresql://localhost/testdb` | Применение миграций |
| Data quality | `dbt test --models marts.users` | Запуск dbt тестов |
| Логический backup | `pg_dump -Fc testdb > testdb.dump` | Формат custom dump |
| Физический backup | `pg_backrest --stanza=test --type=full backup` | pgBackRest full backup |
| Восстановление | `pg_restore -d testdb testdb.dump` | Из логического dump |
| Статус репликации | `SELECT client_addr, state FROM pg_stat_replication` | Текущие реплики |
| Тест-изоляция | `BEGIN; ... ROLLBACK;` | Автооткат изменений теста |
| Параллелизм | `CREATE DATABASE test_${CI_PIPELINE_ID};` | Уникальная БД на тест |

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Тест БД падает только в CI | Разные версии Postgres/различия индексов | `SELECT version();` в CI vs staging | Пинать по версии из продакшн-стенда в `services:` конфиге |
| Миграция применяется дважды и ломается | Нет идемпотентности в SQL | `flyway info` показывает duplicate version | `IF NOT EXISTS`, корректные `DO`-блоки, версионирование |
| `relation "public.orders" does not exist` | Миграции не применены до теста | `flyway info` — статус pending | Порядок: migrate до test job |
| `permission denied` при pgTAP | Пользователь без прав на extension | `psql -c "\dx"` — pgTAP не установлен | `GRANT`/установка `pgtap` в правильную схему |
| Медленные тесты БД (каждый прогон тяжёлый) | Пересоздание таблиц вместо транзакций | `EXPLAIN` показывает sequential scan | Транзакция + ROLLBACK по умолчанию; редкие тяжёлые — отдельная джоба |
| Конфликт тестов при параллелизме | Общие таблицы/sequence | `ERROR: duplicate key value` | idempotent inserts (`ON CONFLICT`), отдельные схемы на тест |
| `pg_prove: command not found` | pgTAP не установлен в CI-образе | `which pg_prove` | Добавить `apt-get install pgtap` в `before_script` |
| `FATAL: password authentication failed` | Неверные credentials в CI | `psql -h $DB_HOST -U $DB_USER` | Использовать CI/CD secrets, а не hardcoded values |
| Тесты падают на этапе restore | Бэкап повреждён (WAL) | `pg_backrest --type=info` | Проверять restore в отдельном pipeline (backup test job) |
| `out of memory` при больших fixture | Массивные INSERT без потоковой обработки | `top`, `dmesg` | Использовать `COPY`, а не `INSERT`; chunked loading |

## Лучшие практики

- **Изоляция через транзакции**: каждый тест в `BEGIN; ... ROLLBACK;` — БД не меняется, тесты не влияют друг на друга.
- **Параллелизм через отдельные БД/схемы**: в CI используйте `test_${CI_PIPELINE_ID}`, чтобы избежать конфликтов.
- **Health check перед тестами**: `pg_isready -d testdb -T 30` в `before_script`.
- **Идемпотентность миграций**: используйте `IF NOT EXISTS`, `DO`-блоки, версионирование `V1__name.sql`.
- **Тестируйте restore, а не только backup**: проверяйте восстановление из бэкапа в отдельном pipeline.
- **Data quality покрывает бизнес-правила**: dbt `test` (not_null, unique, accepted_values) — это слой защиты над аналитикой.
- **pgTAP покрывает схемный слой**: функции, триггеры, констрейнты — защищают схему от регрессий.
- **Минимальные права в CI**: используйте роль с `CONNECT, CREATE, USAGE` на schema, а не superuser.
- **Тесты бизнес-логики в БД через property-based testing**: SQLsmith для fuzz-тестов.

## Ограничения и крайние случаи

- **pgTAP поддерживает только PostgreSQL**: для MySQL/MariaDB используйте `stest4db`; для SQL Server — `tSQLt`.
- **dbt tests работают только с поддерживаемыми адаптерами**: BigQuery, Snowflake, PostgreSQL, Redshift, DuckDB и др. Не работает с произвольными JDBC-источниками.
- **Flyway/Liquibase не проверяют семантику**: миграция может пройти, но сломать бизнес-логику. Дополнительно используйте pgTAP на схему.
- **Большие fixture (>10GB)**: `pg_dump` → `COPY` предпочтительнее `INSERT`. Тестирование restore должно включать time-to-restore SLA.
- **Репликация и consistency**: read-only реплики могут отставать. Тесты, требующие fresh data, используйте на primary.
- **Триггеры и конкурентный доступ**: триггеры могут влиять на порядок тестов. Используйте `SET CONSTRAINTS ALL DEFERRED` при необходимости.
- **pgTAP `BEGIN; ROLLBACK;` не отменяет DDL**: такие операции (`CREATE DATABASE`, `CREATE EXTENSION`) требуют отдельной джобы с cleanup.

## Очистка

- **pgTAP**: тесты в транзакции (`BEGIN; ... ROLLBACK;`) не требуют cleanup. Если используется `CREATE EXTENSION pgtap`, удалите после: `DROP EXTENSION IF EXISTS pgtap CASCADE;`.
- **Testcontainers**: контейнеры удаляются автоматически после тестов. ОчиститеVolumes: `docker volume prune -f`.
- **CI/CD**: временные БД (`test_${CI_PIPELINE_ID}`) удаляются после pipeline через `after_script: DROP DATABASE ...`.
- **Бэкапы**: временные restore-окружения удаляйте через `DROP DATABASE test_restore; rm -rf /var/lib/postgresql/test_restore`.
- **dbt**: `dbt clean` удаляет артефакты (`target/`, `dbt_packages/`).

## Дополнительная информация

### Связь с юнит-уровнем

Тесты БД — низу пирамиды тестирования вместе с unit (см. [Unit/Integration/E2E](./testing_types_unit_integration_e2e.md)). В топ-интервью часто спрашивают именно pgTAP/TAP — осознание «тесты СУБД не заменяют прикладные, но защищают схемный слой».

### См. также

- **[Управление тестовыми данными](./test_data_management.md)** — fixtures, генерация, masking данных для тестов БД.
- **[Тестирование миграций](../Databases/Concepts/migrations/migration_practices.md)** — SSoT по стратегиям и практике применения DDL/DML.
- **[Testcontainers](./testcontainers_overview.md)** — изолированные СУБД для интеграционных тестов.
- **[Методология тестирования производительности](../Databases/Concepts/benchmarking.md)** — нагрузочное тестирование и бенчмаркинг СУБД.
- **[Стратегии отката миграций](../Databases/Concepts/migrations/rollback_strategies.md)** — rollback-стратегии для БД.

### Внешние ресурсы

- [pgTAP на GitHub](https://github.com/theory/pgtap) — библиотека unit-тестирования PostgreSQL (TAP).
- [TAP (Test Anything Protocol)](https://testanything.org/) — спецификация протокола отчётов тестов.
- [dbt](https://docs.getdbt.com/) — трансформации данных и data quality-тесты.
- [Flyway](https://flywaydb.org/) — управление миграциями БД.