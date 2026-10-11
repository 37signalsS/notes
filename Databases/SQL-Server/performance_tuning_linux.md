# SQL Server: Тюнинг производительности в Linux

**Актуально для:** SQL Server 2025 (17.x) / 2022 (16.x) / 2019 (15.x) — Linux (RHEL, Ubuntu; SLES поддерживается до 2022 включительно, начиная с 2025 не поддерживается)

Настройка SQL Server на Linux на уровне экземпляра (`mssql-conf`, T-SQL), ядра ОС (sysctl, TuneD) и хранилища — для bare-metal, VM и контейнеров. Общие теоретические основы (THP, NUMA, KSM, Zram) — в [Оптимизации памяти Linux](../Linux/Core/memory/performance_tuning.md); обзор редакций и установки — в [Обзоре SQL Server](./overview.md).

## Определения

- **mssql-conf** — основной инструмент настройки параметров SQL Server в Linux (`/opt/mssql/bin/mssql-conf`). Изменения записываются в `/var/opt/mssql/mssql.conf`; большинство параметров требуют перезапуска (`sudo systemctl restart mssql-server`).
- **SQLPAL** (SQL Platform Abstraction Layer) — прослойка SQL Server между ядром Linux и ядром СУБД; все системные вызовы идут через неё.
- **cgroup v2** — механизм ядра Linux для ограничения и учёта ресурсов (`memory.max`, `cpu.max`). SQL Server читает лимиты cgroup v2 начиная с **SQL Server 2025** и **SQL Server 2022 CU20**. В более ранних версиях в Kubernetes (например, AKS v1.25+) возможны OOM-ошибки, так как SQL Server не учитывала лимиты памяти контейнера.
- **Headroom** — зазор между лимитом контейнера (или RAM хоста) и `memorylimitmb`, резервируемый под ОС и вспомогательные процессы.
- **Soft affinity (Trace Flag 8002)** — режим, при котором планировщики SQL Server могут перемещаться между ядрами в рамках affinity-маски и квоты cgroup, вместо жёсткой привязки к конкретным CPU.
- **THP (Transparent Huge Pages)** — автоматическое продвижение страниц 4 КБ → 2 МБ. Microsoft рекомендует **оставлять THP включённым** (`always`) для наиболее предсказуемой производительности.
- **TuneD / профиль `mssql`** — демон управления профилями ядра; официальный профиль `/usr/lib/tuned/mssql/tuned.conf` применяет рекомендованные sysctl-параметры.
- **FUA (Forced Unit Access)** — возможность подсистемы I/O гарантировать запись на носитель; SQL Server использует её для эффективного прямого I/O (RHEL 8.0+, SLES 12 SP5+, Ubuntu 18.04+; SQL Server 2017 CU6+).
- **MAXDOP / CTFP** — `max degree of parallelism` (макс. число ядер на параллельный план) и `cost threshold for parallelism` (порог стоимости для параллельных планов).

## Иерархия управления ресурсами

Память ограничена вложенными лимитами — каждый следующий уровень уже предыдущего:

| Уровень | Задаётся | Назначение |
| :--- | :--- | :--- |
| RAM хоста | Hardware/VM | Физическая память сервера |
| cgroup-лимит (`memory.max`) | `docker run --memory`, systemd slice, K8s `resources.limits` | Жёсткий потолок ядра для всех процессов в cgroup (в bare-metal опционален) |
| `memorylimitmb` / `MSSQL_MEMORY_LIMIT_MB` | `mssql-conf` или переменная окружения | **Вся** память процесса SQL Server: buffer pool + SQLPAL + Agent + LibOS + PolyBase + Full-Text Search |
| `max server memory` | `sp_configure` | Только buffer pool (кэш 8-КБ страниц); всегда **ниже** `memorylimitmb` |

Ключевые правила:

- По умолчанию `memorylimitmb` = **80% от меньшего** из RAM хоста и cgroup-лимита (если он есть).
- Переменная окружения `MSSQL_MEMORY_LIMIT_MB` имеет приоритет над `memorylimitmb` в `mssql.conf`.
- `memorylimitmb` не может превышать RAM хоста и cgroup-лимит — иначе OOM Killer завершит `sqlservr`.
- `memory.disablememorypressure = true` **не использовать**: отключает сигналы, ограничивающие потребление памяти, и процесс выйдет за `memorylimitmb`.

## Практические сценарии

### 1. Управление памятью

**Headroom 10–20%** от лимита контейнера — для большинства развёртываний. Для больших конфигураций процентный буфер избыточен (10% от 512 ГБ — это 51 ГБ, больше чем нужно ОС): используйте фиксированный зазор, подобранный под нагрузку.

```bash
# Установка лимита памяти процесса (требует перезапуска)
sudo /opt/mssql/bin/mssql-conf set memory.memorylimitmb 10240
sudo systemctl restart mssql-server
```

Примеры Docker (хост с 16 ГБ RAM):

```bash
# Рекомендуется: лимит контейнера 12 ГБ, SQL Server — 10 ГБ (headroom ~17%)
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=<пароль>" \
   -e "MSSQL_MEMORY_LIMIT_MB=10240" --memory 12g -p 1433:1433 \
   -d mcr.microsoft.com/mssql/server:2025-latest

# НЕ рекомендуется: лимиты равны (12g = 12288 МБ) — нет headroom, риск OOM
# НЕ рекомендуется: MSSQL_MEMORY_LIMIT_MB=14336 при --memory 12g — лимит SQL Server выше лимита контейнера
# НЕ рекомендуется: --memory без MSSQL_MEMORY_LIMIT_MB — другие процессы в контейнере не ограничены
```

**Swap:** включите swap на хосте как страховку от транзиентного давления, но не рассчитывайте на него в стационарной работе — производительность при свопинге деградирует. `vm.swappiness = 1` (см. профиль TuneD ниже).

**Buffer pool:** `max server memory (MB)` настраивается через `sp_configure` и должен быть ниже `memorylimitmb`, чтобы память оставалась для SQLPAL, Agent и остальных компонентов.

### 2. CPU и планировщик

**Affinity** задаётся T-SQL (а не mssql.conf) — например, чтобы создать ровно столько планировщиков, сколько CPU в квоте cgroup (квота 4 CPU на 8-ядерном хосте):

```sql
USE master;
GO
ALTER SERVER CONFIGURATION SET PROCESS AFFINITY CPU = 4 TO 7;
GO
-- или привязка к NUMA-узлу: ALTER SERVER CONFIGURATION SET PROCESS AFFINITY NUMANODE = 1;
```

**Trace Flag 8002 (рекомендуется в контейнерах с явным affinity):**

```bash
sudo /opt/mssql/bin/mssql-conf traceflag 8002 on
sudo systemctl restart mssql-server   # флаг требует перезапуска
```

По умолчанию планировщики жёстко привязаны к CPU из affinity-маски; TF 8002 позволяет им перемещаться между ядрами в рамках маски и квоты cgroup, что обычно улучшает производительность. После перезапуска: SQL Server создаёт только указанное число планировщиков, ядро продолжает применять квоту `cpu.max`, а оптимизатор принимает решения о параллелизме исходя из целевого числа CPU, а не от общего числа ядер хоста. Замечание: в error log может отображаться общее число CPU хоста — это не влияет на реальное использование.

**MAXDOP и CTFP** (T-SQL, действуют как на Windows):

```sql
EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
EXEC sp_configure 'max degree of parallelism', 4;      -- в контейнере: не более квоты CPU
EXEC sp_configure 'cost threshold for parallelism', 25; -- дефолт 5 — лишь отправная точка
RECONFIGURE;
```

Рекомендации MAXDOP: один NUMA-узел — не более 8 (или числа логических процессоров, если их ≤ 8); несколько NUMA-узлов — половина процессоров на узел, максимум 16. CTFP повышают до 20–50 для OLTP, чтобы мелкие запросы не уходили в параллельные планы; признак слишком низкого CTFP — доминирование `CXPACKET`/`CXCONSUMER` в `sys.dm_os_wait_stats`.

### 3. Настройки ОС-хоста

**Профиль TuneD `mssql`** (рекомендуемый способ применить все sysctl-параметры сразу):

```ini
# /usr/lib/tuned/mssql/tuned.conf
[main]
summary=Optimize for Microsoft SQL Server
include=throughput-performance

[cpu]
force_latency=5

[sysctl]
vm.swappiness = 1
vm.dirty_background_ratio = 3
vm.dirty_ratio = 80
vm.dirty_expire_centisecs = 500
vm.dirty_writeback_centisecs = 100
vm.transparent_hugepages=always
# Для multi-instance развёртываний: vm.transparent_hugepages=madvise
vm.max_map_count=1600000
net.core.rmem_default = 262144
net.core.rmem_max = 4194304
net.core.wmem_default = 262144
net.core.wmem_max = 1048576
kernel.numa_balancing=0
```

```bash
sudo chmod +x /usr/lib/tuned/mssql/tuned.conf
sudo tuned-adm profile mssql
tuned-adm active   # проверка: должен показать mssql
```

Для ядер **старше 4.18** дополнительно раскомментируйте `kernel.sched_latency_ns = 60000000`, `kernel.sched_migration_cost_ns = 500000`, `kernel.sched_min_granularity_ns = 15000000`, `kernel.sched_wakeup_granularity_ns = 2000000`; на современных ядрах их держат закомментированными.

Разбор параметров:

- `vm.swappiness = 1` — предпочтение удержания памяти процессов перед page cache; SQL Server пишет в обход файлового кэша для надёжности восстановления.
- `vm.dirty_*` — SQL Server делает uncached-записи; параметры позволяют большому асинхронному кэшу при throttling сброса.
- `vm.max_map_count` — по умолчанию 65536, что может быть мало для SQL Server; минимум 262144, максимум 2147483647.
- `kernel.numa_balancing = 0` — отключить авто-NUMA balancing на многопроцессорных NUMA-системах; SQL Server сама управляет NUMA.
- CPU: governor `performance`, `ENERGY_PERF_BIAS=performance`, `min_perf_pct=100` (настраивается через `throughput-performance`); C-States — только C1 (вручную, по документации вендора).

**Transparent Huge Pages:** оставьте `always` (это значение в профиле `mssql`). Переключайте на `madvise` только если наблюдается высокая страничная активность при нескольких инстансах SQL Server или других требовательных к памяти приложениях — и предварительно протестируйте нагрузкой:

```bash
echo madvise | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

**Сеть:** проверьте и при необходимости увеличьте кольцевые буферы NIC (значения зависят от вендора; пример для Intel — 4 КБ):

```bash
ethtool -g eth0          # текущие максимумы
sudo ethtool -G eth0 rx 4096 tx 4096
```

**Лимит открытых файлов:** production-нагрузка может требовать больше дефолтных 1024; установите soft/hard в 1048576. В RHEL: `/etc/security/limits.d/99-mssql-server.conf` → `mssql - nofile 1048576`. Замечание: для сервисов, запущенных через systemd, этот файл не действует — настраивайте `LimitNOFILE` в unit-файле.

**Core dumps:** на хосте настройте `/proc/sys/kernel/core_pattern` так, чтобы дампы падений SQLPAL сохранялись вне контейнера; внутри экземпляра каталог дампов задаётся `filelocation.defaultdumpdir`.

### 4. Хранилище

- **Файловая система:** XFS — рекомендуется для данных и журнала; ext4 тоже поддерживается (XFS обязателен на ядрах < 5.6, ext4 — на ядрах ≥ 5.6).
- **`noatime`** для томов с данными и журналом — убирает лишние записи метаданных при чтении; в `/etc/fstab` используйте UUID (`blkid`), а не имя устройства:

  ```bash
  UUID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" /data1 xfs rw,attr2,noatime 0 0
  ```

- **Read-ahead 4096** (`sudo blockdev --setra 4096 /dev/sdX`); для RAID выравнивайте stripe: `sunit`/`swidth` при форматировании XFS под размер stripe (пример: RAID-10, stripe 64 КБ, блок 4 КБ → `mkfs.xfs -d su=64k,sw=4`).
- **FUA** (при поддержке дистрибутивом и подсистемой хранения): включите TF 3979 как startup-параметр и задайте `sudo /opt/mssql/bin/mssql-conf set control.writethrough=1` и `control.alternatewritethrough=0`.
- **tempdb на tmpfs** (SQL Server 2025+, только `tempdb`; user-базы на tmpfs — только для dev, не поддерживается):

  ```bash
  sudo mkdir /var/opt/mssql/tempdb && sudo chown mssql. /var/opt/mssql/tempdb
  sudo mount -t tmpfs -o size=4G tmpfs /var/opt/mssql/tempdb/
  # для персистентности: echo "tmpfs /var/opt/mssql/tempdb tmpfs defaults,size=4G 0 0" | sudo tee -a /etc/fstab
  ```

- Размещайте данные, журнал и `tempdb` на отдельных томах; журнал требует низкой латентности записи.

### 5. Контейнеры и Kubernetes

Проверка версии cgroup и лимитов изнутри контейнера:

```bash
stat -fc %T /sys/fs/cgroup        # → cgroup2fs — cgroup v2
cat /sys/fs/cgroup/memory.max     # лимит памяти
cat /sys/fs/cgroup/cpu.max        # квота CPU (например "400000 100000" = 4 CPU)
```

Фрагмент манифеста (16 ГБ лимит, headroom ~19%):

```yaml
resources:
  limits:
    cpu: "8"
    memory: "16Gi"
env:
  - name: MSSQL_MEMORY_LIMIT_MB
    value: "13312"   # 13 ГБ из 16 ГБ; MSSQL_MEMORY_LIMIT_MB приоритетнее mssql.conf
```

Без `limits.memory` контейнер не имеет cgroup-потолка: `MSSQL_MEMORY_LIMIT_MB` ограничит только сам SQL Server, но не остальные процессы. TF 8002 в контейнерах включается через `mssql-conf traceflag 8002 on` (в образе или init-шаге) с последующим перезапуском.

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Список настраиваемых параметров | `sudo /opt/mssql/bin/mssql-conf list` |
| Установить параметр | `sudo /opt/mssql/bin/mssql-conf set memory.memorylimitmb 10240` |
| Сбросить параметр | `sudo /opt/mssql/bin/mssql-conf unset memory.memorylimitmb` |
| Trace flag on/off | `sudo /opt/mssql/bin/mssql-conf traceflag 8002 on` |
| Проверка конфига | `sudo /opt/mssql/bin/mssql-conf validate` |
| Перезапуск | `sudo systemctl restart mssql-server` |
| Ошибки/события | `sudo journalctl -u mssql-server`; лог: `/var/opt/mssql/log/errorlog` |
| Текущие sysctl | `sysctl vm.swappiness vm.max_map_count kernel.numa_balancing` |
| Read-ahead устройства | `sudo blockdev --getra /dev/sdX` |
| Профиль TuneD | `sudo tuned-adm profile mssql`; `tuned-adm active` |
| OOM-убийства | `sudo dmesg -T \| grep -i "killed process"` |

## Мониторинг (DMV и хост)

```sql
-- Информация о хосте (host_platform, host_distribution, host_release) — SQL 2017+
SELECT * FROM sys.dm_os_host_info;

-- Память ОС и процесса
SELECT available_physical_memory_kb, system_memory_state_desc FROM sys.dm_os_sys_memory;
SELECT physical_memory_in_use_kb, virtual_address_space_committed_kb FROM sys.dm_os_process_memory;

-- Планировщики (ожидаемое число = affinity/quota, а не ядра хоста)
SELECT scheduler_id, status, current_tasks_count, runnable_tasks_count
FROM sys.dm_os_schedulers WHERE status = 'VISIBLE ONLINE';

-- Топ ожиданий
SELECT TOP 10 wait_type, wait_time_ms, signal_wait_time_ms
FROM sys.dm_os_wait_stats ORDER BY wait_time_ms DESC;

-- Латентность I/O по файлам (io_stall_read_ms / io_stall_write_ms)
SELECT DB_NAME(database_id) AS db, file_id, num_of_reads, num_of_writes,
       io_stall_read_ms, io_stall_write_ms
FROM sys.dm_io_virtual_file_stats(NULL, NULL);

-- Свободное место на томах (часть колонок возвращает NULL на Linux)
SELECT f.database_id, f.file_id, volume_mount_point, total_bytes, available_bytes
FROM sys.master_files AS f CROSS APPLY sys.dm_os_volume_stats(f.database_id, f.file_id);
```

На хосте: `top`, `vmstat 1`, `iostat -x 1` — DMV «аналог top» для процессов Linux не существует. Разрешения: `sys.dm_os_volume_stats` требует `VIEW SERVER PERFORMANCE STATE` (SQL 2022+) или `VIEW SERVER STATE` (2019 и старше).

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| OOM Killer завершает `sqlservr` (dmesg) | `memorylimitmb` ≥ cgroup-лимита или нет headroom | Выставить `MSSQL_MEMORY_LIMIT_MB`/`memorylimitmb` ниже лимита на 10–20%; обновить до 2025 / 2022 CU20+ для учёта cgroup v2 |
| Ошибки 701/8645, `RESOURCE_SEMAPHORE` | Давление памяти внутри процесса | Проверить `max server memory` < `memorylimitmb`; не отключать `memory.disablememorypressure` |
| Доминирует `SOS_SCHEDULER_YIELD` | CPU pressure; слишком низкий CTFP или высокий MAXDOP | Поднять CTFP до 20–50, MAXDOP ≤ 8 (или ≤ квоты); включить TF 8002 при явном affinity |
| `PAGEIOLATCH_*` | Медленное хранилище | Проверить латентность через `dm_io_virtual_file_stats`; read-ahead 4096, `noatime`, отдельные тома для log |
| Высокий `WRITELOG` | Журнал на медленном/общем томе | Выделенный том для `.ldf`, FUA при поддержке |
| SQL Server не стартует / аллокации падают | `vm.max_map_count` слишком мал | `sysctl -w vm.max_map_count=262144` (минимум) |
| В error log число CPU хоста, а не квоты | Документированное поведение | Не является дефектом: реальное использование ограничено affinity и `cpu.max` |
| Лимит открытых файлов 1024 | Дефолт limits.d не действует на systemd | `LimitNOFILE=1048576` в unit-файле |

## Ограничения и риски

- `sys.dm_os_enumerate_fixed_drives` — только Windows; `sys.dm_os_volume_stats` на Linux возвращает NULL для `volume_id`, `file_system_type` и др.
- `tmpfs` поддерживается только для `tempdb`; user-базы на tmpfs — неподдерживаемая конфигурация (только dev).
- FUA требует поддерживающего дистрибутива и подсистемы хранения; без этого — стандартный buffered I/O.
- Настройки NIC (размеры колец, RSS) зависят от вендора — тестировать на dev перед production.
- Изменения sysctl/TuneD применяются к хосту и затрагивают все рабочие нагрузки на нём.

## Best Practices

- **Baseline перед изменением:** зафиксировать `sys.dm_os_wait_stats`, `dm_io_virtual_file_stats`, счётчики памяти до и после каждой правки; тестировать на dev/staging (официальная рекомендация Microsoft).
- Профиль TuneD `mssql` как базовая линия; read-ahead и C-States — вручную.
- Headroom 10–20% (фиксированный буфер для больших контейнеров); `MSSQL_MEMORY_LIMIT_MB` всегда ниже `limits.memory`.
- XFS + `noatime` + read-ahead 4096; отдельные тома для data/log/tempdb.
- MAXDOP ≤ 8 (или ≤ квоты cgroup), CTFP 20–50 для OLTP; TF 8002 при явном affinity в контейнерах.
- THP оставлять `always`; `madvise` — только по результатам тестов multi-instance.
- Мониторинг: `dm_os_wait_stats`, `dm_io_virtual_file_stats`, `dm_os_sys_memory`/`dm_os_process_memory`, `dmesg` на OOM.

## Дополнительная информация

### См. также

- **[Обзор SQL Server](./overview.md)** — редакции, установка, порты, cgroup v2 вкратце.
- **[Always On AG на Linux](./high_availability.md)** — кластеризация.
- **[Резервное копирование и восстановление](./backup-and-recovery.md)** — стратегии защиты данных.
- **[Оптимизация памяти Linux](../Linux/Core/memory/performance_tuning.md)** — THP, NUMA, KSM, Zram (общая теория).

### Внешние ссылки

- [Performance Best Practices: SQL Server Memory on Linux](https://learn.microsoft.com/en-us/sql/linux/configure/performance-best-practices-sql-server-memory?view=sql-server-ver17) — иерархия лимитов, cgroup v2, TF 8002, Docker-примеры.
- [Storage, Kernel, CPU, and Network for SQL Server on Linux](https://learn.microsoft.com/en-us/sql/linux/configure/performance-best-practices-operating-system?view=sql-server-ver17) — профиль TuneD, XFS, FUA, read-ahead.
- [Configure SQL Server on Linux with the mssql-conf tool](https://learn.microsoft.com/en-us/sql/linux/configure/mssql-conf?view=sql-server-ver17) — полный список параметров.
- [Performance Best Practices for SQL Server on Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-performance-best-practices?view=sql-server-ver17) — общие рекомендации.
- [tempdb on tmpfs (SQL Server 2025)](https://learn.microsoft.com/en-us/sql/linux/configure/tmpfs-tempdb-system-database?view=sql-server-ver17)
- [sys.dm_os_host_info](https://learn.microsoft.com/en-us/sql/relational-databases/system-dynamic-management-views/sys-dm-os-host-info-transact-sql?view=sql-server-ver17), [sys.dm_os_volume_stats](https://learn.microsoft.com/en-us/sql/relational-databases/system-dynamic-management-views/sys-dm-os-volume-stats-transact-sql?view=sql-server-ver17)
- [max degree of parallelism](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/configure-the-max-degree-of-parallelism-server-configuration-option?view=sql-server-ver17), [cost threshold for parallelism](https://learn.microsoft.com/en-us/sql/database-engine/configure-windows/configure-the-cost-threshold-for-parallelism-server-configuration-option?view=sql-server-ver17)
