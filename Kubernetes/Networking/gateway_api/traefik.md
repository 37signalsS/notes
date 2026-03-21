# Traefik как реализация Gateway API

## Traefik как реализация Gateway API

**Traefik** — один из популярных прокси-контроллеров, поддерживающий Gateway API. В отличие от Envoy Gateway, Traefik может работать как Ingress Controller или как Gateway API Controller.

### Установка Traefik с поддержкой Gateway API

```bash
# При установке через ArgoCD или Helm необходимо включить провайдер Gateway API:
# values.yaml
providers:
  kubernetesGateway:
    enabled: true  # Включить поддержку Gateway API
  ingressClass:
    enabled: false  # Отключить классический Ingress (опционально)
gateway:
  enabled: false  # Не создавать Gateway по умолчанию, создавать вручную
```

### Конфигурация GatewayClass (Traefik)

По умолчанию Traefik создает GatewayClass с именем `traefik`. При наличии нескольких контроллеров необходимо создавать отдельные GatewayClass для каждого.

### Конфигурация Gateway (Traefik)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: traefik-gateway
  namespace: sample
spec:
  gatewayClassName: traefik
  listeners:
  - name: web
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: Same  # Разрешить маршруты только из того же namespace
  - name: websecure
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: sample-tls
        namespace: sample  # Secret может быть в другом namespace!
```

**Особенности:**

- `hostname` в HTTP listener не обязателен, маршрутизация по hostname определяется в HTTPRoute
- `hostname` в HTTPS listener обязателен
- TLS mode `Terminate` — SSL-трафик терминируется на контроллере, далее передается по HTTP
- TLS mode `Passthrough` (или `Translate`) — SSL-трафик не расшифровывается, используется TLSRoute далее
- **Важно:** Secret с сертификатом может находиться в **другом namespace**, в отличие от Ingress, где Secret должен быть в том же namespace

### Конфигурация HTTPRoute (Traefik)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: sample-http
  namespace: sample
spec:
  parentRefs:
  - name: traefik-gateway
    sectionName: web  # Какой listener использовать
  hostnames:
  - sample.example.local
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: qmi
      port: 80
```

**Особенности:**

- HTTPRoute может находиться в **любом namespace**, не обязательно в namespace приложения
- HTTPRoute может ссылаться на Service в **любом namespace**
- Traefik по умолчанию отправляет трафик напрямую на pod endpoints, минуя Service (более эффективно)

---

**См. также:**

- [Определения](./definitions.md) — концепции Gateway API
- [Базовые сценарии](./practical_basic.md) — примеры
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация
- [cert-manager](../../ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) — интеграция с TLS

**Parent:** [Gateway API](../gateway_api/definitions.md)
