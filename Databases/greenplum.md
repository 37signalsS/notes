# Greenplum: Массивно-параллельный PostgreSQL

**Актуально для:** VMware Tanzu Greenplum 7.5.x (ядро PostgreSQL 12)

Массивно-параллельная СУБД для аналитических хранилищ. Общая теория распределенных систем и MPP описана в разделе **[Шардирование и MPP](./Concepts/sharding.md)**.

## Определения

**Greenplum** — это СУБД с массивно-параллельной архитектурой (MPP — Massively Parallel Processing), построенная на базе PostgreSQL. Она предназначена для создания корпоративных хранилищ данных (DWH) и выполнения сверхсложных аналитических запросов (OLAP) на петабайтных объемах данных.

Ключевая идея — **разбиение запроса на множество параллельных задач**, которые выполняются одновременно на десятках или сотнях серверов.

**Текущее состояние:** актуальная линейка — VMware Tanzu Greenplum 7.5.x (Greenplum 7.0 вышел 28.09.2023, ядро — PostgreSQL 12; в сборке 7.5.1 используется PostgreSQL 12.22). Сопутствующие компоненты выпускаются и поддерживаются отдельно: Greenplum Command Center 7.5.x и Greenplum Backup and Restore 1.33.x. Greenplum 7 привнес поддержку декларативного (нативного PostgreSQL) синтаксиса партиционирования, сгенерированные колонки, row-level security, расширенный набор типов индексов (btree, hash, bitmap, BRIN, геопространственные, текстовые) и федеративный доступ к данным через PXF на базе FDW API PostgreSQL 12. Хранимые процедуры (`CREATE PROCEDURE`) появились ранее — в Greenplum 6 (ядро PostgreSQL 11).

## Основные концепции

### Архитектура Shared-Nothing («Без разделяемых ресурсов»)

В отличие от систем с общими дисками, в Greenplum каждый узел обладает собственной памятью, CPU и дисковым пространством. Это устраняет единую точку конкуренции за ввод-вывод и позволяет линейно масштабировать производительность.

**Компоненты кластера:**

- **Координатор (Coordinator Host):** (ранее Master; в GP7 терминология изменена) «Мозг» кластера. Принимает SQL-запросы, строит план выполнения и распределяет его между сегментами. Хранит только метаданные (системный каталог).
- **Резервный координатор (Standby Coordinator):** горячий резерв координатора (см. раздел «Отказоустойчивость»).
- **Сегмент-хосты (Segment Hosts):** серверы, выполняющие основную работу. На каждом хосте работают несколько **сегментов** (инстансов Postgres), каждый из которых владеет своей частью данных.
- **Interconnect:** сетевой коммутационный слой. Обеспечивает передачу промежуточных результатов между сегментами.

**Interconnect — важная деталь эксплуатации:** по умолчанию используется **UDP с управлением потоком (UDPIFC — UDP with Flow Control)**. Greenplum выполняет собственную проверку пакетов сверх UDP, поэтому надёжность эквивалентна TCP, а масштабируемость и производительность выше. При переключении interconnect на TCP возникает ограничение масштабируемости — **не более 1000 сегмент-инстансов**; с UDPIFC это ограничение не применимо.

**Сетевые порты кластера:**

| Сервис | Протокол/порт | Назначение |
| :--- | :--- | :--- |
| Клиентские подключения к координатору | TCP 5432 (libpq) | Порт SQL-доступа, настраивается в `postgresql.conf` |
| Interconnect | UDP 1025–65535 (динамически) | Передача кортежей между сегментами при выполнении запросов |
| Репликация standby-координатора | TCP 1025–65535 (`gpsyncmaster`) | Репликация журнала координатора на standby |
| PXF | TCP 5888 | Java-сервис Platform Extension Framework |
| gpfdist / gpload | TCP 8080 (HTTP) / 9000 (HTTPS) | Параллельная загрузка файлов |

### Типы хранения и сжатие

Greenplum позволяет гибко настраивать формат хранения под конкретный тип нагрузки:

1.  **Heap Storage:** классический строковый формат PostgreSQL. Лучший выбор для таблиц с частыми `UPDATE/DELETE`, справочников и таблиц с частыми обновлениями индексов.
2.  **Append-Optimized (AO):** структура, оптимизированная для массовой загрузки (`COPY`, `INSERT`) и сценариев «записал один раз — читаешь много». AO-таблицы используют модель управления конкурентным доступом, отличную от MVCC free space map: удалённые строки отслеживаются в auxiliary visibility bitmap, а место возвращается только операцией `VACUUM` (compaction).
3.  **Column-Oriented (AOCO):** колоночное хранение. Каждая колонка хранится в отдельном файле, что радикально снижает I/O в OLAP-запросах, читающих подмножество колонок.
4.  **Polymorphic:** таблица, объединяющая разные типы хранения (heap/AO/AOCO) в одной таблице.

**Сжатие (только для AO-таблиц):** поддерживаются алгоритмы **ZSTD** (уровни 1–19; рекомендуется), **ZLIB** (1–9) и **RLE_TYPE** (Run-Length Encoding, только для колоночных таблиц; уровни 1–4, в GP7 также 5–6 — комбинации RLE+ZLIB/RLE+ZSTD; для RLE+ZSTD документация рекомендует уровни 5 и выше). Для колонок BIGINT/INTEGER/DATE/TIME/TIMESTAMP применяется дельта-сжатие в комбинации с RLE. **QuickLZ deprecated** и будет удалён в следующем мажорном релизе; в open-source версии он недоступен. Сжатие задаётся на уровне таблицы (`WITH (compresstype=...)`) или на уровне колонки (`ENCODING (compresstype=...)`).

### Отказоустойчивость (High Availability)

- **Standby Coordinator:** резервный узел координатора. Создаётся утилитой `gpinitstandby`, реплицирует журнал координатора через `gpsyncmaster`. При сбое координатора повышение выполняется вручную утилитой `gpactivatestandby` (автоматизация — через скрипты/системы мониторинга).
- **Зеркалирование сегментов (Segment Mirroring):** для каждого первичного сегмента (Primary) создаётся зеркальная копия (Mirror) на другом хосте. Репликация **синхронная**: фиксация транзакции ожидает записи на mirror. Зеркала можно добавить после инициализации кластера (`gpaddmirrors`).
- **FTS (Fault Tolerance Service):** фоновый процесс на координаторе, постоянно опрашивающий сегменты. Если Primary-сегмент недоступен, FTS автоматически активирует Mirror.
- **Восстановление после сбоя:** после отказа сегмента кластер работает на mirror'ах; для возврата к штатной конфигурации используется `gprecoverseg` (восстанавливает failed-сегмент, при необходимости на другой хост).

### Оптимизатор GPORCA

**GPORCA** — современный расширяемый планировщик запросов на основе стоимости, созданный специально для MPP.
- **Масштабируемость:** эффективно обрабатывает запросы с сотнями JOIN'ов и сложными подзапросами.
- **Многоэтапное планирование:** умеет строить планы с перемещением данных (Redistribution) и дублированием (Broadcast) для минимизации сетевого трафика.
- **Развитие в 7.5:** покрытие GPORCA расширено на более широкий диапазон запросов; в 7.5 также ускорено выполнение запросов на AO-таблицах (до 2× за счёт TupleTableSlot-оптимизаций) и добавлены pure index scans на сжатых AO-таблицах (без bitmap-сканов).

### Распределение данных (Distribution)

Greenplum комбинирует два уровня распределения данных:

1. **Дистрибуция (Distribution):** строки таблиц шардируются по сегментам.
    - `DISTRIBUTED BY (key)` — по хешу колонки. Критично для локальных JOIN'ов по этому ключу.
    - `DISTRIBUTED RANDOMLY` — случайное равномерное распределение. Используется, если нет явного ключа дистрибуции.
    - `DISTRIBUTED REPLICATED` — копия таблицы на каждом сегменте. Идеально для небольших справочников.
2. **Партиционирование (Partitioning):** логическое деление внутри каждого сегмента (например, по датам). Позволяет использовать **Partition Pruning** (исключение партиций) для ускорения выборок.

**GP7 поддерживает два синтаксиса партиционирования:**
- **Декларативный (modern)** — производный от PostgreSQL declarative partitioning: партиции являются полноценными таблицами, поддерживаются hash-стратегия, multi-column range-ключи, выражения в ключе партиционирования, иерархии с разными стратегиями у потомков, допустимо нулевое число партиций.
- **Классический (classic)** — синтаксис GP6: range/list, sub-partition templates, обязательное наличие хотя бы одной партиции, данные только в leaf-партициях.

## Практические сценарии

### Области применения

- **Корпоративные хранилища данных (DWH):** централизованный сбор и анализ данных всей организации.
- **Бизнес-аналитика (BI) и отчетность:** построение витрин данных и выполнение тяжелых агрегирующих запросов.
- **Встроенная аналитика:** статистические и аналитические функции на SQL внутри БД (Apache MADlib).
- **Сложные ETL/ELT процессы:** пакетная обработка и преобразование огромных массивов данных (PXF, gpfdist, gpload), а также потоковая загрузка (GPSS — Kafka/RabbitMQ).
- **Геопространственная аналитика:** PostGIS 3; в 7.5 добавлены расширения H3, pgPointCloud, 3DCityDB, pgRouting, TIGER geocoding.

### Антипаттерны

- **OLTP нагрузки:** частые короткие операции записи/обновления отдельных строк.
- **Низкая задержка (Latency):** система оптимизирована для пропускной способности (throughput), а не для мгновенного отклика одиночного запроса.
- **Малые данные:** при объемах <1 ТБ стандартный PostgreSQL обычно проще и быстрее.

### Предварительные требования

**Поддерживаемые ОС (GP7):** RHEL 8.7+/9.x, Oracle Linux 8.7+/9.x (RHCK), Rocky Linux 8.7+/9.x, Amazon Linux 2023.7+. Виртуализация: VMware vSphere (ESXi ≥6.7 U3, vCenter ≥7.0 U3).

**Программные зависимости** (устанавливаются автоматически с RPM): `libcgroup-tools`, `libzstd`, `openssl` (≥3.4.0 на RHEL 9/Rocky 9/Amazon Linux 2023), `python3` (для PL/Python — python3.11).

**Требования к окружению:**
- Greenplum работает **только от непривилегированного пользователя** (по умолчанию `gpadmin`), не от root.
- Passwordless SSH для `gpadmin` между всеми хостами кластера.
- Все хосты прописаны в `/etc/hosts`; синхронизация времени (NTP) на всех узлах.
- Firewalld отключен или настроен (порты из таблицы выше); SELinux в Enforcing работает в контексте Unconfined.
- **Осторожно:** в RHEL 8.5/8.6 есть баг XFS (I/O freezes), исправленный в 8.7. ПО endpoint-security может влиять на производительность и стабильность.
- **Transparent Huge Pages (THP)** не рекомендуются для баз данных (Red Hat); при проблемах с задержками отключить: `echo never > /sys/kernel/mm/transparent_hugepage/enabled` или `transparent_hugepage=never` в параметрах GRUB.

### Установка и базовая настройка

#### 1. Подготовка ОС (Bare Metal / VM)

Greenplum требует специфических настроек ядра. Значения `kernel.shmall`/`kernel.shmmax` рассчитываются как **половина физической памяти** хоста:

```bash
# /etc/sysctl.d/10-gpdb.conf
kernel.shmmni = 4096
kernel.sem = 250 2048000 200 8192
kernel.sysrq = 1
kernel.core_uses_pid = 1
kernel.msgmnb = 65536
vm.overcommit_memory = 2
vm.overcommit_ratio = 95
net.ipv4.ip_local_port_range = 10000 65535

# Половина физической памяти (пример для хоста с 1583 ГБ RAM):
kernel.shmall = 197951838
kernel.shmmax = 810810728448

# Для хостов с RAM > 64 ГБ:
vm.dirty_background_ratio = 0
vm.dirty_ratio = 0
# vm.min_free_kbytes = 3% от RAM
```

Расчёт значений под конкретный хост:
```bash
# → kernel.shmall = _PHYS_PAGES / 2; kernel.shmmax = (_PHYS_PAGES / 2) * PAGE_SIZE
getconf _PHYS_PAGES; getconf PAGE_SIZE
awk 'BEGIN {OFMT = "%.0f";} /MemTotal/ {print "vm.min_free_kbytes =", $2 * .03;}' /proc/meminfo >> /etc/sysctl.d/10-gpdb.conf
sysctl --system
```

#### 2. Установка пакета на все хосты

```bash
# RPM устанавливается на координатор, standby-координатор и каждый сегмент-хост
sudo yum install ./greenplum-db-<version>-rhel8-x86_64.rpm
# → установка в /usr/local/greenplum-db-<version>
```

#### 3. Инициализация кластера

Используется утилита `gpinitsystem` с конфигурационным файлом топологии (координатор, каталоги данных, базовые порты, число сегментов на хост, конфигурация зеркал) и файлом списка сегмент-хостов:

```bash
gpinitsystem -c gpconfigs/gpinitsystem_config -h gpconfigs/hostfile_gpinitsystem
# → 20240229:11:39:11:001290 gpinitsystem:rocky9-gp7-master:gpadmin-[INFO]:-Reading Greenplum configuration file gpconfigs/gpinitsystem_config
# → ...
# → Continue with Greenplum creation Yy|Nn (default=N):
```

Создание резервного координатора и добавление зеркал (если не заданы в конфиге):
```bash
gpinitstandby -s standby-hostname    # → создание standby-координатора
gpaddmirrors                          # → добавление mirror-сегментов (опции: -o файл, -p сдвиг портов, -m файл расположений, -s политика spread)
```

#### 4. Валидация

```bash
gpstart                              # → запуск кластера
psql -c "SELECT version();"
# → PostgreSQL 12.22 (Greenplum Database 7.5.1 build commit:...) on x86_64-pc-linux-gnu
gpstate -s                           # → детальное состояние кластера
gpstate -m                           # → список mirror-сегментов и их роли
gpcheckperf                          # → проверка производительности сети и дисков хостов
```

### Развертывание в Kubernetes (Greenplum Operator)

Текущий оператор (Tanzu Greenplum on Kubernetes) использует CRD `greenplum.data.tanzu.vmware.com/v1` (старый API `greenplum.pivotal.io/v1` с `masterHostCount`/`segmentsHostCount` устарел). Развертывание состоит из CR `GreenplumVersion` (версия и образы) и CR `GreenplumCluster`:

```yaml
# 1. GreenplumVersion — описывает версию БД и образы
apiVersion: greenplum.data.tanzu.vmware.com/v1
kind: GreenplumVersion
metadata:
  name: greenplumversion-7.5.5
spec:
  dbVersion: 7.5.5
  image: repository.example.com/greenplum/gp-instance:7.5.5
  operatorVersion: 1.0.1
  extensions:
    - name: postgis
      version: 3.3.2
    - name: greenplum_backup_restore
      version: 1.31.0
---
# 2. GreenplumCluster — сам кластер
apiVersion: greenplum.data.tanzu.vmware.com/v1
kind: GreenplumCluster
metadata:
  name: gp-prod
  namespace: default
spec:
  version: greenplumversion-7.5.5
  imagePullSecrets:
    - name: regcred
  coordinator:
    storageClassName: premium-rwo
    storage: 20Gi
  segments:
    count: 4
    storageClassName: premium-rwo
    storage: 100Gi
  service:
    type: NodePort
```

```bash
helm install gp-operator . -n ${NAMESPACE}   # → установка оператора (Cert Manager + webhooks входят в комплект)
kubectl apply -f gpversion7.5.5.yaml && kubectl apply -f gp-minimal.yaml
kubectl get greenplumclusters                # → проверка статуса кластера
```

Дополнительные CR: `GreenplumCommandCenter` (GUI-мониторинг), `GreenplumBackup`/`GreenplumRestore` (бэкапы). **Ограничения оператора:** resource groups не поддерживаются; изменение числа сегментов (масштабирование вверх/вниз) не поддерживается.

### Примеры создания таблиц

```sql
-- Распределённая таблица с декларативным партиционированием и колоночным хранением (ZSTD)
CREATE TABLE sales (
    sale_id SERIAL,
    sale_date DATE,
    product_id INT,
    customer_id INT,
    amount NUMERIC(10,2)
)
WITH (appendonly=true, orientation=column, compresstype=zstd, compresslevel=3)
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
(
    PARTITION p2025 VALUES LESS THAN ('2026-01-01'),
    PARTITION p2026 VALUES LESS THAN ('2027-01-01')
);

-- Тот же классический синтаксис (GP6, сохранён в GP7):
-- PARTITION BY RANGE (sale_date)
-- ( PARTITION p2025 START ('2025-01-01') END ('2026-01-01'),
--   PARTITION p2026 START ('2026-01-01') END ('2027-01-01') );

-- Таблица-справочник (реплицируется на все сегменты для быстрых JOIN)
CREATE TABLE products (
    product_id INT PRIMARY KEY,
    product_name TEXT
) DISTRIBUTED REPLICATED;

-- Колоночное сжатие на уровне отдельной колонки
-- ALTER TABLE sales ALTER COLUMN amount ENCODING (compresstype=zstd, compresslevel=3);
```

### Параллельная загрузка данных

```bash
# Запуск gpfdist на сервере-источнике для параллельного чтения всеми сегментами
gpfdist -d /data/csv_files -p 8081 &
# → gpfdist -d /data/csv_files -p 8081 → serving HTTP on port 8081
```

```sql
-- Создание внешней таблицы для доступа к данным
CREATE EXTERNAL TABLE ext_sales (LIKE sales)
LOCATION ('gpfdist://source-host:8081/*.csv')
FORMAT 'CSV' (HEADER);

-- Быстрая параллельная вставка
INSERT INTO sales SELECT * FROM ext_sales;
-- → INSERT 0 <N>

-- Обязательно после загрузки: обновление статистики для планировщика
ANALYZE sales;
-- → ANALYZE
```

Альтернативы: `gpload` (YAML-конфигурация, автоматически поднимает нужное число gpfdist), **PXF** (внешние таблицы `LOCATION ('pxf://...')` с профилями `s3:text`, `hdfs:text` и др. — доступ к HDFS, S3-совместимым объектным хранилищам, JDBC-источникам и другим инстансам Greenplum), **GPSS** (потоковая загрузка из Apache Kafka и RabbitMQ; в 7.5 — scale-out архитектура).

### Управление ресурсами (Resource Groups)

Resource Groups изолируют нагрузку групп пользователей: лимиты на параллельные транзакции, память, CPU и дисковый I/O. GP7 поддерживает **cgroups v1 и v2**, но параметр `IO_LIMIT` (throttling дискового I/O) доступен **только на cgroups v2**.

```sql
-- Группа: 20 параллельных транзакций, 1500 МБ памяти, 25% CPU, лимиты I/O на tablespace pg_default
CREATE RESOURCE GROUP rgroup2 WITH (
  CONCURRENCY=20,
  MEMORY_QUOTA=1500,
  CPU_MAX_PERCENT=25,
  IO_LIMIT='pg_default: wbps=1000, rbps=1000, wiops=100, riops=100'
);
-- → CREATE RESOURCE GROUP
```

При нехватке памяти запросы spill to disk; при достижении `gp_workfile_limit_files_per_query` генерируется OOM-ошибка. Внимание: лимиты IO_LIMIT на tablespace, разделяющем диск с `pg_wal`, могут замедлить весь кластер.

### Обслуживание и мониторинг

**Ключевые утилиты:**

| Утилита | Назначение |
| :--- | :--- |
| `gpstart` / `gpstop` | Запуск / остановка кластера (`gpstop -r` — перезапуск, `gpstop -u` — перезагрузка конфигурации) |
| `gpstate` | Состояние кластера: `-e` — сегменты с проблемами зеркалирования, `-m` — список mirror'ов и их роли, `-c` — маппинг primary→mirror, `-p` — порты, `-s` — детальный статус, `-Q` — быстрый статус из каталога, `-x` — статус расширения кластера |
| `gpconfig` | Изменение параметров конфигурации (GUC) сразу на всем кластере |
| `gpcheckcat` | Проверка целостности системного каталога (перед обновлениями) |
| `gpcheckperf` | Проверка производительности сети и дисков |
| `gplogfilter` | Фильтрация логов координатора и сегментов |
| `analyzedb` | Параллельный ANALYZE по базе |
| `gpaddmirrors` / `gprecoverseg` / `gpexpand` | Добавление зеркал / восстановление failed-сегментов / расширение кластера |

Пример диагностики зеркалирования:
```bash
gpstate -m
# → --Current GPDB mirror list and status
# →    Mirror    Datadir                Port    Status    Data Status
# →    sdw2      /data1/mirror/gpseg0   11000   Passive   Synchronized
```

**VACUUM и ANALYZE:**
- `VACUUM` для Heap-таблиц — освобождение места в free space map. Для AO-таблиц — compaction (перезапись файлов без «скрытых» строк); выполняется на каждом сегменте только если доля скрытых строк превышает порог `gp_appendonly_compaction_threshold` (по умолчанию 10 = 10%). Отключение compaction: `gp_appendonly_compaction = no`.
- `ANALYZE` критически важен: GPORCA строит планы на основе статистики. В 7.5 ANALYZE автоматически пропускает таблицы без изменений.
- `VACUUM FULL` переписывает таблицу целиком и требует **ACCESS EXCLUSIVE** lock — только в окно обслуживания.

**Мониторинг через системные каталоги:**
```sql
-- Состояние сегментов (status='d' — недоступны)
SELECT dbid, content, role, preferred_role, mode, status, port, hostname, datadir
FROM gp_segment_configuration WHERE status = 'd';
-- → строки для down-сегментов

-- История изменений конфигурации кластера (роли, статусы, таймстемпы)
SELECT * FROM gp_configuration_history ORDER BY time DESC LIMIT 10;

-- Размеры объектов и bloat (схема gp_toolkit)
SELECT * FROM gp_toolkit.__gp_aovisimap_compaction_info(47372);
-- → content | datafile | compaction_possible | hidden_tupcount | total_tupcount | percent_hidden
```

**Greenplum Command Center (GPCC):** веб-интерфейс мониторинга запросов и ресурсов; активно развивается (7.5.x, в 7.5.0 добавлен OIDC SSO).

### Резервное копирование и восстановление

`gpbackup`/`gprestore` — рекомендуемые параллельные утилиты (отдельная загрузка: VMware Greenplum Backup and Restore, актуальная линейка 1.33.x). `gpbackup` использует ACCESS SHARE locks на уровне таблиц, поэтому DML на таблицах вне бэкап-сета допустима во время бэкапа. Инкрементальные бэкапы поддерживаются для AO-таблиц:

```bash
# Полный бэкап (база инкрементальной цепочки)
gpbackup --dbname sales --backup-dir /backup/gp --leaf-partition-data

# Инкрементальный бэкап поверх полного
gpbackup --dbname sales --incremental --backup-dir /backup/gp --leaf-partition-data

# Восстановление из полного набора
gprestore --dbname sales --backup-dir /backup/gp --incremental
```

`pg_dump`/`pg_dumpall` — непараллельные, все данные проходят через координатор; только для частных случаев.

## Поиск и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Сегмент недоступен, запросы замедлены | Отказ хоста/диска/сети; mirror принял роль primary | `gpstate -e`, запрос `gp_segment_configuration WHERE status='d'`; восстановление `gprecoverseg` |
| `gpstate` показывает «Segments with Primary and Mirror Roles Switched» | Роли primary/mirror переключены после сбоя — кластер в дисбалансе | `gprecoverseg` для возврата сегментов в preferred role |
| `gpstate` сообщает «Unknown — unable to load segment status» | Не работает passwordless SSH с координатора на сегмент-хосты | Настроить SSH-ключи `gpadmin` |
| `gpinitsystem` FATAL «Failed to complete obtain psql count Master gp_segment_configuration» | systemd очищает IPC-объекты при logout пользователя (`RemoveIPC=yes` в `/etc/systemd/logind.conf` по умолчанию) | Установить `RemoveIPC=no` в `/etc/systemd/logind.conf`, перезагрузить хосты |
| Linux OOM-killer убивает запросы (GP7) | GP7 не устанавливает лимиты памяти в cgroups (только отслеживает); лимиты могли остаться от GP6 или заданы вручную | Проверить `cgget -g memory:gpdb` и `/etc/cgconfig.conf`; очистить лимиты, перезагрузить хосты |
| Ошибки interconnect | Сбой NIC/свитча/DNS — имена хостов не резолвятся | `gpcheckperf`, проверка `/etc/hosts` и DNS |
| Деградация производительности, рост места | Диски сегмент-хостов заполнены >70%, bloat | `VACUUM`/`ANALYZE`, размеры объектов через `gp_toolkit` |
| Блокировки при обслуживании | `VACUUM FULL` требует ACCESS EXCLUSIVE | Выполнять только в окно обслуживания; альтернатива — `CREATE TABLE AS` + swap |

## Лучшие практики

- **Ключ дистрибуции** выбирайте по ключу JOIN'ов крупных фактов — это даёт локальные JOIN'ы без перемещения данных по сети. Проверяйте перекос: `SELECT gp_segment_id, count(*) FROM sales GROUP BY 1 ORDER BY 2 DESC;`
- **ANALYZE после каждой загрузки** (`analyzedb` для параллельного выполнения) — без статистики GPORCA строит плохие планы.
- **Регулярный VACUUM**: частота зависит от частоты UPDATE/DELETE; для AO-таблиц — контроль `gp_toolkit.__gp_aovisimap_compaction_info()`.
- **Обслуживание (загрузки, VACUUM ANALYZE, бэкапы) — в нерабочее время**, не конкурируя с пользовательскими запросами.
- **gpcheckcat перед обновлениями**; обновление 6→7 — утилитой `gpupgrade` (отдельный пакет Greenplum Upgrade). Учтите изменения GP7: `master`→`coordinator`, `pg_xlog`→`pg_wal`, `pg_clog`→`pg_xact`; удалён `checkpoint_segments` (используйте `min_wal_size`/`max_wal_size`); autovacuum включён по умолчанию; deprecated `gpreload` (вместо него `ALTER TABLE...REPACK BY`).
- **Инкрементальные бэкапы** gpbackup всегда создавайте с `--leaf-partition-data`; вся цепочка (полный + инкрементальные) должна использовать согласованные опции.
- **Диски сегмент-хостов не заполнять более чем на 70%** — Greenplum нужен запас для runtime-обработки.
- **Очистка окружения** после тестов: `gpstop`, `sudo yum remove greenplum-db`, удаление каталогов данных (`$MASTER_DATA_DIRECTORY`, каталогов сегментов).

## Дополнительная информация

### Сравнение аналитических решений

| Система | Архитектура | Основное назначение | JOIN'ы |
| :--- | :--- | :--- | :--- |
| **Greenplum** | MPP (Shared-Nothing) | Сложная аналитика, DWH | Отлично (Redistribution/Broadcast) |
| **[ClickHouse](./ClickHouse/clickhouse.md)** | Колоночная | Сверхбыстрые агрегаты, логи | Ограниченно (предпочтительны flat-tables) |
| **[PostgreSQL](./PostgreSQL/overview.md)** | Single Node / Replication | OLTP, малые DWH | Локальные, высокая нагрузка при росте |

### Экосистема и инструменты

- **Apache MADlib:** встроенная аналитика и статистические функции на SQL.
- **PXF (Platform Extension Framework):** федеративный доступ к HDFS, S3-совместимым объектным хранилищам, JDBC-источникам и другим инстансам Greenplum (FDW API PostgreSQL 12).
- **gpbackup / gprestore:** параллельное резервное копирование с инкрементальными бэкапами AO-таблиц (отдельная загрузка, линейка 1.33.x).
- **Greenplum Command Center (GPCC):** графический интерфейс мониторинга запросов и ресурсов (7.5.x, OIDC SSO).
- **Greenplum Streaming Server (GPSS):** потоковая загрузка из Apache Kafka и RabbitMQ (в 7.5 — scale-out архитектура).
- **Greenplum Text:** полнотекстовый поиск на базе Apache Solr.
- **PostGIS 3** и геопространственные расширения (H3, pgPointCloud, 3DCityDB, pgRouting, TIGER — в 7.5).
- **Greenplum Clients:** пакет клиентских утилит (`psql`, `gpfdist` и др.) для клиентских машин.

### Требования к ресурсам (Рекомендации)

| Компонент | Минимум | Рекомендуется для Prod |
| :--- | :--- | :--- |
| **CPU** | 8 ядер на сегмент-хост | 32+ ядер на сегмент-хост (высокая частота) |
| **RAM** | 32 ГБ на сегмент-хост | 128+ ГБ (из расчета ~8 ГБ на сегмент) |
| **Диски** | SSD (SATA/SAS) | NVMe SSD в RAID 10 |
| **Сеть** | 10 Гбит/с | 25/40/100 Гбит/с (Bonding / RoCE) |

### Ограничения и особенности

- **Версия PostgreSQL:** GP7 базируется на PG12. Некоторые расширения и синтаксис PG13+ могут быть недоступны.
- **Распределенные транзакции:** протокол **2PC (Two-Phase Commit)** накладывает штраф на производительность массовых UPDATE/DELETE (см. **[Распределённые транзакции](./Concepts/distributed_transactions.md)**).
- **Interconnect на TCP:** ограничение масштабируемости — 1000 сегмент-инстансов (UDPIFC ограничения не имеет).
- **Data Skew (Перекос данных):** неправильный ключ дистрибуции приводит к перегрузке одного сегмента, что замедляет весь кластер.
    - *Диагностика:* `SELECT gp_segment_id, count(*) FROM table GROUP BY 1;`
- **Compaction AO-таблиц:** порог проверяется на каждом сегменте отдельно — VACUUM может упаковать таблицу на одних сегментах и не упаковать на других.
- **Вложенные cgroups** (контейнерные деплойменты) влияют на лимиты resource groups: лимиты CPU/памяти рассчитываются от квоты родительской группы.
- **QuickLZ** недоступен в open-source версии и deprecated.

### Смежные темы

- **[Шардирование и MPP](./Concepts/sharding.md)** — теоретическая база.
- **[PostgreSQL Scaling](./PostgreSQL/Concepts/scaling.md)** — масштабирование Postgres.
- **[ClickHouse](./ClickHouse/clickhouse.md)** — альтернатива для простых аналитических сценариев.
- **[Репликация](./Concepts/replication.md)** — механизмы копирования данных.
- **[Партиционирование](./Concepts/partitioning.md)** — детали партиционирования.
- **[Резервное копирование](./Concepts/backups.md)** — общие подходы к бэкапам.
