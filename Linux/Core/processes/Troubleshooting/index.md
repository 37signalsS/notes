# Устранение неисправностей процессов в Linux

## Определения

**Troubleshooting процессов** — системный процесс выявления, локализации и устранения сбоев в работе вычислительных задач. Охватывает анализ жизненного цикла (создание, работа, завершение) и потребления ресурсов.

**Exit Code (Код завершения)** — числовой статус (0–255), передаваемый родителю при выходе. Значение `0` — успех, остальные — специфичные ошибки. Подробнее: [**Коды возврата в Shell**](../../../Shell/exit_codes.md).

**Coredump (Дамп памяти)** — объектный файл, содержащий образ памяти процесса на момент фатального сбоя (`SIGSEGV`, `SIGILL`). Позволяет выполнить «посмертный» анализ состояния регистров и стека.

**OOM Killer (Out-of-Memory Killer)** — защитный механизм ядра, принудительно завершающий процессы при критической нехватке RAM. Подробно: [**Механизм OOM Killer**](../oom_killer_mechanism.md), [**Диагностика OOM Killer**](../oom_killer_diagnostics.md), [**Управление OOM Killer**](../oom_killer_management.md).

**Uninterruptible Sleep (Состояние D)** — состояние процесса, ожидающего завершения системного вызова (обычно I/O). Процесс в этом состоянии не реагирует на сигналы, включая `SIGKILL`.

**Context Switching (Переключение контекста)** — процедура сохранения состояния одной задачи и восстановления другой. Чрезмерное количество переключений (Voluntary/Involuntary) ведет к деградации производительности.

**Root Cause Analysis (RCA)** — методология поиска первопричины сбоя, а не лечения симптомов. Включает сбор доказательств, построение таймлайна и проверку гипотез до внесения изменений. Цель — предотвратить повторение инцидента.

**Diagnostic Triage (Триаж диагностики)** — быстрая классификация проблемы по типу, масштабу и критичности для определения стратегии диагностики. Отвечает на три вопроса: **что** сломалось, **насколько** это критично, **какие** ресурсы затронуты.

**Process State Diagnosis (Диагностика состояния процесса)** — анализ текущего состояния задачи (`R`/`S`/`D`/`Z`/`T`) с целью классификации проблемы как CPU-bound, I/O-bound, zombie, blocked или terminated.

## Основные концепции

### Эшелонированная диагностика (Macro → Micro)

Диагностика процессов всегда начинается с общего обзора системы и сужается до конкретного системного вызова:

| Уровень | Что делаем | Инструменты | Цель |
| :--- | :--- | :--- | :--- |
| **1. Macro (Хост)** | Сбор состояния всей системы: нагрузка, память, диск, сеть | `top`, `htop`, `btop`, `vmstat`, `uptime`, `free -h`, `iostat` | Найти узкое место на уровне хоста |
| **2. Micro (Процесс)** | Идентификация конкретного PID, потребляющего ресурс критически | `pidstat`, `ps`, `pgrep`, `top -p` | Сузить поиск до одного-двух процессов |
| **3. Deep (Внутреннее состояние)** | Анализ дескрипторов, карт памяти, стека вызовов | `/proc/PID/*`, `lsof`, `pstack`, `cat /proc/PID/stack` | Понять, что именно делает процесс |
| **4. Событийный (Трассировка)** | Перехват системных вызовов и сигналов в реальном времени | `strace`, `bpftrace`, `perf`, `gdb` | Найти корневую причину на уровне вызовов |

Полный методологический фундамент — в разделе [**Общая методология диагностики**](../../../Diagnostics/Troubleshooting/general_troubleshooting_methodology.md) и [**Быстрая диагностика сервера**](../../../Diagnostics/Troubleshooting/rapid_assessment.md).

### USE-подход к ресурсам процесса

Методика **USE (Utilization, Saturation, Errors)** — фундаментальная модель диагностики, применимая к каждому ресурсу:

| Ресурс | Utilization (Утилизация) | Saturation (Насыщение) | Errors (Ошибки) |
| :--- | :--- | :--- | :--- |
| **CPU** | `%CPU` в `top` | `r` в `vmstat`, `runqlen` в `sar` | `dmesg` (segfault, thermal throttle) |
| **Memory** | `used` в `free`, `Rss` в `/proc/PID/status` | `si`/`so` в `vmstat`, PSI `memory.full` | `dmesg` (OOM kill), `coredumpctl` |
| **FD (дескрипторы)** | `ls /proc/PID/fd \| wc -l` | очередь в `accept()`, `EMFILE` | `strace` (ENFILE, EMFILE) |
| **Disk I/O** | `%util` в `iostat` | `await`, `avgqu-sz` в `iostat` | `dmesg` (I/O error), `smartctl` |
| **Network** | `rxkB/s`, `txkB/s` в `sar` | переполнение `accept()` очереди | `ss` (retrans), `dmesg` (drop) |

### Матрица ответственности за ресурсы

При поиске «виновника» нагрузки следует проверять следующие узкие места:

- **CPU:** Очереди на выполнение (`runqueue`), время в Kernelspace (системные вызовы), влияние прерываний. Используйте `pidstat -u`, `top`, `perf` для локализации hot-spot'ов.
- **Memory:** Разница между RSS и PSS, состояние Swap, утечки в куче (heap). Используйте `smem`, `/proc/PID/smaps_rollup`, `memleak` (BCC).
- **I/O:** Задержки дисковых операций, лимиты пропускной способности, блокировки файлов. Используйте `iotop`, `pidstat -d`, `iostat`, `fio`.
- **FD (Дескрипторы):** Утечки сокетов, пайпов и открытых файлов. Используйте `lsof`, `/proc/PID/fd`, `ss`, `pidstat -d`.
- **Сеть:** Задержки на уровне TCP, переполнение буферов, ошибки. Используйте `ss`, `tcpdump`, `sar -n TCP`.

### Диагностический workflow: принятие решений

При типичной ситуации «процесс завис / падает / ест ресурсы» применяйте следующий workflow:

```text
Симптом
  │
  ├─ Процесс исчез (exit code 137 / 139 / 143)
  │  ├─ dmesg | grep "killed process"  →  OOM Killer
  │  ├─ dmesg | grep "segfault"         →  Coredump / SIGSEGV
  │  └─ journalctl -u сервис            →  systemd OOMPolicy
  │
  ├─ Процесс «висит» (не отвечает, не умирает)
  │  ├─ ps stat = Z  →  зомби (см. debugging.md)
  │  ├─ ps stat = D  →  блокировка I/O (NFS/disk)
  │  ├─ ps stat = T  →  остановлен сигналом (SIGSTOP)
  │  └─ kill -0 PID не работает  →  PID переиспользован
  │
  ├─ Процесс ест CPU
  │  ├─ pidstat -u 1 1  →  процент CPU
  │  ├─ top -H -p PID →  потоки
  │  └─ perf record   →  hot functions
  │
  ├─ Процесс ест память
  │  ├─ smem / smaps_rollup  →  PSS рост
  │  ├─ /proc/PID/oom_score  →  кандидатура на убийство
  │  └─ memleak (BCC)        →  источник утечки
  │
  └─ Процесс не стартует
     ├─ systemctl status      →  ошибка в юните
     ├─ strace — strace startup
     └─ journalctl -xe        →  ошибки инициализации
```

### Диагностические файлы /proc и их назначение

Сводка ключевых файлов procfs для быстрой диагностики:

| Файл | Назначение для SRE |
| :--- | :--- |
| `/proc/PID/status` | Состояние, UID/GID, маски сигналов, количество потоков, лимиты |
| `/proc/PID/limits` | Фактические rlimits (единственный источник истины) |
| `/proc/PID/cgroup` | Принадлежность к cgroup v1/v2 |
| `/proc/PID/smaps_rollup` | Сводка памяти: RSS, PSS, USS, Swap |
| `/proc/PID/oom_score` | Надо ли этому процессу убить |
| `/proc/PID/oom_score_adj` | Коррекция вероятности убийства (-1000..1000) |
| `/proc/PID/wchan` | Функция ядра, в которой процесс спит |
| `/proc/PID/stack` | Полный стек ядра (требует root) |
| `/proc/PID/fd/` | Открытые файлы и сокеты |
| `/proc/PID/io` | Статистика ввода-вывода |

## Практические сценарии

### Сценарии диагностики и отладки

| Проблема | Признаки | Первый шаг диагностики | Ссылка на решение |
| :--- | :--- | :--- | :--- |
| **Утечки памяти** | Рост RSS/PSS при стабильной нагрузке | `smem -rk -s pss` | [Отладка памяти](./debugging.md) |
| **Зомби-процессы** | Накопление `<defunct>` в `ps` | `ps aux \| awk '$8=="Z"'` | [Анализ зомби](./debugging.md) |
| **OOM Killer** | Завершение с кодом 137 | `dmesg -T \| grep "killed process"` | [Диагностика OOM](../oom_killer_diagnostics.md) |
| **Управление OOM** | Профилактика и настройка | `choom -p PID`, `systemctl show svc -p OOMScoreAdjust` | [Управление OOM](../oom_killer_management.md) |
| **Состояние D** | Процесс «висит» и не убивается | `cat /proc/PID/wchan` | [Анализ D-state](./debugging.md) |
| **Слишком много FD** | `EMFILE` / `ENFILE` | `ulimit -n`, `cat /proc/PID/limits` | [Лимиты файлов](../../../Diagnostics/Troubleshooting/troubleshooting_too_many_open_files.md) |
| **Утечка FD** | Рост открытых дескрипторов во времени | `ls /proc/PID/fd \| wc -l` | [Утечки FD](../../../Diagnostics/Troubleshooting/troubleshooting_file_descriptor_leaks.md) |
| **Аварийный крах** | `Segmentation fault` | `ulimit -c unlimited`, `coredumpctl` | [Coredump отладка](../../../Diagnostics/Troubleshooting/coredump_debugging.md) |
| **Высокий Context Switch** | Процесс потребляет CPU на переключениях | `pidstat -w` | [CPU диагностика](../../../Diagnostics/Processes/thread_cpu_troubleshooting.md) |
| **Вечный CPU** | 100% на одном потоке, нет I/O | `top -H -p PID`, `perf record` | [CPU profiling](../../../Diagnostics/Processes/thread_cpu_troubleshooting.md) |
| **Thread contention** | Медленная работа при многих потоках | `pidstat -t`, `perf lock` | [Конкурентность](../concurrency.md) |
| **Процесс не стартует** | `systemctl status` = failed | `journalctl -u svc --since "5 min ago"` | [Методология диагностики](../../../Diagnostics/Troubleshooting/general_troubleshooting_methodology.md) |
| **Сигналы не доставляются** | `kill -TERM` не работает | `grep Sig /proc/PID/status` | [Сигналы](../signals.md) |
| **CPU throttling** | Задержки кратные 100ms | `cat /sys/fs/cgroup/.../cpu.stat` | [Планирование](../scheduling.md) |
| **Fork-bomb / PID exhaustion** | `fork: Cannot allocate memory` | `ps -eo pid,comm \| wc -l`, `cat /proc/sys/kernel/pid_max` | [Сценарии мониторинга](../practical_scenarios.md) |

### Систематический чек-лист диагностики в Production

Алгоритм действий для SRE при любой проблеме с процессом. Выполнять последовательно, фиксируя результаты:

**Этап 1. Быстрая оценка (0–60 сек)**

```bash
# 1. Состояние хоста
uptime
# → load average: 0.52 0.48 0.55  — сравните с числом ядер (nproc)

# 2. Есть ли OOM-события?
journalctl -k --since "30 min ago" | grep -iE "oom|killed process"

# 3. Зомби / D-state?
ps -eo stat,pid,comm | awk '$1 ~ /Z|D/'

# 4. Свободно ли место / inode?
df -h && df -i

# 5. Состояние процесса
systemctl status <service>
# → Active: active (running) / failed / activating
```

**Этап 2. Микро-диагностика (1–5 мин)**

```bash
# Идентифицируем пид
PID=$(systemctl show --property=MainPID --value <service>)

# Проверяем состояние и состояние памяти
ps -p $PID -o pid,ppid,stat,%cpu,%mem,rss,vsz,comm
grep -E "VmRSS|VmSize|Threads" /proc/$PID/status

# Проверяем лимиты
grep -E "Max open files|Max processes" /proc/$PID/limits

# Проверяем маску сигналов
grep "Sig" /proc/$PID/status

# Проверяем cgroup
cat /proc/$PID/cgroup
```

**Этап 3. Глубокая диагностика (5–30 мин)**

```bash
# Память — детальный анализ через smaps_rollup
cat /proc/$PID/smaps_rollup | grep -E "Pss|Rss|Private_Dirty|Shared"

# I/O
cat /proc/$PID/io

# Открытые файлы / утечки
ls -la /proc/$PID/fd | wc -l
ls -la /proc/$PID/fd | head -20

# Стек ядра (если в D-state)
sudo cat /proc/$PID/stack 2>/dev/null
cat /proc/$PID/wchan

# Трассировка (осторожно в prod! используйте bpftrace)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat /pid == $PID/ { printf("%s\n", str(args->filename)); }'
```

**Этап 4. Валидация и исправление**

```bash
# Проверка после исправления
systemctl status <service>
journalctl -u <service> -n 50 --no-pager
# → Ищите новые ошибки или стабильность работы
```

### Техники восстановления

- **Восстановление удаленного бинарного файла:** Если исполняемый файл был удален с диска, но процесс запущен, его можно восстановить из `/proc/PID/exe`:
  ```bash
  cp /proc/<PID>/exe /path/to/restored_binary
  chmod +x /path/to/restored_binary
  ```
- **Заморозка процесса (CRIU):** Сохранение состояния процесса для миграции или отложенного анализа. Подробно: [**Работа с CRIU**](./checkpoint_restore.md).
- **Forensic coredump:** При падении процесса с `SIGSEGV` или `SIGABRT` система создает дамп памяти. Анализ через `coredumpctl gdb <PID>` с командами `bt`, `info locals`, `info registers`. Подробно: [**Отладка через Coredump**](../../../Diagnostics/Troubleshooting/coredump_debugging.md).
- **systemd-oomd (pre-emptive):** При превышении `memory.pressure` система автоматически завершает процессы. Диагностика через `journalctl -u systemd-oomd -f`. Подробно: [**Управление OOM Killer**](../oom_killer_management.md).
- **EarlyOOM fallback:** Для систем без systemd-oomd (старые дистрибутивы, ядра без PSI) — `earlyoom` или `nohang` как fallback.

## Дополнительная информация

### Безопасность при отладке

1. **Влияние strace:** Использование `strace` в продакшене замедляет процесс в десятки раз. Рекомендуется использовать **eBPF** инструменты (`bpftrace`) или `perf` для production-диагностики.

2. **Ptrace YAMA:** Современные системы ограничивают возможность подключения к чужим процессам (параметр `kernel.yama.ptrace_scope=1`). Для отладки:
   ```bash
   sudo sysctl -w kernel.yama.ptrace_scope=0    # временно (все потери безопасности)
   sudo sysctl -w kernel.yama.ptrace_scope=1    # вернуть после отладки
   ```

3. **Чувствительные данные:** Coredumps и трассировки могут содержать пароли и ключи в открытом виде. Ограничьте права доступа к директории с дампами (`chmod 700`), используйте `core_uses_pid`, настраивайте автоочистку через `tmpfiles.d`.

4. **Остановка процесса при attach:** `gdb attach` и `strace -p` останавливают процесс на время сессии. Для production предпочтительнее `gdb -batch` или `gcore` (снимок без долгой остановки).

5. **Контрольный список перед продакшн-отладкой:**
   - Согласовали с владельцем сервиса?
   - Есть ли бэкап/реплика?
   - Настроены ли таймауты health-check'ов (чтобы балансировщик не убил инстанс)?
   - Включен ли `OOMScoreAdjust=-1000` для критичного сервиса?

### Наблюдаемость и мониторинг процессов

Диагностика эффективна только при наличии данных. Обязательные метрики для SRE:

| Метрика | Источник | Порог | Что обнаружит |
| :--- | :--- | :--- | :--- |
| **Load Average** | `uptime`, `/proc/loadavg` | > N_cpu × 1.5 | Перегрузка CPU или I/O |
| **Zombie count** | `ps -eo stat \| grep -c Z` | > 0 | Проблемы с родительским процессом |
| **OOM kills** | `dmesg`, `/proc/vmstat` (`oom_kill`) | > 0 | Недостаток памяти |
| **FD usage** | `/proc/PID/fd`, `process_open_fds` | > 80% от лимита | Утечка дескрипторов |
| **PSI memory** | `/proc/pressure/memory` | `full avg10 > 5%` | Скорый давление на память |
| **Context switches** | `pidstat -w`, `/proc/PID/status` | spike | Блокировки или частые прерывания |
| **CPU throttling** | `cpu.stat` в cgroup | `nr_throttled > 0` | Циклические задержки |

Для централизованного сбора: `node_exporter` (Prometheus), `collectd`, или `sar`/`sysstat` с cron. Подробно: [**Методология USE**](../../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md).

### Лучшие практики Production

1. **Никогда не используйте `kill -9` как первую меру.** Сначала отправляйте `SIGTERM`, дайте приложению время на graceful shutdown (согласуйте таймаут), затем `SIGKILL`.

2. **Настраивайте `OOMScoreAdjust` для критичных сервисов.** Используйте отрицательные значения (`-500..-1000`) для БД, очередей, мониторинга. Через systemd: `OOMScoreAdjust=-500` в unit-файле.

3. **Используйте `tini`/`dumb-init` в контейнерах.** PID 1 в контейнере без init не обрабатывает сигналы и не реапит зомби. `docker run --init` решает эту проблему на уровне runtime.

4. **Ограничивайте ресурсы через cgroups.** `MemoryMax=`, `CPUQuota=`, `TasksMax=` в systemd-юнитах предотвращают «съедание» всех ресурсов одним сервисом.

5. **Не запускайте `strace` на production без согласования.** Используйте `bpftrace` или `perf` для нулевого или минимального влияния на работу сервиса.

6. **Документируйте шаги диагностики.** В пылу инцидента легко забыть, какой параметр меняли 10 минут назад. Используйте `history` и `script` для записи сессий.

7. **Автоматизируйте рутину.** Если диагностическая проверка занимает более 3 команд — оформите её в скрипт или systemd-таймер.

### Типовые ошибки и ограничения (Edge Cases)

1. **PID переиспользование (PID recycling):** После завершения процесса его PID может быть назначен новому процессу. Используйте `pidfd` (`pidfd_open` + `pidfd_send_signal`, Linux 5.3+) или `kill -0` в цикле с проверкой `/proc/PID/starttime`.

2. **Ранний сигнал vs. сигнал в обработчике:** Некоторые сигналы (например, `SIGCHLD`) могут быть потеряны, если процесс не установил обработчик до их генерации. Решение: всегда используйте `sigaction()` с флагом `SA_RESTART`.

3. **fork() в multithreaded приложении:** Вызов `fork()` в многопоточном процессе создает дочерний процесс с одним потоком — все остальные исчезают. Если они держали мьютексы, потомки могут зависнуть в deadlock. Используйте `vfork()` или `posix_spawn()` вместо `fork()` в многопоточном коде.

4. **D-state и reboot-less rescue:** Процесс в состоянии D не реагирует на сигналы. Единственные решения: восстановить I/O-подсистему (переподключить NFS, заменить диск) или перезагрузить. Для удалённых серверов — используйте IPMI/KVM для hard reset.

5. **Silent OOM в cgroup:** cgroups v2 убивает процесс внутри группы, если превышен `memory.max`, но PID 1 контейнера жив. `dmesg` может быть чист. Проверяйте `memory.events.local` в cgroup контейнера.

6. **Наследование rlimits:** Жесткие лимиты (hard limit) можно только понижать. После `exec()` лимиты сохраняются, но если родитель запустил процесс с `prlimit --nproc=100`, все дочерние унаследуют 100 даже если в unit-файле `LimitNPROC=65536`.

7. **`/proc` snapshot race:** Состояние процесса в `/proc` меняется во время чтения. Для согласованного снимка используйте `ps` (читает за один вызов) или `pidstat` (снимок с меткой времени).

### См. также

- [**Отладка процессов**](./debugging.md) — утечки памяти, зомби, coredump, D-state.
- [**Работа с CRIU (checkpoint/restore)**](./checkpoint_restore.md) — заморозка и миграция процессов.
- [**Практические сценарии мониторинга**](../practical_scenarios.md) — команды для SRE: Rapid Assessment, eBPF, fork-bomb, nsenter.
- [**Сигналы процессов**](../signals.md) — управление через сигнальное взаимодействие, маскирование.
- [**Механизм OOM Killer**](../oom_killer_mechanism.md) — теория, PSI, алгоритм выбора жертвы.
- [**Диагностика OOM Killer**](../oom_killer_diagnostics.md) — разбор логов, bpftrace, NUMA.
- [**Управление OOM Killer**](../oom_killer_management.md) — `oom_score_adj`, `choom`, `systemd-oomd`, overcommit.
- [**Концепции лимитов ресурсов**](../resource_limits_concepts.md) — rlimits иерархия, EMFILE/ENFILE.
- [**Управление лимитами (ulimit/prlimit)**](../ulimit_usage.md) — справочник по командам и флагам.
- [**Планирование процессов**](../scheduling.md) — CPU throttling, nice, cgroups.
- [**Трассировка и отладка**](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md) — strace, bpftrace, perf, gdb.