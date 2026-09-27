# Сравнение инструментов диагностики дискового ввода-вывода (I/O)

В данном разделе представлена классификация и сравнительный анализ утилит для мониторинга и отладки дисковой подсистемы Linux — от базовых системных счетчиков до глубокой трассировки на уровне ядра и аппаратных прерываний.

## Определения

- **Уровни диагностики**: Иерархический подход к поиску проблем, начинающийся с системного давления (PSI) и заканчивающийся детальным анализом конкретных блоков данных и прерываний контроллера.
- **Блочный ввод-вывод (Block I/O)**: Операции на уровне блочного устройства (диска или раздела), абстрагированные от файловой системы.
- **Трассировка (Tracing)**: Метод анализа, позволяющий фиксировать каждое событие (запрос I/O) с высокой точностью временных меток и контекстом выполнения.
- **PSI (Pressure Stall Information)**: Механизм ядра Linux (4.20+) для измерения времени, которое процессы провели в ожидании I/O. Даёт объективную картину «голодания» системы, даже если `%iowait` низок.
- **`await` (Average Wait)**: Среднее время (в мс) от создания запроса до его завершения, включая время в очереди. Формула: `(Δ Field_7 + Δ Field_11) / (Δ Field_4 + Δ Field_8)` из `/proc/diskstats`.
- **`avgqu-sz` / `aqu-sz` (Average Queue Size)**: Средняя длина очереди запросов к устройству. Рассчитывается из Weighted I/O time (поле 14). Для HDD порог — >2, для SSD/NVMe — >4–8.
- **`r_await` / `w_await`**: Задержка отдельно для чтения и записи. Асимметрия (`w_await` >> `r_await`) указывает на проблему с записью (writeback, журналирование).
- **`f_await` (Flush Await)**: Среднее время выполнения операций сброса кэша (flush). В ядрах 5.5+ данные берутся из полей 19–20 `/proc/diskstats`. Критично для баз данных.
- **`%util`**: Процент времени, когда устройство обрабатывало запросы. На NVMe 100% не означает насыщение из-за параллельной обработки.
- **`svctm` (Service Time)**: **Устаревший показатель (DEPRECATED)**. В архитектуре blk-mq математически невозможно рассчитать корректно. Игнорировать.
- **blk-mq (Multi-Queue Block I/O)**: Современная многоочередная архитектура стека I/O ядра Linux. Критична для NVMe (64+ аппаратных очередей). Устраняет SPoF в планировщике.
- **io_uring**: Интерфейс асинхронного I/O (ядро 5.1+), работающий через shared ring buffer. Обходит классические `read`/`write`, поэтому не виден в `iotop` и `pidstat`.
- **D-state (Uninterruptible Sleep)**: Состояние процесса, заблокированного в ожидании I/O. Не реагирует на `SIGKILL`, напрямую увеличивает Load Average.
- **taskstats**: Интерфейс ядра Linux (через Netlink), предоставляющий статистику задержек и I/O для каждой задачи. Основа для `iotop` и `pidstat`.
- **TASK_DELAY_ACCT**: Опция ядра (`CONFIG_TASK_DELAY_ACCT`), необходимая для сбора статистики задержек задач. Без неё `iotop` показывает нули.
- **CONFIG_BPF / CONFIG_BPF_SYSCALL**: Опции ядра (4.9+), требуемые для `bpftrace` и BCC-утилит.
- **CONFIG_PSI**: Опция ядра (4.20+), требуемая дляPressure Stall Information.

## Основные концепции

### Классификация по уровням анализа

| Уровень | Инструменты | Что позволяют увидеть |
| :--- | :--- | :--- |
| **Система (PSI)** | `cat /proc/pressure/io`, `vmstat` | Общее влияние нехватки I/O на задержки приложений. |
| **Устройство** | `iostat`, `/proc/diskstats`, `sar -d` | Утилизация физических дисков, задержки (`await`, `aqu-sz`), очереди. |
| **Контейнер** | `systemd-cgtop`, `io.stat` (cgroup v2), `io.max` | Изоляция нагрузки и эффекты лимитирования (Throttling). |
| **Процесс** | `iotop`, `pidstat -d`, `/proc/<pid>/io` | Распределение нагрузки (чтение/запись) между PID. |
| **Файловая система** | `fatrace`, `lsof`, `strace`, `opensnoop` | Конкретные файлы и системные вызовы (`read`/`write`, `openat`). |
| **Блочный уровень** | `blktrace`, `biolatency`, `biosnoop` | Жизненный цикл запроса: от очереди до подтверждения контроллером. |
| **Ядро (Events)** | `perf`, `bpftrace` | Активность `io_uring`, внутренние блокировки ФС, прерывания. |

### Почему классические метрики вводят в заблуждение

Традиционные инструменты (`top`, `iostat`, `vmstat`) создавались для эпохи HDD и single-queue. На современных системах (NVMe, blk-mq, io_uring) они часто дают ложную картину:

- **`%util` на NVMe**: Значение 100% не означает насыщения. NVMe обрабатывает тысячи запросов параллельно. Ориентируйтесь на `aqu-sz` (глубина очереди) и P99 latency.
- **`svctm`**: Полностью устарел. В архитектуре blk-mq невозможно корректно рассчитать среднее время обслуживания без учета параллелизма.
- **Средний `await`**: Прячет «хвосты» задержек. 99% быстрых запросов могут скрыть 1% критически медленных. Используйте гистограммы (`biolatency`).
- **`iowait` на многоядерных системах**: `%wa` в `top`/`vmstat` — агрегированное значение по всем CPU. На 32-ядерном сервере один диск может обслуживать очередь, пока 31 ядер простаивают. PSI даёт точную картину.
- **`iotop` и `io_uring`**: Интерфейс `io_uring` обходит классические `read`/`write`, на которых базируется `taskstats`. `iotop` и `pidstat` не видят такую нагрузку.
- **Writeback masking**: Физический сброс выполняют `kworker`, а не исходный процесс. `iotop` показывает `kworker`, а не приложение-писатель.

### cgroups v2 I/O controller

В системах с systemd и контейнерами контроллер `io` (cgroups v2) предоставляет метрики, дополняющие `iostat`:

- **`io.stat`**: Кумулятивная статистика (`rbytes`, `wbytes`, `rios`, `wios`, `dbytes`, `dios`) для каждого cgroup. Позволяет увидеть, какой slice/контейнер генерирует нагрузку.
- **`io.max`**: Жесткие лимиты (BPS/IOPS) могут ограничивать устройства ниже физического потенциала. Если `await` высокий, а `%util` низкий — проверьте `io.max` в соответствующем cgroup.
- **Делегирование**: Для корректной работы `io.stat` внутри контейнера родительский slice/systemd должен иметь `Delegate=yes`.

### Сравнительные характеристики утилит

| Инструмент | Уровень | Преимущества | Ограничения |
| :--- | :--- | :--- | :--- |
| **`PSI`** | Система | Самый точный индикатор влияния I/O на задержки. | Требует ядро 4.20+, не показывает источник. |
| **`iostat`** | Устройство | Золотой стандарт для анализа латентности железа. | Не привязывает нагрузку к конкретным процессам. |
| **`iotop`** | Процесс | Интерактивный поиск виновника в реальном времени. | Пропускает всплески < 1с, не видит `io_uring`. |
| **`pidstat -d`** | Процесс | Точная интервальная статистика для скриптов. | Не отображает ядерные потоки (`writeback`). |
| **`biolatency`** | Блок | Визуализирует Tail Latency через гистограммы. | Требует eBPF, дает накладные расходы при High I/O. |
| **`blktrace`** | Блок | Максимальная детализация (каждый сектор). | Создает огромные логи, требует глубоких знаний. |
| **`fatrace`** | Файл | Видны все обращения к ФС по всей системе. | Не показывает объем переданных данных (байты). |
| **`syswatch`** | Сводный | Наглядный TUI, автоматический анализ аномалий. | Требует установки, не подходит для автоматизации. |

## Предварительные требования

### Аппаратные требования

- Доступ к целевому блочному устройству (`/dev/sdX`, `/dev/nvmeXnY`).
- Для eBPF-инструментов (`bpftrace`, `bcc-tools`) требуется ядро 4.9+ с включенными `CONFIG_BPF` и `CONFIG_BPF_SYSCALL`.
- Для PSI требуется ядро 4.20+ с включенным `CONFIG_PSI`.
- Для TASK_DELAY_ACCT требуется `CONFIG_TASK_DELAY_ACCT=y` (нужна для `iotop`, `pidstat`).

### Программные требования

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y sysstat iotop bpfcc-tools bpftrace perf-tools-unstable smartmontools nvme-cli fatrace pidstat procps

# RHEL/CentOS/Fedora
sudo dnf install -y sysstat iotop bcc-tools bpftrace perf smartmontools nvme-cli fatrace pidstat procps-ng

# Arch Linux
sudo pacman -S sysstat iotop bpftrace bcc-tools fatrace smartmontools nvme-cli procps

# openSUSE/SLES
sudo zypper install -y sysstat iotop bpftrace bcc-tools fatrace smartmontools nvme-cli procps
```

### Проверка конфигурации ядра

```bash
# Статистика задержек задач (нужна для iotop, pidstat)
grep TASK_DELAY_ACCT /boot/config-$(uname -r)
# → CONFIG_TASK_DELAY_ACCT=y

# PSI (нужна для cat /proc/pressure/io)
grep PSI /boot/config-$(uname -r)
# → CONFIG_PSI=y

# eBPF (нужна для biolatency, biosnoop, bpftrace)
grep BPF /boot/config-$(uname -r)
# → CONFIG_BPF=y, CONFIG_BPF_SYSCALL=y
```

### Включение сбора данных

```bash
# Включение TASK_DELAY_ACCT на лету (если не включена в ядре)
echo 1 > /proc/sys/kernel/task_delayacct

# Проверка версий ключевых инструментов
iostat -V
iotop --version
bpftrace -V
```

## Практические сценарии

### Выбор инструмента в зависимости от глубины проблемы

#### 1. Первичная оценка (Есть ли проблема?)

Если приложения «тормозят», проверьте PSI. Это самый быстрый способ подтвердить, что проблема в I/O, а не в CPU или памяти.

```bash
cat /proc/pressure/io
# → some avg10=12.50 avg60=8.30 avg300=5.20 total=12345678
```

**Интерпретация:**
- `some avg10 > 5–10%`: I/O является бутылочным горлышком.
- `full avg10 > 5%`: Все процессы в системе страдают от нехватки I/O.
- `total`: Кумулятивное время с момента загрузки (мс).

**Ожидаемый результат:** Подтверждено или опровергнуто влияние I/O на задержки. Валидация: если `some avg10` высокий, переходите к локализации устройства.

#### 2. Локализация устройства (Где тормозит?)

Если PSI высок, найдите диск с аномальным временем ожидания (`await`) и глубиной очереди (`aqu-sz`).

```bash
iostat -xz 1
# → Device  await  aqu-sz  %util
# → sda     45.20   3.50    85.00
# → nvme0n1  0.80   0.40    12.00
```

**Интерпретация:**
- `await > 20ms` для HDD или `> 1ms` для SSD/NVMe — аномалия.
- `aqu-sz > 2` для HDD или `> 4–8` для NVMe — очередь растет быстрее, чем диск обрабатывает запросы.
- `%util` на NVMe не является надежным индикатором насыщения.

**Ожидаемый результат:** Определено устройство (`sda`, `nvme0n1`, `dm-1`) с аномальными метриками. Валидация: `await` стабильно выше порога на протяжении 3+ измерений.

#### 3. Идентификация приложения (Кто виноват?)

Если диск перегружен, найдите процесс-виновника.

```bash
# Интерактивный режим: только процессы, совершающие I/O
sudo iotop -o

# Кумулятивный режим: накопленный объем с момента запуска
sudo iotop -a

# Группировка потоков (threads) в одну строку процесса
sudo iotop -P -o

# Для скриптов и исторических данных
pidstat -d 1
# → PID    kB_rd/s  kB_wr/s  iodelay  Command
# → 1234   10240    20480    15000    postgres
```

**Ожидаемый результат:** Идентифицирован PID процесса с наибольшим `DISK WRITE`/`DISK READ`. Валидация: `pidstat -d` показывает тот же PID, что и `iotop`.

**Важные нюансы:**
- `iotop` может показывать `kworker` вместо реального процесса из-за writeback. Для атрибуции используйте `bpftrace` на `writeback_dirty_page`.
- `pidstat -d` не учитывает `io_uring` и writeback ядра.
- Для быстрого анализа без установки утилит: `cat /proc/<PID>/io`.

#### 4. Поиск скрытых задержек (Почему тормозит?)

Если средние значения в норме, но есть жалобы на фризы, используйте eBPF для поиска выбросов (Tail Latency).

```bash
# Гистограмма задержек выполнения I/O (Essential)
sudo biolatency-bpfcc -D 1 10
# → Ищите значения в корзинах > 100–128ms (хвост распределения).

# Трассировка каждого запроса в реальном времени (видит io_uring)
sudo biosnoop-bpfcc | awk '$NF > 100'
# → Запросы с задержкой > 100 мс: COMM, PID, LAT(ms), DISK.

# Альтернатива через perf (если BCC/bpftrace недоступны)
sudo perf record -e 'block:block_rq_issue' -a sleep 5
sudo perf report --sort comm,pid
```

**Ожидаемый результат:** Выявлены P95/P99 выбросы задержек (`biolatency`) или конкретные запросы > 100 мс (`biosnoop`). Валидация: после устранения contention tail latency падает до P99 < 10 ms.

#### 5. Анализ современной асинхронности (io_uring)

Для баз данных нового поколения (PostgreSQL 16+, ScyllaDB, RocksDB) используйте `perf`/`bpftrace`, так как `iotop` и `pidstat` могут их не видеть.

```bash
# Проверка, использует ли процесс io_uring
ls -la /proc/<PID>/fd/ | grep anon_inode:io_uring
# → если вывод не пуст — процесс использует io_uring

# Трассировка отправки запросов io_uring через bpftrace
sudo bpftrace -e 'tracepoint:io_uring:io_uring_submit_sqe { @[comm] = count(); }'
# → [postgres]: 45231
# → [mysqld]: 28914

# Блочный уровень (видит io_uring независимо от интерфейса)
sudo biolatency-bpfcc -D 1 10
sudo biosnoop-bpfcc | head -n 20

# Альтернатива через perf
sudo perf record -e 'block:block_rq_issue' -a sleep 5
sudo perf report --sort comm,pid
```

**Ожидаемый результат:** Подтверждено использование io_uring, идентифицирован PID-виновник. Валидация: `biosnoop-bpfcc` показывает активность, невидимую в `iotop`/`pidstat`.

#### 6. Анализ файловой активности (Когда диск простаивает)

Если `iostat` показывает низкий `%util`, но приложения виснут, проблема может быть в файловой системе (массовые `openat`, поиск несуществующих файлов).

```bash
# Трассировка открытия файлов
sudo opensnoop
# → PID     COMM        FD  ERR  PATH
# → 4217    app         12   0   /etc/app/config.json
# → 4217    app         -1   2   /etc/app/cache.db

# Трассировка через bpftrace (агрегация)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { @[comm] = count(); }'
# → [app]: 45000
# → [nginx]: 12000

# Мониторинг обращений к ФС по всей системе
sudo fatrace -t | head -n 20
```

**Ожидаемый результат:** Выявлен процесс с тысячами `openat` в секунду. Валидация: `opensnoop` показывает > 1000 событий/с от одного PID.

#### 7. Анализ распределения задержек (Tail Latency и contention)

Когда средние значения выглядят нормально, но есть «микро-фризы», анализируйте распределение задержек и блокировки ядра.

```bash
# 1. Гистограмма задержек (Tail Latency)
sudo biolatency-bpfcc -D 1 10
# → Ищите корзины > 100ms.

# 2. Время вне CPU (offcputime) — где процесс проводит время в ожидании
sudo offcputime-bpfcc -p <PID> 5

# 3. Анализ блокировок ядра (Lock Contention)
sudo perf lock record -p <PID> -- sleep 10
sudo perf lock report
# → Ищите lock с высоким Wait time.

# 4. Процессы в D-state и их причины
ps -eo pid,state,wchan:30,comm | grep " D "
# → 9012 D ext4_inode_lock my_app

# 5. Трассировка writeback источников
sudo bpftrace -e 'tracepoint:writeback:writeback_dirty_page { @[comm] = count(); }'
# → [postgres]: 12500
# → [python3]: 4500
```

**Ожидаемый результат:** Выявлены блокировки с высоким `Wait time` или процессы, ожидающие `inode_lock`. Валидация: после устранения contention tail latency падает до P99 < 10 ms.

## Валидация диагноза

Перед применением исправлений подтвердите причину деградации:

1. **Корреляция PSI и iostat**: Высокий `await` должен совпадать с ростом `some avg10` в `/proc/pressure/io`. Если PSI низкий, а `await` высокий — проверяйте внешний троттлинг (hypervisor, SAN) или инструментальные погрешности.
2. **Изоляция контейнера**: В cgroups v2 проверьте `io.stat` и `io.max` для suspicious slice. Высокий `await` при низком `%util` часто указывает на `io.max` limit.
3. **Атрибуция writeback**: Если `iotop` показывает `kworker`, подтвердите через `biosnoop-bpfcc` или `bpftrace` на `writeback_dirty_page`, что источник — приложение-писатель.
4. **io_uring masking**: Если `iotop`/`pidstat` молчат, а нагрузка есть — подтвердите через `bpftrace` на `io_uring_submit_sqe` или `biosnoop-bpfcc`.
5. **Аппаратные ошибки**: Проверьте `dmesg`, `smartctl`, `nvme smart-log` перед изменением конфигурации ПО.

## Автоматизация и мониторинг

### Сбор данных для исторического анализа

```bash
# Сбор disk-метрик каждые 5 секунд в течение 1 часа
sar -d 5 720 > /tmp/disk_metrics.log

# Парсинг iostat в JSON (sysstat 12+)
iostat -o JSON -xz 1 10 > /tmp/iostat.json

# Пример Python-парсинга для аномалий
python3 -c "
import json, sys
with open('/tmp/iostat.json') as f:
    data = json.load(f)
for entry in data['sysstat']['hosts'][0]['statistics']['disk']:
    dev = entry['disk_device']
    await = float(entry['await'])
    aqu_sz = float(entry['aqu-sz'])
    if await > 20 or aqu_sz > 2:
        print(f'ALERT: {dev} await={await}ms aqu-sz={aqu_sz}')
"
```

### Prometheus alerts (node_exporter)

```yaml
groups:
  - name: disk_io_alerts
    rules:
      - alert: HighDiskLatency
        expr: node_disk_io_time_weighted_seconds_total / node_disk_io_time_seconds_total > 0.02
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High disk latency on {{ $labels.device }}"
          description: "await > 20ms for 5 minutes"

      - alert: DiskQueueDepth
        expr: node_disk_read_time_seconds_total + node_disk_write_time_seconds_total > 2
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Deep queue on {{ $labels.device }}"
```

## Ограничения и особые случаи

### Многоядерные системы

- `%iowait` в `top`/`vmstat` — агрегированное значение. На 32-ядерном сервере один диск может быть перегружен, пока `%wa` показывает 2%. Используйте `mpstat -P ALL 1` для per-CPU анализа или PSI.
- `iostat` без флага `-x` не показывает отдельные диски. Всегда используйте `iostat -xz`.

### Виртуализация

- **`%steal`**: В `iostat` показывает время, «украденное» у гостевой ВМ гипервизором. Постоянный `%steal > 5%` — признак overselling CPU на хосте или noisy neighbor.
- Внешний троттлинг (SAN, hypervisor) может вызывать высокий `await` при низком `%util`. Проверяйте через `dmesg`, `smartctl`, метрики гипервизора.
- В Docker `iotop` может не видеть данные без `--privileged` или доступа к `/proc` хоста и Netlink.

### cgroups v1 vs v2

- **cgroups v1**: Нет единого `io.stat`. Нужно проверять `blkio.*` в каждом контроллере отдельно (`blkio.throttle.io_service_bytes`).
- **cgroups v2**: Единый `io.stat`, `io.max`, `io.weight`. Надежнее для диагностики ограничений в контейнерах.

### NFS и FUSE

- Задержки на уровне сети или FUSE-пользовательского пространства не видны в `await` на стороне клиента. Используйте `nfsstat -m`, `mountstats`, `bpftrace` на `vfs_read`/`vfs_write`.
- `fatrace` работает на уровне VFS и видит NFS-операции, но не отличает сетевые задержки от локальных.

### 32-битные системы

- Формат `/proc/<pid>/io` совметим, но некоторые eBPF-утилиты (`biolatency`, `biosnoop`) требуют перекомпиляции под 32-битную архитектуру.
- `iostat` работает корректно, но версия `sysstat` в старых дистрибутивах может не поддерживать `aqu-sz` (показывает `avgqu-sz`).

### SSD/NVMe особенности

- **Write Amplification**: Внутренний Garbage Collection может вызывать всплески задержки (up to 100+ ms) при фоновой перезаписи. Видно в `biolatency` как длинный «хвост» гистограммы.
- **SLC-кэш**: При переходе из SLC-кэша в TLC/QLC латентность может расти в 5–10 раз. Проверяйте через `nvme smart-log` (`percentage_used`, `available_spare`).
- **PLP (Power Loss Protection)**: Отсутствие PLP приводит к задержкам на сброс внутреннего кэша при `fsync`. Видно по росту `f_await`.

### RAID и dm-crypt

- **RAID**: `await` на уровне `dm-0` (LVM/RAID) может быть выше, чем на физических дисках из-за чередования. Анализируйте `iostat` на физические устройства (`sda`, `sdb`) и на mapper (`dm-0`) параллельно.
- **dm-crypt**: Шифрование добавляет 5–15% overhead на CPU. При росте `await` проверяйте `mpstat -P ALL 1` — если `%sys` высокий, возможно, не хватает CPU для шифрования.
- **RAID ребилд**: Во время ребилда скорость массива падает. Можно временно снизить `speed_limit_max`:
  ```bash
  echo 50000 > /proc/sys/dev/raid/speed_limit_max
  ```

## См. также

- [Диагностический чеклист ввода-вывода](./diagnostic_checklist.md) — пошаговый алгоритм применения этих инструментов.
- [Невидимый I/O](./invisible_io.md) — почему стандартные инструменты могут не видеть нагрузку.
- [iostat — детальный разбор метрик](../../Filesystem/iostat.md) — теория и практика основного инструмента анализа устройств.
