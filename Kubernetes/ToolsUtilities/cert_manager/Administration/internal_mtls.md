# Внутренний mTLS с cert-manager

## Определения

**Internal mTLS (внутренний mTLS)** — механизм взаимной аутентификации между сервисами внутри кластера, где каждый сервис предъявляет клиентский сертификат для подключения к другому сервису. В отличие от публичного TLS (односторонний), mTLS требует сертификаты как на сервере, так и на клиенте.

**Service Certificate** — сертификат, подписанный внутренним CA, используемый сервером для предъявления себя клиенту. Обычно содержит SAN вида `<service>.<namespace>.svc.cluster.local`.

**Client Certificate** — сертификат, используемый клиентом для аутентификации перед сервером. Часто используется в паре с server certificate для mTLS.

**SPIFFE ID** — идентификатор сервиса в формате `spiffe://<trust-domain>/<workload>`. Стандарт для идентификации сервисов в распределенных системах. cert-manager может выпускать сертификаты с SPIFFE SAN.

---

## Основные концепции

### Зачем нужен внутренний mTLS

| Сценарий | Без mTLS | С mTLS |
| :--- | :--- | :--- |
| **Database подключения** | Пароль в открытом виде | Клиент аутентифицируется сертификатом |
| **gRPC между сервисами** | Нет аутентификации | Взаимная аутентификация |
| **Message Queue** | Любой может подключиться | Только авторизованные клиенты |
| **API Gateway → Backend** | Доверие по сети | Доверие по сертификату |

### Архитектура внутреннего mTLS

```
┌─────────────────────────────────────────────────────────────┐
│                      Kubernetes Cluster                      │
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │   Frontend    │ ──mTLS──▶   Backend    │                  │
│  │  (client cert)│         │ (server cert)│                  │
│  └──────────────┘         └──────────────┘                  │
│         │                         │                          │
│         └──────────┬──────────────┘                          │
│                    │                                         │
│                    ▼                                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Internal CA (Vault/Step-CA)              │   │
│  │  cert-manager выдаёт сертификаты для mTLS             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: mTLS для PostgreSQL

```yaml
# 1. Issuer для internal mTLS
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: internal-ca
  namespace: database
spec:
  ca:
    secretName: internal-ca-key-pair
---
# 2. Серверный сертификат для PostgreSQL
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: postgres-server
  namespace: database
spec:
  secretName: postgres-server-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - postgres.database.svc.cluster.local
  - postgres-primary.database.svc.cluster.local
  - postgres-replica.database.svc.cluster.local
  usages:
  - server auth
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 720h     # 30 дней
  renewBefore: 168h  # 7 дней
---
# 3. Клиентский сертификат для приложений
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-client
  namespace: production
spec:
  secretName: app-postgres-client-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - app.production.svc.cluster.local
  usages:
  - client auth
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 720h
  renewBefore: 168h
```

**Настройка PostgreSQL для mTLS:**
```sql
-- postgresql.conf
ssl = on
ssl_cert_file = '/tls/tls.crt'
ssl_key_file = '/tls/tls.key'
ssl_ca_file = '/tls/ca.crt'

-- pg_hba.conf
hostssl  all  all  0.0.0.0/0  cert
```

### Сценарий 2: mTLS для gRPC-сервисов

```yaml
# 1. Серверный сертификат
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grpc-server
  namespace: production
spec:
  secretName: grpc-server-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - grpc-service.production.svc.cluster.local
  usages:
  - server auth
  - digital signature
  - key encipherment
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 168h    # 7 дней
  renewBefore: 24h
---
# 2. Клиентский сертификат
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grpc-client
  namespace: production
spec:
  secretName: grpc-client-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  usages:
  - client auth
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 168h
  renewBefore: 24h
```

**Настройка gRPC-клиента (Go):**
```go
creds, err := credentials.NewClientTLSFromFile(
    "tls.crt",
    "tls.key",
    "ca.crt",
)
conn, err := grpc.Dial(
    "grpc-service.production.svc.cluster.local:50051",
    grpc.WithTransportCredentials(creds),
)
```

### Сценарий 3: mTLS для Redis

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: redis-server
  namespace: cache
spec:
  secretName: redis-server-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - redis.cache.svc.cluster.local
  usages:
  - server auth
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 168h
  renewBefore: 24h
```

**Настройка Redis:**
```conf
tls-port 6380
tls-cert-file /tls/tls.crt
tls-key-file /tls/tls.key
tls-ca-cert-file /tls/ca.crt
tls-auth-clients yes
```

### Сценарий 4: mTLS для RabbitMQ

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: rabbitmq-server
  namespace: messaging
spec:
  secretName: rabbitmq-server-tls
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - rabbitmq.messaging.svc.cluster.local
  usages:
  - server auth
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  duration: 168h
  renewBefore: 24h
```

### Сценарий 5: Автоматическая ротация через CSI

```yaml
# CSI Driver монтирует сертификаты в под без сохранения в Secret
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-mtls
  namespace: production
spec:
  secretName: app-mtls  # CSI ignored, ключ не хранится в Secret
  issuerRef:
    name: internal-ca
    kind: Issuer
  dnsNames:
  - app.production.svc.cluster.local
  usages:
  - server auth
  - client auth
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 24h       # Короткий TTL для высокой безопасности
  renewBefore: 6h
---
# Pod с CSI volume
apiVersion: v1
kind: Pod
metadata:
  name: app
  namespace: production
spec:
  containers:
  - name: app
    image: my-app:latest
    volumeMounts:
    - name: tls
      mountPath: /tls
      readOnly: true
  volumes:
  - name: tls
    csi:
      driver: cert-manager.io
      volumeAttributes:
        csi.cert-manager.io/issuer-name: internal-ca
        csi.cert-manager.io/issuer-kind: Issuer
        csi.cert-manager.io/dns-names: "app.production.svc.cluster.local"
        csi.cert-manager.io/duration: "24h"
        csi.cert-manager.io/renew-before: "6h"
```

---

## Дополнительная информация

### Best practices

1. **Короткие TTL:** Для internal mTLS используйте 24–72 часа вместо 90 дней
2. **Rotation Policy:** Всегда `Always` для генерации нового ключа при продлении
3. **SPIFFE ID:** Используйте SPIFFE SAN для идентификации сервисов
4. **CSI Driver:** Для максимальной безопасности используйте CSI (ключ не хранится в etcd)
5. **Network Policy:** Ограничьте mTLS-трафик только необходимыми портами
6. **Мониторинг:** Настройте алерт на `certmanager_certificate_ready_status` для mTLS-сертификатов

### Антипаттерны

| Антипаттерн | Проблема | Решение |
| :--- | :--- | :--- |
| **Длинные TTL для mTLS** | Компрометация ключа →长期 доступ | Короткие TTL (≤72ч) |
| **Один CA на все** | Компрометация → все сервисы | Разные CA для разных уровней |
| **Нет rotation** | Устаревшие ключи | `rotationPolicy: Always` |
| **Хранение ключей в etcd** | Утечка через backup | CSI Driver |

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — общие принципы.
- **[Service Mesh Integration](../Private_CA/service_mesh_integration.md)** — cert-manager как CA для Istio/Linkerd.
- **[Cert-manager: Операции](./operations.md)** — мониторинг и ротация.
- **[gRPC Overview](../../../../Networking/ServicesAndTools/grpc_overview.md)** — настройка gRPC с TLS.
