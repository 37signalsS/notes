# Кросс-региональная отказоустойчивость PostgreSQL

**Актуально для:** PostgreSQL 14–18

## Определения

*   **Cross-region DR** — схема, при которой копия данных и/или возможность восстановления находятся в другом регионе/ДЦ (не просто другой стойке): защита от потери площадки.
*   **RPO по региону** — допустимые потери при потере всего региона. Определяется механизмом: WAL-архив в объектное хранилище (минуты, `archive_timeout`), streaming replica (секунды, async), sync replica (0, но latency коммита растёт на RTT регионов).
*   **RTO по региону** — время восстановления сервиса в другом регионе: promote standby (минуты) vs restore base backup + WAL replay (часы, зависит от объёма).
*   **WAL-архив offsite** — непрерывная выгрузка сегментов WAL в удалённое объектное хранилище; минимальный уровень cross-region защиты.
*   **Standby в другом регионе** — физическая реплика, получающая WAL через WAN; promote превращает её в Primary.
*   **Логическая репликация cross-region** — репликация выбранных таблиц между регионами; работает между разными мажорными версиями, но требует конфигурации публикаций/подписок.
*   **Latency budget** — бюджет задержки: sync-репликация через регионы добавляет RTT (десятки мс) к каждому коммиту; async — нет, но RPO > 0.

## Базовые концепции

### Три уровня cross-region защиты

| Уровень | Механизм | RPO | RTO | Стоимость |
| :--- | :--- | :--- | :--- | :--- |
| 1. WAL-архив offsite | `archive_command` → объектное хранилище | минуты (`archive_timeout`) | часы (restore + replay) | низкая |
| 2. Standby в другом регионе | streaming replication (async) | секунды | минуты (promote) | средняя |
| 3. Sync standby в другом регионе | `synchronous_standby_names` | 0 | минуты | высокая (latency) |

Уровень 1 обязателен всегда (это дешёвый минимум). Уровень 2 — стандарт для production. Уровень 3 — редко: RTT между регионами (10–100 мс) делает каждый коммит медленным; обычно синхронность применяют внутри региона, а между регионами — async.

### Физическая vs логическая репликация между регионами

*   **Физическая (streaming)**: побайтовая, весь кластер, одна мажорная версия, низкий overhead, promote за секунды. Стандарт для DR.
*   **Логическая**: выборочные таблицы, разные мажорные версии, можно фильтровать и трансформировать; но promote — не автоматический (нужно создавать публикации на новой стороне), и нет гарантии «весь кластер».
*   **Выбор**: DR «весь кластер» → физическая; миграция версий / selective replication / read-scale в другом регионе → логическая.

### Почему sync между регионами — почти всегда плохая идея

`synchronous_commit = remote_apply` через 50 мс RTT добавляет ≥50 мс к каждому коммиту. Для OLTP с тысячами TPS это кратно деградирует p99. Паттерн «zero data loss между регионами» обычно реализуется иначе: async standby + `synchronous_commit = on` внутри региона + принятие RPO в секунды между регионами.

## Практические сценарии

### Предварительные требования

1.  **Сеть**: VPN (IPSec/GRE) или выделенный сетевой канал между регионами; MTU учтён (WAN-инкапсуляция); `wal_receiver_timeout` настроен (дефолт 60с — при длительных WAN-разрывах реплика переподключается).
2.  **Права**: роль `replicator` с `REPLICATION` (см. [Настройка репликации](../Operations/replication_setup.md)).
3.  **Хранилище**: объектное хранилище для WAL-архива (для уровня 1).

### 1. WAL-архив в другой регион (уровень 1)

```ini
# postgresql.conf на Primary
archive_mode = on
archive_timeout = 60s          # нижняя граница RPO
archive_command = 'wal-g wal-push %p'   # wal-g поддерживает различные бэкенды
```
```bash
# Проверка: сегменты уходят в архив
wal-g wal-list | tail -3
# → 0000000100000000000000AB  2026-10-04T18:00:00Z
# → 0000000100000000000000AC  2026-10-04T18:01:00Z
```
Восстановление в другом регионе: base backup + `restore_command` из архива + `recovery_target_time` — см. [Бэкап и восстановление](./backup_and_recovery.md).

### 2. Standby в другом регионе (уровень 2)

```bash
# На standby (втором регионе): базовый бэкап через WAN
pg_basebackup -h primary.example.com -D /var/lib/pgsql/18/data \
  -U replicator -P -X stream -R
# → 123456/123456 kB (100%), 1/1 tablespace ...
# -R: записывает primary_conninfo и standby.signal
```
```ini
# postgresql.conf standby (регион 2)
primary_conninfo = 'host=primary.example.com port=5432 user=replicator application_name=dr_standby'
hot_standby = on
recovery_min_apply_delay = 0    # 0 для DR; задержка — защита от логических ошибок, но растёт RPO
wal_receiver_timeout = 120s     # терпимость к WAN-разрывам
```
```sql
-- На Primary: состояние кросс-региональной реплики
SELECT client_addr, state, sync_state, replay_lag, write_lag
FROM pg_stat_replication WHERE application_name = 'dr_standby';
-- → client_addr  | state    | sync_state | replay_lag | write_lag
-- → 203.0.113.10 | streaming | async    | 00:00:00.4 | 00:00:00.02
```

### 3. Promote standby в другом регионе (RTO)

```bash
# На standby (только если Primary потерян безвозвратно!)
pg_ctl promote -D /var/lib/pgsql/18/data
# → server promoting

# Проверка
psql -c "SELECT pg_is_in_recovery();"
# → pg_is_in_recovery
# → f
```
В HA-кластерах (например, Patroni) promote — автоматический (failover) или через `patronictl failover` (плановый). После promote: перестроить новый standby из нового Primary, перенастроить приложение (HAProxy/DNS), проверить WAL-архив продолжает писаться.

### 4. Логическая репликация cross-region (выборочные таблицы)

```sql
-- На Primary (регион 1)
CREATE PUBLICATION dr_pub FOR TABLE orders, customers;
-- → CREATE PUBLICATION

-- На standby (регион 2, может быть другой мажорной версии)
CREATE SUBSCRIPTION dr_sub
  CONNECTION 'host=primary.example.com dbname=myapp user=repl password=***'
  PUBLICATION dr_pub;
-- → CREATE SUBSCRIPTION

-- Лаг подписки
SELECT subname, pid, latest_end_lsn, latest_end_time
FROM pg_stat_subscription;
-- → subname | pid | latest_end_lsn | latest_end_time
-- → dr_sub  | 987 | 0/AB123456     | 2026-10-04 18:05:00
```

### 5. Измерение RPO/RTO (учение)

```bash
# RPO: сколько транзакций потеряется при потере Primary
psql -c "SELECT pg_current_wal_lsn() AS primary_lsn;"
# → primary_lsn
# На standby:
psql -c "SELECT pg_last_wal_replay_lsn() AS standby_lsn;"
# → standby_lsn
# RPO ≈ разница LSN (в байтах) / скорость генерации WAL
```
RTO замеряется на учении: время от «Primary недоступен» до «приложение пишет в новый Primary» — фиксировать в отчёте DR drill (см. [Аварийное восстановление](../Operations/disaster_recovery.md)).

## Валидация конфигурации DR

Перед включением cross-region DR проверьте ключевые параметры:

```sql
-- Проверка конфигурации репликации
SELECT name, setting FROM pg_settings
WHERE name IN ('archive_mode', 'archive_command', 'wal_level',
                'max_wal_senders', 'max_replication_slots', 'hot_standby');
-- → archive_mode  | on
-- → wal_level     | replica
-- → max_wal_senders | >= 1 + количество реплик
-- → max_replication_slots | >= количество реплик
-- → hot_standby  | on  (только на standby)
```

```bash
# Проверка archive_command (на Primary)
psql -c "SELECT name, setting FROM pg_settings WHERE name = 'archive_command';"
# → archive_command | wal-g wal-push %p
# Ручная проверка: archive_command должен возвращать код 0
```

## Мониторинг и алерты

```sql
-- Состояние реплик: lag по LSN и времени
SELECT client_addr, application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS sent_lag_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes,
       now() - pg_last_xact_replay_timestamp() AS replay_lag_time
FROM pg_stat_replication;
```

```sql
-- Слоты репликации: неактивные или с накопившимся WAL (риск переполнения pg_wal)
SELECT slot_name, active, slot_type,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal
FROM pg_replication_slots
WHERE active = false OR pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) > 1073741824; -- 1 GB порог
```

```sql
-- Статус WAL-архива: не заархивированные сегменты и ошибки
SELECT archived_txn, last_archived_wal, last_archived_time,
       failed_wal, last_failed_wal, last_failed_time,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), last_archived_lsn)) AS unarchived_wal
FROM pg_stat_archiver;
```

```sql
-- Лаг логической подписки (cross-region)
SELECT subname, pid,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), latest_end_lsn)) AS lag_bytes,
       EXTRACT(EPOCH FROM (now() - latest_end_time)) AS lag_seconds
FROM pg_stat_subscription
WHERE latest_end_time IS NOT NULL;
```

**Алерты (DevOps/SRE):**
- `replay_lag_time > 120s` на cross-region async реплике (WAN-джиттер допускается, но >2 мин — тревога)
- `active = false` в `pg_replication_slots` более 5 минут — реплика не подключена
- `retained_wal > 10 GB` — WAL накапливается, слот застрял
- `failed_wal > 0` в `pg_stat_archiver` — `archive_command` не работает
- `unarchived_wal > 1 GB` — архив отстаёт
- `lag_seconds > 300` на логической подписке — подписчик не успевает применять

## Устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `replay_lag` растёт на десятки минут | WAN пропуска/задержка | Проверить канал; `wal_receiver_timeout` настроить > RTT |
| Реплика не подключается (`state = connect`) | `pg_hba.conf` не настроен / DNS | Проверить запись `host Replication` в `pg_hba.conf`; проверить DNS/IP |
| `active = false` в `pg_replication_slots` | Реплика остановлена или слот не используется | Перезапустить реплику; если слот не нужен — `SELECT pg_drop_replication_slot(slot_name);` |
| `retained_wal` растёт >10 GB | Слот застрял, WAL не удаляется | Проверить, что реплика работает; если dead — `SELECT pg_drop_replication_slot(slot_name);` (остановит рост, требует pg_rewind после восстановления) |
| PostgreSQL "останавливает запись" | `archive_command` не работает | Исправить `archive_command`; для снятия блокировки — временно `archive_mode = off` + рестарт (только экстренно) |
| Sync репликация между регионами — latency коммита +50 мс | `synchronous_commit = remote_apply` через WAN | Отключить sync между регионами: `synchronous_standby_names = ''`; async между регионами + sync внутри региона |
| Logical replication lag растёт | Подписка не успевает применять | `max_parallel_maintenance_workers_per_subscription` + `max_parallel_workers`; проверить нагрузку на subscriber |
| Split-brain (два Primary) | Promote без потери старого Primary | Остановить старый Primary; `pg_rewind` с бывшего к новому; проверить DCS кворум |
| `recovery_target_time` восстанавливает в прошлое | Часовой пояс сервера | `timezone = 'UTC'` в `postgresql.auto.conf` или `AT TIME ZONE` |

## Лучшие практики

1.  **Минимум — WAL offsite**: `archive_mode = on` + архив в другой регион; без этого потеря площадки = потеря данных с момента последнего бэкапа.
2.  **Async между регионами, sync внутри**: синхронность через регионы убивает latency коммита; нулевые потери между регионами — почти всегда неоправданная цена.
3.  **`recovery_min_apply_delay` с умом**: задержка реплики (например, 1 час) защищает от `DROP TABLE` на Primary, но растёт RPO и не совместима с «быстрым promote» — для DR-реплики обычно 0.
4.  **Тестируйте promote**: RTO без учения — догадка; promote в другом регионе раз в квартал (на стенде или плановый switchover).
5.  **Мониторинг лага**: алерт на `replay_lag > порог SLO` для кросс-региональной реплики (порог больше, чем для intra-region — WAN-джиттер нормален).
6.  **Слоты репликации**: для standby используйте физические слоты (`primary_slot_name`), чтобы WAL не удалялся до получения; мониторить `active` и `pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)` в `pg_replication_slots` — неактивный слот или растущий `retained_wal_bytes` = реплика не доставляет WAL.
7.  **Документируйте процедуру promote**: кто принимает решение, как перенастраивается приложение, как восстанавливается второй регион после.
8.  **Cleanup**: удаляйте неиспользуемые репликационные слоты (`SELECT pg_drop_replication_slot(slot_name);`) — застрявший слот растягивает `pg_wal` до переполнения диска; при decommission DR-standby останавливайте её (`pg_ctl stop`) и удаляйте `standby.signal`/`primary_conninfo`, чтобы исключить split-brain.
9.  **Тестируйте recovery**: DR drill с восстановлением из WAL-архива не реже 1 раза в квартал; проверять целостность данных и фактические RPO/RTO.

## Пограничные случаи

*   **Разрыв WAN на час**: async standby отстаёт; при восстановлении — догоняет (WAL из `pg_wal` или архива); `wal_receiver_timeout` должен быть больше ожидаемого разрыва.
*   **Разные версии**: физическая репликация требует одинаковой мажорной версии (минорные могут отличаться, primary ≥ standby); логическая — разные мажорные.
*   **Большие объёмы**: `pg_basebackup` через WAN на TB-кластере — часы; используйте `wal-g`/`pgbackrest` с инкременталами и сжатием.
*   **Split-brain при promote**: если Primary «жив», но недоступен по сети, promote standby даёт два Primary — кворум DCS (Patroni/etcd) или ручная процедура с `pg_rewind` для расхождения.
*   **`archive_command` и недоступность хранилища**: при недоступности архива PostgreSQL **останавливает запись** (WAL не удаляется) — мониторить доступность хранилища как критическую.
*   **Логическая репликация и DDL**: DDL не реплицируется автоматически (только DML); схему в другом регионе мигрируют отдельно.
*   **Часовые пояса и `recovery_target_time`**: цель PITR задаётся в `timezone` сервера — при восстановлении в другом регионе указывайте явно `AT TIME ZONE` или UTC (см. [Часовые поясы](./timezone_handling.md)).

## Дополнительная информация

*   [Аварийное восстановление (DR)](../Operations/disaster_recovery.md) — RPO/RTO, уровни готовности, учения.
*   [Репликация](./replication.md) — физическая и логическая, слоты, синхронность.
*   [Настройка репликации](../Operations/replication_setup.md) — пошаговая настройка standby.
*   [High Availability (Patroni)](./high_availability.md) — автоматический failover, DCS.
*   [Бэкап и восстановление](./backup_and_recovery.md) — PITR, base backup.
*   [Обработка часовых поясов](./timezone_handling.md) — `recovery_target_time` и пояса.
*   [Официальная документация: Warm Standby](https://www.postgresql.org/docs/current/warm-standby.html)
*   [Официальная документация: Logical Replication](https://www.postgresql.org/docs/current/logical-replication.html)
*   [Официальная документация: WAL Архивирование](https://www.postgresql.org/docs/current/wal-archiving.html)
*   [Официальная документация: pg_replication_slots](https://www.postgresql.org/docs/current/catalog-pg-replication-slots.html)
*   [Официальная документация: Мониторинг репликации](https://www.postgresql.org/docs/current/monitoring-stats.html)
