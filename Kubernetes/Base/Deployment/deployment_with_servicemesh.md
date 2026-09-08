# Deployment с Service Mesh

Интеграция Kubernetes Deployment с Service Mesh: управление трафиком при rollout, circuit breaking для защиты и безопасное обновление через Gateway API.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes с установленным Service Mesh (Istio/Linkerd).
- Установленный `kubectl` с доступом к кластеру.
- Базовое понимание [Deployment](./index.md).

## 1. Определения

**Service Mesh** — инфраструктурный слой, обеспечивающий управление трафиком, безопасность (mTLS) и наблюдаемость между микросервисами без изменения кода приложения.

> Общая архитектура Service Mesh, comparison Istio/Linkerd/Cilium, traffic management и mTLS см. в [Service Mesh концепции](../../../Service_Mesh/service_mesh_concepts.md), [Traffic Management](../../../Service_Mesh/traffic_management.md), [Istio Architecture](../../../Service_Mesh/istio_architecture.md) и [Istio Security](../../../Service_Mesh/istio-security-policies.md).

## 2. Базовые концепции

### Deployment + Service Mesh: что меняется

| Аспект | Без Service Mesh | С Service Mesh |
|:-------|:-----------------|:---------------|
| **Маршрутизация** | Service (ClusterIP) + kube-proxy | Gateway API / VirtualService |
| **Canary** | Два Deployment + Service с весами | Один Rollout + Gateway API weights |
| **Circuit Breaking** | В коде приложения | DestinationRule |
| **mTLS** | Ручная настройка сертификатов | PeerAuthentication (автоматически) |
| **Observability** | Метрики в коде | Автоматические метрики от sidecar |

### Gateway API vs VirtualService (2026)

| Аспект | Gateway API (рекомендуется) | Istio VirtualService (legacy) |
|:-------|:---------------------------|:------------------------------|
| **Статус** | GA, стандарт K8s | Istio CRD, deprecated для новых проектов |
| **Роутинг** | HTTPRoute с weighted backendRefs | HTTPRoute с weighted subsets |
| **Canary** | Нативная поддержка весов | Через subsets + DestinationRule |
| **Рекомендация** | Использовать для новых проектов | Только для существующих конфигураций |

## 3. Практические сценарии

### Canary Deployment через Gateway API

```yaml
# Основной сервис (90% трафика)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-route
  namespace: production
spec:
  parentRefs:
  - name: production-gateway
    namespace: istio-system
  hostnames:
  - "my-app.example.com"
  rules:
  - backendRefs:
    - name: my-app-stable
      port: 8080
      weight: 90
    - name: my-app-canary
      port: 8080
      weight: 10
---
# Стабильная версия
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-stable
spec:
  replicas: 9
  selector:
    matchLabels:
      app: my-app
      version: v1
  template:
    metadata:
      labels:
        app: my-app
        version: v1
    spec:
      containers:
      - name: app
        image: my-registry.com/app:v1
---
# Канареечная версия
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app-canary
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-app
      version: v2
  template:
    metadata:
      labels:
        app: my-app
        version: v2
    spec:
      containers:
      - name: app
        image: my-registry.com/app:v2
```

### Retry Policy через Gateway API

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: BackendTrafficPolicy
metadata:
  name: my-app-traffic-policy
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Service
    name: my-app
  retry:
    numAttempts: 3
    retryOn:
      httpStatusCodes:
      - 503
      - 504
  timeouts:
  - type: Request
    value: 10s
```

### Traffic Mirroring (Shadow Deployment)

```yaml
# Зеркалирование трафика на тестовый сервис
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-mirror
spec:
  parentRefs:
  - name: production-gateway
  hostnames:
  - "my-app.example.com"
  rules:
  - backendRefs:
    - name: my-app-stable
      port: 8080
    filters:
    - type: RequestMirror
      requestMirror:
        backendRef:
          name: my-app-shadow
          port: 8080
        percent: 10
```

### Locality-aware Load Balancing

```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: my-app-locality
spec:
  host: my-app.production.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      localityLbSetting:
        enabled: true
        distribute:
        - from: "us-east-1/us-east-1a/*"
          to:
            "us-east-1/us-east-1a/*": 80
            "us-east-1/us-east-1b/*": 15
            "us-west-2/us-west-2a/*": 5
      failover:
      - from: us-east-1
        to: us-west-2
```

### Диагностика Service Mesh

```bash
# Проверка статуса Istio
istioctl analyze -n production

# Проверка подов с sidecar
kubectl get pods -n production -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].name}{"\n"}{end}' | grep istio-proxy

# Проверка маршрутизации
istioctl proxy-config routes <pod-name>

# Проверка circuit breaker
istioctl proxy-config listeners <pod-name>

# Проверка mTLS
istioctl x describe traffic <pod-name> <service-name>

# Логи Envoy
kubectl logs <pod-name> -c istio-proxy --tail=100
```

## 4. Дополнительная информация

### См. также
- [Service Mesh концепции](../../../Service_Mesh/service_mesh_concepts.md) — архитектура и компоненты.
- [Traffic Management](../../../Service_Mesh/traffic_management.md) — управление трафиком (188 строк).
- [Istio Architecture](../../../Service_Mesh/istio_architecture.md) — архитектура Istio (174 строки).
- [Istio Security](../../../Service_Mesh/istio-security-policies.md) — mTLS и авторизация (160 строк).
- [Gateway API](../../../Kubernetes/Networking/gateway_api/routing_features.md) — routing features (480 строк).
- [Progressive Delivery](./progressive_delivery.md) — Argo Rollouts, Flagger.
- [Deployment с GitOps](./deployment_with_gitops.md) — ArgoCD, Flux.
