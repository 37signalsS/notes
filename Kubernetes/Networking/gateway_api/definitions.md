# Kubernetes Gateway API — Определения

## Определения

**Gateway API** — стандартная спецификация с открытым исходным кодом для управления внешним доступом к сервисам в Kubernetes. Представляет собой следующее поколение API для управления трафиком, приходя на смену Ingress. Ключевая особенность — более выразительный, расширяемый и ролевой подход к маршрутизации.

**Важно:** Gateway API — это стандарт (спецификация), а не конкретная программа. Стандарт описывает, *какие* ресурсы (CRD) существуют и *какие* поля можно использовать в манифестах. Контроллер (Envoy, Traefik, Istio) — это программа, которая реализует этот стандарт, читает манифесты и настраивает нижележащий прокси.

## Базовые концепции

### Ролевая модель

Gateway API разделяет ответственность между инфраструктурой и разработчиками:

- **Администраторы кластера** управляют шлюзами (`Gateway`)
- **Разработчики** управляют правилами маршрутизации (`HTTPRoute`)

### Преимущества перед Ingress

| Характеристика | Ingress | Gateway API |
|---------------|---------|-------------|
| **Разделение ролей** | Слабое, всё в одном манифесте | Четкое: GatewayClass → Gateway → Route |
| **Аннотации** | Множество специфичных для контроллера | Унифицированные CRD |
| **Namespace маршрутов** | Только в namespace приложения | В любом namespace |
| **Secret для TLS** | Только в том же namespace | В любом namespace |
| **Поддержка протоколов** | HTTP/HTTPS | HTTP, HTTPS, gRPC, TCP, UDP |
| **Direct Pod targeting** | Через Service | Напрямую (по endpoints) |
| **Ролевая модель** | Отсутствует | Встроенная (`allowedRoutes`) |

### Статус компонентов (Status Conditions)

В отличие от Ingress, где проверка работоспособности часто требовала `curl`, Gateway API предоставляет подробную обратную связь через статус ресурсов:

- **Accepted:** Манифест синтаксически корректен и принят контроллером.
- **Programmed (для Gateway):** Конфигурация успешно сгенерирована и передана на Data Plane (прокси). Шлюз готов принимать трафик.
- **ResolvedRefs (для Route):** Все ссылки на бэкенды (Service) и другие ресурсы (Secret) успешно разрешены и существуют.

**Рекомендация:** Всегда начинайте диагностику с `kubectl describe <resource>`. Если статус `False`, в сообщении (`message`) будет указана точная причина ошибки.

### Актуальность

Сообщество Kubernetes прекратило поддержку `kubernetes/ingress-nginx` в марте 2026. Gateway API является официальным преемником для управления входящим трафиком.

Подробное руководство по миграции: [Миграция с Ingress на Gateway API](./migration.md).

## Практические сценарии

### Выбор реализации Gateway API

Конфигурации Gateway API переносимы между различными реализациями: Envoy Gateway, Traefik, Cilium, Istio, Kong, GKE. Правильный вопрос: «Поддерживает ли Envoy Gateway API?», а не «Включает ли Gateway API в себя Envoy?».

Сравнение реализаций: [Envoy Gateway](./envoy_gateway.md), [Traefik](./traefik.md).

## Дополнительная информация

Основные ресурсы (CRD): GatewayClass, Gateway, HTTPRoute, GRPCRoute, TLSRoute, TCPRoute, UDPRoute — см. [Ресурсы (CRD)](./resources.md).

Базовые примеры использования: [Базовые сценарии](./practical_basic.md).

Расширенные функции маршрутизации (Redirect, Rewrite, Traffic Splitting): [Расширенные функции маршрутизации](./routing_features.md).

Маршрутизация L4 (TCP/UDP): [L4 маршрутизация](./layer4_routing.md).

Официальная документация: [Gateway API](https://gateway-api.sigs.k8s.io/).

Руководство по миграции с Ingress-NGINX: [Migrating from Ingress-NGINX](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/).

Инструмент автоматической миграции: [ingress2gateway](https://github.com/kubernetes-sigs/gateway-api/tree/main/ingress2gateway).

Обзор Ingress и его ограничений: [Ingress: Будущее — Gateway API](../Ingress/overview.md#будущее-ingress-gateway-api).
