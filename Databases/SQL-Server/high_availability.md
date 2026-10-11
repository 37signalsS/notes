# SQL Server: Always On Availability Groups и FCI на Linux

**Актуально для:** SQL Server 2025 (17.x) / SQL Server 2022 (16.x) на Linux (RHEL 9/10, Ubuntu 22.04/24.04)

## Определения

**Always On Availability Groups (AG)** — технология HA/DR: группа пользовательских БД реплицируется между экземплярами SQL Server как единая единица. На Linux AG управляется внешним кластер-менеджером (Pacemaker), а не WSFC.

**Failover Cluster Instance (FCI)** — экземпляр SQL Server на кластере Pacemaker с общим хранилищем (iSCSI/NFS/SMB). Активен на одном узле; при отказе Pacemaker переводит экземпляр и хранилище на другой узел. Failover на уровне экземпляра (все БД, включая системные, переходят вместе).

**Pacemaker** — менеджер ресурсов кластера Linux, оркестрирует failover. **Corosync** — транспортный слой обмена сообщениями между узлами кластера (максимум 16 узлов).

**Availability Replica** — экземпляр SQL Server с копией БД AG: Primary (чтение/запись) или Secondary (чтение — только в Enterprise).

**Synchronous Commit** — транзакция считается зафиксированной только после записи журнала на диске Primary и Secondary (RPO = 0, но растёт задержка коммита). **Asynchronous Commit** — коммит без ожидания Secondary (низкая задержка, RPO > 0 при аварийном переключении).

**Automatic Seeding** — автоматическая инициализация Secondary потоковой передачей журналов (без ручного backup/restore). Требует совпадения путей данных и журнала на всех репликах.

**Configuration-only replica** — реплика, хранящая только метаданные AG в `master` (без пользовательских БД). Любая редакция, включая Express (где единственный допустимый endpoint — `ROLE = WITNESS`); не считается в лимите реплик; не может быть Primary; максимум одна на AG. Позволяет автоматический failover в конфигурации «2 синхронные реплики + configuration-only».

**Listener / VIP** — сетевое имя для прозрачного переподключения после failover. Аналога WSFC virtual network name на Linux нет: создаётся ресурс виртуального IP (`ocf:heartbeat:IPaddr2`), а имя Listener регистрируется в DNS вручную с этим IP.

**Quorum** — механизм голосования Pacemaker, определяющий легитимность узлов. Кворум и fencing должны быть настроены корректно, иначе кластер остановит все узлы.

**Fencing (STONITH)** — принудительная изоляция «проблемного» узла. Обязательна в production; fencing-агенты платформозависимы, поэтому все узлы должны быть одной платформы (физические или виртуальные на одном гипервизоре).

**Write lease** — внешний механизм защиты от split-brain: только узел с валидной арендой записи может быть Primary.

**Pacemaker HA Agent v2 (`mssql-pcsag`)** — HA-агент нового поколения (preview) в пакете `mssql-server-ha`: SQL Server 2025 CU3+, RHEL 9+, Ubuntu 22.04+. Работает как системный сервис `mssql-pcsag` (управляется через `systemctl`). Улучшения: быстрее planned/unplanned failover, гибкие политики (`FAILURE_CONDITION_LEVEL` 1–5, `HEALTH_CHECK_TIMEOUT`), TLS 1.3 для связи Pacemaker↔SQL Server, оценка write-lease перед переходами, решения на основе `sp_server_diagnostics` (memory pressure, deadlocks, I/O stalls). Агент v1 (`ocf:mssql:ag`) остаётся полностью поддерживаемым для production.

**REQUIRED_SYNCHRONIZED_SECONDARIES_TO_COMMIT** — число Secondary, которые должны записать журнал до коммита на Primary. На Linux задаётся только через Pacemaker (ресурсный агент выставляет автоматически).

---

## Архитектура и компоненты

### Модель интеграции (outside-in)

В отличие от Windows (WSFC), SQL Server на Linux не знает о существовании кластера: вся оркестрация — снаружи внутрь, через Pacemaker. Следствия:

- Cluster-DMV (`sys.dm_os_cluster_nodes`, `sys.dm_os_cluster_properties`) возвращают пустой результат; столбцы cluster-информации в AG DMV — внутренние, ими можно пренебрегать.
- `@@SERVERNAME` и `sys.servers` возвращают имя узла, а не кластера.
- Failover выполняется только средствами кластер-менеджера (`pcs`): при `CLUSTER_TYPE = EXTERNAL` допустимо только `FAILOVER_MODE = EXTERNAL`.
- Active Directory не требуется (в отличие от WSFC-кластеров, кроме workgroup-сценариев).

### AG vs FCI

| | AG | FCI |
| :--- | :--- | :--- |
| Уровень защиты | БД (группа БД) | Экземпляр (все БД + системные БД) |
| Хранилище | Локальное на каждом узле | Общее (iSCSI/NFS/SMB), XFS/ext4 |
| Репликация | Синхронная/асинхронная (журнал) | Нет — общее хранилище |
| Read-scale | Secondary readable (Enterprise) | Нет (active-passive) |
| Редакции | Standard (Basic AG: 2 реплики, 1 БД) / Enterprise (до 9 реплик) | Standard (до 2 узлов) / Enterprise (до 16 узлов кластера) |
| Системные БД | Локальные | Только `/var/opt/mssql/data` на общем хранилище; tempdb на локальном диске не поддерживается |

### Паттерны HA (CLUSTER_TYPE = EXTERNAL)

1.  **3 синхронные реплики** — HA + data protection + read-scale; агент ставит `REQUIRED_SYNCHRONIZED_SECONDARIES_TO_COMMIT = 1`.
2.  **2 синхронные реплики** — HA + data protection; по умолчанию `required_copies_to_commit = 1`: при потере Secondary Primary отклоняет соединения (защита данных ценой доступности).
3.  **2 синхронные + configuration-only** — то же HA; третьим узлом может быть любая редакция (даже Express), хранит метаданные AG.

Автоматический failover требует минимум одной синхронной реплики. Для Linux рекомендуется минимум 3 узла.

### Лимиты

- Enterprise: до 9 реплик (1 Primary + 8 Secondary), из них синхронных — до 3 (включая Primary).
- Standard (Basic AG): 2 реплики (1 Primary + 1 Secondary только для availability, без readable-запросов), 1 БД.
- Кластер Pacemaker/Corosync: максимум 16 узлов; AG охватывает до 9 (Enterprise) или 2 (Standard) узлов.
- Readable Secondary и бэкапы на Secondary — только Enterprise.

### Read-scale AG (без кластера)

`CLUSTER_TYPE = NONE`, `ASYNCHRONOUS_COMMIT`, `FAILOVER_MODE = MANUAL`, `SECONDARY_ROLE (ALLOW_CONNECTIONS = ALL)` — масштабирование чтения без HA; Pacemaker не нужен.

---

## Практические сценарии

### 1. Подготовка: HADR и кластер Pacemaker

```bash
# Включить HADR на каждом узле (требуется для всех реплик, включая configuration-only и Express)
sudo /opt/mssql/bin/mssql-conf set hadr.hadrenabled 1
sudo systemctl restart mssql-server

# Установить стек кластера
# RHEL:
sudo yum install -y pacemaker pcs fence-agents-all resource-agents
# Ubuntu 22.04+:
sudo apt-get install -y pacemaker pcs fence-agents resource-agents-base resource-agents-common resource-agents-extra

# Пользователь кластера и службы
sudo passwd hacluster
sudo systemctl enable pcsd && sudo systemctl start pcsd
sudo systemctl start pacemaker

# Создать кластер (3 узла)
sudo pcs host auth node1 node2 node3 -u hacluster -p '<пароль>'
sudo pcs cluster setup --name sqlha node1 node2 node3
sudo pcs cluster start --all

# Установить SQL Server HA-пакет (агенты ocf:mssql:*)
sudo yum install -y mssql-server-ha   # или: sudo apt-get install -y mssql-server-ha
sudo systemctl restart mssql-server
```

> **Важно:** имя узла в кластере должно совпадать со значением `SERVERPROPERTY('ServerName')` на экземпляре (для FQDN — использовать `addr` в `pcs cluster auth` или `sp_dropserver`/`sp_addserver`), иначе реплики уйдут в состояние resolving.

### 2. Создание AG (сертификаты, endpoint, AG)

На Linux поддерживается только сертификатная аутентификация endpoint (`WINDOWS` недоступна).

```sql
-- На каждом узле: создать сертификат и endpoint (порт 5022)
CREATE MASTER KEY ENCRYPTION BY PASSWORD = '<пароль>';
CREATE CERTIFICATE node1_cert WITH SUBJECT = 'node1 AG Certificate';
BACKUP CERTIFICATE node1_cert TO FILE = '/var/opt/mssql/data/node1_cert.cer';
CREATE ENDPOINT [Hadr_endpoint]
    STATE = STARTED
    AS TCP (LISTENER_PORT = 5022)
    FOR DATABASE_MIRRORING (ROLE = ALL, AUTHENTICATION = CERTIFICATE node1_cert, ENCRYPTION = REQUIRED ALGORITHM AES);
```

Сертификаты каждого узла (`*.cer`) переносятся на остальные узлы и восстанавливаются (`CREATE CERTIFICATE ... FROM FILE`), включая configuration-only реплики. Порт 5022/tcp открывается в файрволе.

```sql
-- На Primary: создать AG (3 синхронные реплики, автоматическое seeding)
CREATE AVAILABILITY GROUP [ag1]
    WITH (DB_FAILOVER = ON, CLUSTER_TYPE = EXTERNAL)
    FOR REPLICA ON
        N'node1' WITH (ENDPOINT_URL = N'tcp://node1:5022',
            AVAILABILITY_MODE = SYNCHRONOUS_COMMIT, FAILOVER_MODE = EXTERNAL, SEEDING_MODE = AUTOMATIC),
        N'node2' WITH (ENDPOINT_URL = N'tcp://node2:5022',
            AVAILABILITY_MODE = SYNCHRONOUS_COMMIT, FAILOVER_MODE = EXTERNAL, SEEDING_MODE = AUTOMATIC),
        N'node3' WITH (ENDPOINT_URL = N'tcp://node3:5022',
            AVAILABILITY_MODE = SYNCHRONOUS_COMMIT, FAILOVER_MODE = EXTERNAL, SEEDING_MODE = AUTOMATIC);

ALTER AVAILABILITY GROUP [ag1] GRANT CREATE ANY DATABASE;
```

`DB_FAILOVER = ON` включает мониторинг состояния БД (`sys.databases`): если БД уходит из ONLINE, кластер триггерит failover. При `SEEDING_MODE = AUTOMATIC` БД создаётся на Secondary автоматически.

### 3. AG как ресурс Pacemaker

```bash
# Агент v1 (production, все поддерживаемые версии):
sudo pcs resource create ag_cluster ocf:mssql:ag ag_name=ag1 meta failure-timeout=60s promotable notify=true

# Агент v2 (preview, SQL Server 2025 CU3+):
sudo pcs resource create ag_cluster ocf:mssql:agv2 ag_name=ag1 meta failure-timeout=30s promotable notify=true

# Виртуальный IP для Listener (опционально, рекомендуется)
sudo pcs resource create virtualip ocf:heartbeat:IPaddr2 ip=10.0.0.99 cidr_netmask=24
sudo pcs constraint colocation add virtualip with ag_cluster-master INFINITY

# Имя Listener зарегистрировать в DNS вручную с этим IP
```

Ресурс AG — promotable clone: master соответствует Primary. Агент автоматически выставляет `REQUIRED_SYNCHRONIZED_SECONDARIES_TO_COMMIT` (для 3 синхронных реплик — 1).

Миграция на агент v2: удалить ресурс и создать заново с `agv2` — сама AG не удаляется, синхронизация возобновляется автоматически:

```bash
sudo pcs resource delete ag_cluster
sudo pcs resource create ag_cluster ocf:mssql:agv2 ag_name=ag1 meta failure-timeout=30s promotable notify=true
sudo pcs status
```

Политики агента v2 (опционально):

```sql
ALTER AVAILABILITY GROUP [ag1] SET (FAILURE_CONDITION_LEVEL = 2);   -- 1–5
ALTER AVAILABILITY GROUP [ag1] SET (HEALTH_CHECK_TIMEOUT = 60000);  -- мс
```

### 4. FCI на Linux (общий диск)

```bash
# Ресурсы в группе (порядок запуска: диск → IP → SQL Server)
sudo pcs resource create fci_disk Filesystem device="//nas/fci" directory="/var/opt/mssql/data" \
    fstype=cifs options="vers=3.0,username=<user>,password=<pass>,uid=<mssqlUID>,gid=<mssqlGID>" --group fci_group
sudo pcs resource create fci_ip ocf:heartbeat:IPaddr2 ip=10.0.0.99 cidr_netmask=24 --group fci_group
sudo pcs resource create fci_sql ocf:mssql:fci op defaults timeout=60s --group fci_group
```

Особенности FCI на Linux: один экземпляр на сервер (default instance, именованных нет); системные БД только в `/var/opt/mssql/data` на общем хранилище; tempdb на локальном диске не поддерживается; имя FCI в DNS = имя ресурса Pacemaker.

**Валидация FCI:**

```bash
sudo pcs resource
# → fci_sql  (ocf::mssql:fci): Started <узел>
```

```sql
SELECT @@SERVERNAME;                                -- → имя FCI
SELECT SERVERPROPERTY('ComputerNamePhysicalNetBIOS');  -- → имя текущего узла
```

### 5. Read-scale AG

```sql
CREATE AVAILABILITY GROUP [ag_rs]
    WITH (CLUSTER_TYPE = NONE)
    FOR REPLICA ON
        N'node1' WITH (ENDPOINT_URL = N'tcp://node1:5022', AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT,
            FAILOVER_MODE = MANUAL, SEEDING_MODE = AUTOMATIC, SECONDARY_ROLE (ALLOW_CONNECTIONS = ALL)),
        N'node2' WITH (ENDPOINT_URL = N'tcp://node2:5022', AVAILABILITY_MODE = ASYNCHRONOUS_COMMIT,
            FAILOVER_MODE = MANUAL, SEEDING_MODE = AUTOMATIC, SECONDARY_ROLE (ALLOW_CONNECTIONS = ALL));
```

---

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Статус кластера / ресурсов | `sudo pcs status` / `sudo pcs resource show` |
| Плановое обслуживание узла | `sudo pcs node standby node1` (вернуть: `pcs node unstandby node1`) |
| Ручной failover AG | `sudo pcs resource move ag_cluster-master node2 --master --lifetime=30S`, затем `sudo pcs resource clear ag_cluster-clone` |
| Принудительный failover (с потерей данных, только DR) | см. процедуру ниже |
| Переопределить защиту данных (риск потери!) | `sudo pcs resource update ag_cluster required_copies_to_commit=0` (откат: `required_copies_to_commit=`) |
| Очистка ошибок после сбоя | `sudo pcs resource cleanup ag_cluster` |
| Ограничения после move | `sudo pcs constraint list --full` |
| Подключение | `sqlcmd -S <listener-или-IP> -U sa -P '<пароль>' -Q "SELECT @@VERSION"` |

**Принудительный failover (только для восстановления после катастрофы, когда кластер недоступен):**

```bash
# 1. Отключить управление ресурсом на целевом узле
sudo pcs resource unmanage ag_cluster   # при неудаче: sudo pcs resource delete ag_cluster
```

```sql
-- 2. На целевом Secondary: пометить сессию как внешний кластер
EXECUTE sp_set_session_context @key = N'external_cluster', @value = N'yes';

-- 3. Принудительный failover
ALTER AVAILABILITY GROUP [ag1] FORCE_FAILOVER_ALLOW_DATA_LOSS;
```

> **Внимание:** при `CLUSTER_TYPE = EXTERNAL` штатный failover выполняется только через `pcs`; T-SQL `ALTER AVAILABILITY GROUP ... FAILOVER` не используется. `FORCE_FAILOVER_ALLOW_DATA_LOSS` — не для учений, только для DR.

**Проверка синхронизации:**

```sql
SELECT DB_NAME(database_id) AS 'database', synchronization_state_desc
FROM sys.dm_hadr_database_replica_states;
-- → database | synchronization_state_desc
-- → MyDb     | SYNCHRONIZED
```

---

## Мониторинг (SRE)

| Метрика | DMV / источник | Описание |
| :--- | :--- | :--- |
| Synchronization Health | `sys.dm_hadr_availability_replica_states` (`synchronization_health_desc`) | HEALTHY / NOT_HEALTHY реплик |
| Log Send Queue | `sys.dm_hadr_database_replica_states` (`log_send_queue_size`, `log_send_rate`) | КБ, ожидающие отправки на Secondary (индикатор latency) |
| Redo Queue | `sys.dm_hadr_database_replica_states` (`redo_queue_size`, `redo_rate`) | КБ, ожидающие применения на Secondary (индикатор RTO) |
| Состояние кластера | `sudo pcs status`, `sudo pcs resource show` | Роли master/Slave, failed actions |
| Логи | `journalctl -u pacemaker`, `journalctl -u mssql-server`, `/var/opt/mssql/log/errorlog` | Диагностика failover и агента |

---

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Реплики в состоянии resolving | Имя узла кластера ≠ `SERVERPROPERTY('ServerName')` | Сравнить имена; исправить через `sp_dropserver`/`sp_addserver` или `addr` в `pcs cluster auth` |
| AG не синхронизируется | Сетевой сбой, порт 5022 закрыт, сертификаты не перенесены | Проверить `sys.dm_hadr_database_replica_states`, файрвол, наличие сертификатов на всех узлах |
| Failover не происходит | Кворум не достигнут; нет синхронной реплики | `sudo pcs status`; проверить `synchronization_health_desc`; настроить кворум/fencing |
| Primary отклоняет соединения | `required_copies_to_commit = 1` и Secondary недоступен | Дождаться восстановления Secondary или осознанно выставить `required_copies_to_commit=0` |
| Automatic Seeding зависает | Пути данных/журнала различаются, блокировки на Primary | Проверить `sys.dm_hadr_physical_seeding_stats`; выровнять пути |
| Split-Brain / остановка всех узлов | Потеря кворума, нет fencing | Восстановить кворум; настроить STONITH |
| Ошибки после failover | Осталась location-constraint от `pcs resource move` | `sudo pcs resource clear ag_cluster-clone` |

---

## Ограничения и риски

*   **DTC:** DTC поддерживается в SQL Server на Linux начиная с 2017 CU16, но **не поддерживается для AG на Linux**. Приложениям с распределенными транзакциями + AG требуется Windows.
*   **Split-Brain:** при потере сети без кворума Pacemaker может остановить все узлы. В production обязателен fencing (STONITH); все узлы — одной платформы (fencing-агенты платформозависимы).
*   **Forced failover:** к несинхронизированной реплике — с потерей данных; не используйте для учений.
*   **Агент v2 в preview:** оценивайте в non-prod; v1 остаётся поддерживаемым для production.

---

## Best Practices

*   **Минимум 3 узла** для HA (или 2 синхронные + configuration-only replica).
*   **Fencing (STONITH)** обязателен в production; примеры без fencing — только для тестов.
*   **`required_copies_to_commit = 1` по умолчанию** — максимальная защита данных; перевод в 0 — осознанный компромисс доступности.
*   **Бэкапы на Secondary** (Enterprise) — снять I/O с Primary; см. [Резервное копирование](./backup-and-recovery.md).
*   **Read-Only Routing** для read-scale: `SECONDARY_ROLE (ALLOW_CONNECTIONS = ALL, READ_ONLY_ROUTING_URL = N'tcp://node2:1433')`.
*   **Тестируйте failover** плановыми переключениями (`pcs resource move`).
*   **Пинить версии** CU и образов; перед миграцией на агент v2 — тестовый стенд.

---

## Дополнительная информация

### См. также
- **[Обзор SQL Server](./overview.md)** — архитектура, редакции, лицензирование, порты.
- **[Тюнинг в Linux](./performance_tuning_linux.md)** — cgroup v2, память, планировщик.
- **[Резервное копирование и восстановление](./backup-and-recovery.md)** — стратегии защиты данных.
- **[Availability groups for SQL Server on Linux](https://learn.microsoft.com/en-us/sql/linux/business-continuity/availability-groups/overview?view=sql-server-ver17)** (Microsoft Learn)
- **[Configure AG for high availability on Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-availability-group-configure-ha?view=sql-server-ver17)** (Microsoft Learn)
- **[Deploy a Pacemaker cluster for SQL Server on Linux](https://learn.microsoft.com/en-us/sql/linux/business-continuity/failover-cluster-instance/deploy-pacemaker-cluster?view=sql-server-ver17)** (Microsoft Learn)
- **[Failover cluster instances on Linux](https://learn.microsoft.com/en-us/sql/linux/business-continuity/failover-cluster-instance/shared-disk-cluster-concepts?view=sql-server-ver17)** (Microsoft Learn)
- **[Manage AG failover on Linux](https://learn.microsoft.com/en-us/sql/linux/business-continuity/availability-groups/failover-high-availability?view=sql-server-ver17)** (Microsoft Learn)
- **[Pacemaker HA Agent v2 (preview)](https://techcommunity.microsoft.com/blog/sqlserver/introducing-pacemaker-ha-agent-v2-for-sql-server-on-linux-in-preview/4505118)** (Microsoft Tech Community)
