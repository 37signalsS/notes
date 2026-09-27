# Диагностика потерь пакетов в сетевом стеке Linux

## Определения

* **Сетевой стек Linux (Network Stack)** — набор уровней обработки сетевого трафика в ядре, от получения пакета сетевой картой до передачи данных приложению.
* **Потери в стеке (Stack Drops)** — отбрасывание пакетов ядром из-за нехватки ресурсов, переполнения очередей или правил фильтрации, даже если физический уровень (L1/L2) работает без ошибок.
* **Socket Backpressure** — механизм «обратного давления», при котором заполнение буферов сокета приводит к замедлению или остановке приема новых данных.
* **Clean Interface** — состояние сетевого интерфейса, при котором счётчики ошибок драйвера (`RX-ERR`, `RX-DRP` в выводе `ip -s link`) равны нулю, но пакеты всё равно теряются на более высоких уровнях.
* **sk_buff (skb)** — основная структура данных ядра Linux для представления сетевого пакета в памяти. Каждый пакет, проходящий через стек, описывается цепочкой `sk_buff`. Нехватка памяти для выделения `sk_buff` приводит к дропам пакетов на ранних этапах обработки.
* **SoftIRQ / NET_RX** — программный контекст прерывания (Bottom Half), в котором выполняется основная часть сетевой обработки входящих пакетов. Для сетевого приема используется обработчик `NET_RX`.
* **ksoftirqd** — поток ядра, который активируется, когда обработка SoftIRQ на данном ядре превышает порог времени (обычно ~2 мс на burst). Высокая загрузка `ksoftirqd` в `top` (поле `si`) указывает на нехватку ресурсов для сетевой обработки.
* **NAPI (New API)** — механизм ядра Linux для обработки входящих пакетов методом опроса (polling) вместо прерываний при высокой нагрузке. NAPI комбинирует обработку прерываний и активный опрос, чтобы минимизизировать нагрузку на CPU.
* **Memory Pressure (Давление памяти)** — состояние, при котором общее потребление памяти подсистемой TCP/UDP превышает пороги, заданные в `tcp_mem` или `udp_mem`. В этом режиме ядро отключает автотюнинг буферов и принудительно отбрасывает новые пакеты.
* **RX/TX Ring Buffer** — аппаратные кольцевые очереди в памяти NIC, через которые DMA-движок карты записывает принятые пакеты (RX) или считывает отправляемые (TX). Переполнение Ring Buffer приводит к дропам на уровне драйвера (`rx_missed_errors`).
* **RPS (Receive Packet Steering)** — программный механизм распределения входящих пакетов по ядрам CPU после их получения из драйвера NIC. Используется, когда NIC имеет недостаточно очередей для аппаратного RSS.
* **RFS (Receive Flow Steering)** — расширение RPS, направляющее обработку пакета на то ядро CPU, где выполняется приложение-получатель. Максимизирует попадание в кэш процессора (CPU Cache Locality).
* **XDP (eXpress Data Path)** — фреймворк eBPF, выполняющий программы на самом раннем этапе в драйвере NIC, до помещения пакета в Ring Buffer и до вызова NAPI. XDP_DROP позволяет отбрасывать пакеты с минимальными накладными расходами.

## Основные концепции

### Путь пакета через стек (Packet Journey)

Для эффективной диагностики важно понимать этапы прохождения пакета и точки, где могут возникать потери:

1.  **NIC Ring Buffer:** Аппаратная очередь сетевой карты. DMA-движок записывает пакеты в кольцевой буфер. Потери здесь — это «Hardware Drops» (`rx_missed_errors`), сигнализирующие о том, что ядро не успевает забирать пакеты из буфера.
2.  **NAPI / SoftIRQ (ksoftirqd):** Ядро опрашивает Ring Buffer через NAPI, забирает пакеты пачками (budget) и передает их в `backlog`-очередь. Если NIC генерирует пакеты быстрее, чем NAPI успевает обрабатывать, пакеты накапливаются в `netdev_max_backlog`. Потери здесь — «Softnet Drops» (второй столбец `/proc/net/softnet_stat`).
3.  **Сетевой уровень (L3/IP):** Проверка контрольных сумм, маршрутизация, фрагментация, фильтрация (Netfilter). Потери на этом уровне могут быть вызваны нехваткой памяти для `sk_buff`, переполнением ARP/neighbor таблицы или правилами firewall.
4.  **Транспортный уровень (L4/TCP/UDP):** Для TCP — проверка состояния соединения, очереди (`somaxconn`, `tcp_max_syn_backlog`), буферы сокетов. Для UDP — буферы приема (`udp_rmem`) и таблица хэшей. Потери здесь — `TcpExtListenDrops`, `UdpInErrors`, `RcvbufErrors`.
5.  **Приложение:** Вычитка данных из сокета. Если приложение не читает данные (`recv()`/`read()`), буферы сокета заполняются, и ядро либо отбрасывает новые пакеты (UDP), либо включает окно размера 0 (TCP Zero Window), что приводит к замедлению или остановке передачи.

### Архитектура обработки пакетов в Linux

#### NAPI и SoftIRQ

Классический обработчик прерываний (one-interrupt-per-packet) не справляется с высокими скоростями (10G+). NAPI переключается в режим опроса после первого прерывания:

1.  NIC получает пакет → генерирует прерывание (Hard IRQ).
2.  Драйвер отключает аппаратные прерывания для очереди (или повышает порог коалесценции).
3.  Ядро запускает цикл NAPI (`napi_poll`), забирая пакеты из Ring Buffer пачками до исчерпания бюджета (`netdev_budget`).
4.  Если пакеты закончились или бюджет исчерпан — цикл завершается, прерывания включаются снова.

**Ключевые параметры:**
*   `net.core.netdev_budget` — глобальный лимит пакетов на все интерфейсы за один SoftIRQ-цикл. Дефолт: 300.
*   `net.core.netdev_budget_usecs` — лимит времени в микросекундах на цикл. Дефолт: 2000 (2 мс).
*   `net.core.netdev_max_backlog` — размер глобальной очереди пакетов, ожидающих обработки SoftIRQ. Дефолт: 1000.
*   `net.core.netdev_budget_per_cpu` — лимит пакетов на одно ядро. Дефолт: 300. Ядро 4.20+.

**Валидация:**
```bash
sysctl net.core.netdev_budget net.core.netdev_budget_usecs net.core.netdev_max_backlog net.core.netdev_budget_per_cpu
# → net.core.netdev_budget = 300
# → net.core.netdev_budget_usecs = 2000
# → net.core.netdev_max_backlog = 1000
# → net.core.netdev_budget_per_cpu = 300
```

#### Жизненный цикл sk_buff и Memory Pressure

Каждый пакет в стеке представлен структурой `sk_buff`. При высокой нагрузке ядро активно выделяет и освобождает эти структуры из slab-кэша (`skbuff_head_cache`, `skb_frag_cache`).

Если память ограничена:
*   `napi_alloc_skb` может возвращать `NULL`
*   Драйвер отбрасывает пакеты с ошибкой `ENOMEM`
*   Срабатывает механизм Memory Pressure для TCP/UDP

**Валидация:**
```bash
# Проверка slab-памяти для sk_buff
cat /proc/slabinfo | grep -E "skb_head|skb_frag"
# → skbuff_head_cache     512   512    256
# → skb_frag_cache        128   128   2048

# Проверка давления на память
cat /proc/pressure/memory
# → some avg10=0.00 avg60=0.00 avg300=0.00 total=0
# → full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

#### Взаимодействие NAPI с коалесценцией и offloading

*   **Interrupt Coalescing** работает на уровне прерываний: NIC накапливает пакеты перед генерацией прерывания. Управляется через `ethtool -C`.
*   **GRO (Generic Receive Offload)** работает в контексте NAPI, агрегируя пакеты пачками. Если budget исчерпан, остальные пакеты остаются в RX-ring, что приводит к `rx_missed_errors`.
*   **XDP** выполняется в драйвере до Ring Buffer и NAPI. XDP_DROP отбрасывает пакеты без участия NAPI, достигая 100Mpps+ на одном ядре.

### Почему пакеты теряются на каждом уровне

| Уровень | Причина потерь | Диагностика |
| :--- | :--- | :--- |
| **NIC Ring Buffer** | DMA не успевает записывать пакеты | `ethtool -S eth0 \| grep rx_missed_errors` |
| **SoftIRQ / NAPI** | Переполнение `netdev_max_backlog` или исчерпание `netdev_budget` | `cat /proc/net/softnet_stat` (столбцы 2 и 3) |
| **L3/IP** | Нехватка памяти для `sk_buff`, переполнение ARP/neighbor таблицы | `dmesg \| grep -i "neighbor table overflow"` |
| **L4/TCP** | Переполнение Accept backlog (`somaxconn`), SYN backlog | `nstat -az \| grep ListenDrops` |
| **L4/UDP** | Переполнение буферов сокетов (`UdpInErrors`) | `nstat -az \| grep UdpInErrors` |
| **L4/conntrack** | Переполнение таблицы отслеживания соединений | `dmesg \| grep "nf_conntrack: table full"` |
| **Firewall** | Правила DROP/REJECT без логирования | `nft monitor trace`, `iptables -L -n -v` |
| **Приложение** | Приложение не читает из сокета (Zero Window) | `ss -tin \| grep -i "zero"` |

## Практические сценарии

### Сценарий 1: Общая картина и диагностика по слоям

Прежде чем углубляться, проверьте глобальные счётчики стека и статистику интерфейсов.

**Команды:**

```bash
# Глобальные счётчики ошибок стека (включая UDP и TCP дропы)
nstat -az | grep -iE "drop|overflow|error"

# Статистика интерфейсов (проверка L1/L2/Driver)
ip -s link show eth0

# Проверка SoftIRQ статистики
cat /proc/net/softnet_stat

# Проверка slab-памяти для sk_buff
cat /proc/slabinfo | grep -E "skb_head|skb_frag"
```

**Интерпретация:**
*   Если `ip -s link` показывает рост `dropped` — проблема в очередях `backlog` (L2-L3).
*   Если `TcpExtListenDrops` растет — приложение не успевает принимать новые TCP-соединения (`accept`).
*   Если `TcpExtUDPInErrors` растет — переполнены буферы UDP-сокетов.
*   Если второй столбец `softnet_stat` растет — переполнена `netdev_max_backlog`.
*   Если третий столбец `softnet_stat` растет — не хватает `netdev_budget`.

**Валидация:**
```bash
# Пример: все счетчики в норме
nstat -az | grep -iE "drop|overflow|error"
# → (вывод пуст или все значения 0)

ip -s link show eth0 | grep -A2 "RX\|TX"
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234567    8901     0       0       0       0
```

---

### Сценарий 2: Переполнение очереди входящих пакетов (softnet)

Пакеты приходят быстрее, чем ядро успевает их обрабатывать в контексте `softirq`. Это одна из самых частых причин потерь в сетевом стеке.

**Диагностика:**

```bash
cat /proc/net/softnet_stat
```

**Интерпретация (столбцы):**
1.  `total`: Всего обработано пакетов.
2.  `dropped`: Пакеты, отброшенные из-за переполнения `netdev_max_backlog`. **Критический показатель.**
3.  `squeezed`: Сколько раз обработка прерывалась по таймауту или кванту времени. Если растет — не хватает `netdev_budget`.

**Валидация:**
```bash
# Сумма dropped по всем ядрам
awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc
# → 0 (должно быть 0 или близко к 0)

# Сумма squeezed по всем ядрам
awk '{print $3}' /proc/net/softnet_stat | paste -sd+ | bc
# → 0 (должно быть 0 или близко к 0 при правильном бюджете)
```

**Решение:**
1.  **Увеличить очередь:** `sysctl -w net.core.netdev_max_backlog=5000`.
2.  **Тюнинг NAPI:** Настроить бюджет обработки пакетов. См. [**Оптимизация NAPI и netdev_budget**](./Concepts/napi_optimization.md).
3.  **Распределить нагрузку:** Использовать **[RSS/RPS/RFS](./Concepts/rss_rps_rfs.md)** для балансировки прерываний по ядрам CPU.

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Второй столбец `softnet_stat` растет | `netdev_max_backlog` слишком мал | Увеличить до 5000-30000 в зависимости от скорости |
| Третий столбец `softnet_stat` растет | `netdev_budget` исчерпан | Увеличить `net.core.netdev_budget` и `net.core.netdev_budget_usecs` |
| Высокий `%si` в `top` | Одно ядро перегружено SoftIRQ | Настроить RSS/RPS, увеличить количество очередей NIC |

**Best Practices:**
*   Для 10G сетей: `netdev_max_backlog` ≥ 10000, `netdev_budget` ≥ 600.
*   Для 100G сетей: `netdev_max_backlog` ≥ 30000, `netdev_budget` ≥ 2000.
*   Постоянное сохранение в `/etc/sysctl.d/99-network-performance.conf`.

---

### Сценарий 3: Таблица соединений (conntrack)

Механизм Netfilter отслеживает состояние каждого соединения. При переполнении таблицы новые пакеты (особенно SYN) отбрасываются.

**Диагностика:**

```bash
# Детальная статистика conntrack
sudo conntrack -S

# Лимиты и текущее состояние
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Поиск подтверждения в системном логе
dmesg | grep -i "nf_conntrack: table full"

# Просмотр активных соединений
sudo conntrack -L -p tcp --dport 80 | wc -l
```

**Интерпретация:**
*   `nf_conntrack_count` близок к `nf_conntrack_max` — таблица заполнена.
*   Сообщения в `dmesg` — критические дропы уже происходят.
*   `conntrack -S` показывает распределение по состояниям (NEW, ESTABLISHED, TIME_WAIT).

**Валидация:**
```bash
# Пример: таблица почти заполнена
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 262000
# → net.netfilter.nf_conntrack_max = 262144

# Проверка дропов
dmesg | grep -c "nf_conntrack: table full"
# → 0 (должно быть 0)
```

**Решение:** Увеличить `net.netfilter.nf_conntrack_max` или уменьшить таймауты для неактивных соединений.

**Настройка для high-load:**
```ini
# /etc/sysctl.d/99-conntrack.conf
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15
net.netfilter.nf_conntrack_udp_timeout = 30
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-conntrack.conf`

**Откат:**
```bash
sudo sysctl -w net.netfilter.nf_conntrack_max=262144
sudo rm /etc/sysctl.d/99-conntrack.conf
sudo sysctl --system
```

**Типичные ошибки:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full` в dmesg | `nf_conntrack_max` исчерпан | Увеличить лимит, сократить таймауты |
| Новые соединения не проходят | Таблица заполнена | `conntrack -S`, `sysctl net.netfilter.nf_conntrack_count` |
| Высокий `TIME_WAIT` | Таймаут слишком большой | Уменьшить `nf_conntrack_tcp_timeout_time_wait` |

**Edge Cases:**
*   **VRF и conntrack:** По умолчанию conntrack не разделяет соединения по VRF — при overlapping IP в разных VRF возможны коллизии (требуется VRF-aware conntrack в новых ядрах). Фильтрация — `meta l3mdev` в nftables.
*   **UDP race condition:** При параллельных UDP-запросах с одного сокета возможны задержки ровно 1000 мс или 5000 мс (таймауты ретрансмиссии). Решение: NodeLocal DNSCache, `single-request-reopen`.

---

### Сценарий 4: Переполнение буферов сокетов

Особенно актуально для UDP-трафика и высоконагруженных TCP-серверов.

**Диагностика:**

```bash
# Счётчики ошибок UDP
nstat -az | grep -iE "UdpInErrors|UdpRcvbufErrors|UdpSndbufErrors"

# Поиск сокетов с переполненной очередью (Recv-Q)
ss -unmp | awk '$2 > 0'

# Проверка TCP-буферов для конкретного соединения
ss -tin state established dst 192.168.1.100 | grep -E "rcv_space|rcv_buf|wmem_queued"
```

**Интерпретация:**
*   `UdpInErrors` растет — UDP-пакеты отбрасываются из-за переполнения буферов приема.
*   `Recv-Q > 0` и не уменьшается — приложение тормозит, не успевает вычитывать данные.
*   `rcv_space` мал относительно BDP — окно приема переполнено.

**Валидация:**
```bash
# Пример: UDP ошибок нет
nstat -az | grep -iE "UdpInErrors|UdpRcvbufErrors"
# → UdpInErrors                0                  0.0
# → UdpRcvbufErrors            0                  0.0

# Пример: TCP соединение с нормальными буферами
ss -tin state established dst 192.168.1.100 | grep -E "rcv_space|rcv_buf"
# → rcv_space:14600 rcv_ssthresh:64088 minrtt:0.5
```

**Тюнинг буферов:**
```bash
# Максимальный размер буфера приема/передачи для всех типов сокетов
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216

# TCP-специфичные буферы (min default max)
sysctl -w net.ipv4.tcp_rmem="4096 131072 16777216"
sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"

# UDP-специфичные буферы (в страницах по 4КБ)
sysctl -w net.ipv4.udp_mem="8192 12582912 16777216"
```

**Best Practices:**
*   Размер буфера должен быть не меньше BDP: `BDP = Bandwidth (bps) * RTT (s)`.
*   Для 10G и RTT 10 мс: BDP ≈ 12.5 МБ, буфер должен быть ≥ 16 МБ.
*   Автотюнинг (`tcp_moderate_rcvbuf = 1`) включен по умолчанию для TCP.

---

### Сценарий 5: TCP Listen Backlog Overflow

При переполнении очереди установленных соединений (Accept backlog) ядро молча отбрасывает пакеты ACK, заставляя клиента выполнять ретрансмиссию.

**Диагностика:**

```bash
# Проверка счетчиков переполнения
nstat -az | grep -E "ListenOverflows|ListenDrops|ReqQFullDrop"

# Проверка текущих лимитов
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog

# Проверка очереди accept для слушающих портов
ss -lnt
# Send-Q — текущий эффективный лимит
# Recv-Q — количество соединений, ожидающих в очереди accept()
```

**Интерпретация:**
*   `TcpExtTCPListenOverflows` растет — Accept backlog переполнен.
*   `TcpExtTCPReqQFullDrop` растет — SYN backlog переполнен (при выключенных syncookies).
*   `Recv-Q` в `ss -lnt` близок к `Send-Q` — очередь почти полна.

**Валидация:**
```bash
# Пример: норма
nstat -az | grep -E "ListenOverflows|ListenDrops|ReqQFullDrop"
# → TcpExtTCPListenOverflows    0       0.0
# → TcpExtTCPListenDrops        0       0.0
# → TcpExtTCPReqQFullDrop       0       0.0
```

**Решение:**
```bash
# Временное увеличение
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384

# Постоянное сохранение
cat <<EOF | sudo tee /etc/sysctl.d/99-network-queues.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_abort_on_overflow = 1
EOF
sudo sysctl -p /etc/sysctl.d/99-network-queues.conf
```

**Best Practices:**
*   За балансировщиком (LBP) используйте `tcp_abort_on_overflow = 1` для быстрой реакции.
*   Для HTTP-серверов: `listen 80 backlog=16384;` в Nginx.
*   Мониторинг через Prometheus: `rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10`.

---

### Сценарий 6: Скрытые правила фильтрации (Firewall)

Правила `nftables` или `iptables` могут отбрасывать пакеты без логов. Часто проблема кроется не в ошибке самого правила, а в его **порядке**: более общее запрещающее правило выше по списку может «перехватывать» трафик раньше нужного разрешающего правила (First-match).

**Диагностика для nftables (современный метод):**

```bash
# Просмотр всего набора правил со счётчиками срабатываний
sudo nft list ruleset

# Мониторинг процесса обработки пакета в реальном времени (Trace)
# Позволяет увидеть, на каком именно правиле пакет был отброшен
sudo nft monitor trace
```

**Диагностика для iptables (Legacy):**
```bash
# Просмотр правил с порядковыми номерами и счётчиками пакетов
sudo iptables -L -n -v --line-numbers | grep -v "0     0"
```

**Валидация:**
```bash
# Пример: правило DROP сработало 1523 раза
sudo nft list ruleset | grep drop
# → drop count 1523

# Пример: iptables с счетчиками
sudo iptables -L INPUT -n -v --line-numbers
# → 3   1542   DROP       all  --  0.0.0.0/0            0.0.0.0/0
```

**Решение:** Переместить разрешающее правило выше блокирующего или уточнить условия фильтрации. В `iptables` используйте вставку (`-I`) вместо добавления в конец (`-A`).

**Best Practices:**
*   Всегда используйте `--line-numbers` при просмотре правил.
*   Для nftables включите `meta nftrace set 1` для отладки.
*   После изменений проверяйте счетчики — они должны расти для разрешающих правил и оставаться нулевыми для блокирующих (если трафик легитимный).

---

### Сценарий 7: Аппаратные потери (Ring Buffers)

Часто путают с потерями в стеке. Если буфер сетевой карты полон, пакет отбрасывается до того, как ядро его увидит.

**Диагностика:**
```bash
# Ошибки на уровне железа
sudo ethtool -S eth0 | grep -E "drop|miss|error"

# Проверка текущего и максимального размера буферов
ethtool -g eth0

# Проверка количества очередей
ethtool -l eth0
```

**Интерпретация:**
*   `rx_missed_errors` растет — Ring Buffer переполнен, NIC отбрасывает пакеты.
*   `rx_fifo_errors` растет — переполнение внутреннего FIFO-буфера NIC.
*   `rx_dropped` в `ip -s link` — пакеты отброшены на уровне драйвера.

**Валидация:**
```bash
# Пример: нет ошибок
sudo ethtool -S eth0 | grep -E "drop|miss|error"
# → rx_missed_errors: 0
# → rx_fifo_errors: 0
# → rx_dropped: 0
```

**Решение:** Увеличить размер Ring Buffers (`ethtool -G eth0 rx 4096`).

**Best Practices:**
*   Для 10G+ сетей: RX Ring Buffer ≥ 4096.
*   Для 100G сетей: RX Ring Buffer ≥ 8192-16384.
*   Количество очередей (`ethtool -L`) должно соответствовать количеству ядер CPU, обрабатывающих сетевой трафик.
*   Настройки сохраняются через systemd-networkd `.link` файлы или `rc.local`.

---

### Сценарий 8: Глубокая диагностика с eBPF (pwru, dropwatch)

Если стандартные счётчики не дают ответа, используйте современные инструменты трассировки, чтобы увидеть, на какой именно функции ядра «умирает» пакет.

**Команды:**

```bash
# Отслеживание пути пакета до конкретного порта (pwru)
# Показывает стек вызовов и место Drop
sudo pwru --filter-dst-port 443

# Использование dropwatch (классика)
sudo dropwatch -l kas

# bpftrace для отслеживания конкретных функций
sudo bpftrace -e '
kprobe:napi_poll {
    @drops[comm] = count();
}
'
```

**Валидация:**
```bash
# pwru показывает стек вызовов с указанием функции дропа
# → [timestamp] netif_receive_skb -> ip_rcv -> nf_hook_slow -> [DROP] nf_reject
```

**Best Practices:**
*   Используйте `pwru` для быстрого поиска места дропа.
*   `dropwatch` полезен для мониторинга в реальном времени.
*   Для постоянного мониторинга рассмотрите `bpftrace` скрипты с записью в Prometheus.

---

### Сценарий 9: Мониторинг и алертинг (SRE/DevOps)

В операционных системах критически важно настроить proactive-мониторинг, а не реактивную диагностику.

**Мониторинг через node_exporter + Prometheus:**

```yaml
# /etc/prometheus/rules/network_stack.yml
groups:
  - name: network_stack_alerts
    rules:
      - alert: HighSoftnetDrops
        expr: rate(node_netstat_Softnet_Drops[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Потери пакетов в softnet ({{ $labels.instance }})"
          description: "Rate дропов в softnet: {{ $value }}"

      - alert: HighSoftnetSqueezed
        expr: rate(node_netstat_Softnet_Squeezed[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Исчерпание netdev_budget ({{ $labels.instance }})"
          description: "Rate squeezed: {{ $value }}"

      - alert: HighListenOverflows
        expr: rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Переполнение Accept backlog"
          description: "Rate переполнений: {{ $value }}"

      - alert: ConntrackTableFull
        expr: node_netfilter_nf_conntrack_count / node_netfilter_nf_conntrack_max > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Таблица conntrack заполнена >90%"
          description: "Использовано {{ $value | humanizePercentage }}"

      - alert: HighUDPInErrors
        expr: rate(node_netstat_Udp_InErrors[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "UDP пакеты отбрасываются"
          description: "Rate UdpInErrors: {{ $value }}"
```

**Скрипт быстрой диагностики для SRE:**

```bash
#!/bin/bash
# network_stack_health.sh — быстрая проверка здоровья сетевого стека
# Использование: ./network_stack_health.sh [interface]

IFACE="${1:-eth0}"
EXIT_CODE=0

check() {
    local name="$1"
    local result="$2"
    local expected="$3"
    if [ "$result" != "$expected" ]; then
        echo "FAIL: $name = $result (ожидалось: $expected)"
        EXIT_CODE=1
    else
        echo "OK: $name = $result"
    fi
}

echo "=== Network Stack Health Check: $IFACE ==="

# 1. Проверка ошибок интерфейса
RX_DROPPED=$(ip -s link show "$IFACE" | awk '/RX:/ {print $5}')
check "ip.rx_dropped" "$RX_DROPPED" "0"

# 2. Проверка softnet
SOFTNET_DROPPED=$(awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc)
check "softnet.dropped" "$SOFTNET_DROPPED" "0"

SOFTNET_SQUEEZED=$(awk '{print $3}' /proc/net/softnet_stat | paste -sd+ | bc)
check "softnet.squeezed" "$SOFTNET_SQUEEZED" "0"

# 3. Проверка Ring Buffer
RX_MISSED=$(ethtool -S "$IFACE" 2>/dev/null | grep rx_missed_errors | awk '{print $2}')
check "nic.rx_missed_errors" "$RX_MISSED" "0"

# 4. Проверка conntrack
CONNTRACK_COUNT=$(sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "0")
CONNTRACK_MAX=$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "1")
if [ "$CONNTRACK_COUNT" -gt "$((CONNTRACK_MAX * 90 / 100))" ]; then
    echo "WARN: conntrack usage = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
    EXIT_CODE=1
else
    echo "OK: conntrack = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
fi

# 5. Проверка UDP ошибок
UDP_ERRORS=$(nstat -az | grep UdpInErrors | awk '{print $2}')
check "udp.in_errors" "$UDP_ERRORS" "0"

# 6. Проверка ListenOverflows
LISTEN_OVERFLOWS=$(nstat -az | grep ListenOverflows | awk '{print $2}')
check "tcp.listen_overflows" "$LISTEN_OVERFLOWS" "0"

exit $EXIT_CODE
```

**Валидация:**
```bash
chmod +x /etc/scripts/network_stack_health.sh
/etc/scripts/network_stack_health.sh eth0
# → OK: ip.rx_dropped = 0
# → OK: softnet.dropped = 0
# → OK: softnet.squeezed = 0
# → OK: nic.rx_missed_errors = 0
# → OK: conntrack = 45000/1048576
# → OK: udp.in_errors = 0
# → OK: tcp.listen_overflows = 0
```

**Автоматизация:**
```bash
# Добавление в cron для периодической проверки
(crontab -l 2>/dev/null; echo "*/5 * * * * /etc/scripts/network_stack_health.sh eth0 || logger 'Network stack health check FAILED'") | crontab -
```

## Дополнительная информация

### Связанные документы

* **[Порядок диагностики сети](./network_troubleshooting_order.md)** — методология «снизу вверх».
* **[Инструменты диагностики сети](./network_diagnostics_tools.md)** — обзор `ss`, `ip`, `tcpdump`.
* **[Управление очередями соединений](./Concepts/tcp_tuning/tcp_connection_queues.md)** — тюнинг `backlog` и `somaxconn`.

### См. также

* **[ethtool: диагностика железа](./Tools/ethtool.md)** — работа с Ring Buffers.
* **[Оптимизация NAPI и netdev_budget](./Concepts/napi_optimization.md)** — лимиты обработки пакетов.
* **[RSS, RPS, RFS: Многопоточность](./Concepts/rss_rps_rfs.md)** — балансировка нагрузки по ядрам.
* **[UDP — специфика потерь](../../Networking/Protocols/udp.md)** — почему UDP теряется чаще.
* **[Оптимизация буферов TCP](./Concepts/tcp_tuning/tcp_buffer_tuning.md)** — детальный тюнинг `rmem/wmem`.

### Сводная таблица диагностики потерь

| Симптом | Диагностика | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| `rx_missed_errors` растет | `ethtool -S eth0` | Ring Buffer NIC переполнен | Увеличить `ethtool -G eth0 rx 4096` |
| `softnet_stat` столбец 2 растет | `cat /proc/net/softnet_stat` | Переполнение `netdev_max_backlog` | Увеличить `net.core.netdev_max_backlog` |
| `softnet_stat` столбец 3 растет | `cat /proc/net/softnet_stat` | Исчерпание `netdev_budget` | Увеличить `net.core.netdev_budget` |
| `TcpExtListenDrops` растет | `nstat -az` | Accept backlog переполнен | Увеличить `somaxconn`, настроить приложение |
| `UdpInErrors` растет | `nstat -az` | Буферы UDP-сокетов переполнены | Увеличить `net.core.rmem_max` |
| `nf_conntrack: table full` | `dmesg`, `conntrack -S` | Таблица conntrack исчерпана | Увеличить `nf_conntrack_max`, сократить таймауты |
| `Recv-Q > 0` в `ss` | `ss -unmp` | Приложение не читает из сокета | Оптимизировать приложение, увеличить буферы |
| Дропы без видимых причин | `nft monitor trace` | Правило firewall | Исправить порядок правил |

### Best Practices (2026)

1.  **Проактивный мониторинг:** Настройте алерты на `softnet.dropped`, `ListenOverflows`, `UdpInErrors` и `conntrack` usage.
2.  **Постепенное изменение:** Увеличивайте параметры постепенно, а не сразу до максимальных значений. Мониторьте влияние на задержки (`si%` в `mpstat`).
3.  **Постоянство:** Сохраняйте изменения в `/etc/sysctl.d/99-*.conf`, а не только временно через `sysctl -w`.
4.  **Валидация после изменений:** Всегда проверяйте счетчики (`nstat`, `softnet_stat`, `ethtool -S`) после применения настроек.
5.  **Изоляция проблем:** Используйте `pwru` или `bpftrace` для точного определения места дропа, а не перебирайте параметры наугад.
6.  **Учет аппаратных ограничений:** Для 10G+ NIC настраивайте Ring Buffers и количество очередей через `ethtool`. Для 100G+ используйте Threaded NAPI (ядро 5.12+).
7.  **Безопасный откат:** Всегда имейте скрипт отката настроек. Используйте версионирование конфигурации (`/etc/sysctl.d/`).

### Типичные ошибки при диагностике

*   **Смешение аппаратных и программных потерь:** `rx_dropped` в `ip -s link` может расти из-за переполнения `netdev_max_backlog` (программный уровень), а не только из-за Ring Buffer NIC.
*   **Игнорирование Memory Pressure:** Даже если `softnet_stat` нулевой, пакеты могут отбрасываться на уровне `sk_buff` allocation. Проверяйте `dmesg | grep -i napi` и slab-память.
*   **Неучет cgroups/containers:** В Docker/Kubernetes параметры `sysctl` могут быть переопределены на уровне Pod security context. Проверяйте приоритет настроек.
*   **Отключение offloading для диагностики:** При анализе через `tcpdump` отключайте TSO/GRO (`ethtool -K eth0 tso off gro off`), иначе пакеты отображаются в неразделанном виде.
*   **Асимметричная маршрутизация и rp_filter:** Значение `net.ipv4.conf.all.rp_filter = 1` (Strict) может отбрасывать легитимные пакеты при асимметричной маршрутизации. Проверяйте `sysctl -a | grep rp_filter`.

### Связанные темы

* **[Прерывания в ядре](../Core/kernel/interrupts.md)** — архитектура Hard/Soft IRQ.
* **[Оптимизация NAPI и netdev_budget](./Concepts/napi_optimization.md)** — лимиты обработки пакетов.
* **[Многопоточная обработка трафика](./Concepts/rss_rps_rfs.md)** — распределение нагрузки по ядрам.
* **[ethtool: диагностика железа](./Tools/ethtool.md)** — настройка очередей, коалесценции, offloading.
* **[Управление очередями соединений](./Concepts/tcp_tuning/tcp_connection_queues.md)** — тюнинг `backlog` и `somaxconn`.
* **[Оптимизация буферов TCP](./Concepts/tcp_tuning/tcp_buffer_tuning.md)** — детальный тюнинг `rmem/wmem`.
* **[UDP — специфика потерь](../../Networking/Protocols/udp.md)** — почему UDP теряется чаще.
* **[Порядок диагностики сети](./network_troubleshooting_order.md)** — методология «снизу вверх».
* **[Инструменты диагностики сети](./network_diagnostics_tools.md)** — обзор `ss`, `ip`, `tcpdump`.
* **[Hardening сетевого стека Linux](./Security/network_hardening.md)** — sysctl для предотвращения потерь и защиты от атак.
