# Traefik в Kubernetes: CRD, RBAC, Helm, NetworkPolicy

## Определения

**IngressRoute** — CRD Traefik, заменяющий стандартный Ingress. Описывает роутер, middleware и сервис в одном объекте.

**Middleware (CRD)** — CRD для middleware, переиспользуемых между несколькими IngressRoute.

**TLSOption** — CRD для централизованного управления TLS-параметрами (minVersion, cipherSuites, clientAuth).

**ServersTransport** — CRD для управления TLS и таймаутами при соединении Traefik с бэкендом.

**IngressClass** — стандартный K8s ресурс для указания, какой Ingress-контроллер обрабатывает Ingress/IngressRoute.

**ServiceMonitor** — CRD Prometheus Operator для автоматического скрапинга метрик Traefik.

**PodDisruptionBudget** — ограничение количества одновременно недоступных подов Traefik при drain/обновлении.

## Базовые концепции

### CRD Traefik: полный набор

Traefik устанавливает четыре собственных CRD (группа `traefik.io`, версия `v1alpha1`):

| CRD | Назначение |
| :--- | :--- |
| **IngressRoute** | Маршрутизация (роутер + сервис + middleware) |
| **Middleware** | Переиспользуемые middleware |
| **TLSOption** | TLS-параметры для роутеров |
| **ServersTransport** | Параметры соединения с бэкендом |

### RBAC

Traefik требует прав на чтение ресурсов Kubernetes (Services, Endpoints, Ingress, Secrets, Nodes). Минимальные роли:

- **ServiceAccount** — идентификация Traefik в кластере.
- **ClusterRole** — права на чтение Services, Endpoints/Endpointslices, Ingress, Secrets, Nodes, Pods, Namespaces.
- **ClusterRoleBinding** — привязка ServiceAccount к ClusterRole.

### NetworkPolicy

По умолчанию Traefik pod не имеет сетевых ограничений. Рекомендуется:
- Разрешить inbound на порты 80, 443, 8080 (dashboard, опционально), 9100 (метрики, опционально).
- Разрешить outbound к Namespace `kube-system` (DNS) и к namespaces с бэкендами.
- Запретить весь остальной traffic.

### Helm chart

Официальный chart `traefik/traefik` управляет всеми компонентами: Deployment, Service, RBAC, CRD, NetworkPolicy, ServiceMonitor. Values.yaml позволяет тонко настраивать каждый аспект.

### PodDisruptionBudget

Обеспечивает минимальное количество доступных подов Traefik при плановых работах (node drain, upgrade).

## Практические сценарии

### Сценарий 1: Полный набор CRD

```yaml
# IngressRoute
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: app
  namespace: prod
spec:
  entryPoints:
    - websecure
  routes:
  - match: Host(`app.example.com`) && PathPrefix(`/`)
    kind: Rule
    services:
    - name: app-service
      port: 8080
      healthCheck:
        path: /health
        interval: 10s
        timeout: 3s
    middlewares:
    - name: secure-headers
      namespace: prod
---
# Middleware
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: secure-headers
  namespace: prod
spec:
  headers:
    stsSeconds: 31536000
    browserXssFilter: true
    contentTypeNosniff: true
    forceSTSHeader: true
    stsIncludeSubdomains: true
    stsPreload: true
---
# TLSOption
apiVersion: traefik.io/v1alpha1
kind: TLSOption
metadata:
  name: modern
  namespace: prod
spec:
  minVersion: VersionTLS13
  sniStrict: true
---
# ServersTransport
apiVersion: traefik.io/v1alpha1
kind: ServersTransport
metadata:
  name: backend-tls
  namespace: prod
spec:
  insecureSkipVerify: false
  rootCAs:
  - secret: backend-ca
  forwardingTimeouts:
    dialTimeout: 30s
    responseHeaderTimeout: 0s
    idleConnTimeout: 90s
  maxIdleConnsPerHost: 200
```

### Сценарий 2: RBAC

```yaml
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: traefik
  namespace: traefik
---
# ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: traefik
rules:
- apiGroups: [""]
  resources: ["services", "endpoints", "secrets", "nodes", "pods", "namespaces"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["networking.k8s.io"]
  resources: ["ingresses", "ingressclasses"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["traefik.io"]
  resources: ["ingressroutes", "middlewares", "tlsoptions", "serverstransports"]
  verbs: ["get", "list", "watch"]
---
# ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: traefik
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: traefik
subjects:
- kind: ServiceAccount
  name: traefik
  namespace: traefik
```

### Сценарий 3: NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: traefik
  namespace: traefik
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: traefik
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: traefik
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 9100
  - from: []
    ports:
    - protocol: TCP
      port: 80
    - protocol: TCP
      port: 443
  egress:
  - to: []
    ports:
    - protocol: TCP
      port: 53
    - protocol: UDP
      port: 53
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 443
```

### Сценарий 4: ServiceMonitor

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: traefik
  namespace: traefik
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
    bearerTokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
    tlsConfig:
      insecureSkipVerify: true
      caFile: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

### Сценарий 5: PodDisruptionBudget

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: traefik
  namespace: traefik
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: traefik
```

### Сценарий 6: Helm values (минимальный production-ready)

```yaml
# values.yaml
deployment:
  replicas: 2
  podAnnotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9100"
  additionalContainers: []
  initContainers: []

service:
  type: LoadBalancer
  annotations:
    metallb.universe.tf/address-pool: production-pool

ports:
  web:
    expose:
      default: true
  websecure:
    expose:
      default: true
  metrics:
    expose:
      default: true

metrics:
  prometheus:
    entryPoint: metrics
    addEntryPointsLabels: true
    addServicesLabels: true
    addRoutersLabels: true

providers:
  kubernetesCRD:
    enabled: true
    allowExternalNameServices: false
    allowCrossNamespace: false
  kubernetesIngress:
    enabled: true
    publishedService:
      enabled: true

rbac:
  enabled: true

serviceAccount:
  create: true
  name: traefik

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70

podDisruptionBudget:
  enabled: true
  minAvailable: 1

networkPolicy:
  enabled: true
```

### Сценарий 7: Graceful shutdown в Kubernetes

```yaml
# В Deployment Traefik
spec:
  template:
    spec:
      containers:
      - name: traefik
        lifecycle:
          preStop:
            exec:
              command:
              - /bin/sh
              - -c
              - sleep 5
        readinessProbe:
          httpGet:
            path: /ping
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        livenessProbe:
          httpGet:
            path: /ping
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
```

### Сценарий 8: Gateway API (Traefik v3.3+)

Gateway API — современный стандарт Kubernetes (GA v1.0+), приходящий на смену Ingress. Traefik поддерживает его начиная с v3.3 через встроенный **Kubernetes Gateway Provider**.

#### Преимущества перед Ingress

- Ролевая модель: админ создает `Gateway` (инфраструктура), разработчик — `HTTPRoute`/`TCPRoute`/`GRPCRoute` (правила).
- Нативная поддержка L4 (TCP, UDP) и gRPC без аннотаций.
- Расширяемость через `PolicyAttachment` и `ReferenceGrant`.
- Прямое сопоставление с GAMMA (мессервисный трафик).

#### Установка CRD

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.0/standard-install.yaml
# → gateway.networking.k8s.io CRDs установлены
```

#### Базовый Gateway + HTTPRoute

```yaml
# Gateway
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: traefik
spec:
  gatewayClassName: traefik
  listeners:
  - name: web
    hostname: "*.example.com"
    port: 80
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: All
  - name: websecure
    hostname: "*.example.com"
    port: 443
    protocol: HTTPS
    tls:
      certificateRefs:
      - name: wildcard-tls
        kind: Secret
    allowedRoutes:
      namespaces:
        from: All
---
# HTTPRoute
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: app
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    forwardTo:
      service:
        name: app-service
        port: 8080
      weight: 100
    filters:
    - type: RequestHeaderModifier
      requestHeaderModifier:
        add:
        - name: X-Forwarded-Group
          value: prod
```

#### GRPCRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: grpc-api
  namespace: prod
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
  rules:
  - matches:
    - method:
        service: api.example.com
        method: GetUser
    forwardTo:
      service:
        name: grpc-backend
        port: 9090
```

#### TCPRoute

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: TCPRoute
metadata:
  name: postgres
  namespace: data
spec:
  parentRefs:
  - name: external-gw
    namespace: traefik
    port: 5432
  rules:
  - forwardTo:
    - service:
        name: postgres
        port: 5432
```

#### ReferenceGrant (cross-namespace secrets)

Если сертификат/секрет лежит в другом namespace:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: ReferenceGrant
metadata:
  name: allow-tls
  namespace: cert-manager
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: traefik
  to:
  - group: ""
    kind: Secret
    name: wildcard-tls
```

#### Helm chart (Gateway Provider)

```yaml
# values.yaml
gateway:
  enabled: true
  gatewayClassName: traefik

kubernetesGateway:
  enabled: true

# Для существующего Deployment Traefik
extraArgs:
  - "--providers.kubernetesgateway=true"
```

Проверка:

```bash
kubectl get gateway
kubectl get httproute -A
kubectl describe gateway external-gw -n traefik
# → Status: Ready=True, Listeners Ready
```

#### Ограничения и отладка

- Traefik **не поддерживает** все экспериментальные расширения Gateway API (например, `BackendTLSPolicy` в ранних версиях v3).
- При конфликте `IngressRoute` и `HTTPRoute` на один и тот же хост — приоритет у Gateway API (см. порядок провайдеров).
- Диагностика: `kubectl describe httproute <name>` — проверяйте `Conditions: Accepted=True, Programmed=True`.
- Логи Traefik содержат `gateway` и `httproute` в метках для correlation.

## Операции и команды

```bash
# Проверка CRD
kubectl get crd ingressroutes.traefik.io middlewares.traefik.io tlsoptions.traefik.io serverstransports.traefik.io

# Проверка IngressRoute
kubectl get ingressroute -A
kubectl describe ingressroute app -n prod

# Проверка middleware
kubectl get middleware -A

# Проверка TLSOption
kubectl get tlsoptions -A

# Проверка ServersTransport
kubectl get serverstransports -A

# Проверка RBAC
kubectl get serviceaccount,clusterrole,clusterrolebinding -n traefik | grep traefik

# Проверка NetworkPolicy
kubectl get networkpolicy -n traefik
kubectl describe networkpolicy traefik -n traefik

# Проверка ServiceMonitor
kubectl get servicemonitor -n traefik

# Проверка PodDisruptionBudget
kubectl get pdb -n traefik

# Проверка metrics
kubectl port-forward -n traefik svc/traefik 9100:9100
curl -s localhost:9100/metrics | head -n 20
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **IngressRoute не применяется** | CRD не установлен, ошибка в YAML | `kubectl get crd`, `kubectl describe ingressroute` |
| **Middleware не найден** | Middleware в другом namespace, нет `allowCrossNamespace` | Создайте middleware в том же namespace или используйте ForwardAuth изnamespace traefik |
| **TLS не работает** | TLSOption не привязан, сертификат отсутствует | Проверьте `tls.options` на IngressRoute, проверьте Secret с сертификатом |
| **Бэкенд недоступен** | ServersTransport с `insecureSkipVerify: true` для самоподписанного сертификата | Настройте `rootCAs` в ServersTransport |
| **Metrics пустые** | ServiceMonitor не настроен, порт metrics не expose | Проверьте ServiceMonitor, `kubectl port-forward` и curl |
| **PDB блокирует drain** | `minAvailable: 2`, но реплик только 2 | Убедитесь что `minAvailable <= replicas - 1` |
| **RBAC PermissionDenied** | ClusterRole слишком ограничен | Добавьте缺少的 ресурсы в ClusterRole |
| **NetworkPolicy блокирует трафик** | Правило egress не разрешает DNS | Добавьте egress на порт 53 (UDP/TCP) |

## Рекомендации

- Всегда используйте фиксированные версии CRD и Helm chart.
- Включайте `allowCrossNamespace: false` по умолчанию.
- Защищайте dashboard: `api.insecure: false`, отдельный Service type ClusterIP, BasicAuth/ForwardAuth.
- Для production используйте `minAvailable: 1` в PDB при 2+ репликах.
- ServiceMonitor — обязателен для Prometheus Operator; без него метрики не будут автоматически собираться.
- NetworkPolicy — включайте всегда, даже если CNI не поддерживает (игнорируется без воркеров).
- Используйте `publishedService` в providers.kubernetesIngress для корректного получения реального IP в логах.

## Дополнительная информация

- [Обзор Traefik](./traefik_overview.md) — архитектура и компоненты.
- [Gateway API Traefik](../../Kubernetes/Networking/gateway_api/traefik.md) — современный стандарт Kubernetes для Traefik.
- [BasicAuth в Kubernetes](../../Kubernetes/Security/traefik_kubernetes_basic_auth.md) — настройка аутентификации через CRD.
- [Helm installation](../../Kubernetes/Networking/Ingress/installation/helm-installation.md) — установка Traefik через Helm.
- [Ingress controllers comparison](../../Kubernetes/Networking/Ingress/controllers_comparison.md) — сравнение Ingress-контроллеров.
