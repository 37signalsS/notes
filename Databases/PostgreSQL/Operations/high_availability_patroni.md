# Отказоустойчивый кластер PostgreSQL (Patroni, etcd, HAProxy)

## Определения

**Patroni** — высокодоступный шаблон (Python-приложение) для управления кластерами PostgreSQL. Обеспечивает автоматический Failover, управление конфигурацией и мониторинг состояния инстансов. Он «оборачивает» процесс БД, превращая его в управляемый компонент HA-стека.

**etcd** — распределенное отказоустойчивое хранилище типа «ключ-значение». Используется Patroni как **DCS (Distributed Configuration Store)** для хранения состояния кластера, конфигурации и реализации механизма распределенных блокировок (Leader Election) на базе алгоритма консенсуса **Raft**.

**Watchdog** — механизм защиты («сторожевой таймер»), принудительно перезагружающий ОС в случае зависания Patroni или потери связи с DCS. Это гарантирует, что узел не останется мастером в изолированном состоянии, исключая возникновение **Split Brain**.

**Failover** — автоматический процесс переключения ролей в кластере при выходе из строя мастера.

**Switchover** — плановый и контролируемый перенос роли мастера на один из резервных узлов (например, для обслуживания железа или обновления ядра ОС).

**Fencing (Изоляция)** — метод принудительного отсечения старого мастера от ресурсов, чтобы предотвратить одновременную запись с двух узлов.

## Архитектура стека

Типовая схема включает 3 узла базы данных для обеспечения кворума в DCS.

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
| Patroni| | Patroni| | Patroni|
| Postgre| | Postgre| | Postgre|
|Watchdog| |Watchdog| |Watchdog|
    \          |          /
     \--- [ etcd кластер ] ---/
```

### Роли компонентов

1.  **PostgreSQL:** Непосредственно хранение и обработка данных. Работает в режиме `Primary` (чтение/запись) или `Replica` (только чтение, асинхронная или синхронная репликация).
2.  **Patroni:**
    -   Запускает и управляет процессом PostgreSQL.
    -   Удерживает **Leader Lock** в etcd через периодические Heartbeats (обычно каждые 10 секунд, настраивается через `loop_wait`).
    -   Взаимодействует с ядром через `/dev/watchdog` для обеспечения безопасности на уровне ОС.
    -   Предоставляет REST API для проверок состояния (порты 8008 по умолчанию: `/master`, `/replica`, `/primary`).
3.  **etcd:**
    -   Хранит конфигурацию кластера и текущую позицию WAL (LSN) каждого узла.
    -   Служит механизмом блокировок (Locks) для предотвращения ситуации "Split Brain".
    -   Обеспечивает консистентность состояния кластера.
4.  **HAProxy:**
    -   Опрашивает REST API Patroni на каждом узле.
    -   Узел, вернувший HTTP 200 на эндпоинт `/master` (или `/primary`), помечается как `UP` в пуле для записи.
    -   Узлы, вернувшие 200 на `/replica`, могут использоваться для балансировки запросов на чтение (Read Scaling).

## Механизмы защиты: Watchdog и Fencing

Критически важно предотвратить ситуацию, когда два узла одновременно считают себя мастерами (Split Brain).

1.  **Watchdog (Software/Hardware):** Patroni периодически "кормит" собаку (сбрасывает таймер `/dev/watchdog`). Если Patroni зависнет (например, из-за 100% CPU или OOM), таймер истечет, и Watchdog вызовет немедленную перезагрузку (Kernel Panic / Reboot), гарантированно освобождая лидерский ключ.
2.  **Fencing:** Если узел теряет связь с etcd, Patroni немедленно переводит PostgreSQL в режим `read-only` или выключает его. Это регулируется параметром `master_start_timeout`. Если Patroni не может подтвердить лидерство в течение заданного времени, он обязан остановить БД.

## Механизм Failover

Процесс переключения ролей происходит по следующему алгоритму:

1.  **Сбой мастера:** Мастер (Узел 1) падает или теряет сетевую связность с DCS.
2.  **Истечение TTL:** Leader Key в etcd имеет время жизни (TTL, обычно 30с). Поскольку Patroni на Узле 1 не может его обновить, ключ удаляется автоматически.
3.  **Выборы:** Patroni на репликах (Узел 2 и 3) замечают отсутствие мастера и начинают процесс выбора. Узел с наиболее актуальными данными (максимальным LSN) захватывает новый Leader Key.
4.  **Смена роли:** Выбранная реплика (например, Узел 2) переходит в режим `Master`.
5.  **Переключение трафика:** HAProxy при очередной проверке (раз в 2-3 секунды) видит, что Узел 1 недоступен, а Узел 2 теперь отвечает на запрос `/master`. Трафик мгновенно перенаправляется на Узел 2.

## Обеспечение отказоустойчивости балансировщика

Сам HAProxy может стать единой точкой отказа. Методы защиты:

-   **Keepalived (VRRP):** Несколько нод HAProxy разделяют один **Virtual IP (VIP)**. При падении активной ноды VIP переезжает на резервную за миллисекунды.
-   **DNS Round Robin:** За одним DNS-именем закреплено несколько IP-адресов балансировщиков. Клиент пробует их по очереди (менее надежно, зависит от TTL DNS).
-   **Headless Service (в Kubernetes):** Если приложение в K8s, оно может обращаться к Patroni напрямую через сервис, который обновляет свои Endpoints на основе проверок Patroni API.

---

## Практическая реализация

### 1. Подготовка окружения (Prerequisites)

- **ОС:** Рекомендуется Ubuntu 22.04+ или RHEL 8+.
- **Watchdog:** Убедитесь, что модуль `softdog` загружен (`modprobe softdog`) и доступен файл `/dev/watchdog`.
- **Сеть:** Открытые порты 5432 (DB), 8008 (API), 2379 (etcd).

### 2. Установка (на примере Ubuntu)

```bash
# PostgreSQL и Patroni
sudo apt install postgresql-16 python3-patroni python3-etcd3
# Или через pip для свежих версий
pip install patroni[etcd3]

# etcd (на 3-х узлах для кворума)
sudo apt install etcd
```

### 3. Пример конфигурации `patroni.yml`

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
    maximum_lag_on_failover: 1048576 # 1MB
    postgresql:
      use_pg_rewind: true
      parameters:
        wal_level: logical
        max_connections: 100
  initdb:
  - encoding: UTF8
  - data-checksums

postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.0.1:5432
  data_dir: /var/lib/postgresql/16/main
  bin_dir: /usr/lib/postgresql/16/bin
  authentication:
    replication: {username: replicator, password: rep_pass}
    superuser: {username: postgres, password: super_pass}

watchdog:
  mode: required
  device: /dev/watchdog
```

### 4. Настройка Health Check в HAProxy

```haproxy
listen postgres_master
    bind *:5432
    option httpchk GET /master
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server pg_node_1 10.0.0.1:5432 check port 8008
    server pg_node_2 10.0.0.2:5432 check port 8008
    server pg_node_3 10.0.0.3:5432 check port 8008
```

### 5. Сценарий: Синхронная репликация (Zero Data Loss)

Если бизнес-требования запрещают потерю даже одной транзакции (RPO=0):

```yaml
# Через patronictl edit-config
postgresql:
  parameters:
    synchronous_commit: "on"
  use_pg_rewind: true
  synchronous_mode: true
  synchronous_node_count: 1 # Минимум одна реплика должна подтвердить запись
```
*Внимание: Если ни одна реплика не доступна, мастер перестанет принимать запись (заблокирует транзакции) до восстановления связности.*

### 6. Сценарий: Обслуживание кластера (Maintenance Mode)

Для проведения технических работ без срабатывания failover:

```bash
# Пауза автоматики
patronictl -c /etc/patroni.yml pause pg_cluster

# Теперь можно безопасно останавливать сервисы
sudo systemctl stop patroni

# Снятие паузы
patronictl -c /etc/patroni.yml resume pg_cluster
```

### 7. Интеграция Patroni с S3 (WAL-архивирование и бэкапы)

Patroni нативно поддерживает интеграцию с S3-совместимыми хранилищами для WAL-архивирования и создания бэкапов через **pgBackRest** или **WAL-G**.

**Конфигурация WAL-G с S3 в Patroni (DCS):**

```yaml
# patronictl edit-config
postgresql:
  parameters:
    archive_mode: "on"
    archive_command: "wal-g wal-push %p"
    restore_command: "wal-g wal-fetch %f %p"
  
  # Настройки pgBackRest (альтернатива WAL-G)
  pgbackrest:
    command: /usr/bin/pgbackrest --stanza=main archive-push %p
    keep_data: true
    no_params: true
  
  # Или использование pgBackRest для полных бэкапов
  recovery_conf:
    restore_command: "pgbackrest --stanza=main archive-get %f %p"
```

**Переменные окружения для доступа к S3:**

```bash
# Должны быть доступны процессу PostgreSQL
export WALG_S3_PREFIX=s3://bucket-name/path/to/wal
export AWS_ACCESS_KEY_ID=<key>
export AWS_SECRET_ACCESS_KEY=<secret>
export AWS_ENDPOINT_URL=https://s3.yandexcloud.net  # Для Yandex Cloud
export AWS_S3_FORCE_PATH_STYLE=true  # Важно для MinIO и Yandex Cloud
```

**Принцип работы:**
1.  Каждый WAL-файл при завершении (16 МБ) автоматически загружается в S3.
2.  При failover/switchover новая реплика может восстановить недостающие WAL-сегменты из S3.
3.  Полные бэкапы (через `pgbackrest backup` или `wal-g backup-push`) также загружаются в S3.
4.  **Point-in-Time Recovery (PITR):** Позволяет восстановить базу на любой момент времени, используя полный бэкап + WAL-архив из S3.

**Patroni + S3 внутри Kubernetes:**
При развертывании Patroni в Kubernetes (через Zalando Operator или чарты), доступ к S3 осуществляется через:
- **Kubernetes Secret** с ключами доступа, монтируемый как volume или переменные окружения.
- **IAM-роли для Service Account (IRSA в AWS, Workload Identity в GCP)** — более безопасный подход без хранения статических ключей.

---

## Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Cluster has no leader** | etcd недоступен или потерян кворум. | Проверьте доступность `etcd` на порту 2379. Проверьте кворум: `etcdctl endpoint health`. |
| **Watchdog reboot loop** | Patroni не успевает сбросить таймер из-за нагрузки. | Увеличьте приоритет процесса Patroni (`nice -n -20`). Проверьте `loop_wait` и `ttl`. |
| **Node won't start (data_dir)** | Остались файлы от старого кластера. | Очистите `data_dir` (только для реплик!) и дайте Patroni сделать `basebackup`. |
| **Multiple Primaries** | Отсутствие Watchdog и проблемы в сети DCS. | Убедитесь, что `watchdog: mode: required`. Проверьте сетевые задержки. |

---

## Критерии выбора: Kubernetes vs ВМ

| Фактор | PostgreSQL в Kubernetes | PostgreSQL на ВМ |
| :--- | :--- | :--- |
| **Управление** | Через операторы (Zalando, CloudNativePG). | Ручное или через Ansible (Patroni). |
| **Автоматизация** | Встроена в оператор (самоисцеление, бэкапы). | Требует настройки внешних инструментов (Barman, WAL-G). |
| **Команда** | Подходит для продуктовых команд (DevOps-style). | Предпочтительно при наличии выделенного отдела DBA. |
| **Сложность** | Высокая (требует глубокого знания K8s Networking/Storage). | Средняя (классический стек). |
| **Fencing** | Lease API Kubernetes (облачный). | Аппаратный/Программный Watchdog. |

---

## Дополнительная информация

**См. также:**

- [Отказоустойчивость PostgreSQL](../Concepts/high_availability.md) — теория RPO/RTO и механизмы DCS.
- [Репликация в PostgreSQL](../Concepts/replication.md) — SSoT по типам репликации.
- [Обзор etcd](../../../etcd/architecture-and-concepts.md) — архитектура хранилища конфигураций.
- [Zalando Postgres Operator](./zalando_postgres_operator.md) — эксплуатация стека в Kubernetes.
- [Безопасная установка СУБД](../../installation_security.md) — общие принципы защиты баз данных.

**Инструменты:** `Patroni`, `etcd`, `HAProxy`, `Keepalived`, `Watchdog`, `patronictl`.
