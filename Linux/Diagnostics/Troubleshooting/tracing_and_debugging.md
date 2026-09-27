# Трассировка и отладка в Linux

## Definitions

**Мониторинг** — непрерывный сбор высокоуровневых метрик (CPU, RAM, I/O) для оценки общего состояния системы и выявления аномалий.

**Трассировка (Tracing)** — детальная фиксация последовательности событий (системных/библиотечных вызовов, срабатываний функций ядра) для анализа логики работы и поиска скрытых задержек.

**Отладка (Debugging)** — интерактивный поиск и устранение ошибок: пошаговое выполнение, проверка состояния памяти/регистров, использование контрольных точек (breakpoints).

**Системный вызов (Syscall)** — программный интерфейс, через который приложение запрашивает у ядра выполнение привилегированных операций (ввод-вывод, работа с сетью, управление процессами).

**Библиотечный вызов (Library Call)** — обращение приложения к функциям динамических библиотек (`.so`, `libc`), которое может выполняться полностью в пользовательском пространстве.

**eBPF (Extended Berkeley Packet Filter)** — технология ядра, позволяющая запускать безопасные программы в контексте ядра без изменения его исходного кода. Используется для высокопроизводительной трассировки с минимальными накладными расходами.

**PSI (Pressure Stall Information)** — механизм ядра (≥4.20) для оценки потерь производительности из-за нехватки ресурсов (CPU, Memory, I/O).

**LD_PRELOAD** — переменная окружения, заставляющая динамический линковщик (`ld.so`) загружать указанные разделяемые библиотеки перед всеми остальными. Позволяет переопределять функции стандартных библиотек.

**Tracepoint** — статическая точка трассировки, встроенная в код ядра разработчиками ядра. Стабильный API между версиями ядра, не меняется при обновлении. Используется `ftrace` и `perf` для сбора событий без модификации кода.

**kprobe (Kernel Probe)** — механизм динамической трассировки функций ядра. Позволяет устанавливать точки останова на любую функцию ядра без перекомпиляции и перезагрузки. Используется `perf`, `bpftrace`, BCC.

**uprobe (User-space Probe)** — аналог kprobe для пространства пользователя. Позволяет трассировать функции в пользовательских библиотеках (`.so`) и бинарниках без модификации исходного кода.

**ftrace** — встроенный в ядро фреймворк трассировки, предоставляющий интерфейс через `debugfs` (`/sys/kernel/debug/tracing/`). Использует tracepoints и function graph tracer для детального анализа работы ядра.

**BCC (BPF Compiler Collection)** — набор инструментов на Python/C для eBPF-трассировки, оборачивающих сложность libbpf в удобные CLI-утилиты. Включает `opensnoop`, `execsnoop`, `memleak`, `tcplife`.

**SystemTap** — фреймворк для динамической инструментации ядра и пользовательских пространств (альтернатива eBPF). Требует debuginfo-пакетов ядра и модуль `staprun`. В 2024+ постепенно замещается eBPF.

**pidstat** — утилита (часть пакета `sysstat`) для мониторинга активности процессов в реальном времени. Показывает CPU, память, I/O по PID.

**perf top** — интерактивный режим `perf` для поиска «горячих» функций в реальном времени. Аналогичен `top`, но для кода.

**perf sched** — набор подкоманд `perf` для анализа планировщика процессов: задержки (latency), миграции между CPU, блокировки.

**ngrep** — утилита, сочетающая `grep` и `tcpdump`. Позволяет фильтровать сетевые пакеты по содержимому payload (а не только по заголовкам).

**debugfs** — виртуальная файловая система ядра (`/sys/kernel/debug/`), предоставляющая интерфейс к `ftrace`, kprobes, uprobes и другим механизмам трассировки.

## Basic Concepts

### Уровни абстракции и инструменты

| Уровень | Что отслеживается | Инструмент |
| :--- | :--- | :--- |
| Зависимости | Наличие и пути разделяемых библиотек (`.so`) | `ldd` |
| Подмена логики | Перехват и замена библиотечных функций | `LD_PRELOAD` |
| Системные вызовы | Взаимодействие приложения с ядром | `strace`, `perf trace`, `bpftrace` |
| Библиотечные вызовы | Обращения к `.so`-библиотекам | `ltrace` |
| Открытые файлы/сокеты | Ресурсы, используемые процессом | `lsof`, `ss` |
| Давление на ресурсы | Потери производительности (CPU/Memory/I/O) | [**PSI**](../../Core/kernel/psi.md) |
| Интерактивная отладка | Пошаговое выполнение, переменные, стек | `gdb` |
| Профилирование CPU | Сэмплирование стека вызовов | `perf record` |

### Сравнение strace и eBPF (bpftrace)

| Характеристика | strace | bpftrace (eBPF) |
| :--- | :--- | :--- |
| **Механизм** | `ptrace` (остановка процесса на входе/выходе syscall) | Инструментация ядра (без остановки процесса) |
| **Влияние на Prod** | Высокое (до 10-100x замедления) | Минимальное (<1-5%) |
| **Безопасность** | Риск зависания процесса при аттаче/детаче | Безопасно для критических сервисов |
| **Сложность** | Низкая (одна команда) | Средняя (требует написания мини-скриптов) |

### Когда применять

- **`ldd`** — ошибки «библиотека не найдена», проверка путей линковки.
- **`LD_PRELOAD`** — отладка (подмена `malloc`), временные фиксы, создание песочниц.
- **`strace`** — ошибки `Permission denied`, сетевые проблемы, непонятные блокировки.
- **`ltrace`** — когда системных вызовов недостаточно и нужна логика работы с библиотеками.
- **`lsof`** — утечки файловых дескрипторов, поиск процесса по открытому сокету.
- **`gdb`** — анализ coredump, пошаговое выполнение сложной логики.
- **`bpftrace`** — профилирование и трассировка в высоконагруженных Production-средах.
- **`perf`** — поиск «горячих» путей в коде и анализ аппаратных событий.
- **PSI** — точная оценка «давления» на систему, более информативная, чем Load Average.

### Права доступа и ограничения для инструментов трассировки

| Инструмент | Требуемые права | Ограничения | Рекомендация |
| :--- | :--- | :--- | :--- |
| **strace** | `CAP_SYS_PTRACE` или root | `ptrace_scope` блокирует аттач к чужим процессам | Временно `sysctl kernel.yama.ptrace_scope=0` |
| **gdb** | `CAP_SYS_PTRACE` или root | Останавливает процесс (SIGSTOP) | Использовать `gcore` для Prod |
| **perf** | Доступ к PMU (`perf_event_paranoid ≤ 1`) | Нет доступа к событиям ядра без прав | Настройка `/proc/sys/kernel/perf_event_paranoid` |
| **bpftrace/BCC** | root или `CAP_BPF`+`CAP_PERFMON` (ядро ≥ 5.8) | Без BTF не работает на старых ядрах | Проверка `uname -r` и `bpftool feature` |
| **ftrace** | root (чтение/запись `debugfs`) | Отключен при `kernel.kptr_restrict=2` | Временное `echo 0 > /proc/sys/kernel/kptr_restrict` |
| **tcpdump** | `CAP_NET_RAW`+`CAP_NET_ADMIN` | Требует raw-сокет | Запуск через sudo или delegation прав |
| **SystemTap** | root + debuginfo-пакеты | Требует `staprun` и отладочные символы ядра | Замещается eBPF в новых дистрибутивах |

### Параметры ядра для диагностики

Ключевые параметры, полезные при отладке:

```bash
# Включение вывода сообщений ядра на консоль (зависание на раннем этапе)
GRUB_CMDLINE_LINUX_DEFAULT="loglevel=7 debug"

# Отключение кварцевания (quirks) для отладки ACPI
GRUB_CMDLINE_LINUX_DEFAULT="acpi=off"

# Принудительный panic для сбора дампа
GRUB_CMDLINE_LINUX_DEFAULT="panic=10"

# Включение earlyprintk (зависание до инициализации консоли)
GRUB_CMDLINE_LINUX_DEFAULT="earlyprintk=ttyS0,115200"

# После загрузки: проверка текущих параметров
cat /proc/cmdline
# → BOOT_IMAGE=/vmlinuz-6.8.0 root=/dev/sda2 ro loglevel=7 debug
```

## Practical Scenarios

### 1. LD_PRELOAD: Перехват и подмена функций

Механизм позволяет подменить стандартную функцию (например, из `libc.so`) на собственную реализацию без перекомпиляции приложения.

**Пример: Перехват функции `open()` для логирования открываемых путей.**
1. Создаем `shim.c`:
```c
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>

int open(const char *pathname, int flags) {
    int (*orig_open)(const char*, int) = dlsym(RTLD_NEXT, "open");
    printf("DEBUG: Opening file: %s\n", pathname);
    return orig_open(pathname, flags);
}
```
2. Компилируем: `gcc -shared -fPIC -o shim.so shim.c -ldl`
3. Запускаем приложение:
```bash
LD_PRELOAD=./shim.so cat /etc/hostname
# → DEBUG: Opening file: /etc/hostname
# → my-server-name
```

---

### 2. Сценарий: Бинарный файл завершается без вывода (Silent Exit)

Алгоритм диагностики, когда программа мгновенно завершается без ошибок в консоли.

1. **Проверка кода возврата:**
    ```bash
    ./binary; echo $?
    # → 127
    ```
    Значения `126` (права доступа) и `127` (файл не найден/проблемы с динамической линковкой) — ключевые.

2. **Проверка зависимостей:**
    ```bash
    ldd ./binary
    # → libsomething.so.1 => not found
    ```

3. **Захват stderr:**
    ```bash
    ./binary 2>&1 | less
    ```

4. **Трассировка системных вызовов (основной этап):**
    ```bash
    strace ./binary
    # → openat(AT_FDCWD, "/etc/myapp.conf", O_RDONLY) = -1 ENOENT (No such file or directory)
    # → exit_group(1) = ?
    ```

5. **Проверка лимитов и безопасности:**
    Проверьте `dmesg | tail` на предмет записей от `OOM Killer` или блокировок `AppArmor/SELinux`.

---

### 3. strace: Трассировка системных вызовов

**Механизм работы:** `strace` использует системный вызов `ptrace`. При подключении ядро останавливает процесс дважды на каждый syscall:
1. **На входе** — для чтения аргументов.
2. **На выходе** — для чтения результата.
Это вносит огромные задержки, поэтому `strace` редко применим для профилирования производительности.

**Продвинутые опции:**
```bash
# Трассировка со временем выполнения (-T) и микросекундами (-tt)
sudo strace -f -ttT -p <PID>
# → 12:00:01.123456 openat(..., "/etc/hosts", ...) = 3 <0.000042>

# Фильтрация по типу вызовов
strace -e trace=network,file uptime

# Сводка (профилирование по количеству вызовов)
strace -c ls
```

#### Сценарий: Диагностика «полумертвого» сервиса
Процесс висит, CPU на нуле, логи молчат. Скорее всего, процесс застрял внутри системного вызова.
- **`connect`** — проблемы с сетью или DNS (ожидание внешнего ресурса).
- **`read / write`** — блокировки на диске или переполненные сокеты.
- **`futex`** — внутренние блокировки (deadlocks) внутри самого приложения.

**Быстрая проверка лимитов:**
```bash
ls /proc/<PID>/fd | wc -l
# → 1024 (Если это лимит, новые файлы не откроются)
```

---

### 4. Современная трассировка: eBPF (bpftrace)

Используется для диагностики в Production без риска значительного замедления сервиса.

**Пример: Подсчет открываемых файлов по процессам.**
```bash
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { @[comm] = count(); }'
# → @[nginx]: 25
# → @[systemd]: 8
```

---

### 5. Профилирование через perf

Позволяет найти функции, потребляющие больше всего ресурсов CPU.

```bash
# Сбор данных в течение 10 секунд (сэмплирование стека вызовов)
sudo perf record -F 99 -p <PID> -g -- sleep 10
# → [ perf record: Captured and wrote 0.500 MB perf.data ]

# Просмотр отчета
sudo perf report -n --stdio
# → 48.15%  myapp  myapp  [.] heavy_algorithm_function
```

---

### 6. ltrace и gdb

**ltrace:** Трассировка библиотечных вызовов (`malloc`, `free`, `printf`).
```bash
ltrace -e malloc+free ls
# → myapp->malloc(120) = 0x55d...
```

**gdb:** Интерактивная отладка.
```bash
sudo gdb -p <PID>
# (gdb) thread apply all bt    # Получить стек всех потоков
# (gdb) print my_variable      # Вывести значение переменной
```

> **Важно:** При использовании `gdb` или `strace` процесс **полностью останавливается** (SIGSTOP). Это может привести к исключению сервера из балансировщика по таймауту. Для Production-систем безопаснее использовать [**отладку через Coredump**](./coredump_debugging.md).

### 7. perf top и perf sched (реальное время)

**perf top** — интерактивный режим для поиска «горячих» функций без сохранения дампа.

```bash
sudo perf top
# →  45.21%  myapp  [.] heavy_function
# →  12.30%  myapp  [.] another_hot_function
```

**perf sched** — анализ планировщика и задержек между CPU:

```bash
sudo perf sched record -- sleep 5
sudo perf sched latency
# → Топ задержек (latency) и количество миграций между CPU
```

> **Примечание:** Детальное описание `perf record`, `perf report`, `perf stat` и анализа аппаратных событий см. в [**`perf` — профилирование производительности**](../Performance/perf.md).

### 8. Трассировка ядра через ftrace

`ftrace` — встроенный в ядро фреймворк, управляемый через `debugfs`:

```bash
# 1. Монтирование debugfs (если не смонтирован)
sudo mount -t debugfs debugfs /sys/kernel/debug

# 2. Доступные трассёры
ls /sys/kernel/debug/tracing/available_tracers | head
# → function_graph function nop ...

# 3. Включение function_graph для ядра
echo function_graph | sudo tee /sys/kernel/debug/tracing/current_tracer

# 4. Фильтр по функции
echo 'do_nanosleep' | sudo tee /sys/kernel/debug/tracing/set_ftrace_filter

# 5. Чтение трассировки
cat /sys/kernel/debug/tracing/trace
# → Выход: вызовы do_nanosleep с временем входа/выхода

# 6. Отключение
echo nop | sudo tee /sys/kernel/debug/tracing/current_tracer
```

### 9. Сетевые инструменты: tcpdump и ngrep

Для отладки сетевых проблем на транспортном уровне используются:

- **[`tcpdump`](../Networking/tcpdump.md)** — перехват сырых пакетов через `libpcap`. Подробное руководство — в [**tcpdump — сетевой анализатор пакетов**](../Networking/tcpdump.md).
- **ngrep** — фильтрация пакетов по содержимому payload (аналогия `grep` для сети).

```bash
# ngrep: поиск строки "password" в HTTP-трафике
sudo ngrep -q -W byline "password" tcp port 80

# tcpdump: захват на интерфейсе с фильтром BPF (детали в tcpdump.md)
sudo tcpdump -i eth0 -n -s 0 -w /tmp/capture.pcap port 443
```

### 10. BCC инструменты (opensnoop, execsnoop, tcplife)

BCC предоставляет готовые eBPF-инструменты с низким overhead для Production:

```bash
# opensnoop: отслеживание открываемых файлов в реальном времени
sudo opensnoop
# → COMM             PID    FD       ERR  PATH
# → nginx            1234   3        0    /etc/nginx/nginx.conf

# execsnoop: отслеживание новых процессов (fork/exec)
sudo execsnoop
# → PCOMM            PID    PPID   RET ARGS

# tcplife: время жизни TCP-соединений
sudo tcplife
# → TCP/LIFESPAN: caddr:port  ...  laddr:port  ...  ms
```

> **Примечание:** Установка BCC: `apt install bpfcc-tools` (Debian/Ubuntu), `yum install bcc-tools` (RHEL). Требует ядро ≥ 4.8 с поддержкой BTF (рекомендуется ≥ 5.8).

### 11. Обнаружение дедлоков (Deadlock Detection)

Дедлок возникает, когда два или более потока ожидают ресурсы, захваченные друг другом.

**Диагностика через strace:**
```bash
# Трассировка блокирующих syscall у всех потоков процесса
sudo strace -f -e trace=all -p <PID> 2>&1 | grep -E "futex|lock|wait"
# → Ожидание futex указывает на блокировку в userspace
```

**Диагностика через gdb:**
```bash
sudo gdb -p <PID>
(gdb) thread apply all bt
# → Поиск одинаковых адресов блокировок в разных потоках
```

**Автоматизированный анализ:**
```bash
# ThreadSanitizer (TSan) при компиляции с -fsanitize=thread
gcc -fsanitize=thread -g myapp.c -o myapp
./myapp
# → WARNING: ThreadSanitizer: data race ...
```

### 12. Трассировка через debugfs и kprobes

Для глубокой трассировки работы ядра без eBPF используется `debugfs`:

```bash
# 1. Монтирование debugfs
sudo mount -t debugfs none /sys/kernel/debug

# 2. Просмотр доступных kprobes
cat /sys/kernel/debug/tracing/available_filter_functions | grep -i "do_nanosleep" | head

# 3. Установка kprobe (функция входа)
echo 'p:myprobe do_nanosleep' | sudo tee /sys/kernel/debug/tracing/kprobe_events

# 4. Включение трассировки
echo 1 | sudo tee /sys/kernel/debug/tracing/events/kprobes/myprobe/enable

# 5. Чтение
cat /sys/kernel/debug/tracing/trace_pipe

# 6. Удаление
echo 0 | sudo tee /sys/kernel/debug/tracing/events/kprobes/myprobe/enable
echo '-:myprobe' | sudo tee /sys/kernel/debug/tracing/kprobe_events
```

## Troubleshooting

### strace не цепляется к процессу: `Operation not permitted`

**Причина:** `kernel.yama.ptrace_scope=1` (по умолчанию в Ubuntu/Debian) или процесс принадлежит другому пользователю.

**Решение:**
```bash
# Временное разрешение (до перезагрузки)
sudo sysctl -w kernel.yama.ptrace_scope=0
# → kernel.yama.ptrace_scope = 0

# Для одного процесса
sudo strace -p <PID>

# Постоянное изменение (не рекомендуется для Prod)
echo "kernel.yama.ptrace_scope = 0" | sudo tee /etc/sysctl.d/99-ptrace.conf
```

### perf: `permission denied` на событиях ядра

**Причина:** `perf_event_paranoid` блокирует доступ к CPU-counters ядра.

**Решение:**
```bash
# Проверка текущего значения
cat /proc/sys/kernel/perf_event_paranoid
# → 2 (по умолчанию — только user-space)

# Временное разрешение
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid
```

### bpftrace: `BCC is not compiled with BTF support`

**Причина:** Ядро без BTF (≥ 5.8) или старый bpftrace.

**Решение:**
```bash
# Проверка версии ядра
uname -r
# → 6.8.0

# Проверка BTF
ls /sys/kernel/btf/vmlinux
# → /sys/kernel/btf/vmlinux

# Установка современных инструментов
sudo apt install bpftrace linux-tools-$(uname -r)
```

### strace: высокое замедление процесса

**Причина:** `strace` использует `ptrace`, который останавливает процесс на каждом syscall.

**Решение:** Использовать `bpftrace` для Production-трассировки:
```bash
# Вместо strace -f -p <PID> в Prod
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { @[comm] = count(); }'
```

### `perf record`: пустой отчет или `[unknown]`

**Причина:** Отсутствуют debug-символы ядра или приложения.

**Решение:**
```bash
# Установка debug-символов (Debian/Ubuntu)
apt-get install linux-image-$(uname -r)-dbgsym

# Для приложения
apt-get install myapp-dbg

# Проверка символов
perf report --vmlinux /usr/lib/debug/boot/vmlinux-$(uname -r)
```

## Best Practices

### Безопасная трассировка в Production

1. **Приоритизируйте eBPF над ptrace:** `bpftrace` и BCC инструменты имеют overhead < 5%, в отличие от `strace`/`gdb` (10-100x замедление).
2. **Используйте coredump вместо gdb attach:** `gcore` или `coredumpctl` создают дамп без полной остановки процесса.
3. **Ограничьте время трассировки:** Для `strace` и `perf record` всегда указывайте `-- sleep N` или `-c` (количество событий).
4. **Фильтруйте syscall:** `strace -e trace=network,file` вместо полной трассировки `-e trace=all`.
5. **Используйте `-T` в strace:** Измеряйте время каждого syscall для быстрого выявления блокировок.
6. **Не запускайте в Prod без dry-run:** Сначала проверьте команду на staging-среде.

### Мониторинг и алертинг

- **perf top** — для быстрого поиска «горячих» функций в рабочем чате.
- **PSI** — для оценки давления на ресурсы без инструментации.
- **bpftrace one-liners** — для точечной диагностики (например, `opensnoop` для поиска медленного диска).

### Чистка после трассировки

```bash
# Отключение kprobes
echo 0 | sudo tee /sys/kernel/debug/tracing/events/kprobes/*/enable

# Отключение tracing
echo nop | sudo tee /sys/kernel/debug/tracing/current_tracer

# Удаление временных BCC-программ
sudo rm -f /tmp/opensnoop_kern.o

# Очистка дампов
rm -f /tmp/perf.data /tmp/capture.core
```

## Additional Information

### Безопасность ptrace
По умолчанию `kernel.yama.ptrace_scope=1` — непривилегированные процессы не могут трассировать друг друга.

```bash
# Временное разрешение для отладки
sudo sysctl -w kernel.yama.ptrace_scope=0
# → kernel.yama.ptrace_scope = 0
```

### См. также
- [**Диагностика производительности: кейсы**](./linux_performance_diagnostics_case.md)
- [**Отладка через Coredump**](./coredump_debugging.md)
- [`lsof` — Список открытых файлов](../Processes/lsof.md)
