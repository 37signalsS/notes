# Быстрая диагностика сервера (Rapid Assessment)

## Определения

**Rapid Assessment (Первичная диагностика, экспресс-диагностика)** — методология структурированного экспресс-анализа состояния Linux-сервера, занимающая от 30 до 60 секунд. Цель — не детальное решение проблемы, а быстрая локализация «бутылочного горлышка» (CPU, Memory, I/O, Network) и фильтрация ложных гипотез для принятия решения о дальнейших действиях.

**Метод USE (Utilization, Saturation, Errors)** — концептуальная основа диагностики, предложенная Брендоном Греггом, фокусирующаяся на трёх метриках для каждого ресурса: утилизации (Utilization — процент времени занятости), насыщении (Saturation — очередь/дефицит) и ошибках (Errors — аппаратные/программные сбои).

**Load Average (LA, средняя нагрузка)** — экспоненциально взвешенное среднее количество процессов в очереди на выполнение или в состоянии несмотря на I/O. Показывает нагрузку за 1, 5 и 15 минут.

**I/O Wait (iowait)** — доля времени, когда CPU простаивал в ожидании завершения операций ввода-вывода. Высокий `iowait` указывает на проблемы с подсистемой хранения, а не на перегрузку процессора.

**Контекстные переключения (context switches, `cs`)** — переключения ядра между процессами/потоками. Высокий `cs` (>100k на ядро) часто указывает на избыточное количество потоков или интенсивный preempt.

## Предварительные требования

### Требования к окружению

| Компонент | Требование |
| :--- | :--- |
| ОС | Linux с установленными утилитами `procps` (`ps`, `top`, `free`, `vmstat`), `sysstat` (`sar`, `iostat`, `mpstat`, `pidstat`), `util-linux` (`dmesg`) |
| Права | `root` или пользователь с доступом к `/proc`, `/var/log/dmesg`, `/var/log/syslog`/`journalctl` |
| Ядро | 3.x+ (для `pidstat -G` и расширенных метрик cgroup) |
| Архитектура | x86_64, aarch64, armv7l — команды универсальны, вывод может отличаться |

### Проверка начального состояния

```bash
# Проверка доступности основных утилит
command -v vmstat && command -v iostat && command -v pidstat && command -v sar && command -v dmesg
# → /usr/bin/vmstat /usr/bin/iostat /usr/bin/pidstat /usr/bin/sar /usr/bin/dmesg

# Проверка версии sysstat (для iostat -xz)
iostat -V | head -1
# → sysstat version 12.5.4

# Проверка доступа к ядерному логу
dmesg -T > /dev/null && echo "dmesg доступен"
# → dmesg доступен
```

## Базовые концепции

### Механизм проблемы

Rapid Assessment строится на принципе последовательного сужения: от общей картины системы к конкретному ресурсу, затем к конкретному процессу. Каждая команда отвечает на чёткий вопрос и имеет заранее определённые «Red Flags» — пороговые значения, при превышении которых требуется углублённая диагностика.

Методология USE применяется на уровне каждого ресурса:
- **CPU:** Utilization (`%idle`, `%iowait`), Saturation (`r` в `vmstat`, `load average`), Errors (`mce`, NMI)
- **Memory:** Utilization (`available`, `commit`), Saturation (`si`/`so`, OOM), Errors (`edac`, `badram`)
- **Disk I/O:** Utilization (`%util`), Saturation (`await`, очередь), Errors (`EIO`, `soft lockup`)
- **Network:** Utilization (`rxkB/s` vs bandwidth), Saturation (`retrans/s`, `drops`), Errors (`FIFO`, `frame`)

### Жизненный цикл инцидента

| Фаза | Действие | Инструменты |
| :--- | :--- | :--- |
| 1. Сбор симптомов | Определить время начала, область влияния, симптомы | `uptime`, `who`, `last` |
| 2. Локализация ресурса | Определить, какой ресурс исчерпан | `vmstat 1 5`, `iostat -xz 1`, `sar -n DEV 1` |
| 3. Идентификация процесса | Найти конкретный PID, ответственный за деградацию | `pidstat 1 5`, `top`, `htop` |
| 4. Проверка ядра | Исключить аппаратные сбои или ошибки драйверов | `dmesg -T`, `journalctl -k` |
| 5. Документирование | Зафиксировать метрики для post-mortem | `sar -A`, `vmstat 1 60 > /tmp/vmstat.log` |

### Ключевые принципы восстановления

1. **30–60 секунд:** Первый раунд диагностики не должен превышать 60 секунд. Если ресурс не идентифицирован — перезапустите сбор с акцентом на другой домен.
2. **Сравнение с базой:** Все метрики сравниваются с типичными значениями для данной инфраструктуры, а не с абсолютными порогами.
3. **Один ресурс за раз:** Не пытайтесь диагностировать CPU, память, диск и сеть одновременно. Определите приоритетный ресурс по Load Average и `vmstat`.
4. **Валидация после действия:** Любое вмешательство (kill, renice, echo 3 > /proc/sys/vm/drop_caches) требует повторного замера метрик.

## Практические сценарии

### Сценарий 1: Анализ общей нагрузки (`uptime`)

```bash
uptime
# → 18:30:05 up 10 days, 2:15, 3 users, load average: 15.05, 10.10, 5.02
```

**Интерпретация:** Load Average — среднее число процессов в очереди (running + uninterruptible). Значение 15 на 8-ядерном сервере означает перегрузку CPU. Три значения показывают тренд: рост за 1 мин при падении за 15 мин может указывать на пиковую вспышку.

**Валидация:**
```bash
# Подсчёт количества ядер
nproc
# → 8

# Сравнение LA/cores
echo "scale=2; 15.05 / 8" | bc
# → 1.88 (LA в 1.88 раза выше числа ядер — перегрузка)

# Проверка тренда через /proc/loadavg
cat /proc/loadavg
# → 15.05 10.10 5.02 2/456 12345
```
*Подробнее:* [Планирование процессов и LA](../../Core/processes/scheduling.md).

### Сценарий 2: Ошибки ядра и оборудования (`dmesg`)

```bash
dmesg -T | tail -n 50
# → [Sun Aug  9 18:30:00 2026] Out of memory: Kill process 1234 (mysqld)
# → [Sun Aug  9 18:29:55 2026] TCP: request_sock_TCP: Possible SYN flooding
# → [Sun Aug  9 18:29:50 2026] sd 0:0:0:0: [sda] tag#12 FAILED
```

**Интерпретация:** Флаг `-T` добавляет читаемое время. Ищите:
- `Out of memory` — OOM-killer сработал, требуется увеличение RAM или поиск утечек
- `TCP` — потери пакетов, возможно DDoS или нехватка backlog
- `sd.*FAILED` — аппаратные ошибки диска (кабель, контроллер, сам диск)

**Валидация:**
```bash
# Подсчёт OOM-инцидентов за последний час
journalctl -k --since "1 hour ago" | grep -c "Out of memory"
# → 3

# Проверка наличия MCE (Machine Check Exception)
grep -c "MCE" /var/log/mcelog 2>/dev/null || dmesg | grep -c "MCE"
# → 0
```

### Сценарий 3: Контекст, своп и I/O wait (`vmstat`)

```bash
vmstat 1 5
# → r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
# → 5  0      0   100M    50M  2500M    0    0     0   500  100  500 80 15  5  0  0
# → 8  0      0   120M    50M  2500M    0    0     0   200  120  600 85 10  5  0  0
```

**Интерпретация:**
- `r` (runnable): Очередь на выполнение. Если `r > кол-во_ядер` — CPU перегружен.
- `si`/`so` (swap in/out): `> 0` означает свопинг. Постоянные `si`/`so` — критично для производительности.
- `wa` (I/O wait): Доля времени в ожидании I/O. `wa > 10%` указывает на деградацию диска.
- `cs` (context switches): `> 100k` на ядро — возможен thrashing потоков.

**Валидация:**
```bash
# Количество ядер для сравнения с r
nproc
# → 4

# Первая строка содержит средние с boot — игнорировать
vmstat 1 3 | tail -n +4
# Используйте только строки 4+ для текущего состояния
```

### Сценарий 4: Дисковая подсистема (`iostat`)

```bash
iostat -xz 1 5
# → Device:  rrqm/s  wrqm/s  r/s  w/s  rkB/s  wkB/s  await  aqu-sz  %util
# → sda        0.00    5.00  100  500   4000  20000  35.00   2.50  95.00
# → nvme0n1    0.00    0.00    0    0      0      0   0.00   0.00   0.00
```

**Интерпретация:**
- `%util`: Время занятости диска. `> 80%` — перегрузка.
- `await`: Среднее время запроса (включая очередь). `> 20ms` — деградация; для NVMe ожидается `< 0.5ms`.
- `aqu-sz`: Средний размер очереди. `> 2` на шпинделе HDD указывает на перегрузку.
- `r/s`, `w/s`: IOPS. Сравните с лимитами диска/controller.

**Валидация:**
```bash
# Проверка типа устройства (NVMe vs SATA SSD vs HDD)
lsblk -d -o NAME,TYPE,MODEL,TRAN | grep -E "disk|nvme"
# → NAME   TYPE MODEL            TRAN
# → sda    disk Samsung SSD 870  sata
# → nvme0n1 disk Samsung SSD 980 nvme
```

### Сценарий 5: Сетевая активность (`sar`)

```bash
sar -n DEV 1
# → IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s
# → eth0    10000.0   12000.0   15000.0   20000.0
# → lo       500.0     500.0      50.0      50.0

sar -n TCP,ETCP 1
# → TCPv4: retrans/s 10.50
# → TCPv4: inerr/s 0.00
```

**Интерпретация:**
- Сравните `rxkB/s`/`txkB/s` с пропускной способностью интерфейса (`ethtool eth0`).
- `retrans/s > 1%` от `txkB/s` — потеря пакетов, проблема на L2/L3.
- `inerr/s > 0` — ошибки приёма (CRC, duplex mismatch).

**Валидация:**
```bash
# Проверка скорости интерфейса
ethtool eth0 | grep -E "Speed|Duplex"
# → Speed: 10000Mb/s
# → Duplex: Full

# Проверка ошибок на интерфейсе
ip -s link show eth0 | grep -A1 "RX\|TX"
# → RX: bytes packets errors dropped 0 overrun 0 mpu 0
# → TX: bytes packets errors dropped 0 overrun 0 carrier 0
```

### Сценарий 6: Память (`free`)

```bash
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           15Gi       12Gi       1.0Gi       256Mi       2.0Gi       2.5Gi
# → Swap:         2.0Gi       1.5Gi       512Mi
```

**Интерпретация:**
- `available`: Реальная память, доступная для запуска новых приложений. `< 10%` от `total` — критично.
- `buff/cache`: Используется ядром для кэширования. Это не утечка, но при отсутствии `available` система начнёт свопить или убивать процессы.
- `swap used > 0` при свободном `available > 0` — обычно нормально (вмятины страниц).

**Валидация:**
```bash
# Проверка давления на память (PSI)
cat /proc/pressure/memory
# → some avg10=0.50 avg60=0.20 avg300=0.10 total=12345
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0

# Проверка, есть ли активный OOM
dmesg -T | grep -i "out of memory" | tail -3
# → (пустой вывод при отсутствии OOM)
```

### Сценарий 7: CPU по ядрам (`mpstat`)

```bash
mpstat -P ALL 1 5
# → 18:30:05     CPU    %usr   %nice    %sys %iowait    %irq   %soft  %steal  %guest  %gnice   %idle
# → 18:30:05     all    5.00    0.00    2.00    0.00    0.00    0.00    0.00    0.00    0.00   93.00
# → 18:30:05       0   95.00    0.00    4.00    0.00    0.00    1.00    0.00    0.00    0.00    0.00
```

**Интерпретация:**
- `%usr` + `%sys` на одном ядре `> 90%` при низком общем CPU — перекос на одно ядро (single-threaded bottleneck или softirq).
- `%iowait` на одном ядре `> 20%` — дисковая операция привязана к конкретному CPU (например, ksoftirqd).
- `%soft`: Высокий `%soft` (>10%) — большой объём сетевых прерываний (rx/tx softirq).

**Валидация:**
```bash
# Проверка привязки прерываний к ядрам
grep -E "smp_affinity|irq" /proc/interrupts | head -10
# →  LOC:   123456   0   0   0   IO-APIC   2-edge    timer
# →  SPU:   987654   0   0   0   IO-APIC   16-edge   eth0-rx-0
```

### Сценарий 8: Общий вид (`top` / `htop`)

```bash
top -b -n 1 | head -20
# → top - 18:30:05 up 10 days,  2:15,  3 users,  load average: 15.05, 10.10, 5.02
# → Tasks: 456 total,   2 running, 454 sleeping,   0 stopped,   0 zombie
# → %Cpu(s):  5.0 us,  2.0 sy,  0.0 ni, 93.0 id,  0.0 wa,  0.0 hi,  0.0 si,  0.0 st
# → MiB Mem: 15360.0 total, 1024.0 free, 12288.0 used,  2048.0 buff/cache
# → MiB Swap: 2048.0 total,    512.0 free,  1536.0 used
# →    PID USER      PR  NI    VIRT    RES    %CPU  %MEM     TIME+  Command
# →  1234 root      20   0  5000M  1500M   95.0  9.5   10:20.45  python3 app.py
```

**Интерпретация:**
- `Tasks`: Зомби-процессы (`Z`) — проблемы с родительским процессом. Состояние `D` (uninterruptible) — ожидание I/O.
- `%CPU > 100%` на процесс: использует несколько потоков/ядер.
- `RES`: Физическая память процесса. Сравните с `available`.

**Валидация:**
```bash
# Проверка состояния конкретного PID
ps -p 1234 -o pid,stat,pcpu,pmem,rss,vsz,comm
# →   PID STAT %CPU %MEM   RSS    VSZ COMMAND
# →  1234 S+   95.0  9.5 1536M 5000M python3

# Проверка зомби-процессов
ps aux | grep -c 'Z'
# → 0
```

### Сценарий 9: Диагностика за 30 секунд (`htop` + `mpstat` + `iotop` + `nethogs` + `ss`)

Собранная последовательность для быстрого определения источника подтормаживания CPU, диска, сети или соединений. Заменяет классический набор `top` + `netstat` на более информативный.

```bash
# Шаг 1: Общая нагрузка и число ядер
uptime
nproc

# Шаг 2: Визуальная оценка CPU/памяти
htop

# Шаг 3: Перекос по ядрам и steal time (виртуалки)
mpstat -P ALL 1 3

# Шаг 4: Дисковые виновники (только запись/чтение)
sudo iotop -oP

# Шаг 5: Сетевые виновники по процессам
sudo nethogs

# Шаг 6: Общая сводка по сокетам
ss -s

# Шаг 7: Количество установленных TCP-соединений
ss -Htn state established | wc -l
```

**Интерпретация:**
- `uptime` + `nproc` — сравнение LA с числом ядер.
- `htop` — цветные шкалы: «зелёный потолок» = виноваты процессы, «серый» = steal и вопросы к хостеру.
- `mpstat -P ALL` — на виртуалке отдельно проверяйте `%steal`; если гипервизор регулярно забирает >5%, проблема за пределами ВМ.
- `iotop -oP` — показывает только процессы, которые прямо сейчас читают или пишут (флаги `-oP` запомните наизусть).
- `nethogs` — показывает потребление трафика по процессам, а не по соединениям.
- `ss -s` — сводка по всем сокетам (established, time-wait, orphaned).
- `ss -Htn state established | wc -l` — количество установленных TCP-соединений; флаг `-H` нужен, чтобы `wc -l` не посчитал строку заголовка.

**Валидация:**
```bash
# Установка инструментов (Debian/Ubuntu)
sudo apt install htop iotop nethogs sysstat bpfcc-tools

# RHEL/Fedora
sudo dnf install htop iotop nethogs sysstat bcc-tools
```

## Устранение неполадок

### Типичные ошибки и их решения

| Ошибка / Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `vmstat`: первый запуск показывает аномалии | Первая строка — средние с boot, не текущие | Запустить `vmstat 1 3`, использовать строки 4+ | Игнорировать первую строку |
| `iostat`: нет вывода по `%util` | Установлен старый `sysstat` (< 10) | `iostat -V` | Обновить `sysstat` или использовать `-d` без расширений |
| `pidstat`: не показывает потоки | Флаг `-t` не указан | `pidstat -t -p <PID> 1` | Добавить `-t` для отображения TID |
| `sar`: `No such file or directory` | Нет данных, `/var/log/sa/` пуст | `ls /var/log/sa/` | Данные собираются только после установки `sysstat` и запуска `sa1` |
| `dmesg`: пустой вывод | Ring buffer переполнен или ограничен | `dmesg -T --level=err,warn,crit` | Проверить `journalctl -k --since "10 min ago"` |
| `free`: `available` = 0, но `free` > 0 | Кэш занял всю память | `echo 3 > /proc/sys/vm/drop_caches` | Осторожно: сброс кэша снижает производительность |
| `top`: `wa` высокий, `iostat` %util низкий | Проблема не в диске, а в scheduler/mapping | `iostat -x 1` + `vmstat 1` | Проверить `iowait` на конкретных CPU через `mpstat` |
| `mpstat`: все ядра 100% `%sys` | Softirq или kernel bug | `softirqs -d` | Проверить сетевые softirqs, обновить ядро |
| `sar -n TCP`: `retrans/s` высокий | Потеря пакетов на L2/L3 | `mtr <host>`, `ethtool -S eth0` | Проверить duplex, скорость, cable, switch |
| `uptime`: LA = 0, но сайт не отвечает | LA не учитывает процессы в `D` state | `ps aux | grep ' D '` | Использовать `pidstat 1` или `perf top` |

### Дополнительные диагностические команды

```bash
# Полная сводка по CPU и памяти (альтернатива top)
ps aux --sort=-%cpu | head -10
# → root     1234  95.0  9.5 1536000 5000000 ?  Rsl   1:25   12345  95.0  9.5  python3

# Проверка IO Pressure (PSI) — ядро 5.x+
cat /proc/pressure/io
# → some avg10=5.00 avg60=2.50 avg300=1.00 total=54321
# → full avg10=1.00 avg60=0.50 avg300=0.20 total=12345

# Проверка нехватки файловых дескрипторов
cat /proc/sys/fs/file-nr
# → 12345   0   200000
# 12345 — выделено, 0 — свободно, 200000 — максимум

# Проверка сетевых ошибок и дропов
nstat -az | grep -E "Drop|Error|Overflow"
# → TcpExt:   1234  ListenOverflows
# → TcpExt:    567  ListenDrops
# → TcpExt:    890  TCPAbortOnClose

# Проверка NUMA-перекосов памяти
numastat -m
# →             Node 0    Node 1    Total
# → MemFree     1024      2048      3072
# → Active       512       256       768

# Быстрый просмотр cgroup-ограничений
systemd-cgtop -b -n 1 | head -10
# →     Control Group                    Tasks   %CPU   Memory
# →     /system.slice/nginx.service      12    5.00    256M
```

### Восстановление после частичного повреждения

```bash
# Если swap переполнен и система "зависла"
swapoff -a && swapon -a
# → (своп отключён и переинициализирован)

# Если кэш занял всю память, но критичные процессы работают
echo 3 > /proc/sys/vm/drop_caches
# → (требует root, безопасно при наличии inode cache)

# Если OOM-killer убил критичный процесс
systemctl restart critical-service
journalctl -u critical-service --since "5 min ago"
# → (проверка успешного перезапуска)

# Если забиты файловые дескрипторы
echo 500000 > /proc/sys/fs/file-max
# → (временное увеличение, требует перезагрузки для постоянства)
```

## Дополнительная информация

### Сводная таблица методов

| Метод / Утилита | Ресурс | За 60 сек даёт | Ограничения |
| :--- | :--- | :--- | :--- |
| `uptime` | CPU | Load Average, тренд | Не показывает распределение по ядрам |
| `dmesg -T` | HW/Kernel | OOM, TCP Drop, Segfaults | Ring buffer ограничен, старые события теряются |
| `vmstat 1` | CPU/Mem | Очередь, своп, контекст | Первая строка не актуальна, нет per-CPU детализации |
| `mpstat -P ALL` | CPU | Перекос по ядрам, softirq, steal | Требует `sysstat`, нет per-process детализации |
| `pidstat 1` | CPU/Mem | PID-виновник, %CPU | Не показывает историю, только текущие процессы |
| `iostat -xz` | Disk | %util, await, IOPS | Требует `sysstat >= 10` для `-xz` |
| `sar -n DEV` | Network | Насыщение канала | Требует предварительной активации `sysstat` |
| `free -h` | Memory | available, swap | Не показывает, кто именно потребляет память |
| `top`/`htop` | All | Общий вид, зомби, D-state | Интерактивный режим сложнее автоматизировать |
| `iotop -oP` | Disk | PID-виновник I/O в реальном времени | Требует root, пропускает всплески < 1с |
| `nethogs` | Network | PID-виновник трафика | Требует root, работает на уровне процессов |
| `ss -s` / `ss -Htn state established \| wc -l` | Network | Сводка по сокетам, число ESTABLISHED | Нет per-process детализации без `-p` |

### Порядок применения (Best Practice)

```bash
# Рекомендуемый pipeline для Rapid Assessment
# 1. Общая картина (10 сек)
uptime && dmesg -T | tail -5

# 2. Выявление перегруженного ресурса (20 сек)
vmstat 1 3 && iostat -xz 1 3

# 3. Детализация по ресурсу (20 сек)
mpstat -P ALL 1 3 && pidstat 1 3

# 4. Сеть (10 сек)
sar -n DEV 1 && sar -n TCP,ETCP 1

# 5. Альтернативный минималистичный пайплайн (30 сек, для серверов без sysstat)
uptime && nproc && htop -b -n 1 && mpstat -P ALL 1 3 && \
sudo iotop -oP -d 1 -n 2 && sudo nethogs -d 1 -n 2 && \
ss -s && ss -Htn state established | wc -l
```

### Лучшие практики и очистка

#### Стандарты для DevOps/SRE

Rapid Assessment интегрируется в процедуры реагирования на инциденты:
- **Runbook:** Каждый Rapid Assessment — шаблонный runbook, выполняемый за 60 секунд.
- **SLO/SLI:** LA > количество ядер более 5 минут = Violation SLO latency. Автоматический алерт.
- **Grafana Dashboards:** Предварительно созданные дашборды с метриками `node_load1`, `node_memory_available_bytes`, `node_disk_io_time_weighted_seconds_total`.
- **On-call Rotation:** Первичная диагностика выполняется on-call инженером до эскалации.

#### Очистка временных файлов

```bash
# Если использовали перенаправление в файл для анализа
rm -f /tmp/vmstat.log /tmp/iostat.log /tmp/sar.log

# Очистка кэша pidstat (если создавали)
rm -f /tmp/pidstat_$(date +%F).csv

# Проверка, что временные файлы удалены
ls /tmp/*.log /tmp/*.csv 2>/dev/null | wc -l
# → 0
```

#### Аудит после восстановления

```bash
# Фиксация метрик после вмешательства
uptime > /var/log/rapid_assessment_$(date +%F_%H%M).log
vmstat 1 60 >> /var/log/rapid_assessment_$(date +%F_%H%M).log
iostat -xz 1 60 >> /var/log/rapid_assessment_$(date +%F_%H%M).log

# Проверка, что система стабилизировалась
watch -n 1 'uptime'
# → LA должна стабилизироваться ниже количества ядер в течение 3-5 минут
```

### Предотвращение

- **sysctl:** Настройка `vm.swappiness=10`, `net.ipv4.tcp_syncookies=1`, `net.core.somaxconn=1024`.
- **limits.conf:** Увеличение `nofile` для критичных сервисов.
- **cgroups v2:** Использование `memory.max`, `cpu.max` для ограничения ресурсов контейнеров/сервисов.
- **Мониторинг:** Настройка алертов по LA, memory available, disk await, TCP retransmit.

### Крайние случаи

#### Статические бинарники и минимальные окружения

В Alpine Linux или BusyBox некоторые утилиты могут отсутствовать или работать иначе:
```bash
# Проверка наличия утилит в BusyBox
busybox --list | grep -E "vmstat|iostat|mpstat|pidstat|sar"
# → (busybox содержит только базовый набор)
```
Решение: устанавливать `sysstat` отдельно или использовать альтернативы (`busybox top`, `cat /proc/stat`).

#### Read-only корневой раздел

Если `/` смонтирован в read-only, некоторые утилиты не смогут обновить кэш:
```bash
# Проверка режима монтирования
mount | grep "on / "
# → /dev/sda1 on / type ext4 (ro,relatime)

# Временное перемонтирование в RW
mount -o remount,rw /
```

#### Файловые системы без поддержки POSIX-прав

На FAT32/NTFS/tmpfs отсутствуют стандартные права доступа. Проверка:
```bash
df -T /tmp | grep -E "FAT|NTFS|tmpfs"
# → /dev/sda1  ext4
```

#### Атрибут immutable (`+i`)

Если файл заблокирован атрибутом `+i`, команды записи не сработают:
```bash
lsattr /usr/bin/top
# → ----i--------e-- /usr/bin/top

# Снятие атрибута
chattr -i /usr/bin/top
```

#### Сверхнизкая нагрузка (LA < 1) при проблемах

Если LA низкий, но сервис не отвечает:
- Проверьте процессы в `D` state: `ps aux | grep ' D '`
- Проверьте `%wa` в `mpstat` — возможна блокировка на I/O
- Проверьте `sar -n TCP,ETCP` — сетевой stall

#### 32-битные системы (i386) на 64-битном ядре (x32 ABI)

На 32-битных окружениях `iostat` и `mpstat` могут показывать ограниченную информацию:
```bash
# Проверка архитектуры
uname -m
# → i686

# Альтернатива: /proc/stat для CPU
grep '^cpu ' /proc/stat
# → cpu  12345 0 6789 123456 123 456 789 0 0 0
```

## Связанные темы

- [Методология USE: Инраструктурный мониторинг](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)
- [Диагностика производительности: кейсы](./linux_performance_diagnostics_case.md)
- [Анализ ошибок и сбоев](../../SystemAdministration/Logging/error_and_crash_analysis.md)
