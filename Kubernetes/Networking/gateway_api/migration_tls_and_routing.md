# Миграция TLS и маршрутизации на Gateway API

## Определения

**TLS Termination** — терминирование TLS на шлюзе (Gateway). Шлюз расшифровывает трафик и передаёт его на бэкенд в открытом виде.

**TLS Passthrough** — сквозное шифрование. Трафик передаётся на бэкенд без расшифровки на шлюзе. Маршрутизация возможна только по SNI (имени хоста).

**TLSRoute** — ресурс Gateway API для маршрутизации TLS-трафика (статус: `v1alpha2`, Alpha). Используется для сценариев Passthrough.

## Базовые концепции

### Сценарий 1: TLS Termination

Если в Ingress используется обычное TLS с Secret (терминирование на контроллере):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: infra
spec:
  gatewayClassName: external-lb
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls-secret
        namespace: my-app
    allowedRoutes:
      namespaces:
        from: All
```

**Преимущество:** Secret может находиться в другом namespace (не в namespace приложения).

### Сценарий 2: SSL Passthrough

Если в Ingress используется `ssl-passthrough: "true"` (сквозное шифрование):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: passthrough-gateway
  namespace: infra
spec:
  gatewayClassName: external-lb
  listeners:
  - name: tls-passthrough
    protocol: TLS
    port: 443
    tls:
      mode: Passthrough
    allowedRoutes:
      namespaces:
        from: All
---
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: app-tls-route
  namespace: my-app
spec:
  parentRefs:
  - name: passthrough-gateway
    sectionName: tls-passthrough
  hostnames:
  - app.example.com
  rules:
  - backendRefs:
    - name: app-service
      port:
        number: 443
```

**Важно:** При использовании TLSRoute маршрутизация возможна **только по SNI** (имени хоста). Маршрутизация по пути, заголовкам или методам HTTP недоступна, так как контроллер не видит содержимое запроса.

### Сценарий 3: Смешанный режим

Если для одного хоста одновременно используются passthrough и HTTP-маршрутизация — архитектуру необходимо пересмотреть:

- Разделить хосты: passthrough для одних доменов, termination для других
- Использовать разные Gateway с разными listener
- Рассмотреть возможность терминирования на бэкенде с re-encrypt

## Практические сценарии

### Пример ручной миграции с Ingress

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-ingress
  namespace: my-app
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$1
spec:
  ingressClassName: nginx
  rules:
  - host: "app.example.com"
    http:
      paths:
      - path: /api/(.*)
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 8080
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend-service
            port:
              number: 80
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-secret
```

**Эквивалент на Gateway API — HTTPRoute для маршрутизации:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-route
  namespace: my-app
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /
    backendRefs:
    - name: api-service
      port:
        number: 8080
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: frontend-service
      port:
        number: 80
```

**HTTPRoute для HTTPS redirect:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-to-https
  namespace: my-app
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
    sectionName: http
  hostnames:
  - "app.example.com"
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

### Типичные проблемы при миграции

| Проблема | Решение |
| :--- | :--- |
| Аннотации не конвертировались | Проверить документацию ingress2gateway, перевести вручную на filters |
| TLS не работает | Убедиться, что Secret доступен в namespace Gateway или использовать `certificateRefs` |
| Маршруты не привязываются к Gateway | Проверить `allowedRoutes` в Gateway и `parentRefs` в HTTPRoute |
| Разные namespace для Gateway и Route | Убедиться, что Gateway разрешает routes из других namespace (`from: All`) |

## Дополнительная информация

Концепции Gateway API: [Определения](./definitions.md).

Основы миграции: [Миграция с Ingress](./migration.md).

Ресурсы (CRD): [Ресурсы](./resources.md).
