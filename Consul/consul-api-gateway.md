# Consul API Gateway

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x / 1.18.x

## Определения

**Consul API Gateway** — это специализированное решение для управления внешним трафиком (North-South), которое заменяет устаревший Ingress Gateway. Оно построено на базе **Envoy** и реализует спецификацию **Kubernetes Gateway API**, обеспечивая бесшовную интеграцию внешнего мира с Consul Service Mesh.

В Consul 2.0 представлено два контроллера API Gateway:

- **Standard API gateway** — контроллер по умолчанию в API group `gateway.networking.k8s.io/v1`. Рекомендуется для всех новых установок, когда платформа управляет CRD Gateway API и поддерживает стабильные версии.
- **Consul API gateway** — контроллер в API group `consul.hashicorp.com/v1beta1`. Используется, когда платформа управляет CRD и поддерживает только стабильный v1, или когда требуется `TCPRoute` в условиях ограниченной поддержки Gateway API.

В отличие от классического Ingress, API Gateway использует ролевую модель управления, разделяя ответственность между администраторами инфраструктуры (создание шлюзов) и разработчиками приложений (определение маршрутов).

## Архитектура и интеграция с Kubernetes

API Gateway работает как контроллер внутри Kubernetes, который отслеживает ресурсы Gateway API и транслирует их в конфигурацию прокси-серверов Envoy.

### Ключевые ресурсы (CRD)

| Ресурс | API group | Версия | Описание |
| :--- | :--- | :--- | :--- |
| **GatewayClass** | `gateway.networking.k8s.io` или `consul.hashicorp.com` | v1 / v1beta1 | Шаблон для создания шлюзов. |
| **Gateway** | `gateway.networking.k8s.io` или `consul.hashicorp.com` | v1 / v1beta1 | Физическая точка входа (порты, TLS-сертификаты). |
| **HTTPRoute** | `gateway.networking.k8s.io` или `consul.hashicorp.com` | v1 / v1beta1 | Правила маршрутизации HTTP (пути, заголовки, фильтры). |
| **TCPRoute** | `gateway.networking.k8s.io` или `consul.hashicorp.com` | v1 / v1alpha2 | Правила маршрутизации TCP (L4). |
| **GRPCRoute** | `gateway.networking.k8s.io` или `consul.hashicorp.com` | v1 / v1alpha2 | Правила маршрутизации gRPC. |
| **ReferenceGrant** | `gateway.networking.k8s.io` | v1beta1 | Разрешение на использование ресурсов из других неймсейсов. |
| **GatewayClassConfig** | `consul.hashicorp.com` | v1beta1 | Дополнительная конфигурация класса шлюза (порты, автоскейлинг). |

### Механизм работы

1. **Контроллер** обнаруживает новый ресурс `Gateway` с обязательной меткой `component: api-gateway` (Standard) или `component: api-gateway-consul` (Consul API gateway).
2. Consul развертывает **Deployment** с Envoy-прокси (`consul-dataplane`) и сервис типа `LoadBalancer`.
3. Разработчик создает `HTTPRoute`, `TCPRoute` или `GRPCRoute`, привязывая его к `Gateway` через `parentRefs`.
4. Envoy-прокси автоматически получает конфигурацию через xDS и направляет внешний трафик в Service Mesh, используя **mTLS** для общения с внутренними сервисами.

### Порты и требования

| Порт | Описание | Компонент |
| :--- | :--- | :--- |
| **21000** | Readiness probe (`/ready` over HTTP) | Pod шлюза |
| **19000** | Envoy admin interface (localhost only) | Pod шлюза |
| **20200** | Prometheus метрики (отключен по умолчанию) | Pod шлюза |

## Предварительные требования

- **Kubernetes** с поддержкой Gateway API CRDs (версия зависит от выбранного контроллера).
- **HashiCorp Consul Helm chart** v1.2.0 и выше.
- **Consul servers** должны быть установлены и доступны из кластера Kubernetes.
- **ACL** (если включен): токен с правами на управление ресурсами Gateway API и конфигурационными записями.
- **TLS-сертификаты** для termination на шлюзе (core/v1/Secret или SDS).
- **Сетевая связность** между Kubernetes и Consul datacenter на портах 8300, 8500, 8600.

## Практические сценарии

### 1. Включение API Gateway (Helm)

API Gateway включается в `values.yaml` чарта `consul-k8s`. Выбор контроллера зависит от возможностей платформы.

```yaml
# Standard API gateway (рекомендуется по умолчанию)
global:
  installK8sNetworkingCRDs: true
  crds:
    enableTcpRoute: true
connectInject:
  enabled: true
  apiGateway:
    manageExternalCRDs: true
```

```yaml
# Consul API gateway (когда CRD управляются внешне и доступен только v1)
global:
  installK8sNetworkingCRDs: false
  crds:
    consulapi:
      enabled: true
connectInject:
  enabled: true
  apiGateway:
    manageExternalCRDs: true
```

### 2. Создание шлюза (Gateway)

Пример для Standard API gateway. Метка `component: api-gateway` обязательна для распознавания контроллером.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: consul
  labels:
    component: api-gateway
spec:
  gatewayClassName: consul
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: "api.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - name: example-com-cert
    allowedRoutes:
      namespaces:
        from: All
```

### 3. Маршрутизация с разделением трафика (Canary)

Пример `HTTPRoute`, который направляет 90% трафика на стабильную версию и 10% на новую.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: apps
spec:
  parentRefs:
  - name: public-gateway
    namespace: consul
  hostnames:
  - "api.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /v1
    backendRefs:
    - name: service-stable
      port: 8080
      weight: 90
    - name: service-canary
      port: 8080
      weight: 10
```

### 4. L4-маршрутизация (TCPRoute)

`TCPRoute` позволяет проксировать TCP-трафик, например, к базам данных или legacy-сервисам.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TCPRoute
metadata:
  name: tcp-route
  namespace: apps
spec:
  parentRefs:
  - name: public-gateway
    namespace: consul
  rules:
  - backendRefs:
    - name: postgres-service
      port: 5432
```

### 5. gRPC-маршрутизация (GRPCRoute)

Для gRPC-сервисов можно использовать `GRPCRoute` для явного указания методов и сервисов.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: grpc-route
  namespace: apps
spec:
  parentRefs:
  - name: public-gateway
    namespace: consul
  hostnames:
  - "grpc.example.com"
  rules:
  - matches:
    - method:
        type: Exact
        value: "/package.Service/Get"
    backendRefs:
    - name: grpc-service
      port: 50051
```

### 6. Cross-namespace Routing (ReferenceGrant)

`ReferenceGrant` необходим, когда `Gateway` или маршрут ссылается на ресурсы (секреты, сервисы) из других неймсейсов.

```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-cert-from-apps
  namespace: consul
spec:
  from:
  - group: ""
    kind: Secret
    namespace: apps
  to:
  - group: ""
    kind: Secret
    namespace: consul
```

## Проверка и валидация

После применения манифестов проверяйте статус ресурсов.

### Проверка статуса шлюза

```bash
kubectl get gateway public-gateway -n consul -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# → True
```

### Проверка привязки маршрута

```bash
kubectl get httproute api-route -n apps -o jsonpath='{.status.parents[*].conditions[?(@.type=="Accepted")].status}'
# → True
```

### Проверка адресов шлюза

```bash
kubectl get gateway public-gateway -n consul -o jsonpath='{.status.addresses[*].value}'
# → <внешний_IP_или_имя_хоста>
```

### Проверка Pod шлюза

```bash
kubectl get pods -n consul -l component=api-gateway
# → NAME READY STATUS RESTARTS AGE
```

### Проверка метрик Envoy

```bash
kubectl port-forward -n consul svc/<gateway-service> 20200:20200
curl -s http://localhost:20200/stats/prometheus | head -n 5
# → # HELP ...
```

### Проверка логов контроллера

```bash
kubectl logs -l app=consul-api-gateway-controller -n consul --tail=100
# → последние 100 строк логов
```

## Продвинутые возможности

- **Cross-namespace Routing**: Использование `ReferenceGrant` позволяет безопасно ссылаться на сервисы или секреты в разных неймсейсах Kubernetes.
- **TLS SDS (Secret Discovery Service)**: Поддержка динамического обновления сертификатов без перезагрузки подов прокси.
- **TCPRoute**: Возможность проксирования L4-трафика (например, для баз данных) с поддержкой TLS Passthrough.
- **GRPCRoute**: Явная маршрутизация gRPC-запросов по методу и сервису.
- **GatewayClassConfig**: Настройка портов, лимитов и поведения шлюза через параметры `parametersRef`.
- **Автоскейлинг (Enterprise)**: В Consul 2.0 максимальное количество инстансов шлюза не ограничено 8; поддерживается Kubernetes HPA.
- **JWT и ExtAuthz**: Верификация JWT на уровне слушателя и маршрута; внешняя авторизация через Envoy External Authorization filter (Enterprise).
- **Route-level лимиты**: Настройка `MaxConnections`, `MaxPendingRequests`, `MaxConcurrentRequests` на уровне маршрута или gateway-wide defaults.

## Устранение неполадок (Troubleshooting)

### Проверка статуса шлюза

Если трафик не проходит, проверьте статус ресурса `Gateway`:

```bash
kubectl get gateway public-gateway -n consul -o yaml
# Ищите секцию status.conditions. Должно быть Ready: True
```

### Проверка привязки маршрута

Убедитесь, что `HTTPRoute` успешно "принят" шлюзом:

```bash
kubectl get httproute api-route -n apps -o yaml
# В секции status.parents должно быть Accepted: True
```

### Логи контроллера

Если ресурсы не создаются, проверьте логи пода `consul-api-gateway-controller`:

```bash
kubectl logs -l app=consul-api-gateway-controller -n consul
# → последние события контроллера
```

### Проблемы с TLS

Если шлюз не стартует с TLS-ошибками:

```bash
kubectl describe gateway public-gateway -n consul
# Ищите события с типом TLSConfigurationError или UnsupportedTLSCipher
```

### Проблемы с ReferenceGrant

Если маршрут не привязывается из-за чужого неймсейса:

```bash
kubectl get httproute api-route -n apps -o jsonpath='{.status.parents[*].conditions[?(@.reason=="RefNotPermitted")].message}'
# → сообщение о необходимости ReferenceGrant
```

### Проблемы с пробами

Не изменяйте путь `/ready` или порт `21000` для ловушек. Envoy слушает только этот путь на этом порту:

```bash
kubectl describe gateway public-gateway -n consul
# Если probe настроен неправильно — pod будет в CrashLoopBackOff
```

## Лучшие практики

- **Используйте Standard API gateway** по умолчанию для новых установок. Переходите на Consul API gateway только при ограничениях платформы.
- **Обязательная метка**: Убедитесь, что `Gateway` содержит метку `component: api-gateway` (Standard) или `component: api-gateway-consul` (Consul API gateway), иначе контроллер проигнорирует ресурс.
- **Секреты в отдельном неймсейсе**: Для TLS-сертификатов создавайте `ReferenceGrant`, если `Gateway` и `Secret` находятся в разных неймсейсах.
- **SDS вместо статических сертификатов**: Предпочитайте SDS для динамического обновления сертификатов без перезагрузки пода.
- **Ограничение ресурсов**: Задавайте `resources.limits` для пода шлюза, так как Envoy может потреблять значительную память при большом количестве маршрутов.
- **Мониторинг**: Включите метрики на порту `20200` через аннотации или `GatewayClassConfig` для сбора RED-метрик (Requests, Errors, Duration).
- **HPA**: Настройте `HorizontalPodAutoscaler` на основе метрик CPU/memory или кастомных метрик Envoy для обработки пиков.
- **Версия Gateway API**: Убедитесь, что версия CRD Gateway API совместима с выбранным контроллером. Standard API gateway требует `gateway.networking.k8s.io/v1`.
- **Сеть**: Разместите шлюз в неймсейсе, близком к сервисам, чтобы минимизировать задержку внутри кластера.

## Граничные случаи

- **Ограничение CRD платформой**: Если платформа управляет CRD Gateway API и предоставляет только `gateway.networking.k8s.io/v1` без `TCPRoute`, используйте Consul API gateway (`consul.hashicorp.com`), так как Standard API gateway не поддерживает `TCPRoute` в этой конфигурации.
- **Отсутствие TCPRoute в Standard API gateway**: При использовании Standard API gateway на платформах с CRD версии ниже 1.6.0 `TCPRoute` недоступен. В этом случае необходим Consul API gateway.
- **SNI не поддерживается**: `Gateway` ресурс не поддерживает SNI-матчинг на уровне слушателя. Для TLS-маршрутизации по SNI используйте `TLSRoute` (если доступен в вашей версии Gateway API) или отдельные слушатели с разными портами.
- **OpenShift**: Для OpenShift 4.19+ доступны новые ресурсы в `consul.hashicorp.com` API group. Для более старых версий используйте Standard API gateway с параметром `openshift.enabled: true`.
- **HPA и максимальное число инстансов**: В Consul 2.0 лимит в 8 инстансов снят. В более старых версиях (до 2.0) необходимо вручную настраивать `defaultInstances` в `GatewayClassConfig`.
- **WAN Federation**: API Gateway не поддерживает маршрутизацию через WAN federation. Для межкластерного трафика используйте peered connections.
- **При большом количестве маршрутов (>1000)**: Monitor memory usage пода шлюза, так как каждый маршрут добавляет нагрузку на конфигурацию Envoy.

## Дополнительная информация

- **[Consul Service Mesh](./consul_service_mesh.md)** — архитектура внутренней сети.
- **[Управление трафиком L7](./consul_service_mesh.md#управление-трафиком-l7-router-splitter-resolver)** — аналогичные механизмы внутри сетки.
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md)** — управление конфигурацией как кодом.
- **[Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/)** — официальная спецификация.
- **[Consul API Gateway tech specs](https://developer.hashicorp.com/consul/docs/north-south/api-gateway/k8s/tech-specs)** — порты, пробы и требования.
- **[Consul API Gateway config entry](https://developer.hashicorp.com/consul/docs/reference/config-entry/api-gateway)** — конфигурационная запись `api-gateway`.
