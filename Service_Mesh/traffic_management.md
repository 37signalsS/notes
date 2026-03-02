# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор техник для контроля потоков запросов (трафика) между сервисами на уровне L7. В контексте [Service Mesh](./service_mesh_concepts.md) эти техники реализуются в прокси-сайдкарах и управляются декларативно через API плоскости управления, что позволяет изменять сетевое поведение без вмешательства в код приложений.

**Ключевое изменение (2025–2026):** Gateway API стал предпочтительным способом конфигурации в Istio (вместо VirtualService/DestinationRule). VirtualService и DestinationRule остаются для обратной совместимости (legacy).

---

## Основные концепции

### Ключевые задачи

| Задача | Описание | Примеры использования |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Направление запросов на основе атрибутов (хост, путь, заголовки, cookie). | Canary, blue-green, A/B-тестирование. |
| **Сегментация по версиям** | Изоляция трафика для разных версий сервиса (например, `v1`, `v2`) с помощью подмножеств (subsets). | Постепенный rollout новых версий. |
| **Отказоустойчивость** | Повышение надежности системы за счет таймаутов, ретраев, circuit breaking, outlier detection. | Защита от каскадных сбоев. |
| **Тестирование и эксперименты** | Зеркалирование трафика (shadowing/mirroring), fault injection. | Тестирование под нагрузкой, chaos engineering. |

### Сравнение примитивов: Istio vs Linkerd

| Примитив | Istio (Gateway API) | Istio (Legacy) | Linkerd |
| :--- | :--- | :--- | :--- |
| **Взвешенная маршрутизация** | `HTTPRoute` + `BackendRef.weight` | `VirtualService` + `DestinationRule` | `TrafficSplit` (SMI) |
| **Ретраи/таймауты** | `HTTPRoute.rules.retries`, `timeouts` | `VirtualService` | `ServiceProfile` |
| **Circuit breaking** | `DestinationRule` (outlierDetection) | `DestinationRule` | Ограниченно, на уровне прокси |
| **Маршрутизация по заголовкам** | `HTTPRoute.matches.headers` | `VirtualService` (секция `match`) | Нативно не поддерживается |
| **Зеркалирование** | `HTTPRoute.rules.mirrors` | `VirtualService` (секция `mirror`) | Нативно не поддерживается |
| **Fault injection** | Через `RequestAuthentication` + кастомные политики | `VirtualService` (секция `fault`) | Через `linkerd inject` + annotations |

**Рекомендация:** Для новых развертываний Istio используйте **Gateway API**. Legacy API (`VirtualService`/`DestinationRule`) — только для миграции или обратной совместимости.

---

## Практические сценарии

### Сценарий 1: Канареечное развертывание в Istio (Gateway API)

Направить 10% трафика на новую версию `v2` сервиса `api`, а 90% — на стабильную `v1`. Дополнительно для всех запросов установить таймаут в 2 секунды и 3 попытки ретрая в случае сбоев.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: default
spec:
  parentRefs:
  - name: istio-waypoint  # Waypoint Proxy для L7-политик (Ambient)
    namespace: default
  hostnames:
  - "api.default.svc.cluster.local"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    timeouts:
      request: 2s
    retries:
      attempts: 3
      perTryTimeout: 1s
    backendRefs:
    - name: api-v1
      port: 8080
      weight: 90
    - name: api-v2
      port: 8080
      weight: 10
```

**Для Sidecar-модели:** Замените `parentRefs` на ссылку на `Service`:
```yaml
  parentRefs:
  - name: api
    kind: Service
    port: 8080
```

### Сценарий 2: Канареечное развертывание в Istio (Legacy API)

> **Примечание:** Legacy API, используйте только для миграции.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api
  namespace: default
spec:
  hosts:
  - "api.default.svc.cluster.local"
  http:
  - route:
    - destination:
        host: api
        subset: v1
      weight: 90
    - destination:
        host: api
        subset: v2
      weight: 10
    timeout: 2s
    retries:
      attempts: 3
      perTryTimeout: 1s
      retryOn: 5xx,connect-failure,refused-stream
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api
  namespace: default
spec:
  host: api
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
```

### Сценарий 3: Зеркалирование трафика в Istio (Gateway API)

Отправлять 100% реального трафика на `v1`, а 10% этого трафика незаметно для пользователя дублировать на `v2` для тестирования под нагрузкой.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-mirror
  namespace: default
spec:
  parentRefs:
  - name: api
    kind: Service
    port: 8080
  rules:
  - backendRefs:
    - name: api-v1
      port: 8080
    mirrors:
    - name: api-v2
      port: 8080
    mirrorPercentage:
      value: 10.0
```

### Сценарий 4: Зеркалирование трафика в Istio (Legacy API)

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-mirror
  namespace: default
spec:
  hosts:
  - "api"
  http:
  - route:
    - destination:
        host: api
        subset: v1
    mirror:
      host: api
      subset: v2
    mirrorPercentage:
      value: 10.0
```

### Сценарий 5: Настройка ретраев и таймаутов в Linkerd

Для сервиса `api` определить, что GET-запросы к `/api/v1` можно повторять в случае сбоя, и установить для них таймаут в 2 секунды.

```yaml
apiVersion: linkerd.io/v1alpha2
kind: ServiceProfile
metadata:
  name: api.default.svc.cluster.local
  namespace: default
spec:
  routes:
  - name: GET /api/v1
    condition:
      method: GET
      pathRegex: /api/v1
    isRetryable: true
    timeout: 2s
```

### Сценарий 6: Маршрутизация по заголовкам (Istio, Gateway API)

Направлять трафик с заголовком `x-version: beta` на версию `v2`, остальной — на `v1`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-header-routing
  namespace: default
spec:
  parentRefs:
  - name: api
    kind: Service
    port: 8080
  rules:
  - matches:
    - headers:
      - name: x-version
        value: beta
    backendRefs:
    - name: api-v2
      port: 8080
  - backendRefs:
    - name: api-v1
      port: 8080
```

### Сценарий 7: Circuit Breaking (Istio, DestinationRule)

Ограничить количество подключений к сервису `api` для защиты от перегрузки.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api-circuit-breaker
  namespace: default
spec:
  host: api
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        h2UpgradePolicy: UPGRADE
        http1MaxPendingRequests: 50
        http2MaxRequests: 1000
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```

---

## Дополнительная информация

### Gateway API: ключевые ресурсы

| Ресурс | Назначение | Пример |
| :--- | :--- | :--- |
| **`GatewayClass`** | Определение типа шлюза (например, `istio`, `istio-waypoint`). | `istio-waypoint` для Ambient L7. |
| **`Gateway`** | Точка входа трафика (north-south) или Waypoint Proxy (east-west). | Ingress Gateway, Waypoint Proxy. |
| **`HTTPRoute`** | Правила маршрутизации L7 (хост, путь, заголовки). | Canary, A/B-тестирование, зеркалирование. |
| **`TCPRoute`**, **`TLSRoute`**, **`GRPCRoute`** | Маршрутизация для других протоколов. | Базы данных, gRPC-сервисы. |
| **`ReferenceGrant`** | Разрешение ссылок между неймспейсами. | Безопасный cross-namespace routing. |

### Best Practices (2025–2026)

1.  **Используйте Gateway API для новых развертываний.** VirtualService/DestinationRule — только для миграции.
2.  **Ambient Mesh для массовых развертываний.** Снижает оверхед на 30–50%.
3.  **Таймауты и ретраи — обязательно.** Защищают от каскадных сбоев.
4.  **Circuit breaking для критичных сервисов.** Предотвращает перегрузку.
5.  **Зеркалирование для тестирования.** Безопасное тестирование под нагрузкой.
6.  **Версионирование через labels.** `version: v1`, `version: v2` для четкой сегментации.

### Актуальность (2025–2026)

- **Istio 1.29:** Gateway API GA, Ambient Mesh production-ready.
- **Kubernetes 1.31–1.35:** Полная поддержка Gateway API.
- **Linkerd 2.x:** SMI TrafficSplit остается основным способом маршрутизации.

**Источники:**
- [Istio Gateway API Documentation](https://istio.io/latest/docs/tasks/traffic-management/gateway-api/)
- [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)
- [Istio 1.29 Release Notes](https://istio.io/latest/news/releases/1.29.x/announcing-1.29/)

### Связанные документы

- **Архитектура:** [Istio Architecture](./istio_architecture.md)
- **Концепции:** [Service Mesh Concepts](./service_mesh_concepts.md)
- **Сравнение:** [Istio vs Linkerd](./istio_vs_linkerd.md)
- **Proxy:** [Proxy Sidecar](./proxy_sidecar.md)
