# Интеграция cert-manager с Service Mesh (Istio/Linkerd)

## Определения

**Service Mesh** — инфраструктурный слой, обеспечивающий mTLS, маршрутизацию, наблюдаемость и безопасность между микросервисами без изменения кода приложения. Основные реализации в 2026 году: Istio (Ambient Mesh) и Linkerd.

**cert-manager как CA для Service Mesh** — паттерн, при котором cert-manager используется как внешний центр сертификации (External CA) для issuance корневых и промежуточных сертификатов, необходимых service mesh для установления mTLS между подами. Позволяет заменить встроенный CA mesh на управляемый через cert-manager.

**Citadel (устар.)** — прежний компонент Istio, отвечавший за управление PKI и выпуск сертификатов. В текущей архитектуре (2026) его функции интегрированы в `istiod`. При интеграции с cert-manager Citadel не используется — `istiod` обращается к cert-manager через кастомный плагин.

**trust-manager Bundle для Mesh** — ресурс `Bundle`, распространяющий корневой сертификат (CA) во все namespace, включая `istio-system` / `linkerd`, чтобы компоненты mesh доверяли сертификатам, подписанным внешним CA.

---

## Основные концепции

### Зачем использовать cert-manager с Service Mesh

| Подход | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Встроенный CA mesh** | Istio/Linkerd генерирует собственный Root CA при установке. | Простые среды, один кластер, нет compliance-требований. |
| **cert-manager как External CA** | cert-manager выпускает Root/Intermediate CA, mesh использует его для подписи сервисных сертификатов. | Единая PKI-инфраструктура, мультикластер, compliance. |
| **Vault + cert-manager + mesh** | Vault PKI → cert-manager → mesh. Самый гибкий вариант. | Enterprise, аудит, HSM, жесткие требования безопасности. |

### Архитектура интеграции (cert-manager + Istio)

```
┌────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                │
│                                                    │
│  ┌──────────────┐    ┌──────────────────────────┐  │
│  │ cert-manager │───►│ Intermediate CA Issuer    │  │
│  │ (controller) │    │ (ClusterIssuer)           │  │
│  └──────┬───────┘    └──────────┬───────────────┘  │
│         │                       │                   │
│         ▼                       ▼                   │
│  ┌──────────────┐    ┌──────────────────────────┐  │
│  │ trust-manager│───►│ Bundle: istio-ca-bundle   │  │
│  │              │    │ (ConfigMap в istio-system) │  │
│  └──────────────┘    └──────────┬───────────────┘  │
│                                 │                   │
│                                 ▼                   │
│  ┌──────────────────────────────────────────────┐  │
│  │ istiod                                       │  │
│  │  └─ Читает CA из Secret/ConfigMap             │  │
│  │  └─ Использует для подписисервисных серт-тов  │  │
│  └──────────────────────────────────────────────┘  │
│                                                    │
│  ┌──────────────────────────────────────────────┐  │
│  │ Поды приложений (с sidecar / ambient)         │  │
│  │  └─ Получают сертификаты от istiod            │  │
│  │  └─ Доверяют CA через trust-manager Bundle    │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────┘
```

### Различия между Istio и Linkerd

| Характеристика | Istio | Linkerd |
| :--- | :--- | :--- |
| **Механизм интеграции с cert-manager** | Кастомный CA через `values.yaml` (плагин `custom`) | Нативная поддержка через `linkerd-ca` issuer |
| **Компонент, работающий с CA** | `istiod` (ранее Citadel) | `identity` (component) |
| **Формат CA-секрета** | TLS Secret (`ca.crt` + `ca.key`) | Secret с `ca.crt` + `ca.key` |
| **Поддержка cert-manager** | Официальная (cert-manager.io) | Официальная (Linkerd docs) |
| **Ambient Mesh** | GA (Istio 1.24+) | Не поддерживается (только sidecar) |

---

## Практические сценарии

### Сценарий 1: cert-manager как CA для Istio (Sidecar модель)

#### Шаг 1: Создание CA через cert-manager

```yaml
# Root CA (Self-signed)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: root-selfsigned
spec:
  selfSigned: {}
---
# Root Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-root-ca
  namespace: istio-system
spec:
  isCA: true
  commonName: istio-root-ca
  secretName: istio-root-ca-secret
  duration: 87600h  # 10 лет
  privateKey:
    algorithm: ECDSA
    size: 256
  issuerRef:
    name: root-selfsigned
    kind: ClusterIssuer
---
# Intermediate CA для Istio
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-intermediate-ca
  namespace: istio-system
spec:
  isCA: true
  commonName: istio-intermediate-ca
  secretName: istio-intermediate-ca-secret
  duration: 8760h  # 1 год
  renewBefore: 720h
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  issuerRef:
    name: root-selfsigned
    kind: ClusterIssuer
```

#### Шаг 2: Настройка trust-manager для доставки CA

```yaml
apiVersion: trust.cert-manager.io/v1alpha2
kind: Bundle
metadata:
  name: istio-ca-bundle
spec:
  sources:
  - secret:
      name: istio-root-ca-secret
      key: ca.crt
  - secret:
      name: istio-intermediate-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt"
    namespaceSelector:
      matchLabels:
        istio-injection: enabled
```

#### Шаг 3: Конфигурация Istio для использования cert-manager

```bash
# Установка Istio с кастомным CA
helm install istiod istio/istiod \
  --namespace istio-system \
  --set pilot.env.EXTERNAL_CA=ISTIOD_RA_KUBERNETES_API \
  --set global.pilotCertProvider=custom \
  --set global.caAddress=cert-manager.cert-manager.svc:443
```

#### Шаг 4: Создание CA Secret для Istio

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cacerts
  namespace: istio-system
type: Opaque
data:
  ca-cert.pem: <base64 intermediate CA cert>
  ca-key.pem: <base64 intermediate CA key>
  cert-chain.pem: <base64 cert chain>
  root-cert.pem: <base64 root CA cert>
```

#### Верификация

```bash
# Проверка, что Istio использует новый CA
kubectl exec -n istio-system deploy/istiod -- \
  pilot-agent request GET /debug/sds/certs | jq

# Проверка mTLS между подами
istioctl authn tls-check my-app.production.svc.cluster.local
```

---

### Сценарий 2: cert-manager как CA для Istio (Ambient Mesh)

В Ambient Mesh (2026+) sidecar отсутствуют. mTLS обеспечивается Ztunnel (L4) и Waypoint Proxy (L7).

#### Шаг 1: CA (тот же что в Сценарии 1)

#### Шаг 2: Установка Istio в режиме Ambient

```bash
helm install istiod istio/istiod \
  --namespace istio-system \
  --set pilot.env.EXTERNAL_CA=ISTIOD_RA_KUBERNETES_API \
  --set global.pilotCertProvider=custom

helm install ztunnel istio/ztunnel \
  --namespace istio-system
```

#### Шаг 3: Создание Waypoint Proxy

```bash
# Создание waypoint для namespace production
istioctl waypoint apply --namespace production --enroll-namespace

# Waypoint автоматически получает сертификат от istiod
```

#### Верификация

```bash
# Проверка Ambient статуса
istioctl ambient describe pod my-app -n production

# Проверка mTLS соединения
istioctl proxy-status
```

---

### Сценарий 3: cert-manager как CA для Linkerd

#### Шаг 1: Создание CA (аналогично Сценарию 1)

#### Шаг 2: Установка Linkerd с кастомным CA

```bash
# Экспорт CA из cert-manager в формат Linkerd
kubectl get secret istio-intermediate-ca-secret -n istio-system \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ca.crt
kubectl get secret istio-intermediate-ca-secret -n istio-system \
  -o jsonpath='{.data.tls\.key}' | base64 -d > ca.key

# Установка Linkerd
linkerd install --ca-cert-file=ca.crt --ca-private-key-file=ca.key | kubectl apply -f -
```

#### Шаг 3: Инъекция sidecar в namespace

```bash
kubectl label namespace production linkerd.io/injection=enabled
```

#### Верификация

```bash
# Проверка статуса Linkerd
linkerd check

# Проверка mTLS
linkerd viz stat deploy -n production
```

---

### Сценарий 4: Разделение CA для Infra и Application

В production рекомендуется использовать отдельные CA для системных компонентов mesh и прикладных сервисов.

```yaml
# CA для Istio (системный)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: istio-system-ca
  namespace: istio-system
spec:
  isCA: true
  commonName: istio-system-ca
  secretName: istio-system-ca-secret
  duration: 8760h
  issuerRef:
    name: root-selfsigned
    kind: ClusterIssuer
---
# CA для прикладных сервисов (отдельная иерархия)
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: app-internal-ca
  secretName: app-ca-secret
  duration: 8760h
  issuerRef:
    name: root-selfsigned
    kind: ClusterIssuer
---
# Trust-manager Bundle: оба CA
apiVersion: trust.cert-manager.io/v1alpha2
kind: Bundle
metadata:
  name: combined-trust
spec:
  sources:
  - secret:
      name: istio-system-ca-secret
      key: ca.crt
  - secret:
      name: app-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt"
```

---

## Дополнительная информация

### Частые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | CA не доставлен в Trust Store пода | Проверить trust-manager Bundle и монтирование |
| Istio не видит кастомный CA | Secret `cacerts` не создан или неверный формат | Убедиться, что Secret содержит `ca-cert.pem`, `ca-key.pem`, `cert-chain.pem`, `root-cert.pem` |
| Linkerd не запускается после смены CA | Старый CA остаётся в Secret | Удалить старый Secret и перезапустить control plane |
| Ambient Mesh: mTLS не работает | Ztunnel не получил CA | Проверить логи Ztunnel и доступность Secret в `istio-system` |

### Когда использовать cert-manager с mesh

| Сценарий | Рекомендация |
| :--- | :--- |
| Один кластер, нет compliance | Встроенный CA mesh достаточен |
| Мультикластер, единая PKI | cert-manager как External CA |
| Vault + compliance + аудит | Vault PKI → cert-manager → mesh |
| Air-gapped среда | cert-manager с self-signed/CA issuer |

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура внутренних CA
- **[Service Mesh: Концепции](../../../../Service_Mesh/service_mesh_concepts.md)** — общие принципы
- **[Istio: Архитектура](../../../../Service_Mesh/istio_architecture.md)** — компоненты Istio
- **[cert-manager: Определения](../definitions.md)** — базовые ресурсы cert-manager
