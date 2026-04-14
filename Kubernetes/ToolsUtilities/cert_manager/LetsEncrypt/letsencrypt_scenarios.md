# Let's Encrypt: Практические сценарии

## Definitions

**ClusterIssuer** — общекластерный ресурс cert-manager, представляющий ACME-аккаунт Let's Encrypt. Доступен из любого namespace.

**Certificate** — запрос на выпуск сертификата. Cert-manager автоматически создаёт Order, проходит Challenges и обновляет Secret.

> **Базовые концепции:** [index.md](../index.md) | **CRD-спецификация:** [definitions.md](../../definitions.md)

---

## Basic Concepts

### Структура ClusterIssuer

```
ClusterIssuer
├── acme.server          # ACME-сервер (production/staging)
├── acme.email           # Уведомления об истечении
├── acme.privateKeySecretRef  # ACME Account Key (хранить в backup!)
└── acme.solvers         # Методы проверки владения (http01, dns01)
```

### Параметры Certificate

| Поле | Значение (45 дней) | Значение (90 дней, legacy) |
| :--- | :--- | :--- |
| `duration` | `1080h` (45 дней) | `2160h` (90 дней) |
| `renewBefore` | `168h` (7 дней) | `360h` (15 дней) |

> **Важно:** Let's Encrypt переходит на 45-дневные сертификаты в 2026. cert-manager 1.15+ с поддержкой ARI обновит `renewBefore` автоматически. Подробнее: [letsencrypt_concepts](./letsencrypt_concepts.md).

### Сравнение solvers для сценариев

| Сценарий | Solver | Wildcard | Требование |
| :--- | :--- | :--- | :--- |
| Публичный Ingress | HTTP-01 | ❌ | Доступность порта 80 извне |
| Wildcard / нет HTTP | DNS-01 | ✅ | API-ключ DNS-провайдера |
| Внутренний сервис | DNS-01 | ✅ | DNS webhook |

---

## Practical Scenarios

### Сценарий 1: ClusterIssuer с HTTP-01

**Применение:** Публичный сертификат для Ingress (без wildcard).

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

**Запрос сертификата:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: default
spec:
  secretName: example-com-tls
  duration: 1080h       # 45 дней (2026+)
  renewBefore: 168h     # 7 дней до истечения
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - www.example.com
```

### Сценарий 2: DNS-01 (Cloudflare) — Wildcard

**Применение:** Wildcard-сертификат `*.example.com`.

**1. Создать Secret с API-ключом:**

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

**3. Запрос wildcard-сертификата:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-wildcard
  namespace: default
spec:
  secretName: example-wildcard-tls
  duration: 1080h       # 45 дней
  renewBefore: 168h     # 7 дней
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - example.com
    - "*.example.com"
```

### Сценарий 3: DNS-01 (Yandex Cloud DNS)

**Применение:** Wildcard для доменов в Yandex Cloud.

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

### Сценарий 4: Staging для тестирования

**Применение:** Отладка конфигурации без риска превысить лимиты production.

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

> **Важно:** Создайте отдельный `ClusterIssuer` для staging, не переиспользуйте production. Staging-сертификаты не доверяются браузерами.

### Сценарий 5: Несколько Issuer (разделение окружений)

**Применение:** Раздельные production/staging Issuer для разных доменов.

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
# Staging Issuer
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

**Использование:**

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

---

## Additional Information

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| HTTP-01 ClusterIssuer | **10** | cert-manager docs, стандартный паттерн |
| DNS-01 Cloudflare | **10** | Подтверждено в cert-manager 1.13+ |
| Yandex Cloud DNS webhook | **8** | Community webhook, может меняться |
| Staging configuration | **10** | Официальное тестовое окружение LE |
| 45-дневные duration | **10** | [letsencrypt.org 2026-02-24](https://letsencrypt.org/2026/02/24/rate-limits-45-day-certs) |

**Связанные документы:** [углублённые концепции](./letsencrypt_concepts.md), [диагностика](./letsencrypt_advanced.md), [cert_manager CRD](../../definitions.md).
