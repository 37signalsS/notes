# TCP_NODELAY / TCP_CORK / TCP_QUICKACK — Практическое руководство

## Определения

**TCP_NODELAY** — опция сокета, отключающая алгоритм Nagle. При включении ядро немедленно отправляет данные в TCP-стек, даже если размер сегмента меньше MSS. Снижает latency для маленьких сообщений ценой роста числа пакетов.

**TCP_CORK** — опция сокета (Linux-специфичная), блокирующая отправку неполных сегментов до тех пор, пока не накопится MSS данных или не будет вызван `TCP_UNCORK`. Агрессивная альтернатива Nagle для batch-отправки.

**TCP_QUICKACK** — опция сокета, принудительно отключающая Delayed ACK для конкретного соединения. В Linux является «одноразовым» флагом — сбрасывается после каждого `recv()` и требует повторной установки.

**Nagle Algorithm** — алгоритм агрегации мелких сегментов (RFC 896/1122). Отправляет данные только если: (1) есть MSS данных, или (2) все отправленные данные подтверждены (ACK), или (3) это принудительная отправка (PSH). Цель — уменьшить число мелких пакетов.

**Delayed ACK** — механизм отложенного подтверждения (RFC 1122 §4.2.3.2). Ядро ждёт до 40-200 мс перед отправкой ACK, надеясь «прилепить» его к исходящему данных (piggybacking). Экономит пакеты, но увеличивает latency.

---

## Теоретический блок

### Nagle + Delayed ACK: проблема deadlock

```
Клиент (Nagle вкл)              Сервер (Delayed ACK)
    │                                │
    │  Маленькое сообщение (50 байт) │
    │ ──────────────────────────────►│
    │                                │
    │  Nagle: жду ACK...             │  Delayed ACK: жду данные...
    │  (не отправляю новые данные)   │  (не отправляю ACK сразу)
    │                                │
    │  ........ deadlock 200 мс ......│
    │                                │
    │  ACK приходит                  │  ACK отправлен (40-200 мс)
    │ ◄──────────────────────────────│
    │                                │
    │  Наконец отправляю             │
```

Эта комбинация создаёт задержку 40-200 мс на каждое маленькое сообщение.

### Решения конфликта Nagle + Delayed ACK

| Решение | Где | Эффект | Ограничение |
|---|---|---|---|
| **TCP_NODELAY** | Клиент | Отключает Nagle, данные уходят немедленно | Рост числа пакетов |
| **TCP_QUICKACK** | Сервер | Отключает Delayed ACK | Одноразовый флаг, нужен re-arm |
| **Отправка полных сегментов** | Приложение | Nagle не блокирует | Требует batching в приложении |
| **TCP_CORK** | Сервер | Блокирует отправку до MSS | Linux-специфичный |

### Взаимодействие TCP_NODELAY и TCP_CORK

Эти опции **взаимоисключающие**:

```c
// TCP_CORK имеет приоритет над TCP_NODELAY
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &one, sizeof(one));  // Включить CORK
setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one)); // CORK всё ещё активен!

// Чтобы TCP_NODELAY работал, сначала отключите CORK:
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &zero, sizeof(zero));
setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
```

### TCP_QUICKACK: одноразовый флаг

```c
// TCP_QUICKACK сбрасывается после каждого recv()
while (1) {
    int quickack = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_QUICKACK, &quickack, sizeof(quickack));
    recv(fd, buf, sizeof(buf), 0);
    // После recv() флаг сброшен, нужно ставить заново
}
```

### Сравнение опций

| Опция | Влияние на отправку | Влияние на приём | Совместимость | Сценарий |
|---|---|---|---|---|
| **TCP_NODELAY** | Немедленная отправка | Нет | POSIX | gRPC, Redis, SSH, interactive |
| **TCP_CORK** | Блокирует до MSS | Нет | Linux only | HTTP ответы, batch writes |
| **TCP_QUICKACK** | Нет | Немедленный ACK | Linux only | Серверы, latency-sensitive |
| **Nagle (вкл)** | Агрегация мелких | Нет | POSIX | Bulk transfer |

### Когда что включать

| Сценарий | TCP_NODELAY | TCP_CORK | TCP_QUICKACK |
|---|---|---|---|
| **gRPC / HTTP/2** | Вкл | Выкл | Вкл на сервере |
| **Redis / Memcached** | Вкл | Выкл | Вкл на сервере |
| **SSH** | Вкл | Выкл | Вкл |
| **WebSocket** | Вкл | Выкл | Вкл |
| **HTTP/1.1 ответ** | Вкл | Вкл → UNCORK | Вкл |
| **Bulk send (файлы)** | Выкл | Вкл → UNCORK | Выкл |
| **Database driver** | Вкл | Выкл | Вкл |
| **Video streaming** | Выкл | Вкл | Выкл |
| **Nginx upstream** | Вкл (по умолчанию) | `tcp_nopush on` | — |
| **Envoy proxy** | Вкл | Выкл | Вкл |

---

## Практический блок

### Включение через setsockopt

```c
// TCP_NODELAY
int enable = 1;
setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &enable, sizeof(enable));

// TCP_CORK
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &enable, sizeof(enable));

// UNCORK (принудительная отправка)
int disable = 0;
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &disable, sizeof(disable));

// TCP_QUICKACK
setsockopt(fd, IPPROTO_TCP, TCP_QUICKACK, &enable, sizeof(enable));
```

```python
# Python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# TCP_NODELAY
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

# TCP_CORK
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)
# ... записать данные ...
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 0)  # Отправить

# TCP_QUICKACK
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
```

```go
// Go
conn, _ := net.Dial("tcp", "10.0.0.1:8080")
tcpConn := conn.(*net.TCPConn)
tcpConn.SetNoDelay(true)  // TCP_NODELAY
// Go не имеет прямой поддержки TCP_CORK, но SetNoDelay(false) включает Nagle
```

### Конфигурация Nginx

```nginx
server {
    listen 80;

    # TCP_NODELAY — включён по умолчанию в современном Nginx
    tcp_nodelay on;

    # TCP_CORK (tcp_nopush в терминологии Nginx)
    # Работает с sendfile: блокирует до заполнения buffer
    tcp_nopush on;

    # Комбинация: sendfile + tcp_nopush + tcp_nodelay
    # tcp_nopush работает ТОЛЬКО когда sendfile активен
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;  # После sendfile завершается, переключается в ноделай
}
```

### Конфигурация Envoy / Istio

```yaml
# Envoy TCP proxy
listeners:
  - name: downstream
    address:
      socket_address:
        address: 0.0.0.0
        port_value: 8080
    filter_chains:
      - filters:
        - name: envoy.filters.network.tcp_proxy
          typed_config:
            "@type": type.googleapis.com/envoy.extensions.filters.network.tcp_proxy.v3.TcpProxy
            cluster: upstream
            # TCP_NODELAY включён по умолчанию
```

### Diagnostics

```bash
# Проверить TCP_NODELAY для соединения
ss -tin dst 10.0.0.1 | grep -i nodelay
# → nodelay в выводе означает TCP_NODELAY включён

# Проверить TCP_CORK
ss -tin dst 10.0.0.1 | grep -i cork

# Проверить Delayed ACK через ato
ss -tin dst 10.0.0.1 | grep -o 'ato:[0-9]*'
# → ato:40 означает QuickACK (40 мс)
# → ato:200 означает Delayed ACK (200 мс)

# Мониторинг Delayed ACK через nstat
watch -n1 'nstat -az | grep -E "TCPACKDelayed|TCPQuickAck|TCPPureAcks"'
# TcpExtTCPACKDelayed → количество Delayed ACK
# TcpExtTCPQuickAckMode → количество QuickACK переключений
# TcpExtTCPPureAcks → количество «чистых» ACK (без данных)

# bpftrace: трассировка Delayed ACK
bpftrace -e 'kprobe:tcp_send_delayed_ack { printf("delayed_ack: %s\n", comm); }'

# Wireshark filter: Delayed ACK
tcp.analysis.delayed_ack

# Wireshark filter: Nagle hold
tcp.analysis.nagle_delay
```

### Проблемы и решения

| Проблема | Симптомы | Причина | Решение |
|---|---|---|---|
| **40 мс latency** | `ss -tin` показывает ato:200 | Delayed ACK + Nagle | TCP_NODELAY на клиенте + TCP_QUICKACK на сервере |
| **Много мелких пакетов** | Рост PPS, CPU на обработке | TCP_NODELAY без batching | Использовать TCP_CORK для batch sends |
| **gRPC latency** | p99 > 100 мс | Nagle + Delayed ACK | TCP_NODELAY на обоих концах |
| **WebSocket lag** | Задержки в чате | Nagle агрегирует сообщения | TCP_NODELAY |
| **Redis latency** | `INFO latency` показывает 40 мс | Nagle + Delayed ACK | TCP_NODELAY в клиенте |

### Паттерн batch-отправки с TCP_CORK

```c
// Паттерн: HTTP ответ через TCP_CORK
// 1. Начать cork
int cork = 1;
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));

// 2. Записать заголовки
write(fd, headers, header_len);

// 3. Записать тело
write(fd, body, body_len);

// 4. Отключить cork — все данные отправятся одним мгновением
cork = 0;
setsockopt(fd, IPPROTO_TCP, TCP_CORK, &cork, sizeof(cork));
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Nagle Algorithm](../../../Networking/Protocols/TCP/tcp_nagle_algorithm.md) — SSoT по алгоритму Nagle (489 строк)
- [TCP Delayed ACK](../../../Networking/Protocols/TCP/reliability_mechanisms/acknowledgments.md) — SSoT по ACK механизмам
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — полная диагностика соединений
- [Network Latency Optimization](network_latency_optimization.md) — снижение латентности

### RFC

- **RFC 896** — Nagle Algorithm (1984)
- **RFC 1122** §4.2.3.2 — Delayed ACK (1989)
- **RFC 7413** — TCP Fast Open

### Важные замечания

1. **TCP_NODELAY应当 включён по умолчанию** для всех latency-sensitive приложений (gRPC, Redis, WebSocket, SSH).
2. **TCP_CORK использовать только для batch-отправки** и всегда вызывать UNCORK после записи.
3. **TCP_QUICKACK требует re-arm** после каждого `recv()` — это не глобальная настройка.
4. **В HTTP/2 и gRPC** TCP_NODELAY критичен из-за multiplexing: задержка одного потока влияет на все.
5. **tcp_nopush в Nginx** — это TCP_CORK; он работает только с sendfile.
