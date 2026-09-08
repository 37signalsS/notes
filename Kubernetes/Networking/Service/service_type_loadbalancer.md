# Тип Service — LoadBalancer

## Определения

**LoadBalancer** — тип Service в Kubernetes, который предоставляет службу внешнему поставщику облачных услуг. Он обеспечивает автоматическую подготовку и настройку внешнего балансировщика нагрузки в инфраструктуре облачного провайдера (AWS, GCP, Azure, OpenStack). Поставщик облачных услуг назначает сервису уникальный внешний IP-адрес или DNS-имя, позволяя получить к нему доступ извне кластера.

LoadBalancer является расширением типов [NodePort](./service_type_nodeport.md) и [ClusterIP](./service_type_clusterip.md). Трафик проходит следующий путь:
`Клиент → Облачный LB → NodePort (на узлах) → ClusterIP (виртуальный IP) → Pod`

**Основная задача:** Обеспечение высокодоступной точки входа для критических приложений с автоматическим управлением сетевой инфраструктурой облака.

## Предварительные требования

Для работы с LoadBalancer Service необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для поддержки `loadBalancerClass` и современных CCM)
- **Cloud Controller Manager (CCM)** — компонент для интеграции с облачным провайдером или in-cluster решение (MetalLB, Cilium) для bare-metal
- **kubectl** — CLI-инструмент для управления ресурсами кластера
- **Сетевой доступ** — узлы должны иметь возможность получать трафик от внешнего балансировщика

**Проверка готовности окружения:**
```bash
# Проверка работы CCM (для облачных кластеров)
kubectl get pods -n kube-system | grep cloud-controller-manager
# → Должен быть Running (если используется облачный провайдер)

# Проверка MetalLB (для bare-metal)
kubectl get pods -n metallb-system
# → controller и speaker должны быть Running

# Проверка существующих LoadBalancer-сервисов
kubectl get svc -A | grep LoadBalancer
# → Показывает текущие сервисы и их внешние IP

# Проверка статуса балансировщика
kubectl get svc web-production-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
# → Должен вернуть назначенный внешний IP
```

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

**Валидация созданного сервиса:**
```bash
# Проверка создания сервиса и назначения внешнего IP
kubectl get svc web-production-lb
# → NAME               TYPE           EXTERNAL-IP     PORT(S)        AGE
# → web-production-lb  LoadBalancer   198.51.100.10   80:31234/TCP   30s

# Проверка статуса балансировщика
kubectl get svc web-production-lb -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
# → 198.51.100.10

# Проверка ограничения доступа (должен быть отклонен с неразрешенного IP)
curl -I http://198.51.100.10:80
# → С разрешенного IP: HTTP/1.1 200 OK
# → С неразрешенного IP: Connection timeout

# Проверка доступности подов
kubectl get endpoints web-production-lb
# → NAME               ENDPOINTS                     AGE
# → web-production-lb  10.244.1.5:8080,10.244.2.3:8080  1m

# Проверка логов CCM (при проблемах с созданием LB)
kubectl logs -n kube-system deployment/cloud-controller-manager | grep web-production-lb
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

**Валидация созданного сервиса:**
```bash
# Проверка создания сервиса и назначения IP из пула MetalLB
kubectl get svc metallb-service
# → NAME             TYPE           EXTERNAL-IP      PORT(S)        AGE
# → metallb-service  LoadBalancer   192.168.10.50    80:31234/TCP   30s

# Проверка статуса в _conditions_ (MetalLB specific)
kubectl get svc metallb-service -o yaml | grep -A 5 "conditions"
# → conditions:
# → - type: LoadBalancerReady
# →   status: "True"

# Проверка доступности сервиса по назначенному IP
curl -I http://192.168.10.50:80
# → HTTP/1.1 200 OK

# Проверка ARP-таблиц (для режима L2 MetalLB)
ip neigh | grep 192.168.10.50
# → 192.168.10.50 dev eth0 lladdr 00:1a:2b:3c:4d:5e REACHABLE

# Проверка логов MetalLB controller (при проблемах)
kubectl logs -n metallb-system deployment/controller | grep metallb-service
```

## Устранение неполадок (Troubleshooting)

### Проблема 1: LoadBalancer не получает внешний IP (Pending)

**Симптом:** Сервис создан, но поле `EXTERNAL-IP` в статусе `<pending>` длительное время.

**Диагностика:**
```bash
# Проверка статуса сервиса
kubectl get svc web-production-lb
# → NAME               TYPE           EXTERNAL-IP   PORT(S)        AGE
# → web-production-lb  LoadBalancer   <pending>     80:31234/TCP   5m

# Проверка событий сервиса
kubectl describe svc web-production-lb | grep -A 10 "Events:"
# → Содержит ошибки от CCM или MetalLB

# Проверка логов CCM
kubectl logs -n kube-system deployment/cloud-controller-manager --tail=50

# Проверка логов MetalLB (для bare-metal)
kubectl logs -n metallb-system deployment/controller --tail=50
```

**Типичные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| CCM не запущен | `kubectl get pods -n kube-system \| grep cloud-controller` | Запустить CCM или проверить конфигурацию |
| MetalLB не установлен | `kubectl get pods -n metallb-system` — нет подов | Установить MetalLB |
| Пул адресов исчерпан | Логи MetalLB: "no available IPs" | Расширить IPAddressPool |
| Нет доступных узлов | `kubectl get nodes` — узлы не Ready | Проверить состояние узлов |
| Квота облака исчерпана | Логи CCM: "Quota exceeded" | Запросить увеличение квоты |

### Проблема 2: Трафик не доходит до подов

**Симптом:** Внешний IP назначен, но запросы возвращают ошибку или таймаут.

**Диагностика:**
```bash
# Проверка endpoints сервиса
kubectl get endpoints web-production-lb
# → Должен содержать IP подов, иначе проблема с селектором

# Проверка доступности подов напрямую
kubectl exec -it <pod-name> -- curl -I http://localhost:8080
# → Должен вернуть 200 OK

# Проверка сетевой связности от узла к поду
kubectl run debug --rm -it --image=busybox -- wget -qO- http://10.244.1.5:8080
# → Должен вернуть ответ приложения

# Проверка правил iptables/ipvs (kube-proxy)
iptables -t nat -L -n | grep web-production-lb
# → Должны быть правила для перенаправления трафика
```

**Типичные причины:**
- Селектор сервиса не соответствует меткам подов
- Поды не проходят readiness probe
- NetworkPolicy блокирует трафик
- Неправильный targetPort в манифесте

### Проблема 3: Потеря Source IP клиента

**Симптом:** Приложение видит все запросы с IP узла, а не реального клиента.

**Диагностика:**
```bash
# Проверка текущей политики трафика
kubectl get svc web-production-lb -o yaml | grep externalTrafficPolicy
# → externalTrafficPolicy: Cluster (по умолчанию — теряет Source IP)

# Проверка через приложение (логи показывают IP узла)
kubectl logs <pod-name> | grep "client-ip"
# → Все запросы с 10.244.x.x (IP узла)
```

**Решение:**
```yaml
spec:
  externalTrafficPolicy: Local  # Сохраняет Source IP
```
**Важно:** При `externalTrafficPolicy: Local` необходимо настроить health checks на балансировщике, иначе трафик может направляться на узлы без подов.

### Проблема 4: Health Check не работает при externalTrafficPolicy: Local

**Симпом:** После изменения политики на `Local` часть запросов получает ошибку 502/503.

**Диагностика:**
```bash
# Проверка распределения подов по узлам
kubectl get pods -o wide -l app=frontend
# → Если на узле нет подов, трафик не должен на него направляться

# Проверка healthCheckNodePort
kubectl get svc web-production-lb -o yaml | grep healthCheckNodePort
# → healthCheckNodePort: 32000 (автоматически назначенный порт)

# Проверка доступности health check
curl http://<node-ip>:32000/healthz
# → Если на узле есть под: 200 OK
# → Если на узле нет подов: 503 Service Unavailable
```

**Решение:** Убедиться, что облачный LB использует `healthCheckNodePort` для проверки доступности узлов.

## Best Practices

1. **Используйте Ingress для HTTP/HTTPS:** Для веб-приложений предпочтительнее Ingress или Gateway API — это экономит стоимость (один LB на много сервисов) и дает гибкую маршрутизацию.

2. **Ограничивайте доступ по IP:** Всегда используйте `loadBalancerSourceRanges` для ограничения доступа к критическим сервисам:
   ```yaml
   loadBalancerSourceRanges:
     - 10.0.0.0/8
     - 192.168.10.0/24
   ```

3. **Сохраняйте Source IP при необходимости:** Используйте `externalTrafficPolicy: Local` для приложений, которым нужен реальный IP клиента. Не забудьте настроить health checks.

4. **Мониторьте квоты и стоимость:** Каждый LoadBalancer в облаке платный. Регулярно проверяйте использование и удаляйте неиспользуемые сервисы.

5. **Используйте аннотации для тонкой настройки:** Тип балансировщика, SSL-сертификаты, внутренняя/внешняя область видимости — всё это настраивается через аннотации облачного провайдера.

6. **Фиксируйте IP для критических сервисов:** Используйте аннотации провайдера или MetalLB для назначения статического IP, чтобы избежать изменения адреса при пересоздании сервиса.

7. **Настройте мониторинг доступности:** Используйте Prometheus Blackbox Exporter или аналогичные инструменты для проверки доступности сервиса через балансировщик.

## Edge Cases и ограничения

1. **Зависимость от провайдера:** Поведение LoadBalancer сильно зависит от реализации CCM конкретного облачного провайдера. Не все функции поддерживаются всеми провайдерами.

2. **Ограничение на протоколы:** По умолчанию LoadBalancer работает с TCP/UDP. Поддержка других протоколов (SCTP, QUIC) зависит от провайдера.

3. **Задержка при создании:** Создание облачного балансировщика может занимать от 30 секунд до нескольких минут. Это необходимо учитывать при автоматизации.

4. **Невозможность изменения типа:** Поле `type` Service неизменяемое. Для смены типа требуется удаление и создание сервиса заново.

5. **Проблемы с hairpin трафиком:** Когда под обращается к внешнему IP собственного сервиса, могут возникнуть проблемы с маршрутизацией. Используйте `ipMode` (K8s 1.30+) для корректной обработки.

6. **Ограничение на количество портов:** Облачные LB могут иметь лимиты на количество портов/правил. Уточняйте у провайдера.

7. **Finalizer блокирует удаление:** При удалении сервиса finalizer `service.kubernetes.io/load-balancer-cleanup` может заблокировать удаление, если CCM не может удалить облачный балансировщик. Проверьте логи CCM.

8. **MetalLB L2 ограничение:** В режиме L2 весь трафик проходит через один узел (лидер), что создает бутылочное горлышко. Для высоких нагрузок используйте BGP режим.

## Очистка и откат изменений

```bash
# Просмотр всех LoadBalancer-сервисов
kubectl get svc -A | grep LoadBalancer

# Удаление конкретного сервиса
kubectl delete svc web-production-lb
# → service "web-production-lb" deleted

# Удаление сервиса по манифесту
kubectl delete -f loadbalancer-service.yaml

# Проверка удаления облачного балансировщика (AWS пример)
aws elbv2 describe-load-balancers --names web-production-lb
# → Балансировщик должен быть удален автоматически

# Принудительное удаление при зависшем finalizer
kubectl patch svc web-production-lb -p '{"metadata":{"finalizers":null}}'
# → Использовать только если облачный LB уже удален вручную
```

**Важно:** При удалении LoadBalancer-сервиса облачный балансировщик удаляется автоматически через finalizer. Убедитесь, что на сервис нет зависимых ресурсов (Ingress, DNS-записи).

## Дополнительная информация

### Ключевые ограничения

- **Стоимость:** Каждый инстанс LoadBalancer в облаке платный. Для экономии ресурсов (один IP на много сервисов) рекомендуется использовать **Ingress** или **Gateway API**.
- **Квоты:** Облачные провайдеры имеют лимиты на количество балансировщиков в одном регионе/аккаунте.
- **Безопасность:** По умолчанию балансировщик открыт для всего интернета (`0.0.0.0/0`). Используйте `spec.loadBalancerSourceRanges` для ограничения доступа по IP.
- **Зависимость от провайдера:** Поведение LoadBalancer сильно зависит от реализации CCM конкретного облачного провайдера.

### Сравнение с альтернативами

| Характеристика | LoadBalancer | Ingress | Gateway API |
| :--- | :--- | :--- | :--- |
| **Уровень OSI** | L4 (TCP/UDP) | L7 (HTTP/HTTPS) | L4/L7 |
| **Сложность** | Низкая (один объект) | Средняя (Service + Ingress) | Высокая (несколько CRD) |
| **Балансировка** | Простая (Round Robin) | Гибкая (Пути, Хосты) | Максимальная (Advanced) |

### См. также

- [Обзор Service](./service_overview.md) — общая информация о Service
- [Сводка по типам Service](./service_types_summary.md) — сравнение всех типов Service
- [Тип Service — NodePort](./service_type_nodeport.md) — базовый тип для LoadBalancer
- [Обзор Ingress](../Ingress/overview.md) — альтернатива для HTTP/HTTPS
- [Механизмы MetalLB](../metallb.md) — LoadBalancer для bare-metal
