# Middleware для управления трафиком: лимиты, circuit breaker, ретраи, сжатие

## Определения

**RateLimit** — token bucket на источник (IP/header/запрос), защищает от перегрузки и флуда. Дает `429 Too Many Requests`.

**InFlightReq** — ограничение числа параллельно обрабатываемых запросов; при переполнении отвечает `429`.

**CircuitBreaker** — автоматическое отключение сервиса при проблемах (машина состояний), повторное подключение после recovery.

**Retry** — повторная отправка запроса на другой сервер/сервис при ошибках (mark `Retry-Attempts`).

**Buffering** — буферизация тела запроса/ответа на диске до отправки в бэкенд (влияет на streaming!); default — прямой стрим.

**Errors** — ответ на нефиксированные коды ошибок HTTP (например, `502`) собственным fallback-файлом.

**Compress** — сжатие `gzip`/`br`/`zstd` (существует только по `Content-Type`), настройка `minSize`, исключения типов.

## Базовые концепции

### RateLimit: параметры и «источник»

Token bucket под капотом: за `period` пул пополняется на `average` токенов; короткие пачки до `burst` допускаются без потерь.

```yaml
http:
  middlewares:
    api-limit:
      rateLimit:
        average: 100
        period: 1s
        burst: 200
        sourceCriterion:
          ipStrategy:
            depth: 1
        # есть ещё addXForwardedHeaders: true | false (по умолчанию true)
```

Полезные возможности v3:

- `sourceCriterion.requestHost: true` — лимит на хост (без потери по IP);
- `sourceCriterion.requestHeaderName: "X-Api-Key"` — лимит на API-ключ (важно: заголовок без дефисов/подчеркиваний не рвется);
- `addXForwardedHeaders: true` (default) — добавляет `X-RateLimit-Limit`, `X-RateLimit-Remaining` (в поле ограничения не ломает поведение).

### Распределённый RateLimit (Redis)

RateLimit **в OSS поддерживает Redis** в качестве общего storage (тот же token bucket, но счётчики на общем сервере). Конфиг:

```yaml
http:
  middlewares:
    global-limit:
      rateLimit:
        average: 100
        period: 1s
        sourceCriterion:
          ipStrategy:
            depth: 1
        redis:
          endpoints:
            - "redis-primary:6379"
          db: 0
          password: "secret"
          poolSize: 20
          minIdleConns: 0
          maxActiveConns: 60
          dialTimeout: 5s
          readTimeout: 3s
          writeTimeout: 3s
          tls:
            ca: /etc/redis/ca.crt
```

Значения по умолчанию: `endpoints: localhost:6379`, таймауты 3s (dial 5s). Требуется `redis://`-совместимый сервер (RESP); выключение Redis означает «Open» (без лимита). Ограничение: единое состояние на всех инстансах Traefik (если трафик идет через несколько replicas Traefik — без Redis лимит считается только локально!).

#### Edge cases Redis RateLimit

- **Redis unavailable**: Traefik ведет себя как «Open» — лимит не применяется вообще. Для production настраивайте Sentinel/Cluster или fallback на локальный лимит.
- **Tuning burst/average**: для API с пиковыми нагрузками ставьте `burst` в 2-3 раза выше `average`; для строгого throttle — `burst: average` (равны).
- **Key design**: ключи в Redis имеют TTL равный `period`. При высокой частоте сбросов проверьте, что `period` не слишком мал.
- **Memory pressure**: при большом количестве уникальных IP Redis может потреблять много памяти. Настройте `maxmemory` и `maxmemory-policy` (например, `allkeys-lru`).

### InFlightReq

```yaml
http:
  middlewares:
    inflight:
      inFlightReq:
        amount: 50
        sourceCriterion:
          ipStrategy:
            depth: 1
```

`amount: 0` **отключает** лимит. Полное соответствие «источника» — как в RateLimit (см. выше).

### Circuit Breaker: выражения

Условие — выражение с функциями метрик:

- `NetworkErrorRatio()` — доля ошибок соединений за период (по умолчанию 10s);
- `LatencyAtQuantileMS(50.0)` — p50 латентности в мс (> значения = break);
- `ResponseCodeRatio(from, to, factorCodeFrom, factorCodeTo)` — доля кодов в диапазоне до долей 5xx.

Пример: `CircuitBreaker` «ломается», если 50% из последних 100 запросов дали 5xx ИЛИ средняя латентность > 150 ms; оперирует в временном окне:

```yaml
http:
  middlewares:
    cb-api:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.50 || LatencyAtQuantileMS(50.0) > 150"
        checkPeriod: 100ms       # интервал оценки выражения
        fallbackDuration: 10s    # сколько ждать перед попыткой восстановления
        recoveryDuration: 10s    # сколько выполнять плавное восстановление
        responseCode: 503        # код при разомкнутой цепи
```

Состояния: **Closed → Open → Recovering → Closed**. В Open сервис возвращает `503 Service Unavailable` (по умолчанию, настраивается `responseCode`), запросы к бэкенду не идут. В Recovering трафик в сервис растёт линейно; очередная ошибка снова размыкает цепь. Circuit breaker анализирует только то, что проходит **после** него в цепочке middleware; у каждого роутера свой инстанс. При стриминговых соединениях (WebSocket/gRPC) статистика не собирается.

### Retry

```yaml
http:
  middlewares:
    retry-mw:
      retry:
        attempts: 3
        initialInterval: 1s
        maxInterval: 8s
        # includedStatusCodes: [500, 502, 503]   # по умолчанию 5xx + 3xx(редиректы)
        # nonRetriableStatusCodes(...) -- переопределяет
```

Сброс счетчиков при новых запросах. Работает и для gRPC (ошибки пересчитываются как неуспешные). Важно: ретраи без буферизации тела — только для GET/HEAD (иначе повторить нечего).

### Errors (fallback-файл)

```yaml
http:
  middlewares:
    error-pages:
      errors:
        status:
          - "500-599"
        query: "/{status}.html"
        service: error-svc
        # service: по умолчанию $useStaticErrorService (внутренняя страница по умолчанию)
```

Обращается к `service` (обычно статическая страница) при обработке ошибок диапазона; при недоступности «self» как сервиса — требует честного сервиса ошибок.

### Compress

```yaml
http:
  middlewares:
    gzip-mw:
      compress:
        encodings:
          - gzip
          - br
          - zstd
        minSize: 1500           # байт; включение только для тел >= этого размера
        excludedContentTypes:
          - text/event-stream
        # inline: true (межузловое сжатие для больших стримов), defaultExcludedContentTypes: [...]
```

Поведение: сжатие применяется также к `API`-ответам, но игнорирует и без того сжатые бэкенды (проверка `Content-Encoding`); `Accept-Encoding: gzip;q=0` — не сжимает. **Не применяйте compress к WebSocket, SSE, большим стримам** — потоки рвутся.

### Buffering

```yaml
http:
  middlewares:
    buffer-mw:
      buffering:
        maxRequestBodyBytes: 10m
        maxResponseBodyBytes: 20m
        memRequestBodyBytes: 2m   # до лимита в памяти
        memResponseBodyBytes: 4m
```

По умолчанию Buffering **не активирован** (потоковый режим). Включение ломает WebSocket (upgrade) и SSE — применяйте только к небольшим API с ограничением полезного тела.

### Лимиты размера тела запроса (entrypoint + middleware)

Traefik ограничивает тело запроса на двух уровнях:

1. **Entrypoint (`maxRequestBodyBytes`)** — глобальный лимит на все запросы через entrypoint. При превышении Traefik отвечает `413 Payload Too Large` **до** передачи бэкенду.

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 30s
    http:
      maxRequestBodyBytes: 10m   # 10 MiB; по умолчанию нет лимита
```

2. **Middleware Buffering (`maxRequestBodyBytes`)** — per-router лимит с возможностью кастомного ответа (через `Errors` middleware).

```yaml
http:
  middlewares:
    upload-limit:
      buffering:
        maxRequestBodyBytes: 50m    # 50 MiB
        memRequestBodyBytes: 5m      # буфер в памяти, остальное — tmpfs/диск
```

Паттерны:

- **Файловый upload (HTML form, multipart):** `maxRequestBodyBytes` на entrypoint + Buffering middleware на роутер. multipart boundary не учитывается в лимит тела.
- **JSON API с большими payload:** Buffering middleware с `Errors` fallback для `413`.
- **Streaming upload (PUT/POST без финального размера):** Buffering **не подходит** — он ждет завершения тела. Для chunked-стримов используйте entrypoint-лимит + бэкенд-валидацию.
- **Docker registry / artifact stores:** entrypoint `maxRequestBodyBytes: 100m` + `buffering.maxRequestBodyBytes: 100m`.

Отладка:

```bash
# Проверить текущий лимит entrypoint
curl -s http://localhost:8080/api/entrypoints | jq '.["websecure"].http.maxRequestBodyBytes'
# → null (нет лимита) или число

# Тест превышения
curl -X POST -H "Content-Type: application/json" --data-binary @large_file.bin https://app.example.com/upload
# → 413 Payload Too Large
```

## Практические сценарии

### Сценарий 1: Полная защита API

```yaml
http:
  middlewares:
    api-throttle:
      chain:
        middlewares:
          - rate-limit-by-key
          - circuit-breaker-api
    rate-limit-by-key:
      rateLimit:
        average: 50
        period: 1s
        burst: 200
        sourceCriterion:
          requestHeaderName: "X-Api-Key"
    circuit-breaker-api:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.40"

  services:
    api-service:
      loadBalancer:
        servers:
          - url: "http://api-backend:8080"
```

### Сценарий 2: Распределенный лимит на кластер

При нескольких репликах Traefik:

```yaml
# Traefik (config file)
http:
  middlewares:
    global-rl:
      rateLimit:
        average: 50
        period: 1s
        sourceCriterion:
          ipStrategy:
            depth: 1
        redis:
          endpoints:
            - "redis-master:6379"
          db: 1
          poolSize: 20
```

Проверка:

```bash
redis-cli -p 6379 KEYS 'traefik:rate:*'
# → traefik:rate:<key>:<window>   (наличие ключей = лимит работает)
```

### Сценарий 3: Сервер ошибок

```yaml
http:
  middlewares:
    custom-errors:
      errors:
        status: ["500-504"]
        service: static-pages
        query: "/error/{status}.html"
  services:
    static-pages:
      loadBalancer:
        servers:
          - url: "http://static-pages:80"
```

## Операции и команды

```bash
# Просмотр метрик rate limit / inFlight / circuit breaker
curl -s localhost:9090/api/v1/query?query=traefik_service_requests_total | jq '.'   # тарелочки на Prometheus

# Проверка после срабатывания breaker (503)
curl -s -o /dev/null -w '%{http_code}\n' https://api.example.com/

# Проверка headers на RateLimit
curl -sv https://api.example.com/ 2>&1 | grep -i '^< x-rate-limit'
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`429` на всех клиентов** | RateLimit по RemoteAddr за LB; отсутствие `depth` / нет `trustedIPs` | Настройте `sourceCriterion.ipStrategy.depth` + `forwardedHeaders` |
| **Сервис открывается/закрывается хаотично** | `movingAverageWindow`/`checkPeriod` несоразмерны | Увеличьте окно, следите за latency-метриками |
| **Retry не помогает** | Тело небуферизуемое / неретрай-код в `includedStatusCodes` | Буферизуйте/ограничьте статусы; помните, что повтор для POST возможен |
| **WebSocket рвется** | `buffering`/`compress` в цепочке | Уберите стриминговые middleware для этих путей |
| **Глобальный лимит обходит локальным** | Каждый инстанс считает в своей памяти | Включите Redis в `rateLimit` |

## Рекомендации

- RateLimit ставить до дорогих проверок (BasicAuth — после). Цепочка: IP → Rate → Auth.
- Для распределенного Traefik (несколько реплик) обязателен Redis в RateLimit — иначе лимит «по кластеру» не держится.
- CircuitBreaker: включайте с порогами под ваши метрики (важно: не 50%/1s для сервисов с низкой частотой трафика).
- Compress: только прозрачные и маленькие ответы; для больших/стриминговых — off.
- Синтаксис YAML: bytes с литералами (`10m`, `20 << 20`), интервалы длительности YAML-duration (`1s`).

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — middleware в архитектуре.
- [Middleware для безопасности](./traefik-middlewares-security.md) — аутентификация и IP-фильтры (комбинация с RateLimit).
- [Доверенные заголовки и реальный IP](./traefik-forwarded-headers.md) — правильный IP-источник для лимитов.
- [Kubernetes Traefik BasicAuth](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) — истории RateLimit/IPAllowList в K8s среде.