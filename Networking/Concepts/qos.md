# QoS (Quality of Service)

## Определения

**QoS (Quality of Service)** — набор технологий для управления сетевым трафиком: приоритизация, гарантия пропускной способности, контроль задержек и джиттера.

## Основные концепции

| Механизм | Описание |
| :--- | :--- |
| Приоритизация | Критичный трафик (VoIP, видео) получает высший приоритет |
| Гарантия полосы | Резервирование части канала для конкретных приложений |
| Управление перегрузками | Контроль очередей, отбрасывание низкоприоритетных пакетов |
| Контроль задержек | Минимизация latency и jitter для real-time приложений |

Подробнее: [Качество real-time трафика](./real_time_traffic_quality.md).

## Практические сценарии

### Шаг 1: Классификация и маркировка

Трафик разделяется на классы по IP-адресам, портам или данным L7. Пакеты маркируются для дальнейшей обработки:

- **L2:** Поле PCP (Priority Code Point) в VLAN-теге 802.1Q (3 бита, приоритет 0–7).
- **L3:** Поле DSCP (Differentiated Services Code Point) в заголовке IP-пакета (6 бит).

### Шаг 2: Управление очередями (Queuing)

Для каждого класса создаётся отдельная очередь. Высокоприоритетные пакеты обрабатываются первыми. Распространённые дисциплины: FIFO, Priority Queuing, Weighted Fair Queuing (WFQ), Class-Based Weighted Fair Queuing (CBWFQ).

### Шаг 3: Предотвращение перегрузок

**WRED (Weighted Random Early Detection)** — начинает отбрасывать низкоприоритетные пакеты до полной перегрузки канала, давая отправителям сигнал снизить скорость.

### Шаг 4: Policing и Shaping

| Механизм | Действие при превышении | Направление | Буферизация |
| :--- | :--- | :--- | :--- |
| **Policing** | Отбрасывает (drop) пакеты | Ingress/Egress | Нет |
| **Shaping** | Помещает в очередь (buffer) | Egress | Да |

- **Policing** — жёсткое ограничение: всё сверх лимита отбрасывается. Эффективен для входящего трафика (`ingress`), где управление очередью на отправителе невозможно.
- **Shaping** — сглаживает пиковые нагрузки через буферизацию. Пакеты отправляются при появлении свободного места в канале. Применяется для исходящего трафика (`egress`).

### Реализация в Linux

Утилита `tc` (traffic control) из пакета `iproute2` реализует QoS через дисциплины очередей (qdisc), классы и фильтры. Основные qdisc: HTB (Hierarchical Token Bucket), TBF (Token Bucket Filter), FQ-CoDel (Fair Queuing Controlled Delay).

Подробнее: [tc — управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md).

## Дополнительная информация

- Real-time трафик: [Real-Time Traffic Quality](./real_time_traffic_quality.md)
- Оптимизация задержек: [Network Latency Optimization](../../Linux/Networking/Concepts/network_latency_optimization.md)
- Traffic control в Linux: [tc Overview](../../Linux/Networking/Tools/iproute2/tc.md)
- Агрегация каналов: [Link Aggregation](./link_aggregation.md)
