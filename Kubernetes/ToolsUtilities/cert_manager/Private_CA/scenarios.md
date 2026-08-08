# Сценарии приватного CA

## Определения

**Сценарии приватного CA** — набор практических конфигураций cert-manager для развертывания внутренних центров сертификации и управления доверием в кластере. Полный архитектурный обзор представлен в [index.md](./index.md).

---

## Основные концепции

### Ключевые параметры Certificate для Private CA

При настройке внутренних сертификатов рекомендуется использовать современные стандарты безопасности и совместимости:

| Параметр | Назначение | Рекомендация (2026) |
| :--- | :--- | :--- |
| `isCA: true` | Позволяет использовать сертификат для подписи других сертификатов | Обязательно для Root и Intermediate CA |
| `rotationPolicy: Always` | Генерирует новый закрытый ключ при каждом обновлении сертификата | **Обязательно** для всех уровней, кроме Root |
| `privateKey.algorithm: Ed25519` | Наиболее современный и быстрый алгоритм | Рекомендуется для mTLS и внутреннего трафика |
| `privateKey.encoding: PKCS8` | Формат хранения закрытого ключа | Стандарт для Java (Spring, Kafka, Elasticsearch) |
| `duration` | Срок жизни сертификата | Root: 5 лет, Intermediate: 1 год, Сервисы: 7–30 дней |
| `dnsNames` | Список имен (SAN) | Для K8s: `svc`, `svc.ns.svc`, `svc.ns.svc.cluster.local` |

---

## Практические сценарии

### Сценарий 1: Двухуровневая иерархия (Root -> Intermediate -> Service)

**Цель:** Обеспечить максимальную безопасность за счет изоляции корневого ключа и делегирования выпуска промежуточному CA.

#### 1. Создание Root CA (Корневой уровень)

```yaml
# 1. Самоподписанный Issuer для Root CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: root-selfsigned-issuer
spec:
  selfSigned: {}
---
# 2. Корневой сертификат (Root CA)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: "internal-root-ca"
  secretName: root-ca-secret
  duration: 43800h # 5 лет
  privateKey:
    algorithm: ECDSA
    size: 384
    rotationPolicy: Never # Root CA ротируется вручную
  issuerRef:
    name: root-selfsigned-issuer
    kind: ClusterIssuer
---
# 3. Issuer корневого уровня
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: root-ca-issuer
spec:
  ca:
    secretName: root-ca-secret
```

#### 2. Создание Intermediate CA (Промежуточный уровень)

```yaml
# 1. Сертификат Intermediate CA, подписанный Root CA
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: intermediate-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: "team-alpha-intermediate-ca"
  secretName: intermediate-ca-secret
  duration: 8760h # 1 год
  renewBefore: 720h # 30 дней
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: root-ca-issuer
    kind: ClusterIssuer
---
# 2. Issuer промежуточного уровня для выпуска сертификатов сервисов
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: intermediate-ca-issuer
spec:
  ca:
    secretName: intermediate-ca-secret
```

#### 3. Выпуск сертификата сервиса

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: alpha-service-tls
  namespace: team-alpha
spec:
  secretName: alpha-service-tls-secret
  duration: 720h # 30 дней
  renewBefore: 168h # 7 дней
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: intermediate-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - alpha-service
    - alpha-service.team-alpha.svc.cluster.local
```

---

### Сценарий 2: Глобальная дистрибуция через trust-manager

**Цель:** Сделать корневой сертификат доверенным во всех Namespace кластера без ручного копирования.

```yaml
apiVersion: trust.cert-manager.io/v1alpha1
kind: Bundle
metadata:
  name: global-trust-bundle
spec:
  sources:
  - useDefaultCAs: true  # Включить системные сертификаты (Let's Encrypt и др.)
  - secret:
      name: root-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt" # Будет создан во всех Namespaces
    # Опционально: фильтрация по Namespace
    # namespaceSelector:
    #   matchLabels:
    #     trust: "enabled"
```

---

### Сценарий 3: Интеграция с Java (Elasticsearch/Kafka) через JKS/PKCS12

Для Java-приложений cert-manager может автоматически генерировать Keystore и Truststore.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: kafka-node-tls
  namespace: messaging
spec:
  secretName: kafka-node-tls-secret
  duration: 2160h
  privateKey:
    algorithm: RSA # RSA 2048 остается стандартом совместимости для некоторых JVM
    size: 2048
    encoding: PKCS8
    rotationPolicy: Always
  # Автоматическая генерация хранилищ для Java
  keystores:
    jks:
      create: true
      passwordSecretRef:
        name: jks-password
        key: password
    pkcs12:
      create: true
      passwordSecretRef:
        name: jks-password
        key: password
  issuerRef:
    name: intermediate-ca-issuer
    kind: ClusterIssuer
  commonName: "kafka-node-1"
  dnsNames:
    - kafka-node-1.messaging.svc.cluster.local
```

---

## Дополнительная информация

### Сравнение алгоритмов (2026)

| Алгоритм | Производительность | Совместимость | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Ed25519** | Максимальная (mTLS) | Современное ПО (Go, Rust, Python) | **Default для mTLS** |
| **ECDSA (P-256)** | Высокая | Почти везде (Nginx, Envoy, Java 11+) | Баланс скорости и совместимости |
| **RSA 4096** | Низкая | Универсальная | Только для внешних Root CA |

### Особенности ротации Intermediate CA

При ротации промежуточного CA (Intermediate) сертификаты сервисов продолжат работать до своего истечения, если они были подписаны старым Intermediate, а Root CA не менялся. Однако для обеспечения консистентности рекомендуется перевыпустить все зависимые сертификаты сразу после обновления Intermediate через `cmctl renew --all`.

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура и выбор типа Issuer
- **[Приватный CA: Операции](./operations.md)** — ротация корневого CA и отладка
- **[trust-manager: Настройка](./scenarios.md#сценарий-2-глобальная-дистрибуция-через-trust-manager)** — детальная настройка дистрибуции в кластере.
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — решение проблем выпуска
