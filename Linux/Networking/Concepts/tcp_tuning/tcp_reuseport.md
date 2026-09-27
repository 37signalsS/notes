# SO_REUSEPORT — Deep Dive

## Определения

**SO_REUSEPORT** — опция сокета (Linux 3.9+), позволяющая нескольким процессам/потокам слушать один и тот же IP:port с балансировкой нагрузки через хеш в ядре. Ядро распределяет входящие соединения по сокетам на основе 4-tuple хеша (src_ip, src_port, dst_ip, dst_port).

**SO_REUSEADDR** — опция сокета, позволяющая привязаться к адресу, который находится в TIME_WAIT или используется другим процессом. НЕ обеспечивает балансировку.

**4-tuple Hash** — алгоритм распределения: хеш от (source IP, source port, destination IP, destination port). Один и тот же клиент всегда попадает на тот же worker (при неизменном source port).

---

## Теоретический блок

### SO_REUSEADDR vs SO_REUSEPORT

| Параметр | SO_REUSEADDR | SO_REUSEPORT |
|---|---|---|
| **Назначение** | Перезапуск сервера,绑定 к TIME_WAIT | Балансировка между процессами |
| **Балансировка** | Нет (ядро выбирает один сокет) | Да (4-tuple хеш) |
| **Безопасность** | Рискованно (маскировка) | Безопасно (разделение порта) |
| **Ядро** | Все Linux | Linux 3.9+ |
| **Сценарий** | Restart after crash | Multi-worker servers |

### SO_REUSEPORT: архитектура

```
Входящее соединение (SYN)
        │
        ▼
┌───────────────────────────────────────────┐
│ Ядро Linux: 4-tuple hash                  │
│ hash(src_ip, src_port, dst_ip, dst_port) │
│                                           │
│  hash % num_sockets = socket_index        │
└───────────────┬───────────────────────────┘
                │
        ┌───────┼───────┐
        ▼       ▼       ▼
   ┌────────┐ ┌────────┐ ┌────────┐
   │Worker 0│ │Worker 1│ │Worker 2│
   │(socket)│ │(socket)│ │(socket)│
   └────────┘ └────────┘ └────────┘
```

### Ограничения 4-tuple hash

| Фактор | Влияние | Решение |
|---|---|---|
| **NAT** | За NAT все клиенты имеют один src_ip | балансировка по src_port (обычно достаточно) |
| **Proxy** | Все запросы от IP прокси | балансировка по src_port прокси |
| **Connection migration** | Клиент может перейти на другой worker | Приложение должно обрабатывать |

### SO_REUSEPORT и epoll

Каждый worker имеет свой epoll instance. Ядро направляет SYN на конкретный сокет, и `accept()` вызывается только на этом worker'е. Это исключает thundering herd:

```
Без SO_REUSEPORT:
┌──────────────────────────────────────────┐
│ Worker 0: epoll_wait( Accept )           │ ← все worker'а пробуждаются
│ Worker 1: epoll_wait( Accept )           │
│ Worker 2: epoll_wait( Accept )           │
└──────────────────────────────────────────┘

С SO_REUSEPORT:
┌──────────────────────────────────────────┐
│ Worker 0: epoll_wait( Accept )           │ ← только целевой worker
│ Worker 1: sleep()                        │
│ Worker 2: sleep()                        │
└──────────────────────────────────────────┘
```

---

## Практический блок

### Включение SO_REUSEPORT

```c
// C: server
int enable = 1;
int listen_fd = socket(AF_INET, SOCK_STREAM, 0);
setsockopt(listen_fd, SOL_SOCKET, SO_REUSEPORT, &enable, sizeof(enable));
setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &enable, sizeof(enable));
bind(listen_fd, ...);
listen(listen_fd, 128);

// Каждый worker (fork или thread) создаёт свой listen_fd
// с тем же SO_REUSEPORT
```

```python
# Python
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 8080))
sock.listen(128)
```

```go
// Go
ln, _ := net.Listen("tcp", ":8080")
ln.(*net.TCPListener).Setsockopt(...)
// Go автоматически использует SO_REUSEPORT если доступен
```

### Nginx

```nginx
# Включение reuseport для worker balancing
server {
    listen 80 reuseport;
    listen 443 ssl reuseport;

    # HTTP/3 (QUIC) требует reuseport
    listen 443 quic reuseport;
}
```

### HAProxy

```haproxy
# HAProxy автоматически использует SO_REUSEPORT
# при multi-process режиме
global
    nbthread 4

frontend http
    bind *:80
    # SO_REUSEPORT включён автоматически при nbproc > 1
```

### Diagnostics

```bash
# Проверить reuseport на слушающем сокете
ss -ltnp | grep :80
# → LISTEN  0  128  0.0.0.0:80  0.0.0.0:*  users:(("nginx",pid=1234,fd=6),("nginx",pid=1233,fd=6))

# Показать все сокеты на одном порту
ss -ltnp | grep :80 | wc -l
# → 4 (если 4 worker'а с reuseport)

# Мониторинг балансировки через /proc
cat /proc/net/softnet_stat
# → Показывает распределение по CPU

# Проверка через nstat
nstat -az | grep -i reuse
# → TcpExtTCPReqQFullDrop → если reuseport не настроен
```

### Проблемы и решения

| Проблема | Симптомы | Причина | Решение |
|---|---|---|---|
| **Разная нагрузка на workers** | Один worker грузится больше | 4-tuple hash даёт неравномерное распределение | Использовать `SO_ATTACH_REUSEPORT_CBPF` для рандомизации |
| **NAT imbalance** | Все соединения от одного IP | Клиенты за NAT | Приёмлемо (src_port всё ещё варьируется) |
| **Клиент переподключается** | Новое соединение на другом worker | Изменился src_port | Приложение должно быть stateless |
| **SO_REUSEPORT + BBR** | Нестабильный throughput | BBR требует per-connection state | Каждый worker настраивает BBR независимо |

---

## Дополнительная информация

### Связанные файлы

- [Socket API](../../../Networking/Concepts/socket_api.md) — SSoT по сокетам
- [Network Ports](../../../Networking/Concepts/network_ports.md) — порты и опции
- [TCP Production Tuning](../../../Networking/Protocols/TCP/production_tuning.md) — production настройка
- [TCP Connection Queues](tcp_connection_queues.md) — listen queue

### Важные замечания

1. **SO_REUSEPORT应当 включён** для всех multi-worker серверов (Nginx, HAProxy, Envoy).
2. **SO_REUSEPORT + epoll** исключает thundering herd.
3. **Для HTTP/3 (QUIC)** SO_REUSEPORT обязателен для балансировки UDP.
4. **4-tuple hash детерминирован** — один клиент всегда попадает на тот же worker (если src_port не изменился).
5. **SO_REUSEADDR ≠ SO_REUSEPORT** — не путайте назначения.
