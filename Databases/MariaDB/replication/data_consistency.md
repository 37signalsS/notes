# Проверка консистентности репликации MariaDB (pt-table-checksum / pt-table-sync)

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS, Percona Toolkit 3.x

## Определения

*   **Репликационная консистентность (data consistency)** — соответствие данных между источником и репликой. При нормальной асинхронной репликации данные **должны** совпадать, но на практике возможны расхождения (ошибки применения, человеческие действия, некорректный `slave_skip_errors`, сбои, фильтрация).
*   **`pt-table-checksum`** — утилита Percona Toolkit для обнаружения расхождений между источником и репликой. Вычисляет контрольные суммы по chunk'ам таблиц и записывает результаты в служебную таблицу (`--replicate`).
*   **`pt-table-sync`** — утилита Percona Toolkit для генерации/применения SQL для синхронизации расхождений (can repair). Требует **крайней осторожности** в production.
*   **Chunk** — порция строк таблицы, обрабатываемая `pt-table-checksum` за один запрос. Размер адаптируется под нагрузку (`--chunk-size`).

## Базовые концепции

### Как работает pt-table-checksum

1.  На источнике утилита разбивает каждую таблицу на chunk'и (по диапазону первичного ключа).
2.  Для каждого chunk'а вычисляется `CRC32` контрольная сумма и записывается в таблицу `--replicate` (например, `percona.checksums`) на источнике.
3.  Запись реплицируется на реплику.
4.  На реплике утилита (или тот же запуск через `DSN`) вычисляет контрольную сумму для того же chunk'а и сравнивает с реплицированной.
5.  Расхождения выводятся в отчёт.

**Важно:** `pt-table-checksum` работает **на источнике**, но сравнивает данные через репликацию. Реплика должна быть подключена и реплицировать таблицу `percona.checksums`.

### Когда проверять консистентность

*   Регулярно (еженедельно/ежемесячно) — как часть SRE-практик.
*   После восстановления из сбоев (relay log corruption, GTID skip).
*   После изменения фильтров репликации.
*   После ручных исправлений на реплике.
*   При подозрении на расхождения (ошибки 1032/1062 в логах).

### pt-table-sync: стратегии синхронизации

*   `--print` — вывести SQL без выполнения (безопасный режим).
*   `--execute` — выполнить SQL на реплике.
*   `--sync-to-master` — синхронизировать реплику с мастером (автоопределение мастера).
*   `--replicate` — использовать таблицу контрольных сумм для определения расхождений.

**Предупреждение:** `pt-table-sync` применяет `REPLACE INTO` / `DELETE` / `INSERT` на реплике. Это **перезаписывает** данные. Всегда начинайте с `--print` и проверяйте SQL.

### Ограничения

*   Таблицы без первичного ключа или уникального индекса — `pt-table-checksum` не может разбить на chunk'и (обрабатывает всю таблицу целиком, медленно).
*   Проверка нагружает источник (чтение всех строк). Запускайте в периоды низкой нагрузки.
*   `pt-table-sync` не решает структурные расхождения (разные схемы) — только данные.

## Практические сценарии

### Сценарий 1: Проверка консистентности (pt-table-checksum)

```bash
# На источнике (утилита реплицирует результаты на реплику)
pt-table-checksum \
    --replicate=percona.checksums \
    --host=source_ip \
    --user=monitor_user \
    --password=monitor_password \
    --databases=app_db \
    --chunk-size=1000 \
    --max-load=Threads_running=25 \
    --critical-load=Threads_running=50
```

**Параметры:**
*   `--replicate` — таблица для хранения контрольных сумм (создаётся автоматически).
*   `--databases` — ограничить проверку конкретными БД.
*   `--chunk-size` — начальный размер chunk'а (адаптируется автоматически).
*   `--max-load` — приостановить при превышении нагрузки.
*   `--critical-load` — прекратить при критической нагрузке.

**Ожидаемый вывод:**
```
TS ERRORS  DIFFS  ROWS  CHUNKS SKIPPED    TIME TABLE
... 0      0      0   12345       0    12.345 app_db.users
```
*   `DIFFS = 0` — расхождений нет.
*   `DIFFS > 0` — есть расхождения (см. Сценарий 3).

### Сценарий 2: Проверка конкретной таблицы

```bash
pt-table-checksum \
    --replicate=percona.checksums \
    --host=source_ip \
    --user=monitor_user \
    --password=*** \
    --databases=app_db \
    --tables=orders,order_items
```

### Сценарий 3: Обнаружение расхождений — анализ

```sql
-- На источнике: какие chunk'и расходятся
SELECT db, tbl, chunk, this_cnt, master_cnt, this_crc, master_crc
FROM percona.checksums
WHERE this_cnt <> master_cnt OR this_crc <> master_crc;

-- Или через pt-table-checksum с --replicate-check-only
pt-table-checksum \
    --replicate=percona.checksums \
    --replicate-check-only \
    --host=source_ip \
    --user=monitor_user \
    --password=***
```

### Сценарий 4: Синхронизация расхождений (pt-table-sync) — БЕЗОПАСНЫЙ РЕЖИМ

```bash
# Шаг 1: вывести SQL без выполнения (ВСЕГДА начинайте с этого)
pt-table-sync \
    --replicate=percona.checksums \
    --print \
    --host=replica_ip \
    --user=monitor_user \
    --password=*** \
    --sync-to-master

# Шаг 2: проверьте выводимый SQL
# REPLACE INTO `app_db`.`users`(...) VALUES(...)
# DELETE FROM `app_db`.`users` WHERE ...

# Шаг 3: только после проверки — выполнить
pt-table-sync \
    --replicate=percona.checksums \
    --execute \
    --host=replica_ip \
    --user=monitor_user \
    --password=*** \
    --sync-to-master
```

> **Предупреждение:** `pt-table-sync --execute` применяет изменения на реплике. Убедитесь, что:
> 1.  Репликация работает (`Replica_IO_Running: Yes`, `Replica_SQL_Running: Yes`).
> 2.  Расхождения действительно на реплике, а не на источнике.
> 3.  У вас есть бэкап.

### Сценарий 5: Регулярная проверка через cron

```bash
# /etc/cron.weekly/mariadb-consistency-check
#!/bin/bash
pt-table-checksum \
    --replicate=percona.checksums \
    --host=source_ip \
    --user=monitor_user \
    --password=*** \
    --replicate-check-only \
    --quiet
if [ $? -ne 0 ]; then
    echo "Replication inconsistency detected!" | mail -s "MariaDB Alert" sre@example.com
fi
```

## Валидация

```sql
-- После pt-table-checksum: проверьте таблицу контрольных сумм
SELECT COUNT(*) FROM percona.checksums;
-- → количество chunk'ов

-- Проверьте, что реплика получила таблицу checksums
SHOW REPLICA STATUS\G
-- Seconds_Behind_Source: 0

-- После pt-table-sync: повторная проверка
pt-table-checksum --replicate=percona.checksums --replicate-check-only \
    --host=source_ip --user=monitor_user --password=***
-- → DIFFS 0
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `ERRORS` в выводе pt-table-checksum | Нет прав или таблица без PK | Дайте `SELECT` на таблицы; проверьте наличие PK |
| `DIFFS > 0` | Реальное расхождение данных | Анализ chunk'ей → `pt-table-sync --print` → `--execute` |
| pt-table-sync применяет изменения на мастере | Указан `--host=source_ip` вместо реплики | Всегда указывайте реплику как `--host` или используйте `--sync-to-master` с хостом реплики |
| Проверка зависает / медленно | Таблица без PK, большой размер | Ограничьте `--tables`; увеличьте `--chunk-size` |
| `percona.checksums` не реплицируется | Фильтры репликации исключают БД `percona` | Убедитесь, что БД `percona` не исключена фильтрами |

## Best Practices

1.  **Регулярная проверка** — включите `pt-table-checksum` в cron (еженедельно).
2.  **Всегда начинайте с `--print`** для `pt-table-sync` — никогда не `--execute` сразу.
3.  **Запускайте в окна низкой нагрузки** — проверка читает все строки.
4.  **`--max-load` / `--critical-load`** — обязательно для production, чтобы не уронить источник.
5.  **Таблицы без PK** — добавьте PK или проверяйте отдельно (медленно).
6.  **Не используйте `pt-table-sync` как замену исправлению причины** — сначала найдите, почему возникло расхождение (фильтры, skip errors, ручные правки).

## Дополнительная информация

### См. также
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — ошибки 1032/1062, GTID skip.
- **[Фильтрация](./filtering.md)** — влияние фильтров на консистентность.
- **[Проверка консистентности MySQL](../../MySQL/replication/consistency_checks.md)** — аналогичная тема для MySQL.
- **[Percona Toolkit Documentation](https://www.percona.com/software/database-tools/percona-toolkit)** — `pt-table-checksum`, `pt-table-sync`.
