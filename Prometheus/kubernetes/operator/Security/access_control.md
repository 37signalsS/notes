# Контроль доступа в Prometheus Operator

## Определения

**Контроль доступа** — комплексная система мер по ограничению взаимодействия с компонентами мониторинга, включающая сетевую изоляцию (Network Policies), авторизацию доступа к Kubernetes API (RBAC) и валидацию ресурсов через Admission Webhooks. Основная цель — реализация принципа минимальных привилегий и защита инфраструктуры от несанкционированного доступа.

**Admission Webhook Security** — защита портов оператора (обычно `9443`), через которые Kubernetes API-сервер проверяет корректность ресурсов мониторинга (PrometheusRule, ServiceMonitor) перед их созданием.

> **Навигация:** [Главная Security](./index.md) | [Управление секретами](./secrets_best_practices.md)

---

## Основные концепции

### Сетевые политики (Network Policies)

**NetworkPolicy** используется для изоляции компонентов мониторинга на сетевом уровне (L3/L4/L7). Это критически важно для защиты Prometheus и Alertmanager от несанкционированного доступа.

- **Принцип работы:** По умолчанию в Kubernetes разрешён весь трафик. Применение политики включает режим «запрещено по умолчанию» (default-deny) для выбранных подов.
- **Современные стандарты (2026):** Рекомендуется использование eBPF-плагинов (Cilium, Calico) для глубокой инспекции трафика и защиты от подмены IP.
- **L7 Фильтрация (Cilium):** Позволяет ограничивать доступ к конкретным эндпоинтам метрик, защищая от перехвата чувствительных данных и позволяя фильтровать метрики на лету через `metricRelabelings`.
- **Критические порты:**
    - Prometheus / Prometheus Agent: `9090` (UI/API)
    - Alertmanager: `9093` (API), `9094` (Gossip/HA)
    - Operator Webhook: `9443` (Validation/Mutation)
    - Thanos Sidecar: `10901` (gRPC)

### Ролевой доступ (RBAC)

**RBAC** управляет правами доступа компонентов мониторинга к Kubernetes API для обнаружения целей (Service Discovery) и управления ресурсами.

- **Service Discovery:** С 2025 года обязательным является использование `EndpointSlice` вместо устаревшего `Endpoints` для снижения нагрузки на Control Plane.
- **Принцип наименьших привилегий:** Prometheus требует права на чтение (`get`, `list`, `watch`) ресурсов во всех отслеживаемых неймспейсах.
- **Granular RBAC (Status Subresource):** С версии Operator v0.80+ поддерживается работа с подресурсом `status` для `ServiceMonitor`, `PodMonitor` и других CRD. Это позволяет внешним контроллерам обновлять состояние объектов без получения полных прав на изменение их конфигурации.
- **RBAC для PrometheusAgent:** В режиме агента (Forwarding) поды требуют таких же прав на чтение API (`nodes`, `pods`, `services`), как и полноценный Prometheus.
- **Управление CRD:** Оператор должен обладать правами на управление новыми ресурсами, такими как `ScrapeConfig`, `PrometheusAgent` и `ThanosRuler`.

### Безопасность Admission Webhooks

Для защиты взаимодействия между API-сервером и оператором используется TLS:
- **CA Injection (cert-manager):** Современный стандарт автоматизации `caBundle` в `ValidatingWebhookConfiguration`.
- **mTLS:** Возможность взаимной проверки сертификатов между API-сервером и вебхуком оператора для предотвращения подмены запросов.

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

#### L7-фильтрация метрик через Cilium

Пример `ServiceMonitor`, который использует `metricRelabelings` для сбора только критических L7-метрик сетевой политики, отсекая шум.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cilium-l7-filtered
spec:
  selector:
    matchLabels:
      k8s-app: cilium
  endpoints:
  - port: metrics
    metricRelabelings:
    - sourceLabels: [__name__]
      regex: 'cilium_policy_l7_.*'
      action: keep
```

#### Защита Admission Webhook (Operator)

Разрешает Kubernetes API-серверу доступ к вебхуку оператора для валидации ресурсов. Важно для предотвращения DoS-атак через некорректные CRD.

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

### Ролевой доступ и Валидация

#### Использование подресурса status

Для CI/CD систем или сторонних операторов рекомендуется ограничивать права только на `status`:

```yaml
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["servicemonitors/status", "podmonitors/status"]
    verbs: ["get", "patch", "update"]
```

#### Автоматизация TLS через cert-manager

Использование аннотации для автоматического внедрения CA в конфигурацию вебхука:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: prometheus-operator-rules
  annotations:
    cert-manager.io/inject-ca-from: monitoring/prometheus-operator-webhook-cert
```

#### Защита от SSRF (OAuth2 Token URL)

В современных версиях оператора встроенная валидация блокирует некорректные `tokenUrl` в OAuth2. Убедитесь, что Admission Webhook оператора активен для предотвращения SSRF-атак.

#### Валидация имен Prometheus 3.0

Если вы используете Prometheus 3.0 с поддержкой UTF-8, Admission Webhook должен быть настроен для пропуска новых символов. Для обратной совместимости с legacy-инструментами используйте:
`--name-validation-scheme=legacy` в аргументах запуска оператора.

---

### Примеры RBAC конфигураций

#### ServiceAccount для Prometheus

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
```

#### ClusterRole для доступа к Kubernetes API

Необходим для работы Service Discovery и сбора метрик (включая поддержку `PrometheusAgent` и `ScrapeConfig`).

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
  - apiGroups: ["monitoring.coreos.com"] # Поддержка ScrapeConfig и Agent
    resources:
      - scrapeconfigs
      - prometheusagents
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

Рекомендуется проводить ежеквартальный аудит прав `ClusterRoleBinding` для минимизации привилегий мониторинга.

- **[Безопасность (Главная)](./index.md)** — архитектура защиты стека.
- **[Управление секретами](./secrets_best_practices.md)** — ротация и внешние хранилища.
- **[NetworkPolicy: Обзор](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — глубокое погружение в сетевую изоляцию.
