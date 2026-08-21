# Отказоустойчивость MariaDB (High Availability)

## Определения

**High Availability (HA, Высокая доступность)** — архитектурный подход, обеспечивающий непрерывную работу СУБД при выходе из строя отдельных компонентов (узлов, дисков, сетевых сегментов). Цель HA — минимизация **MTTR** (Mean Time To Repair) и соблюдение параметров **RTO** (Recovery Time Objective) и **RPO** (Recovery Point Objective), заданных бизнесом.

**Galera Cluster** — технология синхронной multi-master репликации для MariaDB/MySQL. Гарантирует **RPO=0** (отсутствие потери данных) за счет синхронного подтверждения транзакций на всех узлах кластера перед фиксацией. Использует протокол **wsrep** (Write Set Replication) и механизм **Certification-based** replication, при котором каждая транзакция проверяется на конфликты на всех узлах перед применением.

**Orchestrator** — инструмент для управления топологией и автоматического восстановления (failover) классической репликации MariaDB/MySQL. Он визуализирует топологию в виде интерактивного GUI, обнаруживает сбои мастера и автоматически переназначает роли репликам. Работает через регулярное сканирование (Discovery) топологии через `SHOW SLAVE HOSTS` и проверку связности между узлами. Подробнее см. в **[Orchestrator: Управление топологией и Failover](../../Databases/MySQL/orchestrator.md)**.

**MaxScale** — интеллектуальный прокси-сервер, который выполняет роль входной точки для приложений. Он автоматически отслеживает состояние узлов MariaDB, выполняет Read/Write Split и перенаправляет трафик на нового мастера при failover. Для Galera Cluster используется модуль монитора `galeramon`, который определяет `Primary Component` и направляет трафик только на валидные узлы. Подробнее см. в **[MariaDB MaxScale: Обзор и эксплуатация](MaxScale/maxscale_overview.md)**.

**VIP (Virtual IP) / Keepalived** — механизм предоставления единого IP-адреса для доступа к кластеру, который перемещается на живой узел в случае сбоя. Реализуется через протокол **VRRP** (Virtual Router Redundancy Protocol). Keepalived мониторит состояние узла и при обнаружении отказа выполняет ` Gratuitous ARP` для переноса VIP на резервный узел. Подробнее см. в **[Механизмы Failover и Heartbeat](../../Concepts/High_Availability/ha_failover_mechanisms.md)**.

**Quorum (Кворум)** — математический принцип принятия решений большинством голосов (`floor(N/2) + 1`). В Galera Cluster кворум определяет, какая часть узлов является `Primary Component` и имеет право на запись. Сегмент кластера, оставшийся в меньшинстве (Minority), обязан прекратить обслуживание запросов на запись.

**Split-Brain (Расщепление мозга)** — катастрофическое состояние распределенной системы, возникающее при потере связи между узлами (Network Partition). В контексте Galera — узлы переходят в состояние `Non-Primary`, запросы `INSERT/UPDATE` отклоняются. В контексте классической репликации — два узла могут одновременно принимать запись, что приводит к порче данных.

---

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
- **Galera** — входит в поставку MariaDB (пакет `galera-4`)
- **Orchestrator** — версия 3.2+ (для нативной интеграции с ProxySQL — 2026+)
- **MaxScale** — версия 25.0+ (для полной поддержки Galera и ProxySQL-интеграции)
- **mariabackup** — утилита для физических бэкапов (используется как метод SST)
- **Keepalived** — для VIP (опционально, если используется MaxScale)

### Сетевые требования

- Все узлы Galera должны иметь прямую сетевую связность друг с другом
- Порты: `3306` (MariaDB), `4567` (Galera replication), `4568` (IST), `4444` (SST)
- Минимальная задержка (latency) между узлами: **< 1 мс** (в пределах одного дата-центра)
- Для MaxScale: порт `3306` (для клиентов) и порт `8989` (REST API)

---

## Основные концепции

### Сравнение архитектур отказоустойчивости

| Характеристика | Galera Cluster | Classic Replication + Orchestrator |
| :--- | :--- | :--- |
| **Тип репликации** | Синхронная (Certification-based) | Асинхронная / Полусинхронная |
| **Потеря данных (RPO)** | 0 (Гарантировано) | > 0 (Возможна при асинхронной) |
| **Масштабирование записи** | Ограничено (запись на всех узлах) | Только на Master |
| **Сложность настройки** | Высокая | Средняя |
| **Кворум** | Требуется (минимум 3 узла) | Не требуется (но желателен для Orchestrator) |
| **Основной кейс** | Критичные финансовые транзакции | Высоконагруженные Web-проекты |

### Galera Cluster: Особенности SRE

- **Certification Design:** Транзакция считается успешной, если она прошла проверку на конфликты на всех узлах. Это исключает Split-Brain на уровне данных. Механизм работы:
  1. Клиент отправляет транзакцию на любой узел кластера (multi-master).
  2. Узел-приемник выполняет транзакцию локально и отправляет **write set** (набор измененных строк) на все остальные узлы.
  3. Каждый узел проверяет write set на конфликты с собственными транзакциями (Certification).
  4. Если ни на одном узле конфликтов нет — транзакция фиксируется на всех узлах.
  5. Если есть конфликт — транзакция откатывается на узле-приемнике.

- **Flow Control:** Если один узел не успевает применять транзакции (очередь `wsrep_local_recv_queue` растет), он подает сигнал кластеру замедлить запись. Это может привести к "stalls" (задержкам) всего кластера. Мониторинг `wsrep_flow_control_paused` критически важен для обнаружения проблем с производительностью.

- **SST vs IST:** 
  - **SST (State Snapshot Transfer):** Полная передача данных новому узлу. Блокирует донора, если не используется `mariabackup` (рекомендуемый метод). Используется при первом запуске узла или когда gcache недостаточно для IST.
  - **IST (Incremental State Transfer):** Передача только недостающих транзакций из gcache. Не блокирует донора. Используется, когда узел пропустил небольшой объем транзакций, и они все еще находятся в gcache.

- **gcache:** Общий кэш транзакций на каждом узле. Размер определяется параметром `gcache.size`. Если узел пропустил транзакции, которых нет в gcache — используется SST.

### Orchestrator: Failover для асинхронной репликации

Orchestrator решает проблему "Master Failure" в классической топологии:

1.  **Детектирование (Discovery):** Постоянное сканирование топологии через `SHOW SLAVE HOSTS` и проверку связности. Интервал опроса — `InstancePollSeconds` (по умолчанию 5 секунд). Orchestrator также проверяет GTID-позиции всех реплик для определения наиболее актуальной.
2.  **Анализ (Analysis):** Если мастер недоступен, Orchestrator проверяет состояние всех реплик, их GTID-позиции и доступность. Предотвращает ложные срабатывания, требуя подтверждения от нескольких источников.
3.  **Восстановление (Recovery):** Выбирает наиболее актуальную реплику (с наибольшим GTID/позицией бинлога), делает её мастером и переподключает остальные реплики к новому источнику.
4.  **Hooks (Скрипты):** Позволяет запускать внешние скрипты для обновления VIP, конфигурации прокси (MaxScale/HAProxy) или уведомления команды.

### Keepalived: VIP Failover

Keepalived реализует механизм **VRRP** (Virtual Router Redundancy Protocol) для предоставления плавающего IP:

- **MASTER/BACKUP:** Один узел является MASTER (владелец VIP), другой — BACKUP. При падении MASTER, VIP перемещается на BACKUP.
- **VRRP Script:** Скрипт проверки здоровья, который мониторит процесс MariaDB или доступность через `mysqladmin ping`.
- **Preemption:** Если настроено, восстановившийся MASTER может вернуть VIP у BACKUP (с задержкой `nopreempt` для предотвращения flapping).

---

## Практические сценарии

### Настройка Galera Cluster (3 узла)

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
mysql -u root -p -e "SHOW STATUS LIKE 'wsrep_cluster_size';"
```

### Настройка Failover с Orchestrator

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

### Мониторинг здоровья Galera

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

**Мониторинг через Prometheus:**

```yaml
# Пример правил алертинга для Prometheus
groups:
  - name: galera_alerts
    rules:
      - alert: GaleraClusterSizeMismatch
        expr: mysql_global_status_wsrep_cluster_size != 3
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Galera cluster size mismatch"

      - alert: GaleraFlowControlActive
        expr: rate(mysql_global_status_wsrep_flow_control_paused[1m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Galera flow control is active"

      - alert: GaleraNodeNotSynced
        expr: mysql_global_status_wsrep_local_state != 4
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Galera node is not in Synced state"
```

---

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

---

## Дополнительная информация

### См. также
- **[MariaDB MaxScale: Обзор и эксплуатация](MaxScale/maxscale_overview.md)** — установка, конфигурация Read/Write Split и мониторинг.
- **[Конфигурация MariaDB](configuration.md)** — параметры GTID и бинарных логов.
- **[Официальная документация Galera](https://mariadb.com/kb/en/galera-cluster/)** — ссылка на официальную документацию.
