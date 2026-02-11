# Трафик-менеджмент в Service Mesh

Трафик-менеджмент в сервис-мэше — это управляемая на уровне L7 маршрутизация и устойчивость запросов между микросервисами без изменений в коде приложений. Политики задаются декларативно и применяются консистентно ко всем экземплярам через прокси sidecar.

## Задачи трафик-менеджмента

-   **L7-маршрутизация**: по хосту, пути, HTTP-методу, заголовкам, cookie; взвешенное распределение и канареечные релизы.
-   **Сегментация версий**: маршрутизация на подмножества (subsets) по меткам версий.
-   **Устойчивость**: таймауты, ретраи с политиками, circuit breaking и выведение неустойчивых инстансов (outlier detection), лимиты соединений и очередей, алгоритмы балансировки.
-   **Наблюдаемость**: единообразные метрики и трейсинг на уровне маршрутов.
-   **Эксперименты**: зеркалирование (shadow traffic), инъекция задержек/ошибок для проверки устойчивости.

## Istio: ключевые объекты

В Istio за маршрутизацию отвечает VirtualService, а за политику к целям — DestinationRule. Типичный сценарий: направлять 100% трафика с заголовком user-group=beta на v2, остальное распределять 90/10 между v1 и v2; добавить таймауты, ретраи и защиту от нестабильных инстансов.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api
spec:
  hosts: [api.default.svc.cluster.local]
  http:
  - match:
    - headers:
        user-group:
          exact: beta
    route:
    - destination: { host: api, subset: v2 }
      weight: 100
  - route:
    - destination: { host: api, subset: v1 }
      weight: 90
    - destination: { host: api, subset: v2 }
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
spec:
  host: api
  subsets:
  - name: v1
    labels: { version: v1 }
  - name: v2
    labels: { version: v2 }
  trafficPolicy:
    loadBalancer: { simple: LEAST_CONN }
    connectionPool:
      http: { http1MaxPendingRequests: 100, maxRequestsPerConnection: 100 }
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 5s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```

Для исследований можно использовать зеркалирование части трафика на v2, не влияя на ответы пользователю:

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-mirror
spec:
  hosts: [api]
  http:
  - route:
    - destination: { host: api, subset: v1 }
    mirror: { host: api, subset: v2 }
    mirrorPercentage: { value: 10.0 }
```

## Linkerd: эквиваленты и отличия

В Linkerd маршрутизация по весам выполняется через SMI-ресурс TrafficSplit; поведения по ретраям/таймаутам — через ServiceProfile. Маршруты описываются по пути/методу, без полнофункционального мэчинга по заголовкам.

```yaml
apiVersion: split.smi-spec.io/v1alpha2
kind: TrafficSplit
metadata:
  name: api
spec:
  service: api
  backends:
  - service: api-v1
    weight: 90
  - service: api-v2
    weight: 10
---
apiVersion: linkerd.io/v1alpha2
kind: ServiceProfile
metadata:
  name: api.default.svc.cluster.local
spec:
  routes:
  - name: GET /api
    condition:
      method: GET
      pathRegex: ^/api
    isRetryable: true
    timeout: 2s
    retries:
      retryBudget:
        retryRatio: 0.2
        minRetriesPerSecond: 10
```

## Сравнение примитивов

| Примитив | Istio | Linkerd |
| :--- | :--- | :--- |
| **Взвешенная маршрутизация** | VirtualService + subsets в DestinationRule | TrafficSplit (SMI) |
| **Ретраи/таймауты** | VirtualService и/или DestinationRule | ServiceProfile |
| **Circuit breaking / outliers** | DestinationRule.outlierDetection | Ограниченно на уровне прокси, без outlier detection |
| **Маршрутизация по заголовкам** | Полная поддержка match | Нет нативно, обычно через ingress |
| **Зеркалирование** | VirtualService.mirror | Нет нативно |
