# Высокая доступность MySQL (High Availability)

**Актуально для:** MySQL 8.4 LTS (последний релиз 8.4.12, 2026-08-18), InnoDB Cluster, Group Replication, Orchestrator 4.31.1+, MySQL Router 26.7.0+, ProxySQL 3.0.11+

> **Примечание по версии:** на дату правки (2026-10-10) последний релиз линейки MySQL 8.4 — 8.4.12. Следующий LTS — MySQL 9.7 (GA с апреля 2026); путь апгрейда: 8.4.x → 9.7.x, прыжки через LTS-линейку не поддерживаются.
>
> **Orchestrator (2026):** проект перешёл под управление ProxySQL (анонс от 2026-04-09), после периода архивирования. Последний релиз — 4.31.1 (2026-07-28). Новые возможности 4.30+: встроенные Prometheus-метрики, health-эндпоинты (`/health/live`, `/health/ready`, `/health/leader`), нативная интеграция с ProxySQL hostgroups в конфигурации Orchestrator, настройка `FailRecoveryOnFailedPostFailoverProcesses`.
>
> **MySQL Router (2026):** с релиза 26.7.0 (2026-07-28) Router перешёл на единую модель версий; серии 8.4 и 9.7 прекращены. Router 26.7.0 совместим со всеми поддерживаемыми версиями MySQL Server (8.4, 9.7, 26.7). Последний релиз в 8.4-линейке — 8.4.10 (2026-06-16).
>
> **ProxySQL:** последняя стабильная версия — 3.0.11 (2026-08-27); также доступны 3.1.11 (Innovative) и 4.0.11 (Plugin Chassis).

---

## Определения

**Group Replication** — встроенный механизм MySQL для организации отказоустойчивого кластера с синхронной репликацией и автоматическим failover. Использует протокол консенсуса Paxos для гарантии согласованности данных на всех узлах кластера. Поддерживает два режима работы: **single-primary** (один узел принимает запись, остальные — read-only) и **multi-primary** (все узлы принимают запись, транзакции проходят сертификацию на конфликты).

**InnoDB Cluster** — полноценное решение HA от Oracle, объединяющее Group Replication, MySQL Router и метаданные кластера в единую управляемую систему. MySQL Router автоматически обнаруживает лидера кластера и направляет трафик на активный узел, обеспечивая прозрачный failover для приложений.

**MySQL Router** — легковесный прокси, который работает как точка входа в InnoDB Cluster. Он читает метаданные кластера через MySQLX Protocol и автоматически обновляет маршрутизацию при смене лидера. Поддерживает режимы **read-write** (трафик только на лидер) и **read-only** (трафик распределяется по всем узлам).

**Orchestrator** — внешний инструмент для управления топологией репликации и автоматического failover классической асинхронной/полусинхронной репликации. Поддерживает сложные деревья репликации (chain, fan-in, tree) и может автоматически перестраивать топологию после сбоя. Работает через Raft-кластер для собственной HA.

**ProxySQL** — высокопроизводительный прокси-сервер для MySQL, выполняющий read/write split, connection pooling и автоматический failover. В связке с Orchestrator обеспечивает прозрачное переключение трафика при сбое мастера.

**Split-Brain (Расщепление мозга)** — состояние, при котором два узла одновременно считают себя лидером и принимают запись. В Group Replication предотвращается механизмом сертификации транзакций и кворумом Paxos. В классической репликации предотвращается Orchestrator через анализ состояния через реплики.

---

## Предварительные требования

### Аппаратные требования

| Компонент | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядер |
| **RAM** | 4 ГБ | 16+ ГБ (зависит от рабочего набора данных) |
| **Диск** | 50 ГБ SSD | NVMe SSD (минимум 100 ГБ) |
| **Сеть** | 100 Мбит/с | 1 Гбит/с (для Group Replication — между всеми узлами) |

### Программные требования

- **MySQL Server** — версия 8.4 LTS (Group Replication стабилен с 8.0.14+)
- **MySQL Router** — версия 26.7.0+ (для InnoDB Cluster; совместим с 8.4/9.7/26.7)
- **Orchestrator** — версия 4.31.1+ (для классической репликации)
- **ProxySQL** — версия 3.0.11+ (опционально, для read/write split; см. [ProxySQL: Обзор](./ProxySQL/proxysql_overview.md))
- **NTP/Chrony** — синхронизация времени на всех узлах (дрейф < 100 мс)

### Требования Group Replication

Group Replication накладывает жёсткие требования к конфигурации узлов. Нарушение любого из них блокирует присоединение к кластеру или приводит к нестабильной работе.

**Движок и таблицы:**
- Все таблицы — только в **InnoDB**. Использование других движков (включая временные `MEMORY`) вызывает ошибки. Заблокировать их можно через `disabled_storage_engines=MEMORY,MyISAM,...`.
- Каждая реплицируемая таблица должна иметь **первичный ключ** (или эквивалент — ненулевой уникальный индекс). Group Replication использует его для идентификации строк при проверке конфликтов. Собственные проверки GR не используют `sql_require_primary_key`, но могут быть несовместимы с ним.

**Репликационная инфраструктура:**
- `gtid_mode=ON`, `enforce_gtid_consistency=ON` — GTID обязательны для отслеживания транзакций.
- `binlog_format=ROW` — в MySQL 8.4 это дефолт. Обязателен для детекции конфликтов.
- `log_replica_updates=ON` — в MySQL 8.4 дефолт. Необходимо для distributed recovery через бинарный лог донора.
- `binlog_checksum` — в MySQL 8.4 поддерживается значение по умолчанию (`CRC32`); в более старых версиях требовалось `NONE`.
- `replica_parallel_workers` — параллельные апplier'ы включены по умолчанию (4 потока, максимум 1024). При `replica_parallel_workers=0` параллельность отключается. Обязателен `replica_preserve_commit_order=ON` для сохранения порядка коммита.

**Сеть:**
- Все узлы должны иметь прямую двустороннюю связность друг с другом (IPv4, IPv6 или смешанно). VPN не мешает.
- Порт для внутренней коммуникации — `33061` (рекомендуется). Он отличается от client-порта `3306` и не должен использоваться приложениями.
- `group_replication_local_address` — уникальный для каждого узла. Должен разрешаться всеми участниками (IP или FQDN через DNS/`/etc/hosts`). При одинаковых hostname на разных узлах используйте `report_host`.
- Задержка между узлами — **< 100 мс**, рекомендуемый лимит для стабильной работы. При более высоких — используйте классическую репликацию.

**Дополнительные настройки:**
- `default_table_encryption` — одинаковое значение на всех узлах. Менять его нельзя во время работы GR.
- `lower_case_table_names` — одинаковое значение на всех узлах. Рекомендуется `1` для InnoDB.
- `xa_detach_on_prepare=ON` — дефолт, не рекомендуется отключать на узлах GR.
- `disabled_storage_engines` — рекомендуется задать для предотвращения использования не-InnoDB таблиц.

**Distributed recovery** — процесс присоединения нового узла к кластеру. Выполняется через:
- **CLONE plugin** — полная копия данных (по умолчанию, если доступен).
- **Бинарный лог донора** —增量 синхронизация (state transfer).

Для distributed recovery настраивается отдельный набор SSL-переменных (`group_replication_recovery_ssl_*`), даже если основная коммуникация не шифруется. По умолчанию distributed recovery не использует SSL.

### Сетевые требования

- Все узлы Group Replication должны иметь прямую сетевую связность друг с другом
- Порты: `3306` (MySQL), `33060` (MySQL X Protocol), `6446` (MySQL Router), `3000` (Orchestrator Web GUI), `10008` (Orchestrator Raft)
- Минимальная задержка между узлами: **< 10 мс** (в пределах одного дата-центра)

---

## Основные концепции

### Архитектура InnoDB Cluster

```
┌─────────────────────────────────────────────────────────┐
│              InnoDB Cluster (3 узла)                      │
├─────────────────────────────────────────────────────────┤
│  MySQL Router (6446)                                     │
│       │                                                  │
│       ├──► MySQL Primary (порт 3306)                     │
│       │    - Принимает записи                             │
│       │    - Применяет транзакции                         │
│       │                                                  │
│       ├──► MySQL Secondary 1 (read-only)                 │
│       │    - Реплицирует данные                          │
│       │    - Может быть повышен до Primary                │
│       │                                                  │
│       └──► MySQL Secondary 2 (read-only)                 │
│            - Реплицирует данные                          │
│            - Может быть повышен до Primary                │
└─────────────────────────────────────────────────────────┘
```

**Компоненты:**
1. **Group Replication** — обеспечивает синхронную репликацию и консенсус
2. **MySQL Router** — точка входа для приложений, автоматический failover
3. **MySQL Shell** — управление кластером (создание, добавление узлов, проверка состояния)

### Режимы работы Group Replication

| Режим | Описание | RPO | RTO | Применение |
| :--- | :--- | :--- | :--- | :--- |
| **Single-Primary** | Один узел принимает записи, остальные — read-only | 0 | Секунды | Стандарт для production |
| **Multi-Primary** | Все узлы принимают записи, сертификация транзакций | 0 | Секунды | Требует обработки конфликтов |

### Механизм консенсуса Paxos

Group Replication использует модифицированный протокол **Paxos** для гарантии согласованности:
1. Транзакция отправляется на узел кластера
2. Узел распространяет транзакцию среди всех участников
3. Каждый узел проверяет транзакцию на конфликты (Certification)
4. При отсутствии конфликтов транзакция фиксируется на большинстве узлов (кворум)
5. Транзакция считается успешной

**Преимущества:**
- **RPO = 0** — данные не теряются при сбое
- **Автоматический failover** — при отказе Primary новый лидер выбирается автоматически (обычно < 10 секунд)
- **Гарантия согласованности** — все узлы видят одни и те же данные

### Сравнение подходов к HA в MySQL

| Подход | Тип репликации | RPO | RTO | Сложность | Применение |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Group Replication** | Синхронная (Paxos) | 0 | < 10 сек | Средняя | InnoDB Cluster, critical systems |
| **Classic + Orchestrator** | Асинхронная/Полусинхронная | > 0 | 30-60 сек | Средняя | Высоконагруженные системы |
| **ProxySQL + Orchestrator** | Асинхронная/Полусинхронная | > 0 | 10-30 сек | Высокая | Микросервисы, read/write split |

### Failover в Orchestrator

Orchestrator определяет состояние мастера не только по прямому ping, но и по активности реплик: если реплики продолжают получать binlog-события, мастер считается живым. Это защищает от ложных failover при сетевых проблемах между Orchestrator и мастером.

**Процесс failover:**
1. Orchestrator определяет, что мастер недоступен
2. Выбор лучшей реплики для promotion (на основе replication lag, GTID, версии)
3. Автоматическое повышение реплики до мастера
4. Переподключение остальных реплик к новому мастеру
5. Обновление ProxySQL hostgroups (если используется)
6. Уведомление через API/веб-интерфейс

---

## Практические сценарии

### Сценарий 1: Развертывание InnoDB Cluster (Single-Primary)

#### Шаг 1: Установка MySQL Server на всех узлах

```bash
# Установка MySQL 8.4 LTS (RHEL/Rocky/Alma)
sudo dnf install -y mysql-server

# Настройка my.cnf (на всех узлах)
cat <<EOF | sudo tee -a /etc/my.cnf.d/server.cnf
[mysqld]
server-id = 1  # Уникальный на каждом узле: 1, 2, 3
gtid_mode = ON
enforce_gtid_consistency = ON
binlog_format = ROW
log_bin = binlog
log_replica_updates = ON
default_authentication_plugin = caching_sha2_password
disabled_storage_engines = MEMORY,MyISAM
EOF

# Запуск MySQL
sudo systemctl enable --now mysqld
```

#### Шаг 2: Создание пользователя для кластера

```sql
CREATE USER 'cluster_admin'@'%' IDENTIFIED BY 'StrongClusterPass123!';
GRANT CLONE_ADMIN, GROUP_REPLICATION_ADMIN, BACKUP_ADMIN, 
    PERSIST_RO_VARIABLES_ADMIN, REPLICATION SLAVE, REPLICATION CLIENT 
    ON *.* TO 'cluster_admin'@'%';
FLUSH PRIVILEGES;
```

#### Шаг 3: Инициализация кластера через MySQL Shell

```bash
# Подключение к первому узлу
mysqlsh cluster_admin@mysql-node1:3306

# Создание кластера
\connect cluster_admin@mysql-node1:3306
\cluster.createCluster('my-cluster', {'adoptFromGR': false})

# Добавление узлов
\cluster.addInstance('cluster_admin@mysql-node2:3306')
\cluster.addInstance('cluster_admin@mysql-node3:3306')

# Проверка состояния
\cluster.status()
```

#### Шаг 4: Установка MySQL Router

```bash
# Установка
sudo dnf install -y mysql-router

# Настройка автоматического обнаружения кластера
sudo mysqlrouter --bootstrap cluster_admin@mysql-node1:3306 \
  --directory /opt/mysql/router \
  --user=mysql-router \
  --conf-use-sockets \
  --account=cluster_admin

# Запуск
sudo systemctl enable --now mysql-router
```

#### Шаг 5: Проверка работы

```bash
# Подключение через Router
mysql -h 127.0.0.1 -P 6446 -u app_user -p

# Проверка статуса кластера
SELECT * FROM performance_schema.replication_group_members;

# Проверка статуса через MySQL Shell
\cluster.status()
```

### Сценарий 2: Развертывание классической репликации с Orchestrator

#### Шаг 1: Настройка репликации

```bash
# На мастере (my.cnf)
[mysqld]
server-id = 1
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = binlog
binlog_format = ROW
binlog_checksum = CRC32

# На репликах (my.cnf)
[mysqld]
server-id = 2  # Уникальный на каждом узле
gtid_mode = ON
enforce_gtid_consistency = ON
log_bin = binlog
binlog_format = ROW
read_only = ON
super_read_only = ON
```

#### Шаг 2: Установка Orchestrator

```bash
# Скачивание (последний релиз — 4.31.1, 2026-07-28)
wget https://github.com/ProxySQL/orchestrator/releases/download/v4.31.1/orchestrator-4.31.1-linux-amd64.tar.gz
tar xzf orchestrator-4.31.1-linux-amd64.tar.gz
sudo mv orchestrator /usr/local/bin/

# Создание пользователя MySQL
CREATE USER 'orchestrator'@'localhost' IDENTIFIED BY 'OrchPass123!';
GRANT SUPER, PROCESS, REPLICATION SLAVE, REPLICATION CLIENT, 
    RELOAD, SHOW DATABASES, SHOW VIEW ON *.* 
    TO 'orchestrator'@'localhost';
FLUSH PRIVILEGES;

# Запуск в режиме Raft (HA)
orchestrator --raft --raft-config-file /etc/orchestrator/raft.json \
  --backend-db-source "user:orchestrator@tcp(localhost:3306)/orchestrator" \
  --listen-address 0.0.0.0:3000
```

#### Шаг 3: Настройка автоматического failover

```json
// /etc/orchestrator/raft.json
{
  "RaftEnabled": true,
  "RaftBind": "0.0.0.0:10008",
  "RaftNodes": ["node1:10008", "node2:10008", "node3:10008"]
}
```

```json
// /etc/orchestrator/orchestrator.conf
{
  "BackendDB": "mysql",
  "BackendDSN": "orchestrator:OrchPass123!@tcp(localhost:3306)/orchestrator",
  "DetectClusterAlias": true,
  "RecoverMasterClusterFilters": ["*"],
  "RecoverIntermediateMasterClusterFilters": ["*"],
  "FailMasterHostFilter": "",
  "ApplyMySQLPromotionAfterMasterFailover": true,
  "ReplicationRetryOnDuplicateError": true
}
```

### Сценарий 3: Настройка ProxySQL для read/write split

```sql
-- Подключение к ProxySQL admin interface
mysql -h 127.0.0.1 -P 6032 -u admin -p

-- Добавление серверов
INSERT INTO mysql_servers (hostgroup_id, hostname, port, weight) 
VALUES 
  (0, 'mysql-node1', 3306, 100),  -- Write
  (1, 'mysql-node2', 3306, 50),   -- Read
  (1, 'mysql-node3', 3306, 50);   -- Read

-- Настройка пользователя
INSERT INTO mysql_users (username, password, default_hostgroup, default_schema) 
VALUES ('app_user', 'AppPass123!', 0, 'production');

-- Сохранение изменений
SAVE MYSQL SERVERS TO DISK;
SAVE MYSQL USERS TO DISK;
LOAD MYSQL SERVERS TO RUNTIME;
LOAD MYSQL USERS TO RUNTIME;
```

### Сценарий 4: Тестирование failover

```bash
# Имитация отказа Primary (InnoDB Cluster)
mysqlsh cluster_admin@mysql-node1:3306 -- cluster.setPrimaryInstance('mysql-node2')

# Проверка failover через Router
mysql -h 127.0.0.1 -P 6446 -e "SELECT @@hostname"

# Имитация отказа мастера (Orchestrator)
orchestrator-client -c http://localhost:3000/api/force-master-failover/my-cluster/master-host

# Проверка статуса
\cluster.status()  # MySQL Shell
SELECT * FROM performance_schema.replication_group_members;
```

---

## Мониторинг и наблюдаемость

### Ключевые метрики Group Replication

Все метрики доступны в `performance_schema.replication_group_members`:

| Метрика | Значение | Интерпретация |
| :--- | :--- | :--- |
| `MEMBER_STATE` | `ONLINE` / `RECOVERING` / `UNREACHABLE` / `ERROR` | Основной индикатор состояния |
| `MEMBER_ROLE` | `PRIMARY` / `SECONDARY` | Роль в single-primary режиме |
| `MEMBER_VERSION` | `8.4.x` | Должна совпадать со всеми узлами |
| `MEMBER_COMMUNICATION_CHANNEL` | `GroupCommunicationEngine(GCS)` | Тип GCS-канала |
| `MEMBER_ERROR` | текст ошибки | При `MEMBER_STATE=ERROR` |
| `MEMBER TRANSACTION_EPOCH_RAISED` | epoch | Используется для разрешения конфликтов при领袖选举 |
| `MEMBER_TRANSACTION_EPOCH` | epoch | Текущий epoch |
| `COUNT` | количество узлов | Должно быть нечётным и >= 3 для кворума |

**Критические алерты:**
- `MEMBER_STATE` ≠ `ONLINE` для любого узла.
- Уменьшение количества активных узлов ниже majority (для 3 узлов — 2, для 5 — 3).
- `MEMBER_ROLE` изменился без планового switchover.
- `Seconds_Behind_Source` > 30 секунд на репликах (в классической репликации).

### Мониторинг через Prometheus (mysqld_exporter)

Ключевые метрики:
- `mysql_group_member_member_state` — состояние узла (0 = PRIMARY, 1 = SECONDARY, 2 = unreachable и т.д.).
- `mysql_slave_status_seconds_behind_master` — лаг репликации.
- `mysql_global_status_gtid_executed` — количество GTID-транзакций.
- `mysql_status_innodb_row_lock_waits` — блокировки (см. **[Блокировки и взаимоблокировки](./locking_and_deadlocks.md)**).
- `mysql_info_version` — версия MySQL (для отслеживания дрейфа версий).

### Orchestrator мониторинг

- Web-GUI: `http://<orchestrator>:3000/topology` — топология в реальном времени.
- REST API: `GET /api/health` — статус узла; `GET /api/cluster/<alias>/status` — состояние кластера.
- Raft: `GET /api/raft/status` — состояние Raft-кластера, лидер, члены.
- Prometheus-метрики (4.30+): встроенные метрики по failover, discovery, лагу репликации.
- Health-эндпоинты (4.30+): `/health/live`, `/health/ready`, `/health/leader`.

### MySQL Router мониторинг

- Логи: `mysqlrouter.log` — логи маршрутизации, ошибки подключения.
- Метрики: количество активных соединений, задержка маршрутизации, количество ошибок.
- Проверка: `mysql -h 127.0.0.1 -P 6446 -e "SELECT 1"` — базовая доступность.

### ProxySQL мониторинг

- Админ-интерфейс: `mysql -h 127.0.0.1 -P 6032 -u admin -p`.
- Ключевые таблицы: `mysql_servers` (hostgroups, статус), `mysql_query_rules`, `stats_mysql_query_digest`.
- Метрики: `mysql_servers_hosts_down_total`, `mysql_connections_ready_total`, `mysql_connections_active`.
- Алерты: `SHUNNED` сервера, рост `Queries` без роста `Connections` (признак медленных запросов), дисбаланс read/write.

### Мониторинг бэкапов и DR

- Проверяйте бэкапы регулярно: восстановление из `mysqldump`, `mysqlbackup`, `xtrabackup`.
- Тестируйте failover минимум раз в квартал.
- Документируйте процедуры восстановления и проверяйте их — см. **[Disaster Recovery](../../Concepts/disaster_recovery.md)**.

---

## Диагностика и устранение неисправностей

| Проблема | Вероятная причина | Диагностические команды | Решение |
| :--- | :--- | :--- | :--- |
| **Кластер не формирует кворум** | Нечетное количество узлов, потеря связи | `SELECT * FROM performance_schema.replication_group_members` | Проверить сетевую связность, добавить арбитр или третий узел |
| **Primary не может записывать** | Потеря кворума, конфликт транзакций | `SHOW ENGINE INNODB STATUS` | Проверить статус кластера, перезапустить узел |
| **Выборы лидера зависли** | Network Partition, медленные диски | `SELECT * FROM performance_schema.replication_group_members` | Проверить сеть, увеличить `group_replication_member_expel_timeout` |
| **Orchestrator не обнаруживает сбой** | Проблемы с правами MySQL, firewall | `orchestrator-client -c http://localhost:3000/api/health` | Проверить подключение, права пользователя |
| **Replication lag растет** | Нехватка ресурсов, медленная сеть | `SHOW SLAVE STATUS`, `performance_schema.replication_*` | Увеличить `slave_parallel_workers`, оптимизировать запросы |
| **MySQL Router не обновляет маршрут** | Устаревший кэш, потеря связи с кластером | `mysqlrouter --bootstrap cluster_admin@node1:3306 --directory /opt/mysql/router` | Перезапустить Router, проверить доступность кластера |
| **Split-Brain в Group Replication** | Потеря кворума, Partition | `SELECT * FROM performance_schema.replication_group_members` | Восстановить кворум, перезапустить узел в minority |
| **Транзакция откатывается (Certification)** | Конфликт записей в multi-primary режиме | `SHOW ENGINE INNODB STATUS` | Переключиться на single-primary, оптимизировать транзакции |

---

## Лучшие практики (Best Practices)

1. **Используйте single-primary для критичных систем:** Multi-primary требует сложной обработки конфликтов. Для 99% production-сценариев single-primary + read replicas — оптимальный выбор.

2. **Используйте majority write concern:** в Group Replication транзакция фиксируется только после подтверждения большинством узлов (Paxos-кворум). Это гарантирует, что данные не потеряются при сбое. Для критичных данных используйте `group_replication_consistency=BEFORE` или `BEFORE_AND_AFTER` — транзакция не коммитится до подтверждения всеми узлами.

3. **Мониторинг кворума:** Настройте алерты на `performance_schema.replication_group_members` — если узел покинул кластер, это должно быть обнаружено немедленно.

4. **Тестирование failover:** Минимум раз в квартал выполняйте controlled failover. Используйте `mysqlsh cluster.setPrimaryInstance()` для проверки.

5. **Backup перед изменениями:** Перед любым изменением конфигурации создайте бэкап. Используйте `mysqlbackup` или `mysqldump`.

6. **Автоматизация через IaC:** Вся конфигурация (my.cnf, пользователи, права) должна быть в Git и развертываться через Ansible/Terraform.

7. **Используйте ProxySQL для прозрачного failover:** Приложения подключаются через ProxySQL, а не напрямую к MySQL. Это позволяет переключать трафик без изменения конфигурации приложений.

8. **Настройка таймаутов для гео-распределения:** При кластере в разных дата-центрах увеличьте `group_replication_member_expel_timeout` до 10-30 секунд.

9. **Используйте GTID для отслеживания:** GTID simplifies disaster recovery и отслеживание репликации. Всегда включайте `gtid_mode=ON`.

10. **Мониторинг через Prometheus:** Используйте `mysqld_exporter` для сбора метрик. Ключевые метрики: `mysql_global_status_gtid_executed`, `mysql_group_member_member_state`, `mysql_slave_status_seconds_behind_master`.

---

## Граничные случаи и ограничения (Edge Cases)

- **Гео-распределенный кластер:** Group Replication требует низкой задержки между узлами. Для межрегиональных сценариев используйте классическую асинхронную репликацию с Orchestrator.

- **Multi-Primary конфликты:** В режиме multi-primary два узла могут попытаться изменить одну и ту же строку одновременно. Это приведет к откату одной из транзакций ( certification failure). Используйте single-primary для избежания конфликтов.

- **Split-Brain при 2 узлах:** Группа из 2 узлов не может формировать кворум при потере одного узла. Используйте минимум 3 узла или добавьте Group Replication с Arbiter (не поддерживается напрямую, используйте классическую репликацию).

- **Orchestrator и Raft:** Для HA самого Orchestrator используйте Raft-режим с 3 узлами. При использовании одного узла Orchestrator становится SPOF.

- **ProxySQL как SPOF:** Сам ProxySQL требует балансировки. Используйте пару ProxySQL через Keepalived или HAProxy.

- **Сеть с высокой задержкой:** Group Replication требует задержки < 100 мс между узлами. При более высоких задержках используйте асинхронную репликацию.

- **Транзакции большого размера:** Большие транзакции (миллионы строк) могут вызывать таймауты в Group Replication. Разбивайте на мелкие пакеты.

- **DDL в Group Replication:** Некоторые DDL-операции (ALTER TABLE) могут блокировать весь кластер. Выполняйте их с `LOCK=NONE` или в окне обслуживания.

---

## Очистка и откат

### Откат switchover

Плановое переключение можно откатить, если репликация с нового мастера на старый ещё не запущена:
1. Остановить репликацию на новом мастере: `STOP REPLICA`.
2. Перевести новый мастер в `super_read_only=ON`.
3. Запустить репликацию с старого мастера на новом: `CHANGE REPLICATION SOURCE TO ...; START REPLICA`.
4. Проверить догон: `SELECT WAIT_FOR_EXECUTED_GTID_SET(...)` или сравнить `Executed_Gtid_Set`.
5. Переключить ProxySQL/Router обратно на старый мастер.

После запуска репликации с нового мастера откат становится опасным (возможна потеря данных).

### Откат failover

После аварийного failover старый мастер **не должен использоваться повторно** — он может содержать неприменённые транзакции. Процедура:
1. Проверить, не содержит ли старый мастер неприменённые данные (сравнение GTID-наборов).
2. Если данные устарели — переподключить старый мастер как реплику к новому (после `RESET REPLICA` и `CHANGE REPLICATION SOURCE TO`).
3. Если данные свежее — остановить запись на новом мастере (`super_read_only=ON`), проверить догон и переключиться обратно.
4. При несовместимости — восстановить старый мастер из бэкапа или перестроить.

### Удаление узла из кластера

**Group Replication:**
1. Остановить Group Replication на узле: `STOP GROUP_REPLICATION`.
2. Удалить узла из конфигурации через MySQL Shell: `cluster.removeInstance('node')`.
3. При необходимости — перестроить Router через `mysqlrouter --bootstrap`.

**Orchestrator:**
1. Отключить узел из Orchestrator: `orchestrator-client -c http://localhost:3000/api/decommission/<host>:3306` (с `--periodic` для автоматического переподключения реплик).
2. Или вручную: остановить репликацию, удалить из топологии через GUI/CLI.

### Очистка после сбоя

- Удалить «висящие» реплики: узлы, которые не реплицируют и не являются мастерами.
- Очистить Orchestrator backend от устаревших записей: `orchestrator-client -c http://localhost:3000/api/expire-orchestrator`.
- Сбросить Orchestrator state: `orchestrator-client -c http://localhost:3000/api/reset-orchestrator` (только при полной потере топологии).
- Перезапустить MySQL Router после изменений топологии: `systemctl restart mysql-router`.

### Восстановление после полного отказа кластера

1. Восстановить последний полный бэкап на все узлы (или на один, затем distributed recovery).
2. Запустить Group Replication с `group_replication_bootstrap_group=ON` на одном узле.
3. Добавить остальные узлы через `cluster.addInstance()`.
4. Проверить кворум и состояние: `SELECT * FROM performance_schema.replication_group_members`.

---

## Дополнительная информация

### Связь с другими концепциями

- **[Механизмы репликации в MySQL](../MySQL/replication/master_slave_mechanism.md)** — классическая асинхронная репликация, GTID, MTS
- **[Failover и Switchover](../MySQL/replication/failover_switchover.md)** — промоушен, fencing, RPO/RTO, semi-sync при смене источника
- **[Orchestrator: управление топологией](../MySQL/orchestrator.md)** — детальный разбор Orchestrator, Raft-кластер, failover
- **[ProxySQL: Обзор](./ProxySQL/proxysql_overview.md)** — прокси-слой для read/write split
- **[ProxySQL: Failover и мониторинг репликации](./ProxySQL/proxysql_failover.md)** — hostgroups, `SHUNNED`, контроль лага
- **[ProxySQL: HA и ProxySQL Cluster](./ProxySQL/proxysql_ha_cluster.md)** — Cluster, Keepalived, вывод узлов из ротации
- **[Контроль высокой доступности MariaDB](../MariaDB/high_availability.md)** — Galera Cluster, MaxScale
- **[Обзор High Availability](../../Concepts/High_Availability/ha_overview.md)** — RTO/RPO, Active-Active, Active-Passive
- **[Disaster Recovery](../../Concepts/disaster_recovery.md)** — стратегии DR, бэкапы, восстановление
- **[Мониторинг MySQL](../MySQL/monitoring.md)** — `performance_schema`, `SHOW ENGINE INNODB STATUS`, алертинг
- **[Блокировки и взаимоблокировки](../MySQL/locking_and_deadlocks.md)** — metadata locks, блокировки при каскадных операциях, дедлоки

### Полезные ссылки

- [MySQL Group Replication](https://dev.mysql.com/doc/refman/8.4/en/group-replication.html)
- [MySQL InnoDB Cluster](https://dev.mysql.com/doc/mysql-shell/8.4/en/mysql-shell-innodb-cluster.html)
- [Orchestrator Documentation](https://github.com/ProxySQL/orchestrator)
- [ProxySQL Documentation](https://proxysql.com/documentation/)

### Чек-лист для InnoDB Cluster

- [ ] Все узлы имеют одинаковую версию MySQL
- [ ] GTID включен, `enforce_gtid_consistency=ON`
- [ ] `binlog_format=ROW` на всех узлах
- [ ] NTP синхронизация настроена (дрейф < 100 мс)
- [ ] Firewall открывает порты 3306, 33060, 6446
- [ ] MySQL Router настроен и запущен
- [ ] Тестирован failover: `\cluster.setPrimaryInstance()`
- [ ] Настроен мониторинг `performance_schema.replication_group_members`
- [ ] Регулярно тестируются бэкапы
- [ ] Конфигурация хранится в Git

---

## Контрольный список проектирования MySQL HA

- [ ] Выбран подход: InnoDB Cluster (Group Replication) или Classic + Orchestrator
- [ ] Определены RPO/RPO для сервиса
- [ ] Кластер имеет минимум 3 узла (или 2 + QDevice для Pacemaker)
- [ ] GTID включен на всех узлах
- [ ] Настроен автоматический failover (Orchestrator или Group Replication)
- [ ] Приложения подключаются через Router/ProxySQL (не напрямую)
- [ ] Настроен мониторинг: репликация, кворум, лаг
- [ ] Тестирован failover в production-подобной среде
- [ ] Настроены алерты на потерю кворума и смену лидера
- [ ] Документированы процедуры восстановления
- [ ] Конфигурация хранится в Git и развертывается через IaC