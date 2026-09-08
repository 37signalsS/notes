# Интеграция cert-manager с Gateway API: Практические сценарии

## Определения

**Терминация TLS (TLS Termination)** — режим работы шлюза, при котором зашифрованный трафик расшифровывается на уровне Gateway и передается бэкенд-сервисам в открытом или перешифрованном виде. Основной метод интеграции с cert-manager.

**Сквозное шифрование (TLS Passthrough)** — режим, при котором TLS-трафик передается напрямую бэкенду без расшифровки на шлюзе (требуется `TLSRoute`). cert-manager в этом процессе на уровне шлюза не участвует.

**gateway-shim** — механизм в cert-manager, автоматически выпускающий сертификаты на основе аннотаций в ресурсах `Gateway`, `HTTPRoute` или `ListenerSet` (аналог Ingress-аннотаций).

**Wildcard-сертификат** — сертификат, выпускаемый для основного домена и всех его поддоменов первого уровня (например, `*.example.com`). В 2026 году для его получения обязателен метод DNS-01.

**ReferenceGrant** — ресурс безопасности Gateway API, разрешающий перекрестные ссылки между пространствами имен (например, когда Gateway в `infra` namespace использует Secret из `app` namespace).

**CertificateRequest** — внутренний ресурс cert-manager, представляющий запрос на выпуск сертификата, отправляемый в Issuer (ClusterIssuer). Содержит CSR (Certificate Signing Request), подписанный приватным ключом, и отслеживает статус обработки эмитентом. Является промежуточным звеном между `Certificate` и `Order`.

**Order** — объект ACME-протокола, описывающий транзакцию выпуска сертификата. Содержит список требуемых Challenge (HTTP-01, DNS-01, TLS-ALPN-01), конечный статус (`valid`, `invalid`, `expired`) и URL для обновления. cert-manager создаёт Order автоматически при обработке CertificateRequest.

**Challenge** — объект ACME-протокола, представляющий одну проверку подтверждения владения доменом. Поддерживает три типа: `HTTP-01` (размещение токена на порту 80), `DNS-01` (создание TXT-записи `_acme-challenge`) и `TLS-ALPN-01` (представление сертификата на порту 443). cert-manager создаёт Challenge автоматически для каждого домена в Order.

**Алгоритм ключа (Key Algorithm)** — алгоритм генерации ключевой пары для сертификата. В 2026 году рекомендуется ECDSA (P-256) для баланса безопасности и производительности; RSA-2048 остаётся совместимым вариантом для Legacy-систем.

**Цепочка доверия (Chain of Trust)** — иерархия сертификатов: корневой CA -> промежуточный CA -> leaf-сертификат. В Gateway API критична правильная настройка: контроллер шлюза должен иметь доступ ко всем сертификатам цепочки, включая промежуточные.

---

## Основные концепции

### Подготовительные шаги (2025–2026)

Для реализации сценариев в современном окружении необходимо выполнить:

1.  **Установка Gateway API CRD (v1.1.0+):**
    ```bash
    kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
    ```
2.  **Установка cert-manager (v1.20+):**
    Контроллер должен быть запущен с поддержкой Gateway API:
    ```bash
    # Helm параметр
    installCRDs: true
    extraArgs:
      - --enable-gateway-api=true
    ```
3.  **Создание ClusterIssuer:** Настроенный ACME (Let's Encrypt) или внутренний (Vault/PKI) эмитент.

### Полный жизненный цикл (Journey) сертификата

Понимание полной цепочки от создания `Certificate` до готового TLS-секрета критично для диагностики:

1.  **Certificate** -> Создание CertificateRequest с CSR
2.  **CertificateRequest** -> Отправка CSR в Issuer (ClusterIssuer)
3.  **Order** -> Создание ACME Order на стороне CA (для Let's Encrypt)
4.  **Challenge** -> Размещение проверочного токена (HTTP-01/DNS-01/TLS-ALPN-01)
5.  **Самопроверка (Self-Check)** -> CA проверяет доступность токена
6.  **Выпуск сертификата** -> CA выдаёт leaf + промежуточные сертификаты
7.  **Secret** -> Сохранение сертификата и ключа в Kubernetes Secret
8.  **TLS Termination** -> Gateway Controller считывает Secret и настраивает TLS

**Временные рамки (Let's Encrypt):**
- Шаги 1-4: 10-30 секунд
- Шаг 5 (Self-Check): 5-30 секунд (ожидание DNS-пропагации для DNS-01: до 5 минут)
- Шаг 6-7: 5-10 секунд
- Общий Journey: 30 секунд - 5 минут (HTTP-01), до 10 минут (DNS-01)

### Правила SAN (Subject Alternative Names)

SAN определяют домены, для которых действителен сертификат. В Gateway API:

- **Каждый слушатель** с уникальным `hostname` требует отдельный сертификат (или wildcard)
- **Wildcard-сертификаты** (`*.example.com`) покрывают только один уровень поддоменов
- **Первый домен** в списке SAN становится основным (Subject) сертификата
- **cert-manager автоматически** извлекает SAN из поля `hostname` слушателя (при использовании gateway-shim)

**Правило:** Не указывайте SAN вручную, если используете gateway-shim. При явном создании Certificate перечислите ВСЕ домены из всех слушателей Gateway.

### Выбор алгоритма ключа

| Алгоритм | Размер ключа | Безопасность | Совместимость | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **ECDSA P-256** | 256 бит | Высокая | Хорошая (все современные клиенты) | Рекомендуется для Production |
| **ECDSA P-384** | 384 бита | Очень высокая | Ограниченная (старые клиенты) | Для highly-regulated сред |
| **RSA-2048** | 2048 бит | Средняя (ограничена NIST до 2030) | Отличная (все клиенты) | Legacy-системы, совместимость |
| **RSA-4096** | 4096 бит | Высокая | Отличная | Если нужен RSA, но с запасом |

**Практические рекомендации:**
- Для новых кластеров: **ECDSA P-256** (быстрее, меньше размер ключа, современная безопасность)
- Для смешанных сред: RSA-2048 (максимальная совместимость) или гибрид (ECDSA для Gateway, RSA для legacy Ingress)
- **Не используйте** ECDSA P-521 (ограниченная поддержка в ACME-клиентах)

---

### Архитектура интеграции

```mermaid
graph TD
    A[Certificate Resource] -->|создаёт| B[TLS Secret]
    B -->|ссылка в certificateRefs| C[Gateway Listener]
    D[Gateway Controller] -->|читает| C
    D -->|настраивает| E[Data Plane / Envoy / Cilium]
```

---

## Практические сценарии

### Сценарий 1: Базовый шлюз с явным ресурсом Certificate

**Цель:** Максимальный контроль над параметрами сертификата (алгоритмы, ротация, ARI).

**Certificate:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: infra-system
spec:
  secretName: api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - api.example.com
  privateKey:
    algorithm: ECDSA # Рекомендация 2026 года
    size: 256
```

**Gateway:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: infra-system
spec:
  gatewayClassName: cilium
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: api.example.com
    tls:
      mode: Terminate
      certificateRefs:
      - name: api-tls-secret
        namespace: infra-system
  allowedRoutes:
    namespaces:
      from: All
```

---

### Сценарий 2: Автоматический выпуск через аннотации (gateway-shim)

**Цель:** Простота настройки в стиле Ingress. cert-manager сам создаст ресурс `Certificate`.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: auto-tls-gateway
  namespace: default
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: envoy-gateway
  listeners:
  - name: https
    hostname: "app.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs:
      - name: app-tls-secret # Secret будет создан автоматически
    allowedRoutes:
      namespaces:
        from: All
```

---

### Сценарий 3: Несколько слушателей с индивидуальными сертификатами

**Цель:** Разделение TLS-конфигураций для разных доменов на одном физическом шлюзе.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-domain-gateway
  namespace: infra-system
spec:
  gatewayClassName: istio
  listeners:
  - name: https-main
    hostname: main.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: main-tls-secret}]
  - name: https-api
    hostname: api.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: api-tls-secret}]
```

---

### Сценарий 4: Wildcard-сертификат (DNS-01)

**Цель:** Обслуживание множества поддоменов одним сертификатом.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-tls
  namespace: infra-system
spec:
  secretName: wildcard-tls-secret
  issuerRef: 
    name: cloudflare-dns-issuer
    kind: ClusterIssuer
  dnsNames: 
    - "example.com"
    - "*.example.com"
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: wildcard-gateway
  namespace: infra-system
spec:
  gatewayClassName: cilium
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: wildcard-tls-secret}]
    allowedRoutes:
      namespaces: {from: All}
```

---

### Сценарий 5: Безопасный кросс-неймспейс доступ (ReferenceGrant)

**Цель:** Использование сертификата из защищенного хранилища в публичном шлюзе.

**ReferenceGrant (в namespace с сертификатом — `cert-storage`):**
```yaml
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-infra-gateway
  namespace: cert-storage
spec:
  from:
  - group: gateway.networking.k8s.io
    kind: Gateway
    namespace: infra-system
  to:
  - group: ""
    kind: Secret
    name: central-tls-secret
```

**Gateway (в namespace `infra-system`):**
```yaml
# ... фрагмент манифеста
    tls:
      mode: Terminate
      certificateRefs:
      - name: central-tls-secret
        namespace: cert-storage # Ссылка на другой namespace разрешена ReferenceGrant
```

---

### Сценарий 6: Self-Service TLS через ListenerSet (v1.21+ Stable)

**Цель:** Позволить разработчикам приложений управлять TLS самостоятельно, не имея прав на основной Gateway.

```yaml
apiVersion: gateway.networking.k8s.io/v1alpha1
kind: ListenerSet
metadata:
  name: app-team-listeners
  namespace: app-team
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    # Аннотация для прохождения HTTP-01 через 80 порт родительского Gateway
    acme.cert-manager.io/http01-parentreffallback: "true"
spec:
  parentRef:
    name: shared-gateway
    namespace: infra-system
  listeners:
  - name: https-app
    hostname: "app.team-a.example.com"
    port: 443
    protocol: HTTPS
    tls:
      mode: Terminate
      certificateRefs: [{name: team-a-tls-secret}]
```

---

### Сценарий 7: Сквозное шифрование (TLS Passthrough / mTLS)

**Цель:** Передача трафика до пода без расшифровки на шлюзе (для mTLS или строгой изоляции).

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: secure-gateway
spec:
  listeners:
  - name: tls-passthrough
    protocol: TLS
    port: 443
    tls: {mode: Passthrough}
---
apiVersion: gateway.networking.k8s.io/v1alpha2
kind: TLSRoute
metadata:
  name: backend-mtls-route
spec:
  parentRefs: [{name: secure-gateway}]
  rules:
  - backendRefs: [{name: mtls-enabled-service, port: 8443}]
```

---

### Сценарий 8: Нативный HTTP-to-HTTPS редирект

**Цель:** Принудительное использование защищенного соединения без сторонних аннотаций.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-to-https
  namespace: infra-system
spec:
  parentRefs:
  - name: public-gateway
    sectionName: http-80 # Ссылка на слушатель порта 80 в Gateway
  rules:
  - filters:
    - type: RequestRedirect
      requestRedirect:
        scheme: https
        statusCode: 301
```

---

### Сценарий 9: ACME (Let's Encrypt) через Gateway API Solver

**Цель:** Автоматизация прохождения проверки HTTP-01 для внешних сертификатов с использованием Gateway API. cert-manager будет автоматически создавать временные маршруты для подтверждения владения доменом.

**ClusterIssuer:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-gateway-api
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - group: gateway.networking.k8s.io
            kind: Gateway
            name: public-gateway
            namespace: infra-system
```

**Certificate:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: web-tls
  namespace: app-namespace
spec:
  secretName: web-tls-secret
  issuerRef:
    name: letsencrypt-gateway-api
    kind: ClusterIssuer
  dnsNames:
    - web.example.com
```

---

### Сценарий 10: GRPCRoute с TLS-терминацией

**Цель:** Обслуживание gRPC-сервисов через Gateway API с автоматическим TLS. GRPCRoute работает аналогично HTTPRoute, но использует протокол gRPC (HTTP/2).

**Gateway (с двумя слушателями — HTTPS для REST и gRPC):**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: multi-protocol-gateway
  namespace: infra-system
spec:
  gatewayClassName: cilium
  listeners:
  - name: https-rest
    hostname: api.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: api-tls-secret}]
  - name: grpc
    hostname: grpc.example.com
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs: [{name: grpc-tls-secret}]
```

**Certificate (для gRPC-домена):**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: grpc-tls
  namespace: infra-system
spec:
  secretName: grpc-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - grpc.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
```

**GRPCRoute:**
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata:
  name: my-grpc-service
  namespace: app-namespace
spec:
  parentRefs:
  - name: multi-protocol-gateway
    namespace: infra-system
    sectionName: grpc
  rules:
  - backendRefs:
    - name: grpc-service
      port: 8443
    matches:
    - method:
        service: myapp.v1.MyService
        method: MyMethod
```

**Верификация:**
```bash
# Проверка, что Gateway слушает gRPC-домен
kubectl get gateway multi-protocol-gateway -n infra-system -o jsonpath='{.spec.listeners[?(@.name=="grpc")]}' | jq .

# Проверка сертификата
kubectl get certificate grpc-tls -n infra-system -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# -> True

# Тест gRPC-подключения через grpcurl
kubectl run grpc-test --rm -it --image=fullstorydev/grpcurl -- \
  grpc.example.com:443 myapp.v1.MyService/MyMethod
```

**Особенности GRPCRoute:**
- Использует порт 443 (HTTPS) для gRPC, не отдельный порт
- Отличия от HTTPRoute: `method.service` и `method.method` в matches вместо `path`
- Сертификаты выпускаются тем же cert-manager, что и для HTTPRoute
- Необходимо отдельный `sectionName` в Gateway для gRPC-слушателя

---

### Сценарий 11: Путь от Staging к Production (полный Journey)

**Цель:** Безопасная настройка автоматического выпуска сертификатов через Let's Encrypt с тестированием на Staging перед переходом на Production.

**Шаг 1 — ClusterIssuer для Staging:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-key
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: public-gateway
            namespace: infra-system
```

**Шаг 2 — Тестовый Certificate (Staging):**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-tls-staging
  namespace: app-namespace
spec:
  secretName: test-tls-staging-secret
  issuerRef:
    name: letsencrypt-staging
    kind: ClusterIssuer
  dnsNames:
    - test.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
```

**Шаг 3 — Верификация Staging:**
```bash
# Проверка, что сертификат выпущен через Staging
kubectl get certificate test-tls-staging -n app-namespace -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# -> True

# Проверка Issuer (Staging)
kubectl get certificate test-tls-staging -n app-namespace -o jsonpath='{.spec.issuerRef.name}'
# -> letsencrypt-staging

# Проверка сертификата (должен быть от Fake LE Root X1)
kubectl get secret test-tls-staging-secret -n app-namespace -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -issuer
# -> issuer=CN = Fake LE Root X1
```

**Шаг 4 — Production ClusterIssuer (после успешного теста):**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: public-gateway
            namespace: infra-system
```

**Шаг 5 — Замена Issuer в Certificate:**
```bash
# Обновить issuerRef в Certificate с letsencrypt-staging на letsencrypt-prod
kubectl patch certificate test-tls-staging -n app-namespace --type merge -p \
  '{"spec":{"issuerRef":{"name":"letsencrypt-prod","kind":"ClusterIssuer"}}}'

# Или: удалить Staging-сертификат и создать новый с Production
kubectl delete certificate test-tls-staging -n app-namespace
kubectl delete secret test-tls-staging-secret -n app-namespace
# Применить манифест с letsencrypt-prod
```

**Шаг 6 — Финальная верификация (Production):**
```bash
# Проверка, что сертификат выпущен через Production
kubectl get certificate test-tls -n app-namespace -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# -> True

# Проверка Issuer (Production)
kubectl get certificate test-tls -n app-namespace -o jsonpath='{.spec.issuerRef.name}'
# -> letsencrypt-prod

# Проверка сертификата (должен быть от ISRG Root X1)
kubectl get secret test-tls-secret -n app-namespace -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -issuer
# -> issuer=CN = ISRG Root X1

# Проверка срока действия
kubectl get secret test-tls-secret -n app-namespace -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -dates
# -> notBefore=... notAfter=... (90 дней от момента выпуска)
```

**Почему использовать Staging перед Production:**
- Let's Encrypt имеет строгие Rate Limits: 50 сертификатов/домен/неделю (Production)
- Staging не имеет этих ограничений (до 30,000 сертификатов/неделю)
- Ошибки конфигурации (NetworkPolicy, DNS, Gateway) видны сразу
- Staging-сертификаты **не доверяются** клиентами — используйте только для тестирования

---

### Сценарий 12: DNS-01 проверка через Cloudflare

**Цель:** Автоматический выпуск wildcard-сертификатов через DNS-01 с использованием Cloudflare API.

**ClusterIssuer:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01-cloudflare
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-dns01-cloudflare-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

**Secret с API-токеном:**
```bash
kubectl create secret generic cloudflare-api-token \
  --namespace=cert-manager \
  --from-literal=api-token=your-cloudflare-api-token
```

**Wildcard-сертификат:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-example
  namespace: infra-system
spec:
  secretName: wildcard-example-secret
  issuerRef:
    name: letsencrypt-dns01-cloudflare
    kind: ClusterIssuer
  dnsNames:
    - "example.com"
    - "*.example.com"
  privateKey:
    algorithm: ECDSA
    size: 256
```

**Альтернативные DNS-провайдеры:**

| Провайдер | Поле в solver | Тип аутентификации |
| :--- | :--- | :--- |
| **Cloudflare** | `cloudflare.apiTokenSecretRef` | API Token (рекомендуется) |
| **Route53** | `route53.accessKeyIDSecretRef` | IAM Access Key + Secret Key |
| **Google Cloud DNS** | `cloudDNS.serviceAccountSecretRef` | Service Account JSON |
| **Azure DNS** | `azureDNS.clientSecretSecretRef` | Service Principal + Secret |
| **DigitalOcean** | `digitalocean.apiTokenSecretRef` | Personal Access Token |

**Верификация DNS-01:**
```bash
# Проверка TXT-записи (может потребоваться ожидание DNS-пропагации)
dig TXT _acme-challenge.example.com

# Проверка Order и Challenge
kubectl get order -n infra-system
kubectl get challenge -n infra-system

# Просмотр статуса Challenge
kubectl describe challenge -n infra-system

# Проверка сертификата
kubectl get certificate wildcard-example -n infra-system -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
# -> True
```

---

### Сценарий 13: Multi-Issuer (несколько Issuer для разных namespace)

**Цель:** Настройка разных Issuer для разных команд/проектов с изолированными ключами и параметрами.

**Architecture:**
- Namespace `team-a`: ClusterIssuer `letsencrypt-prod-a` (email: team-a@example.com)
- Namespace `team-b`: ClusterIssuer `letsencrypt-prod-b` (email: team-b@example.com)
- Namespace `infra-system`: ClusterIssuer `internal-pki` (Vault PKI)

**ClusterIssuer для team-a:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod-a
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: team-a@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-a-key
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: shared-gateway
            namespace: infra-system
```

**ClusterIssuer для team-b (с DNS-01 для wildcard):**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod-b
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: team-b@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-b-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

**Certificate в namespace team-a:**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: app-tls
  namespace: team-a
spec:
  secretName: app-tls-secret
  issuerRef:
    name: letsencrypt-prod-a
    kind: ClusterIssuer
  dnsNames:
    - app-a.example.com
```

**Certificate в namespace team-b (wildcard):**
```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-tls
  namespace: team-b
spec:
  secretName: wildcard-tls-secret
  issuerRef:
    name: letsencrypt-prod-b
    kind: ClusterIssuer
  dnsNames:
    - "*.team-b.example.com"
```

**Верификация Multi-Issuer:**
```bash
# Проверка ClusterIssuers
kubectl get clusterissuer
# NAME                    READY   AGE
# letsencrypt-prod-a      True    1d
# letsencrypt-prod-b      True    1d

# Проверка сертификатов в разных namespace
kubectl get certificate -A -o custom-columns=\
  NAMESPACE:.metadata.namespace,\
  NAME:.metadata.name,\
  ISSUER:.spec.issuerRef.name,\
  READY:.status.conditions[?(@.type=="Ready")].status

# Проверка, что ключи изолированы
kubectl get secret letsencrypt-prod-a-key -n cert-manager -o jsonpath='{.metadata.name}'
kubectl get secret letsencrypt-prod-b-key -n cert-manager -o jsonpath='{.metadata.name}'
# -> Два разных Secret с разными account keys
```

---

### Сценарий 14: Проверка цепочки доверия (Chain of Trust)

**Цель:** Верификация полной цепочки сертификатов: leaf -> intermediate -> root.

**Контекст:** В Gateway API критично убедиться, что контроллер шлюза (Envoy, Cilium, Istio) корректно загружает промежуточные сертификаты. Неполная цепочка приводит к ошибкам `certificate verify failed` на стороне клиентов.

**Полная цепочка Let's Encrypt:**
```
ISRG Root X1 (корневой) -> R3 (промежуточный) -> leaf-сертификат
```

**Проверка через openssl:**
```bash
# Извлечение leaf-сертификата
kubectl get secret api-tls-secret -n infra-system \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/leaf.pem

# Извлечение промежуточного сертификата (второй сертификат в цепочке)
kubectl get secret api-tls-secret -n infra-system \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  awk 'BEGIN{n=0} /^-----BEGIN CERTIFICATE-----/{n++} n==2' > /tmp/intermediate.pem

# Проверка leaf-сертификата
openssl x509 -in /tmp/leaf.pem -noout -subject -issuer -dates
# -> subject=CN = api.example.com
# -> issuer=CN = R3, O = Let's Encrypt

# Проверка промежуточного сертификата
openssl x509 -in /tmp/intermediate.pem -noout -subject -issuer
# -> subject=CN = R3, O = Let's Encrypt
# -> issuer=CN = ISRG Root X1, O = Internet Security Research Group

# Проверка подписи leaf-сертификата промежуточным
openssl verify -CAfile /tmp/intermediate.pem /tmp/leaf.pem
# -> /tmp/leaf.pem: OK
```

**Верификация через curl:**
```bash
# Проверка TLS-подключения с выводом цепочки
curl -v https://api.example.com 2>&1 | grep -A 2 "SSL certificate"
# -> *  SSL certificate verify ok:
# -> *    subject: CN = api.example.com
# -> *    start date: ...
# -> *    expire date: ...
# -> *    issuer: CN = R3, O = Let's Encrypt
```

**Проверка цепочки через кubectl:**
```bash
# Просмотр всех сертификатов в Secret (включая промежуточные)
kubectl get secret api-tls-secret -n infra-system \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  awk '/BEGIN CERTIFICATE/{n++} {print > "/tmp/cert-" n ".pem"}'

# Подсчёт количества сертификатов в цепочке
ls -1 /tmp/cert-*.pem | wc -l
# -> 2 (leaf + intermediate) или 3 (если есть второй промежуточный)

# Проверка валидности цепочки
openssl verify -untrusted /tmp/cert-2.pem /tmp/cert-1.pem
```

**Типичные проблемы:**
- **Неполная цепочка:** Контроллер шлюза загружает только leaf-сертификат без промежуточного -> `certificate verify failed`
- **Невалидный промежуточный:** Устаревший промежуточный сертификат -> `certificate has expired`
- **Несоответствие SAN:** Сертификат выпущен для `api.example.com`, но клиент обращается по IP -> `certificate verify failed`

---

## Дополнительная информация

### Рекомендации по эксплуатации

1.  **ARI и автоматизация**: В cert-manager v1.21+ ARI включен по умолчанию. Рекомендуется удалять `renewBefore` из ресурсов `Certificate`, чтобы передать управление окном продления протоколу ACME.
2.  **Диагностика фидбека**: Состояние выпуска сертификата теперь транслируется в `status.conditions` ресурсов `Gateway` и `ListenerSet` (тип `ResolvedRefs`), что позволяет отлаживать TLS без прямого доступа к логам cert-manager.
3.  **Безопасность RBAC**: Ограничивайте права на создание `ListenerSet` и `ReferenceGrant`, так как они позволяют манипулировать точками входа в кластер.
4.  **Staging перед Production**: Всегда тестируйте конфигурацию через `letsencrypt-staging` перед использованием `letsencrypt-prod`. Rate Limits на Production: 50 сертификатов/домен/неделю.
5.  **ECDSA по умолчанию**: Используйте `algorithm: ECDSA, size: 256` для новых сертификатов. RSA-2048 допустим только для Legacy-совместимости.
6.  **NetworkPolicy**: Убедитесь, что контроллер cert-manager имеет исходящий доступ к порту 443 (ACME API) и порту 53 (DNS). Для Gateway Controller необходим входящий доступ на порту 80 (HTTP-01 проверки).
7.  **Cleanup при удалении**: При удалении `Certificate` автоматически удаляются `CertificateRequest`, `Order`, `Challenge` и `Secret`. `ClusterIssuer` и его account key Secret удаляются вручную.

### Быстрая верификация (通用 команды)

```bash
# Проверка всех сертификатов в кластере
kubectl get certificate -A -o custom-columns=\
  NAMESPACE:.metadata.namespace,\
  NAME:.metadata.name,\
  READY:.status.conditions[?(@.type=="Ready")].status,\
  SECRET:.spec.secretName

# Проверка всех Issuer/ClusterIssuer
kubectl get issuer,clusterissuer -A

# Проверка pending Order
kubectl get order -A

# Проверка pending Challenge
kubectl get challenge -A

# Просмотр ошибок в логах cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=200 | grep -i "error\|fail\|invalid"

# Проверка, что Secret содержит валидный сертификат
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -text | grep -A 2 "Validity"
```

### Cleanup ресурсов

При удалении ресурсов cert-manager автоматически очищает зависимые объекты:

| Удаляемый ресурс | Автоудаление | Зависимые ресурсы |
| :--- | :--- | :--- |
| `Certificate` | Да | `CertificateRequest`, `Order`, `Challenge`, `Secret` (если указан `secretName`) |
| `CertificateRequest` | Да | `Order`, `Challenge` |
| `Order` | Да | `Challenge` |
| `Challenge` | Нет | -- |
| `ClusterIssuer` | Нет | Account Key Secret (удаляется вручную) |
| `Issuer` | Нет | Account Key Secret (удаляется вручную) |
| `Gateway` | Да | `ReferenceGrant` не удаляется автоматически |
| `ListenerSet` | Да | `Certificate` и `Secret` не удаляются автоматически |

**Полный cleanup-сценарий:**
```bash
# Удаление сертификата и зависимых ресурсов
kubectl delete certificate <name> -n <namespace>

# Удаление Gateway ( certificates, HTTPRoutes будут отвязаны)
kubectl delete gateway <name> -n <namespace>

# Удаление ListenerSet
kubectl delete listenerset <name> -n <namespace>

# Удаление ClusterIssuer + account key Secret
kubectl delete clusterissuer <name>
kubectl delete secret <privateKeySecretRef> -n cert-manager

# Удаление временных ACME-маршрутов (если остались)
kubectl delete httproute -A -l "acme.cert-manager.io/http01=true"
```

### Смотрите также

- **[Определения и концепции Gateway API](./definitions_and_concepts.md)** — архитектура и ролевая модель.
- **[Gateway API: Дополнительные темы](./advanced_topics.md)** — глубокая диагностика и Hostname-конфликты.
- **[Cert-manager: Определения](../../definitions.md)** — базовые ресурсы контроллера.
