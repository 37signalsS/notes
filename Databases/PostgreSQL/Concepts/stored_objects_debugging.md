# Отладка и мониторинг хранимых объектов в PostgreSQL

## Определения

*   **PL/pgSQL:** Основной процедурный язык PostgreSQL.
*   **`RAISE`:** Оператор для вывода сообщений в консоль или лог (аналог `print` или `log`).
*   **`pg_stat_user_functions`:** Системное представление, содержащее статистику выполнения функций (количество вызовов, общее и среднее время).
*   **`track_functions`:** Параметр в `postgresql.conf`, определяющий уровень сбора статистики по функциям (`none`, `pl`, `all`).

---

## Практические сценарии

### 1. Отладка через сообщения (Instrumentation)

Самый простой и эффективный способ отладки в PostgreSQL — использование `RAISE`.

```sql
CREATE OR REPLACE FUNCTION debug_example(p_id INT) RETURNS VOID AS $$
BEGIN
    -- Вывод отладочной информации (уровень NOTICE)
    RAISE NOTICE 'Starting procedure for ID: %', p_id;
    
    IF p_id < 0 THEN
        -- Прерывание с ошибкой
        RAISE EXCEPTION 'ID cannot be negative: %', p_id;
    END IF;
    
    -- Вывод текущего времени для замера шагов
    RAISE LOG 'Step 1 completed at %', now();
END;
$$ LANGUAGE plpgsql;
```
*Совет SRE: Уровень `NOTICE` виден клиенту, уровень `LOG` пишется только в серверный лог.*

### 2. Использование расширения `pldbgapi`

Для пошаговой отладки (breakpoints, step over) используется расширение, которое работает в связке с pgAdmin или DBeaver.

**Настройка:**
1.  Установите пакет `postgresql-x.x-pldebugger`.
2.  Добавьте в `postgresql.conf`:
    ```ini
    shared_preload_libraries = 'plugin_debugger'
    ```
3.  Перезапустите БД и создайте расширение: `CREATE EXTENSION pldbgapi;`.

### 3. Профилирование производительности

Чтобы найти "медленные" функции, используйте `pg_stat_user_functions`.

```sql
-- Топ-5 самых медленных функций по общему времени выполнения
SELECT funcname, calls, total_time, self_time 
FROM pg_stat_user_functions 
ORDER BY total_time DESC 
LIMIT 5;
```
*Примечание: Если `total_time` намного больше `self_time`, значит функция тратит время на вызов других функций или SQL-запросов.*

---

## Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Функция "зависла"** | Длительная блокировка или бесконечный цикл. | Найдите PID через `pg_stat_activity` и выполните `SELECT pg_terminate_backend(pid);`. |
| **`RAISE NOTICE` не виден** | Уровень `client_min_messages` установлен выше `NOTICE`. | Выполните `SET client_min_messages = notice;` в текущей сессии. |
| **Статистика по функциям пуста** | Параметр `track_functions` равен `none`. | Установите `track_functions = all` в `postgresql.conf` (требует перезагрузки или `SIGHUP`). |
| **Ошибка "out of shared memory"** | Слишком много триггеров или вложенных вызовов функций. | Увеличьте `max_locks_per_transaction`. |

## Дополнительная информация

### См. также
- **[Оптимизация PL/pgSQL](./pl_pgsql_optimization.md)** — техники ускорения кода.
- **[Конкурентность и блокировки](./concurrency_and_locking.md)** — как процедуры влияют на локи.
- **[Stored Objects Overview](../../Concepts/stored_objects_overview.md)** — общие концепции.
