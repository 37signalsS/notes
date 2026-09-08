# Envoy Gateway — реализация Gateway API

## Определения

**Envoy Gateway (EG)** — официальная реализация спецификации Kubernetes Gateway API от сообщества Envoy Proxy (проект CNCF). EG управляет жизненным циклом инфраструктуры прокси-серверов, преобразуя высокоуровневые манифесты Gateway API в конфигурацию xDS для Data Plane.

**Envoy Proxy** — высокопроизводительный L3/L4/L7 прокси с открытым исходным кодом (C++), разработанный Lyft и переданный в CNCF. Используется как Data Plane в Envoy Gateway. Обеспечивает динамическую конфигурацию через xDS API, поддерживает HTTP/2, HTTP/3 (QUIC), gRPC, WebSocket.

**xDS API** — набор gRPC/REST API для динамической конфигурации Envoy Proxy (LDS, RDS, CDS, EDS, SDS и др.). Control Plane Envoy Gateway генерирует xDS-конфигурацию на основе ресурсов Gateway API и передает ее в Data Plane в runtime без перезапуска прокси.

**Control Plane** — компонент управления, отвечающий за мониторинг ресурсов Gateway API в Kubernetes, валидацию конфигурации, генерацию xDS-конфигурации и управление жизненным циклом подов прокси. В Envoy Gateway реализован как набор контроллеров (Provisioner, Translator, Status Updater).

**Data Plane** — уровень обработки и передачи данных. В Envoy Gateway представляет собой группу прокси-серверов (Envoy), которые получают конфигурацию динамически через xDS API. Обеспечивает терминацию TLS, маршрутизацию, балансировку нагрузки,  health checking.

**Shadow Mode** — режим проверки политик (Rate Limit, Security) без блокировки реального трафика. Включен в Envoy Gateway начиная с v1.8. Позволяет тестировать конфигурации на копии трафика перед применением к production.

**CRD (Custom Resource Definition)** — пользовательские ресурсы Kubernetes, используемые Envoy Gateway для расширения стандартного Gateway API: SecurityPolicy, BackendTrafficPolicy, ClientTrafficPolicy, BackendTLSPolicy и другие. Полное описание политик: [Провайдер-специфичная конфигурация](./provider_specific_config.md).

## Базовые концепции

### Архитектура и управление

Envoy Gateway строго разделяет уровни управления и обработки согласно архитектурным принципам Gateway API:

**Control Plane:**
- Центральный контроллер, развернутый в отдельном namespace (обычно `envoy-gateway-system`)
- Отвечает за мониторинг ресурсов Gateway API (Gateway, HTTPRoute, GRPCRoute, TCPRoute, UDPRoute)
- Генерирует xDS-конфигурацию на основе манифестов
- Управляет жизненным циклом подов Envoy Proxy (создание, масштабирование, обновление)
- Обновляет статусы ресурсов (Status Conditions)

**Data Plane:**
- Группа прокси-серверов (Envoy), развернутых как DaemonSet или Deployment
- Получают конфигурацию динамически через xDS API без перезапуска
- Обеспечивают терминацию TLS, маршрутизацию, балансировку нагрузки
- Поддерживают health checking бэкендов (active, passive, outlier detection)

**Взаимодействие компонентов:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Control Plane                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Provisioner │  │  Translator │  │   Status Updater    │ │
│  │ (инфраструктура)│ │(xDS генерация)│ │  (статусы ресурсов) │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                         │ xDS API (gRPC)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Data Plane                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │  Envoy Pod 1 │  │  Envoy Pod 2 │  │     Envoy Pod N     │ │
│  │  (proxy)     │  │  (proxy)     │  │     (proxy)         │ │
│  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Возможности Envoy Gateway (v1.8)

**Управление трафиком:**
- Полная поддержка спецификации Gateway API v1.6+
- HTTPRoute, GRPCRoute, TCPRoute, UDPRoute
- Canary deployments, Blue-Green deployments через весовые маршруты
- Request mirroring, Request redirect, URL rewrite, Header modification

**Безопасность:**
- SecurityPolicy: JWT-аутентификация, CORS, OIDC, API Key
- ClientTrafficPolicy: управление TLS-клиентами, HTTP/2, HTTP/3, gRPC-Web
- BackendTrafficPolicy: таймауты, ретрии, Circuit Breaker, алгоритмы балансировки
- BackendTLSPolicy: безопасное соединение с бэкендами (mTLS)

**Наблюдаемость:**
- Встроенные метрики Prometheus (совместимые с Envoy stats)
- Расширенные access logs с настраиваемым форматом
- Distributed tracing (OpenTelemetry, Jaeger, Zipkin)
- Admin interface Envoy для диагностики (порт 19000)

**Shadow Mode (начиная с v1.8):**
- Проверка политик Rate Limit и Security на копии трафика
- Отсутствие влияния на production-трафик
- Возможность анализа потенциальных блокировок до применения политик

### Интеграция и безопасность

**SecurityPolicy:**
- JWT-аутентификация с поддержкой множества провайдеров
- CORS-политики для кросс-доменных запросов
- OIDC-интеграция для SSO

**ClientTrafficPolicy:**
- Управление параметрами TLS-клиента
- Поддержка HTTP/2, HTTP/3, gRPC-Web
- Настройка keep-alive, timeouts

**BackendTrafficPolicy:**
- Тонкая настройка взаимодействия с бэкендами
- Таймауты, ретрии, Circuit Breaker
- Алгоритмы балансировки: Round Robin, Least Request, Ring Hash, Maglev, Random
- Health checking: active (HTTP/TCP), passive (outlier detection)

**Политики и Policy Attachment:**
Детальное описание механизмов прикрепления политик (Direct Policy, Inherited Policy, TargetRef) и практические примеры: [Провайдер-специфичная конфигурация](./provider_specific_config.md).

## Практические сценарии

### Предварительные требования

- Kubernetes кластер версии 1.27+
- kubectl настроен для работы с кластером
- Helm 3.12+ (для установки через Helm)
- Доступ к репозиторию Envoy Gateway

### Установка через Helm (v1.8)

В версии 1.8 CRD вынесены в отдельный sub-chart для обхода ограничений Helm на размер секретов.

```bash
# Добавление репозитория
helm repo add envoygateway https://envoyproxy.github.io/gateway-helm/
helm repo update

# Установка (актуально на июль 2026)
helm install eg envoygateway/gateway-helm \
  --version v1.8.0 \
  -n envoy-gateway-system \
  --create-namespace
```

### Проверка установки

```bash
# Проверка статуса подов
kubectl get pods -n envoy-gateway-system

# Ожидаемый вывод:
# NAME                                          READY   STATUS    RESTARTS   AGE
# envoys-gateway-eg-6c8f9b5d4-abcde             1/1     Running   0          2m

# Проверка GatewayClass
kubectl get gatewayclass

# Ожидаемый вывод:
# NAME          CONTROLLER                                        AGE
# eg            gateway.envoyproxy.io/gatewayclass-controller      2m
```

### Настройка Gateway и HTTPRoute

Базовая конфигурация для маршрутизации HTTP-трафика:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gateway
  namespace: default
spec:
  gatewayClassName: eg
  listeners:
  - name: http
    protocol: HTTP
    port: 80
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: tls-secret
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app-route
  namespace: default
spec:
  parentRefs:
  - name: external-gateway
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api
    backendRefs:
    - name: api-service
      port: 8080
      weight: 100
```

### Настройка политики безопасности (SecurityPolicy)

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: jwt-auth-policy
  namespace: default
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  jwt:
    providers:
    - name: auth0
      issuer: https://auth.example.com/
      audiences: ["api-v1"]
      remoteJWKS:
        uri: https://auth.example.com/.well-known/jwks.json
```

### Настройка BackendTrafficPolicy (устойчивость)

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata:
  name: api-resiliency
  namespace: default
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: app-route
  circuitBreaker:
    maxConnections: 1000
    maxPendingRequests: 100
  retry:
    numRetries: 3
    retryOn: [5xx, gateway-error]
    perTryTimeout: 2s
```

### Диагностика и мониторинг

```bash
# Проверка статуса Gateway
kubectl describe gateway external-gateway -n default

# Проверка статуса HTTPRoute
kubectl describe httproute app-route -n default

# Просмотр логов Control Plane
kubectl logs -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=external-gateway

# Просмотр логов Data Plane (Envoy)
kubectl logs -n envoy-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=external-gateway -c envoy

# Admin interface Envoy (порт 19000)
kubectl port-forward -n envoy-gateway-system pod/<envoy-pod-name> 19000:19000

# Получение конфигурации Envoy (через admin interface)
curl http://localhost:19000/config_dump

# Получение статистики Envoy
curl http://localhost:19000/stats/prometheus
```

### Использование Shadow Mode для тестирования политик

```yaml
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata:
  name: shadow-rate-limit
  namespace: default
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: external-gateway
  rateLimit:
    type: Global
    global:
      rules:
      - clientSelectors:
        - headers:
          - name: x-user-id
            value: test-user
        limit:
          requests: 100
          unit: Hour
      shadowMode: true  # Политика активна только в shadow mode
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway not programmed` | Контроллер не установлен или не работает | Проверить статус подов: `kubectl get pods -n envoy-gateway-system` |
| `ResolvedRefs: False` | Отсутствует ReferenceGrant для кросс-namespace ссылок | Создать ReferenceGrant в namespace целевого ресурса |
| `Accepted: False` на Listener | Неверная конфигурация TLS или сертификат не найден | Проверить существование Secret с сертификатом |
| Высокая задержка (latency) | Неоптимальные настройки BackendTrafficPolicy | Настроить таймауты и Circuit Breaker |
| 503 ошибки | Бэкенды недоступны или не проходят health check | Проверить статус подов бэкендов и health check конфигурацию |

### Диагностика проблем с конфигурацией

```bash
# Проверка статуса всех ресурсов Gateway API
kubectl get gateway,httproute,gatewayclass,referencegrant -A

# Детальная информация о Gateway с условиями
kubectl get gateway external-gateway -n default -o jsonpath='{.status.conditions[*]}'

# Проверка xDS конфигурации через admin interface
curl http://localhost:19000/config_dump | jq '.configs[]'

# Проверка статуса подключения к xDS серверу
curl http://localhost:19000/server_info | jq '.state'

# Просмотр статистики по upstream кластерам
curl http://localhost:19000/stats | grep "cluster.backend"
```

### Диагностика проблем с TLS

```bash
# Проверка наличия TLS-секретов
kubectl get secrets -n default -o json | jq '.items[] | select(.type == "kubernetes.io/tls") | .metadata.name'

# Проверка статуса Listener с TLS
kubectl get gateway external-gateway -n default -o jsonpath='{.status.listeners[?(@.name=="https")].conditions}'

# Проверка сертификата через OpenSSL (из подов Envoy)
kubectl exec -n envoy-gateway-system <envoy-pod> -- openssl s_client -connect localhost:443 -servername app.example.com
```

## Best Practices

### Организация инфраструктуры

1. **Используйте отдельные Gateway для разных сред:**
   - production-gateway, staging-gateway, dev-gateway
   - Изолирует трафик и упрощает управление

2. **Применяйте принцип наименьших привилегий:**
   - Разработчики управляют только Route в своих namespace
   - Операторы управляют Gateway и сертификатами

3. **Используйте отдельные namespace для разных команд:**
   - Обеспечивает изоляцию и контроль доступа через RBAC

### Безопасность

1. **Всегда используйте TLS:**
   - Настройте терминацию TLS на Gateway
   - Используйте cert-manager для автоматизации сертификатов
   - Включите HSTS через SecurityPolicy

2. **Защищайте соединения с бэкендами:**
   - Используйте BackendTLSPolicy для mTLS
   - Настройте ClientTrafficPolicy для управления TLS-параметрами

3. **Аудит и мониторинг:**
   - Настройте алерты на изменения статусов Gateway API ресурсов
   - Мониторьте метрики Envoy через Prometheus

### Производительность

1. **Оптимизируйте настройки BackendTrafficPolicy:**
   - Настройте Circuit Breaker для защиты бэкендов
   - Используйте подходящие алгоритмы балансировки (Least Request для разнородных бэкендов)

2. **Используйте Shadow Mode для тестирования:**
   - Проверяйте политики Rate Limit и Security до применения к production
   - Анализируйте логи shadow mode для выявления потенциальных проблем

3. **Мониторинг метрик Envoy:**
   - Настройте дашборды Grafana для визуализации метрик
   - Следите за upstream_cx_active, upstream_rq_time, upstream_rq_5xx

## Дополнительная информация

**Версионирование:** Актуальная версия Envoy Gateway — v1.8.x (2026). Поддерживает Gateway API v1.6+.

**Сравнение с другими реализациями:**

| Характеристика | Envoy Gateway | Другие реализации |
| :--- | :--- | :--- |
| **Data Plane** | Envoy Proxy (C++) | Traefik, NGINX, Istio (Envoy) |
| **Статус CNCF** | Официальный проект | Различные |
| **Производительность** | Высокая (General Purpose) | Зависит от реализации |
| **Наблюдаемость** | Расширенная (Envoy stats) | Зависит от реализации |

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые определения и архитектура
- [Провайдер-специфичная конфигурация](./provider_specific_config.md) — детальное описание политик (BackendTrafficPolicy, SecurityPolicy)
- [KGateway](./kgateway.md) — альтернативная реализация с поддержкой OpenTelemetry
- [Traefik](./traefik.md) — реализация с нативной поддержкой v3.x
- [Ресурсы (CRD)](./resources.md) — обзор стандартных объектов Gateway API
- [Миграция с Ingress](./migration.md) — пошаговое руководство по переходу

**Родительская тема:** [Gateway API](./definitions.md)

**Официальная документация:** [Envoy Gateway Documentation](https://gateway.envoyproxy.io/).
