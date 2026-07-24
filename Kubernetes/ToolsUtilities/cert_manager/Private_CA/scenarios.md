# Сценарии приватного CA

## Определения

**Сценарии приватного CA** — набор практических конфигураций cert-manager для развертывания внутренних центров сертификации и управления доверием в кластере. Полный архитектурный обзор представлен в [index.md](./index.md).

---

## Основные концепции

### Ключевые параметры Certificate для Private CA

При настройке внутренних сертификатов рекомендуется использовать современные стандарты безопасности и совместимости:

| Параметр | Назначение | Рекомендация |
| :--- | :--- | :--- |
| `isCA: true` | Позволяет использовать сертификат для подписи других сертификатов | Обязательно для Root и Intermediate CA |
| `rotationPolicy: Always` | Генерирует новый закрытый ключ при каждом обновлении сертификата | **Обязательно** для повышения безопасности |
| `privateKey.algorithm: ECDSA` | Современный алгоритм (P-256/P-384) | Рекомендуется вместо RSA (быстрее, меньше размер) |
| `privateKey.encoding: PKCS8` | Формат хранения закрытого ключа | Обязательно для Java-стека (Spring, Elasticsearch, Kafka) |
| `duration` | Срок жизни сертификата | CA: 2–5 лет, Сервисы: 90 дней – 1 год |
| `dnsNames` | Список имен (SAN) | Для K8s: `svc`, `svc.ns.svc`, `svc.ns.svc.cluster.local` |

---

## Практические сценарии

### Сценарий 1: Базовый локальный CA (Namespace-scoped)

**Цель:** Создать изолированный центр сертификации для сервисов в одном пространстве имен.

#### 1. Создание самоподписанного Issuer (Self-signed)

Этот Issuer используется только один раз — для подписи самого корневого сертификата.

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: selfsigned-ca-issuer
  namespace: my-app
spec:
  selfSigned: {}
```

#### 2. Выпуск корневого сертификата (Root CA)

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-root-ca
  namespace: my-app
spec:
  isCA: true
  commonName: "my-root-ca"
  secretName: my-root-ca-secret
  duration: 43800h # 5 лет
  renewBefore: 2160h # 90 дней
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
    rotationPolicy: Always
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
```

#### 3. Создание рабочего CA Issuer

Этот Issuer будет подписывать сертификаты приложений, используя секрет от Root CA.

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: my-ca-issuer
  namespace: my-app
spec:
  ca:
    secretName: my-root-ca-secret
```

#### 4. Выпуск сертификата сервиса

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-service-tls
  namespace: my-app
spec:
  secretName: my-service-tls-secret
  duration: 2160h # 90 дней
  renewBefore: 360h # 15 дней
  privateKey:
    rotationPolicy: Always
    encoding: PKCS8
  issuerRef:
    name: my-ca-issuer
    kind: Issuer
  commonName: "my-service"
  dnsNames:
    - my-service
    - my-service.my-app.svc.cluster.local
```

---

### Сценарий 2: Глобальный ClusterIssuer с дистрибуцией доверия

**Цель:** Создать единый CA для всего кластера и автоматически распространить его публичный ключ (CA Bundle) во все Namespace через **trust-manager**.

#### 1. Иерархия ClusterIssuer

Все ресурсы создаются в системном пространстве имен (например, `cert-manager`).

```yaml
# 1. Самоподписанный ClusterIssuer для Root CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: cluster-selfsigned-issuer
spec:
  selfSigned: {}
---
# 2. Корневой сертификат (Root CA) в системном namespace
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
    rotationPolicy: Always
  issuerRef:
    name: cluster-selfsigned-issuer
    kind: ClusterIssuer
---
# 3. Глобальный CA Issuer для приложений
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: global-ca-issuer
spec:
  ca:
    secretName: cluster-root-ca-secret
```

#### 2. Дистрибуция доверия через trust-manager

Чтобы приложения доверяли этому CA, его публичную часть нужно доставить в каждый Namespace.

```yaml
apiVersion: trust.cert-manager.io/v1alpha1
kind: Bundle
metadata:
  name: global-trust-bundle
spec:
  sources:
  - secret:
      name: cluster-root-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt" # Будет создан во всех namespaces
```

---

### Сценарий 3: Private CA для Java-приложений (Elasticsearch/Kafka)

Для систем на базе JVM критически важен формат **PKCS8** и наличие полной цепочки.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: elasticsearch-node-tls
  namespace: database
spec:
  secretName: elasticsearch-node-tls
  duration: 8760h
  privateKey:
    algorithm: RSA # Некоторые старые версии Java требуют RSA
    size: 2048
    encoding: PKCS8 # Обязательно для Java
    rotationPolicy: Always
  issuerRef:
    name: global-ca-issuer
    kind: ClusterIssuer
  commonName: "elasticsearch-node-1"
  subject:
    organizations:
      - "Database-Cluster"
  dnsNames:
    - elasticsearch-node-1.database.svc
```

---

## Дополнительная информация

### Сравнение подходов

| Сценарий | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Namespace Issuer** | Максимальная изоляция, безопасность | Трудно управлять доверием между разными NS |
| **ClusterIssuer** | Простота использования для всего кластера | Единая точка отказа при компрометации ключа |
| **trust-manager** | Автоматизация доставки доверия (SSoT) | Требует установки дополнительного компонента |

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура и выбор типа Issuer
- **[Приватный CA: Операции](./operations.md)** — ротация корневого CA и отладка
- **[trust-manager: Документация](./trust-manager.md)** — детальная настройка дистрибуции
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — решение проблем выпуска
