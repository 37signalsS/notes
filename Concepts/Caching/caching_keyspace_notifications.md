# Keyspace Notifications в Redis

**Актуально для:** Redis 7.4–8.2, Valkey 8.x

## Определения

**Keyspace Notifications** — механизм публикации событий изменения ключей и ключевого пространства в Redis. Позволяет приложениям подписываться на события (SET, DEL, EXPIRE, RENAME) через Pub/Sub без опроса кэша.

**Канал событий (Event Channel)** — строка формата `__keyevent@<db>__:<event>` или `__keyspace@<db>__:<key>`, через которую Redis публикует события.

**Подписка (Subscription)** — режим Pub/Sub, при котором клиент получает события в реальном времени.

**Событие (Event)** — тип изменения ключа: SET, DEL, EXPIRE, RENAMED, EVICTED и др.

## Основные концепции

### Архитектура

Keyspace Notifications работают поверх Pub/Sub механизма Redis. При изменении ключа Redis публикует событие в соответствующий канал. Все подписчики этого канала получают событие немедленно.

### Типы каналов

**Keyspace events:** события для конкретного ключа
- Канал: `__keyspace@<db>__:<key>`
- Пример: `__keyspace@0__:user:123: SET`

**Keyevent events:** события для конкретного типа изменения
- Канал: `__keyevent@<db>__:<event>`
- Пример: `__keyevent@0__:expired`

### Поддерживаемые события

| Событие | Описание | Канал |
| :--- | :--- | :--- |
| `SET` | Ключ установлен | `__keyspace@<db>__:<key>` |
| `DEL` | Ключ удален | `__keyspace@<db>__:<key>` |
| `EXPIRE` | Установлен TTL | `__keyspace@<db>__:<key>` |
| `EXPIRED` | Ключ истек | `__keyspace@<db>__:<key>` |
| `EVICTED` | Ключ вытеснен | `__keyspace@<db>__:<key>` |
| `RENAMED` | Ключ переименован | `__keyspace@<db>__:<key>` |
| `RPUSH` | Добавлен элемент в список | `__keyspace@<db>__:<key>` |
| `LPUSH` | Добавлен элемент в список | `__keyspace@<db>__:<key>` |
| `SADD` | Добавлен элемент в set | `__keyspace@<db>__:<key>` |
| `ZADD` | Добавлен элемент в sorted set | `__keyspace@<db>__:<key>` |

### Ограничения

- **Подписка только на существующие ключи:** при подписке на конкретный ключ, если его нет, подписка не создастся. Нужно подписаться на паттерн.
- **Нагрузка на Pub/Sub:** при высоком RPSPub/Sub становится узким местом. Используйте паттерн подписки осторожно.
- **Потеря событий:** Pub/Sub не гарантирует доставку. Если клиент отключен, он пропускает события. Для гарантированной доставки используйте Redis Streams.

## Предварительные требования

### Аппаратные и программные требования

- **Redis 7.4+ / Valkey 8.x:** механизм Keyspace Notifications стабилен начиная с Redis 2.8, но рекомендуется использовать актуальные версии для исправлений безопасности и стабильности.
- **Оперативная память:** минимум 2 GB RAM для dev-окружения; для production рассчитывайте по формуле: `RAM = (средний размер ключа × количество ключей) × 1.5` (с overhead).
- **Сеть:** задержка между клиентом-подписчиком и Redis < 1 мс в пределах дата-центра. При междатацентровом доступе (>5 мс) Pub/Sub становится узким местом из-за высокой частоты событий.
- **NTP:** синхронизация времени обязательна для корректной обработки событий `EXPIRED` и `EVICTED`, особенно в кластерных конфигурациях.

### Топология развертывания

| Компонент | Рекомендация |
| :--- | :--- |
| **Standalone Redis** | Подходит для dev и низконагруженных сценариев (<10K событий/сек) |
| **Redis Sentinel** | HA для production: 3 ноды, quorum=2 |
| **Redis Cluster** | При >100K событий/сек или объеме данных >50 GB |
| **Клиенты-подписчики** | Размещайте в том же дата-центре, что и Redis |

### Требования к клиентам

- Используйте `redis-py` 3.0+ / `go-redis` 9.0+ / `ioredis` 5.0+ для корректной работы с паттернами подписки.
- Настройте `tcp-keepalive 300` и `socket-timeout` для предотвращения "зависших" Pub/Sub соединений.
- Для production-приложений реализуйте механизм переподключения (reconnect) с экспоненциальным backoff.

## Пошаговая настройка окружения

### Шаг 1: Включение Keyspace Notifications

Включите уведомления в конфигурации Redis:

```conf
# /etc/redis/redis.conf
notify-keyspace-events AKE
```

**Валидация:**
```bash
redis-cli CONFIG GET notify-keyspace-events
# → notify-keyspace-events AKE
```

### Шаг 2: Проверка базовой работы Pub/Sub

Создайте тестовый скрипт для проверки доставки событий:

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()

# Подписка на expired события
p.psubscribe('__keyevent@0__:expired')

print("Ожидание событий expired...")
for message in p.listen():
    if message['type'] == 'pmessage':
        print(f"Ключ истек: {message['data']}")
        break
```

**Валидация:**
```bash
# В другом терминале: создайте ключ с коротким TTL
redis-cli SET test:key "value" EX 2
redis-cli GET test:key
# → "value" (перед истечением)

# Через 2 секунды:
redis-cli GET test:key
# → nil (после истечения)

# В выводе Python-скрипта:
# → Ключ истек: test:key
```

### Шаг 3: Настройка паттерна подписки для приложения

Используйте `psubscribe` вместо подписки на конкретные ключи для масштабируемости:

```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()

# Подписка на все события для ключей user:*
p.psubscribe('__keyspace@0__:user:*')
```

**Валидация:**
```bash
redis-cli SET user:123 "Alice"
redis-cli DEL user:123
# В выводе Python-скрипта:
# → Ключ 123: событие SET
# → Ключ 123: событие DEL
```

### Шаг 4: Настройка ACL и безопасности (опционально)

Ограничьте доступ к Pub/Sub командам через ACL:

```conf
# /etc/redis/users.acl
user app_subscriber on >password ~* +subscribe +psubscribe +punsubscribe +pubsub channels -@admin -@dangerous
```

**Валидация:**
```bash
redis-cli --user app_subscriber --password password PUBSUB CHANNELS
# → Список активных каналов (или пустой список)

redis-cli --user app_subscriber --password password CONFIG GET notify-keyspace-events
# → (error) NOPERM this user has no permissions to run the 'CONFIG' command
```

### Шаг 5: Настройка мониторинга

Добавьте проверки в вашу систему мониторинга:

```bash
# Количество Pub/Sub клиентов
redis-cli pubsub clients
# → 3 (число активных подписчиков)

# Количество каналов
redis-cli pubsub channels
# → 5 (число активных каналов)

# Количество подписчиков на паттерн
redis-cli pubsub numsub '__keyspace@0__:*'
# → 1) '__keyspace@0__:*' 2) 1
```

## Практические сценарии

### Включение Keyspace Notifications

По умолчанию уведомления отключены. Включите их в `redis.conf`:

```conf
# Включить все уведомления
notify-keyspace-events AKE

# Или выборочно:
# K - Keyspace events
# E - Keyevent events
# A - Все события
# $ - Строковые команды (SET, DEL)
# L - Списки (RPUSH, LPUSH)
# S - Sets (SADD)
# H - Хэши (HSET)
# Z - Sorted sets (ZADD)
# X - Expired events
# E - Evicted events
```

**Проверка конфигурации:**
```bash
redis-cli CONFIG GET notify-keyspace-events
# → AKE
```

### Подписка на события

**Python:**
```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()

# Подписка на все события для ключей user:*
p.psubscribe('__keyspace@0__:user:*')

for message in p.listen():
    if message['type'] == 'pmessage':
        key = message['pattern'].split(':')[-1]
        event = message['data']
        print(f"Ключ {key}: событие {event}")
        # → Ключ 123: событие SET
        # → Ключ 456: событие expired
```

### Инвалидация локального кэша

Keyspace Notifications позволяют реализовать автоматическую инвалидацию локального кэша приложения без опроса Redis:

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()
p.psubscribe('__keyspace@0__:*')

local_cache = {}

for message in p.listen():
    if message['type'] == 'pmessage':
        key = message['pattern'].split(':')[-1]
        event = message['data']
        if event in ('SET', 'DEL', 'EXPIRE', 'EVICTED', 'RENAMED'):
            local_cache.pop(key, None)
            print(f"Инвалидирован ключ: {key}")
```

### Rate Limiting с использованием expired событий

Keyspace Notifications позволяют реагировать на истечение ключей в реальном времени:

```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()
p.psubscribe('__keyevent@0__:expired')

rate_limits = {}

for message in p.listen():
    if message['type'] == 'pmessage':
        key = message['data']
        if key.startswith('rate_limit:'):
            rate_limits[key] = time.time()
            print(f"Rate limit истек для {key}")
```

### Очистка сессий

Keyspace Notifications позволяют отслеживать истечение сессий без периодического опроса:

```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
p = r.pubsub()
p.psubscribe('__keyevent@0__:expired')

session_events = []

for message in p.listen():
    if message['type'] == 'pmessage':
        key = message['data']
        if key.startswith('session:'):
            session_id = key.split(':')[1]
            session_events.append({
                'session_id': session_id,
                'event': 'expired',
                'timestamp': time.time()
            })
            print(f"Сессия {session_id} истекла")
```

## Лучшие практики

### Производительность
- Используйте паттерн подписки (`psubscribe`) вместо подписки на конкретные ключи. Паттерны масштабируются лучше при большом количестве ключей.
- Ограничьте количество каналов, на которые подписаны клиенты. Каждый подписчик потребляет память и CPU на стороне Redis.
- Используйте Pub/Sub только для сценариев, не критичных к потере событий. Для гарантированной доставки используйте Redis Streams.
- Ограничьте частоту событий через TTL-jitter или coalescing на стороне приложения. При >50K событий/сек на один подписчик рассмотрите sharding каналов.
- Настройте `hz 10` (по умолчанию) или `hz 20` для более точного срабатывания TTL-событий в high-load сценариях.

### Безопасность
- Настройте ACL для ограничения доступа к Pub/Sub командам. Минимальные права для подписчика: `+subscribe +psubscribe +punsubscribe +pubsub channels`.
- Используйте TLS для шифрования Pub/Sub трафика, особенно при междатацентровом доступе.
- Ограничьте количество подписчиков для предотвращения memory pressure: `CLIENT KILL type pubsub`.
- Отключите Pub/Sub для пользователей, которые не нуждаются в нем, через ACL.
- Логируйте подключения Pub/Sub клиентов для аудита: `redis-cli CLIENT LIST | grep pubsub`.

### Эксплуатация и мониторинг
- Мониторьте количество Pub/Sub клиентов: `redis-cli pubsub clients`. Алерт при росте > 100 активных подписчиков.
- Настройте алерт на рост Pub/Sub каналов: `redis-cli pubsub channels`. Нормальный рост без очистки указывает на утечку подписок.
- Используйте `PUBSUB NUMSUB <pattern>` для проверки количества подписчиков на критичные паттерны.
- Мониторьте `instantaneous_ops_per_sec` в `INFO stats` для отслеживания пиковой нагрузки на Pub/Sub.
- Настройте `client-query-buffer-limit` для предотвращения OOM при получении очень больших сообщений Pub/Sub.
- Используйте `CLIENT KILL type pubsub idle 600` для очистки неактивных Pub/Sub соединений.

### Сетевая конфигурация
- Размещайте клиентов-подписчики в том же дата-центре, что и Redis. Латентность < 1 мс критична для real-time сценариев.
- Настройте `tcp-keepalive 300` для предотвращения разрыва неактивных Pub/Sub соединений файрволами.
- Используйте отдельные инстансы Redis для Pub/Sub, если нагрузка на события превышает 50K сообщений/сек, чтобы изолировать трафик.
- Для высоконагруженных сценариев рассмотрите использование Redis Cluster с hash-tag для размещения ключей на одной ноде.

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Подписка не работает | `notify-keyspace-events` отключен | `redis-cli CONFIG GET notify-keyspace-events` | Включите уведомления в `redis.conf` и перезапустите Redis |
| Потеря событий | Клиент отключился или Pub/Sub переполнен | Логи клиента, `redis-cli pubsub clients` | Используйте Redis Streams для гарантированной доставки; увеличьте `client-query-buffer-limit` |
| Высокий CPU | Слишком много Pub/Sub клиентов или широкие паттерны | `redis-cli pubsub clients`, `redis-cli INFO stats` | Ограничьте количество подписчиков, используйте более узкие паттерны |
| Пропуск событий при рестарте | События не персистятся в Pub/Sub | Проверка `INFO persistence` | Используйте Streams вместо Pub/Sub; настройте AOF для durability |
| Подписка не создается | Ключ не существует при подписке | `redis-cli EXISTS <key>` | Используйте `psubscribe` с паттерном вместо подписки на конкретный ключ |
| Низкая пропускная способность | Слишком широкие паттерны или high cardinality | `redis-cli INFO stats \| grep instantaneous_ops_per_sec` | Узкие паттерны, шардирование по каналам, отдельный инстанс для Pub/Sub |
| Зависшие Pub/Sub соединения | Файрвол разрывает неактивные соединения | `redis-cli CLIENT LIST \| grep pubsub` | Настройте `tcp-keepalive 300`, добавьте heartbeat в клиент |
| Утечка подписок | Клиент не отписывается при shutdown | `redis-cli pubsub channels` | Реализуйте graceful shutdown с `punsubscribe()`; настройте `client-query-buffer-limit` |
| Высокое потребление памяти | Много Pub/Sub клиентов или буферов | `redis-cli INFO memory` | `CLIENT KILL type pubsub idle 600`, настройте `client-output-buffer-limit` |
| Clock drift в событиях EXPIRED | NTP не синхронизирован | `chronyc tracking` или `ntpq -p` | Настройте NTP на всех нодах; используйте монотонные таймстемпы в приложении |

## Дополнительная информация

### Взаимодействие с другими компонентами

- **Redis Streams:** альтернатива Pub/Sub с гарантированной доставкой и persistence
- **Lua-скрипты:** могут использоваться для атомарного изменения ключей с генерированием событий
- **Redis Functions:** могут обрабатывать expired события через `redis.registerFunction`

### Мониторинг и алертинг

**Ключевые метрики (Prometheus/Grafana):**

| Метрика | Источник | Описание | Алерт |
| :--- | :--- | :--- | :--- |
| `redis_pubsub_clients` | `INFO clients` | Количество активных Pub/Sub подписчиков | > 100 |
| `redis_pubsub_channels` | `PUBSUB CHANNELS` | Количество активных каналов | Рост > 20/мин без очистки |
| `redis_instantaneous_ops_per_sec` | `INFO stats` | Пиковая нагрузка на Pub/Sub | Резкий рост без уведомлений |
| `redis_mem_used_bytes` | `INFO memory` | Потребление памяти | Рост без очистки старых ключей |
| `redis_evicted_keys_total` | `INFO stats` | Количество вытесненных ключей | > 100/мин |
| `redis_keyspace_hit_ratio` | `INFO stats` | Эффективность кэширования | < 80% |

**Команды для ручной проверки:**
```bash
# Статистика Pub/Sub
redis-cli info clients | grep pubsub
redis-cli pubsub clients
redis-cli pubsub channels
redis-cli pubsub numsub '__keyspace@0__:*'

# Проверка утечек памяти
redis-cli INFO memory | grep used_memory
redis-cli INFO memory | grep mem_fragmentation_ratio
# → mem_fragmentation_ratio: 1.08 (норма: 1.0-1.5)

# Slow log для диагностики блокировок
redis-cli slowlog get 10
```

**Пример алертов (Prometheus Alertmanager):**
```yaml
groups:
  - name: redis_pubsub_alerts
    rules:
      - alert: RedisPubSubClientLeak
        expr: rate(redis_connected_clients[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Утечка Pub/Sub клиентов в Redis"
          description: "Рост клиентов: {{ $value }} в секунду."

      - alert: RedisPubSubChannelLeak
        expr: redis_pubsub_channels > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Утечка Pub/Sub каналов"
          description: "Активных каналов: {{ $value }}."

      - alert: RedisPubSubHighLatency
        expr: redis_instantaneous_ops_per_sec > 50000
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокая нагрузка на Pub/Sub"
          description: "Операций в секунду: {{ $value }}."
```

### Очистка и восстановление

#### Принудительное удаление зависших блокировок

Если подписчик "завис" и не отписывается корректно:

```bash
# Просмотр всех Pub/Sub клиентов
redis-cli CLIENT LIST | grep pubsub

# Завершение конкретного клиента
redis-cli CLIENT KILL id <client_id>

# Завершение всех неактивных Pub/Sub клиентов (>10 минут)
redis-cli CLIENT KILL type pubsub idle 600

# Проверка результата
redis-cli pubsub clients
# → 0 (или ожидаемое количество)
```

#### Поиск и удаление устаревших блокировок

Если приложение использует Keyspace Notifications для управления блокировками:

```bash
# Поиск всех блокировок
redis-cli KEYS "lock:*"

# Проверка TTL
redis-cli TTL lock:user:123
# → -2 (уже истек) или положительное значение

# Принудительное удаление зависшей блокировки
redis-cli DEL lock:user:123
```

#### Восстановление после частичного сбоя

Если подписчик отключился и пропустил события:

```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# 1. Проверка текущего состояния ключей
keys = r.keys('user:*')
for key in keys:
    ttl = r.ttl(key)
    value = r.get(key)
    print(f"{key}: TTL={ttl}, exists={value is not None}")

# 2. Принудительная инвалидация локального кэша
local_cache = {}
for key in keys:
    local_cache.pop(key, None)

# 3. Переподключение и повторная подписка
p = r.pubsub()
p.psubscribe('__keyspace@0__:user:*')
```

#### Очистка каналов после рестарта приложения

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Ожидание завершения работы старых подписчиков
time.sleep(1)

# Проверка активных каналов
channels = r.pubsub_channels()
print(f"Активных каналов: {len(channels)}")

# При необходимости: принудительная очистка (осторожно в production)
for channel in channels:
    r.punsubscribe(channel)
```

### Связанные темы

- [Паттерны кэширования](./caching_patterns.md) — инвалидация кэша
- [Обзор кэширования](./caching_overview.md) — управление данными
- [Redis Overview](../../Databases/redis_overview.md) — Pub/Sub и Streams
