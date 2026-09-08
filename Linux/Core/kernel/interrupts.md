# Прерывания в ядре Linux

## Определения

**Прерывание (Interrupt)** — сигнал от аппаратного или программного обеспечения, требующий немедленного внимания процессора. При получении прерывания процессор приостанавливает текущий поток выполнения и переходит к **обработчику прерывания (ISR — Interrupt Service Routine)**.

**IRQ (Interrupt Request)** — логический идентификатор линии прерывания. В современных архитектурах физические линии заменены на механизмы доставки сообщений через шину (MSI).

**Вектор прерывания (Interrupt Vector)** — числовой идентификатор, который процессор использует для индексации в таблице дескрипторов прерываний (IDT) и перехода к соответствующему обработчику.

**Основные типы прерываний:**
- **Аппаратные (Hardware Interrupts):** Генерируются устройствами (NIC, NVMe, клавиатура).
- **Программные (Software Interrupts / Exceptions):** Генерируются процессором при ошибках (Divide by zero, Page Fault) или через инструкции (системные вызовы).
- **Межпроцессорные (IPI — Inter-Processor Interrupts):** Механизм, с помощью которого одно ядро CPU уведомляет другое о необходимости выполнения действия (например, очистка TLB или планирование задачи).

## Архитектура и механизмы

### Многоуровневая обработка (Split Handling)

Для предотвращения блокировки системы и минимизации задержек ядро Linux разделяет обработку прерывания на фазы:

#### 1. Аппаратная фаза (Hard IRQ / Top Half)
- **Контекст:** Атомарный контекст прерывания (Interrupt Context). Прерывает выполнение любого кода на CPU.
- **Задача:** Минимальные действия: квитирование (ACK) прерывания на контроллере, чтение статуса устройства, постановка задачи в очередь Bottom Half.
- **Особенности:** На время работы Hard IRQ другие прерывания на данном ядре маскируются. Длительная обработка приводит к потере событий.

#### 2. Программная фаза (SoftIRQ / Bottom Half)
- **Контекст:** Атомарный контекст прерывания, но с включенными аппаратными прерываниями.
- **Механизмы:**
  - **SoftIRQ:** Набор из 10 статически определенных высокоприоритетных обработчиков (HI, TIMER, NET_TX, NET_RX, BLOCK, IRQ_POLL, TASKLET, SCHED, HRTIMER, RCU).
  - **Tasklets:** Построены поверх SoftIRQ. Постепенно выводятся из употребления (**deprecated** в ядрах 6.x+) в пользу потоковых прерываний.

#### 3. Потоковая фаза (Threaded IRQs)
- **Контекст:** Контекст процесса (Process Context). Поток ядра `irq/N-name` или `ksoftirqd/N`.
- **Задача:** Тяжелая обработка данных. Потоки могут вытесняться планировщиком и иметь собственные приоритеты (RT).
- **ksoftirqd:** Процесс ядра, который активируется, если SoftIRQ на ядре выполняется слишком долго или слишком часто.

### Контроллеры прерываний

#### Наследственные (Legacy) прерывания
- **IO-APIC (I/O Advanced Programmable Interrupt Controller):** Стандартный контроллер для систем x86. Каждому устройству назначается номер IRQ (0–23). Ограниченное количество линий — критично для многопроцессорных систем.
- **Local APIC:** Встроен в каждое ядро CPU. Отвечает за прием и распределение прерываний внутри процессора, а также за генерацию IPI.
- **PIC (Programmable Interrupt Controller):** Устаревший контроллер (AT/XT), используется только в виртуальных машинах без IO-APIC.

#### Современные механизмы доставки
- **MSI (Message Signaled Interrupts):** Устройство генерирует прерывание, записывая специальное значение в адресное пространство PCI. Преимущества: отсутствие конфликтов линий, меньше задержек, масштабируемость.
- **MSI-X (Message Signaled Interrupts Extended):** Расширение MSI, позволяющее каждому устройству иметь до 2048 независимых векторов прерываний. Каждая очередь устройства (RX/TX в NIC) может иметь собственный прерывание, что является основой для RSS.
- **IMS (Interrupt Message Store):** Технология, позволяющая устройствам создавать десятки тысяч векторов прерываний, обходя аппаратные ограничения PCI-таблиц (2048 векторов). Это база для **SIOV** (Scalable I/O Virtualization).

### Прерывания в архитектуре NUMA

В системах с несколькими процессорами критически важно учитывать топологию NUMA:
- Прерывания должны привязываться к ядрам той же NUMA-ноды, к которой подключена шина PCIe устройства.
- Обращение к памяти через QPI/UPI шину между сокетами увеличивает задержки на 50–200%.
- Для проверки соответствия: `cat /sys/bus/pci/devices/0000:03:00.0/numa_node`

### Перераспределение прерываний (Interrupt Remapping)

В системах с виртуализацией (Intel VT-d, AMD-Vi) существует таблица перераспределения (Interrupt Remapping Table — IRT), которая позволяет:
- Перенаправлять прерывания от устройства к виртуальному процессору (vCPU) в гипервизоре.
- Обеспечивать изоляцию прерываний между виртуальными машинами.
- Поддерживатьposted interrupts — доставку прерываний напрямую в ядро виртуальной машины без участия гипервизора.

Проверка поддержки:
```bash
# Intel VT-d
dmesg | grep -i "remapping"
# → DMAR: Intel(R) Virtualization Technology for Directed I/O

# AMD-Vi
dmesg | grep -i "amd.*iommu"
```

### Эволюция интерфейсов (2024–2026)

*   **Intel FRED (Flexible Return and Event Delivery):** Доступно в ядрах 7.x+. Заменяет устаревшую таблицу IDT. FRED ускоряет переход между Ring 3 и Ring 0, атомарно сохраняя контекст и повышая безопасность (защита от атак через переходные состояния).
*   **MSI-X и IMS (Interrupt Message Store):** IMS позволяет устройствам (GPU, SmartNIC) создавать десятки тысяч векторов прерываний, обходя аппаратные ограничения PCI-таблиц (2048 векторов). Это база для **SIOV** (Scalable I/O Virtualization).
*   **Threaded NAPI Busy Polling:** Сочетание потоковой обработки сетевых пакетов с «активным опросом» (busy poll) позволяет достичь задержек уровня DPDK без полной изоляции ядер.

## Практические сценарии

### Диагностика прерываний

```bash
# Просмотр статистики аппаратных прерываний по ядрам
cat /proc/interrupts | head -n 5
# →            CPU0       CPU1       
# →   0:         10          0   IO-APIC   2-edge      timer

# Просмотр программных прерываний
cat /proc/softirqs | grep NET_RX
# → NET_RX:    152432     284910

# Мониторинг загрузки ядер в режиме SoftIRQ
top -bn1 | grep "%Cpu"
# → %Cpu0  :  0.3 us,  2.0 sy,  0.0 ni, 85.0 id,  0.0 wa,  12.7 si
# (Поле 'si' показывает время, затраченное на SoftIRQ)

# Поиск прерываний с наибольшей нагрузкой
cat /proc/interrupts | awk '{print $1, $2+$3+$4+$5+$6+$7+$8+$9+$10+$11+$12+$13+$14+$15+$16+$17}' | sort -k2 -n -r | head -n 10
# → 42:  152341  (eth0)
# → 43:  98234   (nvme0q1)

# Проверка по умолчанию affinity (что принимает все нераспределенные IRQ)
cat /proc/irq/default_smp_affinity
# → f (все ядра)
```

### Управление привязкой (IRQ Affinity)

Для высоконагруженных систем (СУБД, шлюзы) важно привязать прерывания к конкретным ядрам, исключая переключения контекста.

```bash
# Найти IRQ сетевой карты
cat /proc/interrupts | grep eth0
# →  42: ... PCI-MSI 1572864-edge      eth0

# Привязать к ядру 0 (маска 1)
echo 1 | sudo tee /proc/irq/42/smp_affinity
# → 1

# Проверка привязки (списком)
cat /proc/irq/42/smp_affinity_list
# → 0

# Привязка к нескольким ядрам (списком)
echo 0-3 | sudo tee /proc/irq/42/smp_affinity_list
# → 0-3

# Привязка к нескольким ядрам (hex маской)
echo f | sudo tee /proc/irq/42/smp_affinity
# → f
```
*Примечание: Перед ручной настройкой отключите `irqbalance` (`systemctl stop irqbalance`).*

#### NUMA-осознанная привязка

Привязка прерываний к ядрам той же NUMA-ноды, что и устройство:

```bash
# Определить NUMA-ноду устройства
cat /sys/bus/pci/devices/0000:03:00.0/numa_node
# → 0

# Получить список ядер NUMA-ноды 0
lscpu | grep "NUMA node0"
# → NUMA node0 CPU(s): 0-7

# Привязать все прерывания устройства к ядрам NUMA-ноды 0
for irq in $(grep -E "0000:03:00" /proc/interrupts | awk '{print $1}' | tr -d ':'); do
    echo 00ff | sudo tee /proc/irq/$irq/smp_affinity
done
```

### Диагностика сетевых переполнений (Softnet)

Если `ksoftirqd` не успевает обрабатывать пакеты, они отбрасываются в очереди backlog.

```bash
cat /proc/net/softnet_stat
# → 0005a123 00000000 00000012 ...
# (Первая колонка - получено пакетов, вторая - отброшено по лимиту, 
# третья - количество раз, когда обработка заняла слишком много времени)

# Строки softnet_stat:
# Колонка 1 (total): общее количество полученных пакетов
# Колонка 2 (drop): количество отброшенных пакетов (переполнение backlog)
# Колонка 3 (time_squeeze): количество раз, когда обработчик был остановлен из-за нехватки времени в budget
# Колонка 4 (cpu_collisions): количество коллизий при доступе к очередям ( contention )
# Колонка 5 (flownoise): счетчик "шума" потоков (отслеживание RPS/RFS)
# Колонка 6 (rps_success): количество пакетов, успешно перераспределенных через RPS
```

### Мониторинг давления прерываний (PSI)

С ядра 6.1+ доступны метрики давления прерываний через PSI:

```bash
# Проверка давления прерываний
cat /proc/pressure/irq
# → some avg10=18.50 avg60=12.30 avg300=8.10 total=87654321

# avg10=18.50 означает, что за последние 10 секунд система тратила 18.5% времени на обработку прерываний
# Пороги для алертов: avg10 > 10-15% — возможен IRQ-шторм
```
Подробное руководство: [**Pressure Stall Information**](./psi.md).

### Диагностика IRQ-шторма

**Симптомы:** Высокий `si` (softirq) в `top`, потеря пакетов на сетевой карте, прерывания сконцентрированы на одном ядре, высокий Load Average при низком `%CPU`.

```bash
# 1. Проверка PSI IRQ (ядро 6.1+)
cat /proc/pressure/irq
# some avg10=18.50 avg60=12.30 avg300=8.10 total=87654321

# 2. Анализ прерываний
cat /proc/interrupts
# Концентрация на одном CPU указывает на проблему с affinity

# 3. Проверка балансировщика прерываний
systemctl status irqbalance
# → active (running) или inactive (dead)

# 4. Проверка счетчиков softnet
cat /proc/net/softnet_stat | awk '$2 > 0 || $3 > 0'
# → Строки с ненулевыми значениями во 2-й или 3-й колонке

# 5. Поиск конкретного устройства-виновника
# Сопоставление PCI-адреса с прерываниями
lspci -nn | grep Ethernet
# → 03:00.0 Ethernet controller [0200]: Intel Corporation Ethernet Controller X710

# Поиск прерываний для этого устройства
grep 0000:03:00 /proc/interrupts
# →  42: ... PCI-MSI 1572864-edge      eth0
# →  43: ... PCI-MSI 1572864-edge      eth0

# 6. Мониторинг в реальном времени
watch -n 1 'cat /proc/interrupts | grep -E "CPU|eth0|nvme"'
```

**Решение:**
- Настройка `irqbalance` или ручная привязка прерываний через `/proc/irq/<IRQ>/smp_affinity`.
- Использование RPS (Receive Packet Steering) и RFS (Receive Flow Steering) для распределения сетевой нагрузки. См. [**RSS, RPS, RFS**](../../Networking/Concepts/rss_rps_rfs.md).
- Обновление драйвера сетевой карты (часто решает проблемы с прерываниями).
- Отключение прерываний для неиспользуемых устройств (USB, аудио) в BIOS/GRUB (`nousb`, `modprobe.blacklist`).
- Настройка interrupt coalescing через `ethtool` (см. [**ethtool**](../../Networking/Tools/ethtool.md)).

### Настройка coalescing (сглаживания прерываний)

Для сетевых карт и дисковых контроллеров можно настроить coalescing — объединение нескольких событий в одно прерывание, снижая частоту прерываний:

```bash
# Просмотр текущих параметров coalescing
sudo ethtool -c eth0
# → rx-usecs: 123
# → rx-frames: 0

# Установка coalescing: прерывание раз в 100 мкс или при приеме 16 пакетов
sudo ethtool -C eth0 rx-usecs 100 rx-frames 16

# Проверка результата
sudo ethtool -c eth0
```

*Важно:* Слишком агрессивный coalescing увеличивает задержки. Для latency-sensitive workloads (трейдинг, базы данных) используйте минимальные значения или отключите coalescing (`rx-usecs 0`).

### Подавление ksoftirqd и управление потоками

ksoftirqd — процесс ядра, который активируется при перегрузке SoftIRQ. Его высокая загрузка (`si` в `top`) указывает на проблемы:

```bash
# Проверка, какие ksoftirqd загружены
ps aux | grep ksoftirqd
# → root      ksoftirqd/1   0.0  0.0      0    0 ?        S    16:45   0:00 [ksoftirqd/1]

# Проверка приоритета ksoftirqd (по умолчанию 0)
sudo chrt -p $(pgrep -f ksoftirqd/1)
# → pid 12's current scheduling policy: SCHED_OTHER
# → pid 12's current nice priority: 0

# Подавление прерываний на конкретных ядрах
# Перенос всех нераспределенных IRQ на ядра 0-1 (housekeeping)
echo 3 | sudo tee /proc/irq/default_smp_affinity
# → 3

# Запуск ядра с параметром threadirqs позволяет управлять приоритетами обработчиков
# через chrt (в /etc/default/grub)
# GRUB_CMDLINE_LINUX_DEFAULT="... threadirqs"
```
Подробнее: [**Изоляция CPU**](./cpu_isolation.md).

### Настройка irqbalance

`irqbalance` — демон, автоматически распределяющий прерывания между ядрами:

```bash
# Проверка статуса
systemctl status irqbalance

# Конфигурация (/etc/default/irqbalance)
# IRQBALANCE_ARGS="--banirq=42 --banirq=43"
# Запрещает балансировку для конкретных IRQ (например, для высоконагруженной сетевой карты)

# Проверка активных исключений
cat /etc/default/irqbalance | grep BANIRQ
# → IRQBALANCE_BANNED_CPUS=3 (прерывания не будут попадать на CPU3)
```

### Диагностика через perf и ftrace

Для глубокой отладки задержек, вызванных прерываниями:

```bash
# Запись трассировки прерываний в течение 10 секунд
sudo perf record -e irq:irq_handler_entry -e irq:irq_handler_exit -a sleep 10

# Анализ: какие IRQ занимают больше всего времени
sudo perf report

# Анализ задержек через ftrace
echo 1 | sudo tee /sys/kernel/debug/tracing/events/irq/irq_handler_entry/enable
echo 1 | sudo tee /sys/kernel/debug/tracing/events/irq/irq_handler_exit/enable
cat /sys/kernel/debug/tracing/trace_pipe | head -n 20

# Остановка трассировки
echo 0 | sudo tee /sys/kernel/debug/tracing/events/irq/irq_handler_entry/enable
echo 0 | sudo tee /sys/kernel/debug/tracing/events/irq/irq_handler_exit/enable
```

### Мониторинг через bpftrace

```bash
# bpftrace: счетчик прерываний по IRQ
sudo bpftrace -e 'tracepoint:irq:irq_handler_entry { @irqs[args->irq] = count(); }'

# bpftrace: замер длительности обработчиков прерываний
sudo bpftrace -e 'tracepoint:irq:irq_handler_entry /args->irq == 42/ { @start[tid] = nsecs; }
                  tracepoint:irq:irq_handler_exit /@start[tid]/ { @latency[args->irq] = hist((nsecs - @start[tid]) / 1000); delete(@start[tid]); }'
```

### Распространенные сценарии аварийного восстановления

#### Сценарий 1: Система не отвечает (возможный soft lockup)

```bash
# Попытка получить трассу через sysrq
echo t > /proc/sysrq-trigger  # Вывод трассы всех задач
echo b > /proc/sysrq-trigger  # Немедленная перезагрузка
```

#### Сценарий 2: IRQ-шторм после подключения устройства

```bash
# 1. Определить виновника
cat /proc/interrupts | sort -n -k2 -r | head -n 5

# 2. Временно отключить прерывания для устройства
echo 1 | sudo tee /proc/irq/42/smp_affinity  # Привязка к одному ядру
# или полностью заблокировать прерывания через загрузочный параметр noirq

# 3. Перезагрузка или переподключение устройства (если возможно)
echo -n "0000:03:00.0" | sudo tee /sys/bus/pci/drivers/*/unbind
sleep 2
echo -n "0000:03:00.0" | sudo tee /sys/bus/pci/drivers/*/bind
```

#### Сценарий 3: Высокий si% при отсутствии видимой сетевой активности

```bash
# 1. Проверить прерывания таймера (они всегда высоки)
cat /proc/interrupts | grep -i timer

# 2. Проверить SMI (System Management Interrupts) — не видны напрямую, но влияют на si%
# SMI вызываются BIOS/EC для управления питанием, термоинтерфейсами
# Диагностика: моделирование нагрузки на idle CPU
sudo perf stat -e intel_msr/msr/irq_count/ sleep 5

# 3. Отключение ненужных контроллеров в BIOS
# (USB Legacy, Serial Port, Parallel Port)
```

### Настройка для виртуализации (KVM/QEMU)

```bash
# Включение posted interrupts для виртуальной машины
# В конфигурации libvirt XML:
# <features>
#   <apic/>
#   <msi/>
#   <msi vectors='32'/>
# </features>

# Проверка, что виртуальная машина получает MSI
# Внутри VM:
dmesg | grep -i "msi\|irq"
# → Intel(R) I/OAT DMA engine 0000:00:04.0: using MSI interrupts
```

## Дополнительная информация

### Связанные темы

- **Сетевой стек:** [RSS, RPS, RFS](../../Networking/Concepts/rss_rps_rfs.md) — балансировка трафика и диагностика SoftIRQ.
- **Оптимизация:** [Изоляция CPU](./cpu_isolation.md) — перенос прерываний с выделенных ядер, подавление ksoftirqd.
- **Синхронизация:** [Механизмы синхронизации в ядре](./kernel_synchronization.md) — Spinlocks и контекст прерывания.
- **Производительность:** [ethtool](../../Networking/Tools/ethtool.md) — настройка Interrupt Coalescing.
- **Реальное время:** [Kernel Preemption](./preemption.md) — влияние PREEMPT_RT на обработку прерываний.
- **Наблюдаемость:** [Pressure Stall Information](./psi.md) — мониторинг давления IRQ через `/proc/pressure/irq`.
- **Пinning:** [CPU Pinning](../cpu_pinning.md) — привязка процессов и NUMA-оптимизация.
- **Общий контекст:** [Ядро Linux: Обзор](./overview.md) — где обработка прерываний в общей архитектуре ядра.
