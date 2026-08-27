# Состояния TCP-соединений

## Определения

Протокол TCP является **конечным автоматом (Finite State Machine, FSM)**. Это означает, что любое TCP-соединение в каждый момент времени находится в одном из 11 строго определенных состояний. Переход между состояниями происходит в ответ на три типа событий:
1.  **Системные вызовы приложения:** API-функции (`socket()`, `bind()`, `listen()`, `connect()`, `close()`, `shutdown()`).
2.  **Получение сегментов:** Приход пакетов с установленными флагами управления (`SYN`, `ACK`, `FIN`, `RST`).
3.  **Истечение таймеров:** Например, таймер `2MSL` в состоянии `TIME_WAIT` или таймеры ретрансмиссии (RTO).

---

## Основные концепции

### Полная таблица состояний (RFC 9293)

| Состояние | Техническое описание | Роль | Событие перехода |
| :--- | :--- | :--- | :--- |
| **CLOSED** | Исходное состояние: соединение отсутствует. | — | Приложение инициирует `connect` (SYN) или `listen`. |
| **LISTEN** | Ожидание входящих запросов на соединение. | Сервер | Получен `SYN` -> отправка `SYN-ACK` -> переход в `SYN_RECV`. |
| **SYN_SENT** | Отправлен запрос `SYN`, ожидание ответного `SYN-ACK`. | Клиент | Получен `SYN-ACK` -> отправка `ACK` -> переход в `ESTABLISHED`. |
| **SYN_RECEIVED** | Получен `SYN`, отправлен `SYN-ACK`, ожидание финального `ACK`. | Сервер | Получен `ACK` -> переход в `ESTABLISHED`. |
| **ESTABLISHED** | Соединение установлено, активный двусторонний обмен данными. | Обе | Приложение инициирует закрытие (`FIN`) или получен `FIN`. |
| **FIN_WAIT_1** | Соединение закрыто локально, отправлен `FIN`, ожидание `ACK`. | Инициатор | Получен `ACK` -> переход в `FIN_WAIT_2`. |
| **FIN_WAIT_2** | Получен `ACK` на наш `FIN`, ожидание `FIN` от партнера. | Инициатор | Получен `FIN` -> отправка `ACK` -> переход в `TIME_WAIT`. |
| **CLOSE_WAIT** | Получен `FIN` от партнера, ожидание закрытия сокета приложением. | Получатель | Приложение вызывает `close()` -> переход в `LAST_ACK`. |
| **CLOSING** | Редкий случай: одновременное закрытие (мы послали `FIN` и получили `FIN`). | Обе | Получен `ACK` на наш `FIN` -> переход в `TIME_WAIT`. |
| **LAST_ACK** | Партнер прислал `FIN`, мы ответили своим `FIN`, ждем финальный `ACK`. | Получатель | Получен `ACK` -> переход в `CLOSED`. |
| **TIME_WAIT** | Соединение закрыто, ожидание 2×MSL для очистки сети от дубликатов. | Инициатор | Истечение таймера (60 сек в Linux) -> переход в `CLOSED`. |

### Диаграмма переходов состояний

```text
                              +---------+
                              | CLOSED  |
                              +----+----+
                                   |
              +--------------------+--------------------+
              | (passive open)     | (active open)      |
              v                    v                    |
          +--------+          +----------+              |
          | LISTEN |          | SYN_SENT |              |
          +----+---+          +----+-----+              |
               | (recv SYN)        | (recv SYN-ACK)     |
               v                   v                    |
          +----------+        +-------------+           |
          | SYN_RECV |<-------|  SYN_SENT   |           |
          +----+-----+        +-------------+           |
               | (recv ACK)        | (send ACK)         |
               v                   v                    |
          +-------------+     +-------------+           |
          | ESTABLISHED |<----| ESTABLISHED |           |
          +------+------+     +------+------+           |
                 | (app close)       | (recv FIN)       |
                 v                   v                  |
          +------------+      +------------+            |
          | FIN_WAIT_1 |      | CLOSE_WAIT |            |
          +------+-----+      +------+-----+            |
                 | (recv ACK)        | (app close)      |
                 v                   v                  |
          +------------+      +------------+            |
          | FIN_WAIT_2 |      |  LAST_ACK  |            |
          +------+-----+      +------+-----+            |
                 | (recv FIN)        | (recv ACK)       |
                 v                   v                  |
          +------------+      +------------+            |
          | TIME_WAIT  |<-----|  CLOSING   |------------+
          +------+-----+      +------------+
                 | (2*MSL timeout)
                 v
             +--------+
             | CLOSED |
             +--------+
```

### Обработка флага RST (Reset)

Сегмент с флагом **RST** вызывает немедленный принудительный переход сокета в состояние `CLOSED` из любого текущего состояния, минуя стандартную процедуру 4-way handshake.

| Состояние в момент RST | Типичная причина | Эффект для приложения |
| :--- | :--- | :--- |
| **SYN_SENT** | Порт закрыт на сервере или Firewall сбросил пакет. | Ошибка `Connection refused`. |
| **ESTABLISHED** | Сбой процесса, перезагрузка узла, NAT таймаут. | Ошибка `Connection reset by peer`. |
| **FIN_WAIT / TIME_WAIT** | Удаленная сторона уже удалила сокет из памяти. | Сокет немедленно уничтожается. |

---

## Практические сценарии

### Сценарий 1: CLOSE_WAIT (Утечка сокетов в приложении)

**Симптом:** Количество сокетов в `CLOSE_WAIT` постоянно растет и не уменьшается.
**Техническая суть:** Партнер прислал `FIN` (узел перешел в `CLOSE_WAIT`), но локальное приложение не вызвало `close()`. Ядро не может закрыть сокет, пока приложение не даст команду, так как TCP поддерживает полузакрытые соединения.
**Диагностика:**
```bash
# Подсчет количества сокетов по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c
# →    15420 TIME-WAIT
# →      145 CLOSE-WAIT
# →       45 SYN-RECV
# →    12345 ESTAB

# Поиск конкретного процесса-виновника
ss -tanp state close-wait
# → CLOSE-WAIT 0 0 10.0.0.1:80 10.0.0.5:54321 users:(("java",pid=999,fd=14))

# Подсчет CLOSE_WAIT по процессам
ss -tanp state close-wait | awk '{print $NF}' | sort | uniq -c | sort -rn
# → 120 users:(("nginx",pid=1234,fd=5))
# →  25 users:(("java",pid=5678,fd=14))

# Просмотр файловых дескрипторов процесса
ls -la /proc/1234/fd | grep socket
# → lr-x------ 1 root root 64 ... 14 -> socket:[12345678]

# Мониторинг через lsof
lsof -i TCP:80 -sTCP:CLOSE-WAIT
# → COMMAND  PID  USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
# → nginx   1234 root   14u  IPv4 123456      0t0  TCP server:80->client:54321 (CLOSE_WAIT)
```
**Решение:** Анализ кода приложения на предмет корректного освобождения ресурсов (блоки `try-with-resources`, `finally`).

**Практические примеры исправления:**
```python
# Python: Использование context manager для автоматического закрытия
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.connect((host, port))
    sock.sendall(data)
    response = sock.recv(1024)
# Сокет автоматически закрывается при выходе из блока

# Java: Использование try-with-resources
try (Socket socket = new Socket(host, port)) {
    socket.getOutputStream().write(data);
    socket.getInputStream().read(buffer);
} // Сокет автоматически закрывается
```

### Сценарий 2: TIME_WAIT и исчерпание портов (Port Exhaustion)

**Симптом:** Ошибка `Cannot assign requested address` при попытке установить новое соединение.
**Техническая суть:** Состояние `TIME_WAIT` необходимо для того, чтобы "блуждающие" пакеты старой сессии не попали в новую с тем же 5-tuple. Длительность составляет 2×MSL (в Linux жестко зашито 60 сек). При большом количестве коротких соединений эфемерные порты заканчиваются.
**Диагностика:**
```bash
# Проверка лимитов портов
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768 60999

# Количество сокетов в TIME_WAIT
ss -tan state time-wait | wc -l
# → 15420 — проблема, если доступно ~28000 портов

# Просмотр статистики из SNMP-счетчиков
nstat -az | grep -E 'TcpExtTW|TcpExtTCPTimeWaitOverflow'
# → TcpExtTW 15420 0.0 (количество TIME_WAIT)
# → TcpExtTCPTimeWaitOverflow 0 0.0 (сброшенных из-за переполнения)

# Просмотр распределения портов по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn
```
**Решение:**
1.  **Connection Pooling:** Использовать постоянные соединения (Keepalive).
2.  **net.ipv4.tcp_tw_reuse = 1:** Разрешает переиспользовать порт, если временная метка (TCP Timestamps) нового пакета больше последней метки в `TIME_WAIT`.
3.  **Масштабирование:** Увеличение количества IP-адресов на балансировщике.

**Параметры sysctl для тюнинга TIME_WAIT:**
```bash
# Включение переиспользования TIME_WAIT (рекомендуется)
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Увеличение диапазона эфемерных портов
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# Сокращение времени удержания FIN_WAIT_2 (по умолчанию 60 сек)
sudo sysctl -w net.ipv4.tcp_fin_timeout=15

# Отключение переиспользования метрик (для коротких соединений)
sudo sysctl -w net.ipv4.tcp_no_metrics_save=1
```

### Сценарий 3: SYN_RECV (SYN-флуд или перегрузка Accept-очереди)

**Симптом:** Резкий рост соединений в `SYN_RECV`, легитимные пользователи получают таймауты.
**Техническая суть:** Сервер получил `SYN`, ответил `SYN-ACK` и ждет финальный `ACK` от клиента. Если `ACK` не приходит (атака или потери), сокет занимает место в `SYN backlog`.
**Диагностика:**
```bash
# Проверка заполнения очередей
ss -nlit
# → State    Recv-Q    Send-Q    Local Address:Port    Peer Address:Port
# → LISTEN   0         128       0.0.0.0:80            0.0.0.0:*
# → Recv-Q = текущее количество соединений в очереди
# → Send-Q = максимальный размер очереди

# Мониторинг через nstat
nstat -az | grep TcpExtTCPBacklogDrop
# → TcpExtTCPBacklogDrop 125 0.0 — количество отброшенных из-за переполнения

# Просмотр соединений в SYN_RECV
ss -tan state syn-recv
# → SYN-RECV 0 0 10.0.0.1:80 10.0.0.5:54321

# Подсчет количества SYN_RECV соединений
ss -tan state syn-recv | wc -l
# → 45 — проблема, если больше 100

# Мониторинг через netstat (альтернатива ss)
netstat -tan | grep SYN_RECV | wc -l
```
**Решение:** Включение SYN cookies (`net.ipv4.tcp_syncookies = 1`) и тюнинг `net.ipv4.tcp_max_syn_backlog`.

**Параметры sysctl для защиты от SYN-флуда:**
```bash
# Включение SYN cookies (защита от SYN-флуда)
sudo sysctl -w net.ipv4.tcp_syncookies=1

# Увеличение размера SYN backlog
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096

# Отправка RST при переполнении backlog (вместо игнорирования)
sudo sysctl -w net.ipv4.tcp_abort_on_overflow=1

# Сокращение времени повторной отправки SYN-ACK
sudo sysctl -w net.ipv4.tcp_synack_retries=2
```

### Сценарий 4: FIN_WAIT_2 (Зависшее закрытие соединения)

**Симптом:** Сокеты в `FIN_WAIT_2` не закрываются в течение длительного времени.
**Техническая суть:** Инициатор отправил `FIN` и получил `ACK`, но удаленная сторона не отправляет свой `FIN`. Это может произойти, если приложение на удаленной стороне зависло или не закрыло соединение.
**Диагностика:**
```bash
# Просмотр соединений в FIN_WAIT_2
ss -tan state fin-wait-2
# → FIN-WAIT-2 0 0 10.0.0.1:80 10.0.0.5:54321

# Подсчет количества FIN_WAIT_2
ss -tan state fin-wait-2 | wc -l
# → 25 — проблема, если больше 100

# Просмотр времени в состоянии FIN_WAIT_2
ss -tin state fin-wait-2 | grep -oE 'timer:[^\)]+'
# → timer:(TIME-WAIT,60sec,0)
```
**Решение:**
```bash
# Сокращение времени удержания FIN_WAIT_2 (по умолчанию 60 сек)
sudo sysctl -w net.ipv4.tcp_fin_timeout=15

# Принудительное закрытие соединений в FIN_WAIT_2
ss -tan state fin-wait-2 | awk '{print $4, $5}' | while read local remote; do
    ss -K dst $(echo $remote | cut -d: -f1) dport = $(echo $remote | cut -d: -f2)
done
```

### Сценарий 5: LAST_ACK (Ожидание подтверждения закрытия)

**Симптом:** Соединение в `LAST_ACK` не закрывается.
**Техническая суть:** Удаленная сторона отправила `FIN`, мы ответили `FIN`, но не получаем `ACK`. Это может произойти из-за потери пакетов или зависания удаленной стороны.
**Диагностика:**
```bash
# Просмотр соединений в LAST_ACK
ss -tan state last-ack
# → LAST-ACK 0 0 10.0.0.1:80 10.0.0.5:54321

# Подсчет количества LAST_ACK
ss -tan state last-ack | wc -l
# → 5 — проблема, если больше 10

# Просмотр времени в состоянии LAST_ACK
ss -tin state last-ack | grep -oE 'timer:[^\)]+'
# → timer:(TIME-WAIT,60sec,0)
```
**Решение:**
```bash
# Увеличение времени повторной отправки FIN
sudo sysctl -w net.ipv4.tcp_orphan_retries=3

# Принудительное закрытие соединений в LAST_ACK
ss -tan state last-ack | awk '{print $4, $5}' | while read local remote; do
    ss -K dst $(echo $remote | cut -d: -f1) dport = $(echo $remote | cut -d: -f2)
done
```

### Сценарий 6: CLOSING (Одновременное закрытие)

**Симптом:** Соединение в `CLOSING` не закрывается.
**Техническая суть:** Оба узла отправили `FIN` одновременно. Это редкая ситуация, которая обычно возникает при ошибках в приложении.
**Диагностика:**
```bash
# Просмотр соединений в CLOSING
ss -tan state closing
# → CLOSING 0 0 10.0.0.1:80 10.0.0.5:54321

# Подсчет количества CLOSING
ss -tan state closing | wc -l
# → 0 — норма, если больше 0, есть проблема
```
**Решение:**
```bash
# Принудительное закрытие соединений в CLOSING
ss -tan state closing | awk '{print $4, $5}' | while read local remote; do
    ss -K dst $(echo $remote | cut -d: -f1) dport = $(echo $remote | cut -d: -f2)
done
```

---

## Практические команды

### Мониторинг состояний соединений

```bash
# Подсчет соединений по состояниям
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn
# →  15420 TIME-WAIT
# →  12345 ESTAB
# →    145 CLOSE-WAIT
# →     45 SYN-RECV
# →      5 LAST-ACK
# →      0 CLOSING

# Просмотр только ESTABLISHED соединений
ss -tan state established

# Просмотр соединений с процессами
ss -tanp

# Просмотр соединений с внутренней информацией
ss -tin state established

# Просмотр соединений с таймерами
ss -tin state time-wait
```

### Диагностика проблемных соединений

```bash
# Поиск соединений с высоким Retransmits
ss -tin state established | grep -E 'retrans:[1-9]'

# Поиск соединений с низким окном
ss -tin state established | grep -E 'rcv_wnd:[0-9]{1,4}'

# Поиск соединений с высоким RTT
ss -tin state established | grep -E 'rtt:[0-9]{3,}'

# Поиск соединений с ошибками
ss -tin state established | grep -E 'cubic.*retrans'
```

### Управление соединениями

```bash
# Принудительное закрытие соединения
ss -K dst 10.0.0.1 dport = 80

# Закрытие всех соединений вном состоянии
ss -tan state fin-wait-2 | awk 'NR>1 {print $4, $5}' | while read local remote; do
    ss -K dst $(echo $remote | cut -d: -f1) dport = $(echo $remote | cut -d: -f2)
done

# Закрытие соединений по процессу
ss -tanp | grep "nginx" | awk '{print $4, $5}' | while read local remote; do
    ss -K dst $(echo $remote | cut -d: -f1) dport = $(echo $remote | cut -d: -f2)
done
```

### Мониторинг через nstat

```bash
# Просмотр всех счетчиков TCP
nstat -az | grep -E 'Tcp|TcpExt'

# Просмотр счетчиков ошибок
nstat -az | grep -E 'Error|Retrans|Timeout'

# Просмотр счетчиков соединений
nstat -az | grep -E 'Listen|Accept|Overflow'

# Мониторинг в реальном времени
watch -n 2 'nstat -az | grep -E "TcpExtTW|TcpExtTCPBacklogDrop"'
```

### Мониторинг через eBPF

```bash
# Просмотр переходов состояний в реальном времени
sudo tcpstates

# Просмотр с задержками
sudo tcpstates -d

# Просмотр только дляного порта
sudo tcpstates -P 80

# Просмотр с временными метками
sudo tcpstates -t
```

### Настройка параметров sysctl

```bash
# Просмотр текущих параметров
sysctl net.ipv4.tcp_tw_reuse
sysctl net.ipv4.tcp_fin_timeout
sysctl net.ipv4.tcp_syncookies
sysctl net.ipv4.tcp_max_syn_backlog

# Включение оптимальных параметров
sudo sysctl -w net.ipv4.tcp_tw_reuse=1
sudo sysctl -w net.ipv4.tcp_fin_timeout=15
sudo sysctl -w net.ipv4.tcp_syncookies=1
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096

# Сохранение параметров
sudo tee /etc/sysctl.d/99-tcp-connection-states.conf << 'EOF'
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_abort_on_overflow = 1
net.ipv4.tcp_synack_retries = 2
EOF
sudo sysctl --system
```

---

## Linux sysctl параметры для тюнинга

| Параметр | Значение по умолчанию | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| `net.ipv4.tcp_tw_reuse` | 0 | Переиспользование TIME_WAIT | 1 для высоконагруженных серверов |
| `net.ipv4.tcp_fin_timeout` | 60 | Таймаут FIN_WAIT_2 (сек) | 15 для интерактивных приложений |
| `net.ipv4.tcp_syncookies` | 1 | Защита от SYN-флуда | 1 (включено по умолчанию) |
| `net.ipv4.tcp_max_syn_backlog` | 1024 | Размер SYN backlog | 4096 для высоконагруженных серверов |
| `net.ipv4.tcp_abort_on_overflow` | 0 | Отправка RST при переполнении | 1 для защиты от атак |
| `net.ipv4.tcp_synack_retries` | 5 | Повторные отправки SYN-ACK | 2 для ускорения отказа |
| `net.ipv4.tcp_orphan_retries` | 0 | Повторные отправки FIN | 3 для ускорения закрытия |
| `net.ipv4.tcp_max_orphans` | 16384 | Максимум сирот | 8192 для экономии памяти |
| `net.ipv4.ip_local_port_range` | 32768 60999 | Диапазон эфемерных портов | 1024 65535 для расширения |

---

## Контекст Docker и Kubernetes

### Docker

```bash
# Проверка параметров в контейнере
docker exec <container> sysctl net.ipv4.tcp_tw_reuse
docker exec <container> sysctl net.ipv4.tcp_fin_timeout

# Установка оптимальных параметров (на хосте)
sudo tee /etc/sysctl.d/99-tcp-connection-states.conf << 'EOF'
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 4096
EOF
sudo sysctl --system
```

### Kubernetes

```yaml
# Проверка параметров в поде
apiVersion: v1
kind: Pod
metadata:
  name: tcp-states-check
spec:
  containers:
  - name: app
    image: busybox
    command: ["sysctl", "-a", "net.ipv4.tcp_tw_reuse"]
```

```bash
# Проверка на ноде
kubectl exec <pod> -- sysctl net.ipv4.tcp_tw_reuse

# Настройка через SecurityContext (если разрешено)
apiVersion: v1
kind: Pod
metadata:
  name: tcp-states-tuning
spec:
  containers:
  - name: app
    image: nginx
    securityContext:
      capabilities:
        add: ["NET_ADMIN"]
    command: ["sysctl", "-w", "net.ipv4.tcp_tw_reuse=1"]
```

---

## Диагностика проблем

### Проблема: Исчерпание портов (TIME_WAIT)

```bash
# Шаг 1: Проверка количества TIME_WAIT
ss -tan state time-wait | wc -l
# → 15420 — проблема, если доступно ~28000 портов

# Шаг 2: Проверка лимитов портов
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768 60999

# Шаг 3: Проверка использования tcp_tw_reuse
sysctl net.ipv4.tcp_tw_reuse
# → net.ipv4.tcp_tw_reuse = 0 — нужно включить

# Шаг 4: Включение tcp_tw_reuse
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Шаг 5: Увеличение диапазона портов
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"
```

### Проблема: Утечка сокетов (CLOSE_WAIT)

```bash
# Шаг 1: Проверка количества CLOSE_WAIT
ss -tan state close-wait | wc -l
# → 145 — проблема, если больше 100

# Шаг 2: Поиск процесса-виновника
ss -tanp state close-wait | awk '{print $NF}' | sort | uniq -c | sort -rn
# → 120 users:(("nginx",pid=1234,fd=5))

# Шаг 3: Анализ кода приложения
# Проверить, что сокеты закрываются в блоках finally или try-with-resources

# Шаг 4: Перезапуск процесса (временное решение)
sudo systemctl restart nginx
```

### Проблема: SYN-флуд (SYN_RECV)

```bash
# Шаг 1: Проверка количества SYN_RECV
ss -tan state syn-recv | wc -l
# → 45 — проблема, если больше 100

# Шаг 2: Проверка SYN cookies
sysctl net.ipv4.tcp_syncookies
# → net.ipv4.tcp_syncookies = 1 — включено

# Шаг 3: Проверка SYN backlog
sysctl net.ipv4.tcp_max_syn_backlog
# → net.ipv4.tcp_max_syn_backlog = 1024 — нужно увеличить

# Шаг 4: Увеличение SYN backlog
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=4096

# Шаг 5: Включение tcp_abort_on_overflow
sudo sysctl -w net.ipv4.tcp_abort_on_overflow=1
```

---

## Production: Настройка по состояниям

### SYSCTL-чек-лист по проблемным состояниям

| Проблемное состояние | SYSCTL-параметр | Рекомендуемое значение | Описание |
| :--- | :--- | :--- | :--- |
| **SYN_RECV (SYN flood)** | `tcp_syncookies` | 1 | Защита от SYN-флуда через SYN Cookies. |
| | `tcp_max_syn_backlog` | 16384 | Размер очереди полуоткрытых соединений. |
| **ESTABLISHED (backlog overflow)** | `somaxconn` | 65535 | Максимальный размер accept-очереди. |
| | `tcp_abort_on_overflow` | 1 | RST при переполнении (для L4 LB). |
| **CLOSE_WAIT (утечка)** | `tcp_keepalive_time` | 60 | Обнаружение мёртвых соединений через 60 сек. |
| | `tcp_keepalive_intvl` | 10 | Интервал между попытками keepalive. |
| | `tcp_keepalive_probes` | 6 | Количество попыток перед закрытием. |
| **FIN_WAIT_2 (зависание)** | `tcp_fin_timeout` | 15 | Таймаут FIN_WAIT_2 (снижение с 60). |
| | `tcp_max_orphans` | 65535 | Максимум «сирот» (не привязанных к fd). |
| **TIME_WAIT (исчерпание портов)** | `tcp_tw_reuse` | 1 | Переиспользование TIME_WAIT (требует Timestamps). |
| | `ip_local_port_range` | 1024 65535 | Расширение диапазона эфемерных портов. |
| **LAST_ACK (зависание)** | `tcp_abort_on_overflow` | 1 | RST вместо тихого дропа ACK. |

### Production sysctl — полный набор

> *Подробнее:* [Production Tuning](../production_tuning.md#6-production-sysctl--quick-reference).

```bash
# /etc/sysctl.d/99-tcp-production.conf (см. production_tuning.md)
sudo sysctl -p /etc/sysctl.d/99-tcp-production.conf
```

---

## Дополнительная информация

### Инструменты анализа (2026)

- **ss (Socket Statistics):** Основной инструмент диагностики. Флаг `-t` (TCP), `-i` (Internal info), `-p` (Processes).
- **nstat:** Просмотр агрегированных счетчиков SNMP стека TCP.
- **eBPF (tcpstates):** Утилита из пакета `bcc-tools` / `bpftrace`, позволяющая видеть переходы состояний в реальном времени с указанием задержек.
- **conntrack:** Модуль ядра для отслеживания соединений (особенно полезен для NAT).
- **tcpkill:** Утилита для принудительного закрытия TCP-соединений.
- **tcp_splice:** Утилита для перенаправления данных между соединениями.

### См. также

- **[Установка соединения (Handshake)](./tcp_connection_overview.md)** — детальный разбор SYN/ACK.
- **[Завершение соединения](./tcp_connection_termination.md)** — описание 4-way handshake и полузакрытых сокетов.
- **[Диагностика сокетов в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_socket_diagnostics.md)** — практическая интерпретация метрик `ss`.
- **[Управление TIME_WAIT в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_time_wait_management.md)** — глубокий тюнинг `tcp_tw_reuse`.
- **[Диагностика TCP-соединений](./tcp_connection_diagnostics.md)** — дополнительные методы диагностики.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (современная спецификация 2022 года, объединяющая FSM).
- **RFC 1122:** Requirements for Internet Hosts (раздел 4.2.2.11 — уточнения по жизненному циклу).
- **RFC 7323:** TCP Extensions for High Performance (влияние Timestamps на состояния).
- **RFC 6528:** Defending against Sequence Number Attacks (защита от TCP sequence prediction).
- **RFC 4937:** IANA TCP Option Kind Numbers (реестр опций TCP).
