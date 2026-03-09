# tc netem: практические сценарии эмуляции

## Добавление задержки

```bash
# Базовая задержка 100 мс
sudo tc qdisc add dev eth0 root netem delay 100ms

# Задержка 200 мс с джиттером 40 мс и корреляцией 50%
sudo tc qdisc add dev eth0 root netem delay 200ms 40ms 50%
```

---

## Потеря пакетов

```bash
# Потеря 70% пакетов
sudo tc qdisc add dev eth0 root netem loss 70%

# Потеря 10% с корреляцией 25%
sudo tc qdisc add dev eth0 root netem loss 10% 25%
```

### Диагностика потерь

Для отслеживания ретрансмиссий TCP используйте:

```bash
# Счётчик ретрансмиссий до и после теста
netstat -s | grep retransmited; sleep 10; netstat -s | grep retransmited
```

При потере пакетов время выполнения сетевых запросов становится нестабильным (может варьироваться от мгновенного до 20+ секунд).

---

## Повреждение и дублирование

```bash
# Повреждение 50% пакетов
sudo tc qdisc add dev eth0 root netem corrupt 50%

# Дублирование 40% пакетов
sudo tc qdisc add dev eth0 root netem duplicate 40%
```

### Повреждение пакетов (corrupt)

- В случайной позиции пакета появляется шум
- TCP обнаруживает повреждение через контрольную сумму (checksum)
- Повреждённые пакеты отбрасываются, инициируется ретрансмиссия
- В tcpdump видны пакеты с `[bad opt]` или некорректными опциями

### Дублирование пакетов

- Обратная ситуация потере — пакеты приходят дважды
- Важно для тестирования механизмов дедупликации
- TCP обрабатывает дубликаты через acknowledgment mechanism

---

## Комбинированные эффекты

```bash
# Задержка 200 мс + потеря 10%
sudo tc qdisc add dev eth0 root netem delay 200ms loss 10%

# Дублирование 40% + задержка 100 мс
sudo tc qdisc add dev eth0 root netem duplicate 40% delay 100ms
```

---

## Изменение порядка пакетов

```bash
# 30% пакетов приходят с задержкой 50 мс (остальные без задержки)
sudo tc qdisc add dev eth0 root netem delay 50ms 10ms reorder 30% 50%
```

### Два способа reorder

**1. Часть пакетов задерживается:**

```bash
# 25% пакетов с корреляцией 50% отправятся сразу, остальные — с задержкой 10ms
tc qdisc change dev lo root netem delay 10ms reorder 25% 50%
```

**2. Каждый N-й пакет без задержки:**

```bash
# Каждый 5-й пакет с вероятностью 25% отправится без задержки
tc qdisc change dev lo root netem delay 10ms reorder 25% 50% gap 5
```

> **Важно:** `reorder` требует указания базовой задержки (`delay`).

---

## Ограничение скорости

```bash
# Ограничение до 1 Мбит/с
sudo tc qdisc add dev eth0 root netem rate 1mbit
```

---

## Просмотр и удаление

```bash
# Просмотр конфигурации
tc qdisc show dev eth0

# Статистика по пакетам
tc -s qdisc show dev eth0

# Удаление netem
sudo tc qdisc del dev eth0 root netem
```

> **Важно:** Если `tc qdisc del` возвращает `No such file or directory` — `netem` не настроен на интерфейсе.

---

## Тестовые сценарии

### Тестирование устойчивости приложения к задержкам

```bash
# Эмуляция WAN-канала с задержкой 200ms
sudo tc qdisc add dev eth0 root netem delay 200ms

# Запуск тестов приложения
# ...

# Очистка
sudo tc qdisc del dev eth0 root netem
```

### Тестирование обработки потерь пакетов

```bash
# Потеря 5% пакетов (типично для перегруженных сетей)
sudo tc qdisc add dev eth0 root netem loss 5%

# Проверка работы TCP (ретрансмиссии, congestion control)
watch -n 1 'ss -ti | grep -E "retrans|cwnd"'

# Очистка
sudo tc qdisc del dev eth0 root netem
```

### Тестирование VoIP/видеосвязи

```bash
# Эмуляция мобильного соединения с джиттером
sudo tc qdisc add dev eth0 root netem delay 80ms 40ms 25% loss 1%

# Очистка
sudo tc qdisc del dev eth0 root netem
```

### Тестирование распределённых систем (Consensus)

```bash
# Эмуляция межрегионального канала
sudo tc qdisc add dev eth0 root netem delay 50ms 10ms

# Тестирование consensus-алгоритмов (Raft, Paxos)
# ...

# Очистка
sudo tc qdisc del dev eth0 root netem
```

### Эмуляция спутникового канала

```bash
# Высокая задержка (600ms), минимальные потери
sudo tc qdisc add dev eth0 root netem delay 600ms 50ms loss 0.1%
```

### Эмуляция 3G-сети

```bash
# Задержка с джиттером, потери, дублирование, reorder
sudo tc qdisc add dev eth0 root netem delay 100ms 50ms loss 5% duplicate 2% reorder 10%
```
