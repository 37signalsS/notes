# RBAC-примеры для cert-manager

## Определения

**RBAC (Role-Based Access Control)** — модель управления доступом в Kubernetes, где права привязываются к ролям (Role/ClusterRole), а роли — к субъектам (User, Group, ServiceAccount) через RoleBinding/ClusterRoleBinding.

**Namespace-scoped Role** — роль, действующая в пределах одного namespace. Подходит для изоляции tenant'ов: каждый team имеет доступ только к своим сертификатам.

**ClusterRole** — роль, действующая на весь кластер. Используется для системных компонентов (cert-manager controller, webhook) и для управления кластерными ресурсами (ClusterIssuer, ClusterBundle).

**最小权限 (Least Privilege)** — принцип, при котором субъект получает только те права, которые необходимы для выполнения его задач. Для cert-manager это означает: разработчики не должны иметь доступ к CA-ключам, а platform team — к пользовательским сертификатам.

---

## Основные концепции

### Модель доступа cert-manager

| Роль | Scope | Кому | Права |
| :--- | :--- | :--- | :--- |
| **cert-manager-admin** | Cluster | Platform team | Полное управление всеми ресурсами cert-manager |
| **cert-manager-issuer-admin** | Cluster | Platform team | Управление ClusterIssuer, CA Secrets |
| **cert-manager-tenant** | Namespace | Dev team | Создание/обновление Certificate и Issuer в своем namespace |
| **cert-manager-viewer** | Namespace | Dev team (readonly) | Просмотр Certificate, Secret, Event |
| **cert-manager-ci** | Namespace | CI/CD ServiceAccount | Создание Certificate через API |

### API-группы cert-manager

| API-группа | Ресурсы | Описание |
| :--- | :--- | :--- |
| `cert-manager.io` | `certificates`, `certificaterequests`, `orders`, `challenges` | Основные ресурсы сертификатов |
| `cert-manager.io` | `issuers`, `clusterissuers` | Источники сертификатов |
| `trust.cert-manager.io` | `bundles` | Дистрибуция CA через trust-manager |

---

## Практические сценарии

### Сценарий 1: Read-only просмотрщик (Dev team)

Разработчики могут видеть сертификаты, но не могут создавать или изменять их.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-viewer
  namespace: team-frontend
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "orders", "challenges", "issuers"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
  resourceNames: []  # Оставить пустым для всех secrets в namespace
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-viewer-binding
  namespace: team-frontend
subjects:
- kind: Group
  name: team-frontend-devs
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: cert-manager-viewer
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: Полный доступ tenant'а (Dev team)

Разработчики могут создавать сертификаты и Issuer в своем namespace.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-tenant
  namespace: team-frontend
rules:
# Основные ресурсы cert-manager
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "orders", "challenges"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Issuer (namespace-scoped)
- apiGroups: ["cert-manager.io"]
  resources: ["issuers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Чтение секретов (для проверки статуса)
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
# События (для диагностики)
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-tenant-binding
  namespace: team-frontend
subjects:
- kind: Group
  name: team-frontend-devs
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: cert-manager-tenant
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 3: Ограничение доступа к ClusterIssuer

ClusterIssuer — кластерный ресурс. Для управления им требуется ClusterRole. Ограничьте доступ через отдельную роль.

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

### Сценарий 4: CI/CD ServiceAccount

Для автоматического выпуска сертификатов из CI/CD (ArgoCD, Flux, Jenkins).

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cert-manager-ci
  namespace: cert-manager
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-ci-role
  namespace: cert-manager
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: ["cert-manager.io"]
  resources: ["certificaterequests"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-ci-binding
  namespace: cert-manager
subjects:
- kind: ServiceAccount
  name: cert-manager-ci
  namespace: cert-manager
roleRef:
  kind: Role
  name: cert-manager-ci-role
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 5: Platform team (полный доступ)

Для инженеров платформы, управляющих PKI-инфраструктурой.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: cert-manager-platform-admin
rules:
# Полное управление ресурсами cert-manager
- apiGroups: ["cert-manager.io"]
  resources: ["*"]
  verbs: ["*"]
# Управление trust-manager Bundle
- apiGroups: ["trust.cert-manager.io"]
  resources: ["bundles"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Управление секретами (CA-ключи)
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Управление ServiceAccount (для Vault Auth и т.д.)
- apiGroups: [""]
  resources: ["serviceaccounts"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["serviceaccounts/token"]
  verbs: ["create"]
# Управление NetworkPolicy
- apiGroups: ["networking.k8s.io"]
  resources: ["networkpolicies"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# События
- apiGroups: [""]
  resources: ["events"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: cert-manager-platform-admin-binding
subjects:
- kind: Group
  name: platform-team
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: cert-manager-platform-admin
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 6: Ограничение доступа к CA-секретам

CA-ключи — наиболее чувствительные активы. Ограничьте доступ к ним через `resourceNames`.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-ca-reader
  namespace: cert-manager
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
  # Ограничение только конкретными секретами
  resourceNames:
  - letsencrypt-prod-account-key
  - letsencrypt-staging-account-key
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-ca-reader-binding
  namespace: cert-manager
subjects:
- kind: Group
  name: platform-team
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: cert-manager-ca-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 7: Kyverno-политика для принудительства RBAC

Kyverno может автоматически проверять, что создаваемые Certificate используют разрешенные Issuer.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-issuer-ref
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-issuer-allowed
    match:
      any:
      - resources:
          kinds:
          - cert-manager.io/v1/Certificate
    validate:
      message: "Certificate должен использовать разрешенный ClusterIssuer: letsencrypt-prod, vault-issuer"
      pattern:
        spec:
          issuerRef:
            name: "letsencrypt-prod | vault-issuer"
            kind: ClusterIssuer
```

---

## Дополнительная информация

### Чеклист безопасности RBAC

- [ ] CA-ключи доступны только platform team (cert-manager namespace)
- [ ] Dev team может создавать только namespace-scoped Issuer
- [ ] ClusterIssuer доступен только platform team
- [ ] CI/CD ServiceAccount имеет минимально необходимые права
- [ ] Audit log включен для API-сервера с фокусом на `cert-manager.io`
- [ ] NetworkPolicy ограничивает egress контроллера
- [ ] trust-manager Bundle проверяется platform team перед применением

### Антипаттерны

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| **cluster-admin для dev team** | Полный доступ к CA и кластеру | Namespace-scoped Role |
| **Нет resourceNames для CA Secrets** | Доступ ко всем секретам | Ограничение через resourceNames |
| **Wildcard verbs (`*`)** | Избыточные права | Минимальный набор verbs |
| **Нет audit log** | Невозможность расследования инцидентов | Включить audit для cert-manager.io |

### Смотрите также

- **[Мульти-тенантность cert-manager](./multi_tenancy.md)** — изоляция tenant'ов.
- **[Администрирование cert-manager](./index.md)** — общие принципы RBAC.
- **[Операции cert-manager](./operations.md)** — мониторинг и аудит.
