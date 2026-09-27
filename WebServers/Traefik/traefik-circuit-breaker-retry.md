# Circuit Breaker и Retry в Traefik: паттерны, комбинации, мониторинг

## Определения

**Circuit Breaker (CB)** — паттерн отказоустойчивости: автоматическое отключение сервиса при превышении порога ошибок с последующим gradual recovery.

**Состояния CB:** Closed (норма) → Open (разомкнута, запросы не идут) → Recovering (планирование восстановления) → Closed.

**Retry** — повторная отправка запроса при ошибке с задержкой.

**Retry budget** — ограничение общего количества retry-запросов относительно оригинального трафика для предотвращения retry storm.

**Exponential backoff** — экспоненциальное увеличение задержки между retry: 1s, 2s, 4s, 8s...

**Jitter** — случайное отклонение задержки для предотвращения thundering herd.

**Half-open** — пробный период, когда CB разрешает ограниченный трафик для проверки восстановления сервиса.

**Fallback service** — резервный сервис, возвращаемый когда CB разомкнут.

## Базовые концепции

### Circuit Breaker в Traefik

Traefik CB анализирует expression на основе метрик:

```yaml
circuitBreaker:
  expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.50 || LatencyAtQuantileMS(50.0) > 500"
  checkPeriod: 100ms
  fallbackDuration: 10s
  recoveryDuration: 10s
  responseCode: 503
```

Параметры:
- `expression` — условие срабатывания
- `checkPeriod` — интервал оценки (default 100ms)
- `fallbackDuration` — время в Open состоянии (default 10s)
- `recoveryDuration` — время gradual recovery (default 10s)
- `responseCode` — код при разомкнутой цепи (default 503)

### Retry в Traefik

```yaml
retry:
  attempts: 3
  initialInterval: 1s
  maxInterval: 8s
  # includedStatusCodes: [500, 502, 503]  # default: 5xx + 3xx(redirects)
```

Параметры:
- `attempts` — количество попыток (default 3)
- `initialInterval` — начальная задержка (default 1s)
- `maxInterval` — максимальная задержка (default 8s)
- `includedStatusCodes` — коды для retry
- `nonRetriableStatusCodes` — исключения из retry

### Circuit Breaker + Retry: правильная комбинация

Оба middleware применяются к роутеру или сервису. Порядок важен:

```
Request → Retry → CircuitBreaker → Service
```

Если CircuitBreaker Open → Retry не срабатывает (сервис недоступен).

Рекомендация: CB перед Retry, чтобы не нагружать failing сервис повторными попытками.

### Half-open поведение

Traefik не exposes half-open как отдельное состояние, но recovery работает по принципу half-open:

1. После `fallbackDuration` CB переходит в Recovering
2. В Recovering трафик постепенно растет линейно
3. Если ошибки — снова Open
4. Если успех — Closed

### Fallback service

Traefik не имеет встроенного fallback service для CB. Реализуется через Errors middleware:

```yaml
http:
  middlewares:
    fallback:
      errors:
        status:
          - "500-599"
        service: fallback-service
        query: "/error/{status}.html"
  services:
    fallback-service:
      loadBalancer:
        servers:
          - url: http://fallback:80
```

## Практические сценарии

### Сценарий 1: CB + Retry для API

```yaml
http:
  middlewares:
    api-resilience:
      chain:
        middlewares:
          - api-circuit-breaker
          - api-retry
  
  middlewares:
    api-circuit-breaker:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.40"
        checkPeriod: 100ms
        fallbackDuration: 30s
        recoveryDuration: 30s
        responseCode: 503
    
    api-retry:
      retry:
        attempts: 3
        initialInterval: 500ms
        maxInterval: 5s
        includedStatusCodes:
          - "500"
          - "502"
          - "503"
          - "504"
        # nonRetriableStatusCodes: [400, 401, 403]  # не ретраить клиентские ошибки
```

### Сценарий 2: Exponential backoff с jitter

Traefik retry не поддерживает jitter из коробки. Реализуется через внешний proxy или плагин.

Рекомендация: используйте conservative `initialInterval` (1s+) и `maxInterval` (8s+), чтобы избежать thundering herd.

### Сценарий 3: CB для gRPC/WebSocket

Для streaming соединений CB не срабатывает (статистика не собирается).

Решение: `inFlightReq` для ограничения параллельных соединений:

```yaml
http:
  middlewares:
    grpc-limit:
      inFlightReq:
        amount: 50
        sourceCriterion:
          ipStrategy:
            depth: 1
```

### Сценарий 4: Fallback service при CB Open

```yaml
http:
  middlewares:
    api-protection:
      chain:
        middlewares:
          - api-circuit-breaker
          - api-fallback
  
  middlewares:
    api-circuit-breaker:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.50"
        fallbackDuration: 30s
        responseCode: 503
    
    api-fallback:
      errors:
        status:
          - "500-599"
        service: static-fallback
        query: "/error/{status}.html
  
  services:
    static-fallback:
      loadBalancer:
        servers:
          - url: http://static-errors:80
```

### Сценарий 5: Monitoring CB и Retry

```yaml
# Prometheus алерты
groups:
- name: traefik.cb-retry
  rules:
  - alert: TraefikCircuitBreakerOpen
    expr: increase(traefik_middleware_circuit_breaker_opens_total[5m]) > 0
    for: 0m
    labels:
      severity: critical
    annotations:
      summary: "Circuit breaker opened"
      description: "Circuit breaker for {{ $labels.middleware }} is OPEN"

  - alert: TraefikHighRetryRate
    expr: sum(rate(traefik_middleware_retries_total[5m])) > 10
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High retry rate"
      description: "{{ $value }} retries per second"

  - alert: TraefikRetryStorm
    expr: sum(rate(traefik_middleware_retries_total[5m])) / sum(rate(traefik_middleware_requests_total[5m])) > 0.5
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Retry storm detected"
      description: "{{ $value | humanizePercentage }} of requests are retries"
```

## Операции и команды

```bash
# Проверка метрик circuit breaker
curl -s localhost:9100/metrics | grep circuit_breaker
# → traefik_middleware_circuit_breaker_opens_total{middleware="api-circuit-breaker"} 3

# Проверка метрик retry
curl -s localhost:9100/metrics | grep retries
# → traefik_middleware_retries_total{middleware="api-retry"} 42

# Проверка состояния через API
curl -s http://localhost:8080/api/http/middlewares | jq '.[] | select(.name == "api-circuit-breaker")'

# Проверка логов Traefik
docker logs traefik 2>&1 | grep -i "circuit\|breaker\|retry"
# → time="..." level=error msg="Circuit breaker opened" middleware="api-circuit-breaker"
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **CB постоянно открывается** | Expression слишком строгий, бэкенд медленный | Настройте пороги под ваши метрики |
| **Retry storm** | Много retry при failing бэкенде | Добавьте CB перед Retry, уменьшите attempts |
| **CB не срабатывает** | Expression не покрывает ошибки | Проверьте метрики, настройте expression |
| **WebSocket падает при CB** | CB не работает для streaming | Используйте `inFlightReq` вместо CB |
| **Fallback не работает** | Errors middleware не привязан | Проверьте chain на роутере |
| **Retry для POST запросов** | POST не идемпотентен, retry может дублировать | Используйте `nonRetriableStatusCodes` или уберите retry для POST |

## Рекомендации

- CB + Retry: CB перед Retry (не наоборот)
- Expression: настройте под ваши SLO, не используйте дефолтные пороги
- `attempts`: 2-3 максимум (больше = retry storm)
- `initialInterval`: 500ms-2s (защита от thundering herd)
- `maxInterval`: 5-10s
- Для WebSocket/gRPC: используйте `inFlightReq`, не CB
- Для non-idempotent запросов (POST/PUT): отключите retry
- Мониторьте `traefik_middleware_circuit_breaker_opens_total` и `traefik_middleware_retries_total`
- Fallback service: всегда предоставляйте понятный ответ при 503

## Дополнительная информация

- [Паттерны микросервисной архитектуры](../../Concepts/microservice_patterns.md) — отказоустойчивость и масштабируемость.
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — RateLimit, CircuitBreaker, Retry
- [Traefik + CrowdSec](./traefik-edge-security-waf.md) — WAF, DDoS protection
- [Networking: circuit breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md) — общие паттерны
- [CI-CD: reliability patterns](../../CI-CD/Core_Concepts/reliability_patterns.md) — retry budgets, jitter
