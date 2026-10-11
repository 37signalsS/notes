# Аварийное восстановление PostgreSQL (Disaster Recovery)

**Актуально для:** PostgreSQL 14–18

## Определения

*   **Disaster Recovery (DR)** — набор процедур восстановления сервиса после катастрофического сбоя: потеря Primary, повреждение данных, потеря датацентра.
*   **RPO (Recovery Point Objective)** — максимально допустимый объём потерь данных, измеряется временем (например, «не более 5 минут»).
*   **RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса (например, «не более 30 минут»).
*   **DR drill (учение)** — плановая отработка восстановления на изолированном стенде; единственный способ проверить, что бэкап работает.
*   **Failover** — переключение на реплику при отказе Primary (автоматическое в Patroni).
*   **Switchover** — плановое переключение (обе стороны синхронны, потерь нет).
*   **Offsite backup** — копия бэкапа и WAL-архива вне площадки Primary (второй ДЦ, объектное хранилище).

## Базовые концепции

### RPO и RTO: откуда берутся числа

*   **RPO** определяется архивацией WAL: `archive_timeout` задаёт нижнюю границу RPO (сегменты закрываются досрочно, но занимают полные 16 MB — значения порядка минуты обычно разумны). Асинхронная репликация добавляет потенциальную потерю записей при failover; синхронная — нулевые потери ценой latency коммита.
*   **RTO** определяется путём восстановления: promote standby (секунды–минуты) vs restore из base backup + WAL replay (минуты–часы, зависит от объёма и `recovery_max_sync_rate`).

### Уровни DR-готовности

| Уровень | Механизм | RPO | RTO |
| :--- | :--- | :--- | :--- |
| 1. Бэкап + PITR | `pg_basebackup` + WAL-архив | минуты (`archive_timeout`) | минуты–часы |
| 2. Standby в другом ДЦ | Streaming replication + promote | секунды (async) / 0 (sync) | минуты |
| 3. HA-кластер (Patroni) | Автоматический failover | секунды / 0 | секунды |
| 4. Multi-master / распределённый SQL | Citus, CockroachDB и др. | зависит от реализации | зависит |

### Что должно быть в DR-плане

1.  Контакты и эскалация (кто принимает решение о promote).
2.  Целевые RPO/RTO по каждой базе.
3.  Ссылки на runbook-ы: [failover](../Concepts/high_availability.md), [PITR](../Concepts/backup_and_recovery.md), [восстановление после повреждений](../Concepts/corruption_recovery.md), [runbook](./troubleshooting_runbook.md).
4.  Инвентарь: где хранятся бэкапы, WAL-архив, какие учётные данные.
5.  Каденс учений и критерии успеха.

## Предпосылки

1.  **Архивация WAL включена:** `archive_mode = on` и `archive_command` копирует сегменты в offsite-хранилище (тюремная лента, второй ДЦ, NFS-монтирование). Проверка: `SELECT archived_count, failed_count FROM pg_stat_archiver;` — `failed_count` должен быть 0.
2.  **Базовый бэкап доступен:** `pg_basebackup`, pgBackRest, или WAL-G — хотя бы один свежий base backup на offsite. Регулярная проверка целостности валидируется через restore-тест (см. [backup_validation.md](../../Concepts/backup_validation.md)).
3.  **Standby/replica настроен:** streaming replication с `wal_level = replica` (или `logical` для pglogical); `max_wal_senders ≥ 3`, `max_replication_slots ≥ 3`.
4.  **DCS для автоматического failover:** etcd или Consul с кворумом (3 узла минимум); Patroni настроен с `use_pg_rewind = true` и `standby_cluster = true`.
5.  **Инструменты:** `pg_basebackup`, `pg_rewind`, `pg_verifybackup`, `pg_resetwal`, `pg_controldata`, `patronictl` — доступны на всех узлах.
6.  **Права:** `SUPERUSER` или роль с `pg_monitor` + `pg_read_all_settings` для мониторинга; `pg_signal_backend` для `pg_terminate_backend`; `replication` для `pg_basebackup`.
7.  **Мониторинг:** алерты на `pg_stat_archiver.failed_count > 0`, `pg_stat_replication` (слоты inactive > 5 мин), `node_filesystem_free` (< 15% на pg_wal).
8.  **Синхронизация времени:** `ntpd`/`chronyd` на всех узлах; `recovery_target_time` и checkpoint LSN требуют согласованного времени.

## Практические сценарии

### Сценарий: Учение восстановления (restore drill)

Проводится на изолированном стенде (не на production-реплике) не реже 1 раза в квартал.

```bash
# 1. Остановить стенд, очистить PGDATA
# 2. Восстановить base backup
pg_basebackup -D /var/lib/pgsql/restore/data --restore=... # или копия из архива

# 3. Настроить recovery на произвольную точку
cat > /var/lib/pgsql/restore/data/postgresql.auto.conf <<EOF
restore_command = 'cp /archive/%f %p'
recovery_target_time = '2026-10-04 12:00:00+03'
EOF
touch /var/lib/pgsql/restore/data/recovery.signal

# 4. Стартовать и проверить
pg_ctl -D /var/lib/pgsql/restore/data start
psql -c "SELECT now(), pg_is_in_recovery();"
# → now                 | pg_is_in_recovery
# → 2026-10-04 12:00:01 | f
```

**Критерий успеха:** данные на `recovery_target_time` целы, приложение проходит smoke-тест. Фиксируется фактический RTO — он сравнивается с целевым. Алгоритм проверки целостности бэкапов — в [Проверке бэкапов](../../Concepts/backup_validation.md).

### Сценарий: Полная потеря Primary (failover)

**С Patroni:** failover автоматический (DCS: etcd/Consul; кворум 3 узлов). Проверить:

```bash
patronictl list          # состояние кластера
patronictl failover      # ручной switchover/failover
```

**Без оператора (ручной promote):**

```bash
# На standby
pg_ctl promote -D /var/lib/pgsql/18/standby
psql -c "SELECT pg_is_in_recovery();"
# → pg_is_in_recovery
# → f
```

**Возврат бывшего Primary** — `pg_rewind` (быстрая синхронизация без полной перебазы, если бывший Primary не повреждён):

```bash
pg_rewind --source-server="host=new_primary port=5432 dbname=postgres" \
  --target-pgdata=/var/lib/pgsql/18/data
```

Детали: [Репликация](../Concepts/replication.md), [High Availability](../Concepts/high_availability.md).

### Сценарий: Потеря датацентра (восстановление из offsite)

1.  Поднять новый сервер в резервном ДЦ (инфраструктура как код — Terraform/Ansible).
2.  Установить PostgreSQL той же мажорной версии (см. [Установку на RHEL](./installation_rhel.md)).
3.  Восстановить последний base backup из offsite-хранилища.
4.  Настроить `restore_command` на offsite WAL-архив, `recovery.signal`.
5.  Достичь `recovery_target` (или replay до конца WAL).
6.  Переключить приложение (DNS/балансировщик), проверить RPO: `SELECT max(committed_at) FROM audit;` против ожидаемого.
7.  Построить новую HA-цепочку (standby + WAL-архивация) до восстановления основного ДЦ.

### Сценарий: Логическая ошибка (DROP TABLE, UPDATE без WHERE)

PITR восстанавливает **весь кластер** на точку до ошибки — отдельную таблицу восстановить напрямую нельзя:

1.  Восстановить кластер в отдельный каталог до `recovery_target_time` (алгоритм — в [Бэкапе и восстановлении](../Concepts/backup_and_recovery.md#восстановление-отдельной-таблицы-из-pitr)).
2.  Выгрузить нужную таблицу из восстановленного кластера (`pg_dump -t orders`).
3.  Загрузить в production (`psql` / `COPY`).
4.  Удалить временный кластер.

Защита помимо PITR: отложенный standby (`recovery_min_apply_delay`), `pg_dump` перед DDL, расширенные права (`MAINTAIN` вместо суперправ).

### Сценарий: Повреждение данных (коррупция)

1.  `amcheck` / `pg_amcheck` — локализация логической коррупции (онлайн, блокировка уровня SELECT).
2.  Восстановление из бэкапа с PITR — предпочтительный путь.
3.  `pg_resetwal` — **только** если старта нет и PITR невозможен (последнее средство).

Детали: [Восстановление после повреждений](../Concepts/corruption_recovery.md).

## Операции и команды

| Операция | Команда | Когда применяется |
| :--- | :--- | :--- |
| Создание base backup | `pg_basebackup -D /var/lib/pgsql/data --wal-method=stream` | Периодический (квартальный) или перед схемой смены |
| Архивация WAL | `archive_command = 'cp %p /mnt/wal_archive/%f'` | В `postgresql.conf` для PITR |
| Валидация бэкапа | `pg_verifybackup -n /var/lib/pgsql/data` | После каждого base backup |
| Настройка PITR recovery | `restore_command = 'cp /mnt/wal_archive/%f %p'` + `recovery_target_time = '...'` + `touch recovery.signal` | Перед стартом в recovery-режиме |
| Запуск в recovery | `pg_ctl -D /var/lib/pgsql/restore/data start` | После настройки recovery |
| Promoter standby | `pg_ctl promote -D /var/lib/pgsql/data` (или `SELECT pg_promote();`) | Failover без Patroni |
| Возврат бывшего Primary | `pg_rewind --source-server="host=new_primary port=5432 dbname=postgres" --target-pgdata=/var/lib/pgsql/data` | После failover, когда старый Primary не повреждён |
| Сброс WAL | `pg_resetwal /var/lib/pgsql/data` | Последнее средство при повреждении pg_wal и невозможности PITR |
| Проверка контроля | `pg_controldata /var/lib/pgsql/data \| grep -E 'TimeLineID|Latest|Next'` | Диагностика перед recovery |

> **Правило:** `pg_rewind` требует либо `--data-checksums` при `initdb`, либо `wal_log_hints = on` в `postgresql.conf`. Без этого `pg_rewind` удаляет и заново синхронизирует весь кластер.

## Валидация и проверка

**Критерии успеха по сценариям:**

1.  **Restore drill:** данные на `recovery_target_time` целы; приложение проходит smoke-test; фиксируется фактический RTO — он сравнивается с целевым.
2.  **Failover:** новый лидер отвечает `SELECT pg_is_in_recovery() → f`; приложение переподключается (через DNS или балансировщик); RPO = 0 для sync, RPO ≤ async lag для async.
3.  **DC loss:** приложение пишет в новый Primary; `SELECT max(committed_at) FROM audit` — проверка, что пропущенный промежуток ≤ RPO.
4.  **Логическая ошибка:** таблица из PITR-восстановленного кластера восстановлена в production; данные соответствуют состоянию до ошибки.
5.  **Повреждение данных:** `data_checksums` обнаруживает повреждение; кластер не стартует без PITR; восстановление из бэкапа подтверждено `pg_verifybackup`.

**Методология DR-учения:**

1.  Зафиксировать baseline: RPS, p99 latency, `pg_stat_archiver`, `pg_stat_replication`.
2.  Инъекция: имитировать отказ (kill primary, выключить ДЦ, DROP TABLE).
3.  Восстановление: выполнить сценарий из runbook по шагам.
4.  Проверить критерии выше; зафиксировать фактический RTO и RPO.
5.  Очистка (см. ниже); возврат к baseline.
6.  Зафиксировать: что сработало, что не сработало, `found gaps` → обновить runbook.

## Очистка и откат

**Универсальная процедура после DR-учения:**

1.  **Временные кластеры:** остановить и удалить PITR-восстановленный кластер (`pg_ctl -D /tmp/restore/data stop && rm -rf /tmp/restore/data`).
2.  **Табличные данные:** если таблица была загружена в production из PITR — очистить staging-таблицу.
3.  **Сетевые правила:** если использовались `iptables` для имитации изоляции — `sudo iptables -F INPUT`.
4.  **Тестовые файлы:** удалить временные файлы (`sudo rm /var/lib/postgresql/fill`).
5.  **Проверка baseline:** убедиться, что метрики вернулись к baseline (RPS, latency, `pg_stat_replication`).
6.  **Документировать:** зафиксировать `recovery_time`, `RTO_actual`, `RPO_actual`, `found gaps` в runbook.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| PITR не стартует повторно | `recovery_target_action = shutdown` оставил `recovery.signal` | Настроить новый target перед стартом; `recovery.signal` руками не удалять |
| `WAL segment ... has already been removed` | Медленный бэкап / малый `max_wal_size` | Слот репликации (`--create-slot`), `wal_keep_size`, `max_slot_wal_keep_size` |
| Restore занимает часы | Нет параллелизма, малый `maintenance_work_mem` | `pg_restore -j 8`, `maintenance_work_mem` 2–4 GB |
| Восстановленный кластер расходится с ожиданиями | WAL-архив неполный (разрыв retention) | Проверить `pg_stat_archiver` и целостность цепочки сегментов |

## Лучшие практики

1.  **Бэкап без проверенного восстановления не является бэкапом** — DR drill обязателен.
2.  **Правило 3-2-1**: 3 копии, 2 носителя, 1 offsite.
3.  **WAL-архив offsite** — иначе потеря площадки = потеря данных после последнего base backup.
4.  **Шифровать offsite-копии** (см. [Безопасность бэкапов](../../Concepts/backup_security.md)).
5.  **Автоматизировать restore-дриллы** — скрипт поднимает кластер из архива и прогоняет smoke-тест.
6.  **Замерять фактический RTO/RPO** на учениях и сравнивать с целевыми.
7.  **Документировать решения** — кто и когда принимает решение о promote, коммуникация со стейкхолдерами.
8.  **Тестировать и pg_rewind** на стенде — он критичен для быстрого возврата бывшего мастера.

## Пограничные случаи

*   **`recovery_target_action = pause`** (default в PG 12+): recovery останавливается на target, а не завершается. Возобновить: `SELECT pg_wal_replay_resume();`. Если забыть — кластер остаётся в read-only.
*   **Неполный WAL-архив:** PITR останавливается на `WAL segment ... has already been removed`. Найти последний валидный сегмент через `pg_controldata`; выполнить PITR до него. Алгоритм — в [backup_and_recovery.md](../Concepts/backup_and_recovery.md).
*   **`pg_rewind` не срабатывает после длительного downtime:** старый WAL на бывшем Primary потерян. Решение: снять новую `basebackup` (`pg_basebackup`) вместо `pg_rewind`; ручной «приклеивание» узла к кластеру недопустимо.
*   **Split-brain с обоими лидерами:** если DCS недоступен и два узла стали Primary — остановить второй узел, выполнить `pg_resetwal` на его данных, затем `pg_rewind` или base backup. Никогда не пишете в оба узла одновременно.
*   **Failover при `wal_level = replica` + логическая репликация:** после promote логические слоты на старом Primary становятся недоступными; пересоздать их на новом лидере.
*   **Восстановление в другой каталог:** `pg_basebackup` + PITR в `/tmp/restore/` — убедиться что `postgresql.auto.conf` не содержит конфликтных настроек (listen_addresses, port) от исходного кластера.
*   **DR после major upgrade:** PITR восстанавливает на старую мажорную версию; для переноса на новую — использовать `pg_upgrade` после recovery, либо PITR на новый каталог с `pg_upgrade` внутри recovery.

## Дополнительная информация

*   [Бэкап и восстановление](../Concepts/backup_and_recovery.md) — PITR, `pg_basebackup`, архивация WAL
*   [Проверка целостности бэкапов](../../Concepts/backup_validation.md) — валидация восстановлением
*   [High Availability](../Concepts/high_availability.md) — Patroni, DCS, split-brain
*   [Репликация](../Concepts/replication.md) — `pg_rewind`, отложенный standby
*   [Восстановление после повреждений](../Concepts/corruption_recovery.md) — amcheck, `pg_resetwal`
*   [Диагностический runbook](./troubleshooting_runbook.md) — разбор инцидентов
*   [Ёмкостное планирование](./capacity_planning.md) — RPO/RTO и объём архива
*   [Методология SLO/SLI и инцидент-менеджмент](../../../Concepts/sre_concepts_main.md)
*   [Официальная документация: Backup and Recovery](https://www.postgresql.org/docs/current/backup.html)
