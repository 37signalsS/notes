# Troubleshooting Playbook для Apache Kafka

**Troubleshooting Playbook** — это структурированный алгоритм диагностики и решения проблем в production-кластере Kafka. Включает decision trees для типичных сценариев и команды для быстрой локализации неисправностей.

---

## Определения

- **Decision Tree:** Алгоритм диагностики с последовательными проверками и ветвлениями.
- **Poison Pill:** Сообщение, которое вызывает ошибку десериализации и блокирует обработку партиции.
- **Hot Key:** Ключ с аномально высокой частотой, вызывающий перекос нагрузки.
- **Consumer Lag:** Разница между последним записанным офсетом (log end offset) и последним обработанным офсетом консьюмера.
- **ISR Shrink:** Уменьшение списка синхронных реплик.
- **Thread Starvation:** Недостаток потоков для обработки запросов.
- **Split-Brain:** Ситуация, когда два брокера считают себя лидером одной партиции.

---

## Основные концепции

### Алгоритм диагностики

```
┌─────────────────────────────────────────────────────────────┐
│                    1. Определение симптома                   │
│  (Latency, Errors, Lag, Availability)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    2. Сбор метрик                            │
│  (JMX, Logs, OS metrics)                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    3. Локализация проблемы                   │
│  (Broker, Network, Client, Disk)                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    4. Применение решения                     │
│  (Config change, Restart, Scale)                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    5. Верификация                            │
│  (Метрики вернулись к норме)                                │
└─────────────────────────────────────────────────────────────┘
```

### Ключевые метрики для диагностики

| Метрика | Норма | Проблема |
|---------|-------|----------|
| `UnderReplicatedPartitions` | 0 | > 0 → проблемы с репликацией |
| `ActiveControllerCount` | 1 | > 1 → split-brain |
| `RequestHandlerAvgIdlePercent` | > 0.3 | < 0.3 → thread starvation |
| `NetworkProcessorAvgIdlePercent` | > 0.3 | < 0.3 → сетевые проблемы |
| `Consumer Lag` | стабильный | растёт → проблемы с консьюмером |
| `ISR Shrink Rate` | 0 | > 0 → реплики отстают |
| `Request Queue Time` | < 10ms | > 100ms → перегрузка |

### Команды для быстрой диагностики

```bash
# 1. Проверка состояния кластера
kafka-broker-api-versions.sh --bootstrap-server kafka:9092

# 2. Проверка топика
kafka-topics.sh --bootstrap-server kafka:9092 --topic my-topic --describe

# 3. Проверка consumer lag
kafka-consumer-groups.sh --bootstrap-server kafka:9092 --group my-group --describe

# 4. Проверка логов брокера
tail -f /var/log/kafka/server.log | grep -E "ERROR|WARN"

# 5. Thread dump
jstack $(pgrep -f kafka.Kafka) > /tmp/kafka-threaddump.txt

# 6. Heap dump (при подозрении на утечку)
jmap -dump:format=b,file=/tmp/heapdump.hprof $(pgrep -f kafka.Kafka)
```

---

## Практические сценарии

### Сценарий 1: Consumer Lag растёт

**Decision Tree:**
```
Consumer Lag растёт
    │
    ├── Проверить: все ли консьюмеры в группе активны?
    │   └── kafka-consumer-groups.sh --describe
    │       ├── Нет → проверить логи консьюмеров, перезапустить
    │       └── Да → следующий шаг
    │
    ├── Проверить: lag растёт на всех партициях или на одной?
    │   ├── На одной → Hot Key или Poison Pill
    │   │   ├── Hot Key → проверить распределение ключей
    │   │   └── Poison Pill → проверить десериализацию, DLQ
    │   └── На всех → следующий шаг
    │
    ├── Проверить: время обработки сообщения?
    │   └── Увеличилось → профилировать бизнес-логику
    │
    └── Проверить: консьюмер успевает за producer'ом?
        └── Нет → увеличить количество консьюмеров или партиций
```

**Команды:**
```bash
# Проверка распределения lag по партициям
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group my-group --describe | awk '{print $4, $5, $6}'

# Проверка hot key (пример)
kafka-run-class kafka.tools.DumpLogSegments \
  --files /kafka-data/my-topic-0/00000000000000000000.log \
  --print-data-log | awk -F ':' '{print $1}' | sort | uniq -c | sort -rn | head
```

### Сценарий 2: High Latency (Produce/Fetch)

**Decision Tree:**
```
Latency высокая
    │
    ├── Проверить: какая latency? (p50, p95, p99)
    │   └── p99 высокая, p50 норм → выбросы (GC, диск)
    │
    ├── Проверить: на каком брокере?
    │   └── На одном → проблемы с этим брокером (диск, сеть)
    │
    ├── Проверить: метрики брокера
    │   ├── RequestHandlerAvgIdlePercent < 0.3 → thread starvation
    │   ├── NetworkProcessorAvgIdlePercent < 0.3 → сетевые проблемы
    │   └── Request Queue Time > 100ms → перегрузка
    │
    ├── Проверить: OS метрики
    │   ├── iostat -x 1 → %util > 80% → диск перегружен
    │   ├── netstat -s → ретрансмиссии → сетевые проблемы
    │   └── vmstat 1 → si/so > 0 → swap (критично!)
    │
    └── Проверить: GC логи
        └── Длительные паузы → настроить GC или увеличить heap
```

**Команды:**
```bash
# Проверка дисков
iostat -x 1 5

# Проверка сети
netstat -s | grep -i retransmit

# Проверка swap
vmstat 1 5

# Проверка GC
grep "pause" /var/log/kafka/kafkaServer-gc.log | tail -20
```

### Сценарий 3: ISR Shrink

**Decision Tree:**
```
ISR Shrink
    │
    ├── Проверить: какая реплика отстаёт?
    │   └── kafka-topics.sh --describe
    │
    ├── Проверить: метрики реплики
    │   ├── ReplicaFetcherLag → высокий → медленный fetch
    │   └── ReplicaFetcherLag → 0 → реплика не запрашивает данные
    │
    ├── Проверить: сеть между брокерами
    │   └── ping, iperf3 между брокерами
    │
    ├── Проверить: диск на follower'е
    │   └── iostat -x 1 → %util, await
    │
    └── Проверить: настройки репликации
        └── replica.lag.time.max.ms слишком мал?
```

**Команды:**
```bash
# Проверка ISR
kafka-topics.sh --bootstrap-server kafka:9092 \
  --topic my-topic --describe | grep -E "Replicas|Isr"

# Проверка задержки репликации
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica" \
  --one-time true

# Проверка сети между брокерами
iperf3 -c follower-broker -t 10
```

### Сценарий 4: Broker Crash / OOM

**Decision Tree:**
```
Broker Crash
    │
    ├── Проверить: причина краха
    │   └── dmesg | grep -i "killed process" → OOM Killer
    │
    ├── Проверить: логи перед крахом
    │   └── /var/log/kafka/server.log | tail -100
    │
    ├── Проверить: heap dump
    │   └── jmap -histo:live <pid> | head -20
    │
    ├── Проверить: GC логи
    │   └── OutOfMemoryError: Java heap space → увеличить heap
    │   └── OutOfMemoryError: Metaspace → увеличить MaxMetaspaceSize
    │
    └── Проверить: утечку памяти
        └── jmap -dump:format=b,file=heap.hprof <pid>
        └── анализ с Eclipse MAT или VisualVM
```

**Команды:**
```bash
# Проверка OOM Killer
dmesg | grep -i "killed process"

# Проверка логов
grep -E "OutOfMemoryError|ERROR" /var/log/kafka/server.log | tail -50

# Анализ heap dump
jhat heap.hprof -port 7401
# Открыть http://localhost:7401
```

### Сценарий 5: Split-Brain (ActiveControllerCount > 1)

**Decision Tree:**
```
Split-Brain
    │
    ├── Проверить: сколько контроллеров?
    │   └── kafka-run-class kafka.tools.JmxTool \
    │       --object-name "kafka.controller:type=KafkaController,name=ActiveControllerCount"
    │
    ├── Проверить: сеть между брокерами
    │   └── сетевой разрыв (network partition)
    │
    ├── Решение: перезапустить один из брокеров-контроллеров
    │   └── предпочтительно тот, у которого меньше epoch
    │
    └── Профилактика: настроить proper fencing
        └── unclean.leader.election.enable=false
```

**Команды:**
```bash
# Проверка контроллеров
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.controller:type=KafkaController,name=ActiveControllerCount" \
  --one-time true

# Проверка epoch
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.controller:type=KafkaController,name=ControllerEpoch" \
  --one-time true
```

### Сценарий 6: Poison Pill (Consumer зависает)

**Decision Tree:**
```
Consumer зависает на одном сообщении
    │
    ├── Проверить: consumer lag на одной партиции
    │   └── kafka-consumer-groups.sh --describe
    │
    ├── Проверить: логи консьюмера
    │   └── ошибка десериализации
    │
    ├── Решение 1: пропустить сообщение
    │   └── увеличить max.poll.records, обработать ошибку
    │
    ├── Решение 2: DLQ
    │   └── отравленное сообщение в Dead Letter Queue
    │
    └── Решение 3: ручной skip
        └── коммит офсета вручную для проблемной партиции
```

**Команды:**
```bash
# Проверка lag на конкретной партиции
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group my-group --describe | awk '$2 == "partition_number" {print}'

# Ручной коммит офсета (опасно!)
kafka-consumer-groups.sh --bootstrap-server kafka:9092 \
  --group my-group --topic my-topic:partition --reset-offsets --to-offset 12345 --execute
```

### Сценарий 7: Disk Full

**Decision Tree:**
```
Disk Full
    │
    ├── Проверить: какой диск заполнен?
    │   └── df -h
    │
    ├── Проверить: что занимает место?
    │   └── du -sh /kafka-data/*
    │
    ├── Решение 1: увеличить retention (если данные не нужны)
    │   └── kafka-configs.sh --alter --entity-type topics --entity-name my-topic \
    │       --add-config retention.ms=86400000
    │
    ├── Решение 2: добавить диск
    │   └── добавить новый диск, переместить партиции
    │
    └── Решение 3: экстренная очистка
        └── удалить старые сегменты (опасно!)
```

**Команды:**
```bash
# Проверка диска
df -h /kafka-data

# Проверка размера топиков
du -sh /kafka-data/*

# Проверка retention
kafka-configs.sh --bootstrap-server kafka:9092 \
  --entity-type topics --entity-name my-topic --describe
```

---

## Дополнительная информация

### Чек-лист для быстрой диагностики

- [ ] Проверить `UnderReplicatedPartitions`
- [ ] Проверить `ActiveControllerCount`
- [ ] Проверить `RequestHandlerAvgIdlePercent`
- [ ] Проверить consumer lag
- [ ] Проверить логи брокера
- [ ] Проверить OS метрики (диск, сеть, CPU)
- [ ] Проверить GC логи

### Экстренные действия

| Проблема | Действие |
|----------|----------|
| Split-Brain | Перезапустить контроллер с меньшим epoch |
| OOM | Увеличить heap, проанализировать heap dump |
| Disk Full | Уменьшить retention или добавить диск |
| ISR Shrink | Проверить сеть и диски на follower'ах |
| Poison Pill | Отправить в DLQ или пропустить |

### Связь с другими настройками

- **[JVM и GC тюнинг](./kafka_jvm_gc_tuning.md)** — диагностика GC проблем
- **[OS тюнинг](./kafka_os_tuning.md)** — диагностика проблем с ОС
- **[Thread Model](./kafka_broker_thread_model.md)** — диагностика thread starvation
- **[ISR и репликация](./kafka_isr_replication.md)** — диагностика ISR проблем
- **[Мониторинг](./kafka_for_monitoring.md)** — метрики для диагностики

### См. также
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — JMX-метрики и алерты
- **[JVM и GC тюнинг](./kafka_jvm_gc_tuning.md)** — диагностика JVM
- **[OS тюнинг](./kafka_os_tuning.md)** — диагностика проблем с ОС
- **[ISR и репликация](./kafka_isr_replication.md)** — диагностика репликации
- **[Capacity Planning](./kafka_capacity_dr.md)** — планирование ёмкости
