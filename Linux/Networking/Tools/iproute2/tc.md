# tc: Управление трафиком (Traffic Control)

## Определения

* **`tc` (Traffic Control)** — утилита пакета `iproute2` для реализации QoS в Linux. Управляет дисциплинами очередей (`qdisc`), классами и фильтрами.
* **`qdisc` (Queuing Discipline)** — дисциплина очереди, механизм ядра Linux, определяющий как пакеты обрабатываются, откладываются или отбрасываются.
* **HTB (Hierarchical Token Bucket)** — дисциплина для приоритизации трафика с иерархической структурой классов.
* **fq_codel** — дисциплина для борьбы с bufferbloat, снижающая латентность.

> Основные концепции QoS, включая детальное сравнение **Policing** и **Shaping**, описаны в файле [QoS](../../../../Networking/Concepts/qos.md).

## Основные концепции

### Интеграция с сетевым стеком

> Настройка дисциплин по умолчанию через `sysctl` описана в [Оптимизация TCP](../../Concepts/tcp_tuning/tcp_queueing_disciplines.md).

* `net.core.default_qdisc` — задает qdisc по умолчанию (например, `fq_codel`).
* Детальная настройка классов и фильтров выполняется через `tc`.

### Структура QoS

```
Корневая qdisc
├── Класс 1:10 (высокий приоритет)
│   └── Дочерняя qdisc (fq_codel)
├── Класс 1:20 (низкий приоритет)
│   └── Дочерняя qdisc (fq_codel)
└── Фильтры (классификация трафика)
```

## Практические сценарии

### Ограничение входящего трафика (Policing)

Задача: ограничить скорость загрузки до 100 кбит/с.

```bash
# Проверить существующие дисциплины
sudo tc qdisc show dev eth0

# Добавить ingress qdisc
sudo tc qdisc add dev eth0 handle ffff: ingress

# Добавить фильтр с полисингом (весь IP-трафик)
sudo tc filter add dev eth0 parent ffff: protocol ip u32 match u32 0 0 police rate 100kbit burst 8k drop
```

**Параметры:**

* `filter add dev eth0 parent ffff:`: Добавляем фильтр к `ingress` qdisc на интерфейсе `eth0`.
* `u32 match u32 0 0`: Универсальный классификатор `u32`, сопоставляет любой пакет.
* `police rate 100kbit burst 8k drop`:
  * `rate 100kbit`: Лимит скорости.
  * `burst 8k`: Размер буфера (token bucket) для всплесков.
  * `drop`: Отбрасывать пакеты при превышении лимита.

```bash
# Проверка статистики (счетчик dropped)
sudo tc -s filter show dev eth0 parent ffff:

# Удаление правила
sudo tc qdisc del dev eth0 ingress
```

### Приоритизация трафика с HTB и fq_codel

```bash
# Создание HTB с классами приоритета
tc qdisc replace dev eth0 root handle 1: htb default 20

# Корневой класс с ограничением скорости
tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# Класс приоритета 0 для интерактивного трафика (200 Мбит)
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 200mbit prio 0

# Класс приоритета 1 для фонового трафика (800 Мбит)
tc class add dev eth0 parent 1:1 classid 1:20 htb rate 800mbit prio 1

# Добавление fq_codel к каждому классу
tc qdisc add dev eth0 parent 1:10 fq_codel
tc qdisc add dev eth0 parent 1:20 fq_codel
```

### Эмуляция сетевых проблем (netem)

Для тестирования сетевых задержек, потерь и повреждений пакетов используется модуль `netem`.

```bash
# Добавление задержки 100ms
sudo tc qdisc add dev eth0 root netem delay 100ms

# Удаление netem
sudo tc qdisc del dev eth0 root netem
```

Подробные сценарии (потери, дублирование, джиттер) описаны в разделе **[tc netem](./tc_netem.md)**.

## Дополнительная информация

### Таблица дисциплин очередей

| Дисциплина | Назначение | Когда использовать |
|------------|------------|-------------------|
| `htb` | Иерархическое управление полосой | Приоритизация трафика |
| `fq_codel` | Борьба с bufferbloat | Низкая латентность |
| `fq` | Fair Queuing | Pacing с BBR |
| `netem` | Эмуляция проблем | Тестирование |
| `ingress` | Точка для фильтров | Policing входящего |

### Интеграция с сетевым стеком

* **Для initcwnd:** настройка через [`ip route`](./ip_route.md).
* **Для буферов TCP:** через [`sysctl`](../../../Core/kernel/sysctl.md).
* **Для многопоточности:** [RSS, RPS, RFS](../../Concepts/rss_rps_rfs.md).

### Связанные темы

* **[QoS](../../../../Networking/Concepts/qos.md)** — концепции качества обслуживания
* **[tc netem](./tc_netem.md)** — детальное описание эмуляции сетевых проблем
* **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка сетевого стека
* **[`ip route`](./ip_route.md)** — управление маршрутами и initcwnd
