# tc: Управление трафиком (Traffic Control)

## Определения

* **`tc` (Traffic Control)** — утилита пакета `iproute2` для реализации QoS в Linux. Управляет дисциплинами очередей (`qdisc`), классами и фильтрами.
* **`qdisc` (Queuing Discipline)** — дисциплина очереди, механизм ядра Linux, определяющий как пакеты обрабатываются, откладываются или отбрасываются.
* **Policing** — жесткое ограничение скорости путем отбрасывания (`drop`) пакетов, превышающих лимит. Без буферизации. Применяется для **входящего (`ingress`)** трафика.
* **Shaping** — «сглаживание» пиковых нагрузок путем буферизации избыточных пакетов для отправки позже. Вносит задержку. Применяется для **исходящего (`egress`)** трафика.
* **HTB (Hierarchical Token Bucket)** — дисциплина для приоритизации трафика с иерархической структурой классов.
* **fq_codel** — дисциплина для борьбы с bufferbloat, снижающая латентность.

## Основные концепции

### Полисинг vs Шейпинг

| Аспект | Policing | Shaping |
|--------|----------|---------|
| Механизм | Отбрасывание пакетов | Буферизация в очереди |
| Задержка | Нет | Возможна |
| Направление | Ingress (входящий) | Egress (исходящий) |
| Применение | Ограничение входящего | Контроль исходящего |

### Интеграция с TCP-стеком

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
* `protocol ip`: Фильтр будет применяться к IP-трафику.
* `u32 match u32 0 0`: Универсальный классификатор `u32`, который сопоставляет трафик с любым пакетом (`match u32 0 0` означает "сопоставить 32-битное значение 0 со смещением 0", что фактически означает "любой пакет"). Это простой и надежный способ "поймать" весь входящий трафик.
* `police rate 100kbit burst 8k drop`: Основное действие.
  * `rate 100kbit`: Устанавливает лимит скорости в 100 килобит в секунду.
  * `burst 8k`: Разрешает кратковременные "всплески" трафика сверх лимита, используя буфер (token bucket) размером 8 килобайт.
  * `drop`: Действие, которое нужно выполнить при превышении лимита — отбросить пакет.

```bash
# Проверка статистики (счетчик dropped)
sudo tc -s filter show dev eth0 parent ffff:

# Удаление правила
sudo tc qdisc del dev eth0 ingress
```

### Приоритизация трафика с HTB и fq_codel

```bash
# Создание HTB (Hierarchical Token Bucket) с классами приоритета
tc qdisc replace dev eth0 root handle 1: htb default 20

# Корневой класс с ограничением скорости
tc class add dev eth0 parent 1: classid 1:1 htb rate 1gbit ceil 1gbit

# Класс приоритета 0 для интерактивного трафика (200 Мбит)
tc class add dev eth0 parent 1:1 classid 1:10 htb rate 200mbit prio 0

# Класс приоритета 1 для фонового трафика (800 Мбит)
tc class add dev eth0 parent 1:1 classid 1:20 htb rate 800mbit prio 1

# Добавление fq_codel к каждому классу для борьбы с bufferbloat
tc qdisc add dev eth0 parent 1:10 fq_codel
tc qdisc add dev eth0 parent 1:20 fq_codel
```

**Использование:**

* Маркировка пакетов DSCP на стороне приложения/прокси.
* Направление маркированного трафика в приоритетный класс (1:10).

### Эмуляция сетевых проблем (netem)

```bash
# Добавление задержки 100ms
sudo tc qdisc add dev eth0 root netem delay 100ms

# Задержка с вариацией (200ms ± 40ms, 50% корреляция)
sudo tc qdisc add dev eth0 root netem delay 200ms 40ms 50%

# Потери пакетов (70%)
sudo tc qdisc add dev eth0 root netem loss 70%

# Повреждение пакетов (50%)
sudo tc qdisc add dev eth0 root netem corrupt 50%

# Дублирование пакетов (40%)
sudo tc qdisc add dev eth0 root netem duplicate 40%

# Комбинация эффектов
sudo tc qdisc add dev eth0 root netem delay 200ms loss 10%
```

```bash
# Просмотр настроенных qdisc
tc qdisc show dev eth0

# Удаление netem
sudo tc qdisc del dev eth0 root netem
```

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

* **Для initcwnd:** настройка через [`ip route`](../../Tools/iproute2/ip_route.md).
* **Для буферов TCP:** через [`sysctl`](../../../Core/kernel/sysctl.md) (см. [Оптимизация TCP](../../Concepts/tcp_tuning/tcp_buffer_tuning.md)).
* **Для многопоточности:** [RSS, RPS, RFS](../../Concepts/rss_rps_rfs.md).

### Связанные темы

* **[Оптимизация TCP](../../Concepts/tcp_tuning/tcp_tuning_overview.md)** — настройка TCP-стека, алгоритмы congestion control
* **[`ip route`](./ip_route.md)** — управление маршрутами и initcwnd
* **[QoS](../../../../Networking/Concepts/qos.md)** — концепции качества обслуживания
* **[tc netem](./tc_netem.md)** — детальное описание эмуляции сетевых проблем
