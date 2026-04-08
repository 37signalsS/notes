# Wireshark: Диагностика производительности TCP — Обзор

## Определения

**Диагностика производительности TCP в Wireshark** — метод анализа сетевого трафика для выявления узких мест передачи данных на стороне сервера, клиента или сети.

**Ключевые метрики:**

- **RTT (Round Trip Time)** — время от отправки пакета до получения подтверждения (ACK)
- **Delta Time** — временной интервал между пакетами
- **Throughput** — скорость передачи данных в единицу времени
- **Window Size** — размер TCP-окна (объём данных, которые можно отправить без подтверждения)
- **Bytes in Flight** — количество байт, отправленных но ещё не подтверждённых
- **Retransmit** — повторная отправка пакета из-за потери или тайм-аута
- **DupACK (Duplicate ACK)** — повторное подтверждение, указывающее на потерю пакета

---

## Basic Concepts

### Механизм определения скорости TCP

Скорость передачи данных по TCP изначально неизвестна ни клиенту, ни серверу и определяется динамически в процессе передачи:

1. **Начальная скорость** — определяется алгоритмом [Slow Start](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md)
2. **Динамическая адаптация** — скорость меняется в зависимости от ACK, потерь пакетов, задержек (RTT)
3. **Направление** — скорость может отличаться в разных направлениях

**Факторы влияния:** ограничения провайдера (шейперы), физические помехи (Wi-Fi), загруженность сети, производительность клиента/сервера.

### TCP-окно и In-flight пакеты

**In-flight пакеты** — пакеты, отправленные но ещё не подтверждённые получателем.

**TCP-окно (Window)** — минимальное из двух значений:

- **cwnd (congestion window)** — окно перегрузки, определяется отправителем на основе состояния сети. Подробности: [Congestion Control](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md)
- **rwnd (receiver window)** — окно получателя, свободное место в буфере. Подробности: [Flow Control](../../Protocols/TCP/Flow_Control/index.md)

```
Effective Window = min(cwnd, rwnd)
```

**Принцип работы:** при установке соединения стороны анонсируют MSS. Получатель указывает, сколько байт готов принять (rwnd). Отправитель отправляет данные в пределах окна. При получении ACK окно «сдвигается».

### Потери пакетов и восстановление

TCP обнаружает потери двумя способами:

1. **Fast Retransmit** — 3 DupACK → немедленная повторная отправка
2. **Timeout-based Retransmit** — тайм-аут RTO → падение скорости до 0, перезапуск Slow Start

**Допустимый уровень потерь:**

- **< 0,1%** — норма, случайные потери
- **0,1–1%** — допустимо, но требует наблюдения
- **> 1%** — проблема сети, скорость будет плавать

Подробный механизм: [Congestion Control Overview](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md), [Congestion Diagnostics](../../Protocols/TCP/congestion/tcp_congestion_diagnostics.md).

### Влияние offloading

Offloading (TSO, GRO, LRO, Checksum) создаёт ложные артефакты в Wireshark: пакеты > MSS, неверные checksum, ложные Retransmit. Всегда проверяйте Throughput — если он стабилен, ошибки ложные. Подробности: [Network Offloading](../../../../Linux/Networking/Concepts/offloading.md), [Потери в сети и offloading](./tcp_network_losses_and_offloading.md).

---

## Practical Scenarios

### Подготовка к анализу

#### Добавление столбцов для анализа производительности

| Столбец | Поле | Описание |
| :--- | :--- | :--- |
| **Delta Time (displayed)** | `frame.time_delta_displayed` | Разница между отображёнными пакетами (учитывает фильтры) |
| **Delta Time (captured)** | `frame.time_delta` | Разница между всеми захваченными пакетами |
| **TCP Segment Len** | `tcp.len` | Размер полезных данных в сегменте |
| **Calculated Window Size** | `tcp.window_size_value` | Размер окна, объявленный стороной |
| **Bytes in Flight** | `tcp.analysis.bytes_in_flight` | Байты отправленные но ещё не подтверждённые |

**Как добавить:** `Packet Details → Transmission Control Protocol → Правая кнопка на поле → Apply as Column`

> **Важно:** `frame.time_delta_displayed` нельзя сортировать при >20k пакетов. Используйте `frame.time_delta`.

#### Переименование IP-адресов

Для удобства анализа: `Правая кнопка на IP → Edit Resolved Name → Ввести имя` (например, «client», «server»).

#### Поиск наиболее активного потока

`Statistics → Conversations → TCP → Сортировка по Bytes → Правая кнопка → Apply as Filter → Selected → On Stream ID`

### Чек-лист быстрой диагностики

| Симптом | График/Метрика | Вероятная причина | Сценарий |
| :--- | :--- | :--- | :--- |
| **Паузы в передаче** + RTT стабильный (μs) | Time-Sequence: горизонтальные линии, RTT Graph: низкий | **Сервер** не успевает | [Диагностика проблем сервера](./tcp_server_performance_issues.md) |
| **Паузы в передаче** + RTT растёт (ms) | RTT Graph: высокий | **Клиент** не успевает | [Диагностика проблем клиента](./tcp_client_performance_issues.md) |
| **Window Full / Zero Window** | Window Scaling: падение до 0 | Буфер клиента заполнен | [Диагностика проблем клиента](./tcp_client_performance_issues.md) |
| **Провалы скорости до 0** + >1% Retransmit | IO Graph: регулярные падения, Expert Info: много ошибок | **Потери в сети** | [Потери в сети и offloading](./tcp_network_losses_and_offloading.md) |
| **Провалы скорости** + <0,1% Retransmit | Expert Info: ошибок мало, Throughput стабилен | **Offloading** (ложные ошибки) | [Потери в сети и offloading](./tcp_network_losses_and_offloading.md) |
| **Стабильная низкая скорость** | Throughput: ровная линия без провалов | **Ограничение сети** (шейперы провайдера) | [Потери в сети и offloading](./tcp_network_losses_and_offloading.md) |

---

## Additional Information

### Формулы

**Максимальная пропускная способность:**

```
Throughput ≤ Window Size / RTT

Пример:
Window = 64 KB, RTT = 100 ms
Throughput ≤ 65536 / 0.1 = 655 KB/s ≈ 5.2 Мбит/с
```

**Требуемый размер окна (BDP — Bandwidth-Delay Product):**

```
Window ≥ Throughput × RTT

Пример:
Throughput = 1 Гбит/с, RTT = 50 ms
Window ≥ 125 MB/s × 0.05 = 6.25 MB
```

Оптимальный размер буфера ≥ BDP для полной утилизации канала. Настройка: [Оптимизация буферов TCP](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_buffer_tuning.md).

### Предупреждения

1. **Offloading создаёт ложные ошибки** — всегда проверяйте Throughput перед выводом
2. **Delta Time не сортируется при >20k пакетов** — используйте `frame.time_delta`
3. **Захват на одной стороне может быть недостаточен** — для диагностики сети нужен захват с двух сторон
4. **Современные алгоритмы (BBR, CUBIC) сложнее классических** — поведение может отличаться от AIMD

### Связанные темы

Смежные темы: [Диагностика проблем сервера](./tcp_server_performance_issues.md), [Диагностика проблем клиента](./tcp_client_performance_issues.md), [Потери в сети и offloading](./tcp_network_losses_and_offloading.md), [Инструменты анализа](./tcp_performance_analysis_tools.md), [Congestion Control](../../Protocols/TCP/congestion/tcp_congestion_control_overview.md), [Flow Control](../../Protocols/TCP/Flow_Control/index.md), [Оптимизация TCP в Linux](../../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md), [tcpdump](../../../../Linux/Diagnostics/Networking/tcpdump.md).
