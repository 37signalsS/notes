# Алгоритмы управления перегрузкой TCP в Linux

> **SSoT:** Полная документация по алгоритмам congestion control (CUBIC, BBR, Reno, формулы, фазы работы) — в [Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md)

## Определения

**Алгоритм управления перегрузкой (Congestion Control Algorithm)** — алгоритм, определяющий, как TCP-соединение реагирует на перегрузку сети, регулируя скорость передачи данных для предотвращения коллапса сети.

**cwnd (congestion window)** — окно перегрузки, параметр ядра Linux, ограничивающий объём данных в полёте на основе состояния сети.

## Basic Concepts

### Алгоритмы в ядре Linux

Ядро Linux включает несколько встроенных алгоритмов congestion control. Выбор зависит от характера нагрузки и сетевой среды.

| Алгоритм | Статус в Linux | Сценарий |
| :--- | :--- | :--- |
| **CUBIC** | По умолчанию (большинство дистрибутивов) | Универсальный, высокие BDP-каналы |
| **BBR** | Доступен (ядро 4.9+) | Веб-серверы, мобильные сети, LDN |
| **Reno** | Устарел | Исторический, не рекомендуется |
| **DCTCP** | Доступен (ядро 3.18+) | ЦОД с поддержкой ECN |

> **Ключевое отличие BBR от CUBIC:** BBR не ждёт потерь пакетов — он постоянно измеряет пропускную способность и RTT, поддерживая передачу на уровне BDP, что минимизирует bufferbloat.

### Связь с qdisc

Алгоритм congestion control взаимодействует с дисциплиной очереди (qdisc). Для BBR рекомендуется `fq`, для CUBIC — `fq_codel`.

## Practical Scenarios

### Просмотр доступных алгоритмов

```bash
cat /proc/sys/net/ipv4/tcp_available_congestion_control
# Пример вывода: cubic reno bbr
```

### Проверка текущего алгоритма

```bash
sysctl net.ipv4.tcp_congestion_control
# или для всех соединений
ss -ti | grep -o 'cong:[[:space:]]*[a-z0-9]*'
```

### Включение BBR

**Требования:** ядро Linux 4.9+

```ini
# /etc/sysctl.d/99-network.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

```bash
sudo sysctl -p /etc/sysctl.d/99-network.conf
```

**Проверка:**

```bash
ss -ti | grep bbr
# или
sysctl net.ipv4.tcp_congestion_control
```

> **Примечание:** BBR автоматически использует pacing (ядро 4.x+). Для BBRv2 требуется ядро 5.18+.

### BBRv3 (experimental)

> **Внимание:** BBRv3 **НЕ** включён в mainline Linux kernel (2026). Требует патчей или сборки ядра.

### Включение CUBIC (восстановление по умолчанию)

```ini
# /etc/sysctl.d/99-network.conf
net.core.default_qdisc = fq_codel
net.ipv4.tcp_congestion_control = cubic
```

### Выбор алгоритма для сценария

| Сценарий | Рекомендуемый алгоритм | qdisc | Обоснование |
| :--- | :--- | :--- | :--- |
| **Веб-сервер (общий)** | BBR | fq | Низкая задержка, хорошая пропускная способность |
| **Прокси/балансировщик** | BBR | fq | Двусторонний трафик, чувствительность к latency |
| **Мобильные сети** | BBR | fq | Устойчивость к переменным потерям |
| **Высокоскоростные каналы (>1 Гбит/с)** | BBR | fq | Лучшая утилизация BDP |
| **Совместимость (старые ядра)** | CUBIC | fq_codel | По умолчанию, стабилен |
| **ЦОД с ECN** | DCTCP | mqprio | Минимальные задержки в ЦОД |

## Additional Information

### Связанные темы

- **SSoT:** [Алгоритмы congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — подробная документация (CUBIC, BBR, формулы, фазы работы)
- **Основы:** [Обзор congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_control_overview.md) — Slow Start, AIMD, Fast Recovery
- **Диагностика:** [Диагностика congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_diagnostics.md) — практические сценарии
- **Дисциплины очередей:** [Дисциплины очередей TCP](./tcp_queueing_disciplines.md) — взаимодействие с congestion control
- **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
