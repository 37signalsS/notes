# Service Types Summary

## Определения

**Service Types Summary** — сводная информация по всем типам сервисов Kubernetes с иерархией, критериями выбора и сравнением характеристик.

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

| Критерий | Рекомендуемый тип | Альтернатива |
| :--- | :--- | :--- |
| **Внутреннее взаимодействие** | [ClusterIP](./service_type_clusterip.md) | — |
| **Разработка/отладка** | [NodePort](./service_type_nodeport.md) | `kubectl port-forward` |
| **Production в облаке** | [LoadBalancer](./service_type_loadbalancer.md) | [Ingress](../Ingress/overview.md) |
| **On-premise production** | NodePort + внешний LB | [MetalLB](../metallb.md) |
| **HTTP/HTTPS приложения** | [Ingress](../Ingress/overview.md) (L7) | [LoadBalancer](./service_type_loadbalancer.md) (L4) |
| **Stateful-приложения** | [Headless](./service_type_headless.md) | — |
| **Внешние ресурсы (БД, API)** | [ExternalName](./service_type_externalname.md) | Endpoints без селектора |

## Практические сценарии

### Сводная таблица типов сервисов

| Тип | Доступность | Основной сценарий | Ограничения |
| :--- | :--- | :--- | :--- |
| **[ClusterIP](./service_type_clusterip.md)** | Только внутри кластера | Внутренние коммуникации (backend-to-db) | Нет прямого внешнего доступа |
| **[NodePort](./service_type_nodeport.md)** | Внутри и снаружи (через `IP_узла:NodePort`) | Разработка, отладка, on-prem | Диапазон портов 30000-32767, зависимость от IP узла |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Из интернета (через внешний IP от облака) | Публикация приложений в облаке (production) | Зависит от облачного провайдера; в bare-metal требует MetalLB |
| **[ExternalName](./service_type_externalname.md)** | Только DNS (CNAME) | Доступ к внешним сервисам по внутреннему имени | Не проксирует трафик, только DNS |
| **[Headless](./service_type_headless.md)** | Прямой доступ к Pod-ам | Stateful-приложения (StatefulSet), service discovery | Нет балансировки на уровне Service |

### Сравнение по уровням OSI

| Тип | Уровень OSI | Протоколы | Маршрутизация |
| :--- | :--- | :--- | :--- |
| **ClusterIP** | L4 | TCP, UDP | IP + порт |
| **NodePort** | L4 | TCP, UDP | IP узла + порт |
| **LoadBalancer** | L4 | TCP, UDP | Публичный IP + порт |
| **ExternalName** | DNS | DNS (CNAME) | DNS-разрешение |
| **Headless** | L4 | TCP, UDP | Прямой IP Pod |
| **Ingress** | L7 | HTTP, HTTPS | Хост, путь, заголовки |

### Матрица принятия решений

| Вопрос | Ответ | Рекомендуемый тип |
| :--- | :--- | :--- |
| **Нужен ли внешний доступ?** | Нет | ClusterIP |
| **Нужен ли внешний доступ?** | Да, для отладки | NodePort |
| **Нужен ли внешний доступ?** | Да, production в облаке | LoadBalancer или Ingress |
| **Нужен ли внешний доступ?** | Да, on-premise | NodePort + внешний LB или MetalLB |
| **Это HTTP/HTTPS трафик?** | Да | Ingress (L7 маршрутизация) |
| **Это TCP/UDP трафик?** | Да | LoadBalancer / NodePort |
| **Нужны ли стабильные имена Pod?** | Да | Headless (для StatefulSet) |
| **Нужен доступ к внешнему ресурсу?** | Да | ExternalName |

## Дополнительная информация

### Ограничения типов

| Тип | Основное ограничение |
| :--- | :--- |
| **ClusterIP** | Нет внешнего доступа без port-forward |
| **NodePort** | Диапазон портов 30000-32767, зависимость от IP узла |
| **LoadBalancer** | Зависит от облачного провайдера, стоимость за каждый IP |
| **ExternalName** | Только DNS, нет проксирования трафика |
| **Headless** | Нет балансировки на уровне Service |

### Дополнительные свойства сервисов

Помимо основных типов, существуют важные поля и концепции, расширяющие функциональность сервисов:

| Свойство | Описание | Подробнее |
| :--- | :--- | :--- |
| **`externalIPs`** | Привязка сервиса к статическим внешним IP | [ExternalIPs](./service_externalips.md) (депрецируется v1.36) |
| **`externalTrafficPolicy: Local`** | Сохранение IP клиента для NodePort/LoadBalancer | [NodePort](./service_type_nodeport.md#externaltrafficpolicy-local) |
| **`sessionAffinity: ClientIP`** | Привязка сессии клиента к одному Pod | [ClusterIP](./service_type_clusterip.md#session-affinity) |
| **`clusterIP: None`** | Headless Service — DNS возвращает IP Pod напрямую | [Headless](./service_type_headless.md) |

### Связанные концепции

- **[Service Overview](./service_overview.md)** — базовые концепции и архитектура сервисов
- **[Практический сценарий](./service_practical_scenarios.md)** — пошаговый пример публикации приложения
- **[Ingress](../Ingress/overview.md)** — L7 маршрутизация для HTTP/HTTPS приложений
- **[Gateway API](../gateway_api/definitions.md)** — современная альтернатива Ingress
