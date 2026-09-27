# Mimir: Security Hardening

## 1. Определения

**Security Hardening** — процесс укрепления безопасности Mimir-кластера путем ограничения доступа, шифрования трафика, настройки RBAC и изоляции тенантов. Mimir обрабатывает критичные метрики инфраструктуры — компрометация данных может привести к утечке информации о бизнес-процессах и инфраструктуре.

## 2. Теоретический блок

### Угрозы для Mimir

| Угроза | Описание | Влияние |
|--------|----------|---------|
| **Unauthorized Read** | Чтение метрик несанкционированным тенантом | Утечка данных о бизнес-процессах |
| **Ingestion Abuse** | Заполнение хранилища вредоносными данными | DoS, рост стоимости |
| **Tampering** | Изменение или удаление метрик | Потеря данных мониторинга |
| **Network Interception** | Перехват трафика между компонентами | Утечка данных |
| **Compromised Component** | Компрометация одного микросервиса |ateral movement к другим компонентам |

### Модель безопасности Mimir

```
Prometheus/Alloy → [TLS + Auth] → Distributor → [mTLS] → Ingester
                                                      ↓
Grafana → [TLS + Auth] → Query Frontend → [mTLS] → Querier
                                                      ↓
                                               Store-Gateway → [TLS] → S3/MinIO
```

## 3. Практический блок

### mTLS между компонентами

```yaml
# mimir-config.yaml
mimir:
  structuredConfig:
    server:
      # Включение TLS для HTTP
      http_tls_enabled: true
      http_tls_cert_path: /etc/mimir/tls/tls.crt
      http_tls_key_path: /etc/mimir/tls/tls.key

      # Включение TLS для gRPC
      grpc_tls_enabled: true
      grpc_tls_cert_path: /etc/mimir/tls/tls.crt
      grpc_tls_key_path: /etc/mimir/tls/tls.key
      grpc_tls_client_ca_path: /etc/mimir/tls/ca.crt
```

**Создание сертификатов через cert-manager:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: mimir-server-tls
  namespace: mimir
spec:
  secretName: mimir-server-tls
  duration: 8760h  # 1 год
  issuerRef:
    name: mimir-ca
    kind: Issuer
  dnsNames:
    - "*.mimir.svc"
    - "mimir-querier.mimir.svc"
    - "mimir-distributor.mimir.svc"
    - "mimir-ingester.mimir.svc"
```

### Аутентификация Prometheus → Mimir

**Вариант 1: OIDC (рекомендуется для production)**

```yaml
mimir:
  structuredConfig:
    auth:
      auth_enabled: true

    # Внешняя аутентификация через nginx/Envoy
    # nginx performs OIDC validation, добавляет X-Scope-OrgID
```

**Вариант 2: Static tokens (для простых сред)**

```yaml
mimir:
  structuredConfig:
    auth:
      auth_enabled: true

# На стороне Prometheus:
remote_write:
  - url: "http://mimir-distributor:8080/api/v1/push"
    headers:
      X-Scope-OrgID: "production"
```

### NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mimir-internal
  namespace: mimir
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: mimir
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Distributor: принимает от Prometheus/Alloy
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/component: prometheus
      ports:
        - protocol: TCP
          port: 8080
    # Query Frontend: принимает от Grafana
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
      ports:
        - protocol: TCP
          port: 9009
    # Внутренний трафик между компонентами Mimir
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: mimir
  egress:
    # Доступ к S3/MinIO
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: minio
      ports:
        - protocol: TCP
          port: 9000
    # Доступ к Kafka
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: kafka
      ports:
        - protocol: TCP
          port: 9092
    # DNS
    - to: []
      ports:
        - protocol: UDP
          port: 53
```

### RBAC для ServiceAccount'ов

```yaml
# Минимальные права для компонентов Mimir
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: mimir-minimal
  namespace: mimir
rules:
  # Только чтение ConfigMap'ов (для runtime-config)
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
  # Только чтение Secrets (для TLS сертификатов)
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
  # Pod annotations (для service discovery)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
```

### Изоляция тенантов

```yaml
mimir:
  structuredConfig:
    multitenancy_enabled: true
    auth_enabled: true

    limits:
      # Лимиты на тенанта предотвращают DoS
      ingestion:
        ingestion_rate: 100000
        ingestion_burst_size: 200000
        max_series_per_user: 1000000
      query:
        max_query_series: 50000
        query_timeout: 3m
```

**Проверка изоляции:**

```bash
# Тенант A не должен видеть данные тенанта B
curl -s -H "X-Scope-OrgID: tenant-a" \
  "http://mimir-query-frontend:9009/prometheus/api/v1/query?query=up" | jq '.data.result | length'

curl -s -H "X-Scope-OrgID: tenant-b" \
  "http://mimir-query-frontend:9009/prometheus/api/v1/query?query=up" | jq '.data.result | length'
# → Разные результаты
```

### Шифрование данных в S3

```yaml
# MinIO: включение шифрования на уровне бакета
mc anonymous set-json '{"Statement":[{"Action":"s3:GetObject","Effect":"Allow","Principal":{"AWS":["*"]},"Resource":"arn:aws:s3:::mimir-blocks/*","Sid":""}]}' mimir/mimir-blocks

# Или через configuration: SSE-S3 (автоматическое шифрование)
# MinIO по умолчанию поддерживает шифрование на уровне диска
```

### Audit Logging

```yaml
# Включение audit logging в Mimir
mimir:
  structuredConfig:
    server:
      log_level: info

    # Логирование всех API-запросов
    api:
      audit_logging_enabled: true
```

### Проверка безопасности

```bash
# 1. Проверка что аутентификация включена
curl -s http://mimir-distributor:8080/api/v1/push
# → Должен вернуть 401/403 без заголовка X-Scope-OrgID

# 2. Проверка TLS
curl -k https://mimir-distributor:8080/metrics
# → Должен работать только с валидным сертификатом

# 3. Проверка NetworkPolicy
kubectl exec -n mimir test-pod -- curl -s http://mimir-distributor:8080/metrics
# → Должен быть заблокирован если test-pod не в.allowed list

# 4. Проверка лимитов тенанта
curl -s -H "X-Scope-OrgID: test-tenant" \
  -X POST http://mimir-distributor:8080/api/v1/push \
  --data-binary @large-payload.pb
# → Должен вернуть 429 при превышении лимита
```

## 4. Дополнительная информация

### См. также
- [Mimir: Обзор](./mimir_overview.md) — базовые настройки безопасности
- [Prometheus Security](../Prometheus/security.md) — безопасность Prometheus
- [Kubernetes Network Policies](../Kubernetes/Networking/Network/) — общие концепции NetworkPolicy
- [cert-manager](../Kubernetes/ToolsUtilities/cert_manager/) — управление сертификатами
- [Multi-Region Deployment](./mimir_multi_region.md) — безопасность в multi-region среде

### Официальные ресурсы
- **[Mimir Security](https://grafana.com/docs/mimir/latest/configure/configure-tls/)** — настройка TLS
- **[Mimir Authentication](https://grafana.com/docs/mimir/latest/configure/configure-authentication/)** — аутентификация
