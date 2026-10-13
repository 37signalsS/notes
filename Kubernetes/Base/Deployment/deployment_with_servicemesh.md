# Deployment с Service Mesh

**Актуально для:** Kubernetes 1.30+ / Istio 1.22+ / Gateway API v1.1+

Интеграция Kubernetes Deployment с Service Mesh: архитектура внедрения sidecar-прокси, жизненный цикл подов, маршрутизация canary-релизов через Gateway API и VirtualService, защита от каскадных сбоев (circuit breaking), перехват проб kubelet, масштабирование через HPA и оптимизация потребления ресурсов.

## Предварительные требования (Prerequisites)

- Развернутый кластер Kubernetes версии 1.30 или выше на выделенной или bare-metal инфраструктуре.
- Установленный и настроенный Service Mesh (Istio 1.22+ или Linkerd 2.20+) с поддержкой Gateway API (GAMMA).
- Утилиты командной строки `kubectl` и `istioctl` (или `linkerd`), настроенные для работы с кластером.
- Установленный Metrics Server для корректного сбора метрик и работы Horizontal Pod Autoscaler.
- Базовые знания архитектуры [Deployment в Kubernetes](./index.md), [манифестов Deployment](./deployment_manifest.md) и [управления жизненным циклом подов](./lifecycle_management.md).

## 1. Определения

**Service Mesh (сервисная сеть)** — выделенный инфраструктурный слой для управления межсервисным сетевым взаимодействием (East-West) на транспортном и прикладном уровнях (L4/L7), обеспечивающий сквозное шифрование (mTLS), динамическую маршрутизацию, наблюдаемость и политики устойчивости без изменений в коде приложения.

**Sidecar-прокси (Data Plane)** — выделенный прокси-контейнер (Envoy в Istio, linkerd2-proxy в Linkerd), запускаемый внутри того же Pod рядом с контейнером приложения. Sidecar разделяет с приложением сетевой неймспейс (`localhost`, IPC, network interfaces) и перехватывает сетевой трафик через правила `iptables` или расширения eBPF.

**Native Sidecar Containers (K8s 1.29+, GA в 1.33)** — механизм Kubernetes (KEP-3839), позволяющий запускать вспомогательные контейнеры в блоке `initContainers` с директивой `restartPolicy: Always`. Обеспечивает гарантированный запуск и готовность прокси строго до старта основных контейнеров приложения и завершение прокси только после остановки всех контейнеров рабочей нагрузки.

**Discovery Scope (область видимости xDS)** — объем каталога сервисов, кластеров и маршрутов, передаваемый контрольной плоскостью (istiod) в память локального Envoy. Без явного ограничения каждый прокси хранит данные о всех сервисах кластера, что приводит к линейному росту потребления оперативной памяти.

**Gateway API (v1.1+)** — стандартизированный набор ресурсов Kubernetes (`Gateway`, `HTTPRoute`, `GRPCRoute`), заменяющий проприетарные CRD для маршрутизации входящего (North-South) и мессервисного (East-West через инициативу GAMMA) трафика.

> Общая архитектура Service Mesh, сравнение Istio и Linkerd, управление трафиком и mTLS детально описаны в [Service Mesh концепции](../../../Service_Mesh/service_mesh_concepts.md), [Traffic Management](../../../Service_Mesh/traffic_management.md), [Istio Architecture](../../../Service_Mesh/istio_architecture.md) и [Istio Security](../../../Service_Mesh/istio-security-policies.md).

## 2. Базовые концепции и архитектура

### Архитектурные изменения Deployment при внедрении Service Mesh

Внедрение Service Mesh переносит сетевую логику из приложения и базового kube-proxy на уровень локального прокси Envoy:

| Аспект | Deployment без Service Mesh | Deployment с Service Mesh |
|:-------|:----------------------------|:--------------------------|
| **Маршрутизация** | Kube-proxy (L4, round-robin через iptables/IPVS), сервис ClusterIP | Envoy sidecar (L7, с учетом весов, заголовков, latency, cookie) |
| **Canary Rollout** | Несколько Deployment с ручным подбором количества реплик | Единый сервис / независимые Deployment с точным разделением весов в Gateway API / VirtualService |
| **Circuit Breaking** | Библиотеки в коде приложения (Resilience4j, Polly) | Декларативные политики прокси (DestinationRule / BackendTrafficPolicy) |
| **Безопасность (mTLS)** | Настройка сертификатов внутри каждого приложения | Автоматический mutual TLS через SPIFFE ID между прокси-контейнерами |
| **Health Checks** | Прямой опрос контейнера kubelet через HTTP/TCP | Проксирование через Envoy или автоматический rewrite портов для обхода mTLS |
| **Автомасштабирование (HPA)**| Суммарные метрики Pod по CPU и Memory | Риск искажения метрик из-за оверхеда Envoy; требуется фильтрация через `ContainerResource` |
| **Отказоустойчивость** | Базовые ретраи на уровне клиентского HTTP-клиента | Централизованные политики таймаутов, ретраев и Outlier Detection на L7 |

### Механизм инъекции Sidecar

Инъекция прокси в поды Deployment реализуется через вебхук мутации (Mutating Admission Webhook):

1. **Автоматическая инъекция на уровне namespace:** метка неймспейса `istio-injection=enabled` (или `istio.io/rev=<revision>` при канареечном обновлении контрольной плоскости). Контроллер автоматически добавляет init-контейнер настройки сети и sidecar-контейнер `istio-proxy` во все создаваемые поды.
2. **Явная инъекция на уровне шаблона Deployment:** аннотация `sidecar.istio.io/inject: "true"` в блоке `spec.template.metadata.annotations`. Позволяет точечно подключать к мешу конкретные рабочие нагрузки в смешанных неймспейсах.

```
                      +------------------------------------------------+
                      |                   Pod Sandbox                  |
                      |                                                |
                      |  +------------------+    +------------------+  |
                      |  |   istio-proxy    |    |  app container   |  |
Входящий L7 трафик   |  |   (Envoy L7)     |    |                  |  |
--------------------->|  |                  |    |                  |  |
(перехват iptables)   |  |   Порт: 15006    |--->|  Порт: 8080      |  |
                      |  |                  |    |                  |  |
                      |  +------------------+    +------------------+  |
                      |            |                       |           |
                      |            +---------- 127.0.0.1 --+           |
                      +------------------------------------------------+
```

### Жизненный цикл Pod и порядок запуска (Startup Race Condition)

Классическая проблема интеграции со Service Mesh — гонка при старте: контейнер приложения переходит в статус `Running` и пытается выполнить исходящий сетевой запрос (подключение к базе данных PostgreSQL, вычитка секретов из HashiCorp Vault, опрос DNS), когда локальный Envoy еще не загрузил xDS-конфигурацию от istiod. В результате приложение падает с ошибками `Connection refused` или сетевыми таймаутами.

Существует два метода устранения race condition:

1. **Native Sidecar Containers (рекомендуемый современный стандарт):**
   Начиная с Kubernetes 1.29+ (включено по умолчанию в современных релизах Istio), прокси инжектируется в блок `initContainers` с флагом `restartPolicy: Always`. Kubelet ожидает успешного выполнения `startupProbe` у прокси и перехода его в статус `Ready`, и только после этого приступает к запуску основных контейнеров приложения.
2. **Параметр `holdApplicationUntilProxyStarts` (классическая модель):**
   Для кластеров без поддержки нативных сайдкаров используется флаг `holdApplicationUntilProxyStarts: true` (настраивается в `MeshConfig` или через аннотацию `proxy.istio.io/config`). Агент `pilot-agent` блокирует запуск процессов до готовности слушателей Envoy.

### Корректное завершение работы (Graceful Shutdown)

При удалении пода Deployment (`kubectl scale down`, rolling update или eviction узла) возникает обратная гонка: контейнер `istio-proxy` может завершиться раньше приложения, разорвав активные соединения.

Последовательность шагов при остановке пода:

1. **Удаление эндпоинта:** Kube-controller-manager исключает под из `EndpointSlice`. Это занимает от 1 до 3 секунд из-за задержек распространения по кластеру.
2. **Фаза preStop:** Контейнер приложения выполняет `preStop`-хук (`sleep 5..10`), продолжая обслуживать оставшиеся запросы.
3. **Draining Envoy:** Получив сигнал `SIGTERM`, Envoy перестает принимать новые соединения и переводит существующие слушатели в режим сброса (drain). Длительность регулируется параметром `terminationDrainDuration`.
4. **Синхронизация таймаутов:** Значение `terminationGracePeriodSeconds` в спецификации Deployment должно с запасом покрывать время `preStop` приложения, обработку in-flight запросов и дренаж Envoy:
   
$$\text{terminationGracePeriodSeconds} \ge \text{preStop sleep} + \text{terminationDrainDuration} + \text{app processing timeout}$$

### Взаимодействие с Kubelet Health Probes

Kubelet отправляет HTTP-запросы `livenessProbe`, `readinessProbe` и `startupProbe` с IP-адреса рабочего узла непосредственно на сетевой интерфейс пода. При включенном строгом mTLS (`STRICT`) Envoy блокирует входящие запросы от kubelet, так как у kubelet нет клиентского mTLS-сертификата Istio.

Для решения проблемы Istio использует **Probe Rewriting**:
- При инъекции sidecar аннотация `sidecar.istio.io/rewriteAppHTTPProbers: "true"` указывает мутационному вебхуку перенастроить проверки пода на встроенный порт агента `15021` (эндпоинт `/app-health/<container-name>/<probe-type>`).
- Kubelet опрашивает агент по незашифрованному протоколу, а агент локально пересылает проверку в контейнер приложения по loopback (`127.0.0.1`), минуя mTLS-фильтры Envoy.

### Gateway API vs Istio VirtualService (2026)

| Аспект | Gateway API (стандарт K8s) | Istio VirtualService (legacy CRD) |
|:-------|:---------------------------|:-----------------------------------|
| **Спецификация** | `gateway.networking.k8s.io/v1` (GA) | `networking.istio.io/v1beta1` |
| **Портативность** | Единый API для Envoy Gateway, Cilium, Istio, NGINX | Привязка исключительно к контроллеру Istio |
| **Мессервисный трафик** | Поддерживается через GAMMA (`parentRefs` указывает на `Service`) | Указывается через блок `hosts` и `gateways: [mesh]` |
| **Canary веса** | Нативно через `backendRefs[].weight` на разные Service | Через `subsets` с жесткой привязкой к DestinationRule |
| **Ролевая модель** | Четкое разделение: Cluster Operator (GatewayClass), Infra/SRE (Gateway), Dev (HTTPRoute) | Все настройки объединены в одном ресурсе |

## 3. Практические сценарии и конфигурация

### Сценарий 1: Production-ready манифест Deployment со Sidecar

Данный манифест содержит комплексную конфигурацию Deployment для высоконагруженной среды: явный запрос ресурсов для Envoy, переопределение таймаутов завершения, rewrite проб и изоляцию портов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-api
  namespace: production
  labels:
    app: billing-api
    version: v1
spec:
  replicas: 4
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app: billing-api
  template:
    metadata:
      labels:
        app: billing-api
        version: v1
      annotations:
        # Принудительная инъекция sidecar
        sidecar.istio.io/inject: "true"
        # Выделение гарантированных ресурсов для Envoy прокси
        sidecar.istio.io/proxyCPU: "100m"
        sidecar.istio.io/proxyMemory: "128Mi"
        sidecar.istio.io/proxyCPULimit: "500m"
        sidecar.istio.io/proxyMemoryLimit: "512Mi"
        # Перезапись HTTP проб kubelet для работы через istio-agent (порт 15021)
        sidecar.istio.io/rewriteAppHTTPProbers: "true"
        # Тонкая настройка istio-proxy: задержка дренажа и логов
        proxy.istio.io/config: |
          terminationDrainDuration: 25s
          drainDuration: 15s
        # Исключение порта метрик приложения из mTLS перехвата (опционально)
        traffic.sidecar.istio.io/excludeInboundPorts: "9090"
    spec:
      serviceAccountName: billing-api-sa
      # Даем достаточно времени: preStop (10s) + drain (25s) + запас на flush = 45s
      terminationGracePeriodSeconds: 45
      containers:
      - name: application
        image: internal-registry.local/finance/billing-api:1.14.2
        imagePullPolicy: IfNotPresent
        lifecycle:
          preStop:
            exec:
              # Пауза перед SIGTERM для завершения распространения EndpointSlice
              command: ["/bin/sh", "-c", "sleep 10"]
        ports:
        - name: http-app
          containerPort: 8080
          protocol: TCP
        - name: metrics
          containerPort: 9090
          protocol: TCP
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 512Mi
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: 8080
          failureThreshold: 30
          periodSeconds: 2
        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: 8080
          initialDelaySeconds: 2
          periodSeconds: 5
          timeoutSeconds: 2
        livenessProbe:
          httpGet:
            path: /healthz/live
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 2
        securityContext:
          runAsNonRoot: true
          runAsUser: 10001
          readOnlyRootFilesystem: true
          allowPrivilegeEscalation: false
          capabilities:
            drop: ["ALL"]
```

### Сценарий 2: Canary Deployment через Gateway API (HTTPRoute)

Современная реализация канареечной доставки с использованием раздельных Deployment (`billing-stable` и `billing-canary`) и маршрутизации через Gateway API. Трафик делится в пропорции 90% на 10%.

```yaml
# 1. Kubernetes Services для стабильной и канареечной версии
apiVersion: v1
kind: Service
metadata:
  name: billing-stable
  namespace: production
  labels:
    app: billing-api
spec:
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    appProtocol: http
  selector:
    app: billing-api
    version: v1
---
apiVersion: v1
kind: Service
metadata:
  name: billing-canary
  namespace: production
  labels:
    app: billing-api
spec:
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    appProtocol: http
  selector:
    app: billing-api
    version: v2
---
# 2. HTTPRoute с весовой балансировкой трафика
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-traffic-split
  namespace: production
spec:
  parentRefs:
  - name: cluster-gateway
    namespace: istio-ingress
  hostnames:
  - "billing.internal.local"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: billing-stable
      port: 8080
      weight: 90
    - name: billing-canary
      port: 8080
      weight: 10
    timeouts:
      request: 10s
      backendRequest: 2s
---
# 3. Канареечный Deployment (версия v2)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-canary
  namespace: production
  labels:
    app: billing-api
    version: v2
spec:
  replicas: 1
  selector:
    matchLabels:
      app: billing-api
      version: v2
  template:
    metadata:
      labels:
        app: billing-api
        version: v2
      annotations:
        sidecar.istio.io/inject: "true"
        sidecar.istio.io/rewriteAppHTTPProbers: "true"
    spec:
      serviceAccountName: billing-api-sa
      containers:
      - name: application
        image: internal-registry.local/finance/billing-api:1.15.0-rc1
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 200m
            memory: 256Mi
          limits:
            cpu: "1"
            memory: 512Mi
```

### Сценарий 3: Маршрутизация Canary через Istio VirtualService и DestinationRule

Для существующих сред без полной миграции на Gateway API маршрутизация версий Deployment настраивается через подмножества (`subsets`):

```yaml
# DestinationRule: группировка подов по меткам версий и настройка пула соединений
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: billing-destination
  namespace: production
spec:
  host: billing-api.production.svc.cluster.local
  trafficPolicy:
    loadBalancer:
      simple: LEAST_REQUEST
    tls:
      mode: ISTIO_MUTUAL
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
---
# VirtualService: процентное распределение запросов между subsets
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: billing-routing
  namespace: production
spec:
  hosts:
  - billing-api.production.svc.cluster.local
  gateways:
  - mesh # Применение правила для внутреннего (East-West) взаимодействия
  http:
  - route:
    - destination:
        host: billing-api.production.svc.cluster.local
        subset: v1
      weight: 90
    - destination:
        host: billing-api.production.svc.cluster.local
        subset: v2
      weight: 10
    retries:
      attempts: 3
      perTryTimeout: 1s
      retryOn: "5xx,connect-failure,refused-stream"
```

### Сценарий 4: Защита Deployment через Circuit Breaking и Outlier Detection

Предотвращение каскадных сбоев: если одна из реплик Deployment начинает отдавать ошибки 5xx или зависать, прокси временно исключает ее из балансировки.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: billing-resilience
  namespace: production
spec:
  host: billing-api.production.svc.cluster.local
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 1024
      http:
        http1MaxPendingRequests: 100
        maxRequestsPerConnection: 10
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```

### Сценарий 5: Зеркалирование трафика (Shadow Deployment) через HTTPRoute

Безопасная проверка стабильности новой версии приложения под реальной нагрузкой без риска для пользователей. Зеркальные ответы отбрасываются Envoy и не возвращаются клиенту:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: billing-shadow-route
  namespace: production
spec:
  parentRefs:
  - name: cluster-gateway
    namespace: istio-ingress
  hostnames:
  - "billing.internal.local"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: billing-stable
      port: 8080
    filters:
    - type: RequestMirror
      requestMirror:
        backendRef:
          name: billing-canary
          port: 8080
```

### Сценарий 6: Ограничение xDS-скоупа через ресурс Sidecar

По умолчанию прокси каждого пода получает сведения обо всех сервисах во всем кластере. В кластере с 500+ сервисами каждый Envoy потребляет от 150 до 400 МБ оперативной памяти. Создание ресурса `Sidecar` в неймспейсе ограничивает видимость и снижает потребление RAM до 30–50 МБ на под.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: Sidecar
metadata:
  name: billing-scope-limiter
  namespace: production
spec:
  workloadSelector:
    labels:
      app: billing-api
  egress:
  # Прокси видит только сервисы текущего неймспейса, istio-system и базы данных
  - hosts:
    - "./*"
    - "istio-system/*"
    - "databases/postgres.databases.svc.cluster.local"
```

### Сценарий 7: Автомасштабирование (HPA) с изоляцией метрик через ContainerResource

Стандартный HPA по типу `Resource` суммирует использование процессора всех контейнеров в поде (`application` + `istio-proxy`). Если под обрабатывает интенсивный TLS-трафик, Envoy может потреблять 100–200m CPU, вызывая ложный скейлинг Deployment. Метрика `ContainerResource` в API `autoscaling/v2` изолирует метрики приложения.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: billing-api-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
  - type: ContainerResource
    containerResource:
      name: cpu
      container: application
      target:
        type: Utilization
        averageUtilization: 75
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 20
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
```

## 4. Диагностика и устранение неполадок

### Сводная таблица типовых сбоев

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
|:-----------------|:-------------|:-------------------|:------------------|
| **503 UC (Upstream Connection)** | Соединение сброшено бэкендом или приложение завершилось раньше Envoy | `kubectl logs <pod> -c istio-proxy \| grep 503` | Добавить `preStop` `sleep` в приложение; проверить таймауты `keepalive` |
| **503 UF (Upstream Failure)** | Ошибка подключения к бэкенду (connection refused / DNS error) | `istioctl proxy-config endpoints <pod>` | Проверить readinessProbe приложения; проверить соответствие портов в Service |
| **503 NR (No Route)** | Envoy не нашел маршрута для переданного заголовка Host или пути | `istioctl proxy-config routes <pod>` | Проверить совпадение `hostnames` и путей в `HTTPRoute` или `VirtualService` |
| **Connection refused при старте** | Приложение стартовало до готовности Envoy (race condition) | Логи контейнера приложения при запуске | Использовать Native Sidecars (`restartPolicy: Always`) или `holdApplicationUntilProxyStarts: true` |
| **Probe timeout / 404 / 503** | Kubelet probe блокируется mTLS или отправляется на неверный порт | `kubectl describe pod <pod> \| grep Unhealthy` | Добавить аннотацию `sidecar.istio.io/rewriteAppHTTPProbers: "true"` |
| **Envoy OOMKilled** | Раздувание xDS-таблиц из-за отсутствия лимитов видимости сервисов | `kubectl describe pod <pod> \| grep OOMKilled` | Применить ресурс `Sidecar` с ограничением `egress.hosts`; поднять `proxyMemoryLimit` |
| **HPA Flapping** | Скачки CPU Envoy из-за TLS искажают среднюю утилизацию пода | `kubectl describe hpa billing-api-hpa` | Переключить HPA с типа `Resource` на `ContainerResource` с указанием контейнера приложения |
| **Pod висит в Terminating** | Процесс игнорирует SIGTERM либо `terminationGracePeriod` исчерпан | `kubectl get pod <pod> -o yaml` | Проверить обработку сигналов процессом приложения (PID 1); скорректировать drain-таймауты |

### Операции и команды диагностики

Проверка согласованности и обнаружение конфликтующих конфигураций в неймспейсе:

```bash
istioctl analyze -n production
# → ✔ No validation issues found when analyzing namespace: production.
```

Проверка статуса синхронизации xDS-конфигурации пода с контрольной плоскостью istiod:

```bash
istioctl proxy-status billing-api-79b8c5647f-8x2d1.production
# → NAME                                                   CDS        LDS        EDS        RDS          ISTIOD                      VERSION
# → billing-api-79b8c5647f-8x2d1.production                 SYNCED     SYNCED     SYNCED     SYNCED       istiod-6c84c64b59-4v98z     1.22.1
```

Инспекция активных кластеров и актуальных эндпоинтов, известных прокси пода:

```bash
istioctl proxy-config endpoints billing-api-79b8c5647f-8x2d1.production --cluster "outbound|8080||billing-canary.production.svc.cluster.local"
# → ENDPOINT             STATUS  OUTLIER CHECK  CLUSTER
# → 10.244.2.45:8080     HEALTHY OK             outbound|8080||billing-canary.production.svc.cluster.local
```

Просмотр сформированных маршрутов Envoy:

```bash
istioctl proxy-config routes billing-api-79b8c5647f-8x2d1.production --name 8080
# → NOTE: This output shows RouteConfiguration 8080
# → NAME     DOMAINS                        MATCH                  VIRTUAL SERVICE
# → 8080     billing.internal.local         /*                     billing-traffic-split.production
```

Анализ access-логов Envoy для локализации ошибок и кодов ответа:

```bash
kubectl logs billing-api-79b8c5647f-8x2d1 -c istio-proxy --tail=10
# → [2026-10-13T19:35:12.102Z] "POST /api/v1/charge HTTP/1.1" 200 - via_upstream - "-" 154 280 14 14 "-" "Go-http-client/1.1" "9a42f8c5-1b42" "billing.internal.local" "10.244.2.45:8080" outbound|8080||billing-canary.production.svc.cluster.local 10.244.1.88:45210 10.244.2.45:8080 10.244.1.88:38192 - default
```

Проверка типа инъекции sidecar (Native Sidecar в `initContainers` vs классический):

```bash
kubectl get pod billing-api-79b8c5647f-8x2d1 -n production -o jsonpath='{.spec.initContainers[?(@.name=="istio-proxy")].restartPolicy}'
# → Always
```

Инспекция mTLS статуса и контекста безопасности пода:

```bash
istioctl x describe pod billing-api-79b8c5647f-8x2d1 -n production
# → Pod: billing-api-79b8c5647f-8x2d1
# →    Pod Ports: 8080 (http-app), 9090 (metrics)
# → --------------------
# → Service: billing-stable
# →    Port: http 8080/HTTP targets pod port 8080
# → --------------------
# → Effective PeerAuthentication:
# →    Workload mTLS mode: STRICT
```

## 5. Лучшие практики (Best Practices)

1. **Гарантированное выделение ресурсов для Envoy:**
   Всегда задавайте `sidecar.istio.io/proxyCPU` и `sidecar.istio.io/proxyMemory` в аннотациях Deployment. Отсутствие requests приводит к непредсказуемому QoS-классу пода (`Burstable` или `BestEffort`) и рискам eviction при нехватке памяти на узле.
2. **Изоляция HPA через `ContainerResource`:**
   Никогда не используйте стандартную суммарную метрику `Resource: cpu` для подов со sidecar-прокси. Всегда настраивайте `type: ContainerResource` с `container: <app-name>`, чтобы интенсивность сетевой обработки Envoy не вызывала неконтролируемого масштабирования реплик.
3. **Обязательное включение `rewriteAppHTTPProbers`:**
   Используйте `sidecar.istio.io/rewriteAppHTTPProbers: "true"`. Это исключает конфликты со строгим режимом mTLS и позволяет kubelet надежно проверять состояние приложения без открытия уязвимых non-mTLS портов.
4. **Синхронизация жизненного цикла и PreStop:**
   Добавляйте `lifecycle.preStop.exec` с командой `sleep 5..10` в контейнер приложения. Устанавливайте `terminationGracePeriodSeconds` не менее чем на 15–20 секунд больше суммы `preStop` и `terminationDrainDuration`.
5. **Ограничение Discovery Scope через `Sidecar` CRD:**
   Создавайте неймспейсовый ресурс `Sidecar` для каждого сервиса или неймспейса. Ограничивайте видимость только реально необходимыми зависимостями (`./*`, `istio-system/*`), чтобы защитить прокси от утечек памяти при росте кластера.
6. **Выделенный ServiceAccount для каждого Deployment:**
   Не используйте ServiceAccount `default`. Каждому Deployment должен соответствовать индивидуальный ServiceAccount. Это обеспечивает уникальный криптографический SPIFFE ID (`spiffe://cluster.local/ns/<ns>/sa/<sa-name>`) для точечных политик `AuthorizationPolicy`.
7. **Отказ от ручного подбора подов для Canary:**
   Не используйте два Deployment с одинаковым селектором для канареечных выкаток. Разделяйте сервисы (`billing-stable`, `billing-canary`) и управляйте весами на уровне L7 через `HTTPRoute` или `VirtualService`.

## 6. Дополнительная информация

### См. также

- [Deployment в Kubernetes: Обзор](./index.md) — базовая архитектура контроллера и управление репликами.
- [Манифест Deployment: Полная спецификация](./deployment_manifest.md) — детальный справочник по всем полям манифеста.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — rolling updates, откат ревизий и прогресс выкатки.
- [Прогрессивная доставка (Progressive Delivery)](./progressive_delivery.md) — автоматизация канареечных релизов через Argo Rollouts и Flagger.
- [Deployment с GitOps](./deployment_with_gitops.md) — синхронизация и паттерны развертывания через ArgoCD и Flux.
- [Service Mesh концепции](../../../Service_Mesh/service_mesh_concepts.md) — фундаментальные принципы сервисных сетей.
- [Архитектура Istio](../../../Service_Mesh/istio_architecture.md) — структура Control Plane и Data Plane.
- [Конфигурация Sidecar в Istio](../../../Service_Mesh/istio-sidecar-configuration.md) — тонкая настройка ресурса Sidecar и xDS-оптимизация.
- [Graceful Shutdown и длинные соединения в Istio](../../../Service_Mesh/istio-graceful-shutdown.md) — глубокий разбор дренажа соединений и Envoy.
- [Политики безопасности Istio](../../../Service_Mesh/istio-security-policies.md) — Zero-Trust, mTLS и AuthorizationPolicy.
- [Маршрутизация в Gateway API](../../Networking/gateway_api/routing_features.md) — возможности HTTPRoute, перенаправления и фильтрации.
- [HPA: Продвинутая настройка](../../Autoscaling/HPA/hpa_advanced.md) — масштабирование по ContainerResource, поведение behavior и стабилизация.
