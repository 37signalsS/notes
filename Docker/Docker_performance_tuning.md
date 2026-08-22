# Docker: Оптимизация производительности (Performance Tuning)

## Определения

- **OverlayFS (overlay2)**: Union filesystem, используемый Docker по умолчанию для организации файловой системы контейнеров. Работает на принципе наложения нижних слоёв (read-only) на верхний слой (read-write). Все модификации файлов происходят через механизм **Copy-on-Write (CoW)**: при первой записи файл копируется из нижнего слоя в верхний, что создаёт дополнительную задержку и нагрузку на I/O. Для write-heavy workload (БД, логи, сборка артефактов) CoW overhead является критическим узким местом.

- **conntrack**: Модуль ядра Linux, отвечающий за отслеживание состояния сетевых соединений (connection tracking). Используется подсистемой NAT в iptables/nftables для корректной маршрутизации ответных пакетов. При исчерпании таблицы `nf_conntrack_max` новые соединения отбрасываются с ошибкой `nf_conntrack: table full, dropping packet`. Критичен для Docker-хостов с высоким сетевым трафиком (много портов, балансировщики, proxy).

- **I/O Scheduler**: Алгоритм ядра Linux, определяющий порядок обработки блочных операций чтения/записи. Влияет на пропускную способность и задержку дисковых операций. Основные алгоритмы: `mq-deadline` (баланс, по умолчанию для большинства SSD/HDD), `bfq` (fair queueing, лучше для интерактивных нагрузок), `none` (noop, оптимально для NVMe и аппаратных RAID с собственным кешем).

- **NUMA (Non-Uniform Memory Access)**: Архитектура multiprocessing, при которой время доступа к оперативной памяти зависит от физического расположения памяти относительно процессора. На NUMA-системах каждый CPU socket имеет локальную память; доступ к удалённой памяти другого socket происходит через межsocket-каналы с удвоенной задержкой. Для Docker-контейнеров, работающих с интенсивной памятью (БД, кэши), привязка к NUMA-ноде критична для производительности.

- **Page Cache**: Механизм ядра Linux для кэширования содержимого файлов в оперативной памяти. При чтении файла его содержимое сохраняется в RAM и повторные обращения обслуживаются из кэша без обращения к диску. Для Docker Page Cache является двойным мечом: с одной стороны ускоряет чтение файлов из overlay2 нижних слоёв (общий кеш между контейнерами), с другой — при нехватке памяти ядро вытесняет страницы кеша, что может деградировать I/O производительность.

## Базовые концепции

### 1. Производительность storage driver (overlay2 CoW overhead)

Драйвер `overlay2` использует Copy-on-Write для модификации файлов: при первой записи в файл из нижнего слоя выполняется полное копирование в верхний слой контейнера. Это создаёт задержку пропорционально размеру файла.

**Факторы, влияющие на CoW overhead:**
- **Размер файлов**: копирование 10GB файла при первом `docker exec`会造成 значительную задержку
- **Количество слоёв**: чем глубже стек `lowerdir`, тем больше metadata-операций
- **Тип базовой ФС**: XFS с `ftype=1` и `reflink=1` поддерживает CoW на уровне файлов (reflinks), что значительно быстрее
- **Тип хранилища**: volumes и bind mounts обходят overlay2, обеспечивая нативную производительность

**Когда использовать volumes vs bind mounts:**
- **Named volumes**: Docker управляет хранилищем, данные персистентны, поддерживают драйверы (NFS,云 storage). Для PostgreSQL/MySQL/data-intensive приложений.
- **Bind mounts**: прямой доступ к директории хоста, удобно для dev (hot reload). Минус: права доступа, отсутствие isolation.
- **tmpfs**: данные в RAM, для секретов и временных файлов. Не переживает рестарт контейнера.

### 2. Производительность сети (MTU, conntrack, TCP buffers, userland-proxy)

Сетевая производительность Docker определяется несколькими факторами:

**MTU (Maximum Transmission Unit):**
- Стандартный MTU Ethernet = 1500 байт
- При использовании туннелей (IPsec, WireGuard, VXLAN) реальный MTU снижается (обычно 1400-1420)
- Несовпадение MTU между хостом и контейнером вызывает фрагментацию пакетов и потерю производительности
- Рекомендация: `ip link show docker0` → проверить MTU; `ping -M do -s 1472` для валидации

**Conntrack exhaustion:**
- Таблица `nf_conntrack` имеет фиксированный размер (по умолчанию 262144 на большинстве дистрибутивов)
- Docker создаёт DNAT-правила для каждого published port, что увеличивает потребление conntrack
- При исчерпании: `dmesg | grep conntrack` → `table full, dropping packet`
- Решение: увеличение `net.netfilter.nf_conntrack_max` и оптимизация `net.netfilter.nf_conntrack_tcp_timeout_*`

**TCP buffer sizes:**
- `net.core.rmem_max` / `net.core.wmem_max` — максимальные размеры буферов приёма/передачи
- `net.ipv4.tcp_rmem` / `net.ipv4.tcp_wmem` — min/default/max для TCP-сокетов
- Для high-bandwidth links (10Gbps+) дефолтных буферов недостаточно

**userland-proxy vs iptables:**
- `userland-proxy: true` (дефолт): Docker запускает процесс `docker-proxy` для каждого published port. Это потребляет память и CPU, но работает через user-space.
- `userland-proxy: false`: Docker использует iptables DNAT. Нет extra процессов, ниже latency, ниже overhead. Рекомендуется для production.

### 3. Производительность CPU (pinning, NUMA, CFS bandwidth control)

Docker предоставляет несколько механизмов управления CPU:

**CPU pinning (--cpuset-cpus):**
- Привязка контейнера к конкретным ядрам CPU
- Устраняет overhead переключения контейнера между ядрами (context switch)
- Критично для latency-sensitive приложений (БД, real-time)
- Пример: `--cpuset-cpus="0,1"` — контейнер работает только на ядрах 0 и 1

**CPU shares (--cpu-shares):**
- Относительный вес контейнера при конкуренции за CPU
- Дефолт: 1024. Значение 2048 получит в 2 раза больше CPU чем 1024
- Работает только при CPU contention (все ядра заняты)

**CFS Bandwidth Control (--cpu-quota, --cpu-period):**
- Абсолютное ограничение CPU в микросекундах за период
- `--cpu-quota=50000 --cpu-period=100000` = 50% одного ядра
- В cgroups v2: `cpu.max = "50000 100000"`

**NUMA-aware allocation:**
- На NUMA-системах Docker не автоматически привязывает контейнеры к NUMA-ноде
- Неправильная конфигурация → удалённый memory access → удвоенная задержка
- Решение: `numactl --cpunodebind=0 --membind=0 docker run ...`

### 4. Производительность памяти (page cache interaction, swappiness, huge pages)

**Page Cache в контексте Docker:**
- Файлы из overlay2 нижних слоёв кэшируются в Page Cache и разделяются между всеми контейнерами с тем же образом
- При `memory.max` (cgroups v2) ядро ограничивает общее потребление RAM контейнера, включая Page Cache
- При `memory.high` контейнер не убивается, но приложение испытывает давление памяти (memory pressure) и может начать свопать

**Swappiness:**
- `vm.swappiness` — склонность ядра к свопанию (0-100, дефолт 60)
- Значение 0: свопать только при absolute memory pressure
- Значение 100: агрессивное свопание для освобождения Page Cache
- Для Docker-хостов рекомендуется `vm.swappiness=10` или ниже
- На уровне контейнера: `--memory-swap` ограничивает swap отдельно

**Transparent Huge Pages (THP):**
- THP автоматически использует страницы 2MB вместо 4KB
- Выгодно для приложений с large memory footprint (БД, кэши)
- Минус: может вызывать latency spikes при defrag (khugepaged)
- Для БД (MongoDB, Redis) рекомендуется `echo madvise > /sys/kernel/mm/transparent_hugepage/enabled`

### 5. Производительность I/O (scheduler selection, blkio throttling, direct I/O)

**I/O Scheduler:**
- `mq-deadline`: баланс между throughput и latency, рекомендуется для大多数 SSD/HDD
- `bfq`:公平ное распределение I/O bandwidth, лучше для интерактивных нагрузок (Desktop, dev)
- `none` (noop): без обработки, оптимально для NVMe SSD и аппаратных RAID (контроллер сам оптимизирует)
- Проверка текущего scheduler: `cat /sys/block/sda/queue/scheduler`

**blkio throttling (cgroups v1) / io.max (cgroups v2):**
- Ограничение IOPS и bandwidth для контейнера
- cgroups v1: `--device-read-bps`, `--device-write-iops`
- cgroups v2: `io.max = "8:0 rbps=104857600 wbps=52428800 riops=1000 wiops=500"`
- Критично для shared storage: предотвращение "smtpy neighbor" эффекта

**Direct I/O (O_DIRECT):**
- Обход Page Cache для чтения/записи файлов
- Для приложений со собственным кешем (PostgreSQL, MySQL) прямой I/O исключает двойное кэширование
- Достигается через `O_DIRECT` флаг в приложении или `--storage-opt size=10G` для ограничения writable layer

### 6. Тюнинг файловой системы (XFS ftype, noatime, journaling)

**XFS с ftype=1:**
- Обязательное требование для overlay2
- `ftype=0` → whiteout не работает, Docker не может корректно удалять файлы
- Проверка: `xfs_info /var/lib/docker | grep ftype`
- Форматирование: `mkfs.xfs -n ftype=1 /dev/sdX`

**noatime:**
- Отключение обновления времени доступа к файлам
- Снижает количество metadata-операций на 30-50%
- Монтирование: `mount -o noatime /dev/sdX /var/lib/docker`
- В `/etc/fstab`: `UUID=... /var/lib/docker xfs defaults,noatime 0 0`

**Journaling:**
- XFS: journaling включён по умолчанию, необходимо для целостности данных
- Отключение journaling (`nolog`) ускоряет запись, но при аварийном завершении возможна потеря данных
- Для Docker dev/test environments можно рассмотреть `nolog`

**Readahead:**
- `blockdev --setra 4096 /dev/sda` — увеличение read-ahead до 2MB (дефолт 256 sectors = 128KB)
- Выгодно для sequential reads (загрузка образов, pull)
- Для random I/O (БД) лучше оставить дефолт или уменьшить

## Практические сценарии

### Сценарий 1: Оптимизация overlay2 (минимизация слоёв, COPY --link, cache mounts)

Минимизация CoW overhead через оптимизацию Dockerfile и использование современных возможностей BuildKit:

```dockerfile
# Старый подход (плохо): 3 отдельных слоя, 3 copy-up операции
RUN apt-get update
RUN apt-get install -y curl wget
RUN rm -rf /var/lib/apt/lists/*

# Оптимизированный подход: 1 слой, 1 copy-up
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl wget && \
    rm -rf /var/lib/apt/lists/*

# BuildKit cache mount: кеш пакетного менеджера сохраняется между сборками
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends curl wget

# COPY --link: инкрементальная валидация слоёв (BuildKit)
COPY --link requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

COPY --link . /app/
```

```bash
# Проверка размера слоёв
docker history my-app:latest --format "table {{.Size}}\t{{.CreatedBy}}"

# Сравнение: slimmer image = меньше copy-up при первом запуске
docker images --format "table {{.Repository}}\t{{.Size}}"
```

**Валидация:** `docker build --no-cache .` → время сборки должно сократиться, размер финального образа уменьшиться.

### Сценарий 2: Настройка conntrack (sizing, timeouts, sysctl)

Оптимизация таблицы conntrack для Docker-хоста с высоким числом соединений:

```bash
# Проверка текущего состояния conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max

# Текущие таймауты (в секундах)
sysctl net.netfilter.nf_conntrack_tcp_timeout_established
sysctl net.netfilter.nf_conntrack_tcp_timeout_time_wait
```

```bash
# /etc/sysctl.d/99-docker-conntrack.conf
# Увеличение размера таблицы
net.netfilter.nf_conntrack_max = 1048576

# Сокращение таймаутов для высвобождения слотов быстрее
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15

# Увеличение размера hash table (рекомендуется = max / 4)
net.netfilter.nf_conntrack_buckets = 262144
```

```bash
# Применение
sudo sysctl --system

# Мониторинг в реальном времени
watch -n 1 'cat /proc/sys/net/netfilter/nf_conntrack_count /proc/sys/net/netfilter/nf_conntrack_max'

# Проверка ошибок conntrack
dmesg | grep -i conntrack
```

### Сценарий 3: Оптимизация сетевой пропускной способности (MTU, TCP buffers, BBR)

Максимизация throughput для контейнеров с высоким сетевым трафиком:

```bash
# /etc/sysctl.d/99-docker-network-performance.conf

# === MTU ===
# Увеличение MTU для jumbo frames (если сеть поддерживает)
# net.mtu.conf = 9000

# === TCP Buffer Sizes ===
# min/default/max (в байтах) для RX и TX буферов
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216

# === TCP Auto-Tuning ===
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_no_metrics_save = 1

# === Congestion Control ===
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# === TCP Keepalive ===
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_keepalive_intvl = 30
net.ipv4.tcp_keepalive_probes = 5

# === Connection Backlog ===
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
```

```bash
# Применение
sudo sysctl --system

# Проверка
sysctl net.ipv4.tcp_congestion_control
# → bbr

# Тест throughput через iperf3 в контейнере
docker run -d --name iperf-server --network host networkstatic/iperf3 -s
docker run --rm --network host networkstatic/iperf3 -c 127.0.0.1 -t 10 -P 4
```

### Сценарий 4: Оптимизация Disk I/O (scheduler selection, read-ahead)

Настройка I/O scheduler и read-ahead для оптимальной работы Docker storage:

```bash
# Проверка текущего scheduler
cat /sys/block/sda/queue/scheduler
# → [mq-deadline] kyber bfq none

# Установка scheduler для NVMe
echo none > /sys/block/nvme0n1/queue/scheduler

# Установка scheduler для SATA SSD
echo mq-deadline > /sys/block/sda/queue/scheduler

# Проверка и настройка read-ahead
blockdev --getra /dev/sda
# → 256 (sectors) = 128KB

# Увеличение read-ahead для sequential workloads (образы, pull)
blockdev --setra 4096 /dev/sda
# → 4096 sectors = 2MB

# Сохранение при перезагрузке (udev rule)
cat > /etc/udev/rules.d/60-io-scheduler.rules << 'EOF'
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/scheduler}="mq-deadline"
ACTION=="add|change", KERNEL=="sd[a-z]", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="none"
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"
EOF
```

```bash
# Мониторинг I/O в реальном времени
iostat -xz 1 5

# Проверка I/O latency для контейнера
docker run --rm -it alpine sh -c "apk add fio && \
  fio --name=test --rw=randread --bs=4k --size=100M --numjobs=1 --runtime=30 --group_reporting"
```

### Сценарий 5: CPU pinning для latency-sensitive workload

Привязка контейнера к конкретным ядрам для устранения context switch overhead:

```bash
# Определение доступных CPU и NUMA-топологии
lscpu
# → NUMA node(s):        2
# → CPU(s):              64

numactl --hardware
# → node 0 cpus: 0-31
# → node 1 cpus: 32-63
# → node 0 size: 65536 MB
# → node 1 size: 65536 MB

# Запуск контейнера с привязкой к CPU 0-3 (NUMA node 0)
docker run -d \
  --cpuset-cpus="0-3" \
  --cpus="4" \
  --memory=8g \
  --name db-postgres \
  postgres:17-alpine

# Проверка привязки изнутри контейнера
docker exec db-postgres taskset -cp 0-3
# → current affinity: 0-3

# Проверка NUMA locality
docker exec db-postgres numactl --hardware
# → Should show single node if properly bound
```

**Для NUMA-aware allocation на уровне хоста:**
```bash
# Запуск с привязкой к NUMA-ноде через numactl
numactl --cpunodebind=0 --membind=0 \
  docker run -d --name db-postgres postgres:17-alpine

# Или через systemd (для持久化)
cat > /etc/systemd/system/docker-db.service << 'EOF'
[Service]
ExecStart=/usr/bin/numactl --cpunodebind=0 --membind=0 \
  /usr/bin/docker run --rm --name db-postgres postgres:17-alpine
ExecStop=/usr/bin/docker stop db-postgres
Restart=always
EOF
```

### Сценарий 6: Настройка памяти (memory.high vs memory.max, swappiness, THP)

Оптимизация управления памятью для Docker-хостов с memory-intensive workload:

```bash
# /etc/sysctl.d/99-docker-memory.conf

# Снижение swappiness (своп используется только при absolute pressure)
vm.swappiness = 10

# Настройка watermark (в страницах, дефолты часто избыточны)
vm.watermark_boost_factor = 0
vm.watermark_scale_factor = 100

# Min free memory (в KB) — reserve для kernel
vm.min_free_kbytes = 262144

# === Transparent Huge Pages ===
# madvise: THP только если приложение использует madvise(MADV_HUGEPAGE)
#echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
# В永遠化 через sysctl:
kernel.mm.transparent_hugepage.defrag = defer+madvise
kernel.mm.transparent_hugepage.khugepaged.defrag = 0
```

**Конфигурация контейнера:**
```bash
# cgroups v2: memory.high (soft limit) vs memory.max (hard limit)
docker run -d \
  --memory=4g \
  --memory-reservation=2g \
  --memory-swap=4g \
  --name redis-cache \
  redis:7-alpine redis-server --maxmemory 3g --maxmemory-policy allkeys-lru

# Проверка cgroup limits
docker stats redis-cache --no-stream
# → MEM USAGE / LIMIT: 3.2GiB / 4GiB

# Проверка memory pressure
docker exec redis-cache cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

### Сценарий 7: Тюнинг файловой системы для Docker (XFS ftype=1, noatime)

Настройка базовой файловой системы для максимальной производительности Docker storage:

```bash
# Проверка текущей ФС
df -T /var/lib/docker
# → /dev/sda1  xfs

# Проверка ftype
xfs_info /var/lib/docker | grep ftype
# → naming   =version 2              bsize=4096   ascii-ci=0 ftype=1

# Если ftype=0 — пересоздание ФС (ВНИМАНИЕ: данные удаляются!)
sudo systemctl stop docker
sudo umount /var/lib/docker
sudo mkfs.xfs -f -n ftype=1 /dev/sda1
sudo mount /dev/sda1 /var/lib/docker
sudo systemctl start docker
```

**Монтирование с оптимальными параметрами:**
```bash
# /etc/fstab
UUID=xxxx-xxxx  /var/lib/docker  xfs  defaults,noatime,nodiratime,logbufs=8  0 0

# Параметры:
# noatime     — не обновлять atime при чтении (снижает I/O на 30-50%)
# nodiratime  — не обновлять atime для директорий
# logbufs=8   — увеличение буферов журнала (дефолт 2, макс 8)
```

**Проверка после настройки:**
```bash
# Проверка опций монтирования
mount | grep /var/lib/docker
# → /dev/sda1 on /var/lib/docker type xfs (rw,noatime,nodiratime,logbufs=8)

# Бенчмарк: сравнение before/after
fio --name=xfs-noatime --directory=/var/lib/docker/test \
    --rw=randwrite --bs=4k --size=100M --numjobs=4 --runtime=30
```

### Сценарий 8: docker stats и методология бенчмаркинга

Методология измерения и анализа производительности Docker-контейнеров:

```bash
# Базовый мониторинг всех контейнеров
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"

# Пример вывода:
# NAME          CPU %   MEM USAGE / LIMIT   MEM %   NET I/O          BLOCK I/O       PIDs
# nginx         0.05%   12MiB / 256MiB      4.69%   1.2kB / 820B     0B / 4.1kB      3
# postgres      2.30%   128MiB / 1GiB       12.5%   10.5MB / 8.2MB   52MB / 1.2GB    15
```

**Бенчмарк I/O через fio:**
```bash
# Sequential read benchmark
docker run --rm -v /tmp/fio-test:/data alpine sh -c "
  apk add --no-cache fio && \
  fio --name=seq-read --directory=/data --rw=read --bs=1M --size=512M \
      --numjobs=1 --runtime=30 --group_reporting
"

# Random write benchmark (для БД workload)
docker run --rm -v /tmp/fio-test:/data alpine sh -c "
  apk add --no-cache fio && \
  fio --name=rand-write --directory=/data --rw=randwrite --bs=4k --size=256M \
      --numjobs=4 --runtime=60 --group_reporting --fsync=1
"
```

**Бенчмарк сети через iperf3:**
```bash
# Запуск сервера
docker run -d --name iperf-srv --network host networkstatic/iperf3 -s

# Тест TCP throughput (4 потока, 30 секунд)
docker run --rm --network host networkstatic/iperf3 -c 127.0.0.1 -t 30 -P 4

# Тест UDP throughput
docker run --rm --network host networkstatic/iperf3 -c 127.0.0.1 -u -b 10G -t 10
```

**Сбор метрик через cAdvisor:**
```bash
# Запуск cAdvisor для мониторинга контейнеров
docker run -d \
  --name cadvisor \
  --volume=/:/rootfs:ro \
  --volume=/var/run:/var/run:ro \
  --volume=/sys:/sys:ro \
  --volume=/var/lib/docker/:/var/lib/docker:ro \
  --publish=8080:8080 \
  gcr.io/cadvisor/cadvisor:latest

# Доступ: http://localhost:8080
# Метрики: http://localhost:8080/metrics (Prometheus format)
```

### Сценарий 9: Production sysctl конфигурация для Docker-хостов

Полный набор sysctl-параметров для production Docker-хоста:

```bash
# /etc/sysctl.d/99-docker-production.conf

# ==========================================
# === СЕТЬ ===
# ==========================================

#_conntrack: размер таблицы и таймауты
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15

# TCP buffers и auto-tuning
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216
net.ipv4.tcp_moderate_rcvbuf = 1
net.ipv4.tcp_no_metrics_save = 1

# Congestion control (BBR)
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq

# Connection backlog
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_tw_reuse = 1

# ==========================================
# === ПАМЯТЬ ===
# ==========================================

vm.swappiness = 10
vm.min_free_kbytes = 262144
vm.watermark_boost_factor = 0
vm.overcommit_memory = 0
vm.dirty_ratio = 10
vm.dirty_background_ratio = 3

# Transparent Huge Pages
kernel.mm.transparent_hugepage.defrag = defer+madvise
kernel.mm.transparent_hugepage.khugepaged.defrag = 0

# ==========================================
# === ФАЙЛОВАЯ СИСТЕМА ===
# ==========================================

fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 8192
fs.aio-max-nr = 1048576
```

```bash
# Применение
sudo sysctl --system

# Валидация всех параметров
sysctl -a | grep -E "conntrack_max|tcp_congestion|swappiness|transparent_huge"
```

### Сценарий 10: Диагностика узких мест (PSI, cpu.stat, io.stat)

Пошаговая диагностика производительности с использованием PSI (Pressure Stall Information) и cgroup метрик:

```bash
# === PSI: общая информация о давлении ресурсов ===
cat /proc/pressure/cpu
# → some avg10=2.50 avg60=1.20 avg300=0.80 total=12345678
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# some: хотя бы один процесс ждёт CPU
# full: все процессы в cgroup ждут CPU (критично)

cat /proc/pressure/memory
# → some avg10=0.50 avg60=0.10 avg300=0.05 total=2345678
# → full avg10=0.10 avg60=0.02 avg300=0.01 total=567890

# full memory pressure > 0: процессы были вынуждены свопать или ждать освобождения памяти

cat /proc/pressure/io
# → some avg10=5.00 avg60=2.30 avg300=1.10 total=3456789
# → full avg10=2.00 avg60=0.80 avg300=0.30 total=1234567

# full io pressure > 0: процессы заблокированы на I/O операциях
```

```bash
# === CPU: мониторинг конкретного контейнера ===
# Определение cgroup path (cgroups v2)
CONTAINER_ID=$(docker inspect --format '{{.Id}}' my-container)

# Путь к cpu.stat
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/cpu.stat
# → usage_usec 123456789
# → user_usec 98765432
# → system_usec 24691357
# → nr_periods 12345
# → nr_throttled 123
# → throttled_usec 5678901

# nr_throttled > 0: контейнер был ограничен по CPU (throttled)
# throttled_usec: суммарное время в микросекундах, когда контейнер был throttled
```

```bash
# === IO: мониторинг I/O контейнера ===
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/io.stat
# → 8:0 rbytes=123456789 wbytes=987654321 rios=12345 wios=67890

# rbytes/wbytes: байты чтения/записи
# rios/wios: количество операций чтения/записи
```

```bash
# === Быстрая эвристика ===
# 1. Проверка overall system load
uptime
# → load average: 2.50 1.80 1.20

# 2. Проверка I/O wait
vmstat 1 5
# → id  wa
# → 85  15   (15% I/O wait — проблема!)

# 3. Поиск процессов с highest I/O
iotop -oP -d 1 -n 5

# 4. Проверка swap usage
free -h
# → Swap: 8.0GiB  2.1GiB  5.9GiB  (swap используется → memory pressure)

# 5. Проверка контейнеров с highest memory usage
docker stats --no-stream --format "table {{.Name}}\t{{.MemPerc}}" | sort -k2 -rn
```

## Дополнительная информация

### Связанные документы

- **[docker_overlayfs.md](Docker_fs/docker_overlayfs.md)** — устройство и оптимизация overlay2 storage driver
- **[docker_daemon_config.md](docker_daemon_config.md)** — конфигурация Docker daemon, storage, networking
- **[resource_limits.md](Docker_security/resource_limits.md)** — ограничения ресурсов контейнеров (CPU, memory, I/O)
- **[network_connectivity_issues.md](Docker_troubleshooting/network_connectivity_issues.md)** — диагностика сетевых проблем Docker
- **[linux_isolation.md](../Linux/Core/processes/basic_concepts.md)** — namespaces, cgroups, изоляция контейнеров

### Методология baseline

Перед оптимизацией необходимо зафиксировать baseline текущей производительности:

```bash
# 1. Снимок системы до нагрузки
echo "=== BASELINE $(date) ===" > /tmp/perf-baseline.txt
uptime >> /tmp/perf-baseline.txt
free -h >> /tmp/perf-baseline.txt
cat /proc/cpuinfo | grep "model name" | head -1 >> /tmp/perf-baseline.txt
df -h /var/lib/docker >> /tmp/perf-baseline.txt

# 2. Метрики Docker
docker stats --no-stream >> /tmp/perf-baseline.txt

# 3. sysctl
sysctl -a >> /tmp/perf-baseline.txt

# 4. После изменений — повторить и сравнить
```

**Рекомендуемые инструменты для мониторинга:**
- **Prometheus + cAdvisor**: автоматический сбор метрик контейнеров
- **Grafana**: визуализация метрик в реальном времени
- **node_exporter**: системные метрики хоста
- **perf**: профилирование на уровне ядра (CPU cycles, cache misses)
- **bpftrace/eBPF**: трассировка I/O и syscall в реальном времени

### Типичные антипаттерны

| Антипаттерн | Проблема | Решение |
|:---|:---|:---|
| Хранение БД в writable layer | CoW overhead на каждую запись, замедление при copy-up | Named volume: `docker run -v pgdata:/var/lib/postgresql/data` |
| `--cpus` без `--cpuset-cpus` | Контейнер прыгает между ядрами, cache thrashing | Пиннинг: `--cpuset-cpus="0-3"` для latency-sensitive |
| Deфолтный conntrack max (262144) | Table full при 10K+ контейнеров | `nf_conntrack_max=1048576` + оптимизация таймаутов |
| `userland-proxy: true` в production | Extra process per port, higher latency, more memory | `userland-proxy: false` → iptables DNAT |
| swappiness=60 (дефолт) | Агрессивное свопание Page Cache | `vm.swappiness=10` |
| Bind mount для данных БД | Нет isolation, проблемы с правами, нет драйверов | Named volume с драйвером storage |
| MTU mismatch при VPN | Фрагментация, потеря пакетов, таймауты | Синхронизация MTU: `ping -M do -s 1472` |
| THP=always для БД | Latency spikes при khugepaged defrag | `THP=madvise`, отключение для specific workload |
| `docker stats` как единственный инструмент | Мгновенный снимок, нет истории | Prometheus + cAdvisor + Grafana |

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `nf_conntrack: table full, dropping packet` | Исчерпание таблицы conntrack | Увеличить `nf_conntrack_max`, сократить таймауты |
| `too many open files` | Исчерпание ulimit для контейнеров | `--ulimit nofile=65536:65536` + `fs.file-max` в sysctl |
| `CPU throttled` в docker stats | `--cpu-quota` / `--cpu-period` слишком агрессивные | Увеличить quota или использовать `--cpus` (проще) |
| `Cannot allocate memory` | OOM killer завершает контейнеры | Проверить `--memory` лимит, увеличить или оптимизировать usage |
| Высокий `iowait` в `top` | Дисковое узкое место (scheduler, диск) | Проверить scheduler, увеличить read-ahead, проверить disk health |
| `RPC timeout` при `docker pull` | Недостаточная сеть или DNS | Проверить MTU, DNS, TCP buffers, conntrack |
| Page cache thrashing | `memory.max` меньше working set приложения | Увеличить `--memory`, использовать `--memory-reservation` |
| Clipboard пуст после копирования в контейнер | CoW + hard links при copy-up | Использовать volumes вместо bind mounts для данных |
| Медленный `docker build` на macOS | Bind mount через HyperKit/WSL2 | Использовать named volumes для build context, BuildKit cache mounts |
| `device-mapper: thin pool has auto not enabled` | Устаревший storage driver device-mapper | Перейти на overlay2 (рекомендуется Docker 20.10+) |

### Быстрый старт: минимальная production-конфигурация

Для нового Docker-хоста начните с этого минимума:

```bash
# 1. sysctl для production
cat > /etc/sysctl.d/99-docker-minimum.conf << 'EOF'
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.ipv4.tcp_congestion_control = bbr
net.core.default_qdisc = fq
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
vm.swappiness = 10
EOF
sudo sysctl --system

# 2. daemon.json
cat > /etc/docker/daemon.json << 'EOF'
{
  "storage-driver": "overlay2",
  "userland-proxy": false,
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  },
  "live-restore": true
}
EOF
sudo systemctl restart docker

# 3. Валидация
docker info | grep -E "Storage|Logging|Live Restore"
sysctl net.ipv4.tcp_congestion_control
cat /proc/sys/net/netfilter/nf_conntrack_max
```
