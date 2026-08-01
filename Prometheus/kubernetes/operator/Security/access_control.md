# Контроль доступа в Prometheus Operator

## Определения

**Контроль доступа** — система мер по ограничению взаимодействия с компонентами мониторинга, включающая сетевую изоляцию (Network Policies) и авторизацию доступа к Kubernetes API (RBAC). Основная цель — минимизация привилегий и защита данных метрик от несанкционированного доступа.

**Admission Webhook Security** — защита портов оператора, через которые Kubernetes API проверяет корректность создаваемых ресурсов (PrometheusRule, ServiceMonitor).

> **Навигация:** [Главная Security](./index.md) | [Управление секретами](./secrets_best_practices.md) | **Надёжность: 10**

---

## Основные концепции

### Сетевые политики (Network Policies)

**NetworkPolicy** используется для изоляции компонентов мониторинга на сетевом уровне (L3/L4). Это критически важно для защиты Prometheus и Alertmanager от несанкционированного доступа.

- **Принцип работы:** По умолчанию в Kubernetes разрешён весь трафик. Применение политики включает режим «запрещено по умолчанию» (default-deny) для выбранных подов.
- **Современные стандарты (2026):** Рекомендуется использование eBPF-плагинов (Cilium, Calico) для глубокой инспекции трафика и защиты от подмены IP.
- **Критические порты:**
    - Prometheus: `9090` (UI/API)
    - Alertmanager: `9093` (API), `9094` (Gossip/HA)
    - Operator Webhook: `9443` (Validation/Mutation)
    - Thanos Sidecar: `10901` (gRPC)

### RBAC (Role-Based Access Control)

**RBAC** управляет правами доступа Prometheus к Kubernetes API для обнаружения целей (Service Discovery) и управления ресурсами.

- **Service Discovery:** С 2025 года обязательным является использование `EndpointSlice` вместо устаревшего `Endpoints` для снижения нагрузки на Control Plane.
- **Принцип наименьших привилегий:** Prometheus требует права на чтение (`get`, `list`, `watch`) ресурсов во всех отслеживаемых неймспейсах.
- **Управление CRD:** Оператор должен обладать правами на управление новыми ресурсами, такими как `ScrapeConfig` и `ThanosRuler`.

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
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - port: 9090
          protocol: TCP
```

#### Защита Admission Webhook (Operator)

Разрешает Kubernetes API-серверу доступ к вебхуку оператора для валидации ресурсов.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: operator-webhook-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus-operator
  ingress:
    - from:
        - ipBlock:
            cidr: 0.0.0.0/0 # В реальных средах ограничить CIDR мастеров
      ports:
        - port: 9443
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

Необходим для работы Service Discovery и сбора метрик.

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
  - apiGroups: ["discovery.k8s.io"] # Современный механизм SD
    resources:
      - endpointslices
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources:
      - ingresses
    verbs: ["get", "list", "watch"]
  - apiGroups: ["monitoring.coreos.com"] # Поддержка ScrapeConfig
    resources:
      - scrapeconfigs
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

Контроль доступа является фундаментом безопасности мониторинга. Рекомендуется регулярно проводить аудит прав ServiceAccount.

- **[Безопасность (Главная)](./index.md)** — обзорная страница.
- **[Управление секретами](./secrets_best_practices.md)** — ротация и защита учетных данных.
- **[NetworkPolicy: Обзор](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — глубокое погружение в сетевую изоляцию.
- **[RBAC: Обзор](../../../Kubernetes/Security/rbac/rbac_overview.md)** — принципы авторизации в K8s.
- **[Troubleshooting](../troubleshooting.md)** — решение проблем с правами и сетью.
