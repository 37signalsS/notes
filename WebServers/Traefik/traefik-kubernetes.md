# Traefik в Kubernetes: CRD, RBAC, Helm, NetworkPolicy

**Актуально для:** Traefik v3.3+ / Kubernetes v1.28–v1.32+ / Helm Chart traefik v34.x

## Определения

**IngressRoute** — основной Custom Resource Definition (CRD) Traefik (`traefik.io/v1alpha1`) для L7 HTTP/HTTPS маршрутизации, заменяющий стандартный Kubernetes `Ingress`. Объединяет матчеры правил (Rules), подключение Middleware, выбор стратегии балансировки и привязку TLS в едином декларативном ресурсе.

**IngressRouteTCP / IngressRouteUDP** — CRD Traefik (`traefik.io/v1alpha1`) для L4-маршрутизации чистого TCP и UDP трафика (базы данных, Redis, MQTT, Syslog, DNS) с поддержкой SNI Passthrough, TLS-терминации и PROXY Protocol.

**Middleware / MiddlewareTCP** — CRD Traefik (`traefik.io/v1alpha1`) для конвейерной обработки входящих запросов и ответов (добавление security-заголовков, rate limiting, IP allowlist, базовая аутентификация, ограничение параллельных соединений InFlightReq).

**TLSOption** — CRD Traefik (`traefik.io/v1alpha1`) для тонкой настройки параметров TLS-рукопожатия: минимальная/максимальная версии протокола, наборы шифров (cipher suites), ALPN (HTTP/2, HTTP/1.1), строгая проверка SNI (`sniStrict`) и mTLS (клиентская аутентификация).

**TLSStore** — CRD Traefik (`traefik.io/v1alpha1`) для глобального управления хранилищами TLS-сертификатов, включая определение сертификата по умолчанию (`defaultCertificate`), отдаваемого клиентам при отсутствии совпадений по SNI.

**ServersTransport / ServersTransportTCP** — CRD Traefik (`traefik.io/v1alpha1`), определяющий параметры сетевого соединения между Traefik и бэкенд-подами: проверка/пропуск сертификатов бэкенда (`insecureSkipVerify`), кастомные Root CA, mTLS к сервисам, таймауты подключения (dial/idle), пулы соединений и отключение HTTP/2.

**TraefikService** — CRD Traefik (`traefik.io/v1alpha1`), реализующий расширенную балансировку между несколькими Kubernetes Services: взвешенное распределение трафика (Weighted Round Robin для Canary-релизов), автоматический Failover и зеркалирование запросов (Mirroring).

**IngressClass** — стандартный ресурс Kubernetes (`networking.k8s.io/v1`), определяющий класс контроллера, который должен обрабатывать данный ресурс маршрутизации через контроллерное имя `traefik.io/ingress-controller`.

**Direct Pod Routing (EndpointSlice)** — архитектурный режим работы Traefik в Kubernetes по умолчанию, при котором трафик направляется напрямую на IP-адреса целевых подов (получаемые через `EndpointSlice`), минуя виртуальный IP сервиса (`ClusterIP`) и механизм `kube-proxy` (iptables/IPVS).

**NativeLB** — директива в сервисе Traefik (`nativeLB: true`), отключающая прямое обращение к IP подов и переключающая маршрутизацию на виртуальный ClusterIP сервиса, делегируя балансировку уровню ядра Linux (`kube-proxy`).

**Cross-Namespace Routing** — механизм маршрутизации или применения Middleware между разными пространствами имен Kubernetes. В целях безопасности изолируется директивой `--providers.kubernetescrd.allowcrossnamespace=false`.

---

## Базовые концепции

### Архитектура Traefik Ingress Controller в Kubernetes

Traefik функционирует внутри кластера Kubernetes как контроллер и обратный прокси-сервер (Data Plane + Control Plane в одном бинарнике):

```text
                                  Входящий трафик (L4/L7)
                                             │
                                             ▼
                 ┌────────────────────────────────────────────────────────┐
                 │       Traefik Pod (Deployment / DaemonSet)             │
                 │                                                        │
                 │  ┌──────────────────────────────────────────────────┐  │
  K8s API Server │  │ Watchers & Informers (SharedIndexInformer)       │  │
       ▲         │  │ - traefik.io (IngressRoute, Middleware, ...)     │  │
       │         │  │ - networking.k8s.io (Ingress, IngressClass)      │  │
       │         │  │ - discovery.k8s.io (EndpointSlices)              │  │
       │         │  │ - core (Services, Secrets, Endpoints)            │  │
       │         │  └──────────────────────────┬───────────────────────┘  │
       │                                       │                          │
       │                                       ▼                          │
       │                           Динамическая конфигурация              │
       │                           (Маршруты, TLS, Сервисы)               │
       │                                       │                          │
       │                                       ▼                          │
       │                       Прямой роутинг (Direct Pod IP)             │
       └───────────────────────────────┬─────────────────┬────────────────┘
                                       │                 │
                (минуя kube-proxy)     │                 │ (минуя kube-proxy)
                                       ▼                 ▼
                              ┌────────────────┐ ┌────────────────┐
                              │ App Pod 1 (IP) │ │ App Pod 2 (IP) │
                              │ Namespace: app │ │ Namespace: app │
                              └────────────────┘ └────────────────┘
```

1. **Watch & Informers:** Traefik подключается к API-серверу Kubernetes через `SharedIndexInformer` и подписывается на события создания, изменения и удаления ресурсов CRD (`traefik.io`), стандартных `Ingress`, а также объектов `EndpointSlice` и `Secret`.
2. **Direct Pod Routing vs NativeLB:** По умолчанию Traefik извлекает адреса готовых подов из `EndpointSlice` и самостоятельно выполняет балансировку (Round Robin, P2C, замер latency). Это исключает лишний транзитный хоп через `kube-proxy` (IPVS/iptables), обеспечивает поддержку сессионной липкости (`sticky sessions`) и точный мониторинг состояния каждого экземпляра бэкенда. При указании `nativeLB: true` Traefik отправляет запросы на ClusterIP, передавая управление балансировкой ядру ноды.
3. **Безопасность и многопользовательская изоляция (Multi-Tenancy):**
   - По умолчанию параметр `--providers.kubernetescrd.allowcrossnamespace=false` запрещает объекту `IngressRoute` в одном пространстве имен ссылаться на `Middleware` или `Service` из другого пространства имен. Это предотвращает несанкционированный перехват чужих сервисов или внедрение неавторизованных middleware в многопользовательских кластерах.
   - Параметр `--providers.kubernetescrd.allowexternalnameservices=false` блокирует обращение к сервисам типа `ExternalName`, предотвращая атаки класса Server-Side Request Forgery (SSRF) и неконтролируемый доступ во внутренние сети инфраструктуры.

### Полный спектр CRD Traefik (`traefik.io/v1alpha1`)

Traefik v3 предоставляет 10 специализированных CRD, покрывающих все аспекты сетевой маршрутизации и безопасности:

| CRD | Уровень | Назначение |
| :--- | :--- | :--- |
| **IngressRoute** | L7 (HTTP/HTTPS) | Маршрутизация HTTP, сопоставление путей и заголовков, привязка middleware и TLS |
| **IngressRouteTCP** | L4 (TCP) | Маршрутизация TCP, сопоставление по SNI (`HostSNI`), TLS-терминация или Passthrough |
| **IngressRouteUDP** | L4 (UDP) | Маршрутизация UDP по портам (DNS, Syslog, VoIP) |
| **Middleware** | L7 (HTTP/HTTPS) | Модификация HTTP-запросов/ответов, заголовки, Basic/Forward Auth, RateLimit, Retry |
| **MiddlewareTCP** | L4 (TCP) | Фильтрация TCP-соединений: `ipAllowList`, ограничение соединений `inFlightReq` |
| **TLSOption** | L4/L7 (TLS) | Настройка TLS-параметров: cipher suites, версии TLS, mTLS, strict SNI |
| **TLSStore** | L4/L7 (TLS) | Хранилище сертификатов по умолчанию (`defaultCertificate`) для необслуженных SNI |
| **ServersTransport** | L7 (HTTP/HTTPS) | Параметры апстрим-соединения: Root CA, mTLS, timeouts, отключение HTTP/2 |
| **ServersTransportTCP** | L4 (TCP) | Параметры апстрим-соединения TCP: mTLS к бэкенду, таймауты dial |
| **TraefikService** | L7 (Агрегация) | Балансировка между сервисами: Weighted Round Robin (Canary), Mirroring, Failover |

### Сосуществование провайдеров и Gateway API

Traefik v3 способен одновременно запускать и агрегировать правила из нескольких провайдеров:
- `kubernetesCRD` — приоритетный нативный провайдер для расширенных возможностей Traefik.
- `kubernetesIngress` — стандартный провайдер для поддержки классических спецификаций `networking.k8s.io/v1 Ingress`.
- `kubernetesGateway` — провайдер реализации Kubernetes Gateway API (`gateway.networking.k8s.io`). Подробная реализация, спецификации GatewayClass, Gateway, HTTPRoute и ReferenceGrant вынесены в [Traefik Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md).

---

## Практические сценарии

### Сценарий 1: Исчерпывающий набор CRD в действии

Комплексный пример развертывания безопасного приложения: L7 HTTP-маршрутизация с канареечным сервисом `TraefikService`, L4 TCP-проксирование базы данных, строгий `TLSOption`, fallback-сертификат в `TLSStore` и взаимный TLS с бэкендом через `ServersTransport`.

```yaml
# 1. Сертификат по умолчанию для необслуженных SNI
apiVersion: traefik.io/v1alpha1
kind: TLSStore
metadata:
  name: default
  namespace: traefik
spec:
  defaultCertificate:
    secretName: wildcard-default-tls
---
# 2. Современный профиль TLS (TLS 1.3, строгий SNI)
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
  name: modern-tls
  namespace: prod
spec:
  minVersion: VersionTLS13
  sniStrict: true
  alpnProtocols:
    - h2
    - http/1.1
---
# 3. Транспорт соединения с апстрим-подами (внутренний CA и таймауты)
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata:
  name: secure-upstream-transport
  namespace: prod
spec:
  serverName: backend.internal
  insecureSkipVerify: false
  rootCAsSecrets:
    - internal-ca-cert
  forwardingTimeouts:
    dialTimeout: 5s
    responseHeaderTimeout: 30s
    idleConnTimeout: 90s
  maxIdleConnsPerHost: 200
  disableHTTP2: false
---
# 4. Middleware: Заголовки безопасности и Rate Limiting
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: prod-security-headers
  namespace: prod
spec:
  headers:
    stsSeconds: 31536000
    stsIncludeSubdomains: true
    stsPreload: true
    forceSTSHeader: true
    contentTypeNosniff: true
    browserXssFilter: true
    customFrameOptionsValue: SAMEORIGIN
---
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: api-rate-limit
  namespace: prod
spec:
  rateLimit:
    average: 100
    burst: 50
    period: 1s
---
# 5. TraefikService: Взвешенное разделение трафика (Canary 90/10)
apiVersion: traefik.io/v1alpha1
kind: TraefikService
metadata:
  name: app-canary-service
  namespace: prod
spec:
  weighted:
    services:
      - name: app-v1-service
        port: 8080
        weight: 90
      - name: app-v2-service
        port: 8080
        weight: 10
---
# 6. Основной IngressRoute для L7 трафика
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: app-ingressroute
  namespace: prod
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`app.example.com`) && PathPrefix(`/api`)
      kind: Rule
      priority: 100
      services:
        - name: app-canary-service
          kind: TraefikService
          serversTransport: secure-upstream-transport
      middlewares:
        - name: prod-security-headers
        - name: api-rate-limit
  tls:
    secretName: app-example-tls
    options:
      name: modern-tls
```

### Сценарий 2: L4 Маршрутизация через IngressRouteTCP и IngressRouteUDP

Проксирование PostgreSQL (L4 TCP) с фильтрацией IP-адресов через `MiddlewareTCP` и syslog (L4 UDP).

```yaml
# TCP Middleware: ограничение доступа по IP к базе данных
apiVersion: traefik.io/v1alpha1
kind: MiddlewareTCP
metadata:
  name: db-ip-allowlist
  namespace: database
spec:
  ipAllowList:
    sourceRange:
      - 192.168.10.0/24
      - 10.244.0.0/16
---
# IngressRouteTCP: Маршрутизация на основе SNI с Passthrough
apiVersion: traefik.io/v1alpha1
kind: IngressRouteTCP
metadata:
  name: postgres-routing
  namespace: database
spec:
  entryPoints:
    - postgres # Требует объявления entrypoint в Helm values
  routes:
    - match: HostSNI(`postgres.internal.example.com`)
      services:
        - name: postgres-cluster-rw
          port: 5432
          proxyProtocol:
            version: 2
      middlewares:
        - name: db-ip-allowlist
  tls:
    passthrough: true # TLS завершается на самом сервере PostgreSQL
---
# IngressRouteUDP: Проксирование UDP-потока (Syslog)
apiVersion: traefik.io/v1alpha1
kind: IngressRouteUDP
metadata:
  name: syslog-routing
  namespace: logging
spec:
  entryPoints:
    - syslog-udp
  routes:
    - services:
        - name: vector-syslog-svc
          port: 514
```

### Сценарий 3: Production RBAC для Traefik v3

Минимально необходимый и полный профиль прав ClusterRole, покрывающий все 10 CRD `traefik.io`, обновление статусов маршрутов, стандартные Ingress и механизм `discovery.k8s.io/endpointslices`.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: traefik-ingress-controller
  namespace: traefik
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: traefik-ingress-controller
rules:
  # Чтение базовой сетевой топологии
  - apiGroups: [""]
    resources:
      - services
      - endpoints
      - secrets
      - nodes
      - pods
      - namespaces
    verbs: ["get", "list", "watch"]
  # Современное обнаружение эндпоинтов (Kubernetes 1.28+)
  - apiGroups: ["discovery.k8s.io"]
    resources:
      - endpointslices
    verbs: ["get", "list", "watch"]
  # Стандартный Ingress и IngressClass
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
      - ingressclasses
    verbs: ["get", "list", "watch"]
  # Обновление статуса адреса внешнего балансировщика в объектах Ingress
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses/status
    verbs: ["update"]
  # Полный реестр CRD Traefik
  - apiGroups: ["traefik.io"]
    resources:
      - ingressroutes
      - ingressroutetcps
      - ingressrouteudps
      - middlewares
      - middlewaretcps
      - tlsoptions
      - tlsstores
      - serverstransports
      - serverstransportstcps
      - traefikservices
    verbs: ["get", "list", "watch"]
  # Обновление статусов выполнения маршрутов Traefik
  - apiGroups: ["traefik.io"]
    resources:
      - ingressroutes/status
      - ingressroutetcps/status
      - ingressrouteudps/status
    verbs: ["update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: traefik-ingress-controller
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: traefik-ingress-controller
subjects:
  - kind: ServiceAccount
    name: traefik-ingress-controller
    namespace: traefik
```

### Сценарий 4: Полная production-grade NetworkPolicy

Реальная политика сетевой изоляции для Ingress-контроллера. Разрешает входящие HTTP/HTTPS/metrics запросы и исходящий трафик строго к DNS, API-серверу и пространствам имен приложений на порты целевых подов.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: traefik-ingress-policy
  namespace: traefik
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: traefik
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # 1. Входящий публичный клиентский трафик
    - from: []
      ports:
        - protocol: TCP
          port: 8000 # Внутренний контейнерный порт HTTP
        - protocol: TCP
          port: 8443 # Внутренний контейнерный порт HTTPS
    # 2. Скрапинг метрик оператором Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 9100
    # 3. Kubelet health-checks и Dashboard
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: TCP
          port: 9000
  egress:
    # 1. Доступ к CoreDNS в kube-system
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # 2. Доступ к Kubernetes API Server (управляющий контур)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0 # В on-premise замените на подсеть master-нод
      ports:
        - protocol: TCP
          port: 6443
        - protocol: TCP
          port: 443
    # 3. Исходящий трафик к подам приложений в кластере
    - to:
        - namespaceSelector:
            matchLabels:
              env: production
        - namespaceSelector:
            matchLabels:
              env: staging
      ports:
        - protocol: TCP
          port: 80
        - protocol: TCP
          port: 443
        - protocol: TCP
          port: 8080
        - protocol: TCP
          port: 8443
        - protocol: TCP
          port: 3000
        - protocol: TCP
          port: 5432
```

### Сценарий 5: Production Helm values (`values.yaml`) для Bare-Metal

Конфигурация официального Helm-чарта `traefik/traefik` для отказоустойчивого On-Premise / Bare-Metal кластера с балансировкой через MetalLB, жестким SecurityContext, топологическим распределением подов и интеграцией с Prometheus Operator.

```yaml
# Репликация и планирование на ноды
deployment:
  enabled: true
  replicas: 3
  annotations: {}
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9100"
  podSecurityContext:
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    fsGroup: 65532
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    runAsNonRoot: true
    runAsUser: 65532
    runAsGroup: 65532
    capabilities:
      drop:
        - ALL
      add:
        - NET_BIND_SERVICE
  resources:
    requests:
      cpu: "500m"
      memory: "512Mi"
    limits:
      cpu: "4000m"
      memory: "2Gi"
  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: traefik
            topologyKey: kubernetes.io/hostname
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: kubernetes.io/hostname
      whenUnsatisfiable: ScheduleAnyway
      labelSelector:
        matchLabels:
          app.kubernetes.io/name: traefik

# Подключение к сети bare-metal кластера через MetalLB
service:
  enabled: true
  type: LoadBalancer
  spec:
    externalTrafficPolicy: Local # Сохраняет оригинальный IP клиента, исключая SNAT на нодах
  annotations:
    metallb.universe.tf/address-pool: ingress-pool

# Настройка входных сетевых портов
ports:
  traefik:
    port: 9000
    expose:
      default: false
    exposedPort: 9000
    protocol: TCP
  web:
    port: 8000
    expose:
      default: true
    exposedPort: 80
    protocol: TCP
    redirectTo:
      port: websecure
  websecure:
    port: 8443
    expose:
      default: true
    exposedPort: 443
    protocol: TCP
    tls:
      enabled: true
  metrics:
    port: 9100
    expose:
      default: true
    exposedPort: 9100
    protocol: TCP
  postgres:
    port: 5432
    expose:
      default: true
    exposedPort: 5432
    protocol: TCP

# Регистрация IngressClass по умолчанию
ingressClass:
  enabled: true
  isDefaultClass: true
  fallbackToEmptyClass: true

# Настройки внутренних провайдеров Traefik
providers:
  kubernetesCRD:
    enabled: true
    allowCrossNamespace: false
    allowExternalNameServices: false
    nativeLBByDefault: false
  kubernetesIngress:
    enabled: true
    allowExternalNameServices: false
    publishedService:
      enabled: true
      pathOverride: "traefik/traefik"

# Метрики и интеграция с Prometheus Operator
metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addServicesLabels: true
    addRoutersLabels: true
    serviceMonitor:
      enabled: true
      namespace: traefik
      interval: 15s
      telemetry: false

# Гарантия непрерывной доступности при обслуживании узлов
podDisruptionBudget:
  enabled: true
  minAvailable: 2

# Автоматическое создание ServiceAccount и RBAC
serviceAccount:
  create: true
  name: traefik-ingress-controller
rbac:
  enabled: true
```

---

## Операции и команды

### Инспекция состояния и обнаружения CRD

```bash
# 1. Проверка установки всех CRD группы traefik.io
kubectl get crd -l app.kubernetes.io/name=traefik
# → NAME                                    CREATED AT
# → ingressroutes.traefik.io                2026-02-10T10:00:00Z
# → ingressroutetcps.traefik.io             2026-02-10T10:00:00Z
# → ingressrouteudps.traefik.io             2026-02-10T10:00:00Z
# → middlewares.traefik.io                  2026-02-10T10:00:00Z
# → middlewaretcps.traefik.io               2026-02-10T10:00:00Z
# → serverstransports.traefik.io            2026-02-10T10:00:00Z
# → serverstransportstcps.traefik.io        2026-02-10T10:00:00Z
# → tlsoptions.traefik.io                   2026-02-10T10:00:00Z
# → tlsstores.traefik.io                    2026-02-10T10:00:00Z
# → traefikservices.traefik.io              2026-02-10T10:00:00Z

# 2. Проверка состояния конкретного IngressRoute во всех пространствах имен
kubectl get ingressroute -A
# → NAMESPACE   NAME                 AGE
# → prod        app-ingressroute     5d2h

# 3. Получение подробного статуса маршрутизации и валидации IngressRoute
kubectl describe ingressroute app-ingressroute -n prod
# → Status:
# →   Parents:
# →     Conditions:
# →       Last Transition Time:  2026-02-15T12:00:00Z
# →       Message:               Route is valid and loaded
# →       Reason:                Valid
# →       Status:                True
# →       Type:                  Loaded
```

### Диагностика Direct Pod Routing и EndpointSlices

```bash
# 1. Просмотр EndpointSlice, используемых Traefik для прямой балансировки
kubectl get endpointslices -l kubernetes.io/service-name=app-v1-service -n prod
# → NAME                         ADDRESSTYPE   PORTS   ENDPOINTS                            AGE
# → app-v1-service-k2b7x         IPv4          8080    10.244.1.45,10.244.2.112             4d

# 2. Проверка соответствия IP-адресов подов в EndpointSlice
kubectl get pods -n prod -l app=app-v1 -o custom-columns=NAME:.metadata.name,IP:.status.podIP,STATUS:.status.phase
# → NAME                        IP             STATUS
# → app-v1-79b8f67d4-8d4j1      10.244.1.45    Running
# → app-v1-79b8f67d4-k9x11      10.244.2.112   Running
```

### Проверка RBAC полномочий контроллера

```bash
# Проверка прав ServiceAccount на чтение EndpointSlices
kubectl auth can-i get endpointslices.discovery.k8s.io --as=system:serviceaccount:traefik:traefik-ingress-controller
# → yes

# Проверка прав на чтение секретов (TLS сертификатов)
kubectl auth can-i get secrets --as=system:serviceaccount:traefik:traefik-ingress-controller
# → yes

# Проверка прав на обновление статуса Ingress
kubectl auth can-i update ingresses/status.networking.k8s.io --as=system:serviceaccount:traefik:traefik-ingress-controller
# → yes
```

### Сбор метрик и оперативная отладка API Traefik

```bash
# 1. Локальный проброс порта метрик Prometheus
kubectl port-forward -n traefik svc/traefik 9100:9100 &
PID=$!
sleep 1

# 2. Запрос базовых счетчиков трафика
curl -s http://localhost:9100/metrics | grep -E "traefik_entrypoint_requests_total|traefik_service_requests_total" | head -n 10
# → # HELP traefik_entrypoint_requests_total How many HTTP requests processed on an entrypoint, partitioned by status code, protocol, and method.
# → traefik_entrypoint_requests_total{code="200",entrypoint="websecure",method="GET",protocol="https"} 142051
# → traefik_entrypoint_requests_total{code="404",entrypoint="websecure",method="GET",protocol="https"} 32

kill $PID
```

---

## Устранение неисправностей

| Проблема | Диагностика | Первопричина | Решение |
| :--- | :--- | :--- | :--- |
| **404 Not Found при обращении к маршруту** | `kubectl logs -n traefik -l app.kubernetes.io/name=traefik \| grep "Configuration error"` | Несовпадение IngressClass, опечатка в правиле Matcher (в v3 синтаксис строгий: `Header(...)` вместо `Headers(...)`), либо маршрут не зарегистрирован на целевом entrypoint. | Проверьте директиву `spec.entryPoints` в IngressRoute и совпадение Host-заголовка. Проверьте флаг `--providers.kubernetescrd.ingressclass`. |
| **502 Bad Gateway при обращении к бэкенду** | `kubectl logs -n traefik \| grep "502"` и `kubectl get endpointslices -n <ns>` | Traefik пытается доставить запрос на удаленный/перезагруженный под, адрес которого еще не очищен в EndpointSlice, либо целевой сервис слушает другой порт. | Настройте `lifecycle.preStop` с задержкой `sleep 5` в подах приложений. Проверьте соответствие `service.port` реальному порту контейнера. |
| **RBAC PermissionDenied в логах Traefik** | `kubectl logs -n traefik \| grep "forbidden"` | В `ClusterRole` отсутствуют права на чтение `discovery.k8s.io/endpointslices` или ресурсов группы `traefik.io`. | Примените обновленный манифест ClusterRole из Сценария 3, включив все 10 CRD и EndpointSlices. |
| **Middleware rejected across namespace** | В логах: `middleware <ns>/<name> is not allowed from namespace <ns2>` | Включен режим безопасности `--providers.kubernetescrd.allowcrossnamespace=false` (рекомендован), а IngressRoute ссылается на Middleware из чужого пространства имен. | Перенесите манифест Middleware в то же пространство имен, где находится IngressRoute, либо дублируйте его локально. |
| **NetworkPolicy блокирует трафик** | `tcpdump -nn -i any port 53` внутри пода Traefik возвращает timeout | Сетевая политика запрещает egress к CoreDNS (`kube-system`) или к пространству имен с приложением. | Добавьте правила egress в NetworkPolicy контроллера для UDP/TCP порта 53 и портов целевых сервисов (см. Сценарий 4). |
| **PDB блокирует выведение узла из эксплуатации (drain)** | `kubectl drain <node> --ignore-daemonsets` зависает с ошибкой `Cannot evict pod as it would violate the pod's disruption budget.` | Задано `minAvailable: 2`, но доступно только 2 реплики Traefik, одна из которых находится на дренируемой ноде. | Увеличьте общее число реплик Traefik (`replicas: 3`) или скорректируйте PDB на `maxUnavailable: 1` / `minAvailable: 1`. |
| **Потеря реального IP клиента в логах (`10.244.x.x` вместо публичного)** | В логах access-log клиента отображается IP ноды кластера | Service балансировщика использует `externalTrafficPolicy: Cluster`, что приводит к выполнению SNAT ядром ноды. | Установите в Service: `spec.externalTrafficPolicy: Local`. При необходимости включите PROXY Protocol на внешнем L4 балансировщике и в Traefik entryPoints. |
| **TLS Handshake Error: Unknown Certificate** | `openssl s_client -connect app.example.com:443 -servername app.example.com` | Секрет с TLS-сертификатом отсутствует, находится в другом namespace или поврежден ключ. | Проверьте наличие секрета командой `kubectl get secret -n <ns>`. Для сертификата по умолчанию настройте `TLSStore` с именем `default`. |

---

## Рекомендации

1. **Режим высокой доступности (HA):** Всегда развертывайте Traefik с минимум 3 репликами, используя `podAntiAffinity` по признаку `kubernetes.io/hostname` и `PodDisruptionBudget` (`minAvailable: 1` или `maxUnavailable: 1`).
2. **Прямая маршрутизация на поды:** Сохраняйте режим по умолчанию (`nativeLB: false`). Это минимизирует задержки, исключает транзитные пересылки трафика между нодами через `kube-proxy` и позволяет Traefik точно отслеживать состояние отдельных подов.
3. **Безопасность пространств имен:** В продакшн-кластерах никогда не активируйте флаги `--providers.kubernetescrd.allowcrossnamespace=true` и `--providers.kubernetescrd.allowexternalnameservices=true`. Доступ между пространствами имен должен контролироваться централизованно.
4. **Сохранение реального Client IP:** На On-Premise/Bare-Metal кластерах используйте MetalLB с `spec.externalTrafficPolicy: Local`. При использовании внешних аппаратных балансировщиков (HAProxy, F5) передавайте заголовок через PROXY Protocol v2.
5. **Безопасность контейнеров (SecurityContext):** Запускайте контейнер Traefik под непривилегированным пользователем (`runAsNonRoot: true`, UID/GID `65532`), с защитой файловой системы от записи (`readOnlyRootFilesystem: true`) и сбросом всех Linux capabilities, оставляя только `NET_BIND_SERVICE`.
6. **Graceful Shutdown и Connection Draining:** Добавляйте `lifecycle.preStop` с задержкой 5–10 секунд в Deployment Traefik и приложения, чтобы контроллер успел исключить pod из активных маршрутов до закрытия соединений (см. [Traefik Graceful Shutdown](./traefik-graceful-shutdown.md)).
7. **Управление сертификатами:** Для автоматизации жизненного цикла Let's Encrypt сертификатов в многоузловом кластере используйте связку с cert-manager через DNS-01 или HTTP-01 проверки, сохраняя сертификаты в нативные K8s Secrets (см. [cert-manager и Traefik IngressRoute](./traefik-cert-manager-ingressroute-tls.md)).

---

## Дополнительная информация

- [Архитектура и обзор Traefik](./traefik_overview.md) — базовые концепции маршрутизации, entrypoints и провайдеров.
- [High Availability Traefik: отказоустойчивость и zero-downtime](./traefik-high-availability.md) — организация L4 VIP, MetalLB, BGP Anycast и резервирования.
- [Автоматический TLS с cert-manager и Traefik IngressRoute](./traefik-cert-manager-ingressroute-tls.md) — автоматический выпуск и ротация сертификатов Let's Encrypt в кластере.
- [TLSOption в Traefik](./traefik-tls-options.md) — глубокое погружение в настройку шифров, протоколов TLS и клиентских сертификатов (mTLS).
- [Паттерны развертывания и прогрессивная доставка](./traefik-deployments.md) — Canary, Blue-Green релизы через TraefikService и Flagger.
- [Traefik Graceful Shutdown](./traefik-graceful-shutdown.md) — жизненный цикл соединений, сигналы SIGTERM и предотвращение ошибок 502/504.
- [Наблюдаемость Traefik: Метрики, Трейсинг, Логи](./traefik-observability.md) — настройка Prometheus, OpenTelemetry и структурированных access-логов.
- [Безопасность и Hardening Traefik](./traefik-security-hardening.md) — защита от атак, rate limiting, заголовки безопасности OWASP.
- [Traefik и Kubernetes Gateway API](../../Kubernetes/Networking/gateway_api/traefik.md) — реализация стандарта Gateway API (GatewayClass, Gateway, HTTPRoute, GRPCRoute).
- [Базовая аутентификация в Kubernetes с Traefik](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) — реализация BasicAuth Middleware через K8s Secrets.
- [Взаимодействие NetworkPolicy и Ingress Controller](../../Kubernetes/Networking/Network/NetworkPolicy/ingress_controller_interaction.md) — правила сетевой фильтрации CNI для ingress-контроллеров.
- [Сравнение Ingress-контроллеров](../../Kubernetes/Networking/Ingress/controllers_comparison.md) — сравнительный анализ Traefik, NGINX, HAProxy и Envoy.
- [Установка Ingress-контроллеров через Helm](../../Kubernetes/Networking/Ingress/installation/helm-installation.md) — методология управления чартами в Kubernetes.
