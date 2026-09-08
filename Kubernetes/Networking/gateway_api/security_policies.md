# Безопасность Gateway API — политики и контроль доступа

## Определения

**NetworkPolicy** — Kubernetes ресурс, контролирующий сетевой трафик на уровне подов и namespace. В контексте Gateway API используется для защиты Data Plane (Envoy/NGINX/Traefik) от несанкционированного доступа.

**RBAC (Role-Based Access Control)** — механизм контроля доступа Kubernetes, определяющий кто может выполнять какие действия с какими ресурсами. Для Gateway API критичен контроль создания/изменения Gateway, HTTPRoute, ReferenceGrant.

**Kyverno** — Kubernetes-политика как код (Policy as Code), использующая CEL (Common Expression Language) для валидации и мутации ресурсов. Поддерживает валидацию Gateway API CRD.

**OPA Gatekeeper** — Open Policy Agent для Kubernetes, использующий Rego для описания политик. Контролирует admission Gateway API ресурсов.

**Pod Security Standards** — Kubernetes стандарты безопасности подов (Privileged, Baseline, Restricted). Определяют какие安全 характеристики разрешены в namespace.

## Предварительные требования

| Компонент | Минимальная версия | Проверка |
|:---|:---|:---|
| Kubernetes | 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ | `kubectl get crd gateways.gateway.networking.k8s.io` |
| Kyverno | 1.10+ (опционально) | `kubectl get pods -n kyverno` |
| OPA Gatekeeper | 3.14+ (опционально) | `kubectl get pods -n gatekeeper-system` |

## Базовые концепции

### Многоуровневая модель безопасности Gateway API

```
Уровень 1: Admission Control (Kyverno/OPA Gatekeeper)
  ├── Валидация синтаксиса ресурсов
  ├── Проверка политик безопасности
  └── Мутация (добавление лейблов, аннотаций)

Уровень 2: RBAC (Kubernetes)
  ├── Кто может создавать Gateway/HTTPRoute
  ├── Кто может читать ReferenceGrant
  └── Кто может изменять GatewayClass

Уровень 3: NetworkPolicy (Kubernetes/Cilium)
  ├── Защита Data Plane от несанкционированного доступа
  ├── Ограничение трафика между namespace
  └── Изоляция Control Plane

Уровень 4: Application Level (SecurityPolicy Envoy Gateway)
  ├── JWT аутентификация
  ├── CORS политики
  └── Rate Limiting
```

## Практические сценарии

### NetworkPolicy для защиты Envoy Gateway Data Plane

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: envoy-gateway-dataplane
  namespace: envoy-gateway-system
spec:
  podSelector:
    matchLabels:
      gateway.envoyproxy.io/owning-gateway-name: ""
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить внешний трафик на порты HTTP/HTTPS
  - from: []  # Любой источник (внешний LB)
    ports:
    - port: 80
      protocol: TCP
    - port: 443
      protocol: TCP
  # Разрешить трафик от Prometheus для метрик
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 19000  # Envoy admin interface
      protocol: TCP
  # Разрешить трафик от Control Plane
  - from:
    - podSelector:
        matchLabels:
          control-plane: envoy-gateway-controller
    ports:
    - port: 18000  # xDS port
      protocol: TCP
  egress:
  # Разрешить DNS
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Разрешить трафик к бэкендам
  - to:
    - namespaceSelector: {}
    ports:
    - port: 80
      protocol: TCP
    - port: 443
      protocol: TCP
    - port: 8080
      protocol: TCP
```

### NetworkPolicy для защиты NGINX Gateway Fabric

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: nginx-gateway-fabric-policy
  namespace: nginx-gateway
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: nginx-gateway-fabric
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from: []
    ports:
    - port: 80
    - port: 443
  # Prometheus метрики
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 9113
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
  - to:
    - namespaceSelector: {}
    ports:
    - port: 80
    - port: 443
    - port: 8080
```

### RBAC: Ограничение управления Gateway API ресурсами

```yaml
# Role для операторов (только чтение Gateway, изменение HTTPRoute)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: gateway-api-operator
  namespace: production
rules:
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["gateways", "gatewayclasses"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["httproutes", "grpcroutes"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["referencegrants"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

---
# RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gateway-api-operator-binding
  namespace: production
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: gateway-api-operator
subjects:
- kind: Group
  name: dev-team
  apiGroup: rbac.authorization.k8s.io

---

# ClusterRole для администраторов инфраструктуры
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gateway-api-admin
rules:
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["gatewayclasses"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["gateways"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["httproutes", "grpcroutes", "tlsroutes", "tcproutes", "udproutes"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["gateway.networking.k8s.io"]
  resources: ["referencegrants", "backendtlspolicies"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

---

# ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gateway-api-admin-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gateway-api-admin
subjects:
- kind: Group
  name: infra-admins
  apiGroup: rbac.authorization.k8s.io
```

### Kyverno: Валидация Gateway API ресурсов

```yaml
# Политика 1: Запрет wildcard в allowedRoutes
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-wildcard-routes
  annotations:
    policies.kyverno.io/title: Disallow Wildcard Routes
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: check-allowed-routes
    match:
      any:
      - resources:
          kinds:
          - Gateway
    validate:
      message: "Wildcard в allowedRoutes запрещён. Используйте Selector с конкретными namespace."
      pattern:
        spec:
          listeners:
          - allowedRoutes:
              namespaces:
                from: "!All"

---
# Политика 2: Обязательный TLS на Gateway
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-gateway-tls
  annotations:
    policies.kyverno.io/title: Require Gateway TLS
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: check-gateway-tls
    match:
      any:
      - resources:
          kinds:
          - Gateway
    validate:
      message: "Gateway должен иметь хотя бы один listener с TLS Terminate или Passthrough."
      pattern:
        spec:
          listeners:
          - tls:
              mode: "Terminate | Passthrough"

---
# Политика 3: Ограничение hostnames в HTTPRoute
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-httproute-hostnames
  annotations:
    policies.kyverno.io/title: Restrict HTTPRoute Hostnames
    policies.kyverno.io/severity: medium
spec:
  validationFailureAction: Audit
  background: true
  rules:
  - name: check-hostnames
    match:
      any:
      - resources:
          kinds:
          - HTTPRoute
    validate:
      message: "HTTPRoute не должен использовать wildcard-хосты (*.example.com)."
      pattern:
        spec:
          hostnames:
          - "!*.example.com"

---
# Политика 4: Обязательный ReferenceGrant для кросс-namespace
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-reference-grant
  annotations:
    policies.kyverno.io/title: Require ReferenceGrant
    policies.kyverno.io/severity: high
spec:
  validationFailureAction: Audit
  background: true
  rules:
  - name: check-cross-namespace-ref
    match:
      any:
      - resources:
          kinds:
          - HTTPRoute
    validate:
      message: "HTTPRoute с cross-namespace backendRefs требует ReferenceGrant."
      pattern:
        spec:
          rules:
          - backendRefs:
            - namespace: "!*"
```

### OPA Gatekeeper: Валидация Gateway API

```yaml
# ConstraintTemplate для проверки TLS в Gateway
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sgatewayrequiretls
spec:
  crd:
    spec:
      names:
        kind: K8sGatewayRequireTLS
      validation:
        openAPIV3Schema:
          type: object
          properties:
            exemptNamespaces:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8sgatewayrequiretls

        violation[{"msg": msg}] {
          input.review.kind.kind == "Gateway"
          input.review.object.spec.listeners[_].tls == null
          not input.review.object.metadata.namespace in input.parameters.exemptNamespaces
          msg := sprintf("Gateway %v/%v не имеет TLS на listener %v", [
            input.review.object.metadata.namespace,
            input.review.object.metadata.name,
            input.review.object.spec.listeners[_].name
          ])
        }

---
# Constraint для применения политики
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sGatewayRequireTLS
metadata:
  name: require-gateway-tls
spec:
  enforcementAction: deny
  match:
    kinds:
    - apiGroups: ["gateway.networking.k8s.io"]
      kinds: ["Gateway"]
    namespaces:
    - production
    - staging
  parameters:
    exemptNamespaces:
    - kube-system
    - monitoring
```

### Pod Security Standards для namespace Gateway API

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: envoy-gateway-system
  labels:
    # Baseline: запрещает привилегированные поды
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

## Troubleshooting

### Типичные ошибки безопасности

| Симптом | Причина | Решение |
|:---|:---|:---|
| Kyverno блокирует создание Gateway | Политика слишком строгая | Проверить `validateFailureAction`, временно переключить на `Audit` |
| OPA Gatekeeper не блочит ресурсы | Constraint не привязан к namespace | Проверить `match.namespaces` в Constraint |
| NetworkPolicy блокирует трафик к бэкендам | Нет egress правила для портов бэкендов | Добавить egress rule с нужными портами |
| RBAC не позволяет создавать HTTPRoute | Нет прав `create` на `httproutes` | Проверить ClusterRole/Role |

### Диагностика политик безопасности

```bash
# Проверка Kyverno политик
kubectl get clusterpolicy -o wide
# → Все политики должны быть в состоянии Ready

# Проверка OPA Gatekeeper
kubectl get constrainttemplates -o wide
kubectl get constraints -o wide

# Проверка NetworkPolicy
kubectl get networkpolicy -A

# Проверка RBAC
kubectl auth can-i create httproute --namespace production --as system:serviceaccount:production:dev-sa
# → yes или no
```

## Best Practices

### Рекомендуемый набор политик

1. **NetworkPolicy для Data Plane:**
   - Входящий трафик только на порты 80/443
   - Трафик от Prometheus на порт метрик
   - DNS и трафик к бэкендам

2. **RBAC:**
   - Разделение ролей: admin (Gateway), operator (HTTPRoute), developer (только свои namespace)
   - Namespace-scoped Roles вместо ClusterRoles где возможно

3. **Admission Control:**
   - Kyverno/OPA для валидации TLS, запрета wildcard
   - Audit mode перед Enforce для тестирования

4. **Pod Security:**
   - Baseline для namespace контроллеров
   - Restricted для namespace приложений

### Аудит и compliance

1. **Регулярная проверка:**
   ```bash
   # Проверка что все Gateway имеют TLS
   kubectl get gateway -A -o json | jq '.items[] | select(.spec.listeners[].tls == null) | .metadata.name'

   # Проверка ReferenceGrant
   kubectl get httproute -A -o json | jq '.items[].spec.rules[].backendRefs[] | select(.namespace != null)'

   # Проверка NetworkPolicy
   kubectl get networkpolicy -A -o wide
   ```

2. **Логирование изменений:**
   - Kubernetes Audit Log для Gateway API ресурсов
   - GitOps история коммитов

## Дополнительная информация

### Связанные ресурсы

- [Определения Gateway API](./definitions.md) — общие концепции безопасности
- [Провайдер-специфичная конфигурация](./provider_specific_config.md) — SecurityPolicy, BackendTLSPolicy
- [Высокая доступность](./high_availability.md) — HA для защищенных конфигураций
- [GitOps и CI/CD](./gitops_cicd.md) — валидация политик в CI

**Родительская тема:** [Gateway API](./definitions.md)
