# Управление Relay Log в MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Relay Log** — локальный журнал реплики, куда I/O-поток записывает события, полученные от источника, перед их применением SQL-потоком.
*   **`relay_log`** — базовое имя и путь к relay log файлам. По умолчанию — в `datadir` с именем `host_name-relay-bin`.
*   **`max_relay_log_size`** — максимальный размер одного файла relay log. При достижении — ротация (создание нового файла). По умолчанию 0 — используется `max_binlog_size` (1 ГБ). Диапазон: 4096 байт..1 ГБ.
*   **`relay_log_space_limit`** — максимальный суммарный размер всех relay log файлов. По умолчанию 0 (без лимита). При достижении лимита **I/O-поток останавливается** (`Replica_IO_Running: No`), пока SQL-поток не применит события и не освободит место.
*   **`relay_log_purge`** — автоматическое удаление обработанных relay log файлов. По умолчанию ON. Динамическая переменная.
*   **`relay_log_recovery`** — автоматическое восстановление relay log при старте реплики (повторная закачка с источника). По умолчанию OFF. Рекомендуется ON для crash-safe replication.

## Базовые концепции

### Жизненный цикл relay log

1.  I/O-поток получает события от источника и записывает в текущий relay log файл.
2.  При достижении `max_relay_log_size` (или `FLUSH LOGS`, или старте I/O-потока) создаётся новый файл.
3.  SQL-поток читает и применяет события из relay log.
4.  После применения файл автоматически удаляется (при `relay_log_purge = ON`).

### Когда relay log занимает много места

*   **Реплика отстаёт** (SQL-поток не успевает) — relay log накапливается.
*   **Отложенная репликация** (`SOURCE_DELAY`) — relay log растёт на всю величину задержки.
*   **`relay_log_purge = OFF`** — файлы не удаляются после применения (для отладки/аудита).
*   **I/O-поток работает, SQL-поток остановлен** — relay log растёт без ограничений (если нет `relay_log_space_limit`).

### Взаимодействие relay_log_purge и relay_log_recovery

*   `relay_log_purge = ON` + `relay_log_recovery = ON` — безопасная crash-safe конфигурация.
*   `relay_log_purge = OFF` + `relay_log_recovery = ON` — **может привести к несогласованности данных** (документация MariaDB предупреждает об этом). Не комбинируйте.
*   `relay_log_purge = OFF` — только для отладки, когда нужно сохранить relay log для анализа.

### relay_log_space_limit: механика

При достижении лимита:
1.  I/O-поток останавливается (`Replica_IO_Running: No`).
2.  SQL-поток продолжает применять события, освобождая место.
3.  Когда место освобождено — I/O-поток возобновляется.

**Важно:** `relay_log_space_limit` — не динамическая переменная (требует перезапуска для изменения). Значение 0 означает отсутствие лимита.

## Практические сценарии

### Сценарий 1: Рекомендуемая конфигурация (production)

```ini
# На реплике (/etc/mysql/mariadb.conf.d/50-server.cnf)
[mariadb]
relay_log = /var/log/mysql/relay-bin
max_relay_log_size = 1024M
relay_log_space_limit = 0          # 0 = без лимита; при ограниченном диске — с запасом
relay_log_purge = ON               # автоматическая очистка обработанных relay log
relay_log_recovery = ON            # crash-safe: повторная закачка при старте
relay_log_info_repository = TABLE  # позиция репликации в таблице (crash-safe)
sync_relay_log = 1                 # синхронизация на диск (надёжность, цена — производительность)
```

> **Примечание:** `relay_log_space_limit = 0` безопаснее при достаточном свободном месте. Если диск ограничен — выставьте лимит с 20–50% запасом от ожидаемого максимума relay log при худшем лаге.

### Сценарий 2: Ограничение relay log на реплике с ограниченным диском

```ini
[mariadb]
# Диск 100 ГБ, ожидаемый максимальный лаг — 2 часа, binlog ~500 МБ/час
# Максимальный relay log ≈ 1 ГБ + запас 50% → 1.5 ГБ
relay_log_space_limit = 1610612736   # 1.5 ГБ в байтах
relay_log_purge = ON
```

При достижении лимита I/O-поток остановится — это сигнал для алерта (мониторьте `Replica_IO_Running`).

### Сценарий 3: Диагностика роста relay log

```sql
-- Текущий размер relay log
SHOW REPLICA STATUS\G
-- Relay_Log_Space: размер всех relay log файлов в байтах
-- Relay_Log_File: текущий файл

-- Проверка настроек
SHOW VARIABLES LIKE 'relay_log%';
SHOW VARIABLES LIKE 'max_relay_log_size';

-- На диске
ls -lh /var/log/mysql/relay-bin.*
du -sh /var/log/mysql/
```

```bash
# Если relay log растёт:
# 1. Проверьте лаг
SHOW REPLICA STATUS\G
-- Seconds_Behind_Source

# 2. Проверьте, что SQL-поток работает
-- Replica_SQL_Running: Yes

# 3. Если SQL-поток остановлен — см. troubleshooting
```

### Сценарий 4: Сброс relay log после повреждения

```sql
-- Остановите репликацию
STOP REPLICA;

-- Сбросьте relay log (реплика перекачает заново с источника)
RESET REPLICA;

-- Запустите репликацию
START REPLICA;
```

> **Примечание:** `RESET REPLICA` сбрасывает `relay_log_info_repository` и `gtid_slave_pos`. Убедитесь, что `SOURCE_USE_GTID=slave_pos` настроен, чтобы реплика автоматически нашла правильную позицию.

### Сценарий 5: Отключение purge для отладки

```sql
-- Сохранить relay log для анализа (временно!)
SET GLOBAL relay_log_purge = OFF;

-- ... анализ ...

-- Вернуть обратно
SET GLOBAL relay_log_purge = ON;
```

> **Предупреждение:** не оставляйте `relay_log_purge = OFF` в production — relay log заполнит диск. И не комбинируйте с `relay_log_recovery = ON`.

## Валидация

```sql
-- Проверка конфигурации
SHOW VARIABLES LIKE 'relay_log%';
-- relay_log: /var/log/mysql/relay-bin
-- relay_log_purge: ON
-- relay_log_recovery: ON
-- relay_log_space_limit: 0

SHOW VARIABLES LIKE 'max_relay_log_size';
-- → 0 (используется max_binlog_size) или конкретное значение

-- Проверка текущего состояния
SHOW REPLICA STATUS\G
-- Relay_Log_File: relay-bin.000003
-- Relay_Log_Space: 1073741824
-- Replica_IO_Running: Yes
-- Replica_SQL_Running: Yes
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Relay log заполнил диск | `relay_log_purge = OFF` или SQL-поток остановлен | Включите `relay_log_purge = ON`; проверьте `Replica_SQL_Running` |
| `Replica_IO_Running: No` при достаточном диске | Достигнут `relay_log_space_limit` | Увеличьте лимит или дождитесь применения событий SQL-потоком |
| Данные повреждены после сбоя | `relay_log_recovery = OFF` | Включите `relay_log_recovery = ON` |
| Несогласованность после восстановления | `relay_log_purge = OFF` + `relay_log_recovery = ON` | Установите `relay_log_purge = ON` |
| `relay_log_space_limit` не применяется | Переменная не динамическая | Изменение требует перезапуска MariaDB |

## Best Practices

1.  **`relay_log_recovery = ON`** — на всех репликах в production (crash-safe).
2.  **`relay_log_purge = ON`** — по умолчанию; отключайте только для отладки.
3.  **Выносите relay log на отдельный диск** от `datadir` — снижает конкуренцию I/O и упрощает мониторинг места.
4.  **`relay_log_space_limit`** — задавайте только при ограниченном диске, с запасом 20–50% от ожидаемого максимума.
5.  **Мониторьте `Relay_Log_Space`** и свободное место на разделе relay log.
6.  **Не комбинируйте** `relay_log_purge = OFF` с `relay_log_recovery = ON`.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — crash-safe replication.
- **[Диагностика и Troubleshooting](./troubleshooting.md)** — анализ relay log, повреждение.
- **[Документация MariaDB: Relay Log](https://mariadb.com/docs/server/server-management/server-monitoring-logs/binary-log/relay-log)**
- **[Relay Logs и Crash-Safe репликация MySQL](../../MySQL/replication/relay_logs_crashsafe.md)** — аналогичная тема для MySQL.
