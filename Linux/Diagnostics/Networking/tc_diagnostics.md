# Диагностика Traffic Control (tc)

## Определения

**Traffic Control (tc)** — подсистема ядра Linux для управления очередями сетевых пакетов (Queueing Disciplines, qdisc). Позволяет классифицировать, шейпить, полицать и эмулировать сетевые условия.

**qdisc (Queueing Discipline)** — алгоритм управления очередью пакетов на сетевом интерфейсе. Определяет, какой пакет будет отправлен следующим и сколько пакетов может буферизироваться.

**Bufferbloat** — явление, при котором чрезмерная буферизация в промежуточных устройствах (роутер, NIC) приводит к росту задержки (RTT) при высокой загрузке канала. Решается через AQM (fq_codel, CAKE).

** policer** — ограничитель скорости, отбрасывающий пакеты превышающие лимит (без буферизации). Отличается от shaper, который буферизирует и задерживает пакеты.

## Основные концепции

### Типы qdisc

| qdisc | Тип | Назначение | Ключевая особенность |
|:---|:---|:---|:---|
| **pfifo_fast** | немаркируемый | По умолчанию (legacy) | 3 полосы приоритетов, FIFO |
| **fq** | немаркируемый | Fair Queueing | Балансировка потоков,requires BBR pacing |
| **fq_codel** | AQM | Bufferbloat mitigation | CoDel + FQ, active queue management |
| **CAKE** | AQM | WAN shaping | fq_codel + шейпинг + классификация |
| **htb** | маркируемый | Иерархический шейпинг | Классы с приоритетами, burst |
| **tbf** | маркируемый | Одиночная полоса | Token Bucket Filter |
| **netem** | немаркируемый | Эмуляция проблем | Задержка, потери, джиттер |
| **noqueue** | — | Отсутствие очереди | loopback, wireguard |

### Местоположение qdisc в стеке

```
Приложение
    │
    ▼
TCP/UDP стек
    │
    ▼
  ┌─────────────────────────┐
  │  Root qdisc (egress)    │  ← tc qdisc add dev eth0 root ...
  │  ├── Class 1:1          │
  │  │   ├── Class 1:10     │  ← приоритеты
  │  │   └── Class 1:20     │
  │  └── Filter             │  ← классификация
  └─────────────────────────┘
    │
    ▼
  NIC (TX Queue)
    │
    ▼
  Сеть
```

**Важно:** `tc` по умолчанию управляет только **egress** (исходящий) трафиком. Для управления **ingress** используется `IFB` (Intermediate Functional Block) или `clsact`.

### Ключевые команды tc

```bash
# Просмотр всех qdisc
tc qdisc show dev eth0

# Просмотр классов
tc class show dev eth0

# Просмотр фильтров
tc filter show dev eth0

# Статистика
tc -s qdisc show dev eth0
tc -s class show dev eth0
```

## Практические сценарии

### 1. Диагностика текущей конфигурации tc

```bash
# Проверка, установлен ли fq_codel или что-то другое
tc qdisc show dev eth0
# → qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 quantum 1514 target 5.0ms
# →                                ^^^^^^^ ^^^^^^^^               ^^^^^^
#                           default limit    flows      quantum    target

# Интерпретация:
# fq_codel → Bufferbloat mitigated, хорошо
# pfifo_fast → По умолчанию, potentially Bufferbloat
# noqueue → Нет очереди (loopback, wireguard)
# tbf → Шейпинг
# netem → Эмуляция (убрать после тестов!)

# Статистика: потери в qdisc
tc -s qdisc show dev eth0 | grep -E "drop|backlog|overlimit"
# → qdisc fq_codel 0: root ... dropped 0 overlimits 0
```

### 2. Проверка наличия bufferbloat

**Симптом:** RTT растёт при увеличении пропускной способности.

```bash
# Шаг 1: Замер RTT без нагрузки
ping -c 20 8.8.8.8
# → rtt min/avg/max/mdev = 10/10.5/11/0.3 ms

# Шаг 2: Замер RTT во время iperf3
iperf3 -c <server> -t 30 &
ping -c 30 8.8.8.8
# → rtt min/avg/max/mdev = 10/45.2/98/30 ms  ← Bufferbloat!

# Шаг 3: Проверка qdisc
tc qdisc show dev eth0
# → qdisc pfifo_fast 0: root ...   ← Нет AQM!

# Шаг 4: Включение fq_codel
sudo tc qdisc replace dev eth0 root fq_codel

# Шаг 5: Повторный тест — RTT должен быть стабилен
```

### 3. Диагностика tc netem (эмуляция проблем)

```bash
# Проверка, не установлен ли netem (остался после тестов)
tc qdisc show dev eth0
# → qdisc netem 8001: root ... delay 100ms 50ms loss 5%

# Если netem активен — удалить:
sudo tc qdisc del dev eth0 root

# Добавление для тестов (ВРЕМЕННО!)
sudo tc qdisc add dev eth0 root netem delay 50ms 10ms loss 1%
# → Задержка 50ms ± 10ms, потери 1%

# Проверка
tc -s qdisc show dev eth0 | grep -A2 netem
# → loss 1.00%  ← подтверждение потерь
# → delay 50.0ms 10.0ms  ← подтверждение задержки

# Удаление после тестов (ОБЯЗАТЕЛЬНО)
sudo tc qdisc del dev eth0 root
```

### 4. Эмуляция проблем для тестирования resilience

```bash
# Задержка 200ms + джиттер 50ms + потери 2%
sudo tc qdisc add dev eth0 root netem delay 200ms 50ms loss 2%

# Потери 5% + дублирование 1%
sudo tc qdisc add dev eth0 root netem loss 5% duplicate 1%

# Ограничение скорости до 10 Mbit
sudo tc qdisc add dev eth0 root tbf rate 10mbit burst 32kbit latency 50ms

# Комбинирование: шейпинг + задержка
sudo tc qdisc add dev eth0 root handle 1: tbf rate 100mbit burst 32kbit latency 50ms
sudo tc qdisc add dev eth0 parent 1: handle 10: netem delay 30ms
```

### 5. Мониторинг tc в реальном времени

```bash
# Автоматическое обновление каждую секунду
watch -n 1 'tc -s qdisc show dev eth0 | grep -E "qdisc|drop|overlimit|backlog"'

# Скрипт для логирования
#!/bin/bash
LOG="/var/log/tc_stats.log"
while true; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') $(tc -s qdisc show dev eth0 | grep -oP 'dropped \K\d+')" >> "$LOG"
    sleep 60
done

# Проверка переполнения
tc -s qdisc show dev eth0 | awk '/dropped/ {if($2>0) print "ALERT: " $0}'
```

### 6. Диагностика ingress-трафика через IFB

```bash
# tc работает только с egress. Для ingress используем IFB:
sudo modprobe ifb
sudo ip link set ifb0 up

# Перенаправление ingress на IFB
sudo tc qdisc add dev eth0 handle ffff: ingress
sudo tc filter add dev eth0 parent ffff: protocol ip u32 match u32 0 0 action mirred egress redirect dev ifb0

# Теперь можно шейпить ingress через IFB
sudo tc qdisc add dev ifb0 root fq_codel

# Проверка
tc -s qdisc show dev eth0
tc -s qdisc show dev ifb0
```

## Дополнительная информация

### Типичные проблемы

| Симптом | Вероятная причина | Диагностика |
|:---|:---|:---|
| Высокий RTT при загрузке | Bufferbloat (pfifo_fast) | `tc qdisc show` → замена на fq_codel |
| Потери на egress | tc qdisc overlimit drops | `tc -s qdisc show` → поле `dropped` |
| Медленный egress | tc tbf/shaper ограничивает | `tc -s qdisc show` → rate |
| Нестабильный RTT | netem не удалён после теста | `tc qdisc show` → наличие netem |
| Входящий трафик не шейпится | tc управляет только egress | Использовать IFB/clsact |

### Связанные инструменты

- **[tc (Traffic Control)](../../Networking/Tools/iproute2/tc.md)** — полная справка по tc (SSoT).
- **[tc netem](../../Networking/Tools/iproute2/tc_netem.md)** — эмуляция сетевых проблем.
- **[QoS](../../../Networking/Concepts/qos.md)** — обзор QoS и очередей.
- **[Bufferbloat](../../../Networking/Concepts/real_time_traffic_quality.md)** — буферизация и качество трафика.
- **[iperf3](./iperf3.md)** — измерение пропускной способности (валидация tc).
- **[TCP congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md)** — взаимодействие с алгоритмами перегрузки.
