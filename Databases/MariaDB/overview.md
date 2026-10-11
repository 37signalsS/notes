# MariaDB: Обзор

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**MariaDB** — реляционная система управления базами данных (СУБД) с открытым исходным кодом, созданная как форк MySQL в 2010 году Майклом "Монти" Видениусом после покупки MySQL корпорацией Oracle. Проект управляется независимым **MariaDB Foundation**. MariaDB сохраняет высокую степень совместимости с MySQL (drop-in replacement), но развивается как самостоятельная экосистема с уникальными движками хранения, расширенным SQL-синтаксисом и нативными возможностями для временных данных и кластеризации.

**MariaDB Shell (`mariadb-shell`)** — современный интерактивный клиент, поддерживающий выполнение команд на SQL, JavaScript и Python, а также встроенные инструменты миграции.

**Galera Cluster** — технология синхронной multi-master репликации, интегрированная в MariaDB. Обеспечивает высокую доступность и отсутствие потери данных при сбое узла (RPO=0) для Primary Component кластера, позволяя выполнять запись на любой узел.

**Стандартная репликация (Source-Replica)** — механизм асинхронного или полусинхронного копирования данных. В отличие от Galera, имеет четкое разделение на узел записи (Source) и узлы чтения (Replica), что упрощает масштабирование и снижает требования к сети.

**MaxScale** — интеллектуальный прокси-сервер баз данных. Используется для балансировки нагрузки (Read/Write Split), автоматического переключения (Failover), обеспечения безопасности (SQL-firewall) и маскирования данных. Подробнее см. в **[MaxScale: Обзор и эксплуатация](./MaxScale/maxscale_overview.md)**.

**Thread Pool** — встроенный механизм MariaDB для управления потоками, позволяющий эффективно обрабатывать тысячи одновременных соединений через ограниченное количество рабочих потоков. В MariaDB реализован нативно и доступен во всех редакциях, в отличие от MySQL Enterprise Thread Pool, который является коммерческим плагином. Подробнее см. в **[Конфигурация MariaDB](configuration.md)** и **[Мониторинге MariaDB](monitoring.md)**.

## Основные концепции

### История и стратегия развития

Ключевое отличие стратегии MariaDB — открытость к инновациям от сообщества и быстрое внедрение современных технологий без привязки к коммерческим интересам одного вендора.

- **MariaDB 10.x:** Внедрение Galera Cluster как стандартного решения для HA, расширение поддержки JSON и новых движков (MyRocks, ColumnStore). Версия 10.11 LTS — зрелая стабильная версия, широко используемая в дистрибутивах Linux. Поддержка сообществом до февраля 2028 г.
- **MariaDB 11.x:** Глубокая переработка ядра, включая улучшенный Cost-based Optimizer и нативную поддержку системного версионирования таблиц. Версия 11.4 LTS (май 2024 — май 2029) — Recommended для средних нагрузок. Версия 11.8 LTS (июнь 2025 — июнь 2028) — актуальная LTS-линия.
- **MariaDB 12.x:** Современный этап. LTS-версия 12.3 выпущена 28 мая 2026 года, поддержка до июня 2029 г. Основной фокус на производительности (Thread Pool, SSD/NVMe-оптимизации), Oracle-совместимости (`sql_mode=ORACLE`) и улучшениях ядра (бинарный лог, оптимизатор, безопасность).

### Архитектура и движки хранения

MariaDB использует подключаемую архитектуру движков (**Pluggable Storage Engine API**), что позволяет оптимизировать БД под конкретные нагрузки, выбирая движок индивидуально для каждой таблицы.

1.  **Aria:** Улучшенный crash-safe движок, заменивший MyISAM для системных таблиц MariaDB. Поддерживает эффективное кэширование и восстановление после сбоев через логи транзакций без накладных расходов на полную MVCC-изоляцию.
2.  **InnoDB:** Основной транзакционный движок по умолчанию. MariaDB поддерживает собственные оптимизации InnoDB, включая улучшенную очистку (Purge) и адаптивный хеш-индекс. В 12.3 LTS доступна опция `innodb_snapshot_isolation=ON` для повышения согласованности. Подробнее о параметрах см. в **[Конфигурации MariaDB](configuration.md)**.
3.  **MyRocks:** Движок на базе LSM-дерева (RocksDB), обеспечивающий экстремальное сжатие данных (в 3-4 раза лучше InnoDB) и минимизацию износа SSD. Ограничения: не поддерживает внешние ключи (Foreign Keys). Детальный разбор параметров и SRE-тюнинг см. в **[Движках хранения MariaDB](storage_engines.md)**.
4.  **ColumnStore:** Движок для распределенной аналитики (OLAP) с колоночным хранением и архитектурой MPP (Massively Parallel Processing). Позволяет обрабатывать большие объемы данных с высокой скоростью. Подробнее см. в **[Движках хранения MariaDB](storage_engines.md)**.
5.  **Spider:** Движок для прозрачного шардирования, распределяющий данные одной таблицы между несколькими удаленными узлами MariaDB с поддержкой распределенных транзакций XA (2PC). Детали конфигурации см. в **[Движках хранения MariaDB](storage_engines.md)**.

### Ключевые возможности

1.  **Системно-версионируемые таблицы (System-Versioned Tables):**
    Автоматическое хранение истории всех изменений строк с поддержкой стандарта SQL:2011. Использование: аудит, восстановление состояния данных на момент времени (`AS OF`), анализ изменений. Доступно с MariaDB 10.3+. Сценарии разбивки на партиции см. в **[Обслуживании MariaDB](maintenance.md)**.

2.  **Расширенная совместимость:**
    - Режим `sql_mode=ORACLE` позволяет запускать хранимые процедуры, совместимые с Oracle PL/SQL.
    - Поддержка невидимых столбцов (Invisible Columns) и виртуальных столбцов (Generated Columns).
    - Нативные плагины аутентификации: `unix_socket`, `ed25519`, `mysql_native_password`. Подробнее см. в **[Безопасности MariaDB](security/index.md)**.

3.  **Cost-based Optimizer:**
    В MariaDB 11.x+ внедрен улучшенный стоимостный оптимизатор с учетом веса движков и особенностей распределенных запросов. Различия в оптимизаторе могут привести к тому, что один и тот же запрос будет выполняться по-разному на MySQL и MariaDB, поэтому тестирование планов выполнения (`EXPLAIN`) обязательно перед миграции.

### Сравнение с MySQL 8.x/9.x

| Характеристика | MariaDB (12.3 LTS) | MySQL (8.4/9.x) |
| :--- | :--- | :--- |
| **Оптимизатор** | Cost-based, учет веса движков, фокус на JOIN | Oracle Optimizer, глубокая привязка к InnoDB |
| **Движки** | Aria, MyRocks, Spider, ColumnStore | Преимущественно InnoDB |
| **Временные данные** | Нативная поддержка системного версионирования (10.3+) | Ограниченная поддержка через триггеры |
| **Кластеризация** | Встроенная Galera (Multi-Master) | InnoDB Cluster (Group Replication) |
| **Схема данных** | JSON как LONGTEXT с CHECK (JSON_VALID), Generated Columns | Бинарный JSON,Generated Columns |
| **Пул потоков** | Встроен во все редакции | Enterprise plugin only |
| **Лицензирование** | GPLv2 (сервер), BSL/proprietary (MaxScale 25.01+) | GPLv2 / Commercial (Oracle) |

**Критическое замечание:** Из-за различных реализаций GTID (Global Transaction ID) и бинарных логов прямая репликация между MySQL 8.x+ и MariaDB 11/12 невозможна. Рекомендуется использовать `mariadb-dump` для миграции. Детальный разбор несовместимостей см. в **[Миграции с MySQL](./Operations/migration_mysql_to_mariadb.md)**.

## Практические сценарии

### Управление системным версионированием

Создание таблиц, которые автоматически отслеживают историю изменений строк.

**Prerequisites:** MariaDB 10.3+.

```sql
-- Создание таблицы с версионированием
CREATE TABLE product_prices (
    id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100),
    price DECIMAL(10, 2)
) WITH SYSTEM VERSIONING;

-- Запрос данных на конкретный момент в прошлом
SELECT * FROM product_prices FOR SYSTEM_TIME AS OF '2026-08-15 10:00:00';

-- Запрос всей истории изменений строки
SELECT * FROM product_prices FOR SYSTEM_TIME ALL WHERE product_name = 'SSD 1TB';
```

Сценарии разбивки исторических и текущих данных на партиции описаны в **[Обслуживании MariaDB](maintenance.md)**.

### Настройка Thread Pool для высоконагруженных сред

Рекомендуется для систем с количеством соединений > 500.

**Настройка в `my.cnf`:**
```ini
[mariadb]
thread_handling = pool-of-threads
thread_pool_size = 16  # Обычно равно количеству ядер CPU
thread_pool_max_threads = 1000
```

**Валидация:**
```sql
SHOW GLOBAL STATUS LIKE 'Threadpool_threads';
-- Если значение близко к thread_pool_max_threads, требуется увеличение лимита или оптимизация запросов.
```

Диагностика утечек памяти и мониторинг Thread Pool в Prometheus описаны в **[Мониторинге MariaDB](monitoring.md)**.

### Сценарии миграции и обновления

Для обеспечения непрерывности бизнеса и перехода с других систем используйте следующие руководства:
*   **[Миграция с MySQL](./Operations/migration_mysql_to_mariadb.md)** — детальный разбор несовместимостей (GTID, аутентификация) и процедура логического переноса.
*   **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — стратегии поочередного обновления узлов в Galera Cluster и топологии Source-Replica без остановки сервиса.

## Диагностика и устранение неисправностей

### Диагностика Galera Cluster

При возникновении проблем с кластером (например, узел не принимает записи), проверьте статус синхронизации и Flow Control. `wsrep_flow_control_paused` не должен оставаться выше 0 долгое время — это признак того, что один из узлов не справляется с нагрузкой. Детальная диагностика очередей и метрик доступна в **[Мониторинге MariaDB](monitoring.md)** и **[Отказоустойчивости MariaDB](high_availability.md)**.

### Анализ медленных запросов

MariaDB поддерживает расширенный вывод `EXPLAIN`.

```sql
EXPLAIN FORMAT=JSON SELECT ...;
-- В 12.3 LTS вывод включает детальную информацию о стоимости каждой операции (cost),
-- что позволяет понять, почему оптимизатор выбрал конкретный индекс.
```

### Проверка состояния репликации

```sql
-- Проверка GTID-репликации
SHOW SLAVE STATUS\G

-- Проверка положения репликации
SHOW MASTER STATUS;

-- Проверка статуса Galera
SHOW STATUS LIKE 'wsrep_%';
```

Диагностика ошибок репликации и GTID-лаг описана в **[Репликации MariaDB: Устранение неполадок](./replication/troubleshooting.md)**.

## Лучшие практики

1.  **Capacity Planning:** При проектировании кластера учитывайте, что Galera Cluster работает только на Linux и преимущественно с движком InnoDB. Thread Pool в MariaDB масштабируется до тысяч соединений, но требует соответствия `thread_pool_size` количеству ядер CPU.
2.  **Topology Selection:** Для систем с требованием RPO=0 и multi-master доступа используйте Galera Cluster. Для масштабирования чтения с простым failover — Source-Replica с Orchestrator. Детали см. в **[Отказоустойчивости MariaDB](high_availability.md)**.
3.  **License Compliance:** MaxScale до версии 24.02 распространяется под BSL (бесплатно до 2 backend-серверов). Начиная с версии 25.01 (январь 2025), MaxScale переведен на проприетарную коммерческую лицензию, требующую подписки для production. Учитывайте это при выборе версии прокси.
4.  **Monitoring:** Включите сбор метрик Thread Pool (`collect.info_schema.processlist`), Galera (`wsrep_*`) и Aria (`Aria_*`) через экспортер Prometheus. Пороги алертинга см. в **[Мониторинге MariaDB](monitoring.md)**.
5.  **Change Management:** Любое обновление MariaDB должно проходить через Change Advisory Board (CAB) с согласованным окном обслуживания, stop-loss критериями и emergency bridge для экстренной связи. Обновление Galera требует особого внимания к пакетам: в MariaDB 12.3 пакет Galera больше не является зависимостью стандартного `mariadb-server`; требуется явная установка `mariadb-server-galera`. Подробнее см. в **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)**.

## Особенности и ограничения

-   **MySQL 8.0 Compatibility:** MariaDB **не является** 100% совместимой с MySQL 8.0+. Некоторые типы данных (например, пространственные индексы) и форматы аутентификации различаются. Физическая миграция с MySQL 8.0+ невозможна; требуется логическая миграция через `mariadb-dump`.
-   **Storage Engine Limits:** Движок MyRocks не поддерживает внешние ключи (Foreign Keys) и требует специальной настройки для эффективной работы с памятью. Galera Cluster поддерживает преимущественно InnoDB (экспериментальная поддержка MyISAM и Aria начиная с MariaDB 10.6).
-   **MaxScale Licensing:** До версии 24.02 — BSL (бесплатно до 2 backend-серверов). Начиная с версии 25.01 — проприетарная коммерческая лицензия, требующая подписки MariaDB Enterprise для production.
-   **Galera Platform Support:** MariaDB Galera Cluster доступен только на Linux. Для Windows и macOS используйте классическую репликацию Source-Replica.
-   **Thread Pool Units:** При миграции с MySQL Enterprise Thread Pool обратите внимание, что в MariaDB `thread_pool_stall_limit` измеряется в миллисекундах, тогда как в Oracle MySQL — в единицах 10 мс.

## Дополнительная информация

### Связанные документы

*   **[Движки хранения MariaDB](storage_engines.md)** — глубокий разбор InnoDB, MyRocks, ColumnStore и Spider.
*   **[Отказоустойчивость MariaDB](high_availability.md)** — Galera Cluster, Orchestrator и MaxScale.
*   **[Репликация MariaDB: Обзор](./replication/overview.md)** — стандартные Source-Replica топологии и GTID.
*   **[Клиентские утилиты MariaDB](client_utilities.md)** — обзор `mariadb-shell`, `mariadb-dump` и переход на новые имена CLI.
*   **[MaxScale: Обзор и эксплуатация](./MaxScale/maxscale_overview.md)** — детальное руководство по прокси для MariaDB.
*   **[Хранимые объекты в MariaDB](./Concepts/stored_objects_management.md)** — процедуры, функции, триггеры и Event Scheduler.
*   **[Мониторинг MariaDB: Prometheus и Galera](monitoring.md)** — метрики SRE-уровня.
*   **[Управление памятью в MariaDB](memory_management.md)** — расчет буферов и диагностика утечек.
*   **[Конфигурация MariaDB](configuration.md)** — тюнинг `my.cnf`, параметры Thread Pool и кеширование.
*   **[Безопасность MariaDB](security/index.md)** — SSL/TLS, Аудит, TDE и ролевая модель (RBAC).
*   **[Обслуживание MariaDB](maintenance.md)** — дефрагментация, секционирование и системное версионирование.
*   **[Безопасная установка MariaDB](installation_and_setup.md)** — практическое руководство по `mariadb-secure-installation`.
*   **[Миграция с MySQL](./Operations/migration_mysql_to_mariadb.md)** — пошаговый чек-лист перехода.
*   **[Zero-Downtime Upgrade](./Operations/zero_downtime_upgrade.md)** — стратегия обновления без простоя.
*   **[Оптимизация запросов](query_optimization.md)** — EXPLAIN, ANALYZE, гистограммы, pt-query-digest.
*   **[Индексы](indexing.md)** — типы индексов, Ignored Indexes, обслуживание.
*   **[Кодировки и сопоставления](charset_and_collation.md)** — charset/collation, UCA, дефолты версий.
*   **[Часовые пояса](time_zones.md)** — time_zone, TIMESTAMP vs DATETIME, CONVERT_TZ.
*   **[JSON](json.md)** — функции JSON, JSON_TABLE, хранение как LONGTEXT.
*   **[Временные таблицы](temporary_tables.md)** — внутренние временные таблицы, tmp_table_size.
*   **[Справочник кодов ошибок](error_codes.md)** — частые коды 1040/1045/1062/1205/1213 и др.
*   **[Единый runbook устранения неполадок](troubleshooting_runbook.md)** — пошаговые процедуры для инцидентов.
*   **[Управление логами и logrotate](log_management.md)** — ротация error/slow/binlog.
*   **[MariaDB под systemd](systemd.md)** — юнит, лимиты (LimitNOFILE), multi-instance.
*   **[Управление соединениями](connection_management.md)** — max_connections, Thread Pool, connection storm.
*   **[ProxySQL](proxysql.md)** — read/write split, connection pooling, query rules.
*   **[MariaDB в Docker](docker.md)** — эксплуатация контейнера, env-переменные, healthcheck.
*   **[Нагрузочное тестирование](performance_testing.md)** — sysbench и mariadb-slap.
*   **[Capacity Planning](capacity_planning.md)** — sizing CPU/RAM/диск/сеть одиночного инстанса.
*   **[InnoDB Purge и Undo Log](innodb_purge_and_undo.md)** — purge threads, history list, undo truncation.
*   **[Disaster Recovery](disaster_recovery.md)** — DR runbook, RTO/RPO, PITR, стратегия 3-2-1-1-0.
*   **[Вопросы на собеседование](interview_questions.md)** — общие вопросы по MariaDB.

### См. также

*   **[Резервное копирование MariaDB](backup_and_recovery.md)** — методы создания резервных копий и PITR.
*   **[Настройка репликации MariaDB](./replication/setup_guide.md)** — пошаговое руководство по Source-Replica и GTID.
*   **[Официальная документация MariaDB](https://mariadb.com/kb/en/documentation/)** — актуальные руководства и release notes.
*   **[MariaDB Foundation](https://mariadb.org/)** — информация о проекте, сообществе и governance.
