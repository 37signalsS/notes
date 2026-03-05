# Kubernetes Gateway API — Расширенные функции маршрутизации

## Расширенные возможности маршрутизации (Standard Features)

Главное преимущество Gateway API перед Ingress — стандартизация продвинутых правил маршрутизации. Вместо нестандартных аннотаций используются фильтры (`filters`) в `HTTPRoute`.

### Request Redirect

Позволяет перенаправлять запросы на уровне прокси.

**HTTP на HTTPS Redirect:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-to-https
spec:
  hostnames:
  - "test.krukov.local"
  parentRefs:
  - name: my-gateway
    sectionName: http # Привязка к HTTP listener
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301 # Permanent Redirect
```

**Path Redirect (Редирект по пути):**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-path
spec:
  parentRefs:
  - name: my-gateway
    sectionName: https # Работает на HTTPS
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /login
    filters:
    - type: RequestRedirect
      requestRedirect:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /auth
        statusCode: 302 # Temporary Redirect
```

### URL Rewrite

В отличие от редиректа, перезапись URL происходит на стороне прокси без ответа клиенту. Клиент не видит изменения.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: rewrite-url
spec:
  parentRefs:
  - name: my-gateway
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /login
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /auth # Запрос /login/user1 станет /auth/user1
    backendRefs:
    - name: auth-service
      port: 80
```

- `replacePrefixMatch`: заменяет только совпавшую часть пути.
- `replaceFullPath`: заменяет весь путь целиком.
- Также можно изменить `hostname`.

### Header Modification

Позволяет добавлять, изменять или удалять заголовки запросов и ответов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: modify-headers
spec:
  parentRefs:
  - name: my-gateway
  rules:
  - filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add: # Добавить заголовок
        - name: "X-Request-Test"
          value: "true"
        remove: # Удалить заголовок
        - "X-Internal-Header"
    - type: ResponseHeaderModifier
      responseHeaderModifier:
        add:
        - name: "X-Response-Test"
          value: "true"
    backendRefs:
    - name: my-app-service
      port: 80
```

### Traffic Splitting (Разделение трафика)

**Canary Deployment (Канареечное развертывание):**
Направление трафика на новую версию приложения на основе определенных критериев, например, HTTP-заголовка. Идеально для внутреннего тестирования.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: canary-test
spec:
  parentRefs:
  - name: my-gateway
  rules:
  - matches: # Правило для тестировщиков
    - headers:
      - type: Exact
        name: "app-version"
        value: "new"
    backendRefs: # Направляем на новую версию
    - name: my-app-v2
      port: 80
  - backendRefs: # Правило по умолчанию для всех остальных
    - name: my-app-v1
      port: 80
```

**Blue/Green Deployment (Взвешенное разделение):**
Процентное разделение трафика между двумя версиями приложения.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: blue-green-split
spec:
  parentRefs:
  - name: my-gateway
  rules:
  - backendRefs:
    - name: my-app-v1
      port: 80
      weight: 90 # 90% трафика на стабильную версию
    - name: my-app-v2
      port: 80
      weight: 10 # 10% трафика на новую версию
```

---

**См. также:**
- [Базовые сценарии](./practical_basic.md) — основы создания HTTPRoute
- [L4 маршрутизация](./layer4_routing.md) — TCPRoute, UDPRoute

**Parent:** [Gateway API](../gateway_api.md)
