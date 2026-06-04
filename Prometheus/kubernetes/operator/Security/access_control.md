# Контроль доступа в Prometheus Operator

## Определения

**Контроль доступа** — комплекс мер по ограничению доступа к компонентам Prometheus Operator с использованием сетевой фильтрации (Network Policies) и механизмов авторизации Kubernetes API (RBAC).

> **Навигация:** [Главная Security](./index.md) | [Секреты](./secrets_best_practices.md)

---

## Основные концепции

### Сетевые политики (Network Policies)

**NetworkPolicy** используется для изоляции компонентов мониторинга на сетевом уровне (L3/L4). Это критически важно для защиты Prometheus и Alertmanager от несанкционированного доступа из других неймспейсов.

- **Принцип работы:** По умолчанию в Kubernetes разрешён весь трафик. Применение политики включает режим "запрещено по умолчанию" (default-deny) для выбранных подов.
- **Требования:** Необходим CNI-плагин с поддержкой политик (Calico, Cilium). Flannel не поддерживает этот механизм.

> **Подробно:** [Определения и принципы NetworkPolicy](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)

### RBAC (Role-Based Access Control)

**RBAC** управляет правами доступа Prometheus к Kubernetes API для обнаружения целей (Service Discovery) и сбора метрик.

- **ServiceAccount:** Идентифицирует под Prometheus в кластере.
- **ClusterRole:** Определяет права на чтение ресурсов (`nodes`, `pods`, `services`) во всём кластере.
- **Принцип наименьших привилегий:** Prometheus требует только права на чтение (`get`, `list`, `watch`). Права на запись или изменение ресурсов не требуются.

> **Подробно:** [Обзор RBAC в Kubernetes](../../../Kubernetes/Security/rbac/rbac_overview.md)

---

## Практические сценарии

### Сетевые политики (Network Policies)

#### Ограничение доступа к Prometheus

Разрешает доступ к порту 9090 только для Grafana и компонентов внутри неймспейса `monitoring`.

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

#### Ограничение доступа к Alertmanager

Разрешает входящий трафик на порт 9093 только от Prometheus.

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

#### ClusterRole для доступа к Kubernetes API

Необходим для работы Service Discovery.

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

#### ClusterRoleBinding

Связывает ServiceAccount с созданной ролью.

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

## Дополнительная информация

> **См. также:**
>
> - [High Availability](../high_availability.md) — конфигурация отказоустойчивости
> - [Prometheus CRD](../crd/prometheus.md) — описание ресурсов Prometheus
> - [NetworkPolicy Best Practices](../../../Kubernetes/Networking/Network/NetworkPolicy/best_practices.md)
