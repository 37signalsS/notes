# Обзор RabbitMQ

RabbitMQ — брокер сообщений с открытым исходным кодом, реализующий парадигму асинхронного обмена данными. Стандарт для систем с богатой логикой маршрутизации. Поддерживает протоколы AMQP 0-9-1, AMQP 1.0 (нативно в 4.0+), MQTT и STOMP.

Область применения заметок: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развернутых (on-prem / self-hosted) систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, в данной базе знаний не рассматриваются.

## Определения

- **Брокер (Broker):** Центральный узел (или кластер), отвечающий за прием, хранение и доставку сообщений.
- **Продюсер (Producer):** Приложение, отправляющее сообщения в брокер.
- **Консьюмер (Consumer):** Приложение, получающее сообщения из брокера.
- **Обменник (Exchange):** Логический узел маршрутизации, который принимает сообщения от продюсера и распределяет их по очередям на основе правил (биндингов).
- **Очередь (Queue):** Буфер, в котором сообщения хранятся до тех времени, пока не будут успешно обработаны консьюмером.
- **Биндинг (Binding):** Правило связи между обменником и очередью.
- **Виртуальный хост (Vhost):** Механизм логической изоляции ресурсов (очередей, обменников, пользователей) внутри одного инстанса RabbitMQ.
- **Подключение (Connection):** TCP-соединение между клиентом и брокером. Обычно дорогое, поэтому создается на весь жизненный цикл приложения.
- **Канал (Channel):** Логическое соединение поверх TCP, в рамках которого происходят все операции с очередями. Один подключение может иметь множество каналов.
- **Политика (Policy):** Набор правил, применяемых к очередям или обменникам по маске имен (HA-репликация, TTL, Dead Lettering, ограничение длины).
- **Аргумент (Argument):** Параметр, применяемый к конкретной очереди или обменнику при их объявлении (например, `x-queue-type`, `x-message-ttl`).

## Применение RabbitMQ

RabbitMQ используется для решения следующих задач:

- **Разделение приложений (Decoupling):** Асинхронное взаимодействие между сервисами без прямых зависимостей.
- **Балансировка нагрузки:** Распределение задач между воркерами (worker queues).
- **Отказоустойчивость:** Гарантия доставки сообщений при падении потребителей.
- **Обработка всплесков трафика (Burst handling):** Буферизация сообщений при пиковых нагрузках.
- **Гарантия доставки:** Confirmation mechanism для критичных данных.
- **Маршрутизация:** Богатая логика маршрутизации через exchanges (topic, headers, fanout).
- **Request-Reply (RPC):** Асинхронные запросы через temporary queues.

## Операционный контекст: DevOps / SRE / Sysadmin

RabbitMQ в production на bare-metal или виртуальных машинах требует внимания к трем слоям: надежность доставки, производительность и наблюдаемость. В этом файле собраны базовые концепции и типовые сценарии эксплуатации. Для углубленных тем используйте специализированные файлы:

- **[Установка, кластеризация и эксплуатация](./installation_and_clustering.md)** — развертывание кластеров, gossip, Khepri, топологии.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики, Prometheus, Grafana, алерты.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика и решение типичных проблем.
- **[Сравнение RabbitMQ и Kafka](../Kafka/rabbitmq_vs_kafka.md)** — когда выбирать RabbitMQ.
- **[Гарантии доставки](../Kafka/delivery_guarantees.md)** — семантики At-most-once, At-least-once, Exactly-once.
- **[Принципы работы очередей](../Kafka/message_queues_principles.md)** — общие концепции и протоколы.

## Базовые концепции

### Архитектура и поток данных

Взаимодействие строится по схеме: `Producer → Connection → Channel → Exchange → (Binding) → Queue → Consumer`.

**Connection vs Channel:**
- **Connection:** TCP-соединение (порт 5672 для AMQP). Дорогое в создании, поэтому приложение держит его открытым на весь срок работы.
- **Channel:** Многопользовательский логический канал внутри Connection. Все операции AMQP (объявление очередей, публикация, потребление) выполняются в контексте канала. Обработка каналов в Erlang-процессе (`channel_process`) является одним из узких мест при высокой нагрузке.

В отличие от Kafka, где клиент сам управляет чтением (Pull), классический RabbitMQ работает по **Push-модели**, активно проталкивая сообщения свободным консьюмерам.

### Типы обменников (Exchanges)

| Тип | Логика маршрутизации | Применение |
|:---|:---|:---|
| **Direct** | Прямое соответствие `routing_key` сообщения и ключа привязки очереди. | Точечная доставка задач. |
| **Fanout** | Игнорирует ключ и копирует сообщение во все привязанные очереди. | Широковещательные уведомления. |
| **Topic** | Соответствие по шаблону. Использует `*` (одно слово) и `#` (ноль или более слов). | Фильтрация событий по категориям. |
| **Headers** | Использует атрибуты заголовков сообщения вместо ключа маршрутизации. | Сложная фильтрация по метаданным. |
| **Local Random** | (v4.0+) Маршрутизирует сообщение в случайную очередь на *локальном* узле. | Снижение межузлового трафика. |

### Типы структур данных

1. **Кворумные очереди (Quorum Queues):**
   - **Назначение:** Современный стандарт (4.0+) для высокой доступности (HA) и сохранности данных.
   - **Механизм:** Реализованы на базе алгоритма **Raft**. Требуют подтверждения записи от большинства (кворума) узлов кластера.
   - **Особенности:** Начиная с версии 4.0, являются единственным способом репликации данных. Зеркалирование классических очередей удалено.

2. **Классические очереди (Classic Queues):**
   - **Назначение:** Временные или некритичные данные.
   - **Особенности:** В RabbitMQ 4.0+ всегда привязаны к **одной ноде** (не реплицируются). Используют движок хранения CQv2 для высокой производительности.

3. **RabbitMQ Streams:**
   - **Назначение:** Высокая пропускная способность, хранение больших объемов данных, повторное чтение (Replay).
   - **Модель:** Неизменяемый лог (аналог Kafka), работающий по **Pull-модели**.
   - **Производительность:** Позволяют обрабатывать миллионы сообщений в секунду через специализированный бинарный протокол.

### Политики и аргументы

**Политики (Policies)** применяются по маске имен и управляют поведением группы очередей (HA, TTL, DLX). **Аргументы (Arguments)** задаются при объявлении конкретной очереди и имеют приоритет над политиками. Различие важно для автоматизации: политики упрощают массовое применение правил, аргументы — для тонкой настройки.

### Изоляция через виртуальные хосты (Vhosts)

Каждый vhost имеет отдельное пространство имен для очередей, обменников, пользователей и прав. Это основной механимент изоляции сред (development, staging, production) внутри одного кластера. Изоляция на уровне Erlang-процессов отсутствует: проблемный vhost может повлиять на производительность всего узла.

## Продвинутые механизмы

### Надежность и гарантии доставки

- **Publisher Confirms:** Продюсер получает от брокера подтверждение, что сообщение успешно принято и записано (на диск для кворумных очередей).
- **Consumer Acknowledgments (Ack):** Консьюмер подтверждает успешную обработку. Сообщение удаляется из очереди только после получения `ack`.
- **Лимиты переповторов (v4.0+):** Кворумные очереди имеют встроенный `delivery-limit` (по умолчанию 20). При превышении сообщение отправляется в DLX или удаляется.
- **DLX (Dead Letter Exchange):** Обменник, в который перенаправляются "плохие" сообщения (отклоненные консьюмером или превысившие TTL/лимит повторов).
- **TTL (Time-To-Live):** Ограничение времени жизни сообщения в очереди или самой очереди.

**Семантики доставки:**

| Гарантия | Механизм | Применение |
|:---|:---|:---|
| **At-most-once** | `auto_ack=true`, без confirms | Логи, метрики, не критичные данные |
| **At-least-once** | Publisher Confirms + Consumer Ack | Большинство production сценариев |
| **Exactly-once** | Quorum Queues + idempotent consumers | Финансовые системы, платежи |

**Важно:** Полная Exactly-once семантика невозможна без поддержки на стороне приложения (идемпотентность). RabbitMQ обеспечивает At-least-once с механизмами для дедупликации на стороне потребителя.

**Publisher Confirms — детали:**
```python
channel.confirm_delivery()  # Включение подтверждений

try:
    channel.basic_publish(
        exchange='',
        routing_key='critical_tasks',
        body='Payload',
        properties=pika.BasicProperties(delivery_mode=2)
    )
    # Сообщение принято брокером
except pika.exceptions.UnroutableError:
    # Сообщение не может быть маршрутизировано
except pika.exceptions.NackError:
    # Брокер отклонил сообщение
```

**Consumer Acknowledgments — детали:**
```python
def callback(ch, method, properties, body):
    try:
        process_message(body)
        ch.basic_ack(delivery_tag=method.delivery_tag)  # Успешно
    except Exception:
        ch.basic_nack(
            delivery_tag=method.delivery_tag,
            requeue=True  # Вернуть в очередь
        )

channel.basic_consume(queue='tasks', on_message_callback=callback)
```

**Dead Letter Exchange (DLX):**
```bash
# Настройка DLX через политику
rabbitmqctl set_policy DLX "^errors\." \
  '{"dead-letter-exchange":"dlx","dead-letter-routing-key":"errors"}' \
  --apply-to queues

# Причины попадания в DLX:
# 1. TTL истек (message-ttl или queue TTL)
# 2. Превышен delivery-limit (Quorum Queues)
# 3. Reject/Nack с requeue=false
# 4. Переполнение очереди (max-length)
```

### Кластеризация и метаданные
- **Raft для данных:** Используется в Quorum Queues и Streams для обеспечения консистентности.
- **Khepri (v4.0+):** Новый Raft-базированный механизм хранения метаданных (пользователи, vhosts, биндинги), заменяющий устаревший Mnesia. Обеспечивает лучшую надежность при разделении сети (network partitions).

### Безопасность
- **Аутентификация:** Пароли, TLS-сертификаты, SASL, внешние плагины (LDAP, OAuth2).
- **Авторизация (RBAC):** Доступ разграничивается на уровне Vhost и регулярных выражений для имен ресурсов (Configure, Write, Read).
- **Шифрование:** Поддержка TLS для всех протоколов обмена и для управления (Management UI/API).

### Гео-распределенность
- **Federation:** Позволяет передавать сообщения между обменниками или очередями в разных кластерах (через WAN) без создания единого кластера.
- **Shovel:** Низкоуровневый механизм надежного копирования сообщений из одного брокера в другой. Идеален для миграций или объединения данных из разных регионов.

## Consumer Prefetch Optimization

**Prefetch count** — лимит количества сообщений, которые брокер может отправить консьюмеру до получения подтверждения (ack). Критичен для производительности и контроля нагрузки.

### Стратегии prefetch

| Значение | Поведение | Применение |
|:---|:---|:---|
| `prefetch=1` | Только 1 сообщение без ack | Тяжелые задачи, контроль порядка |
| `prefetch=10-100` | Баланс throughput и контроля | Большинство production сценариев |
| `prefetch=0` | Без ограничений | Быстрые consumer'ы с легкой обработкой |

**Рекомендации:**
- Для **очередей задач** (task queues): `prefetch=10-20`
- Для **RPC**: `prefetch=1`
- Для **высокого throughput**: `prefetch=100+`
- Для **Quorum Queues**: `prefetch=256` (дефолт)

**Пример настройки:**
```python
# Глобальный prefetch для канала
channel.basic_qos(prefetch_count=10)

# Per-consumer prefetch ( RabbitMQ 3.8+)
channel.basic_qos(prefetch_count=10, global_=False)
```

**Мониторинг:**
```promql
# Consumer lag (сообщения в очереди / количество consumer'ов)
sum(rabbitmq_queue_messages_ready) by (vhost, name)
/
sum(rabbitmq_queue_consumers) by (vhost, name)
```

Подробнее: **[Паттерны сообщений](./message_patterns.md)**, **[Устранение неполадок](./troubleshooting.md)**

## Queue Lifecycle Management

### Типы очередей и жизненный цикл

| Тип | Особенности | Жизненный цикл |
|:---|:---|:---|
| **Classic** | Одна нода, fast | Создание → Потребление → Удаление |
| **Quorum** | Репликация Raft, HA | Создание → Репликация → Потребление → Удаление |
| **Stream** | Append-only, replay | Создание → Запись → Потребление (многократное) |
| **Priority** | Сортировка по приоритету | Как Classic/Quorum + сортировка |

### Auto-delete и TTL

**Auto-delete очереди:**
- Удаляются автоматически при отключении последнего consumer'а
- Используются для временных очередей (RPC reply queues)

**Queue TTL (x-expires):**
```bash
# Очередь удаляется через 1 час без активности
rabbitmqadmin declare queue name=temp_queue \
  arguments='{"x-expires":3600000}'
```

**Message TTL (x-message-ttl):**
```bash
# Сообщения удаляются через 5 минут
rabbitmqadmin declare queue name=short_lived \
  arguments='{"x-message-ttl":300000}'
```

### Lazy Queues (deprecated)

В RabbitMQ 3.12+ lazy queues deprecated. Используйте **Quorum Queues** для аналогичного поведения (сбрасывание на диск при давлении памяти).

### Удаление очередей

```bash
# CLI
rabbitmqctl delete_queue <queue_name>
rabbitmqadmin delete queue name=<queue_name>

# Management API
curl -u guest:guest -X DELETE http://localhost:15672/api/queues/%2F/<queue_name>
```

Подробнее: **[Приоритетные очереди](./priority_queues.md)**, **[Single Active Consumer](./single_active_consumer.md)**

## Message Deduplication

### Проблема дублирования

RabbitMQ не обеспечивает встроенную дедупликацию. Дубли могут возникать при:
- Повторных попытках публикации ( network failures)
- Requeue сообщений
- Failover consumer'ов

### Механизмы дедупликации

**1. Message ID (клиентская дедупликация):**
```python
import hashlib
import json

def publish_with_dedup(channel, queue, body, published_ids):
    # Генерация уникального ID
    message_id = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()
    ).hexdigest()
    
    # Проверка дубликата
    if message_id in published_ids:
        return False
    
    channel.basic_publish(
        exchange='',
        routing_key=queue,
        body=json.dumps(body),
        properties=pika.BasicProperties(
            message_id=message_id,
            delivery_mode=2
        )
    )
    
    published_ids.add(message_id)
    return True
```

**2. Idempotent Consumers (потребительская дедупликация):**
```python
def process_message(ch, method, properties, body):
    message_id = properties.message_id
    
    # Проверка в БД (Inbox pattern)
    if db.check_processed(message_id):
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return
    
    # Обработка
    result = handle_message(body)
    
    # Сохранение в Inbox
    db.save_inbox(message_id, result)
    
    ch.basic_ack(delivery_tag=method.delivery_tag)
```

**3. Quorum Queues (брокерская дедупликация):**
- Quorum Queues автоматически дедуплицируют сообщения по `message_id`
- Включено по умолчанию в RabbitMQ 3.12+

**4. Stream Deduplication:**
- Streams поддерживают дедупликацию через ` deduplication` plugin
- Конфигурация через policies

Подробнее: **[Паттерны сообщений](./message_patterns.md)**, **[Гарантии доставки](../Kafka/delivery_guarantees.md)**

## Streams:.consumer groups и offset tracking

### Consumer Groups в Streams

RabbitMQ Streams поддерживают consumer groups (аналог Kafka):
- Каждый consumer в группе получает уникальное подмножество партиций
- Автоматическая rebalance при добавлении/удалении consumer'ов
- Повторное чтение (replay) с любого offset

**Пример:**
```python
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = connection.channel()

# Объявление stream с consumer group
channel.queue_declare(
    queue='orders_stream',
    arguments={
        'x-queue-type': 'stream',
        'x-single-active-consumer': False,  # Множество consumer'ов
        'x-stream-offset': 'first'
    }
)

# Consumer group через prefetch
channel.basic_qos(prefetch_count=100)

def callback(ch, method, properties, body):
    print(f"Обработка: {body.decode()}")
    ch.basic_ack(delivery_tag=method.delivery_tag)

channel.basic_consume(queue='orders_stream', on_message_callback=callback)
channel.start_consuming()
```

### Offset Tracking

**Способы задания offset:**
- `first` — с первого сообщения
- `last` — с последнего сообщения
- `next` — после последнего обработанного
- Числовой offset — конкретная позиция

**CLI для управления offset:**
```bash
# Просмотр offset'ов
rabbitmq-streams list_stream_reader --stream orders_stream

# Сброс offset
rabbitmq-streams reset_stream_reader --stream orders_stream \
  --offset 0 --app-id my-app
```

**Prometheus метрики:**
```promql
# Consumer lag в streams
rabbitmq_stream_consumer_lag_entries
```

Подробнее: **[Плагины](./plugins.md)**, **[Мониторинг](./monitoring_and_alerting.md)**

## Практические сценарии

### Установка и запуск (systemd)

RabbitMQ поставляется как systemd-сервис в большинстве дистрибутивов Linux.

```bash
# Проверка статуса сервиса
sudo systemctl status rabbitmq-server
# → Active: active (running) since Thu 2026-09-17 10:00:00 UTC; 2h ago

# Включение автозапуска при загрузке
sudo systemctl enable rabbitmq-server

# Перезапуск после изменения конфигурации
sudo systemctl restart rabbitmq-server

# Просмотр журналов
sudo journalctl -u rabbitmq-server -f
```

### Конфигурация (rabbitmq.conf)

Основной конфигурационный файл: `/etc/rabbitmq/rabbitmq.conf`. Формат — sysctl-like (ключ = значение). Пример минимальной production-конфигурации:

```ini
# Слушаемые интерфейсы (все)
listeners.tcp.default = 5672

# Management UI
management.tcp.port = 15672
management.tcp.ip   = 127.0.0.1

# Лимит памяти (по умолчанию 40% от RAM)
vm_memory_high_watermark.relative = 0.4

# Директория для данных
data_dir = /var/lib/rabbitmq

# Логирование
log.console = true
log.console.level = info
log.file = true
log.file.level = info
log.dir = /var/log/rabbitmq
```

Проверка актуальной конфигурации:

```bash
sudo rabbitmqctl environment
# → Выводит все переменные окружения и конфигурацию Erlang-ноды
```

### Управление пользователями и vhosts

```bash
# Создание vhost
sudo rabbitmqctl add_vhost production

# Создание пользователя с правами
sudo rabbitmqctl add_user app_user 's3cur3_p@ss'
sudo rabbitmqctl set_permissions -p production app_user ".*" ".*" ".*"

# Удаление пользователя
sudo rabbitmqctl delete_user app_user

# Список пользователей
sudo rabbitmqctl list_users
# → app_user  [production]
```

### Управление политиками

```bash
# Применение политики к очередям с префиксом "orders."
# HA на 3 узла, TTL 1 час, DLX "dlx"
sudo rabbitmqctl set_policy \
  --priority 10 \
  --apply-to queues \
  ha-for-orders "orders\." \
  '{"ha-mode":"exactly","ha-params":3,"message-ttl":3600000,"dead-letter-exchange":"dlx"}'

# Проверка политик
sudo rabbitmqctl list_policies
# → ha-for-orders  production  queues  orders\*  10  ...
```

### Резервное копирование и восстановление

Резервные копии включают метаданные (пользователи, vhosts, политики) и, опционально, сообщения из очередей.

```bash
# Экспорт метаданных (пользователи, vhosts, права, политики)
sudo rabbitmqctl export_definitions /tmp/rabbitmq_backup.json

# Импорт метаданных
sudo rabbitmqctl import_definitions /tmp/rabbitmq_backup.json

# Бэкап содержимого очередей (кворумные очереди)
# ВНИМАНИЕ: требует остановки публикаций для консистентности
sudo rabbitmqctl list_queues name messages > /tmp/queue_depths.txt
```

### Управление логами

```bash
# Логи сервиса (systemd)
journalctl -u rabbitmq-server --since "1 hour ago"

# Логи приложения (если log.dir настроен)
tail -f /var/log/rabbitmq/rabbit@node1.log

# Ротация логов выполняется logrotate или внутренним механизмом
sudo rabbitmqctl eval 'application:set_env(rabbit, log, [{file, "/var/log/rabbitmq/rabbit.log"}, {level, info}])'
```

### Надежная публикация и потребление (Python/Pika)

```python
import pika

params = pika.ConnectionParameters('localhost', credentials=pika.PlainCredentials('guest', 'guest'))
connection = pika.BlockingConnection(params)
channel = connection.channel()

channel.queue_declare(queue='critical_tasks', durable=True, arguments={'x-queue-type': 'quorum'})
channel.confirm_delivery()

try:
    channel.basic_publish(
        exchange='',
        routing_key='critical_tasks',
        body='Payload Data',
        properties=pika.BasicProperties(delivery_mode=2)
    )
    print("Сообщение доставлено и подтверждено брокером")
except pika.exceptions.UnroutableError:
    print("Ошибка: Сообщение не может быть маршрутизировано")

def callback(ch, method, properties, body):
    try:
        print(f"Обработка: {body}")
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

channel.basic_consume(queue='critical_tasks', on_message_callback=callback)
channel.start_consuming()
```

### Эксплуатация в Kubernetes
- **RabbitMQ Cluster Operator:** Рекомендуемый способ развертывания. Управляет жизненным циклом, обновлением сертификатов и масштабированием.
- **KEDA:** Автомасштабирование подов-воркеров на основе длины очереди (`rabbitmq` scaler). Позволяет масштабироваться до 0, если очередь пуста.

### Управление и CLI

| Команда | Назначение |
|:---|:---|
| `rabbitmqctl` | Основной инструмент администрирования (пользователи, vhosts, права). |
| `rabbitmq-diagnostics` | Проверка здоровья, портов, памяти, статуса кворума. |
| `rabbitmqadmin` | CLI-клиент для HTTP API (создание обменников/очередей, публикация сообщений). |
| `rabbitmq-plugins` | Управление плагинами (например, `enable rabbitmq_management`). |

### Диагностические команды (шпаргалка)

```bash
# Общий статус кластера
sudo rabbitmq-diagnostics status

# Список всех очередей с метриками
sudo rabbitmqctl list_queues name durable auto_delete messages_ready messages_unacknowledged consumers

# Список подключений
sudo rabbitmqctl list_connections user client_host state

# Проверка кворума
sudo rabbitmq-diagnostics check_local_alarms
```

## Устранение неполадок

Типичные категории проблем:

| Категория | Симптомы | Частые причины |
|:---|:---|:---|
| **Доступность** | Нет подключения, connection refused | Брокер упал, порт закрыт, firewall |
| **Производительность** | Низкий throughput, высокая латентность | Нехватка RAM/CPU, медленный диск, network |
| **Доставка** | Сообщения теряются, дублируются | Отсутствует confirm_delivery, auto_ack=True |
| **Репликация** | Кворум потерян, данные не реплицируются | Проблемы с сетью, недостаточно узлов |
| **Безопасность** | Неавторизованный доступ, утечка данных | Слабые пароли, открытый Management UI |

Подробные сценарии диагностики и решения: **[RabbitMQ: Устранение неполадок](./troubleshooting.md)**.

## Ограничения

- **Размер сообщений:** В v4.0 лимит по умолчанию снижен до **16 MiB** (рекомендуется держать сообщения до 1 MiB для максимальной производительности).
- **Нагрузка на RAM:** RabbitMQ активно использует память для индексации сообщений. При превышении `vm_memory_high_watermark` брокер блокирует публикации.
- **Порядок сообщений:** Гарантируется только в рамках одной очереди при одном консьюмере. При requeue порядок нарушается.
- **Vertically scalable:** Очереди по умолчанию размещаются на одном узле. Масштабирование происходит через Federation/Shovel или Quorum Queues.
- **Memory pressure:** При переполнении RAM брокер блокирует продюсеров (flow control). Требуется careful capacity planning.

## См. также

- **[RabbitMQ vs Kafka](../Kafka/rabbitmq_vs_kafka.md)** — глубокое сравнение архитектур.
- **[Гарантии доставки](../Kafka/delivery_guarantees.md)** — подробнее о семантиках At-least-once и Exactly-once.
- **[Принципы работы очередей](../Kafka/message_queues_principles.md)** — общие концепции и протоколы.
- **[Установка и кластеризация](./installation_and_clustering.md)** — развертывание кластеров.
- **[Мониторинг и алертинг](./monitoring_and_alerting.md)** — метрики и observability.
- **[Приоритетные очереди](./priority_queues.md)** — приоритетная маршрутизация сообщений.
- **[Single Active Consumer](./single_active_consumer.md)** — паттерн SAC для order processing.
- **[Паттерны сообщений](./message_patterns.md)** — Request/Reply, message properties.
- **[Безопасность](./security.md)** — ACL, SASL, LDAP, OAuth, TLS.
- **[CLI-команды](./cli_reference.md)** — справочник всех CLI-инструментов.
- **[Клиентские библиотеки](./client_libraries.md)** — обзор Python, Go, Node.js, Java, .NET.
- **[Плагины](./plugins.md)** — Management, Prometheus, Federation, Shovel.
- **[Балансировка нагрузки](./load_balancing.md)** — HAProxy, DNS round-robin.
- **[Конфигурация](./configuration_reference.md)** — справочник параметров.

