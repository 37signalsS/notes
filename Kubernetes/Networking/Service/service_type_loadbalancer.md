# LoadBalancer

## Определения

**LoadBalancer** — тип Service, создающий внешний балансировщик нагрузки у облачного провайдера (AWS, GCP, Azure). Балансировщик получает публичный IP-адрес и направляет трафик на сервис.

LoadBalancer расширяет [NodePort](./service_type_nodeport.md) и [ClusterIP](./service_type_clusterip.md):

```
External Traffic → Cloud LB → NodePort → ClusterIP → Pod
```

**Ключевое отличие:** Единственный тип сервиса, автоматически создающий внешнюю инфраструктуру в облаке.

## Основные концепции

### Принцип работы

При создании Service типа LoadBalancer:

1. Kubernetes запрашивает создание внешнего балансировщика через API облачного провайдера
2. Облачный провайдер создаёт балансировщик (AWS ELB, GCP Load Balancing, Azure LB) с публичным IP
3. Балансировщик направляет трафик на `NodePort` (автоматически создаётся) на всех узлах
4. `kube-proxy` перенаправляет трафик на Pod
5. Облачный балансировщик выполняет **health-check** на уровне провайдера

### Требования

| Требование | Описание |
| :--- | :--- |
| **Облачный провайдер** | Работает "из коробки" в AWS, GCP, Azure |
| **Контроллер** | Требуется cloud-controller-manager для взаимодействия с API провайдера |
| **On-premise** | Для bare-metal используйте [MetalLB](../metallb.md) |

### externalTrafficPolicy

Для сохранения реального IP-адреса клиента:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local  # Сохраняет IP клиента
  ports:
    - port: 80
      targetPort: 80
```

**Режимы работы:**

| Режим | Описание |
| :--- | :--- |
| **Cluster** (по умолчанию) | Трафик может перенаправляться на Pod на другом узле, IP клиента теряется |
| **Local** | Трафик только на локальные Pod, сохраняется IP клиента, возможна неравномерная балансировка |

> **Подробно:** [externalTrafficPolicy в NodePort](./service_type_nodeport.md#externaltrafficpolicy-local)

### Статический IP-адрес

```yaml
spec:
  type: LoadBalancer
  loadBalancerIP: "1.1.1.1"  # Статический IP (поддерживается не всеми провайдерами)
```

**Важно:** Поле `loadBalancerIP` депрецируется. Для статических IP используйте аннотации провайдера или `Gateway API`.

## Практические сценарии

### Пример манифеста

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service-lb
spec:
  selector:
    app: my-app
  type: LoadBalancer
  ports:
    - name: http
      port: 80
      targetPort: 80
      protocol: TCP
```

### Пример с сохранением IP клиента

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service-lb-local
spec:
  selector:
    app: my-app
  type: LoadBalancer
  externalTrafficPolicy: Local  # Сохраняем реальный IP клиента
  ports:
    - name: http
      port: 80
      targetPort: 80
```

### Распространённые use-case

| Сценарий | Описание |
| :--- | :--- |
| **Production в облаке** | Стандартный способ публикации приложений в AWS, GCP, Azure |
| **TCP/UDP приложения** | Базы данных, кэши, message brokers (не-HTTP трафик) |
| **Прямая публикация** | Сервисы без Ingress, требующие отдельного внешнего IP |

## Дополнительная информация

### Ограничения

| Ограничение | Описание |
| :--- | :--- |
| **L4 only** | Работает на транспортном уровне (TCP/UDP), без понимания HTTP |
| **Один IP на сервис** | Каждый сервис требует отдельный внешний IP |
| **Зависимость от провайдера** | Не работает в bare-metal без дополнительных компонентов (MetalLB) |
| **Стоимость** | Каждый LoadBalancer = отдельный платный ресурс в облаке |

### LoadBalancer vs Ingress

Для HTTP/HTTPS приложений предпочтительнее использовать [Ingress](../Ingress/overview.md):

| Критерий | LoadBalancer | Ingress |
| :--- | :--- | :--- |
| **Уровень OSI** | L4 (TCP/UDP) | L7 (HTTP/HTTPS) |
| **Маршрутизация** | По порту | По хосту, пути, заголовкам |
| **IP-адреса** | Один сервис = один IP | Множество сервисов через один IP |
| **SSL/TLS** | На уровне сервиса | Централизованное управление |
| **Стоимость** | Платный ресурс за каждый сервис | Один балансировщик на множество сервисов |

### Альтернативы для bare-metal

| Решение | Описание |
| :--- | :--- |
| **[MetalLB](../metallb.md)** | Балансировщик для bare-metal кластеров (L2/BGP режимы) |
| **NodePort + внешний LB** | Внешний балансировщик направляет трафик на NodePort |
| **[Gateway API](../gateway_api/definitions.md)** | Современная альтернатива Ingress с поддержкой LoadBalancer |

### Связанные концепции

- **[ClusterIP](./service_type_clusterip.md)** — базовый тип для внутреннего доступа
- **[NodePort](./service_type_nodeport.md)** — публикация через порт узла
- **[Ingress](../Ingress/overview.md)** — L7 маршрутизация для HTTP/HTTPS
- **[Сводка типов сервисов](./service_types_summary.md)** — полное сравнение всех типов
