# Отказоустойчивость MariaDB (High Availability)

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**High Availability (HA, Высокая доступность)** — архитектурный подход, обеспечивающий непрерывную работу СУБД при выходе из строя отдельных компонентов (узлов, дисков, сетевых сегментов). Цель HA — минимизация **MTTR** (Mean Time To Repair) и соблюдение параметров **RTO** (Recovery Time Objective) и **RPO** (Recovery Point Objective), заданных бизнесом.

**Galera Cluster** — технология синхронной multi-master репликации для MariaDB/MySQL. Гарантирует **RPO=0** (отсутствие потери данных) за счет синхронного подтверждения транзакций на всех узлах кластера перед фиксацией. Использует протокол **wsrep** (Write Set Replication) версии 26 (Galera 4) и механизм **Certification-based** replication, при котором каждая транзакция проверяется на конфликты на всех узлах перед применением.

**Orchestrator** — инструмент для управления топологией и автоматического восстановления (failover) классической асинхронной репликации MariaDB/MySQL. Актуальная версия: 3.2.6+. Он визуализирует топологию в виде интерактивного GUI, обнаруживает сбои мастера и автоматически переназначает роли репликам. Работает через регулярное сканирование (Discovery) топологии через `SHOW SLAVE HOSTS` и проверку связности между узлами. Подробнее см. в **[Orchestrator: Управление топологией и Failover](../../Databases/MySQL/orchestrator.md)**.

**MaxScale** — интеллектуальный прокси-сервер MariaDB, который выполняет роль входной точки для приложений. Он автоматически отслеживает состояние узлов MariaDB, выполняет Read/Write Split и перенаправляет трафик на нового мастера при failover. Актуальная версия: 25.10+. Для Galera Cluster используется модуль монитора `galeramon`, который определяет `Primary Component` и направляет трафик только на валидные узлы. Для классической репликации — `mariadbmon` с автоматическим failover/switchover. Подробнее см. в **[MariaDB MaxScale: Обзор и эксплуатация](MaxScale/maxscale_overview.md)** и **[Failover и Switchover (mariadbmon)](MaxScale/maxscale_failover.md)**.

**VIP (Virtual IP) / Keepalived** — механизм предоставления единого IP-адреса для доступа к кластеру, который перемещается на живой узел в случае сбоя. Реализуется через протокол **VRRP** (Virtual Router Redundancy Protocol). Keepalived мониторит состояние узла и при обнаружении отказа выполняет `Gratuitous ARP` для переноса VIP на резервный узел. Подробнее см. в **[Механизмы Failover и Heartbeat](../../Concepts/High_Availability/ha_failover_mechanisms.md)**.

**Quorum (Кворум)** — математический принцип принятия решений большинством голосов (`floor(N/2) + 1`). В Galera Cluster кворум определяет, какая часть узлов является `Primary Component` и имеет право на запись. Сегмент кластера, оставшийся в меньшинстве (Minority), обязан прекратить обслуживание запросов на запись.

**Split-Brain (Расщепление мозга)** — катастрофическое состояние распределенной системы, возникающее при потере связи между узлами (Network Partition). В контексте Galera — узлы переходят в состояние `Non-Primary`, запросы `INSERT/UPDATE` отклоняются. В контексте классической репликации — два узла могут одновременно принимать запись, что приводит к порче данных.

**QDevice / Galera Arbitrator (`garbd`)** — легковесный процесс-арбитр, который участвует в голосовании кворума, но не хранит данные и не обслуживает клиентский трафик. Позволяет строить 2-узловые кластеры с поддержкой кворума без третьего полного сервера MariaDB. Пакет: `galera-arbitrator-4`. Если сам arbitrator падает — кластер продолжает работать, но автоматический failover недоступен до восстановления arbitror.

## Основные концепции

### Сравнение архитектур отказоустойчивости

| Характеристика | Galera Cluster | Classic Replication + Orchestrator |
| :--- | :--- | :--- |
| **Тип репликации** | Синхронная (Certification-based) | Асинхронная / Полусинхронная |
| **Потеря данных (RPO)** | 0 (Гарантировано) | > 0 (Возможна при асинхронной) |
| **Масштабирование записи** | Ограничено (запись на всех узлах) | Только на Source |
| **Сложность настройки** | Высокая | Средняя |
| **Кворум** | Требуется (минимум 3 узла или 2 + QDevice) | Не требуется (но желателен для Orchestrator) |
| **Основной кейс** | Критичные финансовые транзакции, ERP | Высоконагруженные Web-проекты, analytics |

### Galera Cluster: Особенности SRE

- **Certification Design:** Транзакция считается успешной, если она прошла проверку на конфликты на всех узлах. Это исключает Split-Brain на уровне данных. Механизм работы:
  1. Клиент отправляет транзакцию на любой узел кластера (multi-master).
  2. Узел-приемник выполняет транзакцию локально и отправляет **write set** (набор измененных строк) на все остальные узлы.
  3. Каждый узел проверяет write set на конфликты с собственными транзакциями (Certification).
  4. Если ни на одном узле конфликтов нет — транзакция фиксируется на всех узлах.
  5. Если есть конфликт — транзакция откатывается на узле-приемнике.

- **Flow Control:** Если один узел не успевает применять транзакции (очередь `wsrep_local_recv_queue` растет), он подает сигнал кластеру замедлить запись. Это может привести к "stalls" (задержкам) всего кластера. Мониторинг `wsrep_flow_control_paused` критически важен для обнаружения проблем с производительностью. Детальные метрики и алерты см. в **[Мониторинге MariaDB](monitoring.md)**.

- **SST vs IST:**
  - **SST (State Snapshot Transfer):** Полная передача данных новому узлу. Блокирует донора, если не используется `mariadb-backup` (рекомендуемый метод). Используется при первом запуске узла или когда gcache недостаточно для IST.
  - **IST (Incremental State Transfer):** Передача только недостающих транзакций из gcache. Не блокирует донора. Используется, когда узел пропустил небольшой объем транзакций, и они все еще находятся в gcache.

- **gcache:** Общий кэш транзакций на каждом узле. Размер определяется параметром `gcache.size`. Если узел пропустил транзакции, которых нет в gcache — используется SST. Рекомендуемое значение: не менее 2-4 ГБ для production; для кластеров с интенсивной записью — до 10-20 ГБ.

### Конфликты multi-master и их разрешение

В multi-master топологии Galera два транзакции могут конфликтовать, если они изменяют одну и ту же строку. Galera разрешает это через Certification:

1. **Optimistic Concurrency:** Транзакции выполняют на каждом узле независимо, а conflicting checks происходят после выполнения.
2. **Deadlock Detection:** Galera обнаруживает deadlocks на уровне write sets и откатывает одну из транзакций.
3. **Application-level Retry:** Приложение должно быть готово к повторной отправке транзакции при ошибке `ER_LOCK_DEADLOCK` или `ER_SERVER_IS_IN_STRICT_REPLICATION_MODE`.

**Рекомендации:**
- Используйте короткие транзакции. Длинные транзакции увеличивают окно конфликта.
- Избегайте UPDATE без WHERE на высоконагруженных таблицах.
- Используйте `SELECT ... FOR UPDATE` вместо недетерминированных операций.
- Настройте `wsrep_retry_autocommit` (по умолчанию 1) для автоматического повтора транзакций, завершающихся в autocommit.

### Оркестрация и failover

#### Orchestrator: Failover для асинхронной репликации

Orchestrator решает проблему "Master Failure" в классической топологии:

1.  **Детектирование (Discovery):** Постоянное сканирование топологии через `SHOW SLAVE HOSTS` и проверку связности. Интервал опроса — `InstancePollSeconds` (по умолчанию 5 секунд). Orchestrator также проверяет GTID-позиции всех реплик для определения наиболее актуальной.
2.  **Анализ (Analysis):** Если мастер недоступен, Orchestrator проверяет состояние всех реплик, их GTID-позиции и доступность. Предотвращает ложные срабатывания, требуя подтверждения от нескольких источников.
3.  **Восстановление (Recovery):** Выбирает наиболее актуальную реплику (с наибольшим GTID/позицией бинлога), делает её мастером и переподключает остальные реплики к новому источнику.
4.  **Hooks (Скрипты):** Позволяет запускать внешние скрипты для обновления VIP, конфигурации прокси (MaxScale/HAProxy) или уведомления команды.

#### Keepalived: VIP Failover

Keepalived реализует механизм **VRRP** (Virtual Router Redundancy Protocol) для предоставления плавающего IP:

- **MASTER/BACKUP:** Один узел является MASTER (владелец VIP), другой — BACKUP. При падении MASTER, VIP перемещается на BACKUP.
- **VRRP Script:** Скрипт проверки здоровья, который мониторит процесс MariaDB или доступность через `mysqladmin ping`.
- **Preemption:** Если настроено, восстановившийся MASTER может вернуть VIP у BACKUP (с задержкой `nopreempt` для предотвращения flapping).

### Rolling Restart и обслуживание кластера

Для планового обслуживания (обновление ОС, замена дисков, минорный апгрейд MariaDB) используйте Rolling Restart:

1. **Подготовка:** Убедитесь, что кластер имеет минимум 3 узла (или 2 + QDevice) и все узлы в состоянии `Synced`.
2. **Вывод узла:** Переведите узел в режим обслуживания (`SET GLOBAL wsrep_provider_options='pc.bootstrap=NO'` не требуется; просто остановите прием новых соединений на уровне приложения).
3. **Ожидание:** Дождитесь, пока узел полностью отдалит все транзакции (`SHOW STATUS LIKE 'wsrep_local_recv_queue'` → 0).
4. **Обновление:** Выполните обновление ОС/пакетов.
5. **Возврат:** Запустите узел и дождитесь состояния `Synced` (`SHOW STATUS LIKE 'wsrep_local_state_comment'`).
6. **Повтор:** Перейдите к следующему узлу.

**Важно:** При Rolling Restart кластер работает в смешанном режиме версий. Убедитесь, что версии MariaDB совместимы по протоколу wsrep (см. матрицу совместимости в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**).

## Предварительные требования (Prerequisites)

### Аппаратные требования

| Компонент | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядер |
| **RAM** | 4 ГБ | 16+ ГБ (зависит от рабочего набора данных) |
| **Диск** | 50 ГБ SSD | NVMe SSD (минимум 100 ГБ) |
| **Сеть** | 100 Мбит/с | 1 Гбит/с (для Galera — между всеми узлами) |
| **Количество узлов** | 2 (+ QDevice) | 3 (минимум для кворума без внешнего свидетеля) |

### Программные требования

- **MariaDB Server** — версия 10.6+ (рекомендуется 11.4 LTS или 12.3 LTS)
- **Galera** — входит в поставку MariaDB (пакет `galera-4`), wsrep API версии 26
- **Orchestrator** — версия 3.2.6+ (Percona fork: https://github.com/percona/orchestrator)
- **MaxScale** — версия 25.10+ (для полной поддержки Galera и маршрутизации запросов)
- **mariabackup** — утилита для физических бэкапов (используется как метод SST по умолчанию)
- **Keepalived** — для VIP (опционально, если используется MaxScale)
- **Galera Arbitrator (`garbd`)** — для 2-узловых кластеров (пакет `galera-arbitrator-4`)

### Сетевые требования

- Все узлы Galera должны иметь прямую сетевую связность друг с другом
- Порты: `3306` (MariaDB), `4567` (Galera replication), `4568` (IST), `4444` (SST)
- Минимальная задержка (latency) между узлами: **< 1 мс** (в пределах одного дата-центра)
- Для MaxScale: порт `3306` (для клиентов) и порт `8989` (REST API)
- Для Keepalived: multicast/broadcast поддержка на уровне сети для VRRP

### Валидация prerequisites

```bash
# Проверка сетевой связности между узлами Galera
for node in 192.168.1.10 192.168.1.11 192.168.1.12; do
  echo "=== $node ==="
  nc -zv $node 3306
  nc -zv $node 4567
  nc -zv $node 4568
  nc -zv $node 4444
done

# Проверка задержки сети (должна быть < 1 мс)
ping -c 10 192.168.1.11 | tail -1
# → rtt min/avg/max/mdev = 0.034/0.045/0.067/0.012 ms

# Проверка установленных пакетов
dpkg -l | grep -E "mariadb-server|galera-4|orchestrator|maxscale"
# или
rpm -qa | grep -E "MariaDB-server|galera-4|orchestrator|maxscale"

# Проверка наличия arbitrator (для 2-узловых кластеров)
dpkg -l | grep galera-arbitrator
# → galera-arbitrator-4
```

## Практические сценарии

### 1. Настройка Galera Cluster (3 узла)

#### Шаг 1: Подготовка узлов

На каждом из трех узлов (db-node-01, db-node-02, db-node-03):

```bash
# Установка MariaDB и Galera
# Для Debian/Ubuntu:
sudo apt-get update
sudo apt-get install -y mariadb-server mariadb-client galera-4

# Для RHEL/CentOS:
sudo dnf install -y mariadb-server mariadb-client galera-4
```

#### Шаг 2: Конфигурация первого узла

Создайте файл `/etc/mysql/mariadb.conf.d/90-galera.cnf` на первом узле:

```ini
[mariadb]
# Включение Galera
wsrep_on                = ON
wsrep_provider          = /usr/lib/galera/libgalera_smm.so

# Настройки кластера
wsrep_cluster_name      = "production_cluster"
wsrep_cluster_address   = "gcomm://192.168.1.10,192.168.1.11,192.168.1.12"

# Настройки конкретного узла
wsrep_node_address      = "192.168.1.10"
wsrep_node_name         = "db-node-01"

# Метод SST (рекомендуется mariabackup)
wsrep_sst_method        = mariabackup
wsrep_sst_auth          = "sst_user:СЛОЖНЫЙ_ПАРОЛЬ"

# Оптимальные настройки InnoDB для Galera
innodb_autoinc_lock_mode = 2      # Interleaved (обязательно для Galera)
binlog_format            = ROW
default_storage_engine   = InnoDB
```

#### Шаг 3: Запуск кластера

**На первом узле (db-node-01):**

```bash
# Запуск как новый кластер (создание Primary Component)
sudo galera_new_cluster
# → MariaDB запускается и становится первым узлом кластера
```

**На остальных узлах (db-node-02, db-node-03):**

```bash
# Обычный запуск (присоединение к существующему кластеру)
sudo systemctl start mariadb
```

#### Шаг 4: Валидация кластера

```sql
-- Выполните на каждом узле
SHOW STATUS LIKE 'wsrep_cluster_size';
-- → 3 (все узлы подключены)

SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced (узел синхронизирован)

SHOW STATUS LIKE 'wsrep_ready';
-- → ON (узел готов к работе)
```

```bash
# Проверка подключения к кластеру через любой узел
mariadb -u root -p -e "SHOW STATUS LIKE 'wsrep_cluster_size';"
# → 3
```

### 2. Настройка 2-узлового кластера с QDevice

Для 2-узловых кластеров необходим арбитр для достижения кворума:

```bash
# На третьей машине (arbitrator-host):
sudo apt-get install -y galera-arbitrator-4

# Конфигурация /etc/default/garb
GALERA_NODES="192.168.1.10:4567 192.168.1.11:4567"
GALERA_GROUP="production_cluster"
GALERA_OPTIONS=""

# Запуск arbitrator
sudo systemctl start garb
```

**Валидация:**

```sql
-- На узлах кластера
SHOW STATUS LIKE 'wsrep_cluster_size';
-- → 3 (2 узла + 1 arbitrator)

SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced
```

### 3. Настройка Failover с Orchestrator

**Типичная конфигурация `orchestrator.conf.json`:**

```json
{
  "Debug": false,
  "ListenAddress": ":3000",
  "MySQLOrchestratorHost": "127.0.0.1",
  "MySQLOrchestratorPort": 3306,
  "MySQLOrchestratorDatabase": "orchestrator",

  "DiscoveryMaxConcurrency": 20,
  "InstancePollSeconds": 5,
  "UnseenInstanceForgetHours": 240,

  "RecoveryPeriodBlockSeconds": 3600,
  "RecoveryIgnoreHostnameFilters": [],
  "RecoverMasterClusterFilters": ["*"],
  "RecoverIntermediateMasterClusterFilters": ["*"],

  "ApplyMySQLPromotionAfterMasterFailover": true,
  "ApplyMySQLUnittestAfterMasterFailover": false,
  "PreventCrossDataCenterMasterFailover": true,
  "PreventCrossRegionMasterFailover": true,

  "FailMasterPromotionIfMissingGTIDs": true,

  "PostMasterFailoverProcesses": [
    "/usr/local/bin/update-maxscale-master.sh {failedHost} {successorHost}"
  ],
  "PostFailoverProcesses": [
    "/usr/local/bin/send-notification.sh {successorHost}"
  ]
}
```

**Объяснение ключевых параметров:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `InstancePollSeconds` | Интервал опроса узлов (секунды) | 5 (по умолчанию). Для критичных систем — 2-3 |
| `RecoveryPeriodBlockSeconds` | Блокировка повторного failover (секунды) | 3600 (1 час). Предотвращает flapping |
| `ApplyMySQLPromotionAfterMasterFailover` | Автоматическое выполнение SQL-команд для повышения реплики | `true` для автоматизации |
| `FailMasterPromotionIfMissingGTIDs` | Запрет повышения реплики без всех GTID | `true` (безопасность данных) |
| `PreventCrossDataCenterMasterFailover` | Запрет failover между дата-центрами | `true` для geo-распределенных кластеров |

**Действия SRE при сбое мастера:**
1. Orchestrator обнаруживает `DeadMaster` через анализ состояния реплик.
2. Выполняется `MasterRecovery` — выбор наиболее актуальной реплики.
3. Запускается `PostMasterFailoverProcesses` для обновления точки входа (MaxScale/VIP).
4. Бывший мастер после восстановления должен быть переведен в режим реплики (через `mariadb-rejoin` или ручную настройку GTID).

### 4. Мониторинг здоровья Galera

Для SRE критически важно отслеживать состояние кворума и механизмов Flow Control.

**Базовые SQL-проверки:**

```sql
-- Проверка размера кластера (ожидается: количество узлов)
SHOW STATUS LIKE 'wsrep_cluster_size';
-- → 3

-- Проверка статуса синхронизации (Synced — норма)
SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced

-- Проверка готовности узла (ON — норма)
SHOW STATUS LIKE 'wsrep_ready';
-- → ON

-- Анализ очередей (если > 0, узел тормозит кластер)
SHOW STATUS LIKE 'wsrep_local_recv_queue_avg';
-- → 0.000

-- Проверка Flow Control (0 — нет пауз)
SHOW STATUS LIKE 'wsrep_flow_control_paused';
-- → 0

-- Проверка количества узлов, на которые идет отправка
SHOW STATUS LIKE 'wsrep_cluster_status';
-- → Primary
```

Полный набор метрик Prometheus, правил алертинга (`GaleraClusterSizeMismatch`, `GaleraFlowControlActive`, `GaleraNodeNotSynced`) и диагностики сценариев приведен в **[Мониторинге MariaDB](monitoring.md)**.

### 5. Резервное копирование и восстановление Galera

Для Galera Cluster используйте физические бэкапы (`mariadb-backup`), которые также служат методом SST:

```bash
# Физический бэкап на одном из узлов (не блокирует запись на других узлах)
mariadb-backup --user=backup --password \
  --backup \
  --target-dir=/backup/galera_node1_$(date +%Y%m%d) \
  --galera-info

# Валидация бэкапа
mariadb-backup --prepare --target-dir=/backup/galera_node1_20260930
# → backup prepared successfully
```

**Восстановление после сбоя всех узлов:**

1. Остановите все узлы кластера.
2. Восстановите бэкап на одном из узлов: `mariadb-backup --copy-back --target-dir=/backup/galera_node1_20260930`.
3. Запустите этот узел как новый кластер: `galera_new_cluster`.
4. По очереди присоединяйте остальные узлы через обычный `systemctl start mariadb`.

Детальные сценарии PITR, логические бэкапы (`mariadb-dump`) и стратегии хранения бэкапов см. в **[Резервном копировании MariaDB](backup_and_recovery.md)**.

### 6. Rolling Upgrade Galera Cluster

Обновление кластера без остановки обслуживания:

1. **Подготовка:** Создайте полный бэкап каждого узла. Проверьте совместимость версий wsrep.
2. **Обновление первого узла:** Остановите MariaDB, обновите пакеты, запустите `mariadb-upgrade`, затем запустите узел.
3. **Валидация:** Убедитесь, что узел присоединился к кластеру (`SHOW STATUS LIKE 'wsrep_cluster_size'`).
4. **Повтор:** Перейдите к следующему узлу. Кластер работает в смешанном режиме версий, пока все узлы не будут обновлены.

**Важно для MariaDB 12.3:** Пакет `mariadb-server-galera` теперь устанавливается отдельно. Подробности, включая матрицу совместимости и процедуру отката, см. в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**.

### 7. HAProxy как балансировщик нагрузки

HAProxy — L4/L7 балансировщик, используемый перед MariaDB для единой точки входа, health checks и распределения соединений. В отличие от MaxScale (L7, SQL-aware) и ProxySQL (L7, query rules), HAProxy работает на уровне TCP-потока (`mode tcp`) — он не разбирает SQL, но обеспечивает надёжные health checks и failover на уровне портов.

**Когда использовать HAProxy:**
*   Нужен простой, быстрый TCP-балансировщик с health checks.
*   Read/write split на уровне портов (отдельные порты для write и read).
*   Уже используется HAProxy в инфраструктуре.
*   Для SQL-aware маршрутизации (read/write split по содержимому запроса) используйте MaxScale или ProxySQL.

**Конфигурация `/etc/haproxy/haproxy.cfg`:**
```
global
    log 127.0.0.1 local2
    chroot /var/lib/haproxy
    pidfile /var/run/haproxy.pid
    maxconn 4000
    user haproxy
    group haproxy
    daemon
    stats socket /var/lib/haproxy/stats

defaults
    mode tcp
    log global
    option tcplog
    retries 3
    timeout connect 5s
    timeout client 1m
    timeout server 1m
    timeout check 10s

# Frontend для записи (source)
frontend mysql_write
    bind *:3306
    default_backend mysql_primary

# Frontend для чтения (replicas)
frontend mysql_read
    bind *:3307
    default_backend mysql_replicas

# Backend: primary (write)
backend mysql_primary
    mode tcp
    balance roundrobin
    option mysql-check user haproxy_check
    default-server inter 2s fall 3 rise 2
    server db-primary db-primary.example.com:3306 check

# Backend: replicas (read)
backend mysql_replicas
    mode tcp
    balance leastconn
    option mysql-check user haproxy_check
    default-server inter 2s fall 3 rise 2
    server db-replica-1 db-replica-1.example.com:3306 check
    server db-replica-2 db-replica-2.example.com:3306 check
```

**Параметры:**
*   `mode tcp` — L4-проксирование (MySQL-протокол — поток байтов, не HTTP).
*   `option mysql-check user haproxy_check` — health check через MySQL-протокол (а не просто TCP-порт). Требует пользователя `haproxy_check` на MariaDB.
*   `balance leastconn` — отправлять на сервер с наименьшим числом соединений (рекомендуется для БД).
*   `default-server inter 2s fall 3 rise 2` — проверка каждые 2с, отключить после 3 неудач, включить после 2 успехов.
*   `backup` — сервер в резерве (не используется, пока основные недоступны).

**Пользователь для health checks:**
```sql
-- На каждом MariaDB-узле
CREATE USER 'haproxy_check'@'haproxy_host' IDENTIFIED BY 'check_password';
-- Без привилегий (только для проверки доступности)
```

**Валидация:**
```bash
# Проверить конфигурацию
haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Запуск
sudo systemctl enable --now haproxy

# Проверить маршрутизацию
mariadb -h haproxy.example.com -P 3306 -u app -p -e "SELECT @@hostname, @@read_only;"
# → db-primary (read_only=0)

mariadb -h haproxy.example.com -P 3307 -u app -p -e "SELECT @@hostname, @@read_only;"
# → db-replica-1 или db-replica-2 (read_only=1)

# Статистика HAProxy
echo "show stat" | socat /var/lib/haproxy/stats stdio
```

**Важно:**
*   `option mysql-check user ...` работает только с auth-плагинами, поддерживаемыми HAProxy (mysql_native_password, caching_sha2_password с открытым ключом). Для `unix_socket`-аутентификации используйте обычный TCP-check.
*   HAProxy не выполняет автоматический failover source→replica (не промотирует реплику). Для автоматического failover используйте Orchestrator или MaxScale. HAProxy лишь выводит недоступный узел из rotation.
*   Для Galera-кластера все узлы — в одном backend (multi-master), `balance roundrobin` или `leastconn`.

**Сравнение прокси:**
| Прокси | Уровень | Read/Write Split | Failover | Query Cache |
| :--- | :--- | :--- | :--- | :--- |
| **HAProxy** | L4 (TCP) | По портам | Нет (только health check) | Нет |
| **ProxySQL** | L7 (SQL) | По правилам | Через скрипты | Да |
| **MaxScale** | L7 (SQL) | По правилам | Встроенный (mariadbmon) | Нет |

## Устранение неполадок (Troubleshooting)

### Split-Brain в Galera

- **Симптом:** Узлы переходят в состояние `Non-Primary`, запросы `INSERT/UPDATE` отклоняются с ошибкой `Unknown command`.
- **Причина:** Потеря связности между частями кластера, отсутствие кворума. Часто возникает при сетевых сбоях или остановке части узлов.
- **Диагностика:**
  ```sql
  -- Проверка состояния кластера
  SHOW STATUS LIKE 'wsrep_cluster_status';
  -- → Non-Primary (проблема)

  -- Проверка количества активных узлов
  SHOW STATUS LIKE 'wsrep_cluster_size';
  -- → 1 (меньше ожидаемого)
  ```
- **Решение:** Если вы уверены, что узел имеет самые актуальные данные, выполните:
  ```sql
  SET GLOBAL wsrep_provider_options='pc.bootstrap=YES';
  ```
  **Важно:** Выполняйте `pc.bootstrap` ТОЛЬКО на одном узле и ТОЛЬКО если вы уверены, что этот узел имеет наиболее актуальные данные. Неправильное использование приведет к потере данных.

### Orchestrator: Неконсистентность GTID

- **Проблема:** Orchestrator не может повысить реплику, так как она не имеет всех транзакций мастера. Ошибка: `GTID inconsistency`.
- **Причина:** Асинхронная репликация не гарантирует доставку всех транзакций до failover.
- **Решение:**
  1. Используйте полусинхронную репликацию (`rpl_semi_sync_master_enabled=1`) для минимизации лага.
  2. Убедитесь, что `FailMasterPromotionIfMissingGTIDs = true` в конфигурации Orchestrator.
  3. Если реплика не имеет всех GTID — проверьте `Last_SQL_Error` и устраните причину задержки репликации.

### Galera: Высокий latency при записи

- **Симптом:** Записи выполняются медленно, хотя CPU и диск не загружены.
- **Причина:** Flow Control активен из-за одного медленного узла.
- **Диагностика:**
  ```sql
  -- Найти узел-виновника
  SHOW STATUS LIKE 'wsrep_local_recv_queue_avg';
  -- Выполните на каждом узле и сравните результаты

  -- Проверить наличие долгих транзакций
  SHOW PROCESSLIST;
  ```
- **Решение:**
  1. Определите узел с максимальным `wsrep_local_recv_queue`.
  2. Проверьте, нет ли на этом узле тяжелых DDL-операций (`ALTER TABLE`).
  3. Используйте `pt-online-schema-change` вместо `ALTER TABLE` в Galera.
  4. Рассмотрите увеличение `gcache.size` для уменьшения вероятности SST.

### Orchestrator: Flapping (дребезг)

- **Симптом:** Циклические переключения мастера (мастер -> реплика -> мастер).
- **Причина:** Нестабильная сеть или слишком агрессивные настройки детектирования.
- **Решение:**
  1. Увеличьте `RecoveryPeriodBlockSeconds` (рекомендуется 3600 секунд).
  2. Проверьте сеть между узлами (packet loss, latency).
  3. Используйте `Maintenance Mode` на узлах при плановых работах.

### Galera: SST не завершается

- **Симптом:** Новый узел не может подключиться к кластеру, в логах ошибка `SST failed`.
- **Причина:** Неверные учетные данные для `mariabackup`, блокировка порта, нехватка дискового пространства.
- **Диагностика:**
  ```bash
  # Проверка логов
  journalctl -u mariadb | grep -i "sst\|galera"

  # Проверка портов
  ss -tlnp | grep -E "4444|4567|4568"
  ```
- **Решение:**
  1. Убедитесь, что `wsrep_sst_auth` корректен на всех узлах.
  2. Проверьте, что порты 4444, 4567, 4568 открыты между узлами.
  3. Убедитесь, что на доноре достаточно места для бэкапа.
  4. Временно отключите `apparmor` или `selinux` для проверки.

### Galera: Узел не может присоединиться к кластеру (IST fallback to SST)

- **Симптом:** Узел постоянно выполняет SST вместо IST, хотя должен был бы восстановиться через gcache.
- **Причина:** `gcache.size` слишком мал, или узел был отключен дольше, чем размер gcache позволяет покрыть.
- **Диагностика:**
  ```sql
  -- Проверка размера gcache
  SHOW VARIABLES LIKE 'wsrep_gcache_size';
  -- → 1G (или меньше)

  -- Проверка размера ре ceive queue
  SHOW STATUS LIKE 'wsrep_local_recv_queue';
  ```
- **Решение:**
  1. Увеличьте `wsrep_gcache.size` (рекомендуется 2-4 ГБ для production).
  2. Для кластеров с высокой интенсивностью записи установите 10-20 ГБ.
  3. Перезапустите узел для применения нового значения.

## Лучшие практики (Best Practices)

1. **Минимальный кластер:** Используйте 3 узла для production. Для 2 узлов добавьте QDevice (`galera-arbitrator-4`). Никогда не используйте 2 узла без arbitrator — кластер потеряет кворум при падении одного узла.
2. **Имена утилит:** Используйте новые имена (`mariadb-*`, `galera_new_cluster`) во всех скриптах и документации.
3. **Сеть:** Обеспечьте < 1 мс latency между узлами Galera. Используйте выделенный интерфейс для трафика репликации (порты 4567/4568/4444), отдельный от клиентского трафика (3306).
4. **Flow Control:** Мониторьте `wsrep_flow_control_paused`. Если значение > 0 — найдите узел с максимальной `wsrep_local_recv_queue` и устраните причину (медленные диски, отсутствие PK, тяжелые DDL).
5. **SST:** Используйте `mariadb-backup` как метод SST (не `mysqldump` или `rsync`). Он minimally блокирует донора. Настройте `wsrep_sst_auth` с надежным паролем и проверьте права пользователя SST на всех узлах.
6. **gcache.size:** Устанавливайте `wsrep_gcache.size` не менее 2-4 ГБ. Для кластеров с высокой записью — до 10-20 ГБ. Это уменьшает вероятность SST при перезапуске узлов.
7. **Rolling Restart:** Всегда обновляйте кластер по одному узлу, проверяя `wsrep_cluster_size` после возврата каждого узла в `Synced`.
8. **Orchestrator:** Настройте `RecoveryPeriodBlockSeconds` ≥ 3600 для предотвращения flapping. Используйте `FailMasterPromotionIfMissingGTIDs = true`. Тестируйте failover в staging регулярно.
9. **MaxScale:** Используйте MaxScale как точку входа для приложений. Настройте `galeramon` для автоматического определения Primary Component. Мониторьте здоровье MaxScale отдельно от MariaDB.
10. **Backup:** Регулярно создавайте физические бэкапы (`mariadb-backup`) на разных узлах. Храните бэкапы вне кластера. Тестируйте восстановление в staging.
11. **Движки:** Используйте только InnoDB для пользовательских таблиц в Galera. MyRocks и ColumnStore несовместимы с Galera. Подробнее см. в **[Движки хранения MariaDB](storage_engines.md)**.
12. **Критичные транзакции:** Для финансовых операций используйте короткие транзакции с явными `COMMIT`. Настройте `autocommit=1` и избегайте длительных блокировок.

## Особенности и ограничения (Edge Cases)

- **Galera и MyRocks:** Galera Cluster несовместим с MyRocks на уровне транзакций. Используйте только InnoDB для пользовательских таблиц.
- **Galera и Aria:** Экспериментальная поддержка начиная с 10.6. Для системных таблиц используется Aria, но пользовательские таблицы должны быть InnoDB.
- **2 узла без arbitrator:** Кластер из 2 узлов без QDevice потеряет кворум при падении одного узла. Всегда используйте arbitrator для 2-узловых конфигураций.
- **`wsrep_provider_options` и `pc.bootstrap`:** Неправильное использование `pc.bootstrap=YES` на нескольких узлах одновременно приведет к Split-Brain и потере данных. Выполняйте только на одном узле и только при полной уверенности в актуальности данных.
- **SST и блокировка донора:** При использовании `rsync` или `mysqldump` как метода SST донор блокируется на время передачи данных. Всегда используйте `mariabackup` для production.
- **Flow Control и производительность:** При активном Flow Control все записи в кластере замедляются до скорости самого медленного узла. Устранение узкого места на одном узле ускорит весь кластер.
- **Orchestrator и Raft:** Для HA самого Orchestrator используйте Raft-репликацию между несколькими экземплярами. Single-point-of-failure Orchestrator не дает отказоустойчивости failover.
- **MaxScale и Galera:** При переключении Primary Component MaxScale может кратковременно направлять записывающий трафик на узел, ставший `Non-Primary`. Настройте `max_replication_lag` и `enforce_read_only_servers=true` (монитор сам включает `read_only` на не-Primary узлах) для минимизации окна неконсистентности.
- **Rolling Upgrade и смешанные версии:** Во время обновления кластер работает в смешанном режиме. Новые функции целевой версии недоступны до завершения апгрейда всех узлов. Тестируйте совместимость в staging.
- **GTID и полусинхронная репликация:** При failover в Source-Replica топологии метрика `Seconds_Behind_Source` может показывать `NULL` или отрицательные значения. Настройте алерт с `for: >= 5m` и дополнительную проверку `Slave_IO_Running` / `Slave_SQL_Running`.

## Дополнительная информация
### См. также

- **[Безопасность Galera](security/galera-security.md)** — шифрование SST и репликационного трафика, `wsrep_allowlist`, сегментация кластера.
- **[Мониторинг MariaDB](monitoring.md)** — детальные метрики Galera, Prometheus алерты, диагностика Flow Control.
- **[Резервное копирование MariaDB](backup_and_recovery.md)** — `mariadb-backup`, `mariadb-dump`, SST/IST, PITR.
- **[Репликация MariaDB: Обзор](replication/overview.md)** — классическая асинхронная и полусинхронная репликация, GTID, Multi-source.
- **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — стратегия обновления Galera Cluster без остановки.
- **[Конфигурация MariaDB](configuration.md)** — параметры `wsrep_*`, `gcache.size`, `innodb_autoinc_lock_mode`.
- **[Движки хранения MariaDB](storage_engines.md)** — ограничения Galera по движкам (InnoDB only).
- **[Механизмы Failover и Heartbeat](../../Concepts/High_Availability/ha_failover_mechanisms.md)** — VRRP, Keepalived, heartbeat.
- **[MariaDB MaxScale: Обзор и эксплуатация](MaxScale/maxscale_overview.md)** — установка, конфигурация Read/Write Split и мониторинг.
- **[MariaDB MaxScale: Failover и Switchover](MaxScale/maxscale_failover.md)** — mariadbmon: auto_failover, switchover, rejoin, координация нескольких MaxScale.
- **[Orchestrator: Управление топологией и Failover](../../Databases/MySQL/orchestrator.md)** — детальный разбор Orchestrator, Raft-кластер, failover.

### Внешние ресурсы
- [MariaDB Galera Cluster Documentation](https://mariadb.com/docs/galera-cluster/)
- [MariaDB High Availability Solutions](https://mariadb.com/docs/server/server-usage/high-availability/)
- [Galera 4 Release Notes](https://mariadb.com/docs/release-notes/galera-cluster/all-releases)
- [MaxScale Documentation](https://mariadb.com/docs/maxscale/)
