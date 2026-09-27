# Управление очередями соединений TCP в Linux

## Определения

**TCP Backlog** — многоуровневая система очередей на стороне сервера, предназначенная для управления входящими запросами на соединение. Состоит из трех основных компонентов:

*   **SYN backlog (Полуоткрытые соединения):** Очередь запросов в состоянии `SYN_RECV`. Контролируется параметром `net.ipv4.tcp_max_syn_backlog`. В современных ядрах (4.4+) эта очередь эффективно реализована через хэш-таблицы, но лимит всё ещё ограничивает защиту от SYN-флуда до включения SYN Cookies. Размер определяет, сколько полуоткрытых соединений может находиться в ожидании завершения рукопожатия.
*   **Accept backlog (Установленные соединения):** Очередь соединений, завершивших 3-этапное рукопожатие (`ESTABLISHED`), но ещё не забранных приложением через системный вызов `accept()`. Размер ограничен параметром `net.core.somaxconn`. Определяет, сколько установленных соединений может ожидать обработки приложением.
*   **NIC backlog (Входная очередь пакетов):** Очередь пакетов, ожидающих обработки мягким прерыванием (**SoftIRQ**) перед передачей в стек протоколов. Контролируется параметром `net.core.netdev_max_backlog`. Определяет, сколько пакетов может быть буферизировано на уровне устройства до обработки ядром.

**ListenOverflows / ListenDrops** — счётчики переполнения Accept backlog. При переполнении ядро по умолчанию молча отбрасывает пакеты ACK от клиента, заставляя его выполнять ретрансмиссию (что позволяет приложению "нагнать" очередь). ListenOverflows — прямое указание на переполнение Accept backlog. ListenDrops — общее число отброшенных запросов (включая нехватку памяти).

**netdev_max_backlog** — максимальное количество пакетов в очереди входного устройства (NIC), ожидающих обработки мягким прерыванием (**SoftIRQ**) перед передачей в стек протоколов. Критичен для высокоскоростных интерфейсов (10G/40G/100G), где NIC может генерировать пакеты быстрее, чем ядро их обрабатывает.

**somaxconn** — глобальный верхний предел размера Accept backlog для всех сокетов. Определяет максимальное количество установленных соединений, которые могут одновременно ожидать вызова `accept()` от приложения. Эффективный лимит = `min(somaxconn, backlog_приложения)`.

**TCP_DEFER_ACCEPT** — механизм, позволяющий приложению отложить создание соединения до получения первых данных от клиента. Соединение остается в SYN backlog до тех пор, пока от клиента не поступят данные (или не истечёт таймаут). Экономит ресурсы приложения, не пробуждая его для "пустых" соединений.

**SYN Cookies** — механизм защиты от SYN-флуда, активируемый при переполнении SYN backlog. Сервер не выделяет память под запись в очереди, а шифрует параметры соединения в поле `Sequence Number` пакета SYN-ACK. Позволяет успешно обрабатывать легитимные запросы даже во время атаки.

## Основные концепции

### Жизненный цикл и переходы

Путь входящего соединения зависит от настроек ядра и приложения:

1.  **SYN-пакет:** Попадает в **SYN backlog**. Сервер отвечает SYN-ACK.
2.  **ACK от клиента:** Соединение считается установленным на уровне ядра.
3.  **Переход в Accept backlog:**
    *   **По умолчанию:** Соединение переходит в Accept backlog сразу после получения ACK.
    *   **С TCP_DEFER_ACCEPT:** Соединение остается в SYN backlog до тех пор, пока от клиента не поступят первые данные (или не истечёт таймаут). Это экономит ресурсы приложения, не пробуждая его для "пустых" соединений.
    *   **Взаимодействие с TCP Fast Open (TFO):** При использовании TFO соединение может попасть в Accept backlog сразу с данными, пропуская стандартную фазу ожидания ACK.
4.  **Обработка приложением:** Вызов `accept()` извлекает соединение из очереди и создаёт файловый дескриптор.

**Детальный процесс перехода:**
```
Клиент                    Сервер (Ядро)              Приложение
   |                           |                          |
   |--- SYN ----------------->|                          |
   |   [SYN backlog]          |                          |
   |<-- SYN-ACK --------------|                          |
   |                           |                          |
   |--- ACK ----------------->|                          |
   |   [Accept backlog]       |                          |
   |                           |--- accept() ----------->|
   |                           |<-- fd ------------------|
   |                           |                          |
   |--- DATA ---------------->|                          |
   |<-- DATA -----------------|                          |
```

### Поведение при переполнении (tcp_abort_on_overflow)

По умолчанию (`tcp_abort_on_overflow = 0`) при переполнении Accept backlog сервер игнорирует входящие ACK. Клиент думает, что его ACK потерян, и пробует снова.
*   **Тюнинг:** Установка `net.ipv4.tcp_abort_on_overflow = 1` заставляет сервер немедленно отвечать пакетом **RST**. Это полезно, если перед сервером стоит балансировщик (LBP), который должен мгновенно узнать о перегрузке узла и переключить трафик на другой бэкенд.

**Сравнение поведения:**
| Параметр | Поведение при переполнении | Когда использовать |
| :--- | :--- | :--- |
| `tcp_abort_on_overflow = 0` | Игнорирование ACK, ожидание ретрансмита | Стандартные сценарии, когда балансировщик не критичен |
| `tcp_abort_on_overflow = 1` | Отправка RST | За балансировщиком, когда важна быстрая реакция |

### Механизм защиты SYN Cookies

При переполнении SYN backlog ядро переходит в режим **SYN Cookies** (`net.ipv4.tcp_syncookies = 1`). В этом режиме сервер не выделяет память под запись в очереди, а шифрует параметры соединения в поле `Sequence Number` пакета SYN-ACK. Это позволяет успешно обрабатывать легитимные запросы даже во время SYN-флуда.

**Принцип работы SYN Cookies:**
1. При получении SYN пакета сервер вычисляет специальное значение на основе IP-адресов, портов и временной метки
2. Это значение встраивается в Sequence Number SYN-ACK
3. При получении ACK сервер проверяет значение и восстанавливает параметры соединения
4. Память выделяется только после завершения рукопожатия

**Ограничения SYN Cookies:**
*   Не работают с某些 расширениями TCP (например, MSS options)
*   Некоторые параметры соединения могут быть утеряны
*   Рекомендуется как временная мера при атаках, а не как основной механизм

### Взаимодействие с другими параметрами TCP

Очереди соединений тесно связаны с другими параметрами сетевого стека:

| Параметр | Взаимодействие | Рекомендация |
| :--- | :--- | :--- |
| `netdev_max_backlog` | Влияет на обработку пакетов до стека TCP | Увеличивать при высоких скоростях (10G+) |
| `somaxconn` | Определяет максимальный Accept backlog | Устанавливать равным или больше backlog приложения |
| `tcp_max_syn_backlog` | Определяет защиту от SYN-флуда | Увеличивать при высоком RPS |
| `tcp_syncookies` | Активируется при переполнении SYN backlog | Включать (1) для защиты от атак |
| `tcp_abort_on_overflow` | Определяет поведение при переполнении Accept backlog | Включать (1) за балансировщиком |
| `tcp_DEFER_ACCEPT` | Откладывает создание соединения до получения данных | Использовать для HTTP/REST API |
| `net.ipv4.ip_local_port_range` | Определяет диапазон эфемерных портов | Расширять при высоком исходящем трафике |

## Практические сценарии

### 1. Проверка текущих лимитов и состояний

```bash
# Просмотр системных лимитов
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.core.netdev_max_backlog
# → net.core.somaxconn = 128
# → net.ipv4.tcp_max_syn_backlog = 256
# → net.core.netdev_max_backlog = 1000

# Проверка очереди accept для слушающих портов
ss -lnt
# Send-Q — текущий эффективный лимит (min(somaxconn, backlog_приложения))
# Recv-Q — количество соединений, ожидающих в очереди accept()

# Просмотр всех Listening сокетов
ss -ltn | grep -E "State|LISTEN"

# Проверка конкретного порта
ss -ltn | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*
```

### 2. Тюнинг для Highload (2026)

Для систем с нагрузкой более 10 000 соединений в секунду и скоростями 10G+:

```ini
# /etc/sysctl.d/99-network-queues.conf

# Очередь полностью установленных соединений
net.core.somaxconn = 65535

# Очередь полуоткрытых соединений
net.ipv4.tcp_max_syn_backlog = 16384

# Входная очередь пакетов от NIC (важно для предотвращения дропов на L2/L3)
net.core.netdev_max_backlog = 30000

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Поведение при переполнении Accept backlog
net.ipv4.tcp_abort_on_overflow = 1

# Откладывание создания соединения до получения данных
net.ipv4.tcp_DEFER_ACCEPT = 1

# Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535

# Повторное использование TIME_WAIT сокетов
net.ipv4.tcp_tw_reuse = 1
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-network-queues.conf`

### 3. Настройка для Nginx

**Оптимальная конфигурация для высоконагруженного Nginx:**
```nginx
# /etc/nginx/nginx.conf

worker_processes auto;
worker_rlimit_nofile 65535;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    # Системные настройки
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Keep-alive
    keepalive_timeout 65;
    keepalive_requests 1000;

    # Буферы
    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;
    client_max_body_size 8m;

    # Очереди
    listen 80 backlog=16384;
    listen 443 ssl backlog=16384;
}
```

**Проверка:**
```bash
# Проверка Listen очередей
ss -ltn | grep :80
# → LISTEN  0  16384  0.0.0.0:80  0.0.0.0:*

# Проверка worker connections
ps aux | grep nginx
# → worker process 1, connections: 4096
```

### 4. Настройка для PostgreSQL

**Оптимальная конфигурация для PostgreSQL:**
```ini
# /etc/sysctl.d/99-postgres-queues.conf

# Очереди соединений
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 2048

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Откладывание создания соединения до получения данных
net.ipv4.tcp_DEFER_ACCEPT = 1
```

**Настройка в PostgreSQL:**
```sql
-- postgresql.conf
max_connections = 200
superuser_reserved_connections = 3
```

**Проверка:**
```bash
# Проверка Listen очередей
ss -ltn | grep :5432
# → LISTEN  0  4096  0.0.0.0:5432  0.0.0.0:*

# Мониторинг соединений
SELECT count(*) FROM pg_stat_activity;
```

### 5. Настройка для Kafka

**Оптимальная конфигурация для Kafka:**
```ini
# /etc/sysctl.d/99-kafka-queues.conf

# Очереди соединений
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 16384

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Повторное использование TIME_WAIT сокетов
net.ipv4.tcp_tw_reuse = 1
```

**Настройка в Kafka:**
```properties
# server.properties
num.network.threads=8
num.io.threads=16
socket.send.buffer.bytes=102400
socket.receive.buffer.bytes=102400
socket.request.max.bytes=104857600
```

**Проверка:**
```bash
# Проверка Listen очередей
ss -ltn | grep :9092
# → LISTEN  0  65535  0.0.0.0:9092  0.0.0.0:*

# Мониторинг соединений
kafka-broker-api-versions.sh --bootstrap-server localhost:9092
```

### 6. Настройка для Docker и контейнеров

**Системные настройки (на хосте):**
```bash
# Увеличение лимитов для контейнеров
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384
sudo sysctl -w net.core.netdev_max_backlog=30000
```

**Настройки для Docker:**
```bash
# При запуске контейнера
docker run --sysctl net.core.somaxconn=65535 \
           --sysctl net.ipv4.tcp_max_syn_backlog=16384 \
           your_image
```

**Для Kubernetes:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: high-perf-pod
spec:
  containers:
  - name: app
    image: your_image
    securityContext:
      sysctls:
      - name: net.core.somaxconn
        value: "65535"
      - name: net.ipv4.tcp_max_syn_backlog
        value: "16384"
```

### 7. Диагностика переполнения

**Использование nstat:**
```bash
nstat -az | grep -E 'ListenOverflows|ListenDrops|ReqQFullDrop'

# TcpExtTCPListenOverflows — переполнение Accept backlog
# TcpExtTCPListenDrops — общее число отброшенных запросов (вкл. нехватку памяти)
# TcpExtTCPReqQFullDrop — переполнение SYN backlog (при выключенных syncookies)
```

**Пример вывода:**
```bash
nstat -az | grep -E 'ListenOverflows|ListenDrops|ReqQFullDrop'
# TcpExtTCPListenOverflows    1234    0.0
# TcpExtTCPListenDrops        1234    0.0
# TcpExtTCPReqQFullDrop       0       0.0
```

**Глубокий анализ через eBPF (bpftrace):**
Позволяет увидеть, на каких именно портах и в какое время происходят переполнения:

```bash
# Отслеживание переполнений backlog в реальном времени
sudo bpftrace -e '
kprobe:tcp_v4_conn_request 
{ 
  $sk = (struct sock *)arg0;
  if ($sk->sk_ack_backlog > $sk->sk_max_ack_backlog) {
    printf("Backlog overflow! Local port: %d\n", ntop(AF_INET, $sk->sk_num));
  }
}'

# Отслеживание SYN пакетов
sudo bpftrace -e '
kprobe:tcp_v4_conn_request
{
  printf("SYN received on port %d\n", ntop(AF_INET, ((struct sock *)arg0)->sk_num));
}'

# Мониторинг accept queue
sudo bpftrace -e '
kprobe:tcp_accept_queue_full
{
  printf("Accept queue full on port %d, backlog: %d\n",
         ntop(AF_INET, ((struct sock *)arg0)->sk_num),
         ((struct sock *)arg0)->sk_max_ack_backlog);
}'
```

### 8. Сохранение настроек

**Постоянное сохранение (`/etc/sysctl.d/99-network-queues.conf`):**
```ini
# Очередь полностью установленных соединений
net.core.somaxconn = 65535

# Очередь полуоткрытых соединений
net.ipv4.tcp_max_syn_backlog = 16384

# Входная очередь пакетов от NIC
net.core.netdev_max_backlog = 30000

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1

# Поведение при переполнении Accept backlog
net.ipv4.tcp_abort_on_overflow = 1

# Откладывание создания соединения до получения данных
net.ipv4.tcp_DEFER_ACCEPT = 1

# Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535

# Повторное использование TIME_WAIT сокетов
net.ipv4.tcp_tw_reuse = 1
```

Применить: `sudo sysctl -p /etc/sysctl.d/99-network-queues.conf`

**Откат настроек:**
```bash
# Временный откат (до перезагрузки)
sudo sysctl -w net.core.somaxconn=128
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=256
sudo sysctl -w net.core.netdev_max_backlog=1000

# Полный откат
sudo rm /etc/sysctl.d/99-network-queues.conf
sudo sysctl --system
```

## Дополнительная информация

### Взаимодействие с приложениями

Лимит `somaxconn` является глобальным верхним пределом. Приложение при вызове `listen(fd, backlog)` задает своё значение. Эффективный лимит = **min(somaxconn, backlog_приложения)**.

**Настройка в популярных сервисах:**
*   **Nginx:** `listen 80 backlog=16384;`
*   **Redis:** параметр `tcp-backlog 511` в `redis.conf`.
*   **HAProxy:** параметр `backlog` в секции `global` или `listen`.
*   **PostgreSQL:** параметр `max_connections` в `postgresql.conf`.
*   **Kafka:** параметр `socket.request.max.bytes` в `server.properties`.

**Примеры настройки backlog в приложениях:**
```bash
# Nginx
listen 80 backlog=16384;
listen 443 ssl backlog=16384;

# Redis
tcp-backlog 511

# HAProxy
global
    backlog 65535

# PostgreSQL
max_connections = 200
superuser_reserved_connections = 3
```

### Рекомендации по выбору значений (2026)

| Роль системы | somaxconn | tcp_max_syn_backlog | netdev_max_backlog | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Edge Proxy (Nginx/Envoy)** | 65535 | 16384 | 30000 | Максимальные очереди для компенсации всплесков трафика. |
| **Database (PostgreSQL)** | 4096 | 2048 | 1000 | Слишком большие очереди могут маскировать проблемы с производительностью запросов. |
| **Internal Microservice** | 8192 | 4096 | 1000 | Оптимально для среды Kubernetes/Service Mesh. |
| **Kafka Broker** | 65535 | 16384 | 30000 | Максимальные очереди для высокопроизводительных очередей сообщений. |
| **Redis Server** | 4096 | 2048 | 1000 | Стандартные настройки для кэширования. |
| **Docker Host** | 65535 | 16384 | 30000 | Увеличенные лимиты для контейнеров. |

### Диагностика типичных проблем

**Проблема: Connection refused**
```bash
# Проверка somaxconn
sysctl net.core.somaxconn
# → net.core.somaxconn = 128 (слишком мало)

# Проверка Listen очередей
ss -lnt | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*
# Recv-Q = 128 (очередь переполнена)

# Решение
sudo sysctl -w net.core.somaxconn=65535
```

**Проблема: Высокая задержка**
```bash
# Проверка accept queue
ss -lnt | awk 'NR>1 {print $2, $4}'
# → 128 0 (очередь полна, соединения ждут)

# Проверка ListenOverflows
nstat -az | grep ListenOverflows
# → TcpExtTCPListenOverflows 1234 0.0 (переполнения происходят)

# Решение
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384
```

**Проблема: SYN-флуд атака**
```bash
# Проверка SYN Cookies
sysctl net.ipv4.tcp_syncookies
# → net.ipv4.tcp_syncookies = 0 (отключена)

# Проверка SYN backlog
nstat -az | grep ReqQFullDrop
# → TcpExtTCPReqQFullDrop 5678 0.0 (переполнения происходят)

# Решение
sudo sysctl -w net.ipv4.tcp_syncookies=1
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384
```

### Edge Cases и ограничения

**1. Связка с NAT и балансировщиками:**
При использовании NAT или балансировщиков перед сервером:
*   Убедитесь, что балансировщик поддерживает `tcp_abort_on_overflow = 1`
*   Настройте health check интервалы с учетом времени восстановления соединений
*   Рассмотрите использование `tcp_tw_reuse` для повторного использования TIME_WAIT

**2. Kubernetes и Service Mesh:**
В среде Kubernetes:
*   Увеличивайте `somaxconn` на всех нодах
*   Настройте `tcp_max_syn_backlog` для защиты от SYN-флуда
*   Используйте `tcp_ABORT_on_overflow = 1` для быстрого отклика балансировщика

**3. Высокоскоростные сети (100G/400G):**
Для сетей с высокой пропускной способностью:
*   Увеличивайте `netdev_max_backlog` до 100000+
*   Настройте `somaxconn` и `tcp_max_syn_backlog` до максимальных значений
*   Используйте RSS/RPS для распределения нагрузки по CPU

**4. Многопоточные приложения:**
Для многопоточных приложений:
*   Убедитесь, что `somaxconn` достаточен для количества потоков
*   Рассмотрите использование `SO_REUSEPORT` для распределения соединений
*   Настройте `tcp_DEFER_ACCEPT` для оптимизации обработки пустых соединений

### Мониторинг и алерты

**Настройка мониторинга через Prometheus + node_exporter:**
```yaml
# Примеры алертов
groups:
- name: tcp_queue_alerts
  rules:
  - alert: HighListenOverflows
    expr: rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий уровень переполнения Accept backlog"
      description: "Rate переполнений > 10 в течение 5 минут"

  - alert: HighListenDrops
    expr: rate(node_netstat_TcpExt_TCPListenDrops[5m]) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Высокий уровень отброшенных запросов"
      description: "Rate отброшенных запросов > 10 в течение 5 минут"

  - alert: AcceptQueueFull
    expr: node_netstat_TcpExt_TCPListenOverflows > 100
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Accept backlog переполнен"
      description: "Обнаружены переполнения Accept backlog > 100"
```

**Автоматизация диагностики:**
```bash
# Скрипт быстрой диагностики TCP очередей
#!/bin/bash
echo "=== TCP Queue Diagnostics ==="
echo "--- System Limits ---"
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.core.netdev_max_backlog
echo "--- Listen Queues ---"
ss -lnt | awk 'NR>1 {print $1, $2, $4, $6}'
echo "--- Overflow Counters ---"
nstat -az | grep -E "ListenOverflows|ListenDrops|ReqQFullDrop"
echo "--- SYN Cookies ---"
sysctl net.ipv4.tcp_syncookies
echo "--- Deferred Accept ---"
sysctl net.ipv4.tcp_DEFER_ACCEPT
```

### См. также
* **[Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)** — комплексный тюнинг сетевого стека.
* **[Оптимизация буферов TCP](./tcp_buffer_tuning.md)** — настройка rmem/wmem.
* **[Диагностика сокетов TCP](./tcp_socket_diagnostics.md)** — использование `ss` и `nstat`.
* **[Диагностика потерь в стеке](../../network_stack_packet_loss.md)** — поиск проблем в очередях `netdev_max_backlog`.
