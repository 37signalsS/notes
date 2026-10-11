# MySQL Orchestrator: Управление топологией и Failover

**Актуально для:** Orchestrator 4.31.1+, MySQL 5.7 / 8.0 / 8.4

## Определения

**Orchestrator** — инструмент для обнаружения (discovery), визуализации и автоматического восстановления (failover) топологий репликации MySQL. Понимает сложные деревья репликации и может автоматически перестраивать топологию при сбое любого узла. Написан на Go, распространяется как единый бинарник (`orchestrator`) плюс тонкий клиент (`orchestrator-client`). Предоставляет Web-GUI и REST API.

**Discovery:** Процесс автоматического сканирования кластера и построения графа репликации. Orchestrator периодически подключается к каждому известному инстансу по MySQL-протоколу, читает `SHOW REPLICA STATUS` / `SHOW SOURCE STATUS` и строит живой граф «кто кого реплицирует».

**Failover:** Автоматический или ручной процесс повышения реплики до статуса источника (Primary/Source) при обнаружении отказа текущего мастера. Включает выбор наиболее актуальной реплики, её повышение и переподключение остальных реплик к новому источнику.

**Switchover (Graceful Takeover):** Плановое переключение роли мастера при живом исходном мастере (патчинг, обслуживание). Гарантирует отсутствие потери данных, так как реплика синхронизируется до переключения.

**Topology Refactoring:** Перестроение дерева репликации — перенос реплик между мастерами без остановки репликации (CLI-команды `move-up`, `move-below` или Drag-and-Drop в GUI).

**Raft-консенсус:** Протокол распределённого согласования, используемый для построения HA-кластера самого Orchestrator: узлы выбирают лидера, а операции восстановления выполняет только лидер, что исключает конкурирующие failover от разных узлов.

## Базовые концепции

### Архитектура и эксплуатация Orchestrator

Orchestrator состоит из трёх логических частей:

1. **Сервис Orchestrator** — процесс на Go, который выполняет discovery, детектирование сбоев и recovery. Слушает HTTP-порт (по умолчанию `:3000`) и обслуживает Web-GUI и REST API.
2. **Backend-база данных** — хранилище внутреннего состояния (топология, история сбоев, настройки). Поддерживается MySQL/MariaDB-схема либо встроенный SQLite (обязателен для Raft-режима). Таблицы создаются автоматически при первом запуске.
3. **Клиенты** — Web-GUI для операторов, REST API для автоматизации, `orchestrator` (CLI, прямое подключение к backend) и `orchestrator-client` (тонкий клиент, обращается через HTTP API работающего узла — предпочтителен в Raft-кластерах, так как сам находит лидера).

### Механизм детектирования

Ключевая особенность: Orchestrator анализирует состояние мастера **через его реплики**, а не только напрямую. Если мастер не отвечает самому Orchestrator, но реплики продолжают получать от него binlog-события, мастер считается живым. Это защищает от ложных failover при сетевых проблемах между Orchestrator и мастером (например, недоступность одного дата-центра).

### Эксплуатационные требования (Prerequisites)

Перед установкой необходимо убедиться в выполнении следующих условий:

- **ОС и systemd:** Поддерживаются RHEL 9+/Rocky 9+/AlmaLinux 9+ и Ubuntu 22.04+/Debian 12+. Сервис управляется через systemd (`orchestrator.service`).
- **Ресурсы:** Минимум 1 ГБ RAM, 1 ядро CPU. Для Production с >100 инстансов — 2+ ядра и 2+ ГБ RAM.
- **Сеть:** Orchestrator должен подключаться к каждому управляемому MySQL по порту `3306/tcp`. Узлы Raft-кластера — друг к другу по порту `10008/tcp` (по умолчанию). Порт `3000/tcp` должен быть открыт для операторов и автоматизации.
- **Firewall:** Убедитесь, что `firewalld`/`ufw` разрешает указанные порты между Orchestrator и управляемыми инстансами.
- **NTP:** Время на всех узлах (Orchestrator и MySQL) должно быть синхронизировано через `chrony` или `systemd-timesyncd`. Смещение часов (clock skew) повреждает binlog timestamps и ломает мониторинг лага репликации.
- **Лимиты файлов:** Увеличьте `ulimit -n` до минимум 65535 для сервиса Orchestrator, так как он поддерживает множество одновременных соединений к MySQL и backend-базе.
- **Backend-база:** Отдельная схема MySQL или локальный SQLite. Для Raft-режима требуется независимый backend на каждом узле (SQLite).
- **`report_host`:** задайте в `my.cnf` каждого сервера уникальное имя, иначе discovery покажет пустые hostname.

### Пользователи и привилегии

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

### История и состояние проекта (2026)

Проект создан Шломи Ноахом (Outbrain), затем поддерживался GitHub ([github/orchestrator](https://github.com/github/orchestrator)), после чего перешёл в организацию [openark](https://github.com/openark/orchestrator), затем поддерживался Percona ([percona/orchestrator](https://github.com/percona/orchestrator)). **С 2026 года проект поддерживается командой ProxySQL** — актуальный репозиторий [ProxySQL/orchestrator](https://github.com/ProxySQL/orchestrator). Это обеспечило нативную интеграцию: Orchestrator напрямую обновляет hostgroups в ProxySQL через встроенные failover-хуки, без внешних скриптов.

Актуальная версия линейки **4.30.0** (репозиторий [ProxySQL/orchestrator](https://github.com/ProxySQL/orchestrator)) принесла:

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

## Практические сценарии

### Сценарий 1. Установка и регистрация кластера

Установка из релизного архива (последний релиз — 4.31.1, 2026-07-28):

```bash
wget https://github.com/ProxySQL/orchestrator/releases/download/v4.31.1/orchestrator-4.31.1-linux-amd64.tar.gz
tar -xzf orchestrator-4.31.1-linux-amd64.tar.gz -C /usr/local/
ln -s /usr/local/orchestrator/orchestrator /usr/local/bin/orchestrator
ln -s /usr/local/orchestrator/orchestrator-client /usr/local/bin/orchestrator-client
mkdir -p /etc/orchestrator /var/lib/orchestrator /var/log/orchestrator
```

#### Systemd Unit

Создайте файл `/etc/systemd/system/orchestrator.service`:

```ini
[Unit]
Description=MySQL Orchestrator
After=network.target mysql.service
Wants=mysql.service

[Service]
Type=simple
User=orchestrator
Group=orchestrator
ExecStart=/usr/local/bin/orchestrator --config /etc/orchestrator/orchestrator.conf.json
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

# Пути к логам и данным
StandardOutput=journal
StandardError=journal
SyslogIdentifier=orchestrator

[Install]
WantedBy=multi-user.target
```

Включите и запустите сервис:

```bash
sudo useradd -r -s /bin/false orchestrator
sudo chown -R orchestrator:orchestrator /etc/orchestrator /var/lib/orchestrator /var/log/orchestrator
sudo systemctl daemon-reload
sudo systemctl enable --now orchestrator.service
```

#### Валидация установки

```bash
# Проверка статуса службы
sudo systemctl status orchestrator --no-pager | head -3
# → Active: active (running)

# Проверка слушаемых портов
sudo ss -tulpn | grep 3000
# → LISTEN 0 4096 *:3000 *:*

# Проверка версии
orchestrator --version
# → 4.30.0
```

### Сценарий 2. Production конфигурация (`orchestrator.conf.json`)

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

Полная Production-конфигурация:

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

  "ProxySQL": {
    "ProxySQLAdminAddress": "10.0.1.10:6032",
    "ProxySQLAdminPort": 6032,
    "ProxySQLAdminUser": "orchestrator",
    "ProxySQLAdminPassword": "СЛОЖНЫЙ_ПАРОЛЬ",
    "ProxySQLWriterHostgroup": 10,
    "ProxySQLReaderHostgroup": 20,
    "ProxySQLPreFailoverAction": true
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
| `ProxySQLAdminAddress` | Адрес admin-интерфейса ProxySQL (`host:port`) | Адрес узла ProxySQL в формате `host:port` |
| `ProxySQLAdminPort` | Порт admin-интерфейса ProxySQL | `6032` |
| `ProxySQLAdminUser` / `ProxySQLAdminPassword` | Учётные данные для подключения к admin-интерфейсу | Отдельный пользователь admin-интерфейса |
| `ProxySQLWriterHostgroup` | Hostgroup, в который помещается writer | Должен совпадать с hostgroup в `mysql_replication_hostgroups` |
| `ProxySQLReaderHostgroup` | Hostgroup, в который помещаются реплики | Должен совпадать с hostgroup в `mysql_replication_hostgroups` |
| `ProxySQLPreFailoverAction` | Обновлять ли hostgroups до или после MySQL-failover | `true` при использовании ProxySQL |
| `OnFailureDetectionProcesses` | Hook при обнаружении сбоя (до recovery) | Алертинг в PagerDuty/Telegram |
| `PostMasterFailoverProcesses` | Hook после повышения нового мастера | Обновление точки входа, уведомления |

Переменные-шаблоны в hooks: `{failureType}`, `{failedHost}`, `{failedPort}`, `{successorHost}`, `{successorPort}`, `{clusterName}`.

#### Валидация конфигурации

```bash
# Проверка синтаксиса JSON
jq . /etc/orchestrator/orchestrator.conf.json > /dev/null
# → (пустой вывод при валидном JSON)

# Проверка доступности API
curl -s http://localhost:3000/api/lb-check
# → OK

# Проверка списка кластеров
curl -s http://localhost:3000/api/clusters
# → [{"ClusterName":"db-master-01","CountInstances":3}]
```

### Сценарий 3. Ручное управление топологией (CLI)

Используется для плановых работ или при отключенном авто-failover. Два бинарника: `orchestrator` — полноценный CLI (подключается к backend напрямую), `orchestrator-client` — тонкий клиент поверх HTTP API (сам находит лидера Raft-кластера; в HA-инсталляциях используйте именно его).

- **Graceful Takeover (Плановое переключение):**
  Используется для патчинга мастера. Реплика догоняет мастера, мастер переходит в Read-Only, реплика становится новым мастером. Требует живого мастера.
  ```bash
  orchestrator-client -c graceful-master-takeover -i my_cluster -d new-master-host:3306
  # → my_cluster: success. Newly promoted master: new-master-host:3306
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
  # → db-replica-01:3306: maintenance enabled for 30m0s

  orchestrator-client -c end-maintenance -i db-replica-01:3306
  ```

  В maintenance-режиме узел исключается из авто-recovery как кандидат и на нём не запускаются автоматические перестроения.

#### Валидация после switchover

```sql
-- На новом мастере: ожидаем read_only = OFF
SELECT @@read_only, @@super_read_only;
-- → 0, 0

-- На остальных репликах: Source_Host = новый источник, Replica_SQL_Running = Yes
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

#### Валидация Raft-кластера

```bash
# Проверка лидера (OK на лидере; ошибка на follower)
curl -s http://localhost:3000/api/leader-check
# → OK

# Kubernetes-native пробы (4.30+)
curl -s http://localhost:3000/health/live   # → OK (процесс жив)
curl -s http://localhost:3000/health/ready  # → OK (готов обслуживать)
curl -s http://localhost:3000/health/leader # → OK только на лидере

# Список кластеров и их размеры
orchestrator-client -c clusters

# Реплики конкретного узла
orchestrator-client -c replicas -i db-master-01:3306
```

### Сценарий 5. Нативная интеграция с ProxySQL

При заполненной секции `ProxySQL` в `orchestrator.conf.json` Orchestrator сам управляет hostgroups ProxySQL во время failover:

1. **Pre-failover:** старый мастер переводится в `OFFLINE_SOFT` — ProxySQL прекращает направлять на него новую запись, не обрывая активные соединения.
2. Orchestrator повышает реплику на уровне MySQL.
3. **Post-failover:** новый мастер перемещается в writer hostgroup, реплики — в reader hostgroup; таблица `mysql_servers` обновляется напрямую.
4. ProxySQL мгновенно маршрутизирует запись на нового мастера — приложениям не требуется перенастройка.

> **Примечание:** Детальная настройка обеих сторон описана в разделе [Интеграция с Orchestrator](./ProxySQL/proxysql_overview.md#4-интеграция-с-orchestrator-нативная-поддержка).

## Best Practices SRE

1.  **GTID Mode:** Всегда используйте `Global Transaction ID`. Orchestrator намного эффективнее работает с GTID, так как это гарантирует корректное переподключение реплик к новому мастеру без риска потери данных. Без GTID автоматический failover возможен, но переподключение реплик эвристично и менее надёжно.
2.  **Quorum:** Разворачивайте Orchestrator в кластере из 3 узлов (Raft-консенсус), чтобы сам инструмент управления не стал Single Point of Failure. Размещайте узлы в разных зонах доступности.
3.  **Maintenance Mode:** Перед проведением работ на узле БД переводите его в `Maintenance Mode` через GUI/API Orchestrator, чтобы не спровоцировать ложный failover.
4.  **Anti-Flapping:** Используйте `RecoveryPeriodBlockSeconds`, чтобы предотвратить цикличные переключения при нестабильной сети.
5.  **Регулярные учения:** Периодически выполняйте `graceful-master-takeover` в staging (и в плановые окна — в production), чтобы проверять hooks, конфигурацию ProxySQL и логику переподключения приложений до реального сбоя.
6.  **Мониторинг самого Orchestrator:** Проверяйте доступность API (`/api/lb-check`), наличие лидера Raft (`/health/leader` в 4.30+) и метрики Prometheus. Молчащий Orchestrator — незамеченный отказ средства защиты.
7.  **Backup конфигурации:** Храните `orchestrator.conf.json` и backend-схему в системе управления конфигурациями (Git, Ansible). Восстановление после сбоя orchestrator — вопрос времени, если конфигурация не потеряна.
8.  **Capacity Planning:** Для сред с >100 управляемыми инстансами увеличьте `DiscoveryMaxConcurrency` до 50, выделите отдельный backend на SSD и мониторьте лаг API (`/api/clusters` latency).

## Устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **DeadMaster undetected** | Проблемы с доступом к репликам. Orchestrator считает мастера живым, если видит его через реплики. | Проверьте ACL на управляемых инстансах, сетевую связность и пользователя `orchestrator`. |
| **Replication Lag** | Высокая нагрузка на Slave. | Проверьте `Replica_SQL_Running_State`. Orchestrator не будет повышать реплику с большим лагом. |
| **Split-Brain** | Сетевая изоляция узла Orchestrator или потеря кворума Raft. | Используйте Raft-кластер Orchestrator и проверьте `pc.bootstrap` (если используется Galera). |
| **Access denied for user 'orchestrator'** | Гранты выданы не на всех инстансах (типично — забыли новый реплике). | Примените GRANT-блок из раздела предварительных требований на каждом узле, включая добавляемые. |
| **Топология пустая / реплики не видны** | Не задан `report_host`, discovery не выполнен. | Задайте `report_host` в `my.cnf`, выполните `discover` для корня кластера, проверьте связность с backend-базой. |
| **Raft: нет лидера / статус candidate** | Потеря кворума (2 из 3 узлов недоступны) или закрыт порт 10008. | Восстановите доступность узлов; проверьте межузловую связность и firewall. |
| **Promotion blocked: missing GTIDs** | Реплика-кандидат отстала или имеет пробел в GTID. | При `FailMasterPromotionIfMissingGTIDs: true` повышение блокируется намеренно. Сравните `Executed_Gtid_Set` кандидата и мастера, устраните разрыв или выберите другого кандидата. |
| **Бывший мастер вернулся как независимый источник** | После failover старый мастер не переведён в реплики. | Очистите его репликацию (`STOP REPLICA; RESET REPLICA ALL;`), затем `move-below` под нового мастера. `DetachLostReplicasAfterMasterFailover: true` отсоединяет расходящиеся реплики автоматически. |
| **Raft: lost quorum** | Доступно менее 2 узлов из 3. | Восстановите недоступный узел. При невозможности — разверните новый узел и добавьте в кластер; Raft сам переизберёт лидера при восстановлении кворума. |
| **Backend-база недоступна** | MySQL/MariaDB или SQLite backend не отвечает. | Проверьте статус сервиса backend-базы, место на диске и права пользователя `orc_backend`. В Raft-режиме проверьте локальный SQLite на каждом узле. |
| **Метрики Prometheus не работают** | Встроенный эндпоинт `/metrics` не включён или заблокирован firewall. | Проверьте `curl http://localhost:3000/metrics`. Убедитесь, что порт 3000 открыт для Prometheus. |
| **Логи Orchestrator не пишутся** | Неправильные права на `/var/log/orchestrator` или отсутствие места на диске. | Проверьте `ls -la /var/log/orchestrator` и `df -h`. Убедитесь, что сервис запущен от пользователя `orchestrator`. |
| **Stale leader в Raft** | Лидер потерял связь с большинством узлов, но продолжает обслуживать запросы. | Raft автоматически выполнит новый выбор лидера при восстановлении кворума. Проверьте межузловую связность и время работы лидера. |

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

# Проверка статуса Raft-кластера (лидер/follower)
curl -s http://localhost:3000/api/raft-status
```

## Краевые случаи (Edge Cases)

### Миграция с 3.2.x на 4.30+

При обновлении с линейки openark (3.2.x) на ProxySQL-линейку (4.30+):

1. Остановите старый сервис Orchestrator.
2. Сделайте бэкап backend-базы (схема `orchestrator`).
3. Замените бинарники на версию 4.30.0.
4. Обновите `orchestrator.conf.json`, добавив секцию `ProxySQL` при необходимости.
5. Запустите сервис и проверьте `/api/clusters`.

### Использование SQLite vs MySQL backend

- **SQLite:** Обязателен для Raft-режима (независимый backend на каждом узле). Подходит для сред с <50 инстансами.
- **MySQL/MariaDB:** Подходит для единого Orchestrator без Raft или для централизованного хранения истории. Требует отдельной схемы и пользователя.

### Гео-распределённый Raft кластер

Размещайте узлы Orchestrator в разных дата-центрах. Убедитесь, что:
- Задержка между узлами < 50 мс (Raft чувствителен к лату).
- Порт 10008 открыт между всеми узлами.
- Включён `PreventCrossDataCenterMasterFailover: true`, чтобы Orchestrator не повышал реплику из другого ДЦ.

### Большое количество инстансов (>100)

- Увеличьте `DiscoveryMaxConcurrency` до 50.
- Используйте отдельный SSD для backend-базы.
- Настройте ротацию логов Orchestrator (`logrotate` или `journald`).
- Мониторьте латентность `/api/clusters` и `/api/raft-status`.

### Смешанные версии MySQL в топологии

Orchestrator 4.30+ поддерживает одновременное управление MySQL 5.7, 8.0 и 8.4. Однако:
- GTID-репликация обязательна для корректного failover.
- Убедитесь, что пользователь `orchestrator` имеет необходимые привилегии на всех версиях (в 5.7 может потребоваться `SUPER`, в 8.0+ — `SYSTEM_VARIABLES_ADMIN`).

### Отказ backend-базы

При недоступности backend-базы Orchestrator продолжает обслуживать read-only запросы (Web-GUI, API), но не может выполнять запись (discovery, recovery). В Raft-режиме с SQLite отказ одного backend не влияет на работу кластера.

## Дополнительная информация

### См. также

- **[ProxySQL Deep Dive](./ProxySQL/proxysql_overview.md)** — маршрутизация трафика после failover и детали нативной интеграции.
- **[Обзор MySQL и форков](./overview.md)** — архитектура и внутренние механизмы.
- **[Репликация MySQL: Обзор](./replication/overview.md)** — механизмы репликации и GTID.
- **[Мониторинг MySQL](./monitoring.md)** — настройка Zabbix и Prometheus.
- **[Обслуживание и обновления MySQL](./maintenance-and-upgrades.md)** — дефрагментация, партиционирование, Major Upgrade.
- **[Репозиторий проекта](https://github.com/ProxySQL/orchestrator)** — актуальная документация и релизы (поддерживается командой ProxySQL).
