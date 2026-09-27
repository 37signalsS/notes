# Диагностика утечек файловых дескрипторов и файловых блокировок

## Определения

**Утечка файловых дескрипторов (FD Leak)** — программная ошибка, при которой процесс открывает ресурс (файл, сокет, канал), но не освобождает дескриптор после завершения работы. Приводит к исчерпанию лимитов и ошибке **EMFILE**. Подробнее: [**Диагностика «too many open files»**](./troubleshooting_too_many_open_files.md).

**Файловая блокировка (File Lock)** — механизм синхронизации доступа к файлу. Некорректное управление блокировками вызывает зависание процессов, ожидающих ресурс.

**FLOCK** — блокировка на уровне всего файла через системный вызов `flock()`. Advisory-блокировка, не принудительная.

**POSIX Lock (fcntl)** — блокировка на уровне диапазонов байтов через `fcntl()`. Более гранулярная, чем FLOCK.

**Advisory Locking** — «совещательный» режим: процессы добровольно проверяют блокировку перед доступом. Ядро не принуждает к ожиданию.

**Mandatory Locking** — принудительный режим: ядро блокирует доступ к файлу независимо от логики процессов. Считается устаревшим.

**Open File Table (таблица открытых файлов)** — общесистемная структура ядра, содержащая описания открытых файлов. Каждый дескриптор процесса является ссылкой на запись в этой таблице.

**File Descriptor Table (таблица дескрипторов процесса)** — локальная для каждого процесса структура, содержащая указатели на записи Open File Table.

**Скорость роста FD (FD Growth Rate)** — метрика, определяющая количество новых дескрипторов, открываемых процессом в единицу времени. Положительная скорость при отсутствии явной нагрузки указывает на утечку.

**CLOSE_WAIT Storm** — состояние, при котором процесс накапливает сокеты в состоянии `CLOSE_WAIT`, не закрывая их после получения FIN от удаленной стороны. Приводит к исчерпанию FD лимита.

---

## Основные концепции

### Симптомы проблем

- **Для утечек:** Постепенный рост потребления RAM и количества открытых файлов (проверка через `lsof`). Ошибки «Too many open files».
- **Для блокировок:** Зависание утилит бэкапа, «подвисание» БД (SQLite) без ошибок в логах, невозможность удалить файл, который кажется неиспользуемым.

### Почему стандартные утилиты могут не помочь

`lsof` полагается на `/proc`, который может не успевать за быстрыми изменениями. Для глубокого анализа требуется динамическая трассировка (`strace`) или проверка `lslocks`.

### Внутреннее устройство: таблицы ядра

Ядро Linux использует три уровня таблиц для управления открытыми ресурсами:

1. **Таблица дескрипторов процесса (PDT):** Локальна для каждого процесса. Содержит целые числа (FD), возвращаемые при `open()`/`socket()`. Каждый элемент указывает на запись в Open File Table.
2. **Общесистемная таблица открытых файлов (Open File Table):** Содержит Open File Descriptions — структуры с текущим offset, флагами доступа и счетчиком ссылок. При `dup()`/`fork()` несколько дескрипторов указывают на одну запись.
3. **Таблица Inode:** Хранит метаданные файла на диске (права, размер, временные метки). Несколько Open File Descriptions могут ссылаться на один inode.

При закрытии дескриптора ядро уменьшает счетчик ссылок в Open File Description. При достижении нуля запись удаляется из Open File Table, а при отсутствии других ссылок — освобождается inode.

### Классификация дескрипторов по типам ресурсов

Для диагностики важно понимать, какой тип ресурса занимает дескрипторы:

| Тип | Пример | Характерные признаки |
| :--- | :--- | :--- |
| **Обычные файлы** | `/var/log/app.log` | Путь в `/proc/PID/fd` |
| **Сетевые сокеты** | TCP/UDP соединения | `socket:[12345]`, анализируются через `ss` |
| **Pipes** | Каналы между процессами | `pipe:[12345]` |
| **Unix Domain Sockets** | Локальное IPC | `socket:[12345]`, анализируются через `ss -xp` |
| **epoll/kqueue** | Мультиплексирование I/O | `anon_inode:[eventpoll]` |
| **eventfd/timerfd** | События и таймеры | `anon_inode:[eventfd]`, `anon_inode:[timerfd]` |
| **signalfd** | Чтение сигналов через FD | `anon_inode:[signalfd]` |
| **memfd** | Анонимные файлы в памяти | `memfd:...` |
| **inotify** | Мониторинг ФС | `anon_inode:[inotify]` |
| **fanotify** | Мониторинг ФС (более широкий) | `fanotify` |
| **perf_event** | Профилирование | `perf_event` |
| **bpf** | eBPF программы | `bpf` |

### Дифференциальная диагностика: утечка FD или недостаточный лимит?

Перед увеличением лимитов исключите утечку:

| Критерий | Утечка FD | Недостаточный лимит |
| :--- | :--- | :--- |
| **Рост FD со временем** | Да, даже при стабильной нагрузке | Нет, FD стабильны при пике нагрузки |
| **FD после graceful restart** | Продолжает расти | Сбрасывается до baseline |
| **Соотношение FD/запросов** | > 1 FD на запрос без очевидной причины | Пропорционально нагрузке |
| **Типы FD** | Один тип доминирует (например, CLOSE_WAIT) | Сбалансировано по типам |

---

## Практические сценарии

### 1. Поиск процесса, удерживающего файл

**Использование fuser:**
```bash
fuser -v /var/log/app.log
# →                      USER        PID ACCESS COMMAND
# → /var/log/app.log:    root       1234 f....  nginx
```
*Флаги ACCESS:* `f` (open file), `c` (current dir), `m` (mmap library).

**Через /proc:**
```bash
ls -l /proc/*/fd 2>/dev/null | grep "/var/log/app.log"
```

---

### 2. Анализ файловых блокировок (lslocks)

```bash
lslocks
# → COMMAND           PID   TYPE  SIZE MODE  M      START        END PATH
# → dockerd           950  FLOCK   32K WRITE 0          0          0 /var/lib/docker/volumes/metadata.db
```
*Интерпретация:* Если `MODE=WRITE` — другие процессы будут заблокированы при попытке записи.

---

### 3. Трассировка в реальном времени (strace)

```bash
sudo strace -p <PID> -e trace=openat,socket,close,dup,dup2
# → socket(AF_INET, SOCK_STREAM, ...) = 15
# → (Если вы видите возврат дескриптора, но не видите соответствующего close() — это утечка)
```

---

### 4. Типичные причины утечек в коде

**HTTP-клиент без пула соединений (Go):**
```go
// ПЛОХО: новый клиент на каждый запрос
http.Get(url)

// ХОРОШО: переиспользование клиента с настроенным Transport
var client = &http.Client{
   Transport: &http.Transport{
       MaxIdleConns: 100,
       IdleConnTimeout: 90 * time.Second,
   },
}
```

**Забытый `Body.Close()` (Go):**
```go
resp, err := http.Get(url)
if err != nil { return err }
defer resp.Body.Close() // Обязательно для освобождения сокета
```

**Файлы в горячих циклах (Java):**
```java
// ХОРОШО: гарантированное закрытие через try-with-resources
try (FileInputStream fis = new FileInputStream("config.xml")) {
    // ...
} // fis.close() вызывается автоматически
```

**Другие паттерны:**
- **Подключения к БД без пула:** Создание нового соединения на каждый запрос вместо использования `*sql.DB`.
- **Бесконтрольный рост воркеров:** Каждая горутина/поток удерживает сокет, лимит FD исчерпывается при всплеске нагрузки.
- **Кэш открытых файлов без вытеснения:** Процесс открывает файлы и хранит их дескрипторы «на всякий случай» в Map/Dictionary без очистки.

---

### 5. Количественный анализ: определение скорости роста FD

Для подтверждения утечки требуется несколько измерений:

```bash
# Записьbaseline и тренда
watch -n 10 'ls /proc/<PID>/fd | wc -l'
# → Через 1 час: 1200
# → Через 2 часа: 2400
# → Скорость роста: ~200 FD/час — это утечка

# Проверка: есть ли корреляция с RPS?
# Если FD растут пропорционально нагрузке — это может быть нормально
# Если FD растут при нулевом трафике — утечка подтверждена
```

**Скрипт для расчета скорости роста:**
```bash
#!/bin/bash
# fd_growth_rate.sh
PID=${1}
INTERVAL=${2:-60}  # секунды между замерами

if [ -z "$PID" ]; then
    echo "Usage: $0 <PID> [interval_seconds]"
    exit 1
fi

echo "PID: $PID, measuring every ${INTERVAL}s..."

for i in 1 2 3 4 5; do
    count=$(ls /proc/$PID/fd 2>/dev/null | wc -l)
    echo "$(date '+%H:%M:%S') FD count: $count"
    sleep $INTERVAL
done
```

---

### 6. Дифференциация по типам FD: поиск доминирующего ресурса

```bash
# Общее распределение по типам
lsof -p <PID> | awk '{print $5}' | sort | uniq -c | sort -rn
# →   950 TCP
# →    24 file
# →    12 UDP
# →     6 IPv4

# Если TCP доминирует — проблема в сокетах
# Если file доминирует — проблема в файловом I/O
# Если pipe доминирует — проблема в IPC

# Углубленный анализ TCP-сокетов
ss -tnp | grep <PID> | awk '{print $1}' | sort | uniq -c | sort -rn
# → CLOSE_WAIT 380  ← приложение не закрывает сокеты
# → ESTABLISHED 450  ← нормальные соединения
# → TIME_WAIT 120    ← нормальное замыкание

# Анализ Unix-сокетов
lsof -U -p <PID> | awk '{print $9}' | sort | uniq -c | sort -rn
```

---

### 7. Анализ через /proc/PID/fdinfo (детализация конкретных FD)

Для отдельных дескрипторов можно получить расширенную информацию:

```bash
# Информация о конкретном FD
cat /proc/<PID>/fdinfo/<FD>
# → Для сокетов: отправлено/получено байт, окна, состояние TCP
# → Для eventpoll: список зарегистрированных FD
# → Для timerfd: следующее срабатывание

# Пример: анализ eventpoll FD (показывает, сколько сокетов слушает epoll)
cat /proc/<PID>/fdinfo/3 | head -20
# → events: 1024  (количество зарегистрированных событий)
```

---

### 8. Диагностика утечек Unix Domain Sockets

```bash
# Поиск процессов с большим количеством Unix-сокетов
lsof -U | awk '{print $2}' | sort | uniq -c | sort -rn | head
# →   450 1234  (docker-containerd)
# →   120 5678  (systemd)

# Проверка состояния сокетов
ss -xp | grep <PID>
# → u_str  ESTAB 0      0       /run/systemd/private   users:((\"systemd\",pid=1,fd=12))
```

**Причины утечек Unix-сокетов:**
- Приложение создает сокет для каждого запроса, но не закрывает после обработки.
- D-Bus клиенты не освобождают соединения.
- systemd юниты с `ListenStream=` накапливают дескрипторы.

---

### 9. Трассировка открытия/закрытия через auditd

Для глубокого анализа в production без остановки процесса:

```bash
# Включение аудита для конкретного процесса
sudo auditctl -a always,exit -F pid=<PID> -S openat -S close -S socket -k fd_trace

# Просмотр событий
sudo ausearch -k fd_trace -i --start recent | tail -50
# → type=SYSCALL msg=audit(1699999999:999): arch=c000003e syscall=257 success=yes ...
# → a0=ffffff9c a1=7fffdc9a9c50 a2=241 a3=0 items=1 ppid=1234 pid=5678 auid=1000 uid=1000 gid=1000 euid=1000 suid=1000 fsuid=1000 egid=1000 sgid=1000 fsgid=1000 tty=pts0 ses=3 comm=\"myapp\" exe=\"/usr/bin/myapp\" ...
# → \"/var/log/app.log\" name2=\"app.log\"

# Отключение правила
sudo auditctl -d always,exit -F pid=<PID> -S openat -S close -S socket
```

---

### 10. Диагностика через bpftrace (zero-overhead)

Для production-сред, где `strace` слишком затратен:

```bash
# Подсчет open/close по процессу
sudo bpftrace -e '
tracepoint:syscalls:sys_enter_openat
/comm == "myapp"/
{
    @opens[pid] = count();
}

tracepoint:syscalls:sys_exit_close
/comm == "myapp"/
{
    @closes[pid] = count();
}

interval:s:10
{
    print(@opens);
    print(@closes);
    clear(@opens);
    clear(@closes);
}
'
# → Если opens >> closes — утечка подтверждена
```

---

### 11. Восстановление без перезапуска

**Важно:** Самостоятельное закрытие дескрипторов из userspace может привести к падению приложения. Используйте только при невозможности перезапуска.

**Способ 1: Обнуление файла через дескриптор (безопасно для логов)**
```bash
: > /proc/<PID>/fd/<FD_NUMBER>
```
*Применение:* Только для обычных файлов (не сокетов). Эффективно для логирования.

**Способ 2: Graceful restart воркеров**
```bash
# Nginx/Angie
nginx -s reload

# systemd-сервис с поддержкой graceful
systemctl kill -s SIGUSR1 <service>

# Приложения, реагирующие на SIGUSR2 (логирование)
kill -USR2 <PID>
```

**Способ 3: Принудительное закрытие через gdb (опасно)**
```bash
gdb -p <PID> -batch -ex "call close(<FD_NUMBER>)"
```
*Риск:* Приложение может зависнуть, если дескриптор используется в критической секции.

**Когда НЕЛЬЗЯ закрывать FD вручную:**
- Сокеты в состоянии `ESTABLISHED` (разрыв соединения приведет к ошибкам у клиента)
- БД-соединения (потеря транзакционного контекста)
- Дескрипторы, связанные с файлами блокировок (снятие блокировки приведет к corruption)

---

### 12. Типовые сценарии для распространенных сервисов

**Nginx/Angie:**
```bash
# Проверка текущих лимитов worker-процесса
cat /proc/$(pgrep -n 'nginx: worker')/limits | grep "Max open files"

# worker_rlimit_nofile должен быть >= worker_connections * 2
# (клиент + бэкенд на каждое проксируемое соединение)
# Если worker_connections=1024, то worker_rlimit_nofile >= 2048

# Проверка состояния сокетов worker-процесса
ss -tnp | grep $(pgrep -n 'nginx: worker') | awk '{print $1}' | sort | uniq -c
```

**PostgreSQL:**
```bash
# PostgreSQL открывает FD для каждого соединения + WAL + файлы данных
# max_connections не должен превышать доступный лимит FD
# Рекомендация: LimitNOFILE >= max_connections + max_worker_processes + 20
cat /proc/$(pgrep -n postgres)/limits | grep "Max open files"

# Проверка количества активных соединений
psql -c "SELECT count(*) FROM pg_stat_activity;"
```

**Java-приложения (JVM):**
```bash
# JVM создает потоки, каждый из которых может открывать сокеты
# Минимальный лимит: кол-во потоков * 10 + запас
# Для приложения с 200 потоками: LimitNOFILE >= 65536
ulimit -u 65536
java -Xmx4g -jar app.jar

# Проверка количества потоков
ps -o nlwp,pid,comm -p <PID>
```

**Redis:**
```bash
# Redis открывает FD для каждого клиента + RDB/AOF файлы
# maxclients не должен превышать (LimitNOFILE - запас)
redis-cli CONFIG GET maxclients
# → 10000 (по умолчанию)
# Рекомендация: LimitNOFILE >= maxclients + 100
```

**Go-приложения:**
```bash
# Типичная утечка: http.Client без Transport реиспользования
# Каждый запрос создает новый сокет, который не закрывается
# Мониторинг: количество FD должно быть стабильным, а не расти с RPS

# Проверка: goroutine count через /proc
ls /proc/<PID>/fd | wc -l  # FD count
cat /proc/<PID>/status | grep Threads  # goroutine count (потоки)
```

**Node.js:**
```bash
# Утечка EventEmitter listeners или stream pipes
# Используйте node --max-old-space-size и --max-semi-space-size
# Мониторинг через process._getActiveHandles() и process._getActiveRequests()

# Пример проверки активных хендлов
node -e "console.log(process._getActiveHandles().length)"
# Если число растет при отсутствии нагрузки — утечка
```

---

### 13. Диагностика проблем с файловыми блокировками

**Поиск зависших блокировок:**
```bash
# Список всех активных блокировок
lslocks
# → COMMAND  PID  TYPE  SIZE MODE  M  START  END PATH
# → myapp    1234 FLOCK 4096 WRITE 0      0    0 /var/lib/app/data.lock

# Проверка, какой процесс держит блокировку
fuser -v /var/lib/app/data.lock
# → /var/lib/app/data.lock:  1234  (myapp)

# Принудительное снятие (только если процесс мертв)
fuser -k /var/lib/app/data.lock
```

**Отладка блокировок через flock:**
```bash
# Показать, кто ждет блокировку
flock -n /var/lib/app/data.lock -c "echo acquired" || echo "locked by another process"
```

**Deadlock через POSIX-блокировки:**
```bash
# fcntl блокировки не видны в lslocks
# Используйте strace для отслеживания fcntl вызовов
sudo strace -p <PID> -e trace=fcntl
# → fcntl(3, F_SETLK, {type=F_WRLCK, whence=SEEK_SET, start=0, len=0}) = -1 EAGAIN
# → Процесс не может получить блокировку
```

---

### 14. Анализ файловых дескрипторов через fdinfo

Для отдельных дескрипторов можно получить расширенную информацию:

```bash
# Информация о конкретном FD
cat /proc/<PID>/fdinfo/<FD>
# → Для сокетов: отправлено/получено байт, окна, состояние TCP
# → Для eventpoll: список зарегистрированных FD
# → Для timerfd: следующее срабатывание

# Пример: анализ eventpoll FD (показывает, сколько сокетов слушает epoll)
cat /proc/<PID>/fdinfo/3 | head -20
# → events: 1024  (количество зарегистрированных событий)
```

---

### 15. Обнаружение «fork-бомбы» через FD-анализ

Fork-бомбы быстро исчерпывают FD, наследуя дескрипторы родителя:

```bash
# Резкий рост количества процессов с одинаковым PPID
pstree -p | head -20
# → init(1)─┬─bash(1234)───a.out(5678)───a.out(5679)───a.out(5680)─── ...

# Проверка FD-потребления потомками
ls /proc/1234/fd | wc -l  # Родитель
ls /proc/5678/fd | wc -l  # Потомок (наследует FD родителя)

# Остановка: сначала убиваем родителя fork-бомбы
pkill -9 -f bomb_pattern
```

---

## Обнаружение и мониторинг

### Скрипт для мониторинга FD-потребления

```bash
#!/bin/bash
# monitor_fd_leak.sh
# Мониторит рост FD процесса и предупреждает при утечке

PID=${1}
THRESHOLD_PERCENT=${2:-80}
INTERVAL=${3:-10}  # секунд
COUNT=${4:-6}      # количество замеров для определения тренда

if [ -z "$PID" ]; then
    echo "Usage: $0 <PID> [threshold_percent] [interval_seconds] [count]"
    exit 1
fi

echo "Monitoring PID $PID (threshold: ${THRESHOLD_PERCENT}%, interval: ${INTERVAL}s)"

previous=0
for i in $(seq 1 $COUNT); do
    current=$(ls /proc/$PID/fd 2>/dev/null | wc -l)
    limit=$(cat /proc/$PID/limits 2>/dev/null | grep "open files" | awk '{print $4}')
    
    if [ -z "$limit" ] || [ "$limit" -eq 0 ]; then
        echo "ERROR: Cannot read limits for PID $PID"
        exit 1
    fi
    
    percent=$((current * 100 / limit))
    trend=""
    if [ $i -gt 1 ]; then
        diff=$((current - previous))
        if [ $diff -gt 0 ]; then
            trend="↑ +$diff FD"
        elif [ $diff -lt 0 ]; then
            trend="↓ $diff FD"
        else
            trend="→ stable"
        fi
    fi
    
    echo "$(date '+%H:%M:%S') FD: $current/$limit ($percent%) $trend"
    
    if [ "$percent" -gt "$THRESHOLD_PERCENT" ]; then
        echo "ALERT: FD usage above ${THRESHOLD_PERCENT}%"
    fi
    
    previous=$current
    sleep $INTERVAL
done
```

### Анализ логов приложения

```bash
# Поиск EMFILE в логах journalctl
journalctl -u <service> --since "10 minutes ago" | grep -i "too many open files\|EMFILE\|ENFILE"

# Поиск в логах приложения
grep -r "Too many open files" /var/log/app/

# Проверка системных логов
dmesg | grep -i "file-max\|nr_open"

# Анализ rate ошибок (если есть access log)
grep "EMFILE\|Too many open" /var/log/app/error.log | awk '{print $1}' | uniq -c | sort -rn
```

---

## Обнаружение и предотвращение

### Чек-лист предотвращения утечек FD

**На этапе разработки:**
- [ ] Все открытия файлов/сокетов сопровождаются соответствующим `close()` в блоке `finally` или используются context managers (`defer`, `try-with-resources`, `using`).
- [ ] HTTP-клиенты используют пулы соединений (`http.Client` с `Transport`, не `http.Get` в цикле).
- [ ] Пул DB-соединений настроен с явным `SetMaxOpenConns()` / `maxPoolSize`.
- [ ] Для асинхронного кода (asyncio, goroutines) реализован cancellation и graceful shutdown.
- [ ] Логирование файлов ротируется (`logrotate`, `copytruncate`), а не растет бесконечно.

**На этапе code review:**
- [ ] Проверен каждый `open()`/`socket()` на наличие парного `close()`.
- [ ] Проверен обработчик ошибок: при `return` из функции все открытые FD должны быть закрыты.
- [ ] Проверены циклы: в каждом `for`/`while` нет неконтролируемого открытия FD.

**На этапе deployment:**
- [ ] `LimitNOFILE` в systemd-юните настроен с запасом.
- [ ] `fs.file-max` и `fs.nr_open` увеличены до значений, превышающих сумму лимитов всех сервисов.
- [ ] Включен мониторинг FD-потребления (Prometheus node_exporter или кастомный скрипт).
- [ ] Настроены алерты на рост CLOSE_WAIT и приближение к лимиту FD.

---

### Мониторинг (Prometheus)

```promql
# Процент использования лимита процессом
process_open_fds / process_max_fds > 0.8

# Обнаружение CLOSE_WAIT шторма
node_netstat_Tcp_CloseWait > 1000

# Общее количество открытых FD в системе
sum(node_filefd_allocated) / sum(node_filefd_maximum) > 0.9
```

---

## Специфические сценарии

### Диагностика утечек inotify-дескрипторов

```bash
# Проверка количества inotify FD процесса
ls /proc/<PID>/fd | grep inotify | wc -l

# Глобальный лимит inotify
cat /proc/sys/fs/inotify/max_user_watches
cat /proc/sys/fs/inotify/max_user_instances

# Утечка возникает, когда приложение создает watcher'ы, но не закрывает их
# Типичные виновники: IDE, файловые менеджеры, мониторинговые агенты
```

### Утечка eventfd/timerfd

```bash
# Проверка eventfd
ls /proc/<PID>/fd | grep eventfd | wc -l

# Частая причина: неотмененные таймеры в asyncio/Netty при graceful shutdown
# Решение: корректная отмена всех таймеров перед завершением
```

### Утечка memfd (анонимные файлы в памяти)

```bash
# Проверка memfd
ls /proc/<PID>/fd | grep memfd | wc -l

# Частая причина: утечка в коде, использующем memfd_create() без close()
# Также может быть вызвана bug в библиотеках (например, glib)
```

---

## Крайние случаи

### Накопление FD при Stale File Handle в NFS

```bash
# Найти процессы, удерживающие устаревшие дескрипторы NFS
sudo lsof | grep /mnt/nfs

# Если umount не помогает (девайс занят), используйте "ленивое" размонтирование
sudo umount -l /mnt/nfs
```

### Контейнеры: ограничения cgroup v2

```bash
# Проверка лимитов cgroup
cat /sys/fs/cgroup/<slice>/memory.max
cat /sys/fs/cgroup/<slice>/pids.max
cat /sys/fs/cgroup/<slice>/io.max
```

### Системный журнал (journald)

```bash
# journald может накапливать FD при высокой нагрузке
journalctl --disk-usage
# Проверка количества открытых FD journald
ls /proc/$(pgrep systemd-journald)/fd | wc -l
```

### Наследование FD и роль PID 1

При запуске через systemd, PID 1-процесс наследует все открытые FD родителя. Если родительский процесс (например, shell-скрипт) открыл файл и не закрыл его — systemd-сервис унаследует этот дескриптор.

```bash
# Проверка FD, унаследованных сервисом
systemctl show <service> -p ExecMainPID
ls /proc/$(systemctl show <service> -p ExecMainPID --value)/fd | wc -l
```

---

## Восстановление после инцидента

### Процедура восстановления

1. **Идентификация утечки:** Определите тип доминирующего FD и процесс-виновник.
2. **Временное облегчение:** Увеличьте лимит через `prlimit` для running-процесса.
3. **Graceful restart:** Перезапустите только проблемный сервис, не останавливая всю систему.
4. **Постоянное исправление:** Внедрите исправления в код (закрытие FD, пулы соединений).
5. **Валидация:** Убедитесь, что FD-потребление стабилизировалось на новом baseline.

### Очистка после вмешательства

```bash
# 1. Откат временных drop-in'ов systemd
sudo systemctl revert <service_name>

# 2. Очистка временных правил auditd
sudo auditctl -D

# 3. Проверка отсутствия утечек после восстановления
watch -n5 'ls /proc/<PID>/fd | wc -l'
# → Количество должно стабилизироваться

# 4. Удаление временных конфигураций sysctl
sudo rm /etc/sysctl.d/99-emergency.conf
sudo sysctl --system
```

---

## Дополнительная информация

### Сетевые утечки (Socket Leaks)

Используйте `ss` для идентификации утечек сокетов:
```bash
ss -tpn | grep <PID> | awk '{print $1}' | sort | uniq -c
# → 950 CLOSE_WAIT
# → 50  ESTABLISHED
```
*Интерпретация:* Обилие `CLOSE_WAIT` — признак того, что приложение не закрывает свою сторону соединения.

### См. также

- [**Диагностика «too many open files»**](./troubleshooting_too_many_open_files.md)
- [**Файловые дескрипторы**](../../FileSystems/file_descriptors.md)
- [**Утилита lsof**](../Processes/lsof.md)
- [**Трассировка и отладка**](./tracing_and_debugging.md)
- [**Концепции лимитов ресурсов**](../../Core/processes/resource_limits_concepts.md)
- [**Управление ulimit и prlimit**](../../Core/processes/ulimit_usage.md)
- [**Постоянная настройка лимитов**](../../Core/processes/persistent_limits_configuration.md)
- [**Отладка процессов: утечки памяти и зомби**](../../Core/processes/Troubleshooting/debugging.md)
- [**Межпроцессное взаимодействие (IPC)**](../../Core/processes/ipc.md)
- [**Практические сценарии мониторинга процессов**](../../Core/processes/practical_scenarios.md)
