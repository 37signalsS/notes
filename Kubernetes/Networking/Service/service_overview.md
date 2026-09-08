# Обзор Service

## Определения

**Service (Сервис)** — абстрактный ресурс Kubernetes, обеспечивающий стабильную сетевую связность, обнаружение (Discovery) и балансировку нагрузки для динамического набора подов. Он выступает в роли долгоживущей точки входа (Virtual IP или DNS-имя), которая инкапсулирует эфемерность IP-адресов подов и гарантирует доступность приложения даже при сбоях, обновлениях или масштабировании отдельных реплик.

**Ключевые функции:**
- **Service Discovery:** Автоматическая регистрация и обнаружение актуальных IP-адресов подов.
- **Балансировка нагрузки:** Распределение входящих запросов между работоспособными подами (L4).
- **Изоляция сети:** Скрытие внутренних IP-адресов подов за единым стабильным интерфейсом.

## Предварительные требования

Для работы с Service необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для поддержки EndpointSlices) или 1.31+ (для стабильной поддержки nftables и trafficDistribution)
- **CNI-плагин** (Calico, Flannel, Cilium или аналог) — обеспечивает базовую связность подов
- **kube-proxy** — DaemonSet, развёрнутый на всех узлах кластера (или eBPF-замена, например Cilium kube-proxy replacement)
- **CoreDNS** — кластерный DNS-сервер для Service Discovery через имена
- **kubectl** — CLI-инструмент для управления ресурсами кластера

**Проверка готовности окружения:**
```bash
# Проверка статуса kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy
# → Все поды должны быть в статусе Running и Ready

# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть в статусе Running и Ready

# Проверка CNI
kubectl -n kube-system get pods -l k8s-app=calico-node  # для Calico
# или
kubectl -n kube-system get pods -l k8s-app=cilium  # для Cilium
```

## Основные концепции

### Проблема эфемерности IP-адресов подов

IP-адреса подов в Kubernetes являются **эфемерными (временными)**:
- IP привязан к поду только на время его жизненного цикла.
- При удалении пода (сбой, обновление Deployment, вытеснение) новый под получает другой IP.
- Поды не «перезапускаются» — старый объект удаляется, а контроллер создает новый с другими именем и сетевым адресом.

**Следствие:** Прямое использование IP-адресов подов для межсервисного взаимодействия невозможно в динамической среде. Service решает эту проблему, предоставляя стабильный **ClusterIP**, который остается неизменным до удаления самого объекта Service.

### Механизм работы через Labels и Selectors

Связь между Service и подами устанавливается через **метки (labels)** и **селекторы (selectors)**:

1.  **Labels (Метки):** Подам назначаются пары ключ-значение (например, `app.kubernetes.io/name: nginx`).
2.  **Selector (Селектор):** В спецификации Service указывается селектор, соответствующий этим меткам.

**EndpointSlice Controller** (в составе `kube-controller-manager`) автоматически отслеживает поды с указанными метками и обновляет список эндпоинтов (Endpoints/EndpointSlices), направляя трафик только на работоспособные поды, прошедшие проверку `Readiness Probe`.

### Спецификация Service: Ключевые поля

| Поле | Описание |
| :--- | :--- |
| `selector` | Группа меток для идентификации целевых подов. |
| `ports` | Массив определений портов (протокол, входящий порт, порт назначения). |
| `type` | Тип сервиса: `ClusterIP` (дефолт), `NodePort`, `LoadBalancer`, `ExternalName`. |
| `clusterIP` | Стабильный внутренний IP. При значении `None` создается **Headless Service**. |
| `internalTrafficPolicy` | Определяет, как маршрутизируется внутренний трафик (`Cluster` или `Local`). |
| `externalTrafficPolicy` | Определяет, как обрабатывается внешний трафик (`Cluster` или `Local`). |
| `ipFamilyPolicy` | Настройка стека IP: `SingleStack`, `PreferDualStack`, `RequireDualStack`. |
| `trafficDistribution` | (v1.31+) Стратегия распределения трафика (например, `PreferClose`). |

#### Спецификация портов: port vs targetPort

| Параметр | Описание |
| :--- | :--- |
| **`port`** | Порт, который «слушает» сам Service внутри сети кластера. |
| **`targetPort`** | Порт приложения внутри контейнера. Можно использовать числа или **имена**. |
| **`name`** | Обязательно при наличии нескольких портов в одном Service. |

**Именованные порты:** Позволяют абстрагироваться от номеров портов в Service. Если в Pod порт `8080` назван `http-api`, в Service можно указать `targetPort: http-api`. Это упрощает обновление портов приложения без изменения манифестов Service.

### Полный пример манифеста Service

Рабочий пример для публикации веб-приложения с именованными портами:

```yaml
# service-example.yaml
apiVersion: v1
kind: Service
metadata:
  name: web-frontend
  namespace: production
  labels:
    app.kubernetes.io/name: web-frontend
    app.kubernetes.io/component: frontend
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: web-frontend
  ports:
    - name: http
      protocol: TCP
      port: 80          # Порт сервиса внутри кластера
      targetPort: http-web  # Именованный порт приложения в поде
    - name: metrics
      protocol: TCP
      port: 9090        # Порт для метрик Prometheus
      targetPort: metrics
```

**Соответствующий Pod с именованными портами:**
```yaml
# pod-with-named-ports.yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-frontend-pod
  namespace: production
  labels:
    app.kubernetes.io/name: web-frontend
spec:
  containers:
    - name: nginx
      image: nginx:1.25
      ports:
        - name: http-web
          containerPort: 8080
        - name: metrics
          containerPort: 9090
```

**Применение и проверка:**
```bash
# Применение манифестов
kubectl apply -f service-example.yaml
kubectl apply -f pod-with-named-ports.yaml

# Проверка созданных ресурсов
kubectl get svc web-frontend -n production
# NAME           TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)            AGE
# web-frontend   ClusterIP   10.96.100.50    <none>        80/TCP,9090/TCP    5s

# Проверка эндпоинтов
kubectl get endpointslices -l kubernetes.io/service-name=web-frontend -n production
# NAME                        ADDRESSTYPE   PORTS   ENDPOINTS   AGE
# web-frontend-abc123         IPv4          8090    10.244.1.5  10s
```

### Multi-protocol Services

Kubernetes позволяет открывать несколько портов в одном Service с разными протоколами. Это критично для приложений, использующих несколько транспортных протоколов.

**Пример мультипротокольного сервиса (TCP + UDP):**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: multi-proto-app
spec:
  selector:
    app: my-dns-service
  ports:
    - name: dns-tcp
      protocol: TCP
      port: 53
      targetPort: 53
    - name: dns-udp
      protocol: UDP
      port: 53
      targetPort: 53
```

**Важные особенности:**
- Имена портов **обязательны** при использовании нескольких портов с одним номером (как в примере выше — два порта 53 с разными протоколами)
- `protocol` по умолчанию: `TCP`
- Поддержка `SCTP` доступна с Kubernetes 1.12+ (требует включения feature gate `SCTPSupport`)
- **Mixed Protocols** (один LoadBalancer для TCP и UDP) доступны с Kubernetes 1.24+ через `ipFamilyPolicy` и аннотации облачного провайдера

**Ограничение для LoadBalancer:** По умолчанию облачные балансировщики создают отдельный IP для каждого протокола. Для совмещения TCP и UDP на одном IP требуется поддержка провайдера или использование MetalLB/Cilium.

### Политики трафика (Traffic Policies)

Позволяют оптимизировать маршрутизацию и сохранять IP клиента:

- **`internalTrafficPolicy: Local`** — трафик от пода будет направлен на эндпоинты, расположенные на том же узле. Если локальных подов нет, соединение будет разорвано. Снижает задержки и нагрузку на сеть кластера.
- **`externalTrafficPolicy: Local`** — для типов `NodePort` и `LoadBalancer`. Исключает лишний переход (hop) между узлами и сохраняет исходный IP-адрес клиента (`Source IP`), направляя трафик только на локальные поды узла.

**Важно:** При использовании `externalTrafficPolicy: Local` возможен неравномерный распределение трафика между подами, так как балансировка происходит только в пределах узла. Рекомендуется использовать равномерное распределение подов по узлам для минимизации дисбаланса.

### Привязка сессий (Session Affinity)

Механизм `sessionAffinity` обеспечивает направление запросов от одного клиента на один и тот же под в течение заданного времени. Это критично для приложений с сохранением состояния (stateful), например WebSocket-сессий или кэширования сессий на уровне пода.

**Конфигурация:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: sticky-service
spec:
  selector:
    app: web
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800  # 3 часа (по умолчанию)
  ports:
    - port: 80
      targetPort: 8080
```

**Техническая реализация:** Механизм базируется на таблице соединений **conntrack** в ядре Linux. При первом запросе от клиента kube-proxy выбирает под и создаёт запись в conntrack. Последующие запросы с того же IP направляются на тот же под, пока запись не истечёт.

**Ограничения:**
- При переполнении или сбросе таблицы conntrack (например, при перезагрузке узла) привязка теряется
- Не учитывает изменения в количестве подов — при масштабировании распределение может стать неравномерным
- Не работает с Headless Service (нет проксирования трафика)

### Поддержка Dual-Stack (IPv4/IPv6)

Kubernetes поддерживает одновременную работу по обоим протоколам. Service может иметь несколько `clusterIPs` (один IPv4 и один IPv6) при настройке `ipFamilyPolicy: PreferDualStack`. Это критично для современных мобильных сетей и IoT-устройств.

**Значения ipFamilyPolicy:**

| Значение | Описание |
| :--- | :--- |
| `SingleStack` | Только один стек IP (IPv4 или IPv6). Значение по умолчанию для кластеров без включённого Dual-Stack. |
| `PreferDualStack` | Предпочтительно использовать оба стека. Если кластер поддерживает Dual-Stack, сервис получит оба IP. Если нет — будет использоваться доступный стек. |
| `RequireDualStack` | Обязательно использовать оба стека. Если кластер не поддерживает Dual-Stack, сервис не будет создан (ошибка валидации). |

**Пример конфигурации Dual-Stack Service:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: dualstack-service
spec:
  type: ClusterIP
  ipFamilyPolicy: PreferDualStack
  ipFamilies:
    - IPv4
    - IPv6
  selector:
    app: web
  ports:
    - port: 80
      targetPort: 8080
```

**Проверка:**
```bash
kubectl get svc dualstack-service
# NAME                TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)   AGE
# dualstack-service   ClusterIP   10.96.0.100,fd00::100   <none>   80/TCP    5s
```

### Публикация не готовых подов (publishNotReadyAddresses)

По умолчанию Kubernetes включает под в эндпоинты сервиса только после успешного прохождения **Readiness Probe**. Однако для распределённых систем с кворумной архитектурой (Elasticsearch, ZooKeeper, Cassandra) это создаёт проблему «курицы и яйца»: узлы не могут запуститься, пока не обнаружат друг друга, но они не обнаруживаются, пока не запустились.

Параметр `spec.publishNotReadyAddresses: true` заставляет сервис включать IP подов в DNS и эндпоинты сразу после их создания, игнорируя статус готовности.

**Пример для кворумного приложения:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: elasticsearch-cluster
spec:
  clusterIP: None
  publishNotReadyAddresses: true  # Критично для bootstrap кворума
  selector:
    app: elasticsearch
  ports:
    - port: 9300
      name: transport
```

**Важно:** Используйте `publishNotReadyAddresses: true` только когда это действительно необходимо. Включение не готовых подов в эндпоинты может привести к ошибкам запросов, если приложение ещё не может обрабатывать трафик.

### Важность targetPort: Маршрутизация в многоконтейнерных подах

В подах с несколькими контейнерами (например, использующих [Sidecar-паттерн](../../Base/Pod/pod_sidecar_patterns.md)) критически важно точно указывать `targetPort`.

**Сценарий:** Под содержит два контейнера:
1.  **Main Application:** Слушает порт `8080`.
2.  **Nginx Sidecar:** Слушает порт `80` (выполняет роль прокси, раздает статику, терминирует TLS).

Если в Service указать `targetPort: 8080`, трафик пойдет напрямую к приложению, полностью игнорируя Nginx Sidecar. Это приведет к неработоспособности логики кэширования или авторизации, заложенной в sidecar. Для правильной работы необходимо указывать `targetPort: 80`, направляя трафик на прокси-контейнер.

## Практические сценарии

### Подготовка: Создание тестового Deployment

Для демонстрации работы Service создадим тестовое приложение:

```yaml
# nginx-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-demo
  namespace: default
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx-demo
  template:
    metadata:
      labels:
        app: nginx-demo
    spec:
      containers:
        - name: nginx
          image: nginx:1.25
          ports:
            - name: http
              containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 5
            periodSeconds: 10
```

**Применение:**
```bash
kubectl apply -f nginx-deploy.yaml

# Проверка готовности подов
kubectl get pods -l app=nginx-demo
# NAME                         READY   STATUS    RESTARTS   AGE
# nginx-demo-abc123-def456     1/1     Running   0          30s
<longcat_arg_value>


### Взаимодействие внутри кластера по DNS

Любой под внутри кластера может обратиться к сервису по его DNS-имени.
- **Полное имя (FQDN):** `<service-name>.<namespace>.svc.cluster.local`
- **Краткое имя:** `<service-name>.<namespace>` (автоматическое добавление суффикса)
- **В том же namespace:** `<service-name>` (достаточно только имени сервиса)

**Пример обращения:**
```bash
# Из пода в том же namespace
curl http://my-api:80

# Из пода в другом namespace
curl http://my-api.prod.svc.cluster.local:80
```

**Проверка DNS-резолвинга:**
```bash
# Создание тестового пода с утилитами DNS
kubectl run dns-test --rm -it --image=busybox:1.37 -- sh

# Внутри пода:
nslookup my-api.prod.svc.cluster.local
# Server:    10.96.0.10
# Address:   10.96.0.10#53
#
# Name:      my-api.prod.svc.cluster.local
# Address:   10.96.100.50

# Проверка SRV-записей (для именованных портов)
nslookup -type=SRV _http._tcp.my-api.prod.svc.cluster.local
```

Подробное описание работы DNS и CoreDNS см. в разделе [DNS в Kubernetes](../dns_deep_dive.md).

### Сценарий 1: Внутренний доступ (ClusterIP)

Создание стабильной точки входа для межсервисного взаимодействия:

```yaml
# clusterip-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-api
  labels:
    app.kubernetes.io/name: internal-api
spec:
  type: ClusterIP
  selector:
    app: nginx-demo
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: 80
```

**Применение и проверка:**
```bash
kubectl apply -f clusterip-service.yaml

# Получение информации о сервисе
kubectl get svc internal-api
# NAME           TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
# internal-api   ClusterIP   10.96.100.50    <none>        80/TCP    5s

# Проверка эндпоинтов
kubectl get endpointslices -l kubernetes.io/service-name=internal-api
# NAME                        ADDRESSTYPE   PORTS   ENDPOINTS                   AGE
# internal-api-abc123         IPv4          80      10.244.1.5,10.244.2.6,...   10s

# Тестовый запрос из другого пода
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -s http://internal-api
# → <!DOCTYPE html><html><head><title>Welcome to nginx!</title>...
```

### Сценарий 2: Сохранение IP клиента (externalTrafficPolicy: Local)

Используется, когда приложению необходимо видеть реальный IP-адрес источника:

```yaml
# nodeport-local.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-web
spec:
  type: NodePort
  externalTrafficPolicy: Local  # Сохраняет Source IP
  selector:
    app: nginx-demo
  ports:
    - name: http
      port: 80
      targetPort: 80
      nodePort: 32080  # Опционально: явное указание порта (30000-32767)
```

**Особенности:**
- Трафик принимается только теми узлами, на которых запущены целевые поды
- Если на узле нет подов, соединение будет сброшено (Connection Refused)
- Возможна неравномерная балансировка при неравномерном распределении подов по узлам

**Проверка:**
```bash
# Получение IP узлов
kubectl get nodes -o wide

# Запрос с сохранением IP клиента
curl http://<node-ip>:32080
```

### Сценарий 3: Прямое обнаружение подов (Headless Service)

Используется для кластерных решений (Elasticsearch, Kafka), где клиенту нужен список IP всех реплик:

```yaml
# headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: db-cluster
spec:
  clusterIP: None  # Делает сервис Headless
  selector:
    app: nginx-demo
  ports:
    - name: http
      port: 80
```

**Проверка DNS:**
```bash
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup db-cluster
# Server:    10.96.0.10
# Address:   10.96.0.10#53
#
# Name:      db-cluster.default.svc.cluster.local
# Address:   10.244.1.5
# Address:   10.244.2.6
# Address:   10.244.3.7
# → Возвращает список IP всех подов вместо одного VIP
```

Подробнее о Headless Service: [Тип Service — Headless](./service_type_headless.md).

### Сценарий 4: Абстракция внешних ресурсов (ExternalName)

Создание DNS-алиаса для внешней базы данных или API:

```yaml
# external-name.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-postgres
spec:
  type: ExternalName
  externalName: db.prod.example.com
```

**Проверка:**
```bash
# Из пода внутри кластера
kubectl run test --rm -it --image=busybox:1.37 -- nslookup external-postgres
# → external-postgres.default.svc.cluster.local canonical name = db.prod.example.com
```

**Когда использовать:**
- Интеграция с внешними сервисами без изменения кода приложения
- Миграция внешних зависимостей в кластер (постепенный переход)
- Абстракция от реального расположения внешнего ресурса

### Сценарий 5: Оптимизация трафика по зонам (trafficDistribution)

**Доступно с Kubernetes 1.31:** Использование поля `spec.trafficDistribution` для удержания трафика в той же зоне доступности:

```yaml
# topology-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: local-zone-api
spec:
  selector:
    app: nginx-demo
  trafficDistribution: PreferClose  # Предпочитать эндпоинты в той же зоне/узле
  ports:
    - name: http
      port: 80
      targetPort: 80
```

**Требования:**
- Минимум 3 подов на зону для стабильной работы
- Равномерное распределение подов по зонам (используйте Topology Spread Constraints)

### Доступ снаружи для отладки

Для временного доступа к внутреннему сервису (тип `ClusterIP`) без настройки Ingress используется `kubectl port-forward`:

```bash
# Проброс порта 8080 локальной машины на порт 80 сервиса
kubectl port-forward svc/my-nginx 8080:80
# Forwarding from 127.0.0.1:8080 -> 80
# Forwarding from [::1]:8080 -> 80
```

Приложение станет доступно по адресу `http://localhost:8080`.

**Важно:** `port-forward` предназначен только для разработки и отладки. Для production-доступа используйте Ingress, Gateway API или LoadBalancer.

### Публикация приложения и балансировка

Service автоматически выполняет балансировку нагрузки между подами (по умолчанию алгоритм round-robin на уровне `kube-proxy`). При масштабировании количества реплик (увеличении `replicas` в Deployment) новые поды автоматически добавляются в балансировку после успешного прохождения проверки готовности.

**Демонстрация автоматического обновления эндпоинтов:**
```bash
# Масштабирование Deployment
kubectl scale deployment nginx-demo --replicas=5

# Наблюдение за обновлением эндпоинтов
kubectl get endpointslices -l kubernetes.io/service-name=internal-api -w
# NAME                        ADDRESSTYPE   PORTS   ENDPOINTS                   AGE
# internal-api-abc123         IPv4          80      10.244.1.5,10.244.2.6,...   5m
# → Через несколько секунд добавятся новые IP после прохождения readinessProbe
```

## Дополнительная информация

### Endpoints и EndpointSlices

Для каждого Service с селектором Kubernetes поддерживает объекты, содержащие актуальные сетевые адреса:
- **Endpoints:** Классический объект со списком IP. Имеет ограничения по производительности в крупных кластерах (>1000 подов), так как любой апдейт одного пода заставляет API-сервер пересылать весь список.
- **EndpointSlices:** Современная масштабируемая альтернатива. Группирует эндпоинты в несколько объектов (по умолчанию до 100 эндпоинтов на один Slice), что значительно снижает объем трафика управления между API-сервером и `kube-proxy`.

**Проверка EndpointSlices:**
```bash
# Список всех EndpointSlices для сервиса
kubectl get endpointslice -l kubernetes.io/service-name=<service-name>

# Детальная информация
kubectl describe endpointslice <endpointslice-name>
```

### Реализация через kube-proxy

Механизм Service реализуется компонентом `kube-proxy`, который работает на каждом узле кластера. Основные задачи `kube-proxy` — перехват трафика к ClusterIP и его пересылка соответствующим подам на основе правил фильтрации.

#### Режимы работы (Backend)
1.  **nftables (Stable v1.31):** Основной и наиболее производительный режим в современных кластерах (2025-2026). Обеспечивает лучшую масштабируемость и более простую отладку сетевых правил по сравнению с iptables.
2.  **iptables (Legacy):** По-прежнему доступен для совместимости, но постепенно вытесняется nftables.
3.  **IPVS:** Предназначен для кластеров с десятками тысяч сервисов. Поддерживает расширенные алгоритмы балансировки (lc, dh, sh).

**Проверка текущего режима:**
```bash
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "nftables" (или "ipvs", "iptables")
```

#### Алгоритмы балансировки нагрузки
Для распределения трафика `kube-proxy` использует следующие стратегии:

- **Циклический (Round Robin):** Последовательный обход списка доступных эндпоинтов.
- **Случайный выбор (Random):** Стандарт для `iptables` и `nftables` режимов (используется модуль `statistic` в ядре).
- **Привязка сеанса (Session Affinity):** Настраивается через `sessionAffinity: ClientIP`. Гарантирует, что запросы с одного и того же IP-адреса клиента будут направляться на один и тот же под в течение `timeoutSeconds`.

### Аллокация ClusterIP (IPAM)

ClusterIP назначается из диапазона `service-cluster-ip-range` (параметр API-сервера). 
- **Статическая аллокация:** Можно вручную указать конкретный IP из диапазона в поле `spec.clusterIP`.
- **Multiple Service CIDRs (v1.31+):** Позволяет динамически добавлять новые диапазоны IP для сервисов (через объект `ServiceCIDR`), если основной диапазон исчерпан.

**Проверка диапазона ClusterIP:**
```bash
# Получение диапазона из параметров API-сервера
kubectl cluster-info dump | grep -E "service-cluster-ip-range"
# → --service-cluster-ip-range=10.96.0.0/12

# Или через объект ServiceCIDR (v1.31+)
kubectl get servicecidr
# NAME             CIDRS           AGE
# kubernetes       10.96.0.0/12    100d
```

### Жизненный цикл и Graceful Termination

Когда под удаляется (например, при `kubectl delete pod` или масштабировании):
1.  API-сервер помечает под как `Terminating`.
2.  **EndpointSlice Controller** немедленно удаляет IP пода из списка эндпоинтов сервиса.
3.  `kube-proxy` на всех узлах обновляет правила, прекращая посылать *новый* трафик на этот под.
4.  **Важно:** Существующие соединения остаются активными до завершения процесса или истечения `terminationGracePeriodSeconds`. Для предотвращения 502 ошибок рекомендуется использовать `PreStop` хуки в контейнере.

**Рекомендуемая конфигурация для плавного завершения:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: graceful-app
spec:
  terminationGracePeriodSeconds: 60
  containers:
    - name: app
      image: my-app:latest
      lifecycle:
        preStop:
          exec:
            command: ["/bin/sh", "-c", "sleep 10"]  # Ожидание обновления эндпоинтов
```

### Поведение Service при обновлении приложений

Service является **стабильной абстракцией** — сам объект Service не изменяется при деплое. Изменяются только поды (через Deployment/Rollout) и их эндпоинты. Это ключевое понимание для production.

#### Rolling Update

При стандартном `RollingUpdate` Deployment Service автоматически переключает трафик:

1.  Deployment создает новые поды с обновленным образом.
2.  Новые поды проходят `readinessProbe`.
3.  После успешного прохождения проверки готовности под добавляется в `EndpointSlice` сервиса.
4.  `kube-proxy` обновляет правила — трафик начинает распределяться между старыми и новыми подами.
5.  Старые поды удаляются по мере готовности новых.

**Критический момент:** между добавлением нового пода в эндпоинты и удалением старого Service балансирует трафик на обе версии. Если приложение не backward-compatible, клиенты могут получить ошибки.

**Рекомендации:**
- Используйте `maxSurge: 1` и `maxUnavailable: 0` для нулевого даунтайма
- Настраивайте `readinessProbe` с足够 строгими проверками
- Используйте `PreStop` хук для завершения активных соединений

#### Blue-Green деплой

При blue-green стратегии Service переключается между двумя наборами подов через изменение `selector`:

```yaml
# Шаг 1: Основной сервис指向 синюю версию
apiVersion: v1
kind: Service
metadata:
  name: my-app
spec:
  selector:
    app: my-app
    version: blue   # ← переключение на green
  ports:
    - port: 80
      targetPort: 8080
```

**Важно:** при переключении `selector` Service происходит немедленное обновление правил kube-proxy. Существующие соединения (старые поды) продолжают работать до своего завершения, но новые соединения идут уже на новую версию. Для полного переключения без混合 traffic используйте Gateway API или Service Mesh с weighted routing.

Подробнее о blue-green и canary стратегиях: [Прогрессивная доставка в GitOps](../../../GitOps/Concepts/progressive_delivery_gitops.md), [Canary Deployment](../../../CI-CD/Deployment_Strategies/canary_deployment.md).

#### Canary деплой

При canary-стратегии создается отдельный Service для canary-подов, а маршрутизация трафика выполняется на уровне L7 (Gateway API, Istio, Flagger):

```yaml
# Основной Service (100% трафика → primary)
apiVersion: v1
kind: Service
metadata:
  name: my-app
spec:
  selector:
    app: my-app
    track: stable
  ports:
    - port: 80
      targetPort: 8080
---
# Canary Service (часть трафика → canary)
apiVersion: v1
kind: Service
metadata:
  name: my-app-canary
spec:
  selector:
    app: my-app
    track: canary
  ports:
    - port: 80
      targetPort: 8080
```

Распределение весов между Service выполняется через HTTPRoute (Gateway API) или VirtualService (Istio), а не через сам Service. Подробнее: [Flagger](../../../GitOps/Concepts/progressive_delivery_gitops.md#flagger-автономный-canary-для-deployment).

#### Взаимодействие с PodDisruptionBudget (PDB)

PDB защищает Service от потери доступности при обслуживании узлов. PDB ограничивает количество одновременно недоступных подов, guarantee что Service сохранит эндпоинты.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2   # Как минимум 2 пода должны быть доступны
  selector:
    matchLabels:
      app: my-app
```

**Важно:** PDB защищает только добровольные прерывания (`kubectl drain`, evictions). При падении узла или taint `out-of-service` PDB не действует. Подробнее: [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).

#### Взаимодействие с HorizontalPodAutoscaler (HPA)

HPA масштабирует количество подов на основе метрик, что напрямую влияет на эндпоинты Service:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

При масштабировании HPA новые поды проходят `readinessProbe` и добавляются в эндпоинты Service. При уменьшении — поды удаляются из эндпоинтов после `preStop` и `terminationGracePeriodSeconds`. Подробнее: [HPA](../../Autoscaling/HPA/index.md).

### Устранение неполадок (Troubleshooting)

#### Диагностика отсутствия эндпоинтов

**Симптом:** Service не перенаправляет трафик, `kubectl describe svc` показывает `Endpoints: <none>`.

**Диагностика:**
```bash
# 1. Проверка селектора сервиса
kubectl get svc <service-name> -o yaml | grep -A5 selector

# 2. Проверка меток подов
kubectl get pods --show-labels -l <selector>

# 3. Проверка готовности подов
kubectl get pods -l <selector>
# READY должен быть 1/1 (или N/N)

# 4. Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=<service-name>
```

**Типичные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Несоответствие меток | `kubectl get pods --show-labels` | Исправить labels подов или selector сервиса |
| Поды не готовы | `kubectl get pods` (READY 0/1) | Проверить readinessProbe, логи пода |
| Разные namespace | `kubectl get pods -A -l <selector>` | Убедиться, что поды и сервис в одном namespace |
| Нет подов с таким селектором | `kubectl get pods -l <selector>` | Создать поды или исправить селектор |

#### Диагностика сетевых проблем

```bash
# Проверка правил kube-proxy (nftables)
sudo nft list ruleset | grep -E "KUBE-SERVICES|KUBE-SVC" | grep <cluster-ip>

# Проверка DNS из пода
kubectl run dns-debug --rm -it --image=busybox:1.37 -- nslookup <service-name>.<namespace>.svc.cluster.local

# Проверка связности с эндпоинтом
kubectl run curl-debug --rm -it --image=curlimages/curl -- curl -v http://<pod-ip>:<port>

# Проверка conntrack (на узле)
sudo conntrack -L -p tcp --dport <port>
```

#### Зависшие поды в Terminating

**Симптом:** Под находится в статусе `Terminating` длительное время, блокирует обновление эндпоинтов.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A10 Events

# Проверка финализаторов
kubectl get pod <pod-name> -o jsonpath='{.metadata.finalizers}'
```

**Решение:**
```bash
# Принудительное удаление (только в крайнем случае)
kubectl delete pod <pod-name> --grace-period=0 --force
```

**Внимание:** Принудительное удаление может привести к orphaned-состоянию в приложении. Применяйте только после исчерпания остальных вариантов.

### Лучшие практики (Best Practices)

1. **Используйте именованные порты** — упрощает обновление портов приложения без изменения Service:
   ```yaml
   ports:
     - name: http
       port: 80
       targetPort: http-web  # Имя порта, а не номер
   ```

2. **Всегда настраивайте readinessProbe** — предотвращает отправку трафика на не готовые поды:
   ```yaml
   readinessProbe:
     httpGet:
       path: /health
       port: http
     initialDelaySeconds: 5
     periodSeconds: 10
   ```

3. **Используйте стандартные метки** — обеспечивает совместимость с инструментами:
   ```yaml
   labels:
     app.kubernetes.io/name: my-app
     app.kubernetes.io/component: frontend
     app.kubernetes.io/version: "1.2.3"
   ```

4. **Минимизируйте использование externalTrafficPolicy: Local** — только когда действительно необходимо сохранить Source IP, иначе возможна неравномерная балансировка.

5. **Используйте trafficDistribution: PreferClose** (v1.31+) для мультизональных кластеров — снижает межзональный трафик и задержки.

6. **Ограничивайте доступ через NetworkPolicy** — даже для внутренних сервисов:
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-frontend-only
   spec:
     podSelector:
       matchLabels:
         app: backend
     ingress:
       - from:
           - podSelector:
               matchLabels:
                 app: frontend
   ```

### Ограничения и граничные случаи (Edge Cases)

#### Ограничение на количество сервисов
- **iptables режим:** Производительность деградирует при >1000 сервисах (O(N) поиск правила)
- **nftables режим:** O(N) с низким коэффициентом, рекомендуется до ~5000 сервисов
- **IPVS режим:** O(1), рекомендуется для >5000 сервисов

#### Ограничение размера DNS-ответа (Headless Service)
- При >500 подов DNS-ответ может превысить 512 байт (UDP limit)
- CoreDNS устанавливает флаг `TC` (Truncated), клиент должен использовать TCP
- Решение: Использовать EndpointSlices (автоматически) или уменьшить количество подов

#### Проблема gRPC и HTTP/2
- kube-proxy балансирует на уровне TCP, не видит HTTP/2 мультиплексирование
- Все gRPC-запросы по одному TCP-соединению идут на один под
- Решение: Использовать Headless Service с клиентской балансировкой или Service Mesh (Istio, Linkerd)

#### Конфликт портов в NodePort
- Диапазон NodePort: 30000-32767 (по умолчанию)
- Порт открыт на всех интерфейсах всех узлов
- Требует настройки firewall для безопасности
- Изменить диапазон: `--service-node-port-range=3000-32767` в параметрах API-сервера

#### Hairpin NAT (Loopback)
- Под может обращаться к самому себе через ClusterIP своего сервиса
- Без Hairpin NAT такой запрос был бы отброшен
- Включается автоматически в kube-proxy (`--masquerade-all` или `--hairpin-mode=hairpin-veth`)

### Современные возможности (2025-2026)

- **Gateway API:** Рекомендуемый стандарт для управления входящим (Ingress) и внутренним (Service Mesh) трафиком на уровнях L4-L7.
- **Topology Aware Routing:** Эволюционировал в `trafficDistribution`, позволяя более гибко управлять локальностью трафика в пределах зоны или региона.
- **nftables как стандарт:** С v1.31 nftables является рекомендуемым бэкендом kube-proxy.
- **Multiple Service CIDRs:** Динамическое добавление диапазонов IP без перезагрузки кластера.

**См. также:**
- [Сводка по типам сервисов](./service_types_summary.md)
- [Практические сценарии публикации](./service_practical_scenarios.md)
- [Отказоустойчивость Service](./service_failure_modes.md) — failure modes и каскадные сбои
- [NetworkPolicy + Service](./service_network_policy_integration.md) — паттерны сетевой изоляции
- [Продвинутая диагностика Service](./service_advanced_troubleshooting.md) — tcpdump, netshoot, conntrack
- [DNS в Kubernetes](../dns_deep_dive.md)
- [Gateway API](../gateway_api/definitions.md) — современное управление трафиком
- [CNI и kube-proxy: роли и взаимодействие](../Network/cni_kube_proxy_roles.md) — детали реализации сетевых компонентов
- [ExternalIPs](./service_externalips.md) — (Deprecated v1.36)
- [Прогрессивная доставка](../../../GitOps/Concepts/progressive_delivery_gitops.md) — blue-green, canary, A/B
- [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md) — защита доступности при обслуживании
- [HPA](../../Autoscaling/HPA/index.md) — горизонтальное масштабирование

