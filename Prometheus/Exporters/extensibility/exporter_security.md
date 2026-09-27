# Безопасность экспортеров Prometheus

## Определения

**Управление секретами (Secrets Management)** — практика безопасного хранения и передачи учетных данных (пароли API ключи, токены) экспортерам: через Kubernetes Secrets, HashiCorp Vault, переменные окружения. Никогда не используйте лейблы метрик или командную строку для передачи секретов.

**Сетевая изоляция** — ограничение сетевого доступа к экспортерам через NetworkPolicy (Kubernetes), iptables (Linux) или Security Groups (облако). Экспортеры не должны быть доступны из публичного интернета.

**Minimal privileges** — принцип минимальных привилегий: экспортер запускается от непривилегированного пользователя, имеет доступ только к необходимым ресурсам, не требует root-доступа.

**mTLS (mutual TLS)** — двусторонняя аутентификация по TLS: и Prometheus, и экспортер представляют клиентские сертификаты. Используется для защиты scrape-трафика в production.

**См. также:** [Безопасность Prometheus](../../security.md), [Создание собственных экспортеров](./custom_exporters.md), [Kubernetes — Secrets](../../kubernetes/operator/Security/secrets_best_practices.md).

## Основные концепции

### Управление секретами для экспортеров

Экспортеры часто нуждаются в учетных данных для опроса целевых систем (БД, API). Способ передачи секретов зависит от среды развертывания.

#### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-exporter-credentials
  namespace: databases
type: Opaque
stringData:
  DATA_SOURCE_NAME: "postgresql://exporter:StrongPassword123!@localhost:5432/postgres?sslmode=disable"

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-exporter
spec:
  template:
    spec:
      containers:
        - name: exporter
          image: prometheuscommunity/postgres-exporter:v0.15.0
          env:
            - name: DATA_SOURCE_NAME
              valueFrom:
                secretKeyRef:
                  name: postgres-exporter-credentials
                  key: DATA_SOURCE_NAME
```

#### External Secrets Operator (интеграция с Vault/AWS/Azure)

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: postgres-exporter-credentials
  namespace: databases
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: ClusterSecretStore
  target:
    name: postgres-exporter-credentials
  data:
    - secretKey: DATA_SOURCE_NAME
      remoteRef:
        key: secret/data/monitoring/postgres-exporter
        property: dsn

---
apiVersion: v1
kind: Secret
metadata:
  name: postgres-exporter-credentials
type: Opaque
stringData:
  DATA_SOURCE_NAME: "postgresql://exporter:$(vault:secret/data/monitoring/postgres-exporter#dsn)"
```

#### HashiCorp Vault (без K8s)

```bash
# Запись секрета в Vault
vault kv put secret/monitoring/postgres-exporter \
  dsn="postgresql://exporter:StrongPassword123!@db-host:5432/postgres?sslmode=require"

# Запуск экспортера с Vault Agent
vault agent -vault-addr=https://vault.internal:8200 \
  -vault-role=postgres-exporter \
  -template=":/tmp/dsn.txt:{{ with secret \"secret/monitoring/postgres-exporter\" }}{{ .Data.dsn }}{{ end }}"

# В systemd unit:
# EnvironmentFile=/tmp/dsn.txt
```

#### Ansible Vault (без Kubernetes)

```yaml
# inventory/group_vars/databases.yml
vault_db_password: "{{ vault_postgres_exporter_password }}"

# templates/postgres-exporter.env.j2
DATA_SOURCE_NAME="postgresql://exporter:{{ vault_db_password }}@localhost:5432/postgres?sslmode=disable"

# tasks/main.yml
- name: Создание файла окружения
  template:
    src: postgres-exporter.env.j2
    dest: /etc/default/postgres-exporter
    owner: prometheus
    group: prometheus
    mode: '0640'
```

### Аутентификация экспортера к целевым системам

#### PostgreSQL

```sql
-- Создание пользователя для экспортера
CREATE USER exporter WITH PASSWORD 'StrongPassword123!';
GRANT pg_monitor TO exporter;

-- Ограничение доступа (только нужные запросы)
ALTER USER exporter SET statement_timeout = '5s';
```

```yaml
# pg_hba.conf — разрешить доступ только с localhost
host all exporter 127.0.0.1/32 scram-sha-256

# pg_hba.conf — разрешить доступ с Sidecar (если в K8s)
host all exporter 10.0.0.0/8 scram-sha-256
```

#### MySQL

```sql
-- Создание пользователя для экспортера
CREATE USER 'exporter'@'127.0.0.1' IDENTIFIED BY 'StrongPassword123!';
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'127.0.0.1';

-- Ограничение ресурсов
ALTER USER 'exporter'@'127.0.0.1' WITH MAX_USER_CONNECTIONS 3;
```

#### Redis

```yaml
# redis.conf — ACL для экспортера
user exporter on >StrongPassword123! ~* +info +ping +time +dbstats +memory +latency
```

### Сетевая изоляция

#### Kubernetes NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape-exporter
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: blackbox-exporter
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Разрешаем входящий трафик только от Prometheus
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9115
          protocol: TCP
  egress:
    # Разрешаем DNS
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    # Разрешаем HTTP/HTTPS к целям (для blackbox)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 80
          protocol: TCP
        - port: 443
          protocol: TCP
```

#### iptables (Linux)

```bash
# Разрешаем scrape только от Prometheus сервера
iptables -A INPUT -p tcp --dport 9101 -s 10.0.0.100 -j ACCEPT
iptables -A INPUT -p tcp --dport 9101 -s 10.0.0.101 -j ACCEPT
iptables -A INPUT -p tcp --dport 9101 -j DROP
```

### TLS и mTLS

#### self-signed сертификаты для тестов

```bash
# Генерация CA
openssl genrsa -out ca.key 4096
openssl req -new -x509 -days 365 -key ca.key -out ca.crt \
  -subj "/CN=Monitoring CA"

# Генерация серверного сертификата
openssl genrsa -out server.key 4096
openssl req -new -key server.key -out server.csr \
  -subj "/CN=exporter.monitoring.svc"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 365

# Генерация клиентского сертификата (для Prometheus)
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr \
  -subj "/CN=prometheus"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out client.crt -days 365
```

#### web-config.yml для экспортера (mTLS)

```yaml
tls_server_config:
  cert_file: /etc/exporter/tls/server.crt
  key_file: /etc/exporter/tls/server.key
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/exporter/tls/ca.crt
  min_version: TLS13
  cipher_suites:
    - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
    - TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305
```

#### prometheus.yml — scrape с mTLS

```yaml
scrape_configs:
  - job_name: 'myapp-exporter'
    scheme: https
    tls_config:
      cert_file: /etc/prometheus/tls/client.crt
      key_file: /etc/prometheus/tls/client.key
      ca_file: /etc/prometheus/tls/ca.crt
    static_configs:
      - targets: ['exporter.monitoring.svc:9101']
```

### Systemd hardening

```ini
# /etc/systemd/system/myapp-exporter.service
[Unit]
Description=MyApp Exporter
After=network.target

[Service]
Type=simple
User=prometheus
Group=prometheus
ExecStart=/usr/local/bin/myapp-exporter

# Безопасность
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
ReadWritePaths=/var/lib/myapp-exporter
CapabilityBoundingSet=
SystemCallFilter=@system-service
SystemCallArchitectures=native
RestrictNamespaces=yes
RestrictSUIDSGID=yes
MemoryDenyWriteExecute=yes
LockPersonality=yes

# Ресурсы
LimitNOFILE=65536
CPUQuota=50%
MemoryMax=256M

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Docker hardening

```dockerfile
FROM golang:1.24-alpine AS builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 go build -o exporter .

FROM alpine:latest
# Минимальный пользователь
RUN addgroup -g 1001 -S exporter && adduser -u 1001 -S exporter -G exporter
COPY --from=builder --chown=exporter:exporter /app/exporter /usr/local/bin/exporter
USER exporter
EXPOSE 9101
ENTRYPOINT ["exporter"]
```

```bash
docker run -d \
  --name myapp-exporter \
  --read-only \
  --cap-drop ALL \
  --cap-add NET_BIND_SERVICE \
  --no-new-privileges \
  --security-opt seccomp=runtime-default \
  --memory 128m \
  --cpus 0.5 \
  -p 9101:9101 \
  myapp-exporter:latest
```

## Практические сценарии

### Сценарий 1: PostgreSQL exporter с Vault в Kubernetes

```yaml
# 1. SecretStore (подключение к Vault)
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: databases
spec:
  provider:
    vault:
      server: "https://vault.internal:8200"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "postgres-exporter"
          serviceAccountRef:
            name: "postgres-exporter-sa"

---
# 2. ExternalSecret (синхронизация из Vault)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: postgres-exporter-credentials
  namespace: databases
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: postgres-exporter-credentials
    creationPolicy: Owner
  data:
    - secretKey: data_source_name
      remoteRef:
        key: secret/data/monitoring/postgres
        property: dsn

---
# 3. Deployment экспортера
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-exporter
  namespace: databases
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres-exporter
  template:
    metadata:
      labels:
        app: postgres-exporter
    spec:
      serviceAccountName: postgres-exporter-sa
      containers:
        - name: exporter
          image: prometheuscommunity/postgres-exporter:v0.15.0
          env:
            - name: DATA_SOURCE_NAME
              valueFrom:
                secretKeyRef:
                  name: postgres-exporter-credentials
                  key: data_source_name
          ports:
            - containerPort: 9187
          securityContext:
            runAsNonRoot: true
            runAsUser: 65534
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            seccompProfile:
              type: RuntimeDefault
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
```

### Сценарий 2: Network Policy для изоляции экспортеров

```yaml
# Default deny для namespace monitoring
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

---
# Разрешаем scrape от Prometheus
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/component: exporter
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9100
          protocol: TCP
        - port: 9115
          protocol: TCP
        - port: 9187
          protocol: TCP

---
# Разрешаем DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
```

### Сценарий 3: Проверка безопасности экспортера

```bash
#!/bin/bash
# security-audit.sh — проверка безопасности экспортера
set -euo pipefail

EXPORTER_POD=$1
NAMESPACE=${2:-monitoring}

echo "=== Аудит безопасности экспортера: $EXPORTER_POD ==="

# 1. Проверка пользователя
USER=$(kubectl exec -n $NAMESPACE $EXPORTER_POD -- whoami 2>/dev/null || echo "root")
if [ "$USER" = "root" ]; then
    echo "FAIL: экспортер запущен от root"
else
    echo "OK: пользователь $USER"
fi

# 2. Проверка readOnlyRootFilesystem
RO=$(kubectl get pod -n $NAMESPACE $EXPORTER_POD -o jsonpath='{.spec.containers[0].securityContext.readOnlyRootFilesystem}')
if [ "$RO" = "true" ]; then
    echo "OK: readOnlyRootFilesystem=true"
else
    echo "FAIL: filesystem доступен на запись"
fi

# 3. Проверка capabilities
CAPS=$(kubectl get pod -n $NAMESPACE $EXPORTER_POD -o jsonpath='{.spec.containers[0].securityContext.capabilities.drop}')
echo "OK: capabilities drop=$CAPS"

# 4. Проверка seccomp
SECCOMP=$(kubectl get pod -n $NAMESPACE $EXPORTER_POD -o jsonpath='{.spec.containers[0].securityContext.seccompProfile.type}')
if [ "$SECCOMP" = "RuntimeDefault" ] || [ "$SECCOMP" = "Localhost" ]; then
    echo "OK: seccompProfile=$SECCOMP"
else
    echo "WARN: seccomp не настроен"
fi

# 5. Проверка NetworkPolicy
NP=$(kubectl get networkpolicy -n $NAMESPACE --no-headers 2>/dev/null | wc -l)
if [ "$NP" -gt 0 ]; then
    echo "OK: $NP NetworkPolicy активны"
else
    echo "WARN: NetworkPolicy не найдены"
fi

# 6. Проверка секретов в env
SECRETS=$(kubectl get pod -n $NAMESPACE $EXPORTER_POD -o json | \
  jq -r '.spec.containers[0].env[]? | select(.value != null) | select(.value | test("password|secret|token"; "i")) | .name' 2>/dev/null || true)
if [ -n "$SECRETS" ]; then
    echo "FAIL: секреты в открытом виде: $SECRETS"
else
    echo "OK: секреты не передаются через env"
fi

# 7. Проверка портов
PORTS=$(kubectl get pod -n $NAMESPACE $EXPORTER_POD -o jsonpath='{.spec.containers[0].ports[*].containerPort}')
echo "OK: порты $PORTS"

echo "=== Аудит завершен ==="
```

## Дополнительная информация

### Типичные ошибки безопасности

| Ошибка | Риск | Решение |
|:---|:---|:---|
| Секреты в command-line args | `/proc/PID/cmdline` доступен другим пользователям | Используйте env или файлы |
| Секреты в лейблах метрик | Данные видны в TSDB и Grafana | Никогда не кладите секреты в лейблы |
| Экспортер от root | Полный доступ к системе | `runAsUser: 65534`, `runAsNonRoot: true` |
| Нет NetworkPolicy | Любой pod может скрейпить экспортер | Default deny + explicit allow |
| TLS не настроен | Man-in-the-middle, data leak | mTLS для scrape, TLS для API |
| Нет resource limits | DoS через потребление ресурсов | CPU/Memory limits |
| Старые зависимости | Известенные CVE | Регулярно обновляйте образы |

### Чек-лист безопасности

1. **Секреты:** Передаются через Kubernetes Secrets / Vault / env, не через лейблы или command-line
2. **Пользователь:** Экспортер запущен от непривилегированного пользователя (65534/nobody)
3. **Файловая система:** `readOnlyRootFilesystem: true`
4. **Capabilities:** `drop: ["ALL"]`, `allowPrivilegeEscalation: false`
5. **Seccomp:** `seccompProfile: RuntimeDefault` или `Localhost`
6. **NetworkPolicy:** Default deny + explicit allow для scrape и DNS
7. **TLS:** mTLS для scrape-трафика в production
8. **Resource limits:** CPU и Memory limits установлены
9. **Обновления:** Регулярное обновление образов экспортера
10. **Аудит:** Периодическая проверка security context и NetworkPolicy

### CIS Benchmark для контейнеров ( применимо к экспортерам)

| Параметр | Значение | Пункт CIS |
|:---|:---|:---|
| Run as non-root | `runAsNonRoot: true` | 5.2.6 |
| Read-only root filesystem | `readOnlyRootFilesystem: true` | 5.2.7 |
| No privilege escalation | `allowPrivilegeEscalation: false` | 5.2.5 |
| Drop all capabilities | `drop: ["ALL"]` | 5.2.8 |
| Seccomp profile | `RuntimeDefault` или `Localhost` | 5.7.2 |
| Non-default namespace | Не使用 default/kube-system | 5.1.1 |
| Resource quotas | CPU/Memory limits | 5.2.3 |

**См. также:**
- [Безопасность Prometheus](../../security.md) — безопасность сервера Prometheus
- [Kubernetes — Secrets Best Practices](../../kubernetes/operator/Security/secrets_best_practices.md) — управление секретами в K8s
- [Kubernetes — Access Control](../../kubernetes/operator/Security/access_control.md) — RBAC для Operator
- [Надежность экспортеров](./exporter_reliability.md) — HA, graceful degradation, metamonitoring
- [Kubernetes паттерны](./k8s_exporter_patterns.md) — deployment patterns в K8s
