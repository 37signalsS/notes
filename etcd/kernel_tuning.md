# Ядерные параметры и тюнинг ОС для etcd

**Актуально для:** etcd 3.5.x / 3.6.x / 3.7.x (официальная tuning-документация etcd идентична для всех трёх линий)

**etcd** чрезвычайно чувствителен к задержкам диска, сети и планировщику процессов. Официальная документация etcd (Tuning, Hardware recommendations) предписывает конкретные меры: настройку heartbeat/election, приоритет диска через `ionice`, приоритизацию peer-трафика через `tc` и CPU governor в режим `performance`. Прочие параметры ниже — общая практика Linux для latency-нагруженных хранилищ и помечены как таковые.

## Определения

| Термин | Описание |
| :--- | :--- |
| **sysctl** | Утилита для настройки параметров ядра Linux во время выполнения (`/proc/sys/`). |
| **ionice** | Утилита для установки приоритета I/O-операций. Классы: `1` — realtime, `2` — best-effort, `3` — idle. |
| **nice** | Утилита для изменения приоритета CPU-планировщика (от -20 до 19). |
| **CPU Governor** | Политика управления частотой CPU. `performance` — фиксированная высокая частота; `conservative` — адаптивная с малым джиттером. |
| **isolcpus** | Параметр ядра для выделения CPU-ядер под конкретные процессы. |
| **vm.swappiness** | Склонность ядра перемещать страницы в swap (0–100). |
| **net.core.somaxconn** | Максимальная длина очереди ожидающих TCP-соединений (backlog). |
| **LimitNOFILE** | Максимальное количество файловых дескрипторов для процесса (systemd). |
| **Heartbeat Interval** | Частота, с которой лидер уведомляет followers о своём статусе. Default: 100 мс. |
| **Election Timeout** | Время без heartbeat, после которого follower инициирует выборы. Default: 1000 мс. |
| **RTT** | Round-trip time — время кругового обмена между членами кластера. |
| **Sequential IOPS** | Количество последовательных операций ввода-вывода в секунду (ключевой параметр для etcd). |
| **Traffic control (tc)** | Механизм ядра Linux для приоритизации/шейпинга сетевого трафика (qdisc). |
| **snapshot-count** | Число изменений между снапшотами (default: 10 000 в etcd 3.6+, 100 000 в 3.5). |

---

## Основные концепции

### Time parameters (heartbeat / election) — официальная рекомендация

Официальная tuning-документация etcd задаёт правила настройки таймеров:

- **Heartbeat interval** — около **0.5–1.5 × RTT** между членами кластера (default 100 мс). Слишком малое значение — лишний трафик и нагрузка на CPU/сеть; слишком большое — замедленное обнаружение отказа лидера.
- **Election timeout** — **не менее 10 × RTT** (default 1000 мс), чтобы компенсировать джиттер сети. Верхний предел — **50 000 мс (50 с)**, только для глобально-распределённых кластеров.
- Значения **должны быть одинаковыми для всех членов** кластера — разные значения дестабилизируют кластер.

```bash
# Command line arguments:
$ etcd --heartbeat-interval=100 --election-timeout=500

# Environment variables:
$ ETCD_HEARTBEAT_INTERVAL=100 ETCD_ELECTION_TIMEOUT=500 etcd
```

Значения указываются в миллисекундах. Теория выборов и влияние таймеров на стабильность — в **[Алгоритм консенсуса Raft](./raft_consensus.md)**.

### sysctl параметры

> **Примечание:** официальная tuning-документация etcd **не предписывает** значений sysctl. Параметры ниже — общая практика Linux для latency-нагруженных хранилищ.

```bash
# /etc/sysctl.d/99-etcd.conf
# Защита от swap: etcd не должен попадать в swap (WAL-страницы вызывают джиттер fdatasync)
vm.swappiness = 0

# Backlog для listen(): совпадает с default ядер Linux >= 4.3; на старых ядрах (default 128) поднимает очередь
net.core.somaxconn = 4096
```

**Применение:**
```bash
sysctl --system
```

**Что не рекомендуется (дефекты, удалённые из прежней версии файла):**
- `net.ipv4.tcp_sack = 0` — отключение SACK ухудшает восстановление при потерях пакетов; вредно для etcd.
- `net.ipv4.tcp_rmem` / `tcp_wmem` с значениями `4096 87380 ...` — устаревшие default (современные ядра используют 131072); etcd-специфичной выгоды нет.
- `net.core.netdev_max_backlog`, `net.ipv4.tcp_fin_timeout` — общая сетевая настройка, не специфична для etcd.

### Приоритеты процессов (ionice + nice)

Официальная рекомендация etcd — высокий приоритет диска через `ionice` в классе **best-effort**:

```bash
# best effort, highest priority (официальная документация etcd)
$ sudo ionice -c2 -n0 -p `pgrep etcd`
```

**Почему не realtime (`-c1`):** класс realtime требует `CAP_SYS_NICE` и может полностью голодить остальные процессы узла; etcd-кластеру достаточно highest priority внутри best-effort.

Дополнительная мера (не из официальных доков) — приоритет CPU:
```bash
nice -n -10 etcd --config-file /etc/etcd/etcd.conf.yml
```

**В systemd-юните:**
```ini
[Service]
ExecStart=
ExecStart=/usr/bin/etcd --config-file /etc/etcd/etcd.conf.yml
Nice=-10
IOSchedulingClass=best-effort
IOSchedulingPriority=0
```

**Обоснование:**
- `nice=-10` — высокий приоритет CPU (etcd обрабатывает Protobuf и Raft).
- `ionice -c2 -n0` — highest priority в best-effort-классе (WAL fsync не прерывается фоновыми процессами).

### CPU Governor

Официальная рекомендация: режим `performance` **или** `conservative` (оба допустимы; `performance` исключает джиттер переключений частоты):

```bash
# Установить performance governor
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Или через cpupower
cpupower frequency-set -g performance
```

**Обоснование:** transition между частотами CPU добавляет джиттер к обработке heartbeats. В production используется фиксированная высокая частота.

### CPU Isolation (isolcpus)

Для критически важных ядер используйте параметры загрузки `isolcpus`, `nohz_full` и `rcu_nocbs`. Детальная настройка и обоснование приведены в **[Изоляция CPU](../../Linux/Core/kernel/cpu_isolation.md)**.

### Приоритизация peer-трафика (tc) — официальная рекомендация

Если лидер обслуживает много клиентских соединений, он может задерживать peer-запросы followers из-за сетевой перегрузки. Симптом на follower'ах:

```
dropped MsgProp to 247ae21ff9436b2d since streamMsg's sending buffer is full
dropped MsgAppResp to 247ae21ff9436b2d since streamMsg's sending buffer is full
```

Официальное решение — приоритизация peer-трафика (порт 2380) над клиентским (2379) через traffic control:

```bash
# eth0 заменить на реальный интерфейс peer-сети
tc qdisc add dev eth0 root handle 1: prio bands 3
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip sport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip dport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip sport 2379 0xffff flowid 1:2
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip dport 2379 0xffff flowid 1:2
```

**Откат:**
```bash
tc qdisc del dev eth0 root
```

### Лимиты файловых дескрипторов

etcd сам мониторит использование дескрипторов (`/proc/self/fd`) и предупреждает при **80% лимита**:

```
etcdserver: 80% of the file descriptor limit is used [used = 974, limit = 1024]
```

При исчерпании лимита новые клиентские соединения закрываются сразу после accept:

```
transport: accept error: closing connection, exceed file descriptor usage limitation (fd limit=874)
```

**Sizing:** etcd резервирует ~150 fd для внутренних нужд; остальное — клиентские соединения, Watch-стримы и peer-соединения. Лимит определяется ожидаемым числом клиентов и watchers, а не фиксированной нормой. Распространённое production-значение — **65536**:

```ini
# /etc/systemd/system/etcd.service.d/limits.conf
[Service]
LimitNOFILE=65536
```

```bash
# Проверить действующий лимит процесса (не системы!)
cat /proc/$(pgrep etcd)/limits | grep "open files"
# → Max open files            65536                65536                files
```

**Важно:** лимит — **per-process**. Системный `ulimit` или `/etc/security/limits.conf` не помогут, если юнит systemd задаёт меньший лимит (процесс наследует лимит от systemd).

### Выделенный диск для WAL

Для минимальной задержки `fdatasync` размещайте WAL на отдельном физическом диске:

```bash
# Структура дисков
/dev/nvme0n1 → ОС + docker/containerd
/dev/nvme1n1 → /var/lib/etcd/wal (только WAL)
/dev/nvme2n1 → /var/lib/etcd/member (данные + снапшоты)
```

Или через символические ссылки:
```bash
mv /var/lib/etcd/member/wal /var/lib/etcd/wal
ln -s /var/lib/etcd/wal /var/lib/etcd/member/wal
```

**Официальные критерии «достаточно быстрого» диска** (Hardware recommendations):
- **50 sequential IOPS** — типичное требование (диск 7200 RPM);
- **500 sequential IOPS** — для нагруженных кластеров (локальный SSD);
- **10 MB/s** — восстановление 100 MB за 15 с; **100 MB/s+** — для больших кластеров (1 GB за 15 с).

Замер — утилитами `fio` или `diskbench`. Обратите внимание: провайдеры виртуализации часто публикуют **concurrent** IOPS, которые могут быть в 10× выше **sequential** — замеряйте последовательные. Аппаратные требования целиком — в **[Архитектура и основные концепции](./architecture-and-concepts.md)**.

---

## Практические сценарии

### Полная настройка нового узла etcd

```bash
# 1. sysctl
cat <<EOF > /etc/sysctl.d/99-etcd.conf
vm.swappiness = 0
net.core.somaxconn = 4096
EOF
sysctl --system

# 2. CPU governor
echo performance | tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# 3. systemd limits и приоритеты
mkdir -p /etc/systemd/system/etcd.service.d
cat <<EOF > /etc/systemd/system/etcd.service.d/limits.conf
[Service]
LimitNOFILE=65536
Nice=-10
IOSchedulingClass=best-effort
IOSchedulingPriority=0
EOF
systemctl daemon-reload

# 4. Проверка
systemctl show etcd | grep -E "Nice|IOScheduling|LimitNOFILE"
cat /proc/$(pgrep etcd)/limits | grep "open files"
```

### Приоритизация peer-трафика через tc

```bash
# Установить (см. раздел «Приоритизация peer-трафика»)
tc qdisc add dev eth0 root handle 1: prio bands 3
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip sport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 1 u32 match ip dport 2380 0xffff flowid 1:1
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip sport 2379 0xffff flowid 1:2
tc filter add dev eth0 parent 1: protocol ip prio 2 u32 match ip dport 2379 0xffff flowid 1:2

# Проверка: правила видны в выводе
tc qdisc show dev eth0
tc filter show dev eth0

# Откат
tc qdisc del dev eth0 root
```

### Мониторинг эффективности тюнинга

```bash
# Задержка fdatasync (должна быть < 1 ms p99)
curl -s http://localhost:2379/metrics | grep etcd_disk_wal_fsync_duration_seconds

# Использование файловых дескрипторов (предупреждение etcd при 80% лимита)
curl -s http://localhost:2379/metrics | grep process_open_fds

# Использование CPU
mpstat -P ALL 1 5

# Ожидание I/O
iostat -x 1 5

# Context switches
pidstat -w -p $(pgrep etcd) 1
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `fdatasync` > 10 ms | Диск не NVMe, governor ondemand, или high iowait | Перейти на NVMe; установить `performance` governor; проверить `iostat` |
| `dropped MsgProp/MsgAppResp ... sending buffer is full` | Сетевая перегрузка: клиентский трафик вытесняет peer | Приоритизация peer-трафика через `tc` (см. выше) |
| `80% of the file descriptor limit is used` | Лимит дескрипторов близок к исчерпанию | Увеличить `LimitNOFILE`; пересчитать по числу клиентов/watchers |
| `Too many open files` | `LimitNOFILE` слишком мал | Увеличить до 65536; проверить лимит процесса (`/proc/PID/limits`), а не системы |
| Высокий `%iowait` | Другие процессы конкурируют за диск | `ionice` для etcd; выделить отдельный диск |
| Лидер flapping | Сетевой джиттер + CPU throttling | Увеличить `election-timeout` (≥ 10 × RTT); выделить CPU через `isolcpus` |
| Высокий `cs` (context switches) | Много процессов на узле | Выделить отдельные ядра для etcd через `isolcpus` |

---

## Best Practices

- **Таймеры по официальным правилам:** heartbeat ≈ 0.5–1.5 × RTT, election timeout ≥ 10 × RTT, одинаковые на всех членах.
- **`LimitNOFILE=65536`:** распространённое production-значение; итоговый лимит — от ожидаемого числа клиентов и watchers.
- **Отдельный диск для WAL:** минимизирует задержку `fdatasync`.
- **`vm.swappiness = 0`:** etcd не должен попадать в swap.
- **Performance governor:** фиксированная частота CPU исключает джиттер.
- **ionice best-effort highest priority:** гарантирует приоритет etcd при общей нагрузке на узел (официальная рекомендация).
- **tc для peer-трафика:** при большом числе клиентских соединений peer-трафик (2380) должен иметь приоритет над клиентским (2379).
- **Замеряйте диск перед развёртыванием:** `fio`/`diskbench` — sequential IOPS и bandwidth, а не маркетинговые concurrent IOPS.

---

## Edge Cases

- **Container runtime:** если etcd запущен в контейнере, убедитесь, что контейнер имеет права `SYS_NICE` (для nice/ionice) и `CAP_SYS_RESOURCE` (для realtime-класса I/O); лимит дескрипторов задаётся в securityContext/юните, а не в хост-системе.
- **Virtualization:** в виртуализированных средах (ESXi, KVM) CPU Governor настраивается на host level, а не только внутри VM.
- **Burst-CPU:** в средах с burst-кредитами CPU проверьте лимиты sustained-производительности. etcd требует стабильной производительности, а не burst.
- **NUMA:** для multi-socket серверов размещайте etcd (и особенно WAL) на NUMA-ноде, соответствующей CPU-ядрам.
- **Старые ядра (< 4.3):** default `somaxconn` = 128 — параметр из сценария настройки обязателен; на современных ядрах он совпадает с default.
- **Глобально-распределённые кластеры:** election timeout до 50 000 мс допустим только при RTT ~5 с; для локальных сетей такие значения маскируют реальные проблемы.

---

## См. также

* **[Алгоритм консенсуса Raft](./raft_consensus.md)** — влияние heartbeat/election на выборы лидера.
* **[Архитектура и основные концепции](./architecture-and-concepts.md)** — аппаратные требования.
* **[Тестирование производительности](./benchmarking.md)** — замер fdatasync и IOPS.
* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — systemd и Static Pod.
* **[Изоляция CPU](../../Linux/Core/kernel/cpu_isolation.md)** — isolcpus, nohz_full, rcu_nocbs.
* **[sysctl](../../Linux/Core/kernel/sysctl.md)** — параметры ядра Linux.
