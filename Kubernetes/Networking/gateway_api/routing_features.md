# Расширенная маршрутизация в Gateway API

**Надёжность:** 10 (SSoT + Спецификация Gateway API v1.5/1.6)

## Определения

**Фильтр (Filter)** — стандартный механизм Gateway API для модификации запросов и ответов. Фильтры заменяют собой вендор-специфичные аннотации Ingress-контроллеров, обеспечивая переносимость конфигурации.

**Traffic Splitting** — распределение входящего трафика между несколькими сервисами (бэкендами) на основе весовых коэффициентов или условий (headers, cookies).

**CORS (Cross-Origin Resource Sharing)** — механизм безопасности, позволяющий веб-приложениям в браузере запрашивать ресурсы с другого домена. С версии v1.5 Gateway API поддерживает нативный CORS-фильтр.

## Базовые концепции

Стандартизация функций в Gateway API избавляет от необходимости использовать проприетарные аннотации (например, `nginx.ingress.kubernetes.io/rewrite-target`). Весь функционал описывается в блоке `spec.rules[].filters`.

### Основные типы фильтров (Standard Channel)

- `RequestHeaderModifier`: Добавление, изменение или удаление заголовков запроса.
- `ResponseHeaderModifier`: Модификация заголовков ответа.
- `RequestRedirect`: Управление перенаправлением (301/302).
- `URLRewrite`: Внутренняя перезапись путей и хостов.
- `RequestMirror`: Копирование трафика для тестирования (Traffic Shadowing).
- `CORS`: Нативная обработка префлайт-запросов и заголовков безопасности.

## Практические сценарии

### Настройка CORS (v1.5+)

Фильтр `CORS` позволяет шлюзу самостоятельно отвечать на запросы `OPTIONS`, не нагружая бэкенд.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-with-cors
spec:
  parentRefs:
  - name: external-gateway
  hostnames:
  - "api.example.com"
  rules:
  - filters:
    - type: CORS
      cors:
        allowOrigins:
        - "https://app.example.com"
        - "https://*.internal.net"
        allowMethods: [GET, POST, OPTIONS]
        allowHeaders: [Content-Type, Authorization]
        maxAge: 600
    backendRefs:
    - name: api-service
      port: 8080
```

### Перезапись URL (URL Rewrite)

Используется для адаптации внешних путей к внутренней структуре микросервисов.

```yaml
rules:
- matches:
  - path:
      type: PathPrefix
      value: /v1/users
  filters:
  - type: URLRewrite
    urlRewrite:
      path:
        type: ReplacePrefixMatch
        replacePrefixMatch: /api/internal/users
  backendRefs:
  - name: user-service
    port: 80
```

### Канарейка через Traffic Splitting

Разделение трафика между стабильной версией и новой (canary) на основе весов.

```yaml
rules:
- backendRefs:
  - name: app-v1
    port: 80
    weight: 90
  - name: app-v2-canary
    port: 80
    weight: 10
```

### Маршрутизация gRPC (GRPCRoute)

Нативный ресурс для gRPC-трафика (GA с версии v1.1). Позволяет маршрутизировать по конкретным сервисам и методам.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: chat-route
spec:
  parentRefs:
  - name: main-gateway
  rules:
  - matches:
    - method:
        service: "com.example.ChatService"
        method: "SendMessage"
    backendRefs:
    - name: chat-v2-service
      port: 9000
```

### Копирование трафика (Request Mirroring)

Трафик дублируется на тестовый бэкенд. Ответы от зеркального бэкенда игнорируются, что позволяет безопасно проверять новые версии под реальной нагрузкой.

```yaml
rules:
- matches:
  - path: { type: PathPrefix, value: /api }
  filters:
  - type: RequestMirror
    requestMirror:
      backendRef:
        name: app-shadow
        port: 80
  backendRefs:
  - name: app-prod
    port: 80
```

## Дополнительная информация

### Нюансы использования

- **Поддержка фильтров:** Проверьте возможности вашего контроллера (например, Cilium или Envoy Gateway) перед использованием `RequestMirror` или сложных `CORS`-правил.
- **Статусы:** При возникновении проблем проверьте поле `ResolvedRefs` в статусе маршрута. Ошибки в конфигурации фильтров блокируют применение всего правила.
- **Производительность:** Фильтры модификации заголовков и перезаписи URL выполняются на уровне прокси и практически не добавляют задержек.

**См. также:**

- [Базовые сценарии](./practical_basic.md) — основы настройки ресурсов.
- [Миграция с Ingress](./migration.md) — пошаговое руководство по переходу.
- [Реализации: Envoy Gateway](./envoy_gateway.md) — примеры настройки специфичных политик.

**Родительская тема:** [Gateway API](./definitions.md)
