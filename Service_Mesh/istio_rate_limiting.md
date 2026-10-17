# Ограничение скорости (Rate Limiting) в Istio

**Актуально для:** Istio 1.30+ / Istio 1.31 / Envoy 1.30+ / Gateway API v1.6.x / Kubernetes 1.32–1.37

## Определения

**Rate Limiting (ограничение скорости)** — механизм контроля количества запросов, обрабатываемых сервисом за единицу времени. В контексте Service Mesh rate limiting позволяет защитить бэкенды от перегрузки, предотвратить каскадные сбои и обеспечить справедливое распределение ресурсов между потребителями.

**Local Rate Limiting (локальное ограничение)** — ограничение, применяемое на уровне каждого экземпляра прокси (Envoy) индивидуально. Не требует внешнего сервиса; используется для защиты конкретного пода от перегрузки.

**Global Rate Limiting (глобальное ограничение)** — кластерное ограничение, учитывающее суммарную нагрузку на все эндпоинты сервиса. Требует внешнего Rate Limit Service (RLS) для агрегации счетчиков.

**EnvoyFilter** — ресурс Istio (`networking.istio.io/v1alpha3`), позволяющий кастомизировать конфигурацию Envoy на уровне фильтров. Используется для внедрения rate limiting в sidecar-прокси и Waypoint Proxy. API-версия остаётся `v1alpha3` во всех версиях Istio включая 1.30+ (никогда не продвигалась до `v1`). EnvoyFilter не поддерживается для waypoint-прокси.

**Provider-specific Policy Attachment** — ресурсы, привязываемые к `HTTPRoute` или `Service` через `targetRef`, для rate limiting вне core-спецификации Gateway API. Существенно зависят от провайдера: NGINX Gateway Fabric (`RateLimitPolicy`), Envoy Gateway (`BackendTrafficPolicy` с rate-limit), Traefik (`RateLimit` middleware через `ExtensionRef`).

---

## Основные концепции

### Архитектура Rate Limiting в Istio

В Istio 2026 года реализованы два основных подхода:

| Подход | Уровень | Требования | Применение |
| :--- | :--- | :--- | :--- |
| **Local Rate Limiting** | L4/L7 (Envoy sidecar / Ztunnel) | Только Istio, без внешних зависимостей | Защита от перегрузки конкретного экземпляра, defense-in-depth |
| **Global Rate Limiting** | L7 (Envoy sidecar / Waypoint) | Внешний Rate Limit Service (RLS) | Кластерное ограничение, справедливое распределение |

### Локальное ограничение: принцип работы

Каждый Envoy-прокси поддерживает встроенный `local_rate_limit` фильтр. При получении запроса Envoy проверяет локальный счетчик; если лимит превышен, запрос отклоняется с HTTP 429 (Too Many Requests) без обращения к бэкенду.

**Ключевые параметры:**
- `max_tokens` — максимальное количество токенов (запросов) в интервале.
- `tokens_per_fill` — количество токенов, добавляемых за один интервал заполнения.
- `fill_interval` — интервал заполнения токенов (минимум 1 миллисекунда).
- `filter_enabled` — процент трафика, к которому применяется лимит (для canary-тестирования политик).
- `filter_enforced` — процент трафика, для которого лимит actually применяется (отклонение).

### Глобальное ограничение: принцип работы

Envoy отправляет запрос к внешнему Rate Limit Service (RLS) перед обработкой трафика. RLS агрегирует счетчики по всем экземплярам Envoy и возвращает решение `OK`, `OVER_LIMIT` или `SHADOW`.

**Компоненты:**
- **Envoy Rate Limit Filter**: фильтр в цепочке Envoy, отправляющий запросы к RLS.
- **Rate Limit Service (RLS)**: внешний сервис (например, envoy-ratelimit на Go, Redis-backed), хранящий счетчики.
- **Redis**: хранилище счетчиков для RLS (опционально, зависит от реализации RLS).

### Разрешение 429 и Retry-After

При отклонении запроса из-за превышения лимита Envoy возвращает:
```
HTTP/1.1 429 Too Many Requests
Retry-After: 5
```
Клиент должен обрабатывать код 429 и повторять запрос с экспоненциальной задержкой (exponential backoff).

### Взаимодействие с другими механизмами Istio

| Механизм | Взаимодействие |
| :--- | :--- |
| **Circuit Breaking** | Rate limiting предотвращает исчерпание ресурсов; circuit breaking защищает от каскадных сбоев при уже поврежденных эндпоинтах. Используются вместе для многоуровневой защиты. |
| **Retries** | Ретраи НЕ должны повторять запросы, отклонённые rate limiter'ом (429). Настройте `retryOn` без `429` в retry policy. |
| **Outlier Detection** | Rate limiting снижает нагрузку, уменьшая вероятность eject'а эндпоинтов через outlier detection. |
| **AuthorizationPolicy** | Rate limiting применяется ПОСЛЕ авторизации. Неauthorized-запросы отклоняются до проверки лимитов. |

---

## Практические сценарии

### Сценарий 1: Локальный rate limiting через EnvoyFilter (Sidecar)

Ограничение 100 запросов в секунду на каждый экземпляр пода:

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: local-ratelimit
  namespace: my-app
spec:
  workloadSelector:
    labels:
      app: my-api
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: SIDECAR_INBOUND
      listener:
        filterChain:
          filter:
            name: envoy.filters.network.http_connection_manager
            subFilter:
              name: envoy.filters.http.router
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.local_ratelimit
        typed_config:
          "@type": type.googleapis.com/udpa.type.v1.TypedStruct
          type_url: type.googleapis.com/envoy.extensions.filters.http.local_ratelimit.v3.LocalRateLimit
          value:
            stat_prefix: http_local_rate_limiter
            token_bucket:
              max_tokens: 100
              tokens_per_fill: 100
              fill_interval: 1s
            filter_enabled:
              runtime_key: local_rate_limit_enabled
              default_value:
                numerator: 100
                denominator: HUNDRED
            filter_enforced:
              runtime_key: local_rate_limit_enforced
              default_value:
                numerator: 100
                denominator: HUNDRED
            response_headers_to_add:
            - append: false
              header:
                key: x-local-rate-limit
                value: 'true'
```

**Проверка:**
```bash
# Применение
kubectl apply -f local-ratelimit.yaml -n my-app

# Генерация нагрузки (vegeta)
echo 'GET http://my-api.my-app.svc.cluster.local/api/v1' | vegeta attack -rate=200 -duration=10s | vegeta report
# →ok: 1000, 429: 1000 (лимит 100 RPS на под, 10 подов = 1000 RPS)

# Проверка метрик Envoy
kubectl exec -n my-app <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep local_rate_limiter
# → http_local_rate_limiter.http_local_rate_limiter.enabled: 1
# → http_local_rate_limiter.http_local_rate_limiter.enforced: 1
# → http_local_rate_limiter.http_local_rate_limiter.over_limit: 150
```

### Сценарий 2: Локальный rate limiting по конкретным путям

Ограничение только для `/api/v1/checkout` — 10 RPS, для остальных путей — без лимита:

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: checkout-ratelimit
  namespace: my-app
spec:
  workloadSelector:
    labels:
      app: checkout-api
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: SIDECAR_INBOUND
      listener:
        filterChain:
          filter:
            name: envoy.filters.network.http_connection_manager
            subFilter:
              name: envoy.filters.http.router
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.local_ratelimit
        typed_config:
          "@type": type.googleapis.com/udpa.type.v1.TypedStruct
          type_url: type.googleapis.com/envoy.extensions.filters.http.local_ratelimit.v3.LocalRateLimit
          value:
            stat_prefix: http_local_rate_limiter
            token_bucket:
              max_tokens: 10
              tokens_per_fill: 10
              fill_interval: 1s
            filter_enabled:
              runtime_key: local_rate_limit_enabled
              default_value:
                numerator: 100
                denominator: HUNDRED
            filter_enforced:
              runtime_key: local_rate_limit_enforced
              default_value:
                numerator: 100
                denominator: HUNDRED
            local_rate_limit_per_downstream_connection: false
```

### Сценарий 3: Rate limiting для Waypoint Proxy (Ambient)

> **Важно:** EnvoyFilter не поддерживается для waypoint-прокси (Istio 1.30+). 
> Для rate limiting на Waypoint используйте:
> - **Gateway API Provider-specific политики** (см. ниже), или
> - **AuthorizationPolicy + RBAC** с ограничениями на количество запросов, или
> - **External Authorization (`ext-authz`)** с пользовательским rate limiter.

Для Waypoint Proxy, работающего через Gateway API, rate limiting реализуется через Policy Attachment, специфичные для провайдера:

**Envoy Gateway** (`BackendTrafficPolicy` с rate-limit):
```yaml
apiVersion: gateway.networking.k8s.io/v1alpha3
kind: HTTPRoute
metadata:
  name: api-route
  namespace: my-app
spec:
  parentRefs:
  - name: my-gateway
    namespace: my-app
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/
    forwardTo:
    - serviceName: api-svc
      port: 8080
    filters:
    - type: ExtensionRef
      extensionRef:
        group: gateway.networking.k8s.io
        kind: BackendTrafficPolicy
        name: api-ratelimit

---
apiVersion: gateway.networking.k8s.io/v1alpha3
kind: BackendTrafficPolicy
metadata:
  name: api-ratelimit
  namespace: my-app
spec:
  targetRefs:
  - name: api-svc
    kind: Service
    group: ""
  request:
    rateLimit:
      requests: 1000
      requestTimeout: 1s
      unit: Request
```

**Проверка:**
```bash
# Список Waypoint в неймспейсе
istioctl waypoint list -n my-app

# Проверка метрик rate limiting на Waypoint
kubectl exec -n my-app <waypoint-pod> -- curl -s 127.0.0.1:15000/stats | grep -E "rate_limit|429"
```

### Сценарий 4: Глобальный rate limiting через Rate Limit Service

Для кластерного ограничения (суммарно по всем подам) используется внешний RLS:

**1. Развертывание Rate Limit Service:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ratelimit
  namespace: istio-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ratelimit
  template:
    metadata:
      labels:
        app: ratelimit
    spec:
      containers:
      - name: ratelimit
        image: envoyproxy/ratelimit:latest
        ports:
        - containerPort: 8081
          name: http
        - containerPort: 8081
          name: grpc
        env:
        - name: USE_STATSD
          value: "false"
        - name: REDIS_SOCKET_TYPE
          value: tcp
        - name: REDIS_URL
          value: "redis-master.redis.svc.cluster.local:6379"
        - name: RUNTIME_ROOT
          value: /data
        - name: RUNTIME_SUBDIRECTORY
          value: ratelimit
        - name: RUNTIME_IGNOREDOTFILES
          value: "true"
        volumeMounts:
        - name: config
          mountPath: /data/ratelimit
      volumes:
      - name: config
        configMap:
          name: ratelimit-config
---
apiVersion: v1
kind: Service
metadata:
  name: ratelimit
  namespace: istio-system
spec:
  selector:
    app: ratelimit
  ports:
  - name: http
    port: 8081
    targetPort: 8081
  - name: grpc
    port: 8081
    targetPort: 8081
```

**2. Конфигурация лимитов:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ratelimit-config
  namespace: istio-system
data:
  config.yaml: |
    domain: my-api
    descriptors:
    - key: generic_key
      value: checkout
      rate_limit:
        unit: second
        requests_per_unit: 10
    - key: generic_key
      value: public
      rate_limit:
        unit: second
        requests_per_unit: 100
```

**3. EnvoyFilter для подключения к RLS:**
```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: global-ratelimit
  namespace: my-app
spec:
  workloadSelector:
    labels:
      app: checkout-api
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: SIDECAR_INBOUND
      listener:
        filterChain:
          filter:
            name: envoy.filters.network.http_connection_manager
            subFilter:
              name: envoy.filters.http.router
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.rate_limit
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.http.ratelimit.v3.RateLimit
          domain: my-api
          failure_mode_deny: false
          rate_limit_service:
            grpc_service:
              envoy_grpc:
                cluster_name: rate_limit_cluster
                authority: ratelimit.istio-system.svc.cluster.local
            transport_api_version: V3
  - applyTo: CLUSTER
    match:
      context: SIDECAR_OUTBOUND
    patch:
      operation: ADD
      value:
        name: rate_limit_cluster
        type: STRICT_DNS
        connect_timeout: 5s
        lb_policy: ROUND_ROBIN
        http2_protocol_options: {}
        load_assignment:
          cluster_name: rate_limit_cluster
          endpoints:
          - lb_endpoints:
            - endpoint:
                address:
                  socket_address:
                    address: ratelimit.istio-system.svc.cluster.local
                    port_value: 8081
```

### Сценарий 5: Rate Limiting с дифференциацией по потребителям (Global RLS)

> **Важно:** локальный rate limiting (`local_ratelimit`) не поддерживает дифференциацию по IP — 
> каждый под незнает о клиенте. Для IP-based лимитов используйте **Global Rate Limiting** через внешний RLS.

Ограничение по IP-адресу клиента (разные лимиты для внутренних и внешних потребителей) реализуется через `rate_limit` filter с `descriptors`:

**1. Обновлённый конфиг RLS (с сегментами по IP):**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ratelimit-config
  namespace: istio-system
data:
  config.yaml: |
    domain: my-api
    descriptors:
    # Глобальный лимит: 100 RPS на всех
    - key: generic_key
      value: default
      rate_limit:
        unit: second
        requests_per_unit: 100
    # Лимит на внутренние сети: 500 RPS
    - key: remote_address
      value: "10.0.0.0/8"
      rate_limit:
        unit: second
        requests_per_unit: 500
      descriptors:
      - key: generic_key
        value: internal
        rate_limit:
          unit: second
          requests_per_unit: 1000
    # Лимит на внешних потребителей: 50 RPS
    - key: remote_address
      value: "0.0.0.0/0"
      rate_limit:
        unit: second
        requests_per_unit: 50
```

**2. EnvoyFilter с `rate_limit` filter и `request_set_descriptors`:**
```yaml
apiVersion: networking.istio.io/v1alpha3
kind: EnvoyFilter
metadata:
  name: ip-based-ratelimit
  namespace: my-app
spec:
  workloadSelector:
    labels:
      app: public-api
  configPatches:
  - applyTo: HTTP_FILTER
    match:
      context: SIDECAR_INBOUND
      listener:
        filterChain:
          filter:
            name: envoy.filters.network.http_connection_manager
            subFilter:
              name: envoy.filters.http.router
    patch:
      operation: INSERT_BEFORE
      value:
        name: envoy.filters.http.rate_limit
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.http.ratelimit.v3.RateLimit
          domain: my-api
          failure_mode_deny: false
          rate_limit_service:
            grpc_service:
              envoy_grpc:
                cluster_name: rate_limit_cluster
```

### Сценарий 6: Проверка и диагностика

```bash
# 1. Проверка метрик local rate limiter
kubectl exec -n my-app <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep -E "local_rate|rate_limit"
# → http_local_rate_limiter.http_local_rate_limiter.enabled: 1
# → http_local_rate_limiter.http_local_rate_limiter.enforced: 1
# → http_local_rate_limiter.http_local_rate_limiter.over_limit: 42
# → http_local_rate_limiter.http_local_rate_limiter.not_enforced: 0

# 2. Проверка активных фильтров в listener
istioctl proxy-config listeners deploy/my-api -n my-app -o json | grep -A5 "local_ratelimit"

# 3. Тестирование rate limit (отправка burst-запросов)
for i in $(seq 1 200); do
  curl -s -o /dev/null -w "%{http_code}\n" http://my-api.my-app.svc.cluster.local/api/v1
done | sort | uniq -c
# → 150 200
# →  50 429

# 4. Проверка логов при отклонении запросов
kubectl logs <pod> -c istio-proxy -n my-app | grep "local_rate_limit"
# → [2026-09-22T...] "GET /api/v1" 429 - "-" 0 1234 5 2 "-" "curl/8.0" ... local_rate_limit_enforced true

# 5. Проверка конфигурации EnvoyFilter
kubectl get envoyfilter -n my-app
# → NAME              AGE
# → local-ratelimit   5m
```

---

## Операции и команды

### Управление EnvoyFilter

| Команда | Описание |
| :--- | :--- |
| `kubectl apply -f <file>.yaml -n <ns>` | Применить конфигурацию rate limiting |
| `kubectl delete envoyfilter <name> -n <ns>` | Удалить локальный rate limiting |
| `kubectl get envoyfilter -n <ns>` | Список EnvoyFilter в namespace |
| `istioctl proxy-config listeners deploy/<pod> -n <ns> -o json` | Проверить фильтры в listener chain |
| `istioctl proxy-config clusters deploy/<pod> -n <ns> -o json` | Проверить backend-кластеры |

### Метрики Envoy (admin /stats)

Метрики rate limiting доступны на `http://127.0.0.1:15000/stats` (admin port).

| Метрика | Описание |
| :--- | :--- |
| `local_rate_limit.enforced` | Количество отклонённых запросов (429) |
| `local_rate_limit.not_enforced` | Количество пропущенных (filter_enabled < 100%) |
| `rate_limit_service.ratelimit.ok` | RLS вернул OK |
| `rate_limit_service.ratelimit.error` | Ошибка связи с RLS |
| `rate_limit_service.ratelimit.over_limit` | RLS вернул OVER_LIMIT |

### Метрики RLS (Redis)

| Метрика | Источник |
| :--- | :--- |
| `redis.cmdstat_get` | Redis command stats |
| `envoy_cluster_ratelimit_rq_ok` | Envoy → RLS успешные |
| `envoy_cluster_ratelimit_rq_error` | Envoy → RLS ошибки |

---

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **429 Too Many Requests на здоровых сервисах** | Лимит слишком низкий или `tokens_per_fill` не совпадает с ожидаемой нагрузкой | Увеличьте `max_tokens` или уменьшите `fill_interval`. Проверьте метрики `over_limit` в Envoy stats. |
| **Rate limiting не применяется** | EnvoyFilter не совпадает с `workloadSelector` или `context` неверен | Проверьте `istioctl proxy-config listeners` — фильтр должен отображаться в цепочке. Убедитесь, что `context` соответствует модели (SIDECAR_INBOUND / GATEWAY). |
| **Все запросы отклоняются (100% 429)** | `max_tokens` установлен в 0 или `fill_interval` слишком мал | Проверьте YAML EnvoyFilter на ошибки валидации. Убедитесь, что `fill_interval` >= 1ms. |
| **Rate limit не работает для Waypoint** | EnvoyFilter не поддерживается для waypoint-прокси (Istio 1.30+) | Используйте provider-specific Policy Attachment (например, `BackendTrafficPolicy` в Envoy Gateway). |
| **Global RLS возвращает OVER_LIMIT для всех** | Redis недоступен или `failure_mode_deny: true` при сбое RLS | Проверьте доступность Redis: `kubectl exec -it <rls-pod> -- redis-cli ping`. Установите `failure_mode_deny: false` для fail-open поведения. |
| **Запросы с retry попадают под rate limit дважды** | Ретраи считаются новыми запросами для rate limiter'а | Настройте `retryOn` исключающее `429`; увеличьте `max_tokens` с учетом retry overhead. |

---

## Лучшие практики эксплуатации

1. **Defense-in-depth:** комбинируйте локальный rate limiting (защита конкретного пода) с глобальным (кластерное ограничение). Локальный — всегда, глобальный — когда критично.
2. **Начинайте с локального:** для первого внедрения используйте `local_rate_limit` через EnvoyFilter. Это не требует внешних сервисов и минимально влияет на латентность.
3. **Настройте `filter_enabled` и `filter_enforced` раздельно:** используйте `filter_enabled: 50%` для тестирования новой политики, а `filter_enforced: 100%` для ее реального применения. Это позволяет измерить влияние до полного внедрения.
4. **Не лимитируйте health-check'и:** исключите `/health`, `/ready`, `/live` из rate limiting через `descriptors` в RLS или через `envoy.filters.http.cors` / `envoy.filters.http.health_check` до rate limit фильтра.
5. **Обрабатывайте 429 на клиенте:** убедитесь, что клиенты реализуют `Retry-After` и exponential backoff. В Kubernetes-среде используйте resilience-библиотеки (Envoy retry, Istio retry policy).
6. **Мониторинг:** настройте алерты на метрику `over_limit` в Envoy stats. Рост этого счётчика указывает на проблемы с бэкендом или слишком агрессивными потребителями.
7. **Не используйте rate limiting для авторизации:** rate limiting — это protection от перегрузки, а не от несанкционированного доступа. Используйте `AuthorizationPolicy` для контроля доступа.
8. **Кардинальность метрик:** `stat_prefix` в EnvoyFilter задает префикс метрик. Используйте уникальные имена для разных сервисов, чтобы не путать метрики в Prometheus.
9. **Откат:** при проблемах EnvoyFilter можно удалить за секунды — `kubectl delete envoyfilter <name>`. Конфигурация откатывается мгновенно через xDS.

---

## Очистка и откат

При удалении rate limiting избавьтесь от всех созданных ресурсов:

```bash
# 1. Удаление локального rate limiting (EnvoyFilter)
kubectl delete envoyfilter local-ratelimit -n my-app
kubectl delete envoyfilter checkout-ratelimit -n my-app

# 2. Удаление глобального rate limiting
kubectl delete envoyfilter global-ratelimit -n my-app
kubectl delete deployment ratelimit -n istio-system
kubectl delete service ratelimit -n istio-system
kubectl delete configmap ratelimit-config -n istio-system

# 3. Проверка, что rate limiting больше не применяется
istioctl proxy-config listeners deploy/my-api -n my-app -o json | grep -c "local_ratelimit\|rate_limit"
# → 0

# 4. Проверка метрик — счётчики over_limit перестают расти
kubectl exec -n my-app <pod> -c istio-proxy -- curl -s 127.0.0.1:15000/stats | grep -E "local_rate_limiter|rate_limit"
```

---

## Дополнительная информация

### Сравнение с rate limiting в других системах

| Система | Механизм | Особенности |
| :--- | :--- | :--- |
| **Istio + Envoy** | EnvoyFilter (local) / EnvoyFilter + RLS (global) | L4/L7, local и global, интеграция с мешем |
| **NGINX Ingress** | `limit_req_zone` / `limit_req` | Только L7, уровня Ingress, без.mesh-интеграции |
| **Kong** | Rate Limiting plugin | Только L7, плагин-based, без Envoy-интеграции |
| **Traefik** | RateLimit middleware | Только L7, middleware-based |

### Связанные темы

- [Управление трафиком в Istio](./traffic_management.md) — circuit breaking, retries, timeouts
- [Политики безопасности Istio](./istio-security-policies.md) — AuthorizationPolicy для контроля доступа
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md) — outboundTrafficPolicy и scoping

Документация: [Envoy Rate Limit Filter](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/rate_limit_filter), [Istio Rate Limiting](https://istio.io/latest/docs/tasks/policy-enforcement/rate-limit/).
