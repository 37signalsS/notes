# MySQL Orchestrator: Управление топологией и Failover

## Определения

**Orchestrator** — это инструмент для обнаружения (discovery), визуализации и автоматического восстановления (failover) топологий репликации MySQL. Он понимает сложные деревья репликации и может автоматически перестраивать топологию при сбое любого узла. Написан на Go, распространяется как единый бинарник (`orchestrator`) плюс тонкий клиент (`orchestrator-client`), предоставляет Web-GUI и REST API.

**Discovery:** Процесс автоматического сканирования кластера и построения графа репликации. Orchestrator периодически подключается к каждому известному инстансу по MySQL-протоколу, читает `SHOW REPLICA STATUS` / `SHOW MASTER STATUS` и строит живой граф «кто кого реплицирует».

**Failover:** Автоматический или ручной процесс повышения реплики до статуса мастера (Primary) при обнаружении отказа текущего мастера. Включает выбор наиболее актуальной реплики, её повышение и переподключение остальных реплик к новому мастеру.

**Switchover (Graceful Takeover):** Плановое переключение роли мастера при живом исходном мастере (патчинг, обслуживание). Гарантирует отсутствие потери данных, так как реплика синхронизируется до переключения.

**Topology Refactoring:** Перестроение дерева репликации — перенос реплик между мастерами без остановки репликации (CLI-команды `move-up`, `move-below` или Drag-and-Drop в GUI).

**Raft-консенсус:** Протокол распределённого согласования, используемый для построения HA-кластера самого Orchestrator: узлы выбирают лидера, а операции восстановления выполняет только лидер, что исключает конкурирующие failover от разных узлов.

---

## Архитектура и состояние проекта (2026)

### Компоненты

Orchestrator состоит из трёх логических частей:

1. **Сервис Orchestrator** — процесс на Go, который выполняет discovery, детектирование сбоев и recovery. Слушает HTTP-порт (по умолчанию `:3000`) и обслуживает Web-GUI и REST API.
2. **Backend-база данных** — хранилище внутреннего состояния (топология, история сбоев, настройки). Поддерживается MySQL/MariaDB-схема либо встроенный SQLite (обязателен для Raft-режима). Таблицы создаются автоматически при первом запуске.
3. **Клиенты** — Web-GUI для операторов, REST API для автоматизации, `orchestrator` (CLI, прямое подключение к backend) и `orchestrator-client` (тонкий клиент, обращается через HTTP API работающего узла — предпочтителен в Raft-кластерах, так как сам находит лидера).

### Механизм детектирования

Ключевая особенность: Orchestrатор анализирует состояние мастера **через его реплики**, а не только напрямую. Если мастер не отвечает самому Orchestrator, но реплики продолжают получать от него binlog-события, мастер считается живым. Это защищает от ложных failover при сетевых проблемах между Orchestrator и мастером (например, недоступность одного дата-центра).

### История и 2026 Update

Проект создан Шломи Ноахом (Outbrain), затем поддерживался GitHub, позже передан в организацию [openark](https://github.com/openark/orchestrator). После периода архивации репозитория, **в апреле 2026 года Orchestrator перешёл под управление команды ProxySQL** (анонс Рене Каньо, 09.04.2026), что обеспечило нативную интеграцию (**Hook-less integration**) — теперь Orchestrator может напрямую обновлять Hostgroups в ProxySQL без использования внешних скриптов.

Актуальная версия линейки **4.30.0** (репозиторий [ProxySQL/orchestrator-original](https://github.com/ProxySQL/orchestrator-original)) принесла:

- **Модернизированное ядро:** обновлённые Go-зависимости, hardening протоколов.
- **Встроенные метрики Prometheus** — observability без внешних экспортеров.
- **Kubernetes-native health checks:** эндпоинты `/health/live`, `/health/ready`, `/health/leader` для liveness/readiness-проб и проверки лидера Raft.
- **Нативные ProxySQL Failover Hooks:** при failover Orchestrator предварительно «осушает» старого мастера в ProxySQL через `OFFLINE_SOFT`, а после повышения обновляет writer/reader hostgroups. Это сокращает время восстановления и устраняет риск split-brain маршрутизации трафика.
- **Анонсированная поддержка PostgreSQL streaming replication** — расширение за пределы экосистемы MySQL.

### Ключевые функции

- **Визуализация:** Интерактивный GUI для просмотра состояния репликации (лаг, GTID-позиции, счётчик реплик каждого узла).
- **Детектирование:** Обнаруживает сбои через анализ состояния всех реплик (предотвращает ложные срабатывания).
- **Рефакторинг:** Перенос реплик между мастерами простым Drag-and-Drop в GUI или через CLI.
- **Автоматическое восстановление:** Выбор кандидата, повышение, переподключение реплик и вызов hook-скриптов одним автоматизированным процессом.
- **Audit trail:** История сбоев и действий сохраняется в backend-базе — можно разбирать инциденты постфактум.

---

## Базовые концепции работы

### Цикл Discovery

1. Оператор регистрирует первый узел командой `discover` (или Orchestrator находит реплики автоматически через `SHOW REPLICAS` / `SHOW SLAVE HOSTS` уже известных узлов).
2. Каждый инстанс опрашивается раз в `InstancePollSeconds` секунд с параллелизмом до `DiscoveryMaxConcurrency` потоков.
3. Результаты записываются в backend-базу и формируют граф кластера. Узлы, недоступные дольше `UnseenInstanceForgetHours`, удаляются из графа.

### Детектирование и анализ сбоя

При недоступности мастера запускается фаза анализа (до начала каких-либо действий):

- проверяется доступность мастера напрямую и через каждую реплику;
- собираются GTID-позиции всех реплик для определения наиболее актуальной;
- проверяются ограничения: `PreventCrossDataCenterMasterFailover`, maintenance-режимы узлов, блокировка повторного recovery (`RecoveryPeriodBlockSeconds`).

Только если анализ подтверждает `DeadMaster`, запускается recovery. Если мастер «мерцает» (то доступен, то нет), повторный failover блокируется окном `RecoveryPeriodBlockSeconds`.

### Процесс Recovery (DeadMaster)

1. **Детектирование:** подтверждён `DeadMaster`; вызываются процессы `OnFailureDetectionProcesses` (уведомления, алертинг).
2. **Выбор кандидата:** из реплик выбирается наиболее актуальная по GTID, удовлетворяющая ограничениям (лаг, дата-центр, `PromotionRule` — `must`/`prefer`/`neutral`).
3. **Повышение:** реплика останавливает репликацию, применяет остаток relay log, снимает `read_only` (при `ApplyMySQLPromotionAfterMasterFailover: true`).
4. **Переподключение:** остальные реплики переводятся на нового мастера. С GTID это надёжная операция автопозиционирования; без GTID координаты вычисляются эвристически и могут привести к потере или дублированию транзакций.
5. **Post-failover:** вызываются `PostMasterFailoverProcesses` (обновление ProxySQL/VIP/DNS, уведомления).
6. **Блокировка:** повторный автоматический recovery кластера блокируется на `RecoveryPeriodBlockSeconds`.

Бывший мастер после восстановления **не переподключается автоматически**: он должен быть вручную очищен (`RESET REPLICA ALL`) и переведён в реплики нового мастера либо выведен из кластера.

---

## Практические сценарии

### Предварительные требования

- **Версии:** Orchestrator 3.2.x (линейка openark) или 4.30+ (линейка ProxySQL, рекомендована для новых развёртываний); MySQL 5.7 / 8.0 / 8.4, Percona Server, MariaDB 10.x.
- **GTID-репликация:** `gtid_mode=ON`, `enforce_gtid_consistency=ON` — строго рекомендуется для автоматического failover (см. Лучшие практики).
- **Backend-база:** отдельная схема MySQL или локальный SQLite.
- **Сетевой доступ:** Orchestrator должен подключаться к каждому управляемому MySQL по порту 3306; узлы Raft-кластера — друг к другу по порту 10008 (по умолчанию).
- **`report_host`:** задайте в `my.cnf` каждого сервера уникальное имя, иначе discovery покажет пустые hostname:

```ini
[mysqld]
report_host = db-replica-01
```

**Пользователь для доступа к топологии** (создаётся на каждом управляемом инстансе, включая новые реплики):

```sql
CREATE USER 'orchestrator'@'orch-host.internal' IDENTIFIED BY 'str0ng_orch_pass';
GRANT SUPER, PROCESS, REPLICATION SLAVE, REPLICATION CLIENT, RELOAD ON *.*
  TO 'orchestrator'@'orch-host.internal';
GRANT SELECT ON mysql.slave_master_info TO 'orchestrator'@'orch-host.internal';
GRANT SELECT ON performance_schema.replication_group_members TO 'orchestrator'@'orch-host.internal';
FLUSH PRIVILEGES;
```

Для MySQL 8.0+ вместо `SUPER` рекомендуется принцип наименьших привилегий: `SYSTEM_VARIABLES_ADMIN`, `SESSION_VARIABLES_ADMIN`, `BINLOG_ADMIN`.

**Пользователь backend-базы** (на сервере, где размещена схема `orchestrator`):

```sql
CREATE DATABASE orchestrator CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'orc_backend'@'localhost' IDENTIFIED BY 'str0ng_backend_pass';
GRANT ALL PRIVILEGES ON orchestrator.* TO 'orc_backend'@'localhost';
FLUSH PRIVILEGES;
-- Таблицы схемы создаются автоматически при первом запуске сервиса
```

### Сценарий 1. Установка и регистрация кластера

Установка из релизного архива (версия указана для примера):

```bash
wget https://github.com/ProxySQL/orchestrator-original/releases/download/v4.30.0/orchestrator-4.30.0-linux-amd64.tar.gz
tar -xzf orchestrator-4.30.0-linux-amd64.tar.gz -C /usr/local/
ln -s /usr/local/orchestrator/orchestrator /usr/local/bin/orchestrator
ln -s /usr/local/orchestrator/orchestrator-client /usr/local/bin/orchestrator-client
mkdir -p /etc/orchestrator /var/lib/orchestrator /var/log/orchestrator
```

Минимальная конфигурация `/etc/orchestrator/orchestrator.conf.json`:

```json
{
  "Debug": false,
  "ListenAddress": ":3000",
  "MySQLTopologyUser": "orchestrator",
  "MySQLTopologyPassword": "str0ng_orch_pass",
  "MySQLOrchestratorHost": "127.0.0.1",
  "MySQLOrchestratorPort": 3306,
  "MySQLOrchestratorDatabase": "orchestrator",
  "MySQLOrchestratorUser": "orc_backend",
  "MySQLOrchestratorPassword": "str0ng_backend_pass"
}
```

Запуск сервиса и регистрация первого узла:

```bash
systemctl enable --now orchestrator.service

orchestrator-client -c discover -i db-master-01:3306
# → db-master-01:3306: discovered (примерный вывод; узел добавлен в граф)

# Просмотр дерева топологии
orchestrator-client -c topology -i db-master-01:3306
# → db-master-01:3306
# → + db-replica-01:3306
# → + db-replica-02:3306
```

**Валидация:**

```bash
curl -s http://localhost:3000/api/lb-check
# → OK

curl -s http://localhost:3000/api/clusters
# → [{"ClusterName":"db-master-01","CountInstances":3}]
```

Web-GUI доступен на `http://orchestrator-host:3000` — кластер должен отображаться в списке, дерево репликации должно совпадать с реальным.

### Сценарий 2. Конфигурация для Production (`orchestrator.conf.json`)

```json
{
  "Debug": false,
  "ListenAddress": ":3000",
  "MySQLTopologyUser": "orchestrator",
  "MySQLTopologyPassword": "str0ng_orch_pass",
  "MySQLOrchestratorHost": "127.0.0.1",
  "MySQLOrchestratorPort": 3306,
  "MySQLOrchestratorDatabase": "orchestrator",
  "MySQLOrchestratorUser": "orc_backend",
  "MySQLOrchestratorPassword": "str0ng_backend_pass",

  "DiscoveryMaxConcurrency": 20,
  "InstancePollSeconds": 5,
  "RecoveryPeriodBlockSeconds": 3600,

  "RecoverMasterClusterFilters": ["*"],
  "RecoverIntermediateMasterClusterFilters": ["*"],

  "FailMasterPromotionIfMissingGTIDs": true,
  "ApplyMySQLPromotionAfterMasterFailover": true,
  "DetachLostReplicasAfterMasterFailover": true,
  "PreventCrossDataCenterMasterFailover": true,

  "ProxySQLNativeIntegration": true,
  "ProxySQLHostgroupsMapping": {
    "WriterHostgroup": 10,
    "ReaderHostgroup": 20
  },

  "OnFailureDetectionProcesses": [
    "echo 'Failure detected: {failureType} on {failedHost}' >> /var/log/orchestrator-events.log"
  ],
  "PostMasterFailoverProcesses": [
    "echo 'Master failed on {failedHost}, promoted {successorHost}' >> /var/log/orchestrator-recovery.log"
  ]
}
```

**Объяснение ключевых параметров:**

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `ListenAddress` | Адрес HTTP-сервера (GUI + API) | `:3000` (по умолчанию) |
| `MySQLTopology*` | Учётные данные для подключения к управляемым инстансам | Минимальные привилегии, см. prerequisites |
| `MySQLOrchestrator*` | Подключение к backend-базе состояния | Отдельная схема; для Raft — SQLite |
| `DiscoveryMaxConcurrency` | Параллельные потоки опроса инстансов | 20–50 для крупных инсталляций |
| `InstancePollSeconds` | Интервал опроса узлов (секунды) | 5 (по умолчанию); для критичных систем 2–3 |
| `RecoveryPeriodBlockSeconds` | Блокировка повторного failover (секунды) | 3600 (1 час) — защита от flapping |
| `RecoverMasterClusterFilters` | Какие кластеры подлежат авто-recovery мастера | `["*"]` или явный список алиасов |
| `RecoverIntermediateMasterClusterFilters` | Авто-recovery промежуточных мастеров | `["*"]` для chained-топологий |
| `FailMasterPromotionIfMissingGTIDs` | Запрет повышения реплики без всех GTID мастера | `true` (безопасность данных) |
| `ApplyMySQLPromotionAfterMasterFailover` | Выполнение SQL для реального повышения (set read_only=OFF и т.д.) | `true` для автоматизации |
| `DetachLostReplicasAfterMasterFailover` | Отсоединение реплик, потерявших данные при failover | `true` — явная ручная работа с потерями вместо тихой расходимости |
| `PreventCrossDataCenterMasterFailover` | Запрет повышения реплики из другого ДЦ | `true` для geo-распределённых кластеров |
| `ProxySQLNativeIntegration` | Нативное обновление hostgroups ProxySQL (4.30+) | `true` при использовании ProxySQL |
| `ProxySQLHostgroupsMapping` | Соответствие writer/reader hostgroups | Значения должны совпадать с конфигурацией ProxySQL |
| `OnFailureDetectionProcesses` | Hook при обнаружении сбоя (до recovery) | Алертинг в PagerDuty/Telegram |
| `PostMasterFailoverProcesses` | Hook после повышения нового мастера | Обновление точки входа, уведомления |

Переменные-шаблоны в hooks: `{failureType}`, `{failedHost}`, `{failedPort}`, `{successorHost}`, `{successorPort}`, `{clusterName}`.

### Сценарий 3. Ручное управление топологией (CLI)

Используется для плановых работ или при отключенном авто-failover. Два бинарника: `orchestrator` — полноценный CLI (подключается к backend напрямую), `orchestrator-client` — тонкий клиент поверх HTTP API (сам находит лидера Raft-кластера; в HA-инсталляциях используйте именно его).

- **Graceful Takeover (Плановое переключение):**
  Используется для патчинга мастера. Реплика догоняет мастера, мастер переходит в Read-Only, реплика становится новым мастером. Требует живого мастера.
  ```bash
  orchestrator-client -c graceful-master-takeover -i my_cluster -d new-master-host:3306
  # → my_cluster: success. Newly promoted master: new-master-host:3306 (примерный вывод)
  ```

- **Forced Takeover (Аварийное переключение):**
  Используется, если мастер полностью недоступен. Работает и при живом мастере, но без graceful-последовательности — возможна потеря неподтверждённых транзакций.
  ```bash
  orchestrator-client -c force-master-takeover -i my_cluster
  ```
  Альтернатива — `force-master-failover` (семантика аварийного failover с полным циклом recovery).

- **Рефакторинг дерева репликации:**

  ```bash
  # Поднять реплику на уровень выше (под промежуточного мастера)
  orchestrator-client -c move-up -i db-replica-03:3306

  # Подчинить реплику другому мастеру
  orchestrator-client -c move-below -i db-replica-03:3306 -d db-replica-01:3306

  # Вернуть бывшего мастера под нового мастера после failover
  orchestrator-client -c move-below -i old-master-host:3306 -d new-master-host:3306

  # Переподключить реплику без смены мастера (разрыв/восстановление репликации)
  orchestrator-client -c reconnect -i db-replica-02:3306
  ```

- **Maintenance Mode (плановые работы на узле):**

  ```bash
  orchestrator-client -c begin-maintenance -i db-replica-01:3306 \
    --duration 30m --reason "kernel upgrade"
  # → db-replica-01:3306: maintenance enabled for 30m0s (примерный вывод)

  orchestrator-client -c end-maintenance -i db-replica-01:3306
  ```

  В maintenance-режиме узел исключается из авто-recovery как кандидат и на нём не запускаются автоматические перестроения.

**Валидация после switchover:**

```sql
-- На новом мастере: ожидаем read_only = OFF
SELECT @@read_only, @@super_read_only;
-- → 0, 0

-- На остальных репликах: Master_Host = новый мастер, Replica_SQL_Running = Yes
SHOW REPLICA STATUS\G
```

### Сценарий 4. HA самого Orchestrator (Raft-кластер)

Чтобы инструмент управления не стал Single Point of Failure, разворачивайте 3 узла Orchestrator в Raft-режиме (нечётное число — для кворума). Конфигурация каждого узла дополняется секцией:

```json
{
  "RaftEnabled": true,
  "RaftDataDir": "/var/lib/orchestrator",
  "DefaultRaftPort": 10008,
  "RaftBind": "10.0.0.11",
  "RaftNodes": ["10.0.0.11", "10.0.0.12", "10.0.0.13"],
  "EnableSQLiteBackend": true
}
```

- `RaftBind` — адрес данного узла; `RaftNodes` — полный список членов кластера; порт 10008 используется для межузлового консенсуса.
- `EnableSQLiteBackend: true` — каждый узел хранит состояние локально (требование Raft-режима: независимый backend на узле).
- Recovery-операции выполняет только лидер; остальные узлы проксируют запросы. Клиент `orchestrator-client` автоматически находит лидера.

**Валидация:**

```bash
curl -s http://localhost:3000/api/leader-check
# → OK на лидере; ошибка на follower (примерный вывод)

# В версии 4.30+ доступны Kubernetes-native пробы:
curl -s http://localhost:3000/health/live   # → OK (процесс жив)
curl -s http://localhost:3000/health/ready  # → OK (готов обслуживать)
curl -s http://localhost:3000/health/leader # → OK только на лидере
```

### Сценарий 5. Нативная интеграция с ProxySQL

При `ProxySQLNativeIntegration: true` (версия 4.30+) Orchestrator сам управляет hostgroups ProxySQL во время failover:

1. **Pre-failover:** старый мастер переводится в `OFFLINE_SOFT` — ProxySQL прекращает направлять на него новую запись, не обрывая активные соединения.
2. Orchestrator повышает реплику на уровне MySQL.
3. **Post-failover:** новый мастер перемещается в writer hostgroup, реплики — в reader hostgroup; таблица `mysql_servers` обновляется напрямую.
4. ProxySQL мгновенно маршрутизирует запись на нового мастера — приложениям не требуется перенастройка.

Подробная настройка обеих сторон — в разделе [Интеграция с Orchestrator](./ProxySQL/proxysql_overview.md#4-интеграция-с-orchestrator-нативная-поддержка).

---

## Лучшие практики SRE

1.  **GTID Mode:** Всегда используйте `Global Transaction ID`. Orchestrator намного эффективнее работает с GTID, так как это гарантирует корректное переподключение реплик к новому мастеру без риска потери данных. Без GTID автоматический failover возможен, но переподключение реплик эвристично и менее надёжно.
2.  **Quorum:** Разворачивайте Orchestrator в кластере из 3 узлов (Raft-консенсус), чтобы сам инструмент управления не стал Single Point of Failure. Размещайте узлы в разных зонах доступности.
3.  **Maintenance Mode:** Перед проведением работ на узле БД переводите его в `Maintenance Mode` через GUI/API Orchestrator, чтобы не спровоцировать ложный failover.
4.  **Anti-Flapping:** Используйте `RecoveryPeriodBlockSeconds`, чтобы предотвратить цикличные переключения при нестабильной сети.
5.  **Регулярные учения:** Периодически выполняйте `graceful-master-takeover` в staging (и в плановые окна — в production), чтобы проверять hooks, конфигурацию ProxySQL и логику переподключения приложений до реального сбоя.
6.  **Мониторинг самого Orchestrator:** Проверяйте доступность API (`/api/lb-check`), наличие лидера Raft (`/health/leader` в 4.30+) и метрики Prometheus. Молчащий Orchestrator — незамеченный отказ средства защиты.

---

## Диагностика и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **DeadMaster undetected** | Проблемы с доступом к репликам. | Orchestrator считает мастера живым, если видит его через реплики. Проверьте ACL. |
| **Replication Lag** | Высокая нагрузка на Slave. | Проверьте `Slave_SQL_Running_State`. Orchestrator не будет повышать реплику с большим лагом. |
| **Split-Brain** | Сетевая изоляция узла Orchestrator. | Используйте Raft-кластер Orchestrator и проверьте `pc.bootstrap` (если используется Galera). |
| **Access denied for user 'orchestrator'** | Гранты выданы не на всех инстансах (типично — забыли новый реплике). | Примените GRANT-блок из раздела предварительных требований на каждом узле, включая добавляемые. |
| **Топология пустая / реплики не видны** | Не задан `report_host`, discovery не выполнен. | Задайте `report_host` в `my.cnf`, выполните `discover` для корня кластера, проверьте связность с backend-базой. |
| **Raft: нет лидера / статус candidate** | Потеря кворума (2 из 3 узлов недоступны) или закрыт порт 10008. | Восстановите доступность узлов; проверьте межузловую связность и firewall. |
| **Promotion blocked: missing GTIDs** | Реплика-кандидат отстала или имеет пробел в GTID. | При `FailMasterPromotionIfMissingGTIDs: true` повышение блокируется намеренно. Сравните `Executed_Gtid_Set` кандидата и мастера, устраните разрыв или выберите другого кандидата. |
| **Бывший мастер вернулся как независимый источник** | После failover старый мастер не переведён в реплики. | Очистите его репликацию (`STOP REPLICA; RESET REPLICA ALL;`), затем `move-below` под нового мастера. `DetachLostReplicasAfterMasterFailover: true` отсоединяет расходящиеся реплики автоматически. |

**Диагностические команды:**

```bash
# Живость API
curl -s http://localhost:3000/api/lb-check        # → OK

# Список кластеров и их размеры
orchestrator-client -c clusters

# Реплики конкретного узла
orchestrator-client -c replicas -i db-master-01:3306

# Логи сервиса (systemd)
journalctl -u orchestrator -f
```

---

## Дополнительная информация

- **[ProxySQL Deep Dive](./ProxySQL/proxysql_overview.md)** — маршрутизация трафика после failover и детали нативной интеграции.
- **[Обзор MySQL HA](./overview.md)** — архитектурные подходы.
- **[Репозиторий проекта](https://github.com/ProxySQL/orchestrator-original)** — актуальная документация и релизы (поддержка ProxySQL с апреля 2026).
