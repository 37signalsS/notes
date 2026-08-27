# Отладка DPDK-приложений

### Определения

- **GDB (GNU Debugger)**: Стандартный отладчик для Linux. Позволяет устанавливать breakpoints, inspect переменные, делать backtrace, выполнять пошаговую отладку.
- **Core dump**: Снимок состояния процесса при аварийном завершении (segfault, abort). Содержит стек, регистры, память. Анализ core dump позволяет найти причину crash без запуска под отладчиком.
- **ulimit -c unlimited**: Установка unlimited core file size. Без этого core dump не создаётся.
- **core_pattern**: Параметр ядра `/proc/sys/kernel/core_pattern`, определяющий имя и расположение core dump файлов.
- **RTE_LOG**: Макрос DPDK для логирования. Поддерживает уровни: EMERG, ALERT, CRIT, ERR, WARNING, NOTICE, INFO, DEBUG.
- **--log-level**: Параметр EAL для установки уровня логирования. Формат: `--log-level=<driver>,<level>` или `--log-level=user,5`.
- **RTE_LOG_LEVEL**: Переменная окружения для установки уровня логирования (переопределяет --log-level).
- **DPDK trace**: Система трассировки DPDK (experimental). Позволяет записывать события (packet receive, transmit, mempool get/put) с временными метками.
- **valgrind**: Инструмент для обнаружения утечек памяти, невалидных обращений,未initialized memory. Ограниченная поддержка в DPDK (только secondary process).
- **AddressSanitizer (ASan)**: Инструмент компилятора для обнаружения buffer overflow, use-after-free, double-free. Более быстрый чем valgrind, но требует перекомпиляции.
- **UBSan (UndefinedBehaviorSanitizer)**: Инструмент для обнаружения undefined behavior в C коде.
- **perf**: Linux profiling tool. Позволяет найти hot functions, cache misses, branch mispredictions в DPDK-приложении.
- **addr2line**: Утилита для преобразования адресов из core dump/backtrace в файлы и строки исходного кода.

---

### Теория

#### 1. Типы ошибок DPDK

| Тип | Пример | Инструмент | Сложность отладки |
| :--- | :--- | :--- | :--- |
| **Segfault** | Обращение к невалидному указателю | gdb, core dump | Средняя |
| **Memory leak** | mempool exhaustion, HugePages leak | valgrind, rte_mempool_avail_count | Средняя |
| **Use-after-free** | Использование mbuf после rte_mempool_put | ASan, valgrind | Высокая |
| **Deadlock** | race condition в ring/mempool | gdb, thread analysis | Очень высокая |
| **Performance** | низкий throughput, high latency | perf, top, mpstat | Средняя |
| **NIC errors** | packet drops, CRC errors | ethtool -S, dpdk-proc-info | Низкая |
| **EAL init failure** | "Cannot init EAL", "Cannot open /dev/vfio" | dmesg, strace | Низкая |

#### 2. Настройка core dumps

```bash
# 1. Включить core dumps
ulimit -c unlimited

# 2. Настроить core_pattern
echo "/tmp/core.%e.%p.%t" | sudo tee /proc/sys/kernel/core_pattern
# %e = имя executable
# %p = PID
# %t = timestamp

# 3. Запуск DPDK-приложения
./my_app -l 2-3 -n 4 --socket-mem 1024,0

# 4. Если crash: core dump создаётся в /tmp/core.my_app.12345.1234567890

# 5. Анализ core dump
gdb ./my_app /tmp/core.my_app.12345.1234567890
# (gdb) bt          ← backtrace (стек вызовов)
# (gdb) info registers  ← регистры CPU
# (gdb) print variable_name  ← значение переменной
# (gdb) list        ← исходный код
```

#### 3. Уровни логирования DPDK

```bash
# Все драйверы: уровень 8 (DEBUG)
./app -l 2-3 -n 4 --log-level=8

# Только PMD драйверы: уровень 5 (NOTICE)
./app -l 2-3 -n 4 --log-level=pmd,5

# Только EAL: уровень 3 (ERR)
./app -l 2-3 -n 4 --log-level=eal,3

# Через переменную окружения
export RTE_LOG_LEVEL=8
./app -l 2-3 -n 4

# Комбинация
./app -l 2-3 -n 4 --log-level=user,8 --log-level=pmd,5
```

**Уровни логирования:**

| Уровень | Название | Когда использовать |
| :--- | :--- | :--- |
| 0 | EMERG | Никогда (system is unusable) |
| 1 | ALERT | Никогда (immediate action required) |
| 2 | CRIT | Критические ошибки (硬件 failures) |
| 3 | ERR | Ошибки (не могу создать mempool, NIC init fail) |
| 4 | WARNING | Предупреждения (deprecated API, fallback) |
| 5 | NOTICE | Информативные (NIC link up/down) |
| 6 | INFO | Подробная информация |
| 8 | DEBUG | Максимальная детализация (каждый пакет) |

---

### Практическое руководство

#### 1. Отладка через GDB

**Запуск DPDK-приложения под GDB:**
```bash
# Способ 1: Запуск напрямую
gdb --args ./my_app -l 2-3 -n 4 --socket-mem 1024,0
# (gdb) break main
# (gdb) run
# (gdb) break rte_eth_rx_burst  ← breakpoint на RX function
# (gdb) continue
# (gdb) print nb_rx  ← сколько пакетов получено
# (gdb) backtrace  ← стек вызовов

# Способ 2: Присоединение к работающему процессу
# Найти PID:
pgrep my_app
# → 12345

# Присоединиться:
gdb -p 12345
# (gdb) bt  ← текущий стек
# (gdb) thread apply all bt  ← стеки всех потоков
```

**Полезные команды GDB для DPDK:**
```bash
# Просмотр структуры rte_mbuf
(gdb) print *m
# → pool = 0x7f1234567890
# → buf_addr = 0x7f9876543210
# → data_off = 128
# → pkt_len = 64
# → data_len = 64
# → ol_flags = 0x10000

# Просмотр структуры rte_mempool
(gdb) print *mp
# → name = "mbuf_pool"
# → size = 32768
# → cache_size = 256

# Просмотр register state
(gdb) info registers
# → rax = 0x7f1234567890  ← указатель на mbuf
# → rbx = 0x000000000020  ← nb_rx = 32

# Watchpoint: следить за изменением переменной
(gdb) watch m->refcnt
# → Hardware watchpoint 1: m->refcnt
# → При каждом изменении refcnt →停在这里
```

#### 2. Анализ core dump

```bash
# Быстрый анализ core dump
gdb -batch \
  -ex "thread apply all bt" \
  -ex "info registers" \
  ./my_app /tmp/core.my_app.12345.1234567890

# Типичный вывод:
# Thread 2 (LWP 12346):
# #0  0x00007f1234567890 in rte_eth_rx_burst ()
# #1  0x0000000000401234 in main_loop (arg=0x60) at app/main.c:123
# #2  0x0000000000401567 in lcore_main () at app/main.c:456
# #3  0x00007f1234567abc in __libc_start_main ()
```

**addr2line для преобразования адресов:**
```bash
# Найти строку исходного кода по адресу
addr2line -e ./my_app -f 0x401234
# → main_loop
# → app/main.c:123
```

#### 3. Отладка через logging

**Встраивание логов в DPDK-приложение:**
```c
#include <rte_log.h>

// Настройка логирования
rte_set_log_level(RTE_LOG_DEBUG);  // Установить уровень DEBUG

// Логирование
RTE_LOG(INFO, USER1, "Packet received: port=%u queue=%u nb=%u\n",
        port_id, queue_id, nb_rx);

RTE_LOG(ERR, USER1, "Failed to allocate mbuf: pool=%s avail=%u\n",
        mp->name, rte_mempool_avail_count(mp));

RTE_LOG(DEBUG, USER1, "Flow: src=%08x dst=%08x proto=%u\n",
        src_ip, dst_ip, proto);

// Динамическое изменение уровня логирования
rte_set_log_level(RTE_LOG_DEBUG);  // Включить debug
rte_set_log_level(RTE_LOG_WARNING);  // Выключить debug, оставить warnings
```

#### 4. Отладка через valgrind (limited)

```bash
# Запуск под valgrind (только secondary process)
valgrind --tool=memcheck --leak-check=full \
  ./secondary-app -l 4-5 -n 4 --proc-type=secondary

# Типичные ошибки:
# ==12345== Invalid read of size 8
# ==12345==    at 0x401234: main_loop (app/main.c:123)
# ==12345==  Address 0x7f1234567890 is in a ...

# ==12345== LEAK SUMMARY:
# ==12345==    definitely lost: 1024 bytes in 1 blocks
# ==12345==    indirectly lost: 0 bytes in 0 blocks
```

**Ограничения valgrind с DPDK:**
- Primary process: НЕ поддерживается (valgrind не может работать с HugePages mmap)
- Secondary process: Поддерживается (read-only HugePages)
- Производительность: x10 замедление
- Alternative: AddressSanitizer (ASan)

#### 5. Отладка через ASan (AddressSanitizer)

```bash
# Перекомпиляция с ASan
CC=clang CFLAGS="-fsanitize=address -fno-omit-frame-pointer" \
  meson setup build_asan
ninja -C build_asan

# Запуск
./build_asan/my_app -l 2-3 -n 4 --socket-mem 1024,0

# ASan автоматически обнаружит:
# - Buffer overflow (чтение/запись за пределами буфера)
# - Use-after-free (использование после освобождения)
# - Double-free (двойное освобождение)
# - Memory leaks (опционально)
```

#### 6. Профилирование через perf

```bash
# Запуск DPDK-приложения
./my_app -l 2-3 -n 4 --socket-mem 1024,0

# В другом терминале:
PID=$(pgrep my_app)

# Top functions (CPU time)
sudo perf top -p $PID
# → 90% в rte_eth_rx_burst
# → 5% в rte_eth_tx_burst
# → 3% в process_packet

# Профилирование с call graph
sudo perf record -p $PID -g -- sleep 10
sudo perf report
# → Визуализация: какие функции самые "горячие"

# Cache misses
sudo perf stat -p $PID -e cache-misses,cache-references -- sleep 10

# Branch mispredictions
sudo perf stat -p $PID -e branch-misses,branch-instructions -- sleep 10
```

#### 7. Отладка через strace

```bash
# Трассировка системных вызовов
strace -p 12345 -e trace=open,read,write,mmap
# →能看到哪些 файлы/память DPDK открывает

# Определение为什么会aille init
strace ./my_app -l 2-3 -n 4 2>&1 | grep -i "vfio\|huge\|uio"
# →能看到 DPDK пытается открыть /dev/vfio/*, /dev/hugepages/*
```

---

### Типичные ошибки и их отладка

| Проблема | Как отладить |
| :--- | :--- |
| Segfault в rte_eth_rx_burst | `gdb` → `bt` → проверьте mbuf pool, queue_id, port_id |
| "Cannot init EAL" | `strace ./app ... 2>&1 \| grep -i error` → проверьте HugePages, vfio-pci |
| Memory leak (mempool exhaustion) | `valgrind --leak-check=full` (secondary); логирование `rte_mempool_avail_count()` |
| Race condition в ring | GDB → `thread apply all bt` → проверьте SP/SC vs MP/MC flags |
| NIC не инициализируется | `dmesg \| grep -i vfio` → `ethtool -S` → проверьте IOMMU, driver binding |
| Низкий throughput | `perf top -p PID` → найдите hot function; проверьте NUMA, mempool cache |

---

### Дополнительная информация

- **[DPDK: Технические детали](dpdk_technical.md)** — mempool, rte_ring, HugePages (где искать проблемы).
- **[DPDK: Типичные ошибки](dpdk_technical.md#типичные-ошибки-и-устранение-неисправностей)** — troubleshooting таблица.
- **[DPDK: Тестирование](dpdk_testing.md)** — как выявить performance issues.
- **[GDB Documentation](https://www.gnu.org/software/gdb/documentation/)** — полный мануал GDB.
- **[Valgrind Quick Start](https://valgrind.org/docs/manual/quick-start.html)** — начало работы с valgrind.
- **[AddressSanitizer](https://github.com/google/sanitizers/wiki/AddressSanitizer)** — документация по ASan.
- **[perf Wiki](https://perf.wiki.kernel.org/index.php/Main_Page)** — документация по perf.
