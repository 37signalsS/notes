# Диагностика сокетов TCP

> **SSoT:** Полная документация по `ss` (флаги, фильтрация, примеры) — в [Linux/Diagnostics/Networking/ss.md](../../../Diagnostics/Networking/ss.md)

## Определения

**Диагностика TCP-сокетов** — совокупность методов и инструментов для анализа состояния TCP-соединений, выявления проблем производительности и ошибок сетевого стека Linux.

## Basic Concepts

### Основные инструменты диагностики

| Инструмент | Источник данных | Назначение |
| :--- | :--- | :--- |
| **`ss`** | `netlink` (ядро) | Состояния сокетов, TCP-метрики (RTT, cwnd, retrans) |
| **`nstat`** | `/proc/net/netstat` | Счётчики TCP-подсистемы (TFO, SYN cookies, overflow) |
| **`/proc/sys/net/ipv4/`** | sysctl-параметры | Текущие настройки TCP-стека |
| **`tcpdump`** | `libpcap` (packet capture) | Анализ трафика, handshake, ретрансмиссии |

### Ключевые состояния TCP для диагностики

- **ESTABLISHED** — активные соединения, основа анализа нагрузки
- **SYN-RECV** — полуоткрытые, рост может указывать на SYN-flood
- **CLOSE-WAIT** — приложение не закрыло сокет, утечка соединений
- **TIME-WAIT** — нормальное состояние после закрытия, избыток требует тюнинга
- **FIN-WAIT** — одна сторона закрыла, ожидание подтверждения

## Practical Scenarios

### Общая картина

```bash
# Сводная статистика: сколько сокетов в каждом состоянии
ss -s

# Все TCP-соединения с группировкой по состоянию
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn

# Соединения с деталями (RTT, cwnd, retrans)
ss -ti state established
```

### Диагностика TIME-WAIT

```bash
# Количество сокетов в TIME-WAIT
ss -tan state time-wait | wc -l

# Детали TIME-WAIT сессий (время ожидания)
ss -tai state time-wait
```

> **Решение при избытке:** [Управление TIME_WAIT](./tcp_time_wait_management.md) — `tcp_tw_reuse`, `tcp_fin_timeout`.

### Диагностика congestion control

```bash
# Доступные алгоритмы
cat /proc/sys/net/ipv4/tcp_available_congestion_control

# Текущий алгоритм
sysctl net.ipv4.tcp_congestion_control

# Проверка BBR в действии
ss -ti | grep -o 'cong:[[:space:]]*[a-z0-9]*'
```

> **Подробнее:** [Алгоритмы управления перегрузкой](./tcp_congestion_algorithms.md)

### Диагностика буферов и window

```bash
# Поиск сокетов с нулевым окном (Zero Window)
ss -tmo | grep 'window:0'

# Мониторинг в реальном времени
watch -n1 'ss -tmo | grep -c "window:0"'

# Проверка window scaling на соединениях
ss -tno | grep wscale
```

> **Подробнее:** [Оптимизация буферов TCP](./tcp_buffer_tuning.md)

### Диагностика TCP Fast Open

```bash
# Проверка поддержки TFO в ядре
cat /proc/sys/net/ipv4/tcp_fastopen

# Статистика TFO (ядро 4.10+)
nstat -az | grep -i tfo
# TcpExtTCPFastOpenActive     — успешные TFO-соединения (клиент)
# TcpExtTCPFastOpenPassive    — успешные TFO-соединения (сервер)
# TcpExtTCPFastOpenBlackhole  — отброены middlebox
```

> **Подробнее:** [TCP Fast Open](./tcp_fast_open.md)

### Диагностика очередей соединений (backlog)

```bash
# Количество SYN_RECV (полуоткрытые)
ss -tan state syn-recv | wc -l

# Счётчики переполнения backlog
nstat -az | grep -i -E 'listenoverflow|reqqfulldrop'
# TcpExtTCPListenOverflow  — переполнение Accept backlog
# TcpExtTCPReqQFullDrop    — отброшены из-за переполнения SYN backlog
```

> **Подробнее:** [Управление очередями соединений](./tcp_connection_queues.md)

### Сводная диагностика проблем

| Симптом | Команда | Возможная причина | Ссылка |
| :--- | :--- | :--- | :--- |
| Много TIME-WAIT | `ss -tan state time-wait \| wc -l` | Короткие соединения, нет reuse | [TIME_WAIT](./tcp_time_wait_management.md) |
| Zero Window | `ss -tmo \| grep 'window:0'` | Приложение не читает, малый буфер | [Буферы](./tcp_buffer_tuning.md) |
| Высокие retrans | `ss -ti \| grep 'retrans:[1-9]'` | Потери пакетов, перегрузка | [Congestion](./tcp_congestion_algorithms.md) |
| SYN_RECV растёт | `ss -tan state syn-recv \| wc -l` | SYN-flood, малый backlog | [Backlog](./tcp_connection_queues.md) |
| TFO Blackhole | `nstat -az \| grep Blackhole` | Файрвол отбрасывает SYN+data | [TFO](./tcp_fast_open.md) |
| Низкий cwnd | `ss -ti \| grep 'cwnd:[1-5]'` | TCP после потерь, медленный рост | [Congestion](./tcp_congestion_algorithms.md) |

### Мониторинг в реальном времени

```bash
# Все слушающие порты (обновление каждую секунду)
watch -n1 'ss -tlnp'

# Количество ESTABLISHED-соединений
watch -n1 'ss -tan state established | wc -l'

# Ретрансмиссии в реальном времени
watch -n1 'ss -ti state established | grep -o "retrans:[0-9/]*" | head -5'
```

## Additional Information

### Связанные темы

- **SSoT:** [Диагностика ss](../../../Diagnostics/Networking/ss.md) — полная документация по `ss` (флаги, фильтрация, примеры)
- **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
- **Дисциплины очередей:** [Дисциплины очередей TCP](./tcp_queueing_disciplines.md) — мониторинг qlen, bufferbloat
