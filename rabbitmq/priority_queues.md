# RabbitMQ: Приоритетные очереди (Priority Queues)

## Определения

- **Приоритетная очередь (Priority Queue):** Очередь, в которой сообщения распределяются по уровням приоритета. Сообщения с более высоким приоритетом потребляются первыми, независимо от порядка поступления.
- **Уровень приоритета (Priority Level):** Целочисленное значение от 0 до 255 (в RabbitMQ до версии 3.x — от 0 до 10). Чем выше значение, тем выше приоритет.
- **x-max-priority:** Аргумент очереди, задающий максимальный уровень приоритета. При объявлении очереди указывается как `arguments={'x-max-priority': 10}`.
- **Default Priority:** Сообщения без явно заданного приоритета получают приоритет 0 (самый низкий).

## Основные концепции

### Как работают приоритетные очереди

RabbitMQ реализует приоритетные очереди через внутреннюю сортировку сообщений по уровню приоритета. При потреблении брокер сначала отдает сообщения с наивысшим приоритетом. Если сообщений с высоким приоритетом нет, потребляются сообщения с более низким.

**Важные особенности:**
- Приоритеты работают только для **неразделяемых** очередей (non-exclusive queues).
- Количество уровней приоритета определяется при создании очереди (параметр `x-max-priority`).
- Использование большого числа уровней (>10) увеличивает потребление памяти.

### Поддержка типами очередей

| Тип очереди | Поддержка приоритетов | Примечания |
|:---|:---|:---|
| **Classic Queues** | Полная | Стандартная реализация с сортировкой в памяти. |
| **Quorum Queues** | Полная | Приоритеты поддерживаются начиная с RabbitMQ 3.10+. Работают через Raft. |
| **Stream Queues** | Нет | Streams — это логи, приоритеты не применимы. |

### Ограничения и производительность

- **Потребление памяти:** Каждый уровень приоритета создает отдельную внутреннюю очередь. При `x-max-priority=10` RabbitMQ создает 11 внутренних очередей.
- **Рекомендация:** Используйте не более 10 уровней приоритета. Для большинства сценариев достаточно 5-7 уровней.
- **Пропускная способность:** Приоритетные очереди потребляют на 5-10% больше CPU по сравнению с обычными очередями.

## Практические сценарии

### 1. Создание приоритетной очереди через CLI

```bash
# Создание очереди с 10 уровнями приоритета
sudo rabbitmqadmin declare queue name=tasks priority=True \
  arguments='{"x-max-priority": 10}'

# Проверка параметров очереди
sudo rabbitmqadmin list queues name arguments
# → tasks  {"x-max-priority": 10}
```

### 2. Создание приоритетной очереди через Management UI

1. Перейдите в **Queues** → **Add a new queue**.
2. В поле **Name** введите имя очереди.
3. В разделе **Arguments** добавьте: `x-max-priority` = `10`.
4. Нажмите **Add queue**.

### 3. Публикация сообщений с разными приоритетами (Python/Pika)

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Объявление очереди с приоритетами
channel.queue_declare(
    queue='tasks',
    durable=True,
    arguments={'x-max-priority': 10}
)

# Публикация сообщений с разными приоритетами
channel.basic_publish(
    exchange='',
    routing_key='tasks',
    body='Low priority task',
    properties=pika.BasicProperties(
        priority=1,  # Низкий приоритет
        delivery_mode=2
    )
)

channel.basic_publish(
    exchange='',
    routing_key='tasks',
    body='High priority task',
    properties=pika.BasicProperties(
        priority=10,  # Высокий приоритет
        delivery_mode=2
    )
)

print("Сообщения отправлены")
connection.close()
```

### 4. Потребление сообщений с приоритетами

```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

def callback(ch, method, properties, body):
    print(f"Получено: {body.decode()} (приоритет: {properties.priority})")
    ch.basic_ack(delivery_tag=method.delivery_tag)

# Настройка prefetch для приоритетных очередей
channel.basic_qos(prefetch_count=1)

channel.basic_consume(queue='tasks', on_message_callback=callback)
print('Ожидание сообщений...')
channel.start_consuming()
```

### 5. Применение политики к существующим очередям

```bash
# Применение политики ко всем очередям с префиксом "orders."
sudo rabbitmqctl set_policy \
  --priority 10 \
  --apply-to queues \
  priority-orders "^orders\." \
  '{"x-max-priority":5}'

# Проверка политик
sudo rabbitmqctl list_policies
# → priority-orders  production  queues  orders\*  10  ...
```

### 6. Динамическое изменение приоритета очереди

```bash
# Изменение x-max-priority существующей очереди
sudo rabbitmqadmin declare queue name=tasks priority=True \
  arguments='{"x-max-priority": 20}'

# Примечание: изменение приоритета на существующей очереди
# может потребовать пересоздания очереди в некоторых версиях
```

### 7. Мониторинг приоритетных очередей

```bash
# Проверка очередей с приоритетами
sudo rabbitmqadmin list queues name messages messages_ready \
  messages_unacknowledged arguments

# Просмотр статистики по приоритетам через Management API
curl -s -u guest:guest http://localhost:15672/api/queues | \
  jq '.[] | select(.arguments["x-max-priority"] != null) | {name, priority: .arguments["x-max-priority"]}'
```

### 8. Приоритетные очереди в Kubernetes (RabbitMQ Cluster Operator)

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: Queue
metadata:
  name: tasks
  namespace: rabbitmq
spec:
  name: tasks
  type: quorum
  arguments:
    x-max-priority: 10
  rabbitmqClusterReference:
    name: rabbitmq-cluster
```

## Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| Приоритеты не работают | Очередь объявлена без `x-max-priority` | Пересоздайте очередь с аргументом `x-max-priority` |
| Высокое потребление памяти | Слишком много уровней приоритета | Уменьшите `x-max-priority` до 10 или меньше |
| Сообщения не сортируются | Клиент не устанавливает `priority` в `BasicProperties` | Убедитесь, что `priority` задан в properties сообщения |
| Приоритеты не работают в Quorum Queues | Версия RabbitMQ < 3.10 | Обновите RabbitMQ до 3.10+ |

## Лучшие практики

1. **Используйте не более 10 уровней приоритета** — большее число увеличивает overhead.
2. **Задавайте `priority` в properties сообщения** — без этого все сообщения считаются с приоритетом 0.
3. **Комбинируйте с DLX** — для обработки сообщений с истекшим TTL или превышенным delivery-limit.
4. **Мониторьте глубину очереди по приоритетам** — используйте Management API для анализа распределения.
5. **Для Quorum Queues** используйте RabbitMQ 3.10+ для полной поддержки приоритетов.
6. **Не используйте приоритеты для имитации задержек** — для этого лучше подходит `x-message-ttl` или `x-delayed-message`.

## Дополнительная информация

### См. также

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции очередей и обменников.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика проблем с очередями.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — настройка метрик для приоритетных очередей.
