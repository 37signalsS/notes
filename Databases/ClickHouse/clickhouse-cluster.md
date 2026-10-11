# ClickHouse — Репликация, шардирование и кластерное управление

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**ReplicatedMergeTree** — семейство движков таблиц ClickHouse, обеспечивающих синхронизацию данных между репликами через сервис координации (ClickHouse Keeper или ZooKeeper). Данные передаются напрямую между узлами по HTTP/Native TCP, а в Keeper хранятся только метаданные (логи мутаций, список частей данных, контрольные суммы).

**Distributed** — виртуальный движок таблиц, который не хранит данные самостоятельно, а перенаправляет запросы на локальные таблицы на каждом шарде. Узел-инициатор собирает частичные результаты и выполняет финальную агрегацию.

**ClickHouse Keeper** — нативный сервис координации, совместимый с ZooKeeper по протоколу, но использующий алгоритм консенсуса Raft. Хранит метаданные кластера и управляет кворумом.

**insert_quorum** — параметр, включающий синхронную запись при вставке: запрос считается завершенным только после подтверждения от указанного количества реплик.

**internal_replication** — флаг в конфигурации шарда: при `true` запись через `Distributed` отправляется только на одну реплику шарда, а остальные реплики синхронизируются стандартным механизмом; при `false` ClickHouse пытается писать на все реплики сам, что рискованно.

**Data Skew** — неравномерное распределение данных по шардам из-за низкой кардинальности ключа шардирования, приводящее к перегрузке одних узлов и простаиванию других.

## Репликация и шардирование: архитектурные основы

Распределенная архитектура ClickHouse строится на двух независимых, но дополняющих друг друга механизмах: репликации для обеспечения отказоустойчивости и шардирования для горизонтального масштабирования.

### Репликация (ReplicatedMergeTree)

Репликация в ClickHouse работает на уровне отдельных таблиц через движки семейства `ReplicatedMergeTree`.

- **Координация (ClickHouse Keeper / ZooKeeper):** Сервис координации хранит только **метаданные**: логи операций (mutations), список существующих кусков данных (parts) и их контрольные суммы. 
- **Передача данных:** Сами данные (куски) передаются напрямую между узлами ClickHouse по протоколам HTTP или Native TCP. Это позволяет избежать бутылочного горлышка в Keeper при передаче больших объемов данных.
- **Multi-Master:** Запись возможна в любую реплику. Если данные записаны на одну реплику, она сообщает об этом в Keeper, после чего остальные реплики видят новую запись и начинают скачивание куска в фоновом режиме.
- **Асинхронность:** По умолчанию репликация асинхронна. Однако можно настроить синхронную запись (ожидание подтверждения от нескольких реплик) через параметр `insert_quorum`.

### Шардирование (Distributed)

Шардирование позволяет распределить данные по нескольким физическим узлам (шардам) для параллельной обработки запроса всеми ресурсами кластера.

- **Движок Distributed:** Это «виртуальная» таблица, которая не хранит данные сама, а проксирует запросы к локальным таблицам на каждом шарде.
- **Механика запроса:** Узел-инициатор, получив запрос к `Distributed`-таблице, переписывает его в запросы к локальным таблицам, рассылает их на шарды, получает частичные агрегаты и выполняет финальную агрегацию перед ответом клиенту.
- **Ключ шардирования:** Определяет, на какой шард попадет строка при вставке.
  - Рекомендуется использовать хеш (например, `cityHash64(user_id)`) для равномерности.
  - **Data Skew:** Неправильный выбор ключа (например, с низкой кардинальностью) ведет к переполнению одних узлов и простою других.
- **Параметр `internal_replication`:**
  - `true` (рекомендуется): При записи через `Distributed` данные отправляются только на одну реплику каждого шарда. Остальные реплики забирают данные через стандартный механизм репликации.
  - `false`: ClickHouse пытается отправить данные на все реплики шарда самостоятельно, что может привести к несогласованности при сбоях сети.

Подробная теория распределенных систем: **[Шардирование и MPP](../Concepts/sharding.md)**.

---

## Конфигурация кластера

Определение структуры кластера происходит в конфигурационных файлах `config.xml` (или в `config.d/*.xml`).

### Секция remote_servers
Здесь описываются хосты, порты и топология кластера.

```xml
<clickhouse>
    <remote_servers>
        <logs_cluster> <!-- Имя кластера -->
            <shard>
                <internal_replication>true</internal_replication>
                <replica>
                    <host>shard1-replica1.local</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>shard1-replica2.local</host>
                    <port>9000</port>
                </replica>
            </shard>
            <shard>
                <internal_replication>true</internal_replication>
                <replica>
                    <host>shard2-replica1.local</host>
                    <port>9000</port>
                </replica>
            </shard>
        </logs_cluster>
    </remote_servers>
</clickhouse>
```

### Использование макросов
Для того чтобы DDL-запросы были универсальными для всех узлов, используются макросы в файле `macros.xml`.

```xml
<clickhouse>
    <macros>
        <cluster>logs_cluster</cluster>
        <shard>01</shard>
        <replica>shard1-replica1.local</replica>
    </macros>
</clickhouse>
```
Эти значения автоматически подставляются в DDL-запросы типа `CREATE TABLE ... ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/hits', '{replica}')`.

---

## Практические сценарии

### Предварительные требования для кластера

**Аппаратное обеспечение (на один узел):**
- **CPU:** 16+ ядер с поддержкой SSE 4.2 и AVX-512.
- **RAM:** 128+ ГБ (ClickHouse выполняет агрегации в памяти; нехватка RAM ведет к External Aggregation и падению производительности в 10–50 раз).
- **Диски:** NVMe SSD. Критично для фоновых слияний (merge) и синхронизации реплик. Задержки HDD вызывают `Too many parts` и отставание репликации.
- **Сеть:** 10 Gbps и выше между узлами. Низкая задержка (<1 ms) между репликами одного шарда важна для скорости репликации.

**Программное обеспечение:**
- **ОС:** Linux (CentOS Stream 9, Ubuntu 22.04+, Debian 12+).
- **Пакеты:** `clickhouse-server`, `clickhouse-client` из официального репозитория.
- **Сервис координации:** ClickHouse Keeper (рекомендуется standalone-режим) или ZooKeeper 3.8+.
- **DNS:** Стабильное разрешение внутренних имен между узлами. Проверьте `/etc/hosts` или внутренний DNS перед настройкой кластера.

> **Важно:** не используйте встроенный (internal) Keeper для Production-кластеров из 3+ узлов. Выделите отдельные серверы или контейнеры для Keeper, чтобы нагрузка на память и I/O не конкурировала с SQL-запросами.

### Развертывание bare-metal кластера (2 шарда, 2 реплики)

Ниже приведен пример развертывания кластера из 4 узлов: 2 шарда по 2 реплики каждый, плюс 3 узла ClickHouse Keeper.

**Топология:**
- `keeper1`, `keeper2`, `keeper3` — ансамбль Keeper (порт 2181).
- `shard1-replica1`, `shard1-replica2` — первый шард.
- `shard2-replica1`, `shard2-replica2` — второй шард.

**1. Установка ClickHouse на все 4 узла:**
```bash
# Официальный скрипт установки (Debian/Ubuntu)
curl https://clickhouse.com/ | sh

# Или через RPM (RHEL/CentOS)
sudo yum install -y https://clickhouse.com/rpm/lts/clickhouse-repo.rpm
sudo yum install -y clickhouse-server clickhouse-client
```

**2. Настройка ClickHouse Keeper (на keeper1, keeper2, keeper3):**
```xml
<!-- /etc/clickhouse-server/config.d/keeper.xml -->
<clickhouse>
    <keeper_server>
        <tcp_port>2181</tcp_port>
        <server_id>1</server_id> <!-- 2 на keeper2, 3 на keeper3 -->
        <log_storage_path>/var/lib/clickhouse/keeper/</log_storage_path>
        <coordination_settings>
            <operation_timeout_ms>10000</operation_timeout_ms>
            <raft_logs_level>information</raft_logs_level>
        </coordination_settings>
        <raft_configuration>
            <server>
                <id>1</id>
                <host>keeper1.local</host>
                <port>9234</port>
            </server>
            <server>
                <id>2</id>
                <host>keeper2.local</host>
                <port>9234</port>
            </server>
            <server>
                <id>3</id>
                <host>keeper3.local</host>
                <port>9234</port>
            </server>
        </raft_configuration>
    </keeper_server>
</clickhouse>
```

```bash
sudo systemctl enable --now clickhouse-server
# Проверка: echo ruok | nc keeper1.local 2181 # → imok
```

**3. Настройка `config.xml` на узлах ClickHouse (shard1-replica1 показан):**
```xml
<!-- /etc/clickhouse-server/config.d/remote_servers.xml -->
<clickhouse>
    <remote_servers>
        <logs_cluster>
            <shard>
                <internal_replication>true</internal_replication>
                <replica>
                    <host>shard1-replica1.local</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>shard1-replica2.local</host>
                    <port>9000</port>
                </replica>
            </shard>
            <shard>
                <internal_replication>true</internal_replication>
                <replica>
                    <host>shard2-replica1.local</host>
                    <port>9000</port>
                </replica>
                <replica>
                    <host>shard2-replica2.local</host>
                    <port>9000</port>
                </replica>
            </shard>
        </logs_cluster>
    </remote_servers>
</clickhouse>
```

**4. Настройка макросов (`macros.xml` на каждом узле):**

На `shard1-replica1.local`:
```xml
<clickhouse>
    <macros>
        <cluster>logs_cluster</cluster>
        <shard>01</shard>
        <replica>shard1-replica1.local</replica>
    </macros>
</clickhouse>
```

На `shard1-replica2.local`:
```xml
<clickhouse>
    <macros>
        <cluster>logs_cluster</cluster>
        <shard>01</shard>
        <replica>shard1-replica2.local</replica>
    </macros>
</clickhouse>
```

На `shard2-replica1.local`:
```xml
<clickhouse>
    <macros>
        <cluster>logs_cluster</cluster>
        <shard>02</shard>
        <replica>shard2-replica1.local</replica>
    </macros>
</clickhouse>
```

На `shard2-replica2.local`:
```xml
<clickhouse>
    <macros>
        <cluster>logs_cluster</cluster>
        <shard>02</shard>
        <replica>shard2-replica2.local</replica>
    </macros>
</clickhouse>
```

**5. Создание таблиц через `ON CLUSTER` (на любом узле):**
```sql
-- Создание базы данных
CREATE DATABASE IF NOT EXISTS logs_db ON CLUSTER '{cluster}';

-- Локальная реплицируемая таблица (создается на каждом узле)
CREATE TABLE logs_db.events_local ON CLUSTER '{cluster}' (
    event_time DateTime,
    event_id UInt64,
    payload String
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/events', '{replica}')
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, event_id);

-- Распределенная таблица (виртуальный доступ ко всем шардам)
CREATE TABLE logs_db.events ON CLUSTER '{cluster}' AS logs_db.events_local
ENGINE = Distributed('{cluster}', 'logs_db', 'events_local', rand());
```

**6. Валидация работоспособности:**
```sql
-- Проверка версии и списка шардов
SELECT cluster, shard_num, replica_num, host_name, is_leader
FROM system.clusters
WHERE cluster = 'logs_cluster';

-- Проверка статуса репликации (должен быть 0 задержка)
SELECT database, table, is_readonly, absolute_delay, queue_size
FROM system.replicas
WHERE database = 'logs_db';

-- Тестовая вставка через Distributed
INSERT INTO logs_db.events VALUES (now(), 1, 'test');

-- Проверка, что данные попали на все реплики
SELECT count() FROM logs_db.events_local;
```

### Восстановление после сбоя Keeper

Если ансамбль Keeper потерял кворум (осталось меньше 2 узлов из 3), кластер переходит в read-only. Восстановление:

1. **Остановите ClickHouse** на всех узлах, чтобы предотвратить повреждение метаданных.
2. **Восстановите Keeper:** перезапустите упавшие узлы Keeper. Raft автоматически переизберет лидера при наличии большинства узлов.
3. **Проверьте кворум:**
   ```bash
   echo mntr | nc keeper1.local 2181
   # Убедитесь, что role: leader и zk_connected_lservers соответствует количеству узлов
   ```
4. **Запустите ClickHouse** и проверьте `system.replicas` на предмет `is_readonly = 0`.
5. **Сбросьте реплику в read-write** (если автоматического восстановления не произошло):
   ```sql
   SYSTEM RESTORE REPLICA logs_db.events_local;
   ```

### Сценарий: Отключение узла на обслуживание

Graceful decommission replica без прерывания обслуживания:

1. **Исключите узел из балансировщика** (если используется HAProxy/nginx upstream).
2. **Остановите ClickHouse:**
   ```bash
   sudo systemctl stop clickhouse-server
   ```
3. **Проверьте, что данные остаются доступны** через `Distributed` таблицу с оставшимися репликами.
4. **Выполните обслуживание** (обновление ПО, замена диска).
5. **Запустите ClickHouse:**
   ```bash
   sudo systemctl start clickhouse-server
   ```
6. **Убедитесь, что реплика догнала очередь:**
   ```sql
   SELECT absolute_delay FROM system.replicas
   WHERE database = 'logs_db' AND table = 'events_local';
   # → 0
   ```
7. **Верните узел в балансировщик.**

### Решардинг (Resharding)

ClickHouse не поддерживает автоматический решардинг при добавлении нового узла.

**Методы переноса данных:**
1.  **clickhouse-copier:** Официальный инструмент для копирования данных с изменением ключа шардирования. Требует отдельного конфига с описанием задачи в формате XML.
2.  **Ручной перенос:**
    - Подключить новый шард в кластер.
    - Изменить ключ шардирования или топологию.
    - Выполнить `INSERT INTO new_distributed SELECT * FROM old_distributed` (осторожно, создает огромную нагрузку на сеть).

#### Конфигурация clickhouse-copier

`clickhouse-copier` переносит данные между кластерами/таблицами с изменением ключа шардирования. Запускается как отдельный процесс на каждом узле-источнике.

**Конфиг задачи (`copier_task.xml`):**
```xml
<clickhouse_copier_tasks>
    <max_workers>4</max_workers>
    <tables>
        <logs_shard>
            <cluster_pull>source_cluster</cluster_pull>
            <database_pull>devops</database_pull>
            <table_pull>logs</table_pull>
            <cluster_push>dest_cluster</cluster_push>
            <database_push>devops</database_push>
            <table_push>logs</table_push>
            <engine>
                ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/logs', '{replica}')
                PARTITION BY toYYYYMM(event_time)
                ORDER BY (service, event_time)
            </engine>
            <sharding_key>cityHash64(user_id)</sharding_key>
        </logs_shard>
    </tables>
</clickhouse_copier_tasks>
```

**Конфиг запуска (`copier_config.xml`):**
```xml
<clickhouse>
    <logger>
        <level>information</level>
    </logger>
    <remote_servers>
        <source_cluster>
            <shard><replica><host>src-1</host><port>9000</port></replica></shard>
        </source_cluster>
        <dest_cluster>
            <shard><replica><host>dst-1</host><port>9000</port></replica></shard>
        </dest_cluster>
    </remote_servers>
    <tables>
        <logs_shard>
            <cluster_pull>source_cluster</cluster_pull>
            <database_pull>devops</database_pull>
            <table_pull>logs</table_pull>
            <cluster_push>dest_cluster</cluster_push>
            <database_push>devops</database_push>
            <table_push>logs</table_push>
        </logs_shard>
    </tables>
</clickhouse>
```

**Запуск:**
```bash
clickhouse-copier --config copier_config.xml --task-path /clickhouse/copier/task_001
```

**Важно:** `sharding_key` в задаче определяет, как строки распределяются по шардам назначения. Убедитесь, что он совпадает с `ORDER BY`/шардированием целевой таблицы. Копирование — тяжёлая операция: планируйте в off-peak и контролируйте нагрузку на сеть.

### Обновление без простоя (Rolling Updates)
1. Обновить **ClickHouse Keeper** (он обратно совместим).
2. Поочередно выводить реплики из эксплуатации (остановка CH), обновлять бинарные файлы и возвращать в строй.
3. Перед обновлением следующей реплики убедиться, что текущая догнала очередь репликации (`absolute_delay` в `system.replicas` близок к 0).

## ClickHouse Keeper

**ClickHouse Keeper** — это нативный сервис координации, полностью совместимый с протоколом ZooKeeper, использующий алгоритм консенсуса **Raft**.

### Модели развертывания
- **Internal (Встроенный):** Keeper работает внутри процесса `clickhouse-server`. Рекомендуется для экономии ресурсов в небольших кластерах и тестовых окружениях.
- **Standalone (Автономный):** Отдельный процесс `clickhouse-keeper`. Рекомендуется для Production, чтобы нагрузка на Keeper (п memory, I/O) не конкурировала с обработкой SQL-запросов.

### Standalone Keeper deployment

Для production выделяйте 3 или 5 отдельный серверов с `clickhouse-keeper`.

**Установка пакета:**
```bash
# Debian/Ubuntu
apt-get install clickhouse-keeper

# RHEL/CentOS
yum install clickhouse-keeper
```

**Конфигурация (`/etc/clickhouse-keeper/config.xml`):**
```xml
<clickhouse>
    <logger>
        <level>information</level>
        <log>/var/log/clickhouse-keeper/clickhouse-keeper.log</log>
        <errorlog>/var/log/clickhouse-keeper/clickhouse-keeper.err.log</errorlog>
    </logger>

    <keeper_server>
        <tcp_port>2181</tcp_port>
        <server_id>1</server_id>  <!-- 2 на keeper2, 3 на keeper3 -->
        <log_storage_path>/var/lib/clickhouse-keeper/log/</log_storage_path>
        <snapshot_storage_path>/var/lib/clickhouse-keeper/snapshots/</snapshot_storage_path>

        <!-- HTTP-интерфейс для health checks и метрик -->
        <http_port>9182</http_port>
        <!-- Prometheus metrics -->
        <prometheus>
            <endpoint>/metrics</endpoint>
            <port>9182</port>
        </prometheus>

        <coordination_settings>
            <operation_timeout_ms>10000</operation_timeout_ms>
            <min_session_timeout_ms>10000</min_session_timeout_ms>
            <session_timeout_ms>100000</session_timeout_ms>
            <dead_session_check_period_ms>500</dead_session_check_period_ms>
            <heart_beat_interval_ms>500</heart_beat_interval_ms>
            <raft_logs_level>information</raft_logs_level>
            <compress_snapshots_with_zstd_format>true</compress_snapshots_with_zstd_format>
            <snapshot_zstd_compression_level>3</snapshot_zstd_compression_level>
            <snapshot_distance>100000</snapshot_distance>
        </coordination_settings>

        <raft_configuration>
            <server>
                <id>1</id>
                <host>keeper1.internal</host>
                <port>9234</port>
            </server>
            <server>
                <id>2</id>
                <host>keeper2.internal</host>
                <port>9234</port>
            </server>
            <server>
                <id>3</id>
                <host>keeper3.internal</host>
                <port>9234</port>
            </server>
        </raft_configuration>
    </keeper_server>
</clickhouse>
```

**Важно:** `server_id` должен быть стабильным и не меняться после развёртывания. ID и hostname маппятся в `raft_configuration`.

**Запуск:**
```bash
systemctl enable --now clickhouse-keeper

# Health check
curl -s http://localhost:9182/ready
# → OK

# 4-letter commands
echo ruok | nc localhost 2181
# → imok

echo mntr | nc localhost 2181
# → zk_version, zk_role, zk_num_alive_connections, ...
```

### Безопасность Keeper

**TLS (защищенное соединение между Keeper и ClickHouse):**
```xml
<!-- /etc/clickhouse-server/config.d/keeper_tls.xml -->
<clickhouse>
    <keeper_server>
        <tcp_port>2181</tcp_port>
        <secure>yes</secure>  <!-- включить TLS -->
        <cert_file>/etc/clickhouse-server/ssl/server.crt</cert_file>
        <key_file>/etc/clickhouse-server/ssl/server.key</key_file>
        <conf_file>/etc/clickhouse-server/ssl/ca.crt</conf_file>
    </keeper_server>
</clickhouse>
```

```xml
<!-- /etc/clickhouse-keeper/config.xml (standalone, с TLS) -->
<clickhouse>
    <keeper_server>
        <tcp_port>2281</tcp_port>  <!-- отдельный порт для TLS -->
        <secure>yes</secure>
        <cert_file>/etc/clickhouse-keeper/ssl/server.crt</cert_file>
        <key_file>/etc/clickhouse-keeper/ssl/server.key</key_file>
        <conf_file>/etc/clickhouse-keeper/ssl/ca.crt</conf_file>
    </keeper_server>
</clickhouse>
```

На стороне ClickHouse в `config.xml` укажите `use_secure_connection_with_keeper=true`.

**Digest-аутентификация:**
```xml
<!-- /etc/clickhouse-server/config.d/keeper_auth.xml -->
<clickhouse>
    <keeper_server>
        <users>
            <admin>
                <password_hash>6bb48...==</password_hash>  <!-- SHA3-256 -->
            </admin>
        </users>
    </keeper_server>
</clickhouse>
```

```bash
# Создание digest пароля
echo -n "your_password" | sha256sum

# Подключение с аутентификацией через client
clickhouse-keeper-client --host keeper1.internal --port 2181 --user admin --password your_password
```

**Важно:** для production всегда включайте TLS и аутентификацию при работе с Keeper по сети.

### Проверка состояния (Diagnostics)
Keeper поддерживает «четырехбуквенные команды» (4-letter words) через TCP-порт.

**Проверка здоровья:**
```bash
echo ruok | nc localhost 2181
# Ожидаемый ответ: imok
```

**Получение детальной статистики (mntr):**
```bash
echo mntr | nc localhost 2181
# Выведет: версию, роль (leader/follower), количество узлов, латентность.
```

---

## Обслуживание и Troubleshooting

### Диагностика здоровья репликации

Если данные перестали синхронизироваться, проверьте следующие таблицы:

- **`system.replicas`:**
  ```sql
  SELECT table, is_readonly, absolute_delay, queue_size 
  FROM system.replicas WHERE is_readonly = 1 OR absolute_delay > 60;
  ```
  `is_readonly = 1` обычно означает потерю связи с Keeper.
  - **`system.replication_queue`:** Показывает текущие задачи репликации (скачивание кусков, мутации). Если задачи висят со статусом `failed`, изучите колонку `last_exception`.

```sql
-- Подробный мониторинг очереди репликации
SELECT database, table, create_time, source_replica,
       last_attempt_num, last_exception,
       is_currently_executing, num_tries,
       latest_failed_event
FROM system.replication_queue
WHERE last_exception != ''
ORDER BY create_time DESC;

-- Проверка зависших мутаций (ALTER/MUTATE)
SELECT database, table, mutation_id, is_done, latest_of_mutations,
       create_time, num_tries, latest_failed_time, latest_failed_reason
FROM system.mutations
WHERE is_done = 0 AND num_tries >= 3;

-- Принудительная синхронизация реплики
SYSTEM SYNC REPLICA db.logs;
-- или для всех таблиц БД
SYSTEM RESTART REPLICAS;
```

#### Согласованность и кворум (insert_quorum)

Кворумная запись гарантирует, что данные подтверждены N репликами до возврата запроса:

```sql
-- Включить кворум для сессии (2 из 3 реплик должны подтвердить запись)
SET insert_quorum = 2;

-- Вставка с кворумом (запрос вернётся только после подтверждения 2 реплик)
INSERT INTO logs VALUES (...);

-- Не ждать всех реплик (декодирование кворума параллельно)
SET insert_quorum_parallel = 1;

-- Гарантировать, что SELECT видит только кворумные данные
SET select_sequential_consistency = 1;

-- Дождаться, пока реплика догонит очередь репликации
SYSTEM SYNC REPLICA db.logs;

-- Ожидание неактивной реплики при вставке (таймаут, секунды)
SET replication_wait_for_inactive_replica_timeout = 60;
```

**Когда использовать кворум:** критичные данные, где потеря при сбое узла недопустима (RPO ≈ 0). **Стоимость:** рост латентности вставки (ожидание подтверждения от N реплик).

**Синхронизация DDL с партициями:** `replication_alter_partitions_sync` (alias `alter_sync`) — режим синхронизации `ALTER`/`OPTIMIZE`/`TRUNCATE` между репликами: `0` (не ждать), `1` (ждать свою), `2` (ждать всех), `3` (ждать только активных). Cloud default: `0`.

### Диагностика Distributed-записей
Если запись через `Distributed` таблицу идет медленно или данные не появляются на шардах:
- Проверьте **`system.distribution_queue`**. Это очередь асинхронной вставки (если не включена настройка `insert_distributed_sync`).

#### Настройки Distributed-таблиц

```sql
-- Синхронная вставка в Distributed (ждать отправки на шарды)
SET insert_distributed_sync = 1;

-- Максимум соединений к шардам
SET max_distributed_connections = 1024;

-- Предпочитать localhost (на узле-инициаторе использовать локальную таблицу)
SET prefer_localhost = 1;

-- Игнорировать ошибки части реплик при Distributed-запросе
SET distributed_replica_max_ignored_errors = 3;

-- Режим балансировки запросов на чтение
SET load_balancing = 'least_used';
```

**Режимы `load_balancing` для Distributed-таблиц:**

| Режим | Описание | Use case |
| :--- | :--- | :--- |
| `random` (default) | Случайная реплика | Простой случай, равномерная нагрузка |
| `least_used` | Самая свободная реплика (наименьшее `background_pool` tasks) | Высокая нагрузка, нужно распределять запросы |
| `first_or_local` | Локальная реплика (если есть), иначе первая в списке | Минимизация сетевых hops при наличии локального шарда |
| `round_robin` | По кругу по репликам | Сбалансированная нагрузка при одинаковых ресурсах |
| `min_replica_count` | Минимальное количество запросов на реплике | Для контроля over-provisioning |

```sql
-- Параллельные реплики для чтения (распараллеливание на уровне реплик)
SET max_parallel_replicas = 3;

-- Максимальная задержка реплики для чтения через Distributed
-- (если реплика отстаёт больше, запрос не отправляется туда)
SET max_replica_delay_for_distributed_queries = 60;

-- Синхронизация запросов между репликами
SET prefer_localhost = 1;
```

**Фоновые настройки (config.xml):**
```xml
<distributed_directory_monitor_sleep_time_ms>100</distributed_directory_monitor_sleep_time_ms>
<distributed_directory_monitor_max_sleep_time_ms>1000</distributed_directory_monitor_max_sleep_time_ms>
```

`distributed_directory_monitor_*` управляют частотой проверки очереди отправки данных на шарды (асинхронная вставка в Distributed).

**Мониторинг очереди отправки:**
```sql
SELECT database, table, count() AS pending
FROM system.distribution_queue
GROUP BY database, table;
```

**Distributed DDL (ON CLUSTER):** DDL-команды выполняются на всех узлах через очередь в Keeper. Мониторинг:
```sql
SELECT * FROM system.distributed_ddl_queue ORDER BY create_time DESC LIMIT 10;
```
Таймаут ожидания DDL на всех узлах: `distributed_ddl_task_timeout` (по умолчанию 180 секунд).

**Troubleshooting Distributed DDL:**
```sql
-- DDL-запросы, которые ещё не выполнены на всех узлах
SELECT
    query,
    hosts_number,
    finished_hosts_number,
    create_time
FROM system.distributed_ddl_queue
WHERE finished_hosts_number < hosts_number
ORDER BY create_time DESC;

-- Ошибки выполнения DDL на конкретных узлах
SELECT
    query,
    host_name,
    exception
FROM system.distributed_ddl_queue
ARRAY JOIN host_names AS host_name, exceptions AS exception
WHERE exception != ''
ORDER BY create_time DESC;
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| DDL завис | Узел недоступен или перегружен | Проверить `system.distributed_ddl_queue`; увеличить `distributed_ddl_task_timeout` |
| DDL выполнился не на всех узлах | Один из узлов недоступен | Проверить доступность узла; повторить DDL |
| `Database already exists` | Гонка при параллельном DDL | Использовать `IF NOT EXISTS` |
| DDL медленный | Большая таблица, `MATERIALIZE` | Выполнять в off-peak; мониторить `system.mutations` |
| Кластер read-only | Потеря кворума Keeper | Восстановить Keeper; проверить `system.zookeeper_connection` |
| Реплика отстаёт (absolute_delay > 0) | Сеть, диск или высокая нагрузка | Проверить `system.replication_queue`; увеличить `operation_timeout_ms` |
| `BACKUP`/`RESTORE` висит | Недостаточно места или S3 недоступен | Проверить free_space (`system.disks`); credentials |
| `FREEZE` медленен | Активные запросы к таблице | Дождаться завершения; `FREEZE ON CLUSTER` с остановкой записи |
| Distributed-чтение slow | Плохая балансировка | Проверить `load_balancing` режим; использовать `least_used`/`first_or_local` |
| Keeper: `session expired` | Сетевой сбой или high latency | Увеличить `session_timeout_ms`; проверить сеть CH↔Keeper |
| TLS-ошибка к Keeper | Сертификат не доверен | Проверить CA в `conf_file`; включить `use_secure_connection_with_keeper` |

### Тюнинг ClickHouse Keeper

Keeper — критический компонент: его производительность определяет латентность записи в кластере.

**`coordination_settings` (config.xml):**
```xml
<keeper_server>
    <tcp_port>2181</tcp_port>
    <server_id>1</server_id>
    <log_storage_path>/var/lib/clickhouse/keeper/</log_storage_path>
    <snapshot_storage_path>/var/lib/clickhouse/keeper/snapshots/</snapshot_storage_path>
    <coordination_settings>
        <!-- Таймаут операции (мс) -->
        <operation_timeout_ms>10000</operation_timeout_ms>
        <!-- Минимальный таймаут сессии (мс) -->
        <min_session_timeout_ms>10000</min_session_timeout_ms>
        <!-- Таймаут сессии (мс) -->
        <session_timeout_ms>100000</session_timeout_ms>
        <!-- Период проверки мёртвых сессий (мс) -->
        <dead_session_check_period_ms>500</dead_session_check_period_ms>
        <!-- Интервал heartbeat (мс) -->
        <heart_beat_interval_ms>500</heart_beat_interval_ms>
        <!-- Уровень логирования Raft -->
        <raft_logs_level>information</raft_logs_level>
        <!-- Сжатие снапшотов -->
        <compress_snapshots_with_zstd_format>true</compress_snapshots_with_zstd_format>
        <snapshot_zstd_compression_level>3</snapshot_zstd_compression_level>
        <!-- Расстояние между снапшотами (записей Raft-лога) -->
        <snapshot_distance>100000</snapshot_distance>
    </coordination_settings>
    <raft_configuration>
        <server>
            <id>1</id>
            <host>keeper1.local</host>
            <port>9234</port>
        </server>
    </raft_configuration>
</keeper_server>
```

**Ключевые настройки:**

| Настройка | По умолчанию | Назначение |
| :--- | :--- | :--- |
| `operation_timeout_ms` | 10000 | Таймаут операции Keeper. Увеличить при высокой нагрузке (до 30000). |
| `session_timeout_ms` | 100000 | Таймаут сессии клиента. Увеличить при нестабильной сети. |
| `heart_beat_interval_ms` | 500 | Интервал heartbeat между узлами. |
| `snapshot_distance` | 100000 | Число записей Raft-лога между снапшотами. Для загруженных кластеров — 1M. |
| `compress_snapshots_with_zstd_format` | true | Сжатие снапшотов ZSTD. |

**Важно:**
- **server_id → hostname** маппинг должен быть стабильным: не меняйте `server_id` после развёртывания, не переиспользуйте ID.
- **snapshot_storage_path** — выносите на отдельный быстрый диск (SSD/NVMe).
- **HTTP-контроль:** порт 9182 с эндпоинтом `/ready` для health-checks.
- **4lw-команды:** `mntr`, `stat`, `ruok` — для мониторинга через Prometheus.
- **Мониторинг:** `system.zookeeper_connection` — статус соединения с Keeper.

**Мониторинг Keeper:**
```sql
-- Статус соединения с Keeper
SELECT * FROM system.zookeeper_connection;

-- Инспекция znode-структуры (health check нужных путей)
SELECT name, parent_name, full_path, is_empty,
       length(children) AS child_count,
       stat.gcv_stat.version AS stat_version,
       stat.gcv_stat.ephemeral_owner AS ephemeral_owner
FROM system.zookeeper
WHERE full_path = '/clickhouse/tables';

-- Проверка liveness через znode session
SELECT name, stat.numChildren, stat.czxid, stat.mzxid,
       stat.pzxid, stat.version, stat.creation_transaction_id,
       stat.last_changer_cookie, stat.modified_txid,
       stat.children_version
FROM system.zookeeper
WHERE name = 'tables' AND full_path LIKE '/clickhouse/%';

-- Через 4lw (bash)
echo mntr | nc keeper1.local 2181
# → zk_version, zk_avg_latency, zk_num_alive_connections, zk_outstanding_requests, zk_zxid, ...

-- Prometheus health endpoint (если настроен <prometheus> в keeper_server)
curl -s http://keeper1.internal:9182/metrics | grep -E 'keeper_(state|latency|connections|requests)'
```

**Метрики Keeper (Prometheus).** Встроенные метрики доступны на HTTP-порту (`http_port`, по умолчанию 9182), эндпоинт `/metrics`:
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'clickhouse-keeper'
    static_configs:
      - targets: ['keeper1.internal:9182', 'keeper2.internal:9182', 'keeper3.internal:9182']
```

Ключевые метрики для алёртинга:
- `keeper_state` (0=follower, 1=leader, 2=observer)
- `keeper_queue_latency` — латентность запросов
- `keeper_outstanding_requests` — незавершённые запросы (алерт > 1000)
- `keeper_followers` — количество follower-узлов

## Лучшие практики

1.  **Всегда используйте `internal_replication = true`:** Это снижает сложность записи и предотвращает несогласованность при сетевых сбоях. ClickHouse сам управляет распространением данных внутри шарда.
2.  **Выделяйте Keeper отдельно:** Встроенный Keeper подходит только для dev-сред и тестовых кластеров до 3 узлов. Для Production используйте standalone-ансамбли из 3 или 5 узлов на выделенных серверах.
3.  **Используйте макросы для DDL:** Никогда не хардкодьте имена шардов и реплик в `CREATE TABLE`. Макросы в `macros.xml` делают конфигурацию переносимой между окружениями.
4.  **Мониторьте `absolute_delay`:** Добавьте алерт в Prometheus на `absolute_delay > 60` в `system.replicas`. Это ранний индикатор проблем с сетью или Keeper.
5.  **Настраивайте `insert_distributed_sync`:** Для критичных данных включите синхронную запись в `Distributed`-таблицы, чтобы избегать потерь при отказе узла.
6.  **Держите `operation_timeout_ms` под контролем:** При высокой нагрузке увеличьте таймаут в Keeper до 10000–30000 ms, чтобы предотвратить ложные срабатывания таймаута.
7.  **Используйте SSD/NVMe для Keeper:** Raft-логи требуют постоянной синхронизации на диск (`fsync`). Задержки HDD напрямую влияют на латентность записи в кластер.
  8.  **Тестируйте сценарий потери кворума:** Раз в квартал выполняйте drill: остановите 2 из 3 узлов Keeper и убедитесь, что кластер корректно переходит в read-only и восстанавливается.
  9.  **Настраивайте `load_balancing` для read-heavy нагрузок:** режим `least_used` или `first_or_local` снижают сетевые hops и перегрузку при аналитических запросах по Distributed-таблицам.
  10. **Используйте `max_replica_delay_for_distributed_queries`:** ограничивает запросы на сильно отстающие реплики, предотвращая чтение stale data без `select_sequential_consistency`.
  11. **Контролируйте `system.mutations`:** большое количество зависших мутаций (особенно `ALTER ... UPDATE/MATERIALIZE`) блокируют слияния и растут очередь. Добавляйте алерт на `count() WHERE is_done=0 AND create_time < now() - INTERVAL 1 HOUR`.
  12. **Шифруйте соединение с Keeper:** всегда включайте TLS и digest-аутентификацию для standalone-ансамблей Keeper в production.

## Дополнительная информация

### Связанные разделы

- **Архитектура MergeTree и движки:** **[Архитектура ClickHouse](./clickhouse-architecture.md)**.
- **Настройка ОС и лимиты:** **[Эксплуатация ClickHouse](./clickhouse-operations.md)**.
- **Тюнинг запросов и сжатие:** **[Производительность ClickHouse](./clickhouse-performance.md)**.
- **Развертывание в K8s:** **[ClickHouse в Kubernetes](./clickhouse-kubernetes.md)**.
- **Общая теория шардирования:** **[Шардирование и MPP](../Concepts/sharding.md)**.

### Ограничения и известные особенности

- **Нет автоматического решардинга:** Добавление нового шарда требует ручного переноса данных через `clickhouse-copier` или `INSERT ... SELECT`.
- **ReplicatedMergeTree не заменяет стандартный MergeTree:** Для нереплицируемых таблиц используйте обычный `MergeTree`, чтобы избежать накладных расходов на координацию.
- **Data Skew сложно исправить после загрузки:** Неправильный ключ шардирования приводит к перекосу нагрузки, который можно устранить только через полный решардинг.
- **Keeper — единая точка отказа по метаданным:** При потере кворума Keeper кластер становится read-only. Это не приводит к потере данных, но блокирует все записи.
- **Сетевые разрывы между шардами:** ClickHouse не поддерживает multi-master запись между шардами. Каждый шард должен быть доступен из любой точки кластера с задержкой <1 ms.

### Системные пути и файлы (Linux)

При on-prem установке кластера через официальные пакеты:

- **Данные:** `/var/lib/clickhouse/` (разделы `data/`, `system/`, `format_schemas/`, `dictionaries/`)
- **Логи:** `/var/log/clickhouse-server/` (`clickhouse-server.log`, `clickhouse-client.log`, `stderr.log`)
- **Конфигурация:** `/etc/clickhouse-server/`
  - Основные файлы: `config.xml`, `users.xml`
  - Кастомные настройки: `config.d/*.xml`, `users.d/*.xml`
- **Секреты и ключи:** `/etc/clickhouse-server/ssl/` (сертификаты TLS)
- **Systemd unit:** `clickhouse-server.service` (работает от пользователя `clickhouse`)

**Важно:** не редактируйте `config.xml` напрямую — используйте файлы в `config.d/` для переопределения параметров.
