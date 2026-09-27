# Busy Polling — Low-Latency Networking

## Определения

**Busy Polling** — механизм активного опроса (polling) сетевой карты ядром Linux, заменяющий прерывания (IRQ) на опрос. Позволяет обрабатывать пакеты немедленно после поступления в NIC, минимизируя задержку между получением пакета и обработкой.

**SO_BUSY_POLL** — per-socket опция, включающая busy polling для конкретного соединения. Устанавливает таймаут опроса NIC в микросекундах.

**net.core.busy_poll** — sysctl-параметр, устанавливающий таймаут busy polling (в микросекундах) для всех сокетов. По умолчанию `0` (отключён).

**net.core.busy_read** — sysctl-параметр, устанавливающий таймаут busy polling для операций чтения из сокета.

**NAPI (New API)** — механизм ядра Linux для обработки входящих пакетов методом опроса (polling) при высокой нагрузке. Busy polling расширяет NAPI на пользовательское пространство.

---

## Теоретический блок

### Стандартная модель vs Busy Polling

```
Стандартная модель (IRQ):
┌──────┐    ┌──────┐    ┌──────────┐    ┌──────────┐
│ NIC  │───►│ IRQ  │───►│ SoftIRQ  │───►│ Прилож.  │
│      │    │      │    │ NET_RX   │    │ read()   │
└──────┘    └──────┘    └──────────┘    └──────────┘
             5-20 мкс    10-50 мкс       Задержка ~50-200 мкс

Busy Polling:
┌──────┐    ┌──────────────────────────┐    ┌──────────┐
│ NIC  │───►│ Приложение (epoll_wait)  │───►│ read()   │
│      │    │ → опрос NIC напрямую    │    │          │
└──────┘    └──────────────────────────┘    └──────────┘
             Задержка ~5-20 мкс
```

### Ключевые преимущества

| Фактор | IRQ модель | Busy Polling | Эффект |
|---|---|---|---|
| **Задержка (latency)** | 50-200 мкс | 5-20 мкс | 10× снижение |
| **Предсказуемость** | Variable (jitter) | Deterministic | Стабильный p99 |
| **Context switches** | IRQ → SoftIRQ → app | Нет | Снижение overhead |
| **CPU usage** | Spread across cores | Dedicated core | Выделение ресурсов |

### Когда использовать

| Сценарий | Busy Polling | Обоснование |
|---|---|---|
| **Trading / HFT** | Вкл (busy_poll=50) | Субмикросекундная latency |
| **Gaming servers** | Вкл (busy_poll=50) | Низкая p99 latency |
| **VoIP / RTC** | Вкл (busy_poll=50) | Стабильная latency |
| **Database (internal)** | Опционально | Снижение tail latency |
| **Web servers (public)** | Выкл | CPU overhead не оправдан |
| **Batch processing** | Выкл | Не критична latency |
| **Container/K8s** | Выкл (обычно) | Host-level tuning |

### sysctl-параметры

| Параметр | Значение | Описание |
|---|---|---|
| `net.core.busy_poll` | `0` | Отключён (по умолчанию) |
| | `50` | 50 мкс (рекомендуется для low-latency) |
| | `100` | 100 мкс (более агрессивный) |
| `net.core.busy_read` | `0` | Отключён (по умолчанию) |
| | `50` | 50 мкс для read операций |

### Взаимодействие с epoll

```c
// Busy polling работает через epoll_wait
int epfd = epoll_create1(0);
struct epoll_event ev;
ev.events = EPOLLIN;
ev.data.fd = fd;
epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &ev);

// busy_poll_timeout определяет сколько epoll_wait будет опрашивать NIC
struct epoll_event events[10];
int n = epoll_wait(epfd, events, 10, busy_poll_timeout);
// Если busy_poll > 0, epoll_wait будет активно опрашивать NIC
```

---

## Практический блок

### Проверка текущего состояния

```bash
sysctl net.core.busy_poll net.core.busy_read
# → net.core.busy_poll = 0
# → net.core.busy_read = 0

# Проверка поддержки NIC
ethtool -i eth0 | grep driver
# → driver: ixgbe (поддерживает busy polling)
```

### Настройка

```bash
# /etc/sysctl.d/99-busy-polling.conf
net.core.busy_poll = 50
net.core.busy_read = 50

# Применение
sudo sysctl --system
```

### Per-socket настройка

```c
// C: busy polling для конкретного сокета
int busy_poll = 50;  // 50 мкс
setsockopt(fd, SOL_SOCKET, SO_BUSY_POLL, &busy_poll, sizeof(busy_poll));
```

```python
# Python
import socket
SO_BUSY_POLL = 47  # Константа для busy polling
sock.setsockopt(socket.SOL_SOCKET, SO_BUSY_POLL, 50)
```

### Diagnostics

```bash
# Проверка busy poll через ss
ss -tin state established | grep busy
# → busy:50 (если busy poll включён)

# Мониторинг latency
ping -i 0.001 10.0.0.1 | awk '/time/ {
    if ($NF+0 > 0.1) print "HIGH LATENCY:", $0
}'

# Бенчмарк latency до/после
# До:
hping3 -S -p 80 -c 1000 10.0.0.1 | grep "rtt"

# После (busy_poll=50):
hping3 -S -p 80 -c 1000 10.0.0.1 | grep "rtt"
```

### Требования к NIC

Busy polling требует поддержки со стороны NIC driver. Поддерживающиеся драйверы:

| Driver | Поддержка | Примечание |
|---|---|---|
| `ixgbe` | Да | Intel 10GbE |
| `i40e` | Да | Intel 40GbE |
| `ice` | Да | Intel 100GbE |
| `mlx5` | Да | Mellanox 25/100GbE |
| `bnxt` | Да | Broadcom 25/50/100GbE |
| `e1000e` | Ограниченно | Intel 1GbE |
| `virtio_net` | Нет | Виртуальные NIC |

---

## Дополнительная информация

### Связанные файлы

- [NAPI Optimization](napi_optimization.md) — SSoT по NAPI
- [Network Latency Optimization](network_latency_optimization.md) — снижение латентности
- [TCP Socket Diagnostics](tcp_socket_diagnostics.md) — диагностика соединений

### Важные замечания

1. **Busy Polling требует выделенного CPU** — используйтеcpuset или IRQ affinity для изоляции.
2. **busy_poll=50** — рекомендуемое значение для production low-latency.
3. **Для containerized workloads** busy polling настраивается на уровне host (node tuning).
4. **CPU overhead** — busy polling занимает одно ядро CPU на 100%. Используйте только для latency-sensitive workloads.
5. **NIC应当 поддерживать** busy polling. Проверяйте через `ethtool -i`.
