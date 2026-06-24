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

- **Policing** — жёстко ограничивает скорость, отбрасывая избыточные пакеты. Не использует буферизацию и не вносит задержек. Применяется для контроля **входящего трафика (`ingress`)**, где управление очередью на отправителе невозможно.
- **Shaping** — «сглаживает» пиковые нагрузки путём временной буферизации избыточных пакетов. Вносит задержку, но предотвращает потери. Применяется для управления **исходящим трафиком (`egress`)**.

| Механизм | Действие при превышении | Направление | Буферизация | Применение |
| :--- | :--- | :--- | :--- |:---|
| **Policing** | Отбрасывает (drop) пакеты | Ingress/Egress | Нет | Ограничение входящего трафика |
| **Shaping** | Помещает в очередь (buffer) | Egress | Да | Контроль исходящего трафика |

### Реализация в Linux

Утилита `tc` (traffic control) из пакета `iproute2` реализует QoS через дисциплины очередей (qdisc), классы и фильтры. Основные qdisc: HTB (Hierarchical Token Bucket), TBF (Token Bucket Filter), FQ-CoDel (Fair Queuing Controlled Delay).

Подробнее: [tc — управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md).

### Реализация в MikroTik (RouterOS)

MikroTik использует систему Queue для ограничения пропускной способности. Два основных типа: Simple Queue и Queue Tree.

#### Simple Queue

Простой способ ограничения для отдельных IP, подсетей или интерфейсов. Позволяет задать лимиты входящего (`target-upload`) и исходящего (`target-download`) трафика.

```bash
# Ограничение IP 192.168.88.50 до 10 Мбит/с
/queue simple add name="Limit-10M" target=192.168.88.50/32 max-limit=10M/10M

# Ограничение всего интерфейса ether1
/queue simple add name="Interface-Limit" target=ether1 max-limit=100M/100M

# Ограничение подсети
/queue simple add name="Subnet-Limit" target=192.168.88.0/24 max-limit=50M/50M
```

#### PCQ (Per Connection Queue)

PCQ автоматически создаёт виртуальные очереди для каждого клиента, справедливо распределяя пропускную способность. Администратору не нужно вручную создавать отдельные правила для каждого IP.

```bash
# Создание типов очередей PCQ
/queue type add name=PCQ_download kind=pcq pcq-classifier=dst-address pcq-rate=5M pcq-limit=50
/queue type add name=PCQ_upload kind=pcq pcq-classifier=src-address pcq-rate=2M pcq-limit=50

# Привязка типа к подсети
/queue simple add name="Office" target=192.168.1.0/24 max-limit=10M/10M queue=PCQ_download/PCQ_upload
```

В этом примере каждое устройство в подсети получает до 5 Мбит/с на загрузку и 2 Мбит/с на отдачу, при общем лимите 10 Мбит/с на всю подсеть.

**Проверка очередей:**

```bash
/queue simple print
/queue simple monitor 0
/queue simple print stats
```

## Дополнительная информация

- Real-time трафик: [Real-Time Traffic Quality](./real_time_traffic_quality.md)
- Оптимизация задержек: [Network Latency Optimization](../../Linux/Networking/Concepts/network_latency_optimization.md)
- Traffic control в Linux: [tc — управление трафиком](../../Linux/Networking/Tools/iproute2/tc.md)
- Агрегация каналов: [Link Aggregation](./link_aggregation.md)
