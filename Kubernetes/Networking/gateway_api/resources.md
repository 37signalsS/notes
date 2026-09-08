# Gateway API — Ресурсы (CRD)

## Определения

**Custom Resource Definition (CRD)** — фундаментальный механизм расширения API Kubernetes, позволяющий определять собственные типы ресурсов. Gateway API полностью реализован на базе CRD, что позволяет сетевому стандарту развиваться независимо от циклов выпуска ядра Kubernetes, обеспечивая быструю адаптацию к новым протоколам (HTTP/3, gRPC) и современным нагрузкам.

**Gateway API Resources** — иерархическая объектная модель, предназначенная для управления входящим (North-South) и мессервисным (GAMMA) трафиком. Она заменяет монолитный ресурс Ingress на набор специализированных объектов, обеспечивая четкое разделение ответственности (Separation of Concerns).

**Status Conditions** — встроенный механизм обратной связи, позволяющий отслеживать состояние ресурсов через поле `status` в манифестах. Каждый ресурс Gateway API имеет набор условий, отражающих его текущее состояние.

## Базовые концепции

### Версионирование спецификации

Gateway API использует систему каналов (Channels) для управления стабильностью ресурсов:

| Канал | Описание | Стабильность |
|:---|:---|:---|
| **Standard** | Стабильные ресурсы, гарантирующие переносимость между реализациями | GA (General Availability) |
| **Experimental** | Новые функции, находящиеся в стадии тестирования | Alpha/Beta |

Начиная с версии v1.5, основные ресурсы считаются стабильными (GA). Актуальная версия спецификации на середину 2026 года — **v1.6.x**.

### Типы ресурсов по области видимости

| Тип | Ресурсы | Описание |
|:---|:---|:---|
| **Cluster-scoped** | `GatewayClass` | Доступны во всем кластере без привязки к namespace |
| **Namespaced** | `Gateway`, `HTTPRoute`, `GRPCRoute`, `TLSRoute`, `TCPRoute`, `UDPRoute`, `ReferenceGrant`, `BackendTLSPolicy` | Привязаны к конкретному namespace |

### Основные ресурсы (Standard Channel v1.6+)

#### 1. GatewayClass (Cluster-scoped)

Декларативное описание реализации шлюза. Поле `spec.controllerName` связывает ресурс с конкретным контроллером. Позволяет задавать глобальные параметры через `spec.parametersRef`. Является современной заменой `IngressClass`.

**Ключевые поля:**
- `spec.controllerName` — идентификатор контроллера (например, `gateway-envoyproxy.io/gateway-controller`)
- `spec.parametersRef` — ссылка на параметры конфигурации (например, ConfigMap)
- `spec.description` — человекочитаемое описание

**Статусы:**
- `Accepted` — контроллер признает этот GatewayClass

#### 2. Gateway (Namespaced)

Описание физической или виртуальной точки входа трафика. Содержит слушателей (`listeners`), определяющих протоколы (HTTP, HTTPS, TLS, TCP, UDP) и порты. Управляет безопасностью через `certificateRefs` и ограничивает привязку маршрутов из других неймспейсов через `allowedRoutes`.

**Ключевые поля:**
- `spec.gatewayClassName` — ссылка на GatewayClass
- `spec.listeners[]` — массив слушателей (максимум 64)
  - `name` — уникальное имя слушателя
  - `port` — порт (1-65535)
  - `protocol` — протокол (HTTP, HTTPS, TLS, TCP, UDP)
  - `hostname` — фильтрация по хосту (опционально)
  - `tls` — настройки TLS (для HTTPS/TLS протоколов)
  - `allowedRoutes` — ограничение маршрутов
- `spec.addresses[]` — фиксированные IP-адреса (если поддерживается)

**Статусы:**
- `Accepted` — конфигурация валидна и принята контроллером
- `Programmed` — шлюз успешно сконфигурирован в Data Plane (выделен IP, открыты порты)
- `ResolvedRefs` — все зависимости (CertificateRefs) найдены

**Ограничения:**
- Максимум 64 слушателя на один Gateway (для больших конфигураций используйте ListenerSet)
- Каждый слушатель должен иметь уникальную комбинацию `port` + `protocol`

#### 3. ListenerSet (Namespaced, v1.5+)

Специализированный ресурс для масштабируемых и мультитенентных сред. Позволяет командам приложений самостоятельно описывать слушателей (хосты, порты, сертификаты) и прикреплять их к общему `Gateway`.

**Ключевые поля:**
- `spec.parentRef` — ссылка на Gateway, к которому прикрепляется ListenerSet
- `spec.listeners[]` — массив слушателей (аналогично Gateway)

**Решаемые проблемы:**
- **Лимит слушателей:** Преодолевает архитектурное ограничение в 64 слушателя на один объект Gateway
- **Самообслуживание:** Разработчики могут изменять настройки своих доменов без прямого доступа к редактированию общего инфраструктурного шлюза

**Статусы:**
- `Accepted` — конфигурация валидна
- `Programmed` — слушатели успешно добавлены в Gateway
- `Conflicted` — обнаружен конфликт с существующими слушателями

#### 4. HTTPRoute (Namespaced)

Основной ресурс для L7-трафика (HTTP/HTTPS). Поддерживает сложную маршрутизацию по путям, заголовкам, методам и query-параметрам, а также фильтры (Rewrites, Redirects, Mirroring) и весовую балансировку.

**Ключевые поля:**
- `spec.parentRefs[]` — ссылки на Gateway или Service (GAMMA)
- `spec.hostnames[]` — массив хостов для маршрутизации
- `spec.rules[]` — массив правил маршрутизации
  - `matches[]` — условия совпадения (path, headers, method, queryParams)
  - `filters[]` — фильтры (RequestRedirect, URLRewrite, RequestHeaderModifier, ResponseHeaderModifier, RequestMirror)
  - `backendRefs[]` — бэкенды с весами для балансировки
  - `timeouts` — таймауты запроса
  - `sessionPersistence` — настройки sticky sessions

**Статусы:**
- `Accepted` — маршрут принят родительским Gateway/Service
- `ResolvedRefs` — все зависимости (Service, ReferenceGrant) найдены и валидны
- `Conflicted` — обнаружен конфликт с другим маршрутом (Same host + path)

**Фильтры (Standard):**

| Фильтр | Описание |
|:---|:---|
| `RequestRedirect` | Перенаправление (301/302) с заменой схемы, хоста, пути |
| `URLRewrite` | Перезапись пути или хоста |
| `RequestHeaderModifier` | Добавление, удаление или изменение заголовков запроса |
| `ResponseHeaderModifier` | Добавление, удаление или изменение заголовков ответа |
| `RequestMirror` | Зеркалирование трафика на дополнительный бэкенд |

#### 5. GRPCRoute (Namespaced)

Нативная поддержка gRPC. Позволяет маршрутизировать трафик на уровне gRPC-сервисов и методов, а не просто HTTP-путей.

**Ключевые поля:**
- `spec.parentRefs[]` — ссылки на Gateway
- `spec.hostnames[]` — массив хостов
- `spec.rules[]` — массив правил
  - `matches[]` — условия совпадения (service, method, headers)
  - `filters[]` — фильтры (RequestHeaderModifier, ResponseHeaderModifier)
  - `backendRefs[]` — бэкенды gRPC-сервисов

**Статусы:**
- `Accepted` — маршрут принят
- `ResolvedRefs` — все зависимости найдены

**Пример маршрутизации по gRPC-методу:**

```yaml
matches:
- method:
    service: "helloworld.Greeter"
    method: "SayHello"
    type: "Exact"
```

#### 6. TLSRoute (Namespaced)

Маршрутизация по SNI (Server Name Indication) для сценариев TLS Passthrough. Трафик не расшифровывается на уровне шлюза, а передается напрямую бэкенду.

**Ключевые поля:**
- `spec.parentRefs[]` — ссылки на Gateway (listener с протоколом TLS, mode: Passthrough)
- `spec.hostnames[]` — массив SNI-хостов
- `spec.rules[]` — массив правил
  - `backendRefs[]` — бэкенды

**Статусы:**
- `Accepted` — маршрут принят
- `ResolvedRefs` — все зависимости найдены

**Когда использовать:**
- Когда TLS-терминация должна происходить на бэкенде
- Для протоколов, использующих TLS (не только HTTPS)

#### 7. TCPRoute (Namespaced)

Управление TCP-трафиком на транспортном уровне (L4). Переведен в Standard Channel в v1.6.0.

**Ключевые поля:**
- `spec.parentRefs[]` — ссылки на Gateway (listener с протоколом TCP)
- `spec.rules[]` — массив правил
  - `backendRefs[]` — бэкенды

**Статусы:**
- `Accepted` — маршрут принят
- `ResolvedRefs` — все зависимости найдены

**Когда использовать:**
- Базы данных (PostgreSQL, MySQL)
- Кэш-серверы (Redis, Memcached)
- Любой не-HTTP TCP-трафик

#### 8. UDPRoute (Namespaced)

Управление UDP-трафиком на транспортном уровне (L4). Переведен в Standard Channel в v1.6.0.

**Ключевые поля:**
- `spec.parentRefs[]` — ссылки на Gateway (listener с протоколом UDP)
- `spec.rules[]` — массив правил
  - `backendRefs[]` — бэкенды

**Статусы:**
- `Accepted` — маршрут принят
- `ResolvedRefs` — все зависимости найдены

**Когда использовать:**
- DNS-серверы
- Игровые серверы
- VoIP-сервисы

#### 9. ReferenceGrant (Namespaced)

Механизм безопасности для кросс-неймспейс ссылок. Позволяет владельцу ресурса (например, Secret или Service) разрешить его использование объектами из другого пространства имен.

**Ключевые поля:**
- `spec.from[]` — массив источников запросов
  - `group` — API group (например, `gateway.networking.k8s.io`)
  - `kind` — тип ресурса (например, `Gateway`)
  - `namespace` — namespace источника
- `spec.to[]` — массив целевых ресурсов
  - `group` — API group (пустая строка для core)
  - `kind` — тип ресурса (например, `Secret`, `Service`)
  - `name` — имя ресурса (опционально — если не указано, разрешены все ресурсы данного типа)

**Особенности:**
- Не имеет секции status — проверяется контроллером в момент попытки доступа
- Действует только в одну сторону (from → to)
- Для обратного направления требуется отдельный ReferenceGrant

#### 10. BackendTLSPolicy (Namespaced)

Политика для настройки безопасности соединения между шлюзом и бэкендом (re-encryption). Позволяет указать доверенные CA и ожидаемый SNI для проверки сертификата пода.

**Ключевые поля:**
- `spec.targetRef` — ссылка на целевой ресурс (Service)
- `spec.tls` — настройки TLS
  - `caCertRefs[]` — ссылки на CA-сертификаты (ConfigMap или Secret)
  - `hostname` — ожидаемый SNI для проверки сертификата
  - `wellKnownCACerts` — использовать системные CA (опционально)

**Статусы:**
- `Accepted` — политика принята
- `ResolvedRefs` — все зависимости (CA-сертификаты) найдены

**Когда использовать:**
- Для обеспечения сквозного шифрования (end-to-end encryption)
- Когда требуется проверка сертификата бэкенда
- В средах с жесткими требованиями безопасности

### Механизмы прикрепления политик (Policy Attachment)

Gateway API предоставляет стандартизированный способ расширения функционала через политики. Детальное описание механизмов см. в [Провайдер-специфичная конфигурация](./provider_specific_config.md).

**Типы прикрепления:**

1. **Direct Policy Attachment:** Политика применяется к конкретному ресурсу через `targetRef` (например, `BackendTLSPolicy` привязана к конкретному `Service`).

2. **Inherited Policy Attachment:** Политика прикрепляется к верхнему уровню (например, к `GatewayClass` или `Gateway`) и наследуется всеми дочерними ресурсами:
   - **Defaults:** Значения по умолчанию, которые можно переопределить ниже
   - **Overrides:** Принудительные настройки, обязательные для выполнения

## Практические сценарии

### Сценарий 1: Создание и настройка GatewayClass

```bash
# Просмотр доступных GatewayClass в кластере
kubectl get gatewayclass
# → NAME          CONTROLLER                                        AGE
# → envoy         gateway-envoyproxy.io/gateway-controller           5d
# → kgateway      kgateway.dev/kgateway-controller                   3d
# → nginx         gateway.nginx.org/nginx-gateway-controller         10d
```

```yaml
# Создание GatewayClass с параметрами
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: custom-gateway
spec:
  controllerName: example.com/gateway-controller
  parametersRef:
    group: example.com
    kind: GatewayConfig
    name: custom-config
    namespace: gateway-system
  description: "Custom gateway configuration for production"
```

```bash
# Проверка статуса GatewayClass
kubectl describe gatewayclass custom-gateway
# → Status:
# →   Conditions:
# →     Type:               Accepted
# →     Status:             True
# →     Last Transition Time: ...
```

### Сценарий 2: Создание Gateway с несколькими слушателями

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-protocol-gateway
  namespace: gateway-system
spec:
  gatewayClassName: envoy
  listeners:
  # HTTP listener (будет перенаправлен на HTTPS)
  - name: http
    port: 80
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: All
  # HTTPS listener
  - name: https
    port: 443
    protocol: HTTPS
    hostname: "*.example.com"
    tls:
      mode: Terminate
      certificateRefs:
      - name: wildcard-cert
    allowedRoutes:
      namespaces:
        from: Selector
        selector:
          matchLabels:
            gateway-access: "true"
  # TCP listener для базы данных
  - name: tcp-postgres
    port: 5432
    protocol: TCP
    allowedRoutes:
      namespaces:
        from: Same
```

```bash
# Проверка статуса Gateway
kubectl describe gateway multi-protocol-gateway -n gateway-system
# → Status:
# →   Conditions:
# →     Type:               Accepted
# →     Status:             True
# →     Type:               Programmed
# →     Status:             True
# →   Addresses:
# →     - Type:  IPAddress
# →       Value: 192.168.1.100
```

### Сценарий 3: Настройка HTTPRoute с фильтрами

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: app-prod
spec:
  parentRefs:
  - name: multi-protocol-gateway
    namespace: gateway-system
    sectionName: https
  hostnames:
  - "api.example.com"
  rules:
  # Канареечное развертывание (90% v1, 10% v2)
  - matches:
    - path:
        type: PathPrefix
        value: /api/v1
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        set:
        - name: X-Forwarded-Proto
          value: https
    backendRefs:
    - name: api-v1-service
      port: 8080
      weight: 90
    - name: api-v2-service
      port: 8080
      weight: 10
  # Перенаправление /old-path на /new-path
  - matches:
    - path:
        type: Exact
        value: /old-path
    filters:
    - type: RequestRedirect
      requestRedirect:
        path:
          type: ReplaceFullPath
          replaceFullPath: /new-path
        statusCode: 301
  # Зеркалирование трафика для тестирования
  - matches:
    - path:
        type: PathPrefix
        value: /api/test
    filters:
    - type: RequestMirror
      requestMirror:
        backendRef:
          name: test-service
          port: 8080
    backendRefs:
    - name: prod-service
      port: 8080
```

```bash
# Проверка статуса HTTPRoute
kubectl describe httproute api-route -n app-prod
# → Status:
# →   Parents:
# →     - Controller Name: gateway-envoyproxy.io/gateway-controller
# →       Parent Ref:
# →         Name: multi-protocol-gateway
# →       Conditions:
# →         Type:               Accepted
# →         Status:             True
# →         Type:               ResolvedRefs
# →         Status:             True
```

### Сценарий 4: Настройка ReferenceGrant для кросс-неймспейс доступа

```yaml
# В namespace app-prod (где находится секрет)
apiVersion: gateway.networking.k8s.io/v1
kind: ReferenceGrant
metadata:
  name: allow-gateway-cert-access
  namespace: app-prod
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: gateway-system
  to:
  - group: ""
    kind: Secret
    name: api-tls-cert
```

```bash
# Проверка что ReferenceGrant создан
kubectl get referencegrant -n app-prod
# → NAME                        AGE
# → allow-gateway-cert-access   2m

# Проверка статуса Gateway (ResolvedRefs должен быть True)
kubectl describe gateway multi-protocol-gateway -n gateway-system | grep -A 5 "Conditions:"
```

### Сценарий 5: Настройка BackendTLSPolicy для безопасного соединения с бэкендом

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: BackendTLSPolicy
metadata:
  name: api-backend-tls
  namespace: app-prod
spec:
  targetRef:
    group: ""
    kind: Service
    name: api-service
  tls:
    caCertRefs:
    - group: ""
      kind: ConfigMap
      name: internal-ca-cert
    hostname: "api-service.app-prod.svc.cluster.local"
```

```bash
# Проверка статуса BackendTLSPolicy
kubectl describe backendtlspolicy api-backend-tls -n app-prod
# → Status:
# →   Conditions:
# →     Type:               Accepted
# →     Status:             True
# →     Type:               ResolvedRefs
# →     Status:             True
```

### Сценарий 6: Настройка GAMMA (Service как ParentRef)

```yaml
# HTTPRoute ссылается на Service напрямую (East-West трафик)
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: internal-route
  namespace: app-prod
spec:
  parentRefs:
  - group: ""
    kind: Service
    name: payment-service
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /api/payment
    backendRefs:
    - name: payment-service-v1
      port: 8080
      weight: 95
    - name: payment-service-v2
      port: 8080
      weight: 5
```

### Жизненный цикл и связность ресурсов

Связь между ресурсами осуществляется через `parentRefs` и `targetRefs`.

**Пример делегирования TLS через ListenerSet:**

```yaml
# 1. Инфраструктурный Gateway (Namespace: infra)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shared-gateway
spec:
  gatewayClassName: envoy-gateway
  allowedListeners:
    namespaces:
      from: Selector
      selector:
        matchLabels:
          tenant: allowed
---
# 2. ListenerSet команды приложения (Namespace: app-team)
apiVersion: gateway.networking.k8s.io/v1
kind: ListenerSet
metadata:
  name: app-listeners
spec:
  parentRef:
    name: shared-gateway
    namespace: infra
  listeners:
  - name: https
    hostname: "api.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: api-tls-secret
```

## Дополнительная информация

### Статусы ресурсов (Conditions)

Gateway API предоставляет детальную диагностику через `status.conditions`:

| Условие | Ресурс | Описание |
|:---|:---|:---|
| **Accepted** | Gateway, HTTPRoute, GRPCRoute, TLSRoute, TCPRoute, UDPRoute, ListenerSet | Конфигурация признана валидной контроллером |
| **Programmed** | Gateway, ListenerSet | Шлюз успешно сконфигурирован в Data Plane (выделен IP, открыты порты) |
| **ResolvedRefs** | HTTPRoute, GRPCRoute, TLSRoute, TCPRoute, UDPRoute, Gateway | Все зависимости (Service, Secret, ReferenceGrant) найдены и корректны |
| **Conflicted** | ListenerSet, HTTPRoute | Обнаружено пересечение хостов или портов между разными объектами |

**Команды для диагностики:**

```bash
# Проверка состояния всех ресурсов Gateway API в кластере
kubectl get gateway,httproute,gatewayclass,referencegrant,backendtlspolicy -A

# Детальная информация о статусе Gateway
kubectl describe gateway <name> -n <namespace>

# Детальная информация о статусе HTTPRoute
kubectl describe httproute <name> -n <namespace>

# Фильтрация ресурсов с проблемами
kubectl get gateway --all-namespaces -o json | jq '.items[] | select(.status.conditions[]? | select(.type=="Programmed" and .status!="True")) | {namespace: .metadata.namespace, name: .metadata.name}'
```

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Gateway not programmed` | Контроллер не может выделить IP или настроить инфраструктуру | Проверить логи контроллера, настройки провайдера |
| `ResolvedRefs: False` | Отсутствует ReferenceGrant для кросс-namespace ссылок | Создать ReferenceGrant в namespace целевого ресурса |
| `Conflicted: True` | Два ресурса с одинаковым hostname/path на одном Gateway | Исправить hostnames или использовать разные Gateway |
| `Accepted: False` | Неверная конфигурация (невалидный порт, протокол) | Проверить спецификацию listener/route |
| `CertificateNotFound` | Secret с сертификатом не найден | Проверить существование Secret и имени в `certificateRefs` |
| `InvalidParameter` | Неверные параметры в BackendTLSPolicy или других политиках | Проверить ссылки на CA-сертификаты |

### Best Practices

1. **Используйте отдельные Gateway для разных окружений:**
   - Создайте отдельные Gateway для production и staging
   - Применяйте `allowedRoutes` для ограничения доступа к namespace

2. **Минимизируйте кросс-namespace ссылки:**
   - Размещайте TLS-сертификаты в том же namespace, что и Gateway
   - Используйте ReferenceGrant только когда это необходимо

3. **Используйте ListenerSet для масштабирования:**
   - При превышении 50 слушателей переходите на ListenerSet
   - Разделяйте ListenerSet по командам или приложениям

4. **Настройте мониторинг статусов:**
   - Отслеживайте условия `Programmed` и `ResolvedRefs`
   - Настройте алерты на изменения статусов

5. **Версионируйте конфигурации:**
   - Используйте GitOps для управления ресурсами Gateway API
   - Ведите историю изменений в Git

6. **Тестируйте перед применением:**
   - Используйте `kubectl apply --dry-run=client` для проверки синтаксиса
   - Проверяйте статусы ресурсов после применения

### См. также

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта.
- [Провайдер-специфичная конфигурация](./provider_specific_config.md) — детальное описание механизмов Policy Attachment.
- [Миграция с Ingress](./migration.md) — использование инструментов конвертации.
- [Мониторинг и наблюдаемость](./monitoring.md) — Prometheus, Grafana, алертинг.
- [Высокая доступность](./high_availability.md) — PDB, HA, disaster recovery.
- [GitOps и CI/CD](./gitops_cicd.md) — ArgoCD, Flux, валидация.
- [Безопасность](./security_policies.md) — NetworkPolicy, RBAC, Kyverno.
- [Глубокая диагностика](./troubleshooting_deep_dive.md) — Envoy admin, packet capture.

**Родительская тема:** [Gateway API](./definitions.md)
