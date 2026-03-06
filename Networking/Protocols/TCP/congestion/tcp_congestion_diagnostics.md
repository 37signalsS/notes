# Диагностика управления перегрузкой TCP

## 1. Диагностика congestion control

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

**Поля:**

- `cubic` — активный алгоритм
- `cwnd:10` — текущее окно перегрузки (10 MSS)
- `rtt:0.5/0.25` — RTT (среднее/отклонение)

---

## 2. Выбор алгоритма

### Рекомендации

| Сценарий | Рекомендуемый алгоритм | Обоснование |
| :--- | :--- | :--- |
| **Веб-сервер (общий)** | `bbr` | Низкая задержка, хорошая пропускная способность |
| **ЦОД (data center)** | `dctcp` | Оптимизирован для низких задержек ЦОД |
| **Мобильные сети** | `bbr` или `westwood` | Устойчивость к потерям |
| **Высокоскоростные каналы (>1 Гбит/с)** | `bbr` | Лучшая утилизация BDP |
| **Совместимость (старые ядра)** | `cubic` | По умолчанию, стабилен |

### Настройка

```bash
# Включение BBR
echo "net.core.default_qdisc = fq" >> /etc/sysctl.conf
echo "net.ipv4.tcp_congestion_control = bbr" >> /etc/sysctl.conf
sysctl -p
```

---

## 3. Packet Pacing

**Проблема:** отправка всех 10 пакетов `initcwnd` одной очередью вызывает краткосрочную перегрузку.

**Решение:** равномерная отправка пакетов во времени.

**Включение (BBR автоматически использует pacing):**

```bash
# Проверка
ethtool -k eth0 | grep pacing

# BBR автоматически включает pacing с ядром 4.x+
```

---

## 4. Проблемы и решения

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **Низкая пропускная способность** | cwnd растёт медленно | Увеличить `initcwnd`, включить BBR |
| **Bufferbloat** | Высокая задержка при загрузке | BBR вместо CUBIC, fq_codel |
| **Частые потери** | cwnd постоянно падает | Проверить сеть, ECN |
| **Неравномерная скорость** | «Пиловидный» график cwnd | Нормально для AIMD, рассмотреть BBR |

---

## 5. Связанные документы

- **[Обзор и базовые алгоритмы](./tcp_congestion_control_overview.md)** — Slow Start, AIMD, Fast Recovery
- **[Алгоритмы congestion control](./tcp_congestion_algorithms.md)** — CUBIC, BBR
- **[Оптимизация initcwnd](./tcp_initcwnd_and_optimization.md)** — правило 14 КБ
- **[Оптимизация TCP](../../../../Linux/Networking/Concepts/tcp_tuning.md)** — практическая настройка
- **[Wireshark: Диагностика производительности](../../../ServicesAndTools/Wireshark/tcp_performance/tcp_performance_diagnostics.md)** — анализ проблем
