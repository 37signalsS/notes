# Движки хранения в MariaDB

## Определения

**Движок хранения (Storage Engine)** — это программный модуль СУБД, отвечающий за низкоуровневые операции с данными: физическое хранение на диске, индексацию, управление блокировками и обеспечение транзакционности. В MariaDB используется подключаемая архитектура (**Pluggable Storage Engine API**), позволяющая выбирать движок индивидуально для каждой таблицы.

**LSM-дерево (Log-Structured Merge-tree)** — структура данных, оптимизированная для записи, используемая в движке MyRocks. Она преобразует случайную запись в последовательную, буферизуя данные в памяти и периодически сбрасывая их на диск (SST-файлы) с последующим фоновым уплотнением (compaction).

**MPP (Massively Parallel Processing)** — архитектура, применяемая в ColumnStore, где аналитический запрос распределяется между несколькими вычислительными узлами (Performance Modules), каждый из которых обрабатывает свою часть данных параллельно.

## Основные концепции

### Актуальное состояние и инновации (LTS 12.3)

Версия MariaDB 12.3 LTS (2026 год) является ключевым этапом оптимизации под SSD/NVMe и AI-нагрузки.

1.  **Интеграция Binary Log в InnoDB (Atomic Log):**
    - Параметр: `binlog_storage_engine=innodb`.
    - Суть: События бинарного лога пишутся непосредственно в страницы InnoDB. Это устраняет необходимость в дорогостоящей синхронизации между БД и файловой системой лога, ускоряя транзакции до 4 раз.
2.  **Нативный векторный поиск (Vector Search):**
    - Поддержка типа `VECTOR` и индексов **mHNSW**. Индекс адаптирован для многопоточного построения и высокой скорости поиска в задачах RAG (Retrieval-Augmented Generation).
3.  **Оптимизация Aria:**
    - Введение сегментированного кеша ключей (`aria_pagecache_segments`), что устраняет конкуренцию за блокировки на процессорах с 64+ ядрами.
4.  **Удаление Change Buffer:**
    - Полное удаление механизма `innodb_change_buffering` (начиная с 11.0). MariaDB теперь напрямую пишет в страницы индексов, что эффективнее на NVMe-дисках.

### Основные движки (Core Engines)

**InnoDB:** Универсальный транзакционный движок по умолчанию.
- **Особенности:** Полная поддержка ACID, внешние ключи, MVCC (Multi-Version Concurrency Control).
- **Производительность:** В 12.3 LTS включена опция `innodb_snapshot_isolation=ON` для повышения согласованности. Поддерживает аппаратное ускорение SIMD для векторных операций.

**Aria:** Усовершенствованная crash-safe замена MyISAM.
- **Назначение:** Используется для системных таблиц MariaDB и сложных временных таблиц.
- **Преимущества:** Быстрое восстановление после сбоя через логи транзакций без накладных расходов на полную MVCC-изоляцию.

**MyRocks:** Движок на базе LSM-дерева (RocksDB).
- **Преимущества:** Экстремальное сжатие данных (в 3-4 раза лучше InnoDB) и минимизация износа SSD (Write Amplification).
- **SRE-тюнинг (LSM):**
    - **Compaction:** По умолчанию используется *Leveled Compaction*. Для снижения Write Amplification рекомендуется `level_compaction_dynamic_level_bytes=ON`.
    - **Потоки:** Параметр `rocksdb_max_background_jobs` должен быть ~ `CPU_cores / 2` для предотвращения остановки записи (Write Stalls).
    - **Мониторинг:** Ключевые метрики — `Write Amp` (цель < 20) и `Compaction Lag`.

**ColumnStore:** Колоночный движок для распределенной аналитики (OLAP).
- **Архитектура MPP (Massively Parallel Processing):**
    - **User Module (UM):** SQL-слой, агрегация данных, управление метаданными.
    - **Performance Module (PM):** Операции ввода-вывода, вычисления над экстентами.
- **Эксплуатация:**
    - **Загрузка данных:** Утилита `cpimport` работает напрямую с PM, минуя SQL-слой (быстрее в 100 раз). Режим `-m 2` обеспечивает параллельную загрузку на все PM-узлы.
    - **Блокировки:** `cpimport` накладывает Write Metadata Lock (MDL).

**Spider:** Движок для прозрачного шардирования.
- **Функция:** Распределяет данные одной таблицы между несколькими удаленными узлами MariaDB.
- **Распределенные транзакции:**
    - Поддержка **XA (2PC)** для обеспечения атомарности между шардами. Рекомендуется `spider_sync_trx_isolation=1` для согласованности уровней изоляции.
- **Отказоустойчивость:** Мониторинг бэкенд-узлов через таблицу `mysql.link_mon_servers` и `monitoring_bg_kind=1`.

### Вспомогательные и специализированные движки

**S3:** Движок для холодного облачного хранения.
- **Функция:** Перенос архивных таблиц в S3-совместимые хранилища (AWS, MinIO, Google Cloud).
- **Особенности:** Таблицы только для чтения, поддержка сжатия zlib. Позволяет нескольким инстансам MariaDB видеть один набор архивных данных.

**Archive:** Максимальное сжатие для логов без индексов.
- **Особенности:** Поддерживает только `INSERT` и `SELECT`. Данные сжимаются «на лету» через zlib.

**Memory:** Сверхвысокая скорость в оперативной памяти.
- **Особенности:** Данные теряются при перезагрузке. Используется для кешей и промежуточных вычислений.

**Sequence:** Виртуальный генератор числовых последовательностей.
- **Сценарии:** Генерация рядов чисел/дат без создания физических данных (заменяет сложные рекурсивные CTE).

**Connect:** Интеграция с внешними данными (ETL).
- **Функция:** Доступ к CSV, JSON, Excel, XML, а также другим БД (Oracle, PostgreSQL, MSSQL через JDBC/ODBC) как к локальным таблицам.

**Mroonga:** Полнотекстовый поиск на базе Groonga.
- **Особенности:** Быстрый поиск с поддержкой лингвистического анализа и CJK-языков.

**OQGRAPH:** Графовый движок.
- **Функция:** Выполнение графовых алгоритмов (кратчайший путь, поиск в глубину) над реляционными таблицами через SQL.

## Практические сценарии

### Мониторинг и диагностика

```sql
-- 1. Проверка эффективности Buffer Pool в InnoDB
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read%';
-- Hit Rate = Innodb_buffer_pool_read_requests / (Innodb_buffer_pool_reads + 1)
-- Рекомендуемое значение > 99%.

-- 2. Диагностика MyRocks (Compaction Lag)
SHOW ENGINE ROCKSDB STATUS; -- Ищите 'Cumulative compaction stats'

-- 3. Мониторинг Spider (XA-транзакции)
SHOW ENGINE SPIDER STATUS; -- Проверка XA_recover_prepares и активных соединений

-- 4. Диагностика ColumnStore (состояние экстентов)
-- Выполняется в шелле Performance Module
-- edg -view
-- calGetStats 1 1 -- детальная статистика по операциям ввода-вывода
```

### Сводная таблица SRE-метрик

| Движок | Ключевая метрика | Инструмент мониторинга |
| :--- | :--- | :--- |
| **ColumnStore** | `Extent Map` fragmentation | `edg` utility / `calGetStats` |
| **Spider** | `XA_recover_prepares` | `SHOW ENGINE SPIDER STATUS` |
| **MyRocks** | `Write Stalls` / `Write Amp` | `SHOW ENGINE ROCKSDB STATUS` |
| **InnoDB** | `Buffer Pool Hit Rate` | `SHOW GLOBAL STATUS` |

### Настройка векторного индекса (MariaDB 12.3 LTS)

```sql
CREATE TABLE ai_memory (
    id INT PRIMARY KEY AUTO_INCREMENT,
    content TEXT,
    embedding VECTOR(1536) NOT NULL,
    -- Создание индекса mHNSW с косинусным сходством
    VECTOR INDEX (embedding) DISTANCE=cosine
) ENGINE=InnoDB;

-- Поиск 5 наиболее релевантных ответов
SELECT content FROM ai_memory 
ORDER BY VEC_DISTANCE_COSINE(embedding, [0.1, -0.2, ...]) 
LIMIT 5;
```

### Архивация и шардирование

```sql
-- Перевод таблицы на S3
ALTER TABLE log_2024 ENGINE=S3 BUCKET='db-archives';

-- Настройка шардирования через Spider
CREATE SERVER 'node1' FOREIGN DATA WRAPPER mysql OPTIONS (HOST '192.168.1.100', DATABASE 'shards');
CREATE TABLE partitioned_table (id INT, val TEXT) 
ENGINE=Spider COMMENT='wrapper "node1", table "remote_table"';
```

### Генерация последовательностей и Полнотекстовый поиск

```sql
-- Список дат за последние 7 дней
SELECT CURDATE() - INTERVAL seq DAY as day FROM seq_0_to_6;

-- Полнотекстовый поиск Mroonga
CREATE TABLE articles (id INT PRIMARY KEY, txt TEXT, FULLTEXT INDEX(txt)) ENGINE=Mroonga;
SELECT * FROM articles WHERE MATCH(txt) AGAINST('DevOps' IN BOOLEAN MODE);
```

## Диагностика неисправностей (Troubleshooting)

### InnoDB: Взаимоблокировки (Deadlocks)
- **Проблема:** Транзакции отменяются с кодом `Deadlock found`.
- **Диагностика:** `SHOW ENGINE INNODB STATUS` -> секция `LATEST DETECTED DEADLOCK`.
- **Решение:** Проверьте индексы и обеспечьте одинаковый порядок доступа к строкам во всех частях приложения.

### MyRocks: Write Stalls
- **Проблема:** Резкое падение скорости записи.
- **Причина:** MyRocks не успевает уплотнять уровни (Compaction).
- **Решение:** Увеличьте `rocksdb_max_background_compactions` и проверьте лимиты IOPS на дисках.

## Дополнительная информация

### Сравнение характеристик (12.3 LTS)

| Движок | ACID | Индексация | Основной фокус | Масштабируемость |
| :--- | :---: | :--- | :--- | :--- |
| **InnoDB** | Да | B+Tree, mHNSW | Транзакции, Универсальность | Высокая (Thread Pool) |
| **Aria** | Crash-safe | B+Tree | Системные и временные задачи | Сегментированный кэш |
| **MyRocks** | Да | LSM-Tree | Сжатие, интенсивная запись | Отличная на SSD |
| **ColumnStore** | Да | Columnar | Аналитика (OLAP), Big Data | Распределенная (MPP) |
| **Spider** | XA | Remote | Шардинг, Масштабирование | Горизонтальная |
| **S3** | Нет | Aria-based | Холодный архив | Облачная |
| **Memory** | Нет | Hash, B-Tree | Временные данные | Сверхвысокая скорость |
| **Mroonga** | Нет | Inverted | Полнотекстовый поиск | Лингвистический анализ |
| **Connect** | Нет | Variable | Интеграция данных (ETL) | Зависит от источника |

### См. также
- **[Обзор MariaDB](overview.md)** — общая архитектура.
- **[Отказоустойчивость MariaDB](high_availability.md)** — Galera, Orchestrator и MaxScale.
- **[Конфигурация MariaDB](configuration.md)** — тюнинг параметров движков.
- **[ACID в базах данных](../Concepts/acid.md)** — теоретические основы надежности.
- **[Официальная база знаний (Storage Engines)](https://mariadb.com/kb/en/storage-engines/)**
