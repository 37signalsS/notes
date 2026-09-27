# RabbitMQ: Обзор клиентских библиотек

## Определения

- **AMQP 0-9-1:** Протокол, используемый RabbitMQ для обмена сообщениями. Большинство клиентских библиотек реализуют именно этот протокол.
- **Blocking Connection:** Синхронный режим подключения, где каждый вызов блокирует выполнение до получения ответа. Подходит для простых сценариев.
- **Asynchronous Connection:** Асинхронный режим подключения с использованием callback'ов или промисов. Подходит для высоконагруженных приложений.
- **Connection Pool:** Пул соединений для переиспользования TCP-подключений и снижения overhead на создание.
- **Channel:** Логическое соединение поверх TCP. Все операции AMQP выполняются в контексте канала.
- **Heartbeat:** Механизм обнаружения разорванных соединений. Клиент и сервер обмениваются heartbeat-сообщениями для подтверждения доступности.

## Обзор библиотек

### Python

| Библиотека | Тип | async | Описание |
|:---|:---|:---|:---|
| **pika** | Синхронный/async | Да (aio-pika) | Стандарт de facto для RabbitMQ в Python |
| **aio-pika** | Async | Да | Высокоуровневая обертка над pika для asyncio |
| **rabbitmq-client** | Async | Да | Асинхронный клиент с поддержкой Streams |

**pika (основная библиотека):**

```python
import pika

# Blocking connection
connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host='localhost',
        port=5672,
        credentials=pika.PlainCredentials('guest', 'guest'),
        heartbeat=600,
        blocked_connection_timeout=300
    )
)
channel = connection.channel()

# Объявление очереди
channel.queue_declare(queue='tasks', durable=True)

# Публикация
channel.basic_publish(
    exchange='',
    routing_key='tasks',
    body='Hello World',
    properties=pika.BasicProperties(
        delivery_mode=2,
        content_type='text/plain'
    )
)

# Потребление
def callback(ch, method, properties, body):
    print(f"Получено: {body.decode()}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue='tasks', on_message_callback=callback)
channel.start_consuming()
```

**aio-pika (async):**

```python
import asyncio
import aio_pika

async def main():
    # Async connection
    connection = await aio_pika.connect_robust(
        "amqp://guest:guest@localhost/"
    )
    
    async with connection:
        channel = await connection.channel()
        
        # Объявление очереди
        queue = await channel.declare_queue('tasks', durable=True)
        
        # Публикация
        await channel.default_exchange.publish(
            aio_pika.Message(body=b'Hello Async World'),
            routing_key='tasks'
        )
        
        # Потребление
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    print(f"Получено: {message.body.decode()}")

asyncio.run(main())
```

### Go

| Библиотека | Описание |
|:---|:---|
| **amqp091-go** | Официальная библиотека (fork goamq) |
| **rabbitmq/boom** | Высокоуровневая обертка с pool |

```go
package main

import (
    "fmt"
    "log"
    amqp "github.com/rabbitmq/amqp091-go"
)

func main() {
    // Подключение
    conn, err := amqp.Dial("amqp://guest:guest@localhost:5672/")
    if err != nil {
        log.Fatal(err)
    }
    defer conn.Close()

    // Канал
    ch, err := conn.Channel()
    if err != nil {
        log.Fatal(err)
    }
    defer ch.Close()

    // Объявление очереди
    q, err := ch.QueueDeclare(
        "tasks",  // имя
        true,     // durable
        false,    // autoDelete
        false,    // exclusive
        false,    // noWait
        nil,      // args
    )
    if err != nil {
        log.Fatal(err)
    }

    // Публикация
    body := "Hello Go"
    err = ch.Publish(
        "",     // exchange
        q.Name, // routing key
        false,  // mandatory
        false,  // immediate
        amqp.Publishing{
            DeliveryMode: amqp.Persistent,
            ContentType:  "text/plain",
            Body:         []byte(body),
        })
    if err != nil {
        log.Fatal(err)
    }

    // Потребление
    msgs, err := ch.Consume(
        q.Name,  // queue
        "",      // consumer
        false,   // autoAck
        false,   // exclusive
        false,   // noLocal
        false,   // noWait
        nil,     // args
    )
    if err != nil {
        log.Fatal(err)
    }

    forever := make(chan bool)
    go func() {
        for d := range msgs {
            fmt.Printf("Получено: %s\n", d.Body)
            d.Ack(false)
        }
    }()
    <-forever
}
```

### Node.js

| Библиотека | Тип | Описание |
|:---|:---|:---|
| **amqplib** | Callback/Promise | Стандартная библиотека |
| **rascal** | Высокоуровневая | С built-in retry/reconnect |

```javascript
const amqp = require('amqplib');

async function main() {
    // Подключение
    const connection = await amqp.connect('amqp://guest:guest@localhost/');
    const channel = await connection.createChannel();

    // Объявление очереди
    const queue = 'tasks';
    await channel.assertQueue(queue, { durable: true });

    // Публикация
    const msg = 'Hello Node.js';
    channel.sendToQueue(queue, Buffer.from(msg), {
        persistent: true,
        contentType: 'application/json'
    });

    // Потребление
    channel.consume(queue, (msg) => {
        console.log(`Получено: ${msg.content.toString()}`);
        channel.ack(msg);
    });

    console.log('Ожидание сообщений...');
}

main();
```

### Java

| Библиотека | Описание |
|:---|:---|
| **RabbitMQ Java Client** | Официальная библиотека |
| **Spring AMQP** | Интеграция со Spring |

```java
import com.rabbitmq.client.*;

public class RabbitMQExample {
    private final static String QUEUE_NAME = "tasks";

    public static void main(String[] args) throws Exception {
        // Подключение
        ConnectionFactory factory = new ConnectionFactory();
        factory.setHost("localhost");
        factory.setCredentials("guest", "guest");
        
        Connection connection = factory.newConnection();
        Channel channel = connection.createChannel();

        // Объявление очереди
        channel.queueDeclare(QUEUE_NAME, true, false, false, null);

        // Публикация
        String message = "Hello Java";
        channel.basicPublish(
            "",
            QUEUE_NAME,
            MessageProperties.PERSISTENT_TEXT_PLAIN,
            message.getBytes("UTF-8")
        );

        // Потребление
        DeliverCallback deliverCallback = (consumerTag, delivery) -> {
            String msg = new String(delivery.getBody(), "UTF-8");
            System.out.println("Получено: " + msg);
            channel.basicAck(delivery.getEnvelope().getDeliveryTag(), false);
        };
        
        channel.basicConsume(QUEUE_NAME, false, deliverCallback, consumerTag -> {});
    }
}
```

### .NET (C#)

| Библиотека | Описание |
|:---|:---|
| **RabbitMQ.Client** | Официальная библиотека |
| **MassTransit** | Высокоуровневый фреймворк |

```csharp
using RabbitMQ.Client;
using System.Text;

var factory = new ConnectionFactory { HostName = "localhost" };

using var connection = factory.CreateConnection();
using var channel = connection.CreateModel();

// Объявление очереди
channel.QueueDeclare(
    queue: "tasks",
    durable: true,
    exclusive: false,
    autoDelete: false,
    arguments: null
);

// Публикация
var body = Encoding.UTF8.GetBytes("Hello C#");
channel.BasicPublish(
    exchange: "",
    routingKey: "tasks",
    basicProperties: new BasicProperties { Persistent = true },
    body: body
);

// Потребление
var consumer = new EventingBasicConsumer(channel);
consumer.Received += (model, ea) =>
{
    var body = ea.Body.ToArray();
    var message = Encoding.UTF8.GetString(body);
    Console.WriteLine($"Получено: {message}");
    channel.BasicAck(ea.DeliveryTag, multiple: false);
};

channel.BasicConsume(
    queue: "tasks",
    autoAck: false,
    consumer: consumer
);
```

## Интеграция с Kubernetes

### RabbitMQ Cluster Operator

Рекомендуемый способ развертывания RabbitMQ в Kubernetes:

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: RabbitmqCluster
metadata:
  name: rabbitmq
  namespace: rabbitmq
spec:
  replicas: 3
  image: rabbitmq:3.12-management
  persistence:
    storageClassName: fast
    storage: 10Gi
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "2"
      memory: 2Gi
```

### KEDA (Kubernetes Event-driven Autoscaling)

Автомасштабирование consumer'ов по длине очереди:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: rabbitmq-consumer
  namespace: rabbitmq
spec:
  scaleTargetRef:
    name: consumer-deployment
  minReplicaCount: 1
  maxReplicaCount: 20
  triggers:
    - type: rabbitmq
      metadata:
        host: amqp://guest:guest@rabbitmq.rabbitmq.svc.cluster.local
        queueName: tasks
        queueLength: "10"
        mode: QueueLength
```

### Helm Chart

Официальный чарт для развертывания:

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm install rabbitmq bitnami/rabbitmq \
  --set auth.username=admin \
  --set auth.password=secret \
  --set persistence.size=10Gi
```

### Паттерн Worker Queue в Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
spec:
  replicas: 5
  selector:
    matchLabels:
      app: worker
  template:
    metadata:
      labels:
        app: worker
    spec:
      containers:
        - name: worker
          image: my-worker:latest
          env:
            - name: RABBITMQ_HOST
              value: "rabbitmq.rabbitmq.svc.cluster.local"
            - name: RABBITMQ_QUEUE
              value: "tasks"
```

## Сравнение библиотек

| Характеристика | Python (pika) | Go (amqp091-go) | Node.js (amqplib) | Java (RabbitMQ Client) |
|:---|:---|:---|:---|:---|
| **Производительность** | Средняя | Высокая | Средняя | Высокая |
| **Async поддержка** | aio-pika | Нативная | Нативная | CompletableFuture |
| **Connection pooling** | Вручную | rascal/amqp-pool | Вручную | Вручную |
| **Heartbeat** | Да | Да | Да | Да |
| **TLS** | Да | Да | Да | Да |
| **Publisher Confirms** | Да | Да | Да | Да |
| **Consumer Prefetch** | Да | Да | Да | Да |
| **Auto-reconnect** | aio-pika | rascal | rascal | Spring AMQP |

## Connection Pooling

### Python (connection pool)

```python
from pika import BlockingConnection, ConnectionParameters
from queue import Queue
from threading import Lock

class RabbitMQPool:
    def __init__(self, max_size=10, **kwargs):
        self.pool = Queue(maxsize=max_size)
        self.lock = Lock()
        self.params = ConnectionParameters(**kwargs)
        
        for _ in range(max_size):
            conn = BlockingConnection(self.params)
            self.pool.put(conn)
    
    def get_connection(self):
        return self.pool.get()
    
    def return_connection(self, conn):
        self.pool.put(conn)

# Использование
pool = RabbitMQPool(
    host='localhost',
    max_size=5
)

conn = pool.get_connection()
try:
    channel = conn.channel()
    # Работа с каналом
finally:
    pool.return_connection(conn)
```

### Go (connection pool)

```go
import (
    "github.com/wagslane/go-rabbitmq"
)

// Go-rabbitmq имеет встроенный connection pool
consumer, err := rabbitmq.NewConsumer(
    "amqp://guest:guest@localhost:5672/",
    rabbitmq.WithConsumerName("my-consumer"),
    rabbitmq.WithConcurrency(10),
)
defer consumer.Close()
```

## Retry и Reconnect

### Python (retry с exponential backoff)

```python
import pika
import time
from functools import wraps

def retry_on_failure(max_retries=5, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except pika.exceptions.AMQPConnectionError as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay}s")
                    time.sleep(delay)
        return wrapper
    return decorator

@retry_on_failure(max_retries=5)
def publish_message(channel, queue, message):
    channel.basic_publish(
        exchange='',
        routing_key=queue,
        body=message,
        properties=pika.BasicProperties(delivery_mode=2)
    )
```

### Go (reconnect)

```go
import (
    "github.com/wagslane/go-rabbitmq"
)

// go-rabbitmq автоматически переподключается
publisher, err := rabbitmq.NewPublisher(
    "amqp://guest:guest@localhost:5672/",
    rabbitmq.WithPublisherOptionsWithExchangeOpts(
        rabbitmq.WithExchangeDeclareOptions(
            rabbitmq.WithExchangeDurable(),
        ),
    ),
    rabbitmq.WithPublisherOptionsWithConfirmation(true),
)
defer publisher.Close()
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Connection closed` | Heartbeat timeout | Увеличьте `heartbeat` или проверьте сеть |
| `Channel closed` | Ошибка в consumer'е | Обработайте исключения в callback |
| `Already closed` | Повторное использование | Проверяйте `is_open` перед операциями |
| `Memory pressure` | Слишком много каналов | Используйте connection pool |
| `Blocking connection timeout` | Долгая операция | Используйте async connection |

## Лучшие практики

1. **Используйте async** — для production приложений с высокой нагрузкой.
2. **Настраивайте heartbeat** — рекомендуется 30-60 секунд.
3. **Используйте connection pooling** — переиспользуйте TCP-соединения.
4. **Реализуйте retry** — с exponential backoff при переподключении.
5. **Обрабатывайте channel.close** — в consumer'ах и producer'ах.
6. **Используйте durable queues** — для критичных данных.
7. **Устанавливайте prefetch_count** — для контроля нагрузки.
8. **Используйте Publisher Confirms** — для гарантий доставки.
9. **Закрывайте соединения** — в finally/block/defer.
10. **Мониторьте соединения** — через Prometheus метрики.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции.
- **[Паттерны сообщений](./message_patterns.md)** — Request/Reply, properties.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика проблем с клиентами.
- **[Безопасность](./security.md)** — TLS, аутентификация клиентов.
