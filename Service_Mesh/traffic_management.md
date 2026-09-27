# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор технологий для контроля, маршрутизации и обеспечения отказоустойчивости потоков запросов на уровне L7. В современных [Service Mesh](./service_mesh_concepts.md) эти функции реализуются плоскостью данных (Data Plane) и управляются декларативно.

В 2026 году основным способом управления трафиком стал **Kubernetes Gateway API**. Его подпроект **GAMMA** (Gateway API for Mesh Management and Administration) определяет использование стандартных ресурсов (`HTTPRoute`, `GRPCRoute`) для мессервисного (East-West) трафика, привязывая роуты напрямую к `Service` вместо `Gateway`. Поддержка mesh-сценариев включена в Standard Channel Gateway API с версии v1.1.0; актуальная версия спецификации на середину 2026 года — **v1.6.x** (TCPRoute и UDPRoute переведены в Standard в v1.6.0, июнь 2026). Gateway API охватывает как входящий (North-South), так и мессервисный трафик единой объектной моделью.

**VirtualService** — устаревший Istio CRD для декларативного управления маршрутизацией, таймаутами, ретраями и зеркалированием. В 2026 году для новых проектов рекомендуется Gateway API, но VirtualService сохраняет поддержку для обратной совместимости.

**DestinationRule** — Istio CRD, определяющий политики трафика для конкретного хоста: подмножества (subsets), балансировку, circuit breaking, TLS-режим. С 2026 года многие параметры DestinationRule дублируются в Gateway API через `BackendPolicy` и политики Policy Attachment.

**Gateway** — ресурс Gateway API, описывающий точку входа ( ingress/egress ) в кластер. В Ambient Mesh Gateway может представлять Waypoint-прокси.

---

## Основные концепции

### Ключевые задачи

| Задача | Техническая реализация | Цель |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Веса (weights), фильтры по заголовкам/путям. | Canary-релизы, A/B-тестирование, Blue-Green. |
| **Отказоустойчивость** | Таймауты, ретраи (retries), разрыв цепи (circuit breaking). | Защита от каскадных сбоев и нестабильных эндпоинтов. |
| **Интеллектуальная балансировка** | Locality-aware (Istio), Topology Aware Routing (Linkerd). | Снижение задержек и оптимизация распределения трафика. |
| **Эксперименты** | Зеркалирование (mirroring), внедрение ошибок (fault injection). | Тестирование в продакшене без риска для пользователей. |

### Сравнение примитивов управления

| Возможность | Istio (1.30+) | Linkerd (2.20+) | Традиционный подход (Legacy) |
| :--- | :--- | :--- | :--- |
| **Основной API** | **Gateway API (GAMMA)** | **Gateway API (GAMMA)** | VirtualService / ServiceProfile |
| **Канареечные релизы** | `HTTPRoute` (backendRefs + weight) | `HTTPRoute` (backendRefs + weight) | TrafficSplit (SMI) |
| **Зеркалирование** | `HTTPRoute` (mirrors) | `HTTPRoute` (mirrors) | Специфичные аннотации |
| **Надежность (L7)** | Фильтры `HTTPRoute` / `RetryPolicy` (Gateway API) / `DestinationRule` | Фильтры `HTTPRoute` / `ServiceProfile` | ServiceProfile / Annotation |
| **Circuit Breaking** | `DestinationRule` (outlierDetection) / `BackendPolicy` | Автоматически на уровне прокси, произвольный (arbitrary) разрыв цепи | — |
| **Балансировка** | Locality Load Balancing (Topology Hints / `LocalityLoadBalancerSetting`) | Topology Aware Routing (K8s hints) | Topology Aware Hints (K8s) |

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

### Сценарий 4: Зональная балансировка (Topology Aware Routing)

**Topology Aware Routing (TAR)** — встроенный механизм Kubernetes для распределения трафика между эндпоинтами с учетом топологии кластера (зоны, регионы). TAR использует `Topology Aware Hints`, генерируемые kube-proxy, чтобы предпочитать эндпоинты в той же зоне, что и клиент. В open-source Linkerd и Istio эта функция поддерживается нативно, но без динамического вывода эндпоинтов при перегрузке.

Важные ограничения TAR:
- Требует минимум 3 эндпоинтов на зону для корректной работы.
- Не работает при `internalTrafficPolicy: Local` на Service.
- При невозможности удовлетворить запрос локальными эндпоинтами происходит fallback на межзонную маршрутизацию.

```bash
# Проверка статуса Topology Aware Hints
kubectl get endpoints <service-name> -n <namespace> -o yaml | grep topology
# → hints:
#     topologyKeys:
#     - topology.kubernetes.io/zone
#     - ""
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

### Сценарий 6: Ограничения пула соединений (Connection Pool)

Контроль максимального количества соединений предотвращает истощение ресурсов на бэкенде. В Istio параметры задаются в `DestinationRule.trafficPolicy.connectionPool`, в Gateway API — через `BackendTrafficPolicy`.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-connection-pool
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
        connectTimeout: 200ms
      http:
        http2MaxRequests: 1000
        h2UpgradePolicy: DEFAULT
```

### Сценарий 7: Session Affinity через Consistent Hash

Для сохранения привязки сессии к конкретному эндпоинту (sticky sessions) используйте согласованный хеш на основе заголовка или источника IP. В Istio параметр задается в `DestinationRule.loadBalancer.consistentHash`.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-sticky
spec:
  host: api-service.prod.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      consistentHash:
        httpHeaderName: x-user-id
```

### Сценарий 8: Зеркалирование трафика (Traffic Mirror)

Зеркалирование отправляет копию запроса на тестовый бэкенд без влияния на ответ пользователю. Используется для тестирования новой версии в продакшне.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-mirror
spec:
  host: api-service
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

### Сценарий 9: Внедрение ошибок (Fault Injection)

Искусственная инъекция задержек и abort-ошибок для проверки отказоустойчивости клиентов в продакшне.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-fault
spec:
  host: api-service
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

### Сценарий 10: Маршрутизация по заголовкам

Роутинг на основе произвольных заголовков позволяет направлять трафик определенных групп пользователей на выделенные бэкенды.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-header-route
spec:
  host: api-service
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

### Сценарий 11: Валидация и диагностика политик трафика

После применения политик выполните проверку актуального состояния роутов и outlier detection.

```bash
# Проверка статуса синхронизации конфигурации (istioctl)
istioctl proxy-status

# Анализ конфликтов в маршрутизации
istioctl analyze ns prod

# Проверка активных эндпоинтов и outlierDetection
kubectl get endpoints api-service -n prod -o yaml

# Сбор логов прокси для диагностики маршрутизации
istioctl proxy-config routes deploy/<pod> --name http.8000 -o json
```

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
5.  **Локальность трафика:** в мультизональных кластерах используйте зональную балансировку — Topology Aware Routing (Kubernetes Hints) или Locality Load Balancing (Istio) — для минимизации задержек и межзонных затрат. Учитывайте ограничения hints (TAR не работает при <3 эндпоинтов на зону и при `internalTrafficPolicy: Local`). Подробнее о диагностике: **[Cross-zone traffic и задержки](../Networking/Troubleshooting/cross-zone-latency.md)**.
6.  **Мониторинг эндпоинтов:** отслеживайте метрики 5xx ошибок и latency P99 для раннего обнаружения деградации бэкендов.
7.  **Гранулярность таймаутов:** устанавливайте таймауты на каждом уровне (Gateway, Route, Destination), начиная с более коротких на внешних роутах и увеличивая их на внутренних. Избегайте единого глобального таймаута.
8.  **Избегайте конфликтов весов:** сумма весов в `backendRefs` или `route` должна быть валидна; Gateway API отклоняет роуты с нулевыми или отрицательными весами.
9.  **Приоритет маршрутизации:** в Gateway API порядок правил (`rules`) определяет приоритет; более специфичные `matches` размещайте выше.
10.  **Circuit breaking при масштабировании:** настройте `outlierDetection` и `connectionPool` до набора нагрузки; параметры по умолчанию часто слишком либеральны для продакшна.
11.  **Валидация после каждого изменения:** используйте `istioctl analyze` или `kubectl apply --dry-run` для проверки ресурсов перед применением в кластер.

### Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **HTTP 503** на Gateway | Отсутствуют готовые эндпоинты (все эндпоинты исключены outlier detection) | Проверьте статусы подов (`kubectl get pods`), убедитесь что readiness probe проходит, проверьте `maxEjectionPercent` |
| **HTTP 504** Gateway timeout | Превышен `request timeout` в `HTTPRoute` или `DestinationRule` | Увеличьте таймаут или оптимизируйте бэкенд; проверьте задержки на уровне TCP |
| **Веса трафика не применяются** | Неправильное имя `Service` в `parentRefs` (GAMMA) | Убедитесь что `parentRefs` указывает на существующий `Service` и порт совпадает |
| **Трафик игнорирует роут** | Правила `HTTPRoute` перекрываются или отсутствует ReferenceGrant | Проверьте порядок `rules`, наличие `ReferenceGrant` для соседних неймспейсов |
| **TAR не работает** | Менее 3 эндпоинтов на зону или `internalTrafficPolicy: Local` | Добавьте реплики или отключите `internalTrafficPolicy: Local` |
| **Reroutes циклично перезапускаются** | Ретраи без backoff или таймаут меньше времени обработки | Добавьте exponential backoff, увеличьте `http1MaxPendingRequests` |

### Актуальность и ссылки

- **Istio 1.30+:** полная поддержка Gateway API (включая policy-ресурсы) и Ambient Mesh (GA с 1.24).
- **Linkerd 2.20+:** нативная поддержка `HTTPRoute`, системные политики и Topology Aware Routing.
- **Gateway API v1.6.x:** TCPRoute/UDPRoute переведены в Standard; GAMMA-поддержка зафиксирована в Standard Channel с v1.1.0.

**См. также:**
- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Gateway API: Глубокое погружение](../Kubernetes/Networking/gateway_api/definitions.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)

Документация: [Istio Traffic Management](https://istio.io/latest/docs/tasks/traffic-management/), [Linkerd Traffic Management](https://linkerd.io/docs/features/gateway-api/).
