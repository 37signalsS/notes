# Отладка процессов: утечки памяти, дампы памяти и зомби-процессы

## Определения

**Отладка (Debugging) процессов** — совокупность методов выявления и устранения ошибок, связанных с жизненным циклом процесса, потреблением ресурсов и аварийными завершениями.

**Memory Leak (утечка памяти)** — состояние, при котором приложение выделяет память (через `malloc`, `mmap`), но не освобождает её. Ведет к росту RSS и срабатыванию OOM Killer.

**Coredump (дамп памяти)** — снимок адресного пространства процесса в момент аварии. Содержит состояние регистров, стека и переменных для «посмертного» анализа.

**Zombie Process (зомби-процесс)** — задача, завершившая выполнение, но занимающая запись в таблице процессов ядра до тех пор, пока родитель не прочитает её статус через `wait()`.

**Orphan Process (процесс-сирота)** — работающий процесс, чей родитель завершился. Автоматически «усыновляется» процессом с PID 1.

**Uninterruptible Sleep (состояние D)** — состояние процесса, ожидающего завершения системного вызова (обычно I/O). Не реагирует на сигналы, включая `SIGKILL`.

**Memory Fragmentation (фрагментация памяти)** — состояние, при котором свободная память разбита на мелкие непрерывные блоки, недостаточные для удовлетворения запроса большого размера (аналогично `order > 0` в логах OOM).

**Signal Handler (обработчик сигнала)** — функция, зарегистрированная через `signal()` или `sigaction()` для выполнения определенной логики при поступлении сигнала. Если обработчик не установлен, сигнал использует поведение по умолчанию.

## Основные концепции

### Типичные проблемы жизненного цикла

- **Аварийные сигналы:** Ядро завершает процесс при `SIGSEGV` (память), `SIGFPE` (арифметика) или `SIGILL` (недопустимая инструкция).
- **Проблема Reaping (Сбора):** Если PID 1 в системе (или внутри контейнера) некорректно обрабатывает `SIGCHLD`, система наполняется зомби, что ведет к исчерпанию `pid_max`.
- **D-state и Load Average:** Процессы в состоянии D увеличивают показатель LA, даже если CPU простаивает. Часто указывает на проблемы с дисковой подсистемой или сетевыми ФС (NFS).
- **Маскирование сигналов:** Если процесс ведет себя странно и не завершается по `SIGTERM`, возможно, сигнал заблокирован или игнорируется. Эту информацию можно извлечь из `/proc/PID/status`.
- **Fork-бомбы:** Нецобирающиеся ресурсы процессы могут исчерпать PID namespace или таблину процессов, что приводит к отказу всей системы в создании новых задач.

### Иерархия диагностических инструментов

| Инструмент | Уровень | Overhead | Применимость | Описание |
| :--- | :--- | :--- | :--- | :--- |
| `ps`, `top`, `/proc/PID/status` | Легкий снимок | ~0% | Всегда | Быстрая оценка состояния и сигналов |
| `smem`, `smaps_rollup` | Память | ~1-5% | Production | Анализ PSS, выявление утечек |
| `pidstat`, `sar` | Мониторинг | ~1-5% | Production | Сбор исторических данных |
| `lsof`, `ls /proc/PID/fd` | FD | ~0-1% | Production | Проверка дескрипторов |
| `memleak` (BCC) | Аллокации | ~5-10% | Production | eBPF-детекция утечек без остановки |
| `valgrind`, `heaptrack` | Полный анализ | 10-100x | Staging/Preprod | Точная диагностика, требует replay |
| `gdb attach`, `strace -p` | Интерактив | High / Stop-the-world | Dev/Emergency | Глубокий анализ с остановкой процесса |

> **Примечание:** Для production-сред с минимальным overhead предпочтительно использовать eBPF-инструменты. Подробнее о выборе подходящего инструмента — в [`Методология strace vs eBPF`](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md).

## Практические сценарии

### Диагностика утечек памяти

#### 1. Анализ PSS (Proportional Set Size)

RSS может вводить в заблуждение из-за разделяемых библиотек. Используйте `smem` для оценки реального владения памятью.
```bash
# Топ процессов по PSS (требует smem)
smem -rk -s pss | head
```

#### 2. Глубокий анализ через /proc/PID/smaps

`smem` и `smaps_rollup` дают агрегат, но для поиска точного источника утечки нужен `smaps` — детальная карта страниц:
```bash
# Поиск сегмента с максимальным Private_Dirty (наиболее вероятный heap)
grep -A15 "Size:" /proc/<PID>/smaps | grep -B1 "Private_Dirty:[[:space:]]*[1-9]" | grep -E "^(Size|Private_Dirty|Shared)"

# Или более просто — ищем все сегменты с Dirty > 0
awk '/^Size:/{size=$2} /^Private_Dirty:/ && $2>0 && $2!="kB"{print size, $0}' /proc/<PID>/smaps
```

#### 3. Трассировка аллокаций (BCC memleak)

Позволяет найти место в коде, где выделяется, но не освобождается память, с минимальным оверхедом.
```bash
# Отслеживание утечек в процессе 1234 каждые 5 секунд
sudo memleak -p 1234 -t 5
# → Выводит стек вызовов malloc/mmap без соответствующего free/unmap
```

#### 4. Анализ трендов (а не мгновенного снимка)

Важен не мгновенный замер, а тренд. Нужно смотреть на память процесса за несколько дней. Если она ровно ползёт вверх и никогда не спадает — приложение не отдаёт то, что взяло, и утечка подтверждена.

```bash
# Исторические данные о памяти процессе через sar (требует sysstat)
sar -r -P ALL --human
# → %mem: рост без падений → утечка

# Или запрос RSS процесса в цикле (ручной сбор тренда)
while true; do
  date '+%H:%M'; ps -o rss= -p <PID>; sleep 60
done
```

Одиночный снимок (`ps`, `top`) может ввести в заблеждение: кратковременный рост RSS часто является нормальной работой аллокаторов памяти (jemalloc, glibc malloc), которые держат freed-блоки в кэше для переиспользования. Истинная утечка проявляется в постоянном росте без спадов.

#### 5. Valgrind: memory leak и heap profiling

`valgrind` — эталонный инструмент для лабораторной диагностики. Требует replay-окружения, но выдаёт буквально каждый leaked байт.

```bash
# Полный анализ утечек с группировкой по источнику
valgrind --tool=memcheck --leak-check=full --show-leak-kinds=all ./myapp

# heap profiler: запись тренда роста кучи во времени
valgrind --tool=massif --time-unit=B --detailed-freq=1s ./myapp
# → massif.out.<PID>
# ms_print massif.out.<PID>  — ASCII-график роста кучи
```

**Вывод valgrind:**
```text
==12345== 4,096 bytes in 1 blocks are definitely lost in loss record 1 of 1
==12345==    at 0x4C2AB80: malloc (in /usr/lib/valgrind/vgpreload_memcheck-amd64-linux.so)
==12345==    by 0x400526: process_request (main.c:42)
==12345==    by 0x400600: main (main.c:78)
```

#### 6. Heaptrack: production-friendly profiling

`heaptrack` использует `LD_PRELOAD` для перехвата аллокаций без полной эмуляции, как valgrind. Overhead ~5-10x (вместо 50-100x), подходит для staging.

```bash
# Запуск с записью профиля
heaptrack ./myapp

# Анализ
heaptrack_print heaptrack.myapp.*.gz
# → Показывает топ аллокаций по стеку и размеру
```

#### 7. pmap: проверка карты памяти

```bash
# Анализ потребления памяти по сегментам
pmap -x <PID>
# → showmem: сравните RSS и Swap на каждом участке

# Быстрая проверка анонимных сегментов (heap)
pmap -x <PID> | grep -E "total|anon|heap|stack"
```

#### 8. pprof для Go и gperftools (C/C++)

Для Go-приложений используйте pprof:
```bash
# Сбор профиля через HTTP
curl -s http://localhost:6060/debug/pprof/heap > heap.prof

# Анализ
go tool pprof -top heap.prof
go tool pprof -http=:8080 heap.prof
```

Для C/C++ — `gperftools`:
```bash
# В коде: #include <google/profiler.h>
ProfilerStart("cpu.prof");
... код ...
ProfilerStop();
```

### Анализ аварийных завершений (Coredump)

#### 1. Подготовка системы
```bash
# Разрешить дампы неограниченного размера в текущем shell
ulimit -c unlimited

# Для systemd-сервиса (в [Service] юнита)
LimitCORE=infinity
```

#### 2. Работа с coredumpctl (systemd)
```bash
# Поиск последнего падения
coredumpctl list | tail -1

# Запуск отладчика gdb для анализа стека
coredumpctl gdb <PID_OR_COMMAND>
# Внутри gdb:
# (gdb) bt          # вывод стека вызовов (backtrace)
# (gdb) info locals # просмотр локальных переменных
```

#### 3. Расширенный анализ в GDB

Помимо базовых команд, см. [Отладка через Coredump](../../../Diagnostics/Troubleshooting/coredump_debugging.md) для полного справочника gdb. Ключевые дополнительные команды:

```bash
gdb /usr/bin/myapp /tmp/core.<PID>
# (gdb) thread apply all bt         # стек всех потоков (критично для multithreaded)
# (gdb) info registers              # регистры в точке падения
# (gdb) info args                   # аргументы функции
# (gdb) info proc mappings          # карта памяти — ищите corruption
# (gdb) frame 3                     # переход к кадру 3 в стеке
# (gdb) up / down                   # навигация по стеку
# (gdb) print my_var                # значение переменной
# (gdb) p/x $rsp                    # hex-просмотр регистров
# (gdb) x/20gx $rsp                 # дамп памяти со стека (20 строк, 8 байт)
# (gdb) x/s $rdi                    # строка по указателю
# (gdb) break main                  # установить breakpoint
# (gdb) run                         # перезапустить из дампа
```

#### 4. Coredump без systemd (Apport / core_pattern)

В системах без systemd-coredump используйте `apport` или настраивайте `core_pattern` напрямую:

```bash
# Проверка текущего шаблона
cat /proc/sys/kernel/core_pattern
# → /core or |/usr/share/apport/apport %p %s %c

# Настройка: сохранять с PID и hostname
echo "/var/crash/core.%h.%e.%p.%t" | sudo tee /proc/sys/kernel/core_pattern

# Сжатие «на лету» для экономии места
echo "|/bin/gzip -1 > /var/crash/core.%e.%p.gz" | sudo tee /proc/sys/kernel/core_pattern
```

#### 5. Python-программы

Для Python-приложений gdb может быть запущен с расширением:
```bash
python3 -c "import sys; print(sys.executable)"
gdb -p <PID>
(gdb) info proc mappings
(gdb) py-bt              # показать Python stack trace
(gdb) py-list            # исходный код текущей функции
```

### Устранение зомби и сирот

Зомби-процесс (статус **Z**) уже завершен и не потребляет ресурсы (CPU/RAM), но занимает запись в таблице процессов. Важно понимать: **зомби нельзя «убить» напрямую** через `kill -9`, так как процесса физически не существует.

#### Методы «лечения» зомби

1.  **Reaping (Сбор) родителем (Правильный способ):**
    Родительский процесс должен выполнить системный вызов `wait()` или `waitpid()` после получения сигнала `SIGCHLD`. Если у вас есть доступ к коду родителя, необходимо убедиться, что он корректно обрабатывает завершение дочерних процессов.
2.  **Завершение родительского процесса:**
    Если родитель не реагирует и «плодит» зомби, его можно завершить (`kill <PARENT_PID>`). В этом случае зомби-процессы становятся «сиротами» (Orphans) и автоматически усыновляются процессом с **PID 1** (init/systemd), который немедленно выполнит `wait()` и очистит таблицу.
3.  **Перезапуск супервизора или демена:**
    Если родителем является супервизор (например, Systemd, Supervisord) или долгоживущий демон, который перестал корректно собирать детей, может потребоваться перезапуск всей службы (это по сути п. 2 в масштабе сервиса).
4.  **Ручная отправка SIGCHLD:**
    Можно попробовать отправить сигнал `SIGCHLD` родителю вручную:
    ```bash
    kill -s SIGCHLD <PARENT_PID>
    ```
    *Важно:* Это сработает **только в том случае**, если у родителя есть соответствующий обработчик (handler), который вызывает `waitpid()`. Если обработчика нет, сигнал будет проигнорирован.

#### Зомби в контейнерах (PID 1 проблема)

В контейнерах с минимальным образом (scratch, distroless, alpine without init) PID 1 часто становится пользовательским процессом, который **не реапит зомби**. Решение:

```bash
# Используйте tini или dumb-init как PID 1
docker run --init myimage:tag

# Или в Dockerfile:
ENTRYPOINT ["/usr/bin/tini", "--", "/app/mybinary"]
# tini доступен в пакетах: apk add tini, или скачайте static binary

# Проверка: есть ли проблема с зомби в контейнере
docker exec <container> ps aux | grep -E "Z|defunct"
```

`docker --init` автоматически добавляет `tini`. Для Kubernetes — используйте `shareProcessNamespace` + sidecar с init, или `kubectl debug` с `--attach`.

#### Поиск и диагностика
```bash
# Список всех зомби (статус Z) с указанием PID и имени
ps aux | awk '$8=="Z" {print $2, $11}'

# Найти родителя (PPID) конкретного зомби
ps -o ppid= -p <ZOMBIE_PID>

# Подсчёт зомби в системе
ps -eo stat | grep -c "^Z"
```

### Диагностика состояния D (Uninterruptible Sleep)

Процесс «завис» и не убивается через `kill -9`.

#### 1. Определение блокировки
```bash
# На какой функции ядра заблокирован процесс?
cat /proc/<PID>/wchan
# → 'rpc_wait_bit_killable' — NFS; 'blkdev_dequeue_request' — диск I/O

# Полный стек ядра (требует root)
sudo cat /proc/<PID/stack

# Проверка: сколько процессов в D-state?
ps -eo stat,pid,comm | awk '$1 ~ /^D/ {print}'
```

#### 2. Диагностика I/O-узкого места
```bash
# Кто «ест» диск?
sudo iotop -aoP

# Статистика диска: await > 50ms — проблема диска
iostat -xmd 1 5 | grep -vE "^\s*$"

# NFS: статистика запросов по узлам
nfsiostat -c 1
# → retrans: > 2% означает проблемы с сетью/NFS-сервером

# Проверка: висит ли процесс на NFS mount?
mount | grep nfs
# → Проверьте таймауты: timeo=14 (1.4s), retrans=3
```

#### 3. Настройка NFS mount timeouts
Для снижения устойчивости к D-state:
```bash
# В /etc/fstab или mount:
# rw,hard,intr,timeo=600,retrans=2  — уменьшить timeo для быстрого фейловера
# Или: soft,mtime — не рекомендуется для БД, но быстро отпускает

# Проверка: можно ли смонтировать с interruptible
mount -o remount,intr /mnt/nfs
```

#### 4. Recovery: D-state rescue без reboot
```bash
# Остановка службы на проблемном диске
systemctl stop <service-on-bad-device>

# Отмонтирование с forced (может повесить, если D-state процессы)
umount -f /dev/sdX

# Или: сброс I/O через sysfs (Linux 4.19+)
echo 1 > /sys/block/sda/device/delete
# → удалить устройство, затем: echo 1 > /sys/bus/scsi/rescan
```

**В крайнем случае** — IPMI/KVM hard reset для D-state процессов не поддающихся救治.

### Проверка маскирования сигналов

Если процесс игнорирует сигналы управления:
```bash
# Извлечение масок сигналов (шестнадцатеричные значения)
grep Sig /proc/<PID>/status
# SigPnd: сигналы в очереди
# SigBlk: заблокированные сигналы
# SigIgn: игнорируемые сигналы
# SigCgt: пойманные (установленные обработчики)
```
Для декодирования используйте утилиту `sigcheck` или онлайн-калькуляторы битовых масок.

#### Трассировка сигналов через strace
```bash
# Фильтрация только сигнальных вызовов
sudo strace -p <PID> -e trace=signal

# Проверка: доставляется ли сигнал?
sudo strace -p <PID> -e trace=signal -tt
# → 12:00:01.123456 kill(1234, SIGTERM) = 0  — сигнал отправлен
```

## Дополнительная информация

### Безопасность и ограничения

1.  **ptrace_scope:** В современных дистрибутивах (Ubuntu) включен `kernel.yama.ptrace_scope=1`, что запрещает отлаживать процессы, не являющиеся потомками отладчика.
    - *Решение:* `sudo sysctl -w kernel.yama.ptrace_scope=0` (временно).
2.  **pstack:** Легкая обёртка над gdb для быстрого получения стека без долгой остановки процесса надоло.
    ```bash
    sudo pstack <PID>
    ```
3.  **Live attach vs Coredump:** При attach через `gdb -p` процесс останавливается до выхода из gdb. Для production используйте `gcore` (снимок без долгой остановки) или [`coredumpctl`](../../../Diagnostics/Troubleshooting/coredump_debugging.md).
4.  **valgrind overhead:** На production использовать нельзя — overhead 10–100x. Используйте `heaptrack` или `memleak` (BCC) как compromise.

### Production debugging checklist

1.  **Перед attach:** Согласовали с владельцем? Есть ли реплика?
2.  **Таймауты:** Настроены ли health-check timeout больше, чем пауза attach?
3.  **OOM protection:** `systemctl show <svc> -p OOMScoreAdjust` — не -1000? (иначе важные сервисы не защищены).
4.  **Снимок vs attach:** Предпочтительнее `gcore` или `pidstat` — минимум остановки процесса.
5.  **Запись сессии:** Используйте `script` для записи всех команд и вывода.
6.  **Разрешения:** Проверьте `ptrace_scope`, uid совпадает с владельцем процесса.

### Типовые ошибки и ограничения (Edge Cases)

1.  **PID переиспользование (PID recycling):** После завершения процесса его PID может быть назначен новому. Используйте `/proc/PID/starttime` для проверки идентичности.

2.  **Ранний сигнал vs. обработчик:** Некоторые сигналы (например, `SIGCHLD`) могут быть потеряны, если процесс не установил обработчик до их генерации. Решение: всегда используйте `sigaction()` с флагом `SA_RESTART`.

3.  **fork() в multithreaded приложении:** Вызов `fork()` в многопоточном процессе создаёт дочерний процесс с одним потоком — все остальные исчезают. Если они держали мьютексы, потомки могут зависнуть в deadlock. Используйте `vfork()` или `posix_spawn()` вместо `fork()` в многопоточном коде.

4.  **D-state и reboot-less rescue:** Процесс в состоянии D не реагирует на сигналы. Единственные решения: восстановить I/O-подсистему (переподключить NFS, заменить диск) или перезагрузить. Для удалённых серверов — используйте IPMI/KVM для hard reset.

5.  **Silent OOM в cgroup:** cgroups v2 убивает процесс внутри группы, если превышен `memory.max`, но PID 1 контейнера жив. `dmesg` может быть чист. Проверяйте `memory.events.local` в cgroup контейнера. Подробно: [**Диагностика OOM Killer**](../oom_killer_diagnostics.md).

6.  **Проблема с `core_uses_pid`:** Если включено, имя файла изменяется в `core.<binary>.<PID>`. Это путает скрипты, которые ждут `core`. Используйте `core_pattern` с `%p` для предсказуемых имён.

7.  **gdb не может подключиться:** При `ptrace_scope=1` и не-дочернем процессе — gdb падает с `ptrace: Operation not permitted`. Временно отключите: `sudo sysctl -w kernel.yama.ptrace_scope=0`.

8.  **memleak не видит аллокации:** BCC `memleak` по умолчанию отслеживает только `kmalloc/kfree`. Для библиотечных аллокаторов (glibc `malloc`) используйте `-e` или `heaptrack`.

9.  **`ps` snapshot race:** Состояние процесса в `/proc` меняется во время чтения. Для согласованного снимка используйте `ps` (читает за один вызов) или `pidstat` (снимок с меткой времени).

### См. также

- [**Отладка через Coredump**](../../../Diagnostics/Troubleshooting/coredump_debugging.md) — расширенное руководство по gdb, gcore, systemd-coredump.
- [**Трассировка системных вызовов (strace)**](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md) — детальный разбор взаимодействия с ядром.
- [**Сигналы процессов**](../signals.md) — управление и обработка.
- [**Механизм OOM Killer**](../oom_killer_mechanism.md) — теория, PSI, алгоритм выбора жертвы.
- [**Диагностика OOM Killer**](../oom_killer_diagnostics.md) — разбор логов, bpftrace, NUMA.
- [**Управление OOM Killer**](../oom_killer_management.md) — `oom_score_adj`, `choom`, `systemd-oomd`, overcommit.
- [**Концепции лимитов ресурсов**](../resource_limits_concepts.md) — rlimits иерархия, EMFILE/ENFILE.
- [**sar — сбор системной статистики**](../../../Diagnostics/Performance/sar.md) — исторические данные о памяти и нагрузке.
- [**Поиск потока, потребляющего CPU**](../../../Diagnostics/Processes/thread_cpu_troubleshooting.md) — анализ по потокам.
- [**Планирование процессов**](../scheduling.md) — CPU throttling, nice, cgroups.
