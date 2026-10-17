**Актуально для:** Istio 1.31.x / Linkerd 2.20+

# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор технологий для контроля, маршрутизации и обеспечения отказоустойчивости потоков запросов на уровне L7. В современных [Service Mesh](./service_mesh_concepts.md) эти функции реализуются плоскостью данных (Data Plane) и управляются декларативно.

**Gateway API (Kubernetes)** — стандартизированный набор CRD для описания сетевой маршрутизации в Kubernetes (альтернатива Ingress-контроллерам). **Standard Channel (v1.6.x)** на 2026 год: `GatewayClass`, `Gateway`, `HTTPRoute`, `GRPCRoute`, `TLSRoute`, `TCPRoute`, `UDPRoute`, `ReferenceGrant`, `BackendTLSPolicy`. Политики устойчивости (`BackendTrafficPolicy` и аналоги circuit-breaking/timeout/retry) — **provider-specific extension** (Envoy Gateway, KGateway, Traefik), а не Standard Channel.

**GAMMA** (Gateway API for Mesh Management and Administration) — подпроект Gateway API, определяющий использование стандартных ресурсов (`HTTPRoute`, `GRPCRoute`) для сервисного (East-West) трафика. Маршрут привязывается к `Service` через `parentRefs` (вместо `Gateway`), а не к шлюзу. Стандарт поддерживается контроллерами (Istio, Linkerd) на базе Gateway API v1.1.0+.

**VirtualService** — устаревший (legacy) Istio CRD для декларативного управления маршрутизацией, таймаутами, ретраями и зеркалированием. В 2026 году для новых проектов рекомендуется Gateway API; VirtualService сохраняет поддержку для обратной совместимости.

**DestinationRule** — Istio CRD (`networking.istio.io/v1`), определяющий политики трафика для конкретного хоста: подмножества (subsets), балансировку, circuit breaking, TLS-режим. Многие параметры DestinationRule (outlier detection, connection pool, locality LB) пока не имеют стандартного аналога в Gateway API Standard и реализуются через provider-specific политики.

**Gateway** — ресурс Gateway API (`gateway.networking.k8s.io/v1`), описывающий точку входа (ingress/egress) в кластер или Waypoint-прокси в Ambient Mesh.

**Locality Load Balancing** — механизм распределения трафика с учётом топологии (регион/зона), встроенный в Istio (`DestinationRule.spec.trafficPolicy.loadBalancer.localityLbSetting`) и реализуемый через Topology Aware Hints на уровне Kubernetes.

---

## Основные концепции

### Ключевые задачи

| Задача | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Веса (weights), фильтры по заголовкам/путям. | Canary-релизы, A/B-тестирование, Blue-Green. |
| **Отказоустойчивость** | Таймауты, ретраи (retries), разрыв цепи (circuit breaking). | Защита от каскадных сбоев и нестабильных эндпоинтов. |
| **Интеллектуальная балансировка** | Locality-aware (Istio), Topology Aware Routing (Linkerd). | Снижение задержек и оптимизация распределения трафика. |
| **Эксперименты** | Зеркалирование (RequestMirror), внедрение ошибок (fault injection). | Тестирование в продакшене без риска для пользователей. |

### Сравнение примитивов управления

| Возможность | Istio (1.30+) | Linkerd (2.20+) | Традиционный подход (Legacy) |
| :--- | :--- | :--- | :--- |
| **Основной API** | **Gateway API (GAMMA)** | **Gateway API (GAMMA)** | VirtualService / ServiceProfile |
| **Канареечные релизы** | `HTTPRoute` (`backendRefs` + `weight`) | `HTTPRoute` (`backendRefs` + `weight`) | TrafficSplit (SMI) |
| **Зеркалирование** | `HTTPRoute` (`RequestMirror` filter, провайдер-specific в Istio) | `HTTPRoute` (`RequestMirror`, ограничено) | Специфичные аннотации |
| **Надёжность (L7)** | `HTTPRoute` filters + `timeouts`/`retry` (Extended, v1.6+) + `DestinationRule` (legacy) | `HTTPRoute` filters + `timeouts`/`retry` (Extended, v1.6+) + `ServiceProfile` | ServiceProfile / Annotation |
| **Circuit Breaking** | `DestinationRule` (`outlierDetection`) + `connectionPool` + provider-specific `BackendTrafficPolicy` (Envoy Gateway) | Автоматически на уровне прокси; `ServiceProfile` для ограничений | — |
| **Балансировка** | Locality LB (`localityLbSetting`) / Topology Aware Routing | Topology Aware Routing (K8s hints) / HAZL | Topology Aware Hints (K8s) |

> **Примечание:** начиная с v1.6.0 (Standard Channel) таймауты и ретраи входят в core-спецификацию `HTTPRoute` (`rules.timeouts`, `rules.retry`, support: Extended). Circuit breaking (outlier detection, connection pool) и Locality LB остаются Istio-specific (`DestinationRule`) или реализуются через provider-specific Policy Attachment (`BackendTrafficPolicy` в Envoy Gateway).

### Иерархия ресурсов Gateway API (GAMMA)

1. **GatewayClass:** определяет реализацию (Istio, Linkerd, Envoy Gateway, Cilium).
2. **Gateway:** точка входа (ingress) или Waypoint-прокси (Ambient Mesh).
3. **HTTPRoute / GRPCRoute:** логика маршрутизации; в mesh-режиме (GAMMA) привязываются к **Service** через `parentRefs`, а не к `Gateway`.
4. **ReferenceGrant:** разрешает кросс-namespace ссылки на секреты и сервисы.
5. **Политики (Policy Attachment, provider-specific):** `BackendTrafficPolicy` (Envoy Gateway), `BackendTLSPolicy` — прикрепляются к `HTTPRoute`/`Service` через `targetRef` для circuit breaking и ConnectionPool, не покрытных core-спецификацией.

**GAMMA-привязка к `Service`:**
- **Producer route:** `HTTPRoute` в том же неймспейсе, что и `Service`; применяется ко всем клиентам, обращающимся к сервису.
- **Consumer route:** `HTTPRoute` в другом неймспейсе; применяется только к клиентам из неймспейса роута.
- Если хотя бы один `HTTPRoute` привязан к `Service`, запросы, не совпавшие ни с одним роутом, **отклоняются** (консистентное поведение GAMMA).

---

## Практические сценарии

### Предварительные требования

- **Kubernetes:** 1.32–1.37 (минимум 1.31 для Linkerd 2.20+; Istio 1.30+ поддерживает 1.32–1.37).
- **Controller Service Mesh:** Istio 1.30+ или Linkerd 2.20+ (с установленным Gateway API CRD v1.6.x, Standard Channel).
- **istioctl:** версия 1.30+ (или `linkerd` 2.20+ для Linkerd-сценариев).
- **East-West / North-South шлюзы** развернуты (для ingress-маршрутов — `Gateway` с listener'ом HTTP/HTTPS).
- **Сеть:** сервисы `api-v1`, `api-v2` (или `api-service`) должны быть созданы и иметь ready-эндпоинты.

### Сценарий 1: Канареечное развертывание (GAMMA)

В 2026 году для обеих платформ используется идентичный ресурс `HTTPRoute`. Здесь трафик распределяется между `v1` (90%) и `v2` (10%) через весовые коэффициенты в `backendRefs`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: prod
spec:
  parentRefs:
  - name: api-service       # Ссылка на Service (GAMMA)
    kind: Service
    group: ""
  rules:
  - backendRefs:
    - name: api-v1
      port: 8080
      weight: 90
    - name: api-v2
      port: 8080
      weight: 10
```

```bash
# Применение и проверка весов трафика
kubectl apply -f api-canary-route.yaml -n prod
istioctl analyze ns prod
# → No problems detected

# Проверка статуса маршрута (GAMMA)
kubectl get httproute api-canary -n prod -o jsonpath='{.status.parents[].conditions[?(@.type=="Accepted")].status}'
# → True
```

### Сценарий 2: Отказоустойчивость — таймауты и ретраи (Standard Channel)

В Gateway API v1.6+ (Standard Channel) таймауты и ретраи настраиваются **инлайн** в `HTTPRoute.rules[]` через поля `timeouts` и `retry` (support: Extended). Это устраняет необходимость в provider-specific Policy Attachment для базовых кейсов:

```yaml
# HTTPRoute: таймауты, ретраи и модификация заголовка (Standard Channel)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-reliability
  namespace: prod
spec:
  parentRefs:
  - name: backend-service
    kind: Service
    group: ""
  rules:
  - matches:
    - method: GET
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add:
        - name: x-retry-enabled
          value: "true"
    timeouts:
      request: 5s
    retry:
      codes: [503, 504]
      attempts: 3
      backoff: 100ms
    backendRefs:
    - name: backend-service
      port: 80
```

> Поле `backoff` по GEP-1731 — это одна Gateway API Duration (базовый интервал exponential backoff с jitter), а не объект. Имплементация может ограничивать задержку собственным максимумом (для Envoy-имплементаций обычно 10× base interval).

```bash
# 1. Проверка роута и статуса
kubectl apply -f api-reliability.yaml -n prod

# 2. Статус маршрута (GAMMA)
kubectl get httproute api-reliability -n prod -o jsonpath='{.status.parents[0].conditions[?(@.type=="Accepted")].status}'
# → True

# 3. Валидация через Istio (если используется Istio-контроллер)
istioctl analyze ns prod
# → No problems detected

# 4. Диагностика ретраев на стороне прокси
istioctl proxy-config routes deploy/api-v1-<pod> -n prod -o json | jq '.[0].route[0].retry_policy'
```

> **Примечание для Istio:** в режиме legacy `VirtualService` ретраи и таймауты задаются через `http[].retries` и `http[].timeout`. При миграции на Gateway API перенесите их в `HTTPRoute.rules[].retry` и `HTTPRoute.rules[].timeouts`.

#### Семантика ретраев и таймаутов в Istio VirtualService

Для Istio-контроллера важно знать поведение **по умолчанию** — именно оно чаще всего становится причиной неожиданной нагрузки на бэкенд или «зависших» запросов:

| Параметр | Поведение по умолчанию | Назначение |
| :--- | :--- | :--- |
| `http[].timeout` (request timeout) | **Отсутствует** — запрос может висеть неограниченно | Общий лимит времени на запрос со всеми ретраями. Задавайте всегда |
| `retries.attempts` (кластерный default) | **2 попытки** при условиях `connect-failure,refused-stream,unavailable,cancelled,retriable-status-codes` (ретраится в т.ч. 503) | Кластерно настраивается через `MeshConfig.defaultConfig.defaultHttpRetryPolicy`; `attempts: 0` отключает ретраи глобально |
| `retries.perTryTimeout` | равен `timeout` маршрута (итого — без отдельного лимита) | Таймаут одной попытки (initial + каждый ретрай) |
| `retries.backoff` | минимальный интервал 25 мс, экспоненциальный backoff | Защита бэкенда от «thundering herd» при ретраях |
| `retries.retryOn` | `connect-failure,refused-stream,unavailable,cancelled` | Условия ретрая: Envoy-условия через запятую + HTTP-коды (`"503,reset"`) |
| `retryIgnorePreviousHosts` | `true` — ретрай уходит на другой эндпоинт | Борьба с «ядовитыми» подами |
| `retryRemoteLocalities` | `false` — ретраи только в локальной localite | Для cross-region failover включается явно |

Ключевые взаимосвязи, спрашиваемые на собеседованиях:

- **Фактическое число ретраев ограничено общим timeout.** При `attempts: 3`, `backoff: 2s` и `timeout: 3s` успеет выполниться лишь один ретрай — остальные «съедает» ожидание.
- **Максимум запросов к бэкенду = 1 + attempts.** Ретраи умножают нагрузку: 10 RPS × 3 ретрая = до 40 запросов в секунду на деградирующем сервисе. Бюджет ретраев (`retryBudget` в circuit breaker Envoy) ограничивает параллельные ретраи долей активных запросов — см. [Свой Service Mesh на Envoy](./envoy-custom-service-mesh.md).
- **Ретраи не должны повторять запросы, отклонённые rate limiter'ом (429)** — исключайте `429` из `retryOn`, иначе лимитный запрос превращается в серию ретраев (см. [Rate Limiting](./istio_rate_limiting.md)).
- **Ретраи только для идемпотентных операций** (GET/HEAD/OPTIONS); для POST/PUT используйте только таймауты.

Пример `VirtualService` с явной отказоустойчивостью:

```yaml
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: api-reliability-vs
  namespace: prod
spec:
  hosts:
  - api-service
  http:
  - route:
    - destination:
        host: api-service
        subset: v1
    timeout: 5s              # общий лимит (по умолчанию отсутствует!)
    retries:
      attempts: 3            # до 3 ретраев, 1+3=4 запроса максимум
      perTryTimeout: 2s      # лимит одной попытки
      retryOn: connect-failure,refused-stream,503
```

```bash
# Проверка фактической retry-политики в конфиге Envoy
istioctl proxy-config routes deploy/api-client -n prod -o json \
  | jq '.[0].virtualHosts[] | select(.name=="api-service.prod.svc.cluster.local:80") | .routes[0].retry_policy'
# → {"retry_on": "connect-failure,refused-stream,retriable-status-codes",
#    "num_retries": 3, "per_try_timeout": "2s", ...}

# Отключение ретраев для конкретного маршрута
# retries: { attempts: 0 }
```

### Сценарий 3: Circuit Breaking (Outlier Detection)

Изоляция неисправных подов, возвращающих ошибки 5xx, через `DestinationRule.trafficPolicy.outlierDetection`.

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: api-circuit-breaker
  namespace: prod
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 10s
      baseEjectionTime: 1m
      maxEjectionPercent: 100
```

```bash
# Проверка outlier detection на стороне Envoy
istioctl proxy-config clusters deploy/api-v1-<pod> -n prod -o json \
  | jq '.[] | select(.name | contains("outlier"))'

# Проверка ejection-статуса подов
kubectl get pods -n prod -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations."sidecar\.istio\.io/ejected"}{"\n"}{end}'
# → <pod-name>    true
```

### Сценарий 4: Ограничения пула соединений (Connection Pool)

Контроль максимального количества соединений предотвращает истощение ресурсов на бэкенде. В Istio — через `DestinationRule.trafficPolicy.connectionPool`; в Gateway API — через provider-specific `BackendTrafficPolicy`.

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: api-connection-pool
  namespace: prod
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
        connectTimeout: 200ms
      http:
        http2MaxRequests: 1000
        maxRequestsPerConnection: 100
```

### Сценарий 5: Session Affinity через Consistent Hash

Для сохранения привязки сессии к конкретному эндпоинту (sticky sessions) используйте согласованный хеш на основе заголовка или cookies.

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: api-sticky
  namespace: prod
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      consistentHash:
        httpHeaderName: x-user-id
```

### Сценарий 6: Зональная балансировка (Topology Aware Routing + Locality LB)

**Topology Aware Routing (TAR)** — встроенный механизм Kubernetes для распределения трафика между эндпоинтами с учётом топологии кластера (зоны, регионы). TAR использует `Topology Aware Hints`, генерируемые kube-proxy, чтобы предпочитать эндпоинты в той же зоне, что и клиент.

Для mesh-уровня Istio дополнительно применяется **Locality Load Balancing** через `DestinationRule.trafficPolicy.loadBalancer.localityLbSetting` (см. [мультикластерный failover](./istio-multicluster.md)).

Важные ограничения TAR:
- Требует минимум 3 эндпоинта на зону для корректной работы.
- Не работает при `internalTrafficPolicy: Local` на Service.
- При невозможности удовлетворить запрос локальными эндпоинтами происходит fallback на межзонную маршрутизацию.

```bash
# Проверка статуса Topology Aware Hints
kubectl get endpoints api-service -n prod -o yaml | grep topology
# → hints:
#     topologyKeys:
#     - topology.kubernetes.io/zone
#     - ""
```

### Сценарий 7: Зеркалирование трафика (Traffic Mirror)

Зеркалирование отправляет копию запроса на тестовый бэкенд без влияния на ответ пользователю. Используется для тестирования новой версии в продакшене. В Gateway API — через фильтр `RequestMirror` (реализуется провайдерами, в т.ч. Istio); в Istio legacy — через `VirtualService.spec.http.mirror`.

```yaml
# VirtualService (Istio legacy): зеркалирование 10%
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: api-mirror
  namespace: prod
spec:
  hosts:
  - api-service
  http:
  - route:
    - destination:
        host: api-service
        subset: v1
    mirror:
      host: api-service
      subset: v2-canary
    mirrorPercentage:
      value: 10.0
```

```bash
# Проверка, что зеркалирование активно
istioctl proxy-config clusters deploy/api-v1-<pod> -n prod | grep mirror
# → <api-service_v2-canary> SNAKE_CASE 10.0%
```

### Сценарий 8: Внедрение ошибок (Fault Injection)

Искусственная инъекция задержек и abort-ошибок для проверки отказоустойчивости клиентов в продакшене.

```yaml
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: api-fault
  namespace: prod
spec:
  hosts:
  - api-service
  http:
  - fault:
      delay:
        percentage:
          value: 0.1
        fixedDelay: 2s
      abort:
        percentage:
          value: 0.05
        httpStatus: 503
    route:
    - destination:
        host: api-service
        subset: v1
```

### Сценарий 9: Маршрутизация по заголовкам

Роутинг на основе произвольных заголовков позволяет направлять трафик определённых групп пользователей на выделенные бэкенды.

```yaml
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: api-header-route
  namespace: prod
spec:
  hosts:
  - api-service
  http:
  - match:
    - headers:
        x-tenant:
          value: premium
    route:
    - destination:
        host: api-service
        subset: premium
  - route:
    - destination:
        host: api-service
        subset: standard
```

### Сценарий 10: Locality Failover (Istio)

Failover между регионами при недоступности локальных эндпоинтов через `localityLbSetting.failover`.

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: cross-region-failover
  namespace: prod
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      localityLbSetting:
        enabled: true
        failover:
        - from: us-east
          to: us-west
      simple: LEAST_REQUEST
```

```bash
# Проверка, что эндпоинты обоих регионов известны Envoy
istioctl proxy-config endpoint deploy/api-v1-<pod> -n prod | grep api-service
# → <us-east-endpoint>  HEALTHY
# → <us-west-endpoint>  HEALTHY

# При отказе us-east Envoy автоматически переключится на us-west
```

---

## Операции и команды

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `istioctl analyze` | Валидация конфигурации Istio на ошибки и конфликты | `No problems detected` |
| `istioctl proxy-status` | Синхронизация конфигурации proxy с istiod | `in sync` / `stale` |
| `istioctl proxy-config clusters <pod>` | Список upstream-кластеров (включая outlier/mirror) | `outlier_detection: enabled` |
| `istioctl proxy-config routes <pod>` | Таблицы маршрутизации Envoy | JSON-вывод маршрутов |
| `kubectl get httproute -A` | Статус HTTPRoute (Gateway API) | `Accepted / ResolvedRefs` |
| `istioctl proxy-config endpoint <pod>` | Активные эндпоинты (locality/failover) | `HEALTHY / UNHEALTHY` |

---

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **HTTP 503** на Gateway | Отсутствуют готовые эндпоинты (все исключены outlier detection) | Проверьте статусы подов (`kubectl get pods`); убедитесь, что readiness probe проходит; проверьте `maxEjectionPercent` |
| **HTTP 504** Gateway timeout | Превышен таймаут: `HTTPRoute.rules[].timeouts.request` или `DestinationRule` | Увеличьте timeout; оптимизируйте бэкенд; проверяйте задержки на уровне TCP |
| **Веса трафика не применяются** | Неправильное имя `Service` в `parentRefs` (GAMMA) или сумма весов ≠ 100 | Убедитесь, что `parentRefs` указывает на существующий `Service` и порт совпадает; проверьте веса в `backendRefs` |
| **Трафик игнорирует роут** | Правила `HTTPRoute` перекрываются (конфликт `hostname`/`sectionName`) или отсутствует `ReferenceGrant` | Проверьте порядок `rules`, наличие `ReferenceGrant` для соседних неймспейсов |
| **TAR не работает** | Менее 3 эндпоинтов на зону или `internalTrafficPolicy: Local` | Добавьте реплики или отключите `internalTrafficPolicy: Local` |
| **Reroutes циклично перезапускаются** | Ретраи без backoff или таймаут меньше времени обработки | Добавьте exponential backoff, увеличьте `http1MaxPendingRequests` |
| **Outlier detection не срабатывает** | `localityLbSetting.enabled` отключён или `consecutive5xxErrors` = 0 | Убедитесь, что `outlierDetection` задан и `localityLbSetting.enabled: true` |
| **Mirror traffic не доставляется** | Бэкенд-сервис не создан или недоступен | Проверьте, что mirror-host (`v2-canary`) развёрнут и имеет готовые эндпоинты |
| **Запрос висит без ответа (нет ни 2xx, ни 504)** | Не задан `request` timeout — в Istio он отсутствует по умолчанию | Задайте `timeouts.request` (HTTPRoute) или `http[].timeout` (VirtualService) |
| **Нагрузка на бэкенд растёт при деградации (ретраи xN)** | Кластерный default: до 2 ретраев на connect-failure/unavailable/503 | Ограничьте `attempts` явно (в т.ч. `attempts: 0` для неидемпотентных маршрутов); настройте `retryBudget` в circuit breaker |
| **Ретраи «съедают» лимиты rate limiter** | Ретраи 429-ответов от локального rate limiter | Исключите `429` из `retryOn`; см. [Rate Limiting](./istio_rate_limiting.md) |

### Методы диагностики

```bash
# 1. Полный аудит конфигурации Istio (конфликты VirtualService/DestinationRule)
istioctl analyze -A

# 2. Статус синхронизации proxy ↔ istiod
istioctl proxy-status <namespace>/<istio-proxy-pod>
#    или: istioctl proxy-status  # для всех proxy в mesh
# → sync: in sync / stale: <config-hash-mismatch>

# 3. Активные кластеры и outlier-статус Envoy
#    (источник эндпоинтов для outlier detection)
istioctl proxy-config clusters <namespace>/<istio-proxy-pod> -o json \
  | jq '.[] | select(.name | contains("outlier"))'

# 4. Таблицы маршрутизации (RDS) — как envoy роутит HTTP-запросы
istioctl proxy-config routes <namespace>/<istio-proxy-pod> -o json

# 5. Эндпоинты и topology-хинты
kubectl get endpoints <service> -n <namespace> -o yaml | grep -A3 topology
```

---

## Лучшие практики эксплуатации

1. **Стандартизация на Gateway API (GAMMA):** в новых проектах используйте `HTTPRoute` вместо `VirtualService` и `ServiceProfile` для переносимости между мешами. Учитывайте поведение «reject by default» при привязке роута к `Service`.
2. **Идемпотентность:** настраивайте ретраи только для методов, не изменяющих состояние (GET, HEAD, OPTIONS).
3. **Мониторинг задержек:** используйте «золотые метрики» (RPS, Error Rate, P99 Latency) для автоматического отката канареечных релизов. Для реализации автоматизации в CI/CD (Push-модель) см. [Практические сценарии автоматизации трафика](../CI-CD/Deployment_Strategies/canary_deployment.md#автоматизация-трафика-в-ci-пайплайнах-push-метод).
4. **Сжатие трафика:** используйте фильтры сжатия (gzip/brotli) на уровне прокси для экономии пропускной способности.
5. **Локальность трафика:** в мультизональных кластерах используйте зональную балансировку — Topology Aware Routing (Kubernetes Hints) или Locality Load Balancing (Istio). Учитывайте ограничения hints (TAR не работает при <3 эндпоинтах на зону и при `internalTrafficPolicy: Local`). Диагностика: [Cross-zone traffic и задержки](../Networking/Troubleshooting/cross-zone-latency.md).
6. **Мониторинг эндпоинтов:** отслеживайте метрики 5xx ошибок и latency P99 для раннего обнаружения деградации бэкендов.
7. **Гранулярность таймаутов:** устанавливайте таймауты на каждом уровне (Gateway, Route, Destination), начиная с более коротких на внешних роутах и увеличивая их на внутренних. Избегайте единого глобального таймаута.
8. **Избегайте конфликтов весов:** сумма весов в `backendRefs` должна быть корректна; Gateway API отклоняет роуты с нулевыми или отрицательными весами.
9. **Приоритет маршрутизации:** в Gateway API порядок правил (`rules`) определяет приоритет; более специфичные `matches` размещайте выше.
10. **Circuit breaking при масштабировании:** настраивайте `outlierDetection` и `connectionPool` до нагрузки; параметры по умолчанию часто слишком либеральны для продакшена.
11. **Валидация после каждого изменения:** используйте `istioctl analyze` или `kubectl apply --dry-run=client` для проверки ресурсов перед применением.
12. **Locality LB в multi-cluster:** для cross-region failover всегда задавайте `localityLbSetting` с `failover` и проверяйте topology-хинты через `istioctl proxy-config endpoint`.
13. **Явные ретраи и таймауты:** не полагайтесь на дефолты Istio — ретраи по умолчанию (до 2 попыток, включая 503) умножают нагрузку на деградирующий сервис, а request timeout по умолчанию отсутствует. Задавайте `timeout`/`retries` (или `timeouts`/`retry` в Gateway API) явно на каждом маршруте, ретраи — только для идемпотентных методов.

---

## Очистка и откат

При удалении канареечной конфигурации или откате изменений:

```bash
# 1. Удаление роутов и политик
kubectl delete httproute api-canary -n prod
kubectl delete destinationrule api-circuit-breaker -n prod
kubectl delete virtualservice api-* -n prod   # legacy

# 2. Проверка, что старый трафик больше не маршрутизируется на canary
istioctl proxy-config routes deploy/api-v1 -n prod -o json
# → только default-route на api-v1

# 3. Если удалялся VirtualService — убедитесь, что Service/DestinationRule
#    не ссылаются на удалённые подмножества (subsets)
kubectl get destinationrule -n prod -o yaml | grep subset
# → без ссылок на v2-canary
```

---

## Дополнительная информация

### Ссылки

- **Istio 1.30+:** полная поддержка Gateway API (включая policy-ресурсы через extension) и Ambient Mesh (GA с 1.24).
- **Linkerd 2.20+:** нативная поддержка `HTTPRoute`, системные политики и Topology Aware Routing.
- **Gateway API v1.6.x:** TCPRoute/UDPRoute/TLSRoute переведены в Standard (GA) в v1.6.0 (июнь 2026). GRPCRoute — Standard с v1.1.0.
- **Envoy 1.40.x:** расширяемость через `TrafficExtension` (Istio 1.30+) заменяет устаревший `WasmPlugin`.

**См. также:**
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md) — `outboundTrafficPolicy`, `MeshConfig`
- [Мультикластерная и мультисетевая архитектура Istio](./istio-multicluster.md) — locality failover
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [DNS Proxy и автоаллокация в Istio](./istio-dns.md)
- [Gateway API: ресурсы и статусы](../Kubernetes/Networking/gateway_api/resources.md)
- [Gateway API: миграция с Ingress](../Kubernetes/Networking/gateway_api/migration.md)

Документация: [Istio Traffic Management](https://istio.io/latest/docs/tasks/traffic-management/), [Linkerd Traffic Management](https://linkerd.io/docs/features/gateway-api/), [Gateway API Reference](https://gateway-api.sigs.k8s.io/reference/).