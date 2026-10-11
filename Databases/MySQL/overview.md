# MySQL: Обзор и архитектура СУБД

**Актуально для:** MySQL 8.0.x / 8.4 LTS

## Определения

**MySQL** — реляционная система управления базами данных (СУБД), изначально разработанная MySQL AB, ныне поддерживаемая Oracle. Архитектура построена на принципе **Pluggable Storage Engines**, что позволяет подключать различные движки хранения для разных типов задач.

**Форк (Fork)** — ответвление исходного кода, создающее независимый продукт. Форки MySQL сохраняют высокую степень совместимости на уровне протоколов и SQL-синтаксиса, но значительно различаются во внутренних механизмах, оптимизаторах и наборе дополнительных функций.

**Релизные модели (Oracle/Percona):**
- **LTS (Long Term Support):** Стабильные версии (например, **8.4 LTS**). Фокус на надежности и безопасности, цикл поддержки до 8 лет. Рекомендуется для критических Production-систем.
- **Innovation:** Версии с частыми обновлениями (например, **9.0**, **9.1**). Содержат новейшие функции, но имеют короткий цикл поддержки (3 месяца).

**SRE-определения:**
- **Capacity Planning:** Процесс определения требуемых ресурсов (RAM, CPU, disk IOPS) для поддержки целевой нагрузки с запасом.
- **Maintenance Window:** Плановый период простоя для обслуживания: обновление, дефрагментация, переключение реплик.
- **Disaster Recovery (DR):** Комплекс мер для восстановления работы БД после сбоя: бэкапы, PITR, географическое распределение реплик.
- **High Availability (HA):** Архитектурный подход, обеспечивающий непрерывную доступность БД за счет репликации и автоматического переключения (failover).
- **Monitoring:** Сбор метрик (latency, QPS, connections, buffer pool hit rate) и настройка алертов для раннего обнаружения инцидентов.
- **Lifecycle Management:** Управление процессами запуска/остановки, обновления, миграций и вывода из эксплуатации инстансов MySQL.

---

## Базовые концепции

### Внутренняя архитектура и жизненный цикл запроса
MySQL разделена на два уровня: **SQL Layer** (обработка логики) и **Storage Engine Layer** (работа с данными).

**Жизненный цикл запроса:**
1.  **Connection Manager:** Управление TLS-соединениями, аутентификация и проверка прав доступа (ACL).
2.  **Parser:** Лексический и синтаксический анализ, построение дерева разбора.
3.  **Optimizer (Cost-based):** Самый сложный компонент. Выбирает план выполнения на основе статистики, стоимости I/O и CPU. Учитывает индексы, типы JOIN и подзапросы.
4.  **Executor:** Выполнение плана через стандартный API движка хранения.
5.  **Storage Engine:** Непосредственное взаимодействие с файлами данных или памятью.

### Архитектура InnoDB и Buffer Pool
**InnoDB** — основной транзакционный движок хранения (Storage Engine) в MySQL и Percona. В MariaDB используется его форк (ранее XtraDB).

Ключевые механизмы InnoDB:
*   **Buffer Pool:** Главная область оперативной памяти, где кэшируются страницы данных и индексов. 
    *   *Алгоритм LRU:* Использует модифицированный Least Recently Used для предотвращения вымывания кэша при полном сканировании таблиц.
    *   *Dirty Pages:* Измененные в памяти страницы, ожидающие записи на диск (Checkpointer).
*   **Redo Log (WAL):** Журнал опережающей записи. Гарантирует надежность (Durability): при сбое системы изменения восстанавливаются из этого лога. С MySQL 8.0.30 управляется параметром `innodb_redo_log_capacity` (до этого — `innodb_log_file_size` × `innodb_log_files_in_group`).
*   **Undo Log:** Хранит данные для отката транзакций и обеспечивает **MVCC (Multi-Version Concurrency Control)**. Позволяет читать согласованные данные ("снимки"), даже если они изменяются параллельно другими транзакциями.
*   **Doublewrite Buffer:** Защищает от "разорванных страниц" (torn pages) при сбоях питания. Данные сначала пишутся в этот буфер, а затем в основной файл данных.
*   **Change Buffer:** Кэширует изменения вторичных индексов, когда страницы данных не находятся в Buffer Pool. В MariaDB 11.0+ этот механизм **удален** (MDEV-29694) из-за критических багов целостности данных, которые было крайне сложно воспроизвести.
*   **Индексация:** Основным типом индекса является B-Tree. Поддерживаются также Full-text, Spatial (R-Tree) и индексы на виртуальных колонках для JSON. Детальный разбор всех типов и продвинутых техник (Skip Scan, Invisible Indexes) находится в руководстве **[Индексы в MySQL](./indexing.md)**.
*   **Adaptive Hash Index:** Автоматически создает хэш-индексы для часто запрашиваемых страниц InnoDB Buffer Pool для ускорения поиска по B-Tree.

### Репликация и консистентность
В современной документации используется терминология **Источник (Source)** и **Реплика (Replica)**.

**Механизмы репликации:**
1.  **Binary Log (Binlog):** Источник записывает изменения. Типы: **Statement-based** (SQL-запросы), **Row-based** (изменения строк, дефолт в MySQL 8+ для точности), **Mixed**.
2.  **Relay Log:** Реплика копирует binlog источника в свой локальный журнал перед выполнением.
3.  **GTID (Global Transaction Identifier):** Уникальный ID каждой транзакции. Позволяет легко переключать реплики между источниками и гарантирует отсутствие дублей при восстановлении.

**Типы синхронизации:**
*   **Асинхронная:** Источник не ждет подтверждения от реплик. Максимальная производительность, риск потери данных при аварии.
*   **Полусинхронная (Semi-sync):** Источник ждет подтверждения получения данных (записи в relay log) хотя бы от одной реплики.
*   **Синхронная (Galera Cluster / Group Replication):** Транзакция подтверждается только после успешной записи на все узлы кластера (или большинство). Основа для **InnoDB Cluster**.

### Транзакции и безопасность
*   **XA Транзакции:** Распределенные транзакции, использующие протокол двухфазной фиксации (2PC) для согласованности между разными БД или ресурсами.
*   **Транзакционный DDL:** Начиная с MySQL 8.0, операции `ALTER TABLE`, `DROP TABLE` и др. стали атомарными.
*   **Access Control Lists (ACL):** Разграничение прав на основе хоста, пользователя и объектов (DB, Table, Column).
*   **Аутентификация:** В MySQL 8.4+ стандартом является `caching_sha2_password`. В версии 9.0+ `mysql_native_password` полностью удален.

### Работа с данными и NoSQL
*   **JSON в MySQL:** Бинарный формат хранения с автоматической валидацией и быстрым поиском по ключам.
*   **MySQL Document Store:** Возможность использовать MySQL как NoSQL-хранилище (через X Plugin). Позволяет работать с JSON-коллекциями без схем, используя CRUD-операции.
*   **Векторный поиск (Vector Search):** Доступен в MariaDB (начиная с 12.3 LTS) и MySQL Innovation (9.x).

---

## Основные ветки (Форки)

### Oracle MySQL Community Edition
Официальная версия, эталон реализации InnoDB.
- **Преимущества:** Поддержка MySQL Document Store, продвинутый **MySQL Shell** (SQL, JS, Python), нативный InnoDB Cluster.
- **Особенности:** **Query Cache** полностью удален в версии 8.0.

### Percona Server for MySQL
Оптимизированный форк для критических нагрузок.
- **Thread Pool:** Позволяет эффективно обрабатывать тысячи соединений (бесплатно, в Oracle — только в Enterprise).
- **Улучшенная диагностика:** Расширенное логирование медленных запросов, интеграция с Performance Schema и Percona Monitoring and Management (PMM).
- **Движок MyRocks:** Оптимизированное хранение на основе LSM-деревьев. Детальный разбор в **[Глубокое погружение в Storage Engines](./Operations/storage_engines_deep_dive.md)**.

### MariaDB
Полностью независимый форк с собственной стратегией.
- **Движки хранения:** Широкий выбор: **Aria** (безопасная замена MyISAM), **ColumnStore** (аналитика/OLAP), **Spider** (шардинг).
- **Инновации:** Системное версионирование таблиц (`AS OF SYSTEM TIME`), сохранена поддержка **Query Cache**.
- **Совместимость:** Бинарная совместимость с MySQL 8.0+ нарушена — миграция требует логического дампа.
- **Миграция:** Детальный чек-лист и процедура описаны в **[Миграция с MySQL на MariaDB](../MariaDB/Operations/migration_mysql_to_mariadb.md)**.

---

## Практические сценарии

### Сравнение производительности (бенчмарк 2026)

| Тест | MySQL 8.4 LTS | Percona 8.4 LTS | MariaDB 12.3 LTS |
| :--- | :---: | :---: | :---: |
| **OLTP Write (высокая нагрузка)** | Хорошо | **Отлично (Thread Pool)** | Удовлетворительно |
| **Аналитика (OLAP / Big Data)** | Средне | Средне | **Отлично (ColumnStore)** |
| **Сжатие (Space Saving)** | Средне | **Отлично (MyRocks)** | **Отлично (MyRocks)** |

### Диагностика производительности

*   **Анализ медленных запросов:**
    ```bash
    # Использование Percona Toolkit для анализа лога
    pt-query-digest /var/lib/mysql/mysql-slow.log
    ```
*   **Проверка блокировок (Performance Schema):**
    ```sql
    -- Вывод текущих ожиданий блокировок InnoDB
    SELECT * FROM sys.innodb_lock_waits;
    ```
*   **Мониторинг Buffer Pool:**
    ```sql
    -- Процент свободных страниц Buffer Pool
    SELECT FREE_BUFFERS/POOL_SIZE*100 AS free_pct FROM information_schema.INNODB_BUFFER_POOL_STATS;
    ```

### Критерии выбора форка
- **Oracle MySQL:** Если нужна стандартная экосистема, предсказуемость и поддержка NoSQL (Document Store).
- **Percona Server:** Если требуется Thread Pool, глубокий мониторинг (PMM) или нужно экономить место на диске (MyRocks) под высокой нагрузкой записи.
- **MariaDB:** Если нужны исторические таблицы, встроенная аналитика (ColumnStore) или векторный поиск в рамках LTS-релиза.

### Capacity Planning и размерение

**Цель:** определить ресурсы (RAM, CPU, disk IOPS, disk capacity) до развертывания, чтобы инстанс стабильно выдерживал целевую нагрузку с запасом.

**Подход:**
1.  Соберите baseline текущей или эталонной нагрузки: QPS, latency percentiles (p95, p99), размер БД, рост данных в месяц.
2.  Рассчитайте Buffer Pool: рекомендуется 70–80% от доступной RAM для выделенного инстанса. На инстансах <4 GB используйте консервативный коэффициент.
3.  Оцените disk IOPS: для OLTP-нагрузки считается, что 1 IOPS ≈ 1 QPS с учетом redundancy. Учтите RAID/mirroring overhead.
4.  Планируйте disk capacity с запасом 30–50% на индексы, временные таблицы, бинарные логи и рост данных.
5.  Учитывайте overhead операционной системы и других процессов на хосте.

**Инструменты:** `mysqldumpslow`, `pt-query-digest`, Performance Schema, логи медленных запросов.

### Жизненный цикл инстанса

**Развертывание:**
1.  Подготовка ОС: настройка sysctl (`vm.swappiness`, файловые дескрипторы), filesystem (XFS/ext4), timezone, NTP.
2.  Установка бинарей: пакетный менеджер или ручная установка. Для Oracle MySQL 8.4 LTS рекомендуется использовать официальные репозитории.
3.  Инициализация datadir: `mysqld --initialize` или `mysqld --initialize-insecure`.
4.  Первый запуск: настройка root-пароля, удаление анонимных пользователей, загрузка grants.

**Обновление (Upgrade):**
1.  **In-place:** остановка, замена бинарей, запуск `mysqld --upgrade=FORCE`. Требует совместимости формата данных.
2.  **Logical:** дамп через `mysqldump` или MySQL Shell `util.dumpInstance()`, установка нового сервера, восстановление. Позволяет менять ОС или архитектуру CPU.
3.  **Rolling (реплика):** обновление реплик по очереди, затем источника. Минимальный downtime.
4.  **Обязательно:** полный физический бэкап перед любым обновлением. Downgrade не поддерживается.

**Остановка и запуск:**
- **Graceful shutdown:** `mysqladmin shutdown` или `systemctl stop mysqld`. InnoDB выполняет checkpoint, закрывает страницы.
- **Fast shutdown:** `innodb_fast_shutdown=1` (дефолт). InnoDB только сбрасывает dirty pages из Buffer Pool, не выполняет полный purge/merge.
- **Crash recovery:** при нештатной остановке (`innodb_fast_shutdown=1`) InnoDB на следующем запуске применяет redo log и откатывает неподтвержденные транзакции через undo log.
- **Slow shutdown:** `innodb_fast_shutdown=0`. InnoDB выполняет полный purge удаленных строк и слияние change buffer перед остановкой. Требуется перед major upgrade или переносом данных.

### Мониторинг здоровья

**Ключевые метрики для SRE:**
- **Buffer Pool hit rate:** целевое значение >99%. `SELECT (1 - (SELECT COUNT FROM information_schema.INNODB_METRICS WHERE NAME='buffer_pool_reads') / (SELECT COUNT FROM information_schema.INNODB_METRICS WHERE NAME='buffer_pool_read_requests')) * 100;`
- **InnoDB row lock time:** среднее время ожидания блокировок строк.
- **Connections:** активные vs. максимальные (`Max_used_connections`). Для Thread Pool: `threadpool_threads_running`.
- **QPS / TPS:** распределение по времени, сравнение с baseline.
- **Disk usage:** рост данных, заполнение tablespaces, количество открытых файловых дескрипторов.
- **Replication lag:** `Seconds_Behind_Source` для асинхронной, задержка полусинхронной репликации.
- **Slow queries:** счетчик и распределение по времени выполнения.

**Инструменты:** Performance Schema, sys schema, `SHOW GLOBAL STATUS`, `SHOW ENGINE INNODB STATUS`, Percona PMM, Prometheus + mysqld_exporter.

### Поиск и устранение неисправностей

**Типичные инциденты:**
1.  **Высокая CPU:** медленные запросы, отсутствующие индексы, переключение на временные таблицы на диске.
   - Диагностика: `pt-query-digest`, `EXPLAIN ANALYZE`, `SHOW PROCESSLIST`.
   - Решение: добавить индекс, оптимизировать запрос, ограничить `max_execution_time`.
2.  **Высокая latency / таймауты:** переполнение Buffer Pool, contention на метаданных (MDL), долгие транзакции.
   - Диагностика: `sys.innodb_lock_waits`, `performance_schema.events_waits_summary_by_thread_by_event_name`.
   - Решение: тюнинг `innodb_lock_wait_timeout`, уменьшение размера транзакций, разбиение на части.
3.  **Отказ запуска (crash):** проверка логов `/var/log/mysqld.log`, ошибки инициализации InnoDB, недостаток места на диске, права доступа.
   - Решение: исправление ошибки конфигурации, восстановление из бэкапа при повреждении данных.
4.  **Replication broken:** ошибки применения binlog (дублирование ключей, отсутствие таблиц), разрыв GTID.
   - Диагностика: `SHOW REPLICA STATUS`, `SHOW ENGINE INNODB STATUS`, `pt-table-checksum`.
   - Решение: `RESET REPLICA ALL`, переконфигурация, `SET GLOBAL sql_slave_skip_counter` при необходимости.

### Граничные случаи и ограничения

1.  **Ограничения Online DDL:** операции `ALTER TABLE` с `ALGORITHM=INPLACE, LOCK=NONE` поддерживают только ограниченный набор изменений. Перестрока индексов на больших таблицах может вызывать contention на MDL.
2.  **Влияние репликации на DDL:** DDL на источнике реплицируется на реплики. Сложные операции могут вызвать задержку репликации или ошибки на репликах с другими storage engines.
3.  **Влияние индексов на бэкапы:** физические бэкапы (XtraBackup) копируют все страницы данных, включая неиспользуемые индексы. Избыточные индексы увеличивают размер бэкапа и время восстановления.
4.  **Ограничения функциональных индексов:** индексы на виртуальных колонках не могут использоваться для покрывающих индексов (covering index) в некоторых версиях.
5.  **Ограничения Multi-Valued Indexes:** поддерживаются только для JSON-массивов, не работают с обычными столбцами.
6.  **Ограничения Spatial Indexes:** требуют SRID, не поддерживают все пространственные predicates.
7.  **Ограничения Skip Scan:** эффективен только при высокой кардинальности Leading Column. При низкой селективности degenerates в full scan.
8.  **Фрагментация при массовых операциях:** массовые `DELETE` без `TRUNCATE` оставляют "мертвые" строки, вызывая фрагментацию индексов и таблиц. Требуется `OPTIMIZE TABLE` или `ALTER TABLE ... ENGINE=InnoDB`.

### Best Practices

1.  **Baseline before changing:** Record QPS, latency percentiles (p95, p99), connections, and Buffer Pool hit rate before any schema change, upgrade, or configuration modification.
2.  **Validate backups:** Follow the 3-2-1 backup rule (3 copies, 2 media types, 1 offsite) and test restores regularly. RTO/RPO must be validated in drills, not assumed. Details: **[Резервное копирование и восстановление](./backup_and_recovery/overview.md)**.
3.  **Stage changes first:** Test schema changes, version upgrades, and parameter changes on a production-like replica before applying to primary.
4.  **Prefer rolling upgrades:** For replication topologies, upgrade replicas before the source. This minimizes downtime and provides instant rollback. Details: **[Обслуживание и обновления MySQL](./maintenance-and-upgrades.md)**.
5.  **SLO-based alerting:** Alert on error budget burn and baseline deviation, not just static thresholds. This reduces noise and catches gradual degradation early. Details: **[Мониторинг MySQL](./monitoring.md)**.
6.  **Least privilege:** Grant minimum required privileges. Separate application accounts from admin accounts. Audit grants and rotate passwords on a schedule. Details: **[Управление ролями и RBAC](./role_management.md)**.
7.  **Document topology and runbooks:** Keep replication topology diagrams, failover procedures, and escalation paths current. Runbooks must cover crash recovery and replica re-initialization.
8.  **Maintenance windows:** Schedule writes-heavy operations (`OPTIMIZE TABLE`, index rebuild, major upgrades) during low-traffic periods.

---

## Дополнительная информация

### Утилиты и инструменты
- **Обслуживание и обновления:** Детальное руководство по **[Обслуживанию и обновлениям MySQL](./maintenance-and-upgrades.md)** (дефрагментация, партиционирование, Major Upgrade 8.4 LTS с MySQL Shell).
- **Безопасность и TDE:** Настройка шифрования данных на диске, SSL и аудита в **[Безопасность MySQL](./security.md)**.
- **Резервное копирование и восстановление:** Полное руководство по методам (Logical/Physical), инструментам (XtraBackup, MySQL Shell) и сценариям (PITR) находится в **[Резервное копирование и восстановление в MySQL](./backup_and_recovery/overview.md)**.
- **Блокировки и дедлоки:** Классификация (MDL, Record, Gap, Next-Key) и руководство по анализу взаимоблокировок через `SHOW ENGINE INNODB STATUS` описаны в **[Блокировки и взаимоблокировки в MySQL](./locking_and_deadlocks.md)**.
- **Прокси и балансировка:** 
  - **[ProxySQL](./ProxySQL/proxysql_overview.md):** Универсальный L7-прокси с интеллектуальной маршрутизацией, кэшированием и пулингом.
  - **[Orchestrator](./orchestrator.md):** Автоматизация failover и управление топологией репликации.
  - **[MaxScale (MariaDB)](../MariaDB/MaxScale/maxscale_overview.md):** Оптимизированный прокси для MariaDB и Galera Cluster.
- **Администрирование:** **Percona Toolkit** — незаменимый набор скриптов для проверки консистентности (`pt-table-checksum`) и онлайн-смены схем (`pt-online-schema-change`).

### См. также
- **[Установка MySQL](./installation.md)** — практические шаги развертывания.
- **[Безопасность MySQL](./security.md)** — TDE, SSL и Аудит (SSoT).
- **[Механизмы оптимизатора](./optimizer_mechanisms.md)** — ICP, MRR и Batched Key Access.
- **[Обслуживание и обновления MySQL](./maintenance-and-upgrades.md)** — глубокий тюнинг и миграции.
- **[Секционирование данных (Теория)](../Concepts/partitioning.md)** — общие принципы.
- **[Глубокое погружение в Storage Engines](./Operations/storage_engines_deep_dive.md)** — MyISAM, MyRocks, Memory и Archive.
- **[Конфигурация MySQL](./configuration.md)** — тюнинг параметров.
- **[Оптимизация запросов: EXPLAIN и Hints](./Operations/explain_and_optimization.md)** — чтение планов выполнения и подсказки оптимизатору.
- **[Управление ролями и RBAC](./role_management.md)** — разграничение прав в MySQL 8.0+.
- **[Orchestrator: Failover и топология](./orchestrator.md)** — автоматизация высокой доступности.
- **[ProxySQL: L7-балансировка](./ProxySQL/proxysql_overview.md)** — разделение чтения/записи и кэширование.
- **[Мониторинг MySQL](./monitoring.md)** — метрики и алертинг.
- **[Репликация в MySQL: Обзор](./replication/overview.md)** — механизмы репликации и GTID.
- **[Резервное копирование и восстановление](./backup_and_recovery/overview.md)** — методы, инструменты и PITR.
- **[Блокировки и Deadlocks](./locking_and_deadlocks.md)** — MDL, Next-Key, диагностика взаимоблокировок.
- **[Индексы в MySQL](./indexing.md)** — типы индексов, проектирование, эксплуатация.
