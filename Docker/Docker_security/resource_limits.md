# Ограничение ресурсов контейнеров — Deep Dive

## Определения

**Ограничение ресурсов (Resource Limits)** — механизм изоляции контейнеров, реализованный через **cgroups (Control Groups)** ядра Linux. Позволяет установить верхние границы потребления CPU, оперативной памяти, дискового I/O и количества процессов для каждого контейнера. Предотвращает ситуацию, когда один контейнер забирает ресурсы у других (neighbors) или хоста.

**Cgroups v2** — современная версия подсистемы управления ресурсами ядра Linux (дефолт с ядра 4.5, рекомендуется с 5.10+). В отличие от v1, предоставляет иерархическую модель с единым деревом контроля, что исключает конфликты между подсистемами. Docker поддерживает обе версии.

**CPU Throttling** — механизм ядра, ограничивающий время выполнения на CPU. При превышении лимита процесс приостанавливается до конца текущего периода CFS (Completely Fair Scheduler). Мониторинг: `cpu.stat` → `nr_throttled`, `throttled_usec`.

**OOM Killer (Out-Of-Memory Killer)** — подсистема ядра, убивающая процесс при нехватке оперативной памяти. В Docker: `memory.events` → `oom_kill` counter. Exit code контейнера: `137`.

**PSI (Pressure Stall Information)** — подсистема ядра (≥4.20), измеряющая реальное давление на ресурсы (CPU, memory, I/O). Значения `some` и `full` в процентах за интервал времени.

## Базовые концепции

### Архитектура ограничений

Docker передаёт параметры ресурсов демону, который создаёт соответствующие cgroups для каждого контейнера. Путь к cgroup:

```
# Cgroups v2 (единое дерево)
/sys/fs/cgroup/system.slice/docker-<container_id>.scope/

# Ключевые файлы:
cpu.max        # CFS bandwidth (quota/period)
cpu.stat       # Статистика: usage_usec, nr_throttled, throttled_usec
cpu.weight     # Вес для пропорционального распределения (дефолт: 100)
memory.max     # Хард-лимит памяти (байты или "max")
memory.high    # Софт-лимит памяти (throttling перед OOM)
memory.current # Текущее потребление
memory.events  # Счётчики: low, high, max, oom, oom_kill
io.max         # I/O limits по устройствам
io.weight      # Вес I/O
pids.max       # Максимальное количество процессов
```

### Иерархия приоритетов

Ограничения ресурсов применяются в порядке:

```
daemon.json (глобально) → docker run (контейнер) → docker update (динамически)
```

Динамическое изменение без перезапуска:
```bash
docker update --memory 1g --cpus 2.0 <container>
```

### Типы лимитов

| Ресурс | Хард-лимит | Софт-лимит | Эффект |
|--------|-----------|------------|--------|
| CPU | `--cpus`, `--cpu-quota` | `--cpu-shares` | Throttling при превышении |
| Memory | `--memory` (`memory.max`) | `--memory-high` (`memory.high`) | Throttling → OOM Kill |
| I/O | `--device-read-bps`, `--device-write-bps` | `--blkio-weight` | Throttling I/O операций |
| Processes | `--pids-limit` | — | Fork bomb protection |

## Практические сценарии

### 1. CPU Limits — `--cpus`

Ограничение максимального потребления CPU. Значение — доля ядра (2.0 = 2 ядра):

```bash
docker run -d --cpus="1.5" nginx
```

Эквивалент в cgroups v2:
```bash
# 1.5 ядра = 150000/100000 (quota/period)
echo "150000 100000" > /sys/fs/cgroup/.../cpu.max
```

**Как это работает:**
- Docker устанавливает CFS bandwidth control: `quota` (микросекунды) и `period` (дефолт: 100000 = 100ms)
- `--cpus=1.5` → quota = 150000, period = 100000
- Процесс может работать 150ms из каждых 100ms (то есть использовать 1.5 ядра)
- При превышении: процесс **throttled** (приостановлен)

**Диагностика throttling:**
```bash
# Проверка статистики
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/cpu.stat
# usage_usec 123456789    # общее время на CPU
# nr_throttled 42         # количество throttling-событий
# throttled_usec 567890   # общее время в throttling

# Docker CLI
docker stats <container> --no-stream
# CPU% показывает потребление, но НЕ показывает throttling
```

**Ссылка:** [CPU Throttling](Dockerfile/Docker_best_practices/container_execution.md), [Native Metrics](Docker_metrics/docker_native_metrics.md)

### 2. CPU Weight — `--cpu-shares`

Пропорциональное распределение CPU между контейнерами. Дефолтное значение: 1024.

```bash
# Контейнер A получит в 2 раза больше CPU чем B при конкуренции
docker run -d --cpu-shares=2048 --name heavy myapp
docker run -d --cpu-shares=1024 --name light myapp
```

**Отличие от `--cpus`:**
- `--cpus` = хард-лимит (绝对不会 превысить)
- `--cpu-shares` = вес при конкуренции (если CPU свободен, ограничение не действует)

**В cgroups v2:**
```bash
echo 200 > /sys/fs/cgroup/.../cpu.weight  # дефолт: 100
```

**Когда использовать:**
- Смешанные рабочие нагрузки (web + worker на одном хосте)
- Приоритизация:ritical сервисов над фоновыми

### 3. CPU Pinning — `--cpuset-cpus`

Привязка контейнера к конкретным CPU-ядрам:

```bash
# Привязка к ядрам 0 и 2
docker run -d --cpuset-cpus="0,2" nginx

# Диапазон ядер
docker run -d --cpuset-cpus="0-3" nginx
```

**Зачем:**
- Предсказуемая производительность (избежание context switching)
- NUMA-оптимизация (ядра на одном NUMA-узле)
- Изоляция latency-sensitive контейнеров

**NUMA-привязка:**
```bash
# Привязка к NUMA-узлу 0
docker run -d --cpuset-cpus="0-7" --cpuset-mems="0" nginx
```

**Проверка:**
```bash
# Какие ядра доступны контейнеру
cat /sys/fs/cgroup/.../cpuset.cpus.effective
# Какие NUMA-узлы
numactl --hardware
```

### 4. CPU Period и Quota — `--cpu-period` / `--cpu-quota`

Низкоуровневая настройка CFS bandwidth control:

```bash
# period=100ms, quota=50ms → 50% одного ядра
docker run -d --cpu-period=100000 --cpu-quota=50000 nginx

# period=100ms, quota=200ms → 2 ядра
docker run -d --cpu-period=100000 --cpu-quota=200000 nginx
```

**Формула:** `CPU cores = quota / period`

| period | quota | CPU cores |
|--------|-------|-----------|
| 100000 | 100000 | 1.0 |
| 100000 | 200000 | 2.0 |
| 100000 | 50000 | 0.5 |

**Когда использовать вместо `--cpus`:**
- Нестандартная granularity (период ≠ 100ms)
- Совместное использование с scheduler policies
- Рекомендация: используйте `--cpus` если нет специфических требований

### 5. Memory Limits — `--memory`

Хард-лимит памяти. При превышении — OOM Kill:

```bash
# 512 МБ
docker run -d --memory=512m nginx

# 2 ГБ
docker run -d --memory=2g nginx
```

**Эквивалент в cgroups v2:**
```bash
echo "536870912" > /sys/fs/cgroup/.../memory.max  # 512MB в байтах
```

**Диагностика:**
```bash
# Текущее потребление
cat /sys/fs/cgroup/.../memory.current
# Лимит
cat /sys/fs/cgroup/.../memory.max
# События
cat /sys/fs/cgroup/.../memory.events
# low 0        # сколько раз сработал memory.high
# high 0       # сколько раз был throttled
# max 1        # сколько раз достигнут memory.max
# oom 0        # сколько раз вызван OOM killer
# oom_kill 1   # сколько процессов убито
```

**Exit code 137 без логов** — классический признак OOM:
```bash
docker inspect <container> --format '{{.State.OOMKilled}}'
# true
```

**Ссылка:** [Linux Isolation](Concepts/linux_isolation.md), [Exit Codes](Docker_troubleshooting/docker_exit_codes.md)

### 6. Memory High vs Memory Max

Софт-лимит (`memory.high`) вызывает throttling, хард-лимит (`memory.max`) — OOM Kill:

```bash
# memory.high = 400MB (throttling), memory.max = 512MB (OOM)
docker run -d --memory=512m --memory-high=400m nginx
```

**Рекомендация:** `memory.high` = 80% от `memory.max`

| memory.high | memory.max | Поведение |
|-------------|-----------|-----------|
| 400m | 512m | При 400MB: throttling. При 512MB: OOM Kill |
| — | 512m | Нет throttling, сразу OOM Kill при превышении |
| 512m | 512m | memory.high = memory.max: throttling+Kill одновременно |

**Зачем нужен `memory.high`:**
- Раннее предупреждение (throttling) перед катастрофой (OOM Kill)
- Даёт время приложению освободить память (GC, cache eviction)
- Мониторинг через `memory.events` → `high` counter

### 7. Memory Swap — `--memory-swap` / `--memory-swappiness`

Управление использованием swap для контейнера:

```bash
# Запрет swap (memory + swap = memory)
docker run -d --memory=512m --memory-swap=512m nginx

# Разрешить swap до 1GB (memory=512m + swap=512m)
docker run -d --memory=512m --memory-swap=1g nginx

# Отключить swappiness (использовать swap только при memory.max)
docker run -d --memory=512m --memory-swappiness=0 nginx
```

**Формула `--memory-swap`:**
- `--memory-swap` = `--memory` + swap
- `--memory-swap=-1` → без ограничений swap
- `--memory-swap` < `--memory` → ошибка

**`--memory-swappiness` (0-100):**
- `0` — swap только при memory.max (отложенный kill)
- `60` — дефолт Linux
- `100` — агрессивный swap

**Рекомендация:** `--memory-swap=--memory` (отключить swap) для предсказуемой производительности.

### 8. I/O Limits — `--device-read-bps` / `--device-write-bps`

Ограничение пропускной способности диска:

```bash
# Ограничить чтение на /dev/sda до 10 МБ/с
docker run -d --device-read-bps=/dev/sda:10m nginx

# Ограничить запись на /dev/sda до 5 МБ/с
docker run -d --device-write-bps=/dev/sda:5m nginx

# Ограничить IOPS
docker run -d --device-read-iops=/dev/sda:1000 nginx
docker run -d --device-write-iops=/dev/sda:500 nginx
```

**Диагностика I/O:**
```bash
# Текущие I/O limits
cat /sys/fs/cgroup/.../io.max
# MAJ:MIN rbps=10485760 wbps=5242880 riops=1000 wiops=500

# Статистика I/O
cat /sys/fs/cgroup/.../io.stat
# MAJ:MIN rbytes=1234567 wbytes=98765432 rios=100 wios=200 dbytes=0 dios=0

# Время ожидания I/O
cat /sys/fs/cgroup/.../io.pressure
```

**Когда использовать:**
- Multi-tenant среда (один хост, несколько сервисов)
- Защита от "noisy neighbor" (один контейнер засирает диск)
- Базы данных с предсказуемым I/O паттерном

### 9. I/O Weight — `--blkio-weight`

Пропорциональное распределение I/O между контейнерами:

```bash
# Вес от 10 до 1000 (дефолт: 500)
docker run -d --blkio-weight=300 nginx      # низкий приоритет
docker run -d --blkio-weight=700 postgres   # высокий приоритет
```

**cgroups v2 эквивалент:**
```bash
echo 200 > /sys/fs/cgroup/.../io.weight  # дефолт: 100
```

**`--blkio-weight-device`:**
```bash
docker run -d --blkio-weight-device=/dev/sda:300 nginx
```

### 10. Process Limits — `--pids-limit`

Ограничение количества процессов (защита от fork bomb):

```bash
# Максимум 200 процессов
docker run -d --pids-limit=200 nginx

# Проверка
docker inspect <container> --format '{{.HostConfig.PidsLimit}}'
```

**cgroups v2:**
```bash
echo 200 > /sys/fs/cgroup/.../pids.max
```

**Рекомендации по значениям:**

| Приложение | Рекомендуемый `pids-limit` |
|------------|---------------------------|
| Nginx / простой web | 100-200 |
| Node.js (с воркерами) | 200-500 |
| Java (много потоков) | 500-1000 |
| Go (goroutines) | 300-800 |
| Production (без ограничений) | `--pids-limit=-1` (не рекомендуется) |

**Fork bomb в контейнере:**
```bash
# Без pids-limit
docker run --rm alpine sh -c ":(){ :|:& };:"
# → system freeze, host potentially affected

# С pids-limit
docker run --rm --pids-limit=100 alpine sh -c ":(){ :|:& };:"
# → -bash: fork: Cannot allocate memory
```

### 11. Ulimits — `--ulimit`

Настройка лимитов ядра для контейнера:

```bash
# Максимум открытых файлов
docker run -d --ulimit nofile=1024:2048 nginx

# Максимум процессов
docker run -d --ulimit nproc=512:1024 nginx

# Запрет core dumps
docker run -d --ulimit core=0:0 nginx

# Блокировка памяти (для БД)
docker run -d --ulimit memlock=-1:-1 postgres
```

**Формат:** `--ulimit <type>=<soft>:<hard>`

| Тип | Описание | Дефолт |
|-----|----------|--------|
| `nofile` | Макс. открытых файлов | 1024:1048576 |
| `nproc` | Макс. процессов | unlimited |
| `core` | Размер core dump | 0:0 |
| `memlock` | Блокировка памяти (mlock) | 64KB:64KB |
| `stack` | Размер стека | 8MB:unlimited |
| `fsize` | Макс. размер файла | unlimited |

**Типичные проблемы:**
- `too many open files` → увеличить `nofile`
- `cannot allocate memory` для БД → `memlock=-1:-1`
- Java: `Unable to create native thread` → увеличить `nproc`

**Ссылка:** [Docker Compose Directives](Docker_compose/docker_compose_directives.md), [Container Hardening](Docker_security/container_hardening.md)

### 12. OOM Behavior — `--oom-kill-disable` / `--oom-score-adj`

Управление поведением OOM killer:

```bash
# Отключить OOM killer (опасно!)
docker run -d --memory=512m --oom-kill-disable nginx

# Настроить приоритет OOM
docker run -d --memory=512m --oom-score-adj=-500 nginx
```

**`--oom-kill-disable`:**
- Отключает OOM killer для контейнера
- **Опасно**: контейнер может потребить всю память хоста и убить другие контейнеры
- Использовать **только** с `--memory` (хард-лимит обязателен!)
- В cgroups v2: `oom.group = 1` (убить всю группу, а не отдельный процесс)

**`--oom-score-adj` (-1000 до 1000):**
- `-1000` — максимальная защита от OOM (последний кандидат на kill)
- `1000` — максимальный приоритет для OOM kill (первый кандидат)
- Дефолт: 0

**Рекомендация:** Не используйте `--oom-kill-disable` без крайней необходимости. Вместо этого настройте `memory.high` для throttling и мониторьте `memory.events`.

### 13. Docker Update — динамическое изменение лимитов

Изменение ресурсов без перезапуска контейнера:

```bash
# Увеличить память до 1GB
docker update --memory=1g <container>

# Увеличить CPU до 3 ядер
docker update --cpus=3.0 <container>

# Установить все лимиты сразу
docker update \
  --memory=2g \
  --memory-swap=2g \
  --cpus=2.0 \
  --pids-limit=500 \
  <container>
```

**Ограничения:**
- `--memory` можно только увеличить (уменьшение требует перезапуска)
- `--cpus` можно менять свободно
- `--device-read-bps` / `--device-write-bps` — динамически
- Применяется мгновенно, без даунтайма

### 14. Compose Resource Limits

Настройка ресурсов в Docker Compose:

```yaml
services:
  web:
    image: nginx
    deploy:
      resources:
        limits:
          cpus: "1.5"
          memory: 512M
        reservations:
          cpus: "0.5"
          memory: 256M
    ulimits:
      nofile: 1024:2048
      nproc: 512

  db:
    image: postgres
    deploy:
      resources:
        limits:
          memory: 2G
    # Compose v3 (без deploy)
    mem_limit: 2g
    cpus: 2.0
```

**Compose v2 vs v3:**
- `deploy.resources.limits` — Swarm mode / Compose v3
- `mem_limit`, `cpus` — Compose v2 (без deploy)

**Ссылка:** [Compose Directives](Docker_compose/docker_compose_directives.md)

## Дополнительная информация

**Мониторинг ресурсов:**
```bash
# Текущее потребление всех контейнеров
docker stats --no-stream

# Детальная статистика по контейнеру
docker stats <container> --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"

# cgroup файлы (cgroups v2)
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/cpu.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/io.max
```

**PSI (Pressure Stall Information):**
```bash
# Общее давление на ресурсы
cat /sys/fs/cgroup/.../cpu.pressure
# some avg10=0.50 avg60=0.20 avg300=0.10 total=123456
# full avg10=0.00 avg60=0.00 avg300=0.00 total=0

cat /sys/fs/cgroup/.../memory.pressure
cat /sys/fs/cgroup/.../io.pressure
# some = хотя бы один процесс ждёт
# full = все процессы ждут
```

**Связанные документы:**
- **[Linux Isolation](Concepts/linux_isolation.md)** — cgroups v1/v2, namespaces, raw inspection
- **[Native Metrics](Docker_metrics/docker_native_metrics.md)** — cpu.stat, memory.events, io.stat, PSI
- **[Container Hardening](Docker_security/container_hardening.md)** — --pids-limit, --memory-swap, --ulimit
- **[Container Execution](Dockerfile/Docker_best_practices/container_execution.md)** — throttling, signal handling
- **[Exit Codes](Docker_troubleshooting/docker_exit_codes.md)** — exit code 137 (OOM), throttling
- **[Docker Debug](Docker_troubleshooting/docker_debug.md)** — PSI для диагностики bottleneck
- **[Compose Directives](Docker_compose/docker_compose_directives.md)** — ulimits в Compose

**Типичные ошибки:**
- `--memory` без `--memory-swap` → swap в 2 раза больше (512m + 512m swap = 1GB)
- `--pids-limit` не установлен → fork bomb убивает хост
- `docker stats` показывает CPU%, но не throttling → проверяйте `cpu.stat`
- `--oom-kill-disable` без `--memory` → контейнер сожрёт всю память хоста
- `--memory-high` не настроен → нет раннего throttling, сразу OOM Kill
- `--cpus` ≠ `--cpuset-cpus`: первый лимитирует, второй привязывает
