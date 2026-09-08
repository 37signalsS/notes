# Сценарии приватного CA

## Определения

**Сценарии приватного CA** — набор практических конфигураций cert-manager для развертывания внутренних центров сертификации и управления доверием в кластере. Полный архитектурный обзор представлен в [index.md](./index.md).

**Внутренний mTLS** — взаимная аутентификация между сервисами через сертификаты, подписанные внутренним CA. В отличие от mTLS на основе CA кластера (см. [cluster_ca.md](../cluster_ca.md)), используется независимая иерархия доверия, изолированная от системных компонентов Kubernetes.

**Wildcard-сертификат** — сертификат, покрывающий все поддомены уровня (например, `*.team-alpha.svc.cluster.local`). В Private CA issuance wildcard возможен без ограничений, в отличие от ACME, где для wildcard обязателен DNS-01.

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
| `usages` | Расширения ключа (EKU) | mTLS: `[server auth, client auth]`; только сервер: `[server auth]` |

### Структура Secret, создаваемого cert-manager

При выпуске сертификата cert-manager создаёт Secret типа `kubernetes.io/tls` со следующими полями:

| Поле | Содержимое | Назначение |
| :--- | :--- | :--- |
| `tls.crt` | Сертификат + промежуточные CA (цепочка) | Предоставляется клиенту для верификации сервера |
| `tls.key` | Закрытый ключ | Используется сервером для TLS-рукопожатия |
| `ca.crt` | Публичный сертификат CA (только при `isCA: true`) | Доступен для настройки trust store в приложении |

> **Важно:** Поле `tls.crt` содержит полную цепочку (leaf + intermediate), но **не** корневой CA. Корневой CA доставляется отдельно через trust-manager или монтирование.

### Шаблоны SAN (Subject Alternative Names) для Kubernetes

Правильный выбор DNS-имен критичен для корректной работы mTLS:

| Паттерн | Формат | Пример |
| :--- | :--- | :--- |
| Сервис в том же Namespace | `<svc>` | `my-app` |
| Сервис в другом Namespace | `<svc>.<ns>.svc` | `my-app.team-alpha.svc` |
| Полный FQDN | `<svc>.<ns>.svc.cluster.local` | `my-app.team-alpha.svc.cluster.local` |
| Wildcard по подсети | `*.<ns>.svc.cluster.local` | `*.team-alpha.svc.cluster.local` |
| Wildcard по домену | `*.<domain>` | `*.internal.example.com` |

**Рекомендация:** Всегда указывайте как минимум короткое имя и полный FQDN. Wildcard используйте только при необходимости покрыть несколько сервисов в одной команде.

### Доставка CA-цепочки приложениям

Приложение должно доверять не только конечному сертификату, но и всей цепочке. Существует три основных подхода:

| Подход | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **trust-manager Bundle** | ConfigMap с CA автоматически во всех Namespace | Стандарт для production |
| **Volume Mount** | Монтирование Secret/ConfigMap напрямую в Pod | Когда нужен контроль над путём |
| **Init Container** | Копирование CA в системное хранилище | Приложения, требующие `/etc/ssl/certs/ca-certificates.crt` |

> **Подробнее:** Настройка trust-manager описана в [Сценарии 2](#сценарий-2-глобальная-дистрибуция-через-trust-manager) и [index.md](./index.md#дистрибуция-доверия-через-trust-manager).

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

#### Верификация

```bash
# Проверка цепочки: Root → Intermediate → Service
openssl verify \
  -CAfile <(kubectl get secret root-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d) \
  -untrusted <(kubectl get secret intermediate-ca-secret -n cert-manager -o jsonpath='{.data.tls\.crt}' | base64 -d) \
  <(kubectl get secret alpha-service-tls-secret -n team-alpha -o jsonpath='{.data.tls\.crt}' | base64 -d)
# → OK
```

#### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unable to get local issuer certificate` | Intermediate CA не передан в `-untrusted` | Используйте флаг `-untrusted` с промежуточным сертификатом |
| `self signed certificate` | Root CA подписан самим собой (ожидаемо) | Добавьте Root CA в `-CAfile`, а не в `-untrusted` |

---

### Сценарий 2: Глобальная дистрибуция через trust-manager

**Цель:** Сделать корневой сертификат доверенным во всех Namespace кластера без ручного копирования.

```yaml
apiVersion: trust.cert-manager.io/v1alpha2
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

#### Верификация

```bash
# Проверка создания ConfigMap в целевом Namespace
kubectl get configmap global-trust-bundle -n team-alpha -o yaml

# Проверка содержимого (должен содержать корневой CA)
kubectl get configmap global-trust-bundle -n team-alpha \
  -o jsonpath='{.data.ca-certificates\.crt}' | grep -c "BEGIN CERTIFICATE"
# → 2 (системный CA + внутренний CA)
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

#### Верификация

```bash
# Проверка наличия JKS и PKCS12 в Secret
kubectl get secret kafka-node-tls-secret -n messaging -o jsonpath='{.data}' | jq 'keys'
# → ["ca.crt", "keystore.jks", "keystore密码", "tls.crt", "tls.key", "truststore.jks"]

# Проверка JKS через keytool (в поде с JDK)
kubectl exec -n messaging kafka-pod-0 -- \
  keytool -list -keystore /path/to/keystore.jks -storepass <password>
```

---

### Сценарий 4: Начальное создание внутреннего CA (Bootstrap)

В новом кластере часто возникает проблема "курицы и яйца": для `ClusterIssuer` типа `ca` нужен Secret, который еще не существует. cert-manager решает это через временный `selfSigned` эмитент.

**1. Создание временного Bootstrap-эмитента:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned-bootstrap
spec:
  selfSigned: {}
```

**2. Выпуск сертификата CA:**
Этот ресурс преобразует запрос в Secret `internal-ca-secret`, содержащий пару ключей.
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: "internal-ca"
  secretName: internal-ca-secret
  privateKey:
    algorithm: Ed25519 # Оптимально для mTLS в 2026 году
  issuerRef:
    name: selfsigned-bootstrap
    kind: ClusterIssuer
```

**3. Создание основного CA ClusterIssuer:**
Теперь эмитент может ссылаться на созданный Secret.
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  ca:
    secretName: internal-ca-secret
```

---

### Сценарий 5: Wildcard-сертификаты с приватным CA

**Цель:** Выпуск сертификата, покрывающего все поддомены уровня (например, для Ingress, маршрутизирующего трафик к разным сервисам команды).

В отличие от ACME (Let's Encrypt), где wildcard обязателен через DNS-01, в Private CA wildcard выпускается без дополнительных проверок.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: team-alpha-wildcard
  namespace: team-alpha
spec:
  secretName: team-alpha-wildcard-tls
  duration: 2160h # 90 дней
  renewBefore: 360h # 15 дней
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
  issuerRef:
    name: intermediate-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - "*.team-alpha.svc.cluster.local"
    - "*.alpha.internal.example.com"
    - team-alpha.svc.cluster.local # Корень тоже нужен для прямых обращений
```

#### Верификация

```bash
# Проверка SAN в сертификате
kubectl get secret team-alpha-wildcard-tls -n team-alpha \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -ext subjectAltName
# → DNS:*.team-alpha.svc.cluster.local, DNS:*.alpha.internal.example.com, DNS:team-alpha.svc.cluster.local
```

#### Когда использовать wildcard

| Сценарий | Рекомендация |
| :--- | :--- |
| Команда с 5+ сервисами в одном Namespace | Wildcard упрощает управление |
| Ingress с path-based routing | Один сертификат на все сервисы |
| Service Mesh (без mTLS на уровне cert-manager) | Wildcard покрывает все сервисы |
| Малое количество сервисов (<3) | Individual сертификаты проще |

---

### Сценарий 6: mTLS между сервисами (приватный CA)

**Цель:** Взаимная аутентификация двух внутренних сервисов через сертификаты, подписанные приватным CA.

> **Отличие от [cluster_ca.md](../cluster_ca.md#сценарий-3-mtls-между-сервисами):** Здесь используется независимая иерархия Private CA, а не CA кластера. Это обеспечивает изоляцию: компрометация прикладного CA не влияет на системные компоненты Kubernetes.

#### Сертификаты сторон

| Роль | `usages` | Назначение |
| :--- | :--- | :--- |
| **Server** | `[server auth, digital signature, key encipherment]` | Предоставляется сервером для верификации |
| **Client** | `[client auth, digital signature]` | Предоставляется клиентом для аутентификации |

```yaml
# Серверный сертификат
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-server-tls
  namespace: production
spec:
  secretName: api-server-tls-secret
  duration: 720h # 30 дней
  renewBefore: 168h # 7 дней
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: intermediate-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - api-server
    - api-server.production.svc.cluster.local
  usages:
    - server auth
    - digital signature
    - key encipherment
---
# Клиентский сертификат
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: worker-client-tls
  namespace: production
spec:
  secretName: worker-client-tls-secret
  duration: 720h
  renewBefore: 168h
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: intermediate-ca-issuer
    kind: ClusterIssuer
  dnsNames:
    - worker
    - worker.production.svc.cluster.local
  usages:
    - client auth
    - digital signature
```

#### Пример конфигурации Nginx для mTLS

```nginx
server {
    listen 443 ssl;
    server_name api-server.production.svc.cluster.local;

    ssl_certificate     /etc/tls/tls.crt;   # Серверный сертификат + цепочка
    ssl_certificate_key /etc/tls/tls.key;   # Закрытый ключ сервера

    # Верификация клиентского сертификата
    ssl_client_certificate /etc/tls/ca.crt;  # CA для проверки клиента (Intermediate CA)
    ssl_verify_client on;
    ssl_verify_depth 2;                      # Root → Intermediate → Client
}
```

#### Верификация

```bash
# Проверка серверного сертификата
openssl s_client -connect api-server.production.svc:443 \
  -CAfile <(kubectl get secret root-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d) \
  -cert <(kubectl get secret worker-client-tls-secret -n production -o jsonpath='{.data.tls\.crt}' | base64 -d) \
  -key <(kubectl get secret worker-client-tls-secret -n production -o jsonpath='{.data.tls\.key}' | base64 -d)
```

---

### Сценарий 7: Namespace-scoped Issuers для мультитенантности

**Цель:** Делегировать каждой команде право выпускать сертификаты в пределах своего Namespace, сохраняя контроль над Root CA на уровне платформенной команды.

> **Контекст:** Описан в [Administration/index.md](../Administration/index.md#roles-and-rbac) — разграничение между инфраструктурным и прикладным уровнями.

```yaml
# Namespace для команды team-beta
apiVersion: v1
kind: Namespace
metadata:
  name: team-beta
  labels:
    cert-manager.io/issuer: "allowed"
---
# Issuer, привязанный к Namespace team-beta
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: team-beta-issuer
  namespace: team-beta
spec:
  ca:
    secretName: team-beta-intermediate-ca-secret
---
# RBAC: команда может создавать Certificate и Issuer в своем Namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-issuer
  namespace: team-beta
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests", "issuers"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: cert-manager-issuer-binding
  namespace: team-beta
subjects:
- kind: Group
  name: team-beta
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: cert-manager-issuer
  apiGroup: rbac.authorization.k8s.io
```

#### Схема делегирования

```
Platform Team
  └── Root CA (ClusterIssuer, cert-manager namespace)
       ├── Team Alpha Issuer (team-alpha namespace)
       │    └── alpha-service-tls
       ├── Team Beta Issuer (team-beta namespace)
       │    └── beta-service-tls
       └── Team Gamma Issuer (team-gamma namespace)
            └── gamma-service-tls
```

---

### Сценарий 8: Импорт существующего внешнего CA

**Цель:** Использовать сертификаты, выпущенные внешним CA (Vault, Step-CA, корпоративный PKI), через cert-manager как CA Issuer.

```yaml
# 1. Импорт внешнего CA в Kubernetes Secret
# (выполняется один раз, ключи берутся из Vault/Step-CA)
apiVersion: v1
kind: Secret
metadata:
  name: external-ca-secret
  namespace: cert-manager
type: kubernetes.io/tls
data:
  tls.crt: <base64 certificate chain from external CA>
  tls.key: <base64 private key from external CA>
---
# 2. ClusterIssuer, ссылающийся на импортированный CA
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: external-ca-issuer
spec:
  ca:
    secretName: external-ca-secret
```

#### Когда использовать

| Сценарий | Описание |
| :--- | :--- |
| Миграция с Vault PKI | Временная совместимость в переходный период |
| Корпоративный PKI | Единый CA для всего парка кластеров |
| Аудит/Compliance | Требование использовать сертификаты от уполномоченного CA |

> **Важно:** При импорте убедитесь, что `tls.crt` содержит полную цепочку (intermediate + root), иначе верификация завершится ошибкой `unable to get local issuer certificate`.

---

### Сценарий 9: Работа в изолированной среде (Air-gapped)

**Цель:** Обеспечение работы Private CA в кластерах без доступа к интернету.

В air-gapped среде trust-manager не может загрузить системные CA (`useDefaultCAs: true`). Необходимо формировать Bundle вручную.

```yaml
# Bundle без системных CA (только внутренние)
apiVersion: trust.cert-manager.io/v1alpha2
kind: Bundle
metadata:
  name: internal-only-bundle
spec:
  sources:
  - secret:
      name: root-ca-secret
      key: ca.crt
  - configMap:
      name: corporate-ca-bundle  # Предварительно создан вручную
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt"
```

#### Подготовка air-gapped среды

1. **Зеркалирование образов:** Перенесите образ cert-manager и trust-manager во внутренний registry.
2. **Предсоздание ConfigMap:** Импортируйте корневые сертификаты в `corporate-ca-bundle` до установки.
3. **OCI-установка:** Используйте `helm install` с `--set image.repository=internal-registry.io/cert-manager` (описано в [installation.md](../installation.md#альтернатива-через-oci-рекомендуется-для-изолированных-сред)).

---

### Сценарий 10: Локальная разработка с mkcert и динамическим DNS

**Цель:** Получить валидные HTTPS-сертификаты для локального Kubernetes-кластера (Docker Desktop, kind, Minikube, K3s) без публичного DNS и без отключения проверок в браузере.

**Проблема:** В локальных кластерах нет публичного DNS, а Let's Encrypt не может выдать сертификат для `localhost` или внутренних IP-адресов. Самоподписанные сертификаты вызывают предупреждения о недоверии в браузерах. Решение — использовать локальный CA (`mkcert`), импортировать его в cert-manager и динамический DNS (`nip.io` или `sslip.io`) для автоматического разрешения доменов.

#### 1. Установка mkcert

`mkcert` — утилита для создания локальных CA, автоматически добавляемых в доверенные хранилища ОС и браузеров.

```bash
# macOS (Homebrew)
brew install mkcert

# Linux
sudo apt install mkcert

# Установка корневого CA в системное хранилище доверия
mkcert --install
# → Генерирует rootCA.pem и rootCA-key.pem в CAROOT (~/.local/share/mkcert)
# → Добавляет rootCA.pem в macOS Keychain / Linux NSS / Windows Cert Store
```

#### 2. Импорт CA в cert-manager

Создайте Kubernetes Secret с корневым сертификатом mkcert:

```bash
kubectl create secret tls mkcert-ca-key-pair \
  --key "$(mkcert -CAROOT)/rootCA-key.pem" \
  --cert "$(mkcert -CAROOT)/rootCA.pem" \
  -n cert-manager
```

#### 3. ClusterIssuer для mkcert

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: mkcert-issuer
  namespace: cert-manager
spec:
  ca:
    secretName: mkcert-ca-key-pair
```

> **Важно:** Для работы cert-manager с CA необходимо предварительно установить cert-manager в кластере. Подробности: [Установка cert-manager](../installation.md).

#### 4. Подготовка инфраструктуры

Для доступа к приложениям через Ingress с внешним IP:

| Компонент | Назначение | Документация |
| :--- | :--- | :--- |
| **MetalLB** | Назначение внешних IP для LoadBalancer-сервисов в bare-metal/локальных кластерах | [SSoT: MetalLB](../../../Networking/metallb.md) |
| **Ingress NGINX** | Маршрутизация HTTPS-трафика | [Helm-установка ingress-nginx](../../../Networking/Ingress/installation/helm-installation.md) |
| **cert-manager** | Автоматическая выдача и ротация TLS | [Установка cert-manager](../installation.md) |

> **Статус (2026):** Проект `kubernetes/ingress-nginx` официально перешел в статус **End of Life (EOL)** в марте 2026 года. Для новых проектов рекомендуется использовать **Gateway API** (Envoy Gateway, Traefik v3, NGINX Gateway Fabric). Данный сценарий сохраняется для существующих сред и обратной совместимости.

#### 5. Динамический DNS

Используйте `nip.io` или `sslip.io` для автоматического разрешения доменов в IP-адрес Ingress-контроллера без редактирования `/etc/hosts`:

```
<IP>.nip.io            → резолвится в <IP>
<subdomain>.<IP>.nip.io → резолвится в <IP>
```

Пример: `grafana.192.168.1.52.nip.io` → `192.168.1.52`

Подробнее: [Ingress: Обзор](../../../Networking/Ingress/overview.md#совет-для-тестирования).

#### 6. Практический пример

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana-deployment
  labels:
    app: grafana
spec:
  replicas: 3
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - image: grafana/grafana:11.5.1
        name: grafana
        ports:
        - containerPort: 3000
---
apiVersion: v1
kind: Service
metadata:
  name: grafana-service
  labels:
    app: grafana
spec:
  selector:
    app: grafana
  ports:
  - protocol: TCP
    port: 3000
    targetPort: 3000
  type: ClusterIP
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana-ingress
  annotations:
    cert-manager.io/cluster-issuer: mkcert-issuer
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - grafana.192.168.1.52.nip.io
    secretName: grafana-tls
  rules:
  - host: grafana.192.168.1.52.nip.io
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: grafana-service
            port:
              number: 3000
```

> **Примечание:** Версия образа `grafana/grafana:11.5.1` указана для примера. Актуальные версии: [Grafana Overview](../../../../Grafana/grafana_overview.md).

#### 7. Валидация

```bash
# Проверка выданного сертификата
kubectl get certificate -n <namespace>
# → grafana-tls   True   grafana-tls-xxx   5m

# Проверка секрета TLS
kubectl get secret grafana-tls -n <namespace> -o yaml

# Проверка событий Ingress
kubectl describe ingress grafana-ingress -n <namespace>

# Доступ через браузер
# https://grafana.<IP>.nip.io
# → Сертификат валиден, доверенный ОС
```

#### Когда использовать

| Сценарий | Преимущества |
| :--- | :--- |
| Локальная разработка | Валидные HTTPS без публичного DNS |
| Демонстрации/презентации | Сертификаты не вызывают предупреждений |
| Тестирование Ingress | Полный цикл TLS без внешних зависимостей |
| Air-gapped окружения | Работает без доступа к ACME CA |

> **Важно:** mkcert CA доверен только на машине, где был выполнен `mkcert --install`. Для доступа из других устройств в сети скопируйте `rootCA.pem` и установите в доверенные корневые сертификаты каждого клиента.

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура иерархий доверия
- **[Сценарий 8](#сценарий-8-импорт-существующего-внешнего-ca)** — общий паттерн импорта внешнего CA в cert-manager
- **[Ingress: Обзор](../../../Networking/Ingress/overview.md)** — динамические DNS `nip.io`/`sslip.io`
- **[MetalLB: Балансировщик](../../../Networking/metallb.md)** — внешние IP для bare-metal кластеров
- **[cert-manager: Установка](../installation.md)** — установка контроллера

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

### Decision Guide: Какой сценарий выбрать?

| Задача | Рекомендуемый сценарий |
| :--- | :--- |
| Новый кластер, нет CA | Сценарий 4 (Bootstrap) |
| Делегирование командам | Сценарий 1 (2-Tier) + Сценарий 7 (Namespace-scoped) |
| Доставка CA всем подам | Сценарий 2 (trust-manager) |
| Java/Kafka/ES интеграция | Сценарий 3 (JKS/PKCS12) |
| Wildcard для команды | Сценарий 5 (Wildcard) |
| mTLS между сервисами | Сценарий 6 (mTLS) |
| Импорт Vault/корпоративного CA | Сценарий 8 (Pre-existing CA) |
| Air-gapped кластер | Сценарий 9 (Isolated) |

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура и выбор типа Issuer
- **[Приватный CA: Операции](./operations.md)** — ротация корневого CA и отладка
- **[Использование CA кластера](../cluster_ca.md)** — альтернативный подход с K8s CA (сравнение)
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — решение проблем выпуска
