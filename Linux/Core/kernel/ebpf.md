# eBPF (extended Berkeley Packet Filter) — виртуальная машина ядра

## Определения

**eBPF (extended Berkeley Packet Filter)** — это универсальная, событийно-ориентированная виртуальная машина внутри ядра Linux. Она позволяет безопасно выполнять пользовательские программы в адресном пространстве ядра без необходимости модификации исходного кода ядра, загрузки модулей или перезагрузки системы. eBPF превращает ядро в программируемую платформу, позволяя динамически расширять его функциональность в области сетевого взаимодействия, безопасности, мониторинга и планирования задач.

**cBPF (classic BPF)** — изначальная реализация (1992 г.), предназначенная исключительно для фильтрации сетевых пакетов (используется в `tcpdump` и `seccomp`). eBPF значительно расширяет эту архитектуру:
- 11 64-битных регистров (вместо двух 32-битных в cBPF).
- Поддержка структур данных (Maps).
- Возможность вызова функций ядра (Helpers и kfuncs).
- Прикрепление к любым точкам выполнения (kprobes, uprobes, tracepoints).

## Основные концепции

### Жизненный цикл программы eBPF

1.  **Разработка:** Программа пишется на подмножестве C (с использованием `vmlinux.h`) или Rust и компилируется в байт-код eBPF с помощью LLVM/Clang.
2.  **Загрузка:** Байт-код загружается в ядро через системный вызов `bpf()`.
3.  **Верификация (Verifier):** Критический этап безопасности. Ядро проверяет программу на:
    -   Отсутствие бесконечных циклов (проверка графа выполнения).
    -   Безопасный доступ к памяти (границы массивов, инициализация переменных).
    -   Соответствие лимитам сложности (количество инструкций, глубина стека).
    -   Типизацию данных (совместимость типов при вызове хелперов).
4.  **JIT-компиляция:** Проверенный байт-код компилируется в нативные инструкции процессора (x86, ARM64 и др.) для выполнения с максимальной скоростью.
5.  **Прикрепление (Attachment):** Программа привязывается к событию (hook). При возникновении события программа выполняется, обрабатывает контекст и может возвращать результат (например, решение о сбросе пакета).

### Архитектура виртуальной машины eBPF

**Регистры:**
- 11 универсальных 64-битных регистров (`r0`–`r10`).
- `r0` — возвращаемое значение и возврат из функции.
- `r1`–`r5` — аргументы функции.
- `r6`–`r9` — сохраняемые регистры (callee-saved).
- `r10` — стековой указатель (только чтение).

**Инструкции:**
- Подмножество инструкций x86/ARM64, безопасное для ядра.
- Нет произвольных переходов (control flow graph проверяется верификатором).
- Поддержка арифметики, логики,load/store в Maps и стек.

**Верификатор:**
- Выполняет статический анализ графа потока управления.
- Ограничивает глубину стека вызовов (обычно ≤8).
- Ограничивает общее количество инструкций (обычно ≤4096 для программ, прикрепляемых к tracepoints).
- Запрещает неинициализированные переменные и выход за границы массивов.

### Точки подключения (Hooks)

| Hook | Уровень | Назначение |
| :--- | :--- | :--- |
| **kprobe** | Ядро | Динамический перехват функций ядра (доступен всегда, небольшой overhead). |
| **uprobe** | Пространство пользователя | Перехват функций в пользовательских библиотеках/бинарниках. |
| **tracepoint** | Ядро | Статические точки трассировки, встроенные в код ядра (стабильный API). |
| **XDP** | Драйвер NIC | Самый ранний хук — до выделения `sk_buff` (до 24Mpps на ядро). |
| **TC** | Сетевой стек (qdisc) | Обработка пакетов после классификации, но до доставки в приложение. |
| **LSM** | Безопасность | Прикрепление к точкам Linux Security Modules для enforcement политик. |
| **cgroup** | Группы ресурсов | Мониторинг и контроль операций cgroup (создание процессов, выделение памяти). |
| **sockmap** | Сокеты | Перенаправление данных между сокетами внутри ядра, минуя сетевой стек. |

### eBPF Maps (Структуры данных)

Обеспечивают обмен данными между ядром и user-space. Основные типы:
- **Hash Map / Array:** Базовое хранение пар ключ-значение.
- **Ring Buffer (Bpf Ringbuf):** Заменил `Perf Buffer`. Высокопроизводительная очередь для передачи событий в user-space с меньшим оверхедом и сохранением порядка.
- **LRU Hash Map:** Хеш-таблица с автоматическим вытеснением старых записей.
- **Sockmap / Sockhash:** Используются для перенаправления пакетов между сокетами напрямую (`sk_msg`), минуя сетевой стек.
- **Per-CPU Map:** Отдельная копия данных на каждое CPU для устранения contention при параллельном доступе.

### BTF и CO-RE

*   **BTF (BPF Type Format):** Компактный формат метаданных о типах данных ядра.
*   **CO-RE (Compile Once – Run Everywhere):** Технология, позволяющая eBPF-программам работать на разных версиях ядер без перекомпиляции. В момент загрузки библиотека `libbpf` считывает BTF текущего ядра и корректирует смещения в структурах данных (например, если поле в `task_struct` сдвинулось в новой версии ядра).

### Helpers и kfuncs

*   **Helpers:** Стабильный API функций ядра, жестко закодированный в спецификации.
*   **kfuncs (Kernel Functions):** Современный способ вызова функций ядра. Более гибкий механизм, позволяющий ядру экспортировать свои функции для eBPF без изменения основного API, что ускоряет внедрение новых возможностей.

### sched_ext (Kernel 6.12+)

Позволяет реализовывать планировщики CPU на eBPF. Это дает возможность динамически менять алгоритм распределения процессорного времени под конкретные задачи (например, приоритизация игровых кадров или тяжелых SQL-запросов) без пересборки ядра.

## Практические сценарии

### Мониторинг и наблюдаемость

**Continuous Profiling:** Системы (Parca, Pyroscope) используют eBPF для сбора стеков вызовов в реальном времени с минимальным влиянием (<1% CPU), позволяя визуализировать «горячие точки» кода на Flame Graphs.

**bpftrace:** Однострочники для мгновенной отладки системы.

```bash
# Трассировка всех открываемых файлов в системе
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { printf("%s %s\n", comm, str(args->filename)); }'

# Подсчет системных вызовов write() по процессам
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_write { @[comm] = count(); }'

# Замер latency для open() syscall
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { @start[pid] = nsecs; } tracepoint:syscalls:sys_exit_openat { @latency = hist(nsecs - @start[pid]); }'

# Отслеживание создаваемых процессов (execsnoop)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf("%s %d\n", comm, pid); }'
```

**bcc-tools:** Готовые инструменты для частых задач.

```bash
# Топ процессов по количеству открываемых файлов
sudo execsnoop-bpfcc

# Задержка на TCP-рукопожатиях
sudo tcpconnlat

# Ретрансмиссии TCP в реальном времени
sudo tcpretrans
```

### Сетевое взаимодействие

*   **XDP (eXpress Data Path):** Обработка пакетов на уровне драйвера NIC. Идеально для защиты от DDoS (сброс миллионов пакетов в секунду до того, как они нагрузят ядро) и реализации L4-балансировщиков (Katran от Meta).
*   **Cilium:** Заменяет `kube-proxy` (iptables/IPVS) на eBPF, обеспечивая масштабируемость сети в Kubernetes до десятков тысяч узлов без деградации производительности.

Сетевая эффективность eBPF обусловлена выполнением программ в kernel space без системных вызовов. В отличие от user-space сетевой обработки (например, DPDK), где каждый пакет требует переключения контекста между пользовательским и ядровым пространством и копирования данных между буферами, eBPF-программы работают с сетевыми структурами (`sk_buff`, ring-буферы драйвера) напрямую внутри ядра. XDP-программы обрабатывают пакеты на этапе драйвера NIC — ещё до выделения `sk_buff` — что минимизирует путь пакета и достигает производительности более 20Mpps на ядро.

Для глубокого погружения в XDP и TC см.:
- [**eBPF/XDP**](../../Networking/Concepts/sdn/ebpf_xdp.md) — архитектура, сравнение с iptables/OVS, примеры программ.
- [**eBPF в Kubernetes**](../../Kubernetes/Networking/Network/CNI/ebpf.md) — kube-proxy replacement, Hubble, Cilium.

### Безопасность (Runtime Enforcement)

*   **LSM-BPF:** Позволяет писать политики безопасности для Linux Security Modules на eBPF. Это дает возможность блокировать подозрительную активность (например, запись в `/etc/shadow`) на основе сложного контекста процесса, что невозможно сделать через стандартный `seccomp`.
*   **Tetragon:** Обнаруживает и блокирует аномальное поведение (подмена `LD_PRELOAD`, попытки privilege escalation) непосредственно в ядре, предоставляя детальный аудит событий.

### Диагностика и отладка

Для работы с eBPF в системе используется утилита **bpftool**:

```bash
# Список всех загруженных программ
sudo bpftool prog list

# Просмотр содержимого карты eBPF
sudo bpftool map dump id <map_id>

# Просмотр метаданных BTF ядра
sudo bpftool btf dump file /sys/kernel/btf/vmlinux format c

# Проверка доступных функций ядра (kfuncs)
sudo bpftool feature probe

# Просмотр загруженных программ с деталями
sudo bpftool prog dump xlated id <prog_id>
```

### Интеграция с мониторингом

**Prometheus:**
- **node_exporter** собирает метрики BPF Maps (если поддерживается конфигурацией).
- **bpftrace** можно использовать для создания custom metrics:

```bash
# Экспорт счетчика syscall-ов в формате Prometheus
sudo bpftrace -e '
tracepoint:syscalls:sys_enter_openat
{
    @open[comm] = count();
}
interval:s:1
{
    printf("open_total %d\n", @open);
    clear(@open);
}
'
```

**Grafana:**
- Панели для отображения:
    - Количество загруженных eBPF-программ (bpftool prog list).
    - Размер BPF Maps (bpftool map list).
    - Время выполнения eBPF-программ (через `bpftool prog profile`).

### cgroups и планировщик

**cgroup hooks:**
```bash
# Пример: отслеживание создаваемых процессов в cgroup
sudo bpftrace -e '
cgroup/sys/fs/cgroup/system.slice/ {
    tracepoint:syscalls:sys_enter_fork {
        printf("fork in cgroup: %s\n", comm);
    }
}
'
```

**sched_ext (Kernel 6.12+):**
```bash
# Загрузка планировщика на базе eBPF
sudo bpftool prog load sched_ext_prog.o /sys/fs/bpf/sched_ext
sudo bpftool cgroup attach /sys/fs/cgroup/sched_ext sched_attach pinned /sys/fs/bpf/sched_ext
```

### Безопасность

**Ядро:**
```bash
# Проверка, разрешена ли загрузка eBPF обычным пользователям
sysctl kernel.unprivileged_bpf_disabled
# 0 — разрешено (опасно для production)
# 1 — запрещено (рекомендуется)
```

**Yama ptrace_scope:**
```bash
# Проверка ограничений ptrace
sysctl kernel.yama.ptrace_scope
# 0 — нет ограничений
# 1 — только потомки (рекомендуется)
# 2 — только root
# 3 — полностью запрещено
```

**Capabilities:**
```bash
# Минимальные capabilities для загрузки eBPF
sudo setcap cap_bpf,cap_perfmon,cap_sys_admin=+ep /usr/bin/bpftool

# Проверка
getcap /usr/bin/bpftool
# → /usr/bin/bpftool = cap_bpf,cap_perfmon,cap_sys_admin+ep
```

## Производственное развертывание

### Требования к системе

*   **Ядро:** Минимум 4.4, рекомендовано 5.15+ (для Ringbuf, LSM), 6.12+ (для `sched_ext`).
*   **Конфигурация ядра:**
    -   `CONFIG_BPF=y`
    -   `CONFIG_BPF_SYSCALL=y`
    -   `CONFIG_BPF_JIT=y`
    -   `CONFIG_DEBUG_INFO_BTF=y` (необходимо для CO-RE и типизации).
    -   `CONFIG_BPF_EVENTS=y` (для kprobes/uprobes).
*   **Инструментарий:** LLVM/Clang (компиляция), `libbpf-dev` (библиотека разработки), `bpftool` (отладка).

### Ограничения и производительность

| Характеристика | Значение / Ограничение |
| :--- | :--- |
| **Максимальная длина программы** | ~1M инструкций (зависит от типа hook). |
| **Глубина стека вызовов** | Обычно ≤8 фреймов. |
| **Размер Maps** | До нескольких миллионов записей (ограничение памяти). |
| **Время верификации** | От миллисекунд до секунд для сложных программ. |
| **Overhead** | <1% CPU для большинства наблюдаемостных программ. |

### Типичные ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Verifier rejection** | Выход за границы массива, неинициализированная переменная | Проверка вывода `bpftool prog dump xlated`, инициализация всех переменных. |
| **`btf_vmlinux` missing** | Ядро собрано без BTF или пакет `linux-image-*-dbg` не установлен | Установка пакета с отладочной информацией или обновление ядра. |
| **`perf_event_open` failed** | `perf_event_paranoid` слишком строгий или ядро без `CONFIG_BPF_EVENTS` | `sysctl kernel.perf_event_paranoid=1`, проверка конфигурации ядра. |
| **Maps leak** | Программа выгружена неправильно, Maps остаются в ядре | `bpftool map list | grep <name>`, `bpftool map delete <id>`. |
| **High memory usage** | BPF Maps слишком большие или LRU-политика не настроена | Уменьшение размера Maps, настройка `max_entries`, использование `LRU Hash`. |
| **Program not attached** | Ошибка в коде прикрепления или недостаточно прав | Проверка `dmesg`, использование `sudo`, проверка типа hook. |

### Валидация окружения

```bash
# Проверка версии ядра
uname -r
# → 5.15.0-78-generic (минимум 4.4, рекомендовано 5.15+)

# Проверка наличия bpffs
mount | grep bpf
# → bpffs on /sys/fs/bpf type bpf (bpf 0 0)

# Проверка загрузки модулей
lsmod | grep -E 'bpf|jit'
# → bpf 245760 0
# → bpf_jit 16384 1 bpf

# Проверка конфигурации ядра
grep CONFIG_BPF /boot/config-$(uname -r)
# → CONFIG_BPF=y
# → CONFIG_BPF_SYSCALL=y
# → CONFIG_BPF_JIT=y
# → CONFIG_DEBUG_INFO_BTF=y

# Проверка доступных BTF-данных
ls -la /sys/kernel/btf/vmlinux
# → -rw-r--r-- 1 root root 8388608 ... /sys/kernel/btf/vmlinux

# Проверка ограничений eBPF
sudo bpftool feature probe
# → Scanning eBPF features...
# → eBPF JIT enabled: true
# → eBPF ringbuf supported: true
# → eBPF arena supported: false
```

## Связанные темы

*   **Интерфейсы ядра:** [Системные вызовы](./kernel_interfaces.md) — через `bpf()` происходит все взаимодействие.
*   **Cgroups v2:** [Control Groups](../cgroups.md) — eBPF программы могут прикрепляться к cgroups для контроля ресурсов.
*   **Сетевой стек:** [Оптимизация сети](../../Networking/Concepts/rss_rps_rfs.md) — XDP как альтернатива стандартному пути пакета.
*   **eBPF в Kubernetes:** [eBPF в Kubernetes](../../Kubernetes/Networking/Network/CNI/ebpf.md) — kube-proxy replacement, Hubble, Cilium.
*   **eBPF/XDP:** [eBPF/XDP](../../Networking/Concepts/sdn/ebpf_xdp.md) — архитектура XDP, сравнение с iptables/OVS.
*   **Диагностика:** [eBPF-инструменты](../../Networking/ServicesAndTools/Wireshark/ebpf_diagnostics_tools.md) — pwru, bpftrace, dropwatch.
*   **Автоинструментация:** [eBPF и Jaeger](../../Jaeger/jaeger_ebpf_auto_instrumentation.md) — OpenTelemetry eBPF Agent, Odigos, Pixie.
*   **Безопасность:** [Мониторинг безопасности в Runtime](../../Docker/Docker_security/runtime_monitoring.md) — Falco, Tetragon.

## Полезные ресурсы

*   [eBPF.io](https://ebpf.io/) — главный портал сообщества.
*   [BCC (BPF Compiler Collection)](https://github.com/iovisor/bcc) — набор готовых инструментов для диагностики.
*   [libbpf-bootstrap](https://github.com/libbpf/libbpf-bootstrap) — шаблоны для разработки современных eBPF-приложений.
*   [Linux Kernel Documentation — eBPF](https://www.kernel.org/doc/html/latest/bpf/) — официальная документация ядра.
