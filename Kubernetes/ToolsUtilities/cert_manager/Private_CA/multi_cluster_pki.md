# Мультикластерный PKI

## Определения

**Мультикластерный PKI** — архитектура, при которой несколько Kubernetes-кластеров используют единую или связанную инфраструктуру открытых ключей (PKI) для выпуска сертификатов, доверенных между кластерами. Критично для межкластерного mTLS, disaster recovery и гибридных сред.

**Shared CA (Общий CA)** — единый корневой CA, выпускающий сертификаты для всех кластеров. Все кластеры доверяют одному корню. Простая модель, но компрометация одного CA затрагивает все кластеры.

**Per-Cluster CA (Кластерный CA)** — каждому кластеру выделяется собственный промежуточный CA, подписанный общим корнем (или разными корнями). Обеспечивает изоляцию blast radius, но требует управления доверием.

**Federation Trust (Федеративное доверие)** — механизм, при котором кластеры обмениваются публичными частями своих CA для взаимной верификации сертификатов. Реализуется через cross-namespace Secret sharing или внешние хранилища.

---

## Основные концепции

### Модели мультикластерного PKI

| Модель | Описание | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **Shared CA** | Единый Root CA, все кластеры получают Intermediate CA от него | Простота, единая точка управления | Компрометация CA → все кластеры |
| **Per-Cluster CA** | Каждый кластер имеет собственный Intermediate CA, подписанный общим Root | Изоляция blast radius | Сложнее управлять доверием |
| **Sovereign CA** | Полностью независимые CA в каждом кластере | Максимальная изоляция | Нет взаимного доверия (нужен cross-sign) |
| **Hub-and-Spoke** | Центральный кластер выпускает CA для spoke-кластеров | Централизация, легко масштабировать | Точка отказа (hub) |

### Архитектура Hub-and-Spoke

```
┌─────────────────────────────────────────────────────┐
│                   Hub Cluster                       │
│                                                     │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │ cert-manager │───►│ Root CA (ClusterIssuer)    │  │
│  └──────┬───────┘    └───────────┬───────────────┘  │
│         │                        │                   │
│         ▼                        ▼                   │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │ Vault / ESO  │───►│ Intermediate CA (per-spoke)│  │
│  └──────────────┘    └───────────┬───────────────┘  │
│                                  │                   │
└──────────────────────────────────┼───────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
            ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
            │ Spoke K8s-1  │ │ Spoke K8s-2  │ │ Spoke K8s-3  │
            │ (own CA)     │ │ (own CA)     │ │ (own CA)     │
            └──────────────┘ └──────────────┘ └──────────────┘
```

### Выбор модели

| Сценарий | Рекомендуемая модель |
| :--- | :--- |
| 2-3 кластера, одна команда | Shared CA |
| 5+ кластеров, разные команды | Per-Cluster CA |
| Enterprise, compliance | Per-Cluster CA + Vault |
| Мультикластерный service mesh | Shared CA (обязательно для mesh) |
| Air-gapped spoke-кластеры | Sovereign CA + cross-sign при необходимости |

---

## Практические сценарии

### Сценарий 1: Shared CA для 2 кластеров

#### Кластер-источник (Hub): Создание Root CA

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: hub-root-selfsigned
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: hub-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: hub-root-ca
  secretName: hub-root-ca-secret
  duration: 87600h  # 10 лет
  privateKey:
    algorithm: ECDSA
    size: 384
  issuerRef:
    name: hub-root-selfshared
    kind: ClusterIssuer
```

#### Экспорт Root CA

```bash
# Экспорт публичного сертификата Root CA
kubectl get secret hub-root-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > hub-root-ca.crt

# Экспорт приватного ключа (ОПАСНО: храните в защищенном месте!)
kubectl get secret hub-root-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.key}' | base64 -d > hub-root-ca.key
```

#### Spoke-кластер: Импорт Root CA

```bash
# Импорт Root CA в spoke-кластер
kubectl create secret tls hub-root-ca-secret \
  --cert=hub-root-ca.crt \
  --key=hub-root-ca.key \
  -n cert-manager
```

```yaml
# Issuer на основе импортированного Root CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: hub-ca-issuer
spec:
  ca:
    secretName: hub-root-ca-secret
---
# Intermediate CA для spoke-кластера
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: spoke1-intermediate-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: spoke1-intermediate-ca
  secretName: spoke1-intermediate-ca-secret
  duration: 8760h  # 1 год
  renewBefore: 720h
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: hub-ca-issuer
    kind: ClusterIssuer
```

---

### Сценарий 2: Per-Cluster CA с изоляцией

```yaml
# Hub: Root CA
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: global-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: global-root-ca
  secretName: global-root-ca-secret
  duration: 87600h
  privateKey:
    algorithm: ECDSA
    size: 384
  issuerRef:
    name: root-selfshared
    kind: ClusterIssuer
---
# Hub: Intermediate CA для Cluster-1
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: cluster1-intermediate-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: cluster1-ca
  secretName: cluster1-ca-secret
  duration: 8760h
  issuerRef:
    name: root-ca-issuer
    kind: ClusterIssuer
---
# Hub: Intermediate CA для Cluster-2
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: cluster2-intermediate-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: cluster2-ca
  secretName: cluster2-ca-secret
  duration: 8760h
  issuerRef:
    name: root-ca-issuer
    kind: ClusterIssuer
```

#### trust-manager Bundle для кластеров

```yaml
# Bundle для Cluster-1: только его Intermediate CA
apiVersion: trust.cert-manager.io/v1alpha2
kind: Bundle
metadata:
  name: cluster1-trust
spec:
  sources:
  - secret:
      name: global-root-ca-secret
      key: ca.crt
  - secret:
      name: cluster1-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt"
    namespaceSelector:
      matchLabels:
        kubernetes.io/metadata.name: production
```

---

### Сценарий 3: Мультикластерный mTLS

Для mTLS между сервисами в разных кластерах необходим общий CA или cross-signed CA.

#### Вариант A: Shared CA (простой)

Все кластеры используют Intermediate CA от одного Root → сертификаты взаимно доверены.

#### Вариант B: Cross-sign (сложный)

```bash
# На Hub: создание cross-signed CA
# Подпись Intermediate CA Cluster-1 ключом Root CA Cluster-2 (и наоборот)
# Это обеспечивает взаимное доверие при сохранении изоляции
```

#### Конфигурация mTLS через cert-manager

```yaml
# Сертификат клиента (Cluster-1)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: cross-cluster-client
  namespace: production
spec:
  secretName: cross-cluster-client-tls
  duration: 720h
  issuerRef:
    name: cluster1-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - api-service.production.svc.cluster.local
  usages:
    - client auth
    - digital signature
```

---

## Дополнительная информация

### Сравнение с другими подходами

| Подход | Когда использовать |
| :--- | :--- |
| **cert-manager Multi-Cluster** | Kubernetes-native, декларативно, GitOps-friendly |
| **Vault HA** | Централизованное управление, enterprise compliance |
| **SPIFFE/SPIRE** | Service mesh, встроенный identity framework |
| **Kubernetes CSR API** | Кластерные компоненты (kubelet), не прикладные сервисы |

### Ограничения

- **Сетевая доступность:** Hub-кластер должен быть доступен из spoke для выпуска сертификатов. В air-gapped средах требует предварительного создания CA.
- **Латентность:** Обращение к Hub CA добавляет задержку при выпуске сертификатов. Решение: кэширование Intermediate CA в spoke.
- **Ротация Root CA:** При ротации Root CA необходимо обновить trust во всех spoke-кластерах. Используйте trust-manager с двумя CA в переходный период.
- **Бэкап:** Потеря Root CA делает невозможным выпуск новых сертификатов для всех кластеров. Бэкап Root CA — приоритетная задача.

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура иерархий доверия
- **[Приватный CA: Операции](./operations.md)** — ротация и backup
- **[Disaster Recovery Runbook](./disaster_recovery_runbook.md)** — восстановление PKI
- **[cert-manager: Определения](../definitions.md)** — базовые ресурсы cert-manager
