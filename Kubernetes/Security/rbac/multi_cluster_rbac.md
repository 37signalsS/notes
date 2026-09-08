# RBAC в мультикластерных средах

## Определения

**Multi-cluster RBAC** — совокупность подходов к управлению доступом в средах, где используются два или более кластера Kubernetes. Включает синхронизацию ролей между кластерами, federated trust, управление kubeconfig с несколькими контекстами и изоляцию租ant.

**Основные модели:**

- **Centralized Management (Глобальное управление):** Единый инструмент (ArgoCD, Flux, Terraform) управляет RBAC во всех кластерах из одного места.
- **Federated Trust (Доверие между кластерами):** Кластеры доверяют аутентификации друг друга (например, через общий OIDC-провайдер).
- **Cluster-Scoped Isolation (Изоляция):** Каждый кластер имеет свою независимую RBAC-конфигурацию. Нет общих ролей.
- **Hub-and-Spoke (Центр-спутники):** Один «hub» кластер управляет «spoke» кластерами через имперсонацию или代理.

**Зачем это нужно в продакшене:**
- DR (Disaster Recovery): идентичные RBAC в primary и standby кластерах
- Multi-region: один и тот же набор ролей для DevOps-команд в разных регионах
- Compliance: единая политика доступа для аудита
- Development → Staging → Production: воспроизводимость окружений

---

## Основные концепции

### kubeconfig с несколькими кластерами

Каждый кластер — отдельный контекст в kubeconfig:

```yaml
# ~/.kube/config
apiVersion: v1
kind: Config
clusters:
- name: cluster-prod
  cluster:
    server: https://prod-api.example.com:6443
    certificate-authority: /etc/pki/prod-ca.crt
- name: cluster-staging
  cluster:
    server: https://staging-api.example.com:6443
    certificate-authority: /etc/pki/staging-ca.crt
- name: cluster-dev
  cluster:
    server: https://dev-api.example.com:6443
    certificate-authority: /etc/pki/dev-ca.crt

users:
- name: alice-prod
  user:
    client-certificate: /home/alice/certs/prod.crt
    client-key: /home/alice/certs/prod.key
- name: alice-staging
  user:
    client-certificate: /home/alice/certs/staging.crt
    client-key: /home/alice/certs/staging.key
- name: alice-dev
  user:
    client-certificate: /home/alice/certs/dev.crt
    client-key: /home/alice/certs/dev.key

contexts:
- name: prod
  context:
    cluster: cluster-prod
    user: alice-prod
    namespace: production
- name: staging
  context:
    cluster: cluster-staging
    user: alice-staging
    namespace: staging
- name: dev
  context:
    cluster: cluster-dev
    user: alice-dev
    namespace: development

current-context: prod
```

**Переключение между кластерами:**

```bash
# Использование --context для одноразовых команд
kubectl --context=staging get pods -n monitoring

# Установка контекста по умолчанию
kubectl config use-context prod

# Просмотр всех доступных контекстов
kubectl config get-contexts

# Шпаргалка: проверка RBAC во всех кластерах сразу
for ctx in prod staging dev; do
  echo "=== $ctx ==="
  kubectl --context=$ctx auth can-i --list --as=alice@example.com -n production 2>/dev/null | head -5
done
```

### Единый OIDC-провайдер для нескольких кластеров

Паттерн: все кластеры используют один OIDC-провайдер (Dex, Keycloak, Okta), что обеспечивает единую точку управления аутентификацией:

```text
                        ┌─────────────────┐
                        │  OIDC Provider  │
                        │  (Keycloak)     │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
     ┌────────▼────────┐ ┌──────▼───────┐ ┌────────▼────────┐
     │  Cluster Prod   │ │ Cluster Stage│ │  Cluster Dev    │
     │  --oidc-*       │ │  --oidc-*    │ │  --oidc-*       │
     └─────────────────┘ └──────────────┘ └─────────────────┘
```

**Преимущества:**
- Единый выход: отключение пользователя в IdP → потеря доступа ко всем кластерам
- RBAC привязан к OIDC-группам: `platform-admins` → `cluster-admin` в каждом кластере
- Аудит: все логи аутентификации в одном месте

**Флаги API-сервера (одинаковые для всех кластеров):**

```yaml
# Аргументы kube-apiserver (все кластеры)
- --oidc-issuer-url=https://keycloak.example.com/realms/kubernetes
- --oidc-client-id=kubernetes
- --oidc-username-claim=email
- --oidc-groups-claim=groups
- --oidc-ca-file=/etc/kubernetes/pki/oidc-ca.crt
```

### RBAC-синхронизация через GitOps

Паттерн: все манифесты RBAC хранятся в Git и применяются во все кластеры через ArgoCD или Flux:

```yaml
# ArgoCD ApplicationSet для RBAC во всех кластерах
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: rbac-sync
  namespace: argocd
spec:
  generators:
  - clusters:
      selector:
        matchLabels:
          purpose: production
  template:
    metadata:
      name: 'rbac-{{name}}'
    spec:
      project: default
      source:
        repoURL: https://git.internal.company.com/platform/rbac.git
        targetRevision: main
        path: overlays/{{metadata.labels.region}}
      destination:
        server: '{{server}}'
        namespace: kube-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

**Структура репозитория:**

```
rbac-repo/
├── base/
│   ├── cluster-admin-binding.yaml
│   ├── platform-team-role.yaml
│   ├── monitoring-role.yaml
│   └── ci-cd-role.yaml
├── overlays/
│   ├── production/
│   │   ├── kustomization.yaml  # Добавляет production-specific bindings
│   │   └── extra-secrets-access.yaml
│   ├── staging/
│   │   └── kustomization.yaml  # Менее строгие правила
│   └── dev/
│       └── kustomization.yaml  # Расширенные права для dev
└── apps/
    └── argocd-applicationset.yaml
```

### Multi-tenancy через namespace и RBAC

Паттерн: каждый «tenant» (команда/проект) изолирован в namespace-ах с уникальным RBAC:

```yaml
# Шаблон: Tenant Team A (namespace: team-a-*)
---
apiVersion: v1
kind: Namespace
metadata:
  name: team-a-production
  labels:
    tenant: team-a
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: team-a-admin
  namespace: team-a-production
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-a-admin-binding
  namespace: team-a-production
subjects:
- kind: Group
  name: team-a-admins  # OIDC-группа
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: team-a-admin
  namespace: team-a-production
roleRef:
  kind: ClusterRole
  name: admin
  apiGroup: rbac.authorization.k8s.io
---
# Ограничение: команда A не может создавать Namespace
# (через OPA/Kyverno или кастомную валидацию)
```

---

## Практические сценарии

### Проверка RBAC во всех кластерах

```bash
#!/bin/bash
# check_rbac_all_clusters.sh
CLUSTERS=("prod" "staging" "dev")
SUBJECT="alice@example.com"

for CLUSTER in "${CLUSTERS[@]}"; do
  echo "============================================"
  echo "CLUSTER: $CLUSTER"
  echo "============================================"

  # Проверка cluster-admin привязок
  echo "--- Cluster Admin Bindings ---"
  kubectl --context="$CLUSTER" get clusterrolebindings -o json | \
    jq -r --arg sub "$SUBJECT" \
    '.items[] | select(.subjects[]? | .name==$sub) |
     "  \(.metadata.name) -> \(.roleRef.name)"' 2>/dev/null

  # Проверка RoleBinding в key namespaces
  for NS in production staging monitoring; do
    echo "--- RoleBindings in $NS ---"
    kubectl --context="$CLUSTER" get rolebindings -n "$NS" -o json | \
      jq -r --arg sub "$SUBJECT" \
      '.items[] | select(.subjects[]? | .name==$sub) |
       "  \(.metadata.name) -> \(.roleRef.name)"' 2>/dev/null
  done

  # Проверка конкретных прав
  echo "--- Can-I Check ---"
  kubectl --context="$CLUSTER" auth can-i list secrets \
    --as="$SUBJECT" -n production 2>/dev/null && \
    echo "  [DANGER] $SUBJECT can list secrets in production" || \
    echo "  [OK] $SUBJECT cannot list secrets in production"
  echo ""
done
```

### Имперсонация для кросс-кластерного доступа

Паттерн: CI/CD-система работает в «ops» кластере, но деплоит в несколько целевых кластеров:

```yaml
# 1. ServiceAccount в ops-кластере для ArgoCD/Flux
apiVersion: v1
kind: ServiceAccount
metadata:
  name: multi-cluster-deployer
  namespace: argocd
---
# 2. ClusterRole для имперсонации
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: impersonate-deployers
rules:
- apiGroups: [""]
  resources: ["users", "serviceaccounts"]
  verbs: ["impersonate"]
---
# 3. ClusterRoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: deployer-impersonation
subjects:
- kind: ServiceAccount
  name: multi-cluster-deployer
  namespace: argocd
roleRef:
  kind: ClusterRole
  name: impersonate-deployers
  apiGroup: rbac.authorization.k8s.io
```

### Диагностика кросс-кластерных проблем

```bash
# 1. Проверка: какой kubeconfig используется?
kubectl config current-context
# → prod

# 2. Проверка: доступен ли целевой кластер?
kubectl cluster-info
# → Kubernetes control plane is running at https://prod-api.example.com:6443

# 3. Проверка RBAC в целевом кластере
kubectl auth can-i --list --as=alice@example.com -n production | grep -E "secrets|deployments"

# 4. Проверка: совпадают ли OIDC-группы между кластерами?
# В каждом кластере:
kubectl auth can-i --list --as=alice@example.com --as-group=platform-admins -n kube-system | head -5

# 5. Сравнение прав в разных кластерах
for ctx in prod staging dev; do
  echo "=== $ctx ==="
  kubectl --context=$ctx auth can-i list secrets --as=alice@example.com -n production
done
```

---

## Дополнительная информация

### Инструменты

| Инструмент | Назначение |
|-----------|-----------|
| `kubectx` | Быстрое переключение контекстов |
| `kubens` | Быстрое переключение namespace |
| `kubecm` | Управление kubeconfig (слияние, проверка) |
| `argocd` | GitOps для multi-cluster RBAC |
| `terraform` | Declarative management RBAC через kubernetes provider |

### Ограничения

- **Нет федерации RBAC:** Kubernetes не имеет встроенного механизма синхронизации RoleBinding между кластерами. Используйте GitOps или кастомные контроллеры.
- **OIDC-группы не кэшируются:** API-сервер запрашивает OIDC-провайдер при каждой аутентификации (с кэшированием). Изменения групп生效 с задержкой.
- **Certificate-based auth не масштабируется:** При большом числе пользователей лучше использовать OIDC вместо ручного управления сертификатами.

### Best Practices

1. **Единый OIDC-провайдер:** Все кластеры аутентифицируют через один IdP.
2. **RBAC как код:** Храните манифесты в Git, применяйте через GitOps.
3. **Namespace-scoped привязки:** Предпочитайте RoleBinding + ClusterRole (ограниченная область) вместо ClusterRoleBinding.
4. **Регулярный аудит:** Проверяйте RBAC во всех кластерах через скрипты.
5. **Изоляция tenants:** Каждая команда — уникальный namespace + RoleBinding.

### Связанные темы

- **[Обзор RBAC](./rbac_overview.md)** — основы управления доступом
- **[Субъекты доступа](./subjects.md)** — типы субъектов
- **[ArgoCD RBAC](../../../GitOps/ArgoCD/argocd_rbac_deep.md)** — RBAC для multi-cluster GitOps
- **[Multi-tenancy](../../Concepts/multi-tenancy.md)** — изоляция租ant в кластере
