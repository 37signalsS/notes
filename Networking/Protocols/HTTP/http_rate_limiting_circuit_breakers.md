# Rate Limiting и устойчивость HTTP-сервисов

## Определения

**Rate Limiting** — механизм ограничения количества запросов за единицу времени для защиты сервиса от перегрузки, abuse и DDoS. Реализуется на уровне прокси (Nginx, HAProxy) или приложения.

**Circuit Breaker (Прерыватель цепи)** — паттерн устойчивости, который останавливает вызовы к неработающему сервису и возвращает fallback-ответ, предотвращая каскадные отказы.

**Retry (Повторная попытка)** — механизм автоматического повторения запроса при временной ошибке. Требует идемпотентности или `Idempotency-Key`.

**Exponential Backoff** — стратегия повторных попыток с экспоненциально растущей задержкой (1s, 2s, 4s, 8s...), чтобы не перегружать восстановляющийся сервис.

**Jitter** — случайное отклонение задержки при retry, предотвращающее thundering herd (синхронизированные повторы всех клиентов).

**Bulkhead (Ограждение отсеков)** — паттерн изоляции ресурсов (пулов соединений, потоков) для ограничения влияния отказа одного компонента на остальные.

**Burst** — краткосрочный пик запросов, превышающий базовый rate limit. Обрабатывается через очередь или immediate reject.

## Основные концепции

### Алгоритмы Rate Limiting

| Алгоритм | Механизм | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Token Bucket** | Пополнение «жетонов» с постоянной скоростью; запрос тратит жетон | Разрешает burst; прост в реализации | Не гарантирует равномерность во времени |
| **Leaky Bucket** | Запросы «просачиваются» с постоянной скоростью | Равномерный выходной поток | Не разрешает burst; может отбрасывать валидные запросы |
| **Fixed Window** | Ограничение за фиксированный интервал (секунда, минута) | Простой, дешёвый | Проблема на границе окна (burst в конце окна) |
| **Sliding Window** | Окно скользит; учёт каждого запроса с точностью до миллисекунд | Исключает burst на границе | Более высокое потребление памяти |
| **Sliding Window Log** | Хранит временные метки всех запросов за окно | Точный | Память ∝ количеству запросов |
| **Sliding Window Counter** | Аппроксимация через два фиксированных окна | Компромисс точности и памяти | Может незначительно превышать лимит |

### Nginx: директива limit_req

```nginx
# Объявление зоны (10MB = 160 000 IP-адресов)
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

# Применение
location /api/ {
    limit_req zone=api_limit burst=20 nodelay;
    proxy_pass http://api_backend;
}
```

| Параметр | Назначение | Значение |
| :--- | :--- | :--- |
| `zone` | Имя зоны и объём памяти | `api_limit:10m` |
| `rate` | Базовый rate (запросов в секунду) | `10r/s` |
| `burst` | Дополнительные запросы, которые могут быть обработаны | `20` |
| `nodelay` | Обрабатывать burst-запросы без задержки | `nodelay` (или без — с задержкой) |
| `delay` | Количество запросов, обрабатываемых без задержки | `delay=10` |

### Nginx: директива limit_conn

```nginx
limit_conn_zone $binary_remote_addr zone=addr:10m;

server {
    location / {
        limit_conn addr 10;  # максимум 10 соединений с одного IP
        limit_conn_status 429;
    }
}
```

### HAProxy: stick-rate-sessions и maxconn

```haproxy
backend api_servers
    balance roundrobin
    stick-rate-sessions 1
    server app1 10.0.1.10:8080 maxconn 100 check
    server app2 10.0.1.11:8080 maxconn 100 check
```

### Circuit Breaker паттерн

| Состояние | Описание | Поведение |
| :--- | :--- | :--- |
| **Closed (Закрыт)** | Нормальная работа; отслеживаются ошибки | Все запросы проходят |
| **Open (Открыт)** | Превышен порог ошибок | Все запросы сразу возвращают fallback/error |
| **Half-Open (Полуоткрыт)** | Пробная проверка; ограниченное число запросов | Если успех → Closed; если ошибка → Open |

### Retry стратегии

| Стратегия | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Fixed interval** | Повтор через фиксированный интервал | Не использовать в продакшене |
| **Exponential backoff** | 1s, 2s, 4s, 8s... | Стандарт для большинства случаев |
| **Exponential backoff + jitter** | Backoff + случайное отклонение | Рекомендуется для распределённых систем |
| **Decorrelated jitter** | Полностью случайный интервал | Для высоконагруженных систем |
| **Fibonacci backoff** | 1, 1, 2, 3, 5, 8... | Редко используется |

## Практические сценарии

### Сценарий 1: Token Bucket rate limiting в Nginx

Ограничение API: 10r/s с burst=20:

```nginx
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    server {
        listen 80;
        server_name api.example.com;

        location /api/ {
            limit_req zone=api burst=20 nodelay;
            limit_req_status 429;
            limit_req_log_level warn;

            proxy_pass http://api_backend;
        }
    }
}
```

**Валидация:**
- `ab -n 100 -c 25 http://api.example.com/api/` — первые 20 запросов проходят, остальные получают `429`.
- В логах: `limit_req_status=429`, `limit_req_log_level=warn`.

### Сценарий 2: Exponential backoff + jitter в приложении

Python-пример retry-логики:

```python
import random
import time

def retry_with_backoff(func, max_retries=3, base_delay=1.0):
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
            time.sleep(delay)
```

**Валидация:**
- Задержки: ~1s, ~2–3s, ~4–5s (с jitter).
- При восстановлении сервиса retry прерывается досрочно.

### Сценарий 3: Circuit Breaker на Python (Resilience4j-аналог)

```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_failure_time = None

    def call(self, func, *args, **kwargs):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF-OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            self.on_success()
            return result
        except Exception as e:
            self.on_failure()
            raise

    def on_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
```

**Валидация:**
- 5 последовательных ошибок → `state = OPEN`, все последующие вызовы сразу падают.
- Через 30 секунд → `HALF-OPEN`, пробный вызов проходит → `CLOSED`.

### Сценарий 4: Bulkhead pattern (ограничение пулов)

Изоляция критичных и некритичных эндпоинтов:

```python
import concurrent.futures

# Отдельный пул для критичных запросов
critical_pool = concurrent.futures.ThreadPoolExecutor(max_workers=10)
# Отдельный пул для фоновых задач
background_pool = concurrent.futures.ThreadPoolExecutor(max_workers=30)

def handle_request(endpoint):
    if endpoint == "/critical":
        return critical_pool.submit(fetch_critical)
    else:
        return background_pool.submit(fetch_background)
```

**Валидация:**
- При переполнении `/critical` (10 потоков) фоновые задачи продолжают выполняться.
- В логах: `critical_pool` saturated, но `background_pool` свободен.

### Сценарий 5: HAProxy rate limiting (stick-rate-sessions)

Ограничение новых сессий на бэкенд:

```haproxy
backend api_servers
    balance roundrobin
    stick-rate-sessions 1
    server app1 10.0.1.10:8080 maxconn 100 check
    server app2 10.0.1.11:8080 maxconn 100 check
    http-request deny if { req_rate(api) gt 100 }
```

**Валидация:**
- `ab -n 1000 -c 200 http://haproxy/api/` — запросы, превышающие `req_rate`, получают `403` или `429`.

### Сценарий 6: Retry-After enforcement

Сервер возвращает `Retry-After`, клиент соблюдает:

```nginx
# Nginx: возвращаем Retry-After при 503
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://api_backend;
        proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
        proxy_next_upstream_tries 3;
        proxy_next_upstream_timeout 10s;

        error_page 503 = @retry_later;
    }

    location @retry_later {
        add_header Retry-After 5;
        return 503;
    }
}
```

**Валидация:**
- `curl -I http://api.example.com/` при недоступном бэкенде — заголовок `Retry-After: 5` присутствует.
- Клиент (curl, python-requests) не повторяет автоматически, но уважает заголовок при ручном retry.

### Сценарий 7: Slow start (gradual ramp-up)

При добавлении нового бэкенда Nginx постепенно увеличивает вес:

```nginx
upstream api_backend {
    server 10.0.1.20:8080 weight=1 max_fails=3 fail_timeout=30s;
    server 10.0.1.21:8080 weight=10;
    keepalive 32;
}
```

Для плавного старта в HAProxy используйте `slowstart`:

```haproxy
backend api_servers
    server app_new 10.0.1.20:8080 check slowstart 60s
```

**Валидация:**
- После добавления бэкенда его вес растёт линейно в течение 60 секунд.
- В логах: постепенный рост запросов на новый бэкенд, без всплеска ошибок.

## Типичные проблемы и диагностика

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Thundering herd** | Синхронные retry всех клиентов | `tcpdump` — волна запросов через фиксированные интервалы | Добавить jitter к exponential backoff |
| **Retry amplification** | 1 запрос = 10 запросов к бэкенду | Логи бэкенда: RPS в 3–5 раз выше, чем у прокси | Установить `proxy_next_upstream_tries 3` |
| **Burst exhaustion** | Burst-очередь переполнена, все запросы получают 429 | `limit_req` логи: `429` для всех | Увеличить `burst` или `rate`; добавить очередь |
| **Circuit breaker stuck open** | Сервис не восстанавливается после восстановления | Логи: `Circuit breaker is OPEN` при работающем бэкенде | Уменьшить `recovery_timeout` или добавить half-open пробные запросы |
| **Bulkhead exhaustion** | Критичные запросы блокируются фоновыми | `ThreadPoolExecutor` queue full | Увеличить пул критичных задач или добавить очередь |
| **Sliding window edge case** | Burst в начале/конце окна | `rate(...[1m])` — пики на границе | Использовать sliding window log или counter |
| **Client ignores Retry-After** | Клиент повторяет сразу, игнорируя `Retry-After` | Логи: повторные 503 через <1 секунду | На стороне клиента уважать `Retry-After` |
| **Rate limit on CDN** | Лимит срабатывает на CDN, а не на Origin | CDN логи: `429`, Origin логи: нет | Настроить rate limit на CDN или передавать `X-Forwarded-For` |
| **IP-based limit and NAT** | Все клиенты за NAT получают 429 | Логи: один IP, множество клиентов | Использовать cookie-based rate limit или API-key |
| **Retry на POST** | Повторный POST создаёт дубликаты | Логи: дубликаты заказов/платежей | Idempotency-Key или сделать операцию идемпотентной |

## Лучшие практики

1. **Rate limiting на edge:** Настройте `limit_req` на Nginx/HAProxy, а не только на приложении. Edge-прокси защищает от DDoS до приложения.
2. **`burst` с `nodelay` для API:** `burst=20 nodelay` обрабатывает всплески мгновенно, не накапливая очередь.
3. **`limit_req_status 429` и `Retry-After`:** Всегда возвращайте `429` с `Retry-After`, чтобы клиенты могли адаптировать нагрузку.
4. **Retry только идемпотентных методов:** `GET`, `HEAD`, `PUT`, `DELETE`. Для `POST` требуйте `Idempotency-Key`.
5. **Exponential backoff + jitter:** `delay = base * 2^attempt + random(0, 1)`. Jitter предотвращает thundering herd.
6. **Circuit breaker с half-open:** После `recovery_timeout` разрешайте 1–2 пробных запроса. Если успех — `CLOSED`.
7. **Bulkhead для критичных эндпоинтов:** Отдельные пулы соединений/потоков для `/payments` и `/search`. Падение `/search` не влияет на `/payments`.
8. **`proxy_next_upstream_tries`:** Ограничьте количество попыток (обычно 2–3). Без ограничения один клиентский запрос может генерировать десятки upstream-запросов.
9. **Мониторинг circuit breaker state:** Экспортируйте состояние (`CLOSED`/`OPEN`/`HALF-OPEN`) в метрики. Alert при `OPEN` > 5 минут.
10. **Idempotency-Key TTL:** Храните ключи 24–48 часов (больше, чем максимальный retry interval).
11. **API-key rate limiting:** Для публичных API используйте `limit_req_zone $http_apikey` вместо IP. IP меняется у мобильных клиентов.
12. **Адаптивный rate limiting:** На основе текущей утилизации сервиса (если CPU > 80%, снижайте rate limit).

## Граничные случаи и ограничения

1. **Token Bucket и большие bursts:** При `burst=1000` и `rate=10r/s` зона памяти может исчерпаться. Ограничьте `burst` разумным значением (50–100).
2. **Sliding Window и точность:** Аппроксимация sliding window может разрешать на 1–2 запроса больше, чем лимит. Для строгого ограничения используйте Sliding Window Log.
3. **Circuit breaker и cold start:** После `recovery_timeout` бэкенд может ещё не готов (прогрев кэша, пул соединений). Увеличьте `recovery_timeout` или добавьте warm-up.
4. **Retry и идемпотентность:** `PUT /users/123` идемпотентен, но если сервер обработал запрос, а ответ потерялся в сети, клиент повторит — идемпотентность сохранится. Для `POST /orders` требуется `Idempotency-Key`.
5. **Bulkhead и thread starvation:** Слишком мелкие пулы (`max_workers=1`) приведут к starvation. Настройте пулы под ожидаемую пиковую нагрузку.
6. **Rate limit по IP и CDN:** За CDN все клиенты имеют IP edge-сервера. `limit_req_zone $binary_remote_addr` ограничит весь трафик от CDN. Используйте `$http_x_forwarded_for` за доверенным прокси.
7. **Nginx `limit_req` и 0-RTT:** 0-RTT запросы не проходят полный handshake. Rate limit может не сработать на первые 0-RTT запросы. Дополнительно ограничивайте на приложении.
8. **HAProxy `stick-rate-sessions` и keepalive:** `stick-rate-sessions` ограничивает новые соединения, но keepalive-соединения продолжают отправлять запросы. Учитывайте это при расчёте лимитов.
9. **Retry amplification и cost:** При 3 retries и 5 бэкендах один клиентский запрос может сгенерировать до 15 запросов. Учитывайте это в capacity planning.
10. **Circuit breaker и частичные сбои:** Если 90% запросов падают, а 10% успевают, circuit breaker может не открыться (порог по процентам). Используйте абсолютный порог или moving average.

## Дополнительная информация

### Bounded Queue с приоритизацией

```python
import queue

# Критичные запросы имеют приоритет
critical_queue = queue.PriorityQueue()
normal_queue = queue.Queue()

def enqueue(request, priority="normal"):
    if priority == "critical":
        critical_queue.put((0, request))  # 0 = высший приоритет
    else:
        normal_queue.put(request)
```

### Token Bucket: математика

```python
class TokenBucket:
    def __init__(self, rate, capacity):
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max tokens
        self.tokens = capacity
        self.last_time = time.time()

    def consume(self, tokens=1):
        now = time.time()
        elapsed = now - self.last_time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_time = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
```

### Сравнение rate limiting на разных уровнях

| Уровень | Инструмент | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Edge (CDN)** | Cloudflare, Fastly | Глобальное распределение; блокировка до Origin | Зависимость от провайдера; стоимость |
| **Load Balancer** | Nginx, HAProxy | Низкая latency; централизованное управление | Ограничена производительностью LB |
| **API Gateway** | Kong, Envoy, APISIX | Гибкие правила, authentication, analytics | Дополнительный hop; сложность |
| **Application** | App-level middleware | Точный контроль (per-user, per-endpoint) | Нагрузка на приложение; сложнее масштабировать |

## Смотрите также

- **[HTTP-серверы и прокси](./http_servers_proxies.md)** — `limit_req`, `limit_except`, `limit_conn`.
- **[Балансировка нагрузки](./http_load_balancing.md)** — `maxconn`, `stick-rate-sessions`.
- **[Логирование и инструменты диагностики](./http_logging_troubleshooting_tools.md)** — анализ rate limit логов.
- **[Коды ответа HTTP](./http_status_codes.md)** — `429 Too Many Requests`, `Retry-After`.
- **[REST API](./http_rest_api.md)** — `Idempotency-Key` для POST.
