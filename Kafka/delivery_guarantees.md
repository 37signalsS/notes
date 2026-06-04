# Гарантии доставки в очередях сообщений

## Определения

**Гарантии доставки** — фундаментальная концепция в мире брокеров сообщений, определяющая компромисс между надёжностью и производительностью.

- **At-most-once (не более одного раза)** — сообщение доставляется 0 или 1 раз. При сбоях возможны потери, но дубликаты исключены. Основной приоритет: минимальная задержка.
- **At-least-once (не менее одного раза)** — сообщение гарантированно будет доставлено 1 или более раз. Потери исключены, но возможны дубликаты. Требует идемпотентности на стороне потребителя.
- **Exactly-once (ровно один раз)** — каждое сообщение влияет на состояние системы ровно один раз. Достигается комбинацией идемпотентности, транзакций и специальных механизмов брокера. Обеспечивает строгую консистентность.

## Основные концепции

### Сравнительная таблица семантик

| Гарантия | Риск потери | Риск дубликатов | Нагрузка / Латентность | Типичные сценарии |
| :--- | :--- | :--- | :--- | :--- |
| **At-most-once** | Да | Нет | Минимальная | Сбор некритичных метрик, телеметрия. |
| **At-least-once** | Нет | Да | Средняя | Обработка заказов, биллинг с идемпотентностью. |
| **Exactly-once** | Нет | Нет | Высокая | Финансовые транзакции, критические пайплайны. |

### Реализация в RabbitMQ

**At-most-once:**

- **Продьюсер**: Отправка без ожидания подтверждения (`publisher confirms` выключен).
- **Консьюмер**: `auto_ack=true`. Брокер считает сообщение доставленным сразу после отправки.

**At-least-once:**

- **Продьюсер**: Использует подтверждения (`publisher confirms`) для гарантии доставки до брокера.
- **Консьюмер**: `auto_ack=false` (ручное подтверждение). `ack` отправляется только после успешной обработки.

**Exactly-once:**
RabbitMQ не обеспечивает семантику «ровно один раз» на уровне брокера. Гарантия реализуется на прикладном уровне:

- Дедупликация по уникальному ключу сообщения (`Message ID`).
- Паттерн **Outbox** для атомарного обновления БД и отправки сообщения.

### Реализация в Kafka

**At-most-once:**

- **Консьюмер**: Фиксация (коммит) смещения (offset) происходит *до* обработки сообщения.

**At-least-once:**

- **Продьюсер**: `enable.idempotence=true` для исключения дублей при повторных попытках отправки.
- **Консьюмер**: Коммит оффсета выполняется *после* успешной обработки.

**Exactly-once (EOS — Exactly-once semantics):**
Достигается в сценариях «чтение-обработка-запись» (`read-process-write`) через:

1. **Идемпотентный продюсер**: `enable.idempotence=true`.
2. **Транзакции**: Продюсер оборачивает цикл обработки в транзакцию.
3. **Атомарный коммит**: Новые сообщения и оффсеты прочитанных сообщений фиксируются в рамках одной транзакции.

- **Настройка**: `acks=all`, `transactional.id` (уникальный), `isolation.level=read_committed`.

## Практические сценарии

### RabbitMQ: Потребитель с гарантией At-least-once

```python
import pika

conn = pika.BlockingConnection(pika.ConnectionParameters('mq'))
ch = conn.channel()
ch.basic_qos(prefetch_count=1)

def handle(ch, method, properties, body):
    try:
        process(body) # Идемпотентная функция обработки
        # Подтверждение только после успеха
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        # Сообщение вернется в очередь для повторной попытки
        # Или будет отправлено в DLQ (Dead Letter Queue) при настройке
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

ch.basic_consume(queue='tasks', on_message_callback=handle, auto_ack=False)
ch.start_consuming()
```

### Kafka: Обработка ровно один раз (Exactly-once)

```python
from confluent_kafka import Producer, Consumer

# Продюсер с транзакциями
producer = Producer({
    'bootstrap.servers': 'kafka:9092',
    'enable.idempotence': True,
    'acks': 'all',
    'transactional.id': 'app-1'
})
producer.init_transactions()

# Консьюмер с чтением только зафиксированных данных
consumer = Consumer({
    'bootstrap.servers': 'kafka:9092',
    'group.id': 'group-1',
    'enable.auto.commit': False,
    'isolation.level': 'read_committed'
})
consumer.subscribe(['input-topic'])

while True:
    msg = consumer.poll(1.0)
    if not msg: continue
    
    producer.begin_transaction()
    try:
        res = transform(msg.value())
        producer.produce('output-topic', value=res)
        
        # Коммит оффсета вместе с результатом обработки
        producer.send_offsets_to_transaction(
            [consumer.position(msg.topic(), msg.partition())],
            consumer.consumer_group_metadata()
        )
        producer.commit_transaction()
    except Exception:
        producer.abort_transaction()
```

## Дополнительная информация

### См. также

- **[Принципы работы очередей сообщений](./message_queues_principles.md)** — базовые концепции и терминология.
- **[Сравнение RabbitMQ и Kafka](./rabbitmq_vs_kafka.md)** — архитектурные различия Push и Pull моделей.
- **[Партиционирование в Kafka](./partitioning_and_balancing.md)** — механизмы масштабирования и обеспечения порядка.

### Термины

- **DLQ (Dead Letter Queue)** — специальная очередь для сообщений, которые не удалось успешно обработать.
- **Offset (смещение)** — уникальный идентификатор позиции сообщения в партиции Kafka.
- **Acknowledgement (ack)** — сигнал подтверждения успешной обработки сообщения.
