# OOM Killer Diagnostics

## Диагностика и тестирование OOM Killer

#### Просмотр рейтинга OOM для процессов

```bash
# Все процессы, отсортированные по oom_score
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

В данном примере, если произойдет OOM, процесс `fail2ban-server` (PID 131351) будет первым кандидатом на завершение, так как у него самый высокий `oom_score` (700).

#### Просмотр логов OOM Killer

```bash
# Через dmesg
dmesg -T | grep -i "oom\|killed process"

# Через journalctl
journalctl -k | grep -i "oom-kill"

# Детальный просмотр последних OOM событий
journalctl -k -g "Out of memory" -n 50
```

Пример записи в логе:

```
[114247.906865] oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),
cpuset=/,mems_allowed=0,global_oom,task_memcg=/system.slice/fail2ban.service,
task=fail2ban-server,pid=131351,uid=0
[114247.906966] Out of memory: Killed process 131351 (fail2ban-server)
total-vm:886820kB, anon-rss:19928kB, file-rss:30592kB, shmem-rss:0kB,
UID:0 pgtables:628kB oom_score_adj:0
```

#### Принудительный вызов OOM Killer

> **ПРЕДУПРЕЖДЕНИЕ:** Используйте эту команду с осторожностью! Она приведет к немедленному завершению одного или нескольких процессов!

```bash
# Включить sysrq-trigger (если отключен)
echo 1 > /proc/sys/kernel/sysrq

# Принудительно вызвать OOM Killer
echo f > /proc/sysrq-trigger

# Проверить логи
dmesg | tail -50
```

---

**См. также:**

* [Механизм OOM Killer](./oom_killer_mechanism.md)
* [Управление поведением OOM Killer](./oom_killer_management.md)
