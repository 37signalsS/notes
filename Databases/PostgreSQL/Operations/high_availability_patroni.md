# Отказоустойчивый кластер PostgreSQL (Patroni, etcd, HAProxy)

**Актуально для:** Patroni 4.1.x / PostgreSQL 14–18 (Patroni поддерживает PostgreSQL 9.3–18; etcd 3.5)

## Определения

**Patroni** — Python-шаблон (агент) для построения HA-кластеров PostgreSQL. «Обёртывает» процесс БД: управляет запуском/остановкой PostgreSQL, репликацией, выбором лидера и предоставляет REST API для балансировщиков и мониторинга. Начинался как fork Governor (проект Zalando). В качестве DCS поддерживает etcd, Consul, ZooKeeper, Kubernetes (Lease API) и Raft (встроенный).

**DCS (Distributed Configuration Store)** — распределённое консистентное хранилище, в котором Patroni хранит состояние кластера (конфигурацию, позиции WAL/LSN узлов) и реализует распределённую блокировку (**Leader Lock**). Детали консенсуса и защиты от двух лидеров — в [Обзоре Raft в etcd](../../../etcd/raft_consensus.md#механизм-против-двух-лидеров-anti-split-brain).

**Leader Lock / TTL** — ключ в DCS со сроком жизни `ttl` (по умолчанию 30 с). Мастер обязан обновлять его чаще, чем раз в `loop_wait` (по умолчанию 10 с). Истечение ключа — триггер автоматического failover.

**Watchdog** — сторожевой таймер (Linux watchdog device, `/dev/watchdog`). Patroni сбрасывает таймер после каждого успешного обновления Leader Lock; при зависании Patroni таймер истекает и ядро принудительно перезагружает узел, гарантированно освобождая лидерство.

**Failover** — автоматическое или ручное переключение роли при аварии мастера. Возможна потеря данных (незафиксированные и асинхронные транзакции).

**Switchover** — плановое контролируемое переключение роли (обслуживание железа, обновление ядра ОС). При синхронной репликации гарантирует RPO=0.

**Fencing (изоляция)** — принудительное отсечение старого мастера от записи: Patroni останавливает PostgreSQL (или переводит в read-only) при невозможности подтвердить лидерство в DCS.

**STONITH (Shoot The Other Node In The Head)** — аппаратный/hypervisor-level fencing (IPMI/iDRAC/iLO, BMC watchdog): принудительное отключение проигравшего узла при split-brain.

**Split Brain** — состояние, при котором два и более узла одновременно считают себя Primary и принимают запись. Для PostgreSQL необратимо: таймлайны расходятся, автоматический слияние невозможно.

## Базовые концепции

### Архитектура стека

Типовая схема — 3 узла (нечётный кворум для DCS):

```text
      [ Клиент / Приложение ]
               |
        [ VIP / DNS Name ]
               |
      [ HAProxy + Keepalived ] (2-3 ноды)
               |
     -----------------------
     |          |          |
 [ Узел 1 ] [ Узел 2 ] [ Узел 3 ]
 | Patroni | | Patroni | | Patroni |
 | Postgre| | Postgre| | Postgre|
 |Watchdog| |Watchdog| |Watchdog|
     \          |          /
      \--- [ etcd кластер ] ---/
```

**Роли компонентов:**

1. **PostgreSQL** — хранение и обработка данных. Работает как `Primary` (чтение/запись) или `Replica` (только чтение, streaming-репликация).
2. **Patroni** — запускает и управляет процессом PostgreSQL; удерживает Leader Lock в DCS через heartbeats (`loop_wait`); взаимодействует с `/dev/watchdog`; предоставляет REST API (порт 8008 по умолчанию).
3. **etcd (DCS)** — хранит конфигурацию кластера, текущие позиции WAL (LSN) узлов и Leader Lock; обеспечивает консистентность и кворум (Raft). Альтернативы: Consul, ZooKeeper, Kubernetes Lease API.
4. **HAProxy** — опрашивает REST API Patroni: узел, вернувший HTTP 200 на `/primary` (или `/` или `/read-write`), попадает в пул для записи; узлы с 200 на `/replica` — в пул для чтения (Read Scaling).

### Как работает выбор лидера и защита от Split Brain

1. **Leader Lock (DCS-кворум).** Только узел, успешно захвативший и обновляющий Leader Key, может быть Primary. При сетевой партиции кворум сохраняется только у majority-части etcd — меньшинство не может ни выбрать, ни удержать лидера.
2. **Watchdog.** Активируется Patroni **до** промоции в Primary; если активация невозможна, а `watchdog.mode: required` — узел **отказывается** становиться лидером. При зависании Patroni (OOM, 100% CPU, зависание hypervisor) таймер истекает и ядро перезагружает узел. По умолчанию watchdog настроен истечь на 5 с раньше TTL (`safety_margin`), что оставляет HA-циклу `ttl - safety_margin - loop_wait` секунд на завершение до принудительного сброса. Значение `safety_margin: -1` устанавливает тайм-аут watchdog в `ttl // 2` — гарантия срабатывания при любых обстоятельствах. В состоянии `pause` watchdog отключается.
3. **Fencing.** Если обновление Leader Lock невозможно, Patroni останавливает PostgreSQL (или демотирует его), поэтому узел не может принимать запись без кворума DCS.
4. **`primary_start_timeout` (по умолчанию 300 с)** — время, которое Primary может «восстанавливаться» после сбоя, прежде чем будет инициирован failover. Худшее время failover при отказе мастера: `loop_wait + primary_start_timeout + loop_wait` (с дефолтами — до ~320 с; при `primary_start_timeout: 0` — около `loop_wait`). Это компромисс RTO vs. риск потери данных: чем быстрее failover, тем выше шанс промоции отстающей реплики.
5. **`maximum_lag_on_failover`** (по умолчанию 1048576 байт) — максимальный лаг реплики (в байтах), при котором она допускается к участию в выборах лидера.

**Программный vs аппаратный Watchdog.** `softdog` (kernel module) защищает от зависаний процессов и большинства сбоев ядра и достаточен для большинства случаев; он зависит от работоспособности ядра и не спасает при hard lockup или аппаратном сбое. Hardware-watchdog на BMC (iDRAC/iLO/IPMI) независим от ОС — предпочтителен на физических серверах.

### Синхронный режим (RPO=0)

`synchronous_mode` принимает значения `off`, `on`, `quorum` (quorum-based sync replication, PostgreSQL 10+). В этом режиме Patroni сам управляет `synchronous_standby_names`, и в выборах лидера участвуют только последний известный лидер или синхронные реплики — успешно зафиксированные транзакции не теряются при failover.

- `synchronous_node_count` (по умолчанию 1) — сколько синхронных standby требуется.
- `synchronous_mode_strict: true` — при отсутствии доступной синхронной реплики **запись блокируется** (вместо автоматического отключения синхронности). Без `strict` Patroni временно переводит коммиты в асинхронный режим, пока нет подходящей sync-реплики.

### Статическая и динамическая конфигурация

- **Статическая** (`patroni.yml` на каждом узле) — адреса DCS, `data_dir`, порты, учётные записи. Изменяется в файле и применяется через `patronictl reload` (аналог SIGHUP).
- **Динамическая** (хранится в DCS) — `ttl`, `loop_wait`, `maximum_lag_on_failover`, `postgresql.parameters` и пр. Изменяется через `patronictl edit-config` или `PATCH /config` и применяется на всех узлах. Параметры, требующие перезапуска PostgreSQL (например, `max_connections`), помечаются флагом `pending_restart` до выполнения `patronictl restart`.

## Предварительные требования

- **ОС:** Ubuntu 22.04+ / RHEL 8+ (Rocky/Alma 9); Python 3.9+ для Patroni 4.x.
- **Узлы:** нечётное число (3 или 5) для PostgreSQL + etcd; обычно co-located на одних хостах. 2 узла etcd не дают кворума при отказе одного — недопустимо.
- **Watchdog:** `modprobe softdog`, доступен `/dev/watchdog` с правами пользователя Patroni (`chown postgres /dev/watchdog`); на железных серверах — BMC-watchdog.
- **Сеть:** порты 5432 (DB), 8008 (REST API), 2379 (etcd client), 2380 (etcd peer); стабильная связь между узлами (латентность < 10 мс, потери < 0.1%); синхронизация времени (NTP).
- **PostgreSQL:** одинаковые `max_connections`, `max_wal_senders`, `max_replication_slots` на всех узлах; `wal_level: replica` минимум (`logical` — только если нужна логическая репликация); для `pg_rewind` (возврат старого мастера репликой) необходимы data checksums (`initdb --data-checksums`) или `wal_log_hints: on`.
- **Учётные записи:** Patroni требует superuser и replication-пользователя; рекомендуется `password_encryption: scram-sha-256`.

## Практические сценарии

### 1. Установка

```bash
# Debian/Ubuntu (пакет называется patroni)
sudo apt install postgresql-16 patroni etcd haproxy

# Или свежая версия через pip (Patroni 4.x)
pip install "patroni[etcd3,psycopg3]"   # extras: etcd3, consul, zookeeper, kubernetes, raft, aws, systemd

patroni --version                          # → Patroni 4.1.5
```

etcd ставится на все 3 узла; настройка кластера etcd описана в [Конфигурации и деплое etcd](../../../etcd/configuration_and_deployment.md). Проверка:

```bash
etcdctl endpoint health --cluster          # → все узлы "healthy"
```

### 2. Конфигурация `patroni.yml` (узел 1)

```yaml
scope: pg_cluster
name: pg_node_1
namespace: /db/

etcd3:
  hosts: ["10.0.0.1:2379", "10.0.0.2:2379", "10.0.0.3:2379"]

restapi:
  listen: 0.0.0.0:8008
  connect_address: 10.0.0.1:8008

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true        # по умолчанию false; требует data-checksums или wal_log_hints
      parameters:
        wal_level: replica
        max_connections: 100
        max_wal_senders: 10
        max_replication_slots: 10
  initdb:
  - encoding: UTF8
  - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.0.1:5432
  data_dir: /var/lib/postgresql/16/main
  bin_dir: /usr/lib/postgresql/16/bin
  pg_hba:                                    # Patroni сам генерирует pg_hba.conf
  - host replication replicator 10.0.0.0/24 scram-sha-256
  - host all all 10.0.0.0/24 scram-sha-256
  authentication:
    replication: {username: replicator, password: rep_pass}
    superuser: {username: postgres, password: super_pass}

watchdog:
  mode: required
  device: /dev/watchdog
```

Запуск на каждом узле (имя и `connect_address` — свои):

```bash
sudo systemctl enable --now patroni
sudo systemctl status patroni                # → active (running)
journalctl -u patroni -f                     # логи Patroni (stdout/journal, если не задан logfile)
```

### 3. Health Check в HAProxy

```haproxy
listen postgres_master
    bind *:5432
    option httpchk GET /primary
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server pg_node_1 10.0.0.1:5432 check port 8008
    server pg_node_2 10.0.0.2:5432 check port 8008
    server pg_node_3 10.0.0.3:5432 check port 8008

listen postgres_replicas
    bind *:5433
    option httpchk GET /replica
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server pg_node_1 10.0.0.1:5432 check port 8008
    server pg_node_2 10.0.0.2:5432 check port 8008
    server pg_node_3 10.0.0.3:5432 check port 8008
```

Полезные эндпоинты для проверок: `/primary` (200 только у лидера с лидерским ключом), `/replica` (200 у здоровой реплики без тега `noloadbalance`), `/replica?lag=10MB` (дополнительная проверка лага), `/sync` (синхронный standby), `/health` (PostgreSQL запущен), `/liveness` и `/readiness?lag=&mode=apply|write` (для зондирования), `/patroni` (JSON-статус узла), `/metrics` (Prometheus).

Отказоустойчивость самого HAProxy: **Keepalived (VRRP)** с плавающим VIP между 2–3 нодами (переезд за миллисекунды) или DNS с коротким TTL (менее надёжно). В Kubernetes — обращение к Patroni напрямую через сервис; см. [Zalando Postgres Operator](./zalando_postgres_operator.md).

### 4. Switchover (плановое переключение)

```bash
patronictl -c /etc/patroni.yml switchover pg_cluster --candidate pg_node_2
# → Current cluster topology ... Successfully switched over to "pg_node_2"
```

Кандидат необязателен — тогда в выборах участвуют все здоровые узлы. Switchover можно запланировать (`--scheduled <timestamp>`), отменить — `patronictl flush pg_cluster switchover`.

### 5. Failover (аварийное переключение)

```bash
patronictl -c /etc/patroni.yml failover pg_cluster --candidate pg_node_2 --force
```

`--candidate` обязателен. Предназначен для нездорового кластера (нет лидера, нет sync-standby); **может привести к потере данных**, если кандидат отстаёт — в здоровом кластере используйте switchover. Автоматический failover запускается по истечении TTL Leader Key без участия оператора.

### 6. Синхронная репликация (Zero Data Loss)

```bash
patronictl -c /etc/patroni.yml edit-config pg_cluster
```
```yaml
postgresql:
  synchronous_mode: "on"
  synchronous_mode_strict: "true"   # блокирует запись при отсутствии sync-реплики
  synchronous_node_count: 1
```

*Внимание: с `strict` при потере единственной синхронной реплики мастер перестаёт принимать запись до восстановления связности; без `strict` коммиты временно становятся асинхронными.*

### 7. Maintenance Mode (обслуживание без срабатывания failover)

```bash
patronictl -c /etc/patroni.yml pause pg_cluster --wait   # → Success: cluster management is paused
sudo systemctl stop patroni                              # безопасно останавливать узлы
patronictl -c /etc/patroni.yml resume pg_cluster         # автоматика возобновлена
```

### 8. Перезапуск, reload, пересборка реплики

```bash
patronictl -c /etc/patroni.yml reload pg_cluster          # применить изменённый patroni.yml (SIGHUP)
patronictl -c /etc/patroni.yml restart pg_cluster --pending --force   # только узлы с pending_restart
patronictl -c /etc/patroni.yml reinit pg_cluster pg_node_3 --from-leader --wait --force  # пересобрать data_dir
```

Прямой `pg_ctl restart` / `systemctl restart postgresql` обходит Patroni и ломает управление состоянием — используйте `patronictl restart/reload`.

### 9. DR: standby cluster (репликация кластера на удалённую площадку)

```bash
patronictl -c /etc/patroni.yml demote-cluster pg_cluster --host 10.1.0.10 --port 5432 --primary-slot-name pg_cluster --force
# кластер становится standby-cluster, следующим за удалённым Primary
patronictl -c /etc/patroni.yml promote-cluster pg_cluster --force   # обратное преобразование
```

### 10. WAL-архивирование и бэкапы

Patroni сам по себе не заменяет бэкапы: он обеспечивает HA и failover, но не PITR. WAL-архивирование (`archive_mode`/`archive_command`) и полные бэкапы настраиваются через динамическую конфигурацию (`postgresql.parameters`) с помощью **pgBackRest** или **WAL-G**; интеграция pgBackRest с Patroni нативна (секция `postgresql.pgbackrest`). Подробности, конфигурации и сценарии восстановления — в [Бэкапах и восстановлении](../Concepts/backup_and_recovery.md) (SSoT по бэкапам) и [Автоматизации бэкапов](./backup_automation.md).

### 11. Деактивация кластера (cleanup)

```bash
patronictl -c /etc/patroni.yml remove pg_cluster
# → потребует ввести имя кластера, "Yes I am aware" и имя лидера; удаляет информацию кластера из DCS
```

Перед удалением остановите Patroni на всех узлах. Удаление единичного узла: остановите `patroni` на нём — его ключ в DCS истечёт через `ttl`, а репликационный слот удалится через `member_slots_ttl` (30 мин по умолчанию).

## Валидация

```bash
patronictl -c /etc/patroni.yml list pg_cluster
# + Cluster: pg_cluster (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
# | Member    | Host          | Role  | State    | TL | Receive LSN | Lag | Replay LSN | Lag |
# | pg_node_1 | 10.0.0.1:5432 | Leader | running  | 5  |             |     |            |     |
# | pg_node_2 | 10.0.0.2:5432 | Replica | streaming| 5  | 0/40004E8   | 0   | 0/40004E8  | 0   |
# +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+

curl -s http://localhost:8008/patroni | jq .role,.state,.timeline
# → "primary" (только на лидере) / "replica"; "running"; номер таймлайна

curl -s http://localhost:8008/metrics | grep -E 'patroni_primary|patroni_postgres_running|patroni_cluster_unlocked'
# → patroni_primary{scope="pg_cluster",name="pg_node_1"} 1
# → patroni_postgres_running{...} 1
# → patroni_cluster_unlocked{...} 0        (0 = кластер заблокирован лидером — нормально)

patronictl -c /etc/patroni.yml history pg_cluster   # → история failover/switchover: TL, LSN, Reason, Timestamp, New Leader
```

SQL-проверки на каждом узле:

```sql
SELECT pg_is_in_recovery();                          -- → false только на одном узле (Primary)
SELECT pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn();  -- → t на догнавшей реплике
SELECT application_name, state, sync_state FROM pg_stat_replication;  -- → streaming, sync_state = async/quorum/sync
```

HAProxy: `echo "show stat" | socat /var/run/haproxy.sock stdio | grep postgres` — в колонке status не более одного `UP` среди мастер-пула.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Cluster has no leader** | etcd недоступен или потерян кворум | `etcdctl endpoint health --cluster -w table`; проверьте кворум etcd (нечётное число узлов); восстановление etcd — в [etcd: аварийное восстановление](../../../etcd/emergency_recovery.md) |
| **Failover затягивается (~5 мин)** | `primary_start_timeout` по умолчанию 300 с — Primary «восстанавливается» до триггера failover | Уменьшите `primary_start_timeout` (вплоть до 0 — мгновенный failover) при готовности рисковать данными; помните компромисс RTO/данные |
| **Watchdog reboot loop** | Patroni не успевает сбросить таймер (нагрузка, нехватка ресурсов) | Приоритет процесса (`nice`/`ionice`), ресурсы VM; проверьте правило `loop_wait + 2*retry_timeout <= ttl`; для тестов `soft_noboot=1` (таймер только логируется в dmesg) |
| **Node won't start (data_dir)** | Остались файлы старого кластера | Только для реплик: `patronictl reinit <cluster> <member> --force` — Patroni снимет basebackup |
| **Multiple Primaries** | Не сработали Watchdog/Fencing | 1) аппаратно отключить проигравший узел (IPMI/BMC); 2) очистить его `data_dir` и перезапустить Patroni (basebackup от нового мастера); 3) проверить `watchdog: mode: required`; 4) аудит потерь по WAL/`patronictl history` |
| **Patroni не останавливает PostgreSQL при потере DCS** | Watchdog не активен / нет прав на `/dev/watchdog` | Проверьте `ls -l /dev/watchdog` и `lsmod \| grep softdog`; `watchdog: mode: required` |
| **Реплика не участвует в выборах** | Лаг > `maximum_lag_on_failover`, тег `nofailover`, или таймлайн меньше кластерного (`check_timeline`) | `patronictl list` покажет лаг; ускорьте диски реплики или поднимите порог; снимите тег |
| **`pending_restart` не снимается** | Параметры требуют перезапуска PostgreSQL | `patronictl restart <cluster> --pending --force` |
| **Реплика навсегда отстала** | Слот удалён после `member_slots_ttl` (30 мин), WAL переработан | `patronictl reinit`; для постоянных слотов — секция `slots` в конфиге |
| **pg_rewind не срабатывает при возврате узла** | Нет data checksums и `wal_log_hints: off` | Инициализируйте кластер с `--data-checksums` (или включите `wal_log_hints`) — иначе Patroni снимает полную basebackup |

## Пограничные случаи

- **Потеря кворума etcd** (упали 2 из 3 узлов): оставшийся узел не может обновить Leader Lock — Patroni останавливает PostgreSQL на всех узлах (watchdog при необходимости перезагружает узел). Кластер недоступен до восстановления etcd; это корректное поведение, защита от split-brain, а не дефект.
- **DCS failsafe mode** (`failsafe_mode: true`): бывший лидер может продолжить работу как Primary при недоступности DCS — только для специфических DR-сценариев, повышает риск split-brain; по умолчанию выключен.
- **Чётное число узлов**: 2 узла etcd теряют кворум при отказе любого одного — используйте 3 или 5.
- **Синхронный режим без `strict`**: при отсутствии sync-standby коммиты временно становятся асинхронными (доступность важнее гарантии); с `strict` — запись блокируется (гарантия важнее доступности).
- **`/replica` и теги**: эндпоинт возвращает 200 только при отсутствии тега `noloadbalance` — так узел исключают из пула чтения без остановки репликации. Теги `nofailover` (не участвует в выборах), `clonefrom` (предпочитается для basebackup), `nostream` (не копирует постоянные логические слоты).
- **Постоянные слоты** (`slots` в динамическом конфиге): сохраняются при failover/switchover; физические синхронизируются на все узлы каждые `loop_wait` секунд. Внимание: постоянные логические слоты синхронизируются только от Primary — их использование на репликах вызывает неограниченный рост `pg_wal`.
- **Логи Patroni**: по умолчанию в systemd journal (`journalctl -u patroni`); файл — при заданном `logfile` в `patroni.yml`.
- **Kubernetes как DCS**: Patroni может использовать Lease API Kubernetes вместо etcd — см. [Zalando Postgres Operator](./zalando_postgres_operator.md); эндпоинты `/liveness` и `/readiness` предназначены для зондов K8s.

## Лучшие практики

1. **`watchdog: mode: required`** — обязательно в production; `off`/`automatic` оставляют окно для split-brain.
2. **Правило таймеров**: `loop_wait + 2 * retry_timeout <= ttl` (дефолты 10 + 2×10 = 30 удовлетворяют ему); `ttl` минимум 20 с, `retry_timeout` минимум 3 с.
3. **Нечётный кворум** 3 (или 5) узлов etcd + PostgreSQL; регулярно тестируйте switchover — это плановое обслуживание, а не авария.
4. **Не правьте `postgresql.conf` вручную** — только через `patronictl edit-config` / `PATCH /config`; иначе конфигурация расойдётся между узлами.
5. **Мониторинг** (Prometheus-метрики `/metrics`): `patroni_primary` (1 ровно на одном узле), `patroni_postgres_running`, `patroni_xlog_replayed_location` (лаг), `patroni_cluster_unlocked`, `patroni_dcs_last_seen` (свежесть связи с DCS), `patroni_pending_restart`, `patroni_is_paused`.
6. **Автоматическая проверка split-brain** (cron/systemd timer):

    ```bash
    #!/bin/bash
    # /usr/local/bin/patroni_splitbrain_check.sh
    PRIMARIES=$(for node in 10.0.0.1 10.0.0.2 10.0.0.3; do
        curl -sf http://$node:8008/patroni | jq -r .role
    done | grep -c '^primary$')

    if [ "$PRIMARIES" -gt 1 ]; then
        echo "CRITICAL: Multiple primaries detected ($PRIMARIES)" | mail -s "PATRONI SPLIT-BRAIN" ops@example.com
        exit 2
    elif [ "$PRIMARIES" -eq 0 ]; then
        echo "WARNING: No primary detected" | mail -s "PATRONI NO PRIMARY" ops@example.com
        exit 1
    fi
    echo "OK: Single primary"
    ```

7. **Бэкап etcd** — без DCS кластер неуправляем: стратегии резервного копирования etcd — в [Backup strategies for etcd](../../../etcd/backup_strategies.md).
8. **Безопасность REST API**: привязывайте `restapi.listen` к внутреннему интерфейсу или настраивайте `restapi.authentication`; дамп состояния и управление кластером доступны через API.
9. **План отката** при switchover: обратный switchover на прежний узел (`patronictl switchover --candidate <старый_мастер>`) после проверки работоспособности нового лидера.

## Дополнительная информация

**См. также:**

- [Отказоустойчивость PostgreSQL](../Concepts/high_availability.md) — теория RPO/RTO, жизненный цикл failover, сравнение Patroni/CloudNativePG/repmgr.
- [Репликация в PostgreSQL](../Concepts/replication.md) — типы репликации, слоты, `pg_rewind`.
- [Обзор etcd](../../../etcd/architecture-and-concepts.md) — архитектура DCS; [Raft и консенсус](../../../etcd/raft_consensus.md) — механизм против двух лидеров.
- [Бэкапы и восстановление](../Concepts/backup_and_recovery.md) — WAL-архивирование, PITR, pgBackRest/WAL-G.
- [Zalando Postgres Operator](./zalando_postgres_operator.md) — тот же стек в Kubernetes.
- [Безопасная установка СУБД](../../installation_security.md) — общие принципы защиты баз данных.

**Инструменты:** `Patroni`, `etcd`, `HAProxy`, `Keepalived`, `Watchdog (softdog/BMC)`, `patronictl`, `pgBackRest`, `WAL-G`.

**Внешние источники:** [Patroni documentation](https://patroni.readthedocs.io/) (configuration, REST API, patronictl, watchdog), [GitHub patroni/patroni](https://github.com/patroni/patroni) (release notes).
