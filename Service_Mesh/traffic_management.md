# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор технологий для контроля, маршрутизации и обеспечения отказоустойчивости потоков запросов на уровне L7. В современных [Service Mesh](./service_mesh_concepts.md) эти функции реализуются плоскостью данных (Data Plane) и управляются декларативно.

В 2026 году основным способом управления трафиком стал **Kubernetes Gateway API**. Его подпроект **GAMMA** (Gateway API for Mesh Management and Administration) определяет использование стандартных ресурсов (`HTTPRoute`, `GRPCRoute`) для мессервисного (East-West) трафика, привязывая роуты напрямую к `Service` вместо `Gateway`. Поддержка mesh-сценариев включена в Standard Channel Gateway API с версии v1.1.0; актуальная версия спецификации на середину 2026 года — **v1.6.x** (TCPRoute и UDPRoute переведены в Standard в v1.6.0, июнь 2026). Gateway API охватывает как входящий (North-South), так и мессервисный трафик единой объектной моделью.

---

## Основные концепции

### Ключевые задачи

| Задача | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Веса (weights), фильтры по заголовкам/путям. | Canary-релизы, A/B-тестирование, Blue-Green. |
| **Отказоустойчивость** | Таймауты, ретраи (retries), разрыв цепи (circuit breaking). | Защита от каскадных сбоев и нестабильных эндпоинтов. |
| **Интеллектуальная балансировка** | HAZL (BEL), Topology Aware Routing (Linkerd), Locality-aware (Istio). | Снижение затрат на облачный трафик и Latency. |
| **AI-управление** | LLM-фильтры, Rate Limiting по токенам. | Управление трафиком к моделям ИИ и защита провайдеров. |
| **Эксперименты** | Зеркалирование (mirroring), внедрение ошибок (fault injection). | Тестирование в продакшене без риска для пользователей. |

### Сравнение примитивов управления

| Возможность | Istio (1.30+) | Linkerd (2.20+) | Традиционный подход (Legacy) |
| :--- | :--- | :--- | :--- |
| **Основной API** | **Gateway API (GAMMA)** | **Gateway API (GAMMA)** | VirtualService / ServiceProfile |
| **Канареечные релизы** | `HTTPRoute` (backendRefs + weight) | `HTTPRoute` (backendRefs + weight) | TrafficSplit (SMI) |
| **Зеркалирование** | `HTTPRoute` (mirrors) | `HTTPRoute` (mirrors) | Специфичные аннотации |
| **Надежность (L7)** | Фильтры `HTTPRoute` / `RetryPolicy` (Gateway API) / `DestinationRule` | Фильтры `HTTPRoute` / `ServiceProfile` | ServiceProfile / Annotation |
| **Circuit Breaking** | `DestinationRule` (outlierDetection) / `BackendPolicy` | Автоматически на уровне прокси, произвольный (arbitrary) разрыв цепи | — |
| **Балансировка** | Locality Load Balancing (Topology Hints / `LocalityLoadBalancerSetting`) | Topology Aware Routing (K8s hints) или **HAZL** (BEL, zone-aware + 429-aware) | Topology Aware Hints (K8s) |

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

В стандарте Gateway API таймауты настраиваются инлайн в `HTTPRoute.rules.timeouts`, а повторные попытки выносятся в отдельные политики Policy Attachment (`RetryPolicy` — в Istio, `BackendTrafficPolicy` — в Envoy Gateway), поэтому не зависят от реализации конкретного контроллера. Ниже — пример таймаута запроса и модификации заголовка.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-reliability
  namespace: prod
spec:
  parentRefs:
  - name: backend-service
    kind: Service
    group: core
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
    backendRefs:
    - name: backend-service
      port: 80
```

Ретраи и таймауты также могут задаваться на уровне Backend через политику `RetryPolicy` (Istio/Gateway API), прикрепляемую через `targetRef` к `HTTPRoute` или `Service`.

### Сценарий 3: AI Gateway — управление трафиком LLM (Envoy AI Gateway)

Управление трафиком к LLM-моделям в 2026 году реализуется через выделенный **Envoy AI Gateway** (GA с июня 2026) — проект поверх Envoy Gateway от CNCF. Токен-ориентированные политики (`TokenRateLimitPolicy`, `BackendTrafficPolicy` с Global Rate Limit) позволяют ограничивать потребление токенов по пользователям и моделям, а не количеством запросов. Токены извлекаются из ответов LLM в формат OpenAI и аккумулируются в Redis-backed rate limit service.

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

В Istio аналогичная функциональность достигается через WASM-расширения/Envoy-фильтры поверх Gateway API, но начиная с 2026 года LLM-специфичные фильтры (rate limit по токенам, балансировка промптов между провайдерами, failover) вынесены именно в отдельный проект Envoy AI Gateway.

### Сценарий 4: HAZL — зональная балансировка (Buoyant Enterprise for Linkerd 2.20+)

**HAZL** (High Availability Zonal Load balancing) — проприетарная функция **Buoyant Enterprise for Linkerd** (BEL), а не составная часть open-source Linkerd. Она **выключена по умолчанию** и включается флагом destination controller (`-ext-endpoint-zone-weights`). Прокси автоматически удерживает трафик в зоне `europe-west1-a`, но переключит его на `europe-west1-b`, если задержки вырастут или эндпоинты начнут возвращать `429`. С 2.20 HAZL учитывает rate-limit-ответы и через `BUOYANT_BALANCER_READINESS_SCALING=true` временно выводит перегруженные эндпоинты из пула.

В open-source Linkerd зональность обеспечивается стандартным **Topology Aware Routing** на базе Kubernetes Topology Aware Hints (`service.kubernetes.io/topology-aware-hints=auto`), но без rate-limit-aware поведения и динамического вывода эндпоинтов.

```bash
# Проверка эффективности зональной маршрутизации (экономия трафика)
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

1.  **GatewayClass:** определяет реализацию (Istio, Linkerd, Cilium, Envoy Gateway).
2.  **Gateway:** описывает точку входа (шлюз) или Waypoint-прокси (в Ambient Mesh).
3.  **HTTPRoute / GRPCRoute:** описывают логику маршрутизации; в mesh-режиме (GAMMA) привязываются к **Service** через `parentRefs`, а не к `Gateway`.
4.  **ReferenceGrant:** разрешает перекрестные ссылки между неймспейсами (безопасность).
5.  **Политики (Policy Attachment):** `RetryPolicy`, `TimeoutPolicy`, `BackendPolicy`/`BackendTrafficPolicy`, `SecurityPolicy` — прикрепляются к `HTTPRoute`/`Service` через `targetRef`, заменяют разрозненные аннотации.

Детали GAMMA-привязки к `Service` (producer/consumer routes):
- **Producer route:** `HTTPRoute` в том же неймспейсе, что и `Service`; применяется ко всем клиентам, обращающимся к сервису.
- **Consumer route:** `HTTPRoute` в другом неймспейсе; применяется только к клиентам из неймспейса роута.
- Если хотя бы один `HTTPRoute` привязан к `Service`, запросы, не совпавшие ни с одним роутом, **отклоняются** (консистентное поведение GAMMA).

### Лучшие практики эксплуатации

1.  **Стандартизация на GAMMA:** в новых проектах используйте `HTTPRoute` (Gateway API) вместо `VirtualService` и `ServiceProfile` для обеспечения переносимости между мешами. Учитывайте поведение «reject by default» при привязке роута к `Service`.
2.  **Идемпотентность:** настраивайте `retries` только для методов, не изменяющих состояние (GET, HEAD, OPTIONS).
3.  **Мониторинг задержек:** используйте «золотые метрики» (RPS, Error Rate, P99 Latency) для автоматического отката канареечных релизов. Для реализации автоматизации в Push-модели (CI -> Cluster) см. **[Практические сценарии автоматизации трафика](../CI-CD/Deployment_Strategies/canary_deployment.md#автоматизация-трафика-в-ci-пайплайнах-push-метод)**.
4.  **Сжатие трафика:** используйте фильтры сжатия (gzip/brotli) на уровне прокси для экономии пропускной способности.
5.  **Локальность трафика:** в мультизональных кластерах используйте зональную балансировку — Topology Aware Routing (open-source Linkerd), HAZL (Buoyant Enterprise) или Locality Load Balancing (Istio) — для минимизации задержек и межзонных затрат. Учитывайте ограничения hints (TAR не работает при <3 эндпоинтов на зону и при `internalTrafficPolicy: Local`). Подробнее о диагностике: **[Cross-zone traffic и задержки](../Networking/Troubleshooting/cross-zone-latency.md)**.
6.  **AI-трафик:** для LLM-нагрузок применяйте Envoy AI Gateway с токен-ориентированными лимитами (`TokenRateLimitPolicy`) — они лимитируют по фактическому потреблению токенов, а не по количеству запросов.

### Актуальность и ссылки

- **Istio 1.30+:** полная поддержка Gateway API (включая policy-ресурсы) и Ambient Mesh (GA с 1.24).
- **Linkerd 2.20+:** нативная поддержка `HTTPRoute`, системные политики и Topology Aware Routing; **HAZL** доступен только в Buoyant Enterprise for Linkerd.
- **Gateway API v1.6.x:** TCPRoute/UDPRoute переведены в Standard; GAMMA-поддержка зафиксирована в Standard Channel с v1.1.0.
- **Envoy AI Gateway 1.0:** GA с июня 2026, токен-ориентированные лимиты для LLM-трафика.

**См. также:**
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Gateway API: Глубокое погружение](../Kubernetes/Networking/gateway_api/definitions.md)

Документация: [Istio Traffic Management](https://istio.io/latest/docs/tasks/traffic-management/), [Linkerd Traffic Management](https://linkerd.io/docs/features/gateway-api/).
