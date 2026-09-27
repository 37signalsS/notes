# Диагностика производительности контейнеров

## Определения

**Container Performance Diagnostics** — процесс анализа влияния ограничений cgroup (CPU, память, I/O) на производительность приложений в Docker и Kubernetes. Ключевые файлы: `cpu.stat`, `memory.current`, `memory.events`, `io.stat`.

**CPU Throttling** — ограничение времени выполнения контейнера на CPU при превышении `cpu.max` (cgroup v2) или `cpu.cfs_quota_us` (cgroup v1). Метрики: `nr_throttled` (количество периодов), `throttled_usec` (суммарное время). Контейнер может быть throttled даже при низкой загрузке хоста.

**Memory Limits** — `memory.max` (hard limit) и `memory.high` (soft limit) в cgroup v2. При достижении `memory.max` ядро вызывает OOM killer для контейнера. `memory.high` позволяет демону OOM (systemd-oomd) принудительно дросселировать процесс до принудительного убийства.

**CPU Quota** — квота CPU для контейнера. Формат `cpu.max`: `"<quota> <period>"`. Например, `50000 100000` = 50% одного ядра. При 4 ядрах и `limits.cpu=2` контейнер получает 200% (2 ядра).

**Container OOM** — OOM kill на уровне контейнера. Отличается от системного OOM: убивает только процессы в контейнере, не затрагивая хост. Причины: `memory.max` слишком мал, утечка памяти, неоптимальное использование.

**Cgroup v2 Overhead** — минимальные накладные расходы cgroup v2 на производительность (обычно < 1%). Основные источники overhead: account charging (подсчёт памяти), CPU bandwidth throttling, memory reclaim.

---

## Основные концепции

### Cgroup v2: файловая структура для диагностики

```bash
# Определение пути cgroup
# Docker:
cat /proc/<PID>/cgroup
# → 0::/system.slice/docker-<ID>.scope

# Kubernetes (cgroup v2):
cat /proc/<PID>/cgroup
# → 0::/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<UID>.slice/cri-containerd-<ID>.scope

# Путь к метрикам
CGROUP_PATH="/sys/fs/cgroup/system.slice/docker-<ID>.scope"
# или в Kubernetes:
CGROUP_PATH="/sys/fs/cgroup/kubepods.slice/.../<ID>.scope"
```

### Мониторинг CPU throttling

```bash
# Текущая статистика
cat $CGROUP_PATH/cpu.stat
# → usage_usec 12500000
# → user_usec 10000000
# → system_usec 2500000
# → nr_periods 500
# → nr_throttled 50
# → throttled_usec 2500000

# Интерпретация
# throttled_usec / nr_periods > 10% = проблема
# 2500000 / 500 = 5000 мкс/период (при period=100000 мкс = 5% — OK)
# Но если nr_throttled / nr_periods > 10% = проблема
echo "Throttle ratio: $(echo "scale=2; $nr_throttled * 100 / $nr_periods" | bc)%"

# Лимит
cat $CGROUP_PATH/cpu.max
# → 50000 100000  (50% одного ядра)
# → max (без лимита)
```

### Мониторинг памяти контейнера

```bash
# Текущее потребление
cat $CGROUP_PATH/memory.current
# → 2147483648 (2GB)

# Лимит
cat $CGROUP_PATH/memory.max
# → 4294967296 (4GB)
# → max (без лимита)

# Soft limit
cat $CGROUP_PATH/memory.high
# → 3221225472 (3GB)

# События OOM
cat $CGROUP_PATH/memory.events
# → low 5
# → high 10
# → max 0       ← OOM kill!
# → oom 1
# → oom_kill 1
# → oom_group_kill 0

# Детали памяти
cat $CGROUP_PATH/memory.stat
# → anon 1073741824
# → file 536870912
# → kernel 134217728
# → sock 33554432
```

### Мониторинг I/O контейнера

```bash
# Текущая статистика I/O
cat $CGROUP_PATH/io.stat
# → 8:0 rbytes=125000000 wbytes=50000000 rios=15000 wios=5000
# → rbytes: прочитано байт
# → wbytes: записано байт
# → rios: количество операций чтения
# → wios: количество операций записи

# Лимиты I/O
cat $CGROUP_PATH/io.max
# → 8:0 rbps=max wbps=max riops=max wiops=max
# → 8:0 rbps=1048576 wbps=524288 riops=1000 wiops=500
```

### USE-методология для контейнеров

| Ресурс | Utilization | Saturation | Errors |
|:---|:---|:---|:---|
| **CPU** | `cpu.stat` → `usage_usec` | `cpu.stat` → `nr_throttled` | — |
| **MEMORY** | `memory.current / memory.max` | `memory.events` → `high`, `max` | `memory.events` → `oom`, `oom_kill` |
| **DISK I/O** | `io.stat` → `rbytes + wbytes` | `io.stat` → queue depth | I/O errors в `dmesg` |
| **NETWORK** | `ss -s` per container | `ss` → drops | `ethtool -S` |

### Интерпретация CPU throttling

```bash
# Агрегация по всем контейнерам (Kubernetes)
for cg in $(find /sys/fs/cgroup -name "cpu.stat" -path "*/cri-containerd-*" 2>/dev/null); do
    container=$(echo $cg | grep -oP 'cri-containerd-\K[^/]+' | head -c 12)
    throttled=$(grep nr_throttled $cg | awk '{print $2}')
    periods=$(grep nr_periods $cg | awk '{print $2}')
    if [ "$periods" -gt 0 ] 2>/dev/null; then
        ratio=$(echo "scale=2; $throttled * 100 / $periods" | bc)
        echo "Container $container: throttle=${ratio}% (throttled=$throttled periods=$periods)"
    fi
done | sort -t= -k2 -rn | head -10
```

| Метрика | Норма | Проблема | Действие |
|:---|:---|:---|:---|
| `nr_throttled / nr_periods` | < 5% | > 10% | Увеличить `limits.cpu` |
| `throttled_usec / time` | < 1% | > 5% | Контейнер throttled 5%+ времени |
| `memory.current / memory.max` | < 80% | > 90% | Увеличить `limits.memory` |
| `memory.events.oom_kill` | 0 | > 0 | OOM kill! Увеличить лимит или исправить утечку |
| `io.stat rbytes` | Стабильно | Резкий рост | Проверить I/O нагрузку |

---

## Практические сценарии

### Сценарий 1: Контейнер throttled, приложение медленное

**Симптом:** Приложение в Kubernetes работает медленно, хост имеет свободные ресурсы.

```bash
# 1. Определение Pod
kubectl get pods -o wide | grep <app>
# → my-app-xyz  1/1  Running  node-5

# 2. Определение container ID
kubectl get pod my-app-xyz -o jsonpath='{.status.containerStatuses[0].containerID}'
# → containerd://abc123def456

# 3. Поиск cgroup на ноде
ssh node-5
cat /proc/$(docker inspect --format '{{.State.Pid}}' abc123)/cgroup
# → 0::/kubepods.slice/.../cri-containerd-abc123.scope

# 4. Проверка CPU throttling
CGROUP="/sys/fs/cgroup/kubepods.slice/.../cri-containerd-abc123.scope"
cat $CGROUP/cpu.stat
# → nr_throttled 892
# → nr_periods 2500
# → Throttle ratio: 35.7% ← КРИТИЧНО!

# 5. Проверка лимита
cat $CGROUP/cpu.max
# → 100000 100000  (100% одного ядра = limits.cpu=1)
```

**Решение:**
```bash
# Увеличить CPU limits
kubectl patch deployment my-app -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"cpu":"2"}}}]}}}}'

# Или оптимизировать: установить requests = среднему потреблению
kubectl patch deployment my-app -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"requests":{"cpu":"500m"},"limits":{"cpu":"2"}}}]}}}}'
```

### Сценарий 2: OOM Kill контейнера

**Симптом:** Pod перезапускается, `kubectl describe pod` показывает `OOMKilled`.

```bash
# 1. Проверка
kubectl describe pod my-app-xyz | grep -A5 "Last State"
# → Last State: Terminated
#   Reason: OOMKilled
#   Exit Code: 137

# 2. Проверка memory events на ноде
ssh node-5
cat $CGROUP/memory.events
# → oom_kill 1  ← OOM kill произошёл!

# 3. Текущее потребление
cat $CGROUP/memory.current
# → 4294967296 (4GB)

cat $CGROUP/memory.max
# → 4294967296 (4GB) ← лимит совпадает с потреблением!

# 4. Детали памяти
cat $CGROUP/memory.stat | grep -E "anon|file|kernel|sock"
# → anon 3221225472    (3GB — память приложения)
# → file 536870912     (512MB — кэш)
# → kernel 419430400   (400MB — kernel memory)
# → sock 67108864      (64MB — сокеты)
```

**Решение:**
```bash
# 1. Увеличить memory limits
kubectl patch deployment my-app -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"8Gi"}}}]}}}}'

# 2. Добавить memory.high (soft limit) для предотвращения OOM
# В cgroup v2 вручную:
echo 6442450944 > $CGROUP/memory.high  # 6GB (soft limit)

# 3. Исправить утечку памяти в приложении
# (профилирование через jemalloc, heaptrack, async-profiler)
```

### Сценарий 3: Контейнер использует больше CPU, чем limits

**Симптом:** `docker stats` показывает 200% CPU, но `limits.cpu=1`.

```bash
# 1. Проверка cpu.max
cat $CGROUP/cpu.max
# → 100000 100000  (100% = 1 CPU)

# 2. Проверка cpu.stat
cat $CGROUP/cpu.stat
# → usage_usec 50000000 (50 сек за 100 сек = 50% — OK)

# 3. Проверка burst
cat $CGROUP/cpu.max.burst
# → 0  (нет burst credits)

# 4. Фактическое использование
top -H -p $(docker inspect --format '{{.State.Pid}}' <container>)
# → 8 потоков × 25% = 200% total, но CFS ограничивает до 100%
```

**Интерпретация:** `docker stats` показывает *суммарное* использование CPU всеми потоками до throttle. Фактически контейнер получает не более `limits.cpu` × 100% CPU.

**Решение:** Нормальное поведение. Если приложение медленное — увеличить `limits.cpu`.

### Сценарий 4: Контейнер не может выделить память

**Симптом:** `malloc()` возвращает NULL, `dmesg` показывает `oom-kill`.

```bash
# 1. Проверка перекоммита
cat $CGROUP/memory.max
# → 2147483648 (2GB)

cat $CGROUP/memory.current
# → 2000000000 (1.87GB — почти исчерпан!)

# 2. Проверка memory.high
cat $CGROUP/memory.high
# → max (не установлен — приложение будет убито сразу при max)

# 3. Проверка OOM score
cat $CGROUP/cgroup.procs | while read pid; do
    echo "PID $pid: $(cat /proc/$pid/oom_score 2>/dev/null)"
done | sort -k2 -rn
```

**Решение:**
```bash
# 1. Установить memory.high (soft limit)
echo 1610612736 > $CGROUP/memory.high  # 1.5GB

# 2. В Kubernetes: использовать memory.high через annotations
# или настроить systemd-oomd

# 3. Оптимизировать приложение:
# - Уменьшить Heap (Java: -Xmx, Go: GOMEMLIMIT)
# - Использовать pool objects
# - Отключить кэширование если не нужно
```

---

## Дополнительная информация

### Связанные темы

- [**cgroups**](../../Core/cgroups.md) — полная справочная по cgroup v1/v2
- [**Docker performance**](../../../Docker/Docker_performance_tuning.md) — тюнинг Docker
- [**Resource limits**](../../../Docker/Docker_security/resource_limits.md) — настройка лимитов Docker
- [**Container metrics**](../../../Docker/Docker_metrics/docker_cadvisor_deployment.md) — метрики через cAdvisor
- [**Native metrics**](../../../Docker/Docker_metrics/docker_native_metrics.md) — нативные метрики Docker
- [**Container memory**](../Memory/container_memory_diagnostics.md) — диагностика памяти контейнеров
- [**OOM Killed pods**](../../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md) — OOM в Kubernetes
- [**Deployment troubleshooting**](../../../Kubernetes/Base/Deployment/troubleshooting.md) — общая диагностика деплоев
- [**Pod troubleshooting**](../../../Kubernetes/Base/Pod/pod_practical_scenarios_commands.md) — команды для Pod
- [**Deployment monitoring**](../../../Kubernetes/Base/Deployment/deployment_monitoring_observability.md) — мониторинг деплоев
- [**Kubernetes alerts**](../../../Grafana/alerting/kubernetes_alerts.md) — алерты для K8s
- [**CPU throttling alerts**](../../../Grafana/alerting/kubernetes_alerts.md#container-cpu-throttling) — алерт на CPU throttling

### Рекомендации по лимитам для production

| Ресурс | Рекомендация | Обоснование |
|:---|:---|:---|
| `limits.cpu` | = `requests.cpu` × 2 | Guarantees QoS, avoids throttling |
| `limits.memory` | = `requests.memory` × 1.5 | Защита от OOM + запас |
| `memory.high` | = `limits.memory` × 0.85 | Soft limit для early reclaim |
| `cpu.max.burst` | 0–50% от `cpu.max` | Для кратковременных spike |

### Чек-лист диагностики контейнера

```bash
# 1. Определение cgroup path
cat /proc/<PID>/cgroup

# 2. CPU throttling
cat $CGROUP/cpu.stat | grep -E "nr_throttled|nr_periods|throttled_usec"

# 3. Память
cat $CGROUP/memory.current $CGROUP/memory.max $CGROUP/memory.events

# 4. I/O
cat $CGROUP/io.stat

# 5. Лимиты
cat $CGROUP/cpu.max $CGROUP/memory.max $CGROUP/io.max

# 6. Ошибки
dmesg | grep -i "oom\|killed\|cgroup"
```
