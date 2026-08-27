# Диагностика TCP-соединений

## Определения

**Диагностика TCP-соединений** — системный процесс анализа жизненного цикла сокетов, направленный на выявление аномалий при установке соединений, мониторинг эффективности передачи данных и расследование причин некорректного завершения сессий.

**Ключевые области анализа:**
- **Здоровье Handshake:** Отсутствие задержек и отброшенных SYN-пакетов.
- **Целостность потока:** Минимизация ретрансмиссий и таймаутов (RTO).
- **Эффективность очередей:** Баланс между буферами приложения и сетевого стека.

**Стоимость диагностики:** Корректная идентификация корневой причины (root cause) критична, так как симптомы могут быть схожи у разных проблем. Например, и `TIME_WAIT`, и `CLOSE_WAIT` могут приводить к исчерпанию портов, но механизм и решение完全不同不同的。

---

## Методология диагностики (Bottom-up)

Диагностика должна следовать иерархии уровней OSI (от простого к сложному):

1. **Физический уровень (L1):** Проверка линка, ошибок на интерфейсе (CRC, collision, drop).
2. **Канальный уровень (L2):** ARP-таблица, MAC-адреса, VLAN-теги.
3. **Сетевой уровень (L3):** IP-адресация, маршрутизация, ICMP-связность, MTU.
4. **Транспортный уровень (L4):** Доступность портов, состояние TCP-сессий, ретрансмиссии, таймеры.
5. **Прикладной уровень (L7):** DNS-резолвинг, HTTP-ответы, логи приложения.

**Принцип "Исключения":** Начинайте с проверки самых простых и вероятных причин (сервис запущен? порт открыт? файрвол разрешает?), прежде чем углубляться в анализ пакетов.

---

## Основные инструменты

### 1. Утилита ss (Socket Statistics)

Основной инструмент в Linux (пакет `iproute2`), заменивший устаревший `netstat`. Извлекает данные напрямую из интерфейса `tcp_info` ядра через netlink (сложность O(1), в отличие от парсинга `/proc/net/tcp`).

**Базовый мониторинг состояний:**
```bash
# Подсчет всех TCP-соединений по их текущим состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c
# →   5000 ESTAB       (Активная передача)
# →    200 TIME_WAIT   (Ожидание очистки сети)
# →     15 CLOSE_WAIT  (Приложение не закрыло сокет)
# →      5 SYN-RECV    (Ожидание ACK от клиента)
# →      2 FIN-WAIT-2  (Ожидание FIN от партнера)
```

**Интерпретация Recv-Q / Send-Q:**
- **Состояние `LISTEN`:** `Recv-Q` = текущее количество соединений в Accept Queue; `Send-Q` = максимальный размер (min(somaxconn, backlog_приложения)).
- **Состояние `ESTABLISHED`:** `Recv-Q` = байты, принятые ядром, но еще не прочитанные приложением (если растет — приложение "тормозит"); `Send-Q` = байты, отправленные, но еще не подтвержденные удаленной стороной.

**Глубокий анализ параметров сессии (`ss -ti`):**
```bash
ss -ti dst 1.2.3.4
# → cubic rto:204 rtt:15.2/0.5 mdev:0.5 cwnd:120 ssthresh:50 retrans:0/125 delivery_rate 120Mbps
```
- **`rtt/mdev`:** Время круговой задержки и его среднее квадратичное отклонение. Рост `mdev` — признак нестабильности ("джиттера") канала.
- **`retrans`:** Формат `текущие_в_очереди/всего_за_сессию`. Указывает на хронические потери.
- **`cwnd`:** Текущий размер Congestion Window (в MSS). Если замер на малом значении — высокий процент потерь.
- **`ssthresh`:** Порог переключения из Slow Start в Congestion Avoidance. Резкое снижение указывает на потерю пакета.
- **`backoff`:** Счетчик экспоненциального увеличения RTO. Значение > 0 означает, что соединение "зависло" в ожидании.
- **`pacing_rate`:** Скорость отправки пакетов с учетом Pacing (предотвращает burst-нагрузку).
- **`delivery_rate`:** Реальная скорость доставки данных (учитывая потери и подтверждения).
- **`skmem`:** Память, выделенная ядром под сокет (буферы приема/отправки).

**Фильтрация по состояниям:**
```bash
ss -tan state established          # Только ESTABLISHED
ss -tan state time-wait            # Только TIME_WAIT
ss -tan state syn-recv             # Только SYN_RECV (ожидание ACK)
ss -tan dst 10.0.0.1               # Соединения с конкретным IP
ss -tan dport = :443               # Соединения на конкретный порт
ss -tan sport = :80                # Соединения с конкретного порта
ss -tanp state established         # С PID/именем процесса
ss -ti dst 10.0.0.1 | grep retrans # Фильтрация по ретрансмиссиям
```

### 2. Глобальная статистика через nstat

Показывает агрегированные счетчики SNMP стека TCP. Идеален для выявления массовых проблем на уровне всего сервера.

```bash
# Мониторинг отброшенных пакетов из-за очередей
nstat -az | grep -E 'TcpExtListenOverflows|TcpExtListenDrops|TcpRetransSegs'
# → TcpExtListenOverflows            15                 0.0
# → TcpExtListenDrops                15                 0.0
# → TcpRetransSegs                  150                 0.0
```
- `ListenOverflows`: Серверное приложение не успевает делать `accept()`.
- `ListenDrops`: SYN-пакет отброшен (не хватило памяти или переполнен backlog).
- `TcpRetransSegs`: Общий уровень ретрансмиссий в системе.

**Ключевые счетчики для диагностики:**
```bash
nstat -az | grep -E 'TcpExt(TCPTimeouts|TCPLostRetransmit|TCPSACKRecovery|TCPRenoRecovery|TCPFastRetrans)'
# → TcpExtTCPTimeouts              120                 0.0    # RTO-ретрансмиссии (тяжелые потери)
# → TcpExtTCPLostRetransmit         5                 0.0    # Потерянные ретрансмиссии
# → TcpExtTCPSACKRecovery          450                 0.0    # Восстановление через SACK (норма)
# → TcpExtTCPFastRetrans           120                 0.0    # Fast Retransmit (3 DupACK)
```

**Счетчики ошибок:**
```bash
nstat -az | grep -E 'TcpExt(TCPAbortOnTimeout|TCPAbortOnClose|TCPAbortOnMemory)'
# → TcpExtTCPAbortOnTimeout         8                 0.0    # Аварийное закрытие по таймауту
# → TcpExtTCPAbortOnClose           3                 0.0    # Данные не прочитаны при close()
# → TcpExtTCPAbortOnMemory          2                 0.0    # Нехватка памяти для сокета
```

### 3. Анализ через tcpdump

`tcpdump` — инструмент захвата и анализа пакетов на основе библиотеки `libpcap`. Позволяет увидеть "что реально происходит в сети".

**Базовый синтаксис:**
```bash
tcpdump -i <интерфейс> [фильтр] [параметры вывода]
```

**Интерпретация TCP-флагов в выводе:**
```bash
tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn|tcp-fin|tcp-rst) != 0'
# → Flags [S]    : SYN
# → Flags [S.]   : SYN-ACK
# → Flags [F]    : FIN
# → Flags [R]    : RST
# → Flags [P.]   : PSH-ACK (данные)
# → Flags [.]    : ACK
```

**Практические фильтры:**
```bash
# Только SYN-пакеты (для анализа handshake)
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0'

# Только RST-пакеты (для обнаружения отказов)
tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Пакеты с конкретного IP
tcpdump -i eth0 -nn host 10.0.0.1

# Пакеты на конкретный порт
tcpdump -i eth0 -nn port 443

# Пакеты с ошибками checksum
tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0' -vv | grep -i 'cksum'

# Захват с выводом в файл для анализа в Wireshark
tcpdump -i eth0 -w /tmp/capture.pcap port 8080

# Анализ задержки между SYN и SYN-ACK (iRTT)
tcpdump -i eth0 -nn -tt 'port 443 and (tcp[tcpflags] & tcp-syn != 0)'
```

**Что искать в tcpdump:**
- Отсутствие SYN-ACK в ответ на SYN → файрвол блокирует или сервер не слушает.
- RST-пакеты после SYN → порт закрыт или сервис упал.
- Повторные SYN (Retransmission) → SYN-пакет丢失 или задержка.
- Одинаковые sequence numbers в разных пакетах → дубликаты или重组 проблемы.

### 4. Трассировка системных вызовов (strace)

`strace` позволяет отслеживать все системные вызовы приложения, включая сокет-операции.

```bash
# Мониторинг только сетевых вызовов
strace -e trace=network -p <PID>
# → connect(3, {sa_family=AF_INET, sin_port=htons(80), sin_addr=inet_addr("10.0.0.1")}, 16) = -1 ETIMEDOUT (Connection timed out)

# Мониторинг accept() и connect()
strace -e trace=accept,accept4,connect -p <PID>
# → accept4(5, {sa_family=AF_INET, sin_port=htons(3306), sin_addr=inet_addr("10.0.0.2")}, [112 => 16]) = 7

# Мониторинг с фильтрацией по порту
strace -e trace=network -p <PID> 2>&1 | grep -E 'connect|accept'
```

**Типичные ошибки через strace:**
- `ETIMEDOUT`: Нет ответа на SYN (файрвол, недоступность хоста).
- `ECONNREFUSED`: Порт закрыт на сервере.
- `ECONNRESET`: Удаленная сторона сбросила соединение (RST).
- `EPIPE`: Попытка записи в закрытый сокет.
- `EAGAIN`: Сокет в неблокирующем режиме, операция не может быть выполнена немедленно.

### 5. Анализ открытых файлов (lsof)

`lsof` показывает все открытые файловые дескрипторы процесса, включая сокеты.

```bash
# Все TCP-сокеты процесса
lsof -p <PID> | grep -i tcp
# → java    1234  root  123u  IPv4  12345  TCP 10.0.0.1:8080->10.0.0.5:54321 (ESTABLISHED)

# Сокеты в LISTEN
lsof -i TCP -sTCP:LISTEN

# Сокеты в TIME_WAIT
lsof -i TCP -sTCP:TIME-WAIT

# Сокеты в CLOSE_WAIT (потенциальная утечка)
lsof -i TCP -sTCP:CLOSE-WAIT

# Поиск процесса, занявшего порт
lsof -i :8080
```

### 6. Аппаратная диагностика (ethtool)

`ethtool` показывает статистику сетевой карты, включая ошибки на аппаратном уровне.

```bash
# Счетчики ошибок интерфейса
ethtool -S eth0 | grep -E 'error|drop|miss|crc|collision'
# → rx_crc_errors: 15        ← Проблема с кабелем или NIC
# → rx_missed_errors: 8      ← Переполнение RX-очереди
# → tx_dropped: 3            ← TX-очередь переполнена

# Состояние линка
ethtool eth0 | grep -i 'link detected'
# → Link detected: yes

# Offloading (может влиять на tcpdump)
ethtool -k eth0 | grep -E 'checksum|segmentation|generic-receive'
# → rx-checksumming: on
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
```

### 7. eBPF и bpftrace (2026)

Инструменты eBPF (пакет `bcc-tools`) позволяют проводить диагностику с минимальными накладными расходами (overhead) без захвата трафика.

| Инструмент | Назначение | Пример вывода |
| :--- | :--- | :--- |
| **`tcpconnlat`** | Измеряет время от SYN до SYN-ACK (сетевая задержка). | `PID COMM IP LADDR LPORT RADDR RPORT USECS` |
| **`tcplife`** | Выводит лог завершенных соединений с их длительностью и трафиком. | `PID COMM IP LADDR LPORT RADDR RPORT TX_KB RX_KB DURATION` |
| **`tcpretrans`** | Показывает каждый факт повторной передачи с указанием IP и порта. | `TIME PID LADDR:LPORT DADDR:DPORT STATE TYPE` |
| **`tcpstates`** | Трассировка переходов состояний FSM в реальном времени. | `TIME PID COMM IP PROTO OLD NEW` |
| **`tcpdrop`** | Фиксирует моменты, когда ядро отбрасывает пакет. | `TIME PID COMM IP LADDR:LPORT DADDR:DPORT STATE REASON` |
| **`tcprtt`** | Гистограмма распределения RTT для соединений. | Гистограмма задержек по диапазонам |
| **`tcpaccept`** | Мониторинг завершения handshake на стороне сервера. | `PID COMM IP LADDR LPORT RADDR RPORT` |

```bash
# Измерение задержки handshake
sudo tcpconnlat -p 80
# → PID    COMM         IP  LADDR          LPORT  RADDR          RPORT  USECS
# → 1234   curl         4   1.1.1.1        54321  2.2.2.2        80     15234

# Мониторинг ретрансмиссий в реальном времени
sudo tcpretrans
# → TIME     PID    LADDR:LPORT          DADDR:DPORT          STATE       TYPE
# → 12:00:01 123    1.1.1.1:443       >  2.2.2.2:54321        ESTABLISHED RTO

# Анализ распределения RTT
sudo tcprtt -p 80 -i 1 -d
# → [16, 32) ms : 450 |**********|
# → [32, 64) ms : 120 |***|
# → [512, 1024) ms : 2 |*|
```

---

## Интерпретация критических аномалий

| Симптом | Состояние/Метрика | Диагностический вывод | Следующий шаг |
| :--- | :--- | :--- | :--- |
| **Зависание `connect()`** | `SYN_SENT` в `ss` | Сетевой экран отбрасывает пакеты (DROP) или хост выключен. | `tcpdump` для подтверждения; проверка файрвола. |
| **Мгновенный отказ** | `CLOSED` + RST в `tcpdump` | Порт закрыт приложением или заблокирован (REJECT). | Проверить `ss -tlnp`; проверить `iptables -S`. |
| **Утечка дескрипторов** | `CLOSE_WAIT` (растет) | Приложение "зависло": партнер прислал FIN, но `close()` не вызван. | `lsof -p <PID> \| grep CLOSE-WAIT`; исправить код. |
| **Исчерпание портов** | `TIME_WAIT` (max) | Слишком много коротких соединений. | `tcp_tw_reuse=1`; Connection Pool; `ss -tan state time-wait \| wc -l`. |
| **Низкий throughput** | `cwnd` замер на малом значении | Высокий процент потерь или ограничение `rwnd` клиента. | `nstat -az TcpRetransSegs`; `tcpretrans` для типа потерь. |
| **Высокий RTT** | `rtt >> 20ms` (LAN) или `rtt >> 100ms` (WAN) | Проблемы маршрутизации, Bufferbloat, или проблемы на L1/L2. | `mtr` для маршрута; `ethtool -S` для ошибок NIC. |
| **Spurious Retransmissions** | Ретрансмиссии без реальных потерь | Задержка ACK или проблемы с таймерами. | `tcpdump` для анализа ACK; проверка `tcp_delack_min`. |
| **Синхронное закрытие** | `CLOSING` состояние | Обе стороны отправили FIN одновременно. | Нормальное явление; нет действия требуется. |

---

## Практические сценарии

### Сценарий 1: Диагностика Port Exhaustion на балансировщике

**Проблема:** Приложение не может открыть новое соединение с БД, появляется ошибка `Cannot assign requested address`.

**Пошаговая диагностика:**
1. Проверить количество сокетов в `TIME_WAIT`:
   ```bash
   ss -tan state time-wait | wc -l
   # → 28000 (при пороге 32768 — критически много)
   ```
2. Проверить диапазон эфемерных портов:
   ```bash
   sysctl net.ipv4.ip_local_port_range
   # → net.ipv4.ip_local_port_range = 32768 60999 (28232 порта)
   ```
3. Если количество `TIME_WAIT` близко к размеру диапазона — порты исчерпаны.
4. Проверить, какие именно порты заняты:
   ```bash
   ss -tan state time-wait | awk '{print $4}' | cut -d: -f2 | sort -n | head -5
   # → 32768, 32769, 32770 ... 60999 (весь диапазон занят)
   ```

**Решение:**
```bash
# Включение переиспользования TIME_WAIT (для клиентских соединений)
sysctl -w net.ipv4.tcp_tw_reuse=1

# Расширение диапазона портов (если поддерживается)
sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# Переход на Unix Domain Sockets (для локальной БД) или Persistent Connections
```

### Сценарий 2: Поиск причин Tail Latency (Хвостовой задержки)

**Проблема:** 99-й перцентиль запросов выполняется в 10 раз дольше обычного.

**Пошаговая диагностика:**
1. Использование `tcprtt` (eBPF) для анализа распределения RTT:
   ```bash
   sudo tcprtt -p 80 -i 1 -d
   # → [16, 32) ms : 450 |**********|
   # → [32, 64) ms : 120 |***|
   # → [512, 1024) ms : 2 |*|
   ```
2. Если есть всплески в диапазоне >500мс — проверить ретрансмиссии:
   ```bash
   nstat -az TcpRetransSegs
   # → TcpRetransSegs  150  0.0
   ```
3. Дифференциация типа потерь:
   - **Случайные потери:** `retrans` растет, но `rtt` стабильно. Характерно для Wi-Fi.
   - **Bufferbloat:** `rtt` растет под нагрузкой без потерь. Характерно для промежуточных маршрутизаторов с большими буферами.

**Решение:** Для Bufferbloat — переключение на BBR или настройка AQM (fq_codel, CAKE). Для случайных потерь — проверка L1/L2 (кабель, NIC).

### Сценарий 3: Анализ tcpdump при ошибке Connection Refused

**Проблема:** `curl` возвращает `Connection refused`.

**Пошаговая диагностика:**
1. Захват SYN и RST пакетов:
   ```bash
   sudo tcpdump -i eth0 -nn 'port 8080 and (tcp[tcpflags] & (tcp-syn|tcp-rst) != 0)'
   # → 12:00:01.000 IP 10.0.0.1.54321 > 10.0.0.2.8080: Flags [S], seq 1000
   # → 12:00:01.001 IP 10.0.0.2.8080 > 10.0.0.1.54321: Flags [R.], seq 2000, ack 1001
   ```
2. Наличие `Flags [R.]` (RST-ACK) означает, что порт закрыт на сервере.
3. Проверить, что сервис слушает на правильном интерфейсе:
   ```bash
   ss -tlnp | grep :8080
   # → LISTEN  0  128  127.0.0.1:8080  0.0.0.0:*  users:(("app",pid=1234,fd=5))
   # ОШИБКА: слушает только на localhost!
   ```

**Решение:** Настроить сервис на прослушивание `0.0.0.0:8080` или `:::8080`.

### Сценарий 4: Диагностика через strace при зависании приложения

**Проблема:** Приложение "зависает" при обработке запроса, клиенты получают таймаут.

**Пошаговая диагностика:**
1. Найти PID процесса:
   ```bash
   ss -tlnp | grep :8080
   # → users:(("app",pid=1234,fd=5))
   ```
2. Запустить strace с фильтрацией по сети:
   ```bash
   sudo strace -e trace=network -p 1234
   # → connect(7, {sa_family=AF_INET, sin_port=htons(3306), sin_addr=inet_addr("10.0.0.2")}, 16) = -1 ETIMEDOUT (Connection timed out)
   ```
3. Ошибка `ETIMEDOUT` при `connect()` к БД указывает на проблему с доступностью БД.
4. Проверить маршрутизацию:
   ```bash
   ip route get 10.0.0.2
   # → 10.0.0.2 via 10.0.0.1 dev eth0 src 10.0.0.1
   ```

**Решение:** Проверить доступность БД; проверить файрвол между приложением и БД.

### Сценарий 5: Диагностика через lsof при утечке сокетов

**Проблема:** Приложение не может открыть новые соединения, появляется `Too many open files`.

**Пошаговая диагностика:**
1. Подсчитать общее количество открытых файлов:
   ```bash
   ls /proc/<PID>/fd | wc -l
   # → 4096 (лимит ulimit -n)
   ```
2. Показать только TCP-сокеты:
   ```bash
   lsof -p <PID> | grep -c TCP
   # → 3800 (绝大部分 сокетов — TCP)
   ```
3. Показать распределение по состояниям:
   ```bash
   lsof -p <PID> | grep TCP | awk '{print $NF}' | sort | uniq -c | sort -rn
   # → 3200 (ESTABLISHED)
   # →  500 (CLOSE_WAIT)   ← Проблема: приложение не закрывает сокеты
   # →  100 (TIME_WAIT)
   ```

**Решение:** Исправить утечку в коде (вызов `close()` для сокетов в `CLOSE_WAIT`).

### Сценарий 6: Диагностика переполнения Accept Queue

**Проблема:** Серверные приложения не успевают обрабатывать входящие соединения.

**Пошаговая диагностика:**
1. Проверить текущее состояние Accept Queue:
   ```bash
   ss -tlnp
   # → LISTEN  128  128  0.0.0.0:80  0.0.0.0:*
   # Recv-Q = 128, Send-Q = 128 → Accept Queue переполнена!
   ```
2. Проверить статистику переполнений:
   ```bash
   nstat -az | grep -E 'ListenOverflows|ListenDrops'
   # → TcpExtListenOverflows  150  0.0
   # → TcpExtListenDrops      150  0.0
   ```
3. Проверить `somaxconn`:
   ```bash
   sysctl net.core.somaxconn
   # → net.core.somaxconn = 128
   ```

**Решение:**
```bash
# Увеличение somaxconn
sysctl -w net.core.somaxconn=65535

# Увеличение backlog в приложении (Nginx)
# listen 80 backlog=16384;

# Увеличение backlog в приложении (Redis)
# tcp-backlog 511
```

### Сценарий 7: Диагностика влияния Firewall на соединение

**Проблема:** Клиент получает `Connection timed out` вместо `Connection refused`.

**Пошаговая диагностика:**
1. Определить тип блокировки:
   ```bash
   # Если файрвол DROP — клиент не получает ответа и ждет таймаута
   # Если файрвол REJECT — клиент получает RST и ошибку immediately

   sudo tcpdump -i eth0 -nn 'port 8080 and (tcp[tcpflags] & (tcp-syn) != 0)'
   # → Пакет SYN уходит, но SYN-ACK не возвращается → DROP
   ```
2. Проверить правила файрвола:
   ```bash
   sudo iptables -L INPUT -v -n | grep -E "8080|DROP|REJECT"
   # → pkts bytes target     prot opt in     out     source      destination
   # →  100  6000 DROP       tcp  --  *      *       0.0.0.0/0   0.0.0.0/0  tcp dpt:8080
   ```

**Решение:** Добавить правило ACCEPT для порта 8080 или изменить DROP на REJECT.

### Сценарий 8: Полный рабочий процесс диагностики TCP

**Этап 1: Сбор информации**
```bash
# 1. Состояние соединений
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# 2. Глобальная статистика
nstat -az | grep -E 'Retrans|Timeout|Listen|Abort'

# 3. Ошибки NIC
ethtool -S eth0 | grep -E 'error|drop|miss'
```

**Этап 2: Анализ симптомов**
- Нет соединений → проверить `ss -tlnp` (сервис слушает?)
- Много `TIME_WAIT` → проверить `tcp_tw_reuse` и диапазон портов
- Много `CLOSE_WAIT` → утечка в приложении
- Много ретрансмиссий → проверить `mtr` и `ethtool -S`

**Этап 3: Глубокий анализ**
```bash
# tcpdump для захвата пакетов
sudo tcpdump -i eth0 -nn port 8080 -w /tmp/debug.pcap

# ss -ti для конкретного соединения
ss -ti dst 10.0.0.2 | grep -E 'rtt|retrans|cwnd'

# strace для анализа системных вызовов
sudo strace -e trace=network -p <PID> -f
```

**Этап 4: Верификация решения**
```bash
# Повторить сбор метрик
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c
nstat -az | grep -E 'Retrans|Timeout'
```

---

## Диагностические команды (агрегированная секция)

### Мониторинг состояний
```bash
# Подсчет соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# Просмотр слушающих портов с процессами
ss -tlnp

# Соединения в ESTABLISHED с метриками
ss -ti state established

# Соединения в SYN_RECV (ожидание ACK)
ss -tan state syn-recv

# Соединения в CLOSE_WAIT (потенциальная утечка)
ss -tanp state close-wait
```

### Анализ производительности
```bash
# Глобальная статистика ретрансмиссий
nstat -az | grep -E 'Retrans|Timeout|SACK'

# Конкретное соединение с метриками
ss -ti dst 10.0.0.2

# Измерение RTT через ping (для оценки базовой задержки)
ping -c 10 10.0.0.2

# Анализ маршрута и потерь
mtr --report --report-cycles 10 10.0.0.2
```

### Захват пакетов
```bash
# SYN-пакеты (для анализа handshake)
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0'

# RST-пакеты (для обнаружения отказов)
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Захват в файл для Wireshark
sudo tcpdump -i eth0 -w /tmp/capture.pcap port 8080

# Анализ iRTT
sudo tcpdump -i eth0 -nn -tt 'port 443 and (tcp[tcpflags] & tcp-syn != 0)'
```

### Трассировка и eBPF
```bash
# Трассировка системных вызовов
sudo strace -e trace=network -p <PID>

# Открытые файлы процесса
lsof -p <PID> | grep TCP

# eBPF: задержка handshake
sudo tcpconnlat -p 80

# eBPF: ретрансмиссии
sudo tcpretrans

# eBPF: распределение RTT
sudo tcprtt -p 80 -i 1 -d
```

---

## Дополнительная информация

### Типичные ошибки (Errno) и их значение

| Код | Название | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **ECONNREFUSED** | Connection refused | На порту никто не слушает или файрвол блокирует SYN. | Проверить `ss -tlnp`, firewall (`iptables -L -n`), routing. |
| **ETIMEDOUT** | Connection timed out | Нет ответа (проблемы с маршрутизацией, дроп пакетов). | `traceroute`, `ping`, проверка маршрутов, файрволов. |
| **ECONNRESET** | Connection reset by peer | Удаленная сторона принудительно сбросила соединение (`RST`). | Приложение на другой стороне упало или вызвало `close()` с `SO_LINGER`. |
| **EPIPE** | Broken pipe | Попытка записи в сокет, который уже закрыт удаленной стороной. | Обработать `SIGPIPE` (`signal(SIGPIPE, SIG_IGN)`), проверять возврат `send()`. |
| **EADDRINUSE** | Address already in use | Порт занят другим процессом или в `TIME_WAIT`. | `SO_REUSEADDR`, поиск процесса через `ss -ltnp`, завершение процесса. |
| **EADDRNOTAVAIL** | Cannot assign requested address | Исчерпание портов (`TIME_WAIT`) или исчерпание IP-адресов. | `tcp_tw_reuse`, расширение `ip_local_port_range`, connection pooling. |
| **EAGAIN / EWOULDBLOCK** | Resource temporarily unavailable | Сокет в неблокирующем режиме, операция не может быть выполнена немедленно. | Повторить операцию через `poll()`/`epoll` или `select()`. |

### Sysctl-параметры для диагностики и управления

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`net.ipv4.tcp_syn_retries`** | 6 | Количество повторных SYN перед ETIMEDOUT на стороне клиента. |
| **`net.ipv4.tcp_synack_retries`** | 5 | Количество повторных SYN-ACK перед закрытием соединения на стороне сервера. |
| **`net.ipv4.tcp_retries2`** | 15 | Количество повторных передач перед разрывом ESTABLISHED-соединения. |
| **`net.ipv4.tcp_max_syn_backlog`** | 1024 | Размер очереди полуоткрытых соединений (SYN backlog). |
| **`net.core.somaxconn`** | 128 | Максимальный размер Accept Queue (полностью установленных соединений). |
| **`net.ipv4.tcp_tw_reuse`** | 0 | Переиспользование сокетов в TIME_WAIT для клиентских соединений. |
| **`net.ipv4.ip_local_port_range`** | 32768 60999 | Диапазон эфемерных портов для исходящих соединений. |
| **`net.ipv4.tcp_abort_on_overflow`** | 0 | Отправка RST при переполнении Accept Queue (1 = RST, 0 = игнорирование). |

### См. также

- **[Состояния TCP](./tcp_connection_states.md)** — описание всех состояний конечного автомата (FSM).
- **[Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — параметры тюнинга для решения найденных проблем.
- **[Надежность TCP](../reliability_mechanisms/diagnostics.md)** — диагностика ретрансмиссий и таймеров.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (современная спецификация).
- **RFC 6298:** Computing TCP's Retransmission Timer (алгоритмы RTO).
- **RFC 793:** Transmission Control Protocol (классический стандарт).
- **RFC 7413:** TCP Fast Open.
- **RFC 2018:** TCP Selective Acknowledgment Options.
