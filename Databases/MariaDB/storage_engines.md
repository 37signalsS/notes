# Движки хранения в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Движок хранения (Storage Engine)** — программный модуль СУБД, отвечающий за низкоуровневые операции с данными: физическое хранение на диске, индексацию, управление блокировками и обеспечение транзакционности. В MariaDB используется подключаемая архитектура (**Pluggable Storage Engine API**), позволяющая выбирать движок индивидуально для каждой таблицы.

**Pluggable Storage Engine API** — интерфейс, через который движки взаимодействуют с ядром MariaDB. Это позволяет использовать разные движки в одной базе данных без перекомпиляции сервера и регистрировать их динамически через `INSTALL SONAME`.

**LSM-дерево (Log-Structured Merge-tree)** — структура данных, оптимизированная для записи, используемая в движке MyRocks. Она преобразует случайную запись в последовательную, буферизуя данные в памяти и периодически сбрасывая их на диск (SST-файлы) с последующим фоновым уплотнением (compaction).

**MPP (Massively Parallel Processing)** — архитектура, применяемая в ColumnStore, где аналитический запрос распределяется между несколькими вычислительными узлами (**Performance Modules**), каждый из которых обрабатывает свою часть данных параллельно.

**XA / 2PC (Two-Phase Commit)** — протокол распределенных транзакций, используемый в Spider для обеспечения атомарности между шардами.

## Базовые концепции

### Архитектура и приоритеты загрузки

MariaDB считывает конфигурацию движков в порядке, определенном иерархией `my.cnf`. Движки регистрируются через плагины; их можно загружать динамически (`INSTALL SONAME`) или статически при компиляции.

**Важно для SRE:** При обновлении MariaDB проверяйте, не удалены ли системные переменные deprecated. В 12.0 удалены `big_tables`, `large_page_size`, `storage_engine`. В 11.0 удален `innodb_change_buffering`.

### Версионные изменения и инновации

#### MariaDB 12.3 LTS

1.  **Атомарные бинарные логи (Binlog-in-InnoDB):**
    - Параметр: `binlog_storage_engine=innodb`.
    - Суть: События бинарного лога пишутся непосредственно в страницы InnoDB. Это устраняет необходимость в дорогостоящей синхронизации между БД и файловой системой лога.
2.  **Сегментированный кеш Aria:**
    - Параметр: `aria_pagecache_segments` (по умолчанию `1`, макс. `128`). Устраняет конкуренцию за блокировки на процессорах с 64+ ядрами.
3.  **Удаление Change Buffer:**
    - Полное удаление механизма `innodb_change_buffering` (начиная с 11.0). MariaDB теперь напрямую пишет в страницы индексов, что эффективнее на NVMe-дисках.

#### MariaDB 11.4 LTS / 11.8 LTS

- `innodb_snapshot_isolation` по умолчанию изменен на `ON` (в 12.3 LTS; в 11.6.2+ для 11.x). Это меняет семантику транзакций `REPEATABLE READ`. Приложения, зависящие от предыдущего поведения, должны быть протестированы перед апгрейдом.

### Основные движки (Core Engines)

**InnoDB:** Универсальный транзакционный движок по умолчанию.
- **Особенности:** Полная поддержка ACID, внешние ключи, MVCC (Multi-Version Concurrency Control).
- **Производительность:** Начиная с 12.3 LTS включена опция `innodb_snapshot_isolation=ON` по умолчанию для повышения согласованности транзакций.
- **SRE-тюнинг:** Подробный расчёт буферов и диагностика утечек см. в **[Управление памятью в MariaDB](memory_management.md)**.

**Aria:** Усовершенствованная crash-safe замена MyISAM.
- **Назначение:** Используется для системных таблиц MariaDB и сложных временных таблиц.
- **Преимущества:** Быстрое восстановление после сбоя через логи транзакций без накладных расходов на полную MVCC-изоляцию.
- **Оптимизация 12.3:** Сегментированный кеш (`aria_pagecache_segments`) снижает contention на многоядерных системах.

**MyRocks:** Движок на базе LSM-дерева (RocksDB).
- **Преимущества:** Экстремальное сжатие данных (в 3-4 раза лучше InnoDB) и минимизация износа SSD (Write Amplification).
- **Ограничения:** Не поддерживает внешние ключи (Foreign Keys), пространственные индексы, полнотекстовый поиск, SERIALIZABLE и Transportable Tablespace. Не совместим с Galera Cluster.
- **SRE-тюнинг:** Подробно в **[Управлении памятью в MariaDB](memory_management.md)** (раздел про MyRocks Block Cache).

**ColumnStore:** Колоночный движок для распределенной аналитики (OLAP).
- **Архитектура MPP (Massively Parallel Processing):**
    - **User Module (UM):** SQL-слой, агрегация данных, управление метаданными.
    - **Performance Module (PM):** Операции ввода-вывода, вычисления над экстентами.
- **Эксплуатация:** Утилита `cpimport` работает напрямую с PM, минуя SQL-слой.

**Spider:** Движок для прозрачного шардирования.
- **Функция:** Распределяет данные одной таблицы между несколькими удаленными узлами MariaDB.
- **Распределенные транзакции:** Поддержка XA (2PC) для обеспечения атомарности между шардами.

### Вспомогательные и специализированные движки

**S3:** Движок для холодного хранения архивных таблиц в S3-совместимых объектных хранилищах. Таблицы только для чтения, поддержка сжатия zlib. Позволяет нескольким инстансам MariaDB видеть один набор архивных данных.

**Archive:** Максимальное сжатие для логов без индексов. Поддерживает только `INSERT` и `SELECT`.

**Memory:** Сверхвысокая скорость в оперативной памяти. Данные теряются при перезагрузке.

**Sequence:** Виртуальный генератор числовых последовательностей.

**Connect:** Интеграция с внешними данными (ETL).

**Mroonga:** Полнотекстовый поиск на базе Groonga.

**OQGRAPH:** Графовый движок.

## Предварительные требования

При планировании использования специализированных движков учитывайте:

- **MyRocks:** Требует отдельного `rocksdb_block_cache_size`. Не работает с Galera. Подходит для SSD/NVMe с высокой записью.
- **ColumnStore:** Требует отдельной установки PM-узлов. Минимум 3 узла для distributed режима.
- **Spider:** Требует настройки удаленных соединений и XA-транзакций.
- **S3:** Требует установки плагина `ha_s3` и настроенного доступа к объектному хранилищу.
- **Общие:** Пользователь `mysql` должен иметь права на запись в `datadir`, каталог логов и каталог сокета. Для production ОЗУ >= 8GB, диск с поддержкой `O_DIRECT` (ext4, XFS).

## Практические сценарии

### 1. Выбор движка по типу нагрузки

| Нагрузка | Рекомендуемый движок | Обоснование |
| :--- | :--- | :--- |
| **OLTP (транзакции)** | InnoDB | ACID, MVCC, внешние ключи, максимальная производительность на SSD |
| **Архив / лог-таблицы** | Aria / Archive | Crash-safe, низкое потребление памяти, сжатие |
| **Высокая запись (Write-intensive)** | MyRocks | LSM-дерево минимизирует износ SSD, высокое сжатие |
| **Аналитика (OLAP)** | ColumnStore | Колоночное хранение, MPP, векторизация |
| **Шардирование** | Spider | Прозрачное распределение между узлами |
| **Холодный архив** | S3 | Объектное хранение, минимальная стоимость хранения |

### 2. Миграция таблицы между движками

```sql
-- Проверка текущего движка
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE 
FROM information_schema.TABLES 
WHERE TABLE_SCHEMA = 'your_db';
-- → ENGINE = 'InnoDB'

-- Перевод в MyRocks (требует перестроения индексов)
ALTER TABLE large_logs ENGINE=MyRocks;

-- Проверка после миграции
SHOW CREATE TABLE large_logs;
-- → ENGINE=MyRocks
```

**Валидация:**
```sql
-- Проверка совместимости (MyRocks не поддерживает FK)
SELECT CONSTRAINT_NAME, TABLE_NAME
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = 'your_db'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
  AND ENGINE = 'MyRocks';
-- → пустой результат
```

### 3. Настройка MyRocks для write-intensive нагрузки

```ini
[mariadb]
# Размер Block Cache (аналог Buffer Pool для MyRocks)
rocksdb_block_cache_size = 8G

# Фоновые задачи compaction ( ~ CPU_cores / 2)
rocksdb_max_background_jobs = 4

# Уровни compaction
rocksdb_level_compaction_dynamic_level_bytes = ON
```

**Валидация:**
```sql
SHOW ENGINE ROCKSDB STATUS;
-- → cumulative compaction stats

SHOW VARIABLES LIKE 'rocksdb_block_cache_size';
-- → 8589934592 (8G)
```

### 4. Онлайн-миграция между движками (Online DDL)

Для больших таблиц используйте `pt-online-schema-change` или `gh-ost`, так как `ALTER TABLE ... ENGINE=...` блокирует запись на время копирования данных.

```bash
# Пример с pt-osc для перевода в MyRocks
pt-online-schema-change \
  --alter "ENGINE=MyRocks" \
  --execute \
  D=prod,t=events
```

### 5. Проверка поддержки функций движком

```sql
-- Проверка, какие таблицы используют нестандартные движки
SELECT TABLE_SCHEMA, TABLE_NAME, ENGINE
FROM information_schema.TABLES
WHERE ENGINE NOT IN ('InnoDB', 'Aria')
  AND TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');

-- Проверка поддержки Foreign Keys (MyRocks не поддерживает)
SELECT CONSTRAINT_NAME, TABLE_NAME
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = 'prod'
  AND CONSTRAINT_TYPE = 'FOREIGN KEY'
  AND ENGINE = 'MyRocks';
-- → пустой результат
```

### 6. Архивация холодных данных в S3

```sql
-- Перевод таблицы на S3 (требуется установленный плагин)
ALTER TABLE log_2024 ENGINE=S3 BUCKET='db-archives';
```

**Валидация:**
```sql
-- Проверка движка
SHOW TABLE STATUS FROM your_db LIKE 'log_2024';
-- → Engine: S3

-- Попытка записи (должна завершиться ошибкой)
INSERT INTO log_2024 VALUES (1, 'test');
-- → ERROR 1290 (HY000): The storage engine S3 is read-only
```

### 7. Шардирование через Spider

```sql
-- Создание серверного объекта
CREATE SERVER 'node1' FOREIGN DATA WRAPPER mysql 
  OPTIONS (HOST '192.168.1.100', DATABASE 'shards');

-- Создание распределенной таблицы
CREATE TABLE partitioned_table (id INT, val TEXT) 
  ENGINE=Spider COMMENT='wrapper "node1", table "remote_table"';
```

**Валидация:**
```sql
-- Проверка соединения с бэкендом
SHOW ENGINE SPIDER STATUS;
-- → XA_recover_prepares, активные соединения

-- Проверка распределенного запроса
SELECT COUNT(*) FROM partitioned_table;
-- → результат с удаленного узла
```

### 8. Генерация последовательностей и полнотекстовый поиск

```sql
-- Список дат за последние 7 дней
SELECT CURDATE() - INTERVAL seq DAY as day FROM seq_0_to_6;

-- Полнотекстовый поиск Mroonga
CREATE TABLE articles (id INT PRIMARY KEY, txt TEXT, FULLTEXT INDEX(txt)) ENGINE=Mroonga;
SELECT * FROM articles WHERE MATCH(txt) AGAINST('DevOps' IN BOOLEAN MODE);
```

## Устранение неполадок (Troubleshooting)

### InnoDB: Взаимоблокировки (Deadlocks)
- **Проблема:** Транзакции отменяются с кодом `Deadlock found`.
- **Диагностика:** `SHOW ENGINE INNODB STATUS` -> секция `LATEST DETECTED DEADLOCK`.
- **Решение:** Проверьте индексы и обеспечьте одинаковый порядок доступа к строкам во всех частях приложения.

### MyRocks: Write Stalls
- **Проблема:** Резкое падение скорости записи.
- **Причина:** MyRocks не успевает уплотнять уровни (Compaction).
- **Диагностика:** `SHOW ENGINE ROCKSDB STATUS` -> `Cumulative compaction stats`.
- **Решение:** Увеличьте `rocksdb_max_background_jobs` и проверьте лимиты IOPS на дисках.

### MyRocks: Отсутствие Foreign Keys
- **Проблема:** `ERROR 1245 (42000): This version of MariaDB doesn't yet support 'FOREIGN KEY for the RocksDB storage engine'`.
- **Решение:** Удалите внешние ключи перед `ALTER TABLE ... ENGINE=MyRocks`. Используйте прикладной уровень для обеспечения ссылочной целостности.

### Aria: Конкуренция за pagecache на многоядерных системах
- **Проблема:** Низкая производительность на системах с 64+ ядрами.
- **Решение:** Включите `aria_pagecache_segments > 1` (например, `8` или `16`) для снижения contention.

### S3: Ошибка загрузки плагина
- **Проблема:** `Can't find plugin: ha_s3`.
- **Решение:** Установите пакет `mariadb-plugin-s3` или загрузите плагин через `INSTALL SONAME 'ha_s3'`. Подробности см. в **[Резервном копировании MariaDB](backup_and_recovery.md)**.

### ColumnStore: Недостаточно PM-узлов
- **Проблема:** Запросы выполняются медленно или падают.
- **Диагностика:** `edg -view` -> проверка состояния экстентов.
- **Решение:** Убедитесь, что все PM-узлы доступны и имеют достаточные ресурсы.

### Spider: Разрыв соединения с бэкендом
- **Проблема:** `ERROR 7013 (HY000): Got error 2013 when reading table`.
- **Диагностика:** `SHOW ENGINE SPIDER STATUS` -> проверка `XA_recover_prepares` и активных соединений.
- **Решение:** Проверьте сетевую связность между узлами и целостность данных на бэкенде.

## Лучшие практики (Best Practices)

1. **Выбор движка по нагрузке:** Используйте InnoDB для OLTP, MyRocks для write-intensive архивов, ColumnStore для OLAP, Aria для системных таблиц. Не используйте Memory для persistентных данных.
2. **Дефолтный движок:** Устанавливайте `default_storage_engine = InnoDB` в `my.cnf` для предотвращения случайного создания таблиц в Aria/Memory.
3. **Ограничения Galera:** Galera Cluster поддерживает преимущественно InnoDB. Для production Recommended только InnoDB.
4. **Cross-engine миграция:** При переключении движка таблица полностью перестраивается. Планируйте downtime или используйте Online DDL инструменты (`pt-online-schema-change`, `gh-ost`).
5. **MyRocks и память:** При использовании MyRocks разделите память между `innodb_buffer_pool_size` и `rocksdb_block_cache_size`. Подробнее см. в **[Управлении памятью в MariaDB](memory_management.md)**.
6. **Версионный контроль:** Движки имеют разные ограничения по версиям. Перед апгрейдом проверяйте changelog на предмет удаленных параметров и измененного поведения.
7. **Резервное копирование:** Для MyRocks используйте `mariadb-backup`. Для S3-engine резервное копирование не требуется (объектное хранилище само по себе реплицировано). Подробнее см. в **[Резервном копировании MariaDB](backup_and_recovery.md)**.
8. **Мониторинг:** Включите специфичные для движка метрики. Подробнее см. в **[Мониторинге MariaDB](monitoring.md)**.

## Особенности и ограничения (Edge Cases)

- **Galera и MyRocks:** Galera Cluster несовместим с MyRocks на уровне транзакций. Используйте только InnoDB.
- **Galera и Aria:** Экспериментальная поддержка начиная с 10.6. Для системных таблиц используется Aria, но пользовательские таблицы должны быть InnoDB.
- **MyRocks: ограничения:** Нет поддержки Foreign Keys, пространственных индексов, полнотекстового поиска, SERIALIZABLE, Transportable Tablespace.
- **Memory Engine:** Данные теряются при перезагрузке. Подходит только для временных таблиц и кешей. Не используйте для persistентных данных.
- **S3 Engine:** Только для чтения после загрузки. Подходит для архивов, которые редко меняются. Не подходит для OLTP.
- **Online DDL:** `ALTER TABLE ... ENGINE=...` создает временную копию таблицы и требует свободного пространства (до 1.5x от размера таблицы). Для таблиц > 100GB используйте `pt-online-schema-change`.
- **Контейнеры:** В Docker/Kubernetes `innodb_buffer_pool_size` должен быть меньше лимита контейнера минимум на 1-2GB. Для MyRocks учитывайте `rocksdb_block_cache_size` в общем лимите памяти.
- **Переход с MySQL:** Физическая миграция таблиц MyRocks из MySQL в MariaDB невозможна. Требуется логическая миграция через `mariadb-dump`.
- **Удаление Change Buffer:** При апгрейде с версий < 11.0 параметр `innodb_change_buffering` игнорируется. Удалите его из `my.cnf` для чистоты конфигурации.

## Дополнительная информация

### Сводная таблица характеристик (12.3 LTS)

| Движок | ACID | Индексация | Основной фокус | Масштабируемость |
| :--- | :---: | :--- | :--- | :--- |
| **InnoDB** | Да | B+Tree | Транзакции, Универсальность | Высокая (Thread Pool) |
| **Aria** | Crash-safe | B+Tree | Системные и временные задачи | Сегментированный кэш |
| **MyRocks** | Да | LSM-Tree | Сжатие, интенсивная запись | Отличная на SSD |
| **ColumnStore** | Да | Columnar | Аналитика (OLAP), Big Data | Распределенная (MPP) |
| **Spider** | XA | Remote | Шардинг, Масштабирование | Горизонтальная |
| **S3** | Нет | Aria-based | Холодный архив | Объектное хранилище |
| **Memory** | Нет | Hash, B-Tree | Временные данные | Сверхвысокая скорость |
| **Mroonga** | Нет | Inverted | Полнотекстовый поиск | Лингвистический анализ |
| **Connect** | Нет | Variable | Интеграция данных (ETL) | Зависит от источника |

### См. также
- **[Обзор MariaDB](overview.md)** — общая архитектура и стратегия развития.
- **[Управление памятью в MariaDB](memory_management.md)** — расчёт буферов, диагностика утечек, тюнинг MyRocks Block Cache.
- **[Конфигурация MariaDB](configuration.md)** — параметры движков в `my.cnf`.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup` и `mariadb-dump`.
- **[Мониторинг MariaDB](monitoring.md)** — метрики движков через Prometheus.
- **[Отказоустойчивость MariaDB](high_availability.md)** — ограничения Galera по движкам.
- **[Миграция MySQL -> MariaDB](./Operations/migration_mysql_to_mariadb.md)** — особенности перехода.

### Внешние ресурсы
- [MariaDB Storage Engines](https://mariadb.com/docs/server/server-usage/storage-engines/)
- [MariaDB 12.3 Release Notes](https://mariadb.com/docs/release-notes/community-server/12.3/)
- [MariaDB Server System Variables](https://mariadb.com/docs/server/server-system-variables/)
