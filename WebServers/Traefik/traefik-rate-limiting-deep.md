# Rate Limiting в Traefik: паттерны, multi-tenant, DDoS, мониторинг

## Определения

**Rate limiting** — ограничение количества запросов за период времени (token bucket algorithm).

**Source criterion** — параметр, определяющий «источник» запроса для rate limit (IP, header, host).

**Distributed rate limit** — общий лимит между несколькими инстансами Traefik через Redis.

**Rate limit key** — уникальный идентификатор источника (IP, API key, tenant ID).

**Burst** — максимальное количество запросов, которое можно сделать сверх average за короткий период.

**Retry-After** — заголовок ответа 429, указывающий клиенту когда повторить запрос.

**Rate limit bypass** — обход ограничения через подмену заголовков, IP rotation, botnets.

## Базовые концепции

### Token bucket под капотом

За `period` пул пополняется на `average` токенов. Короткие пачки до `burst` допускаются без потерь.

```
period: 1s, average: 100, burst: 200
→ Клиент может сделать 200 запросов мгновенно, затем 100 в секунду
```

### Source criterion: откуда берется IP

По умолчанию Traefik использует `RemoteAddr` (IP соединения). За LB это IP балансировщика, а не клиент.

Варианты:
- `sourceCriterion.ipStrategy.depth: 1` — IP из `X-Forwarded-For` на глубине 1
- `sourceCriterion.requestHost: true` — лимит по хосту
- `sourceCriterion.requestHeaderName: "X-Api-Key"` — лимит по API ключу

### Distributed rate limit с Redis

Без Redis каждый инстанс Traefik считает локально. При 3 репликах и `average: 100` реальный лимит = 300.

С Redis: общий счетчик на всех инстансах.

### Rate limit vs DDoS

Traefik rate limit защищает от:
- Брутфорса (ограничение попыток входа)
- API abuse (ограничение вызовов)
- Скриптовых атак

Не protects от:
- Volumetric DDoS (L3/L4 flood) — нужен внешний LB/WAF
- Slowloris — нужен `inFlightReq` + таймауты
- Application layer DDoS с rotation IP — нужен WAF (CrowdSec)

## Практические сценарии

### Сценарий 1: Базовый rate limit по IP

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
```

### Сценарий 2: Rate limit по API ключу

```yaml
http:
  middlewares:
    api-key-limit:
      rateLimit:
        average: 50
        period: 1s
        burst: 100
        sourceCriterion:
          requestHeaderName: "X-Api-Key"
```

Важно: заголовок без дефисов/подчеркиваний (Traefik не рвет их).

### Сценарий 3: Distributed rate limit (Redis)

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
            - "redis-master:6379"
          db: 0
          password: "secret"
          poolSize: 20
          minIdleConns: 0
          maxActiveConns: 60
          dialTimeout: 5s
          readTimeout: 3s
          writeTimeout: 3s
```

Проверка:

```bash
redis-cli -p 6379 KEYS 'traefik:rate:*'
# → traefik:rate:<key>:<window>
```

### Сценарий 4: Multi-tenant rate limiting

Разные лимиты для разных tenants через header:

```yaml
http:
  middlewares:
    tenant-free:
      rateLimit:
        average: 10
        period: 1s
        sourceCriterion:
          requestHeaderName: "X-Tenant-ID"
    
    tenant-pro:
      rateLimit:
        average: 1000
        period: 1s
        sourceCriterion:
          requestHeaderName: "X-Tenant-ID"
```

Применение через chain:

```yaml
http:
  routers:
    api:
      rule: Host(`api.example.com`)
      service: api-service
      middlewares:
        - tenant-rate-limit
  middlewares:
    tenant-rate-limit:
      chain:
        middlewares:
          - extract-tenant
          - tenant-free
```

### Сценарий 5: Rate limit для WebSocket/gRPC

WebSocket/gRPC — долгие соединения, стандартный rate limit по requests не срабатывает.

Решение: `inFlightReq` middleware:

```yaml
http:
  middlewares:
    websocket-limit:
      inFlightReq:
        amount: 100
        sourceCriterion:
          ipStrategy:
            depth: 1
```

Для gRPC аналогично: `inFlightReq` ограничивает параллельные вызовы.

### Сценарий 6: Rate limit с Retry-After

Traefik автоматически добавляет `Retry-After` заголовок при 429:

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
        # Retry-After добавляется автоматически
```

Клиент получает:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 1
```

### Сценарий 7: Rate limit мониторинг

```yaml
# Prometheus алерты
groups:
- name: traefik.rate-limit
  rules:
  - alert: TraefikHighRateLimitRejections
    expr: sum(rate(traefik_middleware_requests_total{middleware="api-limit", code="429"}[5m])) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High rate limit rejections"
      description: "{{ $value }} requests rejected per second"

  - alert: TraefikRateLimitNearCapacity
    expr: sum(rate(traefik_rate_limit_usage_total{middleware="api-limit"}[5m])) / sum(rate(traefik_rate_limit_limit{middleware="api-limit"}[5m])) > 0.8
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Rate limit near capacity"
      description: "{{ $value | humanizePercentage }} capacity used"
```

### Сценарий 8: Брутфорс защита (Fail2ban + Traefik)

```yaml
http:
  middlewares:
    login-limit:
      rateLimit:
        average: 5
        period: 1m
        burst: 10
        sourceCriterion:
          ipStrategy:
            depth: 1
```

В kombinции с fail2ban на приложении (логи access log).

## Операции и команды

```bash
# Проверка headers rate limit
curl -sv https://api.example.com/ 2>&1 | grep -i 'x-rate-limit'
# → X-RateLimit-Limit: 100
# → X-RateLimit-Remaining: 42

# Проверка Redis ключей
redis-cli -p 6379 KEYS 'traefik:rate:*'
# → traefik:rate:192.168.1.1:1620000000

# Мониторинг метрик
curl -s localhost:9100/metrics | grep -E 'traefik_middleware_requests_total.*429|traefik_rate_limit'

# Проверка source criterion (какой IP видит Traefik)
curl -s http://localhost:8080/api/http/routers | jq '.[].rule'
# → Host(`api.example.com`) && PathPrefix(`/`)
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **429 на всех клиентов** | Rate limit по RemoteAddr (IP = LB) | Настройте `sourceCriterion.ipStrategy.depth` |
| **Лимит не работает в кластере** | Нет Redis, каждый инстанс считает локально | Добавьте Redis в `rateLimit` |
| **Rate limit обходится** | Клиенты rotation IP, используют proxy | Добавьте `requestHeaderName` (API key) или WAF |
| **Retry-After не приходит** | Клиент не запрашивает повторно | Проверьте клиентскую логику |
| **Redis unavailable → лимит отключен** | Traefik ведет себя как "open" при недоступности Redis | Настройте Sentinel/Cluster для Redis |
| **Много ключей в Redis** | Уникальных IP слишком много, memory pressure | Настройте `maxmemory` и `maxmemory-policy` в Redis |

## Рекомендации

- `average`/`burst`: для API с пиками `burst = 2-3 × average`; для строгого throttle `burst = average`
- `sourceCriterion`: для Traefik за LB используйте `ipStrategy.depth: 1` (или больше)
- Distributed rate limit: Redis обязателен для нескольких реплик
- Для WebSocket/gRPC: используйте `inFlightReq`, а не `rateLimit`
- Для multi-tenant: разные middleware с разными лимитами + header-based source
- Мониторьте 429 rejections: алерт при росте
- Для production: Redis с Sentinel/Cluster для HA
- Rate limit — не DDoS protection: используйте CrowdSec/WAF для L7 DDoS

## Дополнительная информация

- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, InFlightReq, CircuitBreaker
- [Traefik + CrowdSec](./traefik-edge-security-waf.md) — WAF, IP banning, DDoS protection
- [Доверенные заголовки](./traefik-forwarded-headers.md) — `sourceCriterion`, `depth`, `trustedIPs`
- [Networking: rate limiting](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md) — общие паттерны rate limiting
