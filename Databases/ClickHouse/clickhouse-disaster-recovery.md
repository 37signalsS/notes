# ClickHouse — Отказоустойчивость и аварийное восстановление

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**DR (Disaster Recovery)** — стратегия и процедуры восстановления после катастрофического отказа (потеря ЦОД, региона).

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных (например, 5 минут).

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления (например, 1 час).

**Cross-DC** — репликация между центрами обработки данных (географически разнесёнными).

**Multi-cluster** — несколько независимых кластеров ClickHouse, синхронизированных через `clickhouse-copier` или репликацию между кластерами.

**Backup** — копия данных для восстановления; в ClickHouse — через `BACKUP`/`RESTORE` или `clickhouse-backup`.

**Keeper quorum** — большинство узлов сервиса координации (2 из 3 или 3 из 5); потеря кворума переводит кластер в read-only.

## Основные концепции

### Уровни отказоустойчивости

| Уровень | Механизм | RPO | RTO |
| :--- | :--- | :--- | :--- |
| **Репликация в кластере** | `ReplicatedMergeTree` | 0 (с `insert_quorum`) | Секунды (автоматический failover) |
| **Межкластерная репликация** | `clickhouse-copier` / репликация между кластерами | Минуты | Минуты–часы |
| **Бэкапы** | `BACKUP`/`RESTORE`, `clickhouse-backup` | Часы–сутки | Часы |
| **Cross-DC** | Репликация в другой ЦОД | Минуты | Часы |

### Архитектура DR

```
[ЦОД A]                          [ЦОД B]
Shard1-R1 ──replicate──> Shard1-R2     (внутри кластера)
     │                        │
     └──clickhouse-copier─────┘          (между кластерами)
```

**Варианты cross-DC:**
1. **Репликация между кластерами** — `ReplicatedMergeTree` с Keeper в каждом ЦОД; реплики в другом ЦОД — async.
2. **`clickhouse-copier`** — периодическое копирование данных между кластерами.
3. **Бэкапы в другой ЦОД** — `clickhouse-backup` + S3/диск в другом регионе.

### RPO и insert_quorum

- **RPO = 0:** `insert_quorum = N` (синхронная запись на N реплик).
- **RPO = минуты:** async-репликация + `clickhouse-copier` каждые 5–15 минут.
- **RPO = часы:** ежедневные бэкапы.

## Практические сценарии

### Стратегия DR для production

```sql
-- 1. Репликация внутри кластера (RPO=0)
CREATE TABLE events_local ON CLUSTER '{cluster}' (
    event_time DateTime,
    event_id UInt64,
    payload String
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/events', '{replica}')
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, event_id);

-- 2. Синхронная запись (RPO=0)
SET insert_quorum = 2;
INSERT INTO events VALUES (now(), 1, 'test');
```

### Бэкап в другой ЦОД

```bash
# Создание бэкапа
clickhouse-backup create --backup-name="dr_$(date +%Y%m%d)"

# Загрузка в S3 (другой регион)
clickhouse-backup upload dr_20261004

# Восстановление
clickhouse-backup download dr_20261004
clickhouse-backup restore dr_20261004
```

### Мониторинг DR

```sql
-- Задержка репликации
SELECT database, table, absolute_delay, queue_size
FROM system.replicas
WHERE absolute_delay > 60;

-- Статус Keeper
SELECT * FROM system.zookeeper_connection;

-- Очередь репликации
SELECT * FROM system.replication_queue
WHERE last_exception != '';
```

### DR Runbook

**Сценарий: потеря ЦОД A**

1. **Оценить ситуацию:** проверить `system.replicas` — какие реплики недоступны.
2. **Переключить трафик** на ЦОД B (обновить DNS/HAProxy).
3. **Проверить кворум Keeper:** если Keeper в ЦОД A потерян, убедиться, что в ЦОД B есть кворум (нужен нечётный ансамбль или 2+ узла в каждом ЦОД).
4. **Восстановить запись:** если кворум потерян — восстановить Keeper из снапшотов.
5. **Догнать репликацию:** `SYSTEM SYNC REPLICA` после восстановления.

**Сценарий: повреждение данных**

1. Остановить запись в таблицу.
2. Восстановить из бэкапа: `RESTORE TABLE events FROM 'backup_name'`.
3. Догнать репликацию с момента бэкапа (replay из Kafka/CDC).

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Кластер read-only | Потеря кворума Keeper | Восстановить Keeper; проверить `system.zookeeper_connection` |
| Реплика отстаёт | Сеть или диск | Проверить `absolute_delay`, `system.replication_queue` |
| Бэкап не создаётся | Нет места на диске | Очистить старые бэкапы; увеличить диск |
| Восстановление медленное | Большой объём | Восстанавливать параллельно по партициям |
| Cross-DC лаг | Высокая задержка сети | Увеличить `operation_timeout_ms`; использовать `clickhouse-copier` |

## Лучшие практики

1. **RPO/RTO** — определить до проектирования; выбрать механизм под них.
2. **`insert_quorum`** — для RPO=0 на критичных данных.
3. **Keeper в разных ЦОД** — нечётный ансамбль (3 или 5) с узлами в разных ЦОД.
4. **Бэкапы** — ежедневные + тестовое восстановление раз в квартал.
5. **DR drill** — раз в квартал отрабатывать сценарий потери ЦОД.
6. **Мониторинг** — алерты на `absolute_delay`, `queue_size`, потерю кворума.
7. **`clickhouse-copier`** — для межкластерной репликации с контролем нагрузки.

## Дополнительная информация

### Смежные темы

- Бэкапы и восстановление — **[Бэкапы и восстановление](./clickhouse-backup.md)**.
- Кластерное управление — **[Кластерное управление](./clickhouse-cluster.md)**.
- Мониторинг — **[Производительность](./clickhouse-performance.md)**.

### Ресурсы

- [Документация: Backup](https://clickhouse.com/docs/operations/backup)
- [Документация: High Availability](https://clickhouse.com/docs/operations/high-availability)
