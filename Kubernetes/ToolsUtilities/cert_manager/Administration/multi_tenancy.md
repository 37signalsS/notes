# Мульти-tenant cert-manager

## Определения

**Multi-tenancy в cert-manager** — архитектурный подход, при котором несколько команд (tenant'ов) совместно используют один экземпляр cert-manager, но изолированы друг от друга на уровне RBAC, namespace и политик. Каждый tenant имеет доступ только к своим сертификатам и Issuer.

**Tenant (Тенант)** — логическая единица изоляции: команда, проект или бизнес-единица, которой выделены собственные namespace и ресурсы cert-manager. Tenant не может влиять на сертификаты других tenant'ов.

**Namespace Scoping (Область видимости namespace)** — ограничение доступа tenant'а к ресурсам cert-manager в пределах одного namespace. Issuer — namespace-scoped, ClusterIssuer — cluster-scoped (требует осторожности).

**Issuer per Tenant** — паттерн, при котором каждому tenant'у выделяется собственный Issuer (namespace-scoped) с уникальными учетными данными CA. Предотвращает конфликт rate limits и обеспечивает аудит.

---

## Основные концепции

### Модели изоляции

| Модель | Описание | Изоляция | Сложность |
| :--- | :--- | :--- | :--- |
| **Shared ClusterIssuer** | Все tenant'ы используют один ClusterIssuer | Низкая (общий rate limit, общий CA) | Низкая |
| **Issuer per Tenant** | Каждый tenant имеет свой Issuer в namespace | Средняя | Средняя |
| **cert-manager per Tenant** | Отдельный экземпляр cert-manager на tenant | Высокая | Высокая |
| **vCluster + cert-manager** | Отдельный виртуальный кластер на tenant | Максимальная | Высокая |

### Рекомендованная модель: Issuer per Tenant

```
┌─────────────────────────────────────────────────────────────┐
│                      Kubernetes Cluster                      │
│                                                              │
│  ┌─────────────────────┐  ┌─────────────────────┐           │
│  │   Tenant: Frontend   │  │   Tenant: Backend    │           │
│  │   namespace: prod-fe │  │   namespace: prod-be  │           │
│  │                      │  │                      │           │
│  │  ┌──────────────┐   │  │  ┌──────────────┐   │           │
│  │  │ Issuer       │   │  │  │ Issuer       │   │           │
│  │  │ (LE staging) │   │  │  │ (LE prod)    │   │           │
│  │  └──────────────┘   │  │  └──────────────┘   │           │
│  │                      │  │                      │           │
│  │  RBAC: edit/view     │  │  RBAC: edit/view     │           │
│  └─────────────────────┘  └─────────────────────┘           │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │   ClusterIssuer (только для admin'ов)                 │   │
│  │   namespace: cert-manager                             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### RBAC для мульти-тенантности

| Роль | Scope | Права | Кто |
| :--- | :--- | :--- | :--- |
| **cert-manager-admin** | Cluster | Управление ClusterIssuer, CA, webhook | Platform team |
| **cert-manager-tenant** | Namespace | Создание/обновление Certificate, Issuer | Dev team |
| **cert-manager-viewer** | Namespace | Просмотр Certificate, Secret | Dev team (readonly) |

---

## Практические сценарии

### Сценарий 1: Namespace-scoped RBAC для tenant'а

```yaml
# Role: tenant peut créer des certificats dans son namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-tenant
  namespace: team-frontend
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "orders", "challenges"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["cert-manager.io"]
  resources: ["issuers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "list", "watch"]
---
# RoleBinding: привязка к ServiceAccount команды
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-tenant-binding
  namespace: team-frontend
subjects:
- kind: ServiceAccount
  name: cert-manager-sa
  namespace: team-frontend
roleRef:
  kind: Role
  name: cert-manager-tenant
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: Issuer per Tenant

```yaml
# Issuer для Frontend команды (Staging для разработки)
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: letsencrypt-staging
  namespace: team-frontend
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: frontend-team@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-frontend-token
            key: api-token
---
# Issuer для Backend команды (Production)
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: letsencrypt-prod
  namespace: team-backend
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: backend-team@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        route53:
          accessKeyIDSecretRef:
            name: route53-credentials
            key: access-key-id
          secretAccessKeySecretRef:
            name: route53-credentials
            key: secret-access-key
          region: us-east-1
```

### Сценарий 3: NetworkPolicy для изоляции tenant'ов

```yaml
# Запрет трафика между tenant namespaces
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-frontend-isolation
  namespace: team-frontend
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить трафик только из ingress-controller
  - from:
    - namespaceSelector:
        matchLabels:
          app.kubernetes.io/name: ingress-nginx
  egress:
  # Разрешить DNS
  - to:
    - namespaceSelector: {}
    ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
  # Разрешить трафик к backend
  - to:
    - namespaceSelector:
        matchLabels:
          team: backend
    ports:
    - port: 8080
      protocol: TCP
```

### Сценарий 4: Ограничение ClusterIssuer через RBAC

```yaml
# Только platform team может использовать ClusterIssuer
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cert-manager-cluster-issuer-user
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["clusterissuers"]
  verbs: ["get", "list", "watch"]
# Примечание: создание ClusterIssuer — только для admin'ов
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cert-manager-cluster-issuer-binding
subjects:
- kind: Group
  name: platform-team
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: cert-manager-cluster-issuer-user
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 5: Ограничение алгоритмов ключей для tenant'а

```yaml
# Kyverno: запрет RSA для tenant frontend
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-ecdsa-frontend
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-ecdsa-frontend
    match:
      any:
      - resources:
          kinds:
          - cert-manager.io/v1/Certificate
          namespaces:
          - team-frontend
    validate:
      message: "Tenant frontend обязан использовать ECDSA P-256"
      pattern:
        spec:
          privateKey:
            algorithm: ECDSA
            size: 256
```

---

## Дополнительная информация

### Антипаттерны

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| **Один ClusterIssuer на всех** | Общий rate limit, невозможность аудита | Issuer per Tenant |
| **cert-manager-admin для всех** | Полный доступ к CA, возможность создания ClusterIssuer | Namespace-scoped Role |
| **Нет NetworkPolicy** | Tenant может читать Secretы других tenant'ов | Default Deny + Allow |
| **Wildcard-сертификаты для tenant'ов** | Один просроченный сертификат затрагивает все сервисы | Отдельные Certificate |

### Best practices

1. **Issuer per Namespace:** Каждому tenant'у — свой Issuer с уникальными учетными данными
2. **RBAC最小权限:** Tenant может создавать только Certificate и Issuer в своем namespace
3. **NetworkPolicy:** Изолируйте tenant namespaces друг от друга
4. **Аудит:** Включите audit log для API-сервера с фокусом на cert-manager ресурсы
5. **Rate Limits:** Используйте разные ACME-аккаунты для разных tenant'ов
6. **Секреты:** Храните ACME-ключи в namespace tenant'а, а не в cert-manager

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — HA, RBAC и Garbage Collection.
- **[Cert-manager: Операции](./operations.md)** — мониторинг и алертинг.
- **[NetworkPolicy: Multi-tenancy](../../../../Kubernetes/Networking/Network/NetworkPolicy/multi_tenancy.md)** — сетевая изоляция tenant'ов.
