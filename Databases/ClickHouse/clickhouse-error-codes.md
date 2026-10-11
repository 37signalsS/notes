# ClickHouse — Коды ошибок

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Error code** — числовой код ошибки ClickHouse, возвращаемый в сообщении (`Code: N. ...`). Позволяет программно обрабатывать ошибки.

**system.errors** — системная таблица со списком всех кодов ошибок и их описаний.

**system.error_log** — таблица с логом ошибок (если включена в конфиге).

**Retryable error** — ошибка, безопасная для повтора (например, Code 517 при гонке метаданных-ALTER).

## Основные концепции

### Структура сообщения об ошибке

```
Code: 241. DB::Exception: Memory limit (total) exceeded. ...
```

- **Code** — числовой код.
- **DB::Exception** — тип исключения.
- **Сообщение** — описание с контекстом.

### Категории кодов

Коды ошибок ClickHouse не фиксированы в диапазонах строго — они назначаются по мере добавления новых типов исключений. Тем не менее сложилась примерная схема:

| Диапазон | Категория | Примеры |
| :--- | :--- | :--- |
| 1–99 | Общие ошибки SУБД | 1 — `NO_FREE_RESOURCE`, 46 — `ACCESS_DENIED` |
| 100–199 | Ошибки парсинга/синтаксиса | 60 — `TABLE_NOT_FOUND`, 117 — `SYNTAX_ERROR` |
| 200–299 | Ресурсы и сеть | 159 — `TIMEOUT_EXCEEDED`, 202 — `TOO_MANY_SIMULTANEOUS_QUERIES`, 241 — `MEMORY_LIMIT_EXCEEDED` |
| 300–399 | Распределённые запросы | 164 — `READONLY`, 285 — `TOO_FEW_LIVE_REPLICAS` |
| 400–499 | Движки таблиц | 246 — `CORRUPTED_DATA`, 252 — `TOO_MANY_PARTS` |
| 500–599 | Репликация и метаданные | 517 — `RETRYABLE_ERROR`, 252 — `TOO_MANY_PARTS` |
| 600+ | Специфические / внешние | 999 — `KEEPER_EXCEPTION`, 243 — `ILLEGAL_LOCK_RELEASED` |

**Полный список** доступен в СУБД:

```sql
SELECT code, name, description
FROM system.errors
ORDER BY code;
```

## Справочник частых кодов

### Синтаксис и парсинг

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 60 | `TABLE_NOT_FOUND` | Таблица не найдена |
| 81 | `DATABASE_NOT_FOUND` | База данных не найдена |
| 115 | `UNKNOWN_SETTING` | Неизвестная настройка |
| 117 | `SYNTAX_ERROR` | Синтаксическая ошибка SQL |

### Ресурсы и лимиты

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 159 | `TIMEOUT_EXCEEDED` | Превышен таймаут выполнения |
| 184 | `TOO_MUCH_INSERTED_ROWS` | Превышено `max_inserted_rows` |
| 199 | `TOO_MUCH_INSERTED_BYTES` | Превышено `max_inserted_bytes` |
| 202 | `TOO_MANY_SIMULTANEOUS_QUERIES` | Превышен лимит параллельных запросов |
| 203 | `NO_FREE_CONNECTION` | Нет свободных соединений |
| 241 | `MEMORY_LIMIT_EXCEEDED` | Превышен лимит памяти |
| 246 | `CORRUPTED_DATA` | Повреждённые данные на диске |
| 252 | `TOO_MANY_PARTS` | Слишком много частей в партиции |
| 257 | `ILLEGAL_TYPE_OF_ARGUMENT` | Неверный тип аргумента в настройке/функции |

### Сеть и соединения

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 198 | `DNS_ERROR` | Ошибка DNS-разрешения |
| 209 | `SOCKET_TIMEOUT` | Таймаут сокета |
| 210 | `NETWORK_ERROR` | Сетевая ошибка |
| 215 | `CANNOT_CONNECT_TO_ENDPOINT` | Не удалось подключиться к endpoint |
| 216 | `UNKNOWN_METHOD` | HTTP-метод не поддерживается |

### Сеть

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 198 | `DNS_ERROR` | Ошибка DNS-разрешения |
| 209 | `SOCKET_TIMEOUT` | Таймаут сокета |
| 210 | `NETWORK_ERROR` | Сетевая ошибка |
| 215 | `CANNOT_CONNECT_TO_ENDPOINT` | Не удалось подключиться к endpoint |
| 216 | `UNKNOWN_METHOD` | HTTP-метод не поддерживается |

### Общие и доступ

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 1 | `NO_FREE_RESOURCE` | Нет свободных ресурсов (слишком много запросов) |
| 46 | `ACCESS_DENIED` | Недостаточно прав на операцию |
| 264 | `NUMBER_OF_ROWS_IS_NOT_SUPPORT_LIMIT` | Превышено `max_result_rows` |

### Данные и репликация

| Код | Имя | Описание |
| :--- | :--- | :--- |
| 164 | `READONLY` | Таблица/реплика в режиме read-only |
| 242 | `TABLE_IS_READ_ONLY` | Таблица доступна только для чтения |
| 246 | `CORRUPTED_DATA` | Повреждённые данные |
| 285 | `TOO_FEW_LIVE_REPLICAS` | Мало живых реплик для кворума |
| 319 | `UNKNOWN_STATUS_OF_INSERT` | Неизвестный статус вставки |
| 517 | `RETRYABLE_ERROR` | Ошибка гонки метаданных (повторяемая) |
| 999 | `KEEPER_EXCEPTION` | Ошибка Keeper/ZooKeeper |

## Практические сценарии

### Поиск кода ошибки

```sql
-- Все коды ошибок
SELECT * FROM system.errors ORDER BY code;

-- Поиск по имени
SELECT code, name, description
FROM system.errors
WHERE name LIKE '%MEMORY%';

-- Поиск по коду
SELECT name, description FROM system.errors WHERE code = 241;
```

### Включение error_log с retention

```xml
<!-- config.xml -->
<clickhouse>
    <error_log>
        <database>system</database>
        <table>error_log</table>
        <partition_by>toYYYYMM(event_time)</partition_by>
        <ttl>event_time + INTERVAL 30 DAY DELETE</ttl>
        <flush_interval_milliseconds>7500</flush_interval_milliseconds>
    </error_log>
</clickhouse>
```

**Устаревание и очистка.** TTL на `event_time` удаляет записи старше 30 дней. Если TTL не задан — включите ручную очистку через cron:

```bash
# Еженедельный DROP устаревших партиций
clickhouse-client --query "
ALTER TABLE system.error_log DELETE WHERE event_time < now() - INTERVAL 30 DAY"
```

```sql
-- Анализ ошибок
SELECT
    code,
    name,
    count() AS cnt,
    max(event_time) AS last_seen
FROM system.error_log
WHERE event_time > now() - INTERVAL 1 HOUR
GROUP BY code, name
ORDER BY cnt DESC;
```

**Интеграция с Prometheus.** Метрика `error_log_count{code, name}` доступна через `clickhouse_exporter` или native `system.metrics`. События из `system.error_log` можно экспортировать через [clickhouse-log-exporter](https://github.com/Perovmakc/clickhouse-log-exporter) для интеграции с Alertmanager.

**Алерты в Prometheus (пример для `clickhouse_exporter`):**

```yaml
groups:
- name: clickhouse.errors
  rules:
  - alert: ClickHouseHighErrorRate
    expr: rate(clickhouse_metrics_ErrorLogCount[5m]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "ClickHouse: высокая частота ошибок (code {{ $value }})"

  - alert: ClickHouseMemoryLimitExceeded
    expr: increase(clickhouse_metrics_MemoryLimitExceededEvents[10m]) > 0
    for: 0m
    labels:
      severity: critical
    annotations:
      summary: "ClickHouse: превышен лимит памяти (Code 241)"
```

### Диагностика через CLI и systemd

Ошибки ClickHouse логируются в `/var/log/clickhouse-server/clickhouse-server.err.log` и `clickhouse-server.log`. Интеграция с `journalctl`:

```bash
# Просмотр ошибок за последние 30 минут
journalctl -u clickhouse-server --since "30 min ago" | grep -E "Error|Exception"

# Фильтрация по коду ошибки в журнале
journalctl -u clickhouse-server | grep "Code: 241" | tail -20

# Анализ в реальном времени
journalctl -fu clickhouse-server --output cat | grep "DB::Exception"
```

**Проверка конфигурации без запуска сервера:**

```bash
# Валидация конфигов (ловит ошибки парсинга XML, неверные пути)
clickhouse-server --config-file=/etc/clickhouse-server/config.xml --check

# Просмотр эффективной конфигурации
clickhouse-client --query "SELECT name, value FROM system.settings WHERE name LIKE '%timeout%'"
```

### Обработка ошибок в клиенте

```python
# Python: retry на retryable-ошибки
from clickhouse_driver import Client, errors

client = Client('localhost')
for attempt in range(3):
    try:
        client.execute("ALTER TABLE logs ADD COLUMN x String")
        break
    except errors.ServerError as e:
        if e.code == 517:  # RETRYABLE_ERROR
            continue
        raise
```

## Устранение неисправностей

| Код | Типичная причина | Решение |
| :--- | :--- | :--- |
| 60 | Опечатка в имени таблицы | Проверить `system.tables` |
| 115 | Опечатка в настройке | Проверить `system.settings` |
| 117 | Синтаксис SQL | Проверить запрос; `EXPLAIN SYNTAX` |
| 159 | Долгий запрос / сеть | Увеличить таймаут; оптимизировать запрос |
| 202 | Перегрузка запросами | Увеличить `max_concurrent_queries`; очередь |
| 203 | Исчерпаны соединения | Пулинг соединений; увеличить `max_connections` |
| 241 | Большой GROUP BY/JOIN | `PREWHERE`; `max_bytes_before_external_group_by` |
| 252 | Мелкие вставки | Батчинг; `async_insert` |
| 285 | Мало реплик | Проверить `system.replicas`; `insert_quorum` |
| 517 | Гонка ALTER | Повторить запрос |
| 999 | Проблемы Keeper | Проверить `system.zookeeper_connection` |

## Лучшие практики

1. **Логировать коды ошибок** — включить `error_log` для анализа трендов.
2. **Retry на 517** — повторять retryable-ошибки гонки метаданных.
3. **Алерты** — на 241 (memory), 252 (parts), 285 (replicas), 999 (keeper).
4. **`system.errors`** — справочник кодов в самой СУБД.
5. **Программная обработка** — использовать коды для логики retry/fallback.

## Дополнительная информация

### Смежные темы

- Производительность и диагностика — **[Производительность](./clickhouse-performance.md)**.
- Мониторинг (system.errors, metrics) — **[Мониторинг](./clickhouse-monitoring.md)**.
- Репликация и репликационные ошибки (242, 285, 517) — **[Кластерное управление](./clickhouse-cluster.md)**.
- Эволюция схемы (Code 517) — **[Эволюция схемы](./clickhouse-schema-evolution.md)**.
- Операционная диагностика (troubleshooting) — **[Эксплуатация](./clickhouse-operations.md#устранение-неисправностей)**.

### Ресурсы

- [Документация: Error codes](https://clickhouse.com/docs/operations/errors)
- [Документация: system.errors](https://clickhouse.com/docs/operations/system-tables/errors)
