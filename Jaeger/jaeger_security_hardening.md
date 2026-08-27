# Security Hardening для Jaeger

> **Важно:** Документация описывает **Jaeger v2** (текущая версия).

**Security Hardening для Jaeger** — это комплекс мер по защите инфраструктуры трассировки от несанкционированного доступа, утечек данных и атак. В production-средах Jaeger содержит чувствительные данные о внутренней архитектуре сервисов, поэтому его нельзя оставлять без защиты. В 2026 году стандартом являются mTLS между всеми компонентами, RBAC по принципу наименьших привилегий, NetworkPolicy, аудит доступа и защита секретов.

Общий обзор безопасности: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**.
HA и DR: **[High Availability и DR](./jaeger_high_availability.md)**.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **mTLS (mutual TLS)** | Взаимная TLS-аутентификация: и клиент, и сервер проверяют сертификаты друг друга |
| **RBAC (Role-Based Access Control)** | Управление доступом на основе ролей: кто может выполнять какие действия |
| **NetworkPolicy** | Kubernetes-ресурс для контроля сетевого трафика между подами и неймспейсами |
| **Security Context** | Настройки безопасности пода/контейнера: запуск от non-root, seccomp, AppArmor |
| **Certificate Rotation** | Автоматическая ротация TLS-сертификатов без простоя (через cert-manager) |
| **Audit Logging** | Запись событий доступа к API и изменения конфигурации для compliance |
| **Secret Management** | Управление TLS-ключами, паролями и токенами через Vault, Sealed Secrets или External Secrets |
| **Least Privilege** | Принцип минимальных привилегий: субъект получает только необходимые права |

---

## Базовые концепции

### Угрозы для Jaeger

| Угроза | Влияние | Защита |
| :--- | :--- | :--- |
| **Несанкционированный доступ к трейсам** | Утечка архитектуры, PII, секретов в тегах | mTLS, RBAC, NetworkPolicy |
| **Инъекция спанов** | Подделка данных, обход алертов | mTLS, API-ключи, rate limiting |
| **DoS через Collector** | Отказ в обслуживании, OOM | memory_limiter, HPA, NetworkPolicy |
| **Утечка данных из хранилища** | Кража трейсов из ClickHouse/ES | Шифрование at rest, RBAC БД, аудит |
| **Man-in-the-Middle** | Перехват трейсов в transit | mTLS, TLS 1.3, сертификаты от доверенного CA |

### Модель углубленной защиты (Defense in Depth)

```
┌─────────────────────────────────────────┐
│ 1. Network Layer                        │
│    - NetworkPolicy                       │
│    - Firewall / Security Group           │
├─────────────────────────────────────────┤
│ 2. Transport Layer                       │
│    - mTLS (TLS 1.3)                      │
│    - Certificate Rotation                │
├─────────────────────────────────────────┤
│ 3. Application Layer                     │
│    - RBAC (Kubernetes + DB)              │
│    - API Keys / Bearer Tokens            │
│    - Rate Limiting                       │
├─────────────────────────────────────────┤
│ 4. Data Layer                            │
│    - Encryption at Rest                  │
│    - TTL / Data Retention                │
│    - Audit Logging                       │
└─────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: mTLS между Collector и Storage

**Ситуация:** Необходимо настроить взаимную TLS-аутентификацию между Jaeger Collector и ClickHouse.

```bash
# 1. Генерация CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes -subj "/CN=Jaeger Internal CA"

# 2. Сертификат для ClickHouse
openssl req -newkey rsa:4096 -keyout clickhouse.key -out clickhouse.csr -nodes -subj "/CN=clickhouse.observability.svc"
openssl x509 -req -in clickhouse.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out clickhouse.crt -days 365

# 3. Сертификат для Jaeger Collector
openssl req -newkey rsa:4096 -keyout collector.key -out collector.csr -nodes -subj "/CN=jaeger-collector.observability.svc"
openssl x509 -req -in collector.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out collector.crt -days 365

# 4. Создание Secrets
kubectl create secret tls jaeger-collector-tls \
  --cert=collector.crt \
  --key=collector.key \
  -n observability

kubectl create secret tls clickhouse-tls \
  --cert=clickhouse.crt \
  --key=clickhouse.key \
  -n observability
```

**Конфигурация Collector:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-collector-config
  namespace: observability
data:
  config.yaml: |
    extensions:
      health_check:
      pprof:
        endpoint: :1888
      zpages:
        endpoint: :55679

    receivers:
      otlp:
        protocols:
          grpc:
            endpoint: 0.0.0.0:4317
            tls:
              cert_file: /etc/tls/server.crt
              key_file: /etc/tls/server.key
              client_ca_file: /etc/tls/ca.crt
          http:
            endpoint: 0.0.0.0:4318

    exporters:
      jaeger_storage_exporter:
        trace_storage:
          type: clickhouse
          options:
            clickhouse:
              endpoint: "tcp://clickhouse.observability.svc:9000"
              database: jaeger_v2
              tls:
                enabled: true
                ca_file: /etc/tls/ca.crt
                cert_file: /etc/tls/client.crt
                key_file: /etc/tls/client.key
                insecure_skip_verify: false

    service:
      extensions: [health_check, pprof, zpages]
      pipelines:
        traces:
          receivers: [otlp]
          processors: [memory_limiter, batch]
          exporters: [jaeger_storage_exporter]
```

**Валидация:**

```bash
# Проверка TLS handshake между Collector и ClickHouse
openssl s_client -connect clickhouse.observability.svc:9000 -CAfile ca.crt

# Проверка rejected connections (без сертификата)
openssl s_client -connect clickhouse.observability.svc:9000
# → verify error:num=20:unable to get local issuer certificate
```

### Сценарий 2: Certificate Rotation с cert-manager

**Ситуация:** Необходимо автоматически ротировать TLS-сертификаты для Collector.

```yaml
# cert-manager.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: jaeger-collector-tls
  namespace: observability
spec:
  secretName: jaeger-collector-tls
  duration: 2160h # 90 дней
  renewBefore: 360h # 15 дней до истечения
  subject:
    organizations:
      - observability
  dnsNames:
    - jaeger-collector.observability.svc
    - jaeger-collector.observability
  issuerRef:
    name: ca-issuer
    kind: ClusterIssuer
  privateKey:
    algorithm: RSA
    size: 4096
```

**Валидация:**

1. Применить Certificate: `kubectl apply -f cert-manager.yaml`.
2. Проверить секрет: `kubectl get secret jaeger-collector-tls -n observability`.
3. Убедиться, что сертификат автоматически обновляется: `kubectl describe certificate jaeger-collector-tls -n observability`.

### Сценарий 3: Audit Logging для Query API

**Ситуация:** Необходимо логировать все обращения к Jaeger Query API для compliance.

```yaml
# audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  - level: Metadata
    resources:
      - group: ""
        resources: ["services"]
    verbs: ["get", "list", "watch"]
    omitStages:
      - RequestReceived
```

**Включение аудита в Jaeger Query:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: jaeger-query-config
  namespace: observability
data:
  query.json: |
    {
      "logging": {
        "enabled": true,
        "format": "json",
        "fields": ["timestamp", "level", "message", "traceID", "spanID", "service"],
        "output": "/var/log/jaeger/query-audit.log"
      }
    }
```

**Валидация:**

1. Выполнить запрос к Query API: `curl http://jaeger-query:16686/api/services`.
2. Проверить лог: `kubectl logs -n observability -l app=jaeger-query | grep query-audit`.
3. Убедиться, что запись содержит timestamp, endpoint, результат.

### Сценарий 4: Защита секретов через External Secrets Operator

**Ситуация:** Необходимо хранить TLS-ключи и пароли ClickHouse во внешнем секрет-менеджере.

```yaml
# external-secret.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: jaeger-secrets
  namespace: observability
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: jaeger-secrets
    creationPolicy: Owner
  data:
    - secretKey: clickhouse-password
      remoteRef:
        key: jaeger/clickhouse
        property: password
    - secretKey: tls-cert
      remoteRef:
        key: jaeger/tls
        property: cert
    - secretKey: tls-key
      remoteRef:
        key: jaeger/tls
        property: key
```

**Валидация:**

1. Применить ExternalSecret: `kubectl apply -f external-secret.yaml`.
2. Проверить, что секрет создан: `kubectl get secret jaeger-secrets -n observability`.
3. Убедиться, что данные соответствуют значениям в AWS Secrets Manager.

---

## Лучшие практики

1.  **mTLS повсеместно:** Настройте mTLS между Collector ↔ Storage, Collector ↔ Query, и для всех внешних подключений.
2.  **RBAC по принципу наименьших привилегий:** Collector должен иметь только `get`, `watch`, `list` на pods/nodes/namespaces, а не `cluster-admin`.
3.  **NetworkPolicy как default deny:** Запретите весь трафик по умолчанию и разрешайте только необходимые порты.
4.  **Certificate Rotation:** Используйте cert-manager для автоматической ротации сертификатов без простоя.
5.  **Audit Logging:** Включайте аудит всех запросов к Query API и изменений конфигурации.
6.  **Encryption at Rest:** Настройте шифрование дисков для ClickHouse и Elasticsearch.
7.  **Secrets Management:** Никогда не храните ключи в ConfigMap. Используйте Vault, AWS Secrets Manager или External Secrets Operator.

---

## Очистка окружения

```bash
# Удаление сертификатов
kubectl delete certificate jaeger-collector-tls -n observability
kubectl delete secret jaeger-collector-tls -n observability

# Удаление ExternalSecret
kubectl delete externalsecret jaeger-secrets -n observability

# Удаление RBAC
kubectl delete serviceaccount,clusterrole,clusterrolebinding -n observability -l app=jaeger

# Удаление NetworkPolicy
kubectl delete networkpolicy -n observability -l app=jaeger
```

---

## Дополнительная информация

**Смежные темы:**

* RBAC и ServiceAccount: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* Security Context: **[Интеграция Jaeger с Kubernetes](./jaeger_kubernetes_integration.md)**
* TLS конфигурация: **[Варианты развертывания Jaeger](./jaeger_deployment_options.md)**
* OTLP mTLS: **[OTLP Configuration для Jaeger](./jaeger_otlp_configuration.md)**
* Kubernetes RBAC: **[RBAC в Kubernetes](../Kubernetes/Base/rbac_basics.md)**
* Secret Management: **[External Secrets Operator](../GitOps/external_secrets_operator.md)**

### См. также

* [Jaeger Security Documentation](https://www.jaegertracing.io/docs/latest/security/)
* [OpenTelemetry Collector Security](https://opentelemetry.io/docs/collector/security/)
