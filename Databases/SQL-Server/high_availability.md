# SQL Server: Always On Availability Groups (Linux)

## Определения

**Always On Availability Groups (AG)** — технология обеспечения высокой доступности и катастрофоустойчивости, которая позволяет объединить группу баз данных в логический кластер с синхронной или асинхронной репликацией.

**Pacemaker** — менеджер ресурсов кластера в Linux, используемый для оркестрации failover в SQL Server.

**mssql-pcsag (Agent v2)** — современный агент HA для SQL Server 2025, обеспечивающий быстрое (<10 сек) переключение ролей за счет постоянного соединения с движком.

---

## Архитектура на Linux (2026)

В отличие от Windows, где используется WSFC (Windows Server Failover Clustering), в Linux кластеризация строится на стеке **Pacemaker + Corosync**.

### Ключевые особенности
1.  **Read-Scale Availability Groups:** Возможность создания AG без кластерного ПО (Pacemaker). Используется только для масштабирования чтения, не обеспечивает автоматический failover.
2.  **TDS 8.0:** В SQL Server 2025 трафик репликации по умолчанию защищен TLS 1.3, что снижает нагрузку на CPU при синхронизации.
3.  **Quorum:** Требуется нечетное количество узлов (минимум 3) или использование Witness-узла для предотвращения Split-Brain.

---

## Практические сценарии

### 1. Настройка синхронной репликации (RPO=0)

**Шаг 1: Создание Endpoint (SQL)**
```sql
CREATE ENDPOINT [Hadr_endpoint]
    STATE=STARTED
    AS TCP (LISTENER_PORT = 5022)
    FOR DATABASE_MIRRORING (ROLE = ALL);
```

**Шаг 2: Создание AG**
```sql
CREATE AVAILABILITY GROUP [AgLinux]
    WITH (CLUSTER_TYPE = EXTERNAL) -- Указывает на управление через Pacemaker
    FOR DATABASE [MyDb]
    REPLICA ON N'node1' WITH (
        ENDPOINT_URL = N'tcp://10.0.0.1:5022',
        AVAILABILITY_MODE = SYNCHRONOUS_COMMIT,
        FAILOVER_MODE = EXTERNAL
    ),
    N'node2' WITH (...);
```

### 2. Управление через Pacemaker CLI

```bash
# Проверка статуса кластера
sudo pcs status

# Перевод узла в Standby (плановое обслуживание)
sudo pcs node standby node1

# Очистка ошибок после сбоя
sudo pcs resource cleanup mssql-ha-resource
```

---

## SRE-мониторинг Always On

Для SRE критично отслеживать следующие показатели через DMV:

| Метрика | DMV | Описание |
| :--- | :--- | :--- |
| **Synchronization Health** | `sys.dm_hadr_availability_replica_states` | Состояние здоровья реплик (HEALTHY/NOT_HEALTHY). |
| **Log Send Queue** | `sys.dm_hadr_database_replica_states` | Объем данных (КБ), ожидающих отправки на реплику (маркер Latency). |
| **Redo Queue** | `sys.dm_hadr_database_replica_states` | Объем данных, ожидающих применения на вторичном узле (маркер RTO). |

---

## Ограничения и риски (2026)

*   **DTC (Distributed Transaction Coordinator):** По-прежнему **не поддерживается** для AG на Linux. Распределенные транзакции между разными БД внутри AG могут привести к потере консистентности при failover.
*   **Split-Brain:** При потере сети между узлами без кворума Pacemaker может остановить все узлы. Всегда используйте **Fencing (STONITH)** для принудительного выключения "проблемного" узла.

---

## Дополнительная информация

### См. также
- **[Обзор SQL Server](./overview.md)** — архитектура и лицензирование.
- **[Тюнинг в Linux-контейнерах](./performance_tuning_linux.md)** — оптимизация ресурсов.
- **[Официальная документация HA Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-availability-group-overview)**
