# Расширенная маршрутизация в Gateway API

## Определения

**Фильтр (Filter)** — стандартный механизм Gateway API, позволяющий модифицировать HTTP-запросы или ответы непосредственно на прокси-сервере. Фильтры описываются в спецификации `HTTPRoute` и заменяют собой вендор-специфичные аннотации Ingress-контроллеров.

**Request Redirect** — механизм перенаправления клиента на другой URL с использованием HTTP-статусов 3xx. При редиректе клиент (браузер) получает новый адрес и выполняет повторный запрос.

**URL Rewrite** — изменение пути или хоста запроса на стороне прокси-сервера перед его передачей бэкенду. В отличие от редиректа, этот процесс прозрачен для клиента.

**Traffic Splitting** — распределение входящего трафика между несколькими сервисами на основе весов или специфических правил (заголовки, куки).

## Базовые концепции

Стандартизация расширенных функций в Gateway API позволяет избежать привязки к конкретному контроллеру. Вместо изучения десятков аннотаций Nginx или Traefik используется единый синтаксис фильтров в `spec.rules[].filters`.

### Основные типы фильтров

- `RequestHeaderModifier`: добавление, изменение или удаление заголовков запроса.
- `ResponseHeaderModifier`: модификация заголовков ответа сервера.
- `RequestRedirect`: управление навигацией пользователя.
- `URLRewrite`: внутренняя адаптация путей под API бэкендов.
- `RequestMirror`: копирование трафика на дополнительный бэкенд для тестирования (shadowing).

## Практические сценарии

### Перенаправление запросов (Request Redirect)

#### Редирект с HTTP на HTTPS

Стандартная задача по принудительному использованию защищенного соединения.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: http-to-https-redirect
spec:
  parentRefs:
  - name: my-gateway
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

#### Изменение пути при редиректе

Перенаправление пользователей со старого адреса `/login` на новый `/auth`.

```yaml
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
      statusCode: 302
```

### Перезапись URL (URL Rewrite)

Используется, когда структура путей на прокси отличается от структуры путей внутри приложения.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-rewrite
spec:
  parentRefs:
  - name: my-gateway
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/v1
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /internal/v1
    backendRefs:
    - name: api-service
      port: 80
```

В данном примере запрос `app.example.com/api/v1/users` будет передан сервису как `/internal/v1/users`.

### Модификация заголовков

Полезно для передачи метаданных о шлюзе или удаления внутренних технических заголовков перед ответом клиенту.

```yaml
rules:
- filters:
  - type: RequestHeaderModifier
    requestHeaderModifier:
      add:
      - name: "X-Gateway-ID"
        value: "edge-01"
      remove:
      - "X-Internal-Token"
  - type: ResponseHeaderModifier
    responseHeaderModifier:
      add:
      - name: "Cache-Control"
        value: "public, max-age=3600"
  backendRefs:
  - name: web-service
    port: 80
```

### Разделение трафика (Traffic Splitting)

#### Канареечное развертывание (Canary Deployment)

Направление трафика на новую версию для группы пользователей с определенным заголовком.

```yaml
rules:
- matches:
  - headers:
    - type: Exact
      name: "X-Canary-Test"
      value: "true"
  backendRefs:
  - name: app-v2
    port: 80
- backendRefs:
  - name: app-v1
    port: 80
```

#### Взвешенная балансировка (Blue/Green)

Постепенное переключение нагрузки между версиями на основе весовых коэффициентов.

```yaml
rules:
- backendRefs:
  - name: app-stable
    port: 80
    weight: 90
  - name: app-beta
    port: 80
    weight: 10
```

## Дополнительная информация

**Особенности реализации:** не все контроллеры поддерживают полный набор фильтров (например, `RequestMirror` может отсутствовать в некоторых реализациях). Всегда проверяйте статус ресурса `HTTPRoute` — при ошибке применения фильтра в статусе будет указано `ResolvedRefs: False`.

**См. также:**

- [Базовые сценарии](./practical_basic.md) — основы настройки ресурсов Gateway API
- [Миграция с Ingress](./migration.md) — сравнение аннотаций и фильтров
- [L4-маршрутизация](./layer4_routing.md) — TCPRoute и UDPRoute

**Родительская тема:** [Gateway API](./definitions.md)
