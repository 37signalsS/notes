# Тюнинг Linux под PostgreSQL

**Актуально для:** PostgreSQL 14–17 на bare-metal / VM (в Kubernetes — часть параметров делегируется runtime)

## Определения

*   **THP (Transparent Huge Pages)** — механизм ядра, автоматически объединяющий страницы 4 KB в 2 MB. Для PostgreSQL рекомендовано **отключение** (`never`): дефрагментация THP вызывает всплески latency на `mmap`-операциях и фоновых процессах.
*   **Huge Pages (explicit)** — ручное резервирование 2 MB страниц под `shared_buffers` (`huge_pages = on` в `postgresql.conf` + `vm.nr_hugepages` в ОС). Убирает TLB-промахи для большого shared memory сегмента; в отличие от THP — без дефрагментации в runtime.
*   **NUMA (Non-Uniform Memory Access)** — архитектура многопроцессорных серверов: доступ к «чужой» памяти узла медленнее. PostgreSQL чувствителен: `shared_buffers` и воркеры, распределённые по узлам NUMA, получают штраф на remote access.
*   **CPU pinning** — привязка процессов к конкретным ядрам (`taskset`, `cgroups cpuset`). Для PostgreSQL: изоляция бэкендов от фоновых задач ОС, контроль распределения по NUMA.
*   **cgroups** — механизм ядра для лимитов ресурсов (CPU, memory, I/O) на группу процессов. Общая теория — **[cgroups](../../../Linux/Core/cgroups.md)**.
*   **`vm.overcommit_memory`** — политика выделения памяти: `0` (эвристика), `1` (всегда разрешать), `2` (строгий лимит по RAM+swap). Для PostgreSQL — `2` с расчётом, чтобы OOM-killer не убил postmaster.
*   **`vm.swappiness`** — склонность ядра вытеснять страницы в swap: `1` (почти не свопить) для серверов БД; `0` — риск OOM при пиках.
*   **I/O scheduler** — планировщик блочного устройства: `mq-deadline` или `none` для NVMe; `cfq` устарел.

## Базовые концепции

### Почему PostgreSQL — особый случай для ОС

PostgreSQL использует **shared memory** (POSIX shm) для `shared_buffers` и собственный пул процессов (process-per-connection). Отсюда три специфичных требования:

1.  **Huge pages**: `shared_buffers` в десятки ГБ — идеальный кандидат на 2 MB страницы; без них TLB-кэш процессора промахивается на каждом обращении.
2.  **NUMA**: postmaster и бэкенды должны либо чередовать память между узлами (`--interleave=all`), либо работать локально к своему CPU; иначе remote access удваивает latency памяти.
3.  **OOM-защита**: `overcommit_memory = 2` + корректный расчёт гарантируют, что ядро не убьёт postmaster в момент пика (OOM-killer выбирает по `oom_score`, а postgres с большим RSS — первый кандидат).

### Что настраивается, а что нет

| Параметр | Где | Контекст |
| :--- | :--- | :--- |
| THP | ОС (`/sys/kernel/mm/transparent_hugepage/enabled`) | хост/VM; в K8s — initContainer с привилегиями |
| Huge pages | ОС (`vm.nr_hugepages`) + `huge_pages` в `postgresql.conf` | хост; в K8s — hugepages resource |
| NUMA | запуск postmaster (`numactl`) или BIOS | хост |
| CPU pinning | `taskset` / cgroups `cpuset` | хост или pod |
| cgroups limits | systemd unit / K8s resources | хост или pod |
| `vm.swappiness`, `overcommit_memory` | sysctl | хост |
| I/O scheduler, `noatime` | udev / mount | хост |

## Практические сценарии

### Предварительные требования

1.  **Доступ**: `sudo` на хост; `numactl` (пакет `numactl`), `taskset` (util-linux).
2.  **Диагностика до изменений**: `numactl --hardware`, `cat /proc/meminfo | grep Huge`, `ps -o psr -p <pid>`.

### 1. Отключение THP

```bash
# Проверка текущего состояния
cat /sys/kernel/mm/transparent_hugepage/enabled
# → always [madvise] never   ← madvise/always — плохо для PostgreSQL

# Отключение (до перезагрузки)
sudo bash -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled'
sudo bash -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag'

# Постоянно: systemd-tmpfiles или GRUB
# /etc/systemd/system/disable-thp.service:
# [Service]
# Type=oneshot
# ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled'
# ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag'
```
```bash
# Валидация
cat /sys/kernel/mm/transparent_hugepage/enabled
# → always madvise [never]
```
Общая теория THP — **[sysctl: память](../../../Linux/Core/kernel/sysctl.md)**.

### 2. Huge pages под `shared_buffers`

```bash
# Расчёт: shared_buffers = 32 GB → 32*1024/2 = 16384 страниц по 2 MB
sudo sysctl vm.nr_hugepages=16384
# → vm.nr_hugepages = 16384

# Проверка
grep HugePages /proc/meminfo
# → HugePages_Total:   16384
# → HugePages_Free:    16384
# → HugePages_Rsvd:    0
# → HugePages_Surp:    0
```
```ini
# postgresql.conf
shared_buffers = 32GB
huge_pages = on      # on = использовать, если доступны; try — без ошибки при нехватке
```
```sql
-- Валидация: PostgreSQL использует huge pages
SELECT name, setting FROM pg_settings WHERE name IN ('shared_buffers', 'huge_pages');
-- → shared_buffers | 32GB
-- → huge_pages    | on
```
Важно: `vm.nr_hugepages` резервируется **при старте**; если после старта PostgreSQL памяти не хватило — `huge_pages = try` продолжит работу на обычных страницах (проверить: `HugePages_Free` не уменьшился).

### 3. NUMA: интерлив или локальность

```bash
# Топология
numactl --hardware
# → available: 2 nodes (0-1)
# → node 0 cpus: 0 1 2 3 ...
# → node 0 size: 128 GB ...

# Вариант A: interleaved (простой, безопасный для shared_buffers)
sudo systemctl edit postgresql
# → [Service]
# → ExecStart=
# → ExecStart=/usr/bin/numactl --interleave=all /usr/lib/postgresql/17/bin/postgres ...

# Вариант B: локальность (для очень больших серверов — бэкенды на узле 0,
# shared_buffers на том же узле; требует тестирования)
numactl --cpunodebind=0 --membind=0 postgres -D /var/lib/pgsql/17/data
```
Проверка: `numastat -p $(pgrep -o postgres)` — `numa_miss` должен быть малой долей от `numa_hit`.

### 4. CPU pinning бэкендов

```bash
# Привязать postmaster к ядрам 0-7 (пример: 8 ядер из 32)
sudo taskset -pc 0-7 $(pgrep -o postgres)
# → pid 12345's current affinity list: 0-31
# → pid 12345's new affinity list: 0-7

# Через cgroups v2 (постоянно): cpuset.cpus в unit-файле
# /etc/systemd/system/postgresql.service.d/override.conf:
# [Service]
# CPUAffinity=0-7
```
```bash
# Валидация
ps -o pid,psr,comm -p $(pgrep -o postgres)
# → PID | PSR | COMMAND
# → 12345 | 3 | postgres
```
Общая теория и нюансы — **[CPU pinning](../../../Linux/Core/cpu_pinning.md)**.

### 5. cgroups: лимиты для кластера

```ini
# /etc/systemd/system/postgresql.service.d/limits.conf (cgroups v2)
[Service]
# CPU: максимум 16 ядер
CPUQuota=1600%
# Memory: жёсткий лимит выше shared_buffers + work_mem × max_connections + overhead
MemoryMax=96G
# IO: вес записи WAL
IOWeight=500
```
```bash
sudo systemctl daemon-reload && sudo systemctl restart postgresql
# Проверка
systemctl show postgresql --property=MemoryCurrent,CPUQuotaPerSecUSec
# → MemoryCurrent=71234567168
# → CPUQuotaPerSecUSec=16000000
```
Полная справка по cgroups — **[cgroups](../../../Linux/Core/cgroups.md)**; методология замеров — **[тестирование производительности](../../../Testing/performance_testing_methodology.md)**.

### 6. sysctl: память и грязные страницы

```bash
# /etc/sysctl.d/99-postgresql.conf
vm.overcommit_memory = 2
vm.overcommit_ratio = 80        # при overcommit_memory=2: RAM×ratio/100 + swap
vm.swappiness = 1
vm.dirty_background_ratio = 5   # фоновая запись грязных страниц
vm.dirty_ratio = 10             # жёсткий предел (процесс блокируется)
vm.dirty_expire_centisecs = 3000
```
```bash
sudo sysctl --system
# → * Applying /etc/sysctl.d/99-postgresql.conf ...
# → vm.overcommit_memory = 2
```
Расчёт `overcommit_ratio`: `(shared_buffers + max_connections × work_mem + overhead) / RAM × 100` с запасом; ошибка → `FATAL: could not create shared memory segment: Cannot allocate memory` при старте.

### 7. I/O: планировщик и монтирование

```bash
# Планировщик для NVMe
cat /sys/block/nvme0n1/queue/scheduler
# → none [mq-deadline] kyber bfq   ← mq-deadline или none для NVMe

# Монтирование PGDATA
# /etc/fstab:
# /dev/nvme0n1 /var/lib/pgsql xfs defaults,noatime 0 0
sudo mount -o remount,noatime /var/lib/pgsql
```

## Операции и команды

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Проверить THP | `cat /sys/kernel/mm/transparent_hugepage/enabled` | `[never]` |
| Резервировать huge pages | `sysctl vm.nr_hugepages=16384` | `vm.nr_hugepages = 16384` |
| Проверить huge pages | `grep HugePages /proc/meminfo` | `HugePages_Total: 16384` |
| Применить sysctl | `sysctl --system` | Параметры применены |
| Проверить NUMA | `numastat -p <pid>` | `numa_miss` минимален |
| Проверить CPU affinity | `ps -o pid,psr,comm -p <pid>` | PSR в заданном диапазоне |
| Проверить cgroups | `systemctl show postgresql --property=MemoryCurrent,CPUQuotaPerSecUSec` | Лимиты активны |
| Проверить I/O scheduler | `cat /sys/block/nvme0n1/queue/scheduler` | `[mq-deadline]` или `[none]` |

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: could not create shared memory segment` | `overcommit_memory=2` без расчёта `overcommit_ratio` | Рассчитать и задать `vm.overcommit_ratio` |
| PostgreSQL не использует huge pages | Недостаточно `vm.nr_hugepages` или `huge_pages=off` | Увеличить `vm.nr_hugepages` с запасом 10%; `huge_pages=on` |
| Высокая latency, `numa_miss` велико | Remote memory access | `numactl --interleave=all` или pin к NUMA-узлу |
| OOM-killer убивает postmaster | `overcommit_memory=0/1` или неверный `overcommit_ratio` | `overcommit_memory=2` + корректный расчёт |
| Высокий `si%` в `mpstat` | SoftIRQ на изолированных ядрах | Настроить IRQ affinity на housekeeping-ядра |
| Процесс мигрирует между ядрами | Ядра не в `isolated` cgroup, балансировщик перераспределяет | Использовать `cpuset.cpus.exclusive` или `isolcpus` |
| `HugePages_Free` не уменьшился после старта | PostgreSQL не смог выделить huge pages | Проверить логи postmaster; возможно, `huge_pages=try` |
| `vm.nr_hugepages` не применяется при старте | Конкуренция за память с другими сервисами | Резервировать huge pages раньше старта других сервисов |

## Лучшие практики

1.  **THP = never** — без исключений для latency-sensitive нагрузки; исключение — только если приложение само использует `madvise(MADV_HUGEPAGE)` и вы это замерили.
2.  **Huge pages для `shared_buffers`** при `shared_buffers > 8 GB`: резервировать `vm.nr_hugepages` с запасом 5–10% и проверять `HugePages_Free` после старта.
3.  **NUMA**: начинать с `--interleave=all`; переходить к `cpunodebind/membind` только по замерам `numastat`.
4.  **`overcommit_memory = 2`** с расчётом — защита от OOM-killer; без расчёта параметр опаснее, чем полезен.
5.  **cgroups в K8s**: `resources.limits.memory` должен быть выше `shared_buffers` + буферов, иначе OOMKill пода; `hugepages-2Mi` resource для huge pages.
6.  **Замер до/после**: `pgbench` или production-нагрузка; метрики — latency p99, `Buffers: shared hit/read`, `numastat`. Не настраивать «по статье» без замера.
7.  **Документировать**: все sysctl и unit-override — в конфигурационном менеджере (Ansible/Puppet), не руками на хосте.
8.  **Housekeeping ядра**: резервировать минимум 2 ядра (0,1) для ОС на системах с < 8 ядрами, минимум 4 ядра на больших.
9.  **CPU Governor**: использовать `performance` governor; исключить `ondemand` и `conservative`.

## Пограничные случаи

*   **Huge pages и контейнеры**: `vm.nr_hugepages` — хостовый параметр; в K8s — `hugepages-2Mi` в `resources.limits`, но резервирование всё равно на хосте.
*   **`overcommit_memory = 1`**: иногда рекомендуют для PostgreSQL — это отключает проверку и переносит риск на OOM-killer; `2` с расчётом безопаснее.
*   **CPU pinning и autovacuum**: привязка всего кластера к ядрам может голодать autovacuum-воркеры; оставляйте резерв ядер или используйте `autovacuum_naptime` + отдельный cpuset.
*   **`swappiness = 0`**: при пике памяти ядро может OOM вместо свопа; `1` — компромисс.
*   **NUMA и parallel workers**: параллельные воркеры могут уйти на другой узел NUMA — `numactl` на postmaster не гарантирует локальность воркеров; проверять `numastat -p`.
*   **Docker**: `--shm-size` (по умолчанию 64 MB) ограничивает `/dev/shm` — влияет на parallel query и некоторые расширения; `--ulimit memlock` для huge pages.
*   **Виртуализация**: в VM NUMA-топология гостя должна совпадать с хостом (NUMA pinning в hypervisor), иначе `numactl` внутри гостя бессмысленен.

## Очистка и откат

**Откат sysctl:**
```bash
# Удалить или закомментировать параметры в /etc/sysctl.d/99-postgresql.conf
sudo sysctl --system
```

**Откат THP:**
```bash
sudo bash -c 'echo always > /sys/kernel/mm/transparent_hugepage/enabled'
sudo bash -c 'echo always > /sys/kernel/mm/transparent_hugepage/defrag'
# Удалить /etc/systemd/system/disable-thp.service
sudo systemctl daemon-reload
```

**Откат huge pages:**
```bash
sudo sysctl vm.nr_hugepages=0
# Убрать huge_pages из postgresql.conf
sudo systemctl restart postgresql
```

**Откат CPU pinning:**
```bash
# Через taskset (до перезагрузки)
sudo taskset -pc 0-31 $(pgrep -o postgres)
# Через systemd: удалить override.conf
sudo rm /etc/systemd/system/postgresql.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart postgresql
```

**Откат cgroups limits:**
```bash
sudo rm /etc/systemd/system/postgresql.service.d/limits.conf
sudo systemctl daemon-reload && sudo systemctl restart postgresql
```

**Откат NUMA:**
```bash
# Убрать numactl из systemd override
sudo systemctl edit postgresql
# Удалить ExecStart строки
sudo systemctl daemon-reload && sudo systemctl restart postgresql
```

## Дополнительная информация

*   [cgroups](../../../Linux/Core/cgroups.md) — лимиты CPU/memory/IO, cgroups v1 vs v2.
*   [CPU pinning](../../../Linux/Core/cpu_pinning.md) — привязка процессов к ядрам.
*   [Изоляция CPU](../../../Linux/Core/kernel/cpu_isolation.md) — `isolcpus`, `nohz_full`, динамические партиции.
*   [NUMA awareness](../../../Linux/Core/processes/numa_awareness.md) — топология памяти и процессы.
*   [sysctl: память](../../../Linux/Core/kernel/sysctl.md) — THP, overcommit, swappiness.
*   [Тестирование производительности](../../../Testing/performance_testing_methodology.md) — методология замеров.
*   [Оптимизация производительность](./performance_tuning.md) — параметры PostgreSQL (`shared_buffers`, `work_mem`).
*   [Установка на Ubuntu](./installation_ubuntu.md) — systemd-юнит, расположение PGDATA.
*   [Официальная документация: Kernel resources](https://www.postgresql.org/docs/current/kernel-resources.html)
*   [Официальная документация: Huge Pages](https://www.postgresql.org/docs/current/kernel-resources.html#LINUX-HUGE-PAGES)