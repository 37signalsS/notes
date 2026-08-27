# Установка TCP-соединения (Handshake)

## Определения

**Установка TCP-соединения (3-way Handshake)** — фундаментальный процесс согласования параметров между клиентом и сервером для создания надежного, полнодуплексного логического канала передачи данных.

**Active Open vs Passive Open:**
- **Active Open:** Клиент инициирует соединение, вызывая системный вызов `connect()`. Переход из `CLOSED` в `SYN_SENT` после отправки SYN.
- **Passive Open:** Сервер вызывает `bind()` и `listen()`, переводя сокет в состояние `LISTEN`. Ожидает входящие SYN-запросы.

**Три фундаментальные цели процесса:**
1.  Уведомление целевого узла о намерении передавать данные.
2.  Синхронизация **Начальных порядковых номеров (Initial Sequence Numbers, ISN)** для корректной сборки потока байт.
3.  Согласование сетевых опций (MSS, Window Scale, SACK, Timestamps) для оптимизации скорости передачи и обеспечения надежности.

**Стоимость установки соединения:** Стандартный three-way handshake требует **1 RTT** (Round-Trip Time) перед передачей первого байта полезных данных. В сочетании с TLS 1.2 это добавляет еще 2 RTT (итого 3 RTT). TLS 1.3 сокращает задержку до 1 RTT (или 0-RTT при повторном подключении).

---

## Основные концепции

### Трехэтапное рукопожатие (3-way Handshake)

```text
Клиент (Active Open)                  Сервер (Passive Open)
     |                                     |
     |  1. SYN (seq=X, Options) ----------> |  Сервер в LISTEN
     |                                     |  Переход в SYN_RECEIVED
     |  2. <---- SYN-ACK (seq=Y, ack=X+1) --|  
     |  Клиент в SYN_SENT                  |
     |                                     |
     |  3. ACK (seq=X+1, ack=Y+1) --------> |
     |  Клиент в ESTABLISHED               |  Сервер в ESTABLISHED
```

1.  **SYN (Synchronize):** Клиент случайным образом выбирает свой ISN (`X`) и отправляет его серверу в пакете с флагом SYN. В этом же пакете передаются опции (например, MSS клиента, поддержка SACK, Window Scale).
2.  **SYN-ACK:** Сервер подтверждает получение ISN клиента, отправляя `ack=X+1` (что означает: "я готов принять байт X+1"). Одновременно сервер выбирает свой собственный случайный ISN (`Y`) и передает его клиенту, устанавливая флаги SYN и ACK. Сервер также объявляет свои опции (MSS, SACK OK, Window Scale, Timestamps).
3.  **ACK (Acknowledge):** Клиент подтверждает получение ISN сервера, отправляя `ack=Y+1`. На этом этапе соединение считается установленным, и клиент уже может прикрепить полезную нагрузку к этому пакету (в стандартном режиме — без TFO данные начнутся со следующего пакета).

**Переходы состояний FSM:**
```
CLOSED → (Active Open) → SYN_SENT → (получен SYN-ACK) → ESTABLISHED
CLOSED → (Passive Open) → LISTEN → (получен SYN) → SYN_RECEIVED → (получен ACK) → ESTABLISHED
```

**Примечание:** В состоянии `SYN_RECEIVED` сервер может отбросить соединение, если не поступает ACK в течение `tcp_synack_retries` попыток (по умолчанию ~127 секунд, или 5 ретрансмиссий).

### Безопасность ISN (Initial Sequence Number)

Исторически ISN начинался с 0 или увеличивался предсказуемо. Это приводило к уязвимостям **TCP Sequence Prediction**, позволяя злоумышленникам подменять пакеты в чужой сессии (Session Hijacking).

**Современный механизм генерации ISN (RFC 6528):**
- ISN генерируется с использованием криптографически стойкого PRNG (Pseudo-Random Number Generator).
- Алгоритм учитывает **5-tuple** (源IP, 目标IP, 源端口, 目标端口) и случайный секрет ядра, обновляемый при каждой перезагрузке.
- ISN никогда не начинается с 0 и увеличивается на 1 каждые 4 наносекунды (для защиты от атак предсказания).

**Взаимодействие с PAWS (Protection Against Wrapped Sequences):**
- Опция Timestamps (RFC 7323) помогает обнаруживать устаревшие пакеты из предыдущих соединений с тем же 5-tuple.
- Если пакет имеет Timestamp, меньший последнего принятого для этого соединения, он отбрасывается. Это критично для высокоскоростных каналов (10G+), где последовательность номеров может "обернуться" (wrap around).

**Формирование ISN для SYN-пакета:**
- SYN-пакет **всегда** содержит флаг SYN, поэтому他的seq поле содержит ISN (а не реальные данные).
- Первый байт полезных данных будет иметь номер `ISN + 1`.

### Согласование опций (Options Negotiation)

Опции TCP передаются **только в пакетах SYN и SYN-ACK**. Если они не согласованы на этом этапе, использовать их в дальнейшем невозможно.

- **MSS (Maximum Segment Size):** Размер полезной нагрузки (в байтах). Узлы объявляют свой предел (обычно `MTU - 40` для IPv4: 20 байт IP + 20 байт TCP). Итоговое значение не обязано быть симметричным. Для VPN-туннелей (GRE, IPsec, IPIP) MSS должен быть уменьшен на размер инкапсуляции (обычно 50-80 байт).
- **SACK (Selective ACK):** Разрешение подтверждать пакеты выборочно, не сбрасывая всю последовательность при потере. Опция `sackOK` передается в SYN. Полная опция SACK (RFC 2018) содержит блоки Left/Right Edge, указывающие на непрерывные сегменты данных, полученные сервером.
- **Window Scale (WS):** Множитель для поля Window Size. Согласование WS критично, так как базовое поле в заголовке TCP ограничено 64 КБ. Значение `wscale 7` означает множитель $2^7 = 128$, что позволяет объявлять окна до 1 ГБ.
- **Timestamps (RFC 7323):** Опция содержит два поля: `TSval` (текущее время отправителя) и `TSecr` (эхо последнего принятого Timestamp). Используется для расчета RTT и защиты от PAWS. Каждые 10 мс генерируется новое значение Timestamp.
- **NOP (No Operation):** Паддинг-опция (Kind 1), используемая для выравнивания других опций по границам байт.

**Эффективный MSS с учетом Timestamps:**
При согласовании Timestamps добавляется 12 байт к заголовку TCP (10 байт опции + 2 байта NOP). Therefore:
```
Эффективный MSS = MTU - 20 (IP) - 20 (TCP) - 12 (Timestamps) = MTU - 52
```
При MTU 1500: MSS = 1448 байт (вместо 1460 без Timestamps).

### TCP Fast Open (TFO)

**TCP Fast Open (RFC 7413)** — расширение, позволяющее передавать данные прикладного уровня уже в **первом** пакете SYN (так называемый 0-RTT).

- **Механизм:** Клиент запрашивает TFO-cookie у сервера при первом (обычном) подключении. При последующих подключениях клиент вставляет этот Cookie и Payload прямо в пакет SYN.
- **Sysctl настройка в Linux:**
  ```bash
  # Включение TFO (битовая маска):
  # 1 = включить для исходящих соединений
  # 2 = включить для входящих соединений
  # 3 = включить для обоих
  sysctl -w net.ipv4.tcp_fastopen=3
  ```
- **Риски:** Требует защиты от Replay-атак на стороне сервера, так как пакет SYN с данными может быть продублирован злоумышленником. Серверы должны использовать TFO только для идемпотентных запросов (GET, HEAD).
- *Подробнее:* [TCP Fast Open в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_fast_open.md).

### SYN Cookies и защита от SYN-флуда

**SYN Cookies (RFC 4987)** — механизм защиты от SYN-флуда, активируемый при переполнении SYN backlog.

**Как работают SYN Cookies:**
1. При переполнении `tcp_max_syn_backlog` ядро переходит в режим SYN Cookies.
2. Сервер не выделяет память под запись в очереди, а шифрует параметры соединения (MSS, Window Scale, SACK) в поле `Sequence Number` пакета SYN-ACK.
3. Когда клиент отправляет ACK с `ack=Y+1`, сервер декодирует ISN и восстанавливает параметры соединения.

**Ограничения SYN Cookies:**
- Невозможно согласовать Timestamps (поле ISN занято параметрами).
- Доступно только 8 комбинаций MSS (из-за ограничения 3 бит в ISN).
- Не работает для TCP Fast Open (TFO требует выделения памяти под Cookie).

**Настройка:**
```bash
# Включение SYN Cookies (рекомендуется всегда)
sysctl -w net.ipv4.tcp_syncookies=1

# Размер SYN backlog
sysctl -w net.ipv4.tcp_max_syn_backlog=16384
```

### Sysctl-параметры для управления рукопожатием

| Параметр | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`net.ipv4.tcp_syn_retries`** | 6 | Количество повторных SYN перед ETIMEDOUT на стороне клиента. |
| **`net.ipv4.tcp_synack_retries`** | 5 | Количество повторных SYN-ACK перед закрытием соединения на стороне сервера. |
| **`net.ipv4.tcp_max_syn_backlog`** | 1024 | Размер очереди полуоткрытых соединений (SYN backlog). |
| **`net.ipv4.tcp_syncookies`** | 1 | Включение защиты от SYN-флуда через SYN Cookies. |
| **`net.core.somaxconn`** | 128 | Максимальный размер Accept Queue (полностью установленных соединений). |
| **`net.ipv4.tcp_fastopen`** | 1 | Битовая маска для TCP Fast Open (1=client, 2=server, 3=both). |

**Рекомендации по `tcp_syn_retries`:**
| Значение | Общее время до ETIMEDOUT | Сценарий |
| :--- | :--- | :--- |
| **1** | ~3 сек | Внутри-ЦОД, low-latency сети |
| **2** | ~7 сек | VLAN, локальные сети |
| **3** | ~15 сек | Значение по умолчанию в некоторых дистрибутивах |
| **6** | ~63 сек | Значение по умолчанию в Linux |

---

## Практические сценарии

### Сценарий 1: Диагностика рукопожатия через tcpdump

Анализ пакетов позволяет увидеть, какие опции были согласованы, и выявить асимметрию задержек.

```bash
# Перехват только SYN и SYN-ACK пакетов
sudo tcpdump -i eth0 -nn -v 'tcp[tcpflags] & (tcp-syn) != 0'
# → 12:00:01.000 IP 1.1.1.1.54321 > 2.2.2.2.80: Flags [S], seq 1000, win 65535, options [mss 1460,sackOK,wscale 7]
# → 12:00:01.015 IP 2.2.2.2.80 > 1.1.1.1.54321: Flags [S.], seq 2000, ack 1001, win 28960, options [mss 1460,sackOK,wscale 7]
```

**Интерпретация:**
- `Flags [S]`: SYN пакет. `Flags [S.]`: SYN-ACK пакет.
- `wscale 7`: Согласован множитель окна $2^7 = 128$.
- `Разница во времени (0.015s)`: RTT между узлами составляет ~15 мс.
- Отсутствие `TSval` в опциях: Timestamps не согласованы (или не поддерживаются одной из сторон).

**Диагностика асимметричных проблем:**
```bash
# Анализ задержки только для特定 порта
sudo tcpdump -i eth0 -nn 'tcp port 443 and (tcp[tcpflags] & (tcp-syn) != 0)' -tt
# → Замер времени между SYN и SYN-ACK для оценки сетевой задержки
```

### Сценарий 2: Переполнение SYN Backlog

Если сервер не успевает обрабатывать входящие SYN-запросы (или подвергается DDoS-атаке SYN Flood), он перестает отвечать SYN-ACK, и клиент получает таймаут.

**Диагностика:**
```bash
# Проверка статистики сетевого стека на наличие отброшенных SYN
nstat -az | grep TcpExtListenDrops
# → TcpExtListenDrops                150                 0.0

# Проверка конкретных счетчиков SYN backlog
nstat -az | grep -E 'Syncookies|ListenOverflows|ReqQFullDrop'
# → TcpExtSyncookiesSent             0                 0.0
# → TcpExtSyncookiesRecv             0                 0.0
# → TcpExtSyncookiesFailed           0                 0.0
# → TcpExtTCPListenOverflows         0                 0.0
```

**Решение:**
```bash
# Увеличение SYN backlog
sysctl -w net.ipv4.tcp_max_syn_backlog=16384

# Включение SYN Cookies
sysctl -w net.ipv4.tcp_syncookies=1

# Сохранение настроек
echo "net.ipv4.tcp_max_syn_backlog = 16384" | sudo tee /etc/sysctl.d/99-syn-backlog.conf
echo "net.ipv4.tcp_syncookies = 1" | sudo tee -a /etc/sysctl.d/99-syn-backlog.conf
sudo sysctl -p /etc/sysctl.d/99-syn-backlog.conf
```

### Сценарий 3: Диагностика через ss и nstat

**Мониторинг состояний соединений:**
```bash
# Подсчет соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c
# →   5000 ESTAB       (Активная передача)
# →    200 TIME_WAIT   (Ожидание очистки)
# →     15 CLOSE_WAIT  (Приложение не закрыло сокет)
# →      5 SYN-RECV    (Ожидание ACK от клиента)

# Просмотр SYN-RECV соединений с процессами
ss -tanp state syn-recv
# → SYN-RECV 0 0 10.0.0.1:80 10.0.0.5:54321 users:(("nginx",pid=1234,fd=5))
```

**Глобальная статистика через nstat:**
```bash
# Мониторинг переполнений и ретрансмиссий
nstat -az | grep -E 'ListenOverflows|ListenDrops|RetransSegs|Syncookies'
# → TcpExtTCPListenOverflows    15    0.0
# → TcpExtTCPListenDrops        15    0.0
# → TcpRetransSegs              150   0.0
# → TcpExtSyncookiesSent        0     0.0
```

### Сценарий 4: Анализ eBPF (bcc-tools) для рукопожатия

Инструменты eBPF позволяют проводить диагностику с минимальными накладными расходами:

```bash
# tcpconnlat: измерение задержки handshake (от SYN до SYN-ACK)
sudo tcpconnlat -p 80
# → PID    COMM         IP  LADDR          LPORT  RADDR          RPORT  USECS
# → 1234   curl         4   1.1.1.1        54321  2.2.2.2        80     15234

# tcpaccept: мониторинг завершения handshake на сервере
sudo tcpaccept
# → PID    COMM         IP  LADDR          LPORT  RADDR          RPORT
# → 5678   nginx        4   0.0.0.0        80     1.1.1.1        54321

# tcpstates: трассировка переходов состояний FSM
sudo tcpstates
# → TIME     PID     COMM             IP  PROTO  OLD        NEW
# → 12:01:00 1234    curl             4   TCP    SYN_SENT   SYN_RECV
# → 12:01:00 5678    nginx            4   TCP    LISTEN     SYN_RECV
```

### Сценарий 5: Тюнинг для Highload (2026)

Для систем с нагрузкой более 10 000 соединений в секунду и скоростями 10G+:

```ini
# /etc/sysctl.d/99-tcp-handshake-tuning.conf

# SYN backlog (очередь полуоткрытых соединений)
net.ipv4.tcp_max_syn_backlog = 16384

# Accept backlog (очередь установленных соединений)
net.core.somaxconn = 65535

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Уменьшение retry для быстрого отказа (внутри-ЦОД)
net.ipv4.tcp_syn_retries = 2

# TCP Fast Open
net.ipv4.tcp_fastopen = 3

# Включение Window Scale и Timestamps
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
```

**Настройка в приложениях:**
- **Nginx:** `listen 80 backlog=16384;`
- **Redis:** `tcp-backlog 511`
- **PostgreSQL:** `listen_addresses = '*'` + `max_connections = 200`

### Сценарий 6: Тroubleshooting типичных проблем

**Проблема: Клиент зависает перед выдачей ошибки Connection timed out**

Диагностика:
```bash
# 1. Проверка маршрута
ip route get 2.2.2.2
# → 2.2.2.2 via 10.0.0.1 dev eth0 src 1.1.1.1

# 2. Проверка reachable
ping -c 3 2.2.2.2

# 3. Проверка Firewall
sudo iptables -S | grep -E "DROP|REJECT"
# → -A INPUT -p tcp --dport 80 -j DROP

# 4. Проверка SYN через tcpdump
sudo tcpdump -i eth0 -nn 'port 80 and tcp[tcpflags] & tcp-syn != 0'
```

**Проблема: Connection refused при работающем сервисе**

Диагностика:
```bash
# 1. Проверка Listening состояния
ss -tlnp | grep :80
# → LISTEN 0 128 127.0.0.1:80 ...  (ОШИБКА: слушает только localhost)

# 2. Проверка правил Firewall
sudo iptables -S | grep REJECT
# → -A INPUT -p tcp --dport 80 -j REJECT --reject-with tcp-reset

# 3. Проверка переполнения accept queue
nstat -az | grep ListenOverflows
# → TcpExtTCPListenOverflows   15    0.0
```

**Проблема: Высокая задержка TTFB (Time To First Byte)**

Диагностика:
```bash
# 1. Измерение iRTT через tcpdump
sudo tcpdump -i eth0 -nn 'port 443 and (tcp[tcpflags] & (tcp-syn) != 0)' -tt
# → Разница между SYN и SYN-ACK = iRTT

# 2. Анализ через ss
ss -ti dst 2.2.2.2
# → cubic rto:204 rtt:15.2/0.5 mdev:0.5 cwnd:120

# 3. Проверка TCP Fast Open
sysctl net.ipv4.tcp_fastopen
# → net.ipv4.tcp_fastopen = 3 (включено)
```

### Сценарий 7: Влияние Firewall на рукопожатие

Поведение файрвола определяет тип получаемой ошибки:

| Действие | Реакция стека TCP | Ошибка приложения | Сценарий |
| :--- | :--- | :--- | :--- |
| **ACCEPT** | Пакет проходит | Зависит от состояния порта | Нормальная работа |
| **DROP** | Пакет молча отбрасывается | `Connection timed out` | Эмуляция недоступности |
| **REJECT (tcp-reset)** | Отправляется RST | `Connection refused` | Эмуляция падения сервиса |
| **REJECT (icmp-unreachable)** | Отправляется ICMP | `No route to host` | Блокировка ACL |

**Диагностика влияния Firewall:**
```bash
# Правила iptables для конкретного порта
sudo iptables -L INPUT -v -n | grep -E "80|443"
# → pkts bytes target     prot opt in     out     source               destination
# → 1500 90000 ACCEPT     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            tcp dpt:443
# →  100  6000 REJECT     tcp  --  *      *       0.0.0.0/0            0.0.0.0/0            tcp dpt:80 reject-with tcp-reset

# Правила nftables
sudo nft list ruleset | grep -E "tcp dport (80|443)"
# → tcp dport 443 accept
# → tcp dport 80 reject with tcp reset
```

### Сценарий 8: Диагностика для IPv6

Поведение handshake для IPv6 идентично IPv4 с исключениями:
- Используется заголовок ICMPv6 вместо ICMP.
- Параметры sysctl аналогичны, но используют префикс `net.ipv6.*`:
  - `net.ipv6.conf.all.accept_redirects`
  - `net.ipv6.icmp.ratelimit`

**Диагностика:**
```bash
# Проверка слушающих портов на IPv6
ss -tln6 | grep :80

# Правила nftables для IPv6
sudo nft add rule inet filter input tcp dport 8080 reject with tcp reset

# Анализ пакетов IPv6
sudo tcpdump -i eth0 -nn 'ip6 and tcp port 443 and (tcp[tcpflags] & (tcp-syn) != 0)'
```

---

## Дополнительная информация

### Сравнение задержек при установке соединения

| Протокол | Транспорт | Задержка до первого байта | Примечание |
| :--- | :--- | :--- | :--- |
| **HTTP/1.1 (plain TCP)** | TCP | 1 RTT | Стандартный three-way handshake |
| **HTTP/1.1 + TLS 1.2** | TCP + TLS | 3 RTT | TCP handshake + TLS 2-RTT handshake |
| **HTTP/2 + TLS 1.3** | TCP + TLS | 1 RTT | TCP handshake + TLS 1-RTT handshake |
| **HTTP/3 (QUIC)** | UDP | 0-1 RTT | QUIC handshake + TLS 1.3; 0-RTT при повторном |
| **TCP Fast Open (TFO)** | TCP | 0 RTT | Данные в первом SYN (повторные соединения) |

### Sysctl-параметры для управления рукопожатием

| Параметр | Значение по умолчанию | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| **`net.ipv4.tcp_syn_retries`** | 6 | Количество повторных SYN перед ETIMEDOUT | 2–3 для локальных сетей |
| **`net.ipv4.tcp_synack_retries`** | 5 | Количество повторных SYN-ACK | 3–5 для Internet |
| **`net.ipv4.tcp_max_syn_backlog`** | 1024 | Размер SYN backlog | 16384 для proxy |
| **`net.core.somaxconn`** | 128 | Размер Accept Queue | 65535 для highload |
| **`net.ipv4.tcp_syncookies`** | 1 | SYN Cookies | 1 (включать всегда) |
| **`net.ipv4.tcp_fastopen`** | 1 | TCP Fast Open | 3 (client+server) |
| **`net.ipv4.tcp_window_scaling`** | 1 | Window Scale | 1 (включать всегда) |
| **`net.ipv4.tcp_timestamps`** | 1 | Timestamps | 1 (включать всегда) |

### Диагностические команды

```bash
# Просмотр всех TCP-соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c

# Просмотр слушающих портов с указанием процессов
ss -tlnp

# Глобальная статистика переполнений
nstat -az | grep -E 'ListenOverflows|ListenDrops|ReqQFullDrop|Syncookies'

# Мониторинг SYN-пакетов без ответов
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & (tcp-syn) != 0' and port 8080

# Анализ задержки handshake
sudo tcpconnlat -p 80

# Мониторинг переходов состояний
sudo tcpstates

# Проверка маршрута
ip route get <destination_ip>

# Проверка sysctl параметров
sysctl net.ipv4.tcp_syn_retries net.ipv4.tcp_synack_retries net.ipv4.tcp_max_syn_backlog
```

### IPv6 и установка соединения

Поведение handshake для IPv6 идентично IPv4 за следующими исключениями:
- Используется заголовок ICMPv6 вместо ICMP.
- ICMPv6 Type 1 (Destination Unreachable) с Code 4 (Port unreachable) вместо ICMP Type 3 Code 3.
- Параметры sysctl аналогичны, но используют префикс `net.ipv6.*`:
  - `net.ipv6.conf.all.accept_redirects`
  - `net.ipv6.icmp.ratelimit`

**Пример диагностики для IPv6:**
```bash
# Проверка слушающих портов на IPv6
ss -tln6 | grep :80

# Правила nftables для IPv6
sudo nft add rule inet filter input tcp dport 8080 reject with tcp reset
```

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (актуальная спецификация, заменяет RFC 793).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, Timestamps, PAWS).
- **RFC 7413:** TCP Fast Open.
- **RFC 6528:** Defending against Sequence Number Attacks.
- **RFC 4987:** TCP SYN Flooding and SYN Cookies.
- **RFC 2018:** TCP Selective Acknowledgment Options.

### См. также

- **[Состояния TCP-соединений](./tcp_connection_states.md)** — подробная таблица всех 11 состояний FSM.
- **[Отказ в установке соединения](./tcp_connection_refusal.md)** — причины появления RST и SYN-тайм-аутов.
- **[Завершение соединения](./tcp_connection_termination.md)** — процесс корректного разрыва канала (FIN).
- **[Очереди соединений TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_connection_queues.md)** — тюнинг SYN/ Accept backlog.
- **[TCP Fast Open в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_fast_open.md)** — полная настройка TFO.
- **[Диагностика TCP-соединений](./tcp_connection_diagnostics.md)** — практические приемы анализа сокетов.
