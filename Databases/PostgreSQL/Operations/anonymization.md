# Анонимизация и маскирование PII-данных в PostgreSQL

**Актуально для:** PostgreSQL 14–18 / PostgreSQL Anonymizer 3.x

Практическое руководство по защите персональных данных (Personally Identifiable Information — PII) с использованием расширения PostgreSQL Anonymizer и встроенных механизмов PostgreSQL. Ветка 2.x (PostgreSQL 13–17) достигла EOL в jan 2026; ветка 1.3 (PostgreSQL 12–16) содержит legacy API динамического маскирования, полностью удалённое в 3.0. Общие концепции защиты описаны в руководстве **[Безопасность бэкапов](../../Concepts/backup_security.md)**.

## Определения

**Анонимизация (Anonymization)** — необратимый процесс изменения данных, при котором идентификация личности становится невозможной. Анонимизированные данные выходят из-под действия GDPR.

**Псевдонимизация (Pseudonymization)** — замена идентификаторов на искусственные значения (псевдонимы). Процесс обратим при наличии дополнительной информации (таблицы соответствия, соли). Важно: согласно GDPR (Recital 26) псевдонимизированные данные остаются персональными — псевдонимизация это защита, а не анонимизация.

**Динамическое маскирование (Transparent Dynamic Masking)** — скрытие данных «на лету» в момент выполнения запроса для ролей, помеченных как `MASKED`. Исходные данные на диске остаются неизменными.

**Статическое маскирование (Static Masking)** — перезапись реальных данных в базе фиктивными значениями. Необратимо, применяется на sandbox-сервере после восстановления Production-бэкапа.

**Анонимный дамп (Anonymous Dump / Backup Masking)** — выгрузка данных через `pg_dump`, запущенный под masked-ролью: в файле дампа оказываются уже замаскированные значения, реальные PII не попадают в файл.

**Маскирующая политика (Masking Policy)** — набор правил, объявленных в схеме БД через `SECURITY LABEL`. Политика по умолчанию называется `anon`; может быть несколько (например, `rgpd`).

**Маскированная роль (Masked Role)** — роль с меткой `SECURITY LABEL FOR anon ON ROLE ... IS 'MASKED'`, которой движок отдаёт замаскированные данные.

## Базовые концепции

### Декларативный подход

PostgreSQL Anonymizer (`postgresql-anonymizer`, расширение `anon`) реализует принцип «privacy by design»: правила маскирования описываются на языке DDL прямо в схеме БД — как ограничения целостности, — а не в коде приложения или внешнем ETL-инструменте. Правила хранятся как security labels и применяются самим сервером, поэтому PII не покидают экземпляр в открытом виде при выгрузке и доступе.

### Пять стратегий маскирования

| Стратегия | Что меняется | Когда применять |
| :--- | :--- | :--- |
| Dynamic Masking | Ничего (маска при чтении) | Доступ аналитиков/поддержки к Production |
| Static Masking | Данные на диске (необратимо) | Подготовка Staging/Dev из бэкапа |
| Anonymous Dumps | Только файл дампа | Передача данных разработчикам/тестировщикам |
| Masking Views | Представления над таблицами | Обобщённые (generalization) выборки, k-анонимность |
| Masking Data Wrappers | Внешние таблицы (FDW) | Маскирование внешних источников |

### Модель доверия

- Правила могут ссылаться только на функции из доверенных схем. По умолчанию доверены `pg_catalog` и `anon`; схема `public` не доверена. Управляется GUC `anon.restrict_to_trusted_schemas`.
- Начиная с 1.3, `pg_catalog` не доверен по умолчанию: в правилах используйте привязки `anon.md5()`, `anon.left()`, `anon.length()`, `anon.concat()` вместо системных функций; полный список — в представлении `anon.pg_trusted_functions`.
- С 3.x суперпользователю запрещено выполнять маскирующие функции (Least Privilege). Для статического маскирования и анонимных дампов создавайте выделенную роль. Вернуть старое поведение (небезопасно): `ALTER SYSTEM SET anon.nosuperuser = FALSE;`.
- Установка правил (`SECURITY LABEL`), объявление доверенных схем и `CREATE EXTENSION` — привилегированные операции (суперпользователь).

## Практические сценарии

### Требования

- PostgreSQL 14–18 (для ветки 2.x — 13–17, EOL jan 2026).
- Пакет расширения, установленный на хосте (см. шаг 1).
- Суперпользователь для установки, загрузки и объявления правил.
- Для динамического маскирования перезапуск не требуется, если используется `session_preload_libraries`.

### 1. Установка и загрузка расширения

**Шаг 1. Установка пакета на хосте:**

| ОС | Команда |
| :--- | :--- |
| RHEL / Rocky / Alma | `curl -fsSL https://repo.dalibo.com/install.sh \| sh` затем `sudo yum install postgresql_anonymizer_16` (замените `16` на мажорную версию PG) |
| Fedora | `sudo dnf install postgresql16-anonymizer` (только PG 16) |
| Debian / Ubuntu (рекомендуемый способ) | `curl -fsSL https://repo.dalibo.com/install.sh \| sh` затем `sudo apt install postgresql_anonymizer_16` |
| SUSE | скачать RPM из GitLab Package Registry, затем `sudo zypper install postgresql_anonymizer_16.rpm` |
| Ansible | `ansible-galaxy collection install dalibo.advanced` + роль `dalibo.advanced.anon` |
| Docker | `docker pull registry.gitlab.com/dalibo/postgresql_anonymizer:stable` |
| Из исходников | требуется PGRX: `cargo install cargo-pgrx --version 0.14.3 --locked && cargo pgrx init`, затем `make extension && sudo make install` |

> Пакеты PGDG RPM (`postgresql_anonymizer14` и аналогичные) устарели — версии 2.0+ там отсутствуют, используйте репозиторий DaLibo Labs.

**Шаг 2. Загрузка библиотеки в экземпляр.** Рекомендуемый способ — глобальная загрузка (покрывает все бэкенды и фоновые процессы, обязательна для Replica Masking):

```sql
ALTER SYSTEM SET shared_preload_libraries = 'anon';
-- → требуется перезапуск PostgreSQL
```

Альтернатива без перезапуска — загрузка на уровне БД (действует на новых подключениях, сохраняется в дампе `pg_dump -C`, реплицируется на standby; фоновые процессы не покрывает):

```sql
ALTER DATABASE foo SET session_preload_libraries = 'anon';
-- → достаточно переподключиться
```

**Шаг 3. Создание и инициализация в базе** (в новой сессии, после загрузки библиотеки):

```sql
CREATE EXTENSION anon;
SELECT anon.init();
-- → anon.init() загружает набор данных (1000 значений на категорию),
--   требуемый функциями fake_* и seeded_*
```

**Шаг 4. Проверка готовности:**

```sql
SELECT anon.is_initialized();
-- → t
SELECT * FROM pg_extension WHERE extname = 'anon';
```

### 2. Объявление правил маскирования

Правила декларативны: вы описываете преобразование прямо в схеме.

```sql
-- Полное уничтожение значения
SECURITY LABEL FOR anon ON COLUMN users.address
IS 'MASKED WITH VALUE NULL';

-- Подстановка константы
SECURITY LABEL FOR anon ON COLUMN users.address
IS 'MASKED WITH VALUE ''CONFIDENTIAL''';

-- Email: частичное перемешивание (da***@gm***.com)
SECURITY LABEL FOR anon ON COLUMN users.email
IS 'MASKED WITH FUNCTION anon.partial_email(email)';

-- Телефон: первые 2 и последние 2 цифры открыты
SECURITY LABEL FOR anon ON COLUMN users.phone
IS 'MASKED WITH FUNCTION anon.partial(phone,2,$$******$$,2)';

-- Фамилия: реалистичное значение из генератора (v2-движок, локализованный)
SECURITY LABEL FOR anon ON COLUMN users.last_name
IS 'MASKED WITH FUNCTION anon.dummy_last_name()';

-- Дата рождения: случайное смещение ±10 лет (для ДАТ — dnoise!)
SECURITY LABEL FOR anon ON COLUMN users.birth
IS 'MASKED WITH FUNCTION anon.dnoise(birth, ''10 years'')';

-- Детерминированный псевдоним по логину (сохраняет связи между таблицами)
SECURITY LABEL FOR anon ON COLUMN users.email
IS 'MASKED WITH FUNCTION anon.seeded_email(users.login)';
```

Правила не наследуются партициями и не применяются автоматически к наследуемым/секционированным таблицам: объявляйте правило на каждой партиции. Правила поддерживаются для партиций, наследуемых и внешних таблиц.

### 3. Динамическое маскирование

Сценарий: аналитики или служба поддержки работают с Production-базой и не должны видеть PII; суперпользователь и сервисные роли — видят.

```sql
-- 1. Включить прозрачное динамическое маскирование для БД
ALTER DATABASE foo SET anon.transparent_dynamic_masking TO true;

-- 2. Создать masked-роль с правами на чтение
CREATE ROLE analyst LOGIN PASSWORD 'password';
GRANT pg_read_all_data TO analyst;
--   или гранулярно:
--   GRANT USAGE ON SCHEMA public TO analyst;
--   GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst;

-- 3. Пометить роль как MASKED
SECURITY LABEL FOR anon ON ROLE analyst IS 'MASKED';

-- 4. Подключиться как analyst
\c - analyst
SELECT * FROM people;
-- → id | firstname | lastname  |   phone
-- → T1 | Sarah     | Stranahan | 06******11
```

Особенности и ограничения (документация):

- Masked-роли не должны иметь INSERT/UPDATE/DELETE; им запрещён `EXPLAIN`.
- К masked-ролям применимы Row-Level Security (RLS) — см. **[Управление ролями](./role_management.md)**.
- Генерируемые столбцы по умолчанию пересчитываются из замаскированных значений; чтобы вернуть исходное хранимое значение: `SECURITY LABEL FOR anon ON COLUMN users.email_hash IS 'NOT MASKED';`.
- Правило может нарушить целостность: например, маскирование UNIQUE-столбца значением `NULL`. Ответственность за выбор — за администратором.
- Правила можно объявлять в нескольких схемах.
- Снять маскирование с роли: `SECURITY LABEL FOR anon ON ROLE analyst IS NULL;`.

Производительность: динамическое маскирование добавляет накладные расходы на выполнение запросов; для тяжёлой аналитики предпочтительны статические анонимизированные копии (см. сценарий 5) или Replica Masking (анонимизированный клон через logical replication).

### 4. Анонимный дамп

Сценарий: передать разработчикам выгрузку Production-базы без PII. Утилиты `pg_dump_anon` (golang, 1.x) и `pg_dump_anon.sh` (bash, 0.x) **deprecated** — современный способ: выгрузка под masked-ролью обычным `pg_dump`.

```sql
-- 1. Masked-роль для выгрузки
CREATE ROLE anon_dumper LOGIN PASSWORD 'x';
ALTER ROLE anon_dumper SET anon.transparent_dynamic_masking = True;
SECURITY LABEL FOR anon ON ROLE anon_dumper IS 'MASKED';
GRANT pg_read_all_data TO anon_dumper;
```

```bash
# 2. Выгрузка под masked-ролью
pg_dump foo \
  --user anon_dumper \
  --no-security-labels \
  --exclude-extension="anon" \
  --file=foo_anonymized.sql
# → в дампе замаскированные данные и БЕЗ самих правил маскирования
```

Примечания:

- `--no-security-labels` обязателен: masked-роль не должна получить доступ к политике маскирования.
- `--exclude-extension` доступен только в `pg_dump` 17+; для более старых версий документация предлагает `--extension plpgsql` как альтернативу. Поддерживается `--format=custom`.
- Согласованность (consistency) выгрузки обеспечивается самим `pg_dump` (single snapshot); в старых версиях (0.x–1.x) согласованность `pg_dump_anon` не гарантировалась.
- «Чёрный ящик» (Docker): `cat dump.sql rules.sql | docker run --rm --interactive registry.gitlab.com/dalibo/postgresql_anonymizer:stable /dump.sh > anon_dump.sql` — работает только с plain-форматом (`-Fp`).

### 5. Статическое маскирование

Сценарий: Dev-сервер, восстановленный из свежего Production-бэкапа. **Необратимая операция — никогда не запускайте в Production.**

```sql
-- Применяет все правила политики 'anon' ко всей БД
SELECT anon.anonymize_database();

-- Или подмножество:
SELECT anon.anonymize_schema('public');
SELECT anon.anonymize_table('customer');
SELECT anon.anonymize_column('customer','zipcode');
```

Операционные нюансы:

- Статическое маскирование медленное: перезаписываются все строки всех таблиц с маскированными столбцами. На больших БД часто быстрее выгрузить анонимный дамп (сценарий 4) и загрузить его в целевую БД.
- Параллельное выполнение: `SELECT anon.anonymize_database_parallel(4);` — анализирует FK, группирует связанные таблицы (обрабатываются последовательно), независимые таблицы распределяет по фоновым воркерам. Количество воркеров ограничено GUC `anon.max_bg_workers` (1–64, дефолт 4) и `max_worker_processes` (дефолт 8). **Функция не атомарна**: при отказе воркера остальные не откатываются — часть таблиц останется незамаскированной; ошибки пишутся в лог PostgreSQL (не в stdout), при `false` на выходе повторите маскирование через `anon.anonymize_table()`.
- Бета-ускорение за счёт индексов: `SET anon.static_masking.drop_indexes = on;` — обычные вторичные индексы сбрасываются до маскирования и пересоздаются после (в одной транзакции). Оговаривается: блокировка таблицы повышается до `ACCESS EXCLUSIVE` (блокирует и чтение), индексы PK/UNIQUE/constraint/partitioned не сбрасываются, таблицы с deferrable constraints пропускаются с `NOTICE`. После маскирования выполните `ANALYZE`.
- Отключить статическое маскирование (защита от случайного запуска): `ALTER SYSTEM SET anon.static_masking TO off;` или выборочно — `ALTER ROLE bob SET anon.static_masking TO off;` (и наоборот: выключить для всех, включить для одной роли).

### 6. Перемешивание и шум по столбцу

Вертикальные операции (не являются masking functions — работают со столбцом целиком):

```sql
-- Перемешивание значений внутри столбца; сохраняет ссылочную
-- целостность — удобно для внешних ключей (нужен первичный ключ таблицы)
SELECT anon.shuffle_column('customer', 'fk_shop', 'id');

-- Шум по всему столбцу: ±33% для чисел, ±2 days для дат
SELECT anon.add_noise_on_numeric_column('customer', 'salary', 0.33);
SELECT anon.add_noise_on_datetime_column('customer', 'birth', '2 days');
```

### 7. Обобщённые представления и k-анонимность

Обобщение (generalization) заменяет значение диапазоном, содержащим его: `54` → `[50,60)`, `1979-12-29` → `["1970-01-01","1980-01-01")`. Это преобразование типов данных, поэтому **не работает с динамическим маскированием** — применяйте в представлениях:

```sql
CREATE VIEW anonymized_patient AS
SELECT
    'REDACTED' AS lastname,
    anon.generalize_int4range(zipcode, 100) AS zipcode,
    anon.generalize_tsrange(birth, 'decade') AS birth,
    disease
FROM patients;
-- → zipcode: [47600,47700);  birth: ["1970-01-01","1980-01-01")
```

Доступны `generalize_int4range`, `generalize_int8range`, `generalize_numrange(value, step)` и `generalize_tsrange(value, 'decade')`. Обобщённые значения остаются истинными для статистики, но снижают риск реидентификации.

Для проверки k-анонимности объявляйте косвенные идентификаторы отдельной политикой и проверяйте набор данных:

```sql
SECURITY LABEL FOR k_anonymity ON COLUMN users.zipcode IS 'INDIRECT IDENTIFIER';
SELECT anon.k_anonymity('anonymized_patient');
```

Поиск столбцов-кандидатов в идентификаторы по словарю имён: `SELECT anon.detect('en_US');` (словари `en_US`, `fr_FR`).

### 8. Проверка результата

```sql
-- 1. Правила, объявленные в текущей БД (в 3.x; в ≤2.x — anon.pg_masking_rules)
SELECT * FROM anon.user_rules;

-- 2. Подключиться как masked-роль и сравнить вывод
\c - analyst
SELECT email, phone FROM users LIMIT 5;
-- → значения должны быть замаскированы

-- 3. Для дампа: развернуть в холостую БД и проверить отсутствие PII
psql -h dev -U postgres -d scratch -f foo_anonymized.sql
psql -h dev -U postgres -d scratch -c "SELECT count(*) FROM users WHERE email LIKE '%@gmail.com';"
-- → 0 (все адреса фиктивные)
```

Методология валидации бэкапов — в **[Валидации бэкапов](../../Concepts/backup_validation.md)**.

### 9. Очистка и откат

```sql
-- Снять динамическое маскирование
SECURITY LABEL FOR anon ON ROLE analyst IS NULL;
ALTER DATABASE foo RESET anon.transparent_dynamic_masking;

-- Удалить все правила (рекомендуется перед DROP EXTENSION)
SELECT anon.remove_masks_for_all_columns();
SELECT anon.remove_masks_for_all_roles();

-- Удалить расширение
DROP EXTENSION anon;

-- Выгрузить библиотеку
ALTER SYSTEM RESET shared_preload_libraries;   -- + перезапуск
-- или: ALTER DATABASE foo RESET session_preload_libraries;
```

```bash
# Удалить пакет (замените 16 на вашу версию PG)
sudo yum remove postgresql_anonymizer_16
```

**Откат статического маскирования невозможен** — оригинальные данные уничтожены; восстановление только из бэкапа.

**Апгрейд расширения:** `ALTER EXTENSION anon UPDATE` не поддерживается — после каждого апгрейда расширение нужно удалить и создать заново. Перед апгрейдом с 2.x на 3.x отключите legacy dynamic masking: `SELECT anon.stop_legacy_dynamic_masking();`. В 3.2 изменилась JSON-схема импорта/экспорта правил — после апгрейда правила нужно переэкспортировать.

## Справочник функций маскирования

| Стратегия | Функция | Результат / примечание |
| :--- | :--- | :--- |
| Destruction | `MASKED WITH VALUE NULL` / `VALUE 'CONFIDENTIAL'` | Уничтожение / константа |
| Noise | `anon.noise(val, 0.33)` | Число ±33% (integer/bigint/double precision) |
| Noise | `anon.dnoise(val, '10 years')` | Дата/timestamp/time ±interval |
| Noise | `anon.noisy_gps_coordinates(origin, 10.0, true)` | GPS в радиусе (км по умолчанию) |
| LDP | `anon.ldp_grrm(val, 1.0, 5)` | Local Differential Privacy (GRRM), ε=1.0, 1..5 |
| LDP | `anon.ldp_grrm_pttt(val, 0.65, 5)` | То же, через долю «правдивых» ответов |
| Randomization | `anon.random_int_between(10,100)` | Случайное int (границы включены) |
| Randomization | `anon.random_date_between(d1,d2)`, `random_bigint_between` | Аналог для дат/bigint |
| Randomization | `anon.random_in(ARRAY['red','green'])`, `random_in_enum(NULL::card)` | Выбор из массива/ENUM |
| Randomization | `anon.random_in_daterange('[2001-01-01,2001-12-31)')` | Случайное значение из RANGE (∞-граница → NULL) |
| Randomization | `anon.random_id()` / `random_id_int()` / `random_id_small_int()` | Уникальные значения для SERIAL; сброс `pg_catalog.setval('anon.random_id_seq',42)` |
| Randomization | `anon.random_string(10)`, `random_zip()`, `random_phone('+7')`, `random_hash(seed)` | Прочие генераторы |
| Faking (v1, требует `anon.init()`) | `anon.fake_email()`, `fake_first_name()`, `fake_last_name()`, `fake_city()`, `fake_company()`, `fake_address()`, `fake_country()`, `fake_iban()`, `fake_postcode()`, `fake_siret()`, `lorem_ipsum(words := 20)` | Фиктивные данные (en, 1000 значений/категория) |
| Advanced faking (v2, fake-rs) | `anon.dummy_first_name()`, `dummy_last_name()`, `dummy_name()`, `dummy_phone_number()`, `dummy_credit_card_number()`, `dummy_free_email()`, `dummy_ip()`, `dummy_ipv4()`, `dummy_ipv6()`, `dummy_uuidv4()`, `dummy_company_name()`, `dummy_city_name()`, `dummy_post_code()`, `dummy_mac_address()` и 70+ функций | Локализованные данные; суффикс `_locale('fr_FR')`; локали: ar_SA, en_US (дефолт), fr_FR, ja_JP, pt_BR, zh_CN, zh_TW. Новые пользователи должны предпочитать `dummy_*` |
| Pseudonymization (детерминированная) | `anon.seeded_email(login)`, `seeded_first_name(seed,locale,salt)` и др. (8 функций) | Один и тот же seed → один и тот же псевдоним; locale/salt опциональны |
| Pseudonymization PK | `anon.pseudo_shift(id)`, `anon.pseudo_xor(id)` | Сдвиг/XOR первичного ключа; секрет `anon.shift`, задаётся `anon.set_shift()` / `anon.set_shift(int)` |
| Hashing | `anon.hash(value)` | sha256 (дефолт) с солью из GUC `anon.salt`; алгоритм — GUC `anon.algorithm` (md5/sha224/sha256/sha384/sha512) |
| Hashing | `anon.digest(value, 'salt', 'sha384')` | Явные соль/алгоритм (не рекомендуется — соль видна в правиле) |
| Partial scrambling | `anon.partial('abcdefgh',1,'xxxx',3)` | `axxxxfgh` |
| Partial scrambling | `anon.partial_email('daamien@gmail.com')` | `da******@gm******.com` |
| Partial scrambling | `anon.array_remove_regex(disease,'(?i)(hiv|aids)')` | Удаление значений из массива по regexp |
| Conditional | `anon.ternary(score IS NULL, NULL, anon.random_int_between(0,100))` | Аналог `CASE WHEN` в правиле |
| Generalization | `anon.generalize_int4range(age, 10)`, `generalize_tsrange(birth,'decade')` | Диапазон, содержащий значение (только представления) |
| Image | `anon.image_blur(photo, 5.0)` | Размытие BYTEA (σ по умолчанию 10.0) |
| pg_catalog-привязки | `anon.md5(x)`, `anon.left(str,12)`, `anon.length(col)`, `anon.concat(a,b)` | TRUSTED-замены системных функций в правилах |
| Vertical | `anon.shuffle_column(t,c,pk)`, `anon.add_noise_on_numeric_column(t,c,ratio)`, `anon.add_noise_on_datetime_column(t,c,interval)` | Операции над столбцом целиком |
| Static masking | `anon.anonymize_database()`, `anonymize_schema(s)`, `anonymize_table(t)`, `anonymize_column(t,c)` | Применение правил к данным (последний аргумент — имя политики) |
| Diagnostics | `anon.is_initialized()`, `anon.user_rules`, `anon.pg_trusted_functions`, `anon.detect('en_US')`, `anon.k_anonymity('table')` | Состояние, правила, доверенные функции, поиск идентификаторов |

Собственные маскирующие функции: создайте функцию в отдельной схеме, объявите схему доверенной (`SECURITY LABEL FOR anon ON SCHEMA my_masks IS 'TRUSTED';`) — функция должна быть `VOLATILE` и либо разрушительной, либо вносящей случайность. Это стандартный путь для JSONB-полей с вложенными PII.

## Настройка (GUC)

| Параметр | Дефолт | Назначение |
| :--- | :--- | :--- |
| `anon.algorithm` | `sha256` | Алгоритм для `anon.hash()` |
| `anon.salt` | `''` | Соль для `anon.hash()`; задаётся `ALTER DATABASE foo SET anon.salt TO '...'` |
| `anon.privacy_by_default` | `off` | Все столбцы БД маскируются по умолчанию (значением DEFAULT или NULL; для NOT NULL-столбцов нужен DEFAULT) |
| `anon.transparent_dynamic_masking` | `off` | Включает прозрачное динамическое маскирование (БД или роль) |
| `anon.static_masking` | `on` | Разрешает/запрещает статическое маскирование (глобально или на роль) |
| `anon.static_masking.drop_indexes` | `off` (beta) | Ускорение статического маскирования через сброс вторичных индексов |
| `anon.max_bg_workers` | `4` | Лимит воркеров параллельного маскирования (1–64; capped `max_worker_processes`) |
| `anon.restrict_to_trusted_schemas` | — | Ограничение правил функциями из доверенных схем (`pg_catalog`, `anon`; `public` не доверена) |
| `anon.nosuperuser` | `TRUE` (3.x) | Запрет маскирования для суперпользователя; `FALSE` возвращает старое поведение (риск) |
| `anon.shift` | — | Секрет для `pseudo_shift`/`pseudo_xor`; инициализация `anon.set_shift()` |

Установка значений: `ALTER DATABASE foo SET anon.salt TO 'xsfnjefnjsnfjsnf';` (рекомендуется — БД-уровень) или `ALTER SYSTEM SET ...` + `pg_reload_conf()`.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `CREATE EXTENSION anon` не находит модуль | Пакет не установлен на хосте | `ls $(pg_config --sharedir)/extension/anon` и `ls $(pg_config --pkglibdir)/anon.so`; установить пакет |
| `SELECT anon.is_initialized()` → `f` | Не выполнена `anon.init()` | `SELECT anon.init();` |
| Правила объявлены, но видны реальные данные | Библиотека не загружена или сессия старая | `SHOW shared_preload_libraries; SHOW session_preload_libraries;`; при `session_preload_libraries` — переподключиться, при `shared_preload_libraries` — перезапустить сервер |
| `ERROR: Cannot mask a "NOT NULL" column with a NULL value` | `privacy_by_default` + NOT NULL без DEFAULT | Задать `DEFAULT` для столбца |
| В дампе содержатся сами правила маскирования | Забыт `--no-security-labels` | Добавить флаг к `pg_dump` |
| `pg_dump: ошибка: unknown option --exclude-extension` | `pg_dump` < 17 | Обновить клиент или использовать `--extension plpgsql` |
| Коллизии на UNIQUE-столбце (два разных значения → один псевдоним) | Набор данных меньше числа строк | Увеличить набор (`anon.init()` с большим словарём), использовать `seeded_*` с солью или `random_id()` |
| Ошибка хеширования на backslash/спецсимволах | Незаэкранированные символы в данных (баг приложения) | Санитизация ввода; не отключать `standard_conforming_strings` (Issue 539) |
| `md5(phone)` отклоняется в правиле | `pg_catalog` не доверен с 1.3 | Использовать `anon.md5(phone)` или `SECURITY LABEL FOR anon ON FUNCTION pg_catalog.md5 IS 'TRUSTED';` |
| Оператор `\|\|` отклонён в правиле | С 1.3 операторы запрещены в `MASKED WITH FUNCTION` | Заменить на `anon.concat(a, b)` |
| Статическое маскирование очень медленное | Полная перезапись данных на диске | `anonymize_database_parallel(n)`; `SET anon.static_masking.drop_indexes = on;`; либо export (сценарий 4) + reload |
| `anonymize_database_parallel()` вернула `false` | Отказ воркера; функция не атомарна | Смотреть лог PostgreSQL (ошибки не в stdout); найти незамаскированные таблицы; повторить через `anonymize_table()` |
| Данные доступны через курсоры или `pg_dump --insert` на версии 2.0/2.1 | Известная уязвимость, исправлена в 2.2 | Обновиться до ≥2.2 (лучше 3.x); временно `ALTER SYSTEM SET anon.transparent_dynamic_masking = OFF;` |
| `anon.pg_masking_rules` пуста/ошибка после апгрейда | В 3.x представление переименовано | Использовать `anon.user_rules` |
| Привилегии пользователя-владельца объектов использованы для выполнения SQL от имени суперпользователя (≤1.2) | Уязвимость SQL-инъекции при создании/обновлении правил, исправлена в 1.3 | Обновиться до ≥1.3 (актуально — 3.x) |

## Лучшие практики

1. **Минимизация:** маскируйте всё, что не требуется потребителю данных. Лучше замаскировать лишнее, чем оставить PII.
2. **Детерминизм для связей:** если тестам важны связи между таблицами (один `user_id` в разных таблицах), используйте `anon.seeded_*(...)` или `anon.hash()` — одинаковый вход даёт одинаковый выход.
3. **Соль хеширования — секрет:** `anon.salt` и алгоритм защищайте на уровне самого набора данных; иначе хеш подбирается brute-force/dictionary-атакой. Предпочитайте `anon.hash()` (соль в GUC) `anon.digest()` (соль в правиле).
4. **Шум — не для динамики:** `noise()`/`dnoise()` уязвимы к repeat attack (masked-пользователь многократно запрашивает значение и усредняет). Только для анонимных дампов и статического маскирования.
5. **Условное маскирование деанонимизирует:** `anon.ternary()` с сохранением NULL (например, для `deceased_date`) раскрывает, кто жив. Проверяйте вывод на утечки.
6. **Права masked-ролей:** только чтение (`GRANT SELECT`), без `EXPLAIN`; RLS комбинируется с динамическим маскированием.
7. **Доверенные схемы:** включите `anon.restrict_to_trusted_schemas`; собственные функции — в отдельной доверенной схеме, не в `public`.
8. **Версия:** используйте ≥2.2 (исправление обхода через курсоры), актуально — 3.x; пиньте версию пакета. Правила версионируйте вместе с миграциями схемы.
9. **Разделение сред:** динамическое маскирование — для доступа к Production; статическое маскирование и дампы — для Dev/Staging, строго на sandbox после восстановления бэкапа и до выдачи доступа разработчикам.
10. **Анализ после маскирования:** после статического маскирования (особенно с `drop_indexes`) выполните `ANALYZE`; для параллельного маскирования проверяйте лог и факт маскирования каждой таблицы.
11. **Хеширование ≠ анонимизация:** `anon.hash()` — это псевдонимизация; результат можно деанонимизировать при доступе к функции и соли.

## Дополнительная информация

### См. также

- **[Управление ролями в PostgreSQL](./role_management.md)** — RLS, гранты, `pg_read_all_data`.
- **[Безопасность и шифрование](../Concepts/security_and_encryption.md)** — RLS, pgcrypto, TDE.
- **[Безопасность бэкапов](../../Concepts/backup_security.md)** — где и как применять анонимизацию.
- **[Валидация бэкапов](../../Concepts/backup_validation.md)** — проверка результата маскирования.
- **[Наблюдаемость](./observability.md)** — PII в логах.
- **[Маскирование в MariaDB (MaxScale)](../../MariaDB/MaxScale/maxscale_overview.md)** — аналог динамического маскирования через прокси для MariaDB.

### Ссылки

- [Официальная документация](https://postgresql-anonymizer.readthedocs.io/en/latest/) (INSTALL, Masking Functions, Dynamic/Static Masking, Anonymous Dumps, UPGRADE)
- [Репозиторий проекта](https://gitlab.com/dalibo/postgresql_anonymizer)
- [Матрица поддерживаемых версий](https://postgresql-anonymizer.readthedocs.io/en/latest/support/)
