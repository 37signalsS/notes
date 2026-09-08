# ServiceAccount, RBAC и NetworkPolicy: Взаимодействие слоёв

## Определения

**ServiceAccount** — объект Kubernetes, предоставляющий поду идентичность (identity) внутри кластера. Каждому поду автоматически назначается ServiceAccount (по умолчанию `default` в namespace). ServiceAccount используется для аутентификации запросов пода к API Server.

**RBAC (Role-Based Access Control)** — система авторизации Kubernetes, определяющая, какие действия (get, list, create, delete) ServiceAccount может выполнять с какими ресурсами (pods, services, secrets) в каких namespace или на уровне кластера.

**NetworkPolicy** — система фильтрации сетевого трафика, определяющая, какие поды могут общаться друг с другом по сети (L3/L4).

**Token Projection** — механизм автоматической ротации сервис-аккаунт токенов. Под получает временный токен (1 часа по умолчанию), который обновляется через API Server без перезапуска пода.

## Базовые Концепции

### Три слоя безопасности

```
┌─────────────────────────────────────────────────────────┐
│ 1. RBAC (Авторизация)                                  │
│    "Что ServiceAccount МОЖЕТ делать?"                   │
│    └── ClusterRole / Role + Bindings                    │
├─────────────────────────────────────────────────────────┤
│ 2. NetworkPolicy (Сетевая изоляция)                    │
│    "С кем под МОЖЕТ общаться по сети?"                  │
│    └── Ingress / Egress правила                         │
├─────────────────────────────────────────────────────────┤
│ 3. Admission Control (Допуск)                          │
│    "Конфигурация пода ДОПУСТИМА?"                       │
│    └── Pod Security Admission, Kyverno, OPA             │
└─────────────────────────────────────────────────────────┘
```

**Ключевой принцип:** Все три слоя работают независимо. RBAC разрешает доступ к API, но NetworkPolicy может блокировать сетевой трафик. NetworkPolicy разрешает трафик, но RBAC может запретить выполнение операции.

### Как ServiceAccount работает с NetworkPolicy

ServiceAccount сам по себе не влияет на NetworkPolicy. Однако:

1. **Под с ServiceAccount может обращаться к API Server** — NetworkPolicy должен разрешать трафик к API Server (port 6443)
2. **Под с ServiceAccount может иметь доступ к secrets** — NetworkPolicy не влияет на доступ к секретам (это RBAC)
3. **Под без ServiceAccount** — не может обращаться к API Server (нет токена)

### Взаимодействие с DNAT (Service → Pod)

```
Клиент → Service ClusterIP → kube-proxy DNAT → Pod IP
                                                 │
                                                 ├── RBAC: проверяется на API Server (не здесь)
                                                 └── NetworkPolicy: проверяется на Pod IP
```

**Важно:** NetworkPolicy работает на IP пода, а не на ServiceAccount. Под с ServiceAccount `restricted-sa` и под с `admin-sa` обрабатываются NetworkPolicy одинаково — по меткам пода.

## Практические сценарии

### Сценарий 1: Минимальный ServiceAccount + NetworkPolicy

Под, который должен только читать метрики из Prometheus:

```yaml
# 1. ServiceAccount без автоматического монтирования токена
apiVersion: v1
kind: ServiceAccount
metadata:
  name: metrics-reader
  namespace: monitoring
automountServiceAccountToken: false
---
# 2. Role: только read метрик
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: metrics-reader
  namespace: monitoring
rules:
- apiGroups: [""]
  resources: ["services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
---
# 3. RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: metrics-reader
  namespace: monitoring
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: metrics-reader
subjects:
- kind: ServiceAccount
  name: metrics-reader
  namespace: monitoring
---
# 4. NetworkPolicy: разрешить только Prometheus scrape
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-metrics-reader
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: metrics-reader
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Только от Prometheus
  - from:
    - podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9090
  egress:
  # Только DNS и API Server (для token review)
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8  # API Server
    ports:
    - protocol: TCP
      port: 6443
```

### Сценарий 2: Приложение с доступом к API Server

Под, который должен читать информацию о собственных подах (например, для self-registration):

```yaml
# 1. ServiceAccount с ограниченными правами
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-self-reader
  namespace: production
automountServiceAccountToken: true
---
# 2. Role: только чтение подов в своем namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
# 3. RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: app-self-reader
  namespace: production
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: pod-reader
subjects:
- kind: ServiceAccount
  name: app-self-reader
  namespace: production
---
# 4. NetworkPolicy: разрешить доступ к API Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-server-access
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: self-aware-app
  policyTypes:
  - Egress
  egress:
  # DNS
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # API Server
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR API Server
    ports:
    - protocol: TCP
      port: 6443
```

### Сценарий 3: Ошибка — RBAC разрешает, но NetworkPolicy блокирует

**Проблема:** Приложение имеет RBAC-доступ к Secrets, но не может их прочитать из-за NetworkPolicy.

```yaml
# RBAC разрешает чтение Secrets
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]
---
# Но NetworkPolicy блокирует трафик к API Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []  # Всё заблокировано!
```

**Симптом:** Под получает ошибку `unable to connect to API server` или `connection refused`.

**Решение:** Добавить Egress-правило для API Server:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-server
  namespace: production
spec:
  podSelector:
    matchLabels:
      needs-api-access: "true"
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
```

### Сценарий 4: DaemonSet с минимальными привилегиями

node_exporter с минимальными правами и NetworkPolicy:

```yaml
# 1. ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: node-exporter
  namespace: monitoring
automountServiceAccountToken: false
---
# 2. NetworkPolicy
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-node-exporter
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: node-exporter
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Только от Prometheus
  - from:
    - podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 9100
  egress:
  # Только DNS
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  # Нет доступа к API Server (automountServiceAccountToken: false)
```

### Сценарий 5: Multi-tenant ServiceAccount с NetworkPolicy

Каждый тенант имеет свой ServiceAccount с ограничениями:

```yaml
# Tenant A: ServiceAccount + RBAC + NetworkPolicy
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tenant-a-app
  namespace: team-alpha
  labels:
    tenant: team-a
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tenant-a-role
  namespace: team-alpha
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-a-isolation
  namespace: team-alpha
spec:
  podSelector:
    matchLabels:
      tenant: team-a
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Только от других подов tenant-a
  - from:
    - podSelector:
        matchLabels:
          tenant: team-a
  egress:
  # Только DNS и API Server
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
  # Запрет трафика к другим tenant
```

## Дополнительная информация

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Forbidden: forbidden` от API Server | RBAC не разрешает операцию | Настроить Role/ClusterRole |
| `connection refused` к API Server | NetworkPolicy блокирует порт 6443 | Добавить Egress-правило для API Server |
| Токен ServiceAccount не обновляется | Под не может достучаться до API Server | Разрешить Egress к API Server (6443) |
| Secret не монтируется в под | RBAC + NetworkPolicy блокируют | Разрешить чтение Secret (RBAC) и доступ к API Server (NetworkPolicy) |
| Pod не может создать другие поды | RBAC не разрешает create pods | Настроить Role с verbs: ["create"] |

### Чек-лист настройки ServiceAccount + NetworkPolicy

| # | Действие | Приоритет |
| :--- | :--- | :--- |
| 1 | Создать ServiceAccount с `automountServiceAccountToken: false` если токен не нужен | Высокий |
| 2 | Настроить RBAC Role с минимальными правами | Высокий |
| 3 | Добавить NetworkPolicy для разрешения доступа к API Server (если нужен токен) | Высокий |
| 4 | Ограничить egress только до API Server и DNS | Средний |
| 5 | Использовать Token Projection для временных токенов | Средний |
| 6 | Проверить, что RBAC + NetworkPolicy не конфликтуют | Высокий |

### Сравнение: что контролирует каждый слой

| Слой | Что контролирует | Пример |
| :--- | :--- | :--- |
| **RBAC** | Доступ к API Server (ресурсы, действия) | Role: "get pods" в namespace |
| **NetworkPolicy** | Сетевой трафик (IP, порты, протоколы) | Egress: "разрешить 6443 к API Server" |
| **Admission** | Конфигурация пода при создании | PSS: "запретить privileged" |

### См. также

* [NetworkPolicy: Определения](./definitions.md) — базовые термины
* [NetworkPolicy: Логика правил](./rule_logic.md) — аддитивность и селекторы
* [NetworkPolicy: Control Plane](./control_plane_network_policy.md) — изоляция control plane
* [Security Context](../../Security/pod_security_context.md) — PSS/PSA
