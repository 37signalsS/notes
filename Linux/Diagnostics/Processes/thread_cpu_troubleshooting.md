# Поиск потока, потребляющего CPU внутри процесса

## Определения

*   **TID (Thread ID)** — уникальный идентификатор потока на уровне ядра Linux (также называется **LWP — Light Weight Process**). В рамках одного процесса (PID) каждый поток имеет свой TID.
*   **PID (Process ID)** — идентификатор основного процесса (лидера группы потоков).
*   **Call Graph (Граф вызовов)** — иерархическая структура вызовов функций, позволяющая отследить путь выполнения кода от точки входа до текущего состояния.
*   **Hot Spot** — участок кода (функция), в котором программа проводит большую часть времени при высокой нагрузке.
*   **User CPU (%usr)** — время, затраченное на выполнение кода в пространстве пользователя (Userspace). Включает логику приложения, библиотеки, JIT-компиляцию.
*   **System CPU (%sys)** — время, затраченное на выполнение системных вызовов в пространстве ядра (Kernelspace). Рост `%sys` без роста `%usr` часто указывает на интенсивные syscall'ы, контенденцию блокировок (futex), или активность в прерываниях (softirq).
*   **CPU Affinity (маска affinity)** — привязка потока к конкретным ядрам CPU. Поток может выполняться только на ядрах, входящих в маску. Изменение affinity влияет на попадание в кэш процессора (cache locality).
*   **Off-CPU** — время, которое поток провёл вне процессора (в ожидании блокировки, I/O, планировщика). Анализ Off-CPU важен, когда приложение «медленное», но не «горячее».
*   **Kernel Thread (KThread)** — поток, выполняющийся только в пространстве ядра (нет адресного пространства Userspace). Обнаружаются в `ps -eLf` как команда `[kthreadd]`, `[kworker/...]`, `[ksoftirqd]`.
*   **Context Switch (CS)** — переключение планировщика с одного потока на другой. Добровольный CS (`cswch/s`) — поток сам отдаёт CPU (ожидание I/O, сокета). Принудительный CS (`nvcswch/s`) — ядро прерывает поток по таймауту кванта.

## Основные концепции

### Почему поток потребляет 100% CPU

Высокая нагрузка на конкретный поток обычно вызвана одной из следующих причин:
*   **Busy Loop (Бесконечный цикл):** ошибка логики, при которой поток выполняет пустые или повторяющиеся операции без пауз (`sleep` или ожидания событий).
*   **Spin-lock (Спин-блокировка):** поток постоянно опрашивает флаг блокировки вместо того, чтобы уйти в режим ожидания (Sleeping). Это эффективно для очень коротких задержек, но губительно при долгой конкуренции за ресурс.
*   **Активная обработка данных:** выполнение тяжёлых математических вычислений, шифрования, компрессии или компиляции JIT-кода.
*   **Lock Contention (Конкуренция за блокировки):** ситуация, когда множество потоков одновременно пытаются захватить одну блокировку (например, `mutex`), что приводит к деградации производительности. В этом случае нагрузка часто смещается в `%sys` из-за работы планировщика и футексов.
*   **CPU Throttling (cgroups):** поток может показывать стабильную нагрузку не из-за жадности, а потому что cgroup v2 (`cpu.max`) ограничил его кванты, и он тратит время в ожидании очереди планировщика. Проверьте `/sys/fs/cgroup/.../cpu.stat`.
*   **Обработка прерываний (SoftIRQ):** при极高 сетевой нагрузке потоки `ksoftirqd/<N>` могут потреблять существенный процент CPU,processing deferred network packets. Это **системные** потоки, а не потоки вашего приложения.

### User CPU (%usr) против System CPU (%sys): как интерпретировать

*   **Высокий `%usr`, низкий `%sys`:** «горячий» код в Userspace. Ищите Hot Spot через `perf record` или `perf top`. Типично для CPU-bound алгоритмов, регулярных выражений, шифрования.
*   **Высокий `%sys`, низкий `%usr`:** проблема в Kernelspace или на границе Userspace/Kernelspace. Возможные причины:
    *   Интенсивные системные вызовы (`futex`, `poll`, `epoll_wait` с высокой частотой).
    *   Контенденция на спинлоках в ядре (сетевой стек, VFS).
    *   Обработка прерываний (IRQ, SoftIRQ, Tasklets).
    *   Диагностика: `perf top -g --sys`, `perf record -e 'syscalls:sys_enter_*'`, `perf sched timehist`.
*   **Высокий `%usr` + высокий `%sys`:** классический признак contention'а на блокировки Userspace (мьютексы, RwLock). Потоки тратят время в Userspace на логику и в Kernelspace на футексы. Диагностика: `perf lock contention`, `strace -c -e futex -p <PID>`.

### CPU Affinity, миграция и эффекты кэша

Каждый поток имеет поле `psr` (Processor — номер ядра, на котором он выполняется в данный момент). Если поток мигрирует между ядрами:
*   Теряется содержимое кэш-линий L1/L2 (cache cold start).
*   Увеличивается латентность доступа к памяти, особенно в NUMA-системах.

Просмотреть и установить affinity:
```bash
# Текущая маска affinity (ядро 0 — 0x1, ядро 1 — 0x2, и т.д.)
taskset -p <PID>
# → pid 1234's current affinity mask: 0x3

# Привязка к ядру 0
taskset -p 0x1 <PID>
```

В `ps` и `top` колонка `PSR` показывает текущее ядро. Если для стабильно нагруженного потока PSR меняется каждые несколько секунд — это признак миграции. Для стабилизации используйте `taskset` или `chrt --affinity`.

### Файловая система `/proc/<PID>/task/<TID>/`

Каждый поток имеет свой каталог в `/proc`:
```bash
# Показать все TID процесса
ls /proc/<PID>/task/
# → 1234  1235  1236

# Статус конкретного потока (имя, состояние, маска affinity, приоритет)
cat /proc/<PID>/task/<TID>/status
# → Name:   worker-3
# → State:  S (sleeping)
# → Pid:    1235
# → Tgid:   1234
# → PPid:   1
# → TracerPid:      0
# → VmPeak:   123456 kB
# → VmSize:   123456 kB
# → VmRSS:     45678 kB
# → VmData:    12345 kB
# → VmStk:       132 kB
# → Threads:        8
# → SigQ:   0/30500
# → SigPnd: 0000000000000000
# → ShdPnd: 0000000000000000
# → SigBlk: 0000000000000000
# → SigIgn: 0000000000000000
# → SigCgt: 0000000180000000
# → SigInh: 0000000000000000
# → UTime:   12000000
# → STime:    500000
# → CPUMigrations: 42
# → voluntary_ctxt_switches: 1200
# → nonvoluntary_ctxt_switches: 85
# → Cpus_allowed:   3
# → Cpus_allowed_list:      0-1

# Стек вызовов ядра для потока (если он в D-state)
cat /proc/<PID>/task/<TID>/stack
# → [<ffff>] __schedule+0x2xx/0x4xx
# → [<ffff>] schedule+0xxx/0xxx

# Статистика планировщика для потока
cat /proc/<PID>/task/<TID>/sched
# → nr_switches                  : 1285
# → nr_voluntary_switches        : 1200
# → nr_involuntary_switches      : 85
# → se.load.weight               : 1024
# → se.avg.load_sum              : 123456789
# → se.avg.util_sum              : 98765432
# → se.avg.runnable_sum          : 98765432
```

Поля `CPUMigrations` и `nonvoluntary_ctxt_switches` в `status` — ключевые индикаторы нестабильности потока. Высокое число миграций (>100/сек) требует установки CPU affinity.

### Ядерные потоки vs Пользовательские потоки

```bash
# Показать все потоки с классификацией
ps -eLf | grep -E 'PID|\[|nginx|java|python'
```

*   **Пользовательские потоки** (TID != PID или TID == PID при однопоточном процессе): имеют командную строку в `ps`, видимую через `/proc/<TID>/cmdline`.
*   **Ядерные потоки:** отображаются в квадратных скобках `[kworker/1:2]`, `[ksoftirqd/0]`, `[migration/2]`. Они не имеют Userspace-стека, поэтому `perf record -g` для них покажет только пути ядра, а `gdb` не сможет Attach (нет Userspace-образа). Для анализа KThread'ов используйте `perf kvm` или `bpftrace`.

### Off-CPU анализ

Если приложение «тормозит», но `top` не показывает 100% CPU, вероятно, потоки проводят время в ожидании (Off-CPU). В этом случае ищите не Hot Spot, а Cold Spot:

```bash
# Время вне CPU для процесса (требует ядро >= 5.x с BPF)
sudo perf record -e sched:sched_switch -g -p <PID> -- sleep 10
sudo perf script | stackcollapse-perf.pl | flamegraph.pl --color=off --bgcolor=blue > offcpu.svg
```

Для быстрого поиска причин Off-CPU:
```bash
# Какая функция ядра заблокировала поток
cat /proc/<PID>/task/<TID>/wchan
# → futex_wait_queue_me

# Все процессы, ожидающие на futex
ps -eo pid,comm,wchan:30 | grep -i futex
```

### Контекст переключения (Context Switches)

```bash
# Добровольные и принудительные переключения контекста по потокам
pidstat -w -t -p <PID> 1
# → UID       PID    TID    %usr %system  %guest   %wait    %CPU   CPU  cswch/s  nvcswch/s  Command
# → 1000     1234   1234    0.00    0.00    0.00    0.00    0.00     1    1200        50  myapp
# → 1000     1234   1235    0.00    0.00    0.00    0.00    0.00     2   15000      500  myapp

# Корреляция: если cswch/s > 10000 — поток активно уступает CPU (ожидание I/O, блокировки)
# Если nvcswch/s высокий (>1000) — поток вытесняется планировщиком (нехватка кванта, высокая конкуренция)
```

## Практические сценарии

### Сценарий 1: Идентификация проблемного TID

Для поиска конкретного потока, перегружающего CPU, используйте комбинацию инструментов.

#### Использование `top` (Режим Threads)
```bash
# Показать потоки конкретного процесса
top -H -p <PID>
```
Нажмите **`H`** в интерактивном режиме для переключения вида (столбец PID превратится в TID).

**Валидация:** В столбце `%CPU` каждый поток может показывать до 100% (на одно ядро). Если суммарная нагрузка процесса 400% на 4-ядерном сервере — это нормально. Если один TID показывает 100%, а остальные 0% — проблема локализована.

#### Использование `ps` (Статический снимок)
```bash
# Вывод всех потоков процесса с указанием потребления CPU, номера ядра (PSR) и класса планирования
ps -L -p <PID> -o pid,tid,psr,pcpu,comm,cls,rtprio
```
**Валидация:** Колонка `PSR` показывает, на каком ядре поток выполняется. Если PSR для горячего потока меняется при повторном запуске команды — происходит миграция. Колонка `cls` (`TS` — стандартный планировщик, `FF` — FIFO/RT) важна: RT-потоки могут monopolize ядро.

#### Использование `pidstat` (Интервальная статистика)
```bash
# Мониторинг нагрузки по потокам каждую секунду
pidstat -t -p <PID> 1
```
**Валидация:** Обратите внимание на столбец `%CPU`. Если поток показывает 99.0% на протяжении нескольких секунд — это кандидат на «горячий». Для короткоживущих потоков используйте `pidstat -t -u 1 1` (один снимок всей системы).

#### Быстрый one-liner для локализации TID
```bash
# Найти PID по имени, вывести топ-5 TID по CPU
PID=$(pgrep -f myapp) && ps -L -p $PID -o tid,psr,pcpu,comm --sort=-pcpu | head -n 6
# →  TID PSR %CPU COMMAND
# → 5678   2 99.5 worker-3
# → 5679   2  0.2 worker-4
```

### Сценарий 2: Живое профилирование (`perf top`)

`perf top` позволяет увидеть «горячие» функции в реальном времени, аналогично `top`, но на уровне функций, а не процессов.

```bash
# Профилирование всей системы
sudo perf top -g --all-cpus

# Профилирование конкретного потока
sudo perf top -g -t <TID>

# Профилирование конкретного процесса (все потоки)
sudo perf top -g -p <PID>
```

**Валидация:** В верхней части экрана появятся функции с наибольшим процентом `Overhead`. Для пользовательского кода ищите символы вашего приложения (не `[kernel.kallsyms]`). Нажмите `Enter` для раскрытия стека вызовов (Call Graph). Для выхода — `Ctrl+C` или `q`.

### Сценарий 3: Генерация Flamegraph (perf + FlameGraph)

Превращает текстовый профиль в наглядную интерактивную SVG-диаграмму.

```bash
# 1. Установка инструментария FlameGraph (требуется Perl и git)
git clone https://github.com/brendangregg/FlameGraph.git /opt/FlameGraph
export PATH=$PATH:/opt/FlameGraph

# 2. Запись профиля конкретного TID на 30 секунд
sudo perf record -F 99 -g -t <TID> -- sleep 30
# → [ perf record: Woken up 1 times to write data ]
# → [ perf record: Captured and wrote 1.234 MB perf.data ]

# 3. Генерация collapsed stack
sudo perf script | /opt/FlameGraph/stackcollapse-perf.pl > out.perf-folded

# 4. Генерация flamegraph.svg
/opt/FlameGraph/flamegraph.pl out.perf-folded > flamegraph.svg

# 5. Просмотр
firefox flamegraph.svg
# или
xdg-open flamegraph.svg
```

**Валидация:** В flamegraph ширина прямоугольника пропорциональна времени CPU. Самые «горячие» пути — сверху. Если Flamegraph пустой или показывает только `[unknown]` — см. раздел «Ограничения» (отсутствие символов отладки).

### Сценарий 4: Профилирование с низкими накладными расходами (py-spy, async-profiler)

Для production-сред, где `perf` недоступен или сложен в настройке, используйте языко-специфичные профайлеры.

#### py-spy (Python)
```bash
# Установка
pip install py-spy

# Живой просмотр топ-функций процесса Python
sudo py-spy top --pid <PID>
# → 99.0%  mymodule.heavy_processing (/app/mymodule.py:42)
# →  0.5%  _pyapi_MakePendingCallsFromHandler

# Генерация flamegraph
sudo py-spy record -o flamegraph.svg --duration 30 --pid <PID>
```

**Валидация:** py-spy работает без остановки процесса (no stop-the-world), читает память через `/proc/<PID>/mem`. Не требует перезапуска приложения и не зависит от debug-символов Python.

#### async-profiler (Java / JVM)
```bash
# Запись CPU-профиля JVM-процесса (лучше, чем perf для JIT-кода)
sudo ./profiler.sh -d 30 -f cpu_profile.html <PID>

# Просмотр (HTML с flamegraph)
firefox cpu_profile.html
```

**Валидация:** async-profiler использует `async-profiler` native agent, загружаемый через `-agentpath`. Он корректно обрабатывает JIT-компилированный код, в отличие от `perf`, который видит только `[JIT]` или `[unknown]`. Для привязки к конкретному TID (nid):
```bash
# 1. Найдите TID (десятичный) через top -H
# 2. Переведите TID в HEX
printf '%x\n' <TID>
# → 162e

# 3. Запустите async-profiler с фильтром по nid
sudo ./profiler.sh -d 30 -f profile_162e.html -t 0x162e <PID>
```

#### go tool trace / go tool pprof (Go)
```bash
# Анализ трассировки выполнения (сбор через код)
curl -s http://localhost:6060/debug/pprof/trace?seconds=30 > trace.out
go tool trace trace.out

# CPU-профиль через pprof
go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
(pprof) top10
```

### Сценарий 5: Анализ контенденции блокировок (`perf lock`)

Если `%sys` высокий, а `perf top` не показывает очевидных Hot Spot'ов в Userspace — проблема может быть в блокировках.

```bash
# Запись событий блокировок на 30 секунд
sudo perf lock record -a sleep 30

# Топ блокировок по времени удержания (hold time)
sudo perf lock report

# Анализ контенденции: кто и сколько ждал
sudo perf lock contention
# → Total contentions: 1542
# → Avg contention time: 1250us
# → Max contention time: 45000us

# Валидация: проверка корректности графа захватов
sudo perf lock validate
```

**Интерпретация:**
*   Высокий `avg contention time` (>1 мс) — блокировка удерживается слишком долго.
*   Высокий `total contentions` — высокая конкуренция за один ресурс.
*   Для Userspace-блокировок (pthread_mutex) `perf lock` показывает стеки захватов. Для анализа конкретного mutex в приложении можно использовать `bpftrace` (см. [Конкурентность и синхронизация](../../Core/processes/concurrency.md)).

### Сценарий 6: Анализ активности в реальном времени (`strace`)

Если нужно понять, не застрял ли поток на системных вызовах:

```bash
# Отслеживание всех системных вызовов конкретного TID с временем выполнения
sudo strace -f -ttT -p <TID>

# Пример вывода:
# 12:00:01.123456 openat(AT_FDCWD, "/etc/hosts", O_RDONLY) = 3 <0.000042>
# 12:00:01.123500 read(3, "127.0.0.1\tlocalhost\n", 4096) = 25 <0.000001>
# 12:00:01.123600 futex(0x7f2c34, FUTEX_WAIT_BITSET_PRIVATE, 0, NULL, 0xffffffff, 0) = ? <0.500000>
```

**Валидация:** Если `strace` ничего не выводит в течение 5–10 секунд — поток выполняет код в Userspace и не обращается к ядру. В этом случае `strace` бесполезен, переходите к `perf` или `gdb`. Если `strace` показывает миллионы вызовов `futex` с временем >100 мс — это lock contention.

#### Фильтрация по типу вызовов
```bash
# Только сетевые вызовы
sudo strace -e trace=network -p <TID> -f

# Только работа с файлами
sudo strace -e trace=file -p <TID> -f

# Сводная статистика по вызовам (количество, время, ошибки)
sudo strace -c -p <PID>
```

**Важно:** `strace` использует `ptrace` и останавливает процесс при каждом syscall. На production-серверах используйте его только на коротких интервалах (<30 секунд). Для длительного мониторинга используйте `bpftrace` (см. [Трассировка и отладка](../Troubleshooting/tracing_and_debugging.md)).

### Сценарий 7: Профилирование (`perf record` / `perf report`)

Утилита `perf` позволяет точно определить «горячую» функцию в коде.

```bash
# 1. Запись профиля конкретного TID на 10 секунд с графом вызовов
sudo perf record -F 99 -g -t <TID> -- sleep 10
# → [ perf record: Captured and wrote 0.500 MB perf.data ]

# 2. Анализ отчета (интерактивный TUI)
sudo perf report --tid <TID>

# 3. Анализ отчета (текстовый режим, для скриптов)
sudo perf report -n --stdio --tid <TID>
# →     8.15%  myapp   myapp              [.] heavy_algorithm_function
#             |
#             --- heavy_algorithm_function (myapp)
#                 process_data (myapp)
#                 main_loop (myapp)
```

**Валидация:** В отчете ищите функции с максимальным значением **Overhead**. Используйте `Enter` для раскрытия стека вызовов. Если `perf report` показывает `[unknown]` — установите `debug-info` пакеты (см. «Ограничения»).

### Сценарий 8: Анализ стека вызовов (`gdb`)

Если нужно «заморозить» поток и посмотреть, какую именно строку кода он выполняет.

#### Соответствие TID и потоков GDB
У `gdb` внутренняя нумерация потоков. Чтобы найти нужный:
```bash
sudo gdb -p <PID>
(gdb) info threads
```
Ищите строку `LWP <TID>`. Запомните внутренний ID (первый столбец).

#### Просмотр стека
```bash
# Переключение на поток
(gdb) thread <ID>

# Вывод стека вызовов
(gdb) bt

# Просмотр локальных переменных текущего кадра
(gdb) info locals

# Просмотр аргументов функции
(gdb) info args
```

#### Снятие стека всех потоков сразу (неинтерактивно)
```bash
# Пакетный режим: сохранить стек всех потоков в файл
sudo gdb -p <PID> -batch -ex "thread apply all bt" > stacks.txt

# Фильтрация: только пользовательские кадры (без системных библиотек)
grep -v '(__libc_' stacks.txt | grep -v '(vdso' > user_stacks.txt
```

**Валидация:** После `gdb attach` процесс полностью останавливается (SIGSTOP). Убедитесь, что сервис не настроен на автоматический restart по таймауту health-check (например, в Kubernetes `livenessProbe` может сработать). Для коротких операций (attach + bt + detach) риск минимален. Для длительного анализа используйте `gcore` или `perf` вместо `gdb`.

### Сценарий 9: Анализ планировщика и задержек (`perf sched`)

Если поток потребляет CPU, но причина не в Userspace-коде, а в планировщике (например, поток часто вытесняется или мигрирует):

```bash
# Время, проведённое в ожидании планировщика (Off-CPU + On-CPU latency)
sudo perf sched record -p <PID> -- sleep 10
sudo perf sched latency
# → Task                  |   Runtime ms |  Switches | Average delay ms | Max delay ms |
# → myapp:5678 (worker-3) |    4500.123  |      1200 |          2.345   |    45.678    |

# Визуализация временной диаграммы (когда поток был на CPU, когда — в ожидании)
sudo perf sched timehist
# →      time  cpu  task name             wait_time  delay
# →  1.000000    0  myapp:5678            0.000 ms  0.002 ms  running
# →  1.000005    0  <idle>                 0.002 ms  0.000 ms  ...
# →  1.000010    0  myapp:5678            0.005 ms  0.001 ms  running

# Карта распределения потоков по ядрам (визуализация migration'ов)
sudo perf sched map
```

**Валидация:** `Average delay ms` > 5 мс указывает на contention или нехватку CPU. `Max delay ms` > 100 мс — критическая задержка. В `timehist` ищите «дыры» (gap), где поток отсутствовал на CPU — это Off-CPU периоды.

### Сценарий 10: Специфика Java-приложений

В Java TID из ОС соответствует полю `nid` (native id) в дампе потоков, но `nid` представлен в **шестнадцатеричном** формате.

#### Сопоставление TID и Java-потоков
```bash
# 1. Найдите TID (десятичный) через top -H или ps
# → TID: 5678

# 2. Переведите TID в HEX
printf '%x\n' 5678
# → 162e

# 3. Снимите дамп потоков
jstack <PID> > jstack.txt

# 4. Найдите в файле строку nid=0x162e
grep -A 20 'nid=0x162e' jstack.txt
# → "worker-3" #1234 prio=5 os_prio=0 cpu=4500.12ms elapsed=3600.45s tid=0x7f2c34 nid=0x162e runnable
```

#### Использование async-profiler (рекомендуется для JVM)
```bash
# CPU-профиль с нативной точностью (JIT-код виден корректно)
sudo ./profiler.sh -d 30 -f cpu_profile.html <PID>

# Профиль конкретного Java-потока (по nid)
sudo ./profiler.sh -d 30 -f profile_nid.html -t 0x162e <PID>

# Allocation-профиль (поиск утечек памяти через аллокации)
sudo ./profiler.sh -e alloc -d 30 -f alloc_profile.html <PID>
```

**Валидация:** async-profiler работает без stop-the-world и не требует debug-символов JVM (работает через JVMTI). Результат в HTML-формате (flamegraph) открывается в браузере. Это стандарт де-факто для профилирования Java в production.

### Сценарий 11: Специфика Go-приложений

Go имеет встроенный профайлинг через pprof и trace.

```bash
# Включение ppprof в коде (runtime/pprof)
# go tool pprof поддерживает CPU, memory, goroutine профили

# CPU-профиль (30 секунд)
go tool pprof http://localhost:6060/debug/pprof/profile?seconds=30
(pprof) top10

# Визузация flamegraph (требуется graphviz)
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/profile?seconds=30

# Или через perf (для нативного кода / cgo)
sudo perf record -F 99 -g -p <PID> -- sleep 30
sudo perf report --pid <PID>
```

**Валидация:** Go 1.25+ автоматически считывает лимиты CPU из cgroups (v1/v2) для `GOMAXPROCS`. Если видите 100% на одном потоке при множестве ядер — проверьте, не ограничен ли cgroup. Используйте `runtime.SetMaxProcs` или переменную окружения `GOMAXPROCS` для контроля.

### Сценарий 12: Специфика Python-приложений

Python имеет GIL (Global Interpreter Lock), поэтому только один поток выполняется в Userspace в любой момент времени. Тем не менее, потоки полезны для I/O-bound задач.

```bash
# py-spy: не требует перезапуска, работает без GIL-ограничений
sudo py-spy top --pid <PID>

# Генерация flamegraph
sudo py-spy record -o python_flame.svg --duration 30 --pid <PID>

# Если приложение использует C-расширения (NumPy, Pandas, cryptography),
# GIL может отпускаться, и CPU может распределяться между потоками
# В этом случае поведение аналогично чистому C/C++
```

**Валидация:** Если CPU > 100% на многоядерном Python-приложении — вероятно, используются C-расширения, отпускающие GIL, или multiprocessing вместо threading. Для CPU-bound задач в Python используйте `ProcessPoolExecutor` или `multiprocessing`, а не `ThreadPoolExecutor`.

## Устранение неисправностей

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Один TID 100% CPU, остальные 0% | Busy-loop, spin-lock, активная обработка | `perf record -g -t <TID>`, `gdb -batch -ex "thread apply all bt" -p <PID>` | Найти Hot Spot через `perf report`, оптимизировать алгоритм или добавить `sched_yield`/`sleep` |
| Высокий `%sys`, низкий `%usr` | Futex contention, spinlock в ядре, SoftIRQ | `perf top -g --sys`, `perf lock contention`, `cat /proc/softirqs` | Sharded locks, уменьшить критическую секцию, отключить ненужные IRQ coalescing |
| Высокий `%usr` + высокий `%sys` | Контенденция на Userspace-блокировки (mutex, RwLock) | `perf lock contention`, `strace -c -e futex -p <PID>` | Разбить данные на shards, использовать RCU или lock-free структуры |
| Поток мигрирует между ядрами (PSR меняется) | Отсутствует CPU affinity, планировщик балансирует | `ps -L -p <PID> -o tid,psr`, `pidstat -t -p <PID> 1` | Установить `taskset -p <mask> <PID>` или `chrt --affinity` |
| 100% CPU, но `perf` показывает `[unknown]` | Бинарник «стрипнут», нет debug-info | `file /path/to/binary`, `dpkg -l | grep dbg` | Установить `debug-info` пакеты или перекомпилировать с `-g` |
| `strace` не показывает ничего, CPU > 90% | Поток в Userspace, не вызывает syscall (JIT, busy-loop) | `perf record -g -t <TID>`, `gdb` | Использовать `perf` или `gdb`, `strace` бесполезен |
| Cannot attach: Operation not permitted | `kernel.yama.ptrace_scope` ограничивает ptrace | `cat /proc/sys/kernel/yama/ptrace_scope` | `echo 0 > /proc/sys/kernel/yama/ptrace_scope` (временно) или использовать `sudo` |
| Поток исчез во время анализа | Short-lived thread (пул, таск-сcheduler) | Повторить с `perf record -a` (вся система), использовать `perf sched` | Записывать профиль заранее или на всё приложение (`-p <PID>` включает все TID) |
| Высокий `%wa` (IOwait) при CPU > 90% | Поток ждёт I/O, но не отпускает CPU (spin) | `pidstat -d -t -p <PID> 1`, `iotop` | Проверить `O_DIRECT`, `io_uring`, блокировки файловой системы |
| CPU 100%, но Load Average низкий | Поток привязан к одному ядру (affinity), остальные ядра простаивают | `nproc`, `ps -L -p <PID> -o tid,psr,pcpu` | Увеличить маску affinity или проверить, не заблокирован ли планировщик (RT-приоритет) |
| Высокий `nvcswch/s` | Высокая конкуренция за CPU, поток вытесняется | `pidstat -w -t -p <PID> 1` | Увеличить nice (понизить приоритет), уменьшить количество потоков, проверить `chrt` |
| Поток в D-state с `wchan=futex_wait` | Ожидает Userspace-блокировку (mutex, condvar) | `cat /proc/<PID>/task/<TID>/wchan`, `pstack <PID>` | Проверить логику захвата блокировок, добавить таймауты |

### Типичные ошибки и их решения (пошагово)

#### Ошибка 1: Невозможно прикрепить strace/gdb
```bash
# Проверка
strace -p <TID>
# → attach: Operation not permitted

# Решение
# 1. Проверить ptrace_scope
cat /proc/sys/kernel/yama/ptrace_scope
# → 2 (по умолчанию в Ubuntu/Debian)

# 2. Временное решение (до перезагрузки)
echo 0 | sudo tee /proc/sys/kernel/yama/ptrace_scope

# 3. Постоянное решение (/etc/sysctl.d/99-ptrace.conf)
# kernel.yama.ptrace_scope = 1
# (1 = разрешить attach только потомкам; 0 = разрешить всем)
```

#### Ошибка 2: perf report показывает только `[kernel.kallsyms]`
```bash
# Причина: бинарник stripped или нет debug-info

# Проверка
file /usr/bin/myapp
# → /usr/bin/myapp: ELF 64-bit LSB executable, x86-64, version 1 (SYSV), **stripped**

# Решение
# 1. Для дистрибутивных пакетов
sudo apt-get install myapp-dbg
# или
sudo debuginfod download /usr/bin/myapp

# 2. Для собранного вруссе бинарника — пересобрать с -g
gcc -g -O2 -o myapp myapp.c

# 3. Для JVM — использовать async-profiler вместо perf
```

#### Ошибка 3: perf.data слишком большой
```bash
# Причина: частота сэмплирования слишком высокая или запись ведётся долго

# Решение
# 1. Уменьшить частоту (по умолчанию 4000 Гц, достаточно 99–250)
sudo perf record -F 99 -g -t <TID> -- sleep 10

# 2. Записать только Userspace-события (если ядро не интересует)
sudo perf record -e cycles:u -g -t <TID> -- sleep 10

# 3. Использовать `perf archive` для переноса perf.data на другую машину
sudo perf archive
```

## Best Practices

1.  **Порядок диагностики (SRE-подход):**
    1.  `top -H -p <PID>` / `pidstat -t -p <PID> 1` — локализация TID.
    2.  `ps -L -p <PID> -o tid,psr,pcpu,cls` — проверка affinity и приоритета.
    3.  `perf top -g -t <TID>` — быстрый взгляд на горячие функции.
    4.  `perf record -F 99 -g -t <TID> -- sleep 10` + `perf report` — точная локализация.
    5.  `perf lock contention` / `cat /proc/<TID>/wchan` — проверка блокировок.
    6.  `gdb -batch -ex "thread apply all bt" -p <PID>` — финальный анализ кода.
2.  **Никогда не используйте `strace` в production на долгих интервалах.** Оверхед до 100x. Для production-мониторинга используйте `bpftrace` (см. [Трассировка и отладка](../Troubleshooting/tracing_and_debugging.md)).
3.  **Проверяйте cgroup-лимиты перед глубоким анализом.** Если процесс в контейнере, 100% CPU может быть ограничением `cpu.cfs_quota_us`, а не жадностью приложения:
    ```bash
    cat /sys/fs/cgroup/system.slice/myapp.service/cpu.stat
    # → usage_usec  nr_throttled_usec  throttled_time
    ```
4.  **Для JVM-приложений используйте `async-profiler`**, а не `perf`. `perf` не видит JIT-код корректно. `async-profiler` даёт flamegraph с нативными именами Java-методов.
5.  **Учитывайте SMT / Hyper-Threading.** На процессорах с SMT (Intel HT, AMD SMT) два логических ядра делят одно физическое ядро и кэш L1/L2. Если поток привязан к sibling-ядру, конкуренция за execution units может давать завышенные показатели CPU. Для точных измерений CPU-intensive workloads используйте `taskset` для привязки к физическим ядрам (`0, 2, 4, 6` на типичном Xeon) или отключайте SMT в BIOS/UEFI.
6.  **Собирайте `perf.data` для офлайн-анализа.** На production-серверах с высокой нагрузкой интерактивный `perf report` может быть медленным. Скопируйте `perf.data` на dev-машину и анализируйте там.
7.  **Используйте `perf sched timehist` для анализа задержек.** Если приложение медленное, но не горячее, ищите не Hot Spot, а Cold Spot — длинные периоды ожидания.

## Границы применимости и крайние случаи

*   **Short-lived потоки:** Если поток живёт < 1 секунды, `perf record` с интервалом 10 секунд может не поймать его. Используйте `perf record -a` (вся система) перед воспроизведением проблемы, или настройте частоту сэмплирования выше (`-F 1000`), но учтите рост оверхеда.
*   **Kernel Threads (KThread):** Потоки `kworker`, `ksoftirqd`, `migration` не имеют Userspace-стека. `gdb` не может анализировать их код. Используйте `perf kvm` или `bpftrace` с `kprobe` для анализа функций ядра. Для сетевых SoftIRQ используйте `watch -d cat /proc/softirqs`.
*   **RT-priority потоки:** Потоки с `chrt -r` (SCHED_RR) или `chrt -f` (SCHED_FIFO) могут monopolize CPU. Проверьте их через `chrt -p <TID>`. Если такой поток завис, `kill -9` может не помочь — RT-потоки игнорируют стандартные сигналы в некоторых случаях. Используйте `chrt -o <TID>` для возврата к обычному планированию.
*   **CPU Throttling (cgroups v2):** Приложение может показывать стабильные 100% на каждом ядре, но в реальности тратить время в ожидании кванта. Проверьте `cpu.stat`:
    ```bash
    cat /sys/fs/cgroup/myapp/cpu.stat
    # → usage_usec 500000000
    # → nr_throttled_usec 200000000
    # → throttled_time 200000000
    ```
    Если `nr_throttled_usec` > 0 — процесс throttled. Увеличьте `cpu.max` или оптимизируйте код.
*   **JIT-компилируемый код (Java, Node.js, V8, Python):** `perf` видит JIT-код как `[JIT]` или `[unknown]`. Используйте `perf jit` (включите `CONFIG_JIT` в ядре) или языко-специфичные профайлеры (`async-profiler`, `py-spy`, `node --prof`).
*   **Lock-free алгоритмы:** Если `perf top` показывает `__atomic_compare_exchange` или `__sync_val_compare_and_swap` — это lock-free контентенция. Проблема не в блокировках, а в высокой частоте CAS-операций. Диагностика: `perf record -e cycles:u -g -t <TID>`, анализ `atomic_ops` через `perf annotate`.
*   **Многопоточные приложения с CPU > 100%:** На 32-ядерном сервере общее потребление CPU процессом может достигать 3200%. Это нормально. Если суммарный `%CPU` процесса равен числу ядер * 100%, все ядра загружены полностью. Ищите проблема на уровне алгоритма, а не «слишком много потоков».
*   **NUMA-эффекты:** Если поток на ядре CPU 0 постоянно обращается к памяти, привязанной к NUMA-узлу 1, каждый доступ добавляет 30–100 нс задержки. Проверка:
    ```bash
    numactl --hardware
    # → available: 2 nodes (0-1)
    # → node 0 cpus: 0 1 2 3
    # → node 0 size: 16384 MB
    # → node 1 cpus: 4 5 6 7
    # → node 1 size: 16384 MB
    ```
    Для привязки потока и памяти к одному узлу:
    ```bash
    numactl --cpunodebind=0 --membind=0 -- <command>
    ```

### Сравнение методов

| Метод | Плюсы | Минусы | Когда использовать |
| :--- | :--- | :--- | :--- |
| `top -H` | Мгновенно, без установки ПО. | Только цифры, без контекста кода. | Первичная локализация TID. |
| `pidstat -t` | Интервальная статистика, CSV-экспорт. | Нет графа вызовов. | Долгосрочный мониторинг, cron, отчеты. |
| `perf top` | Живое профилирование, граф вызовов. | Требует прав root, debug-символы. | Быстрый поиск Hot Spot в production. |
| `perf record` + `perf report` | Точная локализация, flamegraph. | Требует debug-символы, постобработка. | Детальная диагностика, offline-анализ. |
| `perf lock contention` | Анализ блокировок ядра и Userspace. | Нужен perf >= 5.x, debug-info. | Высокий `%sys` без очевидных Hot Spot'ов. |
| `perf sched timehist` | Визуализация задержек планировщика. | Много данных на высоконагруженных системах. | Медленное приложение с низким CPU. |
| `py-spy` | Zero-overhead для Python, без перезапуска. | Только Python. | CPU-bound Python-приложения. |
| `async-profiler` | Лучший профайлер для JVM, flamegraph HTML. | Требуется JVMTI, native agent. | Java/Spring/Kafka-приложения. |
| `strace` | Показывает взаимодействие с ОС. | Высокие накладные расходы, останавливает процесс. | Поиск blocking syscall'ов (connect, read, futex) на коротких интервалах. |
| `gdb` | Максимальная детализация (переменные, интерактивно). | Stop-the-world, привязка к символам. | Анализ state после падения, интерактивная отладка. |

### Ограничения

*   **Символы отладки:** Для эффективного использования `perf` и `gdb` исполняемые файлы должны содержать отладочную информацию (не быть «стрипнутыми») или иметь установленные `debug-info` пакеты (`myapp-dbg`, `linux-image-*-dbgsym`). Для JIT-языков (Java, Node.js, Python C-extensions) требуются map-файлы или языко-специфичные агенты.
*   **Безопасность:** Использование `ptrace` (необходимо для `gdb` и `strace`) может быть ограничено параметром `kernel.yama.ptrace_scope`. Для non-root пользователей может потребоваться `sudo` или настройка `/etc/sysctl.d/`.
*   **Оверхейд:** `strace` создаёт наибольшие накладные расходы (до 100x замедления). `perf` с сэмплированием 99 Гц — <1%. `py-spy` и `async-profiler` — <2%. `bpftrace` — <5%.
*   **Ядерные потоки:** `gdb` не может анализировать KThread'и (нет Userspace-образа). `perf` видит только пути ядра. Используйте `bpftrace` или `perf kvm`.
*   **PID/TID reuse:** После завершения процесса/потока его TID может быть переиспользован. При длительном мониторинге сверяйте также командную строку (`ps -o cmd`) или время старта (`ps -o lstart`).

### См. также

*   [Профилирование через perf](../Performance/perf.md) — детальный справочник по инструменту.
*   [Конкурентность и синхронизация процессов](../../Core/processes/concurrency.md) — диагностика дедлоков, ThreadSanitizer, lock contention.
*   [Трассировка и отладка в Linux](../Troubleshooting/tracing_and_debugging.md) — `strace`, `bpftrace`, `ltrace`, eBPF.
