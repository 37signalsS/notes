# Traefik — реализация Gateway API

## Определения

**Traefik (v3.3+)** — современный облачно-ориентированный обратный прокси-сервер и балансировщик нагрузки, обеспечивающий нативную поддержку спецификации Kubernetes Gateway API (v1.2+). Traefik является одной из наиболее популярных реализаций Gateway API благодаря своей простоте, автоматическому обнаружению сервисов и встроенной поддержке TLS (ACME).

**Kubernetes Gateway Provider** — встроенный компонент Traefik, который отслеживает ресурсы Gateway API в кластере и динамически генерирует правила маршрутизации. В отличие от традиционного Ingress-контроллера, Traefik в режиме Gateway API использует более гибкую ролевую модель разделения ответственности.

## Базовые концепции

### Особенности реализации

- **Direct Pod Targeting:** Traefik по умолчанию направляет трафик напрямую на IP-адреса подов (Endpoints), минуя виртуальный IP сервиса и `kube-proxy`. Это снижает задержки и позволяет реализовать более точные алгоритмы балансировки (например, EWMA).
- **Поддержка спецификации GAMMA:** Traefik v3 поддерживает управление трафиком внутри кластера (Service Mesh). Это позволяет использовать `HTTPRoute` с `parentRef`, указывающим на `Service`, для реализации канареечных релизов и зеркалирования трафика East-West.
- **Middleware и Filters:** Traefik интегрирует свои мощные Middleware (RateLimit, Circuit Breaker, Auth) через стандартный механизм `filters` в `HTTPRoute`. Для специфичных настроек, не покрытых стандартом, используется `ExtensionRef`.
- **Конвергенция конфигураций:** Traefik может одновременно обрабатывать ресурсы Ingress, Gateway API и свои собственные CRD (IngressRoute), обеспечивая плавную миграцию.

### Установка и активация

Для использования Gateway API необходимо предварительно установить CRD (версии v1.2.0+ для полной поддержки Traefik v3.3+).

В конфигурации Traefik (через Helm `values.yaml`) активация провайдера выглядит следующим образом:

```yaml
providers:
  kubernetesGateway:
    enabled: true
    experimentalChannel: true # Включает поддержку TCPRoute, UDPRoute и GRPCRoute
    statusAddress:
      service:
        name: traefik
        namespace: traefik
```

## Практические сценарии

### Настройка инфраструктуры (GatewayClass и Gateway)

`GatewayClass` объявляет Traefik контроллером, а `Gateway` описывает физические точки входа.

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
  name: external-gw
  namespace: traefik
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-example-com
    allowedRoutes:
      namespaces:
        from: All
```

### Расширенная маршрутизация с Middleware

Пример использования Traefik Middleware через `ExtensionRef` для ограничения скорости (Rate Limiting).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  rules:
  - matches:
    - path: { type: PathPrefix, value: /v1 }
    filters:
    - type: ExtensionRef
      extensionRef:
        group: traefik.io
        kind: Middleware
        name: global-ratelimit
    backendRefs:
    - name: api-service
      port: 8080
```

### L4 Маршрутизация (TCP и TLS Passthrough)

Traefik v3 поддерживает маршрутизацию без дешифрования трафика.

**Пример TLSRoute (Passthrough):**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TLSRoute
metadata:
  name: db-tls-passthrough
spec:
  parentRefs:
  - name: external-gw
    sectionName: tls-passthrough-port
  hostnames:
  - "db.example.com"
  rules:
  - backendRefs:
    - name: postgres-service
      port: 5432
```

### Поддержка gRPC

Для gRPC трафика Traefik предоставляет нативную маршрутизацию на уровне методов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: grpc-app
spec:
  parentRefs:
  - name: external-gw
  rules:
  - matches:
    - method:
        service: com.example.UserService
        method: GetUser
    backendRefs:
    - name: user-service
      port: 9000
```

### Канареечные релизы и зеркалирование трафика

**Взвешенная маршрутизация (Weighted Canary):**

Позволяет постепенно перенаправлять трафик между версиями сервиса через механизм `backendRefs` с весами:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api }
    backendRefs:
    - name: api-v1
      port: 8080
      weight: 90
    - name: api-v2
      port: 8080
      weight: 10
```

**Зеркалирование трафика (Traffic Mirroring):**

Позволяет дублировать процент трафика на тестовый сервис без влияния на основной поток. В Gateway API зеркалирование реализуется через спецификацию GAMMA (Gateway API for Mesh Management and Administration) с использованием `HTTPRoute` и `Service` как `parentRef`:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-mirror
  namespace: prod
spec:
  parentRefs:
  - name: api-service
    group: ""
    kind: Service
  rules:
  - filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        set:
        - name: X-Mirrored
          value: "true"
    backendRefs:
    - name: api-service
      port: 8080
    - name: api-mirror-service
      port: 8080
```

> **Примечание:** Зеркалирование трафика в режиме GAMMA поддерживается Traefik v3.3+ и требует включения `experimentalChannel` в конфигурации Gateway Provider.

### Health Checks и автоматическое отключение бэкендов

Traefik поддерживает активные и пассивные проверки здоровья бэкендов:

**Активные проверки (Active Health Checks):**

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: api-route
  namespace: prod
spec:
  entryPoints:
  - websecure
  routes:
  - match: Host(`api.example.com`)
    kind: Rule
    services:
    - name: api-service
      port: 8080
      healthCheck:
        path: /health
        interval: 10s
        timeout: 3s
        scheme: http
        headers:
          X-Check: health
```

**Пассивные проверки (Passive Health Checks) через Circuit Breaker:**

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: circuit-breaker
  namespace: prod
spec:
  circuitBreaker:
    expression: "LatencyAtQuantileMS(50.0) > 1000 || NetworkErrorRatio() > 0.30 || ResponseCodeRatio(500, 600, 0, 600) > 0.25"
    checkPeriod: 10s
    fallbackDuration: 30s
    recoveryDuration: 60s
```

**Параметры Circuit Breaker:**
- `expression` — условие срабатывания (латентность, доля ошибок, соотношение кодов ответа)
- `checkPeriod` — период проверки метрик
- `fallbackDuration` — время переключения на fallback-сервис
- `recoveryDuration` — время до попытки восстановления основного сервиса

### Аутентификация и авторизация

**BasicAuth через Middleware:**

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: basic-auth
  namespace: prod
spec:
  basicAuth:
    secret: auth-secret  # Secret с файлом htpasswd
```

```yaml
# Создание Secret с htpasswd
apiVersion: v1
kind: Secret
metadata:
  name: auth-secret
  namespace: prod
type: Opaque
data:
  # htpasswd -nb admin password | base64
  users: YWRtaW46JGFwcjEkSDY1dnFYNDAkLi4uLi4uLi4uLg==
```

**ForwardAuth (проксирование аутентификации на внешний сервис):**

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: forward-auth
  namespace: prod
spec:
  forwardAuth:
    address: http://auth-service.auth.svc.cluster.local:8080/verify
    trustForwardHeader: true
    authResponseHeaders:
    - X-Auth-User
    - X-Auth-Roles
    authRequestHeaders:
    - Authorization
```

**IP Allowlist (ограничение доступа по IP):**

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: ip-allowlist
  namespace: prod
spec:
  ipAllowList:
    sourceRange:
    - 192.168.1.0/24
    - 10.0.0.0/8
```

### Интеграция с сервисами и Service Mesh (GAMMA)

Traefik v3 поддерживает спецификацию GAMMA для управления трафиком внутри кластера (East-West traffic):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: internal-route
  namespace: backend
spec:
  parentRefs:
  - name: backend-service
    group: ""
    kind: Service
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api/v1 }
    backendRefs:
    - name: backend-v1
      port: 8080
      weight: 80
    - name: backend-v2
      port: 8080
      weight: 20
```

**Принципы работы GAMMA в Traefik:**
- `parentRef` указывает на `Service`, а не на `Gateway`
- Маршрутизация происходит на уровне приложения, минуя kube-proxy
- Поддерживается канареечный релиз и зеркалирование между сервисами
- Требует включения `experimentalChannel` в конфигурации

### Работа с Headless Service и Direct Pod Targeting

Traefik по умолчанию использует Direct Pod Targeting — направляет трафик напрямую на IP-адреса подов:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: headless-route
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  rules:
  - matches:
    - path: { type: PathPrefix, value: / }
    backendRefs:
    - name: headless-service  # Headless Service с прямым доступом к подам
      port: 8080
```

**Преимущества Direct Pod Targeting:**
- Отсутствие дополнительного хопа через kube-proxy
- Снижение задержек
- Возможность использования алгоритмов балансировки EWMA (Exponentially Weighted Moving Average)
- Автоматическое исключение недоступных подов из балансировки

### TLS и автоматическое управление сертификатами (ACME)

Traefik имеет встроенную поддержку ACME (Automated Certificate Management Environment) для автоматического получения и обновления сертификатов Let's Encrypt:

**Настройка Certificate Resolver через Helm values:**

```yaml
# values.yaml для Helm chart
certResolvers:
  letsencrypt:
    acme:
      email: admin@example.com
      storage: /data/acme.json
      httpChallenge:
        entryPoint: web
      # Или DNS Challenge для wildcard-сертификатов:
      # dnsChallenge:
      #   provider: cloudflare
      #   resolvers:
      #   - "1.1.1.1:53"
      #   - "8.8.8.8:53"
```

**Использование в Gateway:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: traefik
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod  # Альтернатива: интеграция с cert-manager
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-example-com
    allowedRoutes:
      namespaces:
        from: All
```

**Типы ACME Challenge:**
- **HTTP Challenge** — проверка через HTTP-запрос на порт 80 (требуется доступность entrypoint `web`)
- **TLS Challenge** — проверка через TLS-ALPN на порту 443 (не требует отдельного порта)
- **DNS Challenge** — проверка через DNS TXT-запись (необходим для wildcard-сертификатов `*.example.com`)

**Хранение сертификатов:**
- Файл `acme.json` — JSON-файл с сертификатами и приватными ключами
- Требует прав доступа `chmod 600` (иначе Traefik проигнорирует файл)
- Рекомендуется использовать PersistentVolume для сохранения между рестартами

### Мониторинг и метрики

Traefik экспортирует метрики через встроенный плагин Prometheus:

**Основные метрики Gateway API:**

| Метрика | Описание | Тип |
|:---|:---|:---|
| `traefik_gateway_requests_total` | Общее количество запросов через Gateway | Counter |
| `traefik_gateway_request_duration_seconds` | Длительность запросов через Gateway | Histogram |
| `traefik_route_requests_total` | Количество запросов по маршрутам | Counter |
| `traefik_backend_requests_total` | Количество запросов к бэкендам | Counter |
| `traefik_backend_open_connections` | Открытые соединения к бэкендам | Gauge |
| `traefik_backend_server_up` | Статус доступности бэкенда (0/1) | Gauge |
| `traefik_config_reloads_total` | Количество перезагрузок конфигурации | Counter |
| `traefik_entrypoint_open_connections` | Открытые соединения на entrypoint | Gauge |

**Настройка ServiceMonitor для Prometheus Operator:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: traefik
  namespace: traefik
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

**Включение метрик в Helm values:**

```yaml
# values.yaml
ports:
  metrics:
    port: 9100
    expose: true
    exposedPort: 9100
    protocol: TCP
additionalArguments:
- "--metrics.prometheus=true"
- "--metrics.prometheus.entryPoint=metrics"
- "--metrics.prometheus.addEntryPointsLabels=true"
- "--metrics.prometheus.addRoutersLabels=true"
- "--metrics.prometheus.addServicesLabels=true"
```

**Grafana Dashboard:**
- ID дашборда `11462` — Traefik v2/v3 Overview
- ID дашборда `13174` — Traefik v3 с поддержкой Gateway API

### Отладка и диагностика

**Проверка статуса Gateway API ресурсов:**

```bash
# Проверка статуса Gateway
kubectl describe gateway external-gw -n traefik

# Проверка статуса HTTPRoute
kubectl describe httproute api-route -n prod

# Проверка привязки маршрутов к Gateway
kubectl get httproute -A -o yaml | grep -A 5 "parentRefs"
```

**Типичные ошибки и их причины:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `GatewayClass not found` | GatewayClass не создан или имя не совпадает | Проверить имя `gatewayClassName` в Gateway |
| `InvalidListener` | Неверная конфигурация listener (порт, протокол) | Проверить спецификацию listener |
| `ConflictingListeners` | Дублирующиеся порты или протоколы | Убедиться в уникальности портов |
| `InvalidBackendRef` | Сервис не найден или порт неверный | Проверить существование сервиса и порта |
| `BackendNotFound` | Указанный backend не существует | Проверить имя сервиса и namespace |
| `RouteReasonResolvedRefs` | Ошибка в ссылках на ресурсы | Проверить `backendRefs` и `certificateRefs` |

**Логи контроллера Gateway:**

```bash
# Просмотр логов Traefik с фильтром по Gateway Provider
kubectl logs -n traefik -l app.kubernetes.io/name=traefik -f | grep "kubernetesgateway"

# Включение debug-логирования
# values.yaml:
logs:
  general:
    level: DEBUG
```

**Проверка конфигурации через API Traefik:**

```bash
# Получение текущей конфигурации
kubectl port-forward -n traefik svc/traefik 9000:9000
curl http://localhost:9000/api/overview
curl http://localhost:9000/api/http/routers
curl http://localhost:9000/api/http/services
```

**Dashboard Traefik:**

```bash
# Проксирование dashboard
kubectl port-forward -n traefik svc/traefik 8080:8080
# Открыть http://localhost:8080/dashboard/
```

### Best Practices

1. **Используйте отдельные Gateway для разных сред:**
   - `external-gw` — для внешнего трафика
   - `internal-gw` — для внутреннего трафика между командами

2. **Ограничивайте allowedRoutes по namespace:**
   ```yaml
   allowedRoutes:
     namespaces:
       from: Selector
       selector:
         matchLabels:
           gateway-access: "true"
   ```

3. **Используйте ReferenceGrant для кросс-namespace ссылок:**
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1beta1
   kind: ReferenceGrant
   metadata:
     name: allow-traefik-wildcard
     namespace: prod
   spec:
     from:
     - group: gateway.networking.k8s.io
       kind: Gateway
       namespace: traefik
     to:
     - group: ""
       kind: Secret
   ```

4. **Мониторьте ключевые метрики:**
   - Латентность запросов (p50, p95, p99)
   - Процент ошибок (5xx)
   - Количество открытых соединений
   - Статус бэкендов

5. **Используйте Circuit Breaker для защиты от каскадных сбоев:**
   - Настройте пороги срабатывания на основе SLO
   - Определите fallback-стратегии

6. **Храните сертификаты в PersistentVolume:**
   - Избегайте повторного запроса сертификатов при рестарте
   - Соблюдайте правила rate limiting Let's Encrypt

7. **Тестируйте конфигурацию в staging-среде:**
   - Используйте `kubectl diff` перед применением
   - Проверяйте статус ресурсов после применения

## Дополнительная информация

### Наблюдаемость (Observability)

Traefik v3 глубоко интегрирован с инструментами мониторинга:
- **Метрики:** Встроенная поддержка Prometheus и OpenTelemetry. Метрики включают статистику по Gateway, Route и Backend.
- **Трассировка:** Поддержка Jaeger, Zipkin и OTLP для анализа сквозного прохождения запросов.
- **Access Logs:** Возможность записи логов в JSON-формате для последующего анализа в ELK/Loki.

### Отладка и диагностика

1. **Dashboard:** Traefik предоставляет веб-интерфейс (порт 8080), где можно визуально проверить состояние Gateway и привязанных к ним маршрутов.
2. **Проверка статуса в K8s:** Gateway API ресурсы имеют секцию `status`, которая содержит детальную информацию о причинах ошибок (например, `ConflictingListeners` или `InvalidBackendRef`).
   ```bash
   kubectl describe gateway external-gw -n traefik
   ```
3. **Логи контроллера:** При проблемах с обновлением конфигурации следует искать ошибки с префиксом `providerName: kubernetesgateway` в логах пода Traefik.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта.
- [L4-маршрутизация — TCPRoute и UDPRoute](./layer4_routing.md) — детали транспортного уровня.
- [Обзор Traefik](../../WebServers/Traefik/traefik_overview.md) — архитектура и общие возможности прокси.
- [Сравнение Ingress-контроллеров](../Ingress/controllers_comparison.md) — технические характеристики контроллеров.
- [Миграция на Gateway API](./migration.md) — пошаговое руководство по переходу с Ingress.
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация Gateway API.

**Родительская тема:** [Gateway API](./definitions.md)
