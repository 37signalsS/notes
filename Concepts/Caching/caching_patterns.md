# Паттерны кэширования

## Определения

**Паттерны кэширования** — это типовые архитектурные стратегии взаимодействия приложения с кэшем и основным хранилищем данных (Database). Выбор паттерна определяет баланс между производительностью (Latency), согласованностью данных (Consistency) и устойчивостью системы к сбоям.

С точки зрения SRE, паттерны кэширования являются инструментом управления **радиусом поражения (Blast Radius)** и обеспечения **деградации функциональности (Graceful Degradation)**. Основная сложность заключается в решении проблемы **Dual Writes** (двойной записи), когда обновление двух независимых систем (БД и кэша) не является атомарным, что может привести к рассинхронизации.

Для ознакомления с уровнями и метриками кэширования см. [общий обзор кэширования](./caching_overview.md).

## Основные концепции

### Стратегии чтения (Read Patterns)

Выбор стратегии чтения напрямую влияет на задержку первого запроса и нагрузку на БД при «холодном» старте.

*   **Cache-aside (Lazy Loading / Ленивая загрузка):**
    *   Приложение сначала проверяет кэш. Если данных нет (*Cache Miss*), оно читает их из БД, записывает в кэш и возвращает пользователю.
    *   **Преимущества:** Устойчивость к сбоям кэша (приложение идет в БД), гибкость данных (кэшируются только реально нужные объекты).
    *   **Недостатки:** Задержка при первом запросе (три операции: кэш → БД → запись в кэш), риск рассинхронизации при обновлении БД.
*   **Read-through (Сквозное чтение):**
    *   Приложение запрашивает данные только у кэша. Кэш-слой (библиотека или прокси) сам загружает данные из БД при их отсутствии.
    *   **Механизм Single-flight:** В высоконагруженных системах `Read-through` часто дополняется механизмом «схлопывания» запросов (Request Collapsing), когда сотни запросов за одним ключом ждут одного ответа от БД, предотвращая [Thundering Herd](./caching_overview.md#типовые-проблемы-и-стратегии-решения).
    *   **Преимущества:** Чистый код приложения, упрощенная логика (приложение «не знает» о БД).
*   **Refresh-ahead (Проактивное обновление):**
    *   Кэш автоматически обновляет «горячие» записи до истечения их TTL. Это происходит на основе анализа популярности данных или по расписанию.
    *   **Преимущества:** Нулевая задержка (Latency) для пользователя, так как данные всегда актуальны и «разогреты».
    *   **Недостатки:** Сложность реализации предсказания популярности, риск лишней нагрузки на БД при обновлении неиспользуемых данных.

### Стратегии записи (Write Patterns)

*   **Write-through (Сквозная запись):**
    *   Данные записываются в кэш и БД одновременно в рамках одной транзакции или последовательно.
    *   **Преимущества:** Высокая согласованность, данные всегда актуальны в кэше.
    *   **Недостатки:** Увеличенная задержка записи (две сетевые операции). Если кэш недоступен, запись может завершиться ошибкой (зависит от политики Failover).
*   **Write-around:**
    *   Данные записываются только в БД. В кэш они попадают только при последующем чтении (обычно через Cache-aside).
    *   **Преимущества:** Кэш не забивается данными, которые могут никогда не понадобиться (например, логи или архивные данные). Снижает «замусоривание» кэша.
*   **Write-back (Write-behind / Обратная запись):**
    *   Данные пишутся только в кэш и мгновенно подтверждаются. В БД они сбрасываются асинхронно через интервал времени или при достижении определенного объема изменений.
    *   **Преимущества:** Максимальная производительность записи, возможность агрегации (Batching) нескольких обновлений одной записи в один запрос к БД.
    *   **Недостатки:** Риск потери данных при сбое кэша до момента их записи в БД. Требует сложной логики обработки ошибок при записи в БД (Retry, Dead Letter Queues).

### Проблемы согласованности и их решение

1.  **Гонка данных (Race Condition) при Cache-aside:**
    *   *Сценарий:* Поток А читает из БД (промах кэша), Поток Б обновляет БД и удаляет из кэша, Поток А записывает в кэш старое значение, которое прочитал ранее.
    *   **Решение:** **Delayed Double Deletion** (Отложенное двойное удаление) — приложение удаляет ключ из кэша, обновляет БД и через короткий интервал (например, 500 мс) удаляет ключ повторно, чтобы затереть возможные «грязные» записи от параллельных потоков.

2.  **Проблема Dual Writes и атомарности:**
    *   Если запись в БД прошла успешно, а инвалидация кэша провалилась, данные разойдутся.
    *   **Решение 1 (Modern):** **Change Data Capture (CDC)**. Инструменты типа Debezium читают Transaction Log базы данных и гарантированно доставляют событие изменения в кэш. Детальное описание паттерна см. в **[Архитектурные паттерны CDC](../../Databases/Concepts/cdc_architectural_patterns.md)**.
    *   **Решение 2:** **Transactional Outbox**. Приложение пишет бизнес-данные и событие изменения в одну транзакцию БД (в специальную таблицу `outbox`). Отдельный процесс читает таблицу и обновляет кэш. Это гарантирует атомарность без использования CDC на уровне логов.

3.  **Выбор: Обновление или Инвалидация?**
    *   **Инвалидация (Удаление):** Проще в реализации, меньше риск гонки данных. Приложение просто удаляет ключ, и следующий запрос загрузит свежие данные.
    *   **Обновление (Запись значения):** Экономит один запрос к БД при чтении, но требует передачи всего объекта в событии и подвержено риску нарушения порядка сообщений (Ordering).

## Сравнение паттернов

| Паттерн | Согласованность | Latency (Чтение) | Latency (Запись) | Сложность |
| :--- | :--- | :--- | :--- | :--- |
| **Cache-aside** | Слабая (Eventual) | Высокая (Hits) | Низкая | Низкая |
| **Read-through** | Средняя | Высокая (Hits) | Средняя | Средняя |
| **Write-through** | Высокая (Strong) | Высокая | Высокая | Средняя |
| **Write-around** | Средняя | Средняя | Низкая | Низкая |
| **Write-back** | Низкая | Максимальная | Максимальная | Высокая |

## Практические сценарии

### Cache-aside: Nginx + Redis (микрокэширование)

Паттерн Cache-aside на уровне прокси-сервера — один из самых распространенных в DevOps-практикаках. Микрокэширование (1–5 секунд) защищает бэкенд от всплесков трафика.

**Конфигурация Nginx:**
```nginx
proxy_cache_path /data/nginx/cache levels=1:2 keys_zone=api_cache:10m max_size=1g inactive=60m use_temp_path=off;

upstream backend {
    server 127.0.0.1:8080;
}

server {
    listen 80;

    location /api/v1/users {
        proxy_cache api_cache;
        proxy_cache_valid 200 1s;
        proxy_cache_valid 404 10s;
        proxy_cache_lock on;          # Защита от Thundering Herd
        proxy_cache_lock_timeout 5s;
        proxy_cache_use_stale error timeout updating http_500 http_502 http_503;
        proxy_cache_background_update on;

        add_header X-Cache-Status $upstream_cache_status;

        proxy_pass http://backend;
    }
}
```

**Валидация:**
```bash
nginx -t && systemctl reload nginx

# Проверка: первый запрос (MISS), повторный (HIT)
curl -sI "http://localhost/api/v1/users/1" | grep X-Cache-Status
# → X-Cache-Status: MISS

curl -sI "http://localhost/api/v1/users/1" | grep X-Cache-Status
# → X-Cache-Status: HIT
```

### Cache-aside: Redis + приложение (Python)

Реализация Cache-aside с защитой от Thundering Herd через распределенную блокировку:

```python
import time
import random
import redis
from contextlib import contextmanager

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

@contextmanager
def distributed_lock(lock_name, timeout=10):
    acquired = redis_client.set(lock_name, "locked", nx=True, ex=timeout)
    try:
        yield acquired
    finally:
        if acquired:
            redis_client.delete(lock_name)

def get_user_profile(user_id):
    cache_key = f"user:{user_id}:profile"

    profile = redis_client.get(cache_key)
    if profile:
        return profile

    lock_key = f"lock:{cache_key}"
    with distributed_lock(lock_key) as acquired:
        if acquired:
            profile = redis_client.get(cache_key)
            if profile:
                return profile

            profile = db_query(user_id)

            ttl = 3600 + random.randint(-60, 60)
            redis_client.set(cache_key, profile, ex=ttl)
            return profile
        else:
            time.sleep(0.05)
            return get_user_profile(user_id)

def db_query(user_id):
    return f"profile_data_for_{user_id}"
```

### Read-through: Go + Redis с singleflight

В Go-приложениях паттерн `Read-through` реализуется через `singleflight.Group`, который «схлопывает» параллельные запросы к одному ключу:

```go
package main

import (
    "context"
    "sync"
    "time"

    "github.com/redis/go-redis/v9"
    "golang.org/x/sync/singleflight"
)

var (
    rdb  = redis.NewClient(&redis.Options{Addr: "localhost:6379"})
    sfg  singleflight.Group
)

func GetUserProfile(ctx context.Context, userID string) (string, error) {
    cacheKey := "user:" + userID + ":profile"

    val, err := rdb.Get(ctx, cacheKey).Result()
    if err == nil {
        return val, nil
    }

    result, err, _ := sfg.Do(cacheKey, func() (interface{}, error) {
        profile, dbErr := dbQuery(ctx, userID)
        if dbErr != nil {
            return nil, dbErr
        }

        ttl := 3600 + time.Duration(randomJitter(60))*time.Second
        rdb.Set(ctx, cacheKey, profile, ttl)
        return profile, nil
    })

    if err != nil {
        return "", err
    }
    return result.(string), nil
}

func dbQuery(ctx context.Context, userID string) (string, error) {
    time.Sleep(50 * time.Millisecond)
    return "profile_data_for_" + userID, nil
}

func randomJitter(maxSec int) int {
    return time.Now().Nanosecond()%maxSec - maxSec/2
}
```

### Write-through: Nginx + Redis (обновление через API)

Write-through реализуется, когда приложение обновляет БД и кэш последовательно. Пример: REST API, который записывает в PostgreSQL и одновременно обновляет Redis:

```python
import redis
import psycopg2

r = redis.Redis(host='localhost', port=6379, decode_responses=True)
conn = psycopg2.connect("dbname=mydb user=app")
conn.autocommit = False

def update_user_profile(user_id, new_data):
    cache_key = f"user:{user_id}:profile"

    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET name=%s, email=%s WHERE id=%s",
            (new_data['name'], new_data['email'], user_id)
        )

        r.set(cache_key, str(new_data), ex=3600)

        conn.commit()
    except Exception:
        conn.rollback()
        r.delete(cache_key)
        raise
```

### Write-around: PostgreSQL + Redis (лендинги, архив)

Write-around эффективен для контента, который записывается редко, но читается часто (лендинги, статические страницы, архивные данные):

```python
import redis
import psycopg2

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def save_landing_page(slug, html_content):
    conn = psycopg2.connect("dbname=mydb user=app")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO landings (slug, content) VALUES (%s, %s) ON CONFLICT (slug) DO UPDATE SET content=%s",
        (slug, html_content, html_content)
    )
    conn.commit()
    cur.close()
    conn.close()

def get_landing_page(slug):
    cache_key = f"landing:{slug}"

    content = r.get(cache_key)
    if content:
        return content

    conn = psycopg2.connect("dbname=mydb user=app")
    cur = conn.cursor()
    cur.execute("SELECT content FROM landings WHERE slug=%s", (slug,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row:
        r.set(cache_key, row[0], ex=86400)
        return row[0]

    return None
```

### Write-back: Redis + PostgreSQL (очередь с буферизацией)

Write-back максимальна по производительности, но требует надежной доставки. Реализация через Redis Stream:

```python
import redis
import psycopg2
import json
import threading

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

STREAM_KEY = "write_back:user_updates"
GROUP_NAME = "db_workers"
CONSUMER_NAME = "worker_1"

def init_stream():
    try:
        r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except redis.exceptions.ResponseError:
        pass

def write_back_producer(user_id, new_data):
    r.xadd(STREAM_KEY, {"user_id": str(user_id), "data": json.dumps(new_data)})
    return True

def write_back_consumer():
    init_stream()
    conn = psycopg2.connect("dbname=mydb user=app")
    conn.autocommit = False

    while True:
        try:
            entries = r.xreadgroup(GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"}, count=10, block=5000)
            if not entries:
                continue

            for stream, messages in entries:
                for msg_id, fields in messages:
                    user_id = fields["user_id"]
                    data = json.loads(fields["data"])

                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE users SET name=%s, email=%s WHERE id=%s",
                        (data['name'], data['email'], user_id)
                    )
                    conn.commit()
                    cur.close()

                    r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        except Exception as e:
            conn.rollback()
            print(f"Error: {e}")
            time.sleep(1)

threading.Thread(target=write_back_consumer, daemon=True).start()
```

### Архитектура инвалидации через CDC (Debezium + Kafka)

Это наиболее надежный современный способ реализации **Write-Through/Write-Behind** эффекта без усложнения кода приложения. Общий архитектурный паттерн описан в **[Архитектурные паттерны CDC](../../Databases/Concepts/cdc_architectural_patterns.md)**.

1.  Приложение пишет только в **PostgreSQL**.
2.  **Debezium** (CDC-коннектор) читает WAL (Write Ahead Log) базы данных.
3.  Событие изменения попадает в топик **Kafka**.
4.  **Consumer** (инвалидатор) читает Kafka и удаляет соответствующий ключ в **Redis**.

**Конфигурация Debezium (JSON):**
```json
{
  "name": "inventory-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "debezium",
    "database.password": "${DB_PASSWORD}",
    "database.dbname": "inventory",
    "database.server.name": "dbserver1",
    "table.include.list": "public.users",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_slot",
    "publication.name": "dbz_publication"
  }
}
```

**Валидация:**
```bash
# Проверка регистрации коннектора
curl -s http://localhost:8083/connectors/inventory-connector/status | jq .connector.state
# → "RUNNING"

# Проверка сообщений в Kafka
kafka-console-consumer --bootstrap-server localhost:9092 \
  --topic dbserver1.public.users \
  --from-beginning --max-messages 5
```

**Результат:** Гарантированная консистентность без распределенных транзакций.

### Цепочка защиты: Circuit Breaker + Fallback

Если кэш-система недоступна, приложение должно переключаться на прямой доступ к БД, чтобы избежать полного отказа (Cascade Failure):

```python
import time
import redis

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

class CacheCircuitBreaker:
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

breaker = CacheCircuitBreaker()

def get_with_fallback(key, db_fetch_fn):
    if not breaker.allow_request():
        return db_fetch_fn()

    try:
        value = r.get(key)
        if value:
            breaker.record_success()
            return value
    except redis.ConnectionError:
        breaker.record_failure()

    value = db_fetch_fn()
    if value:
        try:
            r.set(key, value, ex=3600)
            breaker.record_success()
        except redis.ConnectionError:
            breaker.record_failure()
    return value
```

## Лучшие практики SRE по управлению кэшем

Для обеспечения надежности систем с агрессивным кэшированием рекомендуется придерживаться следующих правил:

1.  **Мониторинг лага записи (Write Lag):** Для паттерна `Write-back` критично отслеживать время между записью в кэш и фиксацией в БД. Рост лага — предвестник потери данных.
2.  **Обработка ошибок (Dead Letter Queues):** Если асинхронная запись в БД провалилась (например, из-за нарушения ограничений целостности), событие должно попадать в DLQ для ручного разбора или автоматического ретрая.
3.  **Circuit Breaker для кэша:** Если система кэширования недоступна, приложение должно уметь автоматически переключаться на работу напрямую с БД (Fallback), чтобы избежать полного отказа сервиса.
4.  **Тестирование «холодного» старта:** Регулярно проводите нагрузочное тестирование с пустым кэшем. База данных должна выдерживать нагрузку при 0% Hit Rate в течение времени, необходимого для прогрева.
5.  **Версионирование кэша:** При изменении структуры данных в приложении используйте префиксы версий в ключах (например, `v1:user:123`, `v2:user:123`), чтобы избежать ошибок десериализации.
6.  **Защита от Big Keys:** В Redis используйте `--bigkeys` для поиска ключей >1 МБ. Разбивайте крупные объекты на части или храните в S3 с кэшированием метаданных.
7.  **Контейнеризация (systemd/cgroup):** При работе с Redis/Memcached в контейнерах настройте лимиты памяти через `memory.limit_in_bytes` (cgroup v1) или `memory.max` (cgroup v2). Убедитесь, что `maxmemory` Redis составляет не более 70% от лимита контейнера, чтобы оставить место для overhead.

## Дополнительная информация

### Выбор паттерна под нагрузку

*   **Read-heavy (Чтение >> Запись):** Однозначно `Cache-aside` или `Read-through`.
*   **Write-heavy (Запись >> Чтение):** `Write-back` с буферизацией в кэше, если допустима небольшая потеря данных.
*   **Strong Consistency:** `Write-through` в транзакции или `Cache-aside` с паттерном `Delayed Double Deletion`.

### Мониторинг паттернов

Критические метрики (Prometheus/Grafana):

| Метрика | Паттерн | Описание | Алерт |
| :--- | :--- | :--- | :--- |
| `cache_hit_ratio_percent` | Все | Эффективность кэширования | < 80% |
| `cache_write_lag_seconds` | Write-back | Время между записью в кэш и фиксацией в БД | > 5 сек |
| `cache_evictions_total` | Все | Частота вытеснения ключей | Рост > 20%/мин |
| `cache_connection_errors_total` | Все | Ошибки подключения к кэшу | > 0 за 1 мин |
| `cache_pending_writes` | Write-back | Размер очереди на запись в БД | > 10000 |
| `cache_invalidation_lag_seconds` | CDC | Задержка инвалидации через CDC | > 10 сек |

**Пример Prometheus-запроса (PromQL):**
```promql
# Hit rate за 5 минут
rate(cache_hits_total[5m]) / (rate(cache_hits_total[5m]) + rate(cache_misses_total[5m])) * 100

# Write lag p95
histogram_quantile(0.95, rate(cache_write_lag_seconds_bucket[5m]))
```

### Диагностика и устранение проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Hit rate < 80% | Недостаточный объем кэша или неэффективный TTL | `redis-cli INFO stats`, `memcached-tool stats` | Увеличить `maxmemory` или оптимизировать TTL |
| Рост latency операций | Фрагментация памяти или блокировки | `redis-cli INFO memory`, `redis-cli SLOWLOG GET` | Включить `activedefrag yes`, проверить bigkeys |
| Write lag растет | БД перегружена или медленные индексы | Мониторинг `cache_write_lag_seconds` | Оптимизировать запросы БД, увеличить concurrency |
| CDC-события не доходят | Debezium-коннектор упал или Kafka недоступна | `curl http://localhost:8083/connectors/<name>/status` | Перезапустить коннектор, проверить Kafka |
| Сессии теряются после рестарта | Нет персистентности | `redis-cli INFO persistence` | Настроить RDB/AOF или вынести сессии в другой сервис |
| `OOM command not allowed` | Исчерпан лимит `maxmemory` | `redis-cli INFO memory \| grep used_memory` | Увеличить `maxmemory` или сменить eviction policy |
| Memory pressure в контейнере | Лимит `memory.limit_in_bytes` (cgroup v1) или `memory.max` (cgroup v2) слишком низок | `cat /sys/fs/cgroup/memory/memory.limit_in_bytes` | Увеличить `memory` limits контейнера |

### Тестирование паттернов (нагрузочное)

**Cache-aside (redis-benchmark):**
```bash
# Базовый тест с Pipeline (100K запросов, 50 соединений)
redis-benchmark -h 127.0.0.1 -p 6379 -c 50 -n 100000 -P 10 -q

# Продвинутый тест (memtier_benchmark)
memtier_benchmark -s 127.0.0.1 -p 6379 -t 4 -c 50 -n 100000 --key-maximum=1000000 --ratio=1:1

# Ожидаемый результат: latency p99 < 1ms для локального Redis
```

**Write-back (имитация нагрузки):**
```bash
# Тест с пользовательским скриптом (Python)
python3 -c "
import redis, time, threading
r = redis.Redis(host='localhost', port=6379)
def writer():
    for i in range(10000):
        r.xadd('test_stream', {'data': f'item_{i}'})
threads = [threading.Thread(target=writer) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()
print('Write-back: 40K items written')
"
```

### Сетевые соображения

*   **Задержка до кэша:** Локальный доступ (localhost) < 0.1 мс, тот же дата-центр (10 Гбит) 0.1–0.5 мс. Междатацентрный доступ 1–50 мс — кэширование неэффективно без мультикэширования.
*   **TCP Keepalive:** Настройте `tcp-keepalive 300` (Redis) или `-o tcp_keepalive` (Memcached) для предотвращения разрыва неактивных соединений.
*   **Проверка задержки:** `redis-cli --latency -h <host>` — норма для локального доступа < 0.5 мс.

### Ограничения и Edge Cases

*   **Однопоточность Redis (основной поток):** Даже с I/O threading, долгие команды (SORT, KEYS, большие множества) блокируют основной поток. Использовать `SCAN` вместо `KEYS`, `SSCAN` вместо `SMEMBERS`.
*   **Race Condition при CDC:** Если Kafka-сообщение обрабатывается медленнее, чем приходит следующее, может возникнуть out-of-order запись. Решение — потребители с сортировкой по timestamp или version.
*   **Split-brain при Redis Cluster:** При сетевом partitions возможна ситуация, когда две ноды считают себя master. Настройте `cluster-require-full-coverage no` для минимизации impact.
*   **Ограничение Memcached на размер объекта:** Максимум 1 МБ (по умолчанию). Увеличивается через `-I` (например, `-I 4m`), но это снижает эффективность Slab Allocator.
*   **Проблема первого запроса:** Первый пользователь всегда платит `Miss Penalty`. Решается через предварительный прогрев кэша (Bulk Load, Shadow Traffic).

### Бэкап и восстановление

*   **Redis (при персистентности):** RDB-снапшоты: автоматические (`save 900 1`) или ручные (`BGSAVE`). AOF: `BGREWRITEAOF`.
*   **Redis (без персистентности):** Полная потеря данных — нормальное поведение для кэша. Recovery: прогрев после перезапуска.
*   **Memcached:** Полная потеря данных при перезапуске — это нормальное поведение для кэша. Recovery strategy: прогрев кэша (Cache Warmup).

**Пример: Ручной снапшот Redis:**
```bash
redis-cli BGSAVE
redis-cli LASTSAVE
# → 1234567890 (Unix timestamp последнего снапшота)
```

### Связанные темы

*   [Кэширование: обзор](./caching_overview.md)
*   [Алгоритмы вытеснения данных](./caching_eviction_policies.md)
