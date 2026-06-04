# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — набор техник для контроля потоков запросов (трафика) между сервисами на уровне L7. В контексте [Service Mesh](./service_mesh_concepts.md) эти техники реализуются в прокси-сайдкарах и управляются декларативно через API плоскости управления (Control Plane), что позволяет изменять сетевое поведение без вмешательства в код приложений.

**Ключевое изменение:** Gateway API (General Availability) стал предпочтительным способом конфигурации в Istio вместо VirtualService и DestinationRule. Традиционные ресурсы (Legacy API) сохраняются для обратной совместимости.

---

## Основные концепции

### Ключевые задачи

| Задача | Описание | Примеры использования |
| :--- | :--- | :--- |
| **Динамическая маршрутизация** | Направление запросов на основе атрибутов (хост, путь, заголовки, cookie). | Canary, blue-green, A/B-тестирование. |
| **Сегментация по версиям** | Изоляция трафика для разных версий сервиса (например, `v1`, `v2`) с помощью подмножеств (subsets). | Постепенное развертывание (rollout) новых версий. |
| **Отказоустойчивость** | Повышение надежности системы за счет таймаутов, повторных попыток (retries), разрыва цепи (circuit breaking). | Защита от каскадных сбоев. |
| **Тестирование и эксперименты** | Зеркалирование трафика (shadowing/mirroring), внедрение ошибок (fault injection). | Тестирование под нагрузкой, Chaos Engineering. |

### Сравнение примитивов управления: Istio и Linkerd

| Примитив | Istio (Gateway API) | Istio (Legacy API) | Linkerd |
| :--- | :--- | :--- | :--- |
| **Взвешенная маршрутизация** | `HTTPRoute` + `weight` | `VirtualService` + `DestinationRule` | `TrafficSplit` (SMI) |
| **Ретраи и таймауты** | `HTTPRoute.rules.retries` | `VirtualService` | `ServiceProfile` |
| **Circuit breaking** | `DestinationRule` | `DestinationRule` | Ограниченно, на уровне прокси |
| **Маршрутизация по заголовкам** | `HTTPRoute.matches.headers` | `VirtualService` (секция `match`) | Нативно не поддерживается |
| **Зеркалирование** | `HTTPRoute.rules.mirrors` | `VirtualService` (секция `mirror`) | Нативно не поддерживается |
| **Fault injection** | Через политики авторизации | `VirtualService` (секция `fault`) | Через аннотации инъекции |

**Рекомендация:** Для новых развертываний Istio используйте **Gateway API**. Legacy API (`VirtualService`/`DestinationRule`) — только для поддержки существующих систем.

---

## Практические сценарии

### Сценарий 1: Канареечное развертывание в Istio (Gateway API)

Направить 10% трафика на новую версию `v2` сервиса `api`, а 90% — на стабильную `v1`.

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

Проверка применения маршрута:

```bash
istioctl proxy-config route deploy/api-v1 -n default
# → NAME         VHOST NAME                               DOMAINS                              MATCH                  VIRTUAL SERVICE
# → 8080         api.default.svc.cluster.local:8080        api.default.svc.cluster.local        /*                     api-canary.default
```

### Сценарий 2: Зеркалирование трафика (Istio Gateway API)

Дублирование 10% реального трафика на тестовую версию `v2` без влияния на пользователя.

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

### Сценарий 3: Настройка повторных попыток и таймаутов в Linkerd

Определение параметров устойчивости для GET-запросов.

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

### Сценарий 4: Circuit Breaking (Istio DestinationRule)

Защита сервиса от перегрузки и изоляция неисправных эндпоинтов (Outlier Detection).

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

### Ключевые ресурсы Gateway API

| Ресурс | Назначение |
| :--- | :--- |
| **`GatewayClass`** | Шаблон для создания шлюзов (например, `istio`, `istio-waypoint`). |
| **`Gateway`** | Точка входа трафика (Ingress) или Waypoint Proxy (внутренний трафик). |
| **`HTTPRoute`** | Правила маршрутизации L7 (пути, заголовки, фильтры). |
| **`ReferenceGrant`** | Разрешение на перекрестные ссылки между неймспейсами (Namespace). |

### Лучшие практики

1. **Приоритет Gateway API:** Используйте современный стандарт для всех новых конфигураций.
2. **Ambient Mesh:** Рассмотрите для снижения потребления ресурсов (до 50%) в масштабных кластерах.
3. **Обязательные таймауты:** Всегда устанавливайте лимиты времени ожидания для предотвращения зависания ресурсов.
4. **Идемпотентные ретраи:** Настраивайте повторные попытки только для безопасных методов (GET, HEAD).
5. **Тестирование зеркалированием:** Проверяйте производительность новых версий на реальном трафике перед переключением.

### Актуальность

- **Istio 1.29+:** Gateway API в статусе GA, полная поддержка Ambient Mesh.
- **Kubernetes 1.30+:** Широкое внедрение Gateway API как замены стандартному Ingress.
- **Linkerd 2.x:** Продолжает использовать SMI (Service Mesh Interface) для управления трафиком.

Документация: [Istio Traffic Management](https://istio.io/latest/docs/tasks/traffic-management/), [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/). Связанные темы: [Архитектура Istio](./istio_architecture.md), [Сравнение Mesh-платформ](./istio_vs_linkerd.md).
