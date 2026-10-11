# Кодировки и сопоставления (Charset & Collation) в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Character Set (кодировка, charset)** — набор символов и их кодов. Определяет, какие символы могут храниться. Например, `utf8mb4` — Unicode UTF-8 (до 4 байт на символ), `latin1` — однобайтовая кодировка для западноевропейских языков.
*   **Collation (сопоставление)** — набор правил сравнения символов кодировки: сортировка, равенство, учёт регистра и акцентов. Например, `utf8mb4_general_ci` — регистронезависимое (`ci` = case-insensitive), `utf8mb4_bin` — побитовое сравнение.
*   **UCA (Unicode Collation Algorithm)** — стандарт алгоритма сопоставления Unicode. MariaDB реализует UCA 4.0.0 (`*_unicode_ci`), UCA 5.2.0 (`*_unicode_520_ci`), UCA 9.0.0 (`utf8mb4_0900_*`, с MariaDB 11.4.5) и UCA 14.0.0 (`utf8mb4_uca1400_*`, с MariaDB 10.10, MDEV-27009).
*   **`character_set_server` / `collation_server`** — серверные кодировка и сопоставление по умолчанию для новых баз данных.
*   **`character_set_database` / `collation_database`** — кодировка и сопоставление текущей (по умолчанию) базы данных.
*   **`character_set_collations`** — карта (map) допустимых сопоставлений для каждой кодировки. Начиная с MariaDB 11.5 карта не-пустая по умолчанию, что позволяет ограничить набор доступных collation для charset.
*   **Суррогатные пары (Surrogate Pairs)** — пара 16-битных кодов для представления символов вне BMP (например, эмодзи). Требуют `utf8mb4`; в `utf8` (3 байта) не помещаются.

## Базовые концепции

### Иерархия кодировок

Кодировка и сопоставление задаются на четырёх уровнях (каждый уровень наследует от вышестоящего, если не задан явно):

1.  **Server** (`character_set_server`, `collation_server`) — по умолчанию для новых БД.
2.  **Database** (`character_set_database`, `collation_database`) — по умолчанию для новых таблиц.
3.  **Table** — задаётся в `CREATE TABLE ... DEFAULT CHARACTER SET ... COLLATE ...`.
4.  **Column** — задаётся в определении столбца.

Дополнительно существуют клиентские переменные: `character_set_client`, `character_set_connection`, `character_set_results`, `character_set_system` (всегда `utf8`).

### Значения по умолчанию — критично для версии

| Версия MariaDB | `character_set_server` | `collation_server` |
| :--- | :--- | :--- |
| **< 11.6** | `latin1` | `latin1_swedish_ci` |
| **11.6+** (первый LTS — 11.8) | `utf8mb4` | `utf8mb4_uca1400_ai_ci` |

**Важно для миграции и репликации:** при обновлении с 10.11/11.4 на 11.8+ дефолтная кодировка меняется с `latin1` на `utf8mb4`. Новые БД, созданные после обновления без явного указания charset, получат `utf8mb4`.

### Сопоставления utf8mb4

| Collation | UCA | Появление | Особенности |
| :--- | :--- | :--- | :--- |
| `utf8mb4_general_ci` | — | все версии | Упрощённое сравнение, быстрее, менее точно |
| `utf8mb4_unicode_ci` | 4.0.0 | все версии | Точнее general_ci |
| `utf8mb4_unicode_520_ci` | 5.2.0 | все версии | UCA 5.2.0 |
| `utf8mb4_0900_ai_ci` | 9.0.0 | **11.4.5+** | MySQL-совместимое (MySQL 8.0 default) |
| `utf8mb4_uca1400_ai_ci` | 14.0.0 | **10.10+** (MDEV-27009) | Дефолт с 11.5/11.6 |

**Default collation для `utf8mb4`:**
*   MariaDB ≤ 11.4: `utf8mb4_general_ci`
*   MariaDB ≥ 11.5: `utf8mb4_uca1400_ai_ci`

**Репликационный риск:** `utf8mb4_uca1400_ai_ci` недоступен в MariaDB < 10.10. При репликации с 11.8+ на 10.11 таблица с этим collation не будет воспроизведена. Проверяйте совместимость collation перед обновлением.

## Практические сценарии

### 1. Проверка текущих кодировок

```sql
-- Серверные значения
SHOW VARIABLES LIKE 'character_set_server';
SHOW VARIABLES LIKE 'collation_server';

-- Значения текущей БД
SELECT @@character_set_database, @@collation_database;

-- Все кодировки и их дефолтные collation
SHOW CHARACTER SET;

-- Все collation для utf8mb4
SHOW COLLATION LIKE 'utf8mb4%';

-- Кодировка конкретной таблицы
SELECT TABLE_COLLATION FROM information_schema.TABLES
  WHERE TABLE_SCHEMA = 'shop' AND TABLE_NAME = 'orders';

-- Кодировка столбцов
SELECT COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shop' AND TABLE_NAME = 'orders';
```

### 2. Настройка кодировок

```ini
# my.cnf
[mariadb]
character_set_server = utf8mb4
collation_server = utf8mb4_uca1400_ai_ci   # или utf8mb4_general_ci для совместимости
```

```sql
-- На уровне БД
CREATE DATABASE shop CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;

-- На уровне таблицы
CREATE TABLE orders (
  id INT PRIMARY KEY,
  comment VARCHAR(500)
) DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;

-- На уровне столбца
ALTER TABLE orders MODIFY comment VARCHAR(500)
  CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;
```

### 3. Конвертация кодировки таблицы

```sql
-- Конвертация таблицы и всех текстовых столбцов
ALTER TABLE orders CONVERT TO CHARACTER SET utf8mb4
  COLLATE utf8mb4_uca1400_ai_ci;

-- Важно: CONVERT TO выполняет полное перестроение таблицы.
-- Для больших таблиц используйте pt-online-schema-change:
pt-online-schema-change --alter "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_uca1400_ai_ci" \
  D=shop,t=orders --execute
```

**Валидация:** после конвертации проверьте `information_schema.COLUMNS` — все текстовые столбцы должны иметь `utf8mb4`.

### 4. Ограничение набора collation (MariaDB 11.5+)

```sql
-- Установить карту допустимых collation для utf8mb4
SET GLOBAL character_set_collations = 'utf8mb4:utf8mb4_uca1400_ai_ci,utf8mb4_general_ci';

-- Проверить текущую карту
SHOW VARIABLES LIKE 'character_set_collations';
```

### 5. Поиск проблем с кодировкой (mojibake)

```sql
-- Найти столбцы не в utf8mb4
SELECT TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'shop'
  AND (CHARACTER_SET_NAME != 'utf8mb4' OR CHARACTER_SET_NAME IS NULL)
  AND DATA_TYPE IN ('char','varchar','text','tinytext','mediumtext','longtext');

-- Проверить, что клиентская кодировка совпадает
SELECT @@character_set_client, @@character_set_connection, @@character_set_results;
-- Ожидается utf8mb4 для всех трёх
```

## Устранение неполадок (Troubleshooting)

### «Incorrect string value» при вставке эмодзи или кириллицы

*   **Причина:** столбец или таблица в `latin1` или `utf8` (3 байта), а данные требуют 4 байт (utf8mb4).
*   **Диагностика:** `SHOW CREATE TABLE` — проверьте charset столбца.
*   **Решение:** конвертируйте в `utf8mb4` (`ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4`).

### Разное поведение сортировки после обновления

*   **Причина:** с MariaDB 11.5 дефолтный collation `utf8mb4` изменился с `utf8mb4_general_ci` на `utf8mb4_uca1400_ai_ci`. UCA 14.0.0 сортирует иначе, чем `general_ci`.
*   **Решение:** если требуется прежнее поведение, явно укажите `COLLATE utf8mb4_general_ci` на уровне таблицы или столбца.

### Репликация прерывается на collation

*   **Причина:** на source используется collation, отсутствующий на replica (например, `utf8mb4_uca1400_ai_ci` на 11.8 source, replica на 10.11).
*   **Решение:** обновите replica до версии, поддерживающей collation, или используйте совместимый collation на source.

## Лучшие практики (Best Practices)

1.  **Явно задавайте charset:** не полагайтесь на серверный дефолт — указывайте `CHARACTER SET utf8mb4` в `CREATE DATABASE` / `CREATE TABLE`.
2.  **utf8mb4, а не utf8:** `utf8` в MariaDB — 3-байтовый UTF-8, не хранит эмодзи и часть иероглифов. Используйте `utf8mb4`.
3.  **Выбор collation:** `utf8mb4_uca1400_ai_ci` (точный, UCA 14.0.0) для новых проектов на 11.5+; `utf8mb4_general_ci` — для совместимости со старыми версиями.
4.  **Единообразие в репликации:** `character_set_server` и `collation_server` должны совпадать на всех узлах.
5.  **Проверяйте совместимость collation** перед обновлением версии (особенно при переходе на 11.5+).

## Дополнительная информация

### См. также

*   **[Репликация: обзор](replication/overview.md)** — требование совпадения charset на узлах.
*   **[Миграция с MySQL](Operations/migration_mysql_to_mariadb.md)** — отличия кодировок MySQL и MariaDB.
*   **[MySQL: Charset & Collation](../MySQL/charset-and-collation.md)** — отличия MySQL (utf8mb4_0900_ai_ci default в MySQL 8.0).

### Внешние ресурсы

*   [MariaDB Character Sets](https://mariadb.com/kb/en/character-sets/)
*   [MariaDB Collations](https://mariadb.com/kb/en/collations/)
*   [MariaDB UCA Collations](https://mariadb.com/kb/en/uca-collations/)
*   [MDEV-27009: UCA 14.0.0 collations](https://jira.mariadb.org/browse/MDEV-27009)
