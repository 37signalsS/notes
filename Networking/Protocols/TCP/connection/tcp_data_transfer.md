# Передача данных в TCP

## Определения

**Передача данных в TCP** — это процесс обмена информацией между двумя узлами после успешного установления логического соединения. В отличие от протоколов, ориентированных на сообщения (например, UDP), TCP предоставляет абстракцию **надежной передачи потока байт (Reliable Byte Stream)**, скрывая от приложения процессы фрагментации, переупорядочивания и повторной передачи.

---

## Основные концепции

### Потоковая модель данных (Byte Stream)

TCP рассматривает поступающие данные как непрерывную последовательность байт, а не как набор отдельных пакетов.

- **Абстракция:** Приложение просто записывает байты в буфер сокета (через системные вызовы `send` или `write`), а стек TCP самостоятельно решает, когда и как отправить эти данные в сеть.
- **Сегментация:** TCP нарезает поток байт на сегменты. Максимальный размер полезной нагрузки в сегменте ограничивается параметром **MSS (Maximum Segment Size)**, который согласовывается во время рукопожатия и зависит от MTU сетевого интерфейса.
- **Отсутствие границ сообщений:** TCP не сохраняет границы прикладных сообщений. Данные, отправленные двумя вызовами `write()`, могут быть доставлены одним большим сегментом, или один большой `write()` может быть разбит на несколько сегментов. Приложение-получатель обязано самостоятельно извлекать границы своих сообщений (например, через заголовки с длиной `Content-Length` в HTTP).

### Управление скоростью передачи

Скорость и объем передаваемых данных в любой момент времени динамически ограничиваются двумя механизмами:

1.  **Окно получателя (Receive Window, `rwnd`):** Механизм [управления потоком (Flow Control)](../Flow_Control/index.md). Окно анонсируется получателем и гарантирует, что отправитель не переполнит буфер на стороне приложения.
2.  **Окно перегрузки (Congestion Window, `cwnd`):** Механизм [управления перегрузкой (Congestion Control)](../congestion/tcp_congestion_control_overview.md). Вычисляется отправителем для защиты сетевой инфраструктуры от переполнения.

**Эффективное окно (Send Window):** Реальный лимит байтов "в полете" (Inflight) всегда равен минимуму: `min(cwnd, rwnd)`.

### Надежность и нумерация

Каждый передаваемый байт имеет свой **порядковый номер (Sequence Number)**. Это позволяет:
- Восстанавливать исходный порядок байт на принимающей стороне, даже если сегменты пришли разными маршрутами.
- Отбрасывать дубликаты пакетов.
- Точно указывать в **подтверждениях (ACK)**, какие данные успешно получены, а какие требуют повторной передачи (включая использование опции SACK — Selective Acknowledgments).

---

## Управление задержками и эффективностью

### Агрегация мелких пакетов

Передача пакетов размером в 1-2 байта (например, нажатия клавиш в SSH) крайне неэффективна из-за накладных расходов на заголовки TCP/IPv4 (минимум 40 байт).

| Алгоритм / Опция | Описание и применение |
| :--- | :--- |
| **Алгоритм Нагла (Nagle)** | Накапливает мелкие данные в буфере до тех пор, пока не наберется полный MSS, либо пока не придет ACK на предыдущую отправку. Экономит полосу, но может вызывать задержки. |
| **TCP_CORK** | Более агрессивный аналог Нагла в Linux. Блокирует отправку любых неполных сегментов, пока опция не будет отключена. Полезен при сборке HTTP-ответов из разных буферов. |
| **TCP_NODELAY** | Опция сокета, полностью отключающая алгоритм Нагла. Данные отправляются немедленно. Критически важно для онлайн-игр и RPC-вызовов (gRPC). |
| **TCP_DEFER_ACCEPT** | (Linux) Откладывает `accept()` до поступления первых данных от клиента или истечения таймаута. Экономит ресурсы приложения, не пробуждая его для «пустых» соединений. |

### Конфликт: Nagle и Delayed ACK (Deadlock)

На стороне получателя работает механизм **Delayed ACK**, который задерживает отправку подтверждения (обычно до 200 мс в Linux, минимум 40 мс), надеясь объединить его с ответными данными (Piggybacking). 
Если отправитель использует алгоритм Нагла, а получатель — Delayed ACK, возникает тупиковая ситуация: отправитель ждет ACK, чтобы отправить остаток данных, а получатель ждет вторую порцию данных, чтобы послать ответ с ACK. Это приводит к стабильным необъяснимым задержкам ~200 мс в сети.

**Решения конфликта:**

1. **TCP_NODELAY на стороне отправителя:** Полностью отключает алгоритм Нагла.
2. **TCP_QUICKACK на стороне получателя:** Отключает Delayed ACK для конкретного соединения.
3. **HTTP/2 и HTTP/3:** Протоколы сами управляют мультиплексированием, Nagle отключается по умолчанию.
4. **gRPC/WebSockets:** Рекомендуется отключать Nagle на стороне клиента и сервера.

### Аппаратное ускорение: Offloading (2026)

Современные сетевые стеки перекладывают рутинные задачи по сегментации с CPU на сетевые адаптеры (NIC), что критично для работы на скоростях 100+ Гбит/с:

- **TSO (TCP Segmentation Offload):** ОС отдает сетевой карте один гигантский блок данных (до 64 КБ), а NIC аппаратно нарезает его на пакеты размером с MSS.
- **GRO (Generic Receive Offload):** Сетевая карта агрегирует множество мелких входящих TCP-сегментов в один большой блок перед передачей его в ядро ОС.
- **Zero-Copy:** Использование системных вызовов `sendfile()` или `splice()` позволяет ядру передавать данные с диска прямо в сетевой сокет, минуя буферы пространства пользователя.

**Проверка состояния offloading:**
```bash
# Показать статус всех функций разгрузки
sudo ethtool -k eth0 | grep -E 'tcp-segmentation-offload|generic-receive-offload'
# → tcp-segmentation-offload: on
# → generic-receive-offload: on

# Временное отключение для «чистого» захвата трафика
sudo ethtool -K eth0 tso off gso off gro off
```

---

## Практические сценарии

### Сценарий 1: Диагностика сегментации через tcpdump

При анализе дампов на отправляющем сервере (до выхода пакета в физическую сеть) можно увидеть пакеты, значительно превышающие MTU (например, 10 000 байт). Это не ошибка сети, а результат работы **TSO** (ядро сбросило большой кусок драйверу).

```bash
# Просмотр флагов (P = PSH) и размера Payload
sudo tcpdump -ni eth0 'tcp port 80'
# → 10:00:01 IP 1.1.1.1.443 > 2.2.2.2.54321: Flags [P.], seq 1001:2001, ack 1, win 501, length 1000
```
Флаг **PSH (Push)** в дампе указывает стеку получателя на необходимость немедленно передать накопленные данные приложению.

### Сценарий 2: Мониторинг передачи через nstat

В Linux глобальные счетчики ядра позволяют быстро оценить здоровье передачи:

```bash
nstat -az | grep -E 'TcpOutSegs|TcpInSegs|TcpRetransSegs'
```
Отношение `TcpRetransSegs` (переотправленные) к `TcpOutSegs` (отправленные) дает процент потерь в сети.

### Сценарий 3: Диагностика конфликта Nagle + Delayed ACK

**Задача:** Определить, вызывает ли алгоритм Нагла задержки ~200 мс в интерактивном приложении.

```bash
# Шаг 1: Просмотр состояния сокета
ss -tin dst 10.0.0.1:22
# → cubic rto:204 rtt:15.2/0.5 nagle ato:200
# → Результат: nagle + ato:200 указывают на активный Delayed ACK

# Шаг 2: Анализ задержек через tcpdump
sudo tcpdump -ni eth0 'tcp port 22' -tt
# → 12:00:00.000 IP 10.0.0.1 > 10.0.0.2: Flags [P.], seq 1:10, ack 1
# → 12:00:00.200 IP 10.0.0.2 > 10.0.0.1: Flags [.], ack 10
# → Результат: Задержка 200 мс — признак конфликта

# Шаг 3: Отключение Nagle через sysctl (временно)
sudo sysctl -w net.ipv4.tcp_low_latency=1
# → Включает приоритет латентности над пропускной способностью
```

### Сценарий 4: Мониторинг эффективности передачи

**Задача:** Оценить соотношение полезных данных и ретрансмиссий.

```bash
# Просмотр общей статистики
nstat -az | grep -E 'TcpOutData|TcpRetrans|TcpInSegs'
# → TcpOutDataSegs    12345    0.0
# → TcpRetransSegs    45       0.0
# → TcpInSegs         12340    0.0

# Расчет процента ретрансмиссий
echo "scale=2; 45 * 100 / 12345" | bc
# → 0.36% — норма для стабильной сети

# Мониторинг в реальном времени
watch -n 2 'nstat -az | grep -E "TcpOutData|TcpRetrans"'
```

### Сценарий 5: Оптимизация sendfile для статических файлов

**Задача:** Включить Zero-Copy передачу в Nginx для раздачи статики.

```bash
# Проверка поддержки sendfile в ядре
cat /proc/filesystems | grep -q sendfile && echo "sendfile supported"

# Настройка Nginx
cat > /etc/nginx/conf.d/sendfile.conf << 'EOF'
sendfile on;
tcp_nopush on;
tcp_nodelay off;

# Ограничение размера блока sendfile (предотвращает блокировку воркера)
sendfile_max_chunk 1m;
EOF

# Проверка через strace (требует root)
sudo strace -e trace=sendfile -p $(pgrep -f "nginx: worker") -f
# → sendfile(5, 7, [0], 131072) = 131072
# → Результат: Системный вызов sendfile подтверждает Zero-Copy
```

### Сценарий 6: Настройка TCP_NODELAY для gRPC/ WebSocket

**Задача:** Включить немедленную отправку данных для low-latency приложений.

```python
# Python: Отключение Nagle для WebSocket
import socket
import websocket

ws = websocket.create_connection("ws://example.com/socket")
sock = ws.sock
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

# Проверка через ss
# ss -tin dst example.com:443
# → cubic rto:204 rtt:15.2/0.5 nodelay
```

```go
// Go: Отключение Nagle для gRPC
conn, err := net.Dial("tcp", "grpc-server:50051")
if err != nil {
    log.Fatal(err)
}
tcpConn := conn.(*net.TCPConn)
tcpConn.SetNoDelay(true)
```

---

## Практические команды

### Просмотр и настройка параметров передачи

```bash
# Текущие параметры TCP
sysctl net.ipv4.tcp_window_scaling
sysctl net.ipv4.tcp_timestamps
sysctl net.ipv4.tcp_sack

# Включение масштабирования окна (рекомендуется)
sudo sysctl -w net.ipv4.tcp_window_scaling=1

# Включение Timestamps (необходимо для PAWS и точного RTT)
sudo sysctl -w net.ipv4.tcp_timestamps=1

# Включение SACK (улучшает восстановление после потерь)
sudo sysctl -w net.ipv4.tcp_sack=1
```

### Мониторинг через ss

```bash
# Детальная информация о TCP-соединениях
ss -tin state established

# Ключевые поля для анализа передачи:
# - cwnd: текущее окно перегрузки (в MSS)
# - rcv_wnd: окно получателя (в байтах)
# - snd_wnd: окно отправителя (в байтах)
# - pacing_rate: скорость отправки (для BBR)
# - delivery_rate: реальная скорость доставки
# - app_limited: флаг ограничения приложением

# Фильтрация по конкретным соединениям
ss -tin dst 10.0.0.1:443 | grep -oE 'cwnd:[0-9]+|rcv_wnd:[0-9]+|delivery_rate [0-9]+Mbps'
```

### Мониторинг через nstat

```bash
# Просмотр счетчиков передачи данных
nstat -az | grep -E 'TcpOutData|TcpInData|TcpRetrans'

# Ключевые счетчики:
# - TcpOutDataSegs: сегменты с полезными данными
# - TcpOutDataBytes: байты полезных данных
# - TcpRetransSegs: переотправленные сегменты
# - TcpInSegs: входящие сегменты

# Мониторинг в реальном времени (каждые 2 секунды)
watch -n 2 'nstat -az | grep -E "TcpOutData|TcpRetrans"'
```

---

## Linux sysctl параметры для тюнинга

| Параметр | Значение по умолчанию | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| `net.ipv4.tcp_window_scaling` | 1 | Масштабирование окна | Включено (не отключать) |
| `net.ipv4.tcp_timestamps` | 1 | Временные метки для RTT/PAWS | Включено (не отключать) |
| `net.ipv4.tcp_sack` | 1 | Выборочные подтверждения | Включено (не отключать) |
| `net.ipv4.tcp_low_latency` | 0 | Приоритет латентности | 1 для интерактивных приложений |
| `net.ipv4.tcp_moderate_rcvbuf` | 1 | Автоматическая настройка буфера | 1 (стандарт) |
| `net.ipv4.tcp_no_metrics_save` | 0 | Сохранение метрик соединения | 1 для динамичных сред |

---

## Контекст Docker и Kubernetes

### Docker

```bash
# Проверка параметров передачи в контейнере
docker exec <container> sysctl net.ipv4.tcp_window_scaling
docker exec <container> sysctl net.ipv4.tcp_sack

# Установка оптимальных параметров (на хосте)
sudo tee /etc/sysctl.d/99-tcp-transfer.conf << 'EOF'
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_low_latency = 0
EOF
sudo sysctl --system
```

### Kubernetes

```yaml
# Проверка параметров в поде
apiVersion: v1
kind: Pod
metadata:
  name: tcp-check
spec:
  containers:
  - name: app
    image: busybox
    command: ["sysctl", "-a", "net.ipv4.tcp_window_scaling"]
```

```bash
# Проверка на ноде
kubectl exec <pod> -- sysctl net.ipv4.tcp_window_scaling

# Настройка через SecurityContext (если разрешено)
apiVersion: v1
kind: Pod
metadata:
  name: tcp-tuning
spec:
  containers:
  - name: app
    image: nginx
    securityContext:
      capabilities:
        add: ["NET_ADMIN"]
    command: ["sysctl", "-w", "net.ipv4.tcp_low_latency=1"]
```

---

## Диагностика проблем

### Проблема: Низкая скорость передачи

```bash
# Шаг 1: Проверка размера окна
ss -tin dst 10.0.0.1:443 | grep -oE 'cwnd:[0-9]+|rcv_wnd:[0-9]+'
# → cwnd:10 rcv_wnd:65536

# Шаг 2: Проверка размера MSS
sudo tcpdump -ni eth0 'tcp port 443' -c 5 | grep -oE 'length [0-9]+'
# → length 1460 — стандартный MSS

# Шаг 3: Проверка offloading
ethtool -k eth0 | grep -E 'tcp-segmentation|generic-receive'
# → tcp-segmentation-offload: on
# → generic-receive-offload: on

# Шаг 4: Проверка буферов
cat /proc/sys/net/core/rmem_max
# → 212992 — стандартный размер
```

### Проблема: Высокая задержка ACK

```bash
# Шаг 1: Проверка ato (Acknowledgment Timeout)
ss -tin dst 10.0.0.1:443 | grep -oE 'ato:[0-9]+'
# → ato:200 — стандартный Delayed ACK

# Шаг 2: Включение QuickACK
sudo sysctl -w net.ipv4.tcp_quickack=1

# Шаг 3: Проверка через tcpdump
sudo tcpdump -ni eth0 'tcp port 443' -tt | head -n 10
# → Анализ задержек между пакетами
```

---

## Дополнительная информация

### См. также

- **[Алгоритм Нагла](../tcp_nagle_algorithm.md)** — глубокий разбор конфликта с Delayed ACK и применение TCP_NODELAY.
- **[Подтверждения (ACK)](../reliability_mechanisms/acknowledgments.md)** — Delayed ACK, SACK, QuickACK.
- **[Сетевая разгрузка в Linux](../../../../Linux/Networking/Concepts/offloading.md)** — TSO, GRO, RSS, kTLS.
- **[Дисциплины очередей (qdisc)](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md)** — pacing и управление очередями.

### Стандарты (RFC)

- **RFC 9293:** Transmission Control Protocol (современная консолидация 2022 года).
- **RFC 1122:** Requirements for Internet Hosts (определение Delayed ACK, Nagle, SWS).
- **RFC 896:** Congestion Control in IP/TCP Internetworks (оригинальное описание алгоритма Нагла).
- **RFC 7323:** TCP Extensions for High Performance (Window Scale, Timestamps, PAWS).
- **RFC 2018:** TCP Selective Acknowledgment Options (SACK).
- **RFC 6298:** Computing TCP's Retransmission Timer (алгоритм RTO).
