# Health Checks в Traefik: активные, пассивные, пороговые значения, gRPC

## Определения

**Active health check** — периодическая проверка Traefikом доступности бэкенда (HTTP-запрос, TCP-connect, gRPC health).

**Passive health check** — анализ ошибок реального трафика: Traefik помечает сервер unhealthy после N неудач подряд, без отдельной проверки.

**Failure threshold** — количество последовательных неудач, после которого сервер помечается unhealthy.

**Success threshold** — количество последовательных успехов, после которого unhealthy сервер возвращается в пул.

**Health check header** — кастомный заголовок (например, `X-Health-Check: 1`), по которому приложение отличает проверки от реального трафика.

**gRPC health check** — проверка доступности gRPC-сервиса через стандартный протокол `grpc.health.v1`.

## Базовые концепции

### Active health checks (HTTP/TCP/gRPC)

Traefik поддерживает три типа active health checks:

| Тип | Синтаксис | Кейс |
| :--- | :--- | :--- |
| **HTTP** | `healthCheck.path`, `healthCheck.interval` | Стандартный HTTP-сервис |
| **TCP** | `healthCheck.send`/`expect` (payload) | PostgreSQL, Redis, SSH |
| **gRPC** | `healthCheck.grpc` | gRPC-сервисы |

### Passive health checks

В Traefik OSS passive health checks **не встроены** на уровне middleware. Реализуются через:
- Внешний LB с passive health (убирает ноду при 5xx)
- Circuit breaker (отключает сервис при превышении порога ошибок)
- Кастомный плагин или внешний orchestrator (Flagger, Argo Rollouts)

### Пороговые значения

Traefik использует:
- `healthCheck.interval` — частота проверок
- `healthCheck.timeout` — таймаут ожидания ответа
- `healthCheck.followRedirects` — следовать ли редиректам

Но **нет** встроенных `failureThreshold`/`successThreshold` на уровне сервиса. Вместо этого:
- Circuit breaker expression анализирует ratio ошибок за окно
- Внешний orchestrator (Flagger) управляет порогами

### Взаимодействие с K8s probes

K8s `readinessProbe`/`livenessProbe` работают **на уровне pod**, а Traefik health checks — **на уровне backend серверов**. Они независимы:

- `readinessProbe` определяет, попадает ли pod в Endpoints
- Traefik health check определяет, попадает ли сервер в балансировку

Оба должны быть настроены для полной картины здоровья.

## Практические сценарии

### Сценарий 1: HTTP health check (базовый)

```yaml
http:
  services:
    api-service:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 10s
          timeout: 3s
          followRedirects: true
        servers:
          - url: http://api-backend:8080
```

Параметры:
- `path` — эндпоинт здоровья (должен возвращать 200)
- `interval` — частота проверок (по умолчанию 30s)
- `timeout` — таймаут (по умолчанию 5s)
- `followRedirects` — следовать 3xx (по умолчанию false)

### Сценарий 2: TCP health check с payload

```yaml
tcp:
  services:
    postgres-service:
      loadBalancer:
        healthCheck:
          send: "SELECT 1;\n"
          expect: "1"
          interval: 10s
          timeout: 3s
        servers:
          - address: 10.0.0.10:5432
```

Для Redis:

```yaml
  healthCheck:
    send: "PING\r\n"
    expect: "PONG"
    interval: 5s
    timeout: 2s
```

### Сценарий 3: gRPC health check

Traefik v3 поддерживает gRPC health check через стандартный протокол:

```yaml
http:
  services:
    grpc-service:
      loadBalancer:
        healthCheck:
          grpc:
            service: "myapp.MyService"
            interval: 10s
            timeout: 3s
        servers:
          - url: "h2c://grpc-backend:50051"
```

Или через HTTPS:

```yaml
        servers:
          - url: "https://grpc-backend:8443"
```

### Сценарий 4: Passive health check через Circuit Breaker

```yaml
http:
  middlewares:
    api-circuit-breaker:
      circuitBreaker:
        expression: "ResponseCodeRatio(500, 600, 0, 600) > 0.50 || LatencyAtQuantileMS(50.0) > 500"
        checkPeriod: 10s
        fallbackDuration: 30s
        recoveryDuration: 30s
        responseCode: 503

  services:
    api-service:
      loadBalancer:
        servers:
          - url: http://api-backend:8080
        # passive: circuit breaker отключает сервер при ошибках
```

Circuit breaker анализирует только трафик, прошедший через middleware. Для сервисного уровня используйте service middleware:

```yaml
  services:
    api-service:
      middlewares:
        - api-circuit-breaker
      loadBalancer:
        servers:
          - url: http://api-backend:8080
```

### Сценарий 5: Health check с кастомным заголовком

Некоторые приложения требуют заголовка для区分 проверок:

```yaml
http:
  services:
    api-service:
      loadBalancer:
        healthCheck:
          path: /health
          headers:
            X-Health-Check: "1"
            X-Forwarded-Proto: "https"
          interval: 10s
          timeout: 3s
        servers:
          - url: http://api-backend:8080
```

### Сценарий 6: K8s readiness + Traefik health check

```yaml
# K8s Deployment
spec:
  template:
    spec:
      containers:
      - name: api
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10

# Traefik service
http:
  services:
    api-service:
      loadBalancer:
        healthCheck:
          path: /health
          interval: 10s
          timeout: 3s
        servers:
          - url: http://api-service:8080
```

### Сценарий 7: Отключение health check

Для сервисов, которые не имеют health endpoint:

```yaml
http:
  services:
    legacy-service:
      loadBalancer:
        healthCheck:
          path: /disable  # Traefik пропустит проверку
        servers:
          - url: http://legacy:8080
```

Или через `allowEmptyServices`:

```yaml
http:
  services:
    legacy-service:
      loadBalancer:
        allowEmptyServices: true
        servers: []
```

## Операции и команды

```bash
# Проверка статуса health check через API
curl -s http://localhost:8080/api/http/services/api-service | jq '.loadBalancer.servers'
# → [{"url":"http://10.0.0.1:8080","weight":1},{"url":"http://10.0.0.2:8080","weight":1}]

# Проверка, что сервер unhealthy
curl -s http://localhost:8080/api/http/services/api-service | jq '.[] | select(.status == "UNKNOWN")'

# Мониторинг метрик health check
curl -s localhost:9100/metrics | grep traefik_service_server_up
# → traefik_service_server_up{service="api-service",server="10.0.0.1:8080"} 1

# Проверка health endpoint бэкенда
curl -s http://api-backend:8080/health
# → {"status":"healthy"}

# TCP health check вручную
nc -zv 10.0.0.10 5432
# → Connection succeeded

# gRPC health check вручную
grpcurl -plaintext grpc-backend:50051 grpc.health.v1.Health/Check
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Все бэкенды unhealthy** | Неверный `path`/`send`, бэкенд не отвечает | Проверьте health endpoint, логи бэкенда |
| **Health check не работает для gRPC** | Нет `grpc.health.v1.Health` service на бэкенде | Реализуйте стандартный gRPC health check |
| **Traefik не видит K8s ready pod** | `readinessProbe` падает, но Traefik health check OK | Разделите логику readiness и Traefik health check |
| **Flapping серверов** | `interval` слишком частый, `timeout` слишком маленький | Увеличьте interval, настройте circuit breaker |
| **Health check портит метрики** | Запросы `/health` попадают в access log и метрики | Добавьте фильтр в access log или исключите из метрик |
| **TCP health check не работает** | Неверный `send`/`expect` payload | Проверьте протокол бэкенда (должен быть точный ответ) |
| **Circuit breaker не срабатывает** | Expression слишком строгий/слабый | Настройте пороги под ваши метрики |

## Рекомендации

- Всегда настраивайте health check для production-сервисов
- `interval`: 5-10s для критичных сервисов, 30s для обычных
- `timeout`: 2-3s (меньше чем interval)
- Используйте circuit breaker как passive health check механизм
- Для gRPC реализуйте стандартный `grpc.health.v1.Health` service
- Отделяйте `/health` (liveness) от `/ready` (readiness) на бэкенде
- Мониторьте `traefik_service_server_up` метрику
- Исключайте health check запросы из access log если нужно

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура, services, health checks
- [Middleware для управления трафиком](./traefik-middlewares-traffic.md) — circuit breaker как passive health
- [Traefik в Kubernetes](./traefik-kubernetes.md) — probes, PDB, rolling update
- [Наблюдаемость Traefik](./traefik-observability.md) — метрики `traefik_service_server_up`
