# Cert-manager: Определения и основные понятия

## Definitions

**Cert-manager** — нативный Kubernetes-контроллер для автоматизации управления TLS-сертификатами. Получает, продлевает и отзывает сертификаты, минимизируя ручное вмешательство. Официальная документация: [cert-manager.io](https://cert-manager.io/).

**Ключевые возможности:**

| Возможность | Описание |
| :--- | :--- |
| **Автоматизация получения** | Интеграция с Let's Encrypt, HashiCorp Vault, Venafi, приватными CA, self-signed |
| **Автопродление** | Мониторинг срока действия, автоматическое продление до истечения |
| **Ingress-интеграция** | Автоматическое создание сертификатов для Ingress через аннотации |
| **Gateway API** | Поддержка Gateway API (флаг `--enable-gateway-api`) |
| **Жизненный цикл** | Создание, продление, отзыв сертификатов через CRD |

**Связанные темы:**

- Установка: [installation.md](./installation.md)
- Let's Encrypt / ACME: [LetsEncrypt/index.md](./LetsEncrypt/index.md)
- Ingress-интеграция: [ingress/overview.md](./ingress/overview.md)
- Gateway API: [gateway_api/definitions_and_concepts.md](./gateway_api/definitions_and_concepts.md)
- Private CA: [Private_CA/index.md](./Private_CA/index.md)
- Troubleshooting: [Administration/troubleshooting.md](./Administration/troubleshooting.md)

---

## Basic Concepts

### CRD cert-manager

Cert-manager расширяет Kubernetes API через Custom Resource Definitions:

#### Источники сертификатов (Issuers)

| Ресурс | Область | Описание |
| :--- | :--- | :--- |
| **`Issuer`** | Namespace | Представляет CA в рамках одного namespace |
| **`ClusterIssuer`** | Кластер | Общекластерный ресурс, доступен из любого namespace |

#### Типы Issuer

| Тип | Описание | Сценарий |
| :--- | :--- | :--- |
| `acme` | ACME-протокол (Let's Encrypt) | Публичные сертификаты |
| `ca` | Существующий CA в Secret | Внутренние PKI |
| `selfSigned` | Самоподписанные сертификаты | Тестирование, корневые CA |
| `vault` | HashiCorp Vault | Интеграция с Vault PKI |
| `venafi` | Venafi Cloud/TPE | Корпоративные PKI |
| `external` | Внешние webhook-провайдеры | Кастомные интеграции |

#### Ресурсы сертификатов

| Ресурс | Описание |
| :--- | :--- |
| **`Certificate`** | Декларативный запрос сертификата. Cert-manager создаёт/обновляет Secret с сертификатом |
| **`CertificateRequest`** | Внутренний ресурс, представляет CSR. Не для прямого использования |
| **`Order`** | ACME-заказ (только ACME-Issuer). Содержит информацию о заказе |
| **`Challenge`** | ACME-проверка владения доменом (HTTP-01, DNS-01, TLS-ALPN-01) |

### Поток ACME-запроса

```
Certificate → Order → Challenge(s) → CertificateRequest → Secret
```

1. Пользователь создаёт `Certificate`
2. Cert-manager создаёт `Order` для ACME-сервера
3. Для каждого домена создаётся `Challenge` (проверка владения)
4. После проверок создаётся `CertificateRequest`
5. При успехе сертификат сохраняется в `Secret`

Подробное описание ACME: [LetsEncrypt/index.md](./LetsEncrypt/index.md).

### Структура ресурса Certificate

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: default
spec:
  # Целевой Secret
  secretName: example-com-tls

  # Срок действия и продление
  duration: 2160h          # 90 дней (по умолчанию)
  renewBefore: 360h        # 15 дней до истечения (по умолчанию)

  # Доменные имена
  dnsNames:
    - example.com
    - www.example.com
  ipAddresses:
    - 192.168.1.1

  # Ссылка на Issuer
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
    group: cert-manager.io

  # Дополнительные параметры
  isCA: false                      # true для CA-сертификатов
  commonName: example.com          # CN (опционально)
  privateKey:
    algorithm: RSA                 # RSA, ECDSA
    size: 2048                     # 2048, 4096 (RSA); 256, 384 (ECDSA)
    encoding: PKCS8                # PKCS8, PKCS1 (важно для Java)
  usages:
    - digital signature
    - key encipherment
```

> **Важно:** Для Java-приложений (OpenSearch, Elasticsearch) указывайте `encoding: PKCS8`.

### ACME Solvers (проверки владения)

| Метод | Принцип | Wildcard | Требования | Сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP-01** | Файл по `http://<domain>/.well-known/acme-challenge/` | ❌ | Публичный Ingress | Стандартные сертификаты |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ | DNS API провайдера | Wildcard, без публичного HTTP |
| **TLS-ALPN-01** | TLS-соединение на порт 443 со спец. сертификатом | ❌ | Прямой доступ к 443 | Редко используется |

Подробные примеры настройки solvers: [LetsEncrypt/scenarios](./LetsEncrypt/letsencrypt_scenarios.md).

---

## Practical Scenarios

### Сценарий 1: Базовый сертификат через аннотацию Ingress

**Цель:** Автоматически получить TLS-сертификат для Ingress.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - example.com
      secretName: example-com-tls
  rules:
    - host: example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-service
                port:
                  number: 80
```

> **Устаревшая аннотация:** `kubernetes.io/tls-acme: "true"` — не используйте.

Подробные сценарии Ingress: [ingress/scenarios.md](./ingress/scenarios.md).

### Сценарий 2: Прямое создание Certificate (без аннотаций)

**Цель:** Полный контроль над жизненным циклом сертификата.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-cert
  namespace: production
spec:
  secretName: my-app-tls
  duration: 8760h           # 1 год
  renewBefore: 720h         # 30 дней
  issuerRef:
    name: my-ca-issuer
    kind: Issuer
  dnsNames:
    - my-app.production.svc
    - my-app.production.svc.cluster.local
```

Этот подход используется для внутренних сервисов, mTLS, Private CA. Подробности: [Private_CA/scenarios.md](./Private_CA/scenarios.md).

---

## Additional Information

### Интеграция с другими системами

| Система | Документ | Описание |
| :--- | :--- | :--- |
| **Ingress** | [ingress/overview.md](./ingress/overview.md) | Автоматизация TLS через аннотации |
| **Gateway API** | [gateway_api/definitions_and_concepts.md](./gateway_api/definitions_and_concepts.md) | Поддержка Gateway API (флаг `--enable-gateway-api`) |
| **CA кластера** | [cluster_ca.md](./cluster_ca.md) | Использование CA control plane для внутренних сертификатов |
| **Private CA** | [Private_CA/scenarios.md](./Private_CA/scenarios.md) | Self-signed CA для внутренних сервисов |

### Версии и совместимость

| Версия cert-manager | Мин. K8s | Статус |
| :--- | :--- | :--- |
| **1.20.x** | 1.25 | **Текущая** |
| 1.19.x | 1.25 | Поддерживается |
| 1.18.x | 1.24 | Поддерживается |
| <1.17 | <1.24 | **Устарели** |

> **Проверка актуальности:** [endoflife.date/cert-manager](https://endoflife.date/cert-manager) · [GitHub Releases](https://github.com/cert-manager/cert-manager/releases)

**Проверка установленных версий:**

```bash
kubectl get deployments -n cert-manager -o wide
helm list -n cert-manager
```

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| CRD и API | **10** | Официальная документация cert-manager.io |
| ACME solvers | **10** | RFC 8555, документация Let's Encrypt |
| Gateway API | **9** | Интеграция подтверждена в релизах 1.13+ |
| PKCS8 encoding | **10** | Требуется для Java (OpenSearch, Elasticsearch) |
