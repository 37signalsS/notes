# Gateway API — Ресурсы (CRD)

**Надёжность:** 10 (SSoT + Официальная документация Gateway API v1.5)

## Определения

**Custom Resource Definition (CRD)** — механизм в Kubernetes, позволяющий расширять стандартный API собственными типами ресурсов. Gateway API полностью построен на базе CRD, что обеспечивает его гибкость и независимость от циклов релиза ядра Kubernetes.

**Gateway API Resources** — иерархический набор стандартных ресурсов (GatewayClass, Gateway, Routes, Policies), предназначенный для управления входящим и мессервисным (GAMMA) трафиком.

## Базовые концепции

### Ролевая модель управления

Gateway API разделяет ответственность за сетевую инфраструктуру между тремя основными ролями, используя соответствующие типы ресурсов:

| Ресурс | Роль | Область ответственности |
| :--- | :--- | :--- |
| **GatewayClass** | Infrastructure Provider | Выбор контроллера (Envoy, Traefik) и глобальные настройки. |
| **Gateway / ListenerSet** | Cluster Operator | Настройка физических параметров (IP, порты, TLS-терминация). |
| ***Route** | Application Developer | Бизнес-логика (пути, заголовки, фильтры, бэкенды). |

### Основные ресурсы (Standard Channel)

Начиная с версии v1.5, следующие ресурсы считаются стабильными (GA) и готовыми к промышленной эксплуатации:

#### 1. GatewayClass (Cluster-scoped)
Шаблон для создания шлюзов. Определяет, какой контроллер (`spec.controllerName`) будет обрабатывать ресурсы. Аналогичен `IngressClass`, но является обязательным и строго типизированным.

#### 2. Gateway (Namespaced)
Описание точки входа трафика. Содержит слушателей (`listeners`), которые определяют протоколы (HTTP, HTTPS, TLS, TCP, UDP) и порты. Управляет безопасностью через `certificateRefs` и ограничивает привязку маршрутов через `allowedRoutes`.

#### 3. ListenerSet (Namespaced, v1.5+)
Новый ресурс для масштабирования и мультитенентности. Позволяет командам приложений самостоятельно описывать слушателей (хосты, порты, TLS) и подключать их к общему `Gateway`, не имея прав на редактирование самого шлюза. Это решает проблему лимита в 64 слушателя на один объект `Gateway`.

#### 4. Ресурсы маршрутизации (*Route)
- **HTTPRoute:** Маршрутизация HTTP/HTTPS. Поддерживает фильтры (CORS, Rewrite, Redirect) и канареечные развертывания.
- **GRPCRoute:** Нативная поддержка gRPC (маршрутизация по сервисам и методам).
- **TLSRoute:** Маршрутизация по SNI для сценариев TLS Passthrough.
- **TCPRoute / UDPRoute:** Управление трафиком на уровне L4.

#### 5. ReferenceGrant (Namespaced)
«Рукопожатие» безопасности для кросс-неймспейс ссылок. Позволяет владельцу ресурса (например, Secret или Service) разрешить его использование ресурсам из другого пространства имен (например, шлюзу или маршруту). **Не имеет поля status**, проверяется контроллером в реальном времени.

#### 6. BackendTLSPolicy (Namespaced)
Политика для настройки безопасного соединения между шлюзом и бэкендом (re-encryption). Позволяет указать доверенные CA и ожидаемый SNI для проверки сертификата пода.

## Практические сценарии

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
apiVersion: gateway.networking.k8s.io/v1alpha1 # v1 в конце 2026
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
- **Accepted:** Конфигурация принята контроллером.
- **Programmed:** (Gateway) Шлюз успешно настроен в Data Plane.
- **ResolvedRefs:** (Route) Все ссылки на бэкенды и секреты успешно разрешены.
- **Conflicted:** Обнаружено дублирование хостов или портов.

**См. также:**
- [Концепции Gateway API](./definitions.md) — базовые определения
- [Базовые сценарии](./practical_basic.md) — примеры создания ресурсов
- [Маршрутизация L4](./layer4_routing.md) — описание TCPRoute и UDPRoute
- [Миграция с Ingress](./migration.md) — использование инструментов конвертации

**Родительская тема:** [Gateway API](./definitions.md)
