# Сводка по типам сервисов Kubernetes

## Определения

Kubernetes предоставляет несколько типов **Service** для различных сценариев доступа к приложениям. Выбор типа определяет **границы доступности** (внутри кластера vs. извне) и **способ маршрутизации** трафика.

> Для быстрого сравнения характеристик в виде таблицы см. **[Сравнительная таблица типов Service](./service_types_comparison.md)**.

## Основные концепции

### Иерархия типов

Все типы сервисов (кроме `ExternalName` и `Headless`) построены на базе **ClusterIP**:

```
ClusterIP (базовый)
    ↓
NodePort (ClusterIP + порт на узлах)
    ↓
LoadBalancer (NodePort + облачный балансировщик)
```

### Критерии выбора типа

| Критерий | Рекомендация |
|----------|--------------|
| **Внутреннее взаимодействие** | [ClusterIP](./service_type_clusterip.md) |
| **Разработка/отладка** | [NodePort](./service_type_nodeport.md) или `kubectl port-forward` |
| **Production в облаке** | [LoadBalancer](./service_type_loadbalancer.md) или [Ingress](../Ingress/overview.md) |
| **On-premise production** | [NodePort](./service_type_nodeport.md) + внешний LB или MetalLB |
| **HTTP/HTTPS приложения** | [Ingress](../Ingress/overview.md) (L7) вместо [LoadBalancer](./service_type_loadbalancer.md) (L4) |

## Практические сценарии

### Сводная таблица типов сервисов

| Тип | Доступность | Основной сценарий | Ограничения |
|-----|-------------|-------------------|-------------|
| **[ClusterIP](./service_type_clusterip.md)** | Только внутри кластера | Внутренние коммуникации (backend-to-db) | Нет прямого внешнего доступа |
| **[NodePort](./service_type_nodeport.md)** | Внутри и снаружи (через `IP_узла:NodePort`) | Разработка, отладка, простой внешний доступ, on-prem | Диапазон портов 30000-32767, зависимость от IP узла |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Из интернета (через внешний IP от облака) | Публикация приложений в облаке (production) | Зависит от облачного провайдера; в bare-metal требует MetalLB |
| **[ExternalName](./service_type_externalname.md)** | Только DNS (CNAME) | Доступ к внешним сервисам по внутреннему имени | Не проксирует трафик, работает только на уровне DNS |
| **[Headless](./service_type_headless.md)** | Прямой доступ к Pod-ам | Stateful-приложения (StatefulSet), service discovery | Нет балансировки на уровне Service |

### Сравнение по уровням OSI

| Тип | Уровень OSI | Протоколы | Маршрутизация |
|-----|-------------|-----------|---------------|
| ClusterIP | L4 | TCP, UDP | IP + порт |
| NodePort | L4 | TCP, UDP | IP узла + порт |
| LoadBalancer | L4 | TCP, UDP | Публичный IP + порт |
| Ingress | L7 | HTTP, HTTPS | Хост, путь, заголовки |

## Дополнительная информация

### ExternalIPs
Поле `externalIPs` позволяет назначить сервису заранее известный внешний IP-адрес. Это не тип, а свойство, применимое к другим типам.
**Подробнее: [ExternalIPs](./service_externalips.md)**

### Headless Service
Сервис без `ClusterIP` (`clusterIP: None`), который используется для прямого обнаружения подов.
**Подробнее: [Headless Service](./service_type_headless.md)**

### Дополнительные ресурсы
- [Обзор Service](./service_overview.md) — базовые концепции и архитектура
- [Сравнительная таблица](./service_types_comparison.md) — быстрое сравнение всех типов
- [Практический сценарий](./service_practical_scenarios.md) — пошаговый пример публикации
- [Ingress](../Ingress/overview.md) — L7 маршрутизация для HTTP/HTTPS
