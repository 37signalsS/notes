# Алгоритмы управления перегрузкой TCP

> **SSoT:** Основная документация по алгоритмам congestion control находится в [Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md)

## Определения

**Алгоритм управления перегрузкой (Congestion Control Algorithm)** — алгоритм, определяющий, как TCP-соединение реагирует на перегрузку сети, регулируя скорость передачи данных для предотвращения коллапса сети.

## Краткий обзор

### CUBIC

* **Статус:** Алгоритм по умолчанию в большинстве дистрибутивов Linux
* **Принцип:** Функция роста на основе времени с момента последней потери пакетов
* **Документация:** [CUBIC](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md#1-cubic-по-умолчанию-в-linux)

### BBR (Bottleneck Bandwidth and Round-trip time)

* **Разработчик:** Google (2016)
* **Принцип:** Модель сети на основе пропускной способности и RTT, а не потерь пакетов
* **Требования:** Ядро Linux 4.9+ (BBRv1), 5.18+ (BBRv2)
* **Документация:** [BBR](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md#2-bbr-bottleneck-bandwidth-and-round-trip-time)

**Ключевое отличие от CUBIC:** BBR не ждёт потерь пакетов для снижения скорости — он постоянно измеряет пропускную способность и RTT, поддерживая передачу на уровне BDP (Bandwidth-Delay Product), что минимизирует задержки (bufferbloat).

### BBRv2

* **Улучшения:** Лучшая fairness с CUBIC, поддержка ECN, стабильность в WiFi/мобильных сетях
* **Документация:** [Версии BBR](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md#версии-bbr)

### Reno

* **Статус:** Классический алгоритм, устарел для современных сетей

## Практическое применение в Linux

### Просмотр доступных алгоритмов

```bash
cat /proc/sys/net/ipv4/tcp_available_congestion_control
```

### Проверка текущего алгоритма

```bash
sysctl net.ipv4.tcp_congestion_control
# или
ss -ti | grep -o 'cong:[[:space:]]*[a-z0-9]*'
```

### Включение BBR

**Требования:** ядро Linux 4.9+

```ini
# /etc/sysctl.conf или /etc/sysctl.d/99-network.conf
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
```

```bash
sudo sysctl -p
```

**Проверка:**

```bash
ss -ti | grep bbr
```

> **Примечание:** BBR автоматически использует pacing (ядро 4.x+). Для BBRv2 требуется ядро 5.18+.

### BBRv3 (experimental)

> **Внимание:** BBRv3 **НЕ** включен в mainline Linux kernel (2026). Требует патчей или сборки ядра.

## Связанные темы

* **SSoT:** [Алгоритмы congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_algorithms.md) — подробная документация
* **Дисциплины очередей:** [Дисциплины очередей](./tcp_queueing_disciplines.md)
* **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
* **Диагностика:** [Диагностика congestion control](../../../Networking/Protocols/TCP/congestion/tcp_congestion_diagnostics.md)
