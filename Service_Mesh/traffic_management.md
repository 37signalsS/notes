# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор технологий для контроля, маршрутизации и обеспечения отказоустойчивости потоков запросов на уровне L7. В современных [Service Mesh](./service_mesh_concepts.md) эти функции реализуются плоскостью данных (Data Plane) и управляются декларативно.

В 2026 году индустрия полностью перешла на **Kubernetes Gateway API** (спецификация **GAMMA**) как единый стандарт управления трафиком как для входящего (North-South), так и для мессервисного (East-West) взаимодействия.

---

## Основные концепции

### Ключевые задачи

| Задача | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Веса (weights), фильтры по заголовкам/путям. | Canary-релизы, A/B-тестирование, Blue-Green. |
| **Отказоустойчивость** | Таймауты, ретраи (retries), разрыв цепи (circuit breaking). | Защита от каскадных сбоев и нестабильных эндпоинтов. |
| **Интеллектуальная балансировка** | HAZL (Linkerd), Locality-aware (Istio). | Снижение затрат на облачный трафик и Latency. |
| **AI-управление** | LLM-фильтры, Rate Limiting по токенам. | Управление трафиком к моделям ИИ и защита провайдеров. |
| **Эксперименты** | Зеркалирование (mirroring), внедрение ошибок (fault injection). | Тестирование в продакшене без риска для пользователей. |

### Сравнение примитивов управления (актуально на 2026 год)

| Возможность | Istio (1.30+) | Linkerd (2.20+) | Традиционный подход (Legacy) |
| :--- | :--- | :--- | :--- |
| **Основной API** | **Gateway API (GAMMA)** | **Gateway API (GAMMA)** | VirtualService / ServiceProfile |
| **Канареечные релизы** | `HTTPRoute` (backendRefs + weight) | `HTTPRoute` (backendRefs + weight) | TrafficSplit (SMI) |
| **Зеркалирование** | `HTTPRoute` (mirrors) | `HTTPRoute` (mirrors) | Специфичные аннотации |
| **Надежность (L7)** | Фильтры `HTTPRoute` / `RetryPolicy` | Фильтры `HTTPRoute` | ServiceProfile / Annotation |
| **Circuit Breaking** | `DestinationRule` / `BackendPolicy` | Автоматически на уровне прокси | — |
| **Балансировка** | Locality Load Balancing | **HAZL** (Zone-aware + 429 aware) | Topology Aware Hints (K8s) |

---

## Практические сценарии

### Сценарий 1: Канареечное развертывание (Istio/Linkerd через GAMMA)

В 2026 году для обеих платформ используется идентичный ресурс `HTTPRoute`. Здесь трафик распределяется между `v1` (90%) и `v2` (10%).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: prod
spec:
  parentRefs:
  - name: api-service # Ссылка на Service (GAMMA)
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

### Сценарий 2: Отказоустойчивость и таймауты (стандарт Gateway API)

Настройка автоматических повторных попыток для GET-запросов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-reliability
spec:
  parentRefs:
  - name: backend-service
    kind: Service
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
    # RetryPolicy (зависит от реализации контроллера)
```

### Сценарий 3: AI Gateway — управление трафиком LLM (Istio)

Сценарий 2026 года: ограничение потребления токенов для группы пользователей при обращении к моделям ИИ.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: TokenRateLimitPolicy
metadata:
  name: llm-token-limit
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: ai-route
  limit:
    tokensPerMinute: 10000
    burstSize: 2000
```

### Сценарий 4: HAZL — зональная балансировка (Linkerd 2.20+)

В Linkerd HAZL включен по умолчанию. Прокси автоматически удерживает трафик в зоне `europe-west1-a`, но переключит его на `europe-west1-b`, если задержки вырастут или эндпоинты начнут возвращать `429`.

```bash
# Проверка эффективности HAZL (экономия трафика)
linkerd viz stat deploy -n app --expected-zone-traffic
# → NAME    LOCAL_TRAFFIC    CROSS_ZONE_TRAFFIC    SAVINGS
# → app     98.5%            1.5%                  $450/mo
```

### Сценарий 5: Разрыв цепи (Istio Outlier Detection)

Изоляция неисправных подов, возвращающих ошибки 5xx.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-circuit-breaker
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 10s
      baseEjectionTime: 1m
      maxEjectionPercent: 100
```

---

## Дополнительная информация

### Иерархия ресурсов Gateway API (GAMMA)

1.  **GatewayClass:** определяет реализацию (Istio, Linkerd, Cilium).
2.  **Gateway:** описывает точку входа (шлюз) или Waypoint-прокси.
3.  **HTTPRoute / GRPCRoute:** описывают логику маршрутизации, привязанную к Service.
4.  **ReferenceGrant:** разрешает перекрестные ссылки между неймспейсами (безопасность).

### Лучшие практики эксплуатации

1.  **Стандартизация на GAMMA:** прекратите использование `VirtualService` и `ServiceProfile` в новых проектах для обеспечения переносимости между мешами.
2.  **Идемпотентность:** настраивайте `retries` только для методов, не изменяющих состояние (GET, HEAD, OPTIONS).
3.  **Мониторинг задержек:** используйте «золотые метрики» (RPS, Error Rate, P99 Latency) для автоматического отката канареечных релизов (например, через Argo Rollouts).
4.  **Сжатие трафика:** используйте фильтры сжатия (gzip/brotli) на уровне прокси для экономии пропускной способности.
5.  **Локальность трафика:** в мультизональных кластерах всегда используйте HAZL или Locality Load Balancing для минимизации задержек.

### Актуальность и ссылки

- **Istio 1.30+:** полная поддержка Gateway API и Ambient Mesh (стабильно).
- **Linkerd 2.20+:** нативная поддержка HTTPRoute и технология HAZL.
- **Kubernetes 1.31+:** Gateway API является стандартом по умолчанию для всех сетевых задач.

**См. также:**
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Gateway API: Глубокое погружение](../Kubernetes/Networking/gateway_api/definitions.md)

Документация: [Istio Traffic Management](https://istio.io/latest/docs/tasks/traffic-management/), [Linkerd Traffic Management](https://linkerd.io/2.20/features/traffic-management/).
