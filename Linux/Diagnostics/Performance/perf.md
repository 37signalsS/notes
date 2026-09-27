# `perf` (Performance Events for Linux)

## Определение

**`perf`** — официальный и наиболее мощный инструмент профилирования производительности в ОС Linux, поставляемый непосредственно в составе исходного кода ядра. Он использует аппаратные счётчики производительности процессора (Performance Monitoring Units, PMU), программные точки трассировки (tracepoints) и механизмы динамического зондирования (kprobes/uprobes) для глубокого анализа работы системы. `perf` позволяет диагностировать проблемы на всех уровнях: от конкретных ассемблерных инструкций и промахов кэша до задержек планировщика и блокировок в приложении.

## Основные концепции

### Типы отслеживаемых событий (`perf list`)

`perf` поддерживает тысячи событий, разделенных на категории:
- **Hardware Events:** События PMU процессора (циклы CPU, выполненные инструкции, промахи кэша L1/LLC, неверные предсказания ветвлений).
- **Software Events:** Программные счетчики ядра (переключения контекста, ошибки страниц, миграции процессов).
- **Tracepoints:** Статические точки трассировки, встроенные в код ядра (система `ftrace`), например, события планировщика или системные вызовы.
- **Dynamic Probes:** Динамически устанавливаемые точки в ядре (`kprobes`) или пользовательских библиотеках/бинарниках (`uprobes`).

### Режимы работы

1. **Сэмплирование (Sampling):** Периодическое снятие «снимков» (например, 99 раз в секунду). Позволяет статистически определить нагрузку с минимальными накладными расходами (обычно < 1%). Основной инструмент для поиска «горячего» кода.
2. **Счётчики (Counting):** Точный подсчёт общего количества событий за определенный интервал времени (используется в `perf stat`).
3. **Трассировка (Tracing):** Запись каждого возникновения события (например, каждого системного вызова). Может создавать значительную нагрузку при высокой частоте событий.

## Предварительные требования

### Установка

На большинстве дистрибутивов `perf` поставляется отдельным пакетом, так как не может быть включён в стандартное ядро из-за размера:

```bash
# Ubuntu/Debian
apt-get install linux-tools-$(uname -r) linux-tools-common linux-tools-generic

# RHEL/CentOS/Fedora
yum install perf
# или
dnf install perf

# openSUSE
zypper install linux-tools

# Arch Linux
pacman -S perf
```

### Проверка установки

```bash
# Версия perf
perf --version
# → perf version 6.8.0

# Доступные события PMU
perf list | head -20

# Проверка доступности PMU
perf stat -e cycles sleep 1
# → 1,234,567 cycles                    #    0.123 GHz
```

### Настройка прав доступа для не-root пользователей

Настройка прав доступа через `/proc/sys/kernel/perf_event_paranoid`:

| Значение | Описание |
| :--- | :--- |
| **`2`** | Только пользовательские события (запрещен доступ к CPU-counters для ядра). Значение по умолчанию на большинстве дистрибутивов. |
| **`1`** | Разрешен доступ к CPU-counters для ядра и приложений (рекомендуется для профилирования). |
| **`0`** | Дополнительный доступ к данным `ftrace`. |
| **`-1`** | Полный доступ без ограничений. |

```bash
# Временное изменение (до перезагрузки)
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid

# Постоянное изменение
echo "kernel.perf_event_paranoid = 1" | sudo tee /etc/sysctl.d/99-perf.conf
sudo sysctl -p /etc/sysctl.d/99-perf.conf
```

### Установка символов отладки

Без символов отладки `perf report` будет показывать `[unknown]` вместо имён функций:

```bash
# Ubuntu/Debian: установка debug-символов для ядра
apt-get install linux-image-$(uname -r)-dbgsym

# Для приложений
apt-get install myapp-dbg
# или через debuginfod (современный подход)
apt-get install debuginfod
```

### Проверка поддержки PMU

```bash
# Проверка наличия PMU процессора
dmesg | grep -i "performance monitor"
# → Performance Events: ...

# Проверка доступных событий
perf list | grep -i "cpu_core\|cpu_atom"
```

## Практические сценарии

### Анализ микроархитектурной эффективности (`perf stat`)

Позволяет оценить IPC (Instructions Per Cycle) и узкие места конвейера.

```bash
# Общая статистика IPC и кэша
perf stat -e cycles,instructions,cache-misses,cache-references <команда>

# Top-Down анализ (TMA) для выявления Front-End или Back-End ограничений
perf stat --topdown -a sleep 10
```
> **Метрика IPC:** Значение < 1.0 обычно указывает на то, что процессор «простаивает» в ожидании данных из памяти (Stalled). Хороший показатель — 1.5 и выше.

### Профилирование гибридных процессоров (P- и E-ядра)

В современных архитектурах (Intel Alder Lake+) важно разделять события между ядрами.

```bash
# Сбор циклов отдельно для производительных (P) и эффективных (E) ядер
perf stat -e cpu_core/cycles/,cpu_atom/cycles/ -a sleep 5
```

### Поиск «горячих» путей в коде (`perf record`)

```bash
# Запись профиля с графом вызовов (-g) для всей системы (-a) на 30 секунд
sudo perf record -F 99 -g -a -- sleep 30

# Интерактивный анализ результатов
sudo perf report
```

### Трассировка инструкций с низким оверхедом (Intel PT)

Intel Processor Trace записывает поток выполнения инструкций почти без влияния на производительность.

```bash
# Трассировка только пользовательского пространства для конкретной функции
sudo perf record -e intel_pt//u --filter 'filter main' -- ./app

# Декодирование и просмотр стека вызовов
sudo perf script --insn-trace --call-trace
```

### Анализ «Off-CPU» (Почему процесс ждет?)

Использование eBPF-скриптов в составе `perf` для диагностики блокировок и ожидания I/O.

```bash
# Запись времени, проведенного процессом вне CPU
sudo perf record -e sched:sched_switch -g -p <PID> -- sleep 10

# Анализ задержек планировщика
sudo perf sched latency
```

### Визуализация через Flame Graphs

Превращает текстовый отчет в интерактивную карту «горячих» вызовов.

```bash
# 1. Сбор данных
sudo perf record -F 99 -ag -- sleep 30

# 2. Обработка (требуется инструментарий FlameGraph)
perf script | stackcollapse-perf.pl | flamegraph.pl > profile.svg
```

### Живое профилирование (`perf top`)

`perf top` показывает «горячие» функции в реальном времени, аналогично `top`, но на уровне функций, а не процессов.

```bash
# Профилирование всей системы
sudo perf top -g --all-cpus

# Профилирование конкретного процесса
sudo perf top -g -p <PID>

# Профилирование конкретного потока
sudo perf top -g -t <TID>
```

### Сравнение профилей (`perf diff`)

Используется для выявления регрессий между двумя запусками.

```bash
# Первый запуск (baseline)
sudo perf record -F 99 -g -a -- sleep 30
sudo perf archive baseline.perf.data

# Второй запуск (после изменений)
sudo perf record -F 99 -g -a -- sleep 30
sudo perf archive after.perf.data

# Сравнение
perf diff baseline.perf.data after.perf.data
# → Функции с положительным delta % ухудшили производительность
```

### Профилирование доступа к памяти (`perf mem`)

Анализирует паттерны доступа к памяти: Load/Store, кэш-промахи, т.н. «cacheline bouncing».

```bash
# Профилирование всей системы
sudo perf mem record -a -- sleep 10

# Отчет с сортировкой по количеству промахов
sudo perf mem report --sort=dso,symbol
```

### Анализ кэш-конфликтов (`perf c2c`)

Обнаруживает False Sharing — когда разные потоки на разных ядрах изменяют данные в одной кэш-линии.

```bash
# Сбор данных о кэш-конфликтах
sudo perf c2c record -p <PID> -- sleep 30

# Анализ: какие ядра и адреса конфликтуют
sudo perf c2c report
```

### Профилирование утечек памяти в ядре (`perf kmem`)

Анализирует аллокации и освобождения памяти в ядре.

```bash
# Запись событий slab allocator
sudo perf kmem record -a -- sleep 10

# Топ аллокаций по размеру
sudo perf kmem stat
```

### Постмортем анализ и CI/CD интеграция

Для SRE важно иметь воспроизводимый пайплайн:

```bash
# 1. Сбор профиля на production (или staging)
sudo perf record -F 99 -g -p <PID> -- sleep 30
sudo perf archive /tmp/perf-$(date +%Y%m%d).perf.data

# 2. Перенос на dev-машину для анализа
scp server:/tmp/perf-*.perf.data /tmp/
perf report -i /tmp/perf-*.perf.data

# 3. Генерация flamegraph для отчета
perf script | stackcollapse-perf.pl | flamegraph.pl > /tmp/report.svg
```

Для автоматизации в CI/CD можно добавить perf-бенчмарк как gate:

```bash
# В Makefile или CI-скрипте
perf stat -e instructions,cycles,cache-misses ./myapp_test > /tmp/perf-baseline.txt 2>&1
# Сравнение с baseline: отклонение > 5% = fail
```

## Устранение неисправностей

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `perf: PMU not supported` | PMU отключен в BIOS, несовместимый CPU, NMI watchdog конфликт | `dmesg | grep -i perf`, `perf list` | Включить PMU в BIOS, отключить `nmi_watchdog` |
| `perf: Permission denied` | `perf_event_paranoid >= 2` или отсутствие прав | `cat /proc/sys/kernel/perf_event_paranoid` | Уменьшить `perf_event_paranoid` или использовать `sudo` |
| `perf: No samples` | Процесс простаивал, слишком короткая запись, неверный PID | Увеличить длительность `sleep`, проверить `top -p <PID>` | Увеличить интервал записи, проверить что процесс активен |
| `perf: No hardware sampling` | CPU не поддерживает hardware sampling, ядро собрано без `CONFIG_PERF_EVENTS` | `perf list hardware` | Использовать software events (`-e cycles:u`) или пересобрать ядро |
| `perf report: [unknown]` | Бинарник stripped, нет debug-info | `file /path/to/binary` | Установить `*-dbg` пакеты, перекомпилировать с `-g` |
| `perf: Invalid argument` | Неподдерживаемое событие для данного CPU | `perf list \| grep <event>` | Использовать универсальные события (`cycles`, `instructions`) |
| `perf.data слишком большой` | Слишком высокая частота сэмплирования или Intel PT без фильтров | `ls -lh perf.data` | Уменьшить `-F`, добавить фильтры, использовать `perf archive` |
| `perf stat: <not supported>` | Событие недоступно на данном CPU | Проверить `perf list` | Использовать общие события (`cpu-cycles`, `instructions`) |
| NMI watchdog конфликт | `nmi_watchdog` использует тот же PMU counter | `perf top` падает с `No hardware sampling` | Отключить: `echo 0 | sudo tee /proc/sys/kernel/nmi_watchdog` |
| `perf record` падает при `-a` | Нет прав root, слишком много ядер | `sudo perf record` | Записать по одному процессу (`-p`) или использовать `--no-big-num` |

## Рекомендации

### Best Practices

1. **Частота сэмплирования:** Используйте `-F 99` (по умолчанию 4000 Гц может давать лишний оверхед). Для long-running записей достаточно 99–250 Гц.
2. **System-wide vs Process:** `-a` даёт полную картину, но создаёт больше данных. Для production-диагностики конкретного сервиса используйте `-p <PID>`.
3. **Граф вызовов:** Флаг `-g` добавляет ~10% оверхеда, но необходим для flamegraph и понимания контекста. Для быстрого `perf top` можно обойтись без него.
4. **Symbol resolution:** Убедитесь, что debug-символы установлены ДО записи профиля. `perf record` записывает адреса, а `perf report` разрешает их — если символы появились позже, данные не восстановятся.
5. **Анализ на dev-машине:** Копируйте `perf.data` на машину с debug-символами. Используйте `perf archive` для автоматической упаковки зависимостей.
6. **perf в контейнерах:** Для записи в контейнере используйте `--pid <PID>` хоста, а не `-a` (требует `--privileged` или `SYS_ADMIN`). Или монтируйте `/proc` и `/sys` read-only.
7. **Ограничение размера:** Для длительных записей используйте `--switch-output` (ядро >= 4.7) или ограничьте размер через `perf record --switch-output=time=60s`.
8. **Верификация:** После `perf record` проверяйте вывод:
   ```bash
   # Убедитесь, что данные записаны
   ls -lh perf.data
   # → -rw-r--r-- 1 root root 1.2M ... perf.data
   ```

### Методология диагностики (SRE)

1. **Локализация:** `top -H -p <PID>` / `pidstat -t -p <PID> 1` → найти TID.
2. **Быстрый взгляд:** `perf top -g -t <TID>` → понять, в какой функции процесс проводит время.
3. **Точная запись:** `perf record -F 99 -g -t <TID> -- sleep 10` → запись для офлайн-анализа.
4. **Анализ:** `perf report` → идентификация Hot Spot'а.
5. **Проверка блокировок:** `perf lock contention` (если `%sys` высокий).
6. **Финальный анализ:** Flamegraph или `perf annotate` для построчного анализа.

## Ограничения и особенности

### Аппаратные ограничения

- **PMU Counters:** Количество аппаратных счётчиков ограничено (обычно 4–8 на ядро). `perf` автоматически мультиплексирует события при превышении лимита, что снижает точность. Для максимальной точности ограничьтесь 3–4 событиями за один запуск.
- **NMI Watchdog Conflict:** На многих дистрибутивах `nmi_watchdog` использует один из PMU счётчиков. При конфликте отключайте watchdog: `echo 0 | sudo tee /proc/sys/kernel/nmi_watchdog`.
- **Ядерные потоки (KThread):** Потоки `kworker`, `ksoftirqd` не имеют Userspace-стека. `perf` видит только пути ядра. Для их анализа используйте `bpftrace` или `perf kvm`.
- **Гибридные CPU:** На Intel Alder Lake+ и ARM big.LITTLE события имеют разные имена для P- и E-ядер (`cpu_core/` vs `cpu_atom/` на Intel). Указывайте явно.

### Программные ограничения

- **perf_event_paranoid:** Значение `2` блокирует доступ к CPU-counters для непривилегированных пользователей. Для production-серверов с APM-агентами используйте значение `1` + `CAP_PERFMON` (ядро 5.8+).
- **Символы отладки:** `perf report` требует debug-символов. Для JIT-языков (Java, Node.js) используйте `perf jit` или языко-специфичные инструменты (`async-profiler`, `py-spy`).
- **Оверхед трассировки:** Трассировка каждого системного вызова (`perf trace`) создаёт нагрузку comparable со `strace`. Используйте только на коротких интервалах.
- **Intel PT:** Генерирует сотни мегабайт данных в секунду. Без фильтров по адресу может заполнить диск за секунды. Используйте `--filter` для ограничения.

### Особенности в контейнерах

- В контейнере без `--privileged` и `CAP_SYS_ADMIN` `perf record -a` работать не будет.
- Используйте `-p <PID>` для записи конкретного процесса, если PID namespace совпадает.
- Для доступа к событиям ядра из контейнера требуется монтировать `/proc` и `/sys`.

### Особенности на виртуализации

- **Steal Time:** На виртуализированных хостах (KVM, VMware) высокий `%st` в `mpstat` означает, что гипервизор забирает CPU. `perf` будет регистрировать это как idle-время. Диагностика: `mpstat -P ALL 1`.
- **NMI и гипервизор:** Некоторые гипервизоры (KVM с `-cpu host`) корректно пробрасывают PMU, другие (VirtualBox) — нет. Проверяйте `perf list` внутри VM.

## Дополнительная информация

### Разрешение символов (Symbols)

Если вместо имен функций отображается `[unknown]` или шестнадцатеричные адреса:
1. **Ядро:** Проверьте доступ к `/proc/kallsyms` и наличие пакетов `linux-image-*-dbgsym`.
2. **Приложения:** Бинарные файлы не должны быть «очищены» (stripped). Используйте флаги `-g` или `-fno-omit-frame-pointer` при компиляции.
3. **JIT-языки (Java, Node.js, V8):** Требуется генерация map-файлов (например, `/tmp/perf-<PID>.map`). Для Java рекомендуется использовать `async-profiler` как более нативную альтернативу для JVM.
4. **Rust/Go:** Современные версии `perf` (6.x+) нативно поддерживают DWARF-символы для этих языков.

### Влияние на производительность (Overhead)

`perf` значительно эффективнее `strace`, так как фильтрация и агрегация происходят в ядре. Однако:
- Сэмплирование с частотой > 1000 Гц может вызвать заметный оверхед на слабых системах.
- Трассировка (Tracing) часто возникающих событий (например, каждого сетевого пакета) может замедлить систему.
- Intel PT может генерировать сотни мегабайт данных в секунду — используйте фильтры по адресу.

### Flame Graphs (Графики пламени)

Flame graph — визуализация CPU-профилей, показывающая горячие пути (hot paths) в стеке вызовов. Ширина прямоугольника пропорциональна количеству сэмплов (времени), проведённому в данной функции. **Это основной способ представления результатов `perf` на собеседованиях и в продакшене.**

#### Генерация Flame Graph

```bash
# 1. Запись профиля
sudo perf record -F 99 -g -p <PID> -- sleep 30

# 2. Конвертация в текстовый формат
sudo perf script > perf_stacks.txt

# 3. Установка FlameGraph toolkit
git clone https://github.com/brendangregg/FlameGraph.git
export PATH=$PWD/FlameGraph:$PATH

# 4. Генерация SVG
stackcollapse-perf.pl perf_stacks.txt | flamegraph.pl > flamegraph.svg

# 5. Открытие в браузере
# open flamegraph.svg
```

#### Однострочник

```bash
sudo perf record -F 99 -g -p <PID> -- sleep 30 && \
sudo perf script | stackcollapse-perf.pl | flamegraph.pl > /tmp/flamegraph.svg
```

#### Differential Flame Graphs (сравнение «до/после»)

```bash
# До оптимизации
sudo perf record -F 99 -g -p <PID> -- sleep 30
sudo perf script > before.txt
stackcollapse-perf.pl before.txt > before.folded

# После оптимизации
sudo perf record -F 99 -g -p <PID> -- sleep 30
sudo perf script > after.txt
stackcollapse-perf.pl after.txt > after.folded

# Сравнение: красный = стало хуже, синий = стало лучше
difffolded.pl before.folded after.folded | flamegraph.pl > differential.svg
```

#### Off-CPU Flame Graphs (где приложение «спит»)

```bash
# Требует BPF (bcc-tools)
sudo offcputime-bpfcc -p <PID> -f 30 | flamegraph.pl > offcpu.svg

# Или через bpftrace
sudo bpftrace -e '
kprobe:finish_task_switch {
    @[kstack] = count();
}' > offcpu.folded
```

#### Интерпретация

| Паттерн в flame graph | Значение | Действие |
|:---|:---|:---|
| Широкий прямоугольник на вершине | Горячая функция userspace | Оптимизация алгоритма |
| Глубокий стек с узкими прямоугольниками | Много вложенных вызовов | Возможна оптимизация стека |
| Широкий прямоугольник в `kernel:` | Системные вызовы | `strace -c` для детализации |
| `__GI___pthread_mutex_lock` | Lock contention | Оптимизация блокировок |
| `futex_wait_queue` | Ожидание мьютекса | Проблема с concurrency |
| `__nanosleep` / `epoll_wait` | Off-CPU (приложение спит) | Off-CPU profiling |

#### Контекстные ссылки

- **Continuous profiling:** [Continuous Profiling](../../Concepts/continuous_profiling.md) — Pyroscope, Parca, eBPF-based
- **Профилирование: глубокое погружение:** [Profiling Deep Dive](../../Concepts/Observability_and_Monitoring/profiling_deep_dive.md) — on-demand vs continuous
- **Java:** `async-profiler` для генерации flame graphs: `./profiler.sh -d 30 -f cpu.html -o flamegraph <PID>`
- **Python:** `py-spy record -o flame.svg --duration 30 --pid <PID>`
- **Go:** `go tool pprof -http=:8080 cpu.prof` (интерактивный flame graph)

### См. также

- [Поиск проблемного потока](../Processes/thread_cpu_troubleshooting.md) — связка `top` и `perf` на уровне TID.
- [Трассировка и отладка в Linux](../Troubleshooting/tracing_and_debugging.md) — `strace`, `bpftrace`, `ltrace`.
- [Диагностика CPU](./cpu_performance_diagnostics.md) — анализ CPU utilization, saturation, context switches.
- [Диагностика Tail Latency](./diagnosing_tail_latency.md) — off-CPU profiling, PSI.
