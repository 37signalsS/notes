# Оптимизация NAPI и netdev_budget в Linux

## Определения

**NAPI (New API)** — механизм сетевой подсистемы ядра Linux, предназначенный для адаптивной обработки входящих пакетов. Он комбинирует режимы прерываний (Interrupts) и активного опроса (Polling), чтобы минимизировать нагрузку на CPU при высоком сетевом трафике (Interrupt Storm).

**Interrupt Storm (Шторм прерываний)** — состояние, при котором NIC генерирует прерывание на каждый входящий пакет. При скорости 10 Gbps и пакетах по 64 байта это ~148 000 прерываний в секунду на одно ядро, что полностью загружает CPU обработкой прерываний, не оставляя времени для приложений.

**SoftIRQ / NET_RX** — программный контекст прерывания (Bottom Half), в котором выполняется основная часть сетевой обработки (включая NAPI). Для сетевого приема используется обработчик `NET_RX`. Если SoftIRQ выполняется слишком долго, ядро активирует поток `ksoftirqd/N` для отложенной обработки.

**ksoftirqd** — поток ядра, который активируется, когда обработка SoftIRQ на данном ядре превышает порог времени (обычно ~2 мс на burst). Высокая загрузка `ksoftirqd` в `top` (поле `si`) указывает на нехватку ресурсов для сетевой обработки.

**netdev_budget** — глобальный параметр ядра, определяющий максимальное количество пакетов, которое все сетевые интерфейсы могут обработать в рамках одного цикла SoftIRQ/NAPI. Дефолт: 300 пакетов.

**netdev_budget_per_cpu** — параметр ядра (ядро 4.20+), ограничивающий количество пакетов, которые одно ядро может обработать за цикл NAPI. Дефолт: 300 (равен `netdev_budget`). Позволяет предотвратить голодание одного ядра при обработке трафика всех интерфейсов.

**netdev_max_backlog** — размер глобальной очереди пакетов, ожидающих обработки SoftIRQ. Если NIC генерирует пакеты быстрее, чем ядро забирает их через NAPI, пакеты помещаются в backlog. При переполнении происходит drop (второй столбец `softnet_stat`). Дефолт: 1000.

**Threaded NAPI** — механизм (введен в ядре 5.12+), позволяющий перенести обработку сетевых пакетов из контекста `softirq` в выделенные потоки ядра (`napi/ifname-N`). Это обеспечивает лучшую изоляцию и возможность приоритизации сетевого трафика через `chrt`.

**Busy Polling** — режим активного ожидания пакетов приложением (через сокеты с флагами `SO_BUSY_POLL` / `SO_BUSY_READ`), позволяющий исключить задержки на переключение контекста и обработку прерываний за счет загрузки одного ядра CPU на 100%.

**GRO Flush Timeout** — таймаут в микросекундах, по истечении которого агрегированные пакеты GRO передаются стеку, даже если размер агрегата не достиг максимума. Позволяет балансировать междуlatency и throughput.

**NAPI Defer (`napi_defer_hard_irqs`)** — счетчик "пустых" циклов NAPI, в течение которых ядро остается в режиме опроса даже при отсутствии пакетов, чтобы избежать шторма прерываний при "рваном" трафике.

**Ring Buffer (RX-ring)** — аппаратная кольцевая очередь в памяти NIC, в которую DMA записывает входящие пакеты. NAPI опрашивает этот буфер. При переполнении NIC отбрасывает пакеты — счетчики `rx_missed_errors` / `rx_fifo_errors`.

**XDP (eXpress Data Path)** — фреймворк eBPF, выполняющий программы на самом раннем этапе в драйвере NIC, **до** помещения пакета в Ring Buffer и **до** вызова NAPI. XDP_DROP / XDP_REDIRECT работают без участия NAPI.

**AF_XDP** — адресное семейство сокетов, позволяющее передавать пакеты из драйвера напрямую в userspace, минуя сетевой стек и NAPI. Используется в DPDK-подобных сценариях с низкими задержками.

**napi_weight** — внутренний параметр драйвера, определяющий бюджет обработки пакетов для одного NAPI-instance (одной RX-очереди). В современных драйверах обычно равен 64 или 128 пакетов на вызов `napi_poll`. В отличие от `netdev_budget`, это per-queue значение.

**Interrupt Coalescing (Коалесценция прерываний)** — механизм NIC, при котором карта накапливает несколько пакетов перед генерацией прерывания. Взаимодействует с NAPI: коалесценция работает на уровне прерываний, NAPI — на уровне обработки пакетов после прерывания.

---

## Базовые концепции

### История и мотивация создания NAPI

В эпоху 10/100 Мбит/с сетей стандартный обработчик прерываний (one-interrupt-per-packet) работал нормально: NIC редко генерировал больше нескольких тысяч прерываний в секунду. С появлением 1 Gbps+ интерфейсов количество пакетов в секунду возросло до десятков и сотен тысяч:

- 1 Gbps, пакеты по 64 байта: ~1.8 Mpps
- 10 Gbps, пакеты по 64 байта: ~14.8 Mpps
- 100 Gbps, пакеты по 64 байта: ~148.0 Mpps

При 14.8 Mpps на ядро CPU тратится почти 100% времени на обработку прерываний, не оставляя ресурсов для приложений. Это явление получило название **Interrupt Storm**.

**NAPI был разработан для решения этой проблемы:** вместо прерывания на каждый пакет NIC генерирует одно прерывание, после чего ядро переключается в режим опроса (polling), обрабатывая пакеты пачками.

### Цикл обработки NAPI

Когда сетевая карта (NIC) получает пакеты, она генерирует прерывание. Ядро переводит интерфейс в режим опроса:

1.  Драйвер отключает аппаратные прерывания для данной очереди (или повышает порог коалесценции).
2.  Ядро запускает цикл NAPI (`napi_poll`), который забирает пакеты из кольцевого буфера (Ring Buffer) пачками.
3.  Если пакеты закончились или исчерпан **бюджет** — цикл завершается, и прерывания включаются снова.

**Ключевое отличие от классического обработчика:** NAPI работает в контексте SoftIRQ (атомарный контекст с включенными прерываниями), но не в контексте процесса. Это означает, что во время NAPI-цикла прерывания других устройств не блокируются, но планировщик не может переключить CPU на другой процесс.

### Бюджет и временные кванты

Обработка ограничивается двумя глобальными параметрами `sysctl` и одним per-cpu:

*   `net.core.netdev_budget` — глобальный лимит пакетов на все интерфейсы за один SoftIRQ-цикл. Дефолт: 300.
*   `net.core.netdev_budget_usecs` — лимит времени в микросекундах на цикл. Дефолт: 2000 (2 мс).
*   `net.core.netdev_budget_per_cpu` — лимит пакетов на одно ядро. Дефолт: 300. Ядро 4.20+.

**Валидация текущих значений:**
```bash
sysctl net.core.netdev_budget net.core.netdev_budget_usecs net.core.netdev_budget_per_cpu
# → net.core.netdev_budget = 300
# → net.core.netdev_budget_usecs = 2000
# → net.core.netdev_budget_per_cpu = 300
```

**Риски разбалансировки:**
*   **Низкий бюджет:** Высокие задержки (Latency) и потери, так как пакеты долго ждут в очередях. Рост третьего столбца `softnet_stat` (squeezed).
*   **Высокий бюджет:** «Голодание» (Starvation) других процессов на CPU, так как ядро слишком долго занято сетевой обработкой (SoftIRQ). Рост поля `si` в `top`.
*   **Очень высокий budget_usecs:** Длительные блокировки CPU в атомарном контексте, рост задержек всех процессов.

### Современные механизмы управления (2025–2026)

В современных ядрах (6.x+) фокус сместился с подавления прерываний на их предсказуемое планирование:

*   **NAPI Defer (`napi_defer_hard_irqs`):** Позволяет NAPI оставаться в режиме опроса даже при отсутствии пакетов на короткое время, чтобы избежать шторма прерываний при «рваном» трафике.
*   **GRO Flush Timeout (`gro_flush_timeout`):** Задержка перед передачей пакетов стеку для их более эффективного объединения (Generic Receive Offload).
*   **Threaded NAPI (Kernel 5.12+):** Вынос обработки в потоки с приоритетами реального времени.

### Взаимодействие с прерываниями и коалесценцией

Прерывания и NAPI работают на разных уровнях:

1.  **Hard IRQ (Top Half):** NIC генерирует прерывание → драйвер квитирует → планирует NAPI-poll. Сама обработка пакетов здесь не происходит.
2.  **Interrupt Coalescing:** NIC накапливает пакеты перед генерацией прерывания. Управляется через `ethtool -C`. Чем больше `rx-usecs`/`rx-frames`, тем меньше прерываний, но выше latency.
3.  **NAPI Poll (SoftIRQ):** Ядро опрашивает Ring Buffer, обрабатывает пачку пакетов. Работает поверх коалесценции.

**Взаимодействие с XDP/AF_XDP:**
- **XDP** выполняется в драйвере **до** Ring Buffer и NAPI. XDP_DROP отбрасывает пакеты без участия NAPI, что позволяет достичь 100Mpps+ на одном ядре.
- **AF_XDP** позволяет передавать пакеты из драйвера в userspace без NAPI и сетевого стека. Критично для high-frequency trading и DDoS-защиты.

### Взаимодействие с GRO/GSO

GRO и NAPI тесно связаны: GRO работает в контексте NAPI, агрегируя пакеты пачками (budget). Если budget исчерпан, остальные пакеты остаются в RX-ring, что приводит к `rx_missed_errors`.

GSO (Generic Segmentation Offload) работает на передаче (TX) и не взаимодействует с NAPI напрямую.

### Потребители памяти и pressure

При высокой нагрузке NAPI активно выделяет структуры `sk_buff` (SKB). Если память ограничена:
- `napi_alloc_skb` может возвращать `NULL`
- Драйвер отбрасывает пакеты с ошибкой `ENOMEM`
- Мониторинг: `dmesg | grep -i "napi"` или `cat /proc/net/dev`

### Per-queue NAPI

Каждой RX-очереди NIC соответствует отдельный экземпляр NAPI (`napi/ifname-N`). Это означает:
- Budget применяется per-queue, а не per-interface
- При использовании RSS/RPS каждый поток NAPI привязан к своей очереди
- Включение Threaded NAPI создает отдельный поток для каждой очереди

**Валидация:**
```bash
ls /sys/class/net/eth0/device/msi_irqs/
# → 0  1  2  3  4  5  6  7  (8 MSI-X прерываний для 8 очередей)

cat /proc/interrupts | grep eth0
# → 107:  1234567  0  0  0  IR-PCI-MSI  eth0-rx-0
# → 108:  2345678  0  0  0  IR-PCI-MSI  eth0-rx-1
```

---

## Практические сценарии

### Шаг 1: Диагностика через softnet_stat

Анализ статистики `/proc/net/softnet_stat` позволяет выявить проблемы планирования:

```bash
cat /proc/net/softnet_stat
# Пример вывода (3-я колонка — squeezed):
# 000a1234 00000000 00000015 ...
# 000b5678 00000002 0000000a ...
```

*   **1-я колонка (total):** Всего обработанных пакетов.
*   **2-я колонка (dropped):** Дропы из-за переполнения `netdev_max_backlog`.
*   **3-я колонка (squeezed/time_squeeze):** Количество раз, когда NAPI завершил цикл по бюджету или времени, не успев обработать все пакеты. Если это число растет — нужно увеличивать бюджет.

**Валидация:**
```bash
awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc
# → 0 (должно быть 0 или близко к 0)

awk '{print $3}' /proc/net/softnet_stat | paste -sd+ | bc
# → 0 (должно быть 0 или близко к 0 при правильном бюджете)
```

### Шаг 2: Тюнинг бюджета для 10G/40G/100G+ сетей

Для высокоскоростных интерфейсов стандартных 300 пакетов недостаточно:

```bash
# Увеличение бюджета до 600-1000 пакетов
sudo sysctl -w net.core.netdev_budget=600
# → net.core.netdev_budget = 600

# Увеличение временного кванта (актуально для GRO)
sudo sysctl -w net.core.netdev_budget_usecs=4000
# → net.core.netdev_budget_usecs = 4000

# Увеличение backlog-очереди
sudo sysctl -w net.core.netdev_max_backlog=5000
# → net.core.netdev_max_backlog = 5000
```

**Валидация:**
```bash
cat /proc/net/softnet_stat | awk '{print $3}' | paste -sd+ | bc
# → 0 (squeezed должен уменьшиться)
```

### Шаг 3: Настройка Threaded NAPI (Kernel 5.12+)

Позволяет вынести обработку из SoftIRQ в потоки, которые можно привязать к конкретным ядрам и настроить приоритеты:

```bash
# Проверка поддержки Threaded NAPI
cat /sys/class/net/eth0/threaded
# → 0 (не включен) или 1 (включен)

# Включение режима для конкретного интерфейса
echo 1 | sudo tee /sys/class/net/eth0/threaded
# → 1

# Поиск потоков NAPI
ps -ef | grep napi
# napi/eth0-0  root  1234  1  0 12:00 ?  00:00:00 [napi/eth0-0]
# napi/eth0-1  root  1235  1  0 12:00 ?  00:00:00 [napi/eth0-1]

# Привязка потока к CPU (CPU Affinity)
sudo taskset -pc 1 1234
# → pid 1234's current affinity mask: 1
# → pid 1234's new affinity mask: 1
```

**Валидация:**
```bash
# Проверка affinity
taskset -pc 1234
# → pid 1234's current affinity mask: 1

# Проверка приоритета (должен быть выше обычных процессов)
chrt -p 1234
# → pid 1234's current scheduling policy: SCHED_OTHER
# → pid 1234's priority: 0
```

### Шаг 4: Борьба с микро-паузами (NAPI Defer)

Если трафик идет мелкими пачками, что вызывает постоянные переключения между Polling и Interrupts:

```bash
# Оставаться в режиме опроса 10 циклов "вхолостую"
echo 10 | sudo tee /sys/class/net/eth0/napi_defer_hard_irqs
# → 10

# Установка таймаута GRO в 20 мкс для лучшего агрегирования
echo 20000 | sudo tee /sys/class/net/eth0/gro_flush_timeout
# → 20000
```

**Валидация:**
```bash
cat /sys/class/net/eth0/napi_defer_hard_irqs
# → 10

cat /sys/class/net/eth0/gro_flush_timeout
# → 20000
```

### Шаг 5: Оптимизация Low Latency (Busy Poll)

Для приложений, критичных к задержкам (Redis, биржевое ПО), используйте активный опрос:

```bash
# Глобальное время ожидания Busy Poll (в мкс)
sudo sysctl -w net.core.busy_poll=50
# → net.core.busy_poll = 50

sudo sysctl -w net.core.busy_read=50
# → net.core.busy_read = 50
```

**Валидация:**
```bash
sysctl net.core.busy_poll net.core.busy_read
# → net.core.busy_poll = 50
# → net.core.busy_read = 50
```

**В коде приложения (C):**
```c
int flags = SO_BUSY_POLL | SO_BUSY_READ;
int busy_us = 50; // мкс
setsockopt(fd, SOL_SOCKET, SO_BUSY_POLL, &busy_us, sizeof(busy_us));
setsockopt(fd, SOL_SOCKET, SO_BUSY_READ, &busy_us, sizeof(busy_us));
```

### Шаг 6: Настройка Interrupt Coalescing через ethtool

Коалесценция работает на уровне прерываний и дополняет NAPI:

```bash
# Просмотр текущих настроек коалесценции
ethtool -c eth0
# Coalesce parameters for eth0:
#   Adaptive RX: on  TX: on
#   rx-usecs: 3
#   rx-frames: 1
#   rx-usecs-irq: 3
#   rx-frames-irq: 1

# Ручная настройка для low-latency (50 мкс)
sudo ethtool -C eth0 rx-usecs 50 rx-frames 25
# → Actual changes:
# → rx-usecs: 50
# → rx-frames: 25

# Для high-throughput (отключение коалесценции, полагаемся на NAPI)
sudo ethtool -C eth0 rx-usecs 0 rx-frames 0
# → Actual changes:
# → rx-usecs: 0
# → rx-frames: 0
```

**Валидация:**
```bash
ethtool -c eth0 | grep -E "rx-usecs|rx-frames"
# → rx-usecs: 50
# → rx-frames: 25
```

### Шаг 7: Мониторинг per-interface через /proc/softirqs и ethtool -S

Для определения, какой интерфейс создает наибольшую нагрузку:

```bash
# Мониторинг NET_RX по ядрам
watch -n1 "cat /proc/softirqs | grep NET_RX"
#            CPU0       CPU1       CPU2       CPU3
# NET_RX:     123456     234567     345678     456789

# Статистика конкретного интерфейса
ethtool -S eth0 | grep -E "rx_queue|missed|drop"
#     rx_queue_0_packets: 12345678
#     rx_queue_0_drops: 0
#     rx_missed_errors: 0
#     rx_fifo_errors: 0
```

**Валидация:**
```bash
# Общий dropped за все ядра
awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc
# → 0 (должен быть 0)

# missed errors
ethtool -S eth0 | grep missed
# → rx_missed_errors: 0
```

### Шаг 8: Тюнинг для 25G/100G сетей

На скоростях 25G+ стандартные параметры недостаточно:

```bash
# Увеличение ring buffer
ethtool -G eth0 rx 4096 tx 4096
# → Ring parameters for eth0:
# → Pre-set maximums:
# → RX:             4096
# → TX:             4096

# Проверка количества очередей
ethtool -l eth0
# Channel parameters for eth0:
#   Pre-set maximums:
#     RX:             64
#     TX:             64
#     Combined:       64

# Установка combined queues
sudo ethtool -L eth0 combined 64
# → 64

# Увеличение бюджета для 100G
sudo sysctl -w net.core.netdev_budget=2000
# → net.core.netdev_budget = 2000

sudo sysctl -w net.core.netdev_budget_usecs=10000
# → net.core.netdev_budget_usecs = 10000
```

### Шаг 9: Контейнеры и KVM (vhost-net, virtio)

В виртуализированных окружениях NAPI работает иначе:

```bash
# Проверка поддержки multi_queue на хосте
ethtool -l eth0
# Combined: 64

# Настройка vhost-net с multi_queue на хосте KVM
# В XML домена:
# <interface type='bridge'>
#   <model name='virtio-net'/>
#   <driver name='vhost'>
#     <driver name='vhost'>
#       <queue size='1024'/>
#     </driver>
#   </driver>
# </interface>

# Внутри контейнера настройки NAPI не видны — настраивайте на хостовом veth
sudo ethtool -G eth0 rx 4096
sudo ethtool -C eth0 rx-usecs 3
```

**Валидация:**
```bash
# Проверка очередей внутри ВМ
ethtool -l eth0
# Combined: 4 (если multi_queue=yes на хосте)

# Проверка dropped в гостевой ОС
cat /proc/net/softnet_stat
# → 00000000 00000000 00000000 ... (все нули = норма)
```

### Шаг 10: Взаимодействие с cgroups и CPU isolation

При использовании cgroups v2 или isolcpus учитывайте влияние на NAPI:

```bash
# Проверка, что housekeeping-ядра доступны для ksoftirqd
cat /sys/fs/cgroup/cpuset/cpuset.cpus
# → 0-3,8-11 (ядре 4-7 изолированы)

# ksoftirqd должен работать на housekeeping-ядрах
ps -o pid,psr,comm -p $(pgrep ksoftirqd | head -1)
# → PID  PSR COMMAND
# → 12    8   ksoftirqd/8

# Если ksoftirqd на изолированном ядре — сдвиньте affinity
sudo taskset -pc 8 1234
# → pid 1234's current affinity mask: 8
# → pid 1234's new affinity mask: 8
```

**Валидация:**
```bash
# Проверка PSI (Pressure Stall Information)
cat /proc/pressure/irq
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0

# Проверка %si на изолированных ядрах
mpstat -P ALL 1 5 | grep -E "CPU|%soft"
# → CPU8  ...  0.0 si (должен быть низким)
```

### Шаг 11: Диагностика memory pressure

При нехватке памяти NAPI не может выделить sk_buff:

```bash
# Проверка логов ядра
dmesg | grep -i "napi" | tail -20
# → [12345.678] NETDEV WATCHDOG: eth0 (mlx5_core): transmit queue 0 timed out
# → [12345.678] mlx5_core 0000:3b:00.0 eth0: Error on NAPI instance

# Мониторинг памяти
free -h
# → Mem: 31G, used: 28G, available: 1.2G (критически мало)

# Проверка slab-памяти для sk_buff
cat /proc/slabinfo | grep -E "skb_head|skb_frag"
# → skbuff_head_cache     512   512    256
# → skb_frag_cache        128   128    2048

# Освобождение кэша (временно, для диагностики)
echo 2 | sudo tee /proc/sys/vm/drop_caches
# → 2
```

---

## Диагностика и устранение неисправностей

### Таблица типичных проблем

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий `%si` в `top`** | NIC перегружает одно ядро | `mpstat -P ALL 1`, `cat /proc/interrupts` | Настроить RSS/RPS, увеличить очереди |
| **Рост столбца 2 в `softnet_stat`** | Переполнение `netdev_max_backlog` | `awk '{print $2}' /proc/net/softnet_stat` | Увеличить backlog, RSS/RPS |
| **Рост столбца 3 в `softnet_stat`** | Исчерпание `netdev_budget` | `awk '{print $3}' /proc/net/softnet_stat` | Увеличить budget, budget_usecs |
| **`rx_missed_errors` растет** | Ring Buffer переполнен | `ethtool -S eth0 \| grep missed` | Увеличить ring buffer через `ethtool -G` |
| **Потери при малых пакетах** | NAPI overhead доминирует | `ethtool -S eth0` | Уменьшить budget, включить XDP/AF_XDP |
| **Busy Poll не снижает latency** | `busy_poll=0` или нет SO_BUSY_POLL | `sysctl net.core.busy_poll`, `ss -ti` | Установить `busy_poll=50`, добавить `SO_BUSY_POLL` |
| **Высокий latency при низкой нагрузке** | Слишком высокая коалесценция | `ethtool -c eth0` | Уменьшить `rx-usecs` |
| **ksoftirqd на изолированном ядре** | cgroups/isolcpus настроены неправильно | `ps -o psr,comm -p $(pgrep ksoftirqd)` | Перенести affinity на housekeeping |
| **`napi_alloc_skb` failures** | Нехватка памяти | `dmesg | grep napi`, `free -h` | Увеличить RAM, уменьшить backlog |
| **Packet reordering после RSS** | Асимметричный Toeplitz key | `ethtool -n eth0` | Использовать symmetric RSS key |

### Диагностический чек-лист

```bash
# 1. Общая нагрузка SoftIRQ
mpstat -P ALL 1 5 | grep -E "CPU|%soft"
# → CPU0  ...  0.0 us,  0.5 sy,  0.0 ni, 99.0 id,  0.0 wa,  0.5 si (норма <5%)

# 2. Статистика softnet
cat /proc/net/softnet_stat
# → 000a1234 00000000 00000000 ... (столбцы 2 и 3 = 0)

# 3. Ring Buffer
ethtool -S eth0 | grep -E "missed|fifo|over"
# → rx_missed_errors: 0
# → rx_fifo_errors: 0

# 4. Прерывания
cat /proc/interrupts | grep eth0
# → Разброс по ядрам равномерный

# 5. NAPI потоки (если Threaded NAPI)
ps -ef | grep napi
# → napi/eth0-0, napi/eth0-1, ...

# 6. Pressure
cat /proc/pressure/irq
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

---

## Особенности и edge cases

### Малые пакеты (< 64 байта)

При минимальном размере пакета накладные расходы NAPI доминируют над полезной работой. Обработка одного 64-байтового пакета может занимать больше CPU, чем 1500-байтового.

**Решение:**
- Уменьшить `netdev_budget` (чтобы другие пакеты не ждали)
- Включить XDP/AF_XDP для минимального overhead
- Увеличить MTU на всем пути (jumbo frames)
- Использовать hardware filtering (Flow Director)

### Виртуализация (KVM/QEMU)

В гостевой ОС NAPI работает поверх virtio-net, который эмулирует NIC. Особенности:
- `virtio-net` программно эмулирует GRO/TSO/GSO
- vhost-net выносит обработку в ядро хоста
- SR-IOV (VF) дает производительность уровня bare-metal
- Количество очередей ограничено параметром `queues` на хосте

### Контейнеры (Docker/Podman)

Внутри контейнера NAPI настраивается на уровне хостового veth-интерфейса. Настройки изолированы netns.

```bash
# На хосте
ethtool -G vethABC rx 4096

# Внутри контейнера настройки Ring Buffer не видны
docker exec c1 ethtool -g eth0
# → Cannot get driver information: Operation not supported
```

### Смешанный трафик (small + large packets)

При одновременном прохождении мелких (64B) и крупных (1500B) пакетов NAPI может "застрять" на обработке мелких, если budget исчерпан.

**Решение:**
- Настроить `ethtool -n` для multi-queue с хэшированием по потоку
- RPS/RFS для распределения потоков
- Уменьшить budget и увеличить частоту вызовов NAPI

### Когда увеличение budget ухудшает производительность

Очень высокий `netdev_budget` (>5000) может привести к:
- Длительному удержанию CPU в SoftIRQ
- Росту задержок всех процессов на системе
- Пробуждению ksoftirqd

**Правило:** Увеличивайте budget постепенно и мониторьте `si%` в `mpstat`. Цель: `si%` < 5% на фоновой нагрузке.

### Взаимодействие с br_netfilter

При использовании моста Linux с включенным `br_netfilter` пакеты проходят дополнительный цикл netfilter, что увеличивает нагрузку на NAPI. Для высокой производительности отключайте `br_netfilter` и используйте нативные nftables bridge family.

### Cgroup CPU limits

Если приложение в cgroup с жестким лимитом `cpu.max`, а NAPI и ksoftirqd работают на том же ядре, происходит contention:

```bash
# Проверка throttle
cat /sys/fs/cgroup/cpuset/cpuset.cpus
cat /sys/fs/cgroup/cpu/cpu.max
# → 50000 100000 (50% одного ядра)

# Проверка throttled time
cat /sys/fs/cgroup/cpu/cpu.stat
# → usage_usec 123456789
# → user_usec 98765432
# → system_usec 24691357
# → nr_periods 1000
# → nr_throttled 150 (высокое значение = проблема)
```

---

## Чек-лист оптимизации сетевого планирования

1.  **Мониторинг:** Проверьте `softnet_stat` на наличие `squeezed` и `dropped`.
2.  **Аппаратное:** Настройте очереди и буферы через `ethtool -G` и `ethtool -L`.
3.  **Коалесценция:** Настройте `ethtool -C` для баланса latency/throughput.
4.  **Бюджет:** Адаптируйте `netdev_budget` и `netdev_budget_usecs` под ваш PPS.
5.  **Backlog:** Увеличьте `net.core.netdev_max_backlog` при переполнениях.
6.  **Распределение:** Если одно ядро CPU перегружено в `%soft` — настройте [RSS/RPS/RFS](./rss_rps_rfs.md).
7.  **Изоляция:** Используйте Threaded NAPI для отделения сетевой обработки от системных прерываний.
8.  **Low Latency:** Для критичных приложений включите Busy Poll (`net.core.busy_poll`).
9.  **Виртуализация:** Для KVM используйте vhost-net с multi_queue, для контейнеров — настраивайте на хосте.
10. **Валидация:** После всех изменений проверьте `rx_missed_errors`, `softnet_stat`, `%si`.

---

## Связанные темы

*   [**Многопоточная обработка трафика (RSS, RPS, RFS)**](./rss_rps_rfs.md) — распределение нагрузки по ядрам.
*   [**Сетевая разгрузка (Offloading)**](./offloading.md) — GRO, LRO, TSO, GSO и их влияние на NAPI.
*   [**Диагностика потерь в сетевом стеке**](../network_stack_packet_loss.md) — поиск дропов на всех уровнях.
*   [**ethtool: диагностика железа**](../Tools/ethtool.md) — настройка очередей, коалесценции, offloading.
*   [**Прерывания в ядре Linux**](../../Core/kernel/interrupts.md) — архитектура MSI-X и SoftIRQ.
