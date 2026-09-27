# Диагностика производительности CPU

## Определения

**CPU Performance Diagnostics** — процесс выявления узких мест процессора: от утилизации ядер до скрытых проблем с планировщиком, прерываниями и контекстными переключениями. Ключевой инструментарий: `mpstat`, `pidstat`, `vmstat`, `uptime`, `perf`, PSI.

**Saturation vs Utilization** — фундаментальное различие: **utilization** — процент времени, когда ядро выполняло задачи; **saturation** — количество процессов, ожидающих очереди на ядро. Высокая utilization без saturation нормальна; высокая saturation при любой utilization — проблема (очередь на CPU).

**Load Average (LA)** — среднее количество процессов в состоянии `TASK_RUNNING` и `TASK_UNINTERRUPTIBLE` (D-state) за 1, 5 и 15 минут. LA > количество ядер не означает проблему, если процессы в D-state (ожидание I/O). LA = 8 на 4 ядрах с `iowait=30%` — это I/O проблема, не CPU.

**Context Switch** — переключение планировщика с одного процесса на другой. **Voluntary** (`cswch/s`) — процесс сам отдал CPU (ожидание I/O,鎖). **Involuntary** (`nvcswch/s`) — ядро прервало процесс (истёк квант, высокая конкуренция). Высокий `nvcswch/s` указывает на то, что процессов больше, чем ядер могут обслужить.

**SoftIRQ (softirq)** — программные прерывания, обрабатываемые ядром в контексте прерывания (без переключения контекста). Основные: `NET_RX`/`NET_TX` (сеть), `TIMER` (таймеры), `SCSI` (диски). Высокий `%soft` в `mpstat` — признак перегрузки сетевого стека или дискового драйвера.

**Steal Time** — время, когда гипервизор забирает CPU у гостевой ВМ. `%steal > 5%` на виртуальной машине указывает на overselling CPU (noisy neighbor). На bare-metal `%steal` должен быть ≈0.

---

## Основные концепции

### USE-методология для CPU

| Ресурс | Utilization | Saturation | Errors |
|:---|:---|:---|:---|
| **CPU** | `mpstat -P ALL` → `%usr + %sys` | `vmstat` → `r` > nproc; PSI `cpu/any` | MCE, machine check exceptions |
| **MEMORY** | `free -m` → used/total | `vmstat` → `si/so`; PSI `memory/full` | OOM kill events |
| **DISK I/O** | `iostat -xz` → `%util` | `iostat` → `aqu-sz`; PSI `io/full` | I/O errors в `dmesg` |
| **NETWORK** | `sar -n DEV` → rxKB/s, txKB/s | `ss -s` → overflow; `nstat` → drops | `ethtool -S` → errors |

### Алгоритм быстрой оценки CPU

```bash
# Шаг 1: Load Average и общая картина
uptime && vmstat 1 3

# Шаг 2: Per-CPU разбивка
mpstat -P ALL 1 3

# Шаг 3: Контекстные переключения и процессы
pidstat -w 1 3

# Шаг 4: PSI — реальное давление
cat /proc/pressure/cpu

# Шаг 5: Поиск горячего процесса
top -H -bn1 | head -20
```

### Интерпретация mpstat

```
$ mpstat -P ALL 1
CPU    %usr   %nice  %sys   %iowait  %irq   %soft  %steal  %guest  %idle
all    45.00   0.00  12.00    3.00    0.00    1.50    0.00    0.00   38.50
  0    90.00   0.00   8.00    1.00    0.00    0.50    0.00    0.00    0.50
  1     2.00   0.00  15.00    5.00    0.00    3.00    0.00    0.00   75.00
```

| Метрика | Порог (норма) | Порог (критично) | Действие |
|:---|:---|:---|:---|
| `%usr` | < 70% | > 85%持續но | `perf top -g` → поиск hotspots в userspace |
| `%sys` | < 25% | > 35%持續но | `pidstat -u 1` → sys = overhead или kernel workload |
| `%iowait` | < 5% | > 15% | `iostat -xz 1` → локализация диска |
| `%soft` | < 10% | > 20% | `/proc/softirqs` → NET_RX/NET_TX или SCSI |
| `%steal` | < 1% | > 5% | Миграция на dedicated instance или другой гипервизор |
| `%irq` | < 5% | > 10% | `/proc/interrupts` → проверка hardware IRQ |

### Интерпретация load average

```bash
$ uptime
 14:20:01 up 45 days, load average: 8.50, 6.20, 3.80

$ nproc
4
```

**Правило:** LA / nproc > 1.5持续но = CPU saturation.

| Ситуация | LA | nproc | %iowait | Вердикт |
|:---|:---|:---|:---|:---|
| Норма | 1.2 | 4 | 1% | OK |
| CPU-bound | 12.0 | 4 | 2% | Критично: 3× превышает ядра |
| I/O-bound | 8.0 | 4 | 35% | Проблема с диском, не CPU |
| Mixed | 5.0 | 4 | 10% | Смешанная: CPU + I/O |

**Важно:** Первая строка (1 min) — актуальная нагрузка. Третья (15 min) — тренд. Если `8.50, 6.20, 3.80` — нагрузка растёт. Если `3.80, 6.20, 8.50` — снижается.

### Context switches: voluntary vs involuntary

```bash
$ pidstat -w 1
Linux 6.1.0-23     09/15/26     _x86_64_    (8 CPU)

14:30:01      UID    PID   cswch/s   nvcswch/s  Command
14:30:02        0      1      0.50        0.00    systemd
14:30:02        0   1234     15.20      120.50    java
14:30:02        0   5678     85.00        2.10    nginx
```

| Метрика | Норма | Высокое значение | Причина |
|:---|:---|:---|:---|
| `cswch/s` | < 50 | > 500 | I/O-bound приложение, много мелких операций |
| `nvcswch/s` | < 10 | > 100 | CPU oversubscription: процессов больше, чем ядер |

**`nvcswch/s` > 100** для критичного приложения = приложение получает меньше CPU, чем ему нужно. Решения: `taskset`/`cpuset`, увеличение CPU limits, уменьшение числа потоков.

### SoftIRQ: определение источника

```bash
# Текущая статистика softirq
$ cat /proc/softirqs | column -t
                   CPU0       CPU1       CPU2       CPU3
HI_SOFTIRQ:         0          0          0          0
TIMER_SOFTIRQ:   1250432    1248001    1249553    1247890
NET_TX_SOFTIRQ:  45210      44890      45100      44950
NET_RX_SOFTIRQ:  892041     875620     889340     882100
BLOCK_SOFTIRQ:    12450      12380      12410      12390
IRQ_POLL_SOFTIRQ: 0          0          0          0
TASKLET_SOFTIRQ:  2890       2850       2870       2860
SCHED_SOFTIRQ:   312450     310200     311800     310500
HRTIMER_SOFTIRQ:  0          0          0          0
RCU_SOFTIRQ:     452100     448900     451200     449800
```

```bash
# Динамическое наблюдение
$ watch -d -n 1 'cat /proc/softirqs | grep -E "NET_RX|NET_TX|BLOCK|SCHED"'
```

| SoftIRQ | Высокий при | Диагностика |
|:---|:---|:---|
| `NET_RX` | Высокий network packet rate | `ethtool -S eth0`, irqbalance, RSS/RPS |
| `NET_TX` | Высокий tx rate, TC qdisc | `tc -s qdisc show`, `sar -n DEV` |
| `BLOCK` | Дисковые операции | `iostat -xz 1`,blktrace |
| `SCHED` | Больше процессов, чем ядер | `vmstat` → `r`, `pidstat -w` |

### Steal time: диагностика

```bash
# Быстрая проверка
$ mpstat -P ALL 1 3 | awk '/^Average/ && $NF < 95 {print "Steal:", $(NF-2)}'

# Детальная проверка на KVM
$ dmesg | grep -iE "steal|kvm.*time|vcpu.*preempt"

# Проверка типа виртуализации
$ virt-what
# → kvm, xen, vmware...
```

| %steal | Действие |
|:---|:---|
| 0–1% | Норма |
| 1–5% | Мониторинг, возможна деградация latency |
| 5–10% | Миграция на dedicated instance или другой AZ |
| > 10% | Критично: гипервизор перегружен, немедленная миграция |

---

## Практические сценарии

### Сценарий 1: «Сервер тормозит, CPU свободен»

**Симптом:** Пользователи жалуются на задержки, но `top` показывает `Cpu(s): 15% us, 5% sy`.

**Алгоритм:**
```bash
# 1. Load average
uptime
# → load average: 12.50, 10.20, 8.80  (при 4 ядрах)

# 2. PSI — есть ли давление?
cat /proc/pressure/cpu
# → some avg10=45.20 avg60=32.10 avg300=15.05

# 3. Процессы в очереди
vmstat 1 3
# → r=12 (при 4 ядрах — 3× превышение)

# 4. Кто в очереди?
pidstat -w 1 5
# → java: nvcswch/s=450 (принудительные переключения)

# 5. Почему? — 8 Java-потоков на 4 ядра
ps -eLf | grep java | wc -l
# → 12 потоков java
```

**Решение:** Уменьшить число worker-потоков до `nproc * 1.5` или увеличить CPU limits в контейнере.

### Сценарий 2: Высокий %sys в mpstat

**Симптом:** `mpstat` показывает `%sys = 40%`.

**Алгоритм:**
```bash
# 1. Кто потребляет system time?
pidstat -u 1 5 | sort -k4 -rn | head -5

# 2. Проверка системных вызовов
strace -c -p <PID> -e trace=all
# → top syscall: futex (много блокировок)

# 3. Проверка context switches
pidstat -w -p <PID> 1
# → cswch/s=800, nvcswch/s=200

# 4. Проверка softirq
mpstat -P ALL 1 3
# → %soft=25% на одном ядре

# 5. Кто генерирует softirq?
cat /proc/softirqs | grep NET_RX
# → CPU0: 500000 (на остальных: ~5000)
```

**Решение:**
- Если `softirq` на одном ядре → настроить `irqbalance` или RSS/RPS
- Если `futex` в strace → проблема в userspace блокировках (lock contention)
- Если context switches > 1000/s → оптимизировать архитектуру приложения

### Сценарий 3: Thermal throttling

**Симптом:** CPU работает на пониженных частотах, приложение медленное.

**Алгоритм:**
```bash
# 1. Проверка частот
cat /proc/cpuinfo | grep "cpu MHz" | head -4
# → 1200.000 (вместо 3500)

# 2. Проверка thermal
cat /sys/class/thermal/thermal_zone*/temp
# → 95000 (95°C — критично)

# 3. Проверка dmesg
dmesg | grep -iE "thermal|throttl|overheat"
# → thermal: cpu cooling device state updated: 95 C -> throttled

# 4. Проверка C-states
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# → powersave (вместо performance)
```

**Решение:**
- Включить `performance` governor: `cpupower frequency-set -g performance`
- Проверить охлаждение сервера
- Для production: `tuned-adm profile throughput-performance`

### Сценарий 4: IRQ affinity problem

**Симптом:** Одно ядро загружено на 100%, остальные простаивают.

**Алгоритм:**
```bash
# 1. Распределение IRQ
cat /proc/interrupts | head -5
# → CPU0: 1500000  IRQ0-NIC

# 2. Проверка irqbalance
systemctl status irqbalance
# → inactive (отключен)

# 3. Ручная привязка IRQ
echo 2 > /proc/irq/32/smp_affinity  # Привязать IRQ32 к CPU1
```

**Решение:**
- Включить `irqbalance`: `systemctl enable --now irqbalance`
- Или ручная настройка: `echo <mask> > /proc/irq/<IRQ>/smp_affinity`
- Для high-load: `irqbalance --banlist=0-3` (запретить балансировку на ядра 0-3, оставить для приложения)

---

## Дополнительная информация

### Связанные темы

- [**perf**](./perf.md) — профилирование CPU через PMU и tracepoints
- [**sar**](./sar.md) — исторические данные CPU
- [**atop**](./atop.md) — комплексный мониторинг с歷史
- [**Диагностика Tail Latency**](./diagnosing_tail_latency.md) — p99/p99.9 анализ
- [**diagnosing_tail_latency**](./diagnosing_tail_latency.md) — CFS throttling, off-CPU
- [**sysctl production**](../../Core/kernel/sysctl_production.md) — параметры ядра для production
- [**pidstat**](../Processes/pidstat.md) — детальный мониторинг процессов
- [**vmstat**](../Memory/vmstat.md) — статистика виртуальной памяти
- [**Планировщик**](../../Core/processes/scheduling.md) — CFS, nice, RT
- [**NUMA awareness**](../../Core/processes/numa_awareness.md) — NUMA-оптимизация
- [**cpu_pinning**](../../Core/cpu_pinning.md) — привязка процессов к ядрам
- [**Flame graphs**](./perf.md#flame-graphs) — визуализация CPU-профилей

### Чек-лист быстрой диагностики CPU

```bash
# 1. Load + общая картина
uptime && vmstat 1 3

# 2. Per-CPU
mpstat -P ALL 1 3

# 3. Context switches
pidstat -w 1 3

# 4. PSI
cat /proc/pressure/cpu

# 5. Top processes
top -H -bn1 | head -15

# 6. Если %soft высокий
cat /proc/softirqs | column -t

# 7. Если steal > 0
mpstat -P ALL 1 3 | grep -v CPU | awk '{if($(NF-2) > 1) print}'
```

### Частые ошибки интерпретации

| Ошибка | Верное понимание |
|:---|:---|
| `LA > nproc` = CPU overload | Нет: LA включает D-state (I/O). Смотрите `vmstat` → `r` и `%iowait` |
| `%usr + %sys = 100%` = проблема | Нет: это нормальная утилизация. Проблема если нет результата (throughput) |
| `top` показывает 100% CPU | Это один процесс. На 8 ядрах 100% одного = 12.5% общего |
| `iowait = 0%` = нет I/O проблем | Нет: `iowait` не показывает I/O на idle CPU. Используйте PSI `io` |
| `nvcswch/s` > 0 = плохо | Нет: нормально при конкуренции. Проблема если > 100持续но для latency-sensitive |
