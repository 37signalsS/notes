# strace для диагностики файловых систем

## Определения

- **strace (System Trace):** Утилита для трассировки системных вызовов процесса и сигналов, которые он получает. Использует механизм `ptrace` для перехвата каждого системного вызова при входе в ядро и выходе из него. Для диагностики ФС позволяет увидеть точную последовательность обращений к файлам: `openat`, `read`, `write`, `stat`, `fstat`, `lstat`, `access`, `rename`, `unlink`, `fsync`, `fdatasync`.
- **ptrace (Process Trace):** Механизм ядра Linux, позволяющий одному процессу (трассировщику) наблюдать и контролировать выполнение другого (трассируемого). `strace` использует `PTRACE_SYSCALL` для остановки процесса на границе каждого системного вызова.
- **Эффективность (Wall Clock):** Параметр `-T` показывает реальное время выполнения каждого системного вызова. Позволяет идентифицировать «медленные» операции (дисковый I/O, сетевые запросы).
- **Сводка (Summary):** Параметр `-c` агрегирует количество вызовов и время по типам syscall, что быстрее для первичного анализа, чем просмотр полного лога.
- **Фильтрация по группам:** `strace` поддерживает фильтрацию по категориям вызовов: `-e trace=file` (файловые), `-e trace=network` (сетевые), `-e trace=process` (процессы), `-e trace=signal` (сигналы).

## Основные концепции

### Механизм работы при диагностики ФС

При запуске `strace -e trace=file <процесс>` ядро перехватывает каждый файловый syscall и выводит его аргументы и результат:

```bash
strace -e trace=file -T ls /tmp
# → openat(AT_FDCWD, "/tmp", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 3 <0.000042>
# → getdents64(3, /* 6 entries */, 32768) = 216 <0.000018>
# → write(1, "file1\nfile2\n", 12) = 12 <0.000035>
# → close(3) = 0 <0.000015>
```

**Ключевые файловые syscall'ы:**

| Syscall | Назначение | Типичная проблема |
|:---|:---|:---|
| `openat` / `open` | Открытие файла | `ENOENT` (файл не найден), `EACCES` (нет прав), `EMFILE` (много открытых файлов) |
| `stat` / `lstat` / `fstat` | Получение метаданных | `ENOENT`, `ELOOP` (цикл симлинков) |
| `read` / `write` | Чтение/запись данных | `EIO` (ошибка диска), `EAGAIN` (неблокирующий I/O) |
| `fsync` / `fdatasync` | Сброс данных на диск | Долгое выполнение (долгий I/O или нет PLP) |
| `rename` | Переименование | `EXDEV` (跨-FS), `EBUSY` (файл открыт) |
| `unlink` | Удаление | Файл остается открытым (deleted-but-open) |
| `access` | Проверка прав | `EACCES` (SELinux, ACL, права) |
| `chmod` / `chown` | Изменение прав | `EPERM` (нет привилегий) |
| `mmap` | Отображение файла в память | Проблемы с shared memory, coredumps |

### Интерпретация времени выполнения

Параметр `-T` выводит wall-clock time для каждого вызова. Это ключевой показатель для поиска узких мест ФС:

```bash
strace -T -e trace=file,fsync nginx 2>&1 | grep -E '<[0-9]+\.[0-9]+>'
# → write(7, "2024-01-15 ..."..., 128) = 128 <0.000089>
# → fsync(7) = 0 <0.023456>      ← подозрительно долго!
```

**Пороговые значения для файловых операций (NVMe):**

| Операция | Норма | Проблема |
|:---|:---|:---|
| `openat` (локальный) | < 0.1 мс | > 1 мс (много файлов или медленная ФС) |
| `read` / `write` (small) | < 0.05 мс | > 0.5 мс (дисковый I/O) |
| `fsync` / `fdatasync` | < 1 мс | > 5 мс (нет PLP, journal storm) |
| `stat` | < 0.05 мс | > 0.5 мс (NFS, FUSE, million files) |

### Ограничения strace в контексте ФС

1. **Накладные расходы:** `ptrace` останавливает процесс на каждый syscall. На нагруженных серверах это замедление может составлять 10–100x. Используйте только для кратковременной диагностики.
2. **Не видит Page Cache:** `strace` показывает `read`/`write` syscall'ы, но не отражает, что данные были обслужены из page cache (без физического I/O). Для анализа физического I/O используйте `biolatency` или `iotop`.
3. **Не видит `io_uring`:** Приложения с `io_uring` (ScyllaDB, modern databases) используют `io_uring_enter` syscall, а не классические `read`/`write`. `strace` покажет `io_uring_enter`, но не покажет конкретные I/O-операции внутри.
4. **Стек вызовов:** `strace` не показывает стек вызовов (какой код вызвал syscall). Для этого используйте `perf trace` или `bpftrace`.

## Практические сценарии

### Диагностика: приложение не может открыть файл

```bash
# Шаг 1: Трассировка файловых syscall'ов
strace -e trace=file -f -o /tmp/strace.log myapp 2>&1

# Шаг 2: Анализ лога на ошибки
grep -E 'ENOENT|EACCES|EPERM|EMFILE' /tmp/strace.log
# → openat(AT_FDCWD, "/etc/myapp/config.yaml", O_RDONLY) = -1 ENOENT (No such file or directory)
# → openat(AT_FDCWD, "/var/log/myapp/app.log", O_WRONLY|O_CREAT|O_APPEND, 0644) = -1 EACCES (Permission denied)

# Шаг 3: Проверка количества открытых файлов (если EMFILE)
ls /proc/$(pgrep -f myapp)/fd | wc -l
cat /proc/$(pgrep -f myapp)/limits | grep "Max open files"
```

### Диагностика: почему процесс завис в D-state

```bash
# Шаг 1: Определение PID зависшего процесса
ps -eo pid,stat,wchan:20,comm | awk '$2 ~ /D/ {print}'
# → 12345 D  jbd2/sda1-8        jbd2

# Шаг 2: Текущий syscall (без strace, если процесс в D)
cat /proc/12345/syscall
# → 231 (fsync)

# Шаг 3: Если процесс НЕ в D-state, использовать strace
sudo strace -p 12345 -e trace=fsync -T
# → fsync(7) = 0 <3.456789>  ← 3.5 секунды на fsync!
```

### Диагностика: утечка файловых дескрипторов

```bash
# Шаг 1: Найти процесс с растущим количеством FD
for pid in $(pgrep -f myapp); do
  echo "PID $pid: $(ls /proc/$pid/fd 2>/dev/null | wc -l) open files"
done

# Шаг 2: Мониторинг открытия/закрытия файлов в реальном времени
sudo strace -p $PID -e trace=openat,close -T 2>&1 | \
  awk '/openat/{print NR, $0} /close/{print NR, $0}' | tail -20

# Шаг 3: Поиск打开了但未 закрытых файлов
sudo lsof -p $PID | awk '$4 == "REG" {print $9}' | sort | uniq -c | sort -rn | head
```

### Диагностика:缓慢的 fsync в PostgreSQL/MySQL

```bash
# Шаг 1: Найти процесс СУБД
PID=$(pgrep -f "postgres: wal writer")

# Шаг 2: Мониторинг fsync/fdatasync с замером времени
sudo strace -p $PID -e trace=fsync,fdatasync -T -c -S time 2>&1 | head -20
# → % time     seconds  usecs/call     calls    errors syscall
# →  98.50    2.345678        2345      1000           fdatasync
# →   1.50    0.035678          35      1000           fsync

# Шаг 3: Анализ p99 задержек (отдельный прогон)
sudo strace -p $PID -e trace=fdatasync -T -o /tmp/fsync_trace.log &
sleep 60
kill %1
awk -F'[<>]' '/fdatasync/{print $2}' /tmp/fsync_trace.log | sort -n | tail -5
```

### Диагностика: что именно пишет процесс

```bash
# Трассировка write с выводом первых байт данных
sudo strace -p $PID -e trace=write -s 256 -X 32 2>&1 | head -20
# → write(7, "2024-01-15T12:00:01Z INFO Request..."..., 4096) = 4096
# → write(7, "\x1f\x8b\x08\x00..."..., 8192) = 8192  ← gzip-данные

# Для бинарных данных: только размеры
sudo strace -p $PID -e trace=write 2>&1 | grep -oP 'write\(\d+, .+?, (\d+)\)' | awk -F', ' '{print $3}' | sort | uniq -c | sort -rn
```

### Массовый поиск процессов, пишущих в определенный файл

```bash
# Найти все процессы, открывающие /var/log/syslog
sudo strace -e trace=openat -f 2>&1 | grep '/var/log/syslog' &
sleep 5
kill %1

# Или через inotifywait (проще)
sudo inotifywait -m -r -e access /var/log/syslog &
sleep 5
kill %1
```

### Анализ производительности ФС через strace

```bash
# Сводка по времени на файловые операции
strace -c -e trace=file,fsync,fdatasync ls -la /var/log/ | tail -15
# → % time     seconds  usecs/call     calls    errors syscall
# →  45.00    0.045000          45      1000           getdents64
# →  30.00    0.030000          30      1000           stat
# →  15.00    0.015000          15       500           openat
# →  10.00    0.010000          10       300           close

# Сравнение двух ФС (ext4 vs XFS)
strace -c -e trace=file,fsync tar cf /dev/null /mnt/ext4_data/ 2>&1 | tail -5
strace -c -e trace=file,fsync tar cf /dev/null /mnt/xfs_data/ 2>&1 | tail -5
```

## Интеграция с другими инструментами

### strace + lsof: полная картина открытых файлов

```bash
# Шаг 1: Найти подозрительные открытые файлы
sudo lsof -p $PID | grep '\.log'

# Шаг 2: Трассировка для понимания паттерна
sudo strace -p $PID -e trace=openat,close,write -T 2>&1 | \
  grep '\.log' | head -20
```

### strace + iostat: корреляция syscall с дисковой активностью

```bash
# В терминале 1:
sudo iostat -xz 1

# В терминале 2:
sudo strace -p $PID -e trace=fsync,fdatasync -T 2>&1 | \
  awk -F'[<>]' '/fsync/{printf "fsync at %s: %s ms\n", strftime("%H:%M:%S"), $2}'
```

### strace + perf: стек вызовов для缓慢ых syscall'ов

```bash
# Найти функции, вызывающие缓慢ые fsync
sudo perf record -e syscalls:sys_enter_fdatasync -p $PID -g -- sleep 30
sudo perf report --stdio | head -30
```

## Прочее: трассировка сетевых, сигнальных и других вызовов

### Сетевые системные вызовы

```bash
# Трассировка сетевых вызовов (connect, sendto, recvfrom)
strace -e trace=network -p $PID

# С таймингом для поиска медленных сетевых операций
strace -e trace=network -T -p $PID

# Трассировка всех сетевых вызовов при старте программы
strace -e trace=network -f curl -s https://api.example.com
```

### Сигналы и процессы

```bash
# Трассировка сигналов (kill, sigaction)
strace -e trace=signal -p $PID

# Трассировка fork/clone (дочерние процессы)
strace -e trace=process -f -p $PID

# Трассировка execve (что запускается)
strace -e trace=execve -f command

# Печать стека вызовов для каждого вызова (требует unwind info)
strace -k -p $PID
```

### Инъекция системных вызовов (fault injection)

```bash
# Искусственно вызвать ошибку write (EIO)
strace -e inject=write:retval=-1:EIO -p $PID

# Инициировать SIGTERM при следующем write
strace -e inject=write:signal=SIGTERM -p $PID

# Эмуляция нехватки памяти для mmap
strace -e inject=mmap:retval=-1:ENOMEM -p $PID
```

### Файловые дескрипторы — расширенная диагностика

```bash
# Трассировка операций с fd (close, dup2, fcntl)
strace -e trace=desc -p $PID

# Трассировка нескольких категорий с таймингом
strace -e trace=file,network,signal -T -p $PID
```

## Типичные ошибки и диагностика

| Ошибка / Симптом | Причина | Команда диагностики | Решение |
|:---|:---|:---|:---|
| `ENOENT` при открытии файла | Неверный путь или файл удален | `strace -e trace=file` | ПроверьтеPWD, working directory приложения |
| `EACCES` при открытии | Нет прав, SELinux, ACL | `strace -e trace=file` + `ls -la` + `getenforce` | `chmod`, `restorecon`, проверка ACL |
| `EMFILE` (too many open files) | Исчерпан лимит FD | `ls /proc/PID/fd \| wc -l` + `cat /proc/PID/limits` | Увеличьте `nofile` в systemd/ulimit |
| `EIO` при чтении/записи | Аппаратная ошибка диска | `dmesg \| grep -i "I/O error"` + `smartctl` | Замена диска |
| `ENOSPC` при записи | Место на диске закончилось | `df -h` + `df -i` | Очистка места или расширение тома |
| `EBUSY` при переименовании/удалении | Файл открыт другим процессом | `lsof +D /path/to/file` | Остановите процесс или `truncate` |
| `ELOOP` при stat/open | Цикл симлинков | `strace -e trace=file` + `find -type l` | Удалите циклическую ссылку |
| `fsync` занимает > 100 мс | Нет PLP, journal storm, медленный диск | `strace -T -e trace=fsync` | Enterprise SSD с PLP, тюнинг journal |
| `write` возвращает `EAGAIN` | Неблокирующий I/O, полный буфер | `strace -e trace=write` | Увеличьте буфер или используйте блокирующий I/O |

## Рекомендации (Best Practices)

1. **Кратковременность:** Не оставляйте `strace` на长时间 в production. Используйте `-p <PID>` для точечной диагностики, `-c` для сводки.
2. **Фильтрация:** Всегда используйте `-e trace=file` для анализа ФС, а не полную трассировку. Снижает overhead в 5–10 раз.
3. **Безопасность:** `strace` к чужому процессу требует `CAP_SYS_PTRACE` или root. В контейнерах используйте `--cap-add=SYS_PTRACE` или `nsenter`.
4. **Для production:** Используйте `perf trace` или `bpftrace` вместо `strace` — они не останавливают процесс и имеют меньший overhead.
5. **Логирование:** Всегда сохраняйте вывод в файл (`-o /tmp/strace.log`) для анализа, так как вывод в stdout может быть потерян.
6. **Связывайте с dmesg:** Если `strace` показывает `EIO` или `ENXIO`, проверьте `dmesg -T | grep -i "error\|I/O"` для поиска аппаратных проблем.

## Дополнительная информация

- **Сравнение strace и eBPF:** [Трассировка и отладка в Linux](../Troubleshooting/tracing_and_debugging.md) — когда использовать strace, а когда eBPF.
- **Диагностика открытых файлов:** [lsof](../Processes/lsof.md) — поиск процессов по открытым файлам.
- **PSI для оценки давления I/O:** [PSI](../../Core/kernel/psi.md) — количественная оценка потерь производительности.
- **/proc/PID/syscall для зависших процессов:** [Виртуальная ФС /proc](../../FileSystems/virtual_fs_proc.md) — диагностика без strace.
