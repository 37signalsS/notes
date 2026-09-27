# DNS-провайдеры для cert-manager

## Определения

**DNS-01 Challenge** — метод подтверждения владения доменом через создание TXT-записи `_acme-challenge.<domain>`. Используется для wildcard-сертификатов (`*.example.com`) и когда HTTP-01 недоступен (например, сервёр за CDN/balancer).

**DNS Provider (DNS-провайдер)** — сервис, предоставляющий API для управления DNS-записями. cert-manager интегрируется с провайдерами через webhook-плагины или встроенные солверы для автоматического создания TXT-записей.

**Webhook DNS Solver** — внешний плагин, реализующий интерфейс `acme.cert-manager.io/v1alpha1.DNS01Solver`. Позволяет добавлять поддержку произвольных DNS-провайдеров без изменения cert-manager.

---

## Основные концепции

### Поддерживаемые DNS-провайдеры

| Провайдер | Тип интеграции | Wildcard | Примечания |
| :--- | :--- | :--- | :--- |
| **Cloudflare** | Встроенный | Да | Рекомендуется, API-токен |
| **AWS Route53** | Встроенный | Да | IAM credentials или IRSA |
| **Google Cloud DNS** | Встроенный | Да | ServiceAccount key |
| **Azure DNS** | Webhook | Да | `cert-manager-webhook-azure` |
| **Yandex Cloud DNS** | Webhook | Да | `cert-manager-webhook-yandex` |
| **DigitalOcean** | Webhook | Да | `cert-manager-webhook-digitalocean` |
| **GoDaddy** | Webhook | Да | Ограниченная поддержка |
| **PowerDNS** | Webhook | Да | Self-hosted |
| **RFC2136** | Встроенный | Да | Для собственных DNS-серверов |

### Когда использовать DNS-01 вместо HTTP-01

| Сценарий | HTTP-01 | DNS-01 |
| :--- | :--- | :--- |
| **Wildcard сертификаты** | Невозможно | Обязательно |
| **Сервер за балансировщиком** | Требует аннотаций | Работает |
| **Нет доступа к порту 80** | Невозможно | Работает |
| **Внутренние домены** | Невозможно | Работает |
| **Мультидоменные сертификаты** | Ограничен | Работает |

---

## Практические сценарии

### Сценарий 1: Cloudflare

```yaml
# 1. Создание Secret с API-токеном
apiVersion: v1
kind: Secret
metadata:
  name: cloudflare-api-token
  namespace: cert-manager
type: Opaque
stringData:
  api-token: "your-cloudflare-api-token"
---
# 2. ClusterIssuer с DNS-01 solver
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsZones:
        - "example.com"
```

**Диагностика:**
```bash
# Проверка TXT-записи
dig +short TXT _acme-challenge.example.com @8.8.8.8

# Проверка через Cloudflare API
curl -X GET "https://api.cloudflare.com/client/v4/zones/<zone_id>/dns_records?type=TXT&name=_acme-challenge.example.com" \
  -H "Authorization: Bearer <api_token>" | jq '.result[].content'
```

### Сценарий 2: AWS Route53

```yaml
# 1. Создание Secret с IAM credentials
apiVersion: v1
kind: Secret
metadata:
  name: route53-credentials
  namespace: cert-manager
type: Opaque
stringData:
  access-key-id: "AKIA..."
  secret-access-key: "wJal..."
---
# 2. ClusterIssuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        route53:
          accessKeyIDSecretRef:
            name: route53-credentials
            key: access-key-id
          secretAccessKeySecretRef:
            name: route53-credentials
            key: secret-access-key
          region: us-east-1
```

**Альтернатива (IRSA для EKS):**
```yaml
solvers:
- dns01:
    route53:
      role: "arn:aws:iam::123456789:role/cert-manager-route53"
      region: us-east-1
```

### Сценарий 3: Google Cloud DNS

```yaml
# 1. Secret с ServiceAccount key
apiVersion: v1
kind: Secret
metadata:
  name: clouddns-service-account
  namespace: cert-manager
type: Opaque
stringData:
  key.json: |
    {
      "type": "service_account",
      "project_id": "your-project",
      ...
    }
---
# 2. ClusterIssuer
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        cloudDNS:
          project: your-project
          serviceAccountSecretRef:
            name: clouddns-service-account
            key: key.json
```

### Сценарий 4: Wildcard-сертификат с DNS-01

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
      name: letsencrypt-prod-account-key
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
  name: wildcard-example
  namespace: production
spec:
  secretName: wildcard-example-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - "*.example.com"
  - "example.com"  # Без wildcard SAN нужен отдельный сертификат
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Always
```

### Сценарий 5: Несколько доменов с разными провайдерами

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
      name: letsencrypt-prod-account-key
    solvers:
    # Cloudflare для example.com
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
      selector:
        dnsZones:
        - "example.com"
    # Route53 для example.org
    - dns01:
        route53:
          accessKeyIDSecretRef:
            name: route53-credentials
            key: access-key-id
          secretAccessKeySecretRef:
            name: route53-credentials
            key: secret-access-key
          region: us-east-1
      selector:
        dnsZones:
        - "example.org"
```

---

## Дополнительная информация

### Типичные проблемы DNS-01

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| **TXT-запись не создается** | Challenge в pending | Проверьте API-токен и права доступа |
| **DNS Propagation** | Challenge проходит нестабильно | Уменьшите TTL до 300 сек |
| **CAA-записи** | `CAA prevents issuance` | Добавьте `letsencrypt.org` в CAA |
| **Внутренний DNS** | Challenge проходит извне, но не из кластера | Настройте `--dns01-recursive-nameservers` |
| **Rate Limit** | 429 при mass issuance | Используйте Staging |

### Рекомендации

1. **API-токены:** Используйте минимальные права (только Zone:DNS:Edit)
2. **TTL:** Уменьшите до 300 сек перед массовой выдачей сертификатов
3. **CAA:** Убедитесь, что CAA-записи разрешают Let's Encrypt
4. **Мониторинг:** Настройте алерт на `certmanager_http_acme_client_request_count`
5. **Staging:** Тестируйте новую конфигурацию на Staging перед Production

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — общие принципы.
- **[Let's Encrypt: Сетевая безопасность](../LetsEncrypt/letsencrypt_network_security.md)** — сетевые требования.
- **[Let's Encrypt: Сценарии](../LetsEncrypt/letsencrypt_scenarios.md)** — типичные проблемы ACME.
