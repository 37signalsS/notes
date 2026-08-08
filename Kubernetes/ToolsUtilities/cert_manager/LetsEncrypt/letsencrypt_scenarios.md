# Let's Encrypt: Практические сценарии в Kubernetes

## Определения

**ClusterIssuer** — общекластерный ресурс cert-manager, описывающий метод взаимодействия с центром сертификации (CA). В отличие от обычного `Issuer`, он доступен для всех пространств имен в кластере.

**Certificate** — ресурс, определяющий желаемые параметры TLS-сертификата (DNS-имена, алгоритм ключа, срок действия). На его основе cert-manager инициирует процесс выпуска.

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — современный алгоритм цифровой подписи, обеспечивающий более высокую безопасность и производительность при меньшем размере ключа по сравнению с RSA.

**preferredChain** — параметр, позволяющий выбрать конкретную цепочку доверия (например, ISRG Root X1), если CA предлагает несколько альтернативных путей.

---

## Основные концепции

### Жизненный цикл заказа (Order Flow)

Для успешного применения сценариев важно понимать последовательность действий контроллера:
1.  **Создание Certificate**: Пользователь определяет параметры.
2.  **CertificateRequest**: Контроллер генерирует CSR.
3.  **Order & Challenge**: cert-manager запрашивает у Let's Encrypt проверку владения доменом.
4.  **Секрет (Secret)**: После успешной проверки сертификат сохраняется в Kubernetes Secret.

### Подготовка к 45-дневным сертификатам (2025–2026)

В связи с планируемым переходом Let's Encrypt на 45-дневные сертификаты, рекомендуется использовать следующие параметры в ресурсах `Certificate` для автоматизации через ARI:

| Параметр | Рекомендация | Комментарий |
| :--- | :--- | :--- |
| `duration` | `1080h` (45 дней) | Соответствует будущему стандарту |
| `renewBefore` | — | **Рекомендуется не указывать**, чтобы cert-manager использовал ARI |
| `privateKey.algorithm` | `ECDSA` | Предпочтительно для новых инсталляций |

---

## Практические сценарии

### Сценарий 1: Публичный Ingress с HTTP-01 (RSA)

Классический сценарий для большинства веб-приложений.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-http01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-http01-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: web-app-tls
  namespace: prod
spec:
  secretName: web-app-tls-secret
  issuerRef:
    name: letsencrypt-http01
    kind: ClusterIssuer
  commonName: app.example.com
  dnsNames:
    - app.example.com
```

### Сценарий 2: Wildcard сертификат через DNS-01 (Cloudflare ECDSA)

Использование API Cloudflare для выпуска сертификата на все поддомены с использованием эллиптических кривых.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01-ecdsa
spec:
  acme:
    email: admin@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-dns01-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: wildcard-ecdsa-tls
  namespace: prod
spec:
  secretName: wildcard-ecdsa-tls-secret
  issuerRef:
    name: letsencrypt-dns01-ecdsa
    kind: ClusterIssuer
  commonName: "*.example.com"
  dnsNames:
    - "*.example.com"
    - "example.com"
  privateKey:
    algorithm: ECDSA
    size: 256
```

### Сценарий 3: Управление цепочкой доверия (preferredChain)

Сценарий необходим, если клиенты (например, старые устройства) требуют специфического корневого сертификата.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: legacy-compat-tls
spec:
  secretName: legacy-compat-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: legacy.example.com
  issuerOptions:
    # Явный выбор цепочки ISRG Root X1 (RSA)
    preferredChain: "ISRG Root X1"
```

### Сценарий 4: Интеграция с Gateway API и HTTPRoute

Современный метод настройки TLS через аннотации Gateway API.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: main-gateway
  namespace: istio-system
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  gatewayClassName: istio
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    hostname: "*.example.com"
    tls:
      mode: Terminated
      certificateRefs:
      - name: gateway-wildcard-tls
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-route
  namespace: backend
spec:
  parentRefs:
  - name: main-gateway
    namespace: istio-system
  hostnames:
  - "api.example.com"
  rules:
  - backendRefs:
    - name: api-service
      port: 8080
```

### Сценарий 5: Миграция с Staging на Production

Алгоритм безопасного тестирования конфигурации без риска блокировок.

1.  **Создание Staging Issuer**: Используйте URL `https://acme-staging-v02.api.letsencrypt.org/directory`.
2.  **Выпуск тестового сертификата**: Убедитесь, что `Challenge` проходит успешно.
3.  **Переключение**: Обновите `issuerRef` в ресурсе `Certificate` на Production Issuer. cert-manager автоматически перевыпустит сертификат.

---

## Дополнительная информация

### Рекомендации по эксплуатации (Best Practices)

1.  **Разделение Issuer**: Рекомендуется иметь отдельные `ClusterIssuer` для HTTP-01 и DNS-01 проверок.
2.  **Использование ECDSA**: С 2025 года ECDSA является предпочтительным выбором для повышения производительности TLS-handshake на мобильных устройствах.
3.  **Контроль лимитов**: При массовом перевыпуске (например, при миграции кластера) следите за лимитом `Duplicate Certificates` (5 в неделю). Использование ARI минимизирует этот риск.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — архитектура ARI, CT-логи и безопасность.
- **[Диагностика и Troubleshooting](./letsencrypt_advanced.md)** — решение проблем с прохождением проверок.
- **[Cert-manager: Определения](../../definitions.md)** — базовая структура ресурсов контроллера.

---
