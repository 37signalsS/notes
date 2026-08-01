# Тип Service — LoadBalancer

## Определения

**LoadBalancer** — тип Service в Kubernetes, который предоставляет службу внешнему поставщику облачных услуг. Он обеспечивает автоматическую подготовку и настройку внешнего балансировщика нагрузки в инфраструктуре облачного провайдера (AWS, GCP, Azure, OpenStack). Поставщик облачных услуг назначает сервису уникальный внешний IP-адрес или DNS-имя, позволяя получить к нему доступ извне кластера.

LoadBalancer является расширением типов [NodePort](./service_type_nodeport.md) и [ClusterIP](./service_type_clusterip.md). Трафик проходит следующий путь:
`Клиент → Облачный LB → NodePort (на узлах) → ClusterIP (виртуальный IP) → Pod`

**Основная задача:** Обеспечение высокодоступной точки входа для критических приложений с автоматическим управлением сетевой инфраструктурой облака.

## Основные концепции

### Механика реализации

При создании ресурса выполняются следующие этапы:

1. **Cloud Controller Manager (CCM):** Контроллер обнаруживает новый сервис и отправляет запрос к API облачного провайдера.
2. **Provisioning:** Провайдер создает сетевой балансировщик (L4 по умолчанию).
3. **Status Reporting:** После выделения IP-адреса или DNS-имени CCM обновляет поле `status.loadBalancer.ingress` в объекте Service.
4. **Finalizers:** Kubernetes добавляет финалайзер `service.kubernetes.io/load-balancer-cleanup`, который гарантирует, что облачный балансировщик будет удален только после успешного удаления объекта Service в кластере.

### Ключевые параметры спецификации

- **loadBalancerClass:** Позволяет указать конкретный контроллер балансировки (например, для использования нескольких разных провайдеров или MetalLB одновременно).
- **allocateLoadBalancerNodePorts:** Если установлено в `false`, Kubernetes не будет резервировать `NodePort` на узлах. Это актуально для провайдеров, поддерживающих прямую маршрутизацию трафика в поды (например, через VPC CNI).
- **loadBalancerIP:** (Deprecated) Ранее использовалось для задания статического IP. Сейчас рекомендуется использовать аннотации провайдера.

### Конфигурация через аннотации

Большинство настроек (тип балансировщика, SSL-сертификаты, внутренняя/внешняя область видимости) передаются через `metadata.annotations`.

| Облако | Пример аннотации | Назначение |
| :--- | :--- | :--- |
| **AWS** | `service.beta.kubernetes.io/aws-load-balancer-type: nlb` | Использование Network Load Balancer |
| **GCP** | `networking.gke.io/load-balancer-type: "Internal"` | Создание внутреннего (частного) LB |
| **Azure** | `service.beta.kubernetes.io/azure-load-balancer-internal: "true"` | Внутренний балансировщик в VNet |

## Управление трафиком

### externalTrafficPolicy

Определяет, как балансировщик распределяет трафик между узлами:

- **Cluster** (по умолчанию): Трафик может быть перенаправлен на любой узел. Происходит SNAT (подмена IP клиента на IP узла).
- **Local**: Трафик направляется только на узлы, где запущены целевые поды. Сохраняется исходный IP клиента (Source IP). Требует корректной настройки Health Checks на стороне облачного LB.

### internalTrafficPolicy

Управляет маршрутизацией запросов, инициированных внутри кластера при обращении к внешнему адресу/имени балансировщика.

## Практические сценарии

### Стандартный публичный балансировщик

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-production-lb
spec:
  type: LoadBalancer
  selector:
    app: frontend
  ports:
    - protocol: TCP
      port: 80         # Порт на балансировщике
      targetPort: 8080 # Порт в контейнере
```

### Внутренний балансировщик (Private LB)

Пример для AWS, создающий балансировщик, доступный только внутри VPC.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-api
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-internal: "true"
spec:
  type: LoadBalancer
  selector:
    app: api
  ports:
    - port: 443
      targetPort: 8443
```

### Использование конкретного LoadBalancer Class

```yaml
apiVersion: v1
kind: Service
metadata:
  name: metallb-service
spec:
  type: LoadBalancer
  loadBalancerClass: metallb.io/v1alpha1 # Явное указание контроллера
  selector:
    app: my-app
  ports:
    - port: 80
```

## Дополнительная информация

### Ограничения и риски

- **Стоимость:** Каждый инстанс LoadBalancer в облаке платный. Для экономии ресурсов (один IP на много сервисов) рекомендуется использовать **Ingress** или **Gateway API**.
- **Квоты:** Облачные провайдеры имеют лимиты на количество балансировщиков в одном регионе/аккаунте.
- **Безопасность:** По умолчанию балансировщик открыт для всего интернета (`0.0.0.0/0`). Используйте `spec.loadBalancerSourceRanges` для ограничения доступа по IP.

### Сравнение с альтернативами

| Характеристика | LoadBalancer | Ingress | Gateway API |
| :--- | :--- | :--- | :--- |
| **Уровень OSI** | L4 (TCP/UDP) | L7 (HTTP/HTTPS) | L4/L7 |
| **Сложность** | Низкая (один объект) | Средняя (Service + Ingress) | Высокая (несколько CRD) |
| **Балансировка** | Простая (Round Robin) | Гибкая (Пути, Хосты) | Максимальная (Advanced) |

### См. также

- [Обзор Service](./service_overview.md)
- [Сводка по типам Service](./service_types_summary.md)
- [Тип Service — NodePort](./service_type_nodeport.md)
- [Обзор Ingress](../Ingress/overview.md)
- [Механизмы MetalLB](../metallb.md)
