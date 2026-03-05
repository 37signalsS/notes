# Let's Encrypt: Публичные сертификаты через ACME

## Определения

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации, использующий протокол ACME для выдачи TLS-сертификатов.

**ACME (Automatic Certificate Management Environment)** — протокол (RFC 8555) для автоматизированного получения и продления сертификатов.

**Ограничения Let's Encrypt:**

| Лимит | Значение | Период |
| :--- | :--- | :--- |
| Сертификатов на домен | 50 | 7 дней |
| Запросов на регистрацию | 10 | 3 часа |
| Wildcard-сертификатов | 50 | 7 дней |
| Срок действия | 90 дней | — |

---

## Основные концепции

### ACME Solvers (проверки владения)

| Метод | Принцип | Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Файл по `http://<domain>/.well-known/acme-challenge/` | ❌ Нет | Публичный Ingress |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ Да | Доступ к DNS API |
| **TLS-ALPN-01** | TLS-соединение на порт 443 | ❌ Нет | Прямой доступ к 443 |

### Окружения Let's Encrypt

| Окружение | URL | Назначение |
| :--- | :--- | :--- |
| **Production** | `https://acme-v02.api.letsencrypt.org/directory` | Боевые сертификаты |
| **Staging** | `https://acme-staging-v02.api.letsencrypt.org/directory` | Тестирование (лимиты выше) |

> **Важно:** Staging использует отдельные тестовые CA, которые не доверяются браузерами. Используйте для отладки конфигурации.

---

## Практические сценарии

### Сценарий 1: Базовый ClusterIssuer с HTTP-01

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

**Параметры:**

| Поле | Описание |
| :--- | :--- |
| `server` | ACME-сервер Let's Encrypt |
| `email` | Уведомления об истечении, восстановлении |
| `privateKeySecretRef` | Secret для хранения ACME-ключа |
| `ingressClassName` | Ingress Controller для solver |

**Запрос сертификата:**

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

---

### Сценарий 2: DNS-01 solver (Cloudflare)

**Цель:** Получить wildcard-сертификат или когда нет публичного HTTP.

#### Подготовка

1. Создать API-ключ Cloudflare в Secret:

```bash
kubectl create secret generic cloudflare-api-key \
  --from-literal=api-key=YOUR_CLOUDFLARE_API_KEY \
  -n cert-manager
```

1. Создать ClusterIssuer:

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

#### Запрос wildcard-сертификата

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

---

### Сценарий 3: DNS-01 solver (Yandex Cloud DNS)

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

**Требуется:** cert-manager Webhook для Yandex Cloud DNS (отдельный Helm-чарт).

---

### Сценарий 4: Staging для тестирования

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

---

### Сценарий 5: Несколько Issuer для разных доменов

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

## Дополнительная информация

### Диагностика

```bash
# Статус Certificate
kubectl get certificate example-com -o wide

# Детали Order
kubectl get order -l cert-manager.io/certificate-name=example-com

# Детали Challenge
kubectl get challenge -l cert-manager.io/certificate-name=example-com

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager | grep -i acme
```

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `403 Forbidden` | Неправильный API-ключ DNS | Проверить права доступа |
| `Connection timed out` | HTTP-01 недоступен извне | Проверить Ingress, firewall |
| `rateLimitReached` | Превышен лимит Let's Encrypt | Использовать staging, подождать |
| `DNS propagation` | TXT-запись не видна | Подождать 1-5 минут |

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| ACME протокол | **10** | RFC 8555, Let's Encrypt документация |
| HTTP-01 solver | **10** | Стандартный паттерн cert-manager |
| DNS-01 solver | **10** | Подтверждено для wildcard |
| Staging окружение | **10** | Официальное тестовое окружение LE |

### Best Practices

1. **Всегда используйте staging** для первичной настройки
2. **Настройте уведомления** на email о продлении
3. **Мониторьте статус** Certificate через Prometheus/Grafana
4. **Избегайте лимитов** — кэшируйте заказы при разработке

---
