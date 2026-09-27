# RabbitMQ: Паттерны обмена сообщениями и свойства сообщений

## Определения

- **Message Properties (Свойства сообщения):** Метаданные, сопровождающие тело сообщения. Задаются в `BasicProperties` при публикации и доступны потребителям для принятия решений.
- **Request-Reply (Запрос-Ответ):** Асинхронный паттерн, при котором клиент отправляет запрос в очередь и ожидает ответа на временной очереди, указанной в `reply_to`.
- **Correlation ID:** Уникальный идентификатор, связывающий запрос с ответом. Позволяет сопоставить ответ с исходным запросом при асинхронной обработке.
- **Routing Key:** Строка, используемая обменником для маршрутизации сообщения в очереди на основе правил (биндингов).
- **Message ID:** Уникальный идентификатор сообщения, используемый для дедупликации, трассировки и логирования.

## Основные концепции

### Message Properties (свойства сообщения)

RabbitMQ поддерживает следующие стандартные свойства AMQP 0-9-1:

| Свойство | Тип | Описание | Пример использования |
|:---|:---|:---|:---|
| `content_type` | string | MIME-тип тела сообщения | `application/json`, `text/plain` |
| `content_encoding` | string | Кодировка тела | `utf-8`, `base64` |
| `headers` | table | Произвольные заголовки (ключ-значение) | Метаданные приложения |
| `delivery_mode` | int8 | Режим доставки: 1 (transient), 2 (persistent) | Персистентные сообщения |
| `priority` | int8 | Приоритет сообщения (0-255) | Приоритетные очереди |
| `correlation_id` | string | ID для связки request-reply | Трассировка запросов |
| `reply_to` | string | Имя очереди ответа | Request-Reply паттерн |
| `expiration` | string | Время жизни сообщения (мс) | TTL для отдельных сообщений |
| `message_id` | string | Уникальный ID сообщения | Дедупликация, трассировка |
| `timestamp` | int64 | Unix timestamp публикации | Аудит, аналитика |
| `type` | string | Тип сообщения | Маршрутизация, обработка |
| `app_id` | string | ID приложения-продюсера | Идентификация источника |
| `user_id` | string | ID пользователя (проверяется брокером) | Аутентификация |

### Паттерн Request-Reply

Классический синхронный RPC через очереди:

```
Client                          Broker                          Server
  │                               │                               │
  │── publish(request) ──────────>│                               │
  │   properties:                 │                               │
  │     correlation_id: "abc"     │                               │
  │     reply_to: "reply.abc"     │                               │
  │                               │── deliver(request) ──────────>│
  │                               │                               │
  │                               │<── publish(reply) ───────────│
  │<── deliver(reply) ───────────│   properties:                 │
  │                               │     correlation_id: "abc"     │
  │                               │                               │
  │   Обработка ответа            │                               │
```

## Практические сценарии

### 1. Request-Reply (RPC) — полная реализация (Python)

```python
import pika
import uuid
import json
import time

class RpcClient:
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters('localhost')
        )
        self.channel = self.connection.channel()
        
        # Временная очередь для ответов
        result = self.channel.queue_declare(queue='', exclusive=True)
        self.callback_queue = result.method.queue
        
        self.channel.basic_consume(
            queue=self.callback_queue,
            on_message_callback=self.on_response
        )
        
        self.response = None
        self.corr_id = None
    
    def on_response(self, ch, method, props, body):
        if self.corr_id == props.correlation_id:
            self.response = json.loads(body)
    
    def call(self, request_data, timeout=30):
        self.response = None
        self.corr_id = str(uuid.uuid4())
        
        self.channel.basic_publish(
            exchange='',
            routing_key='rpc_queue',
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=self.corr_id,
                content_type='application/json',
                delivery_mode=2
            ),
            body=json.dumps(request_data)
        )
        
        # Ожидание ответа с таймаутом
        start_time = time.time()
        while self.response is None:
            self.connection.process_data_events(time_limit=1)
            if time.time() - start_time > timeout:
                raise TimeoutError(f"RPC timeout after {timeout}s")
        
        return self.response

# Клиент
rpc = RpcClient()
response = rpc.call({"action": "get_order", "order_id": 123})
print(f"Ответ: {response}")
```

### 2. RPC Server (обработчик)

```python
import pika
import json

def on_request(ch, method, props, body):
    request = json.loads(body)
    
    # Обработка запроса
    result = {
        "order_id": request["order_id"],
        "status": "completed",
        "total": 150.00
    }
    
    # Отправка ответа в очередь, указанную в reply_to
    ch.basic_publish(
        exchange='',
        routing_key=props.reply_to,
        properties=pika.BasicProperties(
            correlation_id=props.correlation_id,
            content_type='application/json'
        ),
        body=json.dumps(result)
    )
    
    ch.basic_ack(delivery_tag=method.delivery_tag)

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

channel.queue_declare(queue='rpc_queue', durable=True)
channel.basic_qos(prefetch_count=1)
channel.basic_consume(queue='rpc_queue', on_message_callback=on_request)

print("RPC Server готов к обработке запросов...")
channel.start_consuming()
```

### 3. Использование headers для маршрутизации

```python
import pika
import json

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Объявление exchange с маршрутизацией по headers
channel.exchange_declare(exchange='headers_exchange', exchange_type='headers')

# Публикация с заголовками
channel.basic_publish(
    exchange='headers_exchange',
    routing_key='',  # Игнорируется для headers exchange
    body=json.dumps({"event": "user_created"}),
    properties=pika.BasicProperties(
        headers={
            'event_type': 'user',
            'priority': 'high',
            'region': 'eu-west-1'
        },
        content_type='application/json',
        delivery_mode=2
    )
)

print("Сообщение отправлено с заголовками")
connection.close()
```

### 4. Биндинг по headers

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Очередь для high-priority событий
channel.queue_declare(queue='high_priority_events')

# Биндинг: все сообщения с priority=high и event_type=user
channel.queue_bind(
    exchange='headers_exchange',
    queue='high_priority_events',
    arguments={
        'x-match': 'all',  # Все условия должны совпасть
        'event_type': 'user',
        'priority': 'high'
    }
)

# Очередь для всех событий из eu-west-1
channel.queue_declare(queue='eu_events')

channel.queue_bind(
    exchange='headers_exchange',
    queue='eu_events',
    arguments={
        'x-match': 'any',  # Любое условие
        'region': 'eu-west-1'
    }
)

print("Биндинги настроены")
connection.close()
```

### 5. Message deduplication через message_id

```python
import pika
import json
import hashlib

class DedupPublisher:
    def __init__(self):
        self.connection = pika.BlockingConnection(
            pika.ConnectionParameters('localhost')
        )
        self.channel = self.connection.channel()
        self.published_ids = set()  # В production используйте Redis/БД
    
    def publish_with_dedup(self, exchange, routing_key, body, message_id=None):
        if message_id is None:
            # Генерация ID на основе содержимого
            message_id = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()
            ).hexdigest()
        
        # Проверка дубликата
        if message_id in self.published_ids:
            print(f"Пропуск дубликата: {message_id}")
            return False
        
        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=json.dumps(body),
            properties=pika.BasicProperties(
                message_id=message_id,
                content_type='application/json',
                delivery_mode=2,
                timestamp=int(__import__('time').time())
            )
        )
        
        self.published_ids.add(message_id)
        print(f"Опубликовано: {message_id}")
        return True

# Использование
publisher = DedupPublisher()
publisher.publish_with_dedup(
    exchange='',
    routing_key='orders',
    body={"order_id": 123, "amount": 100}
)
```

### 6. Потребитель с обработкой properties

```python
import pika
import json
from datetime import datetime

def callback(ch, method, properties, body):
    # Извлечение свойств
    print(f"=== Сообщение получено ===")
    print(f"Message ID: {properties.message_id}")
    print(f"Correlation ID: {properties.correlation_id}")
    print(f"Reply To: {properties.reply_to}")
    print(f"Content Type: {properties.content_type}")
    print(f"Delivery Mode: {properties.delivery_mode}")
    print(f"Priority: {properties.priority}")
    print(f"Timestamp: {datetime.fromtimestamp(properties.timestamp)}")
    print(f"Headers: {properties.headers}")
    print(f"Body: {json.loads(body)}")
    print(f"==========================")
    
    # Обработка
    result = {"status": "ok"}
    
    # Ответ если есть reply_to
    if properties.reply_to:
        ch.basic_publish(
            exchange='',
            routing_key=properties.reply_to,
            properties=pika.BasicProperties(
                correlation_id=properties.correlation_id,
                content_type='application/json'
            ),
            body=json.dumps(result)
        )
    
    ch.basic_ack(delivery_tag=method.delivery_tag)

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()
channel.queue_declare(queue='task_queue', durable=True)
channel.basic_consume(queue='task_queue', on_message_callback=callback)
channel.start_consuming()
```

### 7. TTL для отдельных сообщений

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Сообщение с TTL 5 секунд
channel.basic_publish(
    exchange='',
    routing_key='temporary_tasks',
    body='Это временное сообщение',
    properties=pika.BasicProperties(
        expiration='5000',  # 5 секунд
        delivery_mode=1  # Transient
    )
)

# Сообщение без TTL (использует TTL очереди)
channel.basic_publish(
    exchange='',
    routing_key='permanent_tasks',
    body='Это постоянное сообщение',
    properties=pika.BasicProperties(
        delivery_mode=2  # Persistent
    )
)

connection.close()
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Response timeout в RPC | Сервер не отправляет reply | Проверьте `reply_to` и `correlation_id` |
| Дублирование сообщений | Нет `message_id` или дедупликации | Используйте `message_id` и проверку на стороне |
| Сообщение не маршрутизируется | Неверный `routing_key` или биндинг | Проверьте тип exchange и правила биндинга |
| Сообщение удаляется раньше TTL | Низкий `expiration` | Увеличьте TTL или используйте DLX |
| Потеря correlation_id | Сервер не копирует ID из request | Убедитесь, что `correlation_id` берется из `props` |

## Лучшие практики

1. **Всегда задавайте `content_type`** — чтобы потребители знали формат тела.
2. **Используйте `message_id`** — для дедупликации и трассировки.
3. **Для RPC обязательно `correlation_id`** — без него невозможно сопоставить ответ.
4. **Устанавливайте `delivery_mode=2`** — для критичных сообщений.
5. **Используйте `headers`** — для сложной маршрутизации вместо code в `routing_key`.
6. **Не храните большие данные в properties** — максимум 1 МБ для properties + body.
7. **Для `reply_to` используйте exclusive queues** — автоматическое удаление при отключении.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — типы exchanges и очередей.
- **[Приоритетные очереди](./priority_queues.md)** — приоритеты через `priority` property.
- **[Single Active Consumer](./single_active_consumer.md)** — паттерн SAC для order processing.
- **[Сравнение RabbitMQ и Kafka](../Kafka/rabbitmq_vs_kafka.md)** — архитектурные различия.
