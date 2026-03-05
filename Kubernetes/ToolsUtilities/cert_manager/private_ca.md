# Приватный CA для внутренних сервисов

## Определения

**Приватный CA** — собственный центр сертификации, созданный внутри кластера для выпуска сертификатов, доверенных только внутри периметра кластера.

**Отличия от CA кластера:**

| Аспект | Приватный CA | CA кластера |
| :--- | :--- | :--- |
| **Источник доверия** | Self-signed, создан в кластере | Корневой CA Kubernetes (`/etc/kubernetes/pki/ca.crt`) |
| **Сценарий** | Сервисы внутри кластера (mTLS, OpenSearch, Kafka) | Внутренние Ingress, сервисы кластера |
| **Изоляция** | Полный контроль, отдельный namespace | Зависит от жизненного цикла кластера |
| **Сложность** | Низкая | Средняя (требует доступа к master-узлам) |

---

## Основные концепции

### Поток создания приватного CA

```
SelfSigned Issuer → CA Certificate → CA Issuer → Сертификаты сервисов
```

1. **SelfSigned Issuer** — временный источник для подписи корневого CA
2. **CA Certificate** — корневой сертификат с `isCA: true`
3. **CA Issuer** — использует CA-сертификат для подписи остальных сертификатов
4. **Сертификаты сервисов** — выпускаются для конкретных сервисов

---

## Практические сценарии

### Сценарий 1: Базовый приватный CA

**Цель:** Создать CA для выпуска сертификатов внутри namespace.

#### Шаг 1: Создание self-signed Issuer

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca-issuer
  namespace: default
spec:
  selfSigned: {}
```

#### Шаг 2: Создание корневого CA-сертификата

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-root-ca
  namespace: default
spec:
  isCA: true
  commonName: "my-root-ca"
  secretName: my-root-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
    group: cert-manager.io
```

**Параметры:**

| Поле | Значение | Описание |
| :--- | :--- | :--- |
| `isCA` | `true` | Сертификат может подписывать другие сертификаты |
| `commonName` | `my-root-ca` | Имя CA |
| `privateKey.encoding` | `PKCS8` | **Важно для Java-приложений** |

#### Шаг 3: Создание CA Issuer

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: my-ca-issuer
  namespace: default
spec:
  ca:
    secretName: my-root-ca-secret
```

#### Шаг 4: Выпуск сертификата для сервиса

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-service-cert
  namespace: default
spec:
  secretName: my-service-tls
  duration: 8760h  # 1 год
  renewBefore: 720h  # 30 дней
  issuerRef:
    name: my-ca-issuer
    kind: Issuer
  commonName: "my-service"
  dnsNames:
    - my-service
    - my-service.default.svc
    - my-service.default.svc.cluster.local
  privateKey:
    encoding: PKCS8
```

---

### Сценарий 2: Приватный CA для OpenSearch/Elasticsearch

**Особенности:**

- Требуется `encoding: PKCS8` для Java
- Отдельные сертификаты для нод и администратора
- `nodes_dn` и `admin_dn` в конфигурации безопасности

```yaml
# 1. Self-signed Issuer
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca-issuer
  namespace: opensearch
spec:
  selfSigned: {}
---
# 2. CA Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: opensearch-ca
  namespace: opensearch
spec:
  isCA: true
  commonName: "opensearch-ca"
  secretName: opensearch-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
    group: cert-manager.io
---
# 3. CA Issuer
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: opensearch-ca-issuer
  namespace: opensearch
spec:
  ca:
    secretName: opensearch-ca-secret
---
# 4. Сертификат для нод
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: opensearch-nodes-cert
  namespace: opensearch
spec:
  secretName: opensearch-nodes-cert
  duration: 8760h
  issuerRef:
    name: opensearch-ca-issuer
    kind: Issuer
  commonName: "nodes"
  dnsNames:
    - opensearch-cluster-master
    - "*.opensearch-cluster-master"
    - "*.opensearch-nodes"
  privateKey:
    encoding: PKCS8
---
# 5. Сертификат администратора
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: opensearch-admin-cert
  namespace: opensearch
spec:
  secretName: opensearch-admin-cert
  duration: 8760h
  issuerRef:
    name: opensearch-ca-issuer
    kind: Issuer
  commonName: "admin"
  organization:
    - "CN=Admin,O=opensearch"
  privateKey:
    encoding: PKCS8
```

**Использование в securityconfig.yml:**

```yaml
nodes_dn:
  - "CN=nodes"
admin_dn:
  - "CN=admin"
```

---

### Сценарий 3: ClusterIssuer для общекластерного CA

**Цель:** Создать CA, доступный из всех namespace.

```yaml
# 1. Self-signed ClusterIssuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-cluster-ca
spec:
  selfSigned: {}
---
# 2. CA Certificate (в namespace cert-manager)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: cluster-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: "cluster-root-ca"
  secretName: cluster-root-ca-secret
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
  issuerRef:
    name: selfsigned-cluster-ca
    kind: ClusterIssuer
    group: cert-manager.io
---
# 3. ClusterIssuer на основе CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: cluster-ca-issuer
spec:
  ca:
    secretName: cluster-root-ca-secret
```

**Использование из любого namespace:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-cert
  namespace: production
spec:
  secretName: my-app-tls
  issuerRef:
    name: cluster-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - my-app.production.svc
```

---

## Дополнительная информация

### Проверка сертификатов

```bash
# Получить сертификат из Secret
kubectl get secret my-service-tls -n default -o jsonpath='{.data.tls\.crt}' | base64 -d > cert.crt

# Просмотр информации
openssl x509 -in cert.crt -noout -text

# Проверка цепочки доверия
openssl verify -CAfile <(kubectl get secret my-root-ca-secret -n default -o jsonpath='{.data.ca\.crt}' | base64 -d) cert.crt
```

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Self-signed CA | **10** | Официальная документация cert-manager.io |
| PKCS8 encoding | **10** | Требуется для Java (OpenSearch, Elasticsearch) |
| ClusterIssuer | **10** | Стандартный паттерн cert-manager |

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `encoding: PKCS1` по умолчанию | Java не читает ключ | Явно указать `encoding: PKCS8` |
| Certificate в статусе `Pending` | Issuer не найден | Проверить `issuerRef.kind` (Issuer vs ClusterIssuer) |
| Ошибка цепочки доверия | Secret с CA удалён | Не удалять CA-сертификат до перевыпуска всех зависимых |

---
