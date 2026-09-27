# Управление секретами в Prometheus Operator

## Определения

**Управление секретами** — комплекс процессов по обеспечению жизненного цикла конфиденциальных данных (паролей, токенов, сертификатов) в стеке мониторинга. В Kubernetes-среде это включает безопасное хранение в `etcd`, динамическую доставку в поды через тома (Volumes) и интеграцию с внешними системами управления ключами (KMS).

**Централизованное управление секретами (Centralized Secrets Management)** — стратегия, при которой секреты не хранятся в Git в открытом виде, а синхронизируются из внешних источников (например, Vault) напрямую в Kubernetes через специализированные контроллеры, что исключает попадание открытых данных в Git.

**Secret Sprawl (Расползание секретов)** — явление, при котором конфиденциальные данные рассредоточены по коду, конфигурациям, CI/CD переменным и документации без централизованного контроля. В контексте мониторинга Secret Sprawl проявляется в хранении токенов Slack, SMTP-паролей и credentials баз данных прямо в манифестах или Helm-values.

**Lifecycle секрета в Operator** — полный цикл: создание внешнего секрета → синхронизация в Kubernetes Secret → включение в CRD (ScrapeConfig, ServiceMonitor, AlertmanagerConfig и др.) → генерация Operator-ом агрегированного конфига → доставка в под через Volume → hot-reload через config-reloader.

---

## Жизненный цикл секретов в Prometheus Operator

Prometheus Operator управляет секретами через несколько механизмов, отличающихся от обычного приложения:

1.  **Генерация конфигурации:** Operator собирает все связанные ресурсы (`ServiceMonitor`, `PodMonitor`, `Probe`, `ScrapeConfig`, `PrometheusRule`, `AlertmanagerConfig`) и агрегирует их в единый YAML-файл (`prometheus.yaml` или `alertmanager.yaml`).
2.  **Сжатие и хранение в Secret:** Итоговый конфиг сжимается gzip и сохраняется в объекте Kubernetes Secret (по умолчанию `<name>-generated` или `<name>`). Лимит размера Secret — **1 MiB** (ограничение etcd).
3.  **Монтирование в Pod:** Secret монтируется как Volume в StatefulSet Prometheus/Alertmanager в режиме `readOnly`.
4.  **Hot Reload:** Sidecar-контейнер `config-reloader` отслеживает изменения в Secret/ConfigMap и отправляет HTTP POST на `/-/reload` без перезапуска пода.

**Критическая деталь:** Оператор не хранит сами credentials (пароли, токены) в генерируемом Secret — только ссылки на них (`secretRef`, `basicAuth.username.secret.name`). Сами секреты с чувствительными данными создаются и управляются пользователем или External Secrets Operator.

---

## Основные концепции

### Типы секретов в экосистеме Operator

| Тип | Назначение | Основной ресурс (CRD) |
|:---|:---|:---|
| **Auth Credentials** | Токены Basic Auth, OAuth2 Client ID/Secret, API Keys | `ServiceMonitor`, `ScrapeConfig`, `Prometheus.web` |
| **Alerting Config** | Webhooks (Slack, Telegram), SMTP, PagerDuty, OpsGenie, Jira | `AlertmanagerConfig` |
| **TLS/mTLS** | CA сертификаты, клиентские ключи/сертификаты | `Prometheus` (web), `ServiceMonitor` (tlsConfig) |
| **Storage Auth** | Конфигурация доступа к объектному хранилищу | `Prometheus` (Thanos Sidecar), `PrometheusAgent` |

### Неизменяемые секреты (Immutable Secrets)

Функция перешла в статус **GA** в Kubernetes 1.21+. Секреты можно помечать как неизменяемые для повышения безопасности и производительности:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-tls
  namespace: monitoring
  immutable: true
type: kubernetes.io/tls
data:
  tls.crt: LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCg==
  tls.key: LS0tLS1CRUdJTiBSU0EgQUJQTHR4ZXQ9
```

**Преимущества:**
- **Защита от изменений:** предотвращает случайное или злонамеренное обновление данных
- **Производительность:** `kubelet` перестает опрашивать `kube-apiserver` на предмет обновлений для этих секретов

**Применение в мониторинге:**
- TLS-сертификаты Alertmanager и Prometheus
- Статические ключи API внешних систем (если ротация не требуется)
- CA-корневые сертификаты для доверия к целям скрейпинга

### Ограничения размера

Размер объекта Secret ограничен **1 MiB** (лимит etcd). Итоговый сжатый `prometheus.yaml` или `alertmanager.yaml` не должен превышать этот лимит.

**Практические рекомендации:**
- Контролируйте размер через: `kubectl get secret prometheus-main -n monitoring -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c`
- При приближении к 800 KiB — планируйте шардирование (`spec.shards`) или переход на `ScrapeConfig`
- Для больших сертификатов (длинные цепочки CA) используйте `ConfigMap` + `secretRef` в `tlsConfig.ca`

### Тепловая перезагрузка (Hot Reload) через Config-Reloader

Prometheus Operator использует sidecar `config-reloader` (образ `quay.io/prometheus-operator/prometheus-config-reloader`), который:

1.  Отслеживает изменения в примонтированных ConfigMap и Secret
2.  При изменении отправляет HTTP POST на `/-/reload`
3.  Валидирует конфигурацию через `promtool check config` перед reload
4.  Обновляет метрику `prometheus_config_last_reload_success_timestamp_seconds`

**Диагностика config-reloader:**

```bash
# Просмотр логов sidecar
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50

# Поиск ошибок валидации
kubectl logs -n monitoring prometheus-main-0 -c config-reloader | grep -i "error"

# Проверка метрики успешности reload
kubectl exec -n monitoring prometheus-main-0 -- wget -qO- http://localhost:9090/metrics \
  | grep prometheus_config_last_reload_success_timestamp_seconds
```

---

## Механизмы автоматизации и ротации

Современная инфраструктура требует минимизации ручного управления секретами:

*   **External Secrets Operator (ESO):** Стандарт для синхронизации секретов из внешних хранилищ (Vault, внешние KMS) в нативные Kubernetes Secret. Поддерживает автоматическое обновление Secret при изменении в источнике через `refreshInterval`.
*   **Secrets Store CSI Driver:** Позволяет монтировать секреты напрямую из внешних хранилищ в файловую систему пода, минуя создание объекта `Secret` в Kubernetes (секрет не попадает в `etcd`).
*   **Vault Secrets Operator (VSO):** Нативный оператор HashiCorp для синхронизации статических и динамических секретов из Vault с поддержкой автоматической ротации.

> **SSoT:** Детальное сравнение ESO, CSI и VSO — в [Внешние менеджеры](../../../../Kubernetes/Base/secrets/external_managers.md). Настоящий документ описывает применение этих механизмов в стеке Prometheus Operator.

---

## Практические сценарии

### ScrapeConfig с OAuth2 ротацией

`ScrapeConfig` (v0.65.0+) позволяет гибко настраивать авторизацию для внешних сервисов. При обновлении секрета `config-reloader` автоматически обновит путь к `client_secret_file`.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: secure-api-scrape
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["api.corp.local"]
  oauth2:
    clientId:
      secret:
        name: oauth-creds
        key: id
    clientSecret:
      name: oauth-creds
      key: secret
    tokenUrl: https://auth.corp.local/token
  # Дополнительная защита:
  tlsConfig:
    ca:
      secret:
        name: api-ca
        key: ca.crt
    # Верификация сертификата сервера
    insecureSkipVerify: false
```

**Валидация:**

```bash
# Проверка, что Secret существует и имеет правильный ключ
kubectl get secret oauth-creds -n monitoring -o jsonpath='{.data.id}' | base64 -d

# Проверка сгенерированного конфига
kubectl get secret prometheus-main-generated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | grep -A10 "secure-api-scrape"
```

### ScrapeConfig с Basic Auth и TLS

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: basic-auth-target
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["prometheus-exporter.corp.local:9090"]
  basicAuth:
    username:
      name: basic-auth-secret
      key: username
    password:
      name: basic-auth-secret
      key: password
  tlsConfig:
    cert:
      secret:
        name: client-cert
        key: tls.crt
    keySecret:
      name: client-cert
      key: tls.key
    ca:
      secret:
        name: ca-bundle
        key: ca.crt
```

### ScrapeConfig с Authorization Header

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata:
  name: api-key-scrape
  namespace: monitoring
spec:
  staticConfigs:
    - targets: ["metrics-api.corp.local"]
  authorization:
    type: Bearer
    credentials:
      name: api-key-secret
      key: token
  # Или через credentialsFile (Prometheus 2.29+)
  # credentialsFile: /etc/prometheus/secrets/api-token/token
```

### ServiceMonitor с mTLS

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-service
  namespace: prod
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app: secure-api
  endpoints:
    - port: metrics
      path: /metrics
      scheme: https
      tlsConfig:
        ca:
          secret:
            name: service-ca
            key: ca.crt
        cert:
          secret:
            name: client-cert
            key: tls.crt
        keySecret:
          name: client-cert
          key: tls.key
      # Отключение проверки hostname (если CN != service DNS)
      # insecureSkipVerify: false
```

### PodMonitor с Basic Auth

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: stateful-app
  namespace: prod
  labels:
    release: monitoring
spec:
  selector:
    matchLabels:
      app: postgres-exporter
  podMetricsEndpoints:
    - port: metrics
      path: /metrics
      basicAuth:
        username:
          name: postgres-metrics-auth
          key: username
        password:
          name: postgres-metrics-auth
          key: password
```

### AlertmanagerConfig — секреты для получателей

Все чувствительные данные в `AlertmanagerConfig` должны храниться в Kubernetes Secrets:

```yaml
apiVersion: monitoring.coreos.com/v1beta1
kind: AlertmanagerConfig
metadata:
  name: slack-config
  namespace: monitoring
spec:
  route:
    groupBy: ['alertname']
    groupWait: 30s
    groupInterval: 5m
    receiver: 'slack'
  receivers:
    - name: 'slack'
      slackConfigs:
        - channel: '#monitoring'
          apiURL:
            name: slack-webhook
            key: url
    - name: 'pagerduty'
      pagerdutyConfigs:
        - routingKey:
            name: pagerduty-secret
            key: routing-key
    - name: 'webhook'
      webhookConfigs:
        - url: 'https://hooks.corp.local/alerts'
          httpConfig:
            authorization:
              type: Bearer
              credentials:
                name: webhook-secret
                key: token
```

Создание секретов:

```bash
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/xxx/yyy/zzz' \
  -n monitoring

kubectl create secret generic pagerduty-secret \
  --from-literal=routing-key='xxx-xxx-xxx-xxx' \
  -n monitoring

kubectl create secret generic webhook-secret \
  --from-literal=token='super-secret-token' \
  -n monitoring
```

### Prometheus Web UI — защита паролем

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  version: v3.12.0
  web:
    tlsConfig:
      cert:
        secret:
          name: prometheus-tls
          key: tls.crt
      keySecret:
        name: prometheus-tls
        key: tls.key
    httpConfig:
      basicAuth:
        username:
          name: prometheus-basic-auth
          key: username
        password:
          name: prometheus-basic-auth
          key: password
```

Создание секрета для Basic Auth:

```bash
# Генерация хеша пароля через htpasswd
htpasswd -nb admin 'StrongP@ssw0rd!' | base64 -w0
# → YWRtaW46JGFwcjEkRDN4eExC...

kubectl create secret generic prometheus-basic-auth \
  --from-literal=username='admin' \
  --from-literal=password='$2a$12$...' \
  -n monitoring
```

### Безопасный доступ к объектному хранилищу Thanos

Конфигурация доступа к S3-совместимому хранилищу (MinIO, Ceph RGW, Garage) через Secret:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
  namespace: monitoring
spec:
  thanos:
    version: v0.41.0
    objectStorageConfig:
      name: thanos-objstore-config
      key: thanos.yaml
```

Создание секрета с конфигурацией:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: thanos-objstore-config
  namespace: monitoring
type: Opaque
stringData:
  thanos.yaml: |
    type: s3
    config:
      bucket: "thanos-metrics"
      endpoint: "minio.corp.local:9000"
      access_key: "minioadmin"
      secret_key: "minioadmin"
      insecure: false
      # Для MinIO:
      # signature_version2: false
```

> **Важно:** В production избегайте статических ключей `access_key`/`secret_key`. Для on-prem S3-совместимых хранилищ (MinIO, Ceph RGW) рассмотрите использование STS (Security Token Service) или внешнего KMS для выдачи краткоживущих credentials.

### Автоматическая ротация через External Secrets

Сценарий, при котором пароль Alertmanager обновляется во внешнем хранилище и автоматически доставляется в мониторинг:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: alertmanager-vault-sync
  namespace: monitoring
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: alertmanager-main-creds
  data:
    - secretKey: slack_url
      remoteRef:
        key: secret/monitoring/alerts
        property: slack_webhook
```

---

## Рекомендации по безопасности

### Защита на уровне инфраструктуры

1.  **Encryption at Rest:** Обязательное включение шифрования `etcd` в Kubernetes через `EncryptionConfiguration` с использованием KMS плагина.
2.  **Minimal RBAC:** Ограничение прав `watch/list` на секреты в неймспейсе `monitoring`. Только ServiceAccount оператора должен иметь доступ к чтению конфигурационных секретов.
3.  **Network Isolation:** Использование Network Policies для запрета доступа к портам Prometheus/Alertmanager извне кластера без авторизации.

### Эксплуатация и Hardening

1.  **Read-Only Mounts:** При монтировании секретов в `spec.secrets` всегда используйте `readOnly: true` в настройках контейнера (через `securityContext`).
2.  **Исключение Env Vars:** Никогда не передавайте секреты через переменные окружения, так как они логируются и доступны через `/proc`. Используйте только файловое монтирование.
3.  **Immutable Secrets:** Для TLS-сертификатов и статических ключей используйте `immutable: true` в Secret.
4.  **Аудит ротации:** Настройте мониторинг метрики `prometheus_config_last_reload_success_timestamp_seconds` для подтверждения успешного применения новых секретов.
5.  **Размер Secret:** Мониторьте размер сгенерированных Secret. При превышении 800 KiB — принимайте меры (шардирование, ScrapeConfig).

### RBAC для секретов мониторинга

Секреты в неймспейсе `monitoring` должны быть изолированы:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: monitoring
  name: operator-secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
  # Ограничение до конкретных секретов (опционально):
  # resourceNames: ["prometheus-main-generated", "alertmanager-main-generated"]

---
# Запрет доступа к секретам для неавторизованных SA
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: monitoring
  name: operator-secret-reader-binding
subjects:
- kind: ServiceAccount
  name: prometheus-operator
  namespace: monitoring
roleRef:
  kind: Role
  name: operator-secret-reader
  apiGroup: rbac.authorization.k8s.io
```

**Проверка прав:**

```bash
# Проверка прав оператора
kubectl auth can-i get secrets --namespace=monitoring \
  --as=system:serviceaccount:monitoring:prometheus-operator

# Проверка, что другие SA не имеют доступа
kubectl auth can-i get secret/alertmanager-main-generated \
  --namespace=monitoring \
  --as=system:serviceaccount:prod:my-app
# → no
```

---

## Мониторинг и аудит секретов

### Метрики Prometheus Operator

| Метрика | Описание |
|:---|:---|
| `prometheus_config_last_reload_success_timestamp_seconds` | Время последнего успешного reload конфигурации |
| `prometheus_config_last_reload_successful` | Бинарный флаг успешности (1 = успех) |
| `prometheus_operator_reconcile_operations_total` | Количество операций reconciliation |

### Алерты на проблемы с секретами

```yaml
groups:
- name: prometheus-operator-secrets
  rules:
  - alert: PrometheusConfigReloadFailure
    expr: prometheus_config_last_reload_successful == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Prometheus не может применить конфигурацию"
      description: "Config-reloader не может загрузить конфиг. Проверьте права на Secret и синтаксис YAML."

  - alert: PrometheusSecretTooLarge
    expr: |
      (kube_secret_size_bytes{namespace="monitoring"} / 1024 / 1024) > 0.8
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Secret превышает 80% лимита (1MB)"
      description: "Секрет {{ $labels.name }} имеет размер {{ $value }}MB. Риск превышения лимита etcd."

  - alert: AlertmanagerConfigReloadFailure
    expr: alertmanager_config_last_reload_successful == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Alertmanager не может применить конфигурацию"
```

### Аудит доступа к секретам

Настройте Audit Policy для отслеживания операций с секретами в неймспейсе мониторинга:

```yaml
# /etc/kubernetes/audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
- level: RequestResponse
  resources:
  - group: ""
    resources: ["secrets"]
  namespaces: ["monitoring"]
  # Логирование операций чтения:
  # verbs: ["get", "list", "watch"]
```

Запросы к Audit Logs:

```bash
# Все операции чтения секретов в monitoring
kubectl logs -n kube-system kube-apiserver-master -f \
  | jq 'select(.verb in ["get","list","watch"] and .objectRef.resource == "secrets" and .objectRef.namespace == "monitoring")'

# Создание/изменение секретов
kubectl logs -n kube-system kube-apiserver-master -f \
  | jq 'select(.verb in ["create","update","patch"] and .objectRef.resource == "secrets" and .objectRef.namespace == "monitoring")'
```

---

## Диагностика и устранение неполадок

### Типичные ошибки

**1. Config-reloader не перезагружает конфигурацию:**

```bash
# Симптом: Prometheus не видит новые цели после обновления ServiceMonitor

# Диагностика
kubectl logs -n monitoring prometheus-main-0 -c config-reloader --tail=50

# Распространенные причины:
# - "error reloading configuration": ошибка в promtool check config
# - "secret not found": RBAC или отсутствие Secret
# - "checksum mismatch": Secret изменен, но config-reloader не видит изменения

# Решение: проверить права на Secret
kubectl auth can-i get secret/prometheus-main-generated \
  --namespace=monitoring \
  --as=system:serviceaccount:monitoring:prometheus-operator
```

**2. Secret превысил лимит 1MB:**

```bash
# Симптом: Operator возвращает ошибку "Secret too large"

# Диагностика
kubectl get secret prometheus-main -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip | wc -c

# Решение: включить шардирование
# spec:
#   shards: 3
```

**3. Секрет не обновляется после изменения:**

```bash
# Симптом: Prometheus использует старое значение секрета

# Если секрет смонтирован через subPath - обновление не произойдет
# Решение: пересоздать Pod или изменить способ монтирования
kubectl delete pod prometheus-main-0 -n monitoring
```

**4. RBAC: доступ запрещен к сгенерированному Secret:**

```bash
# Симптом: "secrets is forbidden"

# Решение: добавить права в ClusterRole оператора
kubectl get clusterrole prometheus-operator -o yaml | grep -A5 secrets
```

**5. Ошибка EncryptionConfiguration:**

```bash
# Симптом: "failed to decode secret"

# Диагностика
kubectl logs -n kube-system kube-apiserver-master | grep -i kms

# Проверка доступности KMS
ETCDCTL_API=3 etcdctl endpoint health --write-out=table
```

### Команды для отладки секретов мониторинга

```bash
# Просмотр всех секретов в monitoring namespace
kubectl get secrets -n monitoring

# Декодирование сгенерированного конфига Prometheus
kubectl get secret prometheus-main-generated -n monitoring \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip

# Проверка, какие Pod используют конкретный Secret
kubectl get pods -n monitoring -o json \
  | jq '.items[] | select(.spec.volumes[]?.secret.secretName == "oauth-creds") | .metadata.name'

# Проверка использований секрета через env
kubectl get pods -n monitoring -o json \
  | jq '.items[] | select(.spec.containers[].envFrom[]?.secretRef.name == "oauth-creds") | .metadata.name'

# Проверка размера всех секретов в monitoring
kubectl get secrets -n monitoring -o json \
  | jq '.items[] | {name: .metadata.name, size: (.data | to_entries | map(.value | length) | add)}' \
  | sort-by(.size) | reverse

# Просмотр audit logs для секретов
kubectl logs -n kube-system kube-apiserver-master -f \
  | jq 'select(.objectRef.resource == "secrets" and .objectRef.namespace == "monitoring")'
```

---

## Дополнительная информация

- **[Безопасность (Главная)](./index.md)** — архитектура защиты стека.
- **[Контроль доступа](./access_control.md)** — RBAC и NetworkPolicy для компонентов мониторинга.
- **[Внешние менеджеры секретов](../../../../Kubernetes/Base/secrets/external_managers.md)** — интеграция с Vault, ESO, CSI.
- **[Alertmanager CRD](../crd/alertmanager.md)** — управление секретами Alertmanager.
- **[AlertmanagerConfig CRD](../crd/alertmanagerconfig.md)** — секреты для получателей алертов.
- **[Prometheus CRD](../crd/prometheus.md)** — ограничение размера Secret и troubleshooting.
- **[Безопасность Secret в Kubernetes](../../../../Kubernetes/Base/secrets/security.md)** — общие принципы и RBAC.
