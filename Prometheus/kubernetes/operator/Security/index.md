# Безопасность Prometheus Operator

## Определения

**Безопасность Prometheus Operator** — многоуровневая система защиты стека мониторинга в Kubernetes, охватывающая весь жизненный цикл данных: от безопасного хранения секретов и контроля доступа к API до шифрования трафика между компонентами и аутентификации пользователей. В современной экосистеме (2025–2026 гг.) включает в себя поддержку Prometheus 3.0 с обновлёнными протоколами Remote Write 2.0 и механизмами валидации имён.

**Threat Model Prometheus Operator** — модель угроз, учитывающая специфику инфраструктуры мониторинга:
- **Цель злоумышленника:** компрометация метрик, инъекция ложных данных, отказ в обслуживании (DoS) через сложные PromQL-запросы, эскалация привилегий через несанкционированный доступ к API Operator.
- **Активы:** секреты (пароли, токены, сертификаты), данные TSDB, контроль над ServiceMonitor/PrometheusRule.
- **Векторы атак:** открытые порты Web UI (9090/9093), слабые RBAC-права, отсутствие TLS, уязвимости Admission Webhooks, SSRF через OAuth2 tokenUrl.

**Defense in Depth (Эшелонированная защита)** — стратегия, при которой компрометация одного элемента инфраструктуры не приводит к полному захвату системы благодаря независимым слоям защиты (RBAC, NetworkPolicy, TLS, SecurityContext, Audit).

**Zero Trust для мониторинга** — подход, при котором ни один компонент (включая поды внутри кластера) не имеет доверия по умолчанию; каждый запрос должен быть авторизован и зашифрован.

---

## Основные концепции

### Эшелонированная защита (Defense in Depth)

Безопасность оператора строится на интеграции нативных механизмов Kubernetes и специфических настроек Custom Resources:

| Уровень | Механизм | Назначение | Источник |
|:---|:---|:---|:---|
| **Управление секретами** | Kubernetes Secrets, External Secrets (ESO) | Безопасное хранение токенов, паролей и ключей с автоматической ротацией. | [secrets_best_practices.md](./secrets_best_practices.md) |
| **Контроль доступа** | RBAC, ServiceAccounts | Авторизация запросов Prometheus к K8s API; использование `status` subresource для гранулярных прав. | [access_control.md](./access_control.md) |
| **Сетевая изоляция** | NetworkPolicy, eBPF (Cilium) | Ограничение L3/L4/L7 доступа к портам компонентов мониторинга. | [access_control.md](./access_control.md) |
| **Валидация ресурсов** | Admission Webhooks, CEL | Проверка корректности CRD (ServiceMonitor, PrometheusRule) перед применением; защита от SSRF. | Настоящий файл |
| **Безопасность подов** | SecurityContext, Pod Security Standards | Ограничение привилегий контейнеров (Non-root, Read-only FS, AppArmor, Seccomp). | Настоящий файл |
| **Инфраструктурный TLS** | `spec.web.tlsConfig`, cert-manager | Шифрование Web UI и API (Prometheus, Alertmanager). | Настоящий файл |
| **Аутентификация** | Basic Auth, OAuth2 Proxy, IAP | Идентификация пользователей; защита нового UI Prometheus 3.0. | [Web Authentication](../../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md) |
| **Аудит** | Kubernetes Audit Log, Prometheus Alerts | Обнаружение подозрительных операций и нарушений политик. | Настоящий файл |

### Принципы проектирования защиты

1. **Принцип наименьших привилегий (Least Privilege):** каждый компонент (Operator, Prometheus, Alertmanager) получает только те права, которые необходимы для его функций. лишние права — риск эскалации.
2. **Шифрование everywhere (Encryption in Transit):** все коммуникации между компонентами мониторинга и внешними системами должны быть зашифрованы (TLS/mTLS). Исключение — локальный скрейпинг внутри кластера с доверенными ServiceAccounts.
3. **Аутентификация before Authorization:** перед проверкой прав необходимо подтвердить личность (AuthN), и только потом определить набор разрешённых действий (AuthZ).
4. **Аудит и наблюдаемость:** каждый доступ к секретам, изменению CRD или доступу к API должен логироваться. Настройте алерты на подозрительные паттерны (например, массовое удаление ServiceMonitor).
5. **Fail-Safe по умолчанию:** при недоступности Admission Webhook или сети политика должна блокировать запрос, а не пропускать его (`failurePolicy: Fail` для валидирующих вебхуков).

### Критические порты и векторы атак

| Компонент | Порт | Протокол | Вектор атаки | Защита |
|:---|:---|:---|:---|:---|
| **Prometheus** | 9090 | TCP | Открытый Web UI, инъекция PromQL | NetworkPolicy, Basic Auth, TLS |
| **Alertmanager** | 9093 | TCP | Подмена алертов, утечка данных | NetworkPolicy, mTLS, Basic Auth |
| **Alertmanager (Gossip)** | 9094 | TCP/UDP | Взлом HA-кластера, split-brain | `clusterTLS`, изоляция сети |
| **Operator Webhook** | 9443 | TCP | Отказ в обслуживании (DoS), SSRF | NetworkPolicy, mTLS, CEL-валидация |
| **Thanos Sidecar** | 10901 | gRPC | Утечка метрик | mTLS, NetworkPolicy |

---

## Практические сценарии

### Настройка безопасности подов (Pod Security)

Рекомендуется использовать максимально строгие настройки `securityContext` для минимизации вектора атаки в случае компрометации контейнера.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: runtime/default
  containers:
    - name: prometheus
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
```

#### AppArmor профили

Для дополнительной защиты используйте кастомный AppArmor профиль, который ограничивает системные вызовы Prometheus. Создайте `LocalhostProfile` и укажите его в аннотации:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: localhost/k8s-apparmor-prometheus
```

Пример профиля `k8s-apparmor-prometheus` (требуется установка на ноды):
```bash
# /etc/apparmor.d/k8s-apparmor-prometheus
profile k8s-apparmor-prometheus flags=(attach_disconnected, mediate_deleted) {
  # Разрешение базовых операций
  capability,
  file,
  network,
  
  # Ограничение доступа к файловой системе
  deny /proc/** wklx,
  deny /sys/** wklx,
  
  # Ограничение сетевых операций
  network inet stream,
  network inet6 stream,
}
```

#### Pod Security Standards (PSA)

Включите enforcement namespace-уровня для принудительного применения политик:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
```

---

### Аутентификация и защита веб-интерфейсов

#### Встроенная авторизация и TLS (Prometheus 3.0)

Начиная с версии Operator v0.80+, настройка TLS и авторизации выполняется через блок `spec.web`. Важно учитывать новый флаг валидации имен при переходе на Prometheus 3.x.

```yaml
spec:
  web:
    tlsConfig:
      cert:
        secret: {name: prometheus-server-tls, key: tls.crt}
      keySecret:
        name: prometheus-server-tls, key: tls.key
    webConfig:
      basicAuth:
        username: {name: prometheus-auth, key: username}
        password: {name: prometheus-auth, key: password}
```

> **Важно:** Prometheus 3.0 поддерживает UTF-8 в именах метрик. Если ваши системы не готовы к этому, используйте флаг `--name-validation-scheme=legacy` в аргументах оператора для admission webhook.

#### Защита нового UI через OAuth2-proxy

Так как Prometheus не имеет встроенной поддержки OIDC/SAML, для корпоративных сред рекомендуется использовать OAuth2-proxy в качестве sidecar или на уровне Ingress.

#### Mutual TLS (mTLS) для компонентов

Для защиты внутреннего трафика между Prometheus и Alertmanager используйте mTLS. Это предотвращает подмену компонентов и перехват метрик:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  web:
    tlsConfig:
      cert:
        secret:
          name: prometheus-tls
          key: tls.crt
      keySecret:
        name: prometheus-tls
        key: tls.key
      clientCA:
        secret:
          name: prometheus-ca
          key: ca.crt
```

---

### Сетевая изоляция (Network Policies)

Сетевая политика — критически важный уровень защиты. По умолчанию Kubernetes разрешает весь трафик между подами; NetworkPolicy реализует режим «запрещено по умолчанию».

#### Default-Deny политика для namespace мониторинга

Применяйте политику, которая блокирует весь входящий и исходящий трафик, а затем явно разрешайте только необходимые:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
```

#### Доступ к Prometheus

Разрешает доступ к порту 9090 только для Grafana и компонентов внутри неймспейса `monitoring`:

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
              kubernetes.io/metadata.name: monitoring
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - port: 9090
          protocol: TCP
```

#### Защита Alertmanager

Разрешает входящий трафик на порт 9093 только от Prometheus и Gossip-трафик на 9094 только между репликами:

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
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9094
          protocol: TCP
        - port: 9094
          protocol: UDP
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
  policyTypes:
    - Ingress
  ingress:
    - from:
        - ipBlock:
            cidr: 10.0.0.0/8 # Ограничьте CIDR мастеров Kubernetes
      ports:
        - port: 9443
          protocol: TCP
```

> **Важно:** В production-средах ограничьте `ipBlock` CIDR только адресами мастеров Kubernetes API-серверов. Использование `0.0.0.0/0` недопустимо.

---

### Безопасность Admission Webhooks и SSRF

Оператор v0.80+ вводит строгую валидацию `tokenUrl` для OAuth2, чтобы предотвратить Server-Side Request Forgery (SSRF).

1.  **Проверка Webhook:** Убедитесь, что `ValidatingWebhookConfiguration` активен. Это предотвращает создание некорректных ресурсов, которые могут вызвать отказ в обслуживании (DoS) мониторинга.
2.  **Granular RBAC:** Используйте `status` subresource. Это позволяет автоматизированным системам обновлять статус мониторинга, не имея прав на изменение логики сбора метрик.

#### CEL-валидация (современная альтернатива)

Начиная с Kubernetes 1.25+, часть проверок можно перенести в CEL (Common Expression Language), что снижает задержку Admission Webhook (5-15 мс):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: example
spec:
  selector:
    matchLabels:
      app: example
  endpoints:
    - port: web
      interval: 30s
      # CEL-валидация на уровне поля
      path: /metrics # Должен начинаться с /
```

#### TLS для Admission Webhook

Используйте cert-manager для автоматического управления сертификатами:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: prometheus-operator-rules
  annotations:
    cert-manager.io/inject-ca-from: monitoring/prometheus-operator-webhook-cert
webhooks:
  - name: validate.prometheusrules.monitoring.coreos.com
    rules:
      - apiGroups: ["monitoring.coreos.com"]
        apiVersions: ["v1", "v1beta1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["prometheusrules"]
    failurePolicy: Fail # Блокировать создание при недоступности вебхука
```

---

### RBAC и минимальные привилегии

#### ServiceAccount для Prometheus

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: prometheus
  namespace: monitoring
```

#### ClusterRole для доступа к Kubernetes API

Необходим для работы Service Discovery и сбора метрик (включая поддержку `PrometheusAgent` и `ScrapeConfig`):

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
      - endpointslices
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
      - servicemonitors
      - podmonitors
      - prometheusrules
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics"]
    verbs: ["get"]
```

#### Status Subresource для CI/CD

Для CI/CD систем или сторонних операторов рекомендуется ограничивать права только на `status`:

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
```

---

### Защита Alertmanager

Alertmanager требует защиты не только API, но и внутреннего Gossip-трафика (порт 9094), используемого в HA-кластерах.

```yaml
kind: Alertmanager
metadata:
  name: main
  namespace: monitoring
spec:
  replicas: 3
  serviceAccountName: alertmanager
  clusterTLS: # Защита трафика между репликами (Gossip)
    cert:
      secret: {name: am-cluster-tls, key: tls.crt}
    keySecret: {name: am-cluster-tls, key: tls.key}
  web:
    tlsConfig: # Защита веб-интерфейса и API
      cert:
        secret: {name: am-web-tls, key: tls.crt}
      keySecret: {name: am-web-tls, key: tls.key}
      clientCA:
        secret:
          name: am-ca
          key: ca.crt # mTLS для входящих запросов
```

> **Примечание:** Gossip-протокол Alertmanager использует **TCP и UDP** на порту 9094. Убедитесь, что NetworkPolicy разрешает оба протокола между репликами. Подробнее о HA-архитектуре: [High Availability](../high_availability.md).

---

### Аудит и мониторинг безопасности

#### Kubernetes Audit Policy

Настройте аудит для отслеживания подозрительных операций с ресурсами мониторинга:

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: Metadata
    resources:
      - group: "monitoring.coreos.com"
        resources: ["servicemonitors", "podmonitors", "prometheusrules"]
    verbs: ["create", "update", "delete", "patch"]
  - level: RequestResponse
    resources:
      - group: ""
        resources: ["secrets"]
        namespaces: ["monitoring"]
```

#### PrometheusRules для безопасности

Создайте алерты на подозрительные активности:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: security-alerts
  namespace: monitoring
spec:
  groups:
    - name: security
      rules:
        - alert: ServiceMonitorDeleted
          expr: changes(kube_service_monitor_created[5m]) < 0
          for: 0m
          labels:
            severity: critical
          annotations:
            summary: "ServiceMonitor удалён"
            description: "{{ $labels.namespace }}/{{ $labels.name }} был удалён"
        
        - alert: OperatorDown
          expr: up{job="prometheus-operator"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Prometheus Operator недоступен"
            description: "Operator не отвечает, валидация CRD отключена"
```

---

### Диагностика и устранение неисправностей

#### Проблемы с CEL и Admission Webhooks

**Симптом:** Ошибки при создании ресурсов: `Internal error occurred: failed calling webhook`.

- **Проверка вебхука:** Оператор использует порт 9443 для валидации ресурсов.
  ```bash
  kubectl get svc -n monitoring # Ищите сервис с портом 443 -> 9443
  kubectl get ep -n monitoring <operator-service-name> # Проверьте наличие IP
  ```
- **TLS сертификаты:** Если сертификаты истекли или не созданы (cert-manager), API-сервер заблокирует создание CRD. Проверьте статус сертификата и аннотации в CRD.
- **CEL vs Webhook:** Если используется CEL-валидация, убедитесь, что версия Kubernetes >= 1.25 и поля имеют корректные `x-kubernetes-validations`.

#### RBAC: 403 Forbidden

**Симптом:** Prometheus видит 0 targets или Operator не может создать ServiceMonitor.

- **Диагностика:**
  ```bash
  kubectl auth can-i get servicemonitors --namespace monitoring --as system:serviceaccount:monitoring:prometheus
  ```
- **Решение:** Проверьте, что ClusterRole/Binding содержит необходимые ресурсы и `verbs`.

#### NetworkPolicy блокирует скрейпинг

**Симптом:** Targets в состоянии DOWN с ошибкой `connection refused`.

- **Причина:** Между подом Prometheus и целевым подом стоит NetworkPolicy, запрещающая трафик.
- **Решение:** Добавьте правило в NetworkPolicy, разрешающее трафик от Prometheus на порт метрик целевых подов.

---

### Чек-лист hardening

| Компонент | Проверка | Статус |
|:---|:---|:---:|
| **Secrets** | Шифрование etcd (`EncryptionConfiguration`) | ☐ |
| **Secrets** | Минимальные RBAC-права на секреты в namespace monitoring | ☐ |
| **RBAC** | ClusterRole содержит только необходимые `verbs` | ☐ |
| **RBAC** | Используется `status` subresource вместо полных прав | ☐ |
| **NetworkPolicy** | Default-deny для namespace monitoring | ☐ |
| **NetworkPolicy** | Доступ к 9090 только от Grafana и Prometheus | ☐ |
| **TLS** | Web UI Prometheus и Alertmanager защищены TLS | ☐ |
| **TLS** | Gossip Alertmanager (9094) защищён clusterTLS | ☐ |
| **Admission** | ValidatingWebhookConfiguration активен | ☐ |
| **Admission** | `failurePolicy: Fail` для валидирующих вебхуков | ☐ |
| **Pod Security** | `runAsNonRoot: true`, `readOnlyRootFilesystem: true` | ☐ |
| **Pod Security** | `allowPrivilegeEscalation: false`, `capabilities.drop: ["ALL"]` | ☐ |
| **Pod Security** | PSA namespace label `enforce: restricted` | ☐ |
| **AppArmor** | Профиль `runtime/default` или кастомный применён | ☐ |
| **Audit** | Включён Kubernetes Audit Log для monitoring namespace | ☐ |
| **Audit** | Настроены PrometheusRules на подозрительные активности | ☐ |

---

## Дополнительная информация

Безопасность Prometheus Operator является динамической областью. Для реализации специфических мер следуйте профильным руководствам:

- **[Контроль доступа](./access_control.md)** — глубокая настройка RBAC, NetworkPolicy и защита Admission Webhook.
- **[Управление секретами](./secrets_best_practices.md)** — ротация, ESO и интеграция с Vault.
- **[Web Authentication](../../Kube_Prometheus_Stack_Helm/practical_scenarios/web_authentication.md)** — реализация SSO, OAuth2-proxy и защита Grafana.
- **[High Availability](../high_availability.md)** — влияние отказоустойчивости на безопасность и Gossip-протокол.
- **[Prometheus Security](../../Prometheus/security.md)** — общая архитектура безопасности Prometheus.
