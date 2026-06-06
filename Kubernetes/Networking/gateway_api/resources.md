# Gateway API — Ресурсы (CRD)

## Определения

**Custom Resource Definition (CRD)** — механизм в Kubernetes, позволяющий расширять стандартный API собственными типами ресурсов. Gateway API полностью построен на базе CRD.

**Gateway API Resources** — набор стандартных ресурсов (GatewayClass, Gateway, HTTPRoute и др.), которые описывают иерархическую модель управления сетевым трафиком.

## Базовые концепции

### Ролевая модель управления

Gateway API разделяет ответственность за сетевую инфраструктуру между тремя основными ролями:

| Ресурс | Роль | Ответственность |
| :--- | :--- | :--- |
| **GatewayClass** | Infrastructure Provider | Определение типов шлюзов и используемых контроллеров. |
| **Gateway** | Cluster Operator | Настройка конкретных точек входа (порты, TLS, IP). |
| ***Route** | Application Developer | Правила маршрутизации трафика к конкретным сервисам. |

### Основные ресурсы (CRD)

#### 1. GatewayClass

Ресурс кластерного уровня (Cluster-scoped), являющийся шаблоном для создания шлюзов.

- Определяет контроллер (`spec.controllerName`), который будет обрабатывать ресурсы.
- Позволяет задавать общую конфигурацию для всех шлюзов данного класса через параметры.
- Аналогичен `IngressClass`, но с более строгой типизацией.

#### 2. Gateway

Ресурс уровня пространства имен (Namespace-scoped), описывающий физическое или виртуальное воплощение шлюза.

- Ссылается на `GatewayClass`.
- Содержит список слушателей (`listeners`), определяющих протокол, порт и правила безопасности (TLS).
- Управляет привязкой маршрутов через `allowedRoutes`, ограничивая, какие пространства имен могут подключать свои правила к этому шлюзу.

#### 3. Ресурсы маршрутизации (*Route)

Описывают логику обработки трафика для различных протоколов:

- **HTTPRoute:** Самый распространенный ресурс для HTTP/HTTPS. Поддерживает фильтры (redirect, rewrite, header modification) и разделение трафика (traffic splitting).
- **GRPCRoute:** Оптимизирован для маршрутизации gRPC-вызовов.
- **TLSRoute:** Используется для сценариев TLS Passthrough (маршрутизация по SNI).
- **TCPRoute / UDPRoute:** Позволяют управлять трафиком на уровне L4 (базы данных, игровые серверы).

## Практические сценарии

### Жизненный цикл ресурса

1. **Infrastructure Provider** устанавливает CRD и контроллер, создавая `GatewayClass` (например, `envoy-gateway`).
2. **Cluster Operator** создает `Gateway` в инфраструктурном неймспейсе, указывая порты 80 и 443.
3. **Application Developer** создает `HTTPRoute` в своем неймспейсе и привязывает его к `Gateway` через поле `parentRefs`.

### Пример иерархии связей

```yaml
# Gateway (infra namespace)
spec:
  gatewayClassName: public-lb
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
---
# HTTPRoute (app namespace)
spec:
  parentRefs:
  - name: external-gateway
    namespace: infra
  rules:
  - matches:
    - path: { type: PathPrefix, value: /api }
    backendRefs:
    - name: api-service
      port: 80
```

## Дополнительная информация

### Статусы ресурсов

Gateway API предоставляет богатую обратную связь через поле `status`:

- **Accepted:** Конфигурация синтаксически верна и принята контроллером.
- **Programmed:** Шлюз успешно настроен и готов принимать трафик (только для `Gateway`).
- **ResolvedRefs:** Все ссылки на бэкенды (Service) и секреты (Secret) корректны (только для `*Route`).

**См. также:**

- [Концепции Gateway API](./definitions.md) — базовые определения и преимущества стандарта
- [Базовые сценарии](./practical_basic.md) — практические примеры создания ресурсов
- [Маршрутизация L4](./layer4_routing.md) — детальное описание TCPRoute и UDPRoute

**Родительская тема:** [Gateway API](./definitions.md)
