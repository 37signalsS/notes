# Управление соединениями в MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

*   **`max_connections`** — максимальное количество одновременных соединений (клиентских сессий). При превышении — ошибка `1040: Too many connections`. По умолчанию 151.
*   **`max_user_connections`** — максимальное количество соединений для одного пользователя (0 = без ограничения). Защита от «одного пользователя, съедающего все соединения».
*   **`thread_cache_size`** — количество кэшированных (неактивных) потоков для повторного использования. При новом соединении поток берётся из кэша, а не создаётся заново. Эффективность: `Threads_created / Connections` (цель < 1%).
*   **`wait_timeout`** — время (секунды) до закрытия неактивного (idle) неинтерактивного соединения. По умолчанию 28800 (8 часов).
*   **`interactive_timeout`** — время до закрытия idle интерактивного соединения (клиент `mariadb`). По умолчанию 28800.
*   **`Thread Pool`** — встроенный механизм MariaDB для обработки тысяч соединений через ограниченное число рабочих потоков. Включается `thread_handling = pool-of-threads`. Подробнее: **[Обзор MariaDB](overview.md)**.
*   **Connection Storm** — резкий всплеск новых соединений (например, после перезапуска приложения), исчерпывающий `max_connections` или создающий нагрузку на создание потоков.
*   **`Aborted_connects`** — счётчик неудачных попыток подключения (неверный пароль, нет прав).
*   **`Aborted_clients`** — счётчик соединений, закрытых некорректно (клиент отключился без `mysql_close`).

## Базовые концепции

### Жизненный цикл соединения

```
Клиент подключается
  ↓
Поток берётся из thread_cache (или создаётся новый → Threads_created++)
  ↓
Аутентификация (плагин: unix_socket, ed25519, mysql_native_password, caching_sha2_password)
  ↓
Активная работа (Queries)
  ↓
Idle (Sleep) — ждёт wait_timeout / interactive_timeout
  ↓
Поток возвращается в thread_cache (или завершается)
```

### Расчёт `max_connections`

Формула оценки:

```
max_connections ≈ (количество приложений × connections_per_app) + административный запас
```

**Важно:** каждое соединение потребляет per-thread память (`sort_buffer_size` + `join_buffer_size` + `read_buffer_size` + ...). При `max_connections = 1000` и 5 MB per-thread — до 5 GB RAM при полной загрузке. Не завышайте `max_connections` без расчёта памяти (см. **[Управление памятью](memory_management.md)**).

### Thread Pool vs thread-per-connection

| Режим | `thread_handling` | Когда использовать |
| :--- | :--- | :--- |
| **Thread-per-connection** | `one-thread-per-connection` (default) | < 500 соединений |
| **Thread Pool** | `pool-of-threads` | > 500 соединений, высокая нагрузка |

Thread Pool масштабируется до тысяч соединений, но требует соответствия `thread_pool_size` количеству ядер CPU.

## Практические сценарии

### 1. Проверка текущего состояния

```sql
-- Лимиты
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'max_user_connections';
SHOW VARIABLES LIKE 'thread_cache_size';
SHOW VARIABLES LIKE 'wait_timeout';
SHOW VARIABLES LIKE 'interactive_timeout';

-- Текущее состояние
SHOW GLOBAL STATUS LIKE 'Threads_connected';
SHOW GLOBAL STATUS LIKE 'Threads_running';
SHOW GLOBAL STATUS LIKE 'Threads_created';
SHOW GLOBAL STATUS LIKE 'Connections';
SHOW GLOBAL STATUS LIKE 'Aborted_%';

-- Эффективность thread cache (цель < 1%)
SELECT
  ROUND(100 *
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Threads_created') /
    (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME = 'Connections'),
  2) AS threads_created_ratio_percent;

-- Распределение соединений по состоянию
SELECT COMMAND, COUNT(*) AS cnt
FROM information_schema.PROCESSLIST
GROUP BY COMMAND;

-- Соединения по пользователю и хосту
SELECT USER, HOST, DB, COMMAND, COUNT(*) AS cnt
FROM information_schema.PROCESSLIST
GROUP BY USER, HOST, DB, COMMAND
ORDER BY cnt DESC;
```

### 2. Настройка

```ini
[mariadb]
# Лимит соединений
max_connections = 500

# Лимит на пользователя (защита)
max_user_connections = 100

# Кэш потоков
thread_cache_size = 50

# Таймауты idle-соединений
wait_timeout = 600
interactive_timeout = 600
```

```sql
-- Динамическое изменение (без перезапуска)
SET GLOBAL max_connections = 500;
SET GLOBAL thread_cache_size = 50;
SET GLOBAL wait_timeout = 600;

-- Лимит на пользователя при создании
CREATE USER 'app'@'%' WITH MAX_USER_CONNECTIONS 100;
-- Или изменение существующего
ALTER USER 'app'@'%' WITH MAX_USER_CONNECTIONS 100;
```

### 3. Thread Pool для высоких нагрузок

```ini
[mariadb]
thread_handling = pool-of-threads
thread_pool_size = 16          # обычно = количеству ядер CPU
thread_pool_max_threads = 2000
thread_pool_stall_limit = 500  # мс (в MariaDB — миллисекунды, в MySQL — 10мс единицы)
```

**Валидация:**
```sql
SHOW STATUS LIKE 'Threadpool_%';
-- Threadpool_threads, Threadpool_idle_threads, Threadpool_waits
```

### 4. Диагностика connection storm

```sql
-- Rate создания потоков (Prometheus: rate(mysql_global_status_threads_created[5m]))
SHOW GLOBAL STATUS LIKE 'Threads_created';

-- Кто держит соединения
SELECT USER, HOST, COUNT(*) AS cnt, COMMAND
FROM information_schema.PROCESSLIST
GROUP BY USER, HOST, COMMAND
ORDER BY cnt DESC;

-- Долгие запросы
SELECT ID, USER, HOST, DB, COMMAND, TIME, STATE, INFO
FROM information_schema.PROCESSLIST
WHERE COMMAND != 'Sleep' AND TIME > 5
ORDER BY TIME DESC;
```

### 5. Принудительное закрытие соединения

```sql
-- Найти ID соединения
SELECT ID, USER, HOST, TIME, INFO FROM information_schema.PROCESSLIST;

-- Закрыть конкретное соединение
KILL 42;

-- Закрыть все idle-соединения конкретного пользователя (через скрипт)
-- Внимание: KILL завершает сессию, приложение получит ошибку
```

## Устранение неполадок (Troubleshooting)

### Too many connections (1040)

*   **Причина:** исчерпан `max_connections`; connection storm; утечки соединений в приложении.
*   **Диагностика:** `SHOW STATUS LIKE 'Threads_connected';` vs `max_connections`; `SHOW PROCESSLIST` — кто держит соединения; много `Sleep` — утечки.
*   **Решение:** увеличьте `max_connections`; включите Thread Pool; сократите `wait_timeout`; настройте connection pooling (ProxySQL/MaxScale); исправьте утечки в приложении.

### Высокий `Threads_created / Connections`

*   **Причина:** `thread_cache_size` слишком мал — потоки создаются/уничтожаются при каждом соединении.
*   **Диагностика:** ratio > 1%.
*   **Решение:** увеличьте `thread_cache_size` (50–100).

### Много `Aborted_clients`

*   **Причина:** клиенты отключаются некорректно (без `mysql_close`), таймаут, сетевые разрывы.
*   **Решение:** проверьте приложение (корректное закрытие соединений); увеличьте `wait_timeout` при сетевых разрывах.

### Много `Aborted_connects`

*   **Причина:** неверные пароли, нет прав, превышен `max_connections`.
*   **Решение:** проверьте логи (`Access denied`), права пользователей, `max_connections`.

## Лучшие практики (Best Practices)

1.  **Connection pooling:** используйте ProxySQL или MaxScale вместо увеличения `max_connections` — снижает нагрузку на Thread Pool.
2.  **`max_user_connections`:** ограничивайте на пользователя — защита от одного «жадного» приложения.
3.  **`wait_timeout`:** сокращайте (600–1800с) для закрытия idle-соединений и освобождения ресурсов.
4.  **Thread Pool:** включайте при > 500 соединениях.
5.  **Расчёт памяти:** учитывайте per-thread потребление при выборе `max_connections`.
6.  **Мониторьте:** `Threads_connected`, `Threads_created`, `Aborted_*` через Prometheus с алертами.

## Дополнительная информация

### См. также

*   **[Обзор MariaDB](overview.md)** — Thread Pool.
*   **[Управление памятью](memory_management.md)** — per-thread буферы.
*   **[Мониторинг](monitoring.md)** — алерты на соединения.
*   **[ProxySQL](proxysql.md)** — connection pooling.
*   **[MaxScale](MaxScale/maxscale_overview.md)** — connection pooling и failover.

### Внешние ресурсы

*   [MariaDB Connection Management](https://mariadb.com/kb/en/connection-management/)
*   [MariaDB Thread Pool](https://mariadb.com/kb/en/thread-pool/)
*   [MariaDB KILL](https://mariadb.com/kb/en/kill/)
*   [MariaDB MAX_USER_CONNECTIONS](https://mariadb.com/kb/en/create-user/)
