# Распределенные блокировки с Redis/Valkey

**Актуально для:** Redis 7.4–8.2, Valkey 8.x

## Определения

**Распределенная блокировка (Distributed Lock)** — механизм синхронизации между несколькими процессами или сервисами, который гарантирует, что только один владелец может выполнять критическую секцию в определенный момент времени.

**Redlock** — алгоритм распределенных блокировок, предложенный Salvatore Sanfilippo (автором Redis). Использует несколько независимых инстансов Redis для достижения консенсуса.

**TTL (Time-To-Live)** — время жизни блокировки, после которого она автоматически освобождается. Защита от deadlock при падении владельца.

**Owner ID** — уникальный идентификатор владельца блокировки (обычно UUID). Позволяет атомарно проверять и освобождать только свою блокировку.

**Lock Extension** — механизм продления времени жизни блокировки до завершения критической секции.

## Основные концепции

### Требования к распределенным блокировкам

1. **Mutual Exclusion:** только один клиент может держать блокировку
2. **Deadlock Free:** блокировка автоматически освобождается по TTL
3. **Fault Tolerance:** блокировка может быть получена даже при частичном отказе Redis
4. **Release Guarantee:** только владелец может освободить блокировку

### Алгоритм Redlock

Redlock использует N независимых инстансов Redis (рекомендуется N=5):

1. Клиент получает текущее время в миллисекундах
2. Клиент пытается получить блокировку на всех N инстансах последовательно:
   - `SET lock:resource <owner_id> NX PX <ttl>`
   - Таймаут на получение: `ttl / N - overhead`
3. Клиент вычисляет общее время получения блокировки
4. Если блокировка получена на большинстве инстансов (quorum) и общее время < TTL — блокировка считается успешной
5. Владелец выполняет критическую секцию
6. Владелец освобождает блокировку на всех инстансах

### Сложности реализации

**Clock Drift:** разница во времени между серверами может привести к преждевременному освобождению блокировки.

**GC Pause:** паузы Garbage Collection могут привести к истечению TTL блокировки, даже если владелец активен.

**Network Partitions:** разделение сети может привести к ситуации, когда блокировка получена на части инстансов.

**Redis Restart and Delayed Recovery:** после аварийного перезапуска Redis без персистентности или с AOF `fsync=everysec` ключ блокировки может исчезнуть. Для гарантии безопасности требуется задержка перезапуска на время, превышающее максимальный TTL блокировки, чтобы все активные блокировки успели истечь.

**Replication is Not Suitable for Locks:** асинхронная репликация Redis/Valkey не гарантирует, что ключ блокировки записан на реплике до подтверждения мастеру. Использование реплик в Redlock недопустимо — все N инстансов должны быть независимыми мастерами.

## Предварительные требования

### Аппаратные и программные требования

- **Redis/Valkey версии:** Redis 7.4+ или Valkey 8.x (совместимость на уровне протокола с Redis OSS 7.2+)
- **Количество инстансов:** 5 независимых мастер-нод (не реплик) на отдельных хостах или в разных availability zones
- **Сеть:** низкая латентность между инстансами (< 1 мс внутри дата-центра). Рекомендуется один дата-центр; междатацентровый Redlock (> 5 мс) снижает время безопасности и увеличивает окно race condition
- **Часы:** синхронизация времени через NTP на всех хостах (максимальный drift < 10 мс). Без NTP алгоритм небезопасен из-за зависимости от относительного времени
- **Персистентность:** для критичных сценариев включите AOF с `fsync=always` или используйте отложенный перезапуск (delayed restart) после сбоя

### Почему реплики не подходят

Асинхронная репликация Redis/Valkey означает, что запись может быть подтверждена мастером, но не достичь реплики. При failover реплика может получить роль мастера, не зная о существовании блокировки. Redlock требует независимых мастер-нод без репликации между ними.

## Практические сценарии

### Базовая блокировка (Single Redis)

Базовый пример `SET ... NX PX` + Lua-освобождение уже приведен в [Обзор Redis](../../Databases/redis_overview.md). Здесь сосредоточимся на продвинутых сценариях: Redlock, автоматическое продление, критика алгоритма.

### Redlock (5 инстансов)

```python
import redis
import uuid
import time

class Redlock:
    def __init__(self, redis_instances, ttl=30000):
        self.instances = [redis.Redis(host=host, port=port, decode_responses=True) 
                         for host, port in redis_instances]
        self.ttl = ttl
        self.quorum = len(redis_instances) // 2 + 1

    def lock(self, resource):
        owner_id = str(uuid.uuid4())
        lock_key = f"redlock:{resource}"
        
        start_time = time.time() * 1000
        acquired = 0
        
        for r in self.instances:
            try:
                if r.set(lock_key, owner_id, nx=True, px=self.ttl):
                    acquired += 1
            except redis.ConnectionError:
                continue
        
        elapsed = (time.time() * 1000) - start_time
        
        # Блокировка успешна, если получена на quorum и время < TTL
        if acquired >= self.quorum and elapsed < self.ttl:
            return owner_id, self.ttl - elapsed
        else:
            # Освободить частично полученные блокировки
            self.unlock(resource, owner_id)
            return None, 0

    def unlock(self, resource, owner_id):
        lock_key = f"redlock:{resource}"
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        
        for r in self.instances:
            try:
                r.eval(script, 1, lock_key, owner_id)
            except redis.ConnectionError:
                continue

# Использование
redlock = Redlock([
    ('10.0.0.10', 6379),
    ('10.0.0.20', 6379),
    ('10.0.0.30', 6379),
    ('10.0.0.40', 6379),
    ('10.0.0.50', 6379)
], ttl=30000)

owner_id, remaining = redlock.lock("resource:123")
if owner_id:
    try:
        print(f"Блокировка получена, осталось {remaining}ms")
        # Критическая секция
        time.sleep(1)
    finally:
        redlock.unlock("resource:123", owner_id)
else:
    print("Блокировка не получена")
```

**Валидация:**
```bash
# Проверка блокировки на одном из инстансов
redis-cli -h 10.0.0.10 GET redlock:resource:123
# → <owner_id>

redis-cli -h 10.0.0.10 TTL redlock:resource:123
# → 29 (примерно, уменьшается со временем)

# После освобождения
redis-cli -h 10.0.0.10 GET redlock:resource:123
# → nil
```

### Блокировка с автоматическим продлением

```python
import redis
import uuid
import time
import threading

class ExtendableLock:
    def __init__(self, r, lock_name, ttl=30000, extension_interval=10000):
        self.r = r
        self.lock_name = lock_name
        self.ttl = ttl
        self.extension_interval = extension_interval
        self.owner_id = str(uuid.uuid4())
        self.lock_key = f"lock:{lock_name}"
        self.stop_event = threading.Event()

    def acquire(self):
        if self.r.set(self.lock_key, self.owner_id, nx=True, px=self.ttl):
            # Запуск фонового продления
            threading.Thread(target=self._extend, daemon=True).start()
            return True
        return False

    def _extend(self):
        while not self.stop_event.is_set():
            time.sleep(self.extension_interval / 1000)
            try:
                # Lua-скрипт для атомарного продления
                script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("pexpire", KEYS[1], ARGV[2])
                else
                    return 0
                end
                """
                self.r.eval(script, 1, self.lock_key, self.owner_id, self.ttl)
            except redis.ConnectionError:
                continue

    def release(self):
        self.stop_event.set()
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        self.r.eval(script, 1, self.lock_key, self.owner_id)

# Использование
lock = ExtendableLock(r, "resource:123", ttl=30000)
if lock.acquire():
    try:
        print("Блокировка получена с автоматическим продлением")
        # Длительная критическая секция
        time.sleep(60)
    finally:
        lock.release()
```

### Пошаговая настройка окружения Redlock

**1. Подготовка хостов (5 независимых мастер-нод):**

```bash
# На каждом хосте установите Redis или Valkey
# Пример для Ubuntu/Debian:
apt-get install redis-server -y

# Отредактируйте redis.conf:
# - bind 0.0.0.0 (или конкретный внутренний IP)
# - protected-mode no
# - requirepass <strong_password>
# - port 6379
```

**2. Проверка независимости нод:**

```bash
# Каждый инстанс должен быть независимым мастером без репликации
redis-cli -h 10.0.0.10 INFO replication
# → role:master
# → connected_slaves:0

redis-cli -h 10.0.0.20 INFO replication
# → role:master
# → connected_slaves:0
```

**3. Проверка синхронизации времени (NTP):**

```bash
# Проверка смещения часов на всех хостах
chronyc tracking
# → System time: ... 
# → Last offset: ... (должно быть < 10 мс)

# Или через ntpq
ntpq -p
# → remote refid st t when poll reach delay offset jitter
# → *10.0.0.1 .GPS. 1 u 12 64 377 0.12345 0.00234 0.00123
```

**4. Тестирование базовой блокировки на одном инстансе:**

```bash
# Получение блокировки
redis-cli -h 10.0.0.10 SET lock:test "owner-1" NX PX 30000
# → OK

# Проверка TTL
redis-cli -h 10.0.0.10 TTL lock:test
# → 29

# Освобождение (только владелец)
redis-cli -h 10.0.0.10 EVAL "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end" 1 lock:test "owner-1"
# → 1
```

## Лучшие практики

### Надежность
- Используйте TTL для всех блокировок (защита от deadlock)
- Используйте уникальный Owner ID (UUID) для каждой блокировки
- Освобождайте блокировку атомарно через Lua-скрипт
- Используйте Redlock только для критичных сценариев, где требуется высокая доступность

### Производительность
- Используйте фиксированный TTL (не увеличивайте бесконечно)
- Ограничьте время удержания блокировки
- Используйте connection pooling для минимизации overhead
- Мониторьте время удержания блокировок

### Безопасность
- Никогда не делитесь Owner ID между процессами
- Используйте TLS для шифрования трафика
- Ограничьте доступ к командам управления блокировками ACL

### Очистка и восстановление

**Принудительное освобождение зависшей блокировки:**

```bash
# Проверка блокировки
redis-cli -h 10.0.0.10 GET redlock:resource:123

# Принудительное удаление (если владелец недоступен)
redis-cli -h 10.0.0.10 DEL redlock:resource:123
```

**Поиск устаревших блокировок:**

```bash
# Найти все блокировки с истекающим TTL
redis-cli -h 10.0.0.10 --bigkeys
redis-cli -h 10.0.0.10 DBSIZE

# Проверить TTL конкретной блокировки
redis-cli -h 10.0.0.10 TTL redlock:resource:123
# → -2 (ключ не существует/удален)
# → -1 (ключ существует без TTL — критично!)
```

**Восстановление после частичного сбоя Redlock:**

Если блокировка была получена на 3 из 5 инстансов и владелец упал:
1. TTL истечет автоматически на всех инстансах через заданное время
2. При перезапуске владельца новый `owner_id` позволит получить блокировку заново
3. Для немедленного восстановления удалите ключи вручную на всех 5 инстансах

## Устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Блокировка не освобождается | Клиент упал без release | `redis-cli GET lock:resource` | Используйте TTL для автоматического освобождения |
| Deadlock | Слишком длинная критическая секция | Логи приложения | Увеличьте TTL или уменьшите время удержания |
| Потеря блокировки | GC pause привел к истечению TTL | Проверка GC настроек | Увеличьте TTL или используйте watchdog |
| Split-brain | Два клиента держат блокировку | Проверка блокировок | Используйте Redlock для критичных сценариев |
| Невозможно получить блокировку | Слишком короткий TTL при высокой латентности | `redis-cli --latency` | Увеличьте TTL или оптимизируйте сеть |
| Блокировка получена, но данные неактуальны | Слишком долгое удержание без продления | Логи времени удержания | Используйте механизм Lock Extension |
| CLOCK DRIFT | Разница во времени между нодами | `chronyc tracking` на всех хостах | Настройте NTP, ограничьте максимальный drift |
| Частичный отказ инстанса | Один из 5 Redis недоступен | `redis-cli -h <host> PING` | Убедитесь, что quorum (3 из 5) достижим |

## Дополнительная информация

### Альтернативы Redlock

**Consul:** использует Raft consensus для распределенных блокировок. Более надежный, чем Redlock, но требует отдельный сервис.

**etcd:** использует Raft и leases для блокировок. Интегрирован с Kubernetes.

**ZooKeeper:** использует ephemeral nodes для блокировок. Надежный, но сложный в эксплуатации.

**PostgreSQL:** использует advisory locks (`pg_advisory_lock`). Простой, если у вас уже есть PostgreSQL.

### Критика Redlock

Алгоритм Redlock подвергается критике со стороны сообщества:
1. **Clock drift:** разница во времени может привести к преждевременному освобождению
2. **GC pauses:** паузы сборки мусора могут привести к истечению TTL
3. **Network partitions:** разделение сети может привести к потерям

**Рекомендация:** используйте Redlock только для не критичных сценариев. Для критичных use cases используйте Consul или etcd.

### Мониторинг

```bash
# Проверка блокировок
redis-cli KEYS lock:*
redis-cli TTL lock:resource:123

# Проверка задержки сети к инстансам Redlock
redis-cli --latency -h 10.0.0.10
redis-cli --latency -h 10.0.0.20
redis-cli --latency -h 10.0.0.30

# Проверка фрагментации памяти
redis-cli INFO memory | grep mem_fragmentation_ratio
# → mem_fragmentation_ratio: 1.08 (норма: 1.0–1.5)

# Проверка блокированных клиентов
redis-cli INFO clients | grep blocked_clients
# → blocked_clients:0 (рост — признак проблем)
```

### Связанные темы

- [Паттерны кэширования](./caching_patterns.md) — реализация блокировок
- [Обзор кэширования](./caching_overview.md) — управление состоянием
- [Redis: высокая доступность](./caching_redis_ha.md) — Sentinel и Cluster
- [Concepts/Idempotency](../../Concepts/idempotency.md) — идемпотентность
