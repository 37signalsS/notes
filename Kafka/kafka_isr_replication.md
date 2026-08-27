# ISR и репликация в Apache Kafka

**ISR (In-Sync Replicas)** — это набор реплик, которые синхронизированы с лидером партиции. Механизм ISR обеспечивает баланс между доступностью и долговечностью данных, позволяя брокеру принимать решения о записи и чтении на основе состояния реплик.

---

## Определения

- **ISR (In-Sync Replicas):** Список реплик (включая лидера), которые полностью синхронизированы с лидером. Только реплики из ISR могут быть выбраны новым лидером.
- **HW (High Watermark):** Офсет последнего сообщения, которое было успешно реплицировано на все ISR. Консьюмеры читают только до HW.
- **LEO (Log End Offset):** Офсет последнего сообщения, записанного в лог реплики (включая незакоммиченные).
- **Replica Lag:** Разница между HW лидера и LEO реплики. Показывает, насколько реплика отстаёт.
- **Unclean Leader Election:** Выбор лидера из реплик, не входящих в ISR. Может привести к потере данных.
- **min.insync.replicas:** Минимальное количество синхронных реплик, необходимое для успешной записи при `acks=all`.
- **replica.lag.time.max.ms:** Максимальное время, в течение которого реплика может не запрашивать данные у лидера, прежде чем быть исключена из ISR.
- **ISR Shrink:** Уменьшение списка ISR (реплика отстаёт и исключается).
- **ISR Expand:** Увеличение списка ISR (реплика догоняет и включается обратно).

---

## Основные концепции

### Механизм ISR

```
┌─────────────────────────────────────────────────────────────┐
│                    Partition 0 (RF=3)                        │
├─────────────────────────────────────────────────────────────┤
│  Leader (Broker 1)                                          │
│  ├── LEO: 100                                               │
│  ├── HW: 95                                                 │
│  └── ISR: [1, 2, 3]                                        │
├─────────────────────────────────────────────────────────────┤
│  Follower (Broker 2)                                        │
│  ├── LEO: 98 (отставание: 2)                               │
│  └── Статус: ISR                                           │
├─────────────────────────────────────────────────────────────┤
│  Follower (Broker 3)                                        │
│  ├── LEO: 95 (отставание: 5)                               │
│  └── Статус: ISR                                           │
└─────────────────────────────────────────────────────────────┘
```

**Правила ISR:**
1. Реплика входит в ISR, если она регулярно запрашивает данные у лидера (в пределах `replica.lag.time.max.ms`)
2. Реплика исключается из ISR, если отстаёт больше, чем `replica.lag.time.max.ms`
3. Реплика может вернуться в ISR, если догоняет лидера

### Взаимодействие acks и ISR

| Настройка | Поведение | Риск потери данных |
|-----------|-----------|-------------------|
| `acks=0` | Продюсер не ждёт подтверждения | Высокий |
| `acks=1` | Продюсер ждёт только лидера | Средний (сбой лидера до репликации) |
| `acks=all` + `min.insync.replicas=1` | Продюсер ждёт все ISR, но ISR может содержать только лидера | Средний |
| `acks=all` + `min.insync.replicas=2` | Продюсер ждёт минимум 2 реплики | Низкий |

**Критический сценарий:**
- RF=3, `min.insync.replicas=2`, `acks=all`
- Если 2 реплики падают, ISR сокращается до 1 (только лидер)
- Продюсер получает `NotEnoughReplicasException`, так как `min.insync.replicas=2` не выполнен
- Данные не теряются, но запись останавливается

### Unclean Leader Election

**Проблема:** Если все реплики из ISR упали, а `unclean.leader.election.enable=true`, то лидером может стать реплика, не входящая в ISR (отстающая).

**Последствия:**
- Потеря данных, которые были на старом лидере, но не реплицированы
- Нарушение порядка сообщений

**Рекомендация:** В production всегда `unclean.leader.election.enable=false`.

### Параметры репликации

| Параметр | Значение по умолчанию | Рекомендуемое | Описание |
|----------|----------------------|---------------|----------|
| `replica.lag.time.max.ms` | 30000 | 10000-30000 | Максимальное время без fetch запросов |
| `replica.fetch.max.bytes` | 1048576 (1MB) | 4194304 (4MB) | Максимальный размер fetch ответа |
| `replica.fetch.wait.max.ms` | 500 | 100-500 | Максимальное время ожидания данных |
| `replica.fetch.min.bytes` | 1 | 1-1024 | Минимальный размер данных для ответа |
| `num.replica.fetchers` | 1 | 2-4 | Потоки репликации |

### Диагностика ISR проблем

**Симптомы ISR shrink:**
- Метрика `UnderReplicatedPartitions > 0`
- Логи: `Partition [topic-0] ... is no longer in sync`
- Рост `ISRShrinkRate` в JMX

**Причины ISR shrink:**
1. Медленные диски на follower'е
2. Проблемы с сетью между брокерами
3. Высокая нагрузка на CPU follower'а
4. Неправильные настройки `replica.lag.time.max.ms`

---

## Практические сценарии

### Сценарий 1: Настройка для максимальной надёжности

```properties
# Требовать подтверждение от всех реплик
acks=all

# Минимум 2 реплики должны быть в ISR
min.insync.replicas=2

# Запретить unclean leader election
unclean.leader.election.enable=false

# Увеличить фактор репликации
default.replication.factor=3
```

### Сценарий 2: Диагностика ISR shrink

```bash
# 1. Проверка текущего состояния ISR
kafka-topics.sh --bootstrap-server localhost:9092 \
  --topic my-topic --describe

# 2. Проверка метрик
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions" \
  --one-time true

# 3. Проверка логов брокера
grep "is no longer in sync" /var/log/kafka/server.log

# 4. Проверка задержки репликации
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica" \
  --one-time true
```

### Сценарий 3: Оптимизация для медленных дисков

Если follower'ы отстают из-за медленных дисков:
```properties
# Увеличить время ожидания
replica.lag.time.max.ms=60000

# Увеличить потоки репликации
num.replica.fetchers=4

# Увеличить размер fetch ответа
replica.fetch.max.bytes=4194304
```

### Сценарий 4: Восстановление после ISR shrink

Если реплика исключена из ISR, но диск цел:
1. Проверить сеть между брокерами
2. Проверить I/O на follower'е (`iostat -x 1`)
3. Увеличить `replica.lag.time.max.ms` временно
4. Дождаться автоматического возврата в ISR (метрика `IsrExpandRate`)

### Сценарий 5: Настройка для cross-DC репликации

Для MirrorMaker 2 между дата-центрами:
```properties
# Увеличить таймауты для высокой задержки
replica.lag.time.max.ms=120000
replica.fetch.wait.max.ms=1000

# Увеличить размер пакетов
replica.fetch.max.bytes=8388608
```

---

## Дополнительная информация

### Мониторинг ISR

Ключевые JMX-метрики:
- `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` — количество недостаточно реплицированных партиций
- `kafka.server:type=ReplicaManager,name=IsrShrinkRate` — скорость сокращения ISR
- `kafka.server:type=ReplicaManager,name=IsrExpandRate` — скорость расширения ISR
- `kafka.server:type=ReplicaFetcherManager,name=MaxLag,clientId=Replica` — максимальная задержка репликации

**Алерты:**
- `UnderReplicatedPartitions > 0` в течение > 5 минут → проблема с репликацией
- `IsrShrinkRate > 0` → реплики отстают

### Связь с другими настройками

- **Thread Model:** `num.replica.fetchers` влияет на скорость репликации
- **OS Tuning:** Сетевые буферы влияют на скорость fetch запросов
- **Disk I/O:** Медленные диски вызывают ISR shrink

### Чек-лист для production

- [ ] `min.insync.replicas=2` для критичных топиков
- [ ] `unclean.leader.election.enable=false`
- [ ] `default.replication.factor=3`
- [ ] Мониторинг `UnderReplicatedPartitions` настроен
- [ ] `replica.lag.time.max.ms` настроен под нагрузку
- [ ] `num.replica.fetchers` >= 2

### См. также
- **[Партиционирование и балансировка](./partitioning_and_balancing.md)** — репликация и лидеры
- **[Гарантии доставки](./delivery_guarantees.md)** — acks и надёжность
- **[Thread Model](./kafka_broker_thread_model.md)** — потоки репликации
- **[Мониторинг Kafka](./kafka_for_monitoring.md)** — JMX-метрики
