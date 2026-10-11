# Connection Pooling для Redis и Memcached

**Актуально для:** Redis 7.x / 8.x, Valkey 8.x, Memcached 1.6.x

> **Примечание по совместимости:** Valkey 8.x является форком Redis 7.x под лицензией BSD. Все команды, параметры конфигурации и форматы вывода, описанные в этом документе, совместимы с Valkey 8.x. Различия могут касаться только лицензирования и поддержки модулей.

## Определения

**Connection Pooling** — техника переиспользования TCP-соединений для снижения overhead на установку и разрыв соединений. Каждое новое соединение Redis/Memcached требует:
1. TCP handshake (3-way handshake)
2. Аутентификация (AUTH)
3. Выбор базы данных (SELECT)

Connection pooling позволяет приложению использовать уже установленные соединения многократно.

**Connection Leak** — утечка соединений, при которой клиент открывает соединение, но никогда его не возвращает в пул. Приводит к исчерпанию лимита `maxclients` на сервере и `EMFILE`/`ENFILE` на стороне клиента.

**Max Clients** — максимальное количество одновременных соединений, которое Redis может обработать. По умолчанию 10000. Настраивается через `maxclients` в `redis.conf` или `CONFIG SET maxclients <value>`.

**Connection Timeout** — время ожидания установки соединения. При превышении клиент получает ошибку. В Redis/Memcached это timeout на TCP-установку, а не на выполнение команды.

**Socket Timeout** — время ожидания ответа на команду. При превышении соединение закрывается и возвращается в пул (или уничтожается).

**Min Idle Connections** — минимальное количество соединений, которые пул поддерживает в «горячем» состоянии, чтобы избежать latency на установку при sudden spikes.

**Connection Lifetime** — максимальное время жизни соединения в пуле. Нужно для предотвращения использования соединений, которые могут быть разорваны прозрачно (NAT timeout, firewall).

**Stale Connection** — соединение, которое было закрыто сервером или промежуточным устройством (timeout, restart, NAT table expiry), но клиент считает его активным. При следующем использовании приводит к ошибке.

**Backlog (TCP)** — очередь незавершённых соединений на сервере. Определяется `tcp-backlog` в Redis и `net.core.somaxconn` в Linux. Если очередь переполнена, новые SYN-пакеты отклоняются.

**File Descriptor (FD)** — дескриптор файла, который ОС выделяет для каждого TCP-соединения. Лимит задаётся `ulimit -n`. При исчерпании FDs приложение получает `EMFILE`/`ENFILE`.

## Основные концепции

### Зачем нужен pooling

Без pooling каждое обращение к Redis/Memcached требует:
- Создания нового TCP-соединения: ~0.5-1ms
- Аутентификации: ~0.1ms
- Выполнения команды: ~0.1ms
- Закрытия соединения: ~0.5ms

Итого: ~1-2ms overhead на каждое обращение

С pooling:
- Получение соединения из пула: ~0.01ms
- Выполнение команды: ~0.1ms
- Возврат соединения в пул: ~0.01ms

Итого: ~0.12ms overhead

### Жизненный цикл соединения в пуле

```
Клиент               Connection Pool              Redis/Memcached
  │                       │                            │
  │  1. Запрос            │                            │
  │ ─────────────────────►│                            │
  │                       │  2. Взять idle-соединение  │
  │                       │     или создать новое       │
  │                       │ ──────────────────────────►│
  │                       │                            │
  │                       │  3. Отправить команду       │
  │                       │ ◄──────────────────────────│
  │                       │                            │
  │                       │  4. Получить ответ          │
  │                       │ ──────────────────────────►│
  │  5. Вернуть ответ     │                            │
  │ ◄─────────────────────│                            │
  │                       │                            │
  │                       │  6. Вернуть соединение в пул
  │                       │     (не закрывать!)         │
  │                       │                            │
```

### Стратегии pooling

**Fixed Pool:** фиксированный размер пула. Простой в управлении, но может привести к блокировкам при burst-нагрузках.

**Dynamic Pool:** пул, который увеличивается при нехватке соединений и уменьшается при простое. Более гибкий, но сложнее в управлении.

**Bounded Pool:** пул с верхним лимитом. При превышении лимита новые запросы ожидают или получают ошибку.

### Проблемы pooling

**Connection Leak:** клиент берёт соединение из пула, но не возвращает его. Со временем пул истощается, приложение получает `ConnectionPoolError`.

**Stale Connections:** соединение, которое было закрыто сервером (timeout, restart), но клиент считает его активным. При следующем использовании приводит к ошибке.

**Pool Sizing:** слишком маленький пул приводит к блокировкам ожидания соединения, слишком большой — к memory pressure на клиенте и избыточному количеству FDs на сервере.

**Thundering Herd:** при восстановлении после downtime все клиенты одновременно пытаются создать соединения, что создаёт burst-нагрузку на сервер.

### Взаимодействие с сервером

Redis/Memcached обрабатывают каждое входящее соединение как отдельный файловый дескриптор. Ключевые ограничения на стороне сервера:

- `maxclients` (Redis): максимальное количество соединений. По умолчанию 10000.
- `tcp-backlog` (Redis): размер очереди незавершённых соединений. По умолчанию 511.
- `net.core.somaxconn` (Linux): системный лимит размера очереди TCP.
- `ulimit -n` (ОС): лимит файловых дескрипторов на процесс.

При превышении любого из этих лимитов новые соединения отклоняются с ошибкой `ERR max number of clients reached` (Redis) или аналогичной.

## Практические сценарии

### Python (redis-py)

**Базовый pooling:**
```python
import redis

# Создание пула
pool = redis.ConnectionPool(
    host='localhost',
    port=6379,
    db=0,
    max_connections=50,
    socket_timeout=5,
    socket_connect_timeout=2,
    retry_on_timeout=True
)

# Использование
r = redis.Redis(connection_pool=pool)
r.set('key', 'value')
r.get('key')

# Закрытие пула
pool.disconnect()
```

**Настройка параметров:**
```python
import redis

r = redis.Redis(
    host='localhost',
    port=6379,
    max_connections=100,
    socket_timeout=5,
    socket_connect_timeout=2,
    retry_on_timeout=True,
    retry=redis.retry.Retry(redis.backoff.ExponentialBackoff(cap=2, base=0.5), 3),
    health_check_interval=30
)
```

**Валидация конфигурации:**
```python
import redis

r = redis.Redis(
    host='localhost',
    port=6379,
    max_connections=50,
    socket_timeout=5,
    socket_connect_timeout=2,
    retry_on_timeout=True
)

# Проверка подключения
r.ping()

# Проверка работоспособности пула
info = r.info('clients')
print(f"Connected clients: {info['connected_clients']}")
```

### Python (asyncio + redis-py)

```python
import asyncio
import redis.asyncio as redis

async def main():
    pool = redis.ConnectionPool(
        host='localhost',
        port=6379,
        max_connections=50,
        socket_timeout=5,
        socket_connect_timeout=2,
        retry_on_timeout=True
    )
    r = redis.Redis(connection_pool=pool)
    await r.set('key', 'value')
    value = await r.get('key')
    await pool.disconnect()

asyncio.run(main())
```

### Go (go-redis)

```go
import (
    "context"
    "time"
    "github.com/redis/go-redis/v9"
)

func NewRedisClient() *redis.Client {
    return redis.NewClient(&redis.Options{
        Addr:         "localhost:6379",
        PoolSize:     50,
        MinIdleConns: 10,
        MaxRetries:   3,
        DialTimeout:  2 * time.Second,
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 5 * time.Second,
    })
}

// Использование
func main() {
    r := NewRedisClient()
    ctx := context.Background()
    err := r.Set(ctx, "key", "value", 0).Err()
    if err != nil {
        panic(err)
    }
    val, err := r.Get(ctx, "key").Result()
    if err != nil {
        panic(err)
    }
    fmt.Println(val)
}
```

### Java (Jedis)

```java
import redis.clients.jedis.Jedis;
import redis.clients.jedis.JedisPool;
import redis.clients.jedis.JedisPoolConfig;

JedisPoolConfig config = new JedisPoolConfig();
config.setMaxTotal(100);
config.setMaxIdle(50);
config.setMinIdle(10);
config.setTestOnBorrow(true);
config.setTestOnReturn(true);
config.setMaxWaitMillis(3000);

JedisPool pool = new JedisPool(config, "localhost", 6379, 5000, "password");

try (Jedis jedis = pool.getResource()) {
    jedis.set("key", "value");
    String value = jedis.get("key");
}
```

### Node.js (ioredis)

```javascript
const Redis = require('ioredis');

const redis = new Redis({
  host: 'localhost',
  port: 6379,
  maxRetriesPerRequest: 3,
  retryStrategy(times) {
    const delay = Math.min(times * 50, 2000);
    return delay;
  },
  connectTimeout: 2000,
  lazyConnect: true
});

(async () => {
  await redis.connect();
  await redis.set('key', 'value');
  const value = await redis.get('key');
  await redis.quit();
})();
```

### Memcached

**Python (pylibmc):**
```python
import pylibmc

mc = pylibmc.Client(
    ['127.0.0.1:11211'],
    binary=True,
    behaviors={
        'tcp_nodelay': 1,
        'no_block': 1,
        'ketama': 1,
        'remove_failed': 1,
        'retry_timeout': 1,
        'dead_timeout': 30,
        'max_pool_connections': 50
    }
)

mc.set('key', 'value', time=3600)
value = mc.get('key')
```

**Go (gomemcache):**
```go
import "github.com/bradfitz/gomemcache/memcache"

func NewMemcachedClient() *memcache.Client {
    return memcache.New("127.0.0.1:11211")
}
```

## Операции и команды

### Диагностика соединений со стороны сервера

**CLIENT LIST** — вывод списка всех соединений:
```bash
redis-cli CLIENT LIST
```

Пример вывода:
```
id=5 addr=127.0.0.1:54321 fd=7 name= age=123456 idle=0 flags=N db=0 cmd=GET
id=6 addr=127.0.0.1:54322 fd=8 name= age=123450 idle=5 flags=N db=0 sub=0 psub=0 multi=-1 qbuf=0 qbuf-free=32768 argv-mem=10 obl=0 oll=0 omem=0 events=r cmd=SET
```

Ключевые поля:
- `id` — уникальный идентификатор соединения
- `addr` — адрес клиента
- `fd` — файловый дескриптор
- `idle` — секунд простоя
- `cmd` — последняя команда
- `qbuf` — размер выходного буфера (большое значение = медленный клиент)

**CLIENT KILL** — принудительное закрытие соединения:
```bash
redis-cli CLIENT KILL id 5
redis-cli CLIENT KILL addr 127.0.0.1:54321
redis-cli CLIENT KILL type pubsub
redis-cli CLIENT KILL idle 600
```

**CLIENT SETNAME** — задание имени соединению:
```bash
redis-cli CLIENT SETNAME myapp-worker-1
```

**INFO clients** — статистика соединений:
```bash
redis-cli INFO clients
```

Пример вывода:
```
connected_clients:25
client_recent_max_input_buffer:8
client_recent_max_output_buffer:0
blocked_clients:0
```

**SLOWLOG GET** — проверка медленных команд:
```bash
redis-cli SLOWLOG GET 10
```

**CLIENT UNBLOCK** — разблокировка клиента (Redis 6.2+):
```bash
redis-cli CLIENT UNBLOCK <client-id> TIMEOUT
```

### Диагностика файловых дескрипторов

```bash
# Текущий лимит FDs
cat /proc/$(pidof redis-server)/limits | grep "open files"

# Использование FDs Redis
ls /proc/$(pidof redis-server)/fd | wc -l

# Системный лимит
cat /proc/sys/fs/file-max
```

## Лучшие практики

### Размер пула

Для in-memory систем (Redis/Memcached) формула из JDBC не применима. Используйте эмпирические правила:

- **Минимальный размер:** 10 соединений (для dev / низконагруженных сервисов)
- **Рекомендуемый размер:** `(CPU_cores * 2) + 10`
- **Максимальный размер:** 500 соединений на инстанс приложения

Пример: 4-core сервер → `pool_size = 4 * 2 + 10 = 18`. Для high-load: `pool_size = 50`.

**Ограничение:** сумма `pool_size` всех инстансов приложения должна быть меньше `maxclients` на сервере Redis с запасом 20% на системные соединения (Sentinel, Cluster bus, репликация).

### Health checks

Включите периодическую проверку соединений для обнаружения stale connections:

**redis-py:**
```python
r = redis.Redis(
    health_check_interval=30,
    socket_connect_timeout=2
)
```

**go-redis:**
```go
r := redis.NewClient(&redis.Options{
    PoolSize: 50,
})
```

go-redis проверяет соединения автоматически при получении из пула.

**Jedis:**
```java
config.setTestOnBorrow(true);
config.setTestOnReturn(true);
```

### Обработка ошибок

**Retry логика:**
```python
import redis

r = redis.Redis(
    retry=redis.retry.Retry(
        redis.backoff.ExponentialBackoff(cap=2, base=0.5),
        3
    ),
    retry_on_timeout=True,
    retry_on_error=[redis.ConnectionError, redis.TimeoutError]
)
```

**Circuit Breaker:**
```python
class ConnectionPoolCircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = "closed"
        self.last_failure_time = 0

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def allow_request(self):
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                return True
            return False
        return True
```

### Конфигурация сервера

Убедитесь, что сервер Redis/Memcached корректно настроен для работы с пулами:

```bash
# redis.conf
maxclients 10000
tcp-backlog 511
tcp-keepalive 300
save ""
appendonly no

# sysctl
net.core.somaxconn = 65535
net.ipv4.tcp_keepalive_time = 300
fs.file-max = 100000
```

### Валидация после изменений

После изменения конфигурации пула или сервера проверьте:

```bash
# Проверка лимита соединений
redis-cli CONFIG GET maxclients
redis-cli INFO clients

# Проверка FDs
cat /proc/$(pidof redis-server)/limits | grep "open files"

# Проверка TCP-очереди
ss -tlnp | grep 6379
cat /proc/sys/net/core/somaxconn

# Проверка rejected connections
redis-cli INFO stats | grep rejected
```

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Connection refused | Лимит maxclients исчерпан | `redis-cli INFO clients` | Увеличьте `maxclients` или уменьшите pool_size |
| Timeout errors | Сетевые проблемы или перегрузка | `redis-cli INFO stats` | Увеличьте `socket_timeout`, проверьте сеть |
| Stale connections | Соединение закрыто сервером | `redis-cli CLIENT LIST` | Настройте `health_check_interval` |
| Memory pressure | Слишком большой пул | `ps aux \| grep python` | Уменьшите pool_size |
| High latency | Недостаток соединений | `redis-cli SLOWLOG GET 10` | Увеличьте pool_size |
| EMFILE/ENFILE | Исчерпание FDs | `cat /proc/$(pidof redis-server)/limits` | Увеличьте `ulimit -n` |
| Connection reset | NAT/Firewall разорвал соединение | `redis-cli CLIENT LIST \| grep idle` | Уменьшите `socket_timeout`, включите keepalive |
| Thundering herd | Много инстансов одновременно создают соединения | `redis-cli INFO clients \| grep connected` | Добавьте jitter к инициализации пула |

## Дополнительная информация

### Мониторинг

```bash
# Количество соединений
redis-cli INFO clients | grep connected_clients

# Лимит соединений
redis-cli INFO clients | grep maxclients

# Блокированные клиенты
redis-cli INFO clients | grep blocked_clients

# Slow log
redis-cli SLOWLOG GET 10

# Список соединений с idle
redis-cli CLIENT LIST | grep idle
```

### SRE Runbook

**Пороги алертинга:**

| Метрика | Источник | Порог | Действие |
| :--- | :--- | :--- | :--- |
| `connected_clients` | `INFO clients` | > 80% maxclients | Проверить утечки, уменьшить pool_size |
| `blocked_clients` | `INFO clients` | > 0 | Проверить блокирующие команды (BLPOP, XREAD) |
| `client_recent_max_input_buffer` | `INFO clients` | > 1MB | Проверить медленных клиентов |
| `rejected_connections_total` | `INFO stats` | > 0 | Увеличить maxclients или tcp-backlog |

**Валидация после изменений:**
```bash
# 1. Проверка лимита соединений
redis-cli CONFIG GET maxclients
redis-cli INFO clients | grep connected_clients

# 2. Проверка FDs
cat /proc/$(pidof redis-server)/limits | grep "open files"
ls /proc/$(pidof redis-server)/fd | wc -l

# 3. Проверка rejected
redis-cli INFO stats | grep rejected

# 4. Проверка slow log
redis-cli SLOWLOG GET 10
```

### Алертинг

```yaml
groups:
  - name: redis_connection_alerts
    rules:
      - alert: RedisConnectionPoolExhausted
        expr: redis_connected_clients / redis_maxclients > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Пул соединений Redis близок к исчерпанию"
          description: "Использовано {{ $value | humanizePercentage }} лимита соединений."

      - alert: RedisConnectionLeak
        expr: rate(redis_connected_clients[5m]) > 0 and rate(redis_disconnected_clients[5m]) == 0
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Возможна утечка соединений Redis"
          description: "Соединения растут, но не освобождаются."
```

### Взаимодействие с ОС

- **File Descriptors:** убедитесь, что `ulimit -n` достаточно для `pool_size + maxclients + 100` (запас под системные соединения)
- **TCP Keepalive:** настройте `tcp-keepalive 300` для предотвращения разрыва неактивных соединений
- **TIME_WAIT:** при высокой нагрузке используйте `net.ipv4.tcp_tw_reuse=1`
- **TCP Backlog:** увеличьте `net.core.somaxconn` до 65535, чтобы сервер мог принимать больше незавершённых соединений

### Особенности для Redis Sentinel и Cluster

При работе с Redis Sentinel или Cluster учитывайте:
- Каждый Sentinel-инстанс требует отдельного пула соединений
- При failover пул автоматически переподключается к новому мастеру, но старые соединения могут оставаться в состоянии `MOVE`/`ASK`
- Используйте `retry_on_error` с `ResponseError` для автоматической обработки `MOVED`/`ASK` ответов

### Связанные темы

- [Обзор кэширования](./caching_overview.md) — управление соединениями
- [Паттерны кэширования](./caching_patterns.md) — реализация пулов
- [Redis Sentinel и Cluster](./caching_redis_ha.md) — failover и пулы
- [Продвинутая отладка Redis](./caching_advanced_debugging.md) — диагностика соединений
