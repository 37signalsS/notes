# ClickHouse — Операционный SQL и SYSTEM-команды

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**Мутация (Mutation)** — асинхронная операция изменения данных (`ALTER TABLE ... UPDATE/DELETE`), перезаписывающая целые куски (parts). Выполняется в фоне, не блокирует запросы.

**Lightweight delete** — операция `DELETE FROM ... WHERE`, помечающая строки как удалённые (`_row_exists = 0`) без немедленного физического удаления. GA с версии 23.3. Доступна только для семейства MergeTree.

**OPTIMIZE TABLE ... FINAL** — принудительное слияние всех частей партиции в одну часть. Дорогая операция, перезаписывающая данные.

**FREEZE PARTITION** — создание жёстких ссылок (hardlinks) на части данных в `/var/lib/clickhouse/shadow/`. Мгновенная операция, основа для бэкапов.

**KILL QUERY** — принудительное завершение выполняющихся запросов по условию (пользователь, query_id, текст запроса).

**DETACH / ATTACH** — отключение таблицы (метаданные удаляются, данные остаются на диске) и повторное подключение.

**FINAL (в SELECT)** — модификатор, заставляющий движки семьи MergeTree вернуть «финальное» состояние строк (дедупликация для `ReplacingMergeTree` и т.п.). Очень дорогая операция.

**lightweight_delete_mode** — настройка, определяющая механизм `DELETE FROM`. `alter_update` (по умолчанию) — мутация; `lightweight_update` / `lightweight_update_force` — запись patch parts с `_row_exists = 0`. С режимом patch parts `lightweight_deletes_sync` не ждёт другие реплики: на `ReplicatedMergeTree` удалённые строки могут быть видны до получения патча.

**APPLY DELETED MASK** — команда `ALTER TABLE ... APPLY DELETED MASK`, принудительно удаляющая строки, помеченные lightweight delete, с диска. Тяжёлая мутация, эквивалентна `ALTER TABLE ... DELETE WHERE _row_exists = 0`. Полезна, когда нужно гарантированно освободить место (например, для compliance) в отличие от обычного слияния.

**APPLY PATCHES** — команда `ALTER TABLE ... APPLY PATCHES`, материализующая patch parts, созданные lightweight `UPDATE`. Выполняется асинхронно в фоне.

**min_age_to_force_merge_seconds** — MergeTree-настройка, заставляющая сливать части, если все они в диапазоне старше указанного времени. Позволяет гарантировать, что строки, помеченные lightweight delete, будут физически удалены в предсказуемое время.

## Основные концепции

### Мутации vs lightweight delete

| Характеристика | `ALTER TABLE ... DELETE/UPDATE` (мутация) | `DELETE FROM ... WHERE` (lightweight) |
| :--- | :--- | :--- |
| Механизм | Перезапись целых частей | Маркировка строк (`_row_exists = 0`) |
| Скорость | Медленная (перезапись данных) | Быстрая (маркировка) |
| Физическое удаление | При слиянии (merge) | При слиянии (merge) |
| Синхронность | Асинхронно (настройка `mutations_sync`) | Синхронно по умолчанию (`lightweight_deletes_sync`) |
| Когда использовать | Массовые изменения, `UPDATE` | Точечное удаление небольших объёмов |

**Важно:** lightweight delete не работает с таблицами, имеющими проекции, без настройки `lightweight_mutation_projection_mode`. В compact-частях все колонки хранятся в одном файле — удаление строк требует перезаписи файла. С версии 26.8 доступен режим **patch parts** через настройку `lightweight_delete_mode`: `lightweight_update` записывает отдельные patch parts с маской `_row_exists = 0` вместо перезаписи частей, что быстрее на wide-частях. С физическим удалением строк — через фоновые слияния или принудительно через `ALTER TABLE ... APPLY DELETED MASK`.

### Как работает OPTIMIZE FINAL

`OPTIMIZE TABLE ... FINAL` заставляет движок слить все части партиции в одну, применив логику движка (дедупликация, агрегация). Это полезно после массовой загрузки или перед важными запросами, но на больших таблицах крайне дорого — фоновые слияния обычно справляются сами.

### FINAL в SELECT

`SELECT ... FROM table FINAL` возвращает строки в «финальном» состоянии (например, для `ReplacingMergeTree` — только последнюю версию строки). Это заставляет движок обрабатывать части особым образом и очень дорого — избегайте в продакшен-запросах. Предпочтительнее: `argMax`/`anyLast` в запросе или дедупликация в материализованном представлении.

## Практические сценарии

### OPTIMIZE TABLE ... FINAL

```sql
-- Принудительное слияние всей таблицы (дорого!)
OPTIMIZE TABLE logs FINAL;

-- Слияние конкретной партиции
OPTIMIZE TABLE logs PARTITION '2026-09' FINAL;

-- Дедупликация (для ReplacingMergeTree и др.)
OPTIMIZE TABLE events DEDUPLICATE;

-- Дедупликация по конкретным колонкам
OPTIMIZE TABLE events DEDUPLICATE BY user_id, event_time;
OPTIMIZE TABLE events DEDUPLICATE BY * EXCEPT service;

-- Принудительное слияние с удалением delete-строк (ReplacingMergeTree)
OPTIMIZE TABLE events FINAL CLEANUP;

-- ON_CLUSTER для распределённой таблицы
OPTIMIZE TABLE logs ON CLUSTER '{cluster}' FINAL;

-- FORCE — слияние даже если уже одна часть (иначе OPTIMIZE молча ничего не делает)
OPTIMIZE TABLE logs FORCE;

-- Безопасный dry-run: перечислить пары для слияния без выполнения
OPTIMIZE TABLE logs DRY RUN PARTS '20260901_1_5_1', '20260901_6_10_1';
```

**Когда запускать:** после разовой массовой загрузки, перед важным отчётом, в тестовых сценариях, для очистки delete-строк в `ReplacingMergeTree`. **Когда НЕ запускать:** регулярно по расписанию — фоновые слияния справляваются сами, а `FINAL` создаёт пик нагрузки на I/O и CPU. `CLEANUP` требует включённой настройки `allow_experimental_replacing_merge_with_cleanup` (см. ниже).

### Lightweight delete

```sql
-- Удаление строк (GA с 23.3, флаг allow_experimental_lightweight_delete больше не нужен)
DELETE FROM logs WHERE event_time < now() - INTERVAL 1 YEAR;

-- Удаление внутри партиции (оптимизация: затрагивает только нужные партиции)
DELETE FROM logs IN PARTITION '2025-01' WHERE severity = 'DEBUG';

-- Асинхронное выполнение (запрос вернётся сразу, данные ещё будут видны до завершения мутации)
SET lightweight_deletes_sync = 0;
DELETE FROM logs WHERE user_id = 12345;

-- Права: DELETE требует привилегии ALTER DELETE
GRANT ALTER DELETE ON db.logs TO analyst;
```

Настройка `optimize_mutations_with_partition_pruning` (включена по умолчанию) автоматически определяет условия по ключу партиционирования в `WHERE` и удаляет только из затронутых партиций.

**Режимы lightweight delete** (`lightweight_delete_mode`):
- `alter_update` (по умолчанию) — мутация с перезаписью `_row_exists`.
- `lightweight_update` — запись patch parts с маской `_row_exists = 0` (быстрее на wide-частях; не ждёт реплики).
- `lightweight_update_force` — то же, но выбрасывает ошибку, если patch parts недоступны.

```sql
-- Явный выбор режима
SET lightweight_delete_mode = 'lightweight_update';
DELETE FROM logs WHERE user_id = 12345;
```

**Гарантированное физическое удаление** — маска `_row_exists = 0` сохраняется до слияния. Чтобы освободить диск в предсказуемый срок:

```sql
-- Принудительно удалить помеченные строки (тяжёлая мутация)
ALTER TABLE logs APPLY DELETED MASK;

-- Или заставить слияния старых частей через MergeTree-настройку
ALTER TABLE logs MODIFY SETTING min_age_to_force_merge_seconds = 86400;
```

`APPLY DELETED MASK` эквивалентен `ALTER TABLE logs DELETE WHERE _row_exists = 0`. На реплицируемых таблицах требует синхронизации реплик перед выполнением.

### Тяжёлые мутации (ALTER UPDATE / ALTER DELETE)

```sql
-- Массовое обновление (перезаписывает части)
ALTER TABLE logs UPDATE severity = 'WARN' WHERE severity = 'WARNING';

-- Массовое удаление (перезаписывает части)
ALTER TABLE logs DELETE WHERE severity = 'DEBUG';

-- Синхронное выполнение (ждать завершения)
ALTER TABLE logs DELETE WHERE severity = 'DEBUG' SETTINGS mutations_sync = 2;

-- Мониторинг мутаций (богатый вариант для SRE)
SELECT database, table, mutation_id, command, create_time, parts_to_do,
       is_done, latest_failed_part, latest_fail_time, latest_fail_reason
FROM system.mutations
WHERE is_done = 0
ORDER BY create_time;

-- Отмена зависшей мутации
KILL MUTATION WHERE table = 'logs' AND is_done = 0;
KILL MUTATION WHERE mutation_id = 'mutation_123_1' SYNC;

-- Принудительное материализование patch parts от lightweight UPDATE
ALTER TABLE logs APPLY PATCHES;
```

**Интерпретация мониторинга:** `parts_to_do` стремительно не убывает → проблема ёмкости (I/O, CPU). `latest_fail_reason` заполнен → ошибка корректности, мутация блокирует очередь. Мутация висит > 24 ч → `SYSTEM STOP MERGES`, затем `KILL MUTATION`.

### Управление запросами (KILL QUERY / PROCESSLIST)

```sql
-- Текущие выполняющиеся запросы (аналог SHOW PROCESSLIST в MySQL)
SHOW PROCESSLIST;
SELECT * FROM system.processes;

-- Завершение запросов по условию
KILL QUERY WHERE query_id = 'abc-123';
KILL QUERY WHERE user = 'etl_user';
KILL QUERY WHERE query LIKE '%heavy_table%';
KILL QUERY WHERE query_id = 'abc-123' SYNC;  -- дождаться подтверждения

-- Завершение всех запросов пользователя (кроме своего)
KILL QUERY WHERE user = 'etl_user' AND query_id != currentQueryID();
```

### DETACH / ATTACH

```sql
-- Отключить таблицу (данные остаются на диске, метаданные удаляются)
DETACH TABLE logs;
DETACH TABLE logs PERMANENTLY;   -- метаданные удаляются без возможности восстановления

-- Подключить обратно
ATTACH TABLE logs;

-- Партиции
ALTER TABLE logs DETACH PARTITION '2026-01';
ALTER TABLE logs ATTACH PARTITION '2026-01';
ALTER TABLE logs DROP DETACHED PARTITION '2026-01';  -- удалить отключённые части
```

### FREEZE / FETCH PARTITION (бэкапы через hardlinks)

```sql
-- Создать снапшот партиции (hardlinks в /var/lib/clickhouse/shadow/)
ALTER TABLE logs FREEZE PARTITION '2026-09';

-- Создать снапшот всей таблицы
ALTER TABLE logs FREEZE;

-- Скачать партицию с другой реплики
ALTER TABLE logs FETCH PARTITION '2026-09' FROM '/clickhouse/tables/{shard}/logs';
```

`FREEZE` мгновенна (hardlinks, не копирование данных). Снапшоты лежат в `/var/lib/clickhouse/shadow/<increment>/` — их нужно скопировать на внешний носитель вручную или через `clickhouse-backup`. Детали — в **[Бэкапах и восстановлении](./clickhouse-backup.md)**.

### Полезные модификаторы запросов

```sql
-- LIMIT n BY: первые N строк в каждой группе
SELECT * FROM events ORDER BY event_time DESC LIMIT 1 BY user_id;

-- SAMPLE: выборка (требует SAMPLE BY в определении таблицы)
SELECT count() FROM events SAMPLE 0.1;            -- 10% данных
SELECT count() FROM events SAMPLE 1/10;           -- то же самое
SELECT count() FROM events SAMPLE 0.1 OFFSET 0.5; -- выборка со смещением

-- WITH TOTALS: итоговая строка по GROUP BY
SELECT service, count() FROM events GROUP BY service WITH TOTALS;

-- ARRAY JOIN: разворачивание массива в строки
SELECT user_id, tag FROM events ARRAY JOIN tags AS tag;
SELECT user_id, tag FROM events LEFT ARRAY JOIN tags AS tag;  -- с сохранением пустых

-- GLOBAL IN: отправить подзапрос на все шарды (иначе каждый шард выполняет локально)
SELECT * FROM distributed_events
WHERE user_id GLOBAL IN (SELECT id FROM users_local);
```

### SYSTEM-команды (справочник)

| Команда | Действие |
| :--- | :--- |
| `SYSTEM RELOAD CONFIG` | Перезагрузить конфигурацию сервера без перезапуска |
| `SYSTEM RELOAD DICTIONARIES` | Перезагрузить все словари |
| `SYSTEM RELOAD DICTIONARY db.name` | Перезагрузить конкретный словарь |
| `SYSTEM FLUSH LOGS` | Сбросить системные логи (`query_log` и др.) на диск |
| `SYSTEM FLUSH DISTRIBUTED db.table` | Сбросить накопленные в очереди распределённые запросы на шарды |
| `SYSTEM STOP/START MERGES [db.table]` | Остановить/возобновить фоновые слияния |
| `SYSTEM STOP/START TTL MERGES [db.table]` | Остановить/возобновить TTL-слияния |
| `SYSTEM STOP/START FETCHES [db.table]` | Остановить/возобновить загрузку частей с реплик |
| `SYSTEM STOP/START REPLICATION QUEUES [db.table]` | Остановить/возобновить очереди репликации |
| `SYSTEM STOP/START MOVES [db.table]` | Остановить/возобновить перемещение данных между дисками |
| `SYSTEM STOP/START DISTRIBUTED SENDS` | Остановить/возобновить отправку данных на шарды |
| `SYSTEM STOP/START REPLICATED SENDS` | Остановить/возобновить отправку данных на реплики |
| `SYSTEM SYNC REPLICA [db.table]` | Дождаться, пока реплика догонит очередь |
| `SYSTEM RESTART REPLICAS` / `SYSTEM RESTART REPLICA db.table` | Перезапустить репликацию |
| `SYSTEM RESTORE REPLICA db.table` | Восстановить реплику (сброс в read-write) |
| `SYSTEM DROP DNS CACHE` | Сбросить кэш DNS |
| `SYSTEM DROP MARK CACHE` | Сбросить кэш маркеров (marks) |
| `SYSTEM DROP UNCOMPRESSED CACHE` | Сбросить кэш незакомпрессированных блоков |
| `SYSTEM CLEANUP` | Очистить старые части, WAL и мутации, накопившиеся в `data/` |
| `SYSTEM REFRESH VIEW [db.]name` | Принудительно запустить out-of-schedule refresh |
| `SYSTEM STOP VIEW [db.]name` (или `... VIEWS`) | Остановить refresh и отменить текущий (Replicated/Shared — только локальная реплика) |
| `SYSTEM START VIEW [db.]name` (или `... VIEWS`) | Возобновить refresh (снимает STOP и PAUSE) |
| `SYSTEM PAUSE VIEW [db.]name` (или `... VIEWS`) | Приостановить refresh без прерывания текущего; отменяется `START VIEW` |
| `SYSTEM CANCEL VIEW [db.]name` | Отменить текущий refresh без изменения расписания |
| `SYSTEM WAIT VIEW [db.]name` | Дождаться завершения текущего refresh |
| `SYSTEM STOP/START REPLICATED VIEW [db.]name` | То же, но на всех репликах (для Replicated/Shared баз) |

## DevOps / SRE: мониторинг и настройка

### Мониторинг мутаций и слияний

Мутации и фоновые слияния — основной источник нагрузки на диск. Следить за очередью:

```sql
-- Активные мутации с деталями для расследования
SELECT database, table, mutation_id, command, create_time, parts_to_do,
       is_done, latest_failed_part, latest_fail_time, latest_fail_reason
FROM system.mutations
WHERE is_done = 0
ORDER BY create_time;

-- Фоновые слияния: прогресс и загрузка
SELECT database, table, elapsed, round(progress * 100, 2) AS progress_pct,
       num_parts, formatReadableSize(total_size_bytes_compressed) AS compressed_size,
       memory_usage, result_part_name, is_mutation
FROM system.merges
ORDER BY elapsed DESC;

-- Алерт: мутация висит дольше 1 часа
SELECT count() AS stuck_mutations
FROM system.mutations
WHERE is_done = 0 AND create_time < now() - INTERVAL 1 HOUR;
```

**Алерты для SRE:**
- `system.mutations WHERE is_done = 0 AND parts_to_do > 0` — висячие мутации.
- `system.merges` растёт — backlog слияний, диск перегружен.
- `system.disks` — свободное место < 20% (см. **[Мониторинг](./clickhouse-monitoring.md)**).

### Настройки, влияющие на мутации и удаления

| Настройка | Что делает | SRE-заметка |
| :--- | :--- | :--- |
| `mutations_sync` | 0 — асинхронно (по умолчанию); 1 — дождаться на сервере; 2 — дождаться на всех репликах; 3 — дождаться активных | Использовать 2 для consistency-критичных удалений |
| `lightweight_deletes_sync` | То же, но только для lightweight delete; по умолчанию 2 (self-hosted), 1 (Cloud) | 0 для fire-and-forget удалений |
| `optimize_mutations_with_partition_pruning` | Авто-принуждение мутации только к нужным партициям | Включено по умолчанию; отключать только при необходимости |
| `min_age_to_force_merge_seconds` | Сливать части старше N секунд | Гарантирует физическое удаление строк после lightweight delete |
| `min_unreserved_disk_space_for_merge` | Резерв свободного места для слияний (байты) | Защищает от переполнения диска во время слияний |
| `merge_tree_clear_old_parts_interval_seconds` | Интервал очистки старых parts/WAL/mutations | Уменьшить при высокой частоте мутаций |

**Пример: защитить диск от переполнения во время слияний**
```sql
-- Оставить 10 ГБ неприкасаемыми для слияний
ALTER TABLE logs MODIFY SETTING min_unreserved_disk_space_for_merge = 10737418240;
```

**Пример: гарантированное удаление данных через срок**
```sql
-- Сливать части старше 24 часов — через сутки deleted-строки будут физически удалены
ALTER TABLE logs MODIFY SETTING min_age_to_force_merge_seconds = 86400;
```

### Очистка после удалений

Lightweight delete и мутации маркируют строки, но место на диске освобождается только при слиянии. Для принудительной очистки:

- `ALTER TABLE ... APPLY DELETED MASK` — удалить строки, помеченные lightweight delete.
- `OPTIMIZE TABLE ... FINAL CLEANUP` — для `ReplacingMergeTree`, удалить delete-строки (требует `allow_experimental_replacing_merge_with_cleanup = 1`).
- `ALTER TABLE ... APPLY PATCHES` — материализовать patch parts от lightweight `UPDATE`.
- Диагностика: `SELECT count() AS inactive_parts, formatReadableSize(sum(bytes_on_disk)) AS bytes_to_reclaim FROM system.parts WHERE table = 'logs' AND active = 0;` покажет части, ожидающие физического удаления.

### Перезагрузка конфигурации без остановки

```bash
# Без перезапуска сервера
clickhouse-client --query "SYSTEM RELOAD CONFIG"
# → (пустой вывод при успехе)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Мутация зависла (`parts_to_do` не уменьшается) | Нехватка I/O или места на диске, высокая нагрузка | Проверить `system.mutations`, `system.merges`; при необходимости `SYSTEM STOP MERGES`, затем `KILL MUTATION` |
| `DELETE FROM` выполняется очень долго | Большой объём данных; синхронный режим | `SET lightweight_deletes_sync = 0`; удалять партициями (`IN PARTITION`); для массовых удалений — `DROP PARTITION` |
| `OPTIMIZE ... FINAL` не завершается | Очень большая таблица, нехватка ресурсов | Отменить (`KILL QUERY`); не использовать `FINAL` на больших таблицах регулярно |
| `SELECT ... FINAL` медленный | Движок обрабатывает части особым образом | Избегать `FINAL` в запросах; использовать `argMax`/`anyLast` или дедупликацию в MV |
| `KILL QUERY` не завершает запрос | Запрос уже завершается или не найден | Проверить `system.processes`; использовать `SYNC` для подтверждения |
| `Replica is in read-only mode` после `DETACH` | Потеря связи с Keeper | `SYSTEM RESTORE REPLICA db.table`; проверить Keeper |
| Диск заполняется после `DELETE`/`ALTER UPDATE` | Строки помечены, но не удалены с диска (ждут merge) | `ALTER TABLE ... APPLY DELETED MASK`; `OPTIMIZE TABLE ... FINAL CLEANUP`; проверить `system.parts` на пустые части; `SYSTEM STOP MERGES` при экстренном случае |
| `APPLY DELETED MASK` не освобождает место | Мутация не завершилась или есть ошибка | Проверить `system.mutations` на `latest_fail_reason`; дождаться синхронизации реплик |
| `OPTIMIZE TABLE ... CLEANUP` не работает | Не включена настройка `allow_experimental_replacing_merge_with_cleanup` | `ALTER TABLE ... MODIFY SETTING allow_experimental_replacing_merge_with_cleanup = 1`; или использовать `APPLY DELETED MASK` |
| `SYSTEM RELOAD CONFIG` не применяет изменения | Конфиг в неверном пути или синтаксическая ошибка | Проверить `/etc/clickhouse-server/config.xml`; `SYSTEM RELOAD CONFIG` не перезагружает users/quotas — используйте `SYSTEM RELOAD USERS` для прав |

## Лучшие практики

1. **Предпочитайте `DELETE FROM` (lightweight) мутациям** для точечного удаления — это маркировка, а не перезапись частей.
2. **Не запускайте `OPTIMIZE ... FINAL` по расписанию** — фоновые слияния справляются; `FINAL` создаёт пик нагрузки.
3. **Избегайте `SELECT ... FINAL`** в продакшене — используйте `argMax`/`anyLast` или дедупликацию в материализованном представлении.
4. **Удаляйте старые данные партициями** (`DROP PARTITION`) — это мгновенная операция, в отличие от удаления строк.
5. **`KILL QUERY` — инструмент SRE** для снятия runaway-запросов; мониторьте `system.processes` в алертах.
6. **`FREEZE` перед любыми структурными изменениями** — мгновенный снапшот через hardlinks.
7. **`SYSTEM SYNC REPLICA`** перед переключением на реплику — гарантирует, что данные догнаны.
8. **Настройте `min_age_to_force_merge_seconds`** для таблиц с compliance-требованиями к удалению данных — гарантирует физическое удаление в предсказуемый срок.
9. **Контролируйте mutations backlog** — алерт на `system.mutations WHERE is_done = 0 AND create_time < now() - 1h` предотвращает наложение мутаций и блокировку слияний.
10. **Используйте `min_unreserved_disk_space_for_merge`** чтобы защищённое пространство не было занято слияниями — особенно важно для небольших дисков.
11. **После `DELETE FROM` следите за диском** — место освобождается не сразу. `APPLY DELETED MASK` или `OPTIMIZE TABLE ... FINAL CLEANUP` принудительно очищают.

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- Мутации и слияния — **[Архитектура](./clickhouse-architecture.md#процесс-слияния-merge)**.
- Бэкапы (FREEZE/FETCH) — **[Бэкапы и восстановление](./clickhouse-backup.md)**.
- Мониторинг мутаций и алерты — **[Мониторинг](./clickhouse-monitoring.md)**.
- Операционные процедуры — **[Эксплуатация](./clickhouse-operations.md)**.
- Refreshable MV (`SYSTEM REFRESH VIEW`) — **[Производительность](./clickhouse-performance.md#refreshable-materialized-views)**.

### Ресурсы

- [Документация: DELETE](https://clickhouse.com/docs/reference/statements/delete)
- [Документация: ALTER TABLE](https://clickhouse.com/docs/ru/sql-reference/statements/alter)
- [Документация: SYSTEM](https://clickhouse.com/docs/ru/sql-reference/statements/system)
- [Документация: OPTIMIZE TABLE](https://clickhouse.com/docs/reference/statements/optimize)
- [Документация: APPLY DELETED MASK](https://clickhouse.com/docs/reference/statements/alter/apply-deleted-mask)
- [Документация: lightweight delete](https://clickhouse.com/docs/concepts/features/operations/delete/lightweight-delete)
- [Настройки мутаций (mutations_sync, lightweight_deletes_sync)](https://clickhouse.com/docs/reference/settings/session-settings/mutations)
