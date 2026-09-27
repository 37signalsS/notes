# Диагностика сокетов TCP в Linux

Данное руководство фокусируется на практическом применении инструментов анализа для проверки эффективности тюнинга и поиска узких мест в сетевом стеке. Полный справочник по флагам утилиты `ss` доступен в разделе **[Диагностика ss](../../../Diagnostics/Networking/ss.md)**.

## Определения

**Диагностика TCP-сокетов** — процесс сбора и интерпретации низкоуровневых метрик соединений (RTT, cwnd, потери) для оценки производительности и выявления сетевых аномалий на уровне ядра. Позволяет понять, почему соединение работает медленно (ограничение буфера, потери в сети или логика приложения).

**Socket Metrics (Метрики сокета)** — параметры внутреннего состояния TCP-стека для конкретной сессии, доступные через интерфейс `tcp_info` ядра. Позволяют понять, почему соединение работает медленно (ограничение буфера, потери в сети или логика приложения).

**tcp_info** — структура данных ядра Linux, содержащая полную информацию о состоянии TCP-соединения. Доступна через системный вызов `getsockopt(fd, IPPROTO_TCP, TCP_INFO, &info, &len)` или через утилиту `ss -ti`. Содержит 33+ полей, включая RTT, cwnd, ssthresh, retrans, bytes_sent/acked/received, pacing_rate, delivery_rate.

**netlink** — интерфейс ядра Linux для коммуникации с пользователями. Утилита `ss` использует netlink для получения информации о сокетах напрямую из ядра, что делает её значительно быстрее, чем `netstat`, который читает `/proc/net/tcp`.

**eBPF (Extended Berkeley Packet Filter)** — технология ядра, позволяющая запускать программы мониторинга сетевых событий (например, задержки функций стека) с минимальными накладными расходами без захвата полных пакетов. В 2026 году является основным инструментом для ad-hoc трассировки.

**bcc-tools** — набор инструментов на основе eBPF для диагностики сетевых проблем. Включает `tcpconnlat`, `tcpretrans`, `tcptop`, `tcpaccept`, `tcpdrop`, `tcpstates`, `tcprtt`, `tcplife` и другие.

**bpftrace** — язык для написания ad-hoc eBPF-скриптов с синтаксисом, напоминающим awk. Позволяет создавать кастомные трассировки для конкретных проблем. Требует ядра 4.14+ для полной функциональности.

**NIC Diagnostics** — диагностика на уровне сетевой карты (NIC) с использованием `ethtool -S` для проверки аппаратных ошибок, дропов и пропущенных пакетов. Позволяет отличить аппаратные проблемы от программных.

## Основные концепции

### Инструментарий 2026 года

| Уровень анализа | Инструмент | Основная задача | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Сессионный** | `ss -ti` | Глубокий анализ параметров конкретного TCP-соединения. | Анализ конкретного соединения, поиск узкого места. |
| **Системный** | `nstat -az` | Анализ глобальных счетчиков ошибок и событий ядра (SNMP). | Мониторинг в реальном времени, поиск аномалий. |
| **Профилирование** | `bpftrace`, `bcc` | Анализ задержек (Latency) и переходов состояний в реальном времени. | Ad-hoc трассировка, поиск хвостовых задержек. |
| **Аппаратный** | `ethtool -S` | Поиск дропов на уровне колец сетевой карты (NIC). | Поиск аппаратных проблем, дропов на L2. |
| **Пакетный** | `tcpdump` | Захват пакетов для анализа. | Детальный анализ протокола, поиск потерь. |
| **Статистический** | `ss -s` | Сводка по состояниям сокетов. | Быстрая оценка состояния системы. |

### Ключевые метрики ss -ti (Интерпретация)

При анализе вывода `ss -tin` (флаг `-n` отключает резолвинг имен для скорости) следует проверять:

*   **`rtt/mdev`**: Среднее время кругового обхода и его дисперсия. Высокий `mdev` указывает на джиттер или нестабильный канал.
*   **`cwnd`**: Текущее окно перегрузки (в MSS). Если оно стабильно на значении 10 при высоком RTT — проверьте настройки `initcwnd`.
*   **`ssthresh`**: Порог медленного старта. Если `cwnd` достигает `ssthresh` и перестает расти — это нормальное поведение.
*   **`pacing_rate` / `delivery_rate`**: Максимальная теоретическая скорость отправки и реальная достигнутая скорость.
    *   Если `pacing_rate` >> `delivery_rate`, значит стек готов слать быстрее, но сеть или приемник ограничивают поток.
*   **`app_limited`**: Состояние, когда TCP-стек простаивает, потому что приложение не отдает данные достаточно быстро.
*   **`retrans`**: Текущие ретрансмиссии (напр. `retrans:0/15` — сейчас 0, всего за сессию 15).
*   **`rcv_space`**: Текущее окно приема. Если оно маленькое, значит получатель (или его настройки буферов) является «бутылочным горлышком».
*   **`snd_wnd`**: Окно отправки (рекламируемое окно получателя). Если мало — получатель не успевает обрабатывать данные.
*   **`ato`**: Таймаут ACK (для delayed ACK). Высокие значения могут указывать на проблемы с задержкой ACK.
*   **`busy`**: Время занятости соединения (в мс). Полезно для оценки загрузки соединения.

### Таблица ключевых полей tcp_info

| Поле | Описание | Единицы | Диагностическое значение |
| :--- | :--- | :--- | :--- |
| `rtt` | Среднее время кругового обхода | мс | Высокое = сетевая задержка |
| `rttvar` | Дисперсия RTT | мс | Высокое = джиттер |
| `cwnd` | Окно перегрузки | MSS | Маленькое = потери/конгестия |
| `ssthresh` | Порог медленного старта | MSS | Определяет фазу congestion control |
| `retrans` | Ретрансмиссии | counter | Рост = потери в сети |
| `bytes_sent` | Отправлено байт | bytes | Объем переданных данных |
| `bytes_acked` | Подтверждено байт | bytes | Объем доставленных данных |
| `bytes_retrans` | Ретрансмитнуто байт | bytes | Объем ретрансмитнутых данных |
| `pacing_rate` | Скорость отправки | байт/с | Ограничен pacing |
| `delivery_rate` | Скорость доставки | байт/с | Реальная скорость |
| `rcv_space` | Окно приема | bytes | Ограничение получателя |
| `snd_wnd` | Окно отправки | bytes | Рекламируемое окно |
| `mss` | Максимальный размер сегмента | bytes | Типичное: 1460 |
| `pmtu` | Path MTU | bytes | Типичное: 1500 |
| `busy` | Время занятости | мс | Загрузка соединения |

### Правила выбора инструмента

| Вопрос | Лучший инструмент | Почему |
| :--- | :--- | :--- |
| **Кто подключен прямо сейчас?** | `ss -tanp` | Живая таблица сокетов через netlink |
| **Переполняется ли accept-очередь?** | `ss -ltn` + `nstat` | Глубина очереди + счетчик дропов |
| **Сколько ретрансмитов за 10 сек?** | `nstat` | Дельта за интервал |
| **Сколько TIME_WAIT сокетов?** | `ss -tn state time-wait \| wc -l` | Фильтрация по состоянию |
| **Частота неудачных соединений?** | `nstat` (`TcpAttemptFails`) | Счетчик дельты |
| **Быстрая сводка по сокетам** | `ss -s` | Однострочная разбивка по состояниям |
| **Аппаратные ошибки NIC** | `ethtool -S eth0` | Счетчики уровня L2 |
| **Хвостовые задержки** | `bpftrace` / `tcprtt` | Гистограммы RTT |
| **Ретрансмиты в реальном времени** | `tcpretrans` | Трассировка причин |

### Замена netstat на современные инструменты

| Старый `netstat` | Современный эквивалент |
| :--- | :--- |
| `netstat -tuanp` | `ss -tuanp` |
| `netstat -ltn` | `ss -ltn` |
| `netstat -s` | `nstat -az` (снимок) или `nstat` (дельта) |
| `netstat -i` | `ip -s link` |
| `netstat -rn` | `ip route` |
| `netstat -g` | `ip maddr` |

**Почему `netstat` устарел:**
*   Читает `/proc/net/tcp` — медленно на системах с десятками тысяч сокетов
*   Смешивает и переименовывает счетчики — трудно коррелировать с документацией
*   Не имеет встроенного дельта-режима — сложно определить "происходит ли это сейчас"
*   Не устанавливается в минимальных контейнерах (Alpine, slim Debian)

## Практические сценарии

### 1. Анализ производительности алгоритма BBR

Для систем, использующих BBR, важно отслеживать динамику окна и скорости:

```bash
# Детальный просмотр BBR-метрик для HTTPS соединений
ss -tin dst :443

# Интерпретация (пример):
# bbr wscale:7,7 rto:204 rtt:15.2/0.5 cwnd:1000 pacing_rate 10Gbps delivery_rate 8Gbps
```
*   Если `cwnd` большой, а `delivery_rate` низкий — ищите проблему в приложении или буферах приемника.
*   Если `pacing_rate` >> `delivery_rate` — стек готов слать быстрее, но сеть ограничивает.

### 2. Поиск скрытых аномалий через nstat

Глобальные счетчики показывают проблемы, которые трудно выловить на одном сокете:

```bash
# Проверка эффективности подтверждений (ACK)
nstat -az | grep -E 'TCPACKCompressed|TCPACKDelayed'

# Поиск признаков проблем с Path MTU или Middleboxes
nstat -az | grep -E 'TCPTimeouts|TCPRetransSegs|TCPTailLossProbe'

# Проверка переполнения очередей listen-сокетов
nstat -az | grep -E 'ListenOverflows|ListenDrops'
```
*   Рост **`TCPTimeouts`** при малом числе **`TCPRetransSegs`** указывает на полную потерю связи (черные дыры), а не на частичные потери пакетов.

### 3. Диагностика «зависших» соединений (Zero Window)

Если передача данных прекратилась, проверьте окно приемника:

```bash
# Найти сокеты, где удаленная сторона выставила нулевое окно
ss -tmo | grep 'window:0'
```
Это означает, что приложение на стороне получателя не успевает вычитывать данные из буфера сокета.

### 4. Real-time профилирование через eBPF

Для анализа «хвостовых» задержек (Tail Latency) используйте инструменты `bcc-tools`:

```bash
# Измерение времени Handshake (сеть или нагрузка на CPU?)
sudo tcpconnlat

# Отслеживание ретрансмитов в реальном времени с указанием причин
sudo tcpretrans

# Просмотр процессов, генерирующих максимальный трафик
sudo tcptop
```

### 5. Диагностика проблем с Kafka

Для анализа соединений Kafka:

```bash
# Просмотр соединений Kafka (порт 9092)
ss -tin dport = :9092

# Анализ ретрансмитов для Kafka
ss -tin dport = :9092 | grep -E "retrans|rtt|cwnd"

# Мониторинг accept-очередей Kafka
nstat -az | grep ListenOverflows

# Проверка состояния соединений
ss -s | grep -E "ESTAB|TIME-WAIT"
```

**Интерпретация:**
*   `cwnd` маленькое (< 10) при высоком RTT — конгестия в сети
*   `retrans` растет — потери пакетов
*   `app_limited` = 1 — приложение не успевает генерировать данные
*   `ListenOverflows` растет — переполнение accept-очереди Kafka

### 6. Диагностика Docker и контейнеров

Для анализа сетевых проблем в Docker:

```bash
# Просмотр соединений контейнера
docker exec <container> ss -tin

# Анализ соединений с хостом
ss -tin | grep -E "docker|br-"

# Проверка дропов на интерфейсе Docker
ethtool -S docker0 | grep -E "drop|error"

# Мониторинг через nstat на хосте
nstat -az | grep -E "ListenOverflows|ListenDrops|RetransSegs"
```

**Типичные проблемы Docker:**
*   **Network namespace:** Каждый контейнер имеет свою сетевую таблицу路由. Используйте `nsenter` для диагностики из контейнера.
*   **Bridge network:** Проблемы с маршрутизацией между контейнерами. Проверяйте `iptables -L -n`.
*   **Overlay network:** Проблемы с VXLAN-инкапсуляцией. Используйте `tcpdump -i docker0`.

### 7. Диагностика PostgreSQL

Для анализа соединений PostgreSQL:

```bash
# Просмотр соединений PostgreSQL (порт 5432)
ss -tin dport = :5432

# Анализ состояния соединений
ss -tin state established dport = :5432 | grep -E "rtt|cwnd|retrans"

# Проверка accept-очереди
nstat -az | grep ListenOverflows

# Мониторинг TIME_WAIT
ss -tn state time-wait dport = :5432 | wc -l
```

**Интерпретация:**
*   `rtt` стабильное и низкое — хорошее соединение
*   `cwnd` растет — нормальная работа congestion control
*   `ListenOverflows` растет — увеличьте `max_connections` или `somaxconn`
*   Много `TIME_WAIT` — используйте connection pooling (PgBouncer)

### 8. Анализ пакетов через tcpdump

Для детального анализа проблем:

```bash
# Захват трафика для конкретного хоста
sudo tcpdump -i eth0 host 192.168.1.100 -w capture.pcap

# Захват для конкретного порта
sudo tcpdump -i eth0 port 443 -w capture.pcap

# Анализ ретрансмитов в Wireshark
# Фильтр: tcp.analysis.retransmission
# Фильтр: tcp.analysis.fast_retransmission
# Фильтр: tcp.analysis.duplicate_ack
```

**Когда использовать tcpdump:**
*   Статистики указывают на проблему, но причина не ясна
*   Нужно увидеть последовательность событий (SYN, ACK, DATA, RETRANS)
*   Проблемы с MTU или фрагментацией
*   Поиск "призрачных" потерь пакетов

### 9. Анализ Ring Buffer и coalescing

Для диагностики проблем с производительностью NIC:

```bash
# Проверка текущих настроек Ring Buffer
ethtool -g eth0

# Проверка coalescing
ethtool -c eth0

# Проверка offloading
ethtool -k eth0 | grep -E "tcp-segmentation|generic-receive|checksum"

# Проверка статистики NIC
ethtool -S eth0 | grep -E "drop|error|miss|crc"
```

**Интерпретация:**
*   `rx_dropped` растет — увеличьте Ring Buffer (`ethtool -G eth0 rx 4096`)
*   `rx_crc_errors` растет — аппаратная проблема с NIC
*   `rx_missed_errors` растет — ядро не успевает обрабатывать пакеты
*   `rx_no_buffer_count` растет — нехватка буферов в ядре

### 10. Скрипт быстрой диагностики

```bash
#!/bin/bash
# Скрипт быстрой диагностики TCP-соединений

echo "=== TCP Socket Diagnostics ==="
echo "--- System Summary ---"
ss -s

echo "--- Listen Queues ---"
ss -ltn | awk 'NR>1 {print $1, $2, $4, $6}'

echo "--- Top 10 Connections by RTT ---"
ss -tin state established | grep -oP 'rtt:\K[\d.]+' | sort -n | tail -10

echo "--- Retransmissions ---"
nstat -az | grep -E "RetransSegs|TCPTimeouts|TailLossProbe"

echo "--- Listen Overflows ---"
nstat -az | grep -E "ListenOverflows|ListenDrops"

echo "--- Zero Window Connections ---"
ss -tmo | grep 'window:0'

echo "--- NIC Errors ---"
for iface in $(ls /sys/class/net/ | grep -v lo); do
    echo "Interface: $iface"
    ethtool -S $iface 2>/dev/null | grep -E "drop|error|miss" | head -5
done

echo "--- Memory Pressure ---"
nstat -az | grep -i "MemoryPressures"
```

## Дополнительная информация

### Таблица интерпретации симптомов

| Симптом | Инструмент -> Метрика | Что это значит | Решение |
| :--- | :--- | :--- | :--- |
| **Низкая скорость** | `ss -ti` -> `cwnd` | Если мал — потери в сети. Если велик — ограничение в буферах. | Увеличить буферы, проверить сеть |
| **Таймауты Handshake** | `tcpconnlat` | Проблема либо в RTT, либо в переполнении `somaxconn`. | Увеличить `somaxconn`, проверить `tcp_max_syn_backlog` |
| **Connection Refused** | `nstat` -> `ListenOverflows` | Приложение не успевает делать `accept()`. | Увеличить backlog приложения, оптимизировать accept |
| **Высокий CPU SoftIRQ** | `mpstat -P ALL` -> `%soft` | Сетевая карта перегружает одно ядро (нужна настройка RSS/RPS). | Настроить RSS/RPS, увеличить `netdev_max_backlog` |
| **Zero Window** | `ss -tmo` -> `window:0` | Получатель не успевает обрабатывать данные. | Увеличить `rmem` получателя, оптимизировать приложение |
| **Высокий RTT** | `ss -ti` -> `rtt` | Сетевая задержка или перегрузка маршрутизатора. | Проверить маршрут, использовать ближний CDN |
| **Ретрансмиты** | `nstat` -> `RetransSegs` | Потери пакетов в сети. | Проверить сеть, увеличить `initcwnd`, использовать BBR |
| **Memory Pressures** | `nstat` -> `MemoryPressures` | Ядро под давлением памяти. | Увеличить `tcp_mem`, оптимизировать буферы |
| **TIME_WAIT flood** | `ss -s` -> `TIME-WAIT` | Много коротких соединений. | Использовать connection pooling, включить `tcp_tw_reuse` |
| **Close-Wait** | `ss` -> `CLOSE-WAIT` | Приложение не закрывает соединения. | Исправить утечку соединений в приложении |

### Диагностика типичных проблем

**Проблема: Низкая пропускная способность**
```bash
# 1. Проверка RTT и cwnd
ss -tin state established | grep -E "rtt|cwnd"
# → rtt:150/50 cwnd:10 (высокий RTT, маленькое cwnd)

# 2. Проверка буферов
ss -tm | grep -E "skmem|rcv_space"
# → rcv_space: 32768 (маленькое)

# 3. Проверка ретрансмитов
nstat -az | grep RetransSegs
# → TcpRetransSegs 1234 0.0 (много ретрансмитов)

# Решение:
# Увеличить буферы
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 16777216"
sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 16777216"
```

**Проблема: Connection refused**
```bash
# 1. Проверка ListenOverflows
nstat -az | grep ListenOverflows
# → TcpExtTCPListenOverflows 5678 0.0

# 2. Проверка accept-очереди
ss -ltn | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*
# Recv-Q = 128 (очередь полна)

# 3. Проверка somaxconn
sysctl net.core.somaxconn
# → net.core.somaxconn = 128

# Решение:
sudo sysctl -w net.core.somaxconn=65535
```

**Проблема: Высокий CPU SoftIRQ**
```bash
# 1. Проверка SoftIRQ
mpstat -P ALL 2 | grep -E "CPU|%soft"
# → CPU  0  ...  45.00%soft  (слишком много)

# 2. Проверка RSS/RPS
cat /sys/class/net/eth0/queues/rx-0/rps_cpus
# → 0 (RSS не настроен)

# Решение:
# Настроить RSS
echo "ff" > /sys/class/net/eth0/queues/rx-0/rps_cpus

# Или настроить RPS
echo "ff" > /sys/class/net/eth0/queues/rx-0/rps_cpus
```

**Проблема: Зависшие соединения (Close-Wait)**
```bash
# 1. Поиск Close-Wait соединений
ss -tn state close-wait
# → CLOSE-WAIT  0  0  192.168.1.100:5432  10.0.0.1:43210

# 2. Определение процесса
ss -tnp state close-wait
# → users:(("postgres",pid=1234,fd=5))

# 3. Анализ утечки
lsof -p 1234 | grep -E "TCP|socket"

# Решение:
# Перезапустить процесс или исправить утечку в коде
kill -9 1234
```

### Edge Cases и ограничения

**1. Контейнеры и namespace:**
В Docker/Kubernetes:
*   Каждый контейнер имеет свой network namespace
*   Используйте `nsenter -t <pid> -n ss -tin` для диагностики из контейнера
*   Проверяйте `nstat` на хосте для глобальных счетчиков
*   Учитывайте overlay network (VXLAN) при анализе RTT

**2. Высокоскоростные сети (100G/400G):**
Для сетей с высокой пропускной способностью:
*   Используйте `ethtool -S` для проверки аппаратных дропов
*   Настройте RSS/RPS для распределения нагрузки
*   Увеличьте Ring Buffer (`ethtool -G`)
*   Отключите TSO/GSO для точного анализа (`ethtool -K eth0 tso off`)

**3. Виртуализация (KVM/Xen):**
В виртуальных машинах:
*   Проверяйте virtio-net драйверы
*   Анализируйте vhost-net производительность
*   Учитывайте гипервизор при анализе RTT
*   Используйте `sar -n DEV` для мониторинга виртуальных интерфейсов

**4. Многопоточные приложения:**
Для многопоточных приложений:
*   Используйте `ss -tnp` для определения потоков
*   Анализируйте `SO_REUSEPORT` для распределения соединений
*   Проверяйте `tcp_abort_on_overflow` при высокой нагрузке

### Мониторинг и алерты

**Настройка мониторинга через Prometheus + node_exporter:**
```yaml
# Примеры алертов
groups:
- name: tcp_socket_alerts
  rules:
  - alert: HighRetransmissions
    expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 100
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий уровень ретрансмиссий"
      description: "Rate ретрансмиссий > 100 в течение 5 минут"

  - alert: HighListenOverflows
    expr: rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Переполнение accept-очереди"
      description: "Rate переполнений > 10 в течение 5 минут"

  - alert: HighZeroWindow
    expr: node_netstat_TcpExt_TCPMemoryPressures > 100
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Давление памяти TCP"
      description: "Обнаружены TCP memory pressures > 100"

  - alert: HighSoftIRQ
    expr: rate(node_softnet_processed_total[5m]) > 1000000
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий SoftIRQ"
      description: "Rate обработки пакетов > 1M в течение 5 минут"
```

**Автоматизация диагностики:**
```bash
# Скрипт автоматической диагностики TCP
#!/bin/bash
LOG_FILE="/var/log/tcp_diagnostics.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

echo "=== TCP Diagnostics @ $TIMESTAMP ===" >> $LOG_FILE

# Проверка ретрансмитов
RETRANS=$(nstat -az | grep TcpRetransSegs | awk '{print $2}')
echo "RetransSegs: $RETRANS" >> $LOG_FILE

# Проверка ListenOverflows
OVERFLOWS=$(nstat -az | grep ListenOverflows | awk '{print $2}')
echo "ListenOverflows: $OVERFLOWS" >> $LOG_FILE

# Проверка соединений
CONNECTIONS=$(ss -s | grep "estab" | awk '{print $2}')
echo "Established: $CONNECTIONS" >> $LOG_FILE

# Проверка TIME_WAIT
TIMEWAIT=$(ss -tn state time-wait | wc -l)
echo "TIME_WAIT: $TIMEWAIT" >> $LOG_FILE

# Проверка ошибок NIC
for iface in $(ls /sys/class/net/ | grep -v lo); do
    ERRORS=$(ethtool -S $iface 2>/dev/null | grep -E "drop|error" | wc -l)
    echo "NIC $iface errors: $ERRORS" >> $LOG_FILE
done
```

### См. также
* **[Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)** — комплексная настройка параметров.
* **[Управление очередями соединений](./tcp_connection_queues.md)** — тюнинг `backlog` и `somaxconn`.
* **[Оптимизация буферов TCP](./tcp_buffer_tuning.md)** — настройка `rmem` и `wmem`.
* **[Диагностика надежности TCP](../../../../Networking/Protocols/TCP/reliability_mechanisms/diagnostics.md)** — теоретические основы анализа потерь.
* **[Алгоритм Нагла](../../../../Networking/Protocols/TCP/tcp_nagle_algorithm.md)** — когда `nodelay` спасает латентность.
* **[Диагностика ss](../../../Diagnostics/Networking/ss.md)** — полный справочник по флагам утилиты `ss`.
