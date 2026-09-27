# Диагностика через nstat (SNMP-счётчики ядра)

## Определения

**nstat** — современная утилита (вместо `netstat -s`) для просмотра SNMP-подобных счётчиков сетевого стека Linux. Работает через `/proc/net/netstat` и `/proc/net/snmp`, предоставляя дельту (разницу) между выборками.

**SNMP-счётчики ядра** — внутренние счётчики сетевого стека Linux, отражающие количество определённых событий: ретрансмиссий, переполнений, ошибок контрольных сумм, таймаутов и т.д. Источник данных — ядро, обновляемое в реальном времени.

**Дельта (Delta)** — разница значений счётчика между двумя выборками. `nstat` по умолчанию показывает именно дельту, что удобно для отслеживания динамики.

## Основные концепции

### Ключевые счётчики для диагностики

| Счётчик | Описание | Когда смотреть |
|:---|:---|:---|
| **TcpRetransSegs** | Количество повторных передач TCP-сегментов | Потери в сети, конгестия |
| **TcpExtTCPTimeouts** | TCP-таймауты (重传 timeout) | Сильные потери, линка нестабильна |
| **TcpExtListenOverflows** | Переполнение Accept backlog | Приложение не успевает accept() |
| **TcpExtListenDrops** | Пакеты отброшены из-за переполнения backlog | Дополнение к ListenOverflows |
| **TcpExtTCPLossProbes** | RACK-пакеты-зонды (loss detection) | Потери, fast recovery |
| **TcpExtTCPSynRetrans** | SYN-ретрансмиссии | Хост недоступен, firewall |
| **TcpExtTCPAutoCork** | Автоматическая буферизация (Nagle) | Мелкие пакеты, задержки |
| **TcpExtTCPOrigDataSent** | Оригинальные данные (без ретрансмиссий) | Эффективность передачи |
| **IpExtInNoRoutes** | Пакеты без маршрута | Проблема маршрутизации |
| **IpExtInHdrErrors** | Ошибки заголовков IP | Фрагментация, неверный IP |
| **UdpInErrors** | Ошибки приёма UDP | Переполнение буфера |
| **UdpRcvbufErrors** | Ошибки буфера приёма UDP | Малый rmem |

### Базовые команды

```bash
# Дельта с момента последнего запуска (по умолчанию)
nstat

# Все счётчики (включая нулевые)
nstat -az

# Только счётчики с ненулевым значением
nstat -s

# В формате timestamp (для логирования)
nstat -y

# В формате epoch
nstat -p

# Интервал 1 секунда, 10 выборок
nstat -c 10 1

# Фильтр по имени
nstat -az | grep -i retrans
nstat -az | grep -i listen
```

## Практические сценарии

### 1. Быстрая оценка здоровья TCP-стека

```bash
#!/bin/bash
# tcp_health_check.sh — быстрый аудит TCP через nstat

echo "=== TCP Health Check ($(date)) ==="

# Сброс счётчиков и сбор дельты за 10 секунд
nstat -z > /dev/null 2>&1
sleep 10

echo -e "\n--- Retransmissions ---"
nstat -az | grep -E "RetransSegs|TCPSynRetrans|TCPLossProbes" | awk '{printf "%-35s %s\n", $1, $2}'

echo -e "\n--- Listen Queue ---"
nstat -az | grep -E "ListenOverflows|ListenDrops" | awk '{printf "%-35s %s\n", $1, $2}'

echo -e "\n--- Timeouts ---"
nstat -az | grep -E "TCPTimeouts|TCPAbortOn" | awk '{printf "%-35s %s\n", $1, $2}'

echo -e "\n--- Errors ---"
nstat -az | grep -iE "error|checksum" | awk '{printf "%-35s %s\n", $1, $2}'
```

### 2. Диагностика ретрансмиссий

```bash
# Шаг 1: Сбор дельты за 5 секунд
nstat -az TcpRetransSegs -y
# → 2025-09-16T10:23:45 TcpRetransSegs 150 0.0

# Шаг 2: Вычисление процента ретрансмиссий
OUT=$(nstat -az TcpOutSegs | awk 'NR==1{print $2}')
RETRANS=$(nstat -az TcpRetransSegs | awk 'NR==1{print $2}')
echo "Retransmission rate: $(echo "scale=2; $RETRANS * 100 / $OUT" | bc)%"
# → Retransmission rate: 2.35%  ← >1% — проблема

# Шаг 3: Мониторинг в реальном времени
while true; do
  nstat -az TcpRetransSegs | awk -v d="$(date '+%H:%M:%S')" '{print d, $1, $2}'
  sleep 5
done
```

### 3. Диагностика переполнения listen queue

```bash
# Мониторинг ListenOverflows
nstat -az ListenOverflows ListenDrops
# → TcpExtListenOverflows  150  0.0   ← 150 переполнений!
# → TcpExtListenDrops       42  0.0

# Сравнение с ss
ss -ltn sport = :80
# → LISTEN  0  511  0.0.0.0:80  0.0.0.0:*
# Recv-Q = 0 (текущее), Send-Q = 511 (максимум)

# Если ListenOverflows > 0:
# 1. Увеличить somaxconn: sysctl -w net.core.somaxconn=65535
# 2. Увеличить backlog в приложении
# 3. Оптимизировать приложение (ускорить accept)
```

### 4. Непрерывный мониторинг ключевых счётчиков

```bash
#!/bin/bash
# nstat_monitor.sh — непрерывный мониторинг TCP-счётчиков

COUNTERS="TcpRetransSegs TcpExtTCPTimeouts TcpExtListenOverflows TcpExtTCPSynRetrans TcpExtTCPAutoCork"
LOG="/var/log/nstat_monitor.csv"

echo "timestamp,$(echo $COUNTERS | tr ' ' ',')" > "$LOG"

while true; do
    nstat -z > /dev/null 2>&1
    sleep 60

    VALUES=""
    for c in $COUNTERS; do
        VAL=$(nstat -az "$c" 2>/dev/null | awk 'NR==1{print $2}')
        VALUES="${VALUES:+$VALUES,}${VAL:-0}"
    done

    echo "$(date '+%Y-%m-%d %H:%M:%S'),$VALUES" >> "$LOG"
done
```

### 5. Корреляция с ss

```bash
# Сбор метрик одновременно
nstat -z > /dev/null 2>&1
ss -ti dst 1.1.1.1 | head -5
sleep 5
nstat -az | grep -E "Retrans|Timeout|Loss"
ss -ti dst 1.1.1.1 | grep -E "retrans|cwnd|rtt"
```

## Дополнительная информация

### Интерпретация счётчиков

| Значение | Норма | Проблема |
|:---|:---|:---|
| TcpRetransSegs > 1% от TcpOutSegs | < 1% | Потери в сети |
| TcpExtListenOverflows > 0 | 0 | Бэкенд не справляется |
| TcpExtTCPTimeouts > 0 (per minute) | 0 | Линка нестабильна или хост мертв |
| TcpExtTCPSynRetrans > 0 | 0 | Хост недоступен / firewall |
| UdpRcvbufErrors > 0 | 0 | Малый rmem, DNS/NTP нагрузка |

### Связанные инструменты

- **[ss](./ss.md)** — статистика сокетов (пара к nstat).
- **[TCP diagnostics](../../../Networking/Protocols/TCP/reliability_mechanisms/diagnostics.md)** — глубокая диагностика TCP.
- **[tcpdump](./tcpdump.md)** — захват пакетов для визуализации.
- **[TCP congestion](../../../Networking/Protocols/TCP/congestion/tcp_congestion_diagnostics.md)** — диагностика перегрузки.
- **[Prometheus TCP metrics](../../Networking/Concepts/tcp_tuning/tcp_metrics_prometheus.md)** — экспорт счётчиков в Prometheus.
