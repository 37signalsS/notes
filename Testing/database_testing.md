# Тестирование баз данных (Database Testing)

## Определения

**Database Testing** — проверка работы СУБД и SQL-кода: схемы (DDL), ограничений (constraints, triggers, indexes), процедур/функций/триггеров и миграций. Направление объединяет три задачи:

- **Schema/Migration Testing** — корректность и идемпотентность применения миграций;
- **Unit-тесты SQL/функций** — проверка хранимых процедур и функций с фиксированными данными;
- **Integration/Data Integrity** — поведение при реальных объёмах, конкурентном доступе, каскадных ограничениях.

**pgTAP** — популярная библиотека unit-тестирования для PostgreSQL (TAP-протокол, набор функций-ассертов, запуск через `pg_prove`).

**TAP (Test Anything Protocol)** — текстовый протокол отчётности тестов (строки `ok 1`, `not ok 2`), де-факто стандарт для Perl-подобных экосистем.

## Основные концепции

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

## Практические сценарии

### Сценарий 1: Настройка pgTAP

```bash
# установка через apt / build
apt-get install pgtap          # Debian/Ubuntu
CREATE EXTENSION pgtap;        # в целевой БД
```

После установки доступны функции-ассерты и `pg_prove` (часть пакета pgtap).

### Сценарий 2: Миграционный тест (Flyway + pgTAP)

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

### Сценарий 3: Тест хранимой функции на edge-кейсах

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

### Сценарий 4: Интеграционный тест через Testcontainers

Поднимается одноразовая Postgres с версией продакшн-скальбирования; применяются миграции и запускается приложение-тест (подробнее — [Testcontainers Overview](./testcontainers_overview.md)).

### Сценарий 5: Интеграция в CI/CD (GitLab)

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

### Сценарий 6: Data quality через dbt tests

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

### Связь с юнит-уровнем

Тесты БД — низу пирамиды тестирования вместе с unit (см. [Unit/Integration/E2E](./testing_types_unit_integration_e2e.md)). В топ-интервью часто спрашивают именно pgTAP/TAP — осознание «тесты СУБД не заменяют прикладные, но защищают схемный слой».

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Тест БД падает только в CI | Разные версии Postgres/различия индексов | Пинать по версии из продакшн-стенда в `services:` конфиге |
| Миграция применяется дважды и ломается | Нет идемпотентности в SQL | `IF NOT EXISTS`, корректные `DO`-блоки, версионирование |
| `relation "public.orders" does not exist` | Миграции не применены до теста | Порядок: migrate до test job |
| `permission denied` при pgTAP | Пользователь без прав на extension | `GRANT`/установка `pgtap` в правильную схему |
| Медленные тесты БД (каждый прогон тяжёлый) | Пересоздание таблиц вместо транзакций | Транзакция + ROLLBACK по умолчанию; редкие тяжёлые — отдельная джоба |
| Конфликт тестов при параллелизме | Общие таблицы/sequence | idempotent inserts (ON CONFLICT), отдельные схемы на тест |

## Дополнительная информация

### См. также

- **[Управление тестовыми данными](./test_data_management.md)** — fixtures, генерация, masking данных для тестов БД.
- **[Тестирование миграций](../Databases/Concepts/migrations/migration_practices.md)** — SSoT по стратегиям и практике применения DDL/DML.
- **[Testcontainers](./testcontainers_overview.md)** — изолированные СУБД для интеграционных тестов.

### Внешние ресурсы

- [pgTAP на GitHub](https://github.com/theory/pgtap) — библиотека unit-тестирования PostgreSQL (TAP).
- [TAP (Test Anything Protocol)](https://testanything.org/) — спецификация протокола отчётов тестов.