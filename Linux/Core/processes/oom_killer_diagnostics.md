# OOM Killer Diagnostics

## Определения

**Диагностика OOM Killer** — процесс выявления, анализа и расследования событий нехватки памяти (Out of Memory) в Linux. Включает просмотр логов ядра, анализ рейтингов процессов (`oom_score`), проверку лимитов cgroups и определение причин OOM.

## Основные концепции

### Источники данных для диагностики

| Источник | Команда | Что показывает |
| :--- | :--- | :--- |
| **Кольцевой буфер ядра** | `dmesg -T` | Последние OOM события, детали убитых процессов |
| **Журнал systemd** | `journalctl -k` | Долгосрочное хранение OOM логов |
| **Рейтинг процессов** | `/proc/<PID>/oom_score` | Текущий рейтинг "кандидата на убийство" |
| **Корректировка рейтинга** | `/proc/<PID>/oom_score_adj` | Влияние пользователя на рейтинг |
| **Лимиты cgroups** | `/sys/fs/cgroup/.../memory.max` | Границы памяти для контейнеров |
| **Статус процесса** | `/proc/<PID>/status` | VmRSS, VmSize, OOM статус |

### Формат записи OOM Killer в логе

Типичная запись содержит:

```
oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),
cpuset=/,mems_allowed=0,global_oom,task_memcg=/system.slice/fail2ban.service,
task=fail2ban-server,pid=131351,uid=0
Out of memory: Killed process 131351 (fail2ban-server)
total-vm:886820kB, anon-rss:19928kB, file-rss:30592kB, shmem-rss:0kB,
UID:0 pgtables:628kB oom_score_adj:0
```

**Расшифровка полей:**

- `constraint` — тип ограничения: `CONSTRAINT_NONE` (глобальный OOM), `CONSTRAINT_MEMCG` (cgroup лимит)
- `task_memcg` — путь к cgroup процесса (например, `/system.slice/fail2ban.service`)
- `task`, `pid` — имя и PID убитого процесса
- `total-vm` — общий объем виртуальной памяти процесса
- `anon-rss` — анонимная резидентная память (heap, stack)
- `file-rss` — файловая резидентная память (mapped files)
- `shmem-rss` — разделяемая память (tmpfs, shared memory)
- `pgtables` — память, используемая таблицами страниц
- `oom_score_adj` — корректировка рейтинга пользователем

## Практические сценарии

### Просмотр рейтинга OOM для процессов

```bash
# Все процессы, отсортированные по oom_score (топ-20)
for p in /proc/[0-9]*; do
    pid=${p##*/}
    [ -r $p/oom_score ] && printf "%4s %5s %8s %s\n" \
        "$(cat $p/oom_score 2>/dev/null)" \
        "$(cat $p/oom_score_adj 2>/dev/null)" \
        "$pid" \
        "$(cat $p/comm 2>/dev/null)"
done | sort -nr | head -20
```

Пример вывода:

```
700  0      131351  fail2ban-server
693  0      1254    node
692  0      131649  fwupd
```

Процесс `fail2ban-server` (PID 131351) имеет наивысший `oom_score` (700) и будет первым кандидатом на завершение при OOM.

### Просмотр логов OOM Killer

```bash
# Через dmesg (последние события)
dmesg -T | grep -i "oom\|killed process"

# Через journalctl (долгосрочное хранение)
journalctl -k | grep -i "oom-kill"

# Детальный просмотр последних OOM событий
journalctl -k -g "Out of memory" -n 50
```

### Анализ потребления памяти процессом

```bash
# Детальная информация о памяти процесса
cat /proc/<PID>/status | grep -i "vm\|rss"

# Карта памяти процесса (какие библиотеки/файлы mapped)
cat /proc/<PID>/smaps_rollup

# Статистика cgroups (v2)
cat /sys/fs/cgroup/system.slice/<service>.scope/memory.current
cat /sys/fs/cgroup/system.slice/<service>.scope/memory.max

# Проверка лимита для процесса
grep "Max resident set size" /proc/<PID>/limits
```

### Диагностика OOM в контейнерах

```bash
# Проверить OOMKilled статус
docker inspect <container> --format '{{.State.OOMKilled}}'

# Проверить лимиты cgroups контейнера
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.max
cat /sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current

# Проверить OOM события в Kubernetes
kubectl describe pod <pod> | grep -A 5 "Last State"
```

### Мониторинг памяти в реальном времени

```bash
# Мониторинг памяти (обновление каждые 2 сек)
watch -n 2 'free -h && echo "---" && ps aux --sort=-%mem | head -10'

# Мониторинг cgroups памяти
watch -n 2 'cat /sys/fs/cgroup/system.slice/<service>.scope/memory.current'
```

## Дополнительная информация

### Принудительный вызов OOM Killer

> **ПРЕДУПРЕЖДЕНИЕ:** Приведет к немедленному завершению одного или нескольких процессов! Используйте только в тестовых средах.

```bash
# Включить sysrq-trigger (если отключен)
echo 1 > /proc/sys/kernel/sysrq

# Принудительно вызвать OOM Killer
echo f > /proc/sysrq-trigger

# Проверить логи
dmesg | tail -50
```

> **Примечание:** Символ `f` выбран как отсылка к триггеру `sysrq` для OOM Killer.

### Автоматизация диагностики

Скрипт для быстрого анализа OOM событий:

```bash
#!/bin/bash
echo "=== Последние 10 OOM событий ==="
dmesg -T | grep -i "killed process" | tail -10

echo ""
echo "=== Топ-10 процессов по oom_score ==="
for p in /proc/[0-9]*; do
    pid=${p##*/}
    [ -r $p/oom_score ] && printf "%4s %8s %s\n" \
        "$(cat $p/oom_score 2>/dev/null)" \
        "$pid" \
        "$(cat $p/comm 2>/dev/null)"
done 2>/dev/null | sort -nr | head -10

echo ""
echo "=== Последние процессы, убитые OOM Killer ==="
journalctl -k -g "Out of memory" --no-pager -n 20
```

### Частые причины OOM

| Причина | Признаки | Решение |
| :--- | :--- | :--- |
| **Утечка памяти** | Постепенный рост RSS, периодические OOM | Профилирование приложения, исправление утечки |
| **Недостаточный лимит** | OOM сразу при запуске/нагрузке | Увеличить `memory.max` (cgroups) или `limits.memory` (K8s) |
| **Пиковая нагрузка** | OOM при spikes нагрузки | Увеличить лимиты с запасом, настроить HPA |
| **Глобальная нехватка RAM** | Много процессов-кандидатов, высокий `free` | Добавить RAM, настроить swap |
| **JVM без лимитов** | Java-процесс с высоким `oom_score` | Установить `-XX:MaxRAMPercentage` |

---

Механизм работы OOM Killer описан в [**OOM Killer Mechanism**](./oom_killer_mechanism.md). Управление поведением — в [**OOM Killer Management**](./oom_killer_management.md).
