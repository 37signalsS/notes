# Оптимизация буферов TCP

## Определения

**TCP буферы** — области памяти ядра, используемые для буферизации входящих (`rmem`) и исходящих (`wmem`) данных TCP-соединений.

**Автотюнинг TCP** — механизм ядра Linux, автоматически адаптирующий размер буфера в пределах заданных значений (`tcp_rmem`/`tcp_wmem`) на основе текущей нагрузки и характеристик соединения.

## Basic Concepts

### Иерархия параметров

Настройка буферов происходит на двух уровнях:

1. **Уровень ядра (`net.core.*`)** — глобальные максимальные размеры для всех типов сокетов:
   - `net.core.rmem_max` — максимальный receive buffer для любого сокета
   - `net.core.wmem_max` — максимальный send buffer для любого сокета

2. **Уровень TCP (`net.ipv4.tcp_*`)** — специфичные параметры для TCP-соединений:
   - `net.ipv4.tcp_rmem` — три значения: `min default max` для receive buffer
   - `net.ipv4.tcp_wmem` — три значения: `min default max` для send buffer

### Параметры tcp_rmem и tcp_wmem

Каждый параметр содержит три значения (в байтах):

| Параметр | Описание | Типичное значение |
| :--- | :--- | :--- |
| **min** | Минимальный размер буфера | `4096` |
| **default** | Начальный размер при установлении соединения | `87380` (receive), `65536` (send) |
| **max** | Максимальный размер при автотюнинге | `16777216` (16 МБ) |

### Связь с Window Scaling

Размер TCP-буфера напрямую влияет на максимальное окно (window) соединения. Без Window Scaling (RFC 7323) максимальное окно ограничено 65535 байт (~64 КБ). С включённым масштабированием (проверяется через `ss -tno | grep wscale`) реальное окно может достигать ~1 ГБ.

**Формула BDP (Bandwidth-Delay Product):**

```
BDP = Пропускная способность × RTT
```

Оптимальный размер буфера ≥ BDP для полной утилизации канала.

### Связь с SO_RCVBUF и SO_SNDBUF

Приложения могут переопределять размер буфера на уровне сокета через `setsockopt()`:

```python
sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16 * 1024 * 1024)
```

**Ограничение:** значение через `SO_RCVBUF`/`SO_SNDBUF` не может превышать `net.core.rmem_max`/`net.core.wmem_max`.

## Practical Scenarios

### Проверка текущих значений

```bash
# Глобальные максимумы
sysctl net.core.rmem_max
sysctl net.core.wmem_max

# TCP-специфичные параметры
sysctl net.ipv4.tcp_rmem
sysctl net.ipv4.tcp_wmem

# Через procfs
cat /proc/sys/net/core/rmem_max
cat /proc/sys/net/ipv4/tcp_rmem
```

### Настройка буферов

**Временно:**

```bash
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216
sudo sysctl -w net.ipv4.tcp_rmem='4096 87380 16777216'
sudo sysctl -w net.ipv4.tcp_wmem='4096 65536 16777216'
```

**Постоянно** (`/etc/sysctl.d/99-network.conf`):

```ini
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
```

Применение: `sudo sysctl -p /etc/sysctl.d/99-network.conf`

### Диагностика проблем с буферами

**Поиск сокетов с нулевым окном (Zero Window):**

```bash
ss -tmo | grep 'window:0'
watch -n1 'ss -tmo | grep -c "window:0"'
```

**Анализ состояния буферов:**

```bash
# Показать receive/send buffer на активных соединениях
ss -tmo

# Ключевые поля:
# rcvspace — размер receive buffer
# sndbuf — размер send buffer
```

**Симптомы недостаточного буфера:**

- Zero Window в Wireshark — приложение не успевает читать из сокета
- Window Full — буфер заполнен, передача остановлена
- Высокий `bytes_received` при низком `rcvspace` — узкое место

### Рекомендации по размерам

| Сценарий | tcp_rmem (max) | tcp_wmem (max) | Обоснование |
| :--- | :--- | :--- | :--- |
| **Веб-сервер** | 16 МБ | 4 МБ | Больше receive для отдачи контента |
| **Прокси/балансировщик** | 16 МБ | 16 МБ | Двусторонний трафик |
| **Высокая задержка (спутник)** | 64 МБ+ | 64 МБ+ | BDP может достигать десятков МБ |
| **Локальная сеть** | 4 МБ | 4 МБ | Низкий RTT, достаточно умеренных буферов |

> **Внимание:** чрезмерное увеличение буферов может привести к bufferbloat — росту задержек из-за избыточной буферизации. Мониторьте латентность после изменений.

## Additional Information

### Связанные темы

- **Обзор оптимизации TCP:** [Оптимизация TCP в Linux: Обзор](./tcp_tuning_overview.md)
- **Управление перегрузкой:** [Алгоритмы управления перегрузкой](./tcp_congestion_algorithms.md)
- **Дисциплины очередей:** [Дисциплины очередей TCP](./tcp_queueing_disciplines.md) — борьба с bufferbloat
- **Flow Control:** [Управление потоком TCP](../../../Networking/Protocols/TCP/Flow_Control/index.md)
- **Диагностика сокетов:** [Диагностика сокетов TCP](./tcp_socket_diagnostics.md)
- **sysctl:** [Настройка sysctl](../../Core/kernel/sysctl.md)

### Источники

- [RFC 7323 — TCP Extensions for High Performance](https://datatracker.ietf.org/doc/html/rfc7323)
- [Kernel documentation: TCP sysctl parameters](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt)
