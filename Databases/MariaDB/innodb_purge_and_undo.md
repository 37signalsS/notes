# InnoDB Purge и Undo Log в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **Purge (очистка)** — фоновый процесс InnoDB, удаляющий устаревшие версии строк и delete-marked записи из undo log и индексов. Часть MVCC: старые версии строк хранятся до тех пор, пока хотя бы одна транзакция может их прочитать.
*   **Undo Log** — журнал обратных изменений: хранит старые версии строк для MVCC (чтение согласованных данных) и отката транзакций (ROLLBACK). Хранится в undo tablespace (файлы `undo_001`, `undo_002`, ...) или в системном tablespace.
*   **History List Length (HLL)** — количество undo log записей, ожидающих purge. Ключевая метрика здоровья purge. Растёт при интенсивной записи или долгих транзакциях. Смотрится в `SHOW ENGINE INNODB STATUS` (секция `TRANSACTIONS`).
*   **Purge Threads** — фоновые потоки, выполняющие garbage collection undo log и delete-marked индексных записей. Количество: `innodb_purge_threads`.
*   **Purge Lag** — отставание purge от записи. При превышении `innodb_max_purge_lag` InnoDB начинает замедлять DML (INSERT/UPDATE/DELETE), чтобы purge успевал.
*   **Undo Log Truncation** — усечение (truncate) целого undo tablespace, а не удаление отдельных записей. Включается `innodb_undo_log_truncate`.
*   **`innodb_purge_batch_size`** — количество undo log страниц, обрабатываемых purge за одну итерацию (по умолчанию 300).

## Базовые концепции

### Как работает purge

```
UPDATE/DELETE строки
  ↓
Старая версия записывается в undo log
Старая индексная запись delete-marked
  ↓
COMMIT
  ↓
Purge threads сканируют undo log:
  - если ни одна активная транзакция не нуждается в старой версии
  - удаляют undo log запись и delete-marked индексную запись
  ↓
History list length уменьшается
```

**Ключевой момент:** purge не может удалить версию, пока хотя бы одна транзакция (с более ранним read view) может её прочитать. Долгие транзакции (даже read-only) блокируют purge.

### Purge threads

*   **`innodb_purge_threads`** — количество purge threads. По умолчанию: 1 (если ≤ 16 логических процессоров), иначе 4. Максимум 32.
*   **Динамическое изменение:** `SET GLOBAL innodb_purge_threads = 8;` (требует SUPER).
*   **Рекомендация:** при DML, распределённом по многим таблицам — больше purge threads; при DML на нескольких таблицах — меньше (чтобы избежать конкуренции).

### Purge lag и throttling

*   **`innodb_max_purge_lag`** — максимальное количество undo log записей в history list. При превышении — задержка DML. По умолчанию 0 (отключено).
*   **Формула задержки:** `(purge_lag / innodb_max_purge_lag - 0.9995) * 10000` микросекунд на каждую DML-операцию.
*   **`innodb_max_purge_lag_delay`** — максимальная задержка в микросекундах (ограничение throttling).
*   **Типичное значение `innodb_max_purge_lag`:** 1000000 (1M), при условии маленьких транзакций (~100 байт) и допустимых 100 MB непрочищенных строк.

### Undo log truncation

*   **`innodb_undo_log_truncate`** — включает усечение undo tablespace (ON/OFF). По умолчанию OFF.
*   **`innodb_max_undo_log_size`** — порог размера undo tablespace для truncation (по умолчанию 1 GB).
*   **`innodb_purge_rseg_truncate_frequency`** — частота проверки undo tablespace для truncation (по умолчанию 128).
*   **`innodb_undo_tablespaces`** — количество undo tablespaces (по умолчанию 2, минимум 2).
*   **`innodb_undo_directory`** — каталог для undo tablespaces.

**Важно:** truncation работает только при `innodb_undo_log_truncate = ON` и `innodb_undo_tablespaces ≥ 2`.

## Практические сценарии

### 1. Проверка состояния purge

```sql
-- History list length (в SHOW ENGINE INNODB STATUS)
SHOW ENGINE INNODB STATUS\G
-- Секция TRANSACTIONS:
-- Trx id counter 0 290328385
-- Purge done for trx's n:o < 0 290315608 undo n:o < 0 17
-- History list length 20

-- Переменные
SHOW VARIABLES LIKE 'innodb_purge%';
SHOW VARIABLES LIKE 'innodb_max_purge_lag%';
SHOW VARIABLES LIKE 'innodb_undo%';

-- Undo log размер
SELECT * FROM information_schema.INNODB_TABLESPACES
  WHERE NAME LIKE '%undo%';
```

```bash
# Размер undo tablespace на диске
ls -lh /var/lib/mysql/undo_00*
du -sh /var/lib/mysql/undo_00*
```

**Норма:** `History list length` обычно < нескольких тысяч. Постоянный рост — сигнал проблемы.

### 2. Настройка purge threads

```ini
[mariadb]
# Количество purge threads (по умолчанию 1 или 4)
innodb_purge_threads = 4

# Размер batch (продвинутая настройка)
innodb_purge_batch_size = 300
```

```sql
-- Динамическое изменение
SET GLOBAL innodb_purge_threads = 8;
```

### 3. Настройка purge lag throttling

```ini
[mariadb]
# Максимальный purge lag (0 = отключено)
innodb_max_purge_lag = 1000000

# Максимальная задержка DML (мкс)
innodb_max_purge_lag_delay = 100000
```

```sql
SET GLOBAL innodb_max_purge_lag = 1000000;
SET GLOBAL innodb_max_purge_lag_delay = 100000;
```

### 4. Undo log truncation

```ini
[mariadb]
# Включить truncation undo tablespace
innodb_undo_log_truncate = ON

# Порог размера для truncation (по умолчанию 1G)
innodb_max_undo_log_size = 1G

# Количество undo tablespaces (минимум 2)
innodb_undo_tablespaces = 2

# Каталог undo tablespaces (опционально)
# innodb_undo_directory = /var/lib/mysql
```

```sql
SET GLOBAL innodb_undo_log_truncate = ON;
SET GLOBAL innodb_max_undo_log_size = 1073741824;  -- 1 GB
```

**Валидация:** после включения truncation размер undo tablespace должен автоматически уменьшаться при превышении `innodb_max_undo_log_size`.

### 5. Поиск долгих транзакций (блокируют purge)

```sql
-- Активные транзакции
SELECT * FROM information_schema.INNODB_TRX
ORDER BY trx_started;

-- Долгие транзакции (> 60 сек)
SELECT trx_id, trx_started, trx_state, trx_rows_modified,
  TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS duration_sec
FROM information_schema.INNODB_TRX
WHERE TIMESTAMPDIFF(SECOND, trx_started, NOW()) > 60;

-- Через sys schema
SELECT * FROM sys.innodb_lock_waits;
```

## Устранение неполадок (Troubleshooting)

### History list length постоянно растёт

*   **Причина:** purge не успевает за записью (мало purge threads, медленный диск), или долгие транзакции блокируют purge.
*   **Диагностика:** `SHOW ENGINE INNODB STATUS` — History list length растёт; `INNODB_TRX` — долгие транзакции.
*   **Решение:**
    1.  Увеличьте `innodb_purge_threads`.
    2.  Найдите и завершите долгие транзакции (даже read-only).
    3.  Ускорьте диск (undo log I/O).
    4.  Включите `innodb_max_purge_lag` для throttling DML.

### Undo tablespace занимает много места

*   **Причина:** много незакоммиченных или долгих транзакций; truncation отключён.
*   **Диагностика:** `du -sh /var/lib/mysql/undo_00*` — большой размер.
*   **Решение:** включите `innodb_undo_log_truncate = ON`; найдите долгие транзакции; увеличьте `innodb_purge_threads`.

### DML замедлился (throttling)

*   **Причина:** `innodb_max_purge_lag` превышен — InnoDB замедляет DML.
*   **Диагностика:** `SHOW ENGINE INNODB STATUS` — History list length > `innodb_max_purge_lag`.
*   **Решение:** увеличьте `innodb_purge_threads`; найдите долгие транзакции; увеличьте `innodb_max_purge_lag` (если допустимо больше непрочищенных данных).

### Purge не сокращает undo после DELETE

*   **Причина:** есть активная транзакция с read view, которому нужны старые версии.
*   **Решение:** дождитесь завершения долгих транзакций; purge выполнится автоматически.

## Лучшие практики (Best Practices)

1.  **Мониторьте History list length** — алерт при постоянном росте.
2.  **Избегайте долгих транзакций** — они блокируют purge (даже read-only).
3.  **`innodb_purge_threads`:** увеличивайте при write-нагрузке, распределённой по многим таблицам.
4.  **Включите `innodb_undo_log_truncate`** для автоматического управления размером undo.
5.  **`innodb_max_purge_lag`:** настройте throttling для защиты от отставания purge.
6.  **Undo tablespace на быстром диске** — purge чувствителен к I/O latency.

## Дополнительная информация

### См. также

*   **[InnoDB: настройка производительности](innodb_durability_tuning.md)** — буферы и I/O.
*   **[Транзакции и блокировки](transactions_and_locking.md)** — MVCC, long transactions.
*   **[MySQL: Undo Logs и Purge](../MySQL/undo_logs_and_purge.md)** — MySQL-специфичные детали.
*   **[Мониторинг](monitoring.md)** — метрики InnoDB.

### Внешние ресурсы

*   [MariaDB InnoDB Purge](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-purge)
*   [MariaDB Configure InnoDB Purge Threads](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/mariadb-enterprise-server-innodb-operations/configure-the-innodb-purge-threads)
*   [MariaDB InnoDB System Variables](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables)
*   [MariaDB Undo Tablespaces](https://mariadb.com/kb/en/undo-tablespaces/)
