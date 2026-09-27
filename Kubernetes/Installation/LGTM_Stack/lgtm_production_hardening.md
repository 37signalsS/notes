# Production Hardening для стека LGTM

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**
> - **[Production Hardening](./lgtm_production_hardening.md)** (текущий)

---

## Определения

**Production Hardening (жёсткая настройка)** — комплекс мер по защите системы от атак, снижению поверхности атаки и обеспечению соответствия требованиям безопасности в рабочей среде.

**Defense in Depth (многоуровневая защита)** — стратегия безопасности, при которой каждый слой защищает независимо от других: сеть, транспорт, аутентификация, авторизация, шифрование данных.

**Least Privilege (наименьшие привилегии)** — принцип предоставления каждому компоненту только минимально необходимых прав для выполнения своих функций.

**Secret Management (управление секретами)** — централизованное хранение и ротация учетных данных, паролей, сертификатов через специализированные системы (HashiCorp Vault, Kubernetes Secrets, Sealed Secrets).

---

## Основные концепции

### Архитектура безопасности стека LGTM

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        Production LGTM Stack                            │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 1: Сеть и транспорт                      │  │
│  │  • NetworkPolicies для изоляции компонентов                       │  │
│  │  • mTLS между всеми компонентами (cert-manager + Istio/Linkerd)  │  │
│  │  • TLS для внешних подключений (Ingress)                         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 2: Аутентификация и авторизация          │  │
│  │  • OIDC/LDAP для Grafana (Keycloak, Okta)                        │  │
│  │  • RBAC для Kubernetes API                                       │  │
│  │  • API-ключи для Prometheus/Loki/Tempo                           │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 3: Управление секретами                   │  │
│  │  • HashiCorp Vault для динамических секретов                     │  │
│  │  • Sealed Secrets для Kubernetes Secrets                         │  │
│  │  • Шифрование данных в покое (encryption at rest)                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Слой 4: Аудит и мониторинг                     │  │
│  │  • Журналы аудита доступа к Grafana                              │  │
│  │  • Мониторинг самого стека LGTM                                  │  │
│  │  • Алерты на инциденты безопасности                              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Ключевые принципы production-безопасности

| Принцип | Описание | Реализация в LGTM |
| :--- | :--- | :--- |
| **Изоляция компонентов** | Каждый компонент в отдельном namespace с минимальными правами | NetworkPolicies, RBAC |
| **Шифрование трафика** | Все коммуникации по TLS/mTLS | cert-manager, Istio/Linkerd |
| **Централизованное управление секретами** | Единый источник для паролей, токенов, сертификатов | Vault, Sealed Secrets |
| **Мониторинг доступа** | Аудит всех попыток доступа к системе | Grafana Audit Logs, Prometheus |
| **Автоматическая ротация** | Регулярная замена ключей и паролей | Vault, cert-manager |

---

## Практические сценарии

### Сценарий 1: Настройка NetworkPolicies для изоляции компонентов

**Цель:** Ограничить сетевое взаимодействие между компонентами стека LGTM.

#### Шаг 1: Создание NetworkPolicy для namespace monitoring

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-allow-ingress
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: opentelemetry
      ports:
        - protocol: TCP
          port: 9090
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
```

#### Шаг 2: Создание NetworkPolicy для namespace loki

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: loki-allow-ingress
  namespace: loki
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: loki
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: opentelemetry
      ports:
        - protocol: TCP
          port: 3100
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 3100
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
```

#### Шаг 3: Создание NetworkPolicy для namespace tempo

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tempo-allow-ingress
  namespace: tempo
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: tempo
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: opentelemetry
      ports:
        - protocol: TCP
          port: 3200
        - protocol: TCP
          port: 4317
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 3200
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
```

#### Шаг 4: Создание NetworkPolicy для namespace opentelemetry

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: otel-collector-allow-ingress
  namespace: opentelemetry
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: opentelemetry-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
        - protocol: TCP
          port: 8889
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: tempo
      ports:
        - protocol: TCP
          port: 4317
    - to:
        - namespaceSelector:
            matchLabels:
              name: loki
      ports:
        - protocol: TCP
          port: 3100
    - to:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - protocol: TCP
          port: 9090
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53
        - protocol: UDP
          port: 53
```

**Валидация:**

```bash
# Проверка создания NetworkPolicy
kubectl get networkpolicy -n monitoring
kubectl get networkpolicy -n loki
kubectl get networkpolicy -n tempo
kubectl get networkpolicy -n opentelemetry

# Проверка, что трафик блокируется/разрешается корректно
kubectl exec -n opentelemetry deploy/otel-collector -- curl -s http://loki.loki:3100/ready
# → Expected: ready

kubectl exec -n opentelemetry deploy/otel-collector -- curl -s http://tempo.tempo:3200/ready
# → Expected: ok
```

---

### Сценарий 2: Настройка mTLS между компонентами

**Цель:** Включить шифрование трафика между всеми компонентами стека LGTM.

> **Примечание:** Подробная теория mTLS и Service Mesh описана в:
> - [Service Mesh: Концепции](../../../Service_Mesh/service_mesh_concepts.md)
> - [Istio: Архитектура](../../../Service_Mesh/istio_architecture.md)
> - [Концепции Zero Trust](../../../Vault/zero_trust.md)

#### Шаг 1: Включение Istio в namespace monitoring

```bash
# Включение автоматической инъекции сайдкаров
kubectl label namespace monitoring istio-injection=enabled

# Перезапуск подов для применения сайдкаров
kubectl rollout restart deployment prometheus-kube-prometheus-prometheus -n monitoring
kubectl rollout restart deployment prometheus-grafana -n monitoring
kubectl rollout restart statefulset alertmanager-prometheus-kube-prometheus-alertmanager -n monitoring
```

#### Шаг 2: Включение Istio в namespace loki

```bash
kubectl label namespace loki istio-injection=enabled
kubectl rollout restart statefulset loki-0 -n loki
```

#### Шаг 3: Включение Istio в namespace tempo

```bash
kubectl label namespace tempo istio-injection=enabled
kubectl rollout restart statefulset tempo-0 -n tempo
```

#### Шаг 4: Включение Istio в namespace opentelemetry

```bash
kubectl label namespace opentelemetry istio-injection=enabled
kubectl rollout restart deployment otel-collector -n opentelemetry
```

#### Шаг 5: Настройка строгого режима mTLS

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: default
  namespace: istio-system
spec:
  host: "*.local"
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL
```

**Валидация:**

```bash
# Проверка статуса mTLS
istioctl x describe pod <pod-name> -n monitoring
# → Expected: Mtls: STRICT

# Проверка, что трафик шифруется
istioctl proxy-status
# → Expected: все поды в статусе SYNCED
```

---

### Сценарий 3: Настройка OIDC для Grafana

**Цель:** Заменить базовую аутентификацию на корпоративный провайдер.

> **Примечание:** Подробная настройка Grafana.security описана в:
> - [Grafana: Безопасность и жёсткая настройка](../../../Grafana/grafana_security_hardening.md)
> - [Grafana: SSO, SAML, JWT](../../../Grafana/grafana_sso_saml_jwt.md)

#### Шаг 1: Конфигурация OIDC в grafana.ini

```ini
[auth.generic_oauth]
enabled = true
name = Keycloak
icon = keycloak
allow_sign_up = true
client_id = grafana
client_secret = <secret-from-vault>
scopes = openid profile email
auth_url = https://keycloak.example.internal/realms/production/protocol/openid-connect/auth
token_url = https://keycloak.example.internal/realms/production/protocol/openid-connect/token
api_url = https://keycloak.example.internal/realms/production/protocol/openid-connect/userinfo
role_attribute_path = contains(realm_access.roles[*], 'admin') && 'Admin' || contains(realm_access.roles[*], 'editor') && 'Editor' || 'Viewer'
```

#### Шаг 2: Настройка RBAC в Grafana

```ini
[roles]
allow_assign_grafana_admin = false
allow_grafana_admin = false

[auth]
disable_login_form = false
disable_signout_menu = false

[users]
auto_assign_org = true
auto_assign_org_role = Viewer
```

#### Шаг 3: Включение аудита доступа

```ini
[audit]
enabled = true
log_destination = stdout
```

**Валидация:**

```bash
# Проверка, что аутентификация работает
curl -s https://grafana.example.internal/api/health
# → Expected: {"database":"ok","version":"...","status":"ok"}

# Проверка, что регистрация отключена
curl -s https://grafana.example.internal/api/user/signup 2>&1 | grep -i "forbidden\|not found"
# → Expected: ошибка авторизации
```

---

### Сценарий 4: Настройка управления секретами через Vault

**Цель:** Централизованное хранение и ротация секретов стека LGTM.

> **Примечание:** Подробная интеграция Vault с Kubernetes описана в:
> - [Vault: Интеграция с Kubernetes](../../../Vault/vault_kubernetes_integration.md)
> - [Vault Agent Injector](../../../Vault/guides/vault_agent/injector.md)

#### Шаг 1: Включение Kubernetes auth method в Vault

```bash
vault auth enable kubernetes
vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"
```

#### Шаг 2: Создание.policy для LGTM стека

```hcl
# lgmt-policy.hcl
path "secret/data/grafana/*" {
  capabilities = ["read"]
}

path "secret/data/prometheus/*" {
  capabilities = ["read"]
}

path "secret/data/loki/*" {
  capabilities = ["read"]
}

path "secret/data/tempo/*" {
  capabilities = ["read"]
}

path "secret/data/otel/*" {
  capabilities = ["read"]
}
```

```bash
vault policy write lgmt-policy lgmt-policy.hcl
```

#### Шаг 3: Создание роли для Kubernetes

```bash
vault write auth/kubernetes/role/lgmt-role \
  bound_service_account_names=grafana,prometheus,loki,tempo,otel-collector \
  bound_service_account_namespaces=monitoring,loki,tempo,opentelemetry \
  policies=lgmt-policy \
  ttl=1h
```

#### Шаг 4: Настройка Injector для Grafana

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: monitoring
spec:
  template:
    metadata:
      annotations:
        vault.hashicorp.com/agent-inject: "true"
        vault.hashicorp.com/role: "lgmt-role"
        vault.hashicorp.com/agent-inject-secret-grafana-admin: "secret/data/grafana/admin"
        vault.hashicorp.com/agent-inject-template-grafana-admin: |
          {{- with secret "secret/data/grafana/admin" -}}
          [security]
          admin_user = {{ .Data.data.username }}
          admin_password = {{ .Data.data.password }}
          {{- end -}}
```

**Валидация:**

```bash
# Проверка, что Vault Agent внедряется
kubectl describe pod -n monitoring -l app.kubernetes.io/name=grafana | grep -A 5 "Init Containers"
# → Expected: init-контейнер vault-agent

# Проверка логов Vault Agent
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c vault-agent --tail=10
# → Expected: логи успешной аутентификации
```

---

### Сценарий 5: Настройка шифрования данных в покое

**Цель:** Защитить данные Prometheus, Loki и Tempo при хранении.

#### Шаг 1: Шифрование PVC через StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: encrypted-ssd
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
  encrypted: "true"
  kmsKeyId: arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
```

#### Шаг 2: Применение StorageClass к компонентам

```bash
# Обновление Prometheus для использования зашифрованного StorageClass
helm upgrade prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.storageClassName=encrypted-ssd

# Обновление Loki
helm upgrade loki oci://ghcr.io/grafana-community/helm-charts/loki \
  --namespace loki \
  --set loki.storage.volumeClaimTemplate.spec.storageClassName=encrypted-ssd

# Обновление Tempo
helm upgrade tempo oci://ghcr.io/grafana-community/helm-charts/tempo \
  --namespace tempo \
  --set tempo.persistence.storageClassName=encrypted-ssd
```

---

### Сценарий 6: Настройка аудита и мониторинга

**Цель:** Отслеживать все попытки доступа к компонентам стека.

#### Шаг 1: Включение аудита в Grafana

```ini
[audit]
enabled = true
log_destination = stdout
log_mode = console
```

#### Шаг 2: Настройка алертов на подозрительную активность

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
        - alert: GrafanaLoginFailed
          expr: rate(grafana_api_login_failed_total[5m]) > 0.1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Многократные неудачные попытки входа в Grafana"
            description: "Обнаружено более 10 неудачных попыток входа в минуту"

        - alert: PrometheusUnauthorizedAccess
          expr: rate(prometheus_http_requests_total{code="401"}[5m]) > 0
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Попытки неавторизованного доступа к Prometheus"
```

---

## Дополнительная информация

### Чек-лист production-безопасности

| Компонент | Проверка | Статус |
| :--- | :--- | :--- |
| **Сеть** | NetworkPolicies настроены для всех namespace | ☐ |
| **Транспорт** | mTLS включен для всех компонентов | ☐ |
| **Аутентификация** | OIDC/LDAP настроен для Grafana | ☐ |
| **Авторизация** | RBAC настроен для всех сервис-аккаунтов | ☐ |
| **Секреты** | Vault интегрирован с Kubernetes | ☐ |
| **Шифрование** | PVC зашифрованы | ☐ |
| **Аудит** | Журналы аудита включены | ☐ |
| **Мониторинг** | Алерты на инциденты настроены | ☐ |

### Связанные материалы

- **[Grafana: Безопасность](../../../Grafana/grafana_security_hardening.md)** — детальный хардинг Grafana
- **[Service Mesh: Концепции](../../../Service_Mesh/service_mesh_concepts.md)** — теория mTLS и Service Mesh
- **[Vault: Zero Trust](../../../Vault/zero_trust.md)** — реализация Zero Trust с Vault
- **[Kubernetes: NetworkPolicy](../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — сетевая изоляция

---

**Навигация по руководству:**

- **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)** (назад)
- **[Backup и восстановление](./lgtm_backup_disaster_recovery.md)** (вперед)
