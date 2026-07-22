# Traefik — реализация Gateway API

**Надёжность:** 10 (SSoT + Официальная документация Traefik v3.x)

## Определения

**Traefik (v3.1+)** — современный обратный прокси-сервер и балансировщик нагрузки с открытым исходным кодом, обеспечивающий полную поддержку спецификации Kubernetes Gateway API (v1.1+).

**Kubernetes Gateway Provider** — встроенный в Traefik компонент, который отслеживает ресурсы Gateway API и динамически настраивает правила маршрутизации. Traefik обеспечивает 100% соответствие (conformance) основным профилям спецификации (HTTP, TLS, gRPC).

## Базовые концепции

### Особенности реализации

- **Контроллер следующего поколения:** Начиная с версии 3.0, Traefik полностью переработан для нативной поддержки Gateway API, сохраняя при этом обратную совместимость с Ingress.
- **Direct Pod Targeting:** Traefik направляет трафик напрямую на IP-адреса подов (Endpoints), минуя `kube-proxy` и виртуальные IP сервисов, что минимизирует задержки.
- **Middleware через ExtensionRef:** Позволяет подключать богатую экосистему Middleware (RateLimit, BasicAuth, и др.) напрямую к ресурсам `HTTPRoute`.
- **Поддержка GAMMA:** Возможность использования Gateway API для управления трафиком внутри кластера (Service Mesh), используя `Service` в качестве `parentRef`.

### Установка и активация

Для работы необходимо предварительно установить CRD Gateway API (версии v1.1.0+ для поддержки всех функций v3.x).

В конфигурации Traefik (Helm `values.yaml`) необходимо включить провайдер:

```yaml
providers:
  kubernetesGateway:
    enabled: true  # Активация поддержки Gateway API
    experimentalChannel: true # Рекомендуется для TCP/UDP и GRPCRoute
```

## Практические сценарии

### Настройка инфраструктуры (GatewayClass и Gateway)

`GatewayClass` определяет Traefik как контроллер, а `Gateway` задаёт точки входа (порты).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: traefik
spec:
  controllerName: traefik.io/gateway-controller
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: main-gateway
  namespace: traefik
spec:
  gatewayClassName: traefik
  listeners:
  - name: web
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
  - name: websecure
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: site-tls
        namespace: traefik
```

### Расширенная маршрутизация (HTTPRoute)

`HTTPRoute` позволяет настраивать правила на основе путей, заголовков и применять Middleware.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: app-space
spec:
  parentRefs:
  - name: main-gateway
    namespace: traefik
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    filters:
    - type: ExtensionRef
      extensionRef:
        group: traefik.io
        kind: Middleware
        name: my-ratelimit
    backendRefs:
    - name: api-service
      port: 8080
```

### Безопасность и ReferenceGrant

Для того чтобы Traefik мог использовать TLS-секрет или Middleware из другого пространства имён, необходимо создать `ReferenceGrant`.

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-traefik-secrets
  namespace: cert-namespace
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: traefik
  to:
  - group: ""
    kind: Secret
```

### Поддержка L4 и gRPC

Traefik v3 поддерживает расширенные протоколы через Gateway API:

- **TCPRoute / UDPRoute:** Маршрутизация на уровне портов.
- **GRPCRoute:** Нативная поддержка gRPC с возможностью маршрутизации на уровне методов (необходим `experimentalChannel: true`).

## Дополнительная информация

### Преимущества Traefik v3

1. **Производительность:** Оптимизированное использование памяти и ресурсов процессора по сравнению с версией v2.x.
2. **Унификация:** Один контроллер для Ingress, Gateway API и Service Mesh (GAMMA).
3. **Нативность:** Отказ от избыточных аннотаций в пользу стандартных фильтров Gateway API.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация Gateway API
- [Интеграция с cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — автоматизация TLS

**Родительская тема:** [Gateway API](./definitions.md)
