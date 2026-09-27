# RabbitMQ: Single Active Consumer (Один активный консьюмер)

## Определения

- **Single Active Consumer (SAC):** Паттерн, при котором только один потребитель активен и обрабатывает сообщения из очереди в любой момент времени. Другие потребители находятся в standby-режиме и готовы взять на себя обработку при падении основного.
- **Exclusive Consumer:** Эксклюзивный потребитель, который единственный подключен к очереди. В отличие от SAC, при его падении очередь остается без потребителей до ручного переподключения.
- **Consumer Tag:** Уникальный идентификатор потребителя, используемый брокером для отслеживания активных подключений.
- **Failover:** Процесс автоматического переключения на резервный потребитель при отказе основного.

## Основные концепции

### Зачем нужен Single Active Consumer

В стандартной модели RabbitMQ несколько потребителей получают сообщения из одной очереди (round-robin). Однако есть сценарии, где параллельная обработка нежелательна:

- **Порядок сообщений:** Гарантия обработки в порядке поступления.
- **Идемпотентность:** Избежание дублирования операций при параллельной обработке.
- **Ресурсоемкие задачи:** Когда обработка требует эксклюзивного доступа к ресурсам (БД, файловая система).
- **Stateful обработка:** Когда состояние зависит от предыдущего сообщения.

### Реализация в RabbitMQ

RabbitMQ **не имеет встроенного** Single Active Consumer на уровне брокера (в отличие от Kafka consumer groups). Паттерн реализуется на стороне клиента или через плагины.

**Варианты реализации:**

| Вариант | Механизм | Гарантия |
|:---|:---|:---|
| **Exclusive Queue** | Очередь с флагом `exclusive=True` | Только одно подключение к очереди |
| **Client-side locking** | Распределенная блокировка (Redis, etcd, ZooKeeper) | Failover через heartbeat |
| **RabbitMQ Streams SAC** | Встроенный в Streams (active consumer election) | Автоматический failover |

### Exclusive Queue vs Single Active Consumer

| Характеристика | Exclusive Queue | Single Active Consumer |
|:---|:---|:---|
| **Количество потребителей** | Только 1 (ограничение брокера) | 1 активный + N standby |
| **Failover** | Ручной (клиент переподключается) | Автоматический |
| **Доступность** | Низкая (нет резервного) | Высокая (резервные готовы) |
| **Использование** | Простые сценарии | Production с требованиями HA |

## Практические сценарии

### 1. Exclusive Queue (простейший вариант)

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Объявление exclusive очереди
channel.queue_declare(
    queue='exclusive_tasks',
    exclusive=True  # Только одно подключение
)

def callback(ch, method, properties, body):
    print(f"Обработка: {body.decode()}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue='exclusive_tasks', on_message_callback=callback)
print('Ожидание сообщений (exclusive mode)...')
channel.start_consuming()
```

**Ограничение:** При падении потребителя очередь удаляется, и сообщения теряются (если не настроен DLX).

### 2. Single Active Consumer с Redis (distributed lock)

```python
import pika
import redis
import time
import uuid

class SingleActiveConsumer:
    def __init__(self, redis_host='localhost', amqp_host='localhost'):
        self.consumer_id = str(uuid.uuid4())
        self.redis_client = redis.Redis(host=redis_host, decode_responses=True)
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters(amqp_host)
        )
        self.channel = self.connection.channel()
        self.lock_key = 'rabbitmq_sac_lock'
        self.lock_ttl = 30  # секунд
        
    def acquire_lock(self):
        """Попытка захватить блокировку"""
        return self.redis_client.set(
            self.lock_key,
            self.consumer_id,
            nx=True,
            ex=self.lock_ttl
        )
    
    def renew_lock(self):
        """Продление блокировки"""
        if self.redis_client.get(self.lock_key) == self.consumer_id:
            self.redis_client.expire(self.lock_key, self.lock_ttl)
            return True
        return False
    
    def consume(self):
        def callback(ch, method, properties, body):
            if self.renew_lock():
                try:
                    print(f"[{self.consumer_id}] Обработка: {body.decode()}")
                    # Имитация обработки
                    time.sleep(1)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            else:
                print(f"[{self.consumer_id}] Потеря блокировки, пропуск сообщения")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        
        self.channel.basic_qos(prefetch_count=1)
        self.channel.basic_consume(
            queue='distributed_tasks',
            on_message_callback=callback
        )
        
        # Периодическая проверка блокировки
        while True:
            if self.acquire_lock():
                print(f"[{self.consumer_id}] Активный消费者")
                self.channel.start_consuming()
            else:
                print(f"[{self.consumer_id}] Резервный消费者")
                time.sleep(5)  # Проверка каждые 5 секунд

# Запуск
consumer = SingleActiveConsumer()
consumer.consume()
```

### 3. Single Active Consumer через RabbitMQ Streams

RabbitMQ Streams имеют встроенный механизм Single Active Consumer:

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Объявление stream queue
channel.queue_declare(
    queue='orders_stream',
    arguments={
        'x-queue-type': 'stream',
        'x-single-active-consumer': True,  # Встроенный SAC
        'x-stream-offset': 'first'
    }
)

def callback(ch, method, properties, body):
    print(f"Обработка: {body.decode()}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(
    queue='orders_stream',
    on_message_callback=callback
)

print('Ожидание сообщений (stream SAC)...')
channel.start_consuming()
```

### 4. Мониторинг Single Active Consumer

```bash
# Проверка потребителей очереди
sudo rabbitmqctl list_consumers queue_name channel consumer_tag
# → orders_stream  <rabbit@node1.1.2.3>  sac-consumer-1

# Проверка exclusive очередей
sudo rabbitmqadmin list queues name exclusive owner_pid
# → exclusive_tasks  true  <rabbit@node1.1.2.3.4.5>

# Проверка через Management API
curl -s -u guest:guest http://localhost:15672/api/queues | \
  jq '.[] | select(.exclusive == true) | {name, exclusive, owner_pid}'
```

### 5. Failover с Kubernetes (Leader Election)

Для Kubernetes используйте leader election через Lease:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rabbitmq-consumer
spec:
  replicas: 3  # 1 активный + 2 standby
  selector:
    matchLabels:
      app: consumer
  template:
    metadata:
      labels:
        app: consumer
    spec:
      containers:
        - name: consumer
          image: my-consumer:latest
          env:
            - name: LEADER_ELECTION
              value: "true"
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
```

```python
# Leader election через Kubernetes Lease
from kubernetes import client, config
import os

config.load_incluster_config()
coordination_api = client.CoordinationV1Api()
lease_name = "rabbitmq-consumer-leader"

def try_acquire_lease():
    try:
        lease = coordination_api.read_namespaced_lease(lease_name, "default")
        # Проверка текущего лидера
        if lease.spec.holder_identity == os.environ['POD_NAME']:
            return True
    except client.exceptions.ApiException:
        pass
    
    # Попытка захватить lease
    lease = client.V1Lease(
        metadata=client.V1ObjectMeta(name=lease_name),
        spec=client.V1LeaseSpec(
            holder_identity=os.environ['POD_NAME'],
            lease_duration_seconds=15
        )
    )
    try:
        coordination_api.create_namespaced_lease("default", lease)
        return True
    except client.exceptions.ApiException:
        return False
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Два активных потребителя одновременно | Отсутствие distributed lock | Используйте Redis/etcd для блокировки |
| Очередь удаляется при падении | Exclusive queue без DLX | Настройте DLX или используйте non-exclusive queue |
| Failover не срабатывает | Слишком длинный heartbeat | Уменьшите `heartbeat` в `ConnectionParameters` |
| Потеря сообщений при failover | Нет requeue при потере блокировки | Используйте `basic_nack(requeue=True)` |

## Лучшие практики

1. **Используйте RabbitMQ Streams** для SAC — встроенный механизм с автоматическим failover.
2. **Настройте heartbeat** — рекомендуется 30-60 секунд для быстрого обнаружения падения.
3. **Реализуйте graceful shutdown** — потребитель должен освобождать блокировку перед завершением.
4. **Мониторьте количество потребителей** — алерт при изменении с 1 на 0.
5. **Используйте DLX** — для обработки сообщений при недоступности потребителя.
6. **Для critical systems** комбинируйте SAC с Publisher Confirms для полных гарантий.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции очередей и consumer'ов.
- **[Приоритетные очереди](./priority_queues.md)** — комбинирование SAC с приоритетами.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика проблем с потребителями.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — мониторинг consumer'ов.
