# Тюнинг производительности

## Cassandra: JVM Heap

```bash
# Рекомендация: Heap не более 8 GB для Cassandra
# Файл /etc/cassandra/jvm.options
-Xms8G
-Xmax8G

# Использование G1GC (рекомендуется)
-XX:+UseG1GC
-XX:G1RSetUpdatingPauseTimePercent=5
-XX:MaxGCPauseMillis=300
```

---

## ScyllaDB: I/O и память

ScyllaDB автоматически оптимизирует использование ресурсов, но ключевые параметры:

```yaml
# scylla.yaml (ScyllaDB)
# Количество шардов (по умолчанию = кол-во ядер)
developer_mode: false

# Лимит памяти для ScyllaDB (рекомендуется 80% RAM)
memory: 32G
```

```bash
# Тюнинг I/O планировщика (ScyllaDB)
# Проверка текущего планировщика
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] none kyber

# Установка recommended для SSD
echo mq-deadline | sudo tee /sys/block/sda/queue/scheduler
```

---

## Диагностика Tombstones (Надгробий)
Надгробия — это маркеры удаления. При чтении Cassandra вынуждена сканировать их, что замедляет запросы и может вызвать `TombstoneOverwhelmingException`.
- **Проверка:** `nodetool cfstats` -> `Number of keys (estimate)`. Если размер на диске растет, а ключей мало — у вас много надгробий.
- **Тюнинг:** Уменьшение `gc_grace_seconds` допустимо только если вы уверены, что Repair проходит чаще этого срока.

```sql
-- Проверка количества Tombstones через запрос
SELECT * FROM user_events
WHERE user_id = 550e8400-e29b-41d4-a716-446655440000
ALLOW FILTERING;  -- ВНИМАНИЕ: антипаттерн! Только для диагностики

-- В логах будет:
-- WARNING: Read 1000 live rows and 5000 tombstone cells
-- Tombstone span: 5000
```

---

## Антипаттерны (Чего НЕЛЬЗЯ делать)
- **ALLOW FILTERING:** Приводит к полному сканированию кластера. Если вы его используете — ваша модель данных неверна.
- **Большие разделы (>100 МБ):** Приводят к огромным паузам GC в Cassandra и нагрузке на диск в обоих СУБД.
- **Кросс-партиционные батчи (`BEGIN BATCH`):** Использовать только для атомарности внутри одного раздела. Для разных разделов это создает узкое место на координаторе.
- **Листинг всех данных без Partition Key:** `SELECT * FROM table` без `WHERE` сканирует весь кластер. Всегда указывайте Partition Key.
- **Высокочастотные Lightweight Transactions:** Paxos-операции масштабируются плохо. Используйте только для атомарных проверок.

---

## См. также
- **[Архитектура: Cassandra vs ScyllaDB](./architecture.md)** — Seastar, JVM, GC.
- **[Обслуживание и эксплуатация](./operations.md)** — Compaction, Tombstones.
- **[Мониторинг и observability](./monitoring.md)** — метрики производительности.
