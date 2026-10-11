# Chaos Engineering для PostgreSQL

**Актуально для:** PostgreSQL 14–18; Patroni — любые поддерживаемые версии

## Определения

*   **Chaos Engineering** — дисциплина контролируемого внедрения отказов в production-подобную среду для проверки устойчивости. Общая теория, принципы и инструменты — **[Chaos Engineering: обзор](../../../Chaos_Engineering/chaos_engineering_overview.md)**.
*   **Инъекция отказа (fault injection)** — целенаправленное действие: `kill` процесса, заполнение диска, задержка пакетов (`tc netem`), блокировка сети (`iptables`).
*   **Blast radius** — зона воздействия эксперимента: один бэкенд, один узел кластера, весь кластер. Начинать с минимального радиуса.
*   **Steady state (стабильное состояние)** — метрики до эксперимента (RPS, latency p99, ошибки); гипотеза: «при отказе X steady state не нарушается дольше N секунд».
*   **DR drill (учение)** — отработка восстановления; пересекается с chaos, но цель — проверить процедуру, а не устойчивость системы. Runbook: **[Аварийное восстановление](./disaster_recovery.md)**.

## Базовые концепции

### Почему PostgreSQL — особый случай

PostgreSQL — stateful-система с процессной моделью и файловым хранилищем. Отказы делятся на классы:

| Класс | Пример | Что проверяет |
| :--- | :--- | :--- |
| Процесс | `kill` бэкенда / postmaster | изоляция сессий, failover |
| Диск | заполнение `pg_wal`, PGDATA | деградация, алерты |
| Сеть | `tc netem`, `iptables` | split-brain, лаг репликации |
| Данные | повреждение страницы, `pg_wal` | recovery, PITR |
| Нагрузка | connection storm, длинные транзакции | пулинг, таймауты |

### Правила безопасности экспериментов

1.  **Не на production без одобрения**: сначала staging, идентичный production (версия, объём, Patroni-топология).
2.  **Гипотеза и метрики до старта**: что именно должно остаться в норме (RPS, p99, `pg_is_in_recovery`, лаг репликации).
3.  **Автооткат**: таймер, который останавливает эксперимент через N минут; `kill -9` — только бэкендам, не postmaster (если это не цель эксперимента).
4.  **Мониторинг включён**: `pg_stat_activity`, `pg_stat_replication`, логи, диск — до, во время и после.
5.  **Один фактор за раз**: иначе причина деградации не определяется.

## Предпосылки

1.  **Стенд:** кластер Patroni (3 узла) или Primary + 1 standby; права `sudo` на хостах.
2.  **Инструменты:** `tc` (iproute2), `iptables`, `stress-ng`, `pg_terminate_backend` (право `pg_signal_backend` или `SUPERUSER` для чужих сессий — см. [Роли](./role_management.md)).
3.  **Базовый мониторинг:** `pg_stat_activity`, `pg_stat_replication`, `pg_is_in_recovery()`.

## Практические сценарии

### 1. Kill бэкенда (blast radius: одна сессия)

```bash
# Находишь pid «жертвы»
psql -c "SELECT pid, usename, application_name, state FROM pg_stat_activity WHERE backend_type = 'client backend' LIMIT 1;"
# → pid | usename | application_name | state
# → 12345 | app_user | billing | idle

# Убиваешь процесс ОС (аналог OOM-killer)
sudo kill -9 12345
```
```sql
-- Ожидание: приложение получает ошибку соединения, пулер (PgBouncer) переподключается
SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend';
-- → число вернулось к baseline за < 30 с
```
Проверка: остальные сессии не пострадали (process-per-connection изоляция); в логе — `server process (PID 12345) was terminated by signal 9`.

### 2. Kill postmaster / failover Patroni (blast radius: узел)

```bash
# На узле-лидере Patroni
sudo systemctl stop patroni
# или жёсткий kill: sudo kill -9 $(pgrep -f postgres)
```
```bash
# Ожидание: Patroni продвигает standby в лидера за секунды
patronictl list mycluster
# → mycluster | 10.0.0.1 | 5432 | Replica | running | 10.0.0.3:5432 | Sync Standby
# → mycluster | 10.0.0.2 | 5432 | Leader  | running |    0 |
# → mycluster | 10.0.0.3 | 5432 | Replica | running | 10.0.0.2:5432 |
```
Проверка: `pg_is_in_recovery()` на новом лидере → `f`; приложение переподключилось через HAProxy; потери — только незакоммиченные/асинхронные транзакции (RPO по архитектуре).

### 3. Заполнение диска под `pg_wal` (blast radius: кластер)

```bash
# Симуляция: заполняем файловую систему с pg_wal
sudo dd if=/dev/zero of=/var/lib/postgresql/fill bs=1M count=4000
# → dd: error writing '/var/lib/postgresql/fill': No space left on device
```
Что должно произойти:
*   PostgreSQL останавливает запись (checkpoint не может завершиться), в логе — `could not write to file "pg_wal/...": No space left on device`.
*   Алерты по `node_filesystem_avail_bytes` срабатывают **до** исчерпания (порог 20%).
*   После освобождения места кластер восстанавливается без вмешательства (если не было `PANIC`).

Очистка: `sudo rm /var/lib/postgresql/fill`.

### 4. Сетевой раздел (split-brain) — `tc netem`

```bash
# Задержка 500 мс + потеря 10% пакетов между Primary и standby
sudo tc qdisc add dev eth0 root netem delay 500ms loss 10%
# → (нет вывода)

# Проверка лага репликации на Primary
psql -c "SELECT client_addr, state, sync_state, replay_lag FROM pg_stat_replication;"
# → client_addr | state  | sync_state | replay_lag
# → 10.0.0.3    | streaming | async | 00:00:00.8

# Откат
sudo tc qdisc del dev eth0 root
```
Проверка: при асинхронной репликации — рост `replay_lag`, при синхронной — рост latency коммита; Patroni не делает failover при кратковременной деградации (таймауты `ttl`/`loop_wait`).

Полная изоляция узла: `sudo iptables -A INPUT -s 10.0.0.3 -j DROP` (откат: `-D INPUT`).

### 5. Длинная транзакция и застой слота репликации

```sql
-- Инъекция: открытая транзакция на 10 минут
BEGIN; SELECT pg_sleep(600);
-- (в другой сессии)
SELECT pid, now() - xact_start AS tx_age, state FROM pg_stat_activity
WHERE state = 'idle in transaction' OR state = 'active';
-- → pid | tx_age | state
-- → 12345 | 00:05:00 | active
```
Проверка: алерт «длинная транзакция > 5 мин» срабатывает; `VACUUM` не может очистить таблицы, которые читает транзакция (рост `n_dead_tup`); WAL не удаляется, если слот репликации застрял (`pg_replication_slots.wal_status = lost` — критично).

### 6. Connection storm

```bash
# Инъекция: 500 одновременных подключений
for i in $(seq 1 500); do psql -c "SELECT 1" & done
# → часть получает: FATAL: sorry, too many clients already
```
Проверка: `superuser_reserved_connections` сохраняет админский доступ; PgBouncer (если есть) ставит клиентов в очередь (`client_waiting`), а не даёт ошибку; после штурма — нет утечки бэкендов (`pg_stat_activity` вернулся к baseline).

### 7. Повреждение страницы данных (только на стенде!)

```bash
# На изолированном стенде: портим байт в файле отношения
printf '\x00' | sudo dd of=/var/lib/postgresql/data/base/16384/1259 bs=1 seek=8192 conv=notrunc
# → 1+0 records in

# Стартуем кластер — при чтении страницы:
psql -c "SELECT * FROM important_table;"
# → ERROR: invalid page header ... или page verification failure
```
Проверка: `data_checksums` (включены при initdb) обнаруживает повреждение; восстановление — `pg_resetwal` **не** для этого, а `REINDEX`/восстановление страницы из бэкапа; полный разбор — **[Восстановление после повреждений](../Concepts/corruption_recovery.md)**.

## Операции и команды

| Команда | Инструмент | Blast radius | Что тестирует |
| :--- | :--- | :--- | :--- |
| `sudo kill -9 <pid>` | OS | одна сессия | изоляция process-per-connection, пулер |
| `sudo systemctl stop patroni` | systemd | узел | failover, split-brain |
| `sudo dd if=/dev/zero of=<file> bs=1M count=N` | dd | кластер | disk full, алерты |
| `sudo tc qdisc add dev <dev> root netem delay <ms> loss <n%>` | tc | сеть | репликационный лаг |
| `sudo tc qdisc del dev <dev> root` | tc | сеть | откат netem |
| `sudo iptables -A INPUT -s <ip> -j DROP` | iptables | сеть | полная изоляция |
| `sudo iptables -D INPUT -s <ip> -j DROP` | iptables | сеть | откат iptables |
| `BEGIN; SELECT pg_sleep(N);` | psql | сессия | long transaction, bloat |
| `for i in $(seq 1 500); do psql -c "SELECT 1" & done` | bash | кластер | connection storm |
| `printf '\x00' \| dd of=<file> bs=1 seek=N conv=notrunc` | dd | страница | data_checksums |
| `SELECT pg_terminate_backend(<pid>)` | psql | сессия | отмена чужой сессии (`pg_signal_backend`) |

> **Правило:** `pg_terminate_backend` требует роли `pg_signal_backend` (PG 10+) или `SUPERUSER` для чужих сессий; для собственных — достаточно обычного пользователя. См. **[Роли](./role_management.md)**.

## Валидация и проверка

Steady state — метрики до эксперимента, которые должны остаться в норме. Проверяйте **до, во время и после**:

| Что измерить | Как | Порог |
| :--- | :--- | :--- |
| RPS / latency p99 | `pgbench` или аппметрика | ±5% от baseline |
| `pg_is_in_recovery()` | `SELECT pg_is_in_recovery();` | Primary → `f`, standby → `t` |
| Репликационный лаг | `SELECT client_addr, replay_lag FROM pg_stat_replication;` | < 1 с (sync), < 5 с (async) |
| Бэкенды | `SELECT count(*) FROM pg_stat_activity WHERE state = 'active';` | ±baseline |
| Диск | `df -h /var/lib/postgresql/pg_wal` | > 20% свободно |
| Алерты | TSDB: `node_filesystem_avail_bytes`, `pg_replication_lag` | срабатывают при эксперименте |

**Методология эксперимента:**
1.  Зафиксировать baseline (3–5 измерений за 2 минуты).
2.  Сформулировать гипотезу: «при отказе X steady state не нарушается дольше N секунд».
3.  Запустить эксперимент с автооткатом (таймер).
4.  Сравнить метрики до/после; если порог нарушен — анализировать причину.

## Очистка и откат

**Универсальная процедура после каждого эксперимента:**

1.  **Снятие нагрузки:** остановить `stress-ng`, завершить штурм подключений (`psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE ...";`).
2.  **Сеть:** `sudo tc qdisc del dev <dev> root 2>/dev/null; sudo iptables -F INPUT;`
3.  **Диск:** удалить временные файлы (`sudo rm /var/lib/postgresql/fill`).
4.  **Сессии:** `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid IN (список_бэкендов_из_эксперимента);`
5.  **Восстановление кластера:** если был `kill -9 postmaster` — убедиться что Patroni поднял нового лидера; если был диск full — проверить что `pg_wal` не застрял на `could not write`.
6.  **Проверка baseline:** убедиться что все метрики вернулись к baseline (см. таблицу выше).
7.  **Документировать:** зафиксировать `blast_radius`, `recovery_time`, `found gaps` в runbook.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Кластер не поднялся после `kill -9 postmaster` | заблокированный `postmaster.pid` | `sudo fuser -c /var/lib/postgresql/data/postmaster.pid` → `kill`, либо `rm postmaster.pid` если нет PID (перед `pg_resetwal`!) |
| `No space left on device` при заполнении диска | `pg_wal` на том же диске | `sudo rm fill` → `pg_ctl restart` или `patronictl reload` |
| Split-brain при сетевой задержке | два лидера одновременно | Patroni использует DCS-куорум (etcd/Consul); если split-brain произошёл — остановить резервный узел, выполнить **`reinit`** на standby |
| `FATAL: sorry, too many clients already` после штурма | бэкенды не освобождаются | `sudo pkill -9 -u postgres` (только на стенде) → перезапуск postmaster |
| `invalid page header` в логе | повреждённая страница (data_checksums off) | включить data_checksums, восстановить из бэкапа, `REINDEX` только для индексов |
| `replay_lag` растёт после `tc netem` | сеть не сброшена | `sudo tc qdisc del dev <dev> root` → подождать `wal_receiver_status_interval` (default 10s) |
| Алерт не сработал при эксперименте | алерт настроен на среднее, а не p99 | исправить порог в TSDB, повторить эксперимент |
| Standby не следует за Primary | слот репликации застрял | `SELECT * FROM pg_replication_slots WHERE active = false;` → `pg_drop_replication_slot()`, перезапустить репликацию |

## Лучшие практики

1.  **Каденс**: ежемесячный chaos-день на staging; quarterly — DR drill на изолированном стенде (restore из бэкапа).
2.  **Начинать с чтения**: сначала `pg_terminate_backend` и `tc netem` (обратимо), потом `kill -9`, потом диск и повреждения.
3.  **Всё, что stateful — через Patroni**: ручной `kill -9 postmaster` без HA — это не chaos, а инцидент.
4.  **Алерты — часть эксперимента**: если при инъекции не сработал ни один алерт — эксперимент провален, даже если система «выстояла».
5.  **Не трогать `pg_wal` на production**: инъекции с повреждением WAL — только на стенде; на production это реальная потеря данных.
6.  **Документировать**: гипотеза, действия, результат, найденные gaps — в отчёте эксперимента; gaps идут в runbook.
7.  **Связь с DR**: chaos проверяет устойчивость «в строю», DR drill — процедуру «после катастрофы»; оба обязательны, они не заменяют друг друга.

## Пограничные случаи

*   **`kill -9` postmaster без Patroni**: recovery при старте (WAL replay) — минуты; незакоммиченные транзакции теряются; это DR-сценарий, не chaos.
*   **`tc netem` на всех узлах сразу**: имитация деградации ДЦ — Patroni может начать failover-каскад; проверять `loop_wait`/`ttl` заранее.
*   **Disk full на standby**: реплика отстаёт, WAL на Primary накапливается (`pg_replication_slots`), может заполнить и Primary — мониторить оба узла.
*   **Connection storm при отсутствии пулера**: `max_connections` исчерпывается за секунды; `superuser_reserved_connections` сохраняет админский доступ; `reserved_connections` (PG 18+) резервирует слоты для ролей с `pg_signal_backend`.
*   **Повреждение индекса vs таблицы**: `REINDEX` лечит индекс; повреждение страницы таблицы — только восстановление из бэкапа/PITR.
*   **Чистый `kill -9 postmaster` без DCS**: recovery при старте (WAL replay) — минуты; если `postmaster.pid` не удалён вручную и PID в нём не отвечает — PostgreSQL откажется стартовать (F0001 `lock_file_exists`); удалить файл после `pgrep postgres` (никаких процессов) — см. [runbook](./troubleshooting_runbook.md).
*   **Повреждение `pg_wal` на Primary**: `pg_resetwal` только после полного останова кластера; на standby — `reinit` через Patroni (`patronictl reinit`) или `pg_rewind`.
*   **Длинные транзакции на standby**: `max_standby_streaming_delay` (default 30s) — standby отстаёт; если транзакция дольше — `cancel`/`terminate` через `pg_terminate_backend` с `pg_signal_backend`.

## Дополнительная информация

*   [Chaos Engineering: обзор](../../../Chaos_Engineering/chaos_engineering_overview.md) — принципы, steady state, blast radius.
*   [Chaos: stateful-приложения](../../../Chaos_Engineering/chaos_stateful_applications.md) — общие подходы к БД.
*   [Chaos: не-Kubernetes](../../../Chaos_Engineering/chaos_non_kubernetes.md) — bare-metal/VM инъекции.
*   [Аварийное восстановление (DR)](./disaster_recovery.md) — RPO/RTO, учения восстановления.
*   [Восстановление после повреждений](../Concepts/corruption_recovery.md) — `data_checksums`, `REINDEX`, PITR.
*   [High Availability (Patroni)](./high_availability_patroni.md) — failover, DCS, split-brain.
*   [Управление соединениями](./connection_management.md) — connection storm, reserved slots.
*   [Диагностический runbook](./troubleshooting_runbook.md) — симптом → команда → причина.
