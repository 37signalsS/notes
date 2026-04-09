# Контроль доступа в Prometheus Operator

## Определения

**Контроль доступа** — ограничение доступа к компонентам Prometheus через Network Policies (L3/L4 фильтрация) и RBAC (авторизация Kubernetes API).

> **Навигация:** [Главная Security](./index.md) | [Секреты](./secrets_best_practices.md)

---

## Basic Concepts

### Network Policies

**NetworkPolicy** — ресурс Kubernetes для декларативного управления правилами доступа к сети на уровне L3/L4. Работает только при поддержке CNI-плагином (Calico, Cilium, Weave Net). Flannel **не поддерживает** NetworkPolicy.

**Принцип работы:**
- Если для пода **не создано ни одной** NetworkPolicy — весь трафик разрешён
- При применении **хотя бы одной** NetworkPolicy — включается режим default-deny для указанного типа трафика (Ingress/Egress)
- Правила обрабатываются аддитивно: если трафик разрешён хотя бы одним правилом — он проходит

**Основные компоненты spec:**
- `podSelector` — выборка подов, к которым применяется политика
- `policyTypes` — тип трафика (`Ingress`, `Egress`)
- `ingress`/`egress` — правила разрешения входящего/исходящего трафика

> **Подробно:** [NetworkPolicy Definitions](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)

### RBAC (Role-Based Access Control)

**RBAC** — встроенный механизм авторизации Kubernetes, контролирующий доступ к API-ресурсам через роли и привязки.

**Основные объекты:**
- **ServiceAccount** — идентификатор для процессов в Pod
- **Role/ClusterRole** — набор правил (ресурсы + глаголы)
- **RoleBinding/ClusterRoleBinding** — привязка субъекта к роли

**Принцип наименьших привилегий:** Prometheus требует только `get`, `list`, `watch` для чтения метрик из Kubernetes API. Запись не требуется.

> **Подробно:** [RBAC Overview](../../../Kubernetes/Security/rbac/rbac_overview.md)

---

## Practical Scenarios

### Network Policies

#### Ограничение доступа к Prometheus

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
        - podSelector:
            matchLabels:
              app: grafana
      ports:
        - port: 9090
          protocol: TCP
```

---

#### Ограничение доступа к Alertmanager

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: alertmanager-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
```

---

### RBAC

#### ServiceAccount для Prometheus

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
```

---

#### ClusterRole для доступа к Kubernetes API

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus
rules:
  - apiGroups: [""]
    resources:
      - nodes
      - nodes/metrics
      - services
      - endpoints
      - pods
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
```

---

#### ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: prometheus
subjects:
  - kind: ServiceAccount
    name: prometheus
    namespace: monitoring
```

---

## Additional Information

> **См. также:** [High Availability](../high_availability.md) — HA конфигурация; [Prometheus CRD](../crd/prometheus.md) — описание Prometheus CRD.
