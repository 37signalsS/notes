# Pressure Stall Information (PSI) — статистика давления на ресурсы

## Определения

**Pressure Stall Information (PSI)** — механизм ядра Linux (начиная с версии 4.20), предназначенный для точного мониторинга «давления» на аппаратные ресурсы: процессор (CPU), память (Memory), ввод-вывод (I/O) и прерывания (IRQ). В отличие от классических метрик загрузки (Load Average), PSI количественно оценивает **время простоя (stall time)** — время, которое процессы теряют в ожидании доступа к ресурсу. Это позволяет выявлять деградацию производительности на ранних стадиях, когда классические метрики могут выглядеть нормальными.

## Основные концепции

### Принцип работы

PSI измеряет время, в течение которого задачи (tasks) не могли выполняться или замедлялись из-за нехватки ресурса.

| Ресурс | Условие возникновения давления (Stall) |
| :--- | :--- |
| **CPU** | Задачи готовы к выполнению (runnable), но ожидают свободного ядра в очереди (runqueue). |
| **Memory** | Задачи ожидают выделения страниц, работают в режиме reclaim (очистка кэша), thrashing (активный свопинг) или ждут завершения page fault. |
| **I/O** | Задачи заблокированы в состоянии Uninterruptible Sleep (D-state) в ожидании завершения операций чтения/записи. |
| **IRQ** | Задачи простаивают, так как CPU занят обработкой аппаратных (Hardirq) или программных (Softirq) прерываний (доступно с ядра 6.1). |

### Архитектура и механизм сбора данных

PSI работает на уровне подсистем ядра, связанных с каждым ресурсом:

- **CPU:** Интегрирован с планировщиком процессов (CFS). При наличии готовых к выполнению задач в очереди runqueue ядро учитывает время их ожидания.
- **Memory:** Подключен к менеджеру памяти (mm subsystem). Учитывает время, затраченное на reclaim (освобождение страниц), page fault и свопинг.
- **I/O:** Взаимодействует с блоковым слоем (block layer) и подсистемой I/O scheduler. Учитывает время в состоянии D (Uninterruptible Sleep).
- **IRQ:** Использует счетчики времени обработки прерываний (hardirq/softirq), доступные при включенном `CONFIG_IRQ_TIME_ACCOUNTING`.

**Механизм окна усреднения:**
Значения `avg10`, `avg60`, `avg300` вычисляются как экспоненциально взвешенное скользящее среднее (EWMA) с разными параметрами затухания для каждого окна. Это позволяет одновременно видеть как мгновенные всплески (avg10), так и долгосрочные тренды (avg300).

### Метрики Some и Full

Каждый файл в `/proc/pressure/` предоставляет два типа метрик (за исключением `cpu` и `irq`):

1.  **`some`**: Процент времени, в течение которого **хотя бы одна** задача была заблокирована из-за нехватки ресурса. Указывает на наличие **конкуренции (contention)**. Общая пропускная способность системы может снижаться, но часть задач всё ещё выполняется.
2.  **`full`**: Процент времени, в течение которого **все** не-idle задачи были заблокированы одновременно. Указывает на **критическое насыщение (thrashing)**. В этот момент система практически не выполняет полезной работы, так как все ресурсы тратятся на управление дефицитом.

> **Важное ограничение:** Для `cpu` и `irq` доступна только метрика `some`. Это связано с тем, что наличие готовой задачи всегда означает прогресс выполнения хотя бы на одном ядре (система не может быть "полностью" заблокирована процессором, так как сам планировщик — это тоже код, исполняемый на CPU).

### Формат вывода

```bash
cat /proc/pressure/memory
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381
```

- **`avg10/60/300`**: Скользящее среднее значение давления в процентах за последние 10, 60 и 300 секунд.
- **`total`**: Суммарное время простоя в микросекундах с момента загрузки системы.

### PSI против Utilization

PSI дополняет, а не заменяет классические метрики утилизации. Высокая утилизация не всегда означает деградацию, а низкая утилиция не исключает давления.

| Метрика | Что измеряет | Когда полезна |
| :--- | :--- | :--- |
| **CPU Utilization** | % времени, когда CPU был занят | Общая загрузка, планирование |
| **CPU PSI (some)** | % времени, когда процессы ждали CPU | Обнаружение saturation при <100% utilization |
| **Memory Utilization** | % используемой RAM | Общая оценка потребления |
| **Memory PSI (full)** | % времени, когда все процессы ждали RAM | Ранний индикатор impending OOM |
| **Disk I/O Utilization** | % времени, когда диск был занят | Оценка пропускной способности |
| **Disk I/O PSI (some)** | % времени, когда процессы ждали I/O | Обнаружение bottleneck в storage |

### PSI vs Load Average

| Характеристика | Load Average (LA) | PSI |
| :--- | :--- | :--- |
| **Природа метрики** | Усредненная длина очереди задач. | Точное время ожидания в микросекундах. |
| **Детализация** | Смешивает CPU и I/O (в Linux). | Четко разделяет CPU, память, I/O и IRQ. |
| **Реактивность** | Медленная (экспоненциальное затухание). | Мгновенная (через механизм триггеров). |
| **Точность** | Косвенный индикатор (зависит от числа ядер). | Абсолютный индикатор потери производительности. |

### Рекомендуемые пороги давления (Thresholds)

Ориентировочные значения для мониторинга (окно 10с — `avg10`):

| Ресурс | Предупреждение (Warning) | Критическое (Critical) |
| :--- | :--- | :--- |
| **CPU (some)** | > 10% | > 25–30% |
| **Memory (some)** | > 5–7% | > 15% |
| **Memory (full)** | > 3% | > 10% (риск OOM) |
| **I/O (full)** | > 5% | > 20% (деградация хранилища) |
| **IRQ (some)** | > 5% | > 15% (проблемы с сетью/прерываниями) |

> **Важно:** Пороги зависят от SLA сервиса. Для latency-sensitive приложений (trading, real-time) пороги должны быть на 30–50% ниже.

## Активация и настройка

### Требования
- **Ядро:** 4.20+ (базовый PSI), 6.1+ (IRQ pressure).
- **Конфигурация ядра:**
  - `CONFIG_PSI=y`
  - `CONFIG_IRQ_TIME_ACCOUNTING=y` (для IRQ метрик)

### Параметры загрузки

В некоторых дистрибутивах (Ubuntu, Debian) PSI может быть отключен для экономии ресурсов. Проверить статус:
```bash
[ -e /proc/pressure/cpu ] && echo "PSI Enabled" || echo "PSI Disabled"
```
Для включения добавьте в параметры загрузчика (GRUB):
```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="... psi=1"
```
После изменения выполните `update-grub` и перезагрузитесь.

Доступные значения параметра `psi`:
- `psi=1` (по умолчанию на большинстве дистрибутивов) — PSI включен.
- `psi=0` — PSI отключен (экономия ~1% CPU на высоконагруженных системах с >64 ядрами).
- `psi=2` — включен только для CPU (экспериментальный режим в старых патчах, в современных ядрах не актуален).

> **Edge case:** На некоторых виртуализированных окружениях (OpenVZ, early KVM) PSI может отсутствовать даже при ядре 4.20+ из-за того, что хост не передает счетчики прерываний. Проверка: `grep -i psi /boot/config-$(uname -r)`.

## Архитектура и ядерные механизмы

### Подсистемы ядра, участвующие в PSI

| Подсистема | Ресурс | Механизм учета |
| :--- | :--- | :--- |
| **CFS Scheduler** | CPU | Замер времени ожидания в очереди runqueue для задач со статусом `TASK_RUNNING`. |
| **Memory Reclaim** | Memory | Учет времени, потраченного на `kswapd` (фоновый reclaim) и прямой reclaim из контекста процесса. |
| **Block Layer** | I/O | Учет времени в состоянии `TASK_UNINTERRUPTIBLE` при операциях чтения/записи. |
| **IRQ Subsystem** | IRQ | Накопление времени обработки `hardirq` и `softirq` с момента последнего счета (требует `CONFIG_IRQ_TIME_ACCOUNTING`). |

### Взаимодействие с cgroups v2

В cgroups v2 PSI является нативным компонентом. Для каждой контрольной группы создаются файлы давления:
- `cpu.pressure`
- `memory.pressure`
- `io.pressure`
- `irq.pressure` (с ядра 6.1)

Это позволяет получать изолированные метрики для каждого контейнера, сервиса или пользовательского cgroup, а не только системные агрегаты из `/proc/pressure/`.

## Мониторинг через Prometheus и Grafana

### Сбор метрик

Начиная с **node_exporter 1.8.0**, поддерживается сбор PSI-метрик. Включите коллектор `pressure` в конфигурации:

```bash
# /etc/node_exporter/collector.pressure.enable
--collector.pressure
```

Доступные метрики:
- `node_pressure_cpu_waiting_seconds_total` — время ожидания CPU.
- `node_pressure_memory_waiting_seconds_total` — время ожидания памяти.
- `node_pressure_io_waiting_seconds_total` — время ожидания I/O.
- `node_pressure_irq_waiting_seconds_total` — время обработки прерываний.

### Правила алертинга (Prometheus Alerting Rules)

```yaml
groups:
  - name: pressure_alerts
    rules:
      - alert: HighCPUPressure
        expr: |
          rate(node_pressure_cpu_waiting_seconds_total[5m]) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое давление на CPU ({{ $labels.instance }})"
          description: "Процессы ждут CPU {{ $value | humanizePercentage }} времени за 5 минут."

      - alert: CriticalMemoryPressureFull
        expr: |
          rate(node_pressure_memory_waiting_seconds_total{state="full"}[5m]) > 0.03
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Критическое давление на память ({{ $labels.instance }})"
          description: "Все процессы заблокированы ожиданием памяти {{ $value | humanizePercentage }} времени. Риск OOM."

      - alert: HighIOPressure
        expr: |
          rate(node_pressure_io_waiting_seconds_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое давление на I/O ({{ $labels.instance }})"
          description: "Процессы ждут завершения операций ввода-вывода {{ $value | humanizePercentage }} времени."

      - alert: IRQStorm
        expr: |
          rate(node_pressure_irq_waiting_seconds_total[5m]) > 0.05
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Возможен IRQ-шторм ({{ $labels.instance }})"
          description: "CPU занят обработкой прерываний более чем {{ $value | humanizePercentage }} времени."
```

### Панели Grafana

Для визуализации рекомендуется использовать готовые дашборды:
- **Node Exporter Full** (ID: 1860) — содержит панели PSI по умолчанию.
- **PSI Pressure** (ID: 11234) — специализированный дашборд для анализа давления на ресурсы.

Ключевые визуализации:
1. **Time series** для `avg10` по каждому ресурсу с зонами Warning/Critical.
2. **Heatmap** распределения времени простоя по часам суток (выявление циклов batch-задач).
3. **Correlation panel** — совместный график PSI Memory + Swap Used + OOM Kill events.

## PSI в контейнерах (Docker и Kubernetes)

### Docker

Для диагностики конкретного контейнера используйте `docker exec` для чтения `/proc/pressure/` внутри namespace:

```bash
# Проверка давления на память внутри контейнера
docker exec <container_id> cat /proc/pressure/memory

# Проверка всех ресурсов
docker exec <container_id> sh -c 'for f in cpu memory io; do echo "=== $f ==="; cat /proc/pressure/$f; done'
```

Через нативные метрики Docker Engine (cgroups v2):
```bash
# Путь к cgroup (зависит от драйвера: cgroupfs или systemd)
# cgroupfs:
cat /sys/fs/cgroup/docker/<container_id>/memory.pressure
# systemd:
cat /sys/fs/cgroup/system.slice/docker-<container_id>.scope/memory.pressure
```

> **Важно:** В Docker PSI доступен только если хост имеет ядро 4.20+ с включенным `CONFIG_PSI`. Контейнер не может получить доступ к PSI, если хост его отключил.

### Kubernetes

В Kubernetes (cgroups v2, K8s 1.25+) PSI доступен на двух уровнях:

1. **Node-level (системный):** `/proc/pressure/*` — показывает общее давление на узел.
2. **Pod-level (cgroup):** `/sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/<container_id>/memory.pressure` — изолированное давление для конкретного пода.

```bash
# Системный PSI на узле
cat /proc/pressure/memory

# PSI для конкретного пода (требуется доступ к kubelet API или exec в init-контейнер)
POD_UID=$(kubectl get pod <pod_name> -o jsonpath='{.metadata.uid}')
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/docker-<id>.scope/memory.pressure
```

**Интеграция с kubelet:**
Начиная с определенных версий, kubelet может использовать PSI как сигнал для выселения подов. PSI показывает **время простоя**, в отличие от `memory.available`, который является мгновенным снимком. Это делает PSI более надежным предиктором проблем.

## Диагностические сценарии

### Сценарий 1: Диагностика давления на CPU

**Симптомы:** Рост латентности, снижение пропускной способности, высокий Load Average при невысокой утилизации CPU.

```bash
# 1. Проверка системного PSI CPU
cat /proc/pressure/cpu
# some avg10=12.50 avg60=8.30 avg300=5.10 total=45678901
# → avg10 > 10%: явная конкуренция за ядра

# 2. Поиск процессов, потребляющих CPU
ps aux --sort=-%cpu | head -11

# 3. Проверка троттлинга в cgroups v2
cat /sys/fs/cgroup/system.slice/my-app.service/cpu.stat
# nr_periods=12345
# nr_throttled=500    ← высокое значение = проблемы
# throttled_usec=25000000

# 4. Проверка очереди runqueue
vmstat 1 5
# procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
#  r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
#  4  0      0 524288  12800 1048576    0    0     0     2  200  300 25  5 70  0  0
# → r=4: 4 задачи в очереди готовых к выполнению
```

**Решение:**
- Вертикальное масштабирование (больше ядер) или горизонтальное (больше инстансов).
- Оптимизация CPU-intensive кода (профилирование через `perf top`, `pprof`).
- Настройка CPU weight/shares в cgroups для приоритизации критичных сервисов.

### Сценарий 2: Диагностика давления на память

**Симптомы:** OOM Kill, svap-активность, рост латентности, systemd-oomd убивает сервисы.

```bash
# 1. Проверка системного PSI Memory
cat /proc/pressure/memory
# some avg10=8.20 avg60=5.10 avg300=2.80 total=12345678
# full avg10=3.50 avg60=1.20 avg300=0.40 total=4567890
# → full avg10 > 3%: критическое давление, процессы останавливаются

# 2. Проверка доступной памяти
free -h
cat /proc/meminfo | grep -E 'MemAvailable|SwapFree|Committed_AS'

# 3. Проверка swap-активности
vmstat 1 5
# swpd: объем swap в использовании
# si/so: swap-in/swap-out в страницах/сек

# 4. Поиск процессов с высоким потреблением памяти
ps aux --sort=-%mem | head -11

# 5. Проверка событий OOM в journal
journalctl -k | grep -i "oom\|killed process"

# 6. Проверка cgroup v2 memory events
cat /sys/fs/cgroup/system.slice/my-app.service/memory.events
# low 0
# high 0
# max 2        ← 2 раза достигался memory.max
# oom 1        ← 1 раз сработал OOM внутри cgroup
# oom_kill 1   ← 1 процесс убит
```

**Решение:**
- Увеличение `memory.max` (limits) или `memory.high` (мягкий лимит) в cgroup.
- Настройка `memory.min` для гарантированной памяти критичным сервисам.
- Профилирование памяти (`valgrind`, `heaptrack`, `go tool pprof`).
- Оптимизация работы с кэшем (настройка `vm.swappiness`, `vfs_cache_pressure`).

### Сценарий 3: Диагностика давления на I/O

**Симптомы:** Высокий `iowait`, медленная работа БД, рост времени ответа API.

```bash
# 1. Проверка PSI I/O
cat /proc/pressure/io
# some avg10=15.30 avg60=10.20 avg300=5.80 total=98765432
# full avg10=8.10 avg60=4.50 avg300=1.20 total=23456789
# → full avg10 > 5%: дисковое подсистема не справляется

# 2. Локализация устройства
iostat -xz 1 5
# await: среднее время ожидания I/O (мс)
# aqu-sz: средний размер очереди
# %util: процент времени, когда устройство обрабатывало запрос

# 3. Поиск процесса-виновника
iotop -oP
# или
pidstat -d 1

# 4. Проверка состояния D-процессов
ps aux | grep ' D '
# → Процессы в Uninterruptible Sleep

# 5. Проверка очереди в cgroup v2
cat /sys/fs/cgroup/system.slice/postgres.service/io.stat
# rbytes=123456789 wbytes=987654321 riops=1200 wiops=800
```

**Решение:**
- Миграция на более быстрые носители (NVMe, SSD).
- Оптимизация паттернов доступа (batch-запросы, уменьшение fsync).
- Настройка I/O sheduler (`mq-deadline` для SSD, `bfq` для десктопов/виртуалок).
- Использование `io.weight` в cgroups для приоритизации I/O критичных сервисов.

### Сценарий 4: Диагностика IRQ-шторма

**Симптомы:** Высокий `si` (softirq) в `top`, потеря пакетов на сетевой карте, прерывания сконцентрированы на одном ядре.

```bash
# 1. Проверка PSI IRQ (ядро 6.1+)
cat /proc/pressure/irq
# some avg10=18.50 avg60=12.30 avg300=8.10 total=87654321

# 2. Анализ прерываний
cat /proc/interrupts
# Концентрация на одном CPU указывает на проблему с affinity

# 3. Проверка балансировщика прерываний
systemctl status irqbalance

# 4. Проверка счетчиков softnet
cat /proc/net/softnet_stat
# Каждая строка = CPU. Третий столбец (packet_dropped) не должен расти.
```

**Решение:**
- Настройка `irqbalance` или ручная привязка прерываний через `/proc/irq/<IRQ>/smp_affinity`.
- Использование RPS (Receive Packet Steering) и RFS (Receive Flow Steering) для распределения сетевой нагрузки.
- Обновление драйвера сетевой карты (часто решает проблемы с прерываниями).
- Отключение прерываний для неиспользуемых устройств (USB, аудио) в BIOS/GRUB (`nousb`, `modprobe.blacklist`).

## Интеграция с инструментами Observability

### atop

Начиная с версии 2.11+, `atop` интегрирован с PSI. Это позволяет видеть не только утилизацию, но и степень голодания процессов:

```bash
# Запуск atop с отображением PSI
atop -P CPU,PRM,DSK

# В интерфейсе atop:
# PRM (Pressure Memory): показывает some/full для памяти
# DSK (Disk): показывает I/O pressure
```

Преимущество `atop` — исторические логи (по умолчанию 28 дней), что позволяет ретроспективно найти момент возникновения давления.

### systemd-oomd

`systemd-oomd` использует PSI для превентивного завершения процессов до срабатывания ядерного OOM Killer:

```ini
# /etc/systemd/oomd.conf
[Service]
# Включить мониторинг
OOMDEnabled=yes

# Порог давления на память (по умолчанию 60%)
DefaultMemoryPressureLimit=60%

# Время удержания порога (по умолчанию 20s)
DefaultMemoryPressureDurationSec=20s

# Исключить критичные сервисы
[Slice:system.slice]
ManagedOnly=yes

[Unit:sshd.service]
ManagedOnly=no
```

Включение и запуск:
```bash
systemctl enable --now systemd-oomd
```

Проверка работы:
```bash
journalctl -u systemd-oomd -f
# → ОOMD применит Kill к cgroup /system.slice/my-app.service
```

## Автоматизация и скрипты

### Мониторинг PSI через cron + алерты

```bash
#!/bin/bash
# /usr/local/bin/check_psi.sh
# Проверка PSI и отправка алерта при превышении порогов

THRESHOLD_CPU=25
THRESHOLD_MEM_FULL=10
THRESHOLD_IO_FULL=20
ALERT_CMD="systemctl send-email --admin"  # или webhook, slack, telegram

check_pressure() {
    local resource=$1
    local threshold=$2
    local avg=$(cat /proc/pressure/$resource 2>/dev/null | awk '/full/ {print $2}' | cut -d= -f2)
    
    if [ -n "$avg" ] && (( $(echo "$avg > $threshold" | bc -l) )); then
        echo "CRITICAL: $resource pressure avg10=${avg}% exceeds threshold ${threshold}%"
        $ALERT_CMD "PSI Alert: $resource pressure=${avg}%"
    fi
}

check_pressure cpu $THRESHOLD_CPU
check_pressure memory $THRESHOLD_MEM_FULL
check_pressure io $THRESHOLD_IO_FULL
```

Добавление в cron (проверка каждые 5 минут):
```bash
*/5 * * * * root /usr/local/bin/check_psi.sh >> /var/log/psi_monitor.log 2>&1
```

### Сбор PSI в цикле нагрузочного тестирования

```bash
#!/bin/bash
# Сбор PSI в фоне во время теста

DURATION=300  # 5 минут
INTERVAL=5    # 5 секунд
OUTPUT="/tmp/psi_collect_$(date +%Y%m%d_%H%M%S).csv"

echo "timestamp,cpu_some,cpu_full,mem_some,mem_full,io_some,io_full" > $OUTPUT

end_time=$((SECONDS + DURATION))
while [ $SECONDS -lt $end_time ]; do
    timestamp=$(date +%s)
    cpu_some=$(awk '/^cpu /{gsub(/some avg10=/,"",$2); split($2,a," "); print a[1]}' /proc/pressure/cpu)
    cpu_full=$(awk '/^cpu /{gsub(/full avg10=/,"",$3); split($3,a," "); print a[1]}' /proc/pressure/cpu)
    mem_some=$(awk '/^some /{gsub(/avg10=/,"",$2); print $2}' /proc/pressure/memory)
    mem_full=$(awk '/^full /{gsub(/avg10=/,"",$2); print $2}' /proc/pressure/memory)
    io_some=$(awk '/^some /{gsub(/avg10=/,"",$2); print $2}' /proc/pressure/io)
    io_full=$(awk '/^full /{gsub(/avg10=/,"",$2); print $2}' /proc/pressure/io)
    
    echo "$timestamp,$cpu_some,$cpu_full,$mem_some,$mem_full,$io_some,$io_full" >> $OUTPUT
    sleep $INTERVAL
done

echo "Collection finished. Output: $OUTPUT"
```

## Практические сценарии

### Настройка уведомлений через триггеры

PSI позволяет пользовательским приложениям получать уведомления в реальном времени при превышении порогов через интерфейс `poll()`/`epoll()`. Это избавляет от необходимости постоянного чтения файлов (polling).

**Формат записи триггера:** `<some|full> <порог_мкс> <окно_мкс>`

Пример на языке C (упрощенно):
```c
int fd = open("/proc/pressure/memory", O_RDWR | O_NONBLOCK);
// Сработать, если задержка 'full' превысит 100мс за 1 секунду:
write(fd, "full 100000 1000000", 20);

// Далее использование в epoll_wait()
```

Пример на Python:
```python
import select

fd = open("/proc/pressure/memory", "w")
fd.write("full 100000 1000000\n")
fd.flush()

epoll = select.epoll()
epoll.register(fd, select.EPOLLPRI)

events = epoll.poll(10)  # timeout 10s
if events:
    fd.seek(0)
    print("Memory pressure threshold exceeded:", fd.read())
```

### Превентивная защита через systemd-oomd

`systemd-oomd` — современный демон, использующий PSI для предотвращения полной блокировки системы (hang). Он убивает группы процессов (cgroups), которые вызывают критическое давление на память, до того, как сработает ядерный OOM Killer.

Настройка в `/etc/systemd/oomd.conf`:
- **`DefaultMemoryPressureLimit=60%`**: Порог, при котором `systemd-oomd` начинает действовать.
- **`DefaultMemoryPressureDurationSec=20s`**: Время, в течение которого давление должно удерживаться выше порога.

### Изоляция в cgroups v2

В cgroups v2 каждая контрольная группа имеет свои файлы `cpu.pressure`, `memory.pressure`, `io.pressure` и (с ядра 6.1) `irq.pressure`. Это позволяет:
- Идентифицировать «шумных соседей» в контейнеризированных средах.
- Ограничивать ресурсы на основе реального времени простоя, а не просто лимитов потребления.

```bash
# Просмотр давления для конкретного контейнера/сервиса
cat /sys/fs/cgroup/system.slice/nginx.service/memory.pressure
# Проверка давления прерываний для группы
cat /sys/fs/cgroup/system.slice/nginx.service/irq.pressure
```

### Диагностика IRQ-штормов

Если `avg10` в `/proc/pressure/irq` растет выше 10–15%, это признак того, что система тратит слишком много времени на обработку прерываний.
- **Причина:** Высокая сетевая нагрузка (PPS), некорректная привязка (affinity) прерываний сетевых карт, проблемы с драйверами.
- **Решение:** Проверка `/proc/interrupts`, использование `irqbalance` или ручная привязка прерываний к конкретным ядрам.

## Типичные ошибки и ограничения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **PSI не отображается** | Ядро собрано без `CONFIG_PSI` или параметр `psi=0` | Проверка: `grep CONFIG_PSI /boot/config-$(uname -r)`, добавление `psi=1` в GRUB |
| **Отсутствует `irq.pressure`** | Ядро < 6.1 или `CONFIG_IRQ_TIME_ACCOUNTING` не включен | Обновление ядра или пересборка с включенным параметром |
| **Полные значения всегда 0** | Нет реального насыщения системы (или окно усреднения слишком велико) | Уменьшение интервала опроса или проведение нагрузочного теста |
| **Высокий `full` при наличии свободной RAM** | Активный reclaim (кэш) или page fault из-за фрагментации | Проверка `vmstat` (si/so), настройка `vm.vfs_cache_pressure` |
| **PSI в контейнере показывает 0** | Контейнер запущен без доступа к cgroup namespace или PSI отключен на хосте | Проверка монтирования cgroupfs внутри контейнера |

## Дополнительная информация

### Связанные темы

- **cgroups v2:** [Control Groups](../cgroups.md) — глубокая интеграция PSI на уровне групп ресурсов.
- **OOM Killer:** [Механизмы OOM](../processes/oom_killer_management.md) — как PSI помогает предотвращать критическую нехватку памяти.
- **MGLRU:** [Multi-Gen LRU](../memory/swap_diagnostics.md) — новый алгоритм управления страницами, работающий в связке с PSI.
- **Диагностика:** [Анализ задержек (Tail Latency)](../../Diagnostics/Performance/diagnosing_tail_latency.md) — использование PSI для поиска причин микро-задержек.
- **Мониторинг:** [Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) — USE методология и место PSI в ней.
- **Планирование ресурсов:** [Capacity Planning](../../Concepts/capacity-planning.md) — PSI для оценки реального насыщения инфраструктуры.
- **atop:** [Advanced System Monitor](../../Diagnostics/Performance/atop.md) — интеграция atop с PSI для исторического анализа.
- **Зависания ядра:** [Soft/Hard Lockup и Hung Task](../kernel/lockups.md) — как отличить I/O задержки от зависаний через PSI.

### Полезные ссылки
- [Официальная документация ядра Linux (PSI)](https://www.kernel.org/doc/html/latest/accounting/psi.html)
- [Статья Facebook: PSI — Pressure Stall Information](https://facebookmicrosites.github.io/psi/) (разработчики механизма)
