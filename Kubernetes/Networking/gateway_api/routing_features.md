# Расширенная маршрутизация в Gateway API

## Определения

**Фильтр (Filter)** — стандартный механизм Gateway API для модификации запросов и ответов. Фильтры заменяют собой вендор-специфичные аннотации Ingress-контроллеров, обеспечивая переносимость конфигурации.

**Traffic Splitting** — распределение входящего трафика между несколькими сервисами (бэкендами) на основе весовых коэффициентов или условий (headers, cookies).

**CORS (Cross-Origin Resource Sharing)** — механизм безопасности, позволяющий веб-приложениям в браузере запрашивать ресурсы с другого домена. С версии v1.5 Gateway API поддерживает нативный CORS-фильтр.

**Канареечное развертывание (Canary Deployment)** — стратегия постепенного переключения трафика между версиями сервиса для минимизации рисков при выпуске новых версий.

**A/B-тестирование** — метод сравнения двух версий приложения путём распределения трафика между ними на основе заголовков, cookies или весовых коэффициентов.

## Предварительные требования

- Kubernetes кластер версии 1.25+
- Gateway API CRD версии v1.6.0+ (Standard Channel)
- Установленный контроллер Gateway API (Envoy Gateway, KGateway, Traefik, Cilium)
- Базовое понимание ресурсов Gateway API (Gateway, HTTPRoute) — см. [Базовые сценарии](./practical_basic.md)
- Доступ к кластеру через `kubectl` с правами на создание HTTPRoute в целевых namespace

## Базовые концепции

Стандартизация функций в Gateway API избавляет от необходимости использовать проприетарные аннотации (например, `nginx.ingress.kubernetes.io/rewrite-target`). Весь функционал описывается в блоке `spec.rules[].filters`.

### Основные типы фильтров (Standard Channel)

| Тип фильтра | Назначение | Основные поля |
| :--- | :--- | :--- |
| `RequestHeaderModifier` | Добавление, изменение или удаление заголовков запроса | `set[]`, `add[]`, `remove[]` |
| `ResponseHeaderModifier` | Модификация заголовков ответа | `set[]`, `add[]`, `remove[]` |
| `RequestRedirect` | Управление перенаправлением (301/302) | `scheme`, `hostname`, `path`, `statusCode` |
| `URLRewrite` | Внутренняя перезапись путей и хостов | `hostname`, `path` |
| `RequestMirror` | Копирование трафика для тестирования (Traffic Shadowing) | `backendRef` |
| `CORS` | Нативная обработка префлайт-запросов и заголовков безопасности | `allowOrigins`, `allowMethods`, `allowHeaders`, `maxAge` |

### Принцип работы фильтров

Фильтры применяются последовательно в порядке их объявления в массиве `filters[]`. Каждый фильтр модифицирует запрос или ответ перед передачей следующему фильтру или бэкенду.

**Порядок применения:**
1. Запрос поступает на Gateway
2. HTTPRoute определяет подходящее правило по `matches`
3. Фильтры применяются последовательно (если указаны)
4. Модифицированный запрос направляется на бэкенд(ы) согласно `backendRefs`

### Обработка CORS-запросов

CORS-фильтр позволяет шлюзу самостоятельно отвечать на предварительные запросы (`OPTIONS`), не нагружая бэкенд:

1. Браузер отправляет `OPTIONS` запрос с заголовками `Origin`, `Access-Control-Request-Method`, `Access-Control-Request-Headers`
2. Шлюз проверяет соответствие `Origin` списку `allowOrigins`
3. Если проверка пройдена — шлюз возвращает заголовки `Access-Control-Allow-Origin`, `Access-Control-Allow-Methods`, `Access-Control-Allow-Headers`
4. Браузер разрешает кросс-доменный запрос (или блокирует при несоответствии)

## Сравнение с Ingress (Legacy Annotations)

Основное преимущество Gateway API — замена вендор-специфичных аннотаций на стандартизированные объекты `spec`.

### Канареечные развертывания (Canary)

В Ingress конфигурация зависела от реализации контроллера. В Gateway API это нативная часть `backendRefs`.

| Метод | Ingress (NGINX) | Gateway API (Standard) |
| :--- | :--- | :--- |
| **Реализация** | `nginx.ingress.kubernetes.io/canary-weight: "10"` | `weight: 10` в `backendRefs` |
| **Прозрачность** | Скрыта в метаданных | Явно видна в спецификации роута |

**Пример Gateway API:**
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

### Настройка CORS

Gateway API v1.5+ вводит унифицированный фильтр, избавляя от необходимости знать специфичные ключи аннотаций.

| Характеристика | Ingress (NGINX) | Gateway API (Standard) |
| :--- | :--- | :--- |
| **Аннотация/Фильтр**| `nginx.ingress.kubernetes.io/enable-cors: "true"` | `type: CORS` |
| **Заголовки** | `nginx.ingress.kubernetes.io/cors-allow-headers` | `allowHeaders: [...]` |

**Пример Gateway API:**
```yaml
rules:
- filters:
  - type: CORS
    cors:
      allowOrigins: ["https://example.com"]
      allowMethods: [GET, POST]
      allowHeaders: [Authorization, Content-Type]
```

## Практические сценарии

### Настройка CORS (v1.5+)

Фильтр `CORS` позволяет шлюзу самостоятельно отвечать на запросы `OPTIONS`, не нагружая бэкенд.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-with-cors
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
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
        exposeHeaders: [X-Request-Id]
        maxAge: 600
        allowCredentials: true
    backendRefs:
    - name: api-service
      port: 8080
```

**Валидация:**
```bash
kubectl get httproute api-with-cors -n app-prod
# → NAME             HOSTNAMES           AGE
# → api-with-cors    api.example.com     1m

kubectl describe httproute api-with-cors -n app-prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Reason:                NoConflicts
# →       Status:                True
# →       Type:                  Accepted

# Проверка CORS-заголовков
curl -I -X OPTIONS -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: GET" \
  http://api.example.com
# → HTTP/1.1 200 OK
# → Access-Control-Allow-Origin: https://app.example.com
# → Access-Control-Allow-Methods: GET, POST, OPTIONS
# → Access-Control-Allow-Headers: Content-Type, Authorization
# → Access-Control-Max-Age: 600
```

### Перезапись URL (URL Rewrite)

Используется для адаптации внешних путей к внутренней структуре микросервисов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: rewrite-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
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

**Валидация:**
```bash
kubectl get httproute rewrite-example -n app-prod
# → NAME               HOSTNAMES         AGE
# → rewrite-example    api.example.com   30s

# Проверка перезаписи пути
curl -v http://api.example.com/v1/users/123
# → Прокси перенаправит на user-service как /api/internal/users/123
```

### Модификация заголовков запроса и ответа

Используется для добавления/удаления технических заголовков, корреляционных ID, security-заголовков.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: header-modify-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
  rules:
  - filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        set:
        - name: X-Forwarded-Proto
          value: https
        - name: X-Request-Id
          value: "static-request-id"
        add:
        - name: X-Custom-Header
          value: custom-value
        remove:
        - X-Unwanted-Header
    - type: ResponseHeaderModifier
      responseHeaderModifier:
        set:
        - name: X-Content-Type-Options
          value: nosniff
        - name: X-Frame-Options
          value: DENY
        add:
        - name: X-Request-Id
          value: response-id
        remove:
        - X-Powered-By
        - Server
    backendRefs:
    - name: api-service
      port: 8080
```

**Валидация:**
```bash
kubectl get httproute header-modify-example -n app-prod
# → NAME                     HOSTNAMES         AGE
# → header-modify-example    api.example.com   45s

# Проверка модификации заголовков ответа
curl -I http://api.example.com
# → X-Content-Type-Options: nosniff
# → X-Frame-Options: DENY
# → (заголовки X-Powered-By и Server отсутствуют)
```

### Перенаправление запросов (RequestRedirect)

Используется для принудительного перенаправления HTTP→HTTPS, смены домена или пути.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "old.example.com"
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        hostname: new.example.com
        path:
          type: ReplaceFullPath
          replaceFullPath: /new-path
        statusCode: 301
        port: 443
    backendRefs:
    - name: api-service
      port: 8080
```

**Валидация:**
```bash
kubectl get httproute redirect-example -n app-prod
# → NAME               HOSTNAMES          AGE
# → redirect-example   old.example.com    1m

# Проверка перенаправления
curl -I http://old.example.com/old-path
# → HTTP/1.1 301 Moved Permanently
# → Location: https://new.example.com/new-path
```

### Канарейка через Traffic Splitting

Разделение трафика между стабильной версией и новой (canary) на основе весов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: canary-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
  rules:
  - backendRefs:
    - name: app-v1
      port: 80
      weight: 90
    - name: app-v2-canary
      port: 80
      weight: 10
```

**Валидация:**
```bash
kubectl get httproute canary-example -n app-prod
# → NAME              HOSTNAMES         AGE
# → canary-example    api.example.com   2m

kubectl describe httproute canary-example -n app-prod
# → Spec:
# →   Rules:
# →     Backend Refs:
# →       Name:     app-v1
# →       Weight:   90
# →       Name:     app-v2-canary
# →       Weight:   10
```

### A/B-тестирование на основе заголовков

Распределение трафика между версиями на основе заголовков запроса.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: ab-testing-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - headers:
      - name: X-Version
        type: Exact
        value: v2
    backendRefs:
    - name: app-v2-service
      port: 80
  - backendRefs:
    - name: app-v1-service
      port: 80
```

**Валидация:**
```bash
# Запрос с заголовком X-Version: v2 → app-v2-service
curl -H "X-Version: v2" http://api.example.com
# → Ответ от app-v2-service

# Обычный запрос → app-v1-service
curl http://api.example.com
# → Ответ от app-v1-service
```

### Маршрутизация gRPC (GRPCRoute)

Нативный ресурс для gRPC-трафика (GA с версии v1.1). Позволяет маршрутизировать по конкретным сервисам и методам.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: chat-route
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "grpc.example.com"
  rules:
  - matches:
    - method:
        service: "com.example.ChatService"
        method: "SendMessage"
    backendRefs:
    - name: chat-v2-service
      port: 9000
  - matches:
    - method:
        service: "com.example.ChatService"
        method: "GetHistory"
    backendRefs:
    - name: chat-v1-service
      port: 9000
```

**Валидация:**
```bash
kubectl get grpcroute chat-route -n app-prod
# → NAME         HOSTNAMES         AGE
# → chat-route   grpc.example.com  1m

kubectl describe grpcroute chat-route -n app-prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Reason:                Accepted
# →       Status:                True
# →       Type:                  Accepted
```

### Копирование трафика (Request Mirroring)

Трафик дублируется на тестовый бэкенд. Ответы от зеркального бэкенда игнорируются, что позволяет безопасно проверять новые версии под реальной нагрузкой.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mirror-example
  namespace: app-prod
spec:
  parentRefs:
  - name: public-gateway
    namespace: infra-ns
  hostnames:
  - "api.example.com"
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

**Валидация:**
```bash
kubectl get httproute mirror-example -n app-prod
# → NAME             HOSTNAMES         AGE
# → mirror-example   api.example.com   1m

# Проверка: логи app-shadow должны содержать копии запросов
kubectl logs -n app-prod -l app=app-shadow --tail=50
# → Должны быть видны копии запросов к /api
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| CORS-запросы блокируются | Неверный `allowOrigins` или отсутствует `OPTIONS` в `allowMethods` | Проверить конфигурацию CORS-фильтра, добавить `OPTIONS` |
| Перенаправление не работает | Неверный `statusCode` (допустимы только 301/302) | Исправить `statusCode` на 301 или 302 |
| Канарейка не распределяет трафик | Сумма весов равна 0 или один из бэкендов недоступен | Проверить `weight` (должен быть >0) и статус бэкендов |
| gRPC-маршрутизация не работает | Неверное имя сервиса/метода в `matches` | Проверить полное имя gRPC-сервиса и метода |
| Зеркалирование не работает | Контроллер не поддерживает `RequestMirror` | Проверить документацию контроллера |
| Заголовки не модифицируются | Ошибка в синтаксисе `set`/`add`/`remove` | Проверить имена заголовков и значения |

### Диагностика проблем

```bash
# Проверка статуса HTTPRoute
kubectl get httproute -A -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.parents[0].conditions[0].type}{"\t"}{.status.parents[0].conditions[0].status}{"\n"}{end}'

# Проверка событий
kubectl get events -n app-prod --field-selector reason=ResolvedRefsFailed
kubectl get events -n app-prod --field-selector reason=BackendNotFound

# Просмотр логов контроллера
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=100

# Проверка конфигурации Envoy (для Envoy Gateway)
kubectl exec -n envoy-gateway-system deploy/envoy-gateway -- envoy-config-dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration")'
```

### Отладка CORS

```bash
# Проверка preflight-запроса
curl -v -X OPTIONS \
  -H "Origin: https://app.example.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Authorization" \
  http://api.example.com

# Ожидаемый ответ:
# → HTTP/1.1 200 OK
# → Access-Control-Allow-Origin: https://app.example.com
# → Access-Control-Allow-Methods: GET, POST, OPTIONS
# → Access-Control-Allow-Headers: Authorization
# → Access-Control-Max-Age: 600
```

## Best Practices

### Организация маршрутизации

1. **Используйте отдельные HTTPRoute для разных функций:**
   - Один HTTPRoute для CORS
   - Другой для канареечного развертывания
   - Упрощает управление и отладку

2. **Документируйте фильтры:**
   - Добавляйте комментарии в YAML к каждому фильтру
   - Объясняйте назначение неочевидных модификаций

3. **Тестируйте фильтры изолированно:**
   - Проверяйте каждый фильтр отдельно перед комбинацией
   - Используйте staging-среду для сложных конфигураций

### Безопасность

1. **Ограничивайте CORS-Origins:**
   - Не используйте wildcard `*` для `allowOrigins` в production
   - Указывайте конкретные домены
   - Используйте `allowCredentials: true` только при необходимости

2. **Удаляйте чувствительные заголовки:**
   - Используйте `ResponseHeaderModifier` для удаления `X-Powered-By`, `Server`
   - Добавляйте security-заголовки: `X-Content-Type-Options`, `X-Frame-Options`

3. **Контролируйте перенаправления:**
   - Проверяйте, что `RequestRedirect` не создаёт циклов
   - Используйте 301 для постоянных перенаправлений, 302 для временных

### Производительность

1. **Минимизируйте количество фильтров:**
   - Каждый фильтр добавляет небольшую задержку
   - Объединяйте связанные модификации

2. **Используйте URLRewrite вместо внешнего прокси:**
   - Перезапись на уровне Gateway эффективнее
   - Уменьшает количество сетевых хопов

3. **Осторожно используйте RequestMirror:**
   - Зеркалирование удваивает нагрузку на инфраструктуру
   - Используйте только для критичных тестов

## Дополнительная информация

### Нюансы использования

- **Поддержка фильтров:** Проверьте возможности вашего контроллера (например, Cilium или Envoy Gateway) перед использованием `RequestMirror` или сложных `CORS`-правил.
- **Статусы:** При возникновении проблем проверьте поле `ResolvedRefs` в статусе маршрута. Ошибки в конфигурации фильтров блокируют применение всего правила.
- **Производительность:** Фильтры модификации заголовков и перезаписи URL выполняются на уровне прокси и практически не добавляют задержек.
- **Порядок фильтров:** Фильтры применяются последовательно. Порядок важен при использовании нескольких фильтров в одном правиле.

**См. также:**

- [Базовые сценарии](./practical_basic.md) — основы настройки ресурсов.
- [Миграция с Ingress](./migration.md) — пошаговое руководство по переходу.
- [Реализации: Envoy Gateway](./envoy_gateway.md) — примеры настройки специфичных политик.

**Родительская тема:** [Gateway API](./definitions.md)
