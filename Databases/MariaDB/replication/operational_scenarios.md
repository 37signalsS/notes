# Операционные сценарии репликации MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Большая транзакция** — транзакция, изменяющая большой объём данных (обычно > 1 ГБ или > 1 млн строк). Вызывает лаг и таймауты на реплике.
*   **Батчинг (batching)** — разбиение большой операции на мелкие транзакции для снижения лага репликации.
*   **Online DDL** — изменение схемы без длительной блокировки (`ALGORITHM=INPLACE`, `ALGORITHM=INSTANT`).
*   **`pt-online-schema-change` / `gh-ost`** — внешние инструменты для безопасного изменения схемы больших таблиц.
*   **`slave_compressed_protocol`** — сжатие репликационного трафика для WAN.
*   **`auto_increment_increment` / `auto_increment_offset`** — параметры для уникальности AUTO_INCREMENT в multi-master.

## Базовые концепции

### Большие транзакции и батчинг

Проблема: одна транзакция на 10 млн строк:
*   Занимает весь relay log до применения.
*   SQL-поток применяет её целиком — блокирует параллельную репликацию.
*   При сбое — повторное применение всей транзакции.

**Решение: батчинг**
```sql
-- Плохо: одна транзакция
DELETE FROM big_table WHERE created_at < '2024-01-01';

-- Хорошо: батчи по 10000 строк
DELETE FROM big_table WHERE created_at < '2024-01-01' LIMIT 10000;
-- повторять в цикле с COMMIT после каждого батча
```

```bash
# Через pt-archiver (Percona Toolkit)
pt-archiver \
    --source h=source_ip,D=app_db,t=big_table \
    --where "created_at < '2024-01-01'" \
    --limit 10000 \
    --txn-size 10000 \
    --purge
```

**Параметры для больших транзакций:**
*   `max_allowed_packet` — увеличьте при больших INSERT/UPDATE.
*   `slave_net_timeout` — увеличьте при медленной сети.
*   `slave_parallel_threads` — параллельное применение.

### DDL на репликах

**Правило:** DDL выполняется **только на источнике** и реплицируется на реплики. Ручной DDL на реплике прерывает репликацию при применении того же DDL с источника.

**Online DDL (встроенный):**
```sql
-- INSTANT (MariaDB 10.3+): мгновенно, без копирования
ALTER TABLE big_table ADD COLUMN new_col INT DEFAULT 0, ALGORITHM=INSTANT;

-- INPLACE: без блокировки записи (для поддерживаемых операций)
ALTER TABLE big_table ADD INDEX idx_email (email), ALGORITHM=INPLACE, LOCK=NONE;

-- COPY: блокирует запись (избегайте на больших таблицах)
ALTER TABLE big_table ENGINE=InnoDB, ALGORITHM=COPY;
```

**Внешние инструменты (для таблиц > 100 ГБ):**
```bash
# pt-online-schema-change
pt-online-schema-change \
    --alter "ADD COLUMN new_col INT DEFAULT 0" \
    --execute \
    D=app_db,t=big_table \
    --max-lag 5 \
    --chunk-size 1000

# gh-ost (через binlog, без триггеров)
gh-ost \
    --user=gh-ost_user --password=*** --host=source_ip \
    --database=app_db --table=big_table \
    --alter="ADD COLUMN new_col INT DEFAULT 0" \
    --max-lag-millis=1500 \
    --execute
```

> **Примечание:** `gh-ost` требует `binlog_format = ROW`. `pt-online-schema-change` использует триггеры — не применим к таблицам с существующими триггерами.

### WAN-репликация (удалённые реплики)

```ini
# На реплике
[mariadb]
slave_compressed_protocol = ON   # сжатие трафика
slave_net_timeout = 60           # таймаут при медленной сети
net_read_timeout = 30
net_write_timeout = 60
```

**Рекомендации:**
*   Сжатие снижает bandwidth в 2–5× при текстовых данных.
*   При RTT > 100 мс — увеличьте таймауты.
*   Для межрегиональных сценариев — полусинхронная внутри региона, асинхронная между регионами.

### AUTO_INCREMENT в multi-master

```ini
# Узел A
auto_increment_increment = 2
auto_increment_offset = 1   # 1, 3, 5, 7, ...

# Узел B
auto_increment_increment = 2
auto_increment_offset = 2   # 2, 4, 6, 8, ...
```

> **Примечание:** при изменении требуется перезапуск или закрытие всех соединений. В Galera управляется автоматически (`wsrep_auto_increment_control`). Подробнее: **[Топологии](./topologies.md)**.

## Практические сценарии

### Сценарий 1: Батчинг большого DELETE

```sql
-- Цикл батчинга (выполнять повторно, пока не вернёт 0)
DELETE FROM big_table WHERE created_at < '2024-01-01' LIMIT 10000;
-- → Query OK, 10000 rows affected

-- Проверка лага между батчами
SHOW REPLICA STATUS\G
-- Seconds_Behind_Source: 0
```

### Сценарий 2: Online DDL на большой таблице

```sql
-- Проверка поддерживаемого алгоритма
ALTER TABLE big_table ADD COLUMN new_col INT DEFAULT 0, ALGORITHM=INPLACE;
-- → ERROR 1846 (0A000): ALGORITHM=INPLACE is not supported...
-- → Используйте pt-online-schema-change или gh-ost

-- INSTANT (если поддерживается)
ALTER TABLE big_table ADD COLUMN new_col INT DEFAULT 0, ALGORITHM=INSTANT;
-- → Query OK
```

### Сценарий 3: WAN-репликация с сжатием

```ini
# На реплике
[mariadb]
slave_compressed_protocol = ON
slave_net_timeout = 120
```

```sql
-- Проверка
SHOW VARIABLES LIKE 'slave_compressed_protocol';
-- → ON
```

### Сценарий 4: Мониторинг больших транзакций

```sql
-- Текущие длительные транзакции
SELECT * FROM information_schema.innodb_trx
WHERE trx_started < NOW() - INTERVAL 60 SECOND;

-- Размер binlog на транзакцию (через Performance Schema)
SELECT * FROM performance_schema.events_transactions_summary_by_digest
ORDER BY SUM_BYTES_WRITTEN DESC LIMIT 10;
```

### Сценарий 5: Увеличение max_allowed_packet

```ini
# На источнике и реплике
[mariadb]
max_allowed_packet = 256M
```

```sql
-- Проверка
SHOW VARIABLES LIKE 'max_allowed_packet';
-- → 268435456
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Лаг репликации при большом DELETE | Одна большая транзакция | Батчинг (`LIMIT` + цикл) или `pt-archiver` |
| `Error 1153: Got a packet bigger than` | `max_allowed_packet` мал | Увеличьте `max_allowed_packet` на обоих узлах |
| DDL прерывает репликацию | Ручной DDL на реплике | DDL только на источнике; используйте Online DDL |
| `ALGORITHM=INPLACE` не поддерживается | Операция требует COPY | Используйте `pt-online-schema-change` / `gh-ost` |
| WAN-репликация отстаёт | Недостаточно bandwidth / RTT | Включите `slave_compressed_protocol`; увеличьте таймауты |
| Дублирование AUTO_INCREMENT | Не настроены increment/offset | Настройте `auto_increment_increment`/`offset` |

## Best Practices

1.  **Батчинг** — никогда не выполняйте массовые операции одной транзакцией.
2.  **Online DDL** — `ALGORITHM=INSTANT`/`INPLACE` по умолчанию; `pt-osc`/`gh-ost` для больших таблиц.
3.  **DDL только на источнике** — ручной DDL на реплике ломает репликацию.
4.  **Сжатие** — `slave_compressed_protocol = ON` для WAN.
5.  **`max_allowed_packet`** — увеличьте при больших BLOB/批量操作.
6.  **Мониторьте длительные транзакции** — через `innodb_trx`.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — параллельная репликация.
- **[Топологии](./topologies.md)** — multi-master, auto_increment.
- **[Online Schema Change MySQL](../../MySQL/Operations/online-schema-change.md)** — pt-osc/gh-ost детально.
- **[Хранимые объекты](../Concepts/stored_objects_management.md)** — триггеры, события, DISABLE ON SLAVE.
- **[Документация MariaDB: Online DDL](https://mariadb.com/docs/server/sql-reference/ddl)**
