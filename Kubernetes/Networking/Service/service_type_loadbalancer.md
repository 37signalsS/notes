# Тип Service — LoadBalancer

## Определения

**LoadBalancer** — тип Service в Kubernetes, который предоставляет службу внешнему поставщику облачных услуг. Он обеспечивает автоматическую подготовку и настройку внешнего балансировщика нагрузки в инфраструктуре облачного провайдера (AWS, GCP, Azure, OpenStack). Поставщик облачных услуг назначает сервису уникальный внешний IP-адрес или DNS-имя, позволяя получить к нему доступ извне кластера.

LoadBalancer является расширением типов [NodePort](./service_type_nodeport.md) и [ClusterIP](./service_type_clusterip.md). Трафик проходит следующий путь:
`Клиент → Облачный LB → NodePort (на узлах) → ClusterIP (виртуальный IP) → Pod`

**Основная задача:** Обеспечение высокодоступной точки входа для критических приложений с автоматическим управлением сетевой инфраструктурой облака.

## Основные концепции

### Механика реализации

При создании ресурса выполняются следующие этапы:

1. **Cloud Controller Manager (CCM):** Контроллер (или in-cluster оператор типа MetalLB) обнаруживает новый сервис и отправляет запрос к API провайдера. Начиная с K8s 1.31, код "in-tree" облачных провайдеров полностью удален из ядра K8s — вся интеграция работает только через внешние CCM.
2. **Provisioning:** Провайдер создает сетевой балансировщик (L4 по умолчанию, работает с TCP/UDP). Поддержка нескольких протоколов (Mixed Protocols) на одном LoadBalancer зависит от возможностей конкретного провайдера и настройки `ipFamilyPolicy`.
3. **Status Reporting:** После выделения IP-адреса или DNS-имени CCM обновляет поле `status.loadBalancer.ingress` в объекте Service.
4. **Finalizers:** Kubernetes добавляет финалайзер `service.kubernetes.io/load-balancer-cleanup`, который гарантирует, что облачный балансировщик будет удален только после успешного удаления объекта Service в кластере.

### Ключевые параметры спецификации

- **loadBalancerClass:** Позволяет указать конкретный контроллер балансировки (например, для использования нескольких разных провайдеров или MetalLB одновременно).
- **allocateLoadBalancerNodePorts:** Если установлено в `false`, Kubernetes не будет резервировать стандартные порты `NodePort` на узлах. Это актуально для провайдеров (или CNI, например, Cilium), поддерживающих прямую маршрутизацию трафика в поды (Direct Pod Routing).
- **healthCheckNodePort:** При `externalTrafficPolicy: Local` облачному LB требуется механизм проверки доступности подов на узле. Kubernetes автоматически выделяет для этого специальный порт, который LB опрашивает (HTTP). В K8s 1.30+ выделение этого порта можно отключить (зависит от поддержки в CCM), если провайдер имеет собственные механизмы health-check.
- **loadBalancerIP:** *(Deprecated в 1.30+)* Ранее использовалось для задания статического IP. Сейчас **строго рекомендуется** использовать аннотации облачного провайдера или конфигурации пулов (в MetalLB/Cilium).

### Ограничение доступа: loadBalancerSourceRanges и ipMode

Поле `spec.loadBalancerSourceRanges` позволяет ограничить доступ к сервису, принимая трафик только с указанных CIDR (работает через правила пакетного фильтра узла).
**Важное нововведение (K8s 1.30+):** Добавлено поле `status.loadBalancer.ingress.ipMode` для корректной маршрутизации "hairpin" трафика (когда под обращается к внешнему IP собственного сервиса) при использовании **Proxy Protocol** и строгих ограничений `loadBalancerSourceRanges`.

### Конфигурация через аннотации

Большинство настроек (тип балансировщика, SSL-сертификаты, внутренняя/внешняя область видимости) передаются через `metadata.annotations`.

| Среда / Облако | Пример аннотации | Назначение |
| :--- | :--- | :--- |
| **AWS** | `service.beta.kubernetes.io/aws-load-balancer-type: nlb` | Использование Network Load Balancer (вместо устаревшего Classic). |
| **GCP** | `networking.gke.io/load-balancer-type: "Internal"` | Создание внутреннего (частного) LB в рамках VPC. |
| **MetalLB** | `metallb.universe.tf/loadBalancerIPs: 192.168.10.50` | Назначение конкретного статического IP-адреса из локального пула. |

### Управление трафиком (Traffic Policies)

#### externalTrafficPolicy

Определяет, как балансировщик распределяет входящий трафик после его попадания на узел:

- **Cluster** *(по умолчанию)*: Трафик равномерно распределяется между всеми узлами. Если на узле нет нужного пода, запрос перенаправляется на другой узел. **Происходит SNAT** (подмена исходного IP клиента на IP узла).
- **Local**: Трафик направляется только на те узлы, где запущены целевые поды. Пересылка (hop) между узлами отсутствует. **Сохраняется исходный IP клиента (Source IP)**. Требует корректной настройки Health Checks (через `healthCheckNodePort`) на стороне LB для исключения маршрутизации на "пустые" узлы.

#### internalTrafficPolicy

Управляет маршрутизацией запросов, инициированных внутри кластера (East-West трафик) при обращении к внешнему адресу/имени балансировщика. В сочетании с `externalTrafficPolicy: Local` позволяет тонко тюнинговать производительность сети.

## Практические сценарии

### Стандартный публичный балансировщик (с ограничением доступа)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web-production-lb
spec:
  type: LoadBalancer
  loadBalancerSourceRanges:
    - 198.51.100.0/24 # Доступ только с этой подсети
  selector:
    app: frontend
  ports:
    - protocol: TCP
      port: 80         # Порт на балансировщике
      targetPort: 8080 # Порт в контейнере
```

### Внутренний балансировщик (Private LB в облаке)

Пример для AWS, создающий Network Load Balancer, доступный только внутри VPC. Сохраняет IP клиента.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-api
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-internal: "true"
    service.beta.kubernetes.io/aws-load-balancer-type: "nlb"
spec:
  type: LoadBalancer
  externalTrafficPolicy: Local
  selector:
    app: api
  ports:
    - port: 443
      targetPort: 8443
```

### Развертывание в Bare-Metal (MetalLB / Cilium)

В локальных или bare-metal средах LoadBalancer реализуется через in-cluster компоненты (например, MetalLB или Cilium L2/BGP).

```yaml
apiVersion: v1
kind: Service
metadata:
  name: metallb-service
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.10.50 # Запрашиваемый статический IP
spec:
  type: LoadBalancer
  loadBalancerClass: metallb.io/v1alpha1 # Явное указание контроллера, если их несколько
  selector:
    app: my-app
  ports:
    - port: 80
      targetPort: 8080
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
