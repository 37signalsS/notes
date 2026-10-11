# Pgpool-II: пулинг, балансировка и HA

**Актуально для:** Pgpool-II 4.3–4.5 / PostgreSQL 14–18

## Определения

*   **Pgpool-II** — middleware между клиентами и серверами PostgreSQL: пул соединений, балансировка read-запросов, автоматический failover, (опционально) репликация.
*   **PCP** — управляющий интерфейс Pgpool-II (по умолчанию порт **9898**): `show pool_nodes`, `pcp_proc_count` и др.
*   **Watchdog** — подсистема HA Pgpool-II: heartbeat между узлами Pgpool-II (UDP **9694**), управление виртуальным IP, кворум при failover.
*   **Режим кластеризации** — как Pgpool-II трактует бэкенды: `raw` (одиночный сервер), `master/slave` (streaming/logical/slony), `native replication` (встроенная репликация Pgpool-II), `streaming replication` (подвид master/slave).
*   **Load balancing** — распределение `SELECT` между бэкендами, когда результат одинаков на любом из них.
*   **Online recovery** — восстановление отставшего/нового бэкенда без остановки пула (follow/attach).

## Базовые концепции

### Архитектура

```
Клиенты → Pgpool-II (9999) → PostgreSQL Primary (5432)
                            → PostgreSQL Standby  (5432)
PCP (9898) — управление; Watchdog (9000 TCP / 9694 UDP) — HA пула
```

Pgpool-II работает как прокси: клиент видит один порт, Pgpool-II держит пул соединений к бэкендам и маршрутизирует запросы.

### Pgpool-II vs PgBouncer vs Patroni + HAProxy

| Задача | PgBouncer | Pgpool-II | Patroni + HAProxy |
| :--- | :--- | :--- | :--- |
| Пул соединений | Да (специализированный, транзакционный/сеансовый) | Да | Нет (HAProxy — TCP-прокси) |
| Балансировка read | Нет | Да | HAProxy — да (по настройке) |
| Авто-failover БД | Нет | Да (failover_command) | Да (DCS: etcd/Consul) |
| Репликация | Нет | Native replication mode | Нет (streaming) |
| Split-brain защита | — | Watchdog (кворум) | DCS-кворум |

**Вывод:** PgBouncer — когда нужна только экономия соединений; Pgpool-II — когда нужны read-balancing + failover в одном компоненте; Patroni — когда failover БД должен быть независим от прокси. Комбинировать PgBouncer **за** Pgpool-II или HAProxy — обычная production-схема.

### Режимы кластеризации

*   **Raw mode** — один бэкенд; только пулинг.
*   **Master/slave mode** — бэкенды реплицируются внешним механизмом (streaming replication, logical replication, Slony-I); запись на Primary, `SELECT` — балансировка. В Pgpool-II ≤ 4.2: `master_slave_mode = on` + `master_slave_sub_mode = 'stream'`; в 4.3+: `backend_clustering_mode = 'streaming_replication'`.
*   **Native replication mode** — встроенная репликация Pgpool-II (2+ сервера); репликация на уровне SQL; `failover_when_quorum_exists` недопустим в этом режиме.
*   **Parallel query mode** — legacy-режим распараллеливания запросов по шардам; для новых развёртываний не рекомендуется.

### Ограничения

*   `SELECT` с побочными эффектами (функции, меняющие данные) балансируются некорректно — комментарий `/*NO LOAD BALANCE*/` перед запросом отправляет его на Primary.
*   `nextval()` обрабатывается корректно, но вставки в таблицы с `SERIAL` требуют блокировки строки (Pgpool-II 3.0+ — row lock вместо table lock).
*   Временные таблицы и DDL — только на Primary.
*   Функции с недетерминированным поведением (`random()`, `now()`) дают разные результаты на разных бэкендах.

## Практические сценарии

### Сценарий: Установка и минимальная конфигурация (streaming replication mode)

```bash
# RHEL/Rocky/Alma (PGDG)
sudo dnf install -y pgpool-II-pg18 pgpool-II-pg18-extensions
```

Конфигурация (`/etc/pgpool-II/pgpool.conf`, образец `pgpool.conf.sample-stream`):

```ini
listen_addresses = '*'
port = 9999
pcp_listen_addresses = '*'
pcp_port = 9898

backend_clustering_mode = 'streaming_replication'   # PG 4.3+; в <=4.2: master_slave_mode = on, master_slave_sub_mode = 'stream'

backend_hostname0 = 'pg-primary'
backend_port0 = 5432
backend_weight0 = 1
backend_data_directory0 = '/var/lib/pgsql/18/data'

backend_hostname1 = 'pg-standby'
backend_port1 = 5432
backend_weight1 = 1
backend_data_directory1 = '/var/lib/pgsql/18/data'

load_balance_mode = on
health_check_period = 10
health_check_user = 'pgpool'
health_check_password = '***'
```

Пользователь `pgpool` на PostgreSQL — для health check и проверки отставания streaming-репликации; `repl` — пользователь репликации.

### Сценарий: Watchdog (HA пула Pgpool-II)

Три узла Pgpool-II, heartbeat + виртуальный IP:

```ini
use_watchdog = on
wd_hostname0 = 'pgpool1'
wd_port0 = 9000
pgpool_port0 = 9999
heartbeat_port0 = 9694
wd_authkey = '***'
failover_when_quorum_exists = on
failover_require_consensus = on
delegate_IP = '10.0.0.100'
```

*   `delegate_IP` — виртуальный IP, переезжает на активный узел.
*   `failover_when_quorum_exists` — failover только при кворуме heartbeat-узлов (защита от split-brain).
*   Pgpool-II 4.1+ запускается от пользователя `postgres` (до 4.0 — root).

### Сценарий: Автоматический failover бэкенда

```ini
failover_command = '/etc/pgpool-II/failover.sh %d %H %P %D %m %h %M %P %r %R'
```

Скрипт получает индекс отказавшего бэкенда, новый Primary и т.д.; типовая логика: `pg_ctl promote` на standby, переконфигурация остальных standby. Проверка состояния:

```bash
pcp -h 127.0.0.1 -p 9898 -U pgpool show pool_nodes
# → Node | Hostname | Port | Status | Weight
# → 0    | pg-primary | 5432 | 2      | 1.0
# → 1    | pg-standby | 5432 | 2      | 1.0
```

Status: `2` = active, `3` = down, `4` = standby.

### Сценарий: Принудительная отправка запроса на Primary

```sql
/*NO LOAD BALANCE*/ SELECT pg_current_wal_lsn();
```

### Сценарий: Health check и отставание реплики

`health_check_period` — период проверки бэкендов; при неудаче бэкенд помечается down и исключается из балансировки. Для streaming-репликации Pgpool-II проверяет отставание (`sr_check_period`, `sr_check_user`) и не отправляет read-запросы на сильно отставший standby.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `backend is not available` | Бэкенд down или health check не прошёл | `show pool_nodes`; проверить PostgreSQL, сеть, `health_check_user` |
| Split-brain (два Primary) | Отсутствие кворума watchdog | `failover_when_quorum_exists = on`, 3 узла watchdog |
| Read-запросы на отставшем standby устаревшие | Lag репликации | `sr_check_period`, `load_balance_mode` с проверкой lag |
| Очередь соединений растёт | `num_init_children` / `max_pool` малы | Поднять лимиты; проверить `show pool_cache` |
| `nextval()` дублируется | Native replication с неправильной обработкой последовательностей | Использовать streaming replication mode |

## Лучшие практики

1.  **Не смешивать роли**: если нужен только пулинг — PgBouncer (проще и быстрее); Pgpool-II — когда нужны read-balancing и failover.
2.  **Watchdog в нечётном числе узлов** (3) — кворум при сетевом разделении.
3.  **Health check обязателен** — без него down-бэкенд продолжает получать трафик.
4.  **`/*NO LOAD BALANCE*/`** для запросов, требующих свежести данных.
5.  **Тестировать failover** на стенде — `failover_command` должен отрабатывать за секунды.
6.  **Мониторить Pgpool-II** через PCP: `show pool_nodes`, `show processlist`, число ожидающих соединений.
7.  **Сравнивать с Patroni** — для HA БД Patroni + DCS даёт более строгую защиту от split-brain; Pgpool-II Watchdog — для HA самого пула.

## Дополнительная информация

*   [Настройка PgBouncer](./pgbouncer_setup.md) — специализированный пулер
*   [Операции PgBouncer](./pgbouncer_operations.md) — администрирование пула
*   [High Availability](../Concepts/high_availability.md) — Patroni, DCS, split-brain
*   [Репликация](../Concepts/replication.md) — streaming replication
*   [Управление соединениями](./connection_management.md) — слоты и таймауты
*   [Официальная документация Pgpool-II](https://www.pgpool.net/docs/latest/en/html/)
*   [PostgreSQL wiki: Pgpool-II](https://wiki.postgresql.org/wiki/Pgpool-II)
