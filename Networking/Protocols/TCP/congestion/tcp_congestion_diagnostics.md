# Диагностика управления перегрузкой TCP

## Определения

**Диагностика congestion control** — набор методов и инструментов для мониторинга состояния TCP-соединений, выявления проблем с перегрузкой сети и выбора оптимальных алгоритмов управления окном перегрузки (`cwnd`).

**Ключевые метрики:**
- `cwnd` — окно перегрузки (congestion window)
- `rtt` — время круговой задержки (среднее/отклонение)
- `rto` — тайм-аут повторной передачи (retransmission timeout)
- Активный алгоритм congestion control (`cubic`, `bbr`, `dctcp`, etc.)

---

## Основные концепции

### Просмотр состояния congestion control

```bash
# Показать активный алгоритм
sysctl net.ipv4.tcp_congestion_control

# Показать доступные алгоритмы
sysctl net.ipv4.tcp_available_congestion_control

# Детальная информация о сокетах
ss -tmo

# Пример вывода:
# cubic wscale:7,7 rto:204 rtt:0.5/0.25 cwnd:10
```

**Расшифровка полей `ss -tmo`:**
- `cubic` — активный алгоритм
- `cwnd:10` — текущее окно перегрузки (10 MSS)
- `rtt:0.5/0.25` — RTT: 0.5 мс (среднее), 0.25 мс (отклонение)
- `rto:204` — тайм-аут повторной передачи (204 мс)

### Выбор алгоритма congestion control

| Сценарий | Рекомендуемый алгоритм | Обоснование |
| :--- | :--- | :--- |
| **Веб-сервер (общий)** | `bbr` | Низкая задержка, хорошая пропускная способность |
| **ЦОД (data center)** | `dctcp` | Оптимизирован для низких задержек ЦОД |
| **Мобильные сети** | `bbr` или `westwood` | Устойчивость к потерям |
| **Высокоскоростные каналы (>1 Гбит/с)** | `bbr` | Лучшая утилизация BDP |
| **Совместимость (старые ядра)** | `cubic` | По умолчанию, стабилен |

**Настройка алгоритма:**

```bash
# Включение BBR
echo "net.core.default_qdisc = fq" >> /etc/sysctl.conf
echo "net.ipv4.tcp_congestion_control = bbr" >> /etc/sysctl.conf
sysctl -p
```

### Packet Pacing

**Проблема:** отправка всех 10 пакетов `initcwnd` одной очередью вызывает краткосрочную перегрузку.

**Решение:** равномерная отправка пакетов во времени (pacing).

**Проверка:**

```bash
ethtool -k eth0 | grep pacing
```

BBR автоматически включает pacing на ядрах 4.x+. Для других алгоритмов pacing можно настроить через `tc` или `fq` qdisc.

---

## Практические сценарии

### Сценарий 1: Низкая пропускная способность

**Симптом:** `cwnd` растёт медленно, throughput ниже ожидаемого.

**Диагностика:**

```bash
# Проверить текущий cwnd и RTT
ss -tmo | grep -E 'cwnd|rtt'

# Проверить активный алгоритм
sysctl net.ipv4.tcp_congestion_control
```

**Решение:**
- Увеличить `initcwnd` (см. [tcp_initcwnd_and_optimization.md](./tcp_initcwnd_and_optimization.md))
- Переключиться на `bbr` для лучшей утилизации канала
- Проверить сеть на наличие потерь (`ping`, `mtr`, `tcpdump`)

### Сценарий 2: Bufferbloat (высокая задержка при загрузке канала)

**Симптом:** при полной загрузке канала RTT возрастает в разы, интерактивные приложения «тормозят».

**Диагностика:**

```bash
# Сравнить RTT в спокойном состоянии и под нагрузкой
ss -tmo | grep rtt
```

**Решение:**
- Переключиться с `cubic` на `bbr` (устойчив к bufferbloat)
- Настроить `fq_codel` на интерфейсе:

```bash
tc qdisc add dev eth0 root fq_codel
```

### Сценарий 3: Частые потери пакетов

**Симптом:** `cwnd` постоянно сбрасывается, пила в throughput.

**Диагностика:**

```bash
# Проверить ретрансмиссии
ss -ti | grep retrans

# Захватить трафик для анализа
tcpdump -i eth0 -w /tmp/tcp.pcap host <remote_ip>
```

**Решение:**
- Выявить источник потерь (`mtr`, `ping` по промежуточным узлам)
- Рассмотреть включение ECN (Explicit Congestion Notification)
- Для мобильных сетей — использовать `westwood` или `bbr`

### Сценарий 4: «Пилообразный» график cwnd

**Симптом:** график `cwnd` имеет форму пилы — рост и резкий спад.

**Диагностика:**

```bash
# Мониторинг cwnd в реальном времени
watch -n1 'ss -tmo | grep cwnd'
```

**Интерпретация:** такое поведение **нормально** для AIMD-алгоритмов (`cubic`, `reno`). Пила — признак корректной работы congestion control. Для сглаживания рассмотреть `bbr` (delay-based алгоритм).

### Сценарий 5: Проверка работы pacing

**Симптом:** всплески трафика (bursts) при старте соединения, кратковременные потери пакетов.

**Диагностика:**

```bash
# Проверить поддержку pacing на интерфейсе
ethtool -k eth0 | grep -E 'tx-scatter-gather|tx-tcp-segmentation'

# Проверить, использует ли BBR pacing
ss -ti | grep bbr
```

**Решение:** убедиться, что `net.core.default_qdisc = fq` установлен для BBR.

---

## Дополнительная информация

### Связанные темы

**Обзор и базовые алгоритмы** ([tcp_congestion_control_overview.md](./tcp_congestion_control_overview.md)) — Slow Start, AIMD, Fast Recovery. **Алгоритмы congestion control** ([tcp_congestion_algorithms.md](./tcp_congestion_algorithms.md)) — CUBIC, BBR, Reno. **Оптимизация initcwnd** ([tcp_initcwnd_and_optimization.md](./tcp_initcwnd_and_optimization.md)) — правило 14 КБ. **Оптимизация TCP** ([tcp_tuning_overview.md](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)) — практическая настройка. **Wireshark: диагностика производительности** ([tcp_performance_diagnostics.md](../../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)) — анализ проблем через Wireshark.
