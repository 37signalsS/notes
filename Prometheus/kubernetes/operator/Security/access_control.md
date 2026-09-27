# Контроль доступа в Prometheus Operator

## Определения

**Контроль доступа** — комплексная система мер по ограничению взаимодействия с компонентами мониторинга, включающая сетевую изоляцию (Network Policies), авторизацию доступа к Kubernetes API (RBAC) и валидацию ресурсов через Admission Webhooks. Основная цель — реализация принципа минимальных привилегий и защита инфраструктуры от несанкционированного доступа.

**Threat Model для контроля доступа** — модель угроз, специфичная для инфраструктуры мониторинга:
- **Цель злоумышленника:** компрометация метрик, инъекция ложных данных, эскалация привилегий через несанкционированный доступ к API Operator, DoS через некорректные CRD.
- **Активы:** секреты (токены, сертификаты), данные TSDB, контроль над ServiceMonitor/PrometheusRule.
- **Векторы атак:** открытые порты Web UI (9090/9093), избыточные RBAC-права, отсутствие TLS, уязвимости Admission Webhooks, SSRF через OAuth2 `tokenUrl`, отсутствие egress-политик.

**Admission Webhook Security** — защита портов оператора (обычно `9443`), через которые Kubernetes API-сервер проверяет корректность ресурсов мониторинга (PrometheusRule, ServiceMonitor) перед их созданием.

**Defense in Depth (Эшелонированная защита)** — стратегия, при которой компрометация одного элемента инфраструктуры не приводит к полному захвату системы благодаря независимым слоям защиты (RBAC, NetworkPolicy, TLS, SecurityContext, Audit).

**Zero Trust для мониторинга** — подход, при котором ни один компонент (включая поды внутри кластера) не имеет доверия по умолчанию; каждый запрос должен быть авторизован и зашифрован.

> **Навигация:** [Главная Security](./index.md) | [Управление секретами](./secrets_best_practices.md)

---

## Основные концепции

### Сетевые политики (Network Policies)

**NetworkPolicy** используется для изоляции компонентов мониторинга на сетевом уровне (L3/L4/L7). Это критически важно для защиты Prometheus и Alertmanager от несанкционированного доступа.

- **Принцип работы:** По умолчанию в Kubernetes разрешён весь трафик. Применение политики включает режим «запрещено по умолчанию» (default-deny) для выбранных подов.
- **Egress так же важен, как и Ingress:** Отсутствие egress-политики позволяет компрометированному поду атаковать внутренние сервисы (metadata API, etcd, CoreDNS), отправлять данные наружу (эксфильтрация) или сканировать сеть.
- **Современные стандарты (2026):** Рекомендуется использование eBPF-плагинов (Cilium, Calico) для глубокой инспекции трафика и защиты от подмены IP.
- **L7 Фильтрация (Cilium):** Позволяет ограничивать доступ к конкретным эндпоинтам метрик, защищая от перехвата чувствительных данных и позволяя фильтровать метрики на лету через `metricRelabelings`.
- **DNS в egress-политиках:** Любой под, которому необходим доступ к внешним сервисам или Service Discovery, должен иметь явное разрешение на доступ к CoreDNS (порт 53 UDP/TCP в namespace `kube-system`).
- **Thanos Sidecar/Ruler:** Требуют отдельных политик egress на порт `10901` (gRPC) для взаимодействия с Thanos Store/Query, а также политик ingress для входящих запросов от Prometheus.
- **Критические порты:**
    - Prometheus / Prometheus Agent: `9090` (UI/API)
    - Alertmanager: `9093` (API), `9094` (Gossip/HA)
    - Operator Webhook: `9443` (Validation/Mutation)
    - Thanos Sidecar: `10901` (gRPC)

### Ролевой доступ (RBAC)

**RBAC** управляет правами доступа компонентов мониторинга к Kubernetes API для обнаружения целей (Service Discovery) и управления ресурсами.

- **Service Discovery:** С 2025 года обязательным является использование `EndpointSlice` вместо устаревшего `Endpoints` для снижения нагрузки на Control Plane.
- **Role vs ClusterRole:** Используйте `Role` для прав внутри одного namespace (например, для CI/CD, обновляющего `status` ServiceMonitor). Используйте `ClusterRole` только для ресурсов, требующих доступа ко всем namespace (например, `nodes`, `services`, `endpointslices`, `scrapeconfigs`).
- **Принцип наименьших привилегий:** Prometheus требует права на чтение (`get`, `list`, `watch`) ресурсов во всех отслеживаемых неймспейсах. Исключите ненужные `verbs` (`create`, `update`, `patch`, `delete`) из ClusterRole.
- **Bound ServiceAccount Tokens:** Начиная с Kubernetes 1.24, по умолчанию используются ограниченные по времени токены (`Bound Token`). Это повышает безопасность: при компрометации токена он автоматически истекает. Убедитесь, что `serviceAccountTokenProjection` не отключён.
- **Granular RBAC (Status Subresource):** С версии Operator v0.80+ поддерживается работа с подресурсом `status` для `ServiceMonitor`, `PodMonitor` и других CRD. Это позволяет внешним контроллерам обновлять состояние объектов без получения полных прав на изменение их конфигурации.
- **RBAC для PrometheusAgent:** В режиме агента (Forwarding) поды требуют таких же прав на чтение API (`nodes`, `pods`, `services`), как и полноценный Prometheus.
- **Агрегируемые ClusterRole:** Для упрощения управления большими наборами прав используйте `aggregationRule`. Это позволяет автоматически собирать правила из нескольких ClusterRole.
- **Управление CRD:** Оператор должен обладать правами на управление новыми ресурсами, такими как `ScrapeConfig`, `PrometheusAgent` и `ThanosRuler`.

### Безопасность Admission Webhooks

Для защиты взаимодействия между API-сервером и оператором используется TLS:
- **CA Injection (cert-manager):** Современный стандарт автоматизации `caBundle` в `ValidatingWebhookConfiguration`.
- **mTLS:** Возможность взаимной проверки сертификатов между API-сервером и вебхуком оператора для предотвращения подмены запросов.
- **`failurePolicy: Fail` vs `Ignore`:** Для валидирующих вебхуков (ValidatingWebhook) всегда используйте `failurePolicy: Fail`. При недоступности вебхука это блокирует создание ресурса, а не пропускает некорректный объект. Исключение — mutate-вебхуки, где `Ignore` допустим только для не-критичных модификаций.
- **CEL-валидация (Kubernetes 1.25+):** Современная альтернатива вебхукам для простых проверок. CEL работает быстрее (внутри API-сервера, без сетевого вызова), снижая задержку на 5–15 мс. Пример валидации для `ServiceMonitor`: проверка, что `path` начинается с `/`.
- **Timeout:** Устанавливайте `timeoutSeconds: 5` для вебхуков оператора. Большие значения блокируют создание ресурсов при высокой нагрузке.
- **Side Effects:** Указывайте `sideEffects: None` для валидирующих вебхуков, чтобы API-сервер мог кэшировать результаты.

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

#### Egress: DNS и внешние сервисы (Prometheus)

Prometheus требует исходящего доступа к DNS (CoreDNS) и, возможно, к внешним сервисам (webhook-у, удалённым хранилищам Thanos):

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-egress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Разрешите egress к Alertmanager (9093) и, при необходимости, к внешним webhook
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9093
          protocol: TCP
```

#### Защита Thanos Sidecar / ThanosRuler

Thanos Sidecar требует доступа к Store Gateway и Query на порту `10901`. ThanosRuler аналогично требует egress к Store Gateway и ingress от Prometheus для проверки алертов:

```yaml
# NetworkPolicy для Thanos Sidecar
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: thanos-sidecar-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: thanos-sidecar
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 10901
          protocol: TCP
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: thanos-query
      ports:
        - port: 10901
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
```

#### Ограничение доступа к Grafana (внешний доступ)

Если Grafana развёрнута в отдельном namespace, разрешите доступ только от engineering-zone и к API Prometheus:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: grafana-access
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: grafana
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              network/zone: engineering
      ports:
        - port: 3000
          protocol: TCP
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9090
          protocol: TCP
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
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

**Влияние на RBAC и NetworkPolicy:**
- Prometheus 3.0 не вводит новых ресурсов CRD, требующих дополнительных RBAC-прав. Существующий `ClusterRole` для `monitoring.coreos.com` покрывает `servicemonitors`, `podmonitors`, `prometheusrules`, `scrapeconfigs` и `prometheusagents`.
- Изменения в `name-validation-scheme` влияют только на Admission Webhook, но не на сетевые политики.
- При переходе с `legacy` на `strict` (UTF-8) убедитесь, что все существующие `ServiceMonitor` и `PodMonitor` имеют корректные DNS-совместимые имена, иначе Admission Webhook начнёт отклонять ресурсы.

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

#### Role для namespace-scoped доступа (CI/CD)

Для систем CI/CD, обновляющих `status` мониторинговых ресурсов, используйте `Role` вместо `ClusterRole` для ограничения области действия одним namespace:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: servicemonitor-status-updater
  namespace: monitoring
rules:
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["servicemonitors/status", "podmonitors/status"]
    verbs: ["get", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: servicemonitor-status-updater
  namespace: monitoring
subjects:
  - kind: ServiceAccount
    name: ci-cd-updater
    namespace: ci-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: servicemonitor-status-updater
```

#### ClusterRole для ThanosRuler

ThanosRuler требует прав на чтение `PrometheusRule` и `Alertmanager` для отправки алертов:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: thanos-ruler
rules:
  - apiGroups: [""]
    resources: ["nodes", "pods", "services", "endpoints", "endpointslices"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["monitoring.coreos.com"]
    resources: ["prometheusrules", "alertmanagers"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
```

#### Агрегируемый ClusterRole

Для упрощения управления большими наборами прав используйте `aggregationRule`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-viewer
  labels:
    rbac.aggregation.k8s.io/automatic-refresh: "true"
aggregationRule:
  clusterRoleSelectors:
    - matchLabels:
        rbac.monitoring.example.com/viewer: "true"
```

#### Bound ServiceAccount Tokens (Kubernetes 1.24+)

Начиная с 1.24, по умолчанию используются ограниченные по времени токены. Убедитесь, что projection включён для дополнительной безопасности:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
automountServiceAccountToken: true
---
apiVersion: v1
kind: Pod
metadata:
  name: prometheus
  namespace: monitoring
spec:
  serviceAccountName: prometheus
  containers:
    - name: prometheus
      image: prom/prometheus:v3.0.0
      volumeMounts:
        - name: service-account-token
          mountPath: /var/run/secrets/kubernetes.io/serviceaccount
          readOnly: true
  volumes:
    - name: service-account-token
      projected:
        sources:
          - serviceAccountToken:
              path: token
              expirationSeconds: 7200
              audience: api
```

---

### Валидация и диагностика

#### RBAC

```bash
# Проверка прав ServiceAccount Prometheus на чтение ServiceMonitor
kubectl auth can-i get servicemonitors \
  --namespace monitoring \
  --as system:serviceaccount:monitoring:prometheus
# → yes

# Просмотр всех прав субъекта
kubectl auth can-i --list \
  --as system:serviceaccount:monitoring:prometheus \
  -n monitoring

# Поиск всех привязок для ServiceAccount
kubectl get rolebindings,clusterrolebindings -A -o wide | grep prometheus

# Проверка конкретного права на подресурс status
kubectl auth can-i patch servicemonitors/status \
  --namespace monitoring \
  --as system:serviceaccount:ci-system:ci-cd-updater
```

**Типичные ошибки:**
- `403 Forbidden`: ClusterRole не содержит необходимого ресурса или `verbs`. Проверьте опечатки в `apiGroups` (например, `monitoring.coreos.com` vs `monitoring`).
- `0 targets`: Prometheus не имеет прав `list/watch` на `endpointslices` в namespace целей. Добавьте правило.

#### NetworkPolicy

```bash
# Проверка применяемых политик в namespace
kubectl get networkpolicy -n monitoring

# Описание конкретной политики
kubectl describe networkpolicy prometheus-egress -n monitoring

# Проверка связности изнутри пода (сетевой тест)
kubectl exec -it <prometheus-pod> -n monitoring -- \
  curl -v http://<alertmanager-service>:9093/api/v2/alerts

# Проверка DNS-резолвинга из пода
kubectl exec -it <prometheus-pod> -n monitoring -- nslookup kubernetes.default

# Проверка DROP-пакетов через Cilium Hubble (если используется Cilium)
hubble observe --type drop --namespace monitoring
```

**Типичные ошибки:**
- `connection refused`: NetworkPolicy блокирует egress. Добавьте правило для целевого порта.
- DNS не работает: отсутствует egress на порт 53 UDP/TCP к `kube-dns`.

#### Admission Webhooks

```bash
# Проверка статуса ValidatingWebhookConfiguration
kubectl get validatingwebhookconfiguration prometheus-operator-rules

# Описание вебхука и проверка caBundle
kubectl describe validatingwebhookconfiguration prometheus-operator-rules

# Проверка сервиса вебхука и endpoint
kubectl get svc -n monitoring | grep webhook
kubectl get ep -n monitoring <webhook-service-name>

# Проверка сертификатов cert-manager
kubectl get certificate -n monitoring
kubectl describe certificate prometheus-operator-webhook-cert -n monitoring
```

**Типичные ошибки:**
- `failed calling webhook`: порт 9443 недоступен или сертификат истёк. Проверьте endpoint и `cert-manager`.
- `Internal error occurred`: CEL-валидация несовместима с версией K8s (< 1.25) или содержит ошибку в `x-kubernetes-validations`.

---

## Дополнительная информация

Рекомендуется проводить ежеквартальный аудит прав `ClusterRoleBinding` для минимизации привилегий мониторинга.

- **[Безопасность (Главная)](./index.md)** — архитектура защиты стека.
- **[Управление секретами](./secrets_best_practices.md)** — ротация и внешние хранилища.
- **[NetworkPolicy: Обзор](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — глубокое погружение в сетевую изоляцию.
- **[Network Policies для мониторинга](../network_policies.md)** — детальные правила для Prometheus, Alertmanager, Grafana, Thanos.
