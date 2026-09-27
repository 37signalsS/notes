# Диагностика производительности в Linux: практические кейсы

## Определения

**TTFB (Time To First Byte)** — время от отправки запроса клиентом до получения первого байта ответа. Ключевой индикатор производительности серверной части.

**Load Average (LA)** — среднее количество процессов в очереди на исполнение и в состоянии бесперебойного ожидания (обычно I/O). Подробнее: [**Планировщик и LA**](../../Core/processes/scheduling.md).

**I/O Wait (`wa`)** — процент времени простоя CPU, пока есть активные запросы к дисковой подсистеме. Косвенный признак дискового bottleneck.

**PSI (Pressure Stall Information)** — механизм ядра (≥4.20) для измерения реального «голодания» ресурсов. Показывает, какой процент времени процессы были заблокированы из-за нехватки CPU, Memory или I/O.

**pidstat** — утилита из пакета `sysstat` для мониторинга активности процессов в реальном времени. Показывает CPU, память, I/O по PID с возможностью разделения на потоки (`-t`).

**vmstat** — утилита для снятия «снимка» виртуальной статистики: процессы, память, swap, I/O, CPU. Режим `vmstat 1` позволяет наблюдать динамику.

**iostat** — утилита из `sysstat` для анализа утилизации дисковых устройств, задержек (`await`) и глубины очереди (`aqu-sz`).

**ss** — утилита для отображения сокетов (замена `netstat`). Показывает состояние TCP/UDP соединений, параметры сокетов, размеры очередей.

**strace** — утилита для трассировки системных вызовов. Позволяет увидеть, что именно делает процесс и сколько времени занимает каждый вызов.

**perf** — официальный инструмент профилирования производительности, использующий аппаратные счётчики PMU и tracepoints ядра. Подробнее: [**perf**](../Performance/perf.md).

**cgroup v2 I/O controller** — подсистема cgroups v2 для ограничения и учёта дискового I/O. Метрики доступны через `io.stat`, лимиты через `io.max`.

**OOM Killer** — механизм ядра, который завершает процессы при критической нехватке памяти. События логируются в `dmesg` и `journalctl`.

**swappiness** — параметр ядра (`vm.swappiness`), определяющий склонность системы перемещать неактивные страницы в swap. Значение 0 = минимизировать swap, 100 = агрессивно использовать swap.

**Transparent Huge Pages (THP)** — механизм ядра, автоматически объединяющий стандартные страницы 4KB в огромные (2MB/1GB) для снижения TLB misses. Может вызывать задержки и всплески CPU.

**NUMA (Non-Uniform Memory Access)** — архитектура многопроцессорных систем, где доступ к памяти зависит от близости ядра к узлу памяти. Неправильное размещение процессов/памяти вызывает лишние задержки.

**Off-CPU** — время, в течение которого процесс не выполняется на CPU (ожидает I/O, мьютекса, планирования). Анализ Off-CPU времени часто раскрывает bottlenecks, скрытые от CPU-bound профилировщиков.

## Основные концепции

### Методология диагностики производительности

Диагностика производительности — это итеративный процесс, который следует базовой методологии:

1. **Macro-анализ:** Оценка общего состояния системы через `top`, `htop`, `vmstat`.
2. **Локализация:** Определение проблемного ресурса (CPU, RAM, Disk, Network) через PSI и USE-методологию.
3. **Micro-анализ:** Исследование конкретного процесса или системного вызова через `pidstat`, `strace`, `perf`.

### Методологии мониторинга

- **USE (Infrastructure):** Utilization (утилизация), Saturation (насыщение), Errors (ошибки) — для каждого ресурса (CPU, RAM, Disk, Network).
- **RED (Services):** Rate (RPS), Errors (ошибки), Duration (латентность) — для API и микросервисов.
- **Golden Signals:** Latency, Traffic, Errors, Saturation.

### Паттерны проблем и индикаторы

| Симптом | Вероятная причина | Основной инструмент |
| :--- | :--- | :--- |
| Высокий TTFB при низком CPU | Ожидание внешнего API или DB | `strace -T`, `tcpdump` |
| Высокий `iowait` (wa > 15%) | Перегрузка диска, медленный RAID | `iostat -xz 1`, `iotop` |
| Высокий LA при низком `wa` | CPU saturation (очередь на ядра) | `uptime`, `cat /proc/pressure/cpu` |
| Рост Swap при наличии Free RAM | Memory pressure, агрессивный swappiness | `vmstat 1`, `cat /proc/pressure/memory` |
| `oom-kill` в `dmesg` | Нехватка памяти, утечка | `dmesg | grep -i oom`, `journalctl -k` |
| Процессы в `D`-состоянии | Непрерываемый сон (I/O wait) | `ps aux | awk '$8 ~ /D/'`, `pidstat -d 1` |
| Высокий `%si`/`%sy` | Обработка прерываний (SoftIRQ) | `top`, `mpstat -P ALL 1` |
| P99 latency растет при среднем 10мс | Ретрансмиты, очередь на коммутаторе | `ss -tin`, `tcpdump` |
| `getrandom` блокируется | Низкая энтропия | `cat /proc/sys/kernel/random/entropy_avail` |
| `cgroup cpu.max` throttling | Превышение лимитов контейнера | `cat /sys/fs/cgroup/<slice>/cpu.max` |

### Интерпретация PSI

При работе с `/proc/pressure/*` важно различать:

- **`some`**: процент времени, когда **хотя бы одна** задача была заблокирована. Указывает на конкуренцию.
- **`full`**: процент времени, когда **все** не-idle задачи были заблокированы одновременно. Указывает на критическое насыщение.

Для CPU и IRQ доступна только метрика `some`, так как система всегда выполняет хотя бы один процесс (планировщик).

## Практические сценарии

### Кейс 1: Высокий TTFB — PHP/WordPress (CPU Bound)

**Симптом:** TTFB ~800 мс при росте RPS.

**Диагностика:**
1. **Нагрузка:** `wrk -t4 -c100 -d30s http://localhost/`
2. **Мониторинг:** `htop` показывает 100% загрузку всех ядер процессами `php-fpm`.
3. **Анализ:** `perf record -F 99 -p <PID> -g -- sleep 10` выявил 40% времени в модуле `xdebug`.
4. **Решение:** Отключение `Xdebug` и включение `OPcache`.
**Результат:** TTFB упал до 150 мс.
*Вывод:* Отладочные инструменты в Prod — критическая ошибка.

---

### Кейс 2: Плавающий TTFB — Ожидание внешнего ресурса

**Симптом:** Случайные задержки до 5 секунд, CPU и Диск в норме.

**Диагностика:**
1. **Трассировка:**
```bash
sudo strace -T -e connect,poll,read -p <PID>
# → poll([{fd=5, ...}], 1, 5000) = 0 (Timeout) <5.000123>
```
2. **Идентификация FD:** `ls -l /proc/<PID>/fd/5` указывает на сокет к внешнему API.
3. **Решение:** Установка агрессивных таймаутов в коде и внедрение очереди (RabbitMQ/Nats) для асинхронной обработки.

---

### Кейс 3: Скрытое голодание ресурсов (PSI)

**Симптом:** Жалобы на «тормоза» базы данных, хотя `iowait` всего 2%.

**Диагностика:**
1. **Проверка давления I/O:**
```bash
cat /proc/pressure/io
# → some avg10=25.40 avg60=15.10 avg300=5.05
```
*Интерпретация:* `avg10=25.40` означает, что в последние 10 секунд процессы 25% времени ждали диск. Это критично.
2. **Поиск причины:** `iostat -xz 1` показывает высокую латентность (`await > 50ms`) на вторичном диске с логами.
*Подробнее:* [**Диагностика дискового ввода-вывода**](../Performance/disk_io_troubleshooting.md).

---

### Кейс 4: Сетевая задержка (Tail Latency)

**Симптом:** P99.9 латентность растет до 1с при среднем значении 10мс.

**Диагностика:**
1. **Анализ сокетов:**
```bash
ss -tin
# → bbr wscale:7,7 rto:1000 rtt:15/2 ato:40 mss:1448 ... retrans:1/15
```
2. **Причина:** Ретрансмиты из-за переполнения очередей на коммутаторе или некорректного MTU.
3. **Решение:** Тюнинг `net.core.somaxconn` и переход на алгоритм `BBR`.
*Подробнее:* [**Диагностика Tail Latency**](../Performance/diagnosing_tail_latency.md).

---

### Кейс 5: Зависания при крипто-операциях

**Симптом:** SSH и TLS «замирают» на несколько секунд.

**Диагностика:**
```bash
cat /proc/sys/kernel/random/entropy_avail
# → 15 (Критически мало)
```
**Решение:** Установка `haveged` или проброс `virtio-rng` в виртуальную машину.
*Подробнее:* [**Проблемы с низкой энтропией**](./linux_entropy_troubleshooting.md).

---

### Кейс 6: Memory pressure и OOM Killer

**Симптом:** Приложения падают с `OOMKilled`, система становится неотзывчивой.

**Диагностика:**
1. **Проверка давления памяти:**
```bash
cat /proc/pressure/memory
# → some avg10=85.20 avg60=40.10 avg300=12.05
```
2. **Поиск жертв OOM:**
```bash
dmesg | grep -i "out of memory"
# или
journalctl -k | grep -i "oom"
```
3. **Анализ потребления:**
```bash
ps aux --sort=-%mem | head -10
# или
smem -tk
```
4. **Проверка параметров:**
```bash
cat /proc/sys/vm/swappiness
# → 60 (по умолчанию, может быть слишком агрессивным)
```

**Решение:**
1. **Временное:** увеличение swap, отключение THP.
2. **Постоянное:** оптимизация приложения, увеличение RAM, настройка cgroup лимитов.
3. **Для контейнеров:** корректные `requests` и `limits` в manifests.

**Предотвращение:**
```bash
# Отключение THP (временное)
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled

# Уменьшение swappiness
echo 10 | sudo tee /proc/sys/vm/swappiness
```

---

### Кейс 7: Высокий I/O wait и насыщение диска

**Симптом:** `iowait` стабильно выше 20%, приложения отвечают медленно.

**Диагностика:**
1. **Быстрый обзор:**
```bash
iostat -xz 1
# await > 50ms на HDD, > 100µs на NVMe — повод для беспокойства
# %util близко к 100% — диск насыщен
```
2. **Поиск виновника:**
```bash
iotop -oP
# Показывает процессы, которые реально делают I/O
```
3. **Проверка D-state процессов:**
```bash
ps aux | awk '$8 ~ /D/'
# Процессы в uninterruptible sleep
```

**Решение:**
1. **Перенос нагрузки:** миграция логи/данные на быстрые диски (NVMe).
2. **Кэширование:** включение `readahead`, использование `bcache`/`dm-cache`.
3. **Планировщик I/O:** переключение на `mq-deadline` для SSD/NVMe или `bfq` для десктопов.
4. **Очереди:** увеличение `nr_requests` в `/sys/block/sdX/queue/`.

*Подробнее:* [**Диагностика дискового ввода-вывода**](../Performance/disk_io_troubleshooting.md).

---

### Кейс 8: Процесс-специфичный CPU-spike

**Симптом:** `top` показывает 100% CPU на одном процессе, но `htop` не даёт информации о причинах.

**Диагностика:**
1. **Идентификация потока:**
```bash
top -H -p <PID>
# Найти TID с максимальным CPU
```
2. **Быстрый взгляд на «горячие» функции:**
```bash
perf top -g -t <TID>
```
3. **Точная запись:**
```bash
perf record -F 99 -g -t <TID> -- sleep 10
perf report
```
4. **Альтернатива без perf:**
```bash
sudo strace -c -p <PID>
# Показывает распределение по системным вызовам
```

**Решение:**
1. **Оптимизация кода:** устранение hotspots, найденных через `perf report`.
2. **Ограничение ресурсов:** `cpulimit` или cgroup v2 `cpu.max` для некритичных фоновых задач.
3. **Планировщик:** `chrt` для повышения приоритета критичных процессов.

---

### Кейс 9: Swap thrashing и утечка памяти

**Симптом:** Система зависает, `vmstat` показывает огромные значения `si`/`so` (swap in/out).

**Диагностика:**
1. **Мониторинг swap:**
```bash
vmstat 1
# si/so > 0 — активный свопинг
```
2. **Поиск потребителей:**
```bash
ps aux --sort=-%mem | head -20
# Или smem для группировки по библиотекам
```
3. **Проверка активности:**
```bash
sar -W 1 10
# pswpin/s, pswpout/s
```

**Решение:**
1. **Краткосрочное:** `swapoff -a` для освобождения, если есть свободная RAM.
2. **Долгосрочное:** увеличение RAM, оптимизация приложения, настройка `vm.swappiness`.
3. **Ограничение:** cgroup v2 `memory.max` для предотвращения тотального swap thrashing.

---

### Кейс 10: Hung task и kernel soft lockup

**Симптом:** Система не реагирует на клавиатуру/сеть, но «жива». `dmesg` показывает `CPU#X: hung task` или `soft lockup`.

**Диагностика:**
1. **Проверка логов ядра:**
```bash
dmesg | grep -E "hung task|soft lockup|rcu"
```
2. **Анализ hung task:**
```bash
cat /proc/<PID>/stack
# Показывает стек вызовов ядра для процесса
```
3. **Проверка PSI:**
```bash
cat /proc/pressure/cpu
# some > 0 = процессы ждут CPU
```

**Решение:**
1. **Ядро:** обновление до последней стабильной версии (исправления RCU, scheduler).
2. **Железо:** проверка на перегрев, ECC-ошибки (`mcelog`), BIOS.
3. **Драйверы:** откат недавно обновлённых драйверов (особенно сетевых/дисковых).
4. **Включение hung task timeout:**
```bash
echo 120 | sudo tee /proc/sys/kernel/hung_task_timeout_secs
```

---

### Кейс 11: DNS resolution latency

**Симптом:** Приложения тормозят на 200–500мс при старте или при обращении к внешним сервисам.

**Диагностика:**
1. **Проверка разрешения имён:**
```bash
time dig example.com +short
time nslookup example.com
```
2. **Анализ системных вызовов:**
```bash
sudo strace -T -e getaddrinfo -p <PID>
```
3. **Проверка `/etc/nsswitch.conf`:**
```bash
cat /etc/nsswitch.conf | grep hosts
# Должен содержать: files dns
```
4. **Кэширование:**
```bash
systemctl status systemd-resolved
# или nscd, dnsmasq
```

**Решение:**
1. **Локальный кэш:** установка `dnsmasq` или `systemd-resolved` с кэшированием.
2. **Файл `/etc/hosts`:** для критичных внутренних имён.
3. **Timeout:** уменьшение `timeout` и `attempts` в `/etc/resolv.conf`.

---

### Кейс 12: File descriptor exhaustion

**Симптом:** Приложения падают с `Too many open files`, `EMFILE`.

**Диагностика:**
1. **Глобальные лимиты:**
```bash
cat /proc/sys/fs/file-nr
# (выделено, использовано, максимум)
```
2. **Лимит процесса:**
```bash
cat /proc/<PID>/limits | grep "open files"
```
3. **Поиск утечек:**
```bash
ls /proc/<PID>/fd | wc -l
# Сравните с лимитом
```
4. **Анализ:**
```bash
lsof -p <PID> | wc -l
lsof | awk '{print $1}' | sort | uniq -c | sort -rn | head
```

**Решение:**
1. **Временное:** увеличение `ulimit -n` для пользователя/системы.
2. **Постоянное:** `/etc/security/limits.conf`, `/etc/sysctl.d/99-fs.conf`.
3. **Код:** закрытие файловых дескрипторов после использования, использование пулов.

---

### Кейс 13: Контейнеры: ограничения cgroup v2

**Симптом:** Приложение в Docker/Kubernetes работает медленно, хотя хост имеет свободные ресурсы.

**Диагностика:**
1. **Проверка CPU throttling:**
```bash
cat /sys/fs/cgroup/cpu.max
# Например: 50000 100000 = 50% лимит
cat /sys/fs/cgroup/cpu.stat
# nr_throttled — количество throttled интервалов
```
2. **Проверка памяти:**
```bash
cat /sys/fs/cgroup/memory.max
cat /sys/fs/cgroup/memory.current
```
3. **Проверка I/O:**
```bash
cat /sys/fs/cgroup/io.stat
cat /sys/fs/cgroup/io.max
```

**Решение:**
1. **Корректировка лимитов:** увеличение `cpu.max`, `memory.max` в deployment spec.
2. **Requests/Limits:** всегда задавайте `requests` чуть ниже среднего потребления, `limits` с запасом.
3. **QoS:** для production используйте `Guaranteed` QoS class (requests == limits).

---

## Дополнительная информация

### Типичные проблемы и решения

| Проблема | Симптомы | Причина | Решение |
|----------|----------|---------|---------|
| Высокий TTFB при низком CPU | Запросы зависают | Внешний API, debug-инструменты | strace, perf, отключить xdebug |
| `iowait` > 20% | Медленные приложения | Насыщение диска | iostat, iotop, миграция на NVMe |
| `oom-kill` в логах | Процессы падают | Утечка памяти, низкий RAM | dmesg, smem, увеличение RAM |
| Высокий LA при низком `wa` | CPU-bound нагрузка | Очередь на ядра | uptime, perf top, scale out |
| `si`/`so` > 0 в vmstat | Диски активны | Swap thrashing | vmstat, sar, настройка swappiness |
| Процессы в `D`-состоянии | Непрерываемый сон | I/O wait | ps, pidstat, iostat |
| `EMFILE` / `Too many open files` | Ошибки открытия файлов | Исчерпан лимит FD | lsof, ulimit, limits.conf |
| DNS latency > 100мс | Задержки при старте | Медленный resolver | dig, systemd-resolved, hosts |
| cgroup throttling | Медленный контейнер | Превышение cpu.max | cat /sys/fs/cgroup/cpu.max |
| `getrandom` блокируется | strace `<unfinished ...>` | Низкая энтропия | haveged, virtio-rng |

### Чек-лист быстрой диагностики

1. **Макро-анализ:**
   ```bash
   uptime && vmstat 1 5 && iostat -xz 1 3
   ```
   Оцените LA, CPU, память, swap, I/O.

2. **Локализация ресурса:**
   ```bash
   cat /proc/pressure/cpu
   cat /proc/pressure/memory
   cat /proc/pressure/io
   ```
   Определите, какой ресурс дефицитен.

3. **Поиск hot processes:**
   ```bash
   top -H -p $(pgrep -d, -f <service>)
   # или
   pidstat -t -p $(pgrep -d, -f <service>) 1
   ```

4. **Проверка системных вызовов:**
   ```bash
   sudo strace -T -e trace=network,file,read,write -p <PID> -c
   ```

5. **Проверка памяти:**
   ```bash
   ps aux --sort=-%mem | head -10
   cat /proc/meminfo | grep -E "MemAvailable|SwapFree|Committed_AS"
   ```

6. **Проверка сети:**
   ```bash
   ss -s
   ss -tin | head -20
   ```

### Рекомендации

1. **Используйте перцентили, а не средние значения.** P95/P99/P99.9 — единственные метрики, отражающие реальный опыт пользователей.
2. **Начинайте с PSI.** `cat /proc/pressure/*` даст быстрый ответ, какой ресурс дефицитен.
3. **Не игнорируйте `vmstat`.** Один snapshot часто даёт больше информации, чем минутный график.
4. **Для глубокого CPU-анализа** используйте `perf`, но предварительно установите `kernel.perf_event_paranoid = 1`.
5. **Для дисков** используйте `iostat -xz 1` и обращайте внимание на `await`, `aqu-sz`, а не на `%util`.
6. **Для памяти** используйте `smem` вместо `ps` для корректного учёта shared memory.
7. **Для сетей** используйте `ss` вместо `netstat`, `tcpdump` для захвата и анализа трафика.
8. **В контейнерах** всегда настраивайте `requests` и `limits`, мониторьте `cpu.max` и `memory.current`.
9. **Ведите журнал изменений.** Любое изменение параметров ядра или конфигурации должно документироваться.
10. **Автоматизируйте сбор артефактов.** Скрипты сбора `dmesg`, `journalctl`, `vmstat`, `iostat` экономят часы при инцидентах.

### Очистка после диагностики

1. **Остановить фоновые процессы мониторинга:**
   ```bash
   sudo pkill iostat vmstat pidstat
   ```
2. **Удалить временные unit-файлы systemd** (если создавались для сбора метрик):
   ```bash
   sudo rm /etc/systemd/system/perf-collect.service
   sudo systemctl daemon-reload
   ```
3. **Откатить параметры sysctl** (если менялись для диагностики):
   ```bash
   sudo sysctl -p /etc/sysctl.d/99-performance.conf
   ```
4. **Удалить временные ключи и сертификаты** (если генерировались для тестов TLS/SSH):
   ```bash
   rm -rf /tmp/test-certs/
   ```
5. **Очистить кэш eBPF-инструментов** (если использовались `bpftrace`, `bcc-tools`):
   ```bash
   sudo rm -rf /var/log/bpftrace/
   ```

### Границы applicability

- **Ядро Linux 5.4+** рекомендуется для полной поддержки PSI, cgroups v2, io_uring. На ядрах <4.20 PSI недоступен, используйте `vmstat` и `iostat`.
- **eBPF-инструменты** (`bpftrace`, `bcc-tools`) требуют ядро 4.9+ с включёнными `CONFIG_BPF`, `CONFIG_BPF_SYSCALL`, `CONFIG_DEBUG_INFO_BTF`.
- **NVMe vs SATA/SSD:** метрики `await` и `aqu-sz` интерпретируются по-разному. Для NVMe порог насыщения — `aqu-sz > 32`, для SATA SSD — > 8.

## См. также

- [**Общая методология диагностики**](./general_troubleshooting_methodology.md) — стратегии и золотые правила.
- [**Диагностика Tail Latency**](../Performance/diagnosing_tail_latency.md) — глубокий разбор хвостовой задержки.
- [**Диагностика проблем с энтропией**](./linux_entropy_troubleshooting.md) — влияние энтропии на крипто-операции.
- [**Диагностика CPU**](../Performance/cpu_performance_diagnostics.md) — mpstat, load average, saturation, context switches, softirq.
- [**Диагностика памяти**](../Performance/memory_performance_diagnostics.md) — vmstat, OOM, THP, overcommit, slab.
- [**Диагностика сети**](../Performance/network_performance_diagnostics.md) — ss, nstat, retransmissions, ring buffer, iperf3.
- [**Диагностика контейнеров**](../Performance/container_performance_diagnostics.md) — CPU throttling, memory limits, cgroup v2.
- [**Flame graphs**](../Performance/perf.md#flame-graphs) — визуализация CPU-профилей через perf.
- [**Continuous Profiling**](../../../Concepts/continuous_profiling.md) — Pyroscope, Parca, eBPF-based profiling.
- [**sysctl production**](../../Core/kernel/sysctl_production.md) — параметры ядра для production.
