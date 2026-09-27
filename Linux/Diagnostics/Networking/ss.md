# ss (Socket Statistics)

## Определения

**`ss`** (Socket Statistics) — основная консольная утилита в Linux для исследования сетевых сокетов. Входит в состав пакета `iproute2`. В отличие от устаревшего `netstat`, она получает информацию напрямую из адресного пространства ядра через интерфейс **netlink**, что позволяет мгновенно обрабатывать тысячи активных соединений.

**netlink** — бинарный интерфейс коммуникации между пользовательским пространством и ядром Linux. Утилита `ss` подключается к multicast-группе `RTNLGRP_LINK` и `RTNLGRP_IPV4_IFADDR`, получая атомарный снимок таблицы сокетов. Это eliminates необходимость парсинга текстовых файлов `/proc/net/tcp*`, что критично для производительности на высоконагруженных системах (10k+ соединений).

**Сокет (socket)** — абстракция ядра Linux для конечной точки сетевого соединения. В ядре каждый сокет представлен структурой `struct sock` (семейство `sock_common`), которая содержит состояние, очереди, таймеры и параметры TCP Info. Утилита `ss` читает эти структуры через netlink-сокет ядра.

**Очереди Recv-Q и Send-Q** — внутренние буферы ядра, расположенные между сетевым стеком и сокетным буфером приложения. Их интерпретация зависит от состояния сокета.

**Orphaned сокет** — сокет, который был закрыт приложением (файловый дескриптор освобожден), но ядро еще удерживает структуру `sock` для завершения передачи данных или обработки задержанных пакетов. Отображается в `ss -s` как `orphaned` и в `ss -x` как `uid:0` без привязки к процессу.

## Основные концепции

### Преимущества перед netstat

| Характеристика | ss | netstat |
| :--- | :--- | :--- |
| **Источник данных** | `netlink` (бинарный интерфейс ядра) | `/proc` (парсинг текстовых файлов) |
| **Производительность** | O(1) — масштабируется линейно | O(n) — замедляется при росте числа сокетов |
| **Фильтрация** | Встроенный язык выражений | Требует внешних утилит (`grep`, `awk`) |
| **TCP-детали** | Полные (RTT, cwnd, MSS, pacing_rate, delivery_rate, app_limited) | Базовые счетчики |
| **Статус** | Активный стандарт (iproute2) | Устарела (deprecated) |
| **Размер вывода** | Только запрошенные сокеты + фильтры | Полный дамп всех сокетов |

### Принцип работы netlink в ss

Утилита `ss` создает netlink-сокет (семейство `AF_NETLINK`, тип `SOCK_RAW`, протокол `NETLINK_SOCK_DIAG`) и отправляет запросы через `struct sock_diag_req`. Ядро возвращает ответы в виде серии `struct sock_diag_msg`, содержащих `struct inet_diag_msg` + опциональные `struct inet_diag_meminfo` и `struct tcp_info`. Такой подход гарантирует согласованность данных, так как ядро собирает снимок за одну операцию.

### Очереди Recv-Q и Send-Q

Значения этих очередей интерпретируются по-разному в зависимости от состояния сокета:

*   **Состояние LISTEN:**
    *   **Recv-Q:** Текущее количество соединений в очереди `backlog` (ожидают `accept()`). Размер очереди ограничен `net.core.somaxconn` и параметром `backlog` в вызове `listen()`.
    *   **Send-Q:** Максимально допустимый размер очереди `backlog`.
    *   *Проблема:* Если `Recv-Q` стабильно равен или близок к `Send-Q`, приложение не успевает обрабатывать новые подключения. Рост `TcpExtListenOverflows` в `nstat` подтверждает переполнение.
*   **Состояние ESTABLISHED:**
    *   **Recv-Q:** Количество данных в байтах, которые ядро приняло, но приложение еще не вычитало через `recv()`. Рост без чтения приводит к блокировке окна приемника (Zero Window).
    *   **Send-Q:** Количество данных в байтах, отправленных приложением через `send()`, но еще не подтвержденных (`ACK`) удаленной стороной или не освободившихся из буфера отправки.

### Состояния TCP-соединений

Утилита позволяет фильтровать сокеты по их жизненному циклу:

- **LISTEN:** Ожидание входящих подключений (серверная часть). Очередь `backlog` формируется здесь.
- **ESTABLISHED:** Активная передача данных. Оба конца прошли трехстороннее рукопожатие.
- **SYN-SENT / SYN-RECV:** Этапы "трехстороннего рукопожатия". Большое число `SYN-RECV` может указывать на SYN-flood атаку или недостаточный `tcp_max_syn_backlog`.
- **TIME-WAIT:** Соединение закрыто, но ядро удерживает запись для обработки задержанных пакетов. Длится 2*MSL (обычно 60 секунд). Может привести к исчерпанию ephemeral портов при высокой нагрузке.
- **CLOSE-WAIT:** Удаленная сторона закрыла соединение (послала FIN), локальное приложение еще нет (возможна утечка ресурсов в коде).
- **LAST-ACK:** Приложение закрыло сокет, ожидание финального ACK от удаленной стороны.
- **FIN-WAIT-1 / FIN-WAIT-2:** Промежуточные состояния при закрытии инициатором.
- **CLOSING:** Оба конца одновременно закрывают соединение.

### Основные флаги

- `-t` / `-u`: TCP или UDP сокеты.
- `-x`: Unix domain сокеты (локальные сокеты процессов).
- `-4` / `-6`: Фильтрация только по IPv4 или IPv6.
- `-l`: Только слушающие (Listening) порты.
- `-a`: Все сокеты (Listening + Established).
- `-p`: Вывод PID и имени процесса (требует `sudo` или `CAP_SYS_PTRACE` / `CAP_NET_ADMIN`).
- `-n`: Числовые значения (без разрешения имен — работает быстрее).
- `-i`: Детальная TCP-статистика (RTT, cwnd, MSS, pacing_rate, delivery_rate, app_limited).
- `-m`: Информация об использовании памяти каждым сокетом.
- `-o`: Информация о таймерах (keepalive, retransmit, time-wait таймеры).
- `-s`: Сводный отчет по всем протоколам.
- `-e`: Расширенная информация (inode, UID, контекст безопасности SELinux).
- `-E`: TCP info extended (требует ядро 3.7+). Показывает дополнительные поля: `tcpi_bytes_sent`, `tcpi_bytes_retrans`, `tcpi_ooo_byte`, `tcpi_zero_window_adv`.
- `-K`: Принудительное закрытие сокета (требует kernel 4.9+).
- `-Z` / `-z`: Контекст безопасности SELinux (source/target context).

### Параметры ядра, влияющие на вывод ss

| Параметр | Влияние на ss | Рекомендация |
| :--- | :--- | :--- |
| `net.core.somaxconn` | Лимит размера backlog для listen-сокетов | 65535 для высоконагруженных сервисов |
| `net.ipv4.tcp_max_syn_backlog` | Очередь полуоткрытых соединений (SYN-RECV) | 4096–65535 |
| `net.ipv4.ip_local_port_range` | Диапазон ephemeral портов (клиентских) | 1024 65535 (минимум) |
| `net.ipv4.tcp_tw_reuse` | Повторное использование TIME-WAIT сокетов | 1 для клиентских нагрузок |
| `net.ipv4.tcp_tw_recycle` | Агрессивное ускорение TIME-WAIT (опасен за NAT) | 0 (устарел) |
| `net.ipv4.tcp_syncookies` | Защита от SYN-flood | 1 в production |
| `net.ipv4.tcp_abort_on_overflow` | RST при переполнении backlog | 0 (по умолчанию); 1 только для тестирования |

## Практические сценарии

### Анализ слушающих портов (IPv4 и IPv6)

Проверка, какие службы открыты для входящих соединений:

```bash
sudo ss -tulpn
# → Netid  State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port  Process
# → tcp    LISTEN  0       128     0.0.0.0:22          0.0.0.0:*          users:(("sshd",pid=1234))
# → tcp    LISTEN  0       511     [::]:80             [::]:*             users:(("nginx",pid=5678))

# Только IPv6
ss -tulpn -6

# Проверка конкретного порта
ss -tlnp | grep :443
```

### Продвинутая фильтрация

`ss` поддерживает фильтрацию по адресам, портам и состояниям с использованием логических операторов:

```bash
# Соединения из конкретной подсети
ss -at dst 192.168.1.0/24

# Логическое ИЛИ для портов
ss -at '( dport = :80 or dport = :443 )'

# Все TCP-соединения, кроме ESTABLISHED
ss -nt state all not established

# Поиск соединений с конкретным портом на локальной стороне
ss -at sport == :ssh

# Соединения в состоянии SYN-SENT (возможен проблемный firewall)
ss -tn state syn-sent

# Соединения, удерживающие порт (привязка без listen)
ss -tn '( dport = :5432 )' | grep -v LISTEN
```

### Сводная статистика по протоколам (`ss -s`)

Быстрая оценка нагрузки на сетевой стек без вывода списка всех сокетов:

```bash
ss -s
# → Total: 156 (kernel 180)
# → TCP:   24 (estab 1, closed 1, orphaned 0, timewait 0)
# → UDP:   12

# Поле `orphaned` показывает сокеты, которые не привязаны ни к одному процессу
# (например, после close(), но до завершения передачи данных).

# Количество TIME-WAIT сокетов (индикатор исчерпания ephemeral портов)
ss -s | grep -i timewait

# Проверка количества соединений в конкретном состоянии
ss -tn state time-wait | wc -l
ss -tn state close-wait | wc -l
```

### Принудительное закрытие сокетов (`ss -K`)

Полезно для сброса "зависших" соединений без перезагрузки приложения:

```bash
# Закрыть все TCP-соединения с конкретным хостом
sudo ss -K dst 1.2.3.4

# Закрыть соединения к конкретному порту назначения
sudo ss -K dport = :3306

# Закрыть соединения от конкретного источника
sudo ss -K src 192.168.1.100
```

### Работа в сетевых пространствах имен (Network Namespaces)

Диагностика сокетов внутри контейнеров или изолированных сред:

```bash
# Просмотр портов внутри namespace 'production'
sudo ip netns exec production ss -tulpn

# Через nsenter (если известен PID процесса в namespace)
sudo nsenter -t <PID> -n ss -tulpn

# Все namespace на хосте
for ns in $(ip netns list); do echo "=== $ns ==="; sudo ip netns exec $ns ss -tlnp; done
```

### Глубокий анализ производительности (`ss -ti`)

Используется для поиска причин задержек без запуска `tcpdump`:

```bash
ss -ti dst 1.1.1.1
# → cubic wscale:7,7 rto:204 rtt:15.2/0.5 ato:40 mss:1448
# → cwnd:10 bytes_acked:15002048 retrans:0/125 delivery_rate 120Mbps
# → pacing_rate 120Mbps  app_limited

# С флагом -n (быстрее, без резолвинга)
ss -tin dst 1.1.1.1
```

**Интерпретация ключевых метрик:**
- **rtt:** Время кругового обхода (среднее/отклонение). Высокий `mdev` означает джиттер.
- **retrans:** `текущие/всего`. Рост общего числа говорит о потерях на линии.
- **cwnd:** Окно перегрузки. Ограничивает объем данных в полете.
- **rcv_space:** Размер окна приема, сообщаемый удаленной стороной. Малый = получатель «бутылочное горлышко».
- **backoff:** Количество экспоненциальных задержек при повторных передачах (высокое значение — признак разрыва связи).
- **pacing_rate:** Максимальная скорость, с которой TCP-стек передает данные (ограничение TCP pacing).
- **delivery_rate:** Реальная достигнутая скорость доставки. Если `pacing_rate` >> `delivery_rate` — сеть ограничивает поток.
- **app_limited:** Если `1` — TCP-стек простаивает, потому что приложение не отдает данные достаточно быстро.
- **bytes_acked / bytes_sent:** Отношение показывает эффективность передачи (должно стремиться к 1:1 при отсутствии потерь).

### Анализ потребления памяти (`ss -m`)

Выявление сокетов, поглощающих буферную память:

```bash
ss -tm
# → skmem:(r0,rb212992,t0,tb212992,f0,w0,o0,bl0,d0)

# Расшифровка полей skmem:
# r  — количество сокетов в очереди приема
# rb — read buffer (лимит памяти на прием, байт)
# tb — transmit buffer (лимит на передачу, байт)
# f  — forward allocations (память, выделенная "вперед")
# w  — количество сокетов в очереди отправки
# o  — memory allocated for "struct sock"
# bl — backlog queue size
# d  — memory allocated for "struct sock_diag"
```

### Мониторинг в реальном времени

```bash
# Обновление списка соединений каждую секунду
watch -n 1 'ss -tulpn | grep LISTEN'

# Фильтрация только ESTABLISHED соединений
watch -n 1 'ss -t established | wc -l'

# Мониторинг роста TIME-WAIT
watch -n 1 'ss -s | grep timewait'

# Топ-10 соединений по RTT
watch -n 1 'ss -tin state established | grep -oP "rtt:\K[\d.]+" | sort -n | tail -10'
```

### Выявление исчерпания ephemeral портов

```bash
# Количество сокетов в TIME-WAIT
timewait_count=$(ss -tn state time-wait | wc -l)
echo "TIME-WAIT: $timewait_count"

# Если > 10000 — вероятно, исчерпание ephemeral портов
# Проверка диапазона ephemeral портов
cat /proc/sys/net/ipv4/ip_local_port_range
# → 1024 65535 (доступно ~64k портов)

# Диагностика: количество уникальных удаленных портов
ss -tn state established | awk '{print $5}' | cut -d: -f2 | sort -u | wc -l
```

### Выявление SYN-flood атаки

```bash
# Большое количество SYN-RECV
sudo ss -tn state syn-recv | wc -l

# Детализация источников
sudo ss -tn state syn-recv | awk '{print $5}' | sort | uniq -c | sort -rn | head -10

# Проверка счетчика SYN cookies (в ядре)
cat /proc/sys/net/ipv4/tcp_syncookies
# → 1 (защита активна)

# Проверка счетчика переполнений backlog
sudo nstat -az | grep -i listen
# → TcpExtListenOverflows    150    0.0
# → TcpExtListenDrops         42    0.0
```

### Диагностика очереди listen (backlog)

```bash
# Состояние очереди для конкретного порта
sudo ss -ltn sport = :443
# → LISTEN  0  511  0.0.0.0:443  0.0.0.0:*
#     ^^^   ^  ^^^
#     Recv-Q   Send-Q (backlog)

# Если Recv-Q близок к Send-Q — приложение не успевает accept()

# Проверка somaxconn (глобальный лимит)
sysctl net.core.somaxconn
# → net.core.somaxconn = 65535

# Проверка per-socket backlog (в исходном коде приложения)
# Обычно задается через listen(fd, backlog) — значение ограничено somaxconn
```

### Выявление утечек сокетов (CLOSE-WAIT)

```bash
# Количество зависших соединений
sudo ss -tn state close-wait | wc -l

# Определение процессов-виновников
sudo ss -tnp state close-wait | awk -F'[()]' '{print $2}' | sort | uniq -c | sort -rn

# Детализация по портам
sudo ss -tnp state close-wait | awk '{print $5}' | cut -d: -f2 | sort | uniq -c | sort -rn | head -10
```

### Интеграция с conntrack (NAT/firewall)

```bash
# Связка ss с conntrack для отслеживания NAT-соединений
sudo conntrack -L -p tcp --dport 443 | head -5

# Статистика conntrack
sudo conntrack -S
# → cpu=0   found=12345 insert=12344 drop=0 early_drop=0 error=0
# → insert_failed=0

# Если insert_failed > 0 — увеличьте nf_conntrack_max
sysctl net.netfilter.nf_conntrack_max
sysctl net.netfilter.nf_conntrack_buckets
```

### Диагностика listen queue с детализацией

```bash
# Скрипт проверки всех listen-сокетов
#!/bin/bash
echo "=== Listen Queue Analysis ==="
echo "somaxconn: $(sysctl -n net.core.somaxconn)"
echo

sudo ss -ltnp | awk 'NR>1 {
    split($4, local, ":")
    port = local[length(local)]
    recvq = $2
    sendq = $3
    pct = (recvq / sendq) * 100
    printf "Port %s: Recv-Q=%s Send-Q=%s (%.1f%%)\n", port, recvq, sendq, pct
}' | sort -t: -k2 -rn
```

### Универсальный скрипт быстрой диагностики

```bash
#!/bin/bash
# quick_socket_audit.sh — аудит сокетного состояния для SRE

echo "=== Socket Audit ==="
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
echo

echo "--- Summary ---"
ss -s

echo
echo "--- Listen Queues (Recv-Q > 0) ---"
sudo ss -ltnp | awk 'NR>1 && $2 > 0 {printf "%-6s %-20s %s/%s\n", $1, $4, $2, $3}'

echo
echo "--- TIME-WAIT count ---"
echo "$(ss -tn state time-wait | wc -l) sockets in TIME-WAIT"

echo
echo "--- CLOSE-WAIT count ---"
echo "$(ss -tn state close-wait | wc -l) sockets in CLOSE-WAIT"

echo
echo "--- Top 10 by Recv-Q (ESTABLISHED) ---"
sudo ss -tnp state established | sort -k2 -rn | head -11

echo
echo "--- Kernel counters ---"
sudo nstat -az | grep -E 'ListenOverflows|ListenDrops|TCPRetransSegs|TCPTimeouts|TCPAbortOn' | head -10

echo
echo "--- conntrack (if active) ---"
sudo conntrack -S 2>/dev/null | head -3
```

### Диагностика Docker-контейнеров

```bash
# Сокеты на docker-мосте
sudo ss -tin | grep -E "docker|br-|veth"

# Внутри контейнера (с netshoot)
docker run --rm -it --network container:<target> nicolaka/netshoot ss -tulpn

# Через nsenter (PID процесса в контейнере)
CONTAINER_PID=$(docker inspect -f '{{.State.Pid}}' <container>)
sudo nsenter -t $CONTAINER_PID -n ss -tulpn
```

## Сравнение команд: netstat → ss

| Задача | netstat (Old) | ss (Modern) |
| :--- | :--- | :--- |
| Слушающие TCP/UDP с PID | `netstat -tulpn` | `ss -tulpn` |
| Все TCP соединения | `netstat -at` | `ss -at` |
| Статистика по протоколам | `netstat -s` | `ss -s` |
| Фильтр по порту 80 | `netstat -an | grep :80` | `ss -tn sport = :80` |
| Просмотр Unix-сокетов | `netstat -x` | `ss -x` |
| Маршруты (Routing) | `netstat -rn` | `ip route` |
| Детальная TCP-статистика | нет | `ss -ti` |
| Память сокета | нет | `ss -tm` |
| Таймеры | нет | `ss -to` |
| Расширенная информация (inode, UID) | нет | `ss -te` |

## Типичные проблемы и решения

| Симптом | Диагностика через ss | Вероятная причина | Исправление |
| :--- | :--- | :--- | :--- |
| **Connection Refused** | `ss -ltnp | grep :80` — Recv-Q = Send-Q | Приложение не успевает accept() | Увеличить `somaxconn`, оптимизировать приложение, проверить `tcp_max_syn_backlog` |
| **Высокий TIME-WAIT** | `ss -s` — timewait > 10000 | Много коротких соединений | Включить `tcp_tw_reuse=1`, использовать connection pooling |
| **CLOSE-WAIT растет** | `ss -tnp state close-wait` — много записей | Утечка сокетов в приложении | Исправить код приложения, перезапустить процесс |
| **Zero Window** | `ss -tmo \| grep window:0` | Приложение медленно читает | Увеличить `rmem`, оптимизировать приложение, включить `tcp_moderate_rcvbuf` |
| **SYN-RECV > 500** | `ss -tn state syn-recv \| wc -l` | SYN-flood или firewall drop | Включить `tcp_syncookies=1`, увеличить backlog, настроить firewall |
| **Рост orphaned** | `ss -s` — orphaned > 100 | Приложение закрывает сокеты без shutdown() | Исправить приложение, увеличить `tcp_max_orphans` |
| **Send-Q растет (ESTABLISHED)** | `ss -tn state established \| sort -k3 -rn \| head` | Приложение отправляет быстрее, чем сеть подтверждает | Увеличить `wmem`, проверить сетевую полосу |
| **Высокий Retrans** | `ss -ti dst <host>` — retrans растет | Потери пакетов на L2/L3 | Проверить `ethtool -S`, `tc qdisc`, заменить кабель |

## Дополнительная информация

### Edge Cases и ограничения

**1. Права доступа:**
- `ss -p` требует `sudo` или `CAP_NET_ADMIN` / `CAP_SYS_PTRACE`.
- В контейнерах без `NET_ADMIN` `ss` работает, но не показывает процессы и netns не переключается.

**2. Контейнеры и namespace:**
- Каждый контейнер имеет свой network namespace. `ss` по умолчанию показывает сокеты текущего namespace.
- Используйте `ip netns exec <ns> ss ...` или `nsenter -t <PID> -n ss ...` для диагностики внутри namespace.
- Учитывайте overlay network (VXLAN) при анализе RTT — реальный RTT может быть ниже, чем видно на хосте.

**3. Высокоскоростные сети (100G/400G):**
- При тысячах соединений `ss -a` может генерировать мегабайты вывода. Используйте фильтрацию.
- Включите `ethtool -K eth0 rx off tx off` для отключения offloading при детальном анализе.

**4. Многопоточные приложения:**
- `ss -p` показывает только основной поток процесса. Для всех потоков используйте `ss -p` + `pthread` IDs или `lsof -p <pid>`.
- `SO_REUSEPORT` создает отдельные listen-сокеты на каждый поток — будете видеть несколько строк для одного порта.

**5. Орфанные сокеты:**
- `ss -s` поле `orphaned` — сокеты без дескриптора в любом процессе. Ядро удерживает их для завершения передачи.
- Если `orphaned` растет — проверьте `tcp_max_orphans` и логи приложения на предмет `close()` без `shutdown()`.

### Мониторинг и алертинг

**Prometheus + node_exporter:**

```yaml
groups:
  - name: socket_alerts
    rules:
      - alert: HighTimeWaitSockets
        expr: node_sockstat_TCP_tw > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High TIME-WAIT sockets on {{ $labels.instance }}"
          description: "TIME-WAIT count is {{ $value }}."

      - alert: HighCloseWaitSockets
        expr: node_sockstat_TCP_orphaned > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High orphaned/close-wait sockets on {{ $labels.instance }}"
          description: "Potential socket leak in application."

      - alert: ListenQueueFull
        expr: node_netstat_TcpExt_ListenOverflows > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Listen queue overflow on {{ $labels.instance }}"
          description: "Application is not accepting connections fast enough."
```

**Автоматизация через systemd-timer (cron alternative):**

```bash
# /etc/systemd/system/socket-audit.service
[Unit]
Description=Socket Audit

[Service]
Type=oneshot
ExecStart=/usr/local/bin/quick_socket_audit.sh

# /etc/systemd/system/socket-audit.timer
[Unit]
Description=Run socket audit every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

### Связанные инструменты

- **[tcpdump](./tcpdump.md)** — захват и анализ сырых пакетов.
- **[iproute2](../../../Linux/Networking/Tools/iproute2/overview.md)** — основной пакет утилит (включает `ss`).
- **[Оптимизация TCP](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка буферов и алгоритмов.
- **[Диагностика сокетов TCP](../../../Networking/Concepts/tcp_tuning/tcp_socket_diagnostics.md)** — глубокий разбор метрик `ss -ti`, eBPF-инструменты, прикладные сценарии (Kafka, PostgreSQL).
- **[Диагностика надежности TCP](../../Networking/Protocols/TCP/reliability_mechanisms/diagnostics.md)** — системный анализ ретрансмиссий, nstat счетчики, production runbook.
- **[Диагностика TCP-соединений](../../Networking/Protocols/TCP/connection/tcp_connection_diagnostics.md)** — анализ состояний соединений.
- **[nstat](./network_cli_tools.md)** — современный мониторинг сетевых счетчиков SNMP.

### См. также

- **[netstat](./netstat.md)** — история и совместимость.
- **[lsof](../Processes/lsof.md)** — поиск процессов, удерживающих сокеты.
- **[conntrack](../../../Networking/Concepts/nat/conntrack_bypass.md)** — диагностика таблицы соединений NAT/firewall.
- **[ethtool](../../../Linux/Networking/Tools/ethtool.md)** — диагностика NIC, offloading, ring buffers.
- **[tcpdump](./tcpdump.md)** — захват трафика для глубокого анализа.
- **[ip-netns](../../../Linux/Networking/Tools/iproute2/ip_netns.md)** — управление сетевыми namespace.
