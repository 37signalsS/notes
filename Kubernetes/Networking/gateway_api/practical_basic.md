# Gateway API — базовые сценарии

**Надёжность:** 10 (SSoT + Практический опыт эксплуатации v1.5+)

## Определения

**Gateway API** — современный стандарт управления трафиком в Kubernetes. Он предоставляет типобезопасный и ролевой интерфейс для настройки балансировщиков нагрузки. Основные концепции описаны в [Определениях](./definitions.md).

**HTTPRoute** — основной ресурс разработчика для описания правил маршрутизации HTTP-трафика (хосты, пути, фильтры).

## Базовые концепции

### Цепочка взаимодействия ресурсов

Публикация приложения в 2026 году (после EOL Ingress-NGINX) требует настройки трёх уровней абстракции:

1. **GatewayClass** (Инфраструктура) — выбор реализации (Envoy Gateway, Traefik, Cilium).
2. **Gateway** (Сеть) — конфигурация портов (80, 443) и привязка IP.
3. **HTTPRoute** (Приложение) — логика распределения запросов по сервисам.

Детальное описание полей каждого ресурса приведено в разделе [Ресурсы (CRD)](./resources.md).

## Практические сценарии

### Шаг 1: Определение класса шлюза (GatewayClass)

Создаётся администратором кластера один раз для всей инфраструктуры.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: external-envoy
spec:
  controllerName: "gateway.envoyproxy.io/gatewayclass-controller"
  description: "Стандартный внешний балансировщик на базе Envoy"
```

### Шаг 2: Настройка шлюза (Gateway)

Оператор инфраструктуры создаёт шлюз в системном пространстве имён (`infra-ns`).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: infra-ns
spec:
  gatewayClassName: external-envoy
  listeners:
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All # Разрешает маршруты из любых пространств имён
```

### Шаг 3: Безопасное подключение маршрута (ReferenceGrant)

Если сервис находится в другом пространстве имён, чем шлюз, необходимо разрешить шлюзу "видеть" бэкенды. Это критическое отличие от Ingress, повышающее безопасность.

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-infra-gateway
  namespace: app-prod
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    namespace: app-prod
  to:
  - group: ""
    kind: Service
```

### Шаг 4: Описание маршрутов приложения (HTTPRoute)

Разработчик разворачивает правила в своём пространстве имён.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web-api-route
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1 }
    backendRefs:
    - name: api-v1-service
      port: 8080
  - matches:
    - path: { type: PathPrefix, value: / }
    backendRefs:
    - name: frontend-service
      port: 80
```

## Механизм обработки трафика

После применения манифестов:
1. **Контроллер** (например, Envoy Gateway) динамически выделяет внешний IP через облачного провайдера или MetalLB.
2. **Запрос** (`api.example.com/v1/users`) попадает на балансировщик.
3. **Gateway** находит слушателя на порту 80 и проверяет права `HTTPRoute` в неймспейсе `app-prod`.
4. **HTTPRoute** сопоставляет путь `/v1` и направляет трафик напрямую на поды сервиса `api-v1-service`.

## Дополнительная информация

**Преимущества базового сценария:**
- **Разделение прав:** Разработчик не может случайно изменить порты или TLS шлюза.
- **Безопасность:** Кросс-неймспейс ссылки работают только при наличии `ReferenceGrant`.
- **Прозрачность:** Статус применения конфигурации виден напрямую в ресурсе (`kubectl describe httproute`).

**См. также:**
- [Определения](./definitions.md) — концепции и ролевая модель.
- [Ресурсы (CRD)](./resources.md) — глубокое описание объектов.
- [Миграция с Ingress](./migration.md) — как перенести старые правила.
- [Расширенная маршрутизация](./routing_features.md) — редиректы и разделение трафика (Canary).

**Родительская тема:** [Gateway API](./definitions.md)
