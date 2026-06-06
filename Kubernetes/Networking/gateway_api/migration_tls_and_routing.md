# Миграция TLS и сложной маршрутизации на Gateway API

## Определения

**TLS Termination** — режим работы шлюза, при котором SSL/TLS-трафик расшифровывается на стороне контроллера (Gateway). Внутренним сервисам трафик передается в открытом виде (HTTP) или перешифровывается (re-encrypt).

**TLS Passthrough** — режим сквозного шифрования, при котором шлюз пересылает зашифрованные пакеты бэкенду без расшифровки. Маршрутизация в этом режиме возможна только на основе SNI (Server Name Indication).

**TLSRoute** — ресурс Gateway API, предназначенный для управления трафиком на уровне TLS/TCP без анализа содержимого прикладного уровня (L7).

## Базовые концепции

### Стратегии обработки TLS
В Gateway API управление сертификатами более гибкое, чем в классическом Ingress:
- **Разделение полномочий:** Секреты (Secret) с сертификатами могут находиться в административном пространстве имен, отличном от пространства имен приложения.
- **Поддержка нескольких сертификатов:** Один слушатель (Listener) может ссылаться на несколько секретов через `certificateRefs`.

### Особенности маршрутизации
Миграция сложной маршрутизации (regex, rewrite, redirect) требует замены аннотаций Ingress NGINX на нативные фильтры Gateway API:
- **URL Rewrite:** Заменяет аннотацию `nginx.ingress.kubernetes.io/rewrite-target`.
- **Request Redirect:** Заменяет аннотацию `nginx.ingress.kubernetes.io/ssl-redirect`.
- **Header Modification:** Заменяет аннотации для манипуляции заголовками (например, `proxy_set_header`).

## Практические сценарии

### Сценарий 1: Перенос TLS Termination
Если в Ingress использовался блок `tls` со ссылкой на `secretName`, в Gateway создается соответствующий слушатель.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: infra
spec:
  gatewayClassName: public-lb
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls-secret
        namespace: app-prod
    allowedRoutes:
      namespaces:
        from: All
```

### Сценарий 2: Перенос SSL Passthrough
Для сквозного шифрования (аннотация `ssl-passthrough: "true"`) используется связка `Gateway` и `TLSRoute`.

```yaml
# Gateway Listener
- name: tls-passthrough
  protocol: TLS
  port: 443
  tls:
    mode: Passthrough
---
# TLSRoute
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: app-passthrough
  namespace: app-prod
spec:
  parentRefs:
  - name: external-gateway
    sectionName: tls-passthrough
  hostnames:
  - "secure.example.com"
  rules:
  - backendRefs:
    - name: secure-service
      port: 443
```
**Важно:** В режиме Passthrough невозможно использовать маршрутизацию по путям (Path) или заголовкам, так как контроллер не видит содержимое HTTP-запроса.

### Сценарий 3: Ручная миграция сложной маршрутизации

**Исходный Ingress (NGINX):**
```yaml
annotations:
  nginx.ingress.kubernetes.io/rewrite-target: /$1
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /api/(.*)
        pathType: Prefix
        backend:
          service:
            name: api-service
            port: { number: 8080 }
```

**Эквивалент в Gateway API (HTTPRoute):**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: app-prod
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
      port: 8080
```

## Дополнительная информация

**Типичные проблемы миграции:**
- **Конфликты SNI:** При использовании нескольких сертификатов убедитесь, что контроллер поддерживает SNI-совмещение.
- **Права доступа:** Если шлюз ссылается на секрет в другом пространстве имен, необходимо создать ресурс `ReferenceGrant`.
- **Regex:** Gateway API не поддерживает регулярные выражения в путях на уровне стандарта v1. Для сложных случаев используйте префиксное совпадение или провайдер-специфичные расширения.

**См. также:**
- [Расширенные функции маршрутизации](./routing_features.md) — детальное описание фильтров.
- [Миграция с Ingress](./migration.md) — общая стратегия и инструменты.
- [Тестирование и перенос трафика](./migration_testing.md) — как безопасно переключить пользователей.

**Родительская тема:** [Gateway API](./definitions.md)
