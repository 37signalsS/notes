# LoadBalancer

## Определения

**LoadBalancer** — тип Service, который создает внешний балансировщик нагрузки у облачного провайдера (AWS, GCP, Azure). Балансировщик получает публичный IP-адрес и направляет трафик на `Service`.

LoadBalancer является расширением [NodePort](./service_type_nodeport.md) и [ClusterIP](./service_type_clusterip.md):

```
External Traffic → Cloud LB → NodePort → ClusterIP → Pod
```

## Основные концепции

### Принцип работы

При создании Service типа LoadBalancer:

1. Kubernetes запрашивает создание внешнего балансировщика через API облачного провайдера
2. Облачный провайдер создает балансировщик (например, AWS ELB) с публичным IP
3. Балансировщик направляет трафик на `NodePort` (автоматически созданный) на всех узлах
4. `kube-proxy` перенаправляет трафик на Pod
5. Облачный балансировщик выполняет **health-check** на уровне провайдера

### Требования

- **Облачный провайдер:** Работает "из коробки" только в облаках (AWS, GCP, Azure)
- **Контроллер:** Требуется cloud-controller-manager для взаимодействия с API провайдера
- **On-premise:** Для bare-metal кластеров используйте [MetalLB](../Addons/metallb.md)

### externalTrafficPolicy

Для сохранения реального IP-адреса клиента используйте:

```yaml
spec:
  externalTrafficPolicy: Local
```

Подробное описание работы `externalTrafficPolicy` см. в [документации NodePort](./service_type_nodeport.md#externaltrafficpolicy-local).

### Статический IP-адрес

```yaml
spec:
  type: LoadBalancer
  loadBalancerIP: "1.1.1.1"  # Статический IP (поддерживается не всеми провайдерами)
```

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

### Распространенные use-case

- **Публикация в production:** Стандартный способ в облачных средах
- **TCP/UDP приложения:** Базы данных, кэши, message brokers
- **Не-HTTP трафик:** Прямая публикация сервисов без Ingress

## Дополнительная информация

### Ограничения

| Ограничение | Описание |
|-------------|----------|
| **L4 only** | Работает только на транспортном уровне (TCP/UDP), без понимания HTTP |
| **Один IP на сервис** | Каждый сервис требует отдельный внешний IP |
| **Зависимость от провайдера** | Не работает в bare-metal без дополнительных компонентов |
| **Стоимость** | Каждый LoadBalancer = отдельный ресурс в облаке |

### Когда использовать Ingress вместо LoadBalancer

Для HTTP/HTTPS приложений предпочтительнее использовать [Ingress](../Ingress/overview.md):

| Критерий | LoadBalancer | Ingress |
|----------|--------------|---------|
| **Уровень** | L4 (TCP/UDP) | L7 (HTTP/HTTPS) |
| **Маршрутизация** | По порту | По хосту, пути, заголовкам |
| **IP-адреса** | Один сервис = один IP | Множество сервисов через один IP |
| **SSL/TLS** | На уровне сервиса | Централизованное управление |

### Переход к другим типам

- Для внутреннего доступа: [ClusterIP](./service_type_clusterip.md)
- Для разработки/on-prem: [NodePort](./service_type_nodeport.md)
- Для HTTP приложений: [Ingress](../Ingress/overview.md)
- Полная сводка типов: [service_types_summary.md](./service_types_summary.md)
