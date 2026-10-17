# Rate Limiting в Traefik: архитектура, Token Bucket, Redis, DDoS-защита и SRE-эксплуатация

**Актуально для:** Traefik v3.x (проверено на v3.7.x)

---

## 1. Определения

**Rate Limiting** — механизм ограничения интенсивности входящих HTTP-запросов за заданный интервал времени для предотвращения каскадной перегрузки бэкендов, защиты от атак типа «отказ в обслуживании» (DoS), сдерживания брутфорса и изоляции арендаторов (tenants).

**Token Bucket (Алгоритм корзины с токенами)** — математический алгоритм ограничения скорости, при котором виртуальная корзина емкостью `burst` пополняется токенами со скоростью `average` за интервал `period`. Запрос пропускается только при наличии доступного токена.

**Burst (Всплеск)** — максимальная емкость корзины токенов, определяющая число запросов, которое клиент может отправить одновременно (взрывной всплеск) без немедленного отклонения.

**Period** — временное окно пополнения корзины (по умолчанию `1s`). Скорость генерации токенов рассчитывается как `average / period`.

**MaxDelay и Traffic Shaping (Формирование трафика)** — встроенный в Traefik механизм сглаживания трафика: если входящий запрос незначительно опережает генерацию токенов, Traefik не сбрасывает его сразу, а приостанавливает выполнение горутины (`time.Sleep`) на рассчитанную задержку `delay`. Если `delay > maxDelay`, запрос отклоняется с кодом `429`.

**Source Criterion (Критерий источника)** — правило группировки запросов по общему пулу токенов: по клиентскому IP (`ipStrategy`), хосту (`requestHost`) или значению произвольного HTTP-заголовка (`requestHeaderName`).

**IP Strategy** — алгоритм извлечения и нормализации IP-адреса клиента из заголовка `X-Forwarded-For` или сетевого сокета с поддержкой глубины (`depth`), фильтрации доверенных прокси (`excludedIPs`) и маскирования подсетей IPv6 (`ipv6Subnet`).

**Distributed Rate Limit** — распределенное состояние корзины токенов, разделяемое между несколькими репликами Traefik через внешний кластер Redis с исполнением атомарных скриптов Lua.

**Fail-Open** — архитектурное поведение Traefik при недоступности Redis: в случае сбоя хранилища middleware пропускает трафик без ограничения скорости, отдавая приоритет доступности сервиса (High Availability) над жестким соблюдением лимитов.

**Retry-After / X-Retry-In** — стандартный HTTP-заголовок (RFC 6585) и служебный заголовок Traefik, возвращаемые при ошибке `429 Too Many Requests` и сообщающие клиенту расчетное время ожидания в секундах до доступности следующего токена.

---

## 2. Архитектура и принципы работы

### Внутренний механизм Token Bucket и сглаживание трафика

В ядре Traefik Rate Limiting реализован на базе библиотеки `golang.org/x/time/rate`. В отличие от тривиальных шлюзов, которые мгновенно сбрасывают любой трафик сверх лимита, Traefik работает как шейпер трафика (traffic shaper) с двумя фазами обработки:

```
[Входящий HTTP-запрос]
         │
         ▼
[Извлечение Source Key] ── (IP / Header / Host)
         │
         ▼
[Проверка пула токенов (Reserve)]
         │
         ├── Токены есть ───────────────────────────> [Проксирование в бэкенд]
         │
         └── Токенов нет (вычислен delay ожидания)
                   │
                   ├── delay <= maxDelay ───────────> [time.Sleep(delay)] ──> [Проксирование]
                   │   (сглаживание всплеска)
                   │
                   └── delay > maxDelay (или переполнение burst)
                               │
                               ▼
                   [HTTP 429 Too Many Requests]
                   (Заголовки: Retry-After, X-Retry-In)
```

1. **Расчет скорости ($R$):**
   $$R = \frac{\text{average} \times 1\,\text{sec}}{\text{period}}$$
   Если `average = 0`, лимитер переходит в режим `rate.Inf` (ограничение отключено).
2. **Предельная задержка (`maxDelay`):**
   - Для ставок $R \ge 1$ req/s: $\text{maxDelay} = \frac{1\,\text{sec}}{2 \times R}$.
   - Для ставок $R < 1$ req/s: $\text{maxDelay} = 500\,\text{ms}$.
3. **Обработка запроса:**
   - Вызывается метод резервации `bucket.Reserve()`.
   - Если резервация успешна и `delay <= maxDelay`, поток блокируется вызовом `time.Sleep(delay)`, после чего запрос передается следующему middleware/сервису.
   - Если `delay > maxDelay`, резервация отменяется, а клиенту возвращается статус `429 Too Many Requests` с заголовками `Retry-After: <ceil(seconds)>` и `X-Retry-In: <duration>`.
   - Если размер пакета превышает допустимый всплеск, возвращается ошибка с телом `No bursty traffic allowed`.

> [!NOTE]
> Traefik **не добавляет** заголовки `X-RateLimit-Limit` и `X-RateLimit-Remaining` в стандартной поставке. Возвращаются исключительно `Retry-After` (целое число секунд) и `X-Retry-In` (человекочитаемая строка длительности, например `450ms`).

### Локальное хранение в памяти: структура и лимит `maxSources`

При локальной работе (без указания блока `redis`) каждый инстанс Traefik изолированно хранит корзины источников в потокобезопасной хеш-таблице `github.com/mailgun/ttlmap`:

```
┌───────────────────────────────────────────────────────────┐
│               Traefik In-Memory TTLMap                   │
│                                                           │
│  Key: "192.0.2.1"     ──> [Token Bucket: rate/burst]     │
│  Key: "198.51.100.25" ──> [Token Bucket: rate/burst]     │
│  Key: "203.0.113.8"   ──> [Token Bucket: rate/burst]     │
│                                                           │
│  Максимум записей: maxSources = 65 536                    │
│  TTL записи: 1s .. (1s + 1/R)                            │
└───────────────────────────────────────────────────────────┘
```

- **Параметр TTL:** Корзина удаляется из памяти сборщиком мусора, если к ней не было обращений в течение времени TTL:
  $$\text{TTL} = \begin{cases} 2\,\text{sec}, & \text{при } R \ge 1 \\ 1 + \left\lfloor\frac{1}{R}\right\rfloor\,\text{sec}, & \text{при } 0 < R < 1 \end{cases}$$
- **Лимит `maxSources = 65536`:** Таблица жестко ограничена 65 536 уникальными источниками одновременно. При распределенной атаке или сканировании с более чем 65 536 уникальных IP-адресов в пределах окна TTL аллокация новой корзины завершается ошибкой. В этом случае Traefik логирует ошибку `Could not insert/update bucket` и возвращает клиенту **HTTP 500 Internal Server Error**. Для высоконагруженных публичных инсталляций это делает обязательным использование Redis или внешнего L4/L7-фильтра.

### Распределенный Rate Limiting через Redis

Когда приложение масштабируется на несколько реплик Traefik за балансировщиком нагрузки, локальный подсчет делит установленный лимит на число реплик: при 3 подах Traefik и настройке `average: 100` суммарная пропускная способность составит 300 req/s.

Для синхронизации Traefik v3 поддерживает встроенную интеграцию с Redis:

```
    [ Клиентские запросы ]
               │
    ┌──────────┴──────────┐
    ▼                     ▼
[Traefik Pod 1]       [Traefik Pod 2]
    │                     │
    └──────────┬──────────┘
               │  Lua EVALSHA (атомарно)
               ▼
      [ Кластер / Sentinel Redis ]
      Ключи: "rate:<source>"
      Значение: [tokens, last_update_micro]
```

- **Атомарность:** Проверка и декремент токенов выполняются на стороне Redis через предзагруженный Lua-скрипт (`EVALSHA`), что гарантирует отсутствие race conditions при параллельных запросах к разным репликам.
- **Формат ключей:** Префикс ключа в Redis жестко зашит в код: `rate:<source>` (например, `rate:203.0.113.195` или `rate:tenant-pro-alpha`).
- **Схема Fail-Open:** Если соединение с Redis обрывается или происходят таймауты (`dialTimeout`, `readTimeout`), Traefik логирует сбой драйвера и пропускает трафик без блокировки, предотвращая отказ сервиса из-за недоступности хранилища кэша.

### Определение источника: стратегии `sourceCriterion`

Параметр `sourceCriterion` определяет, какая сущность считается субъектом ограничения:

| Критерий | Конфигурация | Назначение | Особенности |
| :--- | :--- | :--- | :--- |
| **Сетевой IP (Default)** | `ipStrategy: {}` (без параметров) | Защита внутренних сервисов без прокси | Берет `RemoteAddr` сокета. За внешним LB все клиенты объединятся в один пул! |
| **Глубина прокси** | `ipStrategy.depth: N` | Инсталляция за цепочкой прокси / балансировщиков | Выбирает $N$-й IP с правого конца `X-Forwarded-For`. |
| **Исключение прокси** | `ipStrategy.excludedIPs: [...]` | Балансировщики с плавающим числом хопов | Сканирует `X-Forwarded-For` справа налево, выбирая первый адрес вне списка доверенных. Игнорируется, если задан `depth`. |
| **Подсеть IPv6** | `ipStrategy.ipv6Subnet: 64` | Защита от ботнетов с ротацией IPv6 | Округляет адрес IPv6 до сетевого адреса подсети (например, `/64`). |
| **HTTP-заголовок** | `requestHeaderName: "X-Api-Key"` | Multi-tenant API, аутентифицированные клиенты | Все запросы с одинаковым значением заголовка попадают в один пул. Запросы без заголовка считаются одним общим пустым источником. |
| **Хост** | `requestHost: true` | Защита конкретного vhost от флуда в целом | Ограничивает суммарную частоту запросов на домен независимо от клиентов. |

> [!WARNING]
> В одном middleware разрешено задавать **только одну** стратегию: либо `ipStrategy`, либо `requestHeaderName`, либо `requestHost`. Одновременная комбинация нескольких стратегий вызовет ошибку валидации конфигурации при запуске маршрутизатора.

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Производственный Rate Limit по реальному IP за балансировщиком (File Provider / YAML)

Сценарий с защитой от спуфинга IP, корректной обработкой `X-Forwarded-For` через `depth` и группировкой IPv6 в подсети `/64`.

```yaml
# /etc/traefik/dynamic/rate-limit.yml
http:
  middlewares:
    client-ip-limiter:
      rateLimit:
        average: 50           # 50 запросов в секунду
        period: 1s
        burst: 100            # Двукратный всплеск для статики и параллельных XHR
        sourceCriterion:
          ipStrategy:
            depth: 1          # 1-й справа IP (добавлен upstream LB: HAProxy/NGINX)
            ipv6Subnet: 64    # Группировка /64 пресекает обход лимита через ротацию IPv6

  routers:
    api-router:
      rule: "Host(`api.example.internal`)"
      entryPoints:
        - websecure
      service: api-service
      middlewares:
        - client-ip-limiter

  services:
    api-service:
      loadBalancer:
        servers:
          - url: "http://10.0.10.15:8080"
```

### Сценарий 2: Распределенный Rate Limiting через Redis с TLS и аутентификацией

Использование высокодоступного кластера Redis для синхронизации лимитов между 5+ подами Traefik.

```yaml
# /etc/traefik/dynamic/rate-limit-redis.yml
http:
  middlewares:
    cluster-distributed-limit:
      rateLimit:
        average: 200
        period: 1s
        burst: 300
        sourceCriterion:
          ipStrategy:
            depth: 1
            ipv6Subnet: 64
        redis:
          endpoints:
            - "redis-node-1.db.internal:6379"
            - "redis-node-2.db.internal:6379"
            - "redis-node-3.db.internal:6379"
          username: "traefik_limiter"
          password: "VaultSecretPasswordString"
          db: 0
          poolSize: 100           # Базовый пул коннектов
          minIdleConns: 20        # Поддержание горячих соединений
          maxActiveConns: 300     # Предел на пиках нагрузки
          dialTimeout: 2s         # Быстрый таймаут подключения
          readTimeout: 500ms      # Минимальная задержка при вызове скрипта
          writeTimeout: 500ms
          tls:
            ca: "/etc/ssl/certs/internal-ca.crt"
            insecureSkipVerify: false
```

### Сценарий 3: Kubernetes IngressRoute CRD с секретами Redis

В Kubernetes CRD пароли и сертификаты подключаются декларативно через стандартные `Secret`.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: traefik-redis-auth
  namespace: traefik-ingress
type: Opaque
stringData:
  username: "traefik-operator"
  password: "ProductionRedisPassword123"
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: k8s-api-ratelimit
  namespace: traefik-ingress
spec:
  rateLimit:
    average: 150
    period: 1s
    burst: 200
    sourceCriterion:
      ipStrategy:
        depth: 2              # 2 прокси перед ingress (например, внешний CDN + NodePort/LB)
        ipv6Subnet: 64
    redis:
      endpoints:
        - "redis-cluster.database.svc.cluster.local:6379"
      secret: traefik-redis-auth
      db: 1
      poolSize: 50
      readTimeout: 1s
      writeTimeout: 1s
      dialTimeout: 2s
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: public-api-route
  namespace: traefik-ingress
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`public.company.org`) && PathPrefix(`/v1/`)
      kind: Rule
      services:
        - name: core-api-backend
          port: 8080
      middlewares:
        - name: k8s-api-ratelimit
```

### Сценарий 4: Docker Compose с label-конфигурацией и защитой админ-панели

Пример жесткого лимитирования попыток входа (`/auth/login`) для защиты от перебора паролей (Brute-Force).

```yaml
# docker-compose.yml
services:
  traefik:
    image: traefik:v3.7
    command:
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
    ports:
      - "80:80"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"

  auth-service:
    image: my-auth-app:v1.2.0
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.auth-app.rule=Host(`auth.local.domain`)"
      - "traefik.http.routers.auth-app.entrypoints=web"
      
      # Привязка middleware цепочки
      - "traefik.http.routers.auth-app.middlewares=brute-force-limiter"

      # Определение параметров RateLimit: максимум 5 попыток в минуту, всплеск до 8
      - "traefik.http.middlewares.brute-force-limiter.ratelimit.average=5"
      - "traefik.http.middlewares.brute-force-limiter.ratelimit.period=1m"
      - "traefik.http.middlewares.brute-force-limiter.ratelimit.burst=8"
      - "traefik.http.middlewares.brute-force-limiter.ratelimit.sourcecriterion.ipstrategy.depth=1"
```

### Сценарий 5: Многоуровневый Multi-Tenant Rate Limiting по HTTP-заголовкам

Разделение квот по тарифам клиентов с помощью заголовка `X-Tenant-Tier` или API-ключа. Для этого на уровне роутеров Traefik объявляются разные правила сопоставления заголовков:

```yaml
# /etc/traefik/dynamic/multi-tenant.yml
http:
  middlewares:
    # Базовый тариф: 10 req/s, жесткий burst
    tier-free-limit:
      rateLimit:
        average: 10
        period: 1s
        burst: 15
        sourceCriterion:
          requestHeaderName: "X-Api-Key"

    # Премиальный тариф: 500 req/s, большой burst
    tier-enterprise-limit:
      rateLimit:
        average: 500
        period: 1s
        burst: 1000
        sourceCriterion:
          requestHeaderName: "X-Api-Key"

  routers:
    # Маршрут для Enterprise клиентов
    api-enterprise:
      rule: "Host(`gateway.company.org`) && Headers(`X-Tenant-Tier`, `Enterprise`)"
      priority: 20
      service: api-service
      middlewares:
        - tier-enterprise-limit

    # Маршрут по умолчанию (Free)
    api-free:
      rule: "Host(`gateway.company.org`)"
      priority: 10
      service: api-service
      middlewares:
        - tier-free-limit
```

### Сценарий 6: Комплексная связка: RateLimit + InFlightReq + Кастомные ошибки 429

Эшелонированная защита бэкенда от исчерпания тредов: `inFlightReq` сдерживает параллелизм долгих вызовов (WebSocket, gRPC, тяжелые POST), `rateLimit` отсекает общую частоту, а middleware `errors` отдает брендированный JSON вместо стандартного текстового ответа Traefik.

```yaml
# /etc/traefik/dynamic/defense-in-depth.yml
http:
  middlewares:
    # Ограничение параллельных незавершенных запросов (Slowloris / Concurrency abuse)
    concurrency-limit:
      inFlightReq:
        amount: 25
        sourceCriterion:
          ipStrategy:
            depth: 1

    # Частотное ограничение
    frequency-limit:
      rateLimit:
        average: 100
        period: 1s
        burst: 150
        sourceCriterion:
          ipStrategy:
            depth: 1

    # Перехват статуса 429 и отдача JSON ответа
    custom-429-handler:
      errors:
        status:
          - "429"
        service: error-fallback-service
        query: "/errors/429.json"

    # Цепочка middleware
    complete-api-protection:
      chain:
        middlewares:
          - custom-429-handler
          - concurrency-limit
          - frequency-limit

  services:
    error-fallback-service:
      loadBalancer:
        servers:
          - url: "http://10.0.10.99:80"
```

---

## 4. Диагностика, эксплуатация и мониторинг

### Проверка поведения и заголовков через `curl`

Проверка статуса ответа, замера времени шейпинга и валидация заголовков `Retry-After` и `X-Retry-In`:

```bash
# 1. Запрос в пределах лимита (нормальный статус 200)
curl -s -i -H "Host: api.example.internal" "http://localhost:80/api/v1/ping"
# → HTTP/1.1 200 OK
# → Content-Length: 15
# → {"status":"ok"}

# 2. Быстрый флуд для выбивания пула burst (ожидается HTTP 429)
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code} time_total=%{time_total}s\n" \
    -H "Host: api.example.internal" "http://localhost:80/api/v1/ping"
done
# → 200 time_total=0.003s
# → 200 time_total=0.004s
# → 200 time_total=0.021s   # Начало фазы сглаживания (time.Sleep)
# → 429 time_total=0.002s   # Превышение maxDelay: немедленный сброс
# → 429 time_total=0.002s

# 3. Детальная инспекция заголовков ответа 429
curl -s -D - -o /dev/null -H "Host: api.example.internal" "http://localhost:80/api/v1/ping"
# → HTTP/1.1 429 Too Many Requests
# → Retry-After: 1
# → X-Retry-In: 642.128ms
# → Content-Type: text/plain; charset=utf-8
# → Date: Sat, 17 Oct 2026 15:30:00 GMT
# → Content-Length: 17
```

### Проверка состояния Redis

Инспекция ключей, проверка TTL и потребления оперативной памяти в Redis:

```bash
# Поиск созданных корзин Traefik (префикс rate:)
redis-cli -h redis-node-1.db.internal -p 6379 -a "VaultSecretPasswordString" --scan --pattern 'rate:*'
# → rate:203.0.113.15
# → rate:198.51.100.82

# Проверка оставшегося времени жизни ключа корзины (в секундах)
redis-cli -h redis-node-1.db.internal -p 6379 -a "VaultSecretPasswordString" TTL 'rate:203.0.113.15'
# → (integer) 2

# Инспекция типа структуры и размера ключа
redis-cli -h redis-node-1.db.internal -p 6379 -a "VaultSecretPasswordString" TYPE 'rate:203.0.113.15'
# → hash

# Проверка использования памяти инстансом Redis
redis-cli -h redis-node-1.db.internal -p 6379 -a "VaultSecretPasswordString" INFO memory | grep -E 'used_memory_human|maxmemory_human'
# → used_memory_human:45.12M
# → maxmemory_human:512.00M
```

### Prometheus-метрики и правила алертов

Traefik экспортирует метрики на эндпоинт `/metrics`. Для Rate Limiting отслеживаются счетчики статус-кода `429` на уровнях entrypoint и service:

```bash
# Проверка наличия метрик с кодом 429
curl -s http://localhost:8080/metrics | grep 'code="429"'
# → traefik_service_requests_total{code="429",method="GET",protocol="http",service="api-service@file"} 1482
# → traefik_entrypoint_requests_total{code="429",entrypoint="websecure",method="GET",protocol="http"} 1482
```

Готовые правила для Prometheus Alertmanager:

```yaml
# /etc/prometheus/rules/traefik-ratelimit-alerts.yml
groups:
  - name: traefik_rate_limiting
    rules:
      # Всплеск блокировок: подозрение на DoS-атаку или заниженный лимит
      - alert: TraefikHighRateLimitDropRate
        expr: |
          sum by (service) (rate(traefik_service_requests_total{code="429"}[2m])) > 25
        for: 1m
        labels:
          severity: warning
          tier: networking
        annotations:
          summary: "Высокая частота отклонений по RateLimit в сервисе {{ $labels.service }}"
          description: "Сервис {{ $labels.service }} отклоняет более {{ $value | printf \"%.1f\" }} запр/сек с кодом HTTP 429. Проверьте access-логи на предмет брутфорса или скорректируйте burst."

      # Внезапный скачок ошибок 500: риск переполнения maxSources (65536) в памяти
      - alert: TraefikRateLimitInternalErrors
        expr: |
          sum by (service) (rate(traefik_service_requests_total{code="500"}[2m])) > 10
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Всплеск HTTP 500 в Traefik (возможен сбой TTLMap maxSources)"
          description: "Регистрируются ошибки 500 на шлюзе. Если в логах Traefik присутствует 'Could not insert/update bucket', необходимо переключить RateLimiting на Redis."
```

### Анализ Access Logs Traefik

В access-логах Traefik (рекомендуется формат JSON) отклоненные запросы маркируются кодом `429`, при этом время `Duration` указывает, было ли применено сглаживание:

```json
{
  "ClientHost": "198.51.100.44",
  "ClientPort": "54210",
  "DownstreamContentSize": 17,
  "DownstreamStatus": 429,
  "Duration": 2150000,
  "OriginDuration": 0,
  "OriginStatus": 0,
  "RequestAddr": "api.example.internal",
  "RequestMethod": "POST",
  "RequestPath": "/api/v1/auth",
  "RequestProtocol": "HTTP/1.1",
  "RouterName": "api-router@file",
  "ServiceAddr": "",
  "ServiceName": "api-service@file",
  "StartLocal": "2026-10-17T15:30:12.105421+03:00",
  "entryPointName": "websecure"
}
```

- `OriginStatus: 0` и `OriginDuration: 0` подтверждают, что запрос был отсечен внутри Traefik и **не дошел до бэкенда**.
- `DownstreamStatus: 429` свидетельствует о срабатывании лимитера.

---

## 5. Устранение неисправностей (Troubleshooting)

| Проблема | Диагностика | Первопричина | Решение |
| :--- | :--- | :--- | :--- |
| **Все клиенты получают 429 одновременно** | Запросы от разных внешних клиентов блокируются после нескольких кликов одного пользователя. | Traefik использует `RemoteAddr`, указывающий на адрес внутреннего балансировщика нагрузки (HAProxy, Cloud LB, NodePort). Все клиенты попадают в одну корзину. | Настройте `sourceCriterion.ipStrategy.depth: 1` (или выше) в зависимости от числа промежуточных прокси, либо укажите `ipStrategy.excludedIPs`. Проверьте корректность директивы `forwardedHeaders.trustedIPs` на entrypoint. |
| **Ошибки HTTP 500 `Could not insert/update bucket`** | В логах Traefik: `Could not insert/update bucket`. Запросы клиентов случайно падают с кодом 500. | Исчерпан лимит `maxSources = 65536` во внутреннем хранилище `ttlmap`. Происходит при распределенном DoS с десятков тысяч уникальных IP-адресов. | Переведите Rate Limiting на **Redis** (`redis.endpoints`). В Redis размер пула ограничивается только оперативной памятью сервера. |
| **Лимит перестает работать при масштабировании реплик** | Суммарное число запросов до блокировки превышает `average` в $N$ раз (где $N$ — число подов Traefik). | Локальный in-memory лимитер. Каждый под считает квоту в собственной оперативной памяти независимо от других реплик. | Подключите распределенное хранилище `redis` в секции middleware `rateLimit`. |
| **Падение производительности и рост задержек (Latency spike) перед 429** | Метрика `traefik_service_request_duration_seconds` растет на клиентах, близких к лимиту. | Встроенный механизм сглаживания (Traffic Shaping) усыпляет горутину вызовом `time.Sleep(delay)` на время до `maxDelay` перед пропуском. | Если задержки нежелательны, увеличьте `burst` до значения `2-3 × average` для поглощения пиков, либо установите `average = burst` для жесткого ступенчатого дропа. |
| **Обход блокировки через смену IP в IPv6** | Злоумышленник генерирует миллионы новых IP из выделенной ему провайдером подсети `/64` и обходит лимит. | По умолчанию Traefik считает каждый полный 128-битный IPv6 адрес уникальным источником. | Добавьте директиву `sourceCriterion.ipStrategy.ipv6Subnet: 64`. Все адреса из диапазона `/64` будут агрегироваться в одну общую корзину токенов. |
| **При недоступности Redis весь трафик идет без лимитов** | Redis остановлен или перегружен, Traefik логирует ошибки соединения, но пропускает весь флуд на бэкенд. | Поведение Traefik по умолчанию — **Fail-Open** (приоритет доступности над блокировкой). | Разворачивайте Redis в отказоустойчивой конфигурации (Redis Sentinel или Redis Cluster) с настроенным `maxmemory-policy: allkeys-lru`. Для критичных сервисов продублируйте защиту на L4 (nftables/firewalld) или WAF (CrowdSec). |
| **Клиентское приложение не видит квоты `X-RateLimit-*`** | Заголовки ответов не содержат информации об оставшихся токенах. | Traefik нативно поддерживает только `Retry-After` и `X-Retry-In`. Заголовки драфта IETF (`X-RateLimit-*`) ядром Traefik не генерируются. | Если API-клиентам строго требуются заголовки квот, используйте специализированный плагин Traefik (Traefik Plugin Catalog) или отдавайте заголовки силами самого бэкенд-сервиса. |
| **Подмена заголовка при `requestHeaderName`** | Неавторизованные запросы с пустым заголовком блокируют друг друга. | Все клиенты без указанного заголовка получают ключ `""` (пустая строка) и делят один лимит на всех. | Используйте middleware `chain`: предварительно валидируйте наличие заголовка через middleware `headers` или аутентифицируйте запрос до передачи в `rateLimit`. |

---

## 6. Рекомендации и Best Practices для DevOps/SRE

### 1. Математический расчет `average` и `burst`

- **Стандартный API:** Устанавливайте `burst = 2..3 × average`. Это позволяет браузерам выполнять параллельную загрузку бандлов, шрифтов и начальных запросов интерфейса без ложных срабатываний 429.
- **Строгий троттлинг (Strictest Throttle):** Для чувствительных транзакционных эндпоинтов (платежи, отправка SMS/Email, тяжелые аналитические отчеты) устанавливайте `burst = average`. В этом случае емкость корзины равна секундной ставке, сглаживание минимально, а избыточные запросы сбрасываются мгновенно.
- **Субсекундные ставки:** Если требуется разрешить менее одного запроса в секунду (например, 1 запрос в 5 секунд для формы обратной связи), используйте параметр `period: 5s` при `average: 1`.

### 2. Защита от IPv6-ротации

Современные ботнеты и скрейперы арендуют префиксы IPv6 (`/64` или `/48`) и генерируют случайные 128-битные адреса для каждого HTTP-запроса. Всегда указывайте:

```yaml
sourceCriterion:
  ipStrategy:
    depth: 1
    ipv6Subnet: 64    # Обязательно для публичного сетевого периметра
```

### 3. Сайзинг и оптимизация Redis для Rate Limiting

- **Политика вытеснения (Eviction):** В `redis.conf` обязательно установите:
  ```text
  maxmemory 1gb
  maxmemory-policy allkeys-lru
  ```
  Это предотвратит сбой Redis `OOM command not allowed` при сканировании миллионами случайных IP.
- **Таймауты коннектов:** В конфигурации Traefik устанавливайте агрессивные таймауты (`readTimeout: 200ms`, `dialTimeout: 1s`). Задержка кэша Redis не должна деградировать latency основного прикладного трафика.

### 4. Эшелонированная оборона (Defense-in-Depth)

Rate Limiting в Traefik — это прикладной инструмент защиты L7 (контроль добросовестного использования API). Он **не заменяет**:
1. **L3/L4 Anti-DDoS:** Защиту от SYN-flood, UDP amplification и объемного сетевого флуда необходимо обеспечивать на уровне сетевого экрана провайдера или через BPF/XDP (`iptables`, `nftables`).
2. **WAF и поведенческий анализ:** Защиту от распределенных атак с ротацией IP и эмуляцией браузеров следует делегировать решениям уровня WAF (CrowdSec, ModSecurity).
3. **Slowloris и утечки соединений:** Rate Limiting контролирует частоту запросов, но бессилен против медленно передаваемых байтов. Для защиты от Slowloris обязательно комбинируйте `rateLimit` с middleware `inFlightReq` и глобальными таймаутами entrypoints (`respondingTimeouts.readTimeout`).

---

## 7. Дополнительная информация

- [Middleware управления трафиком Traefik](./traefik-middlewares-traffic.md) — обзорная документация по `RateLimit`, `InFlightReq`, `CircuitBreaker` и `Buffering`.
- [Доверенные прокси и заголовки Forwarded](./traefik-forwarded-headers.md) — детальная настройка `trustedIPs`, `depth` и алгоритмов разбора `X-Forwarded-For`.
- [Безопасность периметра и WAF в Traefik](./traefik-edge-security-waf.md) — интеграция Traefik с CrowdSec и блокировка вредоносных автономных систем (AS).
- [Концепции Rate Limiting в веб-серверах](../Concepts/webserver_rate_limiting.md) — сравнительный анализ алгоритмов Leaky Bucket, Token Bucket и Sliding Window в Nginx, HAProxy и Traefik.
