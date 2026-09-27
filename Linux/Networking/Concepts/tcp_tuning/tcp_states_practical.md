# TCP Connection States — Практическое руководство

## Определения

**TCP Connection State** — текущее состояние TCP-соединения в статусной машине (RFC 9293). Каждое соединение проходит через определённые состояния: ESTABLISHED, FIN-WAIT-1, FIN-WAIT-2, TIME_WAIT, CLOSE-WAIT, LAST-ACK, CLOSING, CLOSED.

**Orphan Socket (Орфанный сокет)** — сокет в ядре, не имеющий файлового дескриптора в пользовательском пространстве. Возникает после `close()` в приложении, если соединение ещё не полностью закрыто (например, в состоянии FIN-WAIT-2 или LAST-ACK).

**tcp_orphan_retries** — sysctl-параметр, определяющий количество попыток отправить FIN перед принудительным закрытием орфанского соединения. По умолчанию `0` (= 8 RTO).

**tcp_max_orphans** — максимальное количество орфанских соединений в ядре. При превышении новые орфаны закрываются принудительно с RST.

**tcp_fin_timeout** — таймаут для соединений в состоянии FIN-WAIT-2 (по умолчанию 60 сек). Не влияет на TIME_WAIT.

---

## Теоретический блок

### Статусная машина TCP

```
                              ┌─────────┐
                              │ CLOSED  │
                              └────┬────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │ listen()     │ connect()     │
                    ▼              ▼               │
              ┌─────────┐  ┌──────────┐            │
              │ LISTEN  │  │ SYN-SENT │            │
              └────┬────┘  └────┬─────┘            │
                   │            │                  │
         SYN_rcvd  │            │ SYN-ACK          │
                   ▼            ▼                  │
              ┌────────────────────┐               │
              │   SYN-RECEIVED     │               │
              └────────┬───────────┘               │
                       │ ACK                       │
                       ▼                           │
              ┌────────────────────┐               │
              │    ESTABLISHED     │◄──────────────│
              └────────┬───────────┘               │
                       │                           │
          app close()  │  app close()              │
          ┌────────────┴──────────────┐            │
          │                           │            │
          ▼                           ▼            │
   ┌────────────┐            ┌──────────────┐      │
   │ FIN-WAIT-1 │            │  CLOSE-WAIT  │      │
   └─────┬──────┘            └──────┬───────┘      │
         │                          │ app close()  │
    ACK  │                     FIN  │              │
         ▼                          ▼              │
   ┌────────────┐            ┌──────────────┐      │
   │ FIN-WAIT-2 │            │   LAST-ACK   │      │
   └─────┬──────┘            └──────┬───────┘      │
         │                          │ ACK          │
    FIN  │                          ▼              │
         ▼                    ┌──────────┐         │
   ┌──────────┐               │ CLOSED   │         │
   │TIME_WAIT │               └──────────┘         │
   └─────┬────┘                                    │
         │ 2×MSL (60 сек)                          │
         ▼                                         │
   ┌──────────┐                                    │
   │ CLOSED   │                                    │
   └──────────┘
```

### Что означает каждое состояние

| Состояние | Описание | Кто видит | Критичность |
|---|---|---|---|
| **ESTABLISHED** | Активное соединение | Обе стороны | Норма |
| **SYN-RECEIVED** | Ожидание ACK после SYN-ACK | Сервер | Норма (много = SYN flood) |
| **FIN-WAIT-1** | Отправлен FIN, ожидаем ACK | Инициатор закрытия | Норма (кратковременно) |
| **FIN-WAIT-2** | Получен ACK на FIN, ожидаем FIN от другой стороны | Инициатор закрытия | Норма (долго = проблема) |
| **CLOSE-WAIT** | Получен FIN, приложение ещё не закрыло | Получатель | Проблема (утечка FD) |
| **LAST-ACK** | Отправлен FIN, ожидаем последний ACK | Сервер | Норма (кратковременно) |
| **TIME_WAIT** | Ожидание 2×MSL после последнего ACK | Инициатор закрытия | Норма (60 сек) |
| **CLOSING** | Одновременное закрытие | Обе стороны | Редкость |

### CLOSE-WAIT: проблема утечки

```
Приложение                Ядро                Удалённый хост
    │                       │                       │
    │                       │      FIN              │
    │                       │ ◄──────────────────────│
    │                       │      ACK              │
    │                       │ ──────────────────────►│
    │                       │                       │
    │  (приложение не        │  Состояние:           │
    │   вызывает close())   │  CLOSE-WAIT           │
    │                       │                       │
    │  ... FD утекает ...   │                       │
    │  ... растёт число     │                       │
    │  соединений ...       │                       │
```

**Причины CLOSE-WAIT:**
- Баг в приложении: не закрывает сокет после обработки
- Connection pool не проверяет соединения
- Блокировка в приложении не даёт вызвать `close()`

**Решение CLOSE-WAIT:**
```bash
# Найти соединения в CLOSE-WAIT
ss -tan state close-wait
lsof -i TCP -sTCP:CLOSE-WAIT

# Если много CLOSE-WAIT → проблема в приложении
# Единственное решение: перезапуск приложения или исправление кода
# sysctl НЕ может закрыть CLOSE-WAIT
```

### FIN-WAIT-2: долгое ожидание

```bash
# Найти долгие FIN-WAIT-2
ss -tan state fin-wait-2 | awk '{print $4, $5, $6}'

# Уменьшить таймаут
sysctl -w net.ipv4.tcp_fin_timeout=15
```

### Orphan Sockets: проблема и решение

```bash
# Количество орфанов
ss -s | grep orphaned
# → TCP:   1500 (estab 1200, closed 200, orphaned 80, timewait 100)

# Если orphaned растёт → увеличить лимит
sysctl -w net.ipv4.tcp_max_orphans=32768

# Уменьшить количество попыток
sysctl -w net.ipv4.tcp_orphan_retries=3
```

### TIME_WAIT vs orphan sockets

| Параметр | TIME_WAIT | Orphan Socket |
|---|---|---|
| **Когда** | После корректного закрытия | После `close()` до полного закрытия |
| **Состояние** | TIME_WAIT | FIN-WAIT-2, CLOSING, LAST-ACK |
| **Длительность** | 60 сек (2×MSL) | Зависит от tcp_orphan_retries |
| **Решение** | tcp_tw_reuse, port range | tcp_max_orphans, tcp_orphan_retries |
| **sysctl** | tcp_tw_reuse, tcp_fin_timeout | tcp_max_orphans, tcp_orphan_retries |

---

## Практический блок

### Diagnostics

```bash
# Все соединения по состояниям
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn
# → 5000 ESTAB
# → 1200 TIME-WAIT
# → 50 CLOSE-WAIT
# → 10 FIN-WAIT-2
# → 5 SYN-RECV

# CLOSE-WAIT: найти приложение
ss -tanp state close-wait | head -20
# → State  Recv-Q Send-Q  Local Address:Port  Peer Address:Port  Process
# → CLOSE-WAIT 0 0 10.0.0.1:8080 10.0.0.2:45678 users:(("nginx",pid=1234,fd=5))

# FIN-WAIT-2: найти долгие
ss -tanp state fin-wait-2 | awk '$4 != "0" {print}'
# → Если Send-Q != 0, данные ещё передаются

# TIME_WAIT: группировка по remote IP
ss -tan state time-wait | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn | head

# Orphaned через ss -s
ss -s
# → TCP:   5000 (estab 4500, closed 300, orphaned 120, timewait 80)

# Мониторинг через /proc
cat /proc/net/sockstat
# → TCP: inuse 5000 orphan 120 tw 80 alloc 5200 mem 100
```

### Production sysctl-конфигурация

```bash
# /etc/sysctl.d/99-tcp-states.conf

# CLOSE-Wait: sysctl не может закрыть, только профилактика
# (убедитесь что приложение корректно закрывает соединения)

# FIN-WAIT-2 таймаут
net.ipv4.tcp_fin_timeout = 15

# Orphan sockets
net.ipv4.tcp_max_orphans = 32768
net.ipv4.tcp_orphan_retries = 3

# TIME_WAIT (для полноты)
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_timestamps = 1
```

### Prometheus alerting

```yaml
groups:
  - name: tcp_state_alerts
    rules:
      - alert: HighCloseWaitConnections
        expr: node_netstat_Tcp_CurrEstab - (node_netstat_Tcp_CurrEstab offset 1h) > 100
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Рост соединений — возможна утечка CLOSE-WAIT"

      - alert: HighOrphanedSockets
        expr: node_sockstat_TCP_orphan > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Много orphaned sockets: {{ $value }}"

      - alert: HighTimeWaitConnections
        expr: node_sockstat_TCP_tw > 50000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Много TIME_WAIT: {{ $value }} — проверьте ephemeral ports"
```

### Troubleshooting decision tree

```
Много соединений в аномальном состоянии?
│
├─ CLOSE-WAIT > 100?
│   ├─ lsof -i TCP -sTCP:CLOSE-WAIT | wc -l → Растёт?
│   │   ├─ Да → Баг в приложении (не вызывает close())
│   │   └─ Нет → Стабильный фон,.acceptable
│   └─ Решение: перезапуск приложения, исправление кода
│
├─ FIN-WAIT-2 > 50?
│   ├─ tcp_fin_timeout = 60? → Уменьшить до 15
│   ├─ Приложение закрывает соединения? → Проверить логику закрытия
│   └─ Send-Q != 0? → Данные ещё передаются, подождите
│
├─ TIME-WAIT > 50000?
│   ├─ tcp_tw_reuse = 0? → Включить tcp_tw_reuse=1
│   ├─ ip_local_port_range = 32768-60999? → Расширить до 1024-65535
│   └─ tcp_timestamps = 0? → Включить (обязательно для tw_reuse)
│
├─ SYN-RECV > 100?
│   ├─ ListenOverflows растёт? → SYN flood
│   │   ├─ Включить syncookies: net.ipv4.tcp_syncookies=1
│   │   └─ Увеличить tcp_max_syn_backlog
│   └─ Нет overflow? → Нормальный traffic spike
│
└─ Orphaned > 1000?
    ├─ tcp_max_orphans = 16384? → Увеличить до 32768-65535
    ├─ tcp_orphan_retries = 0? → Установить 3
    └─ Приложение корректно закрывает? → Проверить close()
```

---

## Дополнительная информация

### Связанные файлы

- [TCP Connection States](../../../Networking/Protocols/TCP/connection/tcp_connection_states.md) — SSoT по статусной машине TCP
- [TCP Connection Termination](../../../Networking/Protocols/TCP/connection/tcp_connection_termination.md) — SSoT по закрытию соединений
- [TCP TIME_WAIT](tcp_time_wait_management.md) — управление TIME_WAIT
- [TCP Connection Queues](tcp_connection_queues.md) — backlog и очереди

### RFC

- **RFC 9293** — TCP specification (2022)
- **RFC 793** — TCP specification (1981, оригинальная)

### Важные замечания

1. **CLOSE-Wait НЕ решается sysctl** — только перезапуск приложения или исправление кода.
2. **TIME_WAIT — это нормально** — не пытайтесь его полностью устранить.
3. **Orphan sockets ограничены** `tcp_max_orphans` — при превышении RST.
4. **FIN-WAIT-2 таймаут** управляется `tcp_fin_timeout`, а не `tcp_keepalive_time`.
5. **SYN-RECV > 500** на слушающем порту — признак SYN flood.
