# Сводка по типам сервисов Kubernetes

## Определения

Kubernetes предоставляет несколько типов **Service** для различных сценариев доступа к приложениям. Выбор типа определяет **границы доступности** (внутри кластера vs. извне) и **способ маршрутизации** трафика.

## Основные концепции

### Иерархия типов

Все типы сервисов (кроме ExternalName) построены на базе **ClusterIP**:

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
| **Внутреннее взаимодействие** | ClusterIP |
| **Разработка/отладка** | NodePort или kubectl port-forward |
| **Production в облаке** | LoadBalancer или Ingress |
| **On-premise production** | NodePort + внешний LB или MetalLB |
| **HTTP/HTTPS приложения** | Ingress (L7) вместо LoadBalancer (L4) |

## Практические сценарии

### Сводная таблица типов сервисов

| Тип | Доступность | Основной сценарий | Ограничения |
|-----|-------------|-------------------|-------------|
| **[ClusterIP](./service_type_clusterip.md)** | Только внутри кластера | Внутренние коммуникации (backend-to-db) | Нет прямого внешнего доступа |
| **[NodePort](./service_type_nodeport.md)** | Внутри и снаружи (через `IP_узла:NodePort`) | Разработка, отладка, простой внешний доступ, on-prem | Диапазон портов 30000-32767, зависимость от IP узла |
| **[LoadBalancer](./service_type_loadbalancer.md)** | Из интернета (через внешний IP от облака) | Публикация приложений в облаке (production) | Зависит от облачного провайдера; в bare-metal требует MetalLB |
| **ExternalName** | Только DNS (CNAME) | Доступ к внешним сервисам по внутреннему имени | Не проксирует трафик, работает только на уровне DNS |
| **Headless** | Прямой доступ к Pod-ам | Stateful-приложения (StatefulSet), service discovery | Нет балансировки на уровне Service |

### Сравнение по уровням OSI

| Тип | Уровень OSI | Протоколы | Маршрутизация |
|-----|-------------|-----------|---------------|
| ClusterIP | L4 | TCP, UDP | IP + порт |
| NodePort | L4 | TCP, UDP | IP узла + порт |
| LoadBalancer | L4 | TCP, UDP | Публичный IP + порт |
| Ingress | L7 | HTTP, HTTPS | Хост, путь, заголовки |

### Решение для распространенных задач

#### Задача: Доступ к базе данных из приложения
**Решение:** [ClusterIP](./service_type_clusterip.md)
```yaml
spec:
  type: ClusterIP
  ports:
    - port: 5432  # PostgreSQL
```

#### Задача: Демо/отладка приложения
**Решение:** [NodePort](./service_type_nodeport.md) или `kubectl port-forward`
```bash
# Быстрый доступ для разработки
kubectl port-forward svc/my-app 8080:80
```

#### Задача: Публикация API в production (облако)
**Решение:** [LoadBalancer](./service_type_loadbalancer.md) для TCP или [Ingress](../Ingress/overview.md) для HTTP
```yaml
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Для сохранения IP клиента
```

#### Задача: Публикация в on-premise кластере
**Решение:** [NodePort](./service_type_nodeport.md) + внешний балансировщик или MetalLB
```yaml
spec:
  type: NodePort
  # + внешний HAProxy/Nginx балансирует на NodeIP:NodePort
```

## Дополнительная информация

### ExternalIPs

Помимо стандартных типов, можно использовать поле `externalIPs` для назначения внешних IP-адресов сервису:

```yaml
spec:
  type: ClusterIP
  externalIPs:
    - 203.0.113.1
```

**Ограничение:** Требует ручной настройки маршрутизации на узлах.

### Headless Service

Для Stateful-приложений создается сервис без ClusterIP (`clusterIP: None`):

```yaml
spec:
  clusterIP: None  # Headless
  selector:
    app: my-stateful-app
```

DNS возвращает IP-адреса всех Pod напрямую, позволяя клиенту самому выбирать под.

### Дополнительные ресурсы

- [Обзор Service](./service_overview.md) — базовые концепции и архитектура
- [ClusterIP](./service_type_clusterip.md) — внутренние коммуникации
- [NodePort](./service_type_nodeport.md) — публикация через порт узла
- [LoadBalancer](./service_type_loadbalancer.md) — облачный балансировщик
- [Ingress](../Ingress/overview.md) — L7 маршрутизация для HTTP/HTTPS
