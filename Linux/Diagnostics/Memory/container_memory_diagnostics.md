# Диагностика памяти в контейнерах (cgroup v2)

## Определения

**Контейнерная память** — изолированный сегмент оперативной памяти, управляемый через контрольные группы (cgroups). В отличие от процессов на хосте, контейнеры имеют жесткие лимиты (`memory.max`), при превышении которых срабатывает OOM Killer внутри cgroup.

**cgroup v2 ( unified hierarchy )** — современная версия контрольных групп, предоставляющая единую иерархию и файлы для управления ресурсами: `memory.max`, `memory.high`, `memory.current`, `memory.events`.

**memory.max** — жесткий лимит памяти для cgroup. При превышении ядро инициирует OOM Killer внутри группы. В Docker соответствует флагу `--memory`, в Kubernetes — `resources.limits.memory`.

**memory.high** — мягкий лимит памяти. При превышении ядро замедляет выделение памяти (throttling), но не убивает процессы. Используется для превентивного контроля.

**memory.events** — файл в cgroups v2, содержащий счетчики событий: `low`, `high`, `max`, `oom`, `oom_kill`. Позволяет диагностировать, какие именно события происходили в контейнере.

**memory.pressure** — файл PSI (Pressure Stall Information) для конкретной cgroup. Показывает давление на память внутри контейнера.

**LXCFS** — файловая система, предоставляющая контейнерам изолированные `/proc/meminfo` и другие виртуальные файлы. Без LXCFS контейнер видит всю память хоста.

**OOMKilled** — статус контейнера в Kubernetes, указывающий на завершение из-за превышения лимита памяти (exit code 137).

## Основные концепции

### Проблема видимости памяти в контейнерах

Ключевая проблема диагностики контейнерной памяти — **отсутствие изоляции `/proc`**:

| Что видит контейнер | Что видит хост | Проблема |
| :--- | :--- | :--- |
| `/proc/meminfo` — вся RAM хоста | `/sys/fs/cgroup/.../memory.current` — лимит контейнера | Контейнер «думает», что у него 64 ГБ, хотя лимит — 4 ГБ |
| `free -h` — хостовая статистика | `docker stats` — контейнерная статистика | `free` бесполезен внутри контейнера |
| `top`/`htop` — все процессы хоста | `ps` внутри контейнера — только свои процессы | `top` не видит других контейнеров |

**Решение:** Всегда диагностируйте контейнерную память с хоста или через cgroup-файлы.

### Архитектура двухуровневого OOM

В контейнерных средах OOM Killer работает на двух уровнях:

1. **Уровень cgroup (primary):** Ядро убивает процесс внутри контейнера при превышении `memory.max`. PID 1 контейнера может остаться живым.
2. **Уровень хоста (fallback):** Если общий OOM сработает, ядро выбирает «самый тяжелый» процесс на всей системе.

**Критическое различие:**
- В cgroups v1: OOM убивает процесс, PID 1 контейнера падает, Docker перезапускает контейнер.
- В cgroups v2: OOM может убить дочерний процесс, не затрагивая PID 1. Контейнер продолжает работать, но сервис недоступен. `dmesg` может быть чист.

### Механизм memory.events

Файл `memory.events` содержит счетчики событий:

| Событие | Описание | Действие SRE |
| :--- | :--- | :--- |
| `low` | Сработал механизм подсказки (reclaim hint). | Информационно. |
| `high` | Превышен `memory.high` (мягкий лимит). | Троттлинг, возможен рост латентности. |
| `max` | Превышен `memory.max` (жесткий лимит). | Немедленный OOM. |
| `oom` | OOM Killer был инициирован. | Проверьте `oom_kill` и логи. |
| `oom_kill` | Процесс был завершен OOM Killer. | Критично: анализируем жертву. |
| `oom_group_kill` | Убита вся группа (cgroup). | Проверьте `memory.oom.group`. |

**Разница между `memory.events` и `memory.events.local`:**
- `memory.events` — рекурсивный: суммирует события по всей иерархии (все дочерние cgroups).
- `memory.events.local` — локальный: только для данной группы.

### Модель памяти Docker

Docker использует несколько механизмов:

| Параметр | Описание | cgroup v2 файл |
| :--- | :--- | :--- |
| `--memory` / `-m` | Жесткий лимит RAM | `memory.max` |
| `--memory-swap` | Лимит RAM + Swap | `memory.swap.max` |
| `--memory-reservation` | Мягкий лимит (гарантия) | `memory.high` |
| `--oom-kill-disable` | Отключить OOM Killer | `memory.oom.group = 1` |
| `--oom-score-adj` | Приоритет OOM | Внутренний параметр |

### Модель памяти Kubernetes

Kubernetes добавляет дополнительный уровень абстракции:

| Ресурс | Описание | Маппинг на cgroup |
| :--- | :--- | :--- |
| `requests.memory` | Гарантированная память (планировщик) | Не直接影响 cgroup, используется для scheduling |
| `limits.memory` | Жесткий лимит | `memory.max` |
| `limits.memory` + `requests.memory` | Burst до limits | `memory.high` (опционально через MemoryQoS) |

**Silent OOM в Kubernetes:**
1. Процесс внутри контейнера превышает `limits.memory`.
2. cgroup v2 убивает процесс (не обязательно PID 1).
3. `dmesg` может быть чист (нет системного OOM).
4. Контейнер перезапускается с exit code 137.
5. Диагностика: `kubectl describe pod` → Last State → Reason: OOMKilled.

## Практические сценарии

### Предварительные требования

**Аппаратные и программные требования:**
- ОС: Linux с ядром 4.15+ (cgroups v1) или 5.2+ (cgroups v2).
- Docker 20.10+ или Podman 3.0+ для полноценной поддержки cgroups v2.
- Kubernetes 1.22+ для MemoryQoS и cgroups v2.
- Пакеты: `cgroup-tools` (для `cgget`, `cgset`), `sysstat`.

**Проверка версии cgroups:**
```bash
# Проверка, какая версия cgroups используется
stat -fc %T /sys/fs/cgroup/
# → cgroup2fs (cgroups v2) или tmpfs (cgroups v1)

# Проверка Docker
docker info | grep -i cgroup
# → Cgroup Driver: systemd
# → Cgroup Version: 2
```

### 1. Быстрый health-check контейнера (с хоста)

```bash
# Найти PID контейнера
CONTAINER_PID=$(docker inspect --format '{{.State.Pid}}' <container_name>)

# Найти cgroup
CGROUP_PATH=$(cat /proc/$CONTAINER_PID/cgroup | grep -oP '\d+:memory:\K.*')
# Или для cgroups v2:
CGROUP_PATH=$(cat /proc/$CONTAINER_PID/cgroup | grep -oP '0::\K.*')

# Проверка текущего потребления
cat /sys/fs/cgroup${CGROUP_PATH}/memory.current
# → 3221225472 (3 ГБ)

# Проверка лимита
cat /sys/fs/cgroup${CGROUP_PATH}/memory.max
# → 4294967296 (4 ГБ)

# Расчет процента использования
CURRENT=$(cat /sys/fs/cgroup${CGROUP_PATH}/memory.current)
MAX=$(cat /sys/fs/cgroup${CGROUP_PATH}/memory.max)
echo "Usage: $(echo "scale=2; $CURRENT/$MAX*100" | bc)%"
```

### 2. Анализ memory.events для диагностики OOM

```bash
# Быстрая проверка OOM-событий
docker exec <container> cat /sys/fs/cgroup/memory.events 2>/dev/null || \
cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' <container>).scope/memory.events

# → low 1234
# → high 0
# → max 5
# → oom 3
# → oom_kill 2
# → oom_group_kill 0

# Интерпретация:
# max=5 → 5 раз превышен memory.max
# oom_kill=2 → 2 процесса убиты OOM Killer
# oom_group_kill=0 → группы не убивались (oom.group=0)
```

### 3. Мониторинг PSI внутри контейнера (с хоста)

```bash
# Через Docker exec
docker exec <container> cat /proc/pressure/memory
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381

# Через cgroup (с хоста)
cat /sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' <container>).scope/memory.pressure
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381

# Для Kubernetes Pod
kubectl exec <pod> -- cat /proc/pressure/memory
```

### 4. Диагностика Silent OOM в Kubernetes

```bash
# 1. Проверка последнего состояния Pod
kubectl describe pod <pod_name> | grep -A 5 "Last State"
# → Last State:   Terminated
# →   Reason:     OOMKilled
# →   Exit Code:  137

# 2. Проверка events
kubectl get events --field-selector reason=OOMKilling --sort-by=.lastTimestamp

# 3. Проверка cgroup events (на ноде)
# Найти ноду
NODE=$(kubectl get pod <pod_name> -o jsonpath='{.spec.nodeName}')

# Подключиться к ноде и найти cgroup
ssh $NODE "find /sys/fs/cgroup -path '*kubepods*' -name memory.events.local | grep $(kubectl get pod <pod_name> -o jsonpath='{.metadata.uid}')"

# 4. Проверка dmesg на ноде
ssh $NODE "dmesg -T | grep -i oom | tail -10"
```

### 5. Настройка memory.high для превентивного контроля

```bash
# Установка мягкого лимита (throttling) для контейнера
CONTAINER_ID=$(docker inspect -f '{{.Id}}' <container>)
CGROUP_PATH="/sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope"

# memory.max = 4 ГБ (жесткий лимит)
echo 4294967296 | sudo tee ${CGROUP_PATH}/memory.max

# memory.high = 3 ГБ (мягкий лимит, throttling)
echo 3221225472 | sudo tee ${CGROUP_PATH}/memory.high

# Проверка
cat ${CGROUP_PATH}/memory.high
# → 3221225472
```

### 6. Анализ потребления через smem (с хоста)

```bash
# Анализ PSS всех процессов контейнера
CONTAINER_PID=$(docker inspect --format '{{.State.Pid}}' <container>)
sudo smem -tk -s pss -r | grep -A 100 "^.*PID" | head -20

# Или через nsenter (для контейнеров с limited PID namespace)
sudo nsenter -t $CONTAINER_PID -p -m -- smem -tk -s pss -r | head -10
```

### 7. Диагностика через /proc/PID/status

```bash
# На хосте: PID процесса внутри контейнера
APP_PID=$(docker inspect --format '{{.State.Pid}}' <container>)

# Проверка виртуальной и резидентной памяти
cat /proc/$APP_PID/status | grep -E "VmSize|VmRSS|VmSwap|VmPeak"
# → VmSize:   8388608 kB  (виртуальное адресное пространство)
# → VmRSS:    3145728 kB  (реально используемая RAM)
# → VmSwap:          0 kB  (swap)
# → VmPeak:   8388608 kB  (пиковый VmSize)

# Важно: VmSize может быть до 128 ТБ (лимит архитектуры), но реальный RSS ограничен cgroup
```

### 8. Настройка OOM-приоритета для критичных контейнеров

```bash
# Docker: отключение OOM Killer (опасно!)
docker run --oom-kill-disable --memory=4g <image>

# Docker: установка приоритета OOM
docker run --oom-score-adj=-500 --memory=4g <image>

# Kubernetes: через安全度
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: critical-app
    resources:
      limits:
        memory: "4Gi"
    # В Kubernetes нет прямого аналога --oom-score-adj
    # Используйте PriorityClass и appropriate limits
```

### 9. Сравнение метрик внутри и снаружи контейнера

```bash
# Внутри контейнера (НЕ использовать для диагностики!)
docker exec <container> free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           62Gi        12Gi        8Gi       256Mi       42Gi       48Gi
# (Показывает всю RAM хоста!)

# На хосте (корректно)
docker stats <container>
# → CONTAINER     CPU %   MEM USAGE / LIMIT     MEM %   NET I/O       BLOCK I/O
# → myapp         1.23%   3.14GiB / 4GiB        78.5%   1.23GB / 456MB   123MB / 456MB

# Через cgroup (на хосте, самый точный)
CGROUP="/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' <container>).scope"
echo "Current: $(cat $CGROUP/memory.current | numfmt --to=iec)"
echo "Max: $(cat $CGROUP/memory.max | numfmt --to=iec)"
echo "Events: $(cat $CGROUP/memory.events)"
```

## Типичные ошибки и их решение

### 1. Контейнер показывает OOMKilled, но dmesg чист

**Симптом:** `kubectl describe pod` показывает `Reason: OOMKilled`, но `dmesg` на ноде пуст.

**Причина:** cgroups v2 убивает дочерний процесс, не затрагивая PID 1. Системный OOM не срабатывает.

**Решение:**
```bash
# Проверка memory.events.local на ноде
cat /sys/fs/cgroup/kubepods.slice/.../memory.events.local
# → oom_kill 1

# Увеличение лимита
kubectl patch deployment <name> -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"8Gi"}}}]}}}}'
```

### 2. Контейнер использует больше памяти, чем limits

**Симптом:** `docker stats` показывает MEM USAGE > LIMIT.

**Причина:** `--memory-swap` включает swap. Контейнер может использовать swap сверх лимита RAM.

**Решение:**
```bash
# Проверка лимита swap
docker inspect <container> | grep -i memory
# → "Memory": 4294967296, "MemorySwap": 8589934592

# Отключение swap для контейнера
docker run --memory=4g --memory-swap=4g <image>
```

### 3. memory.events показывает high, но OOM не происходит

**Симптом:** `memory.events` содержит `high > 0`, но процессы не убиваются.

**Причина:** `memory.high` вызывает throttling, а не OOM. Это нормальное поведение.

**Решение:**
```bash
# Проверка текущего потребления vs memory.high
CGROUP="/sys/fs/cgroup/system.slice/docker-<id>.scope"
CURRENT=$(cat $CGROUP/memory.current)
HIGH=$(cat $CGROUP/memory.high)
echo "Current: $CURRENT, High: $HIGH"
# Если Current > High — процессы замедляются (throttling)
```

### 4. Скрытая утечка памяти в контейнере

**Симптом:** Контейнер медленно потребляет всю доступную память.

**Диагностика:**
```bash
# 1. Мониторинг потребления в реальном времени
watch -n 5 "cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current"

# 2. Анализ процессов внутри контейнера (с хоста)
CONTAINER_PID=$(docker inspect --format '{{.State.Pid}}' <container>)
sudo nsenter -t $CONTAINER_PID -p -m -- ps aux --sort=-%mem | head -10

# 3. Проверка /proc/PID/smaps_rollup
sudo cat /proc/$CONTAINER_PID/smaps_rollup | grep -E "Rss|Pss|Swap"
```

### 5. cgroup v2 не поддерживается

**Симптом:** Файлы `memory.max`, `memory.current` не найдены.

**Причина:** Система использует cgroups v1.

**Решение:**
```bash
# Проверка версии
stat -fc %T /sys/fs/cgroup/
# → tmpfs = cgroups v1

# Для cgroups v1 файлы находятся в:
cat /sys/fs/cgroup/memory/docker/<id>/memory.limit_in_bytes
cat /sys/fs/cgroup/memory/docker/<id>/memory.usage_in_bytes
cat /sys/fs/cgroup/memory/docker/<id>/memory.oom_control
```

## Best Practices

1. **Всегда диагностируйте с хоста.** Не используйте `free`, `top`, `/proc/meminfo` внутри контейнера для оценки потребления.

2. **Используйте cgroup-файлы как primary source.** `memory.current`, `memory.max`, `memory.events` — самые точные источники.

3. **Настройте memory.high.** Мягкий лимит предотвращает мгновенный OOM и дает время на эскалацию.

4. **Мониторьте memory.events.** Рост `max` или `oom_kill` — ранний индикатор проблем.

5. **Используйте PSI для контейнеров.** `memory.pressure` в cgroup показывает реальное давление.

6. **Для Kubernetes используйте VPA.** Vertical Pod Autoscaler рекомендует правильные limits на основе истории потребления.

7. **Настройте OOM-приоритеты.** Критичные сервисы должны иметь `oom_score_adj=-500`.

8. **Храните baseline.** Сохраняйте «здоровые» значения memory.current и memory.events для сравнения.

## Дополнительная информация

### Связанные темы

- [cgroups](../../Core/cgroups.md) — полная теория контрольных групп (v1/v2).
- [OOM Killer diagnostics](../../Core/processes/oom_killer_diagnostics.md) — анализ принудительного завершения процессов.
- [OOM Killer containers](../../Core/processes/oom_killer_containers.md) — OOM в контейнерных средах.
- [PSI](../../Core/kernel/psi.md) — Pressure Stall Information.
- [smem](./smem.md) — точный анализ PSS/USS.
- [pmap](./pmap.md) — карта памяти процесса.
- [proc_meminfo](./proc_meminfo.md) — статистика памяти ядра.

### Инструменты

| Инструмент | Назначение | Где использовать |
| :--- | :--- | :--- |
| `docker stats` | Быстрый обзор потребления | Production, monitoring |
| `cgroup-файлы` | Точная диагностика | Production, troubleshooting |
| `smem` | Детальный PSS/USS анализ | Debugging |
| `ps` / `top` | Процессы внутри контейнера | Debugging |
| `kubectl top` | Aggregated container metrics | Kubernetes |

### Литература

- [Control Group v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)
- [Docker Runtime Metrics](https://docs.docker.com/engine/reference/commandline/stats/)
- [Kubernetes Resource Management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
