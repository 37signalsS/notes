# Kubernetes Gateway API

## Определения

**Gateway API** — это новая стандартная спецификация с открытым исходным кодом для управления внешним доступом к сервисам в Kubernetes. Она представляет собой следующее поколение API для управления трафиком, приходя на смену Ingress. Ключевая особенность Gateway API — это более выразительный, расширяемый и ролевой подход к маршрутизации.

## Основные концепции

### Зачем нужен Gateway API?

Стандартный ресурс `Ingress` имеет ряд ограничений, которые Gateway API призван решить:

- **Разделение ответственности**: В Ingress инфраструктурные и прикладные настройки часто смешаны. Gateway API разделяет их: администраторы кластера управляют шлюзами (`Gateway`), а разработчики — правилами маршрутизации (`HTTPRoute`).
- **Единый стандарт**: Вместо множества специфичных аннотаций для каждого Ingress-контроллера, Gateway API предлагает унифицированные CRD (Custom Resource Definitions) для всех реализаций.
- **Расширенные функции**: Встроенная поддержка TLS, балансировки нагрузки, канареечных развертываний, зеркалирования трафика, взвешенного сплиттинга и многопротокольной маршрутизации (HTTP, HTTPS, gRPC, TCP/UDP).
- **Переносимость**: Единая конфигурация работает с различными нижележащими реализациями (Istio, Cilium, NGINX, GKE, и др.).

### Ключевые ресурсы (CRD)

Gateway API вводит ролевую модель, где разные роли взаимодействуют с разными ресурсами:

1. **`GatewayClass`** (Администратор кластера)
    - **Что это?** Шаблон для создания шлюзов. Определяет тип шлюза и контроллер, который будет его реализовывать. Аналогичен `IngressClass`.
    - **Кто создает?** Администратор кластера.

2. **`Gateway`** (Оператор инфраструктуры / Администратор пространства имен)
    - **Что это?** Реализация шлюза в конкретном `namespace`. Запрашивает IP-адрес и порты у `GatewayClass` и определяет, какие маршруты (`*Route`) могут к нему подключаться.
    - **Кто создает?** Оператор, ответственный за инфраструктуру пространства имен.

3. **`HTTPRoute`, `TCPRoute`, `GRPCRoute` и др.** (Разработчик)
    - **Что это?** Правила маршрутизации, которые привязываются к `Gateway`. Определяют, как направлять трафик к сервисам на основе хостов, путей, заголовков и т.д.
    - **Кто создает?** Разработчики приложений.

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

### Envoy Gateway

**Envoy Gateway** — официальная реализация Gateway API от проекта Envoy Proxy. В отличие от Traefik Proxy, Envoy Gateway работает по модели контроллера.

#### Архитектура

1. **Envoy Gateway Controller** — под в кластере, который:
   - Отслеживает манифесты Gateway API
   - Создает и управляет отдельными подами Envoy Proxy
   - На каждый `Gateway` создается отдельный экземпляр Envoy Proxy

2. **Envoy Proxy** — отдельные поды, обслуживающие конкретный Gateway:
   - По умолчанию создается Service типа LoadBalancer
   - Автоматически получает Endpoints из Service приложения
   - Может работать напрямую с подами или через Service

#### Установка

```bash
helm install eg envoy-gateway/envoy-gateway --version 1.3.1 -n envoy-gateway --create-namespace
```

#### Конфигурация EnvoyProxy

`EnvoyProxy` — CRD для динамической конфигурации Envoy Proxy. Позволяет настраивать логирование, телеметрию, провайдеров.

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: EnvoyProxy
metadata:
  name: my-proxy-config
  namespace: gateway-infra
spec:
  provider:
    type: Kubernetes
    kubernetes:
      kind: Service
  logging:
    level:
      default: warning
      proxy-logs:
        upstream: info
```

**Привязка к GatewayClass** — применяется ко всем Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: ig
spec:
  controllerName: gateway.envoyproxy.io/gateway-class-controller
  parametersRef:
    group: gateway.envoyproxy.io
    kind: EnvoyProxy
    name: my-proxy-config
    namespace: gateway-infra
```

**Привязка к конкретному Gateway** — применяется только к одному Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: ig
  # ...
```

#### Интеграция с cert-manager

Для выпуска сертификатов через Gateway API необходимо:

1. Установить cert-manager с поддержкой Gateway API:

```bash
helm install cert-manager jetstack/cert-manager \
  --set "extraArgs={--enable-gateway-api=true}" \
  -n cert-manager --create-namespace
```

**Важно:** CRD Gateway API должны быть установлены ДО cert-manager, иначе возникнет ошибка.

2. Создать Issuer/ClusterIssuer:

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca
  namespace: sample
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: sample-tls
  namespace: sample
spec:
  secretName: sample-tls
  issuerRef:
    name: selfsigned-ca
    kind: Issuer
  dnsNames:
  - sample.example.local
```

3. Ссылка на Secret в Gateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: ig
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: sample-tls
        namespace: sample
```

#### Особенности работы с HTTPS

При использовании `hostname` в Gateway и cert-manager возможны проблемы с генерацией сертификата. В некоторых случаях требуется:
- Удалить поле `hostname` из манифеста Gateway
- Создать Certificate вручную перед созданием Gateway
- Дождаться создания Secret и только затем применять Gateway

#### MetalLB интеграция

Для работы LoadBalancer сервисов необходим MetalLB в кластере:

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: default-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.218.180-192.168.218.185
```

## Дополнительная информация

* **Официальная документация:** [Gateway API](https://gateway-api.sigs.k8s.io/)
* **Официальная документация Envoy Gateway:** [envoyproxy.io](https://www.envoyproxy.io/docs/envoy/latest/api-docs/xds)
* **Обзор Ingress и его ограничений:** [Ingress: Будущее - Gateway API](./Ingress/future_gateway_api.md)
