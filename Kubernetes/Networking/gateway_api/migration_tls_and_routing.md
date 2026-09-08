# Миграция TLS и сложной маршрутизации на Gateway API

## Определения

**TLS Termination** — режим работы шлюза, при котором SSL/TLS-трафик расшифровывается на стороне контроллера (Gateway). Внутренним сервисам трафик передается в открытом виде (HTTP) или перешифровывается (re-encrypt).

**TLS Passthrough** — режим сквозного шифрования, при котором шлюз пересылает зашифрованные пакеты бэкенду без расшифровки. Маршрутизация в этом режиме возможна только на основе SNI (Server Name Indication).

**TLSRoute** — ресурс Gateway API, предназначенный для управления трафиком на уровне TLS/TCP без анализа содержимого прикладного уровня (L7).

**ingress2gateway** — инструмент CLI для автоматизированного преобразования ресурсов Ingress в объекты Gateway API. Частично поддерживает конвертацию TLS-конфигураций.

## Предварительные требования

### Компоненты и версии

| Компонент | Минимальная версия | Проверка |
| :--- | :--- | :--- |
| Kubernetes | 1.24+ | `kubectl version --short` |
| Gateway API CRD | v1.0.0+ | `kubectl get crd gatewayclasses.gateway.networking.k8s.io` |
| Контроллер шлюза | Поддержка TLSRoute | `kubectl get crd tlsroutes.gateway.networking.k8s.io` |
| cert-manager (опционально) | 1.12+ | `kubectl get pods -n cert-manager` |
| openssl | 1.1.1+ | `openssl version` |

### Проверка поддержки TLS контроллером

```bash
# Проверка наличия TLSRoute CRD
kubectl get crd tlsroutes.gateway.networking.k8s.io
# → должно вернуть имя CRD без ошибки

# Проверка поддержки Passthrough (зависит от реализации)
# Envoy Gateway
kubectl get crd | grep envoyproxy.io
# KGateway
kubectl get crd kgateway.dev
```

### Подготовка сертификатов

```bash
# Проверка существующих TLS-секретов для миграции
kubectl get secret --field-selector type=kubernetes.io/tls -A
# → NAMESPACE   NAME              TYPE                DATA   AGE
# → app-prod    app-tls-secret    kubernetes.io/tls   2      30d

# Проверка содержимого сертификата
kubectl get secret app-tls-secret -n app-prod -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text | head -20
# → Subject: CN = app.example.com
# → Not Before: Jan 15 00:00:00 2026 GMT
# → Not After : Apr 15 23:59:59 2026 GMT
```

### Требования к правам RBAC

Для миграции TLS необходимы:
- `get`, `list`, `watch` — для `Secret` (тип `kubernetes.io/tls`)
- `create`, `update` — для `Gateway`, `HTTPRoute`, `TLSRoute`
- `create`, `update` — для `ReferenceGrant` (при кросс-namespace ссылках)

## Базовые концепции

### Стратегии обработки TLS

В Gateway API управление сертификатами более гибкое, чем в классическом Ingress:

- **Разделение полномочий:** Секреты (Secret) с сертификатами могут находиться в административном пространстве имен, отличном от пространства имен приложения.
- **Поддержка нескольких сертификатов:** Один слушатель (Listener) может ссылаться на несколько секретов через `certificateRefs`.
- **SNI-маршрутизация:** Автоматический выбор сертификата на основе имени хоста из TLS-рукопожатия.

### Сравнение Ingress и Gateway API для TLS

| Характеристика | Ingress | Gateway API |
| :--- | :--- | :--- |
| **Хранение сертификатов** | `secretName` в TLS-секции | `certificateRefs` в listener |
| **Кросс-namespace** | Ограниченная поддержка | `ReferenceGrant` |
| **Несколько сертификатов** | Ограничено контроллером | Нативная поддержка через SNI |
| **Passthrough** | Аннотация `ssl-passthrough` | `TLSRoute` + `mode: Passthrough` |
| **Управление** | Аннотации | Типизированные ресурсы |

### Особенности миграции маршрутизации

Миграция сложной маршрутизации (regex, rewrite, redirect) требует замены аннотаций Ingress NGINX на нативные фильтры Gateway API:

- **URL Rewrite:** Заменяет аннотацию `nginx.ingress.kubernetes.io/rewrite-target`.
- **Request Redirect:** Заменяет аннотацию `nginx.ingress.kubernetes.io/ssl-redirect`.
- **Header Modification:** Заменяет аннотации для манипуляции заголовками (например, `proxy_set_header`).

### Таблица соответствия аннотаций Ingress и фильтров Gateway API

| Аннотация Ingress NGINX | Фильтр Gateway API | Тип фильтра |
| :--- | :--- | :--- |
| `rewrite-target: /$1` | `ReplacePrefixMatch: /` | `URLRewrite` |
| `ssl-redirect: "true"` | `Scheme: "https"` | `RequestRedirect` |
| `permanent-redirect: https://...` | `Hostname: new-host.example.com` | `RequestRedirect` |
| `proxy_set_header X-Real-IP $remote_addr` | `RequestHeaderModifier` | `RequestHeaderModifier` |
| `proxy_hide_header X-Powered-By` | `ResponseHeaderModifier` | `ResponseHeaderModifier` |

## Практические сценарии

### Сценарий 1: Перенос TLS Termination

Если в Ingress использовался блок `tls` со ссылкой на `secretName`, в Gateway создается соответствующий слушатель.

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  namespace: app-prod
spec:
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-secret
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

**Эквивалент в Gateway API:**

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
    hostname: "app.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls-secret
        namespace: app-prod
    allowedRoutes:
      namespaces:
        from: All
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: app-prod
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
    sectionName: https
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: app-service
      port: 80
```

**Валидация:**

```bash
# Применение конфигурации
kubectl apply -f gateway.yaml
kubectl apply -f httproute.yaml

# Проверка статуса Gateway
kubectl describe gateway external-gateway -n infra
# → Status:
# →   Listeners:
# →     Name:  https
# →     Attached Routes: 1
# →     Supported Kinds: ...
# →     Conditions:
# →       Type:     ResolvedRefs
# →       Status:   True
# →       Type:     Programmed
# →       Status:   True

# Проверка статуса HTTPRoute
kubectl describe httproute app-route -n app-prod
# → Status:
# →   Parents:
# →     Parent Ref: external-gateway
# →     Conditions:
# →       Type:     Accepted
# →       Status:   True
# →       Type:     ResolvedRefs
# →       Status:   True

# Проверка TLS-соединения
curl -vI https://app.example.com
# → *  subject: CN=app.example.com
# → *  issuer: C=US; O=Let's Encrypt; CN=R3
# → *  SSL certificate verify ok.
# → < HTTP/1.1 200 OK

# Проверка сертификата через openssl
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -subject -dates
# → subject=CN = app.example.com
# → notBefore=Jan 15 00:00:00 2026 GMT
# → notAfter=Apr 15 23:59:59 2026 GMT
```

### Сценарий 2: Перенос SSL Passthrough

Для сквозного шифрования (аннотация `ssl-passthrough: "true"`) используется связка `Gateway` и `TLSRoute`.

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: secure-ingress
  namespace: app-prod
  annotations:
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
spec:
  rules:
  - host: secure.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: secure-service
            port:
              number: 443
```

**Эквивалент в Gateway API:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: infra
spec:
  gatewayClassName: public-lb
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
  name: app-passthrough
  namespace: app-prod
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
    sectionName: tls-passthrough
  hostnames:
  - "secure.example.com"
  rules:
  - backendRefs:
    - name: secure-service
      port: 443
```

**Важно:** В режиме Passthrough невозможно использовать маршрутизацию по путям (Path) или заголовкам, так как контроллер не видит содержимое HTTP-запроса.

**Валидация:**

```bash
# Применение конфигурации
kubectl apply -f gateway-passthrough.yaml
kubectl apply -f tlsroute.yaml

# Проверка статуса Gateway
kubectl describe gateway external-gateway -n infra
# → Status:
# →   Listeners:
# →     Name:  tls-passthrough
# →     Attached Routes: 1
# →     Conditions:
# →       Type:     Programmed
# →       Status:   True

# Проверка статуса TLSRoute
kubectl describe tlsroute app-passthrough -n app-prod
# → Status:
# →   Parents:
# →     Parent Ref: external-gateway
# →     Conditions:
# →       Type:     Accepted
# →       Status:   True

# Проверка Passthrough (трафик должен быть зашифрован до бэкенда)
curl -vI https://secure.example.com
# → *  SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384
# → *  server certificate: CN=secure.example.com
# → < HTTP/1.1 200 OK

# Убедиться что Passthrough работает (сертификат выдан бэкендом, не шлюзом)
echo | openssl s_client -connect secure.example.com:443 -servername secure.example.com 2>/dev/null | openssl x509 -noout -issuer
# → issuer=<бэкенд-сертификат, а не сертификат шлюза>
```

### Сценарий 3: Ручная миграция сложной маршрутизации

**Исходный Ingress (NGINX) с rewrite:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  namespace: app-prod
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
            port:
              number: 8080
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

**Валидация:**

```bash
# Применение маршрута
kubectl apply -f api-route.yaml

# Проверка статуса
kubectl describe httproute api-route -n app-prod
# → Status:
# →   Parents:
# →     Parent Ref: external-gateway
# →     Conditions:
# →       Type:     Accepted
# →       Status:   True

# Проверка работы rewrite
curl -v https://app.example.com/api/users/list
# → Request URI: /users/list (после rewrite)
# → Backend получает: GET /users/list

# Проверка логов бэкенда (должен показать rewritten path)
kubectl logs -n app-prod deployment/api-service --tail=50 | grep "GET"
# → GET /users/list HTTP/1.1
```

### Сценарий 4: Миграция Request Redirect

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: redirect-ingress
  namespace: app-prod
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/permanent-redirect: "https://new-domain.example.com"
spec:
  rules:
  - host: old-domain.example.com
```

**Эквивалент в Gateway API:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-route
  namespace: app-prod
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
  hostnames:
  - "old-domain.example.com"
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        hostname: new-domain.example.com
        statusCode: 301
    backendRefs:
    - name: dummy-service
      port: 80
```

**Валидация:**

```bash
# Применение маршрута
kubectl apply -f redirect-route.yaml

# Проверка редиректа
curl -v http://old-domain.example.com
# → < HTTP/1.1 301 Moved Permanently
# → < Location: https://new-domain.example.com

# Проверка постоянного редиректа
curl -I https://old-domain.example.com
# → HTTP/1.1 301 Moved Permanently
# → Location: https://new-domain.example.com
```

### Сценарий 5: Модификация заголовков при миграции

**Исходный Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: headers-ingress
  namespace: app-prod
  annotations:
    nginx.ingress.kubernetes.io/proxy-set-headers: |
      X-Real-IP: $remote_addr
      X-Forwarded-For: $proxy_add_x_forwarded_for
      X-Forwarded-Proto: $scheme
spec:
  rules:
  - host: app.example.com
```

**Эквивалент в Gateway API:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: headers-route
  namespace: app-prod
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
  hostnames:
  - "app.example.com"
  rules:
  - filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        set:
        - name: X-Real-IP
          value: "0.0.0.0"
        - name: X-Custom-Header
          value: "custom-value"
        remove:
        - X-Powered-By
    backendRefs:
    - name: app-service
      port: 80
```

**Валидация:**

```bash
# Применение маршрута
kubectl apply -f headers-route.yaml

# Проверка заголовков (через логи бэкенда или debug endpoint)
curl -v https://app.example.com/echo-headers
# → Запрос с кастомными заголовками
```

### Сценарий 6: Миграция с кросс-namespace сертификатами

Когда сертификат находится в другом namespace, требуется ReferenceGrant.

```yaml
# ReferenceGrant в namespace с сертификатом (infra)
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-app-cert-access
  namespace: cert-storage
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: infra
  to:
  - group: ""
    kind: Secret
```

**Валидация:**

```bash
# Создание ReferenceGrant
kubectl apply -f reference-grant.yaml

# Проверка что Gateway может использовать секрет
kubectl describe gateway external-gateway -n infra
# → Conditions:
# →   Type:     ResolvedRefs
# →   Status:   True
# →   Reason:   ResolvedRefs
# →   Message:  все ссылки разрешены
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Accepted: False` | Неверная конфигурация listener | Проверить `gatewayClassName`, `protocol`, `port` |
| `ResolvedRefs: False` | Отсутствует ReferenceGrant для Secret | Создать ReferenceGrant в namespace сертификата |
| `CertificateNotFound` | Секрет не существует или неверное имя | Проверить `kubectl get secret -n <namespace>` |
| `InvalidCertificateRef` | Секрет не типа `kubernetes.io/tls` | Проверить тип секрета |
| `HostnameConflict` | Дублирование hostnames в listener | Уникальные hostnames или wildcard |
| `TLSRouteNotPermitted` | Listener не поддерживает TLSRoute | Проверить `allowedRoutes.kinds` |

### Диагностика проблем с TLS

```bash
# Проверка статуса Gateway
kubectl describe gateway <name> -n <namespace>
# → Обратить внимание на Conditions: Accepted, Programmed, ResolvedRefs

# Проверка статуса TLSRoute
kubectl describe tlsroute <name> -n <namespace>

# Проверка существования секрета
kubectl get secret <name> -n <namespace> -o yaml
# → Должен содержать поля tls.crt и tls.key

# Проверка что секрет имеет правильный тип
kubectl get secret <name> -n <namespace> -o jsonpath='{.type}'
# → Должно вернуть: kubernetes.io/tls

# Проверка ReferenceGrant
kubectl get referencegrant -A
kubectl describe referencegrant <name> -n <namespace>

# Логи контроллера шлюза
kubectl logs -n <gateway-namespace> -l control-plane=<controller-label>
```

### Диагностика проблем с маршрутизацией

```bash
# Проверка HTTPRoute
kubectl describe httproute <name> -n <namespace>

# Проверка что фильтры применяются
kubectl get httproute <name> -n <namespace> -o yaml | grep -A10 "filters"

# Проверка логов Envoy (для Envoy Gateway)
kubectl port-forward -n <namespace> <envoy-pod> 19000:19000
curl http://localhost:19000/config_dump | jq '.configs[].http_connection_manager'

# Проверка через curl с verbose
curl -v https://app.example.com/api/test
```

### Процедура отката

```bash
# Удаление маршрутов
kubectl delete httproute <name> -n <namespace>
kubectl delete tlsroute <name> -n <namespace>

# Восстановление Ingress (если сохранён)
kubectl apply -f backup-ingress.yaml

# Удаление Gateway
kubectl delete gateway <name> -n <namespace>

# Проверка что Ingress работает
kubectl describe ingress <name> -n <namespace>
curl -I https://app.example.com
```

## Дополнительная информация

### Рекомендации (Best Practices)

**Планирование миграции:**

- **Инвентаризация:** Перед миграцией составьте полный список Ingress-ресурсов с их TLS-конфигурациями и аннотациями.
- **Приоритизация:** Начинайте с простых сценариев (без rewrite/redirect), затем переходите к сложным.
- **Тестирование:** Используйте staging-окружение для проверки миграции перед production.

**Безопасность:**

- **ReferenceGrant:** Всегда создавайте ReferenceGrant для кросс-namespace доступа к сертификатам.
- **Least Privilege:** Ограничивайте ReferenceGrant минимально необходимым набором разрешений.
- **Аудит:** Регулярно проверяйте какие шлюзы имеют доступ к сертификатам: `kubectl get referencegrant -A`.

**TLS-конфигурация:**

- **SNI-совмещение:** Убедитесь, что контроллер поддерживает SNI при использовании нескольких сертификатов.
- **Обновление сертификатов:** Настройте автоматическое обновление через cert-manager.
- **Мониторинг:** Отслеживайте срок действия сертификатов через Prometheus/Grafana.

**Маршрутизация:**

- **Regex:** Gateway API не поддерживает регулярные выражения в путях на уровне стандарта v1. Для сложных случаев используйте префиксное совпадение или провайдер-специфичные расширения.
- **Постепенная миграция:** Используйте зеркалирование трафика для проверки новой конфигурации до полного переключения.

### Ограничения и особенности

- **ingress2gateway:** Инструмент не поддерживает автоматическую конвертацию всех аннотаций — ручная доработка часто необходима.
- **Passthrough:** В режиме Passthrough недоступна L7-маршрутизация (по путям, заголовкам).
- **Совместимость:** Не все контроллеры Gateway API поддерживают TLSRoute — проверяйте документацию конкретной реализации.
- **Валидация:** CRD-схемы валидируют базовые параметры, но семантические ошибки могут быть обнаружены только во время выполнения.

**См. также:**

- [Расширенные функции маршрутизации](./routing_features.md) — детальное описание фильтров URLRewrite, RequestRedirect
- [Миграция с Ingress](./migration.md) — общая стратегия и инструменты миграции
- [Тестирование и перенос трафика](./migration_testing.md) — безопасное переключение пользователей

**Родительская тема:** [Gateway API](./definitions.md)
