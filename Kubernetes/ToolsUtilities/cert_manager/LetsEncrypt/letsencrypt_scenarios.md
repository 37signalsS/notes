# Let's Encrypt: Практические сценарии

## 1. Базовый ClusterIssuer с HTTP-01

**Цель:** Получить публичный сертификат для Ingress.

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
        ingress:
          ingressClassName: nginx
```

### Параметры

| Поле | Описание |
| :--- | :--- |
| `server` | ACME-сервер Let's Encrypt |
| `email` | Уведомления об истечении, восстановлении |
| `privateKeySecretRef` | Secret для хранения ACME-ключа |
| `ingressClassName` | Ingress Controller для solver |

### Запрос сертификата

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: default
spec:
  secretName: example-com-tls
  duration: 2160h  # 90 дней
  renewBefore: 360h  # 15 дней
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - www.example.com
```

## 2. DNS-01 solver (Cloudflare)

**Цель:** Получить wildcard-сертификат или когда нет публичного HTTP.

### Подготовка

**1. Создать API-ключ Cloudflare в Secret:**

```bash
kubectl create secret generic cloudflare-api-key \
  --from-literal=api-key=YOUR_CLOUDFLARE_API_KEY \
  -n cert-manager
```

**2. Создать ClusterIssuer:**

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
    - dns01:
        cloudflare:
          email: admin@example.com
          apiKeySecretRef:
            name: cloudflare-api-key
            key: api-key
```

### Запрос wildcard-сертификата

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-wildcard
  namespace: default
spec:
  secretName: example-wildcard-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - "*.example.com"  # Wildcard
```

## 3. DNS-01 solver (Yandex Cloud DNS)

**Цель:** Использовать Yandex Cloud DNS для проверок.

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
    - dns01:
        webhook:
          groupName: acme.cert-manager.io
          solverName: yandex-cloud-dns
          config:
            zoneID: "your-zone-id"
            credentialsSecretRef:
              name: yandex-cloud-credentials
              key: service-account-key
```

> **Требуется:** cert-manager Webhook для Yandex Cloud DNS (отдельный Helm-чарт).

## 4. Staging для тестирования

**Цель:** Протестировать конфигурацию без лимитов production.

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
        ingress:
          ingressClassName: nginx
```

> **Важно:** После успешного тестирования переключитесь на production, создав отдельный `ClusterIssuer`.

## 5. Несколько Issuer для разных доменов

**Цель:** Разделить сертификаты для разных доменов/окружений.

```yaml
# Production Issuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod-main
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@main.com
    privateKeySecretRef:
      name: letsencrypt-prod-main-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
---
# Staging Issuer для тестов
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging-test
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: test@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-test-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
```

### Использование

```yaml
# Production Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: main-domain
spec:
  secretName: main-domain-tls
  issuerRef:
    name: letsencrypt-prod-main
    kind: ClusterIssuer
  dnsNames:
    - main.com

# Staging Certificate
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-domain
spec:
  secretName: test-domain-tls
  issuerRef:
    name: letsencrypt-staging-test
    kind: ClusterIssuer
  dnsNames:
    - test.example.com
```

## Связанные документы

- **[Основные концепции](./letsencrypt_concepts.md)** — определения, ACME solvers, окружения
- **[Дополнительные темы](./letsencrypt_advanced.md)** — диагностика, ошибки, best practices
- **[cert_manager](../cert_manager_overview.md)** — обзор cert-manager
