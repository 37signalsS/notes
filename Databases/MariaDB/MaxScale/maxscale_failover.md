# MariaDB MaxScale: Failover и Switchover (mariadbmon)

**Актуально для:** MaxScale 25.10.x

## Определения

*   **mariadbmon (MariaDB Monitor)** — модуль мониторинга для топологии Primary-Replica. Не только отслеживает состояние узлов, но и модифицирует кластер: выполняет failover, switchover, rejoin. Старое имя модуля — `mysqlmon` (всё ещё работает как псевдоним, с MaxScale 2.2.1 имя — `mariadbmon`).
*   **Failover** — замена упавшего Primary на реплику. Автоматический (при `auto_failover`) или ручной.
*   **Failover-safe** — failover, который отказывается начинаться, если GTID однозначно показывают потерю данных.
*   **Switchover** — плановая замена: работающий Primary понижается в реплики, работающая реплика повышается. Данные не теряются.
*   **Rejoin** — возвращение отвалившегося узла в кластер: настройка репликации с текущим Primary.
*   **Смена Primary (primary change)** — только переключение ролей внутри MaxScale; кластер не модифицируется. Отличается от failover/switchover, которые реально модифицируют кластер (`CHANGE MASTER TO` на репликах).
*   **failcount** — число подряд идущих проходов монитора, в течение которых Primary должен быть недоступен, прежде чем он считается отказавшим. По умолчанию 5; значение 0 или 1 включает немедленный failover.
*   **auto_failover / auto_rejoin** — параметры монитора, включающие автоматический failover и автоматический rejoin. По умолчанию отключены.
*   **Primary monitor** — в cooperative monitoring тот инстанс MaxScale, который получил большинство блокировок; только он выполняет операции изменения кластера.
*   **Cooperative monitoring** — координация нескольких инстансов MaxScale через блокировки (`GET_LOCK`) на серверах БД, чтобы только один MaxScale выполнял операции изменения кластера и все инстансы сходились в выборе Primary.
*   **passive** — глобальный параметр MaxScale: пассивный инстанс мониторит и маршрутизирует, но не выполняет операции изменения кластера.
*   **Journal** — файл состояний монитора на диске (`/var/lib/maxscale/<имя_монитора>/monitor.dat`); читается при старте MaxScale, что делает монитор crash-safe. Удалите его перед стартом, чтобы пропустить восстановление состояний.

## Теоретический блок

### Как mariadbmon выбирает Primary

Primary — это сервер, к которому монитор успешно подключён и у которого выключен `read_only`. Primary не должен реплицировать от другого сервера из мониторируемого кластера (кроме случая multiprimary-группы). При выборе Primary предпочтение отдаётся серверу с наибольшим числом реплик (включая многоуровневые топологии; в расчёт идут только реплики, достижимые через цепочку работающих relay-узлов). При равенстве — сервер, раньше указанный в параметре `servers` монитора.

После выбора монитор старается придерживаться текущего Primary, даже если появляются кандидаты с большим числом реплик; перевыбор происходит только когда текущий Primary явно непригоден. Существующий Primary становится недействительным, если:

1. Он незаписываем (`read_only` включён).
2. Он недоступен более `failcount` проходов монитора и у него нет работающих реплик. Реплика считается работающей, если хотя бы один поток репликации (IO или SQL) хотя бы частично работает; реплики за недоступным relay тоже считаются. При этом сами реплики тоже должны быть недоступны более `failcount` проходов, чтобы разрешить выбор нового Primary.
3. Он начал реплицировать от другого сервера, хотя раньше не реплицировал.
4. Он вышел из мультипраймерной группы или группа стала реплицировать от внешнего сервера.

Случаи 1–2 покрывают ситуацию, когда DBA, внешний скрипт или другой MaxScale модифицировали кластер так, что старый Primary больше не может быть Primary. Случаи 3–4 менее серьёзны: топология сильно изменилась, Primary нужно перевыбрать, но старый Primary может остаться лучшим выбором.

Общее правило: избегайте кластеров с несколькими изолированными серверами, отдельными primary-replica-парами или отдельными multiprimary-группами — изолированный Primary легко теряет статус при падении (правило 2), а новый Primary, скорее всего, не содержит тех же данных.

### Алгоритм failover

При failover mariadbmon:

1. Выбирает самую актуальную реплику по критериям (в порядке приоритета): `gtid_IO_pos` (последнее событие в relay-логе) → `gtid_current_pos` (больше всего обработанных событий) → `log_slave_updates=ON` → достаточное место на диске. При равенстве кандидатов — предпочтение серверам в порядке перечисления в `servers`.
2. Если у кандидата есть неприменённые relay-лог события — отмена и повторная попытка позже.
3. Подготовка нового Primary: удаление его репликационного соединения, снятие `read_only`, включение событий (если `handle_events`), выполнение `promotion_sql_file`, запуск репликации от внешнего Primary, если он есть.
4. Перенаправление остальных реплик на новый Primary: `STOP SLAVE` → `CHANGE MASTER TO` → `START SLAVE`.
5. Проверка, что все реплики реплицируют.

Failover считается успешным, если шаги 1–3 выполнены — кластер имеет валидный Primary.

**Failover-safe** выполняет те же шаги, но отказывается начинаться, если однозначно ясно, что данные будут потеряны (у Primary были события, не реплицированные ни на одну реплику). Определение — по GTID; так как монитор опрашивает GTID только раз в `monitor_interval`, проверка неточна: запись, сделанная незадолго до падения Primary, может быть потеряна даже при «безопасном» failover. Механизм главным образом защищает от ситуации постоянно отстающих реплик.

### Алгоритм switchover (12 шагов)

1. Подготовка старого Primary к понижению.
2. При коротком `backend_timeout` — его удлинение и переподключение (в 25.10 `backend_read_timeout` deprecated и игнорируется, актуален `backend_timeout`).
3. Остановка внешней репликации.
4. Включение `read_only` (блокирует записи обычных пользователей).
5. Убийство соединений пользователей с SUPER/READ_ONLY ADMIN (на них `read_only` не действует); на время блокировки — `FLUSH TABLES WITH READ LOCK`.
6. Отключение событий (если `handle_events`).
7. Выполнение `demotion_sql_file`.
8. `FLUSH LOGS` — все события на диск.
9. Проверка стабильности GTID.
10. Ожидание догоняния нового Primary.
11. Повышение нового Primary и перенаправление реплик (как в failover), включая бывший Primary.
12. Проверка репликации на всех узлах.

Switchover считается успешным, если новый Primary успешно повышен. Switchover требует «замороженного» кластера: без DML и со стабильной GTID-позицией Primary — поэтому пользователи, которые пишут в БД, не должны иметь SUPER (иначе они обходят `read_only` и ломают репликацию); в идеале единственная SUPER-сессия во время switchover — сессия пользователя монитора. То же касается definer-ов событий с SUPER.

**Switchover-force** — те же шаги, но игнорирует ошибки на старом Primary и не требует, чтобы новый Primary догнал GTID старого. Может потерять события и сломать репликацию на нескольких (или всех) репликах. Команда крайней степени, только когда других вариантов нет.

### Rejoin и reset-replication

**Rejoin** — присоединение изолированного сервера или перенаправление реплики, реплицирующей не от того Primary:

*   Изолированный сервер: выполнение `demotion_sql_file`, включение `read_only`, отключение событий (если `handle_events`), `CHANGE MASTER TO` + `START SLAVE`.
*   Реплика с «неправильным» Primary: `STOP SLAVE` → `RESET SLAVE` → `CHANGE MASTER TO` → `START SLAVE`.

Ручной rejoin (в отличие от `auto_rejoin`) позволяет присоединить сервер даже с пустыми GTID — это даёт возможность форсировать rejoin на сервере без бинлогов.

**Reset-replication** (с 2.3.0) — деструктивная операция для ситуации, когда GTID в кластере расходятся, а данные заведомо синхронны: останавливает и удаляет все репликационные соединения (`STOP SLAVE`, `RESET SLAVE ALL`), включает `read_only`, отключает события, удаляет бинлоги (`RESET MASTER`), обнуляет последовательность `gtid_slave_pos`, повышает новый Primary и перенаправляет остальные серверы на него.

### Тайминги failover

Худшее время между отказом Primary и началом failover:

```
(monitor_interval + backend_timeout) * failcount
```

При defaults (`monitor_interval=2s`, `backend_timeout=3s`, `failcount=5`) — до 25 секунд. Уменьшение `failcount` ускоряет обнаружение, но повышает риск ложного срабатывания.

### Координация нескольких MaxScale

Если несколько MaxScale мониторят один кластер, они должны договориться, кто выполняет операции изменения кластера и кто является Primary. Три режима:

| Режим | Как координируются | Защита от расхождения при failover | Защита при сетевом разделении | Серверов нужно |
| :--- | :--- | :--- | :--- | :--- |
| Active/passive (`passive`) | Не координируются — роль задаётся вручную | Нет | Нет | — |
| `cooperative_monitoring_locks=majority_of_running` | Блокировки на большинстве доступных серверов | Да | Нет | 2 |
| `cooperative_monitoring_locks=majority_of_all` | Блокировки на большинстве всех настроенных серверов | Да | Да (с semi-sync репликацией) | 3 |

**Default `cooperative_monitoring_locks` — `none`** (без координации). `majority_of_running` — строгое улучшение по сравнению с active/passive; это рекомендуемый (но не умолчательный) режим для любых развёртываний с `auto_failover`/`auto_rejoin` и более чем одним MaxScale. `majority_of_all` — когда сетевые разделения реалистичны (MaxScale в разных ЦОДах); требует минимум 3 сервера и semi-sync репликации.

**Механизм блокировок.** Монитор регулярно проверяет блокировку с именем `maxscale_mariadbmonitor` на каждом сервере и захватывает её, если свободна. Большинство — это `floor(n/2)+1` захваченных блокировок (2 сервера → 2 блокировки, 3 → 2, 4 → 3, 5 → 3). Primary monitor дополнительно захватывает блокировку `maxscale_mariadbmonitor_master` на сервере Primary; secondary-мониторы принимают как записываемый только тот сервер, на котором видят эту блокировку; если блокировку не видно, secondary-монитор не считает записываемым ни один сервер. При неудачном захвате большинства инстанс отпускает захваченные блокировки и повторяет попытку через случайное число проходов монитора — вероятность конфликта снижается ещё сильнее, если у мониторов разные `monitor_interval`.

**Роль `passive`.** `passive=true` отключает операции изменения кластера даже при захваченных блокировках. Не смешивайте cooperative monitoring с `passive`: задайте `passive=false` или не задавайте его вовсе.

Проверка того, кто primary monitor: `maxctrl show monitors` — поле `primary` (true/false; `null`, если cooperative monitoring выключен), у серверов — поле `lock_held` (`null`, если блокировки не используются).

## Практические сценарии

### Prerequisites

*   GTID-репликация (обязательно для failover/switchover/rejoin); домен GTID не должен меняться во время операции; у реплик не должно быть «лишних» локальных событий.
*   Простая топология: 1 Primary + N реплик. Многоуровневые, кольцевые и multi-source топологии могут давать непредсказуемые результаты — тестируйте отдельно.
*   MariaDB 11.0.1+ для грантов `READ_ONLY ADMIN` / `REPLICATION SLAVE ADMIN` (до 11.0.1 требуется `SUPER`).
*   `assume_unique_hostnames=on` (default) — обязательно для операций изменения кластера: монитор использует адреса из конфига MaxScale в `CHANGE MASTER TO`. Если адреса, которыми MaxScale обращается к серверам, отличаются от адресов, которыми серверы обращаются друг к другу, задайте серверный параметр `private_address` (альтернативный адрес для репликации) или выключите `assume_unique_hostnames` (менее надёжно: вывод по server id).
*   Если несколько MaxScale мониторят один кластер — настройте координацию (cooperative monitoring или active/passive) ДО включения `auto_failover`.

### Шаг 1: Гранты сервисного пользователя

```sql
-- На каждом узле кластера
CREATE USER 'mariadbmon'@'maxscale-host' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';

-- Базовый мониторинг (обязательно)
GRANT REPLICA MONITOR ON *.* TO 'mariadbmon'@'maxscale-host';

-- Рекомендуется: вход даже при достижении лимита соединений сервера
GRANT CONNECTION ADMIN ON *.* TO 'mariadbmon'@'maxscale-host';

-- MariaDB 11.0.1+: операции изменения кластера (failover/switchover/rejoin)
GRANT READ_ONLY ADMIN, REPLICATION SLAVE ADMIN ON *.* TO 'mariadbmon'@'maxscale-host';
GRANT BINLOG ADMIN, CONNECTION ADMIN, PROCESS, RELOAD, SET USER ON *.* TO 'mariadbmon'@'maxscale-host';
GRANT SELECT ON mysql.user TO 'mariadbmon'@'maxscale-host';
GRANT SELECT ON mysql.global_priv TO 'mariadbmon'@'maxscale-host';

-- До MariaDB 11.0.1 вместо READ_ONLY ADMIN/REPLICATION SLAVE ADMIN:
-- GRANT SUPER ON *.* TO 'mariadbmon'@'maxscale-host';
-- (PROCESS, RELOAD и SELECT на mysql.user/mysql.global_priv — те же)

-- Для scan-topology / discover-replicas / bootstrap дополнительно
GRANT REPLICATION MASTER ADMIN ON *.* TO 'mariadbmon'@'maxscale-host';
GRANT REPLICATION SLAVE ON *.* TO 'mariadbmon'@'maxscale-host';

-- Для проверки места на диске (disk_space_ok, maintenance_on_low_disk_space)
GRANT FILE ON *.* TO 'mariadbmon'@'maxscale-host';

-- Для управления событиями (handle_events)
GRANT EVENT, SHOW DATABASES ON *.* TO 'mariadbmon'@'maxscale-host';
```

Отдельный пользователь репликации (если задан `replication_user`/`replication_password` — репликация от внешнего Primary):

```sql
CREATE USER 'replication'@'replica-host' IDENTIFIED BY 'ПАРОЛЬ';
GRANT REPLICATION REPLICA ON *.* TO 'replication'@'replica-host';
```

Полный список привилегий и их разделение по версиям — в **[Привилегия для репликации](../replication/replication_privileges.md)**.

### Шаг 2: Конфигурация монитора с автоматическим failover

```ini
# /etc/maxscale.cnf

[server1]
type=server
address=192.168.1.11
port=3306

[server2]
type=server
address=192.168.1.12
port=3306

[server3]
type=server
address=192.168.1.13
port=3306

[MariaDB-Monitor]
type=monitor
module=mariadbmon
servers=server1,server2,server3
user=mariadbmon
password=СЛОЖНЫЙ_ПАРОЛЬ
monitor_interval=2s

# Автоматический failover и rejoin
auto_failover=true
auto_rejoin=true

# Число проходов монитора до признания Primary отказавшим
failcount=5

# Дополнительные условия для статуса Master (значение по умолчанию)
master_conditions=primary_monitor_master,disk_space_ok

# Пользователь репликации, которым монитор настраивает CHANGE MASTER TO
# (нужен для репликации от внешнего Primary)
replication_user=replication
replication_password=СЛОЖНЫЙ_ПАРОЛЬ

# SQL-файлы при повышении/понижении (опционально)
promotion_sql_file=/etc/maxscale.d/promotion.sql
demotion_sql_file=/etc/maxscale.d/demotion.sql
```

**Пояснения к параметрам:**

*   `master_conditions` — дополнительные условия для статуса Master. Значения: `none`, `connecting_slave`, `connected_slave`, `running_slave`, `primary_monitor_master`, `disk_space_ok` (с 23.08.5). По умолчанию `primary_monitor_master,disk_space_ok`. Если кандидат не проходит `master_conditions`, но проходит `slave_conditions`, он получает статус Slave.
*   `slave_conditions` — условия для статуса Slave (реплика годна для чтения): `none`, `linked_master`, `running_master`, `writable_master`, `primary_monitor_master`, `disk_space_ok` (с 23.08.5). По умолчанию `none`.
*   `enforce_writable_master` (default `false`) — монитор сам снимает `read_only` с Primary каждый проход (нужна возможность управлять `read_only`: `READ_ONLY ADMIN` 11.0.1+ или `SUPER`). При включённом параметре ручная установка `read_only` на Primary больше не заставляет монитор искать другой Primary — Primary ненадолго теряет статус Master, пока монитор не вернёт запись.
*   `enforce_read_only_slaves` (default `false`) — монитор включает `read_only` на всех записываемых репликах.
*   `enforce_read_only_servers` (default `false`) — то же, но на любом записываемом сервере, кроме Primary и maintenance (надмножество `enforce_read_only_slaves`). Критично для active/passive-схемы с несколькими MaxScale. Если в кластере нет валидного Primary, `read_only` не выставляется ни на одном сервере.
*   `maintenance_on_low_disk_space` (default `true`) — сервер без места уходит в maintenance и не участвует в failover; место на диске при этом больше не перепроверяется, выход из maintenance — только вручную (`maxctrl clear server server2 Maint`).
*   `handle_events` (default `true`) — монитор управляет запланированными событиями при повышении/понижении: при демоушене события переводятся в `SLAVESIDE_DISABLED`, при промоушене — обратно в `ENABLED` (только те, что были включены на старом Primary). Сам event scheduler монитор не включает — задайте `event_scheduler=ON` в конфиге сервера.
*   `failover_timeout` (default `90s`) — лимит времени на операцию failover. Если успешный failover не завершился за этот срок, в лог пишется сообщение и **автоматический failover отключается** (защита от дальнейших модификаций «зависшего» кластера).
*   `switchover_timeout` (default `90s`) — лимит на switchover; также является лимитом для rejoin.
*   `verify_master_failure` (default `true`) + `master_failure_timeout` (default `10s`) — дополнительная проверка отказа Primary: если реплики ещё получали события (смена `Gtid_IO_Pos` или heartbeat) в течение `master_failure_timeout`, Primary не считается упавшим, даже если монитор не может к нему подключиться. `master_failure_timeout` должен быть больше `Slave_heartbeat_period` репликационного соединения. Если все реплики потеряли IO-соединение с Primary, отказ считается подтверждённым независимо от таймаута — failover идёт быстрее.
*   `enforce_simple_topology` (default `false`) — монитор считает топологию строго 1-primary-N-replicas и поддерживает её: автоматически активирует `assume_unique_hostnames`, `auto_failover`, `auto_rejoin`; с MaxScale 6.2.0 также rejoins серверы с несколькими источниками репликации (удаляя лишние). Позволяет failover, когда MaxScale стартовал уже после падения Primary (домен GTID угадывается по репликам; для надёжности GTID должны быть «простыми»).
*   `servers_no_promotion` — список серверов, которые не выбираются для автоматического повышения (например, резервные узлы другого ЦОД). Не влияет на switchover с явным указанием нового Primary.
*   `switchover_on_low_disk_space` (default `false`) — автоматический switchover при низком месте на диске Primary (только если найдена реплика без проблем с местом). Требует заданных `disk_space_threshold` и `disk_space_check_interval`.

**Важно про проверку места на диске:** дисковые проверки по умолчанию выключены (`disk_space_check_interval=0s` в общих параметрах монитора). Условие `disk_space_ok` в `master_conditions` и `maintenance_on_low_disk_space` не имеют эффекта, пока не задан `disk_space_check_interval` (и `disk_space_threshold` на сервере или мониторе), а для чтения информации нужен грант `FILE`.

### Шаг 3: Ручные операции через maxctrl

Все зарегистрированные module commands показывает `maxctrl list commands`. С MaxScale 25.10 имя объекта (монитора) можно использовать вместо имени модуля — MaxScale сам подставит его первым аргументом. Обе формы работают в 25.10; старая форма обязательна на 25.01 и ранее. Ручные операции безопасны при включённом автоматическом failover/rejoin — автоматические и ручные операции не могут выполняться одновременно. Выполняются только когда MaxScale в активном режиме (`passive=false`).

```bash
# Аварийный failover (выбор новой реплики автоматически)
maxctrl call command MariaDB-Monitor failover
# → OK

# Failover с проверкой потерь данных (откажет, если GTID показывают потерю)
maxctrl call command MariaDB-Monitor failover-safe

# Плановый switchover (автовыбор реплики и текущего Primary)
maxctrl call command MariaDB-Monitor switchover

# Switchover с явным указанием нового Primary
maxctrl call command MariaDB-Monitor switchover server2

# Switchover с указанием нового Primary и старого
maxctrl call command MariaDB-Monitor switchover server2 server1

# Возврат отвалившегося узла в кластер (ручной rejoin допускает пустые GTID)
maxctrl call command MariaDB-Monitor rejoin server1

# Сброс GTID и бинлогов (деструктивно! только при расхождении GTID при синхронных данных)
maxctrl call command MariaDB-Monitor reset-replication
# либо с явным новым Primary:
# maxctrl call command MariaDB-Monitor reset-replication server2

# Перенаправление реплики на другой сервер (key-value аргументы; неэффективно при auto_rejoin=true)
maxctrl call command mariadbmon redirect monitor=MariaDB-Monitor replica=server3 new_primary=server2
```

Старая форма (для MaxScale 25.01 и ранее; в 25.10 тоже работает):

```bash
maxctrl call command mariadbmon failover MariaDB-Monitor
maxctrl call command mariadbmon switchover MariaDB-Monitor server2 server1
maxctrl call command mariadbmon rejoin MariaDB-Monitor server1
```

**Расширенный синтаксис switchover (key-value, MaxScale 24.08+):**

```bash
# Асинхронный switchover с принудительным выполнением
maxctrl call command mariadbmon switchover monitor=MariaDB-Monitor new_primary=server2 async=1 force=1

# Switchover с оставлением старого Primary в maintenance (rolling upgrade MariaDB)
maxctrl call command mariadbmon switchover monitor=MariaDB-Monitor old_primary_maint=1
```

| Аргумент | Тип | Default | Назначение |
| :--- | :--- | :--- | :--- |
| `monitor` | monitor | обязательно | Имя монитора |
| `new_primary` | server | авто-выбор | Какой сервер повышать |
| `old_primary` | server | авто-выбор | Какой сервер понижать |
| `async` | boolean | `false` | Асинхронный запуск |
| `force` | boolean | `false` | Игнорировать большинство ошибок (аналог switchover-force) |
| `old_primary_maint` | boolean | `false` | Оставить старый Primary в maintenance |

**Асинхронные команды и проверка результата:**

```bash
# Запуск асинхронного switchover
maxctrl call command MariaDB-Monitor async-switchover
# → OK

# Получение результата последней команды
maxctrl call command MariaDB-Monitor fetch-cmd-result
# → {
#      "links": {
#        "self": "http://localhost:8989/v1/maxscale/modules/mariadbmon/fetch-cmd-result"
#      },
#      "meta": "switchover completed successfully."
#    }
```

`fetch-cmd-result` возвращает результат последней ручной команды — очередной или нет.

**Команды MaxScale 25.10:**

```bash
# Сканирование топологии: вывод JSON со всеми найденными серверами
maxctrl call command MariaDB-Monitor scan-topology monitor=MariaDB-Monitor

# Автообнаружение новых реплик: добавляет их в MaxScale и монитор
# (серверы именуются <имя_монитора>-serverN; лучше с параметром cluster у сервисов)
maxctrl call command mariadbmon discover-replicas monitor=MariaDB-Monitor remove=true

# Загрузка пустого монитора: сканирует топологию от указанного адреса
maxctrl call command mariadbmon bootstrap monitor=MariaDB-Monitor template=server1 address=192.168.1.11
```

`scan-topology` и `discover-replicas` несовместимы с configuration synchronization (отказываются выполняться, если она включена). `bootstrap` поддерживает только простые топологии. Пример вывода `scan-topology`:

```json
{
    "results": [
        {
            "host": "192.168.0.1",
            "id": 100,
            "monitor_name": "MyMonitor",
            "port": 3306,
            "primaries": [],
            "replicas": [300, 200],
            "server_name": "MyServer1"
        }
    ]
}
```

### Шаг 4: Проверка после операции

```bash
maxctrl list servers
# ┌─────────┬───────────────┬──────┬─────────────┬─────────────────┐
# │ Server  │ Address       │ Port │ Connections │ State           │
# ├─────────┼───────────────┼──────┼─────────────┼─────────────────┤
# │ server1 │ 192.168.1.11  │ 3306 │ 0           │ Down            │
# ├─────────┼───────────────┼──────┼─────────────┼─────────────────┤
# │ server2 │ 192.168.1.12  │ 3306 │ 0           │ Master, Running │
# ├─────────┼───────────────┼──────┼─────────────┼─────────────────┤
# │ server3 │ 192.168.1.13  │ 3306 │ 0           │ Slave, Running  │
# └─────────┴───────────────┴──────┴─────────────┴─────────────────┘
```

На репликах — репликация настроена на новый Primary:

```sql
SHOW REPLICA STATUS\G
-- → Source_Host: 192.168.1.12
-- → Replica_IO_Running: Yes
-- → Replica_SQL_Running: Yes
```

При cooperative monitoring — кто primary monitor и какие блокировки захвачены:

```bash
maxctrl show monitors
# → В поле primary: true/false (null без cooperative monitoring);
#   у серверов — поле lock_held (null, если блокировки не используются)
```

### REST API: пути для операций

Операции изменения кластера доступны и через REST API. Формат пути:

```
/v1/maxscale/modules/mariadbmon/<operation>?<monitor-name>&<server-name1>&<server-name2>
```

`<server-name1>` и `<server-name2>` — как в maxctrl: switchover принимает оба, failover не требует ни одного, rejoin и reset-replication — по одному.

```bash
# Switchover: server4 повышается, server2 (текущий Primary) понижается
curl -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://localhost:8989/v1/maxscale/modules/mariadbmon/switchover?MariaDB-Monitor&server4&server2"

curl -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://localhost:8989/v1/maxscale/modules/mariadbmon/failover?MariaDB-Monitor"

curl -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://localhost:8989/v1/maxscale/modules/mariadbmon/rejoin?MariaDB-Monitor&server1"
```

### Координация двух MaxScale (active/passive)

На активном инстансе:

```ini
[maxscale]
passive=false
```

На пассивном:

```ini
[maxscale]
passive=true
```

Переключение роли в рантайме:

```bash
maxctrl alter maxscale passive=true
```

`passive=true` — инстанс продолжает мониторить и маршрутизировать, но не выполняет failover/switchover/rejoin. Только один MaxScale должен иметь `passive=false`.

Для защиты от записи на старый Primary после его перезапуска — на серверах БД в конфиге (`read_only=1` считывается при старте и восстанавливается после рестарта):

```ini
# /etc/my.cnf.d/server.cnf
read_only=1
log_slave_updates=1
gtid_strict_mode=1
```

И на обоих MaxScale — монитор сам управляет `read_only`:

```ini
[MariaDB-Monitor]
type=monitor
module=mariadbmon
servers=server1,server2,server3
user=mariadbmon
password=СЛОЖНЫЙ_ПАРОЛЬ
enforce_read_only_servers=1
enforce_writable_master=1
```

Ограничения active/passive: если Primary падает и перезапускается во время failover, пассивный MaxScale может продолжать считать его Primary — с `read_only=1` запись на него не пойдёт, но и переключения на правильный Primary не произойдёт; в этом случае неисправный Primary нужно остановить, чтобы пассивный MaxScale искал новый Primary. Сетевые разделения active/passive не защищает: единственная защита — Primary MaxScale и Primary-сервер в одном ЦОД (или внешний оркестратор, управляющий `passive`).

### Cooperative monitoring (рекомендуемый режим для 2+ MaxScale)

Одинаковая конфигурация монитора на всех инстансах:

```ini
[TheMonitor]
type=monitor
module=mariadbmon
servers=server1,server2,server3
cooperative_monitoring_locks=majority_of_running
auto_failover=true
auto_rejoin=true
```

**Тюнинг `failcount` при cooperative locking.** Блокировки живут, пока жив держащий их MaxScale (при чистом завершении MariaDB отпускает их сразу); при сетевом исчезновении инстанса блокировки удерживаются до истечения `wait_timeout`, который монитор выставляет на своих соединениях:

```
wait_timeout = monitor_interval + 2 * backend_timeout
```

Значение округляется до целых секунд и ограничивается диапазоном 5–28800 секунд; оно логируется при старте MaxScale. Минимально безопасный `failcount` (чтобы устаревшие блокировки успели истечь до начала failover), с запасом в один проход монитора:

```
failcount = (2 * backend_timeout) / monitor_interval + 2
```

| `monitor_interval` | `backend_timeout` | `wait_timeout` | Мин. безопасный `failcount` | Failover начинается через |
| :--- | :--- | :--- | :--- | :--- |
| 2s (default) | 3s (default) | 8s | 5 (default) | 10s |
| 5s | 10s | 25s | 6 | 30s |

Defaults уже безопасны. Пересчитывайте при изменении `backend_timeout`, `monitor_interval` или `failcount`. Не путайте с формулой худшего времени обнаружения `(monitor_interval + backend_timeout) * failcount`: первая отвечает «как быстро начнётся failover», вторая — «насколько малым может быть безопасный failcount».

**`majority_of_all` и сетевые разделения.** Только этот режим защищает от split-brain, и то не полностью: если Primary оказался в меньшинстве, он теряет записываемость через `wait_timeout` (8s по умолчанию) — за это время записи ещё проходят, а к моменту восстановления сети большинство уже могло повысить новый Primary. Чтобы минимизировать ущерб: semi-sync репликация с настройкой, при которой Primary никогда не откатывается в асинхронный режим (`rpl_semi_sync_master_timeout` на максимальное значение; default 10s), — иначе транзакции могут коммититься в minority-разделе и потеряться при склейке. Учтите: `majority_of_all` также «останавливает» кластер — при 3 настроенных серверах всегда требуются 2 блокировки, и кластер уходит в read-only, как только доступно менее 2 серверов, даже если выживший сервер мог бы обслуживать трафик. Третьим голосом может быть небольшой MariaDB-инстанс на машине MaxScale.

### Откат и cleanup

```bash
# Отключение автоматических операций в рантайме (без правки конфига)
maxctrl alter monitor MariaDB-Monitor auto_failover=false
maxctrl alter monitor MariaDB-Monitor auto_rejoin=false

# Вывод сервера из maintenance (единственный способ после maintenance_on_low_disk_space)
maxctrl clear server server2 Maint

# Удаление монитора (после остановки)
maxctrl destroy monitor MariaDB-Monitor
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `failover` не выполняется, Primary «завис» в статусе | Primary недоступен менее `failcount` проходов; либо `verify_master_failure`: реплики ещё получали события/heartbeat в течение `master_failure_timeout` | Подождите `(monitor_interval + backend_timeout) * failcount` или уменьшите `failcount`; проверьте лаг и heartbeat реплик (`master_failure_timeout` > `Slave_heartbeat_period`) |
| Автоматический failover перестал работать | Превышен `failover_timeout` (90s) — автоматический failover отключён, в логе сообщение | Восстановите кластер, перезапустите монитор (или измените параметр в рантайме) |
| Failover не запускается после перезапуска MaxScale | MaxScale стартовал уже после падения Primary — нет данных о GTID-домене (состояния частично восстанавливаются из journal `/var/lib/maxscale/<монитор>/monitor.dat`) | Верните старый Primary в строй или используйте `enforce_simple_topology=1` (домен GTID угадывается по репликам) |
| `switchover` падает на шаге ожидания GTID | Реплика не догоняет за `switchover_timeout` (90s) | Проверьте лаг репликации на реплике-кандидате; увеличьте `switchover_timeout` |
| Switchover «завис» — идут записи | Пользователи с SUPER (или definer событий с SUPER) обходят `read_only` | Убейте их соединения (`CONNECTION ADMIN`); в перспективе не давайте SUPER пишущим пользователям — единственная SUPER-сессия во время switchover должна быть у пользователя монитора |
| Ручной `rejoin` отказывается работать | Автоматический rejoin требует валидный GTID; сервер расходится с новым Primary | Ручной `rejoin` допускает пустые GTID (форсирует присоединение); при расхождении данных используйте `reset-replication` или настройте репликацию вручную |
| Два MaxScale продвигают разные Primary | Нет cooperative locking или `passive` задан неверно | Включите `cooperative_monitoring_locks=majority_of_running`; проверьте `maxctrl show monitors` (поле `primary`); помните: `passive=true` отключает операции даже при захваченных блокировках |
| `read_only` не снимается с нового Primary | Нет `enforce_writable_master` или нет гранта READ_ONLY ADMIN/SUPER | Добавьте `enforce_writable_master=1` и грант |
| Ошибка грантов при switchover | У пользователя монитора нет `SET USER`/`BINLOG ADMIN`/`READ_ONLY ADMIN` | Выполните гранты из раздела «Шаг 1» |
| Сервер «застрял» в Maintenance | `maintenance_on_low_disk_space` перевёл его в maintenance; место не перепроверяется | `maxctrl clear server <server> Maint`; устраните причину нехватки места |
| `disk_space_ok` / переход в maintenance не работают | Дисковые проверки выключены по умолчанию (`disk_space_check_interval=0s`) | Задайте `disk_space_check_interval` и `disk_space_threshold`; нужен грант `FILE` |
| `auto_rejoin` ломает binlogrouter | mariadbmon шлёт команды, которые binlogrouter не поддерживает | Не используйте `auto_rejoin`, если монитор наблюдает за binlogrouter |
| `discover-replicas` / `bootstrap` отказываются работать | Включена configuration synchronization | Отключите configuration synchronization для этого монитора |
| Монитор-скрипт зависает | Скрипт вызывает `alter monitor` / `stop monitor` / `call command` на своём же мониторе — deadlock | Скрипт не должен вызывать эти команды на мониторе, который его запустил |

## Best Practices

1.  **GTID обязателен.** Failover/switchover/rejoin работают только с GTID-репликацией; домен GTID не должен меняться во время операции; у реплик не должно быть локальных событий вне потока репликации.
2.  **Простые топологии.** Switchover и failover рассчитаны на 1 Primary + N реплик; сложные топологии (multi-primary, relay-цепочки, кольца) тестируйте отдельно перед применением в продакшене.
3.  **`auto_failover` + `auto_rejoin` + `cooperative_monitoring_locks=majority_of_running`** — базовая безопасная конфигурация для двух MaxScale. Для нескольких ЦОД — `majority_of_all` + semi-sync с максимальным `rpl_semi_sync_master_timeout`.
4.  **Semi-sync репликация** снижает риск потери данных при failover (но не устраняет: транзакция, подготовленная, но не подтверждённая репликой, фиксируется при crash recovery; на MariaDB 10.6.2+ улучшенная crash recovery удаляет такие транзакции — ситуация стала намного реже).
5.  **Перед плановым отключением Primary — всегда switchover**, а не просто остановка: контролируемое завершение не ждёт репликации на реплики и может потерять события.
6.  **`failover-safe`** (или `auto_failover=safe`) вместо `failover`, когда важна гарантия отсутствия потерь (проверка по GTID; неточна в пределах одного `monitor_interval`; главным образом защищает от постоянно отстающих реплик).
7.  **`promotion_sql_file`/`demotion_sql_file`** — для хуков (обновление VIP, уведомления, изменение конфигурации прокси). В `promotion_sql_file` не ставьте DML (может сломать репликацию от внешнего Primary); `demotion_sql_file` не должен содержать DML вообще (события могут не успеть реплицироваться до остановки потоков).
8.  **Не используйте `switchover-force`** в продакшене: игнорирует ошибки и может потерять события и сломать репликацию на всех репликах.
9.  **`maxctrl set server <server> maintenance --force`** — принудительное закрытие соединений (включая длинные транзакции) при выводе сервера в maintenance; без `--force` открытые транзакции завершаются штатно.
10. **Периодически отрабатывайте failover и switchover в staging** и следите за полем `primary` в `maxctrl show monitors` — мониторинг самого монитора. Оповещения о смене ролей — через монитор-скрипт (`script` + `events=master_down,new_master`).
11. **Не смешивайте `passive` и cooperative monitoring** — либо `passive=false`, либо не задавайте `passive` вовсе.

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — архитектура, установка, базовая конфигурация.
*   **[Read/Write Split](./maxscale_readwritesplit.md)** — поведение роутера при смене Primary (`master_failure_mode`, `master_reconnection`).
*   **[Механизмы Failover и Heartbeat](../../../Concepts/High_Availability/ha_failover_mechanisms.md)** — VRRP, Keepalived, теория failover.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera, Orchestrator, Keepalived в общей архитектуре HA.
*   **[Orchestrator](../../MySQL/orchestrator.md)** — альтернативный инструмент failover для классической репликации.
*   **[Привилегии для репликации](../replication/replication_privileges.md)** — гранты монитора по версиям MariaDB.
*   **[Ручной Switchover в MariaDB](../replication/switchover.md)** — server-side switchover без MaxScale.

### Официальная документация

*   [MariaDB Monitor (mariadbmon)](https://mariadb.com/docs/maxscale/reference/maxscale-monitors/mariadb-monitor.md) — полный справочник параметров и операций.
*   [Failover With Multiple MaxScales](https://mariadb.com/docs/maxscale/mariadb-maxscale-tutorials/failover-with-multiple-maxscales.md) — сравнение режимов координации.
*   [Automatic Failover With MariaDB Monitor](https://mariadb.com/docs/maxscale/mariadb-maxscale-tutorials/automatic-failover-with-mariadb-monitor.md) — пошаговый tutorial с ожидаемым выводом.
*   [Module Commands](https://mariadb.com/docs/maxscale/reference/maxscale-module-commands.md) — синтаксис module commands.
*   [Common Monitor Parameters](https://mariadb.com/docs/maxscale/reference/maxscale-monitors/common-monitor-parameters.md) — общие параметры мониторов (`monitor_interval`, `backend_timeout`, `script`, дисковые проверки).

Дополнительные операции mariadbmon, выходящие за рамки failover: `rebuild-server`, `create-backup`, `restore-from-backup` (запускаются как `async-rebuild-server` и т.п., требуют SSH-доступа с sudo на серверы) — в справочнике MariaDB Monitor, раздел Backup operations.
