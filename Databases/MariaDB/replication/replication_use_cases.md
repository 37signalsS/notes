# Сценарии использования репликации MariaDB

**Актуально для:** MariaDB 11.4 LTS / 12.3 LTS

## Определения

*   **Read scaling** — масштабирование чтения: направление read-запросов на реплики, запись — на источник.
*   **Backup offloading** — снятие нагрузки бэкапов с источника: бэкапы выполняются на реплике.
*   **DR (Disaster Recovery)** — восстановление после аварии площадки: реплика в другом ЦОД.
*   **Analytics / Reporting** — аналитические запросы на реплике, не мешая OLTP на источнике.
*   **Testing / Staging** — тестирование на реплике с продакшен-данными.
*   **CDC (Change Data Capture)** — захват изменений из binlog (MaxScale Binlog Router, Debezium).

## Базовые концепции

### Read scaling

Реплики обслуживают read-запросы, снижая нагрузку на источник.

**Требования:**
*   Приложение или прокси (MaxScale Read/Write Split, HAProxy) маршрутизирует запросы.
*   Реплика должна быть «достаточно свежей» — лаг влияет на консистентность чтения.
*   `read_only = ON` на репликах.

**Ограничения:**
*   Чтение с отставанием (eventual consistency) — реплика может не содержать последней записи.
*   Для критичных чтений (после записи) — читать с источника или использовать полусинхронную репликацию.

### Backup offloading

Бэкапы выполняются на реплике, не нагружая источник.

**Паттерн:**
1.  На реплике: `STOP REPLICA;` (или `FLUSH TABLES WITH READ LOCK` для консистентности).
2.  Выполнить бэкап (`mariadb-backup` или `mariadb-dump`).
3.  `START REPLICA;`.

**Преимущества:**
*   Источник не нагружается I/O бэкапа.
*   Бэкап с реплики — точка восстановления, независимая от источника.

**Важно:**
*   Для физических бэкапов (`mariadb-backup`) остановите репликацию или используйте `--safe-slave-backup` (аналог в Percona XtraBackup).
*   Запишите GTID-позицию (`gtid_slave_pos`) для PITR.

### DR (Disaster Recovery)

Реплика в другом ЦОД для восстановления после аварии.

**Паттерн:**
*   Асинхронная репликация через WAN (сжатие: `slave_compressed_protocol = ON`).
*   Отложенная реплика (`SOURCE_DELAY`) — защита от логических ошибок.
*   Полусинхронная внутри региона, асинхронная между регионами.

**RPO/RTO:**
*   RPO > 0 (асинхронность) — потеря последних транзакций.
*   RTO: минуты (ручной failover) или секунды (Orchestrator/MaxScale).

### Analytics / Reporting

Тяжёлые аналитические запросы на реплике.

**Паттерн:**
*   Реплика с `read_only = ON`, обслуживающая BI/аналитику.
*   Фильтрация (`replicate-do-db`) — реплицировать только нужные БД.
*   Параллельная репликация — чтобы аналитика не отставала.

**Ограничения:**
*   Аналитические запросы нагружают реплику — может расти лаг.
*   Используйте отдельную реплику для аналитики (не ту, что для read scaling).

### Testing / Staging

Реплика с продакшен-данными для тестирования.

**Паттерн:**
*   Реплицировать подмножество данных (фильтрация).
*   Остановить репликацию после синхронизации — статичный снапшот.
*   Маскирование чувствительных данных (если требуется).

### CDC (Change Data Capture)

Захват изменений из binlog для интеграции с другими системами.

**Инструменты:**
*   **MaxScale Binlog Router** — репликация binlog в Kafka/другие системы. Подробнее: **[Binlog Router](../MaxScale/maxscale_binlogrouter.md)**.
*   **Debezium** — CDC через binlog (требует `binlog_format = ROW`).

## Практические сценарии

### Сценарий 1: Read scaling через MaxScale

```ini
# maxscale.cnf
[RW-Split-Service]
type=service
router=readwritesplit
servers=server1,server2,server3
user=maxscale_user
password=***
max_replication_lag=30   # не направлять чтение на реплики с лагом > 30s
```

### Сценарий 2: Бэкап с реплики

```bash
# На реплике
mysql -u root -p
```

```sql
-- Остановить репликацию для консистентности
STOP REPLICA;
-- Записать GTID-позицию для PITR
SELECT @@gtid_slave_pos;
```

```bash
# Физический бэкап
mariadb-backup --backup \
    --target-dir=/backup/replica_$(date +%Y%m%d) \
    --user=backup_admin --password=***

# Вернуть репликацию
mysql -u root -p -e "START REPLICA;"
```

> **Примечание:** для `mariadb-backup` на реплике рекомендуется останавливать репликацию или использовать `--safe-slave-backup` (в Percona XtraBackup), чтобы избежать несогласованности.

### Сценарий 3: DR-реплика в другом ЦОД

```ini
# На DR-реплике
[mariadb]
slave_compressed_protocol = ON
slave_net_timeout = 120
read_only = 1
# Отложенная реплика для защиты от логических ошибок
# SOURCE_DELAY настраивается через CHANGE REPLICATION SOURCE TO
```

```sql
-- Отложенная DR-реплика (30 минут)
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST='source_ip',
    SOURCE_USER='repl_user',
    SOURCE_PASSWORD='***',
    SOURCE_USE_GTID=slave_pos,
    SOURCE_DELAY=1800;
START REPLICA;
```

### Сценарий 4: Аналитическая реплика с фильтрацией

```ini
# На аналитической реплике
[mariadb]
replicate-do-db = app_data
replicate-do-db = analytics
read_only = 1
slave_parallel_threads = 8
slave_parallel_mode = 'optimistic'
```

### Сценарий 5: Testing-реплика (статичный снапшот)

```sql
-- Синхронизировать и остановить репликацию
STOP REPLICA;
RESET REPLICA ALL;
-- Реплика теперь содержит статичный снапшот продакшен-данных
-- Тестируйте без влияния на продакшен
```

## Типовые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Чтение устаревших данных | Лаг реплики | `max_replication_lag` в MaxScale; читать с источника для критичных данных |
| Бэкап с реплики несогласован | Репликация работает во время бэкапа | `STOP REPLICA` перед бэкапом или `--safe-slave-backup` |
| DR-реплика отстаёт | WAN bandwidth недостаточен | Сжатие (`slave_compressed_protocol`); увеличьте bandwidth |
| Аналитика роняет лаг | Тяжёлые запросы на реплике | Отдельная реплика для аналитики; параллельная репликация |
| Testing-реплика влияет на продакшен | Репликация продолжает работать | `STOP REPLICA` после синхронизации |

## Best Practices

1.  **Read scaling** — прокси (MaxScale) с `max_replication_lag`; критичные чтения — с источника.
2.  **Backup offloading** — `STOP REPLICA` перед бэкапом; записывайте `gtid_slave_pos`.
3.  **DR** — сжатие для WAN; отложенная реплика для защиты от логических ошибок.
4.  **Analytics** — отдельная реплика; фильтрация по БД; параллельная репликация.
5.  **Testing** — статичный снапшот (`STOP REPLICA`); маскирование данных.
6.  **CDC** — MaxScale Binlog Router или Debezium; `binlog_format = ROW`.

## Дополнительная информация

### См. также
- **[Обзор репликации](./overview.md)** — топологии и ограничения.
- **[Отложенная репликация](./delayed_replication.md)** — SOURCE_DELAY для DR.
- **[Фильтрация](./filtering.md)** — репликация подмножества данных.
- **[Read/Write Split (MaxScale)](../MaxScale/maxscale_readwritesplit.md)** — маршрутизация чтения.
- **[Binlog Router (MaxScale)](../MaxScale/maxscale_binlogrouter.md)** — CDC.
- **[Резервное копирование](../backup_and_recovery.md)** — бэкапы и PITR.
