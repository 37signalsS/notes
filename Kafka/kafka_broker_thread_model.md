# Thread Model брокера Apache Kafka

**Thread Model брокера** — это архитектура потоков обработки запросов в Kafka. Понимание модели потоков критично для настройки производительности, диагностики узких мест и планирования ёмкости кластера.

---

## Определения

- **Network Threads:** Потоки, отвечающие за чтение и запись данных в сетевые сокеты. Обрабатывают TCP-соединения.
- **Request Threads (KafkaRequestHandler):** Потоки, выполняющие логику обработки запросов (produce, fetch, metadata).
- **Replica Fetcher Threads:** Потоки на follower-репликах, которые копируют данные с лидера.
- **Controller Threads:** Потоки брокера-контроллера для управления партициями и репликацией.
- **Log Compaction Threads:** Потоки для фоновой очистки логов по ключу.
- **Purgatory:** Структура данных для отложенных операций (DelayedProduce, DelayedFetch).
- **queued.max.requests:** Максимальное количество запросов в очереди перед request thread'ами.

---

## Основные концепции

### Архитектура потоков брокера

```
┌─────────────────────────────────────────────────────────────┐
│                      Network Threads                         │
│  (num.network.threads)                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                      │
│  │  Acceptor│  │  Acceptor│  │  Acceptor│  (1-3 потока)      │
│  └────┬────┘  └────┬────┘  └────┬────┘                      │
│       │            │            │                            │
│       └────────────┼────────────┘                            │
│                    ▼                                         │
│            ┌───────────────┐                                 │
│            │   Processor   │  (чтение из сокета)             │
│            │   Sockets     │                                 │
│            └───────┬───────┘                                 │
│                    │                                         │
│                    ▼                                         │
│            ┌───────────────┐                                 │
│            │   Request     │  (queued.max.requests)          │
│            │   Queue       │                                 │
│            └───────┬───────┘                                 │
│                    │                                         │
│                    ▼                                         │
│  ┌─────────────────────────────────────────────┐            │
│  │         Request Handler Threads              │            │
│  │         (num.io.threads)                    │            │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐   │            │
│  │  │  1  │ │  2  │ │  3  │ │  4  │ │  N  │   │            │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘   │            │
│  └─────────────────────────────────────────────┘            │
│                    │                                         │
│                    ▼                                         │
│            ┌───────────────┐                                 │
│            │   Response    │  (запись в сокет)               │
│            │   Queue       │                                 │
│            └───────────────┘                                 │
└─────────────────────────────────────────────────────────────┘
```

### Рекомендации по настройке потоков

| Параметр | Рекомендация | Формула | Описание |
|----------|-------------|---------|----------|
| `num.network.threads` | `cores / 2` | 3-8 | Обработка сетевых соединений |
| `num.io.threads` | `cores * 2` | 8-32 | Обработка запросов |
| `num.replica.fetchers` | `cores / 4` | 2-4 | Потоки репликации |
| `queued.max.requests` | 500-1000 | - | Очередь запросов |
| `request.timeout.ms` | 30000-60000 | - | Таймаут запроса |

### Взаимосвязь параметров

**Правило:** `num.io.threads` должно быть больше, чем количество партиций на брокере, делённое на среднее время обработки запроса.

**Пример расчёта:**
- 16 ядер CPU
- `num.network.threads` = 8
- `num.io.threads` = 16
- `num.replica.fetchers` = 4
- `queued.max.requests` = 1000

### Диагностика проблем с потоками

**Симптомы thread starvation:**
- Высокий `RequestHandlerAvgIdlePercent` (< 0.3)
- Высокий `NetworkProcessorAvgIdlePercent` (< 0.3)
- Рост `request_queue_time_ms`
- Увеличение latency при нормальной нагрузке на CPU

**Команды для диагностики:**
```bash
# Thread dump брокера
jstack $(pgrep -f kafka.Kafka) > /tmp/kafka-threaddump.txt

# Анализ состояния потоков
grep -A 5 "kafka-request-handler" /tmp/kafka-threaddump.txt

# Проверка сетевых потоков
grep -A 5 "kafka-network-thread" /tmp/kafka-threaddump.txt
```

### Purgatory и отложенные операции

Kafka использует **Purgatory** для операций, ожидающих выполнения условий:

- **DelayedProduce:** Ожидание подтверждения от реплик (при `acks=all`)
- **DelayedFetch:** Ожидание появления данных для чтения (при `fetch.max.wait.ms`)

**Метрики для мониторга:**
- `kafka.server:type=DelayedProduceMetrics,name=PurgatorySize`
- `kafka.server:type=DelayedFetchMetrics,name=PurgatorySize`

Высокий PurgatorySize может указывать на:
- Медленные реплики
- Проблемы с сетью
- Неправильные настройки `acks`

---

## Практические сценарии

### Сценарий 1: Базовая настройка для production

Файл `server.properties`:
```properties
# Сетевые потоки (приём соединений)
num.network.threads=8

# Потоки обработки запросов
num.io.threads=16

# Потоки репликации
num.replica.fetchers=4

# Очередь запросов
queued.max.requests=1000

# Таймаут запроса
request.timeout.ms=30000
```

### Сценарий 2: Настройка для высокой нагрузки

Для кластеров с > 1000 партициями на брокер:
```properties
num.network.threads=16
num.io.threads=32
num.replica.fetchers=8
queued.max.requests=2000
```

### Сценарий 3: Диагностика thread starvation

```bash
# 1. Проверка метрик через JMX
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent" \
  --one-time true

# 2. Анализ thread dump
jstack $(pgrep -f kafka.Kafka) | grep -E "BLOCKED|WAITING" | head -20

# 3. Проверка очереди запросов
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.network:type=RequestChannel,name=RequestQueueSize" \
  --one-time true
```

### Сценарий 4: Оптимизация для медленных дисков

Если диски медленные (HDD), увеличьте `num.io.threads`:
```properties
num.io.threads=32
queued.max.requests=2000
```

### Сценарий 5: Настройка для контейнеров

В Kubernetes с ограничениями CPU:
```yaml
resources:
  requests:
    cpu: "8"
    memory: "32Gi"
  limits:
    cpu: "16"
    memory: "32Gi"
```

```properties
# Настройки потоков в зависимости от доступных CPU
num.network.threads=4
num.io.threads=8
num.replica.fetchers=2
```

---

## Дополнительная информация

### Мониторинг потоков

Ключевые JMX-метрики:
- `kafka.server:type=KafkaRequestHandlerPool,name=RequestHandlerAvgIdlePercent` — средний процент простоя request handler'ов
- `kafka.network:type=SocketServer,name=NetworkProcessorAvgIdlePercent` — средний процент простоя network processor'ов
- `kafka.network:type=RequestChannel,name=RequestQueueSize` — размер очереди запросов
- `kafka.server:type=RequestChannel,name=ResponseQueueSize` — размер очереди ответов

**Алерты:**
- `RequestHandlerAvgIdlePercent < 0.3` → увеличить `num.io.threads`
- `NetworkProcessorAvgIdlePercent < 0.3` → увеличить `num.network.threads`
- `RequestQueueSize > 1000` → увеличить `queued.max.requests` или `num.io.threads`

### Связь с другими настройками

- **OS Tuning:** Количество потоков должно учитывать `ulimit -u` (max user processes)
- **JVM GC:** Больше потоков = больше объектов в heap = больше работы для GC
- **Disk I/O:** Больше `num.io.threads` может увеличить I/O wait на медленных дисках

### Чек-лист для production

- [ ] `num.network.threads` >= 4
- [ ] `num.io.threads` >= 8
- [ ] `num.replica.fetchers` >= 2
- [ ] `queued.max.requests` >= 500
- [ ] Мониторинг `RequestHandlerAvgIdlePercent` настроен
- [ ] Thread dump анализируется при проблемах с latency

### См. также
- **[JVM и GC тюнинг](./kafka_jvm_gc_tuning.md)** — настройки JVM
- **[OS тюнинг](./kafka_os_tuning.md)** — настройки ядра Linux
- **[ISR и репликация](./kafka_isr_replication.md)** — потоки репликации
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — JMX-метрики
