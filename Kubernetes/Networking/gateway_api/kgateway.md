# KGateway — реализация Gateway API

## Определения

**KGateway** — контроллер Gateway API с открытым исходным кодом, являющийся эволюционным продолжением Gloo Gateway (разработка Solo.io). Проект ориентирован на высоконагруженные среды и мультикластерные конфигурации, предоставляя расширенную реализацию спецификации Kubernetes Gateway API.

**Data Plane** — уровень передачи данных. KGateway v2.3+ поддерживает гибридную модель обработки трафика, позволяя выбирать оптимальный прокси для конкретных задач:

1. **Envoy Proxy (C++):** основной промышленный стандарт для традиционного North-South трафика. Используется для сложных L7-правил, Rate Limiting и TLS-терминации.
2. **AgentGateway (Rust):** высокопроизводительный Data Plane следующего поколения с минимальным оверхедом, предназначенный для edge-развертываний и сценариев с большим количеством параллельных соединений.

**Control Plane** — центральный контроллер, отвечающий за мониторинг ресурсов Gateway API, генерацию конфигурации прокси и управление жизненным циклом подов.

## Базовые концепции

### Архитектура и управление

KGateway строго разделяет уровни управления и обработки трафика:

- **Control Plane:** отслеживает изменения ресурсов Gateway API в Kubernetes API-сервере, валидирует конфигурации и распространяет их на прокси-серверы.
- **Data Plane:** группа прокси-серверов (Envoy или AgentGateway), которые получают конфигурацию динамически и обрабатывают трафик согласно правилам Gateway API.

### Поддержка Gateway API

KGateway реализует полный набор ресурсов Gateway API:

- **GatewayClass:** определяет класс шлюза и связывает его с конкретным контроллером.
- **Gateway:** описывает точку входа трафика (listeners, TLS, привязку к портам).
- **HTTPRoute:** L7-маршрутизация на основе путей, заголовков, методов и query-параметров.
- **GRPCRoute:** маршрутизация gRPC-трафика на уровне методов.
- **TCPRoute/UDPRoute:** L4-маршрутизация транспортного уровня.
- **TLSRoute:** маршрутизация TLS-трафика на уровне SNI.

### Механизмы безопасности

KGateway предоставляет расширенные политики безопасности через специфичные CRD:

- **SecurityPolicy:** настройка JWT-валидации (несколько провайдеров), CORS, OIDC-аутентификации.
- **ClientTrafficPolicy:** управление параметрами TLS-клиента, HTTP/2, HTTP/3 и специфичными настройками gRPC-Web.
- **BackendTrafficPolicy:** тонкая настройка взаимодействия с бэкендами (таймауты, ретрии, алгоритмы балансировки).

### Мультикластерная маршрутизация

KGateway поддерживает сценарии мультикластерного развертывания:

- Единая точка входа для сервисов, распределенных между несколькими кластерами.
- Автоматическое обнаружение сервисов через Federation API.
- Балансировка трафика между кластерами с учетом геолокации и доступности.

## Практические сценарии

### Установка и подготовка окружения

Для развертывания используется OCI-репозиторий. Важно разделять установку CRD и самого контроллера для стабильности в CI/CD пайплайнах.

```bash
# Установка CRD (включая специфичные ресурсы kgateway.dev)
helm upgrade -i kgateway-crds oci://cr.kgateway.dev/kgateway-dev/charts/kgateway-crds \
  --version v2.3.4 \
  --namespace kgateway-system \
  --create-namespace

# Установка Control Plane
helm upgrade -i kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
  --version v2.3.4 \
  --namespace kgateway-system
```

**Проверка установки:**

```bash
# Проверка статуса подов
kubectl get pods -n kgateway-system
# → NAME                        READY   STATUS    RESTARTS   AGE
# → kgateway-5d4b6c8f9-abc12    2/2     Running   0          2m

# Проверка установленных CRD
kubectl get crd | grep kgateway
# → backends.gateway.kgateway.dev
# → gatewayconfigs.gateway.kgateway.dev
```

### Настройка GatewayClass и Gateway

GatewayClass определяет класс шлюза и связывает его с контроллером KGateway:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: kgateway
spec:
  controllerName: gateway.kgateway.dev/kgateway
  description: KGateway — контроллер Gateway API на базе Envoy
```

Gateway описывает точку входа трафика с настройкой listeners и TLS:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: kgateway-system
spec:
  gatewayClassName: kgateway
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
  - name: http
    protocol: HTTP
    port: 80
    allowedRoutes:
      namespaces:
        from: All
```

### L7-маршрутизация с HTTPRoute

HTTPRoute определяет правила маршрутизации на основе путей, заголовков и методов:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: kgateway-system
  hostnames:
  - api.example.com
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api/v1 }
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add:
        - name: X-Forwarded-Proto
          value: https
    backendRefs:
    - name: api-v1-service
      port: 8080
      weight: 100
  - matches:
    - path: { type: PathPrefix, value: /api/v2 }
    backendRefs:
    - name: api-v2-service
      port: 8080
```

**Канареечное развертывание с взвешенной маршрутизацией:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: kgateway-system
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api }
    backendRefs:
    - name: api-stable
      port: 8080
      weight: 90
    - name: api-canary
      port: 8080
      weight: 10
```

### Маршрутизация gRPC

KGateway поддерживает нативную маршрутизацию gRPC на уровне методов:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: grpc-service
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: kgateway-system
  rules:
  - matches:
    - method:
        service: com.example.UserService
        method: GetUser
    backendRefs:
    - name: user-service
      port: 9000
  - matches:
    - method:
        service: com.example.UserService
        method: CreateUser
    backendRefs:
    - name: user-service
      port: 9000
```

### TLS и управление сертификатами

**Настройка TLS с автоматическим обновлением сертификатов:**

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: tls-gateway
  namespace: kgateway-system
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: kgateway
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: tls-secret
    allowedRoutes:
      namespaces:
        from: All
```

**Создание Secret с сертификатом:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: tls-secret
  namespace: kgateway-system
type: kubernetes.io/tls
data:
  tls.crt: <base64-encoded-certificate>
  tls.key: <base64-encoded-private-key>
```

### Политики безопасности

**Настройка JWT-аутентификации:**

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: SecurityPolicy
metadata:
  name: jwt-auth
  namespace: prod
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: api-route
  jwt:
    providers:
    - name: auth0
      issuer: https://auth.example.com/
      audiences:
      - api.example.com
      remoteJwks:
        url: https://auth.example.com/.well-known/jwks.json
```

**Настройка CORS:**

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: SecurityPolicy
metadata:
  name: cors-policy
  namespace: prod
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gw
  cors:
    allowOrigins:
    - exact: https://app.example.com
    - regex: https://.*\.example\.com
    allowMethods:
    - GET
    - POST
    - PUT
    - DELETE
    allowHeaders:
    - Authorization
    - Content-Type
    maxAge: 3600s
```

### Управление трафиком бэкендов

**Настройка таймаутов и ретриев:**

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: backend-policy
  namespace: prod
spec:
  targetRef:
    group: ""
    kind: Service
    name: api-service
  timeout:
    request: 30s
    backendRequest: 10s
  retry:
    numRetries: 3
    perTryTimeout: 5s
    retryOn:
    - gateway-error
    - connect-failure
    - refused-stream
```

### L4-маршрутизация (TCP/UDP)

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TCPRoute
metadata:
  name: tcp-route
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: kgateway-system
  rules:
  - backendRefs:
    - name: tcp-service
      port: 5432
```

## Дополнительная информация

### Мониторинг и метрики

KGateway экспортирует метрики в формате Prometheus через встроенный endpoint:

**Основные метрики Gateway API:**

| Метрика | Описание | Тип |
|:---|:---|:---|
| `kgateway_gateway_requests_total` | Общее количество запросов через Gateway | Counter |
| `kgateway_httproute_requests_total` | Количество запросов по HTTPRoute | Counter |
| `kgateway_backend_requests_total` | Количество запросов к бэкендам | Counter |
| `kgateway_backend_latency_seconds` | Латентность запросов к бэкендам | Histogram |
| `kgateway_backend_server_up` | Статус доступности бэкенда (0/1) | Gauge |

**Настройка ServiceMonitor:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kgateway
  namespace: kgateway-system
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kgateway
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

**Включение метрик через Helm values:**

```yaml
# values.yaml
metrics:
  enabled: true
  port: 9090
  path: /metrics
```

### Отладка и диагностика

**Проверка статуса ресурсов:**

```bash
# Проверка статуса Gateway
kubectl describe gateway external-gw -n kgateway-system
# → Status:
# →   Conditions:
# →     Type:   Programmed
# →     Status: True

# Проверка статуса HTTPRoute
kubectl describe httproute api-route -n prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Type:   ResolvedRefs
# →       Status: True
```

**Типичные ошибки и их причины:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `GatewayClass not found` | GatewayClass не создан или имя не совпадает | Проверить имя `gatewayClassName` в Gateway |
| `InvalidListener` | Неверная конфигурация listener (порт, протокол) | Проверить спецификацию listener |
| `CertificateNotFound` | Secret с сертификатом не найден | Проверить существование Secret и имени в `certificateRefs` |
| `BackendNotFound` | Указанный сервис не существует | Проверить имя сервиса и namespace |
| `JWTProviderInvalid` | Неверная конфигурация JWT-провайдера | Проверить URL JWKS и issuer |

**Просмотр логов контроллера:**

```bash
# Логи контроллера KGateway
kubectl logs -n kgateway-system -l app.kubernetes.io/name=kgateway -f

# Включение debug-логирования
helm upgrade kgateway oci://cr.kgateway.dev/kgateway-dev/charts/kgateway \
  --set logLevel=debug \
  --namespace kgateway-system
```

**Проверка конфигурации Envoy:**

```bash
# Получение текущей конфигурации Envoy через admin interface
kubectl port-forward -n kgateway-system svc/kgateway 19000:19000
curl http://localhost:19000/config_dump
curl http://localhost:19000/clusters
```

### Best Practices

1. **Разделяйте Gateway по окружениям:**
   - Используйте отдельные Gateway для production и staging.
   - Применяйте `allowedRoutes` для ограничения доступа к namespace.

2. **Ограничивайте доступ к Gateway через ReferenceGrant:**
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1beta1
   kind: ReferenceGrant
   metadata:
     name: allow-kgateway-wildcard
     namespace: prod
   spec:
     from:
     - group: gateway.networking.k8s.io
       kind: Gateway
       namespace: kgateway-system
     to:
     - group: ""
       kind: Secret
   ```

3. **Используйте BackendTrafficPolicy для настройки таймаутов:**
   - Задавайте `backendRequest` меньше, чем клиентский таймаут.
   - Настраивайте ретрии только для идемпотентных операций.

4. **Мониторьте ключевые метрики:**
   - Латентность запросов (p50, p95, p99).
   - Процент ошибок (5xx).
   - Статус бэкендов.

5. **Применяйте канаеечное развертывание:**
   - Начинайте с малого веса (5-10%) для новой версии.
   - Увеличивайте вес постепенно при успешных метриках.

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта.
- [L4-маршрутизация — TCPRoute и UDPRoute](./layer4_routing.md) — детали работы на транспортном уровне.
- [Сравнение Ingress-контроллеров](../Ingress/controllers_comparison.md) — технические характеристики контроллеров.
- [Envoy Gateway](./envoy_gateway.md) — альтернативная реализация на базе Envoy.
- [Traefik](./traefik.md) — реализация с нативной поддержкой v3.x.

**Родительская тема:** [Gateway API](./definitions.md)
