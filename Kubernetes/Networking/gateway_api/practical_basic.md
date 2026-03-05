# Kubernetes Gateway API — Базовые сценарии

## Практические сценарии

### 1. Создание GatewayClass (администратором кластера)

Этот манифест определяет "класс" шлюзов, который будет управляться указанным контроллером.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: public-lb
spec:
  controllerName: "example.com/gateway-controller"
  description: "Шлюз для внешнего трафика"
```

### 2. Создание Gateway (оператором инфраструктуры)

На основе `GatewayClass` создается экземпляр шлюза, который будет слушать трафик на 80 порту. `allowedRoutes` указывает, что к этому шлюзу могут подключаться маршруты из любых пространств имен.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: web
  namespace: infra
spec:
  gatewayClassName: public-lb
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
```

### 3. Создание HTTPRoute (разработчиком)

Разработчик в своем `namespace: app` создает правило маршрутизации. Трафик для домена `app.example.com` привязывается к шлюзу `web` из `namespace: infra`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: frontend-route
  namespace: app
spec:
  parentRefs:
  - name: web
    namespace: infra
  hostnames: ["app.example.com"]
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    backendRefs:
    - name: backend-service
      port: 8080
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: frontend-service
      port: 80
```

### Что происходит после применения манифестов

1. **Контроллер Gateway API** (например, реализация от NGINX или Cilium) обнаруживает `Gateway` и разворачивает соответствующую инфраструктуру (например, Load Balancer) с публичным IP-адресом.
2. **Трафик**, поступающий на этот IP-адрес для хоста `app.example.com`, направляется на шлюз.
3. **Шлюз** анализирует `HTTPRoute`, привязанный к нему.
4. Запросы с путем, начинающимся на `/api`, маршрутизируются к `backend-service`.
5. Весь остальной трафик для этого хоста направляется к `frontend-service`.
6. Политики `allowedRoutes` и `parentRefs` обеспечивают безопасное взаимодействие между пространствами имен, предотвращая конфликты между командами.

---

**См. также:**
- [Определения](./definitions.md) — концепции и ролевая модель
- [Ресурсы](./resources.md) — описание CRD
- [Расширенные функции](./routing_features.md) — Redirect, Rewrite, Traffic Splitting
- [Traefik как реализация](./traefik.md) — пример с конкретным контроллером

**Parent:** [Gateway API](../gateway_api.md)
